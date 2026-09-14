"""연령별(학년 레지스터) 개념 설명 생성기 — EOS-98(C9) 생성 좌석.

`analogy_generator.py`(개념 비유 생성기)의 *설명(explanation)* 짝이다: 같은 개념을 여러 학년
레지스터(`SpeechGradeBand` — 초등/중등/고등/대학)의 언어 수준으로 **다시 쓴다**. 비유 생성기와
결정적으로 다른 지점 하나 — 비유는 "개념당 1건"(레지스터는 파라미터, 상한 불변식)이지만, 이
생성기는 **같은 개념을 4개 레지스터 각각에 대해 동시에 필요로 한다**(EOS-98 acceptance ③ "동일
개념 다수준 설명 생성"). 그래서 착지 좌석(`concept_content.explanation` 단일 컬럼)에 덮어쓰지
않는다 — 이 모듈은 **온디맨드 생성 진입점**까지만 놓는다(착지는 EOS-70이 SubjectAdapter.explain
계약을 확정한 뒤 별도 저장 축 판단 — 정직한 공백).

환각 방지 설계: 프롬프트는 개념명·과목뿐 아니라 **기존 정본 설명(`concept_content.explanation`)
을 원문으로 동봉**하고, LLM에게는 "이 원문의 의미를 바꾸지 말고 대상 레지스터의 어휘·문장으로
다시 쓰라"고만 지시한다(새 사실 창작 금지 — 재표현(rephrase)만 허용). 이는 EOS-89
`equivalent/rephrase.py`(재진술 재작성)와 같은 "사실 고정·문체만 변환" 설계다.

파이프라인(L4=결정·L3=생성 준수 — analogy_generator 동형): 원문 조회(L4가 L1 경유 주입) →
LLM 생성(라우터 경유) → DRAFT → prescreen → review + 언어 수준 결함 검출(F7,
`explanation_checker.py`) → APPROVED만 호출자에게 반환(착지는 호출자 몫).

7계층: L3 콘텐츠 생성. 검수 함수(`prescreen`/`review`)를 재사용한다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from whymath_backend.config import Settings
from whymath_backend.l3.data_grade_defaults import SELF_AUTHORED_CORPUS
from whymath_backend.l3.interfaces import LLMProvider, TraceSink
from whymath_backend.l3.models import (
    CostTier,
    LocalModelTier,
    ModelFamily,
    RoutingDecision,
    RoutingRequest,
    Usage,
)
from whymath_backend.l3.pedagogy.explanation_checker import check_explanation_language_level_defect
from whymath_backend.l3.pedagogy.prescreen import prescreen_slot
from whymath_backend.l3.pedagogy.review import ReviewVerdict, review_slot
from whymath_backend.l3.pedagogy.slot_generator import _is_tts_safe
from whymath_backend.l3.router import Router, _as_cost_tier, actual_cost_krw, langfuse_fields
from whymath_backend.schema.enums import GenerationFailureCode
from whymath_backend.schema.speech import SpeechGradeBand

_LOGGER = logging.getLogger(__name__)

# 설명 초안의 reasoning_type — 슬롯 유형이 아니라 *개념-grain 연령별 설명*임을 표기.
_EXPLANATION_REASONING_TYPE: Final[str] = "age_band_explanation"


# ──────────────────────────────────────────────────────────────────────────
# 시스템 프롬프트 — 환각 방지(재표현만 허용) + 학년 레지스터 어휘 제약
# ──────────────────────────────────────────────────────────────────────────
EXPLANATION_SYSTEM_PROMPT: Final[
    str
] = """당신은 WhyMath의 **개념 설명 재저작자**입니다. 주어진 개념의 기존 정본 설명(원문)을,
지정된 학년 레지스터의 어휘·문장 수준으로 **다시 쓴** 설명 1개를 JSON 하나로만 출력하세요.

## 절대 지켜야 할 것 (환각 방지)
- **원문의 의미를 바꾸지 마세요** — 새로운 사실·예시·정의를 창작하지 말고, 원문이 말하는 내용을
  그대로 유지한 채 **어휘와 문장 구조만** 대상 레지스터에 맞게 바꾸세요(재표현만 허용).
- 원문에 없는 내용을 추가하거나, 원문의 핵심 주장을 누락하지 마세요.

## 학년 레지스터 어휘 제약
- 지시된 레지스터에 **아직 도입되지 않은 구조**(금지 어휘 목록으로 함께 제공됩니다)는 본문에
  쓰지 마세요. 원문에 그런 어휘가 있으면 그 레지스터에서 이해 가능한 더 쉬운 표현으로 바꿔
  쓰세요(예: 초등 레지스터에서 "미분"은 "순간의 변화를 재는 방법" 같은 식으로 풀어 쓰기).
