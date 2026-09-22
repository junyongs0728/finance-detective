from pathlib import Path
from contextlib import asynccontextmanager
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from finance_detective.rag import service as rag_service, store as rag_store
from finance_detective.rag import billing
from finance_detective.agents import workflow as agent_workflow
from finance_detective.knowledge import graph as knowledge_graph
from finance_detective import auth
from finance_detective.chat import answer
from finance_detective.retrieval.evidence import INDEX, PRESETS, search
from typing import Literal
from fastapi import Query, Request
from fastapi.responses import JSONResponse
from finance_detective.providers.common import ProviderError, setting
from finance_detective.providers.registry import find_companies, get_company
from finance_detective.providers.service import load_financials, summary as company_summary
from html import escape
from finance_detective.analysis.metrics import summarize
import json
from finance_detective.collectors.sec import OUTPUT
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

@asynccontextmanager
async def lifespan(app):
    rag_store.initialize()
    yield
    rag_service.POOL.shutdown(wait=True)
    knowledge_graph.close()
    rag_store.close()

app = FastAPI(title="재무탐정", version="0.3.0", lifespan=lifespan,
              description="미국 SEC · 한국 OpenDART 기업 검색과 연간 재무정보 조회")

COMPANY = {
    "name": "Coupang, Inc.", "ticker": "CPNG", "cik": "0001834584",
    "scope": "consolidated", "source": "SEC EDGAR", "analysis_status": "not_implemented",
    "annual_report": {
        "form": "10-K", "period_end": "2025-12-31",
        "url": "https://www.sec.gov/Archives/edgar/data/1834584/000183458426000024/cpng-20251231.htm",
    },
}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.exception_handler(ProviderError)
def provider_error(request: Request, exc: ProviderError):
    status = {"not_found":404,"unsupported":422,"ai_auth_required":401,"ai_forbidden":403,
              "ai_input_limit":422,"ai_user_limit":429,"ai_budget_exceeded":429,"ai_busy":429}.get(exc.code,503)
    return JSONResponse(status_code=status, content={"detail": str(exc), "code": exc.code})


@app.get('/api/session')
def session(request: Request):
    user=auth.resolve(request)
    return {'mode':setting('AI_AUTH_MODE') or 'token','authenticated':bool(user),
            'usage':billing.usage(user) if user else None}


class AccessRequest(BaseModel):
    code: str = Field(min_length=20,max_length=200)


@app.post('/api/session')
def login(payload: AccessRequest,request: Request):
    auth.check_origin(request)
    user=auth.token_user(payload.code)
    if not user:raise ProviderError('이용 코드가 올바르지 않습니다.','ai_auth_required')
    response=JSONResponse({'authenticated':True,'usage':billing.usage(user)})
    response.set_cookie(auth.COOKIE,payload.code,httponly=True,samesite='strict',
                        secure=request.url.scheme=='https',max_age=86400)
    return response


@app.delete('/api/session')
def logout(request: Request):
    auth.check_origin(request)
    response=JSONResponse({'authenticated':False})
    response.delete_cookie(auth.COOKIE)
    return response


@app.get("/api/companies")
def search_companies(q: str = Query(default="", max_length=100), market: Literal["ALL", "SEC", "DART"] = "ALL"):
    return find_companies(q, market)


@app.get("/api/company-data/{company_id}")
def company_data(company_id: str):
    data = load_financials(company_id)
    return {"company": get_company(company_id), "rows": company_summary(data),
            "name": data["company"], "currency": data["currency"], "scope": data["scope"],
            "period_basis": data["period_basis"], "filing": data["filing"],
            "source_url": data["source_url"], "fetched_at": data["fetched_at"],
            "warnings": data["warnings"], "selection_policy": data["selection_policy"]}


@app.get("/api/rag/status/{document_id}")
def rag_status(document_id: str):
    document = rag_store.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="준비 중인 공시를 찾지 못했습니다.")
    return rag_service.public_status(document)


@app.post("/api/rag/prepare/{company_id}")
def prepare_rag(company_id: str,request: Request):
    with billing.as_user(auth.resolve(request,required=True)):
        return rag_service.prepare(load_financials(company_id))


