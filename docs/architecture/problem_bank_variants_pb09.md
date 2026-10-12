# 문제은행 변형 3종 발화 (PB-09) — 난이도 계열 · 조건변형 · 역문제

> 판정 기준: 작업 브랜치 `claude/busy-hamilton-llj064` HEAD `ec1f9dc7` (2026-10-08 실측).
> 정본 근거: `problem_bank_gap_review_r3.md` §3 G5 · §5-④. 구현: `l3/equivalent/variants.py` ·
> `harness/problem_corpus_variants.py`.

## 1. 발화 논증 (acceptance ①)

1차 §5-④가 변형 확대를 유보하며 건 조건은 둘이다. **D4** 재고 부족이 실측될 것, **D8** 변형을 *기록할
자리*(계보)가 생길 것. 둘 다 성립한다 — 아래는 R3 문서의 수치를 베낀 것이 아니라 이번에 다시 잰 값이다.

| 조건 | 근거 | 실측 |
|---|---|---|
| D4 | `ARCH-18` | 대장 `status: done`. 재고 부족(난이도 사다리 부재·유형 0커버)은 R2 §0-③이 실측 |
| D8 | `S4-14`·`S4-18` | 둘 다 `done`. 코퍼스 `relations` 행 **2,128건**(`유사` 1,707 · `변형` 421) — R3가 적은 1,024건에서 늘었다 |
| 판정 잠금 해소 | `G-s4-14-variant-identity` | `backlog/gates.yaml`에 부재(0건). `S4-21`(`done`)이 선행 해소 |
| 기록 좌석의 미사용 | `generation_type` | `problem_bank_*` 전 코퍼스 **14,034건이 전량 `FULLY_GENERATED`** — `VARIANT_*` 3종은 실사용 0건 |

정정 한 가지: R3·태스크 문구가 계보 소비처를 `api/me.py:1807`이라 적었으나 실제 소비 지점은
`l2/recommendation_policy.py:817`(`load_sibling_ids`)이다. 위치가 옮겨졌을 뿐 소비 사실은 같다.

## 2. 설계

신규 생성기·신규 enum·신규 필드는 0이다. 코퍼스 행에서 근·선택을 복원해 기존 `_Skeleton` 조립 경로로
자식을 낳고, 기존 수용 게이트 · 구조 signature dedup · (좌석 주입 시) 임베딩 dedup에 그대로 태운다.
`problem_corpus_batch`의 바이트 동일 재생성 봉인은 건드리지 않고 `problem_corpus_rephrase`처럼 코퍼스를
읽기 전용 입력으로 받는 별도 단계로 뒀다.

방향은 항상 **부모(코퍼스에 있는 문항) → 자식(새 문항)** 이다.

| 모드 | 이동 | 자식이 하는 일 | `relation_type` | `generation_type` |
|---|---|---|---|---|
| 난이도 계열 | `ladder_harder` | 정답 근을 고정하고 *다른 근*을 정수 → 반정수로 | `심화` | `VARIANT_STRUCTURE` |
| 난이도 계열 | `ladder_easier` | 정답 근을 고정하고 *다른 유리근*을 가장 가까운 정수로 | `선수` | `VARIANT_STRUCTURE` |
| 조건변형 | `condition_flip` | 같은 방정식, 반대쪽 근 선택 | `변형` | `VARIANT_CONTEXT` |
| 조건변형 | `condition_sign` | 같은 방정식, 부호 조건("양수인 근") | `변형` | `VARIANT_CONTEXT` |
| 역문제 | `inverse` | 두 근에서 방정식을 복원해 `b + c`를 묻는다 | `대조` | `VARIANT_STRUCTURE` |

- **"기초" 관계**는 `RelationType`에 없다. 방향을 뒤집은 `선수`("자식이 부모의 선수")로 같은 사실을 표현한다.
  관계 타입을 늘리지 않은 이유는 anti-explosion(5~8개 제한)이다.
- **같은 뿌리**: 난이도 계열은 정답 근을 고정한다. 같은 답을 다른 길로 보게 하는 것이 변형의 목적이다
  (플레이북 Part 0 — 문제은행이 아니라 사고 추적기). 심화 이동과 쉬운 쪽 이동은 서로의 역이다
  (`test_harder_then_easier_round_trips_to_the_original_pair`).
- **난이도 값**은 새로 추정하지 않는다. `difficulty.estimate_difficulty` 공식이 *값을 바꾸지 못하는* 이동
  (정답 근이 이미 유리수 등)은 만들지 않고 skip 사유로 센다. 조건변형·역문제는 공식이 모르는 축이라
  **부모 난이도를 계승**하고 가산하지 않는다. 실응답 보정은 `PB-10` 소관이다.
- **유사도(`similarity_score`)는 `None`**이다. 근거 없는 수치를 계보에 날조하지 않는다
  (`rephrase`의 1.0은 수치 내용이 완전히 같다는 실측 사실이라 별개).
- 자식마다 `provenance.parent_problem_id`와 `transformation_pipeline`(부모 slug·이동)을 싣는다 —
  `problem_relation` 행이 유실돼도 출처가 복원된다.

### 검산 계약 (acceptance ④)

