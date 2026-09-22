"""`/v1/admin/*` 가드 감사기의 **변별력** 동결 (ADMIN-04 acceptance ②).

왜 결함 주입이 필수인가
---------------------
ADMIN-04 시점에 `/v1/admin/*` 라우트는 `GET /v1/admin/menu` **1건뿐이고 그것은 면제 대상**이다.
그러므로 실제 앱에 대고 감사기를 돌리면 "위반 0"이 나오는데, 그 0은 *가드가 일했다는 뜻이
아니라 검사할 대상이 없었다는 뜻*이다. 정상 입력에서 초록인 것은 보호의 증거가 아니다 —
모든 입력에서 초록인 감사기도 같은 화면을 낸다(CLAUDE.md 2026-09-01 "보호 장치를 실패 주입
없이 '보호 있음'으로 선언 금지").

그래서 여기서는 **감사기가 막으려는 상태를 실제로 주입해 RED를 확인한다**. ADMIN-05가 실
데이터 라우트를 붙이면 그때부터는 실제 모집단도 커지지만, 이 파일의 주입은 그와 무관하게
계속 감사기 자신을 지킨다.

주입 목록 (각 항목 옆이 그것이 없으면 통과해 버리는 실패 모드)
-----------------------------------------------------------
M1 가드 없는 admin 라우트            → "메뉴엔 없는데 URL로는 됨"
M2 `require_role`을 직접 쓴 라우트    → **역할값은 맞는데 파생 경로가 아님**(드리프트의 씨앗)
M3 미등재 module_id로 태그된 가드      → 지워진 모듈을 가리키는 좀비 가드
M4 면제 경로가 앱에서 사라짐           → 낡은 면제(검토됐다는 인상만 남는다)
M5 `include_router`로 붙인 라우트      → FastAPI 0.140 lazy-include 함정. 감사기가 `app.routes`를
                                       순진하게 훑으면 **admin 라우트가 0건으로 보여** 모든
                                       위반이 사라진다(측정 실패가 통과로 위장)

대조군(무차별 실패가 아님을 보인다)
--------------------------------
C1 정상 파생 가드를 쓴 admin 라우트 → 위반 0
C2 가드 없는 **비**-admin 라우트     → 감사 대상 아님(위반 0) — 접두 판정이 과잉 확장되지 않는다
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, FastAPI

from whymath_backend.api._auth import UserProfile, require_role
from whymath_backend.api.admin_module_registry import (
    GUARD_EXEMPT_PATHS,
    GUARD_MODULE_ATTR,
    all_modules,
    require_module_roles,
)
from whymath_backend.app import create_app
from whymath_backend.ops.admin_guard_audit import (
    audit_admin_route_guards,
    stale_guard_exemptions,
)
from whymath_backend.schema.enums import Role

_SOME_MODULE_ID = all_modules()[0].id


def _app_with(router: APIRouter) -> FastAPI:
    """`include_router` 경유로 붙인다 — M5(lazy-include 함정)를 상시 재현하기 위해서다."""
    app = FastAPI()
    app.include_router(router)
    return app


# ── 실제 앱 ─────────────────────────────────────────────────────────────────────────


def test_real_app_has_no_guard_violations_and_a_non_zero_denominator() -> None:
    """실제 앱은 위반 0이되, **검사한 라우트 수가 0이 아님**을 함께 단언한다.

    분모를 같이 보지 않으면 이 테스트는 "admin 라우트가 통째로 사라진" 상태에서도 통과한다.
    """
    violations, scanned = audit_admin_route_guards(create_app())
    assert scanned >= 1, "admin 라우트를 한 건도 못 찾았다 — 위반 0이 아니라 측정 실패다"
    assert violations == [], violations


def test_real_app_has_no_stale_guard_exemptions() -> None:
    """면제 목록의 경로가 전부 앱에 실재한다."""
    assert stale_guard_exemptions(create_app()) == []


def test_exempt_paths_are_actually_served() -> None:
    """면제로 적힌 경로가 실제 서빙 표면에 있다 — 없는 것을 면제해 두면 사각이다."""
    _, scanned = audit_admin_route_guards(create_app())
    assert scanned >= len(GUARD_EXEMPT_PATHS)


# ── 대조군 ──────────────────────────────────────────────────────────────────────────


def test_c1_registry_derived_guard_passes() -> None:
    """C1: 정상 파생 가드는 위반을 내지 않는다(무차별 실패가 아님)."""
    router = APIRouter(prefix="/v1/admin", tags=["admin"])

    @router.get("/probe", dependencies=[Depends(require_module_roles(_SOME_MODULE_ID))])
    async def _probe() -> dict[str, str]:
        return {}

    violations, scanned = audit_admin_route_guards(_app_with(router))
    assert scanned == 1
    assert violations == []


def test_c2_non_admin_routes_are_out_of_scope() -> None:
    """C2: admin 접두가 아닌 무가드 라우트는 감사 대상이 아니다."""
    router = APIRouter(prefix="/v1/notadmin")

    @router.get("/probe")
    async def _probe() -> dict[str, str]:
        return {}

    violations, scanned = audit_admin_route_guards(_app_with(router))
    assert (violations, scanned) == ([], 0)


# ── 결함 주입 ───────────────────────────────────────────────────────────────────────


def test_m1_unguarded_admin_route_is_detected() -> None:
    """M1: 가드를 깜빡한 admin 라우트."""
    router = APIRouter(prefix="/v1/admin")

    @router.get("/unguarded")
    async def _probe() -> dict[str, str]:
        return {}

    violations, scanned = audit_admin_route_guards(_app_with(router))
    assert scanned == 1
    assert len(violations) == 1
    assert "/v1/admin/unguarded" in violations[0]
    assert "레지스트리 파생 가드 없음" in violations[0]


def test_m2_raw_require_role_is_detected_even_with_correct_roles() -> None:
    """M2: 역할값은 정확히 맞는데 레지스트리를 안 거친 가드.

    이 주입이 이 파일에서 가장 중요하다 — 감사기가 *역할값*만 비교했다면 여기서 통과해 버리고,
    그러면 레지스트리와 가드가 따로 노는 상태가 다시 열린다(04 §2 원칙7이 막으려는 바로 그것).
    """
    router = APIRouter(prefix="/v1/admin")

    @router.get("/raw-guard", dependencies=[Depends(require_role(Role.CONTENT_ADMIN))])
    async def _probe() -> dict[str, str]:
        return {}

    violations, scanned = audit_admin_route_guards(_app_with(router))
    assert scanned == 1
    assert len(violations) == 1
    assert "레지스트리 파생 가드 없음" in violations[0]


def test_m3_guard_tagged_with_unregistered_module_is_detected() -> None:
    """M3: 레지스트리에서 지워진 모듈을 가리키는 좀비 가드."""

    async def _zombie() -> UserProfile | None:
        return None

    setattr(_zombie, GUARD_MODULE_ATTR, "지워진_모듈")

    router = APIRouter(prefix="/v1/admin")

    @router.get("/zombie", dependencies=[Depends(_zombie)])
    async def _probe() -> dict[str, str]:
        return {}

    violations, scanned = audit_admin_route_guards(_app_with(router))
    assert scanned == 1
    assert len(violations) == 1
    assert "미등재 모듈" in violations[0]


def test_m4_exemption_without_a_live_route_is_detected() -> None:
    """M4: 면제 목록에만 남고 앱에는 없는 경로."""
    empty = FastAPI()
    assert stale_guard_exemptions(empty) == sorted(GUARD_EXEMPT_PATHS)


def test_m5_included_router_routes_are_actually_walked() -> None:
    """M5: FastAPI 0.140 lazy-include 언랩이 살아 있는가.

    `app.routes`를 순진하게 훑는 구현으로 되돌리면 여기서 `scanned == 0`이 되어 RED다.
    분모가 0으로 접히면 M1~M3 주입이 **전부 조용히 통과**하므로, 이 검사가 그 셋의 전제다.
    """
    router = APIRouter(prefix="/v1/admin")

    @router.get("/a")
    async def _a() -> dict[str, str]:
        return {}

    @router.get("/b")
    async def _b() -> dict[str, str]:
        return {}

    _, scanned = audit_admin_route_guards(_app_with(router))
    assert scanned == 2, "include_router 하위 라우트를 못 봤다 — lazy-include 언랩이 깨졌다"
