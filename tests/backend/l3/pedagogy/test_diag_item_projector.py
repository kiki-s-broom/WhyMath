"""PED-10 형성평가 diag_item 슬롯 채움 — 순수 파이프라인 단위테스트(hermetic).

핵심 관심사:
  ① **grain 다리** — `concept_nodes`(atom code 배열)와 `atom_probe.code`의 직접 교집합이
     정확히 동작하는지(04e §7.2 crosswalk 가정의 실측 정정 — `diag_item_projector` 모듈
     docstring 참조).
  ② **select-vs-generate** — 이미 검수 결정이 난 슬롯(PRESCREENED/APPROVED/REJECTED)은
     손대지 않고, 그 자리의 원자 후보도 소비하지 않는다.
  ③ **부분 채움의 정직성** — 후보 부족 시 조용히 채우다 만다(과다 생성 금지).
  ④ **표본 0은 None** — `DiagItemFillReport.prescreen_pass_rate`.
  ⑤ **손대지 않은 슬롯 유형 무변경** — 다른 슬롯 유형(`build_slot_rows` 등)의 동작이
     이 모듈 도입으로 바뀌지 않는다(회귀 없음).
"""

from __future__ import annotations

from typing import Any

from whymath_backend.composition import default_expression_equivalence
from whymath_backend.l3.pedagogy.diag_item_projector import (
    DiagItemFillReport,
    DiagItemTarget,
    build_diag_item_slot_row,
    diag_item_count,
    plan_diag_item_targets,
    project_diag_item_slots,
)

_OBJ = "10공수1-이차함수-최대최소:OBJ-01"
_MANIFEST: list[dict[str, Any]] = [
    {"type": "example_pair", "count": 4},
    {"type": "diag_item", "count": 2},
]
_PROBE_A = {"stem": "이차함수의 꼭짓점은 무엇인가?", "answer": "(2, -1)", "signal": "부호 오류"}
_PROBE_B = {"stem": "최솟값을 구하는 절차를 설명하라.", "answer": None, "signal": None}


# ──────────────────────────────────────────────────────────────────────────
# diag_item_count
# ──────────────────────────────────────────────────────────────────────────
class TestDiagItemCount:
    def test_extracts_matching_type(self) -> None:
        assert diag_item_count(_MANIFEST) == 2

    def test_zero_when_absent(self) -> None:
        assert diag_item_count([{"type": "example_pair", "count": 4}]) == 0

    def test_sums_duplicates_defensively(self) -> None:
        manifest = [{"type": "diag_item", "count": 1}, {"type": "diag_item", "count": 1}]
        assert diag_item_count(manifest) == 2


