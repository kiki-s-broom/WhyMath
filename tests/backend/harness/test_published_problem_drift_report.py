"""발행 문항 판-라이브 드리프트 리포트 동결 — hermetic (EOS-195 acceptance ②).

`harness/published_problem_drift_report.py`가 내는 숫자는 "차단이 지켜지고 있는가"의 유일한 탐지
통제다. 그래서 이 파일은 **숫자가 거짓말을 못 하게** 하는 성질을 고정한다:

  ① 3상태(일치/어긋남/판정 불가)를 뭉개지 않는다 — 판정 불가 4사유가 각각 따로 센다
  ② 분모 0은 통과가 아니라 **측정 불성립**이다 — 비율은 None이고 렌더가 "0.0%"를 말하지 않는다
  ③ 해시 대조는 발행 게이트의 해시 함수를 그대로 쓴다(리포트와 게이트가 같은 일치 판정을 한다)
  ④ 어긋난 필드는 **이름만** 싣는다 — 정답·본문 값이 산출물(마크다운·JSON)로 새지 않는다
  ⑤ 게이트가 아니다 — 어긋남이 있어도 exit 0, DB 오류만 exit 2(예외 타입명과 함께 stderr)
  ⑥ DB 조회(`iter_pointer_filled`)의 키셋 페이지네이션이 건수를 잃거나 중복하지 않는다

DB 글루의 실제 SQL(조인·키셋 조건·`populate_existing`)은 실 PG 통합 테스트
(`tests/backend/db/test_published_problem_edit_guard_integration.py`)가 본다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from whymath_backend.harness import published_problem_drift_report as report_mod
from whymath_backend.harness.published_problem_drift_report import (
    SAMPLE_LIMIT,
    DriftReport,
    IndeterminateReason,
    PointerObservation,
    PointerState,
    Verdict,
    aggregate,
    classify,
    collect_report,
    dump_json,
    main,
    observe,
    render_report,
    report_to_json,
)
from whymath_backend.l3 import problem_publish_gate as gate
from whymath_backend.l3.problem_publish_gate import PointerPair
from whymath_backend.schema.enums import Curriculum, SourceType, Subject
from whymath_backend.schema.problem_version import ProblemVersion as SchemaProblemVersion
from whymath_backend.schema.version_header import VersionStatus

#: 산출물에 값이 새는지 보는 결함주입 표지 — 정답·본문 자리에 넣는다.
_SENTINEL = "SENTINEL-EOS195-리포트유출-9913"


def _live(**overrides: Any) -> SimpleNamespace:
    """`snapshot_payload`가 읽는 속성만 가진 라이브 문항 대역(자체생성 — 저작권 레일 통과)."""
    fields: dict[str, Any] = {
        "source_type": SourceType.자체생성,
        "subject": Subject.미적분,
        "curriculum_version": Curriculum.REVISION_2022,
        "unit_codes": ["CAL-INT-DEF"],
        "question_format": None,
        "answer_format": None,
        "points": None,
        "question_text": "적분값을 구하시오",
        "choices": None,
        "answer": _SENTINEL,
        "answer_explanation": None,
        "difficulty_overall": 3.0,
        "problem_id": uuid.uuid4(),
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _version(
    live: SimpleNamespace,
    *,
    status: VersionStatus = VersionStatus.PUBLISHED,
    problem_id: uuid.UUID | None = None,
    **payload_overrides: Any,
) -> SchemaProblemVersion:
    """`live`를 발행 시점에 스냅숏한 판. `payload_overrides`로 판 쪽만 다르게 만든다."""
    payload = gate.snapshot_payload(live)  # type: ignore[arg-type]
    if payload_overrides:
        payload = payload.model_copy(update=payload_overrides)
    return SchemaProblemVersion(
        problem_id=problem_id or live.problem_id,
        version_no=1,
        schema_version=gate.PAYLOAD_SCHEMA_VERSION,
        status=status,
        payload=payload,
    )


def _obs(live: SimpleNamespace, version: SchemaProblemVersion | None) -> PointerObservation:
    return PointerObservation(
        problem_id=live.problem_id,
        live=gate.snapshot_payload(live),  # type: ignore[arg-type]
        live_error=None,
        version=version,
        version_error=None if version is not None else "LookupError",
    )


# ── ① 3상태 판정표 ───────────────────────────────────────────────────────────────────
def test_identical_live_and_version_is_in_sync() -> None:
    live = _live()
    verdict = classify(_obs(live, _version(live)))
    assert verdict == Verdict(PointerState.IN_SYNC)


def test_changed_answer_is_drifted_and_names_the_fields() -> None:
    live = _live()
    version = _version(live)
    edited = _live(problem_id=live.problem_id, answer="고친 정답")
    verdict = classify(_obs(edited, version))
    assert verdict.state is PointerState.DRIFTED
    # 정답이 바뀌면 파생 해시도 같이 바뀐다 — 둘 다 보고되고 값은 없다.
    assert verdict.changed_fields == ("answer", "answer_hash")


def test_difficulty_only_change_is_drifted_with_a_single_field() -> None:
    """난이도만 바뀌어도 게이트의 일치 판정(해시)은 깨진다 — 리포트가 게이트와 같은 기준이다."""
    live = _live()
    version = _version(live)
    verdict = classify(_obs(_live(problem_id=live.problem_id, difficulty_overall=4.0), version))
    assert verdict.state is PointerState.DRIFTED
    assert verdict.changed_fields == ("difficulty_at_publish",)


def test_version_unreadable_is_indeterminate_not_in_sync() -> None:
    live = _live()
    verdict = classify(_obs(live, None))
    assert verdict == Verdict(PointerState.INDETERMINATE, IndeterminateReason.VERSION_UNREADABLE)


def test_pointer_to_another_problems_version_is_indeterminate() -> None:
    live = _live()
    other = _version(live, problem_id=uuid.uuid4())
    verdict = classify(_obs(live, other))
    assert verdict.reason is IndeterminateReason.VERSION_PROBLEM_MISMATCH


@pytest.mark.parametrize(
    "status", [s for s in VersionStatus if s is not VersionStatus.PUBLISHED], ids=lambda s: s.value
)
def test_pointer_to_a_non_published_version_is_indeterminate(status: VersionStatus) -> None:
    """포인터는 PUBLISHED 판만 가리켜야 한다. 그 불변식이 깨진 상태에서는 payload가 우연히 같아도
    '일치'로 세지 않는다."""
    live = _live()
    verdict = classify(_obs(live, _version(live, status=status)))
    assert verdict.state is PointerState.INDETERMINATE
    assert verdict.reason is IndeterminateReason.VERSION_NOT_PUBLISHED


def test_live_snapshot_failure_is_indeterminate_and_does_not_count_as_drift() -> None:
    live = _live()
    obs = PointerObservation(
        problem_id=live.problem_id,
        live=None,
        live_error="ValidationError",
        version=_version(live),
        version_error=None,
    )
    verdict = classify(obs)
    assert verdict.state is PointerState.INDETERMINATE
    assert verdict.reason is IndeterminateReason.LIVE_SNAPSHOT_INVALID


def test_indeterminate_checks_run_before_the_hash_comparison() -> None:
    """판정 불가 사유가 해시 대조보다 먼저 가려진다 — DEPRECATED 판과 payload가 같아도 일치가 아니다."""
    live = _live()
    verdict = classify(_obs(live, _version(live, status=VersionStatus.DEPRECATED)))
    assert verdict.state is not PointerState.IN_SYNC


def test_observe_turns_a_contract_violating_live_row_into_a_typed_error() -> None:
    """평가원 출처에 본문이 남은 행은 스냅숏 계약 위반 — 예외 타입명을 남기고 값은 남기지 않는다."""
    bad = _live(source_type=SourceType.평가원, question_text=_SENTINEL)
    pair = PointerPair(problem=bad, version=_version(_live()))  # type: ignore[arg-type]
    obs = observe(pair)
    assert obs.live is None and obs.live_error == "ValidationError"
    assert _SENTINEL not in repr(obs.live_error)


# ── ① 집계 ──────────────────────────────────────────────────────────────────────────
def _verdicts(*states: Verdict) -> list[tuple[uuid.UUID, Verdict]]:
    return [(uuid.uuid4(), v) for v in states]


_SYNC = Verdict(PointerState.IN_SYNC)
_DRIFT_ANSWER = Verdict(PointerState.DRIFTED, changed_fields=("answer", "answer_hash"))
_DRIFT_DIFFICULTY = Verdict(PointerState.DRIFTED, changed_fields=("difficulty_at_publish",))


def _indet(reason: IndeterminateReason) -> Verdict:
    return Verdict(PointerState.INDETERMINATE, reason)


def test_denominator_is_every_pointer_filled_problem_including_indeterminate() -> None:
    report = aggregate(
        _verdicts(
            _SYNC,
            _SYNC,
            _DRIFT_ANSWER,
            _indet(IndeterminateReason.VERSION_UNREADABLE),
        ),
        problems_total=10,
    )
    assert (report.in_sync, report.drifted, report.indeterminate) == (2, 1, 1)
    assert report.pointer_filled == 4
    assert report.verified == 3
    assert report.drift_rate == pytest.approx(0.25)


def test_indeterminate_reasons_are_counted_separately() -> None:
    report = aggregate(
        _verdicts(
            _indet(IndeterminateReason.VERSION_UNREADABLE),
            _indet(IndeterminateReason.VERSION_UNREADABLE),
            _indet(IndeterminateReason.VERSION_NOT_PUBLISHED),
            _indet(IndeterminateReason.LIVE_SNAPSHOT_INVALID),
            _indet(IndeterminateReason.VERSION_PROBLEM_MISMATCH),
        ),
        problems_total=5,
    )
    assert report.indeterminate_by_reason == {
        "version_unreadable": 2,
        "version_not_published": 1,
        "live_snapshot_invalid": 1,
        "version_problem_mismatch": 1,
    }


def test_drift_is_broken_down_by_field_and_difficulty_only_is_counted() -> None:
    report = aggregate(_verdicts(_DRIFT_ANSWER, _DRIFT_ANSWER, _DRIFT_DIFFICULTY), problems_total=3)
    assert report.drifted_by_field == {"answer": 2, "answer_hash": 2, "difficulty_at_publish": 1}
    assert report.drifted_difficulty_only == 1


def test_difficulty_plus_content_is_not_difficulty_only() -> None:
    mixed = Verdict(PointerState.DRIFTED, changed_fields=("answer", "difficulty_at_publish"))
    assert aggregate(_verdicts(mixed), problems_total=1).drifted_difficulty_only == 0


def test_samples_are_capped_and_keep_input_order() -> None:
    items = [(uuid.uuid4(), _DRIFT_ANSWER) for _ in range(SAMPLE_LIMIT + 5)]
    report = aggregate(items, problems_total=len(items))
    assert report.drifted == SAMPLE_LIMIT + 5
    assert len(report.samples) == SAMPLE_LIMIT
    assert [s.problem_id for s in report.samples] == [pid for pid, _ in items[:SAMPLE_LIMIT]]


# ── ② 분모 0 = 측정 불성립 ───────────────────────────────────────────────────────────
def _empty() -> DriftReport:
    return aggregate([], problems_total=1234)


def test_empty_denominator_is_not_measurable_and_rate_is_none() -> None:
    report = _empty()
    assert report.pointer_filled == 0
    assert report.measurable is False
    assert report.drift_rate is None


def test_empty_denominator_render_says_not_established_and_never_reports_zero_percent() -> None:
    text = render_report(_empty())
    assert "측정 불성립" in text
    assert "0.0%" not in text
    # '통과'로 읽힐 수 있는 표현을 쓰지 않는다.
    assert "드리프트 없음'이 아니라" in text


def test_empty_denominator_json_marks_unmeasurable() -> None:
    data = report_to_json(_empty())
    assert data["measurable"] is False and data["drift_rate"] is None
    assert data["pointer_filled"] == 0 and data["problems_total"] == 1234


def test_all_indeterminate_has_no_rate_even_with_a_denominator() -> None:
    """분모는 있어도 해시를 한 건도 대조하지 못했으면 비율은 None이다 — JSON이 0.0을 내면 소비자가
    "측정됨·어긋남 0%"로 읽는다(독립 검토 지적 #5 · 0건 통과 위장 금지)."""
    report = aggregate(
        _verdicts(
            _indet(IndeterminateReason.VERSION_UNREADABLE),
            _indet(IndeterminateReason.LIVE_SNAPSHOT_INVALID),
        ),
        problems_total=5,
    )
    assert report.pointer_filled == 2 and report.verified == 0
    assert report.drift_rate is None
    assert report_to_json(report)["drift_rate"] is None
    assert "0.0%" not in render_report(report)


def test_a_clean_but_populated_report_does_report_zero_percent() -> None:
    """대조군 — 분모가 있고 어긋남이 0이면 '0.0%'를 말한다. 위 테스트가 문자열 부재만 보는 것이
    아니라 측정 여부에 따라 갈린다는 증거."""
    text = render_report(aggregate(_verdicts(_SYNC, _SYNC), problems_total=2))
    assert "0.0%" in text and "측정 불성립" not in text


# ── ④ 값 유출 금지 ──────────────────────────────────────────────────────────────────
def test_artifacts_never_carry_field_values() -> None:
    live = _live()
    version = _version(live)
    edited = _live(problem_id=live.problem_id, answer=_SENTINEL + "-EDITED")
    verdict = classify(_obs(edited, version))
    report = aggregate([(live.problem_id, verdict)], problems_total=1)
    assert _SENTINEL not in render_report(report)
    assert _SENTINEL not in dump_json(report)
    # 필드 *이름*은 실린다 — 이름도 안 실리면 리포트가 쓸모없다.
    assert "answer" in render_report(report) and "answer" in dump_json(report)


def test_render_lists_indeterminate_reasons_and_warns_about_unverified() -> None:
    text = render_report(
        aggregate(
            _verdicts(_SYNC, _indet(IndeterminateReason.VERSION_UNREADABLE)), problems_total=2
        )
    )
    assert "version_unreadable" in text
    assert "검증 못 한" in text


# ── ⑤ CLI — 게이트가 아니다 ─────────────────────────────────────────────────────────
def _stub_run(monkeypatch: pytest.MonkeyPatch, report: DriftReport | Exception) -> None:
    async def fake_run() -> DriftReport:
        if isinstance(report, Exception):
            raise report
        return report

    monkeypatch.setattr(report_mod, "_run", fake_run)


def test_cli_exits_zero_even_when_drift_exists(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    drifted = aggregate(_verdicts(_DRIFT_ANSWER), problems_total=1)
    _stub_run(monkeypatch, drifted)
    assert main([]) == 0
    assert "어긋남" in capsys.readouterr().out


def test_cli_db_error_exits_two_with_the_exception_type_name(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """측정 실패가 '0건'으로 위장되지 않는다 — 별도 종료 코드와 타입명."""
    _stub_run(monkeypatch, ConnectionRefusedError("접속 거부"))
    assert main([]) == 2
    captured = capsys.readouterr()
    assert "ConnectionRefusedError" in captured.err
    assert captured.out == ""


def test_cli_writes_json_when_asked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub_run(monkeypatch, aggregate(_verdicts(_SYNC), problems_total=1))
    out = tmp_path / "nested" / "drift.json"
    assert main(["--json", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["in_sync"] == 1 and data["measurable"] is True
    capsys.readouterr()


# ── ⑥ DB 조회 — 키셋 페이지네이션 ───────────────────────────────────────────────────────
class _Rows:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows

    def scalar_one(self) -> Any:
        return self._rows[0]


class _ScriptedSession:
    """`execute` 호출마다 미리 정한 결과를 순서대로 돌려준다 — 호출 횟수가 곧 페이지 수다."""

    def __init__(self, *results: list[Any]) -> None:
        self._results = list(results)
        self.calls = 0

    async def execute(self, _stmt: Any) -> _Rows:
        self.calls += 1
        return _Rows(self._results.pop(0))


class _VersionRow:
    def __init__(self, schema: SchemaProblemVersion | Exception) -> None:
        self._schema = schema
        self.version_id = uuid.uuid4()

    def to_schema(self) -> SchemaProblemVersion:
        if isinstance(self._schema, Exception):
            raise self._schema
        return self._schema


def _pairs(n: int) -> list[tuple[SimpleNamespace, _VersionRow]]:
    out = []
    for _ in range(n):
        live = _live()
        out.append((live, _VersionRow(_version(live))))
    return out


async def _drain(session: Any, batch_size: int) -> list[PointerPair]:
    return [p async for p in gate.iter_pointer_filled(session, batch_size=batch_size)]


def test_pagination_yields_every_row_once_across_batches() -> None:
    rows = _pairs(5)
    session = _ScriptedSession(rows[0:2], rows[2:4], rows[4:5])
    got = asyncio.run(_drain(session, 2))
    assert [p.problem for p in got] == [r[0] for r in rows]
    assert session.calls == 3, "마지막 배치가 batch_size보다 작으면 거기서 끝나야 한다"


def test_pagination_stops_after_an_empty_page_when_the_total_is_a_batch_multiple() -> None:
    rows = _pairs(4)
    session = _ScriptedSession(rows[0:2], rows[2:4], [])
    got = asyncio.run(_drain(session, 2))
    assert len(got) == 4 and session.calls == 3


def test_empty_table_yields_nothing_in_one_query() -> None:
    session = _ScriptedSession([])
    assert asyncio.run(_drain(session, 500)) == []
    assert session.calls == 1


def test_missing_version_row_is_reported_not_skipped() -> None:
    live = _live()
    session = _ScriptedSession([(live, None)])
    (pair,) = asyncio.run(_drain(session, 10))
    assert pair.version is None and pair.version_error == "LookupError"


def test_contract_violating_version_is_reported_with_type_name_and_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """건너뛰면 그 문항이 분모에서 사라진다 — 조용한 누락 금지. 타입명을 로그에 남긴다."""
    from whymath_backend.schema.problem_version import ProblemVersionPayload

    try:
        ProblemVersionPayload.model_validate({})
    except Exception as exc:  # noqa: BLE001 — 진짜 ValidationError를 얻으려는 것
        error = exc
    live = _live()
    session = _ScriptedSession([(live, _VersionRow(error))])
    with caplog.at_level(logging.WARNING, logger="whymath.l3.problem_publish_gate"):
        (pair,) = asyncio.run(_drain(session, 10))
    assert pair.version is None and pair.version_error == "ValidationError"
    assert "ValidationError" in caplog.text


def test_batch_size_must_be_positive() -> None:
    with pytest.raises(ValueError):
        asyncio.run(_drain(_ScriptedSession([]), 0))


def test_collect_report_counts_through_the_gate_read_path() -> None:
    """전 문항 수 → 포인터 채워진 문항 훑기 → 판정·집계가 한 줄로 이어진다."""
    clean = _live()
    drifted_live = _live()
    stale_version = _version(drifted_live)
    drifted_live.answer = "나중에 고친 정답"
    session = _ScriptedSession(
        [42],  # select count(*)
        [(clean, _VersionRow(_version(clean))), (drifted_live, _VersionRow(stale_version))],
    )
    report = asyncio.run(collect_report(session))  # type: ignore[arg-type]
    assert report.problems_total == 42
    assert (report.pointer_filled, report.in_sync, report.drifted) == (2, 1, 1)
    assert report.drifted_by_field.get("answer") == 1
