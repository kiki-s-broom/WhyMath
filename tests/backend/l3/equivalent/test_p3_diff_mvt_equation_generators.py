"""Phase 3 미적분Ⅰ '미분' — [12미적Ⅰ-02-06] 평균값 정리 · [12미적Ⅰ-02-09] 방정식·부등식 활용 생성기 테스트.

P3-03(hermetic·LLM 0). 두 생성기는 아직 등록부(`harness.p3_calculus1_diff_batch.GENERATORS`)에 없을 수
있다 — 이 테스트는 등록 여부와 무관하게 두 클래스를 직접 import해 검사한다(등록부 순회 테스트
`test_p3_diff_skeleton_generators.py`와 같은 불변식을 이 두 개념에 적용하되, 개념형 검산 재료
`answer_kind`·`answer_aggregate`·`answer_selection`을 인식한다).

검증 축
-------
① 슬롯 6종 × 선언 건수 · 개념당 고유 문면 골격 ≥ 30 · 틀 ≥ 30 · 슬롯마다 ≥ 5틀.
② 전 문항이 수용 게이트를 통과하고 *틀린 답을 주입하면 전 문항이 거부*된다(변별력).
③ **정답의 독립 재계산** — 검산 재료(조건)만 읽어 SymPy·수치 근 계산으로 답을 다시 구한다(생성기 코드 미사용).
④ 02-06: c값 문항은 방정식 1개 + 열린구간 경계 4개(P3-19 fixture 형식) — 구간 밖 근 오답이 *구간 조건 때문에*
   거부된다(조건을 떼면 통과 — 보호의 실재). `corpus_reverify`가 구간 밖 근 변형을 exit 1로 거부한다.
⑤ 02-09: 매개변수(k) 범위형 없음 · 근과 계수의 관계·근 고르기 틀의 삭제 동결(2차 감사 bad_tag) ·
   값형은 전부 도함수로 구하는 **최솟값**(부등식을 보이는 핵심 단계 — 3차 감사 처분으로 '등호가 성립하는
   x'형은 정수 중근이 인수분해 우회로를 열어 삭제했다 · 우회로 판정기 T09-*) · 개수형이 슬롯을 독점하지
   않음.
⑥ 오개념 연결은 오개념 유발 슬롯에만, 명세의 핵심 M-id로(kebab 좌석이 없어 M-id 그대로 — 좌석이 생기면
   이 테스트가 신호를 낸다).
⑦ 문제유형 정직성: 개수형(`real_root_count`) ⇔ `ptype.count-solutions`.
"""

from __future__ import annotations

import json
import re
import typing
from collections.abc import Sequence
from pathlib import Path

import pytest
import sympy

from whymath_backend.harness import corpus_reverify
from whymath_backend.harness import generator_space_overlap_audit as overlap_audit
from whymath_backend.harness.p3_calculus1_diff_batch import run_p3_calculus1_diff_batch
from whymath_backend.l1.standards.phase3_coverage import load_corpus
from whymath_backend.l1.standards.phase3_scope import load_reference_index, load_scope_spec
from whymath_backend.l3.equivalent import p3_diff_skeleton_base as base
from whymath_backend.l3.equivalent.acceptance import evaluate_equivalent_candidate
from whymath_backend.l3.equivalent.generator import CandidateProblem
from whymath_backend.l3.equivalent.orchestrator import run_equivalent_generation
from whymath_backend.l3.equivalent.p3_diff_equation_application_skeleton_generator import (
    P3DiffEquationApplicationGenerator,
)
from whymath_backend.l3.equivalent.p3_diff_mean_value_theorem_skeleton_generator import (
    KindedDiffItem,
    P3DiffMeanValueTheoremGenerator,
    with_item_kinds,
)
from whymath_backend.l3.equivalent.p3_diff_polynomial_rules_skeleton_generator import (
    P3DiffPolynomialRulesGenerator,
)
from whymath_backend.l3.equivalent.p3_diff_power_derivative_skeleton_generator import (
    P3DiffPowerDerivativeGenerator,
)
from whymath_backend.l3.equivalent.p3_diff_skeleton_base import (
    SLOT_IDS,
    DiffItem,
    P3DiffSlotGenerator,
    skeleton_of,
)
from whymath_backend.l3.verify_answer import verify_answer
from whymath_backend.schema.enums import AnswerFormat

# PB-13: 생성기·배치 회귀는 corpus-authoring 잡이 돌린다(backend 잡 35분 상한 — 비활성화가 아니다).
pytestmark = pytest.mark.corpus_authoring

_MVT = P3DiffMeanValueTheoremGenerator
_EQ = P3DiffEquationApplicationGenerator
_GENS: tuple[type[P3DiffSlotGenerator], ...] = (_MVT, _EQ)
_ALL = pytest.mark.parametrize("generator_cls", _GENS, ids=lambda g: g.standard_code)

_MIN_SKELETONS = 30
_MIN_FRAMES = 30
# 4차 감사(2026-10-07) 표기 교정: 학생 대면 '√'·'≤'·'≥'는 *허용*한다 — 승인 은행 4종이 쓰는 표기이고
# 표기 커버리지 게이트(`l3/notation_coverage`) 베이스라인에 이미 있는 글리프라 신규 누락이 아니다.
# 대신 그 자리를 차지하던 코드 표기('<='·'>='·'sqrt('·'*')를 금지한다(`_CODE_NOTATION`).
_GLYPHS = ("²", "³", "Σ", "α", "β", "′", "≠")
_CODE_NOTATION = re.compile(r"<=|>=|sqrt\(|\*")
_X = sympy.Symbol("x")
_C = sympy.Symbol("c")


def _items(generator_cls: type[P3DiffSlotGenerator]) -> list[DiffItem]:
    return [item for slot in SLOT_IDS for item in generator_cls.items(slot)]


