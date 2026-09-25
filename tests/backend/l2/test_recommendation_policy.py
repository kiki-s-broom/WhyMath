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
`scripts/analysis/mutate_recommendation_policy_guards.py`가 뮤테이션 24종으로 검증한다
(EOS-124 정렬 계약 축 D 11종 포함 · 2026-09-25 실측 24/24 검출)
(CLAUDE.md "보호 장치를 실패 주입 없이 '보호 있음'으로 선언 금지").
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from whymath_backend.api._next_problem_policy import SuneungRecommendationPolicy
from whymath_backend.l2 import recommendation_policy as policy_module
from whymath_backend.l2.learner_state import LearnerState
from whymath_backend.l2.next_problem_selection import AttemptHistoryState, SuccessorRow
from whymath_backend.l2.prerequisite_recommendation import PrerequisiteRow
from whymath_backend.l2.recommendation_contract import (
    IntentAlignmentError,
    LearningContext,
    ReasonBasis,
    ReasonType,
    Recommendation,
    RecommendationAction,
    RecommendationReason,
    action_for,
    build_reason,
    check_intent_alignment,
    demote_to_current_concept,
    no_candidate_reason,
)
from whymath_backend.l2.recommendation_policy import (
    DEFAULT_GRAPH_BUDGET,
    CatRecommendationPolicy,
    ConceptGraphBudget,
    IntentResolution,
    NextProblemOutcome,
    NextProblemPolicy,
    resolve_policy_intent,
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
        # EOS-124: 정렬 재선택으로 선택 규칙이 바뀌었으므로 식별자도 바뀐다(REC-11 규약).
        assert CatRecommendationPolicy.policy_version == "cat_v2"
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


# ──────────────────────────────────────────────────────────────────────────
# ⑥ EOS-124 — 정책 축(action·target)과 선택 축(problem_id)의 정렬
# ──────────────────────────────────────────────────────────────────────────
# 실측 사고(2026-09-19 · main 433ec9ea): 숙달 0.98 개념 문항에 advance_next가 붙고(전진을 선언하며
# 제자리), 선수 숙달 1.0인데 원래 개념 문항에 practice_prerequisite가 붙었다(설명이 낡음). 아래
# 테스트들은 ①구조 계약(순수) ②생성 시점 집행 ③의도 판정 갈래 ④정책 오케스트레이션을 따로 잰다.

_ANCHOR = uuid.uuid4()
_NEXT_A = uuid.uuid4()
_NEXT_B = uuid.uuid4()
_BLOCKED = uuid.uuid4()
_PID = uuid.uuid4()


def _succ(concept_id: uuid.UUID, code: str) -> SuccessorRow:
    return SuccessorRow(concept_id=concept_id, concept_code=code)


class TestIntentAlignmentContract:
    """`check_intent_alignment` — 설명이 전달 콘텐츠와 어긋나는 모든 구조를 거부하는가."""

    def _check(self, **kw: Any) -> None:
        base: dict[str, Any] = {
            "problem_id": _PID,
            "action": RecommendationAction.PRACTICE_CURRENT,
            "reason_concept_id": _ANCHOR,
            "target_concept": _ANCHOR,
            "delivered_concept": _ANCHOR,
        }
        base.update(kw)
        check_intent_alignment(**base)

    def test_aligned_shapes_pass(self) -> None:
        self._check()  # 연습 — 앵커 = 목표 = 전달
        self._check(action=RecommendationAction.DIAGNOSE)
        self._check(  # 전진 — 근거는 앵커, 목표·전달은 다음 개념
            action=RecommendationAction.ADVANCE_NEXT,
            target_concept=_NEXT_A,
            delivered_concept=_NEXT_A,
        )
        self._check(  # 미매핑 — 셋 다 None
            reason_concept_id=None, target_concept=None, delivered_concept=None
        )
        self._check(
            problem_id=None,
            action=RecommendationAction.NONE,
            reason_concept_id=None,
            target_concept=None,
            delivered_concept=None,
        )

    def test_persona_a_shape_is_rejected(self) -> None:
        """EOS-124 (가) 그대로 — 전진을 선언하면서 목표·문항이 앵커(현재 개념)다."""
        with pytest.raises(IntentAlignmentError, match="R3"):
            self._check(action=RecommendationAction.ADVANCE_NEXT)

    def test_persona_b_shape_is_rejected(self) -> None:
        """EOS-124 (나) 그대로 — 받은 문항은 원래 개념인데 목표는 선수 개념이다."""
        with pytest.raises(IntentAlignmentError, match="R2"):
            self._check(
                action=RecommendationAction.PRACTICE_PREREQUISITE,
                target_concept=_PREREQ_A,
                delivered_concept=_ANCHOR,
            )

    def test_non_relational_action_must_stay_on_the_anchor(self) -> None:
        with pytest.raises(IntentAlignmentError, match="R4"):
            self._check(target_concept=_NEXT_A, delivered_concept=_NEXT_A)

    def test_relational_action_without_an_anchor_is_rejected(self) -> None:
        with pytest.raises(IntentAlignmentError, match="R3"):
            self._check(
                action=RecommendationAction.ADVANCE_NEXT,
                reason_concept_id=None,
                target_concept=_NEXT_A,
                delivered_concept=_NEXT_A,
            )

    def test_absent_recommendation_cannot_carry_a_target(self) -> None:
        with pytest.raises(IntentAlignmentError, match="R1"):
            self._check(problem_id=None, action=RecommendationAction.NONE, delivered_concept=None)


class TestHonestDemotion:
    def test_demotion_changes_only_the_type(self) -> None:
        """강등은 행위를 콘텐츠에 맞추는 것이지 측정을 고치는 것이 아니다 — 숙달은 그대로."""
        original = build_reason(concept_id=_ANCHOR, mastery=0.12, confidence=0.4)
        demoted = demote_to_current_concept(original)
        assert demoted.type is ReasonType.CURRENT_CONCEPT
        assert (demoted.concept_id, demoted.mastery, demoted.confidence, demoted.basis) == (
            original.concept_id,
            original.mastery,
            original.confidence,
            original.basis,
        )

    @pytest.mark.parametrize(
        "reason",
        [
            build_reason(concept_id=_ANCHOR, mastery=None, confidence=None),  # 콜드스타트
            build_reason(concept_id=None, mastery=None, confidence=None),  # 미매핑
            no_candidate_reason(),
        ],
    )
    def test_unmeasured_reasons_cannot_be_demoted(self, reason: RecommendationReason) -> None:
        """측정 없는 근거는 관계 행위를 낳지 않는다 — 들어오면 호출부 분기 결함이다(조용히 통과 금지)."""
        with pytest.raises(ValueError, match="실측 근거만"):
            demote_to_current_concept(reason)


class TestOutcomeEnforcesAlignment:
    """집행 지점 — 정렬을 선언한 산출은 어긋난 채로 **만들어지지 않는다**."""

    def _outcome(self, **kw: Any) -> NextProblemOutcome:
        base: dict[str, Any] = {
            "problem_id": _PID,
            "reason": build_reason(concept_id=_ANCHOR, mastery=0.9, confidence=0.5),
            "target_concept": _ANCHOR,
            "delivered_concept": _ANCHOR,
            "intent_resolution": IntentResolution.SERVED,
            "theta": 0.0,
        }
        base.update(kw)
        return NextProblemOutcome(**base)

    def test_declared_misalignment_cannot_be_constructed(self) -> None:
        """숙달 0.9 → advance_next인데 목표·문항이 앵커 — EOS-124 (가)의 산출 모양."""
        with pytest.raises(ValidationError, match="R3"):
            self._outcome()

    def test_aligned_outcome_is_constructed(self) -> None:
        outcome = self._outcome(target_concept=_NEXT_A, delivered_concept=_NEXT_A)
        assert outcome.action is RecommendationAction.ADVANCE_NEXT
        assert outcome.target_concept == _NEXT_A

    def test_policies_that_do_not_declare_alignment_are_not_checked(self) -> None:
        """수능 정책은 아직 정렬하지 않는다 — 검증을 걸면 그 경로가 500으로 죽는다.

        정렬하지 않는다는 사실은 `intent_resolution=None`으로 응답에 드러난다(정직 표기).
        이 면제가 사라지면(검증을 무조건 걸면) 이 테스트가 RED가 된다.
        """
        outcome = self._outcome(intent_resolution=None)
        assert outcome.intent_resolution is None


class _Fakes:
    """정책 의도 판정이 부르는 그래프·근거 조회 대역 — 호출 인자를 캡처한다."""

    def __init__(
        self,
        *,
        prereqs: list[PrerequisiteRow] | None = None,
        successors: list[Any] | None = None,
        concept_reasons: dict[uuid.UUID, RecommendationReason] | None = None,
        hang: bool = False,
    ) -> None:
        self.prereqs = prereqs or []
        self.successors = successors or []
        self.concept_reasons = concept_reasons or {}
        self.hang = hang
        self.prereq_calls: list[dict[str, Any]] = []
        self.successor_calls: list[dict[str, Any]] = []

    async def fetch_prerequisites(
        self, _session: object, concept_id: uuid.UUID, *, max_depth: int = 1
    ) -> list[PrerequisiteRow]:
        self.prereq_calls.append({"concept_id": concept_id, "max_depth": max_depth})
        if self.hang:
            await asyncio.sleep(_SpyFetch.HANG_SECONDS)
        return self.prereqs

    async def load_direct_successors(
        self, _session: object, concept_id: uuid.UUID, *, max_nodes: int
    ) -> list[Any]:
        self.successor_calls.append({"concept_id": concept_id, "max_nodes": max_nodes})
        if self.hang:
            await asyncio.sleep(_SpyFetch.HANG_SECONDS)
        return self.successors

    async def collect_concept_reason(
        self, _session: object, *, learner_id: uuid.UUID, concept_id: uuid.UUID
    ) -> RecommendationReason:
        return self.concept_reasons[concept_id]


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> Any:
    def _install(**kw: Any) -> _Fakes:
        f = _Fakes(**kw)
        monkeypatch.setattr(policy_module, "fetch_prerequisites", f.fetch_prerequisites)
        monkeypatch.setattr(policy_module, "load_direct_successors", f.load_direct_successors)
        monkeypatch.setattr(policy_module, "collect_concept_reason", f.collect_concept_reason)
        return f

    return _install


async def _intent(
    reason: RecommendationReason,
    mastery: dict[str, float] | None = None,
    budget: ConceptGraphBudget = DEFAULT_GRAPH_BUDGET,
) -> Any:
    return await resolve_policy_intent(
        object(),  # type: ignore[arg-type]
        anchor_reason=reason,
        learner_state=_state(mastery),
        learner_id=uuid.uuid4(),
        budget=budget,
    )


class TestResolvePolicyIntent:
    @pytest.mark.parametrize(
        "reason",
        [
            build_reason(concept_id=_ANCHOR, mastery=0.55, confidence=0.5),  # 학습 구간
            build_reason(concept_id=_ANCHOR, mastery=None, confidence=None),  # 콜드스타트
            build_reason(concept_id=None, mastery=None, confidence=None),  # 미매핑
        ],
    )
    async def test_non_relational_bands_are_direct_and_read_no_graph(
        self, fakes: Any, reason: RecommendationReason
    ) -> None:
        f = fakes(prereqs=[_row(_PREREQ_A, "UC-A")], successors=[_succ(_NEXT_A, "UC-N")])
        intent = await _intent(reason, {"UC-A": 0.1})
        assert intent.resolution is IntentResolution.DIRECT
        assert intent.reason == reason
        assert intent.reselect_groups == ()
        assert f.prereq_calls == [] and f.successor_calls == []

    async def test_weak_prerequisites_become_reselection_targets_weakest_first(
        self, fakes: Any
    ) -> None:
        """(가) 측정된 약한 선수 — 가장 약한 것부터 한 개념씩 묶음이 된다."""
        f = fakes(prereqs=[_row(_PREREQ_A, "UC-A"), _row(_PREREQ_B, "UC-B", depth=2)])
        anchor = build_reason(concept_id=_ANCHOR, mastery=0.1, confidence=0.5)
        intent = await _intent(anchor, {"UC-A": 0.6, "UC-B": 0.2})
        assert intent.resolution is IntentResolution.SERVED
        assert intent.reason == anchor  # 근거는 막힌 앵커
        assert intent.reselect_groups == ((_PREREQ_B,), (_PREREQ_A,))
        assert f.prereq_calls[0]["max_depth"] == DEFAULT_GRAPH_BUDGET.max_depth
        assert f.successor_calls == []  # (가)가 서면 (나)를 볼 이유가 없다

    async def test_mastered_prerequisite_is_not_called_blocked(self, fakes: Any) -> None:
        """EOS-124 (나)의 근원 — 선수가 1.0이면 '막힌 선수'가 아니다(종전엔 최저라서 골랐다)."""
        fakes(prereqs=[_row(_PREREQ_A, "UC-A")])
        anchor = build_reason(concept_id=_ANCHOR, mastery=0.12, confidence=0.5)
        intent = await _intent(anchor, {"UC-A": 1.0})
        assert intent.resolution is IntentResolution.REFUTED  # 측정이 반증 — "근거 없음"과 다르다
        assert intent.reason.type is ReasonType.CURRENT_CONCEPT
        assert intent.reason.mastery == 0.12  # 숫자는 그대로
        assert intent.reselect_groups == ()

    async def test_weak_cut_is_the_weak_concept_ceiling_exactly(self, fakes: Any) -> None:
        """경계 — 0.7은 약점이 아니다(`WEAK_CONCEPT_MASTERY_CEILING` 이상이면 약점 아님)."""
        fakes(prereqs=[_row(_PREREQ_A, "UC-A"), _row(_PREREQ_B, "UC-B")])
        anchor = build_reason(concept_id=_ANCHOR, mastery=0.1, confidence=0.5)
        at_cut = await _intent(anchor, {"UC-A": 0.7, "UC-B": 0.9})
        assert at_cut.resolution is IntentResolution.REFUTED
        just_below = await _intent(anchor, {"UC-A": 0.69, "UC-B": 0.9})
        assert just_below.reselect_groups == ((_PREREQ_A,),)

    async def test_unmeasured_prerequisites_are_unsupported_not_refuted(self, fakes: Any) -> None:
        """모른다 ≠ 아니다 — 선수가 미측정이면 반증이 아니라 근거 없음이다."""
        fakes(prereqs=[_row(_PREREQ_A, "UC-A")])
        anchor = build_reason(concept_id=_ANCHOR, mastery=0.1, confidence=0.5)
        intent = await _intent(anchor, {})
        assert intent.resolution is IntentResolution.UNSUPPORTED
        assert intent.reason.type is ReasonType.CURRENT_CONCEPT

    async def test_anchor_that_is_the_prerequisite_of_a_blocked_concept(self, fakes: Any) -> None:
        """(나) 앵커 자신이 막힌 후행의 선수 — 근거는 후행으로 옮기고 재선택은 하지 않는다.

        페르소나 B ⑤의 정확한 이유다: 1차 선택이 이미 선수 문항을 골랐고, 그 이유는 "원래 개념이
        막혔다"이다. 종전에는 선수 문항 자신의 숙달로 근거를 댔고 목표가 우연히 맞았다.
        """
        blocked_reason = build_reason(concept_id=_BLOCKED, mastery=0.12, confidence=0.6)
        f = fakes(
            prereqs=[],
            successors=[_succ(_BLOCKED, "UC-W"), _succ(_NEXT_A, "UC-OK")],
            concept_reasons={_BLOCKED: blocked_reason},
        )
        anchor = build_reason(concept_id=_ANCHOR, mastery=0.15, confidence=0.5)
        intent = await _intent(anchor, {"UC-W": 0.12, "UC-OK": 0.8})
        assert intent.resolution is IntentResolution.SERVED
        assert intent.reason == blocked_reason
        assert intent.reselect_groups == ()  # 전달될 앵커 문항이 곧 목표다
        assert f.successor_calls[0]["max_nodes"] == DEFAULT_GRAPH_BUDGET.max_nodes

    async def test_successor_in_the_learning_band_is_not_blocked(self, fakes: Any) -> None:
        """막힌 후행은 선수 구간(<0.4)이어야 한다 — 학습 구간 후행 때문에 선수 설명을 붙이지 않는다."""
        fakes(successors=[_succ(_BLOCKED, "UC-W")])
        anchor = build_reason(concept_id=_ANCHOR, mastery=0.15, confidence=0.5)
        intent = await _intent(anchor, {"UC-W": 0.4})
        assert intent.resolution is IntentResolution.UNSUPPORTED

    async def test_disagreeing_sources_fall_back_and_log(
        self, fakes: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        """학습자 상태와 최신 숙달이 구간을 다르게 말하면 한쪽에 맞춰 근거를 지어내지 않는다."""
        fakes(
            successors=[_succ(_BLOCKED, "UC-W")],
            concept_reasons={
                _BLOCKED: build_reason(concept_id=_BLOCKED, mastery=0.55, confidence=0.6)
            },
        )
        anchor = build_reason(concept_id=_ANCHOR, mastery=0.15, confidence=0.5)
        with caplog.at_level("WARNING"):
            intent = await _intent(anchor, {"UC-W": 0.1})
        assert intent.resolution is IntentResolution.UNSUPPORTED
        assert "불일치" in caplog.text

    async def test_advance_targets_every_open_successor_as_one_group(self, fakes: Any) -> None:
        """전진 — 미측정·학습 구간 후행은 열려 있고, 이미 숙달한 후행은 목표가 아니다."""
        mastered = uuid.uuid4()
        fakes(
            successors=[
                _succ(_NEXT_A, "UC-N1"),
                _succ(mastered, "UC-DONE"),
                _succ(_NEXT_B, "UC-N2"),
            ]
        )
        anchor = build_reason(concept_id=_ANCHOR, mastery=0.98, confidence=0.7)
        intent = await _intent(anchor, {"UC-DONE": 0.95, "UC-N2": 0.7})
        assert intent.resolution is IntentResolution.SERVED
        assert intent.reason == anchor  # 전진의 근거는 숙달한 현재 개념
        assert intent.reselect_groups == ((_NEXT_A, _NEXT_B),)

    async def test_advance_with_every_successor_mastered_is_refuted(self, fakes: Any) -> None:
        fakes(successors=[_succ(_NEXT_A, "UC-N1")])
        anchor = build_reason(concept_id=_ANCHOR, mastery=0.98, confidence=0.7)
        intent = await _intent(anchor, {"UC-N1": 0.9})
        assert intent.resolution is IntentResolution.REFUTED
        assert intent.reason.type is ReasonType.CURRENT_CONCEPT

    async def test_advance_without_successors_is_unsupported(self, fakes: Any) -> None:
        fakes(successors=[])
        anchor = build_reason(concept_id=_ANCHOR, mastery=0.98, confidence=0.7)
        intent = await _intent(anchor, {})
        assert intent.resolution is IntentResolution.UNSUPPORTED

    @pytest.mark.parametrize("mastery", [0.1, 0.98])
    async def test_graph_timeout_demotes_and_names_the_exception(
        self, fakes: Any, caplog: pytest.LogCaptureFixture, mastery: float
    ) -> None:
        """시간 예산 초과는 추천을 실패시키지 않는다 — 강등하고 예외 타입명을 남긴다."""
        fakes(prereqs=[_row(_PREREQ_A, "UC-A")], successors=[_succ(_NEXT_A, "UC-N")], hang=True)
        anchor = build_reason(concept_id=_ANCHOR, mastery=mastery, confidence=0.5)
        with caplog.at_level("WARNING"):
            intent = await _intent(
                anchor, {"UC-A": 0.1}, budget=ConceptGraphBudget(timeout_seconds=0.01)
            )
        assert intent.resolution is IntentResolution.GRAPH_TIMEOUT
        assert intent.reason.type is ReasonType.CURRENT_CONCEPT
        assert "TimeoutError" in caplog.text

    async def test_node_budget_bounds_the_prerequisite_targets(self, fakes: Any) -> None:
        """예산(20) 밖 선수는 목표 후보가 되지 않는다 — 너비 폭발이 판정을 오염시키지 않는다."""
        rows = [_row(uuid.uuid4(), f"UC-{i}") for i in range(20)] + [_row(_PREREQ_B, "UC-FAR")]
        fakes(prereqs=rows)
        anchor = build_reason(concept_id=_ANCHOR, mastery=0.1, confidence=0.5)
        intent = await _intent(anchor, {"UC-FAR": 0.01})
        assert intent.resolution is IntentResolution.UNSUPPORTED


class TestCatPolicyAlignedSelection:
    """정책 오케스트레이션 — 1차 선택 → 의도 → 정렬 재선택 → 산출(DB 0 · 조회 전부 대역)."""

    @staticmethod
    def _install(
        monkeypatch: pytest.MonkeyPatch,
        *,
        pool: list[tuple[uuid.UUID, float, float | None]],
        anchor_reason: RecommendationReason,
        target_rows: list[tuple[uuid.UUID, float, float | None, uuid.UUID]],
        prereqs: list[PrerequisiteRow] | None = None,
        successors: list[Any] | None = None,
    ) -> dict[str, Any]:
        seen: dict[str, Any] = {"target_calls": []}

        async def _history(_s: object, _u: uuid.UUID) -> AttemptHistoryState:
            return AttemptHistoryState(
                attempted_ids={uuid.UUID(int=1)},
                theta=0.0,
                standard_error=None,
                measurement_sufficient=False,
                administered_count=0,
            )

        async def _pool(_s: object, _t: float, **_kw: Any) -> list[Any]:
            return pool

        async def _reason(_s: object, *, learner_id: uuid.UUID, problem_id: Any) -> Any:
            return anchor_reason if problem_id is not None else no_candidate_reason()

        async def _targets(_s: object, theta: float, **kw: Any) -> list[Any]:
            seen["target_calls"].append(kw)
            return target_rows

        f = _Fakes(prereqs=prereqs, successors=successors)
        monkeypatch.setattr(policy_module, "load_attempt_history_state", _history)
        monkeypatch.setattr(policy_module, "load_candidate_rows", _pool)
        monkeypatch.setattr(policy_module, "collect_recommendation_reason", _reason)
        monkeypatch.setattr(policy_module, "load_target_candidate_rows", _targets)
        monkeypatch.setattr(policy_module, "fetch_prerequisites", f.fetch_prerequisites)
        monkeypatch.setattr(policy_module, "load_direct_successors", f.load_direct_successors)
        return seen

    @staticmethod
    async def _run() -> NextProblemOutcome:
        policy = CatRecommendationPolicy(object())  # type: ignore[arg-type]
        return await policy(_state({"UC-A": 0.2, "UC-B": 0.1}), LearningContext())

    async def test_advance_reselects_the_next_concept_problem(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """페르소나 A ⑤의 모양 — 숙달 개념 문항이 1차 선택돼도 다음 개념 문항이 나간다."""
        cur_pid, next_pid = uuid.uuid4(), uuid.uuid4()
        anchor = build_reason(concept_id=_ANCHOR, mastery=0.98, confidence=0.7)
        seen = self._install(
            monkeypatch,
            pool=[(cur_pid, 3.0, 0.0)],
            anchor_reason=anchor,
            successors=[_succ(_NEXT_A, "UC-N")],
            target_rows=[(next_pid, 3.5, 0.5, _NEXT_A)],
        )
        outcome = await self._run()
        assert outcome.problem_id == next_pid
        assert outcome.action is RecommendationAction.ADVANCE_NEXT
        assert outcome.target_concept == _NEXT_A
        assert outcome.reason == anchor
        assert outcome.intent_resolution is IntentResolution.SERVED
        assert outcome.difficulty == 3.5
        # 소급 평가 재료는 *그 문항을 고른* 비교 집합이어야 한다(전달 문항이 들어 있다).
        assert [pid for pid, _ in outcome.candidate_scores] == [next_pid]
        # 재선택도 1차 선택과 같은 배제(미응답)를 받는다 — 이미 푼 문항을 다시 꺼내지 않는다.
        assert seen["target_calls"][0]["attempted_ids"] == {uuid.UUID(int=1)}
        assert seen["target_calls"][0]["concept_ids"] == [_NEXT_A]

    async def test_missing_target_problems_demote_honestly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """목표 개념에 문항이 없다 — 1차 선택을 내보내되 전진을 말하지 않는다."""
        cur_pid = uuid.uuid4()
        anchor = build_reason(concept_id=_ANCHOR, mastery=0.98, confidence=0.7)
        self._install(
            monkeypatch,
            pool=[(cur_pid, 3.0, 0.0)],
            anchor_reason=anchor,
            successors=[_succ(_NEXT_A, "UC-N")],
            target_rows=[],
        )
        outcome = await self._run()
        assert outcome.problem_id == cur_pid
        assert outcome.action is RecommendationAction.PRACTICE_CURRENT
        assert outcome.target_concept == _ANCHOR
        assert outcome.intent_resolution is IntentResolution.TARGET_UNAVAILABLE
        assert outcome.reason.mastery == 0.98

    async def test_prerequisite_groups_are_tried_in_weakness_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """가장 약한 선수에 문항이 없으면 다음 약한 선수로 — 아무 약한 선수로 뛰지 않는다."""
        cur_pid, pre_a_pid, other_pid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        anchor = build_reason(concept_id=_ANCHOR, mastery=0.1, confidence=0.5)
        self._install(
            monkeypatch,
            pool=[(cur_pid, 3.0, 0.0)],
            anchor_reason=anchor,
            # 학습자 상태: UC-B 0.1(가장 약함) · UC-A 0.2. 그런데 B에는 문항이 없다.
            prereqs=[_row(_PREREQ_A, "UC-A"), _row(_PREREQ_B, "UC-B")],
            # 목표가 아닌 개념의 행이 섞여 들어와도 묶음 밖이면 고르지 않는다.
            target_rows=[(other_pid, 3.0, 0.0, uuid.uuid4()), (pre_a_pid, 3.0, 0.0, _PREREQ_A)],
        )
        outcome = await self._run()
        assert outcome.problem_id == pre_a_pid
        assert outcome.action is RecommendationAction.PRACTICE_PREREQUISITE
        assert outcome.target_concept == _PREREQ_A
        assert outcome.reason == anchor
        assert outcome.intent_resolution is IntentResolution.SERVED

    async def test_direct_band_keeps_the_first_pass_problem(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cur_pid = uuid.uuid4()
        seen = self._install(
            monkeypatch,
            pool=[(cur_pid, 3.0, 0.0)],
            anchor_reason=build_reason(concept_id=_ANCHOR, mastery=0.55, confidence=0.5),
            target_rows=[(uuid.uuid4(), 3.0, 0.0, _NEXT_A)],
        )
        outcome = await self._run()
        assert outcome.problem_id == cur_pid
        assert outcome.intent_resolution is IntentResolution.DIRECT
        assert seen["target_calls"] == []  # 재선택 조회 자체가 없다

    async def test_empty_pool_reports_no_candidate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._install(
            monkeypatch,
            pool=[],
            anchor_reason=no_candidate_reason(),
            target_rows=[],
        )
        outcome = await self._run()
        assert outcome.problem_id is None
        assert outcome.intent_resolution is IntentResolution.NO_CANDIDATE
