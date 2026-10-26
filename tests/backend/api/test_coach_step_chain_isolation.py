"""코치 턴의 풀이 단계 연쇄 검증·시도 오개념 훑기 격리 — 상한 초과는 판정 불가다(OPS-125).

`api/coach.py`의 세 핸들러는 `_build_response_payload`(동기)를 거쳐 L4가 `StepChainVerifier.verify_chain`
(SymPy)을 부르게 했고, 코치 오답 적재(EOS-146)는 `scan_attempt_answer`(SymPy)를 동기로 불렀다. async
핸들러 안의 동기 SymPy는 느린 식 1건이 그 워커의 모든 학생 요청을 멈춘다(OPS-96이 `verify.py`·최종답
판정에서 막은 바로 그 증상). 이 파일은 격리 뒤의 세 가지를 변별력과 함께 고정한다.

  ⓐ 정상 입력은 격리 전후 **같은 판정**이다(정상 문항이 판정 불가로 새지 않는다).
  ⓑ 상한 초과는 **전 전이 판정 불가**다 — 통과(검증 우회)도 오답(부당한 부정 피드백)도 아니고, 코치는
     그것으로 "검산하세요" 코칭을 내지 않는다. 훑기는 `RAN_NO_CANDIDATE`("봤는데 없다")가 아니라
     `NOT_RUN`("못 봤다")으로 접힌다.
  ⓒ 느린 식이 도는 동안 **이벤트 루프가 막히지 않는다**. 대조군(격리 OFF = 격리를 되돌린 뮤테이션과
     같은 상태)은 같은 측정에서 막힌다 — 이 대조군이 ⓒ가 "아무 때나 통과하는 검사"가 아님을 보인다.

느린 입력은 합성 sleep이 아니라 실제 SymPy가 느린 식이다(고유 계수 차수 14 ≈ 3.7초·같은 프로세스
캐시 적중 방지 — `test_verify_isolation._unique_slow` docstring 참조).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from whymath_backend.api import _isolated_call
from whymath_backend.api import coach as coach_module
from whymath_backend.api._attempt_misconception_scan import scan_attempt_misconceptions
from whymath_backend.api._auth import get_consented_user
from whymath_backend.app import create_app
from whymath_backend.config import Settings, get_settings
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.l4.solution_coaching import SolutionCoaching, recommend_coaching_for_solution
from whymath_backend.l4.subject_adapter_math import (
    MathAttemptMisconceptionDetector,
    MathStepChainVerifier,
)
from whymath_backend.schema.assessment_evidence import MisconceptionScan
from whymath_backend.schema.enums import Persona
from whymath_backend.schema.user import UserProfile as UserProfileSchema
from whymath_backend.schema.verification_capabilities import (
    ChainVerificationCounts,
    VerificationOutcome,
)

# 호출 1건 상한. 체인 총 예산 = 이 값 × CHAIN_BUDGET_FACTOR(4) = 1.0초 — 차수 14 방정식 전이(≈3.7초)보다
# 3배 이상 작다. 체인은 한 호출이라 상한이 곧 총 예산이다.
_CAP_S = 0.25
_CHAIN_BUDGET_S = _CAP_S * _isolated_call.CHAIN_BUDGET_FACTOR


def _unique_slow(degree: int) -> list[str]:
    """프로세스 안에서 처음 보는 느린 방정식 전이(2단계) — 계수 고유화로 SymPy 캐시 적중을 막는다."""
    k = time.time_ns() % 1_000_000 + 2
    return [f"x^{degree}+{k}*x+1=0", f"x^{degree - 1}+{k}*x+2=0"]


def _body(steps: list[str] | None, step_types: Any = None) -> Any:
    return SimpleNamespace(solution_steps=steps, solution_step_types=step_types)


def _configure(monkeypatch: pytest.MonkeyPatch, *, enabled: bool, cap_s: float) -> None:
    """env로 격리 설정을 바꾸고 캐시·풀을 비운다(설정은 프로세스 수명 캐시라 반드시 비운다)."""
    monkeypatch.setenv("WHYMATH_JWT_SECRET_KEY", "test-secret-0123456789abcdef")
    monkeypatch.setenv("WHYMATH_SYMPY_ISOLATION_ENABLED", "true" if enabled else "false")
    monkeypatch.setenv("WHYMATH_SYMPY_ISOLATION_TIMEOUT_S", str(cap_s))
    monkeypatch.setenv("WHYMATH_SYMPY_ISOLATION_MAX_WORKERS", "1")
    get_settings.cache_clear()
    _isolated_call.reset_pool_for_tests()


@pytest.fixture
def isolation_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    _configure(monkeypatch, enabled=True, cap_s=_CAP_S)
    yield
    _isolated_call.reset_pool_for_tests()
    get_settings.cache_clear()


@pytest.fixture
def isolation_off(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    _configure(monkeypatch, enabled=False, cap_s=_CAP_S)
    yield
    _isolated_call.reset_pool_for_tests()
    get_settings.cache_clear()


@pytest.fixture
def scan_tight(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """훑기 상한 초과 시험용 — 훑기의 자연 최악(`(x+y+z)^20` 전개 ≈0.7초)보다 작은 상한."""
    _configure(monkeypatch, enabled=True, cap_s=0.1)
    yield
    _isolated_call.reset_pool_for_tests()
    get_settings.cache_clear()


@pytest.fixture
def scan_loose(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """훑기 정상 입력 시험용 — 정상 문항이 상한에 걸려 판정 불가로 새지 않는 넉넉한 상한."""
    _configure(monkeypatch, enabled=True, cap_s=5.0)
    yield
    _isolated_call.reset_pool_for_tests()
    get_settings.cache_clear()


async def _warm() -> None:
    """워커 기동(SymPy import ≈1초)을 시간 상한 밖에서 미리 치른다."""
    verifier = MathStepChainVerifier()
    out = await coach_module._verify_chain_isolated(_body(["2*(x+1)", "2*x+2"]), verifier)
    assert out is not None and out.n_correct == 1
    # 오답(`incorrect`) 판정 경로와 전개 경로까지 데운다 — 이 경로의 첫 계산이 상한(0.25초) 안에서
    # 치러지면 느린 CI에서 정상 입력이 판정 불가로 새 테스트가 흔들린다(뮤테이션 M7 실측).
    await coach_module._verify_chain_isolated(_body(["(a+b)^2", "a^2+b^2"]), verifier)


# ── ⓐ 정상 입력은 격리 전후 같은 판정 ─────────────────────────────────────────────


@pytest.mark.usefixtures("isolation_on")
class TestNormalChainUnchanged:
    async def test_isolated_verdict_equals_inline_verdict(self) -> None:
        verifier = MathStepChainVerifier()
        await _warm()
        for steps in (
            ["2*x+4", "2*(x+2)", "2*x+4"],  # 전부 동치
            ["(a+b)^2", "a^2+2*a*b+b^2", "a^2+b^2"],  # 마지막 전이가 오답
        ):
            isolated_out = await coach_module._verify_chain_isolated(_body(steps), verifier)
            assert isolated_out == verifier.verify_chain(steps, None)

    async def test_wrong_chain_is_still_incorrect_not_unverifiable(self) -> None:
        """정상 오답은 격리 뒤에도 `incorrect`로 남는다 — 오답이 판정 불가로 새면 코칭이 사라진다."""
        await _warm()
        out = await coach_module._verify_chain_isolated(
            _body(["(a+b)^2", "a^2+b^2"]), MathStepChainVerifier()
        )
        assert out is not None
        assert out.n_incorrect == 1 and out.first_incorrect_index == 0
        assert out.n_unverifiable == 0

    async def test_fewer_than_two_steps_has_nothing_to_verify(self) -> None:
        verifier = MathStepChainVerifier()
        assert await coach_module._verify_chain_isolated(_body(None), verifier) is None
        assert await coach_module._verify_chain_isolated(_body([]), verifier) is None
        assert await coach_module._verify_chain_isolated(_body(["x"]), verifier) is None

    async def test_step_types_length_error_still_propagates(self) -> None:
        """입력 규약 위반(`step_types` 길이)은 격리와 무관하게 같은 예외 — 판정 불가로 접히지 않는다."""
        with pytest.raises(ValueError):
            await coach_module._verify_chain_isolated(
                _body(["a", "b", "c"], ["계산"]), MathStepChainVerifier()
            )


# ── ⓑ 상한 초과는 판정 불가 ──────────────────────────────────────────────────────


@pytest.mark.usefixtures("isolation_on")
class TestOverBudgetIsUnverifiable:
    async def test_over_budget_chain_is_all_unverifiable(self) -> None:
        await _warm()
        timeouts_before = _isolated_call.isolation_stats()["timeouts"]
        out = await coach_module._verify_chain_isolated(
            _body(_unique_slow(14)), MathStepChainVerifier()
        )
        assert isinstance(out, coach_module._BudgetExceededChain)
        assert out.n_transitions == 1
        assert out.n_unverifiable == 1  # 전부 판정 불가
        assert out.n_correct == 0  # 통과로 접히지 않는다(검증 우회 금지)
        assert out.n_incorrect == 0  # 오답으로 접히지 않는다(부당한 부정 피드백 금지)
        assert out.first_incorrect_index is None
        assert out.unverified_ratio == 1.0
        assert all(s.state is VerificationOutcome.unverifiable for s in out.steps)
        # "계산이 끊겼다"는 벽시계가 아니라 인과 증거로 단언한다 — `timeouts`는 상한 시간이 지나
        # 워커를 kill했을 때만 오른다(벽시계 상한은 워커 재기동 대기 때문에 환경 속도에 흔들린다).
        assert _isolated_call.isolation_stats()["timeouts"] == timeouts_before + 1

    async def test_budget_is_the_chain_total_not_per_transition(self) -> None:
        """체인 한 건은 `상한 × 4`를 총 예산으로 받는다 — 풀에 실제로 전달된 상한을 본다."""
        seen: list[float | None] = []

        class _Spy:
            async def run(
                self, fn: Any, *args: Any, timeout_s: float | None = None, **kw: Any
            ) -> Any:
                seen.append(timeout_s)
                return fn(*args, **kw)

        original = _isolated_call._get_pool
        _isolated_call._get_pool = lambda: _Spy()  # type: ignore[assignment]
        try:
            await coach_module._verify_chain_isolated(
                _body(["2*(x+1)", "2*x+2"]), MathStepChainVerifier()
            )
        finally:
            _isolated_call._get_pool = original
        assert seen == [pytest.approx(_CHAIN_BUDGET_S)]

    def test_budget_chain_satisfies_the_core_contract(self) -> None:
        """중립 초과 값은 `ChainVerificationCounts` 구조·합 보존 규약을 지키고 그대로 직렬화된다."""
        out = coach_module._budget_exceeded_chain(3)
        assert isinstance(out, ChainVerificationCounts)
        assert len(out.steps) == out.n_transitions == 3
        assert out.n_correct + out.n_incorrect + out.n_unverifiable == out.n_transitions
        assert sum(out.unverifiable_by_reason.values()) == out.n_unverifiable
        # 이벤트 적재(`_log_verify_event`)가 `code.value`를 읽는다 — 기존 폐쇄 어휘와 같은 문자열.
        assert {c.value: n for c, n in out.unverifiable_by_reason.items()} == {"undecidable": 3}
        dumped = SolutionCoaching.model_construct(solution_verification=out).model_dump(mode="json")
        assert dumped["solution_verification"]["n_unverifiable"] == 3
        assert dumped["solution_verification"]["unverifiable_by_reason"] == {"undecidable": 3}

    def test_coaching_reads_budget_exceeded_as_no_signal(self) -> None:
        """코치는 초과 값으로 "검산하세요"를 내지 않는다 — 대조군(진짜 오답)은 낸다."""
        steps = ["(a+b)^2", "a^2+b^2"]

        def _focus(chain: Any) -> tuple[bool, str]:
            sc = recommend_coaching_for_solution(
                "",
                0.95,
                None,
                solution_steps=steps,
                chain_verification=chain,
            )
            return sc.arithmetic_error, str(getattr(sc.trigger.focus, "value", sc.trigger.focus))

        err, focus = _focus(coach_module._budget_exceeded_chain(1))
        assert err is False and focus != "verify"
        err_ctrl, focus_ctrl = _focus(MathStepChainVerifier().verify_chain(steps, None))
        assert err_ctrl is True and focus_ctrl == "verify"  # 대조군 — 진짜 오답은 코칭이 된다

    def test_precomputed_chain_is_used_without_calling_the_verifier(self) -> None:
        """선계산 값이 주어지면 L4는 verifier를 부르지 않는다 — 서빙 중 SymPy가 동기로 안 돈다."""

        class _Boom:
            def verify_chain(self, steps: Any, step_types: Any = None) -> Any:
                raise AssertionError("선계산 값이 있는데 verifier가 호출됐다")

        sc = recommend_coaching_for_solution(
            "",
            0.95,
            None,
            solution_steps=["a", "b"],
            verifier=_Boom(),
            chain_verification=coach_module._budget_exceeded_chain(1),
        )
        assert sc.solution_verification.n_unverifiable == 1


def _client() -> TestClient:
    app = create_app()
    uid = uuid.uuid4()
    app.dependency_overrides[get_consented_user] = lambda: UserProfile.from_schema(
        UserProfileSchema(user_id=uid, persona_primary=Persona.A_일반고고3)
    )
    app.dependency_overrides[get_settings] = lambda: Settings(
        jwt_secret_key=SecretStr("test-secret-0123456789abcdef"),
        coach_rate_limit_read_per_minute=0,
        coach_rate_limit_write_per_minute=0,
        coach_rate_limit_ip_read_per_minute=0,
        coach_rate_limit_ip_write_per_minute=0,
        coach_rate_limit_device_read_per_minute=0,
        coach_rate_limit_device_write_per_minute=0,
    )

    class _NoDb:
        async def execute(self, stmt: Any) -> None:
            raise AssertionError("stateless /v1/coach는 DB 쿼리하지 않아야 한다.")

    async def _sess() -> AsyncIterator[_NoDb]:
        yield _NoDb()

    app.dependency_overrides[get_session] = _sess
    return TestClient(app)


@pytest.mark.usefixtures("isolation_on")
class TestCoachEndpointEndToEnd:
    """`/v1/coach` 종단 — 느린 풀이가 200으로 끝나고 부당한 "틀렸다" 코칭을 만들지 않는다."""

    def test_slow_chain_yields_no_verify_coaching_and_wrong_chain_still_does(self) -> None:
        with _client() as client:
            ok = client.post(
                "/v1/coach",
                json={
                    "student_input": "확인",
                    "bkt_mastery": 0.95,
                    "solution_steps": ["2*(x+1)", "2*x+2"],
                },
            )  # 워커 기동을 상한 밖에서 미리 치른다
            assert ok.status_code == 200, ok.text
            # 대조군(진짜 오답)을 느린 요청 *앞에서* 보낸다 — 느린 요청이 워커를 kill하면 교체
            # 워커는 식어 있어, 그 뒤의 정상 입력이 첫 계산 비용 때문에 상한에 걸릴 수 있다.
            wrong = client.post(
                "/v1/coach",
                json={
                    "student_input": "확인",
                    "bkt_mastery": 0.95,
                    "solution_steps": ["(a+b)^2", "a^2+b^2"],
                },
            )
            timeouts_before = _isolated_call.isolation_stats()["timeouts"]
            slow = client.post(
                "/v1/coach",
                json={
                    "student_input": "확인",
                    "bkt_mastery": 0.95,
                    "solution_steps": _unique_slow(14),
                },
            )
        assert slow.status_code == 200, slow.text
        sc = slow.json()["solution_coaching"]
        # 노출 게이트가 판정 불가 풀이를 숨기든(None) 노출하든, "틀린 단계가 있다"는 처방은 아니다.
        assert sc is None or (
            sc["arithmetic_error"] is False and sc["trigger"]["focus"] != "verify"
        )
        assert _isolated_call.isolation_stats()["timeouts"] == timeouts_before + 1
        # 대조군 — 같은 경로에서 진짜 오답은 격리 뒤에도 검산 코칭이 된다.
        assert wrong.status_code == 200, wrong.text
        assert wrong.json()["solution_coaching"]["trigger"]["focus"] == "verify"


# ── ⓒ 루프 비차단 + 대조군 ───────────────────────────────────────────────────────


async def _max_loop_gap_during(work: Any) -> float:
    """`work()`가 도는 동안 이벤트 루프가 한 번에 멈춘 최대 시간(초) — 10ms 박동의 최대 간격.

    루프가 막히면 박동 코루틴이 돌지 못해 간격이 막힌 시간만큼 벌어진다. 가벼운 HTTP 요청을 따로
    보내는 것과 같은 현상(루프 점유)을 더 단순하게 잰다.
    """
    gaps: list[float] = []
    stop = asyncio.Event()

    async def _beat() -> None:
        last = time.perf_counter()
        while not stop.is_set():
            await asyncio.sleep(0.01)
            now = time.perf_counter()
            gaps.append(now - last)
            last = now

    beat = asyncio.create_task(_beat())
    await asyncio.sleep(0.05)  # 박동이 돌기 시작한 뒤에 일을 시작한다
    try:
        await work()
    finally:
        stop.set()
        await beat
    return max(gaps)


class TestEventLoopNotBlocked:
    async def test_loop_keeps_beating_while_slow_chain_runs(self, isolation_on: None) -> None:
        """격리 ON — 느린 연쇄(≈3.7초)가 상한(1.0초)에 끊기는 동안 루프 정지가 0.3초 미만이다."""
        await _warm()
        verifier = MathStepChainVerifier()
        slow = _unique_slow(14)

        gap = await _max_loop_gap_during(
            lambda: coach_module._verify_chain_isolated(_body(slow), verifier)
        )
        assert gap < 0.3, f"이벤트 루프가 {gap:.2f}s 멈췄다 — 격리가 루프를 비우지 못했다"

    async def test_control_without_isolation_blocks_the_loop(self, isolation_off: None) -> None:
        """대조군 — 격리 OFF(= 격리를 되돌린 뮤테이션)면 같은 측정에서 루프가 연쇄 계산 내내 막힌다.

        이 테스트가 GREEN이라는 것은 위 `test_loop_keeps_beating...`가 격리 때문에 통과했다는
        증거다. 고유 입력(차수 12 ≈ 2.2초)을 쓰는 이유: 같은 프로세스 SymPy 캐시에 적중하면 빠르게
        끝나 대조군이 변별하지 못한다.
        """
        verifier = MathStepChainVerifier()
        slow = _unique_slow(12)

        gap = await _max_loop_gap_during(
            lambda: coach_module._verify_chain_isolated(_body(slow), verifier)
        )
        assert gap > 1.0, f"격리 OFF인데 루프 정지 {gap:.2f}s — 대조군이 변별하지 못한다"


# ── 시도 오개념 훑기 ─────────────────────────────────────────────────────────────


class _ScanSession:
    """`session.scalar(...)`로 문항 지문만 돌려주는 가짜 세션(선지 채널은 인덱스 미보고라 안 읽는다)."""

    def __init__(self, question_text: str) -> None:
        self._question_text = question_text

    async def scalar(self, stmt: Any) -> Any:
        return self._question_text


async def _scan(question: str, answer: str) -> Any:
    return await scan_attempt_misconceptions(
        _ScanSession(question),  # type: ignore[arg-type]
        MathAttemptMisconceptionDetector(),
        problem_id=uuid.uuid4(),
        answer=answer,
        selected_choice_index=None,
    )


class TestAttemptMisconceptionScanBudget:
    @pytest.mark.usefixtures("scan_loose")
    async def test_normal_answer_is_scanned_as_before(self) -> None:
        """정상 답안은 격리 전후 같은 훑기 결과 — 후보가 그대로 나온다."""
        result = await _scan("(a+b)^2 를 전개하시오", "a^2+b^2")
        assert result.scan is MisconceptionScan.RAN_WITH_CANDIDATES
        assert result.candidates

    @pytest.mark.usefixtures("scan_tight")
    async def test_over_budget_scan_is_not_run_never_ran_no_candidate(self) -> None:
        """상한 초과 → `NOT_RUN`("못 봤다") — `RAN_NO_CANDIDATE`("봤는데 없다")로 접히면 안 된다.

        후자로 접으면 측정 못 한 것을 측정된 0으로 읽는 하류가 그 회차를 "오개념 증거 없음"으로
        가설 감쇠에 쓴다(`MisconceptionScan` 3상태가 존재하는 이유).
        """
        await _scan("x+1=3 의 해를 구하시오", "x=2")  # 워커 기동을 상한 밖에서 미리 치른다
        timeouts_before = _isolated_call.isolation_stats()["timeouts"]
        result = await _scan("(x+y+z)^20 을 전개하시오", "x^20+y^20+z^20")
        assert result.scan is MisconceptionScan.NOT_RUN
        assert result.scan is not MisconceptionScan.RAN_NO_CANDIDATE
        assert result.candidates == ()
        assert _isolated_call.isolation_stats()["timeouts"] == timeouts_before + 1
