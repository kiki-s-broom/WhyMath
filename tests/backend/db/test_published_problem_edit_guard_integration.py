"""발행 문항 제자리 편집 차단 — 실 PostgreSQL 통합 (EOS-195 · WHYMATH_RUN_INTEGRATION).

hermetic 테스트가 못 보는 것 — **실제 행 잠금 아래의 쓰기 거부, `INSERT … ON CONFLICT DO UPDATE …
WHERE`의 SQL 의미, 리포트의 조인·키셋 SQL**을 실 DB로 확인한다. 응답 코드만 믿지 않고 `problem` 행을
별도 연결로 직접 읽는다. 모든 문항은 `create_draft → 제출 → 검토 → 승인 → 발행`의 **writer 경로**로
발행한다(판을 INSERT로 심지 않는다 — 심으면 게이트가 만드는 실제 payload·포인터와 다를 수 있다).

  A. 적재기: 발행된 문항은 재적재로 안 덮인다 · **`--overwrite-cms-edits`로도** 안 덮인다 · 같은 배치의
     미발행 문항(대조군)은 갱신된다 · 건너뜀은 `published_version_conflicts`로 보고되고 CMS 충돌과
     섞이지 않는다 · 판을 폐기하면 다시 적재된다
  B. `PATCH /v1/problems/{id}`: 서빙 내용 변경은 409로 막히고 DB가 그대로다 · 격리는 통과한다 ·
     포인터 변조는 409 · 폐기 후에는 같은 수정이 통과한다
  C. CMS `PATCH /v1/admin/cms/problem/items/{id}`: 발행된 문항은 409이고 DB가 그대로다
  D. 리포트: 발행 전 분모 0(측정 불성립) → 발행 직후 일치 → 우회 쓰기(직접 SQL) 뒤 어긋남 +
     필드 이름 · 키셋 페이지네이션(배치 크기 2로 5건)이 건수를 잃지 않는다

PG 미도달 또는 리비전 미적용이면 graceful skip. 만든 행만 지운다(공유 DB 보호). 정리 순서는
**포인터 NULL → 판 → 출처 원장·개념 연결 → 문항**이다(상호 FK).
"""

from __future__ import annotations

import asyncio
import dataclasses
import importlib.util
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from whymath_backend.api._auth import get_current_user, require_content_admin
from whymath_backend.app import create_app
from whymath_backend.config import Settings
from whymath_backend.db.models.user import UserProfile
from whymath_backend.harness import published_problem_drift_report as drift
from whymath_backend.l3 import problem_publish_gate as gate
from whymath_backend.schema.enums import Role
from whymath_backend.schema.version_header import TransitionAction

pytestmark = pytest.mark.integration

_A = TransitionAction
_ROOT = Path(__file__).resolve().parents[3]
_PROBLEM_CORPUS = _ROOT / "data" / "corpus" / "problem_bank_v1" / "problems.jsonl"
_ADMIN = UserProfile(user_id=uuid.uuid4(), role=Role.CONTENT_ADMIN)
_V1, _V2, _HUMAN = "코퍼스 v1 정답", "코퍼스 v2 정답", "사람이 고친 정답"
_META_PATH = _ROOT / "tests" / "backend" / "db" / "test_problem_version_publish_integration.py"
_META_HELPERS = ("_P", "_seed_complete_metadata", "_drop_metadata_seed")


def _load_meta() -> ModuleType:
    """P3-04 7필드 시드 헬퍼를 재사용한다 — 복제하면 "발행 가능한 문항"의 정의가 둘이 된다.

    발행 게이트(P3-04)는 문항 필수 7필드를 요구한다. 이 파일이 재는 것은 발행 이후의 편집 차단이지
    메타데이터가 아니므로, 발행 직전에 EOS-190 통합 테스트의 시드 헬퍼로 7필드를 채운다
    (EOS-194 통합 테스트 `_load_meta`와 같은 방식 · 페르소나 하네스 `_P`도 그 모듈의 것을 쓴다).
    """
    spec = importlib.util.spec_from_file_location("_eos195_meta_seed", _META_PATH)
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


