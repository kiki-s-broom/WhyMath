"""문항 발행 경로(problem_version 유일 writer) 실 PostgreSQL 통합 테스트 — EOS-190 (WHYMATH_RUN_INTEGRATION).

EOS-47은 시도 접수 때 `problem.problem_version_id`를 시도 행에 복사하지만, 그 포인터를 채우는 운영
writer가 없어 값이 전부 NULL이었다. 이 파일은 **writer가 생긴 뒤 고정이 실제로 일하는가**를 실 PG와
**실제 HTTP 경로**(`POST /v1/me/attempts`)로 확인한다:

  A. (acceptance ②) 발행 전 시도는 NULL / 발행 후 시도는 그 판 id + 로그 `outcome=pinned` /
     발행하지 않은 형제 문항은 계속 NULL. — 판을 `INSERT`로 심지 않고 writer(`create_draft` →
     전이표 4전이 → 포인터 전환)를 통과시켜 만든다. 고정이 '모든 문항에 일괄 적용'이 아님도 보인다.
  B. 재발행이 포인터를 옮기고 옛 판을 DEPRECATED로 내리되, 옛 시도는 옛 판을 계속 가리킨다.
  C. 승인 뒤 라이브 문항이 바뀌면 발행이 거부되고 아무 것도 쓰이지 않는다(`live_content_current`).
  D. 발행본을 내리면 포인터가 비워진다. 낡은 상태 기대는 거부되고 아무 것도 쓰이지 않는다.
  E. **코퍼스 재적재가 발행 포인터를 지우지 않는다** — 적재기는 `ON CONFLICT DO UPDATE` 집합을
     mapper에서 동적으로 뽑아 포인터까지 코퍼스 값(None)으로 덮어쓰고 있었다. writer가 0건이던 동안은
     덮을 값이 없어 무해했고, 첫 writer가 생기는 순간 현실이 되는 결함이다(AST 스캔은 못 본다).

  F. (P3-04) **7필드 집행** — 실제 행을 하나씩 망가뜨리면 발행이 거부되고 아무 것도 쓰이지 않으며,
     고치면 같은 경로로 발행된다. 오개념 서명은 슬롯별 규칙(트리거 슬롯은 문항 자체 연결 필수)을 본다.

PG 미도달 또는 리비전 미적용이면 graceful skip. 만든 행만 지운다(공유 DB 보호). 정리 순서는
**학습자(시도) → 포인터 NULL → 판 → 문항**이다 — `problem_attempt.problem_version_id`와
`problem.problem_version_id`가 판을 FK로 잡고 있어 순서를 어기면 정리가 원래 단언 실패를 가린다.
"""

from __future__ import annotations

import asyncio
import dataclasses
import importlib.util
import logging
import pathlib
import sys
import uuid
from types import ModuleType
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from whymath_backend.config import Settings
from whymath_backend.l3 import problem_publish_gate as gate
from whymath_backend.l3.problem_metadata_evidence import load_metadata_evidence
from whymath_backend.l3.publish_gate import PublishGateError, StaleStatusError
from whymath_backend.schema.problem_metadata import (
    FieldState,
    ProblemMetadataField,
    evaluate_metadata,
)
from whymath_backend.schema.version_header import TransitionAction, VersionStatus

pytestmark = pytest.mark.integration

_A = TransitionAction
_PIN_LOGGER = "whymath_backend.l2.attempt_version_pin"
_ROOT = pathlib.Path(__file__).resolve().parents[3]
_PERSONA_PATH = _ROOT / "tests" / "backend" / "api" / "test_e2e_persona_journeys.py"
_PROBLEM_CORPUS = _ROOT / "data" / "corpus" / "problem_bank_v1" / "problems.jsonl"
_HELPERS = (
    "_attempt",
    "_begin",
    "_client",
    "_erase_learner",
    "_get",
    "_login",
    "_seed_concept",
    "_seed_problems",
    "_settings",
)


def _load() -> ModuleType:
    """페르소나 하네스를 재사용한다(재구현 0 — 서빙 경로와 같은 적재·인증 방식)."""
    spec = importlib.util.spec_from_file_location("_eos190_persona_harness", _PERSONA_PATH)
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


def _with_session(fn: Any) -> Any:
    """writer를 호출하는 코루틴을 실 AsyncSession으로 돌리고 commit한다(호출자 트랜잭션 경계)."""

    async def _run() -> Any:
        engine = create_async_engine(_db_url())
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                result = await fn(session)
                await session.commit()
                return result
        finally:
            await engine.dispose()

    return asyncio.run(_run())


_PIPELINE = (
    (_A.SUBMIT, "author"),
    (_A.PASS_REVIEW, "reviewer"),
    (_A.APPROVE, "approver"),
)


