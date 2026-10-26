# P3-14 — Phase 3 지표 7종 일괄 CLI 구현·검증 기록 (2026-10-09)

> **판정 기준: origin/main `713512bc`** (P3-13 머지 직후). 작업 트리는 그 위의 claim 커밋 `21c2955b` + **미커밋** 변경이다
> (커밋·푸시·PR 은 Kiki 검토 후 — 세션 지시). 이 문서의 수치는 전부 아래 명령을 **실제로 실행해 얻은 값**이다.
>
> 정본 계약 문서: `docs/standards/phase3_metrics_contract.md` · 집행 코드: `src/backend/whymath_backend/ops/phase3_metrics.py`

## 1. 한 줄 결론

7종이 `python -m whymath_backend.ops.phase3_metrics` **한 명령**으로 산출되고, 합성 대조 세계에서 지표마다 위반 주입에
**그 지표만** 반응한다(자가 점검 18건 전건 OK · pytest 122건 통과 · 핵심 판정 뮤테이션 28종 전건 RED). 오늘의 실 코퍼스에서
종합은 **측정 실패(exit 2)** 이며 이것이 정상 동작이다(⑤ DB 부재·⑥ payload 부재·⑦ 목표 미정).

## 2. 산출물

| 파일 | 내용 |
|---|---|
| `src/backend/whymath_backend/ops/phase3_metrics.py` | 7종 일괄 CLI · 3상태 모델 · 종합 규칙 · 합성 세계/위반·미측정 주입 표 · `--self-check` |
| `tests/backend/ops/test_phase3_metrics.py` | 단위·주입·CLI·실 코퍼스 배선 테스트 |
| `tests/infra/test_phase3_metrics_wiring.py` + `.github/workflows/ci.yml` | `backend` 잡 게이트 스텝 1개 + 배선 동결 |
| `scripts/analysis/eos_feature_inventory_v2.py` | 신규 모듈 `ops.phase3_metrics` 를 새 행 `WM-O-917` 에 파일 단위 귀속 |
| `src/backend/whymath_backend/ops/declared_unwired_audit.py` | **stale-waiver 5건 제거**(§6-② — 이 변경이 일으킨 `declared-unwired-audit` 잡 RED 의 해소) |
| `docs/standards/phase3_metrics_contract.md` | 전 평면 구분표 · 7종 정의/출처/흡수 · 목표 미확정 · 불일치 기록 |
| `docs/reviews/p3_14_phase3_metrics_2026-10-09.md` | 이 문서 |

P3-02 모듈(`l1/standards/phase3_coverage.py`)은 **수정하지 않았다**(그 테스트 100건 보호). 공개 함수 `load_corpus`·`evaluate`·값 객체만
썼고, 부족했던 것은 한 가지다 — 공개 API 가 문항 **원본 행(verify 재료)** 을 돌려주지 않아 ④ 를 위해 같은 문제은행을 한 번 더 읽는다
(glob 상수는 복제하고 `test_problem_glob_matches_the_p3_02_loader` 가 P3-02 의 것과 같음을 동결).

## 3. 실 코퍼스 실측 (명령 3종 + 자가 점검)

실행 환경: 이 세션의 격리 venv · PostgreSQL **없음**(⑤ 는 접속 거부). 코퍼스 14,034 문항 행 · 대표 과정 승인 문항 413건.

### 3-1. `python -m whymath_backend.ops.phase3_metrics --no-db` → **exit 2**
(run_id `f8456097a0a2` · 관측 시각 2026-10-09T13:57:19Z · 표본 기준 live)

