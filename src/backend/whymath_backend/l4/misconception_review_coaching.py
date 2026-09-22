"""L4 오개념 복습 코칭 결정 — 누적 오개념 *가설* 세트 → "그 오개념을 다시 보자" 코칭.

`docs/architecture/04_pedagogy_engine.md`: L4는 *결정* 계층(L3=생성·L5=노출). 본 모듈은
학생의 활성 오개념 가설 세트(`l4.misconception.hypothesis_store.get_active_hypotheses`)를 받아
**"누적 증거가 충분히 강한 오개념이 있으면 그 규칙 자체를 다시 점검하자"**는 결정을 내린다.

**선수 복습과 다른 축이다**(MISC-35 · MISC-02 옵션 B). `recommend_prerequisite_coaching`이
다루는 것은 *결손*("아래 개념이 비어 있다")이고 이 모듈이 다루는 것은 *오적용*("규칙을 잘못
알고 있을 수 있다")이다. 두 축은 원인도 처방도 달라 서로를 대체하지 않는다 — 그래서 선수
코칭 함수의 시그니처·동작을 전혀 건드리지 않고 형제 모듈로 선다(`calibration_coaching.py`와
동형의 세 번째 사례).

**왜 개념이 아니라 오개념 자체를 대상으로 하는가**(MISC-02 취소 사유의 이면): 런타임 오개념
가설은 kebab-id만 들고 있고 거기서 *개념*으로 가는 링크가 이 저장소에 없다 — 개념 링크를 가진
`MisconceptionCatalog`는 PK가 M-id이고 그 ORM이 "kebab-id 체계와 FK가 전혀 없다"고 명문화하며,
사이를 잇는 crosswalk는 `docs/standards/crosswalk_gate_contract.md`가 사람 승인 전용으로 묶어
비워 둔다. 그 링크를 추측으로 메우면 *오귀속 진단*이 되고 그것은 학생이 검증할 수 없다
(CLAUDE.md 우선순위 #1·#2). 이 모듈은 그 홉을 **건너지 않는다** — 오개념을 개념으로 번역하지
않고 오개념 그대로 코칭하므로 링크가 필요 없다.

순수·결정론(DB·async·fetch 0 — 데이터 fetch는 L5 호출자 책임). 선택 로직은 재구현하지 않고
`select_focus`(ε-규칙·#191)를 그대로 쓴다 — 개입 채널(`select_intervention_from_hypotheses`)과
*같은 가설을* 보게 하기 위해서다(별도 판정 경로 신설 금지·이중 진실원천 방지).

노출 계약(CLAUDE.md 우선순위 #2 — 협상 불가):
- **본문 미노출**: 학생 발화에 싣는 카탈로그 필드는 `name_kr`(짧은 주제 라벨)뿐이다.
  `canonical_statement`("(a+b)² = a²+b²" 같은 *학생이 가정한 잘못된 진술*)는 싣지 않는다 —
  그것을 되돌려 말하는 것은 "너는 이렇게 잘못 생각했다"는 단정이 된다.
- **단정 금지**: 가설은 확정 라벨이 아니라 후보다(`MisconceptionHypothesis` docstring). 발화는
  "혹시 …일 수 있다"는 가정형이고, 학생을 비난하거나 우열을 매기지 않으며 정답을 주지 않는다.
- **점수 미노출**: 신뢰도·누적 증거 수는 *결정 입력*일 뿐 발화·근거 문구에 숫자로 나가지 않는다.
"""

from __future__ import annotations

from collections.abc import Sequence

from whymath_backend.l4.metacognitive_trigger import _SOCRATIC_BY_FOCUS, CoachingTrigger
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.l4.misconception.hypothesis import MisconceptionHypothesis, select_focus
from whymath_backend.l4.misconception.intervene import _LOW_CONFIDENCE

# 개입 보류 바닥 — `l4/misconception/intervene.py`가 "신뢰도 < 0.5는 진단 보류(라벨링 회피)"로
# 쓰는 바로 그 상수를 **복제하지 않고 그대로 참조**한다. 같은 가설 세트를 보는 두 채널이 서로
# 다른 바닥을 쓰면 "개입은 보류인데 코칭은 나가는" 어긋남이 생기고, 값을 베껴 두면 한쪽이 바뀔
# 때 조용히 갈라진다 — 참조는 그 드리프트를 구조적으로 없앤다(동결 테스트가 불필요해진다).
_MIN_CONFIDENCE = _LOW_CONFIDENCE


