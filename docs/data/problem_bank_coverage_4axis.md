# 문제은행 커버리지 관측 리포트 (D4)

> 관측 리포트다 — **exit 게이트가 아니다**(커버율 임계로 실패시키지 않는다).
> S4-01 초·중 확장의 저작 우선순위 입력. 유형(problem_type) × 단원 축은 §2.5(S3-27). 대학 축은 §1.6(W1).

## 0. 입력 요약

- 문항 총계: **14742**문 (코퍼스 39종)
- 성취기준 대장: 레코드 **895** · 고유 코드 **742** (같은 고시코드가 개정별로 중복 등재 — 분모는 개정 내 고유 코드)
  - 2015 개정: 고유 코드 460
  - 2022 개정: 고유 코드 435 ← 이번 분모

| 코퍼스 | 상태 | 문항 | 파싱 실패 |
|---|---|---:|---:|
| `problem_bank_binomial_distribution_v0` | 적재됨 | 300 | 0 |
| `problem_bank_calculus1_integral_v0` | 적재됨 | 400 | 0 |
| `problem_bank_calculus2_trig_integral_v0` | 적재됨 | 80 | 0 |
| `problem_bank_combination_binomial_v0` | 적재됨 | 121 | 0 |
| `problem_bank_complex_number_arithmetic_v0` | 적재됨 | 900 | 0 |
| `problem_bank_conceptual_v0` | 적재됨 | 360 | 0 |
| `problem_bank_conic_section_focus_v0` | 적재됨 | 65 | 0 |
| `problem_bank_coordinate_geometry_v0` | 적재됨 | 400 | 0 |
| `problem_bank_discrete_ev_v0` | 적재됨 | 200 | 0 |
| `problem_bank_elementary_area_measure_v0` | 적재됨 | 270 | 0 |
| `problem_bank_elementary_division_remainder_v0` | 적재됨 | 400 | 0 |
| `problem_bank_elementary_gcd_lcm_v0` | 적재됨 | 600 | 0 |
| `problem_bank_elementary_rounding_v0` | 적재됨 | 600 | 0 |
| `problem_bank_elementary_v0` | 적재됨 | 400 | 0 |
| `problem_bank_elementary_volume_measure_v0` | 적재됨 | 300 | 0 |
| `problem_bank_generated_v0` | 적재됨 | 619 | 0 |
| `problem_bank_highschool_quotient_rule_v0` | 적재됨 | 200 | 0 |
| `problem_bank_killer_v0` | 적재됨 | 120 | 0 |
| `problem_bank_linear_inequality_system_v0` | 적재됨 | 600 | 0 |
| `problem_bank_matrix_ops_v0` | 적재됨 | 320 | 0 |
| `problem_bank_measurement_unit_conversion_v0` | 적재됨 | 180 | 0 |
| `problem_bank_middle_function_v0` | 적재됨 | 200 | 0 |
| `problem_bank_misconception_mc_v0` | 적재됨 | 1080 | 0 |
| `problem_bank_p3_calculus1_diff_v0` | 적재됨 | 504 | 0 |
| `problem_bank_p3_fill_v0` | 적재됨 | 204 | 0 |
| `problem_bank_permutation_combination_v0` | 적재됨 | 160 | 0 |
| `problem_bank_polynomial_arithmetic_v0` | 적재됨 | 1500 | 0 |
| `problem_bank_polynomial_factoring_v0` | 적재됨 | 600 | 0 |
| `problem_bank_probability_finite_v0` | 적재됨 | 34 | 0 |
| `problem_bank_probability_law_v0` | 적재됨 | 724 | 0 |
| `problem_bank_quad_ineq_v0` | 적재됨 | 200 | 0 |
| `problem_bank_radian_conversion_v0` | 적재됨 | 144 | 0 |
| `problem_bank_rephrased_v0` | 적재됨 | 421 | 0 |
| `problem_bank_sample_mean_distribution_v0` | 적재됨 | 400 | 0 |
| `problem_bank_sequence_sigma_v0` | 적재됨 | 132 | 0 |
| `problem_bank_university_calc1_chain_quotient_v0` | 적재됨 | 400 | 0 |
| `problem_bank_university_calc1_v0` | 적재됨 | 200 | 0 |
| `problem_bank_v1` | 적재됨 | 4 | 0 |
| `problem_bank_vector_operations_v0` | 적재됨 | 400 | 0 |

## 1. 성취기준 커버리지

- 대상 개정: **2022 개정** · 분모(고유 코드) **435**
- 커버된 코드: **136** (31.3%)
- 0커버 코드: **299**

### 1.1 학교급별 커버율

| 학교급 | 커버 | 분모 | 커버율 |
|---|---:|---:|---:|
| 대학교 | 3 | 409 | 0.7% |
| 고등학교 | 90 | 254 | 35.4% |
| 초등학교 | 22 | 121 | 18.2% |
| 중학교 | 24 | 60 | 40.0% |

### 1.2 영역별 커버율

| 영역 | 커버 | 분모 | 커버율 |
|---|---:|---:|---:|
| 도형과 측정 | 20 | 81 | 24.7% |
| 변화와 관계 | 13 | 37 | 35.1% |
| 수와 연산 | 12 | 55 | 21.8% |
| 미분 | 10 | 10 | 100.0% |
| 방정식과 부등식 | 9 | 20 | 45.0% |
| 도형의 방정식 | 6 | 14 | 42.9% |
| 경우의 수 | 6 | 9 | 66.7% |
| 수열 | 6 | 7 | 85.7% |
| 다항식 | 6 | 6 | 100.0% |
| 확률 | 6 | 6 | 100.0% |
| 함수와 그래프 | 5 | 10 | 50.0% |
| 자료와 가능성 | 4 | 26 | 15.4% |
| 지수함수와 로그함수 | 4 | 8 | 50.0% |
| 적분 | 4 | 6 | 66.7% |
| 미분법 | 3 | 11 | 27.3% |
| 적분법 | 3 | 7 | 42.9% |
| 통계 | 3 | 7 | 42.9% |
| 벡터 | 3 | 5 | 60.0% |
| 수열의 극한 | 3 | 5 | 60.0% |
| 이차곡선 | 3 | 4 | 75.0% |
| 삼각함수 | 2 | 3 | 66.7% |
| 공간도형과 공간좌표 | 1 | 5 | 20.0% |
| 생활과 수학 | 1 | 4 | 25.0% |
| 예측과 최적화 | 1 | 4 | 25.0% |
| 함수의 극한과 연속 | 1 | 4 | 25.0% |
| 행렬 | 1 | 4 | 25.0% |
| 집합과 명제 | 0 | 13 | 0.0% |
| 함수와 경제 | 0 | 6 | 0.0% |
| 수와 경제 | 0 | 5 | 0.0% |
| 과제 탐구의 방법과 | 0 | 4 | 0.0% |
| 과제탐구의 실행 | 0 | 4 | 0.0% |
| 미분과 경제 | 0 | 4 | 0.0% |
| 사회와 수학 | 0 | 4 | 0.0% |
| 예술과 수학 | 0 | 4 | 0.0% |
| 자료의 분석 | 0 | 4 | 0.0% |
| 자료의 수집과 정리 | 0 | 4 | 0.0% |
| 환경과 수학 | 0 | 4 | 0.0% |
| 이미지 데이터 처리 | 0 | 3 | 0.0% |
| 인공지능과 빅데이터 | 0 | 3 | 0.0% |
| 텍스트 데이터 처리 | 0 | 3 | 0.0% |
| 통계와 통계적 문제 | 0 | 3 | 0.0% |
| 행렬과 경제 | 0 | 3 | 0.0% |
| 과제 탐구의 이해 | 0 | 2 | 0.0% |
| 인공지능과 수학 | 0 | 2 | 0.0% |
| 통계적 탐구 | 0 | 2 | 0.0% |

