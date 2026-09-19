"""오개념 개입 결정트리·프롬프트 어셈블리 단위테스트 — doc L75-79 정본."""

from __future__ import annotations

import random

from whymath_backend.l2.remediation_policy import EscalationRung
from whymath_backend.l4.misconception import (
    CATALOG_BY_ID,
    InterventionPattern,
    MisconceptionMatch,
    select_intervention,
    select_intervention_from_hypotheses,
)
from whymath_backend.l4.misconception.hypothesis import MisconceptionHypothesis


def _match(
    confidence: float, misconception_id: str = "distribution-over-power"
) -> MisconceptionMatch:
    m = CATALOG_BY_ID[misconception_id]
    return MisconceptionMatch(misconception=m, confidence=confidence)


def _hyp(
    confidence: float,
    misconception_id: str = "distribution-over-power",
    evidence_count: int = 1,
) -> MisconceptionHypothesis:
    return MisconceptionHypothesis(
        misconception_id=misconception_id,
        confidence=confidence,
        turns_since_evidence=0,
        evidence_count=evidence_count,
    )


class TestDecisionTree:
    def test_high_confidence_picks_counterexample(self) -> None:
        decision = select_intervention(_match(0.9))
        assert decision is not None
        assert decision.pattern is InterventionPattern.COUNTEREXAMPLE

    def test_mid_confidence_picks_reverse(self) -> None:
        # 0.5 ≤ conf ≤ 0.8
        for conf in (0.5, 0.65, 0.8):
            decision = select_intervention(_match(conf))
            assert decision is not None
            assert decision.pattern is InterventionPattern.REVERSE_REASONING, conf

    def test_low_confidence_holds(self) -> None:
        # < 0.5 → 진단 보류(None)
        for conf in (0.0, 0.3, 0.49):
            assert select_intervention(_match(conf)) is None, conf

    def test_boundary_just_above_high(self) -> None:
        # 0.8은 mid(reverse), 0.81은 high(counter)
        assert select_intervention(_match(0.8)).pattern is InterventionPattern.REVERSE_REASONING  # type: ignore[union-attr]
        assert select_intervention(_match(0.81)).pattern is InterventionPattern.COUNTEREXAMPLE  # type: ignore[union-attr]


class TestPromptAssembly:
    def test_counterexample_contains_assumption_and_case(self) -> None:
        decision = select_intervention(_match(0.95, "distribution-over-power"))
        assert decision is not None
        # 학생 가정·반례 둘 다 프롬프트에 등장
        assert "(a+b)² = a² + b²" in decision.prompt
        assert "a=1, b=1" in decision.prompt
        # 자각 유도형 어미("어떻게 돼?") 확인
        assert decision.prompt.endswith("어떻게 돼?")
        assert decision.misconception_id == "distribution-over-power"

    def test_reverse_prompt_template_correct(self) -> None:
        decision = select_intervention(_match(0.6, "sign-flip-in-inequality"))
        assert decision is not None
        # 거꾸로 사고 정본 어미
        assert "거꾸로 확인" in decision.prompt


