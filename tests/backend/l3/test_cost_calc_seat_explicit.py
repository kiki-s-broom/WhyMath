"""OPS-116 — 원가 계산 호출 6곳이 좌석(seat)을 명시한다 + 신규 호출의 좌석 생략을 AST로 막는다.

배경: `actual_cost_usd`·`actual_cost_usd_or_none`·`actual_cost_krw`의 `seat` 기본값은
`SERVING_CLOUD_SEAT`(anthropic)다. ARCH-64 이후 학생 대면·저작 좌석은 기본 openrouter인데, 이 기본값에
기대어 좌석을 생략한 호출 6곳(`cross_verify`·`multi_solution`·`pedagogy/analogy_generator`·
`pedagogy/explanation_generator`·`queue/tasks`·`ops/live_preflight`)이 openrouter 호출을 anthropic
단가로 적었다(CLOUD_MID 실측 22.5배 과대 계상). OPS-109(`prewarmer`)가 같은 결함을 고치다 발견한 부수
사실이다.

이 파일이 동결하는 것:
  ① **집행 지점(별항)** — 패키지 전체의 원가 함수 호출은 `seat` 키워드를 반드시 싣는다. 신규 호출이 좌석을
    생략하면 RED. 스캔 0건·검사기 자체의 변별력(주입 RED + 대조군)을 함께 단언한다.
  ② **동작** — 좌석별로 단가표가 갈리고(openrouter ≠ anthropic), 좌석 미상(None)은 anthropic으로 접히지
    않고 '미측정'(None)으로 남으며, 같은 좌석이 trace의 `cloud_seat`에 실린다. LOCAL은 0원·`cloud_seat=None`.

오라클은 구현이 아닌 순수 함수다: 기대 원가는 `actual_cost_krw`를 좌석 명시로 직접 불러 얻는다. 좌석 간
값이 실제로 다른지(`!=`)도 전제로 단언한다 — 같으면 좌석 오류가 있어도 통과한다.
"""

from __future__ import annotations

import ast
import asyncio
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.l3.cross_verify import CrossVerifier
from whymath_backend.l3.models import (
    CostTier,
    GenerationResult,
    RoutingDecision,
    Usage,
)
from whymath_backend.l3.multi_solution import _record_trace as ms_record_trace
from whymath_backend.l3.pedagogy.analogy_generator import AnalogyGenerator
from whymath_backend.l3.pedagogy.explanation_generator import ExplanationGenerator
from whymath_backend.l3.queue.tasks import (
    PAYLOAD_DECISION,
    PAYLOAD_PROMPT,
    PAYLOAD_SYSTEM,
    run_quality_generation_payload,
)
from whymath_backend.l3.router import actual_cost_krw
from whymath_backend.ops import live_preflight as lp

_PKG = Path(__file__).resolve().parents[3] / "src" / "backend" / "whymath_backend"

# 좌석을 키워드로 반드시 싣는 원가 함수 — 시그니처가 `*`(키워드 전용)라 위치 인자로는 좌석을 못 준다.
_COST_FUNCS = {"actual_cost_usd", "actual_cost_usd_or_none", "actual_cost_krw"}

_USAGE = Usage(input_tokens=1_000_000, output_tokens=1_000_000, latency_ms=42.0)


# ──────────────────────────────────────────────────────────────────────
# ① 집행 지점 — AST 소스 스캔
# ──────────────────────────────────────────────────────────────────────
def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _seatless_calls(source: str) -> list[int]:
    """원가 함수를 `seat` 키워드 없이 부르는 줄 번호 목록 — `**kwargs` 전개는 모른다로 위반 처리."""
    bad: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and _call_name(node) in _COST_FUNCS:
            has_seat = any(kw.arg == "seat" for kw in node.keywords)
            if not has_seat:  # kw.arg is None(**전개)도 좌석 보장 불가 → 위반
                bad.append(node.lineno)
    return bad


def _scan_package() -> dict[str, list[int]]:
    """패키지 전체 → {상대 경로: 좌석 생략 호출 줄들}(위반 파일만)."""
    out: dict[str, list[int]] = {}
    for path in sorted(_PKG.rglob("*.py")):
        lines = _seatless_calls(path.read_text(encoding="utf-8"))
        if lines:
            out[path.relative_to(_PKG).as_posix()] = lines
    return out


