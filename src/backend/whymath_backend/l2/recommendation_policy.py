"""추천 정책 — `recommend(learner_state, learning_context)`의 **첫 구현체** (EOS-19 · EOS-124).

`EOS-14`가 계약(`l2.recommendation_contract`)을 세우고 닫았고, 그 시점 `RecommendationPolicy`·
`LearningContext`·`Recommendation` 세 타입은 **소비처 0건**이었다. 이 모듈이 그 셋의 첫
소비처다 — 핸들러(`api/me.py`)에 흩어져 있던 선택 로직이 여기로 내려오고, 핸들러는 결과를
HTTP 응답으로 **옮기기만** 한다.

────────────────────────────────────────────────────────────────────────────
계약이 지키는 것 — "내부는 교체되고 시그니처는 남는다"
────────────────────────────────────────────────────────────────────────────
`__call__(learner_state, learning_context)`가 받는 것은 **학습자 상태**와 **요청 상황** 둘뿐이다.
v1 내부는 계획서 §8의 if/else 규칙(숙달 밴드 → 행위)과 기존 IRT 후보 선택이지만, 그것을
BKT→DKT로 갈거나 bandit·LLM 제안을 얹어도 이 시그니처는 바뀌지 않는다. 교체 가능성을 주석이
아니라 **타입**(Protocol)으로 표현한다는 것이 이 말의 실제 내용이다.

`learner_state`를 `object`가 아니라 구체 타입(`LearnerState`)으로 좁히는 것은 구현체의 몫이다
(계약 쪽은 순환 import를 피하려 `object`로 열어 뒀다 — 계약 docstring 참조).

────────────────────────────────────────────────────────────────────────────
EOS-124 — 설명(정책 축)과 콘텐츠(선택 축)를 **한 자리에서** 맞춘다 (`cat_v2`)
────────────────────────────────────────────────────────────────────────────
EOS-19 시점의 v1은 문항을 IRT로 고른 *뒤* 그 문항의 개념 숙달로 행위(action)를 붙였다. 두 축이
서로를 보지 않아 두 방향으로 어긋났다(2026-09-19 페르소나 실측 · main `433ec9ea`):
(가) 숙달 0.98 개념의 문항에 `advance_next` — 전진을 선언하면서 전진하지 않는다.
(나) 선수 숙달 1.0인데 원래 개념 문항에 `practice_prerequisite` — 설명이 낡았다.

**정본 판정**(acceptance ③ — 세 안 중 무엇도 단독으로 채택하지 않았다):
  - *의도*의 정본은 **정책 축**이다 — 숙달 구간 규칙(계획서 §8 · `select_reason_type`)이 무엇을
    하라는지 정한다. 선택 축에 맞춰 행위를 사후 계산하면(안 2) 정책 의도가 사후 합리화된다.
  - *콘텐츠*의 정본은 **선택 축**이다 — 1차 선택(θ·가중·밴드 무변경)이 앵커 개념을 정하고,
    관계 행위(선수 복귀·전진)는 그 앵커에서 그래프로 목표 개념을 찾아 **그 개념의 문항으로
    다시 고른다**(안 1). 단, 목표에 문항이 없을 때 후보 0을 만들지 않는다 — 안 1의 약점.
  - 둘이 맞춰질 수 없으면 **정직 강등**한다(안 3): 1차 선택 문항을 내보내고 행위를 그 콘텐츠에
    맞게 "현재 개념 연습"으로 내린다. none/diagnose가 아니라 practice_current인 이유는 문항이
    실제로 나가고 그 개념이 측정돼 있기 때문이다(없는 부재·없는 미측정을 말하지 않는다).
  - 어느 경로든 **구조 계약**이 산출 생성 시점에 강제된다(`check_intent_alignment` —
    `NextProblemOutcome._aligned_when_declared`): target = 전달 문항의 개념, 관계 행위면
    근거 개념 ≠ 목표. 해소 결과는 `IntentResolution`으로 응답·처치 기록 양쪽에 남는다.

그래서 v1의 아래 제약("추천 결과를 바꾸지 않는다")은 **EOS-19 전환에 한정된 것**이고, EOS-124는
선수·전진 구간에서 선택을 *의도적으로* 바꾼다. 바뀐 알고리즘은 `policy_version=cat_v2`로 구분돼
소급 평가가 두 규칙을 섞지 않는다. θ·난이도 밴드·가중 축은 여전히 그대로다(재선택도 같은
게이트·같은 가중·같은 선택기를 쓴다 — 달라지는 것은 후보 집합뿐이다).

────────────────────────────────────────────────────────────────────────────
**추천 결과를 바꾸지 않는다** (EOS-19 acceptance ④ — 그 전환의 가장 중요한 제약)
────────────────────────────────────────────────────────────────────────────
이 전환은 *배치*를 바꾸는 것이지 *알고리즘*을 바꾸는 것이 아니다. 후보 조회 SQL·가중 축의 곱
결합 순서·`select_weighted_item` 호출은 이동 전 핸들러와 같고(`l2.next_problem_selection`으로
바이트 동일 이동), 그래서 같은 입력에서 같은 문항이 나온다.

특히 **θ를 `learner_state.general_ability`로 갈아끼우지 않는다**. 그 필드는 `ability_snapshot`
테이블의 최신 스냅샷이고 출제에 쓰는 θ는 채점 이력에서 매 호출 재추정한 값이라, 같은 학생에
대해 서로 다른 수다. 계약이 `learner_state`를 받는다는 이유로 그것을 출제 θ로 쓰면 추천 문항이
바뀐다 — 계약 전환이 추천을 바꿨다는 뜻이고, 그러면 "전환이 안전했다"를 증명할 방법이 없다.
두 추정기의 통합은 동치성 실측이 선행돼야 하는 별건이다(미이행 · `l2.next_problem_selection.
load_attempt_history_state` docstring).

그러면 `learner_state`는 **어디에 쓰이는가**(장식이 아니라는 증거 — "작동한 비율" 원칙):
`learner_state.mastery`(개념코드 → BKT 숙달)가 **정책 의도 판정**(`resolve_policy_intent`)의
그래프 쪽 입력이다 — 선수가 아직 약한가, 후행이 막혔는가, 다음 개념이 이미 숙달인가를 여기서
읽는다(숙달 재조회 0건). `learner_state`가 비면(콜드스타트) 목표가 서지 않아 정직 강등되고,
그 사실은 `intent_resolution=unsupported`로 관측된다.

**EOS-24 — `learner_state.learning_state`(학습 상태 머신 국면)가 두 번째 입력이다.** 상태 머신이
오개념 교정(R3)을 결정했으면 추천은 그 결정을 *다시 판정하지 않고 집행*한다 — 후보를 교정 대상
개념으로 제한하고 학습 밴드로 고른다. 집행 조건·안전장치는 `l2.learning_state_recommendation`
docstring이 정본이다. 지시가 없는 요청은 조회 0건이 추가되고 결과는 전환 전과 같다.

────────────────────────────────────────────────────────────────────────────
개념 그래프 예산 — depth ≤ 2 · nodes ≤ 20 · visited · timeout
────────────────────────────────────────────────────────────────────────────
CLAUDE.md 구축 플레이북의 "AI 연동 시" 하드 게이트를 이 모듈이 **구성 시점에** 강제한다:
`ConceptGraphBudget`은 천장(`_DEPTH_CEILING`=2·`_NODES_CEILING`=20)을 넘는 값으로는
**만들어지지 않는다**(생성자가 ValueError). 천장을 주석으로 적고 호출부의 선의에 맡기면
언젠가 누군가 3을 넣는다 — 그때 막는 것은 코드여야 한다.

세 장치가 각각 다른 폭발을 막는다. `max_depth`는 *깊이*(선수의 선수의 선수…), `max_nodes`는
*너비*(hub 노드의 fan-out), `timeout`은 *시간*(DB가 느릴 때 추천 전체가 매달리는 것)이다.
visited set은 DAG의 diamond에서 같은 노드를 여러 경로로 다시 세는 것을 막는다 — 이 세
장치 중 하나라도 없으면 나머지 둘이 통과시킨다.

**전체 그래프를 읽지 않는다**: traversal은 *앵커 개념 1개*에서 출발하는 재귀 CTE(선수 —
`l2.prerequisite_recommendation.fetch_prerequisites`)와 1-hop 조회(후행 — `l2.next_problem_
selection.load_direct_successors`)이고, 그 결과를 다시 예산으로 자른다. 두 조회 모두 시간 예산을
`_within_budget` 한 곳에서 받는다. 개념 전수 조회(`SELECT * FROM concept`) 경로는 이 모듈에 없다.

계층: `l2`. L3~L6을 import하지 않는다 — 수능 모드 정책은 L6 게이팅이 필요해 이 모듈에 둘 수
없고(l2→l6 역방향 금지), L6은 DB를 만질 수 없어(import-linter "데이터 접근 금지" 계약) 그쪽에도
둘 수 없다. 그래서 수능 정책은 두 계층을 합법적으로 합성할 수 있는 유일한 자리인 API 합성
지점(`api/_next_problem_policy.py`)에 산다. 같은 Protocol을 구현하므로 핸들러가 보는 모양은
같다.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol, TypedDict, TypeVar

from pydantic import Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.l2.irt import (
    IrtItem,
    item_information,
    learning_band_weight,
    select_weighted_item,
)
from whymath_backend.l2.learner_state import LearnerState
from whymath_backend.l2.learning_state_recommendation import (
    StateDirectiveOutcome,
    StateRoute,
    collect_remediation_reason,
    route_by_learning_state,
)
from whymath_backend.l2.next_problem_selection import (
    CANDIDATE_ZERO_NO_POOL,
    WEIGHT_AXIS_WEAK_CONCEPT,
    CandidateRow,
    candidate_items,
    combine_weights,
    last_incorrect_problem_id,
    load_attempt_history_state,
    load_candidate_rows,
    load_direct_successors,
    load_sibling_ids,
    load_target_candidate_rows,
    load_weak_concept_weights,
    sibling_weights,
)
from whymath_backend.l2.prerequisite_recommendation import PrerequisiteRow, fetch_prerequisites
from whymath_backend.l2.recommendation_contract import (
    PREREQUISITE_MASTERY_CEILING,
    WEAK_CONCEPT_MASTERY_CEILING,
    LearningContext,
    ReasonType,
    Recommendation,
    RecommendationPolicy,
    RecommendationReason,
    action_for,
    check_intent_alignment,
    demote_to_current_concept,
)
from whymath_backend.l2.recommendation_evidence import (
    POLICY_VERSION_CAT,
    POLICY_VERSION_CAT_STATE_REMEDIATION,
)
from whymath_backend.l2.recommendation_reason import (
    collect_concept_reason,
    collect_recommendation_reason,
)

__all__ = [
    "DEFAULT_GRAPH_BUDGET",
    "CatRecommendationPolicy",
    "ConceptGraphBudget",
    "IntentResolution",
    "NextProblemOutcome",
    "NextProblemPolicy",
    "PolicyIntent",
    "PolicyTelemetry",
    "resolve_policy_intent",
    "resolve_target_concept",
]

_T = TypeVar("_T")

_logger = logging.getLogger("whymath.l2.recommendation_policy")

# ── 개념 그래프 예산 천장 — CLAUDE.md "AI 연동 시" 하드 게이트의 수치 정본 ────────────────────
# 이 둘은 *상한*이지 기본값이 아니다. 기본값은 `DEFAULT_GRAPH_BUDGET`이 따로 들고 있고, 천장은
# 어떤 호출부도 넘을 수 없는 선이다(생성자가 거부). 값을 올리려면 이 줄을 고쳐야 하고, 이 줄을
# 고치면 `tests/backend/l2/test_recommendation_policy.py`의 천장 동결 테스트가 RED가 된다 —
# 즉 완화가 조용히 일어날 수 없다.
_DEPTH_CEILING = 2
_NODES_CEILING = 20


@dataclass(frozen=True, slots=True)
class ConceptGraphBudget:
    """개념 그래프 traversal 예산 — 천장을 넘는 값으로는 **생성되지 않는다**.

    `max_depth`(깊이)·`max_nodes`(너비)·`timeout_seconds`(시간)는 서로 다른 폭발을 막으므로
    하나로 합치지 않는다. 셋 중 하나만 있으면 나머지 둘이 열린 문이 된다.

    검증을 `__post_init__`에 둔 이유: 호출 시점 검사는 *그 호출*만 막지만 생성 시점 검사는
    **그 예산을 쓰는 모든 호출**을 막는다. 예산 객체가 존재한다는 사실 자체가 유효성의 증거가
    되게 한다(CLAUDE.md "보호 장치를 실패 주입 없이 보호 있음으로 선언 금지"의 설계 축).
    """

    max_depth: int = 2
    max_nodes: int = 20
    timeout_seconds: float = 2.0

    def __post_init__(self) -> None:
        if not 1 <= self.max_depth <= _DEPTH_CEILING:
            raise ValueError(
                f"max_depth={self.max_depth}는 허용 범위 1~{_DEPTH_CEILING} 밖입니다 — "
                "LLM·추론 컨텍스트로 흘러드는 subgraph의 깊이 상한은 협상 대상이 아닙니다."
            )
        if not 1 <= self.max_nodes <= _NODES_CEILING:
            raise ValueError(
                f"max_nodes={self.max_nodes}는 허용 범위 1~{_NODES_CEILING} 밖입니다 — "
                "노드 폭발은 관계 폭발·추론 실패로 이어집니다(구축 플레이북 7대 붕괴 연쇄)."
            )
        if self.timeout_seconds <= 0:
            raise ValueError(
                f"timeout_seconds={self.timeout_seconds}는 양수여야 합니다 — "
                "상한 없는 traversal은 추천 전체를 매달리게 합니다."
            )


#: 정책 기본 예산. 천장(2·20)과 같은 값이지만 **다른 것**이다 — 기본값은 정책이 고르는 수이고
#: 천장은 아무도 넘을 수 없는 선이다. 둘을 한 상수로 접으면 기본값을 낮추는 변경이 천장까지
#: 함께 내려 다른 호출부를 조용히 깨뜨린다.
DEFAULT_GRAPH_BUDGET = ConceptGraphBudget()


def _apply_node_budget(
    rows: list[PrerequisiteRow], budget: ConceptGraphBudget
) -> list[PrerequisiteRow]:
    """visited set(중복 제거) + 노드 수 예산 — 초과 절단은 **로그를 남긴다**(침묵 절단 금지).

    `fetch_prerequisites`도 자기 dedup·자기 예산(64)을 갖지만, 그것은 *그 좌석의* 안전밸브이고
    이것은 *이 정책의* 예산이다. 정책이 상위 좌석의 기본값에 자기 상한을 위임하면, 그쪽 기본값이
    올라가는 날 이쪽 상한도 모르는 사이 따라 올라간다 — 그래서 여기서 다시 센다(중복 방어가
    아니라 소유권 분리다).
    """
    visited: set[uuid.UUID] = set()
    deduped: list[PrerequisiteRow] = []
    for row in rows:
        if row.concept_id in visited:
            continue
        visited.add(row.concept_id)
        deduped.append(row)
    if len(deduped) <= budget.max_nodes:
        return deduped
    _logger.warning(
        "개념 그래프 노드 예산 초과 — %d개 중 상위 %d개만 유지(드롭 %d)",
        len(deduped),
        budget.max_nodes,
        len(deduped) - budget.max_nodes,
    )
    return deduped[: budget.max_nodes]


async def _within_budget(budget: ConceptGraphBudget, read: Callable[[], Awaitable[_T]]) -> _T:
    """그래프 읽기 1건에 **시간 예산**을 건다 — 초과 시 `TimeoutError`(판정은 호출부가 한다).

    시간 예산을 거는 자리를 이 함수 하나로 모은 이유: 호출부마다 `asyncio.timeout`을 직접 쓰면
    새 그래프 읽기가 추가될 때 예산을 빠뜨려도 아무것도 모른다. 여기를 지나지 않는 그래프 읽기는
    리뷰에서 눈에 띄고, 여기를 지나는 읽기는 전부 같은 예산을 받는다.
    """
    async with asyncio.timeout(budget.timeout_seconds):
        return await read()


async def _budgeted_prerequisites(
    session: AsyncSession, concept_id: uuid.UUID, budget: ConceptGraphBudget
) -> list[PrerequisiteRow]:
    """선수 traversal — 깊이·시간 예산을 **한 곳에서** 건다(목표 판정·정책 의도 두 호출부 공용)."""
    return await _within_budget(
        budget, lambda: fetch_prerequisites(session, concept_id, max_depth=budget.max_depth)
    )


async def resolve_target_concept(
    session: AsyncSession,
    *,
    reason: RecommendationReason,
    learner_state: LearnerState,
    budget: ConceptGraphBudget = DEFAULT_GRAPH_BUDGET,
) -> uuid.UUID | None:
    """**다음에 다뤄야 할 개념** — 선수 막힘이면 막힌 선수개념, 아니면 문항의 개념.

    계획서 §8의 `PRACTICE_PREREQUISITE`는 "선수개념을 연습하라"는 행위인데, *어느* 선수개념인지를
    말하지 않으면 그 행위는 실행할 수 없다. 이 함수가 그 목적어를 채운다.

    판정: 선수 후보 중 `learner_state.mastery`(개념코드 키)에 **측정이 있는 것들** 중 최저 숙달.
    측정 없는 선수는 고르지 않는다 — 콜드스타트 선수를 "막혔다"고 부르면 근거 없음이 근거로
    위장된다(계약의 `UNMEASURED`/`COLD_START` 분리와 같은 규율). 측정된 선수가 하나도 없으면
    문항 자신의 개념으로 폴백한다(그쪽은 실측 숙달이 있는 것이 확정이다 — `PREREQUISITE_GAP`은
    측정에서만 나온다).

    예산 초과·시간 초과는 **추천을 실패시키지 않는다**: traversal이 타임아웃되면 폴백으로
    내려가고 그 사실을 로그에 남긴다(예외 타입명 포함 — CLAUDE.md 침묵 실패 금지). 근거를
    풍부하게 하는 부가 조회 때문에 학생이 문항을 못 받는 것은 우선순위가 거꾸로다.

    **EOS-124 이후 소비처는 수능 정책뿐이다**(기본 CAT은 `resolve_policy_intent`로 옮겼다).
    이 함수에는 EOS-124가 실측한 결함이 **그대로 남아 있다** — "최저 숙달"은 선수가 전부 숙달이어도
    그중 하나를 막힌 선수로 부르고, 선수가 미측정이면 문항 개념으로 폴백해 `practice_prerequisite`가
    제자리를 가리킨다. 수능 정책의 변경은 별도 판정이 필요해(L6 게이팅과 재선택의 상호작용) 이
    함수를 고치지 않고 `EOS-25`로 분리했다 — 고치면 수능 추천이 판정 없이 바뀐다.
    """
    if reason.concept_id is None:
        return None
    if reason.type is not ReasonType.PREREQUISITE_GAP:
        # 선수로 되돌아가라는 추천이 아니면 목표는 문항의 개념 그대로다 — 그래프를 읽지 않는다
        # (읽을 이유가 없는 조회를 "있으면 좋으니" 넣지 않는다).
        return reason.concept_id

    try:
        rows = await _budgeted_prerequisites(session, reason.concept_id, budget)
    except (TimeoutError, asyncio.CancelledError) as exc:
        _logger.warning(
            "선수 traversal 예산 초과(%s) — 목표 개념을 문항 개념으로 폴백합니다. concept=%s",
            type(exc).__name__,
            reason.concept_id,
        )
        return reason.concept_id

    measured: list[tuple[float, PrerequisiteRow]] = []
    for row in _apply_node_budget(rows, budget):
        if row.concept_code is None:
            continue
        mastery = learner_state.mastery.get(row.concept_code)
        if mastery is not None:
            measured.append((mastery, row))
    if not measured:
        return reason.concept_id
    # 최저 숙달이 최우선 — 동률이면 가까운 선수(depth 낮은 쪽)·그다음 id로 결정론 고정.
    weakest = min(measured, key=lambda pair: (pair[0], pair[1].depth, str(pair[1].concept_id)))
    return weakest[1].concept_id


class IntentResolution(str, Enum):
    """정책 의도(숙달 구간 규칙)가 **전달된 콘텐츠로 어떻게 해소됐나** — EOS-124 관측 축.

    CLAUDE.md "작동한 비율" 원칙의 이행이다: 정렬 선택을 붙였으면 그것이 실제로 몇 번 일했는지를
    응답·처치 기록이 말해야 한다. 정상 응답 200은 정렬이 일했다는 증거가 아니다 — 목표 개념에
    문항이 없어 매번 강등되는 상태도 200이다. 이 값이 그 둘을 가른다.

    강등 사유를 셋으로 나누는 이유(**모른다 ≠ 아니다**): 측정이 관계 행위를 *반증*한 것(`REFUTED`
    — 선수가 전부 숙달)과 근거가 *없는* 것(`UNSUPPORTED` — 엣지 없음·선수 미측정)과 목표는 섰는데
    *문항이 없는* 것(`TARGET_UNAVAILABLE`)은 고칠 곳이 다르다. 첫째는 정상 교수학이고, 둘째는
    그래프·측정 커버리지 공백이며, 셋째는 콘텐츠 공백이다. 한 값으로 접으면 어디를 고칠지 모른다.
    """

    DIRECT = "direct"
    """규칙이 앵커 개념 자신을 가리켰다(연습·진단·미매핑) — 1차 선택을 그대로 전달한다."""

    SERVED = "served"
    """관계 행위(선수 복귀·전진)를 전달 문항이 **실제로 싣는다** — 설명과 콘텐츠가 같은 개념."""

    REFUTED = "refuted"
    """규칙은 관계 행위를 가리켰으나 **측정이 반증**했다(측정된 선수가 전부 숙달 · 후행이 전부
    이미 숙달). 앵커 개념 연습으로 정직 강등한다."""

    UNSUPPORTED = "unsupported"
    """규칙은 관계 행위를 가리켰으나 **근거가 없다**(선수·후행 엣지 없음 · 선수 전부 미측정).
    반증과 구별한다. 앵커 개념 연습으로 정직 강등한다."""

    GRAPH_TIMEOUT = "graph_timeout"
    """그래프 조회가 시간 예산을 넘어 판정하지 못했다 — 정직 강등(예외 타입명 로그 동반)."""

    TARGET_UNAVAILABLE = "target_unavailable"
    """목표 개념은 섰으나 출제 가능한(노출 게이트 통과·미응답) 문항이 없다 — 정직 강등."""

    NO_CANDIDATE = "no_candidate"
    """후보가 아예 없다 — 추천 자체가 없다(`problem_id=None`)."""


@dataclass(frozen=True, slots=True)
class PolicyIntent:
    """정책 의도 1건 — 최종 근거 + 해소 판정 + (필요하면) 재선택할 목표 개념 묶음.

    `reselect_groups`가 비어 있으면 1차 선택 문항을 그대로 전달한다(이미 의도와 맞다). 비어 있지
    않으면 앞 묶음부터 차례로 그 개념들의 문항을 찾고, 처음 찾은 묶음에서 고른다 — 묶음 순서가
    곧 우선순위다(선수는 가장 약한 것부터 한 개념씩, 전진은 열린 후행 전체를 한 묶음으로).
    이때 `resolution=SERVED`는 "찾으면 SERVED"라는 뜻이고, 하나도 못 찾으면 호출부가
    `TARGET_UNAVAILABLE`로 강등한다.
    """

    reason: RecommendationReason
    resolution: IntentResolution
    reselect_groups: tuple[tuple[uuid.UUID, ...], ...] = ()


def _demoted(anchor_reason: RecommendationReason, resolution: IntentResolution) -> PolicyIntent:
    """관계 행위를 실을 수 없다 — 앵커 개념 연습으로 **정직 강등**(재선택 없음)."""
    return PolicyIntent(reason=demote_to_current_concept(anchor_reason), resolution=resolution)


def _mastery_of(code: str | None, learner_state: LearnerState) -> float | None:
    """개념코드의 실측 숙달 — 코드가 없거나 측정이 없으면 None(0으로 접지 않는다)."""
    return learner_state.mastery.get(code) if code is not None else None


async def resolve_policy_intent(
    session: AsyncSession,
    *,
    anchor_reason: RecommendationReason,
    learner_state: LearnerState,
    learner_id: uuid.UUID,
    budget: ConceptGraphBudget = DEFAULT_GRAPH_BUDGET,
) -> PolicyIntent:
    """앵커 개념의 숙달 구간 규칙(계획서 §8)을 **그래프·측정 근거로 확인**해 의도를 세운다.

    앵커 = 1차 선택(기본 CAT — θ·가중·밴드 무변경)이 고른 문항의 대표 개념이다. 구간 규칙
    (`select_reason_type`)은 그대로 정본이고, 이 함수는 그 규칙이 가리킨 *관계 행위*를 실제
    목표 개념으로 바꾼다. 관계 행위가 아니면(연습·진단·미매핑) 그래프를 읽지 않는다.

    **선수 구간(숙달 < 0.4)** — 세 갈래를 차례로 본다:
      (가) 앵커의 측정된 선수 중 **아직 약한 것**(숙달 < `WEAK_CONCEPT_MASTERY_CEILING`)이 있다 →
           가장 약한 것부터 재선택 목표로. EOS-124 (나)가 여기서 막힌다: 선수가 1.0으로 숙달됐으면
           목표가 되지 않는다(종전 `resolve_target_concept`는 측정된 선수 중 *최저*를 골라, 전부
           숙달이어도 그중 하나를 "막힌 선수"로 불렀다).
      (나) 앵커 자신이 **막힌 후행**(숙달 < 0.4)의 직접 선수다 → 근거를 그 후행으로 옮기고, 목표는
           이미 전달될 앵커 문항이다(재선택 없음). "원래 개념이 막혀서 선수를 연습한다"는 설명이
           여기서 선다 — 1차 선택이 이미 선수 문항을 골랐을 때의 정확한 이유다.
      (다) 둘 다 아니다 → 앵커 개념 연습으로 정직 강등(측정된 선수가 있으면 `REFUTED`, 없으면
           `UNSUPPORTED`).

    **전진 구간(숙달 > 0.7)** — 앵커의 직접 후행 중 **아직 숙달되지 않은 것**(미측정 포함)을 한
    묶음으로 재선택 목표로. EOS-124 (가)가 여기서 막힌다: 숙달한 개념의 문항에 `advance_next`를
    붙이는 대신 다음 개념 문항을 찾는다. 후행이 없거나 전부 숙달이면 정직 강등.

    **미측정 선수는 목표가 아니다**(종전 규율 유지): 측정 없는 선수를 "막혔다"고 부르면 근거
    없음이 근거로 위장된다. 미측정 선수를 *진단*하러 내려가는 것은 별도 교수학 판정이 필요한
    선택 변경이라 여기서 하지 않는다.

    **예산**: 선수 traversal은 `_budgeted_prerequisites`(깊이·시간), 후행 조회는 `max_nodes`(너비)
    와 같은 시간 예산을 탄다. 시간 초과는 추천을 실패시키지 않고 `GRAPH_TIMEOUT` 강등으로 내려가며
    예외 타입명을 로그에 남긴다(침묵 실패 금지).
    """
    anchor = anchor_reason.concept_id
    if anchor is None or anchor_reason.type not in (
        ReasonType.PREREQUISITE_GAP,
        ReasonType.NEXT_CONCEPT,
    ):
        return PolicyIntent(reason=anchor_reason, resolution=IntentResolution.DIRECT)
    try:
        if anchor_reason.type is ReasonType.PREREQUISITE_GAP:
            return await _prerequisite_intent(
                session,
                anchor_reason=anchor_reason,
                anchor=anchor,
                learner_state=learner_state,
                learner_id=learner_id,
                budget=budget,
            )
        return await _advance_intent(
            session,
            anchor_reason=anchor_reason,
            anchor=anchor,
            learner_state=learner_state,
            budget=budget,
        )
    except TimeoutError as exc:
        _logger.warning(
            "정책 의도 판정 중 그래프 예산 초과(%s) — 앵커 개념 연습으로 정직 강등. concept=%s",
            type(exc).__name__,
            anchor,
        )
        return _demoted(anchor_reason, IntentResolution.GRAPH_TIMEOUT)


async def _prerequisite_intent(
    session: AsyncSession,
    *,
    anchor_reason: RecommendationReason,
    anchor: uuid.UUID,
    learner_state: LearnerState,
    learner_id: uuid.UUID,
    budget: ConceptGraphBudget,
) -> PolicyIntent:
    """선수 구간 의도 — (가) 약한 선수로 내려가기 · (나) 막힌 후행의 선수로 설명 · (다) 강등."""
    rows = _apply_node_budget(await _budgeted_prerequisites(session, anchor, budget), budget)
    measured = [
        (mastery, row)
        for row in rows
        if (mastery := _mastery_of(row.concept_code, learner_state)) is not None
    ]
    weak = sorted(
        (pair for pair in measured if pair[0] < WEAK_CONCEPT_MASTERY_CEILING),
        # 가장 약한 선수가 최우선 — 동률이면 가까운 선수(depth 낮은 쪽)·그다음 id로 결정론 고정.
        key=lambda pair: (pair[0], pair[1].depth, str(pair[1].concept_id)),
    )
    if weak:
        return PolicyIntent(
            reason=anchor_reason,
            resolution=IntentResolution.SERVED,
            reselect_groups=tuple((row.concept_id,) for _m, row in weak),
        )

    successors = await _within_budget(
        budget, lambda: load_direct_successors(session, anchor, max_nodes=budget.max_nodes)
    )
    blocked = sorted(
        (
            (mastery, succ)
            for succ in successors
            if (mastery := _mastery_of(succ.concept_code, learner_state)) is not None
            and mastery < PREREQUISITE_MASTERY_CEILING
        ),
        key=lambda pair: (pair[0], str(pair[1].concept_id)),
    )
    if blocked:
        blocked_concept = blocked[0][1].concept_id
        blocked_reason = await collect_concept_reason(
            session, learner_id=learner_id, concept_id=blocked_concept
        )
        if blocked_reason.type is ReasonType.PREREQUISITE_GAP:
            return PolicyIntent(reason=blocked_reason, resolution=IntentResolution.SERVED)
        # 학습자 상태(진단 스냅샷)와 최신 숙달 이력이 구간을 다르게 말한다 — 둘 중 하나가 낡았다.
        # 근거를 한쪽에 맞춰 지어내지 않고 (다)로 내려간다(로그로 드러낸다).
        _logger.warning(
            "막힌 후행 판정 불일치 — 학습자 상태는 선수 구간, 최신 숙달 근거는 %s. concept=%s",
            blocked_reason.type.value,
            blocked_concept,
        )
    return _demoted(
        anchor_reason, IntentResolution.REFUTED if measured else IntentResolution.UNSUPPORTED
    )


async def _advance_intent(
    session: AsyncSession,
    *,
    anchor_reason: RecommendationReason,
    anchor: uuid.UUID,
    learner_state: LearnerState,
    budget: ConceptGraphBudget,
) -> PolicyIntent:
    """전진 구간 의도 — 아직 숙달되지 않은 직접 후행을 한 묶음으로 재선택 목표로."""
    successors = await _within_budget(
        budget, lambda: load_direct_successors(session, anchor, max_nodes=budget.max_nodes)
    )
    open_successors = tuple(
        succ.concept_id
        for succ in successors
        # 전진 구간 경계와 같은 선(> 0.7이면 숙달)이다 — 미측정은 열린 것으로 본다.
        if (mastery := _mastery_of(succ.concept_code, learner_state)) is None
        or mastery <= WEAK_CONCEPT_MASTERY_CEILING
    )
    if open_successors:
        return PolicyIntent(
            reason=anchor_reason,
            resolution=IntentResolution.SERVED,
            reselect_groups=(open_successors,),
        )
    return _demoted(
        anchor_reason, IntentResolution.REFUTED if successors else IntentResolution.UNSUPPORTED
    )


class NextProblemOutcome(Recommendation):
    """정책의 반환값 — 계약(`Recommendation`) + **이 정책이 어떻게 돌았나**의 관측 메타.

    `Recommendation`을 상속하는 것이 핵심이다: `RecommendationPolicy` Protocol의 반환 계약
    (`-> Recommendation`)을 그대로 만족하면서(리스코프·반환 공변) 호출부는 필요하면 관측
    필드까지 읽을 수 있다. 관측 메타를 계약 자체에 넣지 않는 이유는 그것이 *정책마다 다른*
    것이기 때문이다 — BKT 정책의 관측 축과 IRT CAT의 관측 축은 같지 않다.

    여기 실리는 5필드는 `EOS-14`가 "관측 메타"로 규정한 기존 응답 필드와 **같은 값**이다
    (`weight_axes_applied`·`candidate_pool_size`·`weak_concept_signal_count`·
    `candidate_zero_reason`·`band_calibrated`). 핸들러가 재계산하던 것이 정책으로 내려온 것뿐이라
    응답은 바이트 동일하다.
    """

    theta: float = Field(description="추천에 쓰인 현재 능력 추정 θ(logit). 응답 없으면 0.")
    difficulty: float | None = Field(
        default=None, description="추천 문항의 difficulty_overall(전문가 1~5). 없으면 null."
    )
    standard_error: float | None = Field(
        default=None, description="현재 θ 추정의 표준오차(응답한 문항 기준). 응답 없으면 null."
    )
    measurement_sufficient: bool = Field(
        default=False, description="SE가 목표 이하면 True — 적응 검사 중단 권고."
    )
    weight_axes_applied: list[str] = Field(
        default_factory=list, description="이번 응답에 실제로 적용된 가중 축 이름 목록."
    )
    applied_weights: bool = Field(
        default=False,
        description=(
            "REC-03 처치 기록용 — 가중 벡터가 **하나라도** 계산됐는가. `weight_axes_applied`와 "
            "다르다: 그쪽은 학생에게 보이는 *정직 표기*라 약점·수능 축만 싣지만, 이것은 학습 "
            "밴드(purpose=learning)·형제 가중까지 포함한 내부 사실이다. 둘을 하나로 접으면 "
            "`purpose=learning`만 준 요청이 '가중 미적용'으로 기록된다(전환 전 동작과 다름)."
        ),
    )
    candidate_pool_size: int = Field(default=0, description="이번 요청의 실제 후보 풀 크기.")
    weak_concept_signal_count: int = Field(
        default=0, description="후보 중 약점 가중이 1.0이 아니게 된 문항 수."
    )
    candidate_zero_reason: str | None = Field(
        default=None, description="problem_id가 null일 때만 채워지는 사유 코드."
    )
    band_calibrated: bool | None = Field(
        default=None, description="purpose=learning일 때만 False(문헌값·실측 미보정)."
    )
    learning_state_directive: StateDirectiveOutcome | None = Field(
        default=None,
        description=(
            "EOS-24 — 학습 상태 머신이 이 추천을 지시했을 때 그 처리 결과(`applied`=집행 · 그 외="
            "집행하지 못한 사유). 상태 머신이 지시하지 않았으면 null. 수능 정책은 상태 머신을 "
            "읽지 않으므로 항상 null이다(판정문 §7-3)."
        ),
    )
    candidate_scores: list[tuple[uuid.UUID, float]] = Field(
        default_factory=list,
        description=(
            "REC-11 소급 평가 재료 — 후보별 점수(정보량×가중). 학생 응답에는 싣지 않는다"
            "(처치 기록 meta 전용 — 후보 노출은 출제 보안 축이다). 정렬 재선택(EOS-124)으로 "
            "전달된 문항이면 *그 문항을 고른 목표 개념 후보들*의 점수다 — 전달 문항이 비교 집합 "
            "안에 있어야 소급 평가가 성립한다."
        ),
    )
    intent_resolution: IntentResolution | None = Field(
        default=None,
        description=(
            "EOS-124 — 정책 의도가 전달 콘텐츠로 어떻게 해소됐나(관측 메타 · `IntentResolution`). "
            "**None이면 이 정책은 정렬 계약을 아직 적용하지 않는다**(수능 정책 — 후속 태스크)."
        ),
    )
    delivered_concept: uuid.UUID | None = Field(
        default=None,
        description=(
            "전달 문항의 대표 개념 — 정렬 판정(`check_intent_alignment`)의 입력. 응답에는 싣지 "
            "않는다(`target_concept`과 같은 값이어야 하므로 응답에는 그쪽 하나로 충분하다)."
        ),
    )

    @model_validator(mode="after")
    def _aligned_when_declared(self) -> "NextProblemOutcome":
        """정렬 계약을 **선언한**(`intent_resolution`이 있는) 산출은 어긋난 채로 만들어지지 않는다.

        EOS-124 집행 지점이다. 계약을 주석으로 적고 정책의 선의에 맡기면 다음 수정이 조용히
        깬다(EOS-19가 `target_concept`을 문항 개념과 따로 계산한 것이 정확히 그 형태였다) —
        그래서 산출 객체가 **존재한다는 사실 자체**가 정렬의 증거가 되게 한다. 핸들러는 이
        객체를 HTTP 응답으로 옮기기만 하므로, 이 검증은 실제 서빙 응답이 반드시 지나가는 자리다.

        `intent_resolution=None`(수능 정책)은 검증하지 않는다 — 그 정책은 아직 정렬하지 않으며,
        이 검증을 걸면 그 경로가 500으로 죽는다. 정렬하지 않는다는 사실은 응답에 None으로
        정직하게 드러난다.
        """
        if self.intent_resolution is not None:
            check_intent_alignment(
                problem_id=self.problem_id,
                action=self.action,
                reason_concept_id=self.reason.concept_id,
                target_concept=self.target_concept,
                delivered_concept=self.delivered_concept,
            )
        return self


class PolicyTelemetry(TypedDict):
    """두 정책이 공통으로 채우는 관측 필드 묶음 — `**telemetry`로 넘기기 위한 타입.

    `dict[str, Any]`로 두면 오타 난 키가 조용히 통과해 `NextProblemOutcome` 기본값으로
    떨어진다(예: `weak_concept_signal_count`를 빠뜨리면 0이 나가는데, 그것은 "신호가 없었다"와
    구별되지 않는다). TypedDict는 그 실수를 mypy가 잡게 한다.
    """

    theta: float
    standard_error: float | None
    measurement_sufficient: bool
    weight_axes_applied: list[str]
    applied_weights: bool
    candidate_pool_size: int
    weak_concept_signal_count: int
    band_calibrated: bool | None
    policy_version: str


class NextProblemPolicy(Protocol):
    """`GET /v1/me/next-problem`이 쓰는 정책 — 계약(`RecommendationPolicy`)의 **정제**.

    계약과 다른 점은 둘뿐이다: 상태 타입이 `LearnerState`로 좁혀졌고(제네릭 인자), 반환이
    `Recommendation`의 하위타입 `NextProblemOutcome`으로 좁혀졌다. 좁히는 방향이 맞으므로
    이 Protocol을 만족하는 구현체는 계약도 만족한다 — 그 사실을 사람이 읽고 믿는 대신 아래
    `_contract_conformance`가 **mypy에게 판정시킨다**(CI의 `mypy --strict` 스텝이 이 파일을
    본다). 어긋나는 순간 타입 검사가 거부한다.

    핸들러가 이 타입으로 정책을 받으면 *어느 정책인지 모르는 채로* 관측 필드까지 읽을 수 있다.
    """

    async def __call__(
        self, learner_state: LearnerState, learning_context: LearningContext
    ) -> NextProblemOutcome: ...


if TYPE_CHECKING:  # pragma: no cover — 타입 검사 전용(런타임 코드 아님)

    def _contract_conformance(
        policy: NextProblemPolicy,
    ) -> RecommendationPolicy[LearnerState]:
        """정제 Protocol이 계약을 만족하는지 **mypy가** 판정한다(주석이 아니라 타입으로).

        `NextProblemPolicy`가 계약에서 벗어나면(매개변수를 늘리거나 반환을 `Recommendation`의
        하위타입이 아닌 것으로 바꾸면) 이 반환문이 타입 오류가 된다.
        """
        return policy


@dataclass(frozen=True, slots=True)
class _Delivery:
    """실제로 학생에게 나갈 문항 1건 — 문항·난이도·**대표 개념**·그 선택의 후보 점수."""

    problem_id: uuid.UUID
    difficulty: float | None
    concept_id: uuid.UUID | None
    scores: list[tuple[uuid.UUID, float]]


def _candidate_scores(
    theta: float,
    rows: list[CandidateRow],
    items: list[IrtItem],
    weights: list[float] | None,
) -> list[tuple[uuid.UUID, float]]:
    """REC-11 후보 점수 — `select_weighted_item`과 **같은 공식**(정보량 × 가중)의 관측 재계산."""
    return [
        (pid, item_information(theta, item) * (weights[i] if weights is not None else 1.0))
        for i, ((pid, _d, _b), item) in enumerate(zip(rows, items, strict=True))
    ]


class CatRecommendationPolicy:
    """기본 CAT 추천 정책 v1 — IRT 정보량 최대 × (약점·밴드·형제) 가중.

    `RecommendationPolicy` Protocol의 구현체다. 세션을 생성자로 받고 `__call__`이
    `(learner_state, learning_context)`만 받는 것은 계약의 요구다 — DB 핸들은 *정책의 설비*이지
    *추천의 입력*이 아니므로 시그니처에 넣지 않는다. 이 구분 덕에 나중에 DB를 쓰지 않는 정책
    (순수 규칙·원격 모델)이 같은 자리에 들어갈 수 있다.

    `sibling_filter`도 생성자 인자다: 형제 필터는 학습자 상태도 요청 상황도 아닌 *실험 손잡이*라
    `LearningContext`에 넣으면 계약이 전송 관심사로 오염된다(계약 docstring의 금지 사항).
    """

    policy_version = POLICY_VERSION_CAT

    def __init__(
        self,
        session: AsyncSession,
        *,
        sibling_filter: str | None = None,
        graph_budget: ConceptGraphBudget = DEFAULT_GRAPH_BUDGET,
    ) -> None:
        self._session = session
        self._sibling_filter = sibling_filter
        self._graph_budget = graph_budget

    async def __call__(
        self, learner_state: LearnerState, learning_context: LearningContext
    ) -> NextProblemOutcome:
        """추천 1건 — 1차 선택 → 앵커 근거 → 정책 의도 → (필요하면) 정렬 재선택 → 산출.

        1차 선택(후보 조회 → 가중 결합 → 정보량 최대)은 이동 전 핸들러의 기본 CAT 경로와 **같은
        순서·같은 연산**이다. 그 뒤가 EOS-124다: 앵커 개념의 숙달 구간이 관계 행위를 가리키면
        목표 개념의 문항으로 다시 고르고, 못 고르면 정직 강등한다(모듈 docstring "EOS-124" 절).
        반환은 `NextProblemOutcome`(계약 + 관측)이므로 이 정책은 HTTP를 모른다.
        """
        session = self._session
        user_id = uuid.UUID(learner_state.student_id)

        attempt_state = await load_attempt_history_state(session, user_id)
        theta = attempt_state.theta

        # S4-14 — sibling_filter 지정 + 직전 오답 존재 시에만 형제 조회(쿼리 0회 증가 보존 원칙).
        sibling_ids: set[uuid.UUID] = set()
        if self._sibling_filter is not None:
            last_wrong = await last_incorrect_problem_id(session, user_id)
            if last_wrong is not None:
                sibling_ids = await load_sibling_ids(session, last_wrong)

        excluded_ids = sibling_ids if self._sibling_filter == "exclude" else set()
        # EOS-24 — 학습 상태 머신이 오개념 교정(R3)을 결정했으면 추천은 그 결정을 *집행*한다:
        # 후보를 교정 대상 개념으로 제한하고, 목적이 측정이 아니라 교정 확인이므로 학습 밴드로
        # 고른다. 지시가 없으면 `state_route`는 None이고 조회 0건 — 아래는 전환 전과 같다.
        state_route = await route_by_learning_state(
            session,
            learner_state,
            theta=theta,
            attempted_ids=attempt_state.attempted_ids,
            excluded_ids=excluded_ids,
        )
        applied_route: StateRoute | None = (
            state_route if state_route is not None and state_route.applied else None
        )
        effective_context = (
            learning_context.model_copy(update={"purpose": "learning"})
            if applied_route is not None
            else learning_context
        )

        # REC-04: purpose=learning일 때만 False(문헌값·미보정 — S4-15 전까지).
        band_calibrated = False if effective_context.purpose == "learning" else None

        candidate_rows = (
            list(applied_route.candidate_rows)
            if applied_route is not None
            else await load_candidate_rows(
                session,
                theta,
                attempted_ids=attempt_state.attempted_ids,
                excluded_ids=excluded_ids,
            )
        )
        candidate_pool_size = len(candidate_rows)
        items = candidate_items(candidate_rows)

        weights = await self._combine_axes(
            user_id=user_id,
            learning_context=effective_context,
            candidate_rows=candidate_rows,
            items=items,
            theta=theta,
            sibling_ids=sibling_ids,
        )
        weight_axes_applied = (
            [WEIGHT_AXIS_WEAK_CONCEPT] if learning_context.prioritize_weak_concepts else []
        )
        weak_signal = sum(1 for w in weights if w != 1.0) if weights is not None else 0

        best = select_weighted_item(theta, items, weights=weights)
        common: PolicyTelemetry = {
            "theta": theta,
            "standard_error": attempt_state.standard_error,
            "measurement_sufficient": attempt_state.measurement_sufficient,
            "weight_axes_applied": weight_axes_applied,
            # 전환 전 핸들러의 `applied_weights=weights is not None`과 **같은 식**이다.
            "applied_weights": weights is not None,
            "candidate_pool_size": candidate_pool_size,
            "weak_concept_signal_count": weak_signal,
            "band_calibrated": band_calibrated,
            # 집행된 추천만 다른 버전을 적는다 — 후보 생성 규칙이 다르므로(개념 제한 + 학습 밴드)
            # 소급 평가가 두 규칙의 로그를 섞지 않게 한다.
            "policy_version": (
                POLICY_VERSION_CAT_STATE_REMEDIATION
                if applied_route is not None
                else self.policy_version
            ),
        }
        directive = state_route.outcome if state_route is not None else None
        if best is None:
            no_candidate = await collect_recommendation_reason(
                session, learner_id=user_id, problem_id=None
            )
            # 기본 CAT에서 best is None은 후보가 비었다는 뜻뿐이다(items는 행과 1:1).
            # 추천이 없어도 이유는 있다 — 조회 0건(없는 문항의 개념을 묻지 않는다).
            return NextProblemOutcome(
                problem_id=None,
                reason=no_candidate,
                action=action_for(no_candidate.type),
                target_concept=None,
                candidate_zero_reason=CANDIDATE_ZERO_NO_POOL,
                intent_resolution=IntentResolution.NO_CANDIDATE,
                learning_state_directive=directive,
                **common,
            )

        chosen_id, chosen_difficulty, _b = candidate_rows[best]
        delivery = _Delivery(
            problem_id=chosen_id,
            difficulty=float(chosen_difficulty) if chosen_difficulty is not None else None,
            concept_id=None,  # 아래 두 갈래가 각자 채운다
            # REC-11: candidates[] 관측 — `select_weighted_item`과 *같은* 점수 공식(새 쿼리 0).
            scores=_candidate_scores(theta, candidate_rows, items, weights),
        )
        if applied_route is not None:
            # EOS-24 집행 경로 — 상태 머신 결정이 의도의 정본이다(추천은 재판정하지 않고 집행한다 ·
            # 판정문 §5). 후보가 개념 C의 **PRIMARY** 문항으로 제한됐으므로 전달 문항의 대표 개념이
            # 곧 C다. EOS-124 의도 판정은 돌리지 않는다 — 교정은 C 자신을 다루는 비관계 행위라
            # 정렬 계약 R4(목표 = 앵커 = 전달 개념)로 검증되고, 해소값은 `direct`다.
            reason = await collect_remediation_reason(
                session, learner_id=user_id, route=applied_route
            )
            resolution = IntentResolution.DIRECT
            delivery = _Delivery(
                problem_id=delivery.problem_id,
                difficulty=delivery.difficulty,
                concept_id=applied_route.concept_id,
                scores=delivery.scores,
            )
        else:
            # ── EOS-124: 1차 선택 → 앵커 → 정책 의도 → (필요하면) 정렬 재선택 ─────────────
            # 1차 선택은 위 그대로다(θ·가중·밴드 무변경). 그 문항의 대표 개념이 *앵커*가 되고,
            # 앵커의 숙달 구간 규칙(§8)이 관계 행위(선수 복귀·전진)를 가리키면 그 목표 개념의
            # 문항으로 다시 고른다. 못 고르면 1차 선택을 그대로 내보내되 설명을 정직하게 내린다
            # — 어느 쪽이든 **설명(action·target)은 전달된 문항의 개념을 가리킨다**
            # (`_aligned_when_declared`가 강제).
            anchor_reason = await collect_recommendation_reason(
                session, learner_id=user_id, problem_id=chosen_id
            )
            intent = await resolve_policy_intent(
                session,
                anchor_reason=anchor_reason,
                learner_state=learner_state,
                learner_id=user_id,
                budget=self._graph_budget,
            )
            delivery = _Delivery(
                problem_id=delivery.problem_id,
                difficulty=delivery.difficulty,
                concept_id=anchor_reason.concept_id,
                scores=delivery.scores,
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
            problem_id=delivery.problem_id,
            reason=reason,
            action=action_for(reason.type),
            target_concept=delivery.concept_id,
            delivered_concept=delivery.concept_id,
            intent_resolution=resolution,
            difficulty=delivery.difficulty,
            candidate_zero_reason=None,
            candidate_scores=delivery.scores,
            learning_state_directive=directive,
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
    ) -> _Delivery | None:
        """정렬 재선택 — 목표 개념 묶음을 우선순위 순으로 보며 **처음 문항이 있는 묶음**에서 고른다.

        선택 연산은 1차 선택과 같다: 같은 게이트·같은 θ 정렬로 읽은 후보에(`load_target_
        candidate_rows`) 같은 가중 축(`_combine_axes` — 약점·밴드·형제)을 곱하고 같은 선택기
        (`select_weighted_item`)로 고른다. 달라지는 것은 **후보 집합** 하나뿐이다 — 그래서 CAT θ·
        난이도 밴드는 이 경로에서도 그대로 작동한다(EOS-124 ⑥ 범위 밖 불변).

        조회는 1건이다: 모든 목표 개념의 후보를 한 번에 읽고(개념별 상한) 파이썬에서 묶음별로
        나눈다. 묶음마다 조회하면 약한 선수가 여럿이고 전부 문항이 없을 때 조회가 묶음 수만큼 는다.
        """
        rows = await load_target_candidate_rows(
            self._session,
            theta,
            concept_ids=[concept for group in groups for concept in group],
            attempted_ids=attempted_ids,
            excluded_ids=excluded_ids,
        )
        for group in groups:
            members = set(group)
            picked: list[CandidateRow] = []
            concept_of: dict[uuid.UUID, uuid.UUID] = {}
            for pid, difficulty, irt_b, concept in rows:
                # 한 문항이 같은 묶음의 두 개념에 PRIMARY로 걸려 두 번 나오면 한 번만 센다.
                if concept not in members or pid in concept_of:
                    continue
                picked.append((pid, difficulty, irt_b))
                concept_of[pid] = concept
            if not picked:
                continue
            items = candidate_items(picked)
            weights = await self._combine_axes(
                user_id=user_id,
                learning_context=learning_context,
                candidate_rows=picked,
                items=items,
                theta=theta,
                sibling_ids=sibling_ids,
            )
            best = select_weighted_item(theta, items, weights=weights)
            if best is None:
                continue
            chosen_id, chosen_difficulty, _b = picked[best]
            return _Delivery(
                problem_id=chosen_id,
                difficulty=float(chosen_difficulty),
                concept_id=concept_of[chosen_id],
                scores=_candidate_scores(theta, picked, items, weights),
            )
        return None

    async def _combine_axes(
        self,
        *,
        user_id: uuid.UUID,
        learning_context: LearningContext,
        candidate_rows: list[CandidateRow],
        items: list[IrtItem],
        theta: float,
        sibling_ids: set[uuid.UUID],
    ) -> list[float] | None:
        """가중 축 3종(약점·학습 밴드·형제)을 **이동 전과 같은 순서로** 곱 결합한다.

        순서가 계약인 이유: 곱셈은 교환법칙을 만족하지만 부동소수 곱은 결합 순서에 따라 마지막
        비트가 달라질 수 있고, 그 차이가 동률 후보의 argmax를 뒤집으면 추천이 바뀐다. 회귀 0을
        주장하려면 순서까지 같아야 한다.
        """
        weights: list[float] | None = None
        if learning_context.prioritize_weak_concepts and candidate_rows:
            weights = await load_weak_concept_weights(
                self._session, user_id, [pid for pid, _d, _b in candidate_rows]
            )
        if learning_context.purpose == "learning" and candidate_rows:
            band = [learning_band_weight(theta, item) for item in items]
            weights = (
                band if weights is None else [w * b for w, b in zip(weights, band, strict=True)]
            )
        if self._sibling_filter == "include" and sibling_ids and candidate_rows:
            weights = combine_weights(
                weights, sibling_weights([pid for pid, _d, _b in candidate_rows], sibling_ids)
            )
        return weights
