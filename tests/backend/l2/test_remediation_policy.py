"""MISC-30 보정 정책 — 경로 표·반복 오류 사다리·경계 동결 (hermetic·순수).

이 파일이 지키는 것은 다섯이다.

① **경로 규칙**(계획서 §9 기본 정책) — `<0.4 선수` / `오개념>0.7 교정` / `0.4~0.7 연습` /
   `>0.7 다음`. 선언 순서가 곧 우선순위라는 것까지 못 박는다.
② **사다리**(계획서 §9 반복 실패 정책) — `≥2 교정설명` / `≥3 쉬운문제` / `≥4 선수개념`.
③ **경계 접촉** — 각 임계마다 *바로 아래·정확히·바로 위* 세 픽스처를 둔다. 경계를 한 칸
   옮기는 뮤테이션이 RED가 나지 않으면 그 픽스처는 경계를 밟지 않은 것이다
   (CLAUDE.md "픽스처가 그 절을 실제로 밟는가" — 2026-09-07 2회차 규칙).
④ **경계 이동 뮤테이션**(§P-09 항목 5·완료 판정) — ③을 주장으로 두지 않고 *스위트 안에서*
   5개 경계를 한 칸씩 양방향으로 옮겨, 그 경계 픽스처의 판정이 실제로 뒤집히는지 잰다.
   주입이 적용됐는지도 함께 단언한다(mutated != original — "주입 자체의 실재" 규칙).
⑤ **임계 단일 진실 원천** — 표의 숙달 미러가 `recommendation_contract`의 정본과 같은가.
   갈라지면 "약한 개념"의 정의가 모듈마다 달라진다.

DB·상위 계층 의존 0 — 전부 순수 함수다.
"""

from __future__ import annotations

import dataclasses
import typing

import pytest

from whymath_backend.l2 import recommendation_contract
from whymath_backend.l2.recommendation_contract import (
    PREREQUISITE_MASTERY_CEILING,
    WEAK_CONCEPT_MASTERY_CEILING,
)
from whymath_backend.l2.remediation_policy import (
    REMEDIATION_POLICY_V1,
    V1_ROUTE_RULES,
    EscalationRung,
    RemediationDecision,
    RemediationPolicy,
    RemediationPolicyTable,
    RemediationRoute,
    RemediationSignals,
    decide_remediation,
    select_route,
    select_rung,
)

#: 경계에서 "한 칸"의 크기. 경계값과 이 폭만큼 떨어진 두 점이 서로 다른 판정을 내야 한다.
_NOTCH = 0.01


def _route(
    mastery: float | None = None,
    misconception_confidence: float | None = None,
    policy: RemediationPolicyTable = REMEDIATION_POLICY_V1,
) -> RemediationRoute:
    """경로만 꺼내는 헬퍼 — 픽스처를 신호 조립 잡음 없이 읽게 한다."""
    return select_route(
        RemediationSignals(mastery=mastery, misconception_confidence=misconception_confidence),
        policy,
    )[0]


# ══════════════════════════════════════════════════════════════════════════
# ① 경로 규칙 + ③ 경계 접촉 (숙달 축)
# ══════════════════════════════════════════════════════════════════════════
class TestMasteryRouteBoundaries:
    """숙달 0.4·0.7 경계 — 각각 바로 아래·정확히·바로 위."""

    # 값은 **리터럴로** 적는다. `PREREQUISITE_MASTERY_CEILING - _NOTCH`처럼 상수에서 파생하면
    # 경계가 옮겨질 때 픽스처도 같이 옮겨져 *어떤 경계 이동도 검출하지 못한다* — 실측으로
    # 뮤테이션 4종(0.4·0.7 각 ±1칸)이 통째로 생존했다(2026-09-18). 리터럴이라야 픽스처가
    # 경계를 붙잡는다. 상수와 리터럴의 일치는 `TestThresholdSingleSource`가 따로 잰다.
    @pytest.mark.parametrize(
        ("mastery", "expected"),
        [
            # ── 0.4 경계: 미만이라야 선수, 0.4 자신은 연습 구간이다 ──
            (0.0, RemediationRoute.PREREQUISITE_CONCEPT),
            (0.39, RemediationRoute.PREREQUISITE_CONCEPT),
            (0.40, RemediationRoute.SAME_CONCEPT_PRACTICE),
            (0.41, RemediationRoute.SAME_CONCEPT_PRACTICE),
            # ── 0.7 경계: 0.7 자신은 아직 연습, *초과*라야 다음 개념 ──
            (0.69, RemediationRoute.SAME_CONCEPT_PRACTICE),
            (0.70, RemediationRoute.SAME_CONCEPT_PRACTICE),
            (0.71, RemediationRoute.NEXT_CONCEPT),
            (1.0, RemediationRoute.NEXT_CONCEPT),
        ],
    )
    def test_mastery_band_routes(self, mastery: float, expected: RemediationRoute) -> None:
        assert _route(mastery=mastery) is expected

    def test_unmeasured_mastery_is_not_a_prerequisite_gap(self) -> None:
        """미측정을 0.0으로 접으면 신규 학생이 전부 "선수가 막혔다"가 된다."""
        assert _route(mastery=None) is RemediationRoute.UNMEASURED
        assert _route(mastery=0.0) is RemediationRoute.PREREQUISITE_CONCEPT


