"""[12미적Ⅰ-02-08] 함수의 그래프의 개형 — 파생 판정 생성기 전용 계약 테스트 — P3-03(hermetic·LLM 0).

`test_p3_diff_skeleton_generators.py`(등록부 전 생성기 공통 계약)가 *수치 평가형* 개념(미분계수 값·연립
부등식 보호)을 전제한 검사를 갖고 있어, 파생 판정 개념(02-08)은 그 몇 가지를 구조상 만족하지 못한다
(보고서 참조). 그래서 이 파일이 같은 불변식을 02-08에 맞는 형태로 직접 건다 — 등록부에 이 생성기를
더하든 아니든 이 파일은 단독으로 돈다(등록부를 건드리지 않는다).

검증 축
-------
① 슬롯 6종×12건·고유 골격 ≥ 30·틀 ≥ 30·문면/조건 중복 0.
② **전 문항이 수용 게이트(Tier1 SymPy + 근 선택)를 통과**하고, *정답을 틀리게 주입하면 전 문항이 거부*된다.
③ 정답의 **독립 재계산** — 생성기가 쓴 도함수 부호 분석이 아니라 *함숫값 비교*(f(r)과 f(r ± 1/4))로
   극대·극소·평평한 점을 다시 판정하고 발문이 요구한 역할과 대조한다(미분을 쓰지 않는 두 번째 경로).
④ **P3-24 저작 규칙 준수** — 전 문항이 `populate` 적재 파서(규칙 집행 지점)를 통과하고, 제외 4형태·
   selection 누락·x 고정 누락 변형은 *같은 파서가 거부*한다(RED 대조군).
⑤ 오개념 연결 — kebab 실재·객관식 불변식·오답 선지가 가리키는 값이 *f'=0이지만 극값이 아닌 점*이다.
⑥ 문제유형 정직성·review_status 부재·유니코드 글리프·결정론.
"""

from __future__ import annotations

import copy
import json
import re
from fractions import Fraction
from pathlib import Path

import pytest
import sympy

from whymath_backend.harness.p3_calculus1_diff_batch import run_p3_calculus1_diff_batch
from whymath_backend.l1.problem_bank.derived_form_rules import (
    DERIVED_STANDARD_CODE,
    derived_form_violations,
)
from whymath_backend.l1.problem_bank.populate import (
    ProblemCorpusError,
    load_problem_bank_records,
)
from whymath_backend.l1.standards.phase3_scope import load_reference_index, load_scope_spec
from whymath_backend.l3.equivalent import p3_diff_skeleton_base as base
from whymath_backend.l3.equivalent.acceptance import evaluate_equivalent_candidate
from whymath_backend.l3.equivalent.generator import CandidateProblem
from whymath_backend.l3.equivalent.orchestrator import run_equivalent_generation
from whymath_backend.l3.equivalent.p3_diff_graph_shape_skeleton_generator import (
    P3DiffGraphShapeGenerator,
)
from whymath_backend.l3.equivalent.p3_diff_skeleton_base import SLOT_IDS, skeleton_of
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.l4.misconception.validate import validate_distractor_map
from whymath_backend.schema.enums import AnswerFormat

pytestmark = pytest.mark.corpus_authoring

_GEN = P3DiffGraphShapeGenerator
_CORPUS_ROOT = Path(__file__).resolve().parents[4] / "data" / "corpus"
# 4차 감사(2026-10-07) 표기 교정: 학생 대면 '√'·'≤'·'≥'는 *허용*한다 — 승인 은행 4종이 쓰는 표기이고
# 표기 커버리지 게이트(`l3/notation_coverage`) 베이스라인에 이미 있는 글리프라 신규 누락이 아니다.
# 대신 그 자리를 차지하던 코드 표기('<='·'>='·'sqrt('·'*')를 금지한다(`_CODE_NOTATION`).
_GLYPHS = ("²", "³", "Σ", "α", "β", "′")
_CODE_NOTATION = re.compile(r"<=|>=|sqrt\(|\*")
_X = sympy.Symbol("x")
_DELTA = Fraction(
    1, 4
)  # 임계점이 정수라 서로 1 이상 떨어져 있다 — 1/4 이내에는 다른 임계점이 없다.

_DERIV_COND = re.compile(r"^Derivative\((?P<f>.+), x\)\.doit\(\) (?P<rel>[=<>]) 0$")
# 본문의 극값 x좌표 고정('x = 2'). 2차 감사(2026-10) 처분으로 값형은 *판정형*이 됐다 — 임계점 여럿을
# 고정하고('x = -1과 x = 3에서 극값을 갖는다') 그중 어느 것이 극대·극소인지 학생이 판정한다. 그래서
# 첫 고정 하나만 보던 패턴을 *모든* 고정으로 넓힌다(`f(x) = 2x^3`의 ') = 2'는 앞이 x가 아니라 걸리지 않는다).
_PINS = re.compile(r"(?<![A-Za-z(])x = (?P<r>-?\d+)")
# '극솟값 -21을 가질 때'(고정 1개)와 '극댓값이 7일 때'(판정형) 두 표기를 모두 읽는다.
_VALUE_WORD = re.compile(r"(?P<word>극댓값|극솟값)(?:이)? (?P<v>-?\d+)")


