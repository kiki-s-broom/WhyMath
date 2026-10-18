"""P3-56 후보 — 그림자 관측이 부모 프로세스에서 기록되는가 (Core 쪽 약속).

어댑터는 훑기를 `isolated(...)`의 **프로세스 풀 워커**에서 돌린다. 워커에는 부모의 로깅 설정이 없어
거기서 남긴 INFO 로그는 조용히 사라진다. 그래서 관측을 결과 객체에 실어 보내고 부모가 기록한다.
이 파일이 지키는 것:

  ① 부모가 어댑터의 불투명 문자열을 **그대로** 기록한다(문항 id와 함께·해석 없음).
  ② 레코드가 없거나 형식이 틀린 결과는 조용히 무시된다(필수 능력 Protocol은 늘리지 않았다).
  ③ 기록 실패는 채점을 깨지 않고 **예외 타입명**을 남긴다(침묵 실패 금지).
  ④ **실제 프로세스 풀**을 통과해도 관측이 살아 돌아오고, 모드(env)가 워커에 전달된다.
     — 이 ④가 없으면 "관측한다"는 말이 풀 안에서만 거짓일 수 있다(상시 침묵).
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest

from whymath_backend.api import _attempt_misconception_scan as scan_module
from whymath_backend.api import _isolated_call
from whymath_backend.api._attempt_misconception_scan import (
    NOT_SCANNED,
    scan_attempt_misconceptions,
    shadow_record_logger,
)
from whymath_backend.config import get_settings
from whymath_backend.schema.assessment_evidence import MisconceptionScan

_RECORD = '{"channel":"derivative_signature","fired":true}'
_QUESTION = "함수 f(x) = x^8에 대하여 f'(3)의 값은?"
_WRONG = "52488"  # 지수는 내렸지만 1을 줄이지 않은 값 — power-rule-step-omitted의 오답 값


class _Session:
    """문항 지문 한 건만 돌려주는 최소 세션 — 이 함수는 텍스트 채널에서 지문 조회 1회만 한다."""

    def __init__(self, question: str | None = _QUESTION) -> None:
        self._question = question

    async def scalar(self, _stmt: Any) -> str | None:
        return self._question


class _Detector:
    """결과에 임의의 속성을 실어 돌려주는 가짜 검출기(인라인 격리 경로에서 쓴다)."""

    def __init__(self, **extra: Any) -> None:
        self._extra = extra

    def scan_attempt_answer(self, *, question_text: str, student_answer: str | None) -> Any:
        return SimpleNamespace(
            scan=MisconceptionScan.RAN_NO_CANDIDATE, candidates=(), **self._extra
        )


def _configure(monkeypatch: pytest.MonkeyPatch, *, isolation: bool, mode: str = "off") -> None:
    monkeypatch.setenv("WHYMATH_JWT_SECRET_KEY", "test-secret-0123456789abcdef")
    monkeypatch.setenv("WHYMATH_SYMPY_ISOLATION_ENABLED", "true" if isolation else "false")
    monkeypatch.setenv("WHYMATH_SYMPY_ISOLATION_TIMEOUT_S", "20")
    monkeypatch.setenv("WHYMATH_SYMPY_ISOLATION_MAX_WORKERS", "1")
    monkeypatch.setenv("WHYMATH_L4_DERIVATIVE_SIGNATURE_MODE", mode)
    get_settings.cache_clear()
    _isolated_call.reset_pool_for_tests()


@pytest.fixture
def inline(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    _configure(monkeypatch, isolation=False)
    yield
    monkeypatch.undo()
    _isolated_call.reset_pool_for_tests()
    get_settings.cache_clear()


def _shadow_lines(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    return [
        json.loads(r.getMessage()) for r in caplog.records if r.name == shadow_record_logger.name
    ]


class TestParentEmitsOpaqueRecords:
    async def test_records_are_logged_verbatim_with_the_problem_id(
        self, inline: None, caplog: pytest.LogCaptureFixture
    ) -> None:
        pid = uuid.uuid4()
        caplog.set_level(logging.INFO, logger=shadow_record_logger.name)
        await scan_attempt_misconceptions(
            _Session(),  # type: ignore[arg-type]
            _Detector(shadow_records=(_RECORD,)),
            problem_id=pid,
            answer=_WRONG,
            selected_choice_index=None,
        )
        lines = _shadow_lines(caplog)
        assert lines == [{"problem_id": str(pid), "adapter_records": [_RECORD]}]

    async def test_result_without_records_logs_nothing(
        self, inline: None, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.INFO, logger=shadow_record_logger.name)
        await scan_attempt_misconceptions(
            _Session(),  # type: ignore[arg-type]
            _Detector(),
            problem_id=uuid.uuid4(),
            answer=_WRONG,
            selected_choice_index=None,
        )
        assert _shadow_lines(caplog) == []

    async def test_non_string_records_are_ignored(
        self, inline: None, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.INFO, logger=shadow_record_logger.name)
        await scan_attempt_misconceptions(
            _Session(),  # type: ignore[arg-type]
            _Detector(shadow_records=(123, None, {"a": 1})),
            problem_id=uuid.uuid4(),
            answer=_WRONG,
            selected_choice_index=None,
        )
        assert _shadow_lines(caplog) == []

    async def test_logging_failure_never_breaks_scoring_and_names_the_exception(
        self, inline: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        def boom(*_: Any, **__: Any) -> str:
            raise TypeError("not serializable")

        monkeypatch.setattr(scan_module.json, "dumps", boom)
        caplog.set_level(logging.WARNING, logger="whymath.api.me")
        out = await scan_attempt_misconceptions(
            _Session(),  # type: ignore[arg-type]
            _Detector(shadow_records=(_RECORD,)),
            problem_id=uuid.uuid4(),
            answer=_WRONG,
            selected_choice_index=None,
        )
        assert out.scan is MisconceptionScan.RAN_NO_CANDIDATE, "관측 실패가 채점 결과를 바꿨다"
        assert "exc_type=TypeError" in caplog.text, "침묵 실패 금지 — 예외 타입명이 있어야 한다"
        assert _RECORD not in caplog.text, "경고에 레코드 본문을 넣지 않는다"

    async def test_student_answer_and_question_never_reach_this_logger(
        self, inline: None, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.DEBUG)
        await scan_attempt_misconceptions(
            _Session(),  # type: ignore[arg-type]
            _Detector(shadow_records=(_RECORD,)),
            problem_id=uuid.uuid4(),
            answer=_WRONG,
            selected_choice_index=None,
        )
        text = "\n".join(
            r.getMessage() for r in caplog.records if r.name == shadow_record_logger.name
        )
        assert _WRONG not in text and "x^8" not in text


@pytest.fixture
def real_pool_shadow(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """실제 프로세스 풀 + 모드 shadow — 워커는 부모 env를 물려받아 spawn된다."""
    _configure(monkeypatch, isolation=True, mode="shadow")
    yield
    monkeypatch.undo()
    _isolated_call.reset_pool_for_tests()
    get_settings.cache_clear()


@pytest.fixture
def real_pool_off(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    _configure(monkeypatch, isolation=True, mode="off")
    yield
    monkeypatch.undo()
    _isolated_call.reset_pool_for_tests()
    get_settings.cache_clear()


class TestObservationCrossesTheProcessBoundary:
    """④ 풀 워커에서 만든 관측이 부모에서 기록된다 — 워커 로그에 기대지 않는다."""

    async def test_shadow_record_survives_the_real_process_pool(
        self, real_pool_shadow: None, caplog: pytest.LogCaptureFixture
    ) -> None:
        from whymath_backend.composition import default_attempt_misconception_detector

        pid = uuid.uuid4()
        caplog.set_level(logging.INFO, logger=shadow_record_logger.name)
        out = await scan_attempt_misconceptions(
            _Session(),  # type: ignore[arg-type]
            default_attempt_misconception_detector(),
            problem_id=pid,
            answer=_WRONG,
            selected_choice_index=None,
        )
        snapshot = _isolated_call.isolation_snapshot()
        assert (
            snapshot.enabled and snapshot.pool_started and snapshot.calls >= 1
        ), "이 테스트가 실제 프로세스 풀을 타지 않았다 — 인라인 실행으로는 경계를 검증하지 못한다"
        assert snapshot.isolated_ratio == 1.0, "일부 호출이 풀이 아니라 스레드 폴백으로 돌았다"
        lines = _shadow_lines(caplog)
        assert len(lines) == 1, "풀 워커의 관측이 부모까지 오지 않았다 — 조용한 상시 침묵"
        assert lines[0]["problem_id"] == str(pid)
        record = json.loads(lines[0]["adapter_records"][0])
        assert record["fired"] is True
        assert record["added_candidate_ids"] == ["power-rule-step-omitted"]
        assert record["answer_is_correct"] is False
        # 학생에게 가는 결과는 off와 같다: 후보가 얹히지 않는다(기존 채널은 이 질문에 후보가 없다).
        assert out is not NOT_SCANNED
        assert out.candidates == ()
        # 학생 답·지문은 어느 로그에도 없다.
        assert _WRONG not in caplog.text and "x^8" not in caplog.text

    async def test_mode_off_in_the_worker_produces_no_record(
        self, real_pool_off: None, caplog: pytest.LogCaptureFixture
    ) -> None:
        """대조군: 같은 풀·같은 입력에서 모드만 off면 레코드가 없다 — 위 테스트가 모드에 반응한다는 증거."""
        from whymath_backend.composition import default_attempt_misconception_detector

        caplog.set_level(logging.INFO, logger=shadow_record_logger.name)
        await scan_attempt_misconceptions(
            _Session(),  # type: ignore[arg-type]
            default_attempt_misconception_detector(),
            problem_id=uuid.uuid4(),
            answer=_WRONG,
            selected_choice_index=None,
        )
        assert _shadow_lines(caplog) == []
