"""독립 다관점 LLM 교차검증 — 기계 불가 잔여의 검출기(S4-13 ②).

정본: `docs/architecture/problem_bank_gap_review.md` §3 D7 — "기계 불가 잔여는 **독립 다관점
LLM 교차검증**(생성자≠검증자·K≥3·**원리 다른 프롬프트**, S3 축 준용) + Wilson 표본 검수
게이트(S5 축)". 초인간 검증 §2 S3(독립 다관점)의 LLM 판(`equivalent/retag.py`가 결정론
독립 감사의 선례라면, 이쪽은 결정론으로 닫히지 않는 축의 판).

**이 모듈은 게이트가 아니라 검출기다.** 판정(exit 0/1)은 `harness/residue_cross_verify_eval`
의 Wilson 표본 검수 게이트가 내린다. 여기 결과는 그 게이트의 *감사 라벨 입력*이다 —
검증 권위 서열 ②("측정 통과 기계 게이트")를 경유하지 않은 LLM 의견은 그 자체로 권위가 없다.

────────────────────────────────────────────────────────────────────────────
독립성을 무엇으로 보장하는가 (K개 같은 프롬프트는 독립이 아니다)
────────────────────────────────────────────────────────────────────────────
독립성을 *선언*하지 않고 **구성 시점에 기계로 강제**한다(`_assert_independent`). 세 축이
모두 달라야 관점으로 인정된다:

  1. **원리(principle)** — 무엇을 하는 행위인가가 다르다. 재풀이 / 반증 / 번역대조.
  2. **시스템 프롬프트** — 역할·출력 계약이 다르다(동일 문자열 금지).
  3. **가시 필드(visible_fields)** — *보는 정보가 다르다*. 이것이 핵심이다. 답을 본 관점과
     답을 못 본 관점은 같은 오류에 걸리지 않는다(앵커링 공유 차단). 세 관점의 가시 필드
     집합이 하나라도 겹치면(동일 집합) 구성이 거부된다.

추가로 **생성자≠검증자**를 구조로 강제한다 — 대상은 자신을 만든 주체 서명(`authored_by`)을
들고 오고, 검증자는 자기 서명과 충돌하면 검증을 거부한다(`IndependenceError`). 파일럿 코퍼스의
`authored_by`는 결정론 SymPy/열거 생성기라 LLM 자기승인이 원천적으로 성립하지 않는다.

────────────────────────────────────────────────────────────────────────────
K=3 기본 관점(원리가 다르다)
────────────────────────────────────────────────────────────────────────────
① `independent_reconstruction` (독립 재구성) — **발문만** 보여주고 표본공간 크기·유리한
   경우의 수를 스스로 세게 한다. 답·해설·형식모델은 은닉(앵커링 차단). **판정은 기계가**
   한다 — LLM 숫자 vs 전수 열거 숫자의 일치. LLM은 의견이 아니라 *독립 재계산*을 낸다.
② `adversarial_falsification` (적대적 반증) — 발문+답을 주고 "이 문항은 결함이 있다고
   가정하고 근거를 찾아라"로 시작한다(6축 ②적대성). 조건 결측·중의성·복수 정답·등확률
   가정 미명시를 노린다. 형식모델은 은닉(모델을 보면 발문의 빈틈을 모델로 메워 읽는다).
③ `model_grounding` (서술-형식모델 정합) — 발문 + *기계가 실제로 검산한 모델의 한국어
   풀어쓰기*를 나란히 주고 **오직 번역 일치만** 판정한다(수치 계산 금지·답 은닉). 기계가
   못 하는 잔여의 정확히 그 지점 — "기계가 발문과 다른 문제를 풀지 않았는가".

7계층: L3 지역. 라우터·provider·trace만 쓴다(CLAUDE.md "LLM 호출은 항상 라우터 경유").
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from whymath_backend.config import Settings
from whymath_backend.l3.data_grade_defaults import SELF_AUTHORED_CORPUS
from whymath_backend.l3.escalation_defaults import default_student_escalation_signals
from whymath_backend.l3.interfaces import LLMProvider, TraceSink
from whymath_backend.l3.models import (
    CallSite,
    CostTier,
    RoutingDecision,
    RoutingRequest,
    Usage,
)
from whymath_backend.l3.prompt_assets import fill, prompt_text
from whymath_backend.l3.router import (
    Router,
    actual_cost_krw,
    langfuse_fields,
    resolve_model,
)

# 학생 요청 라우팅 신호 기본값 — 6개 호출부 공용 단일 좌석(OPS-18, `api/visualization.py` 미러).
_STUDENT_ESCALATION_DEFAULTS = default_student_escalation_signals()

__all__ = [
    "CrossVerificationResult",
    "CrossVerifier",
    "IndependenceError",
    "PROBABILITY_PERSPECTIVES",
    "STATISTICAL_PERSPECTIVES",
    "Perspective",
    "PerspectiveVerdict",
    "ResidueSubject",
]

_LOGGER = logging.getLogger(__name__)

# 관점 최소 개수 — D7 명세의 K≥3. 이보다 적은 구성은 "다관점"이 아니다.
MIN_PERSPECTIVES = 3

ResidueVerdictLabel = Literal["ok", "defect", "unclear"]

# 관점이 볼 수 있는 `ResidueSubject` 필드 이름 — 가시 집합의 정의역(오타로 은닉이 새는 것 방어).
# 기계 계산값(machine_total·machine_favorable)은 *판정 재료*이지 프롬프트 노출 대상이 아니라
# 여기 없다 — ①의 대조는 기계가 하지 LLM에게 정답 숫자를 보여주지 않는다.
_FIELD_NAMES = frozenset(
    {"question_text", "answer", "answer_explanation", "machine_model_ko", "data"}
)


@dataclass(frozen=True, slots=True)
class ResidueSubject:
    """교차검증 대상 — 기계가 닫은 축(수치)과 닫지 못한 축(서술)의 재료를 함께 든다.

    `authored_by`는 이 문항을 만든 주체의 서명이다(예 결정론 생성기 이름·LLM 모델 id).
    검증자는 자기 서명과 충돌하면 검증을 거부한다 — 생성자≠검증자의 구조적 강제.
    `data`는 통계 자료형처럼 원본 자료 문자열이 필요한 도메인용 선택적 필드.
    """

    problem_id: str
    question_text: str
    answer: str
    answer_explanation: str
    machine_model_ko: str
    machine_total: int
    machine_favorable: int
    authored_by: str
    data: str = ""
    machine_value: float | None = None


@dataclass(frozen=True, slots=True)
class PerspectiveVerdict:
    """관점 1개의 판정 — ok(결함 없음)/defect(결함 지목)/unclear(판정 실패·측정 실패)."""

    principle: str
    verdict: ResidueVerdictLabel
    defect_class: str
    reason: str


@dataclass(frozen=True, slots=True)
class Perspective:
    """관점 1개 — 원리·시스템 프롬프트·가시 필드·렌더·판정을 한 묶음으로.

    `judge`는 LLM 응답 JSON을 받아 판정으로 바꾼다. ①처럼 *기계가* 판정하는 관점은 여기서
    대상의 기계 계산값과 대조한다(LLM은 의견이 아니라 재계산을 제공).
    """

    principle: str
    system_prompt: str
    visible_fields: frozenset[str]
    render: Callable[[ResidueSubject], str]
    judge: Callable[[ResidueSubject, Mapping[str, object]], PerspectiveVerdict]


class IndependenceError(RuntimeError):
    """독립성 위반 — 관점 구성이 겹치거나 생성자와 검증자가 같은 주체(자기승인)."""


# ──────────────────────────────────────────────────────────────────────────
# 관점 ① 독립 재구성 — 발문만 보고 스스로 센다(판정은 기계)
# ──────────────────────────────────────────────────────────────────────────
_SYSTEM_RECONSTRUCT = prompt_text("l3.cross_verify.reconstruct_system")


def _render_reconstruct(subject: ResidueSubject) -> str:
    """가시 필드 = 발문뿐. 정답·해설·형식 모델은 여기 없다(은닉 = 앵커링 차단)."""
    return fill(
        prompt_text("l3.cross_verify.reconstruct_user"), QUESTION_TEXT=subject.question_text
    )


def _judge_reconstruct(subject: ResidueSubject, data: Mapping[str, object]) -> PerspectiveVerdict:
    """LLM이 독립적으로 센 수 vs 기계 전수 열거 수 — **기계가** 판정한다."""
    total = data.get("total")
    favorable = data.get("favorable")
    if not isinstance(total, int) or not isinstance(favorable, int):
        return PerspectiveVerdict(
            principle="independent_reconstruction",
            verdict="unclear",
            defect_class="reconstruction_declined",
            reason=f"독립 재구성 실패(표본공간 미확정): {data.get('reason', '사유 미제시')}",
        )
    if total == subject.machine_total and favorable == subject.machine_favorable:
        return PerspectiveVerdict(
            principle="independent_reconstruction",
            verdict="ok",
            defect_class="",
            reason=f"독립 재구성 일치({favorable}/{total}).",
        )
    return PerspectiveVerdict(
        principle="independent_reconstruction",
        verdict="defect",
        defect_class="model_mismatch",
        reason=(
            f"독립 재구성 불일치 — 재계산 {favorable}/{total} vs 기계 전수 "
            f"{subject.machine_favorable}/{subject.machine_total}. 발문이 기계가 검산한 "
            "형식 모델과 다르게 읽힐 소지."
        ),
    )


# ──────────────────────────────────────────────────────────────────────────
# 관점 ② 적대적 반증 — 결함이 있다고 가정하고 근거를 찾는다
# ──────────────────────────────────────────────────────────────────────────
_SYSTEM_FALSIFY = prompt_text("l3.cross_verify.falsify_system")


def _render_falsify(subject: ResidueSubject) -> str:
    """가시 필드 = 발문 + 제시된 정답(형식 모델은 은닉 — 모델을 보면 빈틈을 모델로 메워 읽는다)."""
    return fill(
        prompt_text("l3.cross_verify.falsify_user"),
        QUESTION_TEXT=subject.question_text,
        ANSWER=subject.answer,
    )


# ──────────────────────────────────────────────────────────────────────────
# 관점 ③ 서술-형식모델 정합 — 번역 대조만(수치 계산 금지)
# ──────────────────────────────────────────────────────────────────────────
_SYSTEM_GROUNDING = prompt_text("l3.cross_verify.grounding_system")


def _render_grounding(subject: ResidueSubject) -> str:
    """가시 필드 = 발문 + 기계 형식 모델(정답은 은닉 — 번역 일치만 판정하므로 답이 필요 없다)."""
    return fill(
        prompt_text("l3.cross_verify.grounding_user"),
        QUESTION_TEXT=subject.question_text,
        MACHINE_MODEL_KO=subject.machine_model_ko,
    )


def _judge_labelled(
    principle: str,
) -> Callable[[ResidueSubject, Mapping[str, object]], PerspectiveVerdict]:
    """`verdict` 라벨을 직접 내는 관점(②③)의 공용 판정기 — 미지 라벨은 unclear(단정 금지)."""

    def judge(subject: ResidueSubject, data: Mapping[str, object]) -> PerspectiveVerdict:
        del subject  # 라벨형 관점은 대상 재참조 없이 응답만으로 판정된다.
        raw = data.get("verdict")
        reason = str(data.get("reason", "")).strip() or "사유 미제시"
        defect_class = str(data.get("defect_class", "")).strip() or "unspecified"
        if raw == "ok":
            return PerspectiveVerdict(principle, "ok", "", reason)
        if raw == "defect":
            return PerspectiveVerdict(principle, "defect", defect_class, reason)
        return PerspectiveVerdict(
            principle,
            "unclear",
            "verdict_unparsed",
            f"판정 라벨을 읽을 수 없음(verdict={raw!r}) — 측정 실패로 기록.",
        )

    return judge


PROBABILITY_PERSPECTIVES: tuple[Perspective, ...] = (
    Perspective(
        principle="independent_reconstruction",
        system_prompt=_SYSTEM_RECONSTRUCT,
        visible_fields=frozenset({"question_text"}),
        render=_render_reconstruct,
        judge=_judge_reconstruct,
    ),
    Perspective(
        principle="adversarial_falsification",
        system_prompt=_SYSTEM_FALSIFY,
        visible_fields=frozenset({"question_text", "answer"}),
        render=_render_falsify,
        judge=_judge_labelled("adversarial_falsification"),
    ),
    Perspective(
        principle="model_grounding",
        system_prompt=_SYSTEM_GROUNDING,
        visible_fields=frozenset({"question_text", "machine_model_ko"}),
        render=_render_grounding,
        judge=_judge_labelled("model_grounding"),
    ),
)
"""파일럿(확률 유한 전수형) 기본 K=3 관점 — 원리·프롬프트·가시 필드가 모두 다르다."""

# ──────────────────────────────────────────────────────────────────────────
# 관점 ④~⑥ 통계 자료형 — 독립 재계산 / 반증 / 발문↔자료↔통계량 정합
# ──────────────────────────────────────────────────────────────────────────
_SYSTEM_STAT_RECONSTRUCT = prompt_text("l3.cross_verify.statistical_reconstruct_system")
_SYSTEM_STAT_FALSIFY = prompt_text("l3.cross_verify.statistical_falsify_system")
_SYSTEM_STAT_GROUNDING = prompt_text("l3.cross_verify.statistical_grounding_system")


def _render_stat_reconstruct(subject: ResidueSubject) -> str:
    """가시 필드 = 발문 + 데이터. 정답·해설·기계 계산값은 은닉(앵커링 차단)."""
    return fill(
        prompt_text("l3.cross_verify.statistical_reconstruct_user"),
        QUESTION_TEXT=subject.question_text,
        DATA=subject.data,
    )


def _render_stat_falsify(subject: ResidueSubject) -> str:
    """가시 필드 = 발문 + 데이터 + 제시된 정답."""
    return fill(
        prompt_text("l3.cross_verify.statistical_falsify_user"),
        QUESTION_TEXT=subject.question_text,
        DATA=subject.data,
        ANSWER=subject.answer,
    )


def _render_stat_grounding(subject: ResidueSubject) -> str:
    """가시 필드 = 발문 + 데이터 + 기계가 검산한 통계량 설명."""
    return fill(
        prompt_text("l3.cross_verify.statistical_grounding_user"),
        QUESTION_TEXT=subject.question_text,
        DATA=subject.data,
        MACHINE_STAT_KO=subject.machine_model_ko,
    )


def _parse_numeric_value(raw: object) -> float | None:
    """LLM 재계산 값 파싱 — 정수·실수·'a/b' 분수를 float로."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        text = raw.strip().replace(" ", "")
        if "/" in text:
            try:
                num, den = text.split("/", 1)
                return float(num) / float(den)
            except ValueError:
                return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _judge_stat_reconstruct(
    subject: ResidueSubject, data: Mapping[str, object]
) -> PerspectiveVerdict:
    """LLM이 독립적으로 계산한 통계량 vs 기계 계산값 — **기계가** 판정한다."""
    raw_value = data.get("value")
    if raw_value is None:
        return PerspectiveVerdict(
            principle="statistical_reconstruction",
            verdict="unclear",
            defect_class="reconstruction_declined",
            reason=f"독립 재계산 실패: {data.get('reason', '사유 미제시')}",
        )
    llm_value = _parse_numeric_value(raw_value)
    if llm_value is None:
        return PerspectiveVerdict(
            principle="statistical_reconstruction",
            verdict="unclear",
            defect_class="value_unparsed",
            reason=f"재계산 값을 숫자로 읽을 수 없음(value={raw_value!r}).",
        )
    if subject.machine_value is None:
        return PerspectiveVerdict(
            principle="statistical_reconstruction",
            verdict="unclear",
            defect_class="machine_value_missing",
            reason="기계 계산값이 없어 대조 불가.",
        )
    if math.isclose(llm_value, subject.machine_value, rel_tol=1e-9, abs_tol=1e-9):
        return PerspectiveVerdict(
            principle="statistical_reconstruction",
            verdict="ok",
            defect_class="",
            reason=f"독립 재계산 일치({llm_value}).",
        )
    return PerspectiveVerdict(
        principle="statistical_reconstruction",
        verdict="defect",
        defect_class="model_mismatch",
        reason=(
            f"독립 재계산 불일치 — 재계산 {llm_value} vs 기계 계산 "
            f"{subject.machine_value}. 발문이 기계가 검산한 자료·통계량과 다르게 읽힐 소지."
        ),
    )


