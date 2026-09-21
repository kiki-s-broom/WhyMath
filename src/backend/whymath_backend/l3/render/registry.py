"""전략 → 어댑터 레지스트리 — 단일 조회 지점(미구현 전략은 명확히 거부).

설계 정본: `docs/architecture/03c_content_strategy_cache.md` §2.2.

`CompositeProvider`의 티어 디스패치·`acceptance._CONCEPTUAL_VERIFIERS`의 dict 디스패치와 같은
house style이다. **조용한 폴백을 두지 않는다** — 등록되지 않은 전략을 요청하면 임의의 다른
어댑터로 대체하지 않고 `LookupError`를 던진다(CLAUDE.md "모르면 모른다고"·침묵 실패 금지).

폐쇄 enum `PedagogyStrategy`는 10종이지만 이 슬라이스(REND-01)는 5종만 구현한다. 나머지 5종
(RETRIEVAL·SPACING·INTERLEAVING·SELF_EXPLANATION·VISUALIZATION)은 *의도적 미등록*이며, 요청 시
"미구현"임이 오류로 드러난다 — 있는 척하는 빈 렌더보다 낫다. 상위(supply)는 이 오류를 잡아 생성
경로로 폴백하면 된다.
"""

from __future__ import annotations

from collections.abc import Callable

from whymath_backend.l3.render.adapter import PedagogyAdapter
from whymath_backend.l3.render.adapters import (
    AnalogyAdapter,
    DirectAdapter,
    ProblemBasedAdapter,
    SocraticAdapter,
    WorkedExampleAdapter,
)
from whymath_backend.schema.enums import PedagogyStrategy
from whymath_backend.schema.verification_capabilities import (
    AssessmentAnswerVerifier,
    ExpressionSeal,
)

# 어댑터 **팩토리** 표 — 인스턴스가 아니라 클래스를 담는다(EOS-89). 어댑터가 과목 능력 2종을
# 생성 시 주입받게 되면서 모듈 로드 시점에는 그 능력이 없기 때문이다. 능력은 Application이
# 부팅 시 app.state에 등록한 것이 상류를 타고 `get_adapter`까지 내려온다.
#
# 전략 1개 = 어댑터 1개(개념 무관). 개념 수가 늘어도 이 표는 자라지 않는다 — 조합폭발 방지의
# 구조적 증거다(거버넌스 테스트가 이 불변식을 동결한다).
_ADAPTER_FACTORIES: dict[PedagogyStrategy, Callable[..., PedagogyAdapter]] = {
    PedagogyStrategy.DIRECT: DirectAdapter,
    PedagogyStrategy.SOCRATIC: SocraticAdapter,
    PedagogyStrategy.WORKED_EXAMPLE: WorkedExampleAdapter,
    PedagogyStrategy.PROBLEM_BASED: ProblemBasedAdapter,
    PedagogyStrategy.ANALOGY: AnalogyAdapter,
}


def get_adapter(
    strategy: PedagogyStrategy,
    *,
    seal: ExpressionSeal,
    assessment_verifier: AssessmentAnswerVerifier,
) -> PedagogyAdapter:
    """전략에 대응하는 어댑터를 **과목 능력을 주입해** 만든다 — 미등록이면 `LookupError`.

    호출부(상위 supply)는 이 오류를 잡아 *생성 경로*로 폴백할 수 있다. 여기서 임의 어댑터로
    대체하면 학생이 요청과 다른 방식의 수업을 받게 되므로 하지 않는다.

    EOS-89: `seal`·`assessment_verifier`는 **필수**다. 기본값을 두면 이 모듈이 합성 루트를
    알아야 하고(pull 지점 부활), 없이 도는 것을 허용하면 미검증 렌더가 학생에게 나간다.
    어댑터는 상태가 없어 매 호출 생성이 저렴하다(필드 2개 대입).
    """
    factory = _ADAPTER_FACTORIES.get(strategy)
    if factory is None:
        available = ", ".join(sorted(s.value for s in _ADAPTER_FACTORIES))
        raise LookupError(
            f"전략 {strategy.value}의 렌더 어댑터가 등록되지 않았습니다(미구현). "
            f"현재 구현: {available}."
        )
    return factory(seal=seal, assessment_verifier=assessment_verifier)


def registered_strategies() -> frozenset[PedagogyStrategy]:
    """구현된 전략 집합 — 상위가 렌더 가능 여부를 미리 판단할 때 쓴다."""
    return frozenset(_ADAPTER_FACTORIES)


__all__ = ["get_adapter", "registered_strategies"]
