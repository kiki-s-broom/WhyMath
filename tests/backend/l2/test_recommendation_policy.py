"""EOS-19 추천 정책 v1 — **근거 필수·행위 파생·그래프 예산** (hermetic·DB 0).

계획서 300 §8의 KPI 3은 *"reason 없이 생성된 추천 = 0"*이다. 그 0을 운영에서 세어 확인하는
것이 아니라 **구조적으로 만들 수 없게** 하는 것이 이 파일이 지키는 계약이다.

이 파일이 지키는 넷:

① **근거 없는 추천은 만들어지지 않는다** — `reason`이 필수 필드이므로 생성이 실패한다.
   추천이 없는 경우(`problem_id=None`)에도 이유는 있다("후보가 없었다"도 이유다).
② **행위는 근거에서 파생되고, 어긋난 조합은 거부된다** — `action`을 손으로 넣어 근거와
   다르게 만들 수 없다. 근거는 있는데 행위가 그 근거와 다른 추천도 같은 종류의 거짓말이다.
③ **개념 그래프 예산은 생성 시점에 강제된다** — depth ≤ 2 · nodes ≤ 20을 넘는 예산 객체는
   *존재할 수 없다*. 호출부의 선의에 맡기지 않는다(CLAUDE.md 구축 플레이북 하드 게이트).
④ **목표 개념은 측정된 선수에서만 나온다** — 측정 없는 선수를 "막혔다"고 부르면 근거 없음이
   근거로 위장된다.

**변별력 확인**: 이 파일의 가드들은 정상 입력에서 초록인 것으로 충분하다고 보지 않는다.
막으려는 상태를 실제로 주입해 RED가 나오는지는
`scripts/analysis/mutate_recommendation_policy_guards.py`가 뮤테이션 9종으로 검증한다
(CLAUDE.md "보호 장치를 실패 주입 없이 '보호 있음'으로 선언 금지").
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from whymath_backend.api._next_problem_policy import SuneungRecommendationPolicy
from whymath_backend.l2 import recommendation_policy as policy_module
from whymath_backend.l2.learner_state import LearnerState
from whymath_backend.l2.prerequisite_recommendation import PrerequisiteRow
from whymath_backend.l2.recommendation_contract import (
    LearningContext,
    ReasonBasis,
    ReasonType,
    Recommendation,
    RecommendationAction,
    RecommendationReason,
    action_for,
    build_reason,
    no_candidate_reason,
)
from whymath_backend.l2.recommendation_policy import (
    DEFAULT_GRAPH_BUDGET,
    CatRecommendationPolicy,
    ConceptGraphBudget,
    NextProblemOutcome,
    NextProblemPolicy,
    resolve_target_concept,
)

_CONCEPT = uuid.uuid4()
_PREREQ_A = uuid.uuid4()
_PREREQ_B = uuid.uuid4()


def _state(mastery: dict[str, float] | None = None) -> LearnerState:
    """숙달만 채운 최소 `LearnerState` — 이 파일이 재는 것은 목표 판정이지 조립이 아니다."""
    return LearnerState(
        student_id=str(uuid.uuid4()),
        timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        mastery=mastery or {},
        general_ability=None,
        domain_abilities={},
        active_misconceptions=[],
        recent_struggles=[],
        recent_successes=[],
        grade=None,
        goals={},
    )


def _row(concept_id: uuid.UUID, code: str, depth: int = 1) -> PrerequisiteRow:
    return PrerequisiteRow(
        concept_id=concept_id, concept_code=code, name_ko=None, edge_strength=None, depth=depth
    )


# ──────────────────────────────────────────────────────────────────────────
# ① 근거 없는 추천은 만들어지지 않는다 (KPI 3 — "reason 없이 생성된 추천 = 0")
# ──────────────────────────────────────────────────────────────────────────
class TestReasonIsStructurallyRequired:
    @pytest.mark.parametrize("model", [Recommendation, NextProblemOutcome])
    def test_reason_field_is_required_by_name(self, model: type[Recommendation]) -> None:
        """**필드 자체의 필수성**을 이름으로 단언한다 — 다른 필수 필드에 가려지지 않게.

        처음 이 클래스는 `pytest.raises(Exception)`만 걸었는데, 뮤테이션(`reason`을 옵셔널로)
        을 넣어 보니 **초록이었다**: `action`이 아직 필수라 생성이 그쪽 이유로 실패했고,
        광범위한 `raises`는 둘을 구별하지 못했다. 즉 "근거 없는 추천을 만들 수 없다"를
        지킨다고 믿었던 가드가 실은 다른 필드를 지키고 있었다(2026-09-18 실측 · 하네스
        M1 생존). 아래 단언은 그 혼동이 불가능하다.
        """
        assert model.model_fields["reason"].is_required() is True

    def test_recommendation_without_reason_names_reason_in_the_error(self) -> None:
        """실패 *이유*까지 본다 — 어떤 예외든 통과시키면 다른 필드의 실패를 오인한다."""
        with pytest.raises(Exception, match="reason"):
            Recommendation(problem_id=uuid.uuid4())  # type: ignore[call-arg]

    def test_outcome_without_reason_cannot_be_constructed_either(self) -> None:
        """정책이 실제로 돌려주는 타입에서도 같다 — 하위타입이 계약을 느슨하게 하지 않는다."""
        with pytest.raises(Exception, match="reason"):
            NextProblemOutcome(  # type: ignore[call-arg]
                problem_id=None, theta=0.0, policy_version="cat_v1"
            )

    def test_absent_recommendation_still_carries_a_reason(self) -> None:
        """추천의 부재도 이유를 가진다 — null 경로가 근거의 구멍이 되지 않는다."""
        rec = Recommendation(problem_id=None, reason=no_candidate_reason())
        assert rec.reason.type is ReasonType.NO_CANDIDATE
        assert rec.action is RecommendationAction.NONE

    def test_every_reason_type_has_an_action(self) -> None:
        """전사표 전수성 — 근거 종류가 늘고 행위 대응을 안 정하면 여기서 KeyError로 드러난다."""
        for reason_type in ReasonType:
            assert isinstance(action_for(reason_type), RecommendationAction)


# ──────────────────────────────────────────────────────────────────────────
# ② 행위는 근거에서 파생되고, 어긋난 조합은 거부된다
# ──────────────────────────────────────────────────────────────────────────
class TestActionFollowsReason:
    @pytest.mark.parametrize(
        ("mastery", "expected"),
        [
            (0.2, RecommendationAction.PRACTICE_PREREQUISITE),
            (0.5, RecommendationAction.PRACTICE_CURRENT),
            (0.9, RecommendationAction.ADVANCE_NEXT),
            (None, RecommendationAction.DIAGNOSE),
        ],
    )
    def test_action_is_derived_from_the_mastery_band(
        self, mastery: float | None, expected: RecommendationAction
    ) -> None:
        rec = Recommendation(
            problem_id=uuid.uuid4(),
            reason=build_reason(concept_id=_CONCEPT, mastery=mastery, confidence=0.5),
        )
        assert rec.action is expected

    def test_mismatched_action_is_rejected_at_construction(self) -> None:
        """근거는 '선수가 막혔다'인데 행위가 '다음으로 넘어가라'인 추천은 존재할 수 없다."""
        with pytest.raises(ValueError, match="갈라질 수 없습니다"):
            Recommendation(
                problem_id=uuid.uuid4(),
                reason=build_reason(concept_id=_CONCEPT, mastery=0.1, confidence=0.5),
                action=RecommendationAction.ADVANCE_NEXT,
            )

    def test_cold_start_is_a_diagnose_action_not_a_practice_one(self) -> None:
        """콜드스타트를 연습 행위로 적으면 *측정이 목적인 출제*가 학습으로 위장된다."""
        rec = Recommendation(
            problem_id=uuid.uuid4(),
            reason=RecommendationReason(
                type=ReasonType.UNMEASURED, confidence=0.0, basis=ReasonBasis.COLD_START
            ),
        )
        assert rec.action is RecommendationAction.DIAGNOSE


# ──────────────────────────────────────────────────────────────────────────
# ③ 개념 그래프 예산 — 천장은 생성 시점에 강제된다
# ──────────────────────────────────────────────────────────────────────────
class TestConceptGraphBudget:
    def test_ceilings_are_the_playbook_numbers(self) -> None:
        """CLAUDE.md "AI 연동 시" 하드 게이트의 수치 — 완화는 이 줄을 고쳐야 가능하다."""
        assert policy_module._DEPTH_CEILING == 2
        assert policy_module._NODES_CEILING == 20

    def test_default_budget_obeys_the_ceilings(self) -> None:
        assert DEFAULT_GRAPH_BUDGET.max_depth <= policy_module._DEPTH_CEILING
        assert DEFAULT_GRAPH_BUDGET.max_nodes <= policy_module._NODES_CEILING
        assert DEFAULT_GRAPH_BUDGET.timeout_seconds > 0

    @pytest.mark.parametrize("depth", [3, 5, 99])
    def test_depth_beyond_the_ceiling_cannot_be_constructed(self, depth: int) -> None:
        """예산 객체가 존재한다는 사실 자체가 유효성의 증거여야 한다."""
        with pytest.raises(ValueError, match="max_depth"):
            ConceptGraphBudget(max_depth=depth)

    @pytest.mark.parametrize("nodes", [21, 64, 1000])
    def test_node_count_beyond_the_ceiling_cannot_be_constructed(self, nodes: int) -> None:
        """`fetch_prerequisites`의 자체 상한(64)에 기대지 않는다 — 소유권이 다르다."""
        with pytest.raises(ValueError, match="max_nodes"):
            ConceptGraphBudget(max_nodes=nodes)

    @pytest.mark.parametrize("bad", [0, -1])
    def test_non_positive_budgets_are_rejected(self, bad: int) -> None:
        with pytest.raises(ValueError):
            ConceptGraphBudget(max_depth=bad)
        with pytest.raises(ValueError):
            ConceptGraphBudget(max_nodes=bad)
        with pytest.raises(ValueError, match="timeout_seconds"):
            ConceptGraphBudget(timeout_seconds=float(bad))

    def test_visited_set_removes_diamond_duplicates_before_the_node_budget(self) -> None:
        """DAG diamond에서 같은 노드를 여러 경로로 세면 예산이 *중복*으로 소진된다."""
        rows = [_row(_PREREQ_A, "UC-A"), _row(_PREREQ_A, "UC-A", depth=2), _row(_PREREQ_B, "UC-B")]
        capped = policy_module._apply_node_budget(rows, ConceptGraphBudget(max_nodes=2))
        assert [r.concept_id for r in capped] == [_PREREQ_A, _PREREQ_B]

    def test_node_budget_truncates_and_logs(self, caplog: pytest.LogCaptureFixture) -> None:
        """침묵 절단 금지 — 규모에 도달했다는 사실이 로그로 남아야 관측된다."""
        rows = [_row(uuid.uuid4(), f"UC-{i}") for i in range(5)]
        with caplog.at_level("WARNING"):
            capped = policy_module._apply_node_budget(rows, ConceptGraphBudget(max_nodes=2))
        assert len(capped) == 2
        assert "노드 예산 초과" in caplog.text


# ──────────────────────────────────────────────────────────────────────────
# ④ 목표 개념 — 측정된 선수에서만 나온다 · 그래프는 예산 안에서만 읽는다
# ──────────────────────────────────────────────────────────────────────────
class _SpyFetch:
    """`fetch_prerequisites` 대역 — **호출 인자를 캡처**해 예산이 실제로 전달됐는지 본다.

    소스를 읽고 "depth를 넘기는 것처럼 보인다"고 적는 대신 실제 호출을 관측한다
    (CLAUDE.md "가드가 *막는다*는 주장도 주입으로 검증한다"의 관측 축).
    """

    #: `hang=True`일 때 매다는 시간(초). 예산 타임아웃(0.01초)보다 **충분히 길되 짧다** —
    #: 정상 경로는 0.01초에 끊기고, 시간 예산을 없애는 뮤테이션이 들어가면 이 시간만큼 기다린
    #: 뒤 *다른 목표*를 돌려주어 곧바로 RED가 된다. 3600초 같은 값을 쓰면 뮤테이션 검증이
    #: 한 시간 매달린다(2026-09-18 실측 — 하네스가 그 상태로 중단됐고, 중단은 원복을 건너뛴다).
    HANG_SECONDS = 1.0

    def __init__(self, rows: list[PrerequisiteRow], *, hang: bool = False) -> None:
        self._rows = rows
        self._hang = hang
        self.calls: list[dict[str, Any]] = []

    async def __call__(
        self, _session: object, concept_id: uuid.UUID, *, max_depth: int = 1
    ) -> list[PrerequisiteRow]:
        self.calls.append({"concept_id": concept_id, "max_depth": max_depth})
        if self._hang:
            await asyncio.sleep(self.HANG_SECONDS)
        return self._rows


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> Any:
    def _install(rows: list[PrerequisiteRow], *, hang: bool = False) -> _SpyFetch:
        s = _SpyFetch(rows, hang=hang)
        monkeypatch.setattr(policy_module, "fetch_prerequisites", s)
        return s

    return _install


class TestResolveTargetConcept:
    async def test_prerequisite_gap_targets_the_weakest_measured_prerequisite(
        self, spy: Any
    ) -> None:
        """'선수를 연습하라'는 행위에 *어느* 선수인지가 없으면 실행할 수 없다."""
        s = spy([_row(_PREREQ_A, "UC-A"), _row(_PREREQ_B, "UC-B")])
        target = await resolve_target_concept(
            object(),  # type: ignore[arg-type]
            reason=build_reason(concept_id=_CONCEPT, mastery=0.1, confidence=0.5),
            learner_state=_state({"UC-A": 0.6, "UC-B": 0.2}),
        )
        assert target == _PREREQ_B  # 더 약한 쪽
        assert s.calls[0]["max_depth"] == DEFAULT_GRAPH_BUDGET.max_depth

    async def test_traversal_never_exceeds_the_depth_budget(self, spy: Any) -> None:
        """예산이 *전달되는지*를 본다 — 천장 테스트만으로는 미사용 예산을 못 잡는다."""
        s = spy([_row(_PREREQ_A, "UC-A")])
        await resolve_target_concept(
            object(),  # type: ignore[arg-type]
            reason=build_reason(concept_id=_CONCEPT, mastery=0.1, confidence=0.5),
            learner_state=_state({"UC-A": 0.3}),
        )
        assert s.calls, "선수 traversal이 아예 호출되지 않았다 — 예산 검사가 공허해진다"
        assert s.calls[0]["max_depth"] <= policy_module._DEPTH_CEILING

    async def test_unmeasured_prerequisites_are_not_called_blocked(self, spy: Any) -> None:
        """측정 없는 선수를 목표로 삼으면 근거 없음이 근거로 위장된다 — 문항 개념으로 폴백."""
        spy([_row(_PREREQ_A, "UC-A")])
        target = await resolve_target_concept(
            object(),  # type: ignore[arg-type]
            reason=build_reason(concept_id=_CONCEPT, mastery=0.1, confidence=0.5),
            learner_state=_state({}),  # 선수 숙달 이력 없음
        )
        assert target == _CONCEPT

    @pytest.mark.parametrize("mastery", [0.5, 0.9])
    async def test_non_prerequisite_bands_do_not_touch_the_graph(
        self, spy: Any, mastery: float
    ) -> None:
        """읽을 이유가 없는 조회를 "있으면 좋으니" 넣지 않는다(비용은 학생 대기시간이다)."""
        s = spy([_row(_PREREQ_A, "UC-A")])
        target = await resolve_target_concept(
            object(),  # type: ignore[arg-type]
            reason=build_reason(concept_id=_CONCEPT, mastery=mastery, confidence=0.5),
            learner_state=_state({"UC-A": 0.1}),
        )
        assert target == _CONCEPT
        assert s.calls == []

    async def test_unmapped_problem_has_no_target(self, spy: Any) -> None:
        """개념 매핑이 없으면 목표도 없다 — 없는 근거를 지어내지 않는다."""
        s = spy([])
        target = await resolve_target_concept(
            object(),  # type: ignore[arg-type]
            reason=build_reason(concept_id=None, mastery=None, confidence=None),
            learner_state=_state({"UC-A": 0.1}),
        )
        assert target is None
        assert s.calls == []

    async def test_timeout_falls_back_instead_of_failing_the_recommendation(
        self, spy: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        """근거를 풍부하게 하는 부가 조회 때문에 학생이 문항을 못 받는 것은 우선순위가 거꾸로다."""
        spy([_row(_PREREQ_A, "UC-A")], hang=True)
        with caplog.at_level("WARNING"):
            target = await resolve_target_concept(
                object(),  # type: ignore[arg-type]
                reason=build_reason(concept_id=_CONCEPT, mastery=0.1, confidence=0.5),
                learner_state=_state({"UC-A": 0.1}),
                budget=ConceptGraphBudget(timeout_seconds=0.01),
            )
        assert target == _CONCEPT
        # 침묵 실패 금지 — 예외 타입명이 로그에 남아야 8가지 실패가 같은 글자로 보이지 않는다.
        assert "TimeoutError" in caplog.text

    async def test_node_budget_bounds_what_the_target_search_sees(self, spy: Any) -> None:
        """예산 밖 선수는 목표 후보가 되지 않는다 — 너비 폭발이 판정을 오염시키지 않는다."""
        far = uuid.uuid4()
        rows = [_row(uuid.uuid4(), f"UC-{i}") for i in range(20)] + [_row(far, "UC-FAR")]
        spy(rows)
        target = await resolve_target_concept(
            object(),  # type: ignore[arg-type]
            reason=build_reason(concept_id=_CONCEPT, mastery=0.1, confidence=0.5),
            # 예산(20) 밖 21번째 선수만 측정이 있다 → 잘렸으므로 폴백이어야 한다.
            learner_state=_state({"UC-FAR": 0.01}),
        )
        assert target == _CONCEPT


# ──────────────────────────────────────────────────────────────────────────
# ⑤ Protocol 적합 — EOS-14의 동결이 이 구현체를 실제로 제약하는가
# ──────────────────────────────────────────────────────────────────────────
class TestPolicyConformance:
    def test_both_policies_satisfy_the_next_problem_policy_shape(self) -> None:
        """핸들러가 `NextProblemPolicy`로 받는 두 구현체가 같은 모양인지 — 런타임 확인.

        정적 적합(그리고 그것이 `RecommendationPolicy` 계약을 만족한다는 것)은
        `recommendation_policy._contract_conformance`가 `mypy --strict`로 판정한다.
        """
        for cls in (CatRecommendationPolicy, SuneungRecommendationPolicy):
            call = cls.__call__
            params = list(__import__("inspect").signature(call).parameters)
            assert params == ["self", "learner_state", "learning_context"], cls.__name__
            assert asyncio.iscoroutinefunction(call), cls.__name__

    def test_policy_version_is_declared_by_the_policy_not_the_handler(self) -> None:
        """소급 평가는 "어느 정책이 냈는가"를 알아야 한다 — 핸들러가 붙이면 정책과 갈라진다."""
        assert CatRecommendationPolicy.policy_version == "cat_v1"
        assert SuneungRecommendationPolicy.policy_version

    def test_learning_context_carries_the_request_axes(self) -> None:
        """핸들러의 쿼리 파라미터가 계약 타입으로 옮겨졌는가(전송 관심사 혼입 없이)."""
        ctx = LearningContext(
            purpose="learning", mode="suneung", persona="A_일반고고3", prioritize_weak_concepts=True
        )
        assert (ctx.purpose, ctx.mode, ctx.prioritize_weak_concepts) == (
            "learning",
            "suneung",
            True,
        )

    def test_outcome_is_a_recommendation(self) -> None:
        """관측 메타를 실었다고 계약에서 벗어나면 정책 교체가 불가능해진다."""
        assert issubclass(NextProblemOutcome, Recommendation)
        outcome = NextProblemOutcome(
            problem_id=None, reason=no_candidate_reason(), theta=0.0, policy_version="cat_v1"
        )
        assert isinstance(outcome, Recommendation)
        assert outcome.action is RecommendationAction.NONE

    def test_next_problem_policy_is_a_protocol(self) -> None:
        assert getattr(NextProblemPolicy, "_is_protocol", False)
