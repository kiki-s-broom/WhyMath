"""L2 — IRT 능력 θ *추정*(채점 풀이 이력 → θ·SE·응답수).

학습자 모델 추정은 L2 책임(7계층). `irt.py`(순수 IRT 알고리즘)·`mastery_tracking.py`(BKT
추정+영속)와 대칭으로, 이 모듈은 *채점 이력에서 IRT θ를 추정*한다(난이도 b 변환 + `estimate_ability`
조율 + DB 조회). *현재값 읽기*는 `ability_tracking`(`get_current_theta`/`get_current_ability`)·
*스냅샷 영속*은 api/me 오케스트레이션(`_add_ability_snapshot_if_attempts` 등) 책임 — 추정/읽기/
영속을 분리한다(slice 78에 api/me L5에서 이관 — L2→L5 역방향 의존 제거).
"""

from __future__ import annotations

import math
import uuid

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.activity import ProblemAttempt
from whymath_backend.db.models.concept import Concept, ProblemConcept
from whymath_backend.db.models.problem import Problem
from whymath_backend.l2.irt import IrtItem, ability_standard_error, estimate_ability
from whymath_backend.schema.enums import ASSESSED_ROLES

_DIFFICULTY_MIDPOINT = 3.0  # Problem.difficulty_overall(1~5)의 중앙 → logit 0


def difficulty_to_logit(difficulty: float) -> float:
    """`difficulty_overall`(1~5) → IRT 난이도 b(logit). 휴리스틱 프록시(중앙 3=b0·범위 [-2,2]).

    *보정된* b는 응답 데이터로 `fit_jmle` 적합값(`Problem.irt_difficulty_b`)을 우선 쓰고
    (`resolve_item_difficulty_b`), 없을 때 이 휴리스틱으로 폴백한다(difficulty 1=쉬움→b=-2·
    5=어려움→b=+2).
    """
    return difficulty - _DIFFICULTY_MIDPOINT


def resolve_item_difficulty_b(
    irt_difficulty_b: float | None, difficulty_overall: float | None
) -> float | None:
    """문항 IRT 난이도 b 결정 — *보정값 우선·휴리스틱 폴백*(θ 추정 소비측 단일 지점).

    JMLE 보정값(`Problem.irt_difficulty_b`)이 있으면 그대로 쓰고(데이터 적합), 없으면 전문가
    난이도(`difficulty_overall` 1~5)를 `difficulty_to_logit`으로 매핑한다. 둘 다 없으면 None
    (난이도 정보 없음 → 호출부가 그 응답을 제외). 두 척도 모두 logit·평균 0 중심이라 혼합 안전.
    """
    if irt_difficulty_b is not None:
        return float(irt_difficulty_b)
    if difficulty_overall is not None:
        return difficulty_to_logit(float(difficulty_overall))
    return None


def resolve_item_discrimination_a(irt_a: float | None) -> float:
    """문항 IRT 변별도 a 결정 — *보정값 우선·Rasch 폴백*(`resolve_item_difficulty_b`의 대칭축).

    EOS-129: 2PL 보정(`item_calibration`)이 채택한 a(`Problem.irt_a`)가 **양수·유한**이면 그대로
    쓰고, 그 외(NULL·0 이하·nan·inf)는 1.0(Rasch)으로 폴백한다. b와 달리 None을 돌려주지 않는
    이유: a가 없어도 응답은 θ 추정에 쓸 수 있다 — a=1.0은 "변별도를 모른다"의 중립값이다.
    """
    if irt_a is not None and math.isfinite(irt_a) and irt_a > 0.0:
        return float(irt_a)
    return 1.0


class ConceptAbilityItem(BaseModel):
    """개념별 IRT 능력 — `GET /v1/me/ability/by-concept`의 한 개념 항목."""

    concept_id: uuid.UUID = Field(description="개념 id.")
    concept_code: str | None = Field(default=None, description="개념 코드(orphan이면 null).")
    concept_name: str | None = Field(default=None, description="개념명(orphan이면 null).")
    theta: float = Field(description="이 개념 문항들로 추정한 능력 θ(logit).")
    response_count: int = Field(description="이 개념 추정에 쓰인 채점 풀이 수.")
    standard_error: float | None = Field(
        default=None, description="θ 표준오차 SE=1/√I(θ). 측정 불가면 null."
    )


