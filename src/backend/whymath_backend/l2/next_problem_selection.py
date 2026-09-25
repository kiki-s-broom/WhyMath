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

**예외 — EOS-124 신규분**: 파일 끝의 정렬 선택 조회 2종(`load_direct_successors`·
`load_target_candidate_rows`)은 이동분이 아니라 **새로 만든 것**이다. 정책이 다른 개념(막힌
선수·다음 개념)을 가리켰을 때만 돌고, 위 이동분의 쿼리 모양·순서는 건드리지 않는다.

계층: `l2`. `db.models`·`schema`만 import한다(L3 이상 0건 — import-linter 계약 "EOS Core →
Math Adapter 금지"·"데이터 접근 금지"의 source_modules에 `l2`는 없다).
"""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.activity import ProblemAttempt
from whymath_backend.db.models.assessment import ConceptMasteryHistory
from whymath_backend.db.models.concept import Concept, ConceptEdge, ProblemConcept
from whymath_backend.db.models.problem import Problem, ProblemRelation
from whymath_backend.l2.ability_estimation import (
    _DIFFICULTY_MIDPOINT,
    difficulty_to_logit,
    resolve_item_difficulty_b,
)
from whymath_backend.l2.irt import IrtItem, ability_standard_error, estimate_ability
from whymath_backend.schema.enums import ASSESSED_ROLES, ConceptRole, EdgeType, ReviewStatus
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
    "MAX_ADMINISTERED_ITEMS",
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
    "SuccessorRow",
    "TargetCandidateRow",
    "build_direct_successors_stmt",
    "build_target_candidate_stmt",
    "load_direct_successors",
    "load_target_candidate_rows",
]

_logger = logging.getLogger("whymath.l2.next_problem_selection")

# ── 정책 상수 (이동 전 `api/me.py`의 `_CANDIDATE_POOL_SIZE`·`_TARGET_SE` 등과 같은 값) ──
CANDIDATE_POOL_SIZE = 50  # θ 근방 후보 풀 크기(SQL로 거리순 선별 후 파이썬 정보량 비교)
# slice 15: CAT 중단 규칙 목표 표준오차 — 응답한 문항 기준 SE가 이 값 이하로 내려가면
# "충분히 정밀하게 측정됨"으로 보고 적응 검사 중단을 권고(measurement_sufficient=True).
# 0.3은 통상적 CAT 종료 임계(θ ± ~0.6 95% 구간). 추후 모드/설정별 보정은 후속.
TARGET_SE = 0.3
# EOS-126: CAT **2차 중단 규칙** — 출제 문항 수 상한. `TARGET_SE`(정밀도 축)에 닿지 못해도
# 이 수만큼 채점되면 진단을 *확정 가능*으로 본다(`AttemptHistoryState.diagnosis_confirmable`).
#
# **왜 필요한가 — 실측**: 이 경로의 θ 추정은 모든 응답을 Rasch(a=1.0)로 다룬다
# (`load_attempt_history_state`가 `IrtItem(difficulty=b)`만 만들고 변별도를 넘기지 않는다).
# a=1.0이면 문항 하나가 주는 최대 정보량이 a²·0.25 = 0.25이고, SE ≤ 0.3은 총정보량
# I ≥ 1/0.3² = 11.11을 요구한다 → **최소 45문항**(11.11/0.25 = 44.4). 이 45는 튜닝 여지가
# 아니라 *모든 문항의 난이도가 학생 능력과 완전히 일치(P=0.5)할 때의 이론적 하한*이다.
# 실측이 그 하한을 확인했다: 난이도 1.0~5.0 균등 코퍼스에서 `select_next_item`으로 이상적
# 적응 출제를 돌리면 46문항(SE 0.2973), EOS-22 판정 프로브(정답률 2/3 고정)는 67문항이었다
# (`docs/reviews/eos_phase2_gate2_judgment_2026-09-19.md` §2-1). 즉 **완벽한 적응 알고리즘도
# a=1.0인 한 45문항을 깰 수 없다** — 실학생이 한 자리에서 완주할 수 없는 길이다.
#
# **왜 20인가**: 같은 실측 곡선에서 20문항 SE≈0.45·25문항 0.41·30문항 0.37이다. 어디서 끊어도
# 0.3에는 못 닿으므로 이 상한의 근거는 정밀도가 아니라 *학생이 한 자리에서 감당하는 분량*이고,
# 고정 길이 적응 진단의 통상 범위(20~30문항) 하단을 택했다.
#
# **임계를 낮추는 것이 아니다**(EOS-126 acceptance ③의 금지선): `TARGET_SE`는 0.3 그대로이고
# `measurement_sufficient`의 의미도 "SE ≤ 0.3"에서 바뀌지 않는다. 이 상한은 *정밀도 달성*을
# 참칭하지 않고 **별도의 중단 사유**를 하나 더 둘 뿐이다 — 상한으로 끝난 진단은 응답·적재 양쪽에
# `measurement_sufficient=False`와 달성 SE를 그대로 달고 나간다(침묵 실패 금지).
#
# **근본 원인은 따로 있다**: 수렴 속도 자체를 올리려면 문항 변별도 a를 실측·소비해야 하는데,
# `Problem.irt_a` 컬럼은 존재하지만 **쓰기 경로가 저장소 어디에도 없고**(항상 NULL) 보정기
# `l2/item_calibration.py`는 `fit_jmle`(1PL·a 고정)로 b만 적합한다. a=1.5면 하한이 20문항,
# a=2.0이면 12문항으로 내려간다. 그 2PL 보정은 문항당 응답 축적이 선행돼야 하므로 별건이다
# = `EOS-129`.
MAX_ADMINISTERED_ITEMS = 20
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
    #: EOS-126: SE 산출에 실제로 들어간 채점 응답 수(= 난이도 b가 해소된 응답).
    #: `attempted_ids`와 다르다 — 난이도 라벨도 보정 b도 없는 문항은 θ·SE에 기여하지 못하므로
    #: 여기서도 세지 않는다(상한과 SE가 *같은 문항 집합*을 가리키게 한다).
    administered_count: int

    @property
    def item_cap_reached(self) -> bool:
        """EOS-126 2차 중단 규칙 — 채점된 출제 문항이 상한에 닿았는가(정밀도와 무관)."""
        return self.administered_count >= MAX_ADMINISTERED_ITEMS

    @property
    def diagnosis_confirmable(self) -> bool:
        """진단을 확정(capture)해도 되는가 — 중단 규칙 **둘 중 하나**라도 발화하면 참.

        `measurement_sufficient`(정밀도 축)와 **별개 개념**이다. 정밀도를 달성해서 참인지
        상한에 닿아서 참인지는 이 값으로 구분되지 않으므로, 소비처는 두 원천을 각각 읽어
        정직하게 표기한다(`api/me.py`의 capture `reason`).
        """
        return self.measurement_sufficient or self.item_cap_reached


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
        administered_count=len(administered_items),
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


# ── EOS-124: 정책 의도에 맞춘 **정렬 선택**의 조회 2종 ─────────────────────────────────────
# 기본 CAT의 1차 선택(위 후보 풀 + 정보량 최대)은 그대로 두고, 정책이 *다른 개념*(막힌 선수·다음
# 개념)을 가리켰을 때만 이 두 조회가 추가로 돈다. 1차 선택의 쿼리 모양·순서는 바뀌지 않는다.

#: 목표 개념 후보 한 행 — `CandidateRow` + **그 행을 목표에 묶은 개념**(PRIMARY 매핑).
#: 개념 열이 필요한 이유: 여러 목표 개념의 후보를 한 번에 읽고 우선순위 순으로 나눠 고르기 때문이다.
TargetCandidateRow = tuple[uuid.UUID, float, float | None, uuid.UUID]


@dataclass(frozen=True, slots=True)
class SuccessorRow:
    """직접 후행 개념 1건 — `concept_edge`(from==앵커·PREREQUISITE)의 `to` 쪽.

    `concept_code`는 학습자 상태의 숙달 키(개념코드)와 맞추려고 함께 읽는다(`concept` 내부
    조인이라 NOT NULL 컬럼 값이 항상 있다). 숙달 키에 없으면 호출부는 **미측정**으로 다룬다.
    """

    concept_id: uuid.UUID
    concept_code: str


def build_direct_successors_stmt(
    concept_id: uuid.UUID, *, limit: int
) -> Select[tuple[uuid.UUID, str]]:
    """앵커의 **직접** 후행(1-hop) SELECT — `from_concept_id == 앵커`인 PREREQUISITE 엣지의 `to`.

    `fetch_prerequisites`(to==C → from)와 방향만 반대다. 재귀하지 않는 이유: "다음 개념"은 앵커를
    선수로 삼는 바로 다음 개념이지 그 다음의 다음이 아니다(전진은 한 칸이다). `limit`은 호출부가
    `limit+1`을 넘겨 **초과를 탐지**하는 데 쓴다(침묵 절단 금지 — `load_direct_successors` 참조).
    """
    return (
        select(ConceptEdge.to_concept_id, Concept.code)
        .join(Concept, Concept.concept_id == ConceptEdge.to_concept_id)
        .where(
            ConceptEdge.from_concept_id == concept_id,
            ConceptEdge.edge_type == EdgeType.PREREQUISITE.value,
        )
        .order_by(ConceptEdge.to_concept_id)
        .limit(limit)
    )


async def load_direct_successors(
    session: AsyncSession, concept_id: uuid.UUID, *, max_nodes: int
) -> list[SuccessorRow]:
    """앵커의 직접 후행 개념들 — hub 개념의 fan-out은 `max_nodes`로 자르고 **로그를 남긴다**.

    `max_nodes`는 정책의 그래프 예산(`ConceptGraphBudget.max_nodes`, 천장 20)을 그대로 받는다.
    한 행 더 읽어(`max_nodes+1`) 초과 여부를 판정하므로, 잘렸다는 사실이 조용히 사라지지 않는다.
    같은 후행이 엣지 중복으로 두 번 나오면 한 번만 센다(visited — DAG diamond와 같은 규율).
    """
    rows = (
        await session.execute(build_direct_successors_stmt(concept_id, limit=max_nodes + 1))
    ).all()
    seen: set[uuid.UUID] = set()
    result: list[SuccessorRow] = []
    for to_id, code in rows:
        if to_id == concept_id or to_id in seen:
            continue
        seen.add(to_id)
        result.append(SuccessorRow(concept_id=to_id, concept_code=code))
    if len(result) > max_nodes:
        _logger.warning(
            "후행 개념 노드 예산 초과 — 앵커 %s의 후행 %d개 이상 중 %d개만 유지",
            concept_id,
            len(result),
            max_nodes,
        )
        result = result[:max_nodes]
    return result


def build_target_candidate_stmt(
    theta: float,
    *,
    concept_ids: list[uuid.UUID],
    attempted_ids: set[uuid.UUID],
    excluded_ids: set[uuid.UUID],
) -> Select[Any]:
    """목표 개념(들)의 후보 SELECT — **기본 후보 풀과 같은 게이트·같은 정렬**, 개념별 상한만 다르다.

    같은 것: 노출 게이트 3축(`candidate_pool_conditions`)·미응답·형제 배제·θ 근방 정렬
    (`candidate_pool_order_by`). 1차 선택과 게이트가 갈라지면 정렬 선택이 *1차 선택이 막는 문항*
    (저작권·미검수)을 꺼내 올 수 있다 — 그래서 같은 함수를 재사용한다(REC-06 단일 정의 원칙).

    다른 것 둘:
      ① 대표 개념(`PRIMARY`) 매핑이 목표 개념인 문항만. TESTED 폴백을 쓰지 않는 이유 — 이
         문항이 "그 개념의 문항"이라고 설명에 적으려면 그 개념이 문항의 *주된* 개념이어야 한다.
         PRIMARY=X·TESTED=P인 문항을 P의 연습으로 부르면 설명이 콘텐츠와 다시 어긋난다.
      ② 상한이 **개념마다** `CANDIDATE_POOL_SIZE`다(윈도 함수). 전체에 한 번 limit을 걸면 θ에
         가까운 개념이 풀을 다 채워 우선순위가 높은 개념(가장 약한 선수)의 문항이 잘려 나간다.
    """
    distance = candidate_pool_order_by(theta)
    rank = (
        func.row_number()
        .over(partition_by=ProblemConcept.concept_id, order_by=list(distance))
        .label("rank")
    )
    inner = (
        select(
            Problem.problem_id,
            Problem.difficulty_overall,
            Problem.irt_difficulty_b,
            ProblemConcept.concept_id,
            rank,
        )
        .join(ProblemConcept, ProblemConcept.problem_id == Problem.problem_id)
        .where(
            *candidate_pool_conditions(),
            ProblemConcept.role == ConceptRole.PRIMARY,
            ProblemConcept.concept_id.in_(concept_ids),
        )
    )
    if attempted_ids:
        inner = inner.where(Problem.problem_id.notin_(attempted_ids))
    if excluded_ids:
        inner = inner.where(Problem.problem_id.notin_(excluded_ids))
    ranked = inner.subquery("target_candidates")
    return (
        select(
            ranked.c.problem_id,
            ranked.c.difficulty_overall,
            ranked.c.irt_difficulty_b,
            ranked.c.concept_id,
        )
        .where(ranked.c.rank <= CANDIDATE_POOL_SIZE)
        .order_by(ranked.c.concept_id, ranked.c.rank)
    )


async def load_target_candidate_rows(
    session: AsyncSession,
    theta: float,
    *,
    concept_ids: list[uuid.UUID],
    attempted_ids: set[uuid.UUID],
    excluded_ids: set[uuid.UUID],
) -> list[TargetCandidateRow]:
    """목표 개념 후보 조회 → `(problem_id, difficulty_overall, irt_difficulty_b, concept_id)`.

    목표가 비면 조회하지 않는다(0건). `difficulty_overall`의 비-optional 근거는
    `load_candidate_rows`와 같다(같은 게이트 함수가 `IS NOT NULL`을 건다).
    """
    if not concept_ids:
        return []
    stmt = build_target_candidate_stmt(
        theta,
        concept_ids=concept_ids,
        attempted_ids=attempted_ids,
        excluded_ids=excluded_ids,
    )
    return [
        (pid, float(difficulty), irt_b, cid)
        for pid, difficulty, irt_b, cid in (await session.execute(stmt)).all()
    ]
