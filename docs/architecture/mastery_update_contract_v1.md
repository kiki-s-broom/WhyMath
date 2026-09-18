# Mastery 갱신 호출 계약 v1 (EOS-13)

> 판정 기준: main `c77efb0f` + 본 브랜치 작업분(미머지). **아래 "집행 지점"의 배선 상태는 이
> 브랜치 기준이며, main 기준으로는 아직 존재하지 않는다.**

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

## 6. `EOS-12`와의 이음매 — **착지 완료**(EOS-18, 2026-09-18)

EOS-13 시점에는 `AssessmentEvidence` 구체 타입이 아직 없어 이 계약이 *구조적 입력 계약*만
정의하고, `l2/mastery_contract.py::AttemptOutcomeEvidence`(2속성 최소 어댑터)를 임시 좌석으로
두었다. **EOS-12(PR #1187)가 착지하고 EOS-18이 그 어댑터를 폐기**해 이음매가 닫혔다.

- **실 `AssessmentEvidence`가 상속 없이 `AssessmentEvidenceInput`을 만족한다**(구조적 타이핑).
  `AssessmentEvidence`는 `BaseModel`이고 이 Protocol을 상속하지 않는다. 계약은 `correct`·
  `observed_at` 두 속성만 읽으므로 나머지 필드(귀속·coverage·오개념 후보)는 산출에 닿지 않는다.
  검증 = `TestEvidenceProtocolSeam::test_real_assessment_evidence_satisfies_without_inheritance`
  와 `test_real_evidence_extra_fields_do_not_reach_the_estimator`.
- **어댑터는 폐기됐다.** EOS-13이 예고한 "호출부 시그니처는 바뀌지 않는다"는 **실현되지
  않았다** — 어댑터를 지우려면 실 증거가 적재 경로까지 내려와야 하고, 그러려면 증거를 조립하는
  서빙 경로가 그것을 넘겨야 하기 때문이다. 공개 writer의 진입 인자가 바뀌었다:

  | | EOS-13 | EOS-18 이후 |
  |---|---|---|
  | `record_problem_attempt_mastery` | `(session, user_id, problem_id, correct, *, measured_at=…)` | `(session, *, evidence)` |
  | `record_problem_attempt_skill_mastery` | 〃 | `(session, *, evidence)` |
  | `record_attempt_mastery` | `(session, user_id, concept_id, correct, *, measured_at=…)` | `(session, concept_id, *, evidence)` |
  | `_stage_*_attempt_mastery`(내부) | `(…, correct, *, estimator, measured_at)` | `(…, *, evidence, estimator)` |

  귀속(학습자·문항)을 인자로도 받으면 같은 사실의 사본이 둘이 되고, 증거와 다른 학습자를 넘겨도
  아무도 막지 못한다. 인자를 없애 그 실패를 *구조적으로* 불가능하게 만들었다(가드보다 강하다).
- **행동 변화 1건(명시)**: 적재 행의 `measured_at`이 적재 시점 `datetime.now(UTC)`가 아니라
  관측 시각 `evidence.observed_at`이다. 증거와 숙달 행이 같은 채점 1건에 대해 서로 다른 시각을
  말하던 상태가 해소된다. **숙달 수치는 불변**이다 — `observed_at`은 망각 감쇠 입력으로만 쓰이고
  기본 `p_forget=0.0`이 감쇠를 끈다(`l2/bkt.py::_DEFAULT_P_FORGET`).
- **Protocol 속성은 2개로 유지한다**(EOS-18 ④ 재판정). 후보는 `learner_id`·`problem_id`를 더해
  4개로 넓히는 안이었고, 채택하지 않았다: 그 둘은 *추정 입력*이 아니라 **귀속 식별자**다 —
  추정기(BKT·후속 DKT)는 "누구의 어느 문항인가"를 읽지 않고 "맞았는가·언제인가"만 읽는다.
  귀속은 이미 두 자리가 소유한다(대상축 = `LearnerMasteryState.axis`/`target_id`, 계약이 불일치를
  `MasteryContractError`로 차단 · 학습자·문항 = 공개 writer가 증거에서 직접 읽음). 여기에 또
  실으면 귀속의 세 번째 진실 원천이 되고 추정기 Protocol이 추정과 무관한 것을 요구하게 된다.
  `test_protocol_reads_exactly_two_attributes`가 이 판정을 동결한다.
- **어댑터 재도입 방어**(EOS-18 ⑤): 이름 열거가 아니라 **산출물 검사**다 —
  `TestAdapterRetirementIsEnforced::test_no_module_defines_a_second_evidence_type`이 숙달 모듈이
  *정의한* 클래스를 전수로 훑어 계약이 읽는 속성 집합을 갖춘 것이 있는지 본다(이름을 바꿔
  되살려도 걸린다). 스캔 0건은 실패로 처리한다. 뮤테이션 5종 전건 RED로 변별력을 확인했다
  (어댑터 재도입·귀속 폴백·측정시각 분리·정오답 고정·스캔 대상 전멸).
- 이름 근거: 2026-09-16 Kiki 판정(A안)으로 계획서 쪽 per-answer 채점 산출의 이름이
  **`AssessmentEvidence`** 로 확정됐다. 저장소 정본 `schema/assessment.py::Assessment`(진단
  세션)와는 다른 객체다 — `schema/learning_loop_contract.py`의 `ASSESSMENT_EVIDENCE` 좌석 주석이
  정본이다.

## 7. 범위 밖 (손대지 않은 것)

- **스킬 축 소비 전환** — `EOS-63` 소유. 이 태스크는 계약 *형태*만 다뤘고, 어느 축을 읽어
  학습자에게 보여줄지는 건드리지 않았다.
- **신규 DB 테이블·마이그레이션 0건** — `ARCH-37` 80테이블 동결 준수.
- **추정기 파라미터 적합(EM)·DKT 신경망** — 여전히 후속.
