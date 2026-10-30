# QUAL-12 감사 슬라이스 E — 6개 코퍼스 발문↔정답 의미 정합 감사

판정 기준: 작업 트리 = `main` 0d5647e7 (2026-10-12, `data/corpus` 미커밋 변경 0). 저장소 파일 수정 0.
재현: `python3 audit_E_script.py --out audit_E_result.json --verbose` (종료 코드 0 = 불일치 0건) ·
검사기 변별력: `python3 audit_E_mutation_test.py` (결함 주입 13종 전건 검출, 종료 코드 0).

## 1. 코퍼스 분류 (가 결정론 템플릿 / 나 LLM 재진술 / 다 수작업)

| 코퍼스 | 분류 | 근거 (파일:줄) |
|---|---|---|
| problem_bank_conceptual_v0 (360) | **가** | `_provenance.json:5` "결정론 생성기(LLM 0)" · `l3/equivalent/conceptual_count_mc_generator.py:1`("결정론·LLM 0")·`:734` `@deterministic_generator` · 전 행 `authored_by=deterministic:conceptual_count_mc_generator`(360/360) · 오케스트레이터 `harness/conceptual_count_mc_batch.py` |
| problem_bank_misconception_mc_v0 (1080) | **가** | `_provenance.json:5` · `l3/equivalent/misconception_eval_mc_generator.py:1`("결정론·LLM 0")·`:2173` `@deterministic_generator` · `harness/misconception_mc_batch.py:1,18`("LLM 0") · `authored_by=deterministic:misconception_eval_mc_generator`(1080/1080) |
| problem_bank_generated_v0 (619) | **가** | `_provenance.json:5` "결정론 스켈레톤 생성기 15밴드(LLM 0)" · `harness/problem_corpus_batch.py:4,26`("LLM 0·DB 0·순수 결정론") · `l3/equivalent/skeleton_generator.py:1-3,484` · `authored_by=deterministic:problem_corpus_batch`(619/619) |
| problem_bank_killer_v0 (120) | **가** | `_provenance.json:5` "Vieta 근집계 킬러 결정론 생성기(LLM 0)" · `l3/equivalent/root_aggregate_skeleton_generator.py:1,195` · `authored_by=deterministic:root_aggregate_skeleton_generator`(120/120) · review_status 전부 `pending` |
| problem_bank_rephrased_v0 (421) | **나** (LLM 발문 재진술, 부모 = generated_v0) | `_provenance.json:5` "LLM 발문 다양화(question_text만 재작성)" · `l3/equivalent/rephrase.py:1-6,20,301`(LLM·`l3.pipeline.generate` 경유·temperature 0.7) · `harness/problem_corpus_rephrase.py:121-127`(LLM 재작성 시 `authored_by` 삭제) → 전 421행 `authored_by=None`. **주의**: 부모와 글자까지 동일한 무변화 사본이 274행, 실제 LLM 재작성은 147행(421−274). 정답·선지·수치는 부모에서 복사(부모와 answer/choices 불일치 0, 숫자 다중집합 불일치 0). |
| problem_bank_v1 (4) | **다** (수작업 시드) | `_provenance.json:5` "hand-authored seed (사람 저작 시드)" · `authored_by` 필드 없음. 메타 불일치: 행에는 `generation_type=FULLY_GENERATED`가 찍혀 있어 provenance와 어긋남(감사 결론에는 영향 없음) |

감사 모집단 확정에의 함의: 템플릿 코퍼스는 4종(conceptual·misconception_mc·generated·killer), 나·다는 각 1종. rephrased의 수학 내용은 generated_v0 생성기에 종속(정답·수치 복사)이므로 독립 의미 위험은 "LLM 문장이 방향어/요청을 바꿨는가"에 한정된다.

## 2. 감사 표 (전 행 대조, 샘플링 0)

대조 행 = 발문을 정규식으로 파싱해 **독립 구현으로 정답을 재계산하고 저장 answer와 대조한 행**. 미검증 = 파싱 실패/독립 계산 불가.

