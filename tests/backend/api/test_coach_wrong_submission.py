"""코치 서버 판정 오답의 '문제당 최초 1건' 적재 — 규칙·순서·격리 (EOS-146 · DB 무접근 단위).

`api/coach._record_first_wrong_submission`은 코치가 서버 검증으로 판정한 **명확한 오답**을 원장에
적재하고 `/v1/me/attempts`의 오답 경로와 같은 후처리를 태운다. 이 파일은 그 계약의 다섯 축을 본다:

  - **계수 규칙** — 같은 학생·같은 문항의 최초 1건만 적재한다. 이미 오답이 있으면 생략한다.
  - **후처리 순서·인자** — attempt commit → 훑기 → 증거 → 가설 → 숙달 → 스킬 → 스킬 이벤트 → 상태
    머신(서버 판정 오답 · 확신도 미측정 · 이번 답안 스캔에서 온 R3 입력만).
  - **실패 격리** — attempt 적재 뒤 후처리가 터져도 코치 응답은 살고, 예외 타입명이 로그에 남는다.
  - **킬 스위치** — 꺼져 있으면 조회·적재가 전혀 없다.
  - **완료 표지 비연결** — `_resolve_completion`이 REDIRECT에서 attempt_id를 돌려주지 않는다
    (그 값이 dialogue에 링크되면 풀던 대화가 완료로 읽힌다).

변별력 원칙: 각 검사는 그 규칙을 **어기는 입력**을 넣었을 때 실패해야 한다. 정상 입력의 초록은 증거가
아니다(CLAUDE.md 보호 장치 실패 주입). 뮤테이션 내역은 PR 본문에 있다.

같은 입력에 같은 전이가 난다는 실측은 `test_eos146_coach_wrong_submission_integration.py`(실 PG)가 맡는다.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

import whymath_backend.api.coach as coach_module
from whymath_backend.api._attempt_misconception_scan import (
    AttemptMisconceptionScan,
    this_attempt_misconceptions_from,
)
from whymath_backend.api._crypto import SecretCipher
from whymath_backend.config import get_settings
from whymath_backend.db.models.activity import ProblemAttempt as ProblemAttemptORM
from whymath_backend.l2.attempt_skill_event import AttemptSource
from whymath_backend.schema.assessment_evidence import MisconceptionScan
from whymath_backend.schema.verification_capabilities import VerificationOutcome

_UID = uuid.UUID("00000000-0000-0000-0000-00000000e146")
_PID = uuid.UUID("00000000-0000-0000-0000-0000000a0146")
_T0 = datetime(2026, 9, 30, 11, 0, 0, tzinfo=timezone.utc)
_ANSWER = "x=99"


class _LookupResult:
    """`select(...).limit(1)` 결과 — 이 학생·문항의 기존 오답 attempt id(없으면 None)."""

    def __init__(self, prior: uuid.UUID | None) -> None:
        self._prior = prior

    def scalar_one_or_none(self) -> uuid.UUID | None:
        return self._prior


class _FakeSession:
    def __init__(self, calls: list[str], prior: uuid.UUID | None = None) -> None:
        self._calls = calls
        self._prior = prior
        self.added: list[Any] = []
        self.lookups = 0

    async def get(self, _model: Any, _pk: Any) -> None:
        """EOS-47: 시도 버전 고정이 문항 행을 PK로 읽는다 — 이 대역엔 문항이 없다(None=문항 없음).

        고정 값 자체는 `tests/backend/l2/test_attempt_version_pin.py`·배선 테스트가 잰다. 이 파일이
        재는 것(채점·적재 순서 등)은 그 값과 무관하다.
        """
        return None

    async def execute(self, _stmt: Any) -> _LookupResult:
        self.lookups += 1
        self._calls.append("lookup")
        return _LookupResult(self._prior)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self._calls.append("commit")


class _Spy:
    """후처리 협력 함수의 호출 순서와 인자를 기록한다."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.kwargs: dict[str, dict[str, Any]] = {}
        self.scan_error: Exception | None = None
        # 이번 스캔이 게이트를 통과시킨 후보 — 아래 갱신 세트에는 이번에 증거를 못 받은 옛 가설이 섞여 있다.
        self.candidates = (SimpleNamespace(misconception_id="M-this", gate_passed=True),)
        self.scan_state = MisconceptionScan.RAN_WITH_CANDIDATES
        self.active = [
            SimpleNamespace(misconception_id="M-this", confidence=0.81),
            SimpleNamespace(misconception_id="M-old", confidence=0.95),
        ]
        self.rejected: str | None = None

    async def learning_activity(self, _session: Any, **_kwargs: Any) -> None:
        self.calls.append("session")

    async def scan(self, _session: Any, _detector: Any, **kwargs: Any) -> AttemptMisconceptionScan:
        self.calls.append("scan")
        self.kwargs["scan"] = kwargs
        if self.scan_error is not None:
            raise self.scan_error
        return AttemptMisconceptionScan(
            scan=self.scan_state,
            candidates=self.candidates,  # type: ignore[arg-type]
        )

    async def evidence(self, _session: Any, **kwargs: Any) -> Any:
        self.calls.append("evidence")
        self.kwargs["evidence"] = kwargs
        return SimpleNamespace(tag="evidence")

    async def apply(self, _session: Any, _user_id: Any, candidates: Any) -> list[Any]:
        self.calls.append("hypotheses")
        self.kwargs["apply"] = {"candidates": candidates}
        return self.active

    async def mastery(self, _session: Any, **kwargs: Any) -> list[Any]:
        self.calls.append("mastery")
        self.kwargs["mastery"] = kwargs
        return []

    async def skill_mastery(self, _session: Any, **kwargs: Any) -> list[Any]:
        self.calls.append("skill_mastery")
        self.kwargs["skill_mastery"] = kwargs
        return [SimpleNamespace(skill_id="skill.a")]

    async def skill_event(self, _session: Any, **kwargs: Any) -> None:
        self.calls.append("skill_event")
        self.kwargs["skill_event"] = kwargs

    async def state_machine(self, _session: Any, **kwargs: Any) -> SimpleNamespace:
        self.calls.append("state_machine")
        self.kwargs["state_machine"] = kwargs
        return SimpleNamespace(
            rejected_transition=self.rejected,
            decision=SimpleNamespace(rule_id="R6-wrong-undiagnosed"),
            final_state="PRACTICING",
        )


