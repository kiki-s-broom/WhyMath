# 미머지 브랜치 심층 대조 17회차 — 2026-10-12

> **판정 기준: main `d873d064`** (2026-10-12). 이 문서는 그 시점의 스냅샷이며 정본이 아니다.
> 선행 판정 `unmerged_branch_audit_2026-10-09.md`(16회차)는 수정하지 않는다.
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
| `whymath-pedagogy-review-uqyg79` (PR #675 닫힘) | `5dc040b3` | 테스트 가드 2파일(476줄) — **의도적 제외** | `PED-26` ⑤ (todo) · `PED-22~25` (done) | PED-13 resolver 분석이 main에 없음(PED-26 ⑤가 재배정 소유) |
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

- **수정 파일 쪽 미이식분을 이번에 측정하지 않았다.** 이번 대조는 "신규 파일" 기준이다. 실제 구현의 상당수는 기존 파일 수정에 들어 있다(예: PATH-03의 `l2/learning_path.py` CTE 함수, S4-20의 `harness/problem_bank_coverage.py` 대학 축 167줄+테스트 187줄, `7n9n72`의 `coach.py`·`shadow.py`·`hypothesis_store.py`·`wh1_evaluation.py`). 16회차의 "줄 전체 일치" 방식으로 별도 조사가 필요하다. 소유 태스크가 있으므로 방치 위험은 낮으나 **완결성은 주장하지 않는다.**
- **미확정 3건**: ①`S3-34`(문제별 대화 리셋 코드가 main에 있는지 — grep 키워드 미특정) ②`S3-42~48` 7건의 개별 구현이 S3-32로 흡수됐는지(대조 미실시) ③`OPS-21`을 `OPS-32`가 흡수했다는 대장 기재의 코드 실재(미재확인). `tests/backend/api/test_me_learning_metrics.py`(FakeSession 단위 테스트)가 main에 이름 기준으로 없다는 보고도 단위 갭 여부 미확정이다.
- **`q8tvcx`의 `test_ci_gate_reachability.py`**: 브랜치 시점 이후 main `ci.yml` 구조가 바뀌었는지, 테스트가 지금 통과하는지는 실행하지 않았다.
- **범위 밖**: `gdmwhk`·`iws58k`·`6eejrv`·`34zvse`(16회차 판정 승계, HARN-212 소유)와 16회차 이후 새로 나타난 `gracious-cannon-xwn0lh`(3일 전·1커밋·문서 위주)는 이번에 대조하지 않았다.
- **코드 이식·브랜치 삭제는 하지 않았다.** 이 문서는 판정만 한다.
