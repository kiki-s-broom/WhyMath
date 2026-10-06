"""라벨 없는 힌트 단계와 도움 공급 판정 — EOS-178 (순수 단위·DB 무접근).

`decide_hint_level`은 학생 신호(답 요구·좌절·5회+ 막힘)와 능력 라벨('초보' +1·'숙달' −1)을 섞어 한
단계를 낸다. 숙달 라벨 '초보'는 오답 한 건이면 켜지므로(`docs/reviews/eos178_beginner_label_hint_
judgment_2026-10-06.md` §1) 신호 없는 턴이 라벨만으로 1→2(= `HINT_USAGE_MIN_LEVEL`)가 된다. 이 파일은
그 두 입력을 가르는 두 부품을 잡는다:

  - `decide_base_hint_level` — 같은 함수의 라벨 없는 호출(진실원천 하나).
  - `counts_as_help_supply` — 공급 원장 행 1개를 '도움'으로 세는 진리표.

핵심 성질 하나를 격자 전수로 고정한다: **`base ≥ 2 ⟺ 그 턴에 학생 신호`** — 귀속이 `prev`의 경로
의존(라벨이 이월한 한 칸)과 무관하게 서는 근거다.
"""

from __future__ import annotations

from itertools import product

import pytest
from pydantic import ValidationError

from whymath_backend.l4.hint_deferral import (
    DEMAND_ANSWER_TOKENS,
    FRUSTRATION_TOKENS,
    STUCK_TURN_THRESHOLD,
    counts_as_help_supply,
    decide_base_hint_level,
    decide_hint_level,
    has_any_token,
)
from whymath_backend.l4.lthc.models import MasteryLevel
from whymath_backend.l4.models import PedagogyDecision, PolyaState
from whymath_backend.l4.polya.engine import PolyaCoach
from whymath_backend.schema.enums import EventType
from whymath_backend.schema.event_data_contract import build_event_data

_LABELS: tuple[MasteryLevel | None, ...] = (None, "초보", "발전 중", "숙달")
_UTTERANCES = ("x의 값을 다시 구해볼게요", "모르겠어요", "그냥 답 알려주세요", "")
_PREVS = (None, 1, 2, 3, 4)
_TURNS = (0, 1, 2, 4, 5, 6)


class TestBaseIsTheSameFunctionWithoutALabel:
    def test_base_equals_decide_with_no_label_on_the_whole_grid(self) -> None:
        """진실원천 하나 — 새 규칙이 아니라 `mastery_level=None` 호출이다(격자 120점)."""
        checked = 0
        for text, prev, turn in product(_UTTERANCES, _PREVS, _TURNS):
            expected = decide_hint_level(
                student_input=text, turn_count=turn, prev_hint_level=prev, mastery_level=None
            )
            got = decide_base_hint_level(student_input=text, turn_count=turn, prev_hint_level=prev)
            assert got == expected, (text, prev, turn)
            checked += 1
        assert checked == 4 * 5 * 6

    def test_base_ignores_the_label_that_decide_applies(self) -> None:
        """'초보'는 최종 단계를 올리지만 base는 그대로다 — 두 값이 갈라지는 지점이 곧 라벨의 효과다."""
        base = decide_base_hint_level(
            student_input="계속 풀어볼게요", turn_count=1, prev_hint_level=1
        )
        boosted = decide_hint_level(
            student_input="계속 풀어볼게요", turn_count=1, prev_hint_level=1, mastery_level="초보"
        )
        assert (base, boosted) == (1, 2)


