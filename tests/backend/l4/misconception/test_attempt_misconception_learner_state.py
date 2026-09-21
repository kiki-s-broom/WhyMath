"""오답 → 오개념 후보 → **LearnerState 반영**의 누적·감쇠 계약 (EOS-104).

여기서 묻는 것은 탐지가 아니라 *그 다음*이다: 탐지된 후보가 학습자 상태에 **어떻게 남고,
증거가 끊기면 어떻게 사라지는가**.

왜 감쇠가 계약인가: 오개념은 영속 낙인이 아니다. 한 번 잡힌 오개념이 증거 없이도 계속 활성으로
남으면 학생은 "한 번 틀린 것"으로 영원히 분류된다. Persona C 시나리오가 요구하는 것이 정확히
그 반대 — 재관측되지 않으면 confidence가 **내려가야** 한다.

구성: 순수 축(DB 없음)은 후보→매치 변환과 누적·감쇠 곡선을 직접 실행해 검증하고, 영속 왕복은
실 PG 통합테스트가 맡는다(PG 없으면 skip — `test_hypothesis_store.py` 선례 동형).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.l4.misconception.hypothesis import (
    _PRUNE_THRESHOLD,
    MisconceptionHypothesis,
    update_hypotheses,
)
from whymath_backend.l4.misconception.hypothesis_store import apply_candidates
from whymath_backend.l4.misconception.models import MisconceptionMatch
from whymath_backend.schema.assessment_evidence import MisconceptionCandidate

_MID = "distribution-over-power"


def _candidate(mid: str = _MID, *, confidence: float = 0.9, gate_passed: bool = True) -> Any:
    return MisconceptionCandidate(
        misconception_id=mid, confidence=confidence, gate_passed=gate_passed
    )


def _as_matches(*candidates: MisconceptionCandidate) -> list[MisconceptionMatch]:
    """`apply_candidates`가 내부에서 하는 변환과 **같은 규칙**을 순수하게 재현.

    재현이 아니라 호출로 검증하고 싶지만 그쪽은 DB 세션을 요구한다 — 그래서 변환 규칙 자체는
    아래 `test_apply_candidates_converts_and_filters`가 실제 함수를 불러 동결하고, 이 헬퍼는
    누적·감쇠 곡선을 그리는 데만 쓴다.
    """
    return [
        MisconceptionMatch(
            misconception=CATALOG_BY_ID[c.misconception_id],
            confidence=c.confidence,
            attribution_unclear=c.attribution_unclear,
        )
        for c in candidates
        if c.gate_passed and c.misconception_id in CATALOG_BY_ID
    ]


# ── ① 누적 — 같은 오개념이 다시 관측되면 confidence가 오른다 ──────────────────────
def test_repeated_evidence_accumulates_confidence() -> None:
    """두 번째 관측이 신뢰를 *올린다* — 1회성 실수와 지속 오개념을 구별하는 축."""
    first = update_hypotheses([], _as_matches(_candidate()), turns_elapsed=0)
    assert [h.misconception_id for h in first] == [_MID]
    second = update_hypotheses(first, _as_matches(_candidate()), turns_elapsed=1)
    assert second[0].confidence > first[0].confidence
    assert second[0].evidence_count == first[0].evidence_count + 1


# ── ② 감쇠 — 재관측이 없으면 confidence가 내려간다(Persona C) ─────────────────────
def test_confidence_decays_when_not_re_evidenced() -> None:
    """후보 0건으로 훑은 회차는 기존 가설을 **감쇠**시킨다 — 낙인 방지의 기계 축.

    이것이 "후보가 비어도 `apply_candidates`를 부른다"는 서빙 경로 결정의 근거다. 안 부르면
    신뢰가 영원히 그 자리에 멈춘다.
    """
    seeded = update_hypotheses([], _as_matches(_candidate()), turns_elapsed=0)
    before = seeded[0].confidence
    after = update_hypotheses(seeded, [], turns_elapsed=1)
    assert after, "한 턴 만에 가지치기되면 감쇠 곡선을 볼 수 없다(픽스처 전제 붕괴)"
    assert after[0].confidence < before
    assert after[0].turns_since_evidence == seeded[0].turns_since_evidence + 1


def test_sustained_absence_eventually_prunes() -> None:
    """증거가 계속 없으면 임계 아래로 떨어져 활성 세트에서 빠진다 — 감쇠의 종착."""
    hypotheses = update_hypotheses([], _as_matches(_candidate()), turns_elapsed=0)
    for _ in range(40):
        hypotheses = update_hypotheses(hypotheses, [], turns_elapsed=1)
        if not hypotheses:
            break
    assert hypotheses == [], "40턴 무증거에도 활성으로 남았다 — 감쇠가 종착하지 않는다"


def test_decay_is_the_only_downward_force_here() -> None:
    """변별력 주입: 감쇠를 없애면(`turns_elapsed=0`) 신뢰가 **안 내려간다**.

    이 대조군이 없으면 위 두 테스트는 "어쨌든 숫자가 줄었다"만 말한다 — 줄어든 원인이 감쇠임을
    보이려면 감쇠를 끈 실행이 초록이어야 한다.
    """
    seeded = update_hypotheses([], _as_matches(_candidate()), turns_elapsed=0)
    unchanged = update_hypotheses(seeded, [], turns_elapsed=0)
    assert unchanged[0].confidence == pytest.approx(seeded[0].confidence)


# ── ③ 변환·필터 — 게이트 미통과·미상 id는 상태를 바꾸지 못한다 ────────────────────
class _CapturingSession:
    """`apply_candidates`가 넘긴 매치를 가로채는 최소 세션 대역.

    `apply_matches`를 monkeypatch해 잡으므로 실제 SQL은 돌지 않는다 — 여기서 검증하려는 것은
    영속(그쪽은 실 PG 통합이 본다)이 아니라 **후보→매치 변환 규칙**이다.
    """


@pytest.mark.asyncio
async def test_apply_candidates_converts_and_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    """게이트 통과 + 카탈로그 실재 후보만 매치로 승격된다."""
    captured: dict[str, Any] = {}

    async def _fake_apply_matches(
        _session: Any, user_id: uuid.UUID, matches: Any, *, turns_elapsed: int = 1
    ) -> list[MisconceptionHypothesis]:
        captured["matches"] = list(matches)
        captured["turns_elapsed"] = turns_elapsed
        return []

    monkeypatch.setattr(
        "whymath_backend.l4.misconception.hypothesis_store.apply_matches", _fake_apply_matches
    )
    await apply_candidates(
        _CapturingSession(),  # type: ignore[arg-type]
        uuid.uuid4(),
        [
            _candidate(),  # 통과
            _candidate("존재하지-않는-오개념"),  # 카탈로그 미상 → 탈락
            _candidate(gate_passed=False),  # 게이트 미통과 → 탈락
        ],
    )
    assert [m.misconception.id for m in captured["matches"]] == [_MID]


@pytest.mark.asyncio
async def test_empty_candidates_still_advances_the_decay_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """후보 0건이어도 호출은 유효하다 — 그 호출이 곧 감쇠 1회다."""
    captured: dict[str, Any] = {}

    async def _fake_apply_matches(
        _session: Any, user_id: uuid.UUID, matches: Any, *, turns_elapsed: int = 1
    ) -> list[MisconceptionHypothesis]:
        captured["matches"] = list(matches)
        captured["turns_elapsed"] = turns_elapsed
        return []

    monkeypatch.setattr(
        "whymath_backend.l4.misconception.hypothesis_store.apply_matches", _fake_apply_matches
    )
    await apply_candidates(_CapturingSession(), uuid.uuid4(), [])  # type: ignore[arg-type]
    assert captured["matches"] == []
    assert captured["turns_elapsed"] >= 1, "감쇠가 0턴이면 '훑었지만 없었다'가 상태를 못 바꾼다"


def test_prune_threshold_is_above_zero() -> None:
    """가지치기 임계가 0이면 감쇠는 영원히 끝나지 않는다(위 종착 테스트의 전제)."""
    assert _PRUNE_THRESHOLD > 0.0
