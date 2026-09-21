"""Fixed, parameterized Cypher only. Model text never becomes executable Cypher."""
from functools import lru_cache
from contextlib import contextmanager
from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError, DriverError
from psycopg.types.json import Jsonb
from finance_detective.providers.common import setting, ProviderError
from finance_detective.rag import store
from .ontology import KINDS, RELATIONS


def namespace():
    return setting('DATABASE_SCHEMA') or 'finance_detective'


@lru_cache(maxsize=1)
def _driver(uri,user,password):
    return GraphDatabase.driver(uri,auth=(user,password),connection_timeout=5,
        connection_acquisition_timeout=5,max_transaction_retry_time=0,max_connection_pool_size=8)


def driver():
    if not setting('NEO4J_URI') or not setting('NEO4J_PASSWORD'):
        raise ProviderError('근거 관계 탐색에는 Neo4j 설정이 필요합니다.','graph_unavailable')
    return _driver(setting('NEO4J_URI'),setting('NEO4J_USERNAME') or 'neo4j',setting('NEO4J_PASSWORD'))


def close():
    if _driver.cache_info().currsize:
        driver().close(); _driver.cache_clear()


@contextmanager
def session():
    try:
        with driver().session(database=setting('NEO4J_DATABASE') or 'neo4j') as db: yield db
    except (Neo4jError,DriverError,OSError):
        raise ProviderError('Neo4j 근거 관계 저장소에 연결하지 못했습니다. 관계 탐색은 잠시 사용할 수 없습니다.','graph_unavailable') from None


def persist(snapshot):
    with store.connection() as db:
        db.execute('''INSERT INTO knowledge_snapshots(id,company_id,accession,ontology_version,payload)
          VALUES(%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING''',
          (snapshot['id'],snapshot['company_id'],snapshot['accession'],snapshot['ontology_version'],Jsonb(snapshot)))


def load(snapshot_id):
    with store.connection() as db:
        row=db.execute('SELECT payload FROM knowledge_snapshots WHERE id=%s',(snapshot_id,)).fetchone()
    if not row: raise ProviderError('저장된 근거 관계를 찾지 못했습니다.','not_found')
    return row['payload']


def project(snapshot):
    """SQL commit first; one Neo4j transaction; safe to repeat after partial failure."""
    if any(n['kind'] not in KINDS for n in snapshot['nodes']) or any(e['type'] not in RELATIONS for e in snapshot['edges']):
        raise ValueError('Unknown ontology type')
    persist(snapshot)
    ns=namespace(); sid=snapshot['id']
    with session() as db:
        db.run('CREATE CONSTRAINT fd_identity IF NOT EXISTS FOR (n:FDNode) REQUIRE (n.namespace,n.id) IS UNIQUE').consume()
        with db.begin_transaction(timeout=15) as tx:
            for kind in sorted(KINDS):
                rows=[{'id':n['id'],'label':n['label'],**n['properties']} for n in snapshot['nodes'] if n['kind']==kind]
                # Labels come from the code-owned finite ontology, never from user/LLM input.
                tx.run(f'''UNWIND $rows AS row MERGE (n:FDNode:{kind} {{namespace:$ns,id:row.id}})
                    SET n += row, n.kind=$kind''',rows=rows,ns=ns,kind=kind).consume()
            for relationship in sorted(RELATIONS):
                rows=[e for e in snapshot['edges'] if e['type']==relationship]
                tx.run(f'''UNWIND $rows AS row MATCH (a:FDNode {{namespace:$ns,id:row.source}}),
                    (b:FDNode {{namespace:$ns,id:row.target}})
                    MERGE (a)-[r:{relationship} {{snapshot_id:$sid,namespace:$ns}}]->(b)''',rows=rows,ns=ns,sid=sid).consume()
            tx.commit()
    with store.connection() as db: db.execute('UPDATE knowledge_snapshots SET projected_at=now() WHERE id=%s',(sid,))


