"""힌트 정답 누설 사람 판정 — 표본 추출 + 맹검 판정 세션 CLI (EOS-210).

두 하위 명령이 있다. 기록 계약·표본 규칙·의미 축 산술의 정본은 `ops/hint_human_verdicts`이고,
판정을 읽어 G3 값을 내는 쪽은 `ops/g3_content_measures`다.

  sample  회차 CU + 힌트 JSONL → 표본 매니페스트(`<round>-review/hint_sample_manifest.json`).
          (나) 의미 누설 표본(verified L1·L2 · 기본 30건 · seed는 모집단에서 유도 — 고를 수 없다)과
          (가) 기계 판정 불가 L1·L2 전수를 한 파일에 싣는다. 이미 있으면 **덮어쓰지 않는다**
          (같은 내용이면 그대로 두고 통과, 다르면 거부).
  review  매니페스트의 판정 대상을 하나씩 보여 주고 판정(누설/아님)과 근거를 받아
          `<round>-review/hint_verdicts.jsonl`에 1건씩 즉시 append한다.

맹검 — 헌법 R19-01 ("사람이 판정을 입력하기 전에 AI 참고 판정을 보여주지 않는다")
-----------------------------------------------------------------------------
화면에 내는 것은 `hint_human_verdicts.review_view`의 다섯 칸뿐이다 — 문항·선택지·**정답**(누설을
판정하려면 알아야 한다)·힌트 단계·힌트 본문. 내지 않는 것:

  - 기계 판정(글자·값 축 결과)과 `Hint.gate_report`(게이트 판정)·`reveals`(선언 노출량)
  - 그 힌트가 왜 물어졌는지(`purpose` — "기계가 판정하지 못했다"는 것 자체가 기계의 신호다)
  - 이미 기록된 판정(자기 것·다른 판정자 것 모두) — 판정 수 집계도 내지 않는다

표본·전수 대상은 seed로 섞어 한 줄로 낸다(목적별로 묶어 내면 순서가 곧 목적을 알려 준다).
`sample`은 판정 전에 실행되지만 개별 힌트의 기계 판정을 출력하지 않는다(건수만 낸다).

EOS-199 검수 도구 교훈 이식
--------------------------
  - **쓰기 전 검증** — 판정은 `HintHumanVerdict` 모델로 만든 뒤에만 쓴다(빈 근거·잘못된 ID는
    생성 단계에서 거부되고 다시 묻는다).
  - **기록 파일 쓰기 가능 사전 점검** — 첫 항목을 보여 주기 전에 판정 파일을 append로 열어 본다
    (Windows에서 Excel로 열어 두면 잠긴다). 실패하면 아무것도 보여 주지 않고 exit 2.
  - **기록 실패 시 세션 정지** — append가 실패하면 그 자리에서 멈춘다(exit 2). 다음 항목으로
    넘어가면 "판정했는데 기록 안 된" 항목이 조용히 생긴다.
  - **입력 잠금** — 항목을 띄운 뒤 `INPUT_LOCK_SECONDS` 안에 들어온 판정은 버리고 다시 묻는다.
    붙여넣기 잔여 줄이 판정으로 먹히는 것을 막는다(2026-09-22 카나리 검수 실측 유형). 판정 뒤에는
    "기록할까요(y)"를 한 번 더 묻는다.
  - **중단·재개** — 종료(q)·EOF는 기록된 것까지 남기고 정상 종료한다. 다시 실행하면 같은 표본에
    대해 **이 판정자가 지금 내용으로** 이미 기록한 항목을 건너뛴다. 재판정은 `--rejudge <hint_id>`로
    지정한 항목만 다시 묻는다(append — 앞선 판정은 지우지 않는다).

exit code
---------
  sample : 0 매니페스트 작성(또는 같은 내용이 이미 있음) / 2 입력 오류·대상 0건·다른 매니페스트가
           이미 있음·쓰기 실패
  review : 0 정상 종료(중단 포함 — 중단도 기록된 사실이다) / 1 입력 실패(회차·힌트·매니페스트·
           기존 판정 파일 손상·판정자 ID 형식) / 2 기록 실패(세션 정지)

사용:
    python -m whymath_backend.harness.hint_verdict_session sample --round R \\
        --hints-jsonl data/runs/R-local/cu.hints.jsonl
    python -m whymath_backend.harness.hint_verdict_session review --round R \\
        --hints-jsonl data/runs/R-local/cu.hints.jsonl --reviewer kiki
"""

