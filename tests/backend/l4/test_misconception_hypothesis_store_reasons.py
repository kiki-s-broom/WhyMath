"""MISC-20 (b) — 저장소가 탈락 사유를 `deactivated_reason`으로 영속한다(집행 지점).

순수 `curate_with_reasons`가 사유를 내도 저장소가 쓰지 않으면 컬럼은 장식이다. 이 파일은
`curate_hypothesis`·`apply_matches`가 탈락 행에 사유를 쓰고, 재활성화 시 사유를 비우며,
사유를 모르는 경로(`persist_hypotheses` — 하네스 in-memory 결과 세트)는 NULL(사유 미상)로
정직하게 두는 것을 고정한다. hermetic — 저장소의 질의 헬퍼를 모듈 네임스페이스에서 대체하고
기존 행은 ORM 객체로 주입한다(실 DB 0).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import BindParameter
from sqlalchemy.sql.dml import Update

from whymath_backend.db.models.misconception_hypothesis import MisconceptionHypothesisRecord
from whymath_backend.l4.misconception import hypothesis_store as store
from whymath_backend.l4.misconception.catalog import CATALOG
from whymath_backend.l4.misconception.hypothesis import DeactivationReason, MisconceptionHypothesis
from whymath_backend.l4.misconception.models import MisconceptionMatch

_UID = uuid.uuid4()
_MIDS = [m.id for m in CATALOG[:7]]


class _Scalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)

    def all(self) -> list[Any]:
        return list(self._rows)


class _Session:
    """기존 행 SELECT에 주입 행을 돌려주고, 비활성화 UPDATE 문을 *구문 그대로* 캡처한다.

    비활성화는 ORM 속성 변경이 아니라 `update()` 문(벌크 UPDATE)이라 가짜 세션이 행을 자동으로
    바꾸지 않는다 — 그래서 문에 실린 `values`와 `IN` 목록을 직접 읽는다(SQL 방언 컴파일 없이
    SQLAlchemy 코어 구조를 그대로 관측 — 실 DB 0·문자열 매칭 0).
    """

    def __init__(self, rows: list[MisconceptionHypothesisRecord]) -> None:
        self.rows = rows
        self.added: list[Any] = []
        self.flushes = 0
        self.updates: list[tuple[frozenset[str], str | None]] = []

    async def execute(self, stmt: Any) -> _Result:
        if isinstance(stmt, Update):
            # values는 BindParameter로 감싸여 온다 — 리터럴만 벗겨 읽는다.
            values = {
                c.name: (v.value if isinstance(v, BindParameter) else v)
                for c, v in stmt._values.items()  # noqa: SLF001
            }
            mids: set[str] = set()
            for crit in stmt._where_criteria:  # noqa: SLF001
                for element in crit.get_children():
                    if isinstance(element, BindParameter) and element.expanding:
                        mids.update(element.value)
            reason = values.get("deactivated_reason")
            self.updates.append((frozenset(mids), reason))
            return _Result([])
        return _Result(self.rows)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushes += 1

    def reason_for(self, mid: str) -> str | None:
        """이 mid를 비활성화한 UPDATE에 실린 사유(없으면 AssertionError — 비활성화 자체가 없음)."""
        hits = [reason for mids, reason in self.updates if mid in mids]
        assert hits, f"{mid}를 비활성화하는 UPDATE가 없다 — updates={self.updates}"
        assert len(hits) == 1, f"{mid}가 여러 UPDATE에 실렸다 — updates={self.updates}"
        return hits[0]

    def deactivated_mids(self) -> set[str]:
        return {mid for mids, _ in self.updates for mid in mids}


def _record(mid: str, confidence: float, *, active: bool = True) -> MisconceptionHypothesisRecord:
    return MisconceptionHypothesisRecord(
        user_id=_UID,
        misconception_id=mid,
        confidence=confidence,
        turns_since_evidence=0,
        evidence_count=1,
        is_active=active,
        deactivated_reason=None if active else DeactivationReason.CAPPED.value,
    )


def _hyp(mid: str, confidence: float) -> MisconceptionHypothesis:
    return MisconceptionHypothesis(
        misconception_id=mid, confidence=confidence, turns_since_evidence=0, evidence_count=1
    )


def _match(mid: str) -> MisconceptionMatch:
    entry = next(m for m in CATALOG if m.id == mid)
    return MisconceptionMatch(
        misconception=entry, confidence=1.0, matched_signals=entry.signals[:1]
    )


def _patch_readers(
    monkeypatch: pytest.MonkeyPatch,
    *,
    current: list[MisconceptionHypothesis],
    support: dict[str, float],
    strong: set[str],
) -> None:
    async def _get_active(session: Any, user_id: Any) -> list[MisconceptionHypothesis]:
        return list(current)

    async def _net_support(session: Any, student_id: Any, mid: str) -> float:
        return support.get(mid, 0.0)

    async def _strong(session: Any, student_id: Any, mids: Any) -> set[str]:
        return {m for m in mids if m in strong}

    monkeypatch.setattr(store, "get_active_hypotheses", _get_active)
    monkeypatch.setattr(store, "net_support", _net_support)
    monkeypatch.setattr(store, "strong_refutation_mids", _strong)
    monkeypatch.setattr(store.get_settings(), "misconception_crosslink_mode", "off", raising=False)


class TestCurateHypothesisWritesReasons:
    async def test_refuted_and_resolved_reasons_persisted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rows = [_record(_MIDS[0], 0.9), _record(_MIDS[1], 0.8)]
        _patch_readers(
            monkeypatch,
            current=[_hyp(_MIDS[0], 0.9), _hyp(_MIDS[1], 0.8)],
            support={_MIDS[0]: -1.0, _MIDS[1]: -0.5},
            strong={_MIDS[0]},  # 0번만 정정 형태를 직접 보인 강한 반박 증거 보유
        )
        session = _Session(rows)
        active = await store.curate_hypothesis(session, student_id=_UID, matches=[])  # type: ignore[arg-type]
        assert active == []
        assert session.reason_for(_MIDS[0]) == DeactivationReason.RESOLVED.value
        assert session.reason_for(_MIDS[1]) == DeactivationReason.REFUTED.value
        assert session.flushes == 1

    async def test_capped_reason_persisted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        current = [_hyp(m, 0.9 - i * 0.05) for i, m in enumerate(_MIDS[:6])]
        rows = [_record(m, 0.9 - i * 0.05) for i, m in enumerate(_MIDS[:6])]
        _patch_readers(monkeypatch, current=current, support={}, strong=set())
        session = _Session(rows)
        active = await store.curate_hypothesis(
            session, student_id=_UID, matches=[], turns_elapsed=0, max_active=5  # type: ignore[arg-type]
        )
        assert len(active) == 5
        assert session.deactivated_mids() == {_MIDS[5]}
        assert session.reason_for(_MIDS[5]) == DeactivationReason.CAPPED.value

    async def test_reactivation_clears_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 이전에 캡 절단된 비활성 행이 새 매치로 살아나면 사유를 비운다(옛 사유 잔존 금지).
        rows = [_record(_MIDS[0], 0.3, active=False)]
        _patch_readers(monkeypatch, current=[], support={}, strong=set())
        session = _Session(rows)
        active = await store.curate_hypothesis(
            session, student_id=_UID, matches=[_match(_MIDS[0])]  # type: ignore[arg-type]
        )
        assert [h.misconception_id for h in active] == [_MIDS[0]]
        assert rows[0].is_active is True
        assert rows[0].deactivated_reason is None


class TestApplyMatchesWritesDecayed:
    async def test_decay_prune_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        rows = [_record(_MIDS[0], 0.11)]
        _patch_readers(monkeypatch, current=[_hyp(_MIDS[0], 0.11)], support={}, strong=set())
        session = _Session(rows)
        active = await store.apply_matches(session, _UID, [], turns_elapsed=5)  # type: ignore[arg-type]
        assert active == []
        assert session.reason_for(_MIDS[0]) == DeactivationReason.DECAYED.value


class TestPersistHypothesesUnknownReason:
    async def test_harness_result_set_prune_leaves_reason_null(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 하네스 in-memory 결과 세트는 탈락 사유를 싣지 않는다 — NULL(사유 미상)·날조 0.
        rows = [_record(_MIDS[0], 0.9)]
        session = _Session(rows)
        monkeypatch.setattr(
            store.get_settings(), "misconception_crosslink_mode", "off", raising=False
        )
        await store.persist_hypotheses(session, _UID, [])  # type: ignore[arg-type]
        assert session.deactivated_mids() == {_MIDS[0]}
        assert session.reason_for(_MIDS[0]) is None  # 사유 미상 — 날조 0


class TestResolvedProvenanceNotWeight:
    """MISC-20 (Codex P1 수용) — 해소 판정은 **출처 표식**만 본다. 가중치는 출처가 아니다.

    초판은 `polarity=-1 AND coalesce(weight, 1.0) >= 0.75`로 가중치에서 출처를 추론했고 두 곳에서
    뚫렸다: ①`weight`는 nullable이라 `coalesce(..., 1.0)`이 **NULL(미평가=모름)을 최강 신호로**
    접었다 ②하네스 `LogEvidenceAction.weight`는 **LLM이 지정**한다 — 숫자 하나로 "이 학생은
    오개념을 넘어섰다"가 영구 기록될 수 있었다. 그래서 판정 축을 `provenance` 컬럼으로 옮겼다.
    """

    async def test_predicate_filters_on_provenance_and_polarity(self) -> None:
        """술어 실측 — polarity=-1 **과** provenance 표식을 함께 걸고, 가중치는 보지 않는다."""
        from whymath_backend.db.models.evidence_link import EvidenceLink
        from whymath_backend.l4.misconception.evidence_store import (
            CORRECT_FORM_DEMONSTRATED,
            strong_refutation_mids,
        )

        captured: list[Any] = []

        class _Capturing:
            async def execute(self, stmt: Any) -> _Result:
                captured.append(stmt)
                return _Result([])

        out = await strong_refutation_mids(_Capturing(), _UID, [_MIDS[0]])  # type: ignore[arg-type]
        assert out == set()
        compiled = str(captured[0].compile(compile_kwargs={"literal_binds": True}))
        # 값까지 본다 — 토큰 존재만 보면 부호가 +1로 뒤집혀도 통과하는데, 그 상태는 *지지* 증거를
        # 반박으로 읽어 강하게 지지된 가설을 "해소"로 계상한다(해소율이 반대로 부풀려진다).
        assert "polarity = -1" in compiled, f"반박(-1) 필터가 아니다: {compiled}"
        assert CORRECT_FORM_DEMONSTRATED in compiled, f"출처 표식 필터가 없다: {compiled}"
        assert EvidenceLink.__tablename__ in compiled
        # **가중치는 판정에서 빠져야 한다** — 남아 있으면 LLM 지정 숫자가 다시 해소를 만든다.
        assert "weight" not in compiled, f"가중치가 아직 판정에 쓰인다: {compiled}"

    async def test_empty_input_makes_no_query(self) -> None:
        from whymath_backend.l4.misconception.evidence_store import strong_refutation_mids

        class _Boom:
            async def execute(self, stmt: Any) -> None:
                raise AssertionError("빈 입력에는 쿼리하지 않아야 한다(불필요 왕복 0).")

        assert await strong_refutation_mids(_Boom(), _UID, []) == set()  # type: ignore[arg-type]

    async def test_coach_stamps_provenance_only_for_correct_form(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """집행 지점 — coach의 반박 적재가 *정정 형태 실측*일 때만 표식을 남긴다.

        표식을 남기는 곳이 여기 하나뿐이므로, 여기서 조건이 느슨해지면 판정 축 전체가 무너진다.
        """
        from whymath_backend.api import coach as coach_mod
        from whymath_backend.l4.misconception.evidence_store import CORRECT_FORM_DEMONSTRATED

        calls: list[dict[str, Any]] = []

        async def _fake_log(session: Any, **kw: Any) -> None:
            calls.append(kw)

        monkeypatch.setattr(coach_mod, "log_evidence", _fake_log)
        # 정정 형태가 실재하는 풀이 / 막연한 clean 풀이 각각 1회.
        for text, expect in (
            ("(a+b)² = a² + 2ab + b²", CORRECT_FORM_DEMONSTRATED),
            ("계산했다", None),
        ):
            calls.clear()
            await coach_mod._log_refutation_evidence(
                object(),  # type: ignore[arg-type]
                session_id=uuid.uuid4(),
                student_id=_UID,
                passed=True,
                matches=[],
                active_hypotheses=[
                    MisconceptionHypothesis(
                        misconception_id="distribution-over-power",
                        confidence=0.8,
                        turns_since_evidence=0,
                        evidence_count=1,
                    )
                ],
                solution_text=text,
            )
            assert len(calls) == 1, calls
            assert calls[0]["provenance"] == expect, (text, calls[0])
            assert calls[0]["polarity"] == -1
