"""적재 후 canonical 경쟁 **집행**(HARN-216 ②·④-집행) — 적재 경로가 판정을 실제로 경유해 쓰기를 막는가.

계약(판정 자체)은 `test_crosslink_canonical_flip_contract.py`가 고정한다. 여기서는 판정이 맞아도
**아무도 부르지 않으면 보호가 아니라는** 점을 겨냥해 세 가지를 본다:

  ① `load_crosslinks`가 쓰기(`populate`) **앞에서** 판정을 불러 wrong_winner·tie면 거부한다.
  ② 끄는 인자가 없다 — `check_fk_targets=False`(hermetic 좌석)도 이 판정을 건너뛰게 하지 못한다.
  ③ `promote --load` CLI가 이 거부를 전용 종료 코드 4로 번역한다.

실 PostgreSQL 관통은 `test_crosslink_canonical_flip_integration.py`가 맡는다(여기는 DB 0).
"""

from __future__ import annotations

import ast
import inspect
import json
import textwrap
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.l1.fk_precheck import ForeignKeyTargetMissingError, MissingFkTargets
from whymath_backend.l1.misconception import crosslink_loader
from whymath_backend.l1.misconception.crosslink_loader import (
    CanonicalFlipError,
    load_crosslinks,
)
from whymath_backend.l1.misconception.crosslink_resolve import ResolvedLink
from whymath_backend.l4.misconception import crosslink_review

_SIGNED = "검수:Kiki 2026-10-13"


def _payload(*rows: tuple[str, str, float]) -> dict[str, Any]:
    return {
        "crosslinks": [
            {
                "kebab_id": kebab,
                "mis_id": mis,
                "link_type": "직접매핑",
                "confidence": conf,
                "note": _SIGNED,
            }
            for kebab, mis, conf in rows
        ]
    }


class _StubStore:
    """라이브 행을 지정하고, 판정·FK 확인·쓰기 호출 여부를 기록하는 좌석."""

    def __init__(
        self,
        live: dict[str, list[ResolvedLink]] | None = None,
        missing: list[MissingFkTargets] | None = None,
    ) -> None:
        self._live = live or {}
        self._missing = missing or []
        self.fk_checked = 0
        self.live_read = 0
        self.populated = 0

    def missing_fk_targets(self, _records: Any) -> list[MissingFkTargets]:
        self.fk_checked += 1
        return self._missing

    def live_links(self, kebab_ids: Any) -> dict[str, list[ResolvedLink]]:
        self.live_read += 1
        return {k: v for k, v in self._live.items() if k in set(kebab_ids)}

    def populate(self, records: Any) -> int:
        self.populated += 1
        return len(list(records))


def _rival(mis: str, conf: float) -> ResolvedLink:
    return ResolvedLink(mis_id=mis, link_type="직접매핑", confidence=conf)


# ── ① 쓰기 앞에서 거부 ──────────────────────────────────────────────────────
class TestRefusalBeforeAnyWrite:
    def test_wrong_winner_raises_and_nothing_is_written(self) -> None:
        store = _StubStore({"k": [_rival("M0863", 0.95)]})
        with pytest.raises(CanonicalFlipError) as info:
            load_crosslinks(None, _payload(("k", "M0493", 0.85)), store=store)  # type: ignore[arg-type]
        assert store.populated == 0, "거부했으면 populate를 부르면 안 된다(쓰기 0건)"
        (verdict,) = info.value.verdicts
        assert verdict.verdict == "wrong_winner"

    def test_tie_raises_and_nothing_is_written(self) -> None:
        store = _StubStore({"k": [_rival("M0146", 0.85)]})
        with pytest.raises(CanonicalFlipError) as info:
            load_crosslinks(None, _payload(("k", "M0003", 0.85)), store=store)  # type: ignore[arg-type]
        assert store.populated == 0
        assert info.value.verdicts[0].verdict == "tie"

    def test_every_flipped_kebab_is_listed_and_clean_kebabs_are_not_written_either(self) -> None:
        """전건 열거 — 일부만 말하면 고치고 다시 돌려 또 걸린다. 깨끗한 kebab도 같이 쓰지 않는다(부분 적재 0)."""
        store = _StubStore({"a": [_rival("X", 0.95)], "b": [_rival("Y", 0.85)]})
        payload = _payload(("a", "A1", 0.85), ("b", "B1", 0.85), ("clean", "C1", 0.9))
        with pytest.raises(CanonicalFlipError) as info:
            load_crosslinks(None, payload, store=store)  # type: ignore[arg-type]
        assert [v.kebab_id for v in info.value.verdicts] == ["a", "b"]
        assert store.populated == 0
        text = str(info.value)
        for needle in ("a", "[wrong_winner]", "b", "[tie]", "X(0.95)", "Y(0.85)", "A1(0.85)"):
            assert needle in text
        assert "clean" not in text, "정상 kebab을 위반으로 보고하면 안 된다"
        assert "아무것도 쓰지 않았습니다" in text

    def test_no_competing_live_rows_proceeds_to_write(self) -> None:
        """대조군 — 판정이 모든 적재를 막으면 고장이다."""
        store = _StubStore({"k": [_rival("M9", 0.10)]})
        n = load_crosslinks(None, _payload(("k", "M1", 0.85)), store=store)  # type: ignore[arg-type]
        assert n == 1 and store.populated == 1 and store.live_read == 1

    def test_same_triplet_live_row_is_not_a_competitor(self) -> None:
        """대조군 — 라이브가 코퍼스와 같은 트리플이면 업서트가 덮는다."""
        store = _StubStore({"k": [_rival("M1", 0.99)]})
        n = load_crosslinks(None, _payload(("k", "M1", 0.85)), store=store)  # type: ignore[arg-type]
        assert n == 1 and store.populated == 1

    def test_empty_collection_returns_before_reading_the_live_table(self) -> None:
        store = _StubStore()
        assert load_crosslinks(None, {"crosslinks": []}, store=store) == 0  # type: ignore[arg-type]
        assert store.live_read == 0 and store.populated == 0