async def _approved_draft(session: AsyncSession, problem_id: uuid.UUID) -> uuid.UUID:
    draft = await gate.create_draft(session, problem_id=problem_id, created_by="author")
    for action, actor in _PIPELINE:
        await gate.apply_transition(session, draft.version_id, action, actor=actor)
    return draft.version_id


def _publish(problem_id: uuid.UUID) -> uuid.UUID:
    """writer만 통과시켜 발행한다 — 초안 → 제출 → 검토 → 승인 → 발행."""

    async def _go(session: AsyncSession) -> uuid.UUID:
        version_id = await _approved_draft(session, problem_id)
        await gate.apply_transition(session, version_id, _A.PUBLISH, actor="publisher")
        return version_id

    return _with_session(_go)  # type: ignore[no-any-return]


def _pointer(problem_id: uuid.UUID) -> uuid.UUID | None:
    rows = _rows("SELECT problem_version_id FROM problem WHERE problem_id = :p", {"p": problem_id})
    return rows[0][0]  # type: ignore[no-any-return]


def _status(version_id: uuid.UUID) -> str:
    rows = _rows(
        "SELECT status::text FROM problem_version WHERE version_id = :v", {"v": version_id}
    )
    return str(rows[0][0])


def _attempt_pin(attempt_id: uuid.UUID) -> tuple[uuid.UUID | None, str | None]:
    rows = _rows(
        "SELECT problem_version_id, evaluation_context->>'curriculum_version' "
        "FROM problem_attempt WHERE attempt_id = :a",
        {"a": attempt_id},
    )
    return rows[0]  # type: ignore[return-value]


def _drop_versions(problem_ids: list[uuid.UUID]) -> None:
    """포인터를 끊고 판을 지운다 — 문항 삭제보다 먼저(상호 FK)."""
    ids = [str(p) for p in problem_ids]
    _exec(
        "UPDATE problem SET problem_version_id = NULL WHERE problem_id = ANY(CAST(:i AS uuid[]))",
        {"i": ids},
    )
    _exec(
        "DELETE FROM problem_version WHERE problem_id = ANY(CAST(:i AS uuid[]))",
        {"i": ids},
    )


@dataclasses.dataclass(frozen=True)
class _MetaSeed:
    """7필드를 채우려고 심은 보조 행 — 정리 대상과 복구에 필요한 값을 나른다."""

    cid: uuid.UUID
    src_id: str
    mis_id: str
    skill_id: str
    path_ids: tuple[str, ...]


_SOLUTION_TEXT = "양변에서 상수항을 빼서 x를 구한다."
_HINT_SQL = (
    "INSERT INTO hints (hint_id, solution_path_id, step_order, problem_id, level, content, "
    "reveal_score, verified, generator_version) "
    "VALUES (:h, :sp, 1, :p, 1, '개념 이름을 떠올려 보자', 0.1, true, 'p3-04-test')"
)


def _seed_complete_metadata(
    sfx: str, tag: str, cid: uuid.UUID, skill_id: str, pids: list[uuid.UUID]
) -> _MetaSeed:
    """시드 문항을 7필드 충족으로 만든다 — 해설·개념의 원천 키·소속 개념 오개념·검증된 힌트.

    페르소나 하네스가 이미 난이도·정답·개념(PRIMARY)·스킬(레지스트리 포함)을 심으므로 모자란 것만
    더한다. 슬롯 태그는 달지 않는다 → 오개념 서명은 개념 상속으로 인정된다.
    """
    src_id = f"H:p304-{sfx}-{tag}"
    mis_id = f"M9{uuid.uuid4().int % 10**6:06d}"  # M-id 형태 — distractor 경로(카탈로그 조회)용
    _exec("UPDATE concept SET source_id = :s WHERE concept_id = :c", {"s": src_id, "c": cid})
    _exec(
        "INSERT INTO misconception_catalog (mis_id, concept_src_id) VALUES (:m, :s)",
        {"m": mis_id, "s": src_id},
    )
    path_ids: list[str] = []
    for i, pid in enumerate(pids):
        _exec(
            "UPDATE problem SET answer_explanation = :e WHERE problem_id = :p",
            {"e": _SOLUTION_TEXT, "p": pid},
        )
        path_id = f"sp-p304-{sfx}{tag}{i}"
        _exec(
            "INSERT INTO solution_paths (solution_path_id, problem_id, approach_type) "
            "VALUES (:sp, :p, 'p3-04-test')",
            {"sp": path_id, "p": pid},
        )
        _exec(_HINT_SQL, {"h": f"hint-{path_id}", "sp": path_id, "p": pid})
        path_ids.append(path_id)
    return _MetaSeed(cid, src_id, mis_id, skill_id, tuple(path_ids))


