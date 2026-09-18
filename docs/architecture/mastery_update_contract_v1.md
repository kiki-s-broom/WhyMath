# Mastery 갱신 호출 계약 v1 (EOS-13 · EOS-108)

> 판정 기준(§1~§7, EOS-13): main `c77efb0f` + 당시 브랜치 작업분. 그 작업분은 이후 `a5d9c80f`
> (PR #1188)로 main에 착지했다.
>
> 판정 기준(§8~§11, EOS-108): main `a34d31d4` + 본 브랜치 작업분(**미머지**). 그 절들이 기술하는
> 배선은 이 브랜치 기준이며 main 기준으로는 아직 존재하지 않는다.

출처: 계획서 300 §6(Mastery Engine v1 — "반드시 엔진 인터페이스를 분리합니다") + §2(알고리즘보다
Contract). 코드 정본은 두 파일이다.

| 무엇 | 파일 | 계층 |
|---|---|---|
| 순수 타입·Protocol(계약 그 자체) | `src/backend/whymath_backend/schema/mastery_contract.py` | `schema`(최하위) |
| 추정기 구현·레지스트리·진입점 | `src/backend/whymath_backend/l2/mastery_contract.py` | `l2` |

---

## 1. 무엇을 바꿨나 — 알고리즘이 아니라 *형태*

**전**(스칼라 5개·상태와 증거가 분해돼 들어옴):

```
compute_mastery_record(prior_mastery, prior_sample_size, correct, model, elapsed_days)
```

**후**(상태 + 증거):

```
update_mastery(learner_state: LearnerMasteryState,
               assessment_evidence: AssessmentEvidenceInput,
               *, estimator: MasteryEstimator | None = None) -> MasteryUpdate
```

- `LearnerMasteryState` — 한 축·한 대상의 *직전 측정*(`mastery` / `sample_size` /
  `measured_at`). **미측정은 `None`이다**(0이 아니다).
- `AssessmentEvidenceInput` — 이 계약이 **실제로 읽는 두 속성**(`correct`·`observed_at`)만
  선언한 구조적 Protocol.
- `MasteryUpdate` — 좌석 컬럼 3개(`mastery`·`confidence`·`sample_size`) + 관측 가능성 3개
  (`prior_mastery`·`elapsed_days`·**`estimator_id`**).

`estimator_id`가 산출에 실리는 이유: 추정기를 갈아 끼울 수 있게 만든 이상, 산출이 자기 출처를
말하지 않으면 "무엇이 돌았는지 모르는 상태"가 된다(CLAUDE.md "작동 신호 없는 알고리즘 부착
금지"). 정상 응답 200은 어느 추정기가 일했다는 증거가 아니다.

## 2. 교체 가능성을 타입으로 (acceptance ②)

`MasteryEstimator`는 Protocol이다 — `estimator_id` + `estimate(state, evidence)` 두 멤버.
구현은 **id로 레지스트리에 등록**되고, 기본 추정기는 `ContextVar`로 들고 있다.

```
register_estimator("dkt-v1", DktMasteryEstimator)     # 등록
with use_estimator("dkt-v1"):                          # 기본 교체(블록 한정·자동 원복)
    ...                                                # 적재 경로는 한 글자도 안 바뀐다
```

교체 시 수정이 필요한 호출부는 **0건**이다. `record_attempt_mastery` ·
`record_problem_attempt_mastery` · `record_problem_attempt_skill_mastery` ·
`POST /v1/me/attempts` · `api/coach.py` 어디도 구체 추정기 클래스를 이름으로 알지 않는다.
이것을 문장이 아니라 테스트로 잰다 —
`tests/backend/l2/test_mastery_contract.py::TestSwappableWithoutCallsiteEdits`가 항상 0.5를
내는 스텁을 꽂아 **적재 값이 실제로 바뀌는지**를 확인하고, 같은 테스트가 기본 추정기에서는
0.5가 아님을 함께 단언한다(성공 방향 대조군).

미등록 id는 조용히 기본값으로 떨어지지 않고 `UnknownMasteryEstimatorError`다 — "DKT로 바꿨다고
생각했는데 실은 BKT가 돌고 있었다"가 이 구조에서 가장 비싼 실패다.

## 3. 축 통합 (acceptance ③)

계약은 **하나**이고, 축은 `LearnerMasteryState.axis`(`MasteryAxis.CONCEPT` / `SKILL`)가 값으로
들고 다닌다. 내부 구현(어느 이력을 읽고 어느 좌석에 쓰는가)은 여전히 두 모듈로 갈라져 있다.

통합이 재계산을 낳지 않는 이유: 두 축은 원래부터 같은 커널(`compute_mastery_record`)을
공유했고, 이번 변경은 그 한 벌을 계약 뒤로 옮겼을 뿐이다. 오히려 **중복이 줄었다** — 경과일
(망각 감쇠 입력) 계산식이 두 모듈에 복제돼 있던 것을 `LearnerMasteryState.elapsed_days_until`
한 자리로 모았다.

## 4. 행동 동결 (acceptance ④)

숙달 수치는 **바뀌지 않는다**. 구조로 보장한다 — `BktMasteryEstimator.estimate`의 내부는
`compute_mastery_record` 호출뿐이므로 값을 만드는 코드가 하나다. 그 위에 측정을 얹는다:

- `TestBehaviourFrozen::test_matches_kernel_over_grid` — prior 6종 × 정/오답 × 축 2종 전수 대조.
- `test_matches_kernel_with_forgetting` — `p_forget>0`·경과 4종에서 커널과 동일.
- 기존 숙달 전파 테스트(`test_mastery_tracking.py` 38건 ·
  `test_skill_mastery_tracking.py`)는 **한 줄도 고치지 않고** 통과한다.

## 5. 집행 지점 (정본화 ≠ 집행 — 있는 척 금지)

**계약을 실제로 경유하는 코드**(이 브랜치 기준):

| 경유 지점 | 축 | 비고 |
|---|---|---|
| `l2/mastery_tracking.py::_stage_attempt_mastery` | 개념 | `concept_mastery_history` 적재 |
| `l2/skill_mastery_tracking.py::_stage_skill_attempt_mastery` | 스킬 | `skill_mastery_history` 적재 |

그 위의 서빙 진입점(`POST /v1/me/attempts` → `record_problem_attempt_mastery` ·
`record_problem_attempt_skill_mastery`, `api/coach.py` 완료 경로)은 위 두 함수를 통해
**간접적으로** 계약을 경유한다.

**배선이 없는 것**(정직하게):

- API·L3·L4가 `LearnerMasteryState`·`MasteryUpdate`를 **직접 읽는 배선은 없다.** 응답 스키마
  (`ConceptMasteryUpdate`·`SkillMasteryUpdate`)는 종전대로 ORM 행에서 만들어진다 — `estimator_id`는
  아직 어디에도 노출·적재되지 않는다(좌석 신설 금지·`ARCH-37` 80테이블 동결).
- `l2/learner_state.py::LearnerState`(조회 표면)와 이 계약의 `LearnerMasteryState`(갱신 입력)는
  **아직 잇지 않았다.** 단일 조회 표면은 `EOS-10` 소관이다.
- 추정기가 BKT **1종뿐**이다. 2번째 실구현(DKT)은 이 태스크 범위 밖이며(태스크 notes "구현 금지
  경계"·§15 동결 13종), 여기서 증명한 것은 *꽂을 자리가 열려 있다*는 것이다 — 테스트 스텁으로
  실제 교체를 실증했다.
  **[EOS-108 정정]** 이 진술은 더 이상 사실이 아니다 — 계획서 §6 가산 규칙을 구현한
  `simple-additive-v1`이 두 번째 *진짜* 구현으로 등록됐다(§8). 기본값은 여전히 `bkt-v1`이다.

## 6. `EOS-12`와의 이음매 (가장 중요한 경계)

`AssessmentEvidence` **구체 타입의 좌석은 `EOS-12`가 소유**하며 아직 착지하지 않았다. 그래서
EOS-13은 evidence의 *구조적 입력 계약*만 정의한다.

- **EOS-12가 착지하면 그 `AssessmentEvidence`가 `AssessmentEvidenceInput`을 만족해야 한다** —
  필요한 것은 `correct: bool`·`observed_at: datetime` 두 속성뿐이며, 상속은 필요 없다(구조적
  타이핑). 다른 필드를 얼마든지 더 들고 있어도 이 계약은 그것을 읽지 않는다.
  `TestEvidenceProtocolSeam::test_future_assessment_evidence_satisfies_without_inheritance`가
  그 상황을 미리 재현해 둔다.
- 그때 `l2/mastery_contract.py::AttemptOutcomeEvidence`(임시 최소 어댑터)는 **폐기 대상**이다.
  호출부 시그니처는 바뀌지 않는다.
- **Protocol의 속성을 늘리지 마라** — evidence의 두 번째 진실 원천이 된다.
  `test_protocol_reads_exactly_two_attributes`가 속성 집합을 동결해, 늘리려면 의식적으로 깨야
  한다.
  **[EOS-108 정정]** 그 동결을 **한 번 의식적으로 깼다**(2→3: `attempt_id` 편입). 근거와 그것이
  두 번째 진실 원천이 아닌 이유는 §9에 있다. 동결 테스트 이름도
  `test_protocol_reads_exactly_three_attributes`로 바뀌었고, 같은 클래스의
  `test_landed_assessment_evidence_satisfies_protocol`이 **착지한 실물**로 이음매를 대조한다.
- 이름 근거: 2026-09-16 Kiki 판정(A안)으로 계획서 쪽 per-answer 채점 산출의 이름이
  **`AssessmentEvidence`** 로 확정됐다. 저장소 정본 `schema/assessment.py::Assessment`(진단
  세션)와는 다른 객체다 — `schema/learning_loop_contract.py`의 `ASSESSMENT_EVIDENCE` 좌석 주석이
  정본이다.

## 7. 범위 밖 (손대지 않은 것)

- **스킬 축 소비 전환** — `EOS-63` 소유. 이 태스크는 계약 *형태*만 다뤘고, 어느 축을 읽어
  학습자에게 보여줄지는 건드리지 않았다.
- **신규 DB 테이블·마이그레이션 0건** — `ARCH-37` 80테이블 동결 준수.
- **추정기 파라미터 적합(EM)·DKT 신경망** — 여전히 후속.

---

# Mastery Engine v1 — 값·경계·멱등·단일 경로 (EOS-108)

> 판정 기준: main `a34d31d4` + 본 브랜치 작업분(미머지).

`EOS-13`은 **형태**를 세웠고 값 축은 의도적으로 열어 뒀다("계약만 바꾸고 숙달 수치는 바뀌지
않아야 한다 — 값이 바뀌면 리팩터가 아니라 정책 변경이므로 별건으로 분리한다", acceptance ④).
`EOS-108`이 그 별건이며, 계획서 §6 지시문 7항목 중 EOS-13이 이행한 1항목(인터페이스)을 뺀
나머지를 소유한다.

## 8. 갱신 규칙 정본화 — 그리고 기본값으로 올리지 *않은* 이유

계획서 §6의 네 규칙을 `l2/mastery_estimators.py::AdditiveMasteryEstimator`(id
`simple-additive-v1`)가 코드로 정본화한다. 상수가 규칙의 단일 진실 원천이다.

| 규칙 | 상수 | 값 |
|---|---|---|
| 정답 이득 | `CORRECT_GAIN` | `+0.10` |
| 오답 감점 | `WRONG_PENALTY` | `-0.08` |
| 힌트 사용 시 이득 계수 | `HINT_GAIN_FACTOR` | `x0.7` |
| 연속 정답 1회당 confidence 가산 | `CONFIDENCE_STREAK_STEP` | `+0.05` (상한 4회 = `+0.20`) |

세 가지 설계 판단을 적어 둔다.

1. **감점에는 힌트 계수를 곱하지 않는다.** 곱하면 힌트가 감점 회피 수단이 되고, §6에도 그
   규칙은 없다.
2. **`None`(모른다)을 `False`/`0`으로 접지 않는다.** 힌트·연속 정답은 선택 Protocol
   (`HintUsageSignal`·`StreakSignal`)로 읽고 `hint_used_of`·`consecutive_correct_of`가 3상태를
   돌려준다. 접으면 "힌트를 안 썼다"와 "힌트를 썼는지 모른다"가 같은 숫자를 내고, **생산자가
   배선됐는지를 사후에 판별할 수 없게 된다**.
3. **출발점과 신뢰도 척도를 `bkt-v1`과 맞췄다**(`INITIAL_MASTERY == BktParameters().p_init`,
   `CONFIDENCE_HALFLIFE` 동일). 다르면 두 추정기의 차이가 *규칙의 차이*인지 *사전값의 차이*인지
   구분되지 않는다. 그 일치는 `test_mastery_estimators.py`가 기계로 동결한다.

### 기본 추정기 처분 — `bkt-v1` 유지 (판단과 근거)

**기본값을 바꾸지 않았다.** 근거 셋:

- **격하다.** BKT는 사후 확률 갱신이고 가산 규칙은 그보다 단순하다. 기본을 바꾸면 전 학생의
  숙달 궤적이 *측정 근거 없이* 달라진다(의사결정 우선순위 4 「학습 효과」).
- **EOS-13 acceptance ④가 요구하는 값 변화 전수 열거를 아직 할 수 없다.** 그 열거에는 비교
  측정이 필요하고, 측정은 이 태스크 범위 밖이다.
- **선행 조건이 미충족이다.** §6 규칙 중 둘(힌트·연속 정답)은 생산자가 배선돼 있지 않다(§11).
  그 상태로 기본을 바꾸면 규칙 4개 중 2개가 상시 미발화인 채로 돈다.

전환 비용은 0에 가깝다 — `use_estimator(ADDITIVE_ESTIMATOR_ID)` 한 줄이며 **호출부는 한 글자도
바뀌지 않는다**. 그것이 계약의 요점이고, `test_swapping_default_changes_the_math_without_
touching_callers`가 그 사실을 실증한다(두 구현이 **다른 값**을 낸다는 단언 포함 — 같은 값을
내면 교체가 증명되지 않는다).

## 9. 경계 — 계약은 추정기를 신뢰하지 않는다

`update_mastery`가 반환 직전 `_enforce_bounds`로 `mastery`·`confidence`를 0~1로 **다시 잰다**.

`MasteryUpdate.__post_init__`이 이미 범위를 검사하는데 왜 또 재는가: 그 검사는 *정상적으로
생성자를 통과한* 객체만 막는다. frozen dataclass도 `object.__setattr__`로 사후 변조가 가능하고,
추정기는 레지스트리를 통해 **임의 구현이 꽂히는 표면**이다. 생성자 검사는 저자의 실수를 막고,
계약 층의 검사는 신뢰하지 않는 구현을 막는다 — 둘 중 하나만 있으면 경로가 남는다.

**예외가 아니라 클램프인 이유**: 범위 밖 산출은 추정기의 결함이지 학생의 사실이 아니다. 예외를
던지면 결함 있는 추정기 하나가 *채점 자체를 실패시켜* 학생의 학습을 멈춘다. 그래서 값은 자르되
**자른 사실을 잃지 않는다** — `MasteryUpdate.bounds_clamped=True`가 산출에 실리고
`MasteryContractBoundsViolation` 경고가 추정기 id·전후 값과 함께 로그에 남는다(침묵 실패 금지).

**NaN만 예외다.** NaN은 모든 비교가 False라 클램프를 조용히 통과한다 — 자를 수 없으므로
`MasteryContractError`로 드러낸다.

## 10. 멱등 — 같은 Attempt는 정확히 한 번

계획서 §6: *"같은 Attempt가 두 번 반영되면 KPI 2(State Integrity < 1%)가 즉시 깨진다."*

**착수 시점 실측**: 숙달 적재 경로에 시도 식별자가 **아예 없었다**. 중복을 못 막은 것이 아니라
중복인지 판정할 재료가 없었다. `l2/attempt_skill_event.py`의 docstring이 그 결과를 이미
기술하고 있었다 — "재시도하면 새 attempt가 생기고 숙달이 한 번 더 적용된다".

### 수단 — 두 겹 (어느 쪽이 권위인지 명시)

| 겹 | 수단 | 막는 것 | 검증 |
|---|---|---|---|
| ① 읽기측 | `_applied_for_attempt` 사전 조회 | *정상 재시도*가 예외를 거치지 않고 끝난다 | `test_mastery_idempotency.py` (hermetic) |
| ② 쓰기측 **(권위)** | 부분 유니크 인덱스 `uq_{concept,skill}_mastery_history_attempt` | **동시 갱신 경합** | `test_mastery_tracking_integration.py` (실 PG) |

①만으로는 부족하다 — check-then-act라 동시 제출 두 건이 서로의 행을 못 보고 둘 다 통과할 수
있다. 그래서 권위는 DB에 둔다. 경합에서 진 쪽은 `IntegrityError`를 받아 rollback한 뒤
**승자의 행을 다시 읽어 돌려준다**(호출자가 보는 결과는 같고, 학습 곡선에는 점이 하나만 찍힌다).

멱등 키가 없는 `IntegrityError`, 또는 승자를 못 찾은 `IntegrityError`는 **멱등 위반이 아니므로
그대로 전파한다** — 삼키면 다른 무결성 오류의 원인을 잃는다.

### 스키마 (마이그레이션 `c1f5a8b2d740`)

`concept_mastery_history`·`skill_mastery_history`에 `attempt_id uuid NULL` + 부분 유니크 인덱스
(`WHERE attempt_id IS NOT NULL`).

- **좌석을 늘리지 않았다** — 기존 두 테이블에 컬럼 1개씩이며 `ARCH-37` 엔티티 동결 불변.
- **FK를 걸지 않았다** — 보존기한 파기로 `problem_attempt`가 사라져도 학습 곡선은 남아야 한다
  (`learning_state_transition`이 `attempt_id`에 FK를 걸지 않은 것과 같은 판단).
- **부분 인덱스인 이유** — 시도에서 유래하지 않은 측정(배치·백필)은 `attempt_id`가 NULL이며
  서로 충돌하면 안 된다. 그 대조군이 통합테스트에 있다(전체 유니크로 바꾸면 RED).
- **비파괴** — 기존 행은 전부 NULL이 되어 인덱스 대상 밖이므로 소급 유니크 위반이 구조적으로
  불가능하다.

### 보호받지 않는 경우를 숨기지 않는다

`attempt_id`가 `None`인 관측은 **멱등 보호를 받지 않는다**. 이것은 결함이 아니라 "이 관측에는
신원이 없다"는 사실이며, 신원 없는 관측을 조용히 중복 제거하면 서로 다른 두 관측이 하나로
합쳐진다. `test_without_attempt_id_two_calls_write_twice`가 그 동작을 계약으로 고정한다.

## 11. 단일 쓰기 경로 + 변경 이벤트

### 변경 이벤트는 새로 만들지 않았다 (이미 있다)

계획서는 "mastery 변경은 항상 이벤트로 남긴다(변경 전후 값 포함)"를 요구한다. 이 저장소에서는
**그 요구가 이미 구조로 충족돼 있다**:

- 숙달 좌석이 **append-only 시계열**이다 — 갱신은 UPDATE가 아니라 새 행이므로, 행 자체가 이벤트다.
- `l2/learning_event_trace.py::project_mastery_rows`가 그 행을 `mastery_updated` /
  `skill_mastery_updated` 이벤트로 투영하며, **`mastery_before`를 SQL `lag`로 채워** 전후 값을
  함께 낸다(`MasteryChange`). `mastery_before=None`은 첫 측정이며 0.0으로 접지 않는다.

그래서 새 이벤트 스토어를 만들지 않았다 — 만들면 같은 사실이 두 곳에 적히고 truth source가
둘이 된다(DP-01 ADR·붕괴 연쇄 ④ "유지보수 지옥"). EOS-108이 더한 것은 그 이벤트의 **신원**
(`attempt_id`)이다: 이제 "어느 시도가 이 변화를 일으켰는가"를 되짚을 수 있다.

### 단일 경로 가드 (`scripts/analysis/mastery_write_path_scan.py`)

숙달 좌석에 쓰는 지점이 Mastery Engine 계약 경로뿐임을 **AST 전수 스캔**으로 동결한다. 세 축을
본다 — 하나라도 빠지면 그 축이 우회로가 된다:

| 축 | 검출 대상 | 허용 |
|---|---|---|
| ① 생성 | `ConceptMasteryHistory(...)` 인스턴스화(별칭 import 추적) | 두 staging 함수 |
| ② 변조 | `.mastery`/`.confidence`/`.sample_size` 대입(`=`·`+=`·주석 대입·튜플 언패킹) | `_MasteryRowView.__init__`(읽기 투영) |
| ③ 일괄 | `update(Model)`·`delete(Model)`(모듈 별칭 포함) | 없음 |

**문자열 금지 목록이 아니라 AST인 이유**: `grep 'ConceptMasteryHistory('`는 공백·줄바꿈·별칭
import에서 뚫린다. AST는 그 표기 변형을 같은 노드로 본다.

**면제 규율**: 허용은 `(파일, 스코프, 축)` 삼중항 + **이유**로만 준다. 파일 단위 면제는 없다.
그리고 **면제가 가리키는 코드가 사라지면 그것도 실패**다 — 공허한 면제는 다음 사람에게 열린
문이다(스캔 0건은 통과가 아니라 실패).

**한계(명시)**: 축 ②는 숙달 좌석 ORM을 import한 모듈에만 적용한다. `confidence`·`sample_size`는
저장소 전역에서 흔한 이름이라(오개념 가설의 신뢰도 등) 이름만으로 판정하면 무관한 모듈이 줄줄이
걸리고, 그러면 사람이 면제를 남발해 가드가 무력해진다. 숙달 행을 *인자로 받아* 변조하는 모듈은
이 축이 보지 못한다 — 다만 그런 모듈도 행을 만들거나(①) 일괄 문장을 쓰려면(③) 여전히 걸린다.

**CI 배선**: `infra-contracts` 잡의 차단 스텝(`needs: changes` 게이팅이 없어 **어떤 PR에서도
돈다** — 우회 경로는 정확히 "숙달과 무관해 보이는" PR에서 생긴다). 변별력은
`tests/infra/test_mastery_single_write_path.py`의 결함 주입 9종이 봉인하고, 배선 자체는 같은
파일의 `test_scanner_is_wired_into_ci`가 동결한다.

## 12. 범위 밖 (EOS-108이 손대지 않은 것)

- **임시 증거 어댑터 폐기** — `EOS-18` 소유. EOS-108은 그 길을 *넓혔다*:
  `AssessmentEvidenceInput`이 이제 `attempt_id`까지 읽고, 착지한 `AssessmentEvidence`가 그
  세 속성을 전부 가지므로 어댑터를 그 타입으로 바꾸기만 하면 된다. 선택 확장 2종
  (`HintUsageSignal`·`StreakSignal`)을 본 Protocol에 **넣지 않은 것**도 그 길을 막지 않기
  위해서다.
- **힌트·연속 정답 생산자 배선** — 두 서빙 호출부는 `hint_used`·`consecutive_correct`를 채우지
  않는다(둘 다 `None`). 기본 추정기 `bkt-v1`은 그 축을 읽지 않으므로 오늘의 숙달 값에는 영향이
  0이지만, `simple-additive-v1`을 기본으로 올리려면 이 배선이 선행한다. **감추지 않고 적어
  둔다**(CLAUDE.md 「작동한 비율」 원칙). 신호 자체는 `EOS-45`(HintUsage 엔티티)·
  `l2/learning_state_evidence.py`(연속 카운트)가 이미 갖고 있어 생산자 배선은 조회 결선이다.
- **응답 경계의 `None` vs `0.0`** — `EOS-17` 소유.
- **숙달 임계값 상수 복제** — `ARCH-53` 소유.
- **스킬 축 소비 전환** — `EOS-63` 소유.
- **DKT·IRT 실구현** — 계획서 §15 동결("복잡한 ML 추천") 준수. 이 태스크가 늘린 것은 *꽂을
  자리*가 아니라 *그 자리가 진짜로 동작한다는 증거*다.
