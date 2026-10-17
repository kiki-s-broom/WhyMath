"""QUALITY 티어 dense 27B ↔ MoE 정확도 축 강등전 (OPS-48).

`qwen3.5:27b`(dense·현 QUALITY)와 `qwen3:30b-a3b`(MoE·후보)를 **같은 결함 주입 시험지**로
대조한다. 시험지는 `l3/equivalent/defect_seeder`가 결정론으로 만들며, 정답지(defect_class)
는 우리가 100% 안다. 두 모델에게 각 문항의 결함 여부를 묻고, 검출률·오경보율을 Wilson 단측
경계로 계산한다.

판정 원칙:
  - 속도가 6배여도 검출률이 떨어지거나 오경보가 높아지면 채택하지 않는다.
  - "인상"이 아니라 Wilson 단측 경계 + CLI exit 0/1.
  - 20%p 미만 차이는 "유의하다"고 하지 않는다(이전 세션 재현성 8~18%).

사용(Phaiakes9):
    python -m whymath_backend.harness.quality_tier_moe_accuracy_battle \
        --baseline-model qwen3.5:27b --candidate-model qwen3:30b-a3b \
        --n-defective 70 --n-clean 70 --audit-out data/audit/ops-48

게이트:
    --min-detection-lower 0.75 --max-false-alarm-upper 0.10
    --require-candidate-not-worse-than-baseline
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from whymath_backend.harness.wilson import wilson_lower_bound, wilson_upper_bound
from whymath_backend.l3.equivalent.defect_seeder import (
    DEFECT_CLASSES,
    DefectClass,
    SeededItem,
    build_defect_seeded_set,
)
from whymath_backend.l3.models import (
    CostTier,
    GenerationResult,
    LocalModelTier,
    RoutingDecision,
)
from whymath_backend.l3.providers.ollama import FixedModelOllamaProvider, _OllamaClient

_EXIT_OK = 0
_EXIT_GATE_FAIL = 1
_EXIT_INPUT_ERROR = 2


class _ParsedVerdict(BaseModel):
    """LLM이 낸 결함 판정 — has_defect는 필수, defect_class는 선택."""

    model_config = ConfigDict(extra="forbid")

    has_defect: bool = Field(..., description="결함이 있는가?")
    defect_class: str | None = Field(
        default=None,
        description=f"결함 유형 — {DEFECT_CLASSES} 중 하나 또는 null/unknown.",
    )
    reason: str | None = Field(default=None, description="판정 근거(진단용).")


class ModelOutcome(BaseModel):
    """한 모델이 한 문항에 대해 내 판정 + 정답지 + 측정값."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str = Field(description="호출한 Ollama 모델 ID.")
    slug: str = Field(description="문항 slug.")
    ground_truth: DefectClass | None = Field(description="정답지(None=무결함).")
    detected: bool = Field(description="모델이 '결함 있음'이라고 했는가.")
    predicted_class: str | None = Field(description="모델이 말한 결함 유형(파싱된 경우).")
    parsed: bool = Field(description="응답 파싱 성공 여부.")
    parse_error: str | None = Field(default=None, description="파싱/호출 오류 기록.")
    failure_kind: str | None = Field(
        default=None,
        description="미분류 원인(OPS-50) — truncated(출력 상한 절단)·malformed·empty·transport.",
    )
    latency_ms: float | None = Field(default=None, description="해당 호출 실측 지연(ms).")
    input_tokens: int | None = Field(default=None)
    output_tokens: int | None = Field(default=None)
    raw_response: str = Field(default="", description="모델 원시 응답(디버그·감사용).")


@dataclass(slots=True, frozen=True)
class DetectionMetrics:
    """이진 검출 메트릭 — Wilson 경계 포함."""

    true_positives: int
    false_negatives: int
    false_positives: int
    true_negatives: int
    unresolved: int
    # OPS-50 ⑤ — 미분류를 정답지별로 나눠 센다(B·C 집계의 분모/분자). 기본 0은 구 호출부 호환.
    unresolved_defective: int = 0
    unresolved_clean: int = 0

    @property
    def defective_total(self) -> int:
        return self.true_positives + self.false_negatives

    @property
    def clean_total(self) -> int:
        return self.false_positives + self.true_negatives

    @property
    def detection_rate(self) -> float | None:
        if self.defective_total == 0:
            return None
        return self.true_positives / self.defective_total

    @property
    def false_alarm_rate(self) -> float | None:
        if self.clean_total == 0:
            return None
        return self.false_positives / self.clean_total

    @property
    def unresolved_rate(self) -> float | None:
        total = self.defective_total + self.clean_total + self.unresolved
        if total == 0:
            return None
        return self.unresolved / total

    def detection_lower_bound(self, confidence: float = 0.95) -> float | None:
        if self.defective_total == 0:
            return None
        return wilson_lower_bound(self.true_positives, self.defective_total, confidence)

    def worst_case_detection_lower_bound(self, confidence: float = 0.95) -> float | None:
        """B 집계 — 결함 문항의 미분류를 '놓침'으로 센 검출률 Wilson 하한."""
        total = self.defective_total + self.unresolved_defective
        if total == 0:
            return None
        return wilson_lower_bound(self.true_positives, total, confidence)

    def worst_case_false_alarm_upper_bound(self, confidence: float = 0.95) -> float | None:
        """C 집계 — 무결함 문항의 미분류를 '오경보'로 센 오경보율 Wilson 상한."""
        total = self.clean_total + self.unresolved_clean
        if total == 0:
            return None
        return wilson_upper_bound(self.false_positives + self.unresolved_clean, total, confidence)

    def false_alarm_upper_bound(self, confidence: float = 0.95) -> float | None:
        if self.clean_total == 0:
            return None
        return wilson_upper_bound(self.false_positives, self.clean_total, confidence)


