"""클라우드 프로바이더 정확도·지연·비용 3축 강등전 (ARCH-55 ①②③).

무엇을 재는가
------------
현행 클라우드 핀(Anthropic `claude-sonnet-4-6`)과 DeepSeek 경로 2종(공식 API·OpenRouter
경유)을 **같은 결함 주입 시험지**로 대조한다. 시험지는 `l3/equivalent/defect_seeder`가
결정론으로 만들고 정답지(`defect_class`)를 우리가 100% 안다. 세 축을 함께 수집한다:

  정확도 — 검출률·오경보율을 **Wilson 단측 경계**로. 점추정 금지.
  지연   — 호출마다 provider가 monotonic으로 잰 실측(`Usage.latency_ms`).
  비용   — **토큰만 측정값으로 보고**한다(아래 "비용을 계산하지 않는 이유").

`quality_tier_moe_accuracy_battle`(OPS-48)과 **시험지·시스템 프롬프트·파서를 공유**한다.
그 셋이 갈라지면 두 강등전의 수치를 나란히 놓을 수 없기 때문이다 — 그래서 복사하지 않고
import한다(`test_provider_accuracy_battle.py`가 그 공유를 계약으로 동결한다).

라우터를 경유한다 (프로바이더만 바꾼다)
--------------------------------------
OPS-48은 `FixedModelOllamaProvider`로 모델을 손으로 박고 좌석 계약 유예를 받았다. 여기서는
그럴 필요가 없다 — **바꾸는 것이 모델이 아니라 프로바이더**이기 때문이다. 입력 신호를 골라
`Router()`가 스스로 `CLOUD_MID`를 내게 하고, `CompositeProvider`의 `cloud=` 슬롯만 arm마다
갈아 끼운다. 그래서 각 회차는 라우팅·법적 게이트·관할 게이트를 **모두 통과한 호출**이며,
이 파일은 좌석 계약 스캐너에 CONSUMER로 잡힌다(유예 불요).

공급사 고정 확인 (acceptance ③)
------------------------------
OpenRouter는 응답 본문에 **실제로 서빙한 공급사**를 담는다. 이 하네스는 자기 전송 시임을
주입해 그 값을 회차마다 기록하고, 허용목록 1곳과 다르면 그 회차를 `provider_mismatch`로
표시한다. 양자화가 공급사마다 다르므로(`deepinfra`=FP8·다수 미표기) 섞인 회차를 집계에
넣으면 **모델이 아니라 잡음을 재게 된다** — 그래서 판정에서 제외하고 그 사실을 보고한다.

요금 구간 분리 (acceptance ②)
----------------------------
DeepSeek 공식 API는 피크/오프피크 단가가 정확히 2배 차이다. 회차마다
`l3.providers.deepseek.pricing_window`로 라벨링하고 **분리 집계**한다 — 한 통에 넣으면 그
2배가 평균에 녹아 비교가 무의미해진다.

비용을 계산하지 않는 이유 (정직 고지)
-----------------------------------
이 하네스는 **토큰 수만 측정값으로 보고**하고 원화·달러 환산을 하지 않는다. ARCH-49에서
"실측"이라 기록된 단가 4건이 나중에 전부 틀린 것으로 드러났고(모델 slug·엔드포인트 수·
최저가 공급사·단가), 그 숫자가 코드에 핀돼 있었다. 단가는 공급사·시점·할인에 따라 바뀌는
**외부 사실**이므로 측정 도구가 품고 있으면 안 된다. 환산이 필요하면
`--price ARM[:WINDOW]=입력/출력`(1M 토큰당 USD)으로 그 회차에 쓴 단가를
**명시적으로 주입**하고, `--price-source`로 출처를 함께 남긴다 — 출처 없이는
거부한다(출처 없는 숫자가 나중에 '실측'으로 오인된다).
주지 않으면 비용 절은 "단가 미지정"이라고 말한다.

실패해도 증거가 남는다
--------------------
회차마다 결과를 `--audit-out`에 **즉시 append**한다(마지막에 한 번 저장하면 중간에 멈출 때
전부 잃는다). 호출 실패는 예외 타입명과 메시지를 함께 남기고 `unresolved`로 계상한다 —
검출 실패와 구분되지 않으면 "정확도가 낮다"와 "도구가 고장났다"가 같은 숫자가 된다.

사용(Phaiakes9 — 키 필요):
    python -m whymath_backend.harness.provider_accuracy_battle \
        --arm anthropic --arm deepseek --n-defective 40 --n-clean 40 \
        --audit-out data/audit/arch-55
먼저 호출 없이 준비 상태만 볼 수 있다(키가 없으면 회차를 태우지 않고 멈춘다):
    python -m whymath_backend.harness.provider_accuracy_battle \
        --arm anthropic --arm deepseek --check-only
단가를 나중에 알았으면 **호출 없이** 그 회차를 다시 환산한다:
    python -m whymath_backend.harness.provider_accuracy_battle \\
        --replay data/audit/arch-55 --arm anthropic --arm deepseek \\
        --price anthropic=3/15 --price deepseek=0.15/0.60 --price-source "<출처>"
종료: 0 통과 / 1 게이트 미달·측정 실패 / 2 인자 오류·arm 준비 미비
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from whymath_backend.config import get_settings

# OPS-48과 **같은** 시험지·프롬프트·파서를 쓴다 — 갈라지면 두 강등전을 나란히 놓을 수 없다.
# 사적 이름을 import하는 것은 그 공유를 의도적으로 못박기 위함이며, 계약은
# `tests/backend/harness/test_provider_accuracy_battle.py`가 동결한다.
from whymath_backend.harness.quality_tier_moe_accuracy_battle import (
    _SYSTEM_PROMPT,
    _format_item,
    _parse_response,
)
from whymath_backend.harness.wilson import wilson_lower_bound, wilson_upper_bound
from whymath_backend.l3.equivalent.defect_seeder import DefectClass, build_defect_seeded_set
from whymath_backend.l3.interfaces import LLMProvider
from whymath_backend.l3.models import CostTier, GenerationResult, RoutingDecision, RoutingRequest
from whymath_backend.l3.providers.anthropic import AnthropicProvider
from whymath_backend.l3.providers.composite import CompositeProvider
from whymath_backend.l3.providers.deepseek import DeepSeekProvider, pricing_window
from whymath_backend.l3.providers.ollama import OllamaProvider
from whymath_backend.l3.providers.openrouter import OpenRouterProvider, provider_slug_from_tag
from whymath_backend.l3.router import Router
from whymath_backend.schema.enums import LicenseType

_EXIT_OK = 0
_EXIT_GATE_FAIL = 1
_EXIT_INPUT_ERROR = 2

ARMS = ("anthropic", "deepseek", "openrouter")
"""대조군 이름 — `anthropic`이 baseline(현행 핀)이고 나머지가 후보다."""


_ARM_KEY_ENV = {
    "anthropic": "WHYMATH_ANTHROPIC_API_KEY",
    "deepseek": "WHYMATH_DEEPSEEK_API_KEY 또는 DEEPSEEK_API_KEY",
    "openrouter": "WHYMATH_OPENROUTER_API_KEY 또는 OPENROUTER_API_KEY",
}
"""arm별로 이 머신에 있어야 하는 환경변수 이름(값이 아니라 *이름*만 출력한다)."""


def arm_readiness(arm: str) -> tuple[bool, str]:
    """arm을 지금 이 머신에서 호출할 수 있는가 — **부르기 전에** 판정한다.

    키가 없으면 회차가 전부 `unresolved`로 쌓이는데, 그것은 "정확도가 낮다"와 같은 자리에
    앉는 숫자가 아니라 **측정이 성립하지 않았다**는 뜻이다. 그런데도 실행은 끝까지 돌아
    회차(와 다른 arm의 과금)를 태운다. 그래서 측정 전에 멈춘다(CLAUDE.md "측정·수집 도구를
    성공 경로만 보고 설계 금지").

    OpenRouter는 키만으로 부족하다 — 허용목록이 비면 `build_provider_block`이 거부하므로
    그 비어 있음도 미비로 본다(빈 허용목록은 '아무나 허용'이 아니라 '차단'이다).
    키 값 자체는 어떤 경로로도 출력하지 않는다.
    """
    settings = get_settings()
    if arm == "anthropic":
        ready = settings.anthropic_configured
        detail = "" if ready else f"키 미설정({_ARM_KEY_ENV[arm]})"
    elif arm == "deepseek":
        ready = settings.deepseek_configured
        detail = "" if ready else f"키 미설정({_ARM_KEY_ENV[arm]})"
    elif arm == "openrouter":
        if not settings.openrouter_configured:
            return False, f"키 미설정({_ARM_KEY_ENV[arm]})"
        allowed = tuple(settings.openrouter_allowed_providers)
        if not allowed:
            return False, "허용 공급사 목록이 비어 있음(WHYMATH_OPENROUTER_ALLOWED_PROVIDERS)"
        return True, f"허용 공급사 {', '.join(allowed)}"
    else:
        raise ValueError(f"알 수 없는 arm: {arm!r} (가능: {', '.join(ARMS)})")
    return ready, detail


class _ProviderTap:
    """OpenRouter 전송 시임 — **어느 공급사가 응답했는지**를 회차마다 붙잡는다.

    `GenerationResult`에는 그 정보가 없고(텍스트+usage뿐), 넣으려면 L3 계약을 넓혀야 한다.
    하네스가 자기 전송을 주입하면 원시 응답을 그대로 볼 수 있어 계약을 건드리지 않는다.
    """

    def __init__(self) -> None:
        self.last_provider: str | None = None
        self._inner: Any = None

    async def post_chat(self, url: str, *, headers: Any, payload: Any, timeout_s: float) -> Any:
        from whymath_backend.l3.providers._openai_compat import HttpxChatTransport

        if self._inner is None:
            self._inner = HttpxChatTransport()
        response = await self._inner.post_chat(
            url, headers=headers, payload=payload, timeout_s=timeout_s
        )
        served: Any = None
        if isinstance(response, dict):
            served = response.get("provider")
        self.last_provider = served if isinstance(served, str) else None
        return response


class RoundOutcome(BaseModel):
    """한 arm이 한 문항에 대해 낸 판정 + 정답지 + 3축 측정값."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    arm: str
    slug: str
    ground_truth: DefectClass | None = Field(description="정답지(None=무결함).")
    detected: bool
    parsed: bool
    parse_error: str | None = None
    call_error: str | None = Field(
        default=None, description="호출 실패 시 예외 타입명+메시지(검출 실패와 구분)."
    )
    latency_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    pricing_window: str = Field(description="peak / off_peak — 회차 시각 기준.")
    served_provider: str | None = Field(
        default=None, description="OpenRouter가 실제로 쓴 공급사(다른 arm은 None)."
    )
    provider_mismatch: bool = Field(
        default=False, description="허용목록 1곳과 다른 공급사가 응답했는가(집계 제외 사유)."
    )

    @property
    def usable(self) -> bool:
        """정확도 집계에 넣어도 되는 회차인가 — 호출 성공 + 공급사 고정."""
        return self.call_error is None and not self.provider_mismatch


@dataclass(slots=True, frozen=True)
class DetectionMetrics:
    """이진 검출 메트릭 — Wilson 경계 포함(OPS-48과 동형)."""

    true_positives: int
    false_negatives: int
    false_positives: int
    true_negatives: int
    unresolved: int

    @property
    def defective_total(self) -> int:
        return self.true_positives + self.false_negatives

    @property
    def clean_total(self) -> int:
        return self.false_positives + self.true_negatives

    def detection_lower_bound(self, confidence: float = 0.95) -> float | None:
        if self.defective_total == 0:
            return None
        return wilson_lower_bound(self.true_positives, self.defective_total, confidence)

    def false_alarm_upper_bound(self, confidence: float = 0.95) -> float | None:
        if self.clean_total == 0:
            return None
        return wilson_upper_bound(self.false_positives, self.clean_total, confidence)


def summarize(outcomes: list[RoundOutcome]) -> DetectionMetrics:
    """회차 목록 → 검출 메트릭. **쓸 수 없는 회차는 unresolved로 센다**(0으로 접지 않는다)."""
    tp = fn = fp = tn = unresolved = 0
    for outcome in outcomes:
        if not outcome.usable:
            unresolved += 1
            continue
        if outcome.ground_truth is not None:
            if outcome.detected:
                tp += 1
            else:
                fn += 1
        elif outcome.detected:
            fp += 1
        else:
            tn += 1
    return DetectionMetrics(tp, fn, fp, tn, unresolved)


def latency_summary(outcomes: list[RoundOutcome]) -> dict[str, float | None]:
    """지연 요약 — 측정값이 없으면 지어내지 않고 None."""
    values = sorted(o.latency_ms for o in outcomes if o.usable and o.latency_ms is not None)
    if not values:
        return {"n": 0, "p50_ms": None, "p95_ms": None, "mean_ms": None}
    return {
        "n": len(values),
        "p50_ms": values[len(values) // 2],
        "p95_ms": values[min(int(len(values) * 0.95), len(values) - 1)],
        "mean_ms": sum(values) / len(values),
    }


def token_summary(outcomes: list[RoundOutcome]) -> dict[str, int | None]:
    """토큰 합계 — **이것이 비용 축의 측정값**이다(단가 환산은 하지 않는다)."""
    usable = [o for o in outcomes if o.usable]
    ins = [o.input_tokens for o in usable if o.input_tokens is not None]
    outs = [o.output_tokens for o in usable if o.output_tokens is not None]
    return {
        "n_measured": len(ins),
        "input_total": sum(ins) if ins else None,
        "output_total": sum(outs) if outs else None,
    }


def _battle_request(grade: LicenseType) -> RoutingRequest:
    """라우터가 스스로 `CLOUD_MID`를 내게 하는 입력(03a §C.1 규칙 4).

    티어를 손으로 박지 않는다 — 박으면 결정 우회 스캐너가 막는 형태가 되고, 라우팅 규칙이
    바뀌어도 이 하네스가 그것을 모른다.
    """
    return RoutingRequest(
        task_type="explain",
        difficulty="medium",
        requires_reasoning=True,
        student_subscription="premium",
        budget_krw=1000.0,
        data_licenses=(grade,),
    )


def build_arm(arm: str, tap: _ProviderTap | None) -> tuple[LLMProvider, str]:
    """arm 이름 → (CompositeProvider, 사람이 읽는 라벨).

    로컬 슬롯은 항상 `OllamaProvider`다 — 이 강등전은 `CLOUD_MID`만 태우므로 쓰이지 않지만,
    디스패처가 로컬 없이 구성되지 않기 때문이다.
    """
    if arm == "anthropic":
        cloud: LLMProvider = AnthropicProvider()
        label = "anthropic (baseline · 현행 CLOUD_MID 핀)"
    elif arm == "deepseek":
        cloud = DeepSeekProvider()
        label = "deepseek 공식 API (CN 관할)"
    elif arm == "openrouter":
        cloud = OpenRouterProvider(transport=tap)
        label = "openrouter 경유 (서방 공급사)"
    else:
        raise ValueError(f"알 수 없는 arm: {arm!r} (가능: {', '.join(ARMS)})")
    return CompositeProvider(local=OllamaProvider(), cloud=cloud), label


async def evaluate_arm(
    arm: str,
    items: list[Any],
    *,
    grade: LicenseType,
    concurrency: int,
    audit_path: Path | None,
    expected_provider: str | None,
) -> list[RoundOutcome]:
    """한 arm으로 전 문항을 평가한다 — 회차마다 즉시 flush."""
    tap = _ProviderTap() if arm == "openrouter" else None
    provider, _label = build_arm(arm, tap)
    decision: RoutingDecision = Router().route(_battle_request(grade))
    if decision.cost_tier == CostTier.LOCAL:
        raise RuntimeError(
            f"라우터가 LOCAL을 냈다(cost_tier={decision.cost_tier}) — 클라우드 강등전이 "
            "성립하지 않는다. 등급·구독·예산 입력을 확인하라."
        )
    semaphore = asyncio.Semaphore(concurrency)
    outcomes: list[RoundOutcome] = []

    async def _one(item: Any) -> RoundOutcome:
        prompt = "다음 문항을 검수하세요.\n\n" + _format_item(item)
        window = pricing_window(datetime.now(UTC))
        async with semaphore:
            try:
                result: GenerationResult = await provider.generate(
                    prompt, _SYSTEM_PROMPT, decision, temperature=0.0
                )
            except Exception as exc:  # noqa: BLE001 — 실패 *원인*을 남기는 것이 이 도구의 일
                return RoundOutcome(
                    arm=arm,
                    slug=item.candidate.problem.slug,
                    ground_truth=item.defect_class,
                    detected=False,
                    parsed=False,
                    call_error=f"{type(exc).__name__}: {exc}",
                    pricing_window=window,
                )
        verdict, parsed, parse_error = _parse_response(result.text)
        served = tap.last_provider if tap is not None else None
        mismatch = False
        if expected_provider is not None and served is not None:
            mismatch = provider_slug_from_tag(served).lower() != expected_provider.lower()
        usage = result.usage
        return RoundOutcome(
            arm=arm,
            slug=item.candidate.problem.slug,
            ground_truth=item.defect_class,
            detected=verdict.has_defect,
            parsed=parsed,
            parse_error=parse_error or None,
            latency_ms=usage.latency_ms if usage else None,
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            pricing_window=window,
            served_provider=served,
            provider_mismatch=mismatch,
        )

    for item in items:
        outcome = await _one(item)
        outcomes.append(outcome)
        if audit_path is not None:
            # 회차마다 즉시 append — 중간에 멈춰도 여기까지의 증거는 남는다.
            with audit_path.open("a", encoding="utf-8") as handle:
                handle.write(outcome.model_dump_json() + "\n")
    return outcomes


class PriceRate(BaseModel):
    """1M 토큰당 USD 단가 — **주입받은 값**이지 이 도구가 아는 값이 아니다."""

    model_config = ConfigDict(frozen=True)

    input_per_mtok: float = Field(ge=0.0)
    output_per_mtok: float = Field(ge=0.0)

    def usd_for(self, *, input_tokens: int, output_tokens: int) -> float:
        """이 단가로 환산한 USD. 반올림은 표시 단계에서 한다(중간 반올림 금지)."""
        return (
            input_tokens * self.input_per_mtok + output_tokens * self.output_per_mtok
        ) / 1_000_000


def parse_price_arg(raw: str) -> tuple[str, PriceRate]:
    """`arm[:window]=IN/OUT` → (키, 단가). IN·OUT은 **1M 토큰당 USD**.

    구간별 단가를 따로 줄 수 있다(`deepseek:peak=...`) — DeepSeek 공식 API는 피크/오프피크가
    정확히 2배 차이라 한 값으로 뭉뚱그리면 그 2배가 평균에 녹는다. 구간 없이 주면 그 arm의
    모든 구간에 적용된다.

    형식이 틀리면 **조용히 무시하지 않고 거부한다** — 잘못 읽힌 단가는 없는 단가보다 나쁘다.
    """
    if "=" not in raw:
        raise ValueError(f"단가 형식 오류: {raw!r} — `arm[:window]=입력/출력` 형태여야 한다")
    key, _, value = raw.partition("=")
    if "/" not in value:
        raise ValueError(f"단가 형식 오류: {raw!r} — 값은 `입력/출력`(1M 토큰당 USD)이다")
    in_raw, _, out_raw = value.partition("/")
    try:
        rate = PriceRate(input_per_mtok=float(in_raw), output_per_mtok=float(out_raw))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"단가 값 오류: {raw!r} — {type(exc).__name__}: {exc}") from exc
    key = key.strip()
    if not key:
        raise ValueError(f"단가 형식 오류: {raw!r} — arm 이름이 비었다")
    return key, rate


def rate_for(prices: dict[str, PriceRate], arm: str, window: str | None) -> PriceRate | None:
    """구간 단가가 있으면 그것을, 없으면 arm 단가를, 그것도 없으면 None.

    None은 0이 아니라 **모른다**는 뜻이고, 리포트는 그 차이를 글자로 구분해 적는다.
    """
    if window is not None:
        scoped = prices.get(f"{arm}:{window}")
        if scoped is not None:
            return scoped
    return prices.get(arm)


def cost_line(
    outcomes: list[RoundOutcome],
    *,
    arm: str,
    window: str | None,
    prices: dict[str, PriceRate],
) -> str:
    """토큰 합계 → USD 한 줄. 단가가 없으면 그렇게 말한다(0으로 위장하지 않는다)."""
    tok = token_summary(outcomes)
    rate = rate_for(prices, arm, window)
    if rate is None:
        return "단가 미지정(토큰만 측정)"
    if tok["input_total"] is None or tok["output_total"] is None:
        return "토큰 미측정 — 환산 불가"
    total = rate.usd_for(input_tokens=tok["input_total"], output_tokens=tok["output_total"])
    n = tok["n_measured"] or 0
    per_call = total / n if n else None
    per_call_text = "회당 미산출" if per_call is None else f"회당 ${per_call:.6f}"
    return (
        f"${total:.6f} ({per_call_text} · 단가 "
        f"in ${rate.input_per_mtok}/M · out ${rate.output_per_mtok}/M)"
    )


def render_arm(
    arm: str,
    outcomes: list[RoundOutcome],
    *,
    confidence: float,
    prices: dict[str, PriceRate] | None = None,
) -> list[str]:
    """한 arm의 리포트 — 요금 구간을 **분리 집계**한다.

    `prices`는 호출자가 주입한 단가표다. 비면 비용 절이 "단가 미지정"이라고 말한다 —
    이 도구는 단가를 알지 못하고, 모르는 것을 0으로 적지 않는다.
    """
    prices = prices or {}
    lines: list[str] = [f"── {arm} ──"]
    overall = summarize(outcomes)
    lower = overall.detection_lower_bound(confidence)
    upper = overall.false_alarm_upper_bound(confidence)
    lines.append(
        f"  검출 {overall.true_positives}/{overall.defective_total} "
        f"(Wilson 하한 {lower if lower is None else round(lower, 4)}) · "
        f"오경보 {overall.false_positives}/{overall.clean_total} "
        f"(Wilson 상한 {upper if upper is None else round(upper, 4)}) · "
        f"집계 제외 {overall.unresolved}건"
    )
    lat = latency_summary(outcomes)
    p50 = lat["p50_ms"]
    p95 = lat["p95_ms"]
    lines.append(
        f"  지연 n={lat['n']} p50={p50 if p50 is None else round(p50, 1)}ms "
        f"p95={p95 if p95 is None else round(p95, 1)}ms"
    )
    tok = token_summary(outcomes)
    lines.append(
        f"  토큰 측정 {tok['n_measured']}회 · 입력 {tok['input_total']} · "
        f"출력 {tok['output_total']}"
    )
    lines.append(f"  비용 {cost_line(outcomes, arm=arm, window=None, prices=prices)}")
    for window in ("peak", "off_peak"):
        subset = [o for o in outcomes if o.pricing_window == window]
        if not subset:
            continue
        sub = summarize(subset)
        sub_lat = latency_summary(subset)
        sub_p50 = sub_lat["p50_ms"]
        lines.append(
            f"  [{window}] 회차 {len(subset)} · 검출 {sub.true_positives}/{sub.defective_total} "
            f"· 오경보 {sub.false_positives}/{sub.clean_total} · "
            f"p50={sub_p50 if sub_p50 is None else round(sub_p50, 1)}ms · "
            f"비용 {cost_line(subset, arm=arm, window=window, prices=prices)}"
        )
    errors = [o for o in outcomes if o.call_error]
    if errors:
        lines.append(f"  ⚠ 호출 실패 {len(errors)}건 — 첫 사유: {errors[0].call_error}")
    mismatches = [o for o in outcomes if o.provider_mismatch]
    if mismatches:
        lines.append(
            f"  ⚠ 공급사 불일치 {len(mismatches)}건(집계 제외) — "
            f"예: {mismatches[0].served_provider}"
        )
    return lines


def load_audit(audit_dir: Path, arm: str) -> list[RoundOutcome]:
    """`--audit-out`이 남긴 회차 증거를 되읽는다 — **호출 없이** 다시 집계하기 위해.

    증거를 남긴 이유가 이것이다. 단가는 나중에 바뀌고 나중에 알려지는데, 그때마다 라이브를
    다시 돌리면 그 자체가 새 측정이라 앞 회차와 비교할 수 없다(시험지·시각·모델이 다르다).
    같은 회차를 다른 단가로 다시 읽는 것만이 "그 측정의 비용"을 말한다.

    깨진 줄은 **건너뛰지 않고 세어서 보고한다** — 조용히 버리면 분모가 줄어든 표가 정상으로
    보인다.
    """
    path = audit_dir / f"{arm}.ndjson"
    if not path.exists():
        raise FileNotFoundError(f"{path} — 그 arm의 회차 증거가 없다")
    outcomes: list[RoundOutcome] = []
    broken = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            outcomes.append(RoundOutcome.model_validate_json(line))
        except ValueError:
            broken += 1
    if broken:
        print(f"[{arm}] ⚠ 해석 불가 {broken}줄 — 집계에서 빠졌다(분모 {len(outcomes)})")
    return outcomes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="provider_accuracy_battle",
        description="클라우드 프로바이더 3축 강등전 (ARCH-55) — 정확도·지연·토큰.",
    )
    parser.add_argument("--arm", action="append", choices=ARMS, default=None)
    parser.add_argument("--n-defective", type=int, default=40)
    parser.add_argument("--n-clean", type=int, default=40)
    parser.add_argument("--seed", type=int, default=20260708)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--confidence", type=float, default=0.95)
    parser.add_argument("--audit-out", default=None, help="회차별 증거 append 디렉터리")
    parser.add_argument(
        "--expected-provider",
        default="deepinfra",
        help="OpenRouter arm에서 응답해야 하는 공급사 slug(불일치 회차는 집계 제외)",
    )
    parser.add_argument(
        "--replay",
        default=None,
        metavar="AUDIT_DIR",
        help="호출 없이 기존 --audit-out 증거를 되읽어 다시 집계(단가 재환산용)",
    )
    parser.add_argument(
        "--price",
        action="append",
        default=None,
        metavar="ARM[:WINDOW]=IN/OUT",
        help="1M 토큰당 USD 단가 주입 (예: anthropic=3/15 · deepseek:off_peak=0.14/0.28)",
    )
    parser.add_argument(
        "--price-source",
        default=None,
        help="그 단가를 어디서 봤는지 — 리포트에 그대로 되받아 적는다(출처 없는 숫자 금지)",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="호출 없이 arm별 준비 상태(키·허용목록)만 판정하고 종료",
    )
    parser.add_argument("--min-detection-lower", type=float, default=None)
    parser.add_argument("--max-false-alarm-upper", type=float, default=None)
    args = parser.parse_args(argv)

    arms = args.arm or ["anthropic"]
    if args.n_defective < 1 or args.n_clean < 1:
        print("[인자 오류] --n-defective·--n-clean은 1 이상이어야 한다", file=sys.stderr)
        return _EXIT_INPUT_ERROR

    prices: dict[str, PriceRate] = {}
    for raw in args.price or []:
        try:
            key, rate = parse_price_arg(raw)
        except ValueError as exc:
            print(f"[인자 오류] {exc}", file=sys.stderr)
            return _EXIT_INPUT_ERROR
        prices[key] = rate
    if prices and not args.price_source:
        print(
            "[인자 오류] --price를 줬으면 --price-source도 준다 — 출처 없는 단가는 "
            "나중에 '실측'으로 오인된다(ARCH-49 선례).",
            file=sys.stderr,
        )
        return _EXIT_INPUT_ERROR

    if args.replay:
        replay_dir = Path(args.replay)
        if not replay_dir.is_dir():
            print(f"[인자 오류] --replay 경로가 디렉터리가 아니다: {replay_dir}", file=sys.stderr)
            return _EXIT_INPUT_ERROR
        replayed: dict[str, list[RoundOutcome]] = {}
        for arm in arms:
            try:
                replayed[arm] = load_audit(replay_dir, arm)
            except FileNotFoundError as exc:
                print(f"[{arm}] 재생 불가 — {exc}", file=sys.stderr)
        if not replayed:
            print("재생할 증거가 없다 — 0건 통과로 읽지 않는다.", file=sys.stderr)
            return _EXIT_GATE_FAIL
        print(f"재생 — {replay_dir} (호출 0건)")
        print()
        for arm, outcomes in replayed.items():
            for line in render_arm(arm, outcomes, confidence=args.confidence, prices=prices):
                print(line)
        if prices:
            print(f"\n※ 단가 출처(주입값): {args.price_source}")
            print(
                "   이 도구는 단가를 알지 못한다 — 위 USD는 주입된 값으로 곱한 것이며,\n"
                "   청구서로 검증한 값이 아니다."
            )
        return _EXIT_OK

    # 사전점검 — 못 부를 arm이 하나라도 있으면 **아무것도 부르지 않고** 멈춘다.
    # 여기서 멈추지 않으면 그 arm은 unresolved만 쌓고, 나머지 arm은 과금된 뒤
    # 비교 불가능한 표가 남는다.
    not_ready: list[str] = []
    for arm in arms:
        ready, detail = arm_readiness(arm)
        mark = "OK  " if ready else "미비"
        print(f"[준비] {mark} {arm}{(' — ' + detail) if detail else ''}")
        if not ready:
            not_ready.append(arm)
    if not_ready:
        print(
            f"[중단] 준비되지 않은 arm: {', '.join(not_ready)} — 호출을 하나도 하지 않았다.",
            file=sys.stderr,
        )
        return _EXIT_INPUT_ERROR
    if args.check_only:
        print("[준비] 요청한 arm 전부 호출 가능 — --check-only이므로 여기서 끝낸다.")
        return _EXIT_OK

    try:
        items = build_defect_seeded_set(
            n_defective=args.n_defective, n_clean=args.n_clean, seed=args.seed
        )
    except ValueError as exc:
        print(f"[시험지 생성 실패] {type(exc).__name__}: {exc}", file=sys.stderr)
        return _EXIT_INPUT_ERROR

    audit_dir: Path | None = None
    if args.audit_out:
        audit_dir = Path(args.audit_out)
        audit_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"시험지 {len(items)}문항 (결함 {args.n_defective} · 무결함 {args.n_clean} · "
        f"seed {args.seed})"
    )
    reports: dict[str, list[RoundOutcome]] = {}
    for arm in arms:
        path = audit_dir / f"{arm}.ndjson" if audit_dir else None
        try:
            outcomes = asyncio.run(
                evaluate_arm(
                    arm,
                    items,
                    grade=LicenseType.WHYMATH_GENERATED,
                    concurrency=args.concurrency,
                    audit_path=path,
                    expected_provider=args.expected_provider if arm == "openrouter" else None,
                )
            )
        except Exception as exc:  # noqa: BLE001 — arm 하나가 죽어도 나머지 증거는 남긴다
            print(f"[{arm}] 평가 중단 — {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        reports[arm] = outcomes

    if not reports:
        print("측정 실패 — 어느 arm도 회차를 남기지 못했다(0건 통과로 읽지 않는다).")
        return _EXIT_GATE_FAIL

    print()
    for arm, outcomes in reports.items():
        for line in render_arm(arm, outcomes, confidence=args.confidence, prices=prices):
            print(line)
    if prices:
        print(f"\n※ 단가 출처(주입값): {args.price_source}")
        print(
            "   이 도구는 단가를 알지 못한다 — 위 USD는 주입된 값으로 곱한 것이며,\n"
            "   청구서로 검증한 값이 아니다."
        )
    else:
        print(
            "\n※ 비용은 토큰만 보고한다 — 단가는 공급사·시점·할인에 따라 바뀌는 외부 사실이라\n"
            "   측정 도구가 품지 않는다(ARCH-49에서 코드에 핀된 '실측' 단가 4건이 틀렸다).\n"
            "   환산하려면 --price ARM[:WINDOW]=IN/OUT 와 --price-source 를 함께 준다."
        )

    failed = False
    for arm, outcomes in reports.items():
        metrics = summarize(outcomes)
        if args.min_detection_lower is not None:
            lower = metrics.detection_lower_bound(args.confidence)
            if lower is None or lower < args.min_detection_lower:
                print(f"[게이트 미달] {arm} 검출 하한 {lower} < {args.min_detection_lower}")
                failed = True
        if args.max_false_alarm_upper is not None:
            upper = metrics.false_alarm_upper_bound(args.confidence)
            if upper is None or upper > args.max_false_alarm_upper:
                print(f"[게이트 미달] {arm} 오경보 상한 {upper} > {args.max_false_alarm_upper}")
                failed = True
    if audit_dir is not None:
        summary = {
            arm: {
                "detection_lower": summarize(o).detection_lower_bound(args.confidence),
                "false_alarm_upper": summarize(o).false_alarm_upper_bound(args.confidence),
                "latency": latency_summary(o),
                "tokens": token_summary(o),
            }
            for arm, o in reports.items()
        }
        (audit_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return _EXIT_GATE_FAIL if failed else _EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
