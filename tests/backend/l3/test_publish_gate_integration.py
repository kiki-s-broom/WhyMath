"""Publish Gate 실 PostgreSQL 통합 테스트 — EOS-50 ①⑩⑪ (WHYMATH_RUN_INTEGRATION).

마이그레이션 head(`9d3e7b1c5a20` 이상)가 적용된 실 PG에서 `l3/publish_gate.py`의 실행 층을
검증한다. PG 미도달·리비전 미적용이면 graceful skip.

핵심(⑪): **Rollback이 이전 버전을 실제로 복원한다** — v1 발행 → v2 발행(v1 대체) → rollback 뒤,
발행 포인터가 가리키는 판의 payload를 DB에서 다시 읽어 **v1 발행 시점에 떠 둔 스냅숏과 바이트
단위로 같은지** 단언한다(해시만 비교하지 않는다 — 해시 함수가 고장 나도 이 단언은 속지 않는다).

RED 축(⑩): 미승인 Publish·승인 위조·승인 후 payload 변조·내려가 있던 판의 변조가 전부 거부되고,
거부된 뒤 DB 상태가 그대로인지(부분 쓰기 없음)를 단언한다.

각 테스트는 고유 개념 코드를 심고 끝나면 지운다(다른 통합 테스트와 같은 DB를 공유하므로
전역 판정이 아니라 자기가 심은 식별자로만 단언한다).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from whymath_backend.config import Settings
from whymath_backend.l3 import publish_gate as gate
from whymath_backend.ops import integrity_violations_gate as integrity
from whymath_backend.schema.concept_version import ConceptVersionPayload
from whymath_backend.schema.enums import ConceptLevel
from whymath_backend.schema.version_header import TransitionAction, VersionStatus
from whymath_backend.schema.version_lifecycle import UndefinedTransitionError

pytestmark = pytest.mark.integration

_A = TransitionAction
_TO_APPROVED = (_A.SUBMIT, _A.PASS_REVIEW, _A.APPROVE)


async def _ready() -> bool:
    """PG 도달 + 이 태스크의 리비전 적용(`concept_version.qa` 컬럼 존재)."""
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.connect() as conn:
            found = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name = 'concept_version' AND column_name = 'qa'"
                    )
                )
            ).first()
        return found is not None
    except Exception:
        return False
    finally:
        await engine.dispose()


@pytest.fixture
async def sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    if not await _ready():
        pytest.skip("PostgreSQL 미도달 또는 리비전 9d3e7b1c5a20 미적용 — 통합 테스트 건너뜀")
    engine = create_async_engine(Settings().database_url)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest.fixture
async def concept_code(sessions: async_sessionmaker[AsyncSession]) -> AsyncIterator[str]:
    code = f"HIGH-EOS50-{uuid.uuid4().hex[:8]}"
    async with sessions() as s:
        await s.execute(
            text(
                "INSERT INTO concept (code, name_ko, level, aliases) "
                "VALUES (:code, 'EOS-50 sentinel', '세부개념', '{}'::text[])"
            ),
            {"code": code},
        )
        await s.commit()
    try:
        yield code
    finally:
        async with sessions() as s:
            await s.execute(
                text("UPDATE concept SET current_published_version_id = NULL WHERE code = :c"),
                {"c": code},
            )
            await s.execute(text("DELETE FROM concept_version WHERE concept_id = :c"), {"c": code})
            await s.execute(text("DELETE FROM concept WHERE code = :c"), {"c": code})
            await s.commit()


def _payload(name: str) -> ConceptVersionPayload:
    return ConceptVersionPayload(
        name_ko=name,
        level=ConceptLevel.세부개념,
        aliases=[f"{name}-별칭"],
        intrinsic_difficulty=2.5,
    )


async def _new_version(
    sessions: async_sessionmaker[AsyncSession], code: str, name: str
) -> uuid.UUID:
    async with sessions() as s:
        created = await gate.create_draft(
            s,
            concept_code=code,
            payload=_payload(name),
            schema_version="concept-payload@1",
            created_by="author",
        )
        await s.commit()
    return created.version_id


async def _walk(
    sessions: async_sessionmaker[AsyncSession], version_id: uuid.UUID, *actions: TransitionAction
) -> None:
    for action in actions:
        async with sessions() as s:
            await gate.apply_transition(s, version_id, action, actor=f"{action.value}-actor")
            await s.commit()


async def _row(sessions: async_sessionmaker[AsyncSession], version_id: uuid.UUID) -> dict[str, Any]:
    async with sessions() as s:
        row = (
            (
                await s.execute(
                    text(
                        "SELECT status::text AS status, payload, integrity, qa, published_at, "
                        "version_no, previous_version_id "
                        "FROM concept_version WHERE version_id = :v"
                    ),
                    {"v": version_id},
                )
            )
            .mappings()
            .one()
        )
    return dict(row)


async def _pointer(sessions: async_sessionmaker[AsyncSession], code: str) -> uuid.UUID | None:
    async with sessions() as s:
        value = (
            await s.execute(
                text("SELECT current_published_version_id FROM concept WHERE code = :c"),
                {"c": code},
            )
        ).scalar_one()
    return value  # type: ignore[no-any-return]


async def _published_payload_via_pointer(
    sessions: async_sessionmaker[AsyncSession], code: str
) -> dict[str, Any]:
    async with sessions() as s:
        payload = (
            await s.execute(
                text(
                    "SELECT cv.payload FROM concept c "
                    "JOIN concept_version cv ON cv.version_id = c.current_published_version_id "
                    "WHERE c.code = :c"
                ),
                {"c": code},
            )
        ).scalar_one()
    return payload  # type: ignore[no-any-return]


def _canonical(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False)


async def _pointer_violations(sessions: async_sessionmaker[AsyncSession], code: str) -> set[str]:
    async with sessions() as s:
        report = await integrity.scan_integrity(s)
    return {
        v.identifier
        for v in report.violations_by_kind(integrity.KIND_PUBLISHED_VERSION_INVALID)
        if v.identifier == code
    }


# ── ⑪ Rollback이 이전 버전을 실제로 복원한다 ─────────────────────────────────
async def test_rollback_restores_the_previous_published_version(
    sessions: async_sessionmaker[AsyncSession], concept_code: str
) -> None:
    v1 = await _new_version(sessions, concept_code, "첫 판")
    await _walk(sessions, v1, *_TO_APPROVED, _A.PUBLISH)
    assert await _pointer(sessions, concept_code) == v1
    v1_published = await _row(sessions, v1)
    assert v1_published["status"] == "PUBLISHED"
    snapshot = _canonical(v1_published["payload"])  # 발행 시점 내용의 사본

    v2 = await _new_version(sessions, concept_code, "둘째 판(결함)")
    v2_row = await _row(sessions, v2)
    assert v2_row["version_no"] == 2 and v2_row["previous_version_id"] == v1
    await _walk(sessions, v2, *_TO_APPROVED, _A.PUBLISH)
    assert await _pointer(sessions, concept_code) == v2
    assert (await _row(sessions, v1))["status"] == "DEPRECATED"  # supersede
    assert _canonical(await _published_payload_via_pointer(sessions, concept_code)) != snapshot

    async with sessions() as s:
        result = await gate.rollback(s, concept_code, actor="operator")
        await s.commit()
    assert (result.rolled_back_version_id, result.restored_version_id) == (v2, v1)

    # 복원 단언 — 포인터·상태·내용(바이트 동일)·해시
    assert await _pointer(sessions, concept_code) == v1
    restored = await _row(sessions, v1)
    assert restored["status"] == "PUBLISHED"
    assert (await _row(sessions, v2))["status"] == "RETIRED"
    assert _canonical(await _published_payload_via_pointer(sessions, concept_code)) == snapshot
    assert restored["integrity"]["content_hash"] == gate.compute_content_hash(_payload("첫 판"))
    assert restored["published_at"] == v1_published["published_at"]  # 첫 발행 시각 보존
    last = restored["qa"]["records"][-1]
    assert (last["gate"], last["action"], last["judged_by"], last["bypassed"]) == (
        "restore",
        "restore",
        "operator",
        False,
    )
    # 사후 감사(무결성 게이트 ⑦)도 발행 포인터를 정상으로 본다
    assert await _pointer_violations(sessions, concept_code) == set()

    # 더 앞선 판이 없으면 두 번째 롤백은 거부(결함 판 v2는 RETIRED라 후보가 아니다)
    async with sessions() as s:
        with pytest.raises(gate.RollbackUnavailableError):
            await gate.rollback(s, concept_code, actor="operator")
        await s.rollback()
    assert await _pointer(sessions, concept_code) == v1


async def test_rollback_refuses_when_the_deprecated_payload_was_tampered(
    sessions: async_sessionmaker[AsyncSession], concept_code: str
) -> None:
    """DEPRECATED 판의 payload는 DB 트리거가 보호하지 않는다 — 복원 게이트가 해시로 잡는다."""
    v1 = await _new_version(sessions, concept_code, "첫 판")
    await _walk(sessions, v1, *_TO_APPROVED, _A.PUBLISH)
    v2 = await _new_version(sessions, concept_code, "둘째 판")
    await _walk(sessions, v2, *_TO_APPROVED, _A.PUBLISH)
    async with sessions() as s:
        await s.execute(
            text(
                "UPDATE concept_version SET payload = jsonb_set(payload, '{name_ko}', "
                "'\"몰래 바뀐 이름\"') WHERE version_id = :v"
            ),
            {"v": v1},
        )
        await s.commit()

    async with sessions() as s:
        with pytest.raises(gate.PublishGateError, match="content_hash"):
            await gate.rollback(s, concept_code, actor="operator")
        await s.rollback()
    # 부분 쓰기 없음 — v2가 그대로 발행 중
    assert await _pointer(sessions, concept_code) == v2
    assert (await _row(sessions, v2))["status"] == "PUBLISHED"
    assert (await _row(sessions, v1))["status"] == "DEPRECATED"


# ── ⑩ 미승인 Publish·미정의 전이 ──────────────────────────────────────────────
async def test_publish_from_draft_is_refused_and_nothing_changes(
    sessions: async_sessionmaker[AsyncSession], concept_code: str
) -> None:
    v1 = await _new_version(sessions, concept_code, "초안")
    async with sessions() as s:
        with pytest.raises(UndefinedTransitionError):
            await gate.apply_transition(s, v1, _A.PUBLISH, actor="x")
        await s.rollback()
    assert (await _row(sessions, v1))["status"] == "DRAFT"
    assert await _pointer(sessions, concept_code) is None


async def test_forged_approved_status_cannot_publish(
    sessions: async_sessionmaker[AsyncSession], concept_code: str
) -> None:
    """승인 간선을 건너뛰고 상태만 APPROVED로 바꾼 행 — 게이트가 거부한다."""
    v1 = await _new_version(sessions, concept_code, "위조 승인")
    async with sessions() as s:
        await s.execute(
            text("UPDATE concept_version SET status = 'APPROVED' WHERE version_id = :v"),
            {"v": v1},
        )
        await s.commit()
    async with sessions() as s:
        with pytest.raises(gate.PublishGateError) as info:
            await gate.apply_transition(s, v1, _A.PUBLISH, actor="x")
        await s.rollback()
    assert "governance_complete" in " ".join(info.value.failures)
    assert (await _row(sessions, v1))["status"] == "APPROVED"
    assert await _pointer(sessions, concept_code) is None


async def test_payload_tampered_after_approval_cannot_publish(
    sessions: async_sessionmaker[AsyncSession], concept_code: str
) -> None:
    v1 = await _new_version(sessions, concept_code, "승인본")
    await _walk(sessions, v1, *_TO_APPROVED)
    async with sessions() as s:
        await s.execute(
            text(
                "UPDATE concept_version SET payload = jsonb_set(payload, '{name_ko}', "
                "'\"승인 후 변조\"') WHERE version_id = :v"
            ),
            {"v": v1},
        )
        await s.commit()
    async with sessions() as s:
        with pytest.raises(gate.PublishGateError, match="content_hash"):
            await gate.apply_transition(s, v1, _A.PUBLISH, actor="x")
        await s.rollback()
    assert (await _row(sessions, v1))["status"] == "APPROVED"
    assert await _pointer(sessions, concept_code) is None


async def test_undefined_transition_on_published_is_refused(
    sessions: async_sessionmaker[AsyncSession], concept_code: str
) -> None:
    v1 = await _new_version(sessions, concept_code, "발행본")
    await _walk(sessions, v1, *_TO_APPROVED, _A.PUBLISH)
    for action in (_A.RETIRE, _A.SUBMIT, _A.ROLLBACK):
        async with sessions() as s:
            with pytest.raises(UndefinedTransitionError):
                await gate.apply_transition(s, v1, action, actor="x")
            await s.rollback()
    assert (await _row(sessions, v1))["status"] == "PUBLISHED"


async def test_deprecate_clears_the_pointer(
    sessions: async_sessionmaker[AsyncSession], concept_code: str
) -> None:
    v1 = await _new_version(sessions, concept_code, "내릴 판")
    await _walk(sessions, v1, *_TO_APPROVED, _A.PUBLISH, _A.DEPRECATE)
    assert (await _row(sessions, v1))["status"] == VersionStatus.DEPRECATED.value
    assert await _pointer(sessions, concept_code) is None
    assert await _pointer_violations(sessions, concept_code) == set()


async def test_db_trigger_still_guards_published_payload(
    sessions: async_sessionmaker[AsyncSession], concept_code: str
) -> None:
    """EOS-49 트리거와 공존 — 게이트가 PUBLISHED 행의 qa·상태를 쓰는 것은 허용되고
    payload 직접 변경은 여전히 DB가 거부한다."""
    v1 = await _new_version(sessions, concept_code, "불변")
    await _walk(sessions, v1, *_TO_APPROVED, _A.PUBLISH)
    async with sessions() as s:
        with pytest.raises(DBAPIError, match="immutable"):
            await s.execute(
                text("UPDATE concept_version SET payload = '{}'::jsonb WHERE version_id = :v"),
                {"v": v1},
            )
        await s.rollback()
