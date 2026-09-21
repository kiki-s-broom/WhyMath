"""S1 E2E 수직 슬라이스 *통합 증명* 하니스 — 온보딩→진단→문제→풀이→코치→verify→완료→추천 갱신
(기본 SKIP).

로드맵 최대 병목(#3 "온보딩→진단→문제→풀이→코치→verify 루프가 끝까지 관통·실증된 적 없음")을
**실 PG**로 한 번에 관통해 증명하고, 라이브 LLM 키 투입 *전*의 회귀 앵커를 만든다.

**EOS-81 연장(루프 닫힘)**: verify에서 끝나던 관통을 *뒤로* 연장해 학습 루프가 실제로 닫히는지를
같은 테스트 안에서 순서대로 증명한다 — (가) 코치 완료 경로(2턴: 정답 제출→돌아보기 응답)가
attempt를 적재하고 완료 신호를 응답에 싣는다 → (나) 그 attempt가 실제로 영속된다(응답의
`completed_attempt_id`로 DB를 직접 조회) → (다) 개념 축·스킬 축 숙달이 *값으로* 변한다(완료 전후
비교) → (라) 후속 추천이 갱신된 학습자 상태를 반영한다(완료 전/후 `GET /v1/me/next-problem` 대조).
"API 200"은 완료 조건이 아니다 — 각 단계의 *산출물 자체*(응답 필드 값·DB 행·숙달 델타·추천 변화)를
단언한다.

**부분 쓰기를 정상으로 읽지 않는다**(EOS-81 ⑦): `_complete_problem`은 attempt를 먼저 commit하고
개념 숙달·스킬 숙달·`문제시도` 이벤트를 *각자* commit한다(`l2/attempt_skill_event.py`가 교차
원자성 미해결을 자인). 그래서 아래 관측은 네 축을 **개별 단언**한다 — "attempt만 남고 숙달은
그대로"인 상태는 통과하지 못한다.

**LearningSession 축은 이 관통이 지나가지 않는다(정직한 공백·기계 집행 없음)**: `learning_session`
스키마(`schema/activity.py` §6.1 DDL)는 정본화됐으나 **writer가 0**이고(`src/` 전체에서
`LearningSession(...)` 생성 0건 — `harness/surrogate_baseline_report.py:142`가 같은 실측을 기록),
`l2/recommendation_evidence.py:109`는 `session_id`를 매 호출 `uuid.uuid4()` placeholder로 발급한다.
`_complete_problem`도 `ProblemAttempt.session_id`를 채우지 않는다. 게다가 그 writer는 *미완*이
아니라 **영구 미신설이 결정된 좌석**이다(`S3-16` acceptance ③ — MEMORY 2026-08-11 기록:
"`S3-16`이 영구 미신설을 결정"). 그러므로 이 테스트는 세션 축을 배선하지 않고 그 공백을 *기계로
고정*만 한다(아래 `session_id is None` 단언) — 이 관통에 세션 축의 **기계 집행은 없다**.

핵심 원칙:

- **mock LLM(코치 LLM 0)** — `/v1/coach/sessions`는 `decision.prompt`를 AI 턴 content로 저장할
  뿐 실제 LLM을 호출하지 않는다(coach.py 모듈 docstring 계약). shadow 하네스·의미 매처·judge는
  *전부 기본 off*(config 기본값)라 실 임베딩 provider 의존이 없다 — 결정론 경로만 관통한다.
- **실 PG** — `get_session`은 오버라이드하지 않는다(라이브 PG). `get_settings`만 테스트 Settings로
  덮어 jwt 시크릿을 mint·검증에 공유한다(기존 통합테스트 패턴 답습). 인증은 실 JWT 발급.
- **성인 유저** — ConsentedUser(미성년 동의) 게이트를 우회하려 *성인* birth_year로 시딩한다
  (동의 불요). `parental_consent`·shadow 플래그는 켜지 않는다.

발명 금지: 엔드포인트가 *실제 반환하는 것만* assert한다. 코칭 텍스트는 정밀 검증하지 않고
status code + 핵심 필드 존재/타입/불변식(answer 비노출·verify 신호·턴 영속·is_minor 서버파생)에
집중한다. 불확실하면 관대하게(존재/타입) assert한다.

베이스: `test_coach_integration.py`의 실 PG 픽스처·시딩 헬퍼 패턴을 *동형 복제*한다(각 통합
테스트 모듈이 `_settings`·`_pg_reachable` 등을 독립 정의하는 선례 — 모듈 간 test import 이중
수집 회피). FK 안전 순서 정리는 try/finally로 보장한다.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Select, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from whymath_backend.api._rate_limit import reset_store
from whymath_backend.api.me import _CANDIDATE_POOL_SIZE
from whymath_backend.app import create_app
from whymath_backend.config import Settings, get_settings
from whymath_backend.consent import current_year_kst, derive_is_minor
from whymath_backend.db.models.activity import AttemptEvent, ProblemAttempt
from whymath_backend.db.models.assessment import ConceptMasteryHistory, SkillMasteryHistory
from whymath_backend.db.models.atom_node import AtomNode
from whymath_backend.db.models.concept import Concept, ConceptEdge, ProblemConcept
from whymath_backend.db.models.problem import Problem
from whymath_backend.db.models.skill_node import SKILL_REVIEW_STATUS_DEFAULT, SkillNode
from whymath_backend.db.models.user import UserProfile
from whymath_backend.l2.attempt_skill_event import AttemptSource
from whymath_backend.schema.assessment import (
    ConceptMasteryHistory as ConceptMasteryHistorySchema,
)
from whymath_backend.schema.concept import Concept as ConceptSchema
from whymath_backend.schema.concept import ProblemConcept as ProblemConceptSchema
from whymath_backend.schema.enums import (
    BehaviorArea,
    ConceptLevel,
    ConceptRole,
    Curriculum,
    EdgeType,
    EventType,
    MajorCategory,
    Persona,
    ReviewStatus,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem import Problem as ProblemSchema
from whymath_backend.schema.user import UserProfile as UserProfileSchema
from whymath_backend.security import create_access_token

pytestmark = pytest.mark.integration

_SECRET = "integration-jwt-secret-0123456789abcdef"

# 코치 응답에 정답이 새는지 검사할 sentinel — 시딩 Problem.answer에 심고, 코치 응답 어디에도
# 등장하지 않아야 한다(학생 대면 코칭은 정답을 미룬다·CLAUDE.md·test_coach.py answer 비노출 패턴).
_ANSWER_SENTINEL = "ANSWER_SENTINEL_DONOTLEAK"

# 단계 자가검산 유발 시퀀스 — 분배법칙 오류 전이(2*(x+3) ≠ 2*x+3)라 verify_step이 incorrect로
# 판정한다(대수 비동치·SymPy 결정론). first_incorrect_index=0·has_incorrect=True를 낳는다.
_BAD_STEPS = ["2*(x+3)", "2*x+3"]
# 텍스트 레벨 거짓 등식 — arithmetic_error를 확정적으로 켜 solution_coaching 노출을 보장한다
# (단계 신호와 OR 결합·둘 다 verify 신호이므로 관통 증명이 견고해진다).
_FALSE_ARITHMETIC = "2 + 3 = 6 이므로 답은 6"

# ── EOS-81 완료 루프(관통 뒷구간) 상수 ─────────────────────────────────────────────────
# 완료 문항의 기대정답 — `verify_final_answer`가 **결정론적으로 correct**를 낼 수 있어야 하므로
# 값 해집합으로 읽히는 수치를 쓴다(위 `_ANSWER_SENTINEL`은 값으로 파싱되지 않는 문자열이라 정답
# 판정 입력으로 못 쓴다 — sentinel은 '정답 비노출' 검사 전용이다). 코칭 보일러플레이트와 우연히
# 겹치지 않도록 특이한 수를 고른다(`test_coach_completion.py`의 "77129" 선례와 동형).
_COMPLETION_ANSWER = "70414"
# 턴 A(정답 제출)의 풀이 단계 — 마지막 단계가 기대정답과 동치라 서버가 correct로 판정한다.
# 전이(2x=140828 → x=70414)도 실제로 동치라 단계 검증 신호와 모순되지 않는다.
_CORRECT_STEPS = ["2*x = 140828", f"x = {_COMPLETION_ANSWER}"]
# 시드 숙달 기준선 — 완료 전후 *값 델타*를 비교하기 위한 before 값(둘 다 첫 관측이 아니게 만든다).
_SEED_CONCEPT_MASTERY = 0.35
_SEED_SKILL_MASTERY = 0.30


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
    """성인 유저 시딩 — is_minor=False로 ConsentedUser 게이트를 통과(동의 불요·미성년 회피).

    birth_year는 성인 연나이가 되도록 호출자가 넘긴다(예: 2000 → 2026 기준 연나이 26).
    is_minor는 시딩 시 False로 두되, 이후 온보딩 PATCH가 birth_year에서 *서버 파생*으로 덮어쓴다
    (derive_is_minor 단일 진실 — 이 관통이 그 파생을 실증한다).
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


