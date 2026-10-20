# P3-62 — Solution QA 검증 불가 665건 구조화: 착수 판정 (Kiki 결정 대기)

판정 기준: main 1a1a7c8 (브랜치 claude/p3-62-solution-qa-structuring HEAD eb73ebb9 = claim 커밋만)

상태: **③(생성기 반영·재생성) 착수 전 정지.** 작업 트리 변경 0건. 아래는 ①·② 분석과 정지 사유다.

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

# P3-62 재개 판정 (초안·미커밋) — 판정 기준: main 4f0e6652 (브랜치 HEAD 09cc611f)

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
