"""실사용자 수·리텐션 판정 조건 삭제의 동결 (Kiki 결정 2026-11-06).

WhyMath의 판정은 AI가 검토·점검·해결한 기록으로 한다. 실사용자가 있어야만 통과하는 조건
(학생 100명 · 실제 학생 표본 ≥20명 · β 사용자 100명 · 7일 재방문율 30%)은 학생 참여가
12/31 이후(ARCH-66 ⑥)라 연기만 반복하다 판정 불능을 낳았고, 2026-11-06에 판정 조건에서
삭제됐다(PR #1854 · #1860).

이 파일은 그 삭제가 **선언 문서 밖**에서 조용히 되살아나는 것을 막는다(선언 부록 E G4 행은
`tests/backend/schema/test_declaration_canon_consistency.py::TestG4ConditionFreeze` 소유).

규칙: 금지 패턴이 들어 있는 줄은 같은 줄에 '삭제'라는 결정 기록이 있어야 한다 — 삭제 경위를
적은 줄은 옛 문구를 인용해도 된다. 문서 하나가 통째로 사라지거나 비면 RED다(공허 통과 금지).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# 판정 조건이 적혀 있던 정본 문서들 — 과거 판정·검토 문서(docs/reviews)와 ADR은 당시 기록이라 제외한다.
GUARDED_DOCS = (
    "ROADMAP.md",
    "docs/standards/current_phase_checklist.md",
    "docs/strategy/business_plan_master_v1.md",
    "docs/strategy/execution_bridge_2026-07.md",
    "docs/strategy/s3_pilot_briefing.md",
    "docs/strategy/phase3_math_eos_completion_plan_source.md",
    "docs/strategy/phase3_math_eos_completion_instruction_set.md",
    "docs/architecture/06_application_modes.md",
)

FORBIDDEN = (
    re.compile(r"실제 중·고등학생\s*100\s*명"),
    re.compile(r"100\s*명\s*규모\s*시뮬레이션"),
    re.compile(r"β\s*(사용자\s*)?100\s*명"),
    re.compile(r"실제\s*학생\s*표본\s*[≥>]=?\s*20"),
    re.compile(r"재방문율?\**\s*[≥>]?=?\s*30\s*%"),
    re.compile(r"D7\s*(재방문율?)?\s*[≥>]=?\s*30"),
    re.compile(r"7일\s*30\s*%"),
)

DELETION_MARK = "삭제"


def _violations(text: str) -> list[str]:
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        if DELETION_MARK in line:
            continue
        for pat in FORBIDDEN:
            if pat.search(line):
                out.append(f"{n}: {line.strip()[:160]}")
                break
    return out


@pytest.mark.parametrize("rel", GUARDED_DOCS)
def test_no_live_real_user_condition(rel: str) -> None:
    path = ROOT / rel
    assert path.is_file(), f"감시 대상 문서가 없다: {rel} — 옮겼다면 GUARDED_DOCS를 함께 고친다"
    text = path.read_text(encoding="utf-8")
    assert text.strip(), f"감시 대상 문서가 비었다: {rel}"
    bad = _violations(text)
    assert (
        not bad
    ), (
        f"{rel}에 실사용자 수·리텐션 판정 조건이 삭제 기록 없이 되살아났다 "
        f"(2026-11-06 Kiki 결정 위반):\n" + "\n".join(bad)
    )


@pytest.mark.parametrize(
    "line",
    [
        "- ✅ β 사용자 100명 이상",
        "- [ ] 사용자 재방문율 30%+ (7일 기준)",
        "| 게이트 | **D7 재방문율 ≥ 30%** · 답 미루기 |",
        "→ 파일럿 5~10명 → D7 ≥ 30% 게이트",
        "저장소 게이트(7일 30%+)가 상위 기준",
        "실제 학생 표본 ≥20명은 12/31 이후 판정한다.",
        " Q1 내일부터 실제 중·고등학생 100명을 넣어도",
    ],
)
def test_detector_catches_each_restored_form(line: str) -> None:
    """반례 — 삭제 전 실제로 있던 문면 그대로를 넣으면 잡혀야 한다(가드의 변별력)."""
    assert _violations(line), f"되살아난 조건을 못 잡았다: {line!r}"


def test_detector_allows_deletion_records() -> None:
    """대조군 — 삭제 경위를 적은 줄은 옛 문구를 인용해도 통과한다."""
    assert not _violations('- [Kiki 결정 2026-11-06: 종전 항목 "β 사용자 100명 이상" 삭제]')
