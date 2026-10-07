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
구현하므로 핸들러가 보는 모양은 같다. 알고리즘은 이동 전 핸들러의 수능 분기와 동일하다
(회귀 0 — 후보 SQL·게이팅·가중 결합 순서·선택기 호출이 모두 그대로다).

────────────────────────────────────────────────────────────────────────────
EOS-25 — 설명은 전달 문항에 맞추고, 콘텐츠 재선택은 보류한다
────────────────────────────────────────────────────────────────────────────
EOS-124가 기본 CAT에서 고친 결함이 이 정책에도 있었다(2026-09-28 재현 · main `78a8edff`). 문항을
수능 CAT으로 고른 *뒤* 그 문항 개념의 숙달 구간으로 행위를 붙이고 목표 개념은 따로 계산해서, 세
형태가 나갔다 — (가) 숙달 0.98 개념 문항에 `advance_next`·target=그 개념(정렬 R3 위반) (나) 선수
숙달
1.0인데 `practice_prerequisite`·target=그 선수(R2 위반) (다) 선수가 미측정이면 target=문항 개념(R3
위반). 산출이 `intent_resolution=None`이라 생성 시점 정렬 검증도 면제됐다.

판정(`docs/reviews/eos25_suneung_policy_alignment_judgment_2026-09-28.md`):

  - **진단은 하나다.** 의도는 기본 CAT과 같은 함수(`resolve_policy_intent`)로 세우고, 산출은 정렬을
    선언해 생성 시점 검증(`NextProblemOutcome._aligned_when_declared`)을 받는다.
  - **처방은 모드가 정한다 — 수능 모드는 콘텐츠를 다른 개념으로 옮기지 않는다.** 의도가 목표 개념의
    문항으로 다시 고르라고 해도(`reselect_groups`) 1차 선택 문항을 그대로 내보내고, 설명을 앵커 개념
    연습으로 정직하게 내린다(`IntentResolution.MODE_WITHHELD`). 지금 재선택을 켜지 않는 이유는
    둘이다(독립 비판 F1·F2 — 코드로 확인). ① 수능 게이트가 학년·출제범위를 보지 않는다 —
    persona_fit이
    난이도 구간만의 함수라 난이도 라벨이 있는 문항은 전부 페르소나 A에게 0.70 이상, 곧 수능
    적격이다.
    "수능 모드 안에서 다시 고른다"가 성립하지 않는다(`EOS-31`). ② 구간 규칙의 입력(BKT)에 신뢰
    하한이
    없다 — 숙달 0.55에서 오답 1개면 0.219(선수 복귀), 정답 1개면 0.862(전진)다. 응답 하나로 콘텐츠를
    옮기게 된다(`EOS-33`). 재선택의 재판정은 `EOS-35`가 소유한다.

그래서 EOS-25는 **선택을 바꾸지 않았다** — 같은 입력에서 같은 문항이 나갔고 `policy_version`도
그대로였다 (REC-11: 후보 생성·선택 규칙의 식별자). 바뀐 것은 설명(reason·action·target)과, 그
설명이 전달 문항으로 어떻게 해소됐는지를 말하는 `intent_resolution`이다.

────────────────────────────────────────────────────────────────────────────
EOS-31 — 수능 게이트가 출제 범위를 본다 (`suneung_v1` → `suneung_v2`)
────────────────────────────────────────────────────────────────────────────
위 ①(게이트가 학년·범위를 보지 않는다)을 닫았다. 이번에는 **선택이 바뀐다** — 후보 집합이 다르므로
`policy_version`을 `suneung_v2`로 올렸다. 출제 범위(목표 학년도 수능의 성취기준 접두어 집합)는 L6
`scope.py` 하나가 정본이고, 게이트 ②-c(파이썬)와 이 모듈의 SQL 사전필터(`suneung_scope_clause`)가
같은 접두어 상수를 읽는다. 사전필터가 범위를 모르면 후보 풀 `LIMIT`가 θ 근방 순으로 자르는 사이
범위 밖 문항이 풀을 채우고 게이트가 그것들을 전부 탈락시켜, 범위 안 문항이 있는데도 후보가
사라진다. EOS-25가 보류한 재선택(`mode_withheld`)의 재판정은 `EOS-35`가 소유한다 — 이 변경은 그
전제 ①이 바뀐 사실을 만들 뿐 재선택을 켜지 않는다(숙달 구간 입력의 신뢰 하한 `EOS-33`이 별건으로
남아 있다).

