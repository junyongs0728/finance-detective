# 재무탐정 AI Engineering Guide

2026-09-16 기준. 이 문서는 현재 구현과 향후 설계를 구분합니다. 구현 속도를 유지하면서 코드 리뷰 중심으로 학습합니다.

## 1. 현재 코드의 정확한 위치

| 파일·함수 | 상태 | 책임 |
|---|---|---|
| collectors/sec.py: normalize | 구현 | 특정 CIK·공시 번호·시작일·종료일·USD로 연간 수치 선택 |
| collectors/sec.py: collect | 구현 | SEC JSON 다운로드, 원본 해시·수집 시각 저장, 정상 결과 파일 교체 |
| analysis/metrics.py: percent, summarize | 구현 | 증가율·영업이익률 계산, 기간·통화·중복 검증 |
| retrieval/evidence.py: build | 구현 | PDF 텍스트 추출, 페이지 내부 240단어 청크·60단어 중첩, 원문 링크 |
| retrieval/evidence.py: LexicalIndex | 구현 | 단어 빈도·문서 빈도·문서 길이를 계산하고 BM25 순위 생성 |
| retrieval/evidence.py: _load_index, search | 구현 | 파일 변경 시 갱신되는 프로세스 내부 캐시·검색 응답 |
| retrieval/evaluate.py: evaluate | 구현 | 정답 페이지와 근거 문구를 기준으로 검색 평가 |
| main.py | 구현, 임시 결합 구조 | HTTP 입력 검증, 데이터 조회, HTML·JavaScript 화면 |
| agents/__init__.py | skeleton | 설명 문자열만 있음. 실행되는 Agent 로직 없음 |
| 나머지 __init__.py | 패키지 표시 | Python 패키지를 만드는 파일. 그 자체가 기능은 아님 |
| LLM 생성·embedding·reranker·Graph DB·MCP | 미구현 | 이름이나 폴더가 있다고 구현된 것이 아님 |

Skeleton은 구조·인터페이스·자리만 준비한 코드입니다. 짧은 코드라는 이유로 skeleton은 아닙니다. 현재 BM25는 실제 동작하는 기준선입니다. 장난감 수준의 범위와 무구현은 구별해야 합니다.

## 2. 현재 요청이 흐르는 길

브라우저 → GET /api/companies/CPNG/evidence → main.evidence → search → _load_index → LexicalIndex.rank → 원문 발췌와 페이지 링크.

오프라인 색인: PDF → pypdf → 페이지별 text → words[offset:offset+240] → 청크 JSON.
수치 경로: SEC companyfacts → normalize → 출처 포함 수치 JSON → summarize → 지표 API.

문서 검색과 수치 계산을 분리한 이유는 PDF 표가 평문으로 추출되면서 열·행 연결이 깨질 수 있기 때문입니다. LLM이나 텍스트 검색이 금액을 재구성하게 하지 않고 구조화 수치 경로를 유지합니다.

## 3. RAG: 현재는 R만 있다

RAG는 질문에 관련된 외부 근거를 검색하고, 그 근거를 생성 모델의 입력에 넣어 답변하는 구성입니다. 벡터 DB를 설치하는 것과 동의어가 아닙니다. 지금은 검색까지만 구현했으므로 완성된 RAG라고 부르지 않습니다.

예정 흐름:
질문 → 회사·기간·질문 유형 결정 → 구조화 수치 조회 + 문서 검색 → 근거 패키지 → LLM 답변 → 수치·인용 검증 → 표시.

### 왜 BM25부터 했나
- 영어 보고서의 고유명사와 회계 용어를 빠르고 저렴하게 검색할 수 있습니다.
- 모델 API 없이 오프라인에서 재현 가능하고, 후속 개선을 비교할 기준이 됩니다.
- `k1=1.5`, `b=0.75`를 사용합니다. 현재 상수이며 최적화된 값이라고 주장하지 않습니다.
- TF: 청크 내 단어 빈도. 같은 단어의 과도한 반복에는 점수 증가가 포화됩니다.
- IDF: 여러 문서에 흔한 단어보다 드문 단어의 가중치가 큽니다.
- 길이 정규화: 긴 청크가 단어가 많다는 이유만으로 유리해지는 것을 완화합니다.
- STOP은 간단한 불용어 목록이며 stemming·lemmatization은 없습니다.

