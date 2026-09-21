"""답 미루기 4단계 graded hint 단위테스트 — 스펙 L31-61 정본 정렬.

핵심 invariant:
- 모호 시 hint_level=1(가장 빠른 단계 — 생산적 막힘 우선)
- 점진 상승 min(4, prev+1) — 시나리오 3·4(socratic_template)
- 5회+ 막힘 → 최소 3(스펙 L37) but prev 이하로 내려가지 않음
- REVEALS 라벨이 PRD 정렬과 1:1
"""

from __future__ import annotations

import pytest

from whymath_backend.l4.hint_deferral import (
    REVEALS,
    decide_hint_level,
    is_ceiling_reached,
)
from whymath_backend.l4.lthc.models import MasteryLevel


class TestDefaultLevelOne:
    """모호한 입력(신호 없음·5회 미만) → 1(가장 은근·가장 빠른 단계)."""

    def test_empty_input_first_turn(self) -> None:
        assert decide_hint_level(student_input="", turn_count=0, prev_hint_level=None) == 1

    def test_neutral_input_returns_1_even_if_prev_higher(self) -> None:
        # prev_hint_level이 높아도 신호 사라지면 1로 복귀(가장 빠른 단계에서 멈춤).
        assert (
            decide_hint_level(student_input="네, 그렇게 해볼게요", turn_count=2, prev_hint_level=3)
            == 1
        )


class TestFrustrationSignal:
    """좌절 신호 → min(4, prev+1) 점진 상승(socratic_template 시나리오 4)."""

    @pytest.mark.parametrize("text", ["잘 모르겠어", "막혔어", "너무 어려워", "헷갈려"])
    def test_frustration_keywords_advance(self, text: str) -> None:
        assert decide_hint_level(student_input=text, turn_count=1, prev_hint_level=1) == 2
        assert decide_hint_level(student_input=text, turn_count=1, prev_hint_level=2) == 3
        assert decide_hint_level(student_input=text, turn_count=1, prev_hint_level=3) == 4

    def test_frustration_caps_at_4(self) -> None:
        assert decide_hint_level(student_input="너무 어려워", turn_count=1, prev_hint_level=4) == 4


class TestDemandAnswerSignal:
    """답 요구 신호 → min(4, prev+1) 점진 상승(시나리오 3)."""

    @pytest.mark.parametrize("text", ["답 알려줘", "그냥 답이 뭐야", "정답 알려줘", "풀이 좀 해줘"])
    def test_demand_keywords_advance(self, text: str) -> None:
        assert decide_hint_level(student_input=text, turn_count=1, prev_hint_level=1) == 2
        assert decide_hint_level(student_input=text, turn_count=1, prev_hint_level=2) == 3

    def test_demand_caps_at_4(self) -> None:
        assert decide_hint_level(student_input="답 알려줘", turn_count=1, prev_hint_level=4) == 4


class TestStuckThreshold:
    """turn_count ≥ 5 → 최소 3(스펙 L37 "5회+ 막힘 → 부분 풀이")."""

    def test_five_turns_no_signal_jumps_to_3(self) -> None:
        # 신호 없어도 5회 막혔으면 3으로 점프(보수적 디폴트보다 우선).
        assert decide_hint_level(student_input="음...", turn_count=5, prev_hint_level=1) == 3

    def test_five_turns_prev_4_stays_4(self) -> None:
        # prev=4면 3으로 내려가지 않음(max).
        assert decide_hint_level(student_input="음...", turn_count=5, prev_hint_level=4) == 4

    def test_four_turns_still_default(self) -> None:
        # 임계 미만(4회)은 기본 규칙 적용.
        assert decide_hint_level(student_input="음...", turn_count=4, prev_hint_level=1) == 1


class TestPriorityOrder:
    """5회+ 막힘이 다른 신호보다 우선(임계가 가장 강력)."""

    def test_stuck_beats_demand_signal(self) -> None:
        # 5회+ 막힘 + 답 요구 → 막힘 규칙 적용(max(prev, 3)).
        # prev=1일 때: max(1, 3) = 3 (demand의 min(4, 2)=2보다 큼 — 임계 우선)
        assert decide_hint_level(student_input="답 알려줘", turn_count=5, prev_hint_level=1) == 3


class TestRevealsMap:
    """REVEALS 매핑이 PRD 정렬(스펙 L41-49)과 1:1."""

    def test_all_four_levels_have_reveals(self) -> None:
        assert set(REVEALS.keys()) == {1, 2, 3, 4}
        for label in REVEALS.values():
            assert label  # 비공 문자열

    def test_canonical_reveals_labels(self) -> None:
        assert REVEALS[1] == "next_concept_to_focus"
        assert REVEALS[2] == "step_flow"
        assert REVEALS[3] == "partial_steps_demo"
        assert REVEALS[4] == "full_solution"


