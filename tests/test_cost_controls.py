"""Real PostgreSQL concurrency + fake model transport: no OpenAI charges."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import json
import threading
from types import SimpleNamespace as NS
import pytest
from fastapi.testclient import TestClient
from finance_detective.main import app
from finance_detective import auth, main
from finance_detective.rag import billing, store, llm, service
from finance_detective.providers.common import ProviderError


def create_user(name,token=None):
    with store.connection() as db:
        db.execute('INSERT INTO ai_users(id,token_hash) VALUES(%s,%s)',
                   (name,hashlib.sha256(token.encode()).hexdigest() if token else None))


def prepared():
    data={'company_id':'SEC:FIX','company':'Fixture','currency':'USD','scope':'consolidated','period_basis':'annual',
          'source_url':'https://www.sec.gov/Archives/edgar/data/1/report.htm',
          'filing':{'accession':'fixture-2025','form':'10-K','end':'2025-12-31'}}
    did=store.queue_document(data,llm.embedding_model())
    chunks=[{'id':did+':1','ordinal':1,'section':'Business','text':'The company sells hardware and provides software services.'}]
    store.save_chunks(did,chunks,'fixture-sha')
    store.save_vectors(did,chunks,[[1.]+[0.]*511],10)
    store.progress(did,'ready')
    return data


@pytest.fixture
def fake_api(monkeypatch):
    calls=[]
    def embeddings(**kwargs):
        calls.append('embedding')
        return NS(data=[NS(index=i,embedding=[1.]+[0.]*511) for i in range(len(kwargs['input']))],usage=NS(total_tokens=12),model=kwargs['model'])
    def response(**kwargs):
        kind=kwargs['text']['format']['name'];calls.append(kind)
        if kind=='financial_grounded_answer':
            chunk=json.loads(kwargs['input'])['evidence'][0]
            output={'status':'answered','claims':[{'text':'하드웨어와 소프트웨어 서비스를 제공합니다.',
                'citations':[{'evidence_id':chunk['id'],'span_id':chunk['spans'][0]['id']}]}],'limitations':''}
        else:output={'supported':True,'issues':[]}
        return NS(id='fixture-response',status='completed',output_text=json.dumps(output),model=kwargs['model'],
                  usage=NS(input_tokens=100,output_tokens=20,input_tokens_details=NS(cached_tokens=10)))
    @contextmanager
    def client():yield NS(embeddings=NS(create=embeddings),responses=NS(create=response))
    monkeypatch.setattr(llm,'client',client)
    monkeypatch.setenv('OPENAI_API_KEY','fixture-not-a-real-key')
    monkeypatch.setenv('OPENAI_MODEL','gpt-4.1-mini')
    monkeypatch.setenv('OPENAI_REVIEW_MODEL','gpt-4.1')
    monkeypatch.setenv('OPENAI_EMBEDDING_MODEL','text-embedding-3-small')
    return calls


def test_price_uses_model_and_cached_input():
    assert billing.price('gpt-4.1-mini',1000,100,200)==500
    assert billing.price('gpt-4.1',1000,100,200)==2500
    with pytest.raises(ProviderError):billing.price('unpriced-model',1)


def test_budget_blocks_before_transport(database,monkeypatch,fake_api):
    monkeypatch.setenv('AI_DAILY_BUDGET_USD','0')
    with billing.operation('answer'):
        with pytest.raises(ProviderError) as error:llm.embed(['test'])
    assert error.value.code=='ai_budget_exceeded' and fake_api==[]
    with store.connection() as db:assert db.execute('SELECT count(*) AS n FROM ai_calls').fetchone()['n']==0


def test_concurrent_users_cannot_overspend(database,monkeypatch):
    monkeypatch.setenv('AI_DAILY_BUDGET_USD','0.001')
    create_user('a');create_user('b');barrier=threading.Barrier(2)
    def request(user):
        with billing.as_user(user),billing.operation('answer'):
            barrier.wait(timeout=5)
            try:return billing.reserve('generate','gpt-4.1-mini',1500)
            except ProviderError as exc:return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(request,['a','b']))
    assert results.count('ai_budget_exceeded')==1
    with store.connection() as db:
        assert db.execute('SELECT sum(reserved_microusd) AS n FROM ai_calls').fetchone()['n']==600


def test_timeout_holds_budget_rejected_call_releases(database):
    with billing.operation('answer'):
        first=billing.reserve('generate','gpt-4.1-mini',1000)
        billing.failed(first)
        second=billing.reserve('generate','gpt-4.1-mini',1000)
        billing.failed(second,rejected=True)
    usage=billing.usage('local-owner')
    assert usage['daily_used_usd']==0.0004 and usage['held_usd']==0.0004


def test_settlement_is_idempotence_guarded(database):
    with billing.operation('answer'):
        cid=billing.reserve('generate','gpt-4.1-mini',1000,100)
        billing.settle(cid,'gpt-4.1-mini',100,20,10)
        with pytest.raises(ValueError):billing.settle(cid,'gpt-4.1-mini',100,20,10)
    assert billing.usage('local-owner')['daily_used_usd']==0.000069


def test_limits_cover_user_request_and_month(database,monkeypatch):
    for field in ('AI_USER_DAILY_BUDGET_USD','AI_REQUEST_BUDGET_USD','AI_MONTHLY_BUDGET_USD'):
        monkeypatch.setenv(field,'0')
        with billing.operation('answer'):
            with pytest.raises(ProviderError):billing.reserve('generate','gpt-4.1-mini',10)
        monkeypatch.setenv(field,billing.DEFAULTS[field])
    monkeypatch.setenv('AI_USER_DAILY_REQUESTS','3')
    with pytest.raises(ProviderError) as error:
        with billing.operation('answer'):pass
    assert error.value.code=='ai_user_limit'


def test_one_active_operation_per_user(database):
    with billing.operation('answer'):
        with pytest.raises(ProviderError) as error:
            with billing.operation('answer'):pass
    assert error.value.code=='ai_busy'


def test_model_usage_cache_and_expiry(database,fake_api,monkeypatch):
    data=prepared()
    first=service.answer('사업 설명',data,[])
    assert first['status']=='answered' and len(fake_api)==3
    assert [c['stage'] for c in first['billing']['calls']]==['embedding','generate','review']
    assert first['billing']['estimated_usd']>0
    second=service.answer('사업   설명',data,[])
    assert len(fake_api)==3 and second['billing']['cached'] and second['billing']['estimated_usd']==0
    assert second['trace']['input_tokens']==0
    monkeypatch.setenv('AI_USER_DAILY_REQUESTS','1')
    assert service.answer('사업 설명',data,[])['billing']['cached']
    with store.connection() as db:db.execute("UPDATE answer_cache SET expires_at=now()-interval '1 second'")
    with pytest.raises(ProviderError):service.answer('사업 설명',data,[])
    assert len(fake_api)==3


def test_cache_scope_changes_with_user_doc_prompt_and_numeric_context(database,fake_api,monkeypatch):
    data=prepared();doc=store.get_document(store.document_id(data,llm.embedding_model()))
    key=service.cache_key('사업 설명',data,[],doc)
    assert key!=service.cache_key('사업 설명',data,[{'year':2024}],doc)
    assert key!=service.cache_key('사업 설명',data,[],{**doc,'id':'another-filing'})
    assert key!=service.cache_key('사업 설명',data,[],{**doc,'raw_sha256':'new-source'})
    with billing.as_user('another-user'):assert key!=service.cache_key('사업 설명',data,[],doc)
    monkeypatch.setattr(llm,'PROMPT_VERSION','new-prompt')
    assert key!=service.cache_key('사업 설명',data,[],doc)


def test_malformed_paid_answer_is_charged_but_not_cached(database,fake_api,monkeypatch):
    data=prepared()
    def reject(*args):raise ProviderError('invalid','citation_validation_failed')
    monkeypatch.setattr(service,'validate_answer',reject)
    with pytest.raises(ProviderError):service.answer('사업 설명',data,[])
    assert len(fake_api)==2
    with store.connection() as db:
        assert db.execute('SELECT count(*) AS n FROM ai_calls WHERE actual_microusd>0').fetchone()['n']==2
        assert db.execute('SELECT count(*) AS n FROM answer_cache').fetchone()['n']==0


def test_duplicate_request_lock_does_not_call_model(database,fake_api):
    data=prepared();doc=store.get_document(store.document_id(data,llm.embedding_model()))
    key=service.cache_key('사업 설명',data,[],doc)
    with store.exclusive('answer:'+key) as acquired:
        assert acquired
        with pytest.raises(ProviderError) as error:service.answer('사업 설명',data,[])
    assert error.value.code=='ai_busy' and fake_api==[]


def test_auth_tokens_cookie_and_no_client_identity_trust(database,monkeypatch):
    code='test-access-code-'+'a'*32;create_user('invited',code)
    client=TestClient(app)
    assert client.get('/api/session',headers={'X-User-ID':'invited'}).json()['authenticated'] is False
    assert client.post('/api/rag/prepare/SEC:CPNG',headers={'X-User-ID':'invited'}).status_code==401
    response=client.post('/api/session',json={'code':code})
    assert response.status_code==200 and 'HttpOnly' in response.headers['set-cookie']
    assert 'SameSite=strict' in response.headers['set-cookie']
    assert client.get('/api/session').json()['usage']['user_id']=='invited'
    assert client.post('/api/session',json={'code':code},headers={'Origin':'https://evil.example'}).status_code==403
    with store.connection() as db:db.execute("UPDATE ai_users SET disabled=true WHERE id='invited'")
    assert client.get('/api/session').json()['authenticated'] is False
    monkeypatch.setenv('AI_AUTH_MODE','local')
    assert client.get('/api/session').status_code==403
    local=TestClient(app,base_url='http://localhost',client=('127.0.0.1',12345))
    assert local.get('/api/session').json()['usage']['user_id']=='local-owner'


def test_abandoned_request_keeps_money_and_releases_user_slot(database):
    with billing.operation('answer') as rid:
        cid=billing.reserve('generate','gpt-4.1-mini',1000)
    with store.connection() as db:
        db.execute("UPDATE ai_requests SET status='active',created_at=now()-interval '16 minutes' WHERE id=%s",(rid,))
    with billing.operation('answer'):
        with store.connection() as db:
            assert db.execute('SELECT status FROM ai_calls WHERE id=%s',(cid,)).fetchone()['status']=='uncertain'
        assert billing.usage('local-owner')['held_usd']==0.0004


def test_expired_operation_cannot_make_new_paid_call(database):
    with billing.operation('answer') as rid:
        with store.connection() as db:db.execute("UPDATE ai_requests SET status='failed' WHERE id=%s",(rid,))
        with pytest.raises(ProviderError) as error:billing.reserve('generate','gpt-4.1-mini',1)
    assert error.value.code=='ai_request_expired'


def test_zero_budget_http_keeps_numeric_lookup_available(database,fake_api,monkeypatch):
    from finance_detective import chat
    from pathlib import Path
    data=json.loads((Path(__file__).parent/'fixtures/cpng-annual.json').read_text())
    data.update(company_id='SEC:CPNG',currency='USD',scope='consolidated',period_basis='annual',warnings=[],
                source_url='https://www.sec.gov/Archives/edgar/data/1/report.htm',filing={'form':'10-K','accession':'fixture','end':'2025-12-31'})
    for row in data['records']:row['period_label']=row['end']
    monkeypatch.setattr(chat,'load_financials',lambda cid:data)
    did=store.queue_document(data,llm.embedding_model())
    chunks=[{'id':did+':1','ordinal':1,'section':'Business','text':'The company provides software services.'}]
    store.save_chunks(did,chunks,'sha');store.save_vectors(did,chunks,[[1.]+[0.]*511],1);store.progress(did,'ready')
    code='x'*40;create_user('limited',code)
    client=TestClient(app,headers={'Authorization':'Bearer '+code})
    monkeypatch.setenv('AI_DAILY_BUDGET_USD','0')
    assert client.post('/api/chat',json={'message':'매출 알려줘'}).status_code==200
    blocked=client.post('/api/chat',json={'message':'사업 설명'})
    assert blocked.status_code==429 and blocked.json()['code']=='ai_budget_exceeded'
    assert fake_api==[]


def test_index_worker_tracks_embedding_cost_and_reuses_completed_work(database,fake_api,monkeypatch):
    data=prepared();data['filing']={**data['filing'],'accession':'new-index'};data['provider']='SEC'
    did=store.queue_document(data,llm.embedding_model())
    monkeypatch.setattr(service.documents,'download',lambda *args:(b'fixture','new-sha'))
    monkeypatch.setattr(service.documents,'extract_blocks',lambda *args:[{'section':'Business','text':'Software services are the principal business of this company. '*8}])
    service._index(data,did,'local-owner')
    assert store.get_document(did)['status']=='ready' and fake_api==['embedding']
    assert billing.usage('local-owner')['daily_used_usd']>0
    service._index(data,did,'local-owner')
    assert fake_api==['embedding']


def test_missing_provider_usage_is_not_recorded_as_free(database,fake_api):
    with billing.operation('answer'):
        with pytest.raises(ProviderError) as error:
            llm.paid_call('generate','gpt-4.1-mini',{'input':'hello'},100,lambda api:NS(usage=None))
    assert error.value.code=='ai_usage_unknown'
    with store.connection() as db:
        call=db.execute('SELECT status,actual_microusd FROM ai_calls').fetchone()
    assert call['status']=='uncertain' and call['actual_microusd'] is None
