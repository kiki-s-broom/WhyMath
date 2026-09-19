# Week 3 Gate 판정 — 계획서 300 Phase 2 §10

**판정 기준: main `13826ece3869d0beda5eb1dc74c0f3235fbaccb0`**
**판정자**: claude (구현 세션과 분리 — 이 세션은 판정 하네스만 만들고 P-08~P-10 기능을 구현하지 않았다)
**태스크**: `EOS-113` · **PR**: __PR_LINK__
**선행**: P-08 = `EOS-14`(recommend 호출 계약·reason 필수) · P-09 = `MISC-30`(보정 정책 테이블·반복 오류 사다리) ·
P-10 = 기존부분(핵심 제약이 이미 코드 집행 중 — 잔여는 `PED-18`·`PED-19`·`S4-11`가 소유)

---

## 1. 판정

> **통과 (PASS)** — 단, 인접 결함 1건(`EOS-115`)을 함께 보고한다.

완료 판정 문면은 *"오답→Misconception→교정 콘텐츠→AI Hint→새 문제→재시도가 사람 개입 없이 자동 연결"* 이다.
**연결됐다.** 여섯 마디를 한 회차에 순서대로 관통했고, 다섯 화살표 전부에서 **다음 마디의 산출물이 앞
마디의 영속된 결과에서 나왔다**. 사람이 값을 넣어야 넘어가는 구간은 없었다.

판정은 exit code로 냈다(인상 판정·점추정 없음).

## 2. 이 판정이 실제로 잰 것 — 마디가 아니라 **화살표**

원 문서가 요구한 것은 여섯 마디의 *존재*가 아니라 화살표다. 그래서 하네스는 마디마다 둘을 함께
단언한다 — ⓐ 산출물이 나왔는가 ⓑ **그 산출물이 앞 마디의 영속된 결과에서 나왔는가**. ⓑ가 없으면
"클라이언트가 답을 이미 알고 있어서 이어진 것"과 구별되지 않는다.

그 ⓑ를 기계로 고정하려고 요청 본문을 모듈 상수로 두고 **본문에 오개념 id·힌트 단계가 없다는 것
자체를 단언**한다(`_assert_carries_no_hint`). 코치 세션을 여는 요청이 실어 보낸 것은
`student_input`(중립 발화 "잘 모르겠어요")과 `problem_id` 둘뿐이다.

| # | 마디 | 무엇으로 통과를 판정했나 | 그 다음을 **무엇이 촉발했나** | 실측 |
|---|---|---|---|---|
| 1 | **오답** | `POST /v1/me/attempts` 201 · `is_correct=false` · attempt_id 발급 | — (시작점) | 201 |
| 2 | **Misconception** | 응답 `evidence.possible_misconceptions`에 후보 + `GET /v1/me/learner-state`의 `active_misconceptions`에 **영속** | 학생이 쓴 답 문자열 하나(`x^2+4`) — 요청에 오개념 id 없음 | `distribution-over-power` conf `0.9` · gate_passed |
| 3 | **교정 콘텐츠** | `POST /v1/coach/sessions` 응답 `intervention`이 **그** 오개념을 겨냥 + 발화 비어 있지 않음 | 2마디가 남긴 **활성 가설**(요청은 중립 발화뿐) | pattern=`reverse_reasoning` target=`distribution-over-power` |
| 4 | **AI Hint** | `POST /v1/coach/sessions/{id}/turns` 응답 `decision.hint_level`이 **상승** | 3마디가 적재한 `힌트제공` 이벤트 — 서버가 `_prev_hint_level_for`로 되찾음(클라 미지정) | hint_level `3 → 4` |
| 5 | **새 문제** | `GET /v1/me/next-problem`이 **틀린 그 문항이 아닌** 문항 반환 + `reason` 비어 있지 않음 | 1마디의 attempt(미시도 제외) + 그 오답이 쓴 실측 숙달(`reason.mastery`) | action=`practice_prerequisite` · reason.mastery `0.15` = 상태값 |
| 6 | **재시도** | 추천받은 그 문항을 제출 201 + 가설이 살아남아 다음 바퀴가 돈다 | 5마디가 고른 `problem_id` | 새 attempt_id · 숙달 `0.15 → 0.12` |

여섯 마디는 **한 회차에서 순서대로 실제 실행된 결과**다(간접 추론이 아니다). 각 마디는 status code가
아니라 산출물을 단언한다 — "API 201"을 통과 근거로 쓰는 마디는 없다.

## 3. 이벤트 trace — 화살표의 촉발원이 한 시간선에 남았는가

`GET /v1/me/learning-trace`(P-02 산출물 = `EOS-11` 표면) 14건, 시간 오름차순:

