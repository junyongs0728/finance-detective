"""Deterministic identities and provenance: narrative proximity is not numeric support."""
import hashlib
import json
from finance_detective.providers.common import ProviderError

VERSION = 'financial-evidence-v1'
METRICS = {'revenue': '매출', 'operating_income': '영업이익', 'operating_cash_flow': '영업현금흐름'}
KINDS = {'Company', 'Filing', 'Period', 'Observation', 'Metric', 'Evidence'}
RELATIONS = {'FILED', 'REPORTS', 'FOR_PERIOD', 'MEASURES', 'SUPPORTED_BY', 'CONTAINS'}


def identity(kind, *parts):
    raw=json.dumps(parts,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    return kind.lower()+':'+hashlib.sha256(raw.encode()).hexdigest()[:24]


def observations(data):
    result=[]; seen=set()
    for record in data['records']:
        if record['metric'] not in METRICS: continue
        if type(record['value']) is not int or record['unit']!=data['currency']:
            raise ProviderError('수치의 값 또는 통화가 일치하지 않습니다.','observation_invalid')
        if record['accession']!=data['filing']['accession'] or record['source_url']!=data['source_url']:
            raise ProviderError('선택 공시와 수치의 출처가 다릅니다.','observation_invalid')
        scope=record['scope']
        key=(record['metric'],record['period_label'],record.get('start'),record.get('end'),scope,record['unit'])
        if key in seen: raise ProviderError('같은 기간의 재무 관측값이 중복되었습니다.','observation_invalid')
        seen.add(key)
        value={**record,'company_id':data['company_id'],'currency':record['unit'],
               'metric_label':METRICS[record['metric']], 'value':str(record['value'])}
        # Include the value/tag so corrected facts get new immutable identities.
        value['id']=identity('observation',data['company_id'],record['accession'],key,record['value'],record.get('tag'))
        result.append(value)
    return sorted(result,key=lambda r:(r['year'],r['metric'],r['id']))


def build_snapshot(data, document, evidence=()):
    items=observations(data)
    nodes={}; edges=[]
    def node(kind,nid,label,**props):
        nodes[nid]={'id':nid,'kind':kind,'label':label,
                    'properties':{k:v for k,v in props.items() if v is not None}}
        return nid
    def edge(source,relationship,target):
        edges.append({'source':source,'type':relationship,'target':target})
    cid=node('Company',data['company_id'],data['company'],provider=data['provider'],ticker=data['ticker'])
    fid=node('Filing',identity('filing',cid,data['filing']['accession']),data['filing']['form'],
             accession=data['filing']['accession'],source_url=data['source_url'],report_period=data['filing']['end'])
    edge(cid,'FILED',fid)
    for item in items:
        oid=node('Observation',item['id'],f"{item['period_label']} {item['metric_label']}",
                 value=item['value'],currency=item['currency'],unit=item['unit'],scope=item['scope'],
                 year=item['year'],metric=item['metric'],period_label=item['period_label'],
                 start=item.get('start'),end=item.get('end'),company_id=cid)
        mid=node('Metric',identity('metric',item['metric']),item['metric_label'],key=item['metric'])
        pid=node('Period',identity('period',cid,item['period_label'],item.get('start'),item.get('end')),
                 item['period_label'],year=item['year'],start=item.get('start'),end=item.get('end'),basis=data['period_basis'])
        # XBRL/structured provider facts support numbers. A narrative paragraph is NOT
        # linked with SUPPORTED_BY merely because it mentions the same metric.
        eid=node('Evidence',identity('fact',oid),'재무 API 원본 항목',evidence_kind='structured_fact',
                 text=f"{item['tag']} | {item['period_label']} | {item['value']} {item['unit']} | {item['scope']}",
                 source_url=item['source_url'],tag=item.get('tag'),raw_sha256=data.get('raw_sha256'))
        for a,r,b in [(fid,'REPORTS',oid),(oid,'MEASURES',mid),(oid,'FOR_PERIOD',pid),
                      (oid,'SUPPORTED_BY',eid),(fid,'CONTAINS',eid)]: edge(a,r,b)
    for chunk in evidence:
        if chunk['document_id']!=document['id'] or document['company_id']!=cid or document['accession']!=data['filing']['accession']:
            raise ProviderError('다른 공시의 근거를 Graph에 연결할 수 없습니다.','graph_scope_invalid')
        eid=node('Evidence',identity('chunk',chunk['id']),'공시 문단 '+str(chunk['ordinal']),
                 evidence_kind='narrative_chunk',text=chunk['text'],section=chunk['section'],
                 chunk_id=chunk['id'],ordinal=chunk['ordinal'],source_url=data['source_url'],
                 document_id=document['id'],raw_sha256=document.get('raw_sha256'))
        edge(fid,'CONTAINS',eid)
    payload={'ontology_version':VERSION,'company_id':cid,'accession':data['filing']['accession'],
             'nodes':sorted(nodes.values(),key=lambda n:n['id']),
             'edges':sorted(edges,key=lambda e:(e['source'],e['type'],e['target']))}
    return {'id':identity('snapshot',payload),**payload}
