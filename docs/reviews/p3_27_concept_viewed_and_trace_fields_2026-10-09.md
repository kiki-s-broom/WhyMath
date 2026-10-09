# P3-27 판정 — `concept_viewed` 실체화 결정 + 트레이스 추적 필드 보강 판정

> **판정 기준: `main 713512bc`** (P3-13 머지 직후) 위에 이 브랜치(`claude/dazzling-dijkstra-xe6kr5`)의 변경을 얹은 상태다. 판정은 시점에 종속되므로 해시를 박는다.
> **테스트 계정 기준** — 내부 테스트 계정(운영 OAuth 콜백 경로로 로그인한 합성 학생)의 세션이다. 실사용자 검증으로 계상하지 않는다(ARCH-66 ⑥ · 게이트 `G-student-work-after-internal-completion` 판정 이후로 연기).
> 출처: `docs/reviews/p3_13_gate_d_e_recheck_2026-10-09.md` §4 F2·F3.

## 1. 한 줄 요약

- **① `concept_viewed`**: (나) **세션 writer가 개념을 싣게 확장**하는 안을 채택했다. 새 테이블·새 컬럼이 없다(컬럼 `learning_session.target_concept_id`는 DDL §6.1부터 있었고 writer가 비워 뒀을 뿐이다). (가) 콘텐츠 열람 로그 좌석은 새 테이블이 필요해 `P3-29`로 **이월**한다.
- **② 추적 필드**: 숙달 변경의 `session_id`·`problem_id`는 **보강**했다(시도 귀속 투영만 · 새 컬럼 0). 코치 도중 이벤트(힌트 요청·응답 지연)의 `session_id`는 **원천이 없어** 보강하지 않고 `P3-30`으로 이월한다. 오개념 가설은 **구조적 N/A**다.
- **③ 검증**: census 동결 단언을 승격하고, 기록·귀속을 끊는 주입 14종이 전건 RED임을 실측했다. 이 과정에서 내 검증의 공백 5건을 찾아 메웠다(§5-3).

## 2. 결정 ① — `concept_viewed`는 어떻게 채우는가

### 2-1. 두 안의 비교

| | (가) 콘텐츠 열람 로그 좌석 신설 | (나) 세션 개시 이벤트가 개념을 싣도록 writer 확장 |
|---|---|---|
| 필요한 것 | 새 테이블(학습자×콘텐츠 열람 행) + 쓰기 경로 + 열람 신호를 보내는 클라이언트 | 컬럼은 **이미 있다**(`learning_session.target_concept_id`). writer가 값을 채우면 된다 |
| 새 Entity·스키마 | **필요** → Phase 3 범위규율에 따라 Release Blocker 판정 선행 | **불필요** |
| "개념을 봤다"의 의미 | 콘텐츠를 열람한 사건(가장 정확) | 그 묶음에서 문항을 다룬 첫 개념(근사) |
| Gate D 영향 | 없음(Gate D는 이미 8/8 판정) | `concept_viewed` 역할의 유일한 생산 이벤트가 개념을 싣게 됨 |

### 2-2. 결정과 근거

**(나)를 채택한다.** 근거 3가지다.

1. 새 Entity·스키마가 필요 없어 Release Blocker 판정 없이 진행할 수 있다.
2. Gate D는 이미 역할 대조로 8/8 충족 판정(P3-13)이라 (가)를 하지 않아도 Release Blocker가 아니다 → (가)는 12월 이후로 이월한다(`P3-29`).
3. 실세션에서 `concept_viewed` 역할이 약했던 이유 — "어느 개념을 봤는가"를 시간선이 말하지 못함 — 를 (나)가 직접 해소한다. 실측: `concept_selected`의 `concept_id` 채움 **0/1 → 1/1**.

### 2-3. 값의 의미 (정직한 한계)

`target_concept_id`는 스키마 설명이 "이번 세션의 학습 목표 개념"이지만, 이 writer가 채우는 값의 의미는 **"그 묶음(30분)에서 문항을 실은 첫 활동이 확인한 대표 개념"**이다.

