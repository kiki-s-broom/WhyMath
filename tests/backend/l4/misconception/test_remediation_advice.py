"""후보 → 교정 전략 조회(P3-06) — 사다리 칸에 맞는 내용이 나오고, 공백은 공백으로 드러나는가.

핵심 주장 세 가지를 실행해서 확인한다:
  ① 사다리 임계는 이 모듈이 다시 적지 않는다 — `l2.remediation_policy.select_rung`을 **같은 함수**로 부른다.
     정책 표의 사다리를 옮기면 조회 결과도 따라 움직인다(주입으로 확인).
  ② 조회 결과는 세 상태가 서로 다른 글자다: ADVICE / NO_ESCALATION / NO_STRATEGY.
  ③ 사다리 칸과 교정표의 필드는 일대일이다 — 칸이 늘면 데이터도 늘어야 하고, 어긋나면 여기서 깨진다.
"""

from __future__ import annotations

import pytest

from whymath_backend.l1.misconception import wrong_answer_tables as tables
from whymath_backend.l2.remediation_policy import (
    REMEDIATION_POLICY_V1,
    EscalationRung,
    RemediationPolicyTable,
)
from whymath_backend.l4.misconception import remediation_advice as advice_mod
from whymath_backend.l4.misconception.remediation_advice import (
    RUNG_CONTENT_FIELD,
    AdviceOutcome,
    advise,
    advise_for_rung,
    resolve_row,
)
from whymath_backend.schema.wrong_answer_remediation import RemediationRow

_SEATED = (
    "power-rule-step-omitted",
    "product-rule-naive",
    "critical-point-implies-extremum",
    "continuity-implies-differentiability",
    "extremum-max-min-confused",
    "extremum-value-vs-point-confused",
)


class TestRungFieldMapping:
    def test_every_active_rung_maps_to_a_table_field_and_vice_versa(self) -> None:
        """③ 사다리의 활성 칸 집합 == 교정표가 가진 칸별 필드 집합."""
        active = {r for r in EscalationRung if r is not EscalationRung.NONE}
        assert set(RUNG_CONTENT_FIELD) == active
        row_fields = set(RemediationRow.model_fields)
        assert set(RUNG_CONTENT_FIELD.values()) <= row_fields

    def test_ladder_rungs_are_all_covered_by_the_policy_table(self) -> None:
        """정책 표의 사다리가 내는 칸이 전부 매핑에 있다 — 표에만 있고 데이터엔 없는 칸을 막는다."""
        ladder = {rung for _, rung in REMEDIATION_POLICY_V1.escalation_ladder}
        assert ladder <= set(RUNG_CONTENT_FIELD)


class TestAdviceStates:
    @pytest.mark.parametrize("kebab", _SEATED)
    @pytest.mark.parametrize(
        ("count", "rung", "field"),
        [
            (2, EscalationRung.CORRECTIVE_EXPLANATION, "corrective_explanation"),
            (3, EscalationRung.EASIER_PROBLEM, "easier_problem"),
            (4, EscalationRung.PREREQUISITE_CONCEPT, "prerequisite_concept"),
            (9, EscalationRung.PREREQUISITE_CONCEPT, "prerequisite_concept"),
        ],
    )
    def test_each_rung_returns_exactly_its_own_content(
        self, kebab: str, count: int, rung: EscalationRung, field: str
    ) -> None:
        result = advise(kebab, count)
        assert result.outcome is AdviceOutcome.ADVICE
        assert result.rung is rung
        filled = {
            name
            for name in ("corrective_explanation", "easier_problem", "prerequisite_concept")
            if getattr(result, name) is not None
        }
        assert filled == {field}, "칸에 해당하는 내용 하나만 채워져야 한다"
        assert result.mis_id is not None and result.authoring_status == "draft"

    @pytest.mark.parametrize("count", [0, 1])
    def test_below_the_first_rung_is_no_escalation_not_missing_strategy(self, count: int) -> None:
        """반복이 사다리 첫 칸(2회)에 못 미치면 강도를 올리지 않는다 — 교정표 공백과 구별된다."""
        result = advise("power-rule-step-omitted", count)
        assert result.outcome is AdviceOutcome.NO_ESCALATION
        assert result.rung is EscalationRung.NONE
        assert result.mis_id is None

    def test_kebab_without_a_table_row_is_reported_as_a_gap(self) -> None:
        """칸이 올라갔는데 교정표에 행이 없으면 NO_STRATEGY — 빈 값으로 뭉개지 않는다."""
        result = advise("distribution-over-power", 3)
        assert result.outcome is AdviceOutcome.NO_STRATEGY
        assert result.rung is EscalationRung.EASIER_PROBLEM
        assert result.easier_problem is None
        # 존재하지 않는 id도 같은 글자다 — 오타가 '반복 없음'으로 위장되지 않는다.
        assert advise("no-such-kebab", 3).outcome is AdviceOutcome.NO_STRATEGY

    def test_the_three_states_are_distinct_values(self) -> None:
        assert len({o.value for o in AdviceOutcome}) == 3

    def test_negative_count_is_refused_by_the_policy_function(self) -> None:
        with pytest.raises(ValueError):
            advise("power-rule-step-omitted", -1)


