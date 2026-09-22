"""`GET /v1/admin/menu` — 좌측 내비를 레지스트리에서 파생시키는 단일 엔드포인트(04 §2 원칙7).

프런트(ADMIN-06)는 앱 로드 시 이 엔드포인트를 **1회** 호출해 트리 전체를 렌더한다 —
하드코딩 nav 배열이 프런트 코드에 없다는 것이 "모든 가능 메뉴 자동 등록"의 구체 구현이다.
섹션 순서·섹션 라벨까지 서버가 주는 이유는 `module_registry.SECTION_ORDER` 주석 참조
(프런트가 순서 배열을 들고 있으면 그것이 곧 하드코딩 nav의 재발이다).

인가(04 §2 원칙7·§4)는 **두 축이 다르게** 걸린다.
  · *역할* 축 — `get_current_user`만 요구한다. 역할이 모자라면 403이 아니라 **빈 메뉴**를 받는다
    (메뉴는 모듈이 아니라 *모듈 목록*이고, 권한 판정은 각 모듈 라우트가 자체 가드로 한다 —
    이중 방어). 그 면제는 `module_registry.GUARD_EXEMPT_PATHS`에 사유와 함께 등재돼 있다.
  · *신원* 축 — **데모 계정은 403**이다(ADMIN-06). 위 면제는 역할 축의 면제일 뿐이고, 04 §4의
    "콘솔은 실 신원 필수"는 면제 대상이 아니다. 백오피스 셸이 앱 로드 시 **가장 먼저** 부르는
    곳이 여기라, 여기가 열려 있으면 데모 토큰으로 콘솔 골격과 모듈 목록까지는 그려진다.

표현 ≠ 의미(04 §2 원칙1): 여기서 나가는 것은 *구조*(섹션·모듈·상태·경로)뿐이며 렌더 방식
(아이콘·색·비활성 표기)은 클라가 정한다. `status`는 화면 문자열이 아니라 3값 enum이다.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from whymath_backend.api._auth import CurrentUser
from whymath_backend.api.admin_module_registry import (
    DEMO_ACCOUNT_DENIED_DETAIL,
    SECTION_LABELS_KO,
    SECTION_ORDER,
    AdminModule,
    AdminModuleStatus,
    AdminSection,
    is_demo_account,
    visible_modules,
)

router = APIRouter(prefix="/v1/admin", tags=["admin"])


class AdminMenuItem(BaseModel):
    """내비 항목 1건 — `AdminModule`의 *노출 투영*이다.

    `required_roles`를 싣지 않는다: 이미 서버가 필터링을 끝냈으므로 클라가 다시 판정할 일이
    없고, 역할 목록은 인가 구조의 노출이라 굳이 내보낼 이유가 없다. `backing_assets`도
    내부 추적성 필드라 뺀다(운영자 화면에 레포 경로를 뿌리지 않는다).
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(..., description="안정 식별자.")
    label_ko: str = Field(..., description="메뉴에 찍히는 라벨.")
    route: str = Field(..., description="Next.js 경로.")
    status: AdminModuleStatus = Field(
        ...,
        description="`planned`는 숨기지 않고 비활성('준비 중')으로 렌더한다.",
    )

    @classmethod
    def from_module(cls, module: AdminModule) -> AdminMenuItem:
        return cls(
            id=module.id,
            label_ko=module.label_ko,
            route=module.route,
            status=module.status,
        )


class AdminMenuSection(BaseModel):
    """섹션 1개와 그 구성원. 구성원이 0건인 섹션은 응답에 포함하지 않는다."""

    model_config = ConfigDict(frozen=True)

    key: AdminSection = Field(..., description="섹션 키.")
    label_ko: str = Field(..., description="섹션 헤더 라벨.")
    items: tuple[AdminMenuItem, ...] = Field(..., description="선언 순서 유지.")


class AdminMenuResponse(BaseModel):
    """`GET /v1/admin/menu` 응답."""

    model_config = ConfigDict(frozen=True)

    sections: tuple[AdminMenuSection, ...] = Field(
        ...,
        description="`SECTION_ORDER` 순서. 권한이 없으면 빈 목록(403 아님).",
    )


@router.get(
    "/menu",
    response_model=AdminMenuResponse,
    summary="관리 콘솔 좌측 내비 — 현재 사용자 권한으로 필터된 모듈 트리",
)
async def get_admin_menu(user: CurrentUser) -> AdminMenuResponse:
    """레지스트리를 권한 필터링해 섹션별로 묶어 돌려준다.

    `visible_modules`가 `PLANNED`를 거르지 않는다는 점이 중요하다 — 존재를 숨기면 운영자가
    "그 기능은 없는 줄 알았다"가 되고, 그것이 곧 04 §2 원칙7이 막으려는 "발견 안 됨"이다.
    """
    if is_demo_account(user):
        # 데모 계정은 **역할과 무관하게** 콘솔 입구에서 막는다(04 §4 "콘솔은 실 신원 필수").
        # 이 경로가 `GUARD_EXEMPT_PATHS`인 것은 *역할* 축의 면제이지 *신원* 축의 면제가 아니다 —
        # 셸(ADMIN-06)이 앱 로드 시 가장 먼저 부르는 곳이 여기라, 여기서 막지 않으면 데모 토큰으로
        # 콘솔 골격과 모듈 목록이 그려진 뒤 개별 모듈에서만 403이 난다(각 모듈 가드는 이미 막는다).
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=DEMO_ACCOUNT_DENIED_DETAIL,
        )
    allowed = visible_modules(user.role)
    by_section: dict[AdminSection, list[AdminMenuItem]] = {}
    for module in allowed:
        by_section.setdefault(module.section, []).append(AdminMenuItem.from_module(module))

    sections = tuple(
        AdminMenuSection(
            key=key,
            label_ko=SECTION_LABELS_KO[key],
            items=tuple(by_section[key]),
        )
        for key in SECTION_ORDER
        if key in by_section
    )
    return AdminMenuResponse(sections=sections)
