"""CORS 정책 결정(SEC-26, 2026-09-11 갱신) 동결.

원 결정(2026-08-11, SEC-24(원 SEC-18)): 미들웨어 없음 — 학생 클라가 Flutter 네이티브 앱이라
브라우저 CORS가 적용되지 않는다(네이티브 앱은 브라우저 Same-Origin 정책의 적용 대상이 아니다).

**갱신 결정(SEC-26)**: `src/web/`(웹 클라)가 이 저장소에 실재하게 됐고, 48_보안 §P0가
"CORS/보안 헤더 미들웨어 없음"을 갭으로 명시했다(`docs/architecture/48_eos_security_access_
control.md` L829). 이제 CORSMiddleware를 *항상* 등록하되(`whymath_backend.app.create_app`),
`Settings.cors_allowed_origins`(기본 빈 문자열)로 deny-by-default를 유지한다 — 빈 allowlist는
원 결정과 실질적으로 동치다(모든 브라우저 cross-origin 요청을 거부·네이티브 앱은 미영향).
`allow_origins=["*"]`와 `allow_credentials=True`의 동시 설정은 `Settings` 부팅 시점에
`ValidationError`로 거부된다(`test_config.py::test_cors_wildcard_with_credentials_rejected_at_boot`).

이 테스트가 실패하면(=CORSMiddleware가 제거되거나 기본 allowlist가 비명시적으로 넓어짐) 이
결정이 조용히 우회된 것이므로 회귀다.

**ADMIN-06 추가 축 — `/v1/admin/menu`의 실 프리플라이트**: 위 두 검사는 `/health`로 미들웨어
*자체*를 본다. 그런데 브라우저 백오피스 셸이 처음 보내는 요청은 `Authorization` 헤더를 단
cross-origin GET이고, 그 프리플라이트는 `Access-Control-Request-Headers: authorization`을
함께 보낸다 — 즉 allow-origin뿐 아니라 **allow-headers까지 맞아야** 실제로 열린다. 미들웨어가
살아 있어도 이 조합이 막히면 셸은 원인 없는 실패를 본다(브라우저가 차단된 응답을 JS에 넘기지
않으므로 서버 로그에는 200만 찍힌다). 그래서 web_strategy §4-4가 CORS의 집행 시점으로 지목한
바로 그 경로·바로 그 헤더 조합을 여기서 동결한다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

from whymath_backend.app import create_app
from whymath_backend.config import get_settings
from whymath_backend.l3.interfaces import InMemoryCache, RecordingTraceSink


class _StubProvider:
    async def check_status(self) -> object:  # pragma: no cover — 헬스체크 미사용 경로
        raise NotImplementedError


class _StubQueue:
    async def health_check(self) -> bool:  # pragma: no cover — 헬스체크 미사용 경로
        return True


def _client() -> TestClient:
    app = create_app(
        provider=_StubProvider(),
        cache=InMemoryCache(),
        trace=RecordingTraceSink(),
        queue=_StubQueue(),
    )
    return TestClient(app)


class TestCorsPolicyFreeze:
    def test_current_app_has_cors_middleware(self) -> None:
        """SEC-26 갱신 결정 동결 — 실 `create_app()`에 CORSMiddleware가 *있다*."""
        app = create_app(
            provider=_StubProvider(),
            cache=InMemoryCache(),
            trace=RecordingTraceSink(),
            queue=_StubQueue(),
        )
        assert any(m.cls is CORSMiddleware for m in app.user_middleware)

    def test_default_denies_unlisted_origin(self) -> None:
        """기본(미설정) → allowlist 없는 origin의 cross-origin 요청은 CORS 헤더를 못 받는다.

        실제 preflight(OPTIONS + Origin + Access-Control-Request-Method)를 보내 CORSMiddleware가
        `Access-Control-Allow-Origin`을 응답에 넣지 않는지 확인한다 — "항상 통과하는 위장
        검사"가 아님을 증명하기 위해 아래 테스트가 같은 요청에 허용 origin을 설정해 대조한다.
        """
        get_settings.cache_clear()
        try:
            resp = _client().options(
                "/health",
                headers={
                    "Origin": "https://evil.example.com",
                    "Access-Control-Request-Method": "GET",
                },
            )
            assert "access-control-allow-origin" not in {k.lower() for k in resp.headers}
        finally:
            get_settings.cache_clear()

    def test_configured_origin_is_allowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """WHYMATH_CORS_ALLOWED_ORIGINS에 명시된 origin은 preflight가 허용 응답을 받는다.

        위 거부 테스트와 짝을 이루는 결함주입 대조 — 같은 술어(CORS 헤더 존재 여부)가
        설정에 따라 실제로 갈린다는 것을 증명한다.
        """
        monkeypatch.setenv("WHYMATH_CORS_ALLOWED_ORIGINS", "https://admin.whymath.kr")
        get_settings.cache_clear()
        try:
            resp = _client().options(
                "/health",
                headers={
                    "Origin": "https://admin.whymath.kr",
                    "Access-Control-Request-Method": "GET",
                },
            )
            assert resp.headers.get("access-control-allow-origin") == "https://admin.whymath.kr"
        finally:
            get_settings.cache_clear()


class TestAdminMenuPreflightForWebShell:
    """ADMIN-06 — 백오피스 셸이 실제로 보내는 프리플라이트가 origin에 따라 갈린다.

    두 테스트가 서로의 대조군이다(같은 요청·같은 술어, 설정만 다르다). 한쪽만 두면
    "전부 막힌다"·"전부 열린다" 양쪽 오구현이 통과한다.
    """

    _ORIGIN = "https://admin.internal.whymath.kr"
    _PATH = "/v1/admin/menu"

    def _preflight(self, client: TestClient) -> object:
        return client.options(
            self._PATH,
            headers={
                "Origin": self._ORIGIN,
                "Access-Control-Request-Method": "GET",
                # 셸은 Bearer 토큰을 헤더로 보낸다 → 프리플라이트에 이 줄이 반드시 붙는다.
                "Access-Control-Request-Headers": "authorization",
            },
        )

    def test_unlisted_origin_is_denied(self) -> None:
        """기본(deny-by-default) — allowlist에 없으면 CORS 허용 헤더가 나오지 않는다."""
        get_settings.cache_clear()
        try:
            resp = self._preflight(_client())
            assert "access-control-allow-origin" not in {k.lower() for k in resp.headers}
        finally:
            get_settings.cache_clear()

    def test_listed_origin_is_allowed_including_authorization_header(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """allowlist에 넣으면 같은 프리플라이트가 origin + Authorization 허용을 받는다."""
        monkeypatch.setenv("WHYMATH_CORS_ALLOWED_ORIGINS", self._ORIGIN)
        get_settings.cache_clear()
        try:
            resp = self._preflight(_client())
            assert resp.headers.get("access-control-allow-origin") == self._ORIGIN
            allowed_headers = resp.headers.get("access-control-allow-headers", "").lower()
            assert "authorization" in allowed_headers or "*" in allowed_headers, (
                "Authorization 프리플라이트가 거부됐다 — 셸의 첫 요청이 브라우저에서 막힌다: "
                + allowed_headers
            )
        finally:
            get_settings.cache_clear()