def _total_cost_calls() -> int:
    total = 0
    for path in sorted(_PKG.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        total += sum(
            1 for n in ast.walk(tree) if isinstance(n, ast.Call) and _call_name(n) in _COST_FUNCS
        )
    return total


class TestSeatKeywordIsEnforced:
    def test_scan_sees_the_known_call_sites(self) -> None:
        """스캔 0건은 실패 — 전수 가드가 공허하게 통과하는 것을 막는다(알려진 호출만 해도 ≥ 12)."""
        assert _total_cost_calls() >= 12

    def test_no_cost_call_omits_the_seat(self) -> None:
        offenders = _scan_package()
        assert not offenders, f"원가 함수 호출이 seat 키워드를 생략했다(OPS-116): {offenders}"

    # ── 검사기 자신의 변별력 — 주입 RED + 대조군 ──────────────────────────
    def test_checker_flags_an_omitted_seat(self) -> None:
        src = "def f(d, u):\n    return actual_cost_krw(d, u)\n"
        assert _seatless_calls(src) == [2]

    def test_checker_flags_attribute_style_call_and_all_three_functions(self) -> None:
        src = (
            "def f(d, u):\n"
            "    a = router.actual_cost_usd(d, u)\n"
            "    b = actual_cost_usd_or_none(d, u)\n"
            "    return a, b\n"
        )
        assert _seatless_calls(src) == [2, 3]

    def test_checker_flags_kwargs_spread_since_the_seat_is_not_guaranteed(self) -> None:
        src = "def f(d, u, **kw):\n    return actual_cost_krw(d, u, **kw)\n"
        assert _seatless_calls(src) == [2]

    def test_checker_passes_an_explicit_seat_including_none(self) -> None:
        src = (
            "def f(d, u):\n"
            "    a = actual_cost_krw(d, u, seat='openrouter')\n"
            "    b = actual_cost_krw(d, u, seat=None)\n"
            "    return a, b\n"
        )
        assert _seatless_calls(src) == []

    def test_restoring_the_omission_in_a_real_source_turns_the_scan_red(self) -> None:
        """실제 소스에서 `seat=seat`를 지우면(= 결함 복원) 같은 검사기가 RED — 주입이 적용됐음도 단언."""
        path = _PKG / "l3" / "pedagogy" / "analogy_generator.py"
        original = path.read_text(encoding="utf-8")
        assert _seatless_calls(original) == []
        mutated = original.replace(
            "actual_cost_krw(decision, usage, seat=seat)", "actual_cost_krw(decision, usage)"
        )
        assert mutated != original  # 주입이 실제로 적용됐다
        assert len(_seatless_calls(mutated)) == 1


# ──────────────────────────────────────────────────────────────────────
# ② 동작 — 대역(네트워크 0)
# ──────────────────────────────────────────────────────────────────────
class _SpyTrace:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def record(self, fields: dict[str, object]) -> None:
        self.events.append(dict(fields))


class _Provider:
    """`seat`를 주면 `cloud_seat` 표면을 노출하고 안 주면 표면 자체가 없다(`served_cloud_seat` 3상태)."""

    _NO_SURFACE: Any = object()

    def __init__(self, seat: Any = _NO_SURFACE) -> None:
        if seat is not _Provider._NO_SURFACE:
            self.cloud_seat = seat

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        *,
        images: Sequence[str] | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        json_schema: Mapping[str, object] | None = None,
        seed: int | None = None,
    ) -> GenerationResult:
        return GenerationResult("응답", usage=_USAGE)


def _decision(tier: CostTier) -> RoutingDecision:
    return RoutingDecision(cost_tier=tier, mode="sync", reason="t", est_latency_ms=3000)


def _local_decision() -> RoutingDecision:
    from whymath_backend.l3.models import LocalModelTier, ModelFamily

    return RoutingDecision(
        cost_tier=CostTier.LOCAL,
        local_family=ModelFamily.GENERAL,
        local_model=LocalModelTier.MID,
        mode="sync",
        reason="t",
        est_latency_ms=3000,
    )


def _cross_verify(provider: _Provider, spy: _SpyTrace) -> Any:
    v = CrossVerifier(provider, trace=spy)  # type: ignore[arg-type]
    return lambda decision, usage: v._record_trace(decision, usage)


def _analogy(provider: _Provider, spy: _SpyTrace) -> Any:
    g = AnalogyGenerator(provider, trace=spy)  # type: ignore[arg-type]
    return lambda decision, usage: g._record_trace(decision, usage)


def _explanation(provider: _Provider, spy: _SpyTrace) -> Any:
    g = ExplanationGenerator(provider, trace=spy)  # type: ignore[arg-type]
    return lambda decision, usage: g._record_trace(decision, usage)


def _multi_solution(provider: _Provider, spy: _SpyTrace) -> Any:
    return lambda decision, usage: ms_record_trace(spy, provider, decision, usage)  # type: ignore[arg-type]


# (이름, 기록 함수 조립기) — 좌석을 provider에서 읽는 4곳. 같은 계약이라 한 표로 돌린다.
_TRACE_SITES = [
    pytest.param(_cross_verify, id="cross_verify"),
    pytest.param(_analogy, id="analogy_generator"),
    pytest.param(_explanation, id="explanation_generator"),
    pytest.param(_multi_solution, id="multi_solution"),
]