- **덮어쓰지 않는다.** 한 묶음에서 여러 개념을 풀어도 컬럼은 첫째 하나만 말한다. 학습한 개념의 완전한 집합이 아니다(개념별 사실은 `mastery_updated`가 말한다).
- **NULL→값 한 방향만 있다.** 추천 조회(`/me/next-problem`)는 문항을 고르기 *전에* 세션을 잇기 때문에 개념을 모른다 → 그 호출처에는 `problem_id`를 넘기지 않고 NULL로 둔다(날조 금지). 뒤 활동(시도·코치)이 문항을 실어 오면 그때 채운다.
- **시각이 어긋날 수 있다.** `concept_selected`의 `occurred_at`은 세션 개시 시각이고, 개념이 확인된 시각은 그보다 늦을 수 있다. 트레이스의 `reason` 문구에 명시했다.
- **대표 개념 해석은 재구현하지 않았다.** `l2.mastery_tracking.get_primary_concept_id`(PRIMARY→TESTED 폴백)를 재사용했다.
- **개념 해석이 실패해도 학습 요청은 계속된다.** 해석은 자체 SAVEPOINT 안에서 하고, 실패하면 예외 타입명을 로그에 남기고 `failure_count`에 합산한 뒤 개념 없이 세션에 결합한다.

### 2-4. 소비처 영향

`target_concept_id`를 읽는 곳은 일일 롤업(`l2/learning_metrics_rollup.py`의 `concepts_practiced`)뿐이다. 이전에는 이 컬럼이 항상 NULL이라 `concepts_practiced`가 비어 있었다. 이제 **세션당 최대 1개(첫 확인 개념)**가 들어간다. 이 값은 "연습한 개념의 완전한 목록"이 아니므로 그렇게 읽으면 과소 집계다. `src` 안에서 `concepts_practiced`를 읽는 다른 소비처는 없다(스키마·영속 정의만).

## 3. 결정 ② — 추적 필드 보강 판정 (이벤트별)

| 이벤트 | 필드 | 판정 | 근거(실측) |
|---|---|---|---|
| `mastery_updated` · `skill_mastery_updated` | `session_id` · `problem_id` · `attempt_id` | **보강** (시도 귀속 투영) | `concept_mastery_history`·`skill_mastery_history` 모두 `attempt_id`를 보유한다. 시도(`problem_attempt`)에 LEFT JOIN해 복원한다. 실측 채움 **0/20 → 20/20** (그리고 각 값이 해당 시도의 문항·세션과 **같은지**까지 대조한다) |
| (같은 이벤트, 배치·백필 측정) | 위 3필드 | **NULL 유지** | `attempt_id`가 NULL인 행은 귀속할 시도가 없다. 채우지 않는다 |
| `hint_requested` | `session_id` | **보강 불가 → `P3-30` 이월** | 시도 포인터(`attempt_id`) 실측 **0/1** — 코치 대화 도중에는 시도가 아직 없다. `attempt_event`에 세션 컬럼도 없다. 귀속하려면 컬럼 추가(스키마 변경)가 필요하고, 시간창으로 세션을 추정하는 것은 귀속이 아니라 날조다 |
| `answer_submitted` (응답 지연) | `session_id` | **보강 불가 → `P3-30` 이월** | 위와 같다. 시도 포인터 실측 **0/1** |
| `misconception_detected` | `session_id` · `problem_id` | **구조적 N/A** | 오개념 가설은 학습자×오개념 누적 단위라 문항 하나·세션 하나에 귀속되지 않는다 |
| `problem_attempted` | `concept_id` | **보강하지 않음** | 숙달 변경이 이제 `attempt_id`와 `concept_id`를 함께 싣기 때문에 시도→개념은 `attempt_id`로 되짚을 수 있다. 투영에 문항→대표 개념 정책을 얹으면 조회마다 그 정책(PRIMARY→TESTED 폴백)에 의존하게 된다 |

