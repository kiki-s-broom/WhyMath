"""R2-02 (헌법 제5조 ②·제9조 ③ · 판례 P0001) — 중복 게이트 판정과 무관하게 모든 후보 문항은
사람 품질 판정(F1~F8)을 받는다.

판례 P0001: 중복으로 표시된 문항 9개를 보류로 넘겨 15개 중 6개만 품질 판정을 받았다 —
**중복 게이트가 품질 게이트를 대체**했다. 이 파일은 그 대체가 *코드 경로에서* 일어나지 않음을
지킨다.

지키는 것(코드 경로 불변식 — DB 불필요):
  ① 비수용 상태 4종 중 후보가 있는 3종(needs_review·rejected_gate·rejected_duplicate)이
     검수 큐 → 검수 항목 → 검수 세션의 *같은 길*을 지나 똑같이 판정(finished)을 받는다.
     `rejected_duplicate`만 다른 길로 새지 않는다.
  ② 큐 입력 단계가 status로 걸러내지 않는다 — `rejected_duplicate` 행도 항목이 된다.
  ③ 상태 어휘 동기 — `GenerationOutcome.status`에 새 상태가 생기면 이 파일이 실패해 큐 우선순위
     표(`_STATUS_PRIORITY`)와 수용 판정(`ACCEPTED_STATUSES`)을 함께 갱신하도록 강제한다.
  ④ 보류([s])는 판정이 아니다 — 종결(finished)이 남지 않으므로 `completed_slugs`에서 빠지고,
     재개(`--resume`) 때 다시 제시된다. 보류가 '판정 없이 통과'로 굳지 않는 유일한 장치다.

지키지 못하는 것(정직한 공백): 판정되지 않고 남은 보류분을 *상한으로 막는* 장치는 없다 —
P0001이 정확히 이 경로였다. 보류 허용 여부·'모든 후보'의 범위(라이브 큐만인가, 결정론 배치
산출물도 포함인가)는 Kiki 정책 결정이다(`docs/standards/coding_constitution_transplant.md` P3).
"""

from __future__ import annotations

import io
import json
import typing
from datetime import UTC, datetime
from pathlib import Path

import pytest

from whymath_backend.harness.batch_safety import ACCEPTED_STATUSES
from whymath_backend.harness.needs_review_worklist import (
    _STATUS_PRIORITY,
    append_review_queue_jsonl,
    entry_from_outcome,
)
from whymath_backend.harness.review_session import (
    completed_slugs,
    load_review_items,
    run_review_session,
)
from whymath_backend.l3.equivalent.acceptance import AcceptanceVerdict
from whymath_backend.l3.equivalent.generator import CandidateProblem
from whymath_backend.l3.equivalent.orchestrator import GenerationOutcome
from whymath_backend.schema.enums import (
    AnswerFormat,
    Curriculum,
    GenerationType,
    LicenseType,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem import Problem
from whymath_backend.schema.provenance import ContentProvenance

CANDIDATE_STATUSES = ("needs_review", "rejected_gate", "rejected_duplicate")


def _candidate(slug: str) -> CandidateProblem:
    problem = Problem(
        slug=slug,
        source_type=SourceType.자체생성,
        curriculum_version=Curriculum.REVISION_2022,
        valid_from_year=2022,
        subject=Subject.미적분,
        unit_codes=["CAL-INT-DEF"],
        difficulty_overall=3.0,
        answer_format=AnswerFormat.자연수,
        achievement_standard_codes=["[12미적01-01]"],
        question_text="주어진 이차식의 자연수 근을 구하시오.",
        answer="3",
        answer_explanation="주어진 조건을 풀면 정답은 자연수 세 입니다.",
    )
    return CandidateProblem(
        problem=problem,
        provenance=ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
        ),
        conditions="x**2 - 5*x + 6 = 0",
        answer_map={"x": "3"},
        answer_selection="largest",
    )


def _outcome(status: str, slug: str | None) -> GenerationOutcome:
    return GenerationOutcome(
        status=status,  # type: ignore[arg-type]
        candidate=_candidate(slug) if slug is not None else None,
        acceptance=AcceptanceVerdict(
            accepted=False,
            copyright_ok=True,
            verification="verified",
            hygiene_ok=True,
            equivalence="검수필요",
            equivalence_score=0.8,
            reasons=["기계 사유"],
        ),
        reasons=["기계 사유"],
    )