def _patch(monkeypatch: pytest.MonkeyPatch, spy: _Spy) -> None:
    monkeypatch.setattr(coach_module, "record_learning_activity", spy.learning_activity)
    monkeypatch.setattr(coach_module, "scan_attempt_misconceptions", spy.scan)
    monkeypatch.setattr(coach_module, "collect_assessment_evidence", spy.evidence)
    monkeypatch.setattr(coach_module, "apply_candidates", spy.apply)
    monkeypatch.setattr(coach_module, "record_problem_attempt_mastery", spy.mastery)
    monkeypatch.setattr(coach_module, "record_problem_attempt_skill_mastery", spy.skill_mastery)
    monkeypatch.setattr(coach_module, "record_attempt_skill_event", spy.skill_event)
    monkeypatch.setattr(coach_module, "advance_on_graded_attempt", spy.state_machine)


_DETECTOR = SimpleNamespace(tag="detector")


def _record(session: _FakeSession, *, problem_id: uuid.UUID | None = _PID) -> uuid.UUID | None:
    return asyncio.run(
        coach_module._record_first_wrong_submission(
            session,  # type: ignore[arg-type]
            user_id=_UID,
            problem_id=problem_id,
            final_answer=_ANSWER,
            started_at=_T0,
            detector=_DETECTOR,  # type: ignore[arg-type]
        )
    )


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Spy]:
    s = _Spy()
    _patch(monkeypatch, s)
    yield s


