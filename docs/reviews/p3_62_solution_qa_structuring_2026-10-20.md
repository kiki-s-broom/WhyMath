# P3-62 — Solution QA 검증 불가 665건 구조화

판정 기준: main 1a1a7c8 (1차 착수 판정 §1~§5) · main 4f0e6652 (재개 판정) · main 25898155 (2단계 — §B 생성기 반영·후보 은행 실측) · **main 3a83ed64 (3단계 — §C S5 감사·재측정)**

현재 상태(2026-10-31 · §C): S5 감사를 실행했다 — calc 후보 통과(k = 1) · fill 후보 불합격(k = 11, 전부 구조화와 무관한 기존 템플릿 문장). 런북상 두 은행 모두 통과해야 승격하므로 승격하지 않았고, 현 main 검증 가능 비율은 0.48885 그대로다(후보 두 은행 0.52542 · calc만 0.51115).

이전 상태(2026-10-21): 규칙 (가)를 P3 생성기에 넣었다(기본 꺼짐 · 후보 모드 `--structure-final-step`).
후보 은행은 **스크래치(저장소 밖)에서만** 만들었고, 커밋된 승인 은행 두 개는 한 바이트도 바꾸지 않았다.
후보로 1,121건을 재면 통과 589 · 실패 0 · 검증 불가 532, 검증 가능 비율 0.52542다(현 main 0.48885 대비 +41건).
승격하려면 새 회차 S5 감사(LLM 판정자 A·B)가 필요하고, 그 단계는 이 컨테이너에서 실행할 수 없다.
→ 런북 `docs/reviews/p3_62_s5_candidate_audit_runbook_2026-10-21.md`.
아래 §1~§5와 '재개 판정'은 당시 기록을 그대로 남긴 것이다(as-found).

## 1. 사유 × 생성기 귀속표 (①)

기준선 큐 665건을 slug로 은행 파일에 대조했다. 665/665건 모두 정확히 은행 1곳에서 찾았다.

| 사유 | 단원 | 은행 | 생성기(모듈.클래스 / 풀이 단계 함수) | 건수 | 허용 경로 안 |
|---|---|---|---|---|---|
| C2_FINAL_STEP_NOT_ANSWER_FORM | CALC-EXTREMUM | generated_v0 40 · rephrased_v0 37 | calculus_skeleton_generator.CalculusExtremumSkeletonGenerator / `_extremum_steps` | 77 | ✗ |
| 〃 | CALC-EXTREMUM-IRR | generated_v0 | 〃.CalculusIrrationalExtremumSkeletonGenerator / `_irrational_extremum_steps` | 30 | ✗ |
| 〃 | CALC-EXTREMUM-MC | generated_v0 30 · rephrased_v0 26 | 〃.CalculusExtremumMCSkeletonGenerator / `_extremum_steps` | 56 | ✗ |
| 〃 | CALC-EXTREMUM-VALUE | generated_v0 40 · rephrased_v0 34 | 〃.CalculusExtremumValueSkeletonGenerator / `_extremum_steps` | 74 | ✗ |
| 〃 | CALC-TANGENT | generated_v0 40 · rephrased_v0 40 | 〃.CalculusTangentSlopeSkeletonGenerator / `_tangent_steps` | 80 | ✗ |
| 〃 | DIFFERENTIABILITY | conceptual_v0 | conceptual_count_mc_generator.ConceptualCountMCSkeletonGenerator | 24 | ✗ |
| 〃 | P3-CALC1-DIFF-EQUATION-APPLICATION | p3_calculus1_diff_v0 | p3_diff_equation_application_skeleton_generator | 8 | ○ |
| 〃 | P3-CALC1-DIFF-MEAN-VALUE-THEOREM | p3_calculus1_diff_v0 | p3_diff_mean_value_theorem_skeleton_generator | 6 | ○ |
| 〃 | P3-CALC1-DIFF-POWER | p3_calculus1_diff_v0 | p3_diff_power_derivative_skeleton_generator | 6 | ○ |
| C2_ROOT_CHOICE_UNSTRUCTURED | P3-CALC1-DIFF-EQUATION-APPLICATION | p3_calculus1_diff_v0 | p3_diff_equation_application | 44 | ○ |
| 〃 | P3-CALC1-DIFF-MEAN-VALUE-THEOREM | p3_calculus1_diff_v0 | p3_diff_mean_value_theorem | 49 | ○ |
| 〃 | P3-CALC1-DIFF-TANGENT-LINE | p3_calculus1_diff_v0 | p3_diff_tangent_line | 18 | ○ |
| 〃 | P3-CALC1-DIFF-VELOCITY-ACCELERATION | p3_calculus1_diff_v0 | p3_diff_velocity_acceleration | 13 | ○ |
| 〃 | P3-CALC1-DIFF-POWER | p3_calculus1_diff_v0 | p3_diff_power_derivative | 10 | ○ |
| 〃 | P3-CALC1-DIFF-GRAPH-SHAPE | p3_calculus1_diff_v0 | p3_diff_graph_shape | 6 | ○ |
| 〃 | P3-CALC1-DIFF-POLYNOMIAL-RULES | p3_calculus1_diff_v0 | p3_diff_polynomial_rules | 4 | ○ |
| 〃 | P3-CALC1-DIFF-MONOTONICITY-EXTREMUM | p3_fill_v0 | p3_diff_monotonicity_extremum | 7 | ○ |
| 〃 | P3-CALC1-DIFF-MOTION-WORD | p3_fill_v0 | p3_diff_motion_word_problem | 4 | ○ |
| C2_FINAL_STEP_VAR_NOT_ANSWER_VAR | P3-CALC1-DIFF-GRAPH-SHAPE | p3_calculus1_diff_v0 | p3_diff_graph_shape | 26 | ○ |
| 〃 | P3-CALC1-DIFF-MONOTONICITY-EXTREMUM | p3_fill_v0 | p3_diff_monotonicity_extremum | 21 | ○ |
| 〃 | P3-CALC1-DIFF-EQUATION-APPLICATION | p3_calculus1_diff_v0 | p3_diff_equation_application | 20 | ○ |
| 〃 | P3-CALC1-DIFF-MOTION-WORD | p3_fill_v0 | p3_diff_motion_word_problem | 8 | ○ |
| 〃 | P3-CALC1-DIFF-VELOCITY-ACCELERATION | p3_calculus1_diff_v0 | p3_diff_velocity_acceleration | 2 | ○ |
| C2_NO_STEPS | CALC-CHAIN | misconception_mc_v0 | misconception_eval_mc_generator.MisconceptionEvalMCSkeletonGenerator | 24 | ✗ |
| 〃 | CALC-PRODUCT | misconception_mc_v0 | 〃 | 24 | ✗ |
| 〃 | EXTREMUM-COUNT | conceptual_v0 | conceptual_count_mc_generator.ConceptualCountMCSkeletonGenerator | 24 | ✗ |

