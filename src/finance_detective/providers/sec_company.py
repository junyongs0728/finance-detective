from datetime import date
from collections import Counter
from .common import fetch_json,ProviderError,preserve_raw,now

TAGS={
 "revenue":[("us-gaap","RevenueFromContractWithCustomerExcludingAssessedTax"),("us-gaap","Revenues"),("us-gaap","SalesRevenueNet"),("ifrs-full","Revenue")],
 "operating_income":[("us-gaap","OperatingIncomeLoss"),("ifrs-full","ProfitLossFromOperatingActivities")],
 "operating_cash_flow":[("us-gaap","NetCashProvidedByUsedInOperatingActivities"),("ifrs-full","CashFlowsFromUsedInOperatingActivities")],
}


def choose_filing(submissions):
    recent=submissions.get("filings",{}).get("recent",{})
    filings=[]
    for i,form in enumerate(recent.get("form",[])):
        if form not in ("10-K","10-K/A","20-F","20-F/A","40-F","40-F/A"):continue
        def field(k):return recent.get(k,[""]*len(recent["form"]))[i]
        if not field("reportDate"):continue
        filings.append(dict(form=form,accession=field("accessionNumber"),filed=field("filingDate"),end=field("reportDate"),document=field("primaryDocument")))
    if not filings:raise ProviderError("최근 공시 목록에서 지원하는 연간 보고서를 찾지 못했습니다.","unsupported")
    # Last report period first, then latest amendment for that period. No silent fallback.
    return max(filings,key=lambda f:(f["end"],f["filed"],f["accession"]))


def annual(row,filing):
    try:duration=(date.fromisoformat(row["end"])-date.fromisoformat(row["start"])).days
    except (KeyError,ValueError):return False
    return row.get("accn")==filing["accession"] and 330<=duration<=380 and row["end"]<=filing["end"]


def normalize_company(payload,company,filing):
    if str(payload.get("cik")).zfill(10)!=company["cik"]:raise ProviderError("기업 식별자가 일치하지 않습니다.")
    all_candidates={}
    currencies=Counter()
    for metric,aliases in TAGS.items():
        items=[]
        for priority,(namespace,tag) in enumerate(aliases):
            for unit,rows in payload.get("facts",{}).get(namespace,{}).get(tag,{}).get("units",{}).items():
                if not (len(unit)==3 and unit.isalpha() and unit.isupper()):continue
                for row in rows:
                    if annual(row,filing) and type(row.get("val")) is int:
                        items.append((priority,namespace+":"+tag,unit,row))
                        currencies[unit]+=1
        all_candidates[metric]=items
    if not currencies:raise ProviderError("선택된 연간 공시에서 표준 재무 태그를 찾지 못했습니다. 전용 태그·수정공시·금융업 등은 추가 매핑이 필요할 수 있습니다.","unsupported")
    currency="USD" if "USD" in currencies else currencies.most_common(1)[0][0]
    ends=sorted({r["end"] for items in all_candidates.values() for _,_,u,r in items if u==currency},reverse=True)[:3]
    records=[];warnings=[]
    source=f"https://www.sec.gov/Archives/edgar/data/{int(company['cik'])}/{filing['accession'].replace('-','')}/{filing['document']}"
    for end in sorted(ends):
        for metric,items in all_candidates.items():
            matching=[i for i in items if i[2]==currency and i[3]["end"]==end]
            if not matching:
                warnings.append(f"{end} {metric}: 지원하는 표준 태그 없음");continue
            best=min(i[0] for i in matching);selected=[i for i in matching if i[0]==best]
            values={(i[3]["start"],i[3]["val"]) for i in selected}
            if len(values)!=1:
                warnings.append(f"{end} {metric}: 기간·값 충돌로 제외");continue
            _,tag,unit,row=selected[0]
            records.append(dict(year=int(end[:4]),period_label=end,start=row["start"],end=end,metric=metric,value=row["val"],unit=unit,scope="entity-wide",tag=tag,accession=filing["accession"],form=filing["form"],source_url=source))
    if not records:raise ProviderError("검증을 통과한 연간 수치가 없습니다.","unsupported")
    return dict(company=company["name"],company_id=company["id"],ticker=company["ticker"],provider="SEC",currency=currency,records=records,warnings=warnings,filing=filing,source_url=source,period_basis="회계연도 종료일",scope="공시 기업 전체 · SEC 표준 XBRL",selection_policy="최근 보고 기간의 마지막 연간 공시/수정공시 내 비교 수치; 자동 이전 공시 대체 없음")


def collect_company(company):
    cik=company["cik"]
    submissions=fetch_json(f"https://data.sec.gov/submissions/CIK{cik}.json")
    if company["ticker"].upper() not in [t.upper() for t in submissions.get("tickers",[])]:
        raise ProviderError("기업 목록의 종목코드가 현재 SEC 정보와 다릅니다. 목록을 갱신해야 합니다.","stale_directory")
    company={**company,"name":submissions["name"]}
    filing=choose_filing(submissions)
    payload=fetch_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
    data=normalize_company(payload,company,filing)
    data.update(fetched_at=now(),raw_sha256=preserve_raw(company["id"],payload))
    return data
