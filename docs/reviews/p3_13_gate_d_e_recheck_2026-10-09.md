# P3-13 — Release Gate D·E 준비: 학습 이벤트 8종 실세션 기록 + EOS Core 경계 재확인

**판정 기준: main `594ce16b`** (2026-10-09) · 태스크 `P3-13-learning-events-and-boundary-recheck`
**측정 환경(로컬)**: PostgreSQL 16.15 + pgvector 0.6.0(CI `backend-migrations` 잡과 같은 pgvector/pg16 계열, TimescaleDB 없음) · `alembic upgrade head` 적용 · Python 3.13.16(CI는 3.12 — 차이는 §7에 명시)
**학생 세션의 기준**: **테스트 계정 기준**이다. 운영 OAuth 콜백 경로로 로그인한 내부 합성 학생의 세션이며, 실사용자 검증으로 계상하지 않는다(ARCH-66 ⑥ · 실학생 확인은 게이트 `G-student-work-after-internal-completion` 판정 이후로 연기).

---

## 0. 결론 (한 문단)

**Gate D(이벤트)**: 8개 역할 모두 테스트 계정의 실세션에서 시간선에 **실제 행으로 기록**된다. 다만 8번째 `concept_viewed`는 대응 이벤트 2종 중 1종(`content_viewed`)이 생산자 0건이라 **`concept_selected`만으로 충족**되고, 그 이벤트도 개념 id를 싣지 않는다. 추적 필드 6종 중 `content_version`은 **어느 이벤트에도 없다**(원천이 없다 — `EOS-47` 소유).
**Gate E(경계)**: Core→Adapter 직접 import **0건**, Core 안 과목 리터럴 비교 **0건**, Phase 3 직전(2026-09-23 `9ec7c3ca`) 대비 증가 0. 위반을 주입하면 지목한 가드가 **로컬에서** RED였다.
**미충족 1건**: acceptance ④의 "**CI에서** RED"는 이 세션에서 증명하지 못했다 — PR을 열어 실 CI가 해당 스텝을 실행해야 성립한다(§7).

## 1. 판정표

| acceptance | 판정 | 근거 |
|---|---|---|
| ① 이벤트 8종이 실제 학생 세션에서 기록되는가 | **충족(테스트 계정 기준) · 단서 2** | §2. 8/8 역할 기록, `concept_viewed`는 약함(§4 F2), 실사용자 검증 아님 |
| ② 이름 대조가 아니라 역할 대조인가 | **충족** | §2-1 매핑표를 코드로 동결(`GATE_D_ROLES`) — 이름 grep이면 0건이던 2종을 역할로 찾았다 |
| ③ Core에 Math 로직 침투 0건 + AST 가드에 위반 주입해 RED | **충족(로컬)** | §5. 스캔 대상 0건 아님(753개 파일·826개 파일/6,914 의존), 주입 2종 지목 가드 RED |
| ④ 경계 위반 주입이 **CI에서** RED | **미충족(미실증)** | §7. 가드의 소유 잡은 특정했으나 이번 주입을 실 CI에 올리지 않았다 |

## 2. Gate D — 이벤트 8종

### 2-1. 역할 매핑표 (개명하지 않는다)

| 원 문서 이벤트 | 저장소 카탈로그(`TraceEventType`) | 원천 상태(`SourceAvailability`) |
|---|---|---|
| `learning_started` | `diagnostic_started` · `learner_state_created` | 둘 다 PRODUCED |
| `concept_viewed` | `concept_selected` · `content_viewed` | `concept_selected` PRODUCED · **`content_viewed` DORMANT(생산자 0건)** |
| `problem_attempted` | `problem_attempted` | PRODUCED |
| `answer_submitted` | `answer_submitted` | PRODUCED(단 의미 주의 — §4 F4) |
| `misconception_detected` | `misconception_detected` | PRODUCED |
| `hint_requested` | `hint_requested` | PRODUCED |
| `mastery_updated` | `mastery_updated` | PRODUCED |
| `recommendation_generated` | `recommendation_generated` | PRODUCED |

이름이 다른 2종(`learning_started`·`concept_viewed`)은 `grep`하면 0건이다. 역할로 찾아야 한다.

