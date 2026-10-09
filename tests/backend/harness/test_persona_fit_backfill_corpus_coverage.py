"""persona_fit 백필의 실제 코퍼스 커버리지·L6 적격 효과 봉인(S3-10 acceptance).

`test_persona_fit_rules.py`(합성 픽스처)·`test_problem_corpus_persona_fit_backfill.py`(hermetic
CLI 계약)에 더해, 이 모듈은 **실제 코퍼스 8종**(2026-07-30 미병합 브랜치 회수 시
`probability_finite_v0`이 7번째로 추가됨 — `harness/problem_corpus_persona_fit_backfill.
KNOWN_CORPORA` 참조)을 로드해 두 가지를 실측 봉인한다:

  ① 전 레코드의 `persona_fit`이 빈 dict가 아님(죽은 경로 소생의 직접 증거 — 회귀 시 즉시 실패).
  ② L6 수능(`is_suneung_eligible`)·학교진도(`is_school_progress_eligible`) persona_fit *폴백*
     경로가 실제로 0에서 양수로 바뀜(exam_type·signature_patterns·진도 인자를 배제해 persona_fit
     신호만 격리 측정 — `docs/data/persona_fit_backfill_report_s3_10.md` §1의 측정 방법과 동형).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from whymath_backend.harness.problem_corpus_persona_fit_backfill import KNOWN_CORPORA
from whymath_backend.l1.problem_bank.populate import load_problem_bank_records
from whymath_backend.l6.school_progress.gating import (
    SCHOOL_PROGRESS_PERSONAS,
    is_school_progress_eligible,
)
from whymath_backend.l6.suneung.gating import SUNEUNG_PERSONAS, is_suneung_eligible
from whymath_backend.schema.problem import Problem


def _all_problems() -> list[Problem]:
    root = Path(__file__).resolve().parents[3]
    problems: list[Problem] = []
    for relative_path in KNOWN_CORPORA.values():
        corpus = root / relative_path
        if not corpus.exists():
            pytest.skip(f"코퍼스 미존재({relative_path})")
        problems.extend(r.problem for r in load_problem_bank_records(corpus))
    return problems


def test_eight_corpora_covered() -> None:
    # 8번째 = P3-03 미분 은행(`p3_calculus1_diff_v0` — 5회차 S5 감사 승인 뒤 편입, 2026-10-09).
    assert len(KNOWN_CORPORA) == 8


def test_no_empty_persona_fit_in_real_corpus() -> None:
    problems = _all_problems()
    assert len(problems) > 0
    empty = [p.slug for p in problems if not p.persona_fit]
    assert empty == [], f"persona_fit 미채움 레코드 존재(죽은 경로 재발) — {empty[:5]}"


def test_suneung_persona_fit_only_eligibility_is_positive() -> None:
    """exam_type·signature_patterns 신호를 차단해 persona_fit 폴백 경로만 격리 측정(A/B/C 합산)."""
    count = 0
    for problem in _all_problems():
        isolated = problem.model_copy(update={"exam_type": None, "signature_patterns": []})
        for persona in SUNEUNG_PERSONAS:
            if is_suneung_eligible(isolated, persona, min_fit=0.5):
                count += 1
    assert count > 0


def test_school_progress_persona_fit_fallback_eligibility_is_positive() -> None:
    """진도 인자(단원·성취기준)를 안 줘 persona_fit 폴백 경로만 격리 측정(A/D 합산)."""
    count = 0
    for problem in _all_problems():
        for persona in SCHOOL_PROGRESS_PERSONAS:
            if is_school_progress_eligible(
                problem,
                persona,
                target_unit_codes=None,
                target_achievement_codes=None,
                min_fit=0.5,
            ):
                count += 1
    assert count > 0
