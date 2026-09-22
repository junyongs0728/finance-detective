# 재무탐정 · Finance Detective

미국·한국 기업의 공시를 검색하고, 재무 수치 계산과 출처 확인을 연결하는 AI 분석 웹 앱입니다.
React·FastAPI·LangChain·LangGraph·PostgreSQL/pgvector·Neo4j로 구현한 포트폴리오 MVP입니다.

**[전체 구조·기술 스택](docs/architecture.md)** · **[Agent·Graph 코드 설명](docs/agent-graph-guide.md)** · **[3분 시연 가이드](docs/demo-guide.md)**

**[프로젝트 소개 화면](showcase/index.html)** · **[제출용 소개 PDF](showcase/project-brief.pdf)** · **[지원·면접 근거 정리](docs/application-evidence.md)**

로컬 앱의 `/portfolio/`에서 실제 실행 사례 3개와 설계·실패 개선·평가 범위를 확인할 수 있습니다. `showcase/`는 API·DB 없이 별도로 열 수 있는 정적 소개 자료입니다. 실제 AI 호출이나 임의 질문 입력은 제공하지 않습니다. 소스 저장소는 비공개이며, 외부 공개 URL은 아직 없습니다.

## 현재 구현

- 기업명·종목코드 검색, 한국/미국 필터, 일부 미국 기업의 한국어 별칭
- OpenDART / SEC 표준 XBRL 기반 연간 매출·영업이익·영업현금흐름
- Python으로 계산한 매출 증가율·영업이익률
- 공시별 통화·기간 기준·원문 링크와 누락 데이터 표시
- 단순 수치 질문은 무료 조회, 복합 질문은 도구 선택 Agent, 별도 고정 RAG 모드
- PostgreSQL 문서·문단·실행 기록 + pgvector 벡터 검색
- pgvector 정확 검색 + BM25 검색, 출처 인용, 별도 근거 검토와 답변 유보
- 모델별 토큰·비용 기록, 호출 전 예산 예약, 개인/전체 한도, 검증된 답변 캐시
- 로컬 개발자 계정 / 배포용 이용 코드, React 사용량·캐시 비용 표시
- LangChain 도구 4개: 재무 조회·검증된 계산·공시 검색·근거 관계 탐색
- LangGraph 모델 선택 → 도구 실행 → 결과 관찰 루프와 횟수·시간·입력 제한
- 기업·공시·기간·관측값·지표·근거의 온톨로지, Neo4j Property Graph
- SQL 기준 스냅샷과 Neo4j 조회 결과 대조, 계산 카드·도구 기록·관계 탐색 UI
- 선택적으로 준비하는 쿠팡 2025 10-K의 BM25 본문 검색

Agent가 허용된 도구의 실행 순서를 실제로 선택합니다. 숫자는 Python이 계산하고 인용은 서버가 원문에서 복사합니다. [전체 구조](docs/architecture.md)에서 구현 범위와 운영 단계의 남은 과제를 설명합니다. 범용 투자 자문이나 모든 공시를 완전하게 분석하는 서비스는 아닙니다.

## 로컬 실행

Python 3.12 이상, Node.js 22.12 이상, 실행 중인 Docker Desktop이 필요합니다. 실제 검증 환경은 Python 3.14 / Node.js 24입니다.

```sh
git clone https://github.com/junyongs0728/finance-detective.git
cd finance-detective
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
.venv/bin/python scripts/setup_local.py
docker compose up -d --wait
npm ci --prefix frontend
npm run build --prefix frontend
.venv/bin/python -m uvicorn finance_detective.main:app --app-dir src --host 127.0.0.1 --port 8000 --no-proxy-headers
```

`.env`에 다음 항목을 직접 채우세요. 설정 스크립트는 기존 값을 유지하고 없는 항목만 채웁니다.

