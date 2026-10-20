# P3-71 — Solution QA 판정기 확장: 해석 단계(근 선택·대입) + 도메인 제약 근 선택 (2026-10-20)

판정 기준: main 1a1a7c8b

브랜치 `claude/p3-solution-qa-judge-extension` · 태스크 `P3-71-solution-qa-judge-interpretive-steps` · 선행 분석 = P3-62 착수 판정(규칙 (가)는 현행 판정기에서 거짓 실패 72건, (나)는 순증 0).

생성기·코퍼스·감사 사본은 **한 바이트도 바꾸지 않았다.** 바뀐 것은 판정기 두 파일(`harness/solution_qa.py`·`l3/verify_answer.py`)과 테스트뿐이다. 아래 §2의 "실측"은 그 상태에서 CLI를 돌린 값이고, §3의 "시뮬레이션"은 P3-62 규칙을 **메모리 위에서만** 레코드에 적용해 본 예상값이다(커밋된 코퍼스와 무관). 두 표를 섞어 읽지 않는다.

---

## 0. 한 문단 요약 (초보자용)

검사기가 "풀이의 이웃 줄이 같은 식인가(동치)"만 볼 줄 알아서, 풀이가 `a = -6, a = 6` 다음에 `a = 6`(양수 근을 고름)이나 `x = 3` 다음에 `y = 4`(값을 대입)처럼 **해석하는 줄**을 쓰면 "틀렸다"고 했다. 이번에 그런 줄을 **문항 조건으로** 판정하게 했다 — 조건에 `a > 0` 이 있으면 그 근을 고른 것이 맞는지, 조건에 `y = 2x³ − …` 가 있으면 대입한 값이 맞는지를 SymPy로 계산한다. 조건에 근거가 없으면 통과가 아니라 "판정 불가"다. 같은 원리로, 풀이가 근 두 개를 나열하고 끝나는 문항도 조건의 `a > 0` 으로 하나를 걸러 정답과 맞는지 보게 했다. 결과: 코퍼스를 건드리지 않고 **판정 가능 456 → 548건(40.68% → 48.88%)**, 실패 0건 유지, 기존 통과 456건은 전부 그대로 통과다. P3-62 규칙 (가)를 붙였을 때 생기던 **거짓 실패 72건은 0건**이 된다(시뮬레이션).

## 1. acceptance 대조

| 항목 | 결과 | 근거 |
|---|---|---|
| ① C4 해석 단계 인정 — 성립 pass·불성립 fail·판정 불가 unverifiable, 무조건 통과 금지 | **충족** | §4-1. 근 선택·대입 두 모양만 좁게 인식하고, 조건에 근거(도메인·`answer_selection`·정의 등식)가 없으면 `C4_STEP_UNVERIFIABLE`. 근거 없는 선택 단계를 통과로 바꾸는 뮤테이션 M10이 RED |
| ② 도메인 제약 읽기 + `verify_root_selection` 이 '단일 등식 + 도메인 부등식' 리스트를 받음 · 정답 역산 금지 | **충족** | §4-2. C2 도메인 분기 + `verify_root_selection` 확장(시그니처 무변경). 선택은 조건에서만 도출 — 테스트 `test_selection_is_never_derived_from_the_answer`·`test_substitution_after_candidates_without_a_rule_is_unverifiable` |
| ③ 기준 완화 금지 — 확장마다 주입 RED · 기존 passed 456 중 failed 전환 0 · total 1,121 불변 | **충족** | §5 주입 테스트(합성 + 실 코퍼스) · 뮤테이션 27종 전건 RED · §2-2 문항 ID 집합 대조(456 ⊂ 548, 실패 0) |
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

도구: P3-62 세션의 `sim.py`·`sim_ga.py` 와 같은 도출 규칙(선택은 conditions의 도메인 제약에서만 도출 — 정답 역산 없음, (가)의 덧붙임 값은 answer_map에서 기계 도출). 같은 레코드 1,121건에 같은 변형을 걸고 **판정기만** 옛/새로 바꿔 돌렸다.

