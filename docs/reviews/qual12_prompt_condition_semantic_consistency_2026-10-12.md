# QUAL-12 · 템플릿 코퍼스 발문↔정답 의미 일치 전수 점검과 검사기 설계 판정 (2026-10-12)

**판정 기준:** `main` `5b561e31` (origin/main, 2026-10-12 실측) 위에 브랜치 `claude/adoring-goodall-3dfsdi`.
**이 문서의 "동결 테스트 착지"는 브랜치 기준이며 머지 전에는 main 기준이 아니다.** 코퍼스 감사 수치는 두 기준에서 같다 (이 브랜치는 `data/corpus/`를 한 바이트도 바꾸지 않았다 — `git status` 확인).

## 1. 결론

| 항 | 판정 |
|---|---|
| 현존 불일치 | **0건** — 38개 코퍼스 14,538행 전수를 발문만 읽는 독립 계산으로 재계산해 저장 정답과 대조했다. 미검증(파싱·계산 실패) 0건 |
| 설계 판정 | **(a) 채택 — 단, 코퍼스별 테스트의 기계적 템플릿화가 아니라 "어휘 트리거 거버넌스"** 로 구현. (b) 수용 게이트 편입 기각. (c) "불필요" 기각 |
| 구현 | 거버넌스 테스트 1 + 독립 계산 동결 테스트 1 (+ 기존 어림 동결 테스트에 대상 고정 1건). 결함 주입 9종 전건 RED |
| 코퍼스별 처분 태스크 | 불일치가 0건이라 ③의 분리 등재 대상 없음. 대신 범위 밖·미접촉 분기를 `QUAL-16`·`QUAL-17`로 등재 |

**0건의 의미를 과대하게 읽지 않는다.** 이 0은 "발문 의미 어휘가 걸린 코퍼스가 3개뿐"이라는 데이터 사실 위에 서 있다 (§4). 그 3개는 이제 동결되어 있다. 새 템플릿이 같은 어휘를 들여오는 순간 QUAL-11과 같은 사각이 다시 열리는 것을 막는 것이 이번 구현의 본체다.

## 2. 모집단 확정

`data/corpus/problem_bank_*` 38개 디렉터리, 14,538행. 전량 `is_published=False` (파일 필드 기준).

| 분류 | 코퍼스 | 근거 |
|---|---|---|
| 결정론 템플릿 (36) | 슬라이스 A 7 · B 8 · C 7 · D 10 · E 중 conceptual · misconception_mc · generated · killer 4 | 생성기 `@deterministic_generator`·배치 모듈 (`audit_E.md` §1 에 파일:줄) |
| LLM 재진술 (1) | rephrased_v0 (421행 중 274행은 부모와 글자까지 같은 무변화 사본, 실제 재작성 147행) | `audit_E.md` §1 |
| 수작업 (1) | v1 (4행) | `audit_E.md` §1 |

acceptance 문면의 "37종"과 숫자가 다르다. 문면의 37은 `harness/*_batch.py` 파일 수이며 코퍼스 수와 1:1이 아니다 (`concept_content_review_batch` 같은 비문항 배치가 섞여 있다). 실측 모집단은 위 표를 따른다.

## 3. 코퍼스별 결과 (전 행 대조, 샘플링 없음)

범례: 불일치 / 대조 행 · 모호 · 미검증. `is_published=True`는 전 코퍼스 0건.

