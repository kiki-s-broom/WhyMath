"""수능 모드 추천 정책 — L6 게이팅 × L2 CAT의 **합성 지점** (EOS-19 · EOS-25).

왜 `l2`도 `l6`도 아닌 여기인가(위치 선택의 근거를 코드에 남긴다):

- `l2`에 둘 수 없다 — 이 정책은 `is_suneung_eligible`·`suneung_item_weight`·
  `recommend_suneung_index`(전부 `l6.suneung`)를 부른다. `l2 → l6`은 역방향 의존이고
  CLAUDE.md의 "L_n은 L_{n+1}을 알지 못한다"가 금지한다.
- `l6`에 둘 수 없다 — 이 정책은 후보를 **DB에서** 조회한다. import-linter 계약
  "데이터 접근 금지"가 `whymath_backend.l6`의 sqlalchemy·`whymath_backend.db` import를
  baseline 0으로 동결하고 있다(유예 없음).

두 계층을 합법적으로 합성할 수 있는 자리는 상위 합성 지점뿐이고, 이 저장소에서 그것은
API 패키지의 `_` 접두 모듈이다(`api/_l6_mode_reach_state.py`·`api/_concept_orchestration.py`
선례). 라우터가 아니라 **정책 구현체**이므로 핸들러와 같은 파일에 두지 않는다 — 핸들러는
정책을 고르기만 하고 선택 로직을 갖지 않는다는 것이 `EOS-19` acceptance ③이다.

기본 CAT 정책(`l2.recommendation_policy.CatRecommendationPolicy`)과 **같은 Protocol**을
구현하므로 핸들러가 보는 모양은 같다.

────────────────────────────────────────────────────────────────────────────
EOS-25 — 설명(정책 축)과 콘텐츠(선택 축)를 수능 모드에서도 맞춘다 (`suneung_v2`)
────────────────────────────────────────────────────────────────────────────
EOS-124가 기본 CAT에서 고친 결함이 이 정책에 그대로 남아 있었다(2026-09-28 재현 · main
`78a8edff`). 문항을 수능 CAT으로 고른 *뒤* 그 문항 개념의 숙달 구간으로 행위를 붙이고, 목표
개념은 따로 계산했다. 그래서 세 형태가 나갔다 — (가) 숙달 0.98 개념 문항에 `advance_next`·target=
그 개념(R3 위반) (나) 선수 숙달 1.0인데 `practice_prerequisite`·target=그 선수(R2 위반) (다) 선수가
미측정이면 target=문항 개념(R3 위반). 산출이 `intent_resolution=None`이라 정렬 검증도 면제됐다.

판정(`docs/reviews/eos25_suneung_policy_alignment_judgment_2026-09-28.md`):

  - **의도는 기본 CAT과 같은 함수로 세운다**(`resolve_policy_intent`). 숙달 구간 규칙은 학습자
    상태의 규칙이지 출제 모드의 규칙이 아니다. 모드별 사본을 두면 한쪽만 고쳤을 때 두 모드가 같은
    학생에게 다른 진단을 낸다.
  - **재선택은 수능 모드 안에서만 한다.** 목표 개념 후보는 1차 선택과 같은 사전필터
    (`suneung_pool_conditions`)로 읽고, 같은 진실 게이트·같은 수능 가중·같은 선택기
    (`recommend_suneung_index`)로 고른다. 기본 CAT의 `load_target_candidate_rows`는 수능 게이트를
    모르므로 빌려 쓰지 않는다 — 빌려 쓰면 재선택이 1차 선택이 막는 문항을 꺼내 온다.
  - 목표 개념에 수능 적격 문항이 없으면 **모드를 벗어나지 않는다.** 1차 선택 문항을 내보내고 행위를
    정직 강등한다(`target_unavailable`). 하위 학년 선수는 수능 적격 문항이 드물어 이 강등이 기본
    CAT보다 잦을 것이다. 그것은 결함이 아니라 콘텐츠 공백 신호이고, 응답·처치 기록의
    `intent_resolution`으로 센다.

1차 선택은 **바뀌지 않는다** — 후보 SQL·게이팅·가중 결합 순서·선택기 호출이 EOS-19 이동 전과 같고,
그래서 관계 행위가 아닌 구간(연습·진단·미매핑)에서는 같은 입력에서 같은 문항이 나온다. 달라지는
것은 관계 행위 구간의 후보 집합 하나뿐이다. 선택 규칙이 바뀌었으므로 소급 평가가 두 규칙의 로그를
섞지 않게 `policy_version`을 `suneung_v2`로 올렸다(REC-11 규약).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from whymath_backend.db.models.concept import ProblemConcept
from whymath_backend.db.models.problem import Problem
from whymath_backend.l2.ability_estimation import resolve_item_difficulty_b
from whymath_backend.l2.irt import IrtItem, item_information, learning_band_weight
from whymath_backend.l2.learner_state import LearnerState
from whymath_backend.l2.next_problem_selection import (
    CANDIDATE_POOL_SIZE,
    CANDIDATE_ZERO_ALL_GATED_INELIGIBLE,
    CANDIDATE_ZERO_NO_POOL,
    WEIGHT_AXIS_SUNEUNG_PRIORITY,
    WEIGHT_AXIS_WEAK_CONCEPT,
    candidate_pool_order_by,
    combine_weights,
    last_incorrect_problem_id,
    load_attempt_history_state,
    load_sibling_ids,
    load_weak_concept_weights,
    sibling_weights,
)
from whymath_backend.l2.recommendation_contract import (
    LearningContext,
    action_for,
    demote_to_current_concept,
)
from whymath_backend.l2.recommendation_evidence import POLICY_VERSION_SUNEUNG
from whymath_backend.l2.recommendation_policy import (
    DEFAULT_GRAPH_BUDGET,
    ConceptGraphBudget,
    IntentResolution,
    NextProblemOutcome,
    PolicyTelemetry,
    resolve_policy_intent,
)
from whymath_backend.l2.recommendation_reason import collect_recommendation_reason
from whymath_backend.l6.suneung import (
    SUNEUNG_DEFAULT_MIN_FIT,
    SUNEUNG_EXAM_TYPES,
    is_suneung_eligible,
    recommend_suneung_index,
    suneung_item_weight,
)
from whymath_backend.schema.enums import ConceptRole, Persona
from whymath_backend.schema.problem import METADATA_ONLY_SOURCES
from whymath_backend.schema.problem import Problem as SchemaProblem

__all__ = [
    "SuneungRecommendationPolicy",
    "build_suneung_target_candidate_stmt",
    "load_suneung_target_candidates",
    "suneung_pool_conditions",
]

#: 수능 목표 개념 후보 한 행 — (문항, **그 행을 목표에 묶은 개념**(PRIMARY 매핑)).
SuneungTargetCandidate = tuple[SchemaProblem, uuid.UUID]


def suneung_pool_conditions(persona: Persona) -> list[ColumnElement[bool]]:
    """수능 후보 SQL 사전필터(WHERE) — 1차 선택과 정렬 재선택이 **같은 정의**를 쓴다.

    **축소 전용**이다: 난이도 라벨 보유 · 저작권 사전배제 · 수능 신호(기출 유형 · 시그니처 패턴 ·
    페르소나 적합도) 중 하나. 최종 적격 판정은 `recommend_suneung_index` 안의 `is_suneung_eligible`
    (L6 진실 게이트 — 페르소나·저작권·검수·수능 신호)이 다시 한다. 그래서 사전필터가 느슨해도
    부적격이 새지 않는다.

    한 함수로 둔 이유(EOS-25 · REC-06 단일 정의 원칙): 두 조회가 조건을 따로 들고 있으면 한쪽만
    고쳐지는 날 재선택이 1차 선택이 막는 문항을 꺼내 온다. 조건 순서는 EOS-19 이동 전 인라인
    문장과 같다(1차 선택 SQL 불변).
    """
    return [
        Problem.difficulty_overall.isnot(None),
        Problem.source_type.notin_([s.value for s in METADATA_ONLY_SOURCES]),
        or_(
            Problem.exam_type.in_([e.value for e in SUNEUNG_EXAM_TYPES]),
            func.cardinality(Problem.signature_patterns) > 0,
            Problem.persona_fit[persona.value].as_float() >= SUNEUNG_DEFAULT_MIN_FIT,
        ),
    ]


def build_suneung_target_candidate_stmt(
    theta: float,
    *,
    persona: Persona,
    concept_ids: list[uuid.UUID],
    attempted_ids: set[uuid.UUID],
    excluded_ids: set[uuid.UUID],
) -> Select[Any]:
    """목표 개념(들)의 **수능** 후보 SELECT — 1차 선택과 같은 사전필터·정렬, 개념별 상한만 다르다.

    같은 것: 수능 사전필터(`suneung_pool_conditions`)·미응답·형제 배제·θ 근방 정렬
    (`candidate_pool_order_by`). 게이팅에 전 필드가 필요하므로 1차 선택처럼 ORM 행 전체를 읽는다.

    다른 것 둘(기본 CAT의 `build_target_candidate_stmt`와 같은 이유):
      ① 대표 개념(`PRIMARY`) 매핑이 목표 개념인 문항만. 수능 문항은 여러 개념을 엮는 경우가 많다 —
         TESTED로만 걸린 개념의 "연습"이라고 부르면 설명이 콘텐츠와 다시 어긋난다.
      ② 상한이 **개념마다** `CANDIDATE_POOL_SIZE`다(윈도 함수). 전체에 한 번 걸면 θ에 가까운 개념이
         풀을 다 채워 우선순위가 높은 개념(가장 약한 선수)의 문항이 잘려 나간다.
    """
    distance = candidate_pool_order_by(theta)
    rank = (
        func.row_number()
        .over(partition_by=ProblemConcept.concept_id, order_by=list(distance))
        .label("rank")
    )
    inner = (
        select(Problem, ProblemConcept.concept_id.label("target_concept_id"), rank)
        .join(ProblemConcept, ProblemConcept.problem_id == Problem.problem_id)
        .where(
            *suneung_pool_conditions(persona),
            ProblemConcept.role == ConceptRole.PRIMARY,
            ProblemConcept.concept_id.in_(concept_ids),
        )
    )
    if attempted_ids:
        inner = inner.where(Problem.problem_id.notin_(attempted_ids))
    if excluded_ids:
        inner = inner.where(Problem.problem_id.notin_(excluded_ids))
    ranked = inner.subquery("suneung_target_candidates")
    problem = aliased(Problem, ranked)
    return (
        select(problem, ranked.c.target_concept_id)
        .where(ranked.c.rank <= CANDIDATE_POOL_SIZE)
        .order_by(ranked.c.target_concept_id, ranked.c.rank)
    )


async def load_suneung_target_candidates(
    session: AsyncSession,
    theta: float,
    *,
    persona: Persona,
    concept_ids: list[uuid.UUID],
    attempted_ids: set[uuid.UUID],
    excluded_ids: set[uuid.UUID],
) -> list[SuneungTargetCandidate]:
    """목표 개념 수능 후보 조회 → `(schema Problem, 목표 개념 id)` 목록. 목표가 비면 조회 0건."""
    if not concept_ids:
        return []
    stmt = build_suneung_target_candidate_stmt(
        theta,
        persona=persona,
        concept_ids=concept_ids,
        attempted_ids=attempted_ids,
        excluded_ids=excluded_ids,
    )
    return [
        (row.to_schema(), concept_id) for row, concept_id in (await session.execute(stmt)).all()
    ]


def _suneung_candidate_scores(
    theta: float,
    candidates: list[SchemaProblem],
    persona: Persona,
    extra_weights: list[float] | None,
) -> list[tuple[uuid.UUID, float]]:
    """REC-11 후보 점수 — `recommend_suneung_index` 내부 공식의 **관측 재계산**(미러).

    적격 게이트 × 정보량 × 수능 우선순위 × 추가 가중. 이미 정해진 선택을 그대로 쓰므로 결정에는
    영향이 없다. 그 함수의 알고리즘이 바뀌면 이 미러도 함께 갱신해야 한다 — 단일 진실 원천은
    여전히 `recommend_suneung_index`다. 1차 선택과 재선택이 같은 미러를 쓰도록 함수로 뺐다.
    """
    scores: list[tuple[uuid.UUID, float]] = []
    for i, p in enumerate(candidates):
        if not is_suneung_eligible(p, persona):
            continue
        b = resolve_item_difficulty_b(p.irt_difficulty_b, p.difficulty_overall)
        if b is None:
            continue
        extra = extra_weights[i] if extra_weights is not None else 1.0
        scores.append(
            (
                p.problem_id,
                item_information(theta, IrtItem(difficulty=b)) * suneung_item_weight(p) * extra,
            )
        )
    return scores


@dataclass(frozen=True, slots=True)
class _SuneungDelivery:
    """실제로 학생에게 나갈 수능 문항 1건 — 문항·**대표 개념**·그 선택의 후보 점수."""

    problem: SchemaProblem
    concept_id: uuid.UUID | None
    scores: list[tuple[uuid.UUID, float]]

    @property
    def difficulty(self) -> float | None:
        # SQL이 difficulty_overall NOT NULL을 보장하나, 스키마 타입(Optional) 정합 방어.
        value = self.problem.difficulty_overall
        return None if value is None else float(value)


class SuneungRecommendationPolicy:
    """수능 적응 추천 정책 — θ·SE는 기본 CAT과 공통, *후보 조회·선택만* 분기한다.

    SQL 사전필터는 **축소 전용**(저작권 사전배제·수능 신호·미응답·θ 근방 50개)이고, 최종 적격
    판정은 `recommend_suneung_index` 내부의 `is_suneung_eligible`(L6 진실 게이트)이 재수행한다 —
    사전필터가 느슨해도 부적격이 새지 않는다. 이 이중 구조는 정렬 재선택(EOS-25)에도 그대로 걸린다.
    """

    policy_version = POLICY_VERSION_SUNEUNG

    def __init__(
        self,
        session: AsyncSession,
        *,
        persona: Persona,
        sibling_filter: str | None = None,
        graph_budget: ConceptGraphBudget = DEFAULT_GRAPH_BUDGET,
    ) -> None:
        self._session = session
        self._persona = persona
        self._sibling_filter = sibling_filter
        self._graph_budget = graph_budget

    async def __call__(
        self, learner_state: LearnerState, learning_context: LearningContext
    ) -> NextProblemOutcome:
        """추천 1건 — 1차 선택 → 앵커 근거 → 정책 의도 → (필요하면) 수능 정렬 재선택 → 산출."""
        session = self._session
        user_id = uuid.UUID(learner_state.student_id)
        persona = self._persona

        attempt_state = await load_attempt_history_state(session, user_id)
        theta = attempt_state.theta

        sibling_ids: set[uuid.UUID] = set()
        if self._sibling_filter is not None:
            last_wrong = await last_incorrect_problem_id(session, user_id)
            if last_wrong is not None:
                sibling_ids = await load_sibling_ids(session, last_wrong)
        excluded_ids = sibling_ids if self._sibling_filter == "exclude" else set()

        band_calibrated = False if learning_context.purpose == "learning" else None

        # 게이팅에 source_type·persona_fit·signature_patterns 등 전 필드가 필요해 ORM 전체 행.
        stmt = select(Problem).where(*suneung_pool_conditions(persona))
        if attempt_state.attempted_ids:
            stmt = stmt.where(Problem.problem_id.notin_(attempt_state.attempted_ids))
        if excluded_ids:
            stmt = stmt.where(Problem.problem_id.notin_(excluded_ids))
        stmt = stmt.order_by(*candidate_pool_order_by(theta)).limit(CANDIDATE_POOL_SIZE)
        candidates = [row.to_schema() for row in (await session.execute(stmt)).scalars().all()]
        candidate_pool_size = len(candidates)

        extra_weights, weak_signal = await self._combine_axes(
            user_id=user_id,
            learning_context=learning_context,
            candidates=candidates,
            theta=theta,
            sibling_ids=sibling_ids,
        )
        weight_axes_applied = [WEIGHT_AXIS_SUNEUNG_PRIORITY]
        if learning_context.prioritize_weak_concepts:
            weight_axes_applied.append(WEIGHT_AXIS_WEAK_CONCEPT)

        chosen_index = recommend_suneung_index(
            theta, candidates, persona, extra_weights=extra_weights
        )
        common: PolicyTelemetry = {
            "theta": theta,
            "standard_error": attempt_state.standard_error,
            "measurement_sufficient": attempt_state.measurement_sufficient,
            "weight_axes_applied": weight_axes_applied,
            # 전환 전 핸들러의 `applied_weights=extra_weights is not None`과 **같은 식**이다.
            "applied_weights": extra_weights is not None,
            "candidate_pool_size": candidate_pool_size,
            "weak_concept_signal_count": weak_signal,
            "band_calibrated": band_calibrated,
            "policy_version": self.policy_version,
        }
        if chosen_index is None:
            # 후보 풀 자체가 0건인지, 풀은 있었으나 L6 게이팅이 전부 배제했는지 구분.
            no_candidate = await collect_recommendation_reason(
                session, learner_id=user_id, problem_id=None
            )
            return NextProblemOutcome(
                problem_id=None,
                reason=no_candidate,
                action=action_for(no_candidate.type),
                target_concept=None,
                candidate_zero_reason=(
                    CANDIDATE_ZERO_NO_POOL
                    if not candidates
                    else CANDIDATE_ZERO_ALL_GATED_INELIGIBLE
                ),
                intent_resolution=IntentResolution.NO_CANDIDATE,
                **common,
            )

        picked = candidates[chosen_index]
        # ── EOS-25: 1차 선택 → 앵커 → 정책 의도 → (필요하면) 수능 정렬 재선택 ─────────────────
        # 1차 선택은 위 그대로다. 그 문항의 대표 개념이 *앵커*가 되고, 앵커의 숙달 구간 규칙(§8)이
        # 관계 행위(선수 복귀·전진)를 가리키면 목표 개념의 **수능 적격** 문항으로 다시 고른다. 못
        # 고르면 1차 문항을 그대로 내보내되 설명을 정직하게 내린다 — 어느 쪽이든 설명(action·
        # target)은 전달된 문항의 개념을 가리킨다
        # (`NextProblemOutcome._aligned_when_declared`가 강제).
        anchor_reason = await collect_recommendation_reason(
            session, learner_id=user_id, problem_id=picked.problem_id
        )
        intent = await resolve_policy_intent(
            session,
            anchor_reason=anchor_reason,
            learner_state=learner_state,
            learner_id=user_id,
            budget=self._graph_budget,
        )
        delivery = _SuneungDelivery(
            problem=picked,
            concept_id=anchor_reason.concept_id,
            # REC-11: candidates[] 관측 — recommend_suneung_index 내부 공식의 미러(결정 영향 0).
            scores=_suneung_candidate_scores(theta, candidates, persona, extra_weights),
        )
        reason, resolution = intent.reason, intent.resolution
        if intent.reselect_groups:
            aligned = await self._select_aligned(
                intent.reselect_groups,
                user_id=user_id,
                learning_context=learning_context,
                theta=theta,
                attempted_ids=attempt_state.attempted_ids,
                excluded_ids=excluded_ids,
                sibling_ids=sibling_ids,
            )
            if aligned is None:
                reason = demote_to_current_concept(intent.reason)
                resolution = IntentResolution.TARGET_UNAVAILABLE
            else:
                delivery = aligned
        return NextProblemOutcome(
            problem_id=delivery.problem.problem_id,
            reason=reason,
            action=action_for(reason.type),
            target_concept=delivery.concept_id,
            delivered_concept=delivery.concept_id,
            intent_resolution=resolution,
            difficulty=delivery.difficulty,
            candidate_zero_reason=None,
            candidate_scores=delivery.scores,
            **common,
        )

    async def _select_aligned(
        self,
        groups: tuple[tuple[uuid.UUID, ...], ...],
        *,
        user_id: uuid.UUID,
        learning_context: LearningContext,
        theta: float,
        attempted_ids: set[uuid.UUID],
        excluded_ids: set[uuid.UUID],
        sibling_ids: set[uuid.UUID],
    ) -> _SuneungDelivery | None:
        """수능 정렬 재선택 — 목표 개념 묶음을 우선순위 순으로 보며 **처음 고를 수 있는 묶음**에서
        고른다.


        선택 연산은 1차 선택과 같다: 같은 사전필터로 읽은 후보에(`load_suneung_target_candidates`)
        같은 가중 축(`_combine_axes` — 약점·밴드·형제)을 곱하고 같은 선택기
        (`recommend_suneung_index`
        — L6 진실 게이트 × 정보량 × 수능 우선순위)로 고른다. 달라지는 것은 **후보 집합** 하나뿐이다.

        묶음에 행은 있는데 진실 게이트가 전부 막으면(`recommend_suneung_index`가 None) 그 묶음을
        건너뛴다 — 사전필터를 통과했다고 적격인 것이 아니다(검수·페르소나는 게이트만 본다).
        조회는 1건이다: 모든 목표 개념의 후보를 한 번에 읽고(개념별 상한) 파이썬에서 묶음별로
        나눈다.
        """
        persona = self._persona
        rows = await load_suneung_target_candidates(
            self._session,
            theta,
            persona=persona,
            concept_ids=[concept for group in groups for concept in group],
            attempted_ids=attempted_ids,
            excluded_ids=excluded_ids,
        )
        for group in groups:
            members = set(group)
            picked: list[SchemaProblem] = []
            concept_of: dict[uuid.UUID, uuid.UUID] = {}
            for problem, concept in rows:
                # 한 문항이 같은 묶음의 두 개념에 PRIMARY로 걸려 두 번 나오면 한 번만 센다.
                if concept not in members or problem.problem_id in concept_of:
                    continue
                picked.append(problem)
                concept_of[problem.problem_id] = concept
            if not picked:
                continue
            weights, _weak_signal = await self._combine_axes(
                user_id=user_id,
                learning_context=learning_context,
                candidates=picked,
                theta=theta,
                sibling_ids=sibling_ids,
            )
            index = recommend_suneung_index(theta, picked, persona, extra_weights=weights)
            if index is None:
                continue
            chosen = picked[index]
            return _SuneungDelivery(
                problem=chosen,
                concept_id=concept_of[chosen.problem_id],
                scores=_suneung_candidate_scores(theta, picked, persona, weights),
            )
        return None

    async def _combine_axes(
        self,
        *,
        user_id: uuid.UUID,
        learning_context: LearningContext,
        candidates: list[SchemaProblem],
        theta: float,
        sibling_ids: set[uuid.UUID],
    ) -> tuple[list[float] | None, int]:
        """추가 가중 축 3종(약점·학습 밴드·형제)을 **이동 전과 같은 순서로** 곱 결합한다.

        반환 = (결합 가중 · 약점 신호 수). 약점 신호 수는 **약점 가중만** 센다 — 밴드·형제를 곱하기
        전의 값이다(이동 전 핸들러와 같은 식. 기본 CAT은 결합 뒤 전체를 센다 — 두 정책의 기존 관측
        정의가 달랐고, 이 태스크는 그것을 바꾸지 않는다).

        수능 우선순위 가중은 여기서 곱하지 않는다 — `recommend_suneung_index`가 게이트와 함께
        곱한다.
        순서가 계약인 이유는 기본 CAT `_combine_axes`와 같다: 부동소수 곱의 마지막 비트가 동률
        후보의 argmax를 뒤집으면 추천이 바뀐다.
        """
        extra_weights: list[float] | None = None
        # 약점 가중은 기본 CAT과 *같은 헬퍼*를 공유 — extra_weights로 곱 결합.
        if learning_context.prioritize_weak_concepts and candidates:
            extra_weights = await load_weak_concept_weights(
                self._session, user_id, [p.problem_id for p in candidates]
            )
        weak_signal = sum(1 for w in extra_weights if w != 1.0) if extra_weights is not None else 0
        # REC-04: 밴드 가중은 같은 곱 결합 축에 얹는다(새 선택기 0). b 미보유 후보는 어차피
        # recommend_suneung_index 내부에서 배제되므로 중립 1.0.
        if learning_context.purpose == "learning" and candidates:
            band_weights = [
                (
                    learning_band_weight(theta, IrtItem(difficulty=b))
                    if (b := resolve_item_difficulty_b(p.irt_difficulty_b, p.difficulty_overall))
                    is not None
                    else 1.0
                )
                for p in candidates
            ]
            extra_weights = (
                band_weights
                if extra_weights is None
                else [w * b for w, b in zip(extra_weights, band_weights, strict=True)]
            )
        if self._sibling_filter == "include" and sibling_ids and candidates:
            extra_weights = combine_weights(
                extra_weights, sibling_weights([p.problem_id for p in candidates], sibling_ids)
            )
        return extra_weights, weak_signal