def _concept_with_code(
    cid: uuid.UUID, code: str, name: str, *, behavior_skills: list[str] | None = None
) -> Concept:
    """개념 시딩 — `behavior_skills`는 런타임 concept→skill 브리지(스킬 숙달 해소의 조인 백킹).

    EOS-81: 스킬 축 숙달 전파(`record_problem_attempt_skill_mastery`)는 `Concept.behavior_skills`
    ∩ `skill_node`(mastery_estimable=True)로 스킬을 해소하므로, 그 축이 실제로 움직이는지 보려면
    개념에 브리지를, DB에 스킬 메타 행을 함께 심어야 한다(`l2/skill_mastery_tracking.py`
    `_assessed_skill_ids`).
    """
    return Concept.from_schema(
        ConceptSchema(
            concept_id=cid,
            code=code,
            name_ko=name,
            level=ConceptLevel.세부개념,
            behavior_skills=behavior_skills or [],
        )
    )


def _skill_node(skill_id: str, name_ko: str) -> SkillNode:
    """스킬 메타 행 — `mastery_estimable=True`라야 숙달 해소 대상이 된다(추정 가치 게이트)."""
    return SkillNode(
        skill_id=skill_id,
        name_ko=name_ko,
        behavior_area=BehaviorArea.COMPUTE,
        family="e2e",
        mastery_estimable=True,
        review_status=SKILL_REVIEW_STATUS_DEFAULT,  # NOT NULL(서버 기본값 없음) — 명시 지정.
    )


