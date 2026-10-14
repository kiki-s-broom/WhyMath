# 미태깅 코퍼스 30종 유형 태깅 계약 편입 — CONT-09 실측 기록 (2026-10-12)

> 판정 기준: `main` `d873d064`(작업 브랜치 `claude/brave-lovelace-cbbt8k`가 이 커밋 위에서 분기). 아래 수치는 전부 이 트리에서 직접 실행한 값이다. 명령은 스크래치 가상환경(Python 3.13)에서 `python -m whymath_backend.harness.problem_type_backfill` / `problem_bank_coverage`로 실행했다.

## 0. 결론 한 줄

S3-27 이후 추가된 코퍼스 30종 11,396문은 전량 `unit_codes` 표 분류로 편입됐고(미태깅 0), 스캔 전체 14,538문이 `problem_type_codes`를 갖는다. **0커버 유형은 9종 → 7종**으로 바뀌었다. 단, 그 두 종(`condition-satisfaction` 800문·`transform-expression` 600문)이 새로 커버되는 것은 **내가 내린 분류 판단 두 건(§4)에 전적으로 의존한다** — 다르게 판단하면 9종이 그대로다. 사람 검토가 필요한 지점이며 §5에 민감도를 적었다.

## 1. acceptance ① — 전제 실측

| 항목 | CONT-04 기록(2026-10-09) | 이번 실측(2026-10-12) |
|---|---|---|
| 스캔 문항 수 | 14,034 | **14,538** |
| 태깅 보유 | 2,638 (18.8%) | **3,142** (21.6%) |
| 미태깅 | 11,396 | **11,396** |
| 미태깅 코퍼스 수 | 30 | **30** |

미태깅 11,396문은 그대로이고, 분모가 504 늘었다. 늘어난 504는 `problem_bank_p3_calculus1_diff_v0`이며 **생성 시점에 레코드별로 이미 태깅돼 있었다**(504/504). 이 코퍼스는 직접 분류 6종·계보 1종 어느 좌석에도 없었지만 태깅이 있었기에 미태깅 합계에는 들어가지 않는다 — §3의 네 번째 좌석이 이 사실을 명시적으로 만든다.

소유 태스크 0건: `backlog/tasks/*.yaml` 중 `problem_type_codes`·`problem_type_mapping`·"유형 태깅"을 언급하는 미완료 태스크는 이 태스크 자신과 `PB-20`(변형 코퍼스 노출 경로 조사 — 태깅 소유 아님)뿐이다.

## 2. acceptance ③ — 태깅 방식 판정

| 방식 | 코퍼스 | 문항 |
|---|---|---:|
| 생성기 identity(`unit_codes`) 표 분류 — 신규 편입 | 30종 | 11,396 |
| 계보 분류 | 0종 | 0 |
| 태깅 불가 | 0종 | 0 |

30종 모두 `unit_codes`가 생성기(또는 생성기의 밴드) 1개와 1:1로 남는다(코퍼스당 값 1~3개, 표 키 총 41개). 그래서 계보 분류도 태깅 불가도 필요 없었고, 표의 키 집합이 실코퍼스의 `unit_codes` 집합과 같은지를 테스트가 코퍼스마다 대조한다(`test_table_keys_equal_observed_unit_codes`). LLM 0·런타임 문항 텍스트 추론 0이며 표의 값은 §4의 근거로 사람(에이전트)이 판단해 고정했다.

## 3. 구조 변경

- `problem_type_mapping.py`: `_UNIT_CODE_TABLES`(30종·41키)·`UNIT_CODE_TABLE_CORPORA`를 신설하고 `TARGET_CORPORA`에 편입했다(6종 → 36종). `classify_record`에 표 분기를 추가했다. 표에 없는 `unit_codes`는 빈 리스트(미태깅)로 드러난다.
- **네 번째 좌석 `SELF_TAGGED_CORPORA`**: 생성 시점에 레코드별 유형을 직접 기록하는 코퍼스(`p3_calculus1_diff_v0`). 같은 `unit_codes` 안에서도 유형이 갈려(예: `MEAN-VALUE-THEOREM`은 solve 54·evaluate 12·count 6) 표로 분류할 수 없다. `TARGET_CORPORA`에 넣으면 백필이 저장된 유형을 빈 리스트로 덮어 지우므로 별도 좌석으로 두고 **백필이 쓰지 않게** 했다. 리포트에는 총량·태깅·미태깅을 읽기 전용으로 싣고(`self_tagged` 절), `grand_total`이 스캔 전체(14,538)와 정합한다.
- `find_corpus_seat_violations()`: acceptance ④의 전수 귀속 거버넌스. 아래 §6.

