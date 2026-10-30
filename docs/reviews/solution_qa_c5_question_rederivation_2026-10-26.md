# Solution QA C5 — 발문 독립 재유도 실측 보고 (P3-63)

판정 기준: main `f212a276` (이 문서는 그 위의 브랜치 `claude/happy-heisenberg-4s2h56` 산출물이며, 아래 수치는 이 브랜치에서 잰 값이다)

## 1. 무엇이 문제였나

Solution QA 의 C1 은 **정답이 `verify.conditions` 를 만족하는가**만 본다. 일부 생성기 계열은 conditions 를 *정답에서 역산한 식*으로 적는다. 예) 극댓값 108 문항의 conditions 가 `x**2 + 284*x - 42336 = 0` — x=108 이 근이 되도록 만든 식이다. 이 경우 C1 통과는 "정답이 자기 자신에게서 만든 식을 만족한다"는 뜻일 뿐이라, 학생에게 보이는 **발문(`question_text`)이 그 정답을 낳는지**는 아무 검사도 보지 않았다(P3-07 정직 스코프: "통과율은 실제 정확도의 상한").

## 2. 무엇을 만들었나

- `harness/question_rederive.py` — 발문의 **문장 틀 전체 일치(fullmatch)** 로 질문 의도를 확정하고, 함수식 칸만 SymPy 로 읽어(`l3.safe_parse.safe_sympify` 단일 진입점 · 코딩 헌법 R22-03) **정답을 처음부터 다시 계산**한다. LLM 판정이 아니다. `verify` 는 한 글자도 읽지 않는다(독립성).
- `harness/solution_qa.py` 에 **C5** 추가 — 재유도 값과 `answer` 를 `same_value` 로 비교한다. CI `backend` 잡이 이미 대표 과정 전수에 `solution_qa` 를 인자 없이 돌리고 있어(`tests/infra/test_solution_qa_wiring.py` 동결) 별도 배선 없이 C5 FAIL 이 곧 CI red 다.

C5 의 상태는 셋이며 서로를 위장하지 않는다.

| 재유도 결과 | C5 상태 | 문항 판정에 미치는 영향 |
|---|---|---|
| 값 확정 + 정답과 같음 | PASS | — |
| 값 확정 + 정답과 다름 | **FAIL** (`C5_QUESTION_REDERIVED_MISMATCH`) | 문항 FAIL → 종료 코드 1 |
| 틀은 인식했으나 값이 하나로 안 정해짐 (근 둘 이상·최솟값이 없음·접점이 곡선 밖 등) | UNVERIFIABLE (`C5_REDERIVE_UNDECIDED`) | 문항이 검증 불가로 분류 — 통과로 세지 않음 |
| 인식기가 없는 문장 틀 · 매개변수 미지원 | 해당 없음 (`C5_NOT_COVERED` + 사유) | 판정은 바뀌지 않으나 **보고서 `[C5 적용 범위]` 와 `--c5-list-out` 에 전건 목록으로 남는다** |

미적용을 "통과"로 세지 않는다는 점이 핵심이다: 미적용 문항의 통과는 여전히 C1~C4 만 통과한 값이다.

## 3. 실측 결과 — 대표 과정 승인 문항 전수

- 21개 단원 **전부** 적용, **불일치 0건**. (이전 판정: 통과 548 · 실패 0 · 검증 불가 573 — C5 는 이 숫자를 바꾸지 않았다. C2 의 검증 불가 사유는 풀이 서술 형식이라 C5 와 무관하다.)
- 재유도 계산 시간: 전수 약 8초(평균 7.5ms/문항). `solution_qa` 전체 실행 약 52초.

### 문장 틀 계열별 적용 건수 (50종)

