# 골든 벤치마크 계약 v1 — 판정기를 판정한다 (EOS-60)

> **지위**: `EOS-60-golden-benchmark-qa-confusion-matrix` 산출물 · 코드 정본 =
> `src/backend/whymath_backend/harness/golden_benchmark.py`(승격·동결) +
> `src/backend/whymath_backend/ops/qa_confusion_matrix.py`(혼동행렬 판정).
> 입력 생산자(EOS-137): `src/backend/whymath_backend/harness/qa_item_verdict.py`(문항별 predictions) ·
> 문항 판정 좌석 = `harness/qa_pipeline.judge_item`.
> 상위 계약: `docs/standards/eos_verification_design_v1.md` §6(내용 KPI 동결) ·
> `docs/standards/superhuman_verification_standard.md` §4.5(재채점 금지).
> 갭 근거: `docs/reviews/eos_validation_n1_n10_gap_review_2026-08-30.md` §3.7(N8).

---

## §1. 왜 필요한가 — QA 엔진은 자기 FN율을 모른다

```
현재:   생성 → QA 엔진 → PASS  →  (그대로 신뢰)
필요:   골든 200건(as-found 라벨) → QA 엔진 → 혼동행렬
                                              ├─ Precision
                                              ├─ Recall
                                              └─ FN율  ← 무관용 관리 대상
```

`harness/qa_pipeline`이 9축을 조립해 PASS/FAIL을 내지만, **그 PASS가 얼마나 믿을 만한지 잰 적이
없다**. 교육 콘텐츠에서 결정적인 실패는 **False Negative(틀린 콘텐츠를 정상이라 판정)** 이고,
EOS-51 §6이 동결한 내용 KPI 6종 중 **4종이 골든 라벨에 의존**한다(§5 결선표).

G2(10/25) 기준선의 "자동검증 ≥70%"는 자동검증이 *맞는지* 모르면 의미 없는 숫자다.

`EOS-64`(앵커 E2E 야간 골든)와 **중복이 아니다** — EOS-64는 콘텐츠를 판정하는 *승격 경로*이고,
이 계약은 **판정기를 판정하는 벤치마크 셋**이다. 의존 방향은 `EOS-64` → `EOS-60`.

---

## §2. 골든 셋 구축 — 별도 라벨링 캠페인 금지

**골든 라벨은 새로 만들지 않는다.** EOS-54 검수 타이머 이벤트의 `verdict`·`failure_code`가 곧
사람 라벨이므로, 필요한 것은 "검수 결과 중 무엇을 승격하고 언제 동결하는가"의 규약뿐이다
(추가 인간 시간 ≈ 0 — 검수 185 CU 예산의 부산물).

| 항목 | 값 |
|---|---|
| 규모 목표 | 앵커 6개 × **30~35건** ≈ 200건 (`ANCHOR_QUOTA_MIN/MAX`) |
| 입력 | 검수 타이머 이벤트 JSONL(EOS-54) + `cu_slug→anchor_id` 매핑 |
| 라벨 어휘 | `defective` / `clean` (as-found 기준·폐쇄 2값) |
| 결함 코드 | `GenerationFailureCode` F1~F8(EOS-51 §4 동결 enum 소비 — 신규 어휘 금지) |
| 과목 축 | `subject_id`(기본 `math`) — Validation의 Math 비종속 좌석 |

앵커 매핑이 없는 CU는 **승격하지 않는다**(앵커별 쿼터·앵커별 FN 보고가 성립하지 않으므로).
제외 건수는 리포트에 명시된다 — 조용한 제외 금지.

---

## §3. as-found 라벨 무결성 — fail-closed (핵심 계약)

골든 라벨은 **QA 엔진이 실제로 본 입력**, 즉 *검수 전(as-found)* 상태를 말해야 한다.
손질 후 승인을 `clean`으로 승격하면 **원래 결함이던 입력이 정상으로 라벨링되어 FN율이
과소평가**된다 — 골든이 자기 목적을 훼손한다.

| verdict | 승격 | 근거(`AsFoundBasis`) |
|---|---|---|
| `rejected` | ✅ `defective` | `rejected_failure_code` — 반려는 정의상 손질 전 판정이고 F1~F8이 결함을 명시 |
| `approved` + ⓐ 검수 전 불변 스냅샷 | ✅ 스냅샷이 말하는 라벨 | `pre_review_snapshot` |
| `approved` + ⓑ EOS-62 edit-aware verdict(계약 착지 **이후** 검수분) | ✅ `clean` | `edit_aware_verdict` |
| `approved_with_edit`(EOS-62 착지 후) | ✅ `defective` | `edit_aware_verdict` |
| `approved` (ⓐ·ⓑ 둘 다 없음) | ❌ **제외 + 건수 명시** | 모호 — 미측정 ≠ 정상 |