| # | 지표 | 상태 | 값 | 목표 | 비고 |
|---|---|---|---|---|---|
| ① | Curriculum Coverage [대표 과정 10노드] | 미달 | 3/10 = 30.0% | ≥ 98.0% | 7노드는 승인 PRIMARY 문항 0건 |
| ② | Concept Completeness [핵심 개념 10개] | 미달(확정) | 0/10 = 0.0% | ≥ 95.0% | hint 측정 불가·교수 연결 10개 전부 끊김 → 구간 상한 0 이라 미달 확정 |
| ③ | Problem Coverage [스킬 8종] | 미달 | 6/8 = 75.0% | ≥ 95.0% | 0건 스킬: `skill.pattern-generalization`·`skill.word-problem-modeling` (**조사 기준선 6/8 과 일치**) |
| ④ | Solution QA Pass [승인 문항 413건 재검증] | 충족 | 413/413 = 100.0% | ≥ 99.5% | 통과/실패/검증 불가 = 413/0/0 · 임계는 스코어카드 흡수 |
| ⑤ | Learning Loop Success | **미측정** | — | ≥ 0.95(Wilson 하한) | `--no-db` 이고 입력 없음 |
| ⑥ | Critical Defect [Hard Gate 5종] | **미측정** | — | 0건 | payload 없음 → 5게이트 전부 판정 불가 |
| ⑦ | Graph Connectivity Coverage [핵심 개념 10개] | **목표미정** | 0/10 = 0.0% | (명세 null) | PASS/FAIL 없음 |

합계: 충족 1 · 미달 3 · 미측정 2 · 목표미정 1 / 전체 7. 종합: **측정 실패 → exit 2**. 소요 약 20초(④ 재검증이 약 14초).

### 3-2. DB 수집 시도(`--no-db` 없이) → **exit 2**
(run_id `c61f320a18af`) ⑤ 가 `수집 실패(ConnectionRefusedError)` 로 **미측정**이며 예외 타입명이 출력·증거 NDJSON 에 남는다. 나머지 6종은 3-1 과 같다.

### 3-3. 합성 숫자를 주입한 실행 → **exit 1** (미측정 0 이 되면 위반이 보이는 경로의 실증)
`--no-db --sample-basis synthetic --input <루프 200/200> --hard-gate-input <대조 payload>` (run_id `243416e6a222`):
⑤ 충족(Wilson 하한 0.9867 ≥ 0.95)·⑥ 충족(0/5)이지만 **`기준: 주입값(--input) — 측정이 아니다`·`표본 기준: synthetic`·
`합성 표본` 경고가 각인**된다. 미측정이 0 이므로 종합은 7종 전부 측정됨 + ①②③ 미달 → **exit 1**. 이 실행은 실측이 아니라
종료 코드 경로(2 → 1)의 실증이다.

### 3-4. `--self-check` → **exit 0** (약 4초 · DB 0 · LLM 0)
점검 18건 전건 OK: 대조군 1 · 위반 주입 7 · 미측정 주입 7 · 목표 미정 1 · 경계 1 · 종합 규칙 1.

## 4. 위반 주입 반응 검증 (acceptance ②)

### 4-1. pytest — `tests/backend/ops/test_phase3_metrics.py`
`python -m pytest -c src/backend/pyproject.toml --rootdir=src/backend tests/backend/ops/test_phase3_metrics.py -p no:randomly` → **122 passed, exit 0**(약 20초). 배선 동결 `tests/infra/test_phase3_metrics_wiring.py` 6 passed. 테스트 순서 의존은 역순·무작위 시드 3종으로 합계 128건 전건 통과를 확인했다(이 venv 에는 pytest-randomly 가 없어 별도 셔플 플러그인을 썼다).

- 7종 각각 위반 주입 → 그 지표만 `measured/met=False`, 나머지 6종은 **서명(상태·충족·분자·분모) 불변**, 종합 exit 1.
- 성공 방향 대조군(주입 전 충족)을 매 주입 앞에 단언. 주입 헬퍼는 `mutated != original`·치환 대상 존재를 단언.
- 미측정 주입 7종 → 해당 지표 `unmeasured`·값/판정 없음·종합 exit 2. 대조군 세계는 지표 7종 전부 100%.
- 점추정 대 Wilson: 루프 190/200 은 점추정이 목표(0.95)와 같지만 Wilson 하한이 목표 아래 → 위반(점추정 판정이면 통과했을 입력).

### 4-2. 뮤테이션 검증 — 핵심 판정 한 줄씩 깨뜨려 RED 확인
하네스: 순수 Python(셸 미경유). 원복은 `cp` 백업 → `cp` 복원만 사용(git 계열 원복 미사용). 주입 전후 `mutated != original`·치환 대상
`count == 1`·쓰기 후 sha256 변경, **복원 후 sha256 동일**을 매 건 단언했고 전건 통과했다. 피검체가 도는 동안 트리를 바꾸지 않았다.
"pytest" 열 = `test_phase3_metrics.py`(`-x`) · "자가 점검" 열 = CI 게이트 스텝 `--self-check` 의 exit code.

