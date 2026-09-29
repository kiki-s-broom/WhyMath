"""힌트 검증 게이트 3종 — 통과분만 verified=true (S4-11 · D3 · 순수·결정론).

acceptance "게이트 3종(level-reveals 정합 invariant·detect_answer_leakage 재사용·정서 톤 필터)
통과분만 verified=true". 세 게이트는 **서로 다른 결함**을 잡는다 — 하나가 다른 둘을 대신하지
않는다(각 게이트의 실패 주입 테스트가 나머지 둘은 통과하는 입력으로 그 독립성을 동결한다).

게이트 A — level-reveals 정합(`check_level_reveals`)
  선언(level·reveals 플래그)이 아니라 **본문에서 파생한 노출**을 본다. 선언만 검사하면 생성기가
  스스로 세운 플래그를 스스로 확인하는 동어반복이 된다.
  ① 레벨 행렬 — L1: 개념 이름 O·흐름 X·계산 X / L2: 흐름 O·계산 X / L3: 흐름 O·계산 O.
  ② 점수 — reveal_score = 플래그 파생값(`models.compute_reveal_score`).
  ③ 본문↔선언 양방향 일치 — 흐름 표지(몇 단계·몇 번째 단계·첫/마지막 단계)가 본문에 있는가 /
     경로의 단계 본문(정규화 2자 이상)이 본문에 있는가 / 원천 개념 이름이 본문에 있는가.
     선언하지 않은 노출(과소 선언 → KPI 과소 계상)과 선언했지만 없는 노출(과대 선언) 둘 다 거부.
  ④ Level 4 경계 — 마지막 단계의 부분 시연 금지(구조 판정) · 시연 결과가 최종 결과와 같으면
     금지(문자열 *동등* 판정 — 길이 무관) · 최종 결과(2자 이상)가 본문 어디에든 있으면 금지.
     ④는 게이트 B가 판정 불가(undecidable)를 내는 짧은 정답에서도 전체 풀이 노출을 막는
     **독립 방어선**이다(B와 달리 정답 값이 아니라 풀이 경로 구조로 판정).

게이트 B — 정답 누출(`check_answer_leakage`)
  `harness/pedagogical_rubric.detect_answer_leakage`를 **재사용**한다(재구현 0 — 정규화·단어
  경계·짧은 값 유보 규칙이 그 한 곳에만 산다). 판정: leaked → 거부 · clean → 통과 ·
  undecidable(짧거나 흔한 정답) → 통과하되 판정을 리포트에 남긴다(그 구간은 게이트 A ④가 구조로
  막는다 — 위 설명). 정답 원천이 없으면(문제 answer NULL) **거부**한다(판정 불가를 통과로
  위장하지 않는다 — fail-closed). 정답 값은 판정 함수에 *넘기기만* 하고 이 모듈이 해석하지
  않는다(EOS 불투명 페이로드 원칙).

게이트 C — 정서 톤(`check_tone`)
  `l4/tone_filter.filter_tone`을 재사용한다. 서빙 경로의 톤필터는 금지 패턴을 *치환*하지만,
  사전 생성 콘텐츠는 치환하지 않고 **거부**한다 — 치환은 뜻을 망가뜨릴 수 있다(예: 개념 이름
  「실수」(real number)가 "흥미로운 시도"로 바뀐다). 거부하고 사유를 남기면 사람이 템플릿이나
  개념 표기를 고칠 수 있다.

판정 결과는 `Hint.gate_report`(→ `hints.gate_report` JSONB)에 게이트별로 남는다 — 왜 거부됐는지가
행에 남아야 한다(조용한 실패 금지).
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from whymath_backend.harness.pedagogical_rubric import LeakageVerdict, detect_answer_leakage
from whymath_backend.l4.hint_content.models import Hint, compute_reveal_score
from whymath_backend.l4.tone_filter import filter_tone

__all__ = [
    "GATE_ANSWER_LEAKAGE",
    "GATE_LEVEL_REVEALS",
    "GATE_NAMES",
    "GATE_TONE",
    "GateContext",
    "GateReport",
    "GateVerdict",
    "check_answer_leakage",
    "check_level_reveals",
    "check_tone",
    "evaluate_gates",
]

GATE_LEVEL_REVEALS = "level_reveals"
GATE_ANSWER_LEAKAGE = "answer_leakage"
GATE_TONE = "tone"
GATE_NAMES: tuple[str, ...] = (GATE_LEVEL_REVEALS, GATE_ANSWER_LEAKAGE, GATE_TONE)

# 단계 흐름 표지 — 풀이의 *구조*(전체 단계 수·현재 위치)를 말하는 표현. 흐름 노출의 판정 근거.
_FLOW_MARKERS = re.compile(r"\d+\s*(?:번째\s*)?단계|첫\s*단계|마지막\s*단계")

# 단계 본문을 '계산 노출'로 판정할 최소 정규화 길이 — 1자(예: "3")는 번호·우연 일치와 구별이
# 안 돼 부분 문자열 판정에서 뺀다(detect_answer_leakage의 짧은 값 유보와 같은 규약). 1자 본문의
# 노출은 ④의 *동등* 판정과 L3 선언 확인(길이 무관)으로 다룬다.
_MIN_DECIDABLE_LEN = 2


def _norm(text: str) -> str:
    """비교용 정규화 — NFKC + 공백 제거(표기 공백 차이 흡수·순수)."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


