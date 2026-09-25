# EOS-24 정책 설계 판정 — 추천이 학습 상태 머신을 읽는가

> **판정 기준: main `bbd7c382`** (2026-09-25 · `재발 방지 태스크 3건 + 사고 대장 4건 — PR #1305 회고 (#1309)`) + PR #1295(미머지 · EOS-24 태스크 등재분만 병합)
> **소유 태스크**: `EOS-24-recommendation-reads-learning-state` (acceptance ② "정책 설계 판정 선행")
> **독립 비판**: pedagogy-designer 서브에이전트 1회(적대적 비판 · 결론 "수정 채택") — 반영 내역은 §4
> **이 문서의 위치**: 구현보다 **먼저** 쓰였다. §8(검증)만 구현 뒤에 채웠다.

---

## §0. 결론

**배선한다 — 단, 상태 머신 결정 중 R3(오개념 교정) 하나만, 안전장치 4개를 달아서.**

- 추천은 학습 상태 머신의 결정을 **다시 판정하지 않고 집행**한다. "다음에 무엇을 할까"의 결정자는 상태 머신(`l2/learning_state_policy.py::V1_RULES`) 하나로 둔다.
- 집행 대상은 `REMEDIATING` 중에서도 **트리거가 `POLICY_REMEDIATE_MISCONCEPTION`(R3)인 경우뿐**이다. R5(반복 실패)·R6/R2(PRACTICING)·R1(ADVANCING)은 이번에 읽지 않는다(§3).
- 집행하면 추천은 **방금 틀린 문항의 대표 개념 C**로 후보를 제한하고, `action=practice_current` · `reason.type=misconception_remediation` · `reason.basis=learning_state` · `target_concept=C`를 낸다.
- 이 판정은 **Gate 2 Loop 1을 절반만 푼다.** 오개념 오답 변이(V2·V3)는 풀리지만 일반 오답 변이(V1 — R6)는 그대로다. V1을 "보정"으로 볼지는 Kiki 판정 영역으로 남긴다(§7-1). Gate 2 FAIL의 다른 원인(`EOS-124`·P-13·상시 하네스)도 그대로다.

---

## §1. 실측 사실 (acceptance ①)

코드로 다시 확인했다(main `bbd7c382`).

| 축 | 위치 | 사실 |
|---|---|---|
| 상태 머신 결정 | `api/me.py::submit_attempt` → `advance_on_attempt` | 오개념 오답이면 R3 → `REMEDIATING` · `NextActionKind.REMEDIATE_MISCONCEPTION`. 원장 행에 `trigger=POLICY_REMEDIATE_MISCONCEPTION` · `attempt_id`가 남고 `concept_id`는 비어 있다(호출부가 넘기지 않음) |
| 추천 입력 | `api/me.py::recommend_next_problem` → `NextProblemPolicy(learner_state, learning_context)` | `LearnerState`(`l2/learner_state.py`)에 상태 머신 필드가 **없다**. 추천이 상태를 읽을 경로 자체가 없었다 |
| 추천 결정 | `l2/recommendation_policy.py::CatRecommendationPolicy` | IRT 정보량 최대로 문항을 고른 **뒤**, 고른 문항 개념의 숙달 구간에서 `action`을 파생한다. 오답으로 θ가 내려가면 선수 개념 문항을 고르고, 그 개념이 미측정이라 `diagnose · unmeasured`가 된다 |

같은 회차에 상태 머신은 "오개념부터 교정하라"고 하고 추천은 "선수 개념을 진단하라"고 한다. **학생에게 서로 다른 두 지시가 나간다.**

---

## §2. 선택지와 판정 (acceptance ②)

| 안 | 내용 | 판정 |
|---|---|---|
| (가) 배선 | 추천이 상태 머신 결정을 입력으로 받아 집행 | **채택** (R3 한정) |
| (나) 미배선 + 기준 재정의 | 오답 직후 선수 진단 출제를 교수학적으로 옳다고 보고 Gate 2 Loop 1 기준을 바꿈 | R3에는 기각 · R6에는 판단 보류(§7-1) |

**채택 근거 3가지**

