"""RS-X2 특성화 — 수확 대기열 2순위: 옛 오개념 진단·가설 갱신·개입 선택 엔진.

대상(옛 자리 그대로 import한다):
- `whymath_backend/l4/misconception/diagnose.py` — 풀이 글 → 오개념 후보
- `whymath_backend/l4/misconception/hypothesis.py` — 후보 → 가설(감쇠·강화·정리)
- `whymath_backend/l4/misconception/intervene.py` — 가설 → 튜터 되묻기 문장

입력 10개는 명세 카드 `golden/reports_rescue/P2/명세.md` 「특성화 테스트 입력 10개」를 그대로 쓴다.
기대값은 2026-11-19 main `2d12b938`에서 실제로 돌려 나온 출력이다.
"맞는 답"인지는 묻지 않는다 — 바뀌지 않는지만 본다.

옛 모듈은 이 테스트에서만 import한다(골든 패키지는 import하지 않는다 — test_import_budget.py).
세 파일 모두 DB·네트워크·LLM 부작용이 없어 "부작용으로 제외"한 함수는 없다(명세 ③).
모든 입력은 합성 문장이다(실제 학생 발화가 아니다).
"""

from __future__ import annotations

import random

import pytest

from whymath_backend.l4.misconception.diagnose import diagnose
from whymath_backend.l4.misconception.hypothesis import (
    DeactivationReason,
    MisconceptionHypothesis,
    curate_with_reasons,
)
from whymath_backend.l4.misconception.intervene import (
    select_intervention_from_hypotheses,
)

# 입력 1의 풀이 글 — 입력 5가 이 글의 진단 결과를 증거로 다시 쓴다
_TEXT_1 = "(a+b)² = a² + b² 으로 전개했다"

# 패턴 4(거꾸로 확인) 문장 — 입력 6·8이 같은 문장을 낸다
_REVERSE_PROMPT = (
    "(a+b)² = a² + b²이라고 했지. 이 결과가 맞다면, "
    "원래 조건에 어떻게 부합하는지 거꾸로 확인할 수 있을까?"
)


def _h(mid: str, conf: float, turns: int, count: int) -> MisconceptionHypothesis:
    """명세의 `H(id, conf, turns, count)` 줄임 표기를 그대로 옮긴 생성 도우미."""
    return MisconceptionHypothesis(
        misconception_id=mid,
        confidence=conf,
        turns_since_evidence=turns,
        evidence_count=count,
    )


def _summarize(text: str) -> list[tuple[str, float, tuple[str, ...], int, bool, object]]:
    """진단 결과를 비교하기 쉬운 튜플로 줄인다.

    (오개념 id, 확신도, 맞은 신호 원문, 맞은 정규식 수, 정정 귀속 불명 여부, 의미 유사도)
    """
    return [
        (
            m.misconception.id,
            m.confidence,
            tuple(m.matched_signals),
            len(m.matched_regex_signals),
            m.attribution_unclear,
            m.semantic_similarity,
        )
        for m in diagnose(text)
    ]


# ── diagnose: 입력 1·2·3·4·7 ─────────────────────────────────────────────
# (명세 번호, 풀이 글, 기대 요약)
_DIAGNOSE_CASES: list[
    tuple[int, str, list[tuple[str, float, tuple[str, ...], int, bool, object]]]
] = [
    # 1 정상 — 기호 신호 두 개가 부분 문자열로 맞는다
    (1, _TEXT_1, [("distribution-over-power", 1.0, ("(a+b)", "a² + b²"), 0, False, None)]),
    # 2 정상 — 기호 신호는 0개, 수치 정규식 1개로 확신도 1.0
    (2, "(3+4)²=3²+4²=25", [("distribution-over-power", 1.0, (), 1, False, None)]),
    # 3 정상 — 신호 뒤에 "틀렸다" → refuted로 후보가 사라진다
    (3, "(a+b)²=a²+b²라는 풀이는 틀렸다", []),
    # 4 정상 — 신호 앞에 "틀린" → 매칭은 살고 attribution_unclear=True
    # (맞은 신호는 입력 표기가 아니라 카탈로그 원문 표기로 돌아온다)
    (
        4,
        "틀린 풀이: (a+b)²=a²+b²",
        [("distribution-over-power", 1.0, ("(a+b)", "a² + b²"), 0, True, None)],
    ),
    # 7 경계 — 숫자 신호 "0"은 "10" 안에서 맞지 않는다. "분모"·"분수"만 맞아 0.5 두 개
    (
        7,
        "분모가 10인 분수를 약분했어요",
        [
            ("division-by-zero", 0.5, ("분모",), 0, False, None),
            ("fraction-addition-naive", 0.5, ("분수",), 0, False, None),
        ],
    ),
]


