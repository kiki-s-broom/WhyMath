# Phase 2 Gate 2 2차 재판정 — 게이트 `G-p3-entry-gate2-pass`

> **판정 기준: main `841ee77d`** (2026-09-25 · `EOS-124: 추천 설명(정책 축)과 콘텐츠(선택 축) 정렬 — 기본 CAT cat_v2 (#1317)`)
> **선행 판정**: 9/19 `docs/reviews/eos_phase2_gate2_judgment_2026-09-19.md` (main `77ee1992` · **FAIL**) · 9/24 `docs/reviews/eos_phase2_gate2_rejudgment_2026-09-24.md` (main `5af2097b` · **FAIL**)
> **소유 태스크**: `EOS-130-phase2-gate2-rejudgment` — 선행 3건(`EOS-21`·`EOS-24`·`EOS-124`)이 전부 main에 착지한 뒤 claim했다(`EOS-124`는 #1317 머지를 확인하고 착수).
> **판정 세션**: 구현 세션과 분리(지시문 주의 4). 이 세션의 production code 변경은 0건이다. 3루프 일회성 프로브는 스크래치 영역에서만 돌렸고 커밋하지 않았다.
> **실행 환경**: 컨테이너 · PostgreSQL 16.13 + pgvector · `alembic upgrade head` EXIT=0(리비전 106 · head `8e4c2a7f1b93`) · `WHYMATH_RUN_INTEGRATION=1`

---

## §0. 결론 먼저

**FAIL.** 다만 9/19·9/24와는 FAIL의 **범위**가 다르다.

- **10조건**: 이번에도 전건 충족이다.
- **선행 조건 P-11~P-15**: 처음으로 전건이 main에 있다. P-13 = `EOS-119` · `578fa9d2` · #1300.
- **무개입 연속 3루프**: 오개념 오답 경로에서는 **처음으로 3루프 전건이 성립**한다.
  - 9/24의 두 원인이 해소됐다. `EOS-24`(추천이 상태 머신을 읽음)와 `EOS-124`(추천 설명과 문항의 정렬)다.
- **남은 미충족은 하나다**: 원인 미상 오답(general) 직후의 Loop 1 "보정".
  - main의 판정 기준으로는 성립하지 않는다.
  - 그 기준을 바꿀지는 Kiki 결정 게이트 `G-eos24-loop1-undiagnosed-wrong-criterion`의 몫이다.
  - 이 게이트는 **main에서는 pending**이다.
  - 미머지 브랜치에서는 이미 "(가) 좁힌 기준"으로 clear됐다(§3-5). 그 결정이 main에 없으므로 이 판정의 근거로 쓰지 않는다. 판정 시점 규칙("미머지 존재를 충족으로 단정 금지")에 따른 것이다.

---

## §1. 선행 판정과의 대조표 (acceptance ③)

| 항목 | 9/19 (`77ee1992`) | 9/24 (`5af2097b`) | 9/25 (`841ee77d`) | 변화 |
|---|---|---|---|---|
| 선행 P-11~P-15 main 착지 | ❌ P-13 미머지 | ❌ P-13 미머지 | ✅ 전건 (P-13 = `EOS-119` #1300) | **해소** |
| 조건 1 신규 학생 생성 | 충족 | 충족 | 충족 | 같음 |
| 조건 2 진단 완료 | 충족(단서: 67문항) | 충족(단서 해소 · `EOS-126`) | 충족 (20문항 상한 확정) | 같음 |
| 조건 3 LearnerState 자동 생성 | 충족(단서) | 충족 | 충족 (`provisioned_by=diagnosis_capture`) | 같음 |
| 조건 4 Concept 자동 선택 | 충족 | 충족 | 충족 | 같음 |
| 조건 5 Content → Problem | 충족 | 충족 | 충족 | 같음 |
| 조건 6 Attempt → Assessment | 충족 | 충족 | 충족 | 같음 |
| 조건 7 Misconception 기록 | 충족 | 충족 | 충족 | 같음 |
| 조건 8 Mastery 자동 갱신 | 충족 | 충족 | 충족 | 같음 |
| 조건 9 다음 학습 자동 추천 | 충족 (`practice_prerequisite · prerequisite_gap`) | 충족 | 충족 (`practice_current · misconception_remediation`) | **근거가 바뀜** — 오개념 오답 직후 추천이 오개념 교정을 근거로 댄다(`EOS-24`) |
| 조건 10 전체 과정 반복 | 충족 | 충족 | 충족 | 같음 |
| 판정 하네스 실행 결과 | `10 passed` | `12 passed` | `38 passed, 1 xfailed` | 범위 확대 — 상시 3루프 하네스·SCENARIO 스위트 추가 |
| 3루프 증거 원천 | 일회성 프로브 | 일회성 프로브 | **상시 하네스**(`PED-36` ⑫) + 프로브 + CI | 상시 장치 생김 |
| Loop 1 "보정" | 전 변이 ❌ | V1~V3 ❌ · V4만 한 단계 늦게 ✅ | 오개념(V2·V3) ✅ · **general(V1·V4g) ❌** | **절반 해소** |
| Loop 3 "다음 concept" | V1·V2 ❌ · V3 ✅ | V1~V3 ✅ · **V4 ❌** | **전 변이 ✅** | **해소** (`EOS-124`) |
| 3루프 전건 통과 변이 | 0 | 0 / 4 | **오개념 3 / 3 · general 0 / 2** | 크게 전진 |
| KPI 5종 | 통과 1 · 미측정 4 · EXIT=2 | 같음 | 통과 1 · 미측정 4 · EXIT=2 | 같은 숫자, 다른 내용 (§5) |
| KPI ① 미측정의 성격 | 구조적(writer 0건) | 구조적 | **데이터 의존**(분모 0) | **해소** (`EOS-131`) |
| KPI ⑤ 미측정의 성격 | 구조적 | 구조적 | 구조적(`user_state_snapshot` writer 0건) | 같음 |
| 판정 하네스 CI 도달 | "참조 0건"(이후 정정: 실제로는 돎) | "참조 0건" | 도달 확인 + 6종 동결(`EOS-21`) · 3루프·SCENARIO 미동결 | 해소 + 잔여 1건(`EOS-142`) |
| **최종** | **FAIL** | **FAIL** | **FAIL** | 미충족 1축으로 축소 |

**읽는 법**: 9/24 → 9/25는 반복 판정이 아니다. 9/24가 지목한 PASS 최소 경로 4개(§7-1)는 이렇게 됐다.

- 끝난 것 3개: `EOS-24` · `EOS-124` · `EOS-119`
- 반쯤 끝난 것 1개: 상시 하네스 + CI 배선. 하네스는 생겼고 CI에서도 돌지만, 도달 동결이 빠졌다.

그 결과 남은 미충족은 **판정 기준 한 줄**이다.

---

## §2. 10조건 — 전건 충족

결과는 판정 하네스 6종 `38 passed, 1 xfailed` · **EXIT=0**이다. 대상 파일은 week1·week3·p11·persona·3루프·SCENARIO다. xfail 1건은 §3의 general 3루프이고, 설계상 XFAIL로 드러나게 돼 있다. 재현 명령은 §8-1에 있다.

| # | 조건 | 판정 | 실행 증거 (이번 실행 출력 원문) |
|---|---|---|---|
| 1 | 신규 학생 생성 | 충족 | `WEEK1_GATE_STEP=1-user-created :: user_profile 0건→1건` |
| 2 | 진단 완료 | 충족 | `PERSONA_A-상한확정_STEP=②상한확정 :: … written=True · reason=captured_at_item_cap · 정밀도달성=False · SE=0.486 · 채점수=20` |
| 3 | LearnerState 자동 생성 | 충족 | `PERSONA_A-상한확정_STEP=③학습자상태 :: 진단 확정 분기에서 자동 생성(계획서 §18 조건 3) :: provisioned_by=diagnosis_capture` |
| 4 | Concept 자동 선택 | 충족 | `WEEK1_GATE_STEP=3-concept-selected :: … name=이차함수 · weak-concepts 콜드스타트 0건` |
| 5 | Content → Problem | 충족 | `WEEK1_GATE_STEP=4-problem-fetched :: GET /v1/problems/… 200 · 정답 비노출 확인` |
| 6 | Attempt → Assessment | 충족 | `P11_CHAIN_HANDOFF=H2-event-to-assessment :: evidence filled=3/3 · concept=1건 skill=1건 misconception=1건` |
| 7 | Misconception 기록 | 충족 | `WEEK3_GATE_STEP=2-misconception :: distribution-over-power conf=0.9 · 활성 가설로 영속` |
| 8 | Mastery 자동 갱신 | 충족 | `WEEK1_GATE_STEP=6-mastery-changed :: 스냅샷 0건→1건 · … mastery=0.15` |
| 9 | 다음 학습 자동 추천 | 충족 | `P11_CHAIN_HANDOFF=H4-learner-state-to-recommendation :: … action=practice_current · reason.type=misconception_remediation … mastery=0.15(state 일치)` |
| 10 | 전체 과정 반복 | 충족 | §3 — 상시 하네스 2종 + 프로브 5변이 전건이 HTTP 경로만으로 완주. 봉인 차단 0 · 시간선의 시도 = HTTP 제출 |

**SCENARIO-001~010**(P-13): 10/10 통과. 그중 정직한 공백으로 동결된 것이 있다. Gate 2 문면 밖이며 §6-2에 적었다.

- SCENARIO-003 ③: R4 미발화 · `EOS-127`
- SCENARIO-005 ④: 힌트 귀속·상태 머신 · `EOS-133`·`EOS-134`

---

## §3. 무개입 연속 3루프 — **미충족** (general 오답 Loop 1)

### 3-1. 증거 원천 세 가지

1. **상시 하네스** `tests/backend/api/test_e2e_three_consecutive_loops.py`(`PED-36` ⑫ · #1315)
   - 학습자는 추천을 그대로 따르며, 정오답만 고른다.
   - 오답 종류 2종(general · misconception)을 각각 관통한다.
   - 판정 규칙의 정본은 그 파일 docstring이다. Loop 1 "보정"은 세 절이 모두 서야 한다: ⓐ `action` ∈ {practice_prerequisite, practice_current} ⓑ `target_concept`이 틀린 개념 또는 그 선수 개념 ⓒ 준 문항이 그 target 소속.
   - 9/24 판정의 자(`action`이 보정 행위이고 `reason`이 `unmeasured`가 아님)보다 엄격하며, 이번 데이터에서 두 자의 판정은 같았다.
2. **일회성 프로브**(커밋하지 않음 · 설계는 §8-2): 상시 하네스가 다루지 않는 9/24 변이 V3·V4를 재기 위해 만들었다. 판정 함수는 상시 하네스의 것을 그대로 불렀다(재구현 0). **두 번 돌렸고 판정 줄이 같았다(결정론)**. 비교 방법의 변별력은 한 마디를 뒤집은 변조본과의 차이를 검출하는 것으로 확인했다.
3. **CI**: main `841ee77d`와 같은 커밋을 검증한 merge queue 실행이다(§4). 상시 하네스가 CI에서 같은 판정(general XFAIL)을 냈다.

### 3-2. 결과

| 변이 | 배치 | Loop 1 보정 (첫 오답 직후 추천) | Loop 2 | Loop 3 다음 concept | 이벤트 | 9/24 대비 |
|---|---|---|---|---|---|---|
| V1 (= 하네스 `general`) | 일반 오답(`7`) · 추천 따름 | ❌ 문항=선수 · `diagnose · unmeasured` · target=선수 | ✅ cur 0.15→0.84 (4회) | ✅ 문항·target=다음 · `diagnose · unmeasured` | 33건 | Loop 1 그대로 |
| V2 (= 하네스 `misconception`) | 오개념 오답(`x^2+4`) · 추천 따름 | ✅ 문항=현재 · `practice_current · misconception_remediation` · target=현재 | ✅ 0.15→0.84 (2회) | ✅ `advance_next · next_concept` · target=다음 | 24건 | **Loop 1 해소** |
| V3 | 오개념 오답 · 추천 무시하고 현재 개념 직접 숙달 | ✅ (무시한 추천 자체가 교정) | ✅ 0.15→0.84 (2회) | ✅ `advance_next · next_concept` | 24건 | **Loop 1 해소** |
| V4g | 일반 오답 → 추천된 선수 문항도 오답 → 추천 따름 | 엄격 ❌ (V1과 같음) · 9/24식(두 번째 오답 직후) ✅ `practice_prerequisite · prerequisite_gap` · target=선수 | ✅ 0.15→0.84 (4회) | ✅ `advance_next · next_concept` · target=다음 | 39건 | **Loop 3 해소** (`EOS-124`) |
| V4m | 오개념 오답 → (추천이 선수 문항이면 그것도 오답) | V4 전제 미성립: 첫 추천이 현재 개념이라 V2와 같은 경로 · ✅ | ✅ | ✅ | 24건 | 9/24 V4의 배치(오개념 → 선수)가 더는 생기지 않음 |

불변식은 전 변이에서 성립했다.

- 로그인 이후 시딩 봉인의 차단 0회
- 시작과 끝의 학습자가 같음
- `truncated=False`
- 시간선의 시도 `attempt_id` 집합이 HTTP 제출 집합과 같음

**운영자 DB 개입 0**도 전 변이에서 성립했다.

상시 하네스의 판정 줄 원문:

> `THREE_LOOP_VERDICT[general] :: LOOP1=FAIL LOOP2=PASS LOOP3=PASS · §18=FAIL`
> `THREE_LOOP_VERDICT[misconception] :: LOOP1=PASS LOOP2=PASS LOOP3=PASS · §18=PASS`

**주의 — 하네스의 exit 0은 §18 PASS가 아니다.** general의 §18 계약 테스트는 `xfail(strict=True)`로 표시돼 있어 스위트는 초록으로 끝난다. 판정은 exit code가 아니라 위 판정 줄과 XFAIL 표시로 읽는다. 하네스 docstring이 "이 파일이 초록인 것은 §18 충족이 아니다"라고 적은 그대로다.

### 3-3. 판정 — **미충족**

§18의 문면은 "3회 이상 연속 Learning Loop가 **가능**해야 한다"이다. 선행 두 판정은 이것을 **변이 전건**의 자로 읽었다.

- 9/24 §3-4: "V1~V3을 통과로 쳐도 V4의 Loop 3 실패가 남는다 → FAIL"
- 9/19 §3-3: "3루프는 학습자가 올바른 경로를 미리 알고 있어서 도는 것이면 안 된다"

이번 판정도 같은 자를 쓴다. 원인 미상 오답은 오개념 카탈로그에 걸리지 않는 모든 오답이며, 실학생 오답의 상당 부분일 것이다. 그 경로에서 루프가 닫히지 않으면 "루프가 닫혔다"고 말할 수 없다.

- 오개념 오답 경로: 3루프 전건 성립 (V2·V3·V4m)
- 원인 미상 오답 경로: Loop 1 "보정"에서 끊긴다 (V1·V4g)
  - 첫 오답 직후 추천은 선수 개념 문항을 내지만, 그 개념이 아직 측정되지 않아서 `diagnose · unmeasured`로 나간다.
  - main의 자에서 `diagnose`는 보정이 아니다. 하네스 ⓐ절의 문면은 "측정이 없다는 뜻이고, 방금 오답이라는 측정이 생겼다"이다.

### 3-4. 9/24와 달라진 점

- **해소 1 — 오개념 오답의 Loop 1**: 9/24에는 상태 머신이 `REMEDIATING`에 가도 추천이 그 상태를 읽지 않았다. 이제 `EOS-24`(#1316)로 추천이 상태 머신의 오개념 교정 결정 R3을 집행한다(`practice_current · misconception_remediation`). 후속 수정 `EOS-140`(#1322)이 옛 가설로 교정이 고정되는 경계를 막았다.
- **해소 2 — Loop 3 전진 불일치**: 9/24 V4는 `action=advance_next`인데 문항·target이 현재 개념이었다. 이제 `EOS-124`(#1317)로 정렬 재선택이 서서 문항·target이 모두 다음 개념이다. V1도 다음 개념으로 가는데, 이때 추천 설명은 `diagnose · unmeasured`다. 다음 개념이 미측정이라 그렇다. 하네스의 Loop 3 규칙은 행위 이름을 보지 않으므로 통과다.
- **그대로인 것**: 원인 미상 오답(상태 머신 R6) 직후 추천. 9/19·9/24·9/25 세 번 모두 `diagnose · unmeasured`였다. `EOS-24`가 R6를 **의도적으로** 배선하지 않았기 때문이다. 기계가 정할 수 없는 교수학 기준 문제라는 이유였다(`docs/reviews/eos24_recommendation_reads_learning_state_judgment_2026-09-25.md` §7-1).

### 3-5. 미머지 결정 대조 — 열을 나눠 적는다 (판정에 쓰지 않음)

판정 기준 게이트 `G-eos24-loop1-undiagnosed-wrong-criterion`의 상태는 이렇다.

- **main에서는 pending**이다.
- 브랜치 `claude/kind-allen-v50857`의 커밋 `5c8b557b`(**미머지**)에서는 Kiki 판정 "(가) 인정 — 좁힌 기준"으로 **cleared**다.
- 그 결정문은 원인 미상 오답 직후의 `diagnose`를 다음 **두 조건을 모두 만족할 때만** 보정으로 인정한다.
  - ⓐ 진단 문항의 대표 개념이 오답 개념의 prerequisite 선수 개념일 것
  - ⓑ 그 진단 문항을 틀리면 다음 추천이 `practice_prerequisite`로 하강할 것
- 기준 문장 재정의와 하네스 반영은 `EOS-139`가 소유한다. 이 태스크는 그 브랜치에서 in_progress다.

같은 데이터(main `841ee77d`에서 잰 V1·V4g)를 두 기준에 대 보면 이렇다.

| 판정 요소 | main 기준 (판정에 씀) | 브랜치 포함 기준 (참고 — 판정에 쓰지 않음) |
|---|---|---|
| V1 Loop 1 | ❌ `diagnose`는 보정 행위가 아니다 | ⓐ ✅ 첫 오답 직후 문항=선수 개념 · target=선수 |
| V4g (선수 진단 문항 오답) | — | ⓑ ✅ 다음 추천 `practice_prerequisite · prerequisite_gap` · 문항=선수 |
| general 3루프 | ❌ Loop 1 FAIL | Loop 1 ✅ · Loop 2 ✅ · Loop 3 ✅ |

즉 **main 코드는 이미 좁힌 기준의 두 조건을 만족하는 행동을 한다**. 서빙 코드 변경 없이 기준만 바뀌면 되는 상태다. 이것은 **예측**이지 판정이 아니다.

- `EOS-139`가 main에 착지해야 main의 자가 바뀐다.
- 착지하면 재판정(`EOS-141`)이 그 자로 **다시 재야** 한다.
- 결정문 끝의 "[범위] Gate 2 FAIL은 이 결정과 무관하게 유지된다(V4 Loop 3 = EOS-124 · P-13 미착지)"는 `81070ed5` 기준 서술이다. 두 사유 모두 `841ee77d`에서는 해소됐다(§1).

---

## §4. `EOS-21`의 처분과 CI 실측 (acceptance ④)

**처분 = 배선 확인 + 동결**(명시 제외 아님). `EOS-21`은 done이며, main 커밋은 `bd718175` · #1284다.

- **전제 정정**: 등재 전제였던 "week1·week3·persona 3종이 어느 CI 잡에서도 안 돈다"는 거짓으로 판명됐다(9/19 판정문 §5 정정 단락).
  - `backend — 마이그레이션·통합 (실 PG)` 잡은 파일명이 아니라 `integration` 마커로 수집한다.
  - 수집 명령은 `pytest -m integration --ignore=../../tests/backend/l3`이다.
  - 이 잡은 merge_group·push에서 항상, PR에서는 backend 변경이 있을 때 발화한다(`.github/workflows/ci.yml`의 `backend-migrations` `if:` 조건). 야간(schedule) 전용이 아니다.
- **남은 실결함 해소**: 그 배선을 지키는 가드가 0건이었다. 이제 `tests/infra/test_gate_harness_marker_reach_wiring.py`가 6종의 도달을 동결한다(`GATE_HARNESS_PATHS`).

**CI 실측 출력** — main `841ee77d`와 같은 커밋을 검증한 merge queue 실행이다.

- 실행 `36157270375` · 이벤트 `merge_group` · head `841ee77d` · 결론 success
- 잡 `108144831214`: `backend — 마이그레이션·통합 (실 PG)`

로그 원문:

> `##[group]Run pytest -m integration --ignore=../../tests/backend/l3`
> `collected 11723 items / 11310 deselected / 1 skipped / 413 selected`
> `api/test_e2e_three_consecutive_loops.py ....x............                [ 45%]`
> `scenarios/test_phase2_scenario_regression_suite.py ..........            [ 89%]`
> `XFAIL api/test_e2e_three_consecutive_loops.py::test_plan300_s18_three_consecutive_loops_hold[general] - 계획서 300 §18 무개입 연속 3루프 미충족(general) …`
> `= 400 passed, 13 skipped, 11310 deselected, 1 xfailed, 1 warning in 392.27s (0:06:32) =`

같은 로그에서 week1·week3·p11·persona 하네스도 각각 실행 줄이 확인된다. 즉 **Gate 2 판정 근거 전부가 merge queue와 backend 변경 PR에서 실행되고, general 3루프 미충족은 CI 화면에 XFAIL로 보인다.**

**잔여 1건**: `EOS-21`의 동결 목록 `GATE_HARNESS_PATHS`는 6종에서 멈춰 있다. 그래서 두 파일은 **지금 실행되지만 동결되지 않았다**.

- 3루프 상시 하네스 `test_e2e_three_consecutive_loops.py`
- SCENARIO 스위트 `test_phase2_scenario_regression_suite.py`

`grep` 결과로는 워크플로·`tests/infra` 어디에도 두 파일명 참조가 0건이다(이 검색 방법 기준). 두 파일이 `EOS-21`의 측정(9/23) 뒤인 9/24·9/25에 착지했기 때문이다. 판정 세션은 고치지 않고 `EOS-142`로 등재했다(§8-3).

---

## §5. KPI 5종 (P-14 · `EOS-15`) — acceptance ⑤

### 5-1. 공식 실측 (판정용)

실행 명령은 `python -m whymath_backend.ops.loop_kpi_gate --since-hours 24`이고 결과는 **EXIT=2**다.

> `합계: 통과 1 · 위반 0 · 미측정 4 / 전체 5`
> `판정: 측정 실패 있음 → exit 2 (미측정은 통과가 아니다)`

| KPI | 판정 | 분자/분모 | 미측정의 성격 | 9/24 대비 |
|---|---|---|---|---|
| ① Loop Completion Rate | unmeasured | 0 / 0 | **데이터 의존** — 관측창에 세션 0건. 구조적 선결(원천 대장 `PRODUCED`)은 충족 | **구조적 → 데이터 의존** (`EOS-131`) |
| ② State Integrity | unmeasured | 0 / 0 | 데이터 의존 — 스캔 대상 행 0 | 같음 |
| ③ Explainability | PASS | 0 / 94 | — (잔여상한 0.0280) | 같음 |
| ④ Manual Intervention | unmeasured | 0 / 0 | 데이터 의존 — 관측창 `problem_attempt` 0건 | 같음 |
| ⑤ Traceability | unmeasured | — | **구조적** — `user_state_snapshot` writer 0건 | 같음 (`EOS-132` todo) |

미측정을 0으로 적지 않았다. 관측창이 빈 이유는 판정 하네스가 끝날 때 자기 데이터를 지우기 때문이다(`content.teardown`·학습자 삭제). 9/19·9/24와 같은 조건이다.

### 5-2. 보조 측정 — ①이 정말 구조적 미측정을 벗었는가 (판정 불변)

"데이터 의존"이라는 주장을 검증하려고 한 번 더 쟀다. 프로브 여정 1회(오개념 오답 · 추천 따름)의 데이터를 지우지 않고 남긴 뒤 같은 CLI를 돌렸고, 결과는 **EXIT=1**이었다.

| KPI | 판정 | 분자/분모 | 읽는 법 |
|---|---|---|---|
| ① | FAIL | 1 / 1 | 점추정 1.00 · Wilson 하한 0.27 < 0.95. **측정은 된다**(`sessions_started=1`). FAIL은 표본 1의 통계 하한 때문이며 결함 신호가 아니다 |
| ② | FAIL | 0 / 10 | 점추정 0 · Wilson 상한 0.21 > 0.01. 역시 표본 크기 |
| ③ | PASS | 0 / 99 | — |
| ④ | PASS | 0 / 4 | — (관측 범위는 `privacy_audit` 표면뿐 — 게이트의 `coverage_note`) |
| ⑤ | unmeasured | — | 구조적 — 데이터가 있어도 벗지 못한다 |

결론은 이렇다.

- **①·②·④는 데이터가 쌓이면 측정되는 상태**다.
- **구조적 미측정은 ⑤ 하나**다.

KPI는 Gate 2 완료 판정의 문면(10조건 + 3루프) 밖이다. 다만 판정 규칙("KPI 5종 실측값을 함께 제시하라")에 따라 병기한다.

---

## §6. 미충족 항목 — 끊긴 지점 · 남은 작업량 · 11월 영향 (acceptance ⑥)

### 6-1. 무개입 연속 3루프 — 원인 미상 오답의 Loop 1 "보정" (**유일한 Gate 2 미충족**)

- **(가) 끊긴 지점**
  - 원인 미상 오답(R6 → `PRACTICING` · `PRACTICE_SAME_CONCEPT`) 직후 `GET /v1/me/next-problem`은 선수 개념 문항을 `diagnose · unmeasured`로 낸다.
  - main의 Loop 1 판정 기준(상시 하네스 ⓐ절)은 `diagnose`를 보정으로 인정하지 않는다.
  - 기준을 바꿀지는 Kiki 결정 게이트 `G-eos24-loop1-undiagnosed-wrong-criterion` 소관이다. 이 게이트는 main에서 pending이다.
- **(나) 남은 작업량** — 소(小)
  - Kiki 결정은 미머지 브랜치에서 이미 내려졌다(§3-5).
  - 남은 것 1: `EOS-139` ②. 기준 문장 재정의 + 상시 하네스 판정 규칙·`_FROZEN` 반영이며, 서빙 코드는 바꾸지 않는다. 대략 0.5~1 작업일이고, 타 세션이 진행 중이다.
  - 남은 것 2: 3차 재판정 `EOS-141`. 이 판정문의 §8 절차를 재사용하므로 대략 0.5 작업일이다.
  - §3-5의 대조로 보면 main 코드는 좁힌 기준의 두 조건을 이미 만족한다. 그래서 추가 구현 없이 PASS가 **예상**된다. 예상이지 판정은 아니다.
- **(다) 11월 일정 영향**
  - `G-p3-entry-gate2-pass`가 pending인 동안 P3-01~P3-14 14건이 selector 착수 후보에서 막힌다.
  - Phase 3 판정 상한은 Week 1이 11/1(`G-p3-g1-week1`), Week 2가 11/8, Week 3 + Release 통합이 11/15다.
  - `EOS-139`와 `EOS-141`이 10월 첫 주 안에 끝나고 Kiki가 게이트를 clear하면 11월 일정에 영향은 없다. 게이트 독촉일은 10/06이다.
  - 반대로 한 주 늦어질 때마다 Week 1(범위 동결 + Coverage 계측)의 착수 여유가 그만큼 줄어든다.
  - 그러므로 이 항목은 **작업량이 아니라 순서가 임계 경로**다.

### 6-2. Gate 2 문면 밖 — 관측만 (판정에 영향 없음)

| 관측 | 소유 태스크 | main 상태 | 비고 |
|---|---|---|---|
| KPI ⑤ 구조적 미측정 | `EOS-132` · `ARCH-51` | todo | G4(12/13) 전 해소 필요 — 9/19 §6-2 |
| 3루프 하네스·SCENARIO 스위트 CI 도달 미동결 | `EOS-142` (이 판정이 등재) | todo | 지금은 실행되지만 조용한 skip 전환에 무방비 |
| 상태 머신 R4 미발화 (SCENARIO-003 ③) | `EOS-127` | todo | 정직한 공백으로 동결 |
| 정답 회차가 오개념 감쇠 시계를 돌리지 않음 (persona C ⑥) | `EOS-123` | todo | 정직한 공백으로 동결 |
| 힌트 귀속·힌트 뒤 상태 머신 (SCENARIO-005 ④) | `EOS-133` · `EOS-134` | todo | 정직한 공백으로 동결 |
| 수능 모드 정책·선택 정렬 미적용 | `EOS-25` | todo | `EOS-124` 판정 ⑥에서 분리 |
| 상태 머신 R6 `next_action`과 추천 `diagnose`의 API 수준 불일치 | `EOS-26` (미머지 브랜치에서 등재) | main 미존재 | Kiki 결정문이 "남는 부채"로 적음 |

---

## §7. 최종 판정

10조건은 전건 충족했고, 선행 조건 P-11~P-15도 처음으로 전건이 main에 있다. 무개입 연속 3루프는 오개념 오답 경로에서 처음으로 성립했다. 그러나 원인 미상 오답 경로에서는 main의 판정 기준으로 Loop 1 "보정"이 성립하지 않는다. 그 기준을 바꾸는 Kiki 결정은 main에 아직 없다.

조건부 PASS는 없다. 게이트 `G-p3-entry-gate2-pass`는 **pending을 유지**한다. clear하지 않으며, clear는 Kiki 소유다(acceptance ⑦).

# FAIL

---

## §8. 부록

### 8-1. 재현 절차

환경은 9/19 판정문 §8-1과 같다. 대상 하네스에 3루프 상시 하네스와 SCENARIO 스위트를 더했다.

```bash
# PostgreSQL 16 + pgvector (컨테이너 — root 금지라 postgres 사용자로 initdb)
apt-get install -y postgresql-16-pgvector
su postgres -c "/usr/lib/postgresql/16/bin/initdb -D /var/lib/postgresql/wm16 -A trust -U whymath"
su postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D /var/lib/postgresql/wm16 -o '-p 5432 -k /tmp' -l /var/lib/postgresql/wm16/log.txt start"
psql -h 127.0.0.1 -p 5432 -U whymath -d postgres -c "CREATE DATABASE whymath;"

# 백엔드 설치·스키마
cd src/backend
python3.12 -m venv /root/wm_venv && /root/wm_venv/bin/python -m pip install -e ".[dev]" -e ../data-pipeline
export WHYMATH_DATABASE_URL="postgresql+asyncpg://whymath@127.0.0.1:5432/whymath"
export WHYMATH_RUN_INTEGRATION=1 WHYMATH_DB_DISABLE_POOL=1
/root/wm_venv/bin/python -m alembic upgrade head

# 10조건 + 3루프 + SCENARIO 하네스 (판정 줄을 보려면 -s -rA)
/root/wm_venv/bin/python -m pytest -c pyproject.toml -p no:randomly -o addopts="" -s -rA \
  ../../tests/backend/api/test_week1_gate_closed_loop.py \
  ../../tests/backend/api/test_week3_gate_remediation_loop.py \
  ../../tests/backend/api/test_p11_five_stage_loop_chain.py \
  ../../tests/backend/api/test_e2e_persona_journeys.py \
  ../../tests/backend/api/test_e2e_three_consecutive_loops.py \
  ../../tests/backend/scenarios/test_phase2_scenario_regression_suite.py
echo "PYTEST_EXIT=$?"

# KPI 5종
/root/wm_venv/bin/python -m whymath_backend.ops.loop_kpi_gate --since-hours 24
echo "KPI_EXIT=$?"
```

실측 결과는 하네스 `38 passed, 1 xfailed` · PYTEST_EXIT=0, KPI EXIT=2다.

### 8-2. 일회성 프로브의 지위와 설계

프로브는 **커밋하지 않았다**. 3루프 상시 하네스의 좌석은 `PED-36` ⑫이고 이미 main에 있다. 프로브는 그 하네스가 다루지 않는 9/24 변이(V3·V4)를 재려고 만든 일회성 측정기다. 재작성에 필요한 정보는 이렇다.

- **재사용**: `tests/backend/api/test_e2e_three_consecutive_loops.py`를 경로 로딩해 다음을 그대로 쓴다(재구현 0).
  - 판정 함수 `_remediation_fires`·`_advance_fires`·`_describe`
  - 봉인 `_Seal`
  - 난이도 대역 `_DIFFICULTY_BANDS`·후행 표 `_SUCCESSOR`
  - 오답 문자열 `_WRONG_ANSWERS`
  - 페르소나 조립기 `_P`
- **실행 방법**: 스크래치 폴더의 `conftest.py`가 `pytest_plugins = ["tests.backend.conftest"]`로 저장소 conftest를 적재한다. `--rootdir=src/backend -c pyproject.toml`로 실행한다.
- **변이**:
  - V1: general · 추천 따름
  - V2: misconception · 추천 따름
  - V3: misconception · 추천을 무시하고 틀린 개념의 미시도 문항을 직접 골라 정답
  - V4g/V4m: 첫 오답 직후 추천 문항이 선수 개념이면 그것도 오답으로 제출하고, 이후 추천을 따름
  - Loop 2 예산은 12회다. 선수 우회가 길어 하네스 예산 6을 넘을 수 있기 때문이다.
- **V4의 Loop 1은 두 자로 적었다**:
  - 엄격: 첫 오답 직후 추천 · 하네스 규칙
  - 9/24식: 두 번째 오답 직후 추천
- **결정론 확인**: 두 번 실행해 판정 줄이 같음을 확인했다. UUID를 제거한 뒤 diff했다. 그 비교가 변별력을 갖는지는 한 마디(✓→✗)를 뒤집은 변조본에서 차이가 검출되는 것으로 확인했다. 주입이 실제로 적용됐는지도 확인했다.
- **보조 측정(§5-2)**: `_P._begin`이 돌려주는 콘텐츠의 `teardown`을 no-op으로 바꿔 데이터를 남기고 KPI CLI를 돌렸다. 판정용 DB가 아니다.

### 8-3. 이 판정이 등재한 것

| 대상 | 처분 | 근거 |
|---|---|---|
| `EOS-141-phase2-gate2-third-rejudgment` | **신규** (P0) · `depends_on: EOS-139` | EOS-130 done 뒤 재판정 소유자가 비는 것을 막는다. 9/19 → 9/22 사이 3일간 소유자 부재였던 사고(사고 대장 계열 `gate-resolution-path-unlinked`)의 재생산 방지다. 진입 게이트를 `requires_gates`로 걸지 않는다(순환 방지) |
| `EOS-142-gate2-loop-harness-ci-reach-freeze` | **신규** (P1) | §4 잔여 — 3루프 상시 하네스·SCENARIO 스위트가 `EOS-21` 동결 목록에 없다 |

### 8-4. 이 판정이 하지 않은 것

- 게이트 `G-p3-entry-gate2-pass`를 clear하지 않았다. FAIL이고, decision 게이트의 결정권은 Kiki에게 있다. `--as kiki` 대행도 하지 않는다.
- production code와 테스트 가드를 고치지 않았다. `EOS-142`로 드러난 동결 누락도 등재만 했다.
- 미머지 결정(`5c8b557b`)을 판정 근거로 쓰지 않았다. §3-5에 열을 나눠 참고로만 적었다.
- 타 세션이 claim한 `EOS-139`의 대장은 수정하지 않았다.

---

*판정자: claude (판정 전용 세션 · `EOS-130`) · 판정 기준 main `841ee77d` · 2026-09-25*