1. **결정자가 둘이면 어느 쪽이 옳은지와 무관하게 학생은 모순을 받는다.** 제출 응답의 `learning_state.next_action`과 다음 추천의 `action`이 서로 다른 말을 한다. 한쪽을 결정자로 정해야 하고, 상태 머신은 이미 "학생이 지금 어느 교육적 국면에 있는가"의 제어 평면으로 설계됐다(`schema/learning_state.py` 모듈 docstring).
2. **우선순위 논쟁을 한 곳에 모은다.** 오개념과 선수 결손 중 무엇이 먼저인가는 실제로 논쟁 중이다 — 상태 머신은 R3 > R4이고, `l2/remediation_policy.py`(MISC-30)의 경로 표는 RT1(선수) > RT2(오개념)이다(그 표의 `select_route`는 소비처 0건). 추천이 상태 머신을 *집행*하면, 순서를 바꾸기로 결정했을 때 고칠 곳은 `V1_RULES` 한 곳이다. 추천이 따로 판정하면 두 곳을 고쳐야 하고, 한 곳만 고치면 모순이 되돌아온다.
3. **계약이 이미 그렇게 설계돼 있다.** `RecommendationPolicy`의 입력은 `learner_state`와 `learning_context` 둘뿐이다. 상태 머신의 국면은 학습자 상태이므로, 추천 정책이 DB를 따로 읽지 않고 **`LearnerState`로 받는 것**이 계약에 맞는 배선이다.

---

## §3. 무엇을 읽고 무엇을 읽지 않는가

| 상태 머신 결정 | 이번에 집행? | 이유 |
|---|---|---|
| R3 오개념 → REMEDIATING · REMEDIATE_MISCONCEPTION | **집행** | 이 태스크의 대상. 상태 머신이 "같은 개념에서 오개념부터"라고 명시했다 |
| R5 반복 실패 → REMEDIATING · OFFER_EXPLANATION_OR_HINT | 집행 안 함 | 설명·힌트는 **문항 선택 지시가 아니다**(L4 콘텐츠 행위). 게다가 3연속 오답 뒤에 현재 개념에 가두면 선수 하강(숙달 < 0.4 → `practice_prerequisite`)이 막힌다 — Persona B 여정(`test_e2e_persona_journeys.py`)이 바로 그 하강을 동결하고 있다 |
| R6 원인 미상 오답 → PRACTICING | 집행 안 함 · **Kiki 판정 영역** | §7-1 |
| R2 정답+낮은 확신 → PRACTICING | 집행 안 함 | 확신도를 보고하지 않은 정답은 전부 R2다(미측정 확신 = 낮음 · `_is_high_confidence`). 이것을 "같은 개념 연습"으로 집행하면 확신도를 보내지 않는 클라이언트의 학생은 **진급이 막힌다** |
| R1 정답+높은 확신 → ADVANCING | 집행 안 함 | 상태 머신은 *어느* 다음 개념인지 모른다(`target_concept_id=None`). 전진 방향의 정책·선택 축 정합은 `EOS-124`의 몫이다 |
| R4 선수 결손 → LEARNING · GO_TO_PREREQUISITE | 해당 없음 | 서빙에서 한 번도 발화하지 않는다(`EOS-127`) |

**과도기임을 명시한다.** 이 판정 이후에도 결정자는 완전히 하나가 아니다 — R3 경로는 상태 머신이, 나머지는 숙달 구간 파생이 정한다. 나머지 규칙을 집행으로 옮길지는 각 규칙의 입력이 믿을 만해질 때 다시 판정한다.

---

## §4. 안전장치 — 독립 비판을 반영한 수정

pedagogy-designer 비판의 요지는 "구조는 옳지만 **R3의 입력이 약하다**, 추천이 R3를 충실히 집행할수록 해가 커진다"였다. 코드로 확인한 약점 셋:

- 오개념 증거(`l2/learning_state_evidence.py`)는 **개념 범위가 아니라 학생 전체의 활성 가설**을 읽는다. 다른 개념에서 생긴 옛 가설로도 R3가 걸린다.
- R3에는 **신뢰 하한이 없다.** 활성 가설이 1건이라도 있으면 발화한다.
- 가설은 스캔된 오답 회차에만 감쇠해서, 정답을 많이 맞혀도 옛 가설이 오래 남는다.