| 계열 id | 의미 | 건수 |
|---|---|---:|
| local_extremum_value | 극댓값·극솟값 | 130 |
| local_extremum_x | 극대·극소가 되는 x | 115 |
| derivative_at_point | x = a 에서의 미분계수 | 109 |
| tangent_slope_pick | 접선 기울기가 K 인 점의 x좌표(큰/작은) | 80 |
| extremum_points | 극값·증감 전환점의 x좌표 | 66 |
| mean_value_c | 평균값 정리·롤의 정리·평균속도의 c | 49 |
| extremum_parameter | 극값 조건으로 매개변수를 정한 뒤의 극값 | 46 |
| real_root_count | 서로 다른 실근·교점 개수 | 39 |
| tangent_at_point | 접점이 주어진 접선(기울기·절편·방정식·넓이) | 35 |
| difference_quotient_limit | 차분몫의 극한·평균변화율 | 33 |
| inequality_minimum | 부등식을 보이려 할 때의 최솟값 | 30 |
| motion_at_time | t = a 에서의 속도·가속도 | 28 |
| differentiable_flag · differentiable_parameter · extremum_count · one_sided_derivative · product_derivative_at_point · train_motion | 각 24 | 144 |
| derivative_equation_root · derivative_parameter | 각 19 | 38 |
| motion_time_when | 속도·가속도가 c 가 되는 시각 | 17 |
| power_derivative_form | x^n 의 도함수 cx^m 꼴 | 14 |
| mean_value_parameter | c 값이 주어질 때 매개변수·끝점 | 13 |
| mean_value_bounds | 평균값 정리로 구하는 k · 함숫값의 한계 | 12 |
| (그 밖 26종) | 각 2~11건 | 아래 JSON 참조 |

전체 목록(계열 id → 제목 → 건수)은 `python -m whymath_backend.harness.solution_qa --json out.json` 의 `c5_by_family`·`c5_family_titles` 에 있다.

## 4. 인식기가 발문을 정말 읽는가 — 실패 주입

정상 입력에서 초록인 것은 증거가 아니다(CLAUDE.md "보호 장치를 실패 주입 없이 보호 있음으로 선언 금지"). 세 층으로 확인했다.

1. **손으로 유도한 정답 대조군 15종 + 변조 주입**(`test_question_rederive.py`): 발문의 수식 한 곳을 정답이 **실제로 바뀌게** 변조하면 모두 FAIL. 대조군(변조 없음)은 모두 PASS. 주입이 발문을 바꿨는지(`!=`)를 매번 단언한다.
2. **역산 conditions 구멍 재현**: 정답을 109 로 틀리게 쓰고 conditions 를 그 정답에서 역산하면 **C1 은 PASS(속는다) · C5 는 FAIL**. P3-07 이 정직 스코프에 적은 바로 그 구멍이 닫혔다.
3. **실 코퍼스 변조**: 대표 과정 문항의 숫자 토큰을 하나씩 +1 한 변조 2,795건 중 1,427건(약 51%)이 FAIL, 485건은 문장 틀이 깨져 미적용으로 빠짐, 316건은 값 미정, 567건이 PASS 로 남았다. PASS 로 남은 표본 14건을 직접 확인했다 — 상수항(극점·미분계수에 영향 없음)·교점 개수가 안 변하는 변조 등 **정답이 실제로 불변인 경우**였다. 단원마다 적어도 하나의 변조가 FAIL 임을 테스트로 동결했다(`test_real_corpus_question_tamper_is_detected_in_every_unit`).
4. **소스 뮤테이션 8종 전건 RED**: `극대`/`극댓` 접두 회귀 · 정수 구간 `floor`→`int` · C5 불일치를 PASS 로 · judge 에서 C5 제거 · 극대/극소 뒤집기 · 미적용을 통과로 위장 · C5 가 `verify` 를 읽게 함 · 값 미정을 통과로. 각 주입 직전·직후 파일 해시를 단언했다.

