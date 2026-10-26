"""LangfuseSink 단위테스트 — 가짜 Langfuse 클라이언트 주입 (라이브 서비스 없음).

ollama.py(FakeOllamaClient)·redis_cache.py(FakeRedisClient) 단위테스트를 미러링한다.
실제 langfuse 라이브러리·네트워크에 의존하지 않는다 → CI hermetic.

검증 핵심(S3 위험 표면):
  - 설정 경로: 필드 dict → create_event(metadata/tags)에 라우팅 필드가 실린다
    (`student_id_hash` 패스스루 포함 — 원시 ID 생성·전송 안 함).
  - 미설정 경로: 키 없으면 영구 no-op — 클라이언트를 *만들지도* create_event를
    *부르지도* 않는다.
  - 오류 삼킴: create_event가 예외를 던져도 record()는 전파하지 않는다(생성 비차단).
  - 지연 생성: 클라이언트 미주입+설정 완비 시 첫 record()에서 1회 생성·재사용.

설계 정본: docs/architecture/03a_l3_router_design.md §F.2(Langfuse 필드 표).
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr

from whymath_backend.config import Settings
from whymath_backend.l3.trace import LangfuseSink
from whymath_backend.l3.trace.langfuse_sink import (
    _EVENT_NAME,
    _LangfuseClient,
    _to_metadata,
)


class FakeLangfuseClient:
    """가짜 langfuse 클라이언트 — create_event 호출 기록 + 선택적 예외.

    `_LangfuseClient` Protocol을 구조적으로 충족한다. 호출 인자(name·metadata·level)를
    기록해 매핑을 단정하고, `raises`로 전송 오류(인증·네트워크)를 모사한다.
    """

    def __init__(self, *, raises: Exception | None = None) -> None:
        self._raises = raises
        self.events: list[dict[str, Any]] = []

    def create_event(
        self,
        *,
        name: str,
        metadata: dict[str, object] | None = None,
        level: str | None = None,
    ) -> Any:
        self.events.append({"name": name, "metadata": metadata, "level": level})
        if self._raises is not None:
            raise self._raises
        return object()  # 이벤트 핸들 — 싱크는 사용하지 않음


def _configured_settings() -> Settings:
    """공개키·시크릿키가 채워진 Settings(전송 가능 상태) — 가짜 키(네트워크 안 탐)."""
    return Settings(
        langfuse_public_key="pk-test",
        langfuse_secret_key=SecretStr("sk-test"),
        langfuse_host="http://127.0.0.1:1",
    )


def _unconfigured_settings() -> Settings:
    """키가 빈 Settings(미설정 상태) — 영구 no-op이어야 한다."""
    return Settings(
        langfuse_public_key="",
        langfuse_secret_key=SecretStr(""),
    )


def _sample_fields(**overrides: object) -> dict[str, object]:
    """langfuse_fields()가 만드는 형태의 대표 결정 dict(03a §F.2)."""
    base: dict[str, object] = {
        "cost_tier": "local",
        "local_family": "math",
        "local_model": "fast",
        "mode": "sync",
        "est_latency_ms": 1010,
        "est_cost_krw": 0.0,
        "call_site": None,
        "cache_hit": False,
        "escalated_from": None,
        "student_id_hash": "abc123hash",
        "reason": "local/math/fast",
    }
    base.update(overrides)
    return base


# ──────────────────────────────────────────────────────────────────────────
# 설정 경로 — 필드 → create_event 매핑
# ──────────────────────────────────────────────────────────────────────────
class TestRecordConfigured:
    def test_record_calls_create_event_with_event_name(self) -> None:
        """설정·주입 클라이언트 → create_event가 l3_routing 이름으로 1회 호출된다."""
        client = FakeLangfuseClient()
        sink = LangfuseSink(client=client)
        sink.record(_sample_fields())
        assert len(client.events) == 1
        assert client.events[0]["name"] == _EVENT_NAME
        assert client.events[0]["level"] == "DEFAULT"

    def test_metadata_carries_all_routing_fields(self) -> None:
        """결정 필드 전부가 메타데이터에 보존된다(03a §F.2 표 전체)."""
        client = FakeLangfuseClient()
        sink = LangfuseSink(client=client)
        fields = _sample_fields()
        sink.record(fields)
        meta = client.events[0]["metadata"]
        # 원본 필드가 모두 메타데이터에 들어 있어야 한다.
        for key, value in fields.items():
            assert meta[key] == value

    def test_student_id_hash_passed_through_unchanged(self) -> None:
        """student_id_hash는 *이미 해시* — 그대로 통과(원시 ID 생성·전송 안 함)."""
        client = FakeLangfuseClient()
        sink = LangfuseSink(client=client)
        sink.record(_sample_fields(student_id_hash="deadbeef"))
        assert client.events[0]["metadata"]["student_id_hash"] == "deadbeef"

    def test_tags_synthesized_from_filterable_fields(self) -> None:
        """cost_tier·local_family·local_model·cache_hit이 tags 리스트로 합성된다."""
        client = FakeLangfuseClient()
        sink = LangfuseSink(client=client)
        sink.record(_sample_fields(cache_hit=True))
        tags = client.events[0]["metadata"]["tags"]
        assert "cost_tier:local" in tags
        assert "local_family:math" in tags
        assert "local_model:fast" in tags
        assert "cache_hit:True" in tags

    def test_none_valued_tag_fields_excluded(self) -> None:
        """클라우드처럼 local_family/local_model이 None이면 태그에서 빠진다."""
        client = FakeLangfuseClient()
        sink = LangfuseSink(client=client)
        sink.record(
            _sample_fields(
                cost_tier="cloud_mid",
                local_family=None,
                local_model=None,
            )
        )
        tags = client.events[0]["metadata"]["tags"]
        assert "cost_tier:cloud_mid" in tags
        # None 축은 태그에 'None' 문자열로 새어나오면 안 된다.
        assert not any(t.startswith("local_family:") for t in tags)
        assert not any(t.startswith("local_model:") for t in tags)

    def test_record_does_not_mutate_caller_dict(self) -> None:
        """record는 호출자 dict를 변형하지 않는다(메타데이터는 얕은 복사)."""
        client = FakeLangfuseClient()
        sink = LangfuseSink(client=client)
        fields = _sample_fields()
        sink.record(fields)
        assert "tags" not in fields  # 원본엔 tags가 추가되지 않아야 함

    def test_configured_settings_path_is_active(self) -> None:
        """키가 채워진 Settings를 주입하면 configured=True(주입 클라이언트 없이도)."""
        sink = LangfuseSink(settings=_configured_settings())
        assert sink.configured is True
        assert sink.enabled is True


# ──────────────────────────────────────────────────────────────────────────
# 미설정 경로 — 영구 no-op
# ──────────────────────────────────────────────────────────────────────────
class TestRecordUnconfigured:
    def test_unconfigured_is_noop(self) -> None:
        """키 미설정 Settings → record()는 아무것도 하지 않는다(예외도 없음)."""
        sink = LangfuseSink(settings=_unconfigured_settings())
        assert sink.configured is False
        # 예외 없이 조용히 통과해야 한다.
        sink.record(_sample_fields())

    def test_unconfigured_never_builds_client(self) -> None:
        """미설정 시 _get_client()가 None(클라이언트 생성 안 함)."""
        sink = LangfuseSink(settings=_unconfigured_settings())
        assert sink._get_client() is None

    def test_partial_keys_are_unconfigured(self) -> None:
        """공개키만/시크릿키만 있으면 미설정으로 본다(둘 다 필요)."""
        only_public = LangfuseSink(
            settings=Settings(
                langfuse_public_key="pk-test",
                langfuse_secret_key=SecretStr(""),
            )
        )
        only_secret = LangfuseSink(
            settings=Settings(
                langfuse_public_key="",
                langfuse_secret_key=SecretStr("sk-test"),
            )
        )
        assert only_public.configured is False
        assert only_secret.configured is False
        only_public.record(_sample_fields())  # no-op, 예외 없음
        only_secret.record(_sample_fields())  # no-op, 예외 없음


# ──────────────────────────────────────────────────────────────────────────
# 오류 삼킴 — 관측성 장애가 생성을 깨지 않는다 (CLAUDE.md 우선순위 #1 ≫ #6)
# ──────────────────────────────────────────────────────────────────────────
class TestRecordSwallowsErrors:
    def test_create_event_exception_is_swallowed(self) -> None:
        """create_event가 던지는 예외는 record()를 통과해 전파되지 않는다."""
        client = FakeLangfuseClient(raises=RuntimeError("langfuse down"))
        sink = LangfuseSink(client=client)
        # 예외가 새어나오면 이 테스트가 실패한다(생성 비차단 보장).
        sink.record(_sample_fields())
        assert len(client.events) == 1  # 호출은 시도됐다

    def test_various_exception_types_all_swallowed(self) -> None:
        """네트워크·인증 등 어떤 예외 타입도 삼킨다(생성 절대 미차단)."""
        for exc in (
            ConnectionError("network"),
            ValueError("bad payload"),
            KeyError("missing"),
        ):
            client = FakeLangfuseClient(raises=exc)
            sink = LangfuseSink(client=client)
            sink.record(_sample_fields())  # 어느 것도 전파되면 안 됨

    def test_error_swallow_logs_warning_without_secrets(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """오류 삼킴 시 경고 로그를 남기되 시크릿·필드값은 남기지 않는다."""
        import logging

        client = FakeLangfuseClient(raises=RuntimeError("boom"))
        sink = LangfuseSink(client=client)
        with caplog.at_level(logging.WARNING, logger="whymath.l3.trace"):
            sink.record(_sample_fields(student_id_hash="secret-ish-hash"))
        # 경고는 남되, 메시지에 student_id_hash 값이 새어나오지 않아야 한다.
        assert any("Langfuse 기록 실패" in r.message for r in caplog.records)
        assert all("secret-ish-hash" not in r.message for r in caplog.records)


# ──────────────────────────────────────────────────────────────────────────
# 지연 생성 — 설정 완비 시 첫 record에서 1회 생성·재사용
# ──────────────────────────────────────────────────────────────────────────
class TestLazyConstruction:
    def test_default_client_built_lazily_from_settings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """클라이언트 미주입 + 설정 완비 → 첫 _get_client에서 기본 클라이언트 1회 생성.

        실제 langfuse.Langfuse 대신 가짜 빌더를 monkeypatch해 라이브러리·네트워크를
        타지 않는다(생성자 자체는 네트워크를 안 타지만, CI 안정성을 위해 더블로 대체).
        """
        built: list[Settings] = []

        def _fake_builder(settings: Settings) -> _LangfuseClient:
            built.append(settings)
            return FakeLangfuseClient()

        monkeypatch.setattr(
            "whymath_backend.l3.trace.langfuse_sink._build_default_client",
            _fake_builder,
        )
        sink = LangfuseSink(settings=_configured_settings())
        client1 = sink._get_client()
        client2 = sink._get_client()
        assert client1 is not None
        assert client1 is client2  # 지연 1회 생성·재사용
        assert len(built) == 1  # 빌더는 한 번만 불린다

    def test_construction_does_not_require_keys_or_network(self) -> None:
        """LangfuseSink() 생성만으로는 키·네트워크가 필요 없다(전역 설정 폴백)."""
        from whymath_backend.config import get_settings

        get_settings.cache_clear()
        sink = LangfuseSink()  # 인자 없음 — 전역 Settings로 폴백
        # configured는 환경에 따라 다르나, 생성 자체는 예외 없이 끝나야 한다.
        assert isinstance(sink.configured, bool)

    def test_resolved_settings_falls_back_to_global(self) -> None:
        """settings 미주입 시 전역 get_settings()로 폴백한다."""
        from whymath_backend.config import Settings as _S  # noqa: N814
        from whymath_backend.config import get_settings

        get_settings.cache_clear()
        sink = LangfuseSink()
        assert isinstance(sink._resolved_settings, _S)

    def test_build_default_client_constructs_real_langfuse(self) -> None:
        """_build_default_client가 실제 langfuse.Langfuse를 생성한다(시임 충족·cast 경로).

        ollama.py가 실제 AsyncClient를, redis_cache.py가 실제 Redis를 생성해 기본 경로를
        커버한 것을 미러링한다. langfuse 생성자는 네트워크를 *동기로* 타지 않으므로(전송은
        백그라운드 배치) 라이브 서버 없이 안전하다. 도달 불가 호스트를 주고, 생성 직후
        shutdown()으로 백그라운드 익스포터를 멈춰 잔여 스레드·네트워크 시도를 막는다.
        """
        from whymath_backend.l3.trace.langfuse_sink import _build_default_client

        settings = Settings(
            langfuse_public_key="pk-test",
            langfuse_secret_key=SecretStr("sk-test"),
            langfuse_host="http://127.0.0.1:1",  # 도달 불가 — 전송 시도 차단
        )
        client = _build_default_client(settings)
        # 우리의 좁은 구조적 시임을 런타임에 충족해야 한다(create_event 보유).
        assert isinstance(client, _LangfuseClient)
        # 백그라운드 익스포터 스레드를 즉시 정리(잔여·재시도 로그 방지).
        shutdown = getattr(client, "shutdown", None)
        if callable(shutdown):
            shutdown()

    def test_injected_client_makes_configured_true_regardless_of_keys(self) -> None:
        """주입 클라이언트가 있으면 키 미설정이어도 configured=True(DI 우선)."""
        sink = LangfuseSink(
            client=FakeLangfuseClient(),
            settings=_unconfigured_settings(),
        )
        assert sink.configured is True
        sink.record(_sample_fields())  # 주입 클라이언트로 전송 시도


# ──────────────────────────────────────────────────────────────────────────
# 메타데이터 변환 헬퍼 + Protocol 위생
# ──────────────────────────────────────────────────────────────────────────
class TestToMetadata:
    def test_preserves_all_keys(self) -> None:
        fields = _sample_fields()
        meta = _to_metadata(fields)
        for key in fields:
            assert key in meta

    def test_adds_tags_list(self) -> None:
        meta = _to_metadata(_sample_fields())
        assert isinstance(meta["tags"], list)

    def test_returns_new_dict(self) -> None:
        """원본 dict와 다른 객체를 돌려준다(호출자 불변)."""
        fields = _sample_fields()
        meta = _to_metadata(fields)
        assert meta is not fields

    def test_no_tags_key_when_all_tag_fields_none(self) -> None:
        """태그 후보가 전부 None이면 'tags' 키 자체를 넣지 않는다(빈 리스트 미부착).

        모든 _TAG_FIELDS(cost_tier·local_family·local_model·cache_hit)가 None인 비정상
        입력에서도 깨지지 않고, tags를 *생략*한다(if tags 거짓 분기 — 123->125 커버).
        """
        empty = {
            "cost_tier": None,
            "local_family": None,
            "local_model": None,
            "cache_hit": None,
            "reason": "edge",
        }
        meta = _to_metadata(empty)
        assert "tags" not in meta
        assert meta["reason"] == "edge"  # 비태그 필드는 그대로 보존


def test_satisfies_trace_sink_protocol() -> None:
    """LangfuseSink는 TraceSink Protocol을 충족한다(runtime_checkable)."""
    from whymath_backend.l3.interfaces import TraceSink

    assert isinstance(LangfuseSink(client=FakeLangfuseClient()), TraceSink)


def test_fake_client_satisfies_seam_protocol() -> None:
    """가짜 클라이언트가 _LangfuseClient 시임을 구조적으로 충족하는지 확인(테스트 위생)."""
    assert isinstance(FakeLangfuseClient(), _LangfuseClient)


# ──────────────────────────────────────────────────────────────────────────
# SDK 버전 적응 쓰기 — langfuse v2(create_event 부재)는 event()로 기록 (2026-07-16 실측)
# ──────────────────────────────────────────────────────────────────────────
class FakeLangfuseV2Client:
    """v2형 가짜 — create_event가 *없다*(실측 2.60.10 표면). 쓰기는 event(name=, metadata=).

    종전 sink는 create_event 고정 호출이라 v2에서 매 record가 AttributeError로 전멸했다
    (Phaiakes9 실측·침묵 실패). 이 가짜가 v2 폴백 경로를 동결한다.
    """

    def __init__(self, *, raises: Exception | None = None) -> None:
        self._raises = raises
        self.events: list[dict[str, Any]] = []

    def event(self, *, name: str, metadata: dict[str, object] | None = None) -> Any:
        self.events.append({"name": name, "metadata": metadata})
        if self._raises is not None:
            raise self._raises
        return object()


class TestV2CompatWrite:
    def test_v2_client_records_via_event(self) -> None:
        """create_event 부재(v2) → event()로 기록된다(이름·메타데이터 동일)."""
        client = FakeLangfuseV2Client()
        sink = LangfuseSink(client=client)  # type: ignore[arg-type] — v2 표면 의도적 주입
        fields = _sample_fields()
        sink.record(fields)
        assert len(client.events) == 1
        assert client.events[0]["name"] == _EVENT_NAME
        assert client.events[0]["metadata"] == _to_metadata(fields)

    def test_v2_event_exception_still_swallowed(self) -> None:
        """v2 폴백 경로의 예외도 동일하게 삼킨다(생성 비차단 방침 불변)."""
        client = FakeLangfuseV2Client(raises=ConnectionError("network"))
        sink = LangfuseSink(client=client)  # type: ignore[arg-type]
        sink.record(_sample_fields())  # 전파되면 실패
        assert len(client.events) == 1

    def test_v3_client_still_uses_create_event(self) -> None:
        """create_event가 있으면(v3/v4·기존 가짜) 그 경로를 유지한다(회귀 방지)."""
        client = FakeLangfuseClient()
        sink = LangfuseSink(client=client)
        sink.record(_sample_fields())
        assert len(client.events) == 1
        assert client.events[0]["level"] == "DEFAULT"  # create_event 전용 인자 통과 확인

    def test_warning_includes_exception_type_name(self, caplog: pytest.LogCaptureFixture) -> None:
        """실패 경고에 예외 타입명이 실린다 — v2 전멸 같은 침묵 실패의 재발 방지.

        종전 무타입 경고("기록 실패")는 AttributeError 전멸을 무증상으로 만들었다.
        타입명은 시크릿·필드값이 아니므로 로그 안전(시크릿 0 방침 유지).
        """
        import logging

        client = FakeLangfuseClient(raises=RuntimeError("boom"))
        sink = LangfuseSink(client=client)
        with caplog.at_level(logging.WARNING, logger="whymath.l3.trace"):
            sink.record(_sample_fields())
        assert any("RuntimeError" in r.getMessage() for r in caplog.records)


# ──────────────────────────────────────────────────────────────────────────
# P3-73 — record_event(이벤트명 인자): 비용 표본(l3_routing) 밖으로 기록을 보내는 길
# ──────────────────────────────────────────────────────────────────────────
class TestRecordEvent:
    def test_uses_given_name_with_same_metadata_mapping(self) -> None:
        client = FakeLangfuseClient()
        sink = LangfuseSink(client=client)
        fields = {"seat": "coach.create_session", "complete": True}
        sink.record_event("tutor_context", fields)
        assert client.events == [
            {"name": "tutor_context", "metadata": _to_metadata(fields), "level": "DEFAULT"}
        ]

    def test_record_keeps_l3_routing_name(self) -> None:
        """대조군 — `record()`는 여전히 `l3_routing`이다(이벤트명 인자화가 기존 경로를 바꾸지 않음)."""
        client = FakeLangfuseClient()
        LangfuseSink(client=client).record(_sample_fields())
        assert [e["name"] for e in client.events] == [_EVENT_NAME] == ["l3_routing"]

    def test_v2_fallback_uses_given_name(self) -> None:
        client = FakeLangfuseV2Client()
        sink = LangfuseSink(client=client)  # type: ignore[arg-type]
        sink.record_event("tutor_context", {"seat": "s"})
        assert client.events[0]["name"] == "tutor_context"

    def test_unconfigured_is_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        built: list[object] = []
        monkeypatch.setattr(
            "whymath_backend.l3.trace.langfuse_sink._build_default_client",
            lambda settings: built.append(settings),
        )
        LangfuseSink(settings=_unconfigured_settings()).record_event("tutor_context", {"a": 1})
        assert built == []

    def test_traffic_surface_is_attached(self) -> None:
        from whymath_backend.l3.interfaces import TrafficSurface

        client = FakeLangfuseClient()
        sink = LangfuseSink(client=client, traffic_surface=TrafficSurface.SERVING)
        sink.record_event("tutor_context", {"seat": "s"})
        meta = client.events[0]["metadata"]
        assert meta["traffic_surface"] == "serving"
        assert "traffic_surface:serving" in meta["tags"]

    def test_client_error_swallowed_with_type_name(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        sink = LangfuseSink(client=FakeLangfuseClient(raises=ConnectionError("x")))
        with caplog.at_level(logging.WARNING, logger="whymath.l3.trace"):
            sink.record_event("tutor_context", {"seat": "s"})
        assert any("ConnectionError" in r.getMessage() for r in caplog.records)

    @pytest.mark.parametrize("name", ["l3_routing", "", "  "])
    def test_refuses_routing_or_blank_name(self, name: str) -> None:
        client = FakeLangfuseClient()
        LangfuseSink(client=client).record_event(name, {"cost_tier": "local"})
        assert client.events == []

    def test_sink_satisfies_named_event_protocol(self) -> None:
        from whymath_backend.l3.interfaces import NamedEventSink

        assert isinstance(LangfuseSink(client=FakeLangfuseClient()), NamedEventSink)


class TestSurfaceTaggingNamedEvent:
    def test_delegates_with_surface_when_inner_supports_named_events(self) -> None:
        from whymath_backend.l3.interfaces import (
            RecordingTraceSink,
            SurfaceTaggingTraceSink,
            TrafficSurface,
        )

        inner = RecordingTraceSink()
        SurfaceTaggingTraceSink(inner, TrafficSurface.AUTHORING).record_event("tutor_context", {})
        assert inner.records == []
        assert inner.named_events == [("tutor_context", {"traffic_surface": "authoring"})]

    def test_inner_without_named_events_records_nothing(self) -> None:
        from whymath_backend.l3.interfaces import SurfaceTaggingTraceSink, TrafficSurface

        class _RoutingOnly:
            def __init__(self) -> None:
                self.records: list[dict[str, object]] = []

            def record(self, fields: dict[str, object]) -> None:
                self.records.append(fields)

        inner = _RoutingOnly()
        SurfaceTaggingTraceSink(inner, TrafficSurface.AUTHORING).record_event("tutor_context", {})
        assert inner.records == []  # l3_routing으로 새지 않는다
