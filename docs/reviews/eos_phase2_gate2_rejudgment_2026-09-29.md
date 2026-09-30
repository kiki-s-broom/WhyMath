# Phase 2 Gate 2 3차 재판정 + Phase 2 인수 점검(P3-00b 흡수) — 게이트 `G-p3-entry-gate2-pass`

> **판정 기준: main `a82f9449`** (2026-09-29 09:48Z · `HARN-172: ci_job_coverage scope의 조용한 0건·stdin 무시 차단 … (#1384)`) — 판정 직전 `git fetch origin main`으로 main이 그대로임을 다시 확인했다.
> **판정 수준 = API 계약 · 앱 도달 0.** 10조건·3루프는 HTTP 계약(`POST /v1/me/attempts` → `GET /v1/me/next-problem`)에서 잰 것이다. 실제 모바일 앱은 오답을 서버에 보내지 않으므로, Loop 1의 "오답 → 보정" 구간은 앱 학생에게 한 번도 일어나지 않는다(§4). 이 수준을 Gate 2 충족으로 볼지는 **Kiki 판단 사항**이다(acceptance ⑫ · `EOS-146`).
> **선행 판정**: 9/19 `eos_phase2_gate2_judgment_2026-09-19.md`(main `77ee1992` · FAIL) · 9/24 `eos_phase2_gate2_rejudgment_2026-09-24.md`(main `5af2097b` · FAIL) · 9/25 `eos_phase2_gate2_rejudgment_2026-09-25.md`(main `841ee77d` · FAIL)
> **소유 태스크**: `EOS-141-phase2-gate2-third-rejudgment` — 선행 `EOS-139`·`EOS-26`이 둘 다 main에서 done이다. claim 커밋 `156c47a2`는 대장 2파일만 바꾼다(`git diff a82f9449 156c47a2 -- src tests` 무변경 확인). 이 판정문은 P3-00b(Phase 2 인수 점검)의 산출을 겸한다.
> **판정 세션**: 구현 세션과 분리. production code·테스트 변경 0건. 일회성 프로브는 스크래치 영역에서만 돌렸고 커밋하지 않았다(§9-2).
> **실행 환경**: 컨테이너 · PostgreSQL 16 + pgvector 0.6.0 · 스크래치 DB `whymath_eos141` · `alembic upgrade head` EXIT=0(리비전 109 · head `9d3e7b1c5a20`) · Python 3.12.3 · `WHYMATH_RUN_INTEGRATION=1` `WHYMATH_DB_DISABLE_POOL=1` · 127.0.0.1 접속은 CI와 같은 trust 인증(컨테이너 pg_hba에 한 줄 추가 후 원복)

---

## §0. 결론 먼저

**PASS — 단, 판정 수준은 API 계약이다.** 이 수준은 9/19·9/24·9/25 세 판정이 쓴 것과 같은 자다.

