"""코퍼스 재생 풀이의 풀이 유형 승인 표(`whs/path_promotion` · P3-96) — hermetic.

`whs/corpus_replay`는 모든 풀이에 출처 표지 `corpus-replay`를 단다. 이 태그만으로는 풀이 유형을
모르므로 승격이 전부 사람 검수 큐로 갔다(로컬 PG 샌드박스 실측 1,507/1,507). Kiki가 게이트
G-p332-corpus-replay-approach에서 A안(생성기 문항군 단위 결정론 표를 사람이 승인해 코드에 고정)을
골랐고, 이 파일이 그 표의 경계·배선·코퍼스 정합을 동결한다.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.solution_path import SolutionPath as SolutionPathOrm
from whymath_backend.db.models.verified_solution import VerifiedSolution, WhsSolutionGrade
from whymath_backend.whs.path_promotion import (
    CORPUS_REPLAY_APPROACH_BY_FAMILY,
    CORPUS_REPLAY_STRATEGY_TAG,
    corpus_replay_approach_for_slug,
    plan_promotion,
    promote_verified_solutions,
)

_NOW = datetime(2026, 11, 1, 0, 0, 0, tzinfo=UTC)
_REPO_ROOT = Path(__file__).resolve().parents[3]
#: 표가 전수로 덮어야 하는 은행 — 핵심 개념 10종의 적격 문항이 사는 곳(풀이 단계 보유분).
_COVERED_BANKS = (
    "p3_calculus1_diff_v0",
    "generated_v0",
    "p3_fill_v0",
    "rephrased_v0",
    "conceptual_v0",
)


def _vs(problem_id: uuid.UUID, strategy_tag: str | None = CORPUS_REPLAY_STRATEGY_TAG) -> Any:
    row = VerifiedSolution(
        problem_id=problem_id,
        grade=WhsSolutionGrade.VERIFIED,
        solution_path={"conditions": [], "answer": {}, "steps": ["x**2 - 5*x", "(x)*(x - 5)"]},
        strategy_tag=strategy_tag,
        answer=None,
    )
    row.id = uuid.uuid4()
    row.created_at = _NOW
    return row


def _plan(rows: list[Any], slugs: dict[uuid.UUID, str] | None) -> Any:
    return plan_promotion(
        rows,
        existing_problem_ids={row.problem_id for row in rows},
        already_promoted_path_ids=set(),
        problem_ids_with_steps=set(),
        now=_NOW,
        slug_by_problem=slugs,
    )


# ── 문항군 경계 ──────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("slug", "expected"),
    [
        ("wm-skel", "algebraic"),
        ("wm-skel-0047d3954eb8-rephrased", "algebraic"),
        ("wm-indseq-1a2b3c4d5e6f", "inductive"),
        ("wm-p3-diff-power-1a2b3c4d5e6f", "algebraic"),
        ("wm-p3-diff-power-pattern-1a2b3c4d5e6f", "algebraic"),
    ],
)
def test_family_lookup(slug: str, expected: str) -> None:
    assert corpus_replay_approach_for_slug(slug) == expected


def test_family_boundary_is_hyphen_not_prefix() -> None:
    """`wm-trig`가 `wm-trigX`를, `wm-indseq`가 `wm-indseqX`를 잡으면 안 된다(경계 = `-`)."""
    assert corpus_replay_approach_for_slug("wm-indseqx-1a2b3c4d5e6f") is None
    assert corpus_replay_approach_for_slug("wm-trigonometry-1a2b3c4d5e6f") is None
    assert corpus_replay_approach_for_slug("wm-calc-extq-1a2b3c4d5e6f") is None


def test_longest_family_wins() -> None:
    """더 긴 문항군이 우선한다 — 표 순서와 무관하게(짧은 쪽 값을 일부러 다르게 만든 표로 확인)."""
    table = dict(CORPUS_REPLAY_APPROACH_BY_FAMILY)
    try:
        CORPUS_REPLAY_APPROACH_BY_FAMILY["wm-p3-diff-power"] = "visual"
        assert corpus_replay_approach_for_slug("wm-p3-diff-power-pattern-1a2b") == "algebraic"
        assert corpus_replay_approach_for_slug("wm-p3-diff-power-1a2b") == "visual"
    finally:
        CORPUS_REPLAY_APPROACH_BY_FAMILY.clear()
        CORPUS_REPLAY_APPROACH_BY_FAMILY.update(table)


def test_unknown_or_missing_slug_is_none() -> None:
    assert corpus_replay_approach_for_slug(None) is None
    assert corpus_replay_approach_for_slug("") is None
    assert corpus_replay_approach_for_slug("wm-unknown-family") is None


# ── plan_promotion 배선 ──────────────────────────────────────────────────
def test_corpus_replay_row_promotes_via_table() -> None:
    pid = uuid.uuid4()
    plan = _plan([_vs(pid)], {pid: "wm-indseq-1a2b3c4d5e6f"})
    assert plan.report.promoted == 1
    assert plan.report.approach_from_corpus_family == 1
    assert plan.report.queued_approach_unmappable == 0
    assert plan.planned[0].path.approach_type == "inductive"


def test_corpus_replay_row_without_known_family_still_queues() -> None:
    """표 밖 문항군·slug 미상은 지금처럼 검수 큐 — 추측 금지가 그대로다."""
    known, unknown, no_slug = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    rows = [_vs(known), _vs(unknown), _vs(no_slug)]
    plan = _plan(rows, {known: "wm-skel", unknown: "wm-new-generator-1a2b"})
    assert plan.report.promoted == 1
    assert plan.report.approach_from_corpus_family == 1
    assert plan.report.queued_approach_unmappable == 2


def test_table_applies_only_to_corpus_replay_tag() -> None:
    """다른 미지 태그(LLM 자유 텍스트 등)는 slug가 표에 있어도 매핑하지 않는다."""
    pid = uuid.uuid4()
    plan = _plan([_vs(pid, strategy_tag="직관적")], {pid: "wm-skel"})
    assert plan.report.promoted == 0
    assert plan.report.approach_from_corpus_family == 0
    assert plan.report.queued_approach_unmappable == 1


# ── DB 래퍼 배선 (가짜 세션) ─────────────────────────────────────────────
class _Result:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[Any]:
        return self._items


class _Session:
    def __init__(self, results: list[_Result]) -> None:
        self._results = list(results)
        self.added: list[Any] = []

    async def execute(self, _stmt: Any) -> _Result:
        return self._results.pop(0)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None


@pytest.mark.asyncio
async def test_wrapper_reads_slugs_for_corpus_replay_rows() -> None:
    """재생 행이 있으면 5번째 조회로 slug를 읽어 표를 적용한다."""
    pid = uuid.uuid4()
    row = _vs(pid)
    session = _Session(
        [
            _Result([row]),  # ① 전 행
            _Result([pid]),  # ② problem 실재
            _Result([]),  # ③ 기존 경로 id
            _Result([]),  # ④ 기존 단계 선점
            _Result([(pid, "wm-p3-diff-tangent-1a2b3c4d5e6f")]),  # ⑤ slug
        ]
    )
    plan = await promote_verified_solutions(cast(AsyncSession, session))
    assert plan.report.approach_from_corpus_family == 1
    headers = [o for o in session.added if isinstance(o, SolutionPathOrm)]
    assert [h.approach_type for h in headers] == ["algebraic"]


# ── 코퍼스 정합 — 표가 은행을 전수로 덮는가 ──────────────────────────────
def _families_with_steps() -> dict[str, str]:
    found: dict[str, str] = {}
    for bank in _COVERED_BANKS:
        path = _REPO_ROOT / "data" / "corpus" / f"problem_bank_{bank}" / "problems.jsonl"
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            steps = (record.get("verify") or {}).get("solution_steps") or []
            if len(steps) >= 2:
                found[record["slug"]] = bank
    return found


def test_table_covers_every_stepped_problem_in_covered_banks() -> None:
    """은행에 새 문항군이 생기면 red — 표에 넣을지(어떤 유형으로)는 사람이 정한다."""
    slugs = _families_with_steps()
    assert len(slugs) > 1000, f"스캔 대상이 너무 적다({len(slugs)}) — 경로·형식을 확인하라"
    unmapped = sorted(s for s in slugs if corpus_replay_approach_for_slug(s) is None)
    assert unmapped == [], f"승인 표에 없는 문항 {len(unmapped)}건: {unmapped[:10]}"


def test_table_has_no_dead_family() -> None:
    """표의 모든 문항군이 은행에 실재한다 — 죽은 항목은 승인 근거가 없는 값이다."""
    slugs = list(_families_with_steps())
    dead = [
        family
        for family in CORPUS_REPLAY_APPROACH_BY_FAMILY
        if not any(s == family or s.startswith(family + "-") for s in slugs)
    ]
    assert dead == []


def test_table_values_are_closed_approach_types() -> None:
    from whymath_backend.l3.solution_path import APPROACH_TYPES

    assert set(CORPUS_REPLAY_APPROACH_BY_FAMILY.values()) <= set(APPROACH_TYPES)
    assert re.fullmatch(r"[a-z-]+", CORPUS_REPLAY_STRATEGY_TAG)
