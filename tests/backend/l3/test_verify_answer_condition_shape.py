"""P3-80 — 단일 식이 아닌 조건(쉼표 나열 → 파이썬 튜플)을 자유 변수 수집 전에 형태 검사로 막는다.

`problem_bank_conceptual_v0` 360건 중 96건의 `verify.conditions`는 방정식이 아니라 개념형 문항의
**쉼표 구분 자료 목록 DSL**이다(평균=중앙값 `1,2,3,4,9` · 독립 `1/12,1/12,0` · 조건부확률
`1/12,2/12,6/12` · 내적 `1,1,1,1`). sympify는 이것을 파이썬 `tuple`로 돌려주는데, `_parse_condition`의
마지막 분기가 그 튜플을 잔차(`sympy.Expr`)인 것처럼 그대로 돌려줘 호출부가 `.free_symbols`에서
`AttributeError`로 터졌다(근 선택 유도·근 선택·근 집계·실근 개수·조건 관계). 더 나쁜 자리도 있었다 —
`classify_solvability`는 상수 튜플을 "0 아닌 상수"로 읽어 **해 없음을 확정**했다(판정 불가여야 할
자리의 틀린 판정). 함수식 검증기 5종(극값 개수·일대일·극한=함숫값·미분가능·급수 수렴)은
`_parse_condition`을 거치지 않고 같은 꼴로 터졌다.

이 파일은 ①96건의 네 꼴을 픽스처로 고정해 모든 경로가 예외 없이 판정 불가로 닫히는지 ②형태 검사의
절(분기)마다 그 절이 없으면 통과하는 입력을 두고 ③성공 방향 대조군(정상 조건의 종전 판정 유지)과
④침묵 실패 금지(예외 타입명이 로그에 남고 조건 값은 남지 않음)를 함께 본다.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.l3 import verify_answer as va
from whymath_backend.l3.equivalent.counterexample_fuzz import fuzz_answer
from whymath_backend.l3.verify_answer import (
    _ConditionShapeError,
    _parse_condition,
    classify_solvability,
    condition_relation,
    derive_selected_root,
    verify_answer,
    verify_extremum_count,
    verify_is_differentiable,
    verify_is_one_to_one,
    verify_limit_equals_value,
    verify_real_root_count,
    verify_root_aggregate,
    verify_root_selection,
    verify_series_converges,
)

# tests/backend/l3/<이 파일> → parents[3] = 레포 루트
_CONCEPTUAL_BANK = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "corpus"
    / "problem_bank_conceptual_v0"
    / "problems.jsonl"
)

# 96건의 네 꼴(실제 은행 레코드에서 옮긴 값) — (단원·answer_kind, 조건).
TUPLE_FORMS: dict[str, str] = {
    "STAT-MEAN-MEDIAN·mean_equals_median(N,N,N,N,N)": "1,2,3,4,9",
    "PROB-INDEPENDENCE·events_independent(N/N,N/N,N)": "1/12,1/12,0",
    "PROB-CONDITIONAL·conditional_equal(N/N,N/N,N/N)": "1/12,2/12,6/12",
    "VEC-DOT-PRODUCT·dot_product_scalar(N,N,N,N)": "1,1,1,1",
}

# 은행 꼴 분류용 — 숫자·분수만으로 된 쉼표 나열(2개 이상).
_COMMA_DSL = re.compile(r"\s*-?\d+(/\d+)?(\s*,\s*-?\d+(/\d+)?)+\s*")


# ──────────────────────────────────────────────────────────────────────────
# ① 96건의 네 꼴 — 모든 경로가 예외 없이 판정 불가
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("cond", list(TUPLE_FORMS.values()), ids=list(TUPLE_FORMS))
@pytest.mark.parametrize("selection", ["unique", "largest", "smallest"])
def test_derive_selected_root_returns_none_for_tuple_forms(cond: str, selection: str) -> None:
    """종전 `AttributeError('tuple' … 'free_symbols')` → 판정 불가 None(반환 계약 str | None 유지)."""
    assert derive_selected_root(cond, selection) is None
    assert derive_selected_root([cond], selection) is None


@pytest.mark.parametrize("cond", list(TUPLE_FORMS.values()), ids=list(TUPLE_FORMS))
def test_parse_condition_raises_shape_error_for_tuple_forms(cond: str) -> None:
    """원인 지점 — 마지막 분기가 튜플을 잔차로 돌려주지 않는다(`ValueError` 하위형)."""
    with pytest.raises(_ConditionShapeError):
        _parse_condition(cond)
    assert issubclass(_ConditionShapeError, ValueError)


@pytest.mark.parametrize("cond", list(TUPLE_FORMS.values()), ids=list(TUPLE_FORMS))
def test_every_equation_path_closes_as_undecidable(cond: str) -> None:
    """`_parse_condition`을 쓰는 형제 경로 전부 — 예외 대신 판정 불가(unverifiable·undecidable·None)."""
    amap = {"x": "1"}
    assert verify_answer(cond, amap).state == "unverifiable"
    assert verify_root_selection(cond, amap, "unique").state == "unverifiable"
    assert verify_root_aggregate(cond, "1", "sum").state == "unverifiable"
    assert verify_real_root_count(cond, "1").state == "unverifiable"
    assert condition_relation(cond) is None
    # counterexample_fuzz 는 (SympifyError·ValueError·TypeError)만 받는다 — 하위형이라 닫힌다.
    assert fuzz_answer(cond, amap, "unique").state == "unverifiable"


@pytest.mark.parametrize("cond", list(TUPLE_FORMS.values()), ids=list(TUPLE_FORMS))
def test_classify_solvability_no_longer_asserts_no_solution(cond: str) -> None:
    """종전에는 상수 튜플을 '0 아닌 상수'로 읽어 no_solution(확정 판정)이었다 — 판정 불가여야 한다."""
    verdict = classify_solvability(cond)
    assert verdict.state == "undecidable"


@pytest.mark.parametrize("cond", list(TUPLE_FORMS.values()), ids=list(TUPLE_FORMS))
@pytest.mark.parametrize(
    "verifier",
    [
        verify_extremum_count,
        verify_is_one_to_one,
        verify_limit_equals_value,
        verify_is_differentiable,
        verify_series_converges,
    ],
    ids=["extremum", "one_to_one", "limit", "differentiable", "series"],
)
def test_function_verifiers_close_as_unverifiable(cond: str, verifier: Any) -> None:
    """`_parse_condition`을 거치지 않는 함수식 검증기 5종 — 각자의 형태 검사로 닫힌다."""
    for claimed in ("0", "1", "2"):
        verdict = verifier(cond, claimed)
        assert verdict.state == "unverifiable"
        assert "단일 식이 아님" in (verdict.reason or "")


def test_conceptual_bank_comma_rows_all_close_as_none() -> None:
    """은행의 쉼표 조건 행 전수 — 실제 호출 꼴 `derive_selected_root(conds, sel or "unique")`이 None.

    쉼표가 든 조건은 전부 숫자·분수 DSL 꼴이어야 한다(위 네 꼴 밖의 새 꼴이 생기면 여기서 드러난다).
    대상 0건은 공허한 통과이므로 실패로 친다. 쉼표 없는 정상 행(264건)은 sympy 풀이가 무거워 이
    테스트에서 돌리지 않는다 — 그 행의 출력 불변은 P3-80 전 은행 대조(main 사본 대비)로 확인했다.
    """
    lines = [ln for ln in _CONCEPTUAL_BANK.read_text(encoding="utf-8").splitlines() if ln.strip()]
    comma_rows = 0
    for line in lines:
        verify = json.loads(line).get("verify") or {}
        conds = verify.get("conditions")
        if not (isinstance(conds, str) and "," in conds):
            continue
        comma_rows += 1
        assert _COMMA_DSL.fullmatch(conds), f"새 쉼표 꼴: {conds!r}"
        assert derive_selected_root(conds, verify.get("answer_selection") or "unique") is None
    assert comma_rows > 0, "쉼표 조건 행 0건 — 픽스처가 은행 꼴에 닿지 않는다"


# ──────────────────────────────────────────────────────────────────────────
# ② 형태 검사의 절마다 — 그 절이 없으면 통과(또는 다른 예외)하는 입력
# ──────────────────────────────────────────────────────────────────────────
# 각 입력은 해당 절이 빠지면 `_ConditionShapeError`가 아니라 TypeError(튜플 뺄셈) 또는 튜플 반환이
# 된다. 분기: `!=`·`==`·`=`의 좌·우변, 등호 없는 단일 식(튜플·리스트).
SHAPE_CLAUSES: dict[str, str] = {
    "!= 좌변 튜플": "1,2 != x",
    "!= 우변 튜플": "x != 1,2",
    "== 좌변 튜플": "1,2 == x",
    "== 우변 튜플": "x == 1,2",
    "= 좌변 튜플": "1,2 = x",
    "= 우변 튜플": "x = 1,2",
    "단일 식 튜플": "x, 1",
    "단일 식 리스트": "[x, 1]",
}


@pytest.mark.parametrize("cond", list(SHAPE_CLAUSES.values()), ids=list(SHAPE_CLAUSES))
def test_each_shape_clause_raises_shape_error(cond: str) -> None:
    with pytest.raises(_ConditionShapeError):
        _parse_condition(cond)
    assert derive_selected_root(cond, "unique") is None


# ──────────────────────────────────────────────────────────────────────────
# ③ 성공 방향 대조군 — 정상 조건은 종전 판정 그대로
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("cond", "expected_op"),
    [
        ("x**2 - 1", "=="),
        ("x = 2", "=="),
        ("x**2 == 4", "=="),
        ("x != 1", "!="),
        ("x > 1", ">"),
        ("Eq(x, 3)", "=="),
    ],
)
def test_scalar_conditions_still_parse(cond: str, expected_op: str) -> None:
    residual, op = _parse_condition(cond)
    assert op == expected_op
    assert residual.free_symbols  # 스칼라 식 — 자유 변수 수집이 그대로 된다


@pytest.mark.parametrize(
    ("cond", "selection", "expected"),
    [
        ("x**2 - 4 = 0", "largest", "2"),
        ("x**2 - 4 = 0", "smallest", "-2"),
        ("3*x - 4 = 0", "unique", "4/3"),
        ("x**2 - 4 = 0", "unique", None),  # 다근인데 unique — 종전대로 None
    ],
)
def test_derive_selected_root_unchanged_for_equations(
    cond: str, selection: str, expected: str | None
) -> None:
    assert derive_selected_root(cond, selection) == expected


def test_classify_and_function_verifiers_unchanged_for_valid_inputs() -> None:
    assert classify_solvability("x**2 + 1 = 0").state == "no_solution"
    assert classify_solvability("2*x - 6 = 0").state == "unique"
    assert verify_extremum_count("x**3 - 3*x", "2").state == "pass"
    assert verify_is_one_to_one("x**3", "1").state == "pass"
    assert verify_series_converges("1/n**2", "1").state == "pass"
    # 함수식 검증기의 기존 등식 거부 사유는 형태 검사보다 먼저 그대로 나온다.
    rel = verify_extremum_count("Eq(x**2, 1)", "1")
    assert rel.state == "unverifiable" and "등식/부등식 아님" in (rel.reason or "")


# ──────────────────────────────────────────────────────────────────────────
# ④ 침묵 실패 금지 — 삼킨 예외의 타입명은 남고 조건 값은 남지 않는다
# ──────────────────────────────────────────────────────────────────────────
def test_swallowed_shape_error_logs_type_name_without_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG, logger=va.logger.name):
        assert derive_selected_root("7,8,9,123457", "unique") is None
    text = "\n".join(r.getMessage() for r in caplog.records if r.name == va.logger.name)
    assert "_ConditionShapeError" in text
    assert "123457" not in text
