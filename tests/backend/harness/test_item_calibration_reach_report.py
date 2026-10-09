"""문항 난이도 보정 루프 도달 관측 리포트 테스트 — 결정론·정직 회계(hermetic).

대상: `whymath_backend.harness.item_calibration_reach_report`(PB-10 acceptance①). `build_report`·
`classify`는 순수 함수라 실 DB 없이 합성 `CalibrationReachCounts`로 검증한다. DB를 실제로 여는 델타
변별력 통합테스트는 `tests/backend/db/test_item_calibration_reach_report_integration.py`.

**변별력**(CLAUDE.md "변별력 없는 검증 스텝 금지"): 이 리포트의 존재 이유는 같은 "b 채움 0건"이 *입력
부재*(정상 no-op)와 *배치 미가동*(배선 부재)이라는 다른 사실일 수 있다는 점을 가르는 것이다. 5상태가
같은 irt_b_filled=0에서 서로 다른 판정을 내는지가 이 파일의 핵심 검증 대상이다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from whymath_backend.harness import item_calibration_reach_report as icrr
from whymath_backend.l2 import item_calibration

_FLOOR = icrr.MIN_RESPONSES_FOR_CALIBRATION


def _counts(
    *,
    problem_total: int = 100,
    irt_b_filled: int = 0,
    irt_a_filled: int = 0,
    graded_attempts: int = 0,
    distinct_students: int = 0,
    items_with_responses: int = 0,
    eligible_items: int = 0,
    eligible_unfilled: int = 0,
) -> icrr.CalibrationReachCounts:
    return icrr.CalibrationReachCounts(
        problem_total=problem_total,
        irt_b_filled=irt_b_filled,
        irt_a_filled=irt_a_filled,
        graded_attempts=graded_attempts,
        distinct_students=distinct_students,
        items_with_responses=items_with_responses,
        eligible_items=eligible_items,
        eligible_unfilled=eligible_unfilled,
    )


# ──────────────────────────────────────────────────────────────────────────
# 1. 5상태 판정 — 같은 b 채움 0건에서 서로 다른 사실을 가른다
# ──────────────────────────────────────────────────────────────────────────
def test_no_responses_is_not_dormancy() -> None:
    """응답 0행 → NO_RESPONSES. b가 0건 채워졌어도 이것은 '입력 부재'지 '배치 미가동'이 아니다."""
    assert icrr.classify(_counts()) == icrr.VERDICT_NO_RESPONSES


def test_responses_but_nothing_eligible_is_no_eligible_items() -> None:
    """응답은 있으나 5회 이상 문항 0건 → NO_ELIGIBLE_ITEMS (실제 운영 실측 2026-09-29: 80문항 전부 1~4건)."""
    counts = _counts(graded_attempts=80, distinct_students=1, items_with_responses=80)
    assert icrr.classify(counts) == icrr.VERDICT_NO_ELIGIBLE_ITEMS


def test_eligible_items_all_unfilled_is_loop_dormant() -> None:
    """자격 문항이 있는데 전부 b NULL → LOOP_DORMANT (PB-10이 숫자로 드러내려던 신호)."""
    counts = _counts(
        graded_attempts=40, items_with_responses=8, eligible_items=3, eligible_unfilled=3
    )
    assert icrr.classify(counts) == icrr.VERDICT_LOOP_DORMANT


def test_eligible_items_partially_filled_is_loop_stale() -> None:
    counts = _counts(
        irt_b_filled=2,
        graded_attempts=40,
        items_with_responses=8,
        eligible_items=3,
        eligible_unfilled=1,
    )
    assert icrr.classify(counts) == icrr.VERDICT_LOOP_STALE


def test_eligible_items_all_filled_is_caught_up() -> None:
    counts = _counts(
        irt_b_filled=3,
        graded_attempts=40,
        items_with_responses=8,
        eligible_items=3,
        eligible_unfilled=0,
    )
    assert icrr.classify(counts) == icrr.VERDICT_LOOP_CAUGHT_UP


def test_same_zero_fill_yields_three_different_verdicts() -> None:
    """변별력의 심장 — irt_b_filled=0이 동일해도 입력 상태에 따라 판정이 모두 다르다."""
    no_input = icrr.classify(_counts())
    below_floor = icrr.classify(_counts(graded_attempts=9, items_with_responses=3))
    dormant = icrr.classify(
        _counts(graded_attempts=9, items_with_responses=1, eligible_items=1, eligible_unfilled=1)
    )
    assert len({no_input, below_floor, dormant}) == 3


def test_every_verdict_is_reachable_and_has_distinct_meaning() -> None:
    """VERDICTS 5종이 전부 어떤 입력에서 나오고, 해설이 서로 다르다(죽은 상태·복붙 해설 방지)."""
    reached = {
        icrr.classify(_counts()),
        icrr.classify(_counts(graded_attempts=1, items_with_responses=1)),
        icrr.classify(
            _counts(
                graded_attempts=9, items_with_responses=1, eligible_items=1, eligible_unfilled=1
            )
        ),
        icrr.classify(
            _counts(
                graded_attempts=9, items_with_responses=2, eligible_items=2, eligible_unfilled=1
            )
        ),
        icrr.classify(
            _counts(
                graded_attempts=9, items_with_responses=1, eligible_items=1, eligible_unfilled=0
            )
        ),
    }
    assert reached == set(icrr.VERDICTS)
    meanings = {icrr.build_report(_counts()).verdict_meaning}
    for v in icrr.VERDICTS:
        meanings.add(icrr._VERDICT_MEANING[v])
    assert len(meanings) == len(icrr.VERDICTS)


# ──────────────────────────────────────────────────────────────────────────
# 2. 파생값 — 분모 0은 None(0.0으로 접지 않는다)
# ──────────────────────────────────────────────────────────────────────────
def test_fill_ratio_is_none_when_no_problems() -> None:
    report = icrr.build_report(_counts(problem_total=0))
    assert report.irt_b_fill_ratio is None
    assert report.irt_a_fill_ratio is None
    assert "| `irt_difficulty_b` | 0 | 0 | none |" in icrr.render_report(report)


def test_fill_ratio_is_exact_fraction() -> None:
    report = icrr.build_report(_counts(problem_total=200, irt_b_filled=50, irt_a_filled=10))
    assert report.irt_b_fill_ratio == pytest.approx(0.25)
    assert report.irt_a_fill_ratio == pytest.approx(0.05)


def test_below_floor_and_eligible_filled_are_derived_consistently() -> None:
    report = icrr.build_report(
        _counts(items_with_responses=10, eligible_items=4, eligible_unfilled=1, graded_attempts=50)
    )
    assert report.items_below_floor == 6
    assert report.eligible_filled == 3
    assert report.items_below_floor + report.counts.eligible_items == 10


# ──────────────────────────────────────────────────────────────────────────
# 3. 마지막 보정 시각 — 모른다를 아니다/0으로 접지 않는다
# ──────────────────────────────────────────────────────────────────────────
def test_last_calibration_is_explicitly_unrecorded() -> None:
    report = icrr.build_report(_counts())
    assert report.last_calibration_at == icrr.LAST_CALIBRATION_UNRECORDED == "unrecorded"
    assert "last_calibration_at=unrecorded" in icrr.render_report(report)
    assert icrr.report_to_json(report)["last_calibration_at"] == "unrecorded"


def test_unrecorded_claim_matches_the_problem_model() -> None:
    """'저장 좌석이 없다'는 주장이 모델 사실에 묶여 있다 — calibrated_at이 생기거나 updated_at에
    onupdate가 붙으면 이 테스트가 깨져 리포트 문구의 갱신을 강제한다(조용한 거짓 주장 방지)."""
    from whymath_backend.db.models.problem import Problem

    columns = {c.name: c for c in Problem.__table__.columns}
    assert "calibrated_at" not in columns
    assert columns["updated_at"].onupdate is None


# ──────────────────────────────────────────────────────────────────────────
# 4. 원천 동기화 — 자격 임계는 복제가 아니라 import
# ──────────────────────────────────────────────────────────────────────────
def test_floor_is_imported_from_calibration_not_duplicated() -> None:
    assert _FLOOR == item_calibration._MIN_RESPONSES_FOR_CALIBRATION
    # 값이 같은 것만으로는 복제와 구별되지 않는다 — 소스에 리터럴 대입이 없고 원천 import가 있는지 본다.
    source = Path(icrr.__file__).read_text(encoding="utf-8")
    assert re.search(r"from whymath_backend\.l2\.item_calibration import", source)
    assert not re.search(r"MIN_RESPONSES_FOR_CALIBRATION\s*=\s*\d+", source)


# ──────────────────────────────────────────────────────────────────────────
# 5. 렌더·JSON
# ──────────────────────────────────────────────────────────────────────────
def test_render_contains_verdict_counts_and_not_a_gate_notice() -> None:
    report = icrr.build_report(
        _counts(
            problem_total=1703,
            graded_attempts=80,
            distinct_students=1,
            items_with_responses=80,
        )
    )
    text = icrr.render_report(report)
    assert "## 판정: `NO_ELIGIBLE_ITEMS`" in text
    assert "**exit 게이트가 아니다**" in text
    assert "채점 응답: **80**" in text
    assert "응답 학생: **1**" in text
    assert f"제외(응답 1~{_FLOOR - 1}회): **80**" in text
    assert f"자격(응답 ≥ {_FLOOR}회): **0**" in text


def test_json_roundtrip_has_all_keys_and_is_stable() -> None:
    report = icrr.build_report(
        _counts(graded_attempts=9, items_with_responses=1, eligible_items=1, eligible_unfilled=1)
    )
    first = icrr.dump_json(report)
    assert first == icrr.dump_json(report)  # 결정론
    data = json.loads(first)
    assert data["verdict"] == icrr.VERDICT_LOOP_DORMANT
    assert data["min_responses_for_calibration"] == _FLOOR
    for key in (
        "problem_total",
        "irt_b_filled",
        "irt_a_filled",
        "irt_b_fill_ratio",
        "graded_attempts",
        "distinct_students",
        "items_with_responses",
        "items_below_floor",
        "eligible_items",
        "eligible_filled",
        "eligible_unfilled",
        "last_calibration_at",
    ):
        assert key in data


# ──────────────────────────────────────────────────────────────────────────
# 6. CLI — 게이트 아님(어떤 판정이어도 0) · DB 오류는 타입명과 함께 2
# ──────────────────────────────────────────────────────────────────────────
def test_main_exits_zero_even_when_loop_is_dormant(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    dormant = icrr.build_report(
        _counts(graded_attempts=9, items_with_responses=1, eligible_items=1, eligible_unfilled=1)
    )

    async def _fake_run() -> icrr.CalibrationReachReport:
        return dormant

    monkeypatch.setattr(icrr, "_run", _fake_run)
    out_json = tmp_path / "nested" / "reach.json"
    assert icrr.main(["--json", str(out_json)]) == 0
    assert "LOOP_DORMANT" in capsys.readouterr().out
    assert json.loads(out_json.read_text(encoding="utf-8"))["verdict"] == "LOOP_DORMANT"


def test_main_reports_exception_type_name_and_exits_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def _boom() -> icrr.CalibrationReachReport:
        raise ConnectionRefusedError("db down")

    monkeypatch.setattr(icrr, "_run", _boom)
    assert icrr.main([]) == 2
    err = capsys.readouterr().err
    assert "ConnectionRefusedError" in err  # 무타입 경고 금지
