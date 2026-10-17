"""CMS 리소스 라우트 스모크 — 모든 라우트가 **서빙되고**, 학생은 **DB 접근 전에** 막힌다 (P3-12).

왜 이 파일이 있는가
-------------------
`test_admin_cms.py`·`test_admin_cms_resources.py`는 리소스 8종을 `for spec in RESOURCES` 와
`f"/v1/admin/cms/{spec.key}/items/…"` 로 **일반화해** 부른다 — 로직을 한 번만 쓰려는 옳은 선택이다.
그런데 선언≠배선 정적 감사(`ops/declared_unwired_audit`)는 경로가 *리터럴*이어야 호출로 읽는다. 경로
중간을 변수로 만들면 그 호출은 "어느 라우트를 부르는지" 정적으로 알 수 없어(변수 자리를 와일드카드로
풀면 거짓 도달이 늘어난다 — 그 감사기가 일부러 안 푸는 이유) 일반형 테스트가 닿는 라우트가 미도달로
보인다.

그 구멍을 `by-design` 유예로 덮으면 *수백 번 호출되는 라우트를 "미도달"이라고 선언*하는 거짓이 된다.
그래서 이 파일이 일반형으로만 닿던 13개 라우트를 **리터럴 경로로 한 번씩** 부른다. 그리고 부르는 김에
일반형 테스트가 라우트 하나하나에 대해서는 보장하지 않던 두 가지를 라우트 단위로 확인한다:

  ① 관리자는 라우트에 **실제로 도달**한다 — 라우팅 404(`{"detail":"Not Found"}`)가 아니라 핸들러가 낸
     사유 코드(`not_found`) 또는 정상 응답(200)이다
  ② 학생은 **전 라우트에서** 403이고 세션(DB)을 한 번도 건드리지 않는다 — 모듈 가드가 앞이다
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from whymath_backend.api._auth import get_current_user
from whymath_backend.app import create_app
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.schema.enums import Role


class _Result:
    """빈 DB — 목록은 0건, 단건 조회는 없음."""

    def scalar_one(self) -> int:
        return 0

    def scalar_one_or_none(self) -> None:
        return None

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[Any]:
        return []


class _Session:
    """조회는 빈 결과를 주고, 호출 횟수를 센다(거부된 요청은 0이어야 한다)."""

    def __init__(self) -> None:
        self.calls = 0

    def add(self, _: Any) -> None:
        self.calls += 1

    async def get(self, *_: Any) -> None:
        self.calls += 1
        return None

    async def execute(self, *_: Any, **__: Any) -> _Result:
        self.calls += 1
        return _Result()

    async def commit(self) -> None:
        self.calls += 1

    async def rollback(self) -> None:
        return None


_APP = create_app()
_ADMIN = UserProfile(user_id=uuid.uuid4(), role=Role.CONTENT_ADMIN)
_STUDENT = UserProfile(user_id=uuid.uuid4(), role=Role.STUDENT)


def _client(user: UserProfile, session: _Session) -> TestClient:
    async def _override() -> Any:
        yield session

    _APP.dependency_overrides.clear()
    _APP.dependency_overrides[get_session] = _override
    _APP.dependency_overrides[get_current_user] = lambda: user
    return TestClient(_APP)


#: 라우트 라벨 → 기대(관리자). `"list"` = 200 빈 목록, `"missing"` = 핸들러가 낸 404(`not_found`).
_EXPECT = {
    "GET curriculum_version": "list",
    "GET curriculum_version/items": "missing",
    "PATCH curriculum_version/items": "missing",
    "GET hint": "list",
    "GET misconception": "list",
    "GET misconception/items": "missing",
    "GET problem": "list",
    "GET problem_step": "list",
    "GET problem_step/items": "missing",
    "GET skill_node/items": "missing",
    "GET strategy_node": "list",
    "GET strategy_node/items": "missing",
    "PATCH strategy_node/items": "missing",
}


def _exercise(client: TestClient) -> dict[str, Any]:
    """13개 라우트를 **리터럴 경로**로 한 번씩 부른다 — 정적 도달 감사가 읽는 형태다."""
    return {
        "GET curriculum_version": client.get("/v1/admin/cms/curriculum_version"),
        "GET curriculum_version/items": client.get(
            "/v1/admin/cms/curriculum_version/items/00000000-0000-0000-0000-000000000001"
        ),
        "PATCH curriculum_version/items": client.patch(
            "/v1/admin/cms/curriculum_version/items/00000000-0000-0000-0000-000000000001",
            json={"changes": {"version_label": "스모크"}},
        ),
        "GET hint": client.get("/v1/admin/cms/hint"),
        "GET misconception": client.get("/v1/admin/cms/misconception"),
        "GET misconception/items": client.get("/v1/admin/cms/misconception/items/M-1"),
        "GET problem": client.get("/v1/admin/cms/problem"),
        "GET problem_step": client.get("/v1/admin/cms/problem_step"),
        "GET problem_step/items": client.get(
            "/v1/admin/cms/problem_step/items/00000000-0000-0000-0000-000000000001"
        ),
        "GET skill_node/items": client.get("/v1/admin/cms/skill_node/items/SK-1"),
        "GET strategy_node": client.get("/v1/admin/cms/strategy_node"),
        "GET strategy_node/items": client.get("/v1/admin/cms/strategy_node/items/ST-1"),
        "PATCH strategy_node/items": client.patch(
            "/v1/admin/cms/strategy_node/items/ST-1",
            json={"changes": {"name_ko": "스모크"}},
        ),
    }


def test_exercise_covers_exactly_the_expected_routes() -> None:
    """분모 — 기대표와 실제로 부르는 라우트가 같다(한쪽만 늘면 검사가 조용히 비어 간다)."""
    responses = _exercise(_client(_ADMIN, _Session()))
    assert set(responses) == set(_EXPECT)
    assert len(_EXPECT) == 13


@pytest.mark.parametrize("label", sorted(_EXPECT))
def test_admin_reaches_the_handler_not_a_routing_404(label: str) -> None:
    """① 관리자: 라우팅 404가 아니라 핸들러의 응답이다."""
    resp = _exercise(_client(_ADMIN, _Session()))[label]
    if _EXPECT[label] == "list":
        assert resp.status_code == 200, (label, resp.text)
        body = resp.json()
        assert body["total"] == 0 and body["items"] == [], label
    else:
        assert resp.status_code == 404, (label, resp.text)
        detail = resp.json()["detail"]
        # 라우팅 404는 `{"detail":"Not Found"}`(문자열)이다 — 핸들러가 낸 404만 사유 코드를 가진다.
        assert isinstance(detail, dict) and detail["code"] == "not_found", (label, detail)


@pytest.mark.parametrize("label", sorted(_EXPECT))
def test_student_is_denied_on_every_route_before_any_db_access(label: str) -> None:
    """② 학생: 전 라우트 403, DB 접근 0 — 모듈 가드가 핸들러·세션보다 앞이다."""
    session = _Session()
    resp = _exercise(_client(_STUDENT, session))[label]
    assert resp.status_code == 403, (label, resp.status_code, resp.text)
    assert session.calls == 0, f"{label}: 거부된 요청이 DB를 건드렸다({session.calls}회)"