async def estimate_global_ability(
    session: AsyncSession, user_id: uuid.UUID
) -> tuple[float, float | None, int]:
    """채점 풀이 이력에서 전 과목 단일 θ·SE·응답수 추정 — `/ability`·snapshot 캡처 공유.

    `problem_attempt`(채점됨)를 `problem` JOIN해 (난이도→b, 정답) 응답을 만들고 θ·SE 산출.
    난이도 b는 보정값(`irt_difficulty_b`) 우선·없으면 휴리스틱(`resolve_item_difficulty_b`).
    SE는 정보 0(응답 없음)이면 None(측정 불가). 보정·휴리스틱 b 둘 다 없는 문항 제외.
    """
    stmt = (
        select(
            ProblemAttempt.is_correct,
            Problem.difficulty_overall,
            Problem.irt_difficulty_b,
        )
        .join(Problem, ProblemAttempt.problem_id == Problem.problem_id)
        .where(
            ProblemAttempt.user_id == user_id,
            ProblemAttempt.is_correct.isnot(None),
        )
    )
    responses: list[tuple[IrtItem, bool]] = []
    for is_correct, difficulty, irt_b in (await session.execute(stmt)).all():
        b = resolve_item_difficulty_b(irt_b, difficulty)
        if b is not None:
            responses.append((IrtItem(difficulty=b), bool(is_correct)))
    theta = estimate_ability(responses)
    se = ability_standard_error(theta, [item for item, _ in responses])
    return theta, (None if math.isinf(se) else se), len(responses)


async def compute_concept_abilities(
    session: AsyncSession, user_id: uuid.UUID
) -> list[ConceptAbilityItem]:
    """개념별 IRT θ·SE·응답수·메타 산출(정렬 전) — `/ability/by-concept`·snapshot 캡처 공유."""
    stmt = (
        select(
            ProblemConcept.concept_id,
            Concept.code,
            Concept.name_ko,
            ProblemAttempt.is_correct,
            Problem.difficulty_overall,
            Problem.irt_difficulty_b,
        )
        .join(Problem, ProblemAttempt.problem_id == Problem.problem_id)
        .join(ProblemConcept, ProblemConcept.problem_id == Problem.problem_id)
        .outerjoin(Concept, ProblemConcept.concept_id == Concept.concept_id)
        .where(
            ProblemAttempt.user_id == user_id,
            ProblemAttempt.is_correct.isnot(None),
            ProblemConcept.role.in_(ASSESSED_ROLES),
            # 보정 b 또는 전문가 난이도 중 하나라도 있어야 b 결정 가능(보정 b만 있는 문항도 포함).
            Problem.irt_difficulty_b.isnot(None) | Problem.difficulty_overall.isnot(None),
        )
    )
    grouped: dict[uuid.UUID, list[tuple[IrtItem, bool]]] = {}
    meta: dict[uuid.UUID, tuple[str | None, str | None]] = {}
    for concept_id, code, name, is_correct, difficulty, irt_b in (
        await session.execute(stmt)
    ).all():
        b = resolve_item_difficulty_b(irt_b, difficulty)
        if b is None:
            continue
        grouped.setdefault(concept_id, []).append((IrtItem(difficulty=b), bool(is_correct)))
        meta[concept_id] = (code, name)

    items = []
    for concept_id, responses in grouped.items():
        theta = estimate_ability(responses)
        se = ability_standard_error(theta, [it for it, _ in responses])
        code, name = meta[concept_id]
        items.append(
            ConceptAbilityItem(
                concept_id=concept_id,
                concept_code=code,
                concept_name=name,
                theta=theta,
                response_count=len(responses),
                standard_error=None if math.isinf(se) else se,
            )
        )
    return items


__all__ = [
    "ConceptAbilityItem",
    "compute_concept_abilities",
    "difficulty_to_logit",
    "estimate_global_ability",
    "resolve_item_difficulty_b",
    "resolve_item_discrimination_a",
]