| 설정 | 용도 |
|---|---|
| `DART_API_KEY` | 한국 재무정보 조회용 OpenDART 인증키 |
| `SEC_USER_AGENT` | `"FinanceDetective 실제연락이메일"` 형태의 SEC 요청 식별 정보 |
| `OPENAI_API_KEY` | 설명 질문의 문서 임베딩·답변 생성·근거 검토용. 수치 조회만 할 때는 필요 없음 |
| `OPENAI_MODEL` | 기본값 `gpt-4.1-mini` |
| `OPENAI_AGENT_MODEL` | 도구 선택 모델, 기본값 `gpt-4.1-mini` |
| `OPENAI_REVIEW_MODEL` | 근거 검토 기본값 `gpt-4.1` |
| `OPENAI_EMBEDDING_MODEL` | 기본값 `text-embedding-3-small`, 512차원 |
| `DATABASE_URL` / `POSTGRES_PASSWORD` | 설정 스크립트가 생성, DB는 localhost:55432 |
| `NEO4J_URI` / `NEO4J_USERNAME` / `NEO4J_PASSWORD` | 설정 스크립트가 준비, Bolt localhost:7687, 관리 화면 localhost:7474 |
| `AGENT_MAX_STEPS` / `AGENT_MAX_TOOL_CALLS` | 모델 선택 기본 6회 / 도구 실행 기본 8회 |
| `AGENT_TIMEOUT_SECONDS` | 도구 루프 기본 120초. 마지막 생성·검토 시간은 별도 |
| `AI_AUTH_MODE` | 로컬 `local`, 외부 배포는 `token` 필수 |
| `AI_DAILY_BUDGET_USD` / `AI_MONTHLY_BUDGET_USD` | 전체 기본 $5/일, $30/월 |
| `AI_USER_DAILY_BUDGET_USD` / `AI_USER_DAILY_REQUESTS` | 사용자 기본 $1/일, 분석 50회/일 |
| `AI_REQUEST_BUDGET_USD` | 분석 작업당 $0.15 |
| `AI_CACHE_TTL_SECONDS` | 동일 사용자·질문·공시·모델·프롬프트의 답변 재사용, 24시간 |

기존 SQLite 사용자는 서버를 멈춘 상태에서 `.venv/bin/python scripts/migrate_sqlite.py`를 한 번 실행하세요. 원본을 보존하며 문단·임베딩·실행 기록을 검증해서 이전합니다. 재실행 가능하고 임베딩 API를 호출하지 않습니다. 새 설치는 서버 시작 시 빈 PostgreSQL 스키마를 준비합니다.

- 앱: http://127.0.0.1:8000/
- 프로젝트 소개: http://127.0.0.1:8000/portfolio/
- API 문서: http://127.0.0.1:8000/docs
- 개발 중에는 `npm run dev --prefix frontend`로 Vite를 실행할 수 있습니다. `/api` 요청은 8000 포트로 전달됩니다.

인증키는 백엔드에서만 사용합니다. `.env`, 다운로드한 공시, 실행 캐시, 가상환경, 빌드 결과는 Git에서 제외됩니다.

## 사용 흐름

1. 기업명 또는 종목코드로 검색합니다.
2. 기업을 선택하면 연간 재무표와 출처를 조회합니다.
3. `연간 매출과 영업이익 알려줘` 또는 `2025년 영업이익률 알려줘`처럼 질문합니다.
4. `2025년 영업현금흐름과 영업이익 차이를 계산하고 근거 경로를 보여줘`로 계산·도구 기록·관계를 확인합니다.
5. `주요 사업을 공시 근거로 설명해줘`로 AI 답변을 요청합니다. 처음에는 해당 공시를 준비하며 진행 상태를 표시합니다. 공시 서술문과 질문이 OpenAI API로 전송되고 API 비용이 발생합니다.
6. 기업을 바꾸면 이전 대화가 초기화됩니다. 각 질문은 독립적으로 처리합니다. ‘자동’은 단순 조회와 Agent를 구분하고, ‘AI 심층 분석’은 Agent, ‘공시 검색 답변’은 설명 질문의 고정 RAG 경로입니다.

| API | 역할 |
|---|---|
| `GET /api/companies?q=삼성전자&market=DART` | 기업 검색 |
| `GET /api/company-data/DART:005930` | 한국 기업 연간 수치 |
| `GET /api/company-data/SEC:AAPL` | 미국 기업 연간 수치 |
| `POST /api/chat` | `company_id`, `message`, `engine: auto/rag/agent` |
| `GET /api/agent/runs/{run_id}` | 본인 분석의 도구 실행·결과 기록 |
| `GET /api/graph/{snapshot_id}` | 본인 분석에 연결된 실제 Neo4j 관계 조회 |

