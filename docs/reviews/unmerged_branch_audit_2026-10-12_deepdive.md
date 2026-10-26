# 미머지 브랜치 심층 대조 (17회차 보충) — 2026-10-12

> **판정 기준: main `d873d064`** (2026-10-12). 이 문서는 그 시점의 스냅샷이며 정본이 아니다.
> 선행 판정 `unmerged_branch_audit_2026-10-09.md`(16회차)는 수정하지 않는다.
> **같은 날짜의 정규 전수 감사 `unmerged_branch_audit_2026-10-12.md`(17회차, PR #1593)를 보충한다.** 그 문서는 수정하지 않는다. 이 문서는 그 문서가 "② 추적 중"으로 분류한 8개 브랜치의 심층 재검이며, 두 문서의 분류와 좌석은 일치한다(8개 전부 ② 추적 중).
> 이 세션은 시작 시 shallow였고 `git fetch --unshallow origin` + `git fetch --prune origin '+refs/heads/*:refs/remotes/origin/*'`로 전제를 복구한 뒤에만 판정했다.

## 0. 요약

1. **범위**: 16회차가 "② 추적 중"으로 분류한 고립·PR 닫힘 브랜치 중 **신규 파일이 main에 없는 8개**를 파일 단위로 대조했다(전수 감사가 아니라 심층 재검).
2. **결론: 회수 태스크 신규 등재 0건.** 미이식 코드가 실제로 남은 곳은 모두 main에 `todo` 소유 태스크가 이미 있다(§2). 중복 등재는 이 저장소 최다 반복 사고라 만들지 않았다.
3. **"완료인데 미머지"로 보이던 태스크 약 40건은 대부분 번호가 바뀌어 이미 이식**됐다(SEC-13~18→SEC-24, PED-04~12→PED-22~25, ARCH-29·MOB-15→MOB-18 등). 태스크 ID 대조만으로는 고립을 과대 계상한다.
4. **이식하면 안 되는 잔여분 3종을 확인**: ADMIN-02 마이그레이션(Kiki 판정으로 폐기·파괴적 DDL), MISC-02 계열(main에서 `cancelled`), `k20m0w`의 출하 자산 번들·거버넌스 테스트(ARCH-12 데모 예외와 충돌, ARCH-102 판정 선행).
5. **삭제는 이번 문서의 범위가 아니다.** 8개 중 삭제 가능으로 내릴 수 있는 브랜치는 없다(§2의 "삭제 금지 근거").

## 1. 방법과 검증 출처

신규 파일 열거 → main에 경로가 없는 파일(`git cat-file -e origin/main:<path>` 실패)의 핵심 심볼을 `git grep ... origin/main -- src tests scripts`로 교차했다. 커밋 이력(`git log --grep`)은 보조 근거로만 쓰고, 문서·대장만 고친 커밋은 흡수 근거로 인정하지 않았다.

```bash
git diff --name-only --diff-filter=A origin/main...origin/<브랜치>
git cat-file -e origin/main:<path>
git grep -n '<심볼>' origin/main -- src tests scripts
```

**검증 출처를 둘로 나눈다.** 파일별 판정은 읽기 전용 에이전트 4개가 만들었다.

| 구분 | 내용 |
|---|---|
| 세션이 직접 재확인 | `audit_event`·`AuditEventActorType`·`emit_generate_audit` 심볼이 main `src`에 0건 · `_job_reachable_under_flags`·`gate_steps_reachable`가 main `tests`에 0건 · 소유 태스크 25건의 main status(§2 표의 status 열) · `MISC-02` cancelled |
| 에이전트 보고만 | 파일별 ABSORBED/SUPERSEDED/MISSING_REAL 판정, 줄 수, 심볼 grep 결과 중 위 항목을 뺀 전부 |

에이전트 보고분은 재현 가능한 명령으로 쓰였으나 세션이 전수 재실행하지는 않았다. 판정을 근거로 삭제나 이식을 결정하기 전에는 해당 파일을 직접 열어 확인한다.

## 2. 브랜치별 판정

head는 16회차 문서와 동일(전부 불변). "진짜 미이식"은 신규 파일 기준이다.

| 브랜치 | head | 진짜 미이식(신규 파일) | 소유 태스크 (main status) | 삭제 금지 근거 |
|---|---|---|---|---|
| `backend-audit-event-foundation-29ac1b` (PR #880 닫힘) | `6507e018` | 코드 5 + 테스트 2: `audit_event` 마이그레이션·`audit/{__init__,event_bus,llm}.py`·테스트 2건 | `ADMIN-10` (todo) | ADMIN-10 acceptance ⑦ "삭제·백지 재작성 금지" — `docs/architecture/90_audit_log.md`(246줄)가 main 부재 |
| `whymath-ai-recommendation-review-q8tvcx` | `e1835c0c` | 테스트 1: `tests/infra/test_ci_gate_reachability.py` | `OPS-38` (todo) · 번호 이동분 `OPS-67`·`SEC-32` | OPS-38 완료 전. `data_platform_module_gap_review_r2.md`(490줄)는 SEC-32·OPS-67의 유일한 실측 근거 |
| `subject-problems-theory-check-7n9n72` | `621b11f9` | 소스 1 + 테스트 10 (아래 상세) | `MISC-01·03·05·06` · `PB-02` · `PED-14` · `S3-33·34` (전부 todo) | 위 좌석 전부 todo |
| `whymath-mvp-plan-architecture-trjg5x` | `c8abbc17` | 테스트 1(`fetch_ordering_subgraph` 통합 테스트) + 산출물 JSON/MD(재생성 가능) | `PATH-03` · `S4-20` · `ADMIN-02` (전부 todo) | 수정 파일 쪽 구현이 main에 없음(§3) |
| `openrouter-setup-guide-e98dw4` | `f8c0e3b6` | **0** (개발자 안내 문서 1건만 선택 사항) | `VIZ-06` (done · 원 VIZ-04 번호 이동분) · 16회차 좌석 `VIZ-11`은 이번에 status 재확인 안 함 | 이 문서는 삭제 후보로 내리지 않음(아래 참고) |
| `whymath-pedagogy-review-uqyg79` (PR #675 닫힘) | `5dc040b3` | 테스트 가드 2파일(476줄) — **의도적 제외** | `PED-26` ⑤ (todo) · `PED-22~25` (done) · 정규 17회차: `PED-45`가 선행 | PED-13 resolver 분석이 main에 없음(PED-26 ⑤가 재배정 소유) |
| `whymath-service-operations-review-5t5lmv` | `dd3e9475` | Dart 3파일(281줄) + 백엔드 대응 변경분 | `OPS-112` · `OPS-113` · `A11Y-02` (전부 todo) | 위 3건 todo, 이식 범위는 OPS-40 ⑤가 규정 |
| `whymath-issues-review-k20m0w` | `2330a095` | 2파일(번들 JS 878KB·거버넌스 테스트 172줄) — **정책 충돌** | `ARCH-102` (todo, `ARCH-102.yaml`) | ARCH-102 판정 선행 |

`e98dw4`: 시더(`finite_probability_defect_seeder.py`)는 main `harness/residue_gate_demotion_battle.py`가 자체 구현으로 대체했다. 결함 클래스 이름과 구조가 달라 "이식"이 아니라 "대체"다. 시더 쪽 태스크 S4-16은 main에서 cancelled다. 신규 파일 기준 미이식은 0건이지만, 16회차가 이 브랜치에 지목한 좌석(`VIZ-11`)과 수정 파일 쪽 잔여분은 이번에 대조하지 않았으므로 삭제 가능 여부는 별도 판정으로 넘긴다.

### 2.1 `7n9n72` 상세 — 가장 큰 잔여

| 파일(요약) | 판정 | 소유 |
|---|---|---|
| `harness/misconception_slip_report.py`(600줄) + 테스트(442) | MISSING_REAL | MISC-05 |
| `test_recurrence_signal.py`(370) — `get_recurrence_signals` main 부재 | MISSING_REAL | MISC-06 |
| `test_coach_similar_problem.py`(430) — `_similar_problem_for` main 부재 | MISSING_REAL | MISC-03 |
| `test_coach_visualization.py`(297)·`test_misconception_visualization_shadow.py`(195) | MISSING_REAL | MISC-01 |
| `test_wh1_evaluation_time_normalized_mastery.py`(136) | MISSING_REAL | PED-14 |
| `test_corpus_reverify_wiring.py`(221)·`test_problem_bank_coverage_ci_wiring.py`(263) | MISSING_REAL (ci.yml 스텝 부재) | PB-02 |
| `l4/misconception/prerequisite_link.py`(215) + 테스트(441) | MISSING_REAL이나 **이식 비권고** | MISC-02 (**cancelled** — 오개념 ID crosswalk가 사람 게이트 뒤에 비어 있어 구조적 불가) |
| `PED-15` yaml · `selected_choice_index` 마이그레이션 | ABSORBED | PED-37(done) · `5b3e9c27a1f6` |
| `7ef2b5a8e69e` server_verified 마이그레이션 | SUPERSEDED (main은 `dialogue.attempt_id`를 멱등 가드로 사용) | 포팅 시 alembic 헤드 분기 위험 |

학생 오개념 이력을 읽는 `slip_report`·`recurrence_signal`을 재이식할 때는 낙인 방지·비노출·원문 로그 금지 요건을 이식 시점에 확인한다.

## 3. 이식하면 안 되는 것 (3종)

1. **ADMIN-02 마이그레이션**(`trjg5x`, `d8559726a87a`): `user_profile`의 school_id와 `subscription_*` 컬럼을 드롭한다. main ADMIN-02 notes가 "4컬럼 전량 드롭은 Kiki 판정으로 폐기, 병합 금지"라고 적었고, `subscription_*`는 결제 예약 좌석이다. 게이트 `G-prod-dead-column-check` 선결.
2. **MISC-02 계열**(`7n9n72`): 위 §2.1.
3. **출하 자산 번들·거버넌스 테스트**(`k20m0w`): main 번들 `index-DJ9D7N0L.js`(902,591B)는 `quiz_history`와 "그래프 맞히기"를 포함하고 브랜치판(878,992B)에는 없다. main ARCH-12(데모 예외 공식화)와 정면 충돌하며 `test_shipped_asset_judgement_governance.py`는 main 번들에 금지 문자열이 있어 **이식하면 즉시 RED**다. 열쇠는 `ARCH-102` 판정(Kiki 재판정)이다.

## 4. 신규 등재 0건의 근거

회수 태스크 신규 등재 조건은 "미이식 코드가 있고 main 태스크 acceptance가 그것을 다루지 않음"이다. 8개 브랜치의 미이식 코드는 전부 위 표의 소유 태스크가 이미 다룬다. 따라서 `backlog.py add`는 실행하지 않았다.

## 5. 정직한 공백

- **수정 파일 쪽 미이식분은 §6에서 측정했다(2026-10-13).** §2의 대조는 "신규 파일" 기준이었고, 실제 구현의 상당수는 기존 파일 수정에 들어 있다. §6의 측정도 함수·클래스 정의 단위까지만 본다(§6.3 한계).
- **미확정 3건**: ①`S3-34`(문제별 대화 리셋 코드가 main에 있는지 — grep 키워드 미특정) ②`S3-42~48` 7건의 개별 구현이 S3-32로 흡수됐는지(대조 미실시) ③`OPS-21`을 `OPS-32`가 흡수했다는 대장 기재의 코드 실재(미재확인). `tests/backend/api/test_me_learning_metrics.py`(FakeSession 단위 테스트)가 main에 이름 기준으로 없다는 보고도 단위 갭 여부 미확정이다.
- **`q8tvcx`의 `test_ci_gate_reachability.py`**: 브랜치 시점 이후 main `ci.yml` 구조가 바뀌었는지, 테스트가 지금 통과하는지는 실행하지 않았다.
- **범위 밖**: `gdmwhk`·`iws58k`·`6eejrv`·`34zvse`(16회차 판정 승계, HARN-212 소유)와 16회차 이후 새로 나타난 `gracious-cannon-xwn0lh`(3일 전·1커밋·문서 위주)는 이번에 대조하지 않았다.
- **코드 이식·브랜치 삭제는 하지 않았다.** 이 문서는 판정만 한다.

## 6. 수정 파일 쪽 미이식 측정 (2026-10-13 추가)

> **판정 기준: main `dc214a2f`** (2026-10-13). §0~§5는 `d873d064` 기준이며, 그 사이 main이 14커밋 진행했다. 두 기준의 결론은 달라지지 않았다(§6.2).

### 6.1 방법

16회차와 같은 방식이다. 각 브랜치가 **수정한 파일**(`--diff-filter=M`, `origin/main...origin/<브랜치>`)의 추가 줄을 main의 같은 경로 파일에서 줄 전체 일치로 찾아 없는 줄을 센다. 대장·이벤트·`MEMORY.md`는 제외했다. 줄 수만으로는 main이 그 파일을 다시 쓴 경우도 "부재"로 세므로, 부재 줄 중 **정의 이름(`def`·`class`)이 main 파일 어디에도 없는 것**을 따로 뽑아 기능 단위 부재로 읽었다.

### 6.2 결과

| 브랜치 | 코드 수정 파일 | 추가 줄 | 부재 줄 | 기능 단위 부재 | 판정 |
|---|---|---|---|---|---|
| `29ac1b` | 15 | 510 | 376 | 5 — `AuditEvent{ActorType,Severity,Status,Authorization,RetentionPolicy}` (`schema/enums.py`) | `ADMIN-10` 소유 |
| `q8tvcx` | 2 | 29 | 24 | 0 (`.github/workflows/ci.yml` 16줄) | `OPS-38` 소관으로 보이나 **미확인** |
| `7n9n72` | 28 | 2095 | 1294 | 17 (아래) | 대부분 소유 태스크 있음 |
| `trjg5x` | 19 | 1035 | 484 | 6 (아래) | 소유 태스크 있음 / 대체 확인 |
| `e98dw4` | 17 | 1122 | 275 | 1 — `build_finite_probability_subject` | S4-16(cancelled) 계열 잔여 |
| `uqyg79` | 16 | 616 | 211 | 0 | 기능 단위 잔여 없음 |
| `5t5lmv` | 14 | 388 | 282 | 3 — `ClientVersionBody`, `_client_version_body`, `_observe_version_state` (`app.py`) | `OPS-112` 소유 |
| `k20m0w` | 69 | 3274 | 846 | 3 — `_stuck_depth_from_turn_counts`, `_response_latency_from_values`, `_interaction_diversity_from_kinds` (`wh1_evaluation.py`) | 커밋 `10ef8e7c`(S4-22 소비 배선) → main `S4-22` 소유 |

`7n9n72` 17건의 내역:

| 파일 | 기능 단위 부재 | 판정 |
|---|---|---|
| `api/coach.py` | `_similar_problem_for` · `_maybe_visualize` | `MISC-03` · `MISC-01` 소유 |
| `api/coach.py` | `_final_answer_for_verification` · `_decide_completion_for` · `_apply_completion` | **대체 확인** — main에 `_resolve_completion`·`_complete_problem`·`_final_answer_state`가 있고 `already_completed=dialogue.attempt_id is not None`로 멱등 처리 |
| `api/coach.py` | `_mastery_level_for` · `_l3_deps_or_default` | **미확인** — 이름이 main에 없으나 대체 구현 여부를 보지 않았다 |
| `harness/wh1_evaluation.py` | 시간 정규화 4건(`_time_normalized_mastery_gain_metric` 등) | `PED-14` 소유 |
| `l4/misconception/hypothesis_store.py` | `MisconceptionRecurrenceSignal` · `get_recurrence_signals` · `order_mids_by_recurrence` · `_key` | `MISC-06` 소유 |
| `l4/misconception/shadow.py` | `MisconceptionVisualizationShadowObservation` · `observe_misconception_visualization_shadow` | `MISC-01` 소유 |

`trjg5x` 6건의 내역: `university_covered_code_count`·`university_coverage_rate`(`harness/problem_bank_coverage.py`) → `S4-20` 소유 · `fetch_ordering_subgraph`·`derive_ordering_edges`(`l2/learning_path.py`) → `PATH-03` 소유 · `_validate_date_window`·`list_my_learning_metrics`(`api/me.py`) → **대체 확인**(main에 `GET /v1/me/learning-metrics`와 `l2.learning_metrics_rollup`이 있다).

**결론: 수정 파일 쪽에서도 소유자 없는 미이식 기능은 발견되지 않았다.** 회수 태스크 신규 등재는 여전히 0건이다.

### 6.3 한계

- **정의 이름 단위까지만 본다.** 상수·SQL·분기 조건·배선 줄처럼 `def`·`class`가 아닌 변경은 기능 단위 열에 잡히지 않는다. 예: `29ac1b`의 `app.py` 18줄·`db/models/audit.py` 71줄, `e98dw4`의 `app.py` 52줄, `uqyg79`의 `conftest.py` 31줄, `5t5lmv`의 `accessibility_test.dart` 96줄(`A11Y-02` 소관 추정)은 이 방법으로는 소유 여부를 가르지 못했다.
- **이름이 달라진 대체 구현은 "부재"로 오판될 수 있다.** 위 표에서 대체를 직접 확인한 곳은 완료 판정과 학습 지표 엔드포인트 두 군데뿐이다.
- **미확인 3건**: `q8tvcx`의 `ci.yml` 16줄, `7n9n72`의 `_mastery_level_for`·`_l3_deps_or_default`.
- **줄 수 자체는 미이식 규모가 아니다.** `7n9n72`의 부재 1,294줄(추가 2,095줄 중)은 `coach.py`·`wh1_evaluation.py`처럼 여러 브랜치가 공통으로 건드린 파일을 main이 크게 다시 쓴 결과를 포함한다.
- 측정 스크립트는 세션 스크래치패드의 일회용이며 저장소에 넣지 않았다. 재현하려면 위 §6.1 설명대로 `git diff -U0 origin/main...origin/<브랜치> -- <경로>`의 `+` 줄을 main의 같은 경로 파일에서 줄 전체 일치로 찾는다.
