# P3-71 — Solution QA 판정기 확장: 해석 단계(근 선택·대입) + 도메인 제약 근 선택 (2026-10-20)

판정 기준: main 1a1a7c8b

브랜치 `claude/p3-solution-qa-judge-extension` · 태스크 `P3-71-solution-qa-judge-interpretive-steps` · 선행 분석 = P3-62 착수 판정(규칙 (가)는 현행 판정기에서 거짓 실패 72건, (나)는 순증 0).

생성기·코퍼스·감사 사본은 **한 바이트도 바꾸지 않았다.** 바뀐 것은 판정기 두 파일(`harness/solution_qa.py`·`l3/verify_answer.py`)과 테스트뿐이다. 아래 §2의 "실측"은 그 상태에서 CLI를 돌린 값이고, §3의 "시뮬레이션"은 P3-62 규칙을 **메모리 위에서만** 레코드에 적용해 본 예상값이다(커밋된 코퍼스와 무관). 두 표를 섞어 읽지 않는다.

---

## 0. 한 문단 요약 (초보자용)

검사기가 "풀이의 이웃 줄이 같은 식인가(동치)"만 볼 줄 알아서, 풀이가 `a = -6, a = 6` 다음에 `a = 6`(양수 근을 고름)이나 `x = 3` 다음에 `y = 4`(값을 대입)처럼 **해석하는 줄**을 쓰면 판정을 못 하거나 "틀렸다"고 했다. 이번에 그런 줄을 **문항 조건으로 증명될 때만** 맞다고 하게 했다 — 조건의 등식·`a > 0`·`answer_selection` 만으로 SymPy가 "조건이 요구하는 근은 이것 하나"를 계산하고, 대입은 조건의 정의 등식으로 계산한다. 증명이 안 되면 통과가 아니다: 원래 "틀렸다"였던 줄은 그대로 "틀렸다"로 남고(기준 완화 금지), 원래 "모른다"였던 줄은 "모른다"로 남는다. 같은 원리로, 풀이가 근을 나열하고 끝나는 문항은 그 나열이 **등식의 실근 전부**일 때만 조건의 `a > 0` 으로 하나를 걸러 정답과 대조한다. 결과: 코퍼스를 건드리지 않고 **판정 가능 456 → 548건(40.68% → 48.88%)**, 실패 0건 유지, 기존 통과 456건 전부 유지. 독립 검토(PR #1703)가 찾은 거짓 통과 3건·완화 1건은 모두 고쳤다(§8).

## 1. acceptance 대조

| 항목 | 결과 | 근거 |
|---|---|---|
| ① C4 해석 단계 인정 — 성립 pass·불성립 fail·판정 불가 unverifiable, 무조건 통과 금지 | **충족(단서 1)** | §4-1. 단서: 동치 판정이 이미 incorrect 를 낸 전이(변수 전환)는 **성립이 증명될 때만** 통과로 바꾸고, 판정 불가면 incorrect 를 유지한다 — acceptance ①의 "판정 불가면 unverifiable" 보다 기준 완화 금지(③)를 우선했다(검토 중4). |
| ② 도메인 제약 읽기 + `verify_root_selection` 이 '단일 등식 + 도메인 부등식' 리스트를 받음 · 정답 역산 금지 | **충족** | §4-2·§4-3. 후보 나열의 완전성 요구(검토 상2)·도메인 경로는 다항 등식만(검토 상3). 선택은 조건에서만 계산 |
| ③ 기준 완화 금지 — 확장마다 주입 RED · 기존 passed 456 중 failed 전환 0 · total 1,121 불변 | **충족** | §5 · §8-2 main↔브랜치 회귀 대조(코퍼스 "main FAIL→비실패" 0 · "main PASS→비PASS" 0) |
| ④ 생성기·코퍼스 무변경 상태의 전·후 표 | **충족** | §2(실측) · §3(시뮬레이션 — 별도 표) |

## 2. 실측 — 생성기·코퍼스 무변경, 판정기만 변경

명령: `python -m whymath_backend.harness.solution_qa --json <out>` (작업 디렉터리 `src/backend`, 실행 모듈 경로가 이 워크트리임을 `__file__` 로 확인). 전·후 모두 exit 0.

### 2-1. 총괄

| | 전 (main 1a1a7c8b) | 후 (이 브랜치) | 차이 |
|---|---:|---:|---:|
| total | 1,121 | 1,121 | 0 |
| passed | 456 | **548** | +92 |
| failed | 0 | 0 | 0 |
| unverifiable | 665 | **573** | −92 |
| decidable_ratio | 0.40678 | **0.48885** | +0.08207 |
| Solution QA Pass | 456/456 = 100% | 548/548 = 100% | — |

검사별 상태: C1 `pass 1121`(전후 같음) · C2 `pass 456 / unv 665` → `pass 548 / unv 573` · C3 같음 · C4 `pass 1049 / n/a 72`(전후 같음 — 현 코퍼스 풀이에는 해석 단계가 없다).

### 2-2. 사유별 (검증 불가)

| 사유 | 전 | 후 |
|---|---:|---:|
| C2_FINAL_STEP_NOT_ANSWER_FORM | 361 | 361 |
| C2_ROOT_CHOICE_UNSTRUCTURED | 155 | **63** |
| C2_FINAL_STEP_VAR_NOT_ANSWER_VAR | 77 | 77 |
| C2_NO_STEPS | 72 | 72 |
| 실패 사유 | 없음 | 없음 |

**passed 집합 보존**: 문항 ID(slug) 집합으로 대조했다 — 전 456건 전부 후에도 PASS(이탈 0), 후 FAIL 0건. 새로 PASS가 된 92건은 전부 종전 `C2_ROOT_CHOICE_UNSTRUCTURED`였다.

| 단원 | 새 PASS | 단원 전 → 후 |
|---|---:|---|
| P3-CALC1-DIFF-MEAN-VALUE-THEOREM | 43 | pass 17·unv 55 → pass 60·unv 12 |
| P3-CALC1-DIFF-TANGENT-LINE | 18 | pass 54·unv 18 → pass 72 |
| P3-CALC1-DIFF-VELOCITY-ACCELERATION | 13 | pass 57·unv 15 → pass 70·unv 2 |
| P3-CALC1-DIFF-POWER | 10 | pass 56·unv 16 → pass 66·unv 6 |
| P3-CALC1-DIFF-POLYNOMIAL-RULES | 4 | pass 68·unv 4 → pass 72 |
| P3-CALC1-DIFF-MOTION-WORD | 4 | pass 12·unv 12 → pass 16·unv 8 |

남은 ROOT_CHOICE 63건: EQUATION-APPLICATION 44(정답이 실근 **개수**·answer_map 없음) · MONOTONICITY 7 · GRAPH-SHAPE 6(정답이 구간 안의 정수 — 조건이 `f'(x) < 0` 단독) · MVT 6(answer_map 없음 — 정답이 개수). 전부 "정답이 후보의 함수"라 도메인 근 선택의 대상이 아니며, 일부러 적용하지 않는다(§4-2 적용 모양 ①).

> 과업 지시는 "판정기만 바뀐 상태에서 decidable_ratio가 오르지 않을 수도 있다"였다. 실측은 **올랐다**(+92). 이유는 P3-62 §1-1이 이미 짚은 것이다: ROOT_CHOICE 155건 중 다수(P3-62 집계 94건)는 근을 고르는 도메인 제약이 `verify.conditions` 에 이미 있었고 C2가 그것을 읽지 않았을 뿐이다. 이번에 판정된 것은 92건이다. 남은 63건 중 MVT 6건은 conditions 에 도메인이 있지만 answer_map 이 없는 개수형이라 일부러 제외했다(P3-62의 94와 이 92의 차이를 문항 단위로 대조하지는 않았다).

## 3. 시뮬레이션 — P3-62 규칙 (가)(나)를 메모리상 적용 (커밋 없음 · 코퍼스 무변경)

도구: P3-62 세션의 `sim.py`·`sim_ga.py` 와 같은 도출 규칙(선택은 conditions의 도메인 제약에서만 도출 — 정답 역산 없음, (가)의 덧붙임 값은 answer_map에서 기계 도출). 같은 레코드 1,121건에 같은 변형을 걸고 **판정기만** 옛(main 1a1a7c8b)/새(검토 반영 후)로 바꿔 돌렸다.

| 시나리오 | 판정기 | passed | failed | unverifiable | decidable_ratio | 비고 |
|---|---|---:|---:|---:|---:|---|
| 변형 없음 | 옛 | 456 | 0 | 665 | 0.40678 | = §2 전 |
| 변형 없음 | 새 | 548 | 0 | 573 | 0.48885 | = §2 후 |
| (가) 풀이 끝에 `정답변수 = 값` 1줄 (412건) | 옛 | 456 | 72 | 593 | 0.47101 | C4_STEP_INCORRECT 72 |
| (가) | 새 | **565** | **55** | 501 | 0.55308 | 72 중 17건은 증명돼 통과, 55건은 근거 없는 변수 전환이라 FAIL 유지 |
| (나) 도메인에서 selection 도출 (107건) | 옛 | 456 | 0 | 665 | 0.40678 | C1_SELECTION_UNVERIFIABLE 107 |
| (나) | 새 | 548 | 0 | 573 | 0.48885 | C1_SELECTION_UNVERIFIABLE 107 → 15 |
| (가)+(나) | 옛 | 456 | 72 | 593 | 0.47101 | |
| (가)+(나) | 새 | 552 | 55 | 514 | 0.54148 | |

모든 새 판정기 시나리오에서 "변형 없음·새" 의 passed 548건은 전부 PASS로 남았다(이탈 0).

> 검토 전 판(커밋 `b46f7bd7`)은 (가)의 72건을 "거짓 실패 → 0건"으로 보고했다. 그중 55건은 판정 불가로 **낮춘** 것이었고, 독립 검토가 그것을 기준 완화로 지적했다(중4). 이 판은 그 55건을 FAIL로 되돌렸다. 즉 **P3-62 규칙 (가)를 시뮬레이션처럼 순진하게(근거 없이 한 줄 덧붙이기) 넣으면 FAIL 55건이 난다** — 생성기가 근 선택 근거와 정의 등식을 조건에 같이 실어야 한다(§3-2).

### 3-1. (가)의 옛 판정기 FAIL 72건은 새 판정기에서 어디로 가나

| 단원 | 건수 | 새 판정 | 이유 |
|---|---:|---|---|
| EQUATION-APPLICATION | 9 | **통과** | 조건 `x >= 0` 과 등식 `f'(x) = 0` 만으로 x 가 하나로 정해지고, `y = f(x)` 에 대입한 값이 맞음(증명) |
| MOTION-WORD | 8 | **통과** | 조건 `x > 0` 으로 같은 증명 |
| GRAPH-SHAPE | 25 | FAIL 유지 | 후보 `x = -3, x = 4` 중 어느 x 인지 조건에 근거 없음(도메인·selection 없음). 정의 등식도 매개변수 `a` 가 섞임 |
| MONOTONICITY-EXTREMUM | 20 | FAIL 유지 | 같은 이유 |
| EQUATION-APPLICATION | 8 | FAIL 유지 | 후보 3개·도메인 없음 |
| VELOCITY-ACCELERATION | 2 | FAIL 유지 | 정의 등식 `(…t=3…) = y` 에 t 가 없음 — 대입이 아니라 조건 재진술 |

### 3-2. P3-62에 넘기는 관찰 (생성기 규칙 설계용 — 이 태스크에서 고치지 않음)

1. **(가)를 그대로 붙이면 FAIL 55건.** 변수 전환 단계(`x = … → y = …`)는 조건에 ①그 x 를 하나로 정하는 근거(도메인 부등식 또는 `answer_selection`)와 ②자유변수가 정확히 {x, y} 인 정의 등식(매개변수 `a` 를 대입한 꼴 — 예 `y = 2*x**3 - 3*x**2 - 72*x + 6`)이 함께 있어야 통과한다. 판정기는 정답 기록에서 매개변수 값을 빌려 오지 않는다.
2. **구형 계열 317건(CALC-*)은 (가)를 붙여도 검증 불가로 남는다.** 덧붙인 `x = 8` 의 앞 줄이 `3*(x - 4)*(x - 8)`(도함수 인수분해 — 등식도 후보 나열도 아님)이라 해석 단계 모양이 아니다. CALC-EXTREMUM-VALUE·MC 는 answer_map 의 `x` 가 실제로는 극값(`x = 108`)이라 더 그렇다.
3. **(나)를 VAR_NOT_ANSWER_VAR 문항에 붙이면 C1_SELECTION_UNVERIFIABLE 15건.** 그 conditions 는 `y = f(x)` 까지 담아 "단일 등식 + 도메인"이 아니다. (나)는 마지막 단계 변수가 정답 변수인 문항에만 맞다.
4. **근 나열은 등식의 실근 전부여야 한다.** C2 도메인 판정은 나열이 실근 전부일 때만 한다(다항식 실근 개수와 비교).

## 4. 무엇을 바꿨나 (검토 반영 후 기준)

### 4-1. C4 — 해석 단계 (`solution_qa._check_c4`)

- `verify_solution`(동치 판정)을 그대로 먼저 돌린다. **correct 인 전이는 건드리지 않는다.**
- correct 가 아닌 전이만 모양을 본다(좁게): **근 선택** — 앞: 같은 변수의 서로 다른 수치 후보, 뒤: 그 후보 중 하나(후보 밖 값이면 해석 단계가 아니다) · **대입** — 앞: 변수 v 의 수치 값(들), 뒤: **다른** 변수 w 의 수치 값 하나(기호식이면 해석 단계가 아니다).
- **값 증명 `_judge_value`** (근 선택·대입 공통): ①그 변수의 도메인 부등식을 어기면 위반 ②그 변수 하나만 담은 조건 등식이 정확히 하나여야 함 ③선택 규칙(`answer_selection` largest/smallest, 없으면 unique)으로 `verify_root_selection([등식, *도메인], 값, 규칙)` 이 pass 면 **증명**. largest/smallest 위반이면 위반, unique 인데 허용 근이 둘 이상·값이 근이 아님·판정 불가면 미정. 근의 집합은 풀이가 나열한 후보가 아니라 조건으로 계산한다.
- 근 선택: 증명 → correct · 위반 → incorrect · 미정 → unverifiable(동치 판정도 원래 판정 불가였다).
- 대입: 증명된 v(후보가 여럿이면 증명되는 것 하나)를 자유변수가 정확히 {v, w} 인 정의 등식 전부에 대입 — 전부 유일 실수해 = 주장값이면 correct, 하나라도 다르면 incorrect, 그 밖은 미정. **v 가 하나뿐이어도 같은 증명을 요구한다**(검토 상1 — 풀이 첫 줄의 값은 들어오는 전이가 없어 아무도 검산하지 않는다).
- **단조 규칙(검토 중4)**: 동치 판정이 incorrect 였던 전이는 해석 판정이 correct 를 증명할 때만 바꾼다. 미정이면 incorrect 유지. 변수 전환은 동치 판정에서 늘 incorrect 이므로, 근거 없는 대입·도메인 위반 값의 대입·근이 아닌 값의 대입은 전부 종전대로 FAIL 이다.
- 판정 불가 상세에 "해석 단계 n" 을 붙여 사람 검수 대기 목록에서 생성기 쪽 과제(근거 부재)를 가른다.

### 4-2. C2 — 도메인 제약 근 선택 (`solution_qa._check_c2_domain`)

마지막 단계가 후보 ≥2이고 `answer_selection` 이 largest/smallest 가 아닐 때(종전 `C2_ROOT_CHOICE_UNSTRUCTURED` 자리), 아래가 **전부** 성립하면 판정한다. 하나라도 아니면 종전 사유 그대로다.

1. 정답이 근 자체 — answer_map 이 있고 마지막 단계 변수가 정답 변수, `answer_kind`·`answer_aggregate` 없음
2. conditions 가 "그 변수의 단일 등식 + 도메인 부등식"
3. 후보 전부가 그 등식의 근(Tier1 대입) — 아니면 `C2_DOMAIN_CANDIDATE_NOT_ROOT`
4. **후보가 그 등식의 서로 다른 실근 전부**(`classify_solvability` 의 다항 실근 개수와 같음) — 아니면 `C2_DOMAIN_CANDIDATES_INCOMPLETE`(검토 상2)

판정: 도메인을 만족하는 후보 1개 → 정답과 다르면 **FAIL `C2_DOMAIN_PICK_MISMATCH`**, 같으면 조건만으로 계산한 `verify_root_selection(조건, 정답, "unique")` 도 pass 일 때 PASS · 0개 → **FAIL `C2_DOMAIN_NO_ADMISSIBLE_CANDIDATE`** · 2개 이상 → `C2_DOMAIN_AMBIGUOUS` · 도메인 판정 불가 → `C2_DOMAIN_UNVERIFIABLE`.

### 4-3. `l3/verify_answer.py` — `verify_root_selection` 주변만

- `verify_root_selection`: 시그니처 무변경. 문자열·원소 1개 리스트는 종전 경로 그대로. 원소 ≥2 리스트는 `split_equation_domain` 이 "단일 등식 + 같은 변수 도메인"으로 가를 때만 받고, **그 등식이 다항식일 때만**(검토 상3 — `sympy.solve` 는 `sin(x) = 0` 에 [0, π]만 준다) 실근을 도메인으로 거른 허용 근 안에서 선택한다. 답이 실근이지만 도메인 밖이면 fail. 어느 근에서든 도메인 판정이 불가하면 unverifiable.
- 새 공개 함수 4개(같은 구역): `condition_relation`·`split_equation_domain`·`satisfies_domain`(경계 근은 기호적 0 을 먼저 가른다)·`verify_substituted_value`(다항·유일 실수해일 때만 판정).
- `derive_selected_root` 는 바꾸지 않았다(생성기 경로 — 범위 밖).

### 4-4. 다른 호출자에 대한 영향 (실측 — 검토 전 판 기준, 검토 반영은 도메인 경로를 더 좁히기만 했다)

- `corpus_reverify` 를 `data/corpus/*/problems.jsonl` **40개 은행 전부**에 옛/새 판정기로 돌려 은행별 요약(총·통과·실패·skip)을 대조했다 — **40개 전부 동일**, 둘 다 exit 0.
- acceptance 의 `unique` 탐침: "단일 등식 + 도메인" 리스트 조건 레코드 182건(p3_calculus1_diff 112 · p3_fill 4 · problem_variants_staging 66)에서 pass 173 · unverifiable 9 · **fail 0**. 검토 반영(다항식 한정)은 pass 를 unverifiable 로만 바꿀 수 있어 fail 0 은 그대로다.

## 5. 기준 완화 금지 검증 (③)

### 5-1. 주입 RED 테스트

`tests/backend/harness/test_solution_qa_interpretive_steps.py`(합성 5형 대조군 + 검토 반례 8건 + 실 코퍼스 레코드), `tests/backend/l3/test_verify_answer_domain_selection.py`. 모든 주입은 레코드가 실제로 바뀌었는지 단언한다(`_inject`). 실 코퍼스 픽스처는 대상을 못 찾으면 실패한다(공허 통과 방지).

| 확장 | 주입·반례 | 결과 |
|---|---|---|
| C2 도메인 | 잘못된 근 선택(정답·answer_map 을 제약 밖 근으로) — 합성·실 레코드 | FAIL `C2_DOMAIN_PICK_MISMATCH` |
| C2 도메인 | 제약 위반 근(도메인 `a > 10`) | C2 자신이 FAIL `C2_DOMAIN_NO_ADMISSIBLE_CANDIDATE` |
| C2 도메인 | 근 하나를 빠뜨린 나열(남은 후보가 정답과 같아도) | `C2_DOMAIN_CANDIDATES_INCOMPLETE` |
| C4 근 선택 | 제약 밖 근 선택 — 합성·실 레코드 · `answer_selection` 위반 선택 · 조건 근 집합과 다른 선택 | FAIL `C4_STEP_INCORRECT(해석 단계(근 선택))` |
| C4 대입 | 틀린 대입값(정답·answer_map 도 같이) — 합성·실 레코드 · 제약 밖 후보의 값 | FAIL `C4_STEP_INCORRECT(해석 단계(대입))` |
| C4 대입 | 첫 줄의 도메인 위반 값·등식의 근이 아닌 값에 맞는 대입(검토 상1) · 정의 등식 없는 변수 전환(중4) | FAIL 유지 |
| verify_root_selection | 도메인 밖 근(unique·smallest) · 경계 근 · 주기함수 부분 해(검토 상3) · 일부 근의 도메인 판정 불가 | fail / unverifiable |

### 5-2. 뮤테이션 — 46종 실행 · 44종 RED · 잘못 설계한 1종(J7 → J7b로 대체) · 생존 1종(N4)은 등가 변이

순수 파이썬 하네스로 새 분기·가드를 하나씩 지우거나 뒤집고, 매번 ①앵커 1건 ②`mutated != orig`·길이 산술 ③원복 후 `cmp` 바이트 동일을 단언했다. 대상 테스트 = 위 두 파일 + 기존 `test_solution_qa.py`·`test_verify_answer.py`. 검토가 생존을 보고한 X5~X11 은 같은 의미의 변이를 새 코드에 다시 걸었다(X10·X11 은 `_rule_pick`·선택 단계 도메인 None 분기가 이번 재작성으로 없어져 J1·N5·X7·X6 가 그 자리를 맡는다).

| 묶음 | 변이 (모두 RED) |
|---|---|
| C2 도메인 | M1 분기 제거 · M2 허용 0 → 검증 불가 · M3 불일치 → 통과 · M4 후보=근 가드 · M5 answer_map 가드 · M6 answer_kind 가드 · **X5** answer_aggregate 가드 · **N3** 완전성 검사(상2) · N5 도메인 None → 허용 · X4 다의 → 통과 · X12 도메인 없는 등식 허용 |
| 값 증명 | J1 도메인 위반 무시 · J2 등식 둘 허용 · J4 선택 규칙 무시 · J5 규칙 위반 → 미정 · J6 unique 다근 → 위반 · **J7b** 파싱 불가 조건 건너뜀 · **X6** 다변수 부등식을 도메인으로 |
| C4 | M7 재판정 제거 · **N1** 단조 규칙 제거(중4) · **X8** correct 전이도 재해석 · S1 미증명 값으로 대입 · S3 매개변수 정의 등식 · S4 정의 없음 → 성립 · S5 불일치 → 성립 · **X9** 정의 등식 하나만 pass · SEL1·SEL2 선택 판정 뒤집기 · M14 수치 요구 · M15 후보 소속 |
| verify_answer | V1 도메인 필터 · V2 리스트 분해 · **VP** 다항 가드(상3) · **X7** 도메인 None → 허용 · X3 엄격 경계 만족 · V3 정확 경계 · V4 위반 무시 · V5·V6 분해 · V7~V10·X13 대입 판정 |

생존: **N4**(C2 PASS 직전의 `verify_root_selection(조건, 정답, "unique")` 확인 제거). 검토가 요구한 확인이라 남겼지만, 그 앞에서 ①후보가 등식의 근 전부임(완전성) ②정확근 기준 도메인 판정 ③남은 후보 1개 = 정답이 이미 성립하면 같은 등식·같은 도메인·같은 허용치로 계산하는 `verify_root_selection` 은 반드시 pass 다 — 둘을 가르는 입력이 없는 **등가 변이**다(방어 중복). 1차 J7(파싱 불가 처리 변이)은 `None` 을 빈 목록으로 바꿔 같은 결과를 내는 잘못 설계된 변이였고, 의미 있는 자리(`_relations` 에서 그 조건을 건너뛰기, J7b)에 다시 걸어 RED 를 확인했다. 검토 반영 중 등가가 확인된 중복 가드 3개(값 증명의 등식 근 검사·대입의 `relations is None`·`len(proven) != 1`)는 지웠다.

## 6. 위험·한계 (정직 스코프)

1. **main 에서 FAIL 이던 입력이 PASS 가 되는 경우가 한 부류 있다** — 해석 단계가 조건만으로 **증명**될 때다(검토 반례 A10: `a² − 4 = 0` → `a = -2, a = 2` → `a = 2`(조건 `a > 0`) → `y = 5`(조건 `y = a² + 1`)). acceptance ①이 없애라고 한 거짓 실패가 바로 이것이라 남겼다. 코퍼스 1,121건에는 이 부류가 0건이다(§8-2). "main FAIL → 비실패 0" 을 문자 그대로 강제하려면 단조 규칙을 "incorrect 는 절대 바꾸지 않음"으로 한 줄 바꾸면 되지만, 그러면 대입 단계 인정(①의 절반)이 통째로 사라진다 — 지휘자 결정 사항으로 올린다.
2. **C2 도메인 PASS 의 강도는 conditions 의 충실도에 묶인다.** 도메인 제약이 발문을 충실히 옮겼는지는 보지 않는다. 다만 선택을 정답에서 역산하지 않으므로, 조건과 정답이 어긋나면 FAIL 이 난다.
3. **acceptance `unique` 탐침이 다항 도메인 리스트를 판정하게 됐다**(§4-4). 기존 문항 영향 0을 실측했지만, 신규 생성분은 종전보다 엄격하게 강등될 수 있다.
4. **`verify_answer.py` 동시 작업(EOS-23)과의 충돌 위험** — 변경은 `__all__` 4줄과 `_distinct_values` 뒤 한 구역에 모았다.

## 7. 검증 (판정은 exit code)

### 7-1. 1차 — 커밋 `b46f7bd7` 트리 (검토 전)

실행 코드 출처: 매 실행 `PYTHONPATH=src/backend` 로 이 워크트리 모듈을 우선하고 `whymath_backend.harness.solution_qa.__file__` 이 이 워크트리 경로임을 확인했다.

| 잡 | 명령 (CI와 같은 대상·플래그) | exit |
|---|---|---:|
| backend | `python -m ruff check . ../../tests/backend ../../tests/constitution` | 0 |
| backend | `python -m black --check --line-length 100 . ../../tests/backend ../../tests/constitution` | 0 |
| backend | `python -m mypy --strict whymath_backend` (805 파일) | 0 |
| backend | `lint-imports` (4 kept · 0 broken) | 0 |
| backend | `python -m pytest -m "not corpus_authoring" -n auto --dist loadfile --cov… --cov-fail-under=70` — 21,190 passed · 0 failed · **수집 오류 10**(아래) | 1 |
| backend | 위 수집 오류 10개 모듈을 `data_pipeline` 경로를 더해 재실행 — 163 passed | 0 |
| backend | `check_layer_coverage.py coverage.xml` (api 96.9 · l1 90.8 · l2 96.4 · l3 81.5 · l4 95.8) | 0 |
| backend | `python -m whymath_backend.ops.phase3_metrics --self-check` (24건 중 실패 0) | 0 |
| backend | `python -m whymath_backend.harness.solution_qa` (§2 후) | 0 |
| backend | `python -m pytest -q tests/constitution` — `test_check_signed_changes.py` 33건 실패(아래), 나머지 39 passed | 1 / 0 |
| corpus-authoring | `python -m pytest -m corpus_authoring` — 890 passed · 2 xfailed(기존 strict 마커) | 0 |
| infra-contracts | ruff · black --check (`tests/infra infra conftest.py tests/test_idempotency.py`) | 0 · 0 |
| infra-contracts | `python3 -m pytest tests/infra` — 3,221 passed · 27 skipped | 0 |
| harness-integrity | `backlog.py validate` · `backlog.py audit-deps` | 0 · 0 |
| harness-integrity | `scripts/constitution/audit_ratchet.py` — 단계 2 · 차단 0건 ≤ 기준선 0건 | 0 |
| harness-integrity | `python3 -m pytest tests/harness` — 2,307 passed | 0 |
| policy-guard | `cp949_guard.py` · `check_conflict_markers.py` | 0 · 0 |
| declared-unwired-audit | `python -m whymath_backend.ops.declared_unwired_audit` | 0 |
| (야간 S6 대조) | `corpus_reverify` 40개 은행 전·후 요약 동일(§4-4) | 0 · 0 |

**이 컨테이너에서 확인하지 못한 것(환경)**: ①전체 스위트의 수집 오류 10건은 이 venv에 `data_pipeline` 이 설치돼 있지 않아서다(CI는 `pip install -e ../data-pipeline`). 그 10개 모듈은 경로를 더해 따로 통과시켰지만, **한 프로세스에서 전체를 다 돈 실행은 없다** — 순서 의존 오염은 CI가 최종 판정한다. ②`test_check_signed_changes.py` 33건은 전부 `ssh-keygen 이 없다`(컨테이너에 OpenSSH 클라이언트 부재) 단언 실패이며 이 변경과 무관한 경로다 — CI에서 확인. ③이 밖의 잡(web·mobile·docker-build·data-pipeline 등)은 이 변경이 닿지 않는다(백엔드 Python 두 파일·테스트·문서만 변경)고 판단해 돌리지 않았다.

### 7-2. 검토 반영 후 — 이 커밋 트리

| 잡 | 명령 | exit |
|---|---|---:|
| backend | `python -m ruff check . ../../tests/backend ../../tests/constitution` (src/backend) | 0 |
| backend | `python -m black --check --line-length 100 . ../../tests/backend ../../tests/constitution` | 0 |
| backend | `python -m mypy --strict whymath_backend` (805 파일) | 0 |
| backend | `lint-imports` | 0 |
| backend | `python -m pytest -c src/backend/pyproject.toml --rootdir=src/backend tests/backend/harness tests/backend/l3 tests/backend/ops -n auto --dist loadfile`(마커 필터 없음 — corpus_authoring 포함, `data_pipeline` 경로 추가) — 10,650 passed · 88 skipped · 3 xfailed | 0 |
| backend | `python -m whymath_backend.harness.solution_qa` — §2 후와 같은 수치(548·0·573) | 0 |
| harness-integrity | `backlog.py validate` · `audit_ratchet.py`(차단 0 ≤ 기준선 0) | 0 · 0 |
| policy-guard | `cp949_guard.py` | 0 |

**이 판에서 다시 돌리지 않은 것**: 백엔드 전체 스위트(api·l1·l2·l4 포함)·tests/infra·tests/harness·declared_unwired_audit·corpus_reverify 40은행 대조는 7-1(검토 전 트리)에서만 돌렸다. 이번 변경은 `solution_qa.py`·`verify_answer.py` 의 판정 분기와 그 테스트·이 문서뿐이고, `verify_answer` 변경(다항 가드)은 도메인 경로를 더 좁히기만 한다. 전체 스위트의 최종 판정은 CI에 넘긴다.

## 8. 독립 검토(PR #1703) 결함과 처리

### 8-1. 결함별 처리

| # | 결함(검토 문언 요지) | 반례 | 처리 | 확인 |
|---|---|---|---|---|
| 상1 | 단일 후보 대입 경로에 도메인·등식의 근 검사 없음 → main FAIL 이 PASS | `a = -2 → y = 5`(조건 `a > 0`) · `x = -3 → y = 9`(조건 `x³ = 27`) | 대입에 쓰는 값은 후보가 하나여도 `_judge_value` 증명 필수(도메인·조건 등식·선택 규칙을 `verify_root_selection` 으로) + 단조 규칙 | A3·A3b·A3c·A3d FAIL · 변이 S1·J1 RED |
| 상2 | C2 도메인이 후보 집합의 완전성을 보지 않음 → 근을 빠뜨린 나열이 PASS | `(x-1)(x-2)(x-3) = 0, x > 3/2` 에 `x = 1, x = 2` | 후보 = 등식의 실근 전부(다항 실근 개수 대조) 요구 · PASS 에 `verify_root_selection(조건, 정답, "unique")` pass 추가 요구 | A1·A2·B1 검증 불가 · 변이 N3 RED(N4 는 등가 — §5-2) |
| 상3 | `verify_root_selection` 도메인 경로가 주기함수의 부분 해를 근 전체로 취급 | `sin(x) = 0, 0 < x < 10`, 답 π, unique → pass | 도메인 경로는 다항 등식만, 아니면 unverifiable | 반례 3건 unverifiable · A9 검증 불가 · 변이 VP RED |
| 중4 | 근거 없는 해석 단계가 main FAIL 을 검증 불가로 낮춤 | `x = 3 → y = 5`(정의 등식 없음) | 단조 규칙: 동치 판정 incorrect 는 성립 증명 때만 바꾼다 | A4 FAIL · 변이 N1 RED · 시뮬레이션 (가) FAIL 55 유지(§3) |
| 중5 | 변이 X5~X11 생존 | — | 분기마다 그 분기를 밟는 픽스처 추가, 같은 의미의 변이를 새 코드에 재적용 | X5·X6·X7·X8·X9 RED, X10·X11 은 해당 분기 삭제 — J1·N5·X7·X6 가 대체(§5-2) |

### 8-2. 회귀 대조 — main 판정기 vs 수정 판정기 (같은 입력)

main = `git archive 1a1a7c8b` 로 뽑은 `src/backend`(+`docs/prompts`) 사본, 수정 = 이 워크트리. 각 실행의 모듈 경로를 `__file__` 로 확인했다.

| 입력 | 건수 | main→수정 판정 전이 | main FAIL → 비실패 | main PASS → 비PASS |
|---|---:|---|---:|---:|
| 코퍼스(대표 과정 승인 문항) | 1,121 | pass→pass 456 · unv→pass 92 · unv→unv 573 | **0** | **0** |
| 검토 반례 전체(adv1·adv2) + 추가 반례 3 | 17 | fail→fail 8 · unv→unv 7 · unv→pass 1(B2) · **fail→pass 1(A10)** | **1 (A10)** | 0 |

| 반례 | main | 수정 | 비고 |
|---|---|---|---|
| A1·A2·A2b 불완전 후보 | 검증 불가 | 검증 불가 | `C2_DOMAIN_CANDIDATES_INCOMPLETE` |
| A3·A3b·A3c·A3d 틀린 값의 대입 | FAIL | FAIL | 해석 단계(대입) 미증명 — incorrect 유지 |
| A3e 틀린 선택 뒤 대입 | FAIL | FAIL | 해석 단계(근 선택) incorrect |
| A4 정의 없는 변수 전환 | FAIL | FAIL | 중4 |
| A5 후보 밖 값 | FAIL | FAIL | 동치 판정 그대로 |
| A6 허용 근 둘 · A7 도메인 없음 | 검증 불가 | 검증 불가 | 선택 근거 없음 |
| A9 삼각 등식 | 검증 불가 | 검증 불가 | 상3 |
| B1 근 하나 뺀 나열(남은 후보 = 정답) | 검증 불가 | 검증 불가 | 상2 |
| B2 완전한 나열(`(x+1)(x+2)(x-3) = 0, x > 0`) | 검증 불가 | **PASS** | 판정 확장 — 증명된 경우 |
| B3 조건 근 집합과 다른 선택 | FAIL | FAIL | C1 이 이미 잡음 |
| **A10** `a²−4=0 → a=-2, a=2 → a=2 → y=5`(조건 `a>0`·`y=a²+1`) | FAIL | **PASS** | §6-1: 조건만으로 증명된 올바른 풀이(main 의 거짓 실패). 지휘자 결정 사항 |