def _kind(item: DiffItem) -> str | None:
    return item.answer_kind if isinstance(item, KindedDiffItem) else None


def _agg(item: DiffItem) -> str | None:
    return item.answer_aggregate if isinstance(item, KindedDiffItem) else None


def _sel(item: DiffItem) -> str | None:
    return item.answer_selection if isinstance(item, KindedDiffItem) else None


def _conds(item: DiffItem) -> tuple[str, ...]:
    return (item.conditions,) if isinstance(item.conditions, str) else tuple(item.conditions)


def _candidates(generator_cls: type[P3DiffSlotGenerator], slot: str) -> list[CandidateProblem]:
    spec = generator_cls.spec_for(slot)
    generator = generator_cls(slot=slot)
    out: list[CandidateProblem] = []
    while (candidate := generator.generate(spec)) is not None:
        out.append(candidate)
    return out


# ──────────────────────────────────────────────────────────────────────────
# ① 규모·고유성
# ──────────────────────────────────────────────────────────────────────────
@_ALL
def test_every_slot_is_filled_with_the_declared_count(
    generator_cls: type[P3DiffSlotGenerator],
) -> None:
    for slot in SLOT_IDS:
        items = generator_cls.items(slot)
        assert len(items) == generator_cls.slot_count, (slot, len(items))
        assert {item.slot for item in items} == {slot}
        assert len({item.frame_id for item in items}) >= 5, f"{slot}: 틀이 5종 미만"
    assert set(generator_cls.slot_difficulty) == set(SLOT_IDS)


@_ALL
def test_distinct_skeletons_and_frames_reach_the_floor(
    generator_cls: type[P3DiffSlotGenerator],
) -> None:
    items = _items(generator_cls)
    assert len({skeleton_of(i.question_text) for i in items}) >= _MIN_SKELETONS
    assert len({i.frame_id for i in items}) >= _MIN_FRAMES
    for slot in SLOT_IDS:
        assert len({skeleton_of(i.question_text) for i in generator_cls.items(slot)}) >= 5, slot


@_ALL
def test_questions_and_conditions_are_unique_within_the_concept(
    generator_cls: type[P3DiffSlotGenerator],
) -> None:
    items = _items(generator_cls)
    texts = [i.question_text for i in items]
    conds = ["&&".join(_conds(i)) for i in items]
    assert len(set(texts)) == len(texts)
    assert len(set(conds)) == len(conds)


def test_the_two_generators_do_not_overlap_each_other_or_the_first_two_concepts() -> None:
    """형제 생성기 사이 발문·조건식 공간이 겹치지 않는다(QUAL-08 정신 — 같은 실체를 두 번 내지 않는다)."""
    spaces: dict[str, set[str]] = {}
    conds: dict[str, set[str]] = {}
    for generator_cls in (
        _MVT,
        _EQ,
        P3DiffPowerDerivativeGenerator,
        P3DiffPolynomialRulesGenerator,
    ):
        items = _items(generator_cls)
        spaces[generator_cls.__name__] = {
            overlap_audit.normalize_question_text(i.question_text) for i in items
        }
        conds[generator_cls.__name__] = {"&&".join(_conds(i)) for i in items}
    names = list(spaces)
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            assert not spaces[left] & spaces[right], (left, right)
            assert not conds[left] & conds[right], (left, right)


# ──────────────────────────────────────────────────────────────────────────
# ② 게이트 통과 · 오답 거부
# ──────────────────────────────────────────────────────────────────────────
@_ALL
def test_every_item_passes_the_acceptance_gate(generator_cls: type[P3DiffSlotGenerator]) -> None:
    for slot in SLOT_IDS:
        spec = generator_cls.spec_for(slot)
        generator = generator_cls(slot=slot)
        for _ in range(len(generator_cls.items(slot))):
            outcome = run_equivalent_generation(spec, generator, signature_index=None)
            assert outcome.status == "accepted", (slot, outcome.status, outcome.reasons)
        assert generator.generate(spec) is None  # 소진


def _wrong_answer(candidate: CandidateProblem) -> tuple[str, dict[str, str]]:
    """검산 재료에 대한 *틀린 답* — 개념형은 주장 답을, 값형은 치환맵의 답을 틀리게 한다."""
    if candidate.answer_kind is not None or candidate.answer_aggregate is not None:
        return f"({candidate.problem.answer}) + 1", dict(candidate.answer_map)
    broken = dict(candidate.answer_map)
    key = sorted(broken)[-1]
    broken[key] = f"({broken[key]}) + 1"
    return candidate.problem.answer, broken


@_ALL
def test_gate_rejects_a_wrong_answer_for_every_item(
    generator_cls: type[P3DiffSlotGenerator],
) -> None:
    """**변별력 실측(RED)** — 정답을 틀리게 만들면 전 문항이 정확성 게이트에서 거부된다."""
    rejected = 0
    total = 0
    for slot in SLOT_IDS:
        spec = generator_cls.spec_for(slot)
        for candidate in _candidates(generator_cls, slot):
            total += 1
            claimed, answer_map = _wrong_answer(candidate)
            problem = candidate.problem.model_copy(update={"answer": claimed})
            verdict = evaluate_equivalent_candidate(
                spec,
                problem,
                provenance=candidate.provenance,
                conditions=candidate.conditions,
                answer_map=answer_map,
                answer_selection=candidate.answer_selection,
                answer_aggregate=candidate.answer_aggregate,
                answer_kind=candidate.answer_kind,
            )
            if not verdict.accepted and any("정확성" in r for r in verdict.reasons):
                rejected += 1
    assert total > 0
    assert rejected == total, f"{total - rejected}건이 틀린 답을 통과시켰다"