@pytest.mark.parametrize("make", _TRACE_SITES)
class TestProviderSeatDrivesTheCost:
    def _run(
        self, make: Any, provider: _Provider, tier: CostTier = CostTier.CLOUD_MID
    ) -> tuple[dict[str, object], RoutingDecision]:
        spy = _SpyTrace()
        decision = _decision(tier) if tier is not CostTier.LOCAL else _local_decision()
        make(provider, spy)(decision, _USAGE)
        assert len(spy.events) == 1
        return spy.events[0], decision

    def test_openrouter_seat_uses_the_openrouter_table(self, make: Any) -> None:
        event, decision = self._run(make, _Provider(seat="openrouter"))
        want = actual_cost_krw(decision, _USAGE, seat="openrouter")
        other = actual_cost_krw(decision, _USAGE, seat="anthropic")
        assert want is not None and other is not None
        assert want != other  # 전제 — 좌석 간 단가가 실제로 다르다(같으면 오류를 못 잡는다)
        assert event["cost_krw"] == pytest.approx(want)
        assert event["cloud_seat"] == "openrouter"

    def test_anthropic_seat_uses_the_anthropic_table(self, make: Any) -> None:
        event, decision = self._run(make, _Provider(seat="anthropic"))
        assert event["cost_krw"] == pytest.approx(
            actual_cost_krw(decision, _USAGE, seat="anthropic")
        )
        assert event["cloud_seat"] == "anthropic"

    def test_unknown_seat_stays_unmeasured_instead_of_folding_to_anthropic(self, make: Any) -> None:
        event, decision = self._run(make, _Provider(seat=None))
        assert actual_cost_krw(decision, _USAGE, seat="anthropic") is not None  # 접으면 값이 생긴다
        assert event["cost_krw"] is None  # 미측정 — 0도 anthropic 단가도 아니다
        assert event["cloud_seat"] is None

    def test_provider_without_a_seat_surface_keeps_the_legacy_meaning(self, make: Any) -> None:
        """좌석 표면이 없는 provider(테스트 가짜·레거시)는 종전 의미(anthropic)를 보존한다."""
        event, decision = self._run(make, _Provider())
        assert event["cost_krw"] == pytest.approx(
            actual_cost_krw(decision, _USAGE, seat="anthropic")
        )
        assert event["cloud_seat"] == "anthropic"

    def test_local_is_free_and_has_no_seat(self, make: Any) -> None:
        event, _ = self._run(make, _Provider(seat="openrouter"), CostTier.LOCAL)
        assert event["cost_krw"] == 0.0
        assert event["cloud_seat"] is None


class TestQueueWorkerDeclaresTheSeatUnknown:
    """QUALITY 워커 — 불변식상 LOCAL(27b)이라 좌석과 무관하게 0원이고, 깨지면 '미측정'이다."""

    def _run(self, decision: RoutingDecision) -> dict[str, object]:
        spy = _SpyTrace()
        payload = {
            PAYLOAD_PROMPT: "p",
            PAYLOAD_SYSTEM: "s",
            PAYLOAD_DECISION: decision.model_dump(),
        }
        run_quality_generation_payload(payload, provider=_Provider(), trace=spy)  # type: ignore[arg-type]
        assert len(spy.events) == 1
        return spy.events[0]

    def test_local_decision_costs_zero(self) -> None:
        assert self._run(_local_decision())["cost_krw"] == 0.0

    def test_a_cloud_decision_is_not_priced_with_the_anthropic_default(self) -> None:
        decision = _decision(CostTier.CLOUD_MID)
        assert actual_cost_krw(decision, _USAGE, seat="anthropic") is not None
        assert self._run(decision)["cost_krw"] is None


class _SmokeCloud:
    """스모크용 클라우드 대역 — 좌석 표면(`seat`)을 주입한다(`AnthropicProvider.seat`와 같은 표면)."""

    def __init__(self, *, seat: Any) -> None:
        self.seat = seat
        self.configured = True

    async def generate(
        self, prompt: str, system: str, decision: RoutingDecision
    ) -> GenerationResult:
        return GenerationResult("2", usage=_USAGE)


class TestLivePreflightSmokeReadsTheSeat:
    def _smoke(self, seat: Any) -> lp.SmokeResult:
        return asyncio.run(lp._run_smoke(_SmokeCloud(seat=seat)))  # type: ignore[arg-type]

    def test_openrouter_cloud_is_priced_with_the_openrouter_table(self) -> None:
        result = self._smoke("openrouter")
        decision = lp._cloud_mid_decision()
        assert result.ran is True
        assert result.cost_krw == pytest.approx(
            actual_cost_krw(decision, _USAGE, seat="openrouter")
        )
        assert result.cost_krw != pytest.approx(actual_cost_krw(decision, _USAGE, seat="anthropic"))

    def test_default_anthropic_cloud_keeps_the_anthropic_table(self) -> None:
        result = self._smoke("anthropic")
        assert result.cost_krw == pytest.approx(
            actual_cost_krw(lp._cloud_mid_decision(), _USAGE, seat="anthropic")
        )

    def test_unknown_seat_is_unmeasured(self) -> None:
        assert self._smoke(None).cost_krw is None