### 1.3 과목별 커버리지 (ARCH-28)

> 과목은 성취기준 대장의 `subject` 필드다(`Problem.subject`·코드 prefix 파싱 아님).
> 문항 참조는 커버 코드의 문항 수 합 — 한 문항이 같은 과목 코드를 여러 개 가지면
> 코드마다 1씩 센다(§2 단원 축과 동일한 중복 가산 관례).
>
> **범위 한정(정직 회계)**: 이 축의 분모는 `--standards`가 가리키는 대장 하나뿐이다.
> 기본 경로는 K-12 대장(`standards_v1`)이라 **대학 과목은 분모에 아예 없다** — 아래
> "0문 과목"은 *그 대장 안에서의* 0문이지 전 학교급 판정이 아니다. 대학 축(32과목·
> 409코드)의 문항 커버는 이 도구가 관측하지 않는다(미관측이지 0건이 아니다).

| 과목 | 커버 | 분모 | 커버율 | 문항 참조 |
|---|---:|---:|---:|---:|
| 9수 | 24 | 60 | 40.0% | 1466 |
| 4수 | 5 | 47 | 10.6% | 604 |
| 6수 | 16 | 45 | 35.6% | 1962 |
| 2수 | 1 | 29 | 3.4% | 400 |
| 12미적Ⅱ | 9 | 23 | 39.1% | 400 |
| 10공수2 | 7 | 20 | 35.0% | 520 |
| 12미적Ⅰ | 15 | 20 | 75.0% | 1617 |
| 10공수1 | 14 | 19 | 73.7% | 3000 |
| 12경수 | 0 | 18 | 0.0% | 0 |
| 12대수 | 12 | 18 | 66.7% | 813 |
| 12직수 | 3 | 18 | 16.7% | 96 |
| 10기수1 | 5 | 17 | 29.4% | 1524 |
| 10기수2 | 4 | 17 | 23.5% | 96 |
| 12수문 | 1 | 16 | 6.2% | 24 |
| 12확통 | 12 | 16 | 75.0% | 1899 |
| 12인수 | 1 | 15 | 6.7% | 24 |
| 12기하 | 7 | 14 | 50.0% | 513 |
| 12실통 | 0 | 13 | 0.0% | 0 |
| 12수과 | 0 | 10 | 0.0% | 0 |

- **0문 과목 3종**: `12경수` `12수과` `12실통` — 대장에 성취기준이 있는데 대상 개정 기준 문항이 1건도 없다.

### 1.4 커버된 코드 상위 (문항 수)

| 성취기준 | 문항 |
|---|---:|
| `[10공수1-02-01]` | 900 |
| `[10공수1-01-01]` | 600 |
| `[10기수1-01-01]` | 600 |
| `[6수01-03]` | 600 |
| `[12확통03-06]` | 400 |
| `[2수01-06]` | 400 |
| `[4수01-07]` | 400 |
| `[9수02-20]` | 378 |
| `[10공수1-04-02]` | 320 |
| `[12미적Ⅰ-02-07]` | 309 |
| `[10공수1-01-03]` | 300 |
| `[10공수1-02-09]` | 300 |
| `[10기수1-01-02]` | 300 |
| `[10기수1-01-03]` | 300 |
| `[10기수1-02-07]` | 300 |
| `[12확통02-02]` | 300 |
| `[12확통02-06]` | 300 |
| `[12확통03-03]` | 300 |
| `[6수01-04]` | 300 |
| `[6수01-05]` | 300 |

### 1.5 0커버 코드 목록

- `[10공수1-02-04]` `[10공수1-02-06]` `[10공수1-02-08]` `[10공수1-02-10]` `[10공수1-04-01]` `[10공수2-01-03]` `[10공수2-01-05]` `[10공수2-01-07]` `[10공수2-02-01]` `[10공수2-02-02]` `[10공수2-02-03]` `[10공수2-02-04]` `[10공수2-02-05]` `[10공수2-02-06]` `[10공수2-02-07]` `[10공수2-02-08]` `[10공수2-03-01]` `[10공수2-03-05]` `[10기수1-02-01]` `[10기수1-02-03]` `[10기수1-02-04]` `[10기수1-02-05]` `[10기수1-02-06]` `[10기수1-02-08]` `[10기수1-02-09]` `[10기수1-03-01]` `[10기수1-03-02]` `[10기수1-03-03]` `[10기수1-04-01]` `[10기수1-04-02]` `[10기수2-01-01]` `[10기수2-01-02]` `[10기수2-01-03]` `[10기수2-01-05]` `[10기수2-01-07]` `[10기수2-02-01]` `[10기수2-02-02]` `[10기수2-02-03]` `[10기수2-02-04]` `[10기수2-02-05]`
- …외 **259**건(전량은 `--json` 산출물의 `zero_coverage_codes`).

## 1.6 대학 커버리지

> K-12(§1)와 독립된 분모다 — 대학 성취기준(자체작성, `curriculum_revision="대학"`)은 §1의 target_codes_total에 합산되지 않는다. 학교급별 표(§1.1)의 '대학교' 행이 이 축의 요약이다.

- 분모(대학 고유 코드) **409**
- 커버된 코드: **3** (0.7%)
- 0커버 코드: **406**

### 1.6.1 과목별 커버율