**ⓑ에 시각 경계를 요구하는 이유**: EOS-62 ④가 소급 재분류를 금지하므로 계약 착지 *이전*의
`approved` 행은 어휘가 확장돼도 영구 모호다. 경계 없이 어휘 존재만으로 승격하면 그 과거 행이
조용히 clean으로 섞인다. 그래서 `--edit-aware-since`를 **명시 인자로 요구**하고, 없으면 전부
제외한다(fail-closed). **골든 표본은 계약 착지 이후 검수분에서 뽑는 것이 정본 경로다.**

ⓑ의 착지 여부는 상수로 박지 않는다 — `edit_aware_verdict_available()`이 `ReviewVerdict` 어휘를
**실측**한다. EOS-62가 착지하면 이 경로가 자동으로 열리고, 착지 전에는 아무도 손대지 않아도
fail-closed가 유지된다(선언과 실체의 드리프트 차단).

**clean 라벨이 0건인 상태는 정상이다** — ⓐ·ⓑ 없이 반려분만 승격되면 clean 축이 비고,
Precision·오검출률은 **미산출**로 보고된다(0%로 찍지 않는다).

---

## §4. 과적합 방지 — 재채점 금지 (S2-11의 골든 적용)

초인간 검증 표준 §4.5("결함 교정 후 같은 표본 재채점 금지·신규 독립 표본 재추출")를 골든에도
건다. 집행 수단 2개:

1. **동결 기록** — 골든 셋에 `golden_version`·`rotation`·`frozen_at`·`digest`(내용 sha256)를
   박는다. digest는 판정 축(slug·subject·anchor·label·failure_code·basis)만의 함수이므로
   **라벨 손편집은 로드 시점에 터진다**(부기 메타 변경은 digest를 바꾸지 않는다).
