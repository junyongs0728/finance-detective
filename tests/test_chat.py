from fastapi.testclient import TestClient
from finance_detective.main import app
from finance_detective import chat

import json
from pathlib import Path
import pytest
from finance_detective.collectors.sec import ACCESSION, FILING_URL

client=TestClient(app)

@pytest.fixture(autouse=True)
def offline_coupang(monkeypatch):
    data=json.loads((Path(__file__).parent/"fixtures/cpng-annual.json").read_text())
    data.update(company_id="SEC:CPNG", currency="USD", scope="consolidated", period_basis="회계연도 종료일", warnings=[], source_url=FILING_URL, filing={"accession":ACCESSION,"form":"10-K"})
    for row in data["records"]: row["period_label"]=row["end"]
    monkeypatch.setattr(chat,"load_financials",lambda cid:data)
    # Synthetic RAG result isolates chat routing from provider/model calls.
    monkeypatch.setattr(chat,"rag_answer",lambda question,data,rows:{"mode":"rag","status":"answered",
        "text":"근거를 인용한 합성 응답", "steps":["인용문 대조"],
        "evidence":[{"id":"synthetic", "ordinal":58,"text":"Synthetic retrieval fixture", "source_url":FILING_URL}]})
    monkeypatch.setattr(chat,"agent_answer",lambda question,data,rows:{"mode":"agent","status":"answered",
        "text":"합성 Agent 응답", "steps":["도구 결과 검증"], "evidence":[]})



def test_real_question_selects_year_and_returns_sources():
    result=client.post("/api/chat",json={"message":"쿠팡 2025년 매출 알려줘"})
    assert result.status_code==200
    body=result.json()
    assert body["mode"]=="rule_based"
    assert [r["year"] for r in body["rows"]]==[2025]
    assert body["rows"][0]["revenue"]==34534000000
    assert body["sources"]


def test_unsupported_company_period_and_unknown_intent():
    for text in ["삼성 매출", "쿠팡 2027년 실적", "쿠팡 2025년 1분기 매출", "쿠팡 주가 예측", "안녕하세요"]:
        body=client.post("/api/chat",json={"message":text}).json()
        assert body["status"]=="unsupported"
        assert body["rows"]==[]


def test_blank_and_oversized_input():
    for text in ["", "  ", "x"*2001]:
        assert client.post("/api/chat",json={"message":text}).status_code==422


def test_explanation_is_routed_to_rag():
    body=client.post("/api/chat",json={"message":"쿠팡 현금흐름 감소 근거 찾아줘","engine":"rag"}).json()
    assert body["status"]=="answered"
    assert body["mode"]=="rag"
    assert body["evidence"][0]["ordinal"]==58
    assert body["steps"] == ["인용문 대조"]


def test_auto_explanation_and_difference_use_agent_but_simple_numbers_stay_free():
    for text in ['주요 사업을 설명해줘','영업이익과 현금흐름 차이 계산해줘']:
        body=client.post('/api/chat',json={'message':text}).json()
        assert body['mode']=='agent'
    assert client.post('/api/chat',json={'message':'연간 매출 알려줘'}).json()['mode']=='rule_based'


def test_missing_dataset_returns_actionable_error(tmp_path,monkeypatch):
    def missing(cid): raise FileNotFoundError()
    monkeypatch.setattr(chat,"load_financials",missing)
    assert client.post("/api/chat",json={"message":"쿠팡 매출"}).status_code==503


def test_rag_evaluator_does_not_follow_default_agent_route(tmp_path, monkeypatch):
    import runpy

    def unexpected_agent(*args):
        pytest.fail("The fixed RAG evaluation must not run the default Agent path")

    monkeypatch.setattr(chat, "agent_answer", unexpected_agent)
    monkeypatch.setattr(chat, "rag_answer", lambda question, data, rows: {
        "mode": "rag", "status": "answered", "text": "근거를 인용한 합성 응답",
        "evidence": [{"id": "synthetic", "text": "Synthetic evidence", "quotes": ["Synthetic evidence"]}],
    })
    cases = [{"id": "fixed-rag-route", "company_id": "SEC:CPNG",
              "question": "쿠팡의 주요 사업을 공시 근거로 설명해줘",
              "expected_status": "answered", "must_contain": ["합성 응답"]}]
    (tmp_path / "evals").mkdir()
    (tmp_path / "evals/rag-dev.json").write_text(json.dumps({"cases": cases}))
    (tmp_path / "data/processed").mkdir(parents=True)

    script = Path(__file__).resolve().parents[1] / "scripts/evaluate_rag.py"
    evaluator = runpy.run_path(str(script))["main"]
    monkeypatch.setitem(evaluator.__globals__, "ROOT", tmp_path)
    evaluator()

    report = json.loads((tmp_path / "data/processed/rag-evaluation.json").read_text())
    assert report["passed"] == report["total"] == 1
    assert report["cases"][0]["exact_quote_check"] is True
