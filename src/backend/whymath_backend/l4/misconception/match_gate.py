"""오개념 매칭 *품질 게이트* — WH-1 1단계 슬라이스 1 `match_misconception` 도구화(§3.3).

설계안 §3.3 "품질 게이트"(R6 대응·CLAUDE.md "확실하지 않으면 모른다"·억지 매칭 금지)의 *순수
후처리* 좌석이다. 매칭 *알고리즘*(`diagnose`/regex/의미 매처/`combine_diagnoses`)은 전혀 건드리지
않고, 이미 만들어진 후보 리스트에 두 게이트를 *덧씌운다*:

  ① **top-1 신뢰도 < floor면 "후보 없음"** — 억지 매칭 금지. top-1조차 floor(기본 0.65) 미만이면
     노이즈로 가설을 세우는 셈이라 *후보 전체를 비우고* `no_confident_match=True`로 표시한다.
     (약한 부분매칭 0.5짜리 하나로 COUNTEREXAMPLE 개입 발화하는 라이브 결함류 차단.)
  ② **OCR confidence < ocr_threshold면 `low_quality` 플래그** — OCR 산출물이 입력일 때 인식
     신뢰도가 낮으면(기본 0.8 미만) 매칭은 *유지하되* 오염 가능성을 플래그한다. 하류 LLM이 학생에게
     *재확인 질문*을 유도해 오염된 매칭으로 단정하지 않게 한다. `ocr_confidence`가 None이면(OCR
     입력이 아님) 플래그하지 않는다 — 본 슬라이스에서 요청에 OCR confidence 필드가 없으면 이 분기는
     *dormant*(인터페이스만 마련·실제 미적용)다.
  ③ **top-1의 정정 귀속이 불명하면 `attribution_unclear` 플래그** (MISC-28) — ②와 *같은 좌석*
     이다: 매칭은 유지하되 확신 진단을 보류하고 하류가 재확인을 유도하게 한다. 차이는 신호의
     출처뿐이다(② = 입력 OCR 품질 · ③ = L4 매처의 귀속 판정). 판정 기준을 **top-1**로 두는 것은
     게이트 ①과 같은 근거다 — 학생에게 실제로 발화되는 것이 top-1이므로, 그것이 깨끗하면
     확신은 깨끗하다.

**신뢰도 축 = `confidence`(진단 신뢰)**: 게이트 ①은 `MisconceptionMatch.confidence`(substring 신호
비율 1.0/0.5·정규식 가산)를 기준으로 판단한다. `semantic_similarity`(표면 코사인 근접도)는 *다른
축*(models.py docstring: "진단 신뢰가 아니라 표면 근접도")이라 floor 판정에 쓰지 않는다 — 따라서
semantic-only 후보(confidence가 코사인 클램프라 보통 낮음)는 floor에서 걸러진다. 두 축을 섞지 않는
것은 `combine_diagnoses`의 "재정렬 금지" 불변과 동일한 정신이다.

**순수·결정론**: provider·index·DB·LLM을 *모른다*. 입력 매치 리스트와 스칼라 임계만으로 결정되며
입력 원소를 변형하지 않는다(통과분은 같은 객체를 그대로 재배치). 단위테스트가
`MisconceptionMatch`를 직접 조립해 hermetic하게 검증한다.

**정직 스코프**: 이건 WH-1 1단계 *2도구 중 첫째*(`match_misconception` 품질 게이트)다. 둘째
`verify_step`의 3-state(정답/오답/검증불가) verify는 *후속 슬라이스*이며 본 모듈은 손대지 않는다.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from whymath_backend.l4.misconception.models import MisconceptionMatch

# 설계 §3.3 고정 임계 — 파라미터화하되 기본값은 설계값 준수.
_DEFAULT_CONFIDENCE_FLOOR = 0.65  # top-1 신뢰도 하한(이 미만이면 후보 없음·억지 매칭 금지).
_DEFAULT_OCR_THRESHOLD = 0.8  # OCR 인식 신뢰도 하한(이 미만이면 low_quality 플래그).


class MatchGateResult(BaseModel):
    """`apply_match_quality_gate`의 결과 — 게이트 통과 매칭 + 게이트 플래그 2종.

    `matches`는 게이트 ①을 통과한 후보만 담는다(top-1<floor면 *빈 리스트*). 플래그는 하류
    (가설·intervention·LLM 프롬프트)가 품질 상태를 알 수 있게 노출하나, 본 슬라이스에서 HTTP
    응답 *노출 필드 신설*은 범위 밖이다(게이트 적용=하류 차단까지만).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    matches: list[MisconceptionMatch] = Field(
        default_factory=list,
        description=(
            "게이트 ①(top-1 신뢰도 floor)을 통과한 오개념 후보. top-1<floor(또는 입력 빈 "
            "리스트)면 **빈 리스트**(억지 매칭 금지). 통과 시 입력 순서·원소 그대로(변형 0)."
        ),
    )
    no_confident_match: bool = Field(
        default=False,
        description=(
            "top-1 신뢰도가 floor 미만이라 후보를 *비웠는지* 여부. True면 `matches`는 빈 "
            "리스트 — 확실한 후보가 없으니 가설을 세우지 않는다(CLAUDE.md '모르면 모른다')."
        ),
    )
    low_quality: bool = Field(
        default=False,
        description=(
            "입력이 OCR 산출물이고 OCR confidence가 ocr_threshold 미만일 때 True. 매칭은 "
            "*유지*하되 오염 가능성 플래그 — 하류 LLM이 학생에게 재확인 질문을 유도하게 한다. "
            "`ocr_confidence`가 None(OCR 입력 아님)이면 항상 False."
        ),
    )
    attribution_unclear: bool = Field(
        default=False,
        description=(
            "MISC-28 게이트 ③ — 게이트 ①을 통과한 **top-1**이 `attribution_unclear`면 True. "
            "학생 풀이에 정정 어구가 있으나 그것이 그 오개념을 가리키는지 판정할 수 없다는 뜻이며, "
            "매칭은 *유지*하되 확신 진단을 보류한다(`low_quality`와 같은 좌석·다른 출처). 게이트 "
            "①이 후보를 비웠으면(top-1 없음) 항상 False — 보류할 판정 자체가 없다."
        ),
    )