2. **평가 원장** — `qa_confusion_matrix --ledger --engine-revision`. 평가 1회마다
   (digest, engine_revision)을 append하고, **같은 골든을 다른 엔진 리비전으로 재채점**하면
   exit 1로 막는다. 같은 리비전 재실행은 재현성(S4) 확인이므로 허용한다.
   원장이 **깨져 있으면 통과가 아니라 측정 실패(exit 1)** 다 — 손상된 줄이 하필 이전 평가
   기록이면 빈 이력을 보고 재채점을 허용하게 되어, 금지 규율이 그 증거가 손상된 바로 그
   순간에 무력화된다(#928 리뷰 P1).

### 재추출의 독립성은 회전이 아니라 **제외**에서 온다

`rotation`만 올리는 재추출은 **작동하지 않는다**(#928 리뷰 P1 실측). 앵커 후보가 쿼터 이하면
— 그 구간이 하필 우리 목표 규모 **30~35 = 기본 쿼터 35** 다 — 회전은 선택 *순서*만 바꾸고
전건이 그대로 선택되므로 같은 셋·같은 digest가 나오고, 그러면 교정 후 재판정이 원장에
"재채점"으로 **영구 차단**된다. 규약이 스스로를 막는 상태다.

그래서 독립성의 원천은 **이전 골든의 명시적 제외**다:

```bash
python -m whymath_backend.harness.golden_benchmark \
    --events review_timer.jsonl --anchor-map anchors.jsonl \
    --rotation 1 --exclude-golden data/corpus/golden_benchmark_v1/golden.json \
    --golden-version v2 --out data/corpus/golden_benchmark_v2/golden.json
```

- `--exclude-golden`(반복 가능)의 slug는 후보에서 **빠진다** → 새 셋은 이전과 서로소다.
- `rotation > 0`인데 제외 집합이 없으면 **거부**한다(fail-closed — 독립을 확인할 근거가 없다).
- 제외 후 후보가 소진되면 **비운다**. 이전 표본을 재사용해 쿼터를 채우지 않으며, 승격 0건은
  exit 1(측정 실패)로 드러난다. 재판정하려면 **검수를 더 쌓아 후보를 늘려야 한다** — 이것이
  S2-11이 실제로 요구하는 비용이고, 규약이 그 비용을 숨기지 않는다.
- 회전은 제외 위에서 순서를 재배열하는 보조 축이다. 해시는 새로 만들지 않았다 —
  `reviewer_sample_package.rotation_key`(S2-11)를 그대로 재사용한다.

원장을 주지 않으면 재채점 금지는 **미집행**이며, 리포트가 그 사실을 상시 명기한다
(정본화 ≠ 집행). 제외 집합이 없을 때도 리포트가 "초판만 가능"함을 자인한다.

---

## §5. 내용 KPI 4종의 소비 지점 (집행 별항)

코드 정본 = `ops/qa_confusion_matrix.CONTENT_KPI_CONSUMERS`(표와 실체의 정합은
`tests/backend/ops/test_qa_confusion_matrix.py`가 기계로 동결 — 착지 표기는 import 가능해야
하고, 미착지분은 좌석 태스크가 백로그에 실재해야 한다).

| 내용 KPI (EOS-51 §6) | 골든 라벨 축 | 채점기 | 좌석 |
|---|---|---|---|
| 수학적 오류율 ≤0.5% (독립 모델 심판 전수) | `defective ∧ F1·F2` | `ops/qa_confusion_matrix`(착지) | `EOS-60` |
| 교육과정 정합률 ≥92% (블라인드 역매핑) | `defective ∧ F4` | **미착지** | `EOS-61` |
| 오개념 op-code 라벨 정확도 ≥85% | `defective ∧ F6` | **미착지** | `MISC-07` |
| 풀이 비약 지적률 ≤10% (LLM 심판 κ≥0.5) | `defective ∧ F3` | **미착지**(저장소 κ 구현 0건) | `EOS-61` |

리포트는 **라벨 축별 정답지 건수**를 함께 찍는다 — 골든이 있어도 F4 라벨이 0건이면 교육과정
정합률 KPI는 여전히 계산 근거가 없다는 사실이 그 자리에서 보인다.

---

## §6. "작동한 비율" 원칙 — 측정 실패는 통과가 아니다

| 사태 | 처리 |
|---|---|
| 골든 0건 · 승격 0건 | **exit 1**(측정 실패). "통과 0건"이 아니다 |
| 예측 0건 · 골든과 겹치는 예측 0건 | **exit 1** |
| 골든 항목에 QA 판정이 없음 | **pass로 간주 금지** — `미평가`로 분리 카운트(FN 위장 차단) |
| 평가 원장 파싱 실패 1건 이상 | **exit 1** — 재채점 이력이 손상된 상태에서는 금지를 판정할 수 없다 |
| 제외 후 후보 소진(승격 0건) | **exit 1** — 이전 표본 재사용으로 쿼터를 채우지 않는다 |
| 입력 파싱 실패 1건 이상 | **exit 1** — 유실된 행이 정답지·혼동행렬을 바꿨을 수 있다(부분 입력 판정 금지) |
| clean/defective 라벨 0건으로 분모 없음 | **미산출**로 표기. 그 지표에 게이트가 걸리면 통과가 아니라 exit 1 |
| 적재율 | 골든 중 QA 판정 동반 비율을 **상시 보고**(Wilson 하한 병기) |

판정 형식은 불변이다 — **Wilson 단측 경계**만 쓴다(점추정 금지). "높을수록 좋은"
recall·precision은 하한, "낮을수록 좋은" FN율·오검출률은 상한을 본다.

---

## §7. 사용

```bash
# ① 검수 이벤트 → 골든 승격·동결
python -m whymath_backend.harness.golden_benchmark \
    --events review_timer.jsonl --anchor-map anchors.jsonl \
    --golden-version v1 --rotation 0 \
    --out data/corpus/golden_benchmark_v1/golden.json --report golden_promotion.md

# ② QA 엔진 문항별 판정 — 코퍼스·검수 큐 JSONL(경로 지정) → predictions (EOS-137)
python -m whymath_backend.harness.qa_item_verdict \
    --input canary_review_queue.jsonl --golden data/corpus/golden_benchmark_v1/golden.json \
    --out qa_verdicts.jsonl --undetermined qa_undetermined.jsonl

# ③ 골든 대비 QA 엔진 혼동행렬(재채점 금지 집행 포함)
python -m whymath_backend.ops.qa_confusion_matrix \
    --golden data/corpus/golden_benchmark_v1/golden.json \
    --predictions qa_verdicts.jsonl \
    --engine-revision "$(git rev-parse --short HEAD)" \
    --ledger data/corpus/golden_benchmark_v1/eval_ledger.jsonl \
    --json qa_confusion.json
```

`--predictions`는 QA 판정 JSONL이다: `{"cu_slug": ..., "qa_verdict": "pass"|"fail", "predictor": ...}`
(`passed`/`qa_pass` 불리언 형식도 수용). 어휘 밖 판정은 pass로 관용하지 않고 파싱 실패로 센다.
`predictor`(판정기 식별자)는 선택이지만 `--ledger`를 쓰려면 필수다(§9.3). ②의 판정 불가 문항은
predictions에 없고 `qa_undetermined.jsonl`에 사유와 함께 있다 — 혼동행렬은 그 문항을 `미평가`로 센다.

---

## §8. 한계 명기 (정직)

1. **표본 200건은 FN율의 자릿수만 잡는다** — EOS-51 §7-3이 인정한 검출력 한계 안이다.
   0.5% 수준의 정밀 추정은 못 한다. Wilson 상한을 보는 이유이기도 하다.
2. **골든은 검수가 쌓이는 동안에만 싸게 만들어진다** — 나중에 만들면 as-found 상태가 복원
   불가다(N5·N7·N9의 논지가 N8에도 적용). 승격은 검수와 **같이** 돌려야 한다.
3. **과거 `approved` 행은 영구 모호다** — 소급 재분류 금지(EOS-62 ④)의 귀결. 초기 골든이
   defective 편중(clean 0건)일 수 있고, 그때 Precision 축은 미산출로 남는다.
4. **QA 판정 입력은 파일 기반이다** — 현행 검수·감사 흐름이 JSONL이라 그 관례를 따른다.
   DB 직접 조회 모드는 미구현(정직한 공백 — 소비처가 생기면 확장).
5. **문항 좌석은 수학 기계 판정이 중심이다(EOS-137)** — 필수 성분이 정답 재검산이고 나머지는
   조건 DSL·출처 필드·금칙어/PII다. 즉 F1·F2(기계형) 결함은 볼 수 있지만 **F3(풀이 비약)·F4(성취기준
   이탈)·F6(오개념 오연결)·F7(문장 수준) 결함은 좌석이 거의 보지 못한다** — 그 결함류의 FN은 좌석의
   알려진 사각이고, `fn_by_failure_code`가 그 분포를 드러낸다. §5 결선표의 미착지 채점기가 그 자리다.

---

## §9. 표류 시계열과 판정기 식별 — 설계 판정 (EOS-137 ③④)

> 판정 기준: main `6c880b67`(이 판정을 쓴 브랜치의 분기점). 동결 테스트 =
> `tests/backend/ops/test_qa_confusion_matrix.py::TestDriftSeriesDesign`·`::TestPredictorIdentity` ·
> `tests/backend/harness/test_golden_benchmark.py::TestEvaluationLedger` ·
> `tests/backend/harness/test_qa_item_verdict.py`.

### §9.1 질문

"모델 표류 감지"는 같은 잣대로 시간에 따라 여러 번 재는 것이다. 그런데 §4는 **같은 골든(digest)을
다른 엔진 리비전으로 재면 exit 1**로 막는다. 둘 중 무엇을 양보하는가, 그리고 원장 행에 지표 값이
없는 현 구조(digest·리비전·시각만)로 시계열을 읽을 수 있는가.

### §9.2 판정 — 회전별 독립 표본이 정본, 원장 행이 그 점의 값을 싣는다

두 선택지는 대안이 아니라 **서로 다른 결손을 메운다**. 둘 다 채택한다.

| 축 | 결정 | 이유 |
|---|---|---|
| 점의 **독립성** | 회전(rotation)마다 `--exclude-golden`으로 만든 **새 독립 표본에 점 1개** | 같은 표본에 리비전별 점을 쌓으면, 그 사이의 엔진 교정이 바로 그 표본에 맞춰졌을 수 있다. 그러면 "FN율이 줄었다"가 표류(엔진이 나아짐)인지 과적합(표본을 외움)인지 **구분 불가**다 — S2-11이 금지한 바로 그 상황이다. 표류 감지는 재채점 금지를 풀 이유가 아니다 |
| 점의 **값** | 원장 행에 `predictor`와 `metrics`(혼동행렬 4칸·평가 건수·골든 건수·적재율 하한·recall/precision 하한·FN율/오검출률 상한·신뢰수준)를 싣는다 | 종전 행에는 digest·리비전·시각만 있어, 시계열을 그리려면 과거 회차의 골든·예측 파일을 다시 찾아 재실행해야 했다 — 파일이 Kiki 머신에만 있으면 사실상 재현 불가다. 원장 한 파일로 시계열이 읽혀야 한다 |
| 재채점 금지 | **불변** — 같은 digest × 다른 리비전은 계속 exit 1이고, 막힌 시도는 원장에 점을 남기지 않는다 | 위 첫 줄 |

**대가(숨기지 않는다)**: 점 사이의 차이에는 *엔진 변화*와 *표본 교체*가 섞인다. 점 하나는 30~35건
× 6앵커 규모의 새 표본이므로, 두 점의 차이는 반드시 **Wilson 구간끼리** 비교한다(점추정 비교 금지 —
§6). 표본 잡음보다 작은 표류는 이 설계로 보이지 않는다(§8-1과 같은 검출력 한계). 그리고 점 하나를
찍는 비용은 **검수를 더 쌓아 후보를 늘리는 것**이다(§4 "재추출의 독립성은 제외에서 온다").

### §9.3 판정기 식별 — "어느 판정기의 FN율인가"

예측 행의 `predictor`가 판정기를 가리킨다. 계열(식별자의 `/`·`+` 앞)은
`ops/qa_confusion_matrix.PREDICTOR_KINDS`가 닫힌 표로 정한다.

| 계열 | 종류 | 뜻 |
|---|---|---|
| `qa_pipeline.item_verdict` | `qa_engine` | QA 엔진 문항 좌석 — **정본**. 생산자 `harness/qa_item_verdict`. fuzz를 켜면 `+fuzz` |
| `generation_gate.outcome` | `generation_gate_proxy` | 생성 파이프라인 outcome(`accepted_stored`·`needs_review`) 대용 — **채택하지 않음** |

- **대용안을 채택하지 않는 이유**: 대용 예측이 재는 것은 QA 엔진이 아니라 **생성 게이트**다. 게다가
  코퍼스에 수록된 문항은 정의상 전부 생성 게이트를 통과했으므로(`accepted_stored`), 수록 문항만으로
  만든 골든에서 대용 FN율은 "수록 문항 중 사람이 결함으로 본 비율"로 퇴화한다 — 판정기의 성능이
  아니라 표본의 결함률이다. 정본 좌석(`judge_item`)이 생겼으므로 대용이 필요하지 않다.
- 그래도 대용 예측이 **들어오면 표시한다** — 리포트 머리에 "이 FN율은 생성 게이트의 FN율이다"를
  굵게 적고, JSON `predictor.kind`와 원장 행 `predictor`에 그대로 남는다.
- **섞으면 판정하지 않는다** — 한 예측 파일에 판정기가 2종 이상이면 `MixedPredictor`로 파싱 실패와
  같이 exit 1이다. 섞인 혼동행렬은 어느 판정기의 것도 아니다.
- **원장은 판정기를 요구한다** — `--ledger`인데 예측에 단일 `predictor`가 없으면 exit 1(원장에 아무것도
  쓰지 않음). 원장 없이 재는 것은 여전히 가능하되 리포트가 "미선언"을 자인한다(옛 형식 예측 호환).

### §9.4 문항 좌석의 구성과 판정 불가

`judge_item`은 집계 QA 엔진 9축 중 **문항으로 투영 가능한 축**의 판정 함수를 문항 1건에 그대로
적용한다(새 판정 로직 0 — 축 2는 집계와 문항이 같은 함수를 돈다). 투영 불가 축과 사유는
`qa_pipeline.ITEM_NON_PROJECTABLE_AXES`에 있고, 대응 전수는 테스트가 동결한다.

| 성분 | 출처 | 필수 |
|---|---|---|
| `answer_reverify` | `corpus_reverify._reverify_one` — S6 상시 재검산(집계 9축 밖의 기계 검증 스택) | ✅ |
| `condition_dsl` | 축 2 `equivalence_canonicalize` | |
| `record_provenance_fields` | 축 6 `content_provenance`의 레코드 레벨 검사 | |
| `banned_words_pii` | 축 8 `banned_words_pii` | |

판정: 성분 하나라도 fail → **fail** · 아니면 판정 불가 성분이 있거나 필수 성분이 pass가 아니면
**판정 불가** · 그 밖에만 **pass**. 판정 불가 문항은 predictions에 넣지 않는다 — pass로 채우면 FN이
위장되고 fail로 채우면 검출률이 부풀려진다. 어댑터가 사유 범주별로 따로 센다.
