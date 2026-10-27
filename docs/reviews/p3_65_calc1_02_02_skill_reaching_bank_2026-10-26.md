# P3-65 — `[12미적Ⅰ-02-02]` 스킬 도달 문항 새 은행 (감사 전) · 커버리지 전후·투영 · 감사 런북

**판정 기준: main `97b4132a62e1805929b1eb1eac70bd9e4fee83e6`** (브랜치 병합 커밋 `10c470f4`의 main 쪽 부모 · 2026-10-27 리뷰 반영 판). 아래 '전' 상태 수치는 최초 분기점 main `5c4520cd`에서 쟀고, 그 뒤 main 병합으로 문제은행 바이트는 바뀌지 않았다(`corpus_facts.py sync` 무변경 · 읽은 행 15,042 = 14,742 + 300).
**태스크**: `P3-65-calc1-02-02-skill-reaching-bank` · **출처**: P3-55 판정문(`docs/reviews/p3_55_calc1_02_02_content_single_template_judgment_2026-10-18.md`) 결정 (나)의 (가) 가지
**성격**: 새 은행 생성(결정론 · LLM 0) + 측정 + 감사 런북. **승인하지 않았다** — 승인은 아래 §4 감사 라운드(사람 게이트)의 몫이다.

## 요약

| 항목 | 결과 |
|---|---|
| 새 은행 | `data/corpus/problem_bank_p3_differentiability_reach_v0/` **300건**(5슬롯 × 60) · sha256 `fa365f31caacfc3db9cdd1dc53f894267603c3a718c949847b31664364f8e934` · `review_status` 키 0건 |
| 유형 | `ptype.count-solutions` 160건(미분가능하지 않은 점의 개수) · `ptype.verify-claim` 140건(미분가능성 0/1) — 둘 다 동결 명세 `required_problem_types` 안(명세 변경 0) |
| 정답 분포 | 개수형 0 · 1 · 2 · 3 = 15 · 49 · 55 · 41 / 참거짓형 0 · 1 = 82 · 58 |
| 문면 골격 | 271개(숫자를 `#`로 접은 문면 · 은행 안) |
| 수용 게이트 | 300/300 통과(Tier1 = 생성기와 독립인 검증기 — 개수형 정확 대수 · 참거짓형 차분몫 극한) |
| 감사 기계 판정 | `p3_audit_qualification machine` **0/300** 결함 |
| 현재 커버리지 | 변화 없음(감사 전이라 적격 문항이 아니다) — §2 |
| 투영(승인 주입 · 메모리) | 02-02 연결 **24 → 324** · 줄기 **4 → 275** · 정답 **1 → 4** · 조합 1 → 3 · 견고성 `thin → ok` · 다른 개념 9개 불변 · Content 10/10 유지 — §2 |
| R1(승인 의존) 투영 | conceptual_v0 24건 승인을 걷어도 Content **10/10 유지**(현재는 9/10으로 떨어진다) |
| 감사 크기 | n = 300 → **k ≤ 1 통과**(k = 1 보정 상한 0.01923 · k = 2 0.02475) — §4 |

## ① 전제 확인

