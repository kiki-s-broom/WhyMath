"""골든 클라우드 관할 게이트 — 옛 `CompositeProvider._guard_cloud_jurisdiction`과 같은 판정.

GOLD-20(S20A 후속 위험 제거).

왜 필요한가: 옛 앱은 클라우드 제공자에 보내기 직전 `CompositeProvider`가 "이 공급사 관할(US·CN·
국적 미상)로 이 등급의 자료를 보내도 되는가"를 묻는다(ARCH-49). 골든 튜터는 S4부터 팩토리가 만든
제공자를 **직접** 불러 이 판정을 건너뛰었다. 허용 공급사 목록이 기본값(미국 법인)이면 결과는
같지만, 목록에 국적 미상·중국계 공급사가 들어가는 순간 골든만 막히지 않는다. 이 모듈이 그 구멍을
막는다.

판정 자체는 새로 만들지 않는다 — 옛 `l3.provider_jurisdiction.jurisdiction_judgment`를 그대로
부른다(이미 골든이 import하는 모듈이라 전이 예산 비용 0). 옮긴 것은 그 함수를 부르는 감싸개
세 줄(관할 읽기 · 코퍼스 opt-in 읽기 · 차단 시 오류)뿐이다. 같은 판정을 내는지는
`tests/golden/characterization/test_s20a_llm_gate.py`가 옛 메서드와 나란히 돌려 고정한다 — 옛
판정 규칙이 바뀌면 그 테스트가 RED가 된다.

옛 것과 다르게 한 것 하나: 옛 기본값(관할을 선언하지 않은 제공자 = US)은 **쓰지 않는다**. 옛 코드는
그 넓은 기본값을 프로덕션 제공자 전수 검사(`tests/infra/test_provider_jurisdiction_declaration.py`)
로 보완하는데, 그 검사는 `l3/providers/`만 본다 — 골든 복사본은 그 밖이다. 그래서 골든은 선언이
없으면 **차단**한다(fail-closed). 골든 제공자(`golden.llm.openrouter.OpenRouterProvider`)는 관할을
허용 공급사 목록에서 계산해 선언하므로 정상 경로는 영향이 없다.
"""

from __future__ import annotations

from whymath_backend.l3.models import CostTier, RoutingDecision
from whymath_backend.l3.provider_jurisdiction import Jurisdiction, jurisdiction_judgment
from whymath_backend.l3.router import _as_cost_tier


class JurisdictionBlockedError(RuntimeError):
    """관할 게이트가 클라우드 호출을 막았다 — 호출은 일어나지 않았다."""


def provider_jurisdiction(provider: object) -> Jurisdiction:
    """제공자가 선언한 관할. 선언이 없거나 Jurisdiction이 아니면 오류(기본값으로 반올림 안 함)."""
    declared = getattr(provider, "jurisdiction", None)
    if not isinstance(declared, Jurisdiction):
        raise JurisdictionBlockedError(
            f"클라우드 제공자의 관할 선언이 없다(받은 {type(declared).__name__}) — "
            "골든은 선언 없는 제공자로 보내지 않는다(fail-closed)."
        )
    return declared


def guard_cloud_jurisdiction(provider: object, decision: RoutingDecision) -> None:
    """클라우드 결정이면 보내기 직전 관할을 판정한다 — 통과면 조용히 반환, 막히면 오류.

    LOCAL 결정은 검사하지 않는다(옛 `CompositeProvider`와 같다 — 반출이 없다).
    판정 입력은 라우터가 결정에 실어 준 선언 등급(`decision.data_licenses`)이다.
    """
    if _as_cost_tier(decision.cost_tier) is CostTier.LOCAL:
        return
    jurisdiction = provider_jurisdiction(provider)
    judgment = jurisdiction_judgment(
        jurisdiction,
        decision.data_licenses,
        allow_internal_corpus=bool(getattr(provider, "allow_internal_corpus", False)),
    )
    if judgment.permitted:
        return
    blocking = ", ".join(license_type.value for license_type in judgment.blocking_licenses)
    detail = f" 차단 등급: {blocking}." if blocking else ""
    raise JurisdictionBlockedError(
        f"관할 게이트가 클라우드 위임을 차단했습니다 "
        f"(관할={jurisdiction.value}, 사유={judgment.reason}).{detail}"
    )