| 과목 | 커버 | 분모 | 커버율 |
|---|---:|---:|---:|
| 미분 | 3 | 10 | 30.0% |
| 다중적분 | 0 | 6 | 0.0% |
| 벡터와 공간기하 | 0 | 6 | 0.0% |
| 기수 | 0 | 5 | 0.0% |
| 미분의 응용 | 0 | 5 | 0.0% |
| 벡터 미적분 | 0 | 5 | 0.0% |
| 주요 정리 | 0 | 5 | 0.0% |
| 편미분 | 0 | 5 | 0.0% |
| 함수와 관계 | 0 | 5 | 0.0% |
| 1계 ODE | 0 | 4 | 0.0% |
| 곡선론 | 0 | 4 | 0.0% |
| 군의 기초 | 0 | 4 | 0.0% |
| 그래프 기초 | 0 | 4 | 0.0% |
| 급수 | 0 | 4 | 0.0% |
| 급수전개 | 0 | 4 | 0.0% |
| 다변수 미분 | 0 | 4 | 0.0% |
| 매개변수·극좌표 | 0 | 4 | 0.0% |
| 벡터공간 | 0 | 4 | 0.0% |
| 벡터함수 | 0 | 4 | 0.0% |
| 선형사상 | 0 | 4 | 0.0% |
| 수열과 급수 | 0 | 4 | 0.0% |
| 수열의 극한 | 0 | 4 | 0.0% |
| 열거조합론 | 0 | 4 | 0.0% |
| 오류정정부호 | 0 | 4 | 0.0% |
| 위상 기초 | 0 | 4 | 0.0% |
| 적분 | 0 | 4 | 0.0% |
| 적분 기법 | 0 | 4 | 0.0% |
| 적분의 응용 | 0 | 4 | 0.0% |
| 증명법 | 0 | 4 | 0.0% |
| 초등함수 | 0 | 4 | 0.0% |
| 함수와 극한 | 0 | 4 | 0.0% |
| 함수의 극한과 연속 | 0 | 4 | 0.0% |
| 환과 아이디얼 | 0 | 4 | 0.0% |
| 1차논리 | 0 | 3 | 0.0% |
| 2계 PDE 분류 | 0 | 3 | 0.0% |
| 2계 선형 ODE | 0 | 3 | 0.0% |
| Lᵖ 공간 | 0 | 3 | 0.0% |
| 고유값·고유벡터 | 0 | 3 | 0.0% |
| 곡률 | 0 | 3 | 0.0% |
| 곡면의 곡률 | 0 | 3 | 0.0% |
| 공개키 암호 | 0 | 3 | 0.0% |
| 공리계 | 0 | 3 | 0.0% |
| 그래프 구조 | 0 | 3 | 0.0% |
| 나눗셈과 합동 | 0 | 3 | 0.0% |
| 내적공간 | 0 | 3 | 0.0% |
| 동형정리 | 0 | 3 | 0.0% |
| 라플라스 방정식 | 0 | 3 | 0.0% |
| 라플라스 변환 | 0 | 3 | 0.0% |
| 르베그 적분 | 0 | 3 | 0.0% |
| 르베그 측도 | 0 | 3 | 0.0% |
| 리만적분 | 0 | 3 | 0.0% |
| 명제와 논리 | 0 | 3 | 0.0% |
| 미분다양체 | 0 | 3 | 0.0% |
| 방정식의 해 | 0 | 3 | 0.0% |
| 보간과 근사 | 0 | 3 | 0.0% |
| 부분·곱·몫공간 | 0 | 3 | 0.0% |
| 선형계 수치해 | 0 | 3 | 0.0% |
| 선형연립방정식 | 0 | 3 | 0.0% |
| 스펙트럼 정리 | 0 | 3 | 0.0% |
| 실수계 | 0 | 3 | 0.0% |
| 오차와 부동소수점 | 0 | 3 | 0.0% |
| 원시근과 이차잉여 | 0 | 3 | 0.0% |
| 위상공간 | 0 | 3 | 0.0% |
| 이차형식 | 0 | 3 | 0.0% |
| 점추정 | 0 | 3 | 0.0% |
| 정역의 인수분해 | 0 | 3 | 0.0% |
| 정칙곡면 | 0 | 3 | 0.0% |
| 준동형과 정규부분군 | 0 | 3 | 0.0% |
| 집합 | 0 | 3 | 0.0% |
| 체확장 | 0 | 3 | 0.0% |
| 체확장 복습 | 0 | 3 | 0.0% |
| 컴팩트성 | 0 | 3 | 0.0% |
| 표본분포 | 0 | 3 | 0.0% |
| 함수열·함수급수 | 0 | 3 | 0.0% |
| 행렬대수 | 0 | 3 | 0.0% |
| 행렬식 | 0 | 3 | 0.0% |
| 확률공간 | 0 | 3 | 0.0% |
| 확률변수와 분포 | 0 | 3 | 0.0% |
| 힐베르트 공간 | 0 | 3 | 0.0% |
| 가설검정 | 0 | 2 | 0.0% |
| 가우스 정리 | 0 | 2 | 0.0% |
| 가측함수 | 0 | 2 | 0.0% |
| 갈루아 군 | 0 | 2 | 0.0% |
| 거리화 정리 | 0 | 2 | 0.0% |
| 고전·대칭 암호 | 0 | 2 | 0.0% |
| 군의 작용 | 0 | 2 | 0.0% |
| 극한정리 | 0 | 2 | 0.0% |
| 급수해 | 0 | 2 | 0.0% |
| 기댓값과 적률 | 0 | 2 | 0.0% |
| 기본군 입문 | 0 | 2 | 0.0% |
| 노름공간 | 0 | 2 | 0.0% |
| 다항식환 | 0 | 2 | 0.0% |
| 대수적 정수론 | 0 | 2 | 0.0% |
| 디오판토스 방정식 | 0 | 2 | 0.0% |
| 리만 계량 | 0 | 2 | 0.0% |
| 멱급수와 해석함수 | 0 | 2 | 0.0% |
| 명제논리 | 0 | 2 | 0.0% |
| 미분과 측도 | 0 | 2 | 0.0% |
| 발표와 작성 | 0 | 2 | 0.0% |
| 벡터장과 미분형식 | 0 | 2 | 0.0% |
| 복소수와 해석함수 | 0 | 2 | 0.0% |
| 복소적분 | 0 | 2 | 0.0% |
| 부호의 한계 | 0 | 2 | 0.0% |
| 분리공리 | 0 | 2 | 0.0% |
| 불완전성 | 0 | 2 | 0.0% |
| 사상과 차원 | 0 | 2 | 0.0% |
| 사영 다양체 | 0 | 2 | 0.0% |
| 선택공리 | 0 | 2 | 0.0% |
| 소수 | 0 | 2 | 0.0% |
| 수치적분·미분 | 0 | 2 | 0.0% |
| 순서수 | 0 | 2 | 0.0% |
| 스펙트럼 이론 | 0 | 2 | 0.0% |
| 실로우 정리 | 0 | 2 | 0.0% |
| 아핀 다양체 | 0 | 2 | 0.0% |
| 연결성 | 0 | 2 | 0.0% |
| 연립 ODE·상평면 | 0 | 2 | 0.0% |
| 연속함수와 위상동형 | 0 | 2 | 0.0% |
| 열방정식 | 0 | 2 | 0.0% |
| 옵션가격결정 | 0 | 2 | 0.0% |
| 완비성과 베어 범주 | 0 | 2 | 0.0% |
| 유계작용소 | 0 | 2 | 0.0% |
| 유수정리 | 0 | 2 | 0.0% |
| 응용 | 0 | 2 | 0.0% |
| 이자율과 채권 | 0 | 2 | 0.0% |
| 이차잉여와 상호법칙 | 0 | 2 | 0.0% |
| 정수론적 함수 | 0 | 2 | 0.0% |
| 조합 설계 | 0 | 2 | 0.0% |
| 주제선정과 문헌조사 | 0 | 2 | 0.0% |
| 특이호몰로지 | 0 | 2 | 0.0% |
| 파동방정식 | 0 | 2 | 0.0% |
| 포트폴리오 | 0 | 2 | 0.0% |
| 표준형 | 0 | 2 | 0.0% |
| 피복공간 | 0 | 2 | 0.0% |
| 해석적 정수론 | 0 | 2 | 0.0% |
| 호모토피와 기본군 | 0 | 2 | 0.0% |
| 확률미적분 | 0 | 2 | 0.0% |
| 1계 PDE | 0 | 1 | 0.0% |
| 가우스-보네 정리 | 0 | 1 | 0.0% |
| 갈루아 대응 | 0 | 1 | 0.0% |
| 구간추정 | 0 | 1 | 0.0% |
| 아이디얼-대수집합 대응 | 0 | 1 | 0.0% |
| 완전성·콤팩트성 | 0 | 1 | 0.0% |
| 유한체 | 0 | 1 | 0.0% |
| 적분과 스토크스 정리 | 0 | 1 | 0.0% |
| 조건부확률과 독립 | 0 | 1 | 0.0% |

