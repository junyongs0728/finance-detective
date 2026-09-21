"""Reproducible development acceptance through HTTP; --live explicitly allows API cost."""
import argparse
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
import time
from datetime import datetime,timezone
import httpx

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true',help='OpenAI 유료 호출을 포함한 실제 HTTP 평가 실행')
    parser.add_argument('--base-url',default='http://127.0.0.1:8000')
    parser.add_argument('--case',help='하나의 사례 ID만 실행')
    parser.add_argument('--output',default='data/processed/agent-evaluation.json')
    args=parser.parse_args()
    if not args.live:parser.error('--live를 지정해야 실제 모델 평가를 실행합니다.')
    cases=json.loads((ROOT/'evals/agent-cases.json').read_text())
    if args.case:cases=[c for c in cases if c['id']==args.case]
    if not cases:parser.error('일치하는 평가 사례가 없습니다.')
    reports=[]
    with httpx.Client(base_url=args.base_url,timeout=240) as client:
        for case in cases:
            started=time.perf_counter(); checks={}; result={}
            try:
                payload={'company_id':case['company_id'],'message':case['question'],'engine':'agent'}
                response=client.post('/api/chat',json=payload);response.raise_for_status();result=response.json()
                if result.get('status')=='preparing':
                    did=result['document_status']['id'];deadline=time.monotonic()+180
                    while time.monotonic()<deadline:
                        status=client.get('/api/rag/status/'+did).json()
                        if status['status']=='ready':break
                        if status['status']=='failed':raise RuntimeError('document_preparation_failed')
                        time.sleep(2)
                    else:raise RuntimeError('document_preparation_timeout')
                    response=client.post('/api/chat',json=payload);response.raise_for_status();result=response.json()
                checks['status']=result.get('status') in case['statuses']
                tools={s['tool'] for s in result.get('agent_steps',[]) if s['status']=='ok'}
                if case.get('tools'):checks['tool_selection']=set(case['tools'])<=tools
                if case.get('graph'):
                    kg=result.get('knowledge_graph',{})
                    checks['graph_projection']=kg.get('engine')=='neo4j' and kg.get('verified_against_sql') is True
                if case.get('citations'):
                    citations=result.get('evidence',[])
                    checks['exact_quotes']=bool(citations) and all(e.get('quotes') and all(q in e['text'] for q in e['quotes']) for e in citations)
                if case.get('no_paid_calls'):checks['no_paid_calls']=not result.get('billing',{}).get('calls')
                if case.get('calculation'):
                    expected=case['calculation'];overview=client.get('/api/company-data/'+case['company_id']).json()
                    row=next(r for r in overview['rows'] if r['year']==expected['year'])
                    a=Decimal(str(row[expected['left_metric']]));b=Decimal(str(row[expected['right_metric']]))
                    answer=a-b if expected['operation']=='difference' else (a/b*100).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
                    checks['numeric_result']=any(c['operation']==expected['operation'] and Decimal(c['value'])==answer and c['left']['metric']==expected['left_metric'] and c['right']['metric']==expected['right_metric'] for c in result.get('calculations',[]))
                report={'id':case['id'],'company_id':case['company_id'],'question':case['question'],
                    'status':result.get('status'),'checks':checks,'passed':all(checks.values()),
                    'tool_sequence':[s['tool'] for s in result.get('agent_steps',[])],
                    'agent_trace':result.get('agent_trace'),'evidence_count':len(result.get('evidence',[])),
                    'estimated_usd':result.get('billing',{}).get('estimated_usd',0),
                    'cached':result.get('billing',{}).get('cached',False)}
            except Exception as exc:
                report={'id':case['id'],'passed':False,'error_type':type(exc).__name__,'status':result.get('status'),'checks':checks,
                        'estimated_usd':None,'cost_note':'HTTP 실패 시 호출 비용은 0으로 가정하지 않습니다. SQL 감사 기록을 확인하세요.'}
                if isinstance(exc,httpx.HTTPStatusError):
                    report['http_status']=exc.response.status_code
                    try:report['error_code']=exc.response.json().get('code')
                    except ValueError:pass
            report['elapsed_ms']=round((time.perf_counter()-started)*1000)
            reports.append(report)
            print(json.dumps(report,ensure_ascii=False),flush=True)
    output={'created_at':datetime.now(timezone.utc).isoformat(),'evaluation':'development acceptance; not independent semantic accuracy or hallucination rate',
       'limitations':'고정 개발 사례의 상태·도구·계산·인용 문자열·SQL/Graph 일치 검사. 답변의 의미 정확성과 원인 설명의 충분성은 별도 사람 검토가 필요합니다.',
       'passed':sum(r['passed'] for r in reports),'total':len(reports),'cases':reports}
    path=ROOT/args.output;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(output,ensure_ascii=False,indent=2))
    return 0 if all(r['passed'] for r in reports) else 1


if __name__=='__main__':raise SystemExit(main())
