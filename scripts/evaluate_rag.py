"""Explicit opt-in live evaluation: calls paid model APIs, saves local development results."""
from pathlib import Path
import json
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from finance_detective.chat import answer
from finance_detective.providers.common import ProviderError, now
from finance_detective.rag.llm import PROMPT_VERSION
from finance_detective.rag import billing, store


def main():
    cases=json.loads((ROOT/'evals/rag-dev.json').read_text())['cases']
    results=[]
    for case in cases:
        started=time.perf_counter()
        try:
            result=answer(case['question'],case['company_id'])
            if result['status']=='preparing':
                raise RuntimeError('Prepare the selected filings first via the app.')
            correct=result['status']==case['expected_status'] and all(t in result['text'] for t in case['must_contain'])
            citations_ok=all(q in item['text'] for item in result['evidence'] for q in item.get('quotes',[]))
            if result['status']=='answered':citations_ok=citations_ok and bool(result['evidence'])
            results.append({**case,'actual_status':result['status'],'passed':correct and citations_ok,
                            'exact_quote_check':citations_ok,'text':result['text'],'trace':result.get('trace'),
                            'citation_ids':[e['id'] for e in result['evidence']],'latency_ms':round((time.perf_counter()-started)*1000)})
            print(case['id'],result['status'],'PASS' if results[-1]['passed'] else 'REVIEW',flush=True)
        except ProviderError as error:
            results.append({**case,'passed':False,'error_code':error.code})
            print(case['id'],error.code,flush=True)
    report={'created_at':now(),'prompt_version':PROMPT_VERSION,'evaluation':'development acceptance; no semantic correctness score',
            'passed':sum(r['passed'] for r in results),'total':len(results),'cases':results}
    output=ROOT/'data/processed/rag-evaluation.json'
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print('Results saved locally:',output.relative_to(ROOT),flush=True)


if __name__=='__main__':
    store.initialize()
    try:
        with billing.as_user('local-owner'):main()
    finally:store.close()
