"""Agent control/financial correctness and actual SQL + Neo4j integration, no paid calls."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from finance_detective.providers.common import ProviderError
from finance_detective.providers.service import summary
from finance_detective.rag import store,billing,llm,service as rag
from finance_detective.agents import workflow,model
from finance_detective.agents.tools import ToolContext,calculate
from finance_detective.knowledge import ontology,graph


@pytest.fixture
def data():
    d=json.loads((Path(__file__).parent/'fixtures/cpng-annual.json').read_text())
    d.update(company_id='SEC:CPNG',provider='SEC',currency='USD',scope='consolidated',period_basis='annual',warnings=[],
             source_url=d['records'][0]['source_url'],filing={'form':'10-K','accession':d['records'][0]['accession'],'end':'2025-12-31'})
    for r in d['records']:r['period_label']=r['end']
    return d


@pytest.fixture
def document(data,database):
    did=store.queue_document(data,llm.embedding_model())
    chunk={'id':did+':1','ordinal':1,'section':'Business','text':'The company sells goods through its e-commerce service.'}
    store.save_chunks(did,[chunk],'fixture-hash');store.save_vectors(did,[chunk],[[1.]+[0.]*511],1);store.progress(did,'ready')
    return store.get_document(did)


@pytest.fixture
def graph_database(database):
    ns=graph.namespace();assert ns.startswith('fd_test_')
    try:yield
    finally:
        with graph.session() as db:db.run('MATCH (n:FDNode {namespace:$ns}) DETACH DELETE n',ns=ns).consume()


def fact(data,metric,year=2025):
    return next(r for r in ontology.observations(data) if r['year']==year and r['metric']==metric)


def test_ids_distinguish_period_value_scope_and_currency(data):
    initial=ontology.observations(data)
    assert len({r['id'] for r in initial})==len(initial)==9
    changed=copy.deepcopy(data);changed['records'][0]['value']+=1
    assert {r['id'] for r in initial}!={r['id'] for r in ontology.observations(changed)}
    changed['records'][0]['unit']='KRW'
    with pytest.raises(ProviderError):ontology.observations(changed)


def test_calculations_use_exact_values_and_reject_invalid_combinations(data):
    cash= fact(data,'operating_cash_flow'); income=fact(data,'operating_income')
    result=calculate('difference',cash,income)
    assert result['value']==str(int(cash['value'])-int(income['value']))
    for edit in [{'currency':'KRW','unit':'KRW'},{'scope':'standalone'},{'company_id':'SEC:OTHER'}, {'accession':'other'}]:
        with pytest.raises(ProviderError):calculate('difference',cash,{**income,**edit})
    with pytest.raises(ProviderError):calculate('difference',cash,fact(data,'operating_income',2024))
    with pytest.raises(ProviderError):calculate('growth_pct',cash,income)
    with pytest.raises(ProviderError):calculate('ratio_pct',cash,{**income,'value':'0'})
    with pytest.raises(ProviderError):calculate('ratio_pct',cash,{**income,'value':'-1'})


def test_tool_args_cannot_inject_numbers_scope_or_unseen_ids(data,document):
    ctx=ToolContext(data,document,{2025});tools={t.name:t for t in ctx.tools}
    left=fact(data,'operating_cash_flow')['id'];right=fact(data,'operating_income')['id']
    with pytest.raises(ProviderError):tools['calculate_metrics'].invoke({'operation':'difference','left_id':left,'right_id':right})
    with pytest.raises(ProviderError):tools['get_financials'].invoke({'years':[2024],'metrics':[]})
    with pytest.raises(Exception):tools['get_financials'].invoke({'years':[2025],'metrics':[],'company_id':'DART:005930'})
    with pytest.raises(Exception):tools['calculate_metrics'].invoke({'operation':'difference','left_id':left,'right_id':right,'value':99})
    tools['get_financials'].invoke({'years':[2025],'metrics':[]})
    assert tools['calculate_metrics'].invoke({'operation':'difference','left_id':left,'right_id':right})['unit']=='USD'


def test_real_graph_is_idempotent_and_does_not_invent_narrative_support(data,document,graph_database):
    snapshot=ontology.build_snapshot(data,document,store.chunks(document['id']))
    graph.project(snapshot);graph.project(snapshot)
    result=graph.read(snapshot['id'])
    assert result['engine']=='neo4j' and result['verified_against_sql']
    assert {n['kind'] for n in result['nodes']}==ontology.KINDS
    narratives={n['id'] for n in result['nodes'] if n['properties'].get('evidence_kind')=='narrative_chunk'}
    assert narratives
    assert not any(e['type']=='SUPPORTED_BY' and e['target'] in narratives for e in result['edges'])
    path=graph.trace(snapshot['id'],[fact(data,'revenue')['id']])[0]
    assert path['value']=='34534000000' and path['period']=='2025-12-31'
    assert path['evidence_kind']=='structured_fact'
    with pytest.raises(ProviderError):graph.trace(snapshot['id'],['another-company-id'])
    with store.connection() as db:assert db.execute('SELECT count(*) AS n FROM knowledge_snapshots').fetchone()['n']==1


def test_projection_corruption_and_cross_filing_evidence_are_rejected(data,document,graph_database):
    chunks=store.chunks(document['id']);other={**chunks[0],'document_id':'different-filing'}
    with pytest.raises(ProviderError):ontology.build_snapshot(data,document,[other])
    snapshot=ontology.build_snapshot(data,document,chunks);graph.project(snapshot)
    with graph.session() as db:
        db.run('MATCH (o:Observation {namespace:$ns,id:$id}) SET o.value=$value',ns=graph.namespace(),id=fact(data,'revenue')['id'],value='1').consume()
    with pytest.raises(ProviderError):graph.read(snapshot['id'])
    with pytest.raises(ProviderError):graph.trace(snapshot['id'],[fact(data,'revenue')['id']])
    graph.project(snapshot);assert graph.read(snapshot['id'])['verified_against_sql']
    with graph.session() as db:
        db.run('MATCH (o:Observation {namespace:$ns,id:$id})-[:FOR_PERIOD]->(p) SET p.label=$value',
            ns=graph.namespace(),id=fact(data,'revenue')['id'],value='wrong-period').consume()
    with pytest.raises(ProviderError):graph.trace(snapshot['id'],[fact(data,'revenue')['id']])


def tool_call(name,args,number=1):
    return AIMessage(content='',tool_calls=[{'id':f'call_{number}','name':name,'args':args}])


def numeric_planner(messages,tools):
    """Synthetic model decisions depend on actual preceding tool observations."""
    if len(messages)==2:return tool_call('get_financials',{'years':[2025],'metrics':['operating_cash_flow','operating_income']})
    last=messages[-1]
    if last.name=='get_financials':
        values={r['metric']:r['id'] for r in json.loads(last.content)['observations']}
        return tool_call('calculate_metrics',{'operation':'difference','left_id':values['operating_cash_flow'],'right_id':values['operating_income']},2)
    return AIMessage(content='')


def test_agent_model_selects_next_action_from_real_tool_output(data,document):
    ctx=ToolContext(data,document,{2025});events=[]
    state=workflow.execute('현금흐름과 영업이익 차이',ctx,events,planner=numeric_planner)
    assert not state['stop_reason']
    assert [e['tool'] for e in events]==['get_financials','calculate_metrics']
    assert ctx.calculations[0]['value']==str(int(fact(data,'operating_cash_flow')['value'])-int(fact(data,'operating_income')['value']))


def test_loop_limit_unknown_tool_and_timeout_do_not_execute_unbounded(data,document,monkeypatch):
    monkeypatch.setenv('AGENT_MAX_STEPS','2')
    ctx=ToolContext(data,document,{2025});events=[]
    result=workflow.execute('매출',ctx,events,planner=lambda *args:tool_call('run_arbitrary_code',{'code':'bad'}))
    assert result['stop_reason']=='step_limit' and len(events)==2
    assert all(e['error_code']=='unknown_tool' for e in events)
    timer=iter([0,121])
    result=workflow.execute('매출',ctx,[],planner=lambda *args:pytest.fail('must not call model'),clock=lambda:next(timer))
    assert result['stop_reason']=='time_limit'


def test_agent_cache_audit_and_user_isolation(data,document,graph_database,monkeypatch):
    monkeypatch.setattr(workflow.model,'invoke',numeric_planner)
    monkeypatch.setattr(rag,'prepare',lambda data:{'id':document['id'],'status':'ready'})
    rows=[r for r in summary(data) if r['year']==2025]
    first=workflow.answer('영업현금흐름과 영업이익 차이',data,rows)
    assert first['status']=='answered' and first['knowledge_graph']['engine']=='neo4j'
    run_id=first['agent_trace']['run_id']
    assert workflow.get_run(run_id,'local-owner')['status']=='answered'
    with pytest.raises(ProviderError):workflow.get_run(run_id,'other-user')
    monkeypatch.setattr(workflow.model,'invoke',lambda *args:pytest.fail('cache should not call model'))
    cached=workflow.answer('영업현금흐름과 영업이익 차이',data,rows)
    assert cached['billing']['cached'] and cached['billing']['estimated_usd']==0


def test_missing_requested_calculation_is_not_reported_complete(data,document,graph_database):
    ctx=ToolContext(data,document,{2025});ctx.tools[0].invoke({'years':[2025],'metrics':['revenue']})
    result=workflow._finalize('영업이익 차이 계산',data,summary(data),document,ctx,{'stop_reason':''},[{'tool':'get_financials'}])
    assert result['status']=='partial' and '계산 결과' in result['text']


def test_langchain_calls_are_billed_and_missing_usage_keeps_reservation(database,monkeypatch):
    # The fake client must not depend on a developer's .env or a real credential.
    monkeypatch.setenv('OPENAI_API_KEY','test-only-no-network')
    calls=[]
    class FakeModel:
        def __init__(self,**kwargs):
            assert kwargs['max_retries']==0 and kwargs['store'] is False
        def bind_tools(self,tools,**kwargs):
            assert kwargs['strict'] and kwargs['parallel_tool_calls'] is False
            return self
        def invoke(self,*args,**kwargs):
            calls.append(1)
            return AIMessage(content='',usage_metadata={'input_tokens':12,'output_tokens':3,'total_tokens':15})
    monkeypatch.setattr(model,'ChatOpenAI',FakeModel)
    with billing.operation('agent') as rid:model.invoke([HumanMessage(content='hello')],[])
    report=billing.report(rid)
    assert report['calls'][0]['stage']=='agent_plan' and report['calls'][0]['status']=='completed'
    monkeypatch.setattr(FakeModel,'invoke',lambda *a,**k:AIMessage(content=''))
    with billing.operation('agent') as rid:
        with pytest.raises(ProviderError) as error:model.invoke([HumanMessage(content='hello')],[])
        assert error.value.code=='ai_usage_unknown'
    assert billing.report(rid)['calls'][0]['status']=='uncertain'