합계: 허용 경로 밖(구형 계열) **413건** = NOT_ANSWER_FORM 341 + NO_STEPS 72 / 허용 경로 안(P3 계열) **252건** = NOT_ANSWER_FORM 20 + ROOT_CHOICE 155 + VAR_NOT_ANSWER_VAR 77.
rephrased_v0 137건은 generated_v0의 풀이 단계를 그대로 복사한 파생 은행이다(`problem_corpus_rephrase`). 생성기를 고치면 이 은행도 재조정해야 한다.

### 1-1. ROOT_CHOICE 155건의 실제 모양

| 모양 | 건수 | 뜻 |
|---|---|---|
| 도메인 제약이 이미 `verify.conditions`에 있음(`a > 0`·`c >= 0, c <= 3`·`x > 0`) | 94 | 근을 고르는 조건이 "발문에만" 있지 않다. 구조에 있지만 C2가 읽지 않는다 |
| `answer_kind=real_root_count`(정답이 근이 아니라 개수) | 48 | 고를 근이 없다. 개수는 C1이 따로 검산한다 |
| 정수 범위형 조건(`f'(x) < 0` 등 — 정답 = 범위 안의 정수) | 12 | 정답이 후보의 함수다 |
| 기타 | 1 | |

## 2. P3-24 selection 필수 규칙과의 대조 (②)

- B3(02-08 극대·극소 x좌표 → `answer_selection` 필수)와 (나)는 같은 필드를 쓴다. 중복이 아니라 범위가 다르다(B3는 02-08만, 존재만 강제). 02-08(GRAPH-SHAPE) 안의 ROOT_CHOICE 6건은 극대·극소 x좌표 문항이 아니라 정수 범위형이다. 그래서 B3의 대상이 아니다.
- **충돌 1 — B3 단서**: selection은 작성자가 미리 계산한 값이고, 정답에서 역산하면 C2가 순환 통과한다. 그래서 (나)의 selection은 정답 필드가 아니라 conditions의 도메인 제약에서만 기계적으로 도출해야 한다.
- **충돌 2 — C1 재검산**: selection을 넣으면 C1이 `verify_root_selection`을 돈다. 그런데 이 함수는 단일 등식 조건만 받고, 도메인 제약이 같이 있는 리스트 조건에는 unverifiable을 낸다(`근 선택 — 단일 등식이 아님`). 실측(메모리상 시뮬레이션, 커밋 없음): 도메인 제약에서 도출한 selection을 넣으면 C2 ROOT_CHOICE는 155→61로 줄지만, **C1_SELECTION_UNVERIFIABLE이 107건 새로 생긴다** → unverifiable 665→665, decidable_ratio 0.40678 그대로. 도메인 제약을 conditions에서 빼면 C1이 다시 판정하지만, 그건 C1 검산을 약하게 만드는 일이라 할 수 없다.
- C3(극값의 값·점 → x 고정, answer_map에 x)은 VAR_NOT_ANSWER_VAR와 같은 뿌리다. answer_map이 {x, a, y}이고 풀이 단계가 x 후보에서 끝나기 때문이다. (가)와 충돌하지는 않는다. 아래 C4 문제는 따로 남는다.