### 현재 tokenizer의 명확한 한계
`[a-z]+`는 영어 알파벳만 추출합니다. 한글과 숫자가 검색 토큰에서 빠집니다. 한국어 버튼은 PRESETS의 고정 영어 질의로 바뀝니다. 한글 의미 이해나 자연어 번역이 아닙니다. 숫자 토큰을 추가해도 기간·기업이 자동으로 정확히 필터링되는 것은 아닙니다.

### Chunking은 모델보다 먼저 검토한다
현재 240단어는 토큰 수가 아닙니다. 60단어 중첩은 경계의 근거 누락을 완화하지만 같은 문장이 여러 결과를 차지하게 합니다. 페이지 경계를 지켜 인용이 단순해졌지만 문단이 페이지를 넘으면 근거가 끊깁니다. 헤더·푸터·표가 섞일 수 있습니다. 다음 실험은 섹션·문단 단위 분할과 인접 청크 합치기이며, 기존 질문의 순위가 실제 개선되는지 비교해야 합니다.

### Hybrid retrieval과 reranking은 서로 다르다
Dense retrieval은 embedding 벡터로 의미가 비슷한 후보를 찾습니다. BM25와 dense 후보를 RRF 같은 방법으로 합치는 것이 hybrid retrieval입니다. 서로 다른 점수 척도를 그냥 더하지 않습니다. Reranker는 이미 찾은 소수 후보를 질문과 함께 다시 평가해 순서를 바꿉니다. 후보 단계에서 빠진 근거는 reranker가 되살릴 수 없습니다.

### 생성 단계의 인터페이스 설계안 — 아직 미구현
입력: question, company, periods, facts, evidence[{id,text,source_url,page}].
출력: status(answered/insufficient_evidence), claims[{text,evidence_ids}], calculations, limitations.
검증: 존재하는 evidence ID인가 → 값이 계산 결과와 맞는가 → 인용 문장이 주장을 실제 뒷받침하는가.
ID 유효성은 코드로 확인할 수 있지만, 근거의 의미적 뒷받침은 별도 평가가 필요합니다. Structured output은 JSON 모양을 통제할 뿐 사실성을 보장하지 않습니다. 문서 내용은 데이터로 취급하며 문서 안의 지시문을 실행 지침으로 따르지 않습니다.

## 4. 검색 평가를 읽는 법

`evals/retrieval-dev.json`: 원문을 확인한 뒤 작성한 개발용 질문 10개. 답변 가능한 8개와 이 corpus로 답할 수 없는 2개입니다. 블라인드 테스트가 아니며 질문들이 일부 페이지에 집중돼 있어 일반 성능을 대표하지 않습니다.

정답 기준은 페이지 일치와 근거 문구 포함을 모두 요구합니다. 같은 페이지에 나왔다는 이유만으로 성공으로 치지 않습니다. 단, 표현 변경·새 파서에 취약한 기준이며 여러 근거를 모두 찾아야 하는 완전성은 측정하지 않습니다.

- Hit@1: 첫 결과에 지정 근거가 있는 질문 비율.
- Hit@5: 상위 5개 중 지정 근거가 하나라도 있는 질문 비율. 모든 정답 청크를 모으지 않았으므로 Recall@5라고 부르지 않습니다.
- MRR@5: 첫 정답 순위의 역수 평균. 1위는 1, 4위는 0.25, 5위 안에 없으면 0.
- 답변 불가 질문에서 후보 반환: 그 자체가 환각은 아닙니다. 하지만 후보를 곧바로 답변 근거로 승인하면 위험하다는 신호입니다.

현재 결과: Hit@1 7/8, Hit@5 8/8, MRR@5 0.90625. 소매 매출 인식 시점 질문은 지정 근거가 4위였습니다. 답변 불가 2개에서도 후보가 나왔습니다. 테스트 14개 통과와 검색 정확도는 다른 지표입니다.

