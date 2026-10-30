"""학생 의도 섀도 관측(PED-48) 단위테스트 — hermetic·라이브 서버 0·DB 0.

검증 축 (태스크 acceptance 번호 · 리뷰 지적 번호):
- ① 설정 게이트: 켰는데 URL·키가 비면 *부팅 거부*(리뷰 #3). URL은 내부망 기준 URL만(#6).
- ② 비노출·비차단: 공개 함수는 None, 어떤 실패도 예외로 새지 않는다. 흡수한 예외는 타입명을 남긴다.
  동시 판정 상한을 넘으면 호출 없이 `Overloaded` 레코드(#5). 환경 프록시를 무시한다(#1).
- ③ 레코드: 성공·실패·건너뜀 모두 1건. 학생 원문·식별자 필드가 없다(필드 집합 동결). 관측 시각은
  시 단위 절삭(#12). 레코드 로거는 측정용 로그 설정에서 실제로 파일에 캡처된다(#2).
- ④ 집행 지점(정적): coach 두 핸들러가 *커밋 뒤에*, DB에 적재한 그 값과 *원 발화*로 부른다(#9).
- ⑤ 실패 주입: 총 시간 초과(#8)·단계 타임아웃·연결 거부·401·503·JSON 손상·스키마 위반·예상 밖 예외.
  실물 laya-serve 응답 픽스처로 경계 스키마를 검증한다(#7).

**HTTP 대역**: 대부분은 `httpx.MockTransport`를 끼운 *실물* `httpx.AsyncClient`다. 프록시 축은
MockTransport로는 볼 수 없으므로(전송 계층을 갈아끼우면 프록시 결정이 사라진다) 루프백에 실제
소켓 서버를 띄우고 기본 팩토리 그대로 호출한다.
"""

from __future__ import annotations

import ast
import asyncio
import gc
import hashlib
import json
import logging
import logging.config
import warnings
from collections.abc import Callable, Coroutine, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from whymath_backend.api import _intent_shadow as shadow
from whymath_backend.config import Settings, get_settings
from whymath_backend.schema.enums import StudentIntent

_REPO = Path(__file__).resolve().parents[3]
_RECORD_LOGGER = "whymath.api.intent_shadow.record"
_PLAIN_LOGGER = "whymath.api.intent_shadow"
_URL = "http://127.0.0.1:18080"
_KEY = "test-key-0123456789abcdef0123456789abcdef"
# 레코드·로그에 이 문자열이 나타나면 원문 누출이다 — 이름·학교·번호를 일부러 섞는다.
_STUDENT_TEXT = "저 새솔중 박지호인데요 010-1111-2222 이거 답만 알려주세요"
_ENV_KEYS = (
    "WHYMATH_LAYA_INTENT_SHADOW_ENABLED",
    "WHYMATH_LAYA_INTENT_SHADOW_URL",
    "WHYMATH_LAYA_INTENT_SHADOW_API_KEY",
    "WHYMATH_LAYA_INTENT_SHADOW_TIMEOUT_S",
)

# 실물 laya-serve 0.4.15 + laya-ko-whymath v1 응답(2026-10-28 캡처) — 손으로 쓴 모의 응답이 아니다.
_REAL = json.loads(
    (_REPO / "tests/backend/api/fixtures/laya_systemone_responses.json").read_text(encoding="utf-8")
)["responses"]
_OK_BODY: dict[str, Any] = _REAL["pii"]


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """전역 Settings 캐시·클라이언트 팩토리·동시 판정 카운터·환경변수 누수 차단."""
    for k in _ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    get_settings.cache_clear()
    shadow._in_flight = 0
    yield
    shadow.set_client_factory(None)
    shadow._in_flight = 0
    get_settings.cache_clear()