- **10조건**: 이번에도 전건 충족이다.
- **무개입 연속 3루프**: 처음으로 **두 오답 종류 모두** 성립한다.
  - 상시 하네스 2종(general · misconception)이 통과했다.
  - 일회성 프로브 7변이도 전건 통과했다. V1~V4에 앱 요청 형태 2종을 더한 것이다.
  - 9/25의 유일한 미충족이던 원인 미상 오답(general)의 Loop 1 "보정"은 `EOS-26`(#1338)이 착지하며 섰다. Kiki 기준 ⓐ·ⓑ가 방해 개념 배치와 요청 형태 2종 모두에서 성립한다.
- **SCENARIO-001~010**: 로컬 10/10 통과. 판정 기준 커밋의 CI 실행 2회(merge_group · push)에서도 **실제로 실행돼** 10 passed다(§6).
- **KPI 5종**(Gate 2 문면 밖 · 병기): 공식 실측은 **EXIT=1**이다. 통과 1 · 위반 1 · 미측정 3이다.
  - 위반 1건은 ⑤ Traceability다. 원인은 판정 하네스가 삭제권 경로(`DELETE /v1/me`)로 학습자를 지운 잔여물이다(§5).
  - 이것은 KPI ⑤가 "삭제권 이행"과 "진짜 끊김"을 구별하지 못하는 설계 공백을 드러낸다. 등재를 제안한다(§7 P-2).
- **Kiki 판단 사항 1건**(⑫): 이 PASS는 HTTP 계약 수준이다.
  - 실제 앱 학생에게는 Loop 1의 오답 → 보정이 **0회** 일어난다. 앱은 오답을 서버에 보내지 않는다.
  - "앱 도달"을 Gate 2의 자로 삼으면 판정은 **FAIL**로 바뀐다. 이때 소유 태스크는 `EOS-146`이다.
  - 게이트 `G-p3-entry-gate2-pass`는 이 판정이 닫지 않는다(acceptance ⑦).

---

## §1. 선행 판정과의 대조표 (acceptance ④ · ⑫)

**판정 수준(전체)**은 네 회차 모두 같다. HTTP 계약 수준에서 재고, 학습자는 `POST /v1/me/attempts`로 답을 낸다.

| 회차 | 판정 수준 명기 |
|---|---|
| 9/19 | API 계약 — 앱 도달은 검토하지 않았다(명기 없음) |
| 9/24 | 같음 |
| 9/25 | 같음. 사후 보정(9/26)에서 "해소 수준은 API 계약"이 덧붙었다 |
| **9/29** | **API 계약 · 앱 도달 0 — 상단에 명기** |

| 항목 | 판정 수준 | 9/19 (`77ee1992`) | 9/24 (`5af2097b`) | 9/25 (`841ee77d`) | **9/29 (`a82f9449`)** | 변화 |
|---|---|---|---|---|---|---|
| 선행 P-11~P-15 main 착지 | 저장소 | ❌ P-13 미머지 | ❌ | ✅ | ✅ | 같음 |
| 조건 1~10 | API 계약 | 충족(단서 2·3) | 충족 | 충족 | **충족** | 같음 |
| 조건 9 근거(오개념 오답 직후) | API 계약 | `practice_prerequisite · prerequisite_gap` | 같음 | `practice_current · misconception_remediation` | 같음 | 같음 |
| 판정 하네스 6종 결과 | API 계약 | `10 passed`(4종) | `12 passed`(4종) | `38 passed, 1 xfailed` | **`58 passed` · xfail 0** | general XFAIL 해소 |
| Loop 1 "보정" | API 계약 | 전 변이 ❌ | V1~V3 ❌ | 오개념 ✅ · **general ❌** | **오개념 ✅ · general ✅** | **해소**(`EOS-26`) |
| Loop 3 "다음 concept" | API 계약 | V1·V2 ❌ | V4 ❌ | 전 변이 ✅ | 전 변이 ✅ | 같음 |
| 3루프 전건 통과 변이 | API 계약 | 0 / 3 | 0 / 4 | 오개념 3/3 · general 0/2 | **7 / 7 + 하네스 2/2** | **해소** |
| 진단 보정 프로브(ⓐ 선수지향 · ⓑ 폐루프) | API 계약 · 요청 형태 2종 | — | — | (9/25 이후 EOS-139가 신설) ⓐ FAIL · ⓑ PASS* | **ⓐ PASS · ⓑ PASS** | **해소**(`EOS-26`) |
| 앱 요청 형태(`prioritize_weak_concepts` 미전송) 3루프 | API 계약 | 미측정 | 미측정 | 미측정 | **V1a·V2a 둘 다 ✅** | 신규 측정 |
| 앱 이벤트 원천(오답 제출) | 앱 코드 대조 | 미검토 | 미검토 | 미검토 | **0 — 앱은 오답을 보내지 않는다** | 신규 명기(§4) |
| SCENARIO-001~010 | API 계약 | ❌ 미머지 | ❌ | 10/10 (로컬 · CI) | **10/10 (로컬 · CI 2회)** | 같음 |
| 3루프·SCENARIO CI 도달 동결 | CI | — | — | 실행되나 동결 없음 | **동결**(`EOS-142` done) | **해소** |
| KPI 공식 실측 exit | DB 집계 | 2 | 2 | 2 | **1** | ⑤가 측정 가능해짐 |
| KPI ⑤ 성격 | DB 집계 | 구조적 미측정 | 구조적 | 구조적(`user_state_snapshot` writer 0) | **측정됨 · FAIL(삭제권 잔여)** | `EOS-132`가 구조적 미측정을 해소. 새 공백이 드러남 |
| **최종** | — | **FAIL** | **FAIL** | **FAIL** | **PASS (API 계약 수준)** | §8 |

\* 9/25 이후 EOS-139(#1327)가 방해 개념 프로브를 신설해 main `81070ed5`를 쟀다. EOS-26 판정문 §1-2가 그 ⓑ PASS도 하네스 전용 요청 형태에 기댄 값이었음을 보였다. 지금 프로브는 방해 개념 배치에서 요청 형태 2종을 모두 잰다.

---

## §2. 10조건 — 전건 충족

실행: 판정 하네스 6종(week1 · week3 · p11 · persona · 3루프 · SCENARIO) → **`58 passed, 1 warning in 93.45s` · PYTEST_EXIT=0** · xfail 0 · skip 0. 재현 명령은 §9-1.

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
| 10 | 전체 과정 반복 | 충족 | §3 — 하네스 2종과 프로브 7변이가 전건 HTTP 경로만으로 완주했다. 봉인 차단 0회. 시간선의 시도는 HTTP 제출과 같다 |

하네스 출력에 남은 **정직한 공백 표기**는 이번에도 보인다. 모두 Gate 2 문면 밖이며, 9/25 대비 바뀐 것만 적는다.

- SCENARIO-003 ③: `EOS-127 정직한 공백`(R4 미발화). 9/25와 같다.
- SCENARIO-005 ④: 힌트 귀속(`EOS-133`)과 힌트 뒤 상태 머신(`EOS-134`)이 **해소**로 바뀌었다. 힌트 소비 축만 `정직한 공백 — EOS-29`로 남았다.

---

## §3. 무개입 연속 3루프 — **충족 (API 계약 수준)**

### 3-1. 증거 원천

1. **상시 하네스** `tests/backend/api/test_e2e_three_consecutive_loops.py`(`PED-36` ⑫). 판정 규칙의 정본은 그 파일 docstring이다.
   - Loop 1 "보정"은 두 경로 중 하나로 선다.
     - **직접 보정**: `practice_*` 행위이고, 대상과 문항이 모두 틀린 개념 또는 그 선수다.
     - **진단 보정**: EOS-139 기준이다. R6에서만 열린다. `diagnose`이고, 대상과 문항이 모두 선수다. 여기에 프로브의 ⓕ 폐루프와 ⓖ 선수지향이 둘 다 서야 한다.
   - `_FROZEN`은 두 종류 모두 전 마디 True다. `_GAP_OWNERS`는 비어 있다. `_s18_open_variants() == set()`이다.
2. **일회성 프로브**(커밋하지 않음 · 설계 §9-2). 하네스의 판정 함수·봉인·배치·오답 문자열을 경로 로딩해 그대로 썼다(재구현 0). 9/25 변이 V1~V4에 앱 요청 형태 V1a·V2a를 더했다.
3. **CI**: 판정 기준 커밋 `a82f9449`의 merge_group 실행과 push 실행이다(§6).

### 3-2. 상시 하네스 결과

> 「실측」 `DIAGNOSIS_PROBE :: 폐루프=PASS 선수지향=PASS`
> 「실측」 `THREE_LOOP_VERDICT[general] :: LOOP1=PASS LOOP2=PASS LOOP3=PASS · §18=PASS`
> 「실측」 `THREE_LOOP_VERDICT[misconception] :: LOOP1=PASS LOOP2=PASS LOOP3=PASS · §18=PASS`

general의 Loop 1 보정 마디 원문:

> `LOOP1 ✓ 보정 | 문항소속=pre · action=diagnose · reason=unmeasured · target=pre · 오답 규칙=R6-wrong-undiagnosed · 진단 보정 경로: DIAGNOSIS_PROBE :: 폐루프=PASS 선수지향=PASS`

9/25와 달리 §18 계약 테스트 `test_plan300_s18_three_consecutive_loops_hold`는 두 종류 모두 **표식 없이 PASSED**다(xfail 아님). 이번에는 스위트 exit 0이 §18 PASS와 같은 뜻이다. 판정은 여전히 판정 줄로 읽었다.

### 3-3. 프로브 결과 (Loop 2 예산 12 · 2회 실행 결정론 확인)

| 변이 | 배치 | Loop 1 보정 (첫 오답 직후 추천) | Loop 2 | Loop 3 | 이벤트 | 9/25 대비 |
|---|---|---|---|---|---|---|
| V1 | 일반 오답 · 추천 따름 | ✅ `diagnose · unmeasured` · 문항·target=선수 · `directive=prerequisite_probe` | ✅ cur 0.15→0.84 (4회) | ✅ 문항·target=다음 | 40건 | **Loop 1 해소** |
| V2 | 오개념 오답 · 추천 따름 | ✅ `practice_current · misconception_remediation` · `directive=applied` | ✅ 0.15→0.84 (2회) | ✅ `advance_next · next_concept` | 29건 | 같음 |
| V3 | 오개념 오답 · 추천 무시, 현재 개념 직접 숙달 | ✅ (무시한 추천 자체가 교정) | ✅ 0.15→0.84 (2회) | ✅ `advance_next` | 27건 | 같음 |
| V4g | 일반 오답 → 추천된 선수 문항도 오답 → 추천 따름 | 엄격 ✅(V1과 같음) · 9/24식 ✅ `practice_prerequisite · prerequisite_gap` · target=선수 · `directive=same_concept_repeat` | ✅ 0.15→0.84 (4회) | ✅ `advance_next` | 47건 | **Loop 1 해소** |
| V4m | 오개념 오답 → (추천이 선수면 그것도 오답) | V4 전제 미성립 — 첫 추천이 현재 개념 교정이라 V2와 같은 경로 · ✅ | ✅ | ✅ | 29건 | 같음 |
| V1a | V1 + **앱 요청 형태**(파라미터 미전송) | ✅ V1과 같음 | ✅ | ✅ | 40건 | 신규 |
| V2a | V2 + 앱 요청 형태 | ✅ V2와 같음 | ✅ | ✅ | 29건 | 신규 |

불변식은 전 변이에서 성립했다.

- 로그인 이후 시딩 봉인의 차단 0회
- 시작과 끝의 학습자가 같음
- `truncated=False`
- 시간선의 시도 `attempt_id` 집합이 HTTP 제출 집합과 같음
- `concept_mastery_history`의 이 학습자 행이 전부 HTTP 제출 `attempt_id`에 귀속됨

**운영자 DB 개입 0**도 전 변이에서 성립했다.

**결정론·변별력**: 2·3회차 출력을 UUID 제거 후 비교했고 차이는 0이었다. 1회차(V1a·V2a 추가 전)와 2회차의 공통 구간도 차이가 0이다(끝의 빈 줄 1개 제외). 비교가 변별력을 갖는지는 확인했다. 3회차 출력의 `✓` 한 개를 `✗`로 바꾼 변조본을 만들고, 치환 적용을 단언한 뒤 비교하자 차이가 검출됐다.

### 3-4. 9/25 §3-5 대조 — EOS-139 기준 두 조건을 main 데이터에 대면

| 판정 요소 | 9/25 §3-5 "브랜치 포함 기준" 예측 (`841ee77d` 데이터) | 9/29 main 실측 (`a82f9449`) | 일치 여부 |
|---|---|---|---|
| ⓐ R6 직후 진단 문항이 선수 개념 | ✅로 예측 — "main 코드는 이미 좁힌 기준의 두 조건을 만족" | ✅ V1·V1a·V4g 모두 문항·target=선수(`prerequisite_probe`). 방해 개념 배치 × 요청 형태 2종에서도 ✅(하네스 ⓖ) | **결과는 일치 · 근거는 불일치** |
| ⓑ 그 진단을 틀리면 `practice_prerequisite` 하강 | ✅로 예측 | ✅ V4g `practice_prerequisite · prerequisite_gap` · 문항·target=선수(`same_concept_repeat`). 방해 개념 × 요청 형태 2종 ✅(하네스 ⓕ) | **결과는 일치 · 근거는 불일치** |
| general 3루프 | Loop 1~3 ✅ 예측 | ✅ | 일치 |

**근거가 불일치하는 이유**: 9/25 §3-5는 "서빙 코드 변경 없이 기준만 바뀌면 된다"고 예측했다. 이 예측은 **틀렸다**.

- EOS-139(#1327)의 방해 개념 프로브에 따르면, `841ee77d`의 ⓐ는 픽스처가 선수 개념을 유일하게 더 쉬운 개념으로 심었기 때문에만 섰다. 추천기는 선수 그래프를 보지 않고 θ 근방 최근접을 골랐다(`DIAGNOSIS_PROBE 선수지향=FAIL`).
- EOS-26 판정문 §1-2에 따르면 ⓑ도 하네스 전용 요청 형태(약점 가중 1.85배)에 기대고 있었다.
- 그래서 실제 해소 경로는 서빙 변경이었다. `EOS-26`이 `l2/learning_state_recommendation.py::route_by_learning_state`에서 R6를 집행한다.
- 오늘 ⓐ·ⓑ가 서는 것은 그 변경의 결과다. 9/25가 본 행동이 그대로 이어진 것이 아니다.

9/25 판정문이 그 예측을 "예측이지 판정이 아니다"로 적어 둔 것이 맞았다.

### 3-5. 판정 — **충족 (API 계약 수준)**

9/19~9/25의 자는 "변이 전건"이다. 이번에는 하네스 2종, 프로브 7변이, 진단 보정 프로브의 요청 형태 2종이 **전건 성립**한다. 운영자 DB 개입도 전건 0이다. 이 자로는 §18 무개입 연속 3루프가 충족이다.

**재지 않은 경로**(판정 밖 — 정직 표기):
- 연속 셋째 오답(R5 → 기본 경로 인계 · `EOS-148`)
- 탐침을 맞힌 뒤 오답 개념 C로 복귀하지 않는 분기(`EOS-144`)
- 활성 오개념 가설이 있는 학생의 원인 미상 오답(R3로 분류 · `EOS-138` 범위)

변이 7종은 이 경로를 밟지 않는다.

---

## §4. 판정 수준 — API 계약 · 앱 도달 0 (acceptance ⑫ · Kiki 판단 사항)

### 4-1. 실측 (main `a82f9449` 코드 대조 · 이 검색 방법 기준)

- **앱은 `POST /v1/me/attempts`를 부르지 않는다.**
  - `src/mobile/test/e2e_loop_flow_test.dart`의 422행과 478행이 `callCount('/v1/me/attempts') == 0`을 동결한다.
  - `src/mobile/lib/features/chat/data/coach_models.dart:411`에는 "`POST /v1/me/attempts`를 부르지 않는다(중복 적재 금지)"라고 적혀 있다.
- **앱의 시도 기록은 코치 정답 완료뿐이다.**
  - `api/coach.py::_complete_problem`은 `ProblemAttempt(is_correct=True)`를 적재한다.
  - `EOS-134`(done) 이후로는 `advance_on_graded_attempt(... is_correct=True)`로 상태 머신도 돌린다(`api/coach.py` 1410행).
  - **EOS-26 판정문 §1-6의 "코치 완료는 상태 머신을 부르지 않는다"는 EOS-134 착지로 낡았다.** 다만 결론은 그대로다. 정답만 들어가므로 전이는 R1·R2뿐이다.
- 앱의 오답·포기는 어디에도 적재되지 않는다. 따라서 **R3(오개념 교정 · `EOS-24`)와 R6(원인 미상 오답 · `EOS-26`) 집행은 앱 학생에게 0회**다.
- **§18 Loop 1의 "오답 → 보정" 마디가 앱에는 존재하지 않는다.**
- 요청 형태 축은 앱과 같게 재도 통과한다(V1a·V2a · 진단 보정 프로브 app-default). 앱과 다른 것은 **이벤트 원천** 축뿐이다.

### 4-2. Kiki께 올리는 판단

| 선택 | Gate 2 판정 | 게이트 처리 | 선행 소유 |
|---|---|---|---|
| (A) API 계약 수준을 Gate 2 충족으로 본다 | 이 판정 그대로 **PASS** | Kiki가 이 판정문을 근거로 `G-p3-entry-gate2-pass` clear | `EOS-146`은 Phase 3 Release Gate A(실제 학생 계정의 답안 → 채점 → 오개념 → …) 전에 필요하다 → §7 P-1 |
| (B) 앱 도달을 Gate 2의 자로 삼는다 | **FAIL** — Loop 1 "오답 → 보정"이 앱에서 0회 | 게이트 pending 유지 · 게이트 선행에 `EOS-146` 연결 | `EOS-146` — 착수 전에 처분 판정 (가)·(나)·(다)가 먼저다(그 태스크 ③) |

근거 비교:

- **(A)의 근거**:
  - 9/19~9/25 세 판정이 같은 수준에서 쟀다. 그 세 FAIL도 이 수준에서의 FAIL이었다.
  - 계획서 300 §18의 문면은 "가능해야 한다"이다.
  - 앱 오답 원천은 Gate 2 등재 당시 어느 조건에도 없었다.
- **(B)의 근거**:
  - Phase 3 Release Gate A가 "실제 학생 계정"을 요구한다.
  - 3루프의 교수학적 가치는 Loop 1이 실제 학생에게 일어날 때만 생긴다.
- 이 판정은 어느 쪽도 고르지 않는다. 결정권은 Kiki에게 있다.

---

## §5. KPI 5종 (P-14 · `EOS-15`) — acceptance ⑤

### 5-1. 공식 실측 (9/25 §8-1과 같은 절차 — 하네스 실행 직후 같은 DB)

실행 명령은 `python -m whymath_backend.ops.loop_kpi_gate --since-hours 24`이고 결과는 **EXIT=1**이다.

> 「실측」 `합계: 통과 1 · 위반 1 · 미측정 3 / 전체 5` · `판정: 위반 있음 → exit 1`

| KPI | 판정 | 분자/분모 | 성격 | 9/25 대비 |
|---|---|---|---|---|
| ① Loop Completion Rate | unmeasured | 0 / 0 | 데이터 의존 — 관측창 세션 0건(`sessions_started=0`) | 같음 |
| ② State Integrity | unmeasured | 0 / 0 | 데이터 의존 — 스캔 대상 행 0 | 같음 |
| ③ Explainability | PASS | 0 / 40 | 잔여상한 0.0634 | 같음 |
| ④ Manual Intervention | unmeasured | 0 / 0 | 데이터 의존 — 관측창 `problem_attempt` 0건 | 같음 |
| ⑤ Traceability | **FAIL** | **40 / 40** | 전건 `break_learner_unjoined` — **판정 하네스의 삭제권 잔여**(아래) | **구조적 미측정 → 측정됨 · FAIL** |

**⑤ FAIL의 원인** — DB를 읽기 전용으로 조회해 확인했다.

- 관측창의 `recommendation_render` 이벤트는 40건이고, 모두 `learner_state_basis`가 실려 있다(EOS-132 착지 효과).
- 같은 DB의 `learning_session`은 0행, `user_profile`은 0행이다.
- 판정 하네스는 회차마다 운영 삭제권 경로 `DELETE /v1/me`로 학습자를 지운다(`_erase_learner` · `test_week1_gate_closed_loop.py:233`).
- `evidence_event`에는 설계상 `user_id`가 없다(PED-03). 그래서 삭제 후에도 추천 이벤트가 남고, 세션 조인이 끊긴 채로 계상된다.
- 수집기 자신도 관측범위에 "삭제권 이행으로 세션 행이 지워진 추천은 … break_learner_unjoined로 잡힌다(세션 기록 실패 placeholder와 구별할 수 없다)"라고 적는다.

**그래서 이 FAIL은 루프 결함의 신호가 아니다.** 드러난 것은 **무관용 축이 삭제권 1건에 반응한다**는 설계 공백이다. 운영에서도 관측창 안에 학생 한 명이 삭제권을 행사하면 ⑤는 FAIL이 된다(코드를 읽어서 그렇게 보인다 — 운영 실측 아님). 등재 제안은 §7 P-2.

### 5-2. 보조 측정 — 깨끗한 DB에 학습자 1명을 남겨 재기 (판정 불변)

"⑤ FAIL은 삭제 잔여다"라는 주장을 검증하려고 따로 쟀다.

1. 새 스크래치 DB `whymath_eos141_kpi`를 만들고 `alembic upgrade head`를 적용했다(EXIT=0).
2. 프로브 V1 1회를 데이터를 지우지 않고 남겼다(`--keep V1` · `PROBE_VERDICT[V1] … §18=PASS`).
3. 같은 CLI를 돌렸다. 결과는 **EXIT=1**이다.

| KPI | 판정 | 분자/분모 | 읽는 법 |
|---|---|---|---|
| ① | FAIL | 1 / 1 | 점추정 1.00 · Wilson 하한 0.2699 < 0.95. **측정은 된다.** 통과에는 전건 성공 세션 **≥52건**이 필요하다(같은 `wilson_lower_bound`로 계산) |
| ② | FAIL | 0 / 12 | 점추정 0 · Wilson 상한 0.1840 > 0.01. 통과에는 무위반 스캔 행 **≥268행**이 필요하다 |
| ③ | PASS | 0 / 13 | — |
| ④ | PASS | 0 / 6 | 관측 범위는 `privacy_audit` 표면뿐 |
| ⑤ | FAIL | 6 / 13 | `break_learner_unjoined=6` · `traced_full=6` · `traced_prior_only=1` |

⑤의 6건은 진단 보정 프로브의 관통 2회에서 나왔다. 각 관통이 추천 3건을 내고, 그 학습자는 다음 관통을 시작할 때 `DELETE /v1/me`로 지워졌다. DB 실측이 이를 뒷받침한다: `learning_session` 1행, 세션이 조인되는 추천 7건, 조인되지 않는 추천 6건. **남긴 학습자의 추천 7건은 끊김 0건**이다.

**결론**:
- ⑤는 구조적 미측정을 벗었다(`EOS-132`). 삭제권과 끊김의 구별이 새 공백이다.
- ①·②는 표본 크기 때문에 FAIL이다. 결함 신호가 아니다.
- ④는 표본이 있으면 PASS다.
- 미측정을 0으로 적지 않았다. 관측창이 비는 이유는 판정 하네스가 스스로 데이터를 지우기 때문이다. 네 회차 모두 같은 조건이다.

---

## §6. SCENARIO-001~010 CI 실행 확인 (acceptance ⑧)

GitHub Actions API(MCP `actions_list`·`get_job_logs`)로 판정 기준 커밋 `a82f9449`의 CI 실행 2건을 확인했다. 로그 원본 URL 다운로드는 프록시가 막았다. 대신 같은 도구의 `return_content`로 받은 로그 **전체**(1,780줄 · 1,776줄)를 읽었다.

| 실행 | 이벤트 | 결론 | 잡 | 스텝 | SCENARIO 스위트 | 3루프 하네스 | 요약 줄 |
|---|---|---|---|---|---|---|---|
| `36554382182` | merge_group (head `a82f9449`) | success | `backend — 마이그레이션·통합 (실 PG)` (job `109359972065`) | 10 `Pytest (통합테스트 — 실 PG·l3 외부서비스 제외)` = success | `scenarios/test_phase2_scenario_regression_suite.py ..........` (10 passed) | 32+4 = 36 passed · XFAIL 0 | `453 passed, 13 skipped, 12024 deselected` · seed 793445602 |
| `36556513369` | push (main `a82f9449`) | 잡 success(판정 시점에 `backend — lint·type·test`만 진행 중) | 같은 잡 (job `109367002952`) | 10 = success | `.......... [ 95%]` (10 passed) | 36 passed · XFAIL 0 | `453 passed, 13 skipped` · seed 2752051806 |

- 두 실행 모두 수집 줄이 `collected 12489 items / 12024 deselected / 1 skipped / 465 selected`이다. 명령은 `pytest -m integration --ignore=../../tests/backend/l3`, 환경은 `WHYMATH_RUN_INTEGRATION: 1`이다.
- `-ra` 요약의 SKIPPED 13건은 OCR extra · Redis 미도달 · bge-m3/OpenAI 라이브 · rate limit Redis뿐이다. **SCENARIO와 Gate 2 하네스 6종 중 skip은 0건**이다.
- week1 · week3 · p11 · persona 하네스도 두 실행에서 각각 실행 줄이 확인된다.
- **판정: SCENARIO-001~010은 판정 기준 커밋의 CI에서 실제로 실행돼 통과했다(skipped 아님).**
- 상시 도달 동결은 `EOS-142`(done)가 소유한다. `tests/infra/test_gate_harness_marker_reach_wiring.py` 86·93행이 두 파일을 동결 목록에 둔다.
- 로컬 실행(§2)은 §8-1 절차대로 `-p no:randomly`로 돌렸다. CI는 무작위 순서 2개 seed에서 같은 결과를 냈다.

---

## §7. 미충족·측정 실패 → Phase 3 선행 지목 (acceptance ⑨) · 3루프 축 소유 (⑩)

Gate 2 문면(10조건 + 3루프)에는 이 판정 수준에서 미충족이 없다. 그러나 ⑨는 "PASS가 KPI 공백을 면제하지 않는다"고 요구한다. 그래서 아래 3건을 지목한다. **등재와 `amend --depends`는 메인 세션이 한다.** 이 판정 세션은 대장을 쓰지 않았다.

| # | 항목 | 성격 | 소유 | 고쳐야 할 P3 태스크 (선행으로 걸 대상) | 근거 |
|---|---|---|---|---|---|
| P-1 | 앱 오답 이벤트 원천 부재 — Loop 1 앱 도달 0 (§4) | 판정 수준 공백 | **기존** `EOS-146-app-wrong-answer-event-source` (todo · P1) | `P3-17-week3-release-gate-judgment` | Release Gate A가 "실제 학생 계정에서 … 답안 → 채점 → 오개념 → Hint/Tutor → Mastery Update → Next Recommendation"을 요구한다(`docs/strategy/phase3_math_eos_completion_plan_source.md` 245행). 오답이 앱에서 서버에 닿지 않으면 판정 대상 자체가 없다. (B) 선택 시에는 게이트 `G-p3-entry-gate2-pass`의 선행으로 옮긴다 |
| P-2 | KPI ⑤가 삭제권 이행을 끊김으로 계상 (§5) | 측정 실패(오염) | **신규 제안** | `P3-17-week3-release-gate-judgment` | Release Gate D(데이터)와 성공 기준 1이 추적 가능성을 인용할 판정 회차다. KPI ⑤를 직접 소비하는 P3 태스크는 이 검색 방법(`backlog/tasks/P3-*.yaml`에서 `KPI ⑤`·`Traceability`·`loop_kpi_gate`·`역추적` grep)으로 0건이다. 그래서 가장 가까운 판정 소비자를 지목했다. G4(12/13) 전에도 필요하다 |
| P-3 | KPI ①②④ — 판정 환경에서 매번 미측정이거나 표본 부족 FAIL (§5) | 측정 실패(표본) | **신규 제안** | `P3-17-week3-release-gate-judgment` | 성공 기준 1("학생 100명 … 개발자가 데이터를 만지지 않고")과 Gate A("사람이 DB를 직접 수정하지 않고")가 ④ Manual Intervention과 ① Loop Completion의 실측을 요구한다. `P3-14-phase3-metrics-cli`의 "Learning Loop Success"가 ①을 재사용하면 그 태스크도 대상이다(재사용 여부는 P3-14 설계 판정 몫 — 미확인) |

### 7-1. 등재 제안 초안 (메인 세션이 `backlog.py add`로 등재 · 번호는 CLI가 배정)

> **집행 결과(같은 날 · 메인 세션)**: P-2 = `EOS-37-kpi5-erasure-traceability-disposition` · P-3 = `EOS-38-loop-kpi-judgment-sample-path`(선행 `EOS-37`). 첫 시도 `EOS-151`은 다른 세션의 원격 claim과 충돌해 CLI가 거부했고, 제안 번호로 재등재했다(두 번호 모두 원격 예약 `harness-claims/reservations/` 경유). P-1과 두 신규 태스크를 `backlog.py amend P3-17-week3-release-gate-judgment --depends …`로 `P3-17`의 선행에 걸었다 — `P3-17`의 `depends_on`은 이제 `EOS-146`·`EOS-37`·`EOS-38`을 포함한다. `P3-14`에는 걸지 않았다(①의 재사용 여부 미확인 — 아래 초안 그대로).

**P-2 제목 초안**: "KPI ⑤ Traceability가 삭제권 이행(`DELETE /v1/me`)으로 세션 조인이 끊긴 추천을 끊김으로 계상한다 — 무관용 축이 학생 1명의 삭제에 FAIL"
- ① 실측 사실(EOS-141 판정 §5 · main `a82f9449`):
  - 판정 하네스가 지운 학습자의 추천 40건이 전건 `break_learner_unjoined`로 계상돼 ⑤ FAIL 40/40이 났다.
  - 깨끗한 DB의 보조 측정에서는 6/13이었고, 남긴 학습자의 추천 7건은 끊김 0건이었다.
  - 수집기 관측범위 문구 자신이 "세션 기록 실패 placeholder와 구별할 수 없다"고 적는다.
- ② 처분 판정 선행:
  - (가) 삭제 원장(`privacy/erasure`)이 지운 세션 id를 남기고, 수집기가 그것을 `excluded_erased`로 분모에서 빼 detail에 보고한다
  - (나) 삭제 시 그 세션의 추천 `evidence_event`를 함께 삭제하거나 익명 tombstone으로 둔다(PED-03 user_id 비보유 설계와의 정합을 판정)
  - (다) 현행 유지 — 판정 하네스의 teardown 순서만 조정하고 운영 오염은 수용한다
  - PIPA 삭제권 표면을 건드리므로 결정 없이 구현하지 않는다
- ③ 모른다 ≠ 아니다: 삭제 증거가 없는 끊김은 계속 끊김으로 센다.
- ④ 변별력 두 방향:
  - 삭제 주입 → excluded(끊김 아님)
  - 세션 기록 실패 placeholder 주입 → 끊김 유지
  - 대조군: 남긴 학습자의 추천은 `traced_full`
- ⑤ 걸 P3 태스크: `P3-17-week3-release-gate-judgment`

**P-3 제목 초안**: "루프 KPI ①②④ 판정 표본 산출 경로 — Gate 2 판정 4회 모두 판정 하네스가 스스로 지운 데이터 위에서 재 미측정 또는 표본 부족 FAIL"
- ① 실측 사실(EOS-141 §5):
  - 공식 실측의 ①②④는 분모 0으로 미측정이다.
  - 학습자 1명을 남긴 보조 측정에서 ①은 1/1이지만 Wilson 하한 0.27로 FAIL, ②는 0/12이지만 Wilson 상한 0.18로 FAIL이다.
  - 통과에 필요한 최소 표본은 ① 전건 성공 세션 52건, ② 무위반 스캔 268행이다(`harness/wilson` · CONFIDENCE 0.95).
- ② 목표: 판정 시점에 ①②④가 **측정되는** 경로를 정한다. 후보는 셋이다.
  - (가) ARCH-66 ⑥에 따른 테스트 계정 세션을 관측창에 쌓는다
  - (나) 결정론 합성 부하(하네스 여정 N회 · 삭제하지 않음)를 전용 DB에 쌓고 그 위에서 CLI를 돈다
  - (다) 판정 규칙에 "표본 부족 FAIL은 미측정과 같게 계상"을 명시한다
  - 합성 부하는 실사용 검증으로 계상하지 않는다(P3-13 ARCH-66 ⑥ 단서와 같다).
- ③ 변별력: 위반 주입(끊긴 세션 · 불일치 행 · 운영자 감사 행)이 각 KPI를 FAIL로 바꾸는지 확인한다.
- ④ P-2가 먼저다. ⑤ 오염이 제거되지 않으면 이 경로의 ⑤도 FAIL로 오염된다.
- ⑤ 걸 P3 태스크: `P3-17-week3-release-gate-judgment`. `P3-14-phase3-metrics-cli`는 Learning Loop Success가 ①을 재사용할 때만 대상이다.

**P-1(기존 태스크)**: 신규 등재 없이 `backlog.py amend P3-17-week3-release-gate-judgment --depends EOS-146-app-wrong-answer-event-source`를 제안한다. Kiki가 (B)를 고르면 대신 게이트 `G-p3-entry-gate2-pass`의 선행에 연결한다.

### 7-2. 무개입 연속 3루프 축의 현재 소유 (⑩)

| 축 | 오답 유형 | 현재 소유 (full-id) | main 상태 |
|---|---|---|---|
| 상시 하네스 좌석(판정 장치) | 공통 | `PED-36-learning-scenario-bank-schema` (⑫ 이행분) | todo — ⑫ 하네스는 main에 있다 |
| CI 도달 동결 | 공통 | `EOS-142-gate2-loop-harness-ci-reach-freeze` | done |
| Loop 1 보정 — API 계약 | misconception (R3) | `EOS-24-recommendation-reads-learning-state` · `EOS-140-safeguard1-unscanned-attempt-stale-evidence` · `EOS-138-r3-misconception-input-scope` | 전부 done — 잔여 공백 없음 |
| Loop 1 보정 — API 계약 | general (R6) | `EOS-26-r6-diagnosis-prerequisite-directed` | done. **잔여**: `EOS-144-r6-probe-next-action-residual-mismatch`(탐침 정답 뒤 C 미복귀 · todo) · `EOS-148-r5-non-execution-premise-rejudge`(셋째 연속 오답 · todo) |
| Loop 1 보정 — **앱 도달** | 두 유형 모두 | **`EOS-146-app-wrong-answer-event-source`** | todo |
| Loop 3 다음 concept | 공통 | `EOS-124-next-problem-policy-selection-axis-mismatch` | done. 앱 인접: `EOS-147-all-correct-theta-upper-pin`(정답만 있는 이력의 θ 상한 고정 · todo) |

---

## §8. 최종 판정 (acceptance ⑥)

**측정 결과**
- 10조건은 전건 충족했고, 선행 P-11~P-15도 main에 있다.
- 무개입 연속 3루프는 두 오답 종류, 프로브 7변이, 진단 보정 프로브의 두 요청 형태에서 전건 성립했다. 운영자 DB 개입은 0이다.
- SCENARIO-001~010은 판정 기준 커밋의 CI에서 실제로 실행돼 통과했다.

**판정 수준과 자**
- 이 판정은 **API 계약 수준**이다. 앱 학생에게 Loop 1 "오답 → 보정"은 0회다(§4).
- 9/19·9/24·9/25는 같은 수준에서 FAIL을 냈다. 그 자로 재면 이번 판정은 PASS다.
- 앱 도달을 자로 삼을지는 Kiki 판단 사항이다(§4-2). 그 자라면 판정은 FAIL이고 소유 태스크는 `EOS-146`이다.
- 조건부 PASS가 아니다. 자를 명시한 PASS다.

**게이트 처리**
- 게이트 `G-p3-entry-gate2-pass`는 이 판정이 clear하지 않는다. decision 게이트이고 결정권은 Kiki에게 있다(acceptance ⑦). `--as kiki` 대행도 하지 않는다.

**11월 일정 영향**
- (A)를 택해 10/06 독촉일 전에 clear하면, `P3-01-scope-freeze`의 선행(`EOS-128` done · `EOS-141` 이 판정)이 모두 풀린다. Week 1 상한 11/1(`G-p3-g1-week1`)까지 착수 여유는 4주 남짓이다.
- (B)를 택하면 `EOS-146`의 처분 판정 (가)·(나)·(다)가 먼저다. 작업량은 추정 2~5 작업일이다. 교수학 판정이 선행하므로 순수 구현 시간이 아니다. (다) 채택 시에는 문서·게이트 범위 명기만 남는다.
- (B)를 택하면 P3-01~P3-14의 착수가 그만큼 밀리고, Week 1의 여유가 같은 만큼 줄어든다.
- P-2·P-3은 `P3-17`(11/15 통합 판정) 전까지만 필요하다. 진입 게이트를 막지 않는다.

# PASS

---

## §9. 부록

### 9-1. 재현 절차

9/25 §8-1과 같은 대상을 같은 플래그로 돌렸다. 이 컨테이너에는 PostgreSQL 16 클러스터가 이미 있어, initdb 대신 기동과 새 DB 생성만 했다. 127.0.0.1은 CI와 같은 trust 인증으로 맞췄다.

```bash
pg_ctlcluster 16 main start
psql -h 127.0.0.1 -p 5432 -U whymath -d postgres -c "CREATE DATABASE whymath_eos141;"
cd src/backend
export WHYMATH_DATABASE_URL="postgresql+asyncpg://whymath@127.0.0.1:5432/whymath_eos141"
export WHYMATH_RUN_INTEGRATION=1 WHYMATH_DB_DISABLE_POOL=1
python -m alembic upgrade head
python -m pytest -c pyproject.toml -p no:randomly -o addopts="" -s -rA ../../tests/backend/api/test_week1_gate_closed_loop.py ../../tests/backend/api/test_week3_gate_remediation_loop.py ../../tests/backend/api/test_p11_five_stage_loop_chain.py ../../tests/backend/api/test_e2e_persona_journeys.py ../../tests/backend/api/test_e2e_three_consecutive_loops.py ../../tests/backend/scenarios/test_phase2_scenario_regression_suite.py; rc=$?; echo "PYTEST_EXIT=$rc"
python -m whymath_backend.ops.loop_kpi_gate --since-hours 24; rc=$?; echo "KPI_EXIT=$rc"
```

실측 결과:

> 「실측」 하네스 `58 passed` · PYTEST_EXIT=0 / KPI EXIT=1(통과 1 · 위반 1 · 미측정 3)

### 9-2. 일회성 프로브의 지위와 설계

프로브는 **커밋하지 않았다.** 3루프 상시 하네스의 좌석은 `PED-36` ⑫이고 이미 main에 있다. 재작성 정보는 이렇다.

- **재사용**: `tests/backend/api/test_e2e_three_consecutive_loops.py`를 경로 로딩해 다음을 그대로 쓴다(재구현 0).
  - 판정 함수: `_remediation_node`(직접·진단 두 경로) · `_remediation_fires` · `_advance_fires` · `_describe` · `_rule_of`
  - 봉인·배치: `_Seal` · `_seed_layout` · `_DIFFICULTY_BANDS` · `_SUCCESSOR` · `_PREDECESSOR`
  - 기타: `_WRONG_ANSWERS` · `_run_diagnosis_probe` · 관측 헬퍼(`_user_id` · `_trace` · `_mastery_row_attempt_ids`) · 페르소나 조립기 `_P`
- **실행 방법**: pytest가 아닌 단독 스크립트다. 하네스 함수가 픽스처를 쓰지 않기 때문이다. `_begin`이 레이트리미터를 초기화한다. `src/backend`에서 §9-1과 같은 환경변수로 실행했다.
- **변이**:
  - V1: general · 추천 따름
  - V2: misconception · 추천 따름
  - V3: misconception · 첫 오답 뒤 추천을 무시하고 틀린 개념의 미시도 문항을 직접 골라 정답
  - V4g/V4m: 첫 오답 직후 추천이 선수 문항이면 그것도 같은 종류 오답으로 내고, 이후 추천을 따름
  - V1a/V2a: V1/V2를 `prioritize_weak_concepts` 미전송(앱 요청 형태)으로 돌림
  - Loop 2 예산은 12회다.
- **V4의 Loop 1은 두 자로 적었다**:
  - 엄격: 첫 오답 직후 추천에 하네스 규칙을 적용
  - 9/24식: 두 번째 오답 직후 추천에 직접 보정 규칙을 적용
- **결정론**: §3-3 참조.
- **KPI 보조 측정**(§5-2): 새 DB에서 V1 1회를 `content.teardown()` 없이 돌렸다. 그 학습자는 뒤따르는 `DELETE /v1/me`가 없어 남았다. 판정용 DB가 아니다.

### 9-3. 이 판정이 하지 않은 것

- 게이트 `G-p3-entry-gate2-pass`를 clear하지 않았다(⑦).
- production code·테스트·가드를 고치지 않았다(②). §5의 KPI ⑤ 설계 공백도 등재 제안만 했다.
- 대장(`backlog/`)을 쓰지 않았다. 등재와 `amend --depends`는 메인 세션 몫이다(§7).
- 연속 셋째 오답(R5), 탐침 정답 분기, 활성 가설 보유 학생의 R6는 재지 않았다(§3-5).
- 모바일 앱을 실기기·에뮬레이터로 구동하지 않았다. §4는 코드 대조다.
- 백엔드 전체 스위트는 돌리지 않았다. 코드 변경이 없는 판정 회차이기 때문이다. CI 실행 2건이 전체 통합 스위트 `453 passed`를 보인다(§6). backend 단위 잡(`backend — lint·type·test`)은 merge_group 실행에서 success이고, push 실행은 판정 시점에 진행 중이었다.

### 9-4. 판정 중 드러난 부수 사실

- EOS-26 판정문 §1-6과 `EOS-146` ①의 "코치 완료는 상태 머신을 돌리지 않는다"는 `EOS-134`(done) 착지로 **사실이 아니게 됐다**. 코치 완료는 지금 `advance_on_graded_attempt(is_correct=True)`를 부른다. 결론(R3·R6 앱 도달 0)은 유지된다. `EOS-146` ②의 경계("EOS-134는 정답 완료만 상태 머신에 태운다 — 착지해도 R3·R6 원천은 생기지 않는다")는 착지 후에도 참이지만, 그 문장 속 `EOS-134(todo)` 표기는 낡았다. 대장 정정 여부는 메인 세션 판단이다.
- persona C 하네스 출력은 `EOS-123`(done)을 여전히 "교정 문항을 맞힌 회차도 오답과 같은 1턴 감쇠"로 표기한다(`PERSONA_C_STEP=⑥`). 판정과 무관한 관측이며, 표기가 낡았는지는 확인하지 않았다.

---

*판정자: claude (판정 전용 세션 · `EOS-141`) · 판정 기준 main `a82f9449` · 판정 수준 API 계약 · 앱 도달 0 · 2026-09-29*
