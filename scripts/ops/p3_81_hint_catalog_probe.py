#!/usr/bin/env python3
"""P3-81 힌트 카탈로그 재적재 런북용 읽기 전용 프로브 (`docs/ops/p3_81_hint_repopulate_runbook.md`).

**왜 필요한가**: P3-77이 힌트 게이트 B·④에 값 동치 축을 넣어 `verified`·`gate_report` 판정이
바뀌었지만, 운영 DB의 `hints` 행은 `populate --apply`를 다시 돌리기 전까지 종전 판정 그대로다.
재적재 전후로 (1) 행 수·검수 분포 (2) 서빙 경로가 정답 누설 L3를 내는지를 같은 눈금으로
재야 하는데, 그 전용 도구가 없었다. 이 스크립트가 그것이다.

**쓰기가 없다**: 모든 DB 접근은 `SET TRANSACTION READ ONLY` 트랜잭션이고 끝에 rollback한다.
쓰기 문장을 보내는 순간 PostgreSQL이 거부한다(코드가 아니라 DB가 막는다). 적재는 이 스크립트가
아니라 `whymath_backend.l4.hint_content.populate --apply`뿐이다.

**출력은 ASCII `KEY=VALUE` 줄이다**: 한국어 Windows 콘솔(cp949)·PowerShell 중계에서 한글이 깨져
판정값이 손상되는 것을 피한다(CLAUDE.md 인코딩 규칙). 힌트 본문은 출력하지 않는다 — 식별자
(`hint_id`)와 판정만 낸다.

서브커맨드
---------
- `stats` — `hints` 행 수·레벨별 검수 분포·값 축 판정 표지·CMS 편집 행·승인 문항 L3 지표.
  첫머리에 **import된 코드의 파일 경로**(`CODE_*`)를 낸다(어느 트리의 코드가 돌았는지 증거).
- `run-summary --json <파일>` — `populate`가 낸 한 줄 JSON을 `KEY=VALUE`로 푼다(파싱 실패는 exit 2).
- `serve-sample` — **서빙 reader(`store.find_served_hint`)를 실제로 불러** 문항 표본 × 단계 × 레벨의
  서빙 결과를 P3-10 `ai_quality_eval` 정답 누설 축(`ai_quality_judges.judge_case("answer_leak")`)과
  **같은 판정기**로 훑는다. 사다리 대체(앞 단계 L3·L2 하향)도 센다.
- `catalog-scan` — 검수 통과(`verified`) 행 전수(또는 `--limit`)를 같은 판정기로 훑는다.

종료 코드(판정은 exit code로 — 출력 문자열이 아니다):
  0 — 측정이 끝났고 지적 없음 · 1 — 정답 누설 행이 있다 · 2 — 측정 실패(DB 미도달·스캔 0건·
  JSON 손상). **스캔 0건을 "누설 0건 통과"로 읽지 않는다.**

사용(런북 단계가 환경변수 `WHYMATH_DATABASE_URL`·`PYTHONPATH`를 먼저 설정한다):
    python scripts/ops/p3_81_hint_catalog_probe.py stats
    python scripts/ops/p3_81_hint_catalog_probe.py run-summary --json work/p3_81/dry.json
    python scripts/ops/p3_81_hint_catalog_probe.py serve-sample --problems 300
    python scripts/ops/p3_81_hint_catalog_probe.py catalog-scan
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

EXIT_OK = 0
EXIT_FINDING = 1
EXIT_UNMEASURED = 2

#: 값 축 판정값 4종(`ValueExposure` 값 + 능력 미주입 `not_run`) — 이 밖의 값은 계약 밖이다.
KNOWN_VALUE_VERDICTS: tuple[str, ...] = ("exposed", "clean", "undecidable", "not_run")
#: 표본 문항 수 기본값·문항당 단계 상한(상한은 폭주 방지 — 경로가 12단계를 넘는 문항은 드물다).
DEFAULT_PROBLEMS = 300
MAX_STEPS_PER_PROBLEM = 12
#: 누설 의심 hint_id를 몇 개까지 출력하나(전부 찍으면 화면이 증거를 가린다).
MAX_LISTED = 10

_VALUE_VERDICT_SQL = "coalesce(gate_report->'answer_leakage'->'detail'->>'value_verdict', '(none)')"

# ── 출력 키 계약 ─────────────────────────────────────────────────────────
# 런북의 PowerShell 블록이 이 키들을 이름으로 읽는다. 키를 바꾸면 런북이 조용히 `-1`(없음)을
# 읽으므로, 출력 가능한 키를 여기에 **전수 선언**하고 `kv`가 선언 밖 키를 거부한다(런타임) —
# 런북 계약 테스트(`tests/infra/test_p3_81_hint_repopulate_runbook.py`)는 런북이 읽는 키가 이
# 선언 안에 있는지 대조한다.
_LEVELS: tuple[int, ...] = (1, 2, 3)
META_KEYS: tuple[str, ...] = ("PROBE", "PROBE_ERROR", "CODE_POPULATE", "CODE_STORE", "CODE_PROBE")
_VERDICT_KEYS: tuple[str, ...] = tuple(name.upper() for name in (*KNOWN_VALUE_VERDICTS, "none"))
STATS_KEYS: tuple[str, ...] = (
    "DB_NAME",
    "DB_SERVER_PORT",
    "DB_SERVER_VERSION_NUM",
    "HINTS_TABLE",
    "ALEMBIC_REVISION",
    "HINTS_CMS_COLUMN",
    "HINTS_ROWS",
    "HINTS_VERIFIED",
    *(f"{kind}_L{level}" for level in _LEVELS for kind in ("ROWS", "VERIFIED", "CARRY_VERIFIED")),
    *(f"VALUE_VERDICT_{scope}_{name}" for scope in ("ALL", "VERIFIED") for name in _VERDICT_KEYS),
    "VALUE_VERDICT_ALL_OTHER",
    "CMS_EDITED_ROWS",
    "HINT_PATHS",
    "PROCESSABLE_PATHS",
    "PROBLEMS_WITH_HINTS",
    "PROBLEMS_NO_VERIFIED_L3",
    "APPROVED_PROBLEMS_WITH_HINTS",
    "APPROVED_ROWS_L3",
    "APPROVED_VERIFIED_L3",
    "APPROVED_PROBLEMS_NO_VERIFIED_L3",
)
RUN_KEYS: tuple[str, ...] = (
    "RUN_APPLIED",
    "RUN_PATHS_SEEN",
    "RUN_PATHS_LOADED",
    "RUN_PATHS_SKIPPED_HEADER",
    "RUN_PATHS_SKIPPED_STEPS",
    "RUN_GENERATED",
    "RUN_VERIFIED",
    "RUN_VERIFIED_RATE",
    *(f"RUN_{kind}_L{level}" for kind in ("GENERATED", "VERIFIED") for level in _LEVELS),
    *(f"RUN_VALUE_{name.upper()}" for name in KNOWN_VALUE_VERDICTS),
    "RUN_VALUE_OTHER",
    "RUN_VALUE_ACCOUNTED",
    "RUN_WRITES",
    "RUN_WRITES_INSERTED",
    "RUN_WRITES_UPDATED",
    "RUN_WRITES_UNCHANGED",
    "RUN_WRITES_RETIRED",
    "RUN_CMS_CONFLICTS",
    "RUN_WELLFORMED",
)
_JUDGE_COUNTS: tuple[str, ...] = (
    "JUDGED",
    "UNJUDGED_NO_ANSWER",
    "VALUE_UNDECIDABLE",
    "LEAK_EXPOSED",
)
SERVE_KEYS: tuple[str, ...] = (
    "SERVE_PROBLEMS_WITH_VERIFIED",
    "SERVE_PROBLEMS_SAMPLED",
    "SERVE_CALLS",
    *(f"SERVE_SERVED_L{level}" for level in _LEVELS),
    *(f"SERVE_NONE_L{level}" for level in _LEVELS),
    "SERVE_L3_DOWNGRADED_TO_L2",
    "SERVE_L3_FROM_EARLIER_STEP",
    *(f"SERVE_{name}" for name in _JUDGE_COUNTS),
    "SERVE_LEAK_HINT",
)
SCAN_KEYS: tuple[str, ...] = (
    "SCAN_LEVELS",
    "SCAN_VERIFIED_ROWS",
    "SCAN_ROWS_SCANNED",
    *(f"SCAN_{name}" for name in _JUDGE_COUNTS),
    "SCAN_LEAK_HINT",
)
ALL_KEYS: frozenset[str] = frozenset((*META_KEYS, *STATS_KEYS, *RUN_KEYS, *SERVE_KEYS, *SCAN_KEYS))


def kv(key: str, value: object) -> None:
    """`KEY=VALUE` 한 줄 — 값은 ASCII로 제한한다(콘솔 인코딩 손상 방지).

    선언되지 않은 키는 거부한다(`ALL_KEYS`) — 런북이 읽는 이름과 출력 이름이 어긋나는 것을
    출력 시점에 잡는다.
    """
    if key not in ALL_KEYS:
        raise KeyError(f"선언되지 않은 출력 키: {key}")
    text = str(value)
    if not text.isascii():
        text = json.dumps(text, ensure_ascii=True)
    print(f"{key}={text}")


# ── DB 접근(읽기 전용) ──────────────────────────────────────────────────


async def _read_only(session: Any) -> None:
    """트랜잭션의 첫 문장으로 읽기 전용을 건다 — 이후 쓰기 문장은 DB가 거부한다."""
    from sqlalchemy import text

    await session.execute(text("SET TRANSACTION READ ONLY"))


async def _scalar(session: Any, sql: str, params: Mapping[str, object] | None = None) -> Any:
    from sqlalchemy import text

    return (await session.execute(text(sql), dict(params or {}))).scalar_one()


async def _with_session(work: Callable[[Any], Awaitable[int]]) -> int:
    """읽기 전용 세션에서 `work`를 돌린다. DB에 못 붙으면 exit 2(원인 타입명 포함)."""
    from whymath_backend.db.session import get_engine, get_sessionmaker

    try:
        async with get_sessionmaker()() as session:
            await _read_only(session)
            try:
                return await work(session)
            finally:
                await session.rollback()
    except Exception as exc:  # noqa: BLE001 — 측정 실패는 exit 2로 올린다(원인 타입명 병기)
        kv("PROBE_ERROR", f"{type(exc).__name__}: {str(exc)[:200]}")
        return EXIT_UNMEASURED
    finally:
        await get_engine().dispose()


def _print_code_origin() -> None:
    """import된 코드의 파일 경로 — 어느 트리의 코드가 돌았는지의 증거."""
    import whymath_backend.l4.hint_content.populate as populate
    import whymath_backend.l4.hint_content.store as store

    kv("CODE_POPULATE", populate.__file__)
    kv("CODE_STORE", store.__file__)
    kv("CODE_PROBE", Path(__file__).resolve())


# ── stats ───────────────────────────────────────────────────────────────


async def _stats(session: Any) -> int:
    from sqlalchemy import text

    kv("DB_NAME", await _scalar(session, "SELECT current_database()"))
    kv("DB_SERVER_PORT", await _scalar(session, "SELECT coalesce(inet_server_port(), -1)"))
    kv("DB_SERVER_VERSION_NUM", await _scalar(session, "SHOW server_version_num"))
    has_table = await _scalar(session, "SELECT to_regclass('public.hints') IS NOT NULL")
    kv("HINTS_TABLE", has_table)
    if not has_table:
        kv("PROBE_ERROR", "hints 테이블이 없다(스키마가 head가 아니거나 다른 DB)")
        return EXIT_UNMEASURED
    try:
        kv("ALEMBIC_REVISION", await _scalar(session, "SELECT version_num FROM alembic_version"))
    except Exception as exc:  # noqa: BLE001 — 리비전 표 부재는 정보일 뿐 측정 실패가 아니다
        kv("ALEMBIC_REVISION", f"unreadable:{type(exc).__name__}")
        await session.rollback()
        await _read_only(session)
    has_cms = await _scalar(
        session,
        "SELECT count(*) = 1 FROM information_schema.columns"
        " WHERE table_name = 'hints' AND column_name = 'cms_edited_at'",
    )
    kv("HINTS_CMS_COLUMN", has_cms)

    kv("HINTS_ROWS", await _scalar(session, "SELECT count(*) FROM hints"))
    kv("HINTS_VERIFIED", await _scalar(session, "SELECT count(*) FROM hints WHERE verified"))
    rows = (
        await session.execute(
            text("SELECT level, verified, count(*) FROM hints GROUP BY level, verified")
        )
    ).all()
    by_level: dict[int, dict[bool, int]] = {1: {}, 2: {}, 3: {}}
    for level, verified, count in rows:
        by_level.setdefault(int(level), {})[bool(verified)] = int(count)
    for level in (1, 2, 3):
        cell = by_level.get(level, {})
        kv(f"ROWS_L{level}", sum(cell.values()))
        kv(f"VERIFIED_L{level}", cell.get(True, 0))

    # 이월 행 — 단계가 실체화된 경로 밖에 있는 검수 통과 행. populate가 처리하지 않으므로 재적재로
    # 바뀌지 않는다. 재적재 뒤 기대 검수 수 = (dry-run 검수 수) + (이월 행 수)이다.
    carry_rows = (
        await session.execute(
            text(
                "SELECT level, count(*) FROM hints WHERE verified AND solution_path_id NOT IN"
                " (SELECT solution_path_id FROM problem_step"
                "  WHERE solution_path_id IS NOT NULL AND expected_answer IS NOT NULL)"
                " GROUP BY level"
            )
        )
    ).all()
    carry = {int(level): int(count) for level, count in carry_rows}
    for level in (1, 2, 3):
        kv(f"CARRY_VERIFIED_L{level}", carry.get(level, 0))

    # 값 축 판정 표지 — P3-77 이전 판정 행은 `value_verdict` 키가 없다((none)). 재적재 뒤에는
    # 검수 통과 행에서 이 표지가 사라지는 것이 정상이다(검수 통과 = clean뿐).
    verdicts = (
        await session.execute(
            text(
                f"SELECT {_VALUE_VERDICT_SQL} AS v, verified, count(*)"
                " FROM hints GROUP BY v, verified"
            )
        )
    ).all()
    tally: Counter[str] = Counter()
    verified_tally: Counter[str] = Counter()
    for verdict, verified, count in verdicts:
        tally[str(verdict)] += int(count)
        if verified:
            verified_tally[str(verdict)] += int(count)
    for name in (*KNOWN_VALUE_VERDICTS, "(none)"):
        key = name.strip("()").upper()
        kv(f"VALUE_VERDICT_ALL_{key}", tally.get(name, 0))
        kv(f"VALUE_VERDICT_VERIFIED_{key}", verified_tally.get(name, 0))
    other = sum(n for name, n in tally.items() if name not in (*KNOWN_VALUE_VERDICTS, "(none)"))
    kv("VALUE_VERDICT_ALL_OTHER", other)

    if has_cms:
        kv(
            "CMS_EDITED_ROWS",
            await _scalar(session, "SELECT count(*) FROM hints WHERE cms_edited_at IS NOT NULL"),
        )
    else:
        kv("CMS_EDITED_ROWS", "n/a")
    kv("HINT_PATHS", await _scalar(session, "SELECT count(DISTINCT solution_path_id) FROM hints"))
    kv(
        "PROCESSABLE_PATHS",
        await _scalar(
            session,
            "SELECT count(DISTINCT solution_path_id) FROM problem_step"
            " WHERE solution_path_id IS NOT NULL AND expected_answer IS NOT NULL",
        ),
    )

    no_l3 = (
        "SELECT count(*) FROM (SELECT h.problem_id FROM hints h {join}"
        " GROUP BY h.problem_id HAVING count(*) FILTER (WHERE h.level = 3 AND h.verified) = 0) t"
    )
    approved_join = (
        "JOIN problem p ON p.problem_id = h.problem_id WHERE p.review_status = 'approved'"
    )
    kv(
        "PROBLEMS_WITH_HINTS",
        await _scalar(session, "SELECT count(DISTINCT problem_id) FROM hints"),
    )
    kv("PROBLEMS_NO_VERIFIED_L3", await _scalar(session, no_l3.format(join="")))
    kv(
        "APPROVED_PROBLEMS_WITH_HINTS",
        await _scalar(
            session,
            "SELECT count(DISTINCT h.problem_id) FROM hints h"
            " JOIN problem p ON p.problem_id = h.problem_id WHERE p.review_status = 'approved'",
        ),
    )
    kv(
        "APPROVED_ROWS_L3",
        await _scalar(
            session,
            "SELECT count(*) FROM hints h JOIN problem p ON p.problem_id = h.problem_id"
            " WHERE p.review_status = 'approved' AND h.level = 3",
        ),
    )
    kv(
        "APPROVED_VERIFIED_L3",
        await _scalar(
            session,
            "SELECT count(*) FROM hints h JOIN problem p ON p.problem_id = h.problem_id"
            " WHERE p.review_status = 'approved' AND h.level = 3 AND h.verified",
        ),
    )
    kv("APPROVED_PROBLEMS_NO_VERIFIED_L3", await _scalar(session, no_l3.format(join=approved_join)))
    return EXIT_OK


def cmd_stats(_args: argparse.Namespace) -> int:
    kv("PROBE", "stats")
    _print_code_origin()
    return asyncio.run(_with_session(_stats))


# ── run-summary ─────────────────────────────────────────────────────────

_REQUIRED_RUN_KEYS: tuple[str, ...] = (
    "applied",
    "paths_seen",
    "paths_loaded",
    "generated",
    "generated_by_level",
    "verified",
    "verified_by_level",
    "value_exposure_verdicts",
    "writes",
)


def summarize_run(report: Mapping[str, Any]) -> list[tuple[str, object]]:
    """`populate` 리포트 JSON → `KEY=VALUE` 목록(순수 — 테스트가 직접 부른다).

    **빠진 키는 0으로 읽지 않는다.** 필수 키가 하나라도 없으면 `RUN_WELLFORMED=False`다 — 리포트가
    깨졌는데 "0건"으로 읽혀 통과하는 것을 막는다(모른다 ≠ 0).
    """
    out: list[tuple[str, object]] = []
    wellformed = all(key in report for key in _REQUIRED_RUN_KEYS)
    generated_raw = report.get("generated")
    generated = generated_raw if isinstance(generated_raw, int) else 0
    wellformed = wellformed and isinstance(generated_raw, int)
    out.append(("RUN_APPLIED", report.get("applied")))
    out.append(("RUN_PATHS_SEEN", report.get("paths_seen", "missing")))
    out.append(("RUN_PATHS_LOADED", report.get("paths_loaded", "missing")))
    out.append(("RUN_PATHS_SKIPPED_HEADER", report.get("paths_skipped_missing_header", "missing")))
    out.append(
        ("RUN_PATHS_SKIPPED_STEPS", report.get("paths_skipped_noncontiguous_steps", "missing"))
    )
    out.append(("RUN_GENERATED", generated_raw if generated_raw is not None else "missing"))
    out.append(("RUN_VERIFIED", report.get("verified", "missing")))
    out.append(("RUN_VERIFIED_RATE", report.get("verified_rate")))
    for field_name, prefix in (
        ("generated_by_level", "GENERATED"),
        ("verified_by_level", "VERIFIED"),
    ):
        cell = report.get(field_name)
        for level in ("1", "2", "3"):
            value = cell.get(level, 0) if isinstance(cell, dict) else "missing"
            out.append((f"RUN_{prefix}_L{level}", value))
    verdicts = report.get("value_exposure_verdicts")
    if isinstance(verdicts, dict):
        for name in KNOWN_VALUE_VERDICTS:
            out.append((f"RUN_VALUE_{name.upper()}", verdicts.get(name, 0)))
        other = sum(
            int(n)
            for name, n in verdicts.items()
            if name not in KNOWN_VALUE_VERDICTS and isinstance(n, int)
        )
        out.append(("RUN_VALUE_OTHER", other))
        total = sum(int(n) for n in verdicts.values() if isinstance(n, int))
        # 모든 생성 힌트가 값 축 판정을 받았나 — 합이 생성 수와 다르면 판정 없이 지나간 힌트가 있다.
        out.append(("RUN_VALUE_ACCOUNTED", generated > 0 and total == generated and other == 0))
    else:
        wellformed = False
        out.append(("RUN_VALUE_ACCOUNTED", False))
    writes = report.get("writes")
    if isinstance(writes, dict):
        out.append(("RUN_WRITES_INSERTED", writes.get("inserted", "missing")))
        out.append(("RUN_WRITES_UPDATED", writes.get("updated", "missing")))
        out.append(("RUN_WRITES_UNCHANGED", writes.get("unchanged", "missing")))
        out.append(("RUN_WRITES_RETIRED", writes.get("retired", "missing")))
        conflicts = writes.get("cms_edit_conflicts")
        out.append(
            ("RUN_CMS_CONFLICTS", len(conflicts) if isinstance(conflicts, list) else "missing")
        )
    else:
        out.append(("RUN_WRITES", "none" if "writes" in report else "missing"))
    out.append(("RUN_WELLFORMED", wellformed))
    return out


def cmd_run_summary(args: argparse.Namespace) -> int:
    kv("PROBE", "run-summary")
    path = Path(args.json)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        kv("PROBE_ERROR", f"{type(exc).__name__}: JSON 파일을 읽지 못했다")
        return EXIT_UNMEASURED
    # populate stdout은 JSON 한 줄이다(진단 문구는 stderr). 마지막 비어 있지 않은 줄을 본다.
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        kv("PROBE_ERROR", "JSON 파일이 비었다 — populate가 리포트를 내지 못했다")
        return EXIT_UNMEASURED
    try:
        report = json.loads(lines[-1])
    except ValueError as exc:
        kv("PROBE_ERROR", f"{type(exc).__name__}: 마지막 줄이 JSON이 아니다")
        return EXIT_UNMEASURED
    if not isinstance(report, dict):
        kv("PROBE_ERROR", "JSON 최상위가 객체가 아니다")
        return EXIT_UNMEASURED
    for key, value in summarize_run(report):
        kv(key, value)
    return EXIT_OK


# ── 정답 누설 판정(P3-10 answer_leak 축과 같은 판정기) ───────────────────


class LeakJudge:
    """`ai_quality_judges.judge_case("answer_leak")`를 힌트 본문에 그대로 부르는 얇은 어댑터.

    새 판정 규칙을 만들지 않는다 — P3-10 평가가 쓰는 판정기(정답 문자열·선언 어구·값 동치 산술식·
    최종 풀이 단계)를 같은 입력 모양(`ProblemMaterial`·`TutorResponse`)으로 부른다.
    """

    def __init__(self) -> None:
        from whymath_backend.harness.ai_quality_eval_set import EvalSet
        from whymath_backend.harness.ai_quality_judges import JudgeContext

        self._eval_set_cls = EvalSet
        self._ctx_cls = JudgeContext

    def judge(
        self, *, problem_id: uuid.UUID, answer: str | None, steps: Sequence[str], content: str
    ) -> tuple[bool, bool, bool, str]:
        """(대상 여부, 통과 여부, 값 동치 판정 불가 여부, 사유 요약).

        대상 아님 = 정답 원천이 없어 판정 못 함(측정 한계 — 통과로 세지 않는다).
        """
        from whymath_backend.harness.ai_quality_eval_set import KIND_HINT, EvalCase, ProblemMaterial
        from whymath_backend.harness.ai_quality_judges import TutorResponse, judge_case

        pid = str(problem_id)
        case = EvalCase(
            case_id=f"p3-81-{pid}",
            kind=KIND_HINT,
            problem_id=pid,
            concept_code="",
            concept_id="",
            student_band="",
            verdict=None,
            answer_known_to_student=False,
        )
        material = ProblemMaterial(
            problem_id=pid,
            problem_uuid=problem_id,
            answer=answer or "",
            conditions=(),
            solution_steps=tuple(steps),
            choices=(),
            distractor_map=(),
        )
        ctx = self._ctx_cls(
            registry=None,  # type: ignore[arg-type]  # answer_leak 축은 레지스트리를 읽지 않는다
            eval_set=self._eval_set_cls(
                cases=(), materials={pid: material}, source="p3-81-db", sha256=""
            ),
        )
        response = TutorResponse(case_id=case.case_id, tutor_output={"explanation": content})
        verdict = judge_case("answer_leak", case, response, ctx)
        undecidable = bool(verdict.counters.get("equivalent_expr_undecidable", 0))
        return verdict.applicable, verdict.passed, undecidable, "; ".join(verdict.reasons)


async def _path_context(
    session: Any, path_id: str, cache: dict[str, tuple[uuid.UUID, str | None, tuple[str, ...]]]
) -> tuple[uuid.UUID, str | None, tuple[str, ...]]:
    """경로 id → (문항 id, 문항 정답, 단계 본문) — 판정기 입력 재료. 경로당 한 번만 읽는다."""
    from sqlalchemy import text

    if path_id in cache:
        return cache[path_id]
    head = (
        await session.execute(
            text(
                "SELECT sp.problem_id, p.answer FROM solution_paths sp"
                " JOIN problem p ON p.problem_id = sp.problem_id WHERE sp.solution_path_id = :sp"
            ),
            {"sp": path_id},
        )
    ).one()
    steps = (
        (
            await session.execute(
                text(
                    "SELECT expected_answer FROM problem_step WHERE solution_path_id = :sp"
                    " AND expected_answer IS NOT NULL ORDER BY step_order"
                ),
                {"sp": path_id},
            )
        )
        .scalars()
        .all()
    )
    cache[path_id] = (head[0], head[1], tuple(str(s) for s in steps))
    return cache[path_id]


def _even_sample(items: Sequence[Any], limit: int) -> list[Any]:
    """정렬된 목록에서 고르게 `limit`개 — 결정론(같은 데이터면 같은 표본)."""
    if limit <= 0 or len(items) <= limit:
        return list(items)
    stride = len(items) / limit
    return [items[int(i * stride)] for i in range(limit)]


# ── serve-sample ────────────────────────────────────────────────────────


def _make_serve_sample(problems: int) -> Callable[[Any], Awaitable[int]]:
    async def _serve_sample(session: Any) -> int:
        from sqlalchemy import text

        from whymath_backend.l4.hint_content.store import find_served_hint

        judge = LeakJudge()
        ids = (
            (
                await session.execute(
                    text(
                        "SELECT DISTINCT problem_id FROM hints WHERE verified"
                        " ORDER BY problem_id"
                    )
                )
            )
            .scalars()
            .all()
        )
        sample = _even_sample(ids, problems)
        kv("SERVE_PROBLEMS_WITH_VERIFIED", len(ids))
        kv("SERVE_PROBLEMS_SAMPLED", len(sample))
        counts: Counter[str] = Counter()
        flagged: list[str] = []
        cache: dict[str, tuple[uuid.UUID, str | None, tuple[str, ...]]] = {}
        for pid in sample:
            max_step = int(
                await _scalar(
                    session, "SELECT max(step_order) FROM hints WHERE problem_id = :p", {"p": pid}
                )
            )
            for from_step in range(1, min(max_step, MAX_STEPS_PER_PROBLEM) + 1):
                for level in (1, 2, 3):
                    counts["calls"] += 1
                    served = await find_served_hint(
                        session, problem_id=pid, hint_level=level, from_step_order=from_step
                    )
                    if served is None:
                        counts[f"none_l{level}"] += 1
                        continue
                    counts[f"served_l{served.level}"] += 1
                    if level == 3 and served.level == 2:
                        counts["l3_downgraded_to_l2"] += 1
                    if level == 3 and served.level == 3 and served.step_order < from_step:
                        counts["l3_from_earlier_step"] += 1
                    path_id = await _scalar(
                        session,
                        "SELECT solution_path_id FROM hints WHERE hint_id = :h",
                        {"h": served.hint_id},
                    )
                    problem_id, answer, steps = await _path_context(session, path_id, cache)
                    applicable, passed, undecidable, reason = judge.judge(
                        problem_id=problem_id, answer=answer, steps=steps, content=served.content
                    )
                    if not applicable:
                        counts["unjudged_no_answer"] += 1
                        continue
                    counts["judged"] += 1
                    if undecidable:
                        counts["value_undecidable"] += 1
                    if not passed:
                        counts["leak_exposed"] += 1
                        if len(flagged) < MAX_LISTED:
                            flagged.append(f"{served.hint_id}|{reason[:80]}")
        for key in (
            "calls",
            "served_l1",
            "served_l2",
            "served_l3",
            "none_l1",
            "none_l2",
            "none_l3",
            "l3_downgraded_to_l2",
            "l3_from_earlier_step",
            "judged",
            "unjudged_no_answer",
            "value_undecidable",
            "leak_exposed",
        ):
            kv(f"SERVE_{key.upper()}", counts.get(key, 0))
        for item in flagged:
            kv("SERVE_LEAK_HINT", item)
        if counts["judged"] == 0:
            kv("PROBE_ERROR", "판정한 서빙 결과가 0건이다 — 스캔 0건은 통과가 아니다")
            return EXIT_UNMEASURED
        return EXIT_FINDING if counts["leak_exposed"] else EXIT_OK

    return _serve_sample


def cmd_serve_sample(args: argparse.Namespace) -> int:
    kv("PROBE", "serve-sample")
    _print_code_origin()
    return asyncio.run(_with_session(_make_serve_sample(args.problems)))


# ── catalog-scan ────────────────────────────────────────────────────────


def _make_catalog_scan(limit: int, levels: Sequence[int]) -> Callable[[Any], Awaitable[int]]:
    async def _catalog_scan(session: Any) -> int:
        from sqlalchemy import text

        judge = LeakJudge()
        rows = (
            await session.execute(
                text(
                    "SELECT hint_id, solution_path_id, content FROM hints"
                    " WHERE verified AND level = ANY(:levels) ORDER BY hint_id"
                ),
                {"levels": list(levels)},
            )
        ).all()
        kv("SCAN_LEVELS", ",".join(str(level) for level in levels))
        kv("SCAN_VERIFIED_ROWS", len(rows))
        picked = _even_sample(rows, limit)
        kv("SCAN_ROWS_SCANNED", len(picked))
        counts: Counter[str] = Counter()
        flagged: list[str] = []
        cache: dict[str, tuple[uuid.UUID, str | None, tuple[str, ...]]] = {}
        for hint_id, path_id, content in picked:
            problem_id, answer, steps = await _path_context(session, path_id, cache)
            applicable, passed, undecidable, reason = judge.judge(
                problem_id=problem_id, answer=answer, steps=steps, content=content
            )
            if not applicable:
                counts["unjudged_no_answer"] += 1
                continue
            counts["judged"] += 1
            if undecidable:
                counts["value_undecidable"] += 1
            if not passed:
                counts["leak_exposed"] += 1
                if len(flagged) < MAX_LISTED:
                    flagged.append(f"{hint_id}|{reason[:80]}")
        for key in ("judged", "unjudged_no_answer", "value_undecidable", "leak_exposed"):
            kv(f"SCAN_{key.upper()}", counts.get(key, 0))
        for item in flagged:
            kv("SCAN_LEAK_HINT", item)
        if counts["judged"] == 0:
            kv("PROBE_ERROR", "판정한 행이 0건이다 — 스캔 0건은 통과가 아니다")
            return EXIT_UNMEASURED
        return EXIT_FINDING if counts["leak_exposed"] else EXIT_OK

    return _catalog_scan


def cmd_catalog_scan(args: argparse.Namespace) -> int:
    kv("PROBE", "catalog-scan")
    _print_code_origin()
    levels = [int(token) for token in args.levels.split(",") if token.strip()]
    return asyncio.run(_with_session(_make_catalog_scan(args.limit, levels)))


# ── 진입 ───────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="p3_81_hint_catalog_probe",
        description="P3-81 힌트 카탈로그 재적재 런북용 읽기 전용 프로브(쓰기 없음).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("stats", help="hints 행 수·검수 분포·값 축 표지·승인 문항 L3 지표").set_defaults(
        func=cmd_stats
    )
    summary = sub.add_parser("run-summary", help="populate JSON 한 줄을 KEY=VALUE로 푼다")
    summary.add_argument("--json", required=True, help="populate stdout을 저장한 파일")
    summary.set_defaults(func=cmd_run_summary)
    serve = sub.add_parser("serve-sample", help="서빙 reader 표본의 정답 누설 판정")
    serve.add_argument("--problems", type=int, default=DEFAULT_PROBLEMS, help="표본 문항 수")
    serve.set_defaults(func=cmd_serve_sample)
    scan = sub.add_parser("catalog-scan", help="검수 통과 행의 정답 누설 판정")
    scan.add_argument("--limit", type=int, default=0, help="0이면 전수, 아니면 고른 표본 수")
    scan.add_argument("--levels", default="3", help="쉼표로 구분한 레벨(기본 3)")
    scan.set_defaults(func=cmd_catalog_scan)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