> `problem_attempted` → `assessment_failed` → `mastery_updated` → `skill_mastery_updated` →
> **`misconception_detected`** → `skills_resolved` → **`hint_provided`(3)** → `answer_submitted` →
> **`hint_provided`(4)** → `problem_attempted` → `assessment_failed` → `mastery_updated` →
> `skill_mastery_updated` → `skills_resolved`

하네스는 이 시간선에서 세 가지를 단언한다: ①촉발원 4종(`problem_attempted`·`misconception_detected`·
`hint_provided`·`mastery_updated`)이 전부 있는가 ②**인과 순서** — `misconception_detected`가
`hint_provided`보다 앞서는가(뒤면 그 개입은 이 오답의 결과가 아니다) ③`problem_attempted`가 2건
이상인가(재시도가 시간선에 남아 루프가 닫혔다는 증거).

**정직 표기 — 한 화살표는 트레이스에 나타나지 않는다.** 5마디(새 문제)의 `recommendation_generated`는
트레이스 원천 대장이 **`UNJOINABLE`로 선언**한 축이다(`l2/learning_event_trace.py`) —
`evidence_event`에 `user_id` 컬럼이 없고 `session_id`가 호출마다 uuid4 placeholder라 "이 학생의 추천"을
집어낼 조인 키가 없다. 그래서 그 화살표만은 **이벤트가 아니라 응답 산출물**로 판정했다(추천 문항이
틀린 문항이 아니라는 것 + `reason.mastery`가 그 오답이 쓴 값과 같다는 것). 0건은 추천이 없었다는
뜻이 아니라 조인할 수 없다는 뜻이고, 그 사실은 저장소가 이미 대장에 적어 둔 것이다.

## 4. 이 판정이 배제한 것과 배제하지 **못한** 것

배제한 것(뮤테이션으로 증명 — §5):
- "오답을 오개념으로 읽지 않는다"
- "오개념을 상태에 남기지 않는다"
- "코치가 누적 가설을 읽지 않고 그 턴 발화만 본다"
- "힌트 사다리의 직전값을 적재하지 않는다 / 적재는 하되 읽지 않는다"
- "추천이 시도 이력을 보지 않는다 / 추천 근거가 그 오답이 쓴 값을 인용하지 못한다"

배제하지 **못한** 것(정직 표기):
- **교정 콘텐츠의 다른 표면**. `POST /v1/scene/weak-concept`(학습 장면 기반 교정)은 시각화 spec 생성이
  LLM 라우터를 경유해 스텁이 필요하므로 이 판정이 지나가지 않았다. 3마디의 통과 근거는 코치 경로
  하나이며, 장면 경로의 연결성은 이 판정이 말하지 않는다.
- **교정·힌트의 교수학적 적절성**. 원 문서 지시대로 품질은 보지 않았다(연결성만).
- **새 문제가 오개념을 겨냥하는가**. 5마디의 추천은 *숙달* 기반이지 *오개념 태깅 유사문제*가 아니다
  (그 축은 `MISC-03`이 소유하며 main 부재). 게이트 문면은 "새 문제"이지 "같은 오개념 태그 문항"이
  아니므로 판정은 통과이나, 루프의 정밀도가 그만큼이라는 사실은 적어 둔다.

## 5. 하네스 변별력 — 뮤테이션 8종 전건 RED

정상 입력에서 초록인 것은 보호의 증거가 아니므로, **서빙 코드에서 화살표를 하나씩 끊고** 판정이 실제로
미통과를 내는지 확인했다(`scripts/ops/verify_week3_gate_discrimination.py`). 주입마다 ①치환 대상이 정확히
1건인지 ②주입 후 해시가 원본과 다른지 ③원복이 바이트 동일한지를 단언한다(원복은 `git checkout`이 아니라
바이트 백업 복원 — 미커밋 작업분 보호).

| 뮤테이션 | 끊은 화살표 | 결과 |
|---|---|---|
| M1 | 오답 → Misconception: 답안을 오개념으로 읽지 않는다 | RED |
| M2 | Misconception → 교정: 후보를 상태에 남기지 않는다 | RED |
| M3 | Misconception → 교정: 코치가 누적 가설을 읽지 않는다 | RED |
| M4 | 교정 → 힌트: 사다리 직전값의 **적재**를 끊는다 | RED |
| M5 | 교정 → 힌트: 적재는 하되 **읽기**를 끊는다 | RED |
| M6 | 힌트 → 새 문제: 시도 이력 제외를 지운다 | RED |
| M7 | 힌트 → 새 문제: 추천 근거에서 실측 숙달을 지운다 | RED |
| M8 | 대조군: 개입이 가설과 무관하게 항상 나온다 | RED |