def apply_match_quality_gate(
    matches: Sequence[MisconceptionMatch],
    *,
    ocr_confidence: float | None = None,
    confidence_floor: float = _DEFAULT_CONFIDENCE_FLOOR,
    ocr_threshold: float = _DEFAULT_OCR_THRESHOLD,
) -> MatchGateResult:
    """오개념 후보에 §3.3 품질 게이트 2종을 적용 — 순수·결정론.

    인자:
      - `matches`: 이미 정렬된(confidence 내림차순) 후보 시퀀스. `diagnose`/`combine_diagnoses`
        결과를 그대로 받는다 — 이 함수는 *재정렬하지 않고* `matches[0]`을 top-1으로 신뢰한다.
      - `ocr_confidence`: OCR 산출물일 때 인식 신뢰도(0~1). None이면 OCR 입력이 아님(게이트 ②
        비활성).
      - `confidence_floor`: top-1 신뢰도 하한(기본 0.65·설계값).
      - `ocr_threshold`: OCR 신뢰도 하한(기본 0.8·설계값).

    게이트 ① (억지 매칭 금지): `matches`가 비었거나 `matches[0].confidence < confidence_floor`면
    → `matches=[]`·`no_confident_match=True`. 즉 top-1조차 floor 미만이면 *후보 전체를 비운다*
    (노이즈로 가설 금지). 통과하면 입력 매치를 *그대로*(변형 0) 싣고 `no_confident_match=False`.

    **신뢰도 축**: 판정 기준은 `confidence`(진단 신뢰)다 — substring 신호 비율(1.0/0.5)·정규식
    가산. `semantic_similarity`(표면 근접도)는 *별도 축*이라 floor 판정에 쓰지 않으므로,
    confidence가 낮은 semantic-only 후보는 floor에서 자연히 걸러진다.

    게이트 ② (OCR low_quality): `ocr_confidence is not None and ocr_confidence < ocr_threshold`면
    → `low_quality=True`. 매칭은 *유지*(게이트 ①의 결과를 그대로)하되 플래그만 세운다 — 하류가
    재확인을 유도하게 한다. `ocr_confidence`가 None이면 `low_quality=False`(OCR 입력 아님).

    게이트 ③ (MISC-28 정정 귀속): 게이트 ①을 통과한 top-1이 `attribution_unclear`면
    → `attribution_unclear=True`. ②와 같은 처분(매칭 유지 + 보류 플래그)이며, 게이트 ①이 후보를
    비웠으면 항상 False다. 이 게이트는 인자를 받지 않는다 — 판정은 L4 매처(`diagnose`)가 이미
    내렸고 여기서는 top-1 축으로 *승격*만 한다.
    """
    # 게이트 ① — top-1 신뢰도 floor. 비었거나 top-1<floor면 후보 전체를 비운다(억지 매칭 금지).
    if not matches or matches[0].confidence < confidence_floor:
        gated: list[MisconceptionMatch] = []
        no_confident_match = True
    else:
        gated = list(matches)  # 통과분 — 원소 변형 0(같은 객체 그대로 복사 배치).
        no_confident_match = False

    # 게이트 ② — OCR 산출물이고 인식 신뢰도가 임계 미만이면 low_quality 플래그(매칭은 유지).
    low_quality = ocr_confidence is not None and ocr_confidence < ocr_threshold

    # 게이트 ③(MISC-28) — top-1의 정정 귀속이 불명이면 플래그(매칭은 유지). 게이트 ①이 후보를
    # 비운 경우 `gated`가 비어 있으므로 자연히 False다(보류할 판정 자체가 없음).
    attribution_unclear = bool(gated) and gated[0].attribution_unclear

    return MatchGateResult(
        matches=gated,
        no_confident_match=no_confident_match,
        low_quality=low_quality,
        attribution_unclear=attribution_unclear,
    )


__all__ = [
    "MatchGateResult",
    "apply_match_quality_gate",
]
