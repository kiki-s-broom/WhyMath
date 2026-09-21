"""개인정보 열람·이동권(`privacy/export.py`) — 단위(hermetic·FakeSession) + 실 PG 통합.

단위(FakeSession): `export_user_data`의 *조립 로직*만 검증한다 — `_EXPORT_PLAN` 카테고리별 직렬화·
user_profile 단건·`exported_at`·`not_included` 고지·**읽기 전용**(execute만·commit/flush 0).
`external_export_pending`(외부 store 매니페스트)도 검증. ★실제 ORM 직렬화·**대화 턴 조인 스코핑**
(증분 6·`dialogue_turn`엔 user_id 없음)은 *실 PG 통합테스트*가 seed→export로 검증한다(중복 0).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from _external_store_evidence import (
    KNOWN_UNDEPLOYED_STORES,
    assert_manifest_stores_are_deployed,
)
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from whymath_backend.config import Settings
from whymath_backend.db.models.activity import AttemptEvent, ProblemAttempt
from whymath_backend.db.models.answer_submission import AnswerSubmission
from whymath_backend.db.models.dialogue import Dialogue, DialogueTurn
from whymath_backend.db.models.student_solution_step import StudentSolutionStep
from whymath_backend.db.models.user import UserProfile
from whymath_backend.privacy.export import (
    ExternalDataLocation,
    UserDataExport,
    export_user_data,
    external_export_pending,
)
from whymath_backend.schema.dialogue import Dialogue as DialogueSchema
from whymath_backend.schema.dialogue import DialogueTurn as DialogueTurnSchema
from whymath_backend.schema.enums import ContentType, EventType, Persona, TurnRole
from whymath_backend.schema.user import UserProfile as UserProfileSchema

_CATEGORIES = {
    "learning_sessions",
    "problem_attempts",
    "assessments",
    "concept_mastery_history",
    "skill_mastery_history",
    "ability_snapshots",
    "parental_consents",
    "track_history",
    "persona_history",
    "state_snapshots",
    "misconception_hypotheses",
    "misconception_evidence",
    "daily_learning_metrics",
    "user_behavior_metrics",
    "dialogues",
    "attempt_events",
    "answer_submissions",
    "hint_usages",
    "student_solution_steps",
    "dialogue_turns",
}


class _StubSchema:
    """to_schema() 반환 흉내 — model_dump(mode="json")로 JSON-safe dict를 낸다."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def model_dump(self, *, mode: str) -> dict[str, Any]:
        assert mode == "json"
        return dict(self._payload)


class _StubRow:
    """ORM 행 흉내 — to_schema() + 대화 봉투 암호화 컬럼(감사상환 #2 export 복호 표면).

    dialogue_turns 조회 행은 export가 `content`/`image_uri`/`image_analysis`와 각 짝의
    `*_encrypted`/`*_nonce`를 읽어 노출 직전 복호한다(키 미설정 hermetic에선 평문 폴백
    passthrough). 다른 카테고리 행은 이 속성을 안 읽으므로 기본 None으로 둔다.
    """

    def __init__(
        self,
        payload: dict[str, Any],
        *,
        content: str | None = None,
        content_encrypted: bytes | None = None,
        content_nonce: bytes | None = None,
        image_uri: str | None = None,
        image_uri_encrypted: bytes | None = None,
        image_uri_nonce: bytes | None = None,
        image_analysis: dict[str, Any] | None = None,
        image_analysis_encrypted: bytes | None = None,
        image_analysis_nonce: bytes | None = None,
    ) -> None:
        self._payload = payload
        self.content = content
        self.content_encrypted = content_encrypted
        self.content_nonce = content_nonce
        self.image_uri = image_uri
        self.image_uri_encrypted = image_uri_encrypted
        self.image_uri_nonce = image_uri_nonce
        self.image_analysis = image_analysis
        self.image_analysis_encrypted = image_analysis_encrypted
        self.image_analysis_nonce = image_analysis_nonce

    def to_schema(self) -> _StubSchema:
        return _StubSchema(self._payload)


class _FakeScalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)

    def first(self) -> Any:
        return self._rows[0] if self._rows else None


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._rows)


class _FakeSession:
    """execute(select)별 scalars 큐를 순서대로 반환 + commit/flush 캡처(읽기 전용 검증)."""

    def __init__(self, result_rows: list[list[Any]]) -> None:
        self._queue = list(result_rows)
        self.executed: list[Any] = []
        self.commits = 0
        self.flushes = 0

    async def execute(self, stmt: Any) -> _FakeResult:
        self.executed.append(stmt)
        return _FakeResult(self._queue.pop(0))

    async def commit(self) -> None:
        self.commits += 1

    async def flush(self) -> None:
        self.flushes += 1