## 3. 규칙 (가)(나)(다) — 현행 판정기에서 효과 실측 (시뮬레이션, 커밋 없음)

- (가) 마지막 단계에 `정답변수 = answer_map 값` 1줄을 덧붙이면(값은 answer_map에서 기계 도출): 412건이 바뀐다. 결과는 통과 456 · **실패 72(C4_STEP_INCORRECT)** · 검증 불가 593(그중 C4_STEP_UNVERIFIABLE 340)이다. C4는 이웃 단계의 동치만 보는데, 근 선택·대입 같은 해석 단계(`x = -1, x = 3` → `y = 4`)는 동치가 아니다. 그래서 거짓 실패가 생긴다. 이 경우 decidable_ratio가 0.471로 오르지만, 그 상승은 거짓 실패 72건 덕분이다. failed==0 조건도 깨진다.
- (나) 위 §2 충돌 2와 같다. 순증 0이다.
- (다) NO_STEPS 72건은 전부 구형 은행(misconception_mc_v0·conceptual_v0)에 있다. 허용 경로 밖이다.

## 4. 정지 사유

1. **승인 결속(분모 보호)**: P3 두 은행은 각인을 걷어 낸 바이트가 감사 동결 사본(`docs/data/p3_calculus1_diff_audit/bank_audit_r5/audited_bank.jsonl`·`docs/data/p3_fill_audit/bank_audit_r3/audited_bank.jsonl`)과 같아야 승인이 유효하다. 이것을 `tests/backend/l1/test_p3_calculus1_diff_bank_coverage_link.py::test_committed_bank_approval_is_bound_to_the_audited_content`와 `test_p3_fill_bank_coverage_link.py`의 같은 이름 테스트가 동결한다. 재생성으로 1바이트라도 바뀌면 길은 셋뿐이다. (a) 테스트 red (b) 승인 해제 → 분모 감소(금지) (c) 감사 없이 동결 사본 교체(감사 없는 승인 이전 · docs/data/ 경로라 허용 범위 밖). 정당한 길은 새 회차 S5 감사(기계 ∪ LLM 판정자 A ∪ B)뿐이다.
2. **허용 경로 밖 생성기**: 413건의 생성기는 `l3/equivalent/calculus_skeleton_generator.py`·`conceptual_count_mc_generator.py`·`misconception_eval_mc_generator.py`에 있다. 배치는 `harness/problem_corpus_batch.py`·`conceptual_count_mc_batch.py`·`misconception_mc_batch.py`·`problem_corpus_rephrase.py`이고, 은행은 `data/corpus/problem_bank_{generated,rephrased,conceptual,misconception_mc}_v0/`다. 이 은행들에도 감사 라벨 기반 승인(`AUDIT_LABEL_MAP`)이 있다.
3. **판정기 의존**: 위 §3 실측대로, 판정기(solution_qa C1·C4)를 바꾸지 않으면 (가)(나)로 decidable_ratio를 정직하게 올릴 수 없다. (가)는 C4가 해석 단계를 이해해야 하고, (나)는 C2가 conditions의 도메인 제약을 읽거나 C1 root_selection이 도메인 제약 리스트를 받아야 한다. 이것은 기준 완화가 아니라 판정 확장이다. 그래도 `harness/solution_qa.py`·`l3/verify_answer.py`는 금지·범위 밖이다.

## 5. 남은 결정 (Kiki/지휘자)

- A안: 판정기 확장 태스크를 먼저 둔다. C4에 해석 단계(근 선택·대입) 표기를 허용하고, C2에 conditions 도메인 제약 기반 후보 필터를 넣는다. 그다음 생성기 규칙 (가)(나)를 반영하고, 재생성 + 새 회차 감사를 한다.
- B안: 재생성 + 새 회차 S5 감사를 이 태스크에 포함한다. LLM 판정자 호출·docs/data 감사 경로 변경이 허용 범위에 들어와야 한다.
- 11/15 하한 값은 정하지 않는다(Kiki가 재측정값으로 정함, 후보 60%). 허용 경로 안 252건을 전부 해소해도 상한은 708/1121 = 63.2%다.

---

## 재개 판정 (P3-71 머지 후 · 판정 기준: main 4f0e6652)