- **P3-55 결정 (나)·R1·R2**: 02-02의 Content 연결은 `conceptual_v0` 24건(줄기 4 · 정답 `0` 하나)에만 걸려 있었다. R1(승인 의존 · 빠지면 9/10)·R2(다양성 부족)를 이 은행이 겨냥한다.
- **승인 경로(P3-05 선례 · 고정 코퍼스)**: 승인은 `problem_corpus_review_status_backfill`의 코퍼스 단위 백필이 쓰고, 근거는 감사 라벨 표본 **n ≥ 200**(`_MIN_N = 200`)의 코퍼스 판정 1개다(`docs/standards/review_status_stamping_contract.md` §2 `fixed` 부류). 판정은 자격 통과 프로토콜(기계 ∪ 판정자 A ∪ B) S5 = Wilson 단측 97.5% 상한(k, n) ÷ 검출률 하한 0.96898 ≤ 0.02. P3-05는 **n = 204에서 k = 0만 통과**하는 경계라 1회차 k = 19 · 2회차 k = 2 · 3회차 k = 0으로 **회차마다 새 은행**을 만들어 통과했다(`docs/data/p3_fill_audit/README.md`). 같은 은행을 다시 채점하지 않는다(as-found).
- **MP-03 절차와의 관계**: MP-03(`docs/ops/mp03_first_golden_promotion_runbook.md`)은 **회차(round) 코퍼스**의 사람 판정 기록을 골든 승격 게이트·골든 벤치에 태우는 경로다(축적 CLI 산출물 · `review_status_verdict_bridge`). 이 은행은 레포에 상주하는 **고정 코퍼스**라 그 경로의 대상이 아니고, P3-03·P3-05와 같은 코퍼스 단위 백필 경로를 탄다(계약 §2 — 두 도구는 서로의 대상을 exit 2로 거부한다).
- **크기 선택**: n = 204는 k = 0만 통과했다. 보정 상한을 실측하면 k = 1이 통과하는 최소 n은 292 근방이다(`corrected_upper_bound` · n = 300에서 k = 1 → 0.01923). 그래서 300건(5슬롯 × 60)으로 했다 — 결함 1건에 은행을 다시 만들지 않아도 되는 크기다. 대신 감사 부담은 판정자 12명(6묶음 × A·B · 묶음당 50건)이다.

## ② 형태 — 무엇을 만들었나

생성기: `src/backend/whymath_backend/l3/equivalent/p3_diff_differentiability_skeleton_generator.py`의 **두 번째 클래스** `P3DiffDifferentiabilityReachGenerator`(단위 코드 `P3-CALC1-DIFF-DIFFERENTIABILITY-REACH`). 같은 파일의 첫 클래스(승인 은행 `p3_fill_v0`의 60건)는 한 바이트도 바꾸지 않았다(`p3_fill_batch --check`·`p3_calculus1_diff_batch --check` 둘 다 exit 0).

| 슬롯 | 유형 | 틀 | 무엇을 판정하게 하는가 |
|---|---|---|---|
| 대표 | 개수 | 꺾이는 항 `k\|x − a\|`·`\|x − a\|(x − b)`와 매끄러운 항 `(x − a)\|x − a\|`·`\|x − a\|^3`의 합(2~4항) | 절댓값 항마다 좌·우미분계수 비교 |
| 기본 | 참거짓 | `\|x − p\|(cx + d)`(+ 다항식) · `m\|x − p\|^3 + k\|x − p\|`(+ 다항식) | 한 점의 미분가능성 — `d = −cp`·`k = 0`일 때만 1 |
| 응용 | 개수 | `\|(x − a)^m(x − b)…\|`(인수 꼴·전개 꼴) · `\|x^2 − a^2\|` + 매끄러운 항 둘(+ 꺾이는 항) | 중근은 매끄럽다 · 절댓값 하나에 꺾임 둘 |
| 진단 | 참거짓 | `\|x − p\|(x − q)^2` · `\|x − p\|(x^2 − Q)` (한 점 / 실수 전체) | 곱 꼴이 매끄러운 조건(`q = p`·`Q = p^2`) |
| 숙련도 확인 | 개수·참거짓 | `\|(x − a)(x − b)\|`(전개) + `m(x − b)\|x − a\| + n(x − a)\|x − b\|` · `\|x^2 − a^2\| + m\|x − c\|^3 (+ k\|x − e\|) ± (x − d)\|x − d\|` | 꺾임이 항 사이에서 상쇄되는가 |

