# EOS-119 — Phase 2 시나리오 회귀 스위트 SCENARIO-001~010 (P-13)

> 판정 기준: 작업 트리 기준 `claude/admiring-wright-obipz1` HEAD `e48b8936`(main `b9447c90` 이전 분기) + 이 태스크의 미커밋 변경.
> 이 문서의 실행 수치는 전부 **로컬 실측**이다(PostgreSQL 16.x + pgvector 0.6.0 · Python 3.12.3 · 4코어 컨테이너).
> CI 실행 증거(acceptance ③)는 PR이 열린 뒤 채운다 — 아래 §4에 무엇을 확인해야 하는지 적어 두었다.

## 1. 산출물

| 경로 | 내용 | 실행 좌석 |
|---|---|---|
| `tests/backend/scenarios/test_phase2_scenario_regression_suite.py` | SCENARIO-001~010, 테스트 함수 10개(시나리오당 1개) · `@pytest.mark.integration` | CI `backend-migrations` 잡의 `Pytest (통합테스트 — 실 PG·l3 외부서비스 제외)` 스텝(PR·push 모두) |
| `tests/backend/scenarios/test_scenario_suite_guard.py` | 스위트 형태 계약을 AST로 검사(hermetic): 시나리오 10종이 각각 테스트 1개인지, `integration` 마커, skip/xfail 위장 금지, 학습자 상태 직접 쓰기 0, 원시 SQL은 SELECT/DELETE만 | CI `backend` 잡의 `Pytest (with coverage)` |
| `scripts/ops/verify_scenario_suite_discrimination.py` | 서빙 코드 회귀 주입 하네스 10종(주입 실재·RED·sha256 원복 단언, 교차 검출 행렬) | 수동 실행(실 PG 필요) — §5 |

헬퍼는 **재구현하지 않았다.** 페르소나 하네스(`tests/backend/api/test_e2e_persona_journeys.py`)를 경로 로딩으로 빌려 쓴다. 그 하네스는 다시 Week 2·Week 1 하네스를 빌려 쓴다. 헬퍼 계약 22개는 튜플로 고정해 두었고, 하나라도 사라지면 수집 단계에서 이름을 지목하며 실패한다. 이 스위트에만 새로 생긴 조립기는 두 개다.
- `_answered_problem`: 기대정답이 수치인 문항. Week 2 `_problem`의 정답은 sentinel 문자열이라 코치 완료 판정의 입력으로 쓸 수 없다.
- `_read_rows`: 읽기 전용 SELECT. 공개 표면이 내지 않는 `used_hint`·`hint_usage` 값을 읽는 데만 쓴다.

**시딩 경계**: 학습자 상태는 전부 HTTP 호출의 부수효과로만 만든다. ORM으로 넣는 것은 저작 콘텐츠(concept·atom_node·concept_edge·problem·problem_concept·skill_node)뿐이며, 이 경계는 가드가 AST로 강제한다.

## 2. 대조표 — 시나리오 × 기존 자산 × 처분

acceptance ①은 "덮이는 시나리오는 신설하지 않고 확장한다"고 적는다. 한편 같은 항목과 P-13 지시는 "10종 **각각** 하나의 시나리오 테스트"를 요구한다. 두 요구를 함께 지키려고 이렇게 처분했다. 기존 테스트 본문은 고치지 않는다. 대신 그 헬퍼와 단언 축을 재사용해 독립 시나리오 테스트로 **승격하고 확장**한다. 기존 테스트에 단언을 덧붙이는 방식은 택하지 않았다. 앞 마디에서 멈추면 뒤 마디가 판정되지 않고, 시나리오 식별자도 흐려지기 때문이다.

acceptance가 이름을 댄 기존 e2e 자산 4건 중 둘은 시나리오 10종과 겹치는 축이 없었다.
- `test_eos_anchor_e2e_a4`: 생성 배치 → SymPy 게이트 → 코퍼스 → 검수 큐 파이프라인
- `test_e2e_pedagogy_pilot_integration`: DSL 컴파일 → 팩 → 런타임 조립

`test_e2e_suneung_loop_integration`은 수능 모드 관통이라 001과 일부 표면만 겹친다. 실제로 겹치는 것은 아래 표의 자산들이다.