STATISTICAL_PERSPECTIVES: tuple[Perspective, ...] = (
    Perspective(
        principle="statistical_reconstruction",
        system_prompt=_SYSTEM_STAT_RECONSTRUCT,
        visible_fields=frozenset({"question_text", "data"}),
        render=_render_stat_reconstruct,
        judge=_judge_stat_reconstruct,
    ),
    Perspective(
        principle="statistical_falsification",
        system_prompt=_SYSTEM_STAT_FALSIFY,
        visible_fields=frozenset({"question_text", "data", "answer"}),
        render=_render_stat_falsify,
        judge=_judge_labelled("statistical_falsification"),
    ),
    Perspective(
        principle="statistical_grounding",
        system_prompt=_SYSTEM_STAT_GROUNDING,
        visible_fields=frozenset({"question_text", "data", "machine_model_ko"}),
        render=_render_stat_grounding,
        judge=_judge_labelled("statistical_grounding"),
    ),
)
"""통계 자료형 K=3 관점 — 원리·프롬프트·가시 필드가 모두 다르다."""


@dataclass(frozen=True, slots=True)
class CrossVerificationResult:
    """대상 1건의 교차검증 결과 — 관점별 판정 + 집계.

    집계 규칙(보수적 — "검증 없이 학생에게 제공 금지"):
      - 하나라도 `defect` → **defect**(반증 우선. 다수결이 아니다 — 결함 지목은 다수결로
        덮이지 않는다).
      - 그 외 하나라도 `unclear` → **unclear**(*측정 실패*이며 통과가 아니다).
      - 전 관점 `ok` → **ok**(만장일치만 통과).
    """

    problem_id: str
    verdicts: tuple[PerspectiveVerdict, ...]
    aggregate: ResidueVerdictLabel
    defect_class: str
    reason: str


