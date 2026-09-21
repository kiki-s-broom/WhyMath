"""`GET /v1/me/growth-evidence` — 노출 계약 경유 학생 안전 서빙 엔드포인트 (hermetic) (PED-08).

`whymath_backend.api.me.compute_wh1_surrogate_metrics`를 monkeypatch해 `SurrogateMetrics`
계산 자체(실 DB)는 건드리지 않고, 이 엔드포인트가 그 결과를 *노출 계약*
(`growth_evidence_exposure.classify_metric_exposure`/`narrate_calibration_brier`)을 거쳐서만
직렬화하는지를 검증한다. 핵심 회귀는 `test_gaming_suspect_never_leaks_into_response_text` —
계약 모듈의 `suppressed_reason` 원문(`GAMING_SUSPECT` 리터럴 포함)이 응답 원시 텍스트 어디에도
나타나지 않아야 한다(랜드마인 방어).

`GET /health/ready` 도달 카운터 독립성(N≠M) 검증은 `test_growth_evidence_reachability.py`
(PED-06 원시 표면 전용)와 겹치지 않도록 이 파일에서 *두 라우트를 함께* 때려 구분해 센다.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from whymath_backend.api._auth import get_consented_user, require_content_admin
from whymath_backend.api.me import GrowthEvidenceResponse
from whymath_backend.app import create_app
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.harness.growth_evidence_exposure import narrate_calibration_brier
from whymath_backend.harness.wh1_evaluation import (
    HelpReductionValidation,
    Metric,
    MetricStatus,
    R15Verdict,
    SurrogateMetrics,
)
from whymath_backend.ops.service_health import (
    COMPONENT_DATABASE,
    COMPONENT_LLM_ROUTER,
    COMPONENT_REDIS,
    ComponentCheck,
    ReadinessProbes,
)
from whymath_backend.schema.enums import Persona, Role
from whymath_backend.schema.user import UserProfile as UserProfileSchema

_UID = uuid.uuid4()

_ENDPOINT = "/v1/me/growth-evidence"

# GrowthEvidenceResponse가 선언한 필드 집합 그대로 — §7 스키마 구조 증명과 §2 happy path
# 양쪽에서 재사용(하드코딩 이중화 방지).
_DECLARED_FIELDS = set(GrowthEvidenceResponse.model_fields)


def _user() -> UserProfile:
    return UserProfile.from_schema(
        UserProfileSchema(user_id=_UID, persona_primary=Persona.A_일반고고3)
    )


# SEC-24(원 SEC-13): `/v1/me/harness-metrics`가 `RequireContentAdmin`으로 닫혔다
# (test_problems.py `_ADMIN_USER` 패턴 동형) — 이 파일의 `TestReachCounterIndependence`가
# 두 라우트(growth-evidence·harness-metrics)를 함께 때리므로 admin 오버라이드도 함께 건다.
_ADMIN_USER = UserProfile(user_id=uuid.uuid4(), role=Role.CONTENT_ADMIN)


class _FakeAsyncSession:
    """`compute_wh1_surrogate_metrics`를 monkeypatch하므로 세션은 실제로 쿼리되지 않는다."""


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


def _metric(value: float | None = 0.5, status: MetricStatus = MetricStatus.MEASURED) -> Metric:
    return Metric(value=value, status=status, note="테스트 note")


def _surrogate_metrics(
    *,
    verdict: R15Verdict = R15Verdict.GENUINE_IMPROVEMENT,
    calibration_brier_value: float | None = 0.05,
    hint_depth_value: float = 2.0,
) -> SurrogateMetrics:
    """전 필드 MEASURED 고정 SurrogateMetrics — 필요한 축(verdict·brier)만 매개변수화."""
    m = _metric()
    return SurrogateMetrics(
        verify_pass_rate=m,
        diagnosis_agreement_rate=m,
        session_completion_rate=m,
        tokens_per_turn=m,
        help_reduction_slope=m,
        help_demand_supply_ratio=m,
        calibration_brier=_metric(value=calibration_brier_value),
        transfer_score=m,
        hint_depth_reached=_metric(value=hint_depth_value),
        mastery_gain_rate=m,
        gap_recovery_leadtime_days=m,
        misconception_resolution_rate=m,
        self_solve_rate=m,
        help_reduction_validated=HelpReductionValidation(
            verdict=verdict,
            help_slope=-1.0,
            accuracy_slope=0.5 if verdict is R15Verdict.GENUINE_IMPROVEMENT else -0.5,
            difficulty_slope=None,
            note="테스트 판정 note",
        ),
        sample_sessions=1,
        window_start=None,
        window_end=None,
        user_scoped=True,
    )


def _client_with_auth() -> TestClient:
    app = create_app(readiness_probes=_fake_probes())
    app.dependency_overrides[get_consented_user] = _user
    # SEC-24(원 SEC-13): harness-metrics는 이제 RequireContentAdmin — 이 클라이언트로 그 라우트도
    # 호출하는 TestReachCounterIndependence를 위해 함께 오버라이드(growth-evidence 쪽 인가는 무관향).
    app.dependency_overrides[require_content_admin] = lambda: _ADMIN_USER

    async def _sess() -> AsyncIterator[_FakeAsyncSession]:
        yield _FakeAsyncSession()

    app.dependency_overrides[get_session] = _sess
    return TestClient(app)


def _client_no_auth() -> TestClient:
    """세션 의존성만 오버라이드 — 인증 의존성은 실물 그대로(무토큰 401 재현)."""
    app = create_app(readiness_probes=_fake_probes())

    async def _sess() -> AsyncIterator[_FakeAsyncSession]:
        yield _FakeAsyncSession()

    app.dependency_overrides[get_session] = _sess
    return TestClient(app)


class TestAuthGate:
    def test_401_without_auth(self) -> None:
        client = _client_no_auth()
        resp = client.get(_ENDPOINT)
        assert resp.status_code == 401


class TestStaticReachVisibility:
    """리터럴 경로 스모크 — 정적 도달 가시성 (PED-15).

    **왜 이 파일에 이 테스트가 더 붙었나(정직 표기)**: PED-15는 "`GET /v1/me/growth-evidence`를
    부르는 테스트·모바일 클라이언트가 0건"이라는 전제로 등재됐는데, **테스트 쪽 전제는 실측상
    사실이 아니었다** — 이 파일의 나머지 케이스가 이미 `TestClient`로 이 라우트를 때리고 있다.
    OPS-22 `declared_unwired_audit`가 그것을 못 본 이유는 호출부가 `_ENDPOINT` *상수*를 쓰고
    감사기의 도달 판정이 리터럴 문자열만 매칭하기 때문이다(대장의 `POST /v1/ocr/pages` 항목이
    같은 정밀도 한계로 이미 by-design 처리돼 있다 — 동형 오탐).

    유예(by-design)로 덮지 않고 리터럴 호출을 하나 두는 쪽을 택했다. 유예는 "의도적 미도달"을
    선언하는 것인데 이 라우트는 미도달이 *아니므로*, 사실대로 도달로 잡히게 두는 편이 대장을
    정직하게 유지한다. 나머지 케이스의 `_ENDPOINT` 사용은 그대로 둔다(파일 스타일 보존).

    **잔여 — 감사기가 이 테스트로 덮어 버리는 진짜 공백**: 이 엔드포인트를 소비하는 **모바일
    클라이언트는 여전히 0건**이다. 성장 증거 화면은 아직 없고, 그 배선은 이 태스크 범위 밖이다.
    """

    def test_endpoint_reachable_via_literal_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _fake_compute(*_args: Any, **_kwargs: Any) -> SurrogateMetrics:
            return _surrogate_metrics()

        monkeypatch.setattr("whymath_backend.api.me.compute_wh1_surrogate_metrics", _fake_compute)
        client = _client_with_auth()
        resp = client.get("/v1/me/growth-evidence")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        # 본인 집계만 — 코호트·타 학생 축은 이 표면에 존재하지 않는다.
        assert body["user_scoped"] is True
        # 비교·서열 파생 필드 0종(계약 모듈의 의도적 부재를 서빙 표면에서도 유지).
        forbidden = {"percentile", "rank", "peer_average", "class_rank", "cohort_average"}
        assert forbidden.isdisjoint(body.keys())


class TestHappyPathStructuralFields:
    def test_200_and_exact_top_level_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _fake_compute(*_args: Any, **_kwargs: Any) -> SurrogateMetrics:
            return _surrogate_metrics()

        monkeypatch.setattr("whymath_backend.api.me.compute_wh1_surrogate_metrics", _fake_compute)
        client = _client_with_auth()
        resp = client.get(_ENDPOINT)
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == _DECLARED_FIELDS

    def test_internal_only_metrics_structurally_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _fake_compute(*_args: Any, **_kwargs: Any) -> SurrogateMetrics:
            return _surrogate_metrics()

        monkeypatch.setattr("whymath_backend.api.me.compute_wh1_surrogate_metrics", _fake_compute)
        body = _client_with_auth().get(_ENDPOINT).json()
        assert "diagnosis_agreement_rate" not in body
        assert "tokens_per_turn" not in body

    def test_genuine_improvement_hint_depth_fully_exposed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GAMING_SUSPECT가 아니면 hint_depth_reached는 value·exposable_now=True 그대로."""

        async def _fake_compute(*_args: Any, **_kwargs: Any) -> SurrogateMetrics:
            return _surrogate_metrics(verdict=R15Verdict.GENUINE_IMPROVEMENT, hint_depth_value=3.0)

        monkeypatch.setattr("whymath_backend.api.me.compute_wh1_surrogate_metrics", _fake_compute)
        body = _client_with_auth().get(_ENDPOINT).json()
        assert body["hint_depth_reached"]["exposable_now"] is True
        assert body["hint_depth_reached"]["value"] == 3.0
        assert body["hint_depth_reached"]["suppressed_reason"] is None


