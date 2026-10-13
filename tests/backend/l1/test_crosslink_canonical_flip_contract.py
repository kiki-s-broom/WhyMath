"""적재 후 canonical 시뮬 **계약**(HARN-216 ① + ④-계약) — 순수 함수, DB 0.

**정본 사고** (2026-10-07 `G-crosslink-live-drift-disposition` 추가 검토): 적재기 `populate`는
`ON CONFLICT DO UPDATE` 업서트만 하고 코퍼스에 없는 라이브 행을 지우지 못한다. 그래서 코퍼스 68건을
그대로 다시 적재해도 오귀속 4행이 살아남고, 그중 2건은 신뢰도가 더 높아 정답을 이기며(wrong_winner)
2건은 동률이라 canonical이 미선정이 된다(tie) — 적재가 오류를 고치는 것처럼 보이면서 고치지 못한다.

이 파일은 **판정(계약)** 만 고정한다. 적재 CLI가 그 판정을 실제로 경유해 쓰기를 막는지(집행)는
`test_crosslink_canonical_flip_enforcement.py`가 별항으로 고정한다 — 계약이 맞아도 아무도 부르지 않으면
보호가 아니다(CLAUDE.md "정본화를 집행으로 착각한 완료 선언 금지").
"""

from __future__ import annotations

import pytest

from whymath_backend.l1.misconception.crosslink_resolve import (
    ResolvedLink,
    select_canonical,
    simulate_load_canonical,
)

_D = "직접매핑"


def _link(mis_id: str, conf: float | None, link_type: str = _D) -> ResolvedLink:
    return ResolvedLink(mis_id=mis_id, link_type=link_type, confidence=conf)


def _one(live: list[ResolvedLink], corpus: list[ResolvedLink], kebab: str = "k"):  # type: ignore[no-untyped-def]
    (verdict,) = simulate_load_canonical({kebab: live}, {kebab: corpus})
    return verdict


# ── 2026-10-07 실측 4건 — 실제 kebab·M-id·신뢰도 그대로 ──────────────────────────
class TestIncidentCases:
    def test_angle_sum_non_triangle_wrong_winner(self) -> None:
        v = _one([_link("M0863", 0.95)], [_link("M0493", 0.85)], "angle-sum-non-triangle")
        assert v.verdict == "wrong_winner"
        assert v.corpus.canonical_mis_id == "M0493" and v.corpus_confidence == 0.85
        assert v.after_load.canonical_mis_id == "M0863"
        assert [r.mis_id for r in v.rivals] == ["M0863"]

    def test_period_of_scaled_sine_wrong_winner(self) -> None:
        v = _one([_link("M0862", 0.95)], [_link("M0152", 0.85)], "period-of-scaled-sine")
        assert v.verdict == "wrong_winner"
        assert v.after_load.canonical_mis_id == "M0862"

    def test_division_by_zero_tie(self) -> None:
        v = _one([_link("M0146", 0.85)], [_link("M0003", 0.85)], "division-by-zero")
        assert v.verdict == "tie"
        assert v.corpus.canonical_mis_id == "M0003"
        assert v.after_load.canonical_mis_id is None and v.after_load.reason == "tie"

    def test_circle_radius_squared_tie(self) -> None:
        v = _one([_link("M0630", 0.93)], [_link("M0848", 0.93)], "circle-radius-squared")
        assert v.verdict == "tie"
        assert v.after_load.ambiguous is True


