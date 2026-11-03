#!/usr/bin/env python3
"""P3-97 운영 DB 문제은행 적재 런북용 읽기 전용 미리보기 (`docs/ops/p3_97_bank_load_runbook.md`).

**왜 필요한가**: 적재 CLI(`l1.problem_bank.populate`)에는 시험 실행이 없다. 그런데 이 적재는
학생 출제 후보가 되는 승인 문항 집합을 넓힌다(Kiki 결정 2026-11-03). 그래서 쓰기 전에
**무엇이 바뀌는지**를 같은 눈금으로 센다.

- 은행별 행 수 · 그중 승인(`review_status=approved`) 수
- DB에 이미 같은 `problem_id`로 있는 행(갱신 대상) · 새로 들어갈 행(삽입 대상)
- **slug 충돌**: 같은 slug가 *다른* `problem_id`로 이미 있는 행. 적재는 `ON CONFLICT(slug)`라
  DB의 옛 id가
  남고, 코퍼스 id를 쓰는 측정(P3-32 프로브·계측기)이 그 문항을 찾지 못한다 — 0이어야 한다.
- 갱신 대상 중 CMS 편집·발행 판이 있는 행(적재가 건너뛰고 충돌로 보고한다)
- 핵심 개념별 새로 DB에 들어올 적격 문항 수(계측기 `concept_facts().eligible`과 같은 판정)

**쓰기가 없다**: DB 접근은 `SET TRANSACTION READ ONLY` 트랜잭션이고 끝에 rollback한다.

**출력은 ASCII `KEY=VALUE` 줄이다**(한국어 Windows 콘솔·PowerShell 중계에서 판정값이 깨지지 않게).

종료 코드: 0 — 측정 완료 · 2 — 측정 실패(DB 미도달·은행 파일 없음·0행).
적재 가부는 exit code가 아니라
`LOAD_VERDICT`(`OK`·`SLUG_CONFLICT`·`NOTHING_NEW`)다.

사용(런북이 환경변수 `WHYMATH_DATABASE_URL`·`PYTHONPATH`를 먼저 설정한다):
    python scripts/ops/p3_97_bank_load_probe.py preview \
        --bank data/corpus/problem_bank_x/problems.jsonl ...
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EXIT_OK = 0
EXIT_UNMEASURED = 2
DB_TIMEOUT_S = 120.0
_REPO_ROOT = Path(__file__).resolve().parents[2]

VERDICT_OK = "OK"
VERDICT_SLUG_CONFLICT = "SLUG_CONFLICT"
VERDICT_NOTHING_NEW = "NOTHING_NEW"

_BANK_FIELDS = (
    "PATH",
    "ROWS",
    "APPROVED",
    "IN_DB_SAME_ID",
    "NEW",
    "NEW_APPROVED",
    "SLUG_CONFLICT",
    "PROTECTED",
)
_KEYS = {
    "PROBE",
    "PROBE_ERROR",
    "CODE_PROBE",
    "CODE_PHASE3",
    "DB_PROBLEM_ROWS",
    "BANKS",
    "TOTAL_ROWS",
    "TOTAL_NEW",
    "TOTAL_NEW_APPROVED",
    "TOTAL_SLUG_CONFLICT",
    "TOTAL_PROTECTED",
    "CONCEPTS",
    "CONCEPTS_GAINING",
    "LOAD_VERDICT",
}
ALL_KEYS = frozenset(
    _KEYS
    | {f"BANK_B{i:02d}_{f}" for i in range(1, 20) for f in _BANK_FIELDS}
    | {f"CONCEPT_C{i:02d}_{f}" for i in range(1, 100) for f in ("SRC", "NEW_ELIGIBLE")}
)


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
class BankRow:
    problem_id: str
    slug: str
    approved: bool


@dataclass(frozen=True)
class BankPreview:
    path: str
    rows: int
    approved: int
    in_db_same_id: int
    new: int
    new_approved: int
    slug_conflict: int
    protected: int
    new_ids: frozenset[str]


def preview_bank(
    path: str,
    rows: Sequence[BankRow],
    *,
    db_ids: frozenset[str],
    db_slug_to_id: Mapping[str, str],
    protected_ids: frozenset[str],
) -> BankPreview:
    """은행 1개의 적재 효과(순수·결정론). slug가 다른 id로 있으면 충돌 — 새 행으로 세지 않는다."""
    same = new = new_approved = conflict = protected = 0
    new_ids: set[str] = set()
    for row in rows:
        if row.problem_id in db_ids:
            same += 1
            if row.problem_id in protected_ids:
                protected += 1
            continue
        other = db_slug_to_id.get(row.slug)
        if other is not None and other != row.problem_id:
            conflict += 1
            continue
        new += 1
        new_ids.add(row.problem_id)
        if row.approved:
            new_approved += 1
    return BankPreview(
        path=path,
        rows=len(rows),
        approved=sum(1 for r in rows if r.approved),
        in_db_same_id=same,
        new=new,
        new_approved=new_approved,
        slug_conflict=conflict,
        protected=protected,
        new_ids=frozenset(new_ids),
    )


def load_verdict(previews: Sequence[BankPreview]) -> str:
    if any(p.slug_conflict for p in previews):
        return VERDICT_SLUG_CONFLICT
    if not any(p.new for p in previews):
        return VERDICT_NOTHING_NEW
    return VERDICT_OK


def read_bank(path: Path) -> list[BankRow]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        rows.append(
            BankRow(
                problem_id=str(record["problem_id"]),
                slug=str(record.get("slug") or ""),
                approved=record.get("review_status") == "approved",
            )
        )
    return rows


# ── 코퍼스·DB 읽기 ──────────────────────────────────────────────────────


def _eligible_by_concept() -> list[tuple[str, frozenset[str]]]:
    from whymath_backend.l1.standards import phase3_coverage as cov
    from whymath_backend.l1.standards.phase3_scope import load_scope_spec

    spec = load_scope_spec(cov.default_spec_path())
    index = cov.load_reference_index(spec)
    corpus = cov.load_corpus(spec, _REPO_ROOT)
    return [
        (
            c.source_id,
            frozenset(p.problem_id for p in cov.concept_facts(spec, index, corpus, c).eligible),
        )
        for c in spec.concepts
    ]


async def _db_facts(ids: Sequence[str], slugs: Sequence[str]) -> dict[str, Any]:
    from sqlalchemy import text

    from whymath_backend.db.session import get_engine, get_sessionmaker

    try:
        async with get_sessionmaker()() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            try:
                total = int(
                    (await session.execute(text("SELECT count(*) FROM problem"))).scalar_one()
                )
                by_id = await session.execute(
                    text(
                        "SELECT problem_id::text, (cms_edited_at IS NOT NULL"
                        " OR problem_version_id IS NOT NULL) FROM problem"
                        " WHERE problem_id::text = ANY(CAST(:ids AS text[]))"
                    ),
                    {"ids": list(ids)},
                )
                id_rows = list(by_id)
                by_slug = await session.execute(
                    text(
                        "SELECT slug, problem_id::text FROM problem"
                        " WHERE slug = ANY(CAST(:slugs AS text[]))"
                    ),
                    {"slugs": list(slugs)},
                )
                return {
                    "total": total,
                    "ids": frozenset(r[0] for r in id_rows),
                    "protected": frozenset(r[0] for r in id_rows if r[1]),
                    "slug_to_id": {str(r[0]): str(r[1]) for r in by_slug},
                }
            finally:
                await session.rollback()
    finally:
        await get_engine().dispose()


def cmd_preview(args: argparse.Namespace) -> int:
    import whymath_backend.l1.standards.phase3_coverage as cov

    kv("PROBE", "preview")
    kv("CODE_PROBE", Path(__file__).resolve())
    kv("CODE_PHASE3", cov.__file__)
    try:
        banks = [(p, read_bank(_REPO_ROOT / p)) for p in args.bank]
        eligible = _eligible_by_concept()
    except Exception as exc:  # noqa: BLE001 — 측정 실패는 exit 2(원인 타입명 병기)
        kv("PROBE_ERROR", f"{type(exc).__name__}: {str(exc)[:200]}")
        return EXIT_UNMEASURED
    if not banks or any(not rows for _, rows in banks):
        kv("PROBE_ERROR", "은행 0행 - 경로 확인")
        return EXIT_UNMEASURED
    ids = sorted({r.problem_id for _, rows in banks for r in rows})
    slugs = sorted({r.slug for _, rows in banks for r in rows if r.slug})
    try:
        facts = asyncio.run(asyncio.wait_for(_db_facts(ids, slugs), timeout=DB_TIMEOUT_S))
    except Exception as exc:  # noqa: BLE001 — DB 미도달·시간 초과는 exit 2
        kv("PROBE_ERROR", f"{type(exc).__name__}: {str(exc)[:200]}")
        return EXIT_UNMEASURED
    previews = [
        preview_bank(
            p,
            rows,
            db_ids=facts["ids"],
            db_slug_to_id=facts["slug_to_id"],
            protected_ids=facts["protected"],
        )
        for p, rows in banks
    ]
    kv("DB_PROBLEM_ROWS", facts["total"])
    kv("BANKS", len(previews))
    for i, p in enumerate(previews, start=1):
        prefix = f"BANK_B{i:02d}_"
        kv(prefix + "PATH", p.path)
        kv(prefix + "ROWS", p.rows)
        kv(prefix + "APPROVED", p.approved)
        kv(prefix + "IN_DB_SAME_ID", p.in_db_same_id)
        kv(prefix + "NEW", p.new)
        kv(prefix + "NEW_APPROVED", p.new_approved)
        kv(prefix + "SLUG_CONFLICT", p.slug_conflict)
        kv(prefix + "PROTECTED", p.protected)
    kv("TOTAL_ROWS", sum(p.rows for p in previews))
    kv("TOTAL_NEW", sum(p.new for p in previews))
    kv("TOTAL_NEW_APPROVED", sum(p.new_approved for p in previews))
    kv("TOTAL_SLUG_CONFLICT", sum(p.slug_conflict for p in previews))
    kv("TOTAL_PROTECTED", sum(p.protected for p in previews))
    new_ids = frozenset().union(*(p.new_ids for p in previews))
    kv("CONCEPTS", len(eligible))
    gaining = 0
    for i, (src, ids_c) in enumerate(eligible, start=1):
        n = len(ids_c & new_ids)
        gaining += 1 if n else 0
        kv(f"CONCEPT_C{i:02d}_SRC", src)
        kv(f"CONCEPT_C{i:02d}_NEW_ELIGIBLE", n)
    kv("CONCEPTS_GAINING", gaining)
    kv("LOAD_VERDICT", load_verdict(previews))
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="p3_97_bank_load_probe", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    preview = sub.add_parser("preview", help="은행 적재 효과 미리보기(읽기 전용)")
    preview.add_argument("--bank", action="append", required=True, help="저장소 루트 상대 경로")
    preview.set_defaults(func=cmd_preview)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
