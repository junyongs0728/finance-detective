"""PostgreSQL provenance storage and exact pgvector retrieval (no SQLite runtime)."""
from contextlib import contextmanager
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import threading

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg import sql
from psycopg_pool import ConnectionPool, PoolTimeout
from finance_detective.providers.common import setting, ProviderError

PARSER_VERSION='narrative-only-v2'
DIMENSIONS=512
_POOL_LOCK=threading.Lock()

@lru_cache(maxsize=1)
def _pool(dsn):
    return ConnectionPool(dsn,min_size=0,max_size=12,timeout=10,open=True,
        kwargs={'row_factory':dict_row,'autocommit':True,'connect_timeout':5,
                'options':'-c timezone=UTC -c statement_timeout=15000'},
        check=ConnectionPool.check_connection)


def pool():
    dsn=setting('DATABASE_URL')
    if not dsn:raise ProviderError('PostgreSQL 설정이 없습니다. 로컬 환경 설정을 먼저 실행해주세요.','database_unavailable')
    with _POOL_LOCK:return _pool(dsn)


def close():
    if _pool.cache_info().currsize:
        pool().close()
        _pool.cache_clear()


@contextmanager
def connection():
    try:
        with pool().connection() as db:
            with db.transaction():
                schema=setting('DATABASE_SCHEMA')
                if schema:db.execute(sql.SQL('SET LOCAL search_path TO {},public').format(sql.Identifier(schema)))
                yield db
    except (psycopg.OperationalError,PoolTimeout):
        raise ProviderError('PostgreSQL에 연결하지 못했습니다. 데이터베이스 실행 상태를 확인해주세요.','database_unavailable') from None


def initialize():
    with connection() as db:
        db.execute('SELECT pg_advisory_xact_lock(72016001)')
        db.execute((Path(__file__).with_name('schema.sql')).read_text(),prepare=False)


@contextmanager
def exclusive(key):
    """Session lock spans network calls without keeping an SQL transaction open."""
    number=int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], 'big',signed=True)
    with pool().connection() as db:
        acquired=db.execute('SELECT pg_try_advisory_lock(%s) AS acquired',(number,)).fetchone()['acquired']
        try:yield acquired
        finally:
            if acquired:db.execute('SELECT pg_advisory_unlock(%s)',(number,))


def document_id(data,model):
    key='|'.join([data['company_id'],data['filing']['accession'],PARSER_VERSION,model,str(DIMENSIONS)])
    return hashlib.sha256(key.encode()).hexdigest()[:24]


def get_document(doc_id):
    with connection() as db:return db.execute('SELECT * FROM documents WHERE id=%s',(doc_id,)).fetchone()


def queue_document(data,model):
    did=document_id(data,model)
    with connection() as db:
        db.execute('''INSERT INTO documents
          (id,company_id,accession,title,source_url,period,parser_version,embedding_model,dimensions,status)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'queued')
          ON CONFLICT(id) DO UPDATE SET status=CASE WHEN documents.status IN ('ready','indexing')
          THEN documents.status ELSE 'queued' END,error=NULL,updated_at=now()''',
          (did,data['company_id'],data['filing']['accession'],data['company']+' · '+data['filing']['form'],
           data['source_url'],data['filing']['end'],PARSER_VERSION,model,DIMENSIONS))
    return did


def progress(did,status,error=None):
    with connection() as db:db.execute('UPDATE documents SET status=%s,error=%s,updated_at=now() WHERE id=%s',(status,error,did))


def save_chunks(did,items,digest):
    with connection() as db:
        db.execute('DELETE FROM chunks WHERE document_id=%s',(did,))
        with db.cursor() as cur:
            cur.executemany('INSERT INTO chunks VALUES(%s,%s,%s,%s,%s,%s)',
                [(c['id'],did,c['ordinal'],c['section'],c['text'],hashlib.sha256(c['text'].encode()).hexdigest()) for c in items])
        db.execute('UPDATE documents SET raw_sha256=%s,chunk_count=%s,embedded_count=0,embedding_tokens=0,updated_at=now() WHERE id=%s',
                   (digest,len(items),did))


def vector_literal(vector):
    if len(vector)!=DIMENSIONS or not all(math.isfinite(x) for x in vector):raise ValueError('Invalid embedding dimensions or values')
    return json.dumps([float(x) for x in vector])


def chunks(did,vectors=False):
    with connection() as db:
        rows=db.execute('''SELECT c.*,e.vector::text AS vector FROM chunks c LEFT JOIN embeddings e ON c.id=e.chunk_id
            WHERE c.document_id=%s ORDER BY ordinal''',(did,)).fetchall()
    for row in rows:
        raw=row.pop('vector')
        if vectors:row['vector']=json.loads(raw) if raw else None
    return rows


def dense_rank(did,vector,limit=30):
    # No approximate index: exact ranking within the selected filing.
    with connection() as db:
        rows=db.execute('''SELECT c.id,1-(e.vector <=> %s::public.vector) AS score
            FROM chunks c JOIN embeddings e ON c.id=e.chunk_id WHERE c.document_id=%s
            ORDER BY e.vector <=> %s::public.vector,c.id LIMIT %s''',
            (vector_literal(vector),did,vector_literal(vector),limit)).fetchall()
    return [(r['id'],r['score']) for r in rows]


def save_vectors(did,batch,vectors,tokens):
    if len(batch)!=len(vectors):raise ValueError('Embedding count mismatch')
    with connection() as db:
        for chunk,vector in zip(batch,vectors):
            row=db.execute('SELECT document_id FROM chunks WHERE id=%s',(chunk['id'],)).fetchone()
            if not row or row['document_id']!=did:raise ValueError('Cross-document embedding')
            db.execute('INSERT INTO embeddings VALUES(%s,%s::public.vector) ON CONFLICT(chunk_id) DO UPDATE SET vector=excluded.vector',
                       (chunk['id'],vector_literal(vector)))
        db.execute('''UPDATE documents SET embedded_count=(SELECT COUNT(*) FROM embeddings e JOIN chunks c ON c.id=e.chunk_id WHERE c.document_id=%s),
            embedding_tokens=embedding_tokens+%s,updated_at=now() WHERE id=%s''',(did,tokens,did))


def save_run(run):
    with connection() as db:
        db.execute('''INSERT INTO runs(id,document_id,question,retrieval_json,response_json,model,prompt_version,
            input_tokens,output_tokens,latency_ms,status,request_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
            (run['id'],run['document_id'],run['question'],Jsonb(run['retrieval']),Jsonb(run['response']),run['model'],
             run['prompt_version'],run['input_tokens'],run['output_tokens'],run['latency_ms'],run['status'],run.get('request_id')))


def cached(key,user_id):
    with connection() as db:
        row=db.execute('SELECT response,created_at FROM answer_cache WHERE key=%s AND user_id=%s AND expires_at>now()',
                       (key,user_id)).fetchone()
    return row


def cache_answer(key,user_id,did,response,ttl):
    with connection() as db:
        db.execute('''INSERT INTO answer_cache(key,user_id,document_id,response,expires_at)
            VALUES(%s,%s,%s,%s,now()+(%s * interval '1 second'))
            ON CONFLICT(key) DO UPDATE SET response=excluded.response,created_at=now(),expires_at=excluded.expires_at''',
            (key,user_id,did,Jsonb(response),ttl))
