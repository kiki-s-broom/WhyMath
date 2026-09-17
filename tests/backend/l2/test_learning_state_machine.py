"""EOS-105 학습 상태 머신 — 전이표·거부·정책 규칙 (hermetic·DB 없이).

검증 축 6개:
  ① **전이가 데이터다** — 판정 함수가 `ALLOWED_TRANSITIONS` 외의 어떤 분기도 쓰지 않는다.
     AST 전수 스캔으로 확인한다(주석 주장이 아니라 기계 판정). 이 축이 없으면 누군가
     `if from_state is NEW: return True` 한 줄을 넣어도 다른 모든 테스트가 초록이다.
  ② **미정의 전이가 RED다** — 64쌍(8×8) 전수에서 표에 있는 쌍만 통과하고 나머지는 전부
     `UndefinedTransitionError`. `NEW → ADVANCING`을 개별 사례로도 못 박는다(acceptance ②).
  ③ **규칙당 반례 1개** — 규칙 6종 각각에 대해 *그 규칙을 뺀 정책*을 실제로 만들어 돌려,
     결과가 달라지는(또는 예외가 되는) 입력이 픽스처에 있음을 확인한다. 픽스처가 그 규칙을
     한 번도 밟지 않으면 이 테스트가 실패한다(CLAUDE.md 2026-09-07 픽스처 접촉 규칙).
  ④ **미매치가 예외다** — 어떤 규칙도 매치 안 되면 기본값으로 넘어가지 않는다. 이 성질이
     ③의 변별력을 만든다(폴백이 있으면 규칙을 빼도 조용히 통과한다).
  ⑤ **적재는 판정을 통과한 것만** — 거부된 전이는 원장에 행을 남기지 않는다.
  ⑥ **거부가 표면에 드러난다** — `advance_on_attempt`가 거부를 삼키지 않고 값으로 돌려준다.

정책 규칙의 *의미* 검증(어떤 증거가 어떤 상태로 가는가)은 ③의 반례 픽스처가 겸한다 —
반례는 규칙의 동작을 먼저 고정하지 않으면 만들 수 없기 때문이다.
"""

from __future__ import annotations

import ast
import itertools
import pathlib
import uuid
from dataclasses import dataclass, field
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.l2.learning_state_machine import (
    INITIAL_STATE,
    advance_on_attempt,
    assert_transition_allowed,
    get_current_state,
    reconcile_state,
    record_transition,
)
from whymath_backend.l2.learning_state_policy import (
    V1_RULES,
    NoMatchingPolicyRuleError,
    PolicyRule,
    RuleBasedPolicyV1,
    default_policy,
)
from whymath_backend.schema.learning_state import (
    ALLOWED_TRANSITIONS,
    HIGH_CONFIDENCE_THRESHOLD,
    REPEATED_FAILURE_THRESHOLD,
    AttemptEvidence,
    LearningState,
    NextActionKind,
    PolicyDecision,
    TransitionTrigger,
    UndefinedTransitionError,
    allowed_targets,
    is_transition_allowed,
)

_UID = uuid.UUID("11111111-2222-3333-4444-555555555555")

_MACHINE_SOURCE = (
    pathlib.Path(__file__).resolve().parents[3]
    / "src"
    / "backend"
    / "whymath_backend"
    / "l2"
    / "learning_state_machine.py"
)
_TABLE_SOURCE = (
    pathlib.Path(__file__).resolve().parents[3]
    / "src"
    / "backend"
    / "whymath_backend"
    / "schema"
    / "learning_state.py"
)


# ──────────────────────────────────────────────────────────────────────────
# 가짜 세션 — 원장을 리스트로 흉내 낸다(DB 없이 적재·조회 의미를 검증)
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class _FakeResult:
    """`session.execute()`의 반환 흉내."""

    rows: list[Any]

    def scalar_one_or_none(self) -> Any:
        return self.rows[0] if self.rows else None

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[Any]:
        return list(self.rows)


@dataclass
class _FakeSession:
    """원장 쓰기·현재 상태 읽기만 흉내 내는 최소 세션.

    실제 SQL을 돌리지 않으므로 `ORDER BY`·`OFFSET` 같은 쿼리 의미는 검증하지 않는다 —
    그 축은 통합 테스트(`test_learning_state_machine_integration.py`)가 맡는다. 여기서
    확인하는 것은 **판정→적재 순서**와 **거부 시 미적재**다.
    """

    added: list[Any] = field(default_factory=list)
    committed: int = 0

    async def execute(self, _stmt: Any) -> _FakeResult:
        # 현재 상태 조회 = 마지막으로 적재된 전이의 to_state.
        if not self.added:
            return _FakeResult(rows=[])
        return _FakeResult(rows=[self.added[-1].to_state])

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed += 1