class TestInterventionFromHypotheses:
    """결선 — 활성 가설 세트 → select_focus → 카탈로그 해소 → 결정 트리(누적 신뢰도)."""

    def test_empty_set_holds(self) -> None:
        """빈 가설 세트 → None(개입 보류)."""
        assert select_intervention_from_hypotheses([]) is None

    def test_top_hypothesis_drives_decision(self) -> None:
        """rng=None → 최상위 가설(활용)의 신뢰도로 결정 트리 구동."""
        hyps = [_hyp(0.9, "distribution-over-power"), _hyp(0.6, "log-distribution")]
        decision = select_intervention_from_hypotheses(hyps)
        assert decision is not None
        assert decision.pattern is InterventionPattern.COUNTEREXAMPLE  # 0.9 > 0.8
        assert decision.misconception_id == "distribution-over-power"

    def test_accumulated_confidence_thresholds(self) -> None:
        """가설 신뢰도가 결정 트리 임계를 그대로 탄다(>0.8 반례·≥0.5 거꾸로·<0.5 보류)."""
        assert (
            select_intervention_from_hypotheses([_hyp(0.85)]).pattern  # type: ignore[union-attr]
            is InterventionPattern.COUNTEREXAMPLE
        )
        assert (
            select_intervention_from_hypotheses([_hyp(0.6)]).pattern  # type: ignore[union-attr]
            is InterventionPattern.REVERSE_REASONING
        )
        # 감쇠해 0.5 미만이 된 가설 → 보류(None·낙인 금지)
        assert select_intervention_from_hypotheses([_hyp(0.3)]) is None

    def test_prompt_assembled_from_catalog(self) -> None:
        """focus의 misconception_id를 카탈로그로 해소해 프롬프트를 어셈블한다."""
        decision = select_intervention_from_hypotheses([_hyp(0.95, "distribution-over-power")])
        assert decision is not None
        assert "(a+b)² = a² + b²" in decision.prompt
        assert "a=1, b=1" in decision.prompt

    def test_unknown_misconception_id_holds(self) -> None:
        """카탈로그에 없는 느슨 id → 어셈블 불가 → None(보류·정직)."""
        assert select_intervention_from_hypotheses([_hyp(0.9, "nonexistent-mc-xyz")]) is None

    def test_rng_none_always_exploits_top(self) -> None:
        """rng=None → 항상 최상위 가설(탐색 안 함·결정론)."""
        hyps = [_hyp(0.9, "distribution-over-power"), _hyp(0.85, "log-distribution")]
        for _ in range(5):
            det = select_intervention_from_hypotheses(hyps, rng=None)
            assert det is not None and det.misconception_id == "distribution-over-power"

    def test_epsilon_one_explores_second_hypothesis(self) -> None:
        """epsilon=1 + 시드 rng → 차순위 가설을 탐색(ε passthrough 결정론·select_focus 위임)."""
        hyps = [_hyp(0.9, "distribution-over-power"), _hyp(0.85, "log-distribution")]
        det = select_intervention_from_hypotheses(hyps, epsilon=1.0, rng=random.Random(0))
        # epsilon=1 → 항상 차순위(top 제외) 탐색 → 두 번째 가설이 focus.
        assert det is not None
        assert det.misconception_id == "log-distribution"


class TestNoForbiddenLabeling:
    """프롬프트가 *직접 교정·학생 라벨링*을 하지 않음 — doc 절대 금지 §."""

    def test_no_direct_correction_phrases(self) -> None:
        for mid in ("distribution-over-power", "log-distribution"):
            for conf in (0.9, 0.7):
                decision = select_intervention(_match(conf, mid))
                assert decision is not None
                # doc L84-86 절대 금지 §
                assert "잘못된" not in decision.prompt
                assert "흔한 오개념" not in decision.prompt
                assert "다시 풀어와" not in decision.prompt
                assert "틀렸" not in decision.prompt