작성 중 인식기 자신의 주요 결함 5건을 이 대조로 잡아 고쳤다(코퍼스 결함이 아니었다): `극댓값`의 둘째 글자(댓)가 `극대`(대)와 달라 극댓값을 극소로 읽음 · `int()` 절단으로 구간 내 정수 오판 · 한글 사이시옷(`극솟값`) 정규식 누락 · 단서 괄호 `(단, …)` 누락 · 수식 칸 최소 일치가 식 중간에서 꼬리를 시작함. 첫 전수 실행에서 나온 불일치 21건은 전부 첫째 결함이었다.

## 5. 대표 과정 밖 — 불가(미적용) 목록과 이유

대표 과정이 아닌 나머지 문제은행에 C5 를 걸어 본 결과, **적용된 문항은 불일치 0건**(인식기를 맞추지 않은 `generated_v0`·`rephrased_v0`·`university_calc1_*`·`highschool_quotient_rule_v0` 등에서도 일치 — 대표 과정에 끼워 맞춘 인식기가 아니라는 근거다). 반대로 은행 대부분은 인식기가 없다.

| 상태 | 문제은행 | 이유 |
|---|---|---|
| 전부 적용 | `p3_calculus1_diff` · `p3_fill` | 대표 과정 문장 틀 |
| 일부 적용 | `conceptual` · `generated` · `rephrased` · `misconception_mc` · `highschool_quotient_rule` · `university_calc1` · `university_calc1_chain_quotient` | 미분 계열 틀만 인식, 나머지 틀(개념 서술·몫의 미분 등)은 인식기 없음 |
| 미적용 | 적분(`calculus1_integral`·`calculus2_trig_integral`) · 확률·통계(`binomial_distribution`·`probability_*`·`discrete_ev`·`sample_mean_distribution`) · 조합·순열 · 수열 · 복소수 · 행렬·벡터 · 좌표기하·원뿔곡선 · 다항식 · 이차부등식·연립부등식 · 라디안 · 초등(넓이·부피·약수·나머지·반올림·단위) · 중학 함수 · killer | **다른 수학 영역의 발문 문법**이 필요하다. 이 모듈의 틀은 미분(함수식 + 질문 의도) 전용이다 |

미적용 은행의 문항은 C1~C4 의 통과가 "발문을 독립 재유도하지 않은 값"이라는 한계를 그대로 가진다. 은행별로 인식기를 늘리는 일은 후속 작업이다(은행마다 별도 틀·검증이 필요해 이 태스크 범위 밖).

## 6. 정직 스코프 — 이 수치가 말하지 않는 것

- 100% 적용은 **현재 대표 과정의 문장 틀** 기준이다. 생성기가 새 문장 틀을 추가하면 그 문항은 미적용으로 떨어진다(조용히 통과하지 않고 목록에 남는다). 이를 놓치지 않게 적용률 하한 95% 를 래칫으로 동결했다(`test_real_corpus_has_no_c5_failure_and_high_coverage`).
- 문장 틀은 **전체 일치**로만 인식한다. 의도가 같아도 표현이 다르면 미적용이다 — 틀린 값을 재유도하는 것(거짓 FAIL)보다 읽지 않는 것이 낫다는 선택이다.
- "값이 하나로 안 정해짐"은 보류다. 예) 정수 범위 문항에서 끝점이 정수면 열린/닫힌 구간에 따라 개수가 달라 보류.
- C5 일치는 "발문이 이 정답을 낳는다"의 증거이지 풀이 서술의 옳음이 아니다(C2·C4 가 따로 본다).
- 인식기가 틀렸을 가능성은 남는다. 같은 계산을 다른 방법으로 한 두 번째 경로가 없다(SymPy 단일 권위). 완화 장치는 위 4절의 대조군·주입·뮤테이션이다.

## 7. 재현

```bash
cd src/backend && python -m whymath_backend.harness.solution_qa --json /tmp/out.json --c5-list-out /tmp/c5_not_covered.jsonl
python -m pytest -c pyproject.toml --rootdir=. ../../tests/backend/harness/test_question_rederive.py ../../tests/backend/harness/test_solution_qa_c5.py
```
