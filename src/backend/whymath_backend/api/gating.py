"""L6 응용 모드 게이팅 HTTP API — 6개 응용 모드(아래 엔드포인트)를 HTTP로 노출.

엔드포인트(prefix `/v1/gating`):
  - GET /v1/gating/retake           — RT(재수전용/N수) 트랙 게이팅 결과(페르소나 B·C 대상).
  - GET /v1/gating/suneung          — 수능(정시) 모드 게이팅 결과(페르소나 A·B·C 대상).
  - GET /v1/gating/school-progress  — 학교진도 모드 게이팅 결과(페르소나 A·D 대상). 단원·성취기준
    고시코드 정합(OR·성취기준이 더 세밀). 성취기준 코드는 원자 축 조인(problem_concept→concept→
    atom_node.standard_codes·S2-03 재연결)으로 후보에 주입(school-progress 전용 의존성).
  - GET /v1/gating/thinking         — 사고력 모드 게이팅 결과(Bloom 상위 3단계 주신호·D·E 주 대상).
  - GET /v1/gating/metacognition    — 메타인지 모드(distractor_map 주신호·전 페르소나 공유 코어).
  - GET /v1/gating/gifted           — 영재 트랙 게이팅 결과(심화+창안/융합·페르소나 E 전용).

레이어 경계(CLAUDE.md 7계층): 이 라우터는 **L5(상호작용·api)** 표면이다. L6 응용 모드
게이팅(`whymath_backend.l6`)을 *호출(소비)*해 HTTP로 노출할 뿐, 게이팅 로직을 *구현하지
않는다*(경계 침범 금지). 그리고 L6 게이팅 자신은 **L6→L1만** 의존한다 — 후보 문항은 L1
영속 레이어(`db.models.problem.Problem`)를 `get_session`으로 읽어 `to_schema()`로 L1
Pydantic(`schema.problem.Problem`)으로 복원한 뒤 게이팅에 넘긴다(L6은 L1 필드의 *존재·값*만
본다). 즉 흐름은 `HTTP → get_session(PG) → ORM Problem → to_schema() → L6 게이팅 →
list[ProblemSchema]`이며, api 레이어는 "DB 조회 + L6 함수 호출 + schema 반환" 조합만 한다.

**게이팅이 저작권·페르소나 진실 게이트**(CLAUDE.md 우선순위 #2 법적 ≫ #5 UX): 어떤 문항을
어떤 페르소나에게 노출해도 되는가의 판정 — 저작권 노출 가능성(`is_exposable`)·대상 페르소나·
진도/시험 정합 — 은 **전부 L6 게이팅이** 수행한다. 이 라우터의 SQL 조회는 *후보 축소*가
목적인 *최소* 조회이며(사전 필터 없이 단순 `select(Problem)` + fetch 상한), 게이팅이 모든
부적격 문항을 거른다. 특히 **평가원/EBS/교과서처럼 본문 미보유(구조 메타 전용) 출처는 학생
노출이 불가**하므로(저작권법 §32 단서·영리 금지) L6 저작권 게이트가 응답에서 원천 차단한다 —
이 라우터는 그 차단을 우회하지 않는다(테스트로 입증).

세션 결선·`SessionDep` 의존성 패턴은 problems.py와 동일(session.py 계약). 응답은 게이팅이
선별·우선순위 정렬·limit 적용을 마친 목록을 **공개 투영(`PublicProblem`)으로 변환해**
돌려준다(SEC-24(원 SEC-15) — `functional_security_audit_2026-08-08.md` M1): 이 6개
엔드포인트는 무인증이라 정답류 필드(`PUBLIC_HIDDEN_ANSWER_FIELDS` — answer·distractor_map
등)를 키째 싣지 않는다(키 부재가 계약·problems.py GET과 동일). 게이팅 *입력*은 전체
`ProblemSchema` 그대로다 — 메타인지 모드의 주신호(distractor_map 존재) 같은 판정 재료는
서버 내부에서만 쓰고 응답에는 싣지 않는다(신호는 쓰되 노출하지 않음).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.api._l6_mode_reach_state import (
    GIFTED as _MODE_GIFTED,
)
from whymath_backend.api._l6_mode_reach_state import (
    METACOGNITION as _MODE_METACOGNITION,
)
from whymath_backend.api._l6_mode_reach_state import (
    RETAKE as _MODE_RETAKE,
)
from whymath_backend.api._l6_mode_reach_state import (
    SCHOOL_PROGRESS as _MODE_SCHOOL_PROGRESS,
)
from whymath_backend.api._l6_mode_reach_state import (
    SUNEUNG as _MODE_SUNEUNG,
)
from whymath_backend.api._l6_mode_reach_state import (
    THINKING as _MODE_THINKING,
)
from whymath_backend.api._l6_mode_reach_state import get_l6_mode_reach_counters
from whymath_backend.db.models.atom_node import AtomNode
from whymath_backend.db.models.concept import Concept, ProblemConcept
from whymath_backend.db.models.problem import Problem
from whymath_backend.db.session import get_session
from whymath_backend.l1.curriculum.curriculum_resolve import CurriculumDepthResolver
from whymath_backend.l6 import (
    select_gifted_items,
    select_metacognition_items,
    select_retake_items,
    select_school_progress_items,
    select_suneung_items,
    select_thinking_items,
)
from whymath_backend.schema.enums import Curriculum, Persona, RequiredDepth
from whymath_backend.schema.problem import Problem as ProblemSchema
from whymath_backend.schema.problem import PublicProblem

router = APIRouter(prefix="/v1/gating", tags=["gating"])

_logger = logging.getLogger(__name__)

SessionDep = Annotated[AsyncSession, Depends(get_session)]

# 게이팅에 넘길 후보 문항 fetch 상한(합리적 상한) — 게이팅은 *메모리 안에서* 적격성·우선순위·
# limit을 적용하므로, DB에서는 후보를 *최소 사전 필터 없이* 한 번에 끌어와 게이팅이 모두 거르게
# 한다(게이팅이 진실 게이트라는 설계 규칙). 다만 무제한 조회는 비현실적이라 상한을 둔다 —
# 게이팅이 다시 limit으로 줄이므로 이 상한은 "게이팅에 먹일 후보 풀의 크기"일 뿐 응답 크기가
# 아니다. 응답 limit은 각 엔드포인트의 `limit` 쿼리 파라미터(기본 20·최대 200)가 정한다.
# (사전 필터를 두지 않는 이유: 저작권·페르소나·진도 정합 판정을 SQL로 흩지 않고 L6 한 곳에
# 모은다 — SQL 사전 필터가 없어도 게이팅이 부적격을 전부 차단해 *입증 가능한 단일 게이트*가 된다.)
# PB-03 축③ — 현재 코퍼스(2026-08 기준 7종 2,647건)+여유를 감안해 1000→3000으로 상향. 이
# sandbox에는 살아있는 Postgres가 없어 실측 성능 비교는 못 했다(정직한 공백 — 보수적으로
# 상향한 것뿐이다). SQL 사전축소로의 재설계는 이번 범위 밖(성능 실측 후 별도 후속).
_CANDIDATE_FETCH_LIMIT = 3000


async def _fetch_candidates(session: SessionDep) -> list[ProblemSchema]:
    """게이팅에 넘길 후보 문항을 L1 영속 레이어에서 읽어 L1 schema로 복원한다.

    `select(Problem)`(ORM)으로 후보를 fetch 상한(`_CANDIDATE_FETCH_LIMIT`)까지 끌어와, 각
    ORM 행을 `to_schema()`로 `schema.Problem`(Pydantic)으로 변환해 돌려준다. **사전 SQL 필터를
    두지 않는다** — 저작권/페르소나/진도 정합 판정은 전부 L6 게이팅 소관이며(라우터 docstring),
    이 함수는 후보를 *축소만*(상한) 한다. `to_schema()`는 본문 미보유 불변식을 다시 통과시키므로
    (problem.py `to_schema` 계약) 게이팅에는 항상 검증된 L1 모델만 들어간다.

    안정적 결과를 위해 `created_at desc, problem_id`로 정렬한다(problems.py 목록과 동일 보조키 —
    동일 created_at에서도 결정적 순서). 게이팅이 다시 우선순위로 재정렬하지만, fetch 상한에 걸릴
    때 *어떤* 후보가 잘리는지를 결정적으로 만들기 위함이다.

    PB-03 축③ — 절단 관측: fetch 결과 건수가 정확히 `_CANDIDATE_FETCH_LIMIT`와 같으면(절단
    의심 신호) 전체 행 수를 `SELECT count(*)`로 추가 조회해 `logger.warning`으로 남긴다. 조용한
    절단(silent truncation)을 남기지 않는다(CLAUDE.md 침묵 실패 금지의 구체화).

    Args:
      session: 요청 수명 AsyncSession(`get_session` 주입).

    Returns:
      후보 문항의 `schema.Problem` 리스트(최대 `_CANDIDATE_FETCH_LIMIT`개·게이팅 입력).
    """
    stmt = (
        select(Problem)
        .order_by(Problem.created_at.desc(), Problem.problem_id)
        .limit(_CANDIDATE_FETCH_LIMIT)
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()
    if len(rows) == _CANDIDATE_FETCH_LIMIT:
        # 절단 의심 — fetch 건수가 상한과 정확히 같다. 전체 행 수를 별도 조회해 실제 절단
        # 여부·규모를 로그로 남긴다(조용히 넘기지 않는다).
        total = (await session.execute(select(func.count()).select_from(Problem))).scalar_one()
        truncated = max(total - _CANDIDATE_FETCH_LIMIT, 0)
        _logger.warning(
            "gating candidate fetch truncated: fetched=%d total=%d truncated=%d",
            len(rows),
            total,
            truncated,
        )
    return [row.to_schema() for row in rows]


CandidatesDep = Annotated[list[ProblemSchema], Depends(_fetch_candidates)]


# ──────────────────────────────────────────────────────────────────────────
# 성취기준 조인 — school-progress 전용(다른 3모드는 조인 비용 안 얹음)
# ──────────────────────────────────────────────────────────────────────────
# 자동 커리큘럼 정렬 깊이 축의 국가(Phase 1 KR). curriculum_entry는 (concept × country) 셀이라
# 깊이 해석은 국가별이다 — school-progress는 한국 재학생 모드이므로 KR 셀을 본다.
_DEPTH_COUNTRY_CODE = "KR"

# RequiredDepth 위계(얕음→깊음) 서수 — 한 문항이 여러 개념을 다루면 *가장 깊은* 요구 깊이를 택한다
# (문항은 그 개념들이 요구하는 가장 깊은 깊이에 맞춰 출제돼야 함·06 §자동정렬-3).
_DEPTH_ORDER: dict[RequiredDepth, int] = {
    RequiredDepth.awareness: 0,
    RequiredDepth.procedural: 1,
    RequiredDepth.conceptual: 2,
    RequiredDepth.mastery: 3,
}


async def _fetch_achievement_codes(
    session: AsyncSession, problem_ids: list[uuid.UUID]
) -> dict[uuid.UUID, set[str]]:
    """문항 id 목록 → {problem_id: {성취기준 코드, ...}} (원자 축 조인·N+1 없음).

    **원자 축 전환(S2-03)**: problem_concept가 원자 백본 행(code=원자코드)을 가리키도록
    재연결되면서(`l1/problem_bank/populate` §원자 재연결), 구 4단계 조인(`concept_standard_link`
    → `achievement_standard` — 구 437 code 공간·재연결 후 0행)을 원자 축으로 교체했다. 경로:
    `problem_concept`(문항↔개념 N:M) → `concept`(원자 행) → `atom_node`(원자 메타 프로젝션·
    `AtomNode.code == Concept.code` 동일 키 공간). `atom_node.standard_codes`(NCIC 코드 배열)의
    형식은 구 `achievement_standard.official_code`와 동일(고시코드 — 예 '[10공수1-02-02]')이라
    소비처(L6 진도 정합)의 매칭 축이 불변이다. 배열 컬럼이라 행별 코드 배열을 파이썬에서
    평탄화한다(`{problem_id: set(codes)}`).

    curriculum_entry 깊이 조인(`_fetch_problem_concept_codes` → resolver)의 원자 축 정렬은
    S2-07 완료 — 크로스워크 전파로 유도한 원자-키 curriculum_entry 행(`l1/curriculum/
    curriculum_loader.py` `derive_atom_curriculum_entries`)이 적재되어 조인이 hit한다.

    `me.py`의 `select(...).join(...).where(...in_(...))` 선례를 답습한 *단일 쿼리 IN 일괄*이라
    후보 수와 무관하게 쿼리 1회(N+1 0). INNER 조인이라 원자 행이 달린 (문항,개념) 행만 나오고,
    성취기준 코드가 하나도 없는 문항은 결과 dict의 *키 자체가 없다*(주입 시 빈 리스트로 남음).

    Args:
      session: 요청 수명 AsyncSession.
      problem_ids: 성취기준을 조회할 문항 id 목록(후보 풀). 비면 빈 dict(쿼리 생략).

    Returns:
      `{problem_id: {성취기준 코드, ...}}` — 성취기준이 하나도 없는 문항은 키 부재.
    """
    if not problem_ids:
        return {}
    stmt = (
        select(ProblemConcept.problem_id, AtomNode.standard_codes)
        .join(Concept, ProblemConcept.concept_id == Concept.concept_id)
        .join(AtomNode, AtomNode.code == Concept.code)
        .where(ProblemConcept.problem_id.in_(problem_ids))
    )
    result = await session.execute(stmt)
    mapping: dict[uuid.UUID, set[str]] = {}
    for problem_id, standard_codes in result.all():
        # 배열 컬럼 평탄화 — 빈 배열 행은 키를 만들지 않는다(구 INNER 조인 의미 보존).
        if not standard_codes:
            continue
        mapping.setdefault(problem_id, set()).update(standard_codes)
    return mapping


async def _fetch_problem_concept_codes(
    session: AsyncSession, problem_ids: list[uuid.UUID]
) -> dict[uuid.UUID, set[str]]:
    """문항 id 목록 → {problem_id: {concept code, ...}} (2단계 조인·N+1 없음).

    경로: `problem_concept`(문항↔개념 N:M) → `concept`(개념). 조인 키
    `ProblemConcept.concept_id == Concept.concept_id`로 각 문항이 다루는 개념의 `code`(UC 브리지
    키 — `curriculum_entry.concept_id`와 동일 키 공간)를 모은다. 단일 IN 일괄 쿼리(N+1 0·
    `_fetch_achievement_codes` 선례 동형). 개념이 없는 문항은 결과 dict 키 부재(빈 깊이로 폴백).

    Args:
      session: 요청 수명 AsyncSession.
      problem_ids: 개념 코드를 조회할 문항 id 목록. 비면 빈 dict(쿼리 생략).

    Returns:
      `{problem_id: {concept_code, ...}}` — 개념이 없는 문항은 키 부재.
    """
    if not problem_ids:
        return {}
    stmt = (
        select(ProblemConcept.problem_id, Concept.code)
        .join(Concept, ProblemConcept.concept_id == Concept.concept_id)
        .where(ProblemConcept.problem_id.in_(problem_ids))
    )
    result = await session.execute(stmt)
    mapping: dict[uuid.UUID, set[str]] = {}
    for problem_id, code in result.all():
        mapping.setdefault(problem_id, set()).add(code)
    return mapping


async def _inject_curriculum_required_depth(
    session: AsyncSession, candidates: list[ProblemSchema]
) -> None:
    """후보 문항에 *교육과정 요구 깊이*(비영속 필드)를 curriculum_entry resolver로 주입(in-place).

    자동 커리큘럼 정렬 깊이 축(06_application_modes.md §자동정렬-3): 각 문항이 다루는 개념의 한국
    (KR) 교육과정 요구 깊이(`required_depth`)를 `curriculum_entry`에서 조회해, 한 문항이 여러 개념을
    다루면 *가장 깊은* 깊이를 `problem.curriculum_required_depth`에 넣는다(`_DEPTH_ORDER` 위계).

    경로: ① `_fetch_problem_concept_codes`로 {problem_id: {concept_code}} 조회(async) → ② 전체
    concept_code를 모아 `CurriculumDepthResolver.resolve_many`(sync·단일 SELECT·N+1 0)로
    {concept_code: RequiredDepth} 조회 — sync 엔진 좌석이라 `asyncio.to_thread`로 이벤트 루프를
    막지 않고 워커 스레드에 격리(`l1/atom_graph/retrieval.py` 검색 좌석과 동일 규약. 구
    weak_concept_recommendation 선례는 ARCH-13이 async 단일 엔진으로 옮겨 더는 인용처가 아니다) → ③
    문항별 *가장 깊은* 깊이 주입. curriculum_entry 미적재·깊이 미큐레이션·개념 미해석이면 키가 빠져
    None으로 남는다(L6 깊이정렬 무신호 폴백·데이터0 안전).

    Args:
      session: 요청 수명 AsyncSession.
      candidates: 깊이를 주입할 후보(in-place 변경).
    """
    if not candidates:
        return
    codes_by_problem = await _fetch_problem_concept_codes(
        session, [p.problem_id for p in candidates]
    )
    all_codes = sorted({code for codes in codes_by_problem.values() for code in codes})
    if not all_codes:
        return
    # sync 엔진 좌석(curriculum_entry resolver)을 워커 스레드에 격리 — 이벤트 루프 블로킹 금지.
    resolver = CurriculumDepthResolver()
    depth_by_code = await asyncio.to_thread(
        resolver.resolve_many, all_codes, country_code=_DEPTH_COUNTRY_CODE
    )
    if not depth_by_code:
        return
    for problem in candidates:
        codes = codes_by_problem.get(problem.problem_id)
        if not codes:
            continue
        depths = [depth_by_code[c] for c in codes if c in depth_by_code]
        if depths:
            # 여러 개념 → 가장 깊은 요구 깊이(_DEPTH_ORDER 위계)를 택해 주입.
            problem.curriculum_required_depth = max(depths, key=lambda d: _DEPTH_ORDER[d])


async def _fetch_candidates_with_standards(session: SessionDep) -> list[ProblemSchema]:
    """학교진도 후보를 읽고 *성취기준 코드*·*교육과정 요구 깊이*(비영속 필드)를 주입해 돌려준다.

    `_fetch_candidates`(기존 후보 조회·재사용)로 후보를 끌어온 뒤 두 비영속 신호를 주입한다:
      ① 성취기준 코드 — `_fetch_achievement_codes`(원자 축 조인·S2-03)로 `atom_node.standard_codes`
         를 일괄(IN) 조회해 각 `ProblemSchema.achievement_standard_codes`에 *결정적으로*(sorted)
         채운다(없으면 빈 리스트·단원/persona_fit 폴백).
      ② 교육과정 요구 깊이 — `_inject_curriculum_required_depth`(문항→개념 조인 + curriculum_entry
         resolver)로 각 문항 개념의 한국 교육과정 *가장 깊은* required_depth를
         `ProblemSchema.curriculum_required_depth`에 채운다(자동 커리큘럼 정렬 깊이 축). curriculum_
         entry 미적재·깊이 미큐레이션이면 None으로 남아 L6 깊이정렬이 무신호 폴백(데이터0 안전).

    school-progress 게이팅 핸들러 전용 의존성이라 retake·suneung·thinking은 이 조인 비용을 지지
    않는다(그들은 `CandidatesDep` 유지).

    Args:
      session: 요청 수명 AsyncSession(`get_session` 주입).

    Returns:
      성취기준 코드·교육과정 요구 깊이가 주입된 후보 `schema.Problem` 리스트(게이팅 입력).
    """
    candidates = await _fetch_candidates(session)
    codes = await _fetch_achievement_codes(session, [p.problem_id for p in candidates])
    for problem in candidates:
        if problem.problem_id in codes:
            # sorted로 결정적 순서(집합→리스트). 키 부재 문항은 기본 빈 리스트 유지.
            problem.achievement_standard_codes = sorted(codes[problem.problem_id])
    # 자동 커리큘럼 정렬 깊이 축 주입(curriculum_entry resolver·in-place·데이터0 시 None 폴백).
    await _inject_curriculum_required_depth(session, candidates)
    return candidates


SchoolProgressCandidatesDep = Annotated[
    list[ProblemSchema], Depends(_fetch_candidates_with_standards)
]


def _to_public(items: list[ProblemSchema]) -> list[PublicProblem]:
    """게이팅 결과(내부 정본) → 공개 투영 목록(SEC-24(원 SEC-15)).

    정답류 필드(`PUBLIC_HIDDEN_ANSWER_FIELDS`)는 대상 모델에 자리가 없어 변환에서
    구조적으로 사라진다(키 부재가 계약 — 모듈 docstring 참조).
    """
    return [PublicProblem.from_problem(item) for item in items]


@router.get(
    "/retake",
    response_model=list[PublicProblem],
    summary="RT(재수전용) 트랙 게이팅",
)
async def gating_retake(
    request: Request,
    candidates: CandidatesDep,
    persona: Annotated[Persona, Query(description="노출 대상 페르소나(필수). RT는 B·C 대상")],
    min_fit: Annotated[float, Query(description="persona_fit 임계값(0~1)")] = 0.5,
    limit: Annotated[int, Query(ge=1, le=200, description="응답 최대 개수")] = 20,
) -> list[PublicProblem]:
    """RT(재수전용/N수) 트랙 노출 문항을 게이팅해 반환한다(페르소나 B·C 대상).

    후보를 L1에서 읽어(`_fetch_candidates`) `select_retake_items`에 넘긴다 — 적격 필터(대상
    페르소나·저작권 노출 게이트·RT 적합 신호) → 우선순위 내림차순 안정정렬 → limit 적용까지
    *전부 L6 게이팅이* 수행한 결과를 그대로 돌려준다. 비대상 페르소나(A·D·E)는 게이팅이 전부
    걸러 빈 리스트가 된다. 평가원/EBS/교과서(본문 미보유) 출처는 저작권 게이트가 차단한다.
    """
    # 도달 관측(PB-04) — 성공/실패 무관하게 '이 핸들러에 요청이 닿았다'를 센다.
    get_l6_mode_reach_counters(request.app).record(_MODE_RETAKE)
    return _to_public(select_retake_items(candidates, persona, min_fit=min_fit, limit=limit))


@router.get(
    "/suneung",
    response_model=list[PublicProblem],
    summary="수능(정시) 모드 게이팅",
)
async def gating_suneung(
    request: Request,
    candidates: CandidatesDep,
    persona: Annotated[
        Persona, Query(description="노출 대상 페르소나. 수능은 A·B·C 대상")
    ] = Persona.A_일반고고3,
    min_fit: Annotated[float, Query(description="persona_fit 임계값(0~1)")] = 0.5,
    limit: Annotated[int, Query(ge=1, le=200, description="응답 최대 개수")] = 20,
) -> list[PublicProblem]:
    """수능(정시) 모드 노출 문항을 게이팅해 반환한다(페르소나 A·B·C 대상).

    후보를 L1에서 읽어 `select_suneung_items`에 넘긴다 — 적격 필터(대상 페르소나·저작권 노출
    게이트·수능 적합 신호) → 우선순위(출처 권위>시그니처>난이도) 내림차순 안정정렬 → limit
    적용까지 *전부 L6 게이팅이* 수행한 결과를 그대로 돌려준다. **수능 모드 특히 중요**: 평가원
    기출 *본문*은 절대 노출 불가 → 저작권 게이트가 원천 차단하고, 학생에겐 자체생성 동등문제만
    노출된다(CLAUDE.md 우선순위 #2 법적). D(수시·학종)·E(영재)는 게이팅이 비대상으로 거른다.
    """
    # 도달 관측(PB-04) — 성공/실패 무관하게 '이 핸들러에 요청이 닿았다'를 센다.
    get_l6_mode_reach_counters(request.app).record(_MODE_SUNEUNG)
    return _to_public(select_suneung_items(candidates, persona, min_fit=min_fit, limit=limit))


@router.get(
    "/school-progress",
    response_model=list[PublicProblem],
    summary="학교진도 모드 게이팅",
)
async def gating_school_progress(
    request: Request,
    candidates: SchoolProgressCandidatesDep,
    persona: Annotated[
        Persona, Query(description="노출 대상 페르소나. 학교진도는 A·D 대상")
    ] = Persona.A_일반고고3,
    target_unit_codes: Annotated[
        list[str] | None,
        Query(
            alias="unit_codes",
            description="현재 진도 단원 코드(반복 지정 가능 — `?unit_codes=X&unit_codes=Y`). "
            "주어지면 단원 겹침으로 진도 정합 판정",
        ),
    ] = None,
    target_achievement_codes: Annotated[
        list[str] | None,
        Query(
            alias="achievement_codes",
            description="현재 진도 성취기준 고시코드 반복지정 "
            "— `?achievement_codes=X&achievement_codes=Y`. "
            "단원과 더불어 성취기준 겹침으로 추가 정합(OR·더 세밀하면 우선)",
        ),
    ] = None,
    curriculum_version: Annotated[
        Curriculum | None, Query(description="교육과정 버전 정합 기준(선택)")
    ] = None,
    min_fit: Annotated[
        float, Query(description="persona_fit 임계값(0~1·진도 미지정 시 폴백)")
    ] = 0.5,
    limit: Annotated[int, Query(ge=1, le=200, description="응답 최대 개수")] = 20,
) -> list[PublicProblem]:
    """학교진도 모드 노출 문항을 게이팅해 반환한다(페르소나 A·D 대상).

    후보를 L1에서 읽어(`_fetch_candidates_with_standards` — 후보 + 성취기준 코드 원자 축 조인 주입)
    `select_school_progress_items`에 넘긴다 — 적격 필터(대상 페르소나·저작권 노출 게이트·교육과정
    버전 정합·진도 성취기준/단원 정합) → 우선순위(성취기준 겹침 개수>단원 겹침 개수>난이도) 내림차순
    안정정렬 → limit 적용까지 *전부 L6 게이팅이* 수행한 결과를 그대로 돌려준다.

    `unit_codes`(단원)·`achievement_codes`(성취기준 고시코드)를 반복 지정하면 그 집합과 *하나라도
    겹치는* 문항이 진도 정합으로 통과한다 — 둘은 **OR**로 결합되며(성취기준은 단원보다 세밀한 추가
    신호), 우선순위에서는 성취기준 겹침(×3.0)이 단원 겹침(×2.0)보다 앞선다. 둘 다 미지정이면
    `persona_fit` 폴백으로 판정한다(게이팅 계약). 각 리스트는 `set(...) or None`으로 변환해 넘긴다 —
    빈 리스트(쿼리 미지정)는 None과 같이 폴백/비신호로 취급하기 위함이다. 성취기준 코드는 비영속
    필드라 *문항 태깅·성취기준 코퍼스가 없으면* 빈 리스트로 주입돼 단원 신호로 자연 폴백한다
    (데이터0 안전). `curriculum_version`이 문항과 불일치면 게이팅이 차단한다(예: 2022 진도에 2015
    문항 미혼입). N수(B·C)·영재(E)는 비재학이라 게이팅이 비대상으로 거른다.
    """
    # 빈 리스트(쿼리 미지정·`?unit_codes=` 빈값)는 None과 동일하게 폴백/비신호를 타도록
    # `set(...) or None`으로 정규화한다(빈 set은 falsy → None). 게이팅은 둘 다 None이면 진도 정보
    # 부재로 보고 persona_fit으로 판정한다(school_progress.gating 계약).
    # 도달 관측(PB-04) — 성공/실패 무관하게 '이 핸들러에 요청이 닿았다'를 센다.
    get_l6_mode_reach_counters(request.app).record(_MODE_SCHOOL_PROGRESS)
    unit_code_set = set(target_unit_codes) if target_unit_codes else None
    achievement_code_set = set(target_achievement_codes) if target_achievement_codes else None
    return _to_public(
        select_school_progress_items(
            candidates,
            persona,
            target_unit_codes=unit_code_set,
            target_achievement_codes=achievement_code_set,
            curriculum_version=curriculum_version,
            min_fit=min_fit,
            limit=limit,
        )
    )


@router.get(
    "/thinking",
    response_model=list[PublicProblem],
    summary="사고력 모드 게이팅",
)
async def gating_thinking(
    request: Request,
    candidates: CandidatesDep,
    persona: Annotated[
        Persona, Query(description="노출 대상 페르소나. 사고력 주 대상 D·E(닫힌 집합 게이트 없음)")
    ] = Persona.D_학종고2,
    min_fit: Annotated[float, Query(description="persona_fit 임계값(0~1)")] = 0.5,
    limit: Annotated[int, Query(ge=1, le=200, description="응답 최대 개수")] = 20,
) -> list[PublicProblem]:
    """사고력 모드 노출 문항을 게이팅해 반환한다(Bloom 상위 3단계가 주신호·D·E 주 대상).

    후보를 L1에서 읽어(`_fetch_candidates`) `select_thinking_items`에 넘긴다 — 적격 필터(저작권
    노출 게이트·페르소나 적합도·사고력 주신호) → 우선순위(Bloom 상위 단계>사고력 시그니처 개수>
    케이스/융합/종합 난이도) 내림차순 안정정렬 → limit 적용까지 *전부 L6 게이팅이* 수행한 결과를
    그대로 돌려준다.

    **사고력 주신호는 `bloom_level`**(상위 3단계 ANALYZE/EVALUATE/CREATE) — 사고력 미표지
    (bloom None)·하위 인지 수준(APPLY 이하) 문항은 게이팅이 전부 거른다. **닫힌 페르소나 집합으로
    좁히지 않는다**: 주 대상은 D(학종)·E(영재)이나 A(MVP 고3)도 `persona_fit`이 임계 이상이면
    노출된다(MVP 페르소나 배제 금지·persona_fit 메커니즘만 사용). 평가원/EBS/교과서(본문 미보유)
    출처는 저작권 게이트가 차단하고, 학생에겐 자체생성 동등문제만 노출된다(CLAUDE.md 우선순위 #2).
    """
    # 도달 관측(PB-04) — 성공/실패 무관하게 '이 핸들러에 요청이 닿았다'를 센다.
    get_l6_mode_reach_counters(request.app).record(_MODE_THINKING)
    return _to_public(select_thinking_items(candidates, persona, min_fit=min_fit, limit=limit))


@router.get(
    "/metacognition",
    response_model=list[PublicProblem],
    summary="메타인지 모드 게이팅",
)
async def gating_metacognition(
    request: Request,
    candidates: CandidatesDep,
    persona: Annotated[
        Persona,
        Query(description="노출 대상 페르소나. 메타인지는 전 페르소나 공유 코어(닫힌 집합 없음)"),
    ] = Persona.A_일반고고3,
    min_fit: Annotated[float, Query(description="persona_fit 임계값(0~1)")] = 0.5,
    limit: Annotated[int, Query(ge=1, le=200, description="응답 최대 개수")] = 20,
) -> list[PublicProblem]:
    """메타인지 모드 노출 문항을 게이팅해 반환한다(distractor_map 주신호·전 페르소나 공유 코어).

    후보를 L1에서 읽어(`_fetch_candidates`) `select_metacognition_items`에 넘긴다 — 적격 필터
    (저작권 노출 게이트·페르소나 적합도·메타인지 주신호) → 우선순위(오답→오개념 매핑 개수>진단/
    루브릭 채점>난이도) 내림차순 안정정렬 → limit 적용까지 *전부 L6 게이팅이* 수행한 결과를
    그대로 돌려준다.

    **메타인지 주신호는 `distractor_map`**(오답 선지→오개념 매핑) 존재 — 오답을 오개념으로
    역추적하는 자원이 있거나(주신호) `scoring_type`이 진단/루브릭(보조)인 문항이 적격이며, 둘 다
    없으면 게이팅이 거른다. **닫힌 페르소나 집합으로 좁히지 않는다**: 메타인지는 WhyMath의 공유
    코어(CLAUDE.md §3)라 A(첫 노출 MVP)부터 E까지 `persona_fit`이 임계 이상이면 노출된다.
    평가원/EBS/교과서(본문 미보유) 출처는 저작권 게이트가 차단한다(CLAUDE.md 우선순위 #2).
    """
    # 도달 관측(PB-04) — 성공/실패 무관하게 '이 핸들러에 요청이 닿았다'를 센다.
    get_l6_mode_reach_counters(request.app).record(_MODE_METACOGNITION)
    return _to_public(select_metacognition_items(candidates, persona, min_fit=min_fit, limit=limit))


@router.get(
    "/gifted",
    response_model=list[PublicProblem],
    summary="영재 트랙 게이팅",
)
async def gating_gifted(
    request: Request,
    candidates: CandidatesDep,
    persona: Annotated[
        Persona, Query(description="노출 대상 페르소나. 영재는 E(홈스쿨링 영재) 전용 닫힌 집합")
    ] = Persona.E_홈스쿨링영재,
    min_fit: Annotated[
        float, Query(description="persona_fit 임계값(0~1·영재는 높은 적합 기본 0.7)")
    ] = 0.7,
    min_difficulty: Annotated[
        float, Query(ge=1.0, le=5.0, description="종합 난이도 하한(영재 심화 기본 4.0)")
    ] = 4.0,
    limit: Annotated[int, Query(ge=1, le=200, description="응답 최대 개수")] = 20,
) -> list[PublicProblem]:
    """영재 트랙 노출 문항을 게이팅해 반환한다(심화+창안/융합·페르소나 E 전용).

    후보를 L1에서 읽어(`_fetch_candidates`) `select_gifted_items`에 넘긴다 — 적격 필터(대상
    페르소나 E·저작권 노출 게이트·높은 적합도·심화 하한 AND 창안/융합) → 우선순위(창안 CREATE>
    EVALUATE>단원 융합>융합도>난이도) 내림차순 안정정렬 → limit 적용까지 *전부 L6 게이팅이*
    수행한 결과를 그대로 돌려준다.

    **영재는 페르소나 E(홈스쿨링 영재) 전용 닫힌 집합**(RT가 재수 B·C를 닫은 것과 동형 — 학습
    환경이 본질) — A·B·C·D는 게이팅이 비대상으로 거른다. 적격은 `difficulty_overall`이 심화 하한
    (`min_difficulty`·기본 4.0) 이상 *이고* `bloom_level==CREATE` 또는 `is_cross_unit`인 문항이다.
    영재 콘텐츠(KMO·올림피아드)는 코퍼스 미존재라 데이터가 차오르면 자동 활성한다(데이터0 안전·
    학교진도 성취기준 선례). 평가원/EBS/교과서(본문 미보유) 출처는 저작권 게이트가 차단한다.
    """
    # 도달 관측(PB-04) — 성공/실패 무관하게 '이 핸들러에 요청이 닿았다'를 센다.
    get_l6_mode_reach_counters(request.app).record(_MODE_GIFTED)
    return _to_public(
        select_gifted_items(
            candidates, persona, min_fit=min_fit, min_difficulty=min_difficulty, limit=limit
        )
    )