# ══════════════════════════════════════════════════════════════════════════
# ① 경로 규칙 + ③ 경계 접촉 (오개념 축)
# ══════════════════════════════════════════════════════════════════════════
class TestMisconceptionRouteBoundary:
    """오개념 신뢰 0.7 경계 — **초과**라야 교정 경로다."""

    @pytest.mark.parametrize(
        ("confidence", "expected"),
        [
            (0.69, RemediationRoute.UNMEASURED),
            (0.70, RemediationRoute.UNMEASURED),
            (0.71, RemediationRoute.MISCONCEPTION_REMEDIATION),
            (1.0, RemediationRoute.MISCONCEPTION_REMEDIATION),
        ],
    )
    def test_confidence_boundary(self, confidence: float, expected: RemediationRoute) -> None:
        """숙달이 없는 상태에서 오개념 축만으로 경로가 갈리는지 본다.

        하한 이하가 `UNMEASURED`인 것은 의도다 — 숙달도 없고 오개념도 약하면 경로를
        말할 근거가 없다. 연습으로 접으면 근거 없음이 근거로 위장된다.
        """
        assert _route(misconception_confidence=confidence) is expected

    def test_misconception_does_not_outrank_prerequisite_gap(self) -> None:
        """선언 순서 = 우선순위. 바닥이 무너진 학생에게 교정 설명은 딛고 설 곳이 없다."""
        assert (
            _route(mastery=0.1, misconception_confidence=1.0)
            is RemediationRoute.PREREQUISITE_CONCEPT
        )

    def test_misconception_outranks_practice_and_next(self) -> None:
        """연습·다음 개념보다는 앞선다 — 잘못 알고 있는 것은 연습으로 지워지지 않는다."""
        for mastery in (0.5, 0.95):
            assert (
                _route(mastery=mastery, misconception_confidence=0.9)
                is RemediationRoute.MISCONCEPTION_REMEDIATION
            )


# ══════════════════════════════════════════════════════════════════════════
# ② 사다리 + ③ 경계 접촉 (반복 축)
# ══════════════════════════════════════════════════════════════════════════
class TestEscalationLadderBoundaries:
    """2·3·4회 경계 — 각 칸의 바로 아래와 정확히 그 값."""

    @pytest.mark.parametrize(
        ("count", "expected"),
        [
            (0, EscalationRung.NONE),
            (1, EscalationRung.NONE),  # 2의 바로 아래
            (2, EscalationRung.CORRECTIVE_EXPLANATION),  # 2 정확히
            (3, EscalationRung.EASIER_PROBLEM),  # 3 정확히(=2 칸의 바로 위)
            (4, EscalationRung.PREREQUISITE_CONCEPT),  # 4 정확히(=3 칸의 바로 위)
            (5, EscalationRung.PREREQUISITE_CONCEPT),  # 최상단은 포화한다
            (99, EscalationRung.PREREQUISITE_CONCEPT),
        ],
    )
    def test_rung_by_count(self, count: int, expected: EscalationRung) -> None:
        assert select_rung(count) is expected

    def test_monotonic_non_decreasing(self) -> None:
        """강도는 반복이 늘 때 내려가지 않는다 — 표가 어긋나면 여기서 잡힌다."""
        order = [
            EscalationRung.NONE,
            EscalationRung.CORRECTIVE_EXPLANATION,
            EscalationRung.EASIER_PROBLEM,
            EscalationRung.PREREQUISITE_CONCEPT,
        ]
        ranks = [order.index(select_rung(n)) for n in range(0, 8)]
        assert ranks == sorted(ranks)

    def test_negative_count_is_rejected(self) -> None:
        """음수는 조용히 NONE으로 접지 않는다 — 카운터가 망가진 신호다."""
        with pytest.raises(ValueError, match="0 이상"):
            select_rung(-1)


