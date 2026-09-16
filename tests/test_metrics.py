import pytest
from finance_detective.analysis.metrics import percent, summarize


def record(year, metric, value):
    return dict(year=year, metric=metric, value=value, unit="USD", scope="consolidated", start=f"{year}-01-01", end=f"{year}-12-31", accession="same")


def test_real_revenue_growth_and_margin():
    rows = summarize([record(2024,"revenue",30268000000),record(2025,"revenue",34534000000),record(2025,"operating_income",473000000)])
    assert rows[0]["revenue_growth_pct"] is None
    assert rows[1]["revenue_growth_pct"] == 14.09
    assert rows[1]["operating_margin_pct"] == 1.37


def test_zero_missing_and_loss():
    assert percent(0,100) == 0
    assert percent(-10,100) == -10
    assert percent(10,0) is None
    assert percent(None,100) is None
    assert percent(10,-100) is None


def test_non_consecutive_years_not_yoy():
    rows=summarize([record(2023,"revenue",100),record(2025,"revenue",200)])
    assert rows[-1]["revenue_growth_pct"] is None


def test_mixed_units_and_duplicates_rejected():
    r=record(2025,"revenue",100)
    with pytest.raises(ValueError): summarize([r,r])
    with pytest.raises(ValueError): summarize([{**r,"unit":"KRW"}])