class TestNoFalsePositives:
    """합법 토큰 부분일치로 신호 오작동 — 보수적 디자인 한계 문서화."""

    def test_short_neutral_phrasing_stays_1(self) -> None:
        # 좌절 토큰("어렵") 없는 자연스러운 응답
        assert (
            decide_hint_level(student_input="이 부분이 흥미롭네요", turn_count=2, prev_hint_level=2)
            == 1
        )


class TestMasteryConservatism:
    """능력 라벨 양방향 조정(slice 69 숙달·slice 77 초보) — 숙달 −1·초보 +1·발전중/None 불변."""

    def test_master_demand_lowered_to_1(self) -> None:
        # 답요구 prev=1: base 2 → max(1, 2-1)=1(가장 은근).
        assert (
            decide_hint_level(
                student_input="답 알려줘",
                turn_count=1,
                prev_hint_level=1,
                mastery_level="숙달",
            )
            == 1
        )

    def test_master_stuck_ceiling_guaranteed_at_3(self) -> None:
        # PED-35: 5회+ 막힘 prev=1: base 3 → 숙달 완화 max(1, 3-1)=2 →
        # 규칙 6(상한 도달 보장)이 turn_count≥5를 재확인해 max(2, 3)=3으로 복원.
        # 규칙 5만 있던 구 버전은 여기서 2를 반환해 "부분 풀이"(레벨 3)에 영영 도달하지
        # 못했다(실측 갭 — learnlm_pedagogy_prompting_review_2026-08.md §4-2).
        assert (
            decide_hint_level(
                student_input="음...",
                turn_count=5,
                prev_hint_level=1,
                mastery_level="숙달",
            )
            == 3
        )

    def test_master_neutral_stays_1(self) -> None:
        # 중립 base 1 → max(1, 0)=1(클램프 — 숙달도 방향 힌트는 보장·정서 안전).
        assert (
            decide_hint_level(
                student_input="네, 해볼게요",
                turn_count=1,
                prev_hint_level=1,
                mastery_level="숙달",
            )
            == 1
        )

    def test_master_demand_prev3_lowered_to_3(self) -> None:
        # 답요구 prev=3: base min(4,4)=4 → 3(전체풀이 안전망 회피).
        assert (
            decide_hint_level(
                student_input="답 알려줘",
                turn_count=1,
                prev_hint_level=3,
                mastery_level="숙달",
            )
            == 3
        )

    @pytest.mark.parametrize("level", [None, "발전 중"])
    def test_neutral_levels_unchanged(self, level: MasteryLevel | None) -> None:
        # 발전중·None은 조정 안 함(답요구 prev=1 → 2) — 하위호환(숙달/초보만 조정).
        assert (
            decide_hint_level(
                student_input="답 알려줘",
                turn_count=1,
                prev_hint_level=1,
                mastery_level=level,
            )
            == 2
        )

    def test_novice_demand_raised_to_3(self) -> None:
        # slice 77: 답요구 prev=1 → base 2 → 초보 min(4, 2+1)=3(세분화·숙달의 대칭).
        assert (
            decide_hint_level(
                student_input="답 알려줘",
                turn_count=1,
                prev_hint_level=1,
                mastery_level="초보",
            )
            == 3
        )

    def test_novice_neutral_raised_to_2(self) -> None:
        # slice 77: 중립 base 1 → 초보 min(4, 2)=2(능력 낮음 → 한 단계 구체화).
        assert (
            decide_hint_level(
                student_input="네, 해볼게요",
                turn_count=1,
                prev_hint_level=1,
                mastery_level="초보",
            )
            == 2
        )

    def test_novice_stuck_capped_at_4(self) -> None:
        # slice 77: 5회+ 막힘 prev=3 → base 3 → 초보 min(4, 4)=4(클램프 — 전체풀이 상한).
        assert (
            decide_hint_level(
                student_input="음...",
                turn_count=5,
                prev_hint_level=3,
                mastery_level="초보",
            )
            == 4
        )

    def test_omitted_mastery_arg_unchanged(self) -> None:
        # mastery_level 인자 생략 → 기존 동작(기본 None).
        assert decide_hint_level(student_input="답 알려줘", turn_count=1, prev_hint_level=1) == 2


