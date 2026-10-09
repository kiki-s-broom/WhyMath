"""CMS 편집 표지 계약 *단위·거버넌스* 테스트 (P3-25 · hermetic — PG 불요).

계약 정본: `docs/standards/cms_edit_vs_loader_contract.md`. 실 DB에서 "편집이 적재에 살아남는다"를 보는
쪽은 `tests/backend/l1/test_cms_edit_loader_contract_integration.py`이고, 이 파일은 PG 없이 CI가 매번
돌릴 수 있는 것만 못 박는다:

  ① 공용 헬퍼(`upsert_guard`·`upsert_skipped`·`mark_cms_edited`·`conflict_summary`)의 모양
  ② 표지가 걸린 테이블 목록의 **일치** — 상수·ORM 컬럼·CMS 리소스 선언·마이그레이션이 같은 5종을 말한다
  ③ **집행 지점 거버넌스** — 보호 대상 모델을 upsert하는 모든 적재 모듈이 `upsert_guard`를 부른다
     (스캔 0건은 실패 · 결함을 주입한 소스로 스캐너의 변별력을 직접 확인)
  ④ 적재 CLI 5종이 `--overwrite-cms-edits`를 같은 의미로 받아 넘기고 충돌을 말한다
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from whymath_backend.api.admin_cms_resources import RESOURCES, ResourceSpec, check_specs
from whymath_backend.db.base import Base
from whymath_backend.db.cms_edit_marker import (
    CMS_EDIT_MARKER,
    CMS_PROTECTED_TABLES,
    OVERWRITE_FLAG,
    conflict_summary,
    format_conflict,
    mark_cms_edited,
    upsert_guard,
    upsert_skipped,
)
from whymath_backend.db.models.problem import Problem

_ROOT = Path(__file__).resolve().parents[3]
_PKG = _ROOT / "src" / "backend" / "whymath_backend"
_MIGRATION = (
    _ROOT
    / "src"
    / "backend"
    / "alembic"
    / "versions"
    / "20261009_0900_e7b2c4d8a1f6_cms_edited_at_marker.py"
)

# ── ① 헬퍼 ────────────────────────────────────────────────────────────────


class TestHelpers:
    def test_guard_mode_adds_is_null_where_and_no_release(self) -> None:
        where, release = upsert_guard(Problem, overwrite=False)
        sql = str(where.compile(dialect=postgresql.dialect()))
        assert sql == "problem.cms_edited_at IS NULL"
        assert release == {}

    def test_overwrite_mode_drops_the_where_and_releases_the_marker(self) -> None:
        where, release = upsert_guard(Problem, overwrite=True)
        assert where is None
        assert release == {CMS_EDIT_MARKER: None}

    def test_guard_on_a_model_without_the_column_fails_loudly(self) -> None:
        class _NoMarker:  # 컬럼이 없는 모델에 보호를 요청하면 조용히 무보호가 되면 안 된다.
            pass

        with pytest.raises(AttributeError):
            upsert_guard(_NoMarker, overwrite=False)

    def test_skipped_means_returning_came_back_empty(self) -> None:
        class _Empty:
            def first(self) -> None:
                return None

        class _OneRow:
            def first(self) -> tuple[int]:
                return (1,)

        assert upsert_skipped(_Empty()) is True
        assert upsert_skipped(_OneRow()) is False

    def test_mark_sets_a_tz_aware_timestamp(self) -> None:
        row = Problem()
        mark_cms_edited(row)
        stamp = getattr(row, CMS_EDIT_MARKER)
        assert stamp is not None and stamp.tzinfo is not None

    def test_mark_refuses_an_object_that_has_no_such_column(self) -> None:
        """컬럼이 없는 객체에 `setattr`하면 파이썬 속성이 조용히 생긴다 — 그래서 거부한다."""
        with pytest.raises(AttributeError):
            mark_cms_edited(SimpleNamespace())

    def test_conflict_summary_is_silent_at_zero_and_names_the_flag_otherwise(self) -> None:
        assert conflict_summary([]) == ""
        text = conflict_summary([format_conflict("problem", "a"), format_conflict("hints", "h")])
        assert "problem:a" in text and "hints:h" in text and OVERWRITE_FLAG in text

    def test_conflict_summary_truncates_the_list_but_keeps_the_count(self) -> None:
        text = conflict_summary([f"problem:{i}" for i in range(25)])
        assert "25건" in text and "외 15건" in text and "problem:24" not in text


# ── ② 표지 대상 5종의 일치 ────────────────────────────────────────────────


class TestProtectedTablesAgree:
    def test_orm_columns_exist_exactly_on_the_protected_tables(self) -> None:
        import whymath_backend.db.models  # noqa: F401  (모델 전부 등록)

        with_column = {
            name for name, table in Base.metadata.tables.items() if CMS_EDIT_MARKER in table.c
        }
        assert with_column == set(CMS_PROTECTED_TABLES)

    def test_marker_column_is_nullable_timestamptz_without_default(self) -> None:
        """기본값을 달면 PG가 기존 행 전체를 백필해 "전 행을 사람이 고쳤다"는 날조가 된다."""
        for name in CMS_PROTECTED_TABLES:
            col = Base.metadata.tables[name].c[CMS_EDIT_MARKER]
            assert col.nullable is True, name
            assert isinstance(col.type, sa.DateTime) and col.type.timezone, name
            assert col.server_default is None and col.default is None, name

    def test_cms_specs_declare_loader_protection_exactly_for_the_protected_tables(self) -> None:
        declared = {s.model.__tablename__ for s in RESOURCES if s.loader_protected}
        editable = {s.model.__tablename__ for s in RESOURCES if s.editable or s.review_column}
        assert declared == set(CMS_PROTECTED_TABLES)
        # 적재가 덮는 경로가 없는 두 리소스는 표지를 두지 않는다(두면 거짓 보호 주장).
        assert {"problem_step", "curriculum_version"} <= editable
        assert not ({"problem_step", "curriculum_version"} & declared)

    def test_migration_adds_the_marker_to_exactly_the_protected_tables(self) -> None:
        text = _MIGRATION.read_text(encoding="utf-8")
        added = set(
            re.findall(r'op\.add_column\(\s*"(\w+)",\s*sa\.Column\("cms_edited_at"', text, re.S)
        )
        dropped = set(re.findall(r'op\.drop_column\("(\w+)", "cms_edited_at"\)', text))
        assert added == set(CMS_PROTECTED_TABLES)
        assert dropped == set(CMS_PROTECTED_TABLES), "downgrade가 upgrade와 비대칭이다"
        assert "server_default" not in text.split("def upgrade")[1].split("def downgrade")[0]

    def test_check_specs_rejects_a_spec_whose_declaration_disagrees_with_the_registry(self) -> None:
        import dataclasses

        problem = next(s for s in RESOURCES if s.key == "problem")
        step = next(s for s in RESOURCES if s.key == "problem_step")
        flipped_off = dataclasses.replace(problem, loader_protected=False)
        flipped_on = dataclasses.replace(step, loader_protected=True)
        for bad in (flipped_off, flipped_on):
            others = tuple(s for s in RESOURCES if s.key != bad.key)
            with pytest.raises(RuntimeError, match="loader_protected"):
                check_specs((*others, bad))


class TestApplyChangesMarking:
    """`apply_changes`가 표지를 채우는 조건 — 바뀐 필드가 있을 때만, 보호 리소스에서만."""

    class _Row(SimpleNamespace):
        cms_edited_at: Any = None

    def test_protected_resource_marks_only_when_something_changed(self) -> None:
        from whymath_backend.api.admin_cms_resources import apply_changes, get_resource

        spec = get_resource("hint")
        row = self._Row(content="옛", verified=True)
        apply_changes(spec, row, {"content": "옛"})
        assert row.cms_edited_at is None, "같은 값 저장이 적재 소유권을 가져갔다"
        apply_changes(spec, row, {"content": "새"})
        assert row.cms_edited_at is not None

    def test_unprotected_resource_never_marks(self) -> None:
        from whymath_backend.api.admin_cms_resources import apply_changes, get_resource

        spec = get_resource("curriculum_version")
        assert isinstance(spec, ResourceSpec) and not spec.loader_protected
        row = self._Row(version_label="옛", effective_from=None, effective_to=None)
        apply_changes(spec, row, {"version_label": "새"})
        assert row.cms_edited_at is None


# ── ③ 집행 지점 거버넌스 ──────────────────────────────────────────────────

#: 보호 대상 ORM 클래스를 upsert할 때 쓰이는 이름(별칭 포함). 새 별칭이 생기면 여기에 더한다.
_PROTECTED_CLASS_NAMES = frozenset(
    {"Problem", "ProblemORM", "MisconceptionCatalogORM", "StrategyNode", "ConceptContent"}
)


def unguarded_protected_upserts(source: str) -> list[str]:
    """보호 대상 모델을 `pg_insert(...)`하면서 `upsert_guard`를 부르지 않는 모듈이면 사유를 돌려준다.

    구성된 호출(AST)을 본다 — 문자열 금지가 아니다. 반환이 비어 있어야 통과다.
    """
    tree = ast.parse(source)
    targets: list[str] = []
    guarded = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name == "upsert_guard":
            guarded = True
        if name in {"pg_insert", "insert"} and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Name) and arg.id in _PROTECTED_CLASS_NAMES:
                targets.append(arg.id)
    if targets and not guarded:
        return [f"{sorted(set(targets))} upsert가 upsert_guard를 거치지 않는다"]
    return []


def _modules_upserting_protected_models() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in sorted(_PKG.rglob("*.py")):
        rel = path.relative_to(_PKG).as_posix()
        if rel.startswith(("db/models/", "schema/")):
            continue
        source = path.read_text(encoding="utf-8")
        if "pg_insert" not in source and "insert(" not in source:
            continue
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and node.args
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id in _PROTECTED_CLASS_NAMES
                and getattr(node.func, "id", getattr(node.func, "attr", ""))
                in {"pg_insert", "insert"}
            ):
                found.setdefault(rel, []).append(node.args[0].id)
    return found


class TestEnforcementPoint:
    def test_every_loader_upserting_a_protected_model_goes_through_the_guard(self) -> None:
        found = _modules_upserting_protected_models()
        # 스캔 0건은 실패다 — 대상을 하나도 못 찾은 전수 가드는 공허하게 통과한다.
        assert found, "보호 대상 upsert를 하나도 못 찾았다 — 스캐너가 눈이 멀었다"
        assert set(found) == {
            "l1/problem_bank/populate.py",
            "l1/misconception/catalog_loader.py",
            "l1/strategy_graph/strategy_node_projection.py",
            "l1/concept_content/projection.py",
        }, f"새 적재 경로가 생겼다 — 보호를 걸고 여기와 계약 문서 §2를 갱신하라: {sorted(found)}"
        for rel in found:
            problems = unguarded_protected_upserts((_PKG / rel).read_text(encoding="utf-8"))
            assert not problems, f"{rel}: {problems}"

    def test_hint_writer_checks_the_marker_before_overwriting(self) -> None:
        source = (_PKG / "l4" / "hint_content" / "store.py").read_text(encoding="utf-8")
        assert re.search(r"row\.cms_edited_at is not None and not overwrite_cms_edits", source)

    def test_scanner_detects_an_injected_unguarded_upsert(self) -> None:
        """스캐너의 변별력 — 가드를 뺀 소스는 잡고, 가드가 있는 소스는 통과시킨다(대조군)."""
        bad = "def f():\n    stmt = pg_insert(StrategyNode).values(a=1)\n"
        good = bad + "    where, rel = upsert_guard(StrategyNode, overwrite=False)\n"
        other = "def f():\n    stmt = pg_insert(SomethingElse).values(a=1)\n"
        assert unguarded_protected_upserts(bad)
        assert unguarded_protected_upserts(good) == []
        assert unguarded_protected_upserts(other) == []

    def test_scanner_catches_the_aliased_and_attribute_call_forms(self) -> None:
        aliased = "def f():\n    s = sqlalchemy.dialects.postgresql.insert(ProblemORM).values()\n"
        assert unguarded_protected_upserts(aliased)


# ── ④ CLI 5종 배선 ───────────────────────────────────────────────────────


def _touch(path: Path) -> Path:
    path.write_text("{}", encoding="utf-8")
    return path


class TestCliWiring:
    def test_strategy_cli(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        from whymath_backend.l1.strategy_graph import populate as cli

        seen: list[dict[str, Any]] = []

        def _populate(records: Any, **kw: Any) -> int:
            seen.append(kw)
            kw["conflicts"].append("strategy_node:s1")
            return 3

        monkeypatch.setattr(cli, "load_strategies_from_graph_json", lambda p: [])
        monkeypatch.setattr(cli, "populate_strategy_nodes", _populate)
        graph = _touch(tmp_path / "graph.json")
        assert cli.main(["--graph", str(graph)]) == 0
        assert cli.main(["--graph", str(graph), OVERWRITE_FLAG]) == 0
        assert [kw["overwrite_cms_edits"] for kw in seen] == [False, True]
        assert "strategy_node:s1" in capsys.readouterr().out

    def test_concept_content_cli(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        from whymath_backend.l1.concept_content import populate as cli

        seen: list[bool] = []

        def _populate(records: Any, **kw: Any) -> int:
            seen.append(kw["overwrite_cms_edits"])
            kw["conflicts"].append("concept_content:c1")
            return 2

        monkeypatch.setattr(cli, "load_concept_content_from_json", lambda p, scope: [])
        monkeypatch.setattr(cli, "populate_concept_content", _populate)
        k12, univ = _touch(tmp_path / "k.json"), _touch(tmp_path / "u.json")
        args = ["--k12", str(k12), "--university", str(univ)]
        assert cli.main(args) == 0
        assert cli.main([*args, OVERWRITE_FLAG]) == 0
        assert seen == [False, False, True, True]
        assert "concept_content:c1" in capsys.readouterr().out

    @pytest.mark.parametrize(
        ("module", "func", "flag_path"),
        [
            (
                "whymath_backend.l1.misconception.populate",
                "load_misconceptions",
                "--misconceptions",
            ),
            (
                "whymath_backend.l1.misconception.populate_atom",
                "load_atom_misconceptions",
                "--graph",
            ),
        ],
    )
    def test_misconception_clis(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: Any,
        module: str,
        func: str,
        flag_path: str,
    ) -> None:
        import importlib

        cli = importlib.import_module(module)
        seen: list[bool] = []

        def _load(*args: Any, **kw: Any) -> int:
            seen.append(kw["overwrite_cms_edits"])
            kw["conflicts"].append("misconception_catalog:M1")
            return 4

        monkeypatch.setattr(cli, func, _load)
        src = _touch(tmp_path / "in.json")
        assert cli.main([flag_path, str(src)]) == 0
        assert cli.main([flag_path, str(src), OVERWRITE_FLAG]) == 0
        assert seen == [False, True]
        assert "misconception_catalog:M1" in capsys.readouterr().out

    def test_problem_bank_cli(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        from whymath_backend.l1.problem_bank import populate as mod

        seen: list[bool] = []

        def _populate(
            _s: object,
            *,
            problems_path: Path,
            store: object = None,
            overwrite_cms_edits: bool = False,
        ) -> mod.ProblemBankPopulateReport:
            seen.append(overwrite_cms_edits)
            return mod.ProblemBankPopulateReport(
                problems_loaded=1,
                problem_concepts_loaded=0,
                concepts_skipped=0,
                cms_edit_conflicts=["problem:p1"],
            )

        monkeypatch.setattr(mod, "populate_problem_bank", _populate)
        src = _touch(tmp_path / "problems.jsonl")
        assert mod.main(["--problems", str(src)]) == 0
        assert mod.main(["--problems", str(src), OVERWRITE_FLAG]) == 0
        assert seen == [False, True]
        assert "problem:p1" in capsys.readouterr().out

    def test_hint_cli(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from whymath_backend.l4.hint_content import populate
        from whymath_backend.l4.hint_content.store import PathLoadReport

        seen: list[bool] = []

        async def _run(
            *, apply: bool, overwrite_cms_edits: bool = False
        ) -> populate.GenerationReport:
            seen.append(overwrite_cms_edits)
            return populate.summarize([], load=PathLoadReport(paths_seen=1), applied=apply)

        monkeypatch.setattr(populate, "run", _run)
        assert populate.main(["--apply"]) == 0
        assert populate.main(["--apply", OVERWRITE_FLAG]) == 0
        assert seen == [False, True]


# ── 적재 SQL 모양 (가짜 엔진으로 컴파일) ─────────────────────────────────


class _Recorder:
    """`begin()` 컨텍스트 + 실행 문장 기록 — RETURNING이 키 1행을 돌려준 것처럼 답한다."""

    def __init__(self) -> None:
        self.executed: list[Any] = []

    def begin(self) -> _Recorder:
        return self

    def __enter__(self) -> _Recorder:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, statement: Any) -> Any:
        self.executed.append(statement)
        return SimpleNamespace(first=lambda: (1,))


def _sql(stmt: Any) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


class TestLoaderSqlShape:
    def test_strategy_upsert_is_guarded_and_returns_the_key(self) -> None:
        from whymath_backend.l1.strategy_graph.strategy_node_projection import (
            StrategyNodeRecord,
            StrategyNodeStore,
        )

        rec = StrategyNodeRecord("s.1", "이름", "reduction", "설명", ())
        for overwrite in (False, True):
            engine = _Recorder()
            store = StrategyNodeStore(engine=engine)  # type: ignore[arg-type]
            assert store.upsert(rec, overwrite_cms_edits=overwrite) is True
            sql = _sql(engine.executed[0])
            assert "RETURNING strategy_node.strategy_id" in sql
            if overwrite:
                assert "cms_edited_at IS NULL" not in sql
                assert "cms_edited_at=%(param_" in sql.replace(" ", "")  # 표지를 비우는 SET
            else:
                assert "WHERE strategy_node.cms_edited_at IS NULL" in sql

    def test_upsert_reports_false_when_the_database_skipped_the_row(self) -> None:
        from whymath_backend.l1.strategy_graph.strategy_node_projection import (
            StrategyNodeRecord,
            StrategyNodeStore,
        )

        class _Skipping(_Recorder):
            def execute(self, statement: Any) -> Any:
                self.executed.append(statement)
                return SimpleNamespace(first=lambda: None)

        store = StrategyNodeStore(engine=_Skipping())  # type: ignore[arg-type]
        assert store.upsert(StrategyNodeRecord("s.1", "n", "f", "d", ())) is False
