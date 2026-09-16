"""Deterministic annual metrics, with explicit unavailable values."""
from decimal import Decimal, ROUND_HALF_UP


def percent(numerator, denominator):
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return float((Decimal(numerator) / Decimal(denominator) * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def summarize(records):
    years = {}
    seen = set()
    for record in records:
        if record["unit"] != "USD" or record["scope"] != "consolidated":
            raise ValueError("Expected consolidated USD records")
        year = record["year"]
        if record["start"] != f"{year}-01-01" or record["end"] != f"{year}-12-31":
            raise ValueError("Expected complete calendar year")
        key = (year, record["metric"])
        if key in seen:
            raise ValueError("Duplicate metric")
        seen.add(key)
        years.setdefault(year, {})[record["metric"]] = record["value"]
    if len({r["accession"] for r in records}) > 1:
        raise ValueError("Mixed filing snapshots")
    result = []
    for year, values in sorted(years.items()):
        revenue = values.get("revenue")
        previous = years.get(year - 1, {}).get("revenue")
        result.append({"year": year, **values,
            "revenue_growth_pct": percent(revenue - previous, previous) if revenue is not None and previous is not None else None,
            "operating_margin_pct": percent(values.get("operating_income"), revenue)})
    return result