@_ALL
def test_with_item_kinds_carries_the_gate_materials_into_the_candidate(
    generator_cls: type[P3DiffSlotGenerator],
) -> None:
    """kind·aggregate·selection이 후보 번들에 실린다(싣지 않으면 개념형 문항이 값형으로 오검산된다)."""
    seen = {"kind": 0, "aggregate": 0, "selection": 0}
    for slot in SLOT_IDS:
        for item, candidate in zip(
            generator_cls.items(slot), _candidates(generator_cls, slot), strict=True
        ):
            assert candidate.answer_kind == _kind(item)
            assert candidate.answer_aggregate == _agg(item)
            assert candidate.answer_selection == _sel(item)
            seen["kind"] += candidate.answer_kind is not None
            seen["aggregate"] += candidate.answer_aggregate is not None
            seen["selection"] += candidate.answer_selection is not None
    # 2차 감사(2026-10) 처분: 근과 계수의 관계(합·곱)·근 고르기(가장 큰/작은 근) 틀은 미분 활용 없이
    # 공통수학1 계산만으로 풀려 02-06·02-09 태그가 거짓이었다(bad_tag) — 두 생성기에서 삭제했다.
    # 그래서 생성기 문항이 aggregate·selection 경로를 더는 밟지 않는다(0건 동결). 경로 자체의 운반
    # 계약은 아래 합성 문항 테스트(`test_with_item_kinds_carries_aggregate_and_selection`)가 지킨다.
    assert seen["aggregate"] == 0 and seen["selection"] == 0, seen
    assert seen["kind"] >= (15 if generator_cls is _EQ else 5), seen
    # 확장 필드가 없는 평범한 DiffItem은 후보를 그대로 돌려준다
    sample = _candidates(generator_cls, "representative")[0]
    plain = DiffItem(
        slot="representative",
        frame_id="plain",
        question_text="q",
        answer_text="1",
        explanation="e",
        conditions="x = y",
        answer_map=(("y", "1"),),
        problem_type_code="ptype.evaluate-expression",
        answer_format=AnswerFormat.자연수,
    )
    assert with_item_kinds(sample, plain) is sample


def test_with_item_kinds_carries_aggregate_and_selection() -> None:
    """운반 계약 — 생성기가 더는 aggregate·selection 문항을 내지 않아도 경로 자체는 살아 있어야 한다.

    합성 문항 3종(합·선택·개수)을 직접 만들어 후보 번들에 각 필드가 실리는지 본다. 이 테스트가 없으면
    02-06·02-09 틀 삭제 뒤 `with_item_kinds`의 aggregate·selection 분기는 아무도 밟지 않는다.
    """
    sample = _candidates(_EQ, "representative")[0]
    common = {
        "slot": "representative",
        "frame_id": "synthetic",
        "question_text": "q",
        "answer_text": "1",
        "explanation": "e",
        "conditions": "x**2 - 1 = 0",
        "answer_map": (),
        "problem_type_code": "ptype.solve-for-unknown",
        "answer_format": AnswerFormat.자연수,
    }
    agg = with_item_kinds(sample, KindedDiffItem(**common, answer_aggregate="sum"))
    assert agg.answer_aggregate == "sum" and agg.answer_selection is None
    sel = with_item_kinds(sample, KindedDiffItem(**common, answer_selection="largest"))
    assert sel.answer_selection == "largest" and sel.answer_aggregate is None
    kind = with_item_kinds(sample, KindedDiffItem(**common, answer_kind="real_root_count"))
    assert kind.answer_kind == "real_root_count"


# ──────────────────────────────────────────────────────────────────────────
# ③ 정답의 독립 재계산 — 검산 재료(조건)만 읽는다
# ──────────────────────────────────────────────────────────────────────────
_REL = re.compile(r"\s*(<=|>=|!=|<|>|=)\s*")


def _parse_cond(text: str) -> tuple[sympy.Expr, str]:
    """조건 문자열 → (좌변 - 우변, 관계)."""
    match = _REL.search(text)
    assert match is not None, text
    lhs, rhs = text[: match.start()], text[match.end() :]
    return sympy.sympify(lhs) - sympy.sympify(rhs), match.group(1)


def _symbol_of(exprs: Sequence[sympy.Expr]) -> sympy.Symbol:
    symbols: set[sympy.Symbol] = set()
    for expr in exprs:
        symbols |= set(expr.free_symbols)
    assert len(symbols) == 1, symbols  # 섀도 채점 계약 — 미지수는 정확히 하나
    return next(iter(symbols))


def _numeric_roots(expr: sympy.Expr, symbol: sympy.Symbol) -> list[complex]:
    """다항식의 모든 근(중복도 포함) — 정확 근 계산이 아니라 수치 근(독립 경로).

    중근이 있는 다항식은 mpmath `polyroots`가 수렴하지 못할 때가 있다(실측: 2(x - 1)^2(x + 1)에서
    NoConvergence). 그래서 제곱 없는 분해(`sqf_list`)로 인수마다 수치 근을 구해 중복도만큼 반복한다 —
    여전히 생성기 코드를 쓰지 않는 수치 경로이고, 중복도를 보존하므로 합·곱 재계산도 그대로다.
    """
    _, factors = sympy.Poly(expr, symbol).sqf_list()
    out: list[complex] = []
    for factor, multiplicity in factors:
        roots = [complex(r) for r in factor.nroots(n=40, maxsteps=500)]
        out.extend(roots * multiplicity)
    return out


def _real_distinct(roots: Sequence[complex]) -> list[float]:
    reals = sorted(r.real for r in roots if abs(r.imag) < 1e-7)
    out: list[float] = []
    for value in reals:
        if not out or abs(value - out[-1]) > 1e-5:
            out.append(value)
    return out