def _run(session: _FakeSession, user_id: uuid.UUID) -> UserDataExport:
    return asyncio.run(export_user_data(cast(AsyncSession, session), user_id=user_id))


# SEC-31: `problem_attempts`·`answer_submissions`·`student_solution_steps`는 이제 `_row_to_json`
# (→ `_StubRow.to_schema()`)이 아니라 `_student_work_row_json`이 처리한다 — 그 함수는
# `sa.inspect(type(row))`로 *실제* ORM 매퍼를 읽으므로 `_StubRow`(가짜 타입)로는 대체할 수 없다
# (KeyError — `_STUDENT_WORK_MODELS`에 없는 타입). 그래서 이 세 카테고리만 실제 ORM 인스턴스를
# 쓴다(암호화 컬럼 미설정 — cipher None 평문 passthrough이므로 `.to_schema()`와 동일 결과가
# 기대값이 된다).
_PA_ROW = ProblemAttempt(
    attempt_id=uuid.UUID("00000000-0000-0000-0000-0000000000a1"),
    user_id=uuid.UUID("00000000-0000-0000-0000-0000000000a2"),
    is_correct=True,
    student_answer="pa 원문",
    # server_default('[]'::jsonb)는 실제 flush를 거쳐야 채워진다 — 이 행은 실 DB를 거치지 않는
    # 순수 Python 인스턴스라 명시로 채운다(schema가 필수 list라 None이면 ValidationError).
    step_times=[],
)
_ASB_ROW = AnswerSubmission(
    submission_id=uuid.UUID("00000000-0000-0000-0000-0000000000b1"),
    attempt_id=uuid.UUID("00000000-0000-0000-0000-0000000000b2"),
    user_id=uuid.UUID("00000000-0000-0000-0000-0000000000b3"),
    sequence_no=1,
    response_type="text",
    raw_response="asb 원문",
)
_SSS_ROW = StudentSolutionStep(
    student_step_id=uuid.UUID("00000000-0000-0000-0000-0000000000c1"),
    attempt_id=uuid.UUID("00000000-0000-0000-0000-0000000000c2"),
    user_id=uuid.UUID("00000000-0000-0000-0000-0000000000c3"),
    sequence_no=1,
    expression="sss 원문",
    concept_ids=[],  # server_default 미적용(순수 Python 인스턴스) — schema 필수 list라 명시.
)