### 1.6.2 0커버 코드 목록

- `[AALG1-01-01]` `[AALG1-01-02]` `[AALG1-01-03]` `[AALG1-01-04]` `[AALG1-02-01]` `[AALG1-02-02]` `[AALG1-02-03]` `[AALG1-03-01]` `[AALG1-03-02]` `[AALG1-03-03]` `[AALG1-04-01]` `[AALG1-04-02]` `[AALG1-05-01]` `[AALG1-05-02]` `[AALG2-01-01]` `[AALG2-01-02]` `[AALG2-01-03]` `[AALG2-01-04]` `[AALG2-02-01]` `[AALG2-02-02]` `[AALG2-02-03]` `[AALG2-03-01]` `[AALG2-03-02]` `[AALG2-04-01]` `[AALG2-04-02]` `[AALG2-04-03]` `[AALG2-05-01]` `[AGEO-01-01]` `[AGEO-01-02]` `[AGEO-02-01]` `[AGEO-03-01]` `[AGEO-03-02]` `[AGEO-04-01]` `[AGEO-04-02]` `[ANAL1-01-01]` `[ANAL1-01-02]` `[ANAL1-01-03]` `[ANAL1-02-01]` `[ANAL1-02-02]` `[ANAL1-02-03]`
- …외 **366**건(전량은 `--json` 산출물의 `university.zero_coverage_codes`).

## 2. 단원(unit_code) × 난이도 밴드 분포

> 밴드 경계는 L6 기존 정본에서 유도 — `_DEPTH_TARGET_DIFFICULTY`(RequiredDepth 앵커 1.5/2.5/3.5/4.5)의 중점 2.0·3.0·4.0, 최상단 4.0은 `GIFTED_MIN_DIFFICULTY`와 일치.
> 한 문항이 여러 단원을 가지면 각 단원에 1씩 세므로 행 합계는 총 문항 수와 다를 수 있다.