| 슬라이스 | 코퍼스 | 불일치/대조 | 모호 | 미검증 |
|---|---|---|---|---|
| A 초등 | elementary_v0 | 0/400 | 0 | 0 |
| | elementary_area_measure | 0/270 | 0 | 0 |
| | elementary_division_remainder | 0/400 | 0 | 0 |
| | elementary_gcd_lcm | 0/600 | 0 | 0 |
| | elementary_rounding (QUAL-11 교정 후 회귀 확인) | 0/600 | 0 | 0 |
| | elementary_volume_measure | 0/300 | 0 | 0 |
| | measurement_unit_conversion | 0/180 | 0 | 0 |
| B 대수·함수 | polynomial_arithmetic | 0/1500 | 0 | 0 |
| | polynomial_factoring | 0/600 | 0 | 0 |
| | linear_inequality_system | 0/600 | 0 | 0 |
| | quad_ineq | 0/200 | 0 | 0 |
| | middle_function | 0/200 | 0 | 0 |
| | radian_conversion | 0/144 | 0 | 0 |
| | complex_number_arithmetic | 0/900 | 0 | 0 |
| | matrix_ops | 0/320 | 0 | 0 |
| C 미적분·수열 | calculus1_integral | 0/400 | 0 | 0 |
| | calculus2_trig_integral | 0/80 | 0 | 0 |
| | p3_calculus1_diff | 0/504 | 0 | 0 |
| | highschool_quotient_rule | 0/200 | 0 | 0 |
| | university_calc1 | 0/200 | 0 | 0 |
| | university_calc1_chain_quotient | 0/400 | 0 | 0 |
| | sequence_sigma | 0/132 | 0 | 0 |
| D 확률·기하·벡터 | binomial_distribution | 0/300 | 0 | 0 |
| | combination_binomial | 0/121 | 0 | 0 |
| | permutation_combination | 0/160 | 0 | 0 |
| | probability_finite | 0/34 | 0 | 0 |
| | probability_law | 0/724 | 0 | 0 |
| | sample_mean_distribution | 0/400 | 0 | 0 |
| | discrete_ev | 0/200 | 0 | 0 |
| | coordinate_geometry | 0/400 | 0 | 0 |
| | conic_section_focus | 0/65 | 0 | 0 |
| | vector_operations | 0/400 | 0 | 0 |
| E 비결정론·기타 | conceptual | 0/360 | **24** | 0 |
| | misconception_mc | 0/1080 | **27** | 0 |
| | generated | 0/619 | 0 | 0 |
| | rephrased | 0/421 | **6** | 0 |
| | killer | 0/120 | 0 | 0 |
| | v1 | 0/4 | 0 | 0 |

모호 57건의 내용: conceptual 24건은 `limit_equals_value` — f(a)가 미정의인 것을 "성립 안 함"으로 읽는 관례에 의존. misconception_mc 27건은 `scale_area` 24건(넓이의 비를 단일 수로 답함)과 `vieta_sum` 3건(판별식<0인데 "두 근의 합"). rephrased 6건은 정답은 맞지만 발문이 비문이거나 값을 요구하지 않는 경우. 모호는 "저장값이 한 해석에는 일치한다"는 뜻이며 불일치로 계상하지 않았다.

**재현:** 아래 스크립트는 생성기 모듈을 import하지 않고 저장소 루트를 `__file__` 기준으로 찾는다. 5종 모두 종료 코드 0 (불일치·미검증·스캔 0건이면 비0).

```bash
python3 docs/reviews/qual12_stem_audit/audit_A_script.py
python3 docs/reviews/qual12_stem_audit/audit_B_script.py
python3 docs/reviews/qual12_stem_audit/audit_C_script.py
python3 docs/reviews/qual12_stem_audit/audit_D_script.py
python3 docs/reviews/qual12_stem_audit/audit_E_script.py
```

감사 에이전트의 보고는 그대로 믿지 않고, 세션이 스크립트를 직접 재실행해 숫자를 확인했다 (A·B·C·D·E 전부 exit 0). 슬라이스별 상세·독립 계산 규칙·한계는 `docs/reviews/qual12_stem_audit/audit_{A..E}.md`.

## 4. 왜 0건인가 — 의미 어휘의 분포

발문에 의미가 걸린 어휘 계열이 실제로 나타나는 코퍼스를 전 코퍼스 스캔으로 셌다 (행 수).

| 어휘 계열 | 나타나는 코퍼스 |
|---|---|
| 자리 지시 ("X의 자리") | elementary_rounding 600 **만** |
| 올림·버림·반올림 | elementary_rounding 600 **만** |
| 경계 방향 (이상·이하·초과·미만) | p3_calculus1_diff 7 · probability_finite 8 |
| 한정 (적어도·정확히·반드시·항상) | p3_calculus1_diff 2 · probability_finite 9 |
| 부정 (옳지 않은·아닌 것·틀린 것) | **0건** (전 코퍼스) |