**정답 산출(SymPy)**: 후보 = 절댓값 안 식의 실근. 후보마다 그 점 양옆(±1/1000)에서 절댓값을 벗긴 분기 다항식을 만들고 두 분기의 도함수를 그 점에서 비교한다(좌·우미분계수). Tier1은 이와 **독립인 경로**로 같은 답을 다시 계산한다 — 개수형은 이번에 추가한 `verify_nondifferentiable_point_count`(후보 = `real_roots` 정확 실근 · 후보의 최소다항식 g로 인자를 u = g^k·h로 나눠 양옆 부호를 정하고, 분기 도함수 차를 g로 나눈 나머지가 0인지로 판정 — 극한을 쓰지 않아 무리수 근도 판정한다), 참거짓형은 기존 `verify_is_differentiable`(후보를 `real_roots`로 구하도록 고쳤다 · 판정은 종전대로 차분몫 극한). 테스트는 둘 다 믿지 않고 **학생이 보는 문면**에서 함수를 다시 읽어 정의(극한)로 300건을 재계산한다.

**문제유형 정직성**: 개수를 묻는 문면은 `count-solutions`, "…면 1, …면 0을 쓰시오"는 `verify-claim` — 테스트가 문면 형태와 유형·`answer_kind`의 일대일을 동결한다. 스킬에 닿으려고 유형을 바꿔 단 문항은 없다.

**변별력(R2)**:
- 참거짓 틀 4종은 **틀마다 0과 1이 모두** 나온다(절댓값이 보이면 0이라는 규칙 하나로 풀리지 않는다).
- 개수형은 **지름길 셈법 3종(후보 수 · 절댓값 항 수 · 절댓값이 하나일 때 안 다항식의 차수)으로 센 값과 정답이 다른 매개변수만** 쓴다(`_naive_counts` — 생성 시점 거부 · 테스트가 문면에서 다시 세어 동결).
- 점 판정(“x = p에서 …”)은 후보가 p 하나뿐인 함수만 쓴다 — 그래서 Tier1(실수 전체 판정)과 발문이 같은 명제다.

**풀이 단계(`verify.solution_steps`)**: 참거짓형은 `(Derivative(R, x) − Derivative(L, x)).doit().subs(x, p) → (r) − (l) → 차`의 식↔식 연쇄(기반 `steps_of`가 `verified_expression_chain`으로 전이 전건 correct를 검증 — 어기면 빌드가 멈춘다). 등식 연쇄로 쓰면 차를 담을 새 변수(`y = 2`)가 생겨 정답 `0`과 다른 값을 말하는 검산 재료가 되므로 쓰지 않았다(판정 기준 7 "발문–검산 불일치" 회피). 개수형은 후보 방정식(절댓값 안 식의 곱 = 0)의 근 목록에서 끝난다 — 개수는 식 연쇄로 표현되지 않는다(MVT 개수 문항과 같은 한계 · 개수는 Tier1이 검산).

**보호 장치의 실패 주입(뮤테이션 · `cp` 백업 → 주입 적용 단언 → 테스트 → 바이트 동일 원복 단언)** — 2026-10-27 리뷰 반영 판 21종 **전건 RED**:

| 주입 | 대상 |
|---|---|
| N1 후보를 옛 `solve` + `is_real` 필터로 · N13 같은 되돌림을 `is_differentiable`에 | `_abs_real_corners` · `verify_is_differentiable` |
| N2 실수 여부 확인 제거 · N3 실근 계산 예외 가지 제거 | `_abs_real_corners` |
| N4 벗긴 식 다항식 확인 제거 · N5/N6 최소다항식 예외·None 가지 제거 · N7/N8 부호 판독 None 가지(기울기·인자) 제거 · N10 도함수 차를 나머지 없이 0 판정 · N11 좌측 부호 지수 무시 | `_corner_differentiability` |
| N9 주장 파싱 예외 접기 제거 | `verify_nondifferentiable_point_count` |
| N12 부호 판독 하한 제거 | `_nonzero_sign` |
| C1 단계 수 · C2 등식 혼입 · C3 전이 검증 — 각 가지 제거 | `verified_expression_chain` |
| G1 후보 차수 확인 제거 · M3 지름길 셈 거부 제거 · M6 우분기를 좌분기로 · M7 점 판정 단일 후보 확인 제거 | 생성기 |
| M5 기반이 식 연쇄를 무시 | `steps_of` |

