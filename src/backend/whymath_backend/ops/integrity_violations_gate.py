"""데이터 무결성 게이트 — orphan·dangling·duplicate·발행포인터 7종 단일 CLI (OPS-55·EOS-07).

배경
----
`docs/reviews/eos_plan52_crosswalk_2026-09.md` §H2(갭 후보 #12)가 지목한 공백: 이 저장소는
hypertable·cross-dataset·오프라인 독립성 등의 이유로 다수 참조 컬럼을 **의도적으로 FK가 아닌
"느슨참조"**(모델 docstring 표현)로 둔다(`concept_node.concept_id`·`concept.behavior_skills`·
`solution_nodes.problem_id` 등). DB 제약이 막지 못하므로, 참조 대상이 삭제·재-ID(rename)되면
참조하는 행은 조용히 고아가 된다 — 실측 선례 = `scripts/diagnose_atom_orphans.py`(S2-04, "prod
미적분 raw 129건 orphan"). 이 CLI가 그 점검을 **6종 단일 지점**으로 정례화한다(주간 지표 #4 산출원).

7종 판정 항목
------------
① ORPHAN_CONCEPT           — `concept_node.concept_id`(검색 투영) 중 `concept.code`(런타임
  그래프, 동일 UC 키공간 — `concept.py` 주석 "code = concept_id(개념그래프 UC)")에 없는 것.
② ORPHAN_SKILL              — `concept.behavior_skills`·`concept_node.behavior_skills`·
  `skill_node.prerequisite_skill_ids`(모두 배열·느슨참조)가 가리키는 skill_id 중
  `skill_node.skill_id`에 없는 것.
③ ORPHAN_PROBLEM            — WH-S 솔버 자산(`solution_nodes`·`verified_lemmas`·
  `verified_solutions`·`dead_end_log`·`problem_embedding`의 `problem_id` — 전부 "WH-S 오프라인
  독립성" 느슨참조로 모델 docstring 확정)이 가리키는 problem_id 중 `problem.problem_id`에 없는 것.
④ DANGLING_CURRICULUM_REF   — `concept_node.standard_codes`·`skill_node.standard_codes`(NCIC
  성취기준 코드 배열·느슨참조)가 가리키는 코드 중 `achievement_standard.official_code`에 없는 것.
⑤ DUPLICATE_CANONICAL_ID    — `concept.code`(canonical_id — `math.<area>.<slug>`, Part 9 재-ID)가
  *다른* 개념 행의 `aliases`(구 키 별칭 배열)에도 값으로 들어있는 경우. `code`는 DB UNIQUE라
  같은 컬럼 내부 중복은 이미 불가능하지만, `aliases`는 배열이라 DB 제약이 못 잡는 교차 충돌
  (한 식별자가 A의 canonical이면서 B의 alias로도 존재 — 키 해석이 행마다 달라지는 위험)이다.
⑥ EVENT_SCHEMA_INVALID      — `attempt_event.event_data`가 채워진 행 중 `event_type`이
  `schema/event_data_contract.py`의 `EVENT_DATA_CONTRACT`(계약 있는 7종)에 해당하는데 그 Pydantic
  계약으로 재검증(`model_validate`)했을 때 실패하는 것(invariant ⑫ "event_data 자유 JSONB 금지·
  타입별 계약"의 사후 감사 — 생산 좌석은 `build_event_data`가 이미 강제하나, 이 게이트는 과거
  적재분·생산 좌석 우회분의 드리프트를 잡는다).
⑦ PUBLISHED_VERSION_INVALID — `concept.current_published_version_id`가 가리키는
  `concept_version` 행이 **발행본이 아닌** 경우(status ≠ PUBLISHED) 또는 **다른 개념의 버전**을
  가리키는 경우(`concept_version.concept_id` ≠ `concept.code`). 계획서 200 §27 검사 ⑤
  ("모든 published entity의 version이 존재하는가")의 이 스키마에서의 형태다 — `EOS-07`.

  *행의 존재*는 FK(`fk_concept_current_published_version_id_concept_version`)가 이미 막으므로
  여기서 다시 세지 않는다. DB가 막지 못하는 축은 **가리킨 버전의 상태와 귀속** 둘이며, 그것이
  깨지면 "발행됐다"는 표시가 DRAFT 본문을 가리키거나 남의 개념을 가리킨다.

  이 kind는 **참된 0-불변식**이다(현재 `concept_version` 좌석이 비어 있어 0이고, 채워져도
  올바른 발행 경로를 지나면 0으로 남는다). 반면 계획서 §27 검사 ①("모든 Problem이 최소 1개
  Skill과 연결")은 여기 넣지 않았다 — 실측(2026-09-16·코퍼스 전수) 결과 문제 14,034건 중
  **89.5%만** 스킬까지 해소되므로, 차단 kind로 넣으면 prod에서 상시 red가 되어 사람이 게이트를
  끄게 만든다(CLAUDE.md "상시 실패하는 fail-open 보호를 '보호 있음'으로 신뢰 금지"가 겨냥하는
  상태를 새로 만드는 셈). 그 축은 커버리지 지표이지 무결성 위반이 아니므로 `--skill-coverage`
  리포트로 분리했다(아래 「사용」).

종료 코드
--------
- 0 : 7종 전부 위반 0건.
- 1 : 위반 ≥1건.

스캔 대상 개수를 모든 kind에 함께 출력한다(CLAUDE.md "절단 출력을 부재 판정에 쓰지 않는다" —
0건이 "위반 없음"인지 "스캔 대상 자체가 0"인지 항상 구분 가능하게 한다).

사용
----
    python -m whymath_backend.ops.integrity_violations_gate
    python -m whymath_backend.ops.integrity_violations_gate --json report.json
    # attempt_event가 큰 prod에서 ⑥ 스캔 범위를 최근 N일로 제한(기본은 전건 — 정확성 우선):
    python -m whymath_backend.ops.integrity_violations_gate --event-since-days 30

DB 왕복은 실 PostgreSQL을 요구한다(hermetic 단위테스트는 `main(scan_fn=...)` 주입으로 CLI
배선만 검증 — `role_grant_cli.py` 선례). 실 DB 6종 각각의 검출 변별력(주입 성공/실패 양쪽 신호)은
`@pytest.mark.integration` 통합테스트가 검증한다.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.session import dispose_engine, get_sessionmaker
from whymath_backend.schema.event_data_contract import EVENT_DATA_CONTRACT

__all__ = [
    "KIND_DANGLING_CURRICULUM_REF",
    "KIND_DUPLICATE_CANONICAL_ID",
    "KIND_EVENT_SCHEMA_INVALID",
    "KIND_ORPHAN_CONCEPT",
    "KIND_ORPHAN_PROBLEM",
    "KIND_ORPHAN_SKILL",
    "ALL_KINDS",
    "IntegrityReport",
    "ScanFn",
    "Violation",
    "main",
    "scan_integrity",
    "skill_coverage",
]

_EXIT_OK = 0
_EXIT_VIOLATIONS = 1

KIND_ORPHAN_CONCEPT = "ORPHAN_CONCEPT"
KIND_ORPHAN_SKILL = "ORPHAN_SKILL"
KIND_ORPHAN_PROBLEM = "ORPHAN_PROBLEM"
KIND_DANGLING_CURRICULUM_REF = "DANGLING_CURRICULUM_REF"
KIND_DUPLICATE_CANONICAL_ID = "DUPLICATE_CANONICAL_ID"
KIND_EVENT_SCHEMA_INVALID = "EVENT_SCHEMA_INVALID"
KIND_PUBLISHED_VERSION_INVALID = "PUBLISHED_VERSION_INVALID"

ALL_KINDS: tuple[str, ...] = (
    KIND_ORPHAN_CONCEPT,
    KIND_ORPHAN_SKILL,
    KIND_ORPHAN_PROBLEM,
    KIND_DANGLING_CURRICULUM_REF,
    KIND_DUPLICATE_CANONICAL_ID,
    KIND_EVENT_SCHEMA_INVALID,
    KIND_PUBLISHED_VERSION_INVALID,
)

# WH-S 솔버 자산 5테이블 — 전부 모듈 docstring이 "problem_id는 FK 아닌 느슨참조(WH-S 오프라인
# 독립성)"로 명시 확정한 것만 대상(느슨참조 23파일 전수 확장은 의도적 비대상 — 과공학 방지).
_ORPHAN_PROBLEM_SOURCE_TABLES: tuple[str, ...] = (
    "solution_nodes",
    "verified_lemmas",
    "verified_solutions",
    "dead_end_log",
    "problem_embedding",
)


@dataclass(slots=True, frozen=True)
class Violation:
    kind: str
    identifier: str
    detail: str


@dataclass(slots=True)
class IntegrityReport:
    # kind → 스캔한 참조/행 개수(0건 위반이 "스캔 대상 0"과 구분되게 — 절단 출력 금지 규칙).
    scanned: dict[str, int] = field(default_factory=dict)
    violations: list[Violation] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return _EXIT_OK if not self.violations else _EXIT_VIOLATIONS

    def violations_by_kind(self, kind: str) -> list[Violation]:
        return [v for v in self.violations if v.kind == kind]


async def _check_orphan_concept(session: AsyncSession) -> tuple[int, list[Violation]]:
    scanned = (await session.execute(text("SELECT count(*) FROM concept_node"))).scalar_one()
    rows = await session.execute(text("""
            SELECT cn.concept_id
              FROM concept_node cn
             WHERE NOT EXISTS (SELECT 1 FROM concept c WHERE c.code = cn.concept_id)
             ORDER BY cn.concept_id
            """))
    violations = [
        Violation(
            kind=KIND_ORPHAN_CONCEPT,
            identifier=concept_id,
            detail=f"concept_node.concept_id={concept_id!r} 이(가) concept.code에 없다.",
        )
        for (concept_id,) in rows
    ]
    return int(scanned), violations


async def _check_orphan_skill(session: AsyncSession) -> tuple[int, list[Violation]]:
    refs_sql = text("""
        WITH refs AS (
            SELECT unnest(behavior_skills) AS skill_id, 'concept.behavior_skills' AS src
              FROM concept
             UNION ALL
            SELECT unnest(behavior_skills), 'concept_node.behavior_skills'
              FROM concept_node
             UNION ALL
            SELECT unnest(prerequisite_skill_ids), 'skill_node.prerequisite_skill_ids'
              FROM skill_node
        )
        SELECT skill_id, array_agg(DISTINCT src ORDER BY src) AS sources
          FROM refs
         WHERE NOT EXISTS (SELECT 1 FROM skill_node sn WHERE sn.skill_id = refs.skill_id)
         GROUP BY skill_id
         ORDER BY skill_id
        """)
    scanned_sql = text("""
        SELECT count(DISTINCT skill_id) FROM (
            SELECT unnest(behavior_skills) AS skill_id FROM concept
             UNION ALL
            SELECT unnest(behavior_skills) FROM concept_node
             UNION ALL
            SELECT unnest(prerequisite_skill_ids) FROM skill_node
        ) refs
        """)
    scanned = (await session.execute(scanned_sql)).scalar_one()
    rows = await session.execute(refs_sql)
    violations = [
        Violation(
            kind=KIND_ORPHAN_SKILL,
            identifier=skill_id,
            detail=(
                f"skill_id={skill_id!r} 이(가) skill_node.skill_id에 없다 "
                f"(참조원: {', '.join(sources)})."
            ),
        )
        for (skill_id, sources) in rows
    ]
    return int(scanned), violations


async def _check_orphan_problem(session: AsyncSession) -> tuple[int, list[Violation]]:
    union_all = " UNION ALL ".join(
        f"SELECT problem_id, '{table}' AS src FROM {table}"
        for table in _ORPHAN_PROBLEM_SOURCE_TABLES
    )
    scanned_sql = text(f"SELECT count(DISTINCT problem_id) FROM ({union_all}) refs")
    violations_sql = text(f"""
        WITH refs AS ({union_all})
        SELECT problem_id, array_agg(DISTINCT src ORDER BY src) AS sources
          FROM refs
         WHERE NOT EXISTS (SELECT 1 FROM problem p WHERE p.problem_id = refs.problem_id)
         GROUP BY problem_id
         ORDER BY problem_id
        """)
    scanned = (await session.execute(scanned_sql)).scalar_one()
    rows = await session.execute(violations_sql)
    violations = [
        Violation(
            kind=KIND_ORPHAN_PROBLEM,
            identifier=str(problem_id),
            detail=(
                f"problem_id={problem_id} 이(가) problem.problem_id에 없다 "
                f"(참조원: {', '.join(sources)})."
            ),
        )
        for (problem_id, sources) in rows
    ]
    return int(scanned), violations


async def _check_dangling_curriculum_ref(session: AsyncSession) -> tuple[int, list[Violation]]:
    refs_cte = """
        WITH refs AS (
            SELECT unnest(standard_codes) AS code, 'concept_node.standard_codes' AS src
              FROM concept_node
             UNION ALL
            SELECT unnest(standard_codes), 'skill_node.standard_codes'
              FROM skill_node
        )
    """
    scanned = (
        await session.execute(text(refs_cte + "SELECT count(DISTINCT code) FROM refs"))
    ).scalar_one()
    rows = await session.execute(text(refs_cte + """
            SELECT code, array_agg(DISTINCT src ORDER BY src) AS sources
              FROM refs
             WHERE NOT EXISTS (
                 SELECT 1 FROM achievement_standard a WHERE a.official_code = refs.code
             )
             GROUP BY code
             ORDER BY code
            """))
    violations = [
        Violation(
            kind=KIND_DANGLING_CURRICULUM_REF,
            identifier=code,
            detail=(
                f"성취기준 코드={code!r} 이(가) achievement_standard.official_code에 없다 "
                f"(참조원: {', '.join(sources)})."
            ),
        )
        for (code, sources) in rows
    ]
    return int(scanned), violations


async def _check_duplicate_canonical_id(session: AsyncSession) -> tuple[int, list[Violation]]:
    scanned = (await session.execute(text("SELECT count(*) FROM concept"))).scalar_one()
    rows = await session.execute(text("""
            SELECT c1.code, array_agg(DISTINCT c2.code ORDER BY c2.code) AS alias_holder_codes
              FROM concept c1
              JOIN concept c2
                ON c1.code = ANY(c2.aliases)
               AND c1.concept_id != c2.concept_id
             GROUP BY c1.code
             ORDER BY c1.code
            """))
    violations = [
        Violation(
            kind=KIND_DUPLICATE_CANONICAL_ID,
            identifier=code,
            detail=(
                f"canonical_id={code!r} 이(가) 다른 개념의 aliases에도 존재한다 "
                f"(alias 보유 개념: {', '.join(holders)})."
            ),
        )
        for (code, holders) in rows
    ]
    return int(scanned), violations


async def _check_event_schema_invalid(
    session: AsyncSession, *, since_days: int | None
) -> tuple[int, list[Violation]]:
    contracted_types = sorted(et.value for et in EVENT_DATA_CONTRACT)
    where_clauses = ["event_type = ANY(:types)", "event_data IS NOT NULL"]
    params: dict[str, Any] = {"types": contracted_types}
    if since_days is not None:
        where_clauses.append("event_at >= :since")
        params["since"] = datetime.now(UTC) - timedelta(days=since_days)
    where_sql = " AND ".join(where_clauses)

    scanned = (
        await session.execute(text(f"SELECT count(*) FROM attempt_event WHERE {where_sql}"), params)
    ).scalar_one()

    rows = await session.execute(
        text(
            f"SELECT event_id, event_at, event_type, event_data "
            f"FROM attempt_event WHERE {where_sql} ORDER BY event_id"
        ),
        params,
    )
    violations: list[Violation] = []
    for event_id, event_at, event_type, event_data in rows:
        model = EVENT_DATA_CONTRACT.get(event_type)
        if model is None:  # pragma: no cover — WHERE 절이 이미 계약 있는 타입만 통과시킨다
            continue
        try:
            model.model_validate(event_data)
        except ValidationError as exc:
            violations.append(
                Violation(
                    kind=KIND_EVENT_SCHEMA_INVALID,
                    identifier=f"attempt_event#{event_id}",
                    detail=(
                        f"event_type={event_type!r}(event_at={event_at}) 의 event_data가 "
                        f"계약 위반 — {exc.error_count()}건: {exc.errors()[0].get('msg', '')}"
                    ),
                )
            )
    return int(scanned), violations


@dataclass(slots=True, frozen=True)
class SkillCoverage:
    """문제 → 스킬 해소 커버리지 — **지표이지 위반이 아니다** (계획서 200 §27 검사 ①).

    왜 게이트 kind가 아닌가: 실측(2026-09-16·코퍼스 전수) 결과 문제 14,034건 중 개념 연결은
    95.7%, **스킬까지 해소는 89.5%**다. 나머지 10.5%는 참조가 깨진 것이 아니라 *아직 스킬이
    붙지 않은* 것이며(Skill 27건 대 개념 437건), 그것을 차단 kind로 넣으면 prod에서 상시 red가
    되어 사람이 게이트 자체를 끄게 만든다 — 보호를 하나 세우는 대신 있던 보호까지 잃는다.

    그래서 이 리포트는 **exit code에 영향을 주지 않는다.** 차단 kind로의 승격 조건은 prod 실측
    기준선이며, 그것은 이 코드가 아니라 사람이 정한다(게이트 `G-eos07-skill-coverage-baseline`).

    세 수는 서로 다른 사태를 가리킨다(2분류로 접으면 뭉개진다):
      total          문제 전체
      with_concept   `problem_concept` 행이 하나라도 있는 문제
      with_skill     그 개념들 중 하나라도 `behavior_skills`가 실재 `skill_node`를 가리키는 문제
    """

    total: int
    with_concept: int
    with_skill: int

    @property
    def concept_ratio(self) -> float:
        return 0.0 if not self.total else self.with_concept / self.total

    @property
    def skill_ratio(self) -> float:
        return 0.0 if not self.total else self.with_skill / self.total


async def skill_coverage(session: AsyncSession) -> SkillCoverage:
    """문제 → 개념 → 스킬 해소 커버리지 측정 — 판정이 아니라 관측이다."""
    row = (await session.execute(text("""
            SELECT
              (SELECT count(*) FROM problem) AS total,
              (SELECT count(DISTINCT pc.problem_id) FROM problem_concept pc) AS with_concept,
              (SELECT count(DISTINCT pc.problem_id)
                 FROM problem_concept pc
                 JOIN concept c ON c.concept_id = pc.concept_id
                WHERE EXISTS (
                        SELECT 1 FROM skill_node sn
                         WHERE sn.skill_id = ANY(c.behavior_skills)
                      )) AS with_skill
            """))).one()
    return SkillCoverage(total=int(row[0]), with_concept=int(row[1]), with_skill=int(row[2]))


async def _check_published_version_invalid(
    session: AsyncSession,
) -> tuple[int, list[Violation]]:
    """발행 포인터의 **상태·귀속** 검사 (계획서 200 §27 검사 ⑤ · EOS-07).

    행의 존재는 FK가 막으므로 세지 않는다. 여기서 보는 것은 DB가 못 막는 둘이다:
      · 가리킨 버전의 `status`가 PUBLISHED가 아니다 → "발행됐다"가 DRAFT 본문을 가리킨다.
      · 가리킨 버전의 `concept_id`가 이 개념의 `code`가 아니다 → 남의 개념 버전을 가리킨다.

    `scanned`는 **발행 포인터가 설정된 개념 수**다(전체 개념 수가 아니다) — 포인터가 없는
    개념은 이 불변식의 대상이 아니므로 분모에 넣으면 "위반률"이 실제보다 작아 보인다.
    """
    scanned = (
        await session.execute(
            text("SELECT count(*) FROM concept WHERE current_published_version_id IS NOT NULL")
        )
    ).scalar_one()
    rows = await session.execute(text("""
            SELECT c.code, cv.status::text, cv.concept_id
              FROM concept c
              JOIN concept_version cv ON cv.version_id = c.current_published_version_id
             WHERE cv.status <> 'PUBLISHED' OR cv.concept_id <> c.code
             ORDER BY c.code
            """))
    violations = [
        Violation(
            kind=KIND_PUBLISHED_VERSION_INVALID,
            identifier=code,
            detail=(
                f"concept.code={code!r} 의 발행 포인터가 "
                f"status={status!r}·concept_id={owner!r} 인 버전을 가리킨다 "
                f"(요구: status='PUBLISHED' 이고 concept_id={code!r})."
            ),
        )
        for (code, status, owner) in rows
    ]
    return int(scanned), violations


async def scan_integrity(
    session: AsyncSession, *, event_since_days: int | None = None
) -> IntegrityReport:
    """7종 전부를 실 세션으로 스캔해 `IntegrityReport`를 합성한다."""
    report = IntegrityReport()

    checks: list[tuple[str, Callable[[], Awaitable[tuple[int, list[Violation]]]]]] = [
        (KIND_ORPHAN_CONCEPT, lambda: _check_orphan_concept(session)),
        (KIND_ORPHAN_SKILL, lambda: _check_orphan_skill(session)),
        (KIND_ORPHAN_PROBLEM, lambda: _check_orphan_problem(session)),
        (KIND_DANGLING_CURRICULUM_REF, lambda: _check_dangling_curriculum_ref(session)),
        (KIND_DUPLICATE_CANONICAL_ID, lambda: _check_duplicate_canonical_id(session)),
        (
            KIND_EVENT_SCHEMA_INVALID,
            lambda: _check_event_schema_invalid(session, since_days=event_since_days),
        ),
        (KIND_PUBLISHED_VERSION_INVALID, lambda: _check_published_version_invalid(session)),
    ]
    for kind, check in checks:
        scanned, violations = await check()
        report.scanned[kind] = scanned
        report.violations.extend(violations)
    return report


ScanFn = Callable[[], Awaitable[IntegrityReport]]


async def _default_scan_fn(*, event_since_days: int | None) -> IntegrityReport:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        return await scan_integrity(session, event_since_days=event_since_days)


def _render_stdout(report: IntegrityReport) -> str:
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("데이터 무결성 게이트 (OPS-55·v_integrity_violations)")
    lines.append("=" * 60)
    for kind in ALL_KINDS:
        scanned = report.scanned.get(kind, 0)
        kind_violations = report.violations_by_kind(kind)
        lines.append(f"[{kind}] 스캔 {scanned}건 · 위반 {len(kind_violations)}건")
        for v in kind_violations[:10]:
            lines.append(f"    ✗ {v.identifier}: {v.detail}")
        if len(kind_violations) > 10:
            lines.append(f"    … 외 {len(kind_violations) - 10}건 (JSON 리포트 참조)")
    lines.append("-" * 60)
    total = len(report.violations)
    verdict = "정상(exit 0)" if total == 0 else f"위반 발견 {total}건(exit 1)"
    lines.append(f"결과: {verdict}")
    lines.append("=" * 60)
    return "\n".join(lines)


def _write_json(report: IntegrityReport, path: str) -> None:
    payload = {
        "scanned": report.scanned,
        "violations": [dataclasses.asdict(v) for v in report.violations],
        "exit_code": report.exit_code,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


async def _run_skill_coverage(scan_fn: ScanFn | None) -> SkillCoverage | None:
    """커버리지 측정 — 주입된 scan_fn 테스트에서는 DB를 열지 않는다(None으로 건너뛴다)."""
    if scan_fn is not None:
        return None
    sessionmaker = get_sessionmaker()
    try:
        async with sessionmaker() as session:
            return await skill_coverage(session)
    finally:
        await dispose_engine()


def _render_skill_coverage(coverage: SkillCoverage | None) -> str:
    if coverage is None:
        return "※ 스킬 커버리지: 측정 생략(주입 세션) — 0%가 아니라 **미측정**이다."
    return "\n".join(
        [
            "-" * 60,
            "스킬 커버리지 (계획서 200 §27 ① — 지표이지 위반이 아니다·exit code 무영향)",
            f"  문제 전체              : {coverage.total}",
            f"  개념 연결 보유          : {coverage.with_concept} ({coverage.concept_ratio:.1%})",
            f"  스킬까지 해소 가능       : {coverage.with_skill} ({coverage.skill_ratio:.1%})",
            "  ※ 스캔 대상 0이면 위 비율 0%는 '커버리지 0'이 아니라 '측정 대상 없음'이다.",
        ]
    )


def main(argv: list[str] | None = None, *, scan_fn: ScanFn | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.ops.integrity_violations_gate",
        description="데이터 무결성 게이트 — orphan·dangling·duplicate·발행포인터 7종 단일 CLI.",
    )
    parser.add_argument(
        "--json",
        dest="json_path",
        default=None,
        help="JSON 리포트 저장 경로(선택).",
    )
    parser.add_argument(
        "--event-since-days",
        dest="event_since_days",
        type=int,
        default=None,
        help=(
            "⑥ EVENT_SCHEMA_INVALID 스캔을 최근 N일로 제한(기본 None=전건). attempt_event가 "
            "큰 prod에서 스캔 비용을 줄이되, 제한 시 그 범위만 판정함을 stdout에 명시한다."
        ),
    )
    parser.add_argument(
        "--skill-coverage",
        dest="skill_coverage",
        action="store_true",
        help=(
            "문제 → 개념 → 스킬 해소 커버리지를 함께 출력(계획서 200 §27 검사 ①). "
            "**exit code에 영향을 주지 않는다** — 지표이지 위반이 아니다(SkillCoverage docstring). "
            "차단 kind 승격은 prod 기준선 실측 후 사람이 정한다."
        ),
    )
    args = parser.parse_args(argv)

    async def _run() -> IntegrityReport:
        fn = (
            scan_fn
            if scan_fn is not None
            else (lambda: _default_scan_fn(event_since_days=args.event_since_days))
        )
        try:
            return await fn()
        finally:
            if scan_fn is None:
                await dispose_engine()

    report = asyncio.run(_run())

    if args.event_since_days is not None:
        print(f"※ EVENT_SCHEMA_INVALID 스캔 범위: 최근 {args.event_since_days}일만(전건 아님).")
    print(_render_stdout(report))
    if args.skill_coverage:
        print(_render_skill_coverage(asyncio.run(_run_skill_coverage(scan_fn))))
    if args.json_path is not None:
        _write_json(report, args.json_path)
        print(f"JSON 리포트 저장: {args.json_path}")

    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