class ModelReport(BaseModel):
    """한 모델의 전체 리포트."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str
    n_items: int
    metrics: DetectionMetrics
    latency_ms: dict[str, float | None]
    per_class: dict[str, tuple[int, int]]  # defect_class → (detected, total)
    failure_kinds: dict[str, int] = Field(default_factory=dict)  # OPS-50: 미분류 원인별 건수


class BattleReport(BaseModel):
    """두 모델 대조 리포트."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    baseline: ModelReport
    candidate: ModelReport
    n_defective: int
    n_clean: int
    seed: int
    confidence: float
    baseline_model_id: str
    candidate_model_id: str
    prompt_variant: str = "baseline"  # OPS-50: 후보에 적용한 프롬프트 변형


# ──────────────────────────────────────────────────────────────────────────
# 프롬프트 / JSON schema
# ──────────────────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """당신은 중·고등학생용 수학 학습 앱의 문항 품질 검수자입니다.
주어진 문항에 결함이 있는지 판정하고, 반드시 JSON 형식으로만 답하세요.

결함 유형:
- answer_error: 정답이 계산상 틀림
- explanation_slip: 해설에 거짓 수치/등식이 섞임
- condition_mismatch: 조건식이 변조되어 제시된 정답이 실제 해가 아님
- standard_tag_error: 성취기준 코드가 잘못 붙음
- distractor_misattribution: 객관식 오답 선지가 잘못된 오개념에 귀속됨
- statement_mismatch: 발문의 수식/문장과 검산 조건이 서로 다름
- broken_latex: LaTeX 수식 표기가 깨짐(중괄호 짝 불일치 등)

응답 형식(반드시 JSON만):
{"has_defect": true/false, "defect_class": "answer_error" 또는 null, "reason": "짧은 근거"}

has_defect가 false면 defect_class는 null로 하세요."""


def _format_item(item: SeededItem) -> str:
    """SeededItem → LLM 프롬프트 본문."""
    problem = item.candidate.problem
    lines: list[str] = []
    lines.append(f"[문항 slug] {problem.slug}")
    lines.append(f"[발문] {problem.question_text}")
    if problem.choices:
        lines.append("[선택지]")
        for idx, choice in enumerate(problem.choices, start=1):
            lines.append(f"  {idx}. {choice}")
    lines.append(f"[정답] {problem.answer}")
    if problem.answer_explanation:
        lines.append(f"[해설] {problem.answer_explanation}")
    if problem.achievement_standard_codes:
        lines.append(f"[성취기준] {', '.join(problem.achievement_standard_codes)}")
    if problem.distractor_map:
        lines.append("[오답 오개념]")
        for entry in problem.distractor_map:
            lines.append(f"  choices[{entry.choice_index}]: {entry.misconception_id}")
    return "\n".join(lines)


_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "has_defect": {"type": "boolean"},
        "defect_class": {"type": ["string", "null"]},
        "reason": {"type": ["string", "null"]},
    },
    "required": ["has_defect"],
}


# ──────────────────────────────────────────────────────────────────────────
# 프롬프트 변형 (OPS-50)
#
# OPS-48 감사 JSONL 재분류(OPS-50 ①): 후보 qwen3:30b-a3b 파싱 실패 16건은 전부
# output_tokens == num_predict(512)에서 `reason`이 끊긴 **출력 상한 절단**이었다. 클래스 편중
# (clean 10/50 · broken_latex 4/7)은 원인이 아니라 증상이다 — 잘린 16건은 전부 `"has_defect": true`
# 로 시작해 "판정부터 박고 뒤늦게 자기반박"하는 서술을 끝없이 늘어놓았다. 변형은 한 번에 하나만
# 바꾼다(--prompt-variant 단일 값).
#
#   baseline      OPS-48 프롬프트 그대로(재현 기준).
#   short_reason  근거를 한 문장으로 제한(프롬프트 + schema maxLength) — 절단 직접 대응.
#   reason_first  근거를 먼저 쓰고 판정을 뒤에 두는 필드 순서 — 판정 선행 패턴 대응.
#   stage_split   (a) 1단계 has_defect만 묻고, 결함일 때만 2단계로 유형을 묻는다.
#   latex_check   (b) LaTeX 형식 점검 지시를 추가한다.
#   few_shot      (c) broken_latex 예시 1건을 주입한다(시험지에 없는 자작 문항).
# ──────────────────────────────────────────────────────────────────────────
PROMPT_VARIANTS: tuple[str, ...] = (
    "baseline",
    "short_reason",
    "reason_first",
    "stage_split",
    "latex_check",
    "few_shot",
)

# 기준 프롬프트에서 역할·결함 유형 목록(앞)과 출력 규약(뒤)을 가르는 표지.
_FORMAT_MARKER = "응답 형식"

# 근거 길이 상한(문자). 한글 1자 ≈ 1~2토큰이므로 100자 ≤ 200토큰 < num_predict 512.
_SHORT_REASON_MAX_CHARS = 100
_REASON_FIRST_MAX_CHARS = 160

_SHORT_REASON_ADDENDUM = (
    "\n\nreason은 반드시 한 문장(80자 이내)으로만 쓰세요. "
    "계산 과정을 되풀이하거나 앞선 판단을 스스로 반박하지 마세요."
)

_LATEX_CHECK_ADDENDUM = """

LaTeX 점검(수식이 있는 문항은 판정 전에 반드시 확인):
- 발문·선택지·해설의 `$...$` 안에서 `{`와 `}`의 개수가 같은지 본다.
- `\\frac`·`\\sqrt` 등 인자를 받는 명령에 `{}`가 빠짐없이 붙었는지 본다.
- `\\left`와 `\\right`가 짝을 이루는지 본다.
수식 표기가 깨졌으면 has_defect를 true, defect_class를 broken_latex로 하세요.
수식 표기가 온전하면 broken_latex로 판정하지 마세요."""

# 시험지(이차방정식 계열)와 겹치지 않는 자작 예시 — 거리 공식 문항의 `\sqrt{` 중괄호 미닫힘.
_FEW_SHOT_ADDENDUM = """