def _session() -> AsyncSession:
    return cast(AsyncSession, _FakeSession())


async def _seed(session: AsyncSession, *states: LearningState) -> None:
    """원장에 상태 경로를 밀어 넣는다(전이표를 지키며)."""
    for state in states:
        await record_transition(
            session,
            user_id=_UID,
            to_state=state,
            trigger=TransitionTrigger.LEARNING_STARTED,
        )


# ──────────────────────────────────────────────────────────────────────────
# ① 전이가 데이터다 — 판정 함수에 상태 분기가 없다
# ──────────────────────────────────────────────────────────────────────────


def test_transition_verdict_reads_only_the_table_never_a_state_branch() -> None:
    """`is_transition_allowed`·`assert_transition_allowed` 본문에 상태 리터럴 분기가 없다.

    왜 AST인가: 문자열 검색은 표기 변형(`LearningState.NEW` vs 별칭 import vs `"NEW"`)에서
    뚫린다. 구성된 결과(AST 노드)를 본다(CLAUDE.md 2026-09-01 "금지 패턴 열거 대신 산출물 검사").

    이 가드가 없으면 판정 함수에 예외 분기 한 줄을 넣어도 다른 모든 테스트가 통과한다 —
    그 순간 전이표는 "허용 전이의 목록"이 아니라 "허용 전이 중 일부의 목록"이 된다.
    """
    tree = ast.parse(_TABLE_SOURCE.read_text(encoding="utf-8"))
    machine_tree = ast.parse(_MACHINE_SOURCE.read_text(encoding="utf-8"))

    verdict_fns = [
        node
        for node in itertools.chain(ast.walk(tree), ast.walk(machine_tree))
        if isinstance(node, ast.FunctionDef)
        and node.name in {"is_transition_allowed", "assert_transition_allowed"}
    ]
    # 스캔 0건은 실패다 — 함수명이 바뀌면 이 가드가 공허하게 통과한다
    # (CLAUDE.md 2026-09-01 축 ④ "스캔 0건은 실패").
    assert len(verdict_fns) == 2, f"판정 함수 2개를 찾지 못했습니다(실측 {len(verdict_fns)}개)"

    for fn in verdict_fns:
        for node in ast.walk(fn):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                assert node.value.id != "LearningState", (
                    f"{fn.name} 안에서 상태 리터럴 `LearningState.{node.attr}`를 참조합니다 — "
                    f"판정은 전이표만 읽어야 합니다."
                )


def test_transition_table_is_a_frozen_set_of_state_pairs() -> None:
    """전이표가 *데이터 구조*다 — 함수도, 조건식도 아니다."""
    assert isinstance(ALLOWED_TRANSITIONS, frozenset)
    for pair in ALLOWED_TRANSITIONS:
        assert isinstance(pair, tuple) and len(pair) == 2
        assert isinstance(pair[0], LearningState) and isinstance(pair[1], LearningState)


def test_every_state_is_reachable_from_new_through_the_table() -> None:
    """8상태 전부가 `NEW`에서 표를 따라 도달 가능하다 — 고아 상태 0.

    도달 불가 상태가 있으면 그 상태로 가는 코드는 영원히 죽은 코드이거나, 반대로 표에 빠진
    전이가 있다는 뜻이다. 둘 다 조용히 지나가면 안 된다.
    """
    reachable = {LearningState.NEW}
    frontier = [LearningState.NEW]
    while frontier:
        current = frontier.pop()
        for target in allowed_targets(current):
            if target not in reachable:
                reachable.add(target)
                frontier.append(target)
    assert reachable == set(LearningState), f"도달 불가 상태: {set(LearningState) - reachable}"


# ──────────────────────────────────────────────────────────────────────────
# ② 미정의 전이가 RED다
# ──────────────────────────────────────────────────────────────────────────


def test_new_to_advancing_is_rejected() -> None:
    """acceptance ②의 지정 사례 — 진단·학습 없는 진급은 거부된다."""
    with pytest.raises(UndefinedTransitionError) as excinfo:
        assert_transition_allowed(LearningState.NEW, LearningState.ADVANCING)
    # 메시지가 "무엇이 가능한가"를 말해야 호출부가 다음 행동을 안다.
    assert "NEW" in str(excinfo.value) and "ADVANCING" in str(excinfo.value)
    assert "DIAGNOSING" in str(excinfo.value)