def _aggregate(problem_id: str, verdicts: Sequence[PerspectiveVerdict]) -> CrossVerificationResult:
    defects = [v for v in verdicts if v.verdict == "defect"]
    if defects:
        first = defects[0]
        return CrossVerificationResult(
            problem_id=problem_id,
            verdicts=tuple(verdicts),
            aggregate="defect",
            defect_class=f"{first.principle}:{first.defect_class}",
            reason=" | ".join(f"[{v.principle}] {v.reason}" for v in defects),
        )
    unclear = [v for v in verdicts if v.verdict == "unclear"]
    if unclear:
        first = unclear[0]
        return CrossVerificationResult(
            problem_id=problem_id,
            verdicts=tuple(verdicts),
            aggregate="unclear",
            defect_class=f"{first.principle}:{first.defect_class}",
            reason=" | ".join(f"[{v.principle}] {v.reason}" for v in unclear),
        )
    return CrossVerificationResult(
        problem_id=problem_id,
        verdicts=tuple(verdicts),
        aggregate="ok",
        defect_class="",
        reason=f"K={len(verdicts)} 관점 만장일치 ok.",
    )


def _assert_independent(perspectives: Sequence[Perspective], min_k: int) -> None:
    """관점 구성의 독립성을 *구성 시점에* 기계로 강제 — 선언이 아니라 검사."""
    if len(perspectives) < min_k:
        raise IndependenceError(f"관점 수 {len(perspectives)} < 최소 K={min_k}(다관점 아님)")
    principles = [p.principle for p in perspectives]
    if len(set(principles)) != len(principles):
        raise IndependenceError(f"원리 중복 — 같은 원리 반복은 독립이 아님: {principles}")
    prompts = [p.system_prompt for p in perspectives]
    if len(set(prompts)) != len(prompts):
        raise IndependenceError("시스템 프롬프트 중복 — 같은 프롬프트 K회는 독립이 아님")
    fields = [p.visible_fields for p in perspectives]
    if len(set(fields)) != len(fields):
        raise IndependenceError(
            "가시 필드 집합 중복 — 같은 정보를 보는 관점은 같은 앵커링을 공유해 독립이 아님"
        )
    for perspective in perspectives:
        unknown = perspective.visible_fields - _FIELD_NAMES
        if unknown:
            raise IndependenceError(f"미지 가시 필드 {sorted(unknown)}({perspective.principle})")


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(raw: str) -> dict[str, object] | None:
    """코드펜스·주변 산문을 허용하는 관대 파싱(llm_generator `_extract_json` 동형)."""
    match = _JSON_BLOCK.search(raw)
    if match is None:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


