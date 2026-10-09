"""`POST /v1/problems`의 초기 검수 상태 제한 동결 — hermetic (ADMIN-19).

ADMIN-16이 `PATCH`의 전이표 우회를 닫으며 발견한 같은 부류의 구멍: 생성 본문이 `review_status=
approved`를 직접 실으면 `pending→approve` 전이·감사 동작·검수 기록 없이 승인 상태로 태어났다.
이 파일은 그 우회가 닫혔고 **닫힌 채로 있음**을 고정한다.

  ① 불허 초기 상태(approved·rejected·quarantined)는 422 — 쓰기·원장·감사·커밋 0
  ② 허용 초기 상태(미설정·pending)는 201이고 **값이 그대로 보존**된다(조용한 재작성 금지)
  ③ 거부는 DB·원장 관문보다 앞이다(원장 재료가 비어도 상태 코드가 사유를 말한다)
  ④ 우회 시도는 WARNING으로 남는다(행위자·상태·코드만)
  ⑤ 구조 가드(AST): `create_problem`이 판정기를 `Problem.from_schema`·`session.add`보다 앞에서
     부른다 — 판정기 호출이 지워지거나 쓰기 뒤로 밀리면 ①이 아니라 여기서도 잡힌다

호출자 전수 조사(ADMIN-19 ②) 결과는 태스크 notes와 `problem_quarantine_contract.md` §7에 있다.
"""

from __future__ import annotations

import ast
import logging
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from whymath_backend.api._auth import require_content_admin
from whymath_backend.app import create_app
from whymath_backend.db.models.audit import PrivacyAudit
from whymath_backend.db.models.provenance import ContentProvenance as ContentProvenanceORM
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.schema.enums import Curriculum, ReviewStatus, Role, SourceType, Subject
from whymath_backend.schema.problem import Problem as ProblemSchema

_ADMIN = UserProfile(user_id=uuid.uuid4(), role=Role.CONTENT_ADMIN)
_PROVENANCE: dict[str, Any] = {
    "generation_type": "FULLY_GENERATED",
    "license": "WHYMATH_GENERATED",
}

_API_SRC = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "backend"
    / "whymath_backend"
    / "api"
    / "problems.py"
)


class _Session:
    """POST 라우터가 부르는 표면만 흉내내되 쓰기·flush·커밋을 전부 캡처한다."""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.flushes = 0
        self.commits = 0
        self.rollbacks = 0

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushes += 1

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def refresh(self, obj: Any) -> None:
        return None

    @property
    def audits(self) -> list[PrivacyAudit]:
        return [o for o in self.added if isinstance(o, PrivacyAudit)]

    @property
    def ledgers(self) -> list[ContentProvenanceORM]:
        return [o for o in self.added if isinstance(o, ContentProvenanceORM)]


def _client(fake: _Session) -> TestClient:
    app = create_app()

    async def _override() -> AsyncIterator[_Session]:
        yield fake

    app.dependency_overrides[get_session] = _override
    app.dependency_overrides[require_content_admin] = lambda: _ADMIN
    return TestClient(app)


def _body(status: ReviewStatus | None, *, provenance: bool = True) -> dict[str, Any]:
    """자체생성 최소 유효 본문. `status=None`이면 `review_status` 키를 **싣는다**(null)."""
    schema = ProblemSchema(
        source_type=SourceType.자체생성,
        curriculum_version=Curriculum.REVISION_2022,
        valid_from_year=2022,
        subject=Subject.미적분,
        unit_codes=["CAL-INT-DEF"],
        review_status=status,
    )
    body: dict[str, Any] = schema.model_dump(mode="json")
    if provenance:
        body["provenance"] = dict(_PROVENANCE)
    return body


def _assert_nothing_written(fake: _Session) -> None:
    assert fake.added == [], "거부된 생성 요청이 쓰기(문항·원장·감사)를 일으켰다"
    assert fake.flushes == 0, "거부된 생성 요청이 flush했다"
    assert fake.commits == 0, "거부된 생성 요청이 커밋했다"


_P, _A, _R, _Q = (
    ReviewStatus.pending,
    ReviewStatus.approved,
    ReviewStatus.rejected,
    ReviewStatus.quarantined,
)


# ── ① 불허 초기 상태는 전수 422 ────────────────────────────────────────────────────


@pytest.mark.parametrize("status", [_A, _R, _Q], ids=lambda s: s.value)
def test_non_initial_status_is_422_and_writes_nothing(status: ReviewStatus) -> None:
    """승인·거부·격리로 태어나는 우회가 막힌다 — 응답 모양은 PATCH 422와 같은 {code, message}."""
    fake = _Session()
    resp = _client(fake).post("/v1/problems", json=_body(status))
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "illegal_initial_status"
    assert detail["requested_status"] == status.value
    assert "pending" in detail["message"]
    _assert_nothing_written(fake)


