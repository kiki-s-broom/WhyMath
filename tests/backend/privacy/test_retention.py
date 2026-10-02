"""학습 활동 PII 시계열 보존 파기(`privacy/retention.py`) — 단위(hermetic·FakeSession).

`retention_cutoff`(순수·윤년) + `purge_expired_records`(타임스탬프 < cutoff 삭제·테이블별 행수·
child→parent 순서·계정/인증 테이블 제외)를 DB 없이 검증한다. 실 PG FK/CASCADE 거동은 통합
테스트 영역(여긴 *어떤 테이블을 어떤 순서로 어떤 cutoff로* 지우는지 배선만).
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.activity import ProblemAttempt
from whymath_backend.privacy.retention import (
    _PURGED_ELSEWHERE,
    _RETENTION_PLAN,
    _RETENTION_PLAN_EXEMPTIONS,
    _effective_timestamp,
    purge_expired_records,
    retention_cutoff,
)

# 타임스탬프 창 파기 계획 *밖*이어야 하는 소유 테이블 — **항목별 사유가 붙은** 목록(SEC-41 ③).
# 종전 판은 사유 없이 이름 9개만 나열한 집합이라 "왜 안 지우는가"가 코드 어디에도 없었다(무사유
# 제외 금지). 사유의 정본은 `privacy/retention.py`의 `_RETENTION_PLAN_EXEMPTIONS`(의도적 제외)와
# `_PURGED_ELSEWHERE`(다른 경로가 파기 — evidence_links)다. 같은 사유를 여기 또 적으면 두 곳이
# 어긋나므로 정본을 그대로 쓴다 — 사유가 비면 아래 `test_excluded_tables_all_carry_a_reason`이 RED.
_EXCLUDED_TABLES: dict[str, str] = {**_RETENTION_PLAN_EXEMPTIONS, **_PURGED_ELSEWHERE}


class _FakeResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class _FakeSession:
    """delete 실행 순서·테이블명·WHERE절 텍스트를 캡처(rowcount 고정 반환)."""

    def __init__(self, rowcount: int = 2) -> None:
        self.deletes: list[str] = []
        self.wheres: list[str] = []
        self.rowcount = rowcount

    async def execute(self, stmt: Any) -> _FakeResult:
        self.deletes.append(stmt.table.name)
        self.wheres.append(str(stmt.whereclause))
        return _FakeResult(self.rowcount)


class TestRetentionCutoff:
    def test_subtracts_years(self) -> None:
        assert retention_cutoff(date(2026, 6, 18), years=3) == date(2023, 6, 18)
        assert retention_cutoff(date(2026, 6, 18), years=1) == date(2025, 6, 18)

    def test_leap_day_clamps_to_feb_28(self) -> None:
        # 2028-02-29 − 3년 = 2025(비윤년) → 2/28 클램프(ValueError 회피).
        assert retention_cutoff(date(2028, 2, 29), years=3) == date(2025, 2, 28)


class TestPurgeExpiredRecords:
    def test_deletes_all_plan_tables_child_first(self) -> None:
        """플랜 전 테이블을 child→parent 순서로 삭제·테이블별 행수 반환."""
        session = _FakeSession(rowcount=2)
        counts = asyncio.run(
            purge_expired_records(cast(AsyncSession, session), as_of=date(2026, 6, 18), years=3)
        )
        planned = [m.__tablename__ for m, _ in _RETENTION_PLAN]
        assert session.deletes == planned  # 순서 보존(child→parent)
        assert set(counts) == set(planned)
        assert all(c == 2 for c in counts.values())
        # learning_session보다 problem_attempt가 먼저(session→attempt CASCADE 역순 방지).
        assert session.deletes.index("problem_attempt") < session.deletes.index("learning_session")

    def test_excludes_account_and_evidence_tables(self) -> None:
        """계정/인증/동의/가설·evidence_links는 *파기 대상 아님*(보존 의미 상이·중복 0)."""
        planned = {m.__tablename__ for m, _ in _RETENTION_PLAN}
        overlap = planned & set(_EXCLUDED_TABLES)
        assert overlap == set(), (
            f"계획과 제외 목록에 모두 있는 테이블: {sorted(overlap)} — 계획에 편입했으면 제외 항목을 "
            "걷어라(중복 등재는 어느 쪽이 사실인지 흐린다)."
        )

    def test_excluded_tables_all_carry_a_reason(self) -> None:
        """SEC-41 ③ — 제외 목록의 모든 항목에 사유가 있다(무사유 제외 금지). 공백뿐인 사유도 거부."""
        assert _EXCLUDED_TABLES, "제외 목록이 비었다 — 감사 테이블 등 최소 항목이 있어야 한다."
        for table, reason in _EXCLUDED_TABLES.items():
            assert reason.strip(), f"{table}의 제외 사유가 비어 있다(무사유 제외 금지)."
            assert (
                len(reason.strip()) >= 20
            ), f"{table}의 제외 사유가 지나치게 짧다(형식적 사유 의심)."

    def test_zero_rowcount_reported(self) -> None:
        """만료분 0건 → 테이블별 0(에러 아님·정상)."""
        session = _FakeSession(rowcount=0)
        counts = asyncio.run(
            purge_expired_records(cast(AsyncSession, session), as_of=date(2026, 6, 18), years=3)
        )
        assert sum(counts.values()) == 0
        assert len(counts) == len(_RETENTION_PLAN)

    def test_problem_attempt_where_clause_coalesces_ingested_at(self) -> None:
        """SEC-33 ② — 실행 시 problem_attempt DELETE의 WHERE절이 실제로 COALESCE를 쓴다.

        `_effective_timestamp` 단위 테스트(아래)는 그 함수 자체를 보지만, 이 테스트는
        `purge_expired_records`가 그 함수를 *실제로 호출해 반영하는지*를 본다(배선 증명 —
        함수만 옳고 호출부가 옛 `getattr` 그대로면 이 테스트만 잡는다).
        """
        session = _FakeSession(rowcount=2)
        asyncio.run(
            purge_expired_records(cast(AsyncSession, session), as_of=date(2026, 6, 18), years=3)
        )
        idx = session.deletes.index("problem_attempt")
        where = session.wheres[idx].lower()
        assert "coalesce" in where
        assert "started_at" in where
        assert "ingested_at" in where

    def test_other_tables_where_clauses_do_not_use_coalesce(self) -> None:
        """회귀 가드 — COALESCE 폴백은 SEC-33이 지정한 problem_attempt 하나뿐이다."""
        session = _FakeSession(rowcount=2)
        asyncio.run(
            purge_expired_records(cast(AsyncSession, session), as_of=date(2026, 6, 18), years=3)
        )
        for table, where in zip(session.deletes, session.wheres, strict=True):
            if table == "problem_attempt":
                continue
            assert "coalesce" not in where.lower(), f"{table}이 예기치 않게 COALESCE를 쓴다"


class TestEffectiveTimestamp:
    """`_effective_timestamp` — SEC-33 ② COALESCE 폴백의 단위 계약."""

    def test_problem_attempt_started_at_becomes_coalesce_with_ingested_at(self) -> None:
        expr = _effective_timestamp(ProblemAttempt, "started_at")
        compiled = str(expr).lower()
        assert "coalesce" in compiled
        assert "started_at" in compiled
        assert "ingested_at" in compiled

    def test_all_non_problem_attempt_plan_entries_are_unwrapped(self) -> None:
        """회귀 가드 — `ProblemAttempt` 외 모든 플랜 항목은 원 컬럼 그대로(COALESCE 미개입)."""
        for model, column in _RETENTION_PLAN:
            if model is ProblemAttempt:
                continue
            expr = _effective_timestamp(model, column)
            assert "coalesce" not in str(expr).lower()
            assert expr is getattr(model, column)