그래서 집행에 조건 4개를 단다. 조건이 안 맞으면 **집행하지 않고 기존 추천으로 돌아가며, 그 사실을 응답(`learning_state_directive`)과 처치 기록 meta에 남긴다.**

| # | 안전장치 | 막는 반례 | 구현 |
|---|---|---|---|
| ① | **이번 회차에 새로 확인된 가설만** — 활성 가설 중 `turns_since_evidence = 0`인 것이 있어야 한다 | 옛 가설로 엉뚱한 개념에 고정 (비판 S1) | `misconception_hypothesis` 1행 조회 |
| ② | **신뢰 하한 초과** — 그 가설의 신뢰가 `MISCONCEPTION_REMEDIATION_FLOOR`(0.7)를 **넘어야** 한다 | 신뢰 0.15짜리 가설로 고정 (비판 S3) | 하한은 `l2/remediation_policy.py`의 정본을 재사용(새 숫자 0) |
| ③ | **고정은 1문항** — 교정 국면(`REMEDIATING`)에서 제출한 응답이 다시 R3면 고정을 **풀고** 숙달 구간 파생으로 넘긴다 | 고정이 연속 실패를 만듦 (비판 S2) | 원장 최신 2행: 결정 행과 같은 `attempt_id`의 `ATTEMPT_SUBMITTED` 행의 `from_state` |
| ④ | **작동 비율 기록** — 집행·해제·폴백 사유를 5값으로 남긴다 | "붙였는데 안 돈다"를 모름 | `learning_state_directive` 응답 필드 + meta 키 |

②의 하한을 `remediation_policy`에서 가져오지만 그 표의 `select_route`(경로 판정)는 **쓰지 않는다.** 쓰면 RT1(숙달 < 0.4 → 선수)이 먼저 걸리는데, 오답 1회 뒤의 숙달 0.15는 신뢰도 0.17짜리라 선수 결손의 증거로 약하다(비판 §2). 그 표와 상태 머신의 순서 충돌은 §7-2의 후속으로 넘긴다.

①~③은 **R3 입력을 고치는 것이 아니다.** 추천이 R3 결정 중 *근거를 지금 확인할 수 있는 것만* 집행하는 방어선이다. 근본 수정(R3의 입력을 이번 회차·신뢰 하한으로 좁히기)은 상태 머신 입력 축이라 `EOS-127`(R4 입력)·`EOS-123`(감쇠 비대칭)과 같은 부류의 별건이다(§7-2).

---

## §5. 선택 축 — 개념 C로 **제한**하고 성공률 밴드로 고른다

- **제한인가 가중인가 → 제한.** 가중치만 올리면 `reason`은 "오개념 교정"인데 문항은 다른 개념인 경우가 남는다 — `EOS-124`와 같은 부류의 결함을 새로 만든다. 제한하면 이 경로 안에서는 설명과 문항이 구조적으로 어긋날 수 없다.
- **C의 정의**: 결정 행의 `attempt_id` → 그 시도의 문항 → 대표 개념(`get_primary_concept_id` · PRIMARY 우선·TESTED 폴백). 후보는 **PRIMARY가 C인 문항**으로 제한한다(근거의 `concept_id`와 문항의 대표 개념이 같게).
- **노출 게이트는 그대로다.** 제한은 `build_candidate_pool_stmt`(저작권·검수·난이도 라벨 게이트 + 미시도 + θ 근방 정렬)에 `WHERE`를 **덧붙이는** 방식이라, 기존 게이트를 다시 쓰지 않는다.
- **성공률 밴드**: 교정 직후 문항의 목적은 측정이 아니라 *교정이 됐는지 확인*이다. 그래서 이 경로는 요청의 `purpose`와 무관하게 학습 밴드 가중(`learning_band_weight`, 정답 확률 70~85%)을 쓴다. 밴드는 아직 실측 보정 전이므로 응답의 `band_calibrated=False`가 그 사실을 말한다.
- **C에 미시도 후보가 없으면** 기존 추천으로 돌아가고 `learning_state_directive=no_candidate_in_concept`을 남긴다.
- `policy_version`: 집행된 추천만 `cat_v1_state_remediation`으로 기록한다(후보 생성 규칙이 다르므로 REC-11 소급 평가가 섞지 않게). 집행되지 않은 추천은 전환 전과 **같은 입력에서 같은 결과**이므로 `cat_v1`을 유지한다.