def _items() -> list[base.DiffItem]:
    return [i for s in SLOT_IDS for i in _GEN.items(s)]


def _candidates(slot: str) -> list[CandidateProblem]:
    spec = _GEN.spec_for(slot)
    generator = _GEN(slot=slot)
    out: list[CandidateProblem] = []
    while (candidate := generator.generate(spec)) is not None:
        out.append(candidate)
    return out


@pytest.fixture(scope="module")
def bank(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, list[dict[str, object]]]:
    """임시 배치 — 등록부를 건드리지 않고 이 생성기만 JSONL로 낸다(배치 공개 함수 재사용)."""
    out = tmp_path_factory.mktemp("graph_shape_bank") / "problems.jsonl"
    report = run_p3_calculus1_diff_batch(generators=(_GEN,), out_path=out)
    assert report.total_stored == report.total_requested == 72, report.to_json()
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line]
    return out, rows


def _rows(bank: tuple[Path, list[dict[str, object]]]) -> list[dict[str, object]]:
    return bank[1]


def _verify(row: dict[str, object]) -> dict[str, object]:
    verify = row["verify"]
    assert isinstance(verify, dict)
    return verify


def _function_of(row: dict[str, object]) -> sympy.Expr:
    """검산 조건에서 *원 함수*를 읽는다(문항이 말한 f) — 미지수(a·b·k)는 정답으로 치환한다."""
    verify = _verify(row)
    cond = verify["conditions"]
    first = cond if isinstance(cond, str) else cond[0]
    match = _DERIV_COND.match(first)
    expr_text = match["f"] if match else first.removeprefix("y = ")
    amap = verify["answer_map"]
    assert isinstance(amap, dict)
    params = {
        sympy.Symbol(k): sympy.Integer(int(v)) for k, v in amap.items() if k not in ("x", "y")
    }
    return sympy.sympify(expr_text).subs(params)


def _value_kind(expr: sympy.Expr, r: sympy.Rational | int) -> str:
    """**함숫값 비교**로 r의 성격을 판정한다 — 도함수를 쓰지 않는 독립 경로.

    f(r)이 r ± 1/4의 값보다 둘 다 크면 max, 둘 다 작으면 min, 아니면 평평(극값 아님).
    """
    f0 = expr.subs(_X, r)
    left = expr.subs(_X, sympy.Rational(r) - sympy.Rational(_DELTA.numerator, _DELTA.denominator))
    right = expr.subs(_X, sympy.Rational(r) + sympy.Rational(_DELTA.numerator, _DELTA.denominator))
    if f0 > left and f0 > right:
        return "max"
    if f0 < left and f0 < right:
        return "min"
    return "flat"


def _critical_points(expr: sympy.Expr) -> list[int]:
    roots = sympy.solve(sympy.diff(expr, _X), _X)
    assert roots and all(r.is_integer for r in roots), roots
    return sorted(int(r) for r in roots)


def _role_of(text: str) -> str:
    """발문이 요구하는 x좌표의 역할 — 발문 문자열만 본다(생성기 내부 상태를 보지 않는다)."""
    if "바뀌지 않는" in text:
        return "flat"
    if "증가하다가 감소로" in text or "극대가 되는" in text:
        return "max"
    if "감소하다가 증가로" in text or "극소가 되는" in text:
        return "min"
    return "turn"


def _is_value_item(row: dict[str, object]) -> bool:
    amap = _verify(row)["answer_map"]
    assert isinstance(amap, dict)
    return "y" in amap


def _is_param_item(row: dict[str, object]) -> bool:
    """미지 상수를 *답하는* 문항 — 4차 감사 재설계의 값형(미지 계수 a·k를 거쳐 극값을 답한다)은
    answer_map에 보조 미지수를 싣지만 답은 y라 값형(`_is_value_item`)으로 센다."""
    amap = _verify(row)["answer_map"]
    assert isinstance(amap, dict)
    return "y" not in amap and any(k not in ("x", "y") for k in amap)


def _is_interval_item(row: dict[str, object]) -> bool:
    # 2차 감사는 개폐가 모호한 '감소하는 구간에 속하는 정수'를 `f'(x) < 0`을 만족시키는 정수로
    # 바꿨으나, 3차 감사가 그 발문을 bad_tag로 판정했다(f'의 부등식을 직접 줘 증감 판정이 빠진다 —
    # 우회로 판정기 T08-derivative-inequality). 지금 발문은 다시 '감소(증가)하는 x의 값의 범위'로 묻고,
    # 개폐 모호성은 *함수 선택*으로 없앤다(f'의 근이 정수가 아니다 — 아래 테스트가 열린·닫힌 두 해석의
    # 정수 집합이 같음을 따로 단언한다). 두 문면을 모두 읽는다(종전 표기 'f'(x) < 0을 만족시키는 정수
    # x는 하나뿐'이 되살아나도 이 테스트가 그 문항을 구간형으로 분류해 같은 검사를 건다).
    return bool(re.search(r"정수(?: x)?는 하나뿐", str(row["question_text"])))


