"""클라우드 좌석 상태 보고의 **공통 표면** — 구조적 프로토콜 (ARCH-57).

`CompositeProvider.check_cloud_status()`는 종전에 `AnthropicStatus`를 반환 타입으로 박고
있었다. 클라우드 좌석이 셀렉터(`settings.cloud_provider`)로 바뀔 수 있게 되면서 그 자리에
`OpenRouterStatus`도 오게 됐고, 두 타입은 **구조가 다르다**:

    AnthropicStatus : configured · reachable · error
    OpenRouterStatus: configured · allowed_providers · jurisdiction · error

`reachable`이 없는 것은 누락이 아니라 판단이다 — OpenRouter의 조회 엔드포인트는 라우팅
계약(모델·공급사 고정·fallback 금지 세 파라미터)을 거치지 않으므로, 거기 닿은 것을
"reachable"로 보고하면 *우리가 실제로 쓰는 경로가 살아 있다*는 뜻으로 오독된다
(`openrouter.OpenRouterStatus` docstring).

그래서 공통 표면은 **두 필드의 교집합**만 둔다. `reachable`은 프로토콜에 넣지 않고, 읽는
쪽(`app.py`)이 `getattr(status, "reachable", None)`으로 **있으면 싣고 없으면 None**으로
남긴다. None은 "도달 불가"가 아니라 "미측정"이며, 응답 필드가 이미 `bool | None`이라 이
구분이 그대로 보존된다 — 모름을 아님으로 접으면 두 상태가 같은 화면이 된다(CLAUDE.md
「모른다 ≠ 아니다」).

명목 상속(공통 기반 dataclass)이 아니라 구조적 Protocol인 이유: 두 Status는 각자 provider
모듈이 소유하는 dataclass이고, 공통 부모를 두면 provider들이 서로를 알아야 한다(그리고
`providers/` 안에 상속 축이 하나 더 생긴다). 여기서 필요한 것은 "이 두 필드를 가졌는가"뿐이다.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["CloudStatus"]


@runtime_checkable
class CloudStatus(Protocol):
    """클라우드 좌석이 /status에 최소한으로 보고하는 것 — 구성 여부와 오류 사유.

    `configured`=전송 가능한 구성인가(키·허용목록 등). `error`=구성 점검에서 잡힌 사유
    (없으면 None). 도달성(`reachable`)은 **이 표면에 없다** — 보고하는 제공자만 자기 타입에
    두고, 읽는 쪽이 있으면 싣는다(모듈 docstring 참조).
    """

    configured: bool
    error: str | None
