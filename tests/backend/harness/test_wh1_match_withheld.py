"""WH-1 하네스 확신 진단 보류(MISC-60) — 귀속 불명 매치는 학습자 모델 쪽 도구에 들어가지 않는다.

배경: 하네스는 `wh1_primary_enabled`(기본 ON·2026-07-20 GA)로 학생 대면 발화를 만든다. 코치 경로는
정정 어구의 귀속이 불명(게이트③)하거나 OCR이 미확인(게이트②)이면 그 턴에 가설 갱신·+1·−1 증거를
전부 보류하는데(`persisted_matches=[]`), 하네스는 그 플래그를 보지 않아 같은 입력에 확정 진단처럼
굴었다. 실측(카탈로그 67종): 정정 어구가 신호 앞에 오는 입력 67/67에서 `attribution_unclear`가 섰는데도
하네스가 가설 67건·+1 증거 67건을 만들었고, 학생이 "틀린 풀이:"라고 *표시한* 주장을 했다고 단정하는
발화("…이 항상 맞다고 했지")가 나갔다.

검증 설계(실패 주입으로 변별력을 확인한 케이스만 둔다):
  - **전제 고정**: 보류 입력이 실제로 "top-1이 귀속 불명"이고 대조군은 아님을 *실제 diagnose+게이트*로
    먼저 단언한다 — 전제가 깨지면 아래가 공허하게 통과한다.
  - **대조군**: 같은 오개념의 신호는 같고 정정 어구 유무만 다른 쌍(`_UNCLEAR_TEXT`/`_CLEAN_TEXT`).
  - **단일 원천**: 보류 판정을 하네스가 자체 구현했는지는 "공유 술어를 바꾸면 하네스 결과가 따라
    바뀌는가"로 잰다.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

import pytest

from whymath_backend.api import coach
from whymath_backend.harness import wh1_loop, wh1_shadow
from whymath_backend.harness.wh1_loop import (
    NEUTRAL_GUIDE_UTTERANCE,
    Action,
    CurateHypothesisAction,
    EndTurnAction,
    LogEvidenceAction,
    MatchMisconceptionAction,
    ScriptedTutorPolicy,
    ToolResult,
    TurnOutcome,
    run_tutoring_turn,
)
from whymath_backend.harness.wh1_shadow import (
    Wh1HarnessShadowObservation,
    emit_wh1_observation,
)
from whymath_backend.l4.misconception.diagnose import diagnose
from whymath_backend.l4.misconception.hypothesis import MisconceptionHypothesis
from whymath_backend.l4.misconception.match_gate import (
    apply_match_quality_gate,
    is_verdict_withheld,
)

_MID = "distribution-over-power"
_CLEAN_TEXT = "(a+b) a² + b²"  # 정정 어구 없음 → 귀속 판정 none
_UNCLEAR_TEXT = "틀린 풀이: (a+b) a² + b²"  # 정정 어구가 신호 *앞* → 귀속 불명(unclear)


def _run(actions: list[Action], initial: tuple[MisconceptionHypothesis, ...] = ()) -> TurnOutcome:
    policy = ScriptedTutorPolicy(actions)
    return asyncio.run(run_tutoring_turn(policy=policy, initial_hypotheses=list(initial)))


def _match_curate_ask(text: str) -> list[Action]:
    return [
        MatchMisconceptionAction(student_text=text),
        CurateHypothesisAction(),
        EndTurnAction(action_type="질문"),
    ]


def _results(outcome: TurnOutcome, kind: str) -> list[ToolResult]:
    return [r for r in outcome.trace if r.kind == kind]


def _existing() -> MisconceptionHypothesis:
    return MisconceptionHypothesis(
        misconception_id=_MID, confidence=0.5, turns_since_evidence=0, evidence_count=1
    )


class TestPreconditions:
    """아래 모든 테스트의 전제 — 깨지면 나머지가 공허하게 통과한다."""

    def test_unclear_input_has_a_gated_top1_with_unclear_attribution(self) -> None:
        raw = diagnose(_UNCLEAR_TEXT)
        assert raw and raw[0].misconception.id == _MID
        gate = apply_match_quality_gate(raw)
        assert gate.matches, "게이트 ①을 통과해야 한다(비워지면 보류할 판정이 없다)"
        assert gate.attribution_unclear is True
        assert is_verdict_withheld(
            low_quality=gate.low_quality, attribution_unclear=gate.attribution_unclear
        )

    def test_clean_input_is_not_unclear(self) -> None:
        gate = apply_match_quality_gate(diagnose(_CLEAN_TEXT))
        assert gate.matches and gate.matches[0].misconception.id == _MID
        assert gate.attribution_unclear is False


class TestHypothesisIsWithheld:
    def test_unclear_match_does_not_build_a_hypothesis(self) -> None:
        """보류 턴 — 가설이 서지 않는다(코치 `_apply_hypotheses(persisted_matches=[])` 동형)."""
        outcome = _run(_match_curate_ask(_UNCLEAR_TEXT))

        assert outcome.hypotheses == []

    def test_unclear_turn_asks_the_neutral_confirmation_not_an_attributing_question(self) -> None:
        """가설이 없으면 파생 발화는 중립 확인 질문이다 — 학생이 한 적 없는 주장을 단정하지 않는다."""
        outcome = _run(_match_curate_ask(_UNCLEAR_TEXT))

        assert outcome.utterance == NEUTRAL_GUIDE_UTTERANCE

    def test_clean_match_still_builds_the_hypothesis(self) -> None:
        """대조군 — 정정 어구가 없으면 종전대로 가설이 서고 오개념을 겨냥한 질문이 나간다."""
        outcome = _run(_match_curate_ask(_CLEAN_TEXT))

        assert [h.misconception_id for h in outcome.hypotheses] == [_MID]
        assert outcome.utterance != NEUTRAL_GUIDE_UTTERANCE

    def test_candidates_stay_visible_but_flag_is_recorded(self) -> None:
        """'매칭은 유지하되 확신 진단은 보류' — 후보 수는 그대로 1건, 플래그가 계수에 남는다."""
        outcome = _run(_match_curate_ask(_UNCLEAR_TEXT))

        match = _results(outcome, "match_misconception")[0]
        assert match.detail == "오개념 후보 1건(내부)."
        assert match.match_gate_counts is not None
        assert match.match_gate_counts["kept"] == 1
        assert match.match_gate_counts["attribution_unclear"] == 1

    def test_unclear_turn_only_decays_an_existing_hypothesis(self) -> None:
        """기존 가설이 있으면 보류 턴은 *강화하지 않고 감쇠만* 한다(빈 매칭 턴과 동일)."""
        withheld = _run(_match_curate_ask(_UNCLEAR_TEXT), (_existing(),))
        reinforced = _run(_match_curate_ask(_CLEAN_TEXT), (_existing(),))

        (kept,) = withheld.hypotheses
        (boosted,) = reinforced.hypotheses
        assert kept.evidence_count == 1, "보류 턴은 증거 수를 늘리지 않는다"
        assert kept.confidence < 0.5, "보류 턴은 감쇠한다(강화하지 않는다)"
        assert kept.turns_since_evidence == 1
        assert boosted.evidence_count == 2, "대조군은 강화된다"


class TestEvidenceIsWithheld:
    @pytest.mark.parametrize("polarity", [1, -1])
    def test_log_evidence_is_refused_on_a_withheld_turn(self, polarity: int) -> None:
        """+1 지지도 −1 반박도 만들지 않는다 — `모른다`가 `아니다`로 뒤집히지 않게(양방향 보류)."""
        outcome = _run(
            [
                MatchMisconceptionAction(student_text=_UNCLEAR_TEXT),
                LogEvidenceAction(misconception_id=_MID, polarity=polarity),
                EndTurnAction(action_type="격려", utterance="잘하고 있어."),
            ]
        )

        (result,) = _results(outcome, "log_evidence")
        assert result.ok is False
        assert "귀속 불명" in result.detail
        assert outcome.evidence == []

    def test_log_evidence_is_accepted_on_a_clean_turn(self) -> None:
        """대조군 — 보류가 없는 턴은 종전대로 적재된다(과차단 방지)."""
        outcome = _run(
            [
                MatchMisconceptionAction(student_text=_CLEAN_TEXT),
                LogEvidenceAction(misconception_id=_MID, polarity=1),
                EndTurnAction(action_type="격려", utterance="잘하고 있어."),
            ]
        )

        (result,) = _results(outcome, "log_evidence")
        assert result.ok is True
        assert [(e.misconception_id, e.polarity) for e in outcome.evidence] == [(_MID, 1)]

    def test_log_evidence_before_any_match_is_not_withheld(self) -> None:
        """match 이전엔 보류 상태가 없다 — 기본값이 True면 증거 도구가 통째로 막힌다."""
        outcome = _run(
            [
                LogEvidenceAction(misconception_id=_MID, polarity=1),
                EndTurnAction(action_type="격려", utterance="잘하고 있어."),
            ]
        )

        assert _results(outcome, "log_evidence")[0].ok is True

    def test_latest_match_decides_clean_after_unclear(self) -> None:
        """보류는 *마지막* match 기준이다(`last_matches`와 같은 수명) — 뒤의 정상 match가 푼다."""
        outcome = _run(
            [
                MatchMisconceptionAction(student_text=_UNCLEAR_TEXT),
                MatchMisconceptionAction(student_text=_CLEAN_TEXT),
                LogEvidenceAction(misconception_id=_MID, polarity=1),
                EndTurnAction(action_type="격려", utterance="잘하고 있어."),
            ]
        )

        assert _results(outcome, "log_evidence")[0].ok is True

    def test_latest_match_decides_unclear_after_clean(self) -> None:
        outcome = _run(
            [
                MatchMisconceptionAction(student_text=_CLEAN_TEXT),
                MatchMisconceptionAction(student_text=_UNCLEAR_TEXT),
                LogEvidenceAction(misconception_id=_MID, polarity=1),
                EndTurnAction(action_type="격려", utterance="잘하고 있어."),
            ]
        )

        assert _results(outcome, "log_evidence")[0].ok is False

    def test_existing_refusals_keep_their_own_reason_first(self) -> None:
        """기존 거부(미등록 오개념)가 보류 거부보다 먼저 판정된다 — 거부 사유가 가려지지 않는다."""
        outcome = _run(
            [
                MatchMisconceptionAction(student_text=_UNCLEAR_TEXT),
                LogEvidenceAction(misconception_id="no-such-misconception", polarity=1),
                EndTurnAction(action_type="격려", utterance="잘하고 있어."),
            ]
        )

        (result,) = _results(outcome, "log_evidence")
        assert result.ok is False
        assert "미등록" in result.detail


class TestSingleSourceOfTruth:
    @pytest.mark.parametrize(
        ("low_quality", "attribution_unclear", "expected"),
        [(False, False, False), (True, False, True), (False, True, True), (True, True, True)],
    )
    def test_coach_and_contract_agree_on_the_truth_table(
        self, low_quality: bool, attribution_unclear: bool, expected: bool
    ) -> None:
        """진리표를 명시값으로 고정하고, 코치 `_MatchOutcome`이 같은 값을 낸다(위임)."""
        outcome = coach._MatchOutcome(
            matches=[],
            low_quality=low_quality,
            no_confident_match=False,
            attribution_unclear=attribution_unclear,
        )

        assert (
            is_verdict_withheld(low_quality=low_quality, attribution_unclear=attribution_unclear)
            is expected
        )
        assert outcome.verdict_withheld is expected

    def test_changing_the_shared_predicate_changes_the_loop_result(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """공유 술어를 항상 False로 바꾸면 하네스가 가설을 세운다 — 하네스에 자체 판정이 없다는 증거."""
        never: Callable[..., Any] = lambda **_: False  # noqa: E731 — 한 줄 대체물
        monkeypatch.setattr(wh1_loop, "is_verdict_withheld", never)

        outcome = _run(_match_curate_ask(_UNCLEAR_TEXT))

        assert [h.misconception_id for h in outcome.hypotheses] == [_MID]


class TestShadowRecordCarriesWithheldCount:
    """보류가 운영에서 얼마나 자주 발동하는지가 서버 로그 레코드로 나간다(작동한 비율).

    학생 대면 동작을 바꾸는 보류가 몇 턴에서 발동했는지 셀 수 없으면 "붙였다"와 "일했다"가
    구분되지 않는다(CLAUDE.md '작동 신호 없는 알고리즘 부착 금지').
    """

    @staticmethod
    def _record(
        outcome: TurnOutcome, caplog: pytest.LogCaptureFixture
    ) -> Wh1HarnessShadowObservation:
        record_logger = wh1_shadow.record_logger.name
        with caplog.at_level(logging.INFO, logger=record_logger):
            emit_wh1_observation(outcome)
        lines = [r.getMessage() for r in caplog.records if r.name == record_logger]
        assert len(lines) == 1, "관측 레코드는 정확히 1줄"
        return Wh1HarnessShadowObservation.model_validate_json(lines[0])

    def test_unclear_turn_is_counted_in_the_record(self, caplog: pytest.LogCaptureFixture) -> None:
        obs = self._record(_run(_match_curate_ask(_UNCLEAR_TEXT)), caplog)

        assert obs.n_match_attribution_unclear == 1

    def test_clean_turn_records_zero(self, caplog: pytest.LogCaptureFixture) -> None:
        obs = self._record(_run(_match_curate_ask(_CLEAN_TEXT)), caplog)

        assert obs.n_match_attribution_unclear == 0

    def test_turn_without_match_records_zero_not_none(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """신판 emit은 match 미호출 턴도 0을 기록한다 — None(구판)과 0(신판·보류 없음)을 구분."""
        outcome = _run([EndTurnAction(action_type="격려", utterance="잘하고 있어.")])

        assert self._record(outcome, caplog).n_match_attribution_unclear == 0

    def test_legacy_record_without_the_field_still_parses_as_none(self) -> None:
        """하위호환 — 필드 신설 이전에 찍힌 로그 줄을 수확기가 계속 읽는다(None=구판)."""
        legacy = (
            '{"status":"ended","action_type":"격려","verify_verdict":null,'
            '"tool_calls":1,"hypothesis_count":0}'
        )

        obs = Wh1HarnessShadowObservation.model_validate_json(legacy)

        assert obs.n_match_attribution_unclear is None

    def test_helper_sums_only_ok_match_results(self) -> None:
        def counts(unclear: int) -> dict[str, int]:
            return {"raw": 1, "kept": 1, "no_confident_match": 0, "attribution_unclear": unclear}

        trace = [
            ToolResult(
                kind="match_misconception", ok=True, detail="a", match_gate_counts=counts(1)
            ),
            ToolResult(
                kind="match_misconception", ok=True, detail="b", match_gate_counts=counts(1)
            ),
            ToolResult(  # 거부된 실행은 판정이 아니다.
                kind="match_misconception", ok=False, detail="c", match_gate_counts=counts(9)
            ),
            ToolResult(kind="match_misconception", ok=True, detail="구판 결과(필드 None)."),
            ToolResult(  # kind 절의 반례 — match 가 아닌 결과가 숫자를 달고 있어도 세지 않는다.
                kind="curate_hypothesis", ok=True, detail="d", match_gate_counts=counts(7)
            ),
        ]

        assert wh1_shadow._count_match_attribution_unclear(trace) == 2
