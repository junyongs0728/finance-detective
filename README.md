# 재무탐정 · Finance Detective

미국·한국 기업을 검색하고, 공시 출처가 있는 연간 재무정보를 조회하는 학습용 웹 앱입니다.
React 화면과 Python/FastAPI를 사용하며, 근거를 인용하는 재무 분석 AI로 확장하고 있습니다.

## 현재 구현

- 기업명·종목코드 검색, 한국/미국 필터, 일부 미국 기업의 한국어 별칭
- OpenDART / SEC 표준 XBRL 기반 연간 매출·영업이익·영업현금흐름
- Python으로 계산한 매출 증가율·영업이익률
- 공시별 통화·기간 기준·원문 링크와 누락 데이터 표시
- 수치 질문은 규칙 기반 조회, 설명 질문은 선택 기업·공시에 한정한 RAG
- SQLite 문서·문단·임베딩·실행 기록 저장
- 임베딩 + BM25 검색, 출처 인용, 별도 근거 검토와 답변 유보
- 선택적으로 준비하는 쿠팡 2025 10-K의 BM25 본문 검색

**현재는 고정된 RAG 워크플로이며 자율 Agent는 아닙니다.** OpenAI 생성·임베딩·SQLite 저장은 구현했고, 온톨로지·Property Graph·도구 선택 Agent는 다음 단계입니다. [RAG 구현 가이드](docs/rag-build-guide.md)에서 실제 코드 흐름과 한계를 설명합니다.

## 로컬 실행

Python 3.12 이상, Node.js 22.12 이상이 필요합니다. 실제 검증 환경은 Python 3.14 / Node.js 24입니다.

```sh
git clone https://github.com/junyongs0728/finance-detective.git
cd finance-detective
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
cp .env.example .env
npm ci --prefix frontend
npm run build --prefix frontend
.venv/bin/python -m uvicorn finance_detective.main:app --app-dir src --host 127.0.0.1 --port 8000
```

`.env`에 다음 항목을 직접 채우세요. 이미 `.env`가 있다면 복사 명령으로 덮어쓰지 마세요.

| 설정 | 용도 |
|---|---|
| `DART_API_KEY` | 한국 재무정보 조회용 OpenDART 인증키 |
| `SEC_USER_AGENT` | `"FinanceDetective 실제연락이메일"` 형태의 SEC 요청 식별 정보 |
| `OPENAI_API_KEY` | 설명 질문의 문서 임베딩·답변 생성·근거 검토용. 수치 조회만 할 때는 필요 없음 |
| `OPENAI_MODEL` | 기본값 `gpt-4.1-mini` |
| `OPENAI_REVIEW_MODEL` | 근거 검토 기본값 `gpt-4.1` |
| `OPENAI_EMBEDDING_MODEL` | 기본값 `text-embedding-3-small`, 512차원 |

- 앱: http://127.0.0.1:8000/
- API 문서: http://127.0.0.1:8000/docs
- 개발 중에는 `npm run dev --prefix frontend`로 Vite를 실행할 수 있습니다. `/api` 요청은 8000 포트로 전달됩니다.

인증키는 백엔드에서만 사용합니다. `.env`, 다운로드한 공시, 실행 캐시, 가상환경, 빌드 결과는 Git에서 제외됩니다.

## 사용 흐름

1. 기업명 또는 종목코드로 검색합니다.
2. 기업을 선택하면 연간 재무표와 출처를 조회합니다.
3. `연간 매출과 영업이익 알려줘` 또는 `2025년 영업이익률 알려줘`처럼 질문합니다.
4. `주요 사업을 공시 근거로 설명해줘`로 AI 답변을 요청합니다. 처음에는 해당 공시를 준비하며 진행 상태를 표시합니다. 공시 서술문과 질문이 OpenAI API로 전송되고 API 비용이 발생합니다.
5. 기업을 바꾸면 이전 대화가 초기화됩니다. 각 질문은 독립적으로 처리합니다.

| API | 역할 |
|---|---|
| `GET /api/companies?q=삼성전자&market=DART` | 기업 검색 |
| `GET /api/company-data/DART:005930` | 한국 기업 연간 수치 |
| `GET /api/company-data/SEC:AAPL` | 미국 기업 연간 수치 |
| `POST /api/chat` | `company_id`, `message`를 명시한 질문 |

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

```sh
.venv/bin/python -m pytest -q
npm run build --prefix frontend
```

테스트는 고정 공개 수치와 합성 fixture를 사용하며 인증키·네트워크·다운로드된 PDF가 필요하지 않습니다.
실제 RAG 개발 평가: 삼성전자·애플·쿠팡에 먼저 설명 질문을 한 뒤 `.venv/bin/python scripts/evaluate_rag.py`. 이 평가는 유료 API를 호출하며 결과를 `data/processed/rag-evaluation.json`에 저장합니다. 실제 공급자 연결 및 브라우저 확인과 오프라인 단위 검사를 구분합니다.

## 코드 구조

```text
frontend/src/                 React 기업 검색·채팅
src/finance_detective/
  main.py                    REST API와 화면 제공
  chat.py                    규칙 기반 질문 라우팅
  providers/                 SEC / OpenDART 수집·정규화·캐시
  analysis/                  재무 비율 계산
  retrieval/                 최초 쿠팡 BM25 검색과 개발 평가
  rag/                       공시 수집·SQL·하이브리드 검색·생성·검증
  collectors/                최초 쿠팡 수집 기준선
  agents/                    미구현 확장 자리
scripts/                     선택적 데이터 준비
data/seed/                   공개 검색 목록
tests/                       네트워크 없는 검증
docs/                        구현 설명·설계·학습 기록
```

## 다음 단계와 학습 기록

1. 구현된 RAG의 검색 품질·문서 지원 범위와 평가 데이터 확장
2. 재무 조회·계산·검색 도구를 연결하는 Agent Architecture
3. 온톨로지 설계와 Property Graph 관계 탐색
4. 근거·수치 정확성, 답변 유보, 비용·지연 평가와 Git 변경 기록

- [기업 검색 구현과 AI 학습 계획](docs/company-search-guide.md)
- [AI 엔지니어링 구현 설명](docs/ai-engineering-guide.md)
- [React 채팅 구현 설명](docs/react-chat-guide.md)
- [재무 개념 참고 노트](docs/finance-reference.md)

일부 문서는 초기 단계의 실험 기록입니다. 현재 기능 범위는 이 README와 기업 검색 구현 가이드를 기준으로 확인하세요.