| # | 주입한 것 | pytest | 자가 점검 | 처음 RED 가 된 테스트 |
|---|---|---|---|---|
| M01 | 판정 경계 `value >= target` → `>` | RED | RED | `TestBoundary::test_value_equal_to_target_is_met` |
| M02 | 종합: 미측정 분기 제거(미측정이 통과로 접힘) | RED | RED | `TestUnmeasured::test_each_unmeasured_injection_is_unmeasured_not_pass` |
| M03 | 종합: 위반이 미측정보다 먼저 | RED | RED | `TestUnmeasured::test_each_unmeasured_injection_is_unmeasured_not_pass` |
| M04 | 종합: 7종 완결성 가드 제거(빈 입력이 통과) | RED | RED | `TestComposite::test_not_exactly_seven_is_measurement_failure` |
| M05 | ④ skip 을 통과·분모에 계상 | RED | GREEN | `TestSolutionQa::test_skip_is_not_counted_as_pass` |
| M06 | 분모 0 가드 `<= 0` → `< 0` | RED | GREEN | `TestBoundary::test_zero_denominator_is_unmeasured` |
| M07 | ③ 덮인 스킬 `> 0` → `>= 0` | RED | RED | `test_violation_drops_exactly_that_metric` |
| M08 | ③ 목표를 명세에서 읽지 않고 0.95 하드코딩 | RED | GREEN | `TestProblemCoverage::test_target_is_read_from_the_spec_not_hardcoded` |
| M09 | ③ 미검수(pending) 문항도 계상 | RED | GREEN | `TestProblemCoverage::test_pending_problem_is_not_counted` |
| M10 | ⑤ 충족 여부를 항상 True | RED | RED | `test_violation_drops_exactly_that_metric` |
| M11 | ⑥ 판정 불가 게이트를 0건으로 접음 | RED | GREEN | `TestCriticalDefect::test_empty_payload_is_unmeasured_not_zero_defects` |
| M12 | ⑥ 충족 여부를 항상 True | RED | RED | `test_violation_drops_exactly_that_metric` |
| M13 | ② 미달 확정 분기 제거(확정 위반이 미측정으로) | RED | GREEN | `TestCompletenessInterval::test_unmeasured_hint_does_not_rescue_a_conce` |
| M14 | 목표 null 분기 제거(no_target 소멸) | RED | RED | `TestNoTarget::test_null_target_gives_value_without_verdict` |
| M15 | ④ 임계를 `1-ceiling` 흡수 대신 0.995 하드코딩 | RED | GREEN | `TestSolutionQa::test_target_follows_the_scorecard_when_it_changes` |
| M16 | ④ 스코어카드 방향(ceiling) 검증 제거 | RED | GREEN | `TestSolutionQa::test_wrong_direction_in_scorecard_is_a_config_error` |
| M17 | ④ 모집단 불일치 검사 제거 | RED | GREEN | `TestSolutionQa::test_population_mismatch_is_unmeasured` |
| M18 | 주입 적용 단언(`mutated != original`) 제거 | RED | GREEN | `test_noop_injection_is_rejected` |
| M19 | 자가 점검: '그 지표만' 격리 판정 무시 | RED | GREEN | `TestSelfCheck::test_self_check_fails_when_a_violation_injection_moves_` |
| M20 | 종료 코드 맵: 측정 실패 2 → 1 | RED | GREEN | `TestUnmeasured::test_each_unmeasured_injection_is_unmeasured_not_pass` |
| M21 | 주입 시 `--sample-basis` 필수 검사 제거 | RED | GREEN | `TestCli::test_injection_without_sample_basis_is_refused` |
| M22 | argparse 오류 종료코드 3 → 2 | RED | GREEN | `TestCli::test_argparse_errors_exit_3_not_2` |
| M23 | 예기치 못한 예외 종료코드 3 → 1 | RED | GREEN | `TestCli::test_unexpected_exception_is_exit_3_not_1` |
| M24 | ⑤ 주입값 라벨(basis) 제거 | RED | GREEN | `TestLearningLoop::test_injected_numbers_are_labelled_as_not_a_measurem` |
| M25 | 종합: 목표 미정 분기 제거(충족으로 접힘) | RED | RED | `TestNoTarget::test_composite_with_no_target_is_not_all_met` |
| M26 | ⑤ Wilson 하한 대신 점추정으로 판정 | RED | RED | `test_violation_drops_exactly_that_metric` |
| M27 | ⑤ 지표 완료 시 증거 emit 제거 | RED | GREEN | `TestCli::test_evidence_lines_carry_run_id_and_per_metric_progress` |
| M28 | ③ 명세 밖 스킬도 계수 | RED | GREEN | `TestProblemCoverage::test_only_spec_skills_are_counted` |
| C1 | ci.yml: 자가 점검 스텝 삭제 | RED (배선 테스트) | — | `test_phase3_metrics_self_check_step_exists_in_backend_job` |
| C2 | ci.yml: `--self-check` 제거(실 코퍼스 판정이 됨) | RED (배선 테스트) | — | `test_step_runs_the_self_check_in_module_form` |
| C3 | ci.yml: `continue-on-error: true` 추가 | RED (배선 테스트) | — | `test_step_has_no_continue_on_error` |
| C4 | ci.yml: 스텝에 `if:` 조건 추가 | RED (배선 테스트) | — | `test_step_is_unconditional` |
| C5 | ci.yml: `-m` 대신 파일 경로 직접 실행 | RED (배선 테스트) | — | `test_phase3_metrics_self_check_step_exists_in_backend_job` |
| C6 | ci.yml: 같은 스텝에 `--self-check` 없는 호출 1줄 추가 | RED (배선 테스트) | — | `test_no_ci_step_runs_phase3_metrics_without_self_check` |

