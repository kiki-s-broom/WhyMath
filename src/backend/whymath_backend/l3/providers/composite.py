"""복합 LLM 제공자 — cost_tier로 로컬↔클라우드 디스패치 (M1.2-live S5).

라우터 결정의 축1(CostTier)을 보고 LOCAL→로컬 제공자(Ollama), CLOUD_*→클라우드
제공자(Anthropic)로 *디스패치*한다. interfaces.LLMProvider를 충족하므로 파이프라인·
앱의 `generate(provider=...)` 시그니처를 바꾸지 않고 단일 provider로 두 경로를 모두
태운다(provider-map 방식보다 변경 폭이 작다).

설계 정본: `docs/architecture/03a_l3_router_design.md` §A.0·§C.1·§C.4(클라우드는
mode="sync"). 클라우드 결정은 항상 동기라 비동기 큐(Celery)를 거치지 않는다 → 큐 워커는
로컬(QUALITY) 전용이며 이 디스패처를 알 필요가 없다.

큐 메모 (03a §C.4·§D.3): QUALITY(27b, mode="async")만 큐로 가고, 클라우드는 mode="sync"
라 동기 경로에서 이 디스패처를 탄다. 따라서 비동기 워커는 클라우드를 보지 않는다.

관할 게이트 (ARCH-49) — 디스패치 **직전**에 선다
-----------------------------------------------
클라우드 슬롯에 어떤 프로바이더가 앉느냐에 따라 같은 `CLOUD_MID` 결정이 미국 법인으로도
중국 법인으로도 나간다. 그래서 "이 결정의 자료 등급을 *저* 프로바이더의 관할로 보내도
되는가"를 위임 직전에 묻는다(`l3.provider_jurisdiction`).

**왜 provider 안이 아니라 여기인가**: provider가 자기 자신을 검열하면, provider를 직접
쥐고 부르는 경로(D1 위반)가 게이트까지 함께 우회한다. 디스패처에 두면 라우터→디스패처
경로를 타는 모든 호출이 통과해야 하고, 직접 호출은 `check_provider_seat_contract.py`
(ARCH-46)가 따로 막는다 — 두 게이트가 서로의 사각을 덮는다.

**기존 경로 무변경**: 관할이 1차 법적 게이트보다 좁지 않으면(US·국내) 이 게이트는 아무
판정도 추가하지 않는다(`narrows_beyond_export_gate` False). 현행 Anthropic 클라우드 경로는
그래서 종전과 바이트 단위로 같은 요청을 보낸다. 좁히는 관할(CN·국적 미확인 OpenRouter
공급사)에서만 발동하며, 그때는 `decision.data_licenses` 선언이 **없으면 차단**이다.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any, Final, Literal, cast, get_args

from whymath_backend.config import CloudSeat
from whymath_backend.l3.interfaces import LLMProvider
from whymath_backend.l3.models import CostTier, GenerationResult, LocalDegrade, RoutingDecision
from whymath_backend.l3.provider_jurisdiction import (
    Jurisdiction,
    jurisdiction_judgment,
)
from whymath_backend.l3.providers.cloud_status import CloudStatus
from whymath_backend.l3.providers.ollama import OllamaStatus
from whymath_backend.l3.providers.seat_failure import (
    LocalDegradeCounter,
    LocalDegradeSnapshot,
    classify_seat_failure,
)
from whymath_backend.l3.router import _as_cost_tier, local_degrade_decision

_LOGGER = logging.getLogger("whymath.l3.composite")

DEFAULT_CLOUD_JURISDICTION = Jurisdiction.US
"""관할을 선언하지 않은 클라우드 프로바이더의 기본값 — 역사적 좌석(Anthropic)이 미국 법인이다.