────────────────────────────────────────────────────────────────────────────
EOS-147 — 전부 정답 이력의 표적 θ를 추정 θ에서 분리한다 (`suneung_v2` → `suneung_v3`)
────────────────────────────────────────────────────────────────────────────
전부 정답 이력에서 후보를 고르는 표적 θ가 추정 θ(4.0 클램프)가 아니라 `ability_for_selection`의
표적이라 그 이력의 **선택이 바뀐다** — 그래서 `policy_version`을 `suneung_v3`로 올렸다(REC-11: 후보
생성·선택 규칙의 식별자). `suneung_v2`는 EOS-31의 출제 범위 규칙이 먼저 썼으므로 두 변경이 한
번호를 쓰지 않는다. 그 외 이력의 선택은 `suneung_v2`와 같다.

EOS-39 — 코치 도움 완료를 선택 θ의 입력에서 실패 1건으로 접는다 (`suneung_v3` → `suneung_v4`)
────────────────────────────────────────────────────────────────────────────
기본 CAT과 같은 `AttemptHistoryState.selection_theta`를 쓰므로 수능 모드도 같은 규칙을 받는다.
도움 완료(`used_hint=True`)가 있는 이력에서 후보 선택이 바뀌므로 `suneung_v4`로 올렸다.
접힌 문항 수·미상 수(`selection_help_count`·`selection_hint_unknown_count`)는 이 정책의
산출에도 같은 이름으로 실린다 — 처치 기록이 두 정책을 같은 키로 읽는다.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ColumnElement, and_, exists, func, literal, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.api.gating import _fetch_achievement_codes as fetch_achievement_codes
from whymath_backend.db.models.atom_node import AtomNode
from whymath_backend.db.models.concept import Concept, ProblemConcept
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
    SUNEUNG_SCOPE,
    is_suneung_eligible,
    recommend_suneung_index,
    suneung_item_weight,
)
from whymath_backend.schema.enums import Persona
from whymath_backend.schema.problem import METADATA_ONLY_SOURCES

__all__ = ["SuneungRecommendationPolicy", "suneung_scope_clause"]