def _x_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        r
        for r in rows
        if not _is_value_item(r) and not _is_param_item(r) and not _is_interval_item(r)
    ]


# ──────────────────────────────────────────────────────────────────────────
# ① 구조
# ──────────────────────────────────────────────────────────────────────────
def test_every_slot_is_filled_with_the_declared_count() -> None:
    for slot in SLOT_IDS:
        items = _GEN.items(slot)
        assert len(items) == _GEN.slot_count == 12, (slot, len(items))
        assert {item.slot for item in items} == {slot}
        assert len({item.frame_id for item in items}) >= 4, f"{slot}: 틀이 4종 미만"
    assert set(_GEN.slot_difficulty) == set(SLOT_IDS)


def test_distinct_skeletons_and_frames_reach_the_floor() -> None:
    items = _items()
    assert len({skeleton_of(i.question_text) for i in items}) >= 30
    assert len({i.frame_id for i in items}) >= 30
    for slot in SLOT_IDS:
        assert len({skeleton_of(i.question_text) for i in _GEN.items(slot)}) >= 4, slot


def test_questions_and_conditions_are_unique_within_the_concept() -> None:
    items = _items()
    texts = [i.question_text for i in items]
    conds = [
        i.conditions if isinstance(i.conditions, str) else "&&".join(i.conditions) for i in items
    ]
    assert len(set(texts)) == len(texts)
    assert len(set(conds)) == len(conds)


def test_items_are_deterministic_across_cache_rebuilds() -> None:
    before = {slot: _GEN.items(slot) for slot in SLOT_IDS}
    for slot in SLOT_IDS:
        base._ITEM_CACHE.pop((_GEN, slot), None)
    assert before == {slot: _GEN.items(slot) for slot in SLOT_IDS}


def test_texts_are_clean_korean_without_leftover_placeholders_or_glyphs() -> None:
    for item in _items():
        for field in (
            item.question_text,
            item.explanation,
            item.answer_text,
            *(item.choices or ()),
        ):
            assert "{" not in field and "}" not in field, field
            assert "  " not in field, field
            assert not any(g in field for g in _GLYPHS), field
            assert not _CODE_NOTATION.search(field), field
            assert "$" not in field and "\\" not in field, field
        assert item.answer_format in set(AnswerFormat)
        assert item.answer_format != AnswerFormat.식


def test_no_review_status_and_unpublished(bank: tuple[Path, list[dict[str, object]]]) -> None:
    for row in _rows(bank):
        assert "review_status" not in row
        assert row["is_published"] is False
    for slot in SLOT_IDS:
        for candidate in _candidates(slot):
            problem = candidate.problem
            assert problem.review_status is None
            assert problem.tags == [f"{base.SLOT_TAG_PREFIX}{slot}"]
            assert problem.achievement_standard_codes == [_GEN.standard_code]
            assert [t.concept_src_id for t in candidate.concept_tags] == [_GEN.concept_src_id]


# ──────────────────────────────────────────────────────────────────────────
# ② 수용 게이트 — 통과와 RED 대조
# ──────────────────────────────────────────────────────────────────────────
def test_every_item_passes_the_acceptance_gate() -> None:
    for slot in SLOT_IDS:
        spec = _GEN.spec_for(slot)
        generator = _GEN(slot=slot)
        for _ in range(len(_GEN.items(slot))):
            outcome = run_equivalent_generation(spec, generator, signature_index=None)
            assert outcome.status == "accepted", (slot, outcome.status, outcome.reasons)
        assert generator.generate(spec) is None


def _broken_map(candidate: CandidateProblem) -> dict[str, str]:
    """정답을 틀리게 — 미지수가 x뿐이면 x를, 아니면 x가 아닌 쪽(y·a·b·k)을 1 올린다."""
    amap = dict(candidate.answer_map)
    key = "x" if list(amap) == ["x"] else next(k for k in amap if k != "x")
    amap[key] = f"({amap[key]}) + 1"
    return amap


def test_gate_rejects_a_wrong_answer_for_every_item() -> None:
    """**변별력(RED)** — 정답을 틀리게 만들면 전 문항이 거부된다(`answer_selection`을 함께 넘긴다)."""
    total = rejected = 0
    for slot in SLOT_IDS:
        spec = _GEN.spec_for(slot)
        for candidate in _candidates(slot):
            total += 1
            verdict = evaluate_equivalent_candidate(
                spec,
                candidate.problem,
                provenance=candidate.provenance,
                conditions=candidate.conditions,
                answer_map=_broken_map(candidate),
                answer_selection=candidate.answer_selection,
            )
            if not verdict.accepted:
                rejected += 1
    assert total == 72
    assert rejected == total, f"{total - rejected}건이 틀린 답을 통과시켰다"


