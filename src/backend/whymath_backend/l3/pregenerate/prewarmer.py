"""캐시 사전적재기 — 런타임 라우터와 *같은* 키로 검증된 시드를 캐시에 채워 넣는다.

런타임(`l3/pipeline.py:125·152`)이 컴퓨트하는 `Router().route(req)` + `cache_key_for(
prompt, system, decision)`을 그대로 재사용 → 사전적재한 키는 런타임이 *반드시* 같은
키로 조회하게 된다(키 정합 보장).

설계 정본: MEMORY.md 2026-05-20 "Max=빌드타임 콘텐츠 생성 → 결과는 캐시/DB 저장 →
학생 런타임은 캐시 히트(0원)". 03a §F.1 캐시 키.

경계 메모: 본 슬라이스는 *시드 품질 위생*까지만 강제한다(BasicSeedValidator). 학생
직접 노출 경계는 L4/L5 환각 방어가 책임진다(CLAUDE.md "LLM 응답을 검증 없이 학생에게
제공 금지" — 사전적재된 응답도 런타임에서 환각 방어를 통과해야 학생에게 닿는다).

관측(OPS-109): provider를 *직접* 부르는 이 모듈은 파이프라인을 거치지 않으므로(그것이 이
모듈의 정의 — 파이프라인을 거치면 캐시 적중 때 생성이 일어나지 않는다) 파이프라인이 해 주는
`l3_routing` trace 기록도 받지 못한다. **그 부재는 설계가 아니라 공백이었다** — 어디에도 의도라는
기록이 없고, 같은 저작 계열인 `llm_generator`가 같은 공백을 "추적 0이던 공백 보정(2026-07-21
정합성 검토)"으로 이미 메웠으며, 프로젝트 규칙이 "모든 LLM 호출 → Langfuse 추적"이다. 그래서
provider 생성 1건마다 라우팅·실측(토큰·지연·원가)을 trace sink에 남긴다.
  - **저작 표지**(`TrafficSurface.AUTHORING`)를 단다. 추측이 아니라 사실이다: 이 클래스를 만드는
    프로덕션 호출부는 배치 CLI(`__main__.py`) 하나뿐이고(소스 스캔 테스트가 동결 — 서빙 경로가
    생기면 red), 모듈 정의가 빌드타임 사전생성이다. 표지가 없으면 이 비용이 게이트② 서빙 표본의
    '미표기'로 섞인다(`ops/cost_report`).
  - **원가 좌석은 꽂힌 provider에서 읽는다**(`served_cloud_seat` — ARCH-64). 좌석을 생략하면
    `SERVING_CLOUD_SEAT`(anthropic) 단가로 적혀 openrouter 호출이 22.5배(CLOUD_MID 실측)로
    기록되고, 단가 미등재 좌석(CLOUD_HIGH)은 '미측정'이어야 할 값이 지어낸 금액이 된다. 생성
    로그(`GenerationLog.cost_usd`)와 trace(`cost_krw`)가 같은 좌석을 읽어 서로 다른 원가를 말하지
    않는다.
  - 기록 시점은 **provider 응답을 받은 직후·검증 전**이다 — 응답이 오면 비용이 발생했으므로 이후
    검증 성패와 무관하게 남긴다(`llm_generator` 동형). provider가 예외를 던진 항목·인제스트·스킵은
    생성 호출이 없었으므로 기록하지 않는다.
  - 생성 로그(provenance 채널·재현 좌표)와 Langfuse trace(운영 관측 채널)는 **다른 채널**이다 —
    하나가 다른 하나를 대신하지 않는다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable

from whymath_backend.config import CloudSeat
from whymath_backend.l3.generation_seed import SeedSource, seed_for_decision
from whymath_backend.l3.interfaces import (
    CacheBackend,
    LLMProvider,
    SurfaceTaggingTraceSink,
    TraceSink,
    TrafficSurface,
)
from whymath_backend.l3.models import CostTier, RoutingDecision, Usage
from whymath_backend.l3.pregenerate.models import (
    PregenItem,
    PrewarmItemResult,
    PrewarmReport,
)
from whymath_backend.l3.pregenerate.provenance_bridge import (
    actual_cost_usd_or_none,
    generation_log_from_result,
    input_snapshot_for_prewarm,
    model_name_for_decision,
)
from whymath_backend.l3.pregenerate.validator import SeedValidator
from whymath_backend.l3.router import (
    Router,
    _as_cost_tier,
    actual_cost_krw,
    cache_key_for,
    langfuse_fields,
)
from whymath_backend.schema.provenance import GenerationLog

logger = logging.getLogger("whymath.l3.pregenerate.prewarmer")

# 생성 로그 싱크 계약 — GenerationLog 1건을 받아 적재한다(JSONL appender·DB 세션 등).
# 예외는 prewarmer가 흡수한다(관측 적재 실패가 사전적재 배치를 깨면 안 됨 — 타입명 로그).
GenerationLogSink = Callable[[GenerationLog], None]


class CachePrewarmer:
    """배치 단위 캐시 사전적재기 — provider·cache·validator 주입.

    `prewarm(items)`은 항목당 (a) 라우팅 → (b) 키 계산 → (c) overwrite=False면 존재 시
    스킵 → (d) 응답 획득(인제스트 우선, 없으면 provider) → (e) 검증 → (f) 통과 시
    `cache.set(key, response, ttl_seconds)`. 각 단계 오류는 *흡수*해 항목 결과로 기록하고
    배치 전체는 계속 진행한다(단일 항목 실패가 배치를 깨면 안 됨).

    `ttl_seconds` 기본 `0` = 무만료(S2 RedisCache는 ttl<=0이면 SET without EX) — 사전
    생성물은 만료되면 의미가 없으므로 기본 무만료. 명시적 회전 정책은 후속.

    `generation_log_sink`(EOS-55 집행 별항): 항목 1건 처리마다 `GenerationLog`(모델·
    prompt_version·seed 좌석·입력 스냅샷 해시+참조)를 조립해 싱크로 흘린다 — 스킵·실패
    항목도 기록한다(성공 경로만 보는 계측 금지·2026-08-22 규칙). None(기본)이면 종전
    동작 그대로(관측 0·기존 호출부 무영향).

    `seed_source`(EOS-73): provider 호출마다 실어 보낼 샘플링 시드의 공급자. None(기본)이면
    `generation_seed.default_seed_source()`(호출마다 새 난수)를 쓴다 — **끄는 옵션을 두지
    않는다**: 좌석만 있고 값이 없는 상태(전 경로 NULL)가 이 태스크가 해소하는 무작동이므로
    "적재가 기본"이어야 한다(genlog 싱크 경로 자체는 CLI가 항상 배선하는 것과 동형). 시드가
    실제로 실리는 경로는 LOCAL뿐이고(클라우드는 구조적 불가) 그 판정은 `seed_for_decision`
    단일 좌석이 한다. 재현 프로브·테스트는 고정 시드 공급자를 주입해 같은 좌표를 되먹인다.

    `trace`(OPS-109): provider 생성 1건마다 라우팅·실측을 기록할 관측 싱크. None(기본)이면
    `LangfuseSink`를 기본 구성한다(키 미설정=no-op·네트워크 0 — `llm_generator` 동형) — 끄는
    옵션을 두지 않는다("모든 LLM 호출 → Langfuse 추적"). 주입된 싱크도 **저작 표지로 감싼다**
    (`SurfaceTaggingTraceSink` — 먼저 실린 표지가 이기므로 이미 표지가 있는 레코드는 그대로다).
    배치 종료 시 `flush_trace()`로 전송을 확정할 것(Langfuse는 배치 전송).
    """

    def __init__(
        self,
        *,
        provider: LLMProvider,
        cache: CacheBackend,
        validator: SeedValidator,
        router: Router | None = None,
        generation_log_sink: GenerationLogSink | None = None,
        seed_source: SeedSource | None = None,
        trace: TraceSink | None = None,
    ) -> None:
        self._provider = provider
        self._cache = cache
        self._validator = validator
        self._router = router if router is not None else Router()
        self._generation_log_sink = generation_log_sink
        self._seed_source = seed_source
        if trace is None:
            # 관측 기본 배선 — 지연 import·키 미설정=no-op(네트워크 0)·`llm_generator`와 동형.
            from whymath_backend.l3.trace.langfuse_sink import LangfuseSink

            trace = LangfuseSink()
        # 이 모듈의 provider 호출은 전부 빌드타임 저작이다 — 표지는 사실이다(모듈 docstring).
        self._trace: TraceSink = SurfaceTaggingTraceSink(trace, TrafficSurface.AUTHORING)

    async def prewarm(
        self,
        items: Iterable[PregenItem],
        *,
        ttl_seconds: int = 0,
        overwrite: bool = False,
    ) -> PrewarmReport:
        """항목 배치를 사전적재 — 결과 리포트 반환(예외 전파 없음)."""
        results: list[PrewarmItemResult] = []
        for item in items:
            results.append(
                await self._prewarm_one(item, ttl_seconds=ttl_seconds, overwrite=overwrite)
            )
        return PrewarmReport(items=tuple(results))

    async def _prewarm_one(
        self,
        item: PregenItem,
        *,
        ttl_seconds: int,
        overwrite: bool,
    ) -> PrewarmItemResult:
        """항목 1건: 라우팅 → 본처리 → 생성 로그 적재(EOS-55) — 결과는 그대로 반환."""
        decision = self._router.route(item.request)
        result = await self._prewarm_with_decision(
            item, decision, ttl_seconds=ttl_seconds, overwrite=overwrite
        )
        self._emit_generation_log(item, decision, result)
        return result

    def _emit_generation_log(
        self,
        item: PregenItem,
        decision: RoutingDecision,
        result: PrewarmItemResult,
    ) -> None:
        """항목 결과 → GenerationLog 조립·싱크 적재 (EOS-55 집행 별항 — never-break).

        기록 원칙(날조 금지):
          - `problem_id=None`·`cu_slug=None` — 사전적재 시드는 problem 레코드도 코퍼스 CU
            정체성도 없다(캐시 키 단위 자산·#912 P1-2 "가진 정체성만 기록"의 이 경로 값).
          - `prompt_version=None` — 이 경로는 프롬프트 템플릿 체계가 없다(2026-08-30 실측).
            좌석만 두고 실사용 시점에 실제 값을 기록한다(번호를 발명하지 않는다).
          - `seed`: **provider에 실제로 실려 나간 시드**(EOS-73 — `result.seed`). 호출이
            없었던 항목(인제스트·스킵)과 시드를 실을 수 없는 경로(클라우드 = Anthropic
            Messages API에 seed 파라미터 부재)는 None=미기록이다. 여기서 새로 뽑지 않는
            이유: 뽑은 값과 보낸 값이 갈라지는 순간 기록이 재현을 보장하지 못한다.
          - `cost_usd`: 로컬 0원 확정 / 클라우드 토큰 미상 None(`actual_cost_usd_or_none`).
          - 스냅샷: `input_snapshot_for_prewarm` — 프롬프트/시스템 **전문**+sha256 핀 +
            request 원문(#912 P1-1 자기완결).
        싱크 예외는 흡수하되 **타입명을 로그에 남긴다**(침묵 실패 금지 — 관측 적재 실패가
        배치를 깨면 안 됨·`llm_generator._record_trace` 동형).
        """
        if self._generation_log_sink is None:
            return
        try:
            log = generation_log_from_result(
                result,
                problem_id=None,
                model_name=model_name_for_decision(decision),
                cost_usd=actual_cost_usd_or_none(decision, result.usage, seat=self._served_seat()),
                seed=result.seed,
                input_snapshot=input_snapshot_for_prewarm(item),
            )
            self._generation_log_sink(log)
        except Exception as exc:  # noqa: BLE001 — 관측 적재 장애는 배치 비차단(타입명 로그)
            logger.warning("사전적재 생성 로그 적재 실패(%s) — 무시하고 계속", type(exc).__name__)

    async def _prewarm_with_decision(
        self,
        item: PregenItem,
        decision: RoutingDecision,
        *,
        ttl_seconds: int,
        overwrite: bool,
    ) -> PrewarmItemResult:
        """라우팅 결정이 주어진 항목 1건의 본처리 (provider 호출 경로에서 시드를 실어 보낸다)."""

        # QUALITY(async)는 런타임 파이프라인이 async 분기에서 캐시를 *치지 않는다*
        # (pipeline.py:128-149 — async는 enqueue만 하고 cache.get/set 없음). 따라서
        # 사전적재해도 런타임이 영원히 못 읽는다 → 의미 없으므로 명시적 error로 표시.
        if decision.mode == "async":
            return PrewarmItemResult(
                cache_key="",
                status="error",
                error=(
                    "QUALITY async decisions don't hit runtime cache "
                    "(pipeline.generate async branch skips cache, 03a §D.3)"
                ),
            )

        key = cache_key_for(item.prompt, item.system, decision)

        # 중복 적재 회피 — overwrite=False면 존재 시 스킵(불필요한 재생성/덮어쓰기 방지).
        if not overwrite:
            try:
                existing = await self._cache.get(key)
            except Exception as exc:  # noqa: BLE001 — 캐시 조회 오류도 비크래시로 흡수
                return PrewarmItemResult(
                    cache_key=key,
                    status="error",
                    error=f"cache.get failed: {type(exc).__name__}: {exc}",
                )
            if existing is not None:
                return PrewarmItemResult(cache_key=key, status="skipped_exists")

        # 응답 획득 — 인제스트 모드(precomputed) 우선, 없으면 provider 호출.
        # usage(실측 토큰·지연)는 provider 생성 경로에서만 존재한다(인제스트는 None).
        usage: Usage | None = None
        # 실제로 provider에 실려 나간 시드만 담는다 — 인제스트·스킵 경로는 None(호출 자체가
        # 없으므로 "미기록"이 정직·PrewarmItemResult.seed docstring).
        seed: int | None = None
        if item.precomputed_response is not None:
            response = item.precomputed_response
        else:
            # 시드는 *호출 직전*에 뽑는다 — 스킵·인제스트로 끝난 항목에 쓰이지 않은 시드가
            # 붙는 것을 구조적으로 막는다. 클라우드 결정이면 seed_for_decision이 None을
            # 돌려주고(구조적 불가), 그 경우 아래 호출 kwargs에도 실리지 않는다.
            # 공급자 자체가 잘못 주입된 경우(범위 밖 값)는 흡수하지 않는다 — 배치 전체가
            # 잘못된 좌표를 기록하게 되므로 첫 항목에서 크게 실패하는 편이 낫다(라우팅 호출과
            # 같은 취급·`_prewarm_one`의 route()도 감싸지 않는다).
            seed = seed_for_decision(decision, source=self._seed_source)
            try:
                # seed는 *값이 있을 때만* 싣는다 — 미지원 경로(클라우드)에 실으면 provider가
                # 명확히 거부하고, seed 인자를 모르는 구형 대역과의 하위호환도 유지된다.
                if seed is None:
                    generated = await self._provider.generate(item.prompt, item.system, decision)
                else:
                    generated = await self._provider.generate(
                        item.prompt, item.system, decision, seed=seed
                    )
            except Exception as exc:  # noqa: BLE001 — provider 오류는 항목 단위로 흡수
                return PrewarmItemResult(
                    cache_key=key,
                    status="error",
                    error=f"provider.generate failed: {type(exc).__name__}: {exc}",
                    # 호출을 *시도한* 좌표는 남긴다 — 실패 재현(같은 시드로 재시도)의 재료다.
                    seed=seed,
                )
            response = generated.text
            usage = generated.usage
            # 응답이 왔다 = 비용이 발생했다 — 이후 검증 성패와 무관하게 관측을 먼저 남긴다.
            self._record_trace(decision, usage)

        # 검증 게이트 — 통과한 시드만 캐시에 적재(품질 위생).
        failure_reason = self._validator.validate(item, response)
        if failure_reason is not None:
            return PrewarmItemResult(
                cache_key=key,
                status="failed_validation",
                # 신호의 사유 문자열만 담는다(error: str | None 계약 유지·slice 59).
                error=failure_reason.reason,
                usage=usage,
                seed=seed,
            )

        try:
            await self._cache.set(key, response, ttl_seconds)
        except Exception as exc:  # noqa: BLE001 — 캐시 적재 오류도 항목 단위로 흡수
            return PrewarmItemResult(
                cache_key=key,
                status="error",
                error=f"cache.set failed: {type(exc).__name__}: {exc}",
                usage=usage,
                seed=seed,
            )

        return PrewarmItemResult(cache_key=key, status="written", usage=usage, seed=seed)

    # ── 관측(OPS-109 — 사전적재 호출도 Langfuse에 남긴다) ──
    def _served_seat(self) -> CloudSeat | None:
        """클라우드 결정이 실제로 가는 좌석 — 원가 기록의 단가 좌석(ARCH-64·꽂힌 provider 기준).

        `pipeline.served_cloud_seat`가 단일 원천이다. 함수 안에서 import하는 이유: `pipeline`이
        `pregenerate.validator`를 import하므로(`pregenerate/__init__`가 이 모듈을 먼저 로드) 모듈
        최상단 import는 순환이다. 미상(None)은 anthropic으로 접지 않는다 — 호출부가 '미측정'으로
        남긴다(CLAUDE.md "모른다 ≠ 아니다").
        """
        from whymath_backend.l3.pipeline import served_cloud_seat

        return served_cloud_seat(self._provider)

    def _record_trace(self, decision: RoutingDecision, usage: Usage | None) -> None:
        """생성 1건의 라우팅·실측(usage·원가)을 sink에 기록 — never-break(배치 비차단).

        원가 회계는 `pipeline.generate`·`llm_generator`와 동형: usage 없음(미계측)·클라우드인데 토큰
        미상이면 None('미상'과 0원 구분 — 지어내지 않음), 그 외 토큰 산정(LOCAL 0원 확정). 좌석은
        꽂힌 provider에서 읽고(`_served_seat`) 같은 값을 `cloud_seat`에 실어 "어느 단가표로
        계상했나"를 같은 레코드가 말하게 한다. student_id_hash는 없다(빌드타임 — 학생 무관).
        """
        is_cloud = _as_cost_tier(decision.cost_tier) is not CostTier.LOCAL
        seat = self._served_seat() if is_cloud else None
        actual_krw: float | None
        if usage is None:
            actual_krw = None
        elif is_cloud and (usage.input_tokens is None or usage.output_tokens is None):
            actual_krw = None
        else:
            actual_krw = actual_cost_krw(decision, usage, seat=seat)
        try:
            self._trace.record(
                langfuse_fields(
                    decision,
                    cache_hit=False,
                    usage=usage,
                    cost_krw=actual_krw,
                    cloud_seat=seat,
                )
            )
        except Exception as exc:  # noqa: BLE001 — 관측 장애가 사전적재 배치를 깨면 안 됨
            # 침묵 실패 금지 — 예외 *타입명*만 경고(필드·키 값 미출력, langfuse_sink 방침 동형).
            logger.warning("사전적재 관측 기록 실패(%s) — 무시하고 계속", type(exc).__name__)

    def flush_trace(self) -> None:
        """배치 종료 시 관측 전송 확정 — LangfuseSink는 배치 전송이라 CLI가 flush로 확정한다.

        TraceSink 계약은 record만 요구하므로 flush 없는 sink(테스트 대역)는 조용히 통과한다
        (`SurfaceTaggingTraceSink`가 안쪽 sink의 flush로 위임). flush 오류도 삼키되 타입명은 남긴다.
        """
        flush = getattr(self._trace, "flush", None)
        if not callable(flush):
            return
        try:
            flush()
        except Exception as exc:  # noqa: BLE001 — 관측 전송 장애가 배치 결과를 깨면 안 됨
            logger.warning("사전적재 관측 flush 실패(%s) — 무시", type(exc).__name__)
