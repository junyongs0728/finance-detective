CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;
CREATE TABLE IF NOT EXISTS schema_migrations (version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS documents (
 id text PRIMARY KEY, company_id text NOT NULL, accession text NOT NULL,
 title text NOT NULL, source_url text NOT NULL, period text NOT NULL,
 parser_version text NOT NULL, embedding_model text NOT NULL, dimensions integer NOT NULL CHECK(dimensions=512),
 status text NOT NULL CHECK(status IN ('queued','indexing','ready','failed')),
 raw_sha256 text, chunk_count integer NOT NULL DEFAULT 0, embedded_count integer NOT NULL DEFAULT 0,
 embedding_tokens bigint NOT NULL DEFAULT 0, error text, updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(company_id,accession,parser_version,embedding_model,dimensions)
);
CREATE TABLE IF NOT EXISTS chunks (
 id text PRIMARY KEY, document_id text NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
 ordinal integer NOT NULL, section text NOT NULL, text text NOT NULL, text_sha256 text NOT NULL,
 UNIQUE(document_id,ordinal)
);
CREATE INDEX IF NOT EXISTS chunks_document ON chunks(document_id,ordinal);
CREATE TABLE IF NOT EXISTS embeddings (
 chunk_id text PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
 vector public.vector(512) NOT NULL
);
-- Exact pgvector search is intentional: an ANN index changes retrieval recall.
CREATE TABLE IF NOT EXISTS runs (
 id text PRIMARY KEY, document_id text NOT NULL REFERENCES documents(id), question text NOT NULL,
 retrieval_json jsonb NOT NULL, response_json jsonb NOT NULL, model text NOT NULL, prompt_version text NOT NULL,
 input_tokens bigint NOT NULL, output_tokens bigint NOT NULL, latency_ms integer NOT NULL,
 status text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS ai_users (
 id text PRIMARY KEY, token_hash text UNIQUE, disabled boolean NOT NULL DEFAULT false,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS ai_requests (
 id text PRIMARY KEY, user_id text NOT NULL REFERENCES ai_users(id), kind text NOT NULL,
 status text NOT NULL DEFAULT 'active' CHECK(status IN ('active','completed','failed')),
 created_at timestamptz NOT NULL DEFAULT now(), ended_at timestamptz
);
CREATE INDEX IF NOT EXISTS ai_requests_user_time ON ai_requests(user_id,created_at);
CREATE TABLE IF NOT EXISTS ai_calls (
 id text PRIMARY KEY, request_id text NOT NULL REFERENCES ai_requests(id), user_id text NOT NULL REFERENCES ai_users(id),
 stage text NOT NULL, model text NOT NULL, resolved_model text, provider_response_id text,
 status text NOT NULL DEFAULT 'reserved' CHECK(status IN ('reserved','completed','uncertain','rejected')),
 reserved_microusd bigint NOT NULL CHECK(reserved_microusd>=0), actual_microusd bigint CHECK(actual_microusd>=0),
 input_tokens bigint, output_tokens bigint, cached_input_tokens bigint,
 price_version text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz
);
CREATE INDEX IF NOT EXISTS ai_calls_time ON ai_calls(created_at);
CREATE INDEX IF NOT EXISTS ai_calls_user_time ON ai_calls(user_id,created_at);
ALTER TABLE runs ADD COLUMN IF NOT EXISTS request_id text REFERENCES ai_requests(id);
CREATE TABLE IF NOT EXISTS answer_cache (
 key text PRIMARY KEY, user_id text NOT NULL REFERENCES ai_users(id), document_id text NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
 response jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS answer_cache_expiry ON answer_cache(expires_at);
INSERT INTO schema_migrations(version) VALUES(1) ON CONFLICT DO NOTHING;

-- PostgreSQL is the source of truth; Neo4j is a rebuildable relationship projection.
CREATE TABLE IF NOT EXISTS knowledge_snapshots (
 id text PRIMARY KEY, company_id text NOT NULL, accession text NOT NULL,
 ontology_version text NOT NULL, payload jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), projected_at timestamptz
);
CREATE INDEX IF NOT EXISTS knowledge_company ON knowledge_snapshots(company_id,created_at);
CREATE TABLE IF NOT EXISTS agent_runs (
 id text PRIMARY KEY, user_id text NOT NULL REFERENCES ai_users(id),
 request_id text NOT NULL REFERENCES ai_requests(id),
 document_id text NOT NULL REFERENCES documents(id), snapshot_id text REFERENCES knowledge_snapshots(id),
 question text NOT NULL, model text NOT NULL, prompt_version text NOT NULL,
 status text NOT NULL, trace jsonb NOT NULL, response jsonb NOT NULL,
 latency_ms integer NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO schema_migrations(version) VALUES(2) ON CONFLICT DO NOTHING;