@app.get("/api/companies/{ticker}")
def company(ticker: str):
    if ticker.upper() != "CPNG":
        raise HTTPException(status_code=404, detail="현재 지원 대상은 CPNG입니다.")
    return COMPANY

@app.get("/api/companies/{ticker}/financials")
def financials(ticker: str):
    company(ticker)
    if not OUTPUT.exists():
        raise HTTPException(status_code=503, detail="먼저 SEC 수집기를 실행해주세요.")
    return json.loads(OUTPUT.read_text())

@app.get("/api/companies/{ticker}/metrics")
def metrics(ticker: str):
    data = financials(ticker)
    return {"ticker": ticker.upper(), "amount_unit": "USD", "rate_unit": "percent",
            "rows": summarize(data["records"]), "source": data}

@app.get("/api/companies/{ticker}/evidence")
def evidence(ticker: str, q: str = Query(default="", max_length=300), topic: str | None = None):
    company(ticker)
    if topic is not None and topic not in PRESETS:
        raise HTTPException(status_code=422, detail="Unknown topic")
    if not topic and not q.strip():
        raise HTTPException(status_code=422, detail="Enter an English query or select a topic")
    if not INDEX.exists():
        raise HTTPException(status_code=503, detail="먼저 보고서를 색인해주세요.")
    return search(q, topic)

@app.get("/legacy", response_class=HTMLResponse, include_in_schema=False)
def home():
    try:
        data = financials("CPNG")
    except HTTPException as exc:
        return HTMLResponse("<h1>재무탐정</h1><p>데이터 수집이 필요합니다. SEC 수집기를 실행해주세요.</p>", status_code=exc.status_code)
    rows = summarize(data["records"])
    def amount(value):
        return "—" if value is None else f"{value / 1_000_000:,.0f}"
    def rate(value):
        return "—" if value is None else f"{value:.2f}%"
    body = "".join(
        f"<tr><th>{r['year']}</th><td>{amount(r.get('revenue'))}</td>"
        f"<td>{amount(r.get('operating_income'))}</td><td>{amount(r.get('operating_cash_flow'))}</td>"
        f"<td>{rate(r['revenue_growth_pct'])}</td><td>{rate(r['operating_margin_pct'])}</td></tr>" for r in rows)
    source = escape(COMPANY["annual_report"]["url"], quote=True)
    return """<!doctype html><html lang="ko"><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>재무탐정</title>
    <style>body{font-family:system-ui;background:#101b25;color:#eef3f3;max-width:1100px;margin:7vh auto;padding:24px;line-height:1.8}h1{font-size:44px;line-height:1.2}a,.tag{color:#8be5be}section{border:1px solid #3e505f;border-radius:16px;padding:24px;margin-top:24px}.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;white-space:nowrap}th,td{padding:14px;text-align:right;border-bottom:1px solid #3e505f}th:first-child{text-align:left}p{color:#ccd7df}</style>
    <p class="tag">FINANCE DETECTIVE / CPNG</p><h1>재무탐정</h1>
    <p>숫자 뒤의 주석을 추적하다.</p>
    <section><h2>쿠팡의 이익과 현금</h2><p>Coupang, Inc. 연결 기준 · 금액 단위: 백만 USD</p>
    <div class="scroll"><table><thead><tr><th>연도</th><th>매출</th><th>영업이익</th><th>영업현금흐름</th><th>매출 증가율</th><th>영업이익률</th></tr></thead><tbody>""" + body + """</tbody></table></div>
    <p>매출 증가율 = (당년 매출 − 전년 매출) ÷ 전년 매출 × 100<br>
    영업이익률 = 영업이익 ÷ 매출 × 100</p>
    <p>—는 비교 데이터가 없거나 분모가 0 이하라 계산하지 않은 값입니다. 비율은 소수 둘째 자리에서 표시합니다.</p></section>
    <section><h2>이 숫자의 근거</h2><p>2025년 10-K에 수록된 2023–2025년 비교 수치입니다. 최신 정정 공시를 자동 반영하지 않습니다.</p>
    <a href=""" + '"' + source + '"' + """>SEC 원문 확인</a> · <a href="/api/companies/CPNG/metrics">계산 결과와 출처</a> · <a href="/docs">API 문서</a>
    <p>현재는 데이터 조회와 계산 단계입니다. 변화 원인을 설명하는 AI 분석은 아직 구현하지 않았습니다.</p></section>
    <section><h2>공시 근거 탐색</h2><p>한글 주제 버튼은 정해진 영어 검색어로 검색합니다. 자유 검색은 영어 키워드를 입력하세요.</p>
    <button onclick="lookup('cash_flow')">현금흐름 감소</button>
    <button onclick="lookup('revenue')">매출 성장</button>
    <button onclick="lookup('margin')">영업이익률</button>
    <form id="searchform"><label for="query">영어 검색어</label> <input id="query" maxlength="300" placeholder="accounts receivable"><button>검색</button></form>
    <p>검색 점수는 신뢰도가 아닙니다. 아래 내용은 영문 원문 발췌입니다.</p><div id="evidence" aria-live="polite"></div></section>
    <script>
    let requestNumber=0;
    async function lookup(topic){
      const current=++requestNumber;
      const box=document.getElementById('evidence');box.textContent='검색 중…';
      const params=new URLSearchParams(topic?{topic}:{q:document.getElementById('query').value});
      try{
        const response=await fetch('/api/companies/CPNG/evidence?'+params);
        const data=await response.json();if(current!==requestNumber)return;
        if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'검색어를 확인해주세요.');
        box.replaceChildren();const info=document.createElement('p');info.textContent='실제 검색어: '+data.effective_query;box.append(info);
        if(!data.results.length){box.append('일치하는 근거가 없습니다. 다른 영어 키워드를 사용해보세요.');return;}
        for(const item of data.results){const article=document.createElement('article');const link=document.createElement('a');link.href=item.source_url;link.target='_blank';link.rel='noopener';link.textContent='PDF '+item.page+'쪽 · 검색 점수 '+item.score;const text=document.createElement('p');text.textContent=item.text;article.append(link,text);box.append(article);}
      }catch(error){if(current===requestNumber)box.textContent='검색 실패: '+error.message;}
    }
    document.getElementById('searchform').addEventListener('submit',event=>{event.preventDefault();lookup();});
    </script></html>"""


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    company_id: str = Field(default="SEC:CPNG", min_length=1, max_length=40)
    engine: Literal['auto','rag','agent'] = 'auto'