## 4. 판단 지점 — 사람 검토 요청

표의 41개 키 중 34개는 "식·공식에 값을 대입·연산해 값을 낸다"인 `evaluate-expression`이다. 아래 4군(7키·1,816문)만 다른 유형으로 분류했고, 이 부분이 사람 판단이 갈릴 수 있는 곳이다.

| 군 | 키 | 문항 | 분류 | 근거 | 대안 |
|---|---|---:|---|---|---|
| 경우의 수 | `REPEATED-COMBINATION`·`SUM-PRODUCT-PRINCIPLE`·`PERMUTATION` | 216 | `enumerate-cases` | 발문이 "경우의 수를 구하시오". `misconception_mc`의 `combination-no-denominator`와 같은 판단 | 없음(확정적) |
| 미정계수 | `LINE-EQUATION` | 200 | `determine-coefficient` | 두 점 조건으로 `y=ax+b`의 a·b를 역으로 결정. `problem_bank_v1`의 `wm-quad-fn-axis`와 동형 | `solve-for-unknown` |
| 범위 판정 | `LINEAR-INEQUALITY-SYSTEM`·`QUAD-INEQ-BOUNDARY` | 800 | `condition-satisfaction` | 카탈로그 정의가 "조건을 성립시키는 값·**범위**를 판정"이고, 발문이 부등식을 만족하는 x의 범위의 경계를 묻는다 | `solve-for-unknown`(경계 = 방정식의 근) |
| 식 변형 | `POLYNOMIAL-FACTORING` | 600 | `transform-expression` | 이차식을 `(x+p)(x+q)`로 변형하는 것이 핵심 행동. `skill.factorization`이 이 유형 소속. 상수항 읽기는 사후 단계 | `evaluate-expression`(답이 숫자 하나) |

**일관성 판단(별도 기록)**: 단위 환산 4종(`AREA-/VOLUME-UNIT-CONVERSION`·`MEASUREMENT-UNIT-CONVERSION`·`RADIAN-CONVERSION`)은 같은 인지 행동(상수배 연산)이라 전부 `evaluate-expression`으로 통일했다. `RADIAN-CONVERSION`만 `answer_format`이 `식`이라 `transform-expression`으로 갈 여지가 있었으나, 나머지 환산과 갈라놓을 근거가 없어 통일했다. `CALC1-INTEGRAL`(부정적분 후 F(0)=c로 상수 결정)은 적분상수 결정 단계가 있지만 주 행동이 적분 공식 실행이라 `evaluate-expression`이다.

## 5. acceptance ② — 0커버 유형 전후

방법: 같은 `problem_bank_coverage` CLI를 데이터 기록 전·후에 각각 실행했다(둘 다 exit 0).

| | 태깅 합계 | 0커버 유형 수 |
|---|---|---|
| 전 | 3,142 | **9** |
| 후 | 14,538 | **7** |

유형별 문항 수(전 → 후):

| 유형 | 전 | 후 |
|---|---:|---:|
| `evaluate-expression` | 1,617 | 11,197 |
| `condition-satisfaction` | 0 | 800 |
| `transform-expression` | 0 | 600 |
| `enumerate-cases` | 56 | 272 |
| `determine-coefficient` | 1 | 201 |
| `solve-for-unknown` | 708 | 708 |
| `optimize-extremum` | 321 | 321 |
| `verify-claim` | 264 | 264 |
| `count-solutions` | 145 | 145 |
| `generalize-pattern` | 30 | 30 |
| 나머지 7종 | 0 | 0 |

**후에도 0커버인 7종**: `construct-object`, `existence-decision`, `infer-relationship`, `model-word-problem`, `optimize-constrained`, `prove-statement`, `sketch-graph`. 이 7종은 어떤 분류 판단을 해도 채워지지 않는다 — 30개 코퍼스의 발문이 전부 "값 하나를 구하시오"형이라 해당 인지 행동을 요구하는 문항이 없다. 즉 **이 7종 0커버는 태깅 사각이 만든 착시가 아니라 저작 공백의 실측**이다. 이것이 CONT-04가 남긴 질문("9종 중 실제로 커버되는 유형이 있는가")의 답이다.

