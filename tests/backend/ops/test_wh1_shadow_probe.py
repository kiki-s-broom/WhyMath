"""wh1_shadow_probe 합성 트래픽 드라이버 hermetic 테스트 — 라이브 0(httpx.MockTransport).

실물 표면 검증 2종을 동결한다:
  ① 페이로드가 *실 스키마*(`SessionCreateRequest`/`CoachRequest`·extra="forbid")에 유효한지 —
     프로브가 dict로 보내는 바디를 실제 pydantic 모델로 검증(시임 페이로드 금지).
  ② 대표 3모양이 실제로 의도한 verdict 구간인지 — `verify_step` *실물*(SymPy)로 오전개
     스텝이 진짜 틀렸는지(incorrect), 동치 스텝이 진짜 맞는지(correct), 해집합 보존 방정식
     체인이 진짜 맞는지(correct·S3-02 이후) 동결한다(가짜 모양이 분포를 오염시키지 않게).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field

import httpx
import pytest
from pydantic import ValidationError

from whymath_backend.api.coach import CoachRequest, SessionCreateRequest
from whymath_backend.l3.verify_step import VerifyStepState, verify_step
from whymath_backend.ops import wh1_shadow_probe as probe
from whymath_backend.schema.auth import OAuthCallbackRequest


# ──────────────────────────────────────────────────────────────────────────
# MockTransport — 요청 캡처 + 경로별 스크립트 응답(라이브 0)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(slots=True)
class _Server:
    """가짜 서버 — 요청을 캡처하고 경로별로 스크립트된 응답을 낸다."""

    auth_status: int = 200
    state_status: int = 200
    session_status: int = 201
    turn_status: int = 201
    requests: list[httpx.Request] = field(default_factory=list)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/v1/auth/demo/state":
            return httpx.Response(self.state_status, json={"state": "state-abc"})
        if path == "/v1/auth/demo/callback":
            # 무조건 200을 돌려주는 대역 금지(OPS-111 ②) — 서버 스키마로 바디를 검증해 거부한다.
            # SEC-08 이후 state는 필수이고 서버가 발급한 값이어야 한다(미동봉·불일치 → 거부).
            try:
                body = OAuthCallbackRequest.model_validate(json.loads(request.content))
            except ValidationError:
                return httpx.Response(422, json={"detail": "schema"})
            if body.state != "state-abc":
                return httpx.Response(400, json={"detail": "state mismatch"})
            return httpx.Response(
                self.auth_status,
                json={"access_token": "demo-token", "refresh_token": "r", "token_type": "bearer"},
            )
        if path == "/v1/coach/sessions":
            return httpx.Response(self.session_status, json={"dialogue_id": str(uuid.uuid4())})
        if path.startswith("/v1/coach/sessions/") and path.endswith("/turns"):
            return httpx.Response(self.turn_status, json={})
        return httpx.Response(404, json={})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler), base_url="http://test")

    def coach_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path.startswith("/v1/coach/")]

    def auth_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == "/v1/auth/demo/callback"]


def _body(request: httpx.Request) -> dict[str, object]:
    loaded = json.loads(request.content.decode("utf-8"))
    assert isinstance(loaded, dict)
    return loaded


# ──────────────────────────────────────────────────────────────────────────
# 대표 3모양 — verify_step 실물로 verdict 구간 동결(가짜 모양 금지)
# ──────────────────────────────────────────────────────────────────────────
def _step_states(payload: dict[str, object]) -> list[VerifyStepState]:
    steps = payload["solution_steps"]
    assert isinstance(steps, list) and len(steps) >= 2
    return [verify_step(steps[i], steps[i + 1]).state for i in range(len(steps) - 1)]


def test_misexpansion_steps_actually_wrong() -> None:
    """bad 모양의 오전개 스텝은 실제로 틀린 수식이다(SymPy 실물 incorrect)."""
    for payload in probe.MISEXPANSION_SHAPE.payloads:
        states = _step_states(payload)
        assert VerifyStepState.incorrect in states, payload["solution_steps"]


def test_expression_steps_actually_correct() -> None:
    """expr 모양의 동치 스텝은 실제로 맞는 수식이다(SymPy 실물 correct — 결정 구간)."""
    for payload in probe.EXPRESSION_EQUIVALENCE_SHAPE.payloads:
        assert all(s == VerifyStepState.correct for s in _step_states(payload))


def test_equation_chain_is_correct() -> None:
    """eq 모양(해집합 보존 방정식 체인)은 verify_step이 correct로 판정한다(S3-02 이후 동결).

    S3-02(방향 B) 전에는 등호 방정식 단계가 파싱 실패로 전부 unverifiable였다(shadow 89%
    unverifiable의 근본원인). 이제 해집합 보존 동치로 판정하므로, 이 대표 모양(모두 해집합이
    보존되는 정당한 풀이 체인)은 전 전이 correct다 — 방정식 verify가 실제로 동작함을 동결한다.
    """
    for payload in probe.EQUATION_CHAIN_SHAPE.payloads:
        assert all(s == VerifyStepState.correct for s in _step_states(payload))


def test_all_shape_payloads_valid_against_real_schema() -> None:
    """모든 페이로드가 실 스키마에 유효 + 전 턴 solution_steps 동봉(verify 의무 발동 조건)."""
    for shape in probe.SHAPES.values():
        SessionCreateRequest.model_validate(shape.payloads[0])
        for payload in shape.payloads[1:]:
            CoachRequest.model_validate(payload)
        for payload in shape.payloads:
            steps = payload["solution_steps"]
            assert isinstance(steps, list) and len(steps) >= 2


# ──────────────────────────────────────────────────────────────────────────
# 믹스 파싱·계획 — 순수 코어
# ──────────────────────────────────────────────────────────────────────────
def test_parse_mix_default() -> None:
    assert probe.parse_mix(probe.DEFAULT_MIX) == {"eq": 2, "expr": 2, "bad": 1}


def test_parse_mix_rejects_bad_specs() -> None:
    """알 수 없는 라벨·개수 불일치·비정수·합 0은 명시 거부(빈 측정을 조용히 만들지 않음)."""
    with pytest.raises(ValueError):
        probe.parse_mix("eq:unknown=1:1")
    with pytest.raises(ValueError):
        probe.parse_mix("eq:expr=1")
    with pytest.raises(ValueError):
        probe.parse_mix("eq=abc")
    with pytest.raises(ValueError):
        probe.parse_mix("eq:expr:bad=0:0:0")
    with pytest.raises(ValueError):
        probe.parse_mix("eq:expr:bad,2:2:1")  # '=' 없음


def test_build_plan_expands_mix_and_rounds() -> None:
    """라운드당 믹스 합만큼 펼쳐지고 rounds가 전체를 배수한다(cost_probe 미러)."""
    plan = probe.build_probe_plan({"eq": 2, "expr": 2, "bad": 1}, 3)
    assert len(plan) == 5 * 3
    labels = [s.label for s in plan[:5]]
    assert labels == ["eq", "eq", "expr", "expr", "bad"]


def test_build_plan_rejects_zero_rounds() -> None:
    with pytest.raises(ValueError):
        probe.build_probe_plan({"eq": 1}, 0)


# ──────────────────────────────────────────────────────────────────────────
# run_probe — 제출 수·페이로드·토큰 경로·오류 회계(MockTransport)
# ──────────────────────────────────────────────────────────────────────────
def test_default_mix_submission_counts_and_payloads() -> None:
    """기본 믹스 1라운드: 세션 5·턴 10, 전 코치 요청에 solution_steps·Bearer 헤더."""
    server = _Server()
    with server.client() as client:
        report = probe.run_probe(
            base_url="http://test", rounds=1, token="tkn", client=client, delay_s=0
        )
    assert report.sessions_submitted == {"eq": 2, "expr": 2, "bad": 1}
    assert report.turns_submitted == {"eq": 4, "expr": 4, "bad": 2}
    assert report.total_errors == 0
    assert report.token_auto_issued is False
    assert server.auth_requests() == []  # --token 주입 시 데모 콜백 미호출
    coach = server.coach_requests()
    assert len(coach) == 5 + 10
    for request in coach:
        assert request.headers["Authorization"] == "Bearer tkn"
        body = _body(request)
        steps = body.get("solution_steps")
        assert isinstance(steps, list) and len(steps) >= 2  # 전 턴 verify 의무 발동 조건


def test_captured_bodies_valid_against_real_schema() -> None:
    """와이어에 실린 바디 그대로 실 스키마 검증 — 직렬화 경로까지 유효성 동결."""
    server = _Server()
    with server.client() as client:
        probe.run_probe(base_url="http://test", rounds=1, token="tkn", client=client, delay_s=0)
    for request in server.coach_requests():
        body = _body(request)
        if request.url.path == "/v1/coach/sessions":
            SessionCreateRequest.model_validate(body)
        else:
            CoachRequest.model_validate(body)


def test_token_auto_issued_via_demo_callback() -> None:
    """--token 미지정 → 데모 콜백 1회 호출·발급 토큰으로 코치 요청 인증."""
    server = _Server()
    with server.client() as client:
        report = probe.run_probe(base_url="http://test", rounds=1, client=client, delay_s=0)
    assert report.token_auto_issued is True
    assert len(server.auth_requests()) == 1
    assert all(r.headers["Authorization"] == "Bearer demo-token" for r in server.coach_requests())


def test_token_issue_sends_server_issued_state_in_callback_body() -> None:
    """OPS-111 ① — state를 먼저 GET으로 받아 콜백 바디에 싣는다(run_demo.ps1과 같은 순서)."""
    server = _Server()
    with server.client() as client:
        assert probe.issue_demo_token(client) == "demo-token"
    paths = [r.url.path for r in server.requests]
    assert paths == ["/v1/auth/demo/state", "/v1/auth/demo/callback"]
    assert _body(server.auth_requests()[0])["state"] == "state-abc"


def test_callback_double_rejects_body_without_state() -> None:
    """OPS-111 ② — 대역이 서버 스키마로 검증한다: state 없는 바디는 422(라이브 실패의 재현)."""
    server = _Server()
    with server.client() as client:
        resp = client.post("/v1/auth/demo/callback", json={"code": "demo", "redirect_uri": "x"})
    assert resp.status_code == 422


def test_state_fetch_failure_raises_clear_guidance() -> None:
    """state 발급 비200 → 플래그 안내가 달린 ProbeAuthError(콜백은 시도하지 않는다)."""
    server = _Server(state_status=404)
    with server.client() as client:
        with pytest.raises(probe.ProbeAuthError, match="WHYMATH_DEMO_AUTH_ENABLED"):
            probe.issue_demo_token(client)
    assert server.auth_requests() == []


def test_auth_failure_raises_clear_guidance() -> None:
    """데모 콜백 비200 → ProbeAuthError에 플래그 안내(WHYMATH_DEMO_AUTH_ENABLED) 동봉."""
    server = _Server(auth_status=404)
    with server.client() as client:
        with pytest.raises(probe.ProbeAuthError, match="WHYMATH_DEMO_AUTH_ENABLED"):
            probe.run_probe(base_url="http://test", rounds=1, client=client, delay_s=0)


def test_turn_http_errors_accounted_never_break() -> None:
    """턴 500 → 상태코드별 회계·세션 회계는 보존·나머지 세션도 계속(never-break)."""
    server = _Server(turn_status=500)
    with server.client() as client:
        report = probe.run_probe(
            base_url="http://test", rounds=1, token="tkn", client=client, delay_s=0
        )
    assert report.sessions_submitted == {"eq": 2, "expr": 2, "bad": 1}
    assert report.turns_submitted == {}
    assert report.http_errors == {"500": 10}
    assert report.error_samples  # 표본 기록(최대 5건)


def test_session_create_failure_skips_turns() -> None:
    """세션 생성 실패(비201) → 그 세션의 턴은 시도하지 않고 오류만 회계."""
    server = _Server(session_status=503)
    with server.client() as client:
        report = probe.run_probe(
            base_url="http://test", rounds=1, token="tkn", client=client, delay_s=0
        )
    assert report.sessions_submitted == {}
    assert report.http_errors == {"503": 5}
    # 코치 요청은 세션 생성 5건뿐(턴 0건).
    assert all(r.url.path == "/v1/coach/sessions" for r in server.coach_requests())
    assert len(server.coach_requests()) == 5


def test_mix_override_changes_plan() -> None:
    """--mix 오버라이드 — bad만 3세션이면 incorrect 유도 트래픽만 흐른다."""
    server = _Server()
    with server.client() as client:
        report = probe.run_probe(
            base_url="http://test", rounds=2, mix={"bad": 3}, token="tkn", client=client, delay_s=0
        )
    assert report.sessions_submitted == {"bad": 6}
    assert report.turns_submitted == {"bad": 12}


# ──────────────────────────────────────────────────────────────────────────
# 렌더 — verdict 비집계 원칙·harvest 안내
# ──────────────────────────────────────────────────────────────────────────
def test_render_mentions_harvest_and_synthetic_caveat() -> None:
    """출력에 '서버 로그가 진실'(harvest 안내)과 합성 트래픽 캐비엇이 명시된다."""
    server = _Server()
    with server.client() as client:
        report = probe.run_probe(
            base_url="http://test", rounds=1, token="tkn", client=client, delay_s=0
        )
    text = probe.render_report(report)
    assert "wh1_shadow_harvest" in text
    assert "합성 트래픽" in text
    # verdict 분포를 자체 집계·표기하지 않는다 — 제목에 'verdict 없음' 명시·집계 라벨 없음.
    assert "verdict 없음" in text
    assert "correct=" not in text and "incorrect=" not in text


def test_pacing_called_before_every_write() -> None:
    """쓰기 요청마다 페이싱 훅 호출 — rate limit 30/분 대응(2026-07-17 라이브 429 교훈).

    기본 믹스 1라운드 = 세션 5 + 턴 10 = 쓰기 15회 → sleeper가 delay_s로 15회 불린다.
    """
    server = _Server()
    sleeps: list[float] = []
    with server.client() as client:
        probe.run_probe(
            base_url="http://test",
            rounds=1,
            token="tkn",
            client=client,
            delay_s=2.5,
            sleeper=sleeps.append,
        )
    assert sleeps == [2.5] * 15


def test_zero_delay_never_sleeps() -> None:
    """delay_s=0이면 sleeper가 한 번도 불리지 않는다(테스트·rate limit 비활성 환경)."""
    server = _Server()
    sleeps: list[float] = []
    with server.client() as client:
        probe.run_probe(
            base_url="http://test",
            rounds=1,
            token="tkn",
            client=client,
            delay_s=0,
            sleeper=sleeps.append,
        )
    assert sleeps == []
