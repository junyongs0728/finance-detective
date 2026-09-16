from fastapi.testclient import TestClient
from finance_detective.main import app

client = TestClient(app)

def test_health():
    assert client.get("/health").json() == {"status": "ok"}

def test_company_source_and_scope():
    response = client.get("/api/companies/cpng")
    assert response.status_code == 200
    assert response.json()["cik"] == "0001834584"
    assert response.json()["scope"] == "consolidated"
    assert response.json()["analysis_status"] == "not_implemented"

def test_unknown_company_is_not_coupang():
    assert client.get("/api/companies/UNKNOWN").status_code == 404