범위 밖: `diagnostic_started` 등 진단 이벤트의 `session_id`는 이번 판정이 다루지 않았다(P3-13 §3 표에 현황만 있다).

`content_version`은 이 태스크의 범위가 아니다 — `EOS-47-attempt-version-pinning` 소유다. 현재 `problem.problem_version_id`는 서빙 판 포인터라 시도 시점의 판이 아니므로 그 값으로 채우면 날조다.

## 4. 코드 변경

| 파일 | 변경 |
|---|---|
| `l2/learning_session_writer.py` | `touch_learning_session(concept_id=)` · `record_learning_activity(problem_id=)` · `_adopt_concept`(NULL→값, 덮어쓰기 금지) · `_resolve_concept`(자체 SAVEPOINT·타입명 로그·이중 회계) |
| `api/me.py` · `api/coach.py` | 시도·코치 4곳이 `problem_id`를 writer에 넘긴다. 추천 조회는 의도적으로 제외 |
| `l2/learning_event_trace.py` | 숙달 질의가 `attempt_id`를 들고 와 시도에 LEFT JOIN, 투영이 `attempt_id`·`problem_id`·`session_id`를 싣는다. `concept_selected` 설명 문구 갱신 |
| 테스트 | census 승격 단언 + 코치 첫 활동 시나리오 1건 · writer 통합 8건 · 호출처 전수 AST 2건 · 트레이스 단위 5건 · API 가짜 행 보정 · 판별 스크립트 `C03` 갱신 + `C10`~`C14` 신설 |

스키마·마이그레이션·`LearningEvent` 봉투 변경은 **0건**이다.

## 5. 검증 (③)

### 5-1. 승격한 단언 (`test_gate_d_event_role_census.py`)

- `concept_selected`의 `concept_id`가 **시나리오 개념과 같다**(종전: "전부 None"). 이 장면은 첫 활동이 추천 조회라 NULL로 열리고 시도가 채우므로 HTTP 경로 전체의 NULL→값 채움을 함께 본다.
- 숙달 변경의 `attempt_id`·`problem_id`·`session_id`가 **해당 시도의 값과 같다**(비어 있지 않음이 아니라 같음).
- 코치 도중 이벤트의 `session_id`·`attempt_id`는 **None으로 동결**(소유 `P3-30` — 고쳐지면 이 단언이 깨지며 소유 태스크를 가리킨다).
- `content_viewed`는 DORMANT 동결 유지(소유 `P3-29`).

### 5-2. 기록·귀속 차단 주입 — 14종 전건 RED

`scripts/ops/verify_gate_de_discrimination.py --suite census` 결과: 기준선 통과, **14/14 RED**, 원복 전건 sha256 동일.

| 주입 | 끊은 것 | 관측된 실패(첫 줄) |
|---|---|---|
| C01~C09 | 이벤트 생산자 9곳(종전) | 역할 대응 이벤트 소실 |
| **C10** | 문항→개념 해석 | "concept_selected가 첫 확인 개념을 싣지 않는다" |
| **C11** | 이어진 세션의 NULL→값 채움 | 같은 메시지 (개념 없이 열린 세션을 못 채움) |
| **C12** | 숙달 변경의 세션 귀속 투영 | "숙달 변경의 세션이 그 시도의 세션과 다르다" |
| **C13** | 숙달 변경의 문항 귀속 투영 | "숙달 변경의 문항이 그 시도의 문항과 다르다" |
| **C14** | 시도 조인이 영영 안 맞음 | "숙달 변경의 문항이 그 시도의 문항과 다르다" |

새 주입 5종의 실패가 모두 **승격한 바로 그 단언의 메시지**다(우연한 다른 실패가 아니다).

### 5-3. 검증 중 찾은 공백 (고친 것)

