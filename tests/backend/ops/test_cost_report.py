"""cost_report 판독 hermetic 테스트 — 실 Langfuse·라이브 키 0.

순수 집계 코어(`aggregate_l3_events`·`_percentile`)를 고정 픽스처로 전수 검증하고,
fetch 어댑터(`fetch_l3_events`)는 가짜 read 클라이언트 주입으로 정규화·페이지네이션·
미설정 no-op·오류 삼킴을 단언한다. CLI(main)는 fetch/Settings를 대체해 렌더·JSON을 확인.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from whymath_backend.ops import cost_report as cr

# ──────────────────────────────────────────────────────────────────────────
# _percentile — 선형보간(numpy 기본) 정의를 손계산 기대값으로 고정.
# ──────────────────────────────────────────────────────────────────────────


def test_percentile_empty_and_single() -> None:
    assert cr._percentile([], 0.5) is None
    assert cr._percentile([42.0], 0.5) == 42.0
    assert cr._percentile([42.0], 0.9) == 42.0


def test_percentile_linear_interpolation() -> None:
    vals = [10.0, 20.0, 30.0, 40.0, 50.0]  # n=5
    assert cr._percentile(vals, 0.50) == 30.0  # rank=2.0 → 정확히 index2
    # p90: rank=0.9*4=3.6 → 40*0.4 + 50*0.6 = 46.0
    assert cr._percentile(vals, 0.90) == pytest.approx(46.0)


def test_percentile_even_count_midpoint() -> None:
    vals = [1.0, 2.0, 3.0, 4.0]  # n=4, rank=1.5 → 2.5
    assert cr._percentile(vals, 0.50) == pytest.approx(2.5)


# ──────────────────────────────────────────────────────────────────────────
# aggregate_l3_events — 대표 픽스처(로컬·클라우드·캐시히트 혼재).
# ──────────────────────────────────────────────────────────────────────────


def _sample_events() -> list[dict[str, object]]:
    """대표 5건 — 실측 토큰·비용·tier·cache_hit가 손계산 가능하게 배치."""
    return [
        {
            "cost_tier": "cloud_mid",
            "input_tokens": 100,
            "output_tokens": 50,
            "cost_krw": 0.42,
            "latency_ms": 1200,
            "cache_hit": False,
        },
        {
            "cost_tier": "cloud_high",
            "input_tokens": 200,
            "output_tokens": 150,
            "cost_krw": 1.5,
            "latency_ms": 3000,
            "cache_hit": False,
        },
        {
            "cost_tier": "local",
            "input_tokens": 80,
            "output_tokens": 40,
            "cost_krw": 0.0,
            "latency_ms": 300,
            "cache_hit": False,
        },
        {
            # 캐시 히트 — 실측 토큰·비용·지연이 전부 None(미상, 0 아님).
            "cost_tier": "local",
            "input_tokens": None,
            "output_tokens": None,
            "cost_krw": None,
            "latency_ms": None,
            "cache_hit": True,
        },
        {
            "cost_tier": "cloud_mid",
            "input_tokens": 120,
            "output_tokens": 60,
            "cost_krw": 0.5,
            "latency_ms": 1500,
            "cache_hit": False,
        },
    ]


def test_aggregate_distributions_exclude_none() -> None:
    report = cr.aggregate_l3_events(_sample_events())
    assert report.event_count == 5
    # input 표본 [80,100,120,200] (None 1건 제외) → p50 rank1.5 = 100*.5+120*.5 = 110
    assert report.input_tokens.count == 4
    assert report.input_tokens.p50 == pytest.approx(110.0)
    assert report.input_tokens.total == pytest.approx(500.0)
    # output 표본 [40,50,60,150] → p50 = 55
    assert report.output_tokens.p50 == pytest.approx(55.0)
    # cost 표본 [0.0,0.42,0.5,1.5] → p50 = 0.46
    assert report.cost_krw.count == 4
    assert report.cost_krw.p50 == pytest.approx(0.46)
    assert report.cost_krw.total == pytest.approx(2.42)


def test_aggregate_local_cloud_ratio_and_tiers() -> None:
    report = cr.aggregate_l3_events(_sample_events())
    assert report.local_count == 2  # local 2건
    assert report.cloud_count == 3  # cloud_mid 2 + cloud_high 1
    assert report.local_ratio == pytest.approx(0.4)
    assert report.cost_tier_counts == {"cloud_mid": 2, "cloud_high": 1, "local": 2}


def test_aggregate_cache_hit_rate() -> None:
    report = cr.aggregate_l3_events(_sample_events())
    assert report.cache_total == 5  # 전부 bool cache_hit 보유
    assert report.cache_hits == 1
    assert report.cache_hit_rate == pytest.approx(0.2)


def test_aggregate_tuning_suggestion_is_token_p50() -> None:
    report = cr.aggregate_l3_events(_sample_events())
    assert report.suggested_est_input_tokens == 110  # round(input p50)
    assert report.suggested_est_output_tokens == 55  # round(output p50)


def test_aggregate_small_sample_note() -> None:
    report = cr.aggregate_l3_events(_sample_events())
    # 실측 토큰 표본 4건(<20) → 잠정치 경고 note.
    assert any("잠정치" in n for n in report.notes)


# ── 엣지 케이스 ──────────────────────────────────────────────────────────


def test_aggregate_empty() -> None:
    report = cr.aggregate_l3_events([])
    assert report.event_count == 0
    assert report.input_tokens.count == 0
    assert report.input_tokens.p50 is None
    assert report.local_ratio is None
    assert report.cache_hit_rate is None
    assert report.suggested_est_input_tokens is None
    assert report.content_source_counts == {}  # 공급 경로도 미상(0으로 위장하지 않음)
    assert report.notes == []  # 이벤트 0이면 경고도 없다(빈 입력은 정보).


# ── content_source(공급 경로·03c §4) ─────────────────────────────────────


def test_aggregate_content_source_counts() -> None:
    """공급 경로 값별 카운트 — cost_tier 버킷과 동형."""
    events: list[dict[str, object]] = [
        {"cost_tier": "local", "content_source": "dsl_render"},
        {"cost_tier": "local", "content_source": "dsl_render"},
        {"cost_tier": "local", "content_source": "prompt_cache"},
        {"cost_tier": "cloud_mid", "content_source": "generate"},
    ]
    report = cr.aggregate_l3_events(events)
    assert report.content_source_counts == {
        "dsl_render": 2,
        "prompt_cache": 1,
        "generate": 1,
    }


def test_aggregate_ignores_missing_content_source() -> None:
    """구 이벤트엔 키가 없다 — 분모에 넣지 않는다(없음을 특정 경로로 몰지 않음)."""
    events: list[dict[str, object]] = [
        {"cost_tier": "local"},  # 키 없음
        {"cost_tier": "local", "content_source": "generate"},
        {"cost_tier": "local", "content_source": None},  # str 아님 → 미집계
    ]
    report = cr.aggregate_l3_events(events)
    assert report.content_source_counts == {"generate": 1}


def test_aggregate_local_only_zero_cost() -> None:
    events: list[dict[str, object]] = [
        {"cost_tier": "local", "input_tokens": 90, "output_tokens": 45, "cost_krw": 0.0},
        {"cost_tier": "local", "input_tokens": 110, "output_tokens": 55, "cost_krw": 0.0},
    ]
    report = cr.aggregate_l3_events(events)
    assert report.local_ratio == pytest.approx(1.0)  # 100% 로컬
    assert report.cloud_count == 0
    assert report.cost_krw.total == pytest.approx(0.0)  # 0원 확정(미상 아님)
    assert report.cost_krw.count == 2


def test_aggregate_unknown_tier_noted_and_excluded() -> None:
    events: list[dict[str, object]] = [
        {"cost_tier": "cloud_mid", "input_tokens": 100, "output_tokens": 50, "cost_krw": 0.4},
        {"input_tokens": 100, "output_tokens": 50, "cost_krw": 0.4},  # cost_tier 없음
    ]
    report = cr.aggregate_l3_events(events)
    assert report.cost_tier_counts.get("(unknown)") == 1
    assert report.cloud_count == 1
    assert report.local_count == 0
    # 분류된 것은 cloud 1건뿐(unknown은 분류 제외) → 로컬 비중 0.0.
    assert report.local_ratio == pytest.approx(0.0)
    assert any("미상" in n for n in report.notes)


def test_aggregate_all_cache_hits_no_cost_note() -> None:
    events: list[dict[str, object]] = [
        {"cost_tier": "local", "cache_hit": True},
        {"cost_tier": "cloud_mid", "cache_hit": True},
    ]
    report = cr.aggregate_l3_events(events)
    assert report.cost_krw.count == 0  # 실측 비용 표본 0
    assert any("대표 트래픽 필요" in n for n in report.notes)
    assert report.cache_hit_rate == pytest.approx(1.0)


def test_bool_not_counted_as_number() -> None:
    # cache_hit=True(bool)가 실수로 토큰 수치로 집계되면 안 된다(_opt_int/_opt_float 가드).
    events: list[dict[str, object]] = [
        {"cost_tier": "local", "input_tokens": True, "cost_krw": False}  # 비정상 타입
    ]
    report = cr.aggregate_l3_events(events)
    assert report.input_tokens.count == 0
    assert report.cost_krw.count == 0


# ──────────────────────────────────────────────────────────────────────────
# fetch_l3_events — 가짜 read 클라이언트 주입(정규화·페이지네이션·no-op·오류 삼킴).
# ──────────────────────────────────────────────────────────────────────────


class _FakeObs:
    """langfuse 관측 객체 흉내 — .metadata 속성만."""

    def __init__(self, metadata: dict[str, object]) -> None:
        self.metadata = metadata


class _FakeResponse:
    """fetch_observations 응답 흉내 — .data 리스트만."""

    def __init__(self, data: list[Any]) -> None:
        self.data = data


class _FakeReadClient:
    """페이지 리스트를 순서대로 돌려주는 가짜 read 클라이언트."""

    def __init__(self, pages: list[list[Any]], *, raise_on_page: int | None = None) -> None:
        self._pages = pages
        self._raise_on_page = raise_on_page
        self.calls: list[dict[str, Any]] = []

    def fetch_observations(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(kwargs)
        page = int(kwargs["page"])
        if self._raise_on_page is not None and page == self._raise_on_page:
            raise RuntimeError("조회 장애 시뮬레이션")
        data = self._pages[page - 1] if 0 <= page - 1 < len(self._pages) else []
        return _FakeResponse(data)


class _UnconfiguredSettings:
    langfuse_configured = False


def test_fetch_unconfigured_returns_empty() -> None:
    # 미설정 + client 미주입 → 조회 시도 없이 빈 리스트(no-op).
    events = cr.fetch_l3_events(settings=_UnconfiguredSettings())  # type: ignore[arg-type]
    assert events == []


def test_fetch_normalizes_metadata() -> None:
    client = _FakeReadClient([[_FakeObs({"cost_tier": "cloud_mid", "input_tokens": 100})]])
    events = cr.fetch_l3_events(days=1, limit=100, client=client)
    assert events == [{"cost_tier": "cloud_mid", "input_tokens": 100}]
    # 조회 인자 검증 — 이름·타입·기간이 실린다.
    call = client.calls[0]
    assert call["name"] == "l3_routing"
    assert call["type"] == "EVENT"


def test_fetch_pagination_stops_on_partial_page() -> None:
    # limit=2: page1 꽉 참(2건) → 계속, page2 부분(1건) → 수집 후 종료.
    page1 = [_FakeObs({"i": 1}), _FakeObs({"i": 2})]
    page2 = [_FakeObs({"i": 3})]
    client = _FakeReadClient([page1, page2])
    events = cr.fetch_l3_events(limit=2, client=client)
    assert [e["i"] for e in events] == [1, 2, 3]
    assert len(client.calls) == 2  # 2페이지만 조회(3페이지 조회 안 함)


def test_fetch_pagination_stops_on_empty_page() -> None:
    page1 = [_FakeObs({"i": 1}), _FakeObs({"i": 2})]
    client = _FakeReadClient([page1, []])  # page2 빈 리스트 → 종료
    events = cr.fetch_l3_events(limit=2, client=client)
    assert [e["i"] for e in events] == [1, 2]


def test_fetch_swallows_errors_returns_partial() -> None:
    # page1 성공(2건)·page2 예외 → 예외 전파 없이 page1분만 반환(never-break).
    page1 = [_FakeObs({"i": 1}), _FakeObs({"i": 2})]
    client = _FakeReadClient([page1, [_FakeObs({"i": 3})]], raise_on_page=2)
    events = cr.fetch_l3_events(limit=2, client=client)
    assert [e["i"] for e in events] == [1, 2]  # 예외 없이 부분 반환


def test_fetch_uses_now_for_window() -> None:
    now = datetime(2026, 7, 8, 12, 0, 0, tzinfo=timezone.utc)
    client = _FakeReadClient([[]])
    cr.fetch_l3_events(days=3, client=client, now=now)
    call = client.calls[0]
    assert call["from_start_time"] == now - timedelta(days=3)


def test_extract_metadata_dict_style_observation() -> None:
    # 속성 없이 dict로 온 관측도 흡수한다.
    obs = {"metadata": {"cost_tier": "local"}}
    assert cr._extract_metadata(obs) == {"cost_tier": "local"}
    # 메타 없는 관측 → None(수집에서 제외).
    assert cr._extract_metadata(object()) is None


# ──────────────────────────────────────────────────────────────────────────
# 렌더·CLI — 시크릿 없이 표를 낸다, main은 항상 exit 0(관측 도구).
# ──────────────────────────────────────────────────────────────────────────


def test_render_empty_report_does_not_crash() -> None:
    out = cr._render_stdout(cr.aggregate_l3_events([]))
    assert "총 이벤트: 0건" in out
    assert "미상" in out  # 빈 표본은 '미상'으로 표기(0 아님)


def test_render_includes_tuning_suggestion() -> None:
    out = cr._render_stdout(cr.aggregate_l3_events(_sample_events()))
    assert "_EST_ASSUMED_INPUT_TOKENS" in out
    assert "110" in out  # input p50 제안치


def test_main_smoke_writes_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    # Settings()·fetch를 대체해 라이브 없이 main 경로를 태운다.
    monkeypatch.setattr(cr, "Settings", lambda: _UnconfiguredSettings())
    monkeypatch.setattr(cr, "fetch_l3_events", lambda **kwargs: _sample_events())
    out_path = tmp_path / "report.json"
    rc = cr.main(["--days", "1", "--json", str(out_path)])
    assert rc == 0  # 판독은 항상 정상 종료
    saved = json.loads(out_path.read_text(encoding="utf-8"))
    assert saved["event_count"] == 5
    assert saved["suggested_est_input_tokens"] == 110


# ── 티어별 분포(S1-12 결과표 행 단위) ──


def test_tier_stats_per_tier_distributions() -> None:
    # 결과표는 LOCAL/CLOUD_MID 행별 p50·합이 필요 — 전역 분포로는 채울 수 없다(런북 §5).
    events = [
        {"cost_tier": "local", "input_tokens": 100, "cost_krw": 0.0, "latency_ms": 800},
        {"cost_tier": "local", "input_tokens": 120, "cost_krw": 0.0, "latency_ms": 900},
        {"cost_tier": "cloud_mid", "input_tokens": 900, "cost_krw": 12.5, "latency_ms": 2500},
        {"cost_tier": None},  # 미상 → (unknown) 버킷·표본 없음
    ]
    report = cr.aggregate_l3_events(events)
    assert set(report.tier_stats) == {"local", "cloud_mid", "(unknown)"}
    local = report.tier_stats["local"]
    assert local.events == 2
    assert local.latency_ms.p50 == 850.0
    assert local.cost_krw.total == 0.0
    cloud = report.tier_stats["cloud_mid"]
    assert cloud.events == 1 and cloud.cost_krw.total == 12.5
    unknown = report.tier_stats["(unknown)"]
    assert unknown.events == 1 and unknown.latency_ms.count == 0  # 실측 없음 정직 집계


# ──────────────────────────────────────────────────────────────────────────
# SDK 버전 적응 읽기 — v3/v4(fetch_observations 부재)는 api.observations.get_many
# (2026-07-16 실측: fetch_observations는 v2 전용 표면)
# ──────────────────────────────────────────────────────────────────────────
class _FakeV4ReadClient:
    """v4형 가짜 — fetch_observations가 *없고* api.observations.get_many만 있다."""

    class _Observations:
        def __init__(self, outer: _FakeV4ReadClient) -> None:
            self._outer = outer

        def get_many(self, **kwargs: Any) -> _FakeResponse:
            self._outer.calls.append(kwargs)
            page = int(kwargs["page"])
            pages = self._outer._pages
            data = pages[page - 1] if 0 <= page - 1 < len(pages) else []
            return _FakeResponse(data)

    class _Api:
        def __init__(self, outer: _FakeV4ReadClient) -> None:
            self.observations = _FakeV4ReadClient._Observations(outer)

    def __init__(self, pages: list[list[Any]]) -> None:
        self._pages = pages
        self.calls: list[dict[str, Any]] = []
        self.api = _FakeV4ReadClient._Api(self)


def test_fetch_v4_client_uses_api_get_many() -> None:
    """fetch_observations 부재(v3/v4) → api.observations.get_many로 동일 조회."""
    meta = {"cost_tier": "local", "cost_krw": 0.0}
    client = _FakeV4ReadClient(pages=[[_FakeObs(meta)]])
    events = cr.fetch_l3_events(days=1, limit=10, client=client)  # type: ignore[arg-type]
    assert events == [meta]
    assert client.calls and client.calls[0]["name"] == "l3_routing"


def test_fetch_no_read_surface_returns_empty() -> None:
    """조회 표면이 아예 없는 클라이언트 → 예외 없이 빈 리포트(never-break·경고만)."""

    class _NoSurface:
        pass

    events = cr.fetch_l3_events(days=1, limit=10, client=_NoSurface())  # type: ignore[arg-type]
    assert events == []


# ══════════════════════════════════════════════════════════════════════
# 데이터 등급 게이트 발동률 — Langfuse 측 집계 (EOS-59 ②·관측 보조)
#
# 판정치는 `ops.cost_probe`가 in-process로 낸다. 여기서 지키는 것은 세 가지다:
#   ① 발동/판정 이벤트를 정확히 센다.
#   ② 판정이 안 실린 이벤트는 분모에서 빠지고 **notes로 경고**된다(조용히 희석 금지).
#   ③ 판정 0건은 "0% 발동"이 아니라 **측정 불가(None)**다.
# ══════════════════════════════════════════════════════════════════════
def test_data_export_counts_and_rate() -> None:
    events: list[dict[str, object]] = [
        {
            "cost_tier": "local",
            "data_export_blocked": True,
            "data_export_reason": "EXPORT_PROHIBITED",
        },
        {
            "cost_tier": "local",
            "data_export_blocked": True,
            "data_export_reason": "EXPORT_UNVERIFIED",
        },
        {
            "cost_tier": "cloud_mid",
            "data_export_blocked": False,
            "data_export_reason": "EXPORT_ALLOWED",
        },
        {
            "cost_tier": "local",
            "data_export_blocked": False,
            "data_export_reason": "EXPORT_ALLOWED",
        },
    ]
    report = cr.aggregate_l3_events(events)
    assert report.data_export_blocked_count == 2
    assert report.data_export_evaluated == 4
    assert report.data_export_block_rate == pytest.approx(0.5)
    assert report.data_export_reason_counts == {
        "EXPORT_PROHIBITED": 1,
        "EXPORT_UNVERIFIED": 1,
        "EXPORT_ALLOWED": 2,
    }


def test_events_without_judgment_are_excluded_and_warned() -> None:
    """게이트를 거치지 않은 이벤트가 분모를 조용히 희석하지 않는다 — notes가 말한다."""
    events: list[dict[str, object]] = [
        {
            "cost_tier": "local",
            "data_export_blocked": True,
            "data_export_reason": "EXPORT_PROHIBITED",
        },
        {"cost_tier": "local"},  # 구 이벤트·라우터 미경유
    ]
    report = cr.aggregate_l3_events(events)
    assert report.data_export_evaluated == 1
    assert report.data_export_block_rate == pytest.approx(1.0)
    assert any("라우터 게이트를 거치지 않은" in note for note in report.notes)


def test_zero_judgment_events_is_unmeasurable_not_zero_percent() -> None:
    report = cr.aggregate_l3_events([{"cost_tier": "local"}, {"cost_tier": "cloud_mid"}])
    assert report.data_export_evaluated == 0
    assert report.data_export_block_rate is None
    assert any("측정 불가" in note for note in report.notes)


def test_render_reports_measurement_failure_instead_of_a_fake_zero() -> None:
    text = cr._render_stdout(cr.aggregate_l3_events([{"cost_tier": "local"}]))
    assert "데이터 등급 게이트" in text
    assert "측정 불가" in text


def test_render_shows_block_rate_when_measured() -> None:
    events: list[dict[str, object]] = [
        {
            "cost_tier": "local",
            "data_export_blocked": True,
            "data_export_reason": "EXPORT_PROHIBITED",
        },
        {
            "cost_tier": "cloud_mid",
            "data_export_blocked": False,
            "data_export_reason": "EXPORT_ALLOWED",
        },
    ]
    text = cr._render_stdout(cr.aggregate_l3_events(events))
    assert "차단 발동: 1건 / 판정 이벤트 2건" in text
    assert "발동률 50.0%" in text


# ── 저작 경로 분리(OPS-84 ③) ─────────────────────────────────────────────


def test_authoring_events_are_excluded_from_gate2_sample_but_counted() -> None:
    """저작 표지 이벤트는 게이트② 표본에서 빠지고, 뺀 건수는 숨기지 않는다.

    대조: 서빙 이벤트는 클라우드 1건뿐(로컬 비율 0.0). 저작 로컬 이벤트 3건이 섞이면 로컬
    비율이 0.75로 **위장**된다 — 분리 후에도 0.0이어야 한다.
    """
    serving: dict[str, object] = {
        "cost_tier": "cloud_mid",
        "input_tokens": 100,
        "output_tokens": 50,
        "cost_krw": 0.42,
    }
    authoring = [
        {
            "cost_tier": "local",
            "input_tokens": 400,
            "output_tokens": 300,
            "cost_krw": 0.0,
            "traffic_surface": "authoring",
        }
        for _ in range(3)
    ]
    report = cr.aggregate_l3_events([serving, *authoring])
    assert report.event_count == 1
    assert report.local_ratio == 0.0
    assert report.input_tokens.p50 == 100
    assert report.authoring_excluded_count == 3
    assert any("저작 경로 이벤트 3건" in note for note in report.notes)


def test_events_without_surface_tag_stay_in_the_serving_sample() -> None:
    """표지 없는 구 이벤트는 종전대로 서빙 표본이다(하위호환) — 분리 0건이면 note도 없다."""
    report = cr.aggregate_l3_events(_sample_events())
    assert report.event_count == 5
    assert report.authoring_excluded_count == 0
    assert not any("저작 경로" in note for note in report.notes)
