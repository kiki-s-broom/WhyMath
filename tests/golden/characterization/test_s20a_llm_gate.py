"""GOLD-20 특성화 — 골든 관할 게이트가 옛 `CompositeProvider._guard_cloud_jurisdiction`과 같은 판정을 낸다.

같은 (제공자 관할 · 코퍼스 opt-in · 결정 등급) 10가지에서 통과/차단과 차단 사유가 같은지 본다.
옛 판정 규칙(`l3.provider_jurisdiction`)이 바뀌면 이 테스트가 RED가 되어 골든 감싸개를 다시 맞추게 한다.
의도적 차이 1개(관할 선언 없음 → 옛 것은 US로 통과 · 골든은 차단)는 별도 테스트로 고정한다.

그리고 튜터 행동: 차단되면 클라우드 호출이 0회이고 학생 화면은 대체 문장(degraded)으로 이어진다.
옛 모듈은 이 테스트에서만 import한다(골든 패키지는 import하지 않는다 — test_import_budget.py).
"""

from __future__ import annotations

import asyncio
from typing import Any

import golden.tutor as tutor
import pytest
from golden.llm.gate import JurisdictionBlockedError, guard_cloud_jurisdiction
from golden.problems import load_problems

from whymath_backend.l3.models import (
    CostTier,
    GenerationResult,
    LocalModelTier,
    ModelFamily,
    RoutingDecision,
    Usage,
)
from whymath_backend.l3.provider_jurisdiction import Jurisdiction
from whymath_backend.l3.providers.composite import CompositeProvider
from whymath_backend.schema.enums import LicenseType


class _Provider:
    """관할만 선언한 가짜 제공자. generate가 불린 횟수를 센다."""

    def __init__(self, jurisdiction: Any, *, opt_in: bool = False, declare: bool = True) -> None:
        if declare:
            self.jurisdiction = jurisdiction
        self.allow_internal_corpus = opt_in
        self.calls = 0

    async def generate(self, prompt: str, system: str, decision: RoutingDecision) -> Any:
        self.calls += 1
        return GenerationResult(text="기울기는 무엇의 비일까?", usage=Usage())


def _decision(tier: CostTier, *licenses: LicenseType) -> RoutingDecision:
    # LOCAL 결정은 로컬 모델 지정이 필수다(라우터 불변식) — 값 자체는 게이트 판정과 무관하다
    local: dict[str, Any] = (
        {"local_model": LocalModelTier.FAST, "local_family": ModelFamily.GENERAL}
        if tier is CostTier.LOCAL
        else {}
    )
    return RoutingDecision(cost_tier=tier, est_latency_ms=1000, data_licenses=licenses, **local)


GEN, CORPUS, USER = (
    LicenseType.WHYMATH_GENERATED,
    LicenseType.INTERNAL_OWNED,
    LicenseType.USER_GENERATED,
)
MID, HIGH, LOCAL = CostTier.CLOUD_MID, CostTier.CLOUD_HIGH, CostTier.LOCAL

# (이름, 관할, opt-in, 결정) — 입력 10개
_CASES: list[tuple[str, Jurisdiction, bool, RoutingDecision]] = [
    ("US · 골든 튜터 등급", Jurisdiction.US, False, _decision(MID, GEN)),
    ("US · 선언 없음", Jurisdiction.US, False, _decision(MID)),
    ("CN · 생성 문항만", Jurisdiction.CN, False, _decision(MID, GEN)),
    ("CN · 코퍼스 opt-in 없음", Jurisdiction.CN, False, _decision(MID, GEN, CORPUS)),
    ("CN · 코퍼스 opt-in", Jurisdiction.CN, True, _decision(HIGH, GEN, CORPUS)),
    ("CN · 선언 없음", Jurisdiction.CN, False, _decision(MID)),
    ("국적 미상 · 생성 문항", Jurisdiction.UNKNOWN, False, _decision(MID, GEN)),
    ("국적 미상 · LOCAL은 검사 안 함", Jurisdiction.UNKNOWN, False, _decision(LOCAL, GEN)),
    ("국내 · 학생 저작", Jurisdiction.DOMESTIC, False, _decision(MID, USER)),
    ("CN · 학생 저작은 opt-in으로도 불가", Jurisdiction.CN, True, _decision(MID, USER, GEN)),
]


def _verdict(call: Any) -> tuple[str, str]:
    """통과면 ('pass', ''), 차단이면 ('block', 사유 부분)."""
    try:
        call()
    except RuntimeError as exc:  # 골든 JurisdictionBlockedError도 RuntimeError 하위
        message = str(exc)
        return ("block", message[: message.index(")") + 1])  # "…(관할=…, 사유=…)"까지
    return ("pass", "")