**결과: 소스 뮤테이션 28종 중 pytest RED 28 · 생존 0. 자가 점검(CI 게이트 스텝 단독)은 28종 중 10종에서 RED.**
- 일부만 RED 이면 하네스를 의심하라는 규칙에 따라 점검했다: pytest 는 28/28 이므로 하네스는 정상이다. 자가 점검이 10/28 인 것은 **설계 범위의 차이**다 —
  자가 점검은 acceptance ②(7종 위반·미측정 주입 반응·경계·종합 규칙)를 CI 에서 상시 확인하는 hermetic 게이트이고, 입력 계약·CLI 종료
  코드·skip 의미·임계 흡수 같은 면은 같은 `backend` 잡의 pytest 가 지킨다(자가 점검 단독으로는 못 잡는 18종은 그 pytest 가 잡는다 — 표의 "pytest" 열).
- M10·M26(루프 판정)은 처음에는 자가 점검이 GREEN 이었다(주입이 150/200 이라 점추정으로도 위반) — 주입을 190/200(점추정=목표)으로 바꾼 뒤
  재실행해 둘 다 자가 점검 RED 를 확인했다.
- 배선 동결 테스트 자신도 뮤테이션으로 검증했다(C1~C6, 6종 전건 RED) — 스텝 삭제·`--self-check` 제거·`continue-on-error`·`if:` 조건·
  파일 경로 직접 실행·`--self-check` 없는 호출 추가.

### 4-3. 이 구현에서 일어난 일 — 정직 기록 (재발 방지 대상 아님·결과 설명)
- 첫 pytest 120건이 **한 번에 전부 통과**했다 — 그 자체를 증거로 보지 않고 뮤테이션으로 검증했다(§4-2). 자가 점검이 첫 실행에서 18건 OK 였던 것도 같다.
- `ruff E501` 은 한국어를 2칸으로 센다(문자 수 100이 아니라 표시 폭 100). 독스트링·메시지를 줄여야 했다.
- `PreToolUse` 가드가 `constitution/rules.yaml` 을 **읽기만 하는** `python3 - <<EOF` 조회를 차단했다(차단 사유: 헌법 경로에 쓰기로 오탐). 우회하지 않고
  Grep 도구로 읽었다. 읽기 전용 heredoc 조회가 막히는 것은 가드의 오탐 후보다 — 보고만 한다.

## 5. CI 재현 (명령 + exit code) — 잡 목록 전수 기준