def _configure(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    env = {
        "WHYMATH_LAYA_INTENT_SHADOW_ENABLED": "true",
        "WHYMATH_LAYA_INTENT_SHADOW_URL": _URL,
        "WHYMATH_LAYA_INTENT_SHADOW_API_KEY": _KEY,
    }
    env.update(overrides)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()


class _Captured:
    """`_intent_shadow._spawn` 대체 — 코루틴을 모아 두고 응답 후 동기 구동(비결정성 제거)."""

    def __init__(self) -> None:
        self.coros: list[Coroutine[Any, Any, None]] = []

    def __call__(self, coro: Coroutine[Any, Any, None]) -> None:
        self.coros.append(coro)

    def drive(self) -> None:
        for coro in self.coros:
            asyncio.run(coro)
        self.coros.clear()

    def close(self) -> None:
        for coro in self.coros:
            coro.close()
        self.coros.clear()


def _capture_spawn(monkeypatch: pytest.MonkeyPatch) -> _Captured:
    cap = _Captured()
    monkeypatch.setattr(shadow, "_spawn", cap)
    return cap


Handler = Callable[[httpx.Request], Any]


def _use_transport(handler: Handler) -> list[httpx.Request]:
    """MockTransport를 끼운 실물 AsyncClient로 교체 — 받은 요청을 돌려준다(요청 본문 검사용)."""
    seen: list[httpx.Request] = []

    async def _record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        result = handler(request)
        if asyncio.iscoroutine(result):
            result = await result
        assert isinstance(result, httpx.Response)
        return result

    shadow.set_client_factory(
        lambda t: httpx.AsyncClient(transport=httpx.MockTransport(_record), timeout=t)
    )
    return seen


def _run(**overrides: Any) -> None:
    kwargs: dict[str, Any] = {
        "student_input": _STUDENT_TEXT,
        "rule_intent": StudentIntent.포기,
        "has_solution": False,
        "route": "append_turns",
        "url": _URL,
        "api_key": _KEY,
        "timeout_s": 2.0,
    }
    kwargs.update(overrides)
    asyncio.run(shadow.observe_intent_shadow(**kwargs))


def _records(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    return [json.loads(r.getMessage()) for r in caplog.records if r.name == _RECORD_LOGGER]


def _all_log_text(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(r.getMessage() for r in caplog.records)


# ──────────────────────────────────────────────────────────────────────────
# 질문지 동결 — 학습 때 질문지와 다르면 정확도 근거가 성립하지 않는다
# ──────────────────────────────────────────────────────────────────────────


def test_questions_are_byte_identical_to_trained_v1() -> None:
    """laya-ko-whymath v1 학습 질문지(questions_v1.json)의 정규화 sha256 고정값과 대조한다."""
    canonical = json.dumps(
        shadow.LAYA_QUESTIONS, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    assert (
        hashlib.sha256(canonical.encode()).hexdigest()
        == "9d28d2a73abd76aeee566ec68c973d711d66cbb3b3020ce80869ddab3b9c43df"
    )
    assert shadow.QUESTIONS_VERSION == "questions_v1"


# ──────────────────────────────────────────────────────────────────────────
# ① 설정 게이트 — 부팅 시 검증 (리뷰 #3·#6)
# ──────────────────────────────────────────────────────────────────────────


def test_default_settings_are_off() -> None:
    """기본값(환경변수 없음)은 꺼짐 — opt-in."""
    s = get_settings()
    assert s.laya_intent_shadow_enabled is False
    assert shadow.shadow_configured(s) is False


@pytest.mark.parametrize(
    ("overrides", "missing"),
    [
        ({"WHYMATH_LAYA_INTENT_SHADOW_URL": ""}, "WHYMATH_LAYA_INTENT_SHADOW_URL"),
        ({"WHYMATH_LAYA_INTENT_SHADOW_URL": "   "}, "WHYMATH_LAYA_INTENT_SHADOW_URL"),
        ({"WHYMATH_LAYA_INTENT_SHADOW_API_KEY": ""}, "WHYMATH_LAYA_INTENT_SHADOW_API_KEY"),
        ({"WHYMATH_LAYA_INTENT_SHADOW_API_KEY": "  "}, "WHYMATH_LAYA_INTENT_SHADOW_API_KEY"),
    ],
)
def test_enabled_but_half_configured_refuses_to_boot(
    monkeypatch: pytest.MonkeyPatch, overrides: dict[str, str], missing: str
) -> None:
    _configure(monkeypatch, **overrides)
    with pytest.raises(ValidationError) as exc:
        get_settings()
    assert missing in str(exc.value)
    assert _KEY not in str(exc.value)  # 메시지에 키 값이 실리지 않는다


def test_disabled_with_empty_fields_boots() -> None:
    """꺼져 있으면 URL·키가 비어도 정상 부팅(기본 상태)."""
    s = Settings(laya_intent_shadow_enabled=False, laya_intent_shadow_url="")
    assert shadow.shadow_configured(s) is False


@pytest.mark.parametrize(
    ("url", "stored"),
    [
        ("http://127.0.0.1:18080", "http://127.0.0.1:18080"),
        ("  http://127.0.0.1:18080/  ", "http://127.0.0.1:18080"),
        ("http://localhost:18080", "http://localhost:18080"),
        ("http://192.168.0.13:18080", "http://192.168.0.13:18080"),
        ("http://10.0.0.5:8000", "http://10.0.0.5:8000"),
        ("http://laya-ko-whymath:8000", "http://laya-ko-whymath:8000"),
        ("https://[::1]:18080", "https://[::1]:18080"),
    ],
)
def test_internal_base_urls_are_accepted_and_normalised(url: str, stored: str) -> None:
    s = Settings(laya_intent_shadow_url=url)
    assert s.laya_intent_shadow_url == stored


@pytest.mark.parametrize(
    "url",
    [
        "127.0.0.1:18080",  # 스킴 없음
        "ftp://127.0.0.1:18080",  # 스킴 불가
        "http://127.0.0.1:18080/v1",  # 경로 — /v1/v1/systemone 이 된다
        "http://127.0.0.1:18080?x=1",  # 쿼리
        "http://8.8.8.8:18080",  # 공인 IP
        "https://laya.example.com",  # 외부 도메인
        "http://",  # 호스트 없음
    ],
)
def test_external_or_malformed_urls_refuse_to_boot(url: str) -> None:
    with pytest.raises(ValidationError):
        Settings(laya_intent_shadow_url=url)


def test_api_key_whitespace_is_stripped_at_load() -> None:
    s = Settings(laya_intent_shadow_api_key=SecretStr(f"  {_KEY}\n"))
    assert s.laya_intent_shadow_api_key.get_secret_value() == _KEY


def test_shadow_configured_is_a_second_safety_net() -> None:
    """검증을 우회해 만든 Settings(model_construct)에서도 키·URL 없는 호출은 하지 않는다."""
    base = Settings()
    for url, key in (("", _KEY), (_URL, ""), ("", "")):
        bypass = base.model_copy(
            update={
                "laya_intent_shadow_enabled": True,
                "laya_intent_shadow_url": url,
                "laya_intent_shadow_api_key": SecretStr(key),
            }
        )
        assert shadow.shadow_configured(bypass) is False


# ──────────────────────────────────────────────────────────────────────────
# ② spawn — 꺼짐·빈 발화·상한·실패 흡수
# ──────────────────────────────────────────────────────────────────────────


def test_spawn_creates_no_task_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch, WHYMATH_LAYA_INTENT_SHADOW_ENABLED="false")
    cap = _capture_spawn(monkeypatch)
    shadow.spawn_intent_shadow(
        student_input=_STUDENT_TEXT, rule_intent=None, has_solution=False, route="create_session"
    )
    assert cap.coros == []


def test_spawn_skips_blank_input(monkeypatch: pytest.MonkeyPatch) -> None:
    """빈 발화(풀이만 제출)는 판정할 문장이 없다 — 실패 레코드를 만들지 않는다."""
    _configure(monkeypatch)
    cap = _capture_spawn(monkeypatch)
    shadow.spawn_intent_shadow(
        student_input="   ", rule_intent=None, has_solution=True, route="create_session"
    )
    assert cap.coros == []


def test_spawn_when_configured_schedules_one_task_and_returns_none(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _configure(monkeypatch)
    cap = _capture_spawn(monkeypatch)
    _use_transport(lambda _r: httpx.Response(200, json=_OK_BODY))
    result = shadow.spawn_intent_shadow(  # type: ignore[func-returns-value]
        student_input=_STUDENT_TEXT,
        rule_intent=StudentIntent.포기,
        has_solution=False,
        route="create_session",
    )
    assert result is None
    assert len(cap.coros) == 1
    assert shadow._in_flight == 1  # 자리를 잡았다
    with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
        cap.drive()
    assert shadow._in_flight == 0  # 판정이 끝나면 돌려준다
    (rec,) = _records(caplog)
    assert rec["route"] == "create_session"
    assert rec["laya_intent"] == "answer_only"


def test_overload_skips_call_and_records_it(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """동시 판정이 상한에 차면 laya를 부르지 않고 `Overloaded` 레코드 1건만 남긴다(분모 보존)."""
    _configure(monkeypatch)
    cap = _capture_spawn(monkeypatch)
    shadow._in_flight = shadow.MAX_IN_FLIGHT
    with caplog.at_level(logging.INFO):
        shadow.spawn_intent_shadow(
            student_input=_STUDENT_TEXT,
            rule_intent=StudentIntent.질문,
            has_solution=False,
            route="append_turns",
        )
    assert cap.coros == []
    (rec,) = _records(caplog)
    assert rec["failure"] == shadow.OVERLOADED
    assert rec["rule_intent"] == "질문"
    assert rec["laya_intent"] is None
    assert shadow._in_flight == shadow.MAX_IN_FLIGHT  # 건너뜀은 자리를 잡지 않는다


def test_in_flight_is_released_even_when_observe_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    shadow._in_flight = 1
    _use_transport(lambda _r: httpx.Response(503, text="busy"))
    _run()
    assert shadow._in_flight == 0


def test_spawn_failure_releases_slot_closes_coroutine_and_logs_type(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """`_spawn` 자체가 실패해도(루프 없음 등) 자리·코루틴을 정리하고 타입명을 남긴다."""
    _configure(monkeypatch)

    def _boom(_coro: object) -> None:
        raise RuntimeError("no running event loop")

    monkeypatch.setattr(shadow, "_spawn", _boom)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with caplog.at_level(logging.WARNING, logger=_PLAIN_LOGGER):
            shadow.spawn_intent_shadow(
                student_input=_STUDENT_TEXT,
                rule_intent=None,
                has_solution=False,
                route="append_turns",
            )
        gc.collect()
    assert shadow._in_flight == 0
    assert "RuntimeError" in _all_log_text(caplog)
    assert not [w for w in caught if "was never awaited" in str(w.message)]


def test_spawn_absorbs_settings_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """설정 조회가 터져도 본류로 새지 않고, 타입명이 경고에 남는다(침묵 실패 금지)."""

    def _boom() -> None:
        raise RuntimeError("settings broken")

    monkeypatch.setattr(shadow, "get_settings", _boom)
    with caplog.at_level(logging.WARNING, logger=_PLAIN_LOGGER):
        shadow.spawn_intent_shadow(
            student_input=_STUDENT_TEXT, rule_intent=None, has_solution=False, route="append_turns"
        )
    assert "RuntimeError" in _all_log_text(caplog)


# ──────────────────────────────────────────────────────────────────────────
# ③ 성공 레코드 — 필드 집합 동결·원문 미기록·요청 형태·시각 절삭
# ──────────────────────────────────────────────────────────────────────────

_EXPECTED_FIELDS = {
    "schema_version",
    "route",
    "rule_intent",
    "has_solution",
    "laya_intent",
    "laya_confidence",
    "pii_prob",
    "routed_model",
    "questions_version",
    "latency_ms",
    "failure",
    "http_status",
    "observed_at",
}


def test_success_record_fields_and_values(caplog: pytest.LogCaptureFixture) -> None:
    seen = _use_transport(lambda _r: httpx.Response(200, json=_OK_BODY))
    with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
        _run(has_solution=True)
    (rec,) = _records(caplog)
    # 필드 집합을 통째로 동결 — 원문·해시·학생/세션 식별자 필드가 생기면 RED.
    assert set(rec) == _EXPECTED_FIELDS
    assert rec["schema_version"] == shadow.RECORD_SCHEMA_VERSION
    assert rec["rule_intent"] == "포기"
    assert rec["has_solution"] is True
    assert rec["laya_intent"] == _OK_BODY["answers"]["intent"]["choice"]
    assert rec["laya_confidence"] == pytest.approx(
        _OK_BODY["answers"]["intent"]["answer_confidence"]
    )
    assert rec["pii_prob"] == pytest.approx(_OK_BODY["answers"]["pii"]["noul"])
    assert rec["routed_model"] == "multilingual"
    assert rec["failure"] is None
    assert rec["http_status"] == 200
    assert rec["latency_ms"] >= 0
    # 요청 형태 — 경로·인증·학습 질문지·모델 고정
    (req,) = seen
    assert req.url == httpx.URL(_URL + "/v1/systemone")
    assert req.headers["authorization"] == f"Bearer {_KEY}"
    sent = json.loads(req.content)
    assert sent["state"] == _STUDENT_TEXT
    assert sent["questions"] == shadow.LAYA_QUESTIONS
    assert sent["model"] == "multilingual"


def test_observed_at_is_truncated_to_the_hour(caplog: pytest.LogCaptureFixture) -> None:
    """정밀 시각은 dialogue_turn 시각과 조인돼 학생을 특정할 수 있다 — 시 단위로 절삭."""
    _use_transport(lambda _r: httpx.Response(200, json=_OK_BODY))
    with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
        _run()
    (rec,) = _records(caplog)
    obs = shadow.IntentShadowObservation.model_validate(rec)
    assert (obs.observed_at.minute, obs.observed_at.second, obs.observed_at.microsecond) == (
        0,
        0,
        0,
    )


@pytest.mark.parametrize("key", sorted(_REAL))
def test_real_laya_serve_responses_pass_the_boundary_schema(key: str) -> None:
    """실물 응답(픽스처)이 경계 스키마를 통과한다 — 가짜 응답만으로 표면 정합을 선언하지 않는다."""
    parsed = shadow._LayaResponse.model_validate(_REAL[key])
    assert parsed.routing.model == "multilingual"
    assert 0.0 <= parsed.answers.pii.noul <= 1.0


def test_student_text_and_key_never_appear_in_logs(caplog: pytest.LogCaptureFixture) -> None:
    """성공·실패 양쪽에서 원문 조각과 키가 어떤 로그 줄에도 없다."""
    _use_transport(lambda _r: httpx.Response(200, json=_OK_BODY))
    with caplog.at_level(logging.DEBUG):
        _run()
    _use_transport(lambda _r: httpx.Response(503, text="down"))
    with caplog.at_level(logging.DEBUG):
        _run()
    text = _all_log_text(caplog)
    for fragment in ("박지호", "새솔중", "010-1111-2222", "답만 알려주세요", _KEY):
        assert fragment not in text


# ──────────────────────────────────────────────────────────────────────────
# ② 프록시 무시 — 실제 소켓 서버 + 기본 팩토리 (리뷰 #1)
# ──────────────────────────────────────────────────────────────────────────


async def _serve_once(body: bytes) -> tuple[asyncio.Server, int, list[bytes]]:
    """루프백에 HTTP/1.1 응답 1건짜리 서버를 띄운다(받은 요청 원문을 모은다)."""
    got: list[bytes] = []

    async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = await reader.readuntil(b"\r\n\r\n")
        length = 0
        for line in head.split(b"\r\n"):
            if line.lower().startswith(b"content-length:"):
                length = int(line.split(b":")[1])
        got.append(head + await reader.readexactly(length))
        writer.write(
            b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\n"
            + f"content-length: {len(body)}\r\nconnection: close\r\n\r\n".encode()
            + body
        )
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(_handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port, got


def test_default_client_ignores_environment_proxy(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """HTTP_PROXY가 있어도 학생 발화는 laya로 *직접* 간다(프록시는 닫힌 포트라 경유하면 실패).

    변별력: `trust_env=False`를 빼면 httpx가 루프백 주소도 프록시로 보내 ConnectError가 난다.
    """
    for var in ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.setenv(var, "http://127.0.0.1:9")  # discard 포트 — 연결 거부
    for var in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(var, "")
    body = json.dumps(_OK_BODY).encode()

    async def _scenario() -> list[bytes]:
        server, port, got = await _serve_once(body)
        async with server:
            await shadow.observe_intent_shadow(
                student_input=_STUDENT_TEXT,
                rule_intent=StudentIntent.포기,
                has_solution=False,
                route="append_turns",
                url=f"http://127.0.0.1:{port}",
                api_key=_KEY,
                timeout_s=5.0,
            )
        return got

    with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
        got = asyncio.run(_scenario())
    (rec,) = _records(caplog)
    assert rec["failure"] is None, rec
    assert rec["laya_intent"] == "answer_only"
    assert len(got) == 1 and got[0].startswith(b"POST /v1/systemone ")


# ──────────────────────────────────────────────────────────────────────────
# ⑤ 실패 주입 — 원인별 실패 타입·상태가 남는다(성공 대조군은 위 테스트)
# ──────────────────────────────────────────────────────────────────────────


def _raise(exc: Exception) -> Handler:
    def _h(_r: httpx.Request) -> httpx.Response:
        raise exc

    return _h


def _with_intent(choice: str, conf: float) -> dict[str, Any]:
    body = json.loads(json.dumps(_OK_BODY))
    body["answers"]["intent"]["choice"] = choice
    body["answers"]["intent"]["answer_confidence"] = conf
    return body


async def _slow(_r: httpx.Request) -> httpx.Response:
    await asyncio.sleep(5)
    return httpx.Response(200, json=_OK_BODY)


@pytest.mark.parametrize(
    ("handler", "timeout_s", "failure", "status"),
    [
        (_slow, 0.2, "TimeoutError", None),  # 총 시간 상한(asyncio.timeout) — 리뷰 #8
        (_raise(httpx.ReadTimeout("slow")), 2.0, "ReadTimeout", None),
        (_raise(httpx.ConnectError("refused")), 2.0, "ConnectError", None),
        (lambda _r: httpx.Response(401, json={"detail": "x"}), 2.0, "HTTPStatusError", 401),
        (lambda _r: httpx.Response(503, text="busy"), 2.0, "HTTPStatusError", 503),
        (lambda _r: httpx.Response(200, text="not json"), 2.0, "JSONDecodeError", 200),
        (lambda _r: httpx.Response(200, json={"answers": {}}), 2.0, "ValidationError", 200),
        (
            lambda _r: httpx.Response(200, json=_with_intent("foo", 0.9)),
            2.0,
            "ValidationError",
            200,
        ),
        (
            lambda _r: httpx.Response(200, json=_with_intent("hint", 1.5)),
            2.0,
            "ValidationError",
            200,
        ),
        (_raise(RuntimeError("unexpected")), 2.0, "RuntimeError", None),
    ],
    ids=[
        "total-timeout",
        "read-timeout",
        "conn-refused",
        "401",
        "503",
        "bad-json",
        "missing-answers",
        "unknown-label",
        "confidence-out-of-range",
        "unexpected",
    ],
)
def test_failure_is_recorded_with_type_and_status(
    caplog: pytest.LogCaptureFixture,
    handler: Handler,
    timeout_s: float,
    failure: str,
    status: int | None,
) -> None:
    _use_transport(handler)
    with caplog.at_level(logging.INFO):
        _run(timeout_s=timeout_s)  # 예외가 새면 이 줄에서 테스트가 실패한다(never-break)
    (rec,) = _records(caplog)
    assert rec["failure"] == failure
    assert rec["http_status"] == status
    # 실패 레코드에는 Laya 판단이 비어 있어야 한다(반쯤 파싱된 값을 싣지 않는다)
    assert rec["laya_intent"] is None and rec["pii_prob"] is None
    assert rec["rule_intent"] == "포기"  # 규칙 쪽 값은 실패와 무관하게 남는다(분모 보존)
    warnings_ = [
        r.getMessage()
        for r in caplog.records
        if r.name == _PLAIN_LOGGER and r.levelno == logging.WARNING
    ]
    assert any(failure in w for w in warnings_)


def test_record_emission_failure_is_absorbed(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _use_transport(lambda _r: httpx.Response(200, json=_OK_BODY))

    def _boom(*_a: object, **_k: object) -> None:
        raise OSError("log sink down")

    monkeypatch.setattr(shadow.record_logger, "info", _boom)
    with caplog.at_level(logging.WARNING, logger=_PLAIN_LOGGER):
        _run()
    assert "OSError" in _all_log_text(caplog)


# ──────────────────────────────────────────────────────────────────────────
# ③ 수집 경로 — 측정용 로그 설정이 레코드를 실제로 파일에 받는다 (리뷰 #2)
# ──────────────────────────────────────────────────────────────────────────

_LOGCONFIG = _REPO / "scripts/demo/wh1_shadow_logconfig.json"


def test_measurement_logconfig_captures_intent_records(tmp_path: Path) -> None:
    """dictConfig 로드 → 이 모듈의 record 로거가 순수 JSON 줄로 파일에 캡처된다(e2e).

    기본 로깅 설정에는 핸들러가 없어 레코드가 버려진다 — 측정은 이 설정으로 띄운 서버에서만
    성립하므로 그 배선을 동결한다. 전역 로깅 상태는 사전 스냅샷으로 원복한다.
    """
    config = json.loads(_LOGCONFIG.read_text(encoding="ascii"))
    assert config["loggers"][_RECORD_LOGGER]["handlers"] == ["intent_shadow_record_file"]
    assert shadow.record_logger.name == _RECORD_LOGGER
    for name, spec in config["handlers"].items():
        if "filename" in spec:
            spec["filename"] = str(tmp_path / f"{name}.log")
    names = list(config["loggers"])
    before = {
        n: (
            logging.getLogger(n).propagate,
            logging.getLogger(n).disabled,
            list(logging.getLogger(n).handlers),
        )
        for n in names
    }
    logging.config.dictConfig(config)
    try:
        shadow.record_logger.info('{"probe": "intent"}')
        for h in shadow.record_logger.handlers:
            h.flush()
        out = tmp_path / "intent_shadow_record_file.log"
        assert out.read_text(encoding="utf-8").strip() == '{"probe": "intent"}'
    finally:
        for n, (propagate, disabled, handlers) in before.items():
            target = logging.getLogger(n)
            for h in list(target.handlers):
                if h not in handlers:
                    target.removeHandler(h)
                    h.close()
            target.propagate = propagate
            target.disabled = disabled


# ──────────────────────────────────────────────────────────────────────────
# ④ 집행 지점(정적) — coach 두 핸들러가 커밋 뒤에, 적재한 바로 그 값과 원 발화로 부른다
# ──────────────────────────────────────────────────────────────────────────

_COACH = _REPO / "src/backend/whymath_backend/api/coach.py"


def _handler(name: str) -> ast.AsyncFunctionDef:
    tree = ast.parse(_COACH.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"coach.{name} 없음")


def _is_commit(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Await)
        and isinstance(stmt.value.value, ast.Call)
        and isinstance(stmt.value.value.func, ast.Attribute)
        and stmt.value.value.func.attr == "commit"
    )


def _shadow_call(stmt: ast.stmt) -> ast.Call | None:
    if (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Call)
        and isinstance(stmt.value.func, ast.Name)
        and stmt.value.func.id == "spawn_intent_shadow"
    ):
        return stmt.value
    return None


def _is_body_student_input(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "student_input"
        and isinstance(node.value, ast.Name)
        and node.value.id == "body"
    )


@pytest.mark.parametrize(
    ("handler", "route"), [("create_session", "create_session"), ("append_turns", "append_turns")]
)
def test_coach_handler_spawns_shadow_after_commit_with_stored_intent(
    handler: str, route: str
) -> None:
    fn = _handler(handler)
    body = fn.body
    commits = [i for i, s in enumerate(body) if _is_commit(s)]
    calls = [(i, c) for i, s in enumerate(body) if (c := _shadow_call(s)) is not None]
    assert len(calls) == 1, "섀도 호출은 핸들러 최상위에 정확히 1회"
    (call_idx, call), last_commit = calls[0], commits[-1] if commits else -1
    assert commits and call_idx == last_commit + 1, "마지막 커밋 *직후*에 불러야 한다"
    kw = {k.arg: k.value for k in call.keywords}
    assert isinstance(kw["route"], ast.Constant) and kw["route"].value == route
    # 원 발화(body.student_input)여야 한다 — 풀이 문자열·암호문·빈 값이면 비교가 무의미(리뷰 #9)
    assert _is_body_student_input(kw["student_input"])
    # DB에 적재한 값과 같은 변수여야 한다(재분류·다른 값 전달이면 비교가 무의미)
    assert isinstance(kw["rule_intent"], ast.Name) and kw["rule_intent"].id == "student_intent"
    assert isinstance(kw["has_solution"], ast.Name) and kw["has_solution"].id == "has_solution"
    # TurnMeta(student_intent=...)도 같은 변수를 쓴다
    metas = [
        k.value
        for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "TurnMeta"
        for k in n.keywords
        if k.arg == "student_intent"
    ]
    assert metas and all(isinstance(v, ast.Name) and v.id == "student_intent" for v in metas)
    # 그 변수는 원 발화로 분류한 결과다
    assigns = [
        n
        for n in ast.walk(fn)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "student_intent" for t in n.targets)
    ]
    assert len(assigns) == 1
    call_value = assigns[0].value
    assert isinstance(call_value, ast.Call) and isinstance(call_value.func, ast.Name)
    assert call_value.func.id == "classify_student_intent"
    ckw = {k.arg: k.value for k in call_value.keywords}
    assert _is_body_student_input(ckw["student_input"])
