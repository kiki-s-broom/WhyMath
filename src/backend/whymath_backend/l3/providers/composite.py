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

from collections.abc import Mapping, Sequence
from typing import Any, Final, cast, get_args

from whymath_backend.config import CloudSeat
from whymath_backend.l3.interfaces import LLMProvider
from whymath_backend.l3.models import CostTier, GenerationResult, RoutingDecision
from whymath_backend.l3.provider_jurisdiction import (
    Jurisdiction,
    jurisdiction_judgment,
)
from whymath_backend.l3.providers.cloud_status import CloudStatus
from whymath_backend.l3.providers.ollama import OllamaStatus
from whymath_backend.l3.router import _as_cost_tier

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
"""


def no_secondary_seat_note(primary_seat: CloudSeat | None) -> str:
    """클라우드 좌석 실패 예외에 붙이는 정직한 설명 — "2차 좌석 없음"의 **단일 문구 좌석**.

    두 가지를 함께 말한다. ⓐ 다른 클라우드 좌석으로 넘어가지 않았다(2차 좌석 없음) ⓑ LOCAL로도
    자동 재시도되지 않았다 — 이 기간의 LOCAL 강등은 **라우팅 시점**(구독·예산 가드,
    `l3.router.guard_cloud`)에서만 일어난다. ⓑ를 빼면 읽는 사람이 "LOCAL이 대신 받았겠지"로
    오독한다(03c §3.2 설계도는 런타임 LOCAL 강등을 그렸지만 그 경로는 ARCH-63 몫이며 아직 없다).
    """
    seat = primary_seat if primary_seat is not None else "미선언(좌석 미상)"
    return (
        f"[클라우드 좌석] 1차 좌석 {seat} 호출 실패 — 2차 클라우드 좌석 없음(재시도 좌석 0개). "
        "이 요청은 다른 클라우드 좌석으로도, LOCAL로도 자동 재시도되지 않았다(LOCAL 강등은 "
        "라우팅 시점의 구독·예산 가드에서만 일어난다). Anthropic 2차 좌석 = ARCH-63, "
        "G-arch66-anthropic-api-pause-review 재개 판정 뒤."
    )


class CompositeProvider:
    """로컬↔클라우드 디스패처 — interfaces.LLMProvider 충족.

    `generate()`는 decision.cost_tier로 분기한다: LOCAL→local, CLOUD_*→cloud. cloud가
    None(클라우드 미사용 배포)인데 클라우드 결정이 오면 *명확한 오류*를 던진다(조용한
    강등 금지). `check_status()`는 로컬 상태를(/status 로컬 매핑 보존), `check_cloud_status()`
    는 클라우드 상태를 분리 노출한다 — 앱의 기존 /status 로컬 경로를 건드리지 않고
    클라우드 필드만 덧붙이기 위함(저블래스트 반경).
    """

    def __init__(
        self,
        *,
        local: LLMProvider,
        cloud: LLMProvider | None = None,
    ) -> None:
        self._local = local
        self._cloud = cloud

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

        - 클라우드 위임이 **실패**하면 예외를 그대로 다시 던지되(타입·메시지 보존),
          `no_secondary_seat_note()` 문구를 note로 덧붙인다 — 2차 클라우드 좌석이 없고 LOCAL로도
          자동 재시도하지 않았다는 사실(ARCH-64 · 2026-09-28 Kiki 결정).

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
        try:
            return await target.generate(prompt, system, decision, **forward)
        except Exception as exc:
            # 예외를 **바꾸지 않는다**(타입·메시지 보존 — 기존 호출부의 except·match 계약 무변경).
            # 정직한 좌석 사실만 note로 덧붙여 다시 던진다: 2차 좌석이 없어 아무도 대신 받지
            # 않았다는 것. 삼키거나 LOCAL로 조용히 내리지 않는다(CLAUDE.md 「침묵 실패 금지」).
            try:
                seat = self.cloud_seat
            except TypeError:
                seat = None  # 선언 오류가 원래 실패를 가리지 않게 — 좌석만 '미상'으로 적는다
            exc.add_note(no_secondary_seat_note(seat))
            raise

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