| 단원 | 인지 [1.0,2.0) | 절차 [2.0,3.0) | 개념 [3.0,4.0) | 숙달 [4.0,5.0] | 미평가(난이도 없음) | 범위밖(1.0~5.0 아님) | 합계 |
|---|---|---|---|---|---|---|---|
| `POLYNOMIAL-ARITHMETIC` | 1200 | 300 | 0 | 0 | 0 | 0 | 1500 |
| `COMPLEX-NUMBER-ARITHMETIC` | 0 | 900 | 0 | 0 | 0 | 0 | 900 |
| `GCD-LCM` | 600 | 11 | 13 | 0 | 0 | 0 | 624 |
| `ELEMENTARY-ROUNDING` | 600 | 0 | 0 | 0 | 0 | 0 | 600 |
| `LINEAR-INEQUALITY-SYSTEM` | 0 | 600 | 0 | 0 | 0 | 0 | 600 |
| `POLYNOMIAL-FACTORING` | 0 | 600 | 0 | 0 | 0 | 0 | 600 |
| `CALC1-INTEGRAL` | 0 | 0 | 400 | 0 | 0 | 0 | 400 |
| `ELEM-ADDSUB-2DIGIT` | 400 | 0 | 0 | 0 | 0 | 0 | 400 |
| `SAMPLE-MEAN-DISTRIBUTION` | 0 | 200 | 200 | 0 | 0 | 0 | 400 |
| `TWO-DIGIT-DIVISION` | 400 | 0 | 0 | 0 | 0 | 0 | 400 |
| `QUAD-EQ` | 0 | 201 | 132 | 0 | 0 | 0 | 333 |
| `MATRIX-OPS` | 0 | 320 | 0 | 0 | 0 | 0 | 320 |
| `BINOMIAL-DISTRIBUTION` | 0 | 0 | 300 | 0 | 0 | 0 | 300 |
| `PROBABILITY-ADDITION-LAW` | 0 | 300 | 0 | 0 | 0 | 0 | 300 |
| `PROBABILITY-MULTIPLICATION-LAW` | 0 | 0 | 300 | 0 | 0 | 0 | 300 |
| `CALC1-CHAIN-RULE` | 0 | 0 | 200 | 0 | 0 | 0 | 200 |
| `CALC1-PRODUCT-RULE` | 0 | 0 | 200 | 0 | 0 | 0 | 200 |
| `CALC1-QUOTIENT-RULE` | 0 | 0 | 200 | 0 | 0 | 0 | 200 |
| `DISCRETE-EXPECTED-VALUE` | 0 | 200 | 0 | 0 | 0 | 0 | 200 |
| `HS-CALC2-QUOTIENT-RULE` | 0 | 0 | 200 | 0 | 0 | 0 | 200 |
| `LINE-EQUATION` | 0 | 200 | 0 | 0 | 0 | 0 | 200 |
| `LINEAR-FUNC-VALUE` | 200 | 0 | 0 | 0 | 0 | 0 | 200 |
| `POINT-DISTANCE` | 0 | 200 | 0 | 0 | 0 | 0 | 200 |
| `POSITION-VECTOR` | 69 | 131 | 0 | 0 | 0 | 0 | 200 |
| `QUAD-INEQ-BOUNDARY` | 0 | 200 | 0 | 0 | 0 | 0 | 200 |
| `RECT-PRISM-SURFACE-AREA` | 0 | 200 | 0 | 0 | 0 | 0 | 200 |
| `RECT-PRISM-VOLUME` | 0 | 200 | 0 | 0 | 0 | 0 | 200 |
| `VECTOR-LINEAR-COMBO` | 0 | 200 | 0 | 0 | 0 | 0 | 200 |
| `MEASUREMENT-UNIT-CONVERSION` | 157 | 23 | 0 | 0 | 0 | 0 | 180 |
| `RADIAN-CONVERSION` | 0 | 144 | 0 | 0 | 0 | 0 | 144 |
| `PROBABILITY-COMPLEMENT-LAW` | 0 | 124 | 0 | 0 | 0 | 0 | 124 |
| `ARITH-SEQ` | 54 | 66 | 0 | 0 | 0 | 0 | 120 |
| `POLY-ROOT` | 0 | 0 | 0 | 120 | 0 | 0 | 120 |
| `SUM-PRODUCT-PRINCIPLE` | 84 | 36 | 0 | 0 | 0 | 0 | 120 |
| `SIGMA-LINEARITY` | 0 | 100 | 0 | 0 | 0 | 0 | 100 |
| `CALC-TANGENT` | 0 | 0 | 70 | 10 | 0 | 0 | 80 |
| `CALC2-TRIG-INTEGRAL` | 0 | 0 | 80 | 0 | 0 | 0 | 80 |
| `CALC-EXTREMUM` | 0 | 0 | 69 | 8 | 0 | 0 | 77 |
| `CALC-EXTREMUM-VALUE` | 0 | 0 | 62 | 12 | 0 | 0 | 74 |
| `P3-CALC1-DIFF-EQUATION-APPLICATION` | 0 | 36 | 24 | 12 | 0 | 0 | 72 |
| `P3-CALC1-DIFF-GRAPH-SHAPE` | 0 | 24 | 36 | 12 | 0 | 0 | 72 |
| `P3-CALC1-DIFF-MEAN-VALUE-THEOREM` | 0 | 36 | 24 | 12 | 0 | 0 | 72 |
| `P3-CALC1-DIFF-POLYNOMIAL-RULES` | 0 | 36 | 36 | 0 | 0 | 0 | 72 |
| `P3-CALC1-DIFF-POWER` | 0 | 36 | 36 | 0 | 0 | 0 | 72 |
| `P3-CALC1-DIFF-TANGENT-LINE` | 0 | 36 | 24 | 12 | 0 | 0 | 72 |
| `P3-CALC1-DIFF-VELOCITY-ACCELERATION` | 0 | 36 | 24 | 12 | 0 | 0 | 72 |
| `AREA-UNIT-CONVERSION` | 70 | 0 | 0 | 0 | 0 | 0 | 70 |
| `BINOMIAL-COEFFICIENT` | 0 | 65 | 0 | 0 | 0 | 0 | 65 |
| `CONIC-SECTION-FOCUS` | 0 | 0 | 65 | 0 | 0 | 0 | 65 |
| `GEO-SEQ` | 38 | 22 | 0 | 0 | 0 | 0 | 60 |
| `P3-CALC1-DIFF-DIFFERENTIABILITY` | 0 | 36 | 24 | 0 | 0 | 0 | 60 |
| `CALC-EXTREMUM-MC` | 0 | 0 | 44 | 12 | 0 | 0 | 56 |
| `REPEATED-COMBINATION` | 0 | 56 | 0 | 0 | 0 | 0 | 56 |
| `CIRCLE-CIRCUMFERENCE` | 0 | 50 | 0 | 0 | 0 | 0 | 50 |
| `VOLUME-UNIT-CONVERSION` | 50 | 0 | 0 | 0 | 0 | 0 | 50 |
| `P3-CALC1-DIFF-COEFFICIENT` | 0 | 36 | 12 | 0 | 0 | 0 | 48 |
| `P3-CALC1-DIFF-MONOTONICITY-EXTREMUM` | 0 | 12 | 24 | 12 | 0 | 0 | 48 |
| `EXP-EQ` | 30 | 16 | 0 | 0 | 0 | 0 | 46 |
| `ARITH-SUM` | 7 | 38 | 0 | 0 | 0 | 0 | 45 |
| `PERMUTATION` | 0 | 40 | 0 | 0 | 0 | 0 | 40 |
| `LOG-EQ` | 23 | 11 | 0 | 0 | 0 | 0 | 34 |
| `POWER-SUM` | 0 | 32 | 0 | 0 | 0 | 0 | 32 |
| `CALC-EXTREMUM-IRR` | 0 | 0 | 30 | 0 | 0 | 0 | 30 |
| `IND-SEQ` | 30 | 0 | 0 | 0 | 0 | 0 | 30 |
| `PROB-FINITE-ENUM` | 0 | 18 | 8 | 0 | 0 | 0 | 26 |
| `TRIG-VAL` | 26 | 0 | 0 | 0 | 0 | 0 | 26 |
| `ABS-VALUE` | 0 | 11 | 13 | 0 | 0 | 0 | 24 |
| `AREA-PERIMETER` | 0 | 14 | 10 | 0 | 0 | 0 | 24 |
| `CALC-CHAIN` | 0 | 8 | 16 | 0 | 0 | 0 | 24 |
| `CALC-PRODUCT` | 0 | 8 | 16 | 0 | 0 | 0 | 24 |
| `CIRCLE-AREA` | 0 | 10 | 14 | 0 | 0 | 0 | 24 |
| `CIRCLE-RADIUS` | 0 | 10 | 14 | 0 | 0 | 0 | 24 |
| `COMBINATION-COUNT` | 0 | 15 | 9 | 0 | 0 | 0 | 24 |
| `COMBINE-UNLIKE` | 0 | 16 | 8 | 0 | 0 | 0 | 24 |
| `COMPLETE-SQUARE` | 0 | 8 | 16 | 0 | 0 | 0 | 24 |
| `CONE-VOLUME` | 0 | 10 | 14 | 0 | 0 | 0 | 24 |
| `CONJUGATE-PRODUCT` | 0 | 12 | 12 | 0 | 0 | 0 | 24 |
| `DECIMAL-MULT` | 0 | 13 | 11 | 0 | 0 | 0 | 24 |
| `DIFF-SQUARES` | 0 | 8 | 16 | 0 | 0 | 0 | 24 |
| `DIFFERENTIABILITY` | 0 | 10 | 14 | 0 | 0 | 0 | 24 |
| `DISC-COUNT` | 0 | 12 | 12 | 0 | 0 | 0 | 24 |
| `DISTRIBUTE-PARTIAL` | 0 | 9 | 15 | 0 | 0 | 0 | 24 |
| `DOMAIN-EXCLUDE` | 0 | 7 | 17 | 0 | 0 | 0 | 24 |
| `EXP-PRODUCT` | 0 | 12 | 12 | 0 | 0 | 0 | 24 |
| `EXP-ZERO` | 0 | 10 | 14 | 0 | 0 | 0 | 24 |
| `EXTREMUM-COUNT` | 0 | 10 | 14 | 0 | 0 | 0 | 24 |
| `FRACTION-ADD` | 0 | 13 | 11 | 0 | 0 | 0 | 24 |
| `FRACTION-CANCEL` | 0 | 6 | 18 | 0 | 0 | 0 | 24 |
| `FUNC-COMPOSE` | 0 | 10 | 14 | 0 | 0 | 0 | 24 |
| `FUNC-INVERSE` | 0 | 14 | 10 | 0 | 0 | 0 | 24 |
| `FUNC-TRANSLATE` | 0 | 7 | 17 | 0 | 0 | 0 | 24 |
| `GEO-SERIES-CONV` | 0 | 10 | 14 | 0 | 0 | 0 | 24 |
| `GEOM-SIMILAR-CONGRUENT` | 0 | 8 | 16 | 0 | 0 | 0 | 24 |
| `INEQ-SIGN-FLIP` | 0 | 7 | 17 | 0 | 0 | 0 | 24 |
| `LIMIT-VALUE` | 0 | 4 | 20 | 0 | 0 | 0 | 24 |
| `LOG-DIST` | 0 | 12 | 12 | 0 | 0 | 0 | 24 |
| `MIDPOINT-NO-HALF` | 0 | 10 | 14 | 0 | 0 | 0 | 24 |
| `MIXED-MULT` | 0 | 14 | 10 | 0 | 0 | 0 | 24 |
| `NEG-DISTRIBUTE` | 0 | 10 | 14 | 0 | 0 | 0 | 24 |
| `NEG-EVEN-POWER` | 0 | 10 | 14 | 0 | 0 | 0 | 24 |
| `NEG-PRODUCT` | 0 | 11 | 13 | 0 | 0 | 0 | 24 |
| `NEG-SQUARE` | 0 | 11 | 13 | 0 | 0 | 0 | 24 |
| `P3-CALC1-DIFF-MOTION-WORD` | 0 | 0 | 24 | 0 | 0 | 0 | 24 |
| `P3-CALC1-DIFF-POWER-PATTERN` | 0 | 0 | 24 | 0 | 0 | 0 | 24 |
| `POLY-PRODUCT` | 0 | 10 | 14 | 0 | 0 | 0 | 24 |
| `POLYGON-ANGLE-SUM` | 0 | 10 | 14 | 0 | 0 | 0 | 24 |
| `POWER-OF-POWER` | 0 | 16 | 8 | 0 | 0 | 0 | 24 |
| `PROB-CONDITIONAL` | 0 | 8 | 16 | 0 | 0 | 0 | 24 |
| `PROB-INDEPENDENCE` | 0 | 6 | 18 | 0 | 0 | 0 | 24 |
| `PROB-INDEPENDENT-TRIAL` | 0 | 9 | 15 | 0 | 0 | 0 | 24 |
| `REMAINDER-THEOREM` | 0 | 11 | 13 | 0 | 0 | 0 | 24 |
| `ROOT-LOSS-DIVIDE` | 0 | 8 | 16 | 0 | 0 | 0 | 24 |
| `SAME-ITEM-PERM` | 0 | 12 | 12 | 0 | 0 | 0 | 24 |
| `SCALE-AREA` | 0 | 12 | 12 | 0 | 0 | 0 | 24 |
| `SCALE-VOLUME` | 0 | 10 | 14 | 0 | 0 | 0 | 24 |
| `SERIES-CONV` | 0 | 12 | 12 | 0 | 0 | 0 | 24 |
| `SQRT-POS` | 0 | 10 | 14 | 0 | 0 | 0 | 24 |
| `SQRT-SUM` | 0 | 7 | 17 | 0 | 0 | 0 | 24 |
| `SQUARE-DIFF` | 0 | 10 | 14 | 0 | 0 | 0 | 24 |
| `STAT-MEAN-MEDIAN` | 0 | 19 | 5 | 0 | 0 | 0 | 24 |
| `SUBTRACT-NEG` | 0 | 11 | 13 | 0 | 0 | 0 | 24 |
| `TRANSPOSE-SIGN` | 0 | 10 | 14 | 0 | 0 | 0 | 24 |
| `TRAPEZOID-AREA` | 0 | 8 | 16 | 0 | 0 | 0 | 24 |
| `TRIG-ADD` | 0 | 6 | 18 | 0 | 0 | 0 | 24 |
| `TRIG-PERIOD` | 0 | 12 | 12 | 0 | 0 | 0 | 24 |
| `VEC-DOT-PRODUCT` | 0 | 1 | 23 | 0 | 0 | 0 | 24 |
| `VIETA-SUM` | 0 | 12 | 12 | 0 | 0 | 0 | 24 |
| `GEO-SUM` | 0 | 20 | 0 | 0 | 0 | 0 | 20 |
| `TRIG-EQ` | 3 | 9 | 0 | 0 | 0 | 0 | 12 |
| `COUNT-FINITE-ENUM` | 0 | 8 | 0 | 0 | 0 | 0 | 8 |
| `QUAD-FN` | 0 | 1 | 0 | 0 | 0 | 0 | 1 |
| **문항 기준 합계** | 4041 | 6766 | 3701 | 234 | 0 | 0 | 14742 |

