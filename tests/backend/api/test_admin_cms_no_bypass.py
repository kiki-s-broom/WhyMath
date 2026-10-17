"""CMS가 발행 워크플로우를 우회해 Published를 쓰는 경로가 없음을 동결한다 — P3-12 지시문 검증 ②.

두 층이다. 둘 중 하나만 있으면 다른 쪽의 구멍이 그대로 남는다:

  ① **정적(AST)** — 기존 `test_publish_gate_enforcement`의 스캐너(R1 ORM import · R2 발행 포인터 쓰기 ·
     R3 쓰기 SQL 문자열)를 **CMS 모듈에 직접** 적용한다. 정상 코드가 0건인 것은 증거가 아니므로,
     각 규칙을 위반하는 코드를 CMS 소스에 **주입해 RED를 확인**한다.
     한계(스캐너 docstring이 명시): 런타임에 조립되는 dict 키·`getattr`·동적 SQL은 보지 못한다.
  ② **동적(HTTP)** — 정적 스캔이 못 보는 그 경로를 값 검사로 막는다: CMS 쓰기 라우트에 상태·발행·
     승인 키를 실어 보내면 거부되고, 거부는 게이트·DB·감사를 건드리지 않는다.

스캐너를 복사하지 않고 **원본 테스트 파일을 그대로 로드**한다 — 복사본은 원본이 강화될 때 조용히
뒤처진다(테스트 디렉터리는 패키지가 아니라 경로로 로드한다).
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient

from whymath_backend.api._auth import get_current_user
from whymath_backend.app import create_app
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.schema.enums import Role

_ENFORCEMENT = Path(__file__).resolve().parents[1] / "l3" / "test_publish_gate_enforcement.py"


def _load_enforcement() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_gate_enforcement_for_cms", _ENFORCEMENT)
    assert (
        spec is not None and spec.loader is not None
    ), f"스캐너 원본을 로드하지 못했다: {_ENFORCEMENT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_E = _load_enforcement()
_CMS_MODULES = ("api/admin_cms.py", "api/admin_cms_resources.py")


def _source(rel: str) -> str:
    for path, text in _E._production_files():
        if path == rel:
            return str(text)
    raise AssertionError(f"운영 패키지에서 {rel}을 찾지 못했다 — 스캔 대상이 아니다")


# ═══════════════════════════════════════════════════════════════════════════════════════
# ① 정적 — 실 소스는 깨끗하고, 주입하면 스캐너가 RED를 낸다
# ═══════════════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("rel", _CMS_MODULES)
def test_cms_modules_are_inside_the_scan_population(rel: str) -> None:
    """스캔 대상에 실제로 들어 있다 — 대상 밖이면 아래 '깨끗함'은 공허하다."""
    assert any(path == rel for path, _ in _E._production_files())


@pytest.mark.parametrize("rel", _CMS_MODULES)
def test_cms_modules_have_no_gate_bypass_today(rel: str) -> None:
    assert _E.scan_source(rel, _source(rel)) == []


# 주입 코드 — 각 줄은 **서로 다른 규칙**을 위반한다. (규칙 접두, 주입 소스)
_INJECTIONS: list[tuple[str, str]] = [
    ("R1", "from whymath_backend.db.models.concept_version import ConceptVersion\n"),
    ("R1", "from whymath_backend.db.models import ConceptVersion\n"),
    ("R1", "import whymath_backend.db.models.concept_version\n"),
    ("R2", "def _f(c, x):\n    c.current_published_version_id = x\n"),
    ("R2", "def _f(c, x):\n    c.current_published_version_id += x\n"),
    ("R2", "def _f(x):\n    return Concept(current_published_version_id=x)\n"),
    ("R2", 'def _f(c, x):\n    setattr(c, "current_published_version_id", x)\n'),
    ("R2", 'def _f(x):\n    return {"current_published_version_id": x}\n'),
    ("R3", "SQL = \"UPDATE concept_version SET status = 'PUBLISHED'\"\n"),
    ("R3", 'SQL = "INSERT INTO concept_version (concept_id) VALUES (1)"\n'),
    ("R3", 'SQL = "DELETE FROM concept_version"\n'),
    ("R3", 'SQL = "UPDATE concept SET current_published_version_id = NULL"\n'),
]


@pytest.mark.parametrize("rel", _CMS_MODULES)
@pytest.mark.parametrize(("rule", "snippet"), _INJECTIONS, ids=lambda v: str(v)[:48])
def test_injected_bypass_is_caught_in_cms_modules(rel: str, rule: str, snippet: str) -> None:
    """② 정상 소스가 0건인 것만으로는 '막힌다'의 증거가 아니다 — 위반 주입 → RED."""
    original = _source(rel)
    mutated = original + "\n" + snippet
    assert mutated != original, "주입이 적용되지 않았다"
    violations = _E.scan_source(rel, mutated)
    assert violations, f"{rule} 위반을 주입했는데 스캐너가 침묵했다: {snippet!r}"
    assert any(v.startswith(rule) for v in violations), (rule, violations)


def test_injection_catalog_covers_all_three_rules() -> None:
    """분모 — 주입 목록이 R1·R2·R3를 모두 덮는다(한 규칙만 시험하면 나머지는 보호 미확인)."""
    assert {rule for rule, _ in _INJECTIONS} == {"R1", "R2", "R3"}


def test_cms_reads_versions_through_the_gate_module_not_the_orm() -> None:
    """읽기도 게이트 모듈을 거친다 — CMS가 ORM `ConceptVersion`을 import하지 않고 목록·상세를 낸다.

    문자열 부분일치가 아니라 **import 구문을 AST로** 본다: `schema.concept_version`(순수 pydantic
    스키마)은 허용이고 `db.models.concept_version`(ORM)만 금지인데, 부분일치는 둘을 구분하지 못한다.
    """
    import ast

    tree = ast.parse(_source("api/admin_cms.py"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
            imported.extend(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
    assert imported, "import 구문을 하나도 읽지 못했다 — 스캔 0건은 통과가 아니다"
    assert not [m for m in imported if m.startswith("whymath_backend.db.models.concept_version")]
    assert "whymath_backend.db.models.ConceptVersion" not in imported
    # 대조군 — 허용되는 쪽(스키마·게이트 모듈)은 실제로 쓰고 있다.
    assert "whymath_backend.schema.concept_version" in imported
    assert "whymath_backend.l3.publish_gate" in imported or "whymath_backend.l3" in imported
    source = _source("api/admin_cms.py")
    assert "gate.list_versions" in source and "gate.get_version" in source


# ═══════════════════════════════════════════════════════════════════════════════════════
# ② 동적 — 정적 스캔이 못 보는 런타임 경로
# ═══════════════════════════════════════════════════════════════════════════════════════


class _Session:
    """호출을 기록만 하는 세션 — 거부된 요청은 아무 것도 호출하지 않아야 한다."""

    def __init__(self) -> None:
        self.calls = 0

    def _hit(self) -> None:
        self.calls += 1

    def add(self, _: Any) -> None:
        self._hit()

    async def get(self, *_: Any) -> None:
        self._hit()

    async def execute(self, *_: Any) -> Any:
        self._hit()
        raise AssertionError("거부되어야 할 요청이 DB를 읽었다")

    async def commit(self) -> None:
        self._hit()

    async def rollback(self) -> None:
        return None


_APP = create_app()
_ADMIN = UserProfile(user_id=uuid.uuid4(), role=Role.CONTENT_ADMIN)
_VID = uuid.uuid4()
_CID = uuid.uuid4()

_FORBIDDEN_KEYS: dict[str, Any] = {
    "current_published_version_id": str(uuid.uuid4()),
    "status": "PUBLISHED",
    "published_at": "2026-01-01T00:00:00Z",
    "is_published": True,
    "review_status": "approved",
    "approved_by": "attacker",
    "governance": {"approved_by": "attacker"},
}


def _post(path: str, body: dict[str, Any], session: _Session) -> Any:
    async def _override() -> Any:
        yield session

    _APP.dependency_overrides.clear()
    _APP.dependency_overrides[get_session] = _override
    _APP.dependency_overrides[get_current_user] = lambda: _ADMIN
    return TestClient(_APP).post(path, json=body)


@pytest.mark.parametrize("key", sorted(_FORBIDDEN_KEYS))
def test_transition_request_cannot_carry_published_state(key: str) -> None:
    """전이 요청 본문에 포인터·상태·승인자를 실어도 거부된다(extra=forbid) — 관리자라도."""
    session = _Session()
    resp = _post(
        f"/v1/admin/cms/versions/{_VID}/transitions",
        {"action": "publish", "expected_status": "APPROVED", key: _FORBIDDEN_KEYS[key]},
        session,
    )
    assert resp.status_code == 422, resp.text
    assert session.calls == 0


@pytest.mark.parametrize("key", sorted(_FORBIDDEN_KEYS))
def test_rollback_request_cannot_carry_published_state(key: str) -> None:
    session = _Session()
    resp = _post(
        f"/v1/admin/cms/concepts/{_CID}/rollback",
        {"expected_published_version_id": str(uuid.uuid4()), key: _FORBIDDEN_KEYS[key]},
        session,
    )
    assert resp.status_code == 422, resp.text
    assert session.calls == 0


@pytest.mark.parametrize("key", sorted(_FORBIDDEN_KEYS))
def test_draft_changes_cannot_carry_published_state(key: str) -> None:
    """초안 payload에 실은 포인터·상태 키는 `ConceptVersionPayload(extra=forbid)`가 거부한다.

    개념 행 조회(`session.get`) 뒤에 payload 검증이 일어나므로 `get`은 허용하되, **쓰기(add·commit)
    는 0**이어야 한다 — 거부 뒤에 감사 행이나 초안이 남지 않는다.
    """
    session = _Session()
    live = _make_live()

    async def _get(*_: Any) -> Any:
        return live

    session.get = _get  # type: ignore[method-assign]

    # list_versions는 게이트 모듈이 `session.execute`로 읽는다 — 빈 결과를 돌려준다.
    class _Empty:
        def scalars(self) -> Any:
            return self

        def __iter__(self) -> Any:
            return iter(())

    async def _execute_empty(*_: Any) -> Any:
        return _Empty()

    session.execute = _execute_empty  # type: ignore[method-assign]
    resp = _post(
        f"/v1/admin/cms/concepts/{_CID}/drafts", {"changes": {key: _FORBIDDEN_KEYS[key]}}, session
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "payload_invalid"
    assert session.calls == 0, "거부된 초안이 쓰기(add·commit)를 일으켰다"


def _make_live() -> Any:
    from whymath_backend.db.models.concept import Concept
    from whymath_backend.schema.concept import Concept as ConceptSchema

    return Concept.from_schema(ConceptSchema(code="CAL-X", name_ko="미적분", level="단원"))