`grep -E '^  [a-z][a-z0-9-]*:' .github/workflows/ci.yml` 로 잡을 전수 열거했다(`changes`·`data-pipeline`·`backend`·`backend-migrations`·`data-pipeline-integration`·
`data-pipeline-neo4j`·`mobile`·`concept-reach-guard`·`web`·`webapp`·`infra-contracts`·`docker-build`·`infra-shell`·`policy-guard`·`harness-integrity`·
`declared-unwired-audit`·`corpus-authoring`·`e2e-nightly`·`backend-serial-nightly`, 19개). 이 변경이 닿는 잡과 근거:

| 잡 | 닿는가 | 근거 |
|---|---|---|
| `backend` | **예** | 신규 모듈·테스트·ci.yml 스텝. lint·mypy·lint-imports·pytest·계층 커버리지·게이트 CLI 전부 |
| `infra-contracts` | **예** | 신규 `tests/infra` 테스트 + 신규 모듈 인벤토리 전수 귀속(`test_eos_feature_inventory_v2`) |
| `declared-unwired-audit` | **예(실제로 RED 를 일으켰다)** | 신규 CI 직접 실행 모듈이 `validation_scorecard` 를 import → 유예 5건 stale (§6-②) |
| `harness-integrity` | **예** | 신규 문서·backlog 변경 없음이나 규칙 인덱스·헌법 래칫·`tests/harness`·ruff/black(scripts) 가 같은 트리를 본다 |
| `policy-guard` | **예** | 신규 파일 전체가 금기 패턴·시크릿·인코딩(cp949 mojibake)·충돌 마커 스캔 대상 |
| `changes` | 영향 없음(근거) | 경로 판별 잡. **`.github/workflows/ci.yml` 이 모든 필터(backend·data-pipeline·mobile·web·webapp·docker·corpus)에 들어 있어 ci.yml 을 건드린 이 PR 은 경로 게이트 잡을 전부 깨운다** — 아래 "트리거되나 영향 없음" 행들이 이 때문에 PR 에서 돈다 |
| `concept-reach-guard` | 트리거됨·재현함 | backend 조건 잡. 로컬 재현 `pytest` 17 passed, exit 0 |
| `backend-migrations` | 트리거됨·**재현 불가** | alembic 리비전·`db/models` 변경 0 이라 영향 없다고 판단하나 실 PG 필요 — 로컬에 PG 가 없어 돌리지 못했다 |
| `docker-build` | 트리거됨(`docker` 플래그가 `src/backend/` 포함)·**재현 불가** | 의존성·Dockerfile 변경 0, 모듈 1개 추가뿐이라 영향 가능성은 낮으나 로컬에 Docker 가 없어 돌리지 못했다 |
| `data-pipeline`·`-integration`·`-neo4j` | 트리거됨(ci.yml)·영향 없음(근거: `src/data-pipeline` 변경 0)·**재현 불가** | 이 venv 에 data-pipeline 패키지·PG·Neo4j 가 없다 |
| `mobile`·`web`·`webapp` | 트리거됨(ci.yml)·영향 없음(근거: Flutter·웹 소스 변경 0)·**재현 불가** | Flutter·Node 툴체인 없음 |
| `infra-shell` | 영향 없음 | 셸 스크립트 변경 0 (경로 게이트 아님) |
| `corpus-authoring`·`e2e-nightly`·`backend-serial-nightly` | 아니오 | 스케줄/마커 전용 — 신규 테스트는 `corpus_authoring` 마커 아님. 야간 전체 직렬은 코드 변경이 닿으나 PR 게이트가 아니다 |

### 5-1. 재현 결과 (모두 격리 venv · 저장소 루트 또는 `src/backend` — CI 와 같은 인자)

판정은 전부 **exit code** 로 했다(출력을 자르거나 `-q` 로 죽이지 않았다). 래퍼 스크립트는 스텝 각각의 exit code 를 그대로 기록한다.