def _legacy(provider: object, decision: RoutingDecision) -> tuple[str, str]:
    composite = CompositeProvider.__new__(CompositeProvider)  # 생성자 없이 게이트 메서드만 쓴다
    if decision.cost_tier == CostTier.LOCAL.value:
        return ("pass", "")  # 옛 generate는 LOCAL이면 게이트를 부르지 않는다
    return _verdict(lambda: composite._guard_cloud_jurisdiction(provider, decision))  # noqa: SLF001


@pytest.mark.parametrize(
    ("label", "juris", "opt_in", "decision"), _CASES, ids=[c[0] for c in _CASES]
)
def test_gate_matches_legacy_composite(
    label: str, juris: Jurisdiction, opt_in: bool, decision: RoutingDecision
) -> None:
    provider = _Provider(juris, opt_in=opt_in)
    golden = _verdict(lambda: guard_cloud_jurisdiction(provider, decision))
    assert golden == _legacy(provider, decision), label


def test_cases_are_discriminating() -> None:
    verdicts = {
        _verdict(lambda c=c: guard_cloud_jurisdiction(_Provider(c[1], opt_in=c[2]), c[3]))[0]
        for c in _CASES
    }
    assert verdicts == {"pass", "block"} and len(_CASES) == 10


def test_undeclared_jurisdiction_is_blocked_unlike_legacy_default() -> None:
    # 의도적 차이: 옛 것은 선언 없는 제공자를 US로 보고 통과시킨다. 골든은 막는다(fail-closed)
    provider = _Provider(None, declare=False)
    decision = _decision(MID, GEN)
    assert _legacy(provider, decision) == ("pass", "")
    with pytest.raises(JurisdictionBlockedError):
        guard_cloud_jurisdiction(provider, decision)
    with pytest.raises(JurisdictionBlockedError):  # 문자열 선언도 반올림하지 않는다
        guard_cloud_jurisdiction(_Provider("us"), decision)


def test_golden_openrouter_seat_passes_with_default_allowlist() -> None:
    # 정상 경로 대조군: 기본 허용 공급사(미국 법인)의 골든 제공자는 튜터 결정으로 통과한다
    from golden.llm.openrouter import OpenRouterProvider

    from whymath_backend.config import Settings
    from whymath_backend.l3.router import Router

    provider = OpenRouterProvider(settings=Settings(openrouter_api_key="sk-or-test-not-a-real-key"))
    decision = Router().route(tutor._routing_request())  # noqa: SLF001
    assert provider.jurisdiction is Jurisdiction.US
    guard_cloud_jurisdiction(provider, decision)  # 예외 없음


@pytest.mark.parametrize(
    ("juris", "expect_calls"), [(Jurisdiction.UNKNOWN, 0), (Jurisdiction.US, 1)]
)
def test_tutor_blocked_seat_never_calls_llm(
    juris: Jurisdiction, expect_calls: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 차단되면 클라우드 호출 0회 · 대체 문장(degraded). 통과 대조군은 1회 호출 · 정상 문장
    provider = _Provider(juris)
    monkeypatch.delenv("GOLDEN_FAKE_LLM", raising=False)
    monkeypatch.setattr(tutor, "build_cloud_provider", lambda: provider)
    problem = load_problems()[0]
    reply = asyncio.run(tutor.ask(problem, [], "3이요"))
    assert provider.calls == expect_calls
    assert reply.degraded is (expect_calls == 0)
    if expect_calls == 0:
        assert reply.message.startswith(tutor.FAKE_PREFIX)


@pytest.mark.parametrize(
    ("juris", "expect_calls"), [(Jurisdiction.UNKNOWN, 0), (Jurisdiction.US, 1)]
)
def test_sim_student_blocked_seat_never_calls_llm(
    juris: Jurisdiction, expect_calls: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 시뮬레이터 학생 LLM도 같은 게이트를 거친다 — 차단이면 호출 0회 · 재시도 소진 뒤 멈춘다
    import golden.sim_student as sim

    provider = _Provider(juris)
    monkeypatch.setattr(sim, "build_cloud_provider", lambda: provider)
    result = sim.SimResult(
        persona="slope-blind", nickname="sim-test-1", session_id="s", mode="live", retry_rule=False
    )

    async def go() -> str:
        return await sim._live_student_line("규칙", "문제", result)  # noqa: SLF001

    if expect_calls == 0:
        with pytest.raises(sim.SimStudentError, match="JurisdictionBlockedError"):
            asyncio.run(go())
        assert result.student_llm_failures == sim.STUDENT_LLM_TRIES
    else:
        assert asyncio.run(go())
    assert provider.calls == expect_calls