| 코퍼스 | 행 | 의미 템플릿(숫자접기 변이) | 대조 | 일치 | **불일치** | 모호 | **미검증** | 구조결함 | is_published=True |
|---|---|---|---|---|---|---|---|---|---|
| conceptual_v0 | 360 | 15 (36) | 360 | 360 | **0** | 24 | **0** | 0 | 0 |
| misconception_mc_v0 | 1080 | 45 (54) | 1080 | 1080 | **0** | 27 | **0** | 0 | 0 |
| generated_v0 | 619 | 15 밴드 (239) | 619 | 619 | **0** | 0 | **0** | 0 | 0 |
| rephrased_v0 | 421 | (238) | 421 | 421 | **0** | 6 | **0** | 0 | 0 |
| killer_v0 | 120 | (56) | 120 | 120 | **0** | 0 | **0** | 0 | 0 |
| v1 | 4 | 4 | 4 | 4 | **0** | 0 | **0** | 0 | 0 (필드 없음 4/4, 스키마 기본값 False — `schema/problem.py:836`) |
| 합계 | 2604 | | 2604 | 2604 | 0 | 57 | 0 | 0 | 0 |

"구조결함" = 정답이 선지에 정확히 1개/선지 상호 상이(수치 포함)/오개념 선지(distractor_map)가 정답과 다른 값/conceptual은 선지 0..3·해설이 주장하는 숫자=독립 정답.
미검증이 0인 것은 6개 코퍼스의 모든 템플릿에 독립 solver를 구현했기 때문이다(파싱 실패가 통과로 세어진 행은 없다). 최초 실행에서 rephrased 6행이 방향어 변이("크면서","작게" 등)로 미검증이었으나 solver를 보강해 대조했다.

### 2-1. 의미 어휘 판정
- 부정·한정 발문("아닌 것/옳지 않은 것/틀린 것/반드시/항상/적어도") 전 코퍼스 **0건**. 따라서 "부정 발문에서 answer가 부정 해석을 따르는가"는 검증 대상 자체가 없음(통과 아님, 해당 없음). "모두"는 misconception_mc `same_item_permutation`의 "모두 N 개의 문자"(총 개수 의미, 한정어 아님) 24행뿐. "옳은 것을 고르시오"는 generated/rephrased 극값 MC의 긍정형 15+15행.
- **방향어는 숫자 지정까지 발문에서 읽어 대조**: conceptual 판정형의 "수렴하면 1, 발산하면 0 / 벡터이면 1, 스칼라이면 0 / x>꼴이면 1, x<꼴이면 0 / 독립이면 1, 아니면 0"의 숫자 배정을 solver가 발문에서 파싱한다(다른 템플릿과 극성이 반대인 내적 템플릿 포함). generated/rephrased/killer의 큰/작은·극대/극소·가장 작은/큰·합/곱 방향어는 solver가 직접 해석한다.
- 선택지 정답 위치: conceptual은 선지가 항상 ['0','1','2','3'](answer는 그 중 하나, 위치=answer 값), 나머지 객관식 코퍼스는 answer 문자열이 선지에 정확히 1개이고 독립 정답과 수치적으로 같은 선지도 정확히 1개(구조결함 0).
- 오개념 선지가 정말 오답인가: conceptual 360 + misconception_mc 1080 전 행에서 distractor_map이 지목한 선지 ≠ 독립 정답(위반 0). 4개 선지 수치 상이(misconception_mc 1080/1080).

## 3. 결과 해석 — 불일치 0건에 대한 정직한 한계 진술

