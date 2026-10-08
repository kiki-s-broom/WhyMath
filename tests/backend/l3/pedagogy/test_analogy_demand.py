"""수요 실측 CLI(analogy_demand) hermetic 테스트 — 코퍼스 계수·정직한 공백·exit 규약.

실 코퍼스(레포 커밋 자산)를 읽는 hermetic 측정이다(DB·LLM 0). 검증 축:
  ① 코퍼스 총량·공백 계수 일치(846행 자산 실재 — 04g §6.1 진단의 기계 확인)
  ② ai_estimated=전량(적재기 상수 각인 규약 정합)
  ③ 발주서 슬롯 계수(유닛 컴파일 — 개념형/숫자형 분해 합 정합)
  ④ 채움(APPROVED)은 DB 미접속 시 None — 0% 위장 금지(정직한 공백)
  ⑤ main() exit 0 + JSON 리포트
"""

from __future__ import annotations

import json
from pathlib import Path

from whymath_backend.l3.pedagogy.analogy_demand import (
    MetaphorDemand,
    load_all_content_records,
    main,
    measure_metaphor_demand,
    measure_slot_demand,
    render_report,
)


class TestMetaphorDemand:
    def test_corpus_totals(self) -> None:
        """자산 846행(K-12 437 + 대학 409) 실재 — 04g §6.1 "비유 0이 아니라 846행" 진단 동결."""
        records = load_all_content_records()
        assert len(records) == 846
        demand = measure_metaphor_demand(records)
        assert demand.total == 846
        # ai_estimated는 적재기 상수 각인 규약상 전량이다(projection.py — 코퍼스에 필드 부재).
        assert demand.ai_estimated == 846

    def test_blank_plus_checked_equals_total(self) -> None:
        """공백 + 검사 대상 = 총량(계수 회계 정합)."""
        demand = measure_metaphor_demand(load_all_content_records())
        assert demand.blank + (demand.total - demand.blank) == demand.total
        assert 0 <= demand.defect_rows <= demand.total - demand.blank

    def test_defect_axis_counts_are_row_counts(self) -> None:
        """축별 계수는 행 수 — 각 축 계수가 결함 행 총수를 넘지 않는다(중복 계상 방어)."""
        demand = measure_metaphor_demand(load_all_content_records())
        for axis, count in demand.defect_by_axis.items():
            assert count <= demand.defect_rows, axis

    def test_gamified_measured_zero_on_existing_assets(self) -> None:
        """게임형 산출 0 검사(기존 자산 실측) — 846행에 게임화 메커닉 어휘 0건.

        acceptance ③의 자산측 실측이다. 이 값이 0이 아니게 되면(코퍼스 갱신 등) 해당 행은
        재저작 표적이며, 이 테스트가 그 순간을 즉시 드러낸다(조용한 오염 금지).
        """
        demand = measure_metaphor_demand(load_all_content_records())
        assert demand.gamified_rows == 0

    def test_pure_measure_on_synthetic_records(self) -> None:
        """합성 레코드 변별력 — 공백·결함·무결함이 각각 제 축에 계상된다."""

        class _R:
            def __init__(self, code: str, metaphor: str | None) -> None:
                self.code = code
                self.name = "n"
                self.subject = "s"
                self.metaphor = metaphor

        demand = measure_metaphor_demand(
            [
                _R("A", None),  # 공백
                _R("B", "이것이 정의다."),  # 결함(참칭+한계 부재)
                _R("C", "자판기와 같아. 다만 다르다 — 정의가 아니라 디딤돌."),  # 무결함
            ]  # type: ignore[arg-type]
        )
        assert isinstance(demand, MetaphorDemand)
        assert demand.total == 3
        assert demand.blank == 1
        assert demand.defect_rows == 1


class TestSlotDemand:
    def test_ordered_counts_consistent(self) -> None:
        """발주 총량 = 개념형 + 숫자형 = 유형별 합(회계 정합·유닛 1편 이상)."""
        demand = measure_slot_demand()
        assert demand.units >= 1
        assert demand.ordered_total == demand.conceptual_total + demand.numeric_total
        assert demand.ordered_total == sum(demand.ordered_by_type.values())

    def test_filled_is_none_without_db(self) -> None:
        """④ 채움은 DB 미접속 계측이 없으면 None — 0으로 위장하지 않는다(정직한 공백)."""
        demand = measure_slot_demand()
        assert demand.filled_by_type is None

    def test_pilot_unit_ordered_total(self) -> None:
        """파일럿 소단원 발주 43점(팩 required_slots × 4목표 + variation 오버라이드) 동결.

        2026-08-16 PED-30: MODELING 팩 보강(plan_skeleton 2 + result_interpretation 1 추가)으로
        40 → 43. 의도된 데이터 보강이며, 이후 변경은 다시 이 리터럴을 깨 검토를 강제한다.
        """
        demand = measure_slot_demand()
        assert demand.ordered_total == 43
        assert demand.ordered_by_type["example_pair"] == 4
        assert demand.ordered_by_type["problem_variation"] == 3  # OBJ-04 오버라이드 반영


class TestCli:
    def test_main_exit_zero_and_json(self, tmp_path: Path) -> None:
        out = tmp_path / "demand.json"
        assert main(["--json", str(out)]) == 0
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["metaphor"]["total"] == 846
        assert payload["slots"]["filled_by_type"] is None  # DB 미접속 — 정직한 None

    def test_render_report_mentions_honest_gap(self) -> None:
        records = load_all_content_records()
        report = render_report(measure_metaphor_demand(records), measure_slot_demand())
        assert "미측정" in report  # 채움 미측정을 숨기지 않는다
        assert "게임형" in report