| 시나리오 | 판정기 | passed | failed | unverifiable | decidable_ratio | 비고 |
|---|---|---:|---:|---:|---:|---|
| 변형 없음 | 옛 | 456 | 0 | 665 | 0.40678 | = §2 전 |
| 변형 없음 | 새 | 548 | 0 | 573 | 0.48885 | = §2 후 |
| (가) 풀이 끝에 `정답변수 = 값` 1줄 (412건) | 옛 | 456 | **72** | 593 | 0.47101 | 상승분이 전부 거짓 실패(C4_STEP_INCORRECT 72) |
| (가) | 새 | **565** | **0** | 556 | **0.50401** | 거짓 실패 72 → 0 |
| (나) 도메인에서 selection 도출 (107건) | 옛 | 456 | 0 | 665 | 0.40678 | C1_SELECTION_UNVERIFIABLE 107 |
| (나) | 새 | 548 | 0 | 573 | 0.48885 | C1_SELECTION_UNVERIFIABLE 107 → 15 |
| (가)+(나) | 옛 | 456 | 72 | 593 | 0.47101 | |
| (가)+(나) | 새 | 552 | 0 | 569 | 0.49242 | |

모든 새 판정기 시나리오에서 "변형 없음·새" 의 passed 548건은 전부 PASS로 남았다(이탈 0).

### 3-1. (가)의 거짓 실패 72건은 어디로 갔나 (새 판정기)

| 단원 | 건수 | 새 판정 | 이유 |
|---|---:|---|---|
| GRAPH-SHAPE | 25 | 검증 불가 | 후보 `x = -3, x = 4` 중 어느 x 인지 조건에 근거 없음(도메인·selection 없음). 정의 등식도 매개변수 `a` 가 섞임 |
| MONOTONICITY-EXTREMUM | 20 | 검증 불가 | 같은 이유 |
| EQUATION-APPLICATION | 9 | **통과** | 조건 `x >= 0` 이 x 를 고르고, `y = f(x)` 에 대입한 값이 맞음 |
| EQUATION-APPLICATION | 8 | 검증 불가 | 후보 3개·도메인 없음 |
| MOTION-WORD | 8 | **통과** | 조건 `x > 0` 이 x 를 고르고 대입값이 맞음 |
| VELOCITY-ACCELERATION | 2 | 검증 불가 | 정의 등식 `(…t=3…) = y` 에 t 가 없음 — 대입이 아니라 조건 재진술 |

### 3-2. P3-62에 넘기는 관찰 (생성기 규칙 설계용 — 이 태스크에서 고치지 않음)

1. **(가) 구형 계열 317건(CALC-*)은 새 판정기로도 검증 불가로 남는다.** 덧붙인 `x = 8` 의 앞 줄이 `3*(x - 4)*(x - 8)`(도함수 인수분해 — 등식도 후보 나열도 아님)이라 해석 단계 모양이 아니다. 특히 CALC-EXTREMUM-VALUE·MC 는 answer_map 의 `x` 가 실제로는 극값(`x = 108`)이라 "x 후보 → x 선택"으로 읽을 수도 없다. 규칙 (가)를 이 계열에 적용하려면 생성기가 `f'(x) = 0` 등식 → 후보 나열 → 선택 → 대입 순서의 줄을 내야 한다.
2. **GRAPH-SHAPE·MONOTONICITY 45건은 근 선택 근거가 조건에 있어야 판정된다.** 극대/극소 선택은 도메인 부등식이 아니라 `answer_selection`(P3-24 B3) 같은 구조 필드로 와야 하고, 정의 등식은 매개변수 `a` 를 대입한 꼴(`y = 2*x**3 - 3*x**2 - 72*x + 6`)이어야 한다 — 판정기는 정답 기록에서 매개변수 값을 빌려 오지 않는다(§4-1).
3. **(나)를 마지막 단계 변수 ≠ 정답 변수인 문항(VAR_NOT_ANSWER_VAR)에 붙이면 C1_SELECTION_UNVERIFIABLE 15건이 남는다.** 그 문항의 conditions 는 `y = f(x)` 정의 등식까지 담아 "단일 등식 + 도메인"이 아니다(연립). 판정기는 이것을 정직하게 판정 불가로 둔다 — (나)는 마지막 단계 변수가 정답 변수인 문항에만 적용하는 것이 맞다.

