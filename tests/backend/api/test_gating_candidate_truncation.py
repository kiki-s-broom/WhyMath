"""`api/gating._fetch_candidates`의 절단 관측 로그 단위테스트(PB-03 축③, hermetic).

`_CANDIDATE_FETCH_LIMIT`(3000)만큼 코퍼스가 커지려면 실 DB가 필요하므로, 이 테스트는 상수를
monkeypatch로 작게 낮추고 `_fetch_candidates`를 직접 호출한다(라우터 경유 없이 함수 단위) —
가짜 세션이 fetch 호출과 count 호출을 순서로 구분해 응답한다. 변별력 확인: 상한 미만 행에서는
로그가 찍히지 않고, 상한과 정확히 같은 행에서는 정확한 truncated 건수와 함께 찍힌다(로그 코드가
있어도 실제로 발화하는지 확인 없이 "구현됨"으로 치지 않는다 — CLAUDE.md 변별력 규칙).
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql

from whymath_backend.api import gating as gating_module
from whymath_backend.db.models.problem import Problem
from whymath_backend.schema.enums import (
    Curriculum,
    ReviewStatus,
    SourceType,
    Subject,
    is_review_status_cleared,
)
from whymath_backend.schema.problem import Problem as ProblemSchema


def _problem(slug: str) -> Problem:
    return Problem.from_schema(  # type: ignore[arg-type]
        ProblemSchema(
            slug=slug,
            source_type=SourceType.자체생성,
            review_status=ReviewStatus.approved,
            curriculum_version=Curriculum.REVISION_2022,
            valid_from_year=2022,
            subject=Subject.미적분,
            unit_codes=["CAL-INT-DEF"],
        )
    )


class _FakeScalars:
    def __init__(self, rows: list[Problem]) -> None:
        self._rows = rows

    def all(self) -> list[Problem]:
        return list(self._rows)


class _FakeCandidateResult:
    def __init__(self, rows: list[Problem]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._rows)


class _FakeCountResult:
    def __init__(self, total: int) -> None:
        self._total = total

    def scalar_one(self) -> int:
        return self._total


class _OrderedFakeSession:
    """1번째 execute()=후보 fetch, 2번째(있으면)=count(*) — 호출 순서로만 구분(hermetic)."""

    def __init__(self, rows: list[Problem], total: int) -> None:
        self._rows = rows
        self._total = total
        self.execute_calls = 0
        # PB-27 — 실행된 SQL 문을 남겨 검수 축 사전 축소 조건을 컴파일해 검사한다.
        self.statements: list[Any] = []

    async def execute(self, stmt: Any) -> _FakeCandidateResult | _FakeCountResult:
        self.execute_calls += 1
        self.statements.append(stmt)
        if self.execute_calls == 1:
            return _FakeCandidateResult(self._rows)
        return _FakeCountResult(self._total)


@pytest.mark.asyncio
async def test_no_truncation_below_limit_no_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """fetch 건수가 상한 미만이면 count(*) 재조회도, 경고 로그도 없다."""
    monkeypatch.setattr(gating_module, "_CANDIDATE_FETCH_LIMIT", 5)
    session = _OrderedFakeSession(rows=[_problem(f"p{i}") for i in range(3)], total=3)
    with caplog.at_level(logging.WARNING, logger="whymath_backend.api.gating"):
        result = await gating_module._fetch_candidates(session)  # type: ignore[arg-type]
    assert len(result) == 3
    assert session.execute_calls == 1  # count(*) 재조회 자체가 없어야 함
    assert not any("truncated" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_truncation_at_limit_logs_exact_count(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """fetch 건수가 상한과 정확히 같으면 count(*) 재조회 후 정확한 truncated 건수로 경고."""
    monkeypatch.setattr(gating_module, "_CANDIDATE_FETCH_LIMIT", 3)
    session = _OrderedFakeSession(rows=[_problem(f"p{i}") for i in range(3)], total=10)
    with caplog.at_level(logging.WARNING, logger="whymath_backend.api.gating"):
        result = await gating_module._fetch_candidates(session)  # type: ignore[arg-type]
    assert len(result) == 3
    assert session.execute_calls == 2  # count(*) 재조회가 실제로 일어남
    warnings = [rec.message for rec in caplog.records if "truncated" in rec.message]
    assert len(warnings) == 1
    assert "fetched=3" in warnings[0]
    assert "total=10" in warnings[0]
    assert "truncated=7" in warnings[0]


# ──────────────────────────────────────────────────────────────────────────
# PB-27 — 검수 축 사전 축소(Kiki 결정 ⓒ). 가짜 세션은 SQL을 무시하므로, 여기서는 *실행된 SQL 문*을
# PostgreSQL 방언으로 컴파일해 조건을 직접 본다. 조건이 실제로 행을 거르는지는 실 PG 통합 테스트
# (`test_gating_candidates_integration.py`)가 맡는다.
# ──────────────────────────────────────────────────────────────────────────


def _sql(stmt: Any) -> str:
    """SQL 문을 PostgreSQL 방언·리터럴 바인딩으로 컴파일한 문자열."""
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def _cleared_values() -> list[str]:
    """판정 권위가 통과시키는 검수 상태 값(테스트가 독립적으로 계산)."""
    return [status.value for status in ReviewStatus if is_review_status_cleared(status)]


@pytest.mark.asyncio
async def test_candidate_sql_keeps_only_review_cleared_statuses() -> None:
    """후보 SQL은 권위가 통과시키는 검수 상태만 고르고, 나머지 상태 값은 조건에 없다."""
    session = _OrderedFakeSession(rows=[_problem("p0")], total=1)
    await gating_module._fetch_candidates(session)  # type: ignore[arg-type]
    sql = _sql(session.statements[0])
    cleared = _cleared_values()
    assert cleared, "권위가 통과시키는 검수 상태가 0개 — 테스트 전제가 깨졌다"
    assert "review_status IN" in sql
    for value in cleared:
        assert f"'{value}'" in sql
    for status in ReviewStatus:
        if status.value not in cleared:
            assert (
                f"'{status.value}'" not in sql
            ), f"통과하지 않는 상태 {status.value}가 조건에 있다"
    # 권위가 미평가(None)를 통과시키지 않는 한 NULL 행은 후보가 아니다.
    assert "IS NULL" not in sql


@pytest.mark.asyncio
async def test_candidate_sql_follows_the_review_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    """조건은 권위에서 *호출 시점에* 유도된다 — 권위가 넓어지면 SQL도 넓어진다(하드코딩 금지).

    권위가 pending과 미평가(None)까지 통과시키도록 바꾸면 SQL에 pending과 `IS NULL`이 함께
    나타나야 한다. `== approved`를 SQL에 다시 적는 구현은 여기서 실패한다.
    """
    widened = {ReviewStatus.approved, ReviewStatus.pending, None}

    def _wide(value: object) -> bool:
        return value in widened

    monkeypatch.setattr(gating_module, "is_review_status_cleared", _wide)
    session = _OrderedFakeSession(rows=[_problem("p0")], total=1)
    await gating_module._fetch_candidates(session)  # type: ignore[arg-type]
    sql = _sql(session.statements[0])
    assert "'approved'" in sql
    assert "'pending'" in sql
    assert "review_status IS NULL" in sql


@pytest.mark.asyncio
async def test_truncation_count_uses_the_same_review_condition(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """절단 경고의 total은 *후보가 될 수 있었던* 행 수 — count(*)도 같은 검수 조건을 쓴다.

    조건 없는 count(*)는 비승인 행까지 세어 절단 규모를 부풀린다(PB-25 실측의 truncated=11742처럼).
    """
    monkeypatch.setattr(gating_module, "_CANDIDATE_FETCH_LIMIT", 2)
    session = _OrderedFakeSession(rows=[_problem("p0"), _problem("p1")], total=5)
    with caplog.at_level(logging.WARNING, logger="whymath_backend.api.gating"):
        await gating_module._fetch_candidates(session)  # type: ignore[arg-type]
    assert session.execute_calls == 2
    fetch_sql, count_sql = (_sql(stmt) for stmt in session.statements)
    assert "count(*)" in count_sql
    where = fetch_sql.split("WHERE", 1)[1].split("ORDER BY", 1)[0].strip()
    assert where, "후보 SQL에 WHERE가 없다"
    assert where in count_sql, "count(*)의 조건이 후보 SQL의 조건과 다르다"
