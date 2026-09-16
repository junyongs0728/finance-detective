"""Run source-anchored diagnostics; do not equate retrieval hits with answer accuracy."""
import json
from finance_detective.collectors.sec import ROOT
from finance_detective.retrieval.evidence import INDEX, rank


def evaluate():
    corpus=json.loads(INDEX.read_text())
    dataset=json.loads((ROOT/"evals/retrieval-dev.json").read_text())
    details=[]
    for case in dataset["cases"]:
        results=rank(corpus["chunks"],case["query"],limit=5)
        detail={"id":case["id"],"query":case["query"],"answerable":case["answerable"],"top_pages":[r["page"] for r in results]}
        if case["answerable"]:
            relevant=lambda c:c["page"]==case["page"] and case["evidence_phrase"].lower() in c["text"].lower()
            if not any(relevant(c) for c in corpus["chunks"]):
                raise ValueError("Gold evidence absent from corpus: "+case["id"])
            ranks=[i for i,r in enumerate(results,1) if relevant(r)]
            detail.update(hit_at_1=bool(ranks and ranks[0]==1),hit_at_5=bool(ranks),reciprocal_rank_at_5=1/ranks[0] if ranks else 0)
        else:
            detail["returned_candidates"]=bool(results)
        details.append(detail)
    positive=[d for d in details if d["answerable"]]
    negative=[d for d in details if not d["answerable"]]
    return {"dataset_status":dataset["status"],"corpus_sha256":corpus["sha256"],
            "answerable_count":len(positive),"unanswerable_count":len(negative),
            "hit_at_1":sum(d["hit_at_1"] for d in positive)/len(positive),
            "hit_at_5":sum(d["hit_at_5"] for d in positive)/len(positive),
            "mrr_at_5":sum(d["reciprocal_rank_at_5"] for d in positive)/len(positive),
            "unanswerable_with_candidates":sum(d["returned_candidates"] for d in negative),
            "limitations":"Candidates are not answers. No semantic correctness, completeness, Korean, multi-company or generation evaluation. Negative cases diagnose need for scope/answerability checks; not hallucination rate.","cases":details}


if __name__=="__main__":
    report=evaluate()
    output=ROOT/"evals/retrieval-report.json"
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False,indent=2))
