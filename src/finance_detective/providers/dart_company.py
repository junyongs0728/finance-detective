import io,json,zipfile,re
from urllib.parse import urlencode
from xml.etree import ElementTree
from datetime import date
from .common import ROOT,setting,fetch,fetch_json,ProviderError,write_json,preserve_raw,now

TAGS={"revenue":["ifrs-full_Revenue"],"operating_income":["dart_OperatingIncomeLoss","ifrs-full_ProfitLossFromOperatingActivities"],"operating_cash_flow":["ifrs-full_CashFlowsFromUsedInOperatingActivities"]}
NAMES={"revenue":{"매출액","수익(매출액)","매출"},"operating_income":{"영업이익","영업이익(손실)","영업손익"},"operating_cash_flow":{"영업활동현금흐름","영업활동으로인한현금흐름"}}


def key():
    value=setting("DART_API_KEY")
    if not value:raise ProviderError("한국 재무제표 조회에는 OpenDART 인증키가 필요합니다. 프로젝트 .env에 DART_API_KEY를 설정해주세요. 키는 채팅에 입력하지 마세요.","setup_required")
    return value


def corp_code(stock):
    path=ROOT/"data/processed/dart-corp-codes.json"
    if path.exists(): mapping=json.loads(path.read_text())
    else:
        raw=fetch("https://opendart.fss.or.kr/api/corpCode.xml?"+urlencode({"crtfc_key":key()}))
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as z:xml=z.read("CORPCODE.xml")
            root=ElementTree.fromstring(xml)
        except (zipfile.BadZipFile,KeyError,ElementTree.ParseError):raise ProviderError("DART 기업코드 목록을 받지 못했습니다. 인증키·접근 IP 설정을 확인해주세요.") from None
        mapping={item.findtext("stock_code","").strip():item.findtext("corp_code") for item in root.findall("list") if item.findtext("stock_code","").strip()}
        write_json(path,mapping)
    if stock not in mapping:raise ProviderError("DART 기업코드가 없습니다. 신규 상장 또는 미지원 기업일 수 있습니다.","unsupported")
    return mapping[stock]


def parse_amount(value):
    s=str(value or "").strip().replace(",","")
    if not s or s=="-":return None
    if s.startswith("(") and s.endswith(")"):s="-"+s[1:-1]
    return int(s) if re.fullmatch(r"-?\d+",s) else None


def normalize_dart(payload,company,year):
    rows=payload.get("list",[]);records=[];warnings=[]
    receipts={r.get("rcept_no") for r in rows if r.get("rcept_no")}
    if len(receipts)!=1:raise ProviderError("공시 접수번호가 없거나 여러 공시가 섞여 있습니다.")
    receipt=next(iter(receipts));url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt}"
    for metric,tags in TAGS.items():
        candidates=[r for r in rows if r.get("sj_div") in (("CF",) if metric=="operating_cash_flow" else ("IS","CIS"))]
        exact=[r for r in candidates if r.get("account_id") in tags]
        if exact:candidates=exact
        else:candidates=[r for r in candidates if re.sub(r"\s+","",r.get("account_nm","")) in NAMES[metric]]
        for offset,field in enumerate(("thstrm_amount","frmtrm_amount","bfefrmtrm_amount")):
            values={(r.get("currency") or "UNKNOWN",parse_amount(r.get(field))) for r in candidates if parse_amount(r.get(field)) is not None}
            if len(values)!=1:
                warnings.append(f"{year-offset} {metric}: 미공시 또는 계정 값 충돌");continue
            unit,value=next(iter(values))
            if unit=="UNKNOWN":warnings.append(f"{year-offset} {metric}: 통화 없음");continue
            records.append(dict(year=year-offset,period_label=str(year-offset),metric=metric,value=value,unit=unit,scope="consolidated",tag=candidates[0].get("account_id"),accession=receipt,source_url=url,form="사업보고서",start=None,end=None))
    units={r["unit"] for r in records}
    if len(units)!=1:raise ProviderError("통화가 섞였거나 지원하는 재무 수치가 없습니다.","unsupported")
    return dict(company=company["name"],company_id=company["id"],ticker=company["ticker"],provider="DART",currency=next(iter(units)),records=records,warnings=warnings,filing={"form":"사업보고서","end":str(year),"accession":receipt},source_url=url,scope="연결 재무제표(CFS)",period_basis="사업연도",selection_policy="DART 사업보고서 CFS 당기·전기·전전기 비교 수치; 별도 재무제표로 자동 대체하지 않음")


def collect_company(company):
    secret=key();code=corp_code(company["ticker"])
    # Probe at most two completed calendar years; no silent zero or OFS fallback.
    for year in (date.today().year-1,date.today().year-2):
        params={"crtfc_key":secret,"corp_code":code,"bsns_year":year,"reprt_code":"11011","fs_div":"CFS"}
        payload=fetch_json("https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json?"+urlencode(params))
        status=payload.get("status")
        if status=="013":continue
        if status!="000":raise ProviderError("DART 요청 실패: 코드 "+str(status)+". 인증키·권한·요청 한도를 확인해주세요.")
        if any(r.get("corp_code")!=code for r in payload.get("list",[])):raise ProviderError("DART 기업 식별자가 일치하지 않습니다.")
        result=normalize_dart(payload,company,year)
        result.update(fetched_at=now(),raw_sha256=preserve_raw(company["id"],payload));return result
    raise ProviderError("최근 2개 사업연도의 연결 재무제표가 없습니다. 별도 공시 또는 해당 업종 계정 지원이 필요할 수 있습니다.","unsupported")
