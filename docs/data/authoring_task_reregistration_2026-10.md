# 저작 태스크 32건 재등재 · ID 충돌 해소 (PB-14)

> 판정 기준: 브랜치 `claude/pensive-babbage-ijn58w` 분기점 main `53718366` · 원천 브랜치 `claude/whymath-mvp-plan-architecture-trjg5x`(`c8abbc17`) · 작성 2026-10-02

## 1. 고립 실측 (acceptance ①)

trjg5x의 `backlog/tasks`에서 저작 태스크 S4-19~S4-51(33파일)을 추출해 main과 대조했다. S4-21(`rephrase-lineage-identity-decision`)은 main 사본과 **바이트 동일**이라 제외하고, 나머지 **32건**이 main 백로그에 부재였다. 재현: `git ls-tree -r --name-only c8abbc17 backlog/tasks | grep -E '/S4-(19|[2-5][0-9])'` 후 각 파일에 `git cat-file -e origin/main:<path>`.

## 2. 구번호 → 신번호 매핑 (acceptance ②)

번호 배정은 전건 `backlog.py add`가 판정했다(우회 0). 원 번호가 비어 있던 30건은 CLI가 받아들여 **번호가 유지**됐고, main에서 이종 충돌하던 **S4-19·S4-22 두 건만** CLI 제안 번호로 바뀌었다.
- S4-19 충돌 상대: `S4-19-live-step-verification-event-persist`(main) → 제안 `S4-62`
- S4-22 충돌 상대: `S4-22-attempt-event-signal-consumer-wiring`(main) → 제안 `S4-63`

해석 주의: acceptance ②의 "원 번호 재사용 금지"는 충돌이 확정된 두 번호에 대한 것으로 읽었다. 충돌이 없는 번호까지 바꾸면 `grade_axis_mvp_shortest_path_v1.md`·`w2_content_factory_completion_plan_v1.md`와 원천 커밋 메시지의 번호 참조(S4-27~51)가 전부 끊긴다.

| 구번호 | 신 ID | 번호 | 상태 | 원 증적 |
|---|---|---|---|---|
| S4-19 | S4-62-grade-axis-overlay-wiring | **변경** | todo | 40597d5c |
| S4-20 | S4-20-coverage-report-university-axis | 유지 | todo | 1325fae1 |
| S4-22 | S4-63-elementary-addsub-pilot-corpus | **변경** | done | 6a93537c |
| S4-23 | S4-23-matrix-ops-pilot-corpus | 유지 | done | a6265ebb |
| S4-24 | S4-24-university-calculus-pilot-corpus | 유지 | done | 17f2a53a |
| S4-25 | S4-25-middle-school-function-value-pilot-corpus | 유지 | done | b8e1aa20 |
| S4-26 | S4-26-discrete-expected-value-pilot-corpus | 유지 | done | 33f31cf3 |
| S4-27 | S4-27-quadratic-inequality-pilot-corpus | 유지 | done | 9aa319cc |
| S4-28 | S4-28-sequence-sigma-sum-corpus | 유지 | done | 460de754 |
| S4-29 | S4-29-coordinate-geometry-corpus | 유지 | done | 5ae0d5e9 |
| S4-30 | S4-30-elementary-area-measure-corpus | 유지 | done | 26dc6293 |
| S4-31 | S4-31-vector-operations-corpus | 유지 | done | 9b76c965 |
| S4-32 | S4-32-university-calc1-chain-quotient-corpus | 유지 | done | e4959b3c |
| S4-33 | S4-33-permutation-combination-corpus | 유지 | done | 3de5e416 |
| S4-34 | S4-34-binomial-distribution-corpus | 유지 | done | ef993809 |
| S4-35 | S4-35-elementary-division-remainder-corpus | 유지 | done | 19a270a4 |
| S4-36 | S4-36-elementary-rounding-corpus | 유지 | done | d043f549 |
| S4-37 | S4-37-gcd-lcm-corpus | 유지 | done | df171e80 |
| S4-38 | S4-38-conic-section-focus-corpus | 유지 | done | de22b596 |
| S4-39 | S4-39-highschool-quotient-rule-corpus | 유지 | done | 72beae3e |
| S4-40 | S4-40-elementary-volume-circumference-corpus | 유지 | done | c39c9863 |
| S4-41 | S4-41-repeated-combination-binomial-theorem-corpus | 유지 | done | a177b981 |
| S4-42 | S4-42-probability-law-corpus | 유지 | done | b39c9b0c |
| S4-43 | S4-43-sample-mean-distribution-corpus | 유지 | done | 1e96cd2a |
| S4-44 | S4-44-measurement-unit-conversion-corpus | 유지 | done | b6d393ce |
| S4-45 | S4-45-calculus1-integral-corpus | 유지 | done | 01c454ac |
| S4-46 | S4-46-calculus2-trig-integral-corpus | 유지 | done | 1ff76e52 |
| S4-47 | S4-47-polynomial-arithmetic-corpus | 유지 | done | 02b1c9ab |
| S4-48 | S4-48-polynomial-factoring-corpus | 유지 | done | 89de17c8 |
| S4-49 | S4-49-radian-conversion-corpus | 유지 | done | 7a813a96 |
| S4-50 | S4-50-complex-number-arithmetic-corpus | 유지 | done | 08b6e99c |
| S4-51 | S4-51-linear-inequality-system-corpus | 유지 | done | 6b7fa6c5 |

