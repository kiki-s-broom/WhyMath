"""오답 → 교정 전략 체인(`l4/misconception/remediation_strategy.py`) 단위 테스트 (P3-06).

코퍼스를 읽지 않는다 — 합성 `distractor_map` 만으로 체인의 각 칸을 확인한다. 실 코퍼스에서 핵심
오개념 12개가 실제로 도는지는 `tests/backend/ops/test_phase3_remediation.py` 가 잰다.

지키는 것: 신뢰도 누적·감쇠는 Phase 2 규칙 그대로(여기서 새 규칙을 만들지 않는다) · 정답 회차는 감쇠뿐 ·
충돌(정답으로 보고했는데 오답 보기를 골랐다)은 가설을 건드리지 않는다 · 모르는 id 는 버려지되 사유가 남는다 ·
쉬운 문항·선수 개념을 못 찾으면 해소 실패로 표기한다.
"""

from __future__ import annotations

from collections.abc import Sequence

from whymath_backend.l2.recommendation_contract import ReasonType, RecommendationAction
from whymath_backend.l2.remediation_policy import MISCONCEPTION_REMEDIATION_FLOOR, EscalationRung
from whymath_backend.l4.misconception.attempt_hypothesis_policy import AttemptHypothesisAction
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.l4.misconception.models import InterventionPattern
from whymath_backend.l4.misconception.remediation_strategy import (
    ChainResult,
    RungResolvers,
    run_choice_chain,
)
from whymath_backend.schema.assessment_evidence import MisconceptionScan

_KEBAB = "power-rule-step-omitted"
_MAP = [
    {"choice_index": 0, "misconception_id": _KEBAB, "op_code": "demo-op"},
    {"choice_index": 3, "misconception_id": _KEBAB},
    {"choice_index": 1, "misconception_id": "M0674"},  # 카탈로그에 없는 raw M-id
]
_PID = "00000000-0000-0000-0000-000000000001"


def _pick(
    index: int | None,
    *,
    correct: bool = False,
    prior: Sequence = (),
    resolvers: RungResolvers | None = None,
    dmap: object = _MAP,
) -> ChainResult:
    return run_choice_chain(
        problem_id=_PID,
        distractor_map=dmap,  # type: ignore[arg-type]
        selected_choice_index=index,
        is_correct=correct,
        prior=prior,
        resolvers=resolvers,
    )


class _Fake:
    def easier_problem_ids(self, problem_id: str, misconception_id: str) -> Sequence[str]:
        return (f"easier-of-{misconception_id}",)

    def prerequisite_atoms(self, problem_id: str) -> Sequence[str]:
        return ("atom-a", "atom-b")


class _Empty:
    def easier_problem_ids(self, problem_id: str, misconception_id: str) -> Sequence[str]:
        return ()

    def prerequisite_atoms(self, problem_id: str) -> Sequence[str]:
        return ()


class TestSingleAttempt:
    def test_wrong_pick_runs_the_whole_chain(self) -> None:
        r = _pick(0)
        assert r.scan is MisconceptionScan.RAN_WITH_CANDIDATES
        assert r.hypothesis_action is AttemptHypothesisAction.APPLY
        assert r.signature is not None
        assert (r.signature.problem_id, r.signature.choice_index) == (_PID, 0)
        assert r.signature.misconception_id == _KEBAB and r.signature.op_code == "demo-op"
        assert r.candidate_ids == (_KEBAB,) and r.candidate_confidence == 0.8
        s = r.strategy
        assert s is not None and s.misconception_id == _KEBAB
        assert s.remediation_eligible and s.reason_type is ReasonType.MISCONCEPTION_REMEDIATION
        assert s.action is RecommendationAction.PRACTICE_CURRENT
        assert s.escalation_rung is EscalationRung.NONE  # 1회는 사다리 첫 칸(2회) 미만

    def test_first_pick_confidence_sits_on_the_reverse_reasoning_side_of_the_boundary(self) -> None:
        """선지 신뢰도 0.8 은 반례 임계(>0.8)를 넘지 못한다 — 첫 회엔 '거꾸로 사고'다(기존 동작의 기록)."""
        assert _pick(0).strategy is not None
        assert _pick(0).strategy.intervention_pattern is InterventionPattern.REVERSE_REASONING  # type: ignore[union-attr]

    def test_op_code_is_none_when_the_entry_has_none(self) -> None:
        r = _pick(3)
        assert r.signature is not None and r.signature.op_code is None

    def test_pedagogy_strategy_comes_from_the_real_selector_not_a_new_edge(self) -> None:
        from whymath_backend.l4.pedagogy.runtime_selector import StudentSignals, select

        expected = select(
            StudentSignals(misconception_ids=(_KEBAB,), last_attempt_correct=False)
        ).value
        assert _pick(0).strategy is not None
        assert _pick(0).strategy.pedagogy_strategy == expected  # type: ignore[union-attr]

    def test_deterministic(self) -> None:
        assert _pick(0) == _pick(0)

    def test_corrective_anchor_is_the_catalog_counterexample(self) -> None:
        r1 = _pick(0)
        r2 = _pick(0, prior=r1.hypotheses)
        assert r2.strategy is not None
        assert r2.strategy.escalation_rung is EscalationRung.CORRECTIVE_EXPLANATION
        assert r2.strategy.rung_action.anchor == CATALOG_BY_ID[_KEBAB].counterexample
        assert r2.strategy.rung_action.resolved