def test_answer_selection_carries_weight_in_the_gate() -> None:
    """selection을 빼면 두 근 중 어느 쪽인지 확정되지 않아 게이트가 강등한다 — selection은 장식이 아니다."""
    demoted = checked = 0
    for slot in SLOT_IDS:
        spec = _GEN.spec_for(slot)
        for candidate in _candidates(slot):
            if candidate.answer_selection is None:
                continue
            checked += 1
            verdict = evaluate_equivalent_candidate(
                spec,
                candidate.problem,
                provenance=candidate.provenance,
                conditions=candidate.conditions,
                answer_map=candidate.answer_map,
                answer_selection=None,
            )
            if not verdict.accepted:
                demoted += 1
    assert checked >= 36
    assert demoted == checked


def test_assemble_attaches_selection_exactly_for_items_that_declare_it() -> None:
    for slot in SLOT_IDS:
        items = _GEN.items(slot)
        candidates = _candidates(slot)
        assert len(items) == len(candidates)
        for item, candidate in zip(items, candidates, strict=True):
            declared = getattr(item, "answer_selection", None)
            assert candidate.answer_selection == declared


# ──────────────────────────────────────────────────────────────────────────
# ③ 독립 재계산 — 함숫값 비교 경로
# ──────────────────────────────────────────────────────────────────────────
def test_x_coordinate_answers_match_value_based_classification(
    bank: tuple[Path, list[dict[str, object]]],
) -> None:
    checked = 0
    for row in _x_rows(_rows(bank)):
        text = str(row["question_text"])
        expr = _function_of(row)
        crit = _critical_points(expr)
        kinds = {r: _value_kind(expr, r) for r in crit}
        role = _role_of(text)
        if role == "flat":
            cands = [r for r in crit if kinds[r] == "flat"]
        elif role == "turn":
            cands = [r for r in crit if kinds[r] != "flat"]
        else:
            cands = [r for r in crit if kinds[r] == role]
        if "큰 값" in text:
            assert len(cands) >= 2, text
            expected = max(cands)
        elif "작은 값" in text:
            assert len(cands) >= 2, text
            expected = min(cands)
        else:
            assert len(cands) == 1, (text, cands)
            expected = cands[0]
        assert int(str(row["answer"])) == expected, text
        # 근 선택 — 답이 f' = 0의 *모든* 실근 중 맨 끝이어야 selection 주장이 참이다.
        selection = _verify(row).get("answer_selection")
        assert selection in ("smallest", "largest"), text
        assert expected == (crit[0] if selection == "smallest" else crit[-1]), text
        checked += 1
    assert checked >= 36


def _all_critical_kinds(expr: sympy.Expr) -> dict[int, str]:
    """f'(x) = 0의 정수 근 전부와 그 성격(함숫값 비교 — 도함수 부호 분석과 독립)."""
    return {r: _value_kind(expr, r) for r in _critical_points(expr)}