def _drop_metadata_seed(seed: _MetaSeed, pids: list[uuid.UUID]) -> None:
    """힌트 → 풀이 경로 → 오개념 행 순서로 지운다 — 문항 삭제보다 먼저(FK는 NO ACTION)."""
    ids = [str(p) for p in pids]
    _exec("DELETE FROM hints WHERE problem_id = ANY(CAST(:i AS uuid[]))", {"i": ids})
    _exec("DELETE FROM solution_paths WHERE problem_id = ANY(CAST(:i AS uuid[]))", {"i": ids})
    _exec("DELETE FROM misconception_catalog WHERE mis_id = :m", {"m": seed.mis_id})


class _Scenario:
    """학습자 1명 + 7필드가 채워진 문항 n개를 심고, 끝나면 의존 순서대로 정리한다."""

    def __init__(self, tag: str, difficulties: list[float]) -> None:
        self.content, _journal = _P._begin("EOS-190")
        cid, _code = _P._seed_concept(self.content, tag, "일차방정식의 풀이")
        self.cid = cid
        self.pids: list[uuid.UUID] = _P._seed_problems(self.content, cid, tag, difficulties)
        self.meta = _seed_complete_metadata(
            self.content.sfx, tag, cid, self.content.skill_ids[-1], self.pids
        )

    def teardown(self) -> None:
        try:
            with _P._client() as client:
                _P._erase_learner(client)  # 시도 먼저(시도가 판을 FK로 잡는다)
        finally:
            try:
                _drop_versions(self.pids)
            finally:
                try:
                    _drop_metadata_seed(self.meta, self.pids)
                finally:
                    self.content.teardown()  # 학습자(멱등) → 문항 → 개념


def _submit(client: Any, auth: dict[str, str], pid: uuid.UUID) -> uuid.UUID:
    body = _P._attempt(client, auth, pid, correct=True, answer="정답")
    return uuid.UUID(body["attempt_id"])