예시(참고용 — 아래 문항은 실제 검수 대상이 아닙니다):
[문항 slug] example-distance
[발문] 두 점 A(1, 2), B(4, 6) 사이의 거리를 구하시오.
거리 공식은 $d=\\sqrt{(x_2-x_1)^2+(y_2-y_1)^2$ 이다.
[정답] 5
=> {"has_defect": true, "defect_class": "broken_latex", "reason": "sqrt의 중괄호가 닫히지 않음"}"""


@dataclass(slots=True, frozen=True)
class PromptVariant:
    """한 변형의 호출 규약. `stage2_*`가 있으면 2단계 호출(stage_split)이다."""

    name: str
    system: str
    json_schema: dict[str, Any]
    stage2_system: str | None = None
    stage2_json_schema: dict[str, Any] | None = None

    @property
    def two_stage(self) -> bool:
        return self.stage2_system is not None


def _prompt_head(base_system: str) -> str:
    """기준 프롬프트의 '응답 형식' 이전 부분(역할·결함 유형 목록)."""
    head, sep, _tail = base_system.partition(_FORMAT_MARKER)
    if not sep:
        # 기준 프롬프트 구조가 바뀌면 조용히 엉뚱한 프롬프트를 만들지 않고 즉시 멈춘다.
        raise ValueError(f"기준 프롬프트에 '{_FORMAT_MARKER}' 표지가 없다 — 변형을 만들 수 없다.")
    return head.rstrip() + "\n\n"


def _object_schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required}


def build_variant(
    name: str,
    *,
    base_system: str | None = None,
    base_schema: dict[str, Any] | None = None,
) -> PromptVariant:
    """변형 이름 → 호출 규약. 알 수 없는 이름은 ValueError."""
    system0 = _SYSTEM_PROMPT if base_system is None else base_system
    schema0 = _JSON_SCHEMA if base_schema is None else base_schema

    if name == "baseline":
        return PromptVariant(name=name, system=system0, json_schema=schema0)

    if name == "short_reason":
        props = dict(schema0["properties"])
        # reason을 null 허용 유니온 대신 단순 string으로 — 문법 제약이 단순할수록 안전하다.
        props["reason"] = {"type": "string", "maxLength": _SHORT_REASON_MAX_CHARS}
        return PromptVariant(
            name=name,
            system=system0 + _SHORT_REASON_ADDENDUM,
            json_schema=_object_schema(props, list(schema0["required"])),
        )

    if name == "reason_first":
        system = (
            _prompt_head(system0)
            + "응답 형식(반드시 JSON만, 키 순서 고정 — 근거를 먼저 쓰고 판정하세요):\n"
            '{"reason": "근거 한 문장", "has_defect": true/false, '
            '"defect_class": "answer_error" 또는 null}\n\n'
            "reason은 한 문장(120자 이내)으로 쓰고, "
            "has_defect가 false면 defect_class는 null로 하세요."
        )
        # 속성 선언 순서가 생성 순서다 — reason을 필수로 두어 항상 맨 앞에 나오게 한다.
        props = {
            "reason": {"type": "string", "maxLength": _REASON_FIRST_MAX_CHARS},
            "has_defect": {"type": "boolean"},
            "defect_class": {"type": ["string", "null"]},
        }
        return PromptVariant(
            name=name, system=system, json_schema=_object_schema(props, ["reason", "has_defect"])
        )

    if name == "stage_split":
        head = _prompt_head(system0)
        stage1 = (
            head + '응답 형식(반드시 JSON만): {"has_defect": true/false}\n'
            "결함 유형은 묻지 않습니다. 결함이 있는지 없는지만 답하세요."
        )
        stage2 = (
            head + '응답 형식(반드시 JSON만): {"defect_class": "<결함 유형 하나>"}\n'
            "이 문항에는 결함이 있습니다. 위 결함 유형 중 가장 알맞은 하나만 고르세요."
        )
        return PromptVariant(
            name=name,
            system=stage1,
            json_schema=_object_schema({"has_defect": {"type": "boolean"}}, ["has_defect"]),
            stage2_system=stage2,
            stage2_json_schema=_object_schema(
                {"defect_class": {"type": "string", "enum": list(DEFECT_CLASSES)}},
                ["defect_class"],
            ),
        )

    if name == "latex_check":
        return PromptVariant(name=name, system=system0 + _LATEX_CHECK_ADDENDUM, json_schema=schema0)

    if name == "few_shot":
        return PromptVariant(name=name, system=system0 + _FEW_SHOT_ADDENDUM, json_schema=schema0)

    raise ValueError(f"알 수 없는 프롬프트 변형: {name!r} (허용: {', '.join(PROMPT_VARIANTS)})")


_JSON_RE = re.compile(r"\{.*?\}", re.DOTALL)


def _parse_response(text: str) -> tuple[_ParsedVerdict, bool, str]:
    """원시 응답 → ParsedVerdict. (verdict, parsed_ok, parse_error)."""
    if not text:
        return _ParsedVerdict(has_defect=False), False, "empty response"

    # 1) JSON schema format 사용 시 응답 자체가 JSON.
    # 2) 자유 텍스트 + 코드펜스 fallback.
    candidates: list[str] = []
    candidates.append(text.strip())
    code_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if code_match:
        candidates.append(code_match.group(1))
    for m in _JSON_RE.finditer(text):
        candidates.append(m.group(0))

    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        has_defect = data.get("has_defect")
        if not isinstance(has_defect, bool):
            # "true"/"false" 문자열이라도 받아들인다.
            if isinstance(has_defect, str):
                has_defect = has_defect.strip().lower() == "true"
            else:
                continue
        defect_class = data.get("defect_class")
        if defect_class is not None and not isinstance(defect_class, str):
            defect_class = None
        reason = data.get("reason")
        if reason is not None and not isinstance(reason, str):
            reason = None
        return (
            _ParsedVerdict(
                has_defect=has_defect,
                defect_class=defect_class or None,
                reason=reason,
            ),
            True,
            "",
        )

    # 최후의 fallback — 텍스트에 "결함" / "defect" / "오류"가 있으면 detected.
    lowered = text.lower()
    fallback_detected = any(k in lowered for k in ("결함", "defect", "오류", "잘못"))
    return (
        _ParsedVerdict(has_defect=fallback_detected, defect_class=None, reason=None),
        False,
        "json parse failed, heuristic fallback used",
    )


# ──────────────────────────────────────────────────────────────────────────
# 비동기 평가
# ──────────────────────────────────────────────────────────────────────────
def _quality_routing_decision() -> RoutingDecision:
    """QUALITY 티어 평가용 RoutingDecision — FixedModelOllamaProvider는 model_id만 본다."""
    return RoutingDecision(
        cost_tier=CostTier.LOCAL,
        local_model=LocalModelTier.QUALITY,
        mode="async",
        reason="OPS-48 fixed-model quality battle",
        est_latency_ms=0,
    )


_CLASS_RE = re.compile(r'"defect_class"\s*:\s*"([^"]+)"')


def _classify_failure(text: str, output_tokens: int | None, num_predict: int | None) -> str:
    """파싱 실패 원인 — 숫자가 아니라 원인이 남아야 실패가 정보가 된다(OPS-50)."""
    if not text.strip():
        return "empty"
    if num_predict is not None and output_tokens is not None and output_tokens >= num_predict:
        return "truncated"
    return "malformed"


async def _evaluate_one(
    provider: FixedModelOllamaProvider,
    item: SeededItem,
    *,
    semaphore: asyncio.Semaphore,
    json_schema: dict[str, Any] | None,
    variant: PromptVariant | None = None,
    num_predict: int | None = None,
) -> ModelOutcome:
    """한 문항에 대해 LLM 호출 → 파싱 → ModelOutcome.

    `provider.generate` 직접 호출 자리는 이 함수의 루프 안 1곳으로 동결돼 있다
    (`test_authoring_traffic_surface_inventory`). stage_split 변형의 2단계 호출도 같은 루프다.
    """
    prompt = "다음 문항을 검수하세요.\n\n" + _format_item(item)
    if variant is None:
        # 변형 미지정 — OPS-48 호출 규약 그대로(호출자가 준 schema를 쓴다).
        stages: list[tuple[str, dict[str, Any] | None]] = [(_SYSTEM_PROMPT, json_schema)]
    else:
        use_schema = json_schema is not None  # --no-json-schema면 모든 단계에서 끈다
        stages = [(variant.system, variant.json_schema if use_schema else None)]
        if variant.stage2_system is not None:
            stages.append(
                (variant.stage2_system, variant.stage2_json_schema if use_schema else None)
            )

    slug = item.candidate.problem.slug or ""
    texts: list[str] = []
    latency_total = 0.0
    latency_seen = False
    in_tokens = 0
    out_tokens = 0
    usage_seen = False
    verdict = _ParsedVerdict(has_defect=False)
    parsed = False
    parse_error = ""
    predicted_class: str | None = None

    for index, (system, schema) in enumerate(stages):
        async with semaphore:
            try:
                result: GenerationResult = await provider.generate(
                    prompt=prompt,
                    system=system,
                    decision=_quality_routing_decision(),
                    temperature=0.0,
                    json_schema=schema,
                )
            except Exception as exc:  # noqa: BLE001 — 네트워크·모델 오류는 unresolved로 기록
                return ModelOutcome(
                    model_id=provider._model_id,  # noqa: SLF001 — 동일 클래스 내부 접근
                    slug=slug,
                    ground_truth=item.defect_class,
                    detected=False,
                    predicted_class=None,
                    parsed=False,
                    parse_error=f"{type(exc).__name__}: {exc}",
                    failure_kind="transport",
                    raw_response="\n---\n".join(texts),
                )
        texts.append(result.text)
        if result.usage is not None:
            usage_seen = True
            latency_seen = latency_seen or result.usage.latency_ms is not None
            latency_total += result.usage.latency_ms or 0.0
            in_tokens += result.usage.input_tokens or 0
            out_tokens += result.usage.output_tokens or 0
        if index == 0:
            verdict, parsed, parse_error = _parse_response(result.text)
            predicted_class = verdict.defect_class
            if not parsed or not verdict.has_defect:
                break  # 미분류이거나 무결함 판정 — 2단계(유형 질문)는 결함일 때만
        else:
            match = _CLASS_RE.search(result.text)
            predicted_class = match.group(1) if match else None
            if predicted_class is None:
                parse_error = "stage2 defect_class unparsed"

    text = "\n---\n".join(texts)
    return ModelOutcome(
        model_id=provider._model_id,  # noqa: SLF001
        slug=slug,
        ground_truth=item.defect_class,
        detected=verdict.has_defect,
        predicted_class=predicted_class,
        parsed=parsed,
        parse_error=parse_error or None,
        failure_kind=(
            None if parsed else _classify_failure(texts[0], out_tokens or None, num_predict)
        ),
        latency_ms=latency_total if latency_seen else None,
        input_tokens=in_tokens if usage_seen else None,
        output_tokens=out_tokens if usage_seen else None,
        raw_response=text,
    )


async def evaluate_model(
    model_id: str,
    items: list[SeededItem],
    *,
    ollama_host: str | None = None,
    timeout: float = 600.0,
    num_ctx: int = 8192,
    num_predict: int | None = 512,
    concurrency: int = 1,
    json_schema: dict[str, Any] | None = None,
    client: _OllamaClient | None = None,
    variant: PromptVariant | None = None,
) -> list[ModelOutcome]:
    """주어진 모델로 전체 시험지를 평가한다."""
    from whymath_backend.config import get_settings

    settings = get_settings()
    if ollama_host is not None:
        settings = settings.model_copy(update={"ollama_host": ollama_host})
    provider = FixedModelOllamaProvider(
        model_id=model_id,
        client=client,
        settings=settings,
        timeout=timeout,
        num_ctx=num_ctx,
        num_predict=num_predict,
    )
    semaphore = asyncio.Semaphore(max(1, concurrency))
    coros = [
        _evaluate_one(
            provider,
            item,
            semaphore=semaphore,
            json_schema=json_schema,
            variant=variant,
            num_predict=num_predict,
        )
        for item in items
    ]
    return await asyncio.gather(*coros)


# ──────────────────────────────────────────────────────────────────────────
# 집계 / 리포트
# ──────────────────────────────────────────────────────────────────────────
def _summarize(model_id: str, outcomes: list[ModelOutcome]) -> ModelReport:
    """ModelOutcome 리스트 → DetectionMetrics + per_class + latency."""
    tp = fn = fp = tn = unresolved = 0
    unresolved_defective = unresolved_clean = 0
    failure_kinds: dict[str, int] = {}
    per_class: dict[str, list[int]] = {name: [0, 0] for name in DEFECT_CLASSES}
    latencies: list[float] = []
    for o in outcomes:
        if o.ground_truth is not None:
            per_class[o.ground_truth][1] += 1
        if o.detected and o.ground_truth is not None and o.ground_truth == o.predicted_class:
            per_class[o.ground_truth][0] += 1
        if not o.parsed:
            unresolved += 1
            if o.ground_truth is None:
                unresolved_clean += 1
            else:
                unresolved_defective += 1
            kind = o.failure_kind or "unknown"
            failure_kinds[kind] = failure_kinds.get(kind, 0) + 1
            continue
        if o.ground_truth is None:
            if o.detected:
                fp += 1
            else:
                tn += 1
        else:
            if o.detected:
                tp += 1
            else:
                fn += 1
        if o.latency_ms is not None:
            latencies.append(o.latency_ms)

    metrics = DetectionMetrics(
        true_positives=tp,
        false_negatives=fn,
        false_positives=fp,
        true_negatives=tn,
        unresolved=unresolved,
        unresolved_defective=unresolved_defective,
        unresolved_clean=unresolved_clean,
    )
    latency_report: dict[str, float | None] = {
        "mean": statistics.mean(latencies) if latencies else None,
        "median": statistics.median(latencies) if latencies else None,
        "min": min(latencies) if latencies else None,
        "max": max(latencies) if latencies else None,
        "p90": (statistics.quantiles(latencies, n=10)[8] if len(latencies) >= 10 else None),
    }
    return ModelReport(
        model_id=model_id,
        n_items=len(outcomes),
        metrics=metrics,
        latency_ms=latency_report,
        per_class={name: (v[0], v[1]) for name, v in per_class.items()},
        failure_kinds=failure_kinds,
    )


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _render_model_report(report: ModelReport, *, confidence: float) -> list[str]:
    pct = round(confidence * 100)
    m = report.metrics
    lines: list[str] = []
    lines.append(f"  모델: {report.model_id}")
    lines.append(
        f"  처리 문항: {report.n_items} (결함 {m.defective_total} / 무결함 {m.clean_total})"
    )
    lines.append(
        f"  미분류/파싱실패: {m.unresolved} (결함 {m.unresolved_defective} · "
        f"무결함 {m.unresolved_clean} · 실패율 {_fmt(m.unresolved_rate)})"
    )
    if report.failure_kinds:
        kinds = ", ".join(f"{k} {v}" for k, v in sorted(report.failure_kinds.items()))
        lines.append(f"  미분류 원인: {kinds}")
    dlb = _fmt(m.detection_lower_bound(confidence))
    lines.append(
        f"  결함 검출률: {m.true_positives}/{m.defective_total} "
        f"(점추정 {_fmt(m.detection_rate)} · {pct}% 하한 {dlb})"
    )
    fau = _fmt(m.false_alarm_upper_bound(confidence))
    lines.append(
        f"  무결함 오검출: {m.false_positives}/{m.clean_total} "
        f"(점추정 {_fmt(m.false_alarm_rate)} · {pct}% 상한 {fau})"
    )
    lat = report.latency_ms
    lines.append(
        f"  지연(ms): mean={_fmt(lat.get('mean'))} "
        f"median={_fmt(lat.get('median'))} max={_fmt(lat.get('max'))}"
    )
    # OPS-50 ⑤ — 미분류 처리 3종 병기. A는 판정에 쓰는 방식(미분류 제외)이다.
    lines.append("  [미분류 처리 민감도 A/B/C]")
    lines.append(f"    A 미분류 제외      검출 하한 {dlb} · 오경보 상한 {fau}")
    lines.append(
        f"    B 결함 미분류=놓침 검출 하한 {_fmt(m.worst_case_detection_lower_bound(confidence))}"
    )
    lines.append(
        f"    C 무결함 미분류=오경보 오경보 상한 "
        f"{_fmt(m.worst_case_false_alarm_upper_bound(confidence))}"
    )
    lines.append("  [결함류별(클래스 일치)]")
    for name in DEFECT_CLASSES:
        detected, total = report.per_class[name]
        rate = _fmt(detected / total) if total else "n/a"
        lines.append(f"    {name:26s} {detected:>3d}/{total:<3d} ({rate})")
    return lines


def render_report(report: BattleReport) -> str:
    """사람 가독 대조 리포트."""
    pct = round(report.confidence * 100)
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("OPS-48 QUALITY 티어 dense ↔ MoE 정확도 축 강등전")
    lines.append("=" * 72)
    lines.append(f"후보 프롬프트 변형(OPS-50): {report.prompt_variant}")
    lines.append(
        f"설정: 결함 {report.n_defective} · 무결함 {report.n_clean} "
        f"· seed {report.seed} · 신뢰수준 {pct}%"
    )
    lines.append("")
    lines.append("[기준] " + report.baseline_model_id)
    lines.extend(_render_model_report(report.baseline, confidence=report.confidence))
    lines.append("")
    lines.append("[후보] " + report.candidate_model_id)
    lines.extend(_render_model_report(report.candidate, confidence=report.confidence))
    lines.append("")
    lines.append("[대조]")
    baseline_d = report.baseline.metrics.detection_rate
    candidate_d = report.candidate.metrics.detection_rate
    baseline_f = report.baseline.metrics.false_alarm_rate
    candidate_f = report.candidate.metrics.false_alarm_rate
    d_diff = _fmt((candidate_d or 0) - (baseline_d or 0))
    f_diff = _fmt((candidate_f or 0) - (baseline_f or 0))
    lines.append(
        f"  검출률 점추정: 기준 {_fmt(baseline_d)} → 후보 {_fmt(candidate_d)} (차이 {d_diff})"
    )
    lines.append(
        f"  오검출률 점추정: 기준 {_fmt(baseline_f)} → 후보 {_fmt(candidate_f)} (차이 {f_diff})"
    )
    lines.append("=" * 72)
    return "\n".join(lines)


def report_to_json(report: BattleReport) -> dict[str, object]:
    """리포트 → JSON 직렬화 가능 dict(감사·기계 판독용)."""

    def model_json(m: ModelReport) -> dict[str, object]:
        return {
            "model_id": m.model_id,
            "n_items": m.n_items,
            "metrics": {
                "true_positives": m.metrics.true_positives,
                "false_negatives": m.metrics.false_negatives,
                "false_positives": m.metrics.false_positives,
                "true_negatives": m.metrics.true_negatives,
                "unresolved": m.metrics.unresolved,
                "unresolved_defective": m.metrics.unresolved_defective,
                "unresolved_clean": m.metrics.unresolved_clean,
                "unresolved_rate": m.metrics.unresolved_rate,
                "worst_case_detection_lower_bound": m.metrics.worst_case_detection_lower_bound(),
                "worst_case_false_alarm_upper_bound": (
                    m.metrics.worst_case_false_alarm_upper_bound()
                ),
                "detection_rate": m.metrics.detection_rate,
                "false_alarm_rate": m.metrics.false_alarm_rate,
                "detection_lower_bound": m.metrics.detection_lower_bound(),
                "false_alarm_upper_bound": m.metrics.false_alarm_upper_bound(),
            },
            "latency_ms": m.latency_ms,
            "per_class": dict(m.per_class),
            "failure_kinds": dict(m.failure_kinds),
        }

    return {
        "baseline_model_id": report.baseline_model_id,
        "candidate_model_id": report.candidate_model_id,
        "n_defective": report.n_defective,
        "n_clean": report.n_clean,
        "seed": report.seed,
        "confidence": report.confidence,
        "prompt_variant": report.prompt_variant,
        "baseline": model_json(report.baseline),
        "candidate": model_json(report.candidate),
    }


# ──────────────────────────────────────────────────────────────────────────
# 감사 JSONL
# ──────────────────────────────────────────────────────────────────────────
def _outcome_json(o: ModelOutcome) -> dict[str, object]:
    return {
        "model_id": o.model_id,
        "detected": o.detected,
        "predicted_class": o.predicted_class,
        "parsed": o.parsed,
        "parse_error": o.parse_error,
        "failure_kind": o.failure_kind,
        "latency_ms": o.latency_ms,
        "input_tokens": o.input_tokens,
        "output_tokens": o.output_tokens,
        "raw_response": o.raw_response,
    }


def _write_audit(
    audit_path: Path,
    baseline_outcomes: list[ModelOutcome],
    candidate_outcomes: list[ModelOutcome],
    report: BattleReport,
) -> None:
    """문항별 판정 + as-found 요약 JSONL 저장."""
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("w", encoding="utf-8") as fh:
        for baseline, candidate in zip(baseline_outcomes, candidate_outcomes, strict=True):
            fh.write(
                json.dumps(
                    {
                        "slug": baseline.slug,
                        "ground_truth": baseline.ground_truth,
                        "baseline": _outcome_json(baseline),
                        "candidate": _outcome_json(candidate),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        b = report.baseline.metrics
        c = report.candidate.metrics
        conf = report.confidence
        summary = {
            "as_found_baseline_detection_rate": b.detection_rate,
            "as_found_baseline_false_alarm_rate": b.false_alarm_rate,
            "as_found_candidate_detection_rate": c.detection_rate,
            "as_found_candidate_false_alarm_rate": c.false_alarm_rate,
            "as_found_baseline_detection_lower_bound": b.detection_lower_bound(conf),
            "as_found_candidate_detection_lower_bound": c.detection_lower_bound(conf),
            "as_found_baseline_false_alarm_upper_bound": b.false_alarm_upper_bound(conf),
            "as_found_candidate_false_alarm_upper_bound": c.false_alarm_upper_bound(conf),
            # OPS-50 — 변형·미분류 처리 3종(A는 위 as_found, B·C는 아래).
            "prompt_variant": report.prompt_variant,
            "candidate_unresolved_rate": c.unresolved_rate,
            "candidate_worst_case_detection_lower_bound": c.worst_case_detection_lower_bound(conf),
            "candidate_worst_case_false_alarm_upper_bound": (
                c.worst_case_false_alarm_upper_bound(conf)
            ),
        }
        fh.write(json.dumps(summary, ensure_ascii=False) + "\n")


def load_baseline_outcomes(audit_path: Path, items: list[SeededItem]) -> list[ModelOutcome]:
    """이전 감사 JSONL의 기준 모델 결과를 재사용한다(27B 재실행 생략 — OPS-50).

    같은 시험지일 때만 재사용한다: 문항 수·slug 순서·정답지가 하나라도 다르면 ValueError.
    (seed/개수가 다른 시험지의 기준 결과를 섞으면 대조가 무의미해진다.)
    """
    rows = [
        json.loads(line)
        for line in audit_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rows = [r for r in rows if "slug" in r]
    if len(rows) != len(items):
        raise ValueError(f"감사 파일 문항 {len(rows)}건 ≠ 시험지 {len(items)}건 — 재사용 불가.")
    outcomes: list[ModelOutcome] = []
    for row, item in zip(rows, items, strict=True):
        slug = item.candidate.problem.slug or ""
        if row["slug"] != slug or row["ground_truth"] != item.defect_class:
            raise ValueError(f"감사 파일 문항이 시험지와 다르다: {row['slug']!r} ≠ {slug!r}")
        b = row["baseline"]
        outcomes.append(
            ModelOutcome(
                model_id=b["model_id"],
                slug=slug,
                ground_truth=item.defect_class,
                detected=b["detected"],
                predicted_class=b["predicted_class"],
                parsed=b["parsed"],
                parse_error=b.get("parse_error"),
                failure_kind=b.get("failure_kind"),
                latency_ms=b.get("latency_ms"),
                input_tokens=b.get("input_tokens"),
                output_tokens=b.get("output_tokens"),
                raw_response=b.get("raw_response", ""),
            )
        )
    return outcomes


# ──────────────────────────────────────────────────────────────────────────
# 감사 JSONL 재분류 (OPS-50 ①) — 라이브 호출 없이 과거 감사 파일에서 미분류를 해부한다
# ──────────────────────────────────────────────────────────────────────────
def analyze_parse_failures(
    audit_path: Path, *, side: str = "candidate", num_predict: int = 512
) -> str:
    """감사 JSONL의 미분류 문항을 정답지(클래스)·원인별로 재분류한 사람 가독 리포트.

    구 감사 파일(OPS-48)에는 `failure_kind`가 없으므로 원문·출력 토큰으로 다시 추정한다:
    출력 토큰 ≥ num_predict면 절단, 그 외 비어 있지 않으면 malformed.
    """
    rows = [
        json.loads(line)
        for line in audit_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rows = [r for r in rows if "slug" in r]
    if not rows:
        raise ValueError(f"감사 파일에 문항이 없다: {audit_path}")  # 0건 스캔은 실패다
    total: dict[str, int] = {}
    failed: dict[str, int] = {}
    kinds: dict[str, int] = {}
    prefix_verdict: dict[tuple[str, str], int] = {}  # (클래스구분, 접두 판정) → 건수
    for row in rows:
        truth = row["ground_truth"] or "clean"
        total[truth] = total.get(truth, 0) + 1
        out = row[side]
        if out["parsed"]:
            continue
        failed[truth] = failed.get(truth, 0) + 1
        kind = out.get("failure_kind") or _classify_failure(
            out.get("raw_response", ""), out.get("output_tokens"), num_predict
        )
        kinds[kind] = kinds.get(kind, 0) + 1
        m = re.search(r'"has_defect"\s*:\s*(true|false)', out.get("raw_response", ""))
        group = "clean" if truth == "clean" else "defective"
        key = (group, m.group(1) if m else "unreadable")
        prefix_verdict[key] = prefix_verdict.get(key, 0) + 1

    n_fail = sum(failed.values())
    lines = [
        f"[OPS-50 ①] 파싱 실패 재분류 — {audit_path.name} · {side} · 문항 {len(rows)}건",
        f"미분류 {n_fail}/{len(rows)} ({n_fail / len(rows):.1%})",
        "",
        "[정답지별]",
    ]
    for name in sorted(total):
        lines.append(f"  {name:26s} {failed.get(name, 0):>3d}/{total[name]:<3d}")
    lines.append("")
    lines.append("[원인별] " + (", ".join(f"{k} {v}" for k, v in sorted(kinds.items())) or "없음"))
    lines.append("")
    lines.append("[잘린 응답 앞부분에서 읽히는 판정 — 파싱 복구(접두 구제) 시 반사실]")
    for (group, verdict), n in sorted(prefix_verdict.items()):
        lines.append(f"  {group:9s} 문항 · has_defect={verdict:10s} {n}건")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    """OPS-48 QUALITY 티어 MoE 정확도 강등전 CLI."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.quality_tier_moe_accuracy_battle",
        description="QUALITY 티어 dense 27B ↔ MoE 정확도 축 강등전 — Wilson 단측 경계 판정.",
    )
    parser.add_argument("--baseline-model", default="qwen3.5:27b", help="기준 dense 모델 ID.")
    parser.add_argument("--candidate-model", default="qwen3:30b-a3b", help="후보 MoE 모델 ID.")
    parser.add_argument("--n-defective", type=int, default=70, help="결함 문항 수(기본 70).")
    parser.add_argument("--n-clean", type=int, default=70, help="무결함 문항 수(기본 70).")
    parser.add_argument("--seed", type=int, default=20260708, help="셋 생성 시드(결정론).")
    parser.add_argument("--confidence", type=float, default=0.95, help="Wilson 신뢰수준(단측).")
    parser.add_argument("--ollama-host", default=None, help="Ollama 호스트(기본 설정값 사용).")
    parser.add_argument("--timeout", type=float, default=600.0, help="모델 호출 타임아웃(초).")
    parser.add_argument("--num-ctx", type=int, default=8192, help="Ollama num_ctx.")
    parser.add_argument("--num-predict", type=int, default=512, help="최대 출력 토큰.")
    parser.add_argument("--concurrency", type=int, default=1, help="동시 호출 수(기본 1).")
    parser.add_argument(
        "--no-json-schema",
        action="store_true",
        help="JSON schema 제약을 사용하지 않고 자유 텍스트 생성 후 파싱.",
    )
    parser.add_argument(
        "--min-detection-lower",
        type=float,
        default=0.0,
        help="후보 검출률 Wilson 하한 임계 — 미만이면 exit 1(기본 0=off).",
    )
    parser.add_argument(
        "--max-false-alarm-upper",
        type=float,
        default=1.0,
        help="후보 오경보율 Wilson 상한 임계 — 초과면 exit 1(기본 1.0=off).",
    )
    parser.add_argument(
        "--require-candidate-not-worse-than-baseline",
        action="store_true",
        help="후보가 기준 모델보다 검출률/오경보에서 열등하면 exit 1.",
    )
    parser.add_argument(
        "--not-worse-margin",
        type=float,
        default=0.0,
        help="'not worse' 판정 허용 마진(기본 0.0).",
    )
    parser.add_argument(
        "--prompt-variant",
        choices=PROMPT_VARIANTS,
        default="baseline",
        help="후보에 적용할 프롬프트 변형(OPS-50 — 한 번에 하나만). 기준 모델은 항상 baseline.",
    )
    parser.add_argument(
        "--baseline-audit",
        type=Path,
        default=None,
        help="기준 모델 결과를 이 감사 JSONL에서 재사용(27B 재실행 생략). 시험지가 다르면 exit 2.",
    )
    parser.add_argument(
        "--analyze-audit",
        type=Path,
        default=None,
        help="라이브 호출 없이 감사 JSONL의 후보 미분류를 재분류해 출력하고 종료(OPS-50 ①).",
    )
    parser.add_argument(
        "--unresolved-policy",
        choices=("exclude", "worst"),
        default="exclude",
        help="게이트의 미분류 처리 — exclude=A(OPS-48 방식) · worst=검출 B/오경보 C 최악 가정.",
    )
    parser.add_argument(
        "--max-unresolved-rate",
        type=float,
        default=1.0,
        help="후보 미분류율 상한 — 초과면 exit 1(기본 1.0=off, OPS-50 ③은 0.05).",
    )
    parser.add_argument(
        "--audit-out",
        type=Path,
        default=None,
        help="감사 JSONL 저장 경로(예: data/audit/ops-48-battle.jsonl).",
    )
    args = parser.parse_args(argv)

    if args.analyze_audit is not None:
        try:
            print(analyze_parse_failures(args.analyze_audit, num_predict=args.num_predict))
        except (OSError, ValueError, KeyError) as exc:
            print(f"오류: 감사 파일 분석 실패 — {type(exc).__name__}: {exc}", file=sys.stderr)
            return _EXIT_INPUT_ERROR
        return _EXIT_OK

    if args.n_defective <= 0 or args.n_clean <= 0:
        print("오류: --n-defective와 --n-clean은 1 이상이어야 합니다.", file=sys.stderr)
        return _EXIT_INPUT_ERROR

    items = build_defect_seeded_set(
        n_defective=args.n_defective,
        n_clean=args.n_clean,
        seed=args.seed,
    )

    json_schema = None if args.no_json_schema else _JSON_SCHEMA

    print(
        f"[OPS-48] 시험지 생성 완료: "
        f"결함 {args.n_defective} · 무결함 {args.n_clean} · seed {args.seed}"
    )
    if args.baseline_audit is not None:
        try:
            baseline_outcomes = load_baseline_outcomes(args.baseline_audit, items)
        except (OSError, ValueError, KeyError) as exc:
            print(f"오류: 기준 결과 재사용 실패 — {type(exc).__name__}: {exc}", file=sys.stderr)
            return _EXIT_INPUT_ERROR
        baseline_model_id = baseline_outcomes[0].model_id
        print(
            f"[OPS-48] 기준 모델 {baseline_model_id} 결과를 {args.baseline_audit.name}에서 재사용"
        )
    else:
        baseline_model_id = args.baseline_model
        print(f"[OPS-48] 기준 모델 {args.baseline_model} 평가 시작...")
        baseline_outcomes = asyncio.run(
            evaluate_model(
                args.baseline_model,
                items,
                ollama_host=args.ollama_host,
                timeout=args.timeout,
                num_ctx=args.num_ctx,
                num_predict=args.num_predict,
                concurrency=args.concurrency,
                json_schema=json_schema,
            )
        )
    print(f"[OPS-48] 후보 모델 {args.candidate_model} 평가 시작...")
    candidate_outcomes = asyncio.run(
        evaluate_model(
            args.candidate_model,
            items,
            ollama_host=args.ollama_host,
            timeout=args.timeout,
            num_ctx=args.num_ctx,
            num_predict=args.num_predict,
            concurrency=args.concurrency,
            json_schema=json_schema,
            variant=build_variant(args.prompt_variant),
        )
    )

    report = BattleReport(
        baseline=_summarize(baseline_model_id, baseline_outcomes),
        candidate=_summarize(args.candidate_model, candidate_outcomes),
        n_defective=args.n_defective,
        n_clean=args.n_clean,
        seed=args.seed,
        confidence=args.confidence,
        baseline_model_id=baseline_model_id,
        candidate_model_id=args.candidate_model,
        prompt_variant=args.prompt_variant,
    )

    print(render_report(report))

    if args.audit_out is not None:
        _write_audit(args.audit_out, baseline_outcomes, candidate_outcomes, report)
        print(f"[OPS-48] 감사 JSONL 저장: {args.audit_out}")

    # 게이트 판정
    exit_code = _EXIT_OK
    worst = args.unresolved_policy == "worst"
    cm = report.candidate.metrics
    bm = report.baseline.metrics
    candidate_dlb = (
        cm.worst_case_detection_lower_bound(args.confidence)
        if worst
        else cm.detection_lower_bound(args.confidence)
    )
    if args.min_detection_lower > 0.0 and (
        candidate_dlb is None or candidate_dlb < args.min_detection_lower
    ):
        exit_code = _EXIT_GATE_FAIL
    candidate_fau = (
        cm.worst_case_false_alarm_upper_bound(args.confidence)
        if worst
        else cm.false_alarm_upper_bound(args.confidence)
    )
    candidate_unresolved_rate = cm.unresolved_rate
    if args.max_unresolved_rate < 1.0 and (
        candidate_unresolved_rate is None or candidate_unresolved_rate > args.max_unresolved_rate
    ):
        print(
            f"[OPS-50] 후보 미분류율 {_fmt(candidate_unresolved_rate)} > "
            f"상한 {_fmt(args.max_unresolved_rate)}",
            file=sys.stderr,
        )
        exit_code = _EXIT_GATE_FAIL
    if args.max_false_alarm_upper < 1.0 and (
        candidate_fau is None or candidate_fau > args.max_false_alarm_upper
    ):
        exit_code = _EXIT_GATE_FAIL

    if args.require_candidate_not_worse_than_baseline:
        baseline_dlb = (
            bm.worst_case_detection_lower_bound(args.confidence)
            if worst
            else bm.detection_lower_bound(args.confidence)
        )
        baseline_fau = (
            bm.worst_case_false_alarm_upper_bound(args.confidence)
            if worst
            else bm.false_alarm_upper_bound(args.confidence)
        )
        margin = args.not_worse_margin
        if candidate_dlb is None or (
            baseline_dlb is not None and candidate_dlb < baseline_dlb - margin
        ):
            d_msg = (
                f"후보 하한 {_fmt(candidate_dlb)} < "
                f"기준 하한 {_fmt(baseline_dlb)} - 마진 {_fmt(margin)}"
            )
            print(
                "[OPS-48] 후보가 기준보다 검출률이 열등합니다: " + d_msg,
                file=sys.stderr,
            )
            exit_code = _EXIT_GATE_FAIL
        if candidate_fau is None or (
            baseline_fau is not None and candidate_fau > baseline_fau + margin
        ):
            f_msg = (
                f"후보 상한 {_fmt(candidate_fau)} > "
                f"기준 상한 {_fmt(baseline_fau)} + 마진 {_fmt(margin)}"
            )
            print(
                "[OPS-48] 후보가 기준보다 오경보가 높습니다: " + f_msg,
                file=sys.stderr,
            )
            exit_code = _EXIT_GATE_FAIL

    return exit_code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