이 기본값은 *넓은* 쪽이라 그것만으로는 fail-closed가 아니다. 그래서 프로덕션 프로바이더가
관할 선언을 빠뜨리지 못하게 **기계로 강제**한다:
`tests/infra/test_provider_jurisdiction_declaration.py`가 `l3/providers/`의 실제 제공자
클래스마다 `jurisdiction` 선언을 AST로 전수 확인한다. 즉 이 기본값이 실제로 쓰이는 대상은
테스트 가짜뿐이고, 새 프로바이더가 선언을 잊으면 CI가 적색이다.
"""


CLOUD_FAILOVER_SEAT: Final[None] = None
"""2차 클라우드 좌석 — **없다** (2026-09-28 Kiki 결정 · ARCH-66 기간 처분).

1차 좌석(기본 openrouter)이 실패해도 다른 클라우드 좌석으로 넘어가지 않는다. Anthropic 2차
좌석 failover는 `ARCH-63`이 추가하며, 그 태스크는 게이트 `G-arch66-anthropic-api-pause-review`
(Anthropic API 재개 판정)에 묶여 있다. 이 값을 문자열로 바꾸는 것은 failover 배선 없이
"2차 좌석 있음"을 선언하는 위장이므로, 바꾸려면 ARCH-63이 실제 재시도 경로와 함께 바꾼다
(`tests/backend/l3/test_cloud_mid_seat_cutover.py`가 None을 동결한다).

이것은 **다른 클라우드 좌석**의 부재다. LOCAL 강등(ARCH-69)은 별개 축이며 학생 대면 서빙 조립에
서만 켜진다(`CompositeProvider(runtime_local_degrade=True)` — `app.py`) — 2차 좌석이 없다는 말이
"1차 실패가 LOCAL로도 안 간다"는 뜻이 아니다.
"""


LocalDegradeOutcome = Literal["not_armed", "not_eligible", "local_failed"]
"""예외 note가 말하는 "LOCAL로 넘어갔는가"의 세 상태(강등이 성공한 호출은 예외가 없으므로 없다).

  - `not_armed`    — 이 조립에는 런타임 LOCAL 강등이 없다(저작·측정 경로). 어떤 실패도 LOCAL로
                     가지 않는다.
  - `not_eligible` — 강등이 장착돼 있으나 이 실패는 강등 대상이 아니다(4xx 요청·인증·계약 오류 등).
  - `local_failed` — 강등 경로를 탔으나 LOCAL도 실패했다. 원 클라우드 예외가 올라간다.