## 2.5 유형(problem_type) × 단원 분포

> `problem_type_codes`(S3-27 백필) 기반 — 유보 해제 근거는 `ai_content_generation_gap_review.md` D3·`problem_bank_gap_review.md` §5-③ 편집자 부기. 한 문항이 여러 단원을 가지면 각 단원에 1씩 세므로 행 합계는 총 태깅 문항 수와 다를 수 있다(§2 관례 동일).

| 유형(problem_type_id) | `ABS-VALUE` | `AREA-PERIMETER` | `AREA-UNIT-CONVERSION` | `ARITH-SEQ` | `ARITH-SUM` | `BINOMIAL-COEFFICIENT` | `BINOMIAL-DISTRIBUTION` | `CALC-CHAIN` | `CALC-EXTREMUM` | `CALC-EXTREMUM-IRR` | `CALC-EXTREMUM-MC` | `CALC-EXTREMUM-VALUE` | `CALC-PRODUCT` | `CALC-TANGENT` | `CALC1-CHAIN-RULE` | `CALC1-INTEGRAL` | `CALC1-PRODUCT-RULE` | `CALC1-QUOTIENT-RULE` | `CALC2-TRIG-INTEGRAL` | `CIRCLE-AREA` | `CIRCLE-CIRCUMFERENCE` | `CIRCLE-RADIUS` | `COMBINATION-COUNT` | `COMBINE-UNLIKE` | `COMPLETE-SQUARE` | `COMPLEX-NUMBER-ARITHMETIC` | `CONE-VOLUME` | `CONIC-SECTION-FOCUS` | `CONJUGATE-PRODUCT` | `COUNT-FINITE-ENUM` | `DECIMAL-MULT` | `DIFF-SQUARES` | `DIFFERENTIABILITY` | `DISC-COUNT` | `DISCRETE-EXPECTED-VALUE` | `DISTRIBUTE-PARTIAL` | `DOMAIN-EXCLUDE` | `ELEM-ADDSUB-2DIGIT` | `ELEMENTARY-ROUNDING` | `EXP-EQ` | `EXP-PRODUCT` | `EXP-ZERO` | `EXTREMUM-COUNT` | `FRACTION-ADD` | `FRACTION-CANCEL` | `FUNC-COMPOSE` | `FUNC-INVERSE` | `FUNC-TRANSLATE` | `GCD-LCM` | `GEO-SEQ` | `GEO-SERIES-CONV` | `GEO-SUM` | `GEOM-SIMILAR-CONGRUENT` | `HS-CALC2-QUOTIENT-RULE` | `IND-SEQ` | `INEQ-SIGN-FLIP` | `LIMIT-VALUE` | `LINE-EQUATION` | `LINEAR-FUNC-VALUE` | `LINEAR-INEQUALITY-SYSTEM` | `LOG-DIST` | `LOG-EQ` | `MATRIX-OPS` | `MEASUREMENT-UNIT-CONVERSION` | `MIDPOINT-NO-HALF` | `MIXED-MULT` | `NEG-DISTRIBUTE` | `NEG-EVEN-POWER` | `NEG-PRODUCT` | `NEG-SQUARE` | `P3-CALC1-DIFF-COEFFICIENT` | `P3-CALC1-DIFF-DIFFERENTIABILITY` | `P3-CALC1-DIFF-EQUATION-APPLICATION` | `P3-CALC1-DIFF-GRAPH-SHAPE` | `P3-CALC1-DIFF-MEAN-VALUE-THEOREM` | `P3-CALC1-DIFF-MONOTONICITY-EXTREMUM` | `P3-CALC1-DIFF-MOTION-WORD` | `P3-CALC1-DIFF-POLYNOMIAL-RULES` | `P3-CALC1-DIFF-POWER` | `P3-CALC1-DIFF-POWER-PATTERN` | `P3-CALC1-DIFF-TANGENT-LINE` | `P3-CALC1-DIFF-VELOCITY-ACCELERATION` | `PERMUTATION` | `POINT-DISTANCE` | `POLY-PRODUCT` | `POLY-ROOT` | `POLYGON-ANGLE-SUM` | `POLYNOMIAL-ARITHMETIC` | `POLYNOMIAL-FACTORING` | `POSITION-VECTOR` | `POWER-OF-POWER` | `POWER-SUM` | `PROB-CONDITIONAL` | `PROB-FINITE-ENUM` | `PROB-INDEPENDENCE` | `PROB-INDEPENDENT-TRIAL` | `PROBABILITY-ADDITION-LAW` | `PROBABILITY-COMPLEMENT-LAW` | `PROBABILITY-MULTIPLICATION-LAW` | `QUAD-EQ` | `QUAD-FN` | `QUAD-INEQ-BOUNDARY` | `RADIAN-CONVERSION` | `RECT-PRISM-SURFACE-AREA` | `RECT-PRISM-VOLUME` | `REMAINDER-THEOREM` | `REPEATED-COMBINATION` | `ROOT-LOSS-DIVIDE` | `SAME-ITEM-PERM` | `SAMPLE-MEAN-DISTRIBUTION` | `SCALE-AREA` | `SCALE-VOLUME` | `SERIES-CONV` | `SIGMA-LINEARITY` | `SQRT-POS` | `SQRT-SUM` | `SQUARE-DIFF` | `STAT-MEAN-MEDIAN` | `SUBTRACT-NEG` | `SUM-PRODUCT-PRINCIPLE` | `TRANSPOSE-SIGN` | `TRAPEZOID-AREA` | `TRIG-ADD` | `TRIG-EQ` | `TRIG-PERIOD` | `TRIG-VAL` | `TWO-DIGIT-DIVISION` | `VEC-DOT-PRODUCT` | `VECTOR-LINEAR-COMBO` | `VIETA-SUM` | `VOLUME-UNIT-CONVERSION` | 합계 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `ptype.condition-satisfaction` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 600 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 200 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 800 |
| `ptype.construct-object` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `ptype.count-solutions` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 24 | 0 | 0 | 24 | 0 | 0 | 0 | 0 | 0 | 24 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 42 | 0 | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 24 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 145 |
| `ptype.determine-coefficient` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 200 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 201 |
| `ptype.enumerate-cases` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 24 | 0 | 0 | 0 | 0 | 0 | 0 | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 40 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 56 | 0 | 24 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 120 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 272 |
| `ptype.evaluate-expression` | 24 | 24 | 70 | 120 | 45 | 65 | 300 | 24 | 0 | 0 | 0 | 0 | 24 | 0 | 200 | 400 | 200 | 200 | 80 | 24 | 50 | 24 | 0 | 24 | 24 | 900 | 24 | 65 | 24 | 0 | 24 | 24 | 0 | 0 | 200 | 24 | 0 | 400 | 600 | 0 | 24 | 24 | 0 | 24 | 24 | 24 | 0 | 24 | 624 | 60 | 0 | 20 | 0 | 200 | 0 | 0 | 0 | 0 | 200 | 0 | 24 | 0 | 320 | 180 | 24 | 24 | 24 | 24 | 24 | 24 | 36 | 36 | 0 | 0 | 12 | 0 | 0 | 49 | 47 | 0 | 39 | 45 | 0 | 200 | 24 | 120 | 24 | 1500 | 0 | 200 | 24 | 32 | 0 | 26 | 0 | 24 | 300 | 124 | 300 | 0 | 0 | 0 | 144 | 200 | 200 | 24 | 0 | 0 | 0 | 400 | 24 | 24 | 0 | 100 | 24 | 24 | 24 | 0 | 24 | 0 | 0 | 24 | 24 | 0 | 24 | 26 | 400 | 0 | 200 | 24 | 50 | 11269 |
| `ptype.existence-decision` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `ptype.generalize-pattern` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 30 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 24 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 54 |
| `ptype.infer-relationship` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `ptype.model-word-problem` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 24 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 24 |
| `ptype.optimize-constrained` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `ptype.optimize-extremum` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 77 | 30 | 56 | 74 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 30 | 54 | 0 | 28 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 349 |
| `ptype.prove-statement` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `ptype.sketch-graph` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `ptype.solve-for-unknown` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 80 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 46 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 34 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 12 | 24 | 0 | 18 | 54 | 20 | 0 | 23 | 25 | 0 | 33 | 27 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 332 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 24 | 0 | 0 | 12 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 764 |
| `ptype.transform-expression` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 600 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 600 |
| `ptype.verify-claim` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 24 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 24 | 0 | 0 | 0 | 24 | 0 | 24 | 0 | 0 | 24 | 24 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 24 | 0 | 24 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 24 | 0 | 0 | 0 | 0 | 24 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 24 | 0 | 0 | 0 | 264 |

