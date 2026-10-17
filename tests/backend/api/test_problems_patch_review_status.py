"""`PATCH /v1/problems/{id}`의 검수 상태 전이 검증 동결 — hermetic (ADMIN-16).

ADMIN-07이 전이표(`schema/review_transition.py`)와 감사 1행을 `POST …/transitions`에만 걸어,
같은 `review_status`를 쓰는 기존 `PATCH`가 표를 우회했다(rejected→approved · 사유 없는 격리).
이 파일은 그 우회가 닫혔고 **닫힌 채로 있음**을 고정한다.

  ① 표에 없는 상태 변경은 409 — 쓰기·감사·커밋 0 (5×4 전 쌍 중 불허 12쌍 전수)
  ② 합법 변경은 감사 정확히 1행이고 그 동작이 `update`가 아니라 전이 액션이다
  ③ 격리는 *이번 요청의* 사유가 필요하다(과거 격리의 낡은 사유 재사용 금지) · 시각은 서버 시계
  ④ 격리가 아닌 전이는 격리 기록(사유·시각)을 함께 바꿀 수 없다 · 해제는 기록을 보존한다
  ⑤ 상태가 그대로인 요청(GET 본문 왕복 포함)은 전이가 아니라 기존 `update` 경로다
  ⑥ 상태를 바꾸려는 요청만 행을 잠근다(전이 라우트와 같은 직렬화) — 나머지는 읽기 불변
  ⑦ 우회 시도는 WARNING으로 남되 자유 텍스트(사유)는 싣지 않는다
  ⑧ 구조 가드(AST): Problem 행을 API 스키마에서 쓰는 곳은 `problems.py`뿐이고, PATCH는 판정 함수를
     부르며, `api/`에서 `.review_status`를 대입하는 파일은 `admin_bff.py` 하나다

실 PG 의미(실제 행 잠금·롤백)는 `test_problems_patch_review_status_integration.py`가 본다.
"""

from __future__ import annotations

