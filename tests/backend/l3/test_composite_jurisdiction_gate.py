"""CompositeProvider 관할 게이트 — 디스패치 직전 판정 (ARCH-49 ⑤·acceptance ②).

이 파일이 지키는 것 둘:

1. **회귀**: 학생 저작이 실린 요청은 클라우드로 나가지 않는다. 그 보장은 원래
   `permission_map._USER_GENERATED.export=False` → `guard_data_export` → LOCAL 강등이며,
   관할 축을 얹었다고 그것이 깨지지 않았음을 **라우터 경유 전 경로**로 확인한다
   (사용자 요청 ⑤: "기존 permission_map의 보장을 깨지 않는지 회귀로 확인").
2. **신규**: 좁히는 관할(CN·국적 미확인)은 선언 없는 결정과 허용 밖 등급을 차단하고,
   좁히지 않는 관할(US·현행 Anthropic)은 **아무것도 바꾸지 않는다**.

픽스처 원칙: 각 절이 없으면 통과하는 입력을 둔다 —
  - 관할 판정 절 없음 → `test_cn_provider_blocks_corpus_without_opt_in`이 통과해 버린다
  - 미선언 차단 절 없음 → `test_cn_provider_blocks_undeclared_decision`이 통과해 버린다
  - LOCAL 예외 절 없음 → `test_local_dispatch_is_never_gated`가 실패한다
  - 타입 검사 절 없음 → `test_bogus_jurisdiction_declaration_is_rejected`가 통과해 버린다
"""

from __future__ import annotations

from typing import Any

import pytest

from whymath_backend.l3.models import (
    CostTier,
    GenerationResult,
    LocalModelTier,
    ModelFamily,
    RoutingDecision,
    RoutingRequest,
)
from whymath_backend.l3.provider_jurisdiction import Jurisdiction
from whymath_backend.l3.providers.composite import (
    DEFAULT_CLOUD_JURISDICTION,
    CompositeProvider,
)
from whymath_backend.l3.router import Router
from whymath_backend.schema.enums import LicenseType


class _FakeProvider:
    """관할을 선언할 수 있는 가짜 제공자 — 위임 도달 여부를 호출 기록으로 판정한다."""

    def __init__(
        self,
        *,
        jurisdiction: Any = None,
        allow_internal_corpus: bool | None = None,
    ) -> None:
        self.calls: list[RoutingDecision] = []
        if jurisdiction is not None:
            self.jurisdiction = jurisdiction
        if allow_internal_corpus is not None:
            self.allow_internal_corpus = allow_internal_corpus

    async def generate(
        self, prompt: str, system: str, decision: RoutingDecision, **kwargs: Any
    ) -> GenerationResult:
        self.calls.append(decision)
        return GenerationResult("out")


def _cloud_bound_request(**overrides: Any) -> RoutingRequest:
    """비즈니스 축이 **클라우드를 원하는** 요청 — 법적·관할 게이트의 변별력을 위한 전제.

    `business_cost_tier` 규칙 3(killer/prove → CLOUD_HIGH)을 밟고 구독·예산 가드도
    통과하게 둔다. 이 전제가 없으면 요청이 어차피 LOCAL이라 "게이트가 막았다"와
    "애초에 클라우드가 아니었다"를 구분할 수 없다(변별력 없는 픽스처 금지).
    """
    kwargs: dict[str, Any] = {
        "task_type": "prove",
        "difficulty": "killer",
        "requires_reasoning": True,
        "student_subscription": "premium",
        "budget_krw": 1000.0,
    }
    kwargs.update(overrides)
    return RoutingRequest(**kwargs)


def _cloud_decision(**overrides: Any) -> RoutingDecision:
    kwargs: dict[str, Any] = {
        "cost_tier": CostTier.CLOUD_MID,
        "local_family": None,
        "local_model": None,
        "mode": "sync",
        "reason": "cloud escalation",
        "est_latency_ms": 2000,
        "est_cost_krw": 1.0,
    }
    kwargs.update(overrides)
    return RoutingDecision(**kwargs)


def _local_decision(**overrides: Any) -> RoutingDecision:
    kwargs: dict[str, Any] = {
        "cost_tier": CostTier.LOCAL,
        "local_family": ModelFamily.MATH,
        "local_model": LocalModelTier.FAST,
        "mode": "sync",
        "reason": "local",
        "est_latency_ms": 1010,
        "est_cost_krw": 0.0,
    }
    kwargs.update(overrides)
    return RoutingDecision(**kwargs)