1차 주입에서 N2·N7·N8이 **생존**했다 — 각 가지가 막는 상태에서 다른 가지(최소다항식 계산 실패·다른 부호 판독)가 대신 막았기 때문이다. 가지 하나만 실패하도록 고립한 픽스처(실수 여부 None 근 + 부호 판독 통과 · 부호 판독을 한 번만 실패)를 더한 뒤 RED. 이전 판의 M7도 같은 사정이었다(틀이 그 절을 밟지 않음 → 직접 밟는 픽스처). 도달할 수 없던 가지 3개(중첩 절댓값 검사 · 인자 0 검사 · 인자 다항식 사전 검사 — 앞선 검사·`Poly` 예외가 먼저 거부)는 픽스처를 만들 수 없어 **지웠다**.

## ⑤ 완료 판정 — phase3_coverage 전후·투영

세 상태를 같은 계측기(`phase3_coverage`의 `load_corpus`·`evaluate`·`to_json`)로 쟀다. **투영은 메모리 안 주입이며 파일을 바꾸지 않았다**(P3-55 방식 — 바뀐 문항 수를 센다: 300건).

| 상태 | 읽은 행 | Content | Curriculum | Completeness | Graph | 6슬롯 | exit |
|---|---|---|---|---|---|---|---|
| 전(main `5c4520cd`) | 14,742 | 10/10 | 10/10 | 0/10 | 4/10 | 60/60 | 1 |
| 후(새 은행 · 승인 없음) | 15,042 | 10/10 | 10/10 | 0/10 | 4/10 | 60/60 | 1 |
| **투영(새 은행 300건 승인 주입)** | 15,042 | 10/10 | 10/10 | 0/10 | 4/10 | 60/60 | 1 |

종료 코드 1의 원인은 세 상태 모두 Content가 아니라 Concept Completeness(힌트 측정 불가)·Graph Connectivity 4/10이다(P3-53·P3-55와 같다).

**스킬 연결 견고성(P3-64 공개 · 판정 불참여)** — 02-02와 다른 개념:

| 개념 | 전 연결·줄기·정답·조합 | 후 | **투영** |
|---|---|---|---|
| **02-02** | 24 · 4 · 1 · 1 (`thin`) | 24 · 4 · 1 · 1 (`thin`) | **324 · 275 · 4 · 3 (`ok`)** |
| 02-01 | 92 · 35 · 19 · 3 | 같음 | 같음 |
| 02-03 | 49 · 19 · 31 · 2 | 같음 | 같음 |
| 02-04 | 72 · 61 · 44 · 2 | 같음 | 같음 |
| 02-05 | 33 · 31 · 18 · 1 | 같음 | 같음 |
| 02-06 | 6 · 6 · 1 · 1 (`thin`) | 같음 | 같음 (P3-44 소관 · 채우지 않음) |
| 02-07 | 289 · 90 · 106 · 4 | 같음 | 같음 |
| 02-08 | 54 · 53 · 22 · 1 | 같음 | 같음 |
| 02-09 | 42 · 31 · 2 · 1 | 같음 | 같음 |
| 02-10 | 51 · 38 · 22 · 2 | 같음 | 같음 |

투영의 02-02 조합: `conceptual_v0 × verify-claim` · `p3_differentiability_reach_v0 × count-solutions` · `p3_differentiability_reach_v0 × verify-claim`.

**R1 대조(주입)**: 투영 상태에서 `conceptual_v0`의 02-02 승인 24건을 걷어 내면 Content **10/10 유지**. 같은 주입을 현재 상태에 걸면 **9/10**(P3-55 S1 재현) — 주입이 변별력을 낸다. 즉 승인 뒤에는 02-02의 연결이 24건 한 틀에 걸린 단일 실패점이 아니다.

**판정**: ⑤의 조건(02-02 연결·줄기·정답이 §②-4 대비 증가 · 다른 개념 연결과 Content 10/10 불감소)은 **투영에서 충족**, **현재(감사 전)에서는 미충족**(적격 문항이 아니므로 값이 같다). 실제 충족은 §4 감사 통과와 승격 뒤에 같은 표로 다시 잰다.