def _solution_points(item: DiffItem) -> list[float]:
    """조건이 허용하는 실수 해의 집합(유한 점 집합)을 *조건 문자열만으로* 구한다."""
    parsed = [_parse_cond(c) for c in _conds(item)]
    symbol = _symbol_of([expr for expr, _ in parsed])
    first_expr, first_op = parsed[0]
    if first_op == "=":
        numerator, denominator = sympy.together(sympy.simplify(first_expr)).as_numer_denom()
        candidates = _real_distinct(_numeric_roots(numerator, symbol))
        # 분모가 0이 되는 가짜 근 제거
        candidates = [v for v in candidates if abs(float(denominator.subs(symbol, v))) > 1e-9]
    else:
        relation = {"<=": sympy.Le, ">=": sympy.Ge, "<": sympy.Lt, ">": sympy.Gt}[first_op](
            first_expr, 0
        )
        region = sympy.solveset(relation, symbol, domain=sympy.S.Reals)
        # 정의역 제한(둘째 조건)과 교집합을 취한 뒤 한 점 모임이어야 한다
        for expr, op in parsed[1:]:
            bound = {"<=": sympy.Le, ">=": sympy.Ge, "<": sympy.Lt, ">": sympy.Gt}[op](expr, 0)
            region = region.intersect(sympy.solveset(bound, symbol, domain=sympy.S.Reals))
        assert isinstance(region, sympy.FiniteSet), f"해집합이 한 점 모임이 아니다: {region}"
        return [float(v) for v in region]
    keep: list[float] = []
    for value in candidates:
        ok = True
        for expr, op in parsed[1:]:
            number = float(expr.subs(symbol, value))
            ok &= {
                "=": abs(number) < 1e-9,
                "!=": abs(number) > 1e-9,
                "<=": number <= 1e-9,
                ">=": number >= -1e-9,
                "<": number < -1e-9,
                ">": number > 1e-9,
            }[op]
        if ok:
            keep.append(value)
    return keep


_OPT = "ptype.optimize-extremum"
_DOMAIN = re.compile(r"^(?P<v>[xt]) (?P<op>>=|>) (?P<n>-?\d+)$")


def _is_min_item(item: DiffItem) -> bool:
    """02-09 최솟값형 — 검산 재료가 (임계점 f'(v) = 0, 최솟값 y = f(v)[, 범위 v >= 0])인 문항."""
    return item.problem_type_code == _OPT and not isinstance(item.conditions, str)


def _min_parts(item: DiffItem) -> tuple[sympy.Symbol, sympy.Expr, tuple[str, int] | None]:
    """최솟값형의 (변수, 함수식, 범위) — 조건 문자열만 읽는다(생성기 코드 미사용)."""
    conds = _conds(item)
    assert conds[0].startswith("Derivative(") and conds[0].endswith(".doit() = 0"), conds
    assert conds[1].startswith("y = "), conds
    expr = sympy.sympify(conds[1].removeprefix("y = "))
    (var,) = expr.free_symbols
    assert isinstance(var, sympy.Symbol) and str(var) in ("x", "t"), conds
    # 임계점 조건이 *같은* 함수의 도함수인지 — 다른 함수를 미분해 두면 x 고정이 무의미하다.
    assert sympy.simplify(_parse_cond(conds[0])[0] - sympy.diff(expr, var)) == 0, conds
    domain: tuple[str, int] | None = None
    if len(conds) == 3:
        match = _DOMAIN.match(conds[2])
        assert match is not None and match["v"] == str(var), conds
        domain = (match["op"], int(match["n"]))
    else:
        assert len(conds) == 2, conds
    return var, expr, domain


def _global_minimum(
    expr: sympy.Expr, var: sympy.Symbol, domain: tuple[str, int] | None
) -> tuple[float, float]:
    """범위에서의 최솟값과 그 점을 **수치 근**으로 다시 구한다(생성기의 정확 근·분기와 독립 경로).

    후보 = 범위 안의 f'의 실근(수치) + 닫힌 경계. 전 실수에서는 최고차가 짝수 차·양수 계수, 반직선
    범위에서는 양수 계수여야 최솟값이 존재한다(아니면 실패). 열린 경계(`>`)는 경계값이 최솟값보다
    엄격히 커야 한다(경계에 다가가며 더 작아지면 최솟값이 없다).
    """
    poly = sympy.Poly(expr, var)
    lead = poly.LC()
    assert lead > 0, expr
    if domain is None:
        assert poly.degree() % 2 == 0, expr
    crit = [
        r.real
        for r in map(complex, sympy.Poly(sympy.diff(expr, var), var).nroots(n=30))
        if abs(r.imag) < 1e-9
    ]
    cands = [c for c in crit if domain is None or c > domain[1] - 1e-9]
    if domain is not None and domain[0] == ">=":
        cands.append(float(domain[1]))
    values = sorted((float(expr.subs(var, c)), c) for c in cands)
    assert values, expr
    best, at = values[0]
    if domain is not None and domain[0] == ">":
        assert float(expr.subs(var, domain[1])) > best + 1e-9, expr
    # 최솟점이 하나뿐(답의 x가 유일) — 같은 최솟값을 두 점에서 가지면 answer_map의 x가 모호하다.
    assert all(v > best + 1e-9 for v, c in values[1:] if abs(c - at) > 1e-6), (expr, values)
    return best, at


def _answer_value(item: DiffItem) -> float:
    return (
        float(sympy.Rational(item.answer_text))
        if "/" in item.answer_text
        else float(sympy.sympify(item.answer_text))
    )


