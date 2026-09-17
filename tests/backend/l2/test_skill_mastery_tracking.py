"""L2 BKT↔SkillMasteryHistory 결선 — 스킬 축 단위테스트 (hermetic·Part 2 Phase 2b-2).

순수 커널(`compute_mastery_record`)은 `mastery_tracking`(개념 축)과 *동일 재사용*이라 여기선
스킬 축 고유 로직만 본다: ① `get_current_skill_mastery` 읽기 ② `_assessed_skill_ids` 해소
③ `record_problem_attempt_skill_mastery`의 모델 B 전파(정답=전체 개념 스킬·오답=PRIMARY 스킬·
TESTED 폴백). 실 PG 조인(concept→skill·mastery_estimable 게이트)은 통합테스트가 검증.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.assessment import SkillMasteryHistory
from whymath_backend.l2 import BktModel
from whymath_backend.l2.skill_mastery_tracking import (
    _latest_skill_mastery,
    get_all_current_skill_mastery,
    get_current_skill_mastery,
    record_problem_attempt_skill_mastery,
)

_M = BktModel()
_UID = uuid.uuid4()
_SID = "skill.compute-fraction"


class _FakeResult:
    def __init__(self, row: Any) -> None:
        self._row = row

    def scalars(self) -> _FakeResult:
        return self

    def first(self) -> Any:
        return self._row


class _FakeSession:
    """`_latest_skill_mastery` 단건 SELECT·add·commit 시뮬(stmt 무시)."""

    def __init__(self, prior: SkillMasteryHistory | None = None) -> None:
        self._prior = prior
        self.added: list[Any] = []
        self.commits = 0

    async def execute(self, _stmt: Any) -> _FakeResult:
        return _FakeResult(self._prior)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1


class _QResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _QResult:
        return self

    def all(self) -> list[Any]:
        return self._rows

    def first(self) -> Any:
        return self._rows[0] if self._rows else None


class _QueueSession:
    """execute 호출마다 미리 큐잉한 결과를 순서대로 반환 — 다중 쿼리(개념 → 스킬 → 스킬별 prior)."""

    def __init__(self, results: list[_QResult]) -> None:
        self._results = results
        self._i = 0
        self.added: list[Any] = []
        self.commits = 0

    async def execute(self, _stmt: Any) -> _QResult:
        result = self._results[self._i]
        self._i += 1
        return result

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1


def _prior_row(mastery: float | None, sample_size: int | None) -> SkillMasteryHistory:
    return SkillMasteryHistory(
        user_id=_UID,
        skill_id=_SID,
        measured_at=datetime(2026, 1, 1, tzinfo=UTC),
        mastery=mastery,
        confidence=None,
        sample_size=sample_size,
    )


class TestGetCurrentSkillMastery:
    """(user, skill) 현재 숙달도 — 최신 측정 mastery·없거나 NULL이면 None."""

    async def test_returns_latest_mastery(self) -> None:
        fake = _FakeSession(prior=_prior_row(0.75, 5))
        assert await get_current_skill_mastery(cast(AsyncSession, fake), _UID, _SID) == 0.75

    async def test_returns_none_when_no_history(self) -> None:
        fake = _FakeSession(prior=None)
        assert await get_current_skill_mastery(cast(AsyncSession, fake), _UID, _SID) is None

    async def test_returns_none_when_mastery_null(self) -> None:
        fake = _FakeSession(prior=_prior_row(None, None))
        assert await get_current_skill_mastery(cast(AsyncSession, fake), _UID, _SID) is None


class TestRecordProblemAttemptSkillMastery:
    """채점 풀이 → concept→skill 해소 → 스킬별 전파(모델 B·순수 커널 재사용)."""

    async def test_correct_propagates_to_all_resolved_skills(self) -> None:
        """정답: 평가 개념 전체 → 해소된 스킬 전부 지지(합동 증거·첫 관측 상승)."""
        c1, c2 = uuid.uuid4(), uuid.uuid4()
        s1, s2 = "skill.a", "skill.b"
        ts = datetime(2026, 3, 1, tzinfo=UTC)
        # execute: #1 개념[c1,c2] → #2 스킬[s1,s2] → #3 s1 prior[] → #4 s2 prior[]
        fake = _QueueSession([_QResult([c1, c2]), _QResult([s1, s2]), _QResult([]), _QResult([])])
        records = await record_problem_attempt_skill_mastery(
            cast(AsyncSession, fake), _UID, uuid.uuid4(), True, model=_M, measured_at=ts
        )
        assert [r.skill_id for r in records] == [s1, s2]
        assert all(float(r.mastery) == 0.69 for r in records)  # 정답·첫 관측
        assert all(r.measured_at == ts for r in records)  # 한 풀이=같은 시각
        assert len(fake.added) == 2
        assert fake.commits == 1  # 다스킬 = 단일 트랜잭션(원자성)

    async def test_incorrect_blames_primary_skills_only(self) -> None:
        """오답: PRIMARY 개념 스킬만 감점(PRIMARY 존재 시 TESTED 폴백 미발생·거짓 약점 0)."""
        c_p = uuid.uuid4()
        s1 = "skill.a"
        # execute: #1 PRIMARY[c_p] → #2 스킬[s1] → #3 s1 prior[]
        fake = _QueueSession([_QResult([c_p]), _QResult([s1]), _QResult([])])
        records = await record_problem_attempt_skill_mastery(
            cast(AsyncSession, fake), _UID, uuid.uuid4(), False, model=_M
        )
        assert [r.skill_id for r in records] == [s1]
        assert records[0].mastery == 0.15  # 오답·첫 관측
        assert fake.commits == 1

    async def test_incorrect_falls_back_to_tested_when_no_primary(self) -> None:
        """오답·PRIMARY 미매핑 퇴화 문항은 TESTED 개념 스킬로 폴백(신호 손실 방지)."""
        c_t = uuid.uuid4()
        s1 = "skill.a"
        # execute: #1 PRIMARY[] → #2 TESTED[c_t] → #3 스킬[s1] → #4 s1 prior[]
        fake = _QueueSession([_QResult([]), _QResult([c_t]), _QResult([s1]), _QResult([])])
        records = await record_problem_attempt_skill_mastery(
            cast(AsyncSession, fake), _UID, uuid.uuid4(), False, model=_M
        )
        assert [r.skill_id for r in records] == [s1]
        assert fake.commits == 1

    async def test_no_mapped_concepts_returns_empty(self) -> None:
        """문제↔개념 매핑이 없으면 스킬 해소·갱신 0(_assessed_skill_ids 조기반환·쿼리 0)."""
        # execute: #1 개념[] — 이후 _assessed_skill_ids는 빈 입력이라 쿼리 없음.
        fake = _QueueSession([_QResult([])])
        records = await record_problem_attempt_skill_mastery(
            cast(AsyncSession, fake), _UID, uuid.uuid4(), True
        )
        assert records == []
        assert fake.added == []
        assert fake.commits == 0

    async def test_concepts_but_no_estimable_skills_returns_empty(self) -> None:
        """개념은 있으나 mastery-estimable 스킬 해소가 0이면 갱신 0(빈 리스트·커밋 0)."""
        c1 = uuid.uuid4()
        # execute: #1 개념[c1] → #2 스킬[] (해소 0)
        fake = _QueueSession([_QResult([c1]), _QResult([])])
        records = await record_problem_attempt_skill_mastery(
            cast(AsyncSession, fake), _UID, uuid.uuid4(), True
        )
        assert records == []
        assert fake.added == []
        assert fake.commits == 0

    async def test_reads_prior_and_updates(self) -> None:
        """스킬 직전 측정(0.69·표본1)을 prior로 → 0.92·표본 2(순수 커널 재사용·개념 축과 동일)."""
        c1 = uuid.uuid4()
        s1 = "skill.a"
        fake = _QueueSession([_QResult([c1]), _QResult([s1]), _QResult([_prior_row(0.69, 1)])])
        records = await record_problem_attempt_skill_mastery(
            cast(AsyncSession, fake), _UID, uuid.uuid4(), True, model=_M
        )
        assert records[0].mastery == 0.92
        assert records[0].sample_size == 2


# ──────────────────────────────────────────────────────────────────────────
# EOS-10 — 벌크 좌석 `get_all_current_skill_mastery` (조립기가 쓰는 "스킬별 최신 전건")
# ──────────────────────────────────────────────────────────────────────────
class _CaptureSession:
    """`execute()`에 들어온 statement를 붙잡아 두는 세션 — SQL 형태 대조용."""

    def __init__(self, rows: list[Any] | None = None) -> None:
        self.stmt: Any = None
        self._rows = rows or []

    async def execute(self, stmt: Any) -> _QResult:
        self.stmt = stmt
        return _QResult(self._rows)


def _order_by_sql(stmt: Any) -> str:
    """statement의 ORDER BY 절만 문자열로 — 두 좌석의 '최신' 정의를 대조하는 축."""
    return " ".join(str(clause) for clause in stmt._order_by_clauses)


def _compiled_sql(stmt: Any) -> str:
    """Postgres 방언으로 컴파일한 SQL 전문 — `DISTINCT ON` 같은 *방언 절*을 보는 축.

    `_order_by_sql`은 ORDER BY만 보므로 DISTINCT 절을 지워도 값이 그대로다(초판 뮤테이션
    M11이 정확히 그 틈으로 생존했다 — 가드가 관대한 게 아니라 그 절을 밟는 픽스처가 없었다).
    """
    return str(stmt.compile(dialect=postgresql.dialect()))


class TestGetAllCurrentSkillMastery:
    """벌크 좌석 — `{skill_id: mastery}`. 단건 좌석과 **같은 '최신' 규칙**이어야 한다."""

    async def test_maps_skill_id_to_latest_mastery(self) -> None:
        fake = _CaptureSession([("skill.a", 0.5), ("skill.b", 0.9)])
        got = await get_all_current_skill_mastery(cast(AsyncSession, fake), _UID)
        assert got == {"skill.a": 0.5, "skill.b": 0.9}

    async def test_null_mastery_rows_produce_no_key(self) -> None:
        """NULL은 '숙달 0'이 아니라 '측정 없음' — 키 자체가 없어야 한다(단건 좌석의 None과 동형)."""
        fake = _CaptureSession([("skill.a", None), ("skill.b", 0.4)])
        got = await get_all_current_skill_mastery(cast(AsyncSession, fake), _UID)
        assert got == {"skill.b": 0.4}
        assert "skill.a" not in got

    async def test_empty_history_yields_empty_dict(self) -> None:
        fake = _CaptureSession([])
        assert await get_all_current_skill_mastery(cast(AsyncSession, fake), _UID) == {}

    async def test_latest_rule_matches_single_seat(self) -> None:
        """두 좌석이 같은 (user, skill)에 대해 **다른 행**을 고르면 그 자체가 결함이다.

        벌크는 `DISTINCT ON (skill_id)`, 단건은 `LIMIT 1`이라 형태가 다르지만 "무엇이 최신인가"의
        정의(`measured_at` 내림차순)는 반드시 같아야 한다. 한쪽만 asc로 바뀌면 조립기가 내는
        스킬 숙달과 `/skill-mastery` 단건 조회가 조용히 어긋난다 — 이 테스트가 그것을 잡는다.
        """
        bulk_session = _CaptureSession([])
        await get_all_current_skill_mastery(cast(AsyncSession, bulk_session), _UID)
        single_session = _CaptureSession([])
        await _latest_skill_mastery(cast(AsyncSession, single_session), _UID, _SID)

        bulk_order = _order_by_sql(bulk_session.stmt)
        single_order = _order_by_sql(single_session.stmt)
        assert "measured_at DESC" in bulk_order, f"벌크 좌석의 최신 정의가 아니다: {bulk_order}"
        assert "measured_at DESC" in single_order, f"단건 좌석의 최신 정의가 아니다: {single_order}"
        # DISTINCT ON은 ORDER BY가 그 키로 시작해야 최신 행 선택이 성립한다(Postgres 제약).
        assert bulk_order.split()[0].endswith(
            "skill_id"
        ), f"DISTINCT ON (skill_id)인데 ORDER BY가 skill_id로 시작하지 않는다: {bulk_order}"

    async def test_bulk_seat_selects_one_row_per_skill(self) -> None:
        """`DISTINCT ON (skill_id)` 절 자체를 밟는 반례 — 이 절이 없으면 시계열 전건이 나온다.

        ORDER BY만 검사하는 위 테스트는 이 절을 지워도 통과한다(실측: 뮤테이션 M11 생존).
        "스킬별 **최신 1건**"이라는 계약은 ORDER BY가 아니라 이 절이 만들므로, 절을 직접 본다 —
        빠지면 조립기의 `skill_mastery`가 한 스킬의 옛 측정값에 덮어써질 수 있다(dict 마지막
        승자가 최신이라는 보장이 사라진다).
        """
        fake = _CaptureSession([])
        await get_all_current_skill_mastery(cast(AsyncSession, fake), _UID)
        sql = _compiled_sql(fake.stmt)
        assert "DISTINCT ON" in sql.upper(), (
            "벌크 좌석에 DISTINCT ON이 없다 — 스킬별 최신 1건이 아니라 측정 시계열 전건이 나온다:\n"
            f"{sql}"
        )
        assert (
            "skill_id" in sql.split("DISTINCT ON", 1)[1].split(")", 1)[0]
        ), f"DISTINCT ON의 키가 skill_id가 아니다:\n{sql}"