| 잡 | 명령(요약) | exit | 결과 |
|---|---|---|---|
| backend | `python -m ruff check . ../../tests/backend ../../tests/constitution` | 0 | All checks passed |
| backend | `python -m black --check --line-length 100 . ../../tests/backend ../../tests/constitution` | 0 | 1852 files unchanged |
| backend | `python -m mypy --strict whymath_backend` | 0 | 755 source files, no issues |
| backend | `lint-imports` | 0 | 4 kept, 0 broken (`ops` → `l1.standards`·`harness`·`ops` import 가 계약 위반 아님을 실측) |
| backend | `python -m pytest -m "not corpus_authoring" -n auto --dist loadfile --cov=whymath_backend --cov-report=term --cov-report=xml --cov-fail-under=70` | **1** | 18419 passed · 621 skipped · 1 xfailed · **수집 오류 10건** — 전부 `ModuleNotFoundError: data_pipeline`(이 venv 에 `data-pipeline` 패키지가 없다. CI 는 `pip install -e ../data-pipeline` 를 한다). 그 10개 파일을 `PYTHONPATH=src/data-pipeline` 로 별도 실행 → **166 passed, exit 0**. 실패한 테스트는 0건이나 **단일 명령 exit 0 으로는 확인하지 못했다** |
| backend | `python ../../scripts/coverage/check_layer_coverage.py coverage.xml` | 0 | api 97.0 · l1 89.8 · l2 96.6 · l3 95.1 · l4 96.2 (모두 바닥선 이상). 단 위 수집 오류 10건이 빠진 coverage.xml 기준 |
| backend | 게이트 CLI 17종: `defect_detection_eval`·`selective_grading_demotion_eval`·`explicit_correction_gap`·`misconception_false_positive`·`generator_space_overlap`·`coach_prose_leak`·`anchor_detection_channel_eval`·`pedagogy_pack_fidelity_eval`·`analogy_fidelity_eval`·`explanation_f7_eval`·`notation_coverage`·`curriculum_notation_gate_cli`·`provenance_audit`·`check_routing_data_grade`·`check_routing_decision_bypass`·`check_provider_seat_contract`·`prompt_asset_audit --axis l3` | 0 ×17 | 전건 통과 |
| backend | **`python -m whymath_backend.ops.phase3_metrics --self-check`**(신규 스텝) | 0 | 18건 중 실패 0 |
| backend | `python -m pytest -q tests/constitution`(저장소 루트) | 0 | 39 passed |
| infra-contracts | `python3 -m ruff check tests/infra infra conftest.py tests/test_idempotency.py` | 0 | |
| infra-contracts | `python3 -m black --check --line-length 100 tests/infra infra conftest.py tests/test_idempotency.py` | **1 → 0** | 첫 실행에서 `tests/infra/test_phase3_metrics_wiring.py` 1건 포맷 위반(내가 tests/infra 에 black 을 돌리지 않았다) → black 적용 후 129 files unchanged, exit 0 재확인 |
| infra-contracts | `check_runbook_blocks.py` · `mastery_write_path_scan.py` · `check_dependency_upper_bounds.py` | 0 ×3 | |
| infra-contracts | `python3 -m pytest tests/infra` | 0 | 2967 passed · 1 skipped (black 포맷만 바뀐 뒤 wiring 테스트 6건을 다시 돌려 6 passed) |
| infra-contracts | `python3 -m pytest -q tests/test_idempotency.py` | 0 | 11 passed |
| declared-unwired-audit | `python -m whymath_backend.ops.declared_unwired_audit` | **1 → 0** | 유예 정리 전 `stale-waiver` 5건(exit 1) · 정리 후 위반 0. 격리 worktree 의 `HEAD` 기준선은 exit 0 |
| declared-unwired-audit | OPS-24 백필 드리프트 가드 2종 | 0 ×2 | |
| harness-integrity | `backlog.py validate` · `audit-deps` · `rules lint`+`rules render --check` · `jit check` | 0 ×4 | |
| harness-integrity | `scripts/constitution/audit_ratchet.py` | 0 | **차단 0건 ≤ 기준선 0건**(단계 2) |
| harness-integrity | `pipeline_check.py`(2종) · `selftest_guard.py` · `check_amendment.py` | 0 ×4 | |
| harness-integrity | 관측 리포트 CUR-09·CUR-06·OPS-19 러너 | 0 ×3 | |
| harness-integrity | `python3 -m ruff check scripts tests/harness tools` · `black --check --line-length 100 scripts tests/harness tools` | 0 ×2 | |
| harness-integrity | `python3 -m pytest tests/harness` | 0 | 2256 passed · 3 skipped |
| policy-guard | 금기 패턴 2종·원본 바이너리·시크릿 패턴·`cp949_guard.py`·`check_conflict_markers.py` | 0 ×6 | 이 리뷰 문서·계약 문서를 트리에 둔 **뒤** 다시 돌려 6스텝 모두 exit 0(`cp949_guard`: 5005건 검사·위반 0). 문서가 닿는 `tests/infra` 7개 파일 226 passed·`tests/harness` 7개 파일 586 passed |

