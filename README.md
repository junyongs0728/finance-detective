# 재무탐정 · Finance Detective

[![Verify application](https://github.com/junyongs0728/finance-detective/actions/workflows/verify.yml/badge.svg)](https://github.com/junyongs0728/finance-detective/actions/workflows/verify.yml)

미국 SEC·한국 OpenDART 공시를 검색하고, 재무 수치의 계산 결과와 원문 근거를 함께 확인하는 웹 앱입니다. 기업을 선택해 질문하면 수치 조회, 공시 검색, 계산, 근거 추적을 연결합니다.

**[아키텍처](docs/architecture.md)** · **[설계 결정과 대안](docs/design-decisions.md)** · **[실행 예시](docs/demo-guide.md)** · **[평가와 재현 방법](docs/evaluation.md)**

## 어떤 질문을 처리하나요?

| 질문 예시 | 처리 방식 | 확인할 결과 |
|---|---|---|
| `2025년 영업이익 알려줘` | SEC/DART 수치 조회, Python 계산. LLM 호출 없음 | 금액·통화·기간·공시 링크 |
| `애플이 공시한 공급망 리스크를 설명해줘` | 공시 검색 → 주장 생성 → 인용 대조 → 별도 근거 검토 | 주장별 원문 인용, 출처, 검색 범위 |
| `2025년 영업현금흐름에서 영업이익을 뺀 차이를 계산하고 원본 근거 경로를 보여줘` | Agent가 재무 조회·계산·관계 조회 도구 선택 | 계산식, 원본 값, 도구 실행 기록, 근거 경로 |

선택 기업의 연간 매출·영업이익·영업현금흐름을 지원합니다. 근거가 부족하거나 지원 범위를 벗어난 질문에는 답변을 보류하거나 범위를 안내합니다. 각 질문은 독립적으로 처리합니다.

## 구조

```text
React → FastAPI → 질문 범위 확인
                   ├─ 단순 수치: SEC / OpenDART → Python 계산
                   ├─ 고정 RAG: pgvector + BM25 → 생성 → 인용·근거 검토
                   └─ Agent: LangGraph → LangChain 도구 호출 → 결과 검증

PostgreSQL: 공시·문단·벡터·실행 기록·비용·답변 캐시·관계 스냅샷
Neo4j: SQL 스냅샷을 투영한 근거 관계 탐색 PoC
```

- **검색 범위:** 공시·파서·임베딩 버전을 고정한 뒤 벡터 검색과 BM25 순위를 RRF로 결합합니다.
- **계산 계약:** Agent는 이번 요청에서 조회된 관측값 ID만 계산에 사용할 수 있습니다. 기간·통화·연결 기준은 코드로 검증합니다.
- **답변 검증:** 모델은 출처 구간 ID를 선택하고 서버가 원문을 복사합니다. 별도 LLM 검토는 의미상 근거를 확인하지만 정확성을 보장하지는 않습니다.
- **실행 제어:** 도구 입력·반복·시간 제한, 호출 전 예산 예약, 사용자별 한도와 답변 캐시를 적용합니다.
- **관계 조회:** Neo4j 조회 결과를 PostgreSQL 스냅샷과 대조합니다. 현재 짧은 경로는 SQL JOIN으로도 구현 가능하며, 그래프 DB의 필요성을 검증하는 실험 범위입니다.

## 로컬 실행

Python 3.12 이상, Node.js 22.12 이상, Docker Compose가 필요합니다. CI는 Python 3.14 / Node.js 24를 사용합니다.

```sh
git clone https://github.com/junyongs0728/finance-detective.git
cd finance-detective
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
.venv/bin/python scripts/setup_local.py
```

생성된 `.env`에서 필요한 설정을 채웁니다. 설정 스크립트는 기존 값을 유지하며 DB 비밀번호와 연결 설정을 준비합니다.

| 설정 | 용도 |
|---|---|
| `SEC_USER_AGENT` | `"FinanceDetective 실제연락이메일"` 형태의 SEC 요청 식별 정보 |
| `DART_API_KEY` | 한국 기업 재무정보·공시 조회 |
| `OPENAI_API_KEY` | 임베딩·Agent·답변 생성·근거 검토. 단순 수치 조회에는 불필요 |
| `DATABASE_URL`, `POSTGRES_PASSWORD` | PostgreSQL 연결. 설정 스크립트가 준비 |
| `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` | Neo4j 연결. 설정 스크립트가 준비 |

모델·예산·실행 제한 전체 설정은 [.env.example](.env.example)에 있습니다. 기본 전체 예산은 일 $5 / 월 $30, 사용자별 일 $1 / 50회, 분석 작업당 $0.15입니다. 이는 앱이 기록하는 예상 API 비용의 한도이며 서버·DB 비용과는 별개입니다.

```sh
docker compose up -d --wait
npm ci --prefix frontend
npm run build --prefix frontend
.venv/bin/python -m uvicorn finance_detective.main:app --app-dir src --host 127.0.0.1 --port 8000 --no-proxy-headers
```

- 앱: http://127.0.0.1:8000/ · API 문서: http://127.0.0.1:8000/docs
- 화면 개발: `npm run dev --prefix frontend` (`/api` 요청을 8000 포트로 전달)
- 저장된 실행 예시: http://127.0.0.1:8000/portfolio/ — API 호출 없이 기존 결과를 보여주는 별도 정적 화면

첫 AI 질문은 공시 수집·임베딩 준비에 시간이 걸리고 API 비용이 발생합니다. 질문과 공시 서술문은 OpenAI API로 전송됩니다. 인증키는 백엔드에서만 읽으며 `.env`, 원문, 실행 캐시, 빌드 결과는 Git에서 제외합니다.

## 검증

```sh
.venv/bin/python -m pytest -q
npm run build --prefix frontend
```

테스트는 실제 PostgreSQL·Neo4j의 임시 SQL 스키마·Graph namespace와 합성 모델 응답을 사용합니다. 외부 API 키나 유료 모델 호출은 필요하지 않습니다. GitHub Actions에서도 같은 검사를 실행합니다.

`evals/`에는 고정 개발 질문과 당시 관측 결과를 보관합니다. 2026-09-21 Agent 평가에서 8개 사례의 상태·도구·계산·인용 문자열·SQL/Graph 일치 기준을 통과했습니다. 개발에 사용한 질문의 수용 기준 검사이며 독립적인 답변 정확도나 환각률이 아닙니다. 실패 기록, 검사 범위, 유료 평가 재실행 방법은 [평가 문서](docs/evaluation.md)에 있습니다.

## 지원 범위와 남은 과제

- 검색 목록 등재가 재무 데이터 지원을 보장하지 않습니다. SEC 표준 XBRL 태그와 DART 연결(CFS) 사업보고서를 사용하며, 기업별 전용 계정은 추가 매핑이 필요합니다.
- 실제 회계기간·통화·공시 번호를 유지하고 누락 수치를 0으로 채우지 않습니다. 수집 성공 결과는 로컬에서 24시간 재사용합니다.
- RAG는 선택 공시의 서술문을 수집합니다. 표·첨부·이미지/OCR는 제외하므로 공시 전체의 모든 근거를 검색하지는 않습니다.
- 분기·투자 예측·기업 간 비교·대화 기억은 지원하지 않습니다. 문서 형식별 파서와 질문 범위의 검증도 확대해야 합니다.
- 현재 서버는 로컬 실행 기준입니다. 작업 큐, 재시작 후 Agent 재개, 부하 시험, 백업·복구, 공개 운영 배포는 후속 과제입니다.
- 외부 배포에는 이용 코드 기반 인증(`AI_AUTH_MODE=token`)과 HTTPS가 필요합니다. [인증·비용·복구 범위](docs/postgres-cost-guide.md)를 먼저 확인하세요.

## 코드와 문서

| 경로 | 역할 |
|---|---|
| [frontend/src](frontend/src) | 기업 선택·채팅·인용·계산·실행 기록 UI |
| [src/finance_detective/chat.py](src/finance_detective/chat.py) | 기업·기간 범위 검증과 질문 라우팅 |
| [src/finance_detective/providers](src/finance_detective/providers) | SEC·OpenDART 수집·정규화·캐시 |
| [src/finance_detective/rag](src/finance_detective/rag) | 문서 준비·검색·생성·검토·비용·SQL 저장 |
| [src/finance_detective/agents](src/finance_detective/agents) | 모델·도구 인터페이스와 LangGraph 실행 제어 |
| [src/finance_detective/knowledge](src/finance_detective/knowledge) | 온톨로지와 Neo4j 투영·대조 |
| [tests](tests) / [evals](evals) | 회귀 검사와 개발 평가 기록 |

구현 상세: [RAG](docs/rag-build-guide.md) · [Agent·Graph](docs/agent-graph-guide.md) · [기업 데이터](docs/company-search-guide.md) · [React](docs/react-chat-guide.md) · [저장·비용](docs/postgres-cost-guide.md)

참고: [재무 데이터 해석](docs/finance-reference.md) · [초기 BM25 기준선](docs/legacy-baseline.md)
