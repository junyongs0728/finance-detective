import uuid
import pytest
from psycopg import sql
from finance_detective.rag import store, billing

@pytest.fixture(autouse=True)
def anonymous_http_mode(monkeypatch):
    # Numeric/route tests do not depend on a local developer authentication bypass.
    monkeypatch.setenv('AI_AUTH_MODE','token')

@pytest.fixture
def database(monkeypatch):
    """Actual PostgreSQL, isolated schema; no SQLite stand-in and no paid API calls."""
    schema='fd_test_'+uuid.uuid4().hex
    with store.connection() as db:db.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    monkeypatch.setenv('DATABASE_SCHEMA',schema)
    for key,value in billing.DEFAULTS.items():monkeypatch.setenv(key,value)
    store.initialize()
    try:
        with billing.as_user('local-owner'):yield
    finally:
        monkeypatch.delenv('DATABASE_SCHEMA')
        with store.connection() as db:db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))

@pytest.fixture(scope='session',autouse=True)
def close_database_pool():
    yield
    store.close()
