#!/usr/bin/env python3
"""P3-32 운영 DB 힌트 연결 런북용 읽기 전용 프로브 (`docs/ops/p3_32_hint_link_runbook.md`).

**왜 필요한가**: 샌드박스(로컬 PG · 문항 15,042행)에서는 핵심 개념 10종 hint 연결이 10/10에
닿았지만(`docs/reviews/p3_95_count_answer_finalize_2026-11-02.md`), 운영 DB(`whymath-pg` 5433)는
문항이 1,703행뿐이다. 적격 문항(phase3_coverage가 세는 문항)이 운영 DB에 **같은 problem_id로**
있는지, 개념마다 재생할 수 있는 문항이 남는지를 쓰기 전에 알아야 한다 — 한 개념이라도 0이면 그
개념은 아무리 적재해도 linked가 되지 않는다. 이 스크립트가 그 수를 같은 눈금으로 전후에 잰다.

**쓰기가 없다**: DB 접근은 `SET TRANSACTION READ ONLY` 트랜잭션이고 끝에 rollback한다. 쓰기 문장은
PostgreSQL이 거부한다(코드가 아니라 DB가 막는다).

**적격의 정의를 다시 쓰지 않는다**: 개념별 적격 문항은 계측기 자신의 `concept_facts().eligible`을
부른다(같은 판정 — 두 곳이 따로 계산하면 프로브는 준비됐다고 말하는데 계측기는 미달인 상태가
생긴다).

**출력은 ASCII `KEY=VALUE` 줄이다**: 한국어 Windows 콘솔(cp949)·PowerShell 중계에서 판정값이 깨지지
않게 한다. 개념 코드는 `[12미적Ⅰ-02-09]` 대신 순번 `C01`~`C10`으로 내고, 순번↔코드 대응은
`CONCEPT_Cnn_SRC`(소스 ID, ASCII 아님이면 JSON 이스케이프)로 낸다.

서브커맨드
---------
- `link` — 개념별 적격(코퍼스) · DB에 있음 · 재생 가능 · 검증 풀이 · 경로 · 검증 힌트 수와 합계,
  그리고 재생할 은행 목록(`REPLAY_BANKS`)·판정(`VERDICT`).
- `summary --kind {replay,promotion} --json <파일>` — 재생·승격 CLI 리포트 JSON을
  `KEY=VALUE`로 푼다.

종료 코드(판정은 exit code로 — 출력 문자열이 아니다):
  0 — 측정 완료 · 2 — 측정 실패(DB 미도달·적격 0건·JSON 손상). `link`의 준비 여부는 exit code가
  아니라 `VERDICT`다(측정이 끝났으면 미달이어도 0이다 — 미달과 측정 실패를 섞지 않는다).

사용(런북 단계가 환경변수 `WHYMATH_DATABASE_URL`·`PYTHONPATH`를 먼저 설정한다):
    python scripts/ops/p3_32_hint_link_probe.py link
    python scripts/ops/p3_32_hint_link_probe.py summary --kind replay --json work/replay.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EXIT_OK = 0
EXIT_UNMEASURED = 2

#: DB 읽기 제한 시간(초) — 연결이 걸려 멈춘 채 끝나지 않는 것을 막는다.
DB_TIMEOUT_S = 120.0

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BANK_GLOB = "data/corpus/problem_bank_*/problems.jsonl"

#: VERDICT 값 — 런북 쓰기 블록의 가드가 문자열 일치로 읽는다.
VERDICT_READY = "READY"  # 모든 개념에 DB에 있는 재생 가능 문항이 1건 이상
VERDICT_PARTIAL = "PARTIAL"  # 일부 개념만
VERDICT_NONE = "NONE"  # 어느 개념에도 없다 — 쓰기 무의미

_LINK_KEYS = (
    "PROBE",
    "PROBE_ERROR",
    "CODE_PHASE3",
    "CODE_REPLAY",
    "CODE_PROBE",
    "DB_PROBLEM_ROWS",
    "DB_VERIFIED_SOLUTIONS",
    "DB_SOLUTION_PATHS",
    "DB_HINTS_VERIFIED",
    "CONCEPTS",
    "ELIGIBLE",
    "ELIGIBLE_IN_DB",
    "REPLAYABLE_IN_DB",
    "WITH_VERIFIED_SOLUTION",
    "WITH_PATH",
    "WITH_VERIFIED_HINT",
    "CONCEPTS_REPLAYABLE",
    "CONCEPTS_HINT_LINKED",
    "REPLAY_BANK_COUNT",
    "REPLAY_BANKS",
    "VERDICT",
)
_PER_CONCEPT_FIELDS = (
    "SRC",
    "ELIGIBLE",
    "IN_DB",
    "REPLAYABLE_IN_DB",
    "VERIFIED_SOLUTION",
    "PATH",
    "VERIFIED_HINT",
)
_SUMMARY_KEYS = (
    "SUMMARY_KIND",
    "SUMMARY_WELLFORMED",
    "REPLAY_TOTAL",
    "REPLAY_REPLAYED",
    "REPLAY_VERIFIED",
    "REPLAY_OTHER",
    "REPLAY_SKIPPED_MISSING",
    "REPLAY_FAILURES",
    "PROMO_MODE",
    "PROMO_INPUT",
    "PROMO_PROMOTED",
    "PROMO_ALREADY",
    "PROMO_SKIPPED_MISSING",
    "PROMO_QUEUED_UNMAPPABLE",
    "PROMO_PYDANTIC_REJECTED",
    "PROMO_FAILURES",
)


def _all_keys(concepts: int = 10) -> frozenset[str]:
    keys = set(_LINK_KEYS) | set(_SUMMARY_KEYS)
    for i in range(1, concepts + 1):
        for field in _PER_CONCEPT_FIELDS:
            keys.add(f"CONCEPT_C{i:02d}_{field}")
    return frozenset(keys)


ALL_KEYS = _all_keys(99)


def kv(key: str, value: object) -> None:
    """`KEY=VALUE` 한 줄 — 값은 ASCII로 제한한다. 선언되지 않은 키는 거부한다."""
    if key not in ALL_KEYS:
        raise KeyError(f"선언되지 않은 출력 키: {key}")
    text = str(value)
    if not text.isascii():
        text = json.dumps(text, ensure_ascii=True)
    print(f"{key}={text}")


# ── 순수 집계(테스트가 직접 부른다) ─────────────────────────────────────


@dataclass(frozen=True)
class ConceptRow:
    """개념 1건의 수 — 전부 문항 수(행 수가 아니다)."""

    source_id: str
    eligible: int
    in_db: int
    replayable_in_db: int
    verified_solution: int
    path: int
    verified_hint: int


@dataclass(frozen=True)
class LinkMeasure:
    concepts: tuple[ConceptRow, ...]
    replay_banks: tuple[str, ...]

    @property
    def verdict(self) -> str:
        ready = sum(1 for c in self.concepts if c.replayable_in_db > 0)
        if ready == 0:
            return VERDICT_NONE
        return VERDICT_READY if ready == len(self.concepts) else VERDICT_PARTIAL


def measure_link(
    eligible_by_concept: Sequence[tuple[str, frozenset[str]]],
    *,
    in_db: frozenset[str],
    replayable_by_bank: Mapping[str, frozenset[str]],
    with_solution: frozenset[str],
    with_path: frozenset[str],
    with_hint: frozenset[str],
) -> LinkMeasure:
    """개념별 적격 문항 집합과 DB 사실 집합 → 개념별 수와 재생할 은행(순수·결정론).

    재생할 은행 = 적격이면서 DB에 있고 재생 가능한 문항을 하나라도 가진 은행(이름순). 그 밖의
    은행은 재생해도 이 태스크의 연결에 기여하지 않는다.
    """
    replayable_all = (
        frozenset().union(*replayable_by_bank.values()) if replayable_by_bank else frozenset()
    )
    rows = []
    wanted: set[str] = set()
    for source_id, eligible in eligible_by_concept:
        present = eligible & in_db
        replayable = present & replayable_all
        wanted |= replayable
        rows.append(
            ConceptRow(
                source_id=source_id,
                eligible=len(eligible),
                in_db=len(present),
                replayable_in_db=len(replayable),
                verified_solution=len(present & with_solution),
                path=len(present & with_path),
                verified_hint=len(present & with_hint),
            )
        )
    banks = tuple(sorted(b for b, ids in replayable_by_bank.items() if ids & wanted))
    return LinkMeasure(concepts=tuple(rows), replay_banks=banks)


def emit_link(measure: LinkMeasure) -> None:
    rows = measure.concepts

    def total(attr: str) -> int:
        return sum(int(getattr(r, attr)) for r in rows)

    kv("CONCEPTS", len(rows))
    for i, row in enumerate(rows, start=1):
        prefix = f"CONCEPT_C{i:02d}_"
        kv(prefix + "SRC", row.source_id)
        kv(prefix + "ELIGIBLE", row.eligible)
        kv(prefix + "IN_DB", row.in_db)
        kv(prefix + "REPLAYABLE_IN_DB", row.replayable_in_db)
        kv(prefix + "VERIFIED_SOLUTION", row.verified_solution)
        kv(prefix + "PATH", row.path)
        kv(prefix + "VERIFIED_HINT", row.verified_hint)
    kv("ELIGIBLE", total("eligible"))
    kv("ELIGIBLE_IN_DB", total("in_db"))
    kv("REPLAYABLE_IN_DB", total("replayable_in_db"))
    kv("WITH_VERIFIED_SOLUTION", total("verified_solution"))
    kv("WITH_PATH", total("path"))
    kv("WITH_VERIFIED_HINT", total("verified_hint"))
    kv("CONCEPTS_REPLAYABLE", sum(1 for r in rows if r.replayable_in_db > 0))
    kv("CONCEPTS_HINT_LINKED", sum(1 for r in rows if r.verified_hint > 0))
    kv("REPLAY_BANK_COUNT", len(measure.replay_banks))
    kv("REPLAY_BANKS", ";".join(measure.replay_banks))
    kv("VERDICT", measure.verdict)


# ── 코퍼스 읽기 ─────────────────────────────────────────────────────────


def _eligible_by_concept(root: Path) -> list[tuple[str, frozenset[str]]]:
    from whymath_backend.l1.standards import phase3_coverage as cov
    from whymath_backend.l1.standards.phase3_scope import load_scope_spec

    spec = load_scope_spec(cov.default_spec_path())
    index = cov.load_reference_index(spec)
    corpus = cov.load_corpus(spec, root)
    out = []
    for concept in spec.concepts:
        facts = cov.concept_facts(spec, index, corpus, concept)
        out.append((concept.source_id, frozenset(p.problem_id for p in facts.eligible)))
    return out


def _replayable_by_bank(root: Path) -> dict[str, frozenset[str]]:
    from whymath_backend.whs.corpus_replay import load_replay_items

    out: dict[str, frozenset[str]] = {}
    for path in sorted(root.glob(_BANK_GLOB)):
        items = load_replay_items(path.read_text(encoding="utf-8"))
        if items:
            rel = path.relative_to(root).as_posix()
            out[rel] = frozenset(str(i.problem_id) for i in items)
    return out


# ── DB 읽기(읽기 전용) ──────────────────────────────────────────────────


async def _db_facts(ids: Iterable[str]) -> dict[str, Any]:
    from sqlalchemy import text

    from whymath_backend.db.session import get_engine, get_sessionmaker

    wanted = sorted(set(ids))
    try:
        async with get_sessionmaker()() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            try:

                async def scalar(sql: str) -> int:
                    return int((await session.execute(text(sql))).scalar_one())

                async def present(sql: str) -> frozenset[str]:
                    rows = await session.execute(text(sql), {"ids": wanted})
                    return frozenset(str(r[0]) for r in rows)

                return {
                    "problem_rows": await scalar("SELECT count(*) FROM problem"),
                    "verified_solutions": await scalar(
                        "SELECT count(*) FROM verified_solutions WHERE grade = 'verified'"
                    ),
                    "solution_paths": await scalar("SELECT count(*) FROM solution_paths"),
                    "hints_verified": await scalar(
                        "SELECT count(*) FROM hints WHERE verified IS true"
                    ),
                    "in_db": await present(
                        "SELECT problem_id FROM problem"
                        " WHERE problem_id::text = ANY(CAST(:ids AS text[]))"
                    ),
                    "with_solution": await present(
                        "SELECT DISTINCT problem_id FROM verified_solutions"
                        " WHERE grade = 'verified'"
                        " AND problem_id::text = ANY(CAST(:ids AS text[]))"
                    ),
                    "with_path": await present(
                        "SELECT DISTINCT problem_id FROM solution_paths"
                        " WHERE problem_id::text = ANY(CAST(:ids AS text[]))"
                    ),
                    "with_hint": await present(
                        "SELECT DISTINCT problem_id FROM hints WHERE verified IS true"
                        " AND problem_id::text = ANY(CAST(:ids AS text[]))"
                    ),
                }
            finally:
                await session.rollback()
    finally:
        await get_engine().dispose()


def _print_code_origin() -> None:
    import whymath_backend.l1.standards.phase3_coverage as cov
    import whymath_backend.whs.corpus_replay as replay

    kv("CODE_PHASE3", cov.__file__)
    kv("CODE_REPLAY", replay.__file__)
    kv("CODE_PROBE", Path(__file__).resolve())


def cmd_link(_args: argparse.Namespace) -> int:
    kv("PROBE", "link")
    _print_code_origin()
    try:
        eligible = _eligible_by_concept(_REPO_ROOT)
        replayable = _replayable_by_bank(_REPO_ROOT)
    except Exception as exc:  # noqa: BLE001 — 측정 실패는 exit 2(원인 타입명 병기)
        kv("PROBE_ERROR", f"{type(exc).__name__}: {str(exc)[:200]}")
        return EXIT_UNMEASURED
    all_ids = frozenset().union(*(ids for _, ids in eligible)) if eligible else frozenset()
    if not all_ids:
        # 적격 0건은 공허한 측정이다 — 준비 판정을 내지 않는다.
        kv("PROBE_ERROR", "적격 문항 0건 - 코퍼스 경로 또는 범위 명세 확인")
        return EXIT_UNMEASURED
    try:
        facts = asyncio.run(asyncio.wait_for(_db_facts(all_ids), timeout=DB_TIMEOUT_S))
    except Exception as exc:  # noqa: BLE001 — DB 미도달·시간 초과는 exit 2
        kv("PROBE_ERROR", f"{type(exc).__name__}: {str(exc)[:200]}")
        return EXIT_UNMEASURED
    kv("DB_PROBLEM_ROWS", facts["problem_rows"])
    kv("DB_VERIFIED_SOLUTIONS", facts["verified_solutions"])
    kv("DB_SOLUTION_PATHS", facts["solution_paths"])
    kv("DB_HINTS_VERIFIED", facts["hints_verified"])
    emit_link(
        measure_link(
            eligible,
            in_db=facts["in_db"],
            replayable_by_bank=replayable,
            with_solution=facts["with_solution"],
            with_path=facts["with_path"],
            with_hint=facts["with_hint"],
        )
    )
    return EXIT_OK


# ── summary ─────────────────────────────────────────────────────────────


def _last_json_object(text: str) -> Mapping[str, Any] | None:
    """파일 전체가 JSON이면 그것, 아니면 마지막 비어 있지 않은 줄의 JSON(승격 CLI는 끝줄)."""
    try:
        whole = json.loads(text)
        return whole if isinstance(whole, dict) else None
    except ValueError:
        pass
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    try:
        last = json.loads(lines[-1])
    except ValueError:
        return None
    return last if isinstance(last, dict) else None


_REPLAY_REQUIRED = (
    "total_records",
    "replayed",
    "finalized_verified",
    "finalized_other",
    "skipped_problem_missing",
    "failures",
)
_PROMO_REQUIRED = (
    "mode",
    "total_input",
    "promoted",
    "already_promoted",
    "skipped_problem_missing",
    "queued_approach_unmappable",
    "pydantic_rejected",
    "failures",
)


def summarize(kind: str, report: Mapping[str, Any]) -> list[tuple[str, object]]:
    """리포트 → `KEY=VALUE`(순수). **빠진 키는 0으로 읽지 않는다** — 없으면 WELLFORMED=False."""
    required = _REPLAY_REQUIRED if kind == "replay" else _PROMO_REQUIRED
    wellformed = all(key in report for key in required)

    def count(key: str) -> object:
        value = report.get(key, "missing")
        if key == "failures":
            return len(value) if isinstance(value, list) else "missing"
        return value

    out: list[tuple[str, object]] = [("SUMMARY_KIND", kind)]
    if kind == "replay":
        out += [
            ("REPLAY_TOTAL", count("total_records")),
            ("REPLAY_REPLAYED", count("replayed")),
            ("REPLAY_VERIFIED", count("finalized_verified")),
            ("REPLAY_OTHER", count("finalized_other")),
            ("REPLAY_SKIPPED_MISSING", count("skipped_problem_missing")),
            ("REPLAY_FAILURES", count("failures")),
        ]
    else:
        out += [
            ("PROMO_MODE", count("mode")),
            ("PROMO_INPUT", count("total_input")),
            ("PROMO_PROMOTED", count("promoted")),
            ("PROMO_ALREADY", count("already_promoted")),
            ("PROMO_SKIPPED_MISSING", count("skipped_problem_missing")),
            ("PROMO_QUEUED_UNMAPPABLE", count("queued_approach_unmappable")),
            ("PROMO_PYDANTIC_REJECTED", count("pydantic_rejected")),
            ("PROMO_FAILURES", count("failures")),
        ]
    out.append(("SUMMARY_WELLFORMED", wellformed))
    return out


def cmd_summary(args: argparse.Namespace) -> int:
    try:
        # utf-8-sig — PowerShell 5.1이 쓴 파일의 BOM을 벗긴다(BOM이 있으면 JSON 파싱이 깨진다).
        text = Path(args.json).read_text(encoding="utf-8-sig")
    except OSError as exc:
        kv("PROBE_ERROR", f"{type(exc).__name__}: JSON 파일을 읽지 못했다")
        return EXIT_UNMEASURED
    report = _last_json_object(text)
    if report is None:
        kv("PROBE_ERROR", "JSON 객체를 찾지 못했다 - CLI가 리포트를 내지 못했다")
        return EXIT_UNMEASURED
    pairs = summarize(args.kind, report)
    for key, value in pairs:
        kv(key, value)
    return EXIT_OK if dict(pairs)["SUMMARY_WELLFORMED"] else EXIT_UNMEASURED


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="p3_32_hint_link_probe", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("link", help="개념별 적격·DB·재생 가능·풀이·경로·힌트 수").set_defaults(
        func=cmd_link
    )
    summary = sub.add_parser("summary", help="재생·승격 리포트 JSON → KEY=VALUE")
    summary.add_argument("--kind", choices=("replay", "promotion"), required=True)
    summary.add_argument("--json", required=True)
    summary.set_defaults(func=cmd_summary)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