# ══════════════════════════════════════════════════════════════════════════
# ④ 경계 이동 뮤테이션 — ③이 실제로 경계를 밟는지 스위트 안에서 잰다
# ══════════════════════════════════════════════════════════════════════════
class TestBoundaryShiftMutationsAreDetected:
    """5개 경계를 한 칸씩 양방향으로 옮겨 **그 경계 픽스처의 판정이 뒤집히는지** 잰다.

    이것이 완료 판정("경계 이동 뮤테이션이 RED다")의 스위트 내 집행이다. 각 케이스는
    ①주입이 실제로 적용됐는지(원본 != 뮤테이션) ②그 결과 판정이 바뀌는지를 함께 단언한다 —
    주입이 조용히 실패하면 "안 바뀐다"가 "가드가 없다"처럼 보이기 때문이다.
    """

    # ── 숙달 축: 상수가 모듈 전역이므로 monkeypatch로 옮긴다 ──
    @pytest.mark.parametrize("shift", [+_NOTCH, -_NOTCH])
    def test_prerequisite_ceiling_shift_flips_a_fixture(
        self, monkeypatch: pytest.MonkeyPatch, shift: float
    ) -> None:
        original = PREREQUISITE_MASTERY_CEILING
        probe = original + shift / 2  # 원본과 뮤테이션 사이에 놓인 점
        before = _route(mastery=probe)

        mutated = original + shift
        assert mutated != original, "뮤테이션 미적용 — 아래 판정은 무의미하다."
        monkeypatch.setattr(recommendation_contract, "PREREQUISITE_MASTERY_CEILING", mutated)

        assert _route(mastery=probe) is not before

    @pytest.mark.parametrize("shift", [+_NOTCH, -_NOTCH])
    def test_weak_concept_ceiling_shift_flips_a_fixture(
        self, monkeypatch: pytest.MonkeyPatch, shift: float
    ) -> None:
        original = WEAK_CONCEPT_MASTERY_CEILING
        probe = original + shift / 2
        before = _route(mastery=probe)

        mutated = original + shift
        assert mutated != original, "뮤테이션 미적용 — 아래 판정은 무의미하다."
        monkeypatch.setattr(recommendation_contract, "WEAK_CONCEPT_MASTERY_CEILING", mutated)

        assert _route(mastery=probe) is not before

    # ── 오개념 축: 표가 주입 가능하므로 표를 바꿔 넣는다 ──
    @pytest.mark.parametrize("shift", [+_NOTCH, -_NOTCH])
    def test_misconception_floor_shift_flips_a_fixture(self, shift: float) -> None:
        original = REMEDIATION_POLICY_V1.misconception_remediation_floor
        probe = original + shift / 2
        before = _route(misconception_confidence=probe)

        mutated_table = RemediationPolicyTable(misconception_remediation_floor=original + shift)
        assert (
            mutated_table.misconception_remediation_floor
            != REMEDIATION_POLICY_V1.misconception_remediation_floor
        ), "뮤테이션 미적용 — 아래 판정은 무의미하다."

        assert _route(misconception_confidence=probe, policy=mutated_table) is not before

    # ── 반복 축: 사다리 전체를 ±1 옮기고 **세 경계 각각**에서 판정이 뒤집히는지 본다 ──
    #
    # 한 칸만 옮기지 않는 이유: (4,3,2)에서 4를 -1 하면 3과 겹치고 2를 +1 해도 3과 겹쳐
    # 표 불변식(중복 금지·내림차순)이 **생성 단계에서 거부**한다. 그 거부 자체는 아래
    # `TestPolicyTableInvariants`가 따로 잰다. 여기서 재는 것은 "각 경계 픽스처가 그
    # 경계를 실제로 밟는가"이고, 전체 이동은 세 경계를 동시에 한 칸씩 옮기므로 그 질문에
    # 정확히 답한다(경계마다 probe가 다르고, 세 probe가 전부 뒤집혀야 통과한다).
    @pytest.mark.parametrize("rung_index", [0, 1, 2])
    @pytest.mark.parametrize("shift", [+1, -1])
    def test_ladder_shift_flips_each_boundary_fixture(self, rung_index: int, shift: int) -> None:
        """`shift=-1`이면 *경계 바로 아래* 횟수가, `+1`이면 *경계 정확히*가 영향을 받는다."""
        ladder = REMEDIATION_POLICY_V1.escalation_ladder
        minimum = ladder[rung_index][0]
        probe = minimum - 1 if shift < 0 else minimum
        before = select_rung(probe)

        mutated_table = RemediationPolicyTable(
            escalation_ladder=tuple((count + shift, rung) for count, rung in ladder)
        )
        assert (
            mutated_table.escalation_ladder != ladder
        ), "뮤테이션 미적용 — 아래 판정은 무의미하다."

        assert select_rung(probe, mutated_table) is not before