@_ALL
def test_answers_match_an_independent_recomputation_from_the_conditions(
    generator_cls: type[P3DiffSlotGenerator],
) -> None:
    """정답을 생성기 코드가 아니라 *검산 재료*에서 다시 구해 대조한다.

    · 개수형: 다항식의 서로 다른 실근 수(수치 근).
    · 합·곱: 복소근 포함 모든 근(중복도 포함)의 합·곱.
    · 값형: 조건이 허용하는 해집합이 한 점이면 그 점, 근 선택이면 최대·최소.
    """
    checked = {"count": 0, "aggregate": 0, "value": 0}
    for item in _items(generator_cls):
        answer = _answer_value(item)
        if _kind(item) is not None:
            (cond,) = _conds(item)
            expr, op = _parse_cond(cond)
            assert op == "="
            symbol = _symbol_of([expr])
            assert len(_real_distinct(_numeric_roots(expr, symbol))) == answer, item.question_text
            checked["count"] += 1
        elif _agg(item) is not None:
            (cond,) = _conds(item)
            expr, _ = _parse_cond(cond)
            roots = _numeric_roots(expr, _symbol_of([expr]))
            if _agg(item) == "sum":
                actual = sum(roots)
            else:
                actual = complex(1)
                for r in roots:
                    actual *= r
            assert abs(actual - answer) < 1e-6, (item.question_text, actual, answer)
            checked["aggregate"] += 1
        elif _is_min_item(item):
            var, expr, domain = _min_parts(item)
            best, at = _global_minimum(expr, var, domain)
            assert abs(best - answer) < 1e-6, (item.question_text, best, answer)
            amap = dict(item.answer_map)
            assert set(amap) == {str(var), "y"} and amap["y"] == item.answer_text, item.answer_map
            assert abs(float(sympy.Rational(amap[str(var)])) - at) < 1e-6, (item.question_text, at)
            checked["value"] += 1
        else:
            points = _solution_points(item)
            if _sel(item) == "largest":
                assert abs(max(points) - answer) < 1e-6, item.question_text
            elif _sel(item) == "smallest":
                assert abs(min(points) - answer) < 1e-6, item.question_text
            else:
                # 선택 지정이 없으면 해가 *정확히 하나*여야 정답이 유일하다
                assert len(points) == 1, (item.question_text, points)
                assert abs(points[0] - answer) < 1e-6, item.question_text
            checked["value"] += 1
    # 합·곱(aggregate) 틀은 2차 감사 bad_tag 처분으로 두 생성기에서 삭제했다 — 0건을 동결한다.
    assert checked["value"] >= 20 and checked["count"] >= 3 and checked["aggregate"] == 0, checked


@_ALL
def test_no_function_valued_answers_and_single_unknown_contract(
    generator_cls: type[P3DiffSlotGenerator],
) -> None:
    """함수식 답 금지 · 미지수는 정확히 하나(섀도 채점 계약 — `test_multi_symbol_population_is_frozen`).

    값형 문항은 자유기호가 answer_map의 유일한 키이고, 개념형(개수·집계) 문항은 answer_map이 비어도
    자유기호가 정확히 하나다.

    예외 하나(02-09 최솟값형): 검산 재료가 (임계점 f'(v) = 0, 최솟값 y = f(v)[, 범위])라 자유기호가
    {v, y} 둘이다. 이것은 [12미적Ⅰ-02-08] 규칙 C3이 허용한 형태(극값의 값 — x를 answer_map에 실어
    고정, 프로브 C1 '가능')와 같은 구조로, 최솟점 v는 작성자가 answer_map에 박고 학생은 y(최솟값)만
    답한다. 목록 조건이라 섀도 채점 로더가 읽지 않으므로(문자열 조건만 읽음) 섀도 모집단 동결에는
    들어가지 않는다. 그 형태를 *정확히* 고정한다 — 키가 {v, y}이고 답이 y이며, 첫 조건이 같은 함수의
    임계점 조건이다(`_min_parts`가 대조). 그 밖의 문항은 아래 단일 미지수 계약을 그대로 받는다.
    """
    for item in _items(generator_cls):
        assert item.answer_format != AnswerFormat.식, item.question_text
        assert "x^" not in item.answer_text
        assert not re.search(r"[a-z]", item.answer_text.replace("sqrt", ""))
        if generator_cls is _EQ and _is_min_item(item):
            var, _, _ = _min_parts(item)
            symbols = set().union(*(_parse_cond(c)[0].free_symbols for c in _conds(item)))
            assert {str(sym) for sym in symbols} == {str(var), "y"}, item.conditions
            assert {k for k, _ in item.answer_map} == {str(var), "y"}, item.answer_map
            assert dict(item.answer_map)["y"] == item.answer_text, item.question_text
            continue
        parsed = [_parse_cond(c)[0] for c in _conds(item)]
        symbol = _symbol_of(parsed)
        if _kind(item) is None and _agg(item) is None:
            assert {k for k, _ in item.answer_map} == {str(symbol)}, item.question_text
        else:
            assert item.answer_map == ()
        if not isinstance(item.conditions, str):
            assert len(item.conditions) >= 2
            assert any(_REL.search(c) and re.search(r"[<>!]=?", c) for c in item.conditions[1:])


# ──────────────────────────────────────────────────────────────────────────
# ④ 02-06 — 구간 소속 판정(P3-19)
# ──────────────────────────────────────────────────────────────────────────
_BOUND = re.compile(r"^c (>=|<=|!=) (-?\d+)$")


def _c_find_items() -> list[DiffItem]:
    return [
        i
        for i in _items(_MVT)
        if isinstance(i.conditions, tuple)
        and i.conditions[1:2]
        and i.conditions[1].startswith("c >=")
    ]