"""


def no_secondary_seat_note(
    primary_seat: CloudSeat | None,
    *,
    local_degrade: LocalDegradeOutcome = "not_armed",
    reason: str | None = None,
    failure_type: str | None = None,
    local_error: BaseException | None = None,
) -> str:
    """클라우드 좌석 실패 예외에 붙이는 정직한 설명 — 문구의 **단일 좌석**.

    두 가지를 함께 말한다. ⓐ 다른 클라우드 좌석으로 넘어가지 않았다(2차 좌석 없음 — 항상 참)
    ⓑ LOCAL로 갔는가 — `local_degrade`의 세 상태 중 하나. ⓑ를 뭉개면 읽는 사람이 "LOCAL이 대신
    받았겠지"(강등이 없는 저작 경로에서)나 "LOCAL로도 안 갔겠지"(강등이 있는 서빙 경로에서)로
    오독한다. ARCH-64는 ⓑ를 "항상 안 갔다"로 적었으나 ARCH-69가 서빙 조립에 강등을 붙이면서 그
    문장이 조립마다 갈리게 됐다.
    """
    seat = primary_seat if primary_seat is not None else "미선언(좌석 미상)"
    head = f"[클라우드 좌석] 1차 좌석 {seat} 호출 실패 — 2차 클라우드 좌석 없음(재시도 좌석 0개). "
    tail = " Anthropic 2차 좌석 = ARCH-63, G-arch66-anthropic-api-pause-review 재개 판정 뒤."
    if local_degrade == "not_armed":
        middle = (
            "이 조립은 런타임 LOCAL 강등이 장착되지 않아(저작·측정 경로) 실패가 LOCAL로도 "
            "재시도되지 않았다 — 학생 대면 서빙 조립만 강등이 켜져 있다(ARCH-69)."
        )
    elif local_degrade == "not_eligible":
        kind = f"({failure_type}) " if failure_type else ""
        middle = (
            f"런타임 LOCAL 강등은 429·5xx·타임아웃·미설정 실패에만 걸린다 — 이 실패{kind}는 강등 "
            "대상이 아니라(요청·인증·계약 오류 등) LOCAL로 재시도되지 않았다. 같은 실패가 반복될 "
            "뿐이고 LOCAL 응답이 원인을 가리기 때문이다."
        )
    else:
        local_kind = type(local_error).__name__ if local_error is not None else "미상"
        local_msg = str(local_error)[:200] if local_error is not None else ""
        middle = (
            f"런타임 LOCAL 강등(사유 {reason})을 시도했으나 LOCAL도 실패했다"
            f"({local_kind}: {local_msg}) — 원래의 클라우드 예외를 그대로 올린다."
        )
    return head + middle + tail


class CompositeProvider:
    """로컬↔클라우드 디스패처 — interfaces.LLMProvider 충족.

    `generate()`는 decision.cost_tier로 분기한다: LOCAL→local, CLOUD_*→cloud. cloud가
    None(클라우드 미사용 배포)인데 클라우드 결정이 오면 *명확한 오류*를 던진다(조용한
    강등 금지). `check_status()`는 로컬 상태를(/status 로컬 매핑 보존), `check_cloud_status()`
    는 클라우드 상태를 분리 노출한다 — 앱의 기존 /status 로컬 경로를 건드리지 않고
    클라우드 필드만 덧붙이기 위함(저블래스트 반경).

    **런타임 LOCAL 강등(ARCH-69)은 opt-in이다**(`runtime_local_degrade`, 기본 False). 켜면 1차
    클라우드 좌석 호출이 429·5xx·타임아웃·미설정으로 실패했을 때 LOCAL로 1회 강등한다. 기본값을
    False로 두는 이유: 저작 경로(동등문제·풀이 생성 등)는 "명확한 실패"가 옳고(사람이 본다), 좌석
    정확도를 재는 측정 하네스는 LOCAL 응답이 클라우드 좌석의 응답으로 **기록되면** 측정이 무효가
    된다. 강등은 실패가 학생 화면의 오류가 되는 학생 대면 서빙에서만 옳다 — `app.py`만 켠다(AST로
    동결).
    """

    def __init__(
        self,
        *,
        local: LLMProvider,
        cloud: LLMProvider | None = None,
        runtime_local_degrade: bool = False,
    ) -> None:
        self._local = local
        self._cloud = cloud
        self._runtime_local_degrade = runtime_local_degrade
        self._degrade_counter = LocalDegradeCounter()

    # ── 좌석 관측 (ARCH-64) ─────────────────────────────────────────────
    @property
    def cloud_seat(self) -> CloudSeat | None:
        """클라우드 슬롯에 **실제로 꽂힌** 좌석 이름 — 없거나 선언하지 않았으면 None(미상).

        설정(`cloud_provider`)을 다시 읽지 않고 꽂힌 객체의 선언(`seat`)을 읽는다. 설정을 읽으면
        "셀렉터는 openrouter인데 누군가 다른 제공자를 주입한" 조립에서 기록이 거짓이 된다 —
        ARCH-58이 상환한 사고의 형태다. 미상은 anthropic으로 접지 않고 None으로 둔다
        (호출부가 원가를 '미측정'으로 남긴다 — CLAUDE.md 「모른다 ≠ 아니다」).
        """
        if self._cloud is None:
            return None
        declared = getattr(self._cloud, "seat", None)
        if declared is None:
            return None
        if declared not in get_args(CloudSeat):
            # 오타·새 좌석을 기본 좌석으로 반올림하지 않는다(`cloud_jurisdiction`과 같은 규율).
            raise TypeError(
                f"클라우드 제공자의 seat 선언은 CloudSeat 값이어야 한다(받은 {declared!r}) — "
                "config.CloudSeat에 좌석을 추가하고 단가표·팩토리를 함께 고쳐라."
            )
        return cast(CloudSeat, declared)

    @property
    def cloud_failover_seat(self) -> None:
        """2차 클라우드 좌석 — 이 기간에는 항상 None(`CLOUD_FAILOVER_SEAT` 참조)."""
        return CLOUD_FAILOVER_SEAT

    @property
    def local_degrade_armed(self) -> bool:
        """런타임 LOCAL 강등이 장착돼 있는가 — 학생 대면 서빙 조립만 True(ARCH-69)."""
        return self._runtime_local_degrade

    def local_degrade_snapshot(self) -> LocalDegradeSnapshot:
        """강등 계수의 현재 사본 — `/status`·회차 관측이 같은 객체를 읽는다.

        `armed=False`면 계수가 0이어도 `rate`는 None이다(강등할 수 없는 구성이 "강등 0회"로
        읽히지 않게). 이 프로세스의 값이다 — 워커가 여럿이면 각자의 값이고 재시작하면 0이다.
        """
        return self._degrade_counter.snapshot(armed=self._runtime_local_degrade)

    def _seat_or_none(self) -> CloudSeat | None:
        """좌석 선언 — 선언 오류가 원래 실패를 가리지 않게 오류는 '미상'(None)으로만 적는다."""
        try:
            return self.cloud_seat
        except TypeError:
            return None

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
        """cost_tier로 로컬↔클라우드 디스패치 (LLMProvider 구현).

        - LOCAL → 로컬 제공자(Ollama)에 위임.
        - CLOUD_MID/CLOUD_HIGH → 클라우드 제공자(Anthropic)에 위임. cloud가 None이면
          명확한 RuntimeError(클라우드 결정이 왔으나 제공자 미구성 — 조용한 강등 금지).
        - `images`(멀티모달)는 위임받는 제공자로 그대로 전달한다(비전은 LOCAL Qwen3-VL이
          처리·클라우드 제공자는 images를 받으면 거부).
        - `temperature`(S2-g 생성 다양성)도 위임받는 제공자로 그대로 전달한다(온도 처리는 각
          하위 제공자 책임 — Ollama options·Anthropic API 인자).
        - `top_p`(EOS-121 선결조건 A)도 그대로 전달한다 — 전달 좌석은 temperature와 같다. 이
          디스패처는 top_p를 **삼키지 않는다**: 삼키면 "양 좌석에 같은 값을 줬다"고 믿는 측정이
          실제로는 아무 값도 안 보낸 상태가 되어, 교란 변수를 닫았다고 *거짓말하는* 회차가 된다.
        - `json_schema`(S2-j structured output)도 그대로 전달한다(제약 처리·거부는 각 하위
          제공자 책임 — Ollama format= 제약 디코딩·Anthropic 명확한 거부).
        - `seed`(EOS-73 생성 재현)도 그대로 전달한다(전달·거부는 각 하위 제공자 책임 — Ollama
          options.seed·Anthropic 명확한 거부). 이 디스패처는 seed를 **삼키지 않는다** — 삼키면
          클라우드 경로에서 "요청했는데 조용히 무시됨"이 되어 거짓 재현 기록의 문이 열린다.

        - 클라우드 위임이 **실패**하면 두 갈래다(ARCH-64·ARCH-69):
          ⓐ **강등 미장착**(기본) 또는 **강등 대상이 아닌 실패**(4xx 요청·인증·계약 오류 등) —
            예외를 그대로 다시 던지되(타입·메시지 보존) `no_secondary_seat_note()`를 note로
            덧붙인다. 2차 클라우드 좌석이 없다는 사실(2026-09-28 Kiki 결정)은 어느 경우에나 참이다.
          ⓑ **강등 장착 + 강등 대상 실패**(429·5xx·타임아웃·미설정 — `classify_seat_failure`) —
            LOCAL 제공자로 **1회** 강등한다. LOCAL이 답하면 그 결과에 `local_degrade`(사유·원 좌석·
            답한 LOCAL 결정)를 붙여 돌려준다 — 결정과 응답의 어긋남을 호출자가 볼 수 있게. LOCAL도
            실패하면 **원래의 클라우드 예외**를 올리고 LOCAL 실패를 note에 남긴다(삼키지 않는다).
          강등된 응답은 파이프라인의 검증·관측을 **똑같이** 탄다 — 강등은 이 메서드 안에서 끝나고
          호출자는 다른 응답과 같은 `GenerationResult`를 받는다.

        반환은 위임받은 제공자의 `GenerationResult(text, usage)` *그대로*다(전파) — text는
        검증 전 원시 출력(각 제공자 docstring 경계 메모), usage는 하위 제공자가 포착한 실측.
        """
        cost = _as_cost_tier(decision.cost_tier)
        # 선택 인자(images·temperature·top_p·json_schema·seed)는 *있을 때만* 싣는다 — 해당
        # 인자 미지원 하위 제공자(기존 구현·가짜)는 인자 없이도 동작(하위호환). 전부 None이면
        # 종전과 동일하게 `target.generate(prompt, system, decision)`로 호출된다.
        target = self._local if cost is CostTier.LOCAL else self._cloud
        if cost is not CostTier.LOCAL and target is None:
            raise RuntimeError(
                f"클라우드 결정({cost.value})이 내려졌으나 클라우드 제공자가 미구성입니다 "
                "(CompositeProvider(cloud=None)). 클라우드 라우팅을 쓰려면 cloud= 제공자를 "
                "주입하세요(03a §H 후속 4)."
            )
        assert target is not None  # 위 가드로 보장(LOCAL은 항상 _local·CLOUD는 None 차단)
        if cost is not CostTier.LOCAL:
            self._guard_cloud_jurisdiction(target, decision)
        forward: dict[str, Any] = {}
        if images is not None:
            forward["images"] = images
        if temperature is not None:
            forward["temperature"] = temperature
        if top_p is not None:
            forward["top_p"] = top_p
        if json_schema is not None:
            forward["json_schema"] = json_schema
        if seed is not None:
            forward["seed"] = seed
        if cost is CostTier.LOCAL:
            return await target.generate(prompt, system, decision, **forward)
        armed = self._runtime_local_degrade
        if armed:
            # 분모(seat_local_degrade_rate) — 디스패치 **직전**에 센다. 관할 게이트 차단·클라우드
            # 미구성 오류는 디스패치가 아니므로 위에서 이미 raise돼 여기까지 오지 않는다.
            self._degrade_counter.record_cloud_attempt()
        started = time.monotonic()
        try:
            return await target.generate(prompt, system, decision, **forward)
        except Exception as exc:
            cloud_attempt_ms = (time.monotonic() - started) * 1000.0
            seat = self._seat_or_none()
            # 강등 여부는 **타입으로** 정한다(`classify_seat_failure`) — 메시지를 읽지 않는다.
            reason = classify_seat_failure(exc) if armed else None
            if reason is None:
                # 예외를 **바꾸지 않는다**(타입·메시지 보존 — 기존 except·match 계약 무변경).
                # 정직한 사실만 note로 덧붙여 다시 던진다: 다른 좌석도 LOCAL도 대신 받지 않았다.
                exc.add_note(
                    no_secondary_seat_note(
                        seat,
                        local_degrade="not_armed" if not armed else "not_eligible",
                        failure_type=type(exc).__name__,
                    )
                )
                raise
            # ── 런타임 LOCAL 강등(ARCH-69) — 1회, 재귀 없음 ──
            local_decision = local_degrade_decision(decision)
            _LOGGER.warning(
                "클라우드 좌석 실패 → LOCAL 강등 (seat=%s, reason=%s, cloud_error=%s, to=%s)",
                seat,
                reason,
                type(exc).__name__,
                local_decision.reason,
            )
            local_result: GenerationResult | None = None
            local_failure: Exception | None = None
            try:
                local_result = await self._local.generate(prompt, system, local_decision, **forward)
            except Exception as local_exc:  # noqa: BLE001 — 아래에서 원 예외와 함께 반드시 드러낸다
                local_failure = local_exc
            self._degrade_counter.record_degrade(reason)
            if local_result is None:
                # LOCAL도 실패 — **원래의 클라우드 예외**를 올린다(LOCAL 예외가 원인을 덮지 않게).
                # inner except 블록 밖의 bare `raise`라 원 예외의 __context__가 오염되지 않는다.
                self._degrade_counter.record_degrade_failure()
                _LOGGER.warning(
                    "LOCAL 강등도 실패 — 원 클라우드 예외를 올린다 (reason=%s, cloud_error=%s, "
                    "local_error=%s)",
                    reason,
                    type(exc).__name__,
                    type(local_failure).__name__,
                )
                exc.add_note(
                    no_secondary_seat_note(
                        seat,
                        local_degrade="local_failed",
                        reason=reason,
                        local_error=local_failure,
                    )
                )
                raise
            return replace(
                local_result,
                local_degrade=LocalDegrade(
                    reason=reason,
                    from_seat=seat,
                    cloud_error_type=type(exc).__name__,
                    served_decision=local_decision,
                    cloud_attempt_ms=cloud_attempt_ms,
                ),
            )

    # ── 관할 게이트 (ARCH-49) ────────────────────────────────────────────
    @staticmethod
    def cloud_jurisdiction(provider: object) -> Jurisdiction:
        """클라우드 제공자의 관할을 읽는다 — 선언이 없으면 역사적 기본값(US).

        기능 탐지(`getattr`)를 쓰는 이유는 `check_status`와 같다: `LLMProvider` Protocol에
        `jurisdiction`을 넣으면 그 Protocol을 충족하는 **모든** 가짜·스텁이 관할을
        선언해야 하고, 그것은 이 축과 무관한 테스트까지 전부 고치게 만든다. 대신 프로덕션
        제공자가 빠뜨리지 못하게 하는 일은 거버넌스 테스트(AST 전수)가 맡는다
        (`DEFAULT_CLOUD_JURISDICTION` docstring).

        선언값이 `Jurisdiction`이 아니면 **조용히 기본값으로 반올림하지 않고** 오류다 —
        오타 하나가 "아마 US겠지"로 위장되면 관할 축 전체가 무의미해진다.
        """
        declared = getattr(provider, "jurisdiction", None)
        if declared is None:
            return DEFAULT_CLOUD_JURISDICTION
        if not isinstance(declared, Jurisdiction):
            raise TypeError(
                f"클라우드 제공자의 jurisdiction 선언은 Jurisdiction이어야 한다"
                f"(받은 {type(declared)!r}). 문자열·오타를 기본값으로 반올림하지 않는다."
            )
        return declared

    @staticmethod
    def cloud_allows_internal_corpus(provider: object) -> bool:
        """클라우드 제공자의 코퍼스 opt-in 상태 — 선언이 없으면 **False**(fail-closed).

        관할 기본값(US)과 달리 여기는 좁은 쪽이 기본이다: opt-in은 "우리 영업자산을 저
        관할로 보낸다"는 *명시적* 결정이고, 선언하지 않은 제공자가 그 권한을 물려받을
        이유가 없다.
        """
        return bool(getattr(provider, "allow_internal_corpus", False))

    def _guard_cloud_jurisdiction(self, provider: object, decision: RoutingDecision) -> None:
        """클라우드 위임 직전 관할 판정 — 통과하면 조용히 반환, 막히면 명확한 오류.

        `decision.data_licenses`가 판정 입력이다. 라우터를 거친 결정은 요청의 선언 등급을
        그대로 승계하고(`router.route`), 손으로 조립한 결정은 기본값이 빈 튜플이라
        **좁히는 관할에서는 차단**된다 — 그것이 의도한 기본값이다(fail-closed).

        차단은 *조용한 강등*이 아니라 오류다. 라우터가 정당한 이유로 클라우드를 택했는데
        관할이 막는 상황은 **설정 오류**이며(코퍼스 프롬프트를 CN 경로로 보내도록 배선한
        것), 조용히 로컬로 내리면 그 배선 실수가 영원히 드러나지 않는다.
        """
        jurisdiction = self.cloud_jurisdiction(provider)
        judgment = jurisdiction_judgment(
            jurisdiction,
            decision.data_licenses,
            allow_internal_corpus=self.cloud_allows_internal_corpus(provider),
        )
        if judgment.permitted:
            return
        blocking = ", ".join(license_type.value for license_type in judgment.blocking_licenses)
        detail = f" 차단 등급: {blocking}." if blocking else ""
        raise RuntimeError(
            f"관할 게이트가 클라우드 위임을 차단했습니다 "
            f"(관할={jurisdiction.value}, 사유={judgment.reason}).{detail} "
            "이 관할은 라이선스 등급을 추가로 좁히며, 선언이 없는 결정(손으로 조립된 "
            "RoutingDecision)은 차단됩니다 — 라우터를 경유하거나 "
            "RoutingDecision(data_licenses=...)에 등급을 명시하세요 "
            "(l3.provider_jurisdiction)."
        )

    async def check_status(self) -> OllamaStatus:
        """로컬 제공자의 레디니스 보고 — /status 로컬 매핑 보존.

        로컬 제공자가 check_status를 노출하지 않으면(가짜 등) 도달 불가로 보고한다
        (app.py·ollama check_status와 동일한 기능 탐지 패턴).
        """
        check = getattr(self._local, "check_status", None)
        if check is None:
            return OllamaStatus(
                reachable=False, models=(), error="local provider has no status check"
            )
        status: OllamaStatus = await check()
        return status

    async def check_cloud_status(self) -> CloudStatus | None:
        """클라우드 제공자의 구성(·가능하면 도달성) 보고 — /status 클라우드 필드용.

        클라우드 제공자가 없거나(cloud=None) 상태 점검을 노출하지 않으면 None을 돌려준다
        (앱은 None이면 클라우드 필드를 채우지 않는다 → 기존 로컬 전용 응답과 호환).

        **반환 타입이 `AnthropicStatus`가 아닌 이유**(ARCH-57): 클라우드 좌석이 셀렉터로
        바뀔 수 있게 되면서 여기에 `OpenRouterStatus`도 올 수 있는데, 그 타입에는
        `reachable`이 **의도적으로 없다** — OpenRouter의 조회 엔드포인트는 라우팅 계약(세
        파라미터)을 거치지 않아 "닿았다"를 보고하면 *계약을 통과한 경로가 살아 있다*는 뜻으로
        오독되기 때문이다(`openrouter.OpenRouterStatus` docstring). 그래서 공통 표면은
        `configured`·`error` 둘뿐이고, `reachable`은 보고하는 제공자만 싣는다. 읽는 쪽은
        없음을 **False가 아니라 None(미측정)**으로 다룬다 — 모름을 아님으로 접으면 도달
        불가와 미측정이 같은 화면이 된다.
        """
        if self._cloud is None:
            return None
        check = getattr(self._cloud, "check_status", None)
        if check is None:
            return None
        status: CloudStatus = await check()
        return status
