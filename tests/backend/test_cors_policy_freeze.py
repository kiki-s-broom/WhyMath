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
