"""기존 문항 6슬롯 결정론 백필 CLI (P3-05 3단계·LLM 0).

`data/corpus/phase3_scope_v1/slot_assignment_rules.yaml`의 규칙을 읽어, 규칙이 가리키는 기존 은행의
승인 문항에 `p3-slot:<id>` 태그 **1개**를 `tags`에 더한다. 규칙이 정본이고 태그는 그 산출물이다.

바이트 계약 (`problem_type_backfill`·`problem_corpus_tag`와 같다)
------------------------------------------------------------
  · 태그를 더할 필요가 없는 줄은 **원문 바이트 그대로** 통과한다(재직렬화 0).
  · 더할 줄만 `tags` 한 키를 바꿔 `json.dumps(..., ensure_ascii=False)`로 다시 쓴다.
    발문·선지·정답·해설·오답 귀속·검산 조건 등 감사가 본 내용은 바이트가 같다 —
    승인 근거가 새 내용으로 옮겨 가지 않는다.
  · 2회 실행은 바이트 동일(멱등): 첫 실행이 태그를 달면 두 번째는 `already-slotted`로 전건 통과한다.
  · 이미 슬롯 태그가 있는 문항은 건드리지 않는다(덮어쓰기 0 — 신규 504건 등).

두 모드
-------
  · 기본            규칙을 적용해 파일을 쓴다. 리포트(JSON)를 stdout에 낸다. 종료 코드 0.
  · `--dry-run`     파일을 쓰지 않고 같은 리포트만 낸다. 종료 코드 0.
  · `--check`       파일을 쓰지 않고, 태그를 더할 문항이 1건이라도 남아 있으면
                    종료 코드 1 + stderr에 이유. 기본·`--dry-run`은 채울 게 있든 없든 항상 0이라
                    게이트가 못 되므로(변별력 없음) 따로 둔다.

문항 자체 오개념 연결 판정은 계측기(`phase3_coverage.reached_misconception_ids`)와 같은 계산을 쓴다.
규칙이 "오개념 유발"로 배정한 문항을 계측기가 다르게 세면, 칸이 채워졌다고 믿는 순간에
안 채워져 있다.

사용법:
    python -m whymath_backend.harness.problem_slot_backfill \\
        [--corpus-root <dir>] [--rules <yaml>] [--dry-run | --check]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from whymath_backend.l1.standards.phase3_coverage import (
    PROBLEM_ELIGIBLE_STATUS,
    ProblemRef,
    load_corpus,
    problem_ref_from_row,
    reached_misconception_ids,
)
from whymath_backend.l1.standards.phase3_scope import load_scope_spec
from whymath_backend.l1.standards.phase3_slot_rules import (
    SlotRules,
    SlotRulesError,
    decide_slot,
    default_rules_path,
    load_slot_rules,
)
from whymath_backend.schema.problem_metadata import slot_tag

__all__ = ["CORPUS_FILE_NAME", "SlotBackfillReport", "main", "run_backfill"]

# harness→whymath_backend→backend→src→repo 루트(다른 harness 모듈과 동일 관례).
_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CORPUS_ROOT = _REPO_ROOT / "data" / "corpus"
CORPUS_FILE_NAME = "problems.jsonl"


@dataclass
class SlotBackfillReport:
    """백필 결과 — 무엇이 몇 건 배정·보류·건너뛰었는지(조용한 실패 금지)."""

    scanned: int = 0
    changed: int = 0
    written: int | None = None
    assigned_by_rule: Counter[str] = field(default_factory=Counter)
    held_by_rule: Counter[str] = field(default_factory=Counter)
    skipped: Counter[str] = field(default_factory=Counter)
    unmatched: int = 0
    corpora: dict[str, int] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "scanned": self.scanned,
            "changed": self.changed,
            "written": self.written,
            "assigned_by_rule": dict(sorted(self.assigned_by_rule.items())),
            "held_by_rule": dict(sorted(self.held_by_rule.items())),
            "skipped": dict(sorted(self.skipped.items())),
            "unmatched": self.unmatched,
            "changed_by_corpus": dict(sorted(self.corpora.items())),
        }


def _default_reaches() -> Callable[[ProblemRef], bool]:
    """실 코퍼스의 크로스링크로 "문항 자체 오개념 연결"을 판정하는 함수를 만든다."""
    spec = load_scope_spec()
    corpus = load_corpus(spec)
    return lambda problem: bool(reached_misconception_ids(problem, corpus))


def _check_scope_exists(rules: SlotRules) -> None:
    """규칙의 범위 개념이 범위 명세에 실재하는지 — 오타 난 개념은 0건 통과가 된다."""
    spec = load_scope_spec()
    known = {c.source_id for c in spec.concepts}
    missing = sorted(rules.scope_concepts - known)
    if missing:
        raise SlotRulesError(f"scope_concepts 가 범위 명세에 없다: {missing}")


def _process_line(
    stripped: str,
    rules: SlotRules,
    reaches: Callable[[ProblemRef], bool],
    report: SlotBackfillReport,
) -> str:
    """JSONL 한 줄을 판정 — 태그를 더할 줄만 다시 쓰고 나머지는 원문 그대로 돌려준다."""
    data: dict[str, Any] = json.loads(stripped)
    report.scanned += 1
    problem = problem_ref_from_row(data)
    if problem is None:
        report.skipped["no-problem-id"] += 1
        return stripped
    decision = decide_slot(rules, problem, reaches, eligible_status=PROBLEM_ELIGIBLE_STATUS)
    if decision.skipped is not None:
        report.skipped[decision.skipped] += 1
        return stripped
    if decision.rule_id is None:
        report.unmatched += 1
        return stripped
    if decision.slot is None:
        report.held_by_rule[decision.rule_id] += 1
        return stripped
    tags = data.get("tags")
    updated = dict(data)
    updated["tags"] = (
        [*tags, slot_tag(decision.slot)] if isinstance(tags, list) else [slot_tag(decision.slot)]
    )
    report.assigned_by_rule[decision.rule_id] += 1
    return json.dumps(updated, ensure_ascii=False)


def run_backfill(
    *,
    corpus_root: Path | None = None,
    rules_path: Path | None = None,
    write: bool = True,
    reaches: Callable[[ProblemRef], bool] | None = None,
    verify_scope: bool = True,
) -> SlotBackfillReport:
    """규칙이 가리키는 은행 전부에 규칙을 적용한다(순수 결정론).

    `reaches`·`verify_scope`는 합성 코퍼스로 시험하려는 테스트의 주입구다.
    운영 경로는 둘 다 기본값이다.
    은행 디렉터리가 없으면 예외다(규칙이 가리키는 코퍼스가 사라졌는데 0건 통과로 위장하지 않는다).
    """
    root = corpus_root if corpus_root is not None else DEFAULT_CORPUS_ROOT
    rules = load_slot_rules(rules_path)
    if verify_scope:
        _check_scope_exists(rules)
    judge = reaches if reaches is not None else _default_reaches()

    report = SlotBackfillReport()
    pending_writes: list[tuple[Path, str]] = []
    for bank in rules.banks:
        path = root / bank / CORPUS_FILE_NAME
        if not path.is_file():
            raise SlotRulesError(f"규칙이 가리키는 코퍼스가 없다: {path}")
        out_lines: list[str] = []
        changed = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            out = _process_line(stripped, rules, judge, report)
            if out != stripped:
                changed += 1
            out_lines.append(out)
        report.changed += changed
        report.corpora[bank] = changed
        pending_writes.append((path, "\n".join(out_lines) + "\n" if out_lines else ""))

    if write:
        # 판정을 전부 끝낸 뒤에야 쓴다 — 중간 코퍼스에서 실패해 일부만 쓰인 상태를 남기지 않는다.
        for path, text in pending_writes:
            path.write_text(text, encoding="utf-8")
        report.written = report.changed
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.problem_slot_backfill",
        description=(
            "기존 문항의 6슬롯 결정론 백필(P3-05 3단계) — slot_assignment_rules.yaml 의 규칙으로 "
            "p3-slot 태그를 더한다(LLM 0·tags 키만 변경·바이트 계약·멱등)."
        ),
    )
    parser.add_argument(
        "--corpus-root", type=Path, default=None, help="코퍼스 루트(기본 data/corpus)."
    )
    parser.add_argument(
        "--rules", type=Path, default=None, help=f"규칙 파일(기본 {default_rules_path()})."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run", action="store_true", help="파일 미기록 — 리포트만 출력(항상 exit 0)."
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help="파일 미기록 — 태그를 더할 문항이 남아 있으면 exit 1(드리프트 가드).",
    )
    args = parser.parse_args(argv)

    try:
        report = run_backfill(
            corpus_root=args.corpus_root,
            rules_path=args.rules,
            write=not (args.dry_run or args.check),
        )
    except SlotRulesError as exc:
        print(f"[slot-backfill] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    json.dump(report.to_json(), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    if args.check and report.changed:
        print(
            f"[check] 슬롯 태그를 더할 승인 문항 {report.changed}건이 남아 있다 — "
            "규칙 파일과 코퍼스가 "
            "어긋났다. `--check` 없이 같은 명령을 돌려 백필하고 결과를 커밋하라.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover — 모듈 실행 진입점
    raise SystemExit(main())