def _queue(tmp_path: Path, statuses: tuple[str, ...]) -> Path:
    """상태별로 후보 1건씩 큐에 적재한다 — 실제 적재 함수(append_review_queue_jsonl)를 쓴다."""
    path = tmp_path / "queue.review.jsonl"
    for status in statuses:
        outcome = _outcome(status, f"cu-{status.replace('_', '-')}")
        payload = {"slug": f"cu-{status.replace('_', '-')}", "question_text": "q"}
        append_review_queue_jsonl(
            path, entry_from_outcome(outcome, run_id="r1", candidate_payload=payload)
        )
    return path


def _review(
    tmp_path: Path, items: list, keystrokes: str, *, resume: bool = False
):  # type: ignore[no-untyped-def]
    ticks = iter(range(0, 10**12, 60_000_000_000))
    return run_review_session(
        items,
        events_path=tmp_path / "events.jsonl",
        verdicts_path=tmp_path / "verdicts.jsonl",
        reviewer_id="kiki",
        stream_in=io.StringIO(keystrokes),
        stream_out=io.StringIO(),
        monotonic_ns=lambda: next(ticks),
        now_utc=lambda: datetime(2026, 10, 5, 12, 0, tzinfo=UTC),
        resume=resume,
    )


def _events(tmp_path: Path) -> list[dict[str, object]]:
    path = tmp_path / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ── ① ② 같은 길 ─────────────────────────────────────────────────────────────
def test_every_candidate_status_becomes_a_review_item(tmp_path: Path) -> None:
    items, errors = load_review_items(_queue(tmp_path, CANDIDATE_STATUSES))
    assert errors == []
    assert {i.status for i in items} == set(CANDIDATE_STATUSES)


def test_duplicate_rejected_candidate_is_not_filtered_out_of_the_queue(tmp_path: Path) -> None:
    """P0001 — 중복 표시가 큐 입구에서 후보를 빼 버리지 않는다."""
    items, _ = load_review_items(_queue(tmp_path, ("rejected_duplicate",)))
    assert [i.slug for i in items] == ["cu-rejected-duplicate"]


@pytest.mark.parametrize("status", CANDIDATE_STATUSES)
def test_each_candidate_gets_a_finished_verdict_regardless_of_status(
    tmp_path: Path, status: str
) -> None:
    items, _ = load_review_items(_queue(tmp_path, (status,)))
    outcome = _review(tmp_path, items, "r\nF2\n사유\n")
    assert outcome.rejected == 1 and outcome.aborted == 0
    finished = [e for e in _events(tmp_path) if e["event_type"] == "finished"]
    assert [e["cu_slug"] for e in finished] == [items[0].slug]
    assert finished[0]["failure_code"] == "F2"  # F1~F8 품질 판정이 코드로 남는다


def test_duplicate_flag_does_not_shorten_the_review(tmp_path: Path) -> None:
    """같은 판정 입력이 세 상태 모두에서 같은 모양의 기록을 낳는다(상태가 길을 바꾸지 않는다)."""
    shapes = []
    for status in CANDIDATE_STATUSES:
        sub = tmp_path / status
        sub.mkdir()
        items, _ = load_review_items(_queue(sub, (status,)))
        _review(sub, items, "a\n")
        shapes.append([(e["event_type"], e["verdict"]) for e in _events(sub)])
    assert shapes[0] == shapes[1] == shapes[2] == [("started", None), ("finished", "approved")]


# ── ③ 어휘 동기 ──────────────────────────────────────────────────────────────
def test_status_vocabulary_is_in_sync_with_queue_priority_and_accepted_set() -> None:
    hint = typing.get_type_hints(GenerationOutcome)["status"]
    all_statuses = set(typing.get_args(hint))
    assert all_statuses, "status Literal을 읽지 못했다 — 0건 통과 금지"
    assert all_statuses - set(ACCEPTED_STATUSES) == set(_STATUS_PRIORITY)
    assert set(ACCEPTED_STATUSES) <= all_statuses


# ── ④ 보류는 판정이 아니다 ───────────────────────────────────────────────────
def test_skip_leaves_no_finished_event_and_is_offered_again_on_resume(tmp_path: Path) -> None:
    items, _ = load_review_items(_queue(tmp_path, ("rejected_duplicate",)))
    outcome = _review(tmp_path, items, "s\n")
    assert outcome.aborted == 1 and outcome.rejected == 0 and outcome.approved == 0
    assert completed_slugs(tmp_path / "events.jsonl") == set()  # 보류는 종결이 아니다
    again = _review(tmp_path, items, "a\n", resume=True)
    assert again.approved == 1 and again.skipped_completed == 0  # 재개가 다시 제시한다