- 이번 슬라이스 6개 코퍼스에서는 QUAL-11 같은 "발문 문장이 정답/조건 계산과 어긋나는" 행을 **발견하지 못했다**(대조 2604/2604 일치). 이것은 "내 독립 구현이 생성기와 같은 관례를 공유하지 않았다"는 전제에서만 성립한다. 공유 위험이 있는 관례는 모호 항목(§4)으로 따로 센다.
- 검사기 변별력은 주입으로 확인했다(audit_E_mutation_test.py): 정답 전부 오답 선지로 교체(360/360 검출), 발문 방향 숫자 반전·answer 불변(수렴/발산 48/48, 벡터/스칼라 24/24, 독립 24/24, 부등식 24/24), 첫 수치 +1(misc 980 검출 + 72 미검증, 통과 28건은 a^0=1·g(2)=f(1)처럼 정답이 값에 무관한 28행임을 별도 확인), 오개념 선지를 정답으로(1080/1080), 큰↔작은 근(89/89), 극대↔극소(70 검출 + 8 비문화되어 미검증), 삼각방정식 가장 작은↔큰(4/4), 합↔곱(55 검출, 미검출 5행은 근의 합=곱인 방정식), v1(1/1). 모든 주입은 변경 행 수>0 단언 후 실행.
- **정답 분포 퇴화(불일치는 아니나 설계 결함 후보)**: conceptual 15 kind 중 14 kind가 24문항 전부 같은 정답(real_root_count/extremum/일대일/등비/극한/미분가능/급수/평균·중앙값/배반독립/조건부/닮음합동/내적 = 24/24 정답 "0", inequality_direction = 24/24 "1", root_loss = 24/24 "2"). 전체 정답 분포 "0"=288/360(80%). 판정형(0/1) 264행은 선지에 의미 없는 "2","3"이 있다. 생성기 설계 의도(오개념이 틀린 답을 주는 쪽만 출제)에서 비롯된 것이며 학생이 kind를 알면 정답을 추측할 수 있다.
- 해설: conceptual 해설이 주장하는 숫자 336행 추출 → 독립 정답과 0건 불일치(24행 limit 템플릿은 "달라 0이다" 문형이라 추출 못 해 미확인). misconception_mc는 1032/1080행 해설 본문에 정답 문자열이 존재, 48행(sine_sum·sine_period)은 해설이 값을 다른 표기("2π/21")로 쓰거나 값을 안 써서 확인 못 함. 해설 본문의 계산 서술 전체는 파싱하지 않았다(한계).

## 4. 모호 57건 (불일치 아님 · 관례 의존) 및 대표 예시 5건

1. **conceptual `limit_equals_value` 24행 — f(a) 미정의를 "성립 안 함"으로 읽는 관례**
   - 발문: "함수 f(x) = (x^2 - 3x + 2) / (x - 1) 에서 lim(x→1) f(x) = f(1) 이 성립하면 1, 아니면 0을 쓰시오." answer=0.
   - f(1)이 정의되지 않으므로(분모 0) "lim = f(1)"은 성립하지 않는다고 읽으면 0이다. 해설도 "극한값과 함수값이 달라"라 쓰지만 f(1)은 값이 아니라 미정의다. 한국 교과 관례("함숫값이 존재하고 극한값과 같다")에서는 0이 맞으나, 이 문장을 "극한값 −1 = 함숫값 없음"으로 읽는 학생에게는 모호하다. 24행 전부 정답 0.
2. **misconception_mc `scale_area` 24행 — 단일 수로 답하는 "넓이의 비"**
   - 발문: "닮음비가 18 인 두 도형의 넓이의 비를 구하시오." answer=324.
   - 비는 18²:1 또는 1:18² 표기가 필요한데 단일 수 324를 정답으로 한다(부피비 템플릿은 "1:?"로 명시해 이 문제가 없다). 같은 코퍼스 안에서 두 템플릿의 표기 규약이 다르다.
3. **misconception_mc `vieta_sum` 3행 — 허근(판별식<0)에도 "두 근의 합"**
   - 발문: "x² + 4x + 5 = 0 의 두 근의 합을 구하시오."(D=−4) answer=−4. 복소수 범위를 가정하면 맞으나 발문에는 범위 단서가 없다. 같은 부류: x²+2x+3=0, x²+3x+4=0 (slug `wm-misc-eval-mc-869ad9d64cf7`·`ed75b10d36ad`·`e18cabb90693`).
4. **rephrased 6행 — 정답 방향어는 일치하나 LLM 재진술 문장이 비문/비요청**
   - "이차방정식 x^2 + 4x - 32 = 0 의 두 근 중 어느 것이 작을지 판단하시오."(값 요구 아님, answer −8) / "…x^2 - 4x = 0 의 두 실근 중 크면서 근을 찾아보세요." / "원하는 두 근 중 큰 수는 원래 방정식 x^2 + 11x + 30 = 0의 해에서 찾아야 합니다."(질문문 아님). slug: `wm-skel-83d3e49908db-rephrased`·`cd0b59fdceaa`·`a7c05d7953f8`·`7b02121cf400`·`f70a7458a099`·`a5f2824753f0`(전부 `-rephrased`). 수학 오류는 아니나 PB-07/위생 게이트가 못 거른 발문 품질 사례.
5. **conceptual `events_independent`/`conditional_equal` — 전제 조건의 실현 가능성은 통과(전 행 확률 제약 만족)**: "두 배반사건 A,B에 대하여 P(A)=1/12, P(B)=1/6" 24행 모두 P(A)+P(B)≤1, "P(A)=1/12, P(B)=1/6, P(A|B)=1/2" 24행 모두 P(A∩B)≤min(P(A),P(B)). 즉 불가능 설정으로 인한 허위 문항은 0건(모호 아님, 점검 결과 기록).