import ast
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from whymath_backend.api._auth import require_content_admin
from whymath_backend.app import create_app
from whymath_backend.db.models.audit import PrivacyAudit
from whymath_backend.db.models.problem import Problem
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.schema.enums import (
    AuditEventKind,
    Curriculum,
    PrivacyAuditResourceType,
    ReviewStatus,
    Role,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem import Problem as ProblemSchema
from whymath_backend.schema.review_transition import QUARANTINE_REASON_MAX_LENGTH

_ADMIN = UserProfile(user_id=uuid.uuid4(), role=Role.CONTENT_ADMIN)
_OLD_REASON = "과거 격리 사유 — 복수 정답"
_OLD_AT = datetime(2026, 8, 31, 9, 0, tzinfo=UTC)
#: 거부 로그에 자유 텍스트가 새지 않는지 보는 결함주입 표지.
_SENTINEL = "SENTINEL-ADMIN16-사유본문-7731"

P, A, R, Q = (
    ReviewStatus.pending,
    ReviewStatus.approved,
    ReviewStatus.rejected,
    ReviewStatus.quarantined,
)
_ALL_STATES: tuple[ReviewStatus | None, ...] = (None, P, A, R, Q)
_LEGAL: dict[tuple[ReviewStatus | None, ReviewStatus], str] = {
    (P, A): "approve",
    (P, R): "reject",
    (A, Q): "quarantine",
    (Q, A): "release",
}


def _label(state: ReviewStatus | None) -> str:
    return "미설정" if state is None else state.value


def _problem(status: ReviewStatus | None, *, with_record: bool = False) -> Problem:
    """자체생성 최소 문항 ORM. `with_record`면 과거 격리 기록(사유·시각)을 달아 둔다."""
    kwargs: dict[str, Any] = {
        "source_type": SourceType.자체생성,
        "curriculum_version": Curriculum.REVISION_2022,
        "valid_from_year": 2022,
        "subject": Subject.미적분,
        "unit_codes": ["CAL-INT-DEF"],
        "question_text": "적분값을 구하시오",
        "answer": "3",
        "review_status": status,
    }
    if with_record or status is Q:
        kwargs.update(quarantine_reason=_OLD_REASON, quarantined_at=_OLD_AT)
    return Problem.from_schema(ProblemSchema(**kwargs))


class _Session:
    """라우터가 부르는 표면만 흉내내되 쓰기·커밋·잠금 인자를 전부 캡처한다."""

    def __init__(self, problem: Problem | None) -> None:
        self.problem = problem
        self.added: list[Any] = []
        self.merged: list[Any] = []
        self.commits = 0
        self.rollbacks = 0
        self.get_kwargs: list[dict[str, Any]] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def get(self, _model: Any, pk: uuid.UUID, **kwargs: Any) -> Problem | None:
        self.get_kwargs.append(kwargs)
        if self.problem is not None and pk == self.problem.problem_id:
            return self.problem
        return None

    async def merge(self, obj: Any) -> Any:
        self.merged.append(obj)
        return obj

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def refresh(self, obj: Any) -> None:
        return None

    @property
    def audits(self) -> list[PrivacyAudit]:
        return [o for o in self.added if isinstance(o, PrivacyAudit)]


def _client(fake: _Session) -> TestClient:
    app = create_app()

    async def _override() -> AsyncIterator[_Session]:
        yield fake

    app.dependency_overrides[get_session] = _override
    app.dependency_overrides[require_content_admin] = lambda: _ADMIN
    return TestClient(app)


def _patch(fake: _Session, body: dict[str, Any], **kwargs: Any) -> Any:
    assert fake.problem is not None
    return _client(fake).patch(f"/v1/problems/{fake.problem.problem_id}", json=body, **kwargs)


def _assert_nothing_written(fake: _Session) -> None:
    assert fake.merged == [], "거부된 요청이 병합(쓰기)을 일으켰다"
    assert fake.audits == [], "거부된 요청이 감사 행을 남겼다(변경이 아닌 것을 변경으로 기록)"
    assert fake.commits == 0, "거부된 요청이 커밋했다"


# ── ① 표에 없는 변경은 전수 거부 ─────────────────────────────────────────────────────


_ILLEGAL_PAIRS = [
    (cur, tgt)
    for cur in _ALL_STATES
    for tgt in (P, A, R, Q)
    if cur is not tgt and (cur, tgt) not in _LEGAL
]


def test_the_illegal_pair_set_is_the_complement_of_the_table() -> None:
    """픽스처 자체의 변별력 — 불허 12쌍 + 허용 4쌍 + 같은 상태 4쌍 = 5×4 20쌍."""
    assert len(_ILLEGAL_PAIRS) == 12
    assert len(_LEGAL) == 4


@pytest.mark.parametrize(
    ("current", "target"),
    _ILLEGAL_PAIRS,
    ids=[f"{_label(c)}->{_label(t)}" for c, t in _ILLEGAL_PAIRS],
)
def test_illegal_status_change_is_409_and_writes_nothing(
    current: ReviewStatus | None, target: ReviewStatus
) -> None:
    """rejected→approved 같은 우회가 막힌다. 격리 목표에는 사유를 실어, 거부 사유가 '불허 전이'뿐임을 보인다."""
    fake = _Session(_problem(current))
    resp = _patch(fake, {"review_status": target.value, "quarantine_reason": "충분한 사유"})
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "illegal_transition"
    assert detail["current_status"] == (None if current is None else current.value)
    assert detail["requested_status"] == target.value
    _assert_nothing_written(fake)


def test_clearing_status_to_null_is_also_refused() -> None:
    """상태를 NULL로 되돌리는 것도 표에 없는 변경이다(검수 이력 소거 경로)."""
    fake = _Session(_problem(A))
    resp = _patch(fake, {"review_status": None})
    assert resp.status_code == 409
    assert resp.json()["detail"]["requested_status"] is None
    _assert_nothing_written(fake)


# ── ② 합법 변경은 감사 1행·동작은 전이 액션 ─────────────────────────────────────────


@pytest.mark.parametrize(("pair", "action"), list(_LEGAL.items()), ids=list(_LEGAL.values()))
def test_legal_status_change_writes_exactly_one_audit_row_with_the_transition_action(
    pair: tuple[ReviewStatus | None, ReviewStatus], action: str
) -> None:
    current, target = pair
    fake = _Session(_problem(current))
    body: dict[str, Any] = {"review_status": target.value}
    if action == "quarantine":
        body["quarantine_reason"] = "복수 정답"
    resp = _patch(fake, body)
    assert resp.status_code == 200, resp.text
    assert resp.json()["review_status"] == target.value
    assert len(fake.merged) == 1 and fake.commits == 1 and fake.rollbacks == 0
    # P3-25 — 사람이 정한 상태는 다음 CLI 적재가 되돌리지 못하게 표지가 붙는다.
    assert fake.merged[0].cms_edited_at is not None
    assert len(fake.audits) == 1, "합법 전이는 감사 정확히 1행이어야 한다"
    row = fake.audits[0]
    assert row.action == action, "감사 동작이 전이 액션이 아니라 update로 뭉개졌다"
    assert row.event_kind == AuditEventKind.content_mutation.value
    assert row.resource_type == PrivacyAuditResourceType.problem.value
    assert row.resource_id == fake.problem.problem_id  # type: ignore[union-attr]
    assert row.user_id == _ADMIN.user_id


# ── ③ 격리 — 이번 요청의 사유 · 서버 시각 ───────────────────────────────────────────


@pytest.mark.parametrize(
    "body",
    [
        {"review_status": "quarantined"},
        {"review_status": "quarantined", "quarantine_reason": "   "},
        {"review_status": "quarantined", "quarantine_reason": None},
        {
            "review_status": "quarantined",
            "quarantine_reason": "x" * (QUARANTINE_REASON_MAX_LENGTH + 1),
        },
    ],
    ids=["키없음", "공백뿐", "null", "상한초과"],
)
def test_quarantine_without_a_valid_reason_in_this_request_is_422(body: dict[str, Any]) -> None:
    fake = _Session(_problem(A))
    resp = _patch(fake, body)
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "reason_required"
    _assert_nothing_written(fake)


def test_quarantine_does_not_reuse_a_stale_reason_from_a_past_quarantine() -> None:
    """행에 과거 격리의 사유가 남아 있어도(해제 후 보존) 새 격리는 새 사유를 요구한다.

    병합 결과(`merged`)로 판정하면 이 요청은 '사유 있음'으로 통과한다 — POST 경로는 매 격리마다
    새 사유를 요구하므로, 두 표면의 계약이 갈라지는 지점이다.
    """
    fake = _Session(_problem(A, with_record=True))
    resp = _patch(fake, {"review_status": "quarantined"})
    assert resp.status_code == 422
    _assert_nothing_written(fake)


def test_quarantine_stamps_server_time_and_strips_the_reason() -> None:
    fake = _Session(_problem(A))
    before = datetime.now(UTC)
    resp = _patch(
        fake,
        {
            "review_status": "quarantined",
            "quarantine_reason": "  복수 정답  ",
            # 소급 격리 시도 — 서버 시계가 이긴다.
            "quarantined_at": "2020-01-01T00:00:00Z",
        },
    )
    after = datetime.now(UTC)
    assert resp.status_code == 200, resp.text
    written = fake.merged[0]
    assert written.quarantine_reason == "복수 정답"
    assert written.quarantined_at is not None
    assert before - timedelta(seconds=1) <= written.quarantined_at <= after + timedelta(seconds=1)
    assert resp.json()["quarantine_reason"] == "복수 정답"  # 덮어쓴 실제 기록값이 응답에 보인다


# ── ④ 격리 기록은 격리 전이에서만 · 해제는 보존 ───────────────────────────────────────


def test_release_keeps_the_quarantine_record_untouched() -> None:
    fake = _Session(_problem(Q))
    resp = _patch(fake, {"review_status": "approved"})
    assert resp.status_code == 200, resp.text
    written = fake.merged[0]
    assert written.review_status in (A, A.value)
    assert written.quarantine_reason == _OLD_REASON
    assert written.quarantined_at == _OLD_AT
    assert fake.audits[0].action == "release"


@pytest.mark.parametrize(
    ("current", "body"),
    [
        (Q, {"review_status": "approved", "quarantine_reason": "해제하며 사유를 덮어씀"}),
        (Q, {"review_status": "approved", "quarantine_reason": None}),
        (Q, {"review_status": "approved", "quarantined_at": "2026-09-30T00:00:00Z"}),
        (Q, {"review_status": "approved", "quarantined_at": None}),
        (P, {"review_status": "approved", "quarantine_reason": "승인인데 격리 사유"}),
        (P, {"review_status": "rejected", "quarantined_at": "2026-09-30T00:00:00Z"}),
    ],
    ids=[
        "해제+사유덮어쓰기",
        "해제+사유삭제",
        "해제+시각변경",
        "해제+시각삭제",
        "승인+사유",
        "반려+시각",
    ],
)
def test_a_non_quarantine_transition_cannot_rewrite_the_quarantine_record(
    current: ReviewStatus, body: dict[str, Any]
) -> None:
    fake = _Session(_problem(current))
    resp = _patch(fake, body)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "quarantine_record_immutable"
    _assert_nothing_written(fake)


# ── ⑤ 상태가 그대로면 전이가 아니라 기존 update ─────────────────────────────────────


@pytest.mark.parametrize("status", [None, P, A, R, Q], ids=[_label(s) for s in _ALL_STATES])
def test_unchanged_status_round_trip_is_a_plain_update(status: ReviewStatus | None) -> None:
    """GET으로 받은 본문을 그대로 되돌려 보내는 클라이언트(상태 키 포함)는 막히지 않는다."""
    problem = _problem(status)
    fake = _Session(problem)
    body = problem.to_schema().model_dump(mode="json")
    body["answer"] = "42"
    resp = _patch(fake, body)
    assert resp.status_code == 200, resp.text
    assert len(fake.audits) == 1 and fake.audits[0].action == "update"


def test_a_plain_field_patch_stays_an_update() -> None:
    fake = _Session(_problem(A))
    resp = _patch(fake, {"answer": "42"})
    assert resp.status_code == 200
    assert [a.action for a in fake.audits] == ["update"]


# ── ⑥ 잠금은 상태를 바꾸려는 요청에만 ───────────────────────────────────────────────


def test_status_bearing_patch_locks_the_row_like_the_transition_route() -> None:
    fake = _Session(_problem(P))
    assert _patch(fake, {"review_status": "approved"}).status_code == 200
    assert fake.get_kwargs == [{"with_for_update": True, "populate_existing": True}]


def test_patch_without_a_status_key_reads_exactly_as_before() -> None:
    fake = _Session(_problem(A))
    assert _patch(fake, {"answer": "42"}).status_code == 200
    assert fake.get_kwargs == [{}], "상태를 건드리지 않는 PATCH까지 행을 잠갔다(불필요한 직렬화)"


def test_missing_problem_with_a_status_key_is_404_without_audit() -> None:
    fake = _Session(None)
    resp = _client(fake).patch(f"/v1/problems/{uuid.uuid4()}", json={"review_status": "approved"})
    assert resp.status_code == 404
    _assert_nothing_written(fake)


# ── ⑦ 우회 시도는 로그로 남되 자유 텍스트는 싣지 않는다 ───────────────────────────────


def test_refusal_is_logged_without_free_text(caplog: pytest.LogCaptureFixture) -> None:
    fake = _Session(_problem(R))
    with caplog.at_level(logging.WARNING, logger="whymath_backend.api.problems"):
        resp = _patch(fake, {"review_status": "approved", "quarantine_reason": _SENTINEL})
    assert resp.status_code == 409
    text = caplog.text
    assert "ADMIN-16" in text and "illegal_transition" in text
    assert str(_ADMIN.user_id) in text and "rejected" in text
    assert _SENTINEL not in text, "거부 로그에 사유 본문(자유 텍스트)이 실렸다"


# ── ⑧ 구조 가드(AST) ─────────────────────────────────────────────────────────────────

_API_DIR = Path(__file__).resolve().parents[3] / "src" / "backend" / "whymath_backend" / "api"


def _calls(node: ast.AST) -> list[str]:
    names: list[str] = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            func = sub.func
            if isinstance(func, ast.Name):
                names.append(func.id)
            elif isinstance(func, ast.Attribute):
                names.append(func.attr)
    return names


def test_only_problems_py_builds_problem_rows_from_api_schemas() -> None:
    """Problem 행을 요청 스키마에서 쓰는 API 모듈이 늘면 그 모듈도 전이표를 거쳐야 한다."""
    writers: list[str] = []
    scanned = 0
    for path in sorted(_API_DIR.glob("*.py")):
        scanned += 1
        if "Problem.from_schema(" in path.read_text(encoding="utf-8"):
            writers.append(path.name)
    assert scanned > 10, "API 모듈 스캔이 공허하다(경로 오류)"
    assert writers == ["problems.py"], (
        f"Problem.from_schema를 부르는 API 모듈이 {writers}다 — 새 쓰기 표면이면 "
        "review_status 변경을 plan_review_field_change로 거치게 하라(ADMIN-16)"
    )


def test_patch_problem_calls_the_transition_planner() -> None:
    tree = ast.parse((_API_DIR / "problems.py").read_text(encoding="utf-8"))
    handlers = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "patch_problem"
    ]
    assert len(handlers) == 1
    calls = _calls(handlers[0])
    assert "plan_review_field_change" in calls
    # 병합(쓰기)이 판정보다 앞서면 판정이 쓰기를 막지 못한다 — 호출 순서까지 고정한다.
    merge_line = next(
        sub.lineno
        for sub in ast.walk(handlers[0])
        if isinstance(sub, ast.Call)
        and isinstance(sub.func, ast.Attribute)
        and sub.func.attr == "merge"
    )
    plan_line = next(
        sub.lineno
        for sub in ast.walk(handlers[0])
        if isinstance(sub, ast.Call)
        and isinstance(sub.func, ast.Name)
        and sub.func.id == "plan_review_field_change"
    )
    assert plan_line < merge_line


def test_only_admin_bff_assigns_review_status_attributes_in_the_api_layer() -> None:
    assigners: list[str] = []
    for path in sorted(_API_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                targets = [node.target]
            if any(isinstance(t, ast.Attribute) and t.attr == "review_status" for t in targets):
                assigners.append(path.name)
                break
    assert assigners == ["admin_bff.py"], assigners