class TestAccumulationAndDecay:
    def test_repeated_wrong_picks_accumulate_and_climb_the_ladder(self) -> None:
        prior: tuple = ()
        rungs, counts, confs = [], [], []
        for _ in range(4):
            r = _pick(0, prior=prior, resolvers=_Fake())
            assert r.strategy is not None
            rungs.append(r.strategy.escalation_rung)
            counts.append(r.strategy.evidence_count)
            confs.append(r.strategy.confidence)
            prior = r.hypotheses
        assert counts == [1, 2, 3, 4]
        assert confs == sorted(confs) and confs[-1] > confs[0]  # 누적은 단조 증가
        assert rungs == [
            EscalationRung.NONE,
            EscalationRung.CORRECTIVE_EXPLANATION,
            EscalationRung.EASIER_PROBLEM,
            EscalationRung.PREREQUISITE_CONCEPT,
        ]

    def test_correct_pick_only_decays_and_builds_no_strategy(self) -> None:
        prior = _pick(0).hypotheses
        prior = _pick(0, prior=prior).hypotheses
        r = _pick(2, correct=True, prior=prior)  # 매핑에 없는 정답 보기
        assert r.hypothesis_action is AttemptHypothesisAction.DECAY_ONLY
        assert r.scan is MisconceptionScan.RAN_NO_CANDIDATE and r.strategy is None
        assert r.hypotheses[0].confidence < prior[0].confidence
        assert r.hypotheses[0].evidence_count == prior[0].evidence_count  # 증거는 늘지 않는다

    def test_conflict_leaves_hypotheses_untouched(self) -> None:
        """정답으로 보고했는데 오답 보기를 골랐다 — 감쇠도 강화도 없다(보고와 관측의 충돌)."""
        prior = _pick(0).hypotheses
        r = _pick(0, correct=True, prior=prior)
        assert r.hypothesis_action is AttemptHypothesisAction.HOLD_CONFLICT
        assert r.hypotheses == tuple(prior)
        assert r.strategy is None


class TestHonestFailure:
    def test_unknown_id_is_dropped_with_a_reason_and_no_strategy(self) -> None:
        prior = _pick(0).hypotheses
        r = _pick(1, prior=prior)
        assert r.signature is not None and r.signature.misconception_id == "M0674"
        assert r.dropped_reason == "unknown_misconception"
        assert (
            r.scan is MisconceptionScan.RAN_NO_CANDIDATE
        )  # 후보가 없으면 '후보 있음'이라 말하지 않는다
        assert r.candidate_ids == () and r.strategy is None
        assert r.hypotheses[0].confidence < prior[0].confidence  # 오답이지만 후보가 없으니 1턴 감쇠

    def test_missing_inputs_mean_not_run_not_zero_candidates(self) -> None:
        for r in (_pick(None), _pick(0, dmap=None), _pick(0, dmap=[])):
            assert r.scan is MisconceptionScan.NOT_RUN
            assert r.hypothesis_action is AttemptHypothesisAction.NONE
            assert r.signature is None and r.strategy is None

    def test_a_bool_is_not_a_choice_index(self) -> None:
        """True 가 조용히 1번 보기로 읽히면 안 된다."""
        r = _pick(True)  # type: ignore[arg-type]
        assert r.signature is None and r.candidate_ids == ()

    def test_unresolvable_rungs_are_marked_unresolved(self) -> None:
        prior: tuple = ()
        last: ChainResult | None = None
        for _ in range(4):
            last = _pick(0, prior=prior, resolvers=_Empty())
            prior = last.hypotheses
        assert last is not None and last.strategy is not None
        assert last.strategy.escalation_rung is EscalationRung.PREREQUISITE_CONCEPT
        assert (
            last.strategy.rung_action.resolved is False and last.strategy.rung_action.targets == ()
        )

    def test_without_resolvers_the_easier_rung_is_unresolved(self) -> None:
        prior: tuple = ()
        for _ in range(3):
            r = _pick(0, prior=prior)
            prior = r.hypotheses
        assert (
            r.strategy is not None and r.strategy.escalation_rung is EscalationRung.EASIER_PROBLEM
        )
        assert r.strategy.rung_action.resolved is False

    def test_resolver_targets_are_carried_through(self) -> None:
        prior: tuple = ()
        for _ in range(3):
            r = _pick(0, prior=prior, resolvers=_Fake())
            prior = r.hypotheses
        assert r.strategy is not None
        assert r.strategy.rung_action.targets == (f"easier-of-{_KEBAB}",)


def test_floor_constant_is_the_policy_tables_value() -> None:
    """체인이 하한을 자기 리터럴로 들고 있지 않다 — P-09 표의 값 그대로다."""
    assert MISCONCEPTION_REMEDIATION_FLOOR == 0.7