# ──────────────────────────────────────────────────────────────────────────
# 1. 회귀 — 학생 저작은 애초에 클라우드 결정이 되지 않는다
# ──────────────────────────────────────────────────────────────────────────
class TestStudentAuthoredNeverReachesCloud:
    """1차 게이트(권리 모델)의 보장이 관할 축 도입 후에도 그대로인가."""

    @pytest.mark.parametrize(
        "licenses",
        [
            (LicenseType.USER_GENERATED,),
            # 학생 저작이 자체 코퍼스와 *섞인* 경우 — 보수적 병합이 이겨야 한다.
            (LicenseType.WHYMATH_GENERATED, LicenseType.USER_GENERATED),
        ],
    )
    def test_router_demotes_student_authored_requests_to_local(
        self, licenses: tuple[LicenseType, ...]
    ) -> None:
        """구독·난이도가 클라우드를 원해도 법적 게이트가 LOCAL로 내린다(무변경 확인)."""
        req = _cloud_bound_request(data_licenses=licenses)
        decision = Router().route(req)
        assert decision.cost_tier == CostTier.LOCAL
        assert decision.data_export_blocked is True

    async def test_a_student_authored_decision_cannot_be_dispatched_to_cn(self) -> None:
        """1차 게이트를 손으로 우회해 CN으로 밀어도 관할 게이트가 두 번째로 막는다.

        이 경로는 정상 라우팅에서는 생기지 않는다(위 테스트가 그것을 보장한다). 그래도
        검증하는 이유는 **이중 방어**다 — 한 겹이 깨져도 다른 겹이 성립해야 한다.
        """
        cloud = _FakeProvider(jurisdiction=Jurisdiction.CN)
        composite = CompositeProvider(local=_FakeProvider(), cloud=cloud)
        smuggled = _cloud_decision(data_licenses=(LicenseType.USER_GENERATED,))
        with pytest.raises(RuntimeError, match="관할 게이트"):
            await composite.generate("p", "s", smuggled)
        assert not cloud.calls

    async def test_opt_in_does_not_open_student_authored(self) -> None:
        """코퍼스 opt-in을 켜도 학생 저작은 열리지 않는다 — 교집합 상한 때문."""
        cloud = _FakeProvider(jurisdiction=Jurisdiction.CN, allow_internal_corpus=True)
        composite = CompositeProvider(local=_FakeProvider(), cloud=cloud)
        with pytest.raises(RuntimeError, match="관할 게이트"):
            await composite.generate(
                "p", "s", _cloud_decision(data_licenses=(LicenseType.USER_GENERATED,))
            )
        assert not cloud.calls


# ──────────────────────────────────────────────────────────────────────────
# 2. 신규 — 좁히는 관할에서만 게이트가 발동한다
# ──────────────────────────────────────────────────────────────────────────
class TestCnDispatchGate:
    async def test_cn_provider_accepts_synthetic_probe(self) -> None:
        """CN 기본 허용은 합성 프로브 — 여기까지는 통과해야 측정(acceptance ①)이 가능하다."""
        cloud = _FakeProvider(jurisdiction=Jurisdiction.CN)
        composite = CompositeProvider(local=_FakeProvider(), cloud=cloud)
        await composite.generate(
            "p", "s", _cloud_decision(data_licenses=(LicenseType.WHYMATH_GENERATED,))
        )
        assert len(cloud.calls) == 1

    async def test_cn_provider_blocks_corpus_without_opt_in(self) -> None:
        """자체 저작 코퍼스는 opt-in 없이는 중국 서버로 나가지 않는다."""
        cloud = _FakeProvider(jurisdiction=Jurisdiction.CN)
        composite = CompositeProvider(local=_FakeProvider(), cloud=cloud)
        with pytest.raises(RuntimeError, match="INTERNAL_OWNED"):
            await composite.generate(
                "p", "s", _cloud_decision(data_licenses=(LicenseType.INTERNAL_OWNED,))
            )
        assert not cloud.calls

    async def test_cn_provider_allows_corpus_with_opt_in(self) -> None:
        cloud = _FakeProvider(jurisdiction=Jurisdiction.CN, allow_internal_corpus=True)
        composite = CompositeProvider(local=_FakeProvider(), cloud=cloud)
        await composite.generate(
            "p", "s", _cloud_decision(data_licenses=(LicenseType.INTERNAL_OWNED,))
        )
        assert len(cloud.calls) == 1

    async def test_cn_provider_blocks_undeclared_decision(self) -> None:
        """등급 선언이 없는 결정(손조립·레거시)은 CN으로 나가지 않는다 — fail-closed."""
        cloud = _FakeProvider(jurisdiction=Jurisdiction.CN)
        composite = CompositeProvider(local=_FakeProvider(), cloud=cloud)
        with pytest.raises(RuntimeError, match="JURISDICTION_UNDECLARED"):
            await composite.generate("p", "s", _cloud_decision())
        assert not cloud.calls

    async def test_unknown_jurisdiction_blocks_even_synthetic_probe(self) -> None:
        """국적 미확인 공급사는 합성 프로브조차 못 받는다 — 두 번째 방어층의 기본값."""
        cloud = _FakeProvider(jurisdiction=Jurisdiction.UNKNOWN)
        composite = CompositeProvider(local=_FakeProvider(), cloud=cloud)
        with pytest.raises(RuntimeError, match="관할 게이트"):
            await composite.generate(
                "p", "s", _cloud_decision(data_licenses=(LicenseType.WHYMATH_GENERATED,))
            )
        assert not cloud.calls