def test_value_items_pin_x_and_match_the_value_at_a_verified_extremum(
    bank: tuple[Path, list[dict[str, object]]],
) -> None:
    """값형 — 4차 감사(2026-10-07) 설계를 동결한다.

    3차 은행은 '임계점을 둘 이상 고정하고 종류만 판정'하게 했는데, 감사자가 그 형태를 다시 bad_tag로
    봤다 — 고정된 위치에 대입해 대소를 비교하면 '큰 값이 극댓값'으로 끝난다(삼차·사차에서 늘 맞는다).
    그래서 이제 동결하는 것은 반대 방향이다: 고정된 위치 가운데 *극값인* 점은 많아야 하나이고, 나머지는
    ⓐ 미지 계수형 — 고정점 하나(f'(p) = 0이 미지 계수를 유일하게 정한다)와 *고정되지 않은* 다른
       극값을 답한다(학생이 도함수로 직접 찾는다), 또는
    ⓑ 평평한 임계점형 — 고정점에 극값이 아닌 임계점이 섞여 *극값인지* 판정해야 한다.
    """
    checked = unknown_coef = flat_mixed = 0
    for row in _rows(bank):
        if not _is_value_item(row):
            continue
        text = str(row["question_text"])
        verify = _verify(row)
        amap = verify["answer_map"]
        assert isinstance(amap, dict)
        expr = _function_of(row)  # 미지 계수는 정답 값으로 치환됨
        pins = sorted({int(m["r"]) for m in _PINS.finditer(text)})
        assert pins, f"규칙 C3 — 본문에 x 고정이 없다: {text}"
        kinds = _all_critical_kinds(expr)
        # 고정점은 전부 임계점이다('x = p에서 극값을 갖는다'·'f'(x) = 0의 근은 x = p'가 참이다).
        assert all(p in kinds for p in pins), (text, pins, kinds)
        extremum_pins = [p for p in pins if kinds[p] != "flat"]
        assert len(extremum_pins) <= 1, f"극값 위치를 둘 이상 준다(대입·대소 비교 우회로): {text}"
        r = int(amap["x"])
        unknowns = sorted(k for k in amap if k not in ("x", "y"))
        if unknowns:
            # ⓐ 미지 계수형 — 고정 하나 · 그 고정점의 f'(p) = 0이 미지 계수를 유일하게 정한다 · 답은 다른 점.
            assert len(pins) == 1 and len(unknowns) == 1, (text, pins, unknowns)
            (name,) = unknowns
            cond = verify["conditions"]
            assert isinstance(cond, list) and len(cond) == 2
            raw = sympy.sympify(cond[0].removeprefix("y = "))
            coef = sympy.Symbol(name)
            assert raw.free_symbols == {_X, coef}, (text, raw)
            solved = sympy.solve(sympy.diff(raw, _X).subs(_X, pins[0]), coef)
            assert solved == [sympy.Integer(int(str(amap[name])))], (text, solved)
            assert r != pins[0], f"답한 극값이 고정점이다(다른 임계점을 찾을 필요가 없다): {text}"
            unknown_coef += 1
        else:
            # ⓑ 평평한 임계점형 — 고정점에 극값이 아닌 임계점이 섞여 있다.
            assert any(kinds[p] == "flat" for p in pins), (text, kinds)
            flat_mixed += 1
        wanted = "max" if "극댓값" in text else ("min" if "극솟값" in text else None)
        cands = [c for c, k in kinds.items() if (k == wanted if wanted else k != "flat")]
        assert cands, text
        values = {c: int(expr.subs(_X, c)) for c in cands}
        if "작은 값" in text or "큰 값" in text:
            assert len(cands) >= 2, text
            pick = min if "작은 값" in text else max
            value = pick(values.values())
        else:
            assert len(set(values.values())) == 1, (text, cands)  # 유일(또는 대칭 동값)
            value = next(iter(values.values()))
        assert r in cands and values[r] == value and amap["y"] == str(value), text
        assert int(str(row["answer"])) == value
        # 검산 조건이 x = r의 임계점 성격까지 본다(두 번째 조건 f'(x) = 0 — 미지 계수 치환 후).
        cond = verify["conditions"]
        assert isinstance(cond, list) and len(cond) == 2
        params = {sympy.Symbol(k): sympy.Integer(int(str(amap[k]))) for k in unknowns}
        deriv_at_r = sympy.sympify(cond[1].split(" = ")[0]).subs(params).doit().subs(_X, r)
        assert deriv_at_r == 0
        checked += 1
    assert checked >= 12
    assert unknown_coef >= 8 and flat_mixed >= 1, (unknown_coef, flat_mixed)


def test_interval_items_have_exactly_one_integer_in_the_stated_region(
    bank: tuple[Path, list[dict[str, object]]],
) -> None:
    checked = 0
    for row in _rows(bank):
        if not _is_interval_item(row):
            continue
        text = str(row["question_text"])
        # 부호 방향은 발문 단어가 아니라 검산 조건의 관계(`> 0`·`< 0`)에서 읽고, 발문 단어와 맞는지
        # 따로 대조한다(조건과 문면이 서로 다른 방향을 말하는 결함을 잡는다).
        cond = _verify(row)["conditions"]
        assert isinstance(cond, str), text
        relation = _DERIV_COND.match(cond)
        assert relation is not None and relation["rel"] in "<>", (text, cond)
        wanted = 1 if relation["rel"] == ">" else -1
        assert ("증가" in text or "커지는" in text) == (wanted == 1), text
        deriv = sympy.diff(_function_of(row), _X)
        signs = {n: int(sympy.sign(deriv.subs(_X, n))) for n in range(-80, 81)}
        inside = [n for n, sign in signs.items() if sign == wanted]
        assert inside == [int(str(row["answer"]))], (text, inside)
        # 개폐 해석 무관 — '감소하는 x의 값의 범위'를 교과서 관례대로 닫힌 범위(f' = 0인 끝점 포함)로
        # 읽어도 정수가 하나뿐이어야 '하나뿐이다'가 참이다(f'의 근이 정수면 양 끝 정수가 더해진다).
        closed = [n for n, sign in signs.items() if sign in (wanted, 0)]
        assert closed == inside, (text, closed)
        checked += 1
    assert checked >= 6