def _settings() -> Settings:
    return Settings(jwt_secret_key=SecretStr("integration-jwt-secret-0123456789abcdef"))


def _sync_engine() -> Any:
    return create_engine(_settings().sync_database_url, poolclass=NullPool)


def _async_url() -> str:
    return str(_settings().database_url)


def _with_session(fn: Any) -> Any:
    """writer를 호출하는 코루틴을 실 AsyncSession으로 돌리고 commit한다(호출자 트랜잭션 경계)."""

    async def _run() -> Any:
        engine = create_async_engine(_async_url(), poolclass=NullPool)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                result = await fn(session)
                await session.commit()
                return result
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _read_only(fn: Any) -> Any:
    """읽기 전용 코루틴 — commit하지 않는다."""

    async def _run() -> Any:
        engine = create_async_engine(_async_url(), poolclass=NullPool)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await fn(session)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


@pytest.fixture
def engine() -> Iterator[Any]:
    eng = _sync_engine()
    try:
        with eng.connect() as conn:
            conn.execute(text("SELECT problem_version_id, cms_edited_at FROM problem LIMIT 0"))
    except Exception:
        eng.dispose()
        pytest.skip("PG 미도달 또는 리비전(problem_version·cms_edited_at) 미적용 — 통합 건너뜀")
    try:
        yield eng
    finally:
        eng.dispose()


class _Corpus:
    """적재기에 넣을 레코드를 만들고, 만든 slug를 정리한다."""

    def __init__(self, engine: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        from whymath_backend.l1.problem_bank.populate import (
            ProblemBankStore,
            load_problem_bank_records,
        )

        if not _PROBLEM_CORPUS.exists():
            pytest.skip(f"문제 코퍼스 미존재: {_PROBLEM_CORPUS}")
        self.engine = engine
        self.tag = uuid.uuid4().hex[:8]
        self.base = load_problem_bank_records(_PROBLEM_CORPUS)[0]
        self.store = ProblemBankStore(settings=_settings())
        # 개념 해석 맵은 이 시나리오의 관심사가 아니다 — 빈 맵으로 둔다.
        monkeypatch.setattr(self.store, "_load_source_id_to_concept_id", lambda: {})
        self.slugs: list[str] = []
        # 7필드 시드(P3-04) — 발행하는 문항에만 심고, 정리는 문항 삭제보다 먼저 한다.
        self._content: Any = None
        self._cid: uuid.UUID | None = None
        self._seeds: list[tuple[Any, uuid.UUID]] = []

    def make_publishable(self, problem_id: uuid.UUID) -> None:
        """발행 게이트의 7필드(P3-04)를 채운다 — 개념(PRIMARY)·스킬·해설·오개념·검증된 힌트."""
        if self._content is None:
            self._content, _journal = _M._P._begin("EOS-195")
            self._cid, _code = _M._P._seed_concept(self._content, "e195", "발행 편집 차단")
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO problem_concept (problem_id, concept_id, role) "
                    "VALUES (:p, :c, 'PRIMARY')"
                ),
                {"p": problem_id, "c": self._cid},
            )
        seed = _M._seed_complete_metadata(
            self._content.sfx,
            f"e195{len(self._seeds)}",
            self._cid,
            self._content.skill_ids[-1],
            [problem_id],
        )
        self._seeds.append((seed, problem_id))

    def slug(self, name: str) -> str:
        slug = f"it-eos195-{self.tag}-{name}"
        self.slugs.append(slug)
        return slug

    def rec(self, slug: str, answer: str) -> Any:
        problem = self.base.problem.model_copy(
            update={
                "problem_id": uuid.uuid4(),
                "slug": slug,
                "external_id": None,
                "answer": answer,
                "concept_ids": [],
            }
        )
        return dataclasses.replace(
            self.base, slug=slug, problem=problem, concept_tags=(), relations=()
        )

    def problem_id(self, slug: str) -> uuid.UUID:
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT problem_id FROM problem WHERE slug = :s"), {"s": slug}
            ).one()
        return row[0]  # type: ignore[no-any-return]

    def answer(self, slug: str) -> str | None:
        with self.engine.connect() as conn:
            return conn.execute(  # type: ignore[no-any-return]
                text("SELECT answer FROM problem WHERE slug = :s"), {"s": slug}
            ).scalar_one()

    def cleanup(self) -> None:
        """포인터·판 → 7필드 시드(힌트·풀이 경로·오개념) → 연결·원장·문항 → 개념·스킬 순서로 지운다."""
        try:
            with self.engine.connect() as conn:
                ids = [
                    r[0]
                    for r in conn.execute(
                        text("SELECT problem_id FROM problem WHERE slug = ANY(:s)"),
                        {"s": self.slugs},
                    )
                ]
            if ids:
                with self.engine.begin() as conn:
                    conn.execute(
                        text(
                            "UPDATE problem SET problem_version_id = NULL "
                            "WHERE problem_id = ANY(:i)"
                        ),
                        {"i": ids},
                    )
                    # 시도가 판을 FK로 잡는 시나리오는 이 파일에 없다.
                    conn.execute(
                        text("DELETE FROM problem_version WHERE problem_id = ANY(:i)"), {"i": ids}
                    )
            for seed, pid in self._seeds:
                _M._drop_metadata_seed(seed, [pid])  # 힌트 → 풀이 경로 → 오개념 행
            if ids:
                with self.engine.begin() as conn:
                    conn.execute(
                        text("DELETE FROM problem_concept WHERE problem_id = ANY(:i)"), {"i": ids}
                    )
                    conn.execute(
                        text("DELETE FROM content_provenance WHERE problem_id = ANY(:i)"),
                        {"i": ids},
                    )
                    conn.execute(text("DELETE FROM problem WHERE problem_id = ANY(:i)"), {"i": ids})
        finally:
            if self._content is not None:
                self._content.teardown()  # 학습자(멱등) → 개념·스킬(연결 행을 먼저 지웠다)


