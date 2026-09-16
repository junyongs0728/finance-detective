import json,re
from functools import lru_cache
from .common import ROOT,ProviderError,setting

ALIASES={"쿠팡":"SEC:CPNG","애플":"SEC:AAPL","마이크로소프트":"SEC:MSFT","엔비디아":"SEC:NVDA","테슬라":"SEC:TSLA","아마존":"SEC:AMZN","구글":"SEC:GOOGL","알파벳":"SEC:GOOGL","메타":"SEC:META","넷플릭스":"SEC:NFLX","네이버":"DART:035420","삼성":"DART:005930","삼성전자":"DART:005930","현대차":"DART:005380","현대자동차":"DART:005380"}

@lru_cache(maxsize=1)
def catalog():
    local = ROOT / "data/processed/company-registry.json"
    path = local if local.exists() else ROOT / "data/seed/company-registry.json"
    return json.loads(path.read_text())

def get_company(identifier):
    identifier=identifier.upper()
    if ":" not in identifier:identifier="SEC:"+identifier
    for c in catalog()["companies"]:
        if c["id"].upper()==identifier:return {**c,"evidence_ready":c["id"]=="SEC:CPNG","requires_key":c["provider"]=="DART" and not bool(setting("DART_API_KEY"))}
    raise ProviderError("기업 목록에서 찾을 수 없습니다. 기업명 또는 종목코드를 검색해주세요.","not_found")


def find_companies(query="",market="ALL",limit=20):
    q=query.strip().casefold()
    alias=ALIASES.get(query.strip())
    popular=["SEC:CPNG","SEC:AAPL","SEC:MSFT","SEC:NVDA","SEC:TSLA","DART:005930","DART:000660","DART:035420","DART:005380"]
    matches=[]
    for c in catalog()["companies"]:
        if market!="ALL" and c["provider"]!=market:continue
        hay=(c["name"]+" "+c["ticker"]).casefold()
        if q and q not in hay and c["id"]!=alias:continue
        score=0 if c["id"]==alias or c["ticker"].casefold()==q else 1 if c["name"].casefold()==q else 2
        if not q:score=popular.index(c["id"]) if c["id"] in popular else 100
        matches.append((score,c))
    matches.sort(key=lambda x:(x[0],x[1]["name"]))
    return {"results":[get_company(c["id"]) for _,c in matches[:limit]],"total":len(matches),"catalog_total":len(catalog()["companies"]),"directory_notice":"미국: SEC 목록 미러 스냅샷(선택 시 공식 신원 검증) · 한국: KRX 목록. 검색 등재가 재무 데이터 지원을 보장하지 않습니다.","dart_configured":bool(setting("DART_API_KEY"))}


def mentioned_companies(text):
    ids={cid for name,cid in ALIASES.items() if (re.search(r"삼성(?=$|\s|의)",text) if name=="삼성" else name in text)}
    # Tokenize once instead of compiling thousands of regexes per request.
    symbols=set(re.findall(r"(?<![A-Za-z0-9])[A-Z][A-Z0-9.-]+(?![A-Za-z0-9])",text))
    folded=text.casefold()
    for c in catalog()["companies"]:
        if c["ticker"] in symbols:ids.add(c["id"])
        if len(c["name"])>=4 and c["name"].casefold() in folded:ids.add(c["id"])
    return ids
