"""Bounded RAG workflow: prepare -> retrieve -> generate -> validate -> record."""
from concurrent.futures import ThreadPoolExecutor
import logging
import hashlib
import json
import copy
import threading
import time
import uuid
from finance_detective.providers.common import ProviderError, setting
from . import store, documents, llm, search, billing
from .validation import validate_answer

POOL=ThreadPoolExecutor(max_workers=2,thread_name_prefix='filing-index')
LOCK=threading.Lock()
RUNNING=set()
logger=logging.getLogger(__name__)


def public_status(doc):
    if not doc:return {'status':'not_prepared','chunk_count':0,'embedded_count':0}
    keys=['id','company_id','accession','title','period','status','chunk_count','embedded_count','embedding_model','updated_at','error']
    return {key:doc[key] for key in keys}


def status(data):return public_status(store.get_document(store.document_id(data,llm.embedding_model())))


def _index(data,doc_id,user):
    try:
        with billing.as_user(user), store.exclusive('index:'+doc_id) as acquired:
            if not acquired:return
            if store.get_document(doc_id)['status']=='ready':return
            with billing.operation('index'):
                started=time.monotonic()
                store.progress(doc_id,'indexing')
                document=store.get_document(doc_id)
                if not document['chunk_count']:
                    raw,digest=documents.download(data)
                    chunks=documents.split_blocks(documents.extract_blocks(raw,data['provider']),doc_id)
                    store.save_chunks(doc_id,chunks,digest)
                pending=[c for c in store.chunks(doc_id,vectors=True) if c['vector'] is None]
                for offset in range(0,len(pending),32):
                    if time.monotonic()-started>180:
                        raise ProviderError('공시 준비 시간 제한에 도달했습니다. 다시 시도하면 완료된 부분부터 이어갑니다.','index_timeout')
                    batch=pending[offset:offset+32]
                    vectors,tokens=llm.embed([c['section']+'\n'+c['text'] for c in batch],document['embedding_model'])
                    store.save_vectors(doc_id,batch,vectors,tokens)
                store.progress(doc_id,'ready')
    except Exception as exc:
        error=str(exc) if isinstance(exc,ProviderError) else '공시 준비 중 오류가 발생했습니다. 다시 시도해주세요.'
        store.progress(doc_id,'failed',error)
        logger.warning('Filing preparation failed: %s (%s)',doc_id,type(exc).__name__)
    finally:
        with LOCK:RUNNING.discard(doc_id)


def prepare(data):
    user=billing.require_user()
    if not setting('OPENAI_API_KEY'):raise ProviderError('공시 검색 준비에는 OPENAI_API_KEY가 필요합니다.','ai_setup_required')
    doc_id=store.document_id(data,llm.embedding_model())
    with LOCK:
        existing=store.get_document(doc_id)
        if existing and existing['status']=='ready':return public_status(existing)
        if doc_id not in RUNNING:
            if len(RUNNING)>=2:raise ProviderError('다른 공시를 준비 중입니다. 잠시 후 다시 시도해주세요.','index_busy')
            store.queue_document(data,llm.embedding_model());RUNNING.add(doc_id)
            POOL.submit(_index,data,doc_id,user)
    return public_status(store.get_document(doc_id))


