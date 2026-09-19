"""수능 모드 추천 정책 — L6 게이팅 × L2 CAT의 **합성 지점** (EOS-19).

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
구현하므로 핸들러가 보는 모양은 같다. 알고리즘은 이동 전 핸들러의 수능 분기와 동일하다
(회귀 0 — 후보 SQL·게이팅·가중 결합 순서·선택기 호출이 모두 그대로다).
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

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
from whymath_backend.l2.recommendation_contract import LearningContext, action_for
from whymath_backend.l2.recommendation_evidence import POLICY_VERSION_SUNEUNG
from whymath_backend.l2.recommendation_policy import (
    DEFAULT_GRAPH_BUDGET,
    ConceptGraphBudget,
    NextProblemOutcome,
    PolicyTelemetry,
    resolve_target_concept,
)
from whymath_backend.l2.recommendation_reason import collect_recommendation_reason
from whymath_backend.l6.suneung import (
    SUNEUNG_DEFAULT_MIN_FIT,
    SUNEUNG_EXAM_TYPES,
    is_suneung_eligible,
    recommend_suneung_index,
    suneung_item_weight,
)
from whymath_backend.schema.enums import Persona
from whymath_backend.schema.problem import METADATA_ONLY_SOURCES

__all__ = ["SuneungRecommendationPolicy"]


class SuneungRecommendationPolicy:
    """수능 적응 추천 정책 — θ·SE는 기본 CAT과 공통, *후보 조회·선택만* 분기한다.

    SQL 사전필터는 **축소 전용**(저작권 사전배제·수능 신호·미응답·θ 근방 50개)이고, 최종 적격
    판정은 `recommend_suneung_index` 내부의 `is_suneung_eligible`(L6 진실 게이트)이 재수행한다 —
    사전필터가 느슨해도 부적격이 새지 않는다. 이 이중 구조는 이동 전과 같다.
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

        band_calibrated = False if learning_context.purpose == "learning" else None

        # 게이팅에 source_type·persona_fit·signature_patterns 등 전 필드가 필요해 ORM 전체 행.
        stmt = select(Problem).where(
            Problem.difficulty_overall.isnot(None),
            Problem.source_type.notin_([s.value for s in METADATA_ONLY_SOURCES]),
            or_(
                Problem.exam_type.in_([e.value for e in SUNEUNG_EXAM_TYPES]),
                func.cardinality(Problem.signature_patterns) > 0,
                Problem.persona_fit[persona.value].as_float() >= SUNEUNG_DEFAULT_MIN_FIT,
            ),
        )
        if attempt_state.attempted_ids:
            stmt = stmt.where(Problem.problem_id.notin_(attempt_state.attempted_ids))
        if self._sibling_filter == "exclude" and sibling_ids:
            stmt = stmt.where(Problem.problem_id.notin_(sibling_ids))
        stmt = stmt.order_by(*candidate_pool_order_by(theta)).limit(CANDIDATE_POOL_SIZE)
        candidates = [row.to_schema() for row in (await session.execute(stmt)).scalars().all()]
        candidate_pool_size = len(candidates)

        # 약점 가중은 기본 CAT과 *같은 헬퍼*를 공유 — extra_weights로 곱 결합.
        extra_weights: list[float] | None = None
        if learning_context.prioritize_weak_concepts and candidates:
            extra_weights = await load_weak_concept_weights(
                session, user_id, [p.problem_id for p in candidates]
            )
        weight_axes_applied = [WEIGHT_AXIS_SUNEUNG_PRIORITY]
        if learning_context.prioritize_weak_concepts:
            weight_axes_applied.append(WEIGHT_AXIS_WEAK_CONCEPT)
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
                **common,
            )

        picked = candidates[chosen_index]
        # REC-11: candidates[] 관측 — recommend_suneung_index 내부 공식(적격 게이트 × 정보량 ×
        # 수능우선순위×약점가중)을 재계산해 미러한다(이미 정해진 chosen_index를 그대로 쓰므로
        # 결정에는 영향 없음·관측 재계산일 뿐). 그 함수의 알고리즘이 바뀌면 이 미러도 함께
        # 갱신해야 한다 — 단일 진실 원천은 여전히 recommend_suneung_index.
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
        reason = await collect_recommendation_reason(
            session, learner_id=user_id, problem_id=picked.problem_id
        )
        target = await resolve_target_concept(
            session, reason=reason, learner_state=learner_state, budget=self._graph_budget
        )
        return NextProblemOutcome(
            problem_id=picked.problem_id,
            reason=reason,
            action=action_for(reason.type),
            target_concept=target,
            # SQL이 difficulty_overall NOT NULL을 보장하나, 스키마 타입(Optional) 정합 방어.
            difficulty=(
                None if picked.difficulty_overall is None else float(picked.difficulty_overall)
            ),
            candidate_zero_reason=None,
            candidate_scores=scores,
            **common,
        )
