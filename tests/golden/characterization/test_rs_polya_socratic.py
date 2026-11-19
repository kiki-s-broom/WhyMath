"""RS-X3 특성화 — 수확 대기열 3순위: Polya 4단계·소크라테스 질문 선택(LLM 0회).

옛 `whymath_backend.l4.polya`·`l4.socratic`을 옛 자리에서 그대로 불러, 명세
(`golden/reports_rescue/P3/명세.md` ⑥)의 합성 입력 10개에 대한 **지금 출력**을 고정한다.
맞는 답인지는 묻지 않는다 — 바뀌지 않는지만 본다.

- 옛 모듈은 이 테스트에서만 import한다. 골든 코드(`src/backend/golden/`)는 import하지 않는다
  (import-linter 계약 `golden-no-legacy`의 대상은 `golden` 패키지뿐이다).
- `PolyaCoach.coach`는 LLM을 부르므로 넣지 않았다(부작용으로 제외).
- `decide`는 `pack=None`으로만 부른다 — 설정(`get_settings()`)을 읽지 않는 경로다.
- 입력은 전부 합성값이다. 실제 학생 발화는 쓰지 않는다. `MC-SYN-001`도 합성 ID다.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from whymath_backend.l4.misconception.hypothesis import MisconceptionHypothesis
from whymath_backend.l4.models import CostTier, PolyaStage, PolyaState
from whymath_backend.l4.polya import PolyaCoach, base_system_for_grade, should_advance
from whymath_backend.l4.socratic import SocraticCategory, select_category

# ── 1·2·3·7: should_advance(단계 전이) — 반환값 고정 ─────────────────────────────
# (번호, 상태, 발화, 숙련도, 기대 반환값)
_ADVANCE_CASES: list[tuple[int, PolyaState, str, str | None, str]] = [
    (
        1,
        PolyaState(current_stage=PolyaStage.UNDERSTAND),
        "기울기가 2이고 y절편을 구하는 문제예요.",
        None,
        "next",
    ),
    (
        2,
        PolyaState(current_stage=PolyaStage.PLAN),
        "y=ax+b에 점을 대입해서 b를 구하는 방법을 쓸래요",
        "초보",
        "next",
    ),
    (
        3,
        PolyaState(current_stage=PolyaStage.EXECUTE),
        "3 = 2×1 + b\n따라서 b = 1, 답은 y = 2x + 1",
        None,
        "next",
    ),
    # 경계: 정확히 20자(UNDERSTAND 기본 하한과 같다) · 쉼표·마침표 있음
    (
        7,
        PolyaState(current_stage=PolyaStage.UNDERSTAND),
        "기울기는 2이고, y절편은 3이에요.",
        None,
        "next",
    ),
]


@pytest.mark.parametrize(
    ("no", "state", "text", "mastery", "expected"),
    _ADVANCE_CASES,
    ids=[f"입력{c[0]}" for c in _ADVANCE_CASES],
)
def test_should_advance_fixed(
    no: int, state: PolyaState, text: str, mastery: str | None, expected: str
) -> None:
    # 숙련도 인자는 옛 시그니처가 Literal이라 문자열을 그대로 넘긴다
    assert should_advance(state, text, mastery_level=mastery) == expected  # type: ignore[arg-type]


def test_boundary_input7_is_exactly_20_chars() -> None:
    # 7번이 경계 입력이라는 전제 자체를 고정한다(글자 수가 바뀌면 경계가 아니게 된다)
    assert len(_ADVANCE_CASES[3][2]) == 20


# ── 4·5·8: select_category(질문 종류) — 반환 enum 고정 ───────────────────────────
_SYN_HYPOTHESIS = MisconceptionHypothesis(
    misconception_id="MC-SYN-001",
    confidence=0.65,  # 경계: 규칙 ②의 ≥ 0.65
    turns_since_evidence=2,  # 경계: 규칙 ②의 ≤ 2
    evidence_count=1,
)

# (번호, 단계, 전이, 발화, 가설, 직전 카테고리, 기대 카테고리)
_CATEGORY_CASES: list[
    tuple[
        int,
        PolyaStage,
        str,
        str,
        list[MisconceptionHypothesis] | None,
        list[SocraticCategory],
        SocraticCategory,
    ]
] = [
    (
        4,
        PolyaStage.EXECUTE,
        "stay",
        "왜 b를 먼저 구해야 해요?",
        None,
        [],
        SocraticCategory.EVIDENCE,
    ),
    (
        5,
        PolyaStage.UNDERSTAND,
        "stay",
        "음 잘 모르겠어요",
        None,
        [SocraticCategory.CLARIFICATION] * 3,
        SocraticCategory.EVIDENCE,
    ),
    (
        8,
        PolyaStage.PLAN,
        "stay",
        "잘 모르겠어요",
        [_SYN_HYPOTHESIS],
        [],
        SocraticCategory.ASSUMPTION,
    ),
]


@pytest.mark.parametrize(
    ("no", "stage", "transition", "text", "hyps", "recent", "expected"),
    _CATEGORY_CASES,
    ids=[f"입력{c[0]}" for c in _CATEGORY_CASES],
)
def test_select_category_fixed(
    no: int,
    stage: PolyaStage,
    transition: str,
    text: str,
    hyps: list[MisconceptionHypothesis] | None,
    recent: list[SocraticCategory],
    expected: SocraticCategory,
) -> None:
    got = select_category(stage, transition, text, hyps, recent)  # type: ignore[arg-type]
    assert got is expected


# ── 6: PolyaCoach.decide(pack 없음) — 결정 필드 고정 ─────────────────────────────
def test_decide_input6_fixed() -> None:
    d = PolyaCoach().decide(
        "기울기는 2이고 y절편을 구해야 해요.",
        PolyaState(current_stage=PolyaStage.UNDERSTAND, turn_count=1),
        grade=8,
    )
    assert d.polya_stage_to_advance == "next"
    assert d.hint_level == 1
    assert d.base_hint_level == 1
    # decide는 enum이 아니라 .value 문자열을 넣는다(명세 ⑤)
    assert d.socratic_category == "perspective"
    assert d.suggested_actions == ["관점 선택", "전략 후보 나열", "유사 문제 회상"]
    assert d.reveals == "next_concept_to_focus"
    assert d.applied_mastery_level is None
    assert d.recommended_cost_tier is CostTier.LOCAL
    assert "중학생" in d.system  # grade=8 → 중학생 문구
    assert d.prompt.splitlines()[0] == "좋아, 이제 *어떻게 풀지* 계획을 세워보자."


# ── 9·10: 잘못된 입력 — 예외 이름 고정 ──────────────────────────────────────────
_ERROR_CASES: list[tuple[int, Callable[[], object], type[Exception]]] = [
    (9, lambda: should_advance(PolyaState(), None), AttributeError),  # type: ignore[arg-type]
    (10, lambda: base_system_for_grade("8"), TypeError),  # type: ignore[arg-type]
]


@pytest.mark.parametrize(
    ("no", "call", "exc"), _ERROR_CASES, ids=[f"입력{c[0]}" for c in _ERROR_CASES]
)
def test_bad_input_raises_fixed(no: int, call: Callable[[], object], exc: type[Exception]) -> None:
    with pytest.raises(exc):
        call()