| SCENARIO | 가장 가까운 기존 자산 | 기존이 보는 것 | 이 스위트가 새로 단언하는 상태 변화 | 처분 |
|---|---|---|---|---|
| 001 신규 학생 정상 학습 | `test_week1_gate_closed_loop` · `test_e2e_vertical_slice_integration` · 페르소나 A | 1사이클 연결성(오답 1건) · 숙달 상승 | 학습 상태 원장 `NEW→LEARNING→ASSESSING→PRACTICING` · `entered_learning_from=NEW` · 추천 근거가 `cold_start`에서 `measured_mastery`로 바뀌고 그 값이 LearnerState와 같음 · 첫 측정 이벤트 `mastery_before=None` | 신설(헬퍼 재사용) |
| 002 낮은 진단점수 | 페르소나 A-상한확정(`..._confirms_at_item_cap`) | 대부분 **정답**인 진단의 확정 | 대부분 **오답**인 진단 확정 → `assessment.weak_points`에 개념이 들어감 · `provisioned_by=diagnosis_capture` · 숙달 < 0.4 · 약점 목록 · θ 하강 · 추천이 쉬운 문항으로 내려감 · 근거 `prerequisite_gap` | 신설 |
| 003 선수개념 결손 | 페르소나 B ②~⑤ | 반복 오답 → 선수 결손 → 추천 하강 | 선수 **미측정**일 때는 결손이 아님(변별) → 오답 1건으로 결손 확정 → `practice_prerequisite`·target=선수 · **EOS-127 공백 동결** | 확장(B 축 재사용) |
| 004 동일 오개념 반복 | 페르소나 C ②③ · Week 2 | 2회 반복에서 confidence 상승 | 3회 동안 confidence **단조 증가** · 회차마다 그 시도에서 탐지(`ran_with_candidates`) · 정책이 R3에서 **R5로 넘어감**(규칙 우선순위의 상태 증거) | 확장 |
| 005 힌트 후 정답 | 관통 테스트 7~11(코치 완료) · Week 3 ④(힌트 사다리) | 힌트 없는 코치 완료 · 힌트 사다리 따로 | 막힘 → 힌트 적재 → 정답 풀이는 **돌아보기 대기**(적재 0) → 돌아보기 후 attempt 1행·숙달 첫 측정 · **공백 동결 2건** | 신설(두 자산 결합) |
| 006 AI Tutor 질문 | Week 3 ④ · 관통 5(다턴) | 좌절 신호에 따른 사다리 상승 | 풀이 없는 **질문**은 채점 상태를 움직이지 않음(시도 0·숙달 미측정·`NEW`) · 대화·턴 영속 · 새 대화가 **원장의 직전 단계를 이어** 오름 | 신설 |
| 007 mastery threshold 통과 | 페르소나 A ④ · P-11 H4 | 숙달 상승 방향 · 근거=상태 값 | **궤적 전체**에서 `(숙달, 근거)` 쌍이 경계 규칙과 일치 · 경계 아래·위 관측을 각 1건 이상 요구 · 경계 통과 시 약점 목록에서 제외 · (2026-09-25 `EOS-124`) 후행 개념을 심어 경계 통과 회차에 **다음 개념 문항**이 실제로 나오는지까지 판정 | 신설 |
| 008 다음 concept 이동 | 페르소나 A ⑤⑥ | `advance_next` · 소진 후 이동 · EOS-124 동결 | 확신 있는 정답 → R1 · `ADVANCING` · `ADVANCE_TO_NEXT_CONCEPT`(상태 머신 축) + A의 이동 · (2026-09-25 `EOS-124` 해소) 미시도 현재 개념 문항이 남아 있어도 **다음 개념 문항을 선택**으로 받음 | 확장 |
| 009 세션 종료 후 재접속 | 없음(관통 테스트가 `session_id is None`만 동결) | — | 대화 종료(`ended_at`·`resolution`) → **새 앱 인스턴스 + 재로그인** → 같은 user_id · 종료 상태·턴 보존 · 숙달·활성 오개념 동일 · 시도 문항 재추천 없음 · `LearningSession` 0행 동결(S3-16 ③ 결정) | 신설 |
| 010 학습 상태 복구 | 없음 | — | `REMEDIATING` 학생을 새 앱에서 다시 보면 현재 상태·전이 이력·숙달·오개념·가설 confidence가 동일 · 이어 풀면 `from_state=REMEDIATING`(NEW에서 재시작하지 않음) · 옛 이력 보존 | 신설 |

## 3. 시나리오별 상태 — 통과 / 정직한 공백 동결

