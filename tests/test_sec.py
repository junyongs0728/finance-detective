from copy import deepcopy
import pytest
from finance_detective.collectors.sec import normalize, METRICS, ACCESSION


def sample():
    return {"cik": 1834584, "facts": {"us-gaap": {
        tag: {"units": {"USD": [{"start": f"{y}-01-01", "end": f"{y}-12-31",
        "val": 100, "fy": 2025, "accn": ACCESSION, "form": "10-K", "filed": "2026-02-26"}
        for y in (2023, 2024, 2025)]}} for tag in METRICS.values()}}}


def test_actual_period_not_fiscal_year_and_exclude_quarter_and_other_filing():
    data = sample()
    rows = data["facts"]["us-gaap"][METRICS["revenue"]]["units"]["USD"]
    rows.extend([{**rows[2], "start": "2025-10-01", "val": 999},
                 {**rows[2], "accn": "other", "val": 999}])
    records = normalize(data)
    assert len(records) == 9
    assert {r["year"] for r in records} == {2023, 2024, 2025}
    assert all(r["value"] == 100 for r in records)


def test_missing_is_not_zero():
    data = sample()
    data["facts"]["us-gaap"][METRICS["revenue"]]["units"]["USD"].pop()
    with pytest.raises(ValueError, match="Missing"):
        normalize(data)


def test_conflicting_duplicate_is_rejected():
    data = sample()
    rows = data["facts"]["us-gaap"][METRICS["revenue"]]["units"]["USD"]
    rows.append({**rows[0], "val": 999})
    with pytest.raises(ValueError, match="conflicting"):
        normalize(data)


def test_wrong_company_is_rejected():
    data = sample(); data["cik"] = 1
    with pytest.raises(ValueError, match="CIK"):
        normalize(data)