**민감도**: 9 → 7의 변화는 §4의 `범위 판정`(800문)과 `식 변형`(600문) 두 판단에서만 나온다. 두 군을 대안대로 분류하면 0커버는 9종 그대로다. 이 계측기는 CONT-04가 확인한 대로 `ai_content_generation_gap_review_r3.md` 트리거 ①의 ⓒ 조건(`zero_coverage_types`)을 공급하는데, ⓒ는 7종으로도 계속 성립하고 트리거는 ⓐ(결정론 템플릿 아키텍처) 미착지로 계속 미발화다 — 판단이 바뀌어도 트리거 결론은 바뀌지 않는다.

**분포 집중도(부수 관측)**: 스캔 전체의 `evaluate-expression` 비중이 11,197/14,538 = 77.0%다. 유형 17종 중 한 유형이 4분의 3 이상이라는 것은 저작 우선순위(유형 다양화)의 입력이다. 이 태스크의 범위는 아니며 관측만 남긴다.

## 6. acceptance ④ — 재발 차단과 변별력

`find_corpus_seat_violations()`가 `data/corpus/problem_bank*` 디렉터리 전부를 네 좌석(`TARGET`·`LINEAGE`·`EXCLUDED`·`SELF_TAGGED`)에 대조한다. 위반 4종: ① 어느 좌석에도 없는 코퍼스 ② 좌석 중복 ③ 디렉터리 없는 죽은 좌석 ④ **스캔 0건**(빈 루트·없는 경로는 "위반 없음"이 아니라 위반 — 공허한 통과 금지).

테스트(`TestCorpusSeatContract`)가 각 위반을 주입해 RED를, 정상 상태에서 GREEN을 실측한다. 실코퍼스 1종(`problem_bank_binomial_distribution_v0`)을 좌석에서 빼면 정확히 1건 RED이고 원복하면 GREEN이다.

모듈 뮤테이션 5종을 `cp` 백업/`cmp` 원복으로 주입해 전건 검출을 확인했다(주입 전 `119 passed`, 뮤테이션마다 원복 후 바이트 동일 확인).

| 뮤테이션 | 검출(실패 건수) |
|---|---:|
| M1 `TARGET_CORPORA`에서 표 코퍼스 제외 | 10 |
| M2 `SELF_TAGGED_CORPORA` 비움 | 5 |
| M3 p3를 `TARGET_CORPORA`에도 등재(중복 좌석) | 9 |
| M4 `LINE-EQUATION` 1키 오매핑 | 1 |
| M5 `classify_record`의 표 분기 제거 | 34 |

M4가 1건만 RED인 것은 하네스 결함의 신호가 아니다 — 그 키는 `coordinate_geometry_v0` 골든 1건에만 닿는다(주입은 `mutated != original` 단언으로 실제 적용을 확인했다).

## 7. 데이터 기록 검증

- `python -m whymath_backend.harness.problem_type_backfill` 실행 결과: 30개 파일 11,396행 변경(1회차), 2회차 `changed=0`, 전 `problems.jsonl`의 sha256 목록이 1·2회차 사이 동일(바이트 멱등).
- 변경된 11,396행을 `git show HEAD:<파일>`과 대조: **`problem_type_codes` 외 필드 변경 0건, 키 순서 불변**, 변경 전 값은 전건 `[]`, 변경 후는 전건 길이 1. 14,538행 전부가 `json.dumps(json.loads(line), ensure_ascii=False) == line`을 만족해(재직렬화 항등) 줄 바이트가 다른 필드에서 흔들리지 않는다.
- 이 코퍼스들의 `_provenance.json`에는 `problems.jsonl` sha256 고정이 없다(`grep -c sha256` 0건 — 표본 코퍼스 실측). 데이터 변경이 출처 계약을 깨지 않는다.

## 8. 한계 (정직 고지)

- 표의 값 41개는 에이전트가 발문 샘플과 카탈로그 정의를 대조해 판단한 것이다. `pedagogy-designer`나 Kiki의 검토를 받지 않았다. §4의 4군은 검토 대상으로 표시했다.
- 이 계약은 **유형의 존재**를 닫는다. 유형이 *정확한가*는 §4 판단의 몫이며, 모호한 경계를 기계로 판정하는 장치는 없다(골든 분포 테스트는 표가 *의도대로 적용되는지*를 보장할 뿐 표가 *옳은지*는 보장하지 않는다).
- `problem_bank_coverage`의 0커버 판정은 이제 전체 코퍼스를 본다. 다만 코퍼스가 앞으로 늘면 새 코퍼스는 좌석 편입 전까지 RED로 남는다 — 이것이 의도한 동작이다.