class TestBaseAtLeastTwoMeansAStudentSignal:
    def test_equivalence_on_the_whole_grid(self) -> None:
        """`base ≥ 2` ⟺ 답 요구 ∨ 좌절 ∨ 5회+ 막힘 — `prev`가 무엇이든(라벨 이월 포함)."""
        checked = 0
        for text, prev, turn in product(_UTTERANCES, _PREVS, _TURNS):
            signal = (
                has_any_token(text.strip(), DEMAND_ANSWER_TOKENS)
                or has_any_token(text.strip(), FRUSTRATION_TOKENS)
                or turn >= STUCK_TURN_THRESHOLD
            )
            base = decide_base_hint_level(student_input=text, turn_count=turn, prev_hint_level=prev)
            assert (base >= 2) is signal, (text, prev, turn, base)
            checked += 1
        assert checked == 120

    def test_the_grid_has_both_sides(self) -> None:
        """대조군 — 격자에 신호 있는 점과 없는 점이 모두 있다(한쪽만 있으면 위 단언은 공허하다)."""
        bases = {
            decide_base_hint_level(student_input=t, turn_count=n, prev_hint_level=p) >= 2
            for t, p, n in product(_UTTERANCES, _PREVS, _TURNS)
        }
        assert bases == {True, False}


class TestCountsAsHelpSupplyTruthTable:
    """(최종 단계, base, 검수 힌트 실림) 진리표 — 리터럴 기대값 전건."""

    @pytest.mark.parametrize(
        ("hint_level", "base_level", "served", "expected"),
        [
            # 최종 단계가 2 미만 — 방향만 나갔다(EOS-133 기준 그대로).
            (1, None, False, False),
            (1, 1, False, False),
            (1, 2, False, False),  # '숙달' 완화로 내려간 신호 턴 — 공급한 것이 방향뿐이다
            (1, 3, True, False),  # 최종 1에는 검수 힌트가 실릴 수 없지만 값 자체로 거짓이어야 한다
            # base 모름 — 구판 행이다. 종전 규칙대로 센다(모른다 ≠ 아니다).
            (2, None, False, True),
            (3, None, False, True),
            (4, None, True, True),
            # base ≥ 2 — 학생 신호가 올린 공급.
            (2, 2, False, True),
            (3, 2, False, True),  # 신호 + '초보' 한 칸
            (3, 3, False, True),
            (4, 3, False, True),
            (4, 4, False, True),
            # base < 2 ∧ 최종 ≥ 2 — 라벨만 올린 공급. 검수 힌트가 실렸을 때만 센다.
            (2, 1, False, False),
            (2, 1, True, True),
        ],
    )
    def test_row(
        self, hint_level: int, base_level: int | None, served: bool, expected: bool
    ) -> None:
        assert (
            counts_as_help_supply(hint_level=hint_level, base_level=base_level, served=served)
            is expected
        )

    def test_the_only_false_with_level_two_plus_is_label_only_and_unserved(self) -> None:
        """최종 ≥ 2인데 거짓인 입력은 (base<2 ∧ 미서빙) 하나뿐이다 — 전건 열거로 닫는다."""
        falses = [
            (level, base, served)
            for level, base, served in product((2, 3, 4), (None, 1, 2, 3, 4), (False, True))
            if not counts_as_help_supply(hint_level=level, base_level=base, served=served)
        ]
        assert falses == [(2, 1, False), (3, 1, False), (4, 1, False)]


