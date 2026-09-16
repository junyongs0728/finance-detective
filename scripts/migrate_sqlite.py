"""One-way, idempotent SQLite import. Preserve the original and verify every imported row."""
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import struct
import sys
from psycopg import sql
from psycopg.types.json import Jsonb
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from finance_detective.rag import store


def migrate(source):
    store.initialize()
    # SQLite backup API captures a consistent snapshot including committed WAL data.
    with sqlite3.connect(f'file:{source}?mode=ro',uri=True) as original:
        snapshot=sqlite3.connect(':memory:')
        original.backup(snapshot)
    snapshot.row_factory=sqlite3.Row
    counts={}
    with store.connection() as db:
        db.execute('SELECT pg_advisory_xact_lock(72016003)')
        for table in ('documents','chunks','embeddings','runs'):
            rows=snapshot.execute(f'SELECT * FROM {table}').fetchall()
            counts[table]=len(rows)
            for row in rows:
                value=dict(row)
                if table=='embeddings':
                    v=value['vector'];value['vector']=store.vector_literal(struct.unpack('<'+'f'*(len(v)//4),v))
                if table=='runs':
                    value['retrieval_json']=Jsonb(json.loads(value['retrieval_json']))
                    value['response_json']=Jsonb(json.loads(value['response_json']))
                cols=list(value)
                placeholders=[sql.SQL('%s::public.vector') if table=='embeddings' and c=='vector' else sql.Placeholder() for c in cols]
                query=sql.SQL('INSERT INTO {} ({}) VALUES ({}) ON CONFLICT DO NOTHING').format(
                    sql.Identifier(table),sql.SQL(',').join(map(sql.Identifier,cols)),sql.SQL(',').join(placeholders))
                db.execute(query,list(value.values()))
                pk='chunk_id' if table=='embeddings' else 'id'
                check=db.execute(sql.SQL('SELECT * FROM {} WHERE {}=%s').format(sql.Identifier(table),sql.Identifier(pk)),(value[pk],)).fetchone()
                for col,expected in dict(row).items():
                    actual=check[col]
                    if col=='vector':
                        # pgvector's shortest decimal representation must round-trip to the same float32 bytes.
                        floats=json.loads(actual)
                        if struct.pack('<'+'f'*len(floats),*floats)!=expected:raise ValueError('Vector migration mismatch')
                    elif col in ('retrieval_json','response_json'):
                        if actual!=json.loads(expected):raise ValueError('JSON migration mismatch')
                    elif isinstance(actual,datetime):
                        if actual!=datetime.fromisoformat(expected):raise ValueError('Timestamp migration mismatch')
                    elif actual!=expected:raise ValueError(f'Migration mismatch: {table}.{col}')
    snapshot.close()
    return counts


if __name__=='__main__':
    source=ROOT/'data/processed/rag.sqlite3'
    if not source.exists():raise SystemExit('No legacy SQLite file; initialize a fresh database instead.')
    print(json.dumps({'verified':migrate(source),'embedding_api_calls':0,'original_preserved':True}))
    store.close()
