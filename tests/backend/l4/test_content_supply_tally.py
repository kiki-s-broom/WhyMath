"""공급 집계 어댑터별 분해 + 프로덕션 배선 — `SupplyTally`의 소비처가 실재하는지.

이 파일이 갚는 부채는 **소비처 0**이다. `SupplyTally`는 존재했으나 아무도 기록하지 않아
"generate로 집계되나 학생은 아무것도 못 본" 왜곡이 프로덕션에서 관측 불가였다. 저장소에 존재하는
것과 돌아가는 것은 다르므로, 여기서는 ① 분해가 실제로 쌓이는지 ② `/study` 라우터가 정말로 그
집계에 기록하도록 배선돼 있는지를 소스 스캔으로 함께 동결한다.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from whymath_backend.api import study as study_api
from whymath_backend.composition import (
    default_assessment_answer_verifier,
    default_expression_seal,
)
from whymath_backend.l3.render.dsl import ConceptAssessment
from whymath_backend.l4.content_supply import (
    REASON_CANNOT_RENDER,
    SupplyTally,
    get_concept_dsl,
    get_process_tally,
    reset_process_tally,
    supply,
)
from whymath_backend.l4.pedagogy.runtime_selector import StudentSignals
from whymath_backend.schema.enums import PedagogyStrategy

# ── 테스트 대역(기존 test_content_supply.py와 같은 형태·독립 정의로 결합 회피) ──


@dataclass
class _FakeRow:
    """`ConceptContent` ORM 행 최소 대역."""

    code: str = "TALLY-1"
    name: str = "일차식"
    subject: str = "중학수학"
    unit: str | None = "문자와 식"
    metaphor: str | None = "저울의 균형을 맞추는 일과 같다."
    misconception: str | None = "차수를 혼동한다."
    formal_definition_internal: str | None = "미지수의 차수가 1인 식."
    accepted_expressions: str | None = "2x + 3"
    explanation: str | None = None
    standard_codes: list[str] = field(default_factory=list)
    atom_codes: list[str] = field(default_factory=list)
    flashcards: list[dict[str, object]] = field(default_factory=list)


class _FakeSession:
    async def get(self, _model: object, pk: str) -> _FakeRow | None:
        return _FakeRow(code=pk) if pk.startswith("TALLY") else None


class _FakeCache:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, _ttl_s: int) -> None:
        self.store[key] = value


# ── 분해 회계 ────────────────────────────────────────────────────


def test_record_accumulates_strategy_and_fallback_breakdown() -> None:
    """경로·전략·폴백 사유가 각각 쌓이고, 전략별 비율이 전체 비율과 *다르게* 나온다.

    전략별 분해의 존재 이유가 바로 이 차이다 — 전체 50%가 "한 전략은 100%, 다른 전략은 0%"를
    가릴 수 있다(실제 PROBLEM_BASED 전건 404가 그렇게 묻혔다).
    """
    tally = SupplyTally()
    tally.record("dsl_render", strategy="SOCRATIC")
    tally.record("generate", strategy="PROBLEM_BASED", fallback_reason=REASON_CANNOT_RENDER)

    assert tally.total == 2
    assert tally.dsl_render_rate == pytest.approx(0.5)
    assert tally.strategy_render_rate("SOCRATIC") == pytest.approx(1.0)
    assert tally.strategy_render_rate("PROBLEM_BASED") == pytest.approx(0.0)
    assert tally.by_fallback_reason == {REASON_CANNOT_RENDER: 1}


def test_unknown_strategy_rate_is_none_not_zero() -> None:
    """관측 없는 전략은 0%가 아니라 미상(None) — 모르면 모른다."""
    tally = SupplyTally()
    tally.record("dsl_render", strategy="DIRECT")
    assert tally.strategy_render_rate("ANALOGY") is None


def test_record_without_strategy_still_counts_path() -> None:
    """전략을 모르는 호출자(사전 점검·배치)도 경로 회계는 성립한다(하위호환)."""
    tally = SupplyTally()
    tally.record("dsl_render")
    assert tally.counts == {"dsl_render": 1}
    assert tally.by_strategy == {}


def test_to_json_exposes_adapter_breakdown() -> None:
    """리포트 표면에 어댑터별 분해가 실제로 들어간다(리포트 배선의 계약)."""
    tally = SupplyTally()
    tally.record("dsl_render", strategy="DIRECT")
    payload = tally.to_json()
    assert payload["by_strategy"] == {"DIRECT": {"dsl_render": 1}}
    assert payload["render_rate_by_strategy"] == {"DIRECT": 1.0}
    assert payload["by_fallback_reason"] == {}


def test_process_tally_is_a_singleton_and_resettable() -> None:
    """프로세스 집계는 같은 인스턴스이며 reset으로 격리 가능하다."""
    reset_process_tally()
    try:
        assert get_process_tally() is get_process_tally()
        get_process_tally().record("dsl_render", strategy="DIRECT")
        assert get_process_tally().total == 1
    finally:
        reset_process_tally()
    assert get_process_tally().total == 0


# ── supply 경로에서의 기록 ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_supply_records_strategy_into_tally() -> None:
    """`supply()`가 전략 축까지 집계에 넘긴다 — 경로만 세면 어댑터 분해가 비어버린다."""
    tally = SupplyTally()
    result = await supply(
        code="TALLY-1",
        signals=StudentSignals(),
        session=_FakeSession(),  # type: ignore[arg-type]
        cache=_FakeCache(),  # type: ignore[arg-type]
        tally=tally,
        seal=default_expression_seal(),
        assessment_verifier=default_assessment_answer_verifier(),
    )
    assert result.strategy in set(PedagogyStrategy)
    assert tally.by_strategy.get(result.strategy.value)


@pytest.mark.asyncio
async def test_get_concept_dsl_injects_assessment_from_bank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DSL 조회 경로가 평가 재료를 주입한다 — 캐시 미스·히트 **양쪽 모두**.

    히트 경로까지 확인하는 이유: 뱅크가 나중에 채워졌는데 TTL이 남은 낡은 캐시 항목이 계속 빈
    평가 재료를 돌려주면 그 개념만 조용히 렌더 불가로 남는다.
    """
    injected = ConceptAssessment(conditions=("x = 2",), answer_map={"x": "2"})
    monkeypatch.setattr(
        "whymath_backend.l4.content_supply.attach_assessment",
        lambda dsl: (
            dsl if dsl.assessment is not None else dsl.model_copy(update={"assessment": injected})
        ),
    )
    cache = _FakeCache()
    first = await get_concept_dsl("TALLY-1", session=_FakeSession(), cache=cache)  # type: ignore[arg-type]
    assert first is not None and first.assessment == injected

    # 캐시에 평가 재료 없이 저장된 낡은 항목을 흉내낸다.
    cache.store["dsl:concept:TALLY-1"] = first.model_copy(
        update={"assessment": None}
    ).model_dump_json()
    second = await get_concept_dsl("TALLY-1", session=_FakeSession(), cache=cache)  # type: ignore[arg-type]
    assert second is not None and second.assessment == injected


# ── 프로덕션 배선(소스 스캔 — "존재함"과 "돌아감"은 다르다) ──────────


def test_study_router_feeds_the_process_tally() -> None:
    """`/study` 라우터가 `supply(..., tally=...)`로 프로세스 집계에 기록하도록 배선돼 있다.

    호출 인자를 AST로 확인한다 — 문서·주석이 아니라 *코드*가 배선의 근거여야 한다. 이 검사가
    없으면 인자 하나가 빠져도 아무 테스트도 빨개지지 않고 집계만 조용히 0이 된다.
    """
    source = Path(study_api.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    supply_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "supply"
    ]
    assert supply_calls, "study 라우터에 supply() 호출이 없다"
    for call in supply_calls:
        assert any(kw.arg == "tally" for kw in call.keywords), "supply 호출에 tally= 인자가 없다"
    assert "get_process_tally()" in source