---

## §6. 인접 태스크 경계 (acceptance ④)

| 태스크 | 축 | 이 판정과의 관계 |
|---|---|---|
| `EOS-127` | 상태 머신 **입력**(R4의 `prerequisite_gap_concept_ids` 미배선) | 겹치지 않는다. R4가 배선되면 R4 결정을 추천이 집행할지는 그때 판정한다(이번에 읽는 트리거는 R3뿐) |
| `EOS-124` | 추천 **내부**(숙달 구간 경로의 `action`/`target_concept` ↔ 선택 문항 불일치) · 2026-09-25 타 세션 claim | 겹치지 않는다. 이 판정은 **R3 집행 경로 안에서만** 선택을 정책에 맞췄다(§5). 숙달 구간 경로에 어느 축을 정본으로 할지(`EOS-124` ③)는 정하지 않았다. 다만 그 경로가 "선택을 정책에 맞춘다"를 고르면 이 경로와 같은 모양이 된다 |
| `EOS-123` | 정답 회차가 오개념 감쇠를 안 돌림 | §4 약점 셋째의 원인. 해소되면 안전장치 ①의 필요가 줄지만 해가 되지는 않는다 |
| MISC-30 `select_route` | 경로 표 RT1 > RT2 (소비처 0) | 상태 머신 R3 > R4와 순서가 반대다. 이 판정은 그 표의 **하한 상수만** 재사용하고 경로 판정은 쓰지 않는다. 충돌 해소는 §7-2 |

---

## §7. 이 판정이 하지 않은 것

### 7-1. Kiki 판정 영역 — 일반 오답 직후의 추천 (Gate 2 V1)

원인 미상 오답(R6)에서 상태 머신은 "같은 개념 연습"(PRACTICING)이라고 하고, 추천은 θ가 내려가 선수 개념 문항을 **진단 목적**으로 낸다(`diagnose`). 둘 다 교수학적으로 말이 된다 — 원인을 모르는 오답이면 선수 개념부터 확인하는 것도 합리적이고, Gate 2 V4가 보여 주듯 그 진단 결과가 결손이면 다음 추천이 `practice_prerequisite`로 내려간다.

그래서 **이 태스크는 R6를 배선하지 않았다.** Gate 2 Loop 1 "보정" 마디가 "오답 직후 선수 개념 진단 출제"를 보정으로 인정할지는 재판정문 §3-4가 이미 Kiki 판단 영역으로 적어 둔 문제이며, acceptance ② (나)의 "Kiki 결정으로 재정의"에 해당한다. 결정 게이트 `G-eos24-loop1-undiagnosed-wrong-criterion`(kind=decision · assignee=kiki)으로 등재했고, 결정 뒤 집행은 `EOS-139-undiagnosed-wrong-recommendation-criterion`이 소유한다(그 게이트를 `requires_gates`로 건다).

### 7-2. 후속 태스크로 등재한 것

- **R3 입력 품질** → `EOS-138-r3-misconception-input-scope` — R3가 학생 전체·하한 없는 가설을 읽는다. 이 판정의 안전장치 ①②를 상태 머신 입력(`build_attempt_evidence`)으로 올리면 제출 응답의 `next_action`도 같은 기준을 따르게 된다. 그러면 추천 쪽 방어선은 중복이 되지만 해가 되지 않는다. MISC-30 `select_route`의 순서 충돌도 이 태스크가 함께 판정한다.

### 7-3. 범위 밖

- 수능 모드(`api/_next_problem_policy.py::SuneungRecommendationPolicy`)는 상태 머신을 읽지 않는다. 같은 결함이 있으나 L6 게이팅과의 합성이 필요해 별도 판정이 필요하다(`EOS-124` ⑥과 같은 처분).
- 교정 확인 문항을 "그 오개념을 변별하는 문항"(오답 문항의 변형·형제)으로 좁히는 것은 하지 않았다. 지금은 같은 개념의 문항이면 된다.