# ══════════════════════════════════════════════════════════════════════════
# 표 자신의 불변식 — 깨진 표를 조용히 고쳐 주지 않는다
# ══════════════════════════════════════════════════════════════════════════
class TestPolicyTableInvariants:
    def test_ascending_ladder_is_rejected(self) -> None:
        """오름차순이면 4회 학생이 2회 칸에 걸린다 — 정렬해 주지 않고 거부한다."""
        with pytest.raises(ValueError, match="내림차순"):
            RemediationPolicyTable(
                escalation_ladder=(
                    (2, EscalationRung.CORRECTIVE_EXPLANATION),
                    (4, EscalationRung.PREREQUISITE_CONCEPT),
                )
            )

    def test_empty_ladder_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="비어 있"):
            RemediationPolicyTable(escalation_ladder=())

    def test_duplicate_counts_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="중복"):
            RemediationPolicyTable(
                escalation_ladder=(
                    (2, EscalationRung.EASIER_PROBLEM),
                    (2, EscalationRung.CORRECTIVE_EXPLANATION),
                )
            )

    def test_zero_minimum_is_rejected(self) -> None:
        """0이면 반복이 없는 학생도 강도가 올라간다 — 사다리가 아니라 상시 개입이다."""
        with pytest.raises(ValueError, match="1 이상"):
            RemediationPolicyTable(escalation_ladder=((0, EscalationRung.CORRECTIVE_EXPLANATION),))

    def test_table_is_frozen(self) -> None:
        """표가 런타임에 바뀌면 "정책이 한 곳에 있다"가 무너진다."""
        with pytest.raises(dataclasses.FrozenInstanceError):
            REMEDIATION_POLICY_V1.misconception_remediation_floor = 0.9  # type: ignore[misc]


# ══════════════════════════════════════════════════════════════════════════
# ⑤ 임계 단일 진실 원천
# ══════════════════════════════════════════════════════════════════════════
class TestThresholdSingleSource:
    def test_mastery_mirrors_match_the_canonical_constants(self) -> None:
        """표의 숙달 두 값은 **미러**다 — 원본과 갈라지면 읽는 사람이 속는다."""
        assert REMEDIATION_POLICY_V1.prerequisite_mastery_ceiling == PREREQUISITE_MASTERY_CEILING
        assert REMEDIATION_POLICY_V1.weak_concept_mastery_ceiling == WEAK_CONCEPT_MASTERY_CEILING

    def test_canonical_mastery_constants_are_pinned_to_their_values(self) -> None:
        """상수 **자체**의 값을 못 박는다.

        위 미러 대조만 두면 원본과 미러가 *함께* 움직일 때 아무도 눈치채지 못한다 — 실측으로
        0.4·0.7을 각각 ±0.01 옮긴 뮤테이션 4종이 전부 생존했다(2026-09-18). 계획서 §9가
        정한 값이 바뀌면 여기가 먼저 RED가 나고, 그때 바꾸는 사람이 이 줄을 함께 고친다.
        """
        assert PREREQUISITE_MASTERY_CEILING == 0.4
        assert WEAK_CONCEPT_MASTERY_CEILING == 0.7

    def test_mastery_routing_delegates_instead_of_reimplementing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """숙달 분기의 권위는 `select_reason_type` 하나다.

        미러 필드만 옮기고 정본을 그대로 두면 판정은 **바뀌지 않아야** 한다. 바뀐다면 이
        모듈이 비교를 재구현했다는 뜻이고, 그 순간 진실 원천이 둘이 된다.
        """
        probe = PREREQUISITE_MASTERY_CEILING - _NOTCH
        before = _route(mastery=probe)
        mirrored_only = RemediationPolicyTable(
            prerequisite_mastery_ceiling=PREREQUISITE_MASTERY_CEILING - 0.3,
            weak_concept_mastery_ceiling=WEAK_CONCEPT_MASTERY_CEILING + 0.2,
        )
        assert _route(mastery=probe, policy=mirrored_only) is before

    def test_no_threshold_literal_outside_the_table(self) -> None:
        """표가 아는 임계의 전량 목록 — 개수가 늘면 이 테스트를 먼저 고치게 된다."""
        assert REMEDIATION_POLICY_V1.misconception_remediation_floor == 0.7
        assert REMEDIATION_POLICY_V1.escalation_ladder == (
            (4, EscalationRung.PREREQUISITE_CONCEPT),
            (3, EscalationRung.EASIER_PROBLEM),
            (2, EscalationRung.CORRECTIVE_EXPLANATION),
        )