# ── A. acceptance ② — 실제 submit_attempt 경로가 pinned를 낸다 ─────────────────────
def test_published_problem_is_pinned_by_the_real_submit_attempt_route(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sc = _Scenario("e190a", [3.0, 3.4])
    target, sibling = sc.pids
    try:
        with _P._client() as client:
            _P._erase_learner(client)
            auth = _P._login(client)

            # ① 대조군 — 발행 전 시도는 NULL이다(판 없는 문항에 판을 날조하지 않는다).
            caplog.set_level(logging.INFO, logger=_PIN_LOGGER)
            before = _submit(client, auth, target)
            assert _attempt_pin(before)[0] is None
            assert "outcome=no_version" in caplog.text

            # ② writer 통과 발행 — INSERT로 심지 않는다.
            version_id = _publish(target)
            assert _status(version_id) == VersionStatus.PUBLISHED.value
            assert _pointer(target) == version_id, "발행이 문항 포인터를 옮기지 않았다"

            # ③ 발행 뒤 시도 — 같은 실제 경로가 이제 판 id를 시도 행에 박는다.
            caplog.clear()
            after = _submit(client, auth, target)
            pinned_version, curriculum = _attempt_pin(after)
            assert pinned_version == version_id, "발행된 문항인데 시도에 판 id가 박히지 않았다"
            assert curriculum == "2022_REVISION", "채점 환경 스냅숏도 함께 박혀야 한다"
            assert "outcome=pinned" in caplog.text
            assert f"problem_version_id={version_id}" in caplog.text

            # ④ 대조군 — 발행하지 않은 형제 문항은 계속 NULL이다(일괄 적용이 아니다).
            sib_attempt = _submit(client, auth, sibling)
            assert _attempt_pin(sib_attempt)[0] is None

            # ⑤ 대조군 — 발행이 과거 기록을 소급해 고치지 않는다(이전 시도는 NULL 그대로).
            assert _attempt_pin(before)[0] is None
    finally:
        sc.teardown()


# ── B. 재발행 — 포인터 이동 + 옛 시도는 옛 판을 가리킨다 ─────────────────────────────
def test_republish_moves_pointer_and_old_attempts_keep_their_version() -> None:
    sc = _Scenario("e190b", [3.0])
    (pid,) = sc.pids
    try:
        with _P._client() as client:
            _P._erase_learner(client)
            auth = _P._login(client)

            v1 = _publish(pid)
            old_attempt = _submit(client, auth, pid)
            assert _attempt_pin(old_attempt)[0] == v1

            # 문항을 고친다(정답 정정) → 새 초안은 *고친 뒤* 라이브 내용을 스냅숏한다.
            _exec(
                "UPDATE problem SET answer = :a WHERE problem_id = :p",
                {"a": "정정된정답", "p": pid},
            )
            v2 = _publish(pid)
            assert v2 != v1

            assert _status(v1) == VersionStatus.DEPRECATED.value, "옛 발행본이 내려가지 않았다"
            assert _status(v2) == VersionStatus.PUBLISHED.value
            assert _pointer(pid) == v2
            # 버전 체인 — 수정은 새 판이고 직전 판을 가리킨다(번호는 문항 안에서 1부터 증가).
            assert _rows(
                "SELECT version_no, previous_version_id FROM problem_version WHERE version_id = :v",
                {"v": v2},
            ) == [(2, v1)]

            # 핵심 — 옛 시도는 여전히 v1을 가리키고, v1 payload는 정정 전 모습 그대로다.
            assert _attempt_pin(old_attempt)[0] == v1
            v1_answer = _rows(
                "SELECT payload->>'answer' FROM problem_version WHERE version_id = :v", {"v": v1}
            )[0][0]
            v2_answer = _rows(
                "SELECT payload->>'answer' FROM problem_version WHERE version_id = :v", {"v": v2}
            )[0][0]
            assert v1_answer != "정정된정답", "v1 payload가 정정 뒤 내용으로 오염됐다"
            assert v2_answer == "정정된정답"

            # 대조군 — 정정 뒤 새 시도는 v2를 가리킨다(고정이 '영원히 v1'이 아니다).
            new_attempt = _submit(client, auth, pid)
            assert _attempt_pin(new_attempt)[0] == v2
    finally:
        sc.teardown()


# ── C. live_content_current — 승인 뒤 라이브가 바뀌면 발행 거부 ─────────────────────
def test_publish_is_refused_when_live_problem_changed_after_approval() -> None:
    sc = _Scenario("e190c", [3.0])
    (pid,) = sc.pids
    try:
        version_id = _with_session(lambda s: _approved_draft(s, pid))
        assert _status(version_id) == VersionStatus.APPROVED.value

        # 승인 이후 CMS가 정답을 고쳤다(다른 트랜잭션에서 커밋).
        _exec("UPDATE problem SET answer = :a WHERE problem_id = :p", {"a": "승인뒤수정", "p": pid})

        qa_records_before = _rows(
            "SELECT jsonb_array_length(qa->'records') FROM problem_version WHERE version_id = :v",
            {"v": version_id},
        )[0][0]

        with pytest.raises(PublishGateError, match="live_content_current"):
            _with_session(
                lambda s: gate.apply_transition(s, version_id, _A.PUBLISH, actor="publisher")
            )

        # 아무 것도 쓰이지 않았다 — 상태·포인터·QA 기록 그대로.
        assert _status(version_id) == VersionStatus.APPROVED.value
        assert _pointer(pid) is None
        qa_records_after = _rows(
            "SELECT jsonb_array_length(qa->'records') FROM problem_version WHERE version_id = :v",
            {"v": version_id},
        )[0][0]
        assert qa_records_after == qa_records_before

        # 대조군 — 새 초안(고친 뒤 내용)은 같은 경로로 발행된다. 거부가 '문항 전체 차단'이 아니다.
        fresh = _publish(pid)
        assert _pointer(pid) == fresh
    finally:
        sc.teardown()


def test_live_check_sees_committed_edit_even_if_the_session_already_loaded_the_row() -> None:
    """문항을 먼저 읽어 둔 세션(예: 화면 표시용으로 읽은 요청)에서 발행해도 낡은 내용으로 대조하지 않는다.

    `SELECT … FOR UPDATE`만으로는 이미 identity map에 올라온 엔티티의 속성이 갱신되지 않는다
    (`populate_existing`이 필요하다). 갱신이 안 되면 라이브 해시가 *낡은 내용*에서 계산돼 승인본과
    같아지고, 그 사이 커밋된 수정이 있는데도 `live_content_current`가 통과한다 — 검사가 있으나
    변경을 못 보는 상태다. 테스트마다 새 세션을 쓰면 이 결함은 구조적으로 보이지 않으므로 별도로 둔다.
    """
    sc = _Scenario("e190c2", [3.0])
    (pid,) = sc.pids
    try:
        version_id = _with_session(lambda s: _approved_draft(s, pid))

        async def _go(session: AsyncSession) -> None:
            from whymath_backend.db.models.problem import Problem

            stale = await session.get(Problem, pid)  # 이 세션이 수정 *전* 내용을 먼저 읽어 둔다
            assert stale is not None and stale.answer != "다른세션수정"
            other = create_async_engine(_db_url())
            try:
                async with other.begin() as conn:  # 다른 연결이 수정을 커밋한다
                    await conn.execute(
                        text("UPDATE problem SET answer = :a WHERE problem_id = :p"),
                        {"a": "다른세션수정", "p": pid},
                    )
            finally:
                await other.dispose()
            await gate.apply_transition(session, version_id, _A.PUBLISH, actor="publisher")

        with pytest.raises(PublishGateError, match="live_content_current"):
            _with_session(_go)
        assert _status(version_id) == VersionStatus.APPROVED.value
        assert _pointer(pid) is None
    finally:
        sc.teardown()


# ── D. 내리기 · 낡은 상태 기대 ────────────────────────────────────────────────────
def test_deprecating_the_published_version_clears_the_pointer_and_unpins_new_attempts() -> None:
    sc = _Scenario("e190d", [3.0])
    (pid,) = sc.pids
    try:
        with _P._client() as client:
            _P._erase_learner(client)
            auth = _P._login(client)
            version_id = _publish(pid)
            assert _attempt_pin(_submit(client, auth, pid))[0] == version_id

            _with_session(
                lambda s: gate.apply_transition(
                    s,
                    version_id,
                    _A.DEPRECATE,
                    actor="publisher",
                    expected_status=VersionStatus.PUBLISHED,
                )
            )
            assert _status(version_id) == VersionStatus.DEPRECATED.value
            assert _pointer(pid) is None, "내려간 판을 서빙 기준 포인터가 계속 가리킨다"
            assert _attempt_pin(_submit(client, auth, pid))[0] is None
    finally:
        sc.teardown()


def test_stale_expected_status_is_refused_without_writing() -> None:
    sc = _Scenario("e190d2", [3.0])
    (pid,) = sc.pids
    try:
        version_id = _with_session(lambda s: _approved_draft(s, pid))
        with pytest.raises(StaleStatusError):
            _with_session(
                lambda s: gate.apply_transition(
                    s,
                    version_id,
                    _A.PUBLISH,
                    actor="publisher",
                    expected_status=VersionStatus.IN_QA,
                )
            )
        assert _status(version_id) == VersionStatus.APPROVED.value
        assert _pointer(pid) is None
    finally:
        sc.teardown()


# ── E. 코퍼스 재적재가 발행 포인터를 지우지 않는다 ───────────────────────────────────
def test_corpus_reload_does_not_erase_the_publish_pointer(monkeypatch: pytest.MonkeyPatch) -> None:
    from whymath_backend.l1.problem_bank.populate import ProblemBankStore, load_problem_bank_records

    if not _PROBLEM_CORPUS.exists():
        pytest.skip(f"문제 코퍼스 미존재: {_PROBLEM_CORPUS}")
    if not asyncio.run(_pg_has_version_table()):
        pytest.skip("PostgreSQL 미도달(또는 problem_version 미적용) — 판정 불가. 통과가 아니다.")

    tag = uuid.uuid4().hex[:8]
    base = load_problem_bank_records(_PROBLEM_CORPUS)[0]
    slugs = [f"it-e190-{tag}-a", f"it-e190-{tag}-b"]

    def rec(slug: str, answer: str) -> Any:
        problem = base.problem.model_copy(
            update={
                "problem_id": uuid.uuid4(),
                "slug": slug,
                "external_id": None,
                "answer": answer,
                "concept_ids": [],
            }
        )
        return dataclasses.replace(base, slug=slug, problem=problem, concept_tags=(), relations=())

    store = ProblemBankStore(settings=Settings())
    monkeypatch.setattr(store, "_load_source_id_to_concept_id", lambda: {})
    ids: dict[str, uuid.UUID] = {}
    # P3-04: 발행 대상(A)은 7필드를 갖춰야 한다 — 이 테스트가 재는 것은 포인터 보존이지 메타데이터가
    # 아니므로, 개념·스킬·해설·오개념·힌트는 시드 헬퍼로 채운다. B는 발행하지 않는 대조군이다.
    content, _journal = _P._begin("EOS-190")
    meta: _MetaSeed | None = None
    try:
        report = store.populate([rec(slugs[0], "v1"), rec(slugs[1], "v1")])
        assert report.problems_loaded == 2
        for slug, pid in _rows(
            "SELECT slug, problem_id FROM problem WHERE slug = ANY(:s)", {"s": slugs}
        ):
            ids[slug] = pid
        a_id, b_id = ids[slugs[0]], ids[slugs[1]]
        cid, _code = _P._seed_concept(content, "e304e", "코퍼스 재적재 대조")
        _exec(
            "INSERT INTO problem_concept (problem_id, concept_id, role) VALUES (:p, :c, 'PRIMARY')",
            {"p": a_id, "c": cid},
        )
        meta = _seed_complete_metadata(content.sfx, "e304e", cid, content.skill_ids[-1], [a_id])

        a_version = _publish(a_id)  # A만 발행한다 — B는 대조군(판 없음)
        assert _pointer(a_id) == a_version and _pointer(b_id) is None

        # 코퍼스 값을 v2로 바꿔 다시 적재한다 — 일반 갱신 경로(표지 보호가 막지 않는 행).
        store.populate([rec(slugs[0], "v2"), rec(slugs[1], "v2")])

        # 대조군 — 적재기는 여전히 내용 컬럼을 갱신한다(포인터만 보존하는 것이지 적재를 막는 게 아니다).
        answers = dict(_rows("SELECT slug, answer FROM problem WHERE slug = ANY(:s)", {"s": slugs}))
        assert answers[slugs[0]] == "v2" and answers[slugs[1]] == "v2"
        # 핵심 — 발행 포인터는 재적재를 견딘다.
        assert _pointer(a_id) == a_version, "코퍼스 재적재가 발행 포인터를 NULL로 되돌렸다"
        assert _pointer(b_id) is None
    finally:
        pids = list(ids.values())
        if pids:
            _drop_versions(pids)
        if meta is not None:
            _drop_metadata_seed(meta, pids)  # 힌트 → 풀이 경로 → 오개념 행 (문항 삭제보다 먼저)
        _exec(
            "DELETE FROM problem_concept WHERE problem_id IN "
            "(SELECT problem_id FROM problem WHERE slug = ANY(:s))",
            {"s": slugs},
        )
        _exec(
            "DELETE FROM content_provenance WHERE problem_id IN "
            "(SELECT problem_id FROM problem WHERE slug = ANY(:s))",
            {"s": slugs},
        )
        _exec("DELETE FROM problem WHERE slug = ANY(:s)", {"s": slugs})
        content.teardown()  # 학습자(멱등) → 개념·스킬(연결 행을 먼저 지웠다)


async def _pg_has_version_table() -> bool:
    engine = create_async_engine(_db_url())
    try:
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.tables WHERE table_name = 'problem_version'"
                    )
                )
            ).first()
            return row is not None
    except Exception:
        return False
    finally:
        await engine.dispose()