## 4. 무엇을 바꿨나

### 4-1. C4 — 해석 단계 (`solution_qa._check_c4`)

- `verify_solution`(동치 판정)을 그대로 먼저 돌린다. **correct 인 전이는 건드리지 않는다.**
- correct 가 아닌 전이만 모양을 본다(좁게):
  - **근 선택** — 앞: 같은 변수의 서로 다른 수치 후보 ≥2, 뒤: 그 후보 중 **하나**. 후보 밖 값이면 해석 단계가 아니다(동치 판정 incorrect 유지 — 테스트 `test_value_outside_the_candidates_is_not_a_selection_and_stays_incorrect`).
  - **대입** — 앞: 변수 v 의 수치 값(들), 뒤: **다른** 변수 w 의 수치 값 하나. 값이 기호식이면 해석 단계로 보지 않는다.
- 근 선택 판정: 고른 값이 그 변수의 도메인 부등식을 어기면 **incorrect**(제약 위반 근). 그다음 조건이 고르는 근(도메인으로 하나 남거나, `answer_selection` largest/smallest — 이 경우 후보가 조건 등식의 근일 때만)과 같으면 correct, 다르면 incorrect, 고를 근거가 없으면 **unverifiable**.
- 대입 판정: 앞이 후보 나열이면 먼저 같은 규칙으로 v 를 고른다(못 고르면 unverifiable — 결과값에 맞는 후보를 거꾸로 찾지 않는다). 정의 등식은 조건 중 자유변수가 **정확히 {v, w}** 인 등식만 쓴다. 대입 결과가 w 에 대한 다항 등식의 유일 실수해이고 주장값과 같으면 correct, 다르면 incorrect, 그 밖은 unverifiable.
- 판정 불가 상세에 "해석 단계 n" 을 붙여, 사람 검수 대기 목록에서 생성기 쪽 과제(근거 부재)와 판정기 쪽 과제(동치 판정 불가)를 가를 수 있게 했다.

### 4-2. C2 — 도메인 제약 근 선택 (`solution_qa._check_c2_domain`)

마지막 단계가 후보 ≥2이고 `answer_selection` 이 largest/smallest 가 아닐 때(종전 `C2_ROOT_CHOICE_UNSTRUCTURED` 자리), 아래가 **전부** 성립하면 도메인으로 판정한다. 하나라도 아니면 종전 사유 그대로다.

1. 정답이 근 자체 — answer_map 이 있고 마지막 단계 변수가 정답 변수, `answer_kind`·`answer_aggregate` 없음
2. conditions 가 "그 변수의 단일 등식 + 도메인 부등식"
3. 후보 전부가 그 등식의 근(Tier1 대입)

판정: 도메인을 만족하는 후보 1개 → 정답과 같으면 PASS, 다르면 **FAIL `C2_DOMAIN_PICK_MISMATCH`** · 0개 → **FAIL `C2_DOMAIN_NO_ADMISSIBLE_CANDIDATE`** · 2개 이상 → `C2_DOMAIN_AMBIGUOUS`(검증 불가) · 후보가 등식의 근이 아님 → `C2_DOMAIN_CANDIDATE_NOT_ROOT`(검증 불가 — 그 잘못된 단계는 C4가 잡는다).

### 4-3. `l3/verify_answer.py` — `verify_root_selection` 주변만