def _skill_mastery_row(
    uid: uuid.UUID, skill_id: str, measured_at: datetime, mastery: float
) -> SkillMasteryHistory:
    """스킬 축 숙달 시드(before 값) — 완료 후 델타를 *값으로* 비교하기 위한 기준선."""
    return SkillMasteryHistory(
        user_id=uid,
        skill_id=skill_id,
        measured_at=measured_at,
        mastery=mastery,
        confidence=0.5,
        sample_size=1,
    )


def _node_meta(uc: str, name_ko: str, domain: str, review_status: str) -> AtomNode:
    """원자 축 안전 메타 행(code PK) — S0-4d로 enrich가 `atom_node`로 전환됐다(ARCH-13 정렬).

    이 좌석은 원래 구 437 `concept_node`에 시드했다. 그 테이블은 런타임에서 읽히지 않으므로
    "막힌 선수(선수 복습 코칭 신호 유발)"라는 이 픽스처의 *선언된 의도*가 실제로는 달성되지
    않은 채 통과하고 있었다(축 울타리 이전에는 축이 어긋나도 행이 그냥 흘렀다). 원자 축으로
    시드해 관통 슬라이스가 실제로 선수 경로를 지나가게 한다.
    `test_me_integration.py`·`test_coach_integration.py`의 같은 이름 헬퍼와 동형.
    """
    return AtomNode(
        code=uc,
        name_ko=name_ko,
        level="세부개념",
        subject_area=domain,
        review_status=review_status,
    )


def _prereq_edge(from_id: uuid.UUID, to_id: uuid.UUID, strength: float) -> ConceptEdge:
    """선수 엣지 — from(선수)이 to(후행)의 선수(PREREQUISITE)."""
    return ConceptEdge(
        from_concept_id=from_id,
        to_concept_id=to_id,
        edge_type=EdgeType.PREREQUISITE.value,
        edge_strength=strength,
    )


def _mastery_row(
    uid: uuid.UUID, cid: uuid.UUID, measured_at: datetime, mastery: float
) -> ConceptMasteryHistory:
    return ConceptMasteryHistory.from_schema(
        ConceptMasteryHistorySchema(
            user_id=uid,
            concept_id=cid,
            measured_at=measured_at,
            mastery=mastery,
            sample_size=1,
        )
    )


def _problem_with_answer(pid: uuid.UUID, suffix: str, *, answer: str = _ANSWER_SENTINEL) -> Problem:
    """자체생성 문제 — 기본값은 answer에 sentinel을 심는다(코치 응답 정답 비노출 검사용).

    source_type=자체생성은 본문 보유 금지 불변식({평가원,EBS,교과서}) 대상이 아니라 answer를
    가질 수 있다. difficulty_overall을 채워 next-problem(CAT) 후보가 될 수 있게 한다.

    EOS-81: `answer`를 인자로 연 이유는 완료 루프 구간이 *서버가 correct로 판정 가능한* 기대정답
    (수치)을 요구하기 때문이다 — sentinel 문자열은 값 해집합으로 파싱되지 않아 완료 트리거가 될 수
    없다. 기본값은 그대로라 기존 좌석(정답 비노출 검사)은 무변경이다.
    """
    return Problem.from_schema(
        ProblemSchema(
            problem_id=pid,
            source_type=SourceType.자체생성,
            # PB-03 — 기본 CAT SQL도 review_status=approved만 후보(축②)라 필요.
            review_status=ReviewStatus.approved,
            curriculum_version=Curriculum.REVISION_2022,
            valid_from_year=2022,
            subject=Subject.공통,
            unit_codes=[f"U-{suffix}"],
            difficulty_overall=3.0,
            answer=answer,
        )
    )


def _problem_concept(pid: uuid.UUID, cid: uuid.UUID) -> ProblemConcept:
    return ProblemConcept.from_schema(
        ProblemConceptSchema(problem_id=pid, concept_id=cid, role=ConceptRole.PRIMARY)
    )


async def _fetch_all(stmt: Select[Any]) -> list[Any]:
    """독립 엔진으로 쿼리빌더 SELECT를 실행해 ORM 행 목록을 돌려준다(관측 전용·읽기).

    EOS-81 관측은 "응답이 200이었다"가 아니라 *DB에 무엇이 남았는가*를 본다 — 응답이 준
    `completed_attempt_id`로 `problem_attempt`를 실제로 SELECT하고, 숙달 시계열의 값을 직접 읽어
    완료 전후를 비교한다. 원시 SQL 대신 ORM/쿼리빌더를 쓴다(CLAUDE.md "원시 SQL 최소화" — 정리
    구문만 예외적으로 text()를 쓰는 기존 `_cleanup` 관례는 그대로 둔다).
    """
    engine = create_async_engine(_settings().database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())
    finally:
        await engine.dispose()


async def _latest_concept_mastery(uid: uuid.UUID, cid: uuid.UUID) -> float | None:
    """(user, concept) 최신 숙달값 — 없으면 None. 개념 축 델타 비교의 관측기."""
    rows = await _fetch_all(
        select(ConceptMasteryHistory)
        .where(
            ConceptMasteryHistory.user_id == uid,
            ConceptMasteryHistory.concept_id == cid,
        )
        .order_by(ConceptMasteryHistory.measured_at.desc())
        .limit(1)
    )
    return float(rows[0].mastery) if rows and rows[0].mastery is not None else None