### 2-2. 실측표 (한 학생이 추천 → 오답 20회 → 진단 확정 → 코치 대화를 지난 세션)

시나리오는 `tests/backend/scenarios/test_gate_d_event_role_census.py`다. 공개 HTTP 표면만 쓰고 학습자 상태는 한 줄도 직접 쓰지 않는다(저작 콘텐츠만 ORM 시딩). 아래 "채움"은 `채워진 행 / 전체 행`이다.

| 역할 → 대응 이벤트 | 건수 | learner_id | session_id | concept_id | problem_id | timestamp | content_version |
|---|---:|---|---|---|---|---|---|
| learning_started → `diagnostic_started` | 1 | 1/1 | 0/1 | 0/1 | 0/1 | 1/1 | 0/1 |
| learning_started → `learner_state_created` | 1 | 1/1 | 1/1 | 0/1 | 0/1 | 1/1 | 0/1 |
| concept_viewed → `concept_selected` | 1 | 1/1 | 1/1 | **0/1** | 0/1 | 1/1 | 0/1 |
| concept_viewed → `content_viewed` | **0** | — | — | — | — | — | — |
| problem_attempted | 20 | 20/20 | 20/20 | 0/20 | 20/20 | 20/20 | 0/20 |
| answer_submitted | 1 | 1/1 | 0/1 | 0/1 | 1/1 | 1/1 | 0/1 |
| misconception_detected | 1 | 1/1 | 0/1 | 0/1 | 0/1 | 1/1 | 0/1 |
| hint_requested | 1 | 1/1 | 0/1 | 0/1 | 1/1 | 1/1 | 0/1 |
| mastery_updated | 20 | 20/20 | 0/20 | 20/20 | 0/20 | 20/20 | 0/20 |
| recommendation_generated | 1 | 1/1 | 1/1 | 0/1 | 1/1 | 1/1 | 0/1 |

위 표의 학습 이벤트는 모두 이 학습자의 것이며 `learner_id`·`timestamp`는 전건 채워졌다(테스트가 단언한다).
표의 모든 채움 값은 테스트가 **이름별로** 직접 출력한 실측이다(`NAME=` 행). 역할 단위로 합치면 이름마다 다른 채움이 평균에 묻히므로 합치지 않았다(예: `learning_started`의 두 이벤트 중 `diagnostic_started`에는 세션 결합이 없고 `learner_state_created`에는 있다).

## 3. 추적 필드 6종

| 필드 | 판정 |
|---|---|
| `learner_id` · `timestamp` | **전 이벤트 100%** — 필수 축이다 |
| `problem_id` | 시도·응답 지연·힌트 요청·추천에는 있고, 진단 시작·상태 생성·개념 선택·오개념·숙달에는 없다 |
| `session_id` | 시도·상태 생성·개념 선택·추천에는 있고, 진단 시작·응답 지연·오개념·힌트 요청·숙달에는 없다 |
| `concept_id` | **숙달 변경에만** 있다(20/20). 나머지 7역할은 개념을 싣지 않는다 |
| `content_version` | **어느 이벤트에도 없다** — 봉투(`LearningEvent`)에 슬롯 자체가 없다 |

"없다"의 의미는 필드마다 다르다. 구조적으로 정의될 수 없는 것(오개념 가설은 학습자×오개념 누적 단위라 문항 하나에 귀속되지 않는다)과, 원천은 알고 투영에서 떨어뜨린 것(숙달 이력은 `attempt_id`를 보유하나 트레이스 행에는 문항·시도가 실리지 않는다)을 §4에서 나눈다.

## 4. 발견 — 정직한 공백 4건