10종 **전건 통과**(현행 코드 기준)다. `skip`으로 위장한 시나리오는 없다. 가드가 `pytest.skip` 호출을 1곳(PG 미도달 시 판정 불가)으로 제한하고 `xfail`·`skipif`는 금지한다. 코드 갭은 시나리오 **안의 한 마디**에서 현행 동작 단언으로 동결했다. 고쳐지면 그 단언이 실패하고, 실패 메시지가 승격 방법과 소유 태스크를 가리킨다.

| 동결 | 시나리오 | 현행 동작(실측) | 소유 |
|---|---|---|---|
| ⓐ R4 미발화 | 003 | 선수 결손이 확정된 상태에서 원래 개념에 오답을 내도 정책은 `R6-wrong-undiagnosed`(target 없음). `prerequisite_gap_concept_ids` 생산자가 서빙 경로에 배선되지 않았다(`api/me.py` 주석이 스스로 밝힘) | `EOS-127`(todo) |
| ~~ⓑ 정책·선택 축 불일치~~ (해소 2026-09-25) | 008 | 숙달한 뒤 `action=advance_next`인데, 고른 문항과 `target_concept`은 아직 현재 개념이었다. `EOS-124`가 설명을 전달 문항에 정렬하면서 올바른 값 단언으로 **승격**했다. 같은 변경으로 002의 근거 단언은 `current_concept`·`intent_resolution=unsupported`(선수 엣지가 없는 픽스처)로 정밀화됐다 | `EOS-124`(해소) |
| ⓒ 힌트 귀속 공백 | 005 | 힌트를 받은 뒤 코치 대화로 낸 정답 attempt의 `used_hint`가 NULL이고 `hint_usage`가 0행이다. `HintUsage(` 생성 writer가 `src/` 전체에 0건이다(grep 실측). 그래서 힌트 받은 정답과 스스로 푼 정답이 숙달 갱신에서 구별되지 않는다(기본 추정기 `bkt-v1`은 힌트 축을 읽지 않고, 가산 규칙 `HINT_GAIN_FACTOR`는 기본 추정기가 아니다) | `EOS-133-coach-hint-usage-attribution` (2026-09-24 등재) |
| ⓓ 코치 완료 경로에서 상태 머신 미실행 | 005 | 코치 대화로 문제를 완료해도 `/v1/me/learning-state`가 `NEW`·전이 0건 그대로다. `api/coach.py::_complete_problem`은 attempt·숙달·이벤트를 적재하지만 `advance_on_attempt`를 부르지 않는다(`coach.py`에서 `learning_state`·`record_transition` grep 0건). `/v1/me/attempts` 경로와 비대칭이다 | `EOS-134-coach-completion-state-machine` (2026-09-24 등재) |
| ⓔ 학습 세션 행 0 | 009 | `GET /v1/me/sessions == []`. `LearningSession(` 생성자 0건 | 결함이 아니다 — `S3-16` acceptance ③의 **미신설 결정**. 결정이 바뀌면 단언이 알린다 |

승계 2건(ⓒ·ⓓ)은 `backlog.py add`로 `EOS-133`·`EOS-134`에 등재했다. 착수 전 식별자 검색 범위는 다음과 같다. `backlog/tasks`에서 `코치 완료|_complete_problem|coach_completion` × `상태 머신|learning_state|advance_on_attempt` 교집합이 0건이었다. `hint_usage.*writer|힌트 사용.*귀속|used_hint.*writer`도 0건이었다. `EOS-45`(done)는 스키마·ORM만 만들었고 writer는 만들지 않았다. `S4-11`(todo)은 힌트 *본문* 생성기라 귀속 writer와는 다른 축이다. "내가 찾은 방법으로 0건"이다.

**PED-36 ⑨의 2026-09-16 분류 재확인(main 현재 코드)**:
- 009·010은 "LearningSession writer 0이 원인"으로 분류돼 있었다. writer 0은 여전히 사실이다. 그러나 두 시나리오는 그 좌석 없이 **성립한다.** 009는 실재하는 세션 좌석인 코치 대화(`PATCH /v1/me/dialogues/{id}/end`)로, 010은 학습 상태 원장(`learning_state_transition`, EOS-105)으로 성립한다. 코드 갭이 아니라 좌석을 잘못 지목한 테스트 갭이었다.
- **정정(2026-09-25 EOS-131)**: 표의 ⓔ(학습 세션 행 0 동결)는 해소됐다 — 서버 30분 유휴 규칙 writer(`l2/learning_session_writer`)가 신설돼 SCENARIO-009 ④는 "재접속 뒤에도 같은 학습 세션"을 단언하는 정상 동작 단언으로 승격됐다. 위 표의 ⓔ 행은 판정 당시(`main` 578fa9d2 이전) 기록으로 둔다.
- 005는 "힌트 본문 생성기 부재(S4-11)가 선행"으로 분류돼 있었다. 힌트 **본문**이 없어도 힌트 사다리(`hint_level`·`hint_provided` 원장)와 코치 완료가 실재하므로 시나리오는 성립한다. 남은 코드 갭은 본문이 아니라 **귀속**(ⓒ)과 **상태 머신 비대칭**(ⓓ)이다.