@dataclass(frozen=True)
class GateContext:
    """게이트 판정 맥락 — 경로 단계 본문 전체·원천 개념 이름·문제 정답(불투명 값)."""

    step_contents: tuple[str, ...]
    concept_name: str | None
    final_answer: str | None


class GateVerdict(BaseModel):
    """게이트 1종의 판정 — 통과 여부 + 사유(실패 시 반드시 1개 이상) + 부가 판정값."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    reasons: tuple[str, ...] = ()
    detail: dict[str, str] = Field(default_factory=dict)


class GateReport(BaseModel):
    """게이트 3종 판정 묶음 — 전건 통과여야 verified."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    level_reveals: GateVerdict
    answer_leakage: GateVerdict
    tone: GateVerdict

    @property
    def passed(self) -> bool:
        return self.level_reveals.passed and self.answer_leakage.passed and self.tone.passed

    def to_json(self) -> dict[str, object]:
        """`hints.gate_report` JSONB 직렬화 — 게이트별 판정 + 전체 통과 여부."""
        payload: dict[str, object] = {
            name: verdict.model_dump(mode="json")
            for name, verdict in (
                (GATE_LEVEL_REVEALS, self.level_reveals),
                (GATE_ANSWER_LEAKAGE, self.answer_leakage),
                (GATE_TONE, self.tone),
            )
        }
        payload["passed"] = self.passed
        return payload


def _verdict(reasons: list[str], detail: dict[str, str] | None = None) -> GateVerdict:
    return GateVerdict(passed=not reasons, reasons=tuple(reasons), detail=detail or {})


