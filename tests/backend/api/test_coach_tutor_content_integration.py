"""P3-72 — 튜터 내용 요약 조회 헬퍼 3종의 실 PG 왕복(통합·검토 중2).

`test_coach_tutor_context.py`가 헬퍼를 *실행*하되 세션을 기록 대역으로 둔다면, 이 파일은 마이그레이션
head가 적용된 실 PG에 개념·스킬·문항 행을 적재하고 헬퍼를 그대로 돌린다. 확인하는 것:

- 문항 요약이 허용 열 4개만 읽고(정답 행 값이 결과 어디에도 없다), PG enum 열(question_format·
  bloom_level)이 문자열 값으로 돌아오며, 조건 수가 20에서 잘린다.
- 개념 이름표가 (code, 이름) 순서로 온다.
- 스킬 이름표가 id 오름차순 앞 5개만 조회된다(그 밖 id의 이름은 결과에 없다).

**PG 미도달은 skip이 아니라 fail이다**(PR #1709 재검토 하2 — 이 파일에만 적용). 저장소의 다른 통합
테스트는 미도달 시 graceful skip하지만, 이 파일은 `integration` 마크라 `WHYMATH_RUN_INTEGRATION`이
꺼져 있으면 `tests/backend/conftest.py`가 이미 수집 단계에서 skip한다. 즉 이 픽스처까지 왔다면
누군가 통합 실행을 *명시적으로 켠* 것이고(CI에서는 실 PG가 붙은 `backend-migrations` 잡뿐 —
data-pipeline 통합 잡은 `tests/backend`를 수집하지 않는다), 그때의 미도달은 환경 결함이다. skip으로
삼키면 "정답 열 미조회·enum 반환형" 검증이 한 번도 안 돈 채 초록으로 보인다.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from whymath_backend.api import coach
from whymath_backend.config import Settings
from whymath_backend.harness.wh1_tutor_context import ProblemBrief

pytestmark = pytest.mark.integration

_SKILL_PREFIX = "skill.p372-it-"


async def _with_session(fn: Any) -> Any:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(Settings().database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            return await fn(session)
    finally:
        await engine.dispose()


def _unreachable_reason() -> str | None:
    """PG·대상 테이블 도달 여부 — 못 닿으면 예외 *타입명*을 담은 사유(침묵 실패 금지)."""
    from sqlalchemy import text

    async def _probe(session: Any) -> None:
        await session.execute(text("SELECT count(*) FROM problem"))
        await session.execute(text("SELECT count(*) FROM skill_node"))
        await session.execute(text("SELECT count(*) FROM concept"))

    try:
        asyncio.run(_with_session(_probe))
    except Exception as exc:  # noqa: BLE001 — 사유로 바꿔 fail 메시지에 싣는다(삼키지 않는다).
        return type(exc).__name__
    return None


@pytest.fixture
def seeded() -> Any:
    reason = _unreachable_reason()
    if reason is not None:
        pytest.fail(
            f"통합 실행이 켜졌는데 PostgreSQL·대상 테이블에 닿지 못했다({reason}) — "
            "WHYMATH_DATABASE_URL·alembic upgrade head 확인(이 파일은 미도달을 skip하지 않는다)"
        )
    from sqlalchemy import delete

    from whymath_backend.db.models.concept import Concept
    from whymath_backend.db.models.problem import Problem
    from whymath_backend.db.models.skill_node import SkillNode
    from whymath_backend.schema.enums import (
        BehaviorArea,
        BloomLevel,
        ConceptLevel,
        Curriculum,
        QuestionFormat,
        SourceType,
        Subject,
    )

    concept_id, problem_id = uuid.uuid4(), uuid.uuid4()
    code = f"math.p372-it.{concept_id.hex[:12]}"
    skill_ids = [f"{_SKILL_PREFIX}{concept_id.hex[:8]}-{i:02d}" for i in (9, 3, 7, 1, 8, 2, 6)]

    async def _seed(session: Any) -> None:
        session.add(
            Concept(
                concept_id=concept_id,
                code=code,
                name_ko="일차방정식(통합)",
                level=ConceptLevel.세부개념,
                behavior_skills=skill_ids,
            )
        )
        for sid in skill_ids:
            session.add(
                SkillNode(
                    skill_id=sid,
                    name_ko=f"이름-{sid[-2:]}",
                    behavior_area=BehaviorArea.COMPUTE,
                    family="p372-it",
                    review_status="ai_estimated",
                )
            )
        session.add(
            Problem(
                problem_id=problem_id,
                source_type=SourceType.자체생성,
                curriculum_version=Curriculum.REVISION_2022,
                valid_from_year=2025,
                subject=Subject.공통,
                unit_codes=["P372-IT"],
                question_format=QuestionFormat.단답형,
                bloom_level=BloomLevel.APPLY,
                has_visual=True,
                condition_count=35,
                question_text="SECRET_STEM_P372",
                answer="SECRET_ANSWER_P372",
                answer_explanation="SECRET_EXPLANATION_P372",
            )
        )
        await session.commit()

    async def _cleanup(session: Any) -> None:
        await session.execute(delete(Problem).where(Problem.problem_id == problem_id))
        await session.execute(delete(SkillNode).where(SkillNode.skill_id.in_(skill_ids)))
        await session.execute(delete(Concept).where(Concept.concept_id == concept_id))
        await session.commit()

    asyncio.run(_with_session(_seed))
    try:
        yield {
            "concept_id": concept_id,
            "problem_id": problem_id,
            "code": code,
            "skills": skill_ids,
        }
    finally:
        asyncio.run(_with_session(_cleanup))


def test_problem_brief_reads_structure_only_from_real_pg(seeded: Any) -> None:
    async def _run(session: Any) -> Any:
        return await coach._problem_brief_for(session, seeded["problem_id"])

    brief = asyncio.run(_with_session(_run))
    assert brief == ProblemBrief(
        question_format="단답형", bloom_level="APPLY", has_visual=True, condition_count=20
    )
    assert "SECRET" not in brief.model_dump_json()


def test_concept_label_from_real_pg(seeded: Any) -> None:
    async def _run(session: Any) -> Any:
        return await coach._concept_label_for(session, seeded["concept_id"])

    assert asyncio.run(_with_session(_run)) == (seeded["code"], "일차방정식(통합)")


def test_skill_labels_from_real_pg_are_first_five_sorted(seeded: Any) -> None:
    async def _run(session: Any) -> Any:
        return await coach._skill_labels_for(session, seeded["skills"])

    labels = asyncio.run(_with_session(_run))
    expected = sorted(seeded["skills"])[:5]
    assert sorted(sid for sid, _ in labels) == expected
    assert all(name == f"이름-{sid[-2:]}" for sid, name in labels)
