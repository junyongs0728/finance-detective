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
    # A synthetic retrieval response tests routing, not real corpus relevance.
    monkeypatch.setattr(chat,"search",lambda *args:{"results":[{"id":"synthetic", "page":58,
        "text":"Synthetic retrieval fixture", "source_url":FILING_URL}]})



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


def test_evidence_is_not_claimed_as_generated_answer():
    body=client.post("/api/chat",json={"message":"쿠팡 현금흐름 감소 근거 찾아줘"}).json()
    assert body["status"]=="evidence"
    assert body["evidence"][0]["page"]==58
    assert "확정한 답변은 아닙니다" in body["text"]


def test_missing_dataset_returns_actionable_error(tmp_path,monkeypatch):
    def missing(cid): raise FileNotFoundError()
    monkeypatch.setattr(chat,"load_financials",missing)
    assert client.post("/api/chat",json={"message":"쿠팡 매출"}).status_code==503
