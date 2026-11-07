"""EOS-226 사람 단독 첫 검수 HIT 표본 집계(`scripts/analysis/eos226_a4_human_hit.py`) 동결.

실제 A4 데이터에서는 재검수·다시 보기·미계측 제외가 모두 0건이다. 0건은 "검사가 아무것도 못 잡는다"와
화면이 같으므로, 규칙마다 그 규칙에 걸리는 합성 입력을 넣어 실제로 빠지는지 확인한다.
마지막 테스트는 커밋된 CU별 기록이 스크립트 재실행 결과와 같은지 본다(손으로 고친 기록 차단).
"""

from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from whymath_backend.harness.review_timer import load_events_jsonl
from whymath_backend.schema.review_timer import ReviewTimerEvent

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "scripts/analysis/eos226_a4_human_hit.py"
_A4_EVENTS = _REPO_ROOT / "data/runs/eos-a4-review/canary_review_events.jsonl"
_A6_EVENTS = _REPO_ROOT / "data/runs/eos197-a6-review/canary_review_events.jsonl"
_A4_RECORDS = _REPO_ROOT / "data/runs/eos-a4-review/cu.review_human_hit.jsonl"

_T0 = datetime(2026, 11, 7, 7, 0, 0, tzinfo=UTC)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("eos226_a4_human_hit", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclass가 모듈을 찾을 수 있게
    spec.loader.exec_module(module)
    return module


M = _load_script()


def _fp(slug: str) -> str:
    return "sha256:" + uuid.uuid5(uuid.NAMESPACE_URL, slug).hex * 2


def _session(
    slug: str,
    *,
    start_s: float,
    elapsed_s: float | None,
    terminal: str | None = "finished",
    verdict: str = "approved",
    fingerprint: str | None = None,
) -> list[ReviewTimerEvent]:
    """세션 1개(started + 종결) — terminal=None이면 started만(미종결)."""
    sid = uuid.uuid4()
    fp = fingerprint if fingerprint is not None else _fp(slug)
    started_at = _T0 + timedelta(seconds=start_s)
    rows: list[dict[str, Any]] = [
        {
            "review_session_id": str(sid),
            "cu_slug": slug,
            "reviewer_id": "kiki",
            "event_type": "started",
            "content_fingerprint": fp,
            "occurred_at": started_at.isoformat(),
        }
    ]
    if terminal is not None:
        end = started_at + timedelta(seconds=elapsed_s or 0)
        row: dict[str, Any] = {
            "review_session_id": str(sid),
            "cu_slug": slug,
            "reviewer_id": "kiki",
            "event_type": terminal,
            "elapsed_ms": None if elapsed_s is None else int(round(elapsed_s * 1000)),
            "occurred_at": end.isoformat(),
        }
        if terminal == "finished":
            row["verdict"] = verdict
            row["content_fingerprint"] = fp
            if verdict == "rejected":
                row["failure_code"] = "F8"
        rows.append(row)
    return [ReviewTimerEvent.model_validate(r) for r in rows]


def _run(
    events: list[ReviewTimerEvent],
    *,
    prior: list[ReviewTimerEvent] | None = None,
    review_back: str = "none",
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    records, summary = M.classify(
        events,
        prior_events=prior or [],
        condition="human_only",
        condition_source="테스트",
        review_back=M.ReviewBack.parse(review_back),
        review_back_source="테스트",
    )
    return {r["cu_slug"]: r for r in records}, summary


def test_single_session_above_floor_is_valid() -> None:
    recs, summary = _run(_session("a", start_s=0, elapsed_s=45))
    assert recs["a"]["valid"] is True
    assert recs["a"]["exclusion_reasons"] == []
    assert summary["valid"]["n"] == 1


def test_floor_boundary_excludes_below_and_keeps_equal() -> None:
    events = _session("below", start_s=0, elapsed_s=29.999) + _session(
        "equal", start_s=100, elapsed_s=30.0
    )
    recs, summary = _run(events)
    assert recs["below"]["exclusion_reasons"] == [M.REASON_BELOW_FLOOR]
    assert recs["below"]["valid"] is False
    assert recs["equal"]["valid"] is True  # 하한과 정확히 같으면 통과(hit_cu_metrics 경계)
    assert summary["excluded_by_reason"][M.REASON_BELOW_FLOOR] == 1


def test_held_then_resumed_is_valid_flagged_and_summed() -> None:
    events = _session("h", start_s=0, elapsed_s=20, terminal="aborted") + _session(
        "h", start_s=300, elapsed_s=25
    )
    recs, summary = _run(events)
    rec = recs["h"]
    assert rec["held_resumed"] is True
    assert rec["first_review"] is True
    assert rec["hit_seconds"] == pytest.approx(45.0)  # 두 세션 합 — 첫 세션 시간이 빠지지 않는다
    assert rec["valid"] is True  # 합이 하한 이상이면 유효(세션 하나하나는 30초 미만이어도)
    assert summary["held_resumed_in_valid"]["n"] == 1
    assert summary["valid_excluding_held_resumed"]["n"] == 0


def test_session_after_verdict_is_re_review() -> None:
    events = _session("r", start_s=0, elapsed_s=60) + _session(
        "r", start_s=500, elapsed_s=10, terminal="aborted"
    )
    recs, _ = _run(events)
    assert M.REASON_RE_REVIEW_POST_VERDICT in recs["r"]["exclusion_reasons"]
    assert recs["r"]["first_review"] is False
    assert recs["r"]["valid"] is False


def test_second_verdict_is_re_review() -> None:
    events = _session("r2", start_s=0, elapsed_s=60) + _session("r2", start_s=500, elapsed_s=40)
    recs, _ = _run(events)
    assert M.REASON_RE_REVIEW_POST_VERDICT in recs["r2"]["exclusion_reasons"]


def test_prior_round_same_slug_is_re_review() -> None:
    # 지문은 일부러 다르게 둔다 — 같으면 지문 대조가 대신 잡아 slug 대조 절을 밟지 못한다.
    prior = _session("p", start_s=-9000, elapsed_s=50, fingerprint=_fp("p-이전판"))
    recs, summary = _run(_session("p", start_s=0, elapsed_s=50), prior=prior)
    assert recs["p"]["exclusion_reasons"] == [M.REASON_RE_REVIEW_PRIOR]
    assert summary["prior_finished_scanned"] == 1


def test_prior_round_same_fingerprint_other_slug_is_re_review() -> None:
    shared = _fp("같은내용")
    prior = _session("old-slug", start_s=-9000, elapsed_s=50, fingerprint=shared)
    recs, _ = _run(_session("new-slug", start_s=0, elapsed_s=50, fingerprint=shared), prior=prior)
    assert recs["new-slug"]["exclusion_reasons"] == [M.REASON_RE_REVIEW_PRIOR]


def test_prior_round_unrelated_is_not_re_review() -> None:
    prior = _session("other", start_s=-9000, elapsed_s=50)
    recs, _ = _run(_session("mine", start_s=0, elapsed_s=50), prior=prior)
    assert recs["mine"]["valid"] is True  # 대조군 — 다른 회차가 있다고 전부 재검수가 되지 않는다


def test_review_back_listed_slug_is_excluded_and_unknown_is_only_flagged() -> None:
    events = _session("x", start_s=0, elapsed_s=50) + _session("y", start_s=100, elapsed_s=50)
    recs, summary = _run(events, review_back="x")
    assert recs["x"]["exclusion_reasons"] == [M.REASON_REVIEW_BACK]
    assert recs["x"]["review_back"] == "used"
    assert recs["y"]["valid"] is True
    assert summary["review_back_listed"] == ["x"]

    recs_u, summary_u = _run(events, review_back="unknown")
    assert all(r["valid"] for r in recs_u.values())
    assert {r["review_back"] for r in recs_u.values()} == {"unknown"}
    assert summary_u["review_back"] == "unknown"


def test_review_back_argument_rejects_empty() -> None:
    with pytest.raises(ValueError):
        M.ReviewBack.parse(" , ")


def test_unfinished_and_unmeasured_are_excluded() -> None:
    events = (
        _session("measured", start_s=0, elapsed_s=50)
        + _session("open", start_s=100, elapsed_s=None, terminal=None)
        + _session("untimed", start_s=200, elapsed_s=None)
    )
    recs, _ = _run(events)
    assert recs["open"]["exclusion_reasons"] == [M.REASON_NOT_MEASURED]
    assert recs["untimed"]["exclusion_reasons"] == [M.REASON_NOT_MEASURED]
    assert recs["open"]["hit_seconds"] is None  # 0초로 위장하지 않는다


def test_condition_is_written_on_every_record() -> None:
    events = _session("a", start_s=0, elapsed_s=50) + _session("b", start_s=100, elapsed_s=10)
    recs, summary = _run(events)
    for rec in recs.values():
        assert rec["review_condition"] == "human_only"
        assert rec["ai_assist"] is False
        assert rec["condition_source"] == "테스트"
    assert summary["ai_assist"] is False


def test_unknown_condition_is_refused() -> None:
    with pytest.raises(ValueError):
        M.classify(
            _session("a", start_s=0, elapsed_s=50),
            prior_events=[],
            condition="ai_assisted",
            condition_source="테스트",
            review_back=M.ReviewBack.parse("none"),
            review_back_source="테스트",
        )


def test_zero_events_is_measurement_failure() -> None:
    with pytest.raises(M.MeasurementError):
        _run([])


def test_cross_check_mismatch_is_measurement_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    real_aggregate = M.aggregate

    def _drifted(*args: Any, **kwargs: Any) -> Any:
        import dataclasses

        report = real_aggregate(*args, **kwargs)
        return dataclasses.replace(report, hit_median_seconds=(report.hit_median_seconds or 0) + 1)

    monkeypatch.setattr(M, "aggregate", _drifted)
    with pytest.raises(M.MeasurementError, match="공식 계측기와 불일치"):
        _run(_session("a", start_s=0, elapsed_s=50))


def test_cli_refuses_empty_prior_round_file(tmp_path: Path) -> None:
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    code = M.main(
        [
            "--events",
            str(_A4_EVENTS),
            "--prior-events",
            str(empty),
            "--condition",
            "human_only",
            "--condition-source",
            "테스트",
            "--review-back",
            "none",
            "--review-back-source",
            "테스트",
        ]
    )
    assert code == 1  # 대조 회차 0건으로 "재검수 0건" 공허 통과를 내지 않는다


def test_committed_records_match_regeneration() -> None:
    committed = [
        json.loads(line)
        for line in _A4_RECORDS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert committed, "커밋된 CU별 기록이 비어 있다"
    events, errors = load_events_jsonl(_A4_EVENTS)
    prior, prior_errors = load_events_jsonl(_A6_EVENTS)
    assert not errors and not prior_errors
    head = committed[0]
    regenerated, summary = M.classify(
        events,
        prior_events=prior,
        condition=head["review_condition"],
        condition_source=head["condition_source"],
        review_back=M.ReviewBack.parse("none"),
        review_back_source=head["review_back_source"],
    )
    normalized = [
        json.loads(json.dumps(r, ensure_ascii=False, sort_keys=True)) for r in regenerated
    ]
    assert normalized == committed, "커밋된 기록이 스크립트 출력과 다르다 — 재실행해 다시 커밋하라"
    # acceptance ① — 유효 표본 15건 이상(이 기록이 그 근거다)
    assert summary["valid"]["n"] >= 15
    assert summary["valid"]["n"] == sum(1 for r in committed if r["valid"])
