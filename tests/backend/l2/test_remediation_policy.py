"""MISC-30 보정 정책 — 반복 오류 사다리·하한·경계 동결 + 경로 어휘 재등장 금지 (hermetic·순수).

이 파일이 지키는 것은 다섯이다.

① **사다리**(계획서 §9 반복 실패 정책) — `≥2 교정설명` / `≥3 쉬운문제` / `≥4 선수개념`.
② **경계 접촉** — 각 칸마다 *바로 아래·정확히* 픽스처를 둔다. 경계를 한 칸 옮기는 뮤테이션이
   RED가 나지 않으면 그 픽스처는 경계를 밟지 않은 것이다
   (CLAUDE.md "픽스처가 그 절을 실제로 밟는가" — 2026-09-07 2회차 규칙).
③ **경계 이동 뮤테이션**(§P-09 항목 5·완료 판정) — ②를 주장으로 두지 않고 *스위트 안에서*
   사다리 세 경계를 한 칸씩 양방향으로 옮겨 판정이 실제로 뒤집히는지 잰다. 주입이
   적용됐는지도 함께 단언한다(mutated != original — "주입 자체의 실재" 규칙).
④ **표의 임계 전량** — 하한 0.7과 사다리 (4,3,2)를 리터럴로 고정한다.
⑤ **경로 어휘 재등장 금지(EOS-138 ③)** — 이 모듈은 오답 직후 경로 순서를 선언하지 않는다.
   정본은 `l2/learning_state_policy.V1_RULES` 하나이며, 두 번째 순서 선언이 되살아나면
   `TestNoRouteVocabulary`가 RED를 낸다.

하한(0.7) **경계**의 접촉·이동 뮤테이션은 이 표가 아니라 그 하한을 실제로 비교하는 곳에서 잰다
— R3 입력 필터 `tests/backend/l2/test_learning_state_evidence.py`, 추천 안전장치
`tests/backend/l2/test_learning_state_recommendation.py`. (종전 경로 표 RT2가 쓰던 경계 테스트는
경로 표와 함께 삭제됐다.)

DB·상위 계층 의존 0 — 전부 순수 함수다.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import re

import pytest

from whymath_backend.l2 import remediation_policy
from whymath_backend.l2.remediation_policy import (
    MISCONCEPTION_REMEDIATION_FLOOR,
    REMEDIATION_POLICY_V1,
    EscalationRung,
    RemediationPolicyTable,
    select_rung,
)


# ══════════════════════════════════════════════════════════════════════════
# ① 사다리 + ② 경계 접촉 (반복 축)
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
# ③ 경계 이동 뮤테이션 — ②가 실제로 경계를 밟는지 스위트 안에서 잰다
# ══════════════════════════════════════════════════════════════════════════
class TestBoundaryShiftMutationsAreDetected:
    """사다리 세 경계를 한 칸씩 양방향으로 옮겨 **그 경계 픽스처의 판정이 뒤집히는지** 잰다.

    이것이 완료 판정("경계 이동 뮤테이션이 RED다")의 스위트 내 집행이다. 각 케이스는
    ①주입이 실제로 적용됐는지(원본 != 뮤테이션) ②그 결과 판정이 바뀌는지를 함께 단언한다 —
    주입이 조용히 실패하면 "안 바뀐다"가 "가드가 없다"처럼 보이기 때문이다.
    """

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
# ④ 표의 임계 전량
# ══════════════════════════════════════════════════════════════════════════
class TestThresholdTable:
    def test_no_threshold_literal_outside_the_table(self) -> None:
        """표가 아는 임계의 전량 목록 — 개수가 늘면 이 테스트를 먼저 고치게 된다."""
        assert REMEDIATION_POLICY_V1.misconception_remediation_floor == 0.7
        assert REMEDIATION_POLICY_V1.escalation_ladder == (
            (4, EscalationRung.PREREQUISITE_CONCEPT),
            (3, EscalationRung.EASIER_PROBLEM),
            (2, EscalationRung.CORRECTIVE_EXPLANATION),
        )

    def test_floor_constant_and_table_field_are_the_same_value(self) -> None:
        """소비처(R3 필터·추천 안전장치)는 모듈 상수를 읽는다 — 표 필드와 갈라지면 안 된다."""
        assert MISCONCEPTION_REMEDIATION_FLOOR == 0.7
        assert (
            REMEDIATION_POLICY_V1.misconception_remediation_floor == MISCONCEPTION_REMEDIATION_FLOOR
        )


# ══════════════════════════════════════════════════════════════════════════
# ⑤ 경로 어휘 재등장 금지 — EOS-138 ③
# ══════════════════════════════════════════════════════════════════════════
#: EOS-138 ③이 삭제한 경로 표의 심볼 전량. 하나라도 되살아나면 "오답 직후 무엇을 먼저 보정하나"의
#: 진실 원천이 다시 둘이 된다(상태 머신 R3 > R4 ↔ 경로 표 RT1 > RT2).
_REMOVED_ROUTE_SYMBOLS = (
    "select_route",
    "V1_ROUTE_RULES",
    "RouteRule",
    "RemediationRoute",
    "RemediationSignals",
    "RemediationDecision",
    "decide_remediation",
    "RemediationPolicy",
)

#: 공개 표면의 정본 — 추가하려면 이 목록과 함께 판정 근거를 남긴다.
_EXPECTED_PUBLIC = {
    "MISCONCEPTION_REMEDIATION_FLOOR",
    "REMEDIATION_POLICY_V1",
    "EscalationRung",
    "RemediationPolicyTable",
    "select_rung",
}

#: 이름에 경로 어휘가 든 최상위 정의를 잡는다 — 삭제 목록의 *정확한 이름*만 막으면 `choose_route`
#: 같은 개명 부활이 통과한다(CLAUDE.md "금지 패턴 열거 대신 산출물 검사").
_ROUTE_NAME = re.compile(r"route", re.IGNORECASE)


class TestNoRouteVocabulary:
    """이 모듈은 경로 순서를 정의·export하지 않는다 — 정본은 `learning_state_policy.V1_RULES`."""

    @pytest.mark.parametrize("name", _REMOVED_ROUTE_SYMBOLS)
    def test_removed_route_symbol_is_absent(self, name: str) -> None:
        assert not hasattr(remediation_policy, name), (
            f"`{name}`가 되살아났다 — 경로 순서의 정본은 상태 머신 하나다(EOS-138 ③ 판정문 "
            "`docs/reviews/eos138_r3_input_scope_and_route_order_judgment_2026-09-28.md`)."
        )

    def test_public_surface_is_exactly_the_ladder_and_floor(self) -> None:
        assert set(remediation_policy.__all__) == _EXPECTED_PUBLIC

    def test_no_top_level_definition_is_named_after_a_route(self) -> None:
        """구성된 결과(AST)를 본다 — 최상위 def·class·대입 이름 전수."""
        tree = ast.parse(inspect.getsource(remediation_policy))
        names: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                names.append(node.name)
            elif isinstance(node, ast.Assign):
                names.extend(t.id for t in node.targets if isinstance(t, ast.Name))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names.append(node.target.id)
        # 스캔 0건은 실패다 — 대상을 못 찾은 전수 가드는 공허하게 통과한다.
        assert "select_rung" in names and "EscalationRung" in names, names
        offenders = [n for n in names if _ROUTE_NAME.search(n)]
        assert offenders == [], f"경로 어휘 정의가 생겼다: {offenders}"

    def test_module_no_longer_imports_the_mastery_band_contract(self) -> None:
        """숙달 구간 판정(`select_reason_type`)은 경로 표만을 위해 import됐었다.

        그 import가 돌아오면 이 모듈이 다시 숙달 축으로 경로를 고르려는 것이다.
        """
        tree = ast.parse(inspect.getsource(remediation_policy))
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        assert "whymath_backend.l2.recommendation_contract" not in imported, imported
