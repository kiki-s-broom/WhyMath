# Phase 2 Gate 2 재판정 — 게이트 `G-p3-entry-gate2-pass`

> **판정 기준: main `5af2097b`** (2026-09-24 · `MP-02 원격 홀드 해제 + acceptance 전수 재대조 — done 미처리 (#1290)`)
> **선행 판정**: `docs/reviews/eos_phase2_gate2_judgment_2026-09-19.md` (main `77ee1992` · **FAIL**)
> **판정 세션**: 구현 세션과 분리(게이트 제목 · 지시문 주의 4). production code 변경 0.
> **소유 태스크**: `EOS-130-phase2-gate2-rejudgment` — **PR #1294에만 있다(미머지 · 미착수 · 원격 claim 없음)**. main에 파일이 없어 이 세션이 claim할 수 없었다. #1294가 머지되면 이 판정문을 증거로 `EOS-130`을 닫을 수 있다(§7).
> **실행 환경**: 컨테이너 · PostgreSQL 16 + pgvector · `alembic upgrade head` EXIT=0(리비전 105) · `WHYMATH_RUN_INTEGRATION=1`

---

## §0. 결론 먼저

**FAIL.** 9/19와 같은 판정이며, 이유도 같다 — **무개입 연속 3루프가 성립하지 않는다.** 10조건은 이번에도 전건 충족했다.

9/19 이후 main에 들어온 67커밋 중 3루프 축에 닿는 것은 `EOS-126`(진단 문항 수 상한 20) 하나뿐이다. 이 변경으로 조건 2·3의 단서(진단 완료에 67문항)는 해소됐지만, 3루프를 막는 세 원인(추천 정책이 상태 머신을 읽지 않음 · `EOS-124` · 상시 하네스 부재)은 main에서 하나도 바뀌지 않았다.

---

## §1. 선행 판정과의 대조표

| 항목 | 9/19 (`77ee1992`) | 9/24 (`5af2097b`) | 변화 |
|---|---|---|---|
| 선행 P-13(`EOS-119`) main 착지 | ❌ 미머지 | ❌ 미머지 (타 세션 claim `claude/new-session-jchdr8`) | 같음 |
| 10조건 | 전건 충족 (단서 2·3) | 전건 충족 | **단서 해소** (§2-1) |
| 판정 하네스 4종 | `10 passed` | `12 passed` EXIT=0 | 테스트 2건 늘어남 |
| 무개입 연속 3루프 | 미충족 (3변이 전건) | **미충족 (4변이 전건)** | 끊기는 지점이 옮겨짐 (§3) |
| KPI 5종 | 통과 1 · 미측정 4 · EXIT=2 | 통과 1 · 미측정 4 · EXIT=2 | 같음 |
| KPI ①⑤ 구조적 미측정 | writer 0건 | writer 0건 (`LearningSession(`·`UserStateSnapshot(` 생성 0건) | 같음 |
| 하네스 CI 배선(`EOS-21`) | week1·week3·persona 참조 0건 | 참조 0건 (워크플로 6종 전수) | 같음 |

---

## §2. 10조건 — 전건 충족

재현 명령은 9/19 판정문 §8-1과 같다. 결과: 하네스 4종 `12 passed` · **EXIT=0**.