class TestEscalationLadderReader:
    """MISC-30 — focus 가설의 `evidence_count`가 개입 강도 등급으로 읽히는가.

    이 좌석이 사다리의 **유일한 reader**다. 배선이 끊기면 정책 모듈은 초록인데 서빙
    경로에서는 등급이 영영 `NONE`으로 남는다 — "정본화를 집행으로 착각한 완료 선언 금지".
    """

    def test_raw_match_has_no_repeat_signal(self) -> None:
        """단일 턴 매치에는 반복 횟수라는 사실 자체가 없다 → `None`(미관측).

        `NONE`(미발동)으로 채우면 작동 비율의 분모에 raw 매치가 섞여 비율이 희석된다.
        """
        decision = select_intervention(_match(0.9))
        assert decision is not None
        assert decision.escalation_rung is None

    def test_single_evidence_reads_as_not_escalated(self) -> None:
        """증거 1회는 반복이 아니다 — 읽었고 미발동(`NONE`)이다."""
        decision = select_intervention_from_hypotheses([_hyp(0.9, evidence_count=1)])
        assert decision is not None
        assert decision.escalation_rung is EscalationRung.NONE

    def test_ladder_rungs_are_wired_through(self) -> None:
        """2·3·4회가 각각 제 등급으로 올라오는가 — 경계 그대로."""
        expected = {
            1: EscalationRung.NONE,
            2: EscalationRung.CORRECTIVE_EXPLANATION,
            3: EscalationRung.EASIER_PROBLEM,
            4: EscalationRung.PREREQUISITE_CONCEPT,
            9: EscalationRung.PREREQUISITE_CONCEPT,
        }
        for count, rung in expected.items():
            decision = select_intervention_from_hypotheses([_hyp(0.9, evidence_count=count)])
            assert decision is not None, count
            assert decision.escalation_rung is rung, count

    def test_escalation_does_not_change_the_pattern(self) -> None:
        """강도와 패턴은 직교 축이다 — 반복이 쌓여도 발화 패턴은 신뢰도가 정한다."""
        low, high = (
            select_intervention_from_hypotheses([_hyp(0.65, evidence_count=1)]),
            select_intervention_from_hypotheses([_hyp(0.65, evidence_count=9)]),
        )
        assert low is not None and high is not None
        assert low.pattern is high.pattern is InterventionPattern.REVERSE_REASONING
        assert low.prompt == high.prompt

    def test_escalation_never_reaches_the_student_utterance(self) -> None:
        """정서 안전 — 반복 횟수·등급 어휘가 학생 발화에 실리면 안 된다.

        문자열 금지 목록이 아니라 *산출물*을 본다: 같은 가설에서 횟수만 바꾼 발화가
        **바이트 동일**해야 한다. 어떤 표현으로 새어 나가든 이 대조에 걸린다.
        """
        prompts = {
            select_intervention_from_hypotheses([_hyp(0.9, evidence_count=n)]).prompt  # type: ignore[union-attr]
            for n in range(1, 10)
        }
        assert len(prompts) == 1, f"반복 횟수가 발화를 바꿨다: {prompts}"
        only = prompts.pop()
        for leak in ("번째", "반복", "또", "계속", "다시"):
            assert leak not in only, leak

    def test_held_diagnosis_still_yields_no_decision(self) -> None:
        """신뢰도 보류(<0.5)는 등급과 무관하게 여전히 보류다 — 사다리가 보류를 뚫지 않는다."""
        assert select_intervention_from_hypotheses([_hyp(0.3, evidence_count=9)]) is None


class TestEscalationRungNeverReachesTheWire:
    """등급이 **HTTP 응답에 실리지 않는다** — PG 없이 통합 실패를 재현하는 좌석.

    사고 경위(2026-09-18 PR #1203): `escalation_rung`을 `InterventionDecision`에 그냥 추가했더니
    `api/coach.py`의 `CoachResponse.intervention`이 이 모델을 **그대로 직렬화**하는 탓에 내부
    라우팅 신호가 학생-대면 응답에 실렸다. 그 순간 응답이 *누적 증거의 함수*가 되어, 같은 입력을
    두 번 보낸 두 응답이 서로 달라졌다 — `tests/backend/api/test_coach_wh1_shadow.py`의 shadow
    ON/OFF 노출 비트동일 단언 2건이 RED가 났다.

    그 단언은 실 PG를 요구해 로컬·`backend` 잡에서 전부 skip된다(`backend-migrations` 잡에서만
    돈다). 그래서 **같은 불변식을 순수하게** 여기서 다시 잰다 — 이 클래스가 RED면 저 통합 테스트도
    RED다. 계약: 등급의 관측 좌석은 HTTP가 아니라 `TurnOutcome.escalation_rung`이다.
    """

    def test_dump_carries_no_escalation_key(self) -> None:
        decision = select_intervention_from_hypotheses([_hyp(0.9, evidence_count=4)])
        assert decision is not None
        assert decision.escalation_rung is EscalationRung.PREREQUISITE_CONCEPT  # 파이썬 속성엔 있다
        assert "escalation_rung" not in decision.model_dump()
        assert "escalation_rung" not in decision.model_dump_json()

    def test_repeat_count_does_not_change_the_serialized_response(self) -> None:
        """통합 실패의 재현 — 반복 횟수만 다른 두 결정의 *직렬화*가 비트동일해야 한다.

        `test_coach_wh1_shadow.py`가 같은 학생에게 같은 입력을 두 번 보내 응답을 대조하는데,
        두 번째 호출에서는 가설의 `evidence_count`가 1 늘어 있다. 그 차이가 직렬화에 새면
        저 대조가 깨진다.
        """
        dumps = {
            select_intervention_from_hypotheses([_hyp(0.9, evidence_count=n)]).model_dump_json()  # type: ignore[union-attr]
            for n in range(1, 10)
        }
        assert len(dumps) == 1, f"반복 횟수가 직렬화를 바꿨다: {dumps}"
