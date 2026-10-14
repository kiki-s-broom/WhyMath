"""라이브 `problem` 행에서 7필드 증거를 읽는다 — 발행 게이트의 저장 시점 입력 (P3-04).

`schema/problem_metadata.py`가 "있다"의 정의를 소유한다. 이 모듈은 DB에서 그 정의가 요구하는
**사실을 측정**해 `ProblemMetadataEvidence`로 돌려줄 뿐 판정은 하지 않는다(정의가 갈라지지 않게).

## 읽기 전용이다

`SELECT`만 한다 — 잠금도 쓰기도 없다. 호출자(`problem_publish_gate.apply_transition`)가 이미
문항 행을 잠갔고, 이 모듈은 그 뒤에 불린다(잠금 순서 문항 → 판 은 그대로).

## 필드별 측정 (대조표 정본 `docs/standards/problem_metadata_contract.md`)

- difficulty — `problem.difficulty_overall`
- answer / solution — `problem.answer` / `problem.answer_explanation`
- concept — `problem_concept`(role=PRIMARY)의 개념 id
- skill — 위 개념들의 `behavior_skills` 중 **실재하는 `skill_node`** 만 센다. 이름만 적힌 스킬은
  세지 않는다(`integrity_violations_gate.skill_coverage`와 같은 기준)
- misconception_signature — 두 출처를 따로 잰다
  · 문항 자체: `distractor_map`의 `misconception_id` 중 **등록된 오개념에 닿는 것**(kebab은
    `misconception_crosslink`, M-id는 `misconception_catalog`). P3-02 계측기의
    `_reached_misconceptions`와 같은 기준이다.
  · 소속 개념: PRIMARY 개념의 `source_id`를 `misconception_catalog.concept_src_id`로 가진 오개념
- hint_strategy — `hints`의 `problem_id` 일치 + `verified = true` 행 수

## 한계 (정직하게)

- `distractor_map`의 id가 L4 카탈로그(`CATALOG_BY_ID`)에 있는지는 보지 않는다. l3은 l4를 import할
  수 없다(7계층 단방향). 대신 DB의 크로스링크·카탈로그로 "등록된 오개념에 닿는가"를 본다. 닿지
  못하는 id는 문항 자체 증거로 세지 않는다(없는 오개념으로 서명이 있는 척하지 않는다).
- 개념의 오개념 상속은 `concept.source_id` ↔ `misconception_catalog.concept_src_id` 문자열 일치에
  기댄다. `source_id`가 비어 있는 개념은 상속 증거가 없는 것으로 센다(빈 튜플 — 측정했고 없다).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.concept import Concept, ProblemConcept
from whymath_backend.db.models.hint import Hint
from whymath_backend.db.models.misconception_catalog import MisconceptionCatalog
from whymath_backend.db.models.misconception_crosslink import MisconceptionCrosslink
from whymath_backend.db.models.problem import Problem
from whymath_backend.db.models.skill_node import SkillNode
from whymath_backend.schema.enums import ConceptRole
from whymath_backend.schema.problem_metadata import (
    EMPTY_DIFFICULTY,
    ProblemMetadataEvidence,
    parse_slot_tags,
)

# M-id 형태 — 이 모양이 아닌 id는 kebab(크로스링크 경유)으로 본다.
_MIS_ID_RE = re.compile(r"^M\d{4,}$")


def _non_blank(values: Iterable[Any]) -> tuple[str, ...]:
    return tuple(sorted({v.strip() for v in values if isinstance(v, str) and v.strip()}))


def _distractor_ids(problem: Problem) -> tuple[str, ...]:
    """`distractor_map`에 적힌 오개념 id들(중복 제거·정렬). 형태가 깨진 원소는 건너뛴다."""
    ids: list[Any] = []
    for entry in problem.distractor_map or []:
        if isinstance(entry, dict):
            ids.append(entry.get("misconception_id"))
    return _non_blank(ids)


async def _reachable_misconceptions(session: AsyncSession, ids: tuple[str, ...]) -> tuple[str, ...]:
    """id 중 등록된 오개념에 닿는 것만 — kebab은 크로스링크, M-id는 카탈로그로 확인한다."""
    if not ids:
        return ()
    mis_ids = [i for i in ids if _MIS_ID_RE.match(i)]
    kebab_ids = [i for i in ids if i not in mis_ids]
    reached: set[str] = set()
    if kebab_ids:
        rows = await session.execute(
            select(MisconceptionCrosslink.kebab_id).where(
                MisconceptionCrosslink.kebab_id.in_(kebab_ids)
            )
        )
        reached.update(rows.scalars())
    if mis_ids:
        rows = await session.execute(
            select(MisconceptionCatalog.mis_id).where(MisconceptionCatalog.mis_id.in_(mis_ids))
        )
        reached.update(rows.scalars())
    return tuple(sorted(reached))


async def load_metadata_evidence(
    session: AsyncSession, problem: Problem
) -> ProblemMetadataEvidence:
    """`problem` 행(호출자가 잠근 라이브 행)의 7필드 증거를 측정한다. 읽기 전용."""
    problem_id = problem.problem_id

    primary = (
        await session.execute(
            select(Concept.concept_id, Concept.source_id, Concept.behavior_skills)
            .join(ProblemConcept, ProblemConcept.concept_id == Concept.concept_id)
            .where(
                ProblemConcept.problem_id == problem_id,
                ProblemConcept.role == ConceptRole.PRIMARY,
            )
        )
    ).all()
    concept_ids = tuple(sorted(str(row.concept_id) for row in primary))

    # 스킬 — 개념에 적힌 이름이 아니라 **레지스트리(skill_node)에 실재하는 것**만 센다.
    named_skills = _non_blank(skill for row in primary for skill in (row.behavior_skills or ()))
    skill_ids: tuple[str, ...] = ()
    if named_skills:
        skill_rows = await session.execute(
            select(SkillNode.skill_id).where(SkillNode.skill_id.in_(named_skills))
        )
        skill_ids = tuple(sorted(skill_rows.scalars()))

    own = await _reachable_misconceptions(session, _distractor_ids(problem))

    source_ids = _non_blank(row.source_id for row in primary)
    inherited: tuple[str, ...] = ()
    if source_ids:
        inherited_rows = await session.execute(
            select(MisconceptionCatalog.mis_id).where(
                MisconceptionCatalog.concept_src_id.in_(source_ids)
            )
        )
        inherited = tuple(sorted(inherited_rows.scalars()))

    hint_count = (
        await session.execute(
            select(func.count())
            .select_from(Hint)
            .where(Hint.problem_id == problem_id, Hint.verified.is_(True))
        )
    ).scalar_one()

    overall = problem.difficulty_overall
    return ProblemMetadataEvidence(
        # 컬럼을 읽었으니 NULL은 "측정했고 비어 있음"이다 — None(측정 못함)이 아니다.
        difficulty=float(overall) if overall is not None else EMPTY_DIFFICULTY,
        answer=problem.answer if problem.answer is not None else "",
        solution_text=problem.answer_explanation if problem.answer_explanation is not None else "",
        concept_ids=concept_ids,
        skill_ids=skill_ids,
        own_misconception_ids=own,
        concept_misconception_ids=inherited,
        verified_hint_count=int(hint_count),
        slots=parse_slot_tags(problem.tags).slots,
    )


__all__ = ["load_metadata_evidence"]
