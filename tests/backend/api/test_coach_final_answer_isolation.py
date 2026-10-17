"""코치 턴의 최종답 판정 격리 — 상한 초과는 판정 불가이지 정답·오답이 아니다(OPS-96).

`api/coach.py::_final_answer_state`는 완료 상태머신의 *정답/오답 도달 감지* 입력이다. 여기서 SymPy가
이벤트 루프를 막으면 그 워커의 모든 학생 턴이 멈추고, 상한 초과를 정답으로 접으면 풀지 않은 문제가
완료 처리되고(검증 우회), 오답으로 접으면 학생이 부당한 REDIRECT(부정 피드백)를 받는다.

느린 입력은 합성 sleep이 아니라 실제 SymPy가 느린 식이다(고유 계수 차수 14 ≈ 3.7초·같은 프로세스
캐시 적중 방지 — `test_verify_isolation._unique_slow` docstring 참조).
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest

from whymath_backend.api import _isolated_call
from whymath_backend.api import coach as coach_module
from whymath_backend.config import get_settings
from whymath_backend.db.models.problem import Problem as ProblemORM
from whymath_backend.l4.subject_adapter_math import (
    MathAnswerFormVerifier,
    MathFinalAnswerVerifier,
)
from whymath_backend.schema.answer_form import FormVerdict
from whymath_backend.schema.verification_capabilities import VerificationOutcome


def _unique_slow_equation(degree: int) -> str:
    """프로세스 안에서 처음 보는 느린 방정식(계수 고유화 — SymPy 캐시 적중 방지)."""
    k = time.time_ns() % 1_000_000 + 2
    return f"x^{degree}+{k}*x+1=0"


class _Session:
    """`session.get(ProblemORM, id)`만 지원하는 가짜 세션 — 문항 스텁을 돌려준다."""

    def __init__(self, problem: Any) -> None:
        self._problem = problem

    async def get(self, model: Any, ident: Any) -> Any:
        assert model is ProblemORM
        return self._problem


def _problem(answer: str) -> SimpleNamespace:
    return SimpleNamespace(
        answer=answer,
        answer_constraint=None,
        choices=None,
        question_format=None,
        answer_format=None,
        multiple_answers=None,
    )


def _capabilities() -> Any:
    return coach_module._SubjectCapabilityDeps(
        final_answer=MathFinalAnswerVerifier(),
        answer_form=MathAnswerFormVerifier(),
        step_chain=None,  # type: ignore[arg-type]
        attempt_misconception_detector=None,  # type: ignore[arg-type]
    )


@pytest.fixture
def isolation_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("WHYMATH_JWT_SECRET_KEY", "test-secret-0123456789abcdef")
    monkeypatch.setenv("WHYMATH_SYMPY_ISOLATION_ENABLED", "true")
    monkeypatch.setenv("WHYMATH_SYMPY_ISOLATION_TIMEOUT_S", "0.5")
    monkeypatch.setenv("WHYMATH_SYMPY_ISOLATION_MAX_WORKERS", "1")
    get_settings.cache_clear()
    _isolated_call.reset_pool_for_tests()
    yield
    _isolated_call.reset_pool_for_tests()
    get_settings.cache_clear()


async def _state(last_step: str, answer: str) -> tuple[Any, FormVerdict]:
    body = SimpleNamespace(solution_steps=[last_step])
    return await coach_module._final_answer_state(
        _Session(_problem(answer)),  # type: ignore[arg-type]
        uuid.uuid4(),
        body,  # type: ignore[arg-type]
        capabilities=_capabilities(),
    )


@pytest.mark.usefixtures("isolation_on")
class TestFinalAnswerIsolation:
    async def test_normal_answers_are_judged_as_before(self) -> None:
        """정상 최종답은 격리 전후 같은 판정 — 정답은 correct, 오답은 incorrect."""
        assert (await _state("x=3", "3"))[0] is VerificationOutcome.correct
        assert (await _state("x=4", "3"))[0] is VerificationOutcome.incorrect

    async def test_over_cap_is_unverifiable_never_correct_nor_incorrect(self) -> None:
        """상한 초과 → `unverifiable` — 완료(정답)도 REDIRECT(오답)도 일으키지 않는다."""
        await _state("x=3", "3")  # 워커 기동을 상한 밖에서 미리 치른다
        timeouts_before = _isolated_call.isolation_stats()["timeouts"]
        state, form = await _state(_unique_slow_equation(14), "x^13+x+2=0")
        assert state is VerificationOutcome.unverifiable
        assert state is not VerificationOutcome.correct  # 검증 우회 금지
        assert state is not VerificationOutcome.incorrect  # 부당한 부정 피드백 금지
        assert form is not FormVerdict.violated  # 형태 위반으로도 접히지 않는다
        # "계산이 끊겼다"는 벽시계가 아니라 인과 증거로 단언한다 — `timeouts`는 상한 시간이 지나
        # 워커를 kill했을 때만 오른다. 벽시계 상한(구 `elapsed < 2.0`)은 환경 속도에 따라 거짓
        # 실패한다: max_workers=1이라 kill 뒤 폼 판정 호출이 교체 워커의 ready(SymPy import ≈1.4초,
        # 설계상 상한 밖)를 기다리므로 총 소요가 상한 0.5초 + ≈1.4초 ≈ 1.9초로 경계(2.0초)에
        # 0.1초 차이까지 붙고, 상한 없는 같은 식은 3.3~3.6초라 경계가 양쪽으로 어정쩡했다
        # (OPS-123 회수 중 4코어 샌드박스 실측 2026-10-09).
        assert _isolated_call.isolation_stats()["timeouts"] == timeouts_before + 1

    async def test_unpicklable_capability_still_works_via_thread_fallback(self) -> None:
        """pickle 불가 능력(테스트 스텁)은 스레드 폴백으로 *동작은* 유지된다(상한은 없음 — 로그·카운트)."""

        class _Stub:
            def verify_final_answer(self, student_answer: str, problem: Any) -> Any:
                return SimpleNamespace(state=VerificationOutcome.correct)

        caps = _capabilities()._replace(final_answer=_Stub())
        body = SimpleNamespace(solution_steps=["x=3"])
        state, _ = await coach_module._final_answer_state(
            _Session(_problem("3")),  # type: ignore[arg-type]
            uuid.uuid4(),
            body,  # type: ignore[arg-type]
            capabilities=caps,
        )
        assert state is VerificationOutcome.correct
        assert _isolated_call.isolation_stats()["fallbacks"] >= 1


class TestBudgetOutcomeIsNeutral:
    def test_budget_outcome_state_is_unverifiable(self) -> None:
        """중립 초과 값은 어떤 경우에도 `unverifiable`이다 — 완료·REDIRECT 분기가 둘 다 False."""
        outcome = coach_module._BUDGET_EXCEEDED_OUTCOME
        assert outcome.state is VerificationOutcome.unverifiable
        # coach가 이 상태를 읽는 분기(`state is correct` / `state is incorrect`)에 걸리지 않는다.
        assert (outcome.state is VerificationOutcome.correct) is False
        assert (outcome.state is VerificationOutcome.incorrect) is False

    def test_problem_snapshot_passes_through_non_orm_objects(self) -> None:
        stub = _problem("3")
        assert coach_module._problem_snapshot(stub) is stub

    def test_problem_snapshot_copies_loaded_orm_columns_only(self) -> None:
        """ORM 인스턴스는 *이미 로드된 컬럼만* 복사한 읽기 전용 스냅샷으로 바뀐다(세션 상태 미동반)."""
        orm = ProblemORM(answer="3", question_text="q")
        snap = coach_module._problem_snapshot(orm)
        assert snap is not orm
        assert snap.answer == "3"
        assert not any(k.startswith("_") for k in vars(snap))
        # pickle 가능해야 워커 프로세스로 넘어간다.
        import pickle

        assert pickle.loads(pickle.dumps(snap)).answer == "3"
