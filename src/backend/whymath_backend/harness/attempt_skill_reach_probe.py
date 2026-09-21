"""`문제시도` 스킬 배열 **표본 생성 프로브** — 게이트 `G-eos63-skill-event-reach-sample` 실행 도구.

**존재 이유**: 짝인 `attempt_skill_event_reach_report`는 *관측*만 한다 — 분모가 실 PG의 채점
이력이라, 채점이 0건인 DB에서는 전 지표가 `측정 불가(분모 0)`로 나오고 측정 회차가 통째로
공전한다(이 프로젝트에서 반복 관측된 실패 형태). 게이트가 요구하는 것은 "리포트를 한 번
돌리는 것"이 아니라 **말할 수 있는 수치**이므로, 수치가 성립할 최소 표본을 *만드는* 쪽이
빠져 있었다. 이 모듈이 그 구멍을 메운다.

**엔드포인트를 반드시 경유한다(직접 writer 호출 금지)**: 표본을 `record_attempt_skill_event`
직접 호출로 만들면 writer 도달률이 **구성상 100%**가 되어 측정이 아니라 동어반복이 된다. 그래서
in-process ASGI(`TestClient`)로 실제 `POST /v1/me/attempts` 라우트를 태운다 — 의존성 주입·인증·
동의 게이트·숙달 전파·이벤트 기록까지 서빙 코드 그대로다. 서버(uvicorn)를 띄우지 않는 이유는
포트 점유·좀비 서버·LAN 도달성처럼 *측정과 무관한* 실패 축을 없애기 위함이다(2026-07-17 좀비
uvicorn 사고 계열).

**이 프로브가 답하는 것과 답하지 못하는 것**:
  - 답한다 — 실 코퍼스·실 브리지 데이터에서 채점 1건이 **스킬 ≥1건으로 해소되는 비율**.
    EOS-63 acceptance ②가 막고 있는 위험("기록 0건 상태에서 소비를 바꾸면 스킬 숙달 전파가
    죽는다")은 정확히 이 값으로 판정된다.
  - 답하지 못한다 — *유기적 트래픽*의 writer 도달률. 이 회차의 도달률은 프로브가 스스로 만든
    표본이라 배선이 살아 있으면 100%다(그 자체로 `attempt_submit` 경로 배선의 실재 증거는
    되지만, 학생 트래픽 통계는 아니다). `coach_completion` 경로는 이 프로브가 태우지 않으므로
    리포트의 그 행은 0으로 남는다 — **0으로 보이는 것과 죽은 것을 혼동하지 않도록** 리포트에
    넘길 때 이 사실을 함께 읽는다.

**쓰기가 남는다(의도)**: 표본은 실 DB의 `problem_attempt`·`attempt_event`·숙달 시계열에 남는다
— 남지 않으면 리포트가 볼 것이 없다. 오염을 식별 가능하게 만들기 위해 프로브 사용자는 **고정
UUID**(`PROBE_USER_ID`, uuid5 파생)를 쓴다. 정리는 그 user_id 한 개로 끝난다(런북 §7).

**실패는 서로 다른 exit로 갈린다**(측정 실패가 "해소 0%"로 위장되지 않게 — 「측정·수집 도구를
성공 경로만 보고 설계 금지」):
  0 = 회차 성공(해소율이 0%여도 성공 — 그것이 측정값이다)
  2 = DB 미도달(예외 타입명 동봉)
  3 = 스키마 뒤처짐 — `attempt_event.skill_ids` 컬럼 부재(`alembic upgrade head` 미적용)
  4 = 후보 문제 0건(코퍼스 미적재 또는 프로브 사용자가 전부 시도함)
  5 = 제출 전건 실패(라우트는 있는데 201이 하나도 안 나옴 — 배선 회귀 신호)

사용:
    python -m whymath_backend.harness.attempt_skill_reach_probe --count 20
    python -m whymath_backend.harness.attempt_skill_reach_probe --count 20 --json out/probe.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.config import Settings, get_settings
from whymath_backend.db.models.activity import ProblemAttempt
from whymath_backend.db.models.problem import Problem
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import dispose_engine, get_sessionmaker
from whymath_backend.schema.enums import Persona
from whymath_backend.schema.user import UserProfile as UserProfileSchema
from whymath_backend.security import create_access_token

__all__ = [
    "PROBE_USER_ID",
    "AttemptOutcome",
    "CandidateShortageError",
    "candidate_statement",
    "ProbeError",
    "ProbeResult",
    "SchemaBehindError",
    "dump_json",
    "ensure_probe_user",
    "ensure_skill_ids_column",
    "main",
    "pick_candidate_problems",
    "probe_settings",
    "probe_to_json",
    "render_probe",
    "summarize",
    "window_statement",
]

# 프로브 전용 고정 사용자 — uuid5(결정적)이라 어느 머신에서 몇 번을 돌려도 같은 행 하나에 쌓이고,
# 정리·식별이 user_id 한 개로 끝난다. 실 학생 UUID(uuid4 랜덤)와 충돌할 확률은 0이 아니지만
# 무시 가능하며, 그보다 "이 행들이 프로브 것임을 나중에 알 수 있는가"가 더 중요하다.
PROBE_USER_ID = uuid.uuid5(uuid.NAMESPACE_URL, "whymath://harness/attempt-skill-reach-probe")

_EXIT_OK = 0
_EXIT_DB_UNREACHABLE = 2
_EXIT_SCHEMA_BEHIND = 3
_EXIT_NO_CANDIDATES = 4
_EXIT_ALL_SUBMITS_FAILED = 5


class ProbeError(RuntimeError):
    """프로브 준비 단계 실패의 공통 조상 — CLI가 exit code로 번역한다."""

    exit_code: int = _EXIT_DB_UNREACHABLE


class SchemaBehindError(ProbeError):
    """`attempt_event.skill_ids` 컬럼 부재 — 대상 DB가 EOS-57 마이그레이션 이전이다.

    이것을 잡지 않으면 제출은 통과하고 **이벤트 기록만 조용히** 터지거나(또는 리포트가 exit 2를
    내고) 원인이 "해소 0%"로 오독된다. 컬럼 실재는 정상/비정상에서 서로 다른 값을 내는
    *변별력 있는* 선행 검사다.
    """

    exit_code = _EXIT_SCHEMA_BEHIND


class CandidateShortageError(ProbeError):
    """제출할 후보 문제가 0건 — 코퍼스 미적재이거나 프로브 사용자가 전부 시도했다."""

    exit_code = _EXIT_NO_CANDIDATES


# ──────────────────────────────────────────────────────────────────────────
# 순수 코어 (DB·HTTP 무접근 — 집계·렌더·직렬화)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(slots=True, frozen=True)
class AttemptOutcome:
    """채점 제출 1건의 결과.

    `skill_updates`는 응답 `skill_mastery_updates`의 길이다 — 그 시도가 **실제로 해소한 스킬
    개수**이며, 이벤트에 적재된 `skill_ids` 길이와 같다(엔드포인트가 같은 목록을 넘긴다).
    제출이 실패하면 개수를 *모르므로* `None`으로 둔다 — 0으로 접으면 "해소 0건"과 "측정 실패"가
    같은 글자가 된다(모른다 ≠ 아니다).
    """

    problem_id: uuid.UUID
    is_correct: bool
    status_code: int | None
    skill_updates: int | None
    concept_updates: int | None
    error: str | None = None

    @property
    def accepted(self) -> bool:
        """201 Created로 적재된 시도인가(= 이벤트가 남았어야 하는 시도인가)."""
        return self.status_code == 201


@dataclass(slots=True, frozen=True)
class ProbeResult:
    """한 회차 전량(불변). `started_at`이 리포트 `--since`에 그대로 넘어가는 창 경계다."""

    started_at: datetime
    requested: int
    candidates: int
    outcomes: tuple[AttemptOutcome, ...]

    @property
    def accepted(self) -> int:
        return sum(1 for o in self.outcomes if o.accepted)

    @property
    def failed(self) -> int:
        return sum(1 for o in self.outcomes if not o.accepted)

    @property
    def with_skill(self) -> int:
        """해소 ≥1건인 시도 수(수용된 것만 — 실패분은 분자·분모 어디에도 넣지 않는다)."""
        return sum(1 for o in self.outcomes if o.accepted and (o.skill_updates or 0) > 0)

    @property
    def resolution_rate(self) -> float | None:
        """수용 시도 중 해소 ≥1 비율. 수용 0건이면 **None**(분모 0을 0%로 위장하지 않는다)."""
        return None if self.accepted == 0 else self.with_skill / self.accepted

    @property
    def since_arg(self) -> str:
        """리포트 `--since`에 그대로 붙여 쓸 UTC ISO 문자열(창 경계 인계 — 자리표시자 0)."""
        return self.started_at.isoformat()


def summarize(outcomes: tuple[AttemptOutcome, ...]) -> dict[str, int]:
    """실패 사유를 타입명 단위로 집계 — 8가지 실패가 같은 글자로 보이지 않게."""
    reasons: dict[str, int] = {}
    for outcome in outcomes:
        if outcome.accepted:
            continue
        key = outcome.error or f"HTTP {outcome.status_code}"
        reasons[key] = reasons.get(key, 0) + 1
    return reasons


def _pct(value: float | None) -> str:
    return "측정 불가(분모 0)" if value is None else f"{value * 100:.1f}%"


def render_probe(result: ProbeResult) -> str:
    """회차 결과를 마크다운으로 렌더(순수·입력 외 계산 없음)."""
    reasons = summarize(result.outcomes)
    lines: list[str] = [
        "# `문제시도` 스킬 배열 표본 생성 프로브 (G-eos63)",
        "",
        "> 이 회차는 **표본을 만든다**. 판정 수치는 이어서 도는 기록률 리포트가 낸다.",
        "> 도달률이 100%로 나오는 것은 정상이다 — 표본을 프로브가 만들었기 때문이며,",
        "> 학생 트래픽 통계가 아니다(모듈 docstring '답하지 못하는 것').",
        "",
        f"- 회차 시작(UTC): **{result.since_arg}**",
        f"- 후보 문제: **{result.candidates}** · 제출 요청: **{result.requested}**",
        f"- 수용(201): **{result.accepted}** · 실패: **{result.failed}**",
        f"- 해소 ≥1: **{result.with_skill}** / 수용 {result.accepted} "
        f"→ **해소율 {_pct(result.resolution_rate)}**",
        "",
    ]
    if reasons:
        lines += ["## 실패 사유(타입명 단위)", ""]
        lines += [f"- `{key}` × {count}" for key, count in sorted(reasons.items())]
        lines.append("")
    lines += [
        "## 다음 단계 — 같은 창으로 리포트를 돌린다",
        "",
        "```",
        "python -m whymath_backend.harness.attempt_skill_event_reach_report "
        f"--since {result.since_arg}",
        "```",
        "",
    ]
    return "\n".join(lines)


def probe_to_json(result: ProbeResult) -> dict[str, Any]:
    return {
        "started_at": result.since_arg,
        "probe_user_id": str(PROBE_USER_ID),
        "requested": result.requested,
        "candidates": result.candidates,
        "accepted": result.accepted,
        "failed": result.failed,
        "with_skill": result.with_skill,
        "resolution_rate": result.resolution_rate,
        "failure_reasons": summarize(result.outcomes),
        "outcomes": [
            {
                "problem_id": str(o.problem_id),
                "is_correct": o.is_correct,
                "status_code": o.status_code,
                "skill_updates": o.skill_updates,
                "concept_updates": o.concept_updates,
                "error": o.error,
            }
            for o in result.outcomes
        ],
    }


def dump_json(result: ProbeResult) -> str:
    return json.dumps(probe_to_json(result), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


# ──────────────────────────────────────────────────────────────────────────
# DB seam (조회·준비 — 순수 코어와 분리)
# ──────────────────────────────────────────────────────────────────────────
def window_statement() -> sa.Select[tuple[datetime]]:
    """창 경계를 읽는 쿼리(순수) — **DB 시계**여야 한다(`prepare` docstring의 이유).

    조립을 분리해 두는 이유는 테스트가 *산출된 SQL*을 동결할 수 있게 하기 위함이다.
    파이썬 벽시계로 바꿔치기하는 회귀는 hermetic 테스트가 관측할 수 없고(DB가 없다),
    그 회귀의 증상은 "표본이 창 밖으로 새어 측정 불가"라는 원인 짐작이 어려운 형태다.
    """
    return sa.select(sa.func.now())


async def ensure_skill_ids_column(session: AsyncSession) -> None:
    """대상 DB에 `attempt_event.skill_ids`가 실재하는지 확인(없으면 `SchemaBehindError`).

    `sa.inspect`를 `run_sync`로 태운다 — 원시 SQL 문자열 없이 카탈로그를 읽는 표준 경로다.
    """
    connection = await session.connection()

    def _columns(sync_conn: Any) -> list[str]:
        inspector = sa.inspect(sync_conn)
        if "attempt_event" not in inspector.get_table_names():
            return []
        return [c["name"] for c in inspector.get_columns("attempt_event")]

    columns = await connection.run_sync(_columns)
    if not columns:
        raise SchemaBehindError(
            "대상 DB에 `attempt_event` 테이블이 없다 — 마이그레이션 미적용. "
            "`alembic -c alembic.ini upgrade head` 후 재실행."
        )
    if "skill_ids" not in columns:
        raise SchemaBehindError(
            "`attempt_event.skill_ids` 컬럼 부재 — 대상 DB가 EOS-57 마이그레이션"
            "(d4a71c0f9b32) 이전이다. `alembic -c alembic.ini upgrade head` 후 재실행."
        )


async def ensure_probe_user(session: AsyncSession) -> None:
    """프로브 사용자를 멱등 생성(이미 있으면 무동작).

    생년 정보를 넣지 않는다 — *알려진 미성년자*가 아니어야 `get_consented_user`(SEC-20 D9)를
    통과한다. 프로브는 미성년 동의 경로를 시험하는 도구가 아니므로 그 축을 건드리지 않는다.
    """
    existing = await session.get(UserProfile, PROBE_USER_ID)
    if existing is not None:
        return
    session.add(
        UserProfile.from_schema(
            UserProfileSchema(user_id=PROBE_USER_ID, persona_primary=Persona.A_일반고고3)
        )
    )
    await session.commit()


def candidate_statement(*, limit: int) -> sa.Select[tuple[uuid.UUID]]:
    """후보 선정 쿼리를 조립한다(순수·DB 무접근 — 컴파일된 SQL을 테스트가 동결할 수 있게).

    **모집단을 좁히지 않는다** — "스킬로 해소되는 문제만" 고르면 해소율이 구성상 부풀려져
    측정이 아니라 자기실현이 된다. 학생이 실제로 만나는 모집단(난이도가 매겨진 문제)에서
    균등 무작위로 뽑고, 해소 여부는 *결과*로 관측한다.
    """
    # `NOT IN (서브쿼리)`가 아니라 **NOT EXISTS**를 쓴다 — `problem_attempt.problem_id`는
    # nullable이라 서브쿼리에 NULL이 한 건이라도 섞이면 `NOT IN`이 SQL 3값 논리로 **전건
    # false**가 되어 후보가 조용히 0건이 된다(그리고 그 0건은 "코퍼스가 비었다"로 오독된다).
    # NOT EXISTS는 NULL에 그런 함정이 없다.
    already_attempted = (
        sa.select(ProblemAttempt.attempt_id)
        .where(
            ProblemAttempt.user_id == PROBE_USER_ID,
            ProblemAttempt.problem_id == Problem.problem_id,
        )
        .exists()
    )
    stmt = (
        sa.select(Problem.problem_id)
        .where(Problem.difficulty_overall.is_not(None), ~already_attempted)
        .order_by(sa.func.random())
        .limit(limit)
    )
    return stmt


async def pick_candidate_problems(session: AsyncSession, *, limit: int) -> list[uuid.UUID]:
    """`candidate_statement`를 실행해 후보 problem_id를 돌려준다(DB 접근은 여기 한 곳)."""
    rows = (await session.execute(candidate_statement(limit=limit))).scalars().all()
    return list(rows)


async def prepare(settings: Settings, *, count: int) -> tuple[datetime, list[uuid.UUID]]:
    """제출 전 준비 전량 — 창 경계 확보 → 스키마 확인 → 프로브 사용자 보장 → 후보 선정.

    `dispose_engine()`을 **먼저** 부른다: `get_sessionmaker(settings)`는 전역 캐시가 비어 있을
    때만 주입 settings로 엔진을 만들기 때문에, 캐시를 비우지 않으면 환경 기본값(풀 활성)으로
    이미 만들어진 엔진이 그대로 쓰여 `probe_settings()`의 NullPool이 무효가 된다.

    창 경계를 **DB 시계**(`now()`)에서 읽는다. 리포트가 비교하는 `problem_attempt.created_at`
    ·`attempt_event.event_at`은 서버(DB)가 찍는 값이므로, 파이썬 프로세스의 시각으로 창을
    자르면 미세한 시계 차만으로 방금 만든 표본이 창 밖으로 새고 그 결과가 "측정 불가(분모 0)"로
    보인다 — 같은 머신이라 확률은 낮지만, 그 실패는 원인을 짐작할 수 없는 형태로 나타난다.
    """
    await dispose_engine()
    sessionmaker = get_sessionmaker(settings)
    async with sessionmaker() as session:
        started_at = (await session.execute(window_statement())).scalar_one()
        await ensure_skill_ids_column(session)
        await ensure_probe_user(session)
        candidates = await pick_candidate_problems(session, limit=count)
    if not candidates:
        raise CandidateShortageError(
            "후보 문제 0건 — 난이도(difficulty_overall)가 매겨진 미시도 문제가 없다. "
            "코퍼스 적재(scripts/demo/seed_demo.py) 여부를 확인하거나, 프로브 사용자가 "
            f"이미 전부 시도했는지 확인한다(user_id={PROBE_USER_ID})."
        )
    return started_at.astimezone(UTC), candidates


# ──────────────────────────────────────────────────────────────────────────
# 제출 (in-process ASGI — 실제 라우트를 태운다)
# ──────────────────────────────────────────────────────────────────────────
def probe_settings() -> Settings:
    """런타임 생성 시크릿 + **풀 비활성(NullPool)** Settings(하드코딩 0·환경변수 요구 0).

    `database_url` 등 나머지 필드는 환경변수(`WHYMATH_*`)에서 그대로 읽는다 — 프로브가 바꾸는
    것은 서명 키와 풀 정책뿐이고, 그 키는 이 프로세스 안에서 발급·검증에 함께 쓰이므로 외부에
    남지 않는다.

    **`db_disable_pool=True`가 이 프로브의 정상 동작 조건이다**(선호가 아니다). 이 도구는 한
    회차에서 *여러 이벤트 루프*에 걸쳐 같은 전역 엔진을 쓴다 — 준비는 `asyncio.run()`이 여는
    루프에서, 제출은 컨텍스트매니저 없이 쓰는 `TestClient`가 **요청마다** 여는 AnyIO 포털의
    루프에서 돈다. 풀이 살아 있으면 이미 닫힌 루프에 바인딩된 asyncpg 연결이 다음 루프에서
    재사용돼 `Event loop is closed` / `attached to a different loop`로 **제출이 전건 실패**하고
    회차가 exit 5로 끝난다(`db/session.py`의 `db_disable_pool` 독스트링이 경고하는 바로 그
    실패 모드 · 선례 `tests/backend/harness/test_attempt_grading_shadow_report.py`
    `TestDiscriminatingMismatchCounter` 독스트링). NullPool이면 매 체크아웃이 새 연결이라
    연결이 루프 경계를 넘지 않는다.
    """
    return Settings(jwt_secret_key=SecretStr(secrets.token_urlsafe(48)), db_disable_pool=True)


def submit_attempts(
    problem_ids: list[uuid.UUID], *, settings: Settings
) -> tuple[AttemptOutcome, ...]:
    """`POST /v1/me/attempts`를 문제당 1건씩 태우고 결과를 모은다(정답/오답 교대).

    정답만 태우면 모델 B의 **정답 경로**(PRIMARY+TESTED 전체)만 보게 되고, 오답만 태우면
    PRIMARY만 보게 된다 — 교대로 태워 두 경로를 한 회차에 함께 관측한다.

    `TestClient(app)`을 `with` 없이 쓴다(lifespan 미발화·Starlette 기본) — Redis·device store·
    OCR 웜업 같은 *측정과 무관한* 기동 의존성을 요구하지 않기 위함이다. 스키마 뒤처짐은
    lifespan 가드 대신 `ensure_skill_ids_column`이 더 구체적인 메시지로 잡는다.

    한 건의 실패가 회차를 죽이지 않는다 — 건별로 예외를 잡아 **타입명과 함께** 기록하고
    계속한다(실패해도 증거가 남는다).
    """
    from fastapi.testclient import TestClient  # 지연 import — 모듈 import에 테스트 의존 금지

    from whymath_backend.app import create_app

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    token = create_access_token(PROBE_USER_ID, settings=settings)
    headers = {"Authorization": f"Bearer {token}"}

    outcomes: list[AttemptOutcome] = []
    client = TestClient(app)
    for index, problem_id in enumerate(problem_ids):
        is_correct = index % 2 == 0
        try:
            response = client.post(
                "/v1/me/attempts",
                headers=headers,
                json={"problem_id": str(problem_id), "is_correct": is_correct},
            )
        except Exception as exc:  # noqa: BLE001 — 건별 실패는 타입명과 함께 남기고 계속
            outcomes.append(
                AttemptOutcome(
                    problem_id=problem_id,
                    is_correct=is_correct,
                    status_code=None,
                    skill_updates=None,
                    concept_updates=None,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            continue
        if response.status_code != 201:
            outcomes.append(
                AttemptOutcome(
                    problem_id=problem_id,
                    is_correct=is_correct,
                    status_code=response.status_code,
                    skill_updates=None,
                    concept_updates=None,
                    error=f"HTTP {response.status_code}: {response.text[:200]}",
                )
            )
            continue
        body = response.json()
        outcomes.append(
            AttemptOutcome(
                problem_id=problem_id,
                is_correct=is_correct,
                status_code=201,
                skill_updates=len(body.get("skill_mastery_updates") or []),
                concept_updates=len(body.get("mastery_updates") or []),
            )
        )
    return tuple(outcomes)


# ──────────────────────────────────────────────────────────────────────────
# CLI (얇은 껍데기)
# ──────────────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    """CLI 엔트리 — 표본을 만들고 회차 요약을 stdout에 출력. exit는 모듈 docstring 표 참조."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.attempt_skill_reach_probe",
        description=(
            "`문제시도` 스킬 배열 표본 생성 프로브(G-eos63) — 실 PG에 채점 N건을 태워 "
            "기록률 리포트가 말할 수 있는 표본을 만든다."
        ),
    )
    parser.add_argument(
        "--count",
        type=int,
        default=20,
        help="제출할 채점 건수(기본 20). 후보가 모자라면 후보 수만큼만 제출한다.",
    )
    parser.add_argument(
        "--json", dest="json_path", type=Path, default=None, help="JSON 산출물 경로(선택)"
    )
    args = parser.parse_args(argv)
    if args.count < 1:
        print("--count는 1 이상이어야 한다.", file=sys.stderr)
        return _EXIT_NO_CANDIDATES

    settings = probe_settings()
    try:
        # 창 경계는 준비 트랜잭션의 첫 문장에서 **DB 시계**로 찍는다(prepare docstring 참조).
        started_at, candidates = asyncio.run(prepare(settings, count=args.count))
    except ProbeError as exc:
        print(f"준비 실패({type(exc).__name__}): {exc}", file=sys.stderr)
        return exc.exit_code
    except Exception as exc:  # noqa: BLE001 — DB 미도달 등은 타입명과 함께 보고하고 exit 2
        print(f"DB 오류 — 프로브 준비 실패({type(exc).__name__}): {exc}", file=sys.stderr)
        return _EXIT_DB_UNREACHABLE

    outcomes = submit_attempts(candidates, settings=settings)
    result = ProbeResult(
        started_at=started_at,
        requested=len(candidates),
        candidates=len(candidates),
        outcomes=outcomes,
    )
    print(render_probe(result))
    if args.json_path is not None:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(dump_json(result), encoding="utf-8")
        print(f"JSON 산출물: {args.json_path}")

    if result.accepted == 0:
        print(
            "제출 전건 실패 — 201이 하나도 나오지 않았다. 라우트·인증·동의 게이트를 확인한다"
            "(위 '실패 사유' 표가 타입명을 말한다).",
            file=sys.stderr,
        )
        return _EXIT_ALL_SUBMITS_FAILED
    return _EXIT_OK


if __name__ == "__main__":  # pragma: no cover — CLI 진입
    raise SystemExit(main())
