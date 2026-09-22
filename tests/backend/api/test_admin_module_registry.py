"""관리 모듈 레지스트리 불변식 동결 (ADMIN-04 · 04 §2 원칙7).

레지스트리는 좌측 내비와 라우트 가드 **양쪽**의 원천이므로, 여기가 조용히 틀리면 메뉴가 틀리는
것으로 끝나지 않고 인가가 틀린다. 그래서 스키마가 막아 주는 것(타입) 말고 **스키마가 못 막는
것**을 여기서 잡는다.

동결 항목
--------
① `required_roles` 빈 집합 금지 — 04 §2 원칙7이 스키마 주석에 명시한 요구.
② id·route 중복 금지 — 중복 id는 가드가 엉뚱한 모듈을 참조하게 하고, 중복 route는 내비에서
   같은 자리를 두 항목이 차지한다.
③ `backing_assets`는 **실재해야 한다** — 추적성 필드가 존재하지 않는 경로를 가리키면 "근거가
   적혀 있다"는 인상만 남고 근거는 없다(낡은 면제와 같은 종류의 위장).
④ `PLANNED`만 자산을 비울 수 있다 — `PLANNED`의 정의가 "자산 없음"이므로 그 역도 성립해야
   한다. 자산이 있는데 `PLANNED`거나, 자산이 없는데 `PARTIAL`/`LIVE`면 상태값이 거짓이다.
⑤ 죽은 섹션 키 금지 — 선언된 섹션 키에 구성원이 하나도 없으면 그 키는 내비에 영원히 안 나온다
   (03 §5 표만 시드로 삼았을 때 `dataset` 섹션이 정확히 그 상태가 된다 — 이 검사가 그것을
   실패로 잡으라고 있다).
⑥ `SECTION_ORDER`·`SECTION_LABELS_KO`가 섹션 enum을 **전건** 덮는다 — 하나라도 빠지면 그
   섹션의 모듈이 메뉴에서 통째로 사라지는데, 200 응답이라 아무도 모른다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from whymath_backend.api.admin_module_registry import (
    GUARD_EXEMPT_PATHS,
    SECTION_LABELS_KO,
    SECTION_ORDER,
    AdminModule,
    AdminModuleStatus,
    AdminSection,
    all_modules,
    get_module,
    has_module,
    require_module_roles,
    visible_modules,
)
from whymath_backend.schema.enums import Role

# 저장소 루트 — 이 파일: tests/backend/api/…  →  parents[3] = repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]

_MODULES = all_modules()


def test_registry_is_not_empty() -> None:
    """전수 검사의 분모가 0이면 아래 검사들이 전부 공허하게 통과한다."""
    assert len(_MODULES) >= 20, f"시드가 {len(_MODULES)}건 — 03 §5 22모듈 시드가 유실됐다"


@pytest.mark.parametrize("module", _MODULES, ids=lambda m: m.id)
def test_required_roles_is_never_empty(module: AdminModule) -> None:
    """① 빈 `required_roles`는 "아무나" 또는 "아무도"로 갈리는 미정의 상태다."""
    assert module.required_roles, f"{module.id}: required_roles 빈 집합"


def test_ids_and_routes_are_unique() -> None:
    """② 중복 id는 가드 오참조를, 중복 route는 내비 자리 충돌을 낳는다."""
    ids = [m.id for m in _MODULES]
    routes = [m.route for m in _MODULES]
    assert len(set(ids)) == len(ids), f"중복 id: {sorted({i for i in ids if ids.count(i) > 1})}"
    assert len(set(routes)) == len(
        routes
    ), f"중복 route: {sorted({r for r in routes if routes.count(r) > 1})}"


@pytest.mark.parametrize("module", _MODULES, ids=lambda m: m.id)
def test_backing_assets_exist_on_disk(module: AdminModule) -> None:
    """③ 추적성 경로는 실재해야 한다 — 없으면 근거가 아니라 인상이다."""
    for asset in module.backing_assets:
        assert (_REPO_ROOT / asset).exists(), f"{module.id}: 자산 경로 부재 {asset!r}"


@pytest.mark.parametrize("module", _MODULES, ids=lambda m: m.id)
def test_status_agrees_with_asset_presence(module: AdminModule) -> None:
    """④ `PLANNED`(자산 없음) ↔ `backing_assets` 공백이 서로의 동치여야 한다."""
    is_planned = module.status is AdminModuleStatus.PLANNED
    assert is_planned == (
        not module.backing_assets
    ), f"{module.id}: status={module.status.value}인데 자산 {len(module.backing_assets)}건"


def test_no_dead_section_keys() -> None:
    """⑤ 구성원 0건인 섹션 키 금지(모듈 docstring 참조)."""
    populated = {m.section for m in _MODULES}
    dead = sorted(s.value for s in AdminSection if s not in populated)
    assert not dead, f"구성원 0건 섹션: {dead}"


def test_section_order_and_labels_cover_every_section() -> None:
    """⑥ 순서·라벨 표가 섹션 enum을 전건 덮는다 — 누락은 메뉴에서 조용한 실종이다."""
    assert set(SECTION_ORDER) == set(AdminSection)
    assert len(SECTION_ORDER) == len(AdminSection), "SECTION_ORDER에 중복이 있다"
    assert set(SECTION_LABELS_KO) == set(AdminSection)
    assert all(label for label in SECTION_LABELS_KO.values())


def test_routes_live_under_admin_prefix() -> None:
    """내비 경로는 전부 `/admin`(Next.js) 아래다 — 콘솔 밖으로 새는 링크 금지."""
    for module in _MODULES:
        assert module.route == "/admin" or module.route.startswith(
            "/admin/"
        ), f"{module.id}: route {module.route!r}"


def test_status_vocabulary_is_exactly_three_values() -> None:
    """acceptance ①의 "status 3값" — 어휘가 늘면 프런트의 렌더 분기가 조용히 새 값을 만난다."""
    assert {s.value for s in AdminModuleStatus} == {"live", "partial", "planned"}


def test_modules_are_immutable() -> None:
    """엔트리는 전역 상수다 — 한 요청의 필터링이 다음 요청의 권한을 바꿀 수 없어야 한다."""
    with pytest.raises(ValidationError):
        _MODULES[0].label_ko = "변조"  # type: ignore[misc]


def test_visible_modules_filters_by_role_and_keeps_planned() -> None:
    """권한으로만 거르고 `status`로는 거르지 않는다(04 §2 원칙7)."""
    admin_view = visible_modules(Role.CONTENT_ADMIN)
    assert set(admin_view) == set(_MODULES)
    assert any(m.status is AdminModuleStatus.PLANNED for m in admin_view)
    assert visible_modules(Role.STUDENT) == ()


def test_lookup_helpers_agree() -> None:
    """`get_module`(기동 시점·예외)과 `has_module`(감사용·불리언)이 같은 집합을 본다."""
    for module in _MODULES:
        assert has_module(module.id)
        assert get_module(module.id) is module
    assert not has_module("존재하지_않는_모듈")
    with pytest.raises(KeyError):
        get_module("존재하지_않는_모듈")


def test_guard_factory_rejects_unknown_module_at_import_time() -> None:
    """오타 난 module_id는 서버가 **기동조차 못 하게** 한다 — 조용한 무인가 노출보다 낫다."""
    with pytest.raises(KeyError):
        require_module_roles("오타난_모듈_id")


def test_guard_exemptions_carry_non_empty_reasons() -> None:
    """면제는 사유가 있어야 면제다 — 빈 사유는 무명 구멍이다(CLAUDE.md 허용 목록 규약).

    면제 *경로가 앱에 실재하는가*는 `tests/backend/ops/test_admin_guard_audit.py`가 본다
    (여기서는 앱을 만들지 않는다).
    """
    assert GUARD_EXEMPT_PATHS, "면제 목록이 비었다 — menu 경로 면제가 사라졌다"
    for path, reason in GUARD_EXEMPT_PATHS.items():
        assert path.startswith("/v1/admin/"), f"면제 경로가 admin 표면 밖: {path!r}"
        assert len(reason.strip()) >= 30, f"{path}: 사유가 사유의 모양이 아니다"