def test_mvt_c_items_carry_the_open_interval_in_the_p3_19_format() -> None:
    items = _c_find_items()
    assert len(items) >= 30, len(items)
    for item in items:
        eq, lower, upper, no_lower, no_upper = item.conditions  # type: ignore[misc]
        a = int(_BOUND.match(lower).group(2))  # type: ignore[union-attr]
        b = int(_BOUND.match(upper).group(2))  # type: ignore[union-attr]
        assert lower == f"c >= {a}" and upper == f"c <= {b}"
        assert no_lower == f"c != {a}" and no_upper == f"c != {b}"
        assert a < b
        if "Derivative(" in eq:  # 미분 평가는 조건당 1회·맨몸(Tier1 제약)
            assert ".doit().subs(" in eq and eq.count("Derivative") == 1
        else:  # 문면의 방정식을 c에 대한 다항식으로 그대로 쓴 진단 문항
            assert eq.endswith(" = 0"), eq
        answer = _answer_value(item)
        assert a < answer < b, item.question_text  # 답은 열린구간 안


def test_mvt_answer_is_the_unique_root_inside_the_open_interval() -> None:
    """정답 하나가 유일하다 — 방정식의 근 중 열린구간 안에 있는 것이 정확히 답 1개."""
    outside_seen = 0
    for item in _c_find_items():
        eq, lower, upper, *_ = item.conditions  # type: ignore[misc]
        a = int(_BOUND.match(lower).group(2))  # type: ignore[union-attr]
        b = int(_BOUND.match(upper).group(2))  # type: ignore[union-attr]
        expr, _ = _parse_cond(eq)
        roots = _real_distinct(_numeric_roots(sympy.expand(expr), _C))
        inside = [r for r in roots if a < r < b]
        assert len(inside) == 1, (item.question_text, roots)
        assert abs(inside[0] - _answer_value(item)) < 1e-6
        outside_seen += len(roots) - len(inside)
    assert outside_seen >= 10, "방정식의 근이 둘이고 하나만 구간 안에 있는 문항이 너무 적다"


def test_mvt_outside_root_is_rejected_only_because_of_the_interval_condition() -> None:
    """구간 밖 근 오답은 구간 조건 때문에 거부된다 — 조건을 떼면 같은 오답이 통과한다(보호의 실재)."""
    rejected_with = 0
    passed_without = 0
    for item in _c_find_items():
        eq, lower, upper, *_ = item.conditions  # type: ignore[misc]
        a = int(_BOUND.match(lower).group(2))  # type: ignore[union-attr]
        b = int(_BOUND.match(upper).group(2))  # type: ignore[union-attr]
        expr, _ = _parse_cond(eq)
        roots = [r for r in sympy.solve(sympy.expand(expr), _C) if r.is_real and not (a < r < b)]
        for root in roots:
            wrong = {"c": str(root)}
            assert verify_answer(item.conditions, wrong).state == "fail"
            rejected_with += 1
            assert verify_answer(eq, wrong).state == "pass"
            passed_without += 1
    assert rejected_with >= 10 and rejected_with == passed_without


def test_corpus_reverify_exits_1_for_an_outside_root_variant(tmp_path: Path) -> None:
    """실제 코퍼스 재검증 CLI가 구간 밖 근 변형을 exit 1로 거부한다(P3-19 보호가 문항에 작동)."""
    bank = tmp_path / "mvt.jsonl"
    run_p3_calculus1_diff_batch(generators=(_MVT,), out_path=bank)
    rows = [json.loads(line) for line in bank.read_text(encoding="utf-8").splitlines() if line]
    assert corpus_reverify.main([str(bank)]) == 0  # 대조군: 원본 은행은 통과
    tampered: list[str] = []
    for row in rows:
        conds = row["verify"]["conditions"]
        if not (isinstance(conds, list) and conds[1:2] and conds[1].startswith("c >=")):
            continue
        a, b = int(conds[1].split(">=")[1]), int(conds[2].split("<=")[1])
        expr, _ = _parse_cond(conds[0])
        outside = [r for r in sympy.solve(sympy.expand(expr), _C) if r.is_real and not a < r < b]
        if outside:
            row["answer"] = str(outside[0])
            row["verify"]["answer_map"] = {"c": str(outside[0])}
            tampered.append(json.dumps(row, ensure_ascii=False))
    assert len(tampered) >= 10
    bad = tmp_path / "mvt_outside.jsonl"
    bad.write_text("\n".join(tampered) + "\n", encoding="utf-8")
    assert corpus_reverify.main([str(bad)]) == 1


# ──────────────────────────────────────────────────────────────────────────
# ⑤ 02-09 — 수치형만 · 문면 지침
# ──────────────────────────────────────────────────────────────────────────
def test_equation_concept_has_no_parametric_range_questions() -> None:
    """P3-20 §6 — 매개변수(k) 범위형은 검증 경로가 없어 만들지 않는다.

    자유기호는 x(또는 시간 t)뿐이고 문면에 '범위'를 묻는 표현이 없다. 최솟값형의 y는 매개변수가 아니라
    *답 자체*(최솟값)를 담는 기호라 그 형태에서만 허용한다(`y = f(x)` 조건 하나에만 나타난다).
    """
    for item in _items(_EQ):
        allowed = {"x", "t", "y"} if _is_min_item(item) else {"x", "t"}
        for cond in _conds(item):
            expr, _ = _parse_cond(cond)
            assert {str(s) for s in expr.free_symbols} <= allowed, item.question_text
            if "y" in {str(s) for s in expr.free_symbols}:
                assert cond.startswith("y = "), (item.question_text, cond)
        assert "범위" not in item.question_text
        assert not re.search(r"\bk\b", item.question_text.replace("y = k", "")), item.question_text


_PREREQUISITE_ONLY = re.compile(
    r"근의 (합|곱)|교점의 x좌표의 합|중근은 중복하여 센다|실근 중 가장 (큰|작은)|가장 작은 값|"
    r"x좌표가 가장 큰|오직 하나이다|이차부등식|이차방정식|f'\(x\) = 0을 만족시키는 두 실수|"
    r"f'\(x\) = 0의 (두 실근|서로 다른)|던진"
)