- 교과서·기출 문장을 복제하지 말고 순수 자작으로 쓰세요.

## 출력 형식 — JSON 객체 하나만 (코드펜스·설명 없이)
{"explanation": "다시 쓴 설명 본문(2~5문장·한국어)"}
"""


# ──────────────────────────────────────────────────────────────────────────
# 표적 — 개념 code + 학년 레지스터 + 원문(재표현 대상)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class ExplanationTarget:
    """설명 생성 표적 1건 — 개념 code + 학년 레지스터 + 재표현할 원문 + 금지 어휘 목록.

    `band`는 `SpeechGradeBand`(초등/중등/고등/대학 — `schema/speech.py` 재사용, 낭독 프로파일의
    닫힌 교수학 어휘와 동일 축을 공유해 `l3/pedagogy/analogy_generator.py::ANALOGY_REGISTERS`의
    "중학" 표기 불일치를 새로 만들지 않는다). `forbidden_vocabulary`는 프롬프트에 동봉할 금지
    어휘 표기(사람이 읽는 표현) — 실제 판정은 `explanation_checker`가 별도로 한다(프롬프트 동봉은
    생성측 예방, 검수측 판정은 독립된 기계 게이트 — 생성기 자기 보고에 기대지 않는다).
    """

    code: str
    name: str
    subject: str
    band: SpeechGradeBand
    source_explanation: str
    forbidden_vocabulary: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.source_explanation.strip():
            raise ValueError(
                f"ExplanationTarget({self.code!r}, {self.band!r}): source_explanation이 "
                "비어 있습니다 — 재표현할 원문 없이 생성 발주 금지(환각 방지 설계)."
            )


# ──────────────────────────────────────────────────────────────────────────
# LLM 생성기 (라우터 경유·provider 주입 seam — analogy_generator 미러)
# ──────────────────────────────────────────────────────────────────────────
class ExplanationGenerator:
    """연령별 설명 LLM 생성기 — 라우터 경유·주입 seam·실패 None 폴백(크래시 금지).

    `AnalogyGenerator`의 *설명* 짝이다 — 차이는 ①표적당 원문 재표현(환각 방지) ②온도를 낮춰
    충실도 우선(비유의 다양성 온도 0.9 대신 0.4 — 사실 보존이 관건이라 창의성보다 충실성).
    """

    def __init__(
        self,
        provider: LLMProvider | None = None,
        *,
        settings: Settings | None = None,
        trace: TraceSink | None = None,
        subscription: str = "free",
        temperature: float = 0.4,
        authoring_family: ModelFamily | None = ModelFamily.GENERAL,
    ) -> None:
        """생성기 구성 — provider/trace 미주입 시 표준 구성(지연 연결·네트워크 0)."""
        if provider is None:
            from whymath_backend.l3.providers.anthropic import AnthropicProvider
            from whymath_backend.l3.providers.composite import CompositeProvider
            from whymath_backend.l3.providers.ollama import OllamaProvider

            provider = CompositeProvider(local=OllamaProvider(), cloud=AnthropicProvider())
        if trace is None:
            from whymath_backend.l3.trace.langfuse_sink import LangfuseSink

            trace = LangfuseSink(settings=settings)
        self._provider = provider
        self._trace = trace
        self._subscription = subscription
        self._temperature = temperature
        self._authoring_family = authoring_family
        # 배치용 지속 이벤트 루프(지연 생성) — analogy_generator `_ensure_loop` 미러.
        self._loop: asyncio.AbstractEventLoop | None = None

    # ── 공개 API ───────────────────────────────────────────────────────
    def generate_draft(self, target: ExplanationTarget) -> dict[str, Any] | None:
        """표적 1건의 설명 DRAFT 행 생성(동기 배치 경계용) — 실패 시 None(안전 폴백).

        `analogy_generator` 선례와 동형으로 **지속 이벤트 루프**(`_ensure_loop`)에서
        `agenerate_draft`를 완주한다. 이미 실행 중인 이벤트 루프 안(FastAPI 요청 핸들러 등)에서
        호출하면 `RuntimeError`가 나므로, async 호출부는 이 메서드가 아니라 `agenerate_draft`를
        직접 `await`해야 한다(`l4/pedagogy/age_band_explanation.py`가 그렇게 한다).
        """
        return self._ensure_loop().run_until_complete(self.agenerate_draft(target))

    async def agenerate_draft(self, target: ExplanationTarget) -> dict[str, Any] | None:
        """표적 1건의 설명 DRAFT 행 생성(async 호출부용) — 실패 시 None(안전 폴백·크래시 금지).

        이미 실행 중인 이벤트 루프 안에서 안전하게 호출 가능하다(자체 루프를 새로 열지 않는다 —
        `generate_draft`의 "루프 안에서 또 루프" RuntimeError를 피한다). 반환 행은 상태기계 함수
        (`prescreen_slot`/`review_slot`) 호환 형태다: `{id, target_code, band, payload{body,
        reasoning_type, structure_tags}, sympy_verified=None, tts_safe, status='DRAFT'}`.
        """
        prompt = self._build_user_prompt(target)
        decision = self._decide_routing()
        try:
            generated = await self._provider.generate(
                prompt,
                EXPLANATION_SYSTEM_PROMPT,
                decision,
                temperature=self._temperature,
            )
        except Exception as exc:  # noqa: BLE001 — provider 장애 시 배치 크래시 금지·안전 폴백.
            _LOGGER.warning(
                "설명 생성 provider 호출 실패(%s) — None 폴백: %s", type(exc).__name__, exc
            )
            return None
        # LLM 호출 성공 = 비용 발생 — 파싱 성패와 무관하게 관측을 먼저 남긴다(선례 미러).
        self._record_trace(decision, generated.usage)
        data = _extract_json(generated.text)
        if data is None:
            _LOGGER.warning("설명 생성 응답 JSON 파싱 실패 — None 폴백.")
            return None
        explanation = data.get("explanation")
        if not isinstance(explanation, str) or not explanation.strip():
            _LOGGER.warning("설명 생성 응답 explanation 필드 결측/무효 — None 폴백.")
            return None
        return build_explanation_draft_row(target, explanation.strip())

    # ── 내부: 라우팅·호출·관측 (analogy_generator 미러) ─────────────────
    def _decide_routing(self) -> RoutingDecision:
        """라우터 결정 + 저작 패밀리 스왑 — 비용·크기·모드 결정은 그대로 존중."""
        decision = Router().route(
            RoutingRequest(
                task_type="generate",
                difficulty="medium",
                requires_reasoning=True,
                student_subscription=self._subscription,
                sync=True,
                # 등급: 설명 재저작 프롬프트에는 자체 코퍼스 원문만 실린다(EOS-59).
                data_licenses=SELF_AUTHORED_CORPUS,
            )
        )
        if self._authoring_family is None:
            return decision
        is_local = decision.cost_tier == CostTier.LOCAL.value
        family_applicable = is_local and decision.local_model in (
            LocalModelTier.FAST.value,
            LocalModelTier.MID.value,
        )
        if not family_applicable or decision.local_family == self._authoring_family.value:
            return decision
        return RoutingDecision(
            cost_tier=decision.cost_tier,
            local_family=self._authoring_family,
            local_model=decision.local_model,
            mode=decision.mode,
            reason=f"{decision.reason} → 저작:{self._authoring_family.value}",
            est_latency_ms=decision.est_latency_ms,
            est_cost_krw=decision.est_cost_krw,
            data_export_blocked=decision.data_export_blocked,
            data_export_reason=decision.data_export_reason,
        )

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        """인스턴스 전용 이벤트 루프 지연 생성(배치 커넥션 풀 보존 — analogy_generator 선례)."""
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
        return self._loop

    def _record_trace(self, decision: RoutingDecision, usage: Usage | None) -> None:
        """생성 1건의 라우팅·실측을 sink에 기록 — never-break(예외 타입명 로그·침묵 실패 금지)."""
        actual_krw: float | None
        is_cloud = _as_cost_tier(decision.cost_tier) is not CostTier.LOCAL
        if usage is None:
            actual_krw = None
        elif is_cloud and (usage.input_tokens is None or usage.output_tokens is None):
            actual_krw = None
        else:
            actual_krw = actual_cost_krw(decision, usage)
        try:
            self._trace.record(
                langfuse_fields(decision, cache_hit=False, usage=usage, cost_krw=actual_krw)
            )
        except Exception as exc:  # noqa: BLE001 — 관측 장애가 저작 배치를 깨면 안 됨
            _LOGGER.warning("설명 생성 관측 기록 실패(%s) — 무시하고 계속", type(exc).__name__)

    @staticmethod
    def _build_user_prompt(target: ExplanationTarget) -> str:
        """표적 1건의 사용자 프롬프트 — 원문 동봉(재표현 대상)+레지스터+금지 어휘(Minimal)."""
        forbidden = (
            ", ".join(target.forbidden_vocabulary) if target.forbidden_vocabulary else "(없음)"
        )
        return (
            f"개념: {target.name} (과목: {target.subject}, 코드: {target.code})\n"
            f"학년 레지스터: {target.band.value}\n"
            f"이 레지스터에 아직 도입되지 않은 어휘(쓰지 말 것): {forbidden}\n"
            f"기존 정본 설명(원문 — 의미를 바꾸지 말고 다시 쓸 것):\n{target.source_explanation}\n"
            "위 원문을 지정된 학년 레지스터의 어휘·문장 수준으로 다시 써서 JSON 하나로만 "
            "출력하세요."
        )


# ──────────────────────────────────────────────────────────────────────────
# JSON 관대 추출 — analogy_generator `_extract_json`의 동형 미러
# ──────────────────────────────────────────────────────────────────────────
def _extract_json(raw: str) -> dict[str, object] | None:
    """원시 텍스트에서 JSON 객체를 관대하게 추출 — 실패 시 None."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    candidates = [text]
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