class TestEngineCarriesTheLabelFreeLevel:
    """엔진 결정이 라벨 없는 단계와 적용된 라벨을 **함께** 들고 나간다 — 원장 적재의 재료다."""

    @staticmethod
    def _decide(label: MasteryLevel | None) -> PedagogyDecision:
        return PolyaCoach().decide(
            "계속 풀어볼게요", PolyaState(turn_count=1, prev_hint_level=1), mastery_level=label
        )

    def test_a_beginner_label_raises_the_final_level_but_not_the_base(self) -> None:
        decision = self._decide("초보")
        assert (decision.hint_level, decision.base_hint_level) == (2, 1)
        assert decision.applied_mastery_level == "초보"

    def test_a_mastery_label_lowers_the_final_level_but_not_the_base(self) -> None:
        """신호 없는 턴은 base 1이고 '숙달' 완화는 1에서 바닥이라 둘이 같다 — 라벨은 그래도 기록된다."""
        decision = self._decide("숙달")
        assert (decision.hint_level, decision.base_hint_level) == (1, 1)
        assert decision.applied_mastery_level == "숙달"

    def test_no_label_means_base_equals_final_and_no_applied_label(self) -> None:
        decision = self._decide(None)
        assert (decision.hint_level, decision.base_hint_level) == (1, 1)
        assert decision.applied_mastery_level is None

    def test_a_frustration_turn_has_a_signal_base_under_a_beginner_label(self) -> None:
        decision = PolyaCoach().decide(
            "모르겠어요", PolyaState(turn_count=1, prev_hint_level=1), mastery_level="초보"
        )
        assert (decision.hint_level, decision.base_hint_level) == (3, 2)

    def test_a_stuck_turn_has_a_signal_base_from_the_turn_count(self) -> None:
        """5회+ 막힘(규칙 1)은 신호 — base 3이고 '초보'가 한 칸 얹어 최종 4. base가 `turn_count`를 본다."""
        decision = PolyaCoach().decide(
            "계속 풀어볼게요", PolyaState(turn_count=5, prev_hint_level=1), mastery_level="초보"
        )
        assert (decision.hint_level, decision.base_hint_level) == (4, 3)

    def test_the_base_follows_the_previous_level_like_the_final_one(self) -> None:
        """좌절 턴의 base는 `prev+1` — prev가 2면 3(최종 4). base가 `prev_hint_level`을 본다."""
        decision = PolyaCoach().decide(
            "모르겠어요", PolyaState(turn_count=1, prev_hint_level=2), mastery_level="초보"
        )
        assert (decision.hint_level, decision.base_hint_level) == (4, 3)

    def test_model_copy_keeps_both_fields(self) -> None:
        """완료 상태머신·발화 교체가 `model_copy(update=)`로 결정을 고쳐도 계측 재료는 남는다."""
        decision = self._decide("초보").model_copy(update={"prompt": "교체된 발화"})
        assert (decision.base_hint_level, decision.applied_mastery_level) == (1, "초보")


class TestMeasurementFieldsStayOutOfTheResponse:
    """`exclude=True` — 내부 계측이 응답 본문·OpenAPI 응답 스키마로 새지 않는다."""

    def test_dump_excludes_both_fields(self) -> None:
        dumped = self._decision().model_dump()
        assert "base_hint_level" not in dumped
        assert "applied_mastery_level" not in dumped
        assert "base_hint_level" not in self._decision().model_dump_json()

    def test_the_fields_exist_on_the_instance(self) -> None:
        """대조군 — 제외는 직렬화에서만이다. 인스턴스에는 값이 있다(없으면 위 단언이 공허하다)."""
        assert self._decision().base_hint_level == 1
        assert self._decision().applied_mastery_level == "초보"

    @staticmethod
    def _decision() -> PedagogyDecision:
        return PolyaCoach().decide(
            "계속 풀어볼게요", PolyaState(turn_count=1, prev_hint_level=1), mastery_level="초보"
        )


class TestLedgerContractBounds:
    """`HintEventData`의 새 필드 범위 — 깨진 값이 원장에 들어가지 않는다."""

    @pytest.mark.parametrize("base", [1, 2, 3, 4, None])
    def test_base_level_accepts_the_closed_range_and_none(self, base: int | None) -> None:
        assert (
            build_event_data(EventType.힌트제공, hint_level=2, base_level=base)["base_level"]
            == base
        )

    @pytest.mark.parametrize("base", [0, 5, -1])
    def test_base_level_rejects_out_of_range(self, base: int) -> None:
        with pytest.raises(ValidationError):
            build_event_data(EventType.힌트제공, hint_level=2, base_level=base)

    def test_ability_level_is_a_short_string(self) -> None:
        data = build_event_data(EventType.힌트제공, hint_level=2, ability_level="초보")
        assert data["ability_level"] == "초보"
        with pytest.raises(ValidationError):
            build_event_data(EventType.힌트제공, hint_level=2, ability_level="x" * 17)