# ──────────────────────────────────────────────────────────────────────────
# plan_diag_item_targets — grain 다리 + select-vs-generate
# ──────────────────────────────────────────────────────────────────────────
class TestPlanDiagItemTargets:
    def test_direct_atom_code_bridge(self) -> None:
        """concept_nodes(atom code)와 atom_probe.code의 직접 교집합이 표적을 만든다."""
        objectives = [
            {
                "objective_id": _OBJ,
                "concept_nodes": ["2수01-01-2", "2수01-01-3"],
                "slot_manifest": _MANIFEST,
            }
        ]
        probes = {"2수01-01-2": _PROBE_A, "2수01-01-3": _PROBE_B}
        targets = plan_diag_item_targets(objectives, {}, probes)
        assert len(targets) == 2
        assert targets[0] == DiagItemTarget(
            objective_id=_OBJ,
            slot_id=f"{_OBJ}:diag_item:0",
            atom_code="2수01-01-2",
            stem=_PROBE_A["stem"],
            answer=_PROBE_A["answer"],
            signal=_PROBE_A["signal"],
        )
        assert targets[1].atom_code == "2수01-01-3"

    def test_atom_codes_without_probe_content_are_skipped(self) -> None:
        """probes_by_code에 없는 원자(발문 공백 등, 호출자가 이미 걸러낸)는 후보에서 제외."""
        objectives = [
            {"objective_id": _OBJ, "concept_nodes": ["A", "B", "C"], "slot_manifest": _MANIFEST}
        ]
        probes = {"B": _PROBE_A}  # A·C는 콘텐츠 없음(호출자가 사전 필터)
        targets = plan_diag_item_targets(objectives, {}, probes)
        assert len(targets) == 1
        assert targets[0].atom_code == "B"

    def test_zero_count_objective_produces_no_targets(self) -> None:
        objectives = [{"objective_id": _OBJ, "concept_nodes": ["A"], "slot_manifest": []}]
        assert plan_diag_item_targets(objectives, {}, {"A": _PROBE_A}) == []

    def test_reviewed_slot_is_untouched_and_candidate_not_consumed(self) -> None:
        """슬롯 0이 APPROVED면 손대지 않고, 그 원자 후보도 소비하지 않은 채 슬롯 1을 채운다."""
        objectives = [
            {"objective_id": _OBJ, "concept_nodes": ["A", "B"], "slot_manifest": _MANIFEST}
        ]
        existing = {f"{_OBJ}:diag_item:0": "APPROVED"}
        probes = {"A": _PROBE_A, "B": _PROBE_B}
        targets = plan_diag_item_targets(objectives, existing, probes)
        assert len(targets) == 1
        assert targets[0].slot_id == f"{_OBJ}:diag_item:1"
        assert targets[0].atom_code == "A"  # 후보 A는 소비되지 않고 남아 슬롯1에 쓰인다.

    def test_draft_existing_slot_is_refillable(self) -> None:
        """DRAFT(또는 미기재) 슬롯은 재적재 대상 — 워킹 스켈레톤 픽스처 교체가 의도다."""
        objectives = [{"objective_id": _OBJ, "concept_nodes": ["A"], "slot_manifest": _MANIFEST}]
        existing = {f"{_OBJ}:diag_item:0": "DRAFT"}
        targets = plan_diag_item_targets(objectives, existing, {"A": _PROBE_A})
        assert len(targets) == 1

    def test_partial_fill_when_candidates_exhausted(self) -> None:
        """발주 2건인데 콘텐츠 있는 원자가 1개뿐이면 1건만 — 조용히 채우다 만다(과다 생성 금지)."""
        objectives = [{"objective_id": _OBJ, "concept_nodes": ["A"], "slot_manifest": _MANIFEST}]
        targets = plan_diag_item_targets(objectives, {}, {"A": _PROBE_A})
        assert len(targets) == 1

    def test_multiple_objectives_isolated(self) -> None:
        obj2 = "10공수1-이차함수-최대최소:OBJ-02"
        objectives = [
            {"objective_id": _OBJ, "concept_nodes": ["A"], "slot_manifest": _MANIFEST},
            {"objective_id": obj2, "concept_nodes": ["B"], "slot_manifest": _MANIFEST},
        ]
        targets = plan_diag_item_targets(objectives, {}, {"A": _PROBE_A, "B": _PROBE_B})
        assert {t.objective_id for t in targets} == {_OBJ, obj2}


# ──────────────────────────────────────────────────────────────────────────
# build_diag_item_slot_row
# ──────────────────────────────────────────────────────────────────────────
class TestBuildDiagItemSlotRow:
    def test_row_shape_matches_slot_pipeline(self) -> None:
        target = DiagItemTarget(_OBJ, f"{_OBJ}:diag_item:0", "2수01-01-2", "발문", "정답", "신호")
        row = build_diag_item_slot_row(target)
        assert row["id"] == f"{_OBJ}:diag_item:0"
        assert row["objective_id"] == _OBJ
        assert row["slot_type"] == "diag_item"
        assert row["status"] == "DRAFT"
        assert row["provenance_id"] is None
        assert row["payload"]["body"] == "발문"
        assert row["payload"]["answer"] == "정답"
        assert row["payload"]["signal"] == "신호"
        assert row["payload"]["atom_code"] == "2수01-01-2"

    def test_null_answer_signal_omitted_not_fabricated(self) -> None:
        """answer/signal이 None이면 payload에 키 자체가 없다 — 빈 문자열로 지어내지 않는다."""
        target = DiagItemTarget(_OBJ, f"{_OBJ}:diag_item:0", "A", "발문만 있음", None, None)
        row = build_diag_item_slot_row(target)
        assert "answer" not in row["payload"]
        assert "signal" not in row["payload"]

    def test_sympy_verified_is_none_no_false_certainty(self) -> None:
        """atom_probe 통과기준은 자유서술 — verification 주장이 없어 None(검증 없는 True 금지)."""
        target = DiagItemTarget(_OBJ, f"{_OBJ}:diag_item:0", "A", "발문", "정답", None)
        row = build_diag_item_slot_row(target)
        assert row["sympy_verified"] is None

    def test_tts_safe_plain_korean_body(self) -> None:
        """$ 기호가 없는 평문 본문은 개수가 짝수(0)라 tts_safe=True."""
        target = DiagItemTarget(_OBJ, f"{_OBJ}:diag_item:0", "A", "이차함수의 꼭짓점은?", "", "")
        row = build_diag_item_slot_row(target)
        assert row["tts_safe"] is True