# ──────────────────────────────────────────────────────────────────────────
# DRAFT 행 조립·상태기계(prescreen→review) 재사용 — 순수 함수
# ──────────────────────────────────────────────────────────────────────────
def build_explanation_draft_row(target: ExplanationTarget, explanation: str) -> dict[str, Any]:
    """설명 초안 → 상태기계 호환 DRAFT 행(순수·결정론).

    행 형태는 `pedagogy_content_slot`/`analogy_generator.build_analogy_draft_row`와 동형 키를
    가져 `prescreen_slot`/`review_slot`이 무수정으로 적용된다. 개념-grain 키(`target_code`·
    `band`)를 별도로 담아 호출자(착지 좌석)가 쓴다. 수치 검증 재료가 없는 설명이라
    `sympy_verified=None`(정직 표기·개념형 슬롯 동형).
    """
    payload: dict[str, Any] = {
        "body": explanation,
        "reasoning_type": _EXPLANATION_REASONING_TYPE,
        "structure_tags": ["explanation", target.band.value],
    }
    return {
        "id": f"explanation:{target.code}:{target.band.value}",
        "target_code": target.code,
        "band": target.band,
        "payload": payload,
        "sympy_verified": None,
        "tts_safe": _is_tts_safe(payload),
        "status": "DRAFT",
    }