### 5-2. 실 코퍼스 CLI 결과 요약(§3 의 4개 실행)
`--no-db` exit 2 · DB 시도 exit 2 · 합성 주입 exit 1 · `--self-check` exit 0. JSON/증거(`--json`·`--evidence`)는 모두 `run_id`·관측 시각을 담고, 증거 NDJSON 은 지표 7종이 끝날 때마다 줄 단위로 기록됐다(12줄: run_start·world_loaded·loop_ready·evaluate_start·metric_done×7·run_end).

## 6. 설계 중 사실과 달랐던 것 · 사람 결정이 필요한 것

① **불일치 — 지시문의 Critical Defect 출처.** 저장소에 결함 심각도 필드가 없다(`scripts/harness/models.py` Task 스키마의 `eos_priority` P0~P3 는 태스크의
   12월 검증 등급). 그래서 acceptance ④ 대로 Hard Gate F-Ⅰ~Ⅴ 를 흡수했으나, F-Ⅰ·Ⅲ·Ⅳ 는 생산 공정 평면 신호다. **⑥ 의 의미를 어떻게 둘지는 Kiki 결정**
   (이대로 / F-Ⅱ·Ⅴ 만 / 심각도 필드 신설).
② **조사와 달랐던 점 — `declared-unwired-audit` 잡이 RED 가 된다.** 조사 단계는 "ci.yml 이 모듈을 직접 실행하면 선언이 불필요한지 실측"까지만 지목했는데,
   실제 문제는 *이 모듈 자신의 선언*이 아니라 **이 모듈이 import 하는 모듈들의 기존 `by-design` 유예**였다. `phase3_metrics` 가 `ops.validation_scorecard`
   (Hard Gate·임계 표 흡수)를 import 하면 감사기 축 4 ⑶(전이 import)이 그 폐포 5개 CLI(`validation_scorecard`·`qa_confusion_matrix`·`golden_benchmark`·
   `hit_cu_metrics`·`reviewer_sample_package`)를 **도달**로 판정해 유예 5건이 `stale-waiver` → exit 1 이다. **격리 worktree 의 `HEAD` 에서는 exit 0 이고 내 변경 후 5건
   위반이었음을 실측**했고, 감사기가 지시하는 대로 5건을 걷었다(`declared_unwired_audit.py` 수정 — 지시된 산출물 목록 밖의 파일이다).
   사실은 바뀌지 않았다: 그 5개 CLI 의 `main()` 은 여전히 CI 에서 안 돈다(감사기가 '라이브러리 import' 와 'CLI 실행'을 구분하지 못하는 알려진 한계). 이 한계는 건드리지
   않았다. **Kiki 확인**: 이 5건의 유예 사유가 감사 대장에서 사라지는 것을 받아들일지(주석으로 경위는 남겼다).
③ **P3-07 미착지.** 지시문은 P3-07 재사용을 요구하나 P3-07 은 `todo`. ④ 는 `corpus_reverify` 를 대리로 쓴다. P3-14 의 `depends_on` 에는 P3-07 이 없다.
④ **`EOS-38` 선행 부착.** 그 태스크 notes 는 "P3-14 의 Learning Loop Success 가 KPI ① 을 재사용하면 거기에도 건다"고 적었다. 재사용이 **확인**됐으니 `EOS-38 → P3-14`
   를 `amend --depends` 로 걸지 Kiki 가 판단(대장 조작은 이 세션이 하지 않았다).
⑤ **종합 우선순위.** 지시문 규칙("하나라도 측정 실패면 전체는 측정 실패")을 따라 **미측정이 위반보다 먼저**(exit 2 > 1)로 했다. `loop_kpi_gate` 는 위반이 먼저다. 반대로 하려면
   `compose()` 한 곳과 계약 문서 §4 를 바꾼다.