class TestCountingRule:
    def test_first_wrong_submission_is_recorded_as_a_wrong_attempt(self, spy: _Spy) -> None:
        session = _FakeSession(spy.calls)
        attempt_id = _record(session)

        attempts = [o for o in session.added if isinstance(o, ProblemAttemptORM)]
        assert len(attempts) == 1, "오답 attempt가 적재되지 않았다"
        row = attempts[0]
        assert row.attempt_id == attempt_id
        assert row.is_correct is False  # 서버 권위 판정 — 클라 보고가 아니다.
        assert row.user_id == _UID and row.problem_id == _PID
        assert row.used_socratic is True
        # 힌트 귀속은 판정하지 않는다 — NULL(미판정)이지 False(안 썼다)가 아니다.
        assert row.used_hint is None
        assert row.started_at == _T0

    def test_existing_wrong_attempt_suppresses_a_second_row(self, spy: _Spy) -> None:
        """재제출 오답은 세지 않는다 — 틀린 뒤 스스로 고치는 것은 Polya의 정상 경로다.

        변별력: 조회를 건너뛰고 항상 적재하면 이 단언이 깨진다(행이 1개 생긴다).
        """
        session = _FakeSession(spy.calls, prior=uuid.uuid4())
        assert _record(session) is None
        assert [o for o in session.added if isinstance(o, ProblemAttemptORM)] == []
        assert "commit" not in spy.calls
        # 후처리도 돌지 않는다 — 원장에 새 행이 없는데 상태 머신만 도는 것이 가장 나쁜 비대칭이다.
        assert "state_machine" not in spy.calls and "mastery" not in spy.calls

    def test_skip_is_logged_so_the_rate_is_measurable(
        self, spy: _Spy, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO, logger=coach_module.logger.name):
            _record(_FakeSession(spy.calls, prior=uuid.uuid4()))
        assert "outcome=skipped_duplicate" in caplog.text

    def test_recorded_is_logged_with_the_rule_that_fired(
        self, spy: _Spy, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO, logger=coach_module.logger.name):
            _record(_FakeSession(spy.calls))
        assert "outcome=recorded" in caplog.text
        assert "R6-wrong-undiagnosed" in caplog.text

    def test_without_a_problem_nothing_is_written(self, spy: _Spy) -> None:
        session = _FakeSession(spy.calls)
        assert _record(session, problem_id=None) is None
        assert session.lookups == 0 and session.added == []