# ── F. P3-04 7필드 집행 — 실제 행을 망가뜨리면 발행이 거부된다 ──────────────────────
_FIELD = ProblemMetadataField

#: 필드 하나를 망가뜨렸을 때 **실제로** 비게 되는 필드 집합. 스킬·오개념(상속)은 PRIMARY 개념을
#: 거쳐 도출되므로, 개념 연결을 지우면 세 필드가 함께 비는 것이 정직한 기대값이다.
_BLANKS_WHEN_BROKEN: dict[ProblemMetadataField, frozenset[ProblemMetadataField]] = {
    _FIELD.DIFFICULTY: frozenset({_FIELD.DIFFICULTY}),
    _FIELD.SKILL: frozenset({_FIELD.SKILL}),
    _FIELD.CONCEPT: frozenset({_FIELD.CONCEPT, _FIELD.SKILL, _FIELD.MISCONCEPTION_SIGNATURE}),
    _FIELD.SOLUTION: frozenset({_FIELD.SOLUTION}),
    _FIELD.ANSWER: frozenset({_FIELD.ANSWER}),
    _FIELD.MISCONCEPTION_SIGNATURE: frozenset({_FIELD.MISCONCEPTION_SIGNATURE}),
    _FIELD.HINT_STRATEGY: frozenset({_FIELD.HINT_STRATEGY}),
}