| # | 조건 | 판정 | 실행 증거 (이번 실행) |
|---|---|---|---|
| 1 | 신규 학생 생성 | 충족 | `WEEK1_GATE_STEP=1-user-created :: user_profile 0건→1건` |
| 2 | 진단 완료 | 충족 | §2-1 |
| 3 | LearnerState 자동 생성 | 충족 | §2-1 (진단 확정 분기 · `EOS-126`의 persona 진단 확정 테스트) |
| 4 | Concept 자동 선택 | 충족 | `WEEK1_GATE_STEP=3-concept-selected :: name=이차함수 · weak-concepts 콜드스타트 0건` |
| 5 | Content → Problem | 충족 | `WEEK1_GATE_STEP=4-problem-fetched :: 200 · 정답 비노출 확인` |
| 6 | Attempt → Assessment | 충족 | `P11_CHAIN_HANDOFF=H2-event-to-assessment :: evidence filled=3/3` |
| 7 | Misconception 기록 | 충족 | `WEEK3_GATE_STEP=2-misconception :: distribution-over-power conf=0.9 · 활성 가설로 영속` |
| 8 | Mastery 자동 갱신 | 충족 | `WEEK1_GATE_STEP=6-mastery-changed :: 스냅샷 0건→1건 · mastery=0.15` |
| 9 | 다음 학습 자동 추천 | 충족 | `P11_CHAIN_HANDOFF=H4-learner-state-to-recommendation` · `WEEK1_GATE_STEP=7-next-problem-recommended` |
| 10 | 전체 과정 반복 | 충족 | §3 프로브 4변이 전건 HTTP 경로만으로 완주 · 운영자 DB 개입 0 |

### 2-1. 조건 2·3의 단서는 해소됐다

