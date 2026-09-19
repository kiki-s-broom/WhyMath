# Phase 2 Gate 2 최종 판정 — 계획서 300 §18 / 집행 지시문 P-16

> **판정 기준: main `77ee1992`** (2026-09-19 · `PR — 진단 → 오답 → 보정 → 복귀: 페르소나 3종 여정 완주 슬라이스 (P-15 · EOS-122) (#1227)`)
> **태스크**: `EOS-22-gate2-final-judgment` · **판정 세션**: 구현 세션과 분리(지시문 세트 주의 3번)
> **실행 환경**: 컨테이너 · PostgreSQL 16 + pgvector 0.6.0 · `alembic upgrade head` EXIT=0(104 리비전) · `WHYMATH_RUN_INTEGRATION=1`

---

## §0. 판정 전에 밝히는 것 — 시점과 지위

### 0-1. 이 판정은 예정보다 5주 빠르다

원 계획의 Gate 2 시점은 **2026-10-25**이고 Phase 2 기간은 2026-09-28~10-25다. 이 판정은 **2026-09-19**에 수행된다. 즉 **Phase 2가 아직 시작되지도 않은 시점의 판정**이다. 그럼에도 판정이 성립하는 이유는 P-01~P-15가 4주가 아니라 며칠에 압축 집행됐기 때문이며(아래 §1), 그러므로 이 판정은 "일정대로 진행된 결과"가 아니라 **"압축 집행의 중간 산출물에 대한 조기 판정"**으로 읽어야 한다.

### 0-2. 크로스워크는 P-16을 등재 제외로 처분했다

`docs/strategy/plan300_phase2_backlog_crosswalk.md:243`은 P-16을 다음과 같이 처분했다:

> `P-16` Gate 2 최종 판정(10/25) | §18 | **등재 제외** — 빌드 항목이 아니라 게이트 판정. 게다가 §9-① 일정 충돌 미해소

그 일정 충돌은 **이 판정 시점에도 미해소**다. 더 근본적으로, 같은 문서 §0-2가 기록한 **2026-09-03 Kiki 결정**이 살아 있다:

> 계획서 300의 4주 Phase 2는 **실행하지 않고 참고 문서로 강등**한다. … 10월의 공식 목표는 **G2 앵커 콘텐츠 생산**으로 유지한다.

이 판정문은 그 결정을 뒤집지 않는다. 아래 판정은 "계획서 300 §18의 문면을 그대로 자로 삼았을 때 main이 어디에 있는가"이지, "10월 목표를 폐쇄루프로 바꾼다"가 아니다.

---

## §1. 선행 조건 점검 — P-11~P-15 완료 여부

완료 판정의 시작 조건은 "P-11~P-15 완료"다. main 실측:

| 항목 | 태스크 | main 착지 | 근거 커밋 |
|---|---|---|---|
| P-11 필수 API 표면 | `EOS-10` | ✅ | `3b0e5b9e` (#1217) |
| P-12 Core/Adapter 경계 집행 | `EOS-117` | ✅ | `82d43d52` (#1215) |
| P-13 SCENARIO-001~010 + CI 배선 | `EOS-119` | ❌ **미머지** | 타 세션 원격 claim `claude/new-session-jchdr8` |
| P-14 KPI 5종 계측 | `EOS-15` | ✅ | `433ec9ea` (#1222) |
| P-15 페르소나 3종 안정화 | `EOS-122` | ✅ | `77ee1992` (#1227) |

**선행 조건 미충족.** P-13이 main에 없다. 판정 규칙("미머지 브랜치를 근거로 조건을 닫지 마라")에 따라 P-13은 **없는 것으로 판정**한다. 시작 조건이 성립하지 않는 상태에서의 판정임을 명시한다.

---

## §2. 10조건 전건 판정

각 조건은 **실행 증거**(테스트 실행 출력·이벤트 trace·exit code)를 갖는다. 근거 없는 행은 없다.

| # | 조건 | 판정 | 실행 증거 |
|---|---|---|---|
| 1 | 신규 학생 생성 가능 | **충족** | `WEEK1_GATE_STEP=1-user-created :: user_profile 0건→1건 · uid=94a7ea4a…` — OAuth state 발급 → 콜백. 학습자 행 직접 insert 0 |
| 2 | 진단 완료 가능 | **충족(단서)** | `GATE2B_3진단완료 :: 67회 제출 후 written=True · reason=captured · SE=0.2972` — 단서는 §2-1 |
| 3 | LearnerState 자동 생성 | **충족(단서)** | `GATE2B_4자동생성 :: learner_state 행=1 · provisioned_by='diagnosis_capture' · revision=1` — DB 쓰기 개입 0 |
| 4 | Concept 자동 선택 | **충족** | `WEEK1_GATE_STEP=3-concept-selected :: concept_id=64333b20… name=이차함수 · weak-concepts 콜드스타트 0건` |
| 5 | Content → Problem 연결 | **충족** | `WEEK1_GATE_STEP=4-problem-fetched :: GET /v1/problems/72705a56… 200 · 정답 비노출 확인` |
| 6 | Attempt → Assessment 동작 | **충족** | `P11_CHAIN_HANDOFF=H2-event-to-assessment :: evidence filled=3/3 · concept=1건 skill=1건 misconception=1건` |
| 7 | Misconception 기록 | **충족** | `WEEK3_GATE_STEP=2-misconception :: distribution-over-power conf=0.9 · 활성 가설로 영속` |
| 8 | Mastery 자동 갱신 | **충족** | `WEEK1_GATE_STEP=6-mastery-changed :: 스냅샷 0건→1건 · mastery=0.15` · `P11_CHAIN_HANDOFF=H3` |
| 9 | 다음 학습 자동 추천 | **충족** | `P11_CHAIN_HANDOFF=H4 :: action=practice_prerequisite · reason.type=prerequisite_gap · mastery=0.15(state 일치)` |
| 10 | 전체 과정 반복 가능 | **충족** | 3루프 연속 프로브 EXIT=0 · 이벤트 29~30건 · 운영자 DB 개입 0 (§3) |

**10조건 자체는 전건 충족이다.** 다만 2·3에는 판정을 바꾸지는 않되 반드시 함께 읽어야 할 단서가 있다.

### 2-1. 조건 2·3의 단서 — 진단 완료에 67문항

진단 *완료*(`POST /v1/me/assessments/capture` 가 `written=True`)는 CAT 중단 규칙 `TARGET_SE = 0.3`(`l2/next_problem_selection.py:72`)을 넘어야 성립하고, LearnerState 자동 생성은 **그 분기에서만** 호출된다(`api/me.py:2969` · EOS-103).

판정 프로브 실측(문항 20종 · 난이도 1.0~5.0 균등 · 정답률 2/3 고정):

| 제출 | 10회 | 20회 | 40회 | 67회 |
|---|---|---|---|---|
| SE | 1.007 | 0.536 | 0.379 | **0.297** |

단조 수렴하며 **67회째에 처음 임계를 통과**했다. 40회 시점에도 `measurement_sufficient=False`였다. 즉 조건 2·3은 **기계적으로는 도달 가능하지만 실학생이 한 자리에서 완주할 분량이 아니다.**

이 축의 소유자는 **이미 있다** — `EOS-126-cat-stop-rule-unreachable`(P0 · 타 세션 브랜치 `claude/modest-albattani-cp97rf` · 미머지). 그 태스크의 acceptance ⑧이 *"정보량이 더 높은 실제 문항 풀에서는 수렴이 빠를 수 있으므로 처분 판단 전에 수렴 곡선을 다시 측정한다"*고 열어 둔 질문에, 위 실측이 답한다: **"영구히 도달 불가"가 아니라 "67문항에서 도달"이다.** 등재 문구의 "영구히"는 이 측정으로 정정되어야 한다. (착수 순서 규칙상 타 세션 claim 태스크의 대장은 이 세션이 직접 고치지 않는다 — 판정문에 근거만 남긴다.)

---

## §3. 추가 최종 조건 — 무개입 연속 3루프

> 운영자가 DB를 직접 수정하지 않고 **3회 이상 연속 Learning Loop**가 가능해야 한다.
> Loop 1: 진단 → 문제 → 오답 → **보정** / Loop 2: 보정 → 문제 → 정답 → mastery 상승 / Loop 3: **다음 concept** → 문제 → 평가 → 추천

### 3-1. 상시 하네스는 존재하지 않는다

`tests/backend/api/test_e2e_persona_journeys.py:32`가 명시한다:

> 연속 3루프(계획서 §18)·SCENARIO-001~010(§16)은 이 하네스의 범위가 아니다 (각각 `PED-36` ⑫·`EOS-119` 소유).

`PED-36` ⑫는 **todo**이고 그 본문이 *"현행은 1회 관통까지만 실증돼 있다"*고 적는다. 즉 **이 조건을 재는 상시 장치가 main에 없다.** 그래서 이 판정은 일회성 프로브로 직접 측정했다(프로브 전문 = §7 부록).

### 3-2. 프로브 3회차 실측 — 배치에 따라 결과가 갈린다

학습자 1명 · 로그인 이후 학습자 축 ORM 쓰기 0 · 상태를 움직이는 경로는 HTTP뿐.

| 변이 | 배치 | EXIT | Loop 1 "보정" | Loop 3 "다음 concept" |
|---|---|---|---|---|
| 1 | 일반 오답 · **추천을 따라감** | 0 | ❌ `action=diagnose · reason=unmeasured` | ❌ 문항소속=**현재** |
| 2 | 오개념 유발 오답 · **추천을 따라감** | **1** | ❌ `action=diagnose · reason=unmeasured` | ❌ 문항소속=**현재** (`action=practice_prerequisite`) |
| 3 | 오개념 유발 오답 · **추천을 무시하고 현재 개념을 숙달** | 0 | ❌ `action=diagnose · reason=unmeasured` | ✅ 문항소속=**다음** |

변이 3의 최종 출력:

> `GATE2_LOOP3_1다음concept :: 문항=c7e0fbaf… · 문항소속=다음 · action=diagnose · reason=unmeasured`
> `GATE2_TRACE_전문 :: 이벤트 30건`
> `GATE2_RESULT :: LOOP1=True LOOP2=True LOOP3=True · 운영자 DB 개입=0 (경로가 HTTP뿐) · 이벤트=30건`

### 3-3. 판정 — **미충족**

세 가지가 겹친다.

1. **Loop 1의 네 번째 마디 "보정"이 3회차 전건에서 발화하지 않았다.** 오답 직후 추천은 언제나 `action=diagnose · reason=unmeasured`였다. 변이 2에서 상태 머신은 `REMEDIATING`으로 갔는데 **추천은 그 상태를 반영하지 않았다** — 상태와 추천이 같은 회차에 어긋난다.
2. **시스템 자신의 추천을 따르는 학습자는 3루프 안에 다음 concept에 도달하지 못한다**(변이 1·2). 도달한 유일한 배치(변이 3)는 **추천을 무시하고** 현재 개념을 숙달시킨 경우다. 즉 3루프는 "루프가 닫혀서" 도는 것이 아니라 "학습자가 올바른 경로를 미리 알고 있어서" 돈다.
3. **변이 3에서도 추천의 설명은 틀렸다** — 고른 문항은 다음 개념인데 `reason=unmeasured`다. 이는 main에 **정직한 공백으로 동결된 기지 결함** `EOS-124`(추천 `action`/`target_concept`과 선택된 문항의 불일치)와 같은 축이다.

"운영자 DB 개입 0"은 **충족**이다(전 회차 0). 그러나 조건이 요구한 것은 개입 0인 3회 반복이 아니라 **명시된 내용의 3루프**이며, 그것은 성립하지 않았다.

---

## §4. KPI 5종(P-14 · `EOS-15`) 실측값

CLI: `python -m whymath_backend.ops.loop_kpi_gate --since-hours 24` · **EXIT=2**

| KPI | 판정 | 분자/분모 | 비고 |
|---|---|---|---|
| ① Loop Completion Rate | **미측정** | — | **구조적** — `learning_session` writer 0건 · `evidence_event`에 `user_id` 없고 `session_id`가 호출마다 uuid4 placeholder라 조인 키 부재 |
| ② State Integrity | **미측정** | 0 / 0 | 분모 0 — 관측창에 스캔 대상 행 없음(데이터가 쌓이면 측정됨) |
| ③ Explainability | **PASS** | 0 / 15 | 무관용 충족 · 잔여상한 0.1528 |
| ④ Manual Intervention | **미측정** | 0 / 0 | 분모 0 — 관측창에 `problem_attempt` 0건(데이터가 쌓이면 측정됨) |
| ⑤ Traceability | **미측정** | — | **구조적** — `user_state_snapshot` writer 0건 · `evidence_event` 조인 불가 |

> 합계: 통과 1 · 위반 0 · **미측정 4** / 전체 5 → 판정: 측정 실패 있음 → exit 2 (미측정은 통과가 아니다)

**미측정을 0으로 적지 않았다.** 계획서 §19가 Phase 2의 성공을 이 5축으로 재정의했고, 게이트 모듈 자신의 설계 규칙 1이 *"미측정은 통과가 아니다"*라고 못박는다. ①⑤는 **데이터가 아무리 쌓여도 해소되지 않는 구조적 미측정**이다 — 즉 시스템은 지금 **"루프가 닫혔다"를 스스로 증명할 수 없다.**

여기서 ③의 PASS는 *reason 필드가 존재하는가*만 재며 *reason이 맞는가*는 재지 않는다. §3-3의 3번(다음 개념 문항에 `reason=unmeasured`)이 ③을 통과한 것이 그 증거다.

---

## §5. 판정 하네스의 CI 배선 — 오늘의 통과가 내일 유지되지 않는다

워크플로 참조 전수 실측(`grep -c <파일명> .github/workflows/*.yml`):

| 하네스 | 워크플로 참조 | 실제 실행 |
|---|---|---|
| `test_week1_gate_closed_loop.py` | **0건** | 어느 잡도 실행하지 않음 |
| `test_week3_gate_remediation_loop.py` | **0건** | 어느 잡도 실행하지 않음 |
| `test_e2e_persona_journeys.py` | **0건** | 어느 잡도 실행하지 않음 (P-15가 어제 착지시킨 산출물) |
| `test_p11_five_stage_loop_chain.py` | ci.yml 1건 | `e2e-nightly` — `if: github.event_name == 'schedule'` |
| `test_e2e_vertical_slice_integration.py` | ci.yml 2건 | `e2e-nightly` — 동일 |

**§2의 10조건 중 1·4·5·7·8의 증거를 내는 하네스는 어느 CI 잡에서도 돌지 않는다.** `backend` 잡에는 postgres service도 `WHYMATH_RUN_INTEGRATION`도 없어 이 파일들은 `10 skipped · exit 0`으로 끝난다 — 컨테이너에서 그 조건을 재현해 확인했고, 실 PG + 플래그를 주자 `10 passed`로 바뀌었다. **skip이 통과로 위장하던 상태**다.

이 축의 소유자는 `EOS-21-week-gate-harnesses-never-run-in-ci`(todo · P1)이며, 그 태스크가 적은 범위는 Week 1·2뿐이었다. 이번 판정 실측으로 **week3·persona 2종을 범위에 추가**했다(`backlog.py amend` · 이 PR에 포함).

---

## §6. 미충족 항목별 — 끊긴 지점 · 남은 작업량 · 11월 영향

### 6-1. 무개입 연속 3루프 (§3) — **미충족**

- **끊긴 지점**: ⓐ 오답 직후 추천이 `REMEDIATING` 상태를 읽지 않고 `diagnose/unmeasured`를 낸다(추천 정책의 입력에 상태 머신이 연결돼 있지 않다) ⓑ 추천의 `action`/`target_concept`과 실제 선택 문항이 어긋난다(`EOS-124` 기지 결함) ⓒ 이 조건을 재는 상시 하네스 자체가 없다(`PED-36` ⑫ todo).
- **남은 작업량**: 하네스 신설 1건(중 — `PED-36` ⑫가 소유 · 프로브가 이미 있으므로 골격은 재사용 가능) + 추천 정책의 상태 반영 1건(중~대 — 정책 설계 판정 선행) + `EOS-124` 해소 1건(중). 합계 **대략 3~5 작업일**, 단 추천 정책 축은 교수학 판정이 선행해야 하므로 순수 구현 시간이 아니다.
- **11월 영향**: 이 조건은 "폐쇄루프가 실제로 돈다"의 유일한 종합 증거다. 미충족 상태로 11월에 들어가면 **콘텐츠 생산(G2) 성과를 학습 효과로 환산할 계측기가 없는 채로** 앵커 콘텐츠를 쌓게 된다. 다만 2026-09-03 결정이 10월 공식 목표를 G2로 유지했으므로 **일정상 즉시 블로커는 아니다** — 블로커가 되는 시점은 학습 효과 측정을 요구하는 G4(12/13)다.

### 6-2. KPI ①⑤ 구조적 미측정 (§4)

- **끊긴 지점**: `learning_session` writer 0건 · `user_state_snapshot` writer 0건 · `evidence_event`에 학습자 조인 키 부재(`session_id`가 uuid4 placeholder).
- **남은 작업량**: 세션 writer 배선 1건(중) + `evidence_event` 조인 키 도입 1건(중, 마이그레이션 동반). **대략 2~4 작업일**. KPI 게이트는 원천 대장이 `PRODUCED`로 바뀌면 **스스로 `unmeasured`를 벗도록** 이미 설계돼 있어 게이트 쪽 추가 작업은 없다.
- **11월 영향**: ①⑤가 없으면 G4에서 "루프 완주율"과 "역추적률"을 보고할 수 없다. G4 이전에 해소돼야 한다.

### 6-3. 판정 하네스 CI 미배선 (§5)

- **끊긴 지점**: `backend` 잡에 PG service·통합 플래그 부재 · `e2e-nightly`가 파일을 이름으로만 2종 호출 · schedule 전용이라 PR에서 회귀가 잡히지 않는다.
- **남은 작업량**: `EOS-21` 해소 1건(소~중 — 잡 하나에 service + 플래그 + 파일 목록). **대략 0.5~1 작업일**.
- **11월 영향**: 낮지만 누적 위험이 크다. 지금 통과하는 10조건이 11월 중 어느 PR에서 깨져도 **아무도 모른다**. 가장 싸고 가장 먼저 해야 할 항목이다.

### 6-4. 선행 조건 P-13 미착지 (§1)

- **끊긴 지점**: `EOS-119`(SCENARIO-001~010 + CI 배선)가 타 세션 claim·미머지.
- **남은 작업량**: 해당 세션의 PR 머지 대기. 이 판정 세션의 작업량 아님.
- **11월 영향**: SCENARIO 회귀 스위트가 없으면 §5와 같은 위험이 시나리오 축에서 반복된다.

---

## §7. 최종 판정

10조건은 전건 충족했다. 그러나 완료 판정이 요구한 것은 **"10조건 전부 충족 + 무개입 연속 3루프"**이고, 두 번째 조건이 실측에서 성립하지 않았다 — 시스템 자신의 추천을 따르는 학습자는 3루프 안에 규정된 여정을 완주하지 못하며(변이 2 EXIT=1), 완주한 유일한 배치는 추천을 무시한 경우다. 여기에 선행 조건 P-13 미착지, KPI 5종 중 4종 미측정(2종은 구조적), 판정 하네스 5종 중 3종 CI 미배선이 겹친다.

조건부 PASS는 없다.

# FAIL

---

## §8. 부록 — 재현 절차와 프로브 전문

### 8-1. 환경 재현

```bash
# PostgreSQL 16 + pgvector
apt-get install -y postgresql-16-pgvector
initdb -D <DATA_DIR> -A trust -U whymath && pg_ctl -D <DATA_DIR> -o '-p 5432' start
psql -h 127.0.0.1 -p 5432 -U whymath -d postgres -c "CREATE DATABASE whymath;"

# 백엔드
cd src/backend
python3.12 -m venv <VENV> && <VENV>/bin/python -m pip install -e ".[dev]" -e ../data-pipeline
export WHYMATH_DATABASE_URL="postgresql+asyncpg://whymath@127.0.0.1:5432/whymath"
export WHYMATH_RUN_INTEGRATION=1 WHYMATH_DB_DISABLE_POOL=1
python -m alembic upgrade head

# 10조건 하네스 (CI가 돌리지 않는 3종 포함)
python -m pytest -c pyproject.toml \
  ../../tests/backend/api/test_week1_gate_closed_loop.py \
  ../../tests/backend/api/test_week3_gate_remediation_loop.py \
  ../../tests/backend/api/test_p11_five_stage_loop_chain.py \
  ../../tests/backend/api/test_e2e_persona_journeys.py -s ; echo "EXIT=$?"

# KPI 5종
python -m whymath_backend.ops.loop_kpi_gate --since-hours 24 ; echo "EXIT=$?"
```

실측 결과: 하네스 `10 passed` EXIT=0 · KPI EXIT=2.

### 8-2. 3루프 프로브의 지위

프로브는 **커밋하지 않았다.** 연속 3루프 상시 하네스의 소유자는 `PED-36` ⑫이고 그 태스크는 타 세션 claim 상태이므로, 판정 세션이 그 자리를 선점하지 않는다(착수 순서 규칙). 프로브는 일회성 측정기이며 설계는 다음과 같다 — 재작성에 필요한 정보는 전부 여기 있다.

- `tests/backend/api/test_e2e_persona_journeys.py`를 경로 로딩해 조립기(`_begin`·`_seed_concept`·`_seed_problems`·`_prereq_edge`·`_attempt`·`_mastery_of`·`_next_problem`·`_login`)를 그대로 재사용한다(재구현 0).
- 개념 3종(선수 · 현재 · 다음)을 `prerequisite` 엣지로 잇고, 각각 문항 6·6·3종을 겹치지 않는 난이도 대역(1.0~2.0 / 2.5~3.5 / 4.2~4.8)에 심는다. **난이도는 1~5 범위 강제**다(범위 밖이면 `ProblemSchema` 검증에서 거부).
- 학습자 1명을 `_login`으로 만들고 **그 뒤로는 지우지 않는다**(3루프가 같은 학습자에게 연속이어야 한다). 로그인 이후 학습자 축 ORM 쓰기 0 — 상태 변경 경로는 HTTP뿐이다.
- 루프마다 시작·끝에서 `/v1/me/mastery/current`·`/v1/me/learner-state`를 읽어 표로 남기고, 마지막에 `/v1/me/learning-trace` 전문을 출력한다.
- 판정 단언: Loop 3의 추천 문항이 **다음 개념 소속인지**를 명시 단언한다(이것을 단언하지 않으면 변이 1이 그대로 통과한다 — 실제로 그렇게 통과했고, 단언을 넣은 변이 2에서 EXIT=1로 드러났다).

### 8-3. 이 판정이 등재·정정한 것

| 대상 | 처분 | 근거 |
|---|---|---|
| `EOS-21-week-gate-harnesses-never-run-in-ci` | acceptance **범위 확장** — 미배선 하네스가 Week1·2 외 week3·persona 2종 더 | §5 전수 실측 |
| `EOS-23-diagnosis-completion-item-count-barrier` | **등재 후 취소** — `EOS-126`(타 세션·P0)이 같은 축 선점 | 중복 고지 실측 |
| `EOS-126-cat-stop-rule-unreachable` ⑧ | 정정 **근거만 제시**(대장 미수정 — 타 세션 claim) | §2-1 SE 수렴 곡선 |

---

*판정자: claude (EOS-22) · 판정 기준 main `77ee1992` · 2026-09-19*