def test_parameter_items_have_a_unique_solution_and_a_matching_extremum(
    bank: tuple[Path, list[dict[str, object]]],
) -> None:
    checked = 0
    for row in _rows(bank):
        if not _is_param_item(row):
            continue
        text = str(row["question_text"])
        verify = _verify(row)
        amap = verify["answer_map"]
        assert isinstance(amap, dict)
        param = next(k for k in amap if k != "x")
        word = _VALUE_WORD.search(text)
        assert word is not None, text
        expr = _function_of(row)
        pins = sorted({int(m["r"]) for m in _PINS.finditer(text)})
        assert pins, text
        want = "max" if word["word"] == "극댓값" else "min"
        kinds = _all_critical_kinds(expr)
        # 4차 감사 동결 — 고정점은 임계점이고, 그중 극값인 점은 많아야 하나다(임계점 둘을 다 주던 종전
        # '판정형 k'는 대입·대소 비교로 풀렸다). r은 *물은 종류*의 유일한 임계점이다 — 고정점일 수도
        # (계수 a·b를 f'(r) = 0으로 정하는 형태), 고정되지 않은 다른 임계점일 수도(4차 재설계 — x = p에서
        # 극값을 가질 때 *다른 쪽* 극값이 v) 있다.
        assert all(p in kinds for p in pins), (text, pins, kinds)
        assert len([p for p in pins if kinds[p] != "flat"]) <= 1, text
        matching = [c for c, k in kinds.items() if k == want]
        assert len(matching) == 1, (text, kinds)
        r = matching[0]
        assert int(str(amap["x"])) == r, text
        kind = _value_kind(expr, r)
        assert kind == ("max" if word["word"] == "극댓값" else "min"), text
        assert int(expr.subs(_X, r)) == int(word["v"]), text
        # 유일성 — 미지수를 *기호로 둔* 원 함수에서 f'(r) = 0을 풀면 해가 정답 하나뿐이다.
        # (f'(r) = 0과 f(r) = v 중 미지수를 *담은* 식들의 공통해 — 담지 않은 식은 0 = 0 항등이어야 한다.)
        cond = verify["conditions"]
        assert isinstance(cond, list) and len(cond) == 2
        sym_expr = sympy.sympify(_DERIV_COND.match(cond[0])["f"])  # type: ignore[index]
        # 미지 상수 전부(a·b 연립형은 둘, 판정형 k는 하나) — 3차 감사 처분으로 a·b 두 미지수를 두는
        # 틀이 생겼다(미지수가 하나면 f(r) = v 대입만으로 정해져 f'(r) = 0이 풀이에 안 쓰였다 —
        # 우회로 판정기 T-value-determines). 그래서 단일 기호 풀이를 *연립* 풀이로 일반화한다.
        unknowns = sorted((sympy.Symbol(k) for k in amap if k != "x"), key=str)
        assert set(sym_expr.free_symbols) == {_X, *unknowns}, (text, sym_expr.free_symbols)
        equations = [
            sympy.diff(sym_expr, _X).subs(_X, r),
            sym_expr.subs(_X, r) - int(word["v"]),
        ]
        solutions = sympy.solve(equations, unknowns, dict=True)
        expected = {sym: sympy.Integer(int(str(amap[str(sym)]))) for sym in unknowns}
        assert solutions == [expected], (text, solutions)
        # 미지수가 둘이면 두 식이 *모두* 필요하다 — 한 식만으로 물은 상수가 정해지면 미분 조건(또는 함숫값
        # 조건)이 풀이에 쓰이지 않는 틀이다(T-value-determines의 독립 재확인).
        if len(unknowns) == 2:
            asked = sympy.Symbol(param)
            for eq in equations:
                alone = sympy.solve(eq, asked)
                assert not (alone and all(not v.free_symbols for v in alone)), (text, eq, alone)
        assert int(str(row["answer"])) == int(str(amap[param]))
        checked += 1
    assert checked >= 12


# ──────────────────────────────────────────────────────────────────────────
# ④ P3-24 저작 규칙 — 준수와 RED 대조
# ──────────────────────────────────────────────────────────────────────────
def test_every_row_passes_the_p324_enforcement_parser(
    bank: tuple[Path, list[dict[str, object]]],
) -> None:
    records = load_problem_bank_records(bank[0])
    assert len(records) == 72
    assert sum(1 for r in records if r.verify.answer_selection) >= 36
    for row in _rows(bank):
        verify = _verify(row)
        assert not derived_form_violations(
            standard_codes=[DERIVED_STANDARD_CODE],
            question_text=str(row["question_text"]),
            answer=str(row["answer"]),
            conditions=verify["conditions"],  # type: ignore[arg-type]
            answer_map=verify["answer_map"],  # type: ignore[arg-type]
            answer_selection=verify.get("answer_selection"),  # type: ignore[arg-type]
        )


def test_b3_items_always_carry_selection_and_c3_items_pin_x(
    bank: tuple[Path, list[dict[str, object]]],
) -> None:
    b3 = c3 = 0
    for row in _rows(bank):
        text = str(row["question_text"])
        verify = _verify(row)
        if re.search(r"극[대소].*x좌표|x좌표.*극[대소]", text):
            assert verify.get("answer_selection") in ("smallest", "largest"), text
            b3 += 1
        if re.search(r"극(대|소)?(댓|솟)?값", text) and "x좌표" not in text:
            assert _PINS.search(text), text
            assert "x" in verify["answer_map"]  # type: ignore[operator]
            c3 += 1
    assert b3 >= 6 and c3 >= 24


