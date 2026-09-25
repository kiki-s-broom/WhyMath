"""S3-03 수능 MVP E2E — 온보딩→수능 다음문항→코치(mode=suneung)→다턴→3-tier verify→측정 관통.

`test_e2e_vertical_slice_integration.py`(기본 CAT 경로)의 *수능 미러*다. 로드맵 목표(수능 완주
경험을 하나의 종단 루프로 조립하고 *수능으로 측정 가능하게*)를 **실 PG**로 한 번에 관통 증명한다:

  온보딩 → `GET /me/next-problem?mode=suneung`(L6 게이팅×IRT CAT) → `POST /coach/sessions`
  (mode=suneung·등호 방정식 solution_steps로 S3-02 방정식 verify 발동) → 다턴(mode=suneung)
  → 3-tier verify(Tier1 verify-answer + Tier2 verify-solution) → `GET /me/harness-metrics?mode=
  suneung`(수능 세션 검산 이벤트가 측정 계층에 mode-scoped로 도달했는지 확인).

핵심 원칙(기본 E2E와 동일):
- **mock LLM(코치 LLM 0)** — `/coach/sessions`는 `decision.prompt`를 AI 턴에 저장할 뿐 실 LLM
  호출 0. shadow·의미 매처·judge는 전부 기본 off(config 기본값)라 결정론 경로만 관통한다.
- **실 PG** — `get_session`은 오버라이드하지 않는다(라이브 PG). `get_settings`만 테스트 Settings로
  덮어 jwt 시크릿을 mint·검증에 공유한다. 인증은 실 JWT 발급.
- **성인 유저** — ConsentedUser(미성년 동의) 게이트를 우회하려 성인 birth_year로 시딩(동의 불요).

발명 금지: 엔드포인트가 *실제 반환하는 것만* assert한다. 코칭 텍스트는 정밀 검증하지 않고 status
code + 핵심 필드 존재/타입/불변식(answer 비노출·verify 신호·mode 태깅·측정 반영)에 집중한다.

측정 가능성(핵심 신규 assert): 수능 세션(mode=suneung)과 *일반* 세션(mode 미지정)을 둘 다 만든 뒤,
`GET /me/harness-metrics?mode=suneung`의 검산 표본이 mode 무필터 표본보다 *적음*(수능만 걸러짐)을
assert해 "데이터가 mode를 실어나르고, 그 데이터를 mode-scope할 수 있다"를 증명한다.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from whymath_backend.app import create_app
from whymath_backend.config import Settings, get_settings
from whymath_backend.consent import current_year_kst, derive_is_minor
from whymath_backend.db.models.problem import Problem
from whymath_backend.db.models.user import UserProfile
from whymath_backend.schema.enums import (
    Curriculum,
    Persona,
    ReviewStatus,
    Role,
    SignaturePattern,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem import Problem as ProblemSchema
from whymath_backend.schema.user import UserProfile as UserProfileSchema
from whymath_backend.security import create_access_token

pytestmark = pytest.mark.integration

_SECRET = "integration-jwt-secret-suneung-0123456789ab"

# 코치 응답에 정답이 새는지 검사할 sentinel — 시딩 Problem.answer에 심고, 코치 응답 어디에도
# 등장하지 않아야 한다(학생 대면 코칭은 정답을 미룬다·CLAUDE.md).
_ANSWER_SENTINEL = "SUNEUNG_ANSWER_SENTINEL_DONOTLEAK"

# 등호 방정식 단계 시퀀스 — 2x+3=7(해 x=2) → 2x=3(해 x=1.5)로 *해집합 비보존*이라 S3-02
# 방정식 verify(solution_set_status)가 incorrect로 판정한다(표현식 동치가 아닌 방정식 변형·방향 B).
_EQUATION_STEPS = ["2*x + 3 = 7", "2*x = 3"]
# 텍스트 레벨 거짓 등식 — arithmetic_error를 확정적으로 켜 solution_coaching·검산결과 이벤트를
# 보장한다(단계 신호와 OR 결합·검산결과 event_data에 mode=suneung이 실린다).
_FALSE_ARITHMETIC = "계산하면 2 + 3 = 6 이므로 답은 6"


def _settings() -> Settings:
    """테스트 Settings — jwt 시크릿만 고정. database_url은 WHYMATH_DATABASE_URL 환경변수 소싱."""
    return Settings(jwt_secret_key=SecretStr(_SECRET))


async def _pg_reachable() -> bool:
    """실 PG 도달 가능 여부 — 미도달이면 통합 테스트를 skip한다(WHYMATH_DATABASE_URL 확인)."""
    engine = create_async_engine(_settings().database_url)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


async def _add_adult_user(uid: uuid.UUID, *, birth_year: int) -> None:
    """성인 유저 시딩 — is_minor=False로 ConsentedUser 게이트 통과(동의 불요·미성년 회피).

    SEC-24(원 SEC-13): 이 유저가 흐름 끝에서 `/v1/me/harness-metrics`(RequireContentAdmin)도 호출하므로
    role=CONTENT_ADMIN으로 시드한다 — role은 그 라우트 게이트 외 학습 흐름 어디에도 영향 없다.
    """
    engine = create_async_engine(_settings().database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(
                UserProfile.from_schema(
                    UserProfileSchema(
                        user_id=uid,
                        persona_primary=Persona.A_일반고고3,
                        birth_year=birth_year,
                        is_minor=False,
                        role=Role.CONTENT_ADMIN,
                    )
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


async def _add_all(*objs: object) -> None:
    """ORM 객체들을 독립 엔진으로 한 트랜잭션에 적재한다(시딩 헬퍼)."""
    engine = create_async_engine(_settings().database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add_all(list(objs))
            await session.commit()
    finally:
        await engine.dispose()


def _suneung_problem(pid: uuid.UUID, suffix: str) -> Problem:
    """수능 적격 자체생성 문항 — signature_patterns 보유(수능 신호)·answer sentinel·난이도 라벨.

    자체생성(본문 보유 허용·노출 가능 source)이라 저작권 게이트를 통과하고, signature_patterns가
    비어 있지 않아 `is_suneung_eligible`의 수능 적합 신호(b)를 충족한다. difficulty_overall로
    next-problem CAT 후보(θ 근방·b 폴백)가 될 수 있게 한다.
    """
    return Problem.from_schema(
        ProblemSchema(
            problem_id=pid,
            source_type=SourceType.자체생성,
            # PB-03 — 검수 노출 게이트(`is_review_cleared`) 추가로 approved가 필요.
            review_status=ReviewStatus.approved,
            curriculum_version=Curriculum.REVISION_2022,
            valid_from_year=2022,
            subject=Subject.공통,
            unit_codes=[f"U-suneung-{suffix}"],
            difficulty_overall=3.0,
            signature_patterns=[SignaturePattern.COMPOUND_CHOICES],  # 수능 시그니처 신호
            answer=_ANSWER_SENTINEL,
        )
    )


def _plain_problem(pid: uuid.UUID, suffix: str) -> Problem:
    """일반(비수능) 자체생성 문항 — mode 미지정 세션의 검산 이벤트 원천(mode 필터 대조군)."""
    return Problem.from_schema(
        ProblemSchema(
            problem_id=pid,
            source_type=SourceType.자체생성,
            # PB-03 — 기본 CAT SQL도 review_status=approved만 후보(축②)라 필요.
            review_status=ReviewStatus.approved,
            curriculum_version=Curriculum.REVISION_2022,
            valid_from_year=2022,
            subject=Subject.공통,
            unit_codes=[f"U-plain-{suffix}"],
            difficulty_overall=3.0,
            answer=_ANSWER_SENTINEL,
        )
    )


async def _cleanup(
    uid: uuid.UUID,
    *,
    problem_ids: list[uuid.UUID],
    dialogue_ids: list[uuid.UUID],
) -> None:
    """FK 안전 순서 정리 — 자식부터 부모로."""
    engine = create_async_engine(_settings().database_url)
    dids = [str(d) for d in dialogue_ids]
    pids = [str(p) for p in problem_ids]
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM dialogue_turn WHERE dialogue_id = ANY(:ids)"),
                {"ids": dids},
            )
            await conn.execute(
                text("DELETE FROM attempt_event WHERE user_id = :uid"),
                {"uid": str(uid)},
            )
            await conn.execute(
                text("DELETE FROM misconception_hypothesis WHERE user_id = :uid"),
                {"uid": str(uid)},
            )
            await conn.execute(
                text("DELETE FROM dialogue WHERE dialogue_id = ANY(:ids)"),
                {"ids": dids},
            )
            await conn.execute(
                text("DELETE FROM problem WHERE problem_id = ANY(:ids)"), {"ids": pids}
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


def _client() -> TestClient:
    """실 PG 클라이언트 — get_settings만 오버라이드(jwt 공유)·get_session은 라이브 PG."""
    app = create_app()
    app.dependency_overrides[get_settings] = _settings
    return TestClient(app)


def test_suneung_loop_onboarding_to_measurement_on_live_pg() -> None:
    """수능 완주 루프를 실 PG로 관통 — 다음문항·코치(mode)·3-tier verify·mode-scoped 측정 증명.

    acceptance(S3-03): API 루프 종단 + 수능 세션이 측정 가능(mode 태깅·지표 반영).
    """
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀 (WHYMATH_DATABASE_URL 확인)")

    uid = uuid.uuid4()
    sfx = uid.hex[:8]
    suneung_pid = uuid.uuid4()
    plain_pid = uuid.uuid4()
    dialogue_ids: list[uuid.UUID] = []
    birth_year = 2000  # 성인(2026 기준 연나이 26 > 14) → is_minor 서버파생 False 기대.

    try:
        # ── 시딩: 성인 유저 + 수능 적격 문항 + 일반 문항(mode 필터 대조군) ──────────────
        asyncio.run(_add_adult_user(uid, birth_year=birth_year))
        asyncio.run(_add_all(_suneung_problem(suneung_pid, sfx)))
        asyncio.run(_add_all(_plain_problem(plain_pid, sfx)))

        token = create_access_token(uid, settings=_settings())
        auth = {"Authorization": f"Bearer {token}"}
        with _client() as client:
            # ── 1) 온보딩: GET → ETag → PATCH 프로필(is_minor 서버파생 실증) ────────────
            me0 = client.get("/v1/users/me", headers=auth)
            assert me0.status_code == 200, me0.text
            etag = me0.headers["ETag"]
            patched = client.patch(
                "/v1/users/me",
                headers={**auth, "If-Match": etag},
                json={"target_grade": 3, "birth_year": birth_year},
            )
            assert patched.status_code == 200, patched.text
            expected_is_minor = derive_is_minor(
                birth_year,
                current_year=current_year_kst(),
                threshold=_settings().minor_consent_age,
            )
            assert patched.json()["is_minor"] == expected_is_minor  # 성인 → False.

            # ── 2) 수능 다음문항: GET /me/next-problem?mode=suneung ────────────────────
            nxt = client.get(
                "/v1/me/next-problem",
                headers=auth,
                params={"mode": "suneung", "persona": Persona.A_일반고고3.value},
            )
            assert nxt.status_code == 200, nxt.text
            nbody = nxt.json()
            # 수능 적격 후보가 시드돼 있으므로 추천 문항이 나온다(L6 게이팅×IRT CAT 종단).
            assert nbody["problem_id"] is not None, "수능 적격 후보 시드 → 추천 문항 존재"
            assert isinstance(nbody["theta"], (int, float))
            assert isinstance(nbody["measurement_sufficient"], bool)

            # ── 3) 코치 세션(mode=suneung) — 등호 방정식 solution_steps로 S3-02 verify 발동 ─
            create = client.post(
                "/v1/coach/sessions",
                headers=auth,
                json={
                    "student_input": "이 수능 문제 이렇게 풀었는데 확인해줘",
                    "student_solution": _FALSE_ARITHMETIC,  # 거짓 등식 → 검산결과 이벤트
                    "problem_id": str(suneung_pid),
                    "solution_steps": _EQUATION_STEPS,  # 방정식 해집합 비보존 → S3-02 incorrect
                    "solution_step_types": ["계산"],  # 전이 1개(=len(steps)-1)
                    "mode": "suneung",
                    "persona": Persona.A_일반고고3.value,
                },
            )
            assert create.status_code == 201, create.text
            cbody = create.json()
            did = uuid.UUID(cbody["dialogue_id"])
            dialogue_ids.append(did)

            # S3-02 방정식 verify 신호 — solution_verification(등호 방정식 단계 검증 집계).
            sol = cbody["solution_coaching"]
            assert sol is not None, "거짓 등식+방정식 단계 → solution_coaching 노출"
            sv = sol["solution_verification"]
            assert sv is not None, "solution_steps 제공 → solution_verification 채워짐"
            assert sv["has_incorrect"] is True  # 방정식 해집합 비보존(S3-02)
            assert cbody["wh1_turn_index"] == 1

            # 불변식: answer 비노출 — sentinel이 코치 응답 어디에도 없음.
            assert _ANSWER_SENTINEL not in create.text
            assert _ANSWER_SENTINEL not in json.dumps(cbody, ensure_ascii=False)

            # ── 4) 다턴(mode=suneung) — 후속 턴도 mode 태그를 실어 보낸다 ─────────────────
            turn = client.post(
                f"/v1/coach/sessions/{did}/turns",
                headers=auth,
                json={"student_input": "여기서부터 잘 모르겠어", "mode": "suneung"},
            )
            assert turn.status_code == 201, turn.text
            assert turn.json()["wh1_turn_index"] > cbody["wh1_turn_index"]

            # ── 5) 3-tier verify: Tier2(verify-solution) + Tier1(verify-answer) ────────
            vsol = client.post(
                "/v1/verify-solution",
                headers=auth,
                json={"steps": _EQUATION_STEPS, "step_types": ["계산"]},
            )
            assert vsol.status_code == 200, vsol.text
            vsbody = vsol.json()
            assert vsbody["has_incorrect"] is True  # 코치 내부 신호와 독립 verify 정합
            assert vsbody["first_incorrect_index"] == sv["first_incorrect_index"]

            vans = client.post(
                "/v1/verify-answer",
                headers=auth,
                json={"conditions": "2*x + 3 = 7", "answer": {"x": "2"}},
            )
            assert vans.status_code == 200, vans.text
            assert vans.json()["state"] == "pass"  # x=2 → 2*2+3=7 (Tier1 수치 검산)

            # ── 6) 일반(mode 미지정) 세션 — mode 필터 대조군(검산 이벤트 mode=None) ──────
            plain = client.post(
                "/v1/coach/sessions",
                headers=auth,
                json={
                    "student_input": "일반 문제도 확인",
                    "student_solution": _FALSE_ARITHMETIC,
                    "problem_id": str(plain_pid),
                    # mode 미지정 → 검산 이벤트 event_data.mode=None(mode-agnostic).
                },
            )
            assert plain.status_code == 201, plain.text
            dialogue_ids.append(uuid.UUID(plain.json()["dialogue_id"]))

            # ── 7) 측정 가능성: harness-metrics의 mode-scoped 집계가 수능만 걸러낸다 ───────
            m_all = client.get("/v1/me/harness-metrics", headers=auth)
            assert m_all.status_code == 200, m_all.text
            all_body = m_all.json()
            m_suneung = client.get(
                "/v1/me/harness-metrics", headers=auth, params={"mode": "suneung"}
            )
            assert m_suneung.status_code == 200, m_suneung.text
            su_body = m_suneung.json()

            # 수능 세션 검산 이벤트가 측정 계층에 mode-scoped로 도달했다(지표 반영).
            assert su_body["mode_filter"] == "suneung"
            assert su_body["sample_verify_events"] >= 1  # 수능 검산 1건 이상
            assert su_body["verify_pass_rate"]["status"] == "measured"
            # mode 필터가 *일반* 세션 검산을 배제한다 — 수능(1) < 전체(수능+일반=2).
            assert su_body["sample_verify_events"] < all_body["sample_verify_events"]
    finally:
        # ── FK 안전 순서 정리 ─────────────────────────────────────────────────────────
        asyncio.run(
            _cleanup(
                uid,
                problem_ids=[suneung_pid, plain_pid],
                dialogue_ids=dialogue_ids,
            )
        )
