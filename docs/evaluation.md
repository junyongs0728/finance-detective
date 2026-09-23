# 평가와 재현 방법

자동화 검사는 코드의 계약을, 실제 모델 평가는 특정 질문에서 관측된 동작을 확인한다. 둘을 같은 정확도 지표로 합산하지 않는다.

## 1. API 비용 없는 회귀 검사

[README](../README.md)의 설정과 DB 기동 후 저장소 루트에서 실행한다.

```sh
.venv/bin/python -m pytest -q
npm run build --prefix frontend
```

[GitHub Actions](https://github.com/junyongs0728/finance-detective/actions/workflows/verify.yml)는 고정 의존성, 임시 PostgreSQL·Neo4j, 합성 모델 응답으로 같은 검사를 실행한다. 테스트는 임시 SQL 스키마와 Graph namespace를 정리하며 유료 API를 호출하지 않는다.

| 검사 영역 | 확인하는 실패 조건 | 코드 |
|---|---|---|
| 데이터 범위 | 다른 기업·통화·기간 혼입, 공급자 오류, 누락값 | [test_companies.py](../tests/test_companies.py), [test_metrics.py](../tests/test_metrics.py) |
| 검색·인용 | 다른 공시 문단, 가짜 출처 ID, 인용 재작성, 검토 실패 | [test_rag.py](../tests/test_rag.py) |
| Agent·Graph | 조회하지 않은 값 계산, 실행 제한, 미완료 요구, 관계 손상 | [test_agent_graph.py](../tests/test_agent_graph.py) |
| 비용·사용자 | 동시 예산 경쟁, 사용자 간 캐시·기록 혼입, 타임아웃 예약 | [test_cost_controls.py](../tests/test_cost_controls.py) |
| 라우팅·평가 경로 | 수치 질문의 불필요한 AI 호출, RAG와 Agent 모드 혼동 | [test_chat.py](../tests/test_chat.py) |

## 2. 저장된 개발 평가

| 기록 | 범위와 해석 |
|---|---|
| [agent-baseline.json](../evals/agent-baseline.json) | 2026-09-21 최초 Agent 평가. 8개 중 7개 기준 통과 |
| [agent-schema-failure.json](../evals/agent-schema-failure.json) | 생성 주장 수가 응답 검증 한도를 넘었던 중간 실패 |
| [agent-report.json](../evals/agent-report.json) | 수정 후 같은 8개 기준 통과. AI 실행 5개, 사전 범위 차단 3개 |
| [rag-report.json](../evals/rag-report.json) | 초기 고정 RAG의 상태·문자열·인용 검사. 당시 프롬프트·파서 기준 |
| [retrieval-report.json](../evals/retrieval-report.json) | 초기 쿠팡 PDF BM25 기준선. 현재 하이브리드 검색 점수가 아님 |
| [postgres-cost-report.json](../evals/postgres-cost-report.json) | PostgreSQL 이전 및 캐시·비용 실험 당시 관측 기록 |

Agent 검사는 기대 상태, 필요한 도구 호출, 계산 결과, 인용 문자열, SQL/Neo4j 일치 여부를 확인한다. [agent-cases.json](../evals/agent-cases.json)에 기준을 명시했다. 수정 과정에서 본 질문을 다시 사용했으므로 독립 평가가 아니다. 원인 설명의 충분성이나 답변 전체의 의미 정확도는 자동 검사만으로 판정하지 않는다.

최종 8개 실행의 예상 API 비용 합계는 $0.032146이었다. 공시가 이미 준비된 상태의 기록이며 색인·이전 실패·서버·DB·세금은 제외했다. 현재 실행의 가격이나 평균 지연을 보장하는 수치가 아니다. 재실행 시에는 모델·문서·캐시 여부를 함께 확인한다.

## 3. 실제 모델 평가 재실행

OpenAI API 비용이 발생한다. 키·예산을 설정하고 필요한 공시를 앱에서 준비한다. 아래 HTTP 스크립트는 로컬 인증 모드의 서버를 기준으로 하며 이용 코드 헤더를 직접 전달하는 옵션은 없다.

```sh
# 서버를 실행한 상태에서 Agent 평가. 최초 공시 준비도 발생할 수 있다.
.venv/bin/python scripts/evaluate_agent.py --live

# 특정 사례만 실행
.venv/bin/python scripts/evaluate_agent.py --live --case cash-income-gap

# 선택 공시를 먼저 준비한 뒤 고정 RAG 경로 평가
.venv/bin/python scripts/evaluate_rag.py
```

사례 ID는 [질문 파일](../evals/agent-cases.json)을 기준으로 한다. 결과는 Git에서 제외되는 `data/processed/agent-evaluation.json`, `data/processed/rag-evaluation.json`에 저장된다. 저장된 `evals/` 보고서를 자동으로 덮어쓰지 않는다.

`evaluate_rag.py`는 `engine='rag'`를 명시한다. 기본 모드가 Agent로 바뀌어도 RAG 평가가 다른 경로를 측정하지 않도록 실제 라우터를 통과하는 회귀 검사로 확인한다.

동일 질문은 답변 캐시를 사용할 수 있다. Agent 결과의 `cached`와 비용 기록을 확인하고, 새 모델 호출의 성능·비용과 캐시 응답을 구분한다. 데이터나 프롬프트를 변경한 평가를 공개할 때는 변경 조건과 실패 결과도 함께 기록한다.

## 4. 아직 평가하지 못한 것

- 개발에 사용하지 않은 질문·공시의 사람 평가: 주장 충실성, 정보 누락, 올바른 유보와 과도한 유보.
- 같은 정답 근거 집합에서 BM25 단독·벡터 단독·하이브리드 검색 비교.
- 고정 RAG 대비 Agent의 추가 도구 사용 효용, 비용·지연, 잘못된 도구 선택.
- 장문·다양한 공시 형식, 수정공시, 복수 연산, 동시 사용자 부하·장애 복구.

작은 개발 집합의 통과율로 전체 서비스의 정확도나 운영 안정성을 추정하지 않는다. 구체적인 실패와 수정은 [RAG 가이드](rag-build-guide.md)와 [Agent 가이드](agent-graph-guide.md)에 기록한다.