@dataclass(frozen=True, slots=True)
class ExplanationOutcome:
    """설명 초안 1건의 상태기계 통과 결과 — 최종 상태 + 예심 점수 + 반려 사유(승인 시 None).

    `reject_reason`은 구조 결함(`empty_body` 등 `review_slot` 어휘) 또는 폐쇄 8코드 중 하나
    (`GenerationFailureCode.F7.value` — 언어 수준 부적합)다. F7은 `explanation_checker`가 판정한
    유일한 콘텐츠-품질 축이라 다른 판단형 코드(F3·F4·F5·F6)는 이 게이트가 낼 수 없다(정직한
    커버리지 — 이 생성기가 측정하는 범위는 언어 수준 축뿐).
    """

    row: dict[str, Any]
    status: str  # "APPROVED" | "REJECTED"
    prescreen_score: int
    reject_reason: str | None


def run_explanation_review(
    rows: Sequence[dict[str, Any]],
    *,
    introduced_constructs_by_band: Mapping[SpeechGradeBand, frozenset[str]],
) -> list[ExplanationOutcome]:
    """DRAFT 행들을 상태기계(DRAFT→PRESCREENED→APPROVED|REJECTED)에 태운다 — 순수·결정론.

    전이 재사용: ①`prescreen_slot`(0..3 루브릭 — 슬롯 파이프라인 동형) ②`review_slot`(구조 기계
    게이트) ③`check_explanation_language_level_defect`(F7 언어 수준 결함 — EOS-98 신설 게이트).
    ②③ 모두 통과해야 APPROVED, 하나라도 걸리면 REJECTED(사유=첫 결함 코드·fail-closed).

    `introduced_constructs_by_band`는 호출자가 `l4/speech/profiles.py::PROFILES`에서 조립해
    주입한다(L3가 L4를 직접 import하지 않는다 — DI 규약).
    """
    outcomes: list[ExplanationOutcome] = []
    for row in rows:
        payload = row["payload"]
        score = prescreen_slot(
            payload,
            sympy_verified=row.get("sympy_verified"),
            tts_safe=row.get("tts_safe"),
        )
        verdict: ReviewVerdict = review_slot(payload)
        if verdict.approved:
            band: SpeechGradeBand = row["band"]
            constructs = introduced_constructs_by_band.get(band, frozenset())
            defect: GenerationFailureCode | None = check_explanation_language_level_defect(
                band, payload["body"], introduced_constructs=constructs
            )
            if defect is not None:
                verdict = ReviewVerdict(False, defect.value)
        approved = verdict.approved
        outcomes.append(
            ExplanationOutcome(
                row=row,
                status="APPROVED" if approved else "REJECTED",
                prescreen_score=score,
                reject_reason=verdict.reason,
            )
        )
    return outcomes


__all__ = [
    "EXPLANATION_SYSTEM_PROMPT",
    "ExplanationTarget",
    "ExplanationGenerator",
    "build_explanation_draft_row",
    "ExplanationOutcome",
    "run_explanation_review",
]