@pytest.mark.parametrize(
    ("from_state", "to_state"),
    list(itertools.product(LearningState, LearningState)),
)
def test_exactly_the_declared_pairs_pass_and_all_others_raise(
    from_state: LearningState, to_state: LearningState
) -> None:
    """8×8=64쌍 전수 — 표에 있는 쌍만 통과하고 나머지는 전부 예외.

    전수이므로 표에 쌍을 하나 **더하면** 그 쌍의 케이스가 "예외여야 한다"에서 "통과해야
    한다"로 자동 이동한다. 즉 이 테스트는 표를 복제하지 않고 표를 *참조*한다 — 복제하면
    전이 규칙의 진실 원천이 셋(표·코드·테스트)이 된다.
    """
    declared = (from_state, to_state) in ALLOWED_TRANSITIONS
    assert is_transition_allowed(from_state, to_state) is declared

    if declared:
        assert_transition_allowed(from_state, to_state)  # 예외 없음
    else:
        with pytest.raises(UndefinedTransitionError):
            assert_transition_allowed(from_state, to_state)


def test_no_self_loop_is_allowed_unless_declared() -> None:
    """자기 전이는 *선언된 것만* 허용된다 — 전부 허용도, 전부 금지도 아니다.

    "같은 상태로의 전이는 언제나 무해하다"는 흔한 가정을 막는다: `NEW → NEW`가 허용되면
    아무 일도 없는 전이가 원장을 채우고 "왜 이 상태인가"의 이력이 희석된다.
    """
    declared_self_loops = {s for s in LearningState if (s, s) in ALLOWED_TRANSITIONS}
    assert declared_self_loops == {LearningState.PRACTICING, LearningState.ASSESSING}


# ──────────────────────────────────────────────────────────────────────────
# ③④ 규칙당 반례 1개 + 미매치 예외
# ──────────────────────────────────────────────────────────────────────────

# 규칙 id → "이 규칙이 없으면 통과해 버리는 입력"
#
# 각 픽스처는 **그 규칙이 실제로 이기는** 입력이어야 하며(먼저 선언된 규칙에 가로채이면
# 그 규칙을 한 번도 밟지 못한다), 동시에 **그 규칙을 빼면 결과가 달라지는** 입력이어야 한다.
# 두 조건을 아래 테스트가 각각 단언한다 — 이름이 의도를 말한다고 코드가 그 의도를 실행하는
# 것은 아니다(CLAUDE.md 2026-09-07).
_RULE_COUNTEREXAMPLES: dict[str, AttemptEvidence] = {
    # R5가 없으면 R3가 가로채 REMEDIATE_MISCONCEPTION을 낸다(설명·힌트가 아니라 오개념 교정).
    # 그래서 오개념을 **일부러 함께** 넣는다 — 오개념 없는 반복 실패는 R6와만 구별되어
    # R5↔R3 우선순위를 밟지 않는다.
    "R5-repeated-failure": AttemptEvidence(
        is_correct=False,
        confirmed_misconception_ids=("M-frac-01",),
        consecutive_failures=REPEATED_FAILURE_THRESHOLD,
    ),
    # R3가 없으면 R4가 가로채 LEARNING(선수 개념)으로 보낸다 — 오개념을 남긴 채.
    # 선수결손을 **함께** 넣어야 R3↔R4 우선순위를 밟는다.
    "R3-wrong-misconception": AttemptEvidence(
        is_correct=False,
        confirmed_misconception_ids=("M-frac-01",),
        prerequisite_gap_concept_ids=("C-prereq-01",),
        consecutive_failures=REPEATED_FAILURE_THRESHOLD - 1,
    ),
    # R4가 없으면 R6가 받아 PRACTICING으로 보낸다 — 결손을 둔 채 같은 개념 연습.
    "R4-prerequisite-gap": AttemptEvidence(
        is_correct=False,
        prerequisite_gap_concept_ids=("C-prereq-01",),
        consecutive_failures=1,
    ),
    # R1이 없으면 R2가 받아 PRACTICING으로 보낸다 — 진급이 영원히 일어나지 않는다.
    # 경계값 자체(정확히 임계)를 쓴다: `>`와 `>=`를 뒤바꾼 뮤테이션이 여기서 잡힌다.
    "R1-correct-high-confidence": AttemptEvidence(
        is_correct=True, confidence=HIGH_CONFIDENCE_THRESHOLD
    ),
    # R2가 없으면 매치되는 규칙이 없다(R6는 오답만 받는다) → 예외.
    "R2-correct-low-confidence": AttemptEvidence(
        is_correct=True, confidence=HIGH_CONFIDENCE_THRESHOLD - 0.01
    ),
    # R6가 없으면 원인 미상 오답이 규칙 구멍으로 떨어진다 → 예외.
    "R6-wrong-undiagnosed": AttemptEvidence(is_correct=False, consecutive_failures=1),
}