**주입 하네스 자신도 한 번 걸렸다.** M8의 최초 앵커가 실제 소스와 달라 치환 대상 0건이었고, 주입 실재
검사가 그것을 "통과"가 아니라 **주입 불가**로 보고했다(exit 1). 앵커를 실측 소스로 고친 뒤 RED가 났다 —
이 검사가 없었으면 M8은 "정상 파일에 대해 돌고 GREEN"으로 보였을 것이다(2026-09-06 규칙의 실동작 확인).

**픽스처 하나는 M6이 고쳐 놓았다.** 처음에는 학생이 틀릴 문항을 *더 어려운* 쪽에 두었는데, 그 배치에서는
시도 이력 제외를 통째로 지워도 다른 문항이 뽑혀 5마디가 조용히 통과했다(M6 생존). 틀릴 문항을 *가장 쉬운*
쪽으로 옮기자(오답 뒤 θ는 바닥으로 내려가므로 제외가 없으면 그 문항이 1순위가 된다) RED가 났다 —
"이 절이 없으면 무엇이 통과하는가"를 픽스처가 실제로 밟게 만든 것이다.

**음성 대조군**도 함께 둔다(`test_remediation_content_requires_a_prior_wrong_answer`): 오답 이력이 **없는**
학습자가 *완전히 같은 요청*을 보내면 `intervention`은 `None`이고 활성 가설은 0건이다. 이것이 없으면 3마디
단언이 "코치는 언제나 개입을 낸다"인지 "이 오답 때문에 냈다"인지 구별할 수 없다.

## 6. 인접 결함 1건 — 정책이 지시하는 교정 경로가 기본 학습자에게 닿지 않는다

> **기본 학습자(`NEW`)의 오답은 정책 전이가 거부돼 `next_action`이 항상 `null`이다.**

게이트의 여섯 마디에 없는 축이다(그래서 판정은 통과다). 그러나 계획서 §9의 보정 정책(`MISC-30`)과 §3의
상태 머신(`EOS-105`)이 실제로 도는 유일한 경로가 이것이므로 조용히 두지 않는다.

「실측」 기본 학습자의 오답 응답 `learning_state` 블록:

> from_state: NEW · to_state: NEW · rule_id: null · next_action: null ·
> rejected_transition: "NEW → ASSESSING (UndefinedTransitionError; NEW에서 가능한 상태: ['DIAGNOSING'])"

「실측」 생애주기 전이 3건(NEW→DIAGNOSING · DIAGNOSING→READY · READY→LEARNING)을 **손으로** POST한 뒤
같은 오답을 내면:

> from_state: LEARNING · to_state: REMEDIATING · rule_id: R3-wrong-misconception ·
> next_action: REMEDIATE_MISCONCEPTION · target_misconception_id: distribution-over-power ·
> rejected_transition: null

즉 **정책 자체는 살아 있고 도달 경로만 없다.** 그 전이 3건을 적재하는 서버 경로도, 클라이언트 호출부도
0건이다(역할 기반 검색 — `DIAGNOSIS_STARTED`·`DIAGNOSIS_COMPLETED`·`LEARNING_STARTED`·`PRACTICE_STARTED`
4종이 `schema/learning_state.py`의 enum 선언에만 등장하고, `src/mobile`·`src/web`에 `learning-state` 호출
0건). 사람이 손으로 전이를 POST하지 않는 한 R3(오개념 교정)·R5(반복 실패)는 영원히 발동하지 않는다.

이것은 숨겨진 버그의 발견이 아니라 **선언된 한계의 해소 과제**다 — `l2/learning_state_machine.py` 모듈
docstring이 이미 자인한다("상태 이력이 없는 기존 학생(= 전원)은 … 응답 제출 시 전이가 거부된다").
어느 축으로 해소할지(서버가 전이를 적재 / 전이표를 연다 / 클라가 적재)는 파급이 서로 달라 판정과 사유
기록을 acceptance가 요구한다.

**후속 태스크**: `EOS-115`. 저장소에는 `xfail(strict=True)`로 동결했다
(`test_policy_directed_remediation_fires_for_a_default_learner`). `skip`이 아닌 이유는 저장소 선례와 같다 —
skip은 "검사가 없는 것"과 구별되지 않아 침묵 실패가 되고, strict xfail은 고쳐지는 순간 **XPASS로 빨강**이
되어 표식 제거를 강제한다.

## 7. 판정 밖(원 문서 지시)

AI 답변 품질·교정 발화의 교수학적 적절성·추천 품질·UI는 보지 않았다. 연결성(촉발 관계·자동 전파)만이
대상이다. 학습자 상태 테이블은 한 줄도 직접 쓰지 않았고(전부 HTTP 부수효과), 저작 콘텐츠만 ORM으로
심었다 — Week 1 게이트의 시딩 경계를 Week 2를 거쳐 그대로 승계한다(그쪽 헬퍼 재사용·재구현 0).
