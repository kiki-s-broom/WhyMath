# P3-32 — 힌트 적재 파이프라인 샌드박스 실측 (2026-11-01)

> **판정 기준: main `d81cfd7a`** · 측정 환경 = 클라우드 세션의 로컬 PostgreSQL 16 + pgvector(운영 아님) · 스키마 `a8c4e1f7b3d9`(운영 DB와 같은 head)
> 태스크: `P3-32-core-concept-hint-link` — 핵심 개념 10종 hint 연결 `unmeasured 10 → linked 10/10`

## 1. 결론

1. **운영 DB에 힌트가 0건인 이유는 하나가 아니라 셋이다.** 원천 경로(코퍼스 풀이 단계 → `corpus_replay` → `path_promotion` → `l4.hint_content.populate`)를 처음부터 끝까지 실제 PG에서 돌려 보니 세 곳에서 끊긴다.

   | # | 끊긴 곳 | 성격 | 처리 |
   |---|---|---|---|
   | ① | `path_promotion --apply`가 **외래 키 위반으로 전체 롤백** | 코드 버그 | **이 PR에서 수정**(아래 §3) |
   | ② | 코퍼스 재생 풀이 1,507건 전부 `approach_unmappable` → 승격 0건 | 설계상 사람 결정 지점 | 결정 게이트 등재 |
   | ③ | 12미적Ⅰ-02-09(방정식 실근 개수) 문항군의 재생 풀이 39건 전부 `finalize` 실패 → 검증 풀이 0건 | 기능 공백 | 후속 태스크 등재 |

2. ①을 고치고 ②를 **샌드박스에서만** 임시 우회하면(태그를 `algebraic`으로 바꿈), hint 연결은 **9/10**까지 올라간다. 남는 1건이 ③이다. 즉 ②·③이 해소되면 10/10에 닿는다는 것이 실측으로 확인됐다.

3. 운영 DB 쓰기는 0건이다. 운영 DB 적용(Kiki 머신 런북)은 ②의 결정 뒤에 만든다 — 결정 전에 만든 런북은 승격 0건으로 끝난다.

## 2. 측정 절차와 수치

| 단계 | 명령 | 결과 |
|---|---|---|
| 스키마 | `alembic upgrade head` | `a8c4e1f7b3d9` (운영과 같음) |
| 문항 적재 | `l1.standards.populate` → `l1.atom_graph.populate` → `l1.problem_bank.populate --all` | 문항 15,042건(운영은 1,703건 — §4) |
| 재생 | `whs.corpus_replay <은행> --no-bad-branch` × 핵심 개념 은행 6개 | verified 1,507건 · 실패 63건(eqapp 39 · conceptual 24) · `misconception_mc_v0`는 풀이 단계 없음(대상 0) |
| 승격(수정 전) | `whs.path_promotion --apply` | 승격 0 · `queued_approach_unmappable` 1,507 |
| 승격(샌드박스 우회 후 · 수정 전 코드) | 같음 | `ForeignKeyViolationError` — `problem_step`이 `solution_paths`보다 먼저 INSERT, 전체 롤백 |
| 승격(수정 후) | 같음 | 헤더 1,507 · 단계 4,129 |
| 힌트 적재 | `l4.hint_content.populate --apply` | 생성 6,359 · 검수 통과 5,975(94.0%) · L1 2,622 / L2 2,622 / L3 731 · 게이트 거부 정답 누설 376 · 단계 노출 351 |

### 재측정 전후 (`phase3_coverage` · 기본 vs `--hints-from-db`)

| 지표 | 전 | 후 |
|---|---|---|
| hint 연결 | linked 0 · unmeasured 10 | **linked 9 · missing 1** |
| Concept Completeness | 0/10 | **9/10** (미충족 = 02-09) |
| hint_strategy(적격 1,121건) | unknown 1,121 | present 784 · missing 337 |
| prerequisite / misconception / solution / pedagogy | 각 linked 10 | 각 linked 10 (줄지 않음) |
| Content Coverage · Curriculum Coverage | 10/10 · 10/10 | 10/10 · 10/10 |
| Graph Connectivity | 4/10 | 4/10 (변화 없음 — 힌트와 무관한 지표) |

`힌트 입력: DB 검수 통과 1507문항 → 범위 은행 784 · 적격 784 · 범위 밖 723` — 범위 밖 723은 재생한 은행에 핵심 개념 밖 문항이 섞여 있어서다(ID 불일치 아님).

## 3. 고친 버그 — 헤더보다 단계가 먼저 INSERT됨

- `problem_step.solution_path_id`는 `solution_paths`를 외래 키로 가리키지만 ORM에 `relationship()`이 없다. SQLAlchemy는 이 경우 두 테이블의 INSERT 순서를 보장하지 않는다.
- `whs/path_promotion.py`와 `l3/multi_solution.py`가 헤더와 단계를 **한 번의 flush**에 섞어 보냈다. 실 PG에서 단계가 먼저 나가 배치 전체가 롤백됐다.
- 운영에서는 승격할 경로가 한 번도 없었고(②), hermetic 테스트는 가짜 세션이라 INSERT 순서를 볼 수 없어 드러나지 않았다. `test_path_promotion.py` 모듈 설명은 "실 SQL·FK는 실 PG 통합 몫"이라고 적었지만 그 통합 테스트가 없었다.
- 수정: 헤더를 flush한 뒤 단계를 넣는다(두 모듈 모두).
- 회귀 동결: `tests/backend/whs/test_path_promotion_integration.py`, `tests/backend/l3/test_multi_solution_bank_integration.py`(실 PG · CI 통합 잡). 수정을 되돌리면 두 테스트 모두 `IntegrityError`로 RED, 수정하면 GREEN(뮤테이션 확인).