즉 QUAL-11형 사고가 날 수 있는 입구가 3개 코퍼스에 몰려 있고, 그중 어림은 QUAL-11/15가 이미 동결했다. 나머지 둘 (probability_finite 17행, p3_calculus1_diff 9행)이 이번에 동결 대상이 됐다.

**주의:** 위 표는 QUAL-11형 어휘에 한정한다. "큰 근/작은 근", "~보다 큰", "A에서 B를 뺀" 같은 순서 방향어는 이 표에 넣지 않았다 — 감사에서 불일치 0건이었으나 동결은 안 됐고, `QUAL-16`이 소유한다.

## 5. 통과했으나 데이터가 분기를 밟지 않은 지점 (불일치 아님)

"일치"가 곧 "그 해석이 시험됐다"는 뜻은 아니다. 감사 에이전트들이 스스로 밝힌 미접촉 지점이다.

- 연립부등식 600행: 전부 x 계수 양수. 계수가 음수여서 부등호가 뒤집히는 분기는 0행.
- 이차부등식 200행: 전부 선행계수 양수. 두 경계값의 합은 부등호 방향과 무관해 방향 오해석은 정답 대조로 못 잡고 설명문의 "바깥쪽/안쪽"으로만 잡힌다 (설명문 판정은 200/200 일치).
- 적분 코퍼스의 넓이·거리 문항 230행: 구간에서 피적분 함수가 항상 양수라 "넓이 vs 부호 있는 적분", "거리 vs 변위" 해석이 갈리지 않는다.
- division_remainder: 고유 (A,B) 200쌍 중 118쌍(236/400행)이 몫=나머지. 몫과 나머지를 바꿔 이해해도 정답이 나온다. 결함 주입 시험에서 몫↔나머지 교환이 50행 중 20행만 잡힌 원인이 이것이다.
- conceptual: 정답 "0"이 288/360(80%), 판정형 264행에 무의미 선지 "2","3". 불일치는 아니고 설계 결함 후보.
- answer_format 불일치: coordinate_geometry 200행·vector_operations 196행은 "실수"인데 정수 문자열, discrete_ev 28행은 "분수"인데 정수 문자열.

전부 `QUAL-17`로 이관했다 (판정만, 수정은 판정 결과에 따른 후속).

## 6. 설계 판정

### (b) 수용 게이트(acceptance)에 발문 파싱 대조 단계 — 기각

1. **발문 문법이 코퍼스마다 다르다.** 공통 문법이 없어 게이트에 넣을 "발문 파서"는 사실상 코퍼스마다의 파서이고, 그것은 (a)의 독립 계산을 게이트 안으로 옮긴 것에 불과하다.
2. **기존 선례가 이미 같은 길을 가다 막혔다.** `l3/equivalent/retag.py`의 `StatementConsistencyAuditor`(발문 수식↔조건식 구조 대조)가 정확히 (b)의 형태다. 그런데 `evaluate_equivalent_candidate`의 `tag_auditor=`를 실제로 넘기는 곳은 `defect_detection_eval.py` 한 곳이고, 감사기를 직접 부르는 곳도 `p3_audit_qualification.py`를 더한 평가 도구 2곳뿐이다. 운영 생성 경로인 `orchestrator.run_equivalent_generation`을 경유하는 모듈 43개는 감사기 없이 게이트를 부른다 (`grep -rn "tag_auditor=" src`·`grep -rn StatementConsistencyAuditor src`·`grep -rln run_equivalent_generation src` 로 확인). 즉 게이트에 대조 단계를 "만든" 선례가 있는데 운영에 연결되지 않은 채다.
3. **그 감사기는 구조적으로 공허 통과를 허용한다.** 발문에서 방정식을 못 뽑으면 "감사 불가는 통과 (반증기이지 필수 게이트가 아님)"로 처리한다. QUAL-11 사고의 발문은 방정식이 아니라 자연어 지시어("X의 자리")였으므로 이 감사기는 어림 코퍼스에서 항상 "감사 불가 → 통과"였을 것이다.
4. **오탐 비용이 생성 경로에 직접 걸린다.** 게이트가 정상 문항을 거부하면 코퍼스 생성이 멈춘다. 반증기 성격(모르면 통과)과 필수 게이트 성격(모르면 거부)은 양립하지 않는다.

