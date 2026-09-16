"""Deterministic numeric routing plus a bounded, cited RAG workflow."""
import re
from finance_detective.providers.registry import get_company, mentioned_companies
from finance_detective.providers.service import load_financials, summary
from finance_detective.rag.service import answer as rag_answer


def answer(message: str, company_id: str = "SEC:CPNG"):
    company = get_company(company_id)
    question = message.strip()
    base = {"mode": "rule_based", "company_id": company["id"], "company_name": company["name"],
            "scope": "", "rows": [], "evidence": [], "sources": [],
            "warnings": [], "suggestions": ["연간 매출과 영업이익 알려줘", "연간 영업이익률 비교해줘"]}
    def unavailable(text):
        return {**base, "status": "unsupported", "text": text, "steps": ["기업·질문 범위 확인"]}
    if not question:
        return unavailable("질문을 입력해주세요.")
    if mentioned_companies(question) - {company["id"]}:
        return unavailable("질문에 다른 기업이 포함되어 있습니다. 상단의 기업 검색에서 분석할 기업을 먼저 선택해주세요. 기업 간 비교는 아직 지원하지 않습니다.")
    if re.search(r"분기|반기|quarter|\bq[1-4]\b|예측|전망|주가|목표가|매수|매도|올해|작년|forecast|predict", question, re.I):
        return unavailable("현재는 선택한 기업의 연간 실적 조회를 지원합니다. 연도를 명시하거나 ‘연간 실적’을 요청해주세요. 분기·전망·투자 판단은 아직 지원하지 않습니다.")
    why = bool(re.search(r"왜|이유|원인|근거|주석|공시|설명|요약|정리|사업|제품|위험|리스크|경쟁|전략|어떻게|무엇|어떤|why|reason|evidence|business|risk|explain", question, re.I))
    topic = "cash_flow" if re.search(r"현금|cash", question, re.I) else "margin" if re.search(r"이익|마진|margin|income", question, re.I) else "revenue"
    if not why and not re.search(r"현금|매출|수익|영업|이익|마진|실적|재무|cash|revenue|sales|income|margin", question, re.I):
        return unavailable("매출·영업이익·영업현금흐름·매출 증가율·영업이익률을 조회할 수 있습니다. ‘연간 실적 알려줘’로 시작해보세요. 각 질문은 독립적으로 처리합니다.")
    data = load_financials(company["id"])
    rows = summary(data)
    years = sorted(set(map(int, re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", question))))
    if len(years) == 2 and re.search(r"~|부터|through|–|-", question):
        years = list(range(years[0], years[-1] + 1))
    if set(years) - {row["year"] for row in rows}:
        return unavailable("요청한 기간의 연간 수치가 모두 준비되어 있지 않습니다. 기업 선택 후 표시되는 기간을 확인해주세요.")
    if years: rows = [row for row in rows if row["year"] in years]
    base.update(rows=rows, company_name=data["company"], currency=data["currency"],
                scope=data["scope"], period_basis=data["period_basis"], warnings=data["warnings"],
                fetched_at=data["fetched_at"],
                sources=[{"label": data["company"] + " · " + data["filing"]["form"], "url": data["source_url"]}])
    if why:
        generated = rag_answer(question, data, rows)
        # Keep the structured numeric table only when the question actually asks about financial metrics.
        if not re.search(r"현금|매출|수익|영업|이익|마진|실적|재무|cash|revenue|income|margin",question,re.I):
            base["rows"] = []
        return {**base, **generated}
    return {**base, "status": "answered", "text": f"{data['company']}의 연간 실적입니다. 기간 기준은 {data['period_basis']}이며, 비율은 Python으로 계산했습니다.", "steps": ["기업 확인", "공시 수치 조회", "지표 계산"]}