## 4. 남은 결정과 공백

### ② 코퍼스 재생 풀이의 풀이 유형(approach_type) — 사람 결정

`corpus_replay`는 모든 풀이에 `strategy_tag="corpus-replay"`를 단다. `path_promotion`은 이 값을 6종 풀이 유형 중 하나로 **추측하지 않고** 사람 검수 큐로 보낸다(모듈 설명 — AI 자기승인 금지). 그래서 지금 설계로는 운영에 경로가 하나도 승격되지 않는다. 결정 선택지:

- **A. 생성기 단위 결정론 매핑을 사람이 승인한다** — 핵심 개념 은행 6개(생성기)마다 풀이 유형을 Kiki가 정하고, 그 표를 코드에 고정해 `corpus_replay`가 처음부터 그 값을 쓰게 한다. 표본: 1단계 `3*x**2 + 24*x` → 2단계 `3*(x + 8)*(x)` 같은 식 변형 연쇄라 대부분 `algebraic`으로 보인다(읽어서 그렇게 보인다 — 은행별 확인 필요).
- **B. 1,507건 검수 큐를 사람이 처리한다** — 가장 보수적이나 1,507건 수작업.
- **C. 풀이 유형을 비워 둔 채 승격하는 별도 경로를 만든다** — `approach_type`이 필수 필드라 스키마·설계 변경이 필요.

### ③ 12미적Ⅰ-02-09 — 답이 "실근의 개수"인 문항

이 문항군(`wm-p3-diff-eqapp-*`, 적격 72건)은 `verify.answer_map`이 비어 있고 `answer_kind=real_root_count`다(정답이 근 자체가 아니라 근의 **개수**). WH-S `finalize`는 답 치환 검증을 하므로 재생 39건이 전부 `ended/None`으로 끝난다. 개수형 답을 검증하는 `finalize` 지원(또는 이 문항군 전용 검증 경로)이 필요하다.

### 운영 DB 사실(런북에서 먼저 확인할 것)

운영 `problem`은 1,703행이고 로컬 전 코퍼스 적재는 15,042행이다. 적격 1,121건(핵심 개념 10종)이 운영에 같은 `problem_id`로 있는지는 아직 모른다. `corpus_replay`·`path_promotion`은 문항 행이 없으면 `skipped_problem_missing`으로 건너뛰므로, 운영 런북은 적재 전에 이 겹침을 세고 0이면 쓰기를 거부해야 한다.

## 5. 결정 집행 — 게이트 ② A안 (P3-96 · 2026-11-01)

Kiki가 게이트 `G-p332-corpus-replay-approach`에서 **A안**(생성기 단위 결정론 매핑 표를 사람이 승인해 코드에 고정)을 골랐다. 표는 `whs/path_promotion.py`의 `CORPUS_REPLAY_APPROACH_BY_FAMILY`에 있고, `corpus-replay` 태그 행만 문항 slug의 문항군으로 찾는다. 표에 없는 문항군은 지금처럼 검수 큐로 간다.

| 문항군 | 은행 | 유형 | 표본 풀이 단계 |
|---|---|---|---|
| `wm-indseq` | generated_v0 | **inductive** | `7 + 6 + … + 6` → `7 + (12 - 1)*6` → `73` (항 나열에서 일반항 공식으로 일반화) |
| `wm-skel` | generated_v0 · rephrased_v0 | algebraic | `x**2 - 5*x` → `(x)*(x - 5)` (인수분해) |
| `wm-calc-ext` · `-extv` · `-extmc` · `-extirr` · `wm-calc-tan` | generated_v0 · rephrased_v0 | algebraic | `3*x**2 - 36*x + 96` → `3*(x - 4)*(x - 8)` |
| `wm-exp` · `wm-log` | generated_v0 · rephrased_v0 | algebraic | `log(25, 5)` → `2` · `5**2` → `25` |
| `wm-arseq` · `wm-arsum` · `wm-geseq` · `wm-gesum` | generated_v0 · rephrased_v0 | algebraic | `1 + (11 - 1)*3` → `31` (공식 대입) |
| `wm-trig` · `wm-trigeq` | generated_v0 · rephrased_v0 | algebraic | `sin(210*pi/180)` → `sin(7*pi/6)` → `-1/2` |
| `wm-count-mc` | conceptual_v0 | algebraic | `(Derivative(x - 1, x) - Derivative(-(x - 1), x)).doit()` → `1 - (-1)` → `2` |
| `wm-p3-diff-*` 12종(power · polyrules · tangent · mvt · graphshape · eqapp · velocity · coefficient · differentiability · monotonicity · power-pattern · motion-word) | p3_calculus1_diff_v0 · p3_fill_v0 | algebraic | `Derivative(...).doit().subs(x, 2) = y` → 도함수 → 대입 → 값 |

문항군 28개 = 위 5개 은행의 풀이 단계 보유 문항 전수(테스트 `test_table_covers_every_stepped_problem_in_covered_banks`가 동결 — 새 문항군이 생기면 red가 나고 사람이 유형을 정한다).

### 재측정 (우회 없이 · 샌드박스 상태를 운영과 같게 되돌린 뒤)

| 단계 | 결과 |
|---|---|
| `path_promotion --apply` | 승격 1,507 · `approach_from_corpus_family` 1,507 · `queued_approach_unmappable` **0** · algebraic 1,477 / inductive 30 |
| `hint_content.populate --apply` | 생성 6,359 · 검수 통과 5,975(L1 2,622 / L2 2,622 / L3 731) |
| `phase3_coverage --hints-from-db` | hint **linked 9 · missing 1**(12미적Ⅰ-02-09 → P3-95) · 다른 연결 4종 각 10/10 |
