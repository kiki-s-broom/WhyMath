"""데이터 무결성 게이트(`ops/integrity_violations_gate.py`, OPS-55) — 실 PostgreSQL 통합테스트.

`WHYMATH_RUN_INTEGRATION=1` + 살아있는 PG(마이그레이션 head 적용)에서만 실행한다(conftest
게이트가 CI 기본 skip). PG 미도달 시에도 graceful skip(`test_concepts_integration.py`·
`test_role_grant_cli_integration.py` 패턴 미러).

OPS-55 acceptance ②(위반 주입 변별력 실측 — 성공/실패 양쪽 신호)를 6종 전부에 대해 3단
왕복으로 증명한다: ①삽입 전 — 대상 식별자가 위반 목록에 없다(오탐 아님) ②삽입 후 — 있다
(검출) ③cleanup 후 — 다시 없다(오탐류 잔존 없음). 동일 프로세스에서 다른 통합테스트가 같은
DB에 데이터를 남길 수 있으므로 `report.exit_code`(전역 판정)가 아니라 이 테스트가 심은
식별자 하나하나의 존재/부재로 단언한다(격리·재현성).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from whymath_backend.config import Settings
from whymath_backend.ops import integrity_violations_gate as gate

pytestmark = pytest.mark.integration

# 격리 접두사 — 병렬/반복 실행 간 충돌 방지(role_grant_cli_integration.py uuid 선례 미러).
_RUN_TAG = uuid.uuid4().hex[:8]


async def _pg_reachable() -> bool:
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    if not await _pg_reachable():
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀 (WHYMATH_DATABASE_URL 확인)")
    engine = create_async_engine(Settings().database_url)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        yield session
    await engine.dispose()


async def _kind_identifiers(session: AsyncSession, kind: str) -> set[str]:
    report = await gate.scan_integrity(session)
    return {v.identifier for v in report.violations_by_kind(kind)}


class TestOrphanConceptDiscrimination:
    async def test_concept_node_without_matching_concept_is_detected(
        self, db_session: AsyncSession
    ) -> None:
        concept_id = f"math.test.{_RUN_TAG}.orphan-concept"
        assert concept_id not in await _kind_identifiers(db_session, gate.KIND_ORPHAN_CONCEPT)
        try:
            await db_session.execute(
                text(
                    "INSERT INTO concept_node (concept_id, name_ko, domain, review_status) "
                    "VALUES (:cid, '테스트', '[중]테스트', 'pending')"
                ),
                {"cid": concept_id},
            )
            await db_session.commit()
            assert concept_id in await _kind_identifiers(db_session, gate.KIND_ORPHAN_CONCEPT)
        finally:
            await db_session.execute(
                text("DELETE FROM concept_node WHERE concept_id = :cid"), {"cid": concept_id}
            )
            await db_session.commit()
        assert concept_id not in await _kind_identifiers(db_session, gate.KIND_ORPHAN_CONCEPT)


class TestOrphanSkillDiscrimination:
    async def test_behavior_skills_reference_to_missing_skill_is_detected(
        self, db_session: AsyncSession
    ) -> None:
        skill_id = f"skill.{_RUN_TAG}-orphan"
        concept_pk = uuid.uuid4()
        code = f"math.test.{_RUN_TAG}.skill-holder"
        assert skill_id not in await _kind_identifiers(db_session, gate.KIND_ORPHAN_SKILL)
        try:
            await db_session.execute(
                text(
                    "INSERT INTO concept (concept_id, code, name_ko, level, behavior_skills) "
                    "VALUES (:pk, :code, '테스트', '세부개념', ARRAY[:sid])"
                ),
                {"pk": concept_pk, "code": code, "sid": skill_id},
            )
            await db_session.commit()
            assert skill_id in await _kind_identifiers(db_session, gate.KIND_ORPHAN_SKILL)
        finally:
            await db_session.execute(
                text("DELETE FROM concept WHERE concept_id = :pk"), {"pk": concept_pk}
            )
            await db_session.commit()
        assert skill_id not in await _kind_identifiers(db_session, gate.KIND_ORPHAN_SKILL)


class TestOrphanProblemDiscrimination:
    async def test_dead_end_log_reference_to_missing_problem_is_detected(
        self, db_session: AsyncSession
    ) -> None:
        problem_id = uuid.uuid4()
        identifier = str(problem_id)
        assert identifier not in await _kind_identifiers(db_session, gate.KIND_ORPHAN_PROBLEM)
        try:
            await db_session.execute(
                text(
                    "INSERT INTO dead_end_log (problem_id, state_hash, action) "
                    "VALUES (:pid, :hash, 'test')"
                ),
                {"pid": problem_id, "hash": f"hash-{_RUN_TAG}"},
            )
            await db_session.commit()
            assert identifier in await _kind_identifiers(db_session, gate.KIND_ORPHAN_PROBLEM)
        finally:
            await db_session.execute(
                text("DELETE FROM dead_end_log WHERE problem_id = :pid"), {"pid": problem_id}
            )
            await db_session.commit()
        assert identifier not in await _kind_identifiers(db_session, gate.KIND_ORPHAN_PROBLEM)


class TestDanglingCurriculumRefDiscrimination:
    async def test_skill_node_standard_code_not_in_achievement_standard_is_detected(
        self, db_session: AsyncSession
    ) -> None:
        code = f"9XX{_RUN_TAG}"
        skill_id = f"skill.{_RUN_TAG}-dangling-curriculum"
        assert code not in await _kind_identifiers(db_session, gate.KIND_DANGLING_CURRICULUM_REF)
        try:
            await db_session.execute(
                text(
                    "INSERT INTO skill_node "
                    "(skill_id, name_ko, behavior_area, family, review_status, standard_codes) "
                    "VALUES (:sid, '테스트', 'COMPUTE', 'test-family', 'ai_estimated', "
                    "ARRAY[:code])"
                ),
                {"sid": skill_id, "code": code},
            )
            await db_session.commit()
            assert code in await _kind_identifiers(db_session, gate.KIND_DANGLING_CURRICULUM_REF)
        finally:
            await db_session.execute(
                text("DELETE FROM skill_node WHERE skill_id = :sid"), {"sid": skill_id}
            )
            await db_session.commit()
        assert code not in await _kind_identifiers(db_session, gate.KIND_DANGLING_CURRICULUM_REF)


class TestDuplicateCanonicalIdDiscrimination:
    async def test_code_claimed_as_alias_by_another_concept_is_detected(
        self, db_session: AsyncSession
    ) -> None:
        code_a = f"math.test.{_RUN_TAG}.canonical-a"
        code_b = f"math.test.{_RUN_TAG}.canonical-b"
        pk_a, pk_b = uuid.uuid4(), uuid.uuid4()
        assert code_a not in await _kind_identifiers(db_session, gate.KIND_DUPLICATE_CANONICAL_ID)
        try:
            await db_session.execute(
                text(
                    "INSERT INTO concept (concept_id, code, name_ko, level) "
                    "VALUES (:pk, :code, '테스트A', '세부개념')"
                ),
                {"pk": pk_a, "code": code_a},
            )
            await db_session.execute(
                text(
                    "INSERT INTO concept (concept_id, code, name_ko, level, aliases) "
                    "VALUES (:pk, :code, '테스트B', '세부개념', ARRAY[:alias])"
                ),
                {"pk": pk_b, "code": code_b, "alias": code_a},
            )
            await db_session.commit()
            assert code_a in await _kind_identifiers(db_session, gate.KIND_DUPLICATE_CANONICAL_ID)
        finally:
            await db_session.execute(
                text("DELETE FROM concept WHERE concept_id IN (:a, :b)"), {"a": pk_a, "b": pk_b}
            )
            await db_session.commit()
        assert code_a not in await _kind_identifiers(db_session, gate.KIND_DUPLICATE_CANONICAL_ID)


class TestEventSchemaInvalidDiscrimination:
    async def test_verify_event_missing_required_field_is_detected(
        self, db_session: AsyncSession
    ) -> None:
        result = await db_session.execute(
            text(
                "INSERT INTO attempt_event (event_at, event_type, event_data) "
                "VALUES (now(), '검산결과', :payload) RETURNING event_id"
            ),
            {"payload": '{"error_kind": "missing_passed_field"}'},
        )
        event_id = result.scalar_one()
        identifier = f"attempt_event#{event_id}"
        try:
            await db_session.commit()
            assert identifier in await _kind_identifiers(db_session, gate.KIND_EVENT_SCHEMA_INVALID)
        finally:
            await db_session.execute(
                text("DELETE FROM attempt_event WHERE event_id = :eid"), {"eid": event_id}
            )
            await db_session.commit()
        assert identifier not in await _kind_identifiers(db_session, gate.KIND_EVENT_SCHEMA_INVALID)

    async def test_verify_event_with_valid_payload_is_not_flagged(
        self, db_session: AsyncSession
    ) -> None:
        result = await db_session.execute(
            text(
                "INSERT INTO attempt_event (event_at, event_type, event_data) "
                "VALUES (now(), '검산결과', :payload) RETURNING event_id"
            ),
            {"payload": '{"passed": true}'},
        )
        event_id = result.scalar_one()
        identifier = f"attempt_event#{event_id}"
        try:
            await db_session.commit()
            assert identifier not in await _kind_identifiers(
                db_session, gate.KIND_EVENT_SCHEMA_INVALID
            )
        finally:
            await db_session.execute(
                text("DELETE FROM attempt_event WHERE event_id = :eid"), {"eid": event_id}
            )
            await db_session.commit()


class TestEventSinceDaysScoping:
    async def test_old_event_excluded_when_since_days_set(self, db_session: AsyncSession) -> None:
        """`--event-since-days` 스코핑이 실제로 범위를 좁힌다(절단 출력 무결성 — 선택 시
        정직하게 일부만 본다는 것 자체를 실측 확인, 전건 스캔이 기본이라는 계약과 대조)."""
        result = await db_session.execute(
            text(
                "INSERT INTO attempt_event (event_at, event_type, event_data) "
                "VALUES (now() - interval '90 days', '검산결과', :payload) "
                "RETURNING event_id"
            ),
            {"payload": '{"error_kind": "old_invalid_event"}'},
        )
        event_id = result.scalar_one()
        identifier = f"attempt_event#{event_id}"
        try:
            await db_session.commit()
            # 기본(전건) — 오래된 이벤트도 잡힌다.
            full_report = await gate.scan_integrity(db_session)
            assert identifier in {
                v.identifier for v in full_report.violations_by_kind(gate.KIND_EVENT_SCHEMA_INVALID)
            }
            # 30일 이내로 제한하면 90일 전 이벤트는 스코프 밖 — 검출되지 않는다.
            scoped_report = await gate.scan_integrity(db_session, event_since_days=30)
            assert identifier not in {
                v.identifier
                for v in scoped_report.violations_by_kind(gate.KIND_EVENT_SCHEMA_INVALID)
            }
        finally:
            await db_session.execute(
                text("DELETE FROM attempt_event WHERE event_id = :eid"), {"eid": event_id}
            )
            await db_session.commit()


class TestCleanDatabaseExitsZeroForGateScopedRows:
    async def test_no_gate_scoped_violations_on_untouched_fixture(
        self, db_session: AsyncSession
    ) -> None:
        """이 테스트 클래스가 심지 않은 임의 식별자는 당연히 어느 kind에도 없다(오탐 없음 —
        전역 exit_code는 병행 실행 중인 다른 통합테스트의 잔존 데이터 영향을 받을 수 있어
        여기서 단언하지 않는다 — 모듈 docstring 참조)."""
        sentinel = f"math.test.{_RUN_TAG}.never-inserted"
        report = await gate.scan_integrity(db_session)
        all_identifiers = {v.identifier for v in report.violations}
        assert sentinel not in all_identifiers


class TestPublishedVersionInvalidDiscrimination:
    """⑦ PUBLISHED_VERSION_INVALID — 계획서 200 §27 검사 ⑤ (EOS-07).

    행의 *존재*는 FK가 막으므로 여기서 세지 않는다. DB가 못 막는 두 축을 각각 주입한다:
      A. 발행 포인터가 **DRAFT** 버전을 가리킨다 → "발행됐다"가 미발행 본문을 가리킨다.
      B. 발행 포인터가 **다른 개념**의 버전을 가리킨다 → 귀속이 어긋난다.

    **대조군이 핵심이다**: A를 고친 직후(status만 PUBLISHED로) 미검출로 돌아오는지 본다.
    대조군이 없으면 "전부 위반으로 계상"하는 과잉 검출도 통과한다.

    실측 메모(2026-09-16): `concept_version.concept_id`에는 `concept`로의 FK가 있어 B의 대상
    개념이 **실재해야** 주입된다. 첫 시도는 그것을 모르고 가짜 코드를 넣어 주입이 조용히
    실패했고, 빈 테이블의 0건이 '미검출'로 보였다 — 그래서 아래는 주입 직후 *스캔 대상 수*가
    늘었는지도 함께 단언한다(주입 자체의 실재).
    """

    async def _scanned(self, session: AsyncSession) -> int:
        report = await gate.scan_integrity(session)
        return report.scanned.get(gate.KIND_PUBLISHED_VERSION_INVALID, 0)

    async def test_pointer_to_draft_and_to_another_concept_are_detected(
        self, db_session: AsyncSession
    ) -> None:
        code_a = f"it.pv.{_RUN_TAG}.a"
        code_b = f"it.pv.{_RUN_TAG}.b"
        cid_a, cid_b, ver = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        kind = gate.KIND_PUBLISHED_VERSION_INVALID

        assert code_a not in await _kind_identifiers(db_session, kind)
        scanned_before = await self._scanned(db_session)
        try:
            await db_session.execute(
                text(
                    "INSERT INTO concept (concept_id, code, name_ko, level, created_at) "
                    "VALUES (:a, :ca, '주입개념A', '세부개념', now()), "
                    "       (:b, :cb, '주입개념B', '세부개념', now())"
                ),
                {"a": cid_a, "ca": code_a, "b": cid_b, "cb": code_b},
            )
            await db_session.execute(
                text(
                    "INSERT INTO concept_version "
                    "  (version_id, concept_id, version_no, schema_version, status, payload, "
                    "   created_at) "
                    "VALUES (:v, :ca, 1, 'concept-schema@1', 'DRAFT', '{}'::jsonb, now())"
                ),
                {"v": ver, "ca": code_a},
            )
            await db_session.execute(
                text("UPDATE concept SET current_published_version_id = :v WHERE concept_id = :a"),
                {"v": ver, "a": cid_a},
            )
            await db_session.commit()

            # 주입 자체의 실재 — 스캔 대상이 늘지 않았으면 아래 판정은 전부 무의미하다.
            assert await self._scanned(db_session) == scanned_before + 1

            # A. DRAFT를 가리킴 → 검출
            assert code_a in await _kind_identifiers(db_session, kind)

            # 대조군 — status만 고치면 미검출로 돌아와야 한다(과잉 검출 배제)
            await db_session.execute(
                text("UPDATE concept_version SET status = 'PUBLISHED' WHERE version_id = :v"),
                {"v": ver},
            )
            await db_session.commit()
            assert code_a not in await _kind_identifiers(
                db_session, kind
            ), "발행 포인터가 올바른 PUBLISHED 버전을 가리키는데도 위반으로 계상됐다 — 과잉 검출"

            # B. 남의 개념 버전을 가리킴 → 검출
            await db_session.execute(
                text("UPDATE concept_version SET concept_id = :cb WHERE version_id = :v"),
                {"cb": code_b, "v": ver},
            )
            await db_session.commit()
            assert code_a in await _kind_identifiers(db_session, kind)
        finally:
            await db_session.execute(
                text("UPDATE concept SET current_published_version_id = NULL WHERE code = :ca"),
                {"ca": code_a},
            )
            await db_session.execute(
                text("DELETE FROM concept_version WHERE version_id = :v"), {"v": ver}
            )
            await db_session.execute(
                text("DELETE FROM concept WHERE code = ANY(:codes)"), {"codes": [code_a, code_b]}
            )
            await db_session.commit()
        assert code_a not in await _kind_identifiers(db_session, kind)
        assert await self._scanned(db_session) == scanned_before


class TestSkillCoverageIsAnIndicatorNotAVerdict:
    """계획서 200 §27 검사 ① — 커버리지는 **지표이지 위반이 아니다** (EOS-07).

    차단 kind로 넣지 않은 근거는 실측이다: 코퍼스 전수에서 문제 14,034건 중 스킬까지 해소되는
    것이 89.5%다. 나머지 10.5%는 참조 깨짐이 아니라 *아직 스킬이 안 붙은* 것이며, 차단 kind로
    만들면 prod에서 상시 red가 되어 사람이 게이트 자체를 끄게 된다.

    그래서 이 테스트가 동결하는 것은 두 가지다 — ① 커버리지가 실제로 계산된다 ② 그 값이
    **exit code를 바꾸지 않는다**(지표가 조용히 게이트가 되는 회귀 차단).
    """

    async def test_coverage_counts_are_computed_and_ordered(self, db_session: AsyncSession) -> None:
        coverage = await gate.skill_coverage(db_session)
        assert coverage.total >= 0
        assert coverage.with_concept <= coverage.total, "개념 연결이 전체보다 많을 수 없다"
        assert (
            coverage.with_skill <= coverage.with_concept
        ), "스킬 해소는 개념 연결의 부분집합이다 — 더 크면 조인이 잘못됐다"
        if coverage.total == 0:
            # 미측정 ≠ 0 — 대상이 없으면 비율 0%는 '커버리지 0'이 아니다.
            assert coverage.skill_ratio == 0.0

    async def test_coverage_does_not_participate_in_the_exit_code(
        self, db_session: AsyncSession
    ) -> None:
        """커버리지가 낮아도 게이트 판정은 kind 위반만 본다 — 지표가 게이트가 되면 안 된다."""
        report = await gate.scan_integrity(db_session)
        assert gate.KIND_PUBLISHED_VERSION_INVALID in gate.ALL_KINDS
        assert "SKILL_COVERAGE" not in gate.ALL_KINDS
        assert not any(v.kind == "SKILL_COVERAGE" for v in report.violations)