# ──────────────────────────────────────────────────────────────────────────
# DiagItemFillReport — 표본 0은 None
# ──────────────────────────────────────────────────────────────────────────
class TestDiagItemFillReport:
    def test_zero_fill_rate_is_none_not_zero(self) -> None:
        report = DiagItemFillReport()
        assert report.filled == 0
        assert report.prescreen_pass_rate is None

    def test_nonzero_rate_computed(self) -> None:
        report = DiagItemFillReport(filled=4, prescreen_passed=3)
        assert report.prescreen_pass_rate == 0.75

    def test_to_json_round_trips_none(self) -> None:
        assert DiagItemFillReport().to_json()["prescreen_pass_rate"] is None


# ──────────────────────────────────────────────────────────────────────────
# project_diag_item_slots — 순수 파이프라인 통합(계획→행→예심)
# ──────────────────────────────────────────────────────────────────────────
class TestProjectDiagItemSlots:
    def test_end_to_end_pure_pipeline(self) -> None:
        objectives = [
            {"objective_id": _OBJ, "concept_nodes": ["A", "B"], "slot_manifest": _MANIFEST}
        ]
        probes = {"A": _PROBE_A, "B": _PROBE_B}
        rows, scored, report = project_diag_item_slots(objectives, {}, probes)
        assert len(rows) == 2
        assert len(scored) == 2
        assert report.filled == 2
        # 구조 3요건(본문+유형·구조태그·tts_safe)을 만족하는 평문 콘텐츠 → 전건 통과 기대.
        assert report.prescreen_passed == 2
        assert report.prescreen_pass_rate == 1.0

    def test_empty_targets_short_circuits_to_empty_report(self) -> None:
        rows, scored, report = project_diag_item_slots([], {}, {})
        assert rows == []
        assert scored == []
        assert report.filled == 0
        assert report.prescreen_pass_rate is None


# ──────────────────────────────────────────────────────────────────────────
# 손대지 않은 슬롯 유형 무변경 — build_slot_rows 회귀 없음
# ──────────────────────────────────────────────────────────────────────────
class TestOtherSlotTypesUnchanged:
    def test_build_slot_rows_diag_item_fixture_unchanged(self) -> None:
        """이 모듈 도입이 파일럿 픽스처 생성기(build_slot_rows)의 diag_item 처리를 바꾸지 않는다."""
        from whymath_backend.l3.pedagogy.slot_generator import NUMERIC_SLOT_TYPES, build_slot_rows

        assert "diag_item" in NUMERIC_SLOT_TYPES  # 분류 불변 — 이 모듈이 재분류하지 않는다.
        rows = build_slot_rows(
            _OBJ, [{"type": "diag_item", "count": 2}], equivalence=default_expression_equivalence()
        )
        assert len(rows) == 2
        assert all(r["slot_type"] == "diag_item" for r in rows)

    def test_example_pair_slot_type_unaffected(self) -> None:
        from whymath_backend.l3.pedagogy.slot_generator import build_slot_rows

        rows = build_slot_rows(
            _OBJ,
            [{"type": "example_pair", "count": 3}],
            equivalence=default_expression_equivalence(),
        )
        assert len(rows) == 3