### 승격 시 Solution QA 영향(미리 밝힌다)

`solution_qa`로 이 은행을 재면 C1(정답↔조건) 300/300 pass · C4(단계 연쇄) 300/300 pass · **C2(풀이 최종 답↔정답) 300/300 검증 불가**다(사유 `C2_FINAL_STEP_NOT_ANSWER_FORM` 140 · `C2_ROOT_CHOICE_UNSTRUCTURED` 160). 개념형(0/1·개수) 문항의 마지막 단계가 정답 값이 아니기 때문이며, 기존 승인 `conceptual_v0` 02-02 24건과 MVT 개수 문항이 같은 상태다. 승격하면 대표 과정 Solution QA의 **검증 가능 비율 분모가 300 늘고 분자는 늘지 않는다**(실패는 0 — exit 판정은 실패 0건 기준이라 영향 없음). P3-62가 남긴 "11/15 검증 가능 비율 하한" 결정에 이 효과가 들어가야 한다.

## ④ 승인 — 감사 런북 (지휘 세션용 · Kiki 결정은 승격 승인)

P3-62 런북(`docs/reviews/p3_62_s5_candidate_audit_runbook_2026-10-21.md`)과 같은 프로토콜이다. 판정자 A·B가 Claude 에이전트이므로 **에이전트를 띄울 수 있는 지휘 세션**이 실행한다. Kiki 머신은 필요 없다. 필요한 사람 게이트는 "감사 결과 확인 뒤 승격 승인" 하나다(등재 제안 — 아래 ⑥ 뒤 '등재 요청').

| 은행 | n | 통과 조건 | 묶음 | 판정자 |
|---|---|---|---|---|
| `problem_bank_p3_differentiability_reach_v0` | 300 | **k ≤ 1** (k = 0 → 0.01305 · k = 1 → 0.01923 · k = 2 → 0.02475) | 50건 × 6 | 12명(6 × A·B) |

### 0. 사전 확인
- 실행 코드가 이 태스크 커밋을 포함하는지 `git log -1 --oneline`과 `python -c "import whymath_backend; print(whymath_backend.__file__)"`로 본다. 미머지면 `git worktree add --detach <임시경로> <커밋>`에서 돌린다.

### 1. 은행 바이트 확인(결정론)
```bash
cd <저장소>/src/backend
export PYTHONPATH=$PWD:$PWD/../data-pipeline
python -m whymath_backend.harness.p3_differentiability_reach_batch --check; echo "CHECK_EXIT=$?"
sha256sum ../../data/corpus/problem_bank_p3_differentiability_reach_v0/problems.jsonl
```
- 성공 기준: exit 0이고 sha256이 `fa365f31caacfc3db9cdd1dc53f894267603c3a718c949847b31664364f8e934`. 다르면 감사로 넘어가지 않는다(감사받은 바이트와 승격할 바이트가 갈라진다). 소요 약 1분 30초.

### 2. 판정자 묶음·기계 라벨
```bash
M=whymath_backend.harness.p3_audit_qualification
A=/tmp/p365_audit
B=../../data/corpus/problem_bank_p3_differentiability_reach_v0/problems.jsonl
python -m $M bank-sheets --bank $B --seed 20261008 --shards 6 --out-dir $A/sheets --manifest $A/manifest.json --expected-size 300 --task P3-65-calc1-02-02-skill-reaching-bank --bank-label data/corpus/problem_bank_p3_differentiability_reach_v0/problems.jsonl; echo "SHEETS_EXIT=$?"
python -m $M machine --input $B --out $A/machine_labels.jsonl --id-field problem_id; echo "MACHINE_EXIT=$?"
```
- 세션 실측(2026-10-26): 기계 결함 판정 0/300. 리뷰 반영 재생성 은행(sha256 `fa365f31…`)에서 2026-10-27 재측정도 0/300. 판정자 라벨 없이 `s5`를 부르면 exit 2다(통과로 위장하지 않는다).
- **매니페스트(`manifest.json`)를 판정자 투입 전에 커밋**하면 P3-03 5회차 수준의 사전 등록이 된다(P3-05는 그러지 못했다고 README가 한계로 적었다).