class TestExistingCloudPathUnchanged:
    """US·미선언 제공자에 대해서는 이 축이 아무것도 바꾸지 않는다."""

    @pytest.mark.parametrize("jurisdiction", [Jurisdiction.US, None])
    async def test_undeclared_decision_still_dispatches(
        self, jurisdiction: Jurisdiction | None
    ) -> None:
        """등급 선언이 없어도 US(및 선언 없는 가짜)는 종전처럼 위임된다."""
        cloud = _FakeProvider(jurisdiction=jurisdiction)
        composite = CompositeProvider(local=_FakeProvider(), cloud=cloud)
        await composite.generate("p", "s", _cloud_decision())
        assert len(cloud.calls) == 1

    async def test_us_accepts_every_export_permitted_grade(self) -> None:
        """US는 1차 게이트가 허용한 등급을 그대로 받는다(추가 좁힘 없음)."""
        cloud = _FakeProvider(jurisdiction=Jurisdiction.US)
        composite = CompositeProvider(local=_FakeProvider(), cloud=cloud)
        await composite.generate(
            "p",
            "s",
            _cloud_decision(data_licenses=(LicenseType.INTERNAL_OWNED, LicenseType.KOGL_1)),
        )
        assert len(cloud.calls) == 1

    def test_default_cloud_jurisdiction_is_the_historical_seat(self) -> None:
        assert DEFAULT_CLOUD_JURISDICTION is Jurisdiction.US

    @pytest.mark.parametrize(
        "licenses",
        [(), (LicenseType.USER_GENERATED,), (LicenseType.WHYMATH_GENERATED,)],
    )
    async def test_local_dispatch_is_never_gated(self, licenses: tuple[LicenseType, ...]) -> None:
        """로컬 위임에는 관할 게이트가 서지 않는다 — 반출이 아니기 때문."""
        local = _FakeProvider(jurisdiction=Jurisdiction.DOMESTIC)
        composite = CompositeProvider(local=local, cloud=_FakeProvider())
        await composite.generate("p", "s", _local_decision(data_licenses=licenses))
        assert len(local.calls) == 1


class TestDeclarationReading:
    """선언을 읽는 규칙 자체의 변별력."""

    def test_missing_declaration_falls_back_to_default(self) -> None:
        assert CompositeProvider.cloud_jurisdiction(_FakeProvider()) is DEFAULT_CLOUD_JURISDICTION

    def test_declared_jurisdiction_is_honoured(self) -> None:
        assert (
            CompositeProvider.cloud_jurisdiction(_FakeProvider(jurisdiction=Jurisdiction.CN))
            is Jurisdiction.CN
        )

    def test_bogus_jurisdiction_declaration_is_rejected(self) -> None:
        """문자열·오타를 기본값으로 반올림하지 않는다 — 조용한 위장 금지.

        `"cn"`은 `Jurisdiction.CN`의 *값*이라 눈으로는 맞아 보이지만 enum이 아니다.
        반올림 절이 있으면 이 선언이 US로 읽혀 CN 정책이 통째로 사라진다.
        """
        with pytest.raises(TypeError):
            CompositeProvider.cloud_jurisdiction(_FakeProvider(jurisdiction="cn"))

    def test_missing_opt_in_declaration_is_false(self) -> None:
        """opt-in 기본은 좁은 쪽 — 선언하지 않은 제공자가 권한을 물려받지 않는다."""
        assert CompositeProvider.cloud_allows_internal_corpus(_FakeProvider()) is False

    def test_declared_opt_in_is_honoured(self) -> None:
        assert (
            CompositeProvider.cloud_allows_internal_corpus(
                _FakeProvider(allow_internal_corpus=True)
            )
            is True
        )


class TestRouterDecisionCarriesGrades:
    """라우터 경유 결정은 선언을 승계한다 — 그래야 게이트가 판정할 재료가 생긴다."""

    @pytest.mark.parametrize(
        "licenses",
        [(LicenseType.WHYMATH_GENERATED,), (LicenseType.INTERNAL_OWNED, LicenseType.KOGL_1)],
    )
    def test_route_propagates_declared_licenses(self, licenses: tuple[LicenseType, ...]) -> None:
        decision = Router().route(_cloud_bound_request(data_licenses=licenses))
        assert tuple(decision.data_licenses) == licenses

    def test_hand_assembled_decision_declares_nothing_by_default(self) -> None:
        """기본값이 빈 튜플이라는 사실 자체가 fail-closed의 근거다."""
        assert _cloud_decision().data_licenses == ()

    async def test_routed_probe_reaches_cn_provider_end_to_end(self) -> None:
        """라우터 → 디스패처 관통 — 합성 프로브가 CN 좌석까지 도달한다(측정 경로 실증)."""
        decision = Router().route(
            _cloud_bound_request(data_licenses=(LicenseType.WHYMATH_GENERATED,))
        )
        assert decision.cost_tier != CostTier.LOCAL, "이 요청은 클라우드로 올라가야 한다"
        cloud = _FakeProvider(jurisdiction=Jurisdiction.CN)
        composite = CompositeProvider(local=_FakeProvider(), cloud=cloud)
        await composite.generate("p", "s", decision)
        assert len(cloud.calls) == 1