@pytest.mark.parametrize(
    ("case_no", "text", "expected"),
    _DIAGNOSE_CASES,
    ids=[f"입력{c[0]}" for c in _DIAGNOSE_CASES],
)
def test_diagnose_characterization(
    case_no: int,
    text: str,
    expected: list[tuple[str, float, tuple[str, ...], int, bool, object]],
) -> None:
    """입력 1·2·3·4·7 — 풀이 글 하나의 진단 결과(순서 포함)를 고정한다."""
    assert _summarize(text) == expected, f"입력 {case_no}"


def test_input9_diagnose_none_raises_type_error() -> None:
    """입력 9(잘못된 입력) — 문자열이 아닌 None은 TypeError로 끝난다(명세의 추측이 실행으로 확인됨)."""
    with pytest.raises(TypeError):
        diagnose(None)  # type: ignore[arg-type]


# ── curate_with_reasons: 입력 5 ──────────────────────────────────────────


def test_input5_curate_reinforce_refute_decay() -> None:
    """입력 5 — 강화·반박·감쇠 세 갈래를 한 번에 밟는다.

    - distribution-over-power: 0.6 → 감쇠 뒤 입력 1 매치(1.0)로 강화 → 1.0, 증거 2회
    - sign-flip-in-inequality: refuted에 들어 있어 REFUTED
    - division-by-zero: 0.11 × 0.5^(1/5) ≈ 0.0958 < 0.1 → DECAYED
    """
    survivors, reasons = curate_with_reasons(
        [
            _h("distribution-over-power", 0.6, 0, 1),
            _h("sign-flip-in-inequality", 0.12, 3, 1),
            _h("division-by-zero", 0.11, 0, 1),
        ],
        diagnose(_TEXT_1),
        turns_elapsed=1,
        refuted=frozenset({"sign-flip-in-inequality"}),
    )
    assert [h.model_dump() for h in survivors] == [
        {
            "misconception_id": "distribution-over-power",
            "confidence": 1.0,
            "turns_since_evidence": 0,
            "evidence_count": 2,
        }
    ]
    assert reasons == {
        "division-by-zero": DeactivationReason.DECAYED,
        "sign-flip-in-inequality": DeactivationReason.REFUTED,
    }


# ── select_intervention_from_hypotheses: 입력 6·8·10 ─────────────────────


def test_input6_epsilon_exploration_seed42() -> None:
    """입력 6 — ε=1.0(항상 탐색)·시드 42에서 차순위 distribution-over-power가 뽑힌다.

    확신도 0.55 → 패턴 4(거꾸로 확인). 증거 3회 → 강도 등급 easier_problem.
    """
    decision = select_intervention_from_hypotheses(
        [
            _h("division-by-zero", 0.65, 0, 1),
            _h("distribution-over-power", 0.55, 0, 3),
            _h("sign-flip-in-inequality", 0.3, 0, 1),
        ],
        epsilon=1.0,
        rng=random.Random(42),
    )
    assert decision is not None
    assert decision.misconception_id == "distribution-over-power"
    assert decision.pattern.value == "reverse_reasoning"
    assert decision.prompt == _REVERSE_PROMPT
    assert decision.escalation_rung is not None
    assert decision.escalation_rung.value == "easier_problem"


def test_input8_threshold_exactly_0_8_is_reverse_reasoning() -> None:
    """입력 8(경계) — 확신도 정확히 0.8은 '초과'가 아니므로 반례(패턴 1)가 아니라 패턴 4다."""
    decision = select_intervention_from_hypotheses(
        [_h("distribution-over-power", 0.8, 0, 1)], rng=None
    )
    assert decision is not None
    assert decision.misconception_id == "distribution-over-power"
    assert decision.pattern.value == "reverse_reasoning"
    assert decision.prompt == _REVERSE_PROMPT
    assert decision.escalation_rung is not None
    assert decision.escalation_rung.value == "none"


def test_input10_unknown_id_returns_none() -> None:
    """입력 10(잘못된 입력) — 카탈로그에 없는 id는 예외 없이 None을 돌려준다."""
    assert select_intervention_from_hypotheses([_h("no-such-id", 0.9, 0, 1)]) is None