| # | 발견 | 정오 판정 | 소유 |
|---|---|---|---|
| F1 | `content_version`이 봉투에도 원천에도 없다. `problem_attempt`에 `problem_version_id`가 없다 | **진성 공백.** 현재 `problem.problem_version_id`는 *지금의 서빙 판 포인터*라 시도 시점의 판이 아니므로 그 값으로 채우면 날조다. 그래서 채우지 않고 부재로 동결했다 | `EOS-47-attempt-version-pinning`(todo · 선행 `EOS-44`·`ARCH-31`) |
| F2 | `concept_viewed`: `content_viewed` 생산자 0건(DORMANT) + `concept_selected`가 `concept_id`를 싣지 않는다(세션 writer가 `target_concept_id`를 채우지 않는다) | **진성 공백.** "어느 개념을 봤는가"를 시간선이 말하지 못한다. 카탈로그의 8/8 대응은 "이름이 있다"의 판정이고 실세션에서는 이 한 역할이 가장 약하다 | `P3-27-concept-viewed-and-trace-field-gaps`(후속 등재) |
| F3 | 필드 희소: 숙달 변경에 `session_id`·`problem_id`가 없다, 응답 지연·오개념·힌트 요청에 `session_id`가 없다, 시도에 `concept_id`가 없다 | **혼재.** 오개념의 문항 부재는 구조적(N/A)이고, 숙달의 시도 귀속은 투영에서 떨어뜨린 것이다 | `P3-27-concept-viewed-and-trace-field-gaps`(후속 등재) |
| F4 | `answer_submitted`의 의미가 원 문서와 다르다 — 저장소에서는 "코치 대화의 **이어지는 턴**에서 직전 학생 턴 대비 서버 지연"이고, 답안을 낸 사건은 `problem_attempted`다 | **이름 일치·의미 이동.** 역할 대조로는 충족이나 Gate D 판정문이 "이름이 같다"를 근거로 삼지 않도록 여기 적는다 | 정보 — 조치 없음 |

두 공백(F1·F2)은 `skip`으로 위장하지 않았다. census 테스트가 **현행 동작을 단언**하고, 고쳐지면 그 단언이 실패하며 메시지가 소유 태스크를 가리킨다.

## 5. Gate E — EOS Core 경계

### 5-1. 가드 소유 잡

| 가드 | 무엇을 보는가 | CI 소유 잡 · 스텝 |
|---|---|---|
| `lint-imports` 계약 4건 | Core→Adapter **직접 import**, 7계층 방향, 데이터 접근 | `backend` 잡 "Import contracts (import-linter — 7계층 단방향)" |
| `tests/infra/test_eos_core_boundary_probe.py` | Core 안 **과목·수학유형 리터럴 비교**(AST `Compare`·`match`) · 전이 도달 집합 동결 | `infra-contracts` 잡 "Pytest (tests/infra — 계약 동결·결함주입)" |
| `tests/infra/test_eos_boundary_contract_wiring.py` 외 4 | 계약 배선·공허 금지·의존 방향·LLM↔상태 권위·불투명 페이로드 | 같은 `infra-contracts` 잡 |

주의: 과목 리터럴 비교(`if subject == "math"`)는 `lint-imports`가 **보지 못한다**(import 그래프 도구). 이 축은 `infra-contracts` 잡의 프로브 테스트 **한 곳**이 지키므로, 그 잡이 앞 스텝 실패로 skipped되면 이 보호는 그 실행에서 사라진다(CLAUDE.md 2026-09-10 "안 돌린 검사" 축 · EOS-117이 도달성을 별도로 동결해 둔 이유).

### 5-2. 현황 — Phase 3 직전(`9ec7c3ca`, 2026-09-23) 대비 `594ce16b`

| 지표 | 직전 | 현재 | 판정 |
|---|---:|---:|---|
| CORE→ADAPTER 직접 import(스캔) | 0 | **0** | 증가 0 |
| `lint-imports` 계약 | 4 kept · 0 broken | 4 kept · 0 broken | 동일 |
| 분석 파일 / 의존 간선(lint-imports) | 776 / 6,304 | 826 / 6,914 | **0 아님** — 공허 통과 아님 |
| 스캔 대상 모듈(CORE·ADAPTER·MIXED·INFRA) | 353·82·33·239 | 380·84·35·254 | 증가분 전부 스캔됨 |
| 과목·수학유형 리터럴 비교(AST 프로브) | 0 | **0** | 증가 0 |
| 전이 도달 / 잔여 누수 | 3 / 2 | 3 / 2 | 동일(같은 두 경로 — `api.coach`·`api.ocr_handoff` → … → `l3.verify_solution`) |
| 수학 어휘 문자열 상수(CORE) | 92 | 96 | +4(아래) |

