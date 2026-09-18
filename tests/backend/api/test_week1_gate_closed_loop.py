"""계획서 300 Phase 2 §4 **Week 1 Gate 판정** 하네스 — 1사이클이 *DB 직접 수정 없이* 도는가.

판정 대상(원 문서 §4 완료 판정 그대로):

    사용자 생성 → 진단 → 개념 선택 → 문제 풀이 → 오답 → mastery 변경 → 다음 문제 추천

이 7단계를 **공개 HTTP 표면만으로** 관통한다. 판정은 pytest exit code로 나오고, 각 단계는
`WEEK1_GATE_STEP=...` 줄로 표준출력에 남는다(인상 판정 금지 — 단계마다 *산출물*을 단언한다).

**기존 관통 테스트(`test_e2e_vertical_slice_integration.py`)와 무엇이 다른가**
그 테스트는 `_add_adult_user()`로 `UserProfile`을 **ORM 직접 insert**해 학습자를 만든다. 즉 7단계
중 1단계(`사용자 생성`)가 API 경로를 지나가지 않는다 — 루프 연결성은 증명하지만 "DB 직접 수정
없이"라는 게이트 문면은 증명하지 않는다. 이 모듈은 그 구멍을 닫는다: 학습자는
`POST /v1/auth/{provider}/callback`(운영 코드 `resolve_user` upsert 경로)이 만든다.

**시딩 경계(정직한 선언)**
- *학습자 상태*(user_profile·problem_attempt·concept_mastery_history·attempt_event)는 **단 한 줄도
  직접 쓰지 않는다**. 전부 HTTP 응답의 부수효과로만 생긴다. 이 규율은
  `test_week1_gate_no_learner_writes.py`가 AST로 기계 집행한다(주장이 아니라 검사).
- *저작 콘텐츠*(concept·problem·problem_concept)는 ORM으로 심는다. 원 문서 §4가 "가짜 데이터라도
  전체 흐름이 한 번 돌아가게"라고 명시해 콘텐츠는 전제이고, 게이트의 7단계에 저작 행위가 없다.
  덧붙여 `problem_concept`(문제↔개념 매핑)은 **쓰기 API 자체가 없다**(108 라우트 전수 확인) —
  콘텐츠 축까지 API로 돌리는 것은 이 게이트가 아니라 별건이다.

**외부 신원 제공자(IdP)는 스텁이다 — 스텁 범위의 정직한 명시**
`FakeOAuthProvider`(`api/demo_auth.py` — 저장소에 실재하는 시연 경로)를 주입해 code 교환만
대체한다. 그 뒤의 사용자 생성(`resolve_user`의 email_hash upsert·`derive_is_minor` 서버 파생·JWT
발급)은 **운영 코드 그대로**다. CI에 카카오/네이버 자격증명을 들이지 않고 사용자 생성 코드 경로를
지나가는 유일한 방법이며, 이 모듈이 스텁하는 것은 *외부 IdP 응답 하나*뿐이다.

**판정 밖(원 문서 지시)**: AI 품질·추천 품질·UI는 보지 않는다. 연결성(호출 가능성·상태 전파)만.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Select, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from whymath_backend.api._rate_limit import reset_store
from whymath_backend.api.auth import email_hash
from whymath_backend.api.demo_auth import DEMO_EMAIL, DEMO_PROVIDER_NAME, FakeOAuthProvider
from whymath_backend.app import create_app
from whymath_backend.config import Settings, get_settings
from whymath_backend.db.models.concept import Concept, ProblemConcept
from whymath_backend.db.models.problem import Problem
from whymath_backend.db.models.user import UserProfile
from whymath_backend.schema.concept import Concept as ConceptSchema
from whymath_backend.schema.concept import ProblemConcept as ProblemConceptSchema
from whymath_backend.schema.enums import (
    ConceptLevel,
    ConceptRole,
    Curriculum,
    ReviewStatus,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem import Problem as ProblemSchema

pytestmark = pytest.mark.integration

_SECRET = "week1-gate-jwt-secret-0123456789abcdef"
_REDIRECT_URI = "http://localhost:8000/auth/demo/callback"

# 정답 비노출 검사 sentinel — 학생 대면 문항 조회 응답에 등장하면 안 된다.
_ANSWER_SENTINEL = "WEEK1_GATE_ANSWER_DONOTLEAK"
# 오답으로 제출할 학생 답안(정답과 다르다는 것만 중요하다).
_WRONG_ANSWER = "42"
# 계정 삭제 확인 문구 — `api/me.py::_DELETE_CONFIRMATION`(비공개 상수)의 계약 값.
_ERASE_CONFIRM = "DELETE_MY_ACCOUNT"


def _settings() -> Settings:
    """판정용 Settings — jwt 시크릿과 redirect_uri allowlist만 고정(DB는 환경변수 소싱).

    `oauth_redirect_uri_allowlist`를 비워 두면 콜백이 deny-by-default로 400을 낸다(운영 기본값).
    판정은 그 allowlist에 테스트 uri 하나만 올려 *정상 경로*를 지나간다.
    """
    return Settings(
        jwt_secret_key=SecretStr(_SECRET),
        oauth_redirect_uri_allowlist=_REDIRECT_URI,
    )


async def _pg_reachable() -> bool:
    """실 PG 도달 가능 여부 — 미도달이면 판정을 내리지 않고 skip한다(측정 실패 ≠ 통과)."""
    engine = create_async_engine(_settings().database_url)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


async def _add_all(*objs: object) -> None:
    """저작 콘텐츠 시딩 — 학습자 상태는 여기 넣지 않는다(위 시딩 경계 참조)."""
    engine = create_async_engine(_settings().database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add_all(list(objs))
            await session.commit()
    finally:
        await engine.dispose()


async def _fetch_all(stmt: Select[Any]) -> list[Any]:
    """관측 전용 SELECT(읽기) — 읽기는 "DB 직접 수정"이 아니므로 판정에 허용된다."""
    engine = create_async_engine(_settings().database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())
    finally:
        await engine.dispose()


async def _demo_user_ids() -> list[uuid.UUID]:
    """데모 이메일 해시로 잡히는 `user_profile` id 목록 — 생성 전 0건·생성 후 1건을 관측한다."""
    rows = await _fetch_all(
        select(UserProfile).where(UserProfile.email_hash == email_hash(DEMO_EMAIL))
    )
    return [row.user_id for row in rows]


def _concept(cid: uuid.UUID, code: str, name: str) -> Concept:
    """개념 노드(저작 콘텐츠)."""
    return Concept.from_schema(
        ConceptSchema(
            concept_id=cid,
            code=code,
            name_ko=name,
            level=ConceptLevel.세부개념,
            behavior_skills=[],
        )
    )


def _problem(pid: uuid.UUID, suffix: str, difficulty: float) -> Problem:
    """자체생성 문항(저작 콘텐츠) — CAT 후보 조건(approved·difficulty 보유)을 충족시킨다.

    난이도를 서로 다르게 주는 이유: 추천이 θ 근방 최근접을 고르므로 두 문항의 난이도가 같으면
    어느 쪽이 먼저 나올지 결정론이 아니다. 판정은 "추천이 *시도한 문항을 뺀다*"를 보므로 순서
    자체는 무관하지만, 단계별 단언이 흔들리지 않게 후보를 구별 가능하게 만든다.
    """
    return Problem.from_schema(
        ProblemSchema(
            problem_id=pid,
            source_type=SourceType.자체생성,
            review_status=ReviewStatus.approved,
            curriculum_version=Curriculum.REVISION_2022,
            valid_from_year=2022,
            subject=Subject.공통,
            unit_codes=[f"U-{suffix}"],
            difficulty_overall=difficulty,
            answer=_ANSWER_SENTINEL,
        )
    )


def _problem_concept(pid: uuid.UUID, cid: uuid.UUID) -> ProblemConcept:
    """문제↔개념 PRIMARY 매핑 — 오답이 이 개념의 숙달을 움직이게 하는 책임귀속 축."""
    return ProblemConcept.from_schema(
        ProblemConceptSchema(problem_id=pid, concept_id=cid, role=ConceptRole.PRIMARY)
    )


async def _cleanup_content(*, problem_ids: list[uuid.UUID], concept_ids: list[uuid.UUID]) -> None:
    """이번에 심은 **저작 콘텐츠만** 정리한다 — 학습자 상태는 API 삭제권으로 지운다.

    학습자 쪽을 SQL로 지우지 않는 이유가 판정과 직결된다: 학습자 상태 테이블 목록을 이 하네스가
    알고 있으면(그리고 그 목록이 낡으면) 정리가 FK로 터지거나 조용히 남는다. 실제로 학습자
    user_id를 참조하는 테이블은 18개이고 학습 상태 머신(EOS-105)이 그중 2개를 최근에 늘렸다.
    그래서 정리도 **운영 경로**(`DELETE /v1/me` — `privacy.erase_user`가 자식→부모 순서로 17테이블
    + user_profile을 한 트랜잭션에 지운다)에 맡긴다. 하네스가 학습자 표를 열거하지 않는 것이
    게이트 문면과도 일관된다.
    """
    engine = create_async_engine(_settings().database_url)
    pids = [str(p) for p in problem_ids]
    cids = [str(c) for c in concept_ids]
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM problem_concept WHERE problem_id = ANY(:ids)"), {"ids": pids}
            )
            await conn.execute(
                text("DELETE FROM problem WHERE problem_id = ANY(:ids)"), {"ids": pids}
            )
            await conn.execute(
                text("DELETE FROM concept WHERE concept_id = ANY(:ids)"), {"ids": cids}
            )
    finally:
        await engine.dispose()


def _client() -> TestClient:
    """실 PG 클라이언트 — 외부 IdP만 스텁 주입하고 `get_session`은 라이브 PG 그대로."""
    app = create_app(oauth_providers={DEMO_PROVIDER_NAME: FakeOAuthProvider()})
    app.dependency_overrides[get_settings] = _settings
    return TestClient(app)


def _login(client: TestClient) -> dict[str, str]:
    """데모 provider 콜백으로 로그인 — 신규면 `resolve_user`가 upsert로 **생성**한다.

    운영 코드 경로 그대로다(state 발급 → 검증 → 신원 조회 → upsert → JWT 발급). 스텁은 신원
    조회 한 지점뿐이다.
    """
    state = client.get(f"/v1/auth/{DEMO_PROVIDER_NAME}/state")
    assert state.status_code == 200, state.text
    login = client.post(
        f"/v1/auth/{DEMO_PROVIDER_NAME}/callback",
        json={
            "code": "week1-gate",
            "redirect_uri": _REDIRECT_URI,
            "state": state.json()["state"],
        },
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    assert token, "access_token이 비었다 — 사용자 생성 경로가 토큰을 발급하지 못했다."
    return {"Authorization": f"Bearer {token}"}


def _erase_learner(client: TestClient) -> None:
    """학습자 데이터 정리 — 운영 삭제권 경로(`DELETE /v1/me`). 멱등(없으면 0행).

    선행 정리에도 쓴다: 지난 회차가 남긴 데모 계정이 있으면 "생성 전 0건" 기준선이 깨지므로,
    로그인해서(기존 행 반환) 지우고 시작한다.
    """
    auth = _login(client)
    erased = client.request("DELETE", "/v1/me", headers=auth, json={"confirmation": _ERASE_CONFIRM})
    assert erased.status_code == 200, erased.text


def _step(name: str, detail: str) -> None:
    """단계 통과를 표준출력에 남긴다 — 판정은 exit code, 경위는 이 줄들이 말한다."""
    print(f"WEEK1_GATE_STEP={name} :: {detail}")


def test_week1_gate_one_cycle_without_direct_db_writes() -> None:
    """Week 1 Gate 판정 — 7단계를 HTTP만으로 완주하고 각 단계의 산출물을 단언한다."""
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 판정 불가(WHYMATH_DATABASE_URL 확인). 통과가 아니다.")

    # 레이트리미터 격리 — 같은 프로세스의 앞선 통합 테스트가 IP 버킷을 소진하면 이 판정의
    # 쓰기 호출이 429를 받는다(관통 테스트와 같은 관용·판정은 한도 계약을 재는 자리가 아니다).
    asyncio.run(reset_store())

    sfx = uuid.uuid4().hex[:8]
    cid = uuid.uuid4()
    pid_a, pid_b = uuid.uuid4(), uuid.uuid4()
    problem_ids = [pid_a, pid_b]
    concept_ids = [cid]

    try:
        # ── 저작 콘텐츠 시딩(게이트 7단계 밖·원 문서 §4가 허용한 '가짜 데이터') ──────────
        asyncio.run(_add_all(_concept(cid, f"UC.w1gate.{sfx}", "이차함수")))
        asyncio.run(_add_all(_problem(pid_a, f"{sfx}a", 3.0)))
        asyncio.run(_add_all(_problem(pid_b, f"{sfx}b", 5.0)))
        asyncio.run(_add_all(_problem_concept(pid_a, cid)))
        asyncio.run(_add_all(_problem_concept(pid_b, cid)))

        with _client() as client:
            # 선행 정리 — 지난 회차의 데모 계정을 운영 삭제권으로 비운다(멱등).
            _erase_learner(client)
            before_users = asyncio.run(_demo_user_ids())
            assert before_users == [], f"선행 정리 실패 — 데모 계정이 남아 있다: {before_users}"

            # ── 1) 사용자 생성 — state 발급 → 콜백. 학습자 행 직접 insert 0. ───────────
            auth = _login(client)

            # 산출물 단언: 호출 *전* 0건이던 user_profile이 호출 *후* 1건이다(생성의 증거).
            after_users = asyncio.run(_demo_user_ids())
            assert len(after_users) == 1, f"user_profile이 1건이 아니다: {after_users}"
            uid = after_users[0]

            # 발급된 토큰이 그 사용자로 인증된다(토큰↔행 연결 — 남의 계정이 아니다).
            me = client.get("/v1/users/me", headers=auth)
            assert me.status_code == 200, me.text
            _step("1-user-created", f"user_profile 0건→1건 · uid={uid} · /v1/users/me 200")

            # ── 2) 진단 — 요약 조회 + CAT 출제(진단 목적). ─────────────────────────────
            summary = client.get("/v1/me/diagnosis/summary", headers=auth)
            assert summary.status_code == 200, summary.text

            diag = client.get("/v1/me/next-problem?purpose=diagnosis", headers=auth)
            assert diag.status_code == 200, diag.text
            diag_body = diag.json()
            # 콜드스타트 CAT이 문항을 *고를 수 있는가*만 본다. *어느* 문항인지는 단언하지
            # 않는다 — 이 잡은 통합 테스트 전체가 PG 하나를 공유하므로 후보 풀에 다른
            # 테스트의 시딩이 섞인다. "내 문항이 뽑혀야 한다"고 쓰면 판정이 남의 시딩 순서에
            # 의존하고, 그때의 red는 루프 고장이 아니라 판정 하네스의 결함이다.
            assert diag_body["problem_id"] is not None, (
                "진단 출제가 문항을 고르지 못했다(problem_id=null) — 승인·난이도 보유 미시도 "
                f"후보가 0이다. 이번 시드로 2건을 심었으므로 후보 조회 경로가 끊긴 것이다: {diag_body}"
            )
            _step(
                "2-diagnosis",
                f"summary 200 · CAT 출제 pid={diag_body['problem_id']} "
                f"theta={diag_body['theta']} pool={diag_body['candidate_pool_size']}",
            )

            # ── 3) 개념 선택 — 학습 대상 개념을 열어 본다. ────────────────────────────
            # 목록(`GET /v1/concepts`)이 아니라 *단건*을 쓴다: 목록은 code 필터가 없고
            # limit/offset만 있어, 같은 실행의 다른 통합 테스트가 심은 개념이 앞줄을 차지하면
            # 이번 개념이 첫 페이지 밖으로 밀린다 — 판정이 남의 시딩에 의존하게 된다.
            picked = client.get(f"/v1/concepts/{cid}", headers=auth)
            assert picked.status_code == 200, picked.text
            picked_body = picked.json()
            assert picked_body["concept_id"] == str(cid), picked_body
            # 약점 표면도 이 시점에 호출 가능해야 한다(콜드스타트 0건은 정당한 출력이다).
            weak0 = client.get("/v1/me/weak-concepts", headers=auth)
            assert weak0.status_code == 200, weak0.text
            _step(
                "3-concept-selected",
                f"concept_id={cid} name={picked_body['name_ko']} · weak-concepts 콜드스타트 "
                f"{len(weak0.json())}건",
            )

            # ── 4) 문제 풀이 — 3단계에서 고른 개념의 문항을 연다(정답 비노출 동시 확인). ─
            # 2단계 CAT 출력이 아니라 *선택한 개념에 매핑된* 문항을 푼다 — 게이트 순서
            # (진단 → 개념 선택 → 문제 풀이)가 개념 선택이 문제 선택을 이끄는 흐름이고,
            # 그래야 6단계의 숙달 변경이 그 개념에 귀속돼 값으로 확인된다.
            target_pid = str(pid_a)
            problem = client.get(f"/v1/problems/{target_pid}", headers=auth)
            assert problem.status_code == 200, problem.text
            assert _ANSWER_SENTINEL not in problem.text, (
                "학생 대면 문항 조회 응답에 정답이 노출됐다 — CLAUDE.md 금기(바로 정답 제공)."
            )
            _step("4-problem-fetched", f"GET /v1/problems/{target_pid} 200 · 정답 비노출 확인")

            # ── 5) 오답 제출 ───────────────────────────────────────────────────────────
            mastery_before = client.get("/v1/me/mastery/current", headers=auth)
            assert mastery_before.status_code == 200, mastery_before.text
            assert mastery_before.json() == [], (
                f"신규 사용자인데 숙달 스냅샷이 비어 있지 않다: {mastery_before.json()}"
            )

            attempt = client.post(
                "/v1/me/attempts",
                headers=auth,
                json={
                    "problem_id": target_pid,
                    "is_correct": False,
                    "student_answer": _WRONG_ANSWER,
                },
            )
            assert attempt.status_code == 201, attempt.text
            attempt_body = attempt.json()
            assert attempt_body["is_correct"] is False, attempt_body
            assert attempt_body["attempt_id"], attempt_body
            _step(
                "5-wrong-answer-submitted",
                f"POST /v1/me/attempts 201 · attempt_id={attempt_body['attempt_id']} "
                f"is_correct=False",
            )

            # ── 6) mastery 변경 — 응답 산출물과 조회 표면 양쪽에서 확인한다. ───────────
            updates = attempt_body["mastery_updates"]
            assert updates, "오답인데 mastery_updates가 비었다 — 채점이 숙달로 전파되지 않았다."
            updated_ids = {u["concept_id"] for u in updates}
            assert str(cid) in updated_ids, f"책임귀속 개념(PRIMARY)이 갱신 목록에 없다: {updated_ids}"

            mastery_after = client.get("/v1/me/mastery/current", headers=auth)
            assert mastery_after.status_code == 200, mastery_after.text
            snapshot = {row["concept_id"]: row["mastery"] for row in mastery_after.json()}
            assert str(cid) in snapshot, (
                f"숙달 스냅샷에 그 개념이 없다 — 쓰기가 조회 표면에 도달하지 않았다: {snapshot}. "
                "부분 쓰기(응답만 갱신·조회는 그대로)를 통과로 읽지 않기 위한 두 번째 관측이다."
            )
            assert snapshot[str(cid)] is not None, f"숙달값이 NULL이다: {snapshot}"
            _step(
                "6-mastery-changed",
                f"스냅샷 0건→{len(snapshot)}건 · concept={cid} mastery={snapshot[str(cid)]}",
            )

            # ── 7) 다음 문제 추천 — 시도한 문항이 빠지고 남은 문항이 나온다. ───────────
            nxt = client.get("/v1/me/next-problem", headers=auth)
            assert nxt.status_code == 200, nxt.text
            nxt_body = nxt.json()
            assert nxt_body["problem_id"] is not None, (
                f"오답 후 추천이 비었다 — 루프가 다음 문항을 내놓지 못했다: {nxt_body}. "
                f"이번 시드의 미시도 문항 {pid_b}가 남아 있으므로 후보가 0일 수 없다."
            )
            # 상태 전파의 증거: 방금 시도한 문항이 후보에서 빠진다(미시도 필터가 attempt를 본다).
            assert nxt_body["problem_id"] != target_pid, (
                f"시도한 문항이 다시 추천됐다 — 미시도 필터가 5단계의 attempt를 보지 못했다: "
                f"{nxt_body['problem_id']}"
            )
            # 표준오차는 채점 이력이 생겨야 산출된다(콜드스타트엔 null) — 추천이 *갱신된*
            # 학습자 상태를 읽었다는 두 번째 신호다.
            assert nxt_body["standard_error"] is not None, (
                f"채점 1건 뒤에도 표준오차가 null이다 — 추천이 갱신된 상태를 읽지 않았다: {nxt_body}"
            )
            same_seed = nxt_body["problem_id"] == str(pid_b)
            _step(
                "7-next-problem-recommended",
                f"pid={nxt_body['problem_id']} (시도={target_pid} 제외 · 이번 시드 잔여와 일치="
                f"{same_seed}) se={nxt_body['standard_error']}",
            )

            # 후행 정리(학습자) — 운영 삭제권 경로. 콘텐츠는 아래 finally가 지운다.
            _erase_learner(client)

        print("WEEK1_GATE=PASS :: 7단계 전건 통과 — 학습자 상태 DB 직접 쓰기 0")
    finally:
        asyncio.run(_cleanup_content(problem_ids=problem_ids, concept_ids=concept_ids))


def test_mastery_step_assertion_is_discriminating() -> None:
    """**음성 대조군** — 6단계(mastery 변경) 단언이 실패 상태에서 실제로 실패하는지 본다.

    위 판정은 `mastery_updates`가 *비어 있지 않음*을 6단계의 증거로 쓴다. 그 단언이 어떤 입력에서도
    초록이면 증거가 아니라 장식이다(CLAUDE.md "보호 장치를 실패 주입 없이 '보호 있음'으로 선언
    금지"). 여기서는 **개념 매핑이 없는 문항**(`problem_concept` 0건)으로 같은 오답을 제출한다 —
    책임귀속할 PRIMARY 개념이 없으므로 숙달 전파가 일어나지 않아야 하고, 따라서 위 6단계 단언은
    이 입력에서 **RED**가 되어야 한다. 그 사실을 여기서 양성/음성 양쪽으로 고정한다.

    이 대조군은 판정 하네스의 파일을 고치지 않는다 — 뮤테이션이 아니라 *입력*으로 실패 상태를
    만든다. 그래서 CI에서 판정과 같은 회차에 함께 돌고, 원복 실패 위험도 없다.
    """
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 대조군 판정 불가. 통과가 아니다.")

    asyncio.run(reset_store())

    sfx = uuid.uuid4().hex[:8]
    pid_unmapped = uuid.uuid4()
    problem_ids = [pid_unmapped]

    try:
        # 개념 매핑을 *일부러* 심지 않는다 — 이것이 이 대조군의 실패 주입이다.
        asyncio.run(_add_all(_problem(pid_unmapped, f"{sfx}n", 3.0)))

        with _client() as client:
            _erase_learner(client)  # 선행 정리 — 앞선 회차의 숙달이 섞이면 대조군이 무효다.
            auth = _login(client)

            attempt = client.post(
                "/v1/me/attempts",
                headers=auth,
                json={
                    "problem_id": str(pid_unmapped),
                    "is_correct": False,
                    "student_answer": _WRONG_ANSWER,
                },
            )
            assert attempt.status_code == 201, attempt.text
            body = attempt.json()
            assert body["mastery_updates"] == [], (
                "개념 매핑이 없는 문항인데 숙달이 갱신됐다 — 그렇다면 판정 6단계의 "
                f"`mastery_updates` 비어있지 않음 단언은 변별력이 없다: {body['mastery_updates']}"
            )
            snapshot = client.get("/v1/me/mastery/current", headers=auth)
            assert snapshot.status_code == 200, snapshot.text
            assert snapshot.json() == [], (
                "책임귀속 개념이 없는데 숙달 스냅샷이 생겼다 — 6단계 조회측 단언도 변별력이 "
                f"없다: {snapshot.json()}"
            )
            _erase_learner(client)

        print("WEEK1_GATE_CONTROL=OK :: 매핑 없음 → 숙달 전파 0 (6단계 단언의 변별력 확인)")
    finally:
        asyncio.run(_cleanup_content(problem_ids=problem_ids, concept_ids=[]))