def _break_field(field: ProblemMetadataField, sc: _Scenario, pid: uuid.UUID) -> None:
    m = sc.meta
    statements: dict[ProblemMetadataField, tuple[str, dict[str, Any]]] = {
        _FIELD.DIFFICULTY: (
            "UPDATE problem SET difficulty_overall = NULL WHERE problem_id = :p",
            {"p": pid},
        ),
        _FIELD.SKILL: (
            "UPDATE concept SET behavior_skills = '{}' WHERE concept_id = :c",
            {"c": m.cid},
        ),
        _FIELD.CONCEPT: ("DELETE FROM problem_concept WHERE problem_id = :p", {"p": pid}),
        _FIELD.SOLUTION: (
            "UPDATE problem SET answer_explanation = NULL WHERE problem_id = :p",
            {"p": pid},
        ),
        _FIELD.ANSWER: ("UPDATE problem SET answer = NULL WHERE problem_id = :p", {"p": pid}),
        _FIELD.MISCONCEPTION_SIGNATURE: (
            "UPDATE misconception_catalog SET concept_src_id = NULL WHERE mis_id = :m",
            {"m": m.mis_id},
        ),
        _FIELD.HINT_STRATEGY: ("DELETE FROM hints WHERE problem_id = :p", {"p": pid}),
    }
    sql, params = statements[field]
    _exec(sql, params)