### (c) 둘 다 불필요 — 기각

0건이라는 결과만 보면 "불필요"로 읽힌다. 그러나 QUAL-11 사고 시점에도 수용 게이트는 전건 통과였고 불일치율은 537/600 (89.5%)이었다. 게이트 통과와 의미 일치는 독립이다. 현재 0건은 어휘 부재로 설명되며 (§4), 어휘가 늘면 같은 사각이 열린다. 방어를 안 두는 것은 이 프로젝트의 "보호 장치를 실패 주입 없이 선언하지 않는다"·"스캔 0건은 실패" 계열에 어긋난다.

### (a) 채택 — 형태는 "어휘 트리거 거버넌스"

코퍼스 36종 각각에 독립 계산 테스트를 쓰는 것은 비용 대비 효과가 낮다 (대다수 코퍼스에는 해석이 갈릴 어휘가 없다). 대신:

- **트리거:** 발문에 의미 어휘 계열(자리·올림/버림·경계 방향·한정·부정)이 나타나는 (코퍼스, 계열) 쌍을 전 코퍼스에서 스캔한다.
- **등록 의무:** 그 쌍은 전부 독립 계산 동결 테스트에 등록되어야 한다. 미등록 어휘 유입 = RED. 어휘가 사라졌는데 등록이 남은 낡은 등록 = RED. 등록 테스트 파일 부재 = RED. 등록 테스트가 해당 코퍼스를 본문에서 다루지 않는 위장 등록 = RED.
- **공허 통과 차단:** 코퍼스 38개·14,000행 미만의 스캔, 어휘 쌍 0건, 어휘 행 0건은 전부 RED.

이것이 (a)의 "템플릿화"와 다른 점은, 개별 코퍼스의 독립 계산을 일반화하려는 시도(문형이 달라 불가능)가 아니라 **"독립 계산이 있어야 하는 곳"을 기계가 지목하게** 한 것이다.

### 집행 지점 (정본화와 별항 — 구현 상세와 분리)

- **정본화:** `tests/backend/harness/test_stem_semantic_hook_coverage.py`의 `HOOK_FAMILIES`·`REGISTRY`.
- **집행 지점:** CI `backend` 잡의 `Pytest (with coverage)` 스텝 (`-m "not corpus_authoring"`, `testpaths=../../tests/backend`). 새 테스트는 `corpus_authoring` 마커가 없고 `tests/backend/harness/`에 있어 같은 수집 경로를 탄다 (§8에서 수집 경로로 확인).
- **수용 게이트는 건드리지 않았다** — (b) 기각이므로 PB 수용 게이트 호출처 경유 항목은 해당 없다.
- **한계 (명시):** 이 거버넌스는 새 코퍼스가 *의미 어휘를 발문에 쓰는 경우*만 잡는다. 어휘 없이 해석이 갈리는 템플릿(예: 순서 방향어)은 `HOOK_FAMILIES` 밖이다 — `QUAL-16`.

## 7. 구현과 변별력

신규·변경 파일 (전부 `tests/backend/harness/`, 소스 변경 0):

- `test_stem_semantic_hook_coverage.py` — 거버넌스 + 자기 변별력 시험 (미등록 코퍼스 유입·기등록 코퍼스의 새 계열·낡은 등록·파일 부재·코퍼스 미언급 위장 등록·계열별 검출).
- `test_stem_hook_independent_answers.py` — probability_finite 17행(동전 "정확히 k번"·주사위 "합이 k 이상")과 p3_calculus1_diff 9행("n은 2 이상의 자연수"·"항상 … 최솟값")을 생성기 호출 없이 발문만 파싱해 재계산. 발문이 아는 형태가 아니면 RED (파싱 실패는 통과가 아니다).
- `test_elementary_rounding_corpus_convention.py` — 대상 코퍼스 이름 고정 1건 추가. 거버넌스의 "등록 테스트가 코퍼스를 다루는가" 검사가 이 파일이 코퍼스를 상수로만 참조한다는 사실을 잡아내서 생긴 변경이다.

**결함 주입 (실제 코퍼스 파일, 매 건 `mutated != original` 단언 + 원복 `sha256` 동일 단언, 원복은 `cp` 백업):**