def test_equation_concept_has_no_prerequisite_only_forms() -> None:
    """2차 감사(2026-10) bad_tag 처분의 동결 — 02-09 행위가 없는 틀이 되살아나지 않는다.

    삭제한 틀: 근과 계수의 관계(세·네 근의 합·곱·교점 x좌표의 합)·근 고르기(가장 큰/작은 실근·양의
    실근·정의역 안 유일한 해)·이차부등식/이차방정식·f'(x) = 0의 근 계산(개수·합·작은 근)·'던진
    물체의 높이'(삼차식이 물리 모델과 모순). 미분 활용 없이 선수 계산만으로 풀려 태그가 거짓이었다.
    """
    items = _items(_EQ)
    assert not [i.question_text for i in items if _PREREQUISITE_ONLY.search(i.question_text)]
    assert not [i.question_text for i in items if _agg(i) is not None or _sel(i) is not None]


def test_equation_concept_value_items_find_the_minimum_with_the_derivative() -> None:
    """값형(최솟값)은 해설이 도함수 식을 세우고 f'(x) = 0의 근으로 최솟값에 닿는다 — 결론만 적지 않는다.

    3차 감사 처분 전에는 '등호가 성립하는 x'(최솟값 0인 점)를 물었으나 그 점이 정수 중근이라 인수분해만으로
    풀렸다(T09-repeated-root). 지금 값형은 양수 최솟값을 묻고, 해설은 도함수 식(f'(x) = …·h'(t) = …)과
    방정식 f'(x) = 0(= 0)을 반드시 보인다. 개수형은 인수분해(인수·중근·허근 인수) 또는 도함수(극값
    비교) 중 하나를 반드시 보인다(결론만 적은 해설 금지 — 2차 감사 bad_explanation).
    """
    values = counts = 0
    for item in _items(_EQ):
        if _kind(item) is None:
            assert _is_min_item(item), item.question_text
            assert re.search(r"[fh]'\([xt]\) = ", item.explanation), item.explanation
            assert "최솟값" in item.explanation and "= 0" in item.explanation, item.explanation
            values += 1
        else:
            factored = re.search(r"\)\(|\)\^\d|\d\([xt] [-+]|[xt]\([xt] [-+]", item.explanation)
            derivative = re.search(r"'\(|극댓값|극솟값", item.explanation)
            assert factored or derivative, item.explanation
            counts += 1
    assert values >= 30 and counts >= 20, (values, counts)


def test_equation_concept_count_forms_do_not_monopolise_a_slot() -> None:
    """P3-20 §3 — 실근 개수형을 한 슬롯에 몰아 쓰면 문면 골격이 겹친다. 슬롯별로 형태를 분산한다.

    오개념 유발 슬롯은 객관식이라 M0677(f(x) = k 근의 개수 관점)을 개수형으로만 물을 수 있어 예외이고,
    그 슬롯도 문면 틀이 다섯 가지로 다르다. 나머지 슬롯은 개수형 틀이 둘 이하이고 최솟값형(부등식을
    보이는 핵심 단계) 틀이 셋 이상 섞인다(합·선택형은 2차 감사, 등호점형은 3차 감사 처분으로 삭제).
    """
    for slot in SLOT_IDS:
        items = _EQ.items(slot)
        count_frames = {i.frame_id for i in items if _kind(i) is not None}
        other_frames = {i.frame_id for i in items if _kind(i) is None}
        if slot == "misconception_trigger":
            assert len(count_frames) >= 5
            continue
        assert len(count_frames) <= 2, (slot, count_frames)
        assert len(other_frames) >= 3, (slot, other_frames)


# ──────────────────────────────────────────────────────────────────────────
# ⑥ 오개념 연결 · 객관식
# ──────────────────────────────────────────────────────────────────────────
_MIS = {_MVT: "M0674", _EQ: "M0677"}


@_ALL
def test_misconception_links_are_exactly_the_mc_slot_and_are_core_ids(
    generator_cls: type[P3DiffSlotGenerator],
) -> None:
    spec = load_scope_spec()
    core = {
        m.mis_id for m in spec.core_misconceptions if m.concept_code == generator_cls.standard_code
    }
    assert core == {_MIS[generator_cls]}  # 명세가 이 개념에 귀속한 핵심 오개념(M-id)
    for slot in SLOT_IDS:
        linked = generator_cls.target_misconception_ids(slot)
        if slot == "misconception_trigger":
            assert linked == frozenset(core)
            for candidate in _candidates(generator_cls, slot):
                assert candidate.problem.distractor_map
                assert {e.misconception_id for e in candidate.problem.distractor_map} == core
        else:
            assert linked == frozenset()


def test_kebab_seat_absence_is_a_tripwire() -> None:
    """02-06·02-09의 핵심 M-id에는 L4 kebab 좌석이 없다 — 그래서 M-id를 distractor_map에 그대로 쓴다.

    좌석이 생기면(안 A·B — MISC-40 판정 문서) 이 테스트가 red가 되어, 생성기를 kebab 연결로 옮기라는
    신호를 낸다(참조 무결성 검증자 `validate_distractor_map`이 M-id를 위반으로 읽기 때문).
    """
    from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID

    assert "M0674" not in CATALOG_BY_ID and "M0677" not in CATALOG_BY_ID


@_ALL
def test_multiple_choice_invariants(generator_cls: type[P3DiffSlotGenerator]) -> None:
    mc_seen = 0
    for slot in SLOT_IDS:
        for item in generator_cls.items(slot):
            if item.choices is None:
                assert not item.distractors
                assert slot != "misconception_trigger"
                continue
            mc_seen += 1
            assert len(item.choices) == 4 and len(set(item.choices)) == 4
            assert item.answer_text in item.choices
            answer_index = item.choices.index(item.answer_text)
            for index, _mid in item.distractors:
                assert index != answer_index, "정답 선지에 오개념이 귀속됐다"
                assert 0 <= index < 4
            assert len({i for i, _ in item.distractors}) == len(item.distractors)
    assert mc_seen >= generator_cls.slot_count


