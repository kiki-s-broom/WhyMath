"""trace 표면 표지(`traffic_surface`) — 어휘·표지 규칙·싱크·결선 지점 테스트 (OPS-105 ②).

이 테스트가 지키는 것
---------------------
게이트②(학생 대면 루프당 비용)는 서빙·저작·프로브 트래픽이 같은 `l3_routing` 스트림에 섞이면 위장된다.
표지가 **붙는 지점**과 **붙는 규칙**이 어긋나면 그 위장이 조용히 돌아온다. 그래서

  1. 어휘를 동결한다(값이 바뀌면 소비측 `cost_report` 가 표지를 못 읽는다).
  2. **먼저 실린 표지가 이긴다** — 저작 래퍼가 단 표지를 바깥 서빙 기본 싱크가 덮으면 오프라인 배치가
     학생 대면 표본으로 돌아온다. 이 규칙의 정반대(나중에 실린 것이 이김)를 주입해 RED 를 확인한다.
  3. 표지를 싣는 **세 결선 지점**(앱 기본 싱크=서빙 · 프리플라이트/비용 프로브=프로브 · 저작)을 직접
     확인한다 — 어휘가 맞아도 호출 경로가 싣지 않으면 표지는 없는 것과 같다.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr

from whymath_backend.config import Settings
from whymath_backend.l3.interfaces import (
    TRAFFIC_SURFACE_FIELD,
    RecordingTraceSink,
    SurfaceTaggingTraceSink,
    TrafficSurface,
    with_traffic_surface,
)
from whymath_backend.l3.trace.langfuse_sink import LangfuseSink


class _FakeClient:
    """가짜 Langfuse 클라이언트 — create_event 의 metadata 를 기록한다."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def create_event(
        self,
        *,
        name: str,
        metadata: dict[str, object] | None = None,
        level: str | None = None,
    ) -> Any:
        self.events.append({"name": name, "metadata": metadata, "level": level})
        return object()


class _FlushingSink:
    """flush 를 노출하는 싱크 — 위임 여부를 센다."""

    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []
        self.flushes = 0

    def record(self, fields: dict[str, object]) -> None:
        self.records.append(fields)

    def flush(self) -> None:
        self.flushes += 1


def _fields() -> dict[str, object]:
    return {"cost_tier": "local", "call_site": "extract", "cache_hit": False}


class TestVocabulary:
    def test_values_are_frozen(self) -> None:
        """값이 바뀌면 `cost_report` 가 표지를 읽지 못한다 — 어휘 변경은 소비측과 함께 PR 로."""
        assert {s.value for s in TrafficSurface} == {"serving", "authoring", "probe"}
        assert TRAFFIC_SURFACE_FIELD == "traffic_surface"

    def test_surfaces_are_mutually_exclusive_strings(self) -> None:
        """한 필드에 한 값 — 불리언 둘이 동시에 참인 불가능한 상태가 구조적으로 없다."""
        assert all(isinstance(s.value, str) for s in TrafficSurface)
        assert len({s.value for s in TrafficSurface}) == len(TrafficSurface)


class TestWithTrafficSurface:
    def test_adds_the_tag_and_keeps_every_field(self) -> None:
        out = with_traffic_surface(_fields(), TrafficSurface.SERVING)
        assert out[TRAFFIC_SURFACE_FIELD] == "serving"
        assert {k: v for k, v in out.items() if k != TRAFFIC_SURFACE_FIELD} == _fields()

    def test_does_not_mutate_the_callers_dict(self) -> None:
        original = _fields()
        with_traffic_surface(original, TrafficSurface.PROBE)
        assert TRAFFIC_SURFACE_FIELD not in original

    def test_first_tag_wins(self) -> None:
        """먼저 실린 표지가 이긴다 — 안쪽 싱크의 기본값이 출처의 표지를 덮지 않는다."""
        tagged = {**_fields(), TRAFFIC_SURFACE_FIELD: "authoring"}
        out = with_traffic_surface(tagged, TrafficSurface.SERVING)
        assert out[TRAFFIC_SURFACE_FIELD] == "authoring"

    def test_returns_a_copy_even_when_already_tagged(self) -> None:
        tagged = {**_fields(), TRAFFIC_SURFACE_FIELD: "probe"}
        assert with_traffic_surface(tagged, TrafficSurface.SERVING) is not tagged


class TestSurfaceTaggingTraceSink:
    def test_record_tags_the_inner_sink(self) -> None:
        inner = RecordingTraceSink()
        SurfaceTaggingTraceSink(inner, TrafficSurface.AUTHORING).record(_fields())
        assert inner.records == [{**_fields(), TRAFFIC_SURFACE_FIELD: "authoring"}]

    def test_flush_delegates_when_the_inner_exposes_it(self) -> None:
        inner = _FlushingSink()
        SurfaceTaggingTraceSink(inner, TrafficSurface.PROBE).flush()
        assert inner.flushes == 1

    def test_flush_is_a_noop_when_the_inner_has_none(self) -> None:
        SurfaceTaggingTraceSink(RecordingTraceSink(), TrafficSurface.PROBE).flush()  # 예외 없음

    def test_outer_authoring_wrapper_beats_an_inner_serving_default(self) -> None:
        """저작 래퍼(출처에 가까움)가 서빙 기본 싱크(바깥 기본값) 위에 얹혀도 저작 표지가 남는다.

        이 규칙을 '나중에 실린 것이 이긴다'로 뒤집으면 오프라인 저작 배치가 서빙 표본으로 돌아온다.
        """
        recording = RecordingTraceSink()
        serving_default = SurfaceTaggingTraceSink(recording, TrafficSurface.SERVING)
        SurfaceTaggingTraceSink(serving_default, TrafficSurface.AUTHORING).record(_fields())
        assert recording.records[0][TRAFFIC_SURFACE_FIELD] == "authoring"

    def test_surface_property(self) -> None:
        sink = SurfaceTaggingTraceSink(RecordingTraceSink(), TrafficSurface.PROBE)
        assert sink.surface is TrafficSurface.PROBE