### 3. 판정자 실행(지휘 세션이 서브에이전트로)
- 12명 = 6묶음 × A·B. 격리 규칙·지시문·산출 검사는 P3-62 런북 §3을 그대로 쓴다(지침 `docs/data/p3_calculus1_diff_audit/qualification/rater_protocol.md` sha256 `3046a901…` — 매니페스트에 기록된다). 묶음 크기는 50이다.
- 묶음별 A 라벨을 합쳐 `rater_A.jsonl`, B를 합쳐 `rater_B.jsonl`.

### 4. S5 판정
```bash
Q=<저장소>/docs/data/p3_calculus1_diff_audit/qualification/score.json
python -m $M s5 --bank $B --machine $A/machine_labels.jsonl --llm $A/rater_A.jsonl --llm $A/rater_B.jsonl --qualification $Q --expected-size 300 --label "P3-65 02-02 스킬 도달"; echo "S5_EXIT=$?"
```
- exit 0이면 승인 근거 성립, 1이면 불합격, 2는 입력 오류. 불합격이면 결함 원인을 생성기에서 고쳐 **새 은행(새 회차)**으로 §1부터 다시 한다(같은 은행 재채점 금지).

### 5. 승격(exit 0일 때만 · 별도 태스크·PR · Kiki 승인)
한 PR에서 함께 바꿔야 결속·드리프트가 green이다(P3-05 승격과 같은 묶음).
1. 감사 기록 `docs/data/p3_differentiability_reach_audit/bank_audit_r1/`(`audited_bank.jsonl` = §1 바이트 · `manifest.json` · `machine_labels.jsonl` · `llm_labels/` · `s5_result.txt` · `README.md`).
2. 코퍼스 단위 라벨 `docs/data/corpus_audit_p3_differentiability_reach_v0.jsonl`.
3. `problem_corpus_review_status_backfill`의 `KNOWN_CORPORA`·`AUDIT_LABEL_MAP`, `problem_corpus_persona_fit_backfill`의 코퍼스 목록에 `p3_differentiability_reach_v0` 편입 → 두 백필 실행.
4. 결속 테스트 신설(`test_p3_fill_bank_coverage_link.py` 형태 — 각인을 걷어 낸 바이트 = 감사 동결 사본).
5. 사이드카 `approval_status` 문구를 회차 결과로 바꾼다(배치 `build_provenance`).
6. 승격 뒤 `phase3_coverage`를 다시 재서 위 투영 표가 실측으로 재현되는지 확인한다.