class CrossVerifier:
    """독립 다관점 LLM 교차검증기 — 라우터 경유·관측 기록·생성자≠검증자 강제.

    provider 주입(테스트=결정론 fake). None이면 표준 `CompositeProvider`를 지연 구성한다
    (구성만으로 네트워크 0 — `LLMEquivalentProblemGenerator` 동형).
    """

    def __init__(
        self,
        provider: LLMProvider | None = None,
        *,
        perspectives: Sequence[Perspective] = PROBABILITY_PERSPECTIVES,
        min_perspectives: int = MIN_PERSPECTIVES,
        settings: Settings | None = None,
        trace: TraceSink | None = None,
        subscription: str = _STUDENT_ESCALATION_DEFAULTS.student_subscription,
        difficulty: str = "medium",
    ) -> None:
        _assert_independent(perspectives, min_perspectives)
        if provider is None:
            from whymath_backend.l3.providers.composite import CompositeProvider
            from whymath_backend.l3.providers.factory import build_cloud_provider
            from whymath_backend.l3.providers.ollama import OllamaProvider

            provider = CompositeProvider(local=OllamaProvider(), cloud=build_cloud_provider())
        if trace is None:
            from whymath_backend.l3.trace.langfuse_sink import LangfuseSink

            trace = LangfuseSink(settings=settings)
        self._provider = provider
        self._trace = trace
        self._perspectives = tuple(perspectives)
        self._subscription = subscription
        self._difficulty = difficulty

    # ── 라우팅(호출지점 ⑤ 자기검증 좌석) ────────────────────────────────
    def _routing_request(self) -> RoutingRequest:
        """검증 호출의 라우팅 신호 — task_type='verify'·call_site=⑤.

        호출지점 ⑤는 03a에서 "생성 결과를 *별도 LLM 호출로* 재검토"의 좌석이다(라우터가
        QUALITY 비동기로 보낸다). 이름은 '자기검증'이지만 본 모듈의 대상은 *다른 주체가
        만든* 문항이며 생성자≠검증자를 별도로 강제한다 — 라우팅 좌석만 공유한다.
        """
        return RoutingRequest(
            task_type="verify",
            difficulty=self._difficulty,
            requires_reasoning=True,
            student_subscription=self._subscription,
            budget_krw=_STUDENT_ESCALATION_DEFAULTS.budget_krw,  # 단일 좌석 값(OPS-18·회귀 0)
            call_site=CallSite.SELF_VERIFY,
            sync=False,
            # 등급: 교차검증 대상은 *자체 저작 코퍼스의 문항*이다(2026-09-01 실측 —
            # data/corpus 전 27개 pool이 whymath-original). AIHub 유래 자료가 저작
            # 입력이 되면 `SELF_AUTHORED_CORPUS` 한 자리만 고치면 이 경로도 함께 잠긴다.
            data_licenses=SELF_AUTHORED_CORPUS,
        )

    @property
    def signature(self) -> str:
        """검증자 서명 — 라우터가 고른 실제 모델 id. 생성자 서명과의 충돌 검사에 쓴다."""
        decision = Router().route(self._routing_request())
        if decision.cost_tier == CostTier.LOCAL.value:
            return f"llm:{resolve_model(decision.local_family, decision.local_model)}"
        return f"llm:{decision.cost_tier}"

    def _record_trace(self, decision: RoutingDecision, usage: Usage | None) -> None:
        """호출 1건의 라우팅·실측을 관측에 남긴다 — never-break(배치 비차단·타입명 로그)."""
        is_cloud = decision.cost_tier != CostTier.LOCAL.value
        if usage is None or (
            is_cloud and (usage.input_tokens is None or usage.output_tokens is None)
        ):
            cost_krw: float | None = None
        else:
            cost_krw = actual_cost_krw(decision, usage)
        try:
            self._trace.record(
                langfuse_fields(
                    decision,
                    cache_hit=False,
                    call_site=CallSite.SELF_VERIFY,
                    usage=usage,
                    cost_krw=cost_krw,
                )
            )
        except Exception as exc:  # noqa: BLE001 — 관측 장애가 검증 배치를 깨면 안 됨
            _LOGGER.warning("교차검증 관측 기록 실패(%s) — 무시하고 계속", type(exc).__name__)

    # ── 검증 ───────────────────────────────────────────────────────────
    def verify(
        self,
        subject: ResidueSubject,
        perspectives: Sequence[Perspective] | None = None,
    ) -> CrossVerificationResult:
        """대상 1건을 K개 관점으로 교차검증. 관점 실패는 unclear(측정 실패·통과 아님).

        `perspectives`가 주어지면 해당 관점 집합을, 아니면 인스턴스 기본 관점을 사용한다.
        도메인별 관점 분기는 `Verifier`가 담당한다.

        동기 API로 유지하면서 async provider 호출은 내부에서 새 이벤트 루프를 열어 실행한다.
        호출부가 이미 async loop 안에 있을 경우 `asyncio.to_thread()`로 격리해 충돌을 피한다.
        """
        if subject.authored_by == self.signature:
            raise IndependenceError(
                f"생성자와 검증자가 같은 주체({subject.authored_by}) — 자기승인 금지"
            )
        perspectives_to_use = self._perspectives if perspectives is None else perspectives
        decision = Router().route(self._routing_request())
        return asyncio.run(self._verify_async(subject, decision, perspectives_to_use))

    async def _verify_async(
        self,
        subject: ResidueSubject,
        decision: RoutingDecision,
        perspectives: Sequence[Perspective],
    ) -> CrossVerificationResult:
        """관점별 판정을 순차 await하고 집계한다."""
        verdicts: list[PerspectiveVerdict] = []
        for perspective in perspectives:
            verdict = await self._run_perspective(perspective, subject, decision)
            verdicts.append(verdict)
        return _aggregate(subject.problem_id, verdicts)

    async def _run_perspective(
        self, perspective: Perspective, subject: ResidueSubject, decision: RoutingDecision
    ) -> PerspectiveVerdict:
        try:
            generated = await self._provider.generate(
                perspective.render(subject),
                perspective.system_prompt,
                decision,
            )
        except Exception as exc:  # noqa: BLE001 — provider 장애로 배치가 죽으면 안 됨
            # 침묵 실패 금지 — 예외 *타입명*을 사유에 남긴다(값·시크릿은 제외).
            _LOGGER.warning(
                "교차검증 provider 호출 실패(%s·%s) — unclear 기록",
                perspective.principle,
                type(exc).__name__,
            )
            return PerspectiveVerdict(
                perspective.principle,
                "unclear",
                "provider_error",
                f"provider 호출 실패({type(exc).__name__}) — 측정 실패로 기록.",
            )
        self._record_trace(decision, generated.usage)
        data = _extract_json(generated.text)
        if data is None:
            return PerspectiveVerdict(
                perspective.principle,
                "unclear",
                "response_unparsed",
                "응답에서 JSON을 읽을 수 없음 — 측정 실패로 기록.",
            )
        return perspective.judge(subject, data)

    def flush_trace(self) -> None:
        """배치 종료 시 관측 전송 확정 — flush 없는 sink는 조용히 통과(계약 밖 표면)."""
        flush = getattr(self._trace, "flush", None)
        if not callable(flush):
            return
        try:
            flush()
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("교차검증 관측 flush 실패(%s) — 무시하고 계속", type(exc).__name__)