다음 평가 집합: 한국어 paraphrase, 회사·기간 혼동, 여러 근거 필요 질문, 부정 질문, 데이터 없음. 개발용으로 개선한 뒤 별도 작성한 보류 평가 집합을 최종 확인에만 사용합니다. LLM judge는 보조 수단이며 원문 대조와 계산 정답을 대체하지 않습니다.

## 5. 이번 실제 개선: corpus 캐시

이전 rank는 요청마다 406개 청크를 다시 토큰화하고 단어 빈도를 계산했습니다. 새 LexicalIndex는 생성할 때 counts·lengths·document_frequency를 한 번 계산합니다. _load_index는 경로·수정 시각(ns)·크기를 키로 캐시하고 JSON이 바뀌면 다시 읽습니다.

코드 리뷰 포인트:
- 이전 rank와 새 rank의 출력이 같은가: 동일 질의 결과 테스트.
- 새 공시를 넣어도 옛 결과를 반환하지 않는가: 파일 교체 후 캐시 갱신 테스트.
- 여러 worker는 캐시를 각각 가진다. 분산 공유 캐시가 아니다.
- 같은 크기·mtime을 강제로 보존한 파일 변경은 감지하지 못한다. 운영 단계에서는 명시적 index version 또는 content hash 기반 배포가 더 명확하다.
- 현재 여전히 모든 청크를 순회한다. 문서 수가 커지면 inverted index 또는 검색 엔진을 검토한다.

로컬 30회 중앙값: 매번 corpus 통계를 만드는 rank 약 20.004ms, warm search 약 0.514ms. HTTP·동시 요청·cold start를 포함하지 않아 서비스 전체가 39배 빨라졌다는 뜻은 아닙니다. evals/search-timing.json에 측정 범위를 남겼습니다.

## 6. Agent: LLM이 다음 도구를 선택할 때 도입한다

고정 workflow: retrieve → calculate → generate 순서를 코드가 정합니다.
Agent: 현재 결과를 보고 LLM이 search_notes, get_financials, calculate_metric 같은 허용된 도구 중 다음 행동을 고릅니다.

현재 agents 폴더에는 실행 로직이 없습니다. BM25 검색 함수를 agent라고 부르지 않습니다.

재무탐정의 Agent 설계안:
- 상태: question, company, periods, facts, evidence, tool_history, remaining_steps, cost, status.
- 도구: 검증된 회사·기간으로 수치 조회, 제한된 문서 검색, 결정적 계산 함수.
- 루프: 모델 도구 요청 → 입력 스키마 검증 → 도구 실행 → 결과를 상태에 기록 → 다음 행동 또는 종료.
- 경계: 최대 단계·시간·비용, 동일 도구 반복 감지, timeout, 일시적 실패와 영구 실패 분리.
- 로그: trace ID, 도구명, 검증된 인자, 지연, 오류, 검색한 문서 버전. 비밀키는 남기지 않음.
- 상태 저장은 재시작 복구를 돕지만 외부 작업의 exactly-once 실행까지 보장하지 않음. 쓰기 도구에는 멱등성 키와 승인 정책이 필요.

처음부터 여러 에이전트를 만들면 오류 원인과 비용이 분산됩니다. 단일 workflow에서 해결되지 않는 실제 분기를 확인하고 한 Agent부터 비교합니다.

## 7. Graph: 두 종류를 혼동하지 않는다

LangGraph의 graph는 실행 흐름 그래프입니다. 노드=실행 단계, 엣지=다음 단계입니다.
Neo4j 같은 property graph는 지식·데이터 관계 그래프입니다. 노드=기업·보고서·항목·근거, 엣지=공시함·포함함·근거가됨입니다. LangGraph를 쓰면 지식 그래프가 자동으로 생기는 것은 아닙니다.

재무탐정 ontology 초안:
Company(CIK) → FILED → Filing(accession,period_end)
Filing → CONTAINS → Fact(concept,period,unit,scope,value)
Filing → CONTAINS → Evidence(document_hash,page,chunk_id)
Claim → SUPPORTED_BY → Evidence
Claim → USES → Fact