class TestLangfuseSinkSurface:
    def test_tag_is_carried_in_metadata_and_in_filter_tags(self) -> None:
        client = _FakeClient()
        sink = LangfuseSink(client=client, traffic_surface=TrafficSurface.PROBE)
        sink.record(_fields())
        metadata = client.events[0]["metadata"]
        assert metadata[TRAFFIC_SURFACE_FIELD] == "probe"
        assert "traffic_surface:probe" in metadata["tags"]  # Langfuse UI 필터용

    def test_sink_without_a_surface_adds_no_tag(self) -> None:
        """기본(None)은 기존 호출부와 비트동일 — 표지도 UI 태그도 없다."""
        client = _FakeClient()
        LangfuseSink(client=client).record(_fields())
        metadata = client.events[0]["metadata"]
        assert TRAFFIC_SURFACE_FIELD not in metadata
        assert not any(str(t).startswith("traffic_surface:") for t in metadata.get("tags", []))

    def test_an_already_tagged_record_is_not_overwritten_by_the_sinks_default(self) -> None:
        client = _FakeClient()
        sink = LangfuseSink(client=client, traffic_surface=TrafficSurface.SERVING)
        sink.record({**_fields(), TRAFFIC_SURFACE_FIELD: "authoring"})
        assert client.events[0]["metadata"][TRAFFIC_SURFACE_FIELD] == "authoring"

    def test_record_does_not_mutate_the_callers_dict(self) -> None:
        client = _FakeClient()
        original = _fields()
        LangfuseSink(client=client, traffic_surface=TrafficSurface.SERVING).record(original)
        assert TRAFFIC_SURFACE_FIELD not in original

    def test_traffic_surface_property(self) -> None:
        assert LangfuseSink(traffic_surface=TrafficSurface.SERVING).traffic_surface is (
            TrafficSurface.SERVING
        )
        assert LangfuseSink().traffic_surface is None

    def test_unconfigured_sink_stays_a_noop(self) -> None:
        """표지를 달아도 미설정 싱크는 여전히 영구 no-op 이다(키 없는 CI 에서 예외·전송 없음)."""
        settings = Settings(langfuse_public_key="", langfuse_secret_key=SecretStr(""))
        LangfuseSink(settings=settings, traffic_surface=TrafficSurface.SERVING).record(_fields())


class TestStampPoints:
    """표지를 싣는 결선 지점 — 어휘가 맞아도 호출 경로가 싣지 않으면 표지는 없는 것과 같다."""

    def test_app_default_sink_stamps_serving(self) -> None:
        from whymath_backend.app import _TRACE_KEY, create_app

        sink = getattr(create_app().state, _TRACE_KEY)
        assert isinstance(sink, LangfuseSink)
        assert sink.traffic_surface is TrafficSurface.SERVING

    def test_injected_app_sink_is_left_alone(self) -> None:
        """주입된 싱크는 호출자가 표면을 책임진다 — 앱이 덧씌우지 않는다."""
        from whymath_backend.app import _TRACE_KEY, create_app

        injected = RecordingTraceSink()
        assert getattr(create_app(trace=injected).state, _TRACE_KEY) is injected

    def test_live_preflight_default_sink_stamps_probe(self) -> None:
        from whymath_backend.ops import live_preflight

        deps = live_preflight._default_pipeline_deps(Settings())
        inner = deps.trace._inner  # _CapturingTraceSink 가 감싼 실전송 싱크
        assert isinstance(inner, LangfuseSink)
        assert inner.traffic_surface is TrafficSurface.PROBE

    def test_live_preflight_capture_keeps_the_record_as_the_pipeline_made_it(self) -> None:
        """갈무리는 표지 이전 그대로다 — 프리플라이트가 읽는 필드 모양이 바뀌지 않는다."""
        from whymath_backend.ops import live_preflight

        deps = live_preflight._default_pipeline_deps(Settings())
        deps.trace.record(_fields())
        assert deps.trace.records == [_fields()]

    def test_cost_probe_default_sink_stamps_probe(self) -> None:
        from whymath_backend.ops import cost_probe

        deps = cost_probe._default_probe_deps(Settings())
        assert isinstance(deps.trace, LangfuseSink)
        assert deps.trace.traffic_surface is TrafficSurface.PROBE

    def test_authoring_alias_matches_the_vocabulary(self) -> None:
        from whymath_backend.l3.equivalent.rephrase import AUTHORING_TRAFFIC_SURFACE

        assert AUTHORING_TRAFFIC_SURFACE == TrafficSurface.AUTHORING.value

    @pytest.mark.parametrize("surface", list(TrafficSurface))
    def test_every_surface_round_trips_through_the_sink(self, surface: TrafficSurface) -> None:
        client = _FakeClient()
        LangfuseSink(client=client, traffic_surface=surface).record(_fields())
        assert client.events[0]["metadata"][TRAFFIC_SURFACE_FIELD] == surface.value
