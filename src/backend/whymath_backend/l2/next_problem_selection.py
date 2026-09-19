"""기본 CAT 후보 조회·가중 배선 — `api/me.py`에서 **이동**(EOS-19 · 신규 계산 0).

이 모듈의 함수들은 전부 `api/me.py`(L5)에 있던 것을 **바이트 동일 로직으로** 옮긴 것이다.
옮긴 이유는 하나다: `EOS-19`가 추천 선택을 `l2`의 정책 함수
(`l2.recommendation_policy.CatRecommendationPolicy`)로 내리는데, 정책이 이 헬퍼들을 쓰려면
`l2 → api` 역방향 import가 생긴다(CLAUDE.md "L_n은 L_{n+1}을 알지 못한다"). 애초에 후보 조회·
가중은 학습자 모델(L2)의 일이지 HTTP 경계(L5)의 일이 아니었다 — 위치가 늦게 바로잡힌 것이다.

**동작 변경 0**: 함수 본문·상수값·쿼리 모양·정렬 키가 이동 전과 같다. `api/me.py`는 이 모듈에서
같은 이름을 **다시 import해 자기 네임스페이스에 유지**하므로, `whymath_backend.api.me.
candidate_pool_conditions`처럼 기존 경로로 참조하던 소비처(`ops/repeat_recommendation_report.py`·
테스트)는 손댈 필요가 없다.

계층: `l2`. `db.models`·`schema`만 import한다(L3 이상 0건 — import-linter 계약 "EOS Core →
Math Adapter 금지"·"데이터 접근 금지"의 source_modules에 `l2`는 없다).
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.activity import ProblemAttempt
from whymath_backend.db.models.assessment import ConceptMasteryHistory
from whymath_backend.db.models.concept import ProblemConcept
from whymath_backend.db.models.problem import Problem, ProblemRelation
from whymath_backend.l2.ability_estimation import (
    _DIFFICULTY_MIDPOINT,
    difficulty_to_logit,
    resolve_item_difficulty_b,
)
from whymath_backend.l2.irt import IrtItem, ability_standard_error, estimate_ability
from whymath_backend.schema.enums import ASSESSED_ROLES, ReviewStatus
from whymath_backend.schema.problem import METADATA_ONLY_SOURCES

#: 후보 풀 한 행 — `(problem_id, difficulty_overall, irt_difficulty_b)`.
#: `difficulty_overall`이 optional이 아닌 이유는 `load_candidate_rows` docstring 참조.
CandidateRow = tuple[uuid.UUID, float, float | None]

__all__ = [
    "CANDIDATE_POOL_SIZE",
    "CandidateRow",
    "candidate_items",
    "load_candidate_rows",
    "build_candidate_pool_stmt",
    "CANDIDATE_ZERO_ALL_GATED_INELIGIBLE",
    "CANDIDATE_ZERO_NO_POOL",
    "TARGET_SE",
    "WEIGHT_AXIS_SUNEUNG_PRIORITY",
    "WEIGHT_AXIS_WEAK_CONCEPT",
    "AttemptHistoryState",
    "candidate_pool_conditions",
    "candidate_pool_order_by",
    "combine_weights",
    "load_attempt_history_state",
    "load_sibling_ids",
    "load_weak_concept_weights",
    "last_incorrect_problem_id",
    "sibling_weights",
]

# ── 정책 상수 (이동 전 `api/me.py`의 `_CANDIDATE_POOL_SIZE`·`_TARGET_SE` 등과 같은 값) ──
CANDIDATE_POOL_SIZE = 50  # θ 근방 후보 풀 크기(SQL로 거리순 선별 후 파이썬 정보량 비교)
# slice 15: CAT 중단 규칙 목표 표준오차 — 응답한 문항 기준 SE가 이 값 이하로 내려가면
# "충분히 정밀하게 측정됨"으로 보고 적응 검사 중단을 권고(measurement_sufficient=True).
# 0.3은 통상적 CAT 종료 임계(θ ± ~0.6 95% 구간). 추후 모드/설정별 보정은 후속.
TARGET_SE = 0.3
# slice 16/17: 약점 개념 가중 출제 — BKT 개념별 숙달이 낮을수록(약점) 후보 문항 정보량에
# 곱하는 가중치를 키운다. weight = 1 + BOOST·(1 - 최저숙달). BOOST=1.0이면 완전 미숙달(숙달 0)
# 문항은 가중 2배·완전 숙달(1.0)은 1배. 정책 상수(모드별 차등은 후속).
_WEAK_CONCEPT_BOOST = 1.0
# S4-14: 형제 가중 배율 — `_WEAK_CONCEPT_BOOST`와 동일 스케일 정책.
_SIBLING_BOOST = 1.0

# REC-01: 응답 정직 표기 — 이번 요청에 *실제로* 적용된 가중 축 이름.
WEIGHT_AXIS_WEAK_CONCEPT = "weak_concept"
WEIGHT_AXIS_SUNEUNG_PRIORITY = "suneung_priority"

# REC-01: candidate_zero_reason 값 — problem_id가 null일 때만 채워지는 사유 코드.
CANDIDATE_ZERO_NO_POOL = "no_candidate_pool"
CANDIDATE_ZERO_ALL_GATED_INELIGIBLE = "all_candidates_gated_ineligible"


# ── REC-06: 후보 조회의 노출 게이트·정렬을 *한 곳에서만* 정의한다 ──────────────────────────
# 이 두 함수는 서빙 경로(추천 정책)와 반복 추천 리포트(`ops/repeat_recommendation_report.py`)가
# **같이** 쓴다. 리포트가 후보 풀을 자기 방식으로 다시 조립하면 "리포트가 보는 풀"과 "학생이
# 실제로 받는 풀"이 조용히 갈라져, 측정이 서빙을 설명하지 못하게 된다(구축 플레이북 7대 붕괴
# 연쇄 중 "유지보수 지옥 ← truth source가 하나가 아님"의 방어).
def candidate_pool_conditions() -> list[ColumnElement[bool]]:
    """기본 CAT 후보의 노출 게이트 3축(WHERE) — 난이도 라벨 · 저작권 축① · 검수 축②.

    ① 난이도 라벨(`difficulty_overall`) 보유: 응답 `difficulty` 노출과 b 폴백에 필요.
    ② 저작권 노출 게이트(법적·협상 불가): 본문 미보유 출처(평가원/EBS/교과서)는 SQL 레벨 배제.
    ③ 검수 노출 게이트(운영 축 — 축②와 **절대 합치지 않는다**): `approved`만 후보.
    """
    return [
        Problem.difficulty_overall.isnot(None),
        # PB-03 축① — 저작권 노출 게이트(법적, 협상 불가). 수능 분기가 쓰는 것과 동일 상수를
        # 재사용해 판정 기준 이원화를 막는다.
        Problem.source_type.notin_([s.value for s in METADATA_ONLY_SOURCES]),
        # PB-03 축② — 검수 노출 게이트. `corpus_audit_eval` 측정 판정만 review_status에
        # 각인된다(사람 입력 경로 0).
        Problem.review_status == ReviewStatus.approved,
    ]


def candidate_pool_order_by(theta: float) -> tuple[ColumnElement[Any], ...]:
    """후보 정렬 키 — ① |b−θ| 오름차순 ② `problem_id`(2차 키·동률 구간 동결).

    ①은 기존 그대로다(보정 b `irt_difficulty_b` 우선·없으면 전문가 난이도→logit 폴백을
    COALESCE로 표현). **②가 REC-06 acceptance③의 신규분**이다: ①만 있으면 |b−θ|가 같은 동률
    구간의 행 순서가 **PG 임의**라 같은 DB 상태에서도 후보 풀 구성과 `select_weighted_item`의
    인덱스가 흔들릴 수 있었다 — 결정론이 선택기에만 있고 그 앞 단계(후보 조회)에는 없던 상태다.

    **무작위화가 아니다.** 2차 키는 동률 구간을 `problem_id` 오름차순으로 *고정*할 뿐이라,
    ①로 순서가 이미 확정되는 비동률 구간은 전혀 건드리지 않는다.
    """
    return (
        func.abs(
            func.coalesce(
                Problem.irt_difficulty_b,
                Problem.difficulty_overall - _DIFFICULTY_MIDPOINT,
            )
            - theta
        ),
        # `.asc()`는 방향을 코드에 명시하는 동시에 mypy --strict 정합을 만든다
        # (`InstrumentedAttribute`는 `ColumnElement`로 좁혀지지 않는다).
        Problem.problem_id.asc(),
    )


def _weak_concept_weights(
    candidate_problem_ids: list[uuid.UUID],
    problem_concepts: dict[uuid.UUID, set[uuid.UUID]],
    mastery: dict[uuid.UUID, float],
) -> list[float]:
    """후보 문항별 약점 가중치 — 문항의 평가 개념 중 *최저 숙달*로 weakness 산출(BKT+IRT 융합).

    각 후보의 평가 개념(`problem_concepts[pid]`) 중 숙달 기록(`mastery`)이 있는 것의 최저 숙달을
    취해 `weight = 1 + _WEAK_CONCEPT_BOOST·(1 - 최저숙달)`. 약할수록 가중↑. 개념 매핑이 없거나
    숙달 기록이 없으면 *중립*(1.0 — 정보 없는 개념을 벌하거나 우대하지 않음). 순수·결정론.
    """
    weights = []
    for pid in candidate_problem_ids:
        relevant = [mastery[c] for c in problem_concepts.get(pid, set()) if c in mastery]
        if relevant:
            weights.append(1.0 + _WEAK_CONCEPT_BOOST * (1.0 - min(relevant)))
        else:
            weights.append(1.0)
    return weights


async def load_weak_concept_weights(
    session: AsyncSession,
    user_id: uuid.UUID,
    candidate_ids: list[uuid.UUID],
) -> list[float]:
    """슬라이스 17 약점 가중 *조회 배선* — 숙달 스냅샷·개념 매핑 2쿼리 후 가중치 산출.

    기본 CAT과 수능 모드(mode=suneung) *양 분기*가 같은 약점 가중을 공유한다. 조회 2회:
      ① 개념별 BKT 숙달 스냅샷(개념당 최신 — DISTINCT ON), ② 후보 문항의 평가 개념 매핑
      (`ASSESSED_ROLES`만). 순수 산출은 `_weak_concept_weights`에 위임한다.
    """
    mastery_stmt = (
        select(ConceptMasteryHistory.concept_id, ConceptMasteryHistory.mastery)
        .where(ConceptMasteryHistory.user_id == user_id)
        .distinct(ConceptMasteryHistory.concept_id)
        .order_by(
            ConceptMasteryHistory.concept_id,
            ConceptMasteryHistory.measured_at.desc(),
        )
    )
    mastery = {
        cid: float(m) for cid, m in (await session.execute(mastery_stmt)).all() if m is not None
    }
    pc_stmt = select(ProblemConcept.problem_id, ProblemConcept.concept_id).where(
        ProblemConcept.problem_id.in_(candidate_ids),
        ProblemConcept.role.in_(ASSESSED_ROLES),
    )
    problem_concepts: dict[uuid.UUID, set[uuid.UUID]] = {}
    for pid, cid in (await session.execute(pc_stmt)).all():
        problem_concepts.setdefault(pid, set()).add(cid)
    return _weak_concept_weights(candidate_ids, problem_concepts, mastery)


async def last_incorrect_problem_id(session: AsyncSession, user_id: uuid.UUID) -> uuid.UUID | None:
    """직전 오답 문항 id — `created_at` 최신순 1건.

    `get_my_ability_history`(§6.1)와 동형으로 서버 default 컬럼 `created_at`을 쓴다(`started_at`은
    nullable·미보장이라 정렬 축 부적합).
    """
    stmt = (
        select(ProblemAttempt.problem_id)
        .where(
            ProblemAttempt.user_id == user_id,
            ProblemAttempt.is_correct.is_(False),
            ProblemAttempt.problem_id.isnot(None),
        )
        .order_by(ProblemAttempt.created_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def load_sibling_ids(session: AsyncSession, problem_id: uuid.UUID) -> set[uuid.UUID]:
    """`problem_relation` 양방향(parent/related) 조회 — 변형·유사는 시맨틱상 *대칭 소비*라
    방향 무관하게 상대편 id를 "형제"로 모은다(자기 자신은 스키마가 이미 금지하나 방어적 제외).
    """
    stmt = select(ProblemRelation.parent_problem_id, ProblemRelation.related_problem_id).where(
        or_(
            ProblemRelation.parent_problem_id == problem_id,
            ProblemRelation.related_problem_id == problem_id,
        )
    )
    siblings: set[uuid.UUID] = set()
    for parent_id, related_id in (await session.execute(stmt)).all():
        other = related_id if parent_id == problem_id else parent_id
        if other != problem_id:
            siblings.add(other)
    return siblings


def sibling_weights(candidate_ids: list[uuid.UUID], sibling_ids: set[uuid.UUID]) -> list[float]:
    """형제 후보 가중 — `_weak_concept_weights`와 동형(형제 1+BOOST배·비형제 중립 1.0)."""
    return [1.0 + _SIBLING_BOOST if pid in sibling_ids else 1.0 for pid in candidate_ids]


def combine_weights(*weight_lists: list[float] | None) -> list[float] | None:
    """여러 가중 축을 원소별 곱으로 결합 — None(미적용) 축은 건너뛴다.

    전부 None이면 None(가중 미적용 = 균등). 길이는 모두 후보 수와 같아야 한다(strict zip).
    """
    present = [w for w in weight_lists if w is not None]
    if not present:
        return None
    combined = list(present[0])
    for other in present[1:]:
        combined = [a * b for a, b in zip(combined, other, strict=True)]
    return combined


@dataclass(slots=True, frozen=True)
class AttemptHistoryState:
    """채점 이력 기반 CAT 상태 — 추천 정책·ASM-03 평가 캡처 좌석이 *공유*하는 단일
    진실 원천(single source of truth).

    `attempted_ids`는 추천 후보 필터에만 쓰이는 부가 필드다 — 평가 캡처 좌석
    (`POST /assessments/capture`)은 `theta`·`standard_error`·`measurement_sufficient`만
    소비한다.
    """

    attempted_ids: set[uuid.UUID]
    theta: float
    standard_error: float | None
    measurement_sufficient: bool


async def load_attempt_history_state(
    session: AsyncSession, user_id: uuid.UUID
) -> AttemptHistoryState:
    """채점 이력 조회 → θ 추정 → SE·`measurement_sufficient`(CAT 중단 규칙, slice 15).

    추천 경로(slice 12~17)의 기존 인라인 로직을 *동작 무변경*으로 추출한 것 — 새 계산
    0(같은 쿼리·같은 순서·같은 공식). ASM-03(`POST /assessments/capture`)이 "measurement_
    sufficient 경계"를 추천과 *같은 지점*에서 판정하기 위해 별도 함수로 뽑았다
    (진실 원천이 둘로 갈라지면 유지보수 지옥 — CLAUDE.md 구축 플레이북 7대 붕괴 연쇄 방어).

    **θ는 여기서 산출한다** — `LearnerState.general_ability`(`ability_snapshot` 테이블의 최신
    스냅샷)와 **다른 추정기**다. 정책이 `learner_state`를 입력으로 받게 된 뒤에도 이 함수를
    계속 쓰는 이유는 회귀 0이다: 두 값은 같은 학생에 대해 서로 다른 수를 내므로, 출제 θ를
    스냅샷으로 갈아끼우면 *추천 문항 자체가 바뀐다*(EOS-19 acceptance ④ 위반). 스냅샷 θ로의
    통합은 두 추정기의 동치성을 먼저 실측해야 하는 별건이다.
    """
    attempt_stmt = (
        select(
            ProblemAttempt.problem_id,
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
    attempt_rows = (await session.execute(attempt_stmt)).all()
    responses: list[tuple[IrtItem, bool]] = []
    for _pid, is_correct, difficulty, irt_b in attempt_rows:
        b = resolve_item_difficulty_b(irt_b, difficulty)
        if b is not None:
            responses.append((IrtItem(difficulty=b), bool(is_correct)))
    theta = estimate_ability(responses)
    attempted_ids = {pid for pid, _ic, _d, _b in attempt_rows}
    # slice 15: 응답한 문항(administered) 기준 측정 정밀도 — CAT 중단 규칙 신호.
    administered_items = [item for item, _ in responses]
    se = ability_standard_error(theta, administered_items)
    standard_error = None if math.isinf(se) else se
    measurement_sufficient = standard_error is not None and standard_error <= TARGET_SE
    return AttemptHistoryState(
        attempted_ids=attempted_ids,
        theta=theta,
        standard_error=standard_error,
        measurement_sufficient=measurement_sufficient,
    )


def build_candidate_pool_stmt(
    theta: float,
    *,
    attempted_ids: set[uuid.UUID],
    excluded_ids: set[uuid.UUID],
) -> Select[tuple[uuid.UUID, float | None, float | None]]:
    """기본 CAT 후보 풀 SELECT — 노출 게이트 + 미응답 + 형제 배제 + θ 근방 정렬·limit.

    이동 전 핸들러가 인라인으로 조립하던 것과 **같은 문장**이다(WHERE 순서·정렬 키·limit 동일).
    """
    stmt = select(Problem.problem_id, Problem.difficulty_overall, Problem.irt_difficulty_b).where(
        *candidate_pool_conditions()
    )
    if attempted_ids:
        stmt = stmt.where(Problem.problem_id.notin_(attempted_ids))
    if excluded_ids:
        stmt = stmt.where(Problem.problem_id.notin_(excluded_ids))
    return stmt.order_by(*candidate_pool_order_by(theta)).limit(CANDIDATE_POOL_SIZE)


async def load_candidate_rows(
    session: AsyncSession,
    theta: float,
    *,
    attempted_ids: set[uuid.UUID],
    excluded_ids: set[uuid.UUID],
) -> list[CandidateRow]:
    """후보 풀 조회 → `(problem_id, difficulty_overall, irt_difficulty_b)` 목록.

    `difficulty_overall`을 **비-optional**로 좁히는 근거는 `candidate_pool_conditions()`의
    `difficulty_overall IS NOT NULL`이다(같은 문장 안의 WHERE라 우회 경로가 없다). 값이 그래도
    None이면 `float(None)`이 그 자리에서 터진다 — 이동 전 코드와 같은 동작이며, 조용히 0으로
    접거나 후보에서 빼서 풀 크기를 바꾸지 않는다(침묵 실패 금지).
    """
    stmt = build_candidate_pool_stmt(theta, attempted_ids=attempted_ids, excluded_ids=excluded_ids)
    return [
        (pid, float(difficulty), irt_b)
        for pid, difficulty, irt_b in (await session.execute(stmt)).all()
    ]


def candidate_items(candidate_rows: list[CandidateRow]) -> list[IrtItem]:
    """후보 행 → IRT 문항(보정 b 우선·없으면 휴리스틱 폴백) — 행과 1:1·순서 보존."""
    return [
        IrtItem(difficulty=irt_b if irt_b is not None else difficulty_to_logit(d))
        for _pid, d, irt_b in candidate_rows
    ]