## 데이터 범위와 한계

- 기본 기업 목록은 `data/seed/company-registry.json`의 공개 스냅샷입니다. 미국 목록은 SEC 목록의 미러로 오래되거나 누락된 종목이 있을 수 있습니다. 한국 목록은 KRX 출처입니다. 검색 등재가 재무 데이터 지원을 보장하지 않습니다.
- 미국 데이터는 회사별 최근 보고 기간의 연간 공시/수정공시를 선택합니다. 실제 회계연도 시작·종료일과 표준 태그를 확인하며, 달력 연도와 같다고 가정하지 않습니다.
- 한국 데이터는 최근 완료된 2개 사업연도 중 조회 가능한 연결(CFS) 사업보고서를 사용합니다. 별도(OFS)로 자동 대체하지 않습니다.
- 기업 전용 계정, 일부 금융업, 지원하지 않는 공시 등은 추가 매핑이 필요합니다. 누락 수치를 0으로 채우지 않습니다.
- 성공한 재무 수집 결과는 로컬에서 24시간 재사용합니다. 현재 분기·예측·기업 간 비교·대화 기억은 지원하지 않습니다.
- 새 RAG는 선택한 SEC 연간 HTML / DART 접수번호의 본 XML에서 서술문을 수집합니다. 표·첨부·이미지/OCR는 포함하지 않습니다. 삼성전자·애플에서 검증했으며, 모든 기업의 문서 형식을 보장하지는 않습니다.
- 출처 ID와 인용 원문 일치는 코드로 확인하고, 별도 LLM 호출이 주장의 근거를 검토합니다. 의미 정확성·답변 완전성을 보장하지 않습니다.
- 원문 크기 40MB, 문단 1,600개, 동시 준비 2건으로 제한합니다. 인덱스는 공시·파서·임베딩 모델 버전별로 재사용합니다.

## 선택: 쿠팡 검색 기준선 준비

공시 원문과 검색 색인은 저장소에 포함하지 않습니다. 원래 쿠팡 실험을 재현하려면 `.env` 설정 후 실행합니다.

```sh
.venv/bin/python scripts/prepare_coupang.py
PYTHONPATH=src .venv/bin/python -m finance_detective.retrieval.evaluate
```