@pytest.fixture
def corpus(engine: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[_Corpus]:
    c = _Corpus(engine, monkeypatch)
    try:
        yield c
    finally:
        c.cleanup()


_PIPELINE = ((_A.SUBMIT, "author"), (_A.PASS_REVIEW, "reviewer"), (_A.APPROVE, "approver"))


def _publish(corpus: _Corpus, problem_id: uuid.UUID) -> uuid.UUID:
    """writer만 통과시켜 발행한다 — 7필드 시드(P3-04) → 초안 → 제출 → 검토 → 승인 → 발행."""
    corpus.make_publishable(problem_id)

    async def _go(session: AsyncSession) -> uuid.UUID:
        draft = await gate.create_draft(session, problem_id=problem_id, created_by="author")
        for action, actor in _PIPELINE:
            await gate.apply_transition(session, draft.version_id, action, actor=actor)
        await gate.apply_transition(session, draft.version_id, _A.PUBLISH, actor="publisher")
        return draft.version_id

    return _with_session(_go)  # type: ignore[no-any-return]


def _deprecate(version_id: uuid.UUID) -> None:
    async def _go(session: AsyncSession) -> None:
        await gate.apply_transition(session, version_id, _A.DEPRECATE, actor="publisher")

    _with_session(_go)


def _pointer(engine: Any, problem_id: uuid.UUID) -> uuid.UUID | None:
    with engine.connect() as conn:
        return conn.execute(  # type: ignore[no-any-return]
            text("SELECT problem_version_id FROM problem WHERE problem_id = :p"),
            {"p": problem_id},
        ).scalar_one()


def _row(engine: Any, problem_id: uuid.UUID) -> tuple[Any, ...]:
    """서빙 내용 + 검수 상태를 한 번에 — 거부된 요청이 DB를 건드리지 않았음을 통째로 대조한다."""
    with engine.connect() as conn:
        return tuple(
            conn.execute(
                text(
                    "SELECT answer, question_text, answer_explanation, difficulty_overall, "
                    "review_status::text, cms_edited_at IS NOT NULL, problem_version_id "
                    "FROM problem WHERE problem_id = :p"
                ),
                {"p": problem_id},
            ).one()
        )


# ── A. 적재기 ────────────────────────────────────────────────────────────────────────
def test_reload_does_not_overwrite_a_published_problem(engine: Any, corpus: _Corpus) -> None:
    published, control = corpus.slug("pub"), corpus.slug("ctl")
    report = corpus.store.populate([corpus.rec(published, _V1), corpus.rec(control, _V1)])
    assert report.problems_loaded == 2
    pid = corpus.problem_id(published)
    version_id = _publish(corpus, pid)
    assert _pointer(engine, pid) == version_id

    report = corpus.store.populate([corpus.rec(published, _V2), corpus.rec(control, _V2)])

    assert corpus.answer(published) == _V1, "발행된 문항이 재적재로 덮였다 — 판과 문항이 갈라졌다"
    assert corpus.answer(control) == _V2, "대조군(미발행)은 갱신돼야 한다 — 과차단 방지"
    assert report.problems_loaded == 1, "건너뛴 문항을 적재 건수에 세면 안 된다"
    assert report.published_version_conflicts == [f"problem:{published}"]
    assert report.cms_edit_conflicts == [], "발행 보호 건너뜀이 CMS 충돌로 섞였다"
    assert _pointer(engine, pid) == version_id, "재적재가 발행 포인터를 건드렸다"


def test_overwrite_flag_does_not_unlock_a_published_problem(engine: Any, corpus: _Corpus) -> None:
    """`--overwrite-cms-edits`는 '사람 편집을 감수'한다는 뜻이지 '판과 문항이 갈라져도 된다'가
    아니다. 옵션이 보호를 풀면 운영자가 편집 소실을 감수하려다 발행 판을 깬다."""
    slug = corpus.slug("pub")
    corpus.store.populate([corpus.rec(slug, _V1)])
    pid = corpus.problem_id(slug)
    _publish(corpus, pid)

    report = corpus.store.populate([corpus.rec(slug, _V2)], overwrite_cms_edits=True)

    assert corpus.answer(slug) == _V1
    assert report.problems_loaded == 0
    assert report.published_version_conflicts == [f"problem:{slug}"]


def test_cms_edited_and_published_problem_is_reported_as_published_conflict(
    engine: Any, corpus: _Corpus
) -> None:
    """두 보호가 겹치면 풀리지 않는 쪽(발행)으로 보고한다 — 덮어쓰기 옵션을 권하면 안 되기 때문."""
    slug = corpus.slug("both")
    corpus.store.populate([corpus.rec(slug, _V1)])
    pid = corpus.problem_id(slug)
    _publish(corpus, pid)
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE problem SET cms_edited_at = now() WHERE problem_id = :p"), {"p": pid}
        )

    report = corpus.store.populate([corpus.rec(slug, _V2)])

    assert report.published_version_conflicts == [f"problem:{slug}"]
    assert report.cms_edit_conflicts == []