⑥ **`no_target`(⑦)이 있으면 종합은 exit 2.** 지시문은 이 경우를 말하지 않는다. "충족 위장 금지"를 우선해 목표 미정도 종합을 막게 했다(`target_pending`). ⑦ 목표를 명세가
   정하면 자동으로 사라진다.
⑦ **② Concept Completeness 의 구간 규칙은 이 CLI 가 P3-02 위에 더한 해석**이다(P3-02 자체는 측정 불가를 미달로 계상). 오늘의 실 상태에서는 두 해석의 결론이 같다(미달).
⑧ **④ 전수 계수는 Wilson 을 쓰지 않는다**(P3-02 와 같은 입장). 스코어카드는 표본이라 Wilson 을 쓴다. 모집단이 다르다는 점은 출력에 매번 적는다. 또 검증 불가(skip) 비율이
   매우 높아도 통과율은 평가 가능한 문항 기준이다 — 검증 가능 문항 비율에 하한을 둘지는 Kiki 결정(지금은 0건일 때만 측정 실패, 오늘 skip 은 0건).
⑨ **`--json PATH`**(loop_kpi_gate 형태). P3-02 의 불리언 `--json` 과 다르다.
⑩ **병렬 세션 경고.** 신규 파일 3개에 대해 하네스가 `path_overlap` 경고를 냈다(OPS-30·OPS-34 가 넓은 글롭 `ops/*.py`·`tests/infra/*` 를 소유). 같은 파일이 아니라 글롭 겹침이며
   `backlog/events/claude_blissful-franklin-uv8x0u.ndjson` 에 3줄 기록됐다.
⑪ 이 세션이 만든 **worktree**(`git worktree add --detach`, 기준선 감사 실측용)는 작업 종료 전에 제거했다.

## 7. 돌리지 못한 것

1. **`backend-migrations` 잡 전체** — 실 PostgreSQL 이 없다(alembic upgrade/downgrade 왕복·실 PG 통합 pytest·`loop_kpi_gate --schema-smoke`). 이 변경은 마이그레이션·`db/models` 를
   건드리지 않으나 "영향 없다"는 판정은 코드 대조에 근거한 것이지 실행이 아니다. 같은 이유로 **트리거되지만 로컬 재현이 불가능한 잡**: `docker-build`(Docker 없음)·
   `data-pipeline`·`data-pipeline-integration`·`data-pipeline-neo4j`(패키지·PG·Neo4j 없음)·`mobile`(Flutter)·`web`·`webapp`(Node) — 모두 ci.yml 이 필터에 들어 있어 PR 에서 돈다.
2. **⑤ 의 실 PG 수집 경로** — `lkg.collect_all(collectors={LOOP_COMPLETION: …})` 가 실 스키마 위에서 완주하는지는 확인하지 못했다. 접속 거부(`ConnectionRefusedError`) 경로만 실행됐다.
   (`--no-db --input` 주입 경로·합성 부하 경로는 실행.)
3. **backend 전체 스위트를 단일 명령 exit 0 으로는 확인하지 못했다** — 이 venv 의 `data_pipeline` 미설치로 수집 오류 10건(위 5-1). 그 10개는 `PYTHONPATH` 로 따로 돌려 통과했고 실패 0건이지만,
   CI 의 한 명령과 같은 증거는 아니다. 계층 커버리지 수치도 그 10개 파일이 빠진 coverage.xml 기준이다.
4. **pytest-randomly 무작위 순서** — 이 venv 에 플러그인이 없다. 내 테스트 128건은 별도 셔플 플러그인(역순+시드 3종)으로 확인했으나 CI 의 실제 랜덤 시드와 같지 않다.
5. **harness-integrity 의 원격 의존 3스텝** — ADR 번호 충돌(`git fetch` 필요)·원격 claim reap·고립 브랜치 관측은 네트워크 없이 의미가 없어 건너뛰었다.
6. **실제 GitHub Actions 실행** — 모든 재현은 로컬이다. CI 가 최종 판정이며, 특히 신설 `backend` 스텝이 "이번 실행에서 도달했는가"(앞 스텝 실패 시 skipped)는 PR 이후에야 확인된다.
7. **P3-02 실 코퍼스 값의 고정 테스트** — 의도적으로 두지 않았다(진척 따라 바뀌는 값). 수치는 §3 와 CLI 가 소유한다.