def test_mvt_rolle_confusion_choice_is_the_root_of_f_prime_equals_zero() -> None:
    """02-06 오개념 선지는 롤의 정리와 혼동한 값(f'(x) = 0의 근)이다 — 실제로 그 값인지 독립 확인."""
    checked = 0
    for item in _MVT.items("misconception_trigger"):
        eq, *_ = item.conditions  # type: ignore[misc]
        expr, _ = _parse_cond(eq)
        # 방정식 f'(c) = m 의 좌변에서 f'를 복원: lhs = Derivative(...)... → expr + m이 f'(c)
        lhs_text = eq.split(" = ")[0]
        f_prime = sympy.sympify(lhs_text)
        zero_roots = {float(r) for r in sympy.solve(f_prime, _C) if r.is_real}
        for index, _mid in item.distractors:
            assert item.choices is not None
            value = _answer_text_value(item.choices[index])
            assert any(abs(value - z) < 1e-9 for z in zero_roots), (item.question_text, value)
            checked += 1
    assert checked >= 12


def _answer_text_value(text: str) -> float:
    return float(sympy.Rational(text)) if "/" in text else float(sympy.sympify(text))


# ──────────────────────────────────────────────────────────────────────────
# ⑦ 문제유형 정직성 · 위생
# ──────────────────────────────────────────────────────────────────────────
@_ALL
def test_only_required_problem_types_and_no_review_status(
    generator_cls: type[P3DiffSlotGenerator],
) -> None:
    allowed = set(load_scope_spec().problem_types)
    for slot in SLOT_IDS:
        for candidate in _candidates(generator_cls, slot):
            problem = candidate.problem
            assert set(problem.problem_type_codes) <= allowed
            assert len(problem.problem_type_codes) == 1
            assert problem.review_status is None  # 승인은 감사 표본 경로의 몫
            assert problem.is_published is False
            assert problem.tags == [f"{base.SLOT_TAG_PREFIX}{slot}"]
            assert problem.achievement_standard_codes == [generator_cls.standard_code]
            assert [t.concept_src_id for t in candidate.concept_tags] == [
                generator_cls.concept_src_id
            ]


@_ALL
def test_problem_type_codes_are_honest_count_form_iff_count_solutions(
    generator_cls: type[P3DiffSlotGenerator],
) -> None:
    """개수형(`real_root_count`) ⇔ `ptype.count-solutions` — 스킬 연결을 위해 유형을 거짓으로 달지 않는다."""
    for item in _items(generator_cls):
        is_count = _kind(item) == "real_root_count"
        assert (item.problem_type_code == "ptype.count-solutions") == is_count, item.question_text
        if item.problem_type_code == "ptype.evaluate-expression":
            # 값 계산 문항은 풀어서 미지수를 구하는 것이 아니다 — 개념형이 아니다
            assert _kind(item) is None and _agg(item) is None


@_ALL
def test_skill_link_measurement_by_the_coverage_instrument(
    generator_cls: type[P3DiffSlotGenerator],
) -> None:
    """계측기(`phase3_coverage`)로 개념 스킬과 겹치는 유형을 확인한다 — 겹침을 *측정*하고 동결한다.

    02-06(deductive-reasoning·graph-reading)은 `count-solutions`(graph-reading)만, 02-09(case-analysis·
    word-problem-modeling)는 `count-solutions`(case-analysis)만 겹친다. 이 개념들의 c값·미지수 문항
    (`solve-for-unknown`)은 겹치지 않는데 거짓 유형으로 맞추지 않았다.
    """
    spec = load_scope_spec()
    index = load_reference_index(spec)
    corpus = load_corpus(spec)
    concept = next(c for c in spec.concepts if c.code == generator_cls.standard_code)
    atoms = [a for a in index.crosswalk[concept.concept_id].atom_codes if a in index.atoms]
    skills = {s for a in atoms for s in index.atoms[a].behavior_skills if s in spec.skills}
    used = {i.problem_type_code for i in _items(generator_cls)}
    linked = {t for t in used if skills & set(corpus.type_skills.get(t, ()))}
    assert linked == {"ptype.count-solutions"}, (linked, skills)
    n_linked = sum(1 for i in _items(generator_cls) if i.problem_type_code in linked)
    assert n_linked >= 5, "스킬 연결 문항이 너무 적다"


@_ALL
def test_no_new_unicode_glyphs_or_latex_markup(generator_cls: type[P3DiffSlotGenerator]) -> None:
    for item in _items(generator_cls):
        for field in (
            item.question_text,
            item.explanation,
            item.answer_text,
            *(item.choices or ()),
        ):
            assert not any(g in field for g in _GLYPHS), field
            assert not _CODE_NOTATION.search(field), field
            assert "$" not in field and "\\" not in field, field
        assert item.answer_format in set(AnswerFormat)


@_ALL
def test_items_are_deterministic_across_cache_rebuilds(
    generator_cls: type[P3DiffSlotGenerator],
) -> None:
    before = {slot: generator_cls.items(slot) for slot in SLOT_IDS}
    for slot in SLOT_IDS:
        base._ITEM_CACHE.pop((generator_cls, slot), None)
    after = {slot: generator_cls.items(slot) for slot in SLOT_IDS}
    assert before == after


@_ALL
def test_overlap_audit_can_instantiate_every_slot(generator_cls: type[P3DiffSlotGenerator]) -> None:
    instances, failure = overlap_audit.build_instances(generator_cls)
    assert failure is None, failure
    assert len(instances) == len(SLOT_IDS)
    assert typing.get_args(base.SlotId) == SLOT_IDS