def test_deprecating_the_version_reopens_reload(engine: Any, corpus: _Corpus) -> None:
    """폐기로 포인터가 비면 같은 재적재가 통과한다 — 막힘이 영구 잠금이 아니라 절차의 일부임."""
    slug = corpus.slug("pub")
    corpus.store.populate([corpus.rec(slug, _V1)])
    pid = corpus.problem_id(slug)
    version_id = _publish(corpus, pid)

    _deprecate(version_id)
    assert _pointer(engine, pid) is None
    report = corpus.store.populate([corpus.rec(slug, _V2)])

    assert corpus.answer(slug) == _V2
    assert report.problems_loaded == 1 and report.published_version_conflicts == []


# ── B. PATCH /v1/problems/{id} ───────────────────────────────────────────────────────
def _problems_client() -> TestClient:
    app = create_app()
    app.dependency_overrides[require_content_admin] = lambda: _ADMIN
    return TestClient(app)


def _published_problem(engine: Any, corpus: _Corpus) -> tuple[uuid.UUID, uuid.UUID]:
    slug = corpus.slug("pub")
    corpus.store.populate([corpus.rec(slug, _V1)])
    pid = corpus.problem_id(slug)
    # 승인 상태로 만든다 — 실제 서빙 중인 문항과 같은 조건이다.
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE problem SET review_status = 'approved' WHERE problem_id = :p"), {"p": pid}
        )
    return pid, _publish(corpus, pid)


