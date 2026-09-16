"""SQLite provenance store. One connection per operation, never shared across threads."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import struct
from finance_detective.providers.common import ROOT, now

DB_PATH = ROOT / 'data/processed/rag.sqlite3'
PARSER_VERSION = 'narrative-only-v2'
DIMENSIONS = 512

SCHEMA = '''
CREATE TABLE IF NOT EXISTS documents (
 id TEXT PRIMARY KEY, company_id TEXT NOT NULL, accession TEXT NOT NULL,
 title TEXT NOT NULL, source_url TEXT NOT NULL, period TEXT NOT NULL,
 parser_version TEXT NOT NULL, embedding_model TEXT NOT NULL, dimensions INTEGER NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('queued','indexing','ready','failed')),
 raw_sha256 TEXT, chunk_count INTEGER NOT NULL DEFAULT 0,
 embedded_count INTEGER NOT NULL DEFAULT 0, embedding_tokens INTEGER NOT NULL DEFAULT 0,
 error TEXT, updated_at TEXT NOT NULL,
 UNIQUE(company_id, accession, parser_version, embedding_model, dimensions)
);
CREATE TABLE IF NOT EXISTS chunks (
 id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
 ordinal INTEGER NOT NULL, section TEXT NOT NULL, text TEXT NOT NULL,
 text_sha256 TEXT NOT NULL, UNIQUE(document_id,ordinal)
);
CREATE TABLE IF NOT EXISTS embeddings (
 chunk_id TEXT PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
 vector BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_document ON chunks(document_id,ordinal);
CREATE TABLE IF NOT EXISTS runs (
 id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
 question TEXT NOT NULL, retrieval_json TEXT NOT NULL, response_json TEXT NOT NULL,
 model TEXT NOT NULL, prompt_version TEXT NOT NULL, input_tokens INTEGER NOT NULL,
 output_tokens INTEGER NOT NULL, latency_ms INTEGER NOT NULL,
 status TEXT NOT NULL, created_at TEXT NOT NULL
);
'''

@contextmanager
def connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA journal_mode=WAL')
    conn.executescript(SCHEMA)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def document_id(data, model):
    key = '|'.join([data['company_id'], data['filing']['accession'], PARSER_VERSION, model, str(DIMENSIONS)])
    return hashlib.sha256(key.encode()).hexdigest()[:24]


def get_document(doc_id):
    with connection() as db:
        row = db.execute('SELECT * FROM documents WHERE id=?', (doc_id,)).fetchone()
        return dict(row) if row else None


def queue_document(data, model):
    doc_id = document_id(data, model)
    with connection() as db:
        db.execute('''INSERT INTO documents
            (id,company_id,accession,title,source_url,period,parser_version,embedding_model,dimensions,status,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,'queued',?)
            ON CONFLICT(id) DO UPDATE SET status='queued',error=NULL,updated_at=excluded.updated_at''',
            (doc_id,data['company_id'],data['filing']['accession'],data['company']+' · '+data['filing']['form'],
             data['source_url'],data['filing']['end'],PARSER_VERSION,model,DIMENSIONS,now()))
    return doc_id


def progress(doc_id, status, error=None):
    with connection() as db:
        db.execute('UPDATE documents SET status=?,error=?,updated_at=? WHERE id=?', (status,error,now(),doc_id))


def save_chunks(doc_id, chunks, digest):
    with connection() as db:
        db.execute('DELETE FROM chunks WHERE document_id=?', (doc_id,))
        db.executemany('INSERT INTO chunks VALUES (?,?,?,?,?,?)',
            [(c['id'],doc_id,c['ordinal'],c['section'],c['text'],hashlib.sha256(c['text'].encode()).hexdigest()) for c in chunks])
        db.execute('UPDATE documents SET raw_sha256=?,chunk_count=?,embedded_count=0,embedding_tokens=0,updated_at=? WHERE id=?',
                   (digest,len(chunks),now(),doc_id))


def chunks(doc_id, vectors=False):
    with connection() as db:
        rows = db.execute('''SELECT c.*,e.vector FROM chunks c LEFT JOIN embeddings e ON c.id=e.chunk_id
                             WHERE c.document_id=? ORDER BY ordinal''', (doc_id,)).fetchall()
    result=[]
    for row in rows:
        item=dict(row); raw=item.pop('vector')
        if vectors: item['vector']=list(struct.unpack('<'+str(len(raw)//4)+'f',raw)) if raw else None
        result.append(item)
    return result


def save_vectors(doc_id, batch, vectors, tokens):
    if len(batch)!=len(vectors): raise ValueError('Embedding count mismatch')
    with connection() as db:
        for chunk,vector in zip(batch,vectors):
            if len(vector)!=DIMENSIONS: raise ValueError('Embedding dimension mismatch')
            db.execute('INSERT OR REPLACE INTO embeddings VALUES (?,?)',
                       (chunk['id'],struct.pack('<'+str(DIMENSIONS)+'f',*vector)))
        db.execute('''UPDATE documents SET embedded_count=(SELECT COUNT(*) FROM embeddings e JOIN chunks c ON c.id=e.chunk_id WHERE c.document_id=?),
                      embedding_tokens=embedding_tokens+?,updated_at=? WHERE id=?''', (doc_id,tokens,now(),doc_id))


def save_run(run):
    with connection() as db:
        db.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            (run['id'],run['document_id'],run['question'],json.dumps(run['retrieval'],ensure_ascii=False),
             json.dumps(run['response'],ensure_ascii=False),run['model'],run['prompt_version'],
             run['input_tokens'],run['output_tokens'],run['latency_ms'],run['status'],now()))