## 4. CI 실행 좌석 (acceptance ③·④)

- **소유 잡**은 `backend-migrations`(`.github/workflows/ci.yml` "backend — 마이그레이션·통합 (실 PG)")의 `Pytest (통합테스트 — 실 PG·l3 외부서비스 제외)` 스텝이다. `src/backend`에서 bare `pytest -m integration --ignore=../../tests/backend/l3`를 실행한다. 조건은 `(github.event_name != 'pull_request' || needs.changes.outputs.backend == 'true') && github.event_name != 'schedule'`이다. **e2e-nightly(schedule 전용)에는 넣지 않았다.**
- **수집 실측(로컬 · CI와 같은 형태)**: `src/backend`에서 bare `pytest -m integration --ignore=../../tests/backend/l3 --collect-only -q`를 실행했다. 결과는 exit 0 · `369/11539 tests collected`였고, `scenarios/test_phase2_scenario_regression_suite.py::test_scenario_00N_*` 10건이 모두 목록에 있었다.
- **주의(PR 경로 조건)**: 이 잡은 PR에서 `changes.outputs.backend == 'true'`일 때만 돈다. `tests/backend/**`가 그 필터에 걸리는지는 PR CI에서 잡이 `skipped`가 아닌지로 확인해야 한다. **이 세션은 push하지 않았으므로 CI 증거는 아직 없다.** PR에서 확인할 항목은 세 가지다.
  1. 잡 `backend — 마이그레이션·통합 (실 PG)`의 conclusion이 `success`인지(skipped가 아닌지)
  2. 스텝 `Pytest (통합테스트 — 실 PG·l3 외부서비스 제외)`가 실행됐는지
  3. 로그에 `scenarios/test_phase2_scenario_regression_suite.py ..........`(10 passed, skip 0)가 찍혔는지
- **실행 시간과 PR/nightly 분리 판단(초 단위 실측)**:
  - 기준 CI 실측(main `b9447c90` · run 35955631670): 잡 전체 04:26:22→04:34:21로 **7분 59초**, 통합 pytest 스텝 04:27:52→04:34:18로 **386초**. 잡 상한 `timeout-minutes: 12`(720초).
  - 로컬 실측: 스위트 단독 약 30초. 이 스위트를 포함한 전체 통합(`pytest -m integration --ignore=../../tests/backend/l3`)은 **368.10초**(357 passed · 13 skipped, 벽시계 376초).
  - 시나리오별 call 시간(로컬, 초): 001 1.60 · 002 6.26 · 003 2.43 · 004 2.40 · 005 2.00 · 006 1.71 · 007 1.93 · 008 2.71 · 009 2.35 · 010 1.99 (pytest `--durations=0` call 구간 · 스위트 단독 `10 passed in 28.02s`, 벽시계 30.2초)
  - 판단: 10종을 모두 합쳐도 약 30초로, 잡 여유(720 − 479 ≈ 241초)의 약 12%다. 그래서 **10종 전부 PR용**으로 남기고 nightly 분리는 하지 않았다. 가장 긴 002(진단 확정에 상한 20문항 채점이 필요)도 10초 미만이다. 분리 기준을 "시나리오 1건 > 60초 또는 합계가 잡 여유의 50% 초과"로 두면 둘 다 해당하지 않는다. 이 기준은 이 문서가 정한 것이며 규약이 아니다.

## 5. 회귀 주입 검증 (acceptance ⑤)

하네스는 `scripts/ops/verify_scenario_suite_discrimination.py`다. 서빙 코드(`src/backend/whymath_backend`)의 원본 절을 정확히 1건 치환해 주입한다. 매 주입마다 네 가지를 단언한다: 치환 대상 count == 1, `mutated != original`, 주입 후 sha256 ≠ 원본, 원복 후 sha256 == 원본(`shutil.copy2` 바이트 백업, git 원복 미사용). 판정은 junitxml에 기록된 시나리오별 결과로 낸다. 기준선(주입 전) 10/10 통과를 선행 조건으로 두며, 기준선이 실패하면 exit 1이다.