from __future__ import annotations

import argparse
import random
import re
import sys
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from pydantic import ValidationError

from whymath_backend.l4.hint_content.models import Hint
from whymath_backend.ops.g3_content_measures import (
    discover_round,
    hint_machine_verdict,
    load_hints,
)
from whymath_backend.ops.hint_human_verdicts import (
    DEFAULT_SAMPLE_SIZE,
    RATIONALE_MAX_LENGTH,
    REVIEWER_ID_PATTERN,
    HintHumanVerdict,
    HintVerdict,
    SampleManifest,
    append_verdict,
    build_manifest,
    hint_review_fingerprint,
    load_manifest,
    load_verdicts,
    review_view,
    sample_population,
    write_manifest,
)
from whymath_backend.ops.provenance_audit import default_runs_root

__all__ = [
    "DEFAULT_MANIFEST_NAME",
    "DEFAULT_VERDICTS_NAME",
    "EXIT_INPUT",
    "EXIT_OK",
    "EXIT_RECORD",
    "INPUT_LOCK_SECONDS",
    "SessionOutcome",
    "WorkItem",
    "machine_undecided_hint_ids",
    "main",
    "prepare_work",
    "render_item",
    "run_review_session",
]

EXIT_OK = 0
EXIT_INPUT = 1
EXIT_RECORD = 2
INPUT_LOCK_SECONDS = 2.0
DEFAULT_MANIFEST_NAME = "hint_sample_manifest.json"
DEFAULT_VERDICTS_NAME = "hint_verdicts.jsonl"
_ORDER_SALT = 0x5EED_0210  # 표시 순서 섞기용(표본 추출 seed와 다른 난수열)
_ZERO_TOLERANCE_LEVELS = frozenset({1, 2})


@dataclass(frozen=True, slots=True)
class WorkItem:
    """판정 대상 1건 — 힌트와 그 CU 행. 목적(purpose)은 화면에 내지 않는다(모듈 docstring)."""

    hint: Hint
    cu_row: Mapping[str, Any]


@dataclass(slots=True)
class SessionOutcome:
    """세션 요약 — 기록·건너뜀·이미 판정·중단 여부."""

    total: int = 0
    already_done: int = 0
    recorded: int = 0
    skipped: int = 0
    aborted: bool = False
    record_failed: bool = False
    recorded_hint_ids: list[str] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────
# 입력 — 회차 CU·힌트·매니페스트
# ──────────────────────────────────────────────────────────────────────────
def _load_inputs(
    runs_root: Path, round_id: str, hint_paths: Sequence[Path]
) -> tuple[list[dict[str, Any]], list[Hint], list[str]]:
    round_input = discover_round(runs_root, round_id)
    cu_rows = [row for run in round_input.run_dirs for row in run.cu_rows]
    hints, hint_errors = load_hints(hint_paths)
    errors = [*round_input.errors, *hint_errors]
    if not hint_paths:
        errors.append("--hints-jsonl이 없다 — 판정할 힌트가 없다")
    return cu_rows, hints, errors


def machine_undecided_hint_ids(
    cu_rows: Sequence[Mapping[str, Any]], hints: Sequence[Hint]
) -> list[str]:
    """(가) 대상 = 회차 CU에 붙는 L1·L2 힌트 중 기계 판정 불가(None) 전수(측정기와 같은 판정)."""
    rows_by_problem: dict[str, Mapping[str, Any]] = {}
    for row in cu_rows:
        rows_by_problem.setdefault(str(row.get("problem_id")), row)
    undecided: list[str] = []
    for hint in hints:
        cu_row = rows_by_problem.get(str(hint.solution_step_ref.problem_id))
        if cu_row is None or hint.level not in _ZERO_TOLERANCE_LEVELS:
            continue
        answer = cu_row.get("answer")
        if hint_machine_verdict(hint, answer if isinstance(answer, str) else None) is None:
            undecided.append(hint.hint_id)
    return sorted(set(undecided))