### 2.5.1 0커버 유형 목록

- `ptype.construct-object` `ptype.existence-decision` `ptype.infer-relationship` `ptype.optimize-constrained` `ptype.prove-statement` `ptype.sketch-graph`
- 이 목록이 §4-① 트리거의 발화 계측기다(`ai_content_generation_gap_review.md` D3) — **6**/17종 미커버.

## 3. 코퍼스별 분해

| 코퍼스 | 인지 [1.0,2.0) | 절차 [2.0,3.0) | 개념 [3.0,4.0) | 숙달 [4.0,5.0] | 미평가(난이도 없음) | 범위밖(1.0~5.0 아님) |
|---|---|---|---|---|---|---|
| `problem_bank_binomial_distribution_v0` | 0 | 0 | 300 | 0 | 0 | 0 |
| `problem_bank_calculus1_integral_v0` | 0 | 0 | 400 | 0 | 0 | 0 |
| `problem_bank_calculus2_trig_integral_v0` | 0 | 0 | 80 | 0 | 0 | 0 |
| `problem_bank_combination_binomial_v0` | 0 | 121 | 0 | 0 | 0 | 0 |
| `problem_bank_complex_number_arithmetic_v0` | 0 | 900 | 0 | 0 | 0 | 0 |
| `problem_bank_conceptual_v0` | 0 | 136 | 224 | 0 | 0 | 0 |
| `problem_bank_conic_section_focus_v0` | 0 | 0 | 65 | 0 | 0 | 0 |
| `problem_bank_coordinate_geometry_v0` | 0 | 400 | 0 | 0 | 0 | 0 |
| `problem_bank_discrete_ev_v0` | 0 | 200 | 0 | 0 | 0 | 0 |
| `problem_bank_elementary_area_measure_v0` | 70 | 200 | 0 | 0 | 0 | 0 |
| `problem_bank_elementary_division_remainder_v0` | 400 | 0 | 0 | 0 | 0 | 0 |
| `problem_bank_elementary_gcd_lcm_v0` | 600 | 0 | 0 | 0 | 0 | 0 |
| `problem_bank_elementary_rounding_v0` | 600 | 0 | 0 | 0 | 0 | 0 |
| `problem_bank_elementary_v0` | 400 | 0 | 0 | 0 | 0 | 0 |
| `problem_bank_elementary_volume_measure_v0` | 50 | 250 | 0 | 0 | 0 | 0 |
| `problem_bank_generated_v0` | 129 | 233 | 236 | 21 | 0 | 0 |
| `problem_bank_highschool_quotient_rule_v0` | 0 | 0 | 200 | 0 | 0 | 0 |
| `problem_bank_killer_v0` | 0 | 0 | 0 | 120 | 0 | 0 |
| `problem_bank_linear_inequality_system_v0` | 0 | 600 | 0 | 0 | 0 | 0 |
| `problem_bank_matrix_ops_v0` | 0 | 320 | 0 | 0 | 0 | 0 |
| `problem_bank_measurement_unit_conversion_v0` | 157 | 23 | 0 | 0 | 0 | 0 |
| `problem_bank_middle_function_v0` | 200 | 0 | 0 | 0 | 0 | 0 |
| `problem_bank_misconception_mc_v0` | 0 | 475 | 605 | 0 | 0 | 0 |
| `problem_bank_p3_calculus1_diff_v0` | 0 | 240 | 204 | 60 | 0 | 0 |
| `problem_bank_p3_fill_v0` | 0 | 84 | 108 | 12 | 0 | 0 |
| `problem_bank_permutation_combination_v0` | 84 | 76 | 0 | 0 | 0 | 0 |
| `problem_bank_polynomial_arithmetic_v0` | 1200 | 300 | 0 | 0 | 0 | 0 |
| `problem_bank_polynomial_factoring_v0` | 0 | 600 | 0 | 0 | 0 | 0 |
| `problem_bank_probability_finite_v0` | 0 | 26 | 8 | 0 | 0 | 0 |
| `problem_bank_probability_law_v0` | 0 | 424 | 300 | 0 | 0 | 0 |
| `problem_bank_quad_ineq_v0` | 0 | 200 | 0 | 0 | 0 | 0 |
| `problem_bank_radian_conversion_v0` | 0 | 144 | 0 | 0 | 0 | 0 |
| `problem_bank_rephrased_v0` | 82 | 147 | 171 | 21 | 0 | 0 |
| `problem_bank_sample_mean_distribution_v0` | 0 | 200 | 200 | 0 | 0 | 0 |
| `problem_bank_sequence_sigma_v0` | 0 | 132 | 0 | 0 | 0 | 0 |
| `problem_bank_university_calc1_chain_quotient_v0` | 0 | 0 | 400 | 0 | 0 | 0 |
| `problem_bank_university_calc1_v0` | 0 | 0 | 200 | 0 | 0 | 0 |
| `problem_bank_v1` | 0 | 4 | 0 | 0 | 0 | 0 |
| `problem_bank_vector_operations_v0` | 69 | 331 | 0 | 0 | 0 | 0 |