| 주입 | 위치 | 주입 내용 | 지목 시나리오 | 결과 | 함께 RED |
|---|---|---|---|---|---|
| M001 | `l2/learning_state_machine.py` `ensure_learning_context` | 학습 진입 트리거를 `None`으로 → NEW에서 학습 진입 전이 미적재 | 001 | **RED** | 003·004·008·010 |
| M002 | `api/me.py` 진단 캡처 조립 | `weak_point_items = []` | 002 | **RED** | — |
| M003 | `l2/prerequisite_recommendation.py` | `weak_only` 결손 필터 무력화(`if False`) | 003 | **RED** | — |
| M004 | `l2/learning_state_policy.py` R5 | `consecutive_failures >=` → `>`(off-by-one) | 004 | **RED** | — |
| M005 | `api/coach.py::_complete_problem` | 개념 숙달 전파 호출 제거 | 005 | **RED** | — |
| M006 | `api/coach.py::create_session` | 직전 힌트 단계 원장 조회 결과를 `None`으로 | 006 | **RED** | — |
| M007 | `l2/recommendation_contract.py::select_reason_type` | 경계 `<= 0.7` → `<= 0.95` | 007 | **RED** | — |
| M008 | `l2/learning_state_policy.py::_is_high_confidence` | 항상 `False` | 008 | **RED** | — |
| M009 | `api/me.py::end_my_dialogue` | `row.resolution = body.resolution` 제거 | 009 | **RED** | — |
| M010 | `l2/learning_state_machine.py::get_current_state` | 원장 미조회, 항상 `INITIAL_STATE` | 010 | **RED** | 001·003·004·008 |

최종 실행 exit 0 — 10/10 RED, 원복 10/10 바이트 동일.

**실측 경위(생존 1건 → 픽스처 보강)**: 초판 M006은 `append_turns`(대화 안 두 번째 턴)의 원장 조회를 끊었는데 **GREEN(생존)**이었다. 대화 안에서는 `derive_polya_state`가 턴 메타에서도 사다리를 복원하므로, 원장 읽기를 끊어도 사다리가 오른다. 즉 006의 ② 마디는 원장 읽기를 한 번도 밟지 않았다. 원장이 **유일한** 근거가 되는 자리(새 대화의 첫 턴)를 006 ④로 추가했고, 그 자리의 원장 조회를 끊는 M006으로 교체해 RED를 확인했다. 초판 주입도 보강 뒤 다시 확인했다. 여전히 **생존**(10 passed)이며, 아래 "안 본 분기" ①로 남긴다.

**부수 실측(하네스가 찾은 거짓 실패)**: 초판 009에는 "재접속 토큰 ≠ 이전 토큰" 단언이 있었다. JWT `iat`가 초 단위라 같은 초 안에 재로그인하면 같은 토큰이 나온다. 무작위 순서 4회 중 1회 거짓 실패했고, 뮤테이션 하네스의 교차 RED 열에서 009가 무관한 주입(M003·M006·M008)에 함께 RED로 나타나 발견했다. 그 단언을 제거하고 동일인 판정을 user_id로 옮겼다. 수정 뒤 교차 RED 열에서 009는 사라졌다.

### 안 본 분기 (전건 RED ≠ 커버리지)

전건 RED는 **주입 목록에 올린 10개 절**을 스위트가 잡는다는 뜻일 뿐이다. 아래 분기들은 이 스위트가 밟지 않거나, 밟아도 판정하지 않는다.