class TestStudentWorkEncryption:
    """SEC-31 — 세 ProblemAttempt 적재 경로(`submit_attempt`·완료·오답)가 같은 보호를 받는다.

    학생 풀이는 미성년 데이터라 키가 설정된 환경에서는 평문 컬럼이 비고 봉투 암호화 컬럼에만 실린다.
    변별력: 이 경로가 `encrypt_dialogue_content`를 거치지 않고 평문을 직접 넣으면 키 설정 시 평문 컬럼이
    채워져 이 검사가 깨진다.
    """

    def test_key_configured_stores_only_ciphertext(
        self, spy: _Spy, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        key = os.urandom(32)
        monkeypatch.setenv("WHYMATH_STUDENT_WORK_ENCRYPTION_KEY", base64.b64encode(key).decode())
        get_settings.cache_clear()
        try:
            session = _FakeSession(spy.calls)
            _record(session)
        finally:
            monkeypatch.delenv("WHYMATH_STUDENT_WORK_ENCRYPTION_KEY", raising=False)
            get_settings.cache_clear()
        row = next(o for o in session.added if isinstance(o, ProblemAttemptORM))
        assert row.student_answer is None
        assert row.student_answer_encrypted is not None and row.student_answer_nonce is not None
        cipher = SecretCipher(key)
        assert cipher.decrypt(row.student_answer_encrypted, row.student_answer_nonce) == _ANSWER

    def test_key_unset_falls_back_to_plaintext_like_the_other_paths(
        self, spy: _Spy, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """키 미설정(개발·CI) — 다른 두 경로와 같은 평문 폴백이다(prod-like는 부팅 시 차단된다)."""
        monkeypatch.delenv("WHYMATH_STUDENT_WORK_ENCRYPTION_KEY", raising=False)
        get_settings.cache_clear()
        session = _FakeSession(spy.calls)
        _record(session)
        row = next(o for o in session.added if isinstance(o, ProblemAttemptORM))
        assert row.student_answer == _ANSWER
        assert row.student_answer_encrypted is None and row.student_answer_nonce is None


class TestPostProcessing:
    def test_state_machine_gets_a_server_judged_wrong_attempt(self, spy: _Spy) -> None:
        session = _FakeSession(spy.calls)
        attempt_id = _record(session)

        kwargs = spy.kwargs["state_machine"]
        assert kwargs["user_id"] == _UID
        assert kwargs["is_correct"] is False
        # 코치 경로에는 자기보고 확신도 입력이 없다 — None(미측정)이지 0.0이 아니다.
        assert "confidence" in kwargs and kwargs["confidence"] is None
        assert kwargs["attempt_id"] == attempt_id

    def test_r3_input_is_this_attempts_scan_only(self, spy: _Spy) -> None:
        """R3 입력은 **이번 답안의 스캔** 후보에 든 가설뿐이다(EOS-138).

        갱신 세트에는 이번에 증거를 못 받고 감쇠만 한 옛 가설(`M-old`)이 confidence 0.95로 섞여 있다.
        그것이 R3 입력에 새면 이번 오답이 옛 오개념의 교정 대상이 된다 — 변별력은 그 유입이다.
        """
        _record(_FakeSession(spy.calls))
        pairs = spy.kwargs["state_machine"]["this_attempt_misconceptions"]
        assert pairs == (("M-this", 0.81),)

    def test_not_scanned_gives_no_r3_input_and_no_hypothesis_update(self, spy: _Spy) -> None:
        """훑지 않았으면(NOT_RUN) 가설을 건드리지 않고 R3 입력도 비어 있다 — R6으로 간다."""
        spy.scan_state = MisconceptionScan.NOT_RUN
        spy.candidates = ()
        _record(_FakeSession(spy.calls))
        assert "hypotheses" not in spy.calls
        assert spy.kwargs["state_machine"]["this_attempt_misconceptions"] == ()

    def test_evidence_is_assembled_before_mastery_and_carries_the_scan(self, spy: _Spy) -> None:
        """Answer → Evidence → State 순서. 증거는 이번 스캔 상태를 사실대로 싣는다."""
        _record(_FakeSession(spy.calls))
        calls = spy.calls
        assert calls.index("evidence") < calls.index("mastery"), calls
        ev = spy.kwargs["evidence"]
        assert ev["correct"] is False
        assert ev["misconception_scan"] is MisconceptionScan.RAN_WITH_CANDIDATES
        assert list(ev["possible_misconceptions"]) == list(spy.candidates)
        assert spy.kwargs["mastery"]["evidence"].tag == "evidence"

    def test_scan_reads_the_last_solution_step_without_a_choice_index(self, spy: _Spy) -> None:
        _record(_FakeSession(spy.calls))
        scan_kwargs = spy.kwargs["scan"]
        assert scan_kwargs["answer"] == _ANSWER
        assert scan_kwargs["selected_choice_index"] is None  # 코치에는 보기 탭이 없다.
        assert scan_kwargs["problem_id"] == _PID

    def test_order_is_attempt_commit_then_scan_then_state_machine_last(self, spy: _Spy) -> None:
        _record(_FakeSession(spy.calls))
        calls = spy.calls
        assert calls.count("state_machine") == 1, calls
        assert calls[-1] == "state_machine", f"상태 머신은 마지막이어야 한다: {calls}"
        first_commit = calls.index("commit")
        for later in ("scan", "evidence", "mastery", "skill_mastery", "skill_event"):
            assert first_commit < calls.index(later), f"attempt commit이 {later}보다 늦다: {calls}"

    def test_skill_event_uses_its_own_source_label(self, spy: _Spy) -> None:
        """완료 경로 라벨과 섞이면 경로별 기록률 분모가 의미를 잃는다."""
        _record(_FakeSession(spy.calls))
        ev = spy.kwargs["skill_event"]
        assert ev["source"] is AttemptSource.coach_wrong_submission
        assert ev["is_correct"] is False
        assert ev["skill_ids"] == ["skill.a"]

    def test_rejected_transition_is_logged_and_the_attempt_is_kept(
        self, spy: _Spy, caplog: pytest.LogCaptureFixture
    ) -> None:
        spy.rejected = "DIAGNOSING → ASSESSING (UndefinedTransitionError)"
        session = _FakeSession(spy.calls)
        with caplog.at_level(logging.WARNING, logger=coach_module.logger.name):
            attempt_id = _record(session)
        assert attempt_id is not None
        assert "UndefinedTransitionError" in caplog.text and "EOS-146" in caplog.text


class TestFailureIsolation:
    def test_postprocessing_failure_does_not_break_the_reply_and_names_the_type(
        self, spy: _Spy, caplog: pytest.LogCaptureFixture
    ) -> None:
        """attempt 적재 뒤 후처리가 터져도 예외가 새지 않는다 — 학생은 재고 유도 발화를 받아야 한다.

        변별력: 반드시 터지는 스캔을 *주입*한다. 정상 경로에서는 이 격리가 한 번도 실행되지 않으므로
        주입 없는 초록은 증거가 아니다. 삼킨 사실은 예외 **타입명**으로 로그에 남는다(침묵 실패 금지).
        """
        spy.scan_error = RuntimeError("의도적 주입")
        session = _FakeSession(spy.calls)
        with caplog.at_level(logging.WARNING, logger=coach_module.logger.name):
            attempt_id = _record(session)
        assert attempt_id is not None, "후처리 실패가 attempt id를 지웠다"
        assert [o for o in session.added if isinstance(o, ProblemAttemptORM)]
        assert "commit" in spy.calls, "attempt가 durable하지 않다"
        assert "exc_type=RuntimeError" in caplog.text
        assert "state_machine" not in spy.calls, "후처리가 터졌는데 상태 머신이 돌았다"


class TestKillSwitch:
    def test_switch_off_touches_nothing(self, spy: _Spy, monkeypatch: pytest.MonkeyPatch) -> None:
        """끄면 조회도 적재도 없다 — 종전 동작과 비트동일(재고 유도 발화는 별개로 그대로다)."""
        monkeypatch.setenv("WHYMATH_L4_COACH_WRONG_SUBMISSION_ENABLED", "false")
        get_settings.cache_clear()
        try:
            session = _FakeSession(spy.calls)
            assert _record(session) is None
            assert session.lookups == 0 and session.added == [] and spy.calls == []
        finally:
            monkeypatch.delenv("WHYMATH_L4_COACH_WRONG_SUBMISSION_ENABLED", raising=False)
            get_settings.cache_clear()

    def test_switch_defaults_on(self) -> None:
        """정식 기능 — 기본값이 켜져 있다(꺼진 채 배포돼 R3·R6이 계속 0회 도는 것을 막는다)."""
        get_settings.cache_clear()
        assert get_settings().l4_coach_wrong_submission_enabled is True


class _Decision:
    """`decision.model_copy(update=...)`만 쓰는 최소 대역 — 이 파일의 관심은 분기다."""

    def __init__(self, **fields: Any) -> None:
        self.__dict__.update(fields)

    def model_copy(self, *, update: dict[str, Any]) -> _Decision:
        return _Decision(**{**self.__dict__, **update})


def _resolve(
    monkeypatch: pytest.MonkeyPatch,
    state: VerificationOutcome | None,
    writer_calls: list[dict[str, Any]],
) -> Any:
    async def _state(*_a: Any, **_k: Any) -> tuple[VerificationOutcome | None, Any]:
        return state, coach_module.FormVerdict.not_required

    async def _writer(_session: Any, **kwargs: Any) -> uuid.UUID:
        writer_calls.append(kwargs)
        return uuid.uuid4()

    async def _complete(*_a: Any, **_k: Any) -> tuple[None, None]:
        return None, None

    monkeypatch.setattr(coach_module, "_final_answer_state", _state)
    monkeypatch.setattr(coach_module, "_record_first_wrong_submission", _writer)
    monkeypatch.setattr(coach_module, "_complete_problem", _complete)
    body = SimpleNamespace(solution_steps=["x=1", _ANSWER])
    capabilities = SimpleNamespace(attempt_misconception_detector=_DETECTOR)
    return asyncio.run(
        coach_module._resolve_completion(
            object(),  # type: ignore[arg-type]
            user_id=_UID,
            problem_id=_PID,
            prior_review_remaining=0,
            already_completed=False,
            redirect_turn_index=1,
            body=body,  # type: ignore[arg-type]
            decision=_Decision(prompt="원래 발화", socratic_category=None),  # type: ignore[arg-type]
            capabilities=capabilities,  # type: ignore[arg-type]
            attempt_started_at=_T0,
        )
    )


class TestRedirectWiring:
    def test_redirect_calls_the_writer_and_never_returns_an_attempt_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """REDIRECT가 적재를 부르되 결과의 attempt_id는 None이다 — 완료 표지를 건드리지 않는다.

        호출자는 `completion.attempt_id`가 있으면 dialogue.attempt_id에 링크한다. 여기서 id를 돌려주면
        오답 하나로 풀던 대화가 통째로 '완료됨'이 된다 — 변별력은 그 반환값이다.
        """
        calls: list[dict[str, Any]] = []
        result = _resolve(monkeypatch, VerificationOutcome.incorrect, calls)
        assert len(calls) == 1
        assert calls[0]["final_answer"] == _ANSWER  # 풀이의 마지막 단계.
        assert calls[0]["started_at"] == _T0
        assert calls[0]["detector"] is _DETECTOR
        assert calls[0]["user_id"] == _UID and calls[0]["problem_id"] == _PID
        assert result.attempt_id is None
        assert result.problem_complete is False and result.awaiting_reflection is False
        assert result.handled is True  # 재고 유도 발화는 그대로 가로챈다.

    def test_correct_and_unverified_turns_do_not_record_a_wrong_attempt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """정답 도달(돌아보기 진입)·미검증(unverifiable·판정 없음)은 오답이 아니다.

        모른다 ≠ 아니다 — 판정하지 못한 것을 틀렸다고 접으면 미채점 이력이 학생을 교정 국면으로 민다.
        """
        for state in (VerificationOutcome.correct, VerificationOutcome.unverifiable, None):
            calls: list[dict[str, Any]] = []
            _resolve(monkeypatch, state, calls)
            assert calls == [], f"{state}에서 오답 적재가 불렸다"


class TestThisAttemptMisconceptionsFrom:
    """R3 입력 도출의 단일 좌석 — 두 채점 경로가 같은 규칙을 쓴다(EOS-138 ②)."""

    def test_keeps_only_scanned_and_gate_passed_candidates_with_updated_confidence(self) -> None:
        active = [
            SimpleNamespace(misconception_id="M-a", confidence=0.9),
            SimpleNamespace(misconception_id="M-b", confidence=0.8),
            SimpleNamespace(misconception_id="M-old", confidence=0.99),
        ]
        candidates = [
            SimpleNamespace(misconception_id="M-a", gate_passed=True),
            SimpleNamespace(misconception_id="M-b", gate_passed=False),
        ]
        got = this_attempt_misconceptions_from(active, candidates)  # type: ignore[arg-type]
        # M-b는 게이트 미통과라 되살리지 않는다 · M-old는 이번 스캔에 없다 · 신뢰는 갱신 후 값.
        assert got == (("M-a", 0.9),)

    def test_empty_when_nothing_was_scanned(self) -> None:
        active = [SimpleNamespace(misconception_id="M-old", confidence=0.99)]
        assert this_attempt_misconceptions_from(active, []) == ()  # type: ignore[arg-type]
