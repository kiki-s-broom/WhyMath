"""[12미적Ⅰ-02-07] 증가·감소, 극대·극소 — 빈 4칸 생성기 전용 계약 테스트 (P3-05 4단계).

02-08 생성기의 틀 공장을 쓰므로(`p3_diff_monotonicity_extremum_skeleton_generator`) 같은 검증 축을
같은 방식으로 건다 — 정답을 생성기의 도함수 부호 분석이 아니라 **함숫값 비교**(f(r)과 f(r ± 1/4))로
다시 판정하는 독립 경로, 구간 속 정수의 개폐 해석 무관성, 미지 상수의 유일해. 여기에 02-07만의
검사를 더한다: 문면의 함수와 검산 조건의 함수가 같은가, 02-08·기존 02-07 문항과 문면이 겹치지 않는가.
"""

from __future__ import annotations

import glob
import json
import re
from fractions import Fraction
from pathlib import Path

import pytest
import sympy
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

from whymath_backend.harness.p3_calculus1_diff_batch import run_p3_calculus1_diff_batch
from whymath_backend.l3.equivalent import p3_diff_skeleton_base as base
from whymath_backend.l3.equivalent.acceptance import evaluate_equivalent_candidate
from whymath_backend.l3.equivalent.generator import CandidateProblem
from whymath_backend.l3.equivalent.p3_diff_monotonicity_extremum_skeleton_generator import (
    P3DiffMonotonicityExtremumGenerator,
)
from whymath_backend.l3.equivalent.p3_diff_skeleton_base import SLOT_IDS, skeleton_of

pytestmark = pytest.mark.corpus_authoring

_SLOTS = ("basic", "applied", "diagnostic", "mastery_check")

_GEN = P3DiffMonotonicityExtremumGenerator
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
    out = tmp_path_factory.mktemp("monotonicity_bank") / "problems.jsonl"
    report = run_p3_calculus1_diff_batch(generators=(_GEN,), out_path=out)
    assert report.total_stored == report.total_requested == 48, report.to_json()
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
# ① 선언·구조
# ──────────────────────────────────────────────────────────────────────────
def test_generator_declares_exactly_the_four_empty_cells() -> None:
    assert _GEN.slots == _SLOTS
    assert set(_GEN.slot_difficulty) >= set(_SLOTS)
    assert _GEN.standard_code == "[12미적Ⅰ-02-07]"
    assert _GEN.concept_src_id == "H:12미적Ⅰ02-07"


@pytest.mark.parametrize("slot", sorted(set(SLOT_IDS) - set(_SLOTS)))
def test_a_slot_it_does_not_own_is_empty_not_an_error(slot: str) -> None:
    assert _GEN.items(slot) == ()


@pytest.mark.parametrize("slot", _SLOTS)
def test_twelve_items_per_owned_slot_over_at_least_four_frames(slot: str) -> None:
    items = _GEN.items(slot)
    assert len(items) == 12 and {i.slot for i in items} == {slot}
    assert len({i.frame_id for i in items}) >= 4
    assert len({skeleton_of(i.question_text) for i in items}) >= 8


def test_no_choice_or_misconception_is_attached() -> None:
    """오개념 유발 칸은 기존 승인 문항이 채웠다 — 이 생성기는 객관식·오답 귀속을 만들지 않는다."""
    for item in _items():
        assert not item.choices and not item.misconception_ids and not item.distractors


def test_problem_types_are_the_two_honest_ones() -> None:
    assert {i.problem_type_code for i in _items()} == {
        "ptype.optimize-extremum",
        "ptype.solve-for-unknown",
    }


def test_questions_and_conditions_are_unique_and_answers_are_scalar() -> None:
    items = _items()
    assert len({i.question_text for i in items}) == len(items)
    conds = [
        i.conditions if isinstance(i.conditions, str) else "&&".join(i.conditions) for i in items
    ]
    assert len(set(conds)) == len(conds)
    for item in items:
        assert re.fullmatch(r"-?\d+", item.answer_text), item.answer_text


def test_texts_are_clean_korean_without_code_notation_or_placeholders() -> None:
    for item in _items():
        for text in (item.question_text, item.explanation):
            assert "{" not in text and "}" not in text, text
            assert not _CODE_NOTATION.search(text), text
            assert not any(g in text for g in _GLYPHS), text
            assert not re.search(r"(?<![0-9A-Za-z])1x|\+ -|- -", text), text


# ──────────────────────────────────────────────────────────────────────────
# ② 수용 게이트
# ──────────────────────────────────────────────────────────────────────────
def test_no_review_status_and_unpublished(bank: tuple[Path, list[dict[str, object]]]) -> None:
    for row in _rows(bank):
        assert "review_status" not in row


def test_every_item_passes_the_acceptance_gate() -> None:
    for slot in _SLOTS:
        spec = _GEN.spec_for(slot)
        for candidate in _candidates(slot):
            verdict = evaluate_equivalent_candidate(
                spec,
                candidate.problem,
                provenance=candidate.provenance,
                conditions=candidate.conditions,
                answer_map=candidate.answer_map,
                answer_selection=candidate.answer_selection,
            )
            assert verdict.accepted, (candidate.problem.statement, verdict.reasons)