### 한계(명시)
- **참거짓형 풀이 단계의 마지막 값은 정답이 아니다**(리뷰 ①): 연쇄는 '우미분계수 − 좌미분계수'의 값에서 끝나므로 정답 1(미분가능)인 문항은 `0`으로, 정답 0인 문항은 0이 아닌 값으로 끝난다 — 값과 정답의 방향이 반대로 보인다. 정답 0/1은 그 값이 0인가의 판정이고 식 항등 연쇄로는 그 판정 단계를 쓸 수 없다(검증 가능한 전이가 아니다). `answer_map`은 비워 두어 Solution QA C2는 `C2_FINAL_STEP_NOT_ANSWER_FORM`(검증 불가)로 남고 실패로 세어지지 않는다. 기존 승인 `conceptual_v0` 02-02 24건과 같은 형태다.
- **답 1·후보 여럿인 실수 전체 판정은 연쇄가 한 점만 보인다**(리뷰 ②): '숙련도 확인'의 상쇄 참거짓 틀은 후보 2개 모두에서 미분가능해야 답 1인데, 식 연쇄는 첫 후보 한 점의 차만 싣는다(두 점의 차를 한 연쇄로 이으면 전이가 판정 불가다). 두 점 모두의 판정은 해설과 Tier1(`verify_is_differentiable` — 전 후보)이 맡는다.
- **개념형 두 검증기의 판정 방법이 다르다**(독립 리뷰 2·3차): `verify_nondifferentiable_point_count`(개수형)는 극한 없이 **정확 대수**로 판정하고, 그 범위는 **정수·유리수 계수 식**으로 한정된다 — 소수(`|x − 0.1|^3`)·무리수(`|x² − 2|(x − √2)`)·π 계수는 판정 불가로 접는다(유리수 계수에 무리수 꺾인 점이 있는 `|x³ − 3x + 1|`은 판정한다). `verify_is_differentiable`(0/1형)은 종전대로 **극한**으로 판정하며, 이전부터 있던 두 결함(좌·우 극한 비교가 구조 비교라는 점, 극한 유한성 미확정을 '미분 불가'로 접는 점)은 이 태스크에서 고치지 않았다. 이 은행의 근은 모두 정수라 두 결함이 이 은행 판정에 드러나지는 않는다(전 코퍼스 `is_differentiable` 164건 전후 판정 차이 0).
- **검출률 보정의 이전 가정**: S5의 검출률 하한(0.96898)은 P3-03 시험지(값 계산·미지수 문항)에서 쟀다. 0/1 판정·개수 문항에 같은 검출률이 옮겨 간다는 것은 P3-05와 같은 **가정**이다(P3-05 02-03·02-10 새 유형도 같은 가정으로 승인됐다).
- **판정자는 같은 모델 계열**(P3-05 README 한계와 같다).
- 은행 안 `answer_format`: 정답 `0`은 은행 공통 규칙(`answer_format_for`)에 따라 `실수`, `1` 이상은 `자연수`다. 같은 유형 안에서 형식이 갈린다는 것을 판정자가 기준 2(답 형식)로 볼 수 있다 — 규칙 자체는 P3-05 승인 은행과 같다.

## 리뷰 반영 (2026-10-27 · 독립 리뷰 "머지 불가" 지적)

| 지적 | 처리 | 동결 |
|---|---|---|
| P1-1 무리수 실근 후보 누락(새 검증기) — `solve`가 세 실근 기약 삼차식의 근을 `is_real` None 근호식으로 돌려 `if r.is_real`가 셋 다 버림 → `Abs(x**3 - 3*x + 1)`에 '0' pass | 후보를 `real_roots`(정확 실근)로 구하고 실수 여부가 True가 아니면 판정 불가. 좌·우 비교를 극한 대신 정확 대수(최소다항식 나머지)로 바꿔 무리수 후보도 판정 | `Abs(x**3 - 3*x + 1)`·`Abs(x**3 - 4*x + 1)`·`x*Abs(x**3 - 3*x + 1)` — '0' fail · '3' pass |
| P1-1 같은 결함(`verify_is_differentiable`) — 같은 식에 '1'(미분가능) pass | 후보를 같은 헬퍼(`_abs_real_corners`)로 구한다. 무리수 후보에서는 극한이 계산되지 않아 판정 불가로 접힌다(거짓 pass 없음) | 세 식 모두 '1'이 pass가 아님 · 전 코퍼스 `is_differentiable` 164건 × 주장 0/1 판정 전후 **차이 0건**(HEAD 판과 작업 트리 판 실측) |
| P2-1 `is_finite` None·False를 미분불가로 셈 | 새 검증기는 극한을 쓰지 않아 그 가지 자체가 없어졌다(다항식 분기라 한쪽 미분계수는 늘 유한) | — |
| P2-2 판정 불가 가지 픽스처·뮤테이션 | 가지마다 픽스처(벗긴 식 비다항식 · 인자 비다항식 · 실근 계산 예외 · 실수 미확정 · 최소다항식 예외 · 부호 판정 불가 · 주장 파싱 거부). 도달 불가였던 가지(중첩 절댓값 검사 — 인자 다항식 검사가 먼저 거부 · 인자 0 검사)는 지웠다 | 뮤테이션 하네스 추가분 전건 RED(아래) |
| ③ 문면 `(x)` 표기 7건 | `x\|x - 1\|` · `-x\|x + 1\|` · `x^2\|x + 1\|` · `\|x(x + 2)^2…\|`(x 인수를 맨 앞) | 은행 재생성 — 문면이 바뀐 7건은 slug·id도 바뀐다 · sha256 `fa365f31…` |
| ④ `_claimed_int`의 '1+'·'2개' 예외 | 새 검증기에서 판정 불가로 접는다 | 픽스처 3건 |
| ⑤ `verified_expression_chain` 거부 가지 | 세 가지(단계 2개 미만 · 등식 혼입 · 전이 불일치)를 사유 문구로 각각 단언 | 테스트 |
| ⑥ 생성기 후보의 조용한 누락 | `_abs_roots`가 `real_roots`로 차수만큼 실근이 나오지 않거나 정수가 아니면 생성 거부(ValueError) | 허근·무리근·세 실근 삼차식 픽스처 |
| ①② 참거짓 풀이 단계의 방향·한 점 | 고치지 않고 한계로 명시(§④ 한계) | — |