## 3. 본문 대조 결과 (acceptance ③)

- **done 30건**(S4-22→S4-63, S4-23~S4-51 = 30건): 각 태스크의 `paths`(생성기·배치·테스트·코퍼스 `problems.jsonl`) 전건이 main에 실재함을 확인했다(PB-13 이식, `PR #969` squash `5bb2947b`). 재등재 대신 **done + artifacts(원 커밋 + 이식 PR)**로 기록했다. 코퍼스가 들어왔는데 todo로 열면 허위 잔여가 된다.
- **todo 2건**(S4-62 = 구 S4-19, S4-20): `paths` 일부·핵심 코드가 main에 없다(`load_kr_curriculum_entries_for_university_atoms`·`base_system_for_grade`·`--university-standards` 전건 grep 0건). 회수 원천을 좌석 본문(acceptance 말미)에 부착했다.
- 구 S4-22의 선행이던 구 S4-19는 미완(todo)이라 신 S4-63의 `depends_on`에서 뺐다(코퍼스는 이미 main에 있어 실제 의존은 해소). 이 사실은 S4-63 notes에도 남겼다.
- done 전이 시 `start`가 trjg5x의 done 사본을 "중복 구현 위험"으로 거부해 `--ignore-remote-claim`을 썼다 — 그 사본이 바로 이 재등재가 흡수하는 회수 원천이라 정당하다.

## 4. 회수 원천 (acceptance ⑤ — 재구현 금지)

| 태스크 | 원천 커밋 | 내용 |
|---|---|---|
| S4-62 (구 S4-19) | `40597d5c` | `l1/curriculum/curriculum_loader.py` 대학 원자 → curriculum_entry(115줄) · `l4/polya/prompts.py` 학년 register(45줄) · `engine.py decide(grade=)` · 테스트 5파일(거버넌스 95줄 등) |
| S4-20 | `1325fae1` | `harness/problem_bank_coverage.py` 대학 커버리지 축(167줄) + 테스트 187줄. `docs/data/problem_bank_coverage_4axis.{json,md}`는 생성기 회수 후 재생성 |
| 상위 설계 2건 | `c8abbc17` | `docs/strategy/grade_axis_mvp_shortest_path_v1.md`(302줄)·`w2_content_factory_completion_plan_v1.md`(150줄) — 이 PR로 `docs/strategy/`에 착지(PB-13 생성기가 파일명을 인용하던 유령 참조 해소) |
| PATH-03 | — | 회수 원천은 PATH-03 자신에 부착(별건) |

**삭제 금지 연장**: trjg5x는 PB-13 완료가 아니라 **이 태스크(PB-14)·PATH-03·ADMIN-02 완료 후**에만 삭제 배치 후보다.

## 5. 집행 지점 (acceptance ④)

- `backlog.py validate` EXIT=0(1000건) · `audit-deps` EXIT=0(위반 0) · `overlap S4-62-grade-axis-overlay-wiring` EXIT=0(태스크 id를 인자로 지정).
- `next --n 500 --json` 노출: S4-62는 후보 **22위**(46건 중). S4-20은 S4-62에 의존하므로 S4-62 완료 전에는 후보에 없는 것이 정상이다.
