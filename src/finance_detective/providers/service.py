import json,threading
from collections import defaultdict
from datetime import datetime,timezone
from .common import ROOT,ProviderError,write_json
from .registry import get_company
from . import sec_company,dart_company
from finance_detective.analysis.metrics import percent

LOCKS=defaultdict(threading.Lock)

def load_financials(company_id,refresh=False):
    company=get_company(company_id)
    path=ROOT/"data/processed/companies"/(company["id"].replace(":","_")+".json")
    with LOCKS[company["id"]]:
        if path.exists() and not refresh:
            data=json.loads(path.read_text())
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(data["fetched_at"])).total_seconds()
            if age<86400:return data
        provider=sec_company if company["provider"]=="SEC" else dart_company
        data=provider.collect_company(company);write_json(path,data);return data


def summary(data):
    periods={}
    for r in data["records"]:
        if r["unit"]!=data["currency"]:raise ProviderError("서로 다른 통화는 합칠 수 없습니다.")
        label=r["period_label"]
        bucket=periods.setdefault(label,{"year":r["year"],"period_label":label,"start":r.get("start"),"end":r.get("end")})
        if r["metric"] in bucket:raise ProviderError("같은 기간의 계정이 중복되었습니다.")
        if bucket["start"]!=r.get("start"):raise ProviderError("같은 연도라도 수치의 시작일이 다릅니다.")
        bucket[r["metric"]]=r["value"]
    result=[]
    for row in sorted(periods.values(),key=lambda r:r["period_label"]):
        revenue=row.get("revenue");previous=result[-1] if result else {}
        prev_revenue=previous.get("revenue") if previous.get("year")==row["year"]-1 else None
        row["revenue_growth_pct"]=percent(revenue-prev_revenue,prev_revenue) if revenue is not None and prev_revenue is not None else None
        row["operating_margin_pct"]=percent(row.get("operating_income"),revenue)
        result.append(row)
    return result