def cache_key(question,data,financial_rows,doc):
    values={'user':billing.require_user(),'document_id':doc['id'],'raw_sha256':doc.get('raw_sha256'),
            'question':' '.join(question.split()),'financial_rows':financial_rows,
            'currency':data.get('currency'),'scope':data.get('scope'),'period_basis':data.get('period_basis'),
            'model':llm.model(),'review_model':llm.review_model(),'prompt':llm.PROMPT_VERSION,
            'retrieval':search.RETRIEVAL_VERSION,'cache_version':2}
    return hashlib.sha256(json.dumps(values,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def cache_hit(key,user):
    row=store.cached(key,user)
    if not row:return None
    result=copy.deepcopy(row['response'])
    result['billing']={'estimated_usd':0,'calls':[],'cached':True,'cached_at':row['created_at'].isoformat()}
    # The original trace remains provenance, not this request's token usage.
    result['trace']={'source_run_id':result.get('trace',{}).get('run_id'),'cache_hit':True,
                     'input_tokens':0,'output_tokens':0}
    return result


def answer(question,data,financial_rows):
    doc=prepare(data)
    if doc['status']!='ready':
        return {'mode':'rag','status':'preparing','text':'이 공시를 처음 준비하고 있습니다. 본문과 출처를 저장한 뒤 답변을 이어갑니다.',
                'document_status':doc,'steps':['공시 준비'],'evidence':[]}
    doc=store.get_document(doc['id'])
    user=billing.require_user();key=cache_key(question,data,financial_rows,doc)
    cached=cache_hit(key,user)
    if cached:return cached
    with store.exclusive('answer:'+key) as acquired:
        if not acquired:raise ProviderError('같은 질문의 분석이 진행 중입니다. 잠시 후 다시 시도해주세요.','ai_busy')
        cached=cache_hit(key,user)
        if cached:return cached
        with billing.operation('answer') as rid:
            result=_answer_ready(question,data,financial_rows,doc)
            result['billing']={**billing.report(rid),'cached':False}
            if result['status']=='answered' and billing.number('AI_CACHE_TTL_SECONDS')>0:
                store.cache_answer(key,user,doc['id'],result,int(billing.number('AI_CACHE_TTL_SECONDS')))
            return result


def _answer_ready(question,data,financial_rows,doc,*,evidence=None,retrieval=None):
    started=time.perf_counter();doc_id=doc['id'];run_id=uuid.uuid4().hex
    if evidence is None:
        evidence,retrieval=search.retrieve(doc_id,question)
    retrieval=dict(retrieval or {})
    if not evidence:
        return {'mode':'rag','status':'insufficient_evidence','text':'관련 공시 근거를 찾지 못했습니다.','steps':['근거 검색'],'evidence':[]}
    usage={'input_tokens':0,'output_tokens':0,'model':llm.model()}
    generated=None
    try:
        generated,usage=llm.generate(question,data,evidence,financial_rows)
        verified=validate_answer(generated,evidence)
        review={'supported':False,'issues':[]}
        if verified['status']=='answered':
            review,review_usage=llm.review(question,verified,evidence)
            usage['input_tokens']+=review_usage['input_tokens']
            usage['output_tokens']+=review_usage['output_tokens']
            review['model']=review_usage.get('model',llm.review_model())
            if not review['supported']:
                # Keep the rejected candidate in the audit trail, never show its claims as an answer.
                retrieval['rejected_claims']=verified['claims']
                verified={'status':'insufficient_evidence','claims':[],
                          'limitations':'검색된 설명만으로는 질문의 내용을 충분히 뒷받침할 수 없어 답변을 보류했습니다. 다른 기간이나 더 구체적인 항목으로 질문해주세요.'}
        retrieval['grounding_review']=review
    except ProviderError as exc:
        store.save_run({'id':run_id,'request_id':billing.REQUEST.get(),'document_id':doc_id,'question':question,'retrieval':retrieval,
                        'response':{'error_code':exc.code,'rejected_response':generated},'model':usage['model'],'prompt_version':llm.PROMPT_VERSION,
                        'input_tokens':usage['input_tokens'],'output_tokens':usage['output_tokens'],
                        'latency_ms':round((time.perf_counter()-started)*1000),'status':exc.code})
        raise
    evidence_by_id={c['id']:c for c in evidence}
    cited_ids=list(dict.fromkeys(c['evidence_id'] for claim in verified['claims'] for c in claim['citations']))
    labels={cid:index+1 for index,cid in enumerate(cited_ids)}
    text='\n\n'.join(claim['text']+' '+''.join(f'[{label}]' for label in dict.fromkeys(labels[c['evidence_id']] for c in claim['citations'])) for claim in verified['claims'])
    if not text:
        text='검색된 공시 문단만으로는 질문을 충분히 뒷받침할 수 없어 답변을 보류했습니다. 이는 공시 전체에 해당 정보가 없다는 뜻은 아닙니다.'
    else:
        # The reviewer checks claims, not the free-form limitations field. Do not
        # let that unreviewed field add facts or assert absence from the whole filing.
        text+='\n\n선택한 공시의 검색된 문단을 바탕으로 한 요약이며, 공시 전체 내용을 모두 포함하지 않을 수 있습니다.'
    cited=[]
    for cid in cited_ids:
        chunk=evidence_by_id[cid]
        quotes=list(dict.fromkeys(c['quote'] for claim in verified['claims'] for c in claim['citations'] if c['evidence_id']==cid))
        cited.append({**chunk,'citation_number':labels[cid],'quotes':quotes})
    elapsed=round((time.perf_counter()-started)*1000)
    store.save_run({'id':run_id,'request_id':billing.REQUEST.get(),'document_id':doc_id,'question':question,'retrieval':retrieval,
                    'response':verified,'model':usage['model'],'prompt_version':llm.PROMPT_VERSION,
                    'input_tokens':usage['input_tokens'],'output_tokens':usage['output_tokens'],
                    'latency_ms':elapsed,'status':verified['status']})
    return {'mode':'rag','status':verified['status'],'text':text,'claims':verified['claims'],'evidence':cited,
            'steps':['기업·공시 범위 확인','문서 검색','AI 답변 생성','인용문 대조','근거 검토'],
            'trace':{'run_id':run_id,'model':usage['model'],'prompt_version':llm.PROMPT_VERSION,
                     'retrieval_method':retrieval['method'],'review_model':review.get('model'),'input_tokens':usage['input_tokens'],
                     'output_tokens':usage['output_tokens'],'latency_ms':elapsed},
            'citation_validation':'Source IDs checked and quotes copied verbatim; separate LLM grounding review (not a guarantee)'}