async def _latest_skill_mastery(uid: uuid.UUID, skill_id: str) -> float | None:
    """(user, skill) 최신 숙달값 — 없으면 None. 스킬 축 델타 비교의 관측기."""
    rows = await _fetch_all(
        select(SkillMasteryHistory)
        .where(
            SkillMasteryHistory.user_id == uid,
            SkillMasteryHistory.skill_id == skill_id,
        )
        .order_by(SkillMasteryHistory.measured_at.desc())
        .limit(1)
    )
    return float(rows[0].mastery) if rows and rows[0].mastery is not None else None


async def _fetch_attempts(uid: uuid.UUID) -> list[ProblemAttempt]:
    """이 유저의 `problem_attempt` 전 행 — 적재 실재·중복 0 관측."""
    return await _fetch_all(
        select(ProblemAttempt)
        .where(ProblemAttempt.user_id == uid)
        .order_by(ProblemAttempt.ended_at)
    )


async def _fetch_completion_events(attempt_id: uuid.UUID) -> list[AttemptEvent]:
    """이 attempt의 `문제시도` 이벤트 — 스킬 배열 영속(EOS-57 writer) 도달 관측."""
    return await _fetch_all(
        select(AttemptEvent).where(
            AttemptEvent.attempt_id == attempt_id,
            AttemptEvent.event_type == EventType.문제시도,
        )
    )