1. **기존 주입 `C03`이 새 코드에서 적용되지 않았을 것**: `C03`은 writer 호출부의 정확한 원문을 치환하는데, 내가 그 호출을 여러 줄로 바꿨다. 스크립트가 치환 대상 수(≠1)를 검사해 "주입 하네스 결함"으로 크게 실패하므로 조용히 위장되지는 않지만, 원문에 맞게 갱신했다.
2. **로그 침묵 공백(`W5`)**: 개념 해석 실패 때 예외 타입명을 로그에 남기는 동작을 내 테스트가 확인하지 않아, 로그 호출을 지워도 통과했다(뮤테이션 생존으로 발각). 테스트에 `caplog` 단언을 추가해 닫았다.
3. **경합 합류 경로 공백(`W7`)**: 경합에서 진 요청이 승자 세션에 합류하며 개념을 채우는 분기를 아무 테스트도 밟지 않았다. 기존 결정론적 동시성 테스트 구조를 빌려 추가했다.

writer 통합 테스트에 대한 뮤테이션 7종(덮어쓰기 허용·개념 없이 개설·이어진 세션 채움 끊김·해석 실패가 결합을 죽임·해석 실패 로그 침묵·문항 없는데 해석·합류 패자 채움 끊김)이 전건 RED다.

4. **호출처 전달 공백**: census가 실제로 밟는 채움 경로는 호출처 6곳 중 `/me/attempts` 하나뿐이라, 코치 4곳에서 `problem_id=`를 빼도 어떤 테스트도 RED가 되지 않았다. 호출 표현식의 키워드 인자를 AST로 전수 보는 테스트(`TestEveryServingCallSiteCarriesTheProblem`)와, 코치가 첫 활동인 시나리오 테스트(`test_coach_first_activity_opens_the_session_with_the_problem_concept`)를 추가했다. 주입 실측: 호출처별 `problem_id=` 제거 5종이 AST 테스트에서 전건 RED, `create_session` 제거는 시나리오 테스트에서도 RED.
5. **전체 스위트에서야 드러난 가짜 행 1파일**: 숙달 질의 모양을 흉내 내는 테스트 더블이 `test_learning_event_trace.py`와 `api/test_me_learning_trace.py` 두 곳에 있었다. 앞의 것만 부분 실행에서 잡혔고, 뒤의 것(8건 실패)은 **전체 스위트**를 돌린 뒤에야 보였다. 둘 다 새 질의 열 3개를 기본값 None으로 추가해 고쳤다.

### 5-4. 남은 한계 (정직하게)

- **전건 RED는 가드의 세기일 뿐 커버리지의 증거가 아니다.** census는 개념이 하나뿐인 장면이라 "덮어쓰기 금지"를 못 본다(그 분기는 writer 통합 테스트가 맡는다).
- 코치 호출처 4곳 중 동작(HTTP→개념)까지 확인한 것은 `create_session` 하나다. `append_turns`·`_complete_problem`·`_record_first_wrong_submission`은 `problem_id=` 전달을 AST로만 확인했다(셋 다 같은 키워드를 넘기는 기계적 전달이고, 개념 해석 자체는 writer 통합 테스트가 본다).
- 경합 승자가 개념을 갖고 패자가 다른 개념을 가진 경우는 "먼저 채운 쪽이 이긴다"로 동작하며, 그 순서는 커밋 순서가 정한다(결정론적 우열 규칙이 아니다). 컬럼의 의미가 '첫 확인 개념'이라 허용 범위로 본다.
- 이 판정은 **테스트 계정·로컬 기준**이다. CI에서의 RED는 PR을 열어 실제 CI가 해당 스텝을 실행했음을 확인해야 성립한다.


## 6. 이월

| 태스크 | 내용 | 이월 사유 |
|---|---|---|
| `P3-29-content-view-log-seat-decision` | (가) 콘텐츠 열람 로그 좌석 | 새 테이블 필요 · Gate D는 이미 충족 → Release Blocker 아님 |
| `P3-30-attempt-event-session-attribution` | 코치 도중 이벤트의 `session_id` 귀속 | `attempt_event.session_id` 컬럼(스키마 변경) 필요 |