def prepare_work(
    manifest: SampleManifest,
    cu_rows: Sequence[Mapping[str, Any]],
    hints: Sequence[Hint],
) -> tuple[list[WorkItem], list[str]]:
    """매니페스트 → 판정 대상 목록(seed로 섞은 결정론 순서), 오류.

    매니페스트 모집단이 현재 입력과 다르면 거부한다 — 판정자가 본 내용과 표본을 정한 내용이
    달라진다.
    """
    errors: list[str] = []
    population, population_errors = sample_population(cu_rows, hints)
    errors.extend(population_errors)
    if population != manifest.population:
        errors.append(
            "매니페스트 모집단이 현재 힌트 입력과 다르다 — 힌트·정답이 바뀌었거나 다른 회차다"
        )
    rows_by_problem: dict[str, Mapping[str, Any]] = {}
    for row in cu_rows:
        rows_by_problem.setdefault(str(row.get("problem_id")), row)
    hints_by_id = {hint.hint_id: hint for hint in hints}
    order = sorted(manifest.work_hint_ids)
    random.Random(manifest.seed ^ _ORDER_SALT).shuffle(order)
    items: list[WorkItem] = []
    for hint_id in order:
        hint = hints_by_id.get(hint_id)
        cu_row = rows_by_problem.get(str(hint.solution_step_ref.problem_id)) if hint else None
        if hint is None or cu_row is None:
            errors.append(f"매니페스트의 hint_id {hint_id}가 현재 입력에 없다")
            continue
        items.append(WorkItem(hint=hint, cu_row=cu_row))
    return items, errors


# ──────────────────────────────────────────────────────────────────────────
# 화면 — review_view만 낸다(기계 판정·목적·기존 판정 비노출)
# ──────────────────────────────────────────────────────────────────────────
def render_item(out: TextIO, index: int, total: int, item: WorkItem) -> None:
    """판정 대상 1건을 그린다. `review_view` 밖의 어떤 필드도 출력하지 않는다(R19-01)."""
    view = review_view(item.cu_row, item.hint)
    rule = "─" * 60
    lines = [
        "",
        rule,
        f"[{index}/{total}] 힌트 {item.hint.hint_id}",
        rule,
        f"문항: {view['question_text'] if view['question_text'] else '(문항 본문 없음)'}",
    ]
    if view["choices"]:
        lines.extend(f"  선택지 {n}: {choice}" for n, choice in enumerate(view["choices"], 1))
    lines.append(f"정답: {view['answer'] if view['answer'] is not None else '(정답 없음)'}")
    lines.append(f"힌트 단계: L{view['hint_level']}")
    lines.append(f"힌트 본문: {view['hint_content']}")
    lines.append(rule)
    out.write("\n".join(lines) + "\n")
    out.flush()


def _read_line(stream: TextIO, out: TextIO, prompt: str) -> str | None:
    """프롬프트 후 한 줄 — EOF면 None."""
    out.write(prompt)
    out.flush()
    line = stream.readline()
    if line == "":
        return None
    return line.strip()


_VERDICT_KEYS: dict[str, HintVerdict] = {"1": HintVerdict.LEAKED, "2": HintVerdict.NOT_LEAKED}
_VERDICT_LABEL: dict[HintVerdict, str] = {
    HintVerdict.LEAKED: "누설",
    HintVerdict.NOT_LEAKED: "누설 아님",
}
_SKIP = "skip"
_QUIT = "quit"


def _ask_verdict(
    stream: TextIO, out: TextIO, clock: Callable[[], float], shown_at: float
) -> HintVerdict | str | None:
    """판정 키 1개. 잠금 시간 안의 입력은 버린다. 반환: 판정·`skip`·`quit`·None(EOF)."""
    while True:
        answer = _read_line(stream, out, "판정 [1=누설 · 2=누설 아님 · s=건너뛰기 · q=종료]: ")
        if answer is None:
            return None
        if clock() - shown_at < INPUT_LOCK_SECONDS:
            out.write(
                f"  화면을 읽기 전에 입력됐습니다({INPUT_LOCK_SECONDS:.0f}초 잠금) — "
                "내용을 읽고 다시 입력하세요.\n"
            )
            continue
        key = answer.lower()
        if key in _VERDICT_KEYS:
            return _VERDICT_KEYS[key]
        if key == "s":
            return _SKIP
        if key == "q":
            return _QUIT
        out.write("  1·2·s·q 중 하나를 입력하세요.\n")


