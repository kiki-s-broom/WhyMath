"""`GET /v1/admin/menu` 결선·권한 필터 회귀 (ADMIN-04).

여기서 동결하는 계약은 넷이다.

① **무인증 401** — 메뉴가 `get_current_user`를 요구한다(04 §4 "콘솔은 실 신원 필수").
② **권한 필터는 403이 아니라 빈 메뉴** — 메뉴는 모듈이 아니라 *모듈 목록*이라 04 §2 원칙7이
   `get_current_user`만 요구하도록 못박았다. 학생 토큰으로 부르면 섹션 0개가 나온다.
③ **`planned`를 숨기지 않는다** — 존재를 감추면 "없는 줄 알았다"가 되고 그것이 원칙7이 막으려는
   "발견 안 됨"이다. 비활성 렌더는 클라 몫이고 서버는 상태값을 정직하게 싣는다.
④ **섹션 순서를 서버가 준다** — 프런트가 순서 배열을 들고 있으면 그 자체가 하드코딩 nav의
   재발이다(원칙7).

⑤ **데모 계정은 403** (ADMIN-06) — 04 §4 "콘솔은 실 신원 필수". 이 경로가 모듈 가드에서
   면제된 것은 *역할* 축의 면제일 뿐 *신원* 축의 면제가 아니다. 백오피스 셸이 앱 로드 시
   가장 먼저 부르는 곳이라, 여기가 열려 있으면 데모 토큰으로 콘솔 골격이 그려진다.

①②가 서로의 대조군이다: 같은 엔드포인트가 *인증 없음*에는 401을, *권한 없음*에는 200+빈
목록을 내야 한다. 한쪽만 보면 "전부 막힌다"·"전부 열린다" 양쪽 오구현이 통과한다.
②⑤도 대조군이다: 둘 다 "관리 권한이 아닌 호출"인데 결과가 갈려야 한다(빈 메뉴 vs 403).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from whymath_backend.api._auth import get_current_user
from whymath_backend.api.admin_module_registry import (
    SECTION_ORDER,
    AdminModuleStatus,
    all_modules,
    visible_modules,
)
from whymath_backend.api.auth import email_hash
from whymath_backend.api.demo_auth import DEMO_EMAIL
from whymath_backend.app import create_app
from whymath_backend.db.models.user import UserProfile
from whymath_backend.schema.enums import Role

_ADMIN_USER = UserProfile(user_id=uuid.uuid4(), role=Role.CONTENT_ADMIN)
_STUDENT_USER = UserProfile(user_id=uuid.uuid4(), role=Role.STUDENT)
# 데모 판정은 *계정 동일성*으로 한다(토큰에 발급 출처 표식이 없다 — `is_demo_account` docstring).
# 그래서 픽스처도 역할이 아니라 email_hash로 만든다: **관리 역할을 가진 데모 계정**이라야
# "역할은 되는데 신원이 데모"라는 이 계약의 대상 상태가 된다(역할로 막히면 대조가 무효다).
_DEMO_ADMIN_USER = UserProfile(
    user_id=uuid.uuid4(), role=Role.CONTENT_ADMIN, email_hash=email_hash(DEMO_EMAIL)
)

_MENU_PATH = "/v1/admin/menu"


def _client(user: UserProfile | None) -> TestClient:
    """`user`가 None이면 오버라이드 없이 — 실제 인증 체인이 401을 내는지 본다."""
    app = create_app()
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_unauthenticated_is_401() -> None:
    """토큰 없이 부르면 401 — 메뉴도 비공개 표면이다(04 §4)."""
    with _client(None) as client:
        assert client.get(_MENU_PATH).status_code == 401


def test_content_admin_sees_every_registered_module() -> None:
    """CONTENT_ADMIN은 레지스트리 전건을 본다 — 필터가 과잉 차단하지 않음의 대조군."""
    with _client(_ADMIN_USER) as client:
        response = client.get(_MENU_PATH)
    assert response.status_code == 200
    seen = {item["id"] for section in response.json()["sections"] for item in section["items"]}
    assert seen == {module.id for module in all_modules()}


def test_student_gets_empty_menu_not_403() -> None:
    """권한 없는 사용자는 **403이 아니라 빈 메뉴**를 받는다(계약 ②).

    403으로 바꾸면 역할이 없는 운영자가 콘솔 셸조차 못 그린다 — 그래서 이 구분이 의미가 있다.
    """
    with _client(_STUDENT_USER) as client:
        response = client.get(_MENU_PATH)
    assert response.status_code == 200
    assert response.json()["sections"] == []
    # 필터 자체가 실제로 걸렀는지(=학생에게 열린 모듈이 0건인지) 레지스트리 쪽에서도 확인한다.
    assert visible_modules(Role.STUDENT) == ()


def test_planned_modules_are_present_and_marked() -> None:
    """`planned`도 메뉴에 나온다 — 숨기지 않고 상태값으로 알린다(계약 ③)."""
    planned = {m.id for m in all_modules() if m.status is AdminModuleStatus.PLANNED}
    assert planned, "레지스트리에 planned 엔트리가 하나도 없다 — 이 검사가 공허해진다"

    with _client(_ADMIN_USER) as client:
        payload = client.get(_MENU_PATH).json()
    items = {item["id"]: item for section in payload["sections"] for item in section["items"]}
    assert planned <= set(items)
    for module_id in planned:
        assert items[module_id]["status"] == AdminModuleStatus.PLANNED.value


def test_sections_follow_declared_order_and_are_non_empty() -> None:
    """섹션 순서는 `SECTION_ORDER`를 따르고, 구성원 0건인 섹션은 실리지 않는다(계약 ④)."""
    with _client(_ADMIN_USER) as client:
        sections = client.get(_MENU_PATH).json()["sections"]

    keys = [section["key"] for section in sections]
    expected = [key.value for key in SECTION_ORDER if key in {m.section for m in all_modules()}]
    assert keys == expected
    assert all(section["items"] for section in sections)


def test_response_omits_internal_only_fields() -> None:
    """`required_roles`·`backing_assets`는 응답에 싣지 않는다.

    전자는 서버가 이미 필터를 끝냈으므로 인가 구조를 굳이 내보낼 이유가 없고, 후자는 내부
    추적성 필드다 — 운영자 화면에 레포 경로를 뿌리지 않는다.
    """
    with _client(_ADMIN_USER) as client:
        payload = client.get(_MENU_PATH).json()
    item = payload["sections"][0]["items"][0]
    assert set(item) == {"id", "label_ko", "route", "status"}


@pytest.mark.parametrize("role", list(Role))
def test_every_role_gets_a_well_formed_response(role: Role) -> None:
    """v0 2값 전건에서 응답 스키마가 성립한다 — 역할이 늘어도 이 검사가 먼저 깨진다."""
    with _client(UserProfile(user_id=uuid.uuid4(), role=role)) as client:
        response = client.get(_MENU_PATH)
    assert response.status_code == 200
    assert isinstance(response.json()["sections"], list)


def test_demo_account_is_403_even_with_admin_role() -> None:
    """계약 ⑤ — 데모 계정은 역할이 맞아도 메뉴를 못 받는다(04 §4 · ADMIN-06).

    대조군은 바로 아래 `test_non_demo_admin_with_same_role_gets_menu`다 — 같은
    `CONTENT_ADMIN` 역할이 한쪽은 403, 한쪽은 200이어야 이 검사가 *신원* 축을 실제로 보는
    것이다. 대조군이 없으면 "전부 403" 오구현이 통과한다.
    """
    resp = _client(_DEMO_ADMIN_USER).get(_MENU_PATH)
    assert resp.status_code == 403
    assert "실 신원" in resp.json()["detail"]


def test_non_demo_admin_with_same_role_gets_menu() -> None:
    """계약 ⑤ 양성 대조 — 같은 역할의 비데모 계정은 200 + 비어 있지 않은 메뉴."""
    resp = _client(_ADMIN_USER).get(_MENU_PATH)
    assert resp.status_code == 200
    assert resp.json()["sections"], "관리 역할인데 메뉴가 비었다 — 대조군이 무효다"
