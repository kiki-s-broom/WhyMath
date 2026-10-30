"""P3-84 — 숫자 나열 파서의 형태 검사 + P3-80 형태 오류 메시지에 조건 값이 실리지 않는다는 약속.

① `_parse_number_list`는 쉼표로 자른 항목을 `safe_sympify`로 읽은 뒤 `expr.is_number`를 **try 밖에서**
   조회했다. `safe_sympify`는 `True`→`bool`·`None`→`NoneType`·`[1]`→`list`·`()`→`tuple`·`2 == 3`→`bool`
   (파이썬 구조 비교)처럼 SymPy 식이 아닌 값을 돌려줄 수 있어, 그 조회가 `AttributeError`로 터져 네
   검증기(평균=중앙값·독립·조건부확률·내적) 밖으로 새어 나갔다. 이제 형태 검사(`_require_scalar`)를 try
   안에서 불러 판정 불가로 닫는다.
② P3-80의 `_ConditionShapeError` 메시지는 타입명만 싣는다(조건 원문·값을 싣지 않는다). 그 메시지는
   `fuzz_answer`가 `f"파싱 불가: {exc}"`로 reason에 그대로 옮기므로, 약속이 깨지면 조건 값이 판정
   사유로 밖에 나간다. 그 약속을 여기서 고정한다.

구성: ⓐ결함 입력 6꼴 × 검증기 4종이 예외 없이 판정 불가 ⓑ성공 방향 대조군(정상 숫자 나열의 값·판정
유지 — 과잉 거부 방어) ⓒ실제 은행 96행 전수 ⓓ침묵 실패 금지(타입명은 남고 값은 안 남음) ⓔ메시지 무값.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
import sympy

from whymath_backend.l3 import verify_answer as va
from whymath_backend.l3.equivalent.acceptance import _CONCEPTUAL_VERIFIERS
from whymath_backend.l3.equivalent.counterexample_fuzz import fuzz_answer
from whymath_backend.l3.verify_answer import (
    AnswerVerdict,
    _ConditionShapeError,
    _parse_condition,
    _parse_number_list,
    verify_conditional_equal,
    verify_dot_product_scalar,
    verify_events_independent,
    verify_mean_equals_median,
)

Verifier = Callable[[str | Sequence[str], str], AnswerVerdict]

# tests/backend/l3/<이 파일> → parents[3] = 레포 루트
_CONCEPTUAL_BANK = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "corpus"
    / "problem_bank_conceptual_v0"
    / "problems.jsonl"
)

# 숫자 나열 DSL을 소비하는 검증기 4종(acceptance 디스패치의 실제 answer_kind 이름).
NUMBER_LIST_VERIFIERS: dict[str, Verifier] = {
    "mean_equals_median": verify_mean_equals_median,
    "events_independent": verify_events_independent,
    "conditional_equal": verify_conditional_equal,
    "dot_product_scalar": verify_dot_product_scalar,
}

# ⓐ 결함 입력 — 각 꼴은 *항목 하나가* SymPy 식이 아닌 값으로 읽힌다(괄호 안은 그 값의 타입).
NON_EXPR_FORMS: dict[str, str] = {
    "진리값 단독(bool)": "True",
    "None 단독(NoneType)": "None",
    "리스트 단독(list)": "[1]",
    "빈 튜플 단독(tuple)": "()",
    "나열 중간 리스트(list)": "1,[2],3",
    "나열 중간 구조 비교(bool)": "1,2 == 3,4",
}


def test_dispatch_routes_the_four_kinds_to_these_verifiers() -> None:
    """실제 소비처(acceptance 디스패치)가 이 파일이 검사하는 함수를 그대로 부른다 — 대상 이탈 방지."""
    for kind, verifier in NUMBER_LIST_VERIFIERS.items():
        assert _CONCEPTUAL_VERIFIERS[kind] is verifier


@pytest.mark.parametrize("cond", list(NON_EXPR_FORMS.values()), ids=list(NON_EXPR_FORMS))
def test_non_expression_item_makes_list_unparseable(cond: str) -> None:
    assert _parse_number_list(cond) is None


@pytest.mark.parametrize("cond", list(NON_EXPR_FORMS.values()), ids=list(NON_EXPR_FORMS))
@pytest.mark.parametrize("kind", list(NUMBER_LIST_VERIFIERS))
def test_number_list_verifiers_close_as_unverifiable(kind: str, cond: str) -> None:
    verifier = NUMBER_LIST_VERIFIERS[kind]
    for claimed in ("0", "1"):
        verdict = verifier(cond, claimed)  # 종전에는 여기서 AttributeError
        assert verdict.state == "unverifiable"
        assert verdict.samples_checked == 0


# ──────────────────────────────────────────────────────────────────────────
# ⓑ 성공 방향 대조군 — 정상 숫자 나열은 값·판정이 그대로(과잉 거부 방어)
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("cond", "expected"),
    [
        ("1,2,3,4,9", [1, 2, 3, 4, 9]),
        ("1/12,2/12,6/12", [sympy.Rational(1, 12), sympy.Rational(1, 6), sympy.Rational(1, 2)]),
        ("-3, 0, 5", [-3, 0, 5]),
        ("sqrt(2),1", [sympy.sqrt(2), 1]),
        ("0.5,0.25,0.125", [sympy.Float(0.5), sympy.Float(0.25), sympy.Float(0.125)]),
    ],
)
def test_valid_number_lists_still_parse(cond: str, expected: list[object]) -> None:
    values = _parse_number_list(cond)
    assert values is not None
    assert [sympy.simplify(v - e) for v, e in zip(values, expected, strict=True)] == [0] * len(
        expected
    )


@pytest.mark.parametrize(
    "cond", ["x,1", "I,1", "1,(", ""], ids=["자유변수", "허수", "구문오류", "빈"]
)
def test_existing_rejections_unchanged(cond: str) -> None:
    """형태 검사 이전부터 있던 거부(비수치·비실수·파싱 실패·빈 목록)는 그대로 None."""
    assert _parse_number_list(cond) is None


def test_empty_items_are_still_skipped() -> None:
    """빈 항목은 종전대로 건너뛴다(`1,,` → 1개짜리 목록) — 형태 검사가 빈 항목에 닿지 않는다."""
    values = _parse_number_list("1,,")
    assert values is not None and len(values) == 1


@pytest.mark.parametrize(
    ("kind", "cond", "claimed", "state"),
    [
        ("mean_equals_median", "1,2,3,4,5", "1", "pass"),
        ("mean_equals_median", "1,2,3,4,9", "1", "fail"),
        ("events_independent", "1/2,1/2,1/4", "1", "pass"),
        ("events_independent", "1/12,1/12,0", "1", "fail"),
        ("conditional_equal", "1/12,2/12,6/12", "0", "pass"),
        ("conditional_equal", "1/12,2/12,6/12", "1", "fail"),
        ("dot_product_scalar", "1,1,1,1", "0", "pass"),
        ("dot_product_scalar", "1,2,3,4", "1", "fail"),
    ],
)
def test_valid_verdicts_unchanged(kind: str, cond: str, claimed: str, state: str) -> None:
    assert NUMBER_LIST_VERIFIERS[kind](cond, claimed).state == state


# ──────────────────────────────────────────────────────────────────────────
# ⓒ 실제 은행 — 네 answer_kind 행 전수가 수정 뒤에도 pass(은행 정답은 검증기 판정과 일치)
# ──────────────────────────────────────────────────────────────────────────
def test_conceptual_bank_number_list_rows_still_pass() -> None:
    """은행의 네 꼴 행(각 24건·총 96건)이 실제 디스패치로 전부 pass — 정상 나열을 거부하지 않는다.

    대상 0건은 공허한 통과이므로 실패로 친다. 수정 전후 판정 동일성(360건)은 main 사본 대조로 따로
    확인했다(PR 본문) — 이 테스트는 그중 *이 수정이 닿는* 96건을 상시 고정한다.
    """
    lines = [ln for ln in _CONCEPTUAL_BANK.read_text(encoding="utf-8").splitlines() if ln.strip()]
    seen: dict[str, int] = {kind: 0 for kind in NUMBER_LIST_VERIFIERS}
    for line in lines:
        record = json.loads(line)
        verify = record.get("verify") or {}
        kind = verify.get("answer_kind")
        if kind not in NUMBER_LIST_VERIFIERS:
            continue
        seen[kind] += 1
        verdict = _CONCEPTUAL_VERIFIERS[kind](verify["conditions"], record["answer"])
        assert verdict.state == "pass", (record["problem_id"], verdict)
    assert all(count > 0 for count in seen.values()), f"은행 꼴에 닿지 않음: {seen}"


# ──────────────────────────────────────────────────────────────────────────
# ⓓ 침묵 실패 금지 — 삼킨 형태 오류의 타입명은 남고 항목 값은 남지 않는다
# ──────────────────────────────────────────────────────────────────────────
def test_swallowed_item_shape_error_logs_type_name_without_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG, logger=va.logger.name):
        assert verify_mean_equals_median("7,[123457],9", "0").state == "unverifiable"
    text = "\n".join(r.getMessage() for r in caplog.records if r.name == va.logger.name)
    assert "_ConditionShapeError" in text
    assert "123457" not in text


# ──────────────────────────────────────────────────────────────────────────
# ⓔ P3-80 약속 — `_ConditionShapeError` 메시지(→ fuzz_answer reason)에 조건 값이 실리지 않는다
# ──────────────────────────────────────────────────────────────────────────
def test_fuzz_answer_reason_omits_condition_values() -> None:
    """리뷰 지적 그대로의 입력 — reason이 형태 오류 경로를 지났는지 확인한 뒤 값 부재를 본다."""
    verdict = fuzz_answer("1,2,3,4,9", {"x": "1"}, "unique")
    reason = verdict.reason or ""
    assert verdict.state == "unverifiable"
    # 형태 오류 경로를 지났는지(다른 사유로 바뀌면 아래 부재 단언이 공허해진다).
    assert "단일 식이 아님" in reason
    for leaked in ("1,2,3,4,9", "(1, 2, 3, 4, 9)", "1, 2, 3", "4, 9"):
        assert leaked not in reason


# 형태 검사의 절(분기)마다 — 좌·우변·단일 식. 값은 다른 숫자와 겹치지 않는 표식(1729·4096)이다.
_MARKED_CLAUSES: dict[str, str] = {
    "!= 좌변": "1729,4096 != x",
    "!= 우변": "x != 1729,4096",
    "== 좌변": "1729,4096 == x",
    "== 우변": "x == 1729,4096",
    "= 좌변": "1729,4096 = x",
    "= 우변": "x = 1729,4096",
    "단일 식 튜플": "1729, 4096",
    "단일 식 리스트": "[1729, 4096]",
}


@pytest.mark.parametrize("cond", list(_MARKED_CLAUSES.values()), ids=list(_MARKED_CLAUSES))
def test_shape_error_message_carries_type_name_only(cond: str) -> None:
    with pytest.raises(_ConditionShapeError) as info:
        _parse_condition(cond)
    message = str(info.value)
    assert "단일 식이 아님" in message
    assert "1729" not in message and "4096" not in message
    reason = fuzz_answer(cond, {"x": "1"}, "unique").reason or ""
    assert "단일 식이 아님" in reason
    assert "1729" not in reason and "4096" not in reason
