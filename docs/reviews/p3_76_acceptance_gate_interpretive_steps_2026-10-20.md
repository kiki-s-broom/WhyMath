# P3-76 — 수용 게이트·야간 재검증에 해석 단계 판정 공유 (2026-10-20)

판정 기준: main 4f0e6652

브랜치 `claude/p3-acceptance-gate-interpretive`(착수 HEAD `58881ae0` = main `4f0e6652` + 대장 커밋 2개 — 코드는 `4f0e6652` 와 같다) · 태스크 `P3-76-acceptance-gate-interpretive-steps` · 선행 = P3-71(#1703, Solution QA C4 해석 단계 판정) · 출처 = P3-62 재개 판정(브랜치 `claude/p3-62-solution-qa-structuring` `4e052b1e`).

생성기·코퍼스·감사 사본은 **바꾸지 않았다.** 바뀐 것은 판정기 네 파일(`l3/verify_solution.py`·`l3/equivalent/acceptance.py`·`harness/corpus_reverify.py`·`harness/solution_qa.py`)과 테스트 두 파일, 이 문서, P3-76 대장(`backlog.py amend --path`)뿐이다.

---

## 0. 한 문단 요약

P3-71 은 풀이의 "해석하는 줄"(근 선택 `x = -3, x = 4 → x = 4`, 대입 `x = 4 → y = -202`)을 문항 조건으로 증명하는 판정을 **Solution QA C4 에만** 넣었다. 그래서 같은 풀이를 수용 게이트(`acceptance._evaluate_verification` Tier2)와 야간 상시 재검증(`corpus_reverify._reverify_one`)은 여전히 이웃 동치(`verify_solution`)로만 봐서, P3-62 규칙 (가)를 넣은 문항을 **failed / fail** 로 떨어뜨렸다(P3-62 재개 판정의 실측). 이번에 그 판정을 `l3/verify_solution.py` 의 공용 함수 `verify_solution_interpreted` 로 올리고, 세 곳(C4·수용 게이트·야간 재검증)이 **같은 함수 하나**를 부르게 했다. 판정 의미는 P3-71 과 같다 — 허용 목록 다항식으로 성립이 증명될 때만 통과로 바뀌고, 이웃 동치가 incorrect 를 냈던 전이는 증명되지 않으면 incorrect 그대로다(단조 규칙). 결과: 실 레코드 변형(GRAPH-SHAPE)이 **수용 verified · 재검증 pass** 가 됐고, 틀린 근 선택·틀린 대입값·근거 없는 대입은 **failed · fail** 로 남는다. 현 승인 은행 40개 15,055건은 두 게이트 판정이 **문항 단위로 전부 같다**(종전 pass → 비pass 0 · 종전 verified → 비verified 0). Solution QA 코퍼스 수치는 548 / 0 / 573 그대로이며 문항별 판정·사유 문구까지 main 과 같다.

## 1. acceptance 대조

| 항목 | 결과 | 근거 |
|---|---|---|
| ① 수용 게이트 Tier2·`corpus_reverify` 가 P3-71 해석 단계 판정을 같은 의미로 사용 · 공용 함수 하나(복제 금지) | **충족** | §2. `verify_solution_interpreted` 하나를 세 호출부가 부른다. 판정 구현은 `solution_qa` 에서 옮겨 왔고 사본은 남기지 않았다. AST 거버넌스 테스트가 세 호출 함수가 공용 함수를 부르고 옛 `verify_solution` 을 직접 부르지 않으며, 판정 함수 이름을 따로 정의하지 않음을 동결한다 |
| ② 단조 규칙 · 40개 은행 회귀 대조(종전 pass → 비pass 0, 종전 verified → 비verified 0) | **충족** | §3. 15,055건 문항 단위 대조 — 두 게이트 모두 판정 변화 0건 |
| ③ 주입 실측 — GRAPH-SHAPE 변형 verified·pass, 근거 없는 대입·틀린 근 선택 failed·fail(RED 픽스처) | **충족** | §4. 실 레코드를 읽어 변형하는 픽스처(찾지 못하면 실패) |
| ④ 야간 S6 게이트 의미 변화를 보고서에 명시 | **충족** | §7 |

## 2. 무엇을 바꿨나

### 2-1. 공용 함수의 자리 — `l3/verify_solution.py`

- **왜 harness 가 아닌가**: 수용 게이트는 `l3` 이고 7계층 계약상 `harness` 를 import 할 수 없다. 공용 구현은 `l3` 에 있어야 한다.
- **왜 새 모듈이 아닌가**: `l3` 의 기본 경계 배정은 CORE 이고, 해석 판정은 `verify_answer`(ADAPTER)를 부른다. 새 모듈을 만들면 경계 배정표(`eos_core_adapter_boundary_scan.BOUNDARY_MAP`)·import-linter 금지 목록 두 개·EOS 기능 인벤토리 귀속을 함께 고쳐야 한다. 이미 ADAPTER 로 배정된 "풀이 전체 수식 판정" 모듈(`verify_solution`, 인벤토리 WM-E-355)에 붙이면 그 셋이 그대로다. 이 판단으로 P3-76 `paths` 에 `l3/verify_solution.py` 를 `backlog.py amend --path` 로 더했다(기존 4경로 유지).
- 새 의존: `verify_solution` → `verify_answer`(허용 목록 `certified_*`·`match_root`·`verify_substituted_value`)·`verify_final_answer`(값 동치)·`safe_parse`. 모두 ADAPTER 또는 공식 진입점이라 import-linter 4계약 KEPT(§9).

### 2-2. 공용 API

| 이름 | 역할 | 출처 |
|---|---|---|
| `verify_solution_interpreted(steps, step_types=None, *, conditions, answer_selection=None)` | 이웃 동치 + 해석 단계 판정 → `InterpretedSolutionResult(result, interpretive)` | 신규(C4 의 결합 규칙을 옮김) |
| `interpretive_step`·`judge_root_value` | 해석 단계 모양 판별·값 증명(proven/wrong/unknown) | `solution_qa._interpretive_step`·`_judge_value` 이전 |
| `same_value`·`ValueSame`·`distinct_values`·`final_assignments`·`float_value`·`numeric_assignments`·`split_top_level`·`normalize_value`·`condition_items`·`condition_relations` | 값 동치·풀이 꼴 해석 보조 | `solution_qa` 의 같은 이름(앞 `_`) 이전 |

- `result` 는 `SolutionVerificationResult` 그대로다 — 바뀐 전이만 새 `VerifyStepResult` 로 갈아 끼우고 `aggregate_transitions` 를 다시 돈다. 그래서 `has_incorrect`·`first_incorrect_index`·`n_correct`·`n_unverifiable`·`unverifiable_by_reason` 불변식이 그대로 성립하고, 호출부는 종전 `verify_solution` 결과처럼 쓴다. 해석으로 correct 가 된 전이는 `reason`·`reason_code` 를 비우고 증거 가중치 1.0, 해석으로 incorrect 가 된 전이는 사유 문장을 단다.
- `interpretive` 는 해석 단계 모양으로 본 전이 → 종류(근 선택·대입). 판정이 안 바뀐 전이도 들어 있어 C4 의 "해석 단계 n" 상세를 그대로 만든다.
- `step_types` 길이 규약(전이당 하나, 어긋나면 `ValueError`)은 `verify_solution` 에 그대로 맡긴다.

### 2-3. 판정 규칙 (P3-71 과 같다)

1. 이웃 동치(`verify_solution`)를 먼저 돌린다. correct 인 전이는 다시 보지 않는다.
2. correct 가 아닌 전이만 모양을 본다 — 근 선택(같은 변수의 수치 후보 ≥ 2 → 그중 하나), 대입(변수 v 의 수치 값 → 다른 변수 w 의 수치 값 하나).
3. 값 증명은 조건만 쓴다(정답·answer_map 을 넘기는 자리가 API 에 없다 — P3-24 B3 단서). 그 변수 하나만 담은 등식 하나와 그 변수의 도메인 부등식이 전부 허용 목록 다항식이고(`certified_root_sets`), 그 변수를 다른 변수와 섞는 조건이 없을 때(`y = (허용 목록 다항식)` 정의만 예외)만 증명한다. 근 선택 규칙은 구조의 `answer_selection`(largest/smallest), 없으면 unique.
4. **단조 규칙**: 이웃 동치 incorrect → 성립 증명일 때만 correct, 아니면 incorrect 유지. 이웃 동치 unverifiable → 증명 correct · 위반 확정 incorrect · 판정 불가면 유지.

### 2-4. 호출부

- `acceptance._evaluate_verification`: `verify_solution(steps, step_types)` → `verify_solution_interpreted(steps, step_types, conditions=conditions, answer_selection=answer_selection).result`. Tier1·존재성·근 선택(`verify_root_selection`)·결합 규칙은 그대로다.
- `corpus_reverify._reverify_one`: `verify_solution(steps)` → `verify_solution_interpreted(steps, conditions=conditions, answer_selection=selection).result`. fail 은 종전처럼 incorrect 전이만이다.
- `solution_qa._check_c4`: 자체 루프를 지우고 공용 함수 결과를 읽는다. C1·C2·C3 가 쓰던 값 동치·꼴 해석 보조도 공용 이름을 별칭으로 import 한다(본문 호출 이름 불변). 이 모듈은 1,062줄에서 759줄로 줄었고(−303), `verify_solution.py` 는 251줄에서 666줄로 늘었다(+415 — 옮겨 온 판정과 결합 함수·주석).

## 3. 회귀 대조 — 현 승인 은행 전체 (acceptance ②)

main = `git archive 58881ae0` 로 뽑은 `src/backend`(+`src/data-pipeline`) 사본, 수정 = 이 워크트리. 각 실행의 모듈 경로를 `__file__` 로 확인했다. 같은 레코드에 `_reverify_one(use_fuzz=False)` 와 `_evaluate_verification`(레코드의 conditions·answer_map·solution_steps·answer_selection·answer_aggregate·answer·answer_kind, step_types 없음)을 문항마다 돌려 판정을 문항 단위로 대조했다.

| 게이트 | 대상 | main | 수정 | 판정이 바뀐 문항 |
|---|---|---|---|---:|
| 야간 재검증 `_reverify_one` | 40개 은행 15,055건 | pass 15,055 | pass 15,055 | **0** |
| 수용 게이트 `_evaluate_verification` | 같은 15,055건 | verified 15,054 · unverified 1 | verified 15,054 · unverified 1 | **0** |
| Solution QA (`judge_record`) | 대표 과정 1,121건 | 548 · 0 · 573 | 548 · 0 · 573 | **0**(판정·사유 문구까지 동일) |

- 종전 pass → 비pass **0** · 종전 verified → 비verified **0**. 현 은행의 풀이에는 해석 단계가 없어 판정이 바뀔 문항이 없다 — 이번 변경은 **(가) 꼴이 들어올 때** 판정을 넓힌다.
- CLI 판정은 §9 에 적었다(`corpus_reverify` 40개 은행 · 야간 S6 스텝의 3개 은행).

## 4. 주입 실측 — GRAPH-SHAPE 실 레코드 (acceptance ③)

실 레코드 `wm-p3-diff-graphshape-e6551214a538`(`problem_bank_p3_calculus1_diff_v0`)를 메모리에서만 바꿨다. 조건은 P3-62 재개 판정이 적은 규칙 (가) 꼴(a 결정 등식 · a 대입 도함수 등식 · 선택 근거 `12*x - 6 > 0` · 정의 등식 `y = 2*x**3 - 3*x**2 - 72*x + 6`)으로 재구성했다. a 결정 등식은 재개 판정에 원문이 없어 `Derivative(2*x**3 + a*x**2 - 72*x + 6, x).doit().subs(x, 4) = 0` 으로 적었다(자유변수 a 하나 — x 의 등식과 섞이지 않는다).

| 변형 | 수용 게이트 main → 수정 | 야간 재검증 main → 수정 | Solution QA(참고) |
|---|---|---|---|
| 현행(무변형) | verified → verified | pass → pass | unverifiable |
| (가) 근 선택 + 대입 2줄 | **failed → verified** | **fail → pass** | pass |
| (가) 근 선택 1줄 | unverified → **verified** | pass → pass | unverifiable |
| 틀린 근 선택 `x = -3`(도메인 위반) → `y = 141` | failed → failed(전이 4 → 전이 3) | fail → fail | fail |
| 틀린 대입값 `y = -200` | failed → failed(전이 4) | fail → fail | fail |
| 근거 없는 대입 — 선택 근거 `12*x - 6 > 0` 제거 | failed → failed(전이 4) | fail → fail | fail |
| 근거 없는 대입 — 정의 등식 제거 | failed → failed(전이 4) | fail → fail | fail |

- 틀린 근 선택은 main 에서 대입 전이(4)의 incorrect 로만 걸렸는데, 이제 선택 전이(3) 자체가 incorrect 로 잡힌다(더 이른 위치 — 판정 불가였던 전이가 위반 확정이 됐다).
- RED 픽스처: `tests/backend/l3/equivalent/test_acceptance_interpretive_steps.py`(두 게이트를 같은 레코드로 함께 판정), `tests/backend/l3/test_verify_solution_interpreted.py`(공용 함수 단위·집계 불변식·거버넌스).
- 구조의 `answer_selection` 이 근거인 꼴(도메인 부등식 대신 largest): Tier2 는 통과하지만 수용 게이트는 **unverified** 다. 그 뒤의 근 선택 검사(`verify_root_selection(조건 전체, …)`)가 다변수 조건 목록이라 선택을 확인하지 못해 강등하는 종전 규칙 때문이다(이 태스크가 바꾸지 않은 축). smallest 로 바꾸면 failed · fail.

## 5. P3-71 반례 세트 — 두 게이트에서도 거짓 통과 0

P3-71 검토 반례 adv1~adv8 + P3-71 세션 추가분 96건을 두 게이트에 main·수정으로 돌렸다.

| 게이트 | main → 수정 전이 |
|---|---|
| 수용 게이트 | failed → failed 55 · unverified → unverified 35 · **failed → verified 6** |
| 야간 재검증 | fail → fail 55 · pass → pass 31 · skip → skip 4 · **fail → pass 6** |

- 바뀐 6건은 두 게이트 모두 **A10 · DR2 · IR2 · SP1 · HD2 · DOK(`Derivative(x**3, x).doit() = 3`, `x > 0`)** — P3-71 이 Solution QA 에서 허용 목록 다항 증명으로 통과시킨 6건과 정확히 같다(P3-71 4차 검토가 정당 대조로 지정).
- main pass/verified → 수정 비pass/비verified **0**.
- 분수 약분(RF1~RF8)·`.doit()` 래퍼(B1·D1~D3)·`exp(-log)`(B3)·0 지수(B10)·허수부가 아주 작은 근(NR1·NR2)·초월 등식(T1~T4)·섞인 제약(MV1·MV2)·암묵 정의역(ID1·ID2)·근거 없는 변수 전환(A4) 등은 두 게이트에서 모두 종전 판정 그대로다. 그중 13건을 픽스처로 동결했다.
- 수정 쪽 pass 31 · unverified 35 에는 main 에서도 그 판정이던 우회 꼴의 단일 값 나열 등이 들어 있다 — C1(Tier1) 의 이 PR 이전 결함으로 P3-75 소관이다(§8-3).

## 6. 뮤테이션 — 28종 전건 RED

순수 파이썬 하네스로 호출부 연결·공용 함수의 분기를 하나씩 끊거나 뒤집고, 매번 ①앵커 1건 ②`mutated != orig`·길이 산술 ③원복 후 `filecmp` 바이트 동일을 단언했다. 대상 테스트 = 신규 두 파일 + `test_solution_qa_interpretive_steps.py`·`test_solution_qa.py`·`test_corpus_reverify.py`·`test_acceptance.py`·`test_verify_solution.py`.

| 묶음 | 변이 (모두 RED) |
|---|---|
| 호출부 연결 끊기 | G1 수용 게이트에 조건 미전달 · G2 선택 규칙 미전달 · G3 옛 이웃 동치로 회귀 · G4 재검증에 조건 미전달 · G5 재검증 선택 규칙 미전달 · G6 C4 조건 미전달 · G7 C4 선택 규칙 미전달 |
| 공용 함수 결합 | **U1 단조 규칙 제거**(증명 불가 incorrect → 판정 불가) · U2 해석 incorrect 반영 제거 · U3 성립 증명 반영 제거 · U4 incorrect 전이는 다시 안 봄 · U5 correct 전이도 다시 봄 · U6 집계 재계산 생략 · U7 해석 종류 기록 생략 |
| 값 증명·대입(옮겨 온 판정) | J1 도메인 위반 → 미정 · J3 인증 불가 → 성립 · J4 largest 무시 · J5 smallest 무시 · J6 unique 다근 → 성립 · P2 섞인 조건 규칙 제거 · R6 정의 면제의 허용 목록 요구 제거 · S1 미증명 값으로 대입 · S4 정의 없음 → 성립 · S5 불일치 → 성립 · SEL1·SEL2 선택 판정 뒤집기 · M15 후보 밖 값도 선택 · J7b 파싱 불가 조건 건너뜀 |

첫 실행은 27 RED · 생존 1(U5)이었다. U5(correct 전이도 다시 봄)는 판정 결과는 같고 `interpretive` 기록만 달라지는데, 그것을 밟는 픽스처가 없었다 — 해석 단계 모양이면서 이웃 동치가 correct 인 전이(`x = 4 → x = 4`)를 픽스처에 넣은 뒤 U5 를 다시 돌려 RED 를 확인했다(코드 변경 없음).

## 7. 야간 S6 게이트의 의미 변화 (acceptance ④)

- **판정 확장이지 기준 완화가 아니다.** 야간 재검증(`corpus_reverify` — CI 야간 S6 스텝: generated·rephrased·killer 세 은행)의 Tier2 는 종전에 "이웃 단계가 동치인가"만 물었고, 동치가 아닌 해석 단계(근 선택·대입)는 incorrect(변수 전환) 또는 판정 불가(근 선택)였다. 이제 그 전이를 문항 조건으로 다시 본다.
  - 조건이 허용 목록 다항식으로 그 값을 요구함을 **증명**하면 → 그 전이는 통과(종전 fail 이던 (가) 꼴이 pass 가 된다).
  - 조건과 어긋남이 **확정**이면 → 그 전이는 incorrect(종전 판정 불가이던 틀린 근 선택이 **새로 잡힌다** — 더 엄격해지는 방향).
  - 증명도 위반 확정도 못 하면 → 종전 판정 그대로(incorrect 였으면 fail).
- 허용 목록 밖(초월·분수·`.doit()` 래퍼 속 약분·0/음수 지수·실수 계수·변수 분모·섞인 조건·암묵 정의역 정의)은 종전 판정을 유지한다.
- 현 은행 40개(야간 세 은행 포함)에서는 판정이 바뀐 문항이 0건이다(§3) — 의미 변화는 앞으로 (가) 꼴 문항이 들어올 때 드러난다.
- 수용 게이트(배치 적재)도 같은 함수로 같은 의미 변화를 갖는다. 배치는 verified 만 적재하므로 (가) 꼴 문항이 더는 Tier2 에서 빠지지 않는다.

## 8. 위험·한계

1. **EOS-23(in_progress)과 `l3/equivalent/acceptance.py` 경로가 겹친다.** 이 변경은 `_evaluate_verification` 의 Tier2 호출 한 덩어리·import 한 줄·독스트링뿐이다. `backlog.py amend` 가 보고한 경로 범위 겹침 후보는 정정 전후 14건으로 같다.
2. **`l3/verify_solution` 의 의존이 늘었다**(`verify_answer`·`verify_final_answer`·`safe_parse`). `api/verify`·`l4/subject_adapter_math`·`whs` 등 이 모듈을 import 하는 곳은 `verify_solution`(이웃 동치)만 부르며 판정이 바뀌지 않는다 — 새 함수는 세 게이트만 부른다. import-linter 4계약 KEPT, 순환 import 없음.
3. **C1(Tier1)·`verify_root_selection` 원소 1개 경로의 자동 약분·우회 꼴 결함은 그대로다**(P3-75 소관). 두 게이트가 해석 단계에서 이것들을 증명하지 않을 뿐, Tier1 이 이미 pass 를 내는 단일 값 꼴은 main 과 같은 판정이다.
4. **수용 게이트의 근 선택 강등 축**(다변수 조건 목록 + `answer_selection` → unverified)은 그대로다(§4). 규칙 (가)를 생성기에 넣을 때 선택 근거는 `answer_selection` 보다 도메인 부등식으로 실어야 verified 가 된다 — P3-62 에 넘기는 관찰이다.
5. 회귀 대조는 `step_types` 없는 레코드로 했다(코퍼스에 전이 타입이 없다). 비대수 step_type 전이(`non_algebraic_step` 판정 불가)도 해석 모양이면 다시 본다 — Solution QA C4 와 같은 규칙이다.
6. GRAPH-SHAPE 변형의 a 결정 등식 원문은 재개 판정에 없어 재구성했다(§4).

## 9. 검증 (판정은 exit code)

실행 코드 출처: 매 실행 `PYTHONPATH=src/backend:src/data-pipeline` 로 이 워크트리 모듈을 우선하고(venv editable 은 다른 사본을 가리킨다) `__file__` 로 경로를 확인했다. CI 잡은 `.github/workflows/ci.yml` 의 `run` 스텝을 설치 스텝만 빼고 그대로(같은 명령·작업 디렉터리) 순서대로 돌렸다. 검증이 도는 동안 트리를 바꾸지 않았다.

| 잡 | 스텝 | 결과 | exit |
|---|---|---|---:|
| backend | ruff · black(100) · `mypy --strict whymath_backend` · `lint-imports`(4 kept · 0 broken) | 통과 | 0 · 0 · 0 · 0 |
| backend | `pytest -m "not corpus_authoring" -n auto --dist loadfile --cov…` | 21,624 passed · 710 skipped · 1 xfailed · **1 failed** | 1 |
| backend | ↳ 실패 1건 `l3/test_isolated_call.py::TestThreadIsNotEnough::test_thread_cannot_stop_the_computation` | 스레드의 CPU 소모량 하한(1.5s)을 재는 시간 의존 테스트 — 4코어 전부 쓰는 `-n auto` 부하에서 0.92s. 단독 실행 3회 27 passed(이 브랜치) · main 사본 27 passed. 이 변경과 무관한 모듈(`l3/isolated_call`) | 단독 0 |
| backend | 계층별 커버리지 게이트(l3 81.8% · l4 95.8% 등 전 계층 PASS) · 게이트 CLI 19종(defect_detection … phase3_metrics) | 전부 통과 | 0 |
| backend | `python -m whymath_backend.harness.solution_qa` | 1,121 · 548 · 0 · 573 | 0 |
| backend | `python -m pytest -q tests/constitution` | 40 passed · 33 failed — 33건 전부 `ssh-keygen 이 없다`(컨테이너에 OpenSSH 클라이언트 부재, P3-71 때와 같은 환경 사유) | 1 |
| corpus-authoring | `pytest -m corpus_authoring` | 890 passed · 1 skipped · 2 xfailed | 0 |
| infra-contracts | ruff · black · 게이트 4종 · `pytest tests/infra`(EOS 기능 인벤토리 v2 전수 귀속·경계 계약 포함) · 배치 두 번 실행 | 3,221 passed · 27 skipped / 11 passed | 0 |
| harness-integrity | `backlog.py validate` · `audit-deps` · 규칙 인덱스 린트 · 적시 주입 · `audit_ratchet`(단계 2 · 차단 0 ≤ 기준선 0) · 파이프라인 그래프 · 가드 자가시험 · 개정 기록 · 하류 조회 · ADR 번호 · 원격 claim · 고립 브랜치 · 관측 리포트 · ruff · black · `pytest tests/harness`(2,307 passed) | 통과 | 0 |
| harness-integrity | `check_signed_changes.py` | `⛔ 측정 불가 — ssh-keygen 을 찾지 못함`(환경) | 2 |
| policy-guard | 검정교과서·EBS·원본 바이너리·시크릿 패턴 · `cp949_guard` · 충돌 마커 | 위반 0 | 0 |
| declared-unwired-audit | `declared_unwired_audit` · review_status·persona_fit 백필 드리프트(OPS-24) | 통과 | 0 · 0 · 0 |
| 회귀 대조 | `corpus_reverify` CLI 40개 은행(main 사본·이 트리) | 은행별 요약 40개 전부 동일 | 0 · 0 |
| 회귀 대조 | 야간 S6 스텝(generated 619 · rephrased 421 · killer 120 — 전부 통과) | | 0 |
| 회귀 대조 | §3 문항 단위 대조 15,055건 · §5 반례 96건 · §4 실 레코드 변형 7종 | 표 그대로 | 0 |
| 뮤테이션 | §6 28종 | 28 RED | — |

**확인하지 못한 것**: ①`tests/constitution` 33건·`check_signed_changes` 는 `ssh-keygen` 부재로 이 컨테이너에서 판정할 수 없다 — CI 에서 확인. ②백엔드 전체 스위트는 한 프로세스에서 다 돌렸고 실패 1건은 부하 의존 시간 테스트로 단독 통과를 확인했으나, `-n auto` 전체 재실행으로 다시 0 을 보지는 않았다 — CI 가 최종 판정한다. ③통합 테스트(실 PG 필요 — backend-migrations·backend-serial-nightly)·web·mobile·docker-build·data-pipeline 잡은 돌리지 않았다(이 변경은 백엔드 Python 판정기 네 파일·테스트·문서·대장뿐이다).
