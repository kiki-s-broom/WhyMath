"""L3 외부 의존 인터페이스 — Protocol(미구현) + 테스트용 인메모리 스텁.

범위 메모 (M1.2): 실제 LLM 클라이언트(Ollama/Anthropic)·Redis·Langfuse·비동기
큐는 *연동하지 않는다*. 라우터가 의존하는 *경계*만 `typing.Protocol`로 선언하고,
단위테스트가 라이브 서비스 없이 통과하도록 인메모리 스텁만 제공한다.
실제 구현은 후속 마일스톤(03a §H 후속 4 클라우드 연동·6 큐 SLA).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

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
