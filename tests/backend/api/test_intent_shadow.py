"""학생 의도 섀도 관측(PED-48) 단위테스트 — hermetic·라이브 0·DB 0.

검증 축 (태스크 acceptance 번호):
- ① 설정 게이트: 스위치·URL·키가 *모두* 있어야 호출한다. 하나라도 비면 task 0개.
- ② 비노출·비차단: 공개 함수는 None, 어떤 실패도 예외로 새지 않는다. 흡수한 예외는 타입명을 남긴다.
- ③ 레코드: 성공·실패 모두 1건. 학생 원문·식별자 필드가 없다(필드 집합을 통째로 동결).
- ④ 집행 지점(정적): coach 두 핸들러가 *커밋 뒤에* 섀도를 부르고, DB에 적재한 바로 그 규칙 의도를
  넘긴다 — AST로 순서와 인자를 본다(문자열 grep은 주석·변형에서 뚫린다).
- ⑤ 실패 주입: 타임아웃·연결 거부·401·503·JSON 손상·경계 스키마 위반·예상 밖 예외 각각의 실패 타입과
  HTTP 상태가 레코드에 남는지, 성공 대조군과 함께 본다.

**HTTP 대역**: `set_client_factory`로 `httpx.MockTransport`를 끼운 실제 `httpx.AsyncClient`를 쓴다
(가짜 클라이언트 클래스가 아니라 실물 SDK 표면 — 외부 SDK 표면 시임 금지 규칙).
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import logging
from collections.abc import Callable, Coroutine, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from whymath_backend.api import _intent_shadow as shadow
from whymath_backend.config import get_settings
from whymath_backend.schema.enums import StudentIntent

_RECORD_LOGGER = "whymath.api.intent_shadow.record"
_PLAIN_LOGGER = "whymath.api.intent_shadow"
_URL = "http://laya.test:18080"
_KEY = "test-key-0123456789abcdef0123456789abcdef"
# 레코드·로그에 이 문자열이 나타나면 원문 누출이다 — 이름·학교·번호를 일부러 섞는다.
_STUDENT_TEXT = "저 새솔중 박지호인데요 010-1111-2222 이거 답만 알려주세요"

_OK_BODY: dict[str, Any] = {
    "answers": {
        "intent": {"choice": "answer_only", "confidence": 0.98, "answer_confidence": 0.97},
        "pii": {"noul": 0.99, "confidence": 0.9},
    },
    "routing": {"model": "multilingual", "reason": "non-Latin script"},
    "usage": {"input_tokens": 40, "output_tokens": 0},
}


@pytest.fixture(autouse=True)
def _isolate() -> Iterator[None]:
    """전역 Settings 캐시·클라이언트 팩토리 누수 차단."""
    get_settings.cache_clear()
    yield
    shadow.set_client_factory(None)
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


def _capture_spawn(monkeypatch: pytest.MonkeyPatch) -> _Captured:
    cap = _Captured()
    monkeypatch.setattr(shadow, "_spawn", cap)
    return cap


def _use_transport(handler: Callable[[httpx.Request], httpx.Response]) -> list[httpx.Request]:
    """MockTransport를 끼운 실물 AsyncClient로 교체 — 받은 요청을 돌려준다(요청 본문 검사용)."""
    seen: list[httpx.Request] = []

    def _record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

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
# ① 설정 게이트
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, True),
        ({"WHYMATH_LAYA_INTENT_SHADOW_ENABLED": "false"}, False),
        ({"WHYMATH_LAYA_INTENT_SHADOW_URL": ""}, False),
        ({"WHYMATH_LAYA_INTENT_SHADOW_URL": "   "}, False),
        ({"WHYMATH_LAYA_INTENT_SHADOW_API_KEY": ""}, False),
        ({"WHYMATH_LAYA_INTENT_SHADOW_API_KEY": "  "}, False),
    ],
)
def test_shadow_configured_requires_all_three(
    monkeypatch: pytest.MonkeyPatch, overrides: dict[str, str], expected: bool
) -> None:
    _configure(monkeypatch, **overrides)
    assert shadow.shadow_configured(get_settings()) is expected


def test_default_settings_are_off() -> None:
    """기본값(환경변수 없음)은 꺼짐 — opt-in."""
    s = get_settings()
    assert s.laya_intent_shadow_enabled is False
    assert shadow.shadow_configured(s) is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"WHYMATH_LAYA_INTENT_SHADOW_ENABLED": "false"},
        {"WHYMATH_LAYA_INTENT_SHADOW_URL": ""},
        {"WHYMATH_LAYA_INTENT_SHADOW_API_KEY": ""},
    ],
)
def test_spawn_creates_no_task_when_not_configured(
    monkeypatch: pytest.MonkeyPatch, overrides: dict[str, str]
) -> None:
    _configure(monkeypatch, **overrides)
    cap = _capture_spawn(monkeypatch)
    shadow.spawn_intent_shadow(
        student_input=_STUDENT_TEXT, rule_intent=None, has_solution=False, route="create_session"
    )
    assert cap.coros == []


def test_spawn_skips_blank_input(monkeypatch: pytest.MonkeyPatch) -> None:
    """빈 발화(첫 진입·풀이만 제출)는 판정할 문장이 없다 — 실패 레코드를 만들지 않는다."""
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
    with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
        cap.drive()
    (rec,) = _records(caplog)
    assert rec["route"] == "create_session"
    assert rec["laya_intent"] == "answer_only"


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
# ③ 성공 레코드 — 필드 집합 동결·원문 미기록·요청 형태
# ──────────────────────────────────────────────────────────────────────────

_EXPECTED_FIELDS = {
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
    assert rec["rule_intent"] == "포기"
    assert rec["has_solution"] is True
    assert rec["laya_intent"] == "answer_only"
    assert rec["laya_confidence"] == pytest.approx(0.97)
    assert rec["pii_prob"] == pytest.approx(0.99)
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


def test_trailing_slash_in_url_is_normalised() -> None:
    seen = _use_transport(lambda _r: httpx.Response(200, json=_OK_BODY))
    _run(url=_URL + "/")
    assert seen[0].url == httpx.URL(_URL + "/v1/systemone")


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
# ⑤ 실패 주입 — 원인별 실패 타입·상태가 남는다(성공 대조군은 위 테스트)
# ──────────────────────────────────────────────────────────────────────────


def _raise(exc: Exception) -> Callable[[httpx.Request], httpx.Response]:
    def _h(_r: httpx.Request) -> httpx.Response:
        raise exc

    return _h


_BAD_LABEL = {
    **_OK_BODY,
    "answers": {**_OK_BODY["answers"], "intent": {"choice": "foo", "answer_confidence": 0.9}},
}
_BAD_CONF = {
    **_OK_BODY,
    "answers": {**_OK_BODY["answers"], "intent": {"choice": "hint", "answer_confidence": 1.5}},
}


@pytest.mark.parametrize(
    ("handler", "failure", "status"),
    [
        (_raise(httpx.ReadTimeout("slow")), "ReadTimeout", None),
        (_raise(httpx.ConnectError("refused")), "ConnectError", None),
        (lambda _r: httpx.Response(401, json={"detail": "unauthorized"}), "HTTPStatusError", 401),
        (lambda _r: httpx.Response(503, text="busy"), "HTTPStatusError", 503),
        (lambda _r: httpx.Response(200, text="not json"), "JSONDecodeError", 200),
        (lambda _r: httpx.Response(200, json={"answers": {}}), "ValidationError", 200),
        (lambda _r: httpx.Response(200, json=_BAD_LABEL), "ValidationError", 200),
        (lambda _r: httpx.Response(200, json=_BAD_CONF), "ValidationError", 200),
        (_raise(RuntimeError("unexpected")), "RuntimeError", None),
    ],
    ids=[
        "timeout",
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
    handler: Callable[[httpx.Request], httpx.Response],
    failure: str,
    status: int | None,
) -> None:
    _use_transport(handler)
    with caplog.at_level(logging.INFO):
        _run()  # 예외가 새면 이 줄에서 테스트가 실패한다(never-break)
    (rec,) = _records(caplog)
    assert rec["failure"] == failure
    assert rec["http_status"] == status
    # 실패 레코드에는 Laya 판단이 비어 있어야 한다(반쯤 파싱된 값을 싣지 않는다)
    assert rec["laya_intent"] is None and rec["pii_prob"] is None
    assert rec["rule_intent"] == "포기"  # 규칙 쪽 값은 실패와 무관하게 남는다(분모 보존)
    warnings = [
        r.getMessage()
        for r in caplog.records
        if r.name == _PLAIN_LOGGER and r.levelno == logging.WARNING
    ]
    assert any(failure in w for w in warnings)


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
# ④ 집행 지점(정적) — coach 두 핸들러가 커밋 뒤에, 적재한 바로 그 값으로 부른다
# ──────────────────────────────────────────────────────────────────────────

_COACH = Path(__file__).resolve().parents[3] / "src/backend/whymath_backend/api/coach.py"


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


@pytest.mark.parametrize(
    ("handler", "route"), [("create_session", "create_session"), ("append_turns", "append_turns")]
)
def test_coach_handler_spawns_shadow_after_commit_with_stored_intent(
    handler: str, route: str
) -> None:
    body = _handler(handler).body
    commits = [i for i, s in enumerate(body) if _is_commit(s)]
    calls = [(i, c) for i, s in enumerate(body) if (c := _shadow_call(s)) is not None]
    assert len(calls) == 1, "섀도 호출은 핸들러 최상위에 정확히 1회"
    (call_idx, call), last_commit = calls[0], commits[-1] if commits else -1
    assert commits and call_idx == last_commit + 1, "마지막 커밋 *직후*에 불러야 한다"
    kw = {k.arg: k.value for k in call.keywords}
    assert isinstance(kw["route"], ast.Constant) and kw["route"].value == route
    # DB에 적재한 값과 같은 변수여야 한다(재분류·다른 값 전달이면 비교가 무의미)
    assert isinstance(kw["rule_intent"], ast.Name) and kw["rule_intent"].id == "student_intent"
    assert isinstance(kw["has_solution"], ast.Name) and kw["has_solution"].id == "has_solution"
    # TurnMeta(student_intent=...)도 같은 변수를 쓴다
    metas = [
        k.value
        for n in ast.walk(_handler(handler))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "TurnMeta"
        for k in n.keywords
        if k.arg == "student_intent"
    ]
    assert metas and all(isinstance(v, ast.Name) and v.id == "student_intent" for v in metas)