def test_every_v1_rule_has_a_counterexample_fixture() -> None:
    """규칙 하나당 반례 하나 — 규칙을 추가하고 픽스처를 잊으면 RED.

    이 대조가 없으면 새 규칙이 뮤테이션 목록에도 픽스처에도 오르지 않은 채 "검증된 정책"의
    일부로 조용히 계상된다(CLAUDE.md 2026-09-08 "뮤테이션 전건 RED는 커버리지의 증거가 아니다").
    """
    declared = {rule.rule_id for rule in V1_RULES}
    covered = set(_RULE_COUNTEREXAMPLES)
    assert (
        declared == covered
    ), f"반례 픽스처 누락: {declared - covered} · 존재하지 않는 규칙의 픽스처: {covered - declared}"


@pytest.mark.parametrize("rule_id", sorted(_RULE_COUNTEREXAMPLES))
def test_counterexample_actually_reaches_its_own_rule(rule_id: str) -> None:
    """픽스처가 그 규칙을 **실제로 밟는다** — 먼저 선언된 규칙에 가로채이지 않는다.

    이 단언이 없으면 반례가 엉뚱한 규칙에서 결정되고, 그래도 아래 제거 테스트는 (다른 이유로)
    통과할 수 있다. 픽스처 접촉을 먼저 고정한다.
    """
    decision = default_policy().decide(LearningState.ASSESSING, _RULE_COUNTEREXAMPLES[rule_id])
    assert decision.rule_id == rule_id


@pytest.mark.parametrize("rule_id", sorted(_RULE_COUNTEREXAMPLES))
def test_removing_a_rule_changes_the_outcome_for_its_counterexample(rule_id: str) -> None:
    """**뮤테이션**: 규칙을 하나 빼면 그 반례의 결과가 달라지거나 예외가 된다.

    정상 입력에서 초록인 것은 보호의 증거가 아니다 — 막으려는 상태(규칙 부재)를 실제로
    주입해 RED를 확인한다(CLAUDE.md 2026-09-01).

    주입이 실제로 적용됐는지도 단언한다(`mutated != original`) — 주입이 조용히 실패하면
    정상 정책에 대해 테스트가 돌고 "검출"처럼 보인다(CLAUDE.md 2026-09-06 "주입 자체의 실재").
    """
    evidence = _RULE_COUNTEREXAMPLES[rule_id]
    baseline = default_policy().decide(LearningState.ASSESSING, evidence)

    mutated_rules: tuple[PolicyRule, ...] = tuple(r for r in V1_RULES if r.rule_id != rule_id)
    assert len(mutated_rules) == len(V1_RULES) - 1, "주입 미적용 — 규칙이 제거되지 않았습니다"
    assert mutated_rules != tuple(V1_RULES), "주입 미적용 — 규칙 집합이 원본과 동일합니다"

    mutated_policy = RuleBasedPolicyV1(mutated_rules)
    try:
        mutated = mutated_policy.decide(LearningState.ASSESSING, evidence)
    except NoMatchingPolicyRuleError:
        return  # 규칙 구멍으로 떨어짐 = 변별력 있음(폴백이 없다는 증거)

    changed = (mutated.next_state, mutated.next_action.kind) != (
        baseline.next_state,
        baseline.next_action.kind,
    )
    assert changed, (
        f"{rule_id}를 제거했는데 반례의 결과가 그대로입니다 "
        f"({baseline.next_state.value}/{baseline.next_action.kind.value}) — "
        f"가드가 관대한 것이 아니라 **픽스처가 그 규칙에 닿지 않은 것**입니다."
    )


def test_policy_raises_instead_of_falling_back_when_no_rule_matches() -> None:
    """미매치는 기본값이 아니라 예외다 — 이 성질이 위 뮤테이션의 변별력을 만든다."""
    empty_policy = RuleBasedPolicyV1(())
    with pytest.raises(NoMatchingPolicyRuleError):
        empty_policy.decide(
            LearningState.ASSESSING, AttemptEvidence(is_correct=True, confidence=0.9)
        )


