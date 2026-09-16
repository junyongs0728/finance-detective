# React 채팅 연결 — 2026-09-16

> 후속 구현: OpenAI RAG·임베딩·SQLite·근거 검토가 추가되었습니다. 현재 상태는 [RAG 구현 가이드](rag-build-guide.md)를 참고하세요. 아래는 해당 단계의 기록입니다.


## 실행 흐름
frontend/src/main.jsx App.send → POST /api/chat → ChatRequest 입력 길이 검증 → chat.answer → summarize/search → JSON → Result 컴포넌트.

## 실제 구현
추천 질문, 입력·전송, IME 조합 중 Enter 전송 방지, 대기 상태, AbortController/30초 timeout, 오류 재시도, 새 대화, 실제 데이터 표, 출처, 접을 수 있는 공시 발췌. 모바일에서는 좁은 표만 가로 스크롤합니다.

## 왜 이 구조인가
화면에 수치·계산 공식을 중복 구현하지 않고 기존 Python 도구를 재사용합니다. JSON 응답은 text/rows/evidence/sources/status/steps를 구분하므로 나중에 LLM text를 추가해도 숫자 표와 출처 UI는 재사용 가능합니다. Vite proxy와 배포 시 같은 origin을 사용해 불필요한 광범위 CORS 설정을 피했습니다.

## Skeleton과 제한
프런트는 실제 동작하며 mock 답변은 없습니다. 다만 chat.py의 keyword routing은 LLM intent router를 대신하는 임시 adapter입니다. Agent/LLM/멀티턴 메모리는 구현되지 않았습니다. 수치 요약 문장은 템플릿입니다. 근거 질문은 원인 분석 결과가 아니라 영어 발췌를 반환합니다.

## 시니어 리뷰
1. 범위 인식: 몇 개 기업명 blacklist와 regex는 일반 자연어 scope 검증이 아님. 알 수 없는 회사·복합 질문을 정확히 분리하는 resolver와 평가 필요.
2. 상태 경쟁: 새 대화 후 이전 응답이 끼지 않도록 generation ID로 응답을 무시하고 abort합니다. 브라우저 abort가 서버 연산 취소까지 보장하는 것은 아닙니다.
3. UI 보안: 원문과 질문을 React text로 렌더링하고 raw HTML 삽입을 하지 않습니다.
4. 서버는 비용 발생 모델을 호출하지 않습니다. LLM 연결 때 rate limit, trace, token/cost budget을 추가해야 합니다.
5. 현재 대화는 새로고침하면 없어지고 각 질문은 독립적입니다. 저장·메모리 기능을 암묵적으로 주장하지 않습니다.
6. 응답 schema는 아직 Python dict/JavaScript이며 후속 단계에서 Pydantic response model·TypeScript 타입으로 계약을 강화할 수 있습니다.
7. 한국어 키워드 의도 분류는 질문 뜻을 이해하는 AI가 아닙니다. UI에 ‘데이터 조회 모드’로 표시합니다.