def test_patch_cannot_change_served_content_of_a_published_problem(
    engine: Any, corpus: _Corpus
) -> None:
    pid, _version = _published_problem(engine, corpus)
    before = _row(engine, pid)
    with _problems_client() as client:
        resp = client.patch(f"/v1/problems/{pid}", json={"answer": _HUMAN})
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "published_version_edit_blocked"
    assert resp.json()["detail"]["fields"] == ["answer"]
    assert _row(engine, pid) == before, "거부된 요청이 DB를 건드렸다"


def test_patch_quarantine_of_a_published_problem_still_works(engine: Any, corpus: _Corpus) -> None:
    """결함 문항을 즉시 내릴 수 있어야 한다 — 그리고 격리가 발행 포인터를 건드리지 않는다."""
    pid, version_id = _published_problem(engine, corpus)
    with _problems_client() as client:
        resp = client.patch(
            f"/v1/problems/{pid}",
            json={"review_status": "quarantined", "quarantine_reason": "복수 정답 의심"},
        )
    assert resp.status_code == 200, resp.text
    assert _row(engine, pid)[4] == "quarantined"
    assert _pointer(engine, pid) == version_id, "격리가 발행 포인터를 지웠다"


def test_patch_cannot_forge_the_publish_pointer(engine: Any, corpus: _Corpus) -> None:
    """게이트 밖에서 포인터를 바꾸면 판 없는 문항이 '발행됨'이 된다 — 실제 DB에서도 막힌다."""
    slug = corpus.slug("unpub")
    corpus.store.populate([corpus.rec(slug, _V1)])
    pid = corpus.problem_id(slug)
    other_pid_slug = corpus.slug("other")
    corpus.store.populate([corpus.rec(other_pid_slug, _V1)])
    other_version = _publish(corpus, corpus.problem_id(other_pid_slug))

    with _problems_client() as client:
        resp = client.patch(f"/v1/problems/{pid}", json={"problem_version_id": str(other_version)})
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "publish_pointer_owned"
    assert _pointer(engine, pid) is None


def test_patch_is_allowed_after_the_version_is_deprecated(engine: Any, corpus: _Corpus) -> None:
    """수정 절차의 첫 단계(폐기) 뒤에는 같은 수정이 통과한다 — 대조군."""
    pid, version_id = _published_problem(engine, corpus)
    with _problems_client() as client:
        assert client.patch(f"/v1/problems/{pid}", json={"answer": _HUMAN}).status_code == 409
        _deprecate(version_id)
        resp = client.patch(f"/v1/problems/{pid}", json={"answer": _HUMAN})
    assert resp.status_code == 200, resp.text
    assert _row(engine, pid)[0] == _HUMAN