class TestGamingSuspectSuppression:
    """랜드마인 회귀 — GAMING_SUSPECT 원문이 응답 어디에도 유출되지 않는다."""

    def test_gaming_suspect_hides_value_with_non_null_reason(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _fake_compute(*_args: Any, **_kwargs: Any) -> SurrogateMetrics:
            return _surrogate_metrics(verdict=R15Verdict.GAMING_SUSPECT)

        monkeypatch.setattr("whymath_backend.api.me.compute_wh1_surrogate_metrics", _fake_compute)
        resp = _client_with_auth().get(_ENDPOINT)
        assert resp.status_code == 200
        body = resp.json()
        assert body["hint_depth_reached"]["value"] is None
        assert body["hint_depth_reached"]["exposable_now"] is False
        assert isinstance(body["hint_depth_reached"]["suppressed_reason"], str)
        assert body["hint_depth_reached"]["suppressed_reason"]

    def test_gaming_suspect_literal_never_in_raw_response_text(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """핵심 랜드마인 방어 — 파싱된 JSON이 아니라 원시 응답 *텍스트 전체*를 스캔한다."""

        async def _fake_compute(*_args: Any, **_kwargs: Any) -> SurrogateMetrics:
            return _surrogate_metrics(verdict=R15Verdict.GAMING_SUSPECT)

        monkeypatch.setattr("whymath_backend.api.me.compute_wh1_surrogate_metrics", _fake_compute)
        resp = _client_with_auth().get(_ENDPOINT)
        assert resp.status_code == 200
        assert "GAMING_SUSPECT" not in resp.text

    def test_other_verdicts_do_not_suppress_hint_depth(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """과잉 억제 방지 — GAMING_SUSPECT가 아닌 verdict는 억제하지 않는다(변별력)."""
        for verdict in (R15Verdict.NO_HELP_REDUCTION, R15Verdict.INSUFFICIENT_DATA):

            async def _fake_compute(
                *_args: Any, _verdict: R15Verdict = verdict, **_kwargs: Any
            ) -> SurrogateMetrics:
                return _surrogate_metrics(verdict=_verdict)

            with pytest.MonkeyPatch.context() as mp:
                mp.setattr("whymath_backend.api.me.compute_wh1_surrogate_metrics", _fake_compute)
                body = _client_with_auth().get(_ENDPOINT).json()
                assert body["hint_depth_reached"]["exposable_now"] is True


class TestBrierNarrationOnly:
    @pytest.mark.parametrize(
        "value",
        [None, 0.05, 0.2, 0.5],
        ids=["no_data", "good", "fair", "poor"],
    )
    def test_narrative_matches_contract_function_no_numeric_leak(
        self, monkeypatch: pytest.MonkeyPatch, value: float | None
    ) -> None:
        async def _fake_compute(*_args: Any, **_kwargs: Any) -> SurrogateMetrics:
            return _surrogate_metrics(calibration_brier_value=value)

        monkeypatch.setattr("whymath_backend.api.me.compute_wh1_surrogate_metrics", _fake_compute)
        body = _client_with_auth().get(_ENDPOINT).json()
        brier = body["calibration_brier"]
        assert set(brier.keys()) == {"narrative"}
        assert brier["narrative"] == narrate_calibration_brier(value)
        assert "value" not in brier


class TestReachCounterIndependence:
    def test_harness_metrics_and_growth_evidence_counted_separately(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _fake_compute(*_args: Any, **_kwargs: Any) -> SurrogateMetrics:
            return _surrogate_metrics()

        monkeypatch.setattr("whymath_backend.api.me.compute_wh1_surrogate_metrics", _fake_compute)
        client = _client_with_auth()

        n_harness, m_growth = 2, 5
        for _ in range(n_harness):
            resp = client.get("/v1/me/harness-metrics")
            assert resp.status_code == 200
        for _ in range(m_growth):
            resp = client.get(_ENDPOINT)
            assert resp.status_code == 200

        ready = client.get("/health/ready").json()
        assert ready["growth_evidence"]["requests_total"] == n_harness
        assert ready["growth_evidence_exposure"]["requests_total"] == m_growth


class TestQueryParams:
    def test_since_until_mode_accepted_and_forwarded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        async def _fake_compute(session: Any, **kwargs: Any) -> SurrogateMetrics:
            captured.update(kwargs)
            return _surrogate_metrics()

        monkeypatch.setattr("whymath_backend.api.me.compute_wh1_surrogate_metrics", _fake_compute)
        client = _client_with_auth()
        resp = client.get(
            _ENDPOINT,
            params={
                "since": "2026-01-01T00:00:00+09:00",
                "until": "2026-06-01T00:00:00+09:00",
                "mode": "suneung",
            },
        )
        assert resp.status_code == 200
        assert captured["user_id"] == _UID
        assert captured["since"].isoformat() == "2026-01-01T00:00:00+09:00"
        assert captured["until"].isoformat() == "2026-06-01T00:00:00+09:00"
        assert captured["mode"] == "suneung"

    def test_bad_mode_value_is_422(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _fake_compute(*_args: Any, **_kwargs: Any) -> SurrogateMetrics:
            return _surrogate_metrics()

        monkeypatch.setattr("whymath_backend.api.me.compute_wh1_surrogate_metrics", _fake_compute)
        client = _client_with_auth()
        resp = client.get(_ENDPOINT, params={"mode": "not-a-real-mode"})
        assert resp.status_code == 422


class TestSchemaStructuralProof:
    """런타임 입력과 무관하게 OpenAPI 스키마 자체가 금지 필드 0종임을 증명."""

    def _all_properties(self) -> set[str]:
        schema = GrowthEvidenceResponse.model_json_schema()
        props = set(schema.get("properties", {}))
        for definition in schema.get("$defs", {}).values():
            props |= set(definition.get("properties", {}))
        return props

    def test_internal_only_fields_absent_from_schema(self) -> None:
        props = self._all_properties()
        assert "diagnosis_agreement_rate" not in props
        assert "tokens_per_turn" not in props

    def test_declared_top_level_fields_present(self) -> None:
        schema = GrowthEvidenceResponse.model_json_schema()
        assert set(schema["properties"]) == _DECLARED_FIELDS


class TestResolutionRateProvisionalSuppression:
    """MISC-20 ⑤ 집행 지점 — 강등이 `GET /v1/me/growth-evidence` 응답에 실제로 반영된다.

    티어 상수만 바꾸고 서빙 확인을 생략하면 미완(CLAUDE.md "정본화≠집행"). 계약이 ⑩을
    PROVISIONAL(근사·노출 보류)로 판정하면 서빙 층은 value를 null로 강제하고, 계약 모듈의
    내부 문구 대신 *서빙 층이 소유한 학생 대면 문장*을 `suppressed_reason`으로 낸다
    (hint_depth_reached 랜드마인 방어와 동형 — 검수 안 된 내부 문구를 학생에게 흘리지 않는다).
    """

    def test_value_null_and_student_facing_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _fake_compute(*_args: Any, **_kwargs: Any) -> SurrogateMetrics:
            return _surrogate_metrics()  # ⑩ value=0.5 MEASURED — 계약이 보류하면 흘러가면 안 된다

        monkeypatch.setattr("whymath_backend.api.me.compute_wh1_surrogate_metrics", _fake_compute)
        body = _client_with_auth().get(_ENDPOINT).json()
        view = body["misconception_resolution_rate"]
        assert view["value"] is None, "강등된 근사값이 학생 응답에 흘러갔다"
        assert view["exposable_now"] is False
        assert view["status"] == "measured"  # 계측 상태는 정직하게 그대로(삭제 아님)
        reason = view["suppressed_reason"]
        assert isinstance(reason, str) and reason
        # 계약 모듈 내부 문구(재승격·is_active 등 내부 용어)가 아니라 서빙 층 소유 문장이다.
        assert "재승격" not in reason
        assert "is_active" not in reason
        assert "deactivated_reason" not in reason

    def test_field_still_present_in_schema_not_structurally_removed(self) -> None:
        """② 강등은 삭제가 아니다 — 필드는 남고 값만 보류(INTERNAL_ONLY의 구조적 배제와 다르다)."""
        assert "misconception_resolution_rate" in GrowthEvidenceResponse.model_fields

    def test_other_metrics_unaffected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _fake_compute(*_args: Any, **_kwargs: Any) -> SurrogateMetrics:
            return _surrogate_metrics()

        monkeypatch.setattr("whymath_backend.api.me.compute_wh1_surrogate_metrics", _fake_compute)
        body = _client_with_auth().get(_ENDPOINT).json()
        for field in ("verify_pass_rate", "mastery_gain_rate", "self_solve_rate"):
            assert body[field]["value"] == 0.5, field
            assert body[field]["exposable_now"] is True, field
            assert body[field]["suppressed_reason"] is None, field
