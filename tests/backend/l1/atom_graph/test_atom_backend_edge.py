"""원자 백본 선수엣지 → backend `concept_edge` 적재 *단위테스트*(hermetic·PG 불요).

가짜 sync 엔진으로 PG 없이 검증한다(`test_concept_backend_edge_load.py` 패턴):
  ① 로딩 — from_code/to_code/relation_subtype/strength·prerequisite만·self/누락 skip·evidence 미유입
  ② code→UUID 해석·orphan skip·N+1 0
  ③ upsert SQL — ON CONFLICT(from,to,type)·relation_subtype SET·edge_id/created_at 미-SET
  ④ populate — 멱등·orphan 제외
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import TracebackType

import pytest

from whymath_backend.config import Settings
from whymath_backend.l1.atom_graph.atom_backend_edge import (
    AtomBackendEdgeRecord,
    AtomBackendEdgeStore,
    load_atom_edges_from_graph_json,
    populate_atom_edges,
)
from whymath_backend.schema.enums import EdgeType

_PRE = "2수01-01-1"
_POST = "2수01-01-2"
_ORPHAN = "없는-원자"

_UUID_PRE = uuid.uuid4()
_UUID_POST = uuid.uuid4()


def _pg_dialect() -> object:
    from sqlalchemy.dialects import postgresql

    return postgresql.dialect()


def _compile(statement: object) -> str:
    return str(statement.compile(dialect=_pg_dialect()))  # type: ignore[attr-defined]


class _Row:
    def __init__(self, code: str, concept_id: uuid.UUID) -> None:
        self.code = code
        self.concept_id = concept_id


class _FakeResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows

    def first(self) -> object | None:
        # `INSERT … ON CONFLICT … RETURNING`(P3-25/26 가드): 행이 있으면 적재됨, 없으면 건너뜀.
        return self._rows[0] if self._rows else None


class _FakeConnection:
    def __init__(self, engine: _FakeEngine) -> None:
        self._engine = engine

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    def execute(self, statement: object, parameters: object = None) -> _FakeResult:
        self._engine.executed.append(statement)
        compiled = _compile(statement)
        if "SELECT" in compiled and "concept.code" in compiled and "INSERT" not in compiled:
            return _FakeResult(self._engine.code_rows)
        if "INSERT" in compiled:
            # RETURNING 1행 = 적재됨 / 0행 = CMS 소유 가드가 건너뜀(P3-26)
            rows = [_Row("written", uuid.uuid4())] if self._engine.insert_written else []
            return _FakeResult(rows)
        if "SELECT" in compiled and "concept_edge" in compiled:
            return _FakeResult(self._engine.db_edges)  # DB에 이미 있는 선수 엣지(순환 검사 재료)
        return _FakeResult([])


class _FakeEngine:
    def __init__(self, code_rows: list[object] | None = None) -> None:
        self.insert_written = True
        self.db_edges: list[object] = []
        self.executed: list[object] = []
        self.code_rows: list[object] = (
            code_rows if code_rows is not None else [_Row(_PRE, _UUID_PRE), _Row(_POST, _UUID_POST)]
        )

    def begin(self) -> _FakeConnection:
        return _FakeConnection(self)

    def connect(self) -> _FakeConnection:
        return _FakeConnection(self)


def _fake_store(
    code_rows: list[object] | None = None,
) -> tuple[AtomBackendEdgeStore, _FakeEngine]:
    engine = _FakeEngine(code_rows)
    store = AtomBackendEdgeStore(engine=engine)  # type: ignore[arg-type]
    return store, engine


def _insert_sql(engine: _FakeEngine) -> str:
    """실행된 문장 중 `INSERT`(upsert) 1건의 SQL — 잠금·순환 검사 SQL이 앞에 끼어도 위치에 안 기댄다."""
    inserts = [_compile(s) for s in engine.executed if "INSERT" in _compile(s)]
    assert len(inserts) == 1, inserts
    return inserts[0]


def _record(
    src: str = _PRE,
    dst: str = _POST,
    *,
    edge_strength: float | None = 0.8,
    relation_subtype: str | None = "원본",
) -> AtomBackendEdgeRecord:
    return AtomBackendEdgeRecord(
        from_code=src,
        to_code=dst,
        edge_type=EdgeType.PREREQUISITE,
        edge_strength=edge_strength,
        relation_subtype=relation_subtype,
    )


# ──────────────────────────────────────────────────────────────────────────
# ① 로딩
# ──────────────────────────────────────────────────────────────────────────
class TestLoad:
    def _write(self, tmp_path: Path, edges: list[dict[str, object]]) -> Path:
        path = tmp_path / "graph.json"
        path.write_text(
            json.dumps({"concepts": [], "edges": edges}, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def test_maps_direction_subtype_strength(self, tmp_path: Path) -> None:
        path = self._write(
            tmp_path,
            [
                {
                    "from_code": _PRE,
                    "to_code": _POST,
                    "relation": "prerequisite",
                    "relation_subtype": "소단원내",
                    "strength": 0.75,
                    "evidence": "원자 백본 v1",
                }
            ],
        )
        records, skipped = load_atom_edges_from_graph_json(path)
        assert len(records) == 1 and skipped == []
        rec = records[0]
        assert rec.from_code == _PRE and rec.to_code == _POST
        assert rec.edge_type == EdgeType.PREREQUISITE
        assert rec.edge_strength == 0.75
        assert rec.relation_subtype == "소단원내"

    def test_evidence_no_slot(self) -> None:
        fields = set(AtomBackendEdgeRecord.__dataclass_fields__)
        assert "evidence" not in fields and "notes" not in fields
        assert fields == {
            "from_code",
            "to_code",
            "edge_type",
            "edge_strength",
            "relation_subtype",
        }

    def test_non_prerequisite_skipped(self, tmp_path: Path) -> None:
        path = self._write(
            tmp_path,
            [{"from_code": _PRE, "to_code": _POST, "relation": "analogous_to"}],
        )
        records, skipped = load_atom_edges_from_graph_json(path)
        assert records == [] and any("비-선수" in m for m in skipped)

    def test_self_edge_skipped(self, tmp_path: Path) -> None:
        path = self._write(
            tmp_path,
            [{"from_code": _PRE, "to_code": _PRE, "relation": "prerequisite"}],
        )
        records, skipped = load_atom_edges_from_graph_json(path)
        assert records == [] and any("self-edge" in m for m in skipped)

    def test_missing_endpoint_skipped(self, tmp_path: Path) -> None:
        path = self._write(tmp_path, [{"from_code": _PRE, "relation": "prerequisite"}])
        records, skipped = load_atom_edges_from_graph_json(path)
        assert records == [] and any("양끝 code 누락" in m for m in skipped)

    @pytest.mark.parametrize("bad", ["", "  ", None])
    def test_blank_strength_none(self, tmp_path: Path, bad: object) -> None:
        path = self._write(
            tmp_path,
            [
                {
                    "from_code": _PRE,
                    "to_code": _POST,
                    "relation": "prerequisite",
                    "strength": bad,
                }
            ],
        )
        records, _ = load_atom_edges_from_graph_json(path)
        assert records[0].edge_strength is None

    def test_missing_subtype_none(self, tmp_path: Path) -> None:
        path = self._write(
            tmp_path,
            [{"from_code": _PRE, "to_code": _POST, "relation": "prerequisite"}],
        )
        records, _ = load_atom_edges_from_graph_json(path)
        assert records[0].relation_subtype is None


# ──────────────────────────────────────────────────────────────────────────
# ② 해석·orphan·N+1
# ──────────────────────────────────────────────────────────────────────────
class TestResolution:
    def test_resolves_both(self) -> None:
        store, engine = _fake_store()
        loaded, skipped = store.populate([_record()])
        assert loaded == 1 and skipped == []
        assert "INSERT INTO concept_edge" in _insert_sql(engine)

    def test_orphan_skipped(self) -> None:
        store, engine = _fake_store()
        loaded, skipped = store.populate([_record(dst=_ORPHAN)])
        assert loaded == 0 and any("orphan" in m for m in skipped)
        assert len(engine.executed) == 1  # SELECT만

    def test_no_n_plus_one(self) -> None:
        store, engine = _fake_store()
        store.populate([_record(), _record(), _record()])
        selects = [
            s
            for s in engine.executed
            if "concept.code" in _compile(s) and "INSERT" not in _compile(s)
        ]
        assert len(selects) == 1


# ──────────────────────────────────────────────────────────────────────────
# ③ upsert SQL
# ──────────────────────────────────────────────────────────────────────────
class TestUpsert:
    def test_on_conflict_composite_and_subtype_set(self) -> None:
        store, engine = _fake_store()
        store.populate([_record()])
        sql = _insert_sql(engine)
        assert "ON CONFLICT" in sql
        for col in ("from_concept_id", "to_concept_id", "edge_type"):
            assert col in sql
        # SET 절만 분리 — 뒤따르는 RETURNING concept_edge.edge_id는 PK 대입이 아니라
        # 신규행 PK 회신이므로 잘라낸다(구 test_concept_backend_edge_load 패턴 동일).
        set_clause = sql.split("DO UPDATE SET", 1)[1].split("RETURNING", 1)[0]
        assert "edge_strength" in set_clause
        assert "relation_subtype" in set_clause
        assert "edge_id" not in set_clause
        assert "created_at" not in set_clause

    def test_omits_gap_signal_notes(self) -> None:
        store, engine = _fake_store()
        store.populate([_record()])
        sql = _insert_sql(engine)
        assert "typical_gap_signal" not in sql
        assert "evidence" not in sql


# ──────────────────────────────────────────────────────────────────────────
# ③-b CMS 소유 보호·DB 인지 순환 검사·잠금 (P3-26)
# ──────────────────────────────────────────────────────────────────────────
class TestCmsOwnershipAndCycleGuard:
    def test_a_cms_owned_row_is_skipped_and_reported_as_a_conflict(self) -> None:
        store, engine = _fake_store()
        engine.insert_written = False  # 가드(WHERE cms_edited_at IS NULL)가 행을 건너뜀
        conflicts: list[str] = []
        loaded = populate_atom_edges([_record()], store=store, conflicts=conflicts)
        assert loaded == 0, "건너뛴 행을 적재 건수에 셌다 — 적재가 일했다는 거짓 증거"
        assert conflicts == [f"concept_edge:{_PRE}->{_POST}"]

    def test_a_written_row_is_not_a_conflict(self) -> None:
        store, _ = _fake_store()
        conflicts: list[str] = []
        assert populate_atom_edges([_record()], store=store, conflicts=conflicts) == 1
        assert conflicts == []

    def test_the_insert_carries_the_guard_where_and_overwrite_releases_the_marker(self) -> None:
        store, engine = _fake_store()
        store.populate([_record()])
        guarded = _insert_sql(engine)
        assert "cms_edited_at IS NULL" in guarded
        assert "cms_edited_at" not in guarded.split("DO UPDATE SET", 1)[1].split("WHERE", 1)[0]

        store2, engine2 = _fake_store()
        store2.populate([_record()], overwrite_cms_edits=True)
        released = _insert_sql(engine2)
        assert "cms_edited_at IS NULL" not in released
        assert "cms_edited_at" in released.split("DO UPDATE SET", 1)[1]  # 표지를 비운다

    def test_the_graph_lock_is_taken_before_any_write(self) -> None:
        store, engine = _fake_store()
        store.populate([_record()])
        sqls = [_compile(s) for s in engine.executed]
        lock = next(i for i, s in enumerate(sqls) if "pg_advisory_xact_lock" in s)
        insert = next(i for i, s in enumerate(sqls) if "INSERT" in s)
        assert lock < insert

    def test_a_file_edge_closing_a_cycle_with_a_db_edge_is_refused_before_any_insert(self) -> None:
        """DB에 (CMS가 만든) PRE→POST 가 있는데 파일이 POST→PRE 를 가져왔다 — 합치면 순환."""
        from whymath_backend.l1.concept_graph.prerequisite_guard import PrerequisiteCycleError

        store, engine = _fake_store()
        engine.db_edges = [(_UUID_PRE, _UUID_POST)]
        with pytest.raises(PrerequisiteCycleError) as exc:
            store.populate([_record(src=_POST, dst=_PRE)])
        assert exc.value.cycle[0] == exc.value.cycle[-1]
        assert {_PRE, _POST} <= set(exc.value.cycle), "오류 경로가 개념 코드가 아니라 UUID다"
        assert not any(
            "INSERT" in _compile(s) for s in engine.executed
        ), "거부 전에 쓰기가 일어났다"

    def test_a_non_cyclic_load_next_to_db_edges_passes(self) -> None:
        """대조군 — DB에 엣지가 있어도 순환이 아니면 통과한다(거부가 과잉이 아니다)."""
        store, engine = _fake_store()
        engine.db_edges = [(_UUID_PRE, _UUID_POST)]
        assert store.populate([_record()])[0] == 1

    def test_nothing_to_write_takes_no_lock_and_runs_no_cycle_check(self) -> None:
        store, engine = _fake_store()
        loaded, _ = store.populate([_record(dst=_ORPHAN)])
        assert loaded == 0
        assert not any("pg_advisory_xact_lock" in _compile(s) for s in engine.executed)


# ──────────────────────────────────────────────────────────────────────────
# ④ populate
# ──────────────────────────────────────────────────────────────────────────
class TestPopulate:
    def test_excludes_orphans(self) -> None:
        store, _ = _fake_store()
        assert populate_atom_edges([_record(), _record(dst=_ORPHAN)], store=store) == 1

    def test_empty_noop(self) -> None:
        store, engine = _fake_store()
        assert populate_atom_edges([], store=store) == 0
        assert engine.executed == []

    def test_default_settings(self) -> None:
        assert isinstance(AtomBackendEdgeStore()._resolved_settings, Settings)