리뷰 재현 스크립트 v5(300건 독립 재계산)의 남은 불일치 3건은 그 스크립트 쪽 사정이다: ⓐ 문면 `x|x - 1|`을 막대 치환으로 `xAbs(…)` 한 이름으로 읽음(2건 — 공백을 두면 같은 식) ⓑ `2|x^2(x - 2)(x - 3)(x + 3)^2|`의 x = -3에서 유한차분(h = 10⁻⁶)이 0.00108로 허용치 10⁻³를 넘음 — 정확한 좌·우미분계수는 둘 다 0(극한 실측)이라 정답 2가 맞다.

## ⑥ 질문 — Kiki 결정 요청 (이 태스크는 변경하지 않았다)

**02-02의 개념 스킬 집합에 절차 면(계산 계열 스킬)을 더할 것인가?** P3-55 판정문 §③의 채택하지 않은 대안이다. 지금 02-02의 스킬은 `deductive-reasoning`·`graph-reading`(사고·표상)뿐이라, 단원 목표 OBJ-02(좌·우미분계수를 구해 비교하는 절차)를 연습하는 `p3_fill_v0` 60건(`evaluate-expression`·`solve-for-unknown`)이 스킬에 닿지 않는다.
- 이 은행이 승인되면 R1·R2는 그 변경 없이 해소된다(위 투영) — 즉 **계측기 연결을 위해 이 변경이 필요하지는 않다.**
- 남는 질문은 모델링이다: 원자 3개(CONCEPT/PROCEDURE/REPRESENT)의 스킬 집합이 개념 단위로 같은 현재 구조가 맞는가, 절차 원자(`12미적Ⅰ-02-02-2` 등)에 계산 계열 스킬을 배정할 것인가. 스킬 배정은 SKB-02의 L1 데이터이고 크로스워크·학습 경로가 함께 읽으므로 교수학 판단(Kiki)이 필요하다.

## 등재 요청(지휘 세션 몫 — 이 세션은 대장을 만지지 않았다)

- 사람 게이트 1건: "P3-65 은행 S5 감사 결과 확인 뒤 승격 승인"(제안 id `G-p365-reach-bank-audit-promotion`). 감사 실행 자체는 지휘 세션 몫, 승격 PR 머지 판단이 Kiki 몫이다.
- 위 §5 승격 작업은 P3-65 허용 경로 밖(`docs/data/`·백필 레지스트리)이라 새 태스크가 필요하다.

## 정직한 공백

- **전체 백엔드 스위트는 이 세션에서 돌린 범위를 보고서(지휘 세션 회신)에 적는다** — 이 문서는 측정 결과만 담는다.
- 감사를 실행하지 않았으므로 "결함 0"은 기계 판정 0/300까지만이다. 판정자 결함은 모른다(모른다 ≠ 아니다).
- 투영은 승인을 가정한 값이다. 승격 뒤의 실측이 아니다.
