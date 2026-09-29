"""`hints` 테이블의 유일 writer·reader + 생성 원천 로더 (S4-11 · D3).

연기 해제 전제 3종(MEMORY 2026-07-08 Phase 6b) 중 **① 생성 writer의 영속 절반**과 **③ 서빙
reader**가 이 모듈에 산다(② 검증은 `gates.py`, 생성은 `generator.py`, 오프라인 실행은
`populate.py`). `hints`에 쓰고 읽는 코드는 이 모듈뿐이다 — 테이블 접근점을 한 곳으로 모은다
(`l2/learner_state_store.py` EOS-103 선례 — `scripts/analysis/data_access_layer_audit.py`
baseline에 이 파일 1줄이 느는 대신 그 테이블의 접근점은 영구히 1개다).

원천 로더(`load_path_inputs`):
  - 경로·단계 읽기는 L3 `solution_path_store`를 **다운콜**한다(경로 읽기 단일 표면 — 재구현
    금지). L4→L3 방향이라 계층 계약 그대로다.
  - 개념 이름은 **원자 백본 축에서만** 읽는다(runtime truth source = 원자 백본 단일 · 구 437
    `concept_node`는 `legacy_snapshot`이라 런타임 reader 금지 — `test_legacy_snapshot_governance`).
    조회 좌석은 L2 추천이 쓰는 것과 같은 `l1.atom_graph.axis.fetch_atom_axis_meta`(async 세션
    단일 IN 조회 · `atom_node.name_ko`)다.
    ① 단계 코드(`problem_step.concept_node_id` — 사람 검수로 채워짐)가 원자 축에 있으면 그 이름.
    ② 없으면 문제 대표 개념(`l2.get_primary_concept_id` 재사용 — PRIMARY→TESTED · `api/coach.py`와
       같은 공개 export 경유 — 숙달 *writer* 모듈은 임포트하지 않는다)의 `concept.code`를 같은 원자
       축으로 해석한다(`api/coach._standard_code_for`와 같은 해석 사슬).
    ③ 둘 다 없으면 None(L1을 만들지 않는다 — 날조 금지). 원자 축 **밖** 코드(구 437 UC 등)는
       "메타 누락"이 아니라 축 밖이므로 이름을 쓰지 않고 `concept_codes_off_axis`로 계상한다
       (`l1/atom_graph/axis.py` docstring "미스의 의미" — 조용히 None으로 흘리지 않는다).
  - 정답: `problem.answer`를 **들고 넘기기만** 한다(게이트 B의 판정 함수로 — EOS 불투명 페이로드
    원칙: Core는 이 값을 해석하지 않는다).

writer(`write_hints`·`persist_generation`):
  - 결정론 hint_id로 기존 행을 조회해 insert / 내용이 바뀐 행만 update / 같으면 unchanged —
    두 번 실행하면 두 번째는 전부 unchanged다(헌법 R3-01 '두 번 실행' 계약).
  - **은퇴**: 이번 실행이 처리한 경로에 속하지만 이번에 생성되지 않은 기존 힌트(예: 단계 개념이
    바뀌어 L1이 사라짐)는 삭제하지 않고 verified=false로 내린다 — 서빙에서 즉시 빠지고, 왜
    내려갔는지가 gate_report에 남는다.

reader(`find_served_hint`):
  - `verified=true`만 읽는다(yaml invariant "verified=false 인 Hint 는 학생에게 제공 불가").
    쿼리 조건과 행 재확인의 이중 가드 — 둘 중 하나가 빠져도 미검수 행은 나가지 않는다.
  - Level 4(또는 1~3 밖)는 쿼리하지 않고 None — 전체 풀이는 Hint 엔티티 밖 안전망이다.
  - 단계 선택: "학생이 아직 적지 않은 첫 단계 이후의 가장 이른 검수 힌트"
    (`serving_step_order` — 제출한 풀이 단계 수 + 1). **정직한 한계**: 학생 단계와 경로 단계의
    정렬은 개수 기반이다 — 학생이 단계를 합치거나 쪼개면 어긋날 수 있다. 정렬(LCS 등)은
    `solution_module_gap_review.md` D5(채점 심화 페이퍼)의 축이라 여기서 만들지 않는다.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.concept import Concept
from whymath_backend.db.models.hint import Hint as HintORM
from whymath_backend.db.models.problem import Problem
from whymath_backend.l1.atom_graph.axis import fetch_atom_axis_meta
from whymath_backend.l2 import get_primary_concept_id
from whymath_backend.l3.solution_path_store import (
    get_solution_path,
    get_solution_path_steps,
    list_step_materialized_path_ids,
)
from whymath_backend.l4.hint_content.generator import ConceptRef
from whymath_backend.l4.hint_content.models import (
    HINT_LEVELS,
    Hint,
    ServedHint,
)

logger = logging.getLogger("whymath.l4.hint_content.store")

__all__ = [
    "HintWriteCounts",
    "PathInput",
    "PathLoadReport",
    "find_served_hint",
    "hint_from_row",
    "hint_to_columns",
    "load_path_inputs",
    "persist_generation",
    "serving_step_order",
    "write_hints",
]

# 은퇴 표지 — 재생성에서 사라진 힌트를 내릴 때 gate_report에 남기는 키.
_RETIRED_KEY = "retired"


@dataclass(frozen=True)
class PathInput:
    """경로 1개의 생성 원천 — 단계 본문·검증 플래그·단계별 개념·문제 정답(불투명)."""

    solution_path_id: str
    problem_id: uuid.UUID
    step_contents: tuple[str, ...]
    step_verified: tuple[bool, ...]
    step_concepts: tuple[ConceptRef | None, ...]
    final_answer: str | None


@dataclass
class PathLoadReport:
    """원천 로드 정직 회계 — 몇 경로를 봤고 왜 몇 개를 못 썼는지(조용한 생략 0)."""

    paths_seen: int = 0
    paths_loaded: int = 0
    skipped_missing_header: int = 0
    skipped_noncontiguous_steps: int = 0
    answers_missing: int = 0
    concepts_from_step: int = 0
    concepts_from_problem: int = 0
    concepts_missing: int = 0
    # 원자 축 밖으로 판정돼 이름을 쓰지 않은 코드 수(단계·문제 대표 코드 합산 — 제외 사유 계상).
    concept_codes_off_axis: int = 0
    skipped_path_ids: list[str] = field(default_factory=list)


@dataclass
class HintWriteCounts:
    """writer 회계 — insert·update·unchanged·retired(두 번째 실행은 전부 unchanged여야 한다)."""

    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    retired: int = 0


def serving_step_order(solution_steps: Sequence[str] | None) -> int:
    """서빙 대상 단계 하한 — 학생이 적은 (비어 있지 않은) 풀이 단계 수 + 1(개수 기반 정렬)."""
    written = sum(1 for step in solution_steps or () if step.strip())
    return written + 1


# ── 원천 로더 ──────────────────────────────────────────────────────────


async def _problem_concept(
    session: AsyncSession, problem_id: uuid.UUID, report: PathLoadReport
) -> ConceptRef | None:
    """문제 대표 개념(PRIMARY→TESTED)의 code를 **원자 축**에서 해석 — 축 밖·미매핑이면 None.

    이름은 `concept.name_ko`가 아니라 원자 축 메타(`atom_node.name_ko`)에서 읽는다 — `concept`
    테이블에는 원자 행과 구 437 행이 code로 병존하므로, 축 판정 없이 이름을 쓰면 구 437 데이터가
    런타임 콘텐츠로 새어 나간다(`l1/atom_graph/axis.py` "교차 축 조인" 경고와 같은 이유).
    """
    concept_uuid = await get_primary_concept_id(session, problem_id)
    if concept_uuid is None:
        return None
    concept = await session.get(Concept, concept_uuid)
    if concept is None:
        return None
    meta = await fetch_atom_axis_meta(session, [concept.code])
    atom = meta.get(concept.code)
    if atom is None:
        report.concept_codes_off_axis += 1
        return None
    return ConceptRef(concept_id=concept.code, name=atom.name_ko, source="problem_primary")


async def load_path_inputs(session: AsyncSession) -> tuple[list[PathInput], PathLoadReport]:
    """단계가 실체화된 전 경로의 생성 원천을 모은다(읽기 전용 — commit 없음)."""
    report = PathLoadReport()
    inputs: list[PathInput] = []
    for path_id in await list_step_materialized_path_ids(session):
        report.paths_seen += 1
        header = await get_solution_path(session, path_id)
        if header is None:
            report.skipped_missing_header += 1
            report.skipped_path_ids.append(path_id)
            continue
        steps = await get_solution_path_steps(session, path_id)
        orders = [step.step_order for step in steps]
        if orders != list(range(1, len(steps) + 1)):
            # 단계가 1부터 연속이 아니면 흐름·시연 문장이 거짓이 된다 — 원천 결함으로 건너뛴다.
            report.skipped_noncontiguous_steps += 1
            report.skipped_path_ids.append(path_id)
            continue
        problem = await session.get(Problem, header.problem_id)
        final_answer = problem.answer if problem is not None else None
        if final_answer is None:
            report.answers_missing += 1
        # 단계 코드를 원자 축에서 한 번에 해석(경로당 IN 조회 1회 · 코드 없으면 쿼리 0).
        step_codes = sorted({s.concept_node_id for s in steps if s.concept_node_id is not None})
        step_meta = await fetch_atom_axis_meta(session, step_codes)
        report.concept_codes_off_axis += sum(1 for code in step_codes if code not in step_meta)
        problem_concept: ConceptRef | None = None
        problem_concept_loaded = False
        concepts: list[ConceptRef | None] = []
        for step in steps:
            code = step.concept_node_id
            atom = step_meta.get(code) if code is not None else None
            concept: ConceptRef | None = None
            if code is not None and atom is not None:
                concept = ConceptRef(concept_id=code, name=atom.name_ko, source="step")
                report.concepts_from_step += 1
            else:
                if not problem_concept_loaded:
                    problem_concept = await _problem_concept(session, header.problem_id, report)
                    problem_concept_loaded = True
                concept = problem_concept
                if concept is not None:
                    report.concepts_from_problem += 1
                else:
                    report.concepts_missing += 1
            concepts.append(concept)
        inputs.append(
            PathInput(
                solution_path_id=path_id,
                problem_id=header.problem_id,
                step_contents=tuple(step.expected_answer or "" for step in steps),
                step_verified=tuple(step.sympy_verified is True for step in steps),
                step_concepts=tuple(concepts),
                final_answer=final_answer,
            )
        )
        report.paths_loaded += 1
    return inputs, report


# ── 매핑 ──────────────────────────────────────────────────────────────


def hint_to_columns(hint: Hint) -> dict[str, object]:
    """Pydantic Hint → `hints` 컬럼 값(hint_id·시각 제외). 비교·insert·update 공용."""
    ref = hint.solution_step_ref
    return {
        "solution_path_id": ref.solution_path_id,
        "step_order": ref.step_order,
        "problem_id": ref.problem_id,
        "level": hint.level,
        "content": hint.content,
        "socratic_category": (
            hint.socratic_category.value if hint.socratic_category is not None else None
        ),
        "reveals_concept_names": hint.reveals.reveals_concept_names,
        "reveals_step_flow": hint.reveals.reveals_step_flow,
        "reveals_partial_computation": hint.reveals.reveals_partial_computation,
        "revealed_concept_ids": list(hint.reveals.revealed_concept_ids),
        "reveal_score": hint.reveals.reveal_score,
        "verified": hint.verified,
        "gate_report": dict(hint.gate_report),
        "generator_version": hint.generator_version,
    }


def hint_from_row(row: HintORM) -> Hint:
    """`hints` 행 → Pydantic Hint(검증 복원 — level 1~3·reveal_score 파생 일치 재검증).

    `model_validate`로 복원한다 — DB 값이 계약(level Literal·점수 파생·카테고리 6종)을 벗어나면
    여기서 ValidationError가 난다(서빙 reader가 그 행을 내보내지 않는 근거).
    """
    return Hint.model_validate(
        {
            "hint_id": row.hint_id,
            "solution_step_ref": {
                "solution_path_id": row.solution_path_id,
                "step_order": row.step_order,
                "problem_id": row.problem_id,
            },
            "level": row.level,
            "reveals": {
                "reveals_concept_names": row.reveals_concept_names,
                "reveals_step_flow": row.reveals_step_flow,
                "reveals_partial_computation": row.reveals_partial_computation,
                "revealed_concept_ids": tuple(row.revealed_concept_ids or ()),
                "reveal_score": row.reveal_score,
            },
            "content": row.content,
            "socratic_category": row.socratic_category,
            "verified": row.verified,
            "gate_report": dict(row.gate_report or {}),
            "generator_version": row.generator_version,
        }
    )


# ── writer ────────────────────────────────────────────────────────────


async def write_hints(
    session: AsyncSession,
    hints: Sequence[Hint],
    *,
    processed_path_ids: Iterable[str] = (),
) -> HintWriteCounts:
    """힌트를 멱등 upsert하고, 처리한 경로에서 사라진 기존 힌트를 은퇴시킨다(flush만).

    commit은 호출자(`persist_generation`) — 저장소 패턴. 내용 동일 행은 건드리지 않는다
    (updated_at도 그대로 — '두 번 실행' 시 결과가 같아야 한다). `updated_at`은 이 모듈이 대입하지
    않는다 — ORM `onupdate`가 UPDATE 발생 시에만 갱신한다(내용 변경 = UPDATE = 갱신이 한 축).
    """
    counts = HintWriteCounts()
    ids = [hint.hint_id for hint in hints]
    existing: dict[str, HintORM] = {}
    if ids:
        result = await session.execute(select(HintORM).where(HintORM.hint_id.in_(ids)))
        existing = {row.hint_id: row for row in result.scalars().all()}
    for hint in hints:
        columns = hint_to_columns(hint)
        row = existing.get(hint.hint_id)
        if row is None:
            session.add(HintORM(hint_id=hint.hint_id, **columns))
            counts.inserted += 1
            continue
        if all(getattr(row, key) == value for key, value in columns.items()):
            counts.unchanged += 1
            continue
        for key, value in columns.items():
            setattr(row, key, value)
        counts.updated += 1

    path_ids = sorted(set(processed_path_ids))
    if path_ids:
        keep = set(ids)
        stale = await session.execute(
            select(HintORM).where(
                HintORM.solution_path_id.in_(path_ids),
                HintORM.verified.is_(True),
            )
        )
        for row in stale.scalars().all():
            if row.hint_id in keep:
                continue
            row.verified = False
            row.gate_report = {
                **dict(row.gate_report or {}),
                _RETIRED_KEY: "재생성에서 더는 만들어지지 않아 서빙에서 내림(삭제 아님)",
                "passed": False,
            }
            counts.retired += 1
    await session.flush()
    return counts


async def persist_generation(
    session: AsyncSession,
    hints: Sequence[Hint],
    *,
    processed_path_ids: Iterable[str],
) -> HintWriteCounts:
    """오프라인 생성 결과를 한 트랜잭션으로 적재·commit(`populate --apply`의 유일 쓰기 경로)."""
    counts = await write_hints(session, hints, processed_path_ids=processed_path_ids)
    await session.commit()
    return counts


# ── reader (coach 서빙) ───────────────────────────────────────────────


async def find_served_hint(
    session: AsyncSession,
    *,
    problem_id: uuid.UUID,
    hint_level: int,
    from_step_order: int,
) -> ServedHint | None:
    """이 문제·이 레벨에서 `from_step_order` 이후 가장 이른 **검수 통과** 힌트 1개.

    레벨이 1~3 밖(=4 전체 풀이)이면 쿼리하지 않는다. 행이 Pydantic 복원에 실패하면(DB가 계약을
    벗어난 경우) 서빙하지 않고 예외 타입명과 함께 경고한다(침묵 실패 금지·깨진 행이 학생에게
    나가지 않는다).
    """
    if hint_level not in HINT_LEVELS:
        return None
    stmt = (
        select(HintORM)
        .where(
            HintORM.problem_id == problem_id,
            HintORM.level == hint_level,
            HintORM.verified.is_(True),
            HintORM.step_order >= max(1, from_step_order),
        )
        .order_by(HintORM.step_order, HintORM.solution_path_id)
        .limit(1)
    )
    result = await session.execute(stmt)
    row = result.scalars().first()
    # 이중 가드 — 쿼리 조건이 빠져도 미검수·타입 불일치 행은 나가지 않는다.
    if not isinstance(row, HintORM) or row.verified is not True:
        return None
    try:
        hint = hint_from_row(row)
    except (ValidationError, ValueError) as exc:
        logger.warning(
            "hints 행 복원 실패 — 서빙하지 않음 hint_id=%s exc_type=%s",
            row.hint_id,
            type(exc).__name__,
        )
        return None
    return ServedHint(
        hint_id=hint.hint_id,
        level=hint.level,
        step_order=hint.solution_step_ref.step_order,
        content=hint.content,
        socratic_category=hint.socratic_category,
        reveal_score=hint.reveals.reveal_score,
    )
