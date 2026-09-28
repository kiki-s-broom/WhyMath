"""L2 — 문항 난이도 b *보정*(채점 응답 전수 → JMLE 적합 → `Problem.irt_difficulty_b` 영속).

`ability_estimation`(학생 θ 추정)·`irt`(순수 IRT 알고리즘)와 대칭으로, 이 모듈은 *문항* 난이도
b를 응답 데이터로 *자가 보정*한다 — 전문가 라벨(`difficulty_overall`) 휴리스틱을 데이터 보정 b로
격상. `fit_jmle`(결합 최대우도)이 학생 θ·문항 b를 동시 추정하면, *응답이 충분한* 문항만 보정 b를
영속하고(소응답은 추정 불안정 → 휴리스틱 유지), θ 추정은 `resolve_item_difficulty_b`로 보정 b를
우선 소비한다.

스케일 메모: `fit_jmle`은 순수 파이썬·전수 적합(소규모 프로토타입용). 운영 트리거(주기 배치·증분
적합·엔드포인트)는 후속 — 본 모듈은 *호출형 함수*만 노출한다(L2→L5 역방향 의존 0).
"""

from __future__ import annotations

import uuid

from sqlalchemy import Select, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.activity import ProblemAttempt
from whymath_backend.db.models.problem import Problem
from whymath_backend.l2.irt import fit_jmle

# 보정 b를 영속할 최소 응답 수 — 미만은 b 추정 불안정(전부 정답/오답 → 경계값)이라 보류하고
# 휴리스틱(`difficulty_to_logit`)을 유지한다. 데이터 축적에 맞춰 상향(현재는 프로토타입 floor).
_MIN_RESPONSES_FOR_CALIBRATION = 5


def graded_response_stmt() -> Select[tuple[uuid.UUID | None, uuid.UUID | None, bool | None]]:
    """보정 모집단 조회문 — 채점됨·학생·문항 식별 가능한 `problem_attempt` 전수(학생·문항·정답).

    b 보정기(`calibrate_item_difficulties`)와 응답 축적 실측(`l2/item_response_census` —
    EOS-129 ⑤)이 **같은 모집단**을 보도록 조회문을 한 곳에 둔다. 둘이 따로 조건을 적으면
    실측이 "보정기가 실제로 먹는 데이터"와 다른 것을 세게 된다(진실 원천 이원화). 두 소비자는
    이 조회문을 직접 실행하지 않고 `load_graded_responses`를 거친다.
    """
    return select(
        ProblemAttempt.user_id,
        ProblemAttempt.problem_id,
        ProblemAttempt.is_correct,
    ).where(
        ProblemAttempt.is_correct.isnot(None),
        ProblemAttempt.user_id.isnot(None),
        ProblemAttempt.problem_id.isnot(None),
    )


def _compute_calibrated_b(
    rows: list[tuple[uuid.UUID, uuid.UUID, bool]],
) -> dict[uuid.UUID, float]:
    """(user_id, problem_id, 정답) 응답 → 문항별 보정 b 매핑(응답수 ≥ 임계 문항만). 순수·DB 무관.

    학생·문항을 0-based로 인덱싱해 `fit_jmle`(θ·b 동시 추정) 입력 희소 삼중쌍을 만들고, 적합한
    난이도 중 *응답 N회 이상* 문항만 채택한다(소응답은 추정 불안정 → 제외 = 휴리스틱 폴백 유지).
    빈 입력이면 빈 매핑.
    """
    if not rows:
        return {}
    student_idx: dict[uuid.UUID, int] = {}
    item_idx: dict[uuid.UUID, int] = {}
    responses: list[tuple[int, int, bool]] = []
    counts: dict[uuid.UUID, int] = {}
    for user_id, problem_id, is_correct in rows:
        s = student_idx.setdefault(user_id, len(student_idx))
        i = item_idx.setdefault(problem_id, len(item_idx))
        responses.append((s, i, bool(is_correct)))
        counts[problem_id] = counts.get(problem_id, 0) + 1
    _, difficulties = fit_jmle(responses, len(student_idx), len(item_idx))
    return {
        problem_id: difficulties[i]
        for problem_id, i in item_idx.items()
        if counts[problem_id] >= _MIN_RESPONSES_FOR_CALIBRATION
    }


async def load_graded_responses(
    session: AsyncSession, *, read_only: bool = False
) -> list[tuple[uuid.UUID, uuid.UUID, bool]]:
    """보정 모집단 전수를 (학생, 문항, 정답)으로 읽는다 — b 보정기와 응답 축적 실측의 공용 로더.

    실측(`l2/item_response_census`)은 DB를 직접 잡지 않고 이 함수를 부른다. 그래서 두 소비자가
    같은 모집단을 보는 것이 조회문 수준이 아니라 **실행 경로 수준**에서 성립하고, 데이터 접근
    지점도 늘지 않는다(ARCH-48 처분 (b) — `data_access_layer_audit.BASELINE`).

    `read_only=True`면 조회 전에 트랜잭션을 `READ ONLY`로 선언한다. 운영 DB에서 도는 실측이 쓰는
    옵션이다 — 조회 경로에 쓰기가 섞여 들어와도 DB가 거부한다(방어의 이중화). 이 선언은
    PostgreSQL에서 트랜잭션의 첫 문장이어야 하므로 이 트랜잭션의 **첫 호출**이어야 하고, 원시
    SQL은 이 한 줄뿐이다(ORM에 해당 표현이 없다). b 보정기는 같은 트랜잭션에서 UPDATE하므로
    기본값(False)으로 부른다.
    """
    if read_only:
        await session.execute(text("SET TRANSACTION READ ONLY"))
    rows = (await session.execute(graded_response_stmt())).all()
    return [(user_id, problem_id, bool(is_correct)) for user_id, problem_id, is_correct in rows]


async def count_problems(session: AsyncSession) -> int:
    """`problem` 전체 행 수 — 실측이 "응답이 한 건도 없는 문항"의 몫을 가늠하는 분모."""
    return int((await session.execute(select(func.count()).select_from(Problem))).scalar_one())


async def calibrate_item_difficulties(session: AsyncSession) -> int:
    """채점된 전체 응답을 JMLE 적합해 문항 난이도 b를 `Problem.irt_difficulty_b`에 보정·영속.

    `problem_attempt`(채점됨·학생·문항 식별 가능) 전수를 (학생, 문항, 정답)으로 모아
    `_compute_calibrated_b`로 보정 b를 산출하고, 응답 충분 문항만 UPDATE한다. 보정한 문항 수
    반환. commit은 내부 수행(`mastery_tracking` 선례). 운영 트리거는 후속 — 현재는 호출형.
    """
    calibrated = _compute_calibrated_b(await load_graded_responses(session))
    for problem_id, b in calibrated.items():
        await session.execute(
            update(Problem).where(Problem.problem_id == problem_id).values(irt_difficulty_b=b)
        )
    await session.commit()
    return len(calibrated)


__all__ = [
    "calibrate_item_difficulties",
    "count_problems",
    "graded_response_stmt",
    "load_graded_responses",
]
