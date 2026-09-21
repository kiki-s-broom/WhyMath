"""MISC-20 (b) — 순수 `curate_with_reasons`: 탈락 사유(감쇠/반박/해소/캡절단) 산출.

`curate`는 생존 세트만 돌려줘 "왜 빠졌는지"가 소실됐다 — 그 결과 저장소는 모든 탈락을 같은
`is_active=false`로 눌러 썼고, ⑩ 오개념 해소율이 "학생이 실제로 넘어선 것"과 "조용히 시든 것"을
구분하지 못했다(R2 §2 G4). 이 파일은 순수 계층에서 사유가 결정론적으로 산출됨을 고정한다.
`curate`와의 동치(생존 세트 동일)도 함께 고정한다 — 기존 호출자 회귀 0.
"""

from __future__ import annotations

from whymath_backend.l4.misconception.catalog import CATALOG
from whymath_backend.l4.misconception.hypothesis import (
    DeactivationReason,
    MisconceptionHypothesis,
    curate,
    curate_with_reasons,
)
from whymath_backend.l4.misconception.models import MisconceptionMatch

_MIDS = [m.id for m in CATALOG[:7]]


def _hyp(mid: str, confidence: float) -> MisconceptionHypothesis:
    return MisconceptionHypothesis(
        misconception_id=mid, confidence=confidence, turns_since_evidence=0, evidence_count=1
    )


def _match(mid: str, confidence: float = 1.0) -> MisconceptionMatch:
    entry = next(m for m in CATALOG if m.id == mid)
    return MisconceptionMatch(
        misconception=entry, confidence=confidence, matched_signals=entry.signals[:1]
    )


class TestReasons:
    def test_decayed_when_pruned_below_threshold(self) -> None:
        # 임계(0.1) 바로 위 가설이 1턴 감쇠로 임계 미만 → 감쇠 탈락.
        current = [_hyp(_MIDS[0], 0.11)]
        survivors, reasons = curate_with_reasons(current, [], turns_elapsed=5)
        assert survivors == []
        assert reasons == {_MIDS[0]: DeactivationReason.DECAYED}

    def test_refuted_when_in_refuted_set_without_strong_evidence(self) -> None:
        current = [_hyp(_MIDS[0], 0.9)]
        survivors, reasons = curate_with_reasons(current, [], refuted=frozenset({_MIDS[0]}))
        assert survivors == []
        assert reasons == {_MIDS[0]: DeactivationReason.REFUTED}

    def test_resolved_when_refuted_with_strong_evidence(self) -> None:
        # 해소 = 반박 탈락 ∧ 정정 형태를 직접 보인 강한 반박 증거 실재(학생이 실제로 넘어섬).
        current = [_hyp(_MIDS[0], 0.9)]
        survivors, reasons = curate_with_reasons(
            current, [], refuted=frozenset({_MIDS[0]}), resolved=frozenset({_MIDS[0]})
        )
        assert survivors == []
        assert reasons == {_MIDS[0]: DeactivationReason.RESOLVED}

    def test_resolved_requires_refutation_drop(self) -> None:
        # 강한 증거가 있어도 순지지도가 양이면(반박 집합 밖) 활성 유지 — 사유 없음.
        current = [_hyp(_MIDS[0], 0.9)]
        survivors, reasons = curate_with_reasons(current, [], resolved=frozenset({_MIDS[0]}))
        assert [h.misconception_id for h in survivors] == [_MIDS[0]]
        assert reasons == {}

    def test_capped_when_cut_by_max_active(self) -> None:
        current = [_hyp(m, 0.9 - i * 0.05) for i, m in enumerate(_MIDS[:6])]
        survivors, reasons = curate_with_reasons(current, [], turns_elapsed=0, max_active=5)
        assert len(survivors) == 5
        assert reasons == {_MIDS[5]: DeactivationReason.CAPPED}

    def test_reason_precedence_decay_before_refute_before_cap(self) -> None:
        # 감쇠 탈락은 반박 집합에 있어도 DECAYED(반박 판정 이전에 이미 사라짐), 캡은 마지막.
        current = [_hyp(_MIDS[0], 0.11)] + [
            _hyp(m, 0.9 - i * 0.01) for i, m in enumerate(_MIDS[1:7])
        ]
        survivors, reasons = curate_with_reasons(
            current, [], turns_elapsed=5, refuted=frozenset({_MIDS[0], _MIDS[1]}), max_active=4
        )
        assert reasons[_MIDS[0]] is DeactivationReason.DECAYED
        assert reasons[_MIDS[1]] is DeactivationReason.REFUTED
        # 남은 5개 중 상위 4개 생존 → 최하위 1개 캡 절단.
        assert reasons[_MIDS[6]] is DeactivationReason.CAPPED
        assert len(survivors) == 4

    def test_new_match_not_in_current_has_no_reason_entry(self) -> None:
        # 이번 턴 신규 매치는 기존 행이 없다 — 탈락 사유 대상은 *기존* 가설만.
        survivors, reasons = curate_with_reasons([], [_match(_MIDS[0])])
        assert [h.misconception_id for h in survivors] == [_MIDS[0]]
        assert reasons == {}


class TestEquivalenceWithCurate:
    def test_survivors_identical_to_curate(self) -> None:
        current = [_hyp(m, 0.9 - i * 0.1) for i, m in enumerate(_MIDS[:6])]
        matches = [_match(_MIDS[1]), _match(_MIDS[6])]
        refuted = frozenset({_MIDS[2]})
        expected = curate(current, matches, turns_elapsed=2, refuted=refuted, max_active=4)
        got, _ = curate_with_reasons(
            current, matches, turns_elapsed=2, refuted=refuted, max_active=4
        )
        assert got == expected
