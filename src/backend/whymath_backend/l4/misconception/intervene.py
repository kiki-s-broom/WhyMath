"""오개념 개입 결정 트리·프롬프트 어셈블리 — `docs/prompts/misconception_diagnosis.md` 정본.

**개입 결정 트리**(doc L75-79):
    confidence > 0.8 → 패턴 1 (반례 유도)
    0.5 ≤ confidence ≤ 0.8 → 패턴 4 (거꾸로 사고)
    confidence < 0.5 → 진단 보류(None 반환 — 학생 추가 발화 대기)

**프롬프트 어셈블리**(doc "표준 패턴" L8-22): canonical_statement·counterexample 슬롯
치환. 어셈블된 발화는 *자각 유도형*(직접 교정·라벨링 금지 — doc 절대 금지 §).

**반복 오류 개입 사다리**(MISC-30 · 계획서 §9): 위 결정 트리는 *어느 발화 패턴을 쓸까*를
정하고, 그것과 **직교하는 축**으로 *얼마나 세게 개입할까*가 따로 있다. 후자의 정본은
`l2/remediation_policy.py`의 표이며 이 모듈은 그 표를 **읽기만** 한다(임계 리터럴 0).

입력 신호는 focus 가설의 `evidence_count`다 — 같은 오개념을 지지한 누적 증거 수이고,
"same error"의 정의로 채택된 값이다(정책 모듈 docstring의 근거 3건). 새 카운터를 만들지
않는다. 감쇠·가지치기가 붙어 있어 증거가 끊기면 등급도 되돌아온다(낙인 방지).

산출 등급은 `InterventionDecision.escalation_rung`에만 실리고 **발화(`prompt`)에는 닿지
않는다** — 학생에게 "몇 번 틀렸다"를 말하지 않는다(CLAUDE.md 교수학 금기).
"""

from __future__ import annotations

import random
from collections.abc import Sequence

from whymath_backend.l2.remediation_policy import EscalationRung, select_rung
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.l4.misconception.hypothesis import (
    _DEFAULT_EPSILON,
    MisconceptionHypothesis,
    select_focus,
)
from whymath_backend.l4.misconception.models import (
    InterventionDecision,
    InterventionPattern,
    MisconceptionMatch,
)

# 결정 트리 임계 — doc L75-79 정본.
_HIGH_CONFIDENCE = 0.8
_LOW_CONFIDENCE = 0.5


def _assemble_counterexample(match: MisconceptionMatch) -> str:
    """패턴 1 — doc L8-10 정본 형식.

    "{학생 가정}이 항상 맞다고 했지. 잠깐, {반례 케이스}일 때는 어떻게 돼?"
    """
    m = match.misconception
    return (
        f"{m.canonical_statement}이 항상 맞다고 했지. "
        f"잠깐, {m.counterexample}일 때는 어떻게 돼?"
    )


def _assemble_reverse(match: MisconceptionMatch) -> str:
    """패턴 4 — doc L20-22 정본 형식.

    "이 결과가 맞다면, *원래 조건*에 어떻게 부합하는지 거꾸로 확인할 수 있을까?"
    학생 가정을 명시해 무엇을 거꾸로 검산할지 안내한다.
    """
    m = match.misconception
    return (
        f"{m.canonical_statement}이라고 했지. 이 결과가 맞다면, "
        "원래 조건에 어떻게 부합하는지 거꾸로 확인할 수 있을까?"
    )


