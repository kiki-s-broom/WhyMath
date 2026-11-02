"""P3-32 — corpus replay `--only-existing-problems`: DB에 문항 행이 있는 대상만 재생한다.

`verified_solutions.problem_id`는 FK가 아니라 느슨참조라, 코퍼스 일부만 적재된 운영 DB에 전 은행을
재생하면 가리킬 문항이 없는 풀이 행이 쌓인다. 이 파일은 ① 순수 필터가 없는 문항을 빼고 순서를
보존한다 ② 실 PG에서 옵션이 없는 문항을 재생하지 않고 그 수를 보고한다 ③ 대상이 전부 없으면
0건 재생을 성공으로 보고하지 않는다(exit 1) — 를 못 박는다.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from whymath_backend.config import Settings
from whymath_backend.whs import corpus_replay
from whymath_backend.whs.corpus_replay import ReplayItem, keep_existing


def _item(slug: str) -> ReplayItem:
    return ReplayItem(
        problem_id=uuid.uuid5(uuid.NAMESPACE_URL, f"whymath:test:p3-32:{slug}"),
        slug=slug,
        conditions="x**2 - 3*x - 10 = 0",
        answer_map={"x": "5"},
        steps=("x**2 - 3*x - 10", "(x - 5)*(x + 2)"),
    )


# ── 순수부 ───────────────────────────────────────────────────────────


def test_keep_existing_drops_missing_and_keeps_order() -> None:
    a, b, c = _item("a"), _item("b"), _item("c")
    kept, skipped = keep_existing([a, b, c], {c.problem_id, a.problem_id})
    assert [i.slug for i in kept] == ["a", "c"]
    assert skipped == 1


def test_keep_existing_none_exist() -> None:
    kept, skipped = keep_existing([_item("a"), _item("b")], set())
    assert kept == []
    assert skipped == 2


def test_keep_existing_all_exist() -> None:
    items = [_item("a"), _item("b")]
    kept, skipped = keep_existing(items, {i.problem_id for i in items})
    assert kept == items
    assert skipped == 0


def test_report_json_carries_skipped_count() -> None:
    report = corpus_replay.ReplayReport()
    report.skipped_problem_missing = 3
    assert report.to_json()["skipped_problem_missing"] == 3


# ── 통합(실 PG · 기본 SKIP) ──────────────────────────────────────────

_SECRET = "integration-jwt-secret-0123456789abcdef"


def _settings() -> Settings:
    return Settings(jwt_secret_key=SecretStr(_SECRET))


async def _pg_reachable() -> bool:
    engine = create_async_engine(_settings().database_url)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


async def _insert_problem(pid: uuid.UUID) -> None:
    engine = create_async_engine(_settings().database_url)
    try:
        sm = async_sessionmaker(engine, expire_on_commit=False)
        async with sm() as session:
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
            await session.commit()
    finally:
        await engine.dispose()


async def _count_solutions(pids: list[uuid.UUID]) -> dict[str, int]:
    engine = create_async_engine(_settings().database_url)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT problem_id::text, count(*) FROM verified_solutions"
                    " WHERE problem_id = ANY(:pids) GROUP BY 1"
                ),
                {"pids": [str(p) for p in pids]},
            )
            return {str(r[0]): int(r[1]) for r in rows}
    finally:
        await engine.dispose()


async def _cleanup(pids: list[uuid.UUID]) -> None:
    engine = create_async_engine(_settings().database_url)
    ids = [str(p) for p in pids]
    try:
        async with engine.begin() as conn:
            for table in ("verified_solutions", "solution_nodes", "dead_end_log", "problem"):
                await conn.execute(
                    text(f"DELETE FROM {table} WHERE problem_id = ANY(:pids)"),  # noqa: S608
                    {"pids": ids},
                )
    finally:
        await engine.dispose()


def _write_corpus(tmp_path: Path, items: list[ReplayItem]) -> Path:
    path = tmp_path / "problems.jsonl"
    lines = [
        json.dumps(
            {
                "problem_id": str(i.problem_id),
                "slug": i.slug,
                "verify": {
                    "conditions": i.conditions,
                    "answer_map": i.answer_map,
                    "solution_steps": list(i.steps),
                },
            }
        )
        for i in items
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


@pytest.mark.integration
def test_only_existing_skips_missing_problem_on_live_pg(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")
    present = ReplayItem(
        problem_id=uuid.uuid4(),
        slug="p3-32-present",
        conditions="x**2 - 3*x - 10 = 0",
        answer_map={"x": "5"},
        steps=("x**2 - 3*x - 10", "(x - 5)*(x + 2)"),
    )
    absent = ReplayItem(
        problem_id=uuid.uuid4(),
        slug="p3-32-absent",
        conditions="x**2 - 3*x - 10 = 0",
        answer_map={"x": "5"},
        steps=("x**2 - 3*x - 10", "(x - 5)*(x + 2)"),
    )
    pids = [present.problem_id, absent.problem_id]
    corpus = _write_corpus(tmp_path, [present, absent])
    try:
        asyncio.run(_insert_problem(present.problem_id))
        rc = corpus_replay.main([str(corpus), "--no-bad-branch", "--only-existing-problems"])
        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert payload["total_records"] == 1
        assert payload["finalized_verified"] == 1
        assert payload["skipped_problem_missing"] == 1
        counts = asyncio.run(_count_solutions(pids))
        # 문항이 있는 쪽만 풀이 행이 생기고, 없는 쪽은 고아 행이 생기지 않는다.
        assert counts.get(str(present.problem_id)) == 1
        assert str(absent.problem_id) not in counts
    finally:
        asyncio.run(_cleanup(pids))


@pytest.mark.integration
def test_only_existing_refuses_when_none_exist_on_live_pg(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")
    absent = ReplayItem(
        problem_id=uuid.uuid4(),
        slug="p3-32-none",
        conditions="x**2 - 3*x - 10 = 0",
        answer_map={"x": "5"},
        steps=("x**2 - 3*x - 10", "(x - 5)*(x + 2)"),
    )
    corpus = _write_corpus(tmp_path, [absent])
    try:
        rc = corpus_replay.main([str(corpus), "--no-bad-branch", "--only-existing-problems"])
        out = capsys.readouterr().out
        assert rc == 1
        assert "replay 대상 0건" in out
        assert asyncio.run(_count_solutions([absent.problem_id])) == {}
    finally:
        asyncio.run(_cleanup([absent.problem_id]))