class TestExportUserData:
    def test_assembles_categories_and_profile(self) -> None:
        """20종 카테고리(+대화 턴 조인) 직렬화 + user_profile 단건 + exported_at + 읽기 전용."""
        uid = uuid.uuid4()
        # _EXPORT_PLAN(19) + dialogue_turns 조인(1) + profile(1) = 21 execute. learning_sessions
        # (0)·skill_mastery_history(4·Phase 2b-2 신규)·ability_snapshots(5)·parental_consents(6)·
        # misconception_hypotheses(10)·misconception_evidence(11)·daily_learning_metrics(12)·
        # user_behavior_metrics(13)·dialogues(14)·attempt_events(15)·answer_submissions(16·EOS-32)·
        # hint_usages(17·EOS-45)·student_solution_steps(18·EOS-46)·dialogue_turns(19)에 구분 행,
        # 나머지 빈, 마지막 profile.
        fake = _FakeSession(
            [
                [_StubRow({"cat": "ls"})],
                [_PA_ROW],  # problem_attempts(SEC-31 — 실 ORM 인스턴스, 암호화 복호 표면)
                [],
                [],
                [],  # skill_mastery_history(Phase 2b-2·빈 구간)
                [_StubRow({"cat": "ab"})],
                [_StubRow({"cat": "pc"})],
                [],
                [],
                [],
                [_StubRow({"cat": "mh"})],
                [_StubRow({"cat": "me"})],
                [_StubRow({"cat": "dlm"})],
                [_StubRow({"cat": "ubm"})],
                [_StubRow({"cat": "dlg"})],
                [_StubRow({"cat": "aev"})],
                # answer_submissions(EOS-32·SEC-31 — 실 ORM 인스턴스, 암호화 복호 표면)
                [_ASB_ROW],
                [_StubRow({"cat": "hus"})],  # hint_usages(EOS-45·힌트 사용 이력)
                # student_solution_steps(EOS-46·SEC-31 — 실 ORM 인스턴스, 암호화 복호 표면)
                [_SSS_ROW],
                [
                    _StubRow(
                        {"cat": "dlt", "content": "평문 본문", "image_uri": "s3://x/h.png"},
                        content="평문 본문",
                        image_uri="s3://x/h.png",
                    )
                ],
                [_StubRow({"cat": "profile"})],
            ]
        )
        out = _run(fake, uid)
        assert out.user_id == uid
        assert isinstance(out.exported_at, datetime)
        assert set(out.data.keys()) == _CATEGORIES
        assert out.data["learning_sessions"] == [{"cat": "ls"}]
        # SEC-31: 암호화 컬럼 미설정(cipher None)이라 복호는 평문 passthrough — 결과는
        # `.to_schema().model_dump(mode="json")`와 동일해야 한다(같은 인스턴스로 기대값 계산).
        assert out.data["problem_attempts"] == [_PA_ROW.to_schema().model_dump(mode="json")]
        assert out.data["ability_snapshots"] == [{"cat": "ab"}]
        assert out.data["parental_consents"] == [{"cat": "pc"}]  # 증분 2 신규 카테고리
        assert out.data["misconception_hypotheses"] == [{"cat": "mh"}]  # 증분 3
        assert out.data["misconception_evidence"] == [{"cat": "me"}]  # 증분 3(student_id 스코핑)
        assert out.data["daily_learning_metrics"] == [{"cat": "dlm"}]  # 증분 4 신규
        assert out.data["user_behavior_metrics"] == [{"cat": "ubm"}]  # 증분 4 신규
        assert out.data["dialogues"] == [{"cat": "dlg"}]  # 증분 5 신규(대화 세션 메타)
        assert out.data["attempt_events"] == [{"cat": "aev"}]  # 증분 7 신규(세부 시도 이벤트)
        # EOS-32(답 제출 시퀀스)·SEC-31(암호화 복호 — cipher None 평문 passthrough)
        assert out.data["answer_submissions"] == [_ASB_ROW.to_schema().model_dump(mode="json")]
        assert out.data["hint_usages"] == [{"cat": "hus"}]  # EOS-45(힌트 사용 이력)
        # EOS-46(풀이 step)·SEC-31(암호화 복호 — cipher None 평문 passthrough)
        assert out.data["student_solution_steps"] == [_SSS_ROW.to_schema().model_dump(mode="json")]
        # 증분 6(대화 턴 본문·조인) + 감사상환 #2: 키 미설정이라 평문 passthrough 복호.
        # SEC-01: image_uri·image_analysis도 복호 표면에 올라 export에 실린다(이미지 없으면 None).
        assert out.data["dialogue_turns"] == [
            {
                "cat": "dlt",
                "content": "평문 본문",
                "image_uri": "s3://x/h.png",
                "image_analysis": None,
            }
        ]
        assert out.user_profile == {"cat": "profile"}
        assert len(out.not_included) >= 1  # 부분 export 정직 고지
        assert fake.commits == 0 and fake.flushes == 0  # 읽기 전용(저장소 패턴)
        assert len(fake.executed) == 21

    def test_no_profile_yields_none(self) -> None:
        """프로필 행이 없으면 user_profile=None·각 카테고리 빈 리스트."""
        fake = _FakeSession([[] for _ in range(21)])
        out = _run(fake, uuid.uuid4())
        assert out.user_profile is None
        assert all(rows == [] for rows in out.data.values())
        assert set(out.data.keys()) == _CATEGORIES

    def test_multiple_rows_preserved(self) -> None:
        """카테고리당 다행 직렬화 보존(리스트 순서)."""
        fake = _FakeSession([[_StubRow({"n": 1}), _StubRow({"n": 2})], *([[]] * 20)])
        out = _run(fake, uuid.uuid4())
        assert out.data["learning_sessions"] == [{"n": 1}, {"n": 2}]


