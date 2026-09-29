"""서빙 경로 — 학생 답에 `9^9^9` 류를 보내도 빨리 '판정 불가'로 끝나고 500이 아니다(CONST-09).

재현(2026-09-29): `/v1/verify-answer`·`/v1/verify-step`이 부르는 `verify_answer`·`verify_step`에
다섯 글자 `9^9^9`를 넣으면 20초 timeout까지 끝나지 않았다(≈3억 7천만 자리 정수 계산). 안전
진입점(`l3/safe_parse.py`) 뒤로는 기존 '판정 불가' 경로(`unverifiable` + `parse_error` 사유 코드)로
끝나야 한다 — 새 응답 필드는 없다. 학생 화면은 기존 `parse_error` 분기 문구("읽지 못한 단계가
있어요 — 표기를 한 번 확인해볼까요?")를 그대로 쓴다.

클라이언트 조립은 `test_verify.py`와 같은 패턴(인증 오버라이드·가짜 세션)이다 — 테스트 모듈 간
import를 피하려고 작은 조립 함수만 되풀이한다.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from whymath_backend.api._auth import get_consented_user
from whymath_backend.app import create_app
from whymath_backend.config import Settings, get_settings
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.schema.enums import Persona
from whymath_backend.schema.user import UserProfile as UserProfileSchema

_UID = uuid.uuid4()
# 응답 시간 상한(초) — 재현표에서는 20초 timeout이었다. 앱 조립·직렬화까지 포함한 여유값.
# '멈춤 부류' 상한(초) — 재현표의 20초 timeout 부류만 가른다(정상 실측 최대 0.35초). 부하에 따라
# 흔들리는 좁은 상한은 쓰지 않는다 — 계산 전 거부의 결정론적 증거는 단위 테스트
# (`tests/backend/l3/test_safe_parse.py`의 `forbid_evaluation`)가 호출 사실로 본다.
_PROMPT_S = 5.0
# 부정적 강화 금지(CLAUDE.md) — 학생에게 닿을 수 있는 사유 문장에 들어가면 안 되는 표현.
_NEGATIVE_WORDS = ("틀렸", "못 한", "못한다", "잘못")

_ADVERSARIAL = ("9^9^9", "9**9**9", "(10^9)!", "(x+y+z+w+v)^60")


def _settings_override() -> Settings:
    return Settings(jwt_secret_key=SecretStr("test-secret-0123456789abcdef"))


def _user() -> UserProfile:
    return UserProfile.from_schema(
        UserProfileSchema(user_id=_UID, persona_primary=Persona.A_일반고고3)
    )


class _FakeSession:
    """stateless 라우터용 — DB 쿼리 시 AssertionError(real get_session 누수 차단)."""

    async def execute(self, stmt: Any) -> None:
        raise AssertionError("verify 라우터(stateless)는 DB 쿼리하지 않아야 한다.")


def _client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_consented_user] = _user
    app.dependency_overrides[get_settings] = _settings_override

    async def _sess() -> AsyncIterator[_FakeSession]:
        yield _FakeSession()

    app.dependency_overrides[get_session] = _sess
    return TestClient(app, raise_server_exceptions=False)


def _assert_no_negative_wording(reason: str | None) -> None:
    for word in _NEGATIVE_WORDS:
        assert word not in (reason or ""), f"사유 문장에 부정적 표현 {word!r}: {reason!r}"


@pytest.mark.parametrize("text", _ADVERSARIAL)
def test_verify_answer_with_adversarial_student_answer(text: str) -> None:
    """학생 답(치환맵 값)에 적대 입력 — 200·unverifiable·빠른 응답."""
    client = _client()
    started = time.perf_counter()
    resp = client.post("/v1/verify-answer", json={"conditions": "x = 3", "answer": {"x": text}})
    elapsed = time.perf_counter() - started
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == "unverifiable"
    assert elapsed < _PROMPT_S, f"{elapsed:.2f}s"
    _assert_no_negative_wording(body["reason"])


@pytest.mark.parametrize("text", _ADVERSARIAL)
def test_verify_step_with_adversarial_student_step(text: str) -> None:
    """풀이 단계에 적대 입력 — 200·unverifiable·사유 코드 parse_error(학생 화면 기존 분기)."""
    client = _client()
    started = time.perf_counter()
    resp = client.post("/v1/verify-step", json={"expr_before": text, "expr_after": "1"})
    elapsed = time.perf_counter() - started
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == "unverifiable"
    assert body["reason_code"] == "parse_error"
    assert elapsed < _PROMPT_S, f"{elapsed:.2f}s"
    _assert_no_negative_wording(body["reason"])


def test_verify_answer_code_execution_payload_is_not_run(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """영문자·숫자·괄호·`+`만으로 된 코드 실행 입력 — 실행되지 않고 unverifiable."""
    monkeypatch.chdir(tmp_path)
    marker = tmp_path / "m"
    code = f"open({marker.name!r},'w')"
    payload = "exec(" + "+".join(f"chr({ord(ch)})" for ch in code) + ")"
    resp = _client().post(
        "/v1/verify-answer", json={"conditions": "x = 3", "answer": {"x": payload}}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "unverifiable"
    assert not marker.exists(), "학생 입력이 서버에서 코드로 실행됐다"


def test_normal_answer_still_verifies() -> None:
    """대조군 — 정상 답은 그대로 pass(가드가 정상 경로를 막지 않는다)."""
    resp = _client().post("/v1/verify-answer", json={"conditions": "x^2 = 9", "answer": {"x": "3"}})
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "pass"