# ── 대조군 — 이것들이 ok가 아니면 판정이 모든 적재를 막는 고장이다 ───────────────
class TestControls:
    def test_no_live_rows_is_ok(self) -> None:
        assert _one([], [_link("M1", 0.9)]).verdict == "ok"

    def test_live_row_with_same_triplet_is_overwritten_by_upsert(self) -> None:
        """라이브가 코퍼스와 같은 (kebab, mis_id, link_type)이면 업서트가 코퍼스 값으로 덮는다 — 경쟁 아님."""
        v = _one([_link("M1", 0.99)], [_link("M1", 0.85)])
        assert v.verdict == "ok"
        assert v.rivals == (), "덮어써질 행은 잔존 행이 아니다"

    def test_lower_confidence_survivor_does_not_flip(self) -> None:
        v = _one([_link("M9", 0.60)], [_link("M1", 0.85)])
        assert v.verdict == "ok"
        assert [r.mis_id for r in v.rivals] == ["M9"], "잔존 행은 보고하되 뒤집지는 않는다"

    def test_non_direct_or_null_confidence_survivors_never_compete(self) -> None:
        live = [_link("M7", 0.99, "부분매핑"), _link("M8", None)]
        v = _one(live, [_link("M1", 0.85)])
        assert v.verdict == "ok" and v.rivals == ()

    def test_kebab_absent_from_the_corpus_is_not_judged(self) -> None:
        """이 적재가 건드리지 않는 kebab의 라이브 행은 판정 대상이 아니다."""
        result = simulate_load_canonical(
            {"other": [_link("M9", 0.99)], "k": []}, {"k": [_link("M1", 0.9)]}
        )
        assert [v.kebab_id for v in result] == ["k"]

    def test_corpus_own_tie_is_not_a_flip(self) -> None:
        """코퍼스 자신이 동률이면 라이브가 바꾼 게 없다 — 이 검사의 질문은 '코퍼스 의도와 다른가'다."""
        v = _one([_link("M9", 0.5)], [_link("M1", 0.9), _link("M2", 0.9)])
        assert v.verdict == "ok"
        assert v.corpus.reason == "tie"

    def test_duplicate_triplet_in_the_corpus_folds_last_wins_like_the_loader(self) -> None:
        """적재기 `populate`는 같은 트리플을 마지막 우선으로 접는다 — 시뮬이 다르면 가짜 동률이 생긴다."""
        v = _one([], [_link("M1", 0.5), _link("M1", 0.9), _link("M2", 0.7)])
        assert v.verdict == "ok"
        assert v.corpus.canonical_mis_id == "M1" and v.corpus_confidence == 0.9


# ── 열거·정렬·경계 ──────────────────────────────────────────────────────────
class TestEnumeration:
    def test_returns_every_incoming_kebab_sorted_with_mixed_verdicts(self) -> None:
        live = {
            "b-wrong": [_link("X", 0.95)],
            "a-tie": [_link("Y", 0.85)],
            "c-ok": [_link("Z", 0.1)],
        }
        incoming = {
            "c-ok": [_link("C", 0.9)],
            "b-wrong": [_link("B", 0.85)],
            "a-tie": [_link("A", 0.85)],
        }
        result = simulate_load_canonical(live, incoming)
        assert [(v.kebab_id, v.verdict) for v in result] == [
            ("a-tie", "tie"),
            ("b-wrong", "wrong_winner"),
            ("c-ok", "ok"),
        ]

    def test_rivals_are_sorted_by_confidence_descending(self) -> None:
        v = _one([_link("M3", 0.7), _link("M2", 0.95), _link("M4", 0.95)], [_link("M1", 0.5)])
        assert [r.mis_id for r in v.rivals] == ["M2", "M4", "M3"]

    def test_three_way_tie_with_corpus_tie_is_unchanged(self) -> None:
        """코퍼스가 이미 동률(M1·M2 0.9)이고 라이브가 같은 신뢰도로 합류해도 (None, tie)는 그대로 — 뒤집힘 아님."""
        v = _one([_link("M3", 0.9)], [_link("M1", 0.9), _link("M2", 0.9)])
        assert v.verdict == "ok"

    def test_survivor_wins_when_the_corpus_has_no_direct_link(self) -> None:
        """코퍼스에 직접매핑이 없고(no_direct) 라이브 직접매핑이 선정되면 코퍼스 의도(미선정)와 다르다."""
        v = _one([_link("M9", 0.9)], [_link("M1", 0.9, "부분매핑")])
        assert v.verdict == "wrong_winner"
        assert v.corpus.reason == "no_direct" and v.corpus_confidence is None

    def test_empty_incoming_yields_nothing(self) -> None:
        assert simulate_load_canonical({"k": [_link("M9", 0.9)]}, {}) == []


@pytest.mark.parametrize(
    ("live", "corpus"),
    [
        ([_link("M9", 0.95)], [_link("M1", 0.85)]),
        ([_link("M9", 0.85)], [_link("M1", 0.85)]),
        ([], [_link("M1", 0.85)]),
    ],
)
def test_after_load_equals_select_canonical_of_the_merged_set(
    live: list[ResolvedLink], corpus: list[ResolvedLink]
) -> None:
    """시뮬의 적재 후 선택은 정책 단일 진실 원천(`select_canonical`)을 그대로 쓴다 — 정책 사본이 없다."""
    v = _one(live, corpus)
    assert v.after_load == select_canonical([*corpus, *live])