async def _cleanup(
    uid: uuid.UUID,
    *,
    problem_ids: list[uuid.UUID],
    concept_ids: list[uuid.UUID],
    uc_ids: list[str],
    dialogue_ids: list[uuid.UUID],
    skill_ids: list[str] | None = None,
) -> None:
    """FK 안전 순서 정리 — 자식부터 부모로:
    dialogue_turn→attempt_event→misconception_hypothesis→dialogue→problem_attempt→
    problem_concept→concept_edge→concept_mastery_history→skill_mastery_history→skill_node→
    atom_node→problem→concept→user_profile.

    EOS-81 추가분: 완료 경로가 적재하는 `problem_attempt`(problem·user_profile의 자식·dialogue가
    `ON DELETE SET NULL`로 참조)와 스킬 축 좌석(`skill_mastery_history`·`skill_node`)을 함께
    정리한다. 남기면 다음 실행의 "완료 전 attempt 0" 기준선이 깨진다.
    """
    engine = create_async_engine(_settings().database_url)
    dids = [str(d) for d in dialogue_ids]
    pids = [str(p) for p in problem_ids]
    cids = [str(c) for c in concept_ids]
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
            # 완료 경로 적재분 — dialogue(SET NULL) 정리 뒤·problem/user 정리 앞에 지운다.
            await conn.execute(
                text("DELETE FROM problem_attempt WHERE user_id = :uid"),
                {"uid": str(uid)},
            )
            await conn.execute(
                text("DELETE FROM problem_concept WHERE problem_id = ANY(:ids)"),
                {"ids": pids},
            )
            await conn.execute(
                text("DELETE FROM concept_edge WHERE from_concept_id = ANY(:ids)"),
                {"ids": cids},
            )
            await conn.execute(
                text("DELETE FROM concept_mastery_history WHERE user_id = :uid"),
                {"uid": str(uid)},
            )
            await conn.execute(
                text("DELETE FROM skill_mastery_history WHERE user_id = :uid"),
                {"uid": str(uid)},
            )
            await conn.execute(
                text("DELETE FROM skill_node WHERE skill_id = ANY(:ids)"),
                {"ids": list(skill_ids or [])},
            )
            # atom_node PK는 code(=concept.code=UC 브리지 키)라 code 컬럼으로 정리한다(ARCH-13).
            await conn.execute(
                text("DELETE FROM atom_node WHERE code = ANY(:ids)"),
                {"ids": uc_ids},
            )
            await conn.execute(
                text("DELETE FROM problem WHERE problem_id = ANY(:ids)"), {"ids": pids}
            )
            await conn.execute(
                text("DELETE FROM concept WHERE concept_id = ANY(:ids)"), {"ids": cids}
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


def test_full_loop_onboarding_to_verify_on_live_pg() -> None:
    """온보딩→진단→문제→풀이+코치→다턴→3-tier verify→**완료→숙달→추천 갱신**을 한 번에 관통 증명.

    앞 구간(1~6)은 status code + 핵심 필드 존재/타입/불변식만 검증한다(코칭 텍스트 비정밀 assert).
    불변식: is_minor 서버파생·answer 비노출·verify 신호(코치↔독립 verify 정합)·턴 영속.

    뒤 구간(7~11·EOS-81)은 루프가 *닫히는지*를 산출물로 증명한다:
      (가) 코치 완료 경로 2턴(정답 제출 → 돌아보기 응답) → 응답에 `problem_complete=True`·
           `completed_attempt_id`.
      (나) 그 attempt_id로 `problem_attempt`를 직접 SELECT — 행 실재·서버 권위 `is_correct=True`·
           `used_socratic=True`·중복 0.
      (다) 개념 축(`concept_mastery_history`)·스킬 축(`skill_mastery_history`) 숙달이 완료 전
           시드값보다 **커진다**(값 델타). 두 축은 서로 다른 commit이라 따로 단언한다(부분 쓰기
           통과 금지) — `문제시도` 이벤트(EOS-57 writer·또 다른 commit)도 별도로 관측한다.
      (라) 후속 추천(`GET /v1/me/next-problem`)이 갱신된 상태를 반영한다 — 완료 문항이 후보에서
           빠지고(미시도 필터), 채점 이력이 생겨 θ 표준오차가 산출된다(완료 전엔 콜드스타트라
           None). *정직한 공백*: 개념 BKT 숙달 **값**이 추천 점수에 얼마나 기여했는지는 API가
           수치로 노출하지 않는다(`weak_concept_signal_count`는 신호 *유무* 카운트라 값 변화에
           변별력이 없다) — 그래서 값 델타는 (다)에서 DB로 직접 단언하고, 여기서는 가중 축이
           실제로 적용됐다는 사실(`weight_axes_applied`)까지만 단언한다.

    **LearningSession 축은 관통하지 않는다**(모듈 docstring 참조·기계 집행 없음): writer가 0이라
    `problem_attempt.session_id`는 NULL로 남는다 — 그 사실 자체를 단언해 공백을 동결한다.
    """
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀 (WHYMATH_DATABASE_URL 확인)")

    # 레이트리미터 격리 — 인메모리 백엔드(`_rate_limit._BACKEND`)는 *프로세스 전역*이고 앱마다
    # 새로 설치되지 않는다(lifespan 호출 0건 실측). 같은 pytest 프로세스에서 앞서 돈 통합
    # 테스트(test_coach_integration 세션 생성 20건 등)가 IP 버킷(`ip:testclient`·write 60/분)을
    # 소진하면, 이 테스트의 두 번째 세션 생성이 429를 받는다 — pytest-randomly 순서에 따라
    # 재현되는 순서 의존 오염이다(CI run 34024961969 실측: 07:29 green → 09:39 red, 같은 코드).
    # 이 테스트는 폐쇄루프를 증명하는 자리이지 한도 계약을 재는 자리가 아니므로(그건
    # test_rate_limit_integration 몫) 시작 시 카운트를 비운다 — test_coach.py 등과 같은 관용.
    asyncio.run(reset_store())

    uid = uuid.uuid4()
    sfx = uid.hex[:8]
    # 개념 그래프 — 문제 개념 C(후행)와 그 막힌 선수 P(선수 복습 코칭 신호 유발).
    uc_c = f"UC.e2e.{sfx}.concept"
    uc_p = f"UC.e2e.{sfx}.prereq"
    c_main, c_prereq = uuid.uuid4(), uuid.uuid4()
    pid = uuid.uuid4()
    # EOS-81 — 완료 루프 전용 문항(기대정답이 *수치*라 서버가 correct로 판정 가능)과 스킬 좌석.
    # 앞 구간의 sentinel 문항(pid)은 정답 비노출 검사 좌석이라 그대로 둔다(회귀 0).
    pid_done = uuid.uuid4()
    skill_id = f"skill.e2e.{sfx}"
    t1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    dialogue_ids: list[uuid.UUID] = []
    birth_year = 2000  # 성인(2026 기준 연나이 26 > 14) → is_minor 서버파생 False 기대.

    try:
        # ── 시딩: 성인 유저 + 문제·개념·ProblemConcept·선수 엣지·mastery ─────────────
        asyncio.run(_add_adult_user(uid, birth_year=birth_year))
        asyncio.run(
            _add_all(
                # 문제 개념(후행·PRIMARY) — 스킬 브리지를 실어 스킬 축 숙달 전파를 관통시킨다.
                _concept_with_code(c_main, uc_c, "이차함수", behavior_skills=[skill_id]),
                _concept_with_code(c_prereq, uc_p, "일차함수"),  # 막힌 선수
            )
        )
        asyncio.run(_add_all(_node_meta(uc_p, "일차함수", "[중]함수", "reviewed")))
        asyncio.run(_add_all(_skill_node(skill_id, "일차방정식 계산")))
        asyncio.run(_add_all(_problem_with_answer(pid, sfx)))
        # 완료 루프 문항 — 같은 개념(PRIMARY)에 매핑해 완료가 c_main 숙달을 움직이게 한다.
        asyncio.run(_add_all(_problem_with_answer(pid_done, f"{sfx}b", answer=_COMPLETION_ANSWER)))
        asyncio.run(_add_all(_problem_concept(pid, c_main)))
        asyncio.run(_add_all(_problem_concept(pid_done, c_main)))
        # 선수 엣지(P는 C의 선수·to==c_main·from==c_prereq) + 선수 약점 mastery(막힘).
        asyncio.run(_add_all(_prereq_edge(c_prereq, c_main, 0.9)))
        asyncio.run(_add_all(_mastery_row(uid, c_prereq, t1, 0.2)))
        # 완료 전 기준선 — 개념·스킬 두 축 모두 *첫 관측이 아니게* 심어 델타를 값으로 비교한다.
        asyncio.run(_add_all(_mastery_row(uid, c_main, t1, _SEED_CONCEPT_MASTERY)))
        asyncio.run(_add_all(_skill_mastery_row(uid, skill_id, t1, _SEED_SKILL_MASTERY)))

        token = create_access_token(uid, settings=_settings())
        auth = {"Authorization": f"Bearer {token}"}
        with _client() as client:
            # ── 1) 온보딩: GET /v1/users/me로 ETag 획득 → PATCH로 프로필 채움 ──────────
            # (프로필 GET/PATCH는 users 라우터 `/v1/users/me` — _SELF_EDITABLE 화이트리스트.)
            me0 = client.get("/v1/users/me", headers=auth)
            assert me0.status_code == 200, me0.text
            etag = me0.headers["ETag"]

            patched = client.patch(
                "/v1/users/me",
                headers={**auth, "If-Match": etag},
                # 자유 dict 요청 — target_grade(1~9)·birth_year·target_major_category
                # (전부 _SELF_EDITABLE). track_type은 화이트리스트에 없어 major_category로 표현.
                json={
                    "target_grade": 2,
                    "birth_year": birth_year,
                    "target_major_category": MajorCategory.이공계.value,
                },
            )
            assert patched.status_code == 200, patched.text
            body = patched.json()
            # 입력이 반영됐는지(화이트리스트 필드).
            assert body["target_grade"] == 2
            assert body["target_major_category"] == MajorCategory.이공계.value
            # is_minor는 *서버 파생*(입력 미신뢰)임을 실증 — birth_year에서 파생한 기대값과 일치.
            expected_is_minor = derive_is_minor(
                birth_year,
                current_year=current_year_kst(),
                threshold=_settings().minor_consent_age,
            )
            assert body["is_minor"] == expected_is_minor  # 성인이므로 False 기대.
            # PII(해시)는 응답에서 제외(response_model_exclude).
            assert "email_hash" not in body

            # ── 2) 진단: next-problem(CAT) + diagnosis/concepts ───────────────────────
            nxt = client.get("/v1/me/next-problem", headers=auth)
            assert nxt.status_code == 200, nxt.text
            nbody = nxt.json()
            # CAT 응답 형태 — problem_id(추천 없으면 None 가능)·theta·measurement_sufficient.
            assert "problem_id" in nbody
            assert isinstance(nbody["theta"], (int, float))
            assert isinstance(nbody["measurement_sufficient"], bool)

            diag = client.get("/v1/me/diagnosis/concepts", headers=auth)
            assert diag.status_code == 200, diag.text
            dlist = diag.json()
            assert isinstance(dlist, list)
            # 진단 목록 형태(coaching_focus 후보) — 항목이 있으면 개념·L4 코칭 필드를 갖는다.
            for item in dlist:
                assert "concept_id" in item
                assert "coaching" in item

            # ── 3) 문제 제시: GET /v1/problems/{pid} → 문제 스키마 ────────────────────
            prob = client.get(f"/v1/problems/{pid}", headers=auth)
            assert prob.status_code == 200, prob.text
            assert prob.json()["problem_id"] == str(pid)

            # ── 4) 풀이+코치: POST /v1/coach/sessions (오답 유발 풀이·단계 시퀀스) ──────
            create = client.post(
                "/v1/coach/sessions",
                headers=auth,
                json={
                    "student_input": "이 문제 이렇게 풀었는데 확인해줘",
                    "student_solution": _FALSE_ARITHMETIC,  # 거짓 등식 → arithmetic_error 확정
                    "problem_id": str(pid),
                    "solution_steps": _BAD_STEPS,  # 분배 오류 전이 → 단계 verify incorrect
                    "solution_step_types": ["계산"],  # 전이 1개(=len(steps)-1)·대수 검증 유지
                    "coaching_focus": "verify",
                },
            )
            assert create.status_code == 201, create.text
            cbody = create.json()
            did = uuid.UUID(cbody["dialogue_id"])
            dialogue_ids.append(did)

            # dialogue_id 존재·active_hypotheses는 리스트 형태(후보·낙인 아님).
            assert isinstance(cbody["active_hypotheses"], list)
            # verify 신호가 실렸다 — solution_coaching.solution_verification(단계 검증 집계).
            sol = cbody["solution_coaching"]
            assert sol is not None, "거짓 등식+오답 단계 → solution_coaching 노출"
            sv = sol["solution_verification"]
            assert sv is not None, "solution_steps 제공 → solution_verification 채워짐"
            assert sv["has_incorrect"] is True
            assert isinstance(sv["first_incorrect_index"], int)
            # WH-1 턴 인덱스(생성=1).
            assert cbody["wh1_turn_index"] == 1

            # 불변식: answer 비노출 — sentinel이 코치 응답 본문(텍스트·JSON) 어디에도 없음.
            assert _ANSWER_SENTINEL not in create.text
            assert _ANSWER_SENTINEL not in json.dumps(cbody, ensure_ascii=False)

            # ── 5) WH-1 다턴: 2턴 추가 → 턴 인덱스 증가·가설 리스트·턴 영속 ─────────────
            prev_turn_index = cbody["wh1_turn_index"]
            for _ in range(2):
                turn = client.post(
                    f"/v1/coach/sessions/{did}/turns",
                    headers=auth,
                    json={"student_input": "여기서부터 잘 모르겠어"},
                )
                assert turn.status_code == 201, turn.text
                tbody = turn.json()
                assert isinstance(tbody["active_hypotheses"], list)
                # wh1_turn_index는 교환마다 증가(누적 카운터·§2.2).
                assert tbody["wh1_turn_index"] > prev_turn_index
                prev_turn_index = tbody["wh1_turn_index"]

            # GET 세션 → 턴 영속(생성 2턴 + append 2회×2턴 = 6턴).
            got = client.get(f"/v1/coach/sessions/{did}", headers=auth)
            assert got.status_code == 200, got.text
            gbody = got.json()
            assert gbody["dialogue"]["dialogue_id"] == str(did)
            assert len(gbody["turns"]) == 6

            # ── 6) 3-tier verify: 독립 엔드포인트 POST /v1/verify-solution ────────────
            # 코치 응답 내 verify 신호와 *독립* verify가 정합함을 관통 증명(같은 오답 시퀀스).
            vresp = client.post(
                "/v1/verify-solution",
                headers=auth,
                json={"steps": _BAD_STEPS, "step_types": ["계산"]},
            )
            assert vresp.status_code == 200, vresp.text
            vbody = vresp.json()
            assert vbody["has_incorrect"] is True
            assert vbody["n_incorrect"] >= 1
            assert isinstance(vbody["first_incorrect_index"], int)
            # 정합: 코치가 실은 first_incorrect_index와 독립 verify가 동일 위치를 가리킨다.
            assert vbody["first_incorrect_index"] == sv["first_incorrect_index"]

            # ── 7) 완료 전 기준선 — (다)·(라) 델타 비교의 *before* 스냅샷 ─────────────
            # 게이트 실측: `l4_solution_completion_enabled`가 off면 완료 상태머신이 완전 inert라
            # 아래 구간이 "그냥 통과"한다(돌아보기 진입도·적재도 없음). 그건 통과가 아니라
            # 미측정이므로 게이트 상태를 먼저 단언해 위장을 차단한다(config.py 기본값 True).
            assert (
                _settings().l4_solution_completion_enabled is True
            ), "완료 게이트 off — 이 구간은 통과가 아니라 미측정이다"

            rec_params = {"prioritize_weak_concepts": "true"}
            before_rec = client.get("/v1/me/next-problem", headers=auth, params=rec_params)
            assert before_rec.status_code == 200, before_rec.text
            before = before_rec.json()
            before_pool = before["candidate_pool_size"]
            # 후보 풀이 비어 있으면 (라)에서 "빠졌다"를 관측할 수 없다 — 변별력 전제 확인.
            assert before_pool >= 1, "완료 전 후보 풀 0 — (라) 변별력 전제 불성립"
            # 콜드스타트: 채점 이력 0건이라 θ 표준오차 자체가 산출되지 않는다.
            assert before["standard_error"] is None
            # 대조군(결정론 확인·EOS-81 ③) — 상태를 *바꾸지 않고* 한 번 더 부르면 같은 추천이
            # 나온다. 이 대조가 없으면 완료 후의 차이가 "상태 변화 때문"인지 "추천이 원래
            # 비결정적이라서"인지 구분되지 않는다 — 같은 값을 내는 검사는 위장이라는 규칙의 짝.
            # 결정론은 우연이 아니라 계약이다(REC-06 — `candidate_pool_order_by`가 동률 구간을
            # problem_id 2차 키로 동결한다). 이 단언이 깨지면 아래 (라)의 델타 주장도 무효다.
            control_rec = client.get("/v1/me/next-problem", headers=auth, params=rec_params)
            assert control_rec.status_code == 200, control_rec.text
            control = control_rec.json()
            assert control["problem_id"] == before["problem_id"], "무변화 재호출은 같은 추천"
            assert control["candidate_pool_size"] == before_pool
            assert control["standard_error"] == before["standard_error"]

            assert asyncio.run(_fetch_attempts(uid)) == [], "완료 전 attempt는 0건이어야 한다"
            mastery_before = asyncio.run(_latest_concept_mastery(uid, c_main))
            skill_before = asyncio.run(_latest_skill_mastery(uid, skill_id))
            assert mastery_before == pytest.approx(_SEED_CONCEPT_MASTERY)
            assert skill_before == pytest.approx(_SEED_SKILL_MASTERY)

            # ── 8) 완료 (가) 턴 A: 정답 풀이 제출 → 돌아보기 대기(아직 완료 아님) ───────
            turn_a = client.post(
                "/v1/coach/sessions",
                headers=auth,
                json={
                    "student_input": "이렇게 풀어서 답이 나왔어",
                    "problem_id": str(pid_done),
                    "solution_steps": _CORRECT_STEPS,  # 마지막 단계 == 기대정답(서버 correct)
                    "solution_step_types": ["계산"],  # 전이 1개(=len(steps)-1)
                },
            )
            assert turn_a.status_code == 201, turn_a.text
            abody = turn_a.json()
            did_done = uuid.UUID(abody["dialogue_id"])
            dialogue_ids.append(did_done)
            # 정답이라고 *바로 넘기지 않는다* — Polya 돌아보기 1턴을 먼저 요구한다(교수학 계약).
            assert abody["awaiting_reflection"] is True, "정답 도달 → 돌아보기 대기 진입"
            assert abody["problem_complete"] is False
            assert abody["completed_attempt_id"] is None
            # 돌아보기 대기 상태에서는 아직 어떤 축도 쓰이지 않았다(적재 0 — 부분 쓰기 관측).
            assert asyncio.run(_fetch_attempts(uid)) == []
            assert asyncio.run(_latest_concept_mastery(uid, c_main)) == pytest.approx(
                mastery_before
            )

            # ── 9) 완료 (가) 턴 B: 돌아보기 응답 → 완료 확정·attempt 적재 신호 ──────────
            turn_b = client.post(
                f"/v1/coach/sessions/{did_done}/turns",
                headers=auth,
                json={"student_input": "양변을 2로 나누면 x만 남아서 그렇게 풀었어"},
            )
            assert turn_b.status_code == 201, turn_b.text
            bbody = turn_b.json()
            assert bbody["problem_complete"] is True, "돌아보기 1턴 후 완료 확정"
            assert bbody["awaiting_reflection"] is False
            assert bbody["completed_attempt_id"] is not None, "완료 응답에 적재된 attempt_id"
            attempt_id = uuid.UUID(bbody["completed_attempt_id"])

            # ── 10) 완료 (나)·(다): 네 commit을 *따로* 관측한다(부분 쓰기 통과 금지) ─────
            # ⑴ attempt 영속 — 응답이 준 id로 실제 SELECT(응답 필드 신뢰 금지).
            attempts = asyncio.run(_fetch_attempts(uid))
            assert len(attempts) == 1, "완료는 attempt 1건만 적재한다(중복 0)"
            attempt = attempts[0]
            assert attempt.attempt_id == attempt_id
            assert attempt.problem_id == pid_done
            assert attempt.is_correct is True, "서버 권위 판정(클라 자가보고 아님)"
            assert attempt.used_socratic is True, "코치 대화(돌아보기)로 도달"
            # 완료 턴에 재제출된 단계가 없으므로 student_answer는 None이다 — 정답 도달은 턴 A에서
            # 이미 서버가 확인했고 이 필드는 *완료 턴 재제출* 기록용이라는 현행 계약의 고정
            # (`api/coach.py::_complete_problem` docstring).
            assert attempt.student_answer is None
            # LearningSession writer 부재(정직한 공백·모듈 docstring) — 세션 축은 비어 있다.
            assert attempt.session_id is None, "세션 축 writer 0 — 이 관통은 세션을 만들지 않는다"

            # ⑵ 개념 축 숙달 델타(별도 commit) — 값이 실제로 올라갔다.
            mastery_after = asyncio.run(_latest_concept_mastery(uid, c_main))
            assert mastery_after is not None
            assert mastery_after > mastery_before, "정답 완료 → 개념 숙달 상승"

            # ⑶ 스킬 축 숙달 델타(또 다른 commit) — 개념만 오르고 스킬은 그대로인 상태를 막는다.
            skill_after = asyncio.run(_latest_skill_mastery(uid, skill_id))
            assert skill_after is not None, "concept→skill 브리지 해소 실패(스킬 축 미도달)"
            assert skill_after > skill_before, "정답 완료 → 스킬 숙달 상승"

            # ⑷ `문제시도` 이벤트(EOS-57 writer·마지막 commit) — 경로 라벨·해소 스킬 배열.
            events = asyncio.run(_fetch_completion_events(attempt_id))
            assert len(events) == 1, "완료 1건 → 문제시도 이벤트 1건"
            event = events[0]
            assert event.event_data is not None
            assert event.event_data["source"] == AttemptSource.coach_completion.value
            assert event.event_data["is_correct"] is True
            # None(=writer 미도달)과 []( =해소 0건)를 구분하는 규약이라 값 자체를 단언한다.
            assert event.skill_ids == [skill_id]

            # ── 11) 완료 (라): 후속 추천이 갱신된 상태를 반영한다 ────────────────────────
            after_rec = client.get("/v1/me/next-problem", headers=auth, params=rec_params)
            assert after_rec.status_code == 200, after_rec.text
            after = after_rec.json()
            # ① 방금 완료한 문항은 더 이상 추천되지 않는다(미시도 필터 NOT IN — 루프 전진).
            assert after["problem_id"] != str(pid_done)
            # ② 후보 풀이 정확히 1개 줄었다 — 풀 상한(θ 근방 상위 N)에 걸리지 않은 경우에만
            #    관측 가능하므로 상한 미만일 때만 단언한다(코퍼스가 적재된 DB에서의 오탐 회피).
            if before_pool < _CANDIDATE_POOL_SIZE:
                assert after["candidate_pool_size"] == before_pool - 1
            else:
                # 코퍼스가 적재된 DB — 풀이 상한에 걸려 "1 감소"를 셀 수 없다. 조용히 건너뛰지
                # 않고 상한 유지를 단언하고(빈 분기 금지), (라)의 변별은 아래 ③이 담당한다.
                assert after["candidate_pool_size"] == _CANDIDATE_POOL_SIZE
            # ③ 채점 이력이 생겨 θ 추정에 표준오차가 산출된다(완료 전엔 None이었다) — 적재된
            #    attempt가 추천 엔진의 입력으로 실제로 들어갔다는 직접 증거.
            assert after["standard_error"] is not None, "완료 attempt가 θ 추정에 반영되지 않았다"
            # ④ 약점 가중 축이 실제로 적용됐다("작동한 비율" 원칙 — 적용 여부를 응답이 말한다).
            assert "weak_concept" in after["weight_axes_applied"]
    finally:
        # ── 12) FK 안전 순서 정리 ────────────────────────────────────────────────────
        asyncio.run(
            _cleanup(
                uid,
                problem_ids=[pid, pid_done],
                concept_ids=[c_main, c_prereq],
                uc_ids=[uc_c, uc_p],
                dialogue_ids=dialogue_ids,
                skill_ids=[skill_id],
            )
        )