---

## §8. 검증

> 실행 환경: 컨테이너 · PostgreSQL 16 + pgvector · `alembic upgrade head` EXIT=0 · Python 3.12 venv(`pip install -e ".[dev]"`)

| 검증 | 결과 |
|---|---|
| 변경 전 기준선 — 통합 6파일(Week 1·3 · 페르소나 여정 · P11 · 학습 상태 · 시나리오 회귀) | 39 passed · EXIT=0 |
| 신규 통합 `test_eos24_recommendation_follows_learning_state.py`(실 PG · HTTP) | 3 passed · EXIT=0 |
| 통합 회귀 8파일(위 6 + Week 2 + 신규) | 44 passed · EXIT=0 |
| CI `backend` 잡 전 스텝 재현(ruff · black · `mypy --strict` · `lint-imports` · pytest+커버리지 · 계층 커버리지 · 게이트 CLI 16종) | pytest 외 전 스텝 EXIT=0 · pytest **2 failed / 14,352 passed** → 아래 |
| 그 2건 | `test_me_review_status_gate.py`가 `LearnerState` 조회 수(5)를 **세 번째 사본**으로 들고 있었다(`test_me.py`·`test_study.py` 외). 6으로 갱신 후 그 파일 2 passed. 순서 기반 대역이 조회 증가를 설계대로 잡은 것이다 |
| 커버리지 | 총 90.57%(≥70) · 계층 바닥선 5종 PASS(l2 96.5%) |
| CI `infra-contracts` 잡 재현 | 처음 2 failed + 21 errors(신규 모듈 미귀속 · 데이터 접근 기준선 밖) → 인벤토리 `WM-E-213` 귀속 + 기준선 ②경로 편입 후 해당 2파일 50 passed. 런북 쓰기 가드·숙달 쓰기 경로 스캔 EXIT=0 |
| `harness-integrity` · `policy-guard` · `declared-unwired-audit` | `backlog.py validate`·`audit-deps`·`rules lint`·`rules render --check`·`jit check`·ADR 번호·원본 바이너리·cp949 가드·미배선 감사 전부 EXIT=0 |

**변별력(깨뜨려 본 것)**

- hermetic 가드 뮤테이션 **18종 전건 RED**(대조군 GREEN). 순수 Python 하네스로 주입 실재(`mutated != original`)와 원복 sha256 동일을 매 회차 단언했다. 대상: 국면 검사 · 트리거 검사 · 재실패 해제 · 하한 경계(`<=`→`<`) · 이번 회차 조건 · 응답 조회 학습자 범위 · 개념 제한 · PRIMARY 제한 · 교정 밴드 · 정책 버전 · 집행 근거 출처 · 지시 결과 전파 · 제한 후보 사용 · 짝 행 attempt 일치 · 짝 행 트리거 · basis 짝 검증기 · 행위 매핑 · 원장 조회.
- 통합 테스트 뮤테이션 2종(개념 제한 제거 · 상태 경로 통째 미배선) → 각각 **2 failed / 1 passed**(대조군만 통과). 시딩 배치(C 2.5~3.5 · 더 쉬운 P 1.0~1.5)가 "C 안에 머문 것 = 상태 경로 때문"을 가른다.
- 신뢰 하한 경계는 상수를 import하지 않고 리터럴 0.70 · 0.71로 밟았다(MISC-30 자기참조 교훈).

**정직한 공백**

- 실 PG 통합 테스트는 CI에서 돌지 않는다(`integration` 마크 · 주간 게이트 하네스들과 같은 상태 · 배선은 `EOS-21` 소관). CI에서 도는 대응분은 hermetic `tests/backend/l2/test_learning_state_recommendation.py`다.
- Gate 2 3루프 프로브 자체는 다시 돌리지 않았다(재판정 세션의 몫 · 상시 하네스는 `PED-36` ⑫). V2에 해당하는 경로는 신규 통합 테스트 첫 건이 재현한다.