| # | 주입 | 결과 |
|---|---|---|
| M1 | probability_finite 주사위 정답 오염 | RED |
| M2 | probability_finite "이상"→"이하" 발문 변조 | RED |
| M3 | probability_finite 동전 정답 오염 | RED |
| M4 | p3 n 탐색 정답 오염 | RED |
| M5a | p3 PQ 최솟값 정답 오염 | RED |
| M5b | p3 PQ 최솟값 대신 경계값(t=0) 저장 | RED |
| M6 | p3 "2 이상의 자연수"→"2 초과" 변조 | RED |
| M7 | 미등록 코퍼스(coordinate_geometry)에 경계어 유입 | RED |
| M8 | 어림 정답 오염 (기존 동결 테스트 회귀) | RED |

주입 시도 중 한 건(M5 최초판)이 GREEN으로 나왔다. 가드 결함이 아니라 **주입 하네스 결함**이었다 — 행 선택 조건이 JSON 한 줄 전체(해설 포함)에서 "항상"을 찾아, 발문이 아닌 해설에 그 단어가 있는 엉뚱한 행(행 363)을 오염시켰고 그 행은 트리거 대상이 아니라 GREEN이 맞았다. 발문 기준으로 행을 고른 M5a·M5b로 재주입해 RED를 확인했다. 최초판 결과는 폐기한다.

감사 스크립트 자체의 변별력은 별도로 확인했다 (정답 +1 오염 시 전 코퍼스 검출, 발문 의미 어휘를 뒤집은 사본에서 슬라이스별 검출률 — 예: 연산 +↔− 600/600, 극대↔극소 49/56). 미검출분은 정답값이 우연히 같은 행으로 추정되며 전수 확인은 하지 않았다 (`audit_B_mutation.py`·`audit_E_mutation_test.py`).

## 8. acceptance 재대조

| 항 | 판정 |
|---|---|
| ① 실측 선행·전수 열거·독립 대조·판정 기준 해시 | 이행 — §2·§3, 판정 기준 `5b561e31` 상단 명시 |
| ② 설계 판정 + 집행 지점 별항 | 이행 — §6 (a) 채택(어휘 트리거 거버넌스)·(b) 기각·(c) 기각, 집행 지점 분리 |
| ③ 불일치 코퍼스 처분 태스크 분리 | 해당 없음 (불일치 0). 미접촉 분기·범위 밖은 QUAL-16/17로 등재 |
| ④ 구현 시 결함 주입·공허 통과 차단 | 이행 — §7 (9종 RED, 스캔 0건·파싱 실패·어휘 행 0건 RED) |

## 9. 한계 (정직 표기)

- **독립 구현의 기준은 한국 초·중·고·대학 교재의 통상 해석이다.** 교과서 원문과 대조하지 않았고, 사람 교수학자 검수가 아니다. 구현자(감사 에이전트)가 생성기와 같은 관례를 공유했다면 "일치"로 나온다. 줄이려고 어구마다 대안 해석값을 함께 계산했으나 목록에 든 대안에 한한다.
- **계산 엔진이 생성기와 같은 계열(SymPy)이다.** 막은 것은 "문장→식" 해석 불일치이고 SymPy 자체의 오류는 이 점검의 대상이 아니다.
- **해설(answer_explanation) 대조는 키워드·수치 일치 수준**이다. 서술형 논리 전개의 정당성은 검증하지 않았다.
- **학생 노출 건수는 파일 필드(`is_published`) 기준 0이다.** DB(`problem` 테이블) 쪽 노출 건수는 이 환경에 DB가 없어 확인하지 못했다. 파일 필드 0과 DB 0이 같다고 가정하지 않는다.
- 브랜치 미머지 상태의 판정이다 — 동결 테스트가 main에 착지하기 전에는 §6 집행 지점이 main에서 동작하지 않는다.

## 10. 후속

- `QUAL-16` — 순서 방향어 계열 동결 확장 (거버넌스 `HOOK_FAMILIES` 확장 포함).
- `QUAL-17` — 미접촉 분기·변별력 약한 문항·answer_format 불일치의 처분 판정.