def test_refused_creation_leaves_no_provenance_ledger_row() -> None:
    """원장(LIC-09)도 남지 않는다 — 거부된 문항의 출처 행이 고아로 생기면 안 된다."""
    fake = _Session()
    resp = _client(fake).post("/v1/problems", json=_body(_A))
    assert resp.status_code == 422
    assert fake.ledgers == []
    assert fake.audits == [], "거부된 생성이 감사 행을 남겼다(생성이 아닌 것을 생성으로 기록)"


# ── ② 허용 초기 상태는 값 그대로 보존된다 ────────────────────────────────────────


def test_pending_is_created_and_stays_pending() -> None:
    """pending은 검수 큐 입구다 — 201이고 응답·ORM 어느 쪽에서도 다른 값으로 재작성되지 않는다."""
    fake = _Session()
    resp = _client(fake).post("/v1/problems", json=_body(_P))
    assert resp.status_code == 201, resp.text
    assert resp.json()["review_status"] == "pending"
    assert fake.commits == 1
    assert len(fake.audits) == 1
    assert len(fake.ledgers) == 1


def test_unset_is_created_and_stays_unset() -> None:
    """미설정(null)은 '아직 판정된 적 없음'이다 — pending으로 조용히 접지 않는다."""
    fake = _Session()
    resp = _client(fake).post("/v1/problems", json=_body(None))
    assert resp.status_code == 201, resp.text
    assert resp.json()["review_status"] is None
    assert fake.commits == 1


def test_omitted_key_is_created_and_stays_unset() -> None:
    """필드를 아예 생략한 기존 호출자도 깨지지 않는다(하위호환) — 값은 미설정으로 남는다."""
    body = _body(None)
    del body["review_status"]
    fake = _Session()
    resp = _client(fake).post("/v1/problems", json=body)
    assert resp.status_code == 201, resp.text
    assert resp.json()["review_status"] is None


# ── ③ 거부는 DB·원장 관문보다 앞이다 ─────────────────────────────────────────────


def test_refusal_precedes_the_provenance_gate() -> None:
    """원장 재료가 비어 있어도(자체생성은 필수) 이 요청의 첫 사유는 초기 상태다.

    관문 뒤에 판정기를 두면 provenance 보완 후 재시도에서야 상태 거부를 알게 된다(왕복 낭비)이고,
    더 나쁘게는 관문이 부르는 코드가 늘 때 상태 거부가 가려진다.
    """
    fake = _Session()
    resp = _client(fake).post("/v1/problems", json=_body(_A, provenance=False))
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "illegal_initial_status"
    _assert_nothing_written(fake)


# ── ④ 우회 시도는 기록된다 ──────────────────────────────────────────────────────────


def test_refusal_is_logged_as_warning_without_free_text(caplog: pytest.LogCaptureFixture) -> None:
    """행위자·요청 상태·코드가 WARNING으로 남는다. 본문의 자유 텍스트는 싣지 않는다."""
    sentinel = "SENTINEL-ADMIN19-본문-4417"
    body = _body(_A)
    body["question_text"] = sentinel
    fake = _Session()
    with caplog.at_level(logging.WARNING, logger="whymath_backend.api.problems"):
        resp = _client(fake).post("/v1/problems", json=body)
    assert resp.status_code == 422
    records = [r for r in caplog.records if "ADMIN-19" in r.getMessage()]
    assert len(records) == 1, "거부 로그가 정확히 1건이어야 한다"
    message = records[0].getMessage()
    assert records[0].levelno == logging.WARNING
    assert str(_ADMIN.user_id) in message
    assert "approved" in message
    assert "illegal_initial_status" in message
    assert sentinel not in message
    assert sentinel not in resp.text, "422 응답이 요청 본문의 자유 텍스트를 되돌려 보냈다"


# ── ⑤ 구조 가드(AST) ────────────────────────────────────────────────────────────────


def _create_problem_calls() -> dict[str, list[int]]:
    """`create_problem` 본문 안에서 이름별 호출 줄 번호(검사 대상만)."""
    tree = ast.parse(_API_SRC.read_text(encoding="utf-8"))
    func = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "create_problem"
    )
    wanted = {"ensure_initial_review_status", "require_provenance", "from_schema", "add"}
    found: dict[str, list[int]] = {name: [] for name in wanted}
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        name = callee.attr if isinstance(callee, ast.Attribute) else getattr(callee, "id", "")
        if name in wanted:
            found[name].append(node.lineno)
    return found


def test_create_problem_judges_the_initial_status_before_any_write() -> None:
    """판정기 호출이 존재하고, 문항 변환·세션 쓰기·원장 관문보다 앞에 있다."""
    calls = _create_problem_calls()
    judged = calls["ensure_initial_review_status"]
    assert len(judged) == 1, "create_problem이 초기 상태 판정기를 정확히 한 번 불러야 한다"
    first = judged[0]
    for later in ("require_provenance", "from_schema", "add"):
        found = calls[later]
        assert found, f"가드 하한: create_problem에서 {later} 호출을 찾지 못했다(스캔 무력화)"
        assert first < min(found), f"초기 상태 판정이 {later} 호출보다 뒤에 있다"