## 9. 이 태스크가 바꾼 파일

- `src/backend/whymath_backend/harness/problem_type_mapping.py` — 표 30종·`SELF_TAGGED_CORPORA`·`find_corpus_seat_violations`.
- `src/backend/whymath_backend/harness/problem_type_backfill.py` — 자가 태깅 읽기 전용 회계(`self_tagged` 절).
- `src/backend/whymath_backend/harness/problem_bank_coverage.py` — 모듈 docstring의 낡은 한계 서술 정정(동작 변경 없음).
- `tests/backend/harness/test_problem_type_mapping.py`·`test_problem_type_backfill.py` — 골든 30종·표 정합·전수 귀속·자가 태깅·백필 케이스.
- `data/corpus/problem_bank_*/problems.jsonl` 30개 — `problem_type_codes` 11,396행.
- 본 문서.

## 10. 리뷰 반영 (PR 코드 리뷰 후속)

리뷰 7건을 코드와 대조해 판정했다.

**수정한 3건**
- **저장분 고정 테스트 부재(사실)**: 직접 분류 36종은 유도값(`classify_record`)만 대조했고 *저장된* 태그를 고정하는 테스트가 없었다(계보 코퍼스·자가 태깅만 있었다). 배치 CLI가 코퍼스를 재생성하면 `problem_type_codes=[]`로 돌아가는데 그때 어떤 테스트도 RED가 아니었다. `test_stored_codes_match_derivation_in_all_target_corpora`를 추가했다. 변별력: `radian_conversion_v0`의 태그 144행을 비운 상태에서 이 테스트**만** RED(1 failed·104 passed)이고 `cp`/`cmp` 원복 후 GREEN.
- **백필의 침묵 덮어쓰기(사실)**: 표가 모르는 행에서 유도값이 빈 리스트이면 기존의 비어 있지 않은 태그를 `[]`로 지웠다(원래 6종에도 있던 동작이 30종으로 넓어졌다). 이제 원문 바이트 그대로 두고 리포트 `preserved` 건수로 드러낸다.
- **glob 중복(사실)**: `_CORPUS_DIR_GLOB`가 계측기의 `CORPUS_DIR_GLOB`와 같다는 주석뿐이던 것을 `test_seat_glob_equals_coverage_meter_glob`로 묶었다.

**수정하지 않은 4건과 사유**
- **분류 판단 3군(1,400문)이 발문과 맞지 않는다는 지적**: 이미 §4–5에 대안·민감도와 함께 "사람 검토 필요"로 올렸고 이번 리뷰가 새 반증을 내지는 않았다. 카탈로그 정의는 `condition-satisfaction`을 "판별식·범위 조건형"이라 적고 있어 부등식 범위 판정이 정의 밖이라 단정할 수도 없다. 판단이 갈리는 지점이므로 Kiki/`pedagogy-designer` 검토에 맡긴다. 표를 바꾸면 골든 합계 재산출이 필요하다.
- **`_build_parent_type_index`가 36종을 읽는다는 지적**: 사실이나 비용은 파일 수십 개 한 번 읽기 수준이고 실코퍼스 slug 충돌은 0건이다(테스트가 동결). 부모 코퍼스를 하드코딩하면 오히려 계보 확장 시 침묵 누락 위험이 생긴다.
- **CLI exit 0 고정**: 관측·백필 CLI는 의도적으로 게이트가 아니다(모듈 docstring). 판정은 CI의 `TestCorpusSeatContract`·`TestSelfTaggedSeat`가 맡는다.
- **`RADIAN-CONVERSION`·`BINOMIAL-COEFFICIENT` 일관성**: §4에 이미 근거와 대안을 적었다. 판단 문제이며 검토 대상이다.

**다운스트림 영향(리뷰가 짚은 부분의 실측)**: `problem_type_codes`를 읽는 곳은 `phase3_metrics` ③·`phase3_coverage`·`repeat_recommendation_report`다. 앞의 둘은 `review_status=approved` 문항만 센다. 새로 태깅된 11,396문은 전부 `review_status` 미설정(None)이라 영향이 없다(승인 2,984·보류 158은 기존 태깅 코퍼스). `repeat_recommendation_report`의 유형 집중도 축은 코퍼스 태그를 그대로 읽으므로 풀에 이 문항이 들어오면 `evaluate-expression` 쏠림(77.0%)이 그대로 보고될 것이다 — 관측 축이라 게이트는 아니다.
