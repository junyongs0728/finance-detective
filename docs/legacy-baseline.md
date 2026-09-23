# 초기 쿠팡 BM25 검색 기준선

현재 기본 앱은 SEC/DART 수집과 PostgreSQL 기반 RAG·Agent를 사용한다. `collectors/`, `retrieval/`, `/legacy` 및 `/api/companies/CPNG/...`는 초기 PDF 검색 실험을 재현하기 위해 유지한다.

## 재현

루트의 `.env`에 SEC 요청 식별 정보를 설정한 후 실행한다. 외부 공개 자료 다운로드가 필요하며 OpenAI API는 호출하지 않는다.

```sh
.venv/bin/python scripts/prepare_coupang.py
PYTHONPATH=src .venv/bin/python -m finance_detective.retrieval.evaluate
```

수치는 SEC 구조화 API에서, 본문은 쿠팡 공식 IR PDF에서 수집한다. PDF의 페이지별 240단어 창과 60단어 중첩으로 BM25 색인을 만든다. 한국어 주제는 고정 영어 검색어로 매핑하며 의미 검색이나 생성 모델은 사용하지 않는다.

## 당시 관측값

[retrieval-dev.json](../evals/retrieval-dev.json)은 답변 가능한 8개와 불가능한 2개로 구성된 개발 질문이다. 정답 페이지와 지정 근거 문구가 모두 검색돼야 성공으로 처리했다.

- Hit@1: 7/8, Hit@5: 8/8, MRR@5: 0.90625. 모든 정답 문단을 라벨링하지 않아 Recall이라고 부르지 않는다.
- 답변 불가 질문에서도 검색 후보가 반환됐다. 검색 점수만으로 답변 가능성을 판정할 수 없다는 사례다.
- [search-timing.json](../evals/search-timing.json)은 corpus 통계를 매번 만드는 방식과 프로세스 내부 캐시를 비교한 로컬 기록이다. HTTP·동시 요청·cold start를 포함하지 않는다.

이 결과는 현재 하이브리드 검색이나 Agent의 성능을 나타내지 않는다. 원문 버전·파서·검색 설정이 달라진 실험끼리 수치를 직접 비교하지 않는다.