# ══════════════════════════════════════════════════════════════════════════
# 호출 계약 — 교체 가능성을 타입으로 표현했는가
# ══════════════════════════════════════════════════════════════════════════
class TestPolicyContract:
    def test_route_and_rung_are_orthogonal(self) -> None:
        """경로와 강도는 서로 다른 신호를 읽는다 — 한쪽이 다른 쪽을 덮어쓰지 않는다."""
        decision = decide_remediation(
            RemediationSignals(mastery=0.9, misconception_confidence=0.1, same_error_count=4)
        )
        assert decision.route is RemediationRoute.NEXT_CONCEPT
        assert decision.rung is EscalationRung.PREREQUISITE_CONCEPT

    def test_decision_always_names_the_deciding_rule(self) -> None:
        """규칙 id가 없으면 "왜 이 경로인가"도 "얼마나 발동했나"도 셀 수 없다."""
        for signals in (
            RemediationSignals(),
            RemediationSignals(mastery=0.2),
            RemediationSignals(misconception_confidence=0.95),
            RemediationSignals(mastery=0.5, same_error_count=3),
        ):
            assert decide_remediation(signals).rule_id

    def test_every_rule_id_is_unique_and_reachable(self) -> None:
        """규칙 목록이 곧 "이 정책이 무엇을 아는가"의 전량이다.

        기대 id를 `V1_ROUTE_RULES`에서 뽑아 쓰면 이름을 바꿔도 양쪽이 함께 움직여 통과한다
        (자기참조 단언). 그래서 **리터럴로** 적는다 — 규칙을 더하거나 지우면 여기가 RED다.
        """
        ids = [rule.rule_id for rule in V1_ROUTE_RULES]
        assert ids == [
            "RT1-prerequisite-gap",
            "RT2-misconception",
            "RT3-current-concept",
            "RT4-next-concept",
        ]
        reached = {decide_remediation(s).rule_id for s in _REACHING_SIGNALS}
        assert reached == set(ids) | {"RT0-unmeasured"}

    def test_default_policy_satisfies_the_protocol(self) -> None:
        """v1 구현이 교체 계약을 실제로 만족하는가 — Protocol이 표류하지 않게."""
        policy: RemediationPolicy = decide_remediation
        assert isinstance(policy(RemediationSignals(mastery=0.5)), RemediationDecision)

    def test_protocol_signature_is_frozen(self) -> None:
        """BKT/DKT/LLM으로 갈아도 유지돼야 하는 모양 — 인자는 신호 하나뿐이다."""
        hints = typing.get_type_hints(RemediationPolicy.__call__)
        assert hints["signals"] is RemediationSignals
        assert hints["return"] is RemediationDecision


#: 규칙 전량 도달을 보이는 최소 신호 집합(위 테스트가 읽는다).
_REACHING_SIGNALS = (
    RemediationSignals(mastery=0.1),  # RT1
    RemediationSignals(misconception_confidence=0.95),  # RT2
    RemediationSignals(mastery=0.5),  # RT3
    RemediationSignals(mastery=0.95),  # RT4
    RemediationSignals(),  # RT0
)