- `verify_root_selection`: 시그니처 무변경. 문자열·원소 1개 리스트는 종전 경로 그대로. 원소 ≥2 리스트는 `split_equation_domain` 이 "단일 등식 + 같은 변수 도메인"으로 가를 때만 받고, 실근을 도메인으로 거른 허용 근 안에서 선택한다. 답이 실근이지만 도메인 밖이면 fail. 그 밖의 리스트(연립·다른 변수 제약)는 종전처럼 unverifiable.
- 새 공개 함수 4개(같은 구역에 모음): `condition_relation`·`split_equation_domain`·`satisfies_domain`(경계 근은 기호적 0 을 먼저 가른다 — `s > 3` 에 후보 3 은 "모호"가 아니라 위반)·`verify_substituted_value`(대입 단계 판정 — 다항·유일 실수해일 때만 판정).
- `derive_selected_root` 는 바꾸지 않았다(생성기 경로 — 범위 밖).

### 4-4. 다른 호출자에 대한 영향 (실측)

`verify_root_selection` 은 `harness/corpus_reverify.py`(S6 야간 상시성)와 `l3/equivalent/acceptance.py`(생성 수용 게이트 — selection 미선언 시 `unique` 탐침)도 부른다.

- `corpus_reverify` 를 `data/corpus/*/problems.jsonl` **40개 은행 전부**에 옛/새 판정기로 돌려 은행별 요약(총·통과·실패·skip)을 대조했다 — **40개 전부 동일**, 둘 다 exit 0.
- acceptance 의 `unique` 탐침: 전 은행에서 "단일 등식 + 도메인" 리스트 조건을 가진 레코드 182건(p3_calculus1_diff 112 · p3_fill 4 · problem_variants_staging 66)을 새 판정기로 돌리면 pass 173 · unverifiable 9 · **fail 0** — 기존 문항이 생성 게이트에서 새로 강등되는 경우는 없다. 앞으로 생성되는 문항에서 도메인 안에 근이 둘 남으면 `unique` 탐침이 fail → `unverified` 강등이 된다(종전엔 판정 불가로 지나갔다) — 엄격해지는 방향이다.

## 5. 기준 완화 금지 검증 (③)

### 5-1. 주입 RED 테스트

`tests/backend/harness/test_solution_qa_interpretive_steps.py`(합성 5형 대조군 + 실 코퍼스 레코드), `tests/backend/l3/test_verify_answer_domain_selection.py`. 모든 주입은 레코드가 실제로 바뀌었는지 단언한다(`_inject` — `mutated != record`). 실 코퍼스 픽스처는 대상을 못 찾으면 실패한다(공허 통과 방지).

| 확장 | 주입 | 결과 |
|---|---|---|
| C2 도메인 | 잘못된 근 선택(정답·answer_map 을 제약 밖 근으로) — 합성·실 레코드 | FAIL `C2_DOMAIN_PICK_MISMATCH` |
| C2 도메인 | 제약 위반 근(도메인을 `a > 10` 으로 — 정답이 제약 밖) | C2 자신이 FAIL `C2_DOMAIN_NO_ADMISSIBLE_CANDIDATE` |
| C4 근 선택 | 선택 단계가 제약 밖 근을 고름 — 합성·실 레코드 | FAIL `C4_STEP_INCORRECT(해석 단계(근 선택))` |
| C4 근 선택 | `answer_selection=largest` 인데 작은 근을 고름 | FAIL |
| C4 대입 | 틀린 대입값(정답·answer_map 도 같은 틀린 값으로 맞춤) — 합성·실 레코드 | FAIL `C4_STEP_INCORRECT(해석 단계(대입))` |
| C4 대입 | 제약 밖 후보를 대입한 값 | FAIL |
| verify_root_selection | 도메인 밖 근을 답으로(unique·smallest) · 경계 근(`s > 3` 의 3) | fail |
| verify_substituted_value | 틀린 주장값 | fail |

판정 불가 쪽(통과로 새지 않는지)도 같은 파일에 있다: 근거 없는 선택·대입, 다른 등식의 후보에 selection 적용, 매개변수 섞인 정의 등식, 파싱 불가 조건, 개념형·answer_map 없음, 도메인 안 후보 둘.

### 5-2. 뮤테이션 27종 — 전건 RED