# ── C. CMS ──────────────────────────────────────────────────────────────────────────
def test_cms_patch_is_blocked_for_a_published_problem(engine: Any, corpus: _Corpus) -> None:
    pid, version_id = _published_problem(engine, corpus)
    # 승인된 채로는 '격리 먼저' 가드가 먼저 걸리므로, 판 보호만 보려고 격리한다.
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE problem SET review_status = 'quarantined', quarantine_reason = 'x', "
                "quarantined_at = now() WHERE problem_id = :p"
            ),
            {"p": pid},
        )
    before = _row(engine, pid)

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _ADMIN  # 권한 검사(RBAC)는 그대로 돈다
    with TestClient(app) as client:
        resp = client.patch(
            f"/v1/admin/cms/problem/items/{pid}", json={"changes": {"answer": _HUMAN}}
        )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "edit_blocked"
    assert "폐기" in resp.json()["detail"]["message"]
    assert _row(engine, pid) == before, "거부된 CMS 편집이 DB를 건드렸다"

    _deprecate(version_id)
    with TestClient(app) as client:
        resp = client.patch(
            f"/v1/admin/cms/problem/items/{pid}", json={"changes": {"answer": _HUMAN}}
        )
    assert resp.status_code == 200, resp.text
    assert _row(engine, pid)[0] == _HUMAN


# ── D. 리포트 ───────────────────────────────────────────────────────────────────────
def test_report_flow_unmeasurable_then_in_sync_then_drifted(engine: Any, corpus: _Corpus) -> None:
    """발행 전 → 발행 직후 → 우회 쓰기 뒤, 같은 리포트가 세 상태를 구분해 말한다."""
    slug = corpus.slug("rep")
    corpus.store.populate([corpus.rec(slug, _V1)])
    pid = corpus.problem_id(slug)

    def _mine(report: drift.DriftReport) -> bool:
        return any(s.problem_id == pid for s in report.samples)

    # 1) 발행 전 — 이 문항은 분모에 없다.
    before = _read_only(drift.collect_report)
    assert before.problems_total >= 1

    # 2) 발행 직후 — 분모에 들어가고 일치한다. 같은 DB의 다른 문항이 있을 수 있어 '증가분'을 본다.
    _publish(corpus, pid)
    synced = _read_only(drift.collect_report)
    assert synced.pointer_filled == before.pointer_filled + 1
    assert synced.in_sync == before.in_sync + 1
    assert synced.drifted == before.drifted
    assert synced.measurable is True

    # 3) 우회 쓰기 — 직접 SQL로 정답을 바꾼다(차단 두 경로 밖). 리포트가 필드 이름으로 잡는다.
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE problem SET answer = :a WHERE problem_id = :p"), {"a": _HUMAN, "p": pid}
        )
    drifted = _read_only(drift.collect_report)
    assert drifted.drifted == before.drifted + 1
    assert drifted.in_sync == before.in_sync
    assert _mine(drifted)
    sample = next(s for s in drifted.samples if s.problem_id == pid)
    assert sample.changed_fields == ("answer", "answer_hash")
    assert _HUMAN not in drift.render_report(drifted) and _HUMAN not in drift.dump_json(drifted)


def test_keyset_pagination_returns_every_pointer_filled_problem_once(
    engine: Any, corpus: _Corpus
) -> None:
    """배치 크기 2로 5건 — 건수를 잃거나 중복하지 않는다(실 SQL의 `problem_id >` 키셋 조건)."""
    ids: list[uuid.UUID] = []
    for n in range(5):
        slug = corpus.slug(f"pg{n}")
        corpus.store.populate([corpus.rec(slug, _V1)])
        pid = corpus.problem_id(slug)
        _publish(corpus, pid)
        ids.append(pid)

    async def _scan(session: AsyncSession) -> list[uuid.UUID]:
        return [p.problem.problem_id async for p in gate.iter_pointer_filled(session, batch_size=2)]

    scanned = _read_only(_scan)
    assert len(scanned) == len(set(scanned)), "페이지 경계에서 중복됐다"
    assert set(ids) <= set(scanned), "페이지 경계에서 일부를 잃었다"
    assert scanned == sorted(scanned), "problem_id 순서가 아니다(키셋 전제)"
