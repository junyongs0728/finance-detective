"""Offline provider fixtures and cross-company isolation checks."""
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from finance_detective.main import app
from finance_detective import main, chat
from finance_detective.providers import registry, service, sec_company, dart_company
from finance_detective.providers.common import ProviderError

client = TestClient(app)


def dataset(cid, currency="KRW"):
    return {"company_id": cid, "company": "Fixture company", "currency": currency,
            "selection_policy": "offline test fixture", "scope": "consolidated", "period_basis": "사업연도", "warnings": [],
            "filing": {"form": "사업보고서", "accession": "fixture", "end": "2025"},
            "source_url": "https://dart.fss.or.kr/", "fetched_at": datetime.now(timezone.utc).isoformat(),
            "records": [{"year": y, "period_label": str(y), "start": None, "end": None,
                         "metric": metric, "value": value, "unit": currency}
                        for y in (2024, 2025) for metric, value in [("revenue", 100 if y == 2024 else 120), ("operating_income", 12)]]}


def test_search_alias_code_market_and_not_found():
    assert "DART:005930" not in registry.mentioned_companies("삼성생명 매출")
    assert registry.find_companies("애플")["results"][0]["id"] == "SEC:AAPL"
    assert registry.find_companies("005930")["results"][0]["id"] == "DART:005930"
    assert registry.find_companies("005930", "SEC")["results"] == []
    assert client.get("/api/companies", params={"q": "zzzzzz-no-company"}).json()["results"] == []
    assert client.get("/api/companies?market=invalid").status_code == 422
    with pytest.raises(ProviderError): registry.get_company("../../.env")


def test_selected_company_api_and_chat_never_use_coupang_evidence(monkeypatch):
    calls=[]
    def load(cid):
        calls.append(cid)
        return dataset(cid)
    monkeypatch.setattr(main, "load_financials", load)
    monkeypatch.setattr(chat, "load_financials", load)
    def rag(question,data,rows):
        assert data["company_id"] == "DART:005930"
        return {"mode":"rag","status":"preparing","evidence":[],"text":"Preparing selected company"}
    monkeypatch.setattr(chat, "rag_answer", rag)
    response=client.get("/api/company-data/DART:005930").json()
    assert response["company"]["id"] == "DART:005930"
    assert response["currency"] == "KRW"
    assert response["rows"][-1]["revenue_growth_pct"] == 20
    result=client.post("/api/chat", json={"company_id":"DART:005930", "message":"영업현금흐름 감소 근거", "engine":"rag"}).json()
    assert result["status"] == "preparing" and result["evidence"] == []
    assert calls == ["DART:005930", "DART:005930"]
    mismatch=client.post("/api/chat", json={"company_id":"DART:005930", "message":"애플 매출"}).json()
    assert mismatch["status"] == "unsupported" and not mismatch["rows"]
    assert len(calls) == 2


def test_provider_failure_is_actionable_without_fallback(monkeypatch):
    def fail(cid): raise ProviderError("인증키 설정이 필요합니다.", "setup_required")
    monkeypatch.setattr(main, "load_financials", fail)
    result=client.get("/api/company-data/DART:005930")
    assert result.status_code == 503 and result.json()["code"] == "setup_required"


def test_cache_is_per_company_and_reuses_success(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "ROOT", tmp_path)
    calls=[]
    def load(company):
        calls.append(company["id"])
        return dataset(company["id"])
    monkeypatch.setattr(service.dart_company, "collect_company", load)
    for cid in ["DART:005930", "DART:035420", "DART:005930"]:
        assert service.load_financials(cid)["company_id"] == cid
    assert calls == ["DART:005930", "DART:035420"]


def test_summary_does_not_mix_currencies_or_periods():
    data=dataset("fixture")
    data["records"][1]["unit"]="USD"
    with pytest.raises(ProviderError): service.summary(data)
    data=dataset("fixture")
    data["records"][1]["start"]="2024-04-01"
    with pytest.raises(ProviderError): service.summary(data)


def test_sec_actual_fiscal_period_and_accession_filter():
    company=registry.get_company("SEC:AAPL")
    filing={"accession":"chosen", "end":"2025-09-27", "document":"annual.htm", "form":"10-K"}
    annual={"accn":"chosen", "start":"2024-09-29", "end":"2025-09-27", "val":100}
    payload={"cik":company["cik"], "facts":{"us-gaap":{"Revenues":{"units":{"USD":[annual,
        {**annual, "start":"2025-06-29", "val":999},
        {**annual, "accn":"different", "val":888}]}}}}}
    result=sec_company.normalize_company(payload,company,filing)
    row=result["records"][0]
    assert row["value"]==100 and row["period_label"]=="2025-09-27"
    assert row["start"]=="2024-09-29"
    assert "operating_income" in " ".join(result["warnings"])
    payload["cik"]="0000000001"
    with pytest.raises(ProviderError): sec_company.normalize_company(payload,company,filing)


def test_dart_missing_not_zero_and_conflicts_rejected():
    company=registry.get_company("DART:005930")
    row={"rcept_no":"20260310002820", "sj_div":"IS", "account_id":"ifrs-full_Revenue", "currency":"KRW", "thstrm_amount":"1,200", "frmtrm_amount":"-", "bfefrmtrm_amount":"0"}
    result=dart_company.normalize_dart({"list":[row]},company,2025)
    assert [(r["year"],r["value"]) for r in result["records"]]==[(2025,1200),(2023,0)]
    assert dart_company.parse_amount("(2,000)")==-2000
    assert dart_company.parse_amount("-") is None
    with pytest.raises(ProviderError): dart_company.normalize_dart({"list":[row,{**row,"rcept_no":"different"}]},company,2025)


def test_missing_dart_key_fails_before_network(monkeypatch):
    monkeypatch.setattr(dart_company,"setting",lambda name:"")
    with pytest.raises(ProviderError) as error: dart_company.key()
    assert error.value.code=="setup_required"
