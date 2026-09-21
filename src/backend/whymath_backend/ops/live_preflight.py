"""라이브 프리플라이트 — 라이브 키 투입 *직후 1회* 실행하는 계측 흐름 즉석 검증.

배경
----
Kiki가 Phaiakes9(또는 프로덕션)에 라이브 키(Anthropic·Langfuse)를 수동 주입한 **직후
1회** 실행해, 방금 넣은 키로 실제 계측이 흐르는지 즉석에서 확인하는 도구다. 서버(uvicorn)
를 띄우지 않고 provider를 직접 호출하므로, 배포 파이프라인에 태우기 전 손끝 검증에 쓴다.
LIVE_LLM_ACTIVATION.md §10 "활성 확인/스모크"를 이 단일 명령으로 턴키화한다(§11 판독 연결).

판정 항목
--------
① cloud_configured   — `Settings().anthropic_configured`(config.py). Anthropic 키가 채워졌는가.
② langfuse_configured — `Settings().langfuse_configured`(config.py). 공개키·시크릿키가 둘 다인가.
   도달성      — Anthropic·Ollama `check_status()`(reachable/error)를 /status 없이 직접 점검.
③ 클라우드 스모크    — (스모크 on·anthropic 설정 시) 실 클라우드 CLOUD_MID(Sonnet) 1콜 →
   실측 usage(토큰·지연) → `actual_cost_krw`로 실측 비용(원) 산출. anthropic 미설정이면
   "키 없음"을 명시하고 조용한 실패 없이 graceful skip 한다.

실행
----
    python -m whymath_backend.ops.live_preflight            # 스모크 on(기본) — 실 1콜
    python -m whymath_backend.ops.live_preflight --no-smoke # 판정·도달성만(실 호출 없음)
    python -m whymath_backend.ops.live_preflight --json report.json  # JSON 리포트도 저장
    python -m whymath_backend.ops.live_preflight --via-pipeline      # 스모크를 pipeline 경유

--via-pipeline (§11 Langfuse 기록까지 확인 — Redis·서버·crypto·db 없이)
--------------------------------------------------------------------
기본 경로는 provider를 *직접* 호출한다(위 ③). `--via-pipeline`이면 스모크를 대신
`l3.pipeline.generate`로 태운다 — 라우터 → 캐시(InMemoryCache) → provider(CompositeProvider)
→ 관측(LangfuseSink) 전 결선을 거쳐 **Langfuse `l3_routing` 이벤트를 실제 기록**하고,
CLI가 곧 종료하므로 `trace.flush()`로 전송을 확정한다. 전체 앱(uvicorn)이 요구하는
PII 암호화(cryptography)·DB(pgvector)·Redis·서버 기동을 전부 우회한다 — pipeline import
체인은 config·l3만이라 뒤엉킨 conda/venv 환경에서도 돈다.

라우팅 목표: anthropic 설정 시 **CLOUD_MID(sync)**로 라우팅되는 신호(premium·requires_
reasoning·budget 충분·hard/diagnose)를 실어 실 클라우드 1콜의 실측 비용을 Langfuse에
남긴다(QUALITY 비동기·CLOUD_HIGH로 새지 않게 — async면 job_id만 반환돼 스모크 부적합).
anthropic *미설정*이면 **LOCAL(easy/free)로 폴백**해 로컬 1콜을 태운다 — cost_tier=LOCAL·
cost_krw=0.0이라도 Langfuse 기록 증명 자체는 성립한다(그 사실을 출력에 명시).
**Langfuse 미설정이면** 기록 대상이 없으므로 pipeline 호출 없이 graceful skip(exit 0).

시크릿 안전
----------
키 *값*은 절대 출력하지 않는다 — 설정 여부(bool)·실측 비용(원)·토큰 수만 보고한다.

None-vs-0 원칙(CLAUDE.md "모르면 모른다고")
--------------------------------------------
usage 자체가 없거나(미계측 provider) 클라우드인데 토큰이 미상(None)이면 비용을 **None**으로
남긴다 — '산정 불가(미상)'와 '0원 확정'을 구분한다(값을 지어내지 않음). 로컬만 0.0 확정이며,
이 스모크는 항상 CLOUD_MID라 토큰 미상 시 cost=None이다(pipeline.py 로직과 동형).

종료 코드
--------
- 0  : 정상. *미설정*(키 없음·스모크 skip)은 오류가 아니라 정보이므로 0.
- 2  : 실질 오류 — 클라우드가 *설정됐는데* 도달 불가, 또는 스모크 1콜이 예외로 실패.
  (Ollama 도달성은 정보로만 보고하고 종료 코드를 좌우하지 않는다 — 이 도구가 검증하는
   대상은 방금 주입한 클라우드·관측성 키의 흐름이지 로컬 스택 기동 여부가 아니다.)
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from whymath_backend.config import Settings
from whymath_backend.l3 import pipeline
from whymath_backend.l3.data_grade_defaults import SYNTHETIC_PROBE
from whymath_backend.l3.interfaces import CacheBackend, InMemoryCache, LLMProvider
from whymath_backend.l3.models import (
    CostTier,
    GenerationResult,
    RoutingDecision,
    RoutingRequest,
)
from whymath_backend.l3.providers.anthropic import AnthropicProvider, AnthropicStatus
from whymath_backend.l3.providers.composite import CompositeProvider
from whymath_backend.l3.providers.ollama import OllamaProvider, OllamaStatus
from whymath_backend.l3.router import Router, _as_cost_tier, actual_cost_krw
from whymath_backend.l3.trace.langfuse_sink import LangfuseSink

# 스모크 프롬프트 — 가장 짧고 결정적인 산술 1콜(토큰·비용을 실측하려는 것이지 정답 채점이 아님).
_SMOKE_PROMPT = "1 + 1은 얼마인가? 숫자만 답하라."
_SMOKE_SYSTEM = "너는 간결한 수학 조수다. 요청받은 것만 최소로 답한다."

# 종료 코드 — 미설정은 정보(0), 설정됐는데 실패는 오류(2).
_EXIT_OK = 0
_EXIT_ERROR = 2


class _CloudProvider(Protocol):
    """스모크·도달성에 필요한 클라우드 provider 경계 (AnthropicProvider 충족).

    테스트가 라이브 없이 태울 수 있도록 Protocol로 최소 표면만 요구한다.
    """

    @property
    def configured(self) -> bool: ...

    async def check_status(self) -> AnthropicStatus: ...

    async def generate(
        self, prompt: str, system: str, decision: RoutingDecision
    ) -> GenerationResult: ...


class _LocalProvider(Protocol):
    """도달성 점검에 필요한 로컬 provider 경계 (OllamaProvider 충족)."""

    async def check_status(self) -> OllamaStatus: ...


# provider 주입 지점 — 기본은 실 provider, 테스트는 가짜를 주입한다(라이브 0).
CloudProviderFactory = Callable[[Settings], _CloudProvider]
LocalProviderFactory = Callable[[Settings], _LocalProvider]


def _default_cloud_provider(settings: Settings) -> _CloudProvider:
    """기본 클라우드 provider — 주입된 Settings로 AnthropicProvider 구성."""
    return AnthropicProvider(settings=settings)


def _default_local_provider(settings: Settings) -> _LocalProvider:
    """기본 로컬 provider — 주입된 Settings로 OllamaProvider 구성."""
    return OllamaProvider(settings=settings)


@dataclass(slots=True, frozen=True)
class SmokeResult:
    """③ 클라우드 스모크 1콜 결과 — 실측 비용·토큰·지연(또는 skip/실패 사유)."""

    ran: bool
    """실제로 1콜을 실행했는가. False면 skipped_reason이 이유를 담는다."""

    skipped_reason: str | None = None
    """스모크를 건너뛴 사유(스모크 off·anthropic 미설정 등). ran=True면 None."""

    cost_krw: float | None = None
    """실측 비용(원) — None이면 '산정 불가(미상)'이지 0원이 아니다(None-vs-0)."""

    input_tokens: int | None = None
    """입력 토큰 수(provider usage 포착). 미상이면 None."""

    output_tokens: int | None = None
    """출력 토큰 수(provider usage 포착). 미상이면 None."""

    latency_ms: float | None = None
    """호출 실측 지연(ms). 미측정이면 None."""

    text_chars: int | None = None
    """생성 텍스트 *길이*만 기록(내용은 로그에 남기지 않음). 실패 시 None."""

    error: str | None = None
    """1콜이 예외로 실패한 경우의 오류 요약. 정상이면 None."""

    # ── --via-pipeline 경로 전용 필드(기본 경로는 전부 기본값) ──
    via_pipeline: bool = False
    """스모크가 pipeline.generate 경유였는가(--via-pipeline). 기본 경로는 False."""

    routed_cost_tier: str | None = None
    """pipeline 라우터가 *실제로* 결정한 cost_tier(local/cloud_mid/…). 기본 경로는 None."""

    langfuse_recorded: bool = False
    """Langfuse에 `l3_routing` 이벤트를 기록·flush 했는가(--via-pipeline 성공 시 True)."""

    pipeline_note: str | None = None
    """pipeline 경로의 라우팅 의도 메모(CLOUD_MID 목표 / LOCAL 폴백 사유). 기본 경로는 None."""


@dataclass(slots=True, frozen=True)
class Report:
    """프리플라이트 종합 리포트 — 사람용 출력·JSON 직렬화의 단일 진실."""

    cloud_configured: bool
    """① Anthropic 키 설정 여부(Settings 기준·정본)."""

    langfuse_configured: bool
    """② Langfuse 공개키·시크릿키 둘 다 설정 여부(Settings 기준)."""

    cloud_reachable: bool | None
    """클라우드 도달·인증(설정된 경우만 점검, 미설정이면 None=미점검)."""

    cloud_error: str | None
    """클라우드 도달 실패 사유(설정+실패 시). 정상·미설정이면 None."""

    ollama_reachable: bool
    """로컬 Ollama 데몬 도달 여부(정보용 — 종료 코드에 영향 없음)."""

    ollama_error: str | None
    """Ollama 도달 실패 사유. 정상이면 None."""

    smoke: SmokeResult
    """③ 클라우드 스모크 결과."""

    exit_code: int
    """종료 코드 — 0(정상·미설정) / 2(설정됐는데 도달 불가·스모크 실패)."""


def _cloud_mid_decision() -> RoutingDecision:
    """스모크용 CLOUD_MID(Sonnet) 결정 — **라우터 경유**(EOS-77), 손 조립 아님.

    2026-09-05 이전에는 `RoutingDecision(cost_tier=CLOUD_MID, ...)`를 직접 조립했다. 그 결정은
    데이터 등급(법적) 게이트(`Router.route` 안의 `guard_data_export`)를 지나지 않아
    `data_export_reason=None`으로 provider에 도달했다 — 프로덕션 유일의 클라우드 우회였다
    (EOS-59 자진 공개). 지금은 `--via-pipeline` 경로와 같은 요청(`_cloud_mid_smoke_request`:
    premium·requires_reasoning·budget 충분·hard/diagnose·등급 SYNTHETIC_PROBE)을 라우터에
    태워 CLOUD_MID를 *받아낸다*. 판정(`EXPORT_ALLOWED`)이 결정에 실리므로 `ops.cost_report`가
    이 스모크를 "라우터 게이트 미경유"로 경고하지 않는다.

    긴장(태스크 ②): 라우터를 거치면 비즈니스 규칙(구독·예산 임계)이 바뀔 때 CLOUD_MID가 아닌
    티어가 나올 수 있고, 그러면 이 도구가 재려던 것(클라우드 1콜 실측 비용)을 못 잰다. 그것을
    *조용히* 로컬 스모크로 바꾸지 않도록 `_run_smoke`가 티어를 검사해 CLOUD_MID가 아니면
    스모크를 실행하지 않고 exit 2(측정 실패)로 크게 알린다. 단위 테스트가 현행 규칙에서
    CLOUD_MID·EXPORT_ALLOWED가 나옴을 동결하므로 규칙 변경은 PR 시점에 드러난다.
    """
    return Router().route(_cloud_mid_smoke_request())


async def _run_smoke(cloud: _CloudProvider) -> SmokeResult:
    """실 클라우드 CLOUD_MID 1콜 → 실측 usage·비용(None-vs-0)."""
    decision = _cloud_mid_decision()
    # 라우터가 CLOUD_MID를 주지 않았다면 재려던 것을 못 잰다 — 로컬 1콜로 *조용히* 대체하지
    # 않고 측정 실패로 표면화한다(exit 2). 비즈니스 규칙 변경·등급 게이트 발동 둘 다 여기서
    # 드러난다(`data_export_blocked`가 True면 게이트가 막은 것 — 사유를 그대로 싣는다).
    routed = _as_cost_tier(decision.cost_tier)
    if routed is not CostTier.CLOUD_MID:
        return SmokeResult(
            ran=False,
            error=(
                f"라우터가 CLOUD_MID를 내지 않았다(cost_tier={decision.cost_tier}, "
                f"reason={decision.reason!r}, data_export_blocked={decision.data_export_blocked}, "
                f"data_export_reason={decision.data_export_reason}) — 스모크 미실행·측정 실패"
            ),
        )
    try:
        generated = await cloud.generate(_SMOKE_PROMPT, _SMOKE_SYSTEM, decision)
    except Exception as exc:  # noqa: BLE001 — 스모크 실패를 리포트로 흡수(종료 코드로 표면화)
        return SmokeResult(ran=True, error=f"{type(exc).__name__}: {exc}")

    usage = generated.usage
    # None-vs-0 구분(pipeline.py:234-241 동형): usage 없음 → None; 토큰 미상 → None; 그 외에만
    # 실측 비용을 산정한다. 이 경로는 위 가드로 *항상* CLOUD_MID다 — 예전의
    # `decision.cost_tier is not CostTier.LOCAL` 분기는 `use_enum_values=True`라 필드가
    # 문자열이어서 항상 참이었고(변별력 0), 가드가 티어를 확정한 지금은 분기 자체가 불필요하다
    # (EOS-77 정정 — mypy도 CLOUD_MID로 좁힌 값과 LOCAL의 비교를 non-overlapping으로 거부한다).
    cost_krw: float | None
    if usage is None:
        cost_krw = None
    elif usage.input_tokens is None or usage.output_tokens is None:
        cost_krw = None
    else:
        cost_krw = actual_cost_krw(decision, usage)

    return SmokeResult(
        ran=True,
        cost_krw=cost_krw,
        input_tokens=usage.input_tokens if usage is not None else None,
        output_tokens=usage.output_tokens if usage is not None else None,
        latency_ms=usage.latency_ms if usage is not None else None,
        text_chars=len(generated.text),
    )


# ──────────────────────────────────────────────────────────────────────────
# --via-pipeline 경로 — 스모크를 pipeline.generate로 태워 Langfuse에 기록·flush.
# 기본 경로(위 _run_smoke·직접 provider.generate)와 완전히 분리된다(플래그일 때만).
# ──────────────────────────────────────────────────────────────────────────


class _FlushTraceSink(Protocol):
    """pipeline이 쓰는 record + CLI가 강제하는 flush를 갖춘 관측성 싱크 경계.

    interfaces.TraceSink(record만)에 flush를 더한 좁은 경계다. LangfuseSink가 record·
    flush를 모두 노출하므로 이를 충족한다(테스트 스파이 싱크도 동일 표면으로 주입).
    """

    def record(self, fields: dict[str, object]) -> None: ...

    def flush(self) -> None: ...


class _CapturingTraceSink:
    """pipeline이 record한 필드를 갈무리하며 내부 싱크로 위임(그리고 flush 위임).

    pipeline.generate는 실측 usage·cost_krw를 *결과로 돌려주지 않고* trace.record로만
    흘린다(pipeline.py §S1 게이트②). 프리플라이트는 그 record된 dict에서 cost_krw·토큰을
    읽어 출력해야 하므로, 실전송 싱크(LangfuseSink)로 그대로 전달하는 동시에 마지막
    필드를 보관한다. flush는 내부 싱크로 위임한다(전송 확정). _FlushTraceSink 충족.
    """

    def __init__(self, inner: _FlushTraceSink) -> None:
        self._inner = inner
        self.records: list[dict[str, object]] = []

    def record(self, fields: dict[str, object]) -> None:
        """필드를 갈무리하고 내부 싱크로 전달(Langfuse 실전송)."""
        self.records.append(fields)
        self._inner.record(fields)

    def flush(self) -> None:
        """내부 싱크의 flush로 위임(배치 강제 전송)."""
        self._inner.flush()


@dataclass(slots=True)
class PipelineDeps:
    """--via-pipeline 스모크가 조립하는 의존성 묶음 — 테스트가 통째로 주입 가능.

    기본은 실 provider(CompositeProvider)·InMemoryCache·LangfuseSink(캡처 래핑)·실
    pipeline.generate다. 테스트는 가짜 provider·스파이 trace를 넣어 라이브 없이 경로를
    태운다(pipeline.generate 자체는 순수라 실물 그대로 돌린다).
    """

    provider: LLMProvider
    cache: CacheBackend
    trace: _CapturingTraceSink
    generate: _PipelineGenerate


# pipeline.generate 시그니처의 좁은 별칭 — 테스트 주입·기본값 타이핑용(키워드 경계만).
_PipelineGenerate = Callable[..., Awaitable[pipeline.GenerationResult]]
PipelineDepsFactory = Callable[[Settings], PipelineDeps]


def _default_pipeline_deps(settings: Settings) -> PipelineDeps:
    """기본 pipeline 의존성 — CompositeProvider·InMemoryCache·LangfuseSink(캡처 래핑).

    provider·sink 생성은 지연 클라이언트라 여기서 네트워크·키를 요구하지 않는다(첫
    호출 시에만 접속). crypto/db는 어느 것도 import·구성하지 않는다(--via-pipeline의
    환경 회피 목적 유지 — pipeline·l3만).
    """
    provider = CompositeProvider(
        local=OllamaProvider(settings=settings),
        cloud=AnthropicProvider(settings=settings),
    )
    trace = _CapturingTraceSink(LangfuseSink(settings=settings))
    return PipelineDeps(
        provider=provider,
        cache=InMemoryCache(),
        trace=trace,
        generate=pipeline.generate,
    )


def _cloud_mid_smoke_request() -> RoutingRequest:
    """CLOUD_MID(sync)로 *신뢰성 있게* 라우팅되는 요청 (router._decide_cost_tier 규칙4).

    premium 구독 + requires_reasoning=True + 충분한 budget_krw → guard_cloud(CLOUD_MID)
    통과 → CLOUD_MID sync. difficulty=hard(killer 아님)·task_type=diagnose(prove 아님)라
    규칙3(CLOUD_HIGH)로 승급하지 않고, sync=True라 QUALITY(async)로도 새지 않는다
    (async면 job_id만 반환돼 스모크로 부적합). 실 클라우드 1콜의 실측 비용을 남긴다.
    """
    return RoutingRequest(
        task_type="diagnose",
        difficulty="hard",
        requires_reasoning=True,
        student_subscription="premium",
        budget_krw=1000.0,  # cloud_min_cost(CLOUD_MID)=28원 여유(guard 통과)
        sync=True,
        max_latency_ms=30000,
        # 등급: 스모크 프롬프트는 이 모듈이 만든 합성 문자열 — 반출 가능. 데이터 등급
        # 게이트(EOS-59)도 통과해야 CLOUD_MID에 실제로 도달한다(두 가드 모두 통과 조건).
        data_licenses=SYNTHETIC_PROBE,
    )


def _local_smoke_request() -> RoutingRequest:
    """LOCAL(fast, sync)로 라우팅되는 폴백 요청 — anthropic 미설정 시.

    free 구독 → 규칙2 LOCAL. easy·추론 불필요 → 축2 FAST sync(로컬 즉답). Ollama 로컬
    1콜로 Langfuse에 cost_tier=LOCAL·cost_krw=0.0을 기록한다 — 클라우드 비용은 아니지만
    "pipeline 경유 Langfuse 기록" 증명 자체는 이것으로 성립한다.
    """
    return RoutingRequest(
        task_type="explain",
        difficulty="easy",
        requires_reasoning=False,
        student_subscription="free",
        budget_krw=0.0,
        sync=True,
        # 등급: 합성 스모크 문자열 — 반출 가능(이 요청은 free·예산 0이라 어차피 LOCAL).
        data_licenses=SYNTHETIC_PROBE,
    )


def _opt_float(value: object) -> float | None:
    """캡처된 필드값(object)을 float|None으로 좁힌다(bool 제외·미상은 None)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _opt_int(value: object) -> int | None:
    """캡처된 필드값(object)을 int|None으로 좁힌다(bool 제외·미상은 None)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


async def _run_pipeline_smoke(*, cloud_configured: bool, deps: PipelineDeps) -> SmokeResult:
    """스모크를 pipeline.generate로 태워 Langfuse에 기록·flush 한다.

    anthropic 설정 시 CLOUD_MID(sync) 목표 요청을, 미설정 시 LOCAL 폴백 요청을 쓴다.
    호출 후 `trace.flush()`로 전송을 확정하고, trace가 갈무리한 record dict에서 실측
    cost_krw·토큰을 읽는다(pipeline은 결과로 usage를 돌려주지 않음). 예외는 리포트로
    흡수해 종료 코드(2)로 표면화한다(_run_smoke와 동일 방침)."""
    if cloud_configured:
        req = _cloud_mid_smoke_request()
        note = "CLOUD_MID(sync) 목표 — 실 클라우드 1콜"
    else:
        req = _local_smoke_request()
        note = "LOCAL 폴백(anthropic 미설정) — 로컬 1콜, cost_tier=LOCAL·0원이라도 기록 증명 성립"

    try:
        result = await deps.generate(
            req,
            _SMOKE_PROMPT,
            _SMOKE_SYSTEM,
            provider=deps.provider,
            cache=deps.cache,
            trace=deps.trace,
        )
        # 짧게 끝나는 CLI — 배치 유실 방지로 전송을 지금 확정한다(LangfuseSink.flush).
        deps.trace.flush()
    except Exception as exc:  # noqa: BLE001 — 스모크 실패를 리포트로 흡수(종료 코드로 표면화)
        return SmokeResult(
            ran=True, via_pipeline=True, pipeline_note=note, error=f"{type(exc).__name__}: {exc}"
        )

    # 라우터가 실제로 결정한 티어(문자열/enum 혼재 정규화) — 목표 vs 실제를 출력에 노출.
    routed = _as_cost_tier(result.decision.cost_tier).value
    # 실측 cost_krw·토큰은 trace가 갈무리한 마지막 record dict(langfuse_fields 형태)에서 읽는다.
    captured = deps.trace.records[-1] if deps.trace.records else {}
    return SmokeResult(
        ran=True,
        via_pipeline=True,
        pipeline_note=note,
        routed_cost_tier=routed,
        langfuse_recorded=True,
        cost_krw=_opt_float(captured.get("cost_krw")),
        input_tokens=_opt_int(captured.get("input_tokens")),
        output_tokens=_opt_int(captured.get("output_tokens")),
        latency_ms=_opt_float(captured.get("latency_ms")),
        text_chars=len(result.text),
    )


async def run_preflight(
    settings: Settings,
    *,
    smoke: bool,
    via_pipeline: bool = False,
    cloud_provider_factory: CloudProviderFactory = _default_cloud_provider,
    local_provider_factory: LocalProviderFactory = _default_local_provider,
    pipeline_deps_factory: PipelineDepsFactory = _default_pipeline_deps,
) -> Report:
    """프리플라이트 순수 코어 — 라이브 없이도 provider 주입으로 태울 수 있다.

    순서: ①② 판정(Settings) → 도달성(check_status) → ③ 스모크(설정+on일 때만).
    라이브 호출 여부는 전적으로 주입된 provider·`smoke`·설정 상태가 결정한다.

    `via_pipeline`이면 ③ 스모크를 직접 provider.generate 대신 pipeline.generate로 태워
    Langfuse에 기록·flush 한다(pipeline_deps_factory로 의존성 조립; 테스트는 가짜 주입).
    이때 Langfuse *미설정*이면 기록 대상이 없어 graceful skip 한다(pipeline 호출 없음).
    `via_pipeline`이 아니면 기존 동작(직접 provider.generate)과 완전히 동일하다(하위호환).
    """
    # ①② 판정 — Settings가 정본(키 값은 읽지 않고 '채워졌는지'만 본다).
    cloud_configured = settings.anthropic_configured
    langfuse_configured = settings.langfuse_configured

    # 클라우드 도달성 — 설정된 경우만 의미가 있다(미설정이면 None=미점검).
    cloud = cloud_provider_factory(settings)
    cloud_status = await cloud.check_status()
    cloud_reachable = cloud_status.reachable if cloud_configured else None
    cloud_error = cloud_status.error if cloud_configured else None

    # 로컬 Ollama 도달성 — 정보용(종료 코드 무관).
    local = local_provider_factory(settings)
    local_status = await local.check_status()

    # ③ 스모크 — off거나 anthropic 미설정이면 graceful skip(조용한 실패 없음).
    if not smoke:
        smoke_result = SmokeResult(ran=False, skipped_reason="스모크 비활성(--no-smoke)")
    elif via_pipeline:
        # --via-pipeline: 스모크를 pipeline.generate로 태워 Langfuse에 기록·flush 한다.
        # Langfuse 미설정이면 기록 대상이 없어 graceful skip(pipeline 호출조차 안 함) —
        # 키 무 환경(드라이런)에서 Ollama·클라우드 접속 시도 없이 exit 0으로 끝난다.
        if not langfuse_configured:
            smoke_result = SmokeResult(
                ran=False,
                via_pipeline=True,
                skipped_reason="Langfuse 미설정 — 기록 안 됨(--via-pipeline은 Langfuse 기록 목적)",
            )
        else:
            smoke_result = await _run_pipeline_smoke(
                cloud_configured=cloud_configured,
                deps=pipeline_deps_factory(settings),
            )
    elif not cloud_configured:
        smoke_result = SmokeResult(
            ran=False, skipped_reason="anthropic 미설정(키 없음) — 스모크 skip"
        )
    else:
        smoke_result = await _run_smoke(cloud)

    # 종료 코드 — 설정됐는데 도달 불가, 또는 스모크 예외 실패면 오류(2). 미설정은 0(정보).
    exit_code = _EXIT_OK
    if cloud_configured and cloud_reachable is False:
        exit_code = _EXIT_ERROR
    if smoke_result.error is not None:
        exit_code = _EXIT_ERROR

    return Report(
        cloud_configured=cloud_configured,
        langfuse_configured=langfuse_configured,
        cloud_reachable=cloud_reachable,
        cloud_error=cloud_error,
        ollama_reachable=local_status.reachable,
        ollama_error=local_status.error,
        smoke=smoke_result,
        exit_code=exit_code,
    )


def _fmt_bool(value: bool | None) -> str:
    """bool/None을 사람용 표기로(값이 아니라 상태만)."""
    if value is None:
        return "미점검"
    return "예" if value else "아니오"


def _fmt_cost(cost: float | None) -> str:
    """비용(원) 표기 — None은 '미상'(0원과 구분)."""
    if cost is None:
        return "미상(산정 불가)"
    return f"{cost:.4f}원"


def _render_stdout(report: Report) -> str:
    """사람용 stdout 렌더 — 시크릿 값 없이 판정·도달성·스모크만."""
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("WhyMath 라이브 프리플라이트 — 키 투입 직후 계측 흐름 검증")
    lines.append("=" * 60)
    lines.append("[판정]")
    lines.append(f"  ① cloud_configured (Anthropic 키)      : {_fmt_bool(report.cloud_configured)}")
    lines.append(
        f"  ② langfuse_configured (공개·시크릿키)  : {_fmt_bool(report.langfuse_configured)}"
    )
    lines.append("[도달성]")
    cloud_line = f"  · Anthropic reachable                  : {_fmt_bool(report.cloud_reachable)}"
    if report.cloud_error:
        cloud_line += f"  ({report.cloud_error})"
    lines.append(cloud_line)
    ollama_line = f"  · Ollama reachable (정보용)            : {_fmt_bool(report.ollama_reachable)}"
    if report.ollama_error:
        ollama_line += f"  ({report.ollama_error})"
    lines.append(ollama_line)
    smoke = report.smoke
    if smoke.via_pipeline:
        lines.append("[③ 스모크 — pipeline.generate 경유(Langfuse 기록·flush)]")
    else:
        lines.append("[③ 클라우드 스모크 — CLOUD_MID(Sonnet) 1콜]")
    # 실패를 skip보다 먼저 본다 — 라우터가 CLOUD_MID를 안 준 경우는 ran=False *이면서* error다.
    # skip으로 렌더하면 exit 2의 원인이 화면에서 사라진다(측정 실패의 위장).
    if smoke.error is not None:
        lines.append(f"  · 실패: {smoke.error}")
    elif not smoke.ran:
        lines.append(f"  · skip: {smoke.skipped_reason}")
    else:
        if smoke.via_pipeline:
            if smoke.pipeline_note:
                lines.append(f"  · 라우팅 의도   : {smoke.pipeline_note}")
            lines.append(f"  · 라우팅 결과   : cost_tier={smoke.routed_cost_tier}")
        lines.append(f"  · 실측 비용     : {_fmt_cost(smoke.cost_krw)}")
        lines.append(f"  · 입력 토큰     : {smoke.input_tokens}")
        lines.append(f"  · 출력 토큰     : {smoke.output_tokens}")
        lines.append(f"  · 지연(ms)      : {smoke.latency_ms}")
        lines.append(f"  · 응답 길이(자) : {smoke.text_chars}")
        if smoke.via_pipeline and smoke.langfuse_recorded:
            lines.append(
                "  · Langfuse      : l3_routing 이벤트 기록·flush 완료 — 대시보드에서 확인"
            )
    lines.append("-" * 60)
    verdict = "정상(exit 0)" if report.exit_code == _EXIT_OK else f"오류(exit {report.exit_code})"
    lines.append(f"결과: {verdict}")
    lines.append("=" * 60)
    return "\n".join(lines)


def _write_json(report: Report, path: Path) -> None:
    """리포트를 JSON으로 저장 — 시크릿 없이 bool·비용·토큰만(dataclass 직렬화)."""
    path.write_text(
        json.dumps(dataclasses.asdict(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    """얇은 CLI — 인자 파싱 → Settings() 직접 생성 → run_preflight → 출력/종료 코드.

    Settings()는 lru_cache(get_settings)를 우회해 *지금* 주입된 키를 읽는다(투입 직후 1회).
    """
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.ops.live_preflight",
        description="라이브 키 투입 직후 계측 흐름 1회 검증(cloud/langfuse 설정·도달성·실 1콜).",
    )
    parser.add_argument(
        "--no-smoke",
        dest="smoke",
        action="store_false",
        help="실 클라우드 1콜을 건너뛰고 판정·도달성만 확인(기본은 스모크 on).",
    )
    parser.add_argument(
        "--via-pipeline",
        dest="via_pipeline",
        action="store_true",
        help=(
            "스모크를 pipeline.generate로 태워 Langfuse에 l3_routing 이벤트를 기록·flush 한다"
            "(Redis·서버·crypto·db 없이 §11 확인). Langfuse 미설정이면 graceful skip."
        ),
    )
    parser.add_argument(
        "--json",
        dest="json_path",
        default=None,
        help="JSON 리포트 저장 경로(선택). 지정 시 사람용 stdout과 함께 저장한다.",
    )
    args = parser.parse_args(argv)

    settings = Settings()  # lru_cache 우회 — 방금 주입한 키를 읽는다
    report = asyncio.run(run_preflight(settings, smoke=args.smoke, via_pipeline=args.via_pipeline))

    print(_render_stdout(report))
    if args.json_path is not None:
        json_path = Path(args.json_path)
        _write_json(report, json_path)
        print(f"JSON 리포트 저장: {json_path}")

    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