def _ask_rationale(stream: TextIO, out: TextIO) -> str | None:
    """근거 1줄 — 비었거나 너무 길면 다시 묻는다. EOF면 None."""
    while True:
        text = _read_line(stream, out, "근거(왜 그렇게 판정했는지 한 줄): ")
        if text is None:
            return None
        if not text:
            out.write("  근거가 비었습니다 — 근거 없는 판정은 기록하지 않습니다.\n")
            continue
        if len(text) > RATIONALE_MAX_LENGTH:
            out.write(f"  근거가 {RATIONALE_MAX_LENGTH}자를 넘습니다 — 줄여서 다시 입력하세요.\n")
            continue
        return text


# ──────────────────────────────────────────────────────────────────────────
# 세션
# ──────────────────────────────────────────────────────────────────────────
def _preflight_writable(path: Path) -> OSError | None:
    """판정 파일을 append로 열어 본다(없으면 만든다 · 내용은 바꾸지 않는다)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8"):
            pass
    except OSError as exc:
        return exc
    return None


def _already_done(
    existing: Sequence[HintHumanVerdict],
    items: Sequence[WorkItem],
    *,
    reviewer: str,
    sample_id: str,
) -> set[str]:
    """이 판정자가 이 표본에 대해 **지금 내용으로** 이미 기록한 hint_id."""
    fingerprints = {
        item.hint.hint_id: hint_review_fingerprint(item.cu_row, item.hint) for item in items
    }
    return {
        verdict.hint_id
        for verdict in existing
        if verdict.reviewer == reviewer
        and verdict.sample_id == sample_id
        and fingerprints.get(verdict.hint_id) == verdict.content_fingerprint
    }


def run_review_session(
    items: Sequence[WorkItem],
    *,
    manifest: SampleManifest,
    verdicts_path: Path,
    reviewer: str,
    done: set[str],
    stream: TextIO,
    out: TextIO,
    clock: Callable[[], float] = time.monotonic,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    session_id: uuid.UUID | None = None,
) -> SessionOutcome:
    """대화형 판정 루프. `done`의 항목은 건너뛴다(재개). 기록 실패면 즉시 멈춘다."""
    session = session_id or uuid.uuid4()
    pending = [item for item in items if item.hint.hint_id not in done]
    outcome = SessionOutcome(total=len(items), already_done=len(items) - len(pending))
    out.write(
        f"판정 세션 — 전체 {outcome.total}건 · 이미 판정 {outcome.already_done}건(건너뜀) · "
        f"남음 {len(pending)}건\n판정 파일: {verdicts_path}\n"
    )
    for position, item in enumerate(pending, start=1):
        index = outcome.already_done + position
        render_item(out, index, outcome.total, item)
        shown_at = clock()
        while True:
            choice = _ask_verdict(stream, out, clock, shown_at)
            if choice is None or choice == _QUIT:
                outcome.aborted = True
                return outcome
            if choice == _SKIP:
                outcome.skipped += 1
                break
            assert isinstance(choice, HintVerdict)
            rationale = _ask_rationale(stream, out)
            if rationale is None:
                outcome.aborted = True
                return outcome
            confirm = _read_line(
                stream,
                out,
                f"기록: {_VERDICT_LABEL[choice]} · 근거: {rationale} — 맞으면 y, 다시 하려면 n: ",
            )
            if confirm is None:
                outcome.aborted = True
                return outcome
            if confirm.lower() != "y":
                out.write("  다시 판정합니다.\n")
                continue
            try:
                verdict = HintHumanVerdict(
                    schema_version="hint-human-verdict/v1",
                    hint_id=item.hint.hint_id,
                    problem_id=item.hint.solution_step_ref.problem_id,
                    reviewer=reviewer,
                    judged_at=now(),
                    verdict=choice,
                    rationale=rationale,
                    purpose=manifest.purpose_of(item.hint.hint_id),
                    sample_id=manifest.sample_id,
                    content_fingerprint=hint_review_fingerprint(item.cu_row, item.hint),
                    review_session_id=session,
                    bypassed=False,
                )
            except ValidationError as exc:
                out.write(f"  판정이 기록 계약을 통과하지 못했습니다 — {type(exc).__name__}\n")
                continue
            try:
                append_verdict(verdicts_path, verdict)
            except OSError as exc:
                out.write(
                    f"기록 실패 — {type(exc).__name__}. 세션을 멈춥니다(힌트 "
                    f"{item.hint.hint_id}의 이번 판정은 기록되지 않았다).\n"
                )
                outcome.record_failed = True
                return outcome
            outcome.recorded += 1
            outcome.recorded_hint_ids.append(item.hint.hint_id)
            out.write(f"  기록했습니다({index}/{outcome.total}).\n")
            break
    return outcome


def render_summary(outcome: SessionOutcome) -> str:
    """요약 — 판정 내용(누설 건수 등)은 내지 않는다(다음 판정자·재판정의 맹검 유지)."""
    remaining = outcome.total - outcome.already_done - outcome.recorded
    state = "기록 실패로 정지" if outcome.record_failed else ("중단" if outcome.aborted else "완료")
    return (
        f"SESSION_STATE={state}\nSESSION_TOTAL={outcome.total}\n"
        f"SESSION_ALREADY_DONE={outcome.already_done}\nSESSION_RECORDED={outcome.recorded}\n"
        f"SESSION_SKIPPED={outcome.skipped}\nSESSION_REMAINING={remaining}\n"
    )


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────
def _review_dir(runs_root: Path, round_id: str) -> Path:
    return runs_root / f"{round_id}-review"


def _cmd_sample(args: argparse.Namespace, out: TextIO) -> int:
    runs_root = args.runs_root if args.runs_root is not None else default_runs_root()
    manifest_path = args.manifest or _review_dir(runs_root, args.round) / DEFAULT_MANIFEST_NAME
    cu_rows, hints, errors = _load_inputs(runs_root, args.round, args.hints_jsonl or [])
    population, population_errors = sample_population(cu_rows, hints)
    errors.extend(population_errors)
    if errors:
        out.write("".join(f"INPUT_ERROR={e}\n" for e in errors) + "MANIFEST_WRITTEN=False\n")
        return 2
    undecided = machine_undecided_hint_ids(cu_rows, hints)
    manifest = build_manifest(
        round_id=args.round,
        population=population,
        machine_undecided_hint_ids=undecided,
        size=args.size,
        created_at=datetime.now(UTC),
    )
    summary = (
        f"ROUND={manifest.round_id}\nSAMPLE_ID={manifest.sample_id}\nSEED={manifest.seed}\n"
        f"POPULATION={len(manifest.population)}\nSIZE_REQUESTED={manifest.size_requested}\n"
        f"SAMPLE_SIZE={len(manifest.sample_hint_ids)}\n"
        f"MACHINE_UNDECIDED={len(manifest.machine_undecided_hint_ids)}\n"
        f"WORK_ITEMS={len(manifest.work_hint_ids)}\n"
        f"SEMANTIC_SAMPLE_REACHES_30={len(manifest.sample_hint_ids) >= 30}\n"
        f"MANIFEST_PATH={manifest_path}\n"
    )
    out.write(summary)
    if not manifest.work_hint_ids:
        out.write(
            "INPUT_ERROR=판정 대상 0건(모집단·기계 판정 불가 모두 0)\nMANIFEST_WRITTEN=False\n"
        )
        return 2
    if manifest_path.exists():
        existing, load_errors = load_manifest(manifest_path)
        same = (
            existing is not None
            and existing.sample_id == manifest.sample_id
            and existing.population == manifest.population
            and existing.machine_undecided_hint_ids == manifest.machine_undecided_hint_ids
        )
        if same:
            out.write("MANIFEST_WRITTEN=EXISTS_IDENTICAL\n")
            return 0
        reasons = "; ".join(load_errors) or "내용이 다르다"
        out.write(
            f"INPUT_ERROR=다른 매니페스트가 이미 있다({reasons}) — 덮어쓰지 않는다\n"
            "MANIFEST_WRITTEN=False\n"
        )
        return 2
    try:
        write_manifest(manifest_path, manifest)
    except OSError as exc:
        out.write(f"WRITE_ERROR={type(exc).__name__}\nMANIFEST_WRITTEN=False\n")
        return 2
    out.write("MANIFEST_WRITTEN=True\n")
    return 0


def _cmd_review(
    args: argparse.Namespace,
    stream: TextIO,
    out: TextIO,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    if not re.fullmatch(REVIEWER_ID_PATTERN, args.reviewer or ""):
        out.write(
            "INPUT_ERROR=판정자 ID 형식 — 영문·숫자로 시작하는 1~32자(영문·숫자·_ . -)만 쓴다"
            "(이름 대신 짧은 ID)\n"
        )
        return EXIT_INPUT
    runs_root = args.runs_root if args.runs_root is not None else default_runs_root()
    review_dir = _review_dir(runs_root, args.round)
    manifest_path = args.manifest or review_dir / DEFAULT_MANIFEST_NAME
    verdicts_path = args.verdicts or review_dir / DEFAULT_VERDICTS_NAME
    cu_rows, hints, errors = _load_inputs(runs_root, args.round, args.hints_jsonl or [])
    manifest, manifest_errors = load_manifest(manifest_path)
    errors.extend(manifest_errors)
    if manifest is not None and manifest.round_id != args.round:
        errors.append(f"매니페스트 회차 {manifest.round_id!r} ≠ --round {args.round!r}")
    items: list[WorkItem] = []
    if manifest is not None and not errors:
        items, work_errors = prepare_work(manifest, cu_rows, hints)
        errors.extend(work_errors)
    existing: list[HintHumanVerdict] = []
    if verdicts_path.exists():
        existing, verdict_errors = load_verdicts(verdicts_path)
        errors.extend(f"기존 판정 파일 손상 — 이어 쓰지 않는다: {e}" for e in verdict_errors)
    work_ids = {item.hint.hint_id for item in items}
    unknown = sorted(set(args.rejudge or []) - work_ids)
    if unknown:
        errors.append(f"--rejudge 대상이 판정 대상 목록에 없다: {', '.join(unknown)}")
    if errors or manifest is None:
        out.write("".join(f"INPUT_ERROR={e}\n" for e in errors))
        return EXIT_INPUT
    failure = _preflight_writable(verdicts_path)
    if failure is not None:
        out.write(
            f"WRITE_PREFLIGHT_FAILED={type(failure).__name__} — 판정 파일을 쓸 수 없다"
            "(다른 프로그램이 열고 있는지 확인). 아무것도 묻지 않고 멈춘다.\n"
        )
        return EXIT_RECORD
    done = _already_done(existing, items, reviewer=args.reviewer, sample_id=manifest.sample_id)
    done -= set(args.rejudge or [])
    outcome = run_review_session(
        items,
        manifest=manifest,
        verdicts_path=verdicts_path,
        reviewer=args.reviewer,
        done=done,
        stream=stream,
        out=out,
        clock=clock,
    )
    out.write(render_summary(outcome))
    return EXIT_RECORD if outcome.record_failed else EXIT_OK


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.hint_verdict_session",
        description="힌트 정답 누설 사람 판정 — 표본 추출(sample)·맹검 판정(review) (EOS-210)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("sample", "review"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--round", required=True, help="회차 접두어(<round>-* 좌석)")
        cmd.add_argument("--runs-root", type=Path, default=None, help="회차 루트(기본 data/runs)")
        cmd.add_argument(
            "--hints-jsonl",
            type=Path,
            action="append",
            default=None,
            help="Hint 모델 JSONL(반복 가능 — 측정기에 주는 것과 같은 파일)",
        )
        cmd.add_argument(
            "--manifest",
            type=Path,
            default=None,
            help=f"표본 매니페스트(기본 <runs-root>/<round>-review/{DEFAULT_MANIFEST_NAME})",
        )
        if name == "sample":
            cmd.add_argument(
                "--size", type=int, default=DEFAULT_SAMPLE_SIZE, help="표본 크기(기본 30)"
            )
        else:
            cmd.add_argument(
                "--verdicts",
                type=Path,
                default=None,
                help=f"판정 JSONL(기본 <runs-root>/<round>-review/{DEFAULT_VERDICTS_NAME})",
            )
            cmd.add_argument("--reviewer", required=True, help="판정자 짧은 ID(이름 아님)")
            cmd.add_argument(
                "--rejudge",
                action="append",
                default=None,
                help="이미 판정한 hint_id를 다시 묻는다(반복 가능 · 앞선 판정은 지우지 않는다)",
            )
    return parser


def main(
    argv: list[str] | None = None,
    *,
    stream: TextIO | None = None,
    out: TextIO | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    """CLI 진입점. `stream`·`out`·`clock`은 테스트 주입용(기본 표준입출력·단조 시계)."""
    args = _parser().parse_args(argv)
    output = out if out is not None else sys.stdout
    if args.command == "sample":
        if args.size < 1:
            output.write("INPUT_ERROR=--size는 1 이상\n")
            return 2
        return _cmd_sample(args, output)
    return _cmd_review(args, stream if stream is not None else sys.stdin, output, clock)


if __name__ == "__main__":  # pragma: no cover — 모듈 실행 진입점
    raise SystemExit(main())
