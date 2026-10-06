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
_GLYPHS = ("²", "³", "Σ", "α", "β", "√", "′")
_X = sympy.Symbol("x")
_DELTA = Fraction(
    1, 4
)  # 임계점이 정수라 서로 1 이상 떨어져 있다 — 1/4 이내에는 다른 임계점이 없다.

_DERIV_COND = re.compile(r"^Derivative\((?P<f>.+), x\)\.doit\(\) (?P<rel>[=<>]) 0$")
_PIN = re.compile(r"x = (?P<r>-?\d+)에서")
_VALUE_WORD = re.compile(r"(?P<word>극댓값|극솟값) (?P<v>-?\d+)")


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
    amap = _verify(row)["answer_map"]
    assert isinstance(amap, dict)
    return any(k not in ("x", "y") for k in amap)


def _is_interval_item(row: dict[str, object]) -> bool:
    return "정수는 하나뿐" in str(row["question_text"])


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


def test_value_items_pin_x_and_match_the_value_at_a_verified_extremum(
    bank: tuple[Path, list[dict[str, object]]],
) -> None:
    checked = 0
    for row in _rows(bank):
        if not _is_value_item(row):
            continue
        text = str(row["question_text"])
        expr = _function_of(row)
        pin = _PIN.search(text)
        assert pin is not None, f"본문에 x 고정이 없다: {text}"
        r = int(pin["r"])
        kind = _value_kind(expr, r)
        assert kind != "flat", f"x = {r}은 극값이 아니다: {text}"
        if "극댓값" in text:
            assert kind == "max", text
        if "극솟값" in text:
            assert kind == "min", text
        value = int(expr.subs(_X, r))
        verify = _verify(row)
        assert verify["answer_map"] == {"x": str(r), "y": str(value)}
        assert int(str(row["answer"])) == value
        # 검산 조건이 x = r의 임계점 성격까지 본다(두 번째 조건 f'(x) = 0).
        cond = verify["conditions"]
        assert isinstance(cond, list) and len(cond) == 2
        deriv_at_r = sympy.sympify(cond[1].split(" = ")[0]).subs(_X, r)
        assert deriv_at_r == 0
        checked += 1
    assert checked >= 12


def test_interval_items_have_exactly_one_integer_in_the_stated_region(
    bank: tuple[Path, list[dict[str, object]]],
) -> None:
    checked = 0
    for row in _rows(bank):
        if not _is_interval_item(row):
            continue
        text = str(row["question_text"])
        wanted = 1 if "증가하는 구간" in text else -1
        deriv = sympy.diff(_function_of(row), _X)
        inside = [n for n in range(-80, 81) if int(sympy.sign(deriv.subs(_X, n))) == wanted]
        assert inside == [int(str(row["answer"]))], (text, inside)
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
        r = int(_PIN.search(text)["r"])  # type: ignore[index]
        word = _VALUE_WORD.search(text)
        assert word is not None, text
        expr = _function_of(row)
        kind = _value_kind(expr, r)
        assert kind == ("max" if word["word"] == "극댓값" else "min"), text
        assert int(expr.subs(_X, r)) == int(word["v"]), text
        # 유일성 — 미지수를 *기호로 둔* 원 함수에서 f'(r) = 0을 풀면 해가 정답 하나뿐이다.
        # (f'(r) = 0과 f(r) = v 중 미지수를 *담은* 식들의 공통해 — 담지 않은 식은 0 = 0 항등이어야 한다.)
        cond = verify["conditions"]
        assert isinstance(cond, list) and len(cond) == 2
        sym_expr = sympy.sympify(_DERIV_COND.match(cond[0])["f"])  # type: ignore[index]
        symbol = sympy.Symbol(param)
        equations = [
            sympy.diff(sym_expr, _X).subs(_X, r),
            sym_expr.subs(_X, r) - int(word["v"]),
        ]
        solution_sets: list[set[sympy.Expr]] = []
        for eq in equations:
            if eq.has(symbol):
                solution_sets.append(set(sympy.solve(eq, symbol)))
            else:
                assert eq == 0, (text, eq)  # 미지수가 없는 식은 이미 성립해야 한다
        common = set.intersection(*solution_sets)
        assert common == {sympy.Integer(int(str(amap[param])))}, (text, common)
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
            assert _PIN.search(text), text
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
        out["question_text"] = str(out["question_text"]).replace("x = ", "x가 ", 1)
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
