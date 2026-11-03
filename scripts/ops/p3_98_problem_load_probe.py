#!/usr/bin/env python3
"""P3-98 운영 DB 문항은행 적재 런북용 읽기 전용 프로브 (`docs/ops/p3_98_problem_load_runbook.md`).

**왜 필요한가**: P3-32 힌트 연결 런북의 실측(2026-11-03 Kiki 머신 · main `37e32712`)에서 운영 DB
`problem` 1,703행에 핵심 개념 10종의 적격 문항이 228/1,121건만 있었고, 8개 개념은 0건이었다. 힌트는
문항 행이 있어야 붙으므로 그 8개 개념은 문항을 먼저 넣어야 한다.
적재기(`l1.problem_bank.populate`)는 `slug` 기준 멱등 upsert지만, 두 가지 상태에서는
쓰기 전에 멈춰야 한다:

- **기본키 충돌(PK_COLLISION)** — 코퍼스의 `problem_id`가 DB에 **다른 slug로** 이미 있다. upsert는
  slug로만 충돌을 처리하므로 이 행은 기본키 위반으로 그 은행 파일 전체 트랜잭션을 롤백시킨다.
- **ID 이탈(ID_DRIFT)** — 같은 slug가 DB에 **다른 problem_id로** 있다. 적재기는 기존 PK를 보존하므로
  적재해도 그 문항은 코퍼스 ID로 DB에 생기지 않는다(힌트·계측기는 코퍼스 ID로 조인한다).

그 밖에 이미 있는 행 중 CMS 편집(`cms_edited_at`)·발행 판(`problem_version_id`)이 있는 행은 적재기가
건너뛴다(PROTECTED — 차단 사유가 아니라 보고 대상).

**쓰기가 없다**: DB 접근은 `SET TRANSACTION READ ONLY` 트랜잭션이고 끝에 rollback한다. 개념 해석
가능 여부도 적재기 자신의 해석 함수(`ProblemBankStore._load_source_id_to_concept_id` — SELECT 1회)를
불러 같은 판정으로 센다.

**적격의 정의를 다시 쓰지 않는다**: 핵심 개념별 적격 문항은 계측기의 `concept_facts().eligible`이다.

**출력은 ASCII `KEY=VALUE` 줄이다**(한국어 Windows 콘솔·PowerShell 중계에서 판정값이 깨지지 않게).
은행은 순번 `B01`~, 개념은 `C01`~`C10`으로 낸다.

서브커맨드
---------
- `measure --bank <저장소 상대 경로> [--bank …]` — 은행별 분류 · 개념별 지금/적재 후 예측 · 판정.
  적재 전(BEFORE)과 적재 후(AFTER)에 **같은 명령**으로 돌려 두 출력을 비교한다.

종료 코드(판정은 exit code로 — 출력 문자열이 아니다):
  0 — 측정 완료(준비 여부는 `VERDICT`)
  2 — 측정 실패(DB 미도달·은행 파일 부재·코퍼스 거부·적격 0건).

사용(런북 단계가 `WHYMATH_DATABASE_URL`·`PYTHONPATH`를 먼저 설정하고 저장소 루트에서 실행한다):
    python scripts/ops/p3_98_problem_load_probe.py measure \\
        --bank data/corpus/problem_bank_p3_calculus1_diff_v0/problems.jsonl \\
        --bank data/corpus/problem_bank_p3_fill_v0/problems.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

EXIT_OK = 0
EXIT_UNMEASURED = 2

#: DB 읽기 제한 시간(초) — 연결이 걸려 멈춘 채 끝나지 않는 것을 막는다.
DB_TIMEOUT_S = 120.0

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: VERDICT 값 — 런북 쓰기 블록의 가드가 문자열 일치로 읽는다.
VERDICT_READY = "READY"  # 새로 넣을 행이 있고 차단 사유 0
VERDICT_DONE = "DONE"  # 새로 넣을 행이 없고 차단 사유 0 — 이미 적재됨
VERDICT_BLOCKED = "BLOCKED"  # 기본키 충돌·ID 이탈·개념 미해석 중 하나 이상

_TOP_KEYS = (
    "PROBE",
    "PROBE_ERROR",
    "CODE_POPULATE",
    "CODE_PHASE3",
    "CODE_PROBE",
    "DB_PROBLEM_ROWS",
    "BANK_COUNT",
    "BANK_ROWS",
    "PRESENT_ROWS",
    "NEW_ROWS",
    "ID_DRIFT",
    "PK_COLLISION",
    "PROTECTED",
    "SRC_NEEDED",
    "SRC_UNRESOLVED",
    "CONCEPTS",
    "ELIGIBLE",
    "ELIGIBLE_IN_DB",
    "PREDICTED_ELIGIBLE_IN_DB",
    "CONCEPTS_IN_DB",
    "PREDICTED_CONCEPTS_IN_DB",
    "BLOCK_REASONS",
    "VERDICT",
)
_PER_BANK_FIELDS = ("PATH", "ROWS", "PRESENT", "NEW", "ID_DRIFT", "PK_COLLISION", "PROTECTED")
_PER_CONCEPT_FIELDS = ("SRC", "ELIGIBLE", "IN_DB", "PREDICTED_IN_DB")


def _all_keys(limit: int = 99) -> frozenset[str]:
    keys = set(_TOP_KEYS)
    for i in range(1, limit + 1):
        keys.update(f"BANK_B{i:02d}_{f}" for f in _PER_BANK_FIELDS)
        keys.update(f"CONCEPT_C{i:02d}_{f}" for f in _PER_CONCEPT_FIELDS)
    return frozenset(keys)


ALL_KEYS = _all_keys()


def kv(key: str, value: object) -> None:
    """`KEY=VALUE` 한 줄 — 값은 ASCII로 제한한다. 선언되지 않은 키는 거부한다."""
    if key not in ALL_KEYS:
        raise KeyError(f"선언되지 않은 출력 키: {key}")
    text = str(value)
    if not text.isascii():
        text = json.dumps(text, ensure_ascii=True)
    print(f"{key}={text}")


# ── 순수 분류(테스트가 직접 부른다) ─────────────────────────────────────


@dataclass(frozen=True)
class BankRows:
    """은행 파일 1개의 (slug, problem_id) 목록 — 적재기가 실제로 넣을 레코드(dedup 후)."""

    path: str
    rows: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class DbRow:
    """DB `problem` 행 중 판정에 필요한 열만."""

    problem_id: str
    slug: str | None
    protected: bool  # cms_edited_at 또는 problem_version_id가 있다 — 적재기가 건너뛴다


@dataclass(frozen=True)
class BankClass:
    path: str
    rows: int
    present: int  # 같은 slug · 같은 problem_id — 이미 적재됨(멱등 갱신 대상)
    new: int  # slug도 problem_id도 DB에 없다 — 이번에 생긴다
    id_drift: int  # 같은 slug · 다른 problem_id — 적재해도 코퍼스 ID로 생기지 않는다(차단)
    pk_collision: int  # problem_id가 다른 slug로 있다 — 기본키 위반(차단)
    protected: int  # present 중 CMS 편집·발행 판 — 적재기가 갱신을 건너뛴다(보고만)
    new_ids: frozenset[str]


def classify_bank(
    bank: BankRows, by_slug: Mapping[str, DbRow], by_id: Mapping[str, DbRow]
) -> BankClass:
    """은행 레코드를 DB 사실과 대조해 다섯 부류로 센다(순수·결정론)."""
    present = new = drift = collision = protected = 0
    new_ids: set[str] = set()
    for slug, pid in bank.rows:
        same_slug = by_slug.get(slug)
        if same_slug is not None:
            if same_slug.problem_id == pid:
                present += 1
                protected += int(same_slug.protected)
            else:
                drift += 1
            continue
        same_id = by_id.get(pid)
        if same_id is not None:
            collision += 1
            continue
        new += 1
        new_ids.add(pid)
    return BankClass(
        path=bank.path,
        rows=len(bank.rows),
        present=present,
        new=new,
        id_drift=drift,
        pk_collision=collision,
        protected=protected,
        new_ids=frozenset(new_ids),
    )


@dataclass(frozen=True)
class LoadMeasure:
    banks: tuple[BankClass, ...]
    concepts: tuple[tuple[str, int, int, int], ...]  # (src, 적격, 지금 DB, 적재 후 예측)
    src_needed: int
    src_unresolved: int

    def total(self, attr: str) -> int:
        return sum(int(getattr(b, attr)) for b in self.banks)

    @property
    def block_reasons(self) -> tuple[str, ...]:
        reasons = []
        if self.total("pk_collision"):
            reasons.append("PK_COLLISION")
        if self.total("id_drift"):
            reasons.append("ID_DRIFT")
        if self.src_unresolved:
            reasons.append("SRC_UNRESOLVED")
        return tuple(reasons)

    @property
    def verdict(self) -> str:
        if self.block_reasons:
            return VERDICT_BLOCKED
        return VERDICT_READY if self.total("new") > 0 else VERDICT_DONE


def measure_load(
    banks: Sequence[BankRows],
    db_rows: Iterable[DbRow],
    eligible_by_concept: Sequence[tuple[str, frozenset[str]]],
    *,
    src_needed: frozenset[str],
    src_resolved: frozenset[str],
) -> LoadMeasure:
    """은행·DB·적격 → 은행별 분류와 개념별 지금/적재 후 예측(순수).

    적재 후 예측 = 지금 DB에 있는 적격 ∪ 이번에 새로 생길 적격(`new`). ID 이탈·충돌 행은 예측에
    넣지 않는다 — 그 행은 코퍼스 ID로 생기지 않는다.
    """
    rows = list(db_rows)
    by_slug = {r.slug: r for r in rows if r.slug}
    by_id = {r.problem_id: r for r in rows}
    in_db = frozenset(by_id)
    classes = tuple(classify_bank(b, by_slug, by_id) for b in banks)
    new_ids = frozenset().union(*(c.new_ids for c in classes)) if classes else frozenset()
    concepts = tuple(
        (src, len(ids), len(ids & in_db), len(ids & (in_db | new_ids)))
        for src, ids in eligible_by_concept
    )
    return LoadMeasure(
        banks=classes,
        concepts=concepts,
        src_needed=len(src_needed),
        src_unresolved=len(src_needed - src_resolved),
    )


def emit_measure(m: LoadMeasure, db_problem_rows: int) -> None:
    kv("DB_PROBLEM_ROWS", db_problem_rows)
    kv("BANK_COUNT", len(m.banks))
    for i, b in enumerate(m.banks, start=1):
        p = f"BANK_B{i:02d}_"
        kv(p + "PATH", b.path)
        kv(p + "ROWS", b.rows)
        kv(p + "PRESENT", b.present)
        kv(p + "NEW", b.new)
        kv(p + "ID_DRIFT", b.id_drift)
        kv(p + "PK_COLLISION", b.pk_collision)
        kv(p + "PROTECTED", b.protected)
    kv("BANK_ROWS", m.total("rows"))
    kv("PRESENT_ROWS", m.total("present"))
    kv("NEW_ROWS", m.total("new"))
    kv("ID_DRIFT", m.total("id_drift"))
    kv("PK_COLLISION", m.total("pk_collision"))
    kv("PROTECTED", m.total("protected"))
    kv("SRC_NEEDED", m.src_needed)
    kv("SRC_UNRESOLVED", m.src_unresolved)
    kv("CONCEPTS", len(m.concepts))
    for i, (src, eligible, now, predicted) in enumerate(m.concepts, start=1):
        p = f"CONCEPT_C{i:02d}_"
        kv(p + "SRC", src)
        kv(p + "ELIGIBLE", eligible)
        kv(p + "IN_DB", now)
        kv(p + "PREDICTED_IN_DB", predicted)
    kv("ELIGIBLE", sum(c[1] for c in m.concepts))
    kv("ELIGIBLE_IN_DB", sum(c[2] for c in m.concepts))
    kv("PREDICTED_ELIGIBLE_IN_DB", sum(c[3] for c in m.concepts))
    kv("CONCEPTS_IN_DB", sum(1 for c in m.concepts if c[2] > 0))
    kv("PREDICTED_CONCEPTS_IN_DB", sum(1 for c in m.concepts if c[3] > 0))
    kv("BLOCK_REASONS", ";".join(m.block_reasons) or "none")
    kv("VERDICT", m.verdict)


# ── 코퍼스 읽기 ─────────────────────────────────────────────────────────


def _bank_rows(root: Path, rel: str) -> tuple[BankRows, frozenset[str]]:
    """적재기 자신의 로더로 읽는다 — 위생·스키마 거부도 적재기와 같은 판정(dedup은 마지막 우선)."""
    from whymath_backend.l1.problem_bank.populate import load_problem_bank_records

    path = root / rel
    if not path.is_file():
        raise FileNotFoundError(f"은행 파일 없음: {rel}")
    records = load_problem_bank_records(path)
    deduped: dict[str, str] = {}
    srcs: set[str] = set()
    for record in records:
        deduped[record.slug] = str(record.problem.problem_id)
        srcs.update(tag.concept_src_id for tag in record.concept_tags)
    return BankRows(path=rel, rows=tuple(deduped.items())), frozenset(srcs)


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


# ── DB 읽기(읽기 전용) ──────────────────────────────────────────────────


async def _db_rows() -> tuple[int, list[DbRow]]:
    from sqlalchemy import text

    from whymath_backend.db.session import get_engine, get_sessionmaker

    try:
        async with get_sessionmaker()() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            try:
                result = await session.execute(
                    text(
                        "SELECT problem_id::text, slug,"
                        " (cms_edited_at IS NOT NULL OR problem_version_id IS NOT NULL)"
                        " FROM problem"
                    )
                )
                rows = [DbRow(problem_id=r[0], slug=r[1], protected=bool(r[2])) for r in result]
                return len(rows), rows
            finally:
                await session.rollback()
    finally:
        await get_engine().dispose()


def _resolved_srcs(needed: frozenset[str]) -> frozenset[str]:
    """적재기 자신의 해석 함수(SELECT 1회)로 DB에 원자 행이 있는 src를 센다."""
    from whymath_backend.l1.problem_bank import populate

    # 해석 코퍼스 경로는 적재기의 기본값(저장소 루트 상대)을 루트 기준 절대 경로로 넘긴다 — 작업
    # 디렉터리에 따라 다른 파일을 읽지 않게.
    store = populate.ProblemBankStore(
        crosswalk_path=_REPO_ROOT / populate._DEFAULT_CROSSWALK,
        concept_graph_path=_REPO_ROOT / populate._DEFAULT_CONCEPT_GRAPH,
    )
    try:
        resolved = store._load_source_id_to_concept_id()
    finally:
        store._get_engine().dispose()
    return frozenset(src for src in needed if src in resolved)


def _print_code_origin() -> None:
    import whymath_backend.l1.problem_bank.populate as populate
    import whymath_backend.l1.standards.phase3_coverage as cov

    kv("CODE_POPULATE", populate.__file__)
    kv("CODE_PHASE3", cov.__file__)
    kv("CODE_PROBE", Path(__file__).resolve())


def cmd_measure(args: argparse.Namespace) -> int:
    kv("PROBE", "measure")
    if not args.bank:
        kv("PROBE_ERROR", "--bank 0건 - 적재 대상 은행을 지정하라")
        return EXIT_UNMEASURED
    try:
        _print_code_origin()
    except Exception as exc:  # noqa: BLE001 — 백엔드 import 실패(PYTHONPATH 미설정 등)는 exit 2
        kv("PROBE_ERROR", f"{type(exc).__name__}: {str(exc)[:200]}")
        return EXIT_UNMEASURED
    try:
        banks: list[BankRows] = []
        needed: set[str] = set()
        for rel in args.bank:
            bank, srcs = _bank_rows(_REPO_ROOT, rel)
            banks.append(bank)
            needed |= srcs
        eligible = _eligible_by_concept(_REPO_ROOT)
    except Exception as exc:  # noqa: BLE001 — 측정 실패는 exit 2(원인 타입명 병기)
        kv("PROBE_ERROR", f"{type(exc).__name__}: {str(exc)[:200]}")
        return EXIT_UNMEASURED
    if not any(ids for _, ids in eligible):
        kv("PROBE_ERROR", "적격 문항 0건 - 코퍼스 경로 또는 범위 명세 확인")
        return EXIT_UNMEASURED
    if not any(b.rows for b in banks):
        # 스캔 0건은 공허한 측정이다 — 준비 판정을 내지 않는다.
        kv("PROBE_ERROR", "은행 레코드 0건")
        return EXIT_UNMEASURED
    try:
        count, rows = asyncio.run(asyncio.wait_for(_db_rows(), timeout=DB_TIMEOUT_S))
        resolved = _resolved_srcs(frozenset(needed))
    except Exception as exc:  # noqa: BLE001 — DB 미도달·시간 초과는 exit 2
        kv("PROBE_ERROR", f"{type(exc).__name__}: {str(exc)[:200]}")
        return EXIT_UNMEASURED
    emit_measure(
        measure_load(banks, rows, eligible, src_needed=frozenset(needed), src_resolved=resolved),
        count,
    )
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="p3_98_problem_load_probe", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    measure = sub.add_parser("measure", help="은행별 분류·개념별 지금/적재 후 예측·판정")
    measure.add_argument("--bank", action="append", default=[], help="저장소 상대 은행 경로(반복)")
    measure.set_defaults(func=cmd_measure)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