게이트 Tier1은 "답이 조건을 만족하는가"만 보고 *유일성*은 보지 않는다. 그래서 부호 조건(정확히 한 근만
고르는가)과 역문제(해가 유일한가)는 낳을 때 SymPy 정확값으로 직접 확인하고, 성립하지 않으면 자식을
만들지 않는다. 연립 조건 · 부등식 조건(`x > 0`)은 기존 `verify_answer`가 이미 검산한다.

## 3. 작동한 비율 (acceptance ⑥, 실측)

`python -m whymath_backend.harness.problem_corpus_variants --out <경로>` — 부모 `generated_v0` 619행,
시드 signature는 `problem_bank_*` 전 코퍼스. LLM 0 · DB 0 · 두 번 실행 바이트 동일.

부모 자격: 619행 중 **126행**만 부모가 된다(`QUAD-EQ` 아님 435 · 무리근 50 · 중근 8).

| 이동 | 시도 | skip | 파생 | 저장 | 작동률 | 파생 후 탈락 |
|---|---|---|---|---|---|---|
| `ladder_harder` | 126 | 49 | 77 | 75 | 59.5% | 구조 중복 2 |
| `ladder_easier` | 126 | 103 | 23 | 11 | 8.7% | 구조 중복 10 · 변형 키 중복 2 |
| `condition_flip` | 126 | 0 | 126 | 94 | 74.6% | 구조 중복 32 |
| `condition_sign` | 126 | 58 | 68 | 66 | 52.4% | 변형 키 중복 2 |
| `inverse` | 126 | 49 | 77 | 70 | 55.6% | 변형 키 중복 7 |
| **합계** | **630** | 259 | 371 | **316** | **50.2%** | — |

모드별 저장: 난이도 계열 86 · 조건변형 160 · 역문제 70. 계보 좌석 실사용: `심화` 75 · `선수` 11 · `변형` 160 ·
`대조` 70, `generation_type`은 `VARIANT_CONTEXT` 160 · `VARIANT_STRUCTURE` 156이며 `FULLY_GENERATED` 0건.

수용 게이트에서 거부된 자식은 0건이다. 이 숫자만으로는 게이트가 일한다는 증거가 못 되므로(모든 입력에서
초록인 검사는 검증이 아니다) 대조군을 뒀다 — 정답·근 선택·부호·역문제 계수를 망가뜨린 자식은 거부된다
(`TestGateDiscrimination`). 테스트 결함 주입 11종은 전건 검출됐다.

skip 사유 상위: `ladder_easier`는 부모가 유리근이 아닌 경우 77, 정답 근이 이미 유리수인 경우 26이다. 쉬운
계열이 구조적으로 얇다는 뜻이며 숨기지 않고 낮은 작동률(8.7%)로 드러낸다.

종료 코드: 요청된 모드 중 저장 0건이 있으면 **exit 1**. 부착됐으나 무작동인 모드가 정상 종료로 보이지
않게 한다.

## 4. 이번 범위에서 하지 않은 것 (정직한 한계)

- **코퍼스를 커밋하지 않았다.** `populate.py`·QA·CAT 후보 선정이 `data/corpus/problem_bank_*/problems.jsonl`을
  전수 글롭하므로, 검수·노출 게이트 분석 없이 산출물을 두면 미검수 문항이 후보로 흘러갈 수 있다.
  그래서 `--out`은 필수이며 기본 경로가 없다. 편입은 별도 결정(후속 태스크)이다.
- 무리근 · 중근 부모, 선두계수 ≠ 1 부모의 역문제는 v1 범위 밖이다(skip/거부 사유로 센다).
- 난이도 계열은 **한 걸음씩**이다. 3단 이상 사다리는 파생 문항을 다시 부모로 삼는 후속 회차가 필요하다.
- 임베딩 dedup 좌석은 주입 가능하고 테스트로 배선을 확인했지만, 기본 CLI는 배치 CLI처럼 hermetic이라 끈다.
  켠 실행은 Phaiakes9 소관이다.
- 학생 노출 정책 · 역문제 채점 루브릭 · 다중 풀이는 스코프 밖(acceptance ⑦).

## 5. 이번에 발견해 분리한 것

1. **CAT 형제 필터가 관계 유형을 구분하지 않는다.** `load_sibling_ids`는 `problem_relation`을 유형 무관하게
   양방향으로 모아 "형제"로 취급한다. `sibling_filter=exclude`(기본 OFF)에서는 직전 오답 문항의 `선수`(쉬운
   계열)까지 후보에서 빠지고, `include`에서는 `심화`까지 가중 우대된다. Polya의 "더 쉬운 관련 문제를 먼저"와
   정면으로 어긋날 수 있다. 계보가 코퍼스에 편입되기 **전에** 정해야 하는 노출 정책이라 후속 태스크로 분리한다.
2. **이미 코퍼스에 있는 구조와 겹친 자식**(`ladder_harder` 2 · `ladder_easier` 10 · `condition_flip` 32)은
   새로 낳을 필요 없이 *기존 문항 사이에 계보만 거는* 후보다. 신규 콘텐츠 0으로 계열을 늘릴 수 있다.
3. **코퍼스 편입** — 노출 게이트 분석 · 검수 상태 · 유형 태깅(`problem_type_codes`) · `persona_fit` 정합.
