"""WH-1 하네스 match_misconception 품질 게이트 결선(MISC-18) — 동작 계약.

`harness/wh1_loop.py`의 MatchMisconceptionAction 실행부가 `apply_match_quality_gate`를 거친다는
것을 *동작*으로 고정한다. 이전에는 코치 경로(`api/coach.py`)만 게이트를 부르고 이 하네스 주경로는
`diagnose()` 원시 후보로 가설을 세웠다 — top-1 신뢰도 0.5짜리 약한 부분매칭 하나로 개입 발화까지
가는 라이브 결함류(match_gate.py docstring ①)가 이 경로에선 막히지 않았다("한 곳에서만 부름").

검증 설계(실패 주입으로 변별력을 확인한 케이스만 둔다):
  - **전제 고정**: 약한 입력이 실제로 "후보는 나오지만 floor 미만"이고 강한 입력은 floor 이상임을
    *실제 diagnose*로 먼저 단언한다 — 전제가 깨지면 아래 테스트가 공허하게 통과하므로(스캔 0건은
    실패) 전제 자체를 테스트로 만든다.
  - **대조군**: 같은 오개념(`distribution-over-power`)의 신호 1개(약함)와 2개(강함)를 쌍으로 쓴다 —
    신호 완결성만 다르므로 게이트 유무 외의 차이가 결과에 끼지 않는다.
  - **단일 원천**: floor를 하네스가 복제했는지는 "계약 쪽 floor를 바꾸면 하네스 결과가 따라 바뀌는가"로
    잰다(복제본이 있으면 계약을 바꿔도 그대로다).
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
from collections.abc import Callable
from typing import Any

import pytest

from whymath_backend.harness import wh1_loop, wh1_shadow
from whymath_backend.harness.wh1_loop import (
    CurateHypothesisAction,
    EndTurnAction,
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
from whymath_backend.l4.misconception.match_gate import apply_match_quality_gate

_MID = "distribution-over-power"
_STRONG_TEXT = "(a+b) a² + b²"  # 이 오개념의 신호 2개 전부 → confidence 1.0
_WEAK_TEXT = "(a+b)"  # 같은 오개념의 신호 1개뿐 → confidence 0.5 (floor 미만)
_NO_MATCH_TEXT = "그냥 천천히 풀어 봤어요"  # 어떤 오개념 신호도 없는 풀이

# 계약이 소유한 floor — 테스트도 상수를 복제하지 않고 시그니처 기본값에서 읽는다.
_FLOOR: float = inspect.signature(apply_match_quality_gate).parameters["confidence_floor"].default


def _turn(text: str) -> TurnOutcome:
    """match → curate → end_turn 한 턴을 돌려 가설 세트와 트레이스를 돌려준다."""
    policy = ScriptedTutorPolicy(
        [
            MatchMisconceptionAction(student_text=text),
            CurateHypothesisAction(),
            EndTurnAction(action_type="격려", utterance="잘하고 있어."),
        ]
    )
    return asyncio.run(run_tutoring_turn(policy=policy))


def _match_result(outcome: TurnOutcome) -> ToolResult:
    results = [r for r in outcome.trace if r.kind == "match_misconception"]
    assert len(results) == 1, "match_misconception 도구 결과가 정확히 1건이어야 한다"
    return results[0]


class TestPreconditions:
    """아래 모든 테스트의 전제 — 깨지면 나머지가 공허하게 통과한다."""

    def test_weak_input_is_a_raw_candidate_below_the_floor(self) -> None:
        raw = diagnose(_WEAK_TEXT)
        assert raw, "약한 입력은 원시 diagnose 후보가 있어야 한다(없으면 게이트가 걸러낼 것이 없다)"
        assert raw[0].misconception.id == _MID
        assert raw[0].confidence < _FLOOR

    def test_strong_input_is_at_or_above_the_floor(self) -> None:
        raw = diagnose(_STRONG_TEXT)
        assert raw
        assert raw[0].misconception.id == _MID
        assert raw[0].confidence >= _FLOOR


class TestGateAppliedInLoop:
    def test_weak_match_does_not_build_a_hypothesis(self) -> None:
        """게이트 ① — top-1<floor면 후보를 비워 가설이 서지 않는다(억지 매칭 금지)."""
        outcome = _turn(_WEAK_TEXT)

        assert outcome.hypotheses == []
        assert _match_result(outcome).detail == "오개념 후보 0건(내부)."

    def test_strong_match_still_builds_the_hypothesis(self) -> None:
        """대조군 — 게이트가 floor 이상 매치까지 막지 않는다(과차단 방지)."""
        outcome = _turn(_STRONG_TEXT)

        assert [h.misconception_id for h in outcome.hypotheses] == [_MID]

    def test_gate_activity_is_recorded_as_counts(self) -> None:
        """작동한 비율 — 게이트가 걸러낸 양(raw−kept)이 트레이스에 숫자로 남는다."""
        weak = _match_result(_turn(_WEAK_TEXT)).match_gate_counts
        assert weak == {
            "raw": len(diagnose(_WEAK_TEXT)),
            "kept": 0,
            "no_confident_match": 1,
            "attribution_unclear": 0,
        }
        assert weak["raw"] > weak["kept"], "약한 매치는 raw>kept(게이트가 실제로 일했다)여야 한다"

        strong = _match_result(_turn(_STRONG_TEXT)).match_gate_counts
        assert strong is not None
        assert strong["raw"] == strong["kept"] == len(diagnose(_STRONG_TEXT))
        assert strong["no_confident_match"] == 0

    def test_empty_input_counts_zero_raw_and_flags_no_confident_match(self) -> None:
        """후보가 아예 없을 때도 게이트는 같은 규칙(빈 입력 → no_confident_match)을 따른다."""
        counts = _match_result(_turn(_NO_MATCH_TEXT)).match_gate_counts

        assert counts is not None
        assert counts["raw"] == 0
        assert counts["kept"] == 0
        # 계약 규칙(match_gate.py): 비었거나 top-1<floor면 둘 다 no_confident_match=True.
        # 그래서 이 플래그만으로는 "약한 매치가 걸러졌다"를 알 수 없다 — 그건 raw−kept로만 센다.
        assert counts["no_confident_match"] == 1

    def test_counts_are_only_on_match_results(self) -> None:
        """관측 필드는 match_misconception 결과에만 — 다른 도구 결과는 None이다."""
        outcome = _turn(_STRONG_TEXT)

        others = [r for r in outcome.trace if r.kind != "match_misconception"]
        assert others, "match 외 도구 결과가 있어야 이 단언이 공허하지 않다"
        assert all(r.match_gate_counts is None for r in others)

    def test_counts_hold_numbers_only(self) -> None:
        """비식별 계약 — 값은 정수뿐이고 학생 원문·후보 id가 키/값에 들어가지 않는다."""
        counts = _match_result(_turn(_STRONG_TEXT)).match_gate_counts

        assert counts is not None
        assert all(isinstance(v, int) for v in counts.values())
        assert set(counts) == {"raw", "kept", "no_confident_match", "attribution_unclear"}


class TestSingleSourceOfTruth:
    """floor 0.65는 `match_gate.py`가 소유한다 — 하네스에 복제본이 없다(이중 진실원천 금지)."""

    def test_loop_calls_contract_without_overriding_floor_or_ocr(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """호출 인자 — floor·threshold 미전달(계약 기본값이 정본) + ocr_confidence 미전달(None).

        하네스는 OCR 신뢰도를 갖고 있지 않다 — 게이트 ②는 dormant여야 하고 없는 신호를 날조하지
        않는다. 인자를 *넘기지 않는 것*이 곧 단일 원천이다.
        """
        calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

        def spy(*args: Any, **kwargs: Any) -> Any:
            calls.append((args, kwargs))
            return apply_match_quality_gate(*args, **kwargs)

        monkeypatch.setattr(wh1_loop, "apply_match_quality_gate", spy)
        _turn(_WEAK_TEXT)

        assert len(calls) == 1, "match 액션 1회 = 게이트 호출 정확히 1회"
        args, kwargs = calls[0]
        assert len(args) == 1 and list(args[0]) == diagnose(_WEAK_TEXT)
        assert kwargs == {}, f"floor/threshold/ocr 인자를 하네스가 넘기면 안 된다: {kwargs}"

    def test_changing_the_contract_floor_changes_the_loop_result(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """계약 쪽 floor를 0으로 내리면 약한 매치가 통과해 가설이 선다 — 복제 floor가 없다는 증거.

        하네스가 자체 floor 비교를 가졌다면(복제) 계약을 바꿔도 약한 매치는 여전히 걸러진다.
        """
        open_gate: Callable[..., Any] = functools.partial(
            apply_match_quality_gate, confidence_floor=0.0
        )
        monkeypatch.setattr(wh1_loop, "apply_match_quality_gate", open_gate)

        outcome = _turn(_WEAK_TEXT)

        assert [h.misconception_id for h in outcome.hypotheses] == [_MID]
        counts = _match_result(outcome).match_gate_counts
        assert counts is not None and counts["raw"] == counts["kept"]


class TestShadowRecordCarriesGateCounts:
    """감소량이 서버 로그 레코드로 나간다 — 트레이스에만 있으면 운영에서 아무도 못 본다.

    "게이트를 붙였다"와 "게이트가 실사용에서 일했다"는 다르다(CLAUDE.md '작동한 비율'). shadow
    관측 레코드가 raw/kept 합을 싣고, 수확기는 같은 모델로 파싱하므로 그 값이 곧 운영 지표다.
    """

    @staticmethod
    def _record(outcome: TurnOutcome, caplog: pytest.LogCaptureFixture) -> Wh1HarnessShadowObservation:
        record_logger = wh1_shadow.record_logger.name
        with caplog.at_level(logging.INFO, logger=record_logger):
            emit_wh1_observation(outcome)
        lines = [r.getMessage() for r in caplog.records if r.name == record_logger]
        assert len(lines) == 1, "관측 레코드는 정확히 1줄"
        return Wh1HarnessShadowObservation.model_validate_json(lines[0])

    def test_weak_match_shows_raw_greater_than_kept_in_record(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        obs = self._record(_turn(_WEAK_TEXT), caplog)

        assert obs.n_match_raw == len(diagnose(_WEAK_TEXT))
        assert obs.n_match_kept == 0
        assert obs.n_match_raw is not None and obs.n_match_raw > 0

    def test_strong_match_keeps_everything_in_record(self, caplog: pytest.LogCaptureFixture) -> None:
        obs = self._record(_turn(_STRONG_TEXT), caplog)

        assert obs.n_match_raw == obs.n_match_kept == len(diagnose(_STRONG_TEXT))

    def test_turn_without_match_records_zero_not_none(self, caplog: pytest.LogCaptureFixture) -> None:
        """신판 emit은 match 미호출 턴도 0을 기록한다 — None(구판)과 0(신판·후보 없음)을 구분."""
        policy = ScriptedTutorPolicy([EndTurnAction(action_type="격려", utterance="잘하고 있어.")])
        outcome = asyncio.run(run_tutoring_turn(policy=policy))

        obs = self._record(outcome, caplog)

        assert (obs.n_match_raw, obs.n_match_kept) == (0, 0)

    def test_legacy_record_without_the_fields_still_parses_as_none(self) -> None:
        """하위호환 — 필드 신설 이전에 찍힌 로그 줄을 수확기가 계속 읽는다(None=구판)."""
        legacy = (
            '{"status":"ended","action_type":"격려","verify_verdict":null,'
            '"tool_calls":1,"hypothesis_count":0}'
        )

        obs = Wh1HarnessShadowObservation.model_validate_json(legacy)

        assert obs.n_match_raw is None and obs.n_match_kept is None

    def test_count_helper_sums_ok_results_and_ignores_rejected_and_legacy(self) -> None:
        trace = [
            ToolResult(
                kind="match_misconception",
                ok=True,
                detail="오개념 후보 0건(내부).",
                match_gate_counts={"raw": 3, "kept": 1, "no_confident_match": 0, "attribution_unclear": 0},
            ),
            ToolResult(
                kind="match_misconception",
                ok=True,
                detail="오개념 후보 0건(내부).",
                match_gate_counts={"raw": 2, "kept": 0, "no_confident_match": 1, "attribution_unclear": 0},
            ),
            ToolResult(  # 거부된 실행은 판정이 아니다.
                kind="match_misconception",
                ok=False,
                detail="거부.",
                match_gate_counts={"raw": 99, "kept": 99, "no_confident_match": 0, "attribution_unclear": 0},
            ),
            ToolResult(kind="match_misconception", ok=True, detail="구판 결과(필드 None)."),
            ToolResult(kind="end_turn", ok=True, detail="학생 발화 산출(격려)."),
            ToolResult(  # kind 절의 반례 — match 가 아닌 결과가 숫자를 달고 있어도 세지 않는다.
                kind="curate_hypothesis",
                ok=True,
                detail="활성 가설 0건(내부).",
                match_gate_counts={"raw": 7, "kept": 7, "no_confident_match": 0, "attribution_unclear": 0},
            ),
        ]

        assert wh1_shadow._count_match_gate(trace) == (5, 1)
