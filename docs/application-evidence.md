# 지원·면접에서 설명할 구현 근거

2026-09-22 기준. 재무탐정은 개인 프로젝트이며 AI 코딩 도구를 활용했다. 회사에서 수행한 ERP·MES 업무와 개인 프로젝트의 구현 범위는 구분한다.

## 가장 강한 경력 연결

고객 공장을 방문하여 작업자가 원하는 **수주 → 작업지시 → 출하 연결**을 파악하고, 실제 업무 순서에 맞는 데이터 모델·API·화면을 자체 구축했다. 기존 이력서의 ERP 풀스택 구현 및 재고·출하 트랜잭션 경험과 연결되는 사례다.

이 경험은 업무 개념과 관계를 명시하는 **도메인 모델링 경험**이며 Ontology Modeling에 전이 가능한 기반이다. Palantir Foundry를 사용한 경험은 없다. 당시 업무를 Foundry 구축이나 기업 전체 온톨로지 운영으로 표현하지 않는다.

| 면접에서 설명할 요소 | 확인된 실제 경험 | 재무탐정에서 확인할 구현 |
|---|---|---|
| 업무 객체 | 수주·작업지시·출하 | Company·Filing·Period·Observation·Metric·Evidence |
| 객체 간 관계 | 작업자가 요구한 업무 연결을 데이터·API·화면으로 구현 | `knowledge/ontology.py`의 관계 정의와 `knowledge/graph.py` 투영 |
| 실행 규칙 | 재고와 출하를 연결하는 트랜잭션 처리 | 도구 입력의 기업·기간·통화·관측값 ID 검증 |
| 사용자 요구 | 현장 방문과 작업자 요구를 반영한 작업 흐름 | 숫자만 답하지 않고 계산·공시 출처·실행 기록 제공 |
| 검증 | ML 데이터 누수 검증·내부 평가·채점기 개선 | 계산·인용·사용자 격리·비용·SQL/Graph 대조 테스트 |

수주와 작업지시의 정확한 카디널리티, 출하 상태 전이, 부분 출하·취소 규칙, 성능 개선 수치는 확인된 자료 없이 덧붙이지 않는다. 면접에서는 실제 구현했던 사례를 본인이 설명한다.

참고: [Palantir Ontology 핵심 개념](https://www.palantir.com/docs/foundry/ontology/core-concepts)은 객체 유형·속성·링크와 Action을 구분한다. 업무 관계를 설계한 경험과 특정 플랫폼 사용 경험은 서로 다른 주장이다.

## 채용 요구사항과 코드의 연결

| 요구 기술 | 구현 증거 | 설명해야 할 설계 판단 |
|---|---|---|
| LLM Agent Architecture | `agents/workflow.py`, `agents/model.py`, `agents/tools.py` | 모델이 네 가지 도구를 선택하는 루프. 제한·종료·결과 검증은 코드의 책임 |
| Prompt Engineering | `rag/llm.py` 및 Agent 프롬프트 | 삼성전자 사업부 범위 오류, 주장 수·길이 제약, 검토되지 않는 자유 문장 제거 |
| RAG / Python | `rag/service.py`, `rag/store.py`, `rag/llm.py` | 공시 범위 제한, pgvector·BM25·RRF, 인용 복사, 별도 근거 검토 |
| Ontology / Property Graph | `knowledge/ontology.py`, `knowledge/graph.py` | 의미·관계를 명시하되 현재 짧은 경로는 SQL로도 가능. Neo4j는 관계 탐색 PoC |
| REST API / SQL | `main.py`, `providers/`, `rag/schema.sql` | SEC·OpenDART 정규화, 기간·통화 보존, SQL 기준 기록, 사용자별 실행 조회 |
| 평가 / 문서화 | `tests/`, `evals/agent-report.json`, `docs/agent-graph-guide.md` | 68개 자동화 검사와 고정 개발 사례 8개. 독립 정확도 평가와 구분 |

## 제출 자료와 접근 범위

- 이력서: 현장 문제 해결, ML 검증, 영어 실무 협업, 재무탐정 구현을 중심으로 작성했다.
- `showcase/index.html`: 실제 계산·공시 설명·답변 보류의 기록을 전환하는 정적 소개 화면.
- `showcase/project-brief.pdf`: 원문 링크, 기술 선택, 실패 개선, 평가 범위가 포함된 2페이지 소개 자료.
- `showcase/evaluation.json`: 개발 평가 기록에서 실행 식별자를 제외한 소개용 사본.
- 소스는 비공개다. 저장소 URL만 제출하면 외부 채용 담당자가 코드를 볼 수 없다. 소개 PDF를 첨부하거나, 별도 공개 소개 페이지에 대한 승인을 받은 뒤 해당 URL을 제출한다.

## 다음 구현의 우선순위

1. 개발에 사용하지 않은 질문·공시로 독립 평가 집합을 만들고 사람이 주장 근거를 채점한다.
2. 숫자만 필요한 Agent 질문에서 불필요한 RAG 준비와 Graph 투영 비용을 측정하고 줄인다.
3. 실제로 복잡한 관계 질의가 필요한지 확인한 뒤 Neo4j 유지와 SQL 단순화를 비교한다.
4. 공개 운영이 필요해지면 이용 제한·작업 큐·부하·백업 복구를 검증한다.

채용 직전의 우선 목표는 새로운 라이브러리 추가가 아니라, 현재 코드의 의사결정과 실패 사례를 재현 가능하게 설명하는 것이다.