## 4. 질문형식별 분해

| 코퍼스 | 단답형 | 객관식 |
|---|---|---|
| `problem_bank_binomial_distribution_v0` | 300 | 0 |
| `problem_bank_calculus1_integral_v0` | 400 | 0 |
| `problem_bank_calculus2_trig_integral_v0` | 80 | 0 |
| `problem_bank_combination_binomial_v0` | 121 | 0 |
| `problem_bank_complex_number_arithmetic_v0` | 900 | 0 |
| `problem_bank_conceptual_v0` | 0 | 360 |
| `problem_bank_conic_section_focus_v0` | 65 | 0 |
| `problem_bank_coordinate_geometry_v0` | 400 | 0 |
| `problem_bank_discrete_ev_v0` | 200 | 0 |
| `problem_bank_elementary_area_measure_v0` | 270 | 0 |
| `problem_bank_elementary_division_remainder_v0` | 400 | 0 |
| `problem_bank_elementary_gcd_lcm_v0` | 600 | 0 |
| `problem_bank_elementary_rounding_v0` | 600 | 0 |
| `problem_bank_elementary_v0` | 400 | 0 |
| `problem_bank_elementary_volume_measure_v0` | 300 | 0 |
| `problem_bank_generated_v0` | 524 | 95 |
| `problem_bank_highschool_quotient_rule_v0` | 200 | 0 |
| `problem_bank_killer_v0` | 120 | 0 |
| `problem_bank_linear_inequality_system_v0` | 600 | 0 |
| `problem_bank_matrix_ops_v0` | 320 | 0 |
| `problem_bank_measurement_unit_conversion_v0` | 180 | 0 |
| `problem_bank_middle_function_v0` | 200 | 0 |
| `problem_bank_misconception_mc_v0` | 0 | 1080 |
| `problem_bank_p3_calculus1_diff_v0` | 420 | 84 |
| `problem_bank_p3_fill_v0` | 204 | 0 |
| `problem_bank_permutation_combination_v0` | 160 | 0 |
| `problem_bank_polynomial_arithmetic_v0` | 1500 | 0 |
| `problem_bank_polynomial_factoring_v0` | 600 | 0 |
| `problem_bank_probability_finite_v0` | 34 | 0 |
| `problem_bank_probability_law_v0` | 724 | 0 |
| `problem_bank_quad_ineq_v0` | 200 | 0 |
| `problem_bank_radian_conversion_v0` | 144 | 0 |
| `problem_bank_rephrased_v0` | 345 | 76 |
| `problem_bank_sample_mean_distribution_v0` | 400 | 0 |
| `problem_bank_sequence_sigma_v0` | 132 | 0 |
| `problem_bank_university_calc1_chain_quotient_v0` | 400 | 0 |
| `problem_bank_university_calc1_v0` | 200 | 0 |
| `problem_bank_v1` | 3 | 1 |
| `problem_bank_vector_operations_v0` | 400 | 0 |
| **합계** | 13046 | 1696 |

## 5. 정직 회계 (누락·미지 값)

> 조용히 버리지 않는다 — 아래가 모두 0이어야 위 수치를 액면 그대로 읽을 수 있다.

| 항목 | 건수 |
|---|---:|
| 파싱 실패 라인 | 0 |
| 성취기준 코드 없는 문항 | 0 |
| 단원 코드 없는 문항 | 0 |
| 난이도 없는 문항 | 0 |
| 질문형식 없는 문항 | 0 |
| 유형(problem_type) 없는 문항 | 0 |
| 대장에 없는 성취기준 코드(종) | 0 |
| 다른 개정에만 있는 코드(종) | 0 |

JSON 산출물: ../../docs/data/problem_bank_coverage_4axis.json