def suneung_scope_clause() -> ColumnElement[bool]:
    """수능 출제 범위 SQL 절 — 게이트 ②-c(`l6.suneung.scope.suneung_scope_verdict`)의 SQL 사본.

    **같은 정의를 쓴다**(EOS-31 ④): 교육과정 개정이 목표 학년도의 것이고, 문항이 잇는 원자 개념의
    `atom_node.standard_codes` 중 `SUNEUNG_SCOPE.code_startswith_patterns()`로 시작하는 코드가
    **하나라도** 있다. 접두어 상수는 L6 모듈 하나이고 이 함수는 그것을 읽기만 한다 — 한쪽만 고치면
    사전필터가 막은 문항을 게이트가 통과시키거나 그 반대가 되므로 같은 입력 전수에서 두 판정이
    일치하는지를 실 PG 통합 테스트가 본다(`test_eos31_suneung_scope_integration.py`). 성취기준
    코드를 모르는 문항 (`UNKNOWN`)은 이 절에서도 빠진다(조인 행이 없으므로).

    `unnest`는 문항→개념→원자 조인에 이어 LATERAL로 펼친다 — 후보 풀 `LIMIT`가 θ 근방 순으로
    자르기 전에 범위 밖 문항이 풀을 채워 게이트가 전부 탈락시키는 일(후보 소멸)을 막는다.
    """
    codes = func.unnest(AtomNode.standard_codes).table_valued("scope_code").render_derived()
    codes_lateral = codes.lateral("scope_codes")
    code_column = codes_lateral.c.scope_code
    return and_(
        Problem.curriculum_version == SUNEUNG_SCOPE.curriculum.value,
        exists(
            select(literal(1))
            .select_from(ProblemConcept)
            .join(Concept, ProblemConcept.concept_id == Concept.concept_id)
            .join(AtomNode, AtomNode.code == Concept.code)
            .join(codes_lateral, true())
            .where(
                ProblemConcept.problem_id == Problem.problem_id,
                or_(
                    *(
                        code_column.startswith(pattern, autoescape=True)
                        for pattern in SUNEUNG_SCOPE.code_startswith_patterns()
                    )
                ),
            )
            .correlate(Problem)
        ),
    )


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
        # EOS-147 — 이 함수의 `theta`는 후보 선택에 쓰는 θ(`selection_theta`)다. 전부 정답 이력의
        # 추정 θ는 MLE가 없는 상한 클램프(4.0)라 표적으로 쓰지 않는다. 기본 CAT 정책과 같은 상태
        # 객체·같은 정의다(모드마다 표적 θ의 정의를 갈라 두지 않는다). 응답·SE에는 추정 θ가 나간다.
        theta = attempt_state.selection_theta

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
            # EOS-31 — 출제 범위는 신호(OR)가 아니라 선결 조건(AND)이다. 게이트 ②-c와 같은 정의.
            suneung_scope_clause(),
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
        # EOS-31 — 게이트 ②-c가 보는 성취기준 코드(비영속 필드)를 L5가 주입한다. 주입이 빠지면
        # 모든 후보가 `UNKNOWN`으로 거절돼 후보가 소멸한다(fail-closed) — "없음"이 "적격"으로
        # 새지 않는다.
        codes_by_problem = await fetch_achievement_codes(
            session, [p.problem_id for p in candidates]
        )
        for candidate in candidates:
            if candidate.problem_id in codes_by_problem:
                candidate.achievement_standard_codes = sorted(
                    codes_by_problem[candidate.problem_id]
                )

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
            "theta": attempt_state.theta,
            "selection_theta": theta,
            "theta_boundary": attempt_state.theta_boundary,
            "selection_help_count": attempt_state.selection_help_count,
            "selection_hint_unknown_count": attempt_state.selection_hint_unknown_count,
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
        # ── EOS-25: 설명은 전달 문항에 맞추고, 콘텐츠 재선택은 보류한다 ──────────────────
        # 1차 선택 문항의 대표 개념이 *앵커*다. 의도는 기본 CAT과 같은 함수로 세운다(진단은 모드와
        # 무관하게 하나다). 의도가 목표 개념의 문항으로 다시 고르라고 해도(`reselect_groups`) 수능
        # 모드는 고르지 않는다 — 1차 문항을 그대로 내보내고 설명을 앵커 개념 연습으로 정직하게
        # 내린다. 재선택하지 않는 이유는 모듈 docstring "EOS-25" 절.
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
        reason, resolution = intent.reason, intent.resolution
        if intent.reselect_groups:
            reason = demote_to_current_concept(intent.reason)
            resolution = IntentResolution.MODE_WITHHELD
        return NextProblemOutcome(
            problem_id=picked.problem_id,
            reason=reason,
            action=action_for(reason.type),
            # 설명이 가리키는 개념 = 전달 문항의 대표 개념(정렬 계약 R2 — 생성 시점에 검증된다).
            target_concept=anchor_reason.concept_id,
            delivered_concept=anchor_reason.concept_id,
            intent_resolution=resolution,
            # SQL이 difficulty_overall NOT NULL을 보장하나, 스키마 타입(Optional) 정합 방어.
            difficulty=(
                None if picked.difficulty_overall is None else float(picked.difficulty_overall)
            ),
            candidate_zero_reason=None,
            candidate_scores=scores,
            **common,
        )