class TestExternalExportPending:
    """미포함 범위 고지의 진실성 — 선언한 store가 실재해야 한다(SEC-32·삭제권 매니페스트와 동형).

    하드코딩 집합(`{"clickhouse","s3","redis"}`) 대신 배포 근거 대조로 바꾼다. 열람권 쪽이
    삭제권 쪽보다 느슨하면 안 된다 — 같은 사실("데이터가 밖 어디에 있는가")을 두 권리가
    서로 다르게 고지하게 된다.
    """

    def test_declared_stores_are_actually_deployed(self) -> None:
        """선언된 store 전부에 배포 근거가 있고, 각 locator가 그 user를 가리킨다."""
        uid = uuid.uuid4()
        pending = external_export_pending(uid)
        assert_manifest_stores_are_deployed(
            (t.store for t in pending), source="external_export_pending"
        )
        assert all(str(uid) in t.locator for t in pending)
        assert all(isinstance(t, ExternalDataLocation) for t in pending)

    def test_undeployed_stores_are_not_declared(self) -> None:
        """미도입 store(ClickHouse·S3)는 미포함 고지에도 등장하지 않는다."""
        declared = {t.store for t in external_export_pending(uuid.uuid4())}
        assert not declared & set(KNOWN_UNDEPLOYED_STORES)

    def test_mirrors_erasure_manifest_stores(self) -> None:
        """삭제권 매니페스트와 *같은 store 집합*이다 — 한쪽만 고치면 두 고지가 모순된다."""
        from whymath_backend.privacy.erasure import external_erasure_targets

        uid = uuid.uuid4()
        assert {t.store for t in external_export_pending(uid)} == {
            t.store for t in external_erasure_targets(uid)
        }

    def test_frozen(self) -> None:
        """ExternalDataLocation은 frozen(불변)."""
        loc = external_export_pending(uuid.uuid4())[0]
        with pytest.raises(Exception):  # noqa: B017 — pydantic frozen ValidationError
            loc.store = "x"  # type: ignore[misc]


# ===========================================================================
# 통합 (실 PG·기본 SKIP) — seed→export 왕복(증분 6 대화 턴 조인 스코핑 검증)
# ===========================================================================

_SECRET = "integration-jwt-secret-0123456789abcdef"


def _settings() -> Settings:
    return Settings(jwt_secret_key=SecretStr(_SECRET))


async def _pg_reachable() -> bool:
    engine = create_async_engine(_settings().database_url)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


def _build_user(user_id: uuid.UUID) -> UserProfile:
    return UserProfile.from_schema(
        UserProfileSchema(
            user_id=user_id,
            persona_primary=Persona.A_일반고고3,
            nickname="열람학생",
            email_hash=f"HASH-{user_id.hex[:8]}",
            is_minor=True,
        )
    )


def _build_turn(dialogue_id: uuid.UUID, order: int, content: str) -> DialogueTurn:
    return DialogueTurn.from_schema(
        DialogueTurnSchema(
            dialogue_id=dialogue_id,
            turn_order=order,
            role=TurnRole.student,
            content=content,
            content_type=ContentType.텍스트,
            spoken_at=datetime.now(UTC),
        )
    )


async def _cleanup(user_ids: tuple[uuid.UUID, ...], dialogue_ids: tuple[uuid.UUID, ...]) -> None:
    engine = create_async_engine(_settings().database_url)
    try:
        async with engine.begin() as conn:
            for did in dialogue_ids:
                await conn.execute(
                    text("DELETE FROM dialogue_turn WHERE dialogue_id = :k"), {"k": str(did)}
                )
            for uid in user_ids:
                await conn.execute(text("DELETE FROM dialogue WHERE user_id = :k"), {"k": str(uid)})
                await conn.execute(
                    text("DELETE FROM user_profile WHERE user_id = :k"), {"k": str(uid)}
                )
    finally:
        await engine.dispose()