def _repair_field(field: ProblemMetadataField, sc: _Scenario, pid: uuid.UUID) -> None:
    m = sc.meta
    statements: dict[ProblemMetadataField, tuple[str, dict[str, Any]]] = {
        _FIELD.DIFFICULTY: (
            "UPDATE problem SET difficulty_overall = 3.0 WHERE problem_id = :p",
            {"p": pid},
        ),
        _FIELD.SKILL: (
            "UPDATE concept SET behavior_skills = ARRAY[CAST(:s AS text)] WHERE concept_id = :c",
            {"s": m.skill_id, "c": m.cid},
        ),
        _FIELD.CONCEPT: (
            "INSERT INTO problem_concept (problem_id, concept_id, role) VALUES (:p, :c, 'PRIMARY')",
            {"p": pid, "c": m.cid},
        ),
        _FIELD.SOLUTION: (
            "UPDATE problem SET answer_explanation = :e WHERE problem_id = :p",
            {"e": _SOLUTION_TEXT, "p": pid},
        ),
        _FIELD.ANSWER: (
            "UPDATE problem SET answer = '복구된정답' WHERE problem_id = :p",
            {"p": pid},
        ),
        _FIELD.MISCONCEPTION_SIGNATURE: (
            "UPDATE misconception_catalog SET concept_src_id = :s WHERE mis_id = :m",
            {"s": m.src_id, "m": m.mis_id},
        ),
        _FIELD.HINT_STRATEGY: (
            _HINT_SQL,
            {"h": f"hint-fix-{uuid.uuid4().hex[:8]}", "sp": m.path_ids[0], "p": pid},
        ),
    }
    sql, params = statements[field]
    _exec(sql, params)


async def _evidence_of(session: AsyncSession, pid: uuid.UUID) -> Any:
    from whymath_backend.db.models.problem import Problem

    problem = await session.get(Problem, pid)
    assert problem is not None
    return await load_metadata_evidence(session, problem)


def _metadata_failures(error: PublishGateError) -> set[str]:
    """`problem_metadata_complete: <필드>: <사유>` 거부 사유에서 필드 이름만 모은다."""
    prefix = "problem_metadata_complete: "
    others = [f for f in error.failures if not f.startswith(prefix)]
    assert not others, f"7필드 말고 다른 이유로도 거부됐다 — 격리가 깨졌다: {others}"
    return {f[len(prefix) :].split(": ")[0] for f in error.failures}


def test_loader_reads_all_seven_fields_from_real_rows() -> None:
    sc = _Scenario("e304a", [3.0])
    (pid,) = sc.pids
    try:
        evidence = _with_session(lambda s: _evidence_of(s, pid))
        assert evidence.difficulty == 3.0
        assert evidence.answer and evidence.solution_text == _SOLUTION_TEXT
        assert evidence.concept_ids == (str(sc.cid),)
        assert evidence.skill_ids == (sc.meta.skill_id,)
        assert evidence.own_misconception_ids == ()
        assert evidence.concept_misconception_ids == (sc.meta.mis_id,)
        assert evidence.verified_hint_count == 1
        assert evidence.slots == frozenset()
        assert evaluate_metadata(evidence).complete
    finally:
        sc.teardown()


@pytest.mark.parametrize("field", list(ProblemMetadataField), ids=lambda f: f.value)
def test_publish_is_refused_when_a_real_field_is_blank_and_passes_once_repaired(
    field: ProblemMetadataField,
) -> None:
    sc = _Scenario("e304b", [3.0])
    (pid,) = sc.pids
    try:
        # 대조군 — 망가뜨리기 전에는 7필드가 전부 있다(이게 없으면 아래 거부가 무엇 때문인지 모른다).
        assert evaluate_metadata(_with_session(lambda s: _evidence_of(s, pid))).complete

        _break_field(field, sc, pid)
        version_id = _with_session(lambda s: _approved_draft(s, pid))
        assert _status(version_id) == VersionStatus.APPROVED.value, "7필드는 발행의 조건이다"

        verdict = evaluate_metadata(_with_session(lambda s: _evidence_of(s, pid)))
        assert set(verdict.missing) == _BLANKS_WHEN_BROKEN[field]
        assert verdict.unknown == ()

        with pytest.raises(PublishGateError) as info:
            _with_session(
                lambda s: gate.apply_transition(s, version_id, _A.PUBLISH, actor="publisher")
            )
        assert _metadata_failures(info.value) == {f.value for f in _BLANKS_WHEN_BROKEN[field]}

        # 아무 것도 쓰이지 않았다 — 상태·포인터 그대로(APPROVED에서 멈춘다).
        assert _status(version_id) == VersionStatus.APPROVED.value
        assert _pointer(pid) is None

        # 대조군 — 고치면 같은 경로로 발행된다. 거부가 '문항 전체 차단'이 아니다.
        _repair_field(field, sc, pid)
        fresh = _publish(pid)
        assert _pointer(pid) == fresh
    finally:
        sc.teardown()


