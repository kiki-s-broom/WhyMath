"""[12미적Ⅰ-02-08] 파생 판정 저작 형태 규칙(P3-24) — 진리표·배선·절별 반례·범위 밖 불변.

판정 입력은 P3-21 프로브 fixture 26행(13형태 × 정답·오답)이다. 게이트 결정(안 나)이 요구하는 허용/거부
집합을 **그대로** 동결한다:

  허용 7형태  A1 · A2 · A2d · B1 · B2 · C1 · C2
  거부 6형태  A3 · A4 · A5(제외 3) · B3 · C3(저작 규칙 필수 2) · C4(제외 1)

절별 반례(`TestClauseCounterexamples`)는 규칙의 각 정규식 절이 **그 절만의 입력**으로 밟히는지 본다 —
절을 지웠을 때 GREEN이면 가드가 관대한 게 아니라 픽스처가 그 절에 닿지 않은 것이다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.l1.problem_bank.derived_form_rules import (
    DERIVED_STANDARD_CODE,
    derived_form_violations,
)
from whymath_backend.l1.problem_bank.populate import ProblemCorpusError, _record_from_line

_FIXTURES = Path(__file__).resolve().parents[1] / "harness" / "fixtures"

_ACCEPTED_FORMS = {"A1", "A2", "A2d", "B1", "B2", "C1", "C2"}
_REJECTED_FORMS = {
    "A3": "A3-boundary-inclusion",
    "A4": "A4-interval-notation",
    "A5": "A5-bare-expression-condition",
    "B3": "B3-require-answer-selection",
    "C3": "C3-pin-extremum-x",
    "C4": "C3-pin-extremum-x",
}


def _rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in ("p3_21_correct.jsonl", "p3_21_wrong.jsonl"):
        for line in (_FIXTURES / name).read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _violations(row: dict[str, Any]) -> list[str]:
    verify = row.get("verify") or {}
    return [
        v.rule
        for v in derived_form_violations(
            standard_codes=row["achievement_standard_codes"],
            question_text=row["question_text"],
            answer=row["answer"],
            conditions=verify.get("conditions"),
            answer_map=verify.get("answer_map"),
            answer_selection=verify.get("answer_selection"),
        )
    ]


def _check(
    *,
    question: str,
    answer: str = "2",
    conditions: Any = "3*x**2 - 6*x = 0",
    answer_map: dict[str, str] | None = None,
    selection: str | None = None,
    codes: tuple[str, ...] = (DERIVED_STANDARD_CODE,),
) -> list[str]:
    return [
        v.rule
        for v in derived_form_violations(
            standard_codes=list(codes),
            question_text=question,
            answer=answer,
            conditions=conditions,
            answer_map={"x": "2"} if answer_map is None else answer_map,
            answer_selection=selection,
        )
    ]


class TestTruthTableOverTheProbeFixtures:
    def test_fixture_covers_all_thirteen_forms_in_both_roles(self) -> None:
        rows = _rows()
        assert len(rows) == 26
        assert {r["probe_form"] for r in rows} == _ACCEPTED_FORMS | set(_REJECTED_FORMS)

    @pytest.mark.parametrize("form", sorted(_ACCEPTED_FORMS))
    def test_possible_forms_are_accepted_in_both_roles(self, form: str) -> None:
        rows = [r for r in _rows() if r["probe_form"] == form]
        assert len(rows) == 2
        for row in rows:
            assert _violations(row) == [], (form, row["probe_role"])

    @pytest.mark.parametrize(("form", "rule"), sorted(_REJECTED_FORMS.items()))
    def test_excluded_and_required_rule_forms_are_rejected_in_both_roles(
        self, form: str, rule: str
    ) -> None:
        rows = [r for r in _rows() if r["probe_form"] == form]
        assert len(rows) == 2
        for row in rows:
            assert rule in _violations(row), (form, row["probe_role"], _violations(row))

    def test_the_rejected_set_is_exactly_the_decision_not_a_superset(self) -> None:
        """거부 집합 = 결정문의 6형태. 허용 7형태를 더 거부하면 문항화 가능 범위가 몰래 줄어든다."""
        rejected = {r["probe_form"] for r in _rows() if _violations(r)}
        assert rejected == set(_REJECTED_FORMS)


class TestScopeIsOnlyDerivedStandard:
    def test_a_rejected_form_is_untouched_when_the_standard_code_is_absent(self) -> None:
        b3 = next(r for r in _rows() if r["probe_form"] == "B3")
        assert _violations(b3) != []
        b3_other = {**b3, "achievement_standard_codes": ["[12미적Ⅰ-02-07]"]}
        assert _violations(b3_other) == []

    def test_no_codes_at_all_is_out_of_scope(self) -> None:
        assert _check(question="극댓값을 갖는 x좌표를 구하시오.", codes=()) == []


class TestClauseCounterexamples:
    """각 절을 **그 절만** 밟는 반례 — 절을 지우면 이 테스트가 RED가 된다."""

    # ── 규칙 B3 ──
    def test_b3_fires_on_the_standard_siot_spelling_of_the_maximum_value(self) -> None:
        """'극댓값'(사이시옷)을 빠뜨리면 표준 표기가 구별 요구로 읽히지 않는다 — 처음 구현의 실제 결함."""
        assert _check(question="극댓값을 갖는 x좌표를 구하시오.") == ["B3-require-answer-selection"]
        assert _check(question="극솟값을 갖는 x좌표를 구하시오.") == ["B3-require-answer-selection"]
        assert _check(question="극대가 되는 x좌표를 구하시오.") == ["B3-require-answer-selection"]

    def test_b3_is_satisfied_by_a_valid_selection_only(self) -> None:
        q = "극댓값을 갖는 x좌표를 구하시오."
        assert _check(question=q, selection="smallest") == []
        assert _check(question=q, selection="largest") == []
        assert _check(question=q, selection="bogus") == ["B3-require-answer-selection"]

    def test_b3_does_not_fire_when_extremum_kind_is_not_distinguished(self) -> None:
        """'극값을 갖는 x좌표 중 큰 값'은 극대·극소를 구별하지 않는다(프로브 B1 — 가능)."""
        assert _check(question="극값을 갖는 x좌표 중 큰 값을 구하시오.") == []

    # ── 규칙 C3 ──
    def test_c3_requires_x_pinned_in_the_question(self) -> None:
        pinned = "x=2에서의 극솟값을 구하시오."
        unpinned = "극솟값을 구하시오."
        amap = {"x": "2", "y": "-2"}
        assert _check(question=pinned, answer="-2", answer_map=amap) == []
        assert _check(question=unpinned, answer="-2", answer_map=amap) == ["C3-pin-extremum-x"]

    def test_c3_requires_x_in_the_answer_map_even_when_pinned_in_text(self) -> None:
        q = "x=2에서의 극솟값을 구하시오."
        assert _check(question=q, answer="-2", answer_map={"y": "-2"}) == ["C3-pin-extremum-x"]

    def test_c3_pin_accepts_spaces_around_the_equals_sign(self) -> None:
        assert _check(question="x = 2에서의 극솟값", answer="-2", answer_map={"x": "2"}) == []

    def test_c3_pin_requires_a_numeric_constant_not_a_symbol(self) -> None:
        """'x = a에서의 극솟값'은 x를 상수로 못 박지 않는다 — 숫자가 아니면 고정으로 계상하지 않는다."""
        out = _check(question="x = a에서의 극솟값을 구하시오.", answer="-2", answer_map={"x": "2"})
        assert out == ["C3-pin-extremum-x"]

    def test_c3_pin_is_not_triggered_by_a_longer_identifier_ending_in_x(self) -> None:
        """'ax=2'의 x는 변수 x가 아니다 — 앞에 영문자가 붙은 식별자는 고정으로 읽지 않는다."""
        out = _check(question="ax=2일 때 극솟값을 구하시오.", answer="-2", answer_map={"x": "2"})
        assert out == ["C3-pin-extremum-x"]

    def test_c3_a_point_answer_is_rejected_unless_x_is_pinned(self) -> None:
        amap = {"x": "2", "y": "-2"}
        assert _check(question="극솟점을 구하시오.", answer="(2, -2)", answer_map=amap) == [
            "C3-pin-extremum-x"
        ]
        assert (
            _check(question="x=2일 때 극솟점을 구하시오.", answer="(2, -2)", answer_map=amap) == []
        )

    def test_c3_does_not_fire_for_the_x_coordinate_question(self) -> None:
        """'극댓값을 갖는 x좌표'는 값·점이 아니라 x좌표를 묻는다 — C3이 아니라 B3 소관이다."""
        out = _check(question="극댓값을 갖는 x좌표를 구하시오.", selection="smallest")
        assert out == []

    def test_c3_function_definition_alone_does_not_count_as_pinning(self) -> None:
        """본문의 `f(x) = x^3 …` 정의가 'x = …'로 오독돼 고정으로 계상되면 안 된다."""
        q = "삼차함수 f(x) = x^3 - 3x^2 + 2의 극솟값을 구하시오."
        assert _check(question=q, answer="-2", answer_map={"x": "2", "y": "-2"}) == [
            "C3-pin-extremum-x"
        ]

    # ── 제외 A4 ──
    def test_a4_catches_closed_open_and_infinite_interval_answers(self) -> None:
        q = "증가하는 구간을 구하시오."
        for ans in ("[2, 5]", "(0, 2]", "(-∞, 0]", "[2, ∞)", "(-∞, 0], [2, ∞)"):
            assert "A4-interval-notation" in _check(question=q, answer=ans), ans

    def test_a4_catches_an_open_interval_that_looks_like_a_coordinate_pair(self) -> None:
        """(0, 2)는 ∞·대괄호가 없어 모양만으로는 좌표쌍과 같다 — 본문이 '구간'을 묻는지로 가른다."""
        assert "A4-interval-notation" in _check(
            question="감소하는 구간을 구하시오.", answer="(0, 2)"
        )

    def test_a4_question_wording_alone_is_enough(self) -> None:
        assert "A4-interval-notation" in _check(
            question="증가 구간을 구간 기호로 쓰시오.", answer="x"
        )

    def test_a4_does_not_fire_on_a_single_integer_in_the_interval(self) -> None:
        assert _check(question="증가하는 구간에 속하는 정수 하나를 구하시오.", answer="3") == []

    # ── 제외 A3 ──
    def test_a3_catches_boundary_wording_and_inequality_answers(self) -> None:
        assert "A3-boundary-inclusion" in _check(question="경계 포함 여부를 쓰시오.", answer="포함")
        assert "A3-boundary-inclusion" in _check(question="닫힌 구간으로 쓰시오.", answer="x")
        assert "A3-boundary-inclusion" in _check(question="시작점을 쓰시오.", answer="x >= 2")
        assert "A3-boundary-inclusion" in _check(question="시작점을 쓰시오.", answer="x ≤ 0")

    # ── 제외 A5 ──
    def test_a5_flags_any_condition_without_a_relation_operator(self) -> None:
        assert "A5-bare-expression-condition" in _check(
            question="증가 구간 소속 정수", answer="3", conditions="3*x**2 - 6*x"
        )

    def test_a5_inspects_every_condition_in_a_list(self) -> None:
        assert "A5-bare-expression-condition" in _check(
            question="증가 구간 소속 정수",
            answer="3",
            conditions=["3*x**2 - 6*x > 0", "3*x**2 - 6*x"],
        )
        assert (
            _check(
                question="증가 구간 소속 정수",
                answer="3",
                conditions=["3*x**2 - 6*x > 0", "x >= 0"],
            )
            == []
        )

    def test_a5_accepts_every_relation_operator_spelling(self) -> None:
        for cond in ("p = 0", "p < 0", "p > 0", "p <= 0", "p >= 0", "p ≤ 0", "p ≥ 0", "p != 0"):
            assert _check(question="증가 구간 소속 정수", answer="3", conditions=cond) == [], cond

    def test_a5_missing_verify_is_not_a_condition_violation(self) -> None:
        """verify 부재(조건 없음)는 A5가 아니다 — 문자열 규칙만 적용된다."""
        assert (
            _check(question="증가 구간 소속 정수", answer="3", conditions=None, answer_map={}) == []
        )


def _loadable_row(form: str, role: str = "correct") -> dict[str, Any]:
    """프로브 행을 적재 가능한 코퍼스 행으로 바꾼다 — 프로브 전용 키를 떼고 `subject`를 실제 코퍼스 값으로.

    프로브 fixture는 `corpus_reverify`(자체 로더) 전용이라 `populate`를 거친 적이 없다. `subject`가
    '미적분Ⅰ'(과목 표기)인데 `Problem` 스키마의 enum은 '미적분'이라 그대로는 파싱 전에 막힌다 — 이 규칙과
    무관한 fixture 표기 차이이므로 여기서만 맞춘다(fixture 자체는 P3-21 동결 대상이라 건드리지 않는다).
    """
    row = next(r for r in _rows() if r["probe_form"] == form and r["probe_role"] == role)
    loadable = {k: v for k, v in row.items() if not k.startswith("probe_")}
    loadable["subject"] = "미적분"
    return loadable


class TestWiredIntoTheCorpusParse:
    """집행 지점 — 규칙이 `populate._record_from_line`(적재 전 파싱)에서 실제로 부려진다."""

    @pytest.mark.parametrize("form", sorted(_ACCEPTED_FORMS))
    def test_allowed_forms_parse(self, form: str) -> None:
        record = _record_from_line(_loadable_row(form))
        assert record.slug

    @pytest.mark.parametrize("form", sorted(_REJECTED_FORMS))
    def test_rejected_forms_raise_before_any_database_work(self, form: str) -> None:
        with pytest.raises(ProblemCorpusError) as info:
            _record_from_line(_loadable_row(form))
        message = str(info.value)
        assert "G-p321-derived-form-disposition" in message
        assert _REJECTED_FORMS[form] in message
        assert "slug=" in message  # 어느 문항이 막혔는지 지목한다

    def test_the_same_row_loads_once_the_standard_code_is_changed(self) -> None:
        """집행이 02-08 한정임을 파싱 경로에서도 확인한다 — 코드를 바꾸면 같은 본문이 통과한다."""
        row = _loadable_row("B3")
        with pytest.raises(ProblemCorpusError):
            _record_from_line(row)
        assert _record_from_line({**row, "achievement_standard_codes": ["[12미적Ⅰ-02-07]"]})
