"""P3-73 — 튜터 context 구성 요약의 Langfuse 기록(이벤트 `tutor_context`) 계약.

`test_wh1_tutor_context.py`가 매니페스트 판정을 본다면, 이 파일은 그 판정이 **Langfuse에 어떤 모양으로
남는가**를 본다.

- 이벤트명이 `l3_routing`과 다르다 — 비용 판독(`ops/cost_report.py`) 집계가 무변화임을 가짜 Langfuse
  (쓰기·읽기 둘 다)로 동결하고, 같은 내용을 `l3_routing`으로 보내면 집계가 **바뀌는** 대조군을 둔다
  (대조군이 없으면 "필터가 원래 아무것도 안 걸렀다"와 구별이 안 된다).
- 기록 필드에 값이 없다 — θ·숙달·학생 원문·스킬 id가 직렬화 결과 어디에도 없다.
- 이중 회계 — 이름 목록 세 개가 관측 레코드(`context_*`)와 같다.
- never-break — 싱크 부재·능력 부재·전송 예외·조립 예외 각각에서 예외 0, 실패는 타입명 WARNING.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic import SecretStr

from whymath_backend.config import Settings
from whymath_backend.harness import wh1_primary, wh1_tutor_context
from whymath_backend.harness.wh1_tutor_context import (
    TUTOR_CONTEXT_EVENT_NAME,
    TutorContextManifest,
    TutorContextSlot,
    TutorDeliveryPath,
    build_tutor_context_manifest,
    record_tutor_context,
    tutor_context_trace_fields,
)
from whymath_backend.l3.interfaces import RecordingTraceSink, TrafficSurface
from whymath_backend.l3.trace import LangfuseSink, langfuse_sink
from whymath_backend.l4.misconception.hypothesis import MisconceptionHypothesis
from whymath_backend.l4.pedagogy.pack_registry import get_pack
from whymath_backend.ops import cost_report

_CTX_LOGGER = "whymath.harness.wh1_tutor_context"
_THETA = 0.4137  # 누출 감시 표지 — 다른 수치와 겹치지 않게
_MASTERY = 0.5813
_SKILL = "SK-ALG-UNIQUE-77"
_ANSWER = "x+1=3 이니까 x=2 라고 생각했어요"
_HYP = MisconceptionHypothesis(
    misconception_id="distribution-over-power",
    confidence=0.8,
    turns_since_evidence=0,
    evidence_count=1,
)


def _manifest(**over: Any) -> TutorContextManifest:
    """9종을 얻은 매니페스트(턴 뒤 전달 경로 반영) — `over`로 슬롯을 비운다."""
    pack = get_pack("CONCEPT")
    assert pack is not None
    kwargs: dict[str, Any] = {
        "problem_present": True,
        "concept_present": True,
        "concept_lookup_failed": False,
        "skill_ids": [_SKILL],
        "skill_lookup_failed": False,
        "theta": _THETA,
        "theta_enabled": True,
        "grade": 11,
        "student_answer": _ANSWER,
        "solution_steps": ["x+1=3", "x=2"],
        "hypotheses": [_HYP],
        "server_mastery": _MASTERY,
        "client_mastery_supplied": False,
        "mastery_enabled": True,
        "pack": pack,
        "pack_enabled": True,
    }
    kwargs.update(over)
    resolved = build_tutor_context_manifest(**kwargs)
    slot_, path_ = TutorContextSlot, TutorDeliveryPath
    paths = {
        slot_.LEARNER_STATE: [path_.PRIVATE_TOOL],
        slot_.CONCEPT: [path_.PROMPT],
        slot_.SKILL: [path_.PROMPT],
        slot_.PROBLEM: [path_.PROMPT],
        slot_.STUDENT_ANSWER: [path_.PRIVATE_TOOL],
        slot_.SOLUTION_RECORD: [path_.PRIVATE_TOOL],
        slot_.MISCONCEPTION: [path_.PROMPT, path_.PRIVATE_TOOL],
        slot_.PEDAGOGY_POLICY: [path_.PROMPT],
    }
    # 못 얻은 슬롯은 전달 경로를 줄 수 없다(판정 불일치 WARNING 회피).
    live = {slot: p for slot, p in paths.items() if resolved.status_of(slot).resolved}
    return resolved.with_delivery(tutor_invoked=True, paths=live)


# ──────────────────────────────────────────────────────────────────────────
# 가짜 Langfuse — 쓰기(create_event)와 읽기(fetch_observations name 필터)를 같은 저장소로
# ──────────────────────────────────────────────────────────────────────────
class _Obs:
    def __init__(self, name: str, metadata: dict[str, object]) -> None:
        self.name = name
        self.metadata = metadata


class _Page:
    def __init__(self, data: list[_Obs]) -> None:
        self.data = data


class _FakeLangfuse:
    """실제 Langfuse처럼 이벤트를 이름과 함께 저장하고, 조회는 `name`으로 거른다."""

    def __init__(self) -> None:
        self.events: list[_Obs] = []

    def create_event(
        self, *, name: str, metadata: dict[str, object] | None = None, level: str | None = None
    ) -> Any:
        self.events.append(_Obs(name, dict(metadata or {})))
        return object()

    def fetch_observations(self, **kwargs: Any) -> _Page:
        name = kwargs["name"]
        page, limit = int(kwargs["page"]), int(kwargs["limit"])
        hits = [e for e in self.events if e.name == name]
        return _Page(hits[(page - 1) * limit : page * limit])


def _routing(cost_tier: str, cost_krw: float, tokens: int) -> dict[str, object]:
    return {
        "cost_tier": cost_tier,
        "local_family": "math" if cost_tier == "local" else None,
        "cache_hit": False,
        "input_tokens": tokens,
        "output_tokens": tokens // 2,
        "cost_krw": cost_krw,
        "latency_ms": 120,
    }


def _report(fake: _FakeLangfuse) -> cost_report.CostReport:
    events = cost_report.fetch_l3_events(
        client=fake,
        settings=Settings(langfuse_public_key="pk", langfuse_secret_key=SecretStr("sk")),
        now=datetime(2026, 10, 26, tzinfo=timezone.utc),
    )
    return cost_report.aggregate_l3_events(events)


# ──────────────────────────────────────────────────────────────────────────
# ② 이벤트명 분리 — cost_report 집계 무변화(대조군 포함)
# ──────────────────────────────────────────────────────────────────────────
def test_event_name_differs_from_cost_report_query_key() -> None:
    assert TUTOR_CONTEXT_EVENT_NAME == "tutor_context"
    assert TUTOR_CONTEXT_EVENT_NAME != langfuse_sink._EVENT_NAME
    assert TUTOR_CONTEXT_EVENT_NAME != cost_report._L3_EVENT_NAME


def test_tutor_context_events_leave_cost_report_unchanged() -> None:
    fake = _FakeLangfuse()
    sink = LangfuseSink(client=fake, traffic_surface=TrafficSurface.SERVING)
    sink.record(_routing("local", 0.0, 400))
    sink.record(_routing("cloud_mid", 3.2, 900))
    before = _report(fake)
    assert before.event_count == 2

    for seat in ("coach.create_session", "coach.append_turns", "coach.append_turns"):
        assert record_tutor_context(sink, _manifest(), seat=seat) is True

    # 튜터 context 이벤트는 실제로 Langfuse에 들어갔다(기록 0이라 무변화인 게 아니다).
    assert [e.name for e in fake.events].count(TUTOR_CONTEXT_EVENT_NAME) == 3
    assert _report(fake) == before


def test_control_same_payload_as_l3_routing_would_change_cost_report() -> None:
    """대조군 — 같은 내용을 `record()`(= l3_routing)로 보내면 집계가 바뀐다(필터에 변별력이 있다)."""
    fake = _FakeLangfuse()
    sink = LangfuseSink(client=fake)
    sink.record(_routing("local", 0.0, 400))
    before = _report(fake)
    sink.record(tutor_context_trace_fields(_manifest(), seat="coach.create_session"))
    after = _report(fake)
    assert after.event_count == before.event_count + 1
    assert after != before


def test_record_event_refuses_l3_routing_name(caplog: pytest.LogCaptureFixture) -> None:
    fake = _FakeLangfuse()
    sink = LangfuseSink(client=fake)
    with caplog.at_level(logging.WARNING, logger="whymath.l3.trace"):
        sink.record_event(langfuse_sink._EVENT_NAME, {"x": 1})
        sink.record_event("", {"x": 1})
        sink.record_event("   ", {"x": 1})
    assert fake.events == []
    assert sum("record_event 거부" in r.getMessage() for r in caplog.records) == 3


# ──────────────────────────────────────────────────────────────────────────
# ① 값 0 — 직렬화 결과에 학생 데이터·식별자 없음
# ──────────────────────────────────────────────────────────────────────────
def test_fields_carry_names_and_judgements_but_no_values() -> None:
    fields = tutor_context_trace_fields(_manifest(), seat="coach.create_session")
    assert set(fields) == {
        "seat",
        "tutor_invoked",
        "complete",
        "slots",
        "context_missing",
        "context_not_delivered",
        "context_coverage_gap",
        "context_prompt",
        "context_held_privately",
        "fallback_reason",
        "required_missing",
    }
    slots = fields["slots"]
    assert isinstance(slots, list) and len(slots) == 9
    assert [s["slot"] for s in slots] == [s.value for s in TutorContextSlot]
    for s in slots:
        assert set(s) == {
            "slot",
            "resolved",
            "delivered_to_tutor",
            "delivery_paths",
            "size",
            "cause",
        }
    blob = json.dumps(fields, ensure_ascii=False)
    for leaked in (str(_THETA), str(_MASTERY), _SKILL, _ANSWER, "x+1=3", "distribution-over-power"):
        assert leaked not in blob, leaked


def test_fields_match_manifest_judgement_and_absence_causes() -> None:
    manifest = _manifest(theta=None, theta_enabled=False, grade=None, skill_ids=[])
    fields = tutor_context_trace_fields(manifest, seat="coach.append_turns")
    by_slot = {s["slot"]: s for s in fields["slots"]}  # type: ignore[union-attr]
    assert by_slot["learner_state"]["resolved"] is False
    assert by_slot["learner_state"]["cause"] == "source_disabled"
    assert by_slot["learner_state"]["delivery_paths"] == []
    assert by_slot["concept"]["delivery_paths"] == ["prompt"]
    assert by_slot["misconception"]["delivery_paths"] == ["prompt", "private_tool"]
    assert by_slot["student_answer"]["size"] is None  # 답안 길이는 노출하지 않는다
    assert fields["complete"] is False and fields["tutor_invoked"] is True
    assert fields["seat"] == "coach.append_turns"


def test_dual_accounting_names_equal_observation_record_fields() -> None:
    """이중 회계 — Langfuse 이벤트의 이름 목록 = 관측 레코드(`context_*`) 필드(같은 매니페스트)."""
    for manifest in (
        _manifest(),
        _manifest(theta=None, theta_enabled=False, skill_ids=[], pack=None),
        _manifest(concept_present=False, skill_ids=[], concept_lookup_failed=True),
    ):
        fields = tutor_context_trace_fields(manifest, seat="s")
        record = wh1_primary._context_record_fields(manifest)
        assert fields["context_missing"] == record["context_missing"]
        assert fields["context_not_delivered"] == record["context_not_delivered"]
        assert fields["context_coverage_gap"] == record["context_coverage_gap"]


# ──────────────────────────────────────────────────────────────────────────
# ③ never-break — 각 실패 원인별 픽스처(예외 0·타입명 WARNING)
# ──────────────────────────────────────────────────────────────────────────
def test_recording_sink_keeps_tutor_context_out_of_routing_records() -> None:
    sink = RecordingTraceSink()
    assert record_tutor_context(sink, _manifest(), seat="coach.create_session") is True
    assert sink.records == []
    ((name, fields),) = sink.named_events
    assert name == TUTOR_CONTEXT_EVENT_NAME and fields["seat"] == "coach.create_session"


def test_no_sink_records_nothing_and_logs_nothing(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG, logger=_CTX_LOGGER):
        assert record_tutor_context(None, _manifest(), seat="s") is False
    assert [r for r in caplog.records if r.name == _CTX_LOGGER] == []


class _RoutingOnlySink:
    """`record()`만 있는 싱크 — 이름 있는 이벤트를 못 받는다."""

    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def record(self, fields: dict[str, object]) -> None:
        self.records.append(fields)


def test_sink_without_named_events_is_skipped_loudly_and_never_falls_back_to_routing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sink = _RoutingOnlySink()
    with caplog.at_level(logging.WARNING, logger=_CTX_LOGGER):
        assert record_tutor_context(sink, _manifest(), seat="s") is False
    assert sink.records == []  # l3_routing으로 대신 보내지 않았다(비용 표본 보호)
    (line,) = [r for r in caplog.records if r.name == _CTX_LOGGER]
    assert line.levelno == logging.WARNING and "_RoutingOnlySink" in line.getMessage()


class _ExplodingSink:
    def record(self, fields: dict[str, object]) -> None:  # pragma: no cover — 불리면 안 된다
        raise AssertionError("record()로 보내면 안 된다")

    def record_event(self, name: str, fields: dict[str, object]) -> None:
        raise ConnectionResetError("langfuse down")


def test_sink_exception_is_swallowed_with_type_name(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=_CTX_LOGGER):
        assert record_tutor_context(_ExplodingSink(), _manifest(), seat="s") is False
    (line,) = [r for r in caplog.records if r.name == _CTX_LOGGER]
    assert "ConnectionResetError" in line.getMessage()
    assert "langfuse down" not in line.getMessage()  # 메시지(값)는 싣지 않는다


def test_field_build_exception_is_swallowed_with_type_name(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def _boom(manifest: TutorContextManifest, *, seat: str) -> dict[str, object]:
        raise KeyError("slot")

    monkeypatch.setattr(wh1_tutor_context, "tutor_context_trace_fields", _boom)
    sink = RecordingTraceSink()
    with caplog.at_level(logging.WARNING, logger=_CTX_LOGGER):
        assert record_tutor_context(sink, _manifest(), seat="s") is False
    assert sink.named_events == []
    assert any("KeyError" in r.getMessage() for r in caplog.records if r.name == _CTX_LOGGER)


def test_langfuse_client_failure_is_swallowed_by_sink(caplog: pytest.LogCaptureFixture) -> None:
    class _Down(_FakeLangfuse):
        def create_event(self, **kwargs: Any) -> Any:
            raise TimeoutError

    sink = LangfuseSink(client=_Down())
    with caplog.at_level(logging.WARNING, logger="whymath.l3.trace"):
        # 싱크 내부에서 삼킨다 — 호출부에는 '넘겼다(True)'로 보이고 실패는 sink 로그에 타입명으로 남는다.
        assert record_tutor_context(sink, _manifest(), seat="s") is True
    assert any("TimeoutError" in r.getMessage() for r in caplog.records)