**어휘 상수 +4의 정오**: `l2.irt` +1("표준오차 … 제곱근" 설명 문구), `l4.misconception.attempt_hypothesis_policy` +2(정책 표 설명·오류 메시지 문구), `l4.misconception.catalog` +1(카탈로그 서술). 전부 **산문 언급**이고 분기·import가 아니다 → **위반 아님**. `test_core_math_vocabulary_ratchet`(별도 기준선)도 통과했다.

**`ignore_imports` 18건**은 ADAPTER·MIXED·INFRA 출발의 구조적 제외이며, CORE 진성 위반을 적는 baseline 구역은 **0줄**이다(`pyproject.toml` 그룹②). 재확인 지점이던 G1(2026-09-27)은 지났고 0이 유지된다.

### 5-3. 현행 위반 목록

**진성 위반 0건.** 잔여 누수 2건(`api.coach`·`api.ocr_handoff`)은 `harness.wh1_loop`을 경유해 `l3.verify_solution`에 닿는 **전이 경로**이며 `ARCH-99`(별건) 소유로 알려진 설계상 잔여다. 이번 구간에서 늘지 않았다.

## 6. 변별력 검증 — 막으려는 상태를 실제로 주입했다

`scripts/ops/verify_gate_de_discrimination.py`. 주입이 실제 적용됐는지(`mutated != original`, 치환 대상 정확히 1건)와 원복이 바이트 동일한지(sha256)를 매 회차 단언한다. 원복은 `git checkout`이 아니라 바이트 백업 복원이다.

### 6-1. 이벤트 기록을 끊는 주입(Gate D) — 9종 전건 RED

| 주입 | 끊은 것 | 결과 |
|---|---|---|
| C01 | 진단 확정이 assessment를 적재하지 않는다 | RED — `learning_started→diagnostic_started` 지목 |
| C02 | 추천 기록이 상태 근거를 싣지 않는다 | RED — `learning_started→learner_state_created` 지목 |
| C03 | 학습 세션 writer가 세션을 만들지 않는다 | RED — `concept_selected` 외 상태 생성·추천도 함께 소실(세션 결합 키가 사라지므로) |
| C04 | 코치 후속 턴의 응답 지연 이벤트 미적재 | RED — `answer_submitted` 지목 |
| C05 | 오개념 가설 미적재 | RED — `misconception_detected` 지목 |
| C06 | 답 요구 발화의 힌트요청 미적재 | RED — `hint_requested` 지목 |
| C07 | 숙달 측정 행 미적재 | RED — `mastery_updated` 지목 |
| C08 | 추천 처치 미기록 | RED — `recommendation_generated` 지목(상태 근거도 함께) |
| C09 | 채점 제출이 시도 행을 적재하지 않는다 | RED — **단, 간접 검출**: 진단 확정 단계에서 먼저 실패했다(시도 0건이라 `insufficient_measurement`). "problem_attempted 부재" 메시지로 잡힌 것이 아니다 |

**검증 중 잡은 결함 2건(내 도구·테스트 쪽)**: ⓐ 첫 census는 역할당 "대응 이벤트 중 하나만 있으면" 통과했다 — `learning_started`는 `diagnostic_started`를 끊어도 `learner_state_created`가 가려 보호가 위장될 자리였다. 생산 중인 대응 이름을 **전부** 요구하도록 강화한 뒤 C01·C02가 각각 지목됐다. ⓑ 경계 주입 첫 회차에서 junit 클래스명에서 파일 경로를 잘못 뽑아(`tests/infra.py`) 실제로는 RED였던 B01이 "생존"으로 판정됐다 — 파싱을 고치고 재실행했다. 하네스의 오판정이 가드의 오판정으로 읽힐 뻔했다.

### 6-2. Core 경계 위반 주입(Gate E) — 2종 전건 지목 가드 RED