# ── ② 끄는 인자가 없다 ──────────────────────────────────────────────────────
class TestNoBypass:
    def test_signature_has_no_new_switch(self) -> None:
        """우회 인자를 새로 두지 않는다 — 인자 집합이 늘면 이 테스트가 그 사실을 드러낸다."""
        params = set(inspect.signature(load_crosslinks).parameters)
        assert params == {
            "session",
            "collection_json",
            "engine",
            "settings",
            "store",
            "check_fk_targets",
        }

    def test_check_fk_targets_false_does_not_skip_the_flip_check(self) -> None:
        """hermetic 좌석(`check_fk_targets=False`)이 canonical 판정까지 끄면 사실상 우회로다."""
        store = _StubStore({"k": [_rival("M0863", 0.95)]})
        with pytest.raises(CanonicalFlipError):
            load_crosslinks(
                None,
                _payload(("k", "M0493", 0.85)),
                store=store,  # type: ignore[arg-type]
                check_fk_targets=False,
            )
        assert store.fk_checked == 0 and store.live_read == 1 and store.populated == 0

    def test_gate_violation_still_wins_before_any_database_read(self) -> None:
        store = _StubStore({"k": [_rival("M0863", 0.95)]})
        bad = _payload(("k", "M0493", 0.85))
        bad["crosslinks"][0]["note"] = "서명 없음"
        with pytest.raises(crosslink_loader.CrosslinkGateError):
            load_crosslinks(None, bad, store=store)  # type: ignore[arg-type]
        assert store.fk_checked == 0 and store.live_read == 0

    def test_fk_error_is_reported_before_the_flip_check(self) -> None:
        """순서 계약 — 입력 쪽 결함(FK)이 먼저, 라이브 경쟁은 그 다음이다."""
        store = _StubStore(
            {"k": [_rival("M0863", 0.95)]}, missing=[MissingFkTargets("a -> b", ("M0493",))]
        )
        with pytest.raises(ForeignKeyTargetMissingError):
            load_crosslinks(None, _payload(("k", "M0493", 0.85)), store=store)  # type: ignore[arg-type]
        assert store.live_read == 0 and store.populated == 0


# ── ④ 집행 지점이 쓰기 앞에 구조적으로 있다 ─────────────────────────────────
def _call_lines(func: Any, name: str) -> list[int]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    return sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == name)
            or (isinstance(node.func, ast.Attribute) and node.func.attr == name)
        )
    )


class TestWiringIsStructural:
    def test_load_crosslinks_calls_the_verdict_before_populate(self) -> None:
        verdict_lines = _call_lines(load_crosslinks, "canonical_flip_verdicts")
        populate_lines = _call_lines(load_crosslinks, "populate")
        assert len(verdict_lines) == 1 and len(populate_lines) == 1
        assert verdict_lines[0] < populate_lines[0]

    def test_the_verdict_helper_reads_live_rows_through_the_store_seat(self) -> None:
        assert _call_lines(crosslink_loader.canonical_flip_verdicts, "live_links")
        assert _call_lines(crosslink_loader.canonical_flip_verdicts, "simulate_load_canonical")


# ── ③ CLI 종료 코드 ─────────────────────────────────────────────────────────
class TestCliExitCode:
    def _queue(self, tmp_path: Path) -> Path:
        row = {
            "kebab_id": "distribution-over-power",
            "mis_id": "M0493",
            "link_type": "직접매핑",
            "confidence": 0.85,
            "rationale": "근거",
            "status": "approved",
            "reviewer": "kiki",
            "reviewed_on": "2026-10-13",
            "note": None,
        }
        path = tmp_path / "queue.json"
        path.write_text(json.dumps({"review_queue": [row]}, ensure_ascii=False), encoding="utf-8")
        return path

    def test_promote_load_exits_4_and_prints_the_listing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store = _StubStore({"distribution-over-power": [_rival("M0863", 0.95)]})

        def _via_stub(session: Any, collection_json: Any, **kwargs: Any) -> int:
            return load_crosslinks(session, collection_json, store=store, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(crosslink_loader, "load_crosslinks", _via_stub)
        code = crosslink_review.main(["promote", "--queue", str(self._queue(tmp_path)), "--load"])
        out = capsys.readouterr().out
        assert code == 4
        assert (
            "distribution-over-power" in out
            and "M0863(0.95)" in out
            and "아무것도 쓰지 않았습니다" in out
        )
        assert store.populated == 0

    def test_exit_code_4_is_documented_on_the_cli(self) -> None:
        doc = crosslink_review.main.__doc__ or ""
        assert "4=" in doc and "HARN-216" in doc
