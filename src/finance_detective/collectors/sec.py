"""Coupang 2025 10-K snapshot; not a generic/latest-filings selector."""
import ssl
import certifi
import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[3]
API_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK0001834584.json"
FILING_URL = "https://www.sec.gov/Archives/edgar/data/1834584/000183458426000024/cpng-20251231.htm"
ACCESSION = "0001834584-26-000024"
METRICS = {
    "revenue": "RevenueFromContractWithCustomerExcludingAssessedTax",
    "operating_income": "OperatingIncomeLoss",
    "operating_cash_flow": "NetCashProvidedByUsedInOperatingActivities",
}
OUTPUT = ROOT / "data/processed/cpng-annual.json"


def normalize(payload: dict) -> list[dict]:
    if str(payload.get("cik")).zfill(10) != "0001834584":
        raise ValueError("Unexpected company CIK")
    records = []
    for year in (2023, 2024, 2025):
        for metric, tag in METRICS.items():
            candidates = payload.get("facts", {}).get("us-gaap", {}).get(tag, {}).get("units", {}).get("USD", [])
            matches = [r for r in candidates if r.get("accn") == ACCESSION
                       and r.get("form") == "10-K"
                       and r.get("start") == f"{year}-01-01"
                       and r.get("end") == f"{year}-12-31"]
            values = {r["val"] for r in matches}
            if len(values) != 1:
                raise ValueError(f"Missing or conflicting annual USD fact: {year}/{metric}")
            value = values.pop()
            if type(value) is not int:
                raise ValueError("Expected integer USD amount")
            r = matches[0]
            records.append({"year": year, "metric": metric, "value": value,
                            "unit": "USD", "scope": "consolidated", "tag": f"us-gaap:{tag}",
                            "start": r["start"], "end": r["end"], "filed": r["filed"],
                            "accession": ACCESSION, "form": "10-K", "source_url": FILING_URL})
    return records


def collect():
    # Single request with timeout; no automatic retry loop or on-request fetching.
    agent = os.environ.get("SEC_USER_AGENT", "FinanceDetective educational financial analysis project")
    request = Request(API_URL, headers={"User-Agent": agent, "Accept": "application/json"})
    with urlopen(request, timeout=30, context=ssl.create_default_context(cafile=certifi.where())) as response:
        raw = response.read()
    payload = json.loads(raw)
    records = normalize(payload)
    fetched = datetime.now(timezone.utc).isoformat()
    digest = hashlib.sha256(raw).hexdigest()
    raw_path = ROOT / "data/raw" / f"cpng-companyfacts-{digest[:16]}.json"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(raw)
    result = {"company": "Coupang, Inc.", "ticker": "CPNG", "cik": "0001834584",
              "selection_policy": "2023-2025 annual periods as presented in the 2025 10-K; not latest amendments",
              "fetched_at": fetched, "api_url": API_URL, "raw_sha256": digest,
              "raw_file": str(raw_path.relative_to(ROOT)), "records": records}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    temporary.replace(OUTPUT)
    return result


if __name__ == "__main__":
    argparse.ArgumentParser(description="Download and validate Coupang annual facts").parse_args()
    result = collect()
    print(f"Saved {len(result['records'])} facts to {OUTPUT}")