단순히 ‘매출’ 이름만으로 사실 노드를 합치면 연도·통화·기업이 섞입니다. stable ID와 unique constraint를 먼저 설계합니다. restatement는 원본 덮어쓰기보다 새 filing/version과의 관계로 보존하는 편이 추적에 유리합니다.

Graph가 유용할 질문: ‘이 분석 주장이 어떤 수치와 어떤 공시에 의존하며, 공시가 바뀌면 어떤 분석을 다시 계산해야 하나?’ 여러 관계를 이어 가는 경로 탐색입니다. 단일 회사·3년 수치 조회는 SQL로 충분할 수 있습니다. 동일 질문에서 SQL/벡터 검색 대비 품질·구현 복잡도를 비교해야 합니다. 모든 설명에 CAUSED_BY 엣지를 붙이지 않습니다. 보고서의 주장과 검증된 인과관계는 다릅니다.

현재 Graph DB, 노드·엣지 생성, Cypher 실행은 모두 미구현입니다.

## 8. 시니어 리뷰 우선순위: 이번 코드에 적용

P1: 회사·기간 scope와 답변 가능성 검증이 없다. 생성 연결 전에 해결. 높은 BM25 점수를 정답 확신으로 쓰지 않기.
P1: 문서 근거가 있는데도 다른 연도 값을 섞는 오류. 질문에서 정한 scope를 검색·계산·생성 전체에 전달.
P1: 숫자와 문서가 같은 보고 버전을 쓰는지 확인. 현재 SEC 수치와 IR PDF는 각각 해시/출처를 가지지만 자동 내용 동일성 검증은 없음.
P2: PDF 표·헤더·문단 분할 품질. 추출 실패를 나중에 프롬프트로 덮지 않기.
P2: 실험 재현성. corpus hash·질문 집합·검색 설정·모델·프롬프트 버전·시간·비용 기록.
P2: main.py의 HTML·API·서비스 책임 분리. 기능 경계가 안정화될 때 templates와 router로 분리.
P2: cached corpus invalidation과 cold start. 이번에는 로컬 캐시와 갱신 테스트까지 구현.
P2: 네트워크 오류·파일 손상·권한·실패 응답. 정상 경로뿐 아니라 장애를 주입해 확인.
P3: requirements에 개발 의존성까지 들어 있고 사용하지 않는 beautifulsoup4도 있음. 배포 의존성 분리 및 잠금 도구 도입 검토.
P3: 테스트 실행 시 서드파티 deprecation 경고 2개. 현재 실패는 아니며 호환성 정리 필요.

리뷰의 질문은 ‘최신 프레임워크인가?’보다 ‘어떻게 틀리며, 그걸 어떻게 알아내고, 고친 뒤 어떻게 증명하는가?’입니다.

## 9. 이후 집중 스프린트

1) scope가 명시된 답변 생성: 구조화 입력·근거 ID·답변 보류, 제공자 API 실제 연동 및 비용 측정.
2) retrieval 실험: 영어 BM25 vs 다국어 dense vs hybrid, 같은 평가 집합 비교. 개선 실패도 기록.
3) 단일 Agent: 수치/문서/계산 도구 선택, trace, step budget, retry. 고정 workflow와 비교.
4) knowledge graph: 위 ontology의 최소 모델과 근거 경로 조회, SQL로 충분한 경우도 기록.
5) 운영: request ID, 지연/비용, 오류 분류, 인증, 컨테이너·복구 실험.

각 작업 후 기록: 동작 코드 / skeleton / 설계 이유 / 실패 사례 / 측정 결과 / 다음 변경. 재무 산수 퀴즈 없이 실제 코드 수정과 장애 원인 설명으로 이해를 확인합니다.

## 10. 공식 참고 자료

- LangGraph workflow와 agent 구분: https://docs.langchain.com/oss/python/langgraph/workflows-agents
- Neo4j GraphRAG 구성: https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_rag.html
- BM25 설정 개념: https://www.elastic.co/docs/reference/elasticsearch/index-settings/similarity

문서에 나오는 제품 기능과 이 프로젝트에 구현한 기능은 별개입니다.