def check_level_reveals(hint: Hint, ctx: GateContext) -> GateVerdict:
    """게이트 A — 레벨·노출 선언·본문 파생 노출·Level 4 경계의 정합(모듈 docstring ①~④)."""
    reasons: list[str] = []
    reveals = hint.reveals
    level = hint.level

    # ① 레벨 행렬 — 레벨이 허용하는 노출과 선언이 맞는가.
    if level == 1 and not (
        reveals.reveals_concept_names
        and not reveals.reveals_step_flow
        and not reveals.reveals_partial_computation
    ):
        reasons.append("L1은 개념 이름만 노출해야 한다(흐름·계산 노출 금지·개념 이름 필수)")
    if level == 2 and not (reveals.reveals_step_flow and not reveals.reveals_partial_computation):
        reasons.append("L2는 단계 흐름을 노출하되 계산은 노출하지 않아야 한다")
    if level == 3 and not (reveals.reveals_partial_computation and reveals.reveals_step_flow):
        reasons.append("L3는 단계 흐름과 부분 시연을 함께 노출해야 한다")

    # ② 점수 — 플래그 파생값과 일치(모델 검증기의 재확인 — 외부 조립 행 방어).
    expected = compute_reveal_score(
        concept_names=reveals.reveals_concept_names,
        step_flow=reveals.reveals_step_flow,
        partial_computation=reveals.reveals_partial_computation,
    )
    if not math.isclose(reveals.reveal_score, expected, abs_tol=1e-9):
        reasons.append(f"reveal_score {reveals.reveal_score}≠플래그 파생값 {expected}")

    # ③ 본문 ↔ 선언 양방향 일치 — 선언이 아니라 본문이 무엇을 드러내는지를 본다.
    body = _norm(hint.content)
    derived_flow = _FLOW_MARKERS.search(hint.content) is not None
    if reveals.reveals_step_flow != derived_flow:
        reasons.append(
            f"흐름 노출 선언={reveals.reveals_step_flow}이나 본문 파생={derived_flow}"
            "(흐름 표지 기준)"
        )
    normed_steps = [_norm(c) for c in ctx.step_contents]
    decidable_hits = [
        order
        for order, c in enumerate(normed_steps, start=1)
        if len(c) >= _MIN_DECIDABLE_LEN and c in body
    ]
    any_hits = [order for order, c in enumerate(normed_steps, start=1) if c and c in body]
    if not reveals.reveals_partial_computation and decidable_hits:
        reasons.append(f"계산 노출을 선언하지 않았는데 단계 본문이 실렸다(order={decidable_hits})")
    if reveals.reveals_partial_computation and not any_hits:
        reasons.append("부분 시연을 선언했으나 본문에 단계 식이 없다(과대 선언)")
    if ctx.concept_name is not None:
        derived_concept = _norm(ctx.concept_name) in body
        if reveals.reveals_concept_names != derived_concept:
            reasons.append(
                f"개념 이름 노출 선언={reveals.reveals_concept_names}이나 "
                f"본문 파생={derived_concept}"
            )
    elif reveals.reveals_concept_names:
        reasons.append("개념 이름 노출을 선언했으나 원천 개념이 없다")
    if reveals.reveals_concept_names != bool(reveals.revealed_concept_ids):
        reasons.append("개념 이름 노출 선언과 revealed_concept_ids가 어긋난다")

    # ④ Level 4 경계 — 전체 풀이(최종 결과)는 Hint 엔티티가 아니다.
    n = len(ctx.step_contents)
    k = hint.solution_step_ref.step_order
    if k > n:
        reasons.append(f"단계 참조 order={k}가 경로 단계 수 {n}을 넘는다")
    if n:
        final = normed_steps[-1]
        if level == 3 and k >= n:
            reasons.append("마지막 단계의 부분 시연은 전체 풀이다(Level 4 — Hint 엔티티 밖)")
        if level == 3 and k <= n and normed_steps[k - 1] == final:
            reasons.append("시연한 단계의 결과가 최종 결과와 같다(전체 풀이 노출)")
        if len(final) >= _MIN_DECIDABLE_LEN and final in body:
            reasons.append("최종 단계 결과가 본문에 실렸다(전체 풀이 노출)")

    return _verdict(
        reasons,
        {
            "derived_flow": str(derived_flow),
            "computation_hit_orders": ",".join(str(o) for o in any_hits),
        },
    )


def check_answer_leakage(hint: Hint, ctx: GateContext) -> GateVerdict:
    """게이트 B — `detect_answer_leakage` 재사용(leaked 거부·정답 원천 부재 거부)."""
    if ctx.final_answer is None:
        return _verdict(
            ["정답 원천이 없어 누출을 판정할 수 없다(fail-closed — 판정 불가를 통과로 두지 않는다)"],
            {"verdict": "not_run"},
        )
    verdict = detect_answer_leakage(hint.content, ctx.final_answer)
    reasons: list[str] = []
    if verdict is LeakageVerdict.leaked:
        reasons.append("정답 값이 힌트 본문에 노출됐다(최상위 교수학 금기)")
    return _verdict(reasons, {"verdict": verdict.value})


def check_tone(hint: Hint) -> GateVerdict:
    """게이트 C — `filter_tone` 재사용. 금지 패턴이 하나라도 있으면 거부(치환하지 않는다)."""
    _rewritten, report = filter_tone(hint.content)
    reasons = [f"정서 안전 금지 패턴 {pattern!r}" for pattern in sorted(set(report.violations))]
    return _verdict(reasons, {"violations": str(len(report.violations))})


def evaluate_gates(hint: Hint, ctx: GateContext) -> Hint:
    """게이트 3종을 모두 돌려(단락 평가 없음 — 사유 전부 기록) verified·gate_report를 채운다."""
    report = GateReport(
        level_reveals=check_level_reveals(hint, ctx),
        answer_leakage=check_answer_leakage(hint, ctx),
        tone=check_tone(hint),
    )
    return hint.model_copy(update={"verified": report.passed, "gate_report": report.to_json()})