def test_unmeasured_confidence_is_not_treated_as_high() -> None:
    """확신도 미측정(None)은 "높음"이 아니다 — 확신 미보고 정답이 곧바로 진급하지 않는다.

    `None`을 0.0으로 채우거나 높음으로 접는 두 흔한 실수를 각각 막는다.
    """
    decision = default_policy().decide(
        LearningState.ASSESSING, AttemptEvidence(is_correct=True, confidence=None)
    )
    assert decision.next_state is LearningState.PRACTICING
    assert decision.rule_id == "R2-correct-low-confidence"


def test_every_policy_next_state_is_a_legal_transition_from_assessing() -> None:
    """정책이 제안할 수 있는 모든 상태가 전이표에 있다 — 정책과 표의 정합.

    이 둘이 어긋나면 학생 응답이 `UndefinedTransitionError`로 죽는다. 규칙을 추가하면서
    표를 안 고치는 실수를 여기서 잡는다.
    """
    for rule_id, evidence in _RULE_COUNTEREXAMPLES.items():
        decision = default_policy().decide(LearningState.ASSESSING, evidence)
        assert is_transition_allowed(
            LearningState.ASSESSING, decision.next_state
        ), f"{rule_id}가 제안한 ASSESSING → {decision.next_state.value}가 전이표에 없습니다"


def test_policy_triggers_are_distinct_per_rule() -> None:
    """규칙 ↔ 트리거가 1:1이다 — 사후 감사에서 두 규칙이 같은 사유로 보이지 않는다."""
    triggers = [rule.decide(_RULE_COUNTEREXAMPLES[rule.rule_id]).trigger for rule in V1_RULES]
    assert len(set(triggers)) == len(triggers), f"중복 트리거: {triggers}"


# ──────────────────────────────────────────────────────────────────────────
# ⑤⑥ 적재·거부 표면화
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_initial_state_is_new_when_ledger_is_empty() -> None:
    """전이 이력이 없는 학생은 `NEW`다 — "상태 미상"이라는 아홉 번째 값은 없다."""
    assert await get_current_state(_session(), _UID) is INITIAL_STATE
    assert INITIAL_STATE is LearningState.NEW


@pytest.mark.asyncio
async def test_rejected_transition_writes_no_row() -> None:
    """거부된 전이는 원장에 남지 않는다 — 판정이 적재보다 **앞선다**."""
    session = _session()
    fake = cast(_FakeSession, session)
    with pytest.raises(UndefinedTransitionError):
        await record_transition(
            session,
            user_id=_UID,
            to_state=LearningState.ADVANCING,  # NEW → ADVANCING
            trigger=TransitionTrigger.POLICY_ADVANCE,
        )
    assert fake.added == [], "거부된 전이가 적재됐습니다"
    assert fake.committed == 0


@pytest.mark.asyncio
async def test_recorded_transition_derives_from_state_from_the_ledger() -> None:
    """`from_state`를 호출부가 지어내지 않는다 — 머신이 원장에서 읽는다."""
    session = _session()
    fake = cast(_FakeSession, session)
    await _seed(session, LearningState.DIAGNOSING, LearningState.READY)
    assert fake.added[-1].from_state is LearningState.DIAGNOSING
    assert fake.added[-1].to_state is LearningState.READY
    assert await get_current_state(session, _UID) is LearningState.READY


@pytest.mark.asyncio
async def test_advance_on_attempt_surfaces_the_rejection_instead_of_swallowing_it() -> None:
    """상태 이력이 없는 학생의 응답 제출 — 거부가 **값으로** 올라온다.

    이것이 이 슬라이스의 핵심 계약이다. 예외로만 흘리면 호출부의 `except` 한 줄에서 사라지고,
    사라지면 "조용히 통과"다. 동시에 원장에는 아무 것도 적재되지 않아야 한다.
    """
    session = _session()
    fake = cast(_FakeSession, session)
    result = await advance_on_attempt(
        session, user_id=_UID, evidence=AttemptEvidence(is_correct=True, confidence=0.9)
    )
    assert result.assessed is False
    assert result.decision is None
    assert result.final_state is LearningState.NEW
    assert result.rejected_transition is not None
    # 예외 타입명이 설명에 들어간다(CLAUDE.md 침묵 실패 금지 — 무타입 경고 금지).
    assert "UndefinedTransitionError" in result.rejected_transition
    assert "NEW → ASSESSING" in result.rejected_transition
    assert fake.added == []


