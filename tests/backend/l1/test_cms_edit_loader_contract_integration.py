"""CMS 편집 ↔ CLI 적재 덮어쓰기 계약 *통합테스트* (P3-25 · WHYMATH_RUN_INTEGRATION · 실 PG).

계약 정본: `docs/standards/cms_edit_vs_loader_contract.md`. 이 파일은 그 계약의 **집행 증거**다 —
"CMS로 고친 행은 다음 적재에 보존되거나 충돌로 보고된다"를 5개 리소스(문항·오개념·교수전략·개념
설명·힌트) 각각에 대해 *실제 적재 코드*를 실 PostgreSQL에 돌려 확인한다.

모든 리소스가 같은 4단 시나리오를 거친다(대조군 포함 — 보호가 "모든 행을 막는" 과잉 수정이 아님을
함께 증명한다):

  ① 두 행(A·B)을 적재한다(코퍼스 값 v1).
  ② A만 **CMS가 쓰는 그 코드**(`validate_changes` + `apply_changes`)로 고친다 — B는 건드리지 않는다.
  ③ 코퍼스 값 v2로 **다시 적재**한다 → A는 사람의 값 그대로·충돌로 보고 / B는 v2로 갱신(대조군).
  ④ `overwrite_cms_edits=True`로 다시 적재한다 → A도 v2·표지가 비워진다(적재가 다시 소유).
     표지가 풀린 뒤에는 보호 없이 갱신된다(영구 잠금이 아니다).

**RED→GREEN**: 보호를 끈 상태(`upsert_guard`가 가드 없음을 돌려주게 주입)에서는 ③이 실패해야 한다 —
세션 증적은 계약 문서 §6에 있다. 보호가 켜진 이 파일은 GREEN이다.

PG 미도달 또는 `cms_edited_at` 컬럼 미적용(마이그레이션 `e7b2c4d8a1f6`)이면 graceful skip. 만든 행만
삭제한다(공유 DB 보호). 힌트는 커밋하지 않는 한 트랜잭션 안에서 돌고 되돌린다.
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.api.admin_cms_resources import apply_changes, get_resource, validate_changes
from whymath_backend.config import Settings

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_PROBLEM_CORPUS = _ROOT / "data" / "corpus" / "problem_bank_v1" / "problems.jsonl"
_HUMAN = "사람이 CMS에서 고친 값"


def _sync_engine() -> Any:
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    settings = Settings()
    if settings.db_disable_pool:
        return create_engine(settings.sync_database_url, poolclass=NullPool)
    return create_engine(settings.sync_database_url)


def _skip_unless_marker_column_exists() -> None:
    """5개 테이블에 `cms_edited_at`이 있어야 한다 — 없으면 PG 미도달 또는 리비전 미적용."""
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.connect() as conn:
            for table in (
                "problem",
                "misconception_catalog",
                "strategy_node",
                "concept_content",
                "hints",
            ):
                conn.execute(text(f"SELECT cms_edited_at FROM {table} LIMIT 0"))
    except Exception:
        pytest.skip("PG 미도달 또는 리비전 e7b2c4d8a1f6(cms_edited_at) 미적용 — 통합 건너뜀")
    finally:
        engine.dispose()


@pytest.fixture
def engine() -> Iterator[Any]:
    _skip_unless_marker_column_exists()
    eng = _sync_engine()
    try:
        yield eng
    finally:
        eng.dispose()


def _tag() -> str:
    return uuid.uuid4().hex[:8]


def _cms_edit(engine: Any, model: type[Any], key: object, resource: str, changes: dict[str, Any]):
    """CMS 편집 라우트가 쓰는 *그 함수*(검증→적용)로 행을 고치고 commit한다. 반환=고친 필드 목록."""
    from sqlalchemy.orm import Session

    spec = get_resource(resource)
    coerced = validate_changes(spec, changes)
    with Session(engine) as session:
        row = session.get(model, key)
        assert row is not None, f"편집 대상 행이 없다: {resource}:{key}"
        changed, _resets = apply_changes(spec, row, coerced)
        session.commit()
    assert changed, "편집이 아무 필드도 바꾸지 못했다 — 시나리오 설정 오류"
    return changed


def _read(engine: Any, model: type[Any], key: object, *columns: str) -> tuple[Any, ...]:
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        row = session.get(model, key)
        assert row is not None, f"행이 없다: {model.__tablename__}:{key}"
        return tuple(getattr(row, c) for c in columns)


# ─────────────────────────────────────────────────────────────────────────
# ① 교수전략 (strategy_node)
# ─────────────────────────────────────────────────────────────────────────
def test_strategy_node_cms_edit_survives_reload(engine: Any) -> None:
    from sqlalchemy import text

    from whymath_backend.db.models.strategy_node import StrategyNode
    from whymath_backend.l1.strategy_graph.strategy_node_projection import (
        StrategyNodeRecord,
        StrategyNodeStore,
        populate_strategy_nodes,
    )

    tag = _tag()
    a, b = f"it-p325.{tag}.a", f"it-p325.{tag}.b"

    def rec(sid: str, description: str) -> StrategyNodeRecord:
        return StrategyNodeRecord(
            strategy_id=sid,
            name_ko="원본 이름",
            family="reduction",
            description=description,
            standard_codes=(),
        )

    store = StrategyNodeStore(settings=Settings())
    try:
        assert populate_strategy_nodes([rec(a, "v1"), rec(b, "v1")], store=store) == 2
        _cms_edit(engine, StrategyNode, a, "strategy_node", {"description": _HUMAN})
        assert _read(engine, StrategyNode, a, "cms_edited_at")[0] is not None
        assert _read(engine, StrategyNode, b, "cms_edited_at")[0] is None

        conflicts: list[str] = []
        written = populate_strategy_nodes(
            [rec(a, "v2"), rec(b, "v2")], store=store, conflicts=conflicts
        )
        assert written == 1, "건너뛴 행을 적재 건수에 세면 보호가 일했는지 알 수 없다"
        assert conflicts == [f"strategy_node:{a}"]
        assert _read(engine, StrategyNode, a, "description")[0] == _HUMAN, "A의 편집이 소실됐다"
        assert _read(engine, StrategyNode, b, "description")[0] == "v2", "대조군 B는 갱신돼야 한다"

        overwritten: list[str] = []
        assert (
            populate_strategy_nodes(
                [rec(a, "v2"), rec(b, "v2")],
                store=store,
                overwrite_cms_edits=True,
                conflicts=overwritten,
            )
            == 2
        )
        assert overwritten == []
        assert _read(engine, StrategyNode, a, "description", "cms_edited_at") == ("v2", None)

        # 표지가 풀린 뒤에는 영구 잠금이 아니다 — 보호 모드 적재가 다시 갱신한다.
        assert populate_strategy_nodes([rec(a, "v3")], store=store) == 1
        assert _read(engine, StrategyNode, a, "description")[0] == "v3"
    finally:
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM strategy_node WHERE strategy_id = ANY(:ids)"), {"ids": [a, b]}
            )


# ─────────────────────────────────────────────────────────────────────────
# ② 개념 설명 (concept_content) — 편집뿐 아니라 검수 표시도 보호
# ─────────────────────────────────────────────────────────────────────────
def test_concept_content_cms_edit_survives_reload(engine: Any) -> None:
    from sqlalchemy import text

    from whymath_backend.db.models.concept_content import ConceptContent
    from whymath_backend.l1.concept_content.projection import (
        ConceptContentRecord,
        ConceptContentStore,
        populate_concept_content,
    )

    tag = _tag()
    a, b = f"IT-P325-{tag}-A", f"IT-P325-{tag}-B"

    def rec(code: str, explanation: str) -> ConceptContentRecord:
        return ConceptContentRecord(
            code=code,
            scope="K-12",
            name="통합 개념",
            subject="수학",
            unit=None,
            metaphor="비유",
            misconception=None,
            formal_definition_internal=None,
            accepted_expressions=None,
            explanation=explanation,
            standard_codes=(),
            flashcards=(),
            review_status="ai_estimated",
        )

    store = ConceptContentStore(settings=Settings())
    try:
        assert populate_concept_content([rec(a, "v1"), rec(b, "v1")], store=store) == 2
        _cms_edit(engine, ConceptContent, a, "concept_content", {"explanation": _HUMAN})

        conflicts: list[str] = []
        written = populate_concept_content(
            [rec(a, "v2"), rec(b, "v2")], store=store, conflicts=conflicts
        )
        assert written == 1
        assert conflicts == [f"concept_content:{a}"]
        assert _read(engine, ConceptContent, a, "explanation")[0] == _HUMAN
        assert _read(engine, ConceptContent, b, "explanation")[0] == "v2"

        # 검수 승격 CLI(`mark_review_status`)도 고친 본문에는 `reviewed`를 찍지 않는다.
        review_conflicts: list[str] = []
        updated = store.mark_review_status([a, b], "reviewed", conflicts=review_conflicts)
        assert updated == 1
        assert review_conflicts == [f"concept_content:{a}"]
        assert _read(engine, ConceptContent, a, "review_status")[0] == "ai_estimated"
        assert _read(engine, ConceptContent, b, "review_status")[0] == "reviewed"

        assert populate_concept_content([rec(a, "v2")], store=store, overwrite_cms_edits=True) == 1
        assert _read(engine, ConceptContent, a, "explanation", "cms_edited_at") == ("v2", None)
    finally:
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM concept_content WHERE code = ANY(:ids)"), {"ids": [a, b]}
            )


# ─────────────────────────────────────────────────────────────────────────
# ③ 오개념 (misconception_catalog)
# ─────────────────────────────────────────────────────────────────────────
def test_misconception_cms_edit_survives_reload(engine: Any) -> None:
    from sqlalchemy import text

    from whymath_backend.db.models.misconception_catalog import (
        MisconceptionCatalog as MisconceptionORM,
    )
    from whymath_backend.l1.misconception.catalog_loader import MisconceptionCatalogStore
    from whymath_backend.schema.misconception_catalog import MisconceptionCatalog

    tag = _tag()
    a, b = f"ITP325-{tag}-A", f"ITP325-{tag}-B"

    def rec(mis_id: str, statement: str) -> MisconceptionCatalog:
        return MisconceptionCatalog(mis_id=mis_id, canonical_statement=statement)

    store = MisconceptionCatalogStore(settings=Settings())
    try:
        assert store.populate([rec(a, "v1"), rec(b, "v1")]) == 2
        _cms_edit(engine, MisconceptionORM, a, "misconception", {"canonical_statement": _HUMAN})

        conflicts: list[str] = []
        written = store.populate([rec(a, "v2"), rec(b, "v2")], conflicts=conflicts)
        assert written == 1
        assert conflicts == [f"misconception_catalog:{a}"]
        assert _read(engine, MisconceptionORM, a, "canonical_statement")[0] == _HUMAN
        assert _read(engine, MisconceptionORM, b, "canonical_statement")[0] == "v2"

        assert store.populate([rec(a, "v2")], overwrite_cms_edits=True) == 1
        assert _read(engine, MisconceptionORM, a, "canonical_statement", "cms_edited_at") == (
            "v2",
            None,
        )
    finally:
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM misconception_catalog WHERE mis_id = ANY(:ids)"),
                {"ids": [a, b]},
            )


# ─────────────────────────────────────────────────────────────────────────
# ④ 문항 (problem) — 본문뿐 아니라 사람이 정한 검수·격리 상태도 되돌아가지 않는다
# ─────────────────────────────────────────────────────────────────────────
def test_problem_cms_edit_and_quarantine_survive_reload(
    engine: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import text

    from whymath_backend.db.cms_edit_marker import mark_cms_edited
    from whymath_backend.db.models.problem import Problem as ProblemORM
    from whymath_backend.l1.problem_bank.populate import (
        ProblemBankStore,
        load_problem_bank_records,
    )
    from whymath_backend.schema.enums import ReviewStatus

    if not _PROBLEM_CORPUS.exists():
        pytest.skip(f"문제 코퍼스 미존재: {_PROBLEM_CORPUS}")

    tag = _tag()
    base = load_problem_bank_records(_PROBLEM_CORPUS)[0]
    slugs = [f"it-p325-{tag}-a", f"it-p325-{tag}-b"]

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
    # 개념 해석 맵은 이 시나리오의 관심사가 아니다 — 크로스워크 파일 없이 빈 맵으로 둔다.
    monkeypatch.setattr(store, "_load_source_id_to_concept_id", lambda: {})
    try:
        report = store.populate([rec(slugs[0], "v1"), rec(slugs[1], "v1")])
        assert report.problems_loaded == 2 and report.cms_edit_conflicts == []

        with engine.connect() as conn:
            ids = {
                slug: pid
                for slug, pid in conn.execute(
                    text("SELECT slug, problem_id FROM problem WHERE slug = ANY(:s)"),
                    {"s": slugs},
                )
            }
        a_id, b_id = ids[slugs[0]], ids[slugs[1]]

        # A: CMS 편집(본문) + 관리자 검수 큐의 격리 — 둘 다 사람이 정한 상태다.
        _cms_edit(engine, ProblemORM, a_id, "problem", {"answer": _HUMAN})
        from sqlalchemy.orm import Session

        with Session(engine) as session:
            row = session.get(ProblemORM, a_id)
            row.review_status = ReviewStatus.quarantined
            row.quarantine_reason = "사람이 격리함"
            mark_cms_edited(row)
            session.commit()

        report = store.populate([rec(slugs[0], "v2"), rec(slugs[1], "v2")])
        assert report.problems_loaded == 1, "건너뛴 문항을 적재 건수에 세면 안 된다"
        assert report.cms_edit_conflicts == [f"problem:{slugs[0]}"]
        answer, status, reason = _read(
            engine, ProblemORM, a_id, "answer", "review_status", "quarantine_reason"
        )
        assert answer == _HUMAN, "A의 편집이 소실됐다"
        assert status == ReviewStatus.quarantined, "격리가 코퍼스 초기 상태로 되돌아갔다"
        assert reason == "사람이 격리함"
        assert _read(engine, ProblemORM, b_id, "answer")[0] == "v2", "대조군 B는 갱신돼야 한다"

        report = store.populate(
            [rec(slugs[0], "v2"), rec(slugs[1], "v2")], overwrite_cms_edits=True
        )
        assert report.problems_loaded == 2 and report.cms_edit_conflicts == []
        answer, marker = _read(engine, ProblemORM, a_id, "answer", "cms_edited_at")
        assert (answer, marker) == ("v2", None)
    finally:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "DELETE FROM problem_concept WHERE problem_id IN "
                    "(SELECT problem_id FROM problem WHERE slug = ANY(:s))"
                ),
                {"s": slugs},
            )
            conn.execute(
                text(
                    "DELETE FROM content_provenance WHERE problem_id IN "
                    "(SELECT problem_id FROM problem WHERE slug = ANY(:s))"
                ),
                {"s": slugs},
            )
            conn.execute(text("DELETE FROM problem WHERE slug = ANY(:s)"), {"s": slugs})


# ─────────────────────────────────────────────────────────────────────────
# ⑤ 힌트 (hints) — 재생성이 사람의 문구를 되돌리지 않는다 (한 트랜잭션·되돌림)
# ─────────────────────────────────────────────────────────────────────────
async def test_hint_cms_edit_survives_regeneration() -> None:
    _skip_unless_marker_column_exists()
    from sqlalchemy import select, text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from whymath_backend.db.models.hint import Hint as HintORM
    from whymath_backend.l4.hint_content import store
    from whymath_backend.l4.hint_content.gates import GateContext, evaluate_gates
    from whymath_backend.l4.hint_content.generator import (
        ConceptRef,
        StepSource,
        generate_step_hints,
    )

    steps = ("x**2 - 5*x + 6", "(x - 2)*(x - 3)", "x = 2, x = 3")
    pid = uuid.uuid4()
    path_id = f"sp-it-p325-{pid.hex[:12]}"
    concept = ConceptRef("math.algebra.factoring", "인수분해", "step")
    source = StepSource(
        solution_path_id=path_id,
        problem_id=pid,
        step_order=2,
        step_contents=steps,
        transition_verified=True,
        concept=concept,
    )
    ctx = GateContext(step_contents=steps, concept_name=concept.name, final_answer="123")
    hints = [evaluate_gates(d, ctx) for d in generate_step_hints(source).drafts]
    assert len(hints) == 3

    engine = create_async_engine(Settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as session:
            labels: dict[str, str] = {}
            for enum in ("source_type_enum", "curriculum_enum", "subject_enum"):
                labels[enum] = (
                    await session.execute(
                        text(f"SELECT unnest(enum_range(NULL::{enum}))::text LIMIT 1")
                    )
                ).scalar_one()
            await session.execute(
                text(
                    "INSERT INTO problem (problem_id, source_type, curriculum_version,"
                    " valid_from_year, subject, unit_codes) VALUES (:p,"
                    " CAST(:st AS source_type_enum), CAST(:cv AS curriculum_enum), 2015,"
                    " CAST(:sj AS subject_enum), '{}')"
                ),
                {
                    "p": pid,
                    "st": labels["source_type_enum"],
                    "cv": labels["curriculum_enum"],
                    "sj": labels["subject_enum"],
                },
            )
            await session.execute(
                text(
                    "INSERT INTO solution_paths (solution_path_id, problem_id, approach_type)"
                    " VALUES (:sp, :p, 'algebraic')"
                ),
                {"sp": path_id, "p": pid},
            )
            first = await store.write_hints(session, hints, processed_path_ids=[path_id])
            assert first.inserted == 3 and first.cms_edit_conflicts == []

            # CMS가 쓰는 그 코드로 L2 힌트 문구를 고친다.
            edited = hints[1]
            spec = get_resource("hint")
            row = (
                await session.execute(select(HintORM).where(HintORM.hint_id == edited.hint_id))
            ).scalar_one()
            changed, _ = apply_changes(spec, row, validate_changes(spec, {"content": _HUMAN}))
            assert changed == ["content"] and row.cms_edited_at is not None
            await session.flush()

            # 재생성(같은 hint_id·원래 문구) — 사람의 문구가 보존되고 충돌로 보고된다.
            second = await store.write_hints(session, hints, processed_path_ids=[path_id])
            assert second.cms_edit_conflicts == [f"hints:{edited.hint_id}"]
            assert (second.inserted, second.updated, second.unchanged) == (0, 0, 2)
            await session.refresh(row)
            assert row.content == _HUMAN, "재생성이 사람의 힌트 문구를 되돌렸다"
            assert row.verified is False, "고친 힌트의 검증 표지가 재생성으로 올라갔다"

            third = await store.write_hints(
                session, hints, processed_path_ids=[path_id], overwrite_cms_edits=True
            )
            assert third.cms_edit_conflicts == [] and third.updated == 1
            await session.refresh(row)
            assert row.content == edited.content and row.cms_edited_at is None
            await session.rollback()  # 흔적 0 — 부모·힌트 모두 되돌린다
    finally:
        await engine.dispose()
