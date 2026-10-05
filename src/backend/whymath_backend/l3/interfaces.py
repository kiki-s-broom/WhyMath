"""L3 외부 의존 인터페이스 — Protocol(미구현) + 테스트용 인메모리 스텁.

범위 메모 (M1.2): 실제 LLM 클라이언트(Ollama/Anthropic)·Redis·Langfuse·비동기
큐는 *연동하지 않는다*. 라우터가 의존하는 *경계*만 `typing.Protocol`로 선언하고,
단위테스트가 라이브 서비스 없이 통과하도록 인메모리 스텁만 제공한다.
실제 구현은 후속 마일스톤(03a §H 후속 4 클라우드 연동·6 큐 SLA).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Final, Protocol, runtime_checkable

from whymath_backend.l3.models import GenerationResult, RoutingDecision


@runtime_checkable
class LLMProvider(Protocol):
    """LLM 호출 백엔드 경계 (Ollama 로컬 / Anthropic·OpenAI 클라우드).

    라우터는 *결정*만 내리고, 실제 생성은 이 Protocol을 통해 위임된다.
    M1.2에서는 시그니처만 정의 — 구현·라이브 호출 없음.
    """

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        *,
        images: Sequence[str] | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        json_schema: Mapping[str, object] | None = None,
        seed: int | None = None,
    ) -> GenerationResult:
        """라우터 결정(decision)에 따라 응답을 생성한다(미구현).

        반환은 `models.GenerationResult(text, usage)`다 — `text`는 검증 전 원시 출력,
        `usage`는 provider가 포착한 실측 토큰·지연(S1 게이트 ② 비용 실측 배선). usage를
        노출하지 않는 백엔드/테스트 가짜는 usage=None으로 돌려준다(값을 지어내지 않음).
        ⚠️ `pipeline.GenerationResult`(오케스트레이션 결과)와 이름만 같은 다른 타입이다.

        `images`(base64 인코딩 이미지 목록)는 멀티모달(VL) 호출용 *선택적* 입력이다.
        None(기본·텍스트 호출)이면 기존 동작과 동일하다. 비전 미지원 제공자는 images가
        주어지면 *조용한 무시 없이* 명확한 오류를 던진다(CLAUDE.md "모르면 모른다고").

        `temperature`(샘플링 온도)는 *생성 다양성* 제어용 *선택적* 입력이다(S2-g). None(기본)
        이면 제공자가 자기 기본 온도를 쓴다 — 즉 **기존 동작 무변경**(튜터링·도구선택 등 결정론이
        바람직한 호출부는 지정하지 않아 종전 그대로다). 값을 주면(예 동등문제 저작=0.9) 제공자가
        그 온도로 호출한다. 온도를 지원하지 않는 백엔드(예 Opus 4.7·temperature 거부)는 이를
        조용히 무시하지 않고 호출부가 지정하지 않도록 하는 것이 계약이다(아래 각 제공자 주석).

        `top_p`(누적확률 절단·nucleus sampling)는 temperature와 **같은 축의 짝**인 *선택적*
        입력이다(EOS-121 선결조건 A). None(기본)이면 제공자가 top_p를 **싣지 않아** 각 공급사
        기본값이 적용된다 — 즉 **기존 동작 무변경**이다. 기본값을 None으로 두는 이유가 이
        파라미터의 요점이다: 무조건 명시 전송하면 현재 공급사 기본값과 다른 값이 나가 *저작
        품질이 조용히 바뀐다*(회귀). 목표는 "top_p를 켜는 것"이 아니라 **좌석 간 샘플링 설정을
        맞출 수단을 갖는 것**이다 — 좌석별 생성 다양성을 측정할 때 통제되지 않은 공급사 기본값이
        교란 변수가 되기 때문이다(`docs/ops/eos121_seat_generation_diversity_precheck.md` §1:
        저장소에는 두 공급사 기본값이 같다는 근거도 다르다는 근거도 없다 — "모른다 ≠ 아니다").
        값을 주면 제공자가 그 값을 실제 페이로드에 싣는다. top_p를 지원하지 않는 백엔드(예
        Opus 4.7은 temperature/top_p/top_k를 함께 거부·400)는 temperature와 **같은 계약**을
        따른다 — 제공자가 조용히 무시하지 않고, 호출부가 그 경로에 지정하지 않는 것이 계약이다
        (temperature와 다른 정책을 이 축에만 따로 두지 않는다 — 각 제공자 주석 참조).

        `json_schema`(출력 JSON 스키마)는 *structured output 문법 강제*용 *선택적* 입력이다
        (S2-j). None(기본)이면 자유 텍스트 생성 — **기존 동작 무변경**. 스키마를 주면 제공자가
        출력을 그 스키마에 맞는 JSON으로 *문법 수준에서 제약*한다(Ollama `format=` 제약 디코딩).
        문법 제약을 지원하지 않는 백엔드(예 Anthropic plain messages)는 *조용히 무시하지 않고*
        명확한 오류를 던진다 — 호출부가 백엔드에 맞게 지정 여부를 결정하는 것이 계약이다(예
        동등문제 저작은 LOCAL 결정일 때만 스키마를 싣고, 클라우드 경로는 프롬프트+관대 파서로
        동작). 문법 제약은 *형식*만 보장하며 내용의 수학적 진실은 여전히 하류 게이트가 검증한다.

        `seed`(샘플링 시드)는 *생성 재현*용 **선택적** 입력이다(EOS-73). None(기본)이면 제공자가
        시드를 싣지 않는다 — 즉 **기존 동작 무변경**. 값을 주면 제공자가 그 시드로 호출하고,
        호출부는 *같은 값을* `GenerationLog.seed`에 기록해 재투입 좌표를 남긴다. seed를 물리적으로
        받을 수 없는 백엔드(Anthropic Messages API에는 seed 파라미터가 **없다**)는 이를 *조용히
        무시하지 않고* 명확한 오류를 던진다 — 조용히 무시하면 "기록된 seed로 재현된다"고 거짓말하는
        행이 남기 때문이다. 지원 판정의 단일 좌석은 `l3/generation_seed.seed_supported`이며,
        호출부는 그 판정이 True일 때만 seed를 싣는다(json_schema와 동일한 계약 형태).
        """
        ...


@runtime_checkable
class CacheBackend(Protocol):
    """응답 캐시 백엔드 경계 (실제로는 Redis, 03a §F.1).

    캐시 키에 세 축 `{cost_tier}:{local_family}:{local_model}`이 포함되어야 한다
    (라우터의 cache_key() 참조). M1.2에서는 경계만 선언.
    """

    async def get(self, key: str) -> str | None:
        """키로 캐시 조회. 미스면 None(미구현)."""
        ...

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        """키-값 저장(TTL 초). (미구현)"""
        ...


@runtime_checkable
class TraceSink(Protocol):
    """관측성 싱크 경계 (실제로는 Langfuse, 03a §F.2).

    라우터의 langfuse_fields()가 만든 태그 dict를 받아 기록한다.
    M1.2에서는 경계만 선언 — 실제 호출 없음.
    """

    def record(self, fields: dict[str, object]) -> None:
        """라우팅 결정 태그를 기록(미구현)."""
        ...


class TrafficSurface(str, Enum):
    """trace 표면 표지 — 이 호출이 **누구를 위한 트래픽인가**(OPS-84 ③ → OPS-105 일반화).

    `ops/cost_report`의 게이트②는 **학생 대면 루프당 비용**을 잰다. 같은 `l3_routing` 스트림에
    서빙·저작·프로브 호출이 함께 흐르므로 표면이 구분되지 않으면 로컬 비율과 토큰 분포가 위장된다.

    **왜 CallSite 로는 안 되는가**: `CallSite`는 *호출지점*(개념 추출·자기검증 등)의 분류다. 같은
    호출지점을 서빙·저작·프로브가 똑같이 쓰므로 호출지점에서 표면을 유도할 수 없다 — 표면은 호출이
    *어디서 시작됐는가*의 사실이라 호출 경로가 직접 싣는다.

    **왜 별도 불리언이 아니라 닫힌 어휘 한 필드인가**: 표면은 서로 배타적이고(한 호출은 한 표면)
    값이 늘 수 있다. `is_authoring`·`is_probe`로 쪼개면 둘 다 True/둘 다 False 같은 불가능한
    상태가 생기고, 소비측(`cost_report`)이 불리언마다 분기를 늘려야 한다.

    표지가 **없는** 이벤트는 위 셋의 어느 것도 아니다 — `cost_report`가 미표기로 따로 세고 비율을
    보고한다(`TRAFFIC_SURFACE_FIELD`가 비어 있는 것과 `serving`은 다르다).

    표지를 싣는 지점(= 표면을 *아는* 지점): 서빙 = `app.create_app`의 기본 `LangfuseSink` ·
    저작 = `QuestionRephraser`의 래퍼 · 프로브 = `live_preflight`·`cost_probe`의 기본 싱크.
    **싣지 않는 지점(의도적 미표기)**: 비동기 큐 워커(`l3/queue/tasks.py`)와 자체 `LangfuseSink`를
    만드는 오프라인 생성기들(`cross_verify`·`multi_solution`·`pedagogy/*`·`llm_generator`)
    — 표면을 추측해 채우면 틀린 표지가 '관측'으로 위장되므로 비워 두고 미표기 비율로 드러낸다.
    """

    SERVING = "serving"
    """학생 대면 — 게이트② 표본의 대상."""

    AUTHORING = "authoring"
    """저작 — 오프라인 배치(대량·LOCAL·0원)라 학생 대면 비용 표본에 섞이면 안 된다."""

    PROBE = "probe"
    """프로브 — 프리플라이트·비용 측정 같은 계측 트래픽. 측정을 위해 일부러 낸 호출이다."""


TRAFFIC_SURFACE_FIELD: Final = "traffic_surface"
"""기록 dict 안의 표면 표지 키."""


def with_traffic_surface(
    fields: Mapping[str, object], surface: TrafficSurface
) -> dict[str, object]:
    """기록 dict 복사본에 표면 표지를 싣는다 — **먼저 실린 표지가 이긴다**(원 dict 불변).

    표지가 이미 있으면 덮지 않는다. 트래픽의 **출처에 가까운 쪽이 더 구체적**이기 때문이다 —
    저작 래퍼가 단 `authoring`을, 바깥 기본 싱크(서빙)가 `serving`으로 덮어쓰면 오프라인 배치가
    학생 대면 표본으로 되돌아온다. 래퍼가 겹쳐도(저작 → 서빙 기본 싱크) 먼저 실린 표지가 남는다.
    """
    if TRAFFIC_SURFACE_FIELD in fields:
        return dict(fields)
    return {**fields, TRAFFIC_SURFACE_FIELD: surface.value}


class SurfaceTaggingTraceSink:
    """안쪽 싱크로 넘기기 전에 `traffic_surface` 표지를 싣는 얇은 래퍼 — TraceSink 충족.

    호출 경로가 싱크를 **직접 만들지 못할 때**(주입된 싱크를 감싸야 하는 저작·프로브) 쓴다. 싱크를
    스스로 만드는 자리는 `LangfuseSink(traffic_surface=...)`가 같은 규칙을 쓴다.
    `flush`는 안쪽 싱크가 노출할 때만 위임한다(없으면 no-op — 짧게 끝나는 CLI가 래퍼에도 안전하게
    부를 수 있게).
    """

    def __init__(self, inner: TraceSink, surface: TrafficSurface) -> None:
        self._inner = inner
        self._surface = surface

    @property
    def surface(self) -> TrafficSurface:
        """이 래퍼가 싣는 표면."""
        return self._surface

    def record(self, fields: dict[str, object]) -> None:
        """표지를 싣고(먼저 실린 표지 우선) 안쪽 싱크에 기록한다."""
        self._inner.record(with_traffic_surface(fields, self._surface))

    def flush(self) -> None:
        """안쪽 싱크가 `flush`를 노출하면 위임한다."""
        flush = getattr(self._inner, "flush", None)
        if callable(flush):
            flush()


@runtime_checkable
class AsyncJobQueue(Protocol):
    """비동기 작업 큐 경계 (QUALITY 27b 비동기 전용 경로, 03a §D.3).

    QUALITY로 라우팅된 요청은 동기 호출 불가 → 이 큐로 enqueue되고 job_id를
    반환받는다. 동시성 1 제한은 워커 구현의 책임. M1.2에서는 경계만 선언.
    """

    async def enqueue(self, payload: dict[str, object]) -> str:
        """작업을 큐에 넣고 job_id를 반환(미구현)."""
        ...


class InMemoryCache:
    """테스트용 인메모리 캐시 스텁 — CacheBackend 충족.

    Redis 없이 단위테스트에서 캐시 경계를 검증하기 위한 최소 구현.
    TTL은 만료 로직 없이 *기록만* 한다(단위테스트 범위엔 만료 시뮬레이션 불필요).
    프로덕션 사용 금지.
    """

    def __init__(self) -> None:
        # 키 → (값, ttl_seconds). ttl은 기록만 (만료 미구현)
        self._store: dict[str, tuple[str, int]] = {}

    async def get(self, key: str) -> str | None:
        """저장된 값 반환, 없으면 None."""
        entry = self._store.get(key)
        return entry[0] if entry is not None else None

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        """값과 TTL 기록."""
        self._store[key] = (value, ttl_seconds)


class RecordingTraceSink:
    """테스트용 관측성 싱크 스텁 — TraceSink 충족.

    기록된 태그 dict들을 리스트로 보관하여 테스트에서 검증 가능하게 한다.
    실제 Langfuse 전송 없음.
    """

    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def record(self, fields: dict[str, object]) -> None:
        """태그 dict를 보관."""
        self.records.append(fields)