SEC 수치와 [쿠팡 공식 IR PDF](https://s206.q4cdn.com/919117365/files/doc_financials/2026/ar/Coupang-Inc-_10-K_2026_V3_PWO-65955-FINAL.pdf)를 내려받습니다. PDF 페이지별 240단어 창과 60단어 중첩으로 BM25 검색을 수행합니다. 한국어 주제는 고정 영어 검색어로 매핑하며, 의미 검색이나 LLM 답변은 아닙니다. 숫자 계산에는 PDF 대신 구조화된 재무 API를 사용합니다.

`evals/`의 기존 결과는 작은 개발 집합에 대한 실험 기록이며 일반 성능을 뜻하지 않습니다. 이전 쿠팡 전용 `/legacy`, `/api/companies/CPNG/...`는 호환용입니다.

## 검증

GitHub Actions는 `main` push·PR에서 고정 의존성 설치, PostgreSQL·Neo4j 통합 검사, React 빌드를 실행합니다. CI는 임시 DB와 합성 모델 응답을 사용하며 유료 API 키를 사용하지 않습니다.

```sh
.venv/bin/python -m pytest -q
npm run build --prefix frontend
```

테스트는 고정 공개 수치와 합성 모델 응답을 사용하며 실제 PostgreSQL·Neo4j가 필요합니다 (`docker compose up -d --wait`). 테스트마다 임시 SQL 스키마·Graph namespace를 만들고 삭제하며 운영 데이터는 건드리지 않습니다. 외부 API 인증키·호출·다운로드된 PDF는 필요하지 않습니다.
실제 RAG 개발 평가: 삼성전자·애플·쿠팡에 먼저 설명 질문을 한 뒤 `.venv/bin/python scripts/evaluate_rag.py`. 이 평가는 유료 API를 호출하며 결과를 `data/processed/rag-evaluation.json`에 저장합니다. 실제 공급자 연결 및 브라우저 확인과 오프라인 단위 검사를 구분합니다.

Agent 개발 평가: 서버 실행 후 `.venv/bin/python scripts/evaluate_agent.py --live`. **유료 API 호출**을 포함하며, 고정 8개 질문의 도구 선택·계산·인용 문자열·Graph 일치·범위 차단을 확인합니다. [관측 결과](evals/agent-report.json)와 [실패 개선 기록](docs/agent-graph-guide.md)을 참고하세요. 이 결과를 일반 정확도나 환각률로 표현하지 않습니다.

## 코드 구조

```text
frontend/src/                 React 기업 검색·채팅
src/finance_detective/
  main.py                    REST API와 화면 제공
  chat.py                    규칙 기반 질문 라우팅
  providers/                 SEC / OpenDART 수집·정규화·캐시
  analysis/                  재무 비율 계산
  retrieval/                 최초 쿠팡 BM25 검색과 개발 평가
  rag/                       PostgreSQL·pgvector·비용 예약·캐시·검색·생성·검증
  auth.py                    로컬/이용 코드 사용자 식별
  collectors/                최초 쿠팡 수집 기준선
  agents/                    LangChain 도구·모델 연결, LangGraph 실행 제어
  knowledge/                 온톨로지, SQL 스냅샷, Neo4j 투영·검증·조회
scripts/                     선택적 데이터 준비
data/seed/                   공개 검색 목록
tests/                       외부 API 없는 검증, 로컬 PostgreSQL·Neo4j 사용
docs/                        구현 설명·설계·학습 기록
```

## 다음 단계와 학습 기록

1. 검색 정답 데이터·사람 검토를 늘려 공시 형식과 질문 범위 확대
2. 복합·다기간 질문의 도구 선택 평가와 재무 항목 매핑 확대
3. 작업 큐·복구·Graph 속성 이력·DB 마이그레이션 운영 개선
4. 외부 시연 배포, 접근 제어, 부하·백업·모니터링 검증

- [PostgreSQL 전환과 AI 비용 제어](docs/postgres-cost-guide.md)
- [기업 검색 구현과 AI 학습 계획](docs/company-search-guide.md)
- [AI 엔지니어링 구현 설명](docs/ai-engineering-guide.md)
- [React 채팅 구현 설명](docs/react-chat-guide.md)
- [재무 개념 참고 노트](docs/finance-reference.md)

일부 문서는 초기 단계의 실험 기록입니다. 현재 기능 범위는 이 README와 [전체 구조](docs/architecture.md)를 기준으로 확인하세요.

## 비용 확인과 외부 배포 준비

상단 ‘공시 근거 AI’를 누르면 오늘의 사용량을 확인할 수 있습니다. 새 공시 준비와 새 답변 분석은 각각 1회로 계산하며 실패한 실행도 횟수에 포함합니다. 수치 조회와 캐시 응답은 AI 횟수·토큰을 사용하지 않습니다. 일/월 기준은 UTC입니다.

```sh
.venv/bin/python scripts/cost_report.py
.venv/bin/python scripts/create_access_token.py --user reviewer
```

이용 코드는 무시되는 `data/processed/access-reviewer.txt`에 생성됩니다. 외부 배포에서는 `AI_AUTH_MODE=token`과 HTTPS를 설정한 후 이용 코드를 배포합니다. 같은 사용자 코드 재발급은 기존 코드를 무효화합니다. 공개 회원가입·결제·SSO는 구현하지 않았습니다. `local` 모드는 로컬 IP/Host만 허용하며 reverse proxy 뒤에서 사용하면 안 됩니다.

금액은 요금표와 응답 usage 기반의 **예상 API 비용**입니다. 세금·환율·서버·DB 비용, 전환 전 호출 및 다른 앱에서 같은 키로 쓴 비용은 포함하지 않습니다. 시간 초과 등 청구 여부가 불확실한 호출은 예약금을 계속 보유합니다. 예약 합계로 다음 호출을 차단하므로 설정 한도보다 보수적으로 멈출 수 있습니다. 자세한 정산·장애 복구·보안 범위는 비용 제어 문서를 보세요.
