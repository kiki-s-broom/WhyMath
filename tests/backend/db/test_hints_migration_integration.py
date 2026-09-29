"""hints 마이그레이션 왕복 + CHECK·FK 실발화 + store writer/reader 실 PG 왕복 — S4-11
(WHYMATH_RUN_INTEGRATION).

마이그레이션 head가 적용된 **실 PostgreSQL**에서 리비전 `9d3e6b1f4a27`(S4-11)을 검증한다. CI
`backend — 마이그레이션·통합 (실 PG)` 잡이 이미 `alembic downgrade base → upgrade head` 전구간
왕복을 돌리므로, 이 파일은 그 위에서 *이 리비전이 무엇을 더하고/되돌리는지*와 *DB 제약이 실제로
막는지*, 그리고 *유일 writer·reader가 실 PG에서 왕복하는지*를 못 박는다. PG 미도달 또는 이
리비전 미적용이면 graceful skip(`test_concept_version_migration_integration.py` 미러).

검증(S4-11 핵심):
  ① head에서 `hints` 테이블·제약(CHECK 3·UNIQUE·FK 2)·서빙 인덱스 존재.
  ② revision-local 왕복(downgrade → `8c19e8a611e4` → upgrade head)이 대칭.
  ③ **CHECK 실발화 — RED/GREEN 양면**: level=4(전체 풀이) 삽입은 CHECK가 거부(RED) · level=2는
     CHECK를 통과해 FK 단계까지 간다(GREEN 대조군 — CHECK가 모든 삽입을 막는 것이 아님).
  ④ store 왕복: 부모(문제·풀이 경로) 위에 `write_hints` → `find_served_hint`가 검수 힌트만 서빙 ·
     두 번째 `write_hints`는 전부 unchanged(헌법 R3-01) · 미검수 행은 서빙 안 됨.
  ⑤ 원천 로더 → 생성 → 게이트 → 적재 → 서빙 관통: 실 `problem_step`(S4-09 단계 좌석)에 심은
     경로를 `load_path_inputs`가 읽고 `build_path_hints`가 만든 검수 힌트가 coach reader로 나온다.
     전부 커밋하지 않은 한 트랜잭션 안에서 돌고 되돌린다(다른 테스트의 DB에 흔적 0).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from whymath_backend.config import Settings

pytestmark = pytest.mark.integration

_REVISION = "9d3e6b1f4a27"
_PREV_REVISION = "8c19e8a611e4"
_BACKEND_DIR = Path(__file__).resolve().parents[3] / "src" / "backend"
_ALEMBIC_DIR = _BACKEND_DIR / "alembic"


def _sync_engine() -> object:
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    settings = Settings()
    if settings.db_disable_pool:
        return create_engine(settings.sync_database_url, poolclass=NullPool)
    return create_engine(settings.sync_database_url)


def _reachable() -> bool:
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.connect() as conn:  # type: ignore[attr-defined]
            conn.execute(text("SELECT count(*) FROM hints"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def _skip_if_unreachable() -> None:
    if not _reachable():
        pytest.skip(
            "PostgreSQL 미도달(또는 hints 리비전 미적용) — 통합 테스트 건너뜀 "
            "(WHYMATH_DATABASE_URL·alembic upgrade head 확인)"
        )


def _alembic_config() -> object:
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(_ALEMBIC_DIR))
    cfg.set_main_option("sqlalchemy.url", "")
    return cfg


def _table_exists(table: str) -> bool:
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.connect() as conn:  # type: ignore[attr-defined]
            found = conn.execute(
                text("SELECT 1 FROM information_schema.tables WHERE table_name = :t"),
                {"t": table},
            ).first()
        return found is not None
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def _constraint_names(table: str) -> set[str]:
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.connect() as conn:  # type: ignore[attr-defined]
            rows = conn.execute(
                text(
                    "SELECT conname FROM pg_constraint c JOIN pg_class t ON c.conrelid = t.oid "
                    "WHERE t.relname = :t"
                ),
                {"t": table},
            ).all()
            idx = conn.execute(
                text("SELECT indexname FROM pg_indexes WHERE tablename = :t"), {"t": table}
            ).all()
        return {r[0] for r in rows} | {r[0] for r in idx}
    finally:
        engine.dispose()  # type: ignore[attr-defined]


class TestHintsMigration:
    def test_head_has_table_constraints_and_serving_index(self) -> None:
        _skip_if_unreachable()
        names = _constraint_names("hints")
        for expected in (
            "pk_hints",
            "ck_hints_level_graded_1_3",
            "ck_hints_reveal_score_unit",
            "ck_hints_step_order_positive",
            "uq_hints_step_level",
            "fk_hints_problem_id_problem",
            "fk_hints_solution_path_id_solution_paths",
            "idx_hints_serving",
        ):
            assert expected in names, f"{expected} 부재 — 실제: {sorted(names)}"

    def test_downgrade_then_upgrade_removes_and_restores(self) -> None:
        _skip_if_unreachable()
        from alembic import command

        cfg = _alembic_config()
        try:
            command.downgrade(cfg, _PREV_REVISION)  # type: ignore[arg-type]
            assert not _table_exists("hints")
        finally:
            command.upgrade(cfg, "head")  # type: ignore[arg-type]
        assert _table_exists("hints")

    def test_check_rejects_level_four_but_not_level_two(self) -> None:
        """③ RED/GREEN 양면 — CHECK는 4를 막고, 2는 CHECK를 지나 FK에서 멈춘다."""
        _skip_if_unreachable()
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError

        insert = text(
            "INSERT INTO hints (hint_id, solution_path_id, step_order, problem_id, level, content,"
            " reveal_score, generator_version) VALUES (:h, 'sp-none', 1, :p, :lv, 'x', 0.5, 't')"
        )
        engine = _sync_engine()
        try:
            with engine.connect() as conn:  # type: ignore[attr-defined]
                with pytest.raises(IntegrityError) as red:
                    with conn.begin():
                        conn.execute(insert, {"h": "it-l4", "p": uuid.uuid4(), "lv": 4})
                assert "ck_hints_level_graded_1_3" in str(red.value)
                with pytest.raises(IntegrityError) as green:
                    with conn.begin():
                        conn.execute(insert, {"h": "it-l2", "p": uuid.uuid4(), "lv": 2})
                # 대조군: CHECK가 아니라 FK(부모 부재)에서 거부된다 = CHECK는 2를 통과시켰다.
                assert "ck_hints_level_graded_1_3" not in str(green.value)
                assert "fk_hints" in str(green.value)
        finally:
            engine.dispose()  # type: ignore[attr-defined]


class TestStoreRoundTripOnRealPg:
    async def test_write_serve_and_rewrite_idempotently(self) -> None:
        _skip_if_unreachable()
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from whymath_backend.l4.hint_content import store
        from whymath_backend.l4.hint_content.gates import GateContext, evaluate_gates
        from whymath_backend.l4.hint_content.generator import (
            ConceptRef,
            StepSource,
            generate_step_hints,
        )

        steps = ("x**2 - 5*x + 6", "(x - 2)*(x - 3)", "x = 2, x = 3")
        pid = uuid.uuid4()
        path_id = f"sp-it-{pid.hex[:12]}"
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
        unverified_l1 = hints[0].model_copy(update={"verified": False})

        engine = create_async_engine(Settings().database_url)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with maker() as session:
                labels = {}
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
                first = await store.write_hints(
                    session, [unverified_l1, *hints[1:]], processed_path_ids=[path_id]
                )
                assert first.inserted == 3
                # 미검수 L1은 서빙되지 않는다 · 검수 L2는 서빙된다.
                assert (
                    await store.find_served_hint(
                        session, problem_id=pid, hint_level=1, from_step_order=1
                    )
                    is None
                )
                served = await store.find_served_hint(
                    session, problem_id=pid, hint_level=2, from_step_order=1
                )
                assert served is not None and served.step_order == 2
                second = await store.write_hints(
                    session, [unverified_l1, *hints[1:]], processed_path_ids=[path_id]
                )
                assert (second.inserted, second.updated, second.unchanged) == (0, 0, 3)
                await session.rollback()  # 흔적 0 — 부모·힌트 모두 되돌린다
        finally:
            await engine.dispose()


async def _seed_problem(session: object, pid: uuid.UUID, *, answer: str | None) -> None:
    """최소 문제 행(열거형 라벨은 DB에서 첫 값을 읽는다 — 루프 KPI 통합테스트 선례)."""
    from sqlalchemy import text

    labels: dict[str, str] = {}
    for enum in ("source_type_enum", "curriculum_enum", "subject_enum"):
        labels[enum] = (
            await session.execute(  # type: ignore[attr-defined]
                text(f"SELECT unnest(enum_range(NULL::{enum}))::text LIMIT 1")
            )
        ).scalar_one()
    await session.execute(  # type: ignore[attr-defined]
        text(
            "INSERT INTO problem (problem_id, source_type, curriculum_version,"
            " valid_from_year, subject, unit_codes, answer) VALUES (:p,"
            " CAST(:st AS source_type_enum), CAST(:cv AS curriculum_enum), 2015,"
            " CAST(:sj AS subject_enum), '{}', :ans)"
        ),
        {
            "p": pid,
            "st": labels["source_type_enum"],
            "cv": labels["curriculum_enum"],
            "sj": labels["subject_enum"],
            "ans": answer,
        },
    )


class TestLoaderToServingOnRealPg:
    async def test_seeded_path_flows_from_problem_step_to_coach_reader(self) -> None:
        _skip_if_unreachable()
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from whymath_backend.l4.hint_content import store
        from whymath_backend.l4.hint_content.populate import build_path_hints

        steps = ("x**2 - 5*x + 6", "(x - 2)*(x - 3)", "x = 2, x = 3")
        pid = uuid.uuid4()
        path_id = f"sp-it-load-{pid.hex[:12]}"
        engine = create_async_engine(Settings().database_url)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with maker() as session:
                await _seed_problem(session, pid, answer="x = 2 또는 x = 3")
                await session.execute(
                    text(
                        "INSERT INTO solution_paths (solution_path_id, problem_id, approach_type)"
                        " VALUES (:sp, :p, 'algebraic')"
                    ),
                    {"sp": path_id, "p": pid},
                )
                # 원자 축 개념 1개(단계 2에 매칭) + 축 밖 코드(단계 3 — 구 437 UC 흉내).
                atom_code = f"it-atom-{pid.hex[:12]}"
                await session.execute(
                    text(
                        "INSERT INTO atom_node (code, name_ko, level, review_status)"
                        " VALUES (:c, '인수분해', '세부개념', 'reviewed')"
                    ),
                    {"c": atom_code},
                )
                step_codes = (None, atom_code, f"legacy-uc-{pid.hex[:12]}")
                for order, (content, verified, code) in enumerate(
                    zip(steps, (False, True, True), step_codes, strict=True), start=1
                ):
                    await session.execute(
                        text(
                            "INSERT INTO problem_step (problem_id, step_order, expected_answer,"
                            " solution_path_id, sympy_verified, concept_node_id)"
                            " VALUES (:p, :o, :c, :sp, :v, :cn)"
                        ),
                        {
                            "p": pid,
                            "o": order,
                            "c": content,
                            "sp": path_id,
                            "v": verified,
                            "cn": code,
                        },
                    )
                inputs, report = await store.load_path_inputs(session)
                mine = [p for p in inputs if p.solution_path_id == path_id]
                assert len(mine) == 1, report
                path = mine[0]
                assert path.step_contents == steps
                assert path.step_verified == (False, True, True)
                assert path.final_answer == "x = 2 또는 x = 3"
                # 이름은 실 PG 원자 축(atom_node)에서 해석 — 축 밖 코드·미매핑은 None(날조 금지).
                # 문항-개념 매핑(problem_concept)은 심지 않아 문제 대표 개념 폴백도 없다.
                assert path.step_concepts[0] is None
                assert path.step_concepts[1] is not None
                assert (path.step_concepts[1].name, path.step_concepts[1].source) == (
                    "인수분해",
                    "step",
                )
                assert path.step_concepts[2] is None
                assert report.concept_codes_off_axis >= 1

                result = build_path_hints(path)
                # 2단계는 개념이 있어 L1~L3, 3단계(마지막·축 밖)는 L2만.
                assert sorted((h.solution_step_ref.step_order, h.level) for h in result.hints) == [
                    (2, 1),
                    (2, 2),
                    (2, 3),
                    (3, 2),
                ]
                counts = await store.write_hints(
                    session, list(result.hints), processed_path_ids=[path_id]
                )
                assert counts.inserted == len(result.hints)
                served = await store.find_served_hint(
                    session,
                    problem_id=pid,
                    hint_level=2,
                    from_step_order=store.serving_step_order(["x**2 - 5*x + 6"]),
                )
                assert served is not None and served.step_order == 2
                assert served.reveal_score == 2 / 3
                await session.rollback()  # 흔적 0
        finally:
            await engine.dispose()
