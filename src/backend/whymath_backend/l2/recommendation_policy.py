"""추천 정책 v1 — `recommend(learner_state, learning_context)`의 **첫 구현체** (EOS-19).

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
**추천 결과를 바꾸지 않는다** (acceptance ④ — 이 모듈의 가장 중요한 제약)
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
`learner_state.mastery`(개념코드 → BKT 숙달)가 **선수개념 목표 판정**의 유일한 입력이다.
선수 후보들의 숙달을 여기서 읽으므로 숙달 재조회가 0건이고, `learner_state`가 비면
(콜드스타트) 목표 판정이 문항 개념으로 자연 폴백한다. 그 경로는 `target_concept`으로
관측된다.

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

**전체 그래프를 읽지 않는다**: traversal은 *선택된 문항의 대표 개념 1개*에서 출발하는
재귀 CTE(`l2.prerequisite_recommendation.fetch_prerequisites`)이고, 그 결과를 다시 예산으로
자른다. 개념 전수 조회(`SELECT * FROM concept`) 경로는 이 모듈에 없다.

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
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, TypedDict

from pydantic import Field
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
    load_sibling_ids,
    load_weak_concept_weights,
    sibling_weights,
)
from whymath_backend.l2.prerequisite_recommendation import PrerequisiteRow, fetch_prerequisites
from whymath_backend.l2.recommendation_contract import (
    LearningContext,
    ReasonType,
    Recommendation,
    RecommendationPolicy,
    RecommendationReason,
    action_for,
)
from whymath_backend.l2.recommendation_evidence import (
    POLICY_VERSION_CAT,
    POLICY_VERSION_CAT_STATE_REMEDIATION,
)
from whymath_backend.l2.recommendation_reason import collect_recommendation_reason

__all__ = [
    "DEFAULT_GRAPH_BUDGET",
    "CatRecommendationPolicy",
    "ConceptGraphBudget",
    "NextProblemOutcome",
    "NextProblemPolicy",
    "PolicyTelemetry",
    "resolve_target_concept",
]

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
    """
    if reason.concept_id is None:
        return None
    if reason.type is not ReasonType.PREREQUISITE_GAP:
        # 선수로 되돌아가라는 추천이 아니면 목표는 문항의 개념 그대로다 — 그래프를 읽지 않는다
        # (읽을 이유가 없는 조회를 "있으면 좋으니" 넣지 않는다).
        return reason.concept_id

    try:
        async with asyncio.timeout(budget.timeout_seconds):
            rows = await fetch_prerequisites(session, reason.concept_id, max_depth=budget.max_depth)
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
            "(처치 기록 meta 전용 — 후보 노출은 출제 보안 축이다)."
        ),
    )


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
        """추천 1건 — 후보 조회 → 가중 결합 → 정보량 최대 선택 → 근거·목표 개념 조립.

        이동 전 핸들러의 기본 CAT 경로와 **같은 순서·같은 연산**이다(회귀 0). 달라진 것은 반환
        타입뿐이다: `NextProblemResponse`(HTTP 스키마)가 아니라 `NextProblemOutcome`(계약 +
        관측)을 내므로, 이 정책은 HTTP를 모른다.
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
                learning_state_directive=directive,
                **common,
            )

        chosen_id, chosen_difficulty, _b = candidate_rows[best]
        # REC-11: candidates[] 관측 — `select_weighted_item`과 *같은* 점수 공식을 재사용(새 쿼리 0).
        scores = [
            (pid, item_information(theta, item) * (weights[i] if weights is not None else 1.0))
            for i, ((pid, _d, _bb), item) in enumerate(zip(candidate_rows, items, strict=True))
        ]
        # 근거는 **선택이 끝난 뒤** 조립된다 — 이 호출이 위 선택에 영향을 줄 수 없는 위치이므로
        # 근거·목표 배선이 추천 결과를 바꾸지 않는다(acceptance ④의 구조적 보장).
        if applied_route is not None:
            # 집행 경로: 후보가 개념 C로 제한됐으므로 고른 문항의 대표 개념이 곧 C다 — 근거·목표를
            # 상태 머신 결정에서 채워도 문항과 어긋나지 않는다(판정문 §5).
            reason = await collect_remediation_reason(
                session, learner_id=user_id, route=applied_route
            )
            target = applied_route.concept_id
        else:
            reason = await collect_recommendation_reason(
                session, learner_id=user_id, problem_id=chosen_id
            )
            target = await resolve_target_concept(
                session, reason=reason, learner_state=learner_state, budget=self._graph_budget
            )
        return NextProblemOutcome(
            problem_id=chosen_id,
            reason=reason,
            action=action_for(reason.type),
            target_concept=target,
            difficulty=float(chosen_difficulty) if chosen_difficulty is not None else None,
            candidate_zero_reason=None,
            candidate_scores=scores,
            learning_state_directive=directive,
            **common,
        )

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