def read(snapshot_id):
    expected=load(snapshot_id)
    with session() as db:
        records=list(db.run('''MATCH (a:FDNode {namespace:$ns})-[r]->(b:FDNode {namespace:$ns})
           WHERE r.snapshot_id=$sid AND r.namespace=$ns
           RETURN properties(a) AS a,type(r) AS type,properties(b) AS b''',ns=namespace(),sid=snapshot_id))
    nodes={}; edges=[]
    for row in records:
        for key in ('a','b'):
            props=dict(row[key]); nid=props.pop('id'); kind=props.pop('kind'); label=props.pop('label'); props.pop('namespace')
            nodes[nid]={'id':nid,'kind':kind,'label':label,'properties':props}
        edges.append({'source':row['a']['id'],'type':row['type'],'target':row['b']['id']})
    actual_nodes=sorted(nodes.values(),key=lambda n:n['id']); actual_edges=sorted(edges,key=lambda e:(e['source'],e['type'],e['target']))
    if actual_nodes!=expected['nodes'] or actual_edges!=expected['edges']:
        raise ProviderError('SQL 원본과 Graph 투영 결과가 달라 근거 관계를 표시하지 않았습니다.','graph_projection_mismatch')
    return {**expected,'nodes':actual_nodes,'edges':actual_edges,'engine':'neo4j','verified_against_sql':True}


def trace(snapshot_id, observation_ids):
    expected=load(snapshot_id); allowed={n['id'] for n in expected['nodes'] if n['kind']=='Observation'}
    if not observation_ids or set(observation_ids)-allowed:
        raise ProviderError('선택 기업·공시에 속하지 않는 수치입니다.','graph_scope_invalid')
    with session() as db:
        rows=list(db.run('''MATCH (f:Filing {namespace:$ns})-[a:REPORTS]->(o:Observation {namespace:$ns})
           -[b:SUPPORTED_BY]->(e:Evidence {namespace:$ns}),
           (o)-[c:FOR_PERIOD]->(p:Period {namespace:$ns})
           WHERE o.id IN $ids AND all(rel IN [a,b,c] WHERE rel.snapshot_id=$sid AND rel.namespace=$ns)
           RETURN o.id AS observation_id,o.value AS value,o.currency AS currency,o.scope AS scope,
             p.label AS period,f.id AS filing_id,f.accession AS accession,e.id AS evidence_id,
             e.text AS evidence,e.evidence_kind AS evidence_kind,e.source_url AS source_url ORDER BY observation_id''',
           ns=namespace(),sid=snapshot_id,ids=observation_ids))
    if {r['observation_id'] for r in rows}!=set(observation_ids):
        raise ProviderError('일부 수치의 원문 근거 관계를 찾지 못했습니다.','graph_projection_mismatch')
    authoritative={n['id']:n for n in expected['nodes']}
    expected_paths=[]
    for oid in sorted(set(observation_ids)):
        eid=next(e['target'] for e in expected['edges'] if e['source']==oid and e['type']=='SUPPORTED_BY')
        pid=next(e['target'] for e in expected['edges'] if e['source']==oid and e['type']=='FOR_PERIOD')
        fid=next(e['source'] for e in expected['edges'] if e['target']==oid and e['type']=='REPORTS')
        o=authoritative[oid]['properties']; e=authoritative[eid]['properties']; f=authoritative[fid]['properties']
        expected_paths.append({'observation_id':oid,'value':o['value'],'currency':o['currency'],'scope':o['scope'],
            'period':authoritative[pid]['label'],'filing_id':fid,'accession':f['accession'],'evidence_id':eid,
            'evidence':e['text'],'evidence_kind':e['evidence_kind'],'source_url':e['source_url']})
    actual=[dict(r) for r in rows]
    if actual!=expected_paths:
        raise ProviderError('Graph와 원본 수치·기간·출처 경로가 일치하지 않습니다.','graph_projection_mismatch')
    return actual