def _mutated(row: dict[str, object], name: str) -> dict[str, object]:
    out = copy.deepcopy(row)
    verify = _verify(out)
    amap = verify["answer_map"]
    assert isinstance(amap, dict)
    if name == "drop_selection":
        del verify["answer_selection"]
    elif name == "unpin_x_text":
        # 판정형 본문은 고정이 여럿이라 첫 고정만 지우면 나머지가 남는다 — 고정을 *모두* 지운다.
        out["question_text"] = str(out["question_text"]).replace("x = ", "x가 ")
    elif name == "drop_x_from_answer_map":
        amap.pop("x")
    elif name == "value_without_x":
        out["question_text"] = "삼차함수 f(x) = x^3 - 3x^2 + 2의 극솟값을 구하시오."
        verify["answer_map"] = {"y": amap["y"]}
    elif name == "bare_expression_condition":
        verify["conditions"] = "3*x**2 - 6*x"
    elif name == "interval_notation":
        out["question_text"] = (
            "삼차함수 f(x) = x^3 - 3x^2 + 2가 증가하는 구간을 구간 기호로 쓰시오."
        )
        out["answer"] = "(-∞, 0], [2, ∞)"
        out["answer_format"] = "식"
    elif name == "boundary_inclusion":
        out["question_text"] = (
            "삼차함수 f(x) = x^3 - 3x^2 + 2가 증가하는 구간의 시작을 닫힌 구간(경계 포함)으로 쓰시오."
        )
        out["answer"] = "x ≥ 2"
        out["answer_format"] = "식"
    elif name == "extremum_count":
        out["question_text"] = "삼차함수 f(x) = x^3 - 3x의 극값의 개수를 구하시오."
        out["answer"] = "2"
        out["problem_type_codes"] = ["ptype.count-solutions"]
        out["verify"] = {
            "conditions": "x**3 - 3*x",
            "answer_map": {},
            "answer_kind": "extremum_count",
            "verification_tier": "machine_sampled",
        }
    else:  # pragma: no cover — 오타 방지
        raise AssertionError(name)
    return out


_NEGATIVES = [
    ("drop_selection", "B3-", "b3"),
    ("unpin_x_text", "C3-", "c3"),
    ("drop_x_from_answer_map", "C3-", "c3"),
    ("value_without_x", "C3-", "c3"),
    ("bare_expression_condition", "A5-", "base"),
    ("interval_notation", "A4-", "base"),
    ("boundary_inclusion", "A3-", "base"),
    ("extremum_count", "A5-", "base"),
]


