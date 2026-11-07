"""개념 생애 상태 마이그레이션·트리거 *실 PostgreSQL 통합테스트* — PED-17 A1 (WHYMATH_RUN_INTEGRATION).

리비전 `b1a4d7c92e05`가 만든 것을 **실 DB에서** 검증한다. 가짜 세션으로는 볼 수 없는 것들이다:

  ① 컬럼·테이블·트리거 3종이 head에 실재한다.
  ② 허용 전환 5쌍 트리거 — 16쌍 전수에서 **파이썬 전환표와 정확히 같은** 5쌍만 통과한다(표 이중 정의의 드리프트 방지).
  ③ 상태 변경 기록은 추가 전용 — UPDATE·DELETE·TRUNCATE가 DB에서 거부되고 INSERT는 된다(대조군).
  ④ 노출 기록은 UPDATE만 거부되고 DELETE는 된다(보존기한 파기를 위해 의도된 비대칭) · 가명 형식 CHECK.
  ⑤ 어휘 CHECK·최초 부여 쌍 CHECK가 오염 값을 거부한다 · DB 어휘 = 파이썬 어휘.
  ⑥ 전환 함수가 실 DB에서 상태 변경 + 기록 1건을 같은 트랜잭션에 남기고, 거부 시 아무것도 쓰지 않는다.
  ⑦ 동시 전환 — 같은 행에 두 세션이 동시에 초안→검증됨을 시도하면 정확히 하나만 성공한다.
  ⑧ 되돌리기 왕복 + 백필 분류(reviewed→공개됨/사람 검수 · rejected→회수됨 · 그 외→초안).

PG 미도달 또는 마이그레이션 미적용이면 graceful skip(`test_concept_version_migration_integration.py` 미러).

**정리 규칙**: 상태 변경 기록은 추가 전용이라 DELETE로 지울 수 없다. sentinel 정리는 `ALTER TABLE ... DISABLE
TRIGGER USER`를 **같은 트랜잭션 안에서** 쓰고(실패 시 롤백 = 자동 복구), 모듈 마지막 테스트가 트리거가 켜져
있는지 다시 확인한다. sentinel code는 실행마다 달라 실제 데이터와 충돌하지 않는다.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.config import Settings
from whymath_backend.schema.concept_lifecycle import (
    ALLOWED_TRANSITIONS,
    ChangedByKind,
    ConceptContentOrigin,
    ConceptLifecycleState,
    ConceptTransitionVia,
)

pytestmark = pytest.mark.integration

_REVISION = "b1a4d7c92e05"
_PREV_REVISION = "a8c4e1f7b3d9"
_RUN = uuid.uuid4().hex[:8]  # 실행마다 다른 sentinel 접두 — 실제 코드와 충돌하지 않는다.

_BACKEND_DIR = Path(__file__).resolve().parents[3] / "src" / "backend"
_ALEMBIC_DIR = _BACKEND_DIR / "alembic"

_STATES = [s.value for s in ConceptLifecycleState]
_TRIGGERS = (
    ("concept_content", "trg_concept_content_lifecycle_pair_guard"),
    ("concept_state_transition", "trg_concept_state_transition_append_only_row"),
    ("concept_state_transition", "trg_concept_state_transition_append_only_truncate"),
    ("concept_exposure_event", "trg_concept_exposure_event_no_update"),
)
_PSEUDO = "a" * 64


# ── DB 도우미 ──────────────────────────────────────────────────────────────────────────


def _engine() -> Any:
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    return create_engine(Settings().sync_database_url, poolclass=NullPool)


def _reachable() -> bool:
    from sqlalchemy import text

    engine = _engine()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT count(*) FROM concept_state_transition"))
            conn.execute(text("SELECT lifecycle_status FROM concept_content LIMIT 1"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def _require_db() -> None:
    if not _reachable():
        pytest.skip(
            "PostgreSQL 미도달(또는 b1a4d7c92e05 미적용) — 통합 테스트 건너뜀 "
            "(WHYMATH_DATABASE_URL·alembic upgrade head 확인)"
        )


def _exec(sql: str, **params: Any) -> list[Any]:
    """단일 트랜잭션으로 실행하고 (있으면) 행을 돌려준다."""
    from sqlalchemy import text

    engine = _engine()
    try:
        with engine.begin() as conn:
            res = conn.execute(text(sql), params)
            return list(res.fetchall()) if res.returns_rows else []
    finally:
        engine.dispose()


def _sqlstate(sql: str, **params: Any) -> str | None:
    """실행해서 DB가 거부하면 SQLSTATE를, 통과하면 None을 돌려준다(통과/거부 양쪽을 관찰)."""
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    engine = _engine()
    try:
        with engine.begin() as conn:
            conn.execute(text(sql), params)
        return None
    except DBAPIError as exc:
        return str(getattr(exc.orig, "sqlstate", None))
    finally:
        engine.dispose()


def _code(tag: str) -> str:
    return f"A1IT-{_RUN}-{tag}"


def _insert_content(
    code: str,
    *,
    review: str = "ai_estimated",
    lifecycle: str | None = None,
    origin: str | None = None,
) -> None:
    cols = "code, scope, name, subject, review_status"
    vals = ":code, 'K-12', :name, '통합테스트', :review"
    params: dict[str, Any] = {"code": code, "name": f"{code} sentinel", "review": review}
    if lifecycle is not None:
        cols += ", lifecycle_status"
        vals += ", :lc"
        params["lc"] = lifecycle
    if origin is not None:
        cols += ", content_origin"
        vals += ", :og"
        params["og"] = origin
    _exec(f"INSERT INTO concept_content ({cols}) VALUES ({vals})", **params)


def _cleanup() -> None:
    """이 실행의 sentinel 정리. 추가 전용 트리거는 같은 트랜잭션에서만 끈다(실패 시 롤백=복구)."""
    from sqlalchemy import text

    engine = _engine()
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE concept_state_transition DISABLE TRIGGER USER"))
            conn.execute(
                text("DELETE FROM concept_state_transition WHERE concept_code LIKE :p"),
                {"p": f"A1IT-{_RUN}-%"},
            )
            conn.execute(text("ALTER TABLE concept_state_transition ENABLE TRIGGER USER"))
            conn.execute(
                text("DELETE FROM concept_exposure_event WHERE concept_code LIKE :p"),
                {"p": f"A1IT-{_RUN}-%"},
            )
            conn.execute(
                text("DELETE FROM concept_content WHERE code LIKE :p"), {"p": f"A1IT-{_RUN}-%"}
            )
    finally:
        engine.dispose()


@pytest.fixture
def clean() -> Iterator[None]:
    _cleanup()
    try:
        yield
    finally:
        _cleanup()


# ── ① 실재 ─────────────────────────────────────────────────────────────────────────────


class TestSchemaExists:
    def test_columns_tables_and_triggers_exist(self, clean: None) -> None:
        cols = {
            r[0]
            for r in _exec(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'concept_content'"
            )
        }
        assert {"lifecycle_status", "content_origin"} <= cols
        tables = {
            r[0]
            for r in _exec(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            )
        }
        assert {"concept_state_transition", "concept_exposure_event"} <= tables
        for table, trigger in _TRIGGERS:
            found = _exec(
                "SELECT tgenabled FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                "WHERE c.relname = :tbl AND t.tgname = :trg AND NOT t.tgisinternal",
                tbl=table,
                trg=trigger,
            )
            assert found and found[0][0] == "O", f"트리거 없음/비활성: {trigger}"

    def test_new_row_defaults_are_fail_closed(self, clean: None) -> None:
        # 컬럼을 모르는 쓰기 경로(코퍼스 적재기 등)가 만든 새 행은 초안/AI 생성 = 학생에게 안 나간다.
        code = _code("DEFAULT")
        _insert_content(code)
        assert _exec(
            "SELECT lifecycle_status, content_origin FROM concept_content WHERE code = :c", c=code
        )[0] == ("초안", "AI 생성")


# ── ② 허용 전환 5쌍 트리거 ──────────────────────────────────────────────────────────────


class TestPairTrigger:
    @pytest.mark.parametrize("frm", _STATES)
    @pytest.mark.parametrize("to", _STATES)
    def test_trigger_allows_exactly_the_python_table(self, clean: None, frm: str, to: str) -> None:
        if frm == to:
            pytest.skip("같은 값 UPDATE는 트리거 WHEN 절 밖(아래 대조군 테스트)")
        code = _code(f"PAIR-{_STATES.index(frm)}{_STATES.index(to)}")
        _insert_content(code, lifecycle=frm)  # INSERT는 트리거 대상이 아니다(UPDATE OF만).
        state = _sqlstate(
            "UPDATE concept_content SET lifecycle_status = :to WHERE code = :c", to=to, c=code
        )
        allowed = (ConceptLifecycleState(frm), ConceptLifecycleState(to)) in ALLOWED_TRANSITIONS
        if allowed:
            assert state is None, f"{frm}->{to} 는 허용인데 거부됨({state})"
            assert (
                _exec("SELECT lifecycle_status FROM concept_content WHERE code = :c", c=code)[0][0]
                == to
            )
        else:
            assert state == "23514", f"{frm}->{to} 는 거부여야 하는데 sqlstate={state}"
            assert (
                _exec("SELECT lifecycle_status FROM concept_content WHERE code = :c", c=code)[0][0]
                == frm
            )

    def test_updates_not_touching_lifecycle_are_unaffected(self, clean: None) -> None:
        # 대조군 — 트리거가 *모든* UPDATE를 막는 것이 아니다(코퍼스 재적재·검수 반영 경로 보호).
        code = _code("CTRL")
        _insert_content(code, lifecycle="공개됨", origin="사람 검수", review="reviewed")
        assert (
            _sqlstate(
                "UPDATE concept_content SET name = 'x', review_status = 'ai_estimated' WHERE code = :c",
                c=code,
            )
            is None
        )
        # 같은 값으로 쓰는 UPDATE(공개됨→공개됨)도 변경이 아니므로 통과한다.
        assert (
            _sqlstate(
                "UPDATE concept_content SET lifecycle_status = '공개됨' WHERE code = :c", c=code
            )
            is None
        )


# ── ③ 상태 변경 기록: 추가 전용 ─────────────────────────────────────────────────────────

_LEDGER_INSERT = (
    "INSERT INTO concept_state_transition "
    "(concept_code, from_state, to_state, changed_by_kind, changed_by_name, via, reason) "
    "VALUES (:c, '초안', '검증됨', 'agent', 'B6 공개 관문', 'B6 공개 관문', '자동 검증 통과')"
)


class TestLedgerAppendOnly:
    def test_insert_is_allowed_control(self, clean: None) -> None:
        assert _sqlstate(_LEDGER_INSERT, c=_code("L-INS")) is None

    def test_update_is_rejected(self, clean: None) -> None:
        c = _code("L-UPD")
        _exec(_LEDGER_INSERT, c=c)
        assert (
            _sqlstate(
                "UPDATE concept_state_transition SET reason = '바꿈' WHERE concept_code = :c", c=c
            )
            == "23000"
        )
        assert (
            _exec("SELECT reason FROM concept_state_transition WHERE concept_code = :c", c=c)[0][0]
            == "자동 검증 통과"
        )

    def test_delete_is_rejected(self, clean: None) -> None:
        c = _code("L-DEL")
        _exec(_LEDGER_INSERT, c=c)
        assert (
            _sqlstate("DELETE FROM concept_state_transition WHERE concept_code = :c", c=c)
            == "23000"
        )
        assert (
            _exec("SELECT count(*) FROM concept_state_transition WHERE concept_code = :c", c=c)[0][
                0
            ]
            == 1
        )

    def test_truncate_is_rejected(self, clean: None) -> None:
        c = _code("L-TRN")
        _exec(_LEDGER_INSERT, c=c)
        before = _exec("SELECT count(*) FROM concept_state_transition")[0][0]
        assert _sqlstate("TRUNCATE concept_state_transition") == "23000"
        assert _exec("SELECT count(*) FROM concept_state_transition")[0][0] == before

    def test_all_triggers_still_enabled_after_cleanup_cycle(self, clean: None) -> None:
        # 정리 절차가 트리거를 끈 채로 남기지 않았다는 증거(추가 전용 보호의 상시 유효).
        _cleanup()
        for table, trigger in _TRIGGERS:
            row = _exec(
                "SELECT tgenabled FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                "WHERE c.relname = :tbl AND t.tgname = :trg",
                tbl=table,
                trg=trigger,
            )
            assert row and row[0][0] == "O", trigger


# ── ④ 노출 기록 ─────────────────────────────────────────────────────────────────────────


class TestExposureEvent:
    _INS = (
        "INSERT INTO concept_exposure_event (concept_code, student_pseudonym, ai_label_shown) "
        "VALUES (:c, :p, :l)"
    )

    def test_insert_valid_pseudonym_is_allowed(self, clean: None) -> None:
        assert _sqlstate(self._INS, c=_code("E-OK"), p=_PSEUDO, l=False) is None

    @pytest.mark.parametrize(
        "bad",
        [
            "11111111-1111-1111-1111-111111111111",  # 원본 user_id(UUID)
            "홍길동",  # 실제 이름
            "student@example.com",  # 이메일
            "A" * 64,  # 대문자 16진 — 형식 위반
            "a" * 63,
            "a" * 65,
            "",
        ],
    )
    def test_non_pseudonym_values_are_rejected_by_check(self, clean: None, bad: str) -> None:
        assert _sqlstate(self._INS, c=_code("E-BAD"), p=bad, l=False) == "23514"

    def test_update_is_rejected(self, clean: None) -> None:
        c = _code("E-UPD")
        _exec(self._INS, c=c, p=_PSEUDO, l=False)
        assert (
            _sqlstate(
                "UPDATE concept_exposure_event SET ai_label_shown = true WHERE concept_code = :c",
                c=c,
            )
            == "23000"
        )
        assert (
            _exec("SELECT ai_label_shown FROM concept_exposure_event WHERE concept_code = :c", c=c)[
                0
            ][0]
            is False
        )

    def test_delete_is_allowed_for_retention_purge(self, clean: None) -> None:
        # 의도된 비대칭 — 학습 기록이라 보존기한 파기·삭제 요청을 막으면 법령 유래 절차와 충돌한다.
        c = _code("E-DEL")
        _exec(self._INS, c=c, p=_PSEUDO, l=False)
        assert _sqlstate("DELETE FROM concept_exposure_event WHERE concept_code = :c", c=c) is None
        assert (
            _exec("SELECT count(*) FROM concept_exposure_event WHERE concept_code = :c", c=c)[0][0]
            == 0
        )

    def test_ai_label_shown_is_required(self, clean: None) -> None:
        assert (
            _sqlstate(
                "INSERT INTO concept_exposure_event (concept_code, student_pseudonym) VALUES (:c, :p)",
                c=_code("E-NL"),
                p=_PSEUDO,
            )
            == "23502"
        )


# ── ⑤ 어휘 CHECK와 파이썬 어휘 정합 ──────────────────────────────────────────────────────


def _check_literals(constraint: str) -> set[str]:
    row = _exec(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n", n=constraint
    )
    assert row, f"제약 없음: {constraint}"
    return set(re.findall(r"'([^']*)'", row[0][0]))


class TestVocabularyParity:
    def test_state_vocab_matches_python(self, clean: None) -> None:
        py = {s.value for s in ConceptLifecycleState}
        assert _check_literals("ck_concept_content_lifecycle_status") == py
        assert _check_literals("ck_concept_state_transition_to_state") == py
        assert _check_literals("ck_concept_state_transition_from_state") == py

    def test_origin_vocab_matches_python(self, clean: None) -> None:
        assert _check_literals("ck_concept_content_content_origin") == {
            o.value for o in ConceptContentOrigin
        }

    def test_via_vocab_matches_python(self, clean: None) -> None:
        assert _check_literals("ck_concept_state_transition_via") == {
            v.value for v in ConceptTransitionVia
        }

    def test_kind_vocab_matches_python(self, clean: None) -> None:
        assert _check_literals("ck_concept_state_transition_changed_by_kind") == {
            k.value for k in ChangedByKind
        }

    @pytest.mark.parametrize("bad", ["Published", "공개", "published", " 공개됨", ""])
    def test_bad_lifecycle_value_is_rejected(self, clean: None, bad: str) -> None:
        assert (
            _sqlstate(
                "INSERT INTO concept_content (code, scope, name, subject, review_status, lifecycle_status) "
                "VALUES (:c, 'K-12', 'n', 's', 'ai_estimated', :v)",
                c=_code("V-BAD"),
                v=bad,
            )
            == "23514"
        )

    def test_bad_origin_is_rejected(self, clean: None) -> None:
        assert (
            _sqlstate(
                "INSERT INTO concept_content (code, scope, name, subject, review_status, content_origin) "
                "VALUES (:c, 'K-12', 'n', 's', 'ai_estimated', 'human')",
                c=_code("O-BAD"),
            )
            == "23514"
        )

    def test_blank_reason_and_actor_are_rejected(self, clean: None) -> None:
        base = (
            "INSERT INTO concept_state_transition (concept_code, from_state, to_state, changed_by_kind, "
            "changed_by_name, via, reason) VALUES (:c, '초안', '검증됨', 'agent', :n, 'B6 공개 관문', :r)"
        )
        assert _sqlstate(base, c=_code("B1"), n="B6", r="   ") == "23514"
        assert _sqlstate(base, c=_code("B2"), n="  ", r="사유") == "23514"

    def test_initial_assignment_pair_check(self, clean: None) -> None:
        # from_state가 NULL이면 via는 '최초 부여'여야 하고, 그 반대도 성립해야 한다.
        ins = (
            "INSERT INTO concept_state_transition (concept_code, from_state, to_state, changed_by_kind, "
            "changed_by_name, via, reason) VALUES (:c, {f}, '공개됨', 'rule', 'x', {v}, '사유')"
        )
        assert _sqlstate(ins.format(f="NULL", v="'최초 부여'"), c=_code("I1")) is None
        assert _sqlstate(ins.format(f="NULL", v="'D4 AI 카나리'"), c=_code("I2")) == "23514"
        assert _sqlstate(ins.format(f="'초안'", v="'최초 부여'"), c=_code("I3")) == "23514"


# ── ⑥⑦ 전환 함수: 실 DB ────────────────────────────────────────────────────────────────


def _async_session_factory() -> Any:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(Settings().database_url, poolclass=NullPool)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _transition(
    maker: Any,
    code: str,
    to: ConceptLifecycleState,
    via: ConceptTransitionVia,
    kind: ChangedByKind = ChangedByKind.AGENT,
) -> Any:
    from whymath_backend.l1.concept_content.lifecycle import transition_concept_state

    async with maker() as session:
        record = await transition_concept_state(
            session,
            concept_code=code,
            to_state=to,
            via=via,
            changed_by_kind=kind,
            changed_by_name="통합테스트 에이전트",
            reason="통합테스트 사유",
        )
        await session.commit()
        return record


class TestTransitionFunctionAgainstRealDb:
    async def test_full_lifecycle_records_one_row_per_change_in_order(self, clean: None) -> None:
        code = _code("FN-FULL")
        _insert_content(code)
        engine, maker = _async_session_factory()
        try:
            st, vi = ConceptLifecycleState, ConceptTransitionVia
            steps = [
                (st.VERIFIED, vi.B6_PUBLIC_GATE, ChangedByKind.AGENT),
                (st.PUBLISHED, vi.D5_STAGED_ROLLOUT, ChangedByKind.AGENT),
                (st.WITHDRAWN, vi.EMERGENCY_STOP, ChangedByKind.KIKI),
                (st.DRAFT, vi.REGENERATE, ChangedByKind.AGENT),
            ]
            for i, (to, via, kind) in enumerate(steps, start=1):
                await _transition(maker, code, to, via, kind)
                # 완료 기준 3: 상태를 바꾸면 기록 테이블에 1건이 남는다(누적 i건).
                n = _exec(
                    "SELECT count(*) FROM concept_state_transition WHERE concept_code = :c", c=code
                )[0][0]
                assert n == i
                assert (
                    _exec("SELECT lifecycle_status FROM concept_content WHERE code = :c", c=code)[
                        0
                    ][0]
                    == to.value
                )
            rows = _exec(
                "SELECT from_state, to_state, via, changed_by_kind FROM concept_state_transition "
                "WHERE concept_code = :c ORDER BY changed_at, to_state",
                c=code,
            )
            chain = {(r[0], r[1]) for r in rows}
            assert chain == {
                ("초안", "검증됨"),
                ("검증됨", "공개됨"),
                ("공개됨", "회수됨"),
                ("회수됨", "초안"),
            }
            assert ("공개됨", "회수됨", "긴급 정지", "kiki") in {tuple(r) for r in rows}
        finally:
            await engine.dispose()

    async def test_rejected_transition_writes_nothing(self, clean: None) -> None:
        # 완료 기준 1: 허용되지 않은 전환을 시도하면 거부된다 — 상태 불변 · 기록 0건.
        from whymath_backend.l1.concept_content.lifecycle import InvalidConceptTransitionError

        code = _code("FN-REJ")
        _insert_content(code)  # 초안
        engine, maker = _async_session_factory()
        try:
            with pytest.raises(InvalidConceptTransitionError):
                await _transition(
                    maker,
                    code,
                    ConceptLifecycleState.PUBLISHED,
                    ConceptTransitionVia.D5_STAGED_ROLLOUT,
                )
            with pytest.raises(InvalidConceptTransitionError):  # 쌍은 맞고 경로가 틀림
                await _transition(
                    maker, code, ConceptLifecycleState.VERIFIED, ConceptTransitionVia.D4_AI_CANARY
                )
            assert (
                _exec("SELECT lifecycle_status FROM concept_content WHERE code = :c", c=code)[0][0]
                == "초안"
            )
            assert (
                _exec(
                    "SELECT count(*) FROM concept_state_transition WHERE concept_code = :c", c=code
                )[0][0]
                == 0
            )
        finally:
            await engine.dispose()

    async def test_concurrent_transitions_exactly_one_wins(self, clean: None) -> None:
        from whymath_backend.l1.concept_content.lifecycle import InvalidConceptTransitionError

        code = _code("FN-RACE")
        _insert_content(code)
        engine, maker = _async_session_factory()
        try:
            results = await asyncio.wait_for(
                asyncio.gather(
                    *[
                        _transition(
                            maker,
                            code,
                            ConceptLifecycleState.VERIFIED,
                            ConceptTransitionVia.B6_PUBLIC_GATE,
                        )
                        for _ in range(2)
                    ],
                    return_exceptions=True,
                ),
                timeout=30,
            )
            wins = [r for r in results if not isinstance(r, Exception)]
            losses = [r for r in results if isinstance(r, InvalidConceptTransitionError)]
            assert (len(wins), len(losses)) == (1, 1), results
            assert (
                _exec(
                    "SELECT count(*) FROM concept_state_transition WHERE concept_code = :c", c=code
                )[0][0]
                == 1
            )
        finally:
            await engine.dispose()

    async def test_unknown_concept_is_refused(self, clean: None) -> None:
        from whymath_backend.l1.concept_content.lifecycle import ConceptNotFoundError

        engine, maker = _async_session_factory()
        try:
            with pytest.raises(ConceptNotFoundError):
                await _transition(
                    maker,
                    _code("NOPE"),
                    ConceptLifecycleState.VERIFIED,
                    ConceptTransitionVia.B6_PUBLIC_GATE,
                )
            assert (
                _exec(
                    "SELECT count(*) FROM concept_state_transition WHERE concept_code = :c",
                    c=_code("NOPE"),
                )[0][0]
                == 0
            )
        finally:
            await engine.dispose()


class TestExposureWriterAgainstRealDb:
    """노출 기록 writer의 ORM 모델이 실제 테이블과 맞는가 — 가짜 세션으로는 볼 수 없는 축.

    `record_concept_exposure`를 실 세션으로 커밋하고 raw SQL로 읽어 온다. 컬럼명·타입·가명 CHECK
    (소문자 16진 64자)를 실제 HMAC 값이 통과하는지까지 본다. 학생 원본 user_id가 행 어디에도 없는지도 본다.
    """

    async def test_writer_commits_one_row_with_pseudonym_only(self, clean: None) -> None:
        from pydantic import SecretStr

        from whymath_backend.l2.concept_exposure import record_concept_exposure, student_pseudonym

        settings = Settings(jwt_secret_key=SecretStr("integration-secret-0123456789-abcdef"))
        user_id = uuid.uuid4()
        code = _code("EXP-W")
        engine, maker = _async_session_factory()
        try:
            async with maker() as session:
                await record_concept_exposure(
                    session,
                    concept_code=code,
                    user_id=user_id,
                    settings=settings,
                    ai_label_shown=False,
                )
                await session.commit()
        finally:
            await engine.dispose()

        rows = _exec(
            "SELECT concept_code, student_pseudonym, ai_label_shown, exposed_at "
            "FROM concept_exposure_event WHERE concept_code = :c",
            c=code,
        )
        assert len(rows) == 1  # 완료 기준 3: 열면 노출 기록이 정확히 1건.
        assert rows[0][1] == student_pseudonym(user_id, settings=settings)
        assert rows[0][2] is False
        assert rows[0][3] is not None  # 시각은 DB 기본값(now())이 채웠다.
        flat = " ".join(str(v) for v in rows[0])
        assert str(user_id) not in flat and user_id.hex not in flat


# ── ⑧ 되돌리기 왕복 + 백필 분류 ──────────────────────────────────────────────────────────


def _alembic_cfg() -> Any:
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(_ALEMBIC_DIR))
    cfg.set_main_option("sqlalchemy.url", "")
    return cfg


class TestRollbackRoundTripAndBackfill:
    def test_downgrade_then_upgrade_reproduces_backfill_classification(self, clean: None) -> None:
        from alembic import command

        # 보호: 최초 부여 외의 기록(= 실제 상태 변경 이력)이 있으면 downgrade가 그 이력을 파괴하므로 건너뛴다.
        real_history = _exec(
            "SELECT count(*) FROM concept_state_transition WHERE via <> '최초 부여' "
            "AND concept_code NOT LIKE 'A1IT-%'"
        )[0][0]
        if real_history:
            pytest.skip(
                f"실제 상태 변경 이력 {real_history}건이 있어 왕복(기록 DROP)을 건너뜀 — 되돌리기 문서의 내보내기 먼저"
            )

        rev, rej, est = _code("BF-REV"), _code("BF-REJ"), _code("BF-EST")
        _insert_content(rev, review="reviewed")
        _insert_content(rej, review="rejected")
        _insert_content(est, review="ai_estimated")

        cfg = _alembic_cfg()
        command.downgrade(cfg, _PREV_REVISION)
        try:
            cols = {
                r[0]
                for r in _exec(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = 'concept_content'"
                )
            }
            assert not (
                {"lifecycle_status", "content_origin"} & cols
            ), "downgrade 후 컬럼이 남아 있다"
            tables = {
                r[0]
                for r in _exec(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
                )
            }
            assert not ({"concept_state_transition", "concept_exposure_event"} & tables)
            # 되돌린 뒤에도 기존 행은 그대로다(삭제·덮어쓰기 금지).
            assert (
                _exec("SELECT review_status FROM concept_content WHERE code = :c", c=rev)[0][0]
                == "reviewed"
            )
        finally:
            command.upgrade(cfg, "head")

        got = {
            r[0]: (r[1], r[2])
            for r in _exec(
                "SELECT code, lifecycle_status, content_origin FROM concept_content WHERE code IN (:a, :b, :c)",
                a=rev,
                b=rej,
                c=est,
            )
        }
        assert got[rev] == ("공개됨", "사람 검수")
        assert got[rej] == ("회수됨", "AI 생성")
        assert got[est] == ("초안", "AI 생성")
        # 기본값이 아닌 행(공개됨·회수됨)에만 '최초 부여' 기록이 정확히 1건씩 남는다. 초안은 기록 없음.
        ledger = {
            r[0]: (r[1], r[2], r[3])
            for r in _exec(
                "SELECT concept_code, from_state, to_state, via FROM concept_state_transition "
                "WHERE concept_code IN (:a, :b, :c)",
                a=rev,
                b=rej,
                c=est,
            )
        }
        assert ledger == {rev: (None, "공개됨", "최초 부여"), rej: (None, "회수됨", "최초 부여")}
        # 되돌린 뒤 다시 올려도 트리거가 전부 살아 있다.
        for table, trigger in _TRIGGERS:
            row = _exec(
                "SELECT tgenabled FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                "WHERE c.relname = :tbl AND t.tgname = :trg",
                tbl=table,
                trg=trigger,
            )
            assert row and row[0][0] == "O", trigger

    def test_current_revision_is_at_or_after_a1(self, clean: None) -> None:
        # 이 테스트 모듈이 전제하는 리비전이 체인에 있다.
        from alembic.script import ScriptDirectory

        script = ScriptDirectory.from_config(_alembic_cfg())
        assert script.get_revision(_REVISION).down_revision == _PREV_REVISION
