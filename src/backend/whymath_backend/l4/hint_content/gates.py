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
     금지(문자열 *동등* 판정 — 길이 무관) · 최종 결과(2자 이상)가 본문 어디에든 있으면 금지 ·
     **본문의 식 하나가 최종 단계와 값이 같으면 금지**(P3-77 — 값 동치).
     ④는 게이트 B가 판정 불가(undecidable)를 내는 짧은 정답에서도 전체 풀이 노출을 막는
     **독립 방어선**이다(B와 달리 정답 값이 아니라 풀이 경로의 최종 단계를 목표로 판정 — 문항
     정답과 풀이 경로의 최종 값이 다른 문항이 실재한다: 2026-10-22 코퍼스 실측 36건).

게이트 B — 정답 누출(`check_answer_leakage`) — 두 축
  ① 글자 축: `harness/pedagogical_rubric.detect_answer_leakage`를 **재사용**한다(재구현 0 —
     정규화·단어 경계·짧은 값 유보 규칙이 그 한 곳에만 산다). leaked → 거부.
  ② 값 축(P3-77): 본문의 식 중 계산하면 정답이 되는 것이 있는가 — 선택적 능력
     `AnswerValueExposure`(과목 어댑터 구현)에 묻는다. exposed → 거부 · undecidable → **거부**
     (판정 불가 ≠ 통과) · clean → 통과. 능력이 주입되지 않았으면(None) 값 축을 판정하지 못한
     것이므로 **거부**한다 — "모른다"를 "노출 없음"으로 접지 않는다.
  글자 축이 undecidable(짧거나 흔한 정답 — 예: 정답 `4`)이어도 값 축이 판정한다. P3-10 실측
  `aq-h-06-04-l3`(정답 4 · L3가 `(-3) + (4)*((2) - (0)) + (-3) + (1)*((2) - (0)) = y`를 보여
  줌)이 바로 그 구간이었다 — 글자 축은 유보하고 ④는 문자열 동등만 봐서 둘 다 통과시켰다.
  정답 원천이 없으면(문제 answer NULL) **거부**한다(fail-closed). 정답 값은 판정 함수에
  *넘기기만* 하고 이 모듈이 해석하지 않는다(EOS 불투명 페이로드 원칙).

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
from whymath_backend.schema.verification_capabilities import AnswerValueExposure, ValueExposure

__all__ = [
    "GATE_ANSWER_LEAKAGE",
    "GATE_LEVEL_REVEALS",
    "GATE_NAMES",
    "GATE_TONE",
    "VALUE_NOT_RUN",
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

# 값 축을 돌리지 못했다는 판정값(능력 미주입) — 3상태(`ValueExposure`) 밖의 네 번째 값이다.
VALUE_NOT_RUN = "not_run"


def _norm(text: str) -> str:
    """비교용 정규화 — NFKC + 공백 제거(표기 공백 차이 흡수·순수)."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


@dataclass(frozen=True)
class GateContext:
    """게이트 판정 맥락 — 경로 단계 본문 전체·원천 개념 이름·문제 정답(불투명 값)·값 축 능력.

    `value_exposure`에 기본값이 없는 이유: 기본값 None이면 호출부가 *잊는 것*과 *능력이 없는
    과목이라 넘기지 않는 것*이 구별되지 않는다. 필수 인자로 두면 모든 호출부가 둘 중 하나를
    명시해야 한다(None을 넘기면 값 축은 fail-closed — 모듈 docstring 게이트 B ②).
    """

    step_contents: tuple[str, ...]
    concept_name: str | None
    final_answer: str | None
    value_exposure: AnswerValueExposure | None


def _value_scan(ctx: GateContext, text: str, target: str) -> tuple[str, str | None]:
    """값 축 판정값(`ValueExposure` 값 또는 `VALUE_NOT_RUN`)과 노출된 식(있으면)."""
    if ctx.value_exposure is None:
        return VALUE_NOT_RUN, None
    scan = ctx.value_exposure.scan_value_exposure(text, target)
    return scan.outcome.value, scan.fragment


def _value_reason(verdict: str, fragment: str | None, *, target_label: str) -> str | None:
    """값 축 판정값 → 거부 사유(통과면 None). **clean만 통과한다** — 판정 불가·미실행·알 수 없는
    판정값(능력 구현이 계약 밖 값을 낸 경우)은 전부 거부다(fail-closed · 허용 목록 방식)."""
    if verdict == ValueExposure.clean.value:
        return None
    if verdict == ValueExposure.exposed.value:
        return f"본문의 식이 {target_label} 값과 같다({fragment!r} — 값 동치 노출)"
    if verdict == ValueExposure.undecidable.value:
        return f"본문의 식이 {target_label} 값과 같은지 판정하지 못했다(판정 불가 ≠ 통과)"
    if verdict == VALUE_NOT_RUN:
        return f"값 동치 판정 능력이 주입되지 않아 {target_label} 값 노출을 판정하지 못했다"
    return f"값 축 판정값 {verdict!r}은 계약 밖이다(통과로 접지 않는다)"


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
    final_value = "no_steps"
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
        # 값 동치(P3-77) — 글자가 달라도 계산하면 최종 단계 값이 되는 식이 본문에 있으면 전체 풀이
        # 노출이다. 구조(k)가 아니라 **본문**을 본다: 다른 단계의 L3로 대체 서빙된 본문도 같은
        # 규칙으로 판정되어야 하기 때문이다(store.select_ladder_hint — L3 공백 대체).
        final_value, fragment = _value_scan(ctx, hint.content, ctx.step_contents[-1])
        value_reason = _value_reason(final_value, fragment, target_label="최종 단계")
        if value_reason is not None:
            reasons.append(f"{value_reason}(전체 풀이 노출)")

    return _verdict(
        reasons,
        {
            "derived_flow": str(derived_flow),
            "computation_hit_orders": ",".join(str(o) for o in any_hits),
            "final_value_verdict": final_value,
        },
    )


def check_answer_leakage(hint: Hint, ctx: GateContext) -> GateVerdict:
    """게이트 B — 글자 축(`detect_answer_leakage` 재사용) + 값 축(능력 경유). 모듈 docstring."""
    if ctx.final_answer is None:
        return _verdict(
            ["정답 원천이 없어 누출을 판정할 수 없다(fail-closed — 판정 불가 ≠ 통과)"],
            {"verdict": "not_run", "value_verdict": VALUE_NOT_RUN},
        )
    verdict = detect_answer_leakage(hint.content, ctx.final_answer)
    reasons: list[str] = []
    if verdict is LeakageVerdict.leaked:
        reasons.append("정답 값이 힌트 본문에 노출됐다(최상위 교수학 금기)")
    # 값 축 — 글자 축의 판정과 무관하게 항상 돈다(글자 축 undecidable 구간을 값으로 닫는다).
    value_verdict, fragment = _value_scan(ctx, hint.content, ctx.final_answer)
    value_reason = _value_reason(value_verdict, fragment, target_label="정답")
    if value_reason is not None:
        reasons.append(value_reason)
    return _verdict(reasons, {"verdict": verdict.value, "value_verdict": value_verdict})


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
