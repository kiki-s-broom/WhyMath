"""PED-37 — `ProblemAttempt.started_at` 상시 NULL 근본수정의 *집행 지점* 증명 (실 PG·기본 SKIP).

버그(main 실측): attempt를 적재하는 서빙 writer가 **둘 다** `started_at`을 채우지 않았다 —
`api/me.py::submit_attempt`(클라 자가보고 경로)·`api/coach.py::_complete_problem`(코치 완료
경로). 그 컬럼이 비면 두 소비자가 *조용히* 무력해진다:

  - `harness/wh1_evaluation.compute_wh1_surrogate_metrics` — R15 정답률/난이도 추세·⑥ Brier·
    ⑦ 전이 점수의 `since`/`until` 필터가 전부 `ProblemAttempt.started_at` 기준이라, NULL과의
    비교는 참이 되지 못해 **시간창을 지정한 호출이 상시 0행**이었다.
  - `privacy/retention._RETENTION_PLAN` — `(ProblemAttempt, "started_at")`이 보존기한 파기
    기준이라 미성년 풀이 데이터의 **파기 대상이 상시 0건**이었다(PII 무기한 보존).

두 실패 모두 예외를 내지 않는다. 0행은 "데이터가 없다"와 글자 그대로 같은 화면이라, 이 모듈은
**개수를 단언**한다 — 지표가 MEASURED로 바뀌는 것만이 아니라 *정확히 몇 건을 셌는지*까지 본다.

변별력 설계(CLAUDE.md 「보호 장치를 실패 주입 없이 보호 있음으로 선언 금지」):
  - 시간창 테스트의 표본은 ORM 직접 적재가 아니라 **서빙 엔드포인트를 통해** 쌓는다. writer가
    `started_at`을 무시하도록 되돌리면(수정 전 상태) 이 테스트는 실제로 RED가 된다 — ORM으로
    미리 채워 넣으면 writer가 죽어도 초록이라 배선을 증명하지 못한다.
  - 같은 표본 안에 **미신고(NULL) attempt**를 섞는다. 시간창 지정 호출에서 조용히 빠지고
    no-window 호출에는 포함되는 것이 계약이며, 그 계약 자체를 개수로 고정한다.
  - no-window(since=until=None) 결과는 `started_at` 유무와 무관하게 같다 — 회귀 0 축의 단언.

베이스: `test_coach_integration.py`·`test_e2e_vertical_slice_integration.py`의 실 PG 픽스처·시딩
헬퍼 패턴을 *동형 복제*한다(각 통합 모듈이 `_settings`·`_pg_reachable`을 독립 정의하는 선례 —
모듈 간 test import 이중 수집 회피). 정리는 try/finally로 FK 안전 순서를 보장한다.

SEC-33 후속(`TestRetentionPurge.test_null_started_at_is_still_purged_via_ingested_at_fallback`):
위 파기 소비자 테스트가 고정한 "NULL은 파기 대상 아님" 정직 스코프는 그 자체로 새 회피 통로였다
— 클라가 `started_at` 신고를 아예 생략하면 무기한 보존을 얻는다. `privacy/retention`이
`ProblemAttempt`만 `COALESCE(started_at, ingested_at)`으로 폴백해 닫는다(`ingested_at`은 서버
전용·클라 조작 불가).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from whymath_backend.app import create_app
from whymath_backend.config import Settings, get_settings
from whymath_backend.db.models.activity import ProblemAttempt
from whymath_backend.db.models.dialogue import Dialogue
from whymath_backend.db.models.problem import Problem
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import dispose_engine
from whymath_backend.harness.wh1_evaluation import (
    MetricStatus,
    compute_wh1_surrogate_metrics,
)
from whymath_backend.privacy.retention import purge_expired_records
from whymath_backend.schema.enums import (
    Curriculum,
    Persona,
    ReviewStatus,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem import Problem as ProblemSchema
from whymath_backend.schema.user import UserProfile as UserProfileSchema
from whymath_backend.security import create_access_token

pytestmark = pytest.mark.integration

_SECRET = "ped37-integration-jwt-secret-0123456789"

# 코치 완료 경로 상수 — `verify_final_answer`가 결정론적으로 correct를 내야 하므로 값 해집합으로
# 읽히는 수치를 쓴다(`test_e2e_vertical_slice_integration.py` 선례와 동형·코칭 보일러플레이트와
# 우연히 겹치지 않는 특이한 수).
_COMPLETION_ANSWER = "70414"
_CORRECT_STEPS = ["2*x = 140828", f"x = {_COMPLETION_ANSWER}"]


@pytest.fixture(autouse=True)
def _dispose_db_globals() -> Iterator[None]:
    """매 테스트 뒤 `db.session` 전역 엔진 반납 — OPS-07 누수 가드가 요구하는 정리.

    이 모듈은 `get_session`을 오버라이드하지 않으므로(실 PG 관통이 목적) 첫 요청에서 전역
    엔진/세션메이커가 만들어진다. 가드는 integration 마크를 면제하지만 *격리까지* 해주지는
    않아서, 같은 프로세스에서 뒤따르는 hermetic 테스트가 남은 전역에 귀책된다(실측: 이 모듈
    뒤에 `test_coach_completion.py`를 붙이면 그쪽 첫 테스트가 teardown 에러). 우연히 마지막
    테스트가 lifespan을 돌아 정리되는 데 기대지 않고 명시적으로 반납한다.
    """
    yield
    asyncio.run(dispose_engine())


def _settings() -> Settings:
    """테스트 Settings — jwt 시크릿만 고정. database_url은 WHYMATH_DATABASE_URL 환경변수 소싱."""
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


def _skip_unless_pg() -> None:
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀 (WHYMATH_DATABASE_URL 확인)")


async def _add_all(*objs: object) -> None:
    engine = create_async_engine(_settings().database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add_all(list(objs))
            await session.commit()
    finally:
        await engine.dispose()


def _adult_user(uid: uuid.UUID) -> UserProfile:
    """성인 유저 — ConsentedUser(미성년 동의) 게이트를 동의 없이 통과시키기 위한 시딩."""
    return UserProfile.from_schema(
        UserProfileSchema(
            user_id=uid,
            persona_primary=Persona.A_일반고고3,
            birth_year=2000,
            is_minor=False,
        )
    )


def _problem(pid: uuid.UUID, suffix: str, *, answer: str | None = None) -> Problem:
    """자체생성 문제 — `answer`를 채우면 코치 완료 경로의 서버 정답 판정 입력이 된다."""
    return Problem.from_schema(
        ProblemSchema(
            problem_id=pid,
            source_type=SourceType.자체생성,
            review_status=ReviewStatus.approved,
            curriculum_version=Curriculum.REVISION_2022,
            valid_from_year=2022,
            subject=Subject.공통,
            unit_codes=[f"U-{suffix}"],
            difficulty_overall=3.0,
            answer=answer,
        )
    )


async def _fetch_all(stmt: Select[object]) -> list[object]:
    """독립 엔진으로 SELECT 실행 — 관측은 응답 필드가 아니라 *DB에 남은 것*으로 한다."""
    engine = create_async_engine(_settings().database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())
    finally:
        await engine.dispose()


async def _attempts_of(uid: uuid.UUID) -> list[ProblemAttempt]:
    from sqlalchemy import select

    rows = await _fetch_all(
        select(ProblemAttempt)
        .where(ProblemAttempt.user_id == uid)
        .order_by(ProblemAttempt.ingested_at)
    )
    return [row for row in rows if isinstance(row, ProblemAttempt)]


async def _dialogue(did: uuid.UUID) -> Dialogue:
    from sqlalchemy import select

    rows = await _fetch_all(select(Dialogue).where(Dialogue.dialogue_id == did))
    assert len(rows) == 1
    row = rows[0]
    assert isinstance(row, Dialogue)
    return row


async def _cleanup(
    uid: uuid.UUID,
    *,
    problem_ids: list[uuid.UUID],
    dialogue_ids: list[uuid.UUID] | None = None,
) -> None:
    """FK 안전 순서 정리 — dialogue_turn→attempt_event→가설→dialogue→problem_attempt→
    concept/skill 숙달→problem→user_profile."""
    engine = create_async_engine(_settings().database_url)
    dids = [str(d) for d in (dialogue_ids or [])]
    pids = [str(p) for p in problem_ids]
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM dialogue_turn WHERE dialogue_id = ANY(:ids)"), {"ids": dids}
            )
            await conn.execute(
                text("DELETE FROM attempt_event WHERE user_id = :uid"), {"uid": str(uid)}
            )
            await conn.execute(
                text("DELETE FROM misconception_hypothesis WHERE user_id = :uid"),
                {"uid": str(uid)},
            )
            await conn.execute(
                text("DELETE FROM dialogue WHERE dialogue_id = ANY(:ids)"), {"ids": dids}
            )
            await conn.execute(
                text("DELETE FROM problem_attempt WHERE user_id = :uid"), {"uid": str(uid)}
            )
            await conn.execute(
                text("DELETE FROM concept_mastery_history WHERE user_id = :uid"),
                {"uid": str(uid)},
            )
            await conn.execute(
                text("DELETE FROM skill_mastery_history WHERE user_id = :uid"), {"uid": str(uid)}
            )
            await conn.execute(
                text("DELETE FROM problem WHERE problem_id = ANY(:ids)"), {"ids": pids}
            )
            # EOS-115: 응답 제출이 학습 상태 전이를 적재하므로 user_profile보다 먼저 지운다.
            #
            # 이 줄이 없으면 `DELETE FROM user_profile`이 FK로 실패하고, 이 블록이
            # `engine.begin()` **트랜잭션**이라 위에서 지운 문항·숙달행까지 전부 롤백된다 —
            # 그 잔여 데이터가 *다른* 테스트의 추천 후보로 끼어들어 무관해 보이는 실패를
            # 만든다(2026-09-19 CI 실측: 이 파일의 FK 실패 5건이 다른 파일의 추천 단언 1건을
            # 함께 빨강으로 만들었다).
            await conn.execute(
                text("DELETE FROM learning_state_transition WHERE user_id = :uid"),
                {"uid": str(uid)},
            )
            # EOS-131: 서버 유휴 규칙 세션(user_profile의 자식) — user 삭제 전에 지운다.
            await conn.execute(
                text("DELETE FROM learning_session WHERE user_id = :uid"), {"uid": str(uid)}
            )
            await conn.execute(
                text("DELETE FROM user_profile WHERE user_id = :uid"), {"uid": str(uid)}
            )
    finally:
        await engine.dispose()


def _client(uid: uuid.UUID) -> tuple[TestClient, dict[str, str]]:
    """실 PG 클라이언트 — get_session은 오버라이드하지 않는다(라이브 PG). 인증은 실 JWT."""
    app = create_app()
    app.dependency_overrides[get_settings] = _settings
    client = TestClient(app)
    token = create_access_token(str(uid), settings=_settings())
    return client, {"Authorization": f"Bearer {token}"}


# ── ① writer A: POST /v1/me/attempts — 클라 신고 발생 시각을 그대로 적재 ─────────────────
class TestSubmitAttemptStartedAt:
    def test_reported_started_at_is_persisted_verbatim(self) -> None:
        """클라가 신고한 발생 시각이 *그대로* 남고, 서버 수신 시각은 ingested_at에 따로 남는다.

        `started_at != ingested_at`을 단언하는 이유: 서버 now 폴백이 살아 있으면 두 값이 같아진다
        (수신 시각 복제 = 날조·32_learning_history §EOS-48-2). 즉 이 부등호가 폴백 부재의 증거다.
        """
        _skip_unless_pg()
        uid, pid = uuid.uuid4(), uuid.uuid4()
        reported = datetime(2026, 3, 2, 9, 30, tzinfo=UTC)
        try:
            asyncio.run(_add_all(_adult_user(uid), _problem(pid, "ped37-a")))
            client, auth = _client(uid)
            resp = client.post(
                "/v1/me/attempts",
                headers=auth,
                json={
                    "problem_id": str(pid),
                    "is_correct": True,
                    "duration_seconds": 240,
                    "started_at": reported.isoformat(),
                },
            )
            assert resp.status_code == 201, resp.text

            attempts = asyncio.run(_attempts_of(uid))
            assert len(attempts) == 1
            attempt = attempts[0]
            assert (
                attempt.started_at is not None
            ), "신고된 발생 시각이 적재되지 않았다(writer 미배선)"
            assert attempt.started_at == reported
            assert attempt.ingested_at is not None, "서버 수신 시각 좌석이 비었다"
            # 신고 시각은 과거이고 수신은 지금 — 둘이 같으면 서버 now가 발생 자리에 들어간 것이다.
            assert attempt.ingested_at > attempt.started_at
        finally:
            asyncio.run(_cleanup(uid, problem_ids=[pid]))

    def test_unreported_started_at_stays_null(self) -> None:
        """클라 미신고면 NULL로 남는다 — 서버 now로 메우지 않는다(NULL=미측정이 정직한 상태)."""
        _skip_unless_pg()
        uid, pid = uuid.uuid4(), uuid.uuid4()
        try:
            asyncio.run(_add_all(_adult_user(uid), _problem(pid, "ped37-b")))
            client, auth = _client(uid)
            resp = client.post(
                "/v1/me/attempts",
                headers=auth,
                json={"problem_id": str(pid), "is_correct": False},
            )
            assert resp.status_code == 201, resp.text

            attempts = asyncio.run(_attempts_of(uid))
            assert len(attempts) == 1
            assert attempts[0].started_at is None, "미신고인데 값이 생겼다 — 서버 now 폴백 잔존"
            # 수신 시각은 서버가 아는 사실이므로 채워진다(미기록과 구분).
            assert attempts[0].ingested_at is not None
        finally:
            asyncio.run(_cleanup(uid, problem_ids=[pid]))


# ── ② writer B: 코치 완료 경로 — dialogue 발생 시각 이관 ─────────────────────────────────
class TestCoachCompletionStartedAt:
    def test_completion_attempt_carries_dialogue_started_at(self) -> None:
        """2턴 완료(정답 제출 → 돌아보기 응답)로 적재된 attempt가 대화 시작 시각을 물려받는다.

        추정이 아니라 *발생 시각끼리의 이관*이다 — 학생이 이 문항 풀이에 착수한 시점이 곧 대화가
        시작된 시점이므로 `dialogue.started_at`이 유일하게 정직한 출처다.
        """
        _skip_unless_pg()
        uid, pid = uuid.uuid4(), uuid.uuid4()
        dialogue_ids: list[uuid.UUID] = []
        try:
            asyncio.run(
                _add_all(_adult_user(uid), _problem(pid, "ped37-c", answer=_COMPLETION_ANSWER))
            )
            client, auth = _client(uid)
            # 턴 A — 정답 최종답 도달 → 돌아보기 대기(아직 완료 아님·적재 0).
            turn_a = client.post(
                "/v1/coach/sessions",
                headers=auth,
                json={
                    "student_input": "이렇게 풀어서 답이 나왔어",
                    "problem_id": str(pid),
                    "solution_steps": _CORRECT_STEPS,
                    "solution_step_types": ["계산"],
                },
            )
            assert turn_a.status_code == 201, turn_a.text
            abody = turn_a.json()
            assert abody["awaiting_reflection"] is True
            did = uuid.UUID(abody["dialogue_id"])
            dialogue_ids.append(did)
            assert asyncio.run(_attempts_of(uid)) == []

            # 턴 B — 돌아보기 응답 → 완료 확정·attempt 적재.
            turn_b = client.post(
                f"/v1/coach/sessions/{did}/turns",
                headers=auth,
                json={"student_input": "양변을 2로 나누면 x만 남아서 그렇게 풀었어"},
            )
            assert turn_b.status_code == 201, turn_b.text
            assert turn_b.json()["problem_complete"] is True

            attempts = asyncio.run(_attempts_of(uid))
            assert len(attempts) == 1
            attempt = attempts[0]
            dialogue = asyncio.run(_dialogue(did))
            assert dialogue.started_at is not None
            assert attempt.started_at is not None, "완료 attempt의 발생 시각이 비었다(이관 미배선)"
            assert attempt.started_at == dialogue.started_at
            assert attempt.ingested_at is not None
        finally:
            asyncio.run(_cleanup(uid, problem_ids=[pid], dialogue_ids=dialogue_ids))


# ── ③ 소비자 1: 시간창 집계 — 0행이던 것이 정확한 건수를 센다 ───────────────────────────
class TestTimeWindowAggregation:
    """`compute_wh1_surrogate_metrics`의 since/until 축.

    ⑥ 보정 점수(Brier)로 관측한다 — 이 지표는 note에 *쌓인 쌍 수*를 그대로 적고 값이 정확한
    평균이라, "MEASURED로 바뀌었다"가 아니라 **몇 건을 셌는지**를 단언할 수 있다. 표본 하한
    (`_MIN_CALIBRATION_SAMPLES`=5)이 있어 6건/8건 구성으로 창 안팎을 가른다.
    """

    # (confidence, is_correct) — 창 안 6건. Brier = mean((conf − outcome)²).
    _IN_WINDOW = [
        (0.9, True),
        (0.8, True),
        (0.7, False),
        (0.6, True),
        (0.5, False),
        (0.4, True),
    ]
    # 창 밖(= 클라 미신고 NULL) 2건 — 시간창 호출에서 빠지고 no-window 호출에는 들어온다.
    _NO_TIME = [(0.3, False), (0.2, True)]

    @staticmethod
    def _brier(pairs: list[tuple[float, bool]]) -> float:
        return sum((conf - (1.0 if ok else 0.0)) ** 2 for conf, ok in pairs) / len(pairs)

    def test_window_counts_only_reported_attempts_and_no_window_is_unchanged(self) -> None:
        _skip_unless_pg()
        uid, pid = uuid.uuid4(), uuid.uuid4()
        base = datetime(2026, 4, 10, 12, 0, tzinfo=UTC)
        since, until = base - timedelta(hours=1), base + timedelta(hours=6)
        try:
            asyncio.run(_add_all(_adult_user(uid), _problem(pid, "ped37-d")))
            client, auth = _client(uid)
            # 창 안 — 발생 시각을 신고하며 제출(엔드포인트 경유·ORM 직접 적재 금지).
            for i, (conf, ok) in enumerate(self._IN_WINDOW):
                resp = client.post(
                    "/v1/me/attempts",
                    headers=auth,
                    json={
                        "problem_id": str(pid),
                        "is_correct": ok,
                        "confidence_self_reported": conf,
                        "started_at": (base + timedelta(minutes=i)).isoformat(),
                    },
                )
                assert resp.status_code == 201, resp.text
            # 미신고 — started_at 없이 제출(NULL 잔존).
            for conf, ok in self._NO_TIME:
                resp = client.post(
                    "/v1/me/attempts",
                    headers=auth,
                    json={
                        "problem_id": str(pid),
                        "is_correct": ok,
                        "confidence_self_reported": conf,
                    },
                )
                assert resp.status_code == 201, resp.text

            windowed = asyncio.run(self._metrics(uid, since=since, until=until))
            unwindowed = asyncio.run(self._metrics(uid, since=None, until=None))

            # ⓐ 시간창 지정 — 수정 전에는 0쌍(NO_DATA)이던 자리. 이제 창 안 6건을 정확히 센다.
            assert windowed.calibration_brier.status is MetricStatus.MEASURED, (
                "시간창 집계가 여전히 0행이다 — started_at writer가 끊겼다: "
                f"{windowed.calibration_brier.note}"
            )
            assert windowed.calibration_brier.value == pytest.approx(self._brier(self._IN_WINDOW))
            assert "6쌍" in windowed.calibration_brier.note

            # ⓑ 미신고(NULL) 2건은 시간창에서 *조용히 빠진다* — 이것이 계약이다(없는 시각을
            #    지어내 창 안으로 끌어들이지 않는다). 8쌍 평균과 값이 달라야 그 사실이 증명된다.
            assert windowed.calibration_brier.value != pytest.approx(
                self._brier(self._IN_WINDOW + self._NO_TIME)
            )

            # ⓒ 회귀 0 — no-window는 started_at 유무와 무관하게 전 8건을 센다(수정 전후 동일).
            assert unwindowed.calibration_brier.status is MetricStatus.MEASURED
            assert unwindowed.calibration_brier.value == pytest.approx(
                self._brier(self._IN_WINDOW + self._NO_TIME)
            )
            assert "8쌍" in unwindowed.calibration_brier.note
        finally:
            asyncio.run(_cleanup(uid, problem_ids=[pid]))

    @staticmethod
    async def _metrics(uid: uuid.UUID, *, since: datetime | None, until: datetime | None) -> object:
        engine = create_async_engine(_settings().database_url)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await compute_wh1_surrogate_metrics(
                    session, user_id=uid, since=since, until=until
                )
        finally:
            await engine.dispose()


# ── ④ 소비자 2: PII 보존기한 파기 — 파기 대상이 실제 행으로 잡힌다 ───────────────────────
class TestRetentionPurge:
    def test_purge_selects_expired_attempts_by_started_at(self) -> None:
        """`_RETENTION_PLAN`의 `(ProblemAttempt, "started_at")`이 실제 행을 센다.

        수정 전에는 이 컬럼이 상시 NULL이라 `started_at < cutoff`가 어떤 행도 고르지 못했고,
        미성년 풀이 데이터의 파기가 **0건**이었다. 창은 다른 테스트의 최근 행을 건드리지 않도록
        아주 먼 과거(2000년대)로 잡는다 — 파기는 user 스코프가 없는 전역 삭제이기 때문이다.
        """
        _skip_unless_pg()
        uid, pid = uuid.uuid4(), uuid.uuid4()
        expired = datetime(2000, 5, 1, 10, 0, tzinfo=UTC)
        try:
            asyncio.run(_add_all(_adult_user(uid), _problem(pid, "ped37-e")))
            client, auth = _client(uid)
            for _ in range(2):
                resp = client.post(
                    "/v1/me/attempts",
                    headers=auth,
                    json={
                        "problem_id": str(pid),
                        "is_correct": True,
                        "started_at": expired.isoformat(),
                    },
                )
                assert resp.status_code == 201, resp.text
            # 미신고 1건 — ingested_at(수신 시각)이 방금이라 COALESCE 폴백도 아직 만료 전이다.
            # (started_at·ingested_at이 *둘 다* 만료돼야 파기 대상이 된다 — 아래 SEC-33 테스트가
            # ingested_at도 오래됐을 때는 파기됨을 별도로 증명한다.)
            resp = client.post(
                "/v1/me/attempts",
                headers=auth,
                json={"problem_id": str(pid), "is_correct": True},
            )
            assert resp.status_code == 201, resp.text
            assert len(asyncio.run(_attempts_of(uid))) == 3

            counts = asyncio.run(self._purge(as_of=date(2005, 1, 1), years=3))
            assert (
                counts["problem_attempt"] == 2
            ), "보존기한 경과 attempt가 파기 대상으로 잡히지 않았다 — started_at이 비어 있다"
            remaining = asyncio.run(_attempts_of(uid))
            assert len(remaining) == 1
            assert remaining[0].started_at is None, "남은 1건은 미신고(NULL) 행이어야 한다"
        finally:
            asyncio.run(_cleanup(uid, problem_ids=[pid]))

    def test_null_started_at_is_still_purged_via_ingested_at_fallback(self) -> None:
        """SEC-33 ① — NULL 회피 재현: 미신고 attempt도 ingested_at이 오래되면 파기된다.

        수정 전(COALESCE 미도입)에는 `started_at`이 NULL인 행은 `ingested_at`이 아무리 오래돼도
        `started_at < cutoff`가 NULL이라 *영원히* 파기 대상에서 빠졌다 — 클라가 발생 시각 신고를
        생략하기만 하면 보존기한을 무기한 회피할 수 있는 통로였다(위 테스트가 고정한 "정직
        스코프"의 반대편 악용). `ingested_at`은 서버가 수신 순간 그대로 채우므로 클라가 조작할
        수 없다 — 여기서는 그 값이 "오래전에 수신됐다"는 상태를 API가 아니라 직접 UPDATE로
        재현한다(API로는 backdate 불가 — 수신 시각은 항상 요청 처리 시점이다).
        """
        _skip_unless_pg()
        uid, pid = uuid.uuid4(), uuid.uuid4()
        old_ingest = datetime(2000, 5, 1, 10, 0, tzinfo=UTC)
        try:
            asyncio.run(_add_all(_adult_user(uid), _problem(pid, "sec33-a")))
            client, auth = _client(uid)
            resp = client.post(
                "/v1/me/attempts",
                headers=auth,
                json={"problem_id": str(pid), "is_correct": True},  # started_at 미신고 → NULL
            )
            assert resp.status_code == 201, resp.text
            attempts = asyncio.run(_attempts_of(uid))
            assert len(attempts) == 1
            assert attempts[0].started_at is None
            asyncio.run(self._backdate_ingested_at(attempts[0].attempt_id, old_ingest))

            counts = asyncio.run(self._purge(as_of=date(2005, 1, 1), years=3))
            assert counts["problem_attempt"] == 1, (
                "미신고(NULL) attempt가 ingested_at 폴백으로도 파기되지 않았다 — "
                "started_at 미신고가 보존기한을 무기한 회피하는 통로로 남아 있다"
            )
            assert asyncio.run(_attempts_of(uid)) == []
        finally:
            asyncio.run(_cleanup(uid, problem_ids=[pid]))

    @staticmethod
    async def _backdate_ingested_at(attempt_id: uuid.UUID, when: datetime) -> None:
        """`ingested_at`을 직접 UPDATE — 서버 전용 컬럼이라 API로는 과거 값을 만들 수 없다."""
        engine = create_async_engine(_settings().database_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text("UPDATE problem_attempt SET ingested_at = :when WHERE attempt_id = :aid"),
                    {"when": when, "aid": str(attempt_id)},
                )
        finally:
            await engine.dispose()

    @staticmethod
    async def _purge(*, as_of: date, years: int) -> dict[str, int]:
        engine = create_async_engine(_settings().database_url)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                counts = await purge_expired_records(session, as_of=as_of, years=years)
                await session.commit()  # commit은 호출자 책임(모듈 계약).
                return counts
        finally:
            await engine.dispose()