9/19에는 진단 확정이 SE ≤ 0.3에서만 성립해 **67문항**이 필요했다. `EOS-126`(`8ee9231c` · #1274)이 2차 중단 규칙 `MAX_ADMINISTERED_ITEMS = 20`(`l2/next_problem_selection.py`)을 넣어, 20문항이 채점되면 진단을 확정할 수 있게 됐다. 정밀도 임계 `TARGET_SE = 0.3`은 그대로이며, 상한으로 끝난 진단은 `reason="captured_at_item_cap"`과 `measurement_sufficient=False`를 그대로 달고 나간다(정밀도를 달성한 척하지 않는다). 따라서 **조건 2·3은 단서 없이 충족**으로 올린다.

---

## §3. 무개입 연속 3루프 — **미충족**

### 3-1. 측정 방법

9/19 판정문 §8-2 설계를 그대로 다시 만든 일회성 프로브로 쟀다(커밋하지 않음 — 상시 하네스 자리는 `PED-36` ⑫ 소유). 개념 3종(선수 → 현재 → 다음)을 `prerequisite` 엣지로 잇고, 난이도 대역을 1.0~2.0 / 2.5~3.5 / 4.2~4.8로 나눴다. 학습자 1명 · 로그인 이후 학습자 축 ORM 쓰기 0 · 상태를 움직이는 경로는 HTTP뿐이다. **두 번 실행했고 두 번 모두 결과가 같았다(결정론).** 테스트 EXIT=1.

마디별 판정 기준:

- **Loop 1 "보정"**: 첫 오답 직후 추천의 `action`이 `practice_prerequisite` 또는 `practice_current`이고, `reason.type`이 `unmeasured`가 아니다 (9/19와 같은 기준). *2026-09-25 재정의 — 원인 미상 오답의 선수 진단을 조건부로 인정한다. §3-4 사후 보정 참조.*
- **Loop 2 "mastery 상승"**: 보정 구간에서 푼 개념의 숙달이 그 구간 시작 때보다 오른다.
- **Loop 3 "다음 concept"**: 추천 문항이 다음 개념 소속이고, 그 문항을 제출한 뒤 다시 추천이 나온다.

### 3-2. 결과

| 변이 | 배치 | Loop 1 보정 | Loop 2 | Loop 3 | 이벤트 |
|---|---|---|---|---|---|
| V1 | 일반 오답(`7`) · 추천을 따라감 | ❌ `diagnose · unmeasured` (문항=선수) | ✅ | ✅ `advance_next · next_concept` | 33건 |
| V2 | 오개념 오답(`x^2+4`) · 추천을 따라감 | ❌ `diagnose · unmeasured` (상태는 `REMEDIATING`) | ✅ | ✅ `advance_next · next_concept` | 34건 |
| V3 | 오개념 오답 · 추천을 무시하고 현재 개념 숙달 | ❌ `diagnose · unmeasured` | ✅ | ✅ (단, 추천 설명은 `diagnose · unmeasured`) | 30건 |
| V4 | 오개념 오답 → **추천된 선수 문항도 오답** → 추천을 따라감 | ✅ `practice_prerequisite · prerequisite_gap` (한 단계 늦게) | ✅ | ❌ 문항=**현재** · `advance_next` · target=현재 | 35건 |

**4변이 중 3루프를 모두 통과한 변이는 0개**다. 모든 변이의 trace는 `truncated=False`다.

### 3-3. 9/19와 달라진 점 — 끊기는 자리가 옮겨졌다

- **나아진 점**: 9/19에는 추천을 따르는 학습자(V1·V2)가 다음 개념에 도달하지 못했다(V2 EXIT=1). 이번에는 **V1·V2도 다음 개념에 도달하고, 추천 설명도 `advance_next · next_concept`으로 맞다.** 또 오답 직후 추천이 고르는 문항은 **선수 개념 문항**(`target=선수`)이다. 즉 내용상으로는 선수 개념 쪽으로 내려가는 움직임이 있다.
- **그대로인 점**: 그 선수 문항에 붙은 설명은 `diagnose · unmeasured`다(선수 개념이 아직 측정되지 않았기 때문). 오개념 오답으로 상태 머신이 `REMEDIATING`에 가고 `l2/learning_state_policy`가 `NextActionKind.REMEDIATE_MISCONCEPTION`을 만드는데도, `GET /v1/me/next-problem`의 추천 정책(`NextProblemPolicy(learner_state, learning_context)`)은 **그 상태를 입력으로 받지 않는다.** 보정이 추천으로 드러나려면 V4처럼 선수 문항을 한 번 더 틀려야 한다.
- **V4에서 드러난 것**: 보정이 발화하는 경로로 가면 이번에는 Loop 3에서 `EOS-124`(추천 `action`은 전진인데 문항·`target_concept`은 현재 개념)에 막힌다. persona A 하네스가 main에 "정직한 공백"으로 동결해 둔 바로 그 결함이다.

정리하면 **Loop 1 보정과 Loop 3 전진은 한 학습자 안에서 동시에 성립하지 않는다.** 보정이 드러나지 않는 경로(V1~V3)에서는 전진이 되고, 보정이 드러나는 경로(V4)에서는 전진이 막힌다.

### 3-4. 판정 기준에 대한 한 줄 (Kiki 판단 영역)

"오답 직후 선수 개념 문항을 **진단 목적**으로 내는 것"을 보정으로 볼지는 교수학적 해석의 문제다. 이 판정은 9/19와 **같은 자**(추천의 `action`/`reason`이 보정을 말하는가)를 썼다. 기준을 바꾸려면 Kiki 결정이 필요하다 — 다만 **기준을 완화해도 FAIL은 그대로다.** V1~V3을 통과로 쳐도 V4의 Loop 3 실패(`EOS-124`)가 남고, 선행 P-13 미착지(§1)도 남는다.

> **사후 보정 (2026-09-25 · main `81070ed5` · `EOS-139`)** — 위 질문에 Kiki가 답했다(게이트 `G-eos24-loop1-undiagnosed-wrong-criterion` clear). **Loop 1 "보정" 기준을 재정의한다**: §3-1의 기준(직접 보정)에 더해, 오답이 **원인 미상**(상태 머신 R6)일 때만 `diagnose`도 보정으로 친다. 단 두 조건을 모두 만족할 때만이다 — ⓐ 진단 문항의 대표 개념이 오답 개념의 **선수** 개념일 것 ⓑ 그 진단 문항을 틀리면 다음 추천이 `practice_prerequisite`로 하강할 것. 오개념 오답(R3)의 `diagnose`는 여전히 보정이 아니다(EOS-24 판정문 §2).
>
> **이 문서 §3-3의 사실 서술 정정** — "오답 직후 추천이 고르는 문항은 **선수 개념 문항**"은 프로브 픽스처에서만 참이다. 추천기는 선수 그래프를 보지 않고 θ 근방 최근접(=오답 직후에는 가장 쉬운 문항)을 고르며, 프로브가 선수 개념을 **유일하게 더 쉬운 개념**으로 심었기 때문에 선수로 간 것이다. 2026-09-25 방해 개념 프로브(선수 관계가 없는 개념을 선수보다 쉽게 심음)에서 진단은 그 무관 개념으로 갔다. 그래서 재정의된 기준 아래에서도 V1(일반 오답)의 Loop 1은 **여전히 미충족**이다 — ⓑ는 성립하지만 ⓐ를 시스템이 보장하지 않는다. 상시 판정은 `tests/backend/api/test_e2e_three_consecutive_loops.py`(진단 보정 프로브 · `_FROZEN_PROBE`), ⓐ를 구조적으로 충족시키는 서빙 변경은 `EOS-26-r6-diagnosis-prerequisite-directed`가 소유한다.

---

## §4. KPI 5종 — 변화 없음

`python -m whymath_backend.ops.loop_kpi_gate --since-hours 24` · **EXIT=2** (통과 1 · 위반 0 · 미측정 4 / 전체 5).

| KPI | 판정 | 비고 |
|---|---|---|
| ① Loop Completion Rate | 미측정 | 구조적 — `learning_session` writer 0건 |
| ② State Integrity | 미측정 | 분모 0 (스캔 대상 행 없음) |
| ③ Explainability | PASS | 0 / 11 · 잔여상한 0.1974 |
| ④ Manual Intervention | 미측정 | 분모 0 (관측창 `problem_attempt` 0건) |
| ⑤ Traceability | 미측정 | 구조적 — `evidence_event` 조인 키 부재 · `user_state_snapshot` writer 0건 |

③의 PASS는 여전히 *reason 필드가 있는가*만 잰다. V3의 다음 개념 문항에 붙은 `reason=unmeasured`가 ③을 통과하는 것이 그 증거다(9/19 §4와 같음).

---

## §5. 미충족 항목과 소유자

| 미충족 | 끊긴 지점 | 소유 태스크 | main 상태 |
|---|---|---|---|
| Loop 1 보정 미발화 | 추천 정책이 상태 머신 상태·다음행동을 읽지 않음 | **`EOS-24-recommendation-reads-learning-state`** (이 PR에서 신규 등재) | todo |
| Loop 3 전진 불일치 (V4) | 추천 `action`/`target_concept` ↔ 선택 문항 불일치 | `EOS-124-next-problem-policy-selection-axis-mismatch` | todo |
| 3루프 상시 하네스 없음 | 이 조건을 재는 CI 장치가 없음 | `PED-36` ⑫ | todo |
| 판정 하네스 CI 미배선 | week1·week3·persona 워크플로 참조 0건 | `EOS-21-week-gate-harnesses-never-run-in-ci` | todo (타 세션 claim `claude/compassionate-hypatia-chznsu`) |
| KPI ⑤ — `user_state_snapshot` writer 0 | 스냅샷 생성 경로 없음 | `ARCH-51-user-state-snapshot-seat-disposition` | todo |
| KPI ①⑤ — `learning_session` writer 0 · `evidence_event` 조인 키 부재 | 세션 writer 없음 · `session_id`가 uuid4 placeholder | **소유자 미확인** — 열린 태스크에서 `learning_session`·`evidence_event`+`user_id`/조인으로 찾은 결과 직접 소유 0건(`PED-14`는 인접 언급뿐). 내가 찾은 방법으로 0건이며, Gate 2 문면(10조건+3루프) 밖이라 이 판정에서는 등재하지 않았다 — 등재는 `P3-00` ②의 몫이다 | — |
| 선행 P-13 | SCENARIO 회귀 스위트 미머지 | `EOS-119` | 타 세션 claim · 미머지 |
| 상태 머신 R4 미발화 (인접) | `prerequisite_gap_concept_ids` 미배선 | `EOS-127-prerequisite-gap-rule-r4-wiring` | todo |

**신규 등재 1건의 근거**: 9/19 판정문 §6-1 ⓐ가 이 축을 "추천 정책의 상태 반영 1건(중~대 — 정책 설계 판정 선행)"으로 지목했지만, 소유 태스크는 등재되지 않았다. 역할 기반으로 검색했다 — 열린 태스크 중 상태 머신 출력을 추천 입력으로 연결하는 것을 acceptance로 가진 태스크를 찾았고(`REMEDIATING`·`NextAction`·`next_action` 키워드, 추천/상태 머신 동시 언급), 결과는 0건이었다. 가장 가까운 `EOS-127`은 상태 머신의 *입력* 축이고, `EOS-124`는 추천 *내부* 축이다. 이 태스크는 상태 머신 *출력* → 추천 *입력* 축이다. 세 태스크의 경계는 `EOS-24` acceptance ④에 적었다.

---

## §6. 최종 판정

10조건은 전건 충족했고, 조건 2·3의 단서도 `EOS-126`으로 해소됐다. 그러나 완료 판정의 두 번째 요건인 **무개입 연속 3루프**는 4변이 전건에서 성립하지 않았다. 여기에 선행 조건 P-13 미착지, KPI 5종 중 4종 미측정(2종은 구조적), 판정 하네스 CI 미배선이 9/19와 똑같이 남아 있다.

조건부 PASS는 없다. 게이트 `G-p3-entry-gate2-pass`는 **pending을 유지**한다(clear하지 않는다).

# FAIL

---

## §7. 부록

### 7-1. 재판정 PASS까지 필요한 최소 경로

1. `EOS-24`(추천이 상태를 읽음) — 정책 설계 판정이 먼저 필요하다.
2. `EOS-124`(추천 설명과 선택 문항의 일치).
3. `PED-36` ⑫ 상시 3루프 하네스 + `EOS-21` CI 배선 — 통과가 유지되는지 CI가 지켜보게 한다.
4. `EOS-119` 머지 — 선행 조건.

KPI ①⑤(`ARCH-51` + 소유자 미확인 축)는 Gate 2 완료 판정의 문면(10조건 + 3루프) 밖이지만, 9/19 판정과 같은 이유로 G4(12/13) 전에 해소돼야 한다.

### 7-2. 대장에 대해 이 판정이 하지 않은 것

- `EOS-130-phase2-gate2-rejudgment`: main에 없어 claim하지 않았다. PR #1294 머지 후 이 판정문을 근거로 `done`할 수 있다. 참고로 그 태스크는 `depends_on: EOS-21`을 걸고 있는데, 이 판정은 CI 배선을 기다리지 않고 실 PG에서 하네스를 직접 돌려 같은 근거를 얻었다. 그 의존을 유지할지는 `EOS-130` 소유 세션이 판단한다.
- `P3-00-phase2-acceptance-check`: 자기가 증거를 대야 할 게이트를 `requires_gates`로 걸고 있다(순환). `EOS-130` notes가 이미 지적한 내용이라 여기서는 다시 등재하지 않는다.
- 게이트 `G-p3-entry-gate2-pass`: FAIL이라 clear 대상이 아니다. decision 게이트의 결정권은 Kiki에게 있다.

### 7-3. 3루프 프로브 재작성 정보

9/19 판정문 §8-2 설계와 같다. 차이점은 두 가지다. ⓐ V4를 추가했다 — 오답 직후 추천된 문항이 선수 개념이면 그 문항도 오답으로 제출한다. ⓑ trace 이벤트 수는 응답의 `entries` 길이로 센다(응답 최상위 dict의 키 수가 아니다 — 첫 실행에서 이 실수로 `7건`이 찍혀 고쳤다). 이벤트 기본 상한은 200(`DEFAULT_TRACE_LIMIT`)이며, 이번 실행은 전건 `truncated=False`다.

---

*판정자: claude (판정 전용 세션) · 판정 기준 main `5af2097b` · 2026-09-24*