| 주입 | 지목 가드 | 결과 |
|---|---|---|
| B01 Core(`l2.mastery_tracking`)에 `subject == "math"` 비교 추가 | `tests/infra/test_eos_core_boundary_probe.py` | RED. **`lint-imports`는 exit 0(못 본다)** — 위 §5-1의 단일 보호 지점이 실측으로 확인됐다 |
| B02 Core(`api.me`)에 `import whymath_backend.l4.subject_adapter_math` 추가 | `lint-imports` | RED(exit 1). `tests/infra`의 3개 파일(계약 배선·프로브·의존 방향)도 함께 RED — 이중 보호 |

기준선은 주입 전 `lint-imports` exit 0 · `tests/infra` 경계 테스트 185건 전건 통과였다.

### 6-3. 도달성 동결

census 테스트를 `tests/infra/test_gate_harness_marker_reach_wiring.py`의 `GATE_HARNESS_PATHS`에 올렸다. 이 테스트는 `backend-migrations` 잡의 `pytest -m integration` 마커 수집으로 돈다(파일명이 워크플로에 안 보인다). `pytestmark`를 떼는 주입에서 `test_gate_harnesses_carry_the_integration_marker`가 RED(1 failed)였고 원복은 바이트 동일이다.

## 7. 미이행과 한계 (숨기지 않는다)

1. **"CI에서 RED"(acceptance ④) 미실증.** 위 §6은 전부 **로컬 실행**이다. CI는 `pull_request`·`main` push·merge queue에서만 도는데 이 세션은 PR을 열지 않았다. 따라서 이번 census 테스트와 새 하네스가 실 CI에서 도는지·주입이 그 스텝에서 RED가 되는지는 **확인하지 않았다.** 가드 자체의 CI RED는 선행 `EOS-117`이 PR #1215로 실측했다(위반 주입 run `35421591228` · 원복 run `35421783017`) — 그 증거를 이번 주입의 증거로 읽지 않는다.
2. **Python 3.13.16으로 측정했다.** CI는 3.12다. 이 변경은 런타임 코드를 0줄 바꾸고(`src` 무변경) 테스트·스크립트만 추가했으나 인터프리터 차이는 존재한다.
3. **테스트 계정 기준.** 실사용자·실기기 세션이 아니다. 판정문에 이 사실을 유지한다.
4. **C09는 간접 검출**(§6-1). `problem_attempted`는 다른 이벤트의 전제라 끊으면 여정이 먼저 무너진다 — 역할 부재로 잡히지 않는다.
5. **전건 RED는 커버리지가 아니다.** 주입하지 않은 분기(예: 생산자는 있으나 학습자 결합이 끊기는 `UNJOINABLE` 전환, `occurred_at` 폴백 방향, 시간창 절단)는 이 문서가 보증하지 않는다.
6. **전체 백엔드 스위트**는 이 문서 작성 시점에 돌리지 않았다. 결과는 PR/보고에 별도로 적는다.

## 8. 후속

- `F2`·`F3`: 소유 태스크가 없어 `P3-27-concept-viewed-and-trace-field-gaps`로 후속 등재했다(`backlog.py add`로 등재 · 중복 검색은 역할 기반으로 했고 "내가 찾은 방법으로는 0건"이다). 범위는 **콘텐츠 열람 로그 좌석 또는 `concept_selected`의 개념 채움 결정** + **트레이스 추적 필드 보강 판정**이다. `content_version`은 `EOS-47` 소유이므로 포함하지 않는다.
- Phase 3 규율에 따라 이번 PR은 새 Entity·DB 스키마·새 Agent를 추가하지 않았다. `LearningEvent` 봉투도 바꾸지 않았다(F1은 채우지 않고 동결).

## 9. 재현

실 PG가 있는 환경(`src/backend` 기준, CI `backend-migrations` 잡과 같은 변수):

```bash
export WHYMATH_DATABASE_URL=postgresql+asyncpg://whymath@127.0.0.1:5432/whymath
export WHYMATH_RUN_INTEGRATION=1 WHYMATH_DB_DISABLE_POOL=1
python -m alembic upgrade head
python -m pytest -c src/backend/pyproject.toml --rootdir=src/backend \
  tests/backend/scenarios/test_gate_d_event_role_census.py -s
python scripts/ops/verify_gate_de_discrimination.py --suite all
```
