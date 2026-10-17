"""문항 판 발행 호출 표면 실 PostgreSQL 종단 간 — EOS-194 (`WHYMATH_RUN_INTEGRATION=1` + head 적용 PG).

hermetic 테스트(`test_admin_cms_problem_versions.py`)는 게이트를 스파이로 대체한다. 이 파일은
**대체하지 않는다**: 역할별 실제 JWT → 실제 `get_current_user`(DB 사용자 로드) → 실제 모듈 가드·권한
검사 → 실제 `problem_publish_gate`(행 잠금·전이표·게이트·해시) → 실제 감사 행까지 왕복하고, 그 뒤
**실제 학습자의 `POST /v1/me/attempts`가 `outcome=pinned`를 내는지**를 시도 행(`problem_attempt.
problem_version_id`)으로 확인한다. EOS-190은 게이트 함수를 직접 불러 이것을 보였고, 이 파일은 같은 것을
**운영자가 실제로 쓰는 표면(HTTP)만으로** 보인다 — 인수 조건 ③의 실행 증거다.

판정 기준은 응답 코드만이 아니다. 거부된 요청 뒤에는 **DB가 그대로인지**를 SQL로 직접 읽는다.

CI의 `backend-migrations` 잡은 `pytest -m integration --ignore=../../tests/backend/l3`을 돌리므로 이
파일(`tests/backend/api`)은 수집된다(`--collect-only`로 실측 — `l3` 하위에 두면 수집되지 않는다).

만든 행만 지운다(공유 DB 보호). 정리 순서: **학습자(시도) → 포인터 NULL → 판 → 감사 → CMS 사용자 → 문항**
— `problem_attempt.problem_version_id`와 `problem.problem_version_id`가 판을 FK로 잡고 있어 순서를 어기면
정리가 원래 단언 실패를 가린다.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import pathlib
import sys
import uuid
from collections.abc import Iterator
from types import ModuleType
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from whymath_backend.db.models.user import UserProfile
from whymath_backend.schema.enums import Persona, Role
from whymath_backend.schema.user import UserProfile as UserProfileSchema
from whymath_backend.security import create_access_token

pytestmark = pytest.mark.integration

_PIN_LOGGER = "whymath_backend.l2.attempt_version_pin"
_ROOT = pathlib.Path(__file__).resolve().parents[3]
_PERSONA_PATH = _ROOT / "tests" / "backend" / "api" / "test_e2e_persona_journeys.py"
_HELPERS = (
    "_attempt",
    "_begin",
    "_client",
    "_erase_learner",
    "_login",
    "_seed_concept",
    "_seed_problems",
    "_settings",
)


def _load() -> ModuleType:
    """페르소나 하네스를 재사용한다(재구현 0 — 서빙 경로와 같은 적재·인증 방식)."""
    spec = importlib.util.spec_from_file_location("_eos194_persona_harness", _PERSONA_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"페르소나 하네스 스펙 생성 실패: {_PERSONA_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    missing = [name for name in _HELPERS if not hasattr(module, name)]
    if missing:
        raise RuntimeError(f"페르소나 하네스 헬퍼가 사라졌다: {missing}")
    return module


_P = _load()

_META_PATH = _ROOT / "tests" / "backend" / "db" / "test_problem_version_publish_integration.py"
_META_HELPERS = ("_seed_complete_metadata", "_drop_metadata_seed")


def _load_meta() -> ModuleType:
    """P3-04 7필드 시드 헬퍼를 재사용한다 — 복제하면 "발행 가능한 문항"의 정의가 둘이 된다.

    발행 게이트(P3-04)는 문항 필수 7필드(난이도·스킬·개념·해설·정답·오개념 서명·힌트 전략)를
    요구한다. 이 표면은 게이트를 그대로 부르므로 시드 문항이 7필드를 채우지 못하면 발행이 422로
    거부된다 — 그 거부가 이 표면의 결함이 아니라 시드의 결함임을 구분하려면 "채워진 문항"의
    정의가 EOS-190 통합 테스트와 같은 한 곳이어야 한다.
    """
    spec = importlib.util.spec_from_file_location("_eos194_meta_seed", _META_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"7필드 시드 헬퍼 스펙 생성 실패: {_META_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    missing = [name for name in _META_HELPERS if not hasattr(module, name)]
    if missing:
        raise RuntimeError(f"7필드 시드 헬퍼가 사라졌다: {missing}")
    return module


_M = _load_meta()


def _load_runbook_sql() -> str:
    """운영 런북이 싣는 측정 SQL — hermetic 파일의 상수 한 벌(드리프트 가드가 그 파일에 있다)."""
    path = _ROOT / "tests" / "backend" / "api" / "test_admin_cms_problem_versions.py"
    spec = importlib.util.spec_from_file_location("_eos194_hermetic_for_sql", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"hermetic 테스트 스펙 생성 실패: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    sql = getattr(module, "EXPOSURE_COVERAGE_SQL", None)
    if not isinstance(sql, str):
        raise RuntimeError("EXPOSURE_COVERAGE_SQL 상수가 사라졌다")
    return sql


_RUNBOOK_SQL = _load_runbook_sql()


def _runbook_counts() -> dict[str, int]:
    """런북 SQL을 **글자 그대로** 실행한 결과 — 5개 열 이름과 값."""

    async def _run() -> dict[str, int]:
        engine = create_async_engine(_db_url())
        try:
            async with engine.connect() as conn:
                row = (await conn.execute(text(_RUNBOOK_SQL))).mappings().one()
                return {k: int(v) for k, v in row.items()}
        finally:
            await engine.dispose()

    return asyncio.run(_run())


# ── 공용 헬퍼 ────────────────────────────────────────────────────────────────────
def _db_url() -> str:
    return str(_P._settings().database_url)


def _rows(sql: str, params: dict[str, Any] | None = None) -> list[tuple[Any, ...]]:
    async def _run() -> list[tuple[Any, ...]]:
        engine = create_async_engine(_db_url())
        try:
            async with engine.connect() as conn:
                return [tuple(r) for r in (await conn.execute(text(sql), params or {})).all()]
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _exec(sql: str, params: dict[str, Any] | None = None) -> None:
    async def _run() -> None:
        engine = create_async_engine(_db_url())
        try:
            async with engine.begin() as conn:
                await conn.execute(text(sql), params or {})
        finally:
            await engine.dispose()

    asyncio.run(_run())


def _schema_ready() -> bool:
    """이 태스크가 기대는 스키마(CMS 역할 + 문항 판 테이블)가 적용된 DB인가."""
    try:
        role = _rows(
            "SELECT 1 FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
            "WHERE t.typname = 'role_enum' AND e.enumlabel = 'content_publisher'"
        )
        table = _rows("SELECT to_regclass('problem_version')")
    except Exception:
        return False
    return bool(role) and table[0][0] is not None


def _make_user(role: Role) -> uuid.UUID:
    uid = uuid.uuid4()

    async def _run() -> None:
        engine = create_async_engine(_db_url())
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                session.add(
                    UserProfile.from_schema(
                        UserProfileSchema(
                            user_id=uid, persona_primary=Persona.A_일반고고3, role=role
                        )
                    )
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())
    return uid


def _headers(uid: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(uid, settings=_P._settings())}"}


def _pointer(problem_id: uuid.UUID) -> uuid.UUID | None:
    return _rows("SELECT problem_version_id FROM problem WHERE problem_id = :p", {"p": problem_id})[
        0
    ][
        0
    ]  # type: ignore[no-any-return]


def _coverage(problem_ids: list[uuid.UUID]) -> tuple[int, int]:
    """(포인터가 채워진 노출 문항 수, 노출 문항 수) — 서빙 노출 게이트를 SQLAlchemy로 그대로 쓴다."""
    import sqlalchemy as sa

    from whymath_backend.db.models.problem import Problem
    from whymath_backend.l2.next_problem_selection import candidate_pool_conditions

    stmt = (
        sa.select(
            sa.func.count(),
            sa.func.count().filter(Problem.problem_version_id.isnot(None)),
        )
        .select_from(Problem)
        .where(*candidate_pool_conditions(), Problem.problem_id.in_(problem_ids))
    )

    async def _run() -> tuple[int, int]:
        engine = create_async_engine(_db_url())
        try:
            async with engine.connect() as conn:
                exposed, with_pointer = (await conn.execute(stmt)).one()
                return int(with_pointer), int(exposed)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _status(version_id: str) -> str:
    return str(
        _rows(
            "SELECT status::text FROM problem_version WHERE version_id = CAST(:v AS uuid)",
            {"v": version_id},
        )[0][0]
    )


def _attempt_pin(attempt_id: uuid.UUID) -> uuid.UUID | None:
    return _rows(
        "SELECT problem_version_id FROM problem_attempt WHERE attempt_id = :a",
        {"a": attempt_id},
    )[0][
        0
    ]  # type: ignore[no-any-return]


def _submit_attempt(client: Any, auth: dict[str, str], pid: uuid.UUID) -> uuid.UUID:
    body = _P._attempt(client, auth, pid, correct=True, answer="정답")
    return uuid.UUID(body["attempt_id"])


class _World:
    """학습자용 문항 n개 + CMS 사용자 3역할을 심고, 끝나면 의존 순서대로 정리한다."""

    def __init__(self, tag: str, difficulties: list[float]) -> None:
        self.content, _journal = _P._begin("EOS-194")
        cid, _code = _P._seed_concept(self.content, tag, "일차방정식의 풀이")
        self.pids: list[uuid.UUID] = _P._seed_problems(self.content, cid, tag, difficulties)
        self.meta = _M._seed_complete_metadata(
            self.content.sfx, tag, cid, self.content.skill_ids[-1], self.pids
        )
        self.users: dict[str, uuid.UUID] = {}

    def staff(self, name: str, role: Role) -> dict[str, str]:
        uid = _make_user(role)
        self.users[name] = uid
        return _headers(uid)

    def teardown(self) -> None:
        ids = [str(p) for p in self.pids]
        uids = [str(u) for u in self.users.values()]
        try:
            with _P._client() as client:
                _P._erase_learner(client)  # 시도 먼저(시도가 판을 FK로 잡는다)
        finally:
            try:
                _exec(
                    "UPDATE problem SET problem_version_id = NULL "
                    "WHERE problem_id = ANY(CAST(:i AS uuid[]))",
                    {"i": ids},
                )
                _exec(
                    "DELETE FROM problem_version WHERE problem_id = ANY(CAST(:i AS uuid[]))",
                    {"i": ids},
                )
                if uids:
                    _exec(
                        "DELETE FROM privacy_audit WHERE user_id = ANY(CAST(:u AS uuid[]))",
                        {"u": uids},
                    )
                    _exec(
                        "DELETE FROM user_profile WHERE user_id = ANY(CAST(:u AS uuid[]))",
                        {"u": uids},
                    )
            finally:
                try:
                    _M._drop_metadata_seed(self.meta, self.pids)  # 힌트→풀이 경로→오개념 행
                finally:
                    self.content.teardown()  # 학습자(멱등) → 문항 → 개념


@pytest.fixture
def world() -> Iterator[_World]:
    if not _schema_ready():
        pytest.skip(
            "PostgreSQL 미도달 또는 필요한 리비전 미적용 — 통합 테스트 건너뜀(통과가 아니다)"
        )
    w = _World("e194", [3.0, 3.4])
    try:
        yield w
    finally:
        w.teardown()


def _draft(client: Any, headers: dict[str, str], pid: uuid.UUID, **body: Any) -> Any:
    return client.post(f"/v1/admin/cms/problems/{pid}/drafts", headers=headers, json=body)


def _move(client: Any, headers: dict[str, str], version_id: str, action: str, expected: str) -> Any:
    return client.post(
        f"/v1/admin/cms/problem-versions/{version_id}/transitions",
        headers=headers,
        json={"action": action, "expected_status": expected},
    )


def _drive_to_approved(
    client: Any, editor: dict[str, str], reviewer: dict[str, str], pid: uuid.UUID
) -> str:
    created = _draft(client, editor, pid, reason="EOS-194 통합")
    assert created.status_code == 201, created.text
    version_id = str(created.json()["version_id"])
    for headers, action, expected, want in (
        (editor, "submit", "DRAFT", "IN_REVIEW"),
        (reviewer, "pass_review", "IN_REVIEW", "IN_QA"),
        (reviewer, "approve", "IN_QA", "APPROVED"),
    ):
        resp = _move(client, headers, version_id, action, expected)
        assert resp.status_code == 200, (action, resp.text)
        assert resp.json()["status"] == want
    return version_id


# ── A. 인수 조건 ③ — 운영 표면만으로 발행하면 실제 시도가 pinned가 된다 ──────────────────
def test_publishing_through_the_cms_surface_makes_real_attempts_pinned(
    world: _World, caplog: pytest.LogCaptureFixture
) -> None:
    target, sibling = world.pids
    editor = world.staff("editor", Role.CONTENT_EDITOR)
    reviewer = world.staff("reviewer", Role.CONTENT_REVIEWER)
    publisher = world.staff("publisher", Role.CONTENT_PUBLISHER)

    with _P._client() as client:
        _P._erase_learner(client)
        learner = _P._login(client)

        # ① 대조군 — 발행 전 시도는 NULL이다(판 없는 문항에 판을 날조하지 않는다).
        caplog.set_level(logging.INFO, logger=_PIN_LOGGER)
        before = _submit_attempt(client, learner, target)
        assert _attempt_pin(before) is None
        assert "outcome=no_version" in caplog.text

        runbook_before = _runbook_counts()

        # ② 세 역할이 HTTP만으로 초안 → 제출 → 검토 → 승인 → 발행. 그 사이 포인터는 비어 있다.
        version_id = _drive_to_approved(client, editor, reviewer, target)
        assert _status(version_id) == "APPROVED"
        assert _pointer(target) is None, "발행 전에 포인터가 움직였다"
        published = _move(client, publisher, version_id, "publish", "APPROVED")
        assert published.status_code == 200, published.text
        assert published.json()["status"] == "PUBLISHED"
        assert _status(version_id) == "PUBLISHED"
        assert _pointer(target) == uuid.UUID(version_id), "발행이 문항 포인터를 옮기지 않았다"

        # ③ 발행 뒤 시도 — 같은 실제 경로가 이제 판 id를 시도 행에 박는다.
        caplog.clear()
        after = _submit_attempt(client, learner, target)
        assert _attempt_pin(after) == uuid.UUID(version_id)
        assert "outcome=pinned" in caplog.text
        assert f"problem_version_id={version_id}" in caplog.text

        # ④ 대조군 — 발행하지 않은 형제 문항은 계속 NULL이다(일괄 적용이 아니다).
        sib_attempt = _submit_attempt(client, learner, sibling)
        assert _attempt_pin(sib_attempt) is None
        # ⑤ 대조군 — 발행이 과거 기록을 소급해 고치지 않는다.
        assert _attempt_pin(before) is None

        # ⑥ 작동한 비율 — 이 월드에서 "발행 표면이 포인터를 채운 문항 수 / 서빙 노출 문항 수".
        #    분모의 '노출'은 서빙 후보 풀의 WHERE(`candidate_pool_conditions`) 그대로다.
        with_pointer, exposed = _coverage(world.pids)
        print(f"EOS194_POINTER_COVERAGE={with_pointer}/{exposed}")
        assert (with_pointer, exposed) == (1, 2)

        # ⑥-b 운영 런북 SQL(글자 그대로) — 발행 전후 증분이 분모는 0, 분자·발행 판은 +1이다.
        #     (공유 DB의 다른 행과 무관하게 증분으로 본다.)
        runbook_after = _runbook_counts()
        delta = {k: runbook_after[k] - runbook_before[k] for k in runbook_after}
        assert delta == {
            "total_problems": 0,
            "exposed": 0,
            "exposed_with_pointer": 1,
            "any_with_pointer": 1,
            "published_versions": 1,
        }, delta

        # ⑦ 감사 — 전이 1건마다 정확히 1행, 행위자는 그 전이를 한 역할의 사용자다.
        audit = _rows(
            "SELECT action, user_id FROM privacy_audit "
            "WHERE resource_type = 'problem_version' AND resource_id = CAST(:v AS uuid)",
            {"v": version_id},
        )
        by_action = {a: u for a, u in audit}
        assert len(audit) == 5 == len(by_action), audit
        assert by_action == {
            "create": world.users["editor"],
            "submit": world.users["editor"],
            "pass_review": world.users["reviewer"],
            "approve": world.users["reviewer"],
            "publish": world.users["publisher"],
        }

        # ⑧ 이력 — 목록과 상세가 같은 판을 말하고, 상세에 두 게이트 통과 기록이 남는다.
        listed = client.get(f"/v1/admin/cms/problems/{target}/versions", headers=publisher)
        assert listed.status_code == 200, listed.text
        assert [v["version_id"] for v in listed.json()] == [version_id]
        assert listed.json()[0]["allowed_actions"] == ["deprecate"]
        detail = client.get(f"/v1/admin/cms/problem-versions/{version_id}", headers=editor)
        assert detail.status_code == 200, detail.text
        assert [r["gate"] for r in detail.json()["gate_records"]] == ["qa", "publish"]


# ── B. 권한 거부는 실제 스택에서도 DB를 바꾸지 않는다 ───────────────────────────────────
def test_wrong_role_is_refused_and_leaves_the_database_untouched(world: _World) -> None:
    target, _sibling = world.pids
    editor = world.staff("editor", Role.CONTENT_EDITOR)
    reviewer = world.staff("reviewer", Role.CONTENT_REVIEWER)
    publisher = world.staff("publisher", Role.CONTENT_PUBLISHER)

    with _P._client() as client:
        version_id = _drive_to_approved(client, editor, reviewer, target)
        audit_before = _rows(
            "SELECT count(*) FROM privacy_audit WHERE resource_id = CAST(:v AS uuid)",
            {"v": version_id},
        )[0][0]

        # 편집자·검수자는 발행할 수 없다 — 지시문 검증 ①을 실제 스택에서 본다.
        for headers in (editor, reviewer):
            resp = _move(client, headers, version_id, "publish", "APPROVED")
            assert resp.status_code == 403, resp.text
            assert resp.json()["detail"]["code"] == "capability_required"
        # 배포자는 초안을 만들 수 없다.
        resp = _draft(client, publisher, target)
        assert resp.status_code == 403
        # 학생(일반 사용자)은 모듈 가드에서 막힌다.
        learner = _P._login(client)
        assert (
            client.get(f"/v1/admin/cms/problems/{target}/versions", headers=learner).status_code
            == 403
        )
        assert _move(client, learner, version_id, "publish", "APPROVED").status_code == 403

        assert _status(version_id) == "APPROVED", "거부된 요청이 상태를 바꿨다"
        assert _pointer(target) is None, "거부된 요청이 포인터를 옮겼다"
        audit_after = _rows(
            "SELECT count(*) FROM privacy_audit WHERE resource_id = CAST(:v AS uuid)",
            {"v": version_id},
        )[0][0]
        assert audit_after == audit_before, "거부된 요청이 감사 행을 남겼다"

        # 대조군 — 그 배포자는 같은 판을 정상적으로 발행한다(거부가 과잉이 아니다).
        ok = _move(client, publisher, version_id, "publish", "APPROVED")
        assert ok.status_code == 200, ok.text
        assert _pointer(target) == uuid.UUID(version_id)
        _P._erase_learner(client)


# ── C. 승인 뒤 라이브 문항이 바뀌면 발행이 422로 거부된다(live_content_current) ─────────
def test_publish_is_refused_422_when_the_live_problem_changed_after_approval(world: _World) -> None:
    target, _sibling = world.pids
    editor = world.staff("editor", Role.CONTENT_EDITOR)
    reviewer = world.staff("reviewer", Role.CONTENT_REVIEWER)
    publisher = world.staff("publisher", Role.CONTENT_PUBLISHER)

    with _P._client() as client:
        version_id = _drive_to_approved(client, editor, reviewer, target)
        _exec(
            "UPDATE problem SET answer = :a WHERE problem_id = :p", {"a": "정정된정답", "p": target}
        )

        resp = _move(client, publisher, version_id, "publish", "APPROVED")
        assert resp.status_code == 422, resp.text
        detail = resp.json()["detail"]
        assert detail["code"] == "gate_failed"
        assert any(f.startswith("live_content_current") for f in detail["failures"]), detail
        assert _status(version_id) == "APPROVED" and _pointer(target) is None

        # 과잉 거부가 아니다 — 새 초안(정정된 내용의 스냅숏)은 같은 표면으로 발행된다.
        v2 = _drive_to_approved(client, editor, reviewer, target)
        assert v2 != version_id
        assert _move(client, publisher, v2, "publish", "APPROVED").status_code == 200
        assert _pointer(target) == uuid.UUID(v2)
        _P._erase_learner(client)


# ── D. 재발행 — 옛 발행본이 내려가고 포인터가 이동한다 / 낡은 expected_status는 409 ──────
def test_republish_via_the_surface_moves_the_pointer_and_stale_status_is_409(world: _World) -> None:
    target, _sibling = world.pids
    editor = world.staff("editor", Role.CONTENT_EDITOR)
    reviewer = world.staff("reviewer", Role.CONTENT_REVIEWER)
    publisher = world.staff("publisher", Role.CONTENT_PUBLISHER)

    with _P._client() as client:
        v1 = _drive_to_approved(client, editor, reviewer, target)
        assert _move(client, publisher, v1, "publish", "APPROVED").status_code == 200

        v2 = _drive_to_approved(client, editor, reviewer, target)
        assert _move(client, publisher, v2, "publish", "APPROVED").status_code == 200
        assert _status(v1) == "DEPRECATED" and _status(v2) == "PUBLISHED"
        assert _pointer(target) == uuid.UUID(v2)
        versions = client.get(f"/v1/admin/cms/problems/{target}/versions", headers=editor).json()
        assert [v["version_no"] for v in versions] == [2, 1], "최신 판부터"

        # 낡은 화면: 이미 PUBLISHED인 판을 APPROVED로 알고 publish → 409, 아무 것도 쓰이지 않는다.
        audit_before = _rows(
            "SELECT count(*) FROM privacy_audit WHERE resource_id = CAST(:v AS uuid)", {"v": v2}
        )[0][0]
        stale = _move(client, publisher, v2, "publish", "APPROVED")
        assert stale.status_code == 409, stale.text
        assert stale.json()["detail"]["code"] == "stale_status"
        assert stale.json()["detail"]["current_status"] == "PUBLISHED"
        assert _pointer(target) == uuid.UUID(v2)
        assert (
            _rows(
                "SELECT count(*) FROM privacy_audit WHERE resource_id = CAST(:v AS uuid)", {"v": v2}
            )[0][0]
            == audit_before
        )

        # 발행본 내리기 — 포인터가 비고, 새 시도는 다시 NULL이다.
        assert _move(client, publisher, v2, "deprecate", "PUBLISHED").status_code == 200
        assert _pointer(target) is None
        _P._erase_learner(client)


# ── E. 없는 문항·판 ────────────────────────────────────────────────────────────────────
def test_unknown_ids_are_404(world: _World) -> None:
    editor = world.staff("editor", Role.CONTENT_EDITOR)
    ghost = uuid.uuid4()
    with _P._client() as client:
        assert _draft(client, editor, ghost).status_code == 404
        assert (
            client.get(f"/v1/admin/cms/problems/{ghost}/versions", headers=editor).status_code
            == 404
        )
        assert (
            client.get(f"/v1/admin/cms/problem-versions/{ghost}", headers=editor).status_code == 404
        )
        assert _move(client, editor, str(ghost), "submit", "DRAFT").status_code == 404
