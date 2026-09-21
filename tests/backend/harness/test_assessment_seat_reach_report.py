"""평가 결과 영속 좌석 도달 관측 리포트 테스트 — 결정론·정직 회계(hermetic).

대상: `whymath_backend.harness.assessment_seat_reach_report`(ASM-01 acceptance②). `build_report`는
순수 함수라 실 DB 없이 합성 `SeatCounts`로 검증한다. DB를 실제로 여는 통합테스트는
`tests/backend/db/test_assessment_seat_reach_report_integration.py`(acceptance④ 변별력)에 별도로
있다.

**변별력**(CLAUDE.md "변별력 없는 검증 스텝 금지"): writer citation이 있는 테이블과 없는
테이블이 *같은 0이라는 값에서 다른 문구*를 내는지가 이 파일의 핵심 검증 대상이다(같은 값을
내면 이 리포트 설계 자체가 실패다). [ASM-05 stale 정정·2026-08-10] ASM-01 동결 당시엔
`ability_snapshot`(writer 有) vs 나머지 3테이블(writer 無)의 실물 대비로 이를 검증했으나,
ASM-03(capture)·ASM-04(assemble)·mastery 트래킹 착지로 **4테이블 전부 writer가 실재**하게 돼
실물로는 그 대비를 더 만들 수 없다 — 변별력은 합성(synthetic) writerless 항목으로 보존한다.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

from whymath_backend.harness import assessment_seat_reach_report as asrr
from whymath_backend.schema.enums import AssessmentType

# tests/backend/harness/ → tests/backend → tests → repo root → src/backend
_BACKEND_DIR = Path(__file__).resolve().parents[3] / "src" / "backend"


def _counts(
    *,
    assessment: int = 0,
    concept_mastery_history: int = 0,
    skill_mastery_history: int = 0,
    ability_snapshot: int = 0,
    type_counts: dict[str, int] | None = None,
    concept_diagnosis_nonempty: int = 0,
    recommended_path_nonempty: int = 0,
    strong_points_nonempty: int = 0,
) -> asrr.SeatCounts:
    return asrr.SeatCounts(
        table_row_counts={
            "assessment": assessment,
            "concept_mastery_history": concept_mastery_history,
            "skill_mastery_history": skill_mastery_history,
            "ability_snapshot": ability_snapshot,
        },
        assessment_type_counts=type_counts or {},
        concept_diagnosis_nonempty_count=concept_diagnosis_nonempty,
        recommended_path_nonempty_count=recommended_path_nonempty,
        strong_points_nonempty_count=strong_points_nonempty,
    )


def _seat(report: asrr.SeatReachReport, name: str) -> asrr.TableSeat:
    return next(s for s in report.seats if s.name == name)


# ──────────────────────────────────────────────────────────────────────────
# 1. 행 수 반영
# ──────────────────────────────────────────────────────────────────────────
def test_build_report_reflects_all_four_table_counts_exactly() -> None:
    counts = _counts(
        assessment=3,
        concept_mastery_history=10,
        skill_mastery_history=5,
        ability_snapshot=7,
    )
    report = asrr.build_report(counts)
    assert _seat(report, "assessment").row_count == 3
    assert _seat(report, "concept_mastery_history").row_count == 10
    assert _seat(report, "skill_mastery_history").row_count == 5
    assert _seat(report, "ability_snapshot").row_count == 7


# ──────────────────────────────────────────────────────────────────────────
# 2. [ASM-05 진실 갱신] 4테이블 전부 writer 실재 — 빈 테이블 사유는 "writer 존재하나 미호출 관측"
# ──────────────────────────────────────────────────────────────────────────
def test_all_four_tables_report_uncalled_writer_when_empty() -> None:
    """[ASM-05 의도된 진실 갱신·2026-08-10] 빈 테이블의 사유가 '생성 경로 부재'→'writer 존재하나
    미호출 관측'으로 바뀌었다 — ASM-01 동결 당시 writer 0이던 assessment·concept_mastery_history·
    skill_mastery_history에 ASM-03(capture)·ASM-04(assemble)·mastery 트래킹으로 라이브 writer가
    착지해, 옛 동결('생성 경로 부재')을 유지하면 그것이 거짓 주장이 되기 때문이다."""
    report = asrr.build_report(_counts())
    for name in (
        "assessment",
        "concept_mastery_history",
        "skill_mastery_history",
        "ability_snapshot",
    ):
        seat = _seat(report, name)
        assert seat.reason == asrr._REASON_UNCALLED_WRITER
        assert seat.writer_citation is not None


def test_writer_citations_anchor_measured_code_paths() -> None:
    """인용 문자열이 실측 앵커(핸들러·경로·행 번호)를 담는지 동결 — 드리프트 감시.

    기존 ability_snapshot 인용(api/me.py:965)도 드리프트해 :1030으로 재실측 정정됐고,
    EOS-57(2026-09-01)에서 5개 인용이 다시 전부 드리프트한 것을 재실측 갱신했다
    (738→759·743→764·1030→1064) — 이 테스트가 그 갱신을 강제하는 장치다.
    """
    report = asrr.build_report(_counts())
    cmh = _seat(report, "concept_mastery_history").writer_citation
    smh = _seat(report, "skill_mastery_history").writer_citation
    asm = _seat(report, "assessment").writer_citation
    abs_ = _seat(report, "ability_snapshot").writer_citation
    assert cmh is not None and "record_problem_attempt_mastery" in cmh
    assert cmh is not None and "api/me.py:759" in cmh
    assert smh is not None and "record_problem_attempt_skill_mastery" in smh
    assert smh is not None and "api/me.py:764" in smh
    assert asm is not None and "capture_measurement_assessment" in asm
    assert asm is not None and "assemble_blueprint_assessment" in asm
    assert abs_ is not None and "capture_ability_snapshot" in abs_
    assert abs_ is not None and "api/me.py:1064" in abs_


# ──────────────────────────────────────────────────────────────────────────
# 3. 변별력 보존 — '생성 경로 부재' vs 'writer 존재하나 미호출'은 합성 writerless 항목으로 검증
# ──────────────────────────────────────────────────────────────────────────
def test_no_producer_vs_uncalled_writer_discrimination_via_synthetic_entry() -> None:
    """[ASM-05 재작성] 핵심 변별력 테스트 — 같은 0에서 writer 유무에 따라 *다른* 문구가 나오는지.

    실물 4테이블이 전부 writer를 갖게 돼(위 진실 갱신) 실물 대비로는 이 변별을 더 만들 수 없다 —
    대장에 없는 합성 테이블명과 명시 None 항목으로 `_reason_for`의 분기 자체를 직접 검증한다
    (같은 값을 내면 이 리포트의 존재 이유가 무너진다는 원칙은 ASM-01 그대로다).
    """
    synthetic = "__asm05_synthetic_writerless__"
    # 전제 확인: 합성 이름은 writer 대장에 없다(있다면 이 테스트 설계 자체가 무효).
    assert synthetic not in asrr._KNOWN_WRITER_CITATION
    # 대장 밖 이름(get→None)과 명시 None 항목 둘 다 '생성 경로 부재'로 분류돼야 한다.
    assert asrr._reason_for(synthetic, 0) == asrr._REASON_NO_PRODUCER
    with patch.dict(asrr._KNOWN_WRITER_CITATION, {synthetic: None}):
        assert asrr._reason_for(synthetic, 0) == asrr._REASON_NO_PRODUCER
    # 같은 0인데 writer가 실재하는 테이블과는 사유가 달라야 한다 — 변별력의 심장.
    assert asrr._reason_for("ability_snapshot", 0) == asrr._REASON_UNCALLED_WRITER
    assert asrr._reason_for(synthetic, 0) != asrr._reason_for("ability_snapshot", 0)
    # count>0이면 writer 유무와 무관하게 '관측됨'(3분류 상호 배타의 나머지 한 축).
    assert asrr._reason_for(synthetic, 3) == asrr._REASON_OBSERVED


# ──────────────────────────────────────────────────────────────────────────
# 4. count>0 → "관측됨"(writer 유무 무관)
# ──────────────────────────────────────────────────────────────────────────
def test_nonzero_count_reports_observed_regardless_of_writer() -> None:
    report = asrr.build_report(_counts(assessment=1, ability_snapshot=1))
    assert _seat(report, "assessment").reason == asrr._REASON_OBSERVED
    assert _seat(report, "ability_snapshot").reason == asrr._REASON_OBSERVED


# ──────────────────────────────────────────────────────────────────────────
# 5. AssessmentType 5종 전부 보강(데이터 없는 값도 0)
# ──────────────────────────────────────────────────────────────────────────
def test_all_five_assessment_types_appear_even_when_db_has_only_two() -> None:
    report = asrr.build_report(_counts(type_counts={"초기진단": 2, "단원진단": 1}))
    assert set(report.assessment_type_distribution) == {t.value for t in AssessmentType}
    assert report.assessment_type_distribution["초기진단"] == 2
    assert report.assessment_type_distribution["단원진단"] == 1
    # 나머지 3종은 데이터가 없어도 조용히 생략되지 않고 0으로 명시된다.
    assert report.assessment_type_distribution["주간진단"] == 0
    assert report.assessment_type_distribution["실전모의고사"] == 0
    assert report.assessment_type_distribution["D-100예측"] == 0


def test_assessment_type_distribution_all_zero_when_db_empty() -> None:
    report = asrr.build_report(_counts())
    assert report.assessment_type_distribution == {
        "초기진단": 0,
        "주간진단": 0,
        "단원진단": 0,
        "실전모의고사": 0,
        "D-100예측": 0,
    }


# ──────────────────────────────────────────────────────────────────────────
# 6. D-100예측 하이픈 표기 정확성
# ──────────────────────────────────────────────────────────────────────────
def test_d100_prediction_hyphen_value_rendered_exactly() -> None:
    report = asrr.build_report(_counts(type_counts={"D-100예측": 4}))
    assert report.assessment_type_distribution["D-100예측"] == 4
    rendered = asrr.render_report(report)
    assert "D-100예측" in rendered
    assert "D_100예측" not in rendered  # 멤버명이 아니라 값(하이픈)이 렌더돼야 한다.


# ──────────────────────────────────────────────────────────────────────────
# 7. JSONB 결손 표기
# ──────────────────────────────────────────────────────────────────────────
def test_concept_diagnosis_and_recommended_path_nonempty_counts_pass_through() -> None:
    report = asrr.build_report(_counts(concept_diagnosis_nonempty=2, recommended_path_nonempty=1))
    assert report.concept_diagnosis_nonempty_count == 2
    assert report.recommended_path_nonempty_count == 1
    rendered = asrr.render_report(report)
    assert "2" in rendered
    assert "concept_diagnosis" in rendered
    assert "recommended_path" in rendered


def test_strong_points_nonempty_count_passes_through() -> None:
    """ASM-13 — `strong_points`(강점 개념) writer 착지의 채운 비율 가시화 동결."""
    report = asrr.build_report(_counts(strong_points_nonempty=4))
    assert report.strong_points_nonempty_count == 4
    rendered = asrr.render_report(report)
    assert "strong_points" in rendered
    assert "4" in rendered


# ──────────────────────────────────────────────────────────────────────────
# 8. JSON 직렬화 왕복
# ──────────────────────────────────────────────────────────────────────────
def test_report_to_json_roundtrips_through_json_dumps_loads() -> None:
    report = asrr.build_report(
        _counts(assessment=2, type_counts={"초기진단": 2}, concept_diagnosis_nonempty=1)
    )
    payload = asrr.report_to_json(report)
    roundtripped = json.loads(json.dumps(payload, ensure_ascii=False))
    assert roundtripped == payload
    assert roundtripped["concept_diagnosis_nonempty_count"] == 1


def test_dump_json_produces_valid_json_with_sorted_keys() -> None:
    report = asrr.build_report(_counts(assessment=1))
    dumped = asrr.dump_json(report)
    parsed = json.loads(dumped)
    assert parsed["seats"][0]["name"] == "assessment"


# ──────────────────────────────────────────────────────────────────────────
# 9. 렌더링 결정론성
# ──────────────────────────────────────────────────────────────────────────
def test_render_report_is_deterministic_across_repeated_calls() -> None:
    counts = _counts(assessment=1, type_counts={"단원진단": 3}, ability_snapshot=2)
    report = asrr.build_report(counts)
    r1 = asrr.render_report(report)
    r2 = asrr.render_report(asrr.build_report(counts))
    assert r1 == r2


# ──────────────────────────────────────────────────────────────────────────
# 10. CLI — DB 오류 시 exit 2·예외 타입명 stderr 포함(침묵 실패 금지)
# ──────────────────────────────────────────────────────────────────────────
def test_main_returns_exit_2_and_logs_exception_type_on_db_failure(capsys) -> None:
    with patch.object(asrr, "_run", new=AsyncMock(side_effect=RuntimeError("접속 실패"))):
        exit_code = asrr.main([])
    assert exit_code == asrr._EXIT_INPUT_ERROR
    captured = capsys.readouterr()
    assert "RuntimeError" in captured.err  # 무타입 경고 금지 — 예외 타입명이 로그에 있어야 한다.


def test_main_cli_smoke_help_exits_zero_without_db() -> None:
    """`--help`는 DB 접속 없이 exit 0이어야 한다(argparse 표준 동작 회귀 감시)."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "whymath_backend.harness.assessment_seat_reach_report",
            "--help",
        ],
        cwd=_BACKEND_DIR,
        capture_output=True,
        text=True,
        # [OPS-44 사고 경위] 자식 --help 출력의 UTF-8 한국어를 부모가 로케일(cp949)로 디코드해
        # reader thread가 UnicodeDecodeError로 죽고 stdout=None이 됐다 — UTF-8 명시로 고정.
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    assert result.returncode == 0
    assert "assessment" in result.stdout.lower() or "평가" in result.stdout