@pytest.mark.asyncio
async def test_advance_on_attempt_records_both_transitions_on_the_happy_path() -> None:
    """정상 경로 — 평가 진입 전이 + 정책 전이, 두 행이 남는다.

    한 행만 남기면 "언제 평가에 들어갔는가"가 사라져 사후 재구성이 불가능해진다.
    """
    session = _session()
    fake = cast(_FakeSession, session)
    await _seed(session, LearningState.DIAGNOSING, LearningState.READY, LearningState.LEARNING)
    before = len(fake.added)

    attempt_id = uuid.uuid4()
    result = await advance_on_attempt(
        session,
        user_id=_UID,
        evidence=AttemptEvidence(is_correct=True, confidence=0.95),
        attempt_id=attempt_id,
    )

    assert result.assessed is True
    assert result.from_state is LearningState.LEARNING
    assert result.final_state is LearningState.ADVANCING
    assert result.rejected_transition is None
    assert result.decision is not None
    assert result.decision.next_action.kind is NextActionKind.ADVANCE_TO_NEXT_CONCEPT

    written = fake.added[before:]
    assert [(w.from_state, w.to_state) for w in written] == [
        (LearningState.LEARNING, LearningState.ASSESSING),
        (LearningState.ASSESSING, LearningState.ADVANCING),
    ]
    # 평가 진입 행은 규칙이 없다(생애주기), 정책 행은 규칙 id가 있다 — 빈 문자열로 채우지 않는다.
    assert written[0].rule_id is None
    assert written[1].rule_id == "R1-correct-high-confidence"
    assert all(w.attempt_id == attempt_id for w in written)


@pytest.mark.asyncio
async def test_policy_proposing_an_illegal_state_propagates_instead_of_being_swallowed() -> None:
    """정책과 전이표가 어긋나면 예외가 **그대로 전파된다** — 삼키지 않는다.

    이것은 학생 데이터 문제가 아니라 코드 결함이다. 조용히 넘기면 정책이 무효인 상태를 계속
    제안하는데도 아무도 모른다.
    """
    rogue = PolicyRule(
        rule_id="ROGUE",
        description="전이표에 없는 상태를 제안하는 가짜 규칙",
        matches=lambda _e: True,
        decide=lambda _e: PolicyDecision(
            next_state=LearningState.NEW,  # ASSESSING → NEW는 표에 없다
            next_action=__import__(
                "whymath_backend.schema.learning_state", fromlist=["NextAction"]
            ).NextAction(kind=NextActionKind.PRACTICE_SAME_CONCEPT),
            rule_id="ROGUE",
            trigger=TransitionTrigger.POLICY_PRACTICE_UNDIAGNOSED,
        ),
    )
    session = _session()
    await _seed(session, LearningState.DIAGNOSING, LearningState.READY, LearningState.LEARNING)
    with pytest.raises(UndefinedTransitionError):
        await advance_on_attempt(
            session,
            user_id=_UID,
            evidence=AttemptEvidence(is_correct=False),
            policy=RuleBasedPolicyV1((rogue,)),
        )


@pytest.mark.asyncio
async def test_reconcile_reports_divergence_without_overwriting() -> None:
    """대조는 **검출만** 한다 — 원장을 조용히 고치지 않는다(acceptance ⑥).

    자동 정정은 "어느 쪽이 옳은지 기계가 안다"는 전제가 필요한데 그 전제는 성립하지 않는다
    (정책이 바뀌었을 수도, 적재가 누락됐을 수도 있다).
    """
    session = _session()
    fake = cast(_FakeSession, session)
    await _seed(session, LearningState.DIAGNOSING, LearningState.READY, LearningState.LEARNING)
    before = len(fake.added)

    # 원장은 LEARNING인데, 증거(정답+높은 확신)를 재계산하면 ADVANCING이 나온다.
    report = await reconcile_state(
        session, user_id=_UID, evidence=AttemptEvidence(is_correct=True, confidence=0.99)
    )
    assert report.persisted is LearningState.LEARNING
    assert report.recomputed is LearningState.ADVANCING
    assert report.diverged is True
    assert report.detail is not None and "자동 정정하지 않았습니다" in report.detail
    assert len(fake.added) == before, "대조가 원장을 변경했습니다"
