"""L6 응용 모드 6종 도달 카운터 — `/health/ready` 노출 + gating 엔드포인트 배선 (hermetic) (PB-04).

`L6ModeReachCounters`가 `create_app()`이 만드는 모든 앱에 항상 심어지고, `/health/ready`의
`l6_mode_reach.*`로 정확히 그 스냅샷을 노출하는지 검증한다. 나아가 `GET /v1/gating/*` 6개
엔드포인트를 실제로 호출하면 해당 모드 카운터만 정확히 1 증가하는지(다른 모드에 새지 않는지)를
`TestClient`로 확인한다 — `test_growth_evidence_reachability.py`(PED-06) + `test_gating.py`
(FakeSession 패턴)의 결합이다.

**"도달 0회" 실측 재현의 핵심**: 아무것도 호출하지 않은 새 앱은 6개 카운터 전부 0이다
(`test_fresh_app_has_all_zero_counts`) — `problem_bank_gap_review_r2.md` §0-②-나가 정적으로
주장하는 "학생 도달 0회"가 라이브 카운터로도 재현됨을 이 테스트가 고정한다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

from whymath_backend.api._l6_mode_reach_state import (
    GIFTED,
    RETAKE,
    SUNEUNG,
    THINKING,
    L6ModeReachCounters,
    get_l6_mode_reach_counters,
)
from whymath_backend.app import create_app
from whymath_backend.db.session import get_session
from whymath_backend.ops.service_health import (
    COMPONENT_DATABASE,
    COMPONENT_LLM_ROUTER,
    COMPONENT_REDIS,
    ComponentCheck,
    ReadinessProbes,
)


# test_gating.py의 FakeSession(빈 후보) 재사용은 순환 위험이 있어(테스트 모듈 간 import) 여기선
# 최소한의 빈 세션만 둔다 — 게이팅 6개 핸들러는 후보가 비어도(candidates=[]) 정상 200을 반환하고
# (기존 test_gating.py `test_empty_candidates_returns_empty` 등과 동일 계약) 카운터 증가는 응답
# 성공/실패와 무관하다(핸들러 진입 즉시 record).
class _EmptyResult:
    def scalars(self) -> "_EmptyScalars":
        return _EmptyScalars()


class _EmptyScalars:
    def all(self) -> list[object]:
        return []


class _EmptySession:
    """`select(Problem)` 후보 조회가 항상 빈 결과를 돌려주는 가짜 세션.

    school-progress 핸들러는 후보가 비면(`_fetch_candidates`가 빈 리스트) 성취기준 원자 축
    조인(`_fetch_achievement_codes`)을 아예 호출하지 않는다(`if not problem_ids: return {}` —
    gating.py 조기 반환) — 그래서 이 가짜 세션은 scalars 경로 하나만 구현해도 6개 엔드포인트
    전부(school-progress 포함) 안전하다.
    """

    async def execute(self, stmt: object) -> _EmptyResult:
        return _EmptyResult()


def _fake_probes() -> ReadinessProbes:
    """실 DB·Redis·LLM 진입을 막는 가짜 probes(`test_growth_evidence_reachability.py` 미러)."""

    async def _ok(name: str, *, required: bool) -> ComponentCheck:
        return ComponentCheck(
            name=name, configured=True, reachable=True, required=required, error=None
        )

    async def _db() -> ComponentCheck:
        return await _ok(COMPONENT_DATABASE, required=True)

    async def _redis() -> ComponentCheck:
        return await _ok(COMPONENT_REDIS, required=False)

    async def _llm() -> ComponentCheck:
        return await _ok(COMPONENT_LLM_ROUTER, required=False)

    return ReadinessProbes(database=_db, redis=_redis, llm=_llm)


def _gating_client() -> TestClient:
    app = create_app(readiness_probes=_fake_probes())

    async def _override() -> AsyncIterator[_EmptySession]:
        yield _EmptySession()

    app.dependency_overrides[get_session] = _override
    return TestClient(app)


# ──────────────────────────────────────────────────────────────────────
# 카운터 자체 — app.state 심기 + `/health/ready` 노출(hermetic·gating 미호출)
# ──────────────────────────────────────────────────────────────────────
def test_fresh_app_has_all_zero_counts() -> None:
    """새 앱은 6개 모드 카운터 전부 0에서 시작 — '측정했더니 0'이 아니라 초기 상태."""
    app = create_app(readiness_probes=_fake_probes())
    snapshot = get_l6_mode_reach_counters(app).snapshot()
    assert snapshot.retake == 0
    assert snapshot.suneung == 0
    assert snapshot.school_progress == 0
    assert snapshot.thinking == 0
    assert snapshot.metacognition == 0
    assert snapshot.gifted == 0


def test_health_ready_exposes_l6_mode_reach_section() -> None:
    """`GET /health/ready` 응답에 l6_mode_reach.{모드}가 6개 다 0으로 있다."""
    app = create_app(readiness_probes=_fake_probes())
    resp = TestClient(app).get("/health/ready")
    body = resp.json()
    assert "l6_mode_reach" in body
    assert body["l6_mode_reach"] == {
        "retake": 0,
        "suneung": 0,
        "school_progress": 0,
        "thinking": 0,
        "metacognition": 0,
        "gifted": 0,
    }


def test_health_ready_reflects_recorded_counts() -> None:
    """카운터를 직접 증가시키면 `/health/ready` 응답에 그대로 반영된다(변별력)."""
    app = create_app(readiness_probes=_fake_probes())
    counters = get_l6_mode_reach_counters(app)
    counters.record(RETAKE)
    counters.record(RETAKE)
    counters.record(GIFTED)

    resp = TestClient(app).get("/health/ready")
    body = resp.json()["l6_mode_reach"]
    assert body["retake"] == 2
    assert body["gifted"] == 1
    assert body["suneung"] == 0
    assert body["school_progress"] == 0
    assert body["thinking"] == 0
    assert body["metacognition"] == 0


def test_counters_are_independent_per_app_instance() -> None:
    """앱 인스턴스가 다르면 카운터도 독립 — 한쪽 증가가 다른 쪽에 새지 않는다."""
    app_a = create_app(readiness_probes=_fake_probes())
    app_b = create_app(readiness_probes=_fake_probes())
    get_l6_mode_reach_counters(app_a).record(SUNEUNG)

    assert get_l6_mode_reach_counters(app_a).snapshot().suneung == 1
    assert get_l6_mode_reach_counters(app_b).snapshot().suneung == 0


class TestL6ModeReachCountersUnit:
    """`L6ModeReachCounters` 자체의 계약(app 무관 순수 단위테스트)."""

    def test_starts_at_zero(self) -> None:
        snapshot = L6ModeReachCounters().snapshot()
        assert (
            snapshot.retake,
            snapshot.suneung,
            snapshot.school_progress,
            snapshot.thinking,
            snapshot.metacognition,
            snapshot.gifted,
        ) == (0, 0, 0, 0, 0, 0)

    def test_record_increments_only_target_mode(self) -> None:
        counters = L6ModeReachCounters()
        counters.record(THINKING)
        counters.record(THINKING)
        snapshot = counters.snapshot()
        assert snapshot.thinking == 2
        assert snapshot.retake == 0
        assert snapshot.suneung == 0
        assert snapshot.school_progress == 0
        assert snapshot.metacognition == 0
        assert snapshot.gifted == 0

    def test_unknown_mode_raises_keyerror(self) -> None:
        """오타 방어적 무시 금지 — 값공간 밖 mode는 KeyError로 즉시 터진다."""
        counters = L6ModeReachCounters()
        try:
            counters.record("오타모드")
        except KeyError:
            pass
        else:
            raise AssertionError("알 수 없는 모드 이름이 조용히 무시됐다 — 침묵 실패 금지 위반.")

    def test_snapshot_is_immutable_dataclass(self) -> None:
        """스냅샷은 frozen — 호출자가 실수로 값을 고쳐 카운터를 오염시킬 수 없다."""
        snapshot = L6ModeReachCounters().snapshot()
        try:
            snapshot.retake = 999  # type: ignore[misc]
        except (AttributeError, TypeError):
            pass
        else:
            raise AssertionError("frozen dataclass가 값 변경을 막지 못했다")


# ──────────────────────────────────────────────────────────────────────
# gating 엔드포인트 배선 — 실제 HTTP 호출이 해당 모드만 1 증가시키는지
# ──────────────────────────────────────────────────────────────────────
class TestGatingEndpointsIncrementReachCounters:
    """6개 `/v1/gating/*` 엔드포인트를 각각 1회 호출 → `/health/ready`의 해당 카운터만 +1."""

    def test_retake_endpoint_increments_retake_only(self) -> None:
        client = _gating_client()
        resp = client.get("/v1/gating/retake", params={"persona": "B_자사고N수"})
        assert resp.status_code == 200, resp.text
        body = client.get("/health/ready").json()["l6_mode_reach"]
        assert body["retake"] == 1
        assert body["suneung"] == 0

    def test_suneung_endpoint_increments_suneung_only(self) -> None:
        client = _gating_client()
        resp = client.get("/v1/gating/suneung")
        assert resp.status_code == 200, resp.text
        body = client.get("/health/ready").json()["l6_mode_reach"]
        assert body["suneung"] == 1
        assert body["retake"] == 0

    def test_school_progress_endpoint_increments_school_progress_only(self) -> None:
        client = _gating_client()
        resp = client.get("/v1/gating/school-progress", params={"persona": "A_일반고고3"})
        assert resp.status_code == 200, resp.text
        body = client.get("/health/ready").json()["l6_mode_reach"]
        assert body["school_progress"] == 1
        assert body["thinking"] == 0

    def test_thinking_endpoint_increments_thinking_only(self) -> None:
        client = _gating_client()
        resp = client.get("/v1/gating/thinking")
        assert resp.status_code == 200, resp.text
        body = client.get("/health/ready").json()["l6_mode_reach"]
        assert body["thinking"] == 1
        assert body["metacognition"] == 0

    def test_metacognition_endpoint_increments_metacognition_only(self) -> None:
        client = _gating_client()
        resp = client.get("/v1/gating/metacognition")
        assert resp.status_code == 200, resp.text
        body = client.get("/health/ready").json()["l6_mode_reach"]
        assert body["metacognition"] == 1
        assert body["gifted"] == 0

    def test_gifted_endpoint_increments_gifted_only(self) -> None:
        client = _gating_client()
        resp = client.get("/v1/gating/gifted")
        assert resp.status_code == 200, resp.text
        body = client.get("/health/ready").json()["l6_mode_reach"]
        assert body["gifted"] == 1
        assert body["retake"] == 0

    def test_repeated_calls_accumulate(self) -> None:
        """같은 엔드포인트를 3회 호출하면 그 모드만 3이 된다(요청 1건당 1 증가 계약)."""
        client = _gating_client()
        for _ in range(3):
            resp = client.get("/v1/gating/gifted")
            assert resp.status_code == 200
        body = client.get("/health/ready").json()["l6_mode_reach"]
        assert body["gifted"] == 3

    def test_query_validation_422_does_not_reach_handler_body(self) -> None:
        """FastAPI 쿼리 검증 실패(422)는 핸들러 *본문 진입 전*이라 카운터가 증가하지 않는다.

        `record()` 호출은 핸들러 본문 첫 줄에 있다 — "성공/실패 무관"은 *본문이 실행된 뒤의*
        응답 상태(200/500 등)를 가리키는 것이지, FastAPI 프레임워크 레벨의 파라미터 검증
        (필수 쿼리 누락 → 422·본문 미실행)까지 포함하지 않는다. 이 테스트는 그 경계를
        명시적으로 고정한다 — retake는 persona가 필수라 누락 시 422고, 이때 카운터는 0 그대로.
        """
        client = _gating_client()
        resp = client.get("/v1/gating/retake")  # persona 필수 — 422(핸들러 본문 미실행)
        assert resp.status_code == 422
        body = client.get("/health/ready").json()["l6_mode_reach"]
        assert body["retake"] == 0
