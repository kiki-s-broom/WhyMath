"""모델 상태 수집 — `GET /status`와 `GET /v1/admin/models`의 **단일 진실 원천**.

왜 분리했는가
------------
두 엔드포인트가 같은 것(로컬 Ollama 도달성·모델 매트릭스·클라우드 구성)을 보고한다. 로직을
양쪽에 복제하면 아래 두 미묘함이 한쪽에서만 유지되다 갈라진다 — 그리고 갈라진 쪽은 *틀린 답을
자신 있게* 낸다:

① **provider가 점검 메서드를 노출하지 않는 경우**(가짜·로컬전용 provider). 로컬은 "도달 불가",
   클라우드는 "미노출(None)"로 각각 다르게 간주해야 한다.
② **클라우드 `reachable`은 공통 표면이 아니다**(ARCH-57). 보고하는 제공자만 자기 Status에 두므로,
   없을 때 `False`로 접으면 "도달 불가"와 "미측정"이 **같은 화면**이 된다 — `None`으로 남겨
   구분을 보존한다.

그래서 수집은 여기 한 곳에서 하고, 각 엔드포인트는 이 결과를 자기 응답 스키마로 *투영*만 한다
(04 §2 원칙1 표현≠의미의 같은 축 — 의미는 하나, 표현은 소비자마다).

7계층: `api` 안의 내부 헬퍼이며 수학 로직이 없다. provider는 `_l3_state`에서 꺼낸다(app.state
주입 — FastAPI 의존성이 아니라 `Request`만 필요).
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from whymath_backend.api._l3_state import get_provider
from whymath_backend.l3.providers.ollama import OllamaStatus


@dataclass(frozen=True, slots=True)
class ModelStatusSnapshot:
    """한 시점의 모델 상태. 클라우드 3필드는 **미측정을 `None`으로** 구분해 보존한다."""

    local: OllamaStatus
    cloud_configured: bool | None
    cloud_reachable: bool | None
    cloud_error: str | None


async def collect_model_status(request: Request) -> ModelStatusSnapshot:
    """provider를 점검해 스냅샷을 만든다. **예외를 던지지 않는다** — 죽어 있어도 상태로 보고한다.

    Ollama·클라우드가 내려가 있을 때 500을 내면 운영자가 "서버가 죽었다"와 "모델이 없다"를
    구분할 수 없다. 그래서 도달 실패는 에러가 아니라 필드다.
    """
    provider = get_provider(request)

    check = getattr(provider, "check_status", None)
    if check is None:
        local = OllamaStatus(reachable=False, models=(), error="provider has no status check")
    else:
        local = await check()

    cloud_configured: bool | None = None
    cloud_reachable: bool | None = None
    cloud_error: str | None = None
    cloud_check = getattr(provider, "check_cloud_status", None)
    if cloud_check is not None:
        cloud_status = await cloud_check()
        if cloud_status is not None:
            cloud_configured = cloud_status.configured
            cloud_error = cloud_status.error
            # ARCH-57 — 모듈 docstring ② 참조. 없으면 False가 아니라 None이다.
            cloud_reachable = getattr(cloud_status, "reachable", None)

    return ModelStatusSnapshot(
        local=local,
        cloud_configured=cloud_configured,
        cloud_reachable=cloud_reachable,
        cloud_error=cloud_error,
    )