(당시 브랜치 HEAD 09cc611f — 이 절의 해소 경로 1은 P3-76 #1710 으로 착지했다.)

## 결론: ②(생성기 반영) 착수 전 정지 — 허용 경로 밖 게이트가 규칙 (가)를 막는다

### 주입 실측 (GRAPH-SHAPE 실 레코드 wm-p3-diff-graphshape-e6551214a538, 메모리상 변형)
조건을 P3-71 허용 목록 꼴로 재구성했다(a 결정 등식 · a 대입 도함수 등식 · 선택 근거 `12*x - 6 > 0` · 정의 등식 `y = 2*x**3 - 3*x**2 - 72*x + 6`).
- 수용 게이트 `l3/equivalent/acceptance._evaluate_verification` 결과
  - 현행 풀이 → verified
  - (가) 선택+대입 2줄 추가 → **failed**(Tier2 전이 4 incorrect)
  - (가) 선택 1줄만 추가 → **unverified**(unverifiable 1)
  - 배치는 verified만 적재하므로 문항이 빠진다. 분모가 줄어든다.
- 상시 재검증 `harness/corpus_reverify._reverify_one` 결과
  - 현행 → pass
  - (가) → **fail**(Tier2 단계 incorrect: 전이 4)
- 원인: P3-71은 `solution_qa` C4에만 해석 단계(근 선택·대입) 판정을 넣었다. 수용 게이트와 corpus_reverify는 여전히 `verify_solution`(동치만)으로 Tier2를 판정한다. 두 파일 다 허용 경로 밖이다.

### 기각한 우회
풀이를 y 단독 연쇄(`y = f(4)` → `y = -202`)로 바꾸는 방법. 세 게이트는 다 통과하지만, 도함수 단계가 풀이에서 사라지고 x = 4를 근거 없이 쓰게 된다. 판정 수치를 위해 풀이 내용을 깎는 일이라 하지 않는다.

### 규칙 (나)·(다)
- (나): 남은 P3 ROOT_CHOICE 63건은 개수형 48(real_root_count — 고를 근이 없음), 정수 범위형 13(정답 = 구간 안 정수), 기타 2다. 도메인 제약 94건은 이미 P3-71 판정기가 PASS로 바꿨다. 근 선택 구조화로 풀 문항이 남아 있지 않다.
- (다): NO_STEPS 72건은 전부 구형 은행이라 범위 밖이다.

### 허용 경로 안 남은 검증 불가 160건
| 사유 | 건수 | 내역 |
|---|---|---|
| VAR_NOT_ANSWER_VAR | 77 | GRAPH-SHAPE 26 · MONO 21 · EQ-APP 20 · MOTION 8 · VELOCITY 2 — 전부 (가) 대상, 전부 위 게이트에 막힘 |
| ROOT_CHOICE | 63 | 위 (나) 항목 |
| NOT_ANSWER_FORM | 20 | EQ-APP 8 · MVT 6 · POWER 6 — 허근·지수 미지수·변수 분모 때문에 해 연쇄가 판정 불가 |

(가) 77건이 전부 풀려도 상한은 625/1121 = 0.5575다.

### S5 감사 실행 가능성 (실측)
- 기계 단계는 이 컨테이너에서 가능하다: `p3_audit_qualification bank-sheets`·`machine`·`s5`, LLM 호출 0.
- LLM 판정자 A·B(묶음 8 × 2 = 16명)는 이전 회차에서 Claude 에이전트 판정자였다(qualification/README "에이전트 도구 권한상 …").
  - 이 컨테이너에는 OpenRouter·DeepSeek 키가 없고, Ollama(11434)도 없다. Anthropic API는 ARCH-66으로 중단 상태다.
  - 이 서브에이전트에는 하위 에이전트를 띄우는 도구가 없다.
  - 그래서 판정자 단계는 에이전트를 띄울 수 있는 지휘 세션이나 Kiki가 맡아야 한다.
- 다만 재생성 은행 자체가 수용 게이트에 막히므로, 감사할 후보 은행이 아직 없다. 런북은 작성하지 않았다.

### 해소 경로 (결정 필요)
1. 수용 게이트(`l3/equivalent/acceptance.py`)의 Tier2와 `harness/corpus_reverify.py`에 P3-71과 같은 해석 단계 판정을 넣는다. 공용 함수로 승격하는 것이 좋다. 별도 태스크이고, 야간 S6 게이트 의미 변경을 동반한다.
2. 그다음 P3 생성기에 (가)를 반영한다. 반영 내용: 선택 근거(극소 f''>0 · 극대 f''<0 · 발문 도메인), a 대입 정의 등식, MOTION 2계 도함수 명시 다항식. 이어서 후보 은행을 만들고 새 회차 S5 감사를 한다.

---

## B. 2단계 — 생성기 반영·후보 은행 실측 (판정 기준: main 25898155)

선행: P3-71(#1703, Solution QA C4 해석 단계)과 P3-76(#1710, 수용 게이트·야간 재검증이 같은 판정 공유 — `verify_solution_interpreted`).
P3-76 검토 인계 두 건을 그대로 따랐다.
- ⓐ 선택 근거는 `answer_selection`이 아니라 **도메인 부등식**으로 싣는다(selection은 다변수 조건 목록에서 수용 게이트가 unverified로 강등한다).
- ⓑ 생성기는 `answer_selection`을 새로 쓰지 않는다.

### B-1. 무엇을 바꿨나 (허용 경로 안)

| 파일 | 변경 |
|---|---|
| `l3/equivalent/p3_diff_solution_steps.py` | `final_statement_steps`(근 선택·정답 변수 값 두 줄 덧붙이기)와 `explicit_definitions`(정의 등식을 명시 다항식으로 다시 쓰기)를 더했다 |
| `l3/equivalent/p3_diff_skeleton_base.py` | `DiffItem.structured_conditions`(기본 None) · 구조화 모드 `final_step_structuring`(ContextVar, **기본 꺼짐**) · `structured_view` · `_assemble`(모드가 켜졌을 때만 조건·단계 교체) · `_validate_slot`(구조화 조건은 빌드 시점에 증명 가능해야 함) |
| `l3/equivalent/p3_diff_graph_shape_skeleton_generator.py` | 틀 3종에 구조화 조건을 달았다(02-08 그래프 개형, 02-07 단조·극값 생성기가 상속): ① `_other_root_value_item`(x = p에서 극값 → 다른 극값) ② `_quartic_k_frame` 가운데 극값 ③ `_find_k_other_root_frame`(상수 k). 선택 근거는 `_kind_basis`(발문이 묻는 종류: 극소 f''>0 · 극대 f''<0), 미지 계수는 `_pin_cond`(f'(p) = 0)로 정한다 |
| `harness/p3_calculus1_diff_batch.py`·`p3_fill_batch.py` | `--structure-final-step`(후보 모드) · 승인 은행 자리 쓰기 자가거부(`refuses_structured_write` → `WRITE_REFUSED`, exit 2) · `--check`와 함께 쓰면 exit 2 · 후보 사이드카에만 `solution_structuring` 표기 |

규칙 정의:
- **(가) 풀이 끝 진술**: 근 목록(`x = -3, x = 4`)으로 끝난 연쇄 뒤에 근 선택 `x = 4`와 정답 변수 값 `y = -202`를 덧붙인다.
  - **정답 역산 금지**: 후보 하나하나로 붙인 연쇄를 공용 판정 `verify_solution_interpreted`가 **조건만으로** 전 전이 correct로 증명하는 후보가 정확히 하나일 때만 쓴다. 함수에는 정답·answer_map을 넘기는 자리가 없다(시그니처를 테스트로 동결).
  - 진술값은 조건의 정의 등식(`y = P(x)`·`k = V - P(x)`)으로 계산한다. 그 값이 정답 기록과 다르면 빌드가 멈춘다(저작 결함 — 조용히 종전 단계로 돌아가지 않는다).
  - 매개변수(a·k)를 정하는 조건은 a·k만 담는 꼴로 남겨 C1 검산이 a·k를 계속 본다(`Derivative(f(x; a), x).doit().subs(x, p) = 0`).
- **(나) 근 선택 조건**: 도메인 부등식으로만 싣는다(위 ⓐⓑ). 남은 ROOT_CHOICE 60건은 개수형·구간 안 정수형이라 고를 근이 없다. 손대지 않았다.
- **(다) 단계 없는 개념형**: 72건 전부 구형 은행이다. 범위 밖이라 손대지 않았다.
- **MOTION 2계 도함수**: `explicit_definitions`가 `y = Derivative(f, x, x).doit()`를 SymPy로 계산한 `y = -12*x - 6`으로 다시 쓴다. 같은 조건의 표기 변환이다.

### B-2. 후보 은행 — 결정론·문항 집합 보존

| 은행 | 건수 | 바뀐 레코드 | 바뀐 필드 | 같은 시드 2회 | 후보 sha256 |
|---|---:|---:|---|---|---|
| p3_calculus1_diff_v0 | 504 | 25 | `verify.conditions`·`verify.solution_steps`만 | 바이트 동일(`cmp`) | `c4f3ad11232cdafd4b02e29e454e7c74ffb42d655a9d7c28f7227536d07786a9` |
| p3_fill_v0 | 204 | 16 | 같음 | 바이트 동일 | `8ae08bd8beb088f77fc7ead40eb0d17b7b3bc3165fb839e5ba0ea7fb7b81082e` |

- slug 목록과 순서는 커밋된 승인 은행과 같다(분모 불변). 발문·정답·해설·선지·answer_map은 그대로다.
- 기본 모드 `--check`는 두 은행 모두 "드리프트 없음"으로 exit 0이다. 승인 은행·결속 테스트는 무변경이다.
- 서로 다른 프로세스 두 번(cand1·cand2) 실행의 `problems.jsonl`·`_provenance.json`이 모두 바이트 동일했다.
- 최종 코드로 한 세 번째 실행(cand3)도 cand1과 동일했다 — 결과는 §B-6에 적는다.

### B-3. 후보 실측 — Solution QA (1,121건 · P3 두 은행만 후보로 교체)

| | 현 main 기준선 | 후보 | 차이 |
|---|---:|---:|---:|
| total | 1,121 | **1,121** | 0 |
| passed | 548 | **589** | +41 |
| failed | 0 | **0** | 0 |
| unverifiable | 573 | **532** | −41 |
| decidable_ratio | 0.48885 | **0.52542** | +0.03657 |
| C2_FINAL_STEP_NOT_ANSWER_FORM | 361 | 361 | 0 |
| C2_FINAL_STEP_VAR_NOT_ANSWER_VAR | 77 | **39** | −38 |
| C2_ROOT_CHOICE_UNSTRUCTURED | 63 | **60** | −3 |
| C2_NO_STEPS | 72 | 72 | 0 |

- 측정 방식: `python -m whymath_backend.harness.solution_qa <합본.jsonl>`(exit 0)으로 쟀다. 합본은 대표 과정 1,121건 원본 행에서 P3 두 은행의 708건만 후보 행으로 바꾼 것이다(problem_id 대조 708/708).
- 같은 방식으로 기준선 합본을 재면 548/0/573이다. CLI 기본 모드 실측과 같으므로 측정 경로가 같다.
- 새로 판정 가능해진 41건의 단원: GRAPH-SHAPE 14 · EQ-APP 11 · MOTION-WORD 8 · MONOTONICITY 8.
- 새로 검증 불가가 된 문항은 0건이다. 기존 통과 548건은 전부 통과로 남았다.

**수용 게이트·야간 재검증 (후보 708건 전수):**
- 수용 게이트 `_evaluate_verification`: **verified 708/708**.
- `corpus_reverify._reverify_one`: **pass 708/708**.
- 기준선(커밋된 은행)도 708/708·708/708이다.
- 적재 파싱 `populate._record_from_line`(P3-24 02-08 파생 판정 규칙 포함): 위반 0/708.
- 우회로 판정기 `shortcut_violations`(구조화 조건으로 다시 본 41건): 위반 0.

### B-4. S5 감사 — 기계 단계 실측 (후보 · 이 컨테이너)

| 단계 | calc 후보 (504) | fill 후보 (204) |
|---|---|---|
| `bank-sheets`(seed 20261008) | exit 0 · 8묶음 × 63 · 지침 sha `3046a901…` | exit 0 · 4묶음 × 51 |
| `machine --id-field problem_id` | exit 0 · **결함 0/504** | exit 0 · **결함 0/204** |
| `s5`(판정자 라벨 없이) | exit 2 — `QualificationInputError: 판정자 라벨 0개 — 2명 이상이 필요하다` | 실행 안 함(같은 사유) |

LLM 판정자 단계는 실행하지 못했다. 이 컨테이너에는 OpenRouter·DeepSeek 키가 없고 Ollama도 없다. Anthropic API는 ARCH-66으로 중단 상태다.
이전 회차 판정자는 Claude 에이전트였고, 이 서브에이전트에는 하위 에이전트를 띄우는 도구가 없다.
그래서 **지휘 세션이 서브에이전트 판정자 24명(calc 16 + fill 8)을 돌리는 방안**을 런북 §3에 지시문·격리 규칙·산출 검사와 함께 적었다.
Kiki 머신은 필요 없고, Kiki의 몫은 승격 승인이다.
- fill 은행은 n = 204라 **k = 0만 통과**한다. 결함 1건이면 그 회차는 불합격이다(as-found · 새 은행으로 재감사).

### B-5. 남은 검증 불가 (허용 경로 안 119건) — 원인

| 사유 | 단원 | 건수 | 원인 |
|---|---|---:|---|
| VAR_NOT_ANSWER_VAR | GRAPH-SHAPE 12 · MONO 14 | 26 | ① 미지수 a·b를 연립으로 구하는 틀(`_find_ab_item`·`_find_b_*`): 정답이 a·b라 `a = P(x)` 정의 등식이 없다 ② 같은 종류 두 극값 중 큰/작은 값(f'' 부호로 하나가 정해지지 않는다). 판정기가 증명하지 못하는 꼴이라 단계를 붙이지 않았다 |
| VAR_NOT_ANSWER_VAR | EQ-APP | 11 | 사차함수 전역 최솟값(극소 두 개 중 작은 값 · 도메인 없음) — 선택 근거를 다항 부등식으로 쓸 수 없다 |
| VAR_NOT_ANSWER_VAR | VELOCITY | 2 | '처음' 운동 방향을 바꿀 때 — 시각 t가 조건에 없고 '처음'은 도메인 부등식이 아니다 |
| ROOT_CHOICE | EQ-APP 42 · GRAPH 6 · MVT 6 · MONO 6 | 60 | 정답이 근이 아니라 개수(real_root_count)이거나 구간 안 정수다 |
| NOT_ANSWER_FORM | EQ-APP 8 · MVT 6 · POWER 6 | 20 | 허근 섞인 인수분해·지수 속 미지수·변수 분모 — 해 연쇄를 이웃 동치로 판정할 수 없다 |

허용 경로 밖 413건(구형 4개 은행)은 그대로다(§1 귀속표).

### B-6. 검증 (판정은 exit code)

| 검사 | 명령 | exit |
|---|---|---|
| 승인 은행 드리프트 | `p3_calculus1_diff_batch --check` · `p3_fill_batch --check` | 0 · 0 |
| 후보 생성 2회 + 최종 코드 1회 | `--structure-final-step --out-dir <스크래치>` × 3 | 0(6회 전부) · 바이트 동일 |
| ruff | `python -m ruff check . ../../tests/backend ../../tests/constitution` (src/backend) | 0 |
| black | `python -m black --check --line-length 100 . ../../tests/backend ../../tests/constitution` | 0 |
| mypy | `python -m mypy --strict whymath_backend` | 0 (806 파일) |
| import 계약 | `lint-imports` | 0 (4 kept) |
| 신규 테스트 | `test_p3_62_final_statement.py`(15) · `test_p3_62_structured_candidate.py`(3, corpus_authoring) | 0 (18 passed) |
| 뮤테이션 | 규칙 절 9종 — cp 백업 → 주입(앵커 1건·변경 단언) → pytest → cp 원복(바이트 단언) | **9/9 RED** |

뮤테이션 9종:
1. 선택 증명 생략
2. 진술값↔정답 대조 제거
3. 모드 무시
4. 정의 등식 명시화 제거
5. 쓰기 자가거부 제거
6. 극대·극소 근거 부호 뒤집기
7. 증명 실패 구조화 조건 침묵
8. k 정의 틀 구조화 제거
9. 정답 변수 판별 무력화

전체 스위트(코드 확정 뒤 트리 무변경 상태에서 실행):

| 잡(CI와 같은 명령) | 결과 | exit |
|---|---|---|
| backend `python -m pytest -m "not corpus_authoring" -n auto --dist loadfile --cov=whymath_backend --cov-fail-under=70` (src/backend) | 21,731 passed · 713 skipped · 1 xfailed · 커버리지 87.69% | 0 |
| corpus-authoring `python -m pytest -m corpus_authoring` (src/backend) | 893 passed · 1 skipped · 2 xfailed | 0 |
| infra-contracts `python3 -m pytest tests/infra -q` | 3,221 passed · 27 skipped | 0 |
| harness-integrity `python3 -m pytest tests/harness -q` | 2,307 passed · 3 skipped | 0 |

backend 잡의 나머지 게이트 스텝(계층 커버리지·게이트 CLI 등)과 mobile·web 잡은 이 세션에서 돌리지 않았다 — CI가 판정한다.

### B-7. 한계

1. **후보는 감사 전이다.** 승인 은행이 아니며, 수치(589/0/532)는 승격 후 기대값일 뿐 현재 main의 Solution QA 값이 아니다. 현재 main은 548/0/573 그대로다.
2. **구조화 모드 스위치는 기본 꺼짐이다.** 승격 때 기본값을 켜는 코드 변경이 함께 필요하다(런북 §5-4). 꺼진 채로 은행만 바꾸면 `--check`가 드리프트로 red가 된다.
3. **선택 근거(f'' 부호)는 '극소/극대'라는 발문의 종류에서 나온다.** 그 종류가 발문과 맞는지는 생성기 틀 설계에 달려 있다(P3-24 B3 단서와 같은 축). 다만 근거가 정답과 다른 근을 가리키면 진술값이 정답 기록과 달라져 빌드가 멈춘다(반례 테스트 · 뮤테이션 M2·M6).
4. 11/15 검증 가능 비율 하한 값은 정하지 않는다. Kiki가 (다)·승격 실측 뒤 정한다(후보 60%).
   - 이 후보까지의 허용 경로 안 상한은 0.5575다(VAR 77건 전부 해소 가정).
   - 60%에 닿으려면 구형 은행(허용 경로 밖 413건)이 필요하다.

---

## C. 3단계 — S5 후보 감사 실행·검증 가능 비율 재측정 (판정 기준: main 3a83ed64)

런북 `p3_62_s5_candidate_audit_runbook_2026-10-21.md` §0~§4를 그대로 실행했다(2026-10-31). 실행 코드는 main `3a83ed64`의
`whymath_backend`이며(`__file__`로 출처 확인), 승인 은행 두 개는 한 바이트도 바꾸지 않았다.

### C-1. 후보 재생성(§1) — 바이트 동일

| 은행 | exit | sha256 | §B-2 값과 |
|---|---|---|---|
| p3_calculus1_diff_v0 후보 | 0 | `c4f3ad11…86a9` | 같음 |
| p3_fill_v0 후보 | 0 | `8ae08bd8…082e` | 같음 |

### C-2. S5 감사(§2~§4) — calc 통과 · fill 불합격 (as-found)

판정자는 지휘 세션이 띄운 Claude 서브에이전트 24명(calc 8묶음 × A·B + fill 4묶음 × A·B)이다. 각 판정자 폴더는 저장소 밖 빈
폴더이고 지침 사본(sha256 `3046a901…`)과 자기 묶음 하나만 두었다. 계산용 인터프리터는 저장소와 분리한 SymPy 전용 가상환경이다.
24명 출력 전부 산출 검사(줄 수 · id 고유 · 입력 집합 일치 · verdict 값)를 통과했다.

| 은행 | 기계 | 판정자 A | 판정자 B | 합집합 k / n | 보정 상한 | `s5` exit | 판정 | 기록 |
|---|---:|---:|---:|---:|---:|---:|---|---|
| calc 후보 | 0 | 1 | 0 | **1 / 504** | 0.01151 | **0** | 승인 근거 성립 | `docs/data/p3_calculus1_diff_audit/bank_audit_r6/` |
| fill 후보 | 0 | 10 | 4 | **11 / 204** | 0.09697 | **1** | 불합격 | `docs/data/p3_fill_audit/bank_audit_r4/` |

- **fill 결함 11건은 전부 구조화와 무관한 문항이다.** 11건 모두 `verify`를 포함한 전 필드가 3회차 승인 동결 사본과 바이트 동일하다
  (구조화로 바뀐 16건과 교집합 0). 원인은 해설·발문 템플릿 문장 5종(차분몫 문장의 대상 누락 4 · "(a는 상수)가" 조사 3 ·
  단위 뒤 조사 2 · "구하는 극한값" 1 · 줄임표 뒤 조사 1)이고 정답 오류는 0건이다. 3회차 판정자는 같은 글자를 k = 0으로 봤다 —
  판정자에 따라 문장 표기 엄격도가 달랐다. 규칙대로 as-found로 남긴다(재채점·부분 승인 없음).
- 같은 글자가 **현재 승인 은행에도 있다.** 교정은 생성기 템플릿에서 하고 새 회차로 감사한다 — 승계 태스크 소유.
- calc 결함 1건(`3294c5cf…`, 미분 없이 풀림 · 불확실)은 5회차에서도 같은 사유로 짚인 문항이고, 이 문항의 `verify`는 바뀌지 않았다.
- **측정 타당성 단서(검토 반영)**: 같은 4회차 안에서도 같은 템플릿 문장의 검출은 부분적이었다 — "구하는 극한값" 1/8 · 받침 뒤 "(a는 상수)가" 3/8 · "cm/초^2였다고" 2/3 · "2, 4, 6, ...로" 1/4(차분몫 문장만 4/4). 자격 측정의 검출률 하한 0.96898은 **주입 결함 120/120**에서 잰 값이라 이런 문장 표기 결함에는 그대로 성립한다고 볼 수 없다. 그래서 k = 11은 하한값이고, 같은 템플릿이 든 문항은 후보·승인 은행 모두 **최소 27건**이다. calc의 "통과"(k = 1)에도 같은 단서가 붙는다 — 문장 표기 결함을 판정자가 일관되게 잡는다는 보장이 없다.

### C-3. 승격하지 않았다

런북 §5는 **두 은행이 모두 exit 0일 때만** 승격한다. fill이 불합격이라 이번 회차로는 승격하지 않았다. 승인 결속 테스트의
`_AUDITED_BANK`는 그대로 `bank_audit_r5/`(calc)·`bank_audit_r3/`(fill)이다. calc만 먼저 승격할지는 런북 조건의 예외라 Kiki 결정이다.

### C-4. 검증 가능 비율 재측정 — 분모 불변 1,121

| 측정 | 명령 | 통과 | 실패 | 검증 불가 | 검증 가능 비율 |
|---|---|---:|---:|---:|---:|
| **현 main(승인 은행)** | `python -m whymath_backend.harness.solution_qa --json ../../work/sqa.json` (exit 0) | 548 | 0 | 573 | **0.48885** |
| 후보 두 은행 승격 시 | 같은 모집단에서 P3 두 은행 행 708건만 후보로 교체 | 589 | 0 | 532 | 0.52542 |
| 후보 calc만 승격 시 | 같은 모집단에서 calc 은행 행 504건만 후보로 교체 | 573 | 0 | 548 | 0.51115 |

결과 파일: `docs/reviews/p3_62_sqa_main_2026-10-31.json`(CLI 출력 그대로) · `docs/reviews/p3_62_sqa_candidate_merge_2026-10-31.json`(합본 3종 ·
검증 불가 사유별 분해 · 후보 sha256). 구조적 상한은 0.5575(허용 경로 안 VAR 77건 전부 해소 가정 · §재개 판정)다.

### C-5. 남은 것

- 11/15 검증 가능 비율 하한 값은 이 세션이 정하지 않는다 — **D11**(= `G-p3-w3-release-merged`의 Solution QA 검증 가능 비율 하한 결정 · EOS 감리 지시문 2026-10-30의 결정 번호 · Kiki 기한 11/10). 결정문을 받으면 그대로 기록한다.
- 승계 `P3-91`: fill 템플릿 문장 교정(실제 27건 + 낱말 '차분몫' 10건) → 새 회차 감사 → (Kiki 결정에 따라) 두 은행 또는 calc 먼저 승격(런북 §5). 발문을 고치면 문항 id가 바뀌고, 기본 모드 출력이 바뀌어 한 PR로 내야 한다 — 상세는 `P3-91` acceptance 정정 항.
- **P3-62 종결 방침**: acceptance ③(규칙을 생성기에 반영하고 재생성 전후 검증 가능 비율을 CLI로 재측정 · 분모 불변)은 2단계(#1714 — 후보 모드)와 이 3단계(후보 S5 감사 + 재측정)로 이행됐다고 보고 이 PR 머지 뒤 P3-62를 닫는다. 승격은 런북 §5가 처음부터 별도 태스크로 둔 단계라 `P3-91`이 소유한다 — P3-62를 열어 두면 `P3-91`(depends_on P3-62)이 착수 후보가 되지 못한다.