def recommend_misconception_review_coaching(
    hypotheses: Sequence[MisconceptionHypothesis],
    *,
    min_confidence: float = _MIN_CONFIDENCE,
) -> CoachingTrigger | None:
    """활성 오개념 가설 세트에서 "오개념 복습" 코칭 결정 — 순수·결정론(`recommend_*_coaching` 동형).

    `hypotheses`는 confidence **내림차순 정렬**을 가정한다(`get_active_hypotheses`·`curate`가
    보장하는 계약 — 여기서 재정렬하지 않는다).

    None을 돌려주는 경우 3종(전부 *코칭하지 않는 것이 옳은* 상태다):
      - **빈 세트** — 활성 가설 없음. 의심할 것이 없으니 코칭도 없다.
      - **초점 신뢰도 < `min_confidence`** — 가설이 약하다. 오답을 오개념으로 단정하지 않는다는
        제약이 여기서 집행된다(약한 후보로 코칭하면 그것이 곧 오귀속이다).
      - **카탈로그 미해소** — `misconception_id`가 정본 카탈로그에 없다(느슨 id·구 데이터).
        표시할 안전 라벨을 만들 수 없으므로 *날조하지 않고* 보류한다(`intervene.py` 동일 규약).

    초점 선택은 `select_focus(rng=None)` = 최상위 활용이다. ε-탐색을 쓰지 않는 이유: 탐색은
    *개입*(반례 제시 등)으로 가설 세트를 갱신하려는 행동이고, 이 코칭은 그 갱신을 노리지 않는
    복습 권유라 무작위성을 들일 이유가 없다(결정론·재현 가능).
    """
    focus = select_focus(hypotheses)
    if focus is None:
        return None  # 활성 가설 없음 → 의심할 것이 없으니 코칭도 없다.
    if focus.confidence < min_confidence:
        return None  # 가설이 약함 → 보류(오답을 오개념으로 단정 금지·intervene 바닥과 동일).
    misconception = CATALOG_BY_ID.get(focus.misconception_id)
    if misconception is None:
        return None  # 느슨 id → 안전 라벨 없음 → 날조하지 않고 보류.

    # 노출 필드는 `name_kr`(짧은 주제 라벨) 하나뿐 — canonical_statement(학생이 가정한 잘못된
    # 진술)는 싣지 않는다. 라벨 뒤에는 받침 유무와 무관한 '쪽'을 붙여 한국어 조사 안전을 지킨다.
    display = misconception.name_kr

    # 교사용 근거 — *가설*임을 문면에 남긴다("보입니다"·"가능성"). 신뢰도 수치는 싣지 않는다.
    rationale = (
        f"'{display}' 쪽에서 같은 오류가 반복되는 정황이 있습니다"
        f"(누적 가설 — 확정 진단 아님). 새 개념으로 넘어가기 전에 그 규칙이 항상 성립하는지"
        f" 학생이 스스로 확인하게 하는 편이 좋습니다."
    )
    # 다른 의심이 더 있으면 개수만 부가한다(초점만 노출하되 맥락은 알림 — 선수 코칭 동형).
    if len(hypotheses) > 1:
        rationale += f" (다른 의심 {len(hypotheses) - 1}개 더 있음)"

    # 학생용 prompt — 가정형("혹시")·비난 0·정답 제공 0. 반례를 *주지 않고* 학생이 직접 수를
    # 넣어 보게 한다(답 미루기·메타인지 유도). 오개념 진술을 되돌려 말하지 않는다.
    prompt = (
        f"혹시 '{display}' 쪽 규칙이 항상 성립하는지 한 번 같이 확인해 볼까? "
        f"간단한 수를 직접 넣어 보면 스스로 판단할 수 있어."
    )

    return CoachingTrigger(
        focus="misconception_review",
        rationale=rationale,
        prompt=prompt,
        socratic_category=_SOCRATIC_BY_FOCUS["misconception_review"],
    )


__all__ = ["recommend_misconception_review_coaching"]