순수 파이썬 하네스(셸 이스케이프 없음)로 새 분기·가드를 하나씩 지우거나 뒤집고, 매번 ①앵커 1건 ②`mutated != orig`·길이 산술 ③원복 후 `cmp` 바이트 동일을 단언했다. 대상 테스트 = 위 두 파일 + 기존 `test_solution_qa.py`·`test_verify_answer.py`.

1회차 27종 중 26종 RED, **M2(허용 후보 0 → 검증 불가로 후퇴) 생존**: 그 주입은 C1도 FAIL로 만들어 문항 판정만 보는 단언이 초록이었다. 테스트에 C2 자신의 상태 단언을 더한 뒤 M2 재실행 RED → **27/27**.

| ID | 뮤테이션 | ID | 뮤테이션 |
|---|---|---|---|
| M1 | C2 도메인 분기 제거 | M15 | 선택: 후보 소속 요구 제거 |
| M2 | C2 허용 후보 0 → 검증 불가 | M16 | `_domain_of` 파싱 불가 무시 |
| M3 | C2 도메인 선택 불일치 → 통과 | M17 | 선택 규칙: 등식 근 가드 제거 |
| M4 | C2 후보=등식 근 가드 제거 | V1 | 근 선택: 도메인 필터 제거 |
| M5 | C2 answer_map 가드 제거 | V2 | 근 선택: 리스트 분해 제거 |
| M6 | C2 answer_kind 가드 제거 | V3 | 도메인: 정확 경계 판정 제거 |
| M7 | C4 해석 단계 재판정 제거 | V4 | 도메인: 위반 무시 |
| M8 | 선택: 제약 위반 근 → 통과 | V5 | 분해: 등식 둘 허용 |
| M9 | 선택: 규칙 불일치 → 통과 | V6 | 분해: 다른 변수 허용 |
| M10 | 선택: 근거 없음 → 무조건 통과 | V7 | 대입: 불일치 → 통과 |
| M11 | 대입: 불일치 → 통과 | V8 | 대입: 유일성 요구 완화 |
| M12 | 대입: 후보 선택 생략 | V9 | 대입: 다항 가드 제거(`tan(y) = x` 반례) |
| M13 | 대입: 매개변수 등식 허용 | V10 | 대입: 자유변수 검사 제거(사유 단언) |
| M14 | 해석 단계: 수치 값 요구 제거 | | |

뮤테이션 실행 뒤의 변경은 docstring 줄바꿈·black 포맷뿐이다(로직 무변경).

## 6. 위험·한계 (정직 스코프)

1. **변수가 바뀌는 단계의 판정이 incorrect → unverifiable 로 바뀔 수 있다.** 종전 동치 판정은 `x = 3 → y = 4` 를 늘 incorrect 로 냈다. 이제 조건에 정의 등식이 없거나 선택 근거가 없으면 unverifiable 이다. acceptance ①이 요구한 의미론이고, 현 코퍼스에는 이런 전이가 0건이라(§2-1 C4 불변) 지금 바뀐 판정은 없다. 그러나 앞으로 근거 없는 대입 단계를 쓰는 생성기는 FAIL 이 아니라 사람 검수 대기로 간다.
2. **C2 도메인 PASS 의 강도는 conditions 의 충실도에 묶인다.** P3-07 문서의 단서와 같다 — 도메인 제약이 발문을 충실히 옮겼는지는 보지 않는다. 다만 선택을 정답에서 역산하지 않으므로, 조건의 도메인과 정답이 어긋나면 FAIL 이 난다.
3. **acceptance `unique` 탐침이 도메인 리스트를 판정하게 됐다**(§4-4). 기존 문항 영향 0을 실측했지만, 신규 생성분은 종전보다 엄격하게 강등될 수 있다.
4. **`verify_answer.py` 동시 작업(EOS-23)과의 충돌 위험** — 변경은 `__all__` 4줄과 `_distinct_values` 뒤 한 구역(새 함수 4개 + `verify_root_selection` 본문)에 모았다.
