"""Small-corpus hybrid retrieval. SQL scope filtering happens BEFORE ranking."""
from collections import Counter
import math
import re
from . import llm, store

RETRIEVAL_VERSION='pgvector-exact-bm25-rrf-v1'


def tokens(text):
    words=re.findall(r'[a-z0-9]+|[가-힣]+',text.lower())
    result=[]
    for word in words:
        if re.fullmatch('[가-힣]+',word):
            result.extend(word[i:i+2] for i in range(max(1,len(word)-1)))
        elif word not in {'the','and','of','to','in','a','is','for','with'}:result.append(word)
    return result


def lexical_rank(chunks, question):
    terms=set(tokens(question)); counts=[Counter(tokens(c['section']+' '+c['text'])) for c in chunks]
    lengths=[sum(c.values()) for c in counts]; average=sum(lengths)/len(lengths) if lengths else 1
    df=Counter(t for count in counts for t in count)
    scored=[]
    for chunk,count,length in zip(chunks,counts,lengths):
        score=0
        for term in terms:
            freq=count[term]
            score+=math.log(1+(len(chunks)-df[term]+.5)/(df[term]+.5))*freq*2.5/(freq+1.5*(.25+.75*length/(average or 1)))
        if score>0:scored.append((chunk['id'],score))
    return sorted(scored,key=lambda x:(-x[1],x[0]))


def cosine(a,b):
    if len(a)!=len(b):raise ValueError('Mismatched embedding dimensions')
    norm=math.sqrt(sum(x*x for x in a)*sum(x*x for x in b))
    return sum(x*y for x,y in zip(a,b))/norm if norm else 0


def retrieval_query(question):
    # A transparent bilingual baseline for our supported question types.
    # This is query expansion, not general translation or an LLM planning step.
    if re.search(r"위험|리스크|risk", question, re.I):
        terms="risk factors business risks"
    elif re.search(r"현금|cash", question, re.I):
        terms="operating cash flows changes liquidity management discussion"
    elif re.search(r"매출|revenue|sales", question, re.I):
        terms="net revenue growth changes management discussion"
    elif re.search(r"사업|제품|돈.*벌|business|product", question, re.I):
        terms="business overview principal products services reportable segments"
    else:
        terms=""
    return question + ("\n" + terms if terms else "")


def retrieve(doc_id, question, limit=6):
    document=store.get_document(doc_id)
    if not document or document['status']!='ready':raise ValueError('Document is not ready')
    # Query only this exact company + accession + parser/model version via document FK.
    chunks=store.chunks(doc_id)
    effective=retrieval_query(question)
    vectors,usage=llm.embed([effective],document['embedding_model'])
    dense=store.dense_rank(doc_id,vectors[0],limit=30)
    lexical=lexical_rank(chunks,effective)
    # RRF combines rankings, not incomparable BM25 and cosine score scales.
    scores=Counter()
    for ranking in [dense[:30],lexical[:30]]:
        for rank,(cid,_) in enumerate(ranking,1):scores[cid]+=1/(60+rank)
    by_id={c['id']:c for c in chunks}
    results=[]
    for cid,score in sorted(scores.items(),key=lambda x:(-x[1],x[0]))[:limit]:
        chunk={k:v for k,v in by_id[cid].items() if k!='vector'}
        results.append({**chunk,'score':round(score,6),'source_url':document['source_url'],'document_title':document['title']})
    return results,{'method':'pgvector_exact_bm25_rrf','version':RETRIEVAL_VERSION,'embedding_tokens':usage,'document_id':doc_id,
                   'candidate_count':len(chunks),'effective_query':effective,'dense_top_ids':[i for i,_ in dense[:6]],'lexical_top_ids':[i for i,_ in lexical[:6]]}