1. **대화 안 턴의 힌트 원장 조회**(`append_turns`의 `_prev_hint_level_for`): 턴 메타와 겹쳐 대화 안에서는 판정력이 없다(위 생존 실측). 턴 메타가 비어 있는 이어 턴이 실제로 존재하는지는 확인하지 않았다.
2. **상태 머신 규칙 R4**: 서빙 경로에서 매치되지 않으므로 003은 R6 현행만 동결한다. R4의 target 해소는 전혀 보지 않는다(EOS-127).
3. **`rejected_transition` 경로**: 모든 시나리오가 `None`만 본다. 전이표가 거부하는 입력(`ADVANCING`에서 곧바로 평가 등)은 시나리오에 없다. 008은 `ADVANCING` 다음 제출이 거부되지 않는다는 것만 암묵적으로 통과할 뿐, 단언하지 않는다.
4. **정답 회차의 오개념 감쇠**(EOS-123): 010 ③은 복구 후 정답을 내지만 confidence 변화를 단언하지 않는다(페르소나 C ⑥이 동결을 소유).
5. **수능 모드·`purpose=learning` 추천 정책**: 모든 시나리오가 기본 CAT 정책(`prioritize_weak_concepts=true`)만 쓴다. `SuneungRecommendationPolicy`는 0회 경유한다.
6. **미성년 학생·동의 게이트**: 로그인 경로의 데모 신원은 성인이다. 14세 미만 `ConsentedUser` 거부 분기는 밟지 않는다.
7. **코치 오답 완료(`final_answer_incorrect` → 재고 발화)**: 005는 정답 도달만 본다.
8. **진단 캡처 idempotency**(`already_captured_window`): 002는 첫 캡처만 본다.
9. **스킬 축 숙달**: 시나리오들은 개념 숙달만 단언한다. 스킬 숙달은 Week 2 게이트가 소유한다.
10. **동시성·재시도**: 같은 학생의 병렬 제출이나 네트워크 재전송 중복은 범위 밖이다.
11. **공유 PG 후보 풀 오염**: 추천 단언(001·002·003·007·008)은 다른 통합 테스트가 심은 문항이 후보에 섞이지 않는다고 전제한다. 페르소나 하네스와 같은 전제이며, 로컬 전체 통합 실행 1회(357 passed)에서는 성립했다.

## 6. 로컬 실행 명령과 exit code

```bash
# 환경(1회): PostgreSQL 16 + apt postgresql-16-pgvector(0.6.0), initdb(postgres 사용자) → role/db whymath(trust)
cd src/backend
export WHYMATH_DATABASE_URL=postgresql+asyncpg://whymath@127.0.0.1:5432/whymath
alembic upgrade head                                                     # exit 0
export WHYMATH_RUN_INTEGRATION=1 WHYMATH_DB_DISABLE_POOL=1
pytest -m integration --ignore=../../tests/backend/l3 --collect-only -q  # exit 0 · scenarios 10건 수집
pytest -m integration --ignore=../../tests/backend/l3                    # exit 0 · 357 passed · 13 skipped · 368.10s
python -m pytest -c pyproject.toml -m integration ../../tests/backend/scenarios   # 스위트 단독
cd ../.. && python scripts/ops/verify_scenario_suite_discrimination.py  # exit 0 · 10/10 RED
```

최종 실측 exit code(모두 로컬, 출력 무절단·exit 판정):

| 검사 | 명령(CI 잡 기준) | 결과 |
|---|---|---|
| 통합 스위트 단독 | `python -m pytest -c pyproject.toml -m integration ../../tests/backend/scenarios` | exit 0 · 10 passed(+가드 5 deselected) · 28.02s |
| 통합 전체(CI 형태) | `pytest -m integration --ignore=../../tests/backend/l3` | exit 0 · 357 passed · 13 skipped · 368.10s |
| 통합 수집(CI 형태) | 위 + `--collect-only -q` | exit 0 · scenarios 10건 수집 |
| 회귀 주입 | `python scripts/ops/verify_scenario_suite_discrimination.py` | exit 0 · 10/10 RED · 원복 10/10 바이트 동일 |
| hermetic backend(CI 형태·커버리지 옵션 제외) | `pytest -m "not corpus_authoring" -n auto --dist loadfile` | exit 0 · 14261 passed · 387 skipped · 1 xfailed |
| 가드 자체 주입 4종 | skip 추가·`_read_rows` INSERT·시나리오 함수 개명·학습자 행 생성자 | 4/4 RED(초판 가드는 `_read_rows` SQL을 못 봐 INSERT 주입이 GREEN → SQL 싱크 확장 후 RED) |
| ruff / black (backend 잡) | `ruff check . ../../tests/backend` · `black --check --line-length 100 . ../../tests/backend` | exit 0 · exit 0 |
| mypy / import-linter (backend 잡) | `mypy --strict whymath_backend` · `lint-imports` | exit 0(707 파일) · exit 0(4 kept) |
| ruff / black (harness-integrity 잡) | `ruff check scripts tests/harness` · `black --check --line-length 100 scripts tests/harness` | exit 0 · exit 0 |
| mypy --strict (신규 3파일, CI 비대상 · 참고) | `mypy --strict tests/backend/scenarios scripts/ops/verify_scenario_suite_discrimination.py` | exit 0 |
| infra-contracts · harness-integrity 테스트 | `python -m pytest tests/infra -q` · `python -m pytest tests/harness -q` | exit 0(1742 passed) · exit 0(977 passed) |