@pytest.mark.integration
def test_export_dialogue_turns_scoped_by_join_on_live_pg() -> None:
    """증분 6 — `dialogue_turns`는 user_id 직접 키가 없어 `Dialogue` 조인으로 본인 턴만(타인 제외).

    학생 A의 대화 턴 2건(역순 삽입)·학생 B의 턴 1건을 심고, A의 export가 A의 2턴만 turn_order
    오름차순·본문 round-trip으로 담고 B의 턴은 *조인 WHERE user_id 스코핑*으로 제외함을 실 PG로
    검증한다(hermetic FakeSession이 못 잡는 실제 조인 SQL·정렬·직렬화).
    """
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

    a_uid = uuid.uuid4()
    b_uid = uuid.uuid4()
    a_did = uuid.uuid4()
    b_did = uuid.uuid4()

    async def _seed(sm: async_sessionmaker[AsyncSession]) -> None:
        # 사용자를 *먼저 별도 트랜잭션*으로 커밋 — dialogue.user_id FK(fk_dialogue_user_id_
        # user_profile)가 user_profile 선존재를 요구한다(test_erasure 패턴 그대로).
        async with sm() as session:
            session.add(_build_user(a_uid))
            session.add(_build_user(b_uid))
            await session.commit()
        async with sm() as session:
            session.add(
                Dialogue.from_schema(
                    DialogueSchema(dialogue_id=a_did, user_id=a_uid, total_turns=2)
                )
            )
            session.add(
                Dialogue.from_schema(
                    DialogueSchema(dialogue_id=b_did, user_id=b_uid, total_turns=1)
                )
            )
            await session.flush()  # 턴 FK(dialogue_id)가 dialogue 선존재를 요구
            session.add(_build_turn(a_did, 2, "두번째 턴"))  # 역순 삽입 → 정렬 검증
            session.add(_build_turn(a_did, 1, "첫번째 턴"))
            session.add(_build_turn(b_did, 1, "타인 턴"))
            await session.commit()

    async def _run() -> None:
        engine = create_async_engine(_settings().database_url)
        try:
            sm = async_sessionmaker(engine, expire_on_commit=False)
            await _seed(sm)
            async with sm() as session:
                export = await export_user_data(session, user_id=a_uid)

            # 대화 세션 메타 — A의 대화만(B 제외).
            dialogues = export.data["dialogues"]
            assert [d["dialogue_id"] for d in dialogues] == [str(a_did)]

            # 대화 턴 — A의 2턴만·turn_order 오름차순·본문 round-trip·B 턴 제외(조인 스코핑).
            turns = export.data["dialogue_turns"]
            assert [t["turn_order"] for t in turns] == [1, 2]
            assert [t["content"] for t in turns] == ["첫번째 턴", "두번째 턴"]
            assert all(t["dialogue_id"] == str(a_did) for t in turns)
        finally:
            await engine.dispose()

    try:
        asyncio.run(_run())
    finally:
        asyncio.run(_cleanup((a_uid, b_uid), (a_did, b_did)))


async def _cleanup_attempt_events(user_ids: tuple[uuid.UUID, ...]) -> None:
    engine = create_async_engine(_settings().database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM attempt_event WHERE user_id = ANY(:uids)"),
                {"uids": [str(u) for u in user_ids]},
            )
    finally:
        await engine.dispose()


def test_export_attempt_events_scoped_by_user_on_live_pg() -> None:
    """증분 7(실 PG) — attempt_events는 user_id로 본인만·event_data(JSONB) round-trip·타인 제외.

    `attempt_event`는 FK 없는 hypertable 느슨참조라 user_profile 선적재 불요. 학생 A의 이벤트 2건·
    학생 B의 1건을 심고, A의 export가 A의 2건만(event_id/event_at 정렬·JSONB 페이로드 보존) 담고
    B는 제외함을 실 PG로 검증한다(hermetic이 못 잡는 실제 user_id 쿼리·JSONB 직렬화).
    """
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

    a_uid = uuid.uuid4()
    b_uid = uuid.uuid4()
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    t2 = datetime(2026, 1, 1, 0, 5, tzinfo=UTC)

    async def _seed(sm: async_sessionmaker[AsyncSession]) -> None:
        async with sm() as session:
            # event_id(BIGSERIAL)는 DB가 삽입 순서로 할당 → A는 검산결과(먼저)·힌트제공(나중) 순.
            session.add(
                AttemptEvent(
                    event_at=t1,
                    user_id=a_uid,
                    event_type=EventType.검산결과,
                    event_data={"passed": True},
                )
            )
            session.add(
                AttemptEvent(
                    event_at=t2,
                    user_id=a_uid,
                    event_type=EventType.힌트제공,
                    event_data={"hint_level": 2},
                )
            )
            session.add(
                AttemptEvent(
                    event_at=t1,
                    user_id=b_uid,
                    event_type=EventType.검산결과,
                    event_data={"passed": False},
                )
            )
            await session.commit()

    async def _run() -> None:
        engine = create_async_engine(_settings().database_url)
        try:
            sm = async_sessionmaker(engine, expire_on_commit=False)
            await _seed(sm)
            async with sm() as session:
                export = await export_user_data(session, user_id=a_uid)
            events = export.data["attempt_events"]
            assert len(events) == 2  # A의 2건만(B 제외)
            assert all(e["user_id"] == str(a_uid) for e in events)  # user_id 스코핑
            # event_id 오름차순(삽입 순서)·JSONB 페이로드 round-trip.
            assert [e["event_data"] for e in events] == [{"passed": True}, {"hint_level": 2}]
        finally:
            await engine.dispose()

    try:
        asyncio.run(_run())
    finally:
        asyncio.run(_cleanup_attempt_events((a_uid, b_uid)))
