"""`PATCH /v1/problems/{id}`의 발행 판 보호 동결 — hermetic (EOS-195).

이 PATCH는 본문을 스키마로 병합해 `session.merge`로 **모든 컬럼**을 행에 쓴다 — 승인 상태 가드도
없다. 발행된 판이 있는 문항을 여기서 고치면 판 payload와 라이브 행이 갈라진다(EOS-47이 시도에
고정한 판이 학생이 푼 문항과 달라진다). 이 파일은 그 입구가 닫혔고 **긴급 정지(격리)는 열려 있음**을
고정한다.

  ① 발행된 판이 있는 문항의 서빙 내용 변경은 409 `published_version_edit_blocked` — 쓰기·감사·커밋 0,
     응답에 막힌 필드 *이름*만 싣는다(값은 싣지 않는다)
  ② 필드마다 막힌다 — 서빙 내용 필드 12개 전수(목록이 `snapshot_payload`와 같음은
     `tests/backend/db/test_published_edit_guard.py`가 고정)
  ③ 격리·해제처럼 서빙 내용을 바꾸지 않는 요청은 통과한다 — 막으면 결함 문항을 내릴 수 없다
  ④ GET 본문을 그대로 되돌려 보내는 왕복은 통과한다(값이 같으면 변경이 아니다)
  ⑤ 발행 포인터는 이 PATCH로 바꿀 수 없다 — 포인터가 없을 때 채우는 것도, 있을 때 비우거나 바꾸는
     것도 409 `publish_pointer_owned`(포인터의 유일한 writer는 발행 게이트)
  ⑥ 대조군 — 포인터가 없는 문항은 종전대로 수정된다(과차단 방지)
  ⑦ 모든 PATCH가 행을 잠근다(낡은 포인터가 동시 발행의 포인터를 덮어쓰는 것과 판정 경쟁 방지)

실 PG 의미(실제 잠금·롤백·재적재)는 `tests/backend/db/test_published_problem_edit_guard_integration.py`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from whymath_backend.api._auth import require_content_admin
from whymath_backend.app import create_app
from whymath_backend.db.models.audit import PrivacyAudit
from whymath_backend.db.models.problem import Problem
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.published_edit_guard import SERVED_CONTENT_FIELDS
from whymath_backend.db.session import get_session
from whymath_backend.schema.enums import Curriculum, ReviewStatus, Role, SourceType, Subject
from whymath_backend.schema.problem import Problem as ProblemSchema

_ADMIN = UserProfile(user_id=uuid.uuid4(), role=Role.CONTENT_ADMIN)
_POINTER = uuid.uuid4()
#: 응답·로그에 값이 새지 않는지 보는 결함주입 표지 — 정답 자리에 넣는다.
_SENTINEL_ANSWER = "SENTINEL-EOS195-정답본문-5521"


def _problem(*, published: bool, status: ReviewStatus | None = ReviewStatus.approved) -> Problem:
    """자체생성 최소 문항 ORM — `published`면 발행 포인터를 달아 둔다."""
    problem = Problem.from_schema(
        ProblemSchema(
            source_type=SourceType.자체생성,
            curriculum_version=Curriculum.REVISION_2022,
            valid_from_year=2022,
            subject=Subject.미적분,
            unit_codes=["CAL-INT-DEF"],
            question_text="적분값을 구하시오",
            answer=_SENTINEL_ANSWER,
            review_status=status,
        )
    )
    if published:
        problem.problem_version_id = _POINTER
    return problem


class _Session:
    """라우터가 부르는 표면만 흉내내되 쓰기·커밋·잠금 인자를 전부 캡처한다."""

    def __init__(self, problem: Problem) -> None:
        self.problem = problem
        self.added: list[Any] = []
        self.merged: list[Any] = []
        self.commits = 0
        self.get_kwargs: list[dict[str, Any]] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def get(self, _model: Any, pk: uuid.UUID, **kwargs: Any) -> Problem | None:
        self.get_kwargs.append(kwargs)
        return self.problem if pk == self.problem.problem_id else None

    async def merge(self, obj: Any) -> Any:
        self.merged.append(obj)
        return obj

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None

    async def refresh(self, obj: Any) -> None:
        return None

    @property
    def audits(self) -> list[PrivacyAudit]:
        return [o for o in self.added if isinstance(o, PrivacyAudit)]


def _patch(fake: _Session, body: dict[str, Any]) -> Any:
    app = create_app()

    async def _override() -> AsyncIterator[_Session]:
        yield fake

    app.dependency_overrides[get_session] = _override
    app.dependency_overrides[require_content_admin] = lambda: _ADMIN
    return TestClient(app).patch(f"/v1/problems/{fake.problem.problem_id}", json=body)


def _assert_nothing_written(fake: _Session) -> None:
    assert fake.merged == [], "거부된 요청이 병합(쓰기)을 일으켰다"
    assert fake.audits == [], "거부된 요청이 감사 행을 남겼다"
    assert fake.commits == 0, "거부된 요청이 커밋했다"


# 필드마다 *현재 값과 다른* 유효한 새 값 — 스키마 재검증을 통과해야 가드가 판정 단계에 닿는다.
_CHANGES: dict[str, Any] = {
    "source_type": "AIHub",
    "subject": "확통",
    "curriculum_version": "2015_REVISION",
    "unit_codes": ["CAL-INT-DEF", "CAL-INT-APP"],
    "question_format": "서술형",
    "answer_format": "분수",
    "points": 4,
    "question_text": "다른 발문",
    "choices": ["1", "2", "3", "4", "5"],
    "answer": "다른 정답",
    "answer_explanation": "다른 해설",
    "difficulty_overall": 4.5,
}


def test_the_change_table_covers_every_served_field() -> None:
    """픽스처 자체의 변별력 — 서빙 내용 필드가 늘면 이 표도 늘어야 ②가 전수가 된다."""
    assert set(_CHANGES) == set(SERVED_CONTENT_FIELDS)


# ── ① ② 발행된 판이 있는 문항은 서빙 내용 변경이 막힌다 ──────────────────────────────────
@pytest.mark.parametrize("field", sorted(set(SERVED_CONTENT_FIELDS) - {"source_type"}))
def test_served_content_change_on_a_published_problem_is_blocked(field: str) -> None:
    fake = _Session(_problem(published=True))
    resp = _patch(fake, {field: _CHANGES[field]})
    # 스키마 재검증에서 먼저 422가 나면 가드에 닿지 못한 것이다 — 그건 이 테스트의 결함이다.
    assert resp.status_code == 409, f"{field}: {resp.status_code} {resp.text}"
    detail = resp.json()["detail"]
    assert detail["code"] == "published_version_edit_blocked"
    assert field in detail["fields"]
    _assert_nothing_written(fake)


def test_source_type_change_on_a_published_problem_is_blocked() -> None:
    """`source_type`은 저작권 레일의 근거라 판 payload에도 박힌다 — 바뀌면 판과 갈라진다."""
    fake = _Session(_problem(published=True))
    resp = _patch(fake, {"source_type": "AIHub"})
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["fields"] == ["source_type"]
    _assert_nothing_written(fake)


def test_blocked_response_names_fields_but_never_carries_values() -> None:
    """정답은 내부 전용이다 — 거부 응답이 값을 되돌려 주면 오류 메시지가 유출 경로가 된다."""
    fake = _Session(_problem(published=True))
    resp = _patch(fake, {"answer": "새 정답", "question_text": "새 발문"})
    assert resp.status_code == 409
    assert resp.json()["detail"]["fields"] == ["answer", "question_text"]
    assert _SENTINEL_ANSWER not in resp.text
    assert "새 정답" not in resp.text and "새 발문" not in resp.text


def test_blocked_message_names_the_way_out() -> None:
    """막기만 하고 길을 안 알려 주면 사람이 가드를 끈다 — 판 폐기 → 수정 → 새 판 발행."""
    fake = _Session(_problem(published=True))
    message = _patch(fake, {"answer": "새 정답"}).json()["detail"]["message"]
    assert "폐기" in message and "발행" in message


# ── ③ 긴급 정지는 열려 있다 ────────────────────────────────────────────────────────────
def test_quarantine_of_a_published_problem_is_still_allowed() -> None:
    """결함 문항은 즉시 내릴 수 있어야 한다 — 격리는 서빙 내용이 아니라 노출 축이다."""
    fake = _Session(_problem(published=True, status=ReviewStatus.approved))
    resp = _patch(fake, {"review_status": "quarantined", "quarantine_reason": "복수 정답"})
    assert resp.status_code == 200, resp.text
    assert len(fake.merged) == 1 and fake.commits == 1


def test_release_of_a_published_problem_is_still_allowed() -> None:
    fake = _Session(_problem(published=True, status=ReviewStatus.quarantined))
    resp = _patch(fake, {"review_status": "approved"})
    assert resp.status_code == 200, resp.text


# ── ④ 값이 같으면 변경이 아니다 ────────────────────────────────────────────────────────
def test_unchanged_value_round_trip_on_a_published_problem_is_allowed() -> None:
    """GET 본문을 그대로 되돌려 보내는 클라이언트를 막으면 PATCH 전체가 쓸 수 없어진다."""
    problem = _problem(published=True)
    fake = _Session(problem)
    resp = _patch(fake, problem.to_schema().model_dump(mode="json"))
    assert resp.status_code == 200, resp.text


def test_resending_the_same_answer_is_not_a_change() -> None:
    fake = _Session(_problem(published=True))
    assert _patch(fake, {"answer": _SENTINEL_ANSWER}).status_code == 200


# ── ⑤ 발행 포인터는 게이트만 바꾼다 ─────────────────────────────────────────────────────
def test_cannot_set_the_pointer_on_an_unpublished_problem() -> None:
    """게이트 밖에서 포인터를 채우면 판 없는 문항이 '발행됨'이 된다 — 키가 동적이라 AST는 못 본다."""
    fake = _Session(_problem(published=False))
    resp = _patch(fake, {"problem_version_id": str(uuid.uuid4())})
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "publish_pointer_owned"
    _assert_nothing_written(fake)


def test_cannot_clear_the_pointer_of_a_published_problem() -> None:
    fake = _Session(_problem(published=True))
    resp = _patch(fake, {"problem_version_id": None})
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "publish_pointer_owned"
    _assert_nothing_written(fake)


def test_cannot_repoint_the_pointer_of_a_published_problem() -> None:
    fake = _Session(_problem(published=True))
    resp = _patch(fake, {"problem_version_id": str(uuid.uuid4())})
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "publish_pointer_owned"
    _assert_nothing_written(fake)


def test_resending_the_current_pointer_is_not_a_change() -> None:
    fake = _Session(_problem(published=True))
    assert _patch(fake, {"problem_version_id": str(_POINTER)}).status_code == 200


# ── ⑥ 대조군 — 과차단 방지 ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("field", sorted(set(SERVED_CONTENT_FIELDS) - {"source_type"}))
def test_the_same_change_on_an_unpublished_problem_is_allowed(field: str) -> None:
    """같은 입력이 포인터만 없으면 통과한다 — 위 거부가 입력 탓이 아니라 가드 탓임을 증명한다."""
    fake = _Session(_problem(published=False))
    resp = _patch(fake, {field: _CHANGES[field]})
    assert resp.status_code == 200, f"{field}: {resp.status_code} {resp.text}"


# ── ⑦ 잠금 ─────────────────────────────────────────────────────────────────────────────
def test_every_patch_locks_the_row() -> None:
    fake = _Session(_problem(published=False))
    assert _patch(fake, {"answer": "다른 정답"}).status_code == 200
    assert fake.get_kwargs == [{"with_for_update": True, "populate_existing": True}]
