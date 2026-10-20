# P3-71 — Solution QA 판정기 확장: 해석 단계(근 선택·대입) + 도메인 제약 근 선택 (2026-10-20)

판정 기준: main 1a1a7c8b

브랜치 `claude/p3-solution-qa-judge-extension` · 태스크 `P3-71-solution-qa-judge-interpretive-steps` · 선행 분석 = P3-62 착수 판정(규칙 (가)는 현행 판정기에서 거짓 실패 72건, (나)는 순증 0).

생성기·코퍼스·감사 사본은 **한 바이트도 바꾸지 않았다.** 바뀐 것은 판정기 두 파일(`harness/solution_qa.py`·`l3/verify_answer.py`)과 테스트뿐이다. 아래 §2의 "실측"은 그 상태에서 CLI를 돌린 값이고, §3의 "시뮬레이션"은 P3-62 규칙을 **메모리 위에서만** 레코드에 적용해 본 예상값이다(커밋된 코퍼스와 무관). 두 표를 섞어 읽지 않는다.

---

## 0. 한 문단 요약 (초보자용)

검사기가 "풀이의 이웃 줄이 같은 식인가(동치)"만 볼 줄 알아서, 풀이가 `a = -6, a = 6` 다음에 `a = 6`(양수 근을 고름)이나 `x = 3` 다음에 `y = 4`(값을 대입)처럼 **해석하는 줄**을 쓰면 판정을 못 하거나 "틀렸다"고 했다. 이번에 그런 줄을 **문항 조건으로 증명될 때만** 맞다고 하게 했다 — 조건의 등식·`a > 0`·`answer_selection` 만으로 SymPy가 "조건이 요구하는 근은 이것 하나"를 계산하고, 대입은 조건의 정의 등식으로 계산한다. 증명이 안 되면 통과가 아니다: 원래 "틀렸다"였던 줄은 그대로 "틀렸다"로 남고(기준 완화 금지), 원래 "모른다"였던 줄은 "모른다"로 남는다. 같은 원리로, 풀이가 근을 나열하고 끝나는 문항은 그 나열이 **등식의 실근 전부**일 때만 조건의 `a > 0` 으로 하나를 걸러 정답과 대조한다. 결과: 코퍼스를 건드리지 않고 **판정 가능 456 → 548건(40.68% → 48.88%)**, 실패 0건 유지, 기존 통과 456건 전부 유지. 독립 검토(PR #1703)가 1차에서 찾은 거짓 통과 3건·완화 1건, 재검토에서 찾은 초월 등식 '증명'·근사 중복 후보·섞인 제약 무시도 모두 고쳤다(§8). 3차 검토가 찾은 분수방정식 무연근(자동 약분)·암묵 정의역 정의 등식도 막았다. 4차 검토가 그 막음(금지 목록 — 분모·초월 함수 탐지)이 표기 하나로 뚫리는 것(`(…).doit()` 래퍼·`exp(-log(x - 2))`·`(x - 2)**0`·허수부가 아주 작은 근)을 보이자, 증명 경로를 **허용 목록**으로 뒤집었다: 조건 원문의 구문 나무를 실행 없이 읽어 정수·상수 나눗셈·기호·`+ − *`·양의 정수 지수·`Derivative(다항식, 기호)` 만으로 이뤄진 **유리 계수 다항식**일 때만 증명하고, 실근은 정확 계산(`real_roots`)으로 센다. main 에서 FAIL 이던 입력이 통과로 바뀌는 것은 **허용 목록 다항 등식으로 증명된 경우뿐**이다(§6-1).

## 1. acceptance 대조

| 항목 | 결과 | 근거 |
|---|---|---|
| ① C4 해석 단계 인정 — 성립 pass·불성립 fail·판정 불가 unverifiable, 무조건 통과 금지 | **충족(단서 1)** | §4-1. 단서: 동치 판정이 이미 incorrect 를 낸 전이(변수 전환)는 **성립이 증명될 때만** 통과로 바꾸고, 판정 불가면 incorrect 를 유지한다 — acceptance ①의 "판정 불가면 unverifiable" 보다 기준 완화 금지(③)를 우선했다(검토 중4). 증명은 **허용 목록 다항 등식**(§4-3)·변수를 섞지 않는 조건에서만 한다(재검토 상1·MV2, 3차 상1, 4차 상1). |
| ② 도메인 제약 읽기 + `verify_root_selection` 이 '단일 등식 + 도메인 부등식' 리스트를 받음 · 정답 역산 금지 | **충족** | §4-2·§4-3. 후보 나열의 완전성 요구(검토 상2)·도메인 경로는 허용 목록 다항 등식·부등식만, 실근은 정확 계산(검토 상3·4차). 선택은 조건에서만 계산 |
| ③ 기준 완화 금지 — 확장마다 주입 RED · 기존 passed 456 중 failed 전환 0 · total 1,121 불변 | **충족** | §5 · §8-2 main↔브랜치 회귀 대조(코퍼스 "main FAIL→비실패" 0 · "main PASS→비PASS" 0) |
| ④ 생성기·코퍼스 무변경 상태의 전·후 표 | **충족** | §2(실측) · §3(시뮬레이션 — 별도 표) |

## 2. 실측 — 생성기·코퍼스 무변경, 판정기만 변경

명령: `python -m whymath_backend.harness.solution_qa --json <out>` (작업 디렉터리 `src/backend`, 실행 모듈 경로가 이 워크트리임을 `__file__` 로 확인). 전·후 모두 exit 0. 4차 판(허용 목록)에서 다시 측정해 같은 값을 얻었고, 문항별 판정(판정·사유)이 3차 판과 1,121건 모두 같다.

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
| (가) | 새 | **561** | **59** | 501 | 0.55308 | 72 중 13건은 증명돼 통과, 59건은 FAIL 유지(근거 없는 변수 전환 55 · 허용 목록 밖 정의 등식 4 — §3-1) |
| (나) 도메인에서 selection 도출 (107건) | 옛 | 456 | 0 | 665 | 0.40678 | C1_SELECTION_UNVERIFIABLE 107 |
| (나) | 새 | 548 | 0 | 573 | 0.48885 | C1_SELECTION_UNVERIFIABLE 107 → 15 |
| (가)+(나) | 옛 | 456 | 72 | 593 | 0.47101 | |
| (가)+(나) | 새 | 548 | 59 | 514 | 0.54148 | |

모든 새 판정기 시나리오에서 "변형 없음·새" 의 passed 548건은 전부 PASS로 남았다(이탈 0). 새 판정기 값은 4차 판(허용 목록)에서 다시 돌린 것이다 — 3차 판 대비 (가) 565·55 → **561·59**, (가)+(나) 552·55 → **548·59**, (나) 같음. 바뀐 4건은 §3-1 의 MOTION-WORD 다.

> 검토 전 판(커밋 `b46f7bd7`)은 (가)의 72건을 "거짓 실패 → 0건"으로 보고했다. 그중 55건은 판정 불가로 **낮춘** 것이었고, 독립 검토가 그것을 기준 완화로 지적했다(중4). 이 판은 그 55건을 FAIL로 되돌렸다. 즉 **P3-62 규칙 (가)를 시뮬레이션처럼 순진하게(근거 없이 한 줄 덧붙이기) 넣으면 FAIL 55건이 난다**(4차 판에서는 2계 도함수 정의 4건이 더해 59건 — §3-1) — 생성기가 근 선택 근거와 정의 등식을 조건에 같이 실어야 한다(§3-2).

### 3-1. (가)의 옛 판정기 FAIL 72건은 새 판정기에서 어디로 가나

| 단원 | 건수 | 새 판정 | 이유 |
|---|---:|---|---|
| EQUATION-APPLICATION | 9 | **통과** | 조건 `x >= 0` 과 등식 `f'(x) = 0` 만으로 x 가 하나로 정해지고, `y = f(x)` 에 대입한 값이 맞음(증명) |
| MOTION-WORD | 4 | **통과** | 조건 `x > 0` 으로 같은 증명 |
| MOTION-WORD | 4 | FAIL 유지(4차 판에서 통과 → FAIL) | 정의 등식 `y = Derivative(f, x, x).doit()`(2계 도함수)가 허용 목록 밖(`Derivative` 는 식·기호 두 인자만)이라 정의로 면제하지 않는다 → 섞인 조건 → 미증명 → 종전 incorrect 유지. 수학적으로는 다항식이라 정당한 풀이지만, 수치를 지키려고 허용 목록을 넓히지 않았다(4차 지시) |
| GRAPH-SHAPE | 25 | FAIL 유지 | 후보 `x = -3, x = 4` 중 어느 x 인지 조건에 근거 없음(도메인·selection 없음). 정의 등식도 매개변수 `a` 가 섞임 |
| MONOTONICITY-EXTREMUM | 20 | FAIL 유지 | 같은 이유 |
| EQUATION-APPLICATION | 8 | FAIL 유지 | 후보 3개·도메인 없음 |
| VELOCITY-ACCELERATION | 2 | FAIL 유지 | 정의 등식 `(…t=3…) = y` 에 t 가 없음 — 대입이 아니라 조건 재진술 |

### 3-2. P3-62에 넘기는 관찰 (생성기 규칙 설계용 — 이 태스크에서 고치지 않음)

1. **(가)를 그대로 붙이면 FAIL 59건**(근거 없는 변수 전환 55 · 2계 도함수 정의 4). 변수 전환 단계(`x = … → y = …`)는 조건에 ①그 x 를 하나로 정하는 근거(도메인 부등식 또는 `answer_selection`)와 ②자유변수가 정확히 {x, y} 인 정의 등식(매개변수 `a` 를 대입한 꼴 — 예 `y = 2*x**3 - 3*x**2 - 72*x + 6`)이 함께 있어야 통과한다. 판정기는 정답 기록에서 매개변수 값을 빌려 오지 않는다.
2. **구형 계열 317건(CALC-*)은 (가)를 붙여도 검증 불가로 남는다.** 덧붙인 `x = 8` 의 앞 줄이 `3*(x - 4)*(x - 8)`(도함수 인수분해 — 등식도 후보 나열도 아님)이라 해석 단계 모양이 아니다. CALC-EXTREMUM-VALUE·MC 는 answer_map 의 `x` 가 실제로는 극값(`x = 108`)이라 더 그렇다.
3. **(나)를 VAR_NOT_ANSWER_VAR 문항에 붙이면 C1_SELECTION_UNVERIFIABLE 15건.** 그 conditions 는 `y = f(x)` 까지 담아 "단일 등식 + 도메인"이 아니다. (나)는 마지막 단계 변수가 정답 변수인 문항에만 맞다.
4. **근 나열은 등식의 실근 전부여야 한다.** C2 도메인 판정은 나열이 실근 전부일 때만 한다(허용 목록 다항식의 정확 실근 전부와 하나씩 대응).

## 4. 무엇을 바꿨나 (4차 검토 반영 후 기준)

### 4-1. C4 — 해석 단계 (`solution_qa._check_c4`)

- `verify_solution`(동치 판정)을 그대로 먼저 돌린다. **correct 인 전이는 건드리지 않는다.**
- correct 가 아닌 전이만 모양을 본다(좁게): **근 선택** — 앞: 같은 변수의 서로 다른 수치 후보, 뒤: 그 후보 중 하나(후보 밖 값이면 해석 단계가 아니다) · **대입** — 앞: 변수 v 의 수치 값(들), 뒤: **다른** 변수 w 의 수치 값 하나(기호식이면 해석 단계가 아니다).
- **값 증명 `_judge_value`** (근 선택·대입 공통): ①그 변수 하나만 담은 조건 등식이 정확히 하나 ②그 변수를 다른 변수와 함께 묶는 조건이 없을 것(`x + z > 100`·`x**2 + y**2 = 1` 등 — 예외는 `y = f(x)`·`f(x) = y` 꼴 정의 등식이고 f 가 **허용 목록 다항식**일 때뿐. `y = log(x)`·`sqrt(x)`·`1/(x - a)` 는 x 의 정의역을 제약하므로 예외가 아니다 — 재검토 MV2·3차 하2) ③그 등식과 그 변수의 도메인 부등식이 전부 **허용 목록 다항식**(§4-3 `certified_root_sets` — 4차 검토). 초월 함수·변수 분모·0/음수/분수/실수 지수·실수 리터럴·`.doit()` 래퍼 속 분모는 노드 단계에서 거부되므로, 평가 파싱의 자동 약분(`x*(x - 2)/(x - 2)` → `x`)이 끼어들 자리가 없다 ④실근은 제곱 인수를 뗀 다항식의 **정확 실근**으로 센다(허수부가 아주 작은 근을 실근으로 세지 않는다 — NR1). 도메인은 각 정확 근에서 대수적으로 가른다(경계는 gcd 로 정확 0 판정, 그 밖은 60자리 부호 — 부호가 문턱 1e-40 아래면 판정 불가) ⑤값은 허용치(1e-9) 안의 정확 근 **하나**에만 대응해야 한다(근사 소수 근 `1.4142135623730951` 은 √2 로 대응, 근 둘이 허용치 안이면 미정) ⑥그 근이 도메인을 어기면 위반. 선택 규칙 `answer_selection` largest/smallest 는 허용 근의 끝/처음이면 **증명**·아니면 위반, 규칙이 없으면 unique — 허용 근이 하나일 때만 **증명**, 둘 이상이면 미정. 근의 집합은 풀이가 나열한 후보가 아니라 조건으로 계산한다.
- 근 선택: 증명 → correct · 위반 → incorrect · 미정 → unverifiable(동치 판정도 원래 판정 불가였다).
- 대입: 증명된 v(후보가 여럿이면 증명되는 것 하나)를 자유변수가 정확히 {v, w} 인 정의 등식 전부에 대입 — 전부 유일 실수해 = 주장값이면 correct, 하나라도 다르면 incorrect, 그 밖은 미정. **v 가 하나뿐이어도 같은 증명을 요구한다**(검토 상1 — 풀이 첫 줄의 값은 들어오는 전이가 없어 아무도 검산하지 않는다).
- **단조 규칙(검토 중4)**: 동치 판정이 incorrect 였던 전이는 해석 판정이 correct 를 증명할 때만 바꾼다. 미정이면 incorrect 유지. 변수 전환은 동치 판정에서 늘 incorrect 이므로, 근거 없는 대입·도메인 위반 값의 대입·근이 아닌 값의 대입은 전부 종전대로 FAIL 이다.
- 판정 불가 상세에 "해석 단계 n" 을 붙여 사람 검수 대기 목록에서 생성기 쪽 과제(근거 부재)를 가른다.

### 4-2. C2 — 도메인 제약 근 선택 (`solution_qa._check_c2_domain`)

마지막 단계가 후보 ≥2이고 `answer_selection` 이 largest/smallest 가 아닐 때(종전 `C2_ROOT_CHOICE_UNSTRUCTURED` 자리), 아래가 **전부** 성립하면 판정한다. 하나라도 아니면 종전 사유 그대로다.

1. 정답이 근 자체 — answer_map 이 있고 마지막 단계 변수가 정답 변수, `answer_kind`·`answer_aggregate` 없음
2. conditions 가 "그 변수의 단일 등식 + 도메인 부등식"
3. 그 등식과 도메인 부등식이 전부 허용 목록 다항식(`certified_root_sets`) — 아니면 판정하지 않고 종전 사유로 돌아간다(분수방정식·초월 함수·`.doit()` 래퍼 속 약분 등)
4. 후보 하나하나가 등식의 정확 실근 하나에 대응하고(`match_root` — 아니면 `C2_DOMAIN_CANDIDATE_NOT_ROOT`), **후보가 그 정확 실근 전부**를 가리킬 것 — 아니면 `C2_DOMAIN_CANDIDATES_INCOMPLETE`(검토 상2). 근사 중복 후보(`-1.4142135623730951`·`-sqrt(2)`)는 같은 근을 가리키므로 √2 를 빠뜨린 나열이 '완전'으로 보이지 않고(재검토 중2 · N4a), 중근 근처 값 2.00001 은 어느 정확 근에도 대응하지 않는다(ND)

판정(정확 근 기준): 도메인을 만족하는 근 1개 → 정답이 그 근에 대응하면 PASS, 아니면 **FAIL `C2_DOMAIN_PICK_MISMATCH`** · 0개 → **FAIL `C2_DOMAIN_NO_ADMISSIBLE_CANDIDATE`** · 2개 이상 → `C2_DOMAIN_AMBIGUOUS`. 정답은 대조에만 쓴다.

### 4-3. `l3/verify_answer.py` — `verify_root_selection` 주변만

- `verify_root_selection`: 시그니처 무변경. 문자열·원소 1개 리스트는 종전 경로 그대로(main 과 같은 분기). 원소 ≥2 리스트는 `split_equation_domain` 이 "단일 등식 + 같은 변수 도메인"으로 가를 때만 받고, 그 판정은 `_certified_root_selection` 이 **허용 목록 다항 등식·부등식**의 정확 근 집합 안에서만 한다(검토 상3 — `sympy.solve` 는 `sin(x) = 0` 에 [0, π]만 준다 · 4차 — 평가 파싱의 자동 약분·`.doit()` 래퍼). 답이 정확 근이지만 도메인 밖이면 fail, 인증 불가·답이 정확 근 하나에 대응하지 않음이면 unverifiable.
- 새 공개 함수 6개(한 구역): `condition_relation`·`split_equation_domain`·`verify_substituted_value`(다항·유일 실수해일 때만 판정) 그리고 허용 목록 `certified_polynomial`(원문 → 유리 계수 다항식 또는 None)·`certified_root_sets`(정확 실근 전부·그중 허용 근)·`match_root`(값 → 허용치 안의 유일 정확 근 위치). 3차 판의 금지 목록 함수 `has_variable_denominator`·`denominator_vanishes`·`is_polynomial_expression` 과 수치 도메인 판정 `satisfies_domain` 은 허용 목록으로 대체돼 **지웠다** — 호출부는 `solution_qa` 와 두 테스트 파일뿐이었다(`src`·`tests`·`scripts` grep 0건 확인).
- **허용 목록**(`_certified_build` — 원문의 파이썬 `ast` 구문 나무, 아무것도 실행하지 않는다): 정수 리터럴(|v| ≤ 10³⁰, bool 제외) → Integer · 평범한 식별자이고 SymPy 이름이 아닌 것 → Symbol · 단항 ± · `+ − *` · `/` 는 분모가 0 아닌 **상수**일 때만(유리 계수) · `**` 는 지수가 1~64 정수 리터럴일 때만 · `Derivative(허용 식, 기호)` → 미분 · `.doit()`(인자 없음) → 항등 · `.subs(기호, 허용 식)` → 대입. 그 밖의 노드(함수 전부·실수 리터럴·0/음수/분수/기호/실수 지수·변수 분모·다른 메서드·비기호 대입/미분 변수)는 하나라도 있으면 거부한다. 원문은 그 전에 공식 진입점 `safe_sympify` 의 문자·길이·차수 예산 검사를 통과해야 한다(R22-03 — 구문 나무 빌더는 CAS 파서 호출이 아니다). 세운 식이 그 변수 하나의 ZZ/QQ 다항식(차수 ≤ 24)일 때만 인증한다. 다항식에 대한 미분·대입은 다항식이므로 이 목록 안에서는 약분·정의역 문제가 생길 수 없다.
- 근사값 **대응**만 수치로 남는다(IR2 의 `1.4142135623730951`·HD2 의 `1.1673039782614187` — 허용치 1e-9). 근의 **개수**와 도메인 판정은 정확하다.
- `derive_selected_root` 는 바꾸지 않았다(생성기 경로 — 범위 밖).

### 4-4. 다른 호출자에 대한 영향 (실측 — 4차 판)

- `corpus_reverify` 를 `data/corpus/*/problems.jsonl` **40개 은행 전부**에 옛/새 판정기로 돌려 은행별 요약(총·통과·실패·skip)을 대조했다 — **40개 전부 동일**, 둘 다 exit 0. 4차 판(허용 목록)에서 다시 돌려 main 전 요약과 40개 전부 동일(exit 0)을 확인했다.
- acceptance 의 `unique` 탐침(`verify_root_selection(조건, answer_map, "unique")`): "단일 등식 + 도메인" 리스트 조건 레코드 182건(p3_calculus1_diff 112 · p3_fill 4 · problem_variants_staging 66). 4차 판 **pass 167 · unverifiable 15 · fail 0**(검토자 실측 `3813ddb0` = pass 170 · unv 12 · fail 0). 차이 3건(p3_calculus1_diff 243·248·249)은 pass → unverifiable 로, MVT 꼴 `Derivative(…).doit().subs(x, -5/3) = (f(0) − f(a))/((0) − a)` 의 우변에 **변수 분모** `(0) − a` 가 있어 허용 목록이 거부한 것이다 — 규칙 (b)(변수 분모 제외)대로의 정당한 거부이고, 분수식을 인증하려면 허용 목록을 넓혀야 하므로 하지 않았다. 남은 unverifiable 12건은 3차 판과 같다(answer_map 에 그 변수 없음 9 · 변수 분모 MVT 꼴 3). main 은 이 리스트 조건을 받지 않는다(전부 unverifiable). 이 탐침 변화는 코퍼스 solution_qa 판정·corpus_reverify 요약에 닿지 않았다(둘 다 3차 판·main 대비 동일).

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
| C4 증명(재검토) | 초월 등식 값의 대입(T1)·근 선택(T3·T4) · 다른 변수와 섞인 제약 무시(MV2) · x 를 묶는 목표 등식(`y**2 + (x-3)**2 = 0`) · 섞인 부등식 뒤의 확정 위반 · 정의 등식 둘 중 하나만 성립 | FAIL 유지 / 검증 불가 |
| 분수방정식(3차) | 자동 약분 무연근 RF3 `x*(x-2)/(x-2) = 2`·RF4 `(x-2)**3/(x-2)**2 = 0`·표기 변형 RF5 `x*(x-2)*(x-2)**-1`·RF6 `x/((x-2)/(x-2))` 의 값 대입 · C2 무연근 섞인 후보 · `verify_root_selection` 도메인 경로의 무연근·허수 분모 | FAIL 유지 / 검증 불가 · 대조 `x*(x-2)/(x-2) = 3`(x = 3)은 근 선택 pass |
| 암묵 정의역(3차 하2) | `y = log(x)` 를 정의로 면제해 smallest(-2)와 비교하던 근 선택 거짓 incorrect | 근 선택은 판정 불가, 대입 단계에서 종전 FAIL |
| C2 완전성(재검토) | 근사 중복 후보로 근 누락(N4a, 5e-15 차 소수 포함) → `CANDIDATES_INCOMPLETE` · 중근 근처 값 2.00001(Tier1 잔차 허용치 안) → 어느 정확 근에도 대응하지 않아 `C2_DOMAIN_CANDIDATE_NOT_ROOT` | 검증 불가 |
| 허용 목록(4차) | B1 `(x*(x - 2)/(x - 2)).doit() = 2` · B3 `x*(x - 2)*exp(-log(x - 2)) = 2` · B10 `x*(x - 2)**0 = 2` · D1~D3 `Derivative(x**3*(x - 1)/(x - 1), x).doit() = 3` · NR1 `(x - 1)**2 + 10**(-20) = 0`·NR2 `… + 1/10**12` · 거부 노드마다 1건(함수 6종·음수/0/분수/기호/실수 지수·실수 리터럴·변수 분모·SymPy 이름·다른 메서드·비기호 대입/미분 변수·미분 인자 개수·0 나눗셈·정수 상한·`safe_sympify` 문자/길이 예산) · 판정 불가 꼴(관계 둘·등식 아닌 관계·잔차 1e-44 의 도메인 부호·허용치 안 근 둘) | C4 FAIL 유지 / C2 종전 사유 / `verify_root_selection` unverifiable / 인증 None · 정당 대조 `Derivative(x**3, x).doit() = 3`(x = 1, x > 0)·A10·DR2·IR2·SP1·HD2 PASS |

### 5-2. 뮤테이션 — 4차 판 78종 실행 · 72종 RED · 생존 6종은 등가(방어 중복)

순수 파이썬 하네스로 분기·가드를 하나씩 지우거나 뒤집고(허용 목록은 **노드를 하나씩 더 허용**), 매번 ①앵커 1건 ②`mutated != orig`·길이 산술 ③원복 후 `filecmp` 바이트 동일을 단언했다. 대상 테스트 = 두 신규 파일 + 기존 `test_solution_qa.py`·`test_verify_answer.py`. 4차 판 코드 확정 뒤 77종을 한 번에 돌렸고(66 RED · 생존 11), 생존 11종 중 5종(A6·A9·A11·A14·J5)은 **잡는 픽스처가 없었던 것**이라 테스트를 더한 뒤(코드는 그대로) 생존 11종 + 조합 변이 A18 을 다시 돌렸다(6 RED · 생존 6). 테스트를 더해도 이미 RED 인 변이는 RED 로 남으므로 합계는 78종 중 72 RED 다.

| 묶음 | 변이 (모두 RED) |
|---|---|
| 허용 목록 빌더 — 노드 하나씩 추가 허용 | A1 함수 호출 · A2 0 지수 · A3 음수 지수 · A4 분수·식 지수 · A5 실수 지수 · **A6** 실수 리터럴 · A7 변수 분모 · A8 SymPy 이름 기호 · **A9** 임의 메서드(항등) · A10 비기호 대입 대상 · **A11** 비기호 미분 변수 · A12 미분 인자 개수 완화 · A13 정수 상한 제거 · **A14** 0 나눗셈 · A15 `safe_sympify` 사전 검사 제거 · A18 다른 기호·비유리 도메인 동시 허용 |
| 정확 근·진리값·대응 | C1 제곱 인수 제거 생략 · C2 등식 아닌 관계 · C3 도메인에 등식 · C4 도메인 판정 불가 → 만족 · C5 gcd 정확 0 판정 제거 · C6 0 문턱 제거 · C7 엄격 경계 만족 · C8 대응 유일성 제거 · C9 관계 둘 이상 허용 |
| `verify_root_selection` 도메인 경로·분해·대입 | D1 도메인 경로 우회(종전 solve) · D2 도메인 위반 근 계속 · D3 unique 다근 통과 · D4 대응 실패 → 첫 근 · V2 리스트 분해 · V5·V6 분해 · V7~V10·X13 대입 판정 |
| 값 증명 | J1 도메인 위반 근 → 미정 · J2 등식 둘 · J3 인증 불가 → 성립 · J4 largest 무시 · **J5** smallest 무시 · J6 unique 다근 → 성립 · J8 unique 다근 → 위반 · J9 대응 실패 → 첫 근 · J7b 파싱 불가 조건 건너뜀 · P2 섞인 조건 규칙 · P3 정의 면제 제거 · P4 면제 무조건 · P5b 두 변수 등식 전부 면제 · R6 정의 면제의 허용 목록 요구 제거 |
| C2 도메인 | M1 분기 제거 · M2 허용 0 → 검증 불가 · M3 불일치 → 통과 · M4 대응 가드 · N3 완전성 · M8 정답 대조의 허용 근 비교 · M5 answer_map · M6 answer_kind · X5 answer_aggregate · X4 다의 → 통과 · X12 도메인 없는 등식 |
| C4 | M7 재판정 제거 · N1 단조 규칙 제거 · X8 correct 전이도 재해석 · S1 미증명 값으로 대입 · S4 정의 없음 → 성립 · S5 불일치 → 성립 · SEL1·SEL2 · M14 · M15 |

굵은 5종을 잡으려고 더한 픽스처: 허용 목록 빌더 **자체**가 노드마다 거부하는지 보는 테스트(`_certified_build` 직접 — 앞단 `safe_sympify` 사전 검사(속성은 `.doit`·`.subs` 만, 비기호 미분 변수는 SymPy 가 예외)나 뒷단 Poly 도메인 검사(실수·`zoo` 계수)가 우연히 같은 입력을 막아 주는 것에 기대지 않는다) · `x + 0.5 - 0.5`(평가하면 실수가 지워지는 꼴) · smallest 규칙 위반 근 선택(+대조).

3차 판에서 쓰던 변이 중 금지 목록·수치 도메인 코드에 걸린 것(Q1·Q2·N4·N5·P1·R1~R5·R7~R9·V1·VP·X7·X3·V3·V4)은 그 코드가 지워져 대상이 없다 — 같은 의미의 변이를 새 코드에 다시 걸었다(예 R1·R2·VP → A7·J3·D1, N5·X7 → C4, X3·V3 → C5·C7, Q1·Q2·N4 → M4·N3·C8).

**생존 6종 — 전부 등가(방어 중복)**:
- **A16**(다항식 판정의 '다른 기호 없음' 검사 제거)·**A17**(ZZ/QQ 도메인 검사 제거): 서로를 덮는다 — 다른 기호가 섞이면 Poly 도메인이 `ZZ[a]` 라 A17 검사가, 비유리 계수는 빌더가 애초에 만들지 못한다. 둘을 함께 지운 **A18 은 RED**(`x + a`).
- **P6**(정의 등식 판정에서 반대쪽 자유변수를 `== {x}` 대신 `x ∈`): 반대쪽에 다른 기호가 섞이면 바로 뒤의 `certified_polynomial(반대쪽, x)` 가 거부한다(A18 RED 가 그 거부를 고정).
- **X6**(다변수 부등식을 도메인으로): 그런 부등식은 같은 조건이 '섞인 조건'으로 먼저 잡혀 값 증명이 미정으로 끝난다(P2 RED 가 그 규칙을 고정).
- **S3**·**X9**: 3차 판과 같은 이유다. S3(대입 정의 등식 필터를 `names == {v, w}` 에서 `{v, w} ⊆ names` 로 넓힘)로 새로 잡히는 조건은 v 를 다른 변수와 함께 묶는 조건뿐인데, 그런 조건이 있으면 값 증명이 이미 미정으로 끝나 이 필터에 닿지 않는다. X9(정의 등식 '전부 pass' → '하나라도 pass'): 이 자리에 닿는 정의 등식은 `w = (v 의 허용 목록 다항식)` 꼴뿐이고 그 대입 판정은 늘 유일 실수해라 pass/fail 로만 끝나며, fail 은 앞 줄이 먼저 잡는다.

## 6. 위험·한계 (정직 스코프)

1. **main 에서 FAIL 이던 입력이 통과로 바뀌는 것은 해석 단계가 조건만으로 증명될 때뿐이고, 증명은 그 변수의 등식·도메인 부등식이 전부 허용 목록 다항식일 때만 한다**(§4-3 — 원문 구문 나무가 정수·상수 나눗셈·기호·`+ − *`·양의 정수 지수·`Derivative(다항식, 기호)`·`.doit()`·`.subs(기호, 다항식)` 만으로 이뤄진 유리 계수 다항식). 증명 = 그 다항 등식의 정확 실근 중 도메인·선택 규칙으로 값이 하나로 정해지고, 그 변수를 다른 변수와 섞는 조건이 없으며(`y = (허용 목록 다항식)` 꼴 정의만 예외), 대입은 정의 등식의 유일 실수해와 같을 것. 초월 등식(`sin`·`tan`·LambertW)·분수방정식(자동 약분 포함)·`.doit()`/`Derivative` 래퍼 속 약분·`exp(-log(…))`·0/음수 지수·허수부가 아주 작은 근에서는 증명 경로가 FAIL 을 비실패로 바꾸지 않는다(직전 세 판에서는 이 문장이 거짓이었다: 재검토 T1, 3차 RF3·RF4, 4차 B1·B3·B10·D2·D3·NR1). 검토 반례 중 이 부류는 **A10·DR2(중근)·IR2(근사 √2)·SP1(다른 변수만의 등식 섞임)·HD2(5차 다항식의 근사 실근)·DOK(`Derivative(x**3, x).doit() = 3`, `x > 0`)** 6건이고, 코퍼스 1,121건에는 0건이다(§8-2). "main FAIL → 비실패 0" 을 문자 그대로 강제하려면 단조 규칙을 "incorrect 는 절대 바꾸지 않음"으로 바꾸면 되지만, 그러면 대입 단계 인정(①의 절반)이 사라진다 — 검토자는 A10 유지를 타당하다고 판단했다.
2. **C2 도메인 PASS 의 강도는 conditions 의 충실도에 묶인다.** 도메인 제약이 발문을 충실히 옮겼는지는 보지 않는다. 다만 선택을 정답에서 역산하지 않으므로, 조건과 정답이 어긋나면 FAIL 이 난다.
3. **acceptance `unique` 탐침이 허용 목록 다항 도메인 리스트를 판정하게 됐다**(§4-4). 182건 중 3건(변수 분모 MVT 꼴)은 3차 판의 pass 에서 unverifiable 로 바뀌었다(코퍼스 solution_qa 판정·corpus_reverify 요약 영향 0). 신규 생성분도 종전보다 엄격하게 강등될 수 있다.
4. **보수 규칙이 정당한 풀이도 막는다**: 분수방정식(`x/(x + 5) = 1/3`)·약분 꼴의 정당한 값(`x*(x - 2)/(x - 2) = 3` 의 x = 3)·암묵 정의역 정의(`y = log(x)`)·초월 정의(`y = sin(x)`)·2계 도함수 정의(`y = Derivative(f, x, x).doit()` — §3-1)·변수 분모가 있는 MVT 꼴 등식(`(f(b) − f(a))/(b − a)`)·공식 진입점이 구조 불가로 거부하는 꼴(`Derivative(x**3, x).doit() - 3 = 0`)이 섞인 해석 단계는 증명하지 않는다 — 종전(main) 판정이 그대로 남는다(FAIL 이었으면 FAIL).
5. **C1(Tier1)·`verify_root_selection` 원소 1개 경로의 자동 약분 결함은 이 PR 이전부터 있고 이 PR 범위 밖이다** — RF3 의 C1 은 지금도 pass 다(이 PR 은 C4 에서 FAIL 로 잡는다). 후속 태스크 **P3-75**(`verify_answer 파싱 자동 약분: 분수방정식 무연근을 근으로 통과`)로 분리했다. 4차 검토의 우회 표기도 같다 — B1·B3·B10·`Derivative` 래퍼 꼴의 C1(Tier1)과 NR1 의 Tier1 은 main·이 브랜치 모두 pass 이고, 단일 값 나열(`x = 2, x = 2`)의 C2 는 그 위에서 PASS 다(§8-2 V6 C2 도메인 14건 중 11건 — main 도 같음). P3-75 acceptance 에 RED 기준 ⑤와 ② 정정 ⑥(금지 목록 함수 `denominator_vanishes` 는 지워졌으니 허용 목록 기준)을 `backlog.py amend` 로 붙였다.
6. **`verify_answer.py` 동시 작업(EOS-23)과의 충돌 위험** — 변경은 import 2줄(`ast`·`re`)·`__all__` 7줄·`_distinct_values` 뒤 한 구역·`verify_root_selection` 의 리스트 분해와 도메인 분기(독스트링 포함)에 모았다. 원소 1개 경로의 본문은 main 과 같다.

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

### 8-2. 회귀 대조 — main 판정기 vs 수정 판정기 (같은 입력 · 최종 판)

main = `git archive 1a1a7c8b` 로 뽑은 `src/backend`(+`docs/prompts`) 사본, 수정 = 이 워크트리. 각 실행의 모듈 경로를 `__file__` 로 확인했다. 반례 = 검토 adv1~adv8 전체 + 이 세션 추가분 96건 = 3차 판의 61건(adv1~adv5 + B1~B3·근사 중근 ND·RF5~RF8·RFC2) + 4차 adv6 B1~B14 × (C4 대입·C2 도메인) 28 · adv7 D1~D3 · adv8 NR1·NR2 · 허용 대조 DOK 2(C2 도메인·C4).

| 입력 | 건수 | main→수정 판정 전이 | main FAIL → 비실패 | main PASS → 비PASS |
|---|---:|---|---:|---:|
| 코퍼스(대표 과정 승인 문항) | 1,121 | pass→pass 456 · unv→pass 92 · unv→unv 573 | **0** | **0** |
| 검토 반례 전체(adv1~adv8) + 추가 | 96 | fail→fail 56 · unv→unv 18 · pass→pass 11 · unv→pass 5 · fail→pass 6 | **6** — 전부 허용 목록 다항 등식 증명(아래) | 0 |

| 반례 | main | 수정 | 근거 |
|---|---|---|---|
| A1·A2·A2b·B1 근을 빠뜨린 나열 | 검증 불가 | 검증 불가 | `C2_DOMAIN_CANDIDATES_INCOMPLETE` |
| N4a 근사 중복으로 √2 누락 | 검증 불가 | 검증 불가 | 수치 기준 완전성(재검토 중2) |
| ND 중근 근처 값 2.00001 | 검증 불가 | 검증 불가 | 조건 단독 unique 확인 |
| A3·A3b·A3c·A3d·A3e·SP2 틀린 값·틀린 선택 | FAIL | FAIL | 미증명 — incorrect 유지 |
| A4 정의 없는 변수 전환 | FAIL | FAIL | 중4 |
| A5 후보 밖 값 · B3·LS1·LS3·LS4 선택 규칙 위반 | FAIL | FAIL | 동치 판정·C1 |
| T1 `sin(x) = 1` 값 대입 | FAIL | FAIL | 초월 등식 — 증명 안 함(재검토 상1) |
| T2 LambertW · T3 `tan(x) = 1` 선택 · T4·T4b `sin` + largest | 검증 불가 | 검증 불가 | 초월 등식(T4 는 C1 주근 관례상 하로 분류됐지만 같은 가드로 막힌다) |
| MV1 · MV2 `x + z > 100` 섞인 제약 | FAIL | FAIL | 섞인 조건 — 증명 안 함(재검토 MV2) |
| A6·A7 선택 근거 없음 · A9 삼각 후보 | 검증 불가 | 검증 불가 | |
| IR3 정답 없음 | FAIL | FAIL | C1 |
| B2·DR1·IR1·LS2·DOK(C2 도메인) | 검증 불가 | **PASS** | 판정 확장 — 다항 등식으로 증명(LS2 는 C1 이 도메인 리스트를 읽게 된 결과) |
| **A10** `a²−4=0 → a=-2, a=2 → a=2 → y=5`(`a>0`·`y=a²+1`) | FAIL | **PASS** | 다항 등식 증명 · 검토자 유지 동의 |
| **DR2** `(x-2)²(x+1)=0`·`x>0` 에서 `x=2 → y=4`(`y=x²`) | FAIL | **PASS** | 중근 다항 등식 증명 |
| **IR2** `x²=2`·`x>0` 에서 `x=1.4142135623730951 → y=3`(`y=x²+1`) | FAIL | **PASS** | 다항 등식 증명(근사 소수 근) |
| **SP1** A10 조건 + `b = 7` 에서 `a=2 → y=5` | FAIL | **PASS** | 다른 변수만의 등식은 a 를 제약하지 않음 |
| **HD2** `x⁵ − x − 1 = 0` 에서 `x = 1.1673… → y = x + 1` | FAIL | **PASS** | 실근이 하나인 다항 등식 증명(근사 소수 근) |
| **DOK** `Derivative(x**3, x).doit() = 3`·`x > 0` 에서 `x = -1, x = 1 → x = 1 → y = 6`(`y = x + 5`) | FAIL | **PASS** | 허용 목록 다항식(다항식의 미분) 증명 — 4차 지시의 정당 대조 |
| V6 B1~B14 · C4 대입(`x = 2 → y = 3`, `y = x + 1`) — `.doit()`·`.subs`·`exp(-log)`·`Derivative` 래퍼·`sqrt` 분모·음수/0 지수·0 분자·`Abs` 비·우변 분모·`*1/2` 분모·중첩 분모·`exp(log)` | FAIL | FAIL | 허용 목록 밖 — 증명 안 함(4차 상1). 같은 14꼴의 `verify_root_selection([등식, "x > 0"], {x: 2}, "unique")` 도 전부 unverifiable |
| V6 B1~B14 · C2 도메인(`x = 2, x = 2`, `x > 0`) | PASS 11 · 검증 불가 3 | 같음 | 서로 같은 값의 나열이라 C2 단일 값 경로(도메인 판정 아님) + C1 Tier1 pass — 이 PR 이전 결함, P3-75(§6-5) |
| D1 미분 래퍼 속 약분 · C2 도메인 | 검증 불가 | 검증 불가 | 허용 목록 밖 → 종전 사유 `C2_ROOT_CHOICE_UNSTRUCTURED` |
| D2 근 선택 → 대입 · D3 단일 값 대입 | FAIL | FAIL | 허용 목록 밖 — 증명 안 함 |
| NR1 `(x - 1)**2 + 10**(-20) = 0` · NR2 `… + 1/10**12` | FAIL | FAIL | 정확 실근 0개 → 값이 근에 대응하지 않음 |
| RF1~RF6 자동 약분 분수방정식(무연근 x = 2 · 표기 변형 포함) | FAIL | FAIL | 원문 분모 — 증명 안 함(3차 상1) |
| RF7 `x*(x - 2)/(x - 2) = 3` 의 x = 3 · RF8 `x/(x + 5) = 1/3` 의 x = 5/2 | FAIL | FAIL | 분수방정식 — 보수(정당하지만 증명 안 함, §6-4) |
| RFC2 무연근 섞인 후보 나열(C2) | 검증 불가 | 검증 불가 | 분수방정식 — 도메인 완전성 판정 안 함 |
| ID1·ID2 `y = log(x)` · TD1·TD2 `y = sin(x)` · CH1·CH2·NB1~NB3 정의 사슬·섞인 제약 · AM1·AM2 · HD1·HD3·HD4 | FAIL | FAIL | 암묵 정의역·비다항 정의·섞인 조건은 증명 안 함 · C1 |

### 8-3. 재검토(HEAD `348d7277`) 결함과 처리

| # | 결함(검토 문언 요지) | 반례 | 처리 | 확인 |
|---|---|---|---|---|
| 상1 | `_judge_value` 의 도메인 없는 경로가 원소 1개 `verify_root_selection` 을 타 다항 가드가 없음 — 초월 등식의 부분 해가 '유일 근 증명' | T1 `sin(x)=1` 대입(main FAIL → PASS) · T3 `tan(x)=1` 선택 | 증명은 `classify_solvability` 가 unique/multiple(실근 있는 다항 등식)일 때만, 아니면 미정(단조 규칙상 incorrect 유지). T4(`sin` + largest)도 같은 가드로 막았다 | T1 FAIL · T3·T4 검증 불가 · 변이 P1 RED |
| 중2 | N4 는 등가 변이가 아님 — 완전성이 후보 중복은 정본 채점기로, 근 여부는 수치로 섞어 셈 | N4a `-1.4142135623730951, -sqrt(2), 0` | 완전성의 서로 다름을 수치 기준(1e-9)으로 통일 · N4a(코드 단언)·5e-15 차 소수·중근 근처 값 픽스처 | N4·Q1·Q2 RED |
| (추가) | 증명이 그 변수를 다른 변수와 섞는 조건을 무시 | MV2 `x + z > 100`(main FAIL → 검증 불가) | 섞인 조건이 있으면 미정 — `y = f(x)` 꼴 정의 등식만 예외(대입 목표 등식 면제는 이 예외와 겹쳐 지움) | MV2 FAIL · 변이 P2~P6 RED |
| 하3 | 보고서 서술 정정 | — | §5-2 N4 정정 · §6-1 "다항 증명뿐" 으로 정정(직전 판에서는 거짓이었음) · §8-2 에 DR2·IR2·SP1 추가, T1 부류 차단 기재 | 이 문서 |

### 8-4. 재검토 반영 후 검증 (이 커밋 트리)

| 잡 | 명령 | exit |
|---|---|---:|
| backend | `python -m ruff check . ../../tests/backend ../../tests/constitution` (src/backend) | 0 |
| backend | `python -m black --check --line-length 100 . ../../tests/backend ../../tests/constitution` | 0 |
| backend | `python -m mypy --strict whymath_backend` (805 파일) | 0 |
| backend | `lint-imports` | 0 |
| backend | `python -m pytest -c src/backend/pyproject.toml --rootdir=src/backend tests/backend/harness tests/backend/l3 tests/backend/ops -n auto --dist loadfile`(마커 필터 없음 · `data_pipeline` 경로 추가) — 10,662 passed · 88 skipped · 3 xfailed | 0 |
| backend | `python -m whymath_backend.harness.solution_qa` — 548·0·573 | 0 |
| harness-integrity | `backlog.py validate` · `audit_ratchet.py` | 0 · 0 |
| policy-guard | `cp949_guard.py` | 0 |

이 판에서도 백엔드 전체 스위트(api·l1·l2·l4)·tests/infra·tests/harness·corpus_reverify 40은행 대조는 다시 돌리지 않았다(§7-1 에서만). 재검토 반영은 `solution_qa.py` 의 판정 분기와 그 테스트·이 문서뿐이다. 전체 판정은 CI에 넘긴다.

### 8-5. 3차 검토(HEAD `d991d18d`) 결함과 처리

| # | 결함(검토 문언 요지) | 반례 | 처리 | 확인 |
|---|---|---|---|---|
| 상1 | `_judge_value`·C2 완전성이 약분 가능한 유리식에서 거짓 증명 — 평가 파싱이 `x*(x - 2)/(x - 2)` → `x` 로 약분해 '다항·실근 1개'로 분류, Tier1 도 x = 2 를 pass | RF3·RF4(main FAIL → PASS) | 조건 원문을 비평가 구조(`safe_sympify(…, evaluate=False)`)로 보고 그 변수를 담은 분모(음수 지수 거듭제곱의 밑)가 있으면 증명하지 않음(단조 규칙상 종전 판정 유지) · C2 는 분수방정식이면 종전 사유로 · `verify_root_selection` 도메인 경로는 근에서 원문 분모 0/판정 불가면 unverifiable | RF1~RF6 FAIL · RFC2 검증 불가 · 대조 `x*(x-2)/(x-2) = 3` 근 선택 pass · 변이 R1~R5·R9 RED |
| 하2 | `_defines_other_variable` 정의 예외가 f 의 암묵 정의역(log·sqrt·1/(x−a))을 무시 | ID1(smallest 와 비교해 근 선택 거짓 incorrect) | f 가 구조상 x 의 다항식일 때만 정의로 면제 | ID1 근 선택 판정 불가(대입에서 종전 FAIL) · 변이 R6~R8 RED |
| 후속 | C1(Tier1)의 같은 자동 약분 결함(이 PR 이전부터) | RF3·RF4 의 C1 pass | 후속 태스크 **P3-75-verify-answer-autocancel-spurious-root** 등재(`backlog.py add` — P3-72 는 원격 예약 충돌로 CLI 가 P3-75 제안) | `backlog.py validate` 0 |

### 8-6. 3차 검토 반영 후 검증 (이 커밋 트리)

| 잡 | 명령 | exit |
|---|---|---:|
| backend | `python -m ruff check . ../../tests/backend ../../tests/constitution` (src/backend) | 0 |
| backend | `python -m black --check --line-length 100 . ../../tests/backend ../../tests/constitution` | 0 |
| backend | `python -m mypy --strict whymath_backend` (805 파일) | 0 |
| backend | `lint-imports` | 0 |
| backend | `python -m pytest -c src/backend/pyproject.toml --rootdir=src/backend tests/backend/harness tests/backend/l3 tests/backend/ops -n auto --dist loadfile` — 10,690 passed · 88 skipped · 3 xfailed | 0 |
| backend | `python -m whymath_backend.harness.solution_qa` — 548·0·573 | 0 |
| harness-integrity | `backlog.py validate`(P3-75 등재 후) · `audit_ratchet.py` | 0 · 0 |
| policy-guard | `cp949_guard.py` | 0 |

시뮬레이션(§3)은 이 판에서 다시 돌려 같은 수치를 확인했다((가) 565·55·501 · 0.55308, (가)+(나) 552·55·514 · 0.54148). 이 판에서도 백엔드 전체 스위트·tests/infra·tests/harness·corpus_reverify 40은행 대조는 다시 돌리지 않았다(§7-1 에서만).


### 8-7. 4차 검토(HEAD `3813ddb0`) 결함과 처리 — 금지 목록 → 허용 목록

| # | 결함(검토 문언 요지) | 반례 | 처리 | 확인 |
|---|---|---|---|---|
| 상1 B1 | 분모 가드가 `.doit()` 래퍼로 우회 — 비평가 파싱에서도 `.doit()` 이 실행돼 약분된 식이 보인다 | `(x*(x - 2)/(x - 2)).doit() = 2` 에서 `x = 2 → y = 3`(main FAIL → PASS) | 증명 경로 전체를 **허용 목록**으로 전환(§4-3). 원문을 실행하지 않고 `ast` 구문 나무에서 허용 노드만으로 식을 세운다 — `.doit()` 은 항등으로만 읽으므로 그 안의 변수 분모 `/(x - 2)` 가 그대로 거부된다 | B1 C4 FAIL · `verify_root_selection` 도메인 경로 unverifiable · 변이 A7·A9 RED |
| 상1 D1~D3 | `Derivative(x**3*(x - 1)/(x - 1), x).doit() = 3` — 미분 래퍼 속 약분 | D1 C2 도메인 · D2 근 선택 → 대입 · D3 단일 값 대입 | 미분은 **다항식 안쪽**일 때만(안쪽도 같은 허용 목록) | D1 검증 불가(`C2_ROOT_CHOICE_UNSTRUCTURED` — 종전 사유) · D2·D3 FAIL |
| 상1 B3·B10 | 분모 없이 같은 효과 | B3 `x*(x - 2)*exp(-log(x - 2)) = 2` · B10 `x*(x - 2)**0 = 2` | 함수 호출 전부·0/음수 지수 거부 | B3·B10 C4 FAIL · 변이 A1·A2·A3 RED |
| 중 NR1 | 허수부가 아주 작은 근을 실근으로 셈 | `(x - 1)**2 + 10**(-20) = 0` 에서 `x = 1 → y = 2` | 실근을 수치 허용치가 아니라 정확 계산(`real_roots`·제곱 인수 제거)으로 센다 · 값 → 근 대응만 수치(유일 대응 필수) | NR1·NR2 C4 FAIL · 변이 C1·C8 RED |
| 정리 | 중복 금지 목록 가드 | — | `has_variable_denominator`·`denominator_vanishes`·`is_polynomial_expression`·`satisfies_domain`·`_numeric_distinct_count`·옛 다항 가드·무연근 가드 삭제(호출부 grep 0) | §4-3 |
| 하3 | §4-4 182건 수치 | 검토자 실측 pass 170 · unv 12 · fail 0 | 이 판 재측정 pass 167 · unv 15 · fail 0 — 차이 3건은 변수 분모 MVT 꼴의 정당한 거부 | §4-4 |
| 하4 | P3-75 acceptance 에 우회 입력 RED 기준 | — | `backlog.py amend --acceptance` 로 ⑤(`.doit()`·`exp(-log)`·`**0`·NR1 RED)·⑥(② 의 `denominator_vanishes` 재사용 정정 — 허용 목록 기준) 추가 | YAML 재확인 · `backlog.py validate` 0 |

### 8-8. 4차 검토 반영 후 검증 (이 커밋 트리)

| 잡 | 명령 | 결과 | exit |
|---|---|---|---:|
| backend | `python -m ruff check . ../../tests/backend ../../tests/constitution` (src/backend) | All checks passed | 0 |
| backend | `python -m black --check --line-length 100 . ../../tests/backend ../../tests/constitution` | 1,995 파일 변경 없음 | 0 |
| backend | `python -m mypy --strict whymath_backend` | 805 파일 문제 없음 | 0 |
| backend | `lint-imports` | 4 kept · 0 broken | 0 |
| backend | `python -m pytest -c src/backend/pyproject.toml --rootdir=src/backend tests/backend/harness tests/backend/l3 tests/backend/ops -n auto --dist loadfile`(마커 필터 없음 · `data_pipeline` 경로 추가) | 10,747 passed · 88 skipped · 3 xfailed | 0 |
| infra-contracts | `python3 -m pytest tests/infra/test_cas_parse_entrypoint_governance.py`(R22-03 — 구문 나무 빌더가 CAS 파서 호출로 잡히지 않음) | 15 passed | 0 |
| backend | `python -m whymath_backend.harness.solution_qa` | 1,121 · 548 · 0 · 573 (3차 판과 문항 단위 동일) | 0 |
| backend | `python -m whymath_backend.harness.corpus_reverify`(40개 은행) | 은행별 요약 main 전과 40개 전부 동일 | 0 |
| 회귀 대조 | main 사본 vs 이 트리 — 코퍼스 1,121 · 반례 96(adv1~adv8) | §8-2 (main PASS → 비PASS 0 · main FAIL → 비실패는 허용 목록 증명 6건뿐) | — |
| 뮤테이션 | 78종(§5-2) | 72 RED · 등가 6 | — |
| 시뮬레이션 | `sim_ga`·`sim_na`(na·both) | §3 표 | 0 · 0 · 0 |
| harness-integrity | `backlog.py validate`(P3-75 amend 후) · `backlog.py audit-deps` · `audit_ratchet.py`(단계 2 · 차단 0 ≤ 기준선 0) | | 0 · 0 · 0 |
| harness-integrity | `python3 -m pytest -n 4 tests/harness` | 2,307 passed · 3 skipped | 0 |
| policy-guard | `cp949_guard.py` · `check_conflict_markers.py` | 위반 0 · 위반 0 | 0 · 0 |

이 판에서도 백엔드 전체 스위트(api·l1·l2·l4)·tests/infra 전체는 다시 돌리지 않았다(§7-1 에서만). 4차 반영은 `solution_qa.py`·`verify_answer.py` 의 판정 구역과 두 테스트 파일·이 문서·P3-75 acceptance 뿐이다. 전체 판정은 CI에 넘긴다.