def test_trigger_slot_needs_its_own_signature_not_an_inherited_or_dangling_one() -> None:
    sc = _Scenario("e304c", [3.0])
    (pid,) = sc.pids
    try:
        _exec(
            "UPDATE problem SET tags = ARRAY['p3-slot:misconception_trigger'] WHERE problem_id = :p",
            {"p": pid},
        )
        version_id = _with_session(lambda s: _approved_draft(s, pid))

        def _try_publish() -> PublishGateError:
            with pytest.raises(PublishGateError) as info:
                _with_session(
                    lambda s: gate.apply_transition(s, version_id, _A.PUBLISH, actor="publisher")
                )
            return info.value

        # ① 개념 상속은 있으나(7필드 중 이 필드만 문제) 문항 자체 연결이 없다 → 거부
        assert _metadata_failures(_try_publish()) == {"misconception_signature"}

        # ② 등록되지 않은 id는 서명이 아니다(없는 오개념으로 서명이 있는 척하지 않는다)
        dangling = '[{"choice_index": 0, "misconception_id": "no-such-misconception-kebab"}]'
        _exec(
            "UPDATE problem SET distractor_map = CAST(:d AS jsonb) WHERE problem_id = :p",
            {"d": dangling, "p": pid},
        )
        assert _metadata_failures(_try_publish()) == {"misconception_signature"}

        # ③ 같은 승인본이 문항 자체의 등록된 오개념 연결을 가지면 통과한다(distractor_map은 판 payload
        #    밖이라 승인 뒤 고쳐도 live_content_current와 무관하다).
        registered = f'[{{"choice_index": 0, "misconception_id": "{sc.meta.mis_id}"}}]'
        _exec(
            "UPDATE problem SET distractor_map = CAST(:d AS jsonb) WHERE problem_id = :p",
            {"d": registered, "p": pid},
        )
        _with_session(lambda s: gate.apply_transition(s, version_id, _A.PUBLISH, actor="publisher"))
        assert _status(version_id) == VersionStatus.PUBLISHED.value
    finally:
        sc.teardown()


def test_kebab_signature_counts_only_through_a_registered_crosslink() -> None:
    sc = _Scenario("e304d", [3.0])
    (pid,) = sc.pids
    kebab = f"kebab-p304-{uuid.uuid4().hex[:8]}"
    try:
        entry = f'[{{"choice_index": 0, "misconception_id": "{kebab}"}}]'
        _exec(
            "UPDATE problem SET distractor_map = CAST(:d AS jsonb) WHERE problem_id = :p",
            {"d": entry, "p": pid},
        )
        before = _with_session(lambda s: _evidence_of(s, pid))
        assert before.own_misconception_ids == (), "크로스링크 없는 kebab이 서명으로 세어졌다"

        _exec(
            "INSERT INTO misconception_crosslink (kebab_id, mis_id, link_type) "
            "VALUES (:k, :m, '직접매핑')",
            {"k": kebab, "m": sc.meta.mis_id},
        )
        after = _with_session(lambda s: _evidence_of(s, pid))
        assert after.own_misconception_ids == (kebab,)
        assert FieldState.PRESENT is evaluate_metadata(after).states[_FIELD.MISCONCEPTION_SIGNATURE]
    finally:
        sc.teardown()  # 오개념 행 삭제가 크로스링크를 함께 지운다(ON DELETE CASCADE)


def test_a_skill_name_without_a_registry_row_is_not_a_skill() -> None:
    """개념에 스킬 **이름**만 적혀 있고 `skill_node`에 행이 없으면 스킬이 아니다(오타로 없는 스킬을 세지 않는다)."""
    sc = _Scenario("e304e", [3.0])
    (pid,) = sc.pids
    try:
        assert evaluate_metadata(_with_session(lambda s: _evidence_of(s, pid))).complete
        _exec(
            "UPDATE concept SET behavior_skills = ARRAY['skill.p304.no-such-registry-row'] "
            "WHERE concept_id = :c",
            {"c": sc.cid},
        )
        evidence = _with_session(lambda s: _evidence_of(s, pid))
        assert evidence.skill_ids == (), "레지스트리에 없는 스킬 이름이 스킬로 세어졌다"
        assert evaluate_metadata(evidence).missing == (_FIELD.SKILL,)
    finally:
        sc.teardown()


def test_an_unverified_hint_is_not_a_hint_strategy() -> None:
    """`verified=false` 힌트는 학생에게 제공될 수 없다 — 있어도 힌트 전략으로 세지 않는다."""
    sc = _Scenario("e304f", [3.0])
    (pid,) = sc.pids
    try:
        _exec("UPDATE hints SET verified = false WHERE problem_id = :p", {"p": pid})
        evidence = _with_session(lambda s: _evidence_of(s, pid))
        assert evidence.verified_hint_count == 0, "미검증 힌트가 세어졌다"
        assert evaluate_metadata(evidence).missing == (_FIELD.HINT_STRATEGY,)
        # 대조군 — 검증 표시를 돌려놓으면 다시 인정된다.
        _exec("UPDATE hints SET verified = true WHERE problem_id = :p", {"p": pid})
        assert _with_session(lambda s: _evidence_of(s, pid)).verified_hint_count == 1
    finally:
        sc.teardown()