def test_gate_rejects_a_wrong_answer_for_every_item() -> None:
    """변별력 — 정답에 1을 더하면 전 문항이 Tier1에서 거부된다(게이트가 답을 실제로 본다)."""
    total = rejected = 0
    for slot in _SLOTS:
        spec = _GEN.spec_for(slot)
        for candidate in _candidates(slot):
            key = sorted(candidate.answer_map)[-1]
            broken = dict(candidate.answer_map)
            broken[key] = f"({broken[key]}) + 1"
            verdict = evaluate_equivalent_candidate(
                spec,
                candidate.problem,
                provenance=candidate.provenance,
                conditions=candidate.conditions,
                answer_map=broken,
                answer_selection=candidate.answer_selection,
            )
            total += 1
            rejected += int(not verdict.accepted)
    assert total == 48 and rejected == total


# ──────────────────────────────────────────────────────────────────────────
# ③ 문면 ↔ 검산 조건 정합 · 코퍼스 문면 중복 0
# ──────────────────────────────────────────────────────────────────────────
_TEXT_FN = re.compile(r"(?:f\(x\)|y) = (?P<expr>[^가-힣]+)")


def test_the_function_in_the_text_is_the_function_in_the_condition(
    bank: tuple[Path, list[dict[str, object]]],
) -> None:
    """문면이 보여 주는 함수와 검산 조건이 푸는 함수가 같다 — 둘이 어긋나면 정답이 맞아도 문항이 거짓이다."""
    checked = 0
    for row in _rows(bank):
        text = str(row["question_text"])
        cond = _verify(row)["conditions"]
        first = cond if isinstance(cond, str) else cond[0]
        match = _DERIV_COND.match(first)
        in_condition = sympy.sympify(match["f"] if match else first.removeprefix("y = "))
        in_text = _TEXT_FN.search(text)
        assert in_text is not None, text
        shown = parse_expr(
            in_text["expr"].replace("(단,", "").strip(),
            local_dict={"x": _X},
            transformations=(
                *standard_transformations,
                implicit_multiplication_application,
                convert_xor,
            ),
        )
        assert sympy.expand(shown - in_condition) == 0, (text, shown, in_condition)
        checked += 1
    assert checked == 48


def test_no_mathematical_entity_repeats_the_sibling_graph_shape_bank() -> None:
    """같은 틀 공장을 쓰는 02-08 문항과 검산 조건(같은 함수·같은 조건)이 한 건도 겹치지 않는다."""
    from whymath_backend.l3.equivalent.p3_diff_graph_shape_skeleton_generator import (
        P3DiffGraphShapeGenerator,
    )

    theirs = {
        base._condition_key(i)
        for s in P3DiffGraphShapeGenerator.slots
        for i in P3DiffGraphShapeGenerator.items(s)
    }
    mine = {base._condition_key(i) for i in _items()}
    assert mine and not (mine & theirs), sorted(mine & theirs)[:3]


def test_frame_labels_agree_with_the_extremum_kind_the_text_asks() -> None:
    """틀 이름의 극대·극소와 발문이 말하는 종류가 같다(이름과 내용이 어긋난 틀을 잡는다)."""
    checked = 0
    for item in _items():
        for token, words in (("local-max", ("극대", "극댓")), ("local-min", ("극소", "극솟"))):
            if token in item.frame_id:
                assert any(w in item.question_text for w in words), item.question_text
                checked += 1
    assert checked >= 8


def test_no_question_text_repeats_any_other_bank() -> None:
    """02-08·기존 02-07 문항과 문면이 한 글자도 같지 않다(실중복 0 — 중복 감사기의 T2 단언과 같은 기준)."""
    mine = {i.question_text for i in _items()}
    for path in glob.glob(str(_CORPUS_ROOT / "problem_bank_*" / "problems.jsonl")):
        if Path(path).parent.name == "problem_bank_p3_fill_v0":
            continue
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                assert json.loads(line).get("question_text") not in mine, path


# ──────────────────────────────────────────────────────────────────────────
# ④ 정답의 독립 재계산 (함숫값 비교 · 구간 속 정수 · 미지 상수 유일해)
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
    assert checked >= 12


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
    assert checked >= 8
    # ⓑ 평평한 임계점형은 은행 감사 1회차(P3-05, 2026-10-15)에서 진단 틀 `diag-increase-to-decrease-x`가
    # '미분 없이 풀림'으로 지적돼 극대 이후 감소 꼴 삼차 틀로 바뀌며 값형 문항에서 빠졌다(감사받은
    # 바이트 보존 — 되살리면 새 은행·새 감사다). 그래서 이 분기는 있으면 검증하되 하한은 요구하지 않는다.
    assert unknown_coef >= 4, (unknown_coef, flat_mixed)


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
        # 문면이 묻는 상수의 이름('상수 b의 값')이 정답이 가리키는 상수와 같다.
        asked = re.search(r"상수 ([a-z])의 값", text)
        assert asked is not None and int(str(amap[asked[1]])) == int(str(row["answer"])), text
        checked += 1
    assert checked >= 12


# ──────────────────────────────────────────────────────────────────────────
# ⑤ 결정론
# ──────────────────────────────────────────────────────────────────────────
def test_items_are_deterministic_across_cache_rebuilds() -> None:
    before = {slot: _GEN.items(slot) for slot in SLOT_IDS}
    for slot in SLOT_IDS:
        base._ITEM_CACHE.pop((_GEN, slot), None)
    assert before == {slot: _GEN.items(slot) for slot in SLOT_IDS}