class TestCeilingGuarantee:
    """PED-35 규칙 6 — 5회+ 막힘 상한(레벨 3)이 숙달 완화(규칙 5)로 깎이지 않음을 보장.

    `test_master_stuck_ceiling_guaranteed_at_3`(단일 호출)의 변별력을 다각도로 확장:
    turn 경계(4 vs 5)·연속 턴 피드백 고착 재현·상한이 3이지 4가 아님(즉답 아님)을 각각 고정.
    """

    def test_ceiling_does_not_apply_below_threshold(self) -> None:
        # turn_count=4(임계 미만)면 규칙 6이 개입하지 않음 — 중립 신호는 그대로 1.
        assert (
            decide_hint_level(
                student_input="음...",
                turn_count=4,
                prev_hint_level=1,
                mastery_level="숙달",
            )
            == 1
        )

    def test_ceiling_holds_across_consecutive_stuck_turns(self) -> None:
        # 구 버전(규칙 5까지만)의 실측 갭 재현: '숙달' 학생이 매 턴 좌절 신호를 내며 prev를
        # 그대로 피드백받으면 turn_count≥5부터 고정점이 2에서 벗어나지 못했다. 규칙 6 적용
        # 후에는 turn 5부터 3에 도달하고 이후 턴에도 3에서 유지된다(퇴행 없음).
        prev: int | None = None
        levels: list[int] = []
        for turn in range(1, 8):
            level = decide_hint_level(
                student_input="막혔어",
                turn_count=turn,
                prev_hint_level=prev,
                mastery_level="숙달",
            )
            levels.append(level)
            prev = level
        # turn 1~4(임계 미달): 좌절 신호 점진 상승(규칙 3, min(4,prev+1))도 숙달 완화(규칙
        # 5, max(1,base-1))에 매 턴 상쇄돼 prev=1이 고정점 — 규칙 6은 아직 개입 안 함.
        assert levels[:4] == [1, 1, 1, 1]
        # turn 5부터: 규칙 1이 base=max(prev,3)로 3을 만들어도 규칙 5가 다시 2로 깎는다 —
        # 규칙 6이 없던 구 버전은 여기서 2가 새 고정점이 돼 영영 3에 도달하지 못했다.
        # 규칙 6 적용 후에는 turn 5부터 3에 도달하고 이후 턴에도 3에서 유지된다(퇴행 없음).
        assert levels[4:] == [3, 3, 3]

    def test_ceiling_caps_at_3_not_4_even_with_demand_signal(self) -> None:
        # 규칙 6은 "즉답(4)까지 허용"이 아니라 "부분 풀이(3) 도달 보장"이다 — 5회+ 막힘이
        # 답 요구 신호보다 우선(TestPriorityOrder)이므로 여기서도 상한은 3에서 멈춘다.
        assert (
            decide_hint_level(
                student_input="답 알려줘",
                turn_count=5,
                prev_hint_level=1,
                mastery_level="숙달",
            )
            == 3
        )

    def test_ceiling_no_effect_on_non_mastery_students(self) -> None:
        # 숙달 완화가 없는 학생(발전중/None/초보)은 애초에 규칙 5에서 깎이지 않으므로
        # 규칙 6은 항등(no-op) — 회귀 없음을 명시적으로 고정.
        for level in (None, "발전 중", "초보"):
            assert (
                decide_hint_level(
                    student_input="음...",
                    turn_count=5,
                    prev_hint_level=1,
                    mastery_level=level,  # type: ignore[arg-type]
                )
                >= 3
            )


class TestCeilingReachedTelemetryHook:
    """PED-35 acceptance③ — `is_ceiling_reached` 순수 훅("작동한 비율" 집계용)."""

    def test_reached_when_stuck_and_level_at_least_3(self) -> None:
        assert is_ceiling_reached(hint_level=3, turn_count=5) is True
        assert is_ceiling_reached(hint_level=4, turn_count=6) is True

    def test_not_reached_when_stuck_but_level_below_3(self) -> None:
        # 규칙 6이 무력화된(가정) 경우를 재현 — 막힘 상태인데 레벨이 3 미달.
        assert is_ceiling_reached(hint_level=2, turn_count=5) is False

    def test_not_reached_when_not_stuck_even_if_level_high(self) -> None:
        # 막힘 임계 미달이면 상한 보장 자체가 무관 — 레벨이 높아도 "도달" 집계 대상 아님.
        assert is_ceiling_reached(hint_level=4, turn_count=1) is False

    def test_matches_decide_hint_level_real_output(self) -> None:
        # 실제 decide_hint_level 출력과 조합해도 일관됨(정본화가 재계산이 아니라 재사용임을 확인).
        level = decide_hint_level(
            student_input="음...", turn_count=5, prev_hint_level=1, mastery_level="숙달"
        )
        assert is_ceiling_reached(hint_level=level, turn_count=5) is True
