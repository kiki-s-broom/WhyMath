"""성취기준 1건의 **학습맵** 조회 — Concept → Skill → Problem → Misconception 한 번에 (EOS-05).

무엇을 답하나 (계획서 200 §18 — "Week 2의 핵심 테스트")
--------------------------------------------------------
    "중3 이차방정식 단원의 성취기준 X를 학습하려면 어떤 개념과 Skill이 필요하며,
     이를 평가할 문제와 발견할 수 있는 오개념은 무엇인가?"

계획서는 이 한 질문을 Week 2의 성공 기준으로 지목했다. 실측(2026-09-16·라우트 97개 전건)
결과 저장소는 이 체인을 **한 호출로 답하지 못했다** — 최소 4회 조합이 필요했고 그중
`Concept→Skill[]`·`→Misconception[]` 두 홉은 공개 표면 자체가 없었다. 이 모듈이 그 조합을
**L1에서 한 번에** 수행한다.

조회 로직을 복제하지 않는다 (acceptance ②)
------------------------------------------
1홉(성취기준→개념)은 `alignment_query.get_alignments`가 정본이다 — 3축 통합·조인 회계·어휘
정책이 전부 거기 있고, 여기서 SQL을 다시 쓰면 진실 원천이 둘이 된다. 나머지 홉은 이 저장소에
통합 좌석이 없던 자리이므로 여기가 그 좌석이 된다.

어휘 분기를 여기서 **푼다** (그러나 통일하지는 않는다)
-----------------------------------------------------
축마다 성취기준 어휘가 다르다 — 1축은 `norm_id`(`2022_2수_01_01`), 2·3축은 고시코드
(`[2수01-01]`). `alignment_query`는 이 차이를 *없애지 않고 표시*하며, 번역 테이블은 Phase 2다.

이 모듈은 번역표를 만들지 않고도 그 분기를 넘는다: **입력이 `AchievementStandard` 행이라
두 어휘를 이미 둘 다 알고 있기 때문이다.** 그래서 축을 나눠 두 번 물어본다(1축엔 norm_id,
2·3축엔 official_code). 이것은 어휘 통일이 아니라 *어휘를 아는 지점에서 각 축에 맞게 묻는 것*
이며, 조용한 가짜 통일(서로 다른 어휘를 한 리스트에 섞기)을 하지 않는다.

"작동한 비율" 원칙 — 빈 배열이 "없음"인지 "안 봄"인지 (acceptance ③)
--------------------------------------------------------------------
정상 응답 200은 체인이 작동했다는 증거가 아니다(CLAUDE.md 절대 금기). 그래서 홉마다
`HopStats(scanned, resolved, produced)`를 함께 낸다:

    scanned  이 홉이 입력으로 받은 키 수 (0이면 **앞 홉이 비어서 이 홉은 돌지도 않았다**)
    resolved 그 키 중 실제로 DB 행이 붙은 수 (scanned>0인데 0이면 조인/적재 이상 의심)
    produced 그 결과로 나온 항목 수 (resolved>0인데 0이면 "매핑이 없다" — 정상일 수 있다)

`alignment_query`의 probed/joined/matched 3분류와 같은 이유로 3분류다 — 2분류로는 "조인이
안 됐다"와 "매핑이 없다"가 같은 0으로 뭉개진다.

개념 키 공간 (실측 근거)
------------------------
1·3축의 `concept_key`는 개념 code 공간이고, `concept.code`와 `atom_node.code`는 같은 키
공간이다(`l1/skill_graph/resolve.py` docstring — "code는 atom_node.code PK이며 backend
concept.code와 동일 키 공간"). 2축(`curriculum_entry.concept_id`)은 개념 키 *문자열*이라
같은 공간일 수도 아닐 수도 있다 — **그래서 맞춰 보고, 안 맞으면 맞지 않았다고 센다**
(`concepts.scanned` vs `concepts.resolved`). 추정으로 채우지 않는다.

7계층: L1(데이터 기반)의 조회 함수다. 상위(L5 api)가 세션을 주고 호출하며 이 모듈은 상위를
모른다. 수학 의미론을 해석하지 않는다 — 키로 조인만 한다(Core 구역·EOS-67 경계 계약 준수).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlalchemy as sa

from whymath_backend.db.models.atom_node import AtomNode
from whymath_backend.db.models.concept import Concept, ProblemConcept
from whymath_backend.db.models.misconception_catalog import MisconceptionCatalog
from whymath_backend.db.models.problem import Problem
from whymath_backend.db.models.skill_node import SkillNode
from whymath_backend.l1.standards.alignment_query import (
    AlignmentAxis,
    AlignmentJoinStats,
    get_alignments,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "HopStats",
    "LearningMap",
    "LearningMapConcept",
    "LearningMapMisconception",
    "LearningMapProblem",
    "LearningMapSkill",
    "build_learning_map",
]

# 1축만 norm_id 어휘를 쓴다(모듈 docstring). 나머지 둘은 고시코드다.
_NORM_ID_AXES = frozenset({AlignmentAxis.CONCEPT_STANDARD_LINK})
_OFFICIAL_CODE_AXES = frozenset({AlignmentAxis.CURRICULUM_ENTRY, AlignmentAxis.ATOM_NODE})


@dataclass(frozen=True, slots=True)
class HopStats:
    """한 홉의 조인 회계 — 빈 배열의 원인을 구분 가능하게 만드는 최소 3분류."""

    scanned: int
    """입력 키 수. 0 = 앞 홉이 비어 **이 홉은 돌지 않았다**(미측정 ≠ 0)."""

    resolved: int
    """DB 행이 실제로 붙은 입력 키 수. scanned>0·resolved==0 = 조인/적재 이상 의심."""

    produced: int
    """산출 항목 수. resolved>0·produced==0 = 매핑이 비어 있다(정상일 수 있다)."""

    @property
    def join_blackout(self) -> bool:
        """훑었는데 **전건 조인 실패** — "없음"이 아니라 "안 붙음"을 의심할 상태."""
        return self.scanned > 0 and self.resolved == 0


@dataclass(frozen=True, slots=True)
class LearningMapConcept:
    concept_key: str
    """정렬이 준 개념 측 식별자 — 축별 어휘 그대로."""

    axes: tuple[str, ...]
    """이 키를 낸 축들(중복 제거·정렬)."""

    concept_id: uuid.UUID | None
    """`concept.code`로 해소된 UUID. None = 그 코드의 concept 행이 없다."""

    name_ko: str | None
    resolved_from: tuple[str, ...]
    """어느 테이블에서 실물을 찾았는가 — 'concept' / 'atom_node' / 둘 다 / 비어 있음."""


@dataclass(frozen=True, slots=True)
class LearningMapSkill:
    skill_id: str
    name_ko: str
    behavior_area: str
    family: str
    mastery_estimable: bool
    via_concept_keys: tuple[str, ...]
    """이 스킬을 요구한 개념 키들 — 어느 개념 때문에 딸려 왔는지 추적 가능하게."""


@dataclass(frozen=True, slots=True)
class LearningMapProblem:
    problem_id: uuid.UUID
    question_format: str | None
    answer_format: str | None
    difficulty_overall: float | None
    via_concept_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True, slots=True)
class LearningMapMisconception:
    mis_id: str
    canonical_statement: str | None
    error_type: str | None
    severity: str | None
    matched_by: tuple[str, ...]
    """무엇으로 걸렸는가 — 'concept_src_id' / 'behavior_skills'. 두 경로가 다르므로 표시한다."""


@dataclass(frozen=True, slots=True)
class LearningMap:
    """성취기준 1건의 학습맵 — 항목 + 홉별 회계. 회계 없이 항목만 돌려주지 않는다."""

    norm_id: str
    official_code: str
    concepts: tuple[LearningMapConcept, ...]
    skills: tuple[LearningMapSkill, ...]
    problems: tuple[LearningMapProblem, ...]
    misconceptions: tuple[LearningMapMisconception, ...]
    concept_stats: HopStats
    skill_stats: HopStats
    problem_stats: HopStats
    misconception_stats: HopStats
    alignment_stats: tuple[AlignmentJoinStats, ...]
    """1홉이 돌린 `get_alignments` 호출들의 원 회계 — 축별 probed/joined/matched 보존."""


async def _resolve_concepts(
    session: AsyncSession, keys: list[str]
) -> tuple[dict[str, Concept], dict[str, AtomNode]]:
    """개념 키를 `concept.code`·`atom_node.code` 양쪽에서 찾는다 — 둘은 같은 키 공간이다.

    두 테이블을 **둘 다** 보는 이유: 1·3축이 내는 키가 각각 구 437 개념 공간과 원자 공간이라,
    한쪽만 보면 다른 축이 낸 키가 통째로 미해소로 계상된다(그리고 그 0은 "없다"로 읽힌다).
    """
    if not keys:
        return {}, {}
    concept_rows = (
        (await session.execute(sa.select(Concept).where(Concept.code.in_(keys)))).scalars().all()
    )
    atom_rows = (
        (await session.execute(sa.select(AtomNode).where(AtomNode.code.in_(keys)))).scalars().all()
    )
    return {row.code: row for row in concept_rows}, {row.code: row for row in atom_rows}


async def build_learning_map(
    session: AsyncSession,
    *,
    norm_id: str,
    official_code: str,
    concept_limit: int = 100,
    problem_limit: int = 50,
    misconception_limit: int = 50,
) -> LearningMap:
    """성취기준 → Concept[] → Skill[] → Problem[] → Misconception[] 를 한 번에.

    Args:
      norm_id: `achievement_standard.norm_id` — 1축(`concept_standard_link`) 어휘.
      official_code: 고시코드 — 2·3축(`curriculum_entry`·`atom_node`) 어휘.
      concept_limit: 1홉 인출 상한. 뒤 홉의 입력 크기를 지배하므로 여기서 한 번만 자른다.
      problem_limit / misconception_limit: 각 홉의 산출 상한.

    상한에 걸려 잘린 것과 원래 없는 것을 구분해야 하므로, 각 홉의 `scanned`는 **자르기 전
    입력 수**다(잘린 뒤 수를 적으면 "적게 봤다"가 "적게 있다"로 보인다).
    """
    # ── 1홉: 성취기준 → 개념 키 (어휘별로 축을 나눠 묻는다) ───────────────
    alignment_stats: list[AlignmentJoinStats] = []
    keyed_axes: dict[str, set[str]] = {}
    for axes, outcome in ((_NORM_ID_AXES, norm_id), (_OFFICIAL_CODE_AXES, official_code)):
        result = await get_alignments(
            session, outcome_id=outcome, axes=axes, limit=concept_limit, require_nonempty=True
        )
        alignment_stats.append(result.stats)
        for item in result.alignments:
            keyed_axes.setdefault(item.concept_key, set()).add(item.axis.value)

    concept_keys = sorted(keyed_axes)[:concept_limit]
    by_code, by_atom = await _resolve_concepts(session, concept_keys)

    concepts = tuple(
        LearningMapConcept(
            concept_key=key,
            axes=tuple(sorted(keyed_axes[key])),
            concept_id=by_code[key].concept_id if key in by_code else None,
            name_ko=(by_code[key].name_ko if key in by_code else None)
            or (by_atom[key].name_ko if key in by_atom else None),
            resolved_from=tuple(
                name
                for name, hit in (("concept", key in by_code), ("atom_node", key in by_atom))
                if hit
            ),
        )
        for key in concept_keys
    )
    concept_stats = HopStats(
        scanned=len(keyed_axes),
        resolved=sum(1 for c in concepts if c.resolved_from),
        produced=len(concepts),
    )

    # ── 2홉: 개념 → 스킬 (behavior_skills 참조 배열 — 신규 엣지 타입 0) ────
    skill_sources: dict[str, set[str]] = {}
    for key in concept_keys:
        # 두 키 공간의 행을 모두 본다. `getattr(row, ..., None)`로 뭉개지 않는 이유: 모델에서
        # 컬럼이 사라져도 조용히 빈 목록이 되어 **스킬 0건이 '없음'으로 위장**된다(침묵 실패).
        # None(미해소)만 건너뛰고, 실재하는 행에는 컬럼 접근을 그대로 시켜 부재를 드러낸다.
        for row in (by_code.get(key), by_atom.get(key)):
            if row is None:
                continue
            for skill_id in row.behavior_skills or ():
                skill_sources.setdefault(skill_id, set()).add(key)
    skill_rows = (
        (
            await session.execute(
                sa.select(SkillNode).where(SkillNode.skill_id.in_(sorted(skill_sources)))
            )
        )
        .scalars()
        .all()
        if skill_sources
        else []
    )
    skills = tuple(
        LearningMapSkill(
            skill_id=row.skill_id,
            name_ko=row.name_ko,
            behavior_area=row.behavior_area.value,
            family=row.family,
            mastery_estimable=row.mastery_estimable,
            via_concept_keys=tuple(sorted(skill_sources[row.skill_id])),
        )
        for row in sorted(skill_rows, key=lambda r: r.skill_id)
    )
    skill_stats = HopStats(
        scanned=len(skill_sources), resolved=len(skill_rows), produced=len(skills)
    )

    # ── 3홉: 개념 → 문제 (problem_concept N:M) ───────────────────────────
    concept_ids = [c.concept_id for c in concepts if c.concept_id is not None]
    problem_rows: list[tuple[Problem, uuid.UUID]] = []
    if concept_ids:
        rows = await session.execute(
            sa.select(Problem, ProblemConcept.concept_id)
            .join(ProblemConcept, ProblemConcept.problem_id == Problem.problem_id)
            .where(ProblemConcept.concept_id.in_(concept_ids))
            .order_by(Problem.problem_id)
        )
        problem_rows = list(rows.all())  # type: ignore[arg-type]
    via_by_problem: dict[uuid.UUID, set[uuid.UUID]] = {}
    problem_by_id: dict[uuid.UUID, Problem] = {}
    for problem, cid in problem_rows:
        problem_by_id[problem.problem_id] = problem
        via_by_problem.setdefault(problem.problem_id, set()).add(cid)
    problems = tuple(
        LearningMapProblem(
            problem_id=pid,
            question_format=_enum_value(problem_by_id[pid].question_format),
            answer_format=_enum_value(problem_by_id[pid].answer_format),
            difficulty_overall=_as_float(problem_by_id[pid].difficulty_overall),
            via_concept_ids=tuple(sorted(via_by_problem[pid])),
        )
        for pid in sorted(via_by_problem)[:problem_limit]
    )
    problem_stats = HopStats(
        scanned=len(concept_ids), resolved=len(via_by_problem), produced=len(problems)
    )

    # ── 4홉: 개념·스킬 → 오개념 (두 경로 — 개념 느슨참조 / 행동스킬 배열) ──
    skill_ids = [s.skill_id for s in skills]
    mis_rows: list[MisconceptionCatalog] = []
    if concept_keys or skill_ids:
        clauses = []
        if concept_keys:
            clauses.append(MisconceptionCatalog.concept_src_id.in_(concept_keys))
        if skill_ids:
            clauses.append(MisconceptionCatalog.behavior_skills.overlap(skill_ids))
        mis_rows = list(
            (
                await session.execute(
                    sa.select(MisconceptionCatalog)
                    .where(sa.or_(*clauses))
                    .order_by(MisconceptionCatalog.mis_id)
                )
            )
            .scalars()
            .all()
        )
    concept_key_set, skill_id_set = set(concept_keys), set(skill_ids)
    misconceptions = tuple(
        LearningMapMisconception(
            mis_id=row.mis_id,
            canonical_statement=row.canonical_statement,
            error_type=row.error_type,
            severity=row.severity,
            matched_by=tuple(
                name
                for name, hit in (
                    ("concept_src_id", row.concept_src_id in concept_key_set),
                    ("behavior_skills", bool(set(row.behavior_skills or ()) & skill_id_set)),
                )
                if hit
            ),
        )
        for row in mis_rows[:misconception_limit]
    )
    misconception_stats = HopStats(
        scanned=len(concept_keys) + len(skill_ids),
        resolved=len(mis_rows),
        produced=len(misconceptions),
    )

    return LearningMap(
        norm_id=norm_id,
        official_code=official_code,
        concepts=concepts,
        skills=skills,
        problems=problems,
        misconceptions=misconceptions,
        concept_stats=concept_stats,
        skill_stats=skill_stats,
        problem_stats=problem_stats,
        misconception_stats=misconception_stats,
        alignment_stats=tuple(alignment_stats),
    )


def _enum_value(value: object) -> str | None:
    """Enum이면 값, 아니면 그대로 — Core는 수학 의미론을 해석하지 않고 실어 나르기만 한다."""
    if value is None:
        return None
    return str(getattr(value, "value", value))


def _as_float(value: object) -> float | None:
    """Numeric(Decimal)을 JSON 친화 float로 — 값의 의미는 해석하지 않는다."""
    return None if value is None else float(value)  # type: ignore[arg-type]
