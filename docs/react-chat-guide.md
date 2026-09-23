# React 채팅과 API 연결

## 요청 흐름

`frontend/src/main.jsx`의 `App.send()` → `POST /api/chat` → FastAPI 입력·사용자 확인 → `chat.answer()` → 수치 / 고정 RAG / Agent → `Result`와 `AnalysisDetails` 표시.

기업 검색, 입력·전송, 한국어 IME 조합 중 Enter 방지, 준비 진행 상태, 요청 중지, 오류 재시도, 수치 표, 원문 인용을 지원한다. Agent 응답에는 계산 카드·도구 실행 기록·근거 관계 탐색을 표시한다.

## 데이터 계약과 화면 책임

- `company_id`와 `engine: auto/rag/agent`를 서버에 명시한다. 계산과 통화·기간 검증은 Python에서 수행한다.
- `text`, `rows`, `evidence`, `sources`, `calculations`, `agent_steps`, `knowledge_graph`, `status`를 구분해 표시한다.
- 공시가 `preparing`이면 문서 상태를 확인한 후 질문을 다시 요청한다. 즉시 답변과 준비 중 상태를 구분한다.
- 사용량·답변 캐시 여부는 서버 응답을 표시하며 프런트가 API 키나 예산을 관리하지 않는다.
- Vite 개발 프록시와 FastAPI의 정적 파일 제공으로 API를 같은 origin에 연결한다.

## 상태 경쟁과 제한

새 대화나 기업 변경 시 `AbortController`와 실행 번호로 이전 응답이 새 화면에 섞이지 않게 한다. 브라우저의 요청 중지는 진행 중인 서버·모델 호출 취소나 비용 환불을 보장하지 않는다.

원문과 질문은 React 텍스트로 렌더링한다. 현재 대화는 브라우저 메모리에 있으며 새로고침하면 초기화된다. 대화 이력을 모델에 전달하지 않으므로 후속 질문에도 기업·기간·대상을 명시해야 한다.

응답 계약은 Python dict와 JavaScript로 연결되어 있다. TypeScript 타입 및 더 넓은 응답 모델 검증, 자동화된 브라우저 회귀 검사는 후속 과제다.

`showcase/`는 저장된 실행 결과를 표시하는 별도 정적 예시다. 실시간 API 채팅 앱과 동작 범위를 구분한다. 사용 예시는 [demo-guide.md](demo-guide.md)를 참고한다.