@app.post("/api/chat")
def chat(payload: ChatRequest,request: Request):
    if not payload.message.strip():
        raise HTTPException(status_code=422, detail="질문을 입력해주세요.")
    try:
        with billing.as_user(auth.resolve(request)):
            return answer(payload.message, payload.company_id, payload.engine)
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="분석 자료가 준비되지 않았습니다. 수집과 색인을 먼저 실행해주세요.")


@app.get('/api/agent/runs/{run_id}')
def agent_run(run_id: str,request: Request):
    return agent_workflow.get_run(run_id,auth.resolve(request,required=True))


@app.get('/api/graph/{snapshot_id}')
def evidence_graph(snapshot_id: str,request: Request):
    # Only users with an analysis containing this snapshot can retrieve its projection.
    user=auth.resolve(request,required=True)
    with rag_store.connection() as db:
        allowed=db.execute('SELECT 1 FROM agent_runs WHERE snapshot_id=%s AND user_id=%s LIMIT 1',(snapshot_id,user)).fetchone()
    if not allowed:raise ProviderError('이 사용자의 근거 관계를 찾지 못했습니다.','not_found')
    return knowledge_graph.read(snapshot_id)


FRONTEND = Path(__file__).resolve().parents[2] / "frontend/dist"
SHOWCASE = Path(__file__).resolve().parents[2] / "showcase"
if SHOWCASE.exists():
    app.mount("/portfolio", StaticFiles(directory=SHOWCASE, html=True), name="portfolio")

if (FRONTEND / "assets").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND / "assets"), name="assets")

@app.get("/", include_in_schema=False)
def react_home():
    if not (FRONTEND / "index.html").exists():
        return HTMLResponse("React 화면을 빌드해주세요: cd frontend &amp;&amp; npm run build", status_code=503)
    return FileResponse(FRONTEND / "index.html", headers={"Cache-Control":"no-cache"})