def select_intervention(
    match: MisconceptionMatch,
    *,
    escalation_rung: EscalationRung | None = None,
) -> InterventionDecision | None:
    """결정 트리(doc L75-79) — 신뢰도에 따라 패턴 선택·프롬프트 어셈블.

    낮은 신뢰도(<0.5)는 *진단 보류* — None 반환(학생 추가 발화 대기, 라벨링 회피).

    `escalation_rung`은 **패턴 선택에 관여하지 않는다** — 결정에 실려 나갈 뿐이다(직교 축).
    기본 `None`은 "반복 신호를 입력받지 못했다"이고, 단일 턴 raw 매치 호출자가 여기에
    해당한다(한 번의 매치에는 반복 횟수라는 사실 자체가 없다). 없는 값을 `NONE` 등급으로
    채우면 "사다리가 미발동"과 "사다리를 볼 수 없음"이 같은 글자가 된다.
    """
    if match.confidence > _HIGH_CONFIDENCE:
        return InterventionDecision(
            pattern=InterventionPattern.COUNTEREXAMPLE,
            prompt=_assemble_counterexample(match),
            misconception_id=match.misconception.id,
            escalation_rung=escalation_rung,
        )
    if match.confidence >= _LOW_CONFIDENCE:
        return InterventionDecision(
            pattern=InterventionPattern.REVERSE_REASONING,
            prompt=_assemble_reverse(match),
            misconception_id=match.misconception.id,
            escalation_rung=escalation_rung,
        )
    return None


def select_intervention_from_hypotheses(
    hypotheses: Sequence[MisconceptionHypothesis],
    *,
    epsilon: float = _DEFAULT_EPSILON,
    rng: random.Random | None = None,
) -> InterventionDecision | None:
    """활성 가설 세트 → ε-규칙 focus 선택 → 개입 결정(결선·재구현 0).

    WH-1 2단계 *결선* 좌석. 단일 턴 raw 매치(`select_intervention(match)`)가 아니라, 시간
    감쇠·강화로 누적된 **활성 가설 세트**가 개입을 결정하게 한다(`_apply_hypotheses` docstring이
    예고한 "select_focus 기반 intervention 변경"). 절차(전부 기존 순수 로직 재사용·재구현 0):
      1. `select_focus`(#191 ε-규칙)로 개입 대상 가설을 고른다 — 기본(rng=None)은 *최상위 활용*,
         `rng` 주입 시 ε 확률로 차순위 탐색(1위 고착·확증편향 방지·R4).
      2. focus의 `misconception_id`를 정본 카탈로그(`CATALOG_BY_ID`)로 해소한다 — 프롬프트
         어셈블(canonical_statement·counterexample)에 실 `Misconception`이 필요하다.
      3. focus의 *가설 신뢰도*(누적)로 `select_intervention` 결정 트리를 구동(>0.8 반례·≥0.5
         거꾸로·<0.5 보류). 즉 여러 턴 강화된 가설은 반례 유도로, 감쇠한 가설은 보류로 간다.
      4. focus의 `evidence_count`를 **반복 오류 사다리**(`l2/remediation_policy.select_rung`)에
         넣어 개입 *강도* 등급을 함께 싣는다(MISC-30). 이 좌석이 그 reader다 — 여기서만 반복
         신호를 알 수 있기 때문이다(raw 매치 경로에는 누적 횟수가 없다). 등급은 패턴 선택을
         바꾸지 않고(직교) 발화에도 닿지 않는다.

    빈 세트·focus 없음(None)·카탈로그 부재(느슨 id — 어셈블 불가)면 None(개입 보류·날조 0·낙인
    금지). **순수**: DB·LLM·전역 상태 무지(가설 세트와 주입 rng만으로 결정). 가설 세트는 confidence
    내림차순 정렬을 가정한다(`select_focus` 전제·`get_active_hypotheses`/`curate` 결과).
    """
    focus = select_focus(hypotheses, epsilon=epsilon, rng=rng)
    if focus is None:
        return None
    misconception = CATALOG_BY_ID.get(focus.misconception_id)
    if misconception is None:
        return None  # 느슨 id(카탈로그 부재) → 프롬프트 어셈블 불가 → 보류(정직).
    match = MisconceptionMatch(misconception=misconception, confidence=focus.confidence)
    return select_intervention(match, escalation_rung=select_rung(focus.evidence_count))