## 5. 독립 계산 규칙 (생성기 import 0, 정규식 파싱 → sympy/Fraction)

- conceptual 15종: 실근 개수 = 판별식 부호; 극값 개수 = 도함수 임계점 좌우 부호변화 개수(sympy); 일대일 = 도함수 부호변화 유무; 등비급수 수렴 = |r|<1; 극한=함숫값 = 분모 0이면 f(a) 미정의→불성립(모호 표지), 아니면 limit 비교; 미분가능 = 좌·우 미분계수 비교; 급수 = k/n^p의 p>1 수렴(p=1, 1/2 발산); 제외 실수 = 분모 인수의 서로 다른 근 개수; 평균=중앙값 = Fraction 비교; 배반사건 독립 = P(A)P(B)=0; 조건부 P(A|B)=P(B|A) = P(A∩B)=P(A|B)P(B), P(B|A)=P(A∩B)/P(A) 및 가능성 검사; 닮음=합동 = 비=1; 내적 = 수(스칼라); 부등식 = sympy 구간 방향; 근 소실 = 서로 다른 실근 개수. 판정형은 발문의 "…이면 D" 숫자 배정을 파싱.
- misconception_mc 45종: 각 발문을 템플릿별 정규식으로 파싱해 정의대로 직접 계산(분배·연쇄법칙·덧셈정리·로그·합성 f(g(c))·평행이동 g(t)=f(t−s)·곱의 미분·내각합·나머지정리 f(a)·조합 C(n,r)·같은 문자 순열 (a+b)!/(a!b!)·원뿔/원 넓이 /π 등). 비독립 보조 점검: `verify.conditions`의 "x = 식" 우변 = answer (1080/1080, 위반 0 — 생성기 자체 일관성 확인일 뿐 독립 근거 아님).
- generated/rephrased: 이차방정식 근 선택(큰/작은/중근), 삼차 극대·극소 x좌표/극값(f''부호), 접선 기울기 m인 점, 지수·로그, 등차·등비 항/합, 삼각값, 삼각방정식(0°≤x<360° 전수 탐색), 점화식 수열. 방향어 변이("크면서", "작게" 포함)를 처리.
- killer: Vieta 값을 계수에서 직접(−b/a, (−1)^n c/a) + 근의 중복도/허근 분해, "서로 다른" 문구 15행은 서로 다른 근 합·곱으로 재계산(중근 0행·허근 0행이라 두 해석이 일치).
- v1: 수작업 4건 sympy 직접 풀이.

## 6. 한계 (모르는 것을 모른다고 적음)

1. 독립 solver가 템플릿의 **의도된 해석**을 따라 작성됐으므로, 생성기와 같은 오해를 공유하는 의미 오류(예: 반올림 vs 자리까지)는 이 방법으로 안 잡힌다. 관례 의존 후보는 §4에만 표기했고, 내가 떠올리지 못한 관례 충돌은 센 적이 없다.
2. 발문 **조사/문법**(josa) 정합은 정규식에서 변이를 허용했을 뿐 판정하지 않았다(QUAL-12 범위 밖). rephrased 발문의 한국어 품질은 6행만 마커로 식별했으며 전수 문법 검사가 아니다(마커 목록은 사람이 본 6행에서 도출 — 스크립트가 일반 비문을 탐지하는 것은 아님).
3. 해설(answer_explanation) 본문의 중간 계산 서술은 전수 대조하지 않았다(conceptual 336행의 결론 숫자, misconception_mc 1032행의 정답 문자열 포함 여부만).
4. `is_published`는 JSONL 필드 기준이다. DB 적재 후 값(populate 시점 변경 여부)은 보지 않았다. v1은 필드가 없어 스키마 기본값(False) 추정.
5. generated_v0는 요청 범위상 "가능한 만큼"이었으나 15 밴드 전체에 solver를 구현해 619/619 대조했다. `answer_format`(자연수/실수/분수) 라벨 정합은 대조하지 않았다.
6. 샘플링은 하지 않았으나, "일치"는 정확히 "내 독립 구현과 저장 answer가 같다"는 뜻이며 문항의 교육적 적절성(난이도·학년·성취기준 태그)은 이번 감사 대상이 아니다.