@pytest.mark.parametrize(("name", "rule", "source"), _NEGATIVES, ids=[n[0] for n in _NEGATIVES])
def test_p324_parser_rejects_every_excluded_or_unsafe_variant(
    bank: tuple[Path, list[dict[str, object]]],
    tmp_path: Path,
    name: str,
    rule: str,
    source: str,
) -> None:
    """RED 대조군 — 제외 4형태·selection 누락·x 고정 누락 변형을 *같은 적재 파서*가 거부한다."""
    rows = _rows(bank)
    if source == "b3":
        row = next(
            r
            for r in rows
            if "극대가 되는 x좌표" in str(r["question_text"]) and _verify(r).get("answer_selection")
        )
    elif source == "c3":
        row = next(r for r in rows if _is_value_item(r))
    else:
        row = next(r for r in rows if _verify(r).get("answer_selection"))
    path = tmp_path / "variant.jsonl"
    path.write_text(json.dumps(_mutated(row, name), ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(ProblemCorpusError) as info:
        load_problem_bank_records(path)
    assert rule in str(info.value), (name, str(info.value)[:200])


def test_unmodified_control_row_loads(
    bank: tuple[Path, list[dict[str, object]]], tmp_path: Path
) -> None:
    """대조군의 대조군 — 변형하지 않은 같은 행은 적재된다(거부가 '무엇이든 거부'가 아님)."""
    row = next(r for r in _rows(bank) if _verify(r).get("answer_selection"))
    path = tmp_path / "control.jsonl"
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    assert len(load_problem_bank_records(path)) == 1


def test_excluded_forms_never_appear_in_generated_text() -> None:
    banned = ("구간 기호", "경계", "닫힌 구간", "열린 구간", "개수", "∞")
    for item in _items():
        for field in (item.question_text, item.answer_text):
            assert not any(b in field for b in banned), field
        assert not item.answer_text.startswith(("x ", "(", "["))


# ──────────────────────────────────────────────────────────────────────────
# ⑤ 오개념 연결
# ──────────────────────────────────────────────────────────────────────────
def test_misconception_links_are_exactly_the_mc_slot_and_resolve() -> None:
    for slot in SLOT_IDS:
        linked = _GEN.target_misconception_ids(slot)
        if slot != "misconception_trigger":
            assert linked == frozenset(), slot
            continue
        assert linked == {"critical-point-implies-extremum"}
        assert all(k in CATALOG_BY_ID for k in linked)
        for candidate in _candidates(slot):
            assert candidate.problem.distractor_map
            assert validate_distractor_map(candidate.problem.distractor_map) == []


def test_misconception_chain_gap_is_documented_not_hidden() -> None:
    """02-08의 핵심 오개념(M0676)에는 크로스링크 kebab이 없다 — 이 문항들은 M0080에만 닿는다.

    이 테스트는 *현 상태를 동결*한다: 누군가 M0676을 가리키는 kebab을 신설하면 red가 되어, 그때 이
    생성기의 오답 연결과 `docstring`의 '계측기 도달 불가' 서술을 함께 갱신하게 한다.
    """
    core = {
        m.mis_id
        for m in load_scope_spec().core_misconceptions
        if m.concept_code == "[12미적Ⅰ-02-08]"
    }
    assert core == {"M0676"}
    crosslinks = json.loads(
        (_CORPUS_ROOT / "misconception_crosslinks_v1" / "crosslinks.json").read_text(
            encoding="utf-8"
        )
    )["crosslinks"]
    reached = {
        row["mis_id"]
        for row in crosslinks
        if row["kebab_id"] == "critical-point-implies-extremum" and row["link_type"] == "직접매핑"
    }
    assert reached == {"M0080"}
    assert not (core & reached)


def test_mc_distractor_is_a_flat_critical_point_and_other_choices_are_not_critical(
    bank: tuple[Path, list[dict[str, object]]],
) -> None:
    """오답 선지의 정체를 *독립 경로*로 확인한다 — kebab이 붙은 선지는 f'=0이지만 극값이 아닌 점이다."""
    mc_rows = [r for r in _rows(bank) if "misconception_trigger" in str(r["tags"])]
    assert len(mc_rows) == 12
    for row in mc_rows:
        choices = [int(c) for c in row["choices"]]  # type: ignore[attr-defined]
        assert len(choices) == len(set(choices)) == 4
        assert str(row["answer"]) in row["choices"]  # type: ignore[operator]
        expr = _function_of(row)
        deriv = sympy.diff(expr, _X)
        crit = _critical_points(expr)
        kinds = {r: _value_kind(expr, r) for r in crit}
        dmap = row["distractor_map"]
        assert isinstance(dmap, list) and len(dmap) == 1
        entry = dmap[0]
        assert entry["misconception_id"] == "critical-point-implies-extremum"
        flat_choice = choices[entry["choice_index"]]
        assert flat_choice in crit and kinds[flat_choice] == "flat"
        assert deriv.subs(_X, flat_choice) == 0
        answer = int(str(row["answer"]))
        assert answer != flat_choice
        assert answer in crit and kinds[answer] != "flat"
        # 나머지 두 선지는 임계점이 아니다(오개념이 아닌 필러).
        others = [c for c in choices if c not in (answer, flat_choice)]
        assert len(others) == 2 and all(deriv.subs(_X, c) != 0 for c in others)


# ──────────────────────────────────────────────────────────────────────────
# ⑥ 문제유형·스킬 연결 정직성
# ──────────────────────────────────────────────────────────────────────────
def test_problem_types_are_honest_and_skill_overlap_is_measured(
    bank: tuple[Path, list[dict[str, object]]],
) -> None:
    spec = load_scope_spec()
    index = load_reference_index(spec)
    concept = next(c for c in spec.concepts if c.code == _GEN.standard_code)
    cross = index.crosswalk[concept.concept_id]
    concept_skills = {
        s for a in cross.atom_codes if a in index.atoms for s in index.atoms[a].behavior_skills
    } & set(spec.skills)
    assert concept_skills == {"skill.graph-sketching", "skill.graph-reading"}
    type_skills: dict[str, set[str]] = {}
    for line in (
        (_CORPUS_ROOT / "problem_type_graph_v1" / "problem_types.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ):
        record = json.loads(line)
        type_skills[record["problem_type_id"]] = set(record["behavior_skills"])
    allowed = set(spec.problem_types)
    linked = 0
    by_type: dict[str, int] = {}
    for row in _rows(bank):
        codes = row["problem_type_codes"]
        assert isinstance(codes, list) and len(codes) == 1 and codes[0] in allowed
        by_type[codes[0]] = by_type.get(codes[0], 0) + 1
        if type_skills[codes[0]] & concept_skills:
            linked += 1
    # 정직한 유형만: 극값·증감 경계점의 위치·값은 optimize-extremum(graph-sketching과 겹침),
    # 구간 소속 정수·미지수 구하기는 solve-for-unknown(겹치지 않음 — 겹치게 하려고 바꾸지 않는다).
    assert set(by_type) == {"ptype.optimize-extremum", "ptype.solve-for-unknown"}
    assert linked == by_type["ptype.optimize-extremum"]
    assert linked >= 40


def test_no_function_valued_or_non_scalar_answers() -> None:
    for item in _items():
        assert re.fullmatch(r"-?\d+", item.answer_text), item.answer_text
        assert all(re.fullmatch(r"-?\d+", v) for _, v in item.answer_map), item.answer_map


def test_multiple_choice_invariants() -> None:
    mc = 0
    for slot in SLOT_IDS:
        for item in _GEN.items(slot):
            if item.choices is None:
                assert not item.distractors
                continue
            mc += 1
            assert len(item.choices) == len(set(item.choices)) == 4
            assert item.answer_text in item.choices
            answer_index = item.choices.index(item.answer_text)
            assert all(index != answer_index for index, _ in item.distractors)
    assert mc == 12
