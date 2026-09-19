# Phase 2 필수 API 표면 매핑표 (계획서 300 §12 · 지시문 P-11)

> **판정 기준: main `40f78795`** (2026-09-19). 판정은 시점에 종속되므로 이 해시 없이 이 표를
> 인용하지 않는다 — 재현 불가한 판정은 며칠 뒤 조용히 거짓이 된다(CLAUDE.md 판정 시점 규칙).
>
> **이 표는 산문이 아니라 기계가 붙든다**: 아래 매핑의 정본 자료구조는
> `tests/backend/api/test_required_api_surface_map.py`의 `REQUIRED_SURFACES`이고, 그 테스트가
> ① 매핑된 경로가 **실제 앱 라우트 표에 있는지** ② 이 문서의 표가 그 자료구조와 **글자까지
> 일치하는지** ③ `없음`으로 적힌 것이 **정말 없는지**를 매번 재확인한다. 문서만 고치거나
> 코드만 고치면 CI가 red다.

## 판정 어휘 (3택의 경계를 먼저 못 박는다)

이 저장소의 **모든** 라우트는 `/v1/` 아래에 있고 학습자 자기 자원은 `/v1/me/` 스코프를 쓴다.
그 규약까지 개명으로 세면 12건이 전부 `다른 이름으로 있음`이 되어 표가 아무 정보도 주지
못한다. 그래서 다음과 같이 정의한다:

| 판정 | 뜻 |
|---|---|
| **있음** | 같은 자원·같은 메서드가 이 저장소의 `/v1[/me]` 규약 아래 그대로 있다 |
| **다른 이름으로 있음** | 자원 이름·분할 방식·메서드가 다르지만 **같은 일을 하는 표면이 실재**한다 |
| **없음** | 그 일을 하는 라우트가 없다 (=P-11 ④의 "빠진 API") |

## 매핑표 — 12/12

| # | 계획서 §12 API | 저장소 실제 경로 | 판정 |
|---|---|---|---|
| 1 | `POST /diagnostics` | `POST /v1/me/assessments/capture` · `POST /v1/me/assessments/assemble` · `GET /v1/me/diagnosis/summary` · `GET /v1/me/diagnosis/concepts` | 다른 이름으로 있음 |
| 2 | `GET /learner-state` | `GET /v1/me/learner-state` | 있음 |
| 3 | `GET /learning/next` | `GET /v1/me/next-problem` | 다른 이름으로 있음 |
| 4 | `GET /concepts/{id}` | `GET /v1/concepts/{concept_id}` | 있음 |
| 5 | `GET /contents/{id}` | `GET /v1/concepts/content/{code}` | 있음 |
| 6 | `GET /problems/{id}` | `GET /v1/problems/{problem_id}` | 있음 |
| 7 | `POST /attempts` | `POST /v1/me/attempts` | 있음 |
| 8 | `POST /assessments` | `POST /v1/me/assessments/capture` · `POST /v1/me/assessments/assemble` | 다른 이름으로 있음 |
| 9 | `GET /recommendations/next` | `GET /v1/me/next-problem` · `GET /v1/me/weak-concepts/{concept_id}/learning-path` · `GET /v1/me/review-queue` | 다른 이름으로 있음 |
| 10 | `POST /tutor/query` | `POST /v1/coach` · `POST /v1/coach/sessions/{dialogue_id}/turns` | 다른 이름으로 있음 |
| 11 | `GET /sessions/{id}` | `GET /v1/coach/sessions/{dialogue_id}` · `GET /v1/me/sessions` | 다른 이름으로 있음 |
| 12 | `GET /learning/result` | `GET /v1/me/learning-metrics` · `GET /v1/me/target-progress` · `POST /v1/me/objectives/{objective_id}/outcome` | 다른 이름으로 있음 |

**있음 5 · 다른 이름으로 있음 7 · 없음 0** (라우트 전수 119건 기준 — 앱 라우트 표 실측).

## 개명하지 않는다 (P-11 ②)

이름이 다른 7건은 **개명 대상이 아니라 매핑 대상**이다. 개명은 기존 클라이언트(Flutter 학생앱·
교사 웹·통합테스트)를 깨는 반면, 얻는 것은 계획서 문서와의 표기 일치뿐이다. 계획서 자신이
"API 숫자가 목적이 아니다"라고 적었고, 2026-09-03 갭 리뷰(§5 항목 C)도 같은 판정을 냈다 —
제2 표면(`/attempts` vs `/v1/me/attempts`)을 만드는 것은 **API 어휘 분기**이지 정리가 아니다.
그러므로 이 표가 정본 매핑이며, 개명 제안이 생기면 근거를 적어 Kiki에게 묻는다(세션 임의 개명 0건).

## 이번에 채운 것 (P-11 ④ — 최소 형태)

5번 `GET /contents/{id}`는 **판정 시점에 `없음`이었다**. `concept_content` 테이블은 실재하고
목록 좌석 `GET /v1/concepts/content`도 있었으나, 그 목록에는 `code` 필터가 없어 **단건을 집어올
경로가 0건**이었다(2026-09-03 갭 리뷰는 이 행을 목록 표면으로 `충족` 처리했는데, 목록과 단건은
다른 표면이다 — 이번 재실측이 그 판정을 정정한다).

채운 형태는 최소다: `GET /v1/concepts/content/{code}`가 목록과 **같은 응답 스키마**
(`ConceptContentSchema`)를 돌려주고 필드를 늘리지 않는다. 노출 계약도 목록과 같다(학생 직접
노출이 아닌 내부 표면 · `formal_definition_internal`은 학생 렌더에서 별도 게이팅).

> 경로의 `{code}`가 `{id}`가 아닌 이유: `concept_content`의 기본키는 UUID가 아니라 **코드
> 문자열**이다. 계획서의 `{id}`를 UUID로 읽어 경로를 만들면 조회가 영구히 0건이 된다.

## 표면 12개보다 중요한 것 — 5단계 연결 (P-11 ③)

P-11의 핵심 판정은 개수가 아니라 **연결**이다:

    Attempt → Event → Assessment → LearnerState → Recommendation

이 연결은 `tests/backend/api/test_p11_five_stage_loop_chain.py`가 **넘김(handoff) 4건**으로
동결한다 — 각 단계를 따로 보지 않고, 앞 단계의 산출물이 뒤 단계의 입력으로 실제 나타나는지를
단언한다. 특히 마지막 넘김은 200 응답으로 판정하지 않는다: 추천이 방금 푼 문항을 제외했는지,
숙달 가중이 **실제로 적용**됐는지(`weak_concept_signal_count >= 1`), 추천이 인용한 숙달값이
LearnerState의 값과 **같은지**를 본다("작동한 비율" 원칙).

인접 하네스와의 경계(중복 회피):

| 하네스 | 보는 것 | 이 연결과의 관계 |
|---|---|---|
| `test_week1_gate_closed_loop.py` | 루프 1바퀴 완주(7단계)·DB 직접 수정 없이 | Evidence·Event Trace·LearnerState 단일 표면을 보지 않는다 |
| `test_week2_gate_wrong_answer_propagation.py` | 오답 1건의 전파 + 이벤트 일치 | H1~H3을 촘촘히 덮지만 **추천 구간을 지나가지 않는다** |
| `test_p11_five_stage_loop_chain.py` | 넘김 4건의 **연결** | 고유 기여는 **H4(LearnerState→Recommendation)** |
