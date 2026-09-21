"""L3 렌더링 엔진 — 교수법-중립 콘텐츠(ConceptDSL) → 전략별 학생 화면.

설계 정본: `docs/architecture/03c_content_strategy_cache.md`(콘텐츠 전략·2층 캐시)·
`04d_adaptive_pedagogy_engine.md`(전략을 *고르는* 쪽은 L4).

한 줄 요약: **콘텐츠는 하나, 방식은 N개.** 저장 자산은 (개념 × 교수법)의 곱이 아니라 (중립 DSL +
개념-무관 어댑터 N개)의 합이다 — 조합은 렌더 시점에 계산한다(조합폭발 방지).

    dsl = from_concept_content(row)          # 교수법-중립 투영
    # 전략 선택은 L4(PED-02) 소관 · 과목 능력 2종은 상류(app.state 등록분)에서 내려온다(EOS-89)
    adapter = get_adapter(PedagogyStrategy.SOCRATIC, seal=seal, assessment_verifier=verifier)
    unit = adapter.render(dsl, RenderContext())
    if unit.ok: ...                          # 검증 통과분만 학생 노출

경계: 렌더는 **순수 렌더**다(LLM=0·결정론). *어느* 전략을 쓸지 고르는 책임은 L4 Runtime Pedagogy
Selector에 있고, 캐시·생성 폴백 배선은 상위 supply(CACHE-01)에 있다.
"""

from whymath_backend.l3.render.adapter import (
    NullAdapter,
    PedagogyAdapter,
    RenderContext,
    RenderedUnit,
    RenderSegment,
    SegmentKind,
)
from whymath_backend.l3.render.adapters import (
    AnalogyAdapter,
    DirectAdapter,
    ProblemBasedAdapter,
    SocraticAdapter,
    WorkedExampleAdapter,
)
from whymath_backend.l3.render.assessment_bank import (
    attach_assessment,
    get_assessment_bank,
    reset_assessment_bank_cache,
    uncovered_concept_codes,
)
from whymath_backend.l3.render.dsl import (
    PEDAGOGY_METHOD_BLOCKLIST,
    ConceptAssessment,
    ConceptDSL,
    from_concept_content,
)
from whymath_backend.l3.render.registry import get_adapter, registered_strategies

__all__ = [
    "PEDAGOGY_METHOD_BLOCKLIST",
    "AnalogyAdapter",
    "ConceptAssessment",
    "ConceptDSL",
    "DirectAdapter",
    "NullAdapter",
    "PedagogyAdapter",
    "ProblemBasedAdapter",
    "RenderContext",
    "RenderSegment",
    "RenderedUnit",
    "SegmentKind",
    "SocraticAdapter",
    "WorkedExampleAdapter",
    "attach_assessment",
    "from_concept_content",
    "get_adapter",
    "get_assessment_bank",
    "registered_strategies",
    "reset_assessment_bank_cache",
    "uncovered_concept_codes",
]