class TestRowResolution:
    def test_shared_kebab_uses_the_canonical_mis_id_row(self) -> None:
        """product-rule-naive에는 M0075·M0672가 걸려 있다 — canonical(M0075)의 행을 쓴다."""
        row = resolve_row("product-rule-naive")
        assert row is not None and row.mis_id == "M0075"

    def test_both_shared_mis_ids_have_their_own_rows_so_neither_is_lost(self) -> None:
        assert tables.remediation_row_for_mis_id("M0075") is not None
        assert tables.remediation_row_for_mis_id("M0672") is not None

    def test_when_canonical_is_unselected_the_first_row_in_sorted_order_is_used(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """동률이라 canonical이 없어도 결정론적으로 같은 행을 쓴다(임의 선택 아님)."""
        monkeypatch.setattr(advice_mod, "canonical_mis_id_for_kebab", lambda _k: None)
        row = resolve_row("product-rule-naive")
        assert row is not None and row.mis_id == "M0075"  # 정렬 순 첫 번째 행 있는 M-id


class TestPolicyIsNotCopied:
    def test_moving_the_ladder_moves_the_advice(self) -> None:
        """① 사다리 임계 사본이 없다는 증거 — 정책 표를 한 칸 옮기면 같은 횟수의 처방이 바뀐다."""
        shifted = RemediationPolicyTable(
            escalation_ladder=(
                (5, EscalationRung.PREREQUISITE_CONCEPT),
                (4, EscalationRung.EASIER_PROBLEM),
                (3, EscalationRung.CORRECTIVE_EXPLANATION),
            )
        )
        assert shifted != REMEDIATION_POLICY_V1, "주입 미적용 — 테스트 무효"
        assert advise("power-rule-step-omitted", 2).rung is EscalationRung.CORRECTIVE_EXPLANATION
        assert advise("power-rule-step-omitted", 2, shifted).outcome is AdviceOutcome.NO_ESCALATION
        assert advise("power-rule-step-omitted", 4, shifted).rung is EscalationRung.EASIER_PROBLEM

    def test_module_has_no_ladder_numbers_of_its_own(self) -> None:
        """이 모듈 소스에 사다리 임계 리터럴(2·3·4회)이 없다 — 정책 모듈이 정본이다."""
        import ast
        import inspect

        tree = ast.parse(inspect.getsource(advice_mod))
        ints = {
            n.value
            for n in ast.walk(tree)
            if isinstance(n, ast.Constant)
            and isinstance(n.value, int)
            and not isinstance(n.value, bool)
        }
        assert not ({2, 3, 4} & ints), f"사다리 숫자 사본 의심: {sorted({2, 3, 4} & ints)}"

    def test_advise_for_rung_skips_the_policy_when_the_rung_is_already_known(self) -> None:
        result = advise_for_rung("extremum-max-min-confused", EscalationRung.EASIER_PROBLEM)
        assert result.outcome is AdviceOutcome.ADVICE and result.easier_problem is not None


class TestAuthoringStatusIsCarriedNotFiltered:
    def test_draft_rows_are_returned_with_their_status(self) -> None:
        """draft를 조용히 걸러 내면 '표는 있는데 안 나온다'는 침묵 실패다 — 상태를 싣고 소비 경로가 정한다."""
        result = advise("power-rule-step-omitted", 2)
        assert result.authoring_status == "draft"
        assert result.corrective_explanation is not None

    def test_status_follows_the_row_not_a_constant(self, monkeypatch: pytest.MonkeyPatch) -> None:
        row = tables.remediation_row_for_mis_id("M0671")
        assert row is not None
        reviewed = row.model_copy(update={"authoring_status": "reviewed"})
        assert reviewed.authoring_status != row.authoring_status, "주입 미적용 — 테스트 무효"
        monkeypatch.setattr(advice_mod, "resolve_row", lambda _k: reviewed)
        assert advise("power-rule-step-omitted", 2).authoring_status == "reviewed"
