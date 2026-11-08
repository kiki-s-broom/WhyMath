"""골든 패스 문항 30개(golden/data/problems_linear_fn.json)의 모양 검사.

공유 계약의 문항 JSON 스키마를 7항목으로 확인한다.
① 정확히 30개 ② id가 LF-01~LF-30이고 중복 없음 ③ 7개 필드가 모두 있고 비어 있지 않음
④ answer_kind는 "number" 또는 "expression" ⑤ answer가 SymPy로 읽힌다
(number면 수, expression이면 자유 변수가 {x} 이하) ⑥ hint1에 answer 문자열이 그대로 들어 있지
않다(힌트가 답을 말하지 않는다) ⑦ stem의 `$` 개수가 짝수다(LaTeX를 열고 닫음).

정답이 수학적으로 맞는지는 이 테스트가 보지 않는다(S3 세션이 1회 검산하고 보고에 적었다).
"""

import json
from pathlib import Path
from typing import Any

import pytest
from sympy import Symbol
from sympy.parsing.sympy_parser import parse_expr

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROBLEMS_PATH = _REPO_ROOT / "golden" / "data" / "problems_linear_fn.json"

# 공유 계약의 필드 7개
_REQUIRED_FIELDS = ("id", "stem", "answer", "answer_kind", "hint1", "concept", "source")
_ANSWER_KINDS = {"number", "expression"}
_EXPECTED_COUNT = 30
_ALLOWED_SYMBOLS = {Symbol("x")}


def _load_problems() -> list[dict[str, Any]]:
    """문항 파일을 읽어 객체 배열로 돌려준다(배열이 아니면 실패)."""
    data = json.loads(_PROBLEMS_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, list), "문항 파일 최상위는 배열이어야 한다"
    return data


_PROBLEMS = _load_problems()


def _pid(problem: dict[str, Any]) -> str:
    """parametrize 표시 이름 — id가 없으면 '?'로 보여 준다."""
    return str(problem.get("id", "?"))


def test_exactly_30_problems() -> None:
    """① 문항은 정확히 30개다(31개 이상·29개 이하 모두 실패)."""
    assert len(_PROBLEMS) == _EXPECTED_COUNT


def test_ids_are_lf01_to_lf30_without_duplicates() -> None:
    """② id 집합이 LF-01~LF-30과 정확히 같고, 같은 id가 두 번 나오지 않는다."""
    ids = [p.get("id") for p in _PROBLEMS]
    expected = [f"LF-{i:02d}" for i in range(1, _EXPECTED_COUNT + 1)]
    assert len(ids) == len(set(ids)), f"중복 id: {sorted(i for i in ids if ids.count(i) > 1)}"
    assert sorted(ids) == expected


@pytest.mark.parametrize("problem", _PROBLEMS, ids=_pid)
def test_required_fields_present_and_non_empty(problem: dict[str, Any]) -> None:
    """③ 7개 필드가 모두 있고, 값이 공백만 있는 문자열이 아니다."""
    for field in _REQUIRED_FIELDS:
        assert field in problem, f"필드 없음: {field}"
        value = problem[field]
        assert isinstance(value, str), f"{field}는 문자열이어야 한다: {value!r}"
        assert value.strip(), f"{field}가 비어 있다"


@pytest.mark.parametrize("problem", _PROBLEMS, ids=_pid)
def test_answer_kind_is_number_or_expression(problem: dict[str, Any]) -> None:
    """④ answer_kind는 두 값 중 하나다."""
    assert problem["answer_kind"] in _ANSWER_KINDS


@pytest.mark.parametrize("problem", _PROBLEMS, ids=_pid)
def test_answer_parses_with_sympy(problem: dict[str, Any]) -> None:
    """⑤ answer가 SymPy로 읽힌다 — number는 자유 변수 없는 실수, expression은 변수가 x뿐."""
    expr = parse_expr(problem["answer"])
    if problem["answer_kind"] == "number":
        assert not expr.free_symbols, f"number인데 변수가 있다: {expr.free_symbols}"
        assert expr.is_real, f"number인데 실수가 아니다: {expr}"
    else:
        assert expr.free_symbols <= _ALLOWED_SYMBOLS, f"x 밖의 변수: {expr.free_symbols}"


@pytest.mark.parametrize("problem", _PROBLEMS, ids=_pid)
def test_hint_does_not_contain_answer(problem: dict[str, Any]) -> None:
    """⑥ hint1에 answer 문자열이 그대로 들어 있지 않다."""
    assert problem["answer"] not in problem["hint1"]


@pytest.mark.parametrize("problem", _PROBLEMS, ids=_pid)
def test_stem_latex_dollars_are_balanced(problem: dict[str, Any]) -> None:
    """⑦ stem의 `$` 개수가 짝수다(인라인 LaTeX를 열고 닫는다)."""
    assert problem["stem"].count("$") % 2 == 0
