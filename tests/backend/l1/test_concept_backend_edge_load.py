"""개념그래프 선수엣지 → backend `concept_edge` 적재 *단위테스트* — 선수 슬1 (hermetic·PG 불요).

CI hermetic 잡엔 PostgreSQL이 없으므로 `BackendEdgeStore`/`populate_backend_edges`의 *실
라운드트립*은 통합테스트(`test_concept_backend_load_integration.py` 확장·실 PG 게이트)로 미룬다.
여기서는 PG 없이 검증 가능한 것만 못 박는다(`test_concept_backend_load.py` 가짜 엔진 패턴 재사용):

  ① graph.json 로딩 — edges 파싱(prerequisite만·비-선수 skip·self-edge skip)·src/dst→code·
     strength 매핑·evidence 미유입(슬롯 부재)
  ② code→UUID 해석 — backend concept 단일 조회 맵·orphan skip(맵에 없는 code)
  ③ upsert SQL 구성 — ON CONFLICT(from,to,type)·edge_id(PK)·created_at 미-SET(보존 멱등)
  ④ populate — orphan 제외 후 적재 행 수·멱등(같은 레코드 2회→같은 upsert)

P2b 재ID(2026-06-16): 엣지 적재기는 *형식 불문*(endpoint id 문자열을 그대로 concept.code에 대조)
이라 concept_id 재ID(UC.*→`{TRACK}-{AREA}-{NNN}`)에 코드 변경이 없다. 이 테스트는 정본으로 새 형식
id를 쓴다(옛 UC도 같은 경로로 흘렀겠지만). 가짜 엔진(`_FakeEngine`)은 begin()/connect() 컨텍스트 +
execute()를 흉내내 실행 statement·code→UUID 조회 결과를 제어한다 — psycopg/PG 없이 배선·방향·
redaction·멱등 키를 검증한다.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import TracebackType

import pytest

from whymath_backend.config import Settings
from whymath_backend.l1.concept_graph.backend_edge import (
    BackendConceptEdgeRecord,
    BackendEdgeStore,
    load_backend_edges_from_graph_json,
    populate_backend_edges,
)
from whymath_backend.schema.enums import EdgeType

# 재ID 후 concept_id 규약 키 예시(`{TRACK}-{AREA}-{NNN}`·concept.code·concept_node와 동일 키 공간).
_NID_PRE = "HIGH-ALG-001"  # 선수
_NID_POST = "HIGH-CALC-001"  # 후행
_NID_ORPHAN = "HIGH-ZZ-999"  # 노드 미적재(orphan)

_UUID_PRE = uuid.uuid4()
_UUID_POST = uuid.uuid4()


# ──────────────────────────────────────────────────────────────────────────
# 가짜 sync 엔진 — begin()/connect() 컨텍스트 + execute() (PG 없이 배선 관찰)
# ──────────────────────────────────────────────────────────────────────────
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
        # code→UUID 조회(SELECT concept.code, concept.concept_id)면 맵 행을 돌려준다.
        compiled = str(statement.compile(dialect=_pg_dialect()))  # type: ignore[attr-defined]
        if "SELECT" in compiled and "concept.code" in compiled and "INSERT" not in compiled:
            return _FakeResult(self._engine.code_rows)
        if "INSERT" in compiled:
            # RETURNING 1행 = 적재됨 / 0행 = CMS 소유 가드가 건너뜀(P3-26)
            rows = [_Row("written", uuid.uuid4())] if self._engine.insert_written else []
            return _FakeResult(rows)
        if "SELECT" in compiled and "concept_edge" in compiled:
            return _FakeResult(self._engine.db_edges)  # DB에 이미 있는 선수 엣지(순환 검사 재료)
        return _FakeResult([])


def _pg_dialect() -> object:
    from sqlalchemy.dialects import postgresql

    return postgresql.dialect()


class _FakeEngine:
    """SQLAlchemy sync Engine 최소 흉내 — begin()/connect() + 실행 statement·code맵 제어."""

    def __init__(self, code_rows: list[object] | None = None) -> None:
        self.insert_written = True
        self.db_edges: list[object] = []
        self.executed: list[object] = []
        # code→UUID 조회가 돌려줄 행(name 튜플 흉내). 기본: 선수·후행 둘 다 적재됨.
        self.code_rows: list[object] = (
            code_rows
            if code_rows is not None
            else [_Row(_NID_PRE, _UUID_PRE), _Row(_NID_POST, _UUID_POST)]
        )

    def begin(self) -> _FakeConnection:
        return _FakeConnection(self)

    def connect(self) -> _FakeConnection:
        return _FakeConnection(self)


class _Row:
    """code→UUID 조회 결과 행 흉내 — `.code`·`.concept_id` 속성 접근."""

    def __init__(self, code: str, concept_id: uuid.UUID) -> None:
        self.code = code
        self.concept_id = concept_id


def _fake_store(
    code_rows: list[object] | None = None,
) -> tuple[BackendEdgeStore, _FakeEngine]:
    engine = _FakeEngine(code_rows)
    store = BackendEdgeStore(engine=engine)  # type: ignore[arg-type]  # 가짜 엔진(구조만 충족)
    return store, engine


def _compile(statement: object) -> str:
    return str(statement.compile(dialect=_pg_dialect()))  # type: ignore[attr-defined]


def _insert_sql(engine: _FakeEngine) -> str:
    """실행된 문장 중 `INSERT`(upsert) 1건의 SQL — 잠금·순환 검사 SQL이 앞에 끼어도 위치에 안 기댄다."""
    inserts = [_compile(s) for s in engine.executed if "INSERT" in _compile(s)]
    assert len(inserts) == 1, inserts
    return inserts[0]


def _record(
    src: str = _NID_PRE,
    dst: str = _NID_POST,
    *,
    edge_strength: float | None = 0.8,
) -> BackendConceptEdgeRecord:
    return BackendConceptEdgeRecord(
        src_code=src,
        dst_code=dst,
        edge_type=EdgeType.PREREQUISITE,
        edge_strength=edge_strength,
    )


# ──────────────────────────────────────────────────────────────────────────
# ① graph.json 로딩 — prerequisite만·비-선수/self-edge skip·방향·strength·evidence 미유입
# ──────────────────────────────────────────────────────────────────────────
class TestLoadFromGraphJson:
    def _write_graph(self, tmp_path: Path, edges: list[dict[str, object]]) -> Path:
        path = tmp_path / "graph.json"
        path.write_text(
            json.dumps({"concepts": [], "edges": edges}, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def test_prerequisite_edge_direction_and_mapping(self, tmp_path: Path) -> None:
        # 방향: src(선수)→src_code·dst(후행)→dst_code. strength→edge_strength.
        path = self._write_graph(
            tmp_path,
            [
                {
                    "src_concept_id": _NID_PRE,
                    "dst_concept_id": _NID_POST,
                    "relation": "prerequisite",
                    "strength": 0.75,
                    "evidence": "근거 산문(적재 금지)",
                    "evidence_source": "ncic",
                }
            ],
        )
        records, skipped = load_backend_edges_from_graph_json(path)
        assert len(records) == 1
        assert skipped == []
        rec = records[0]
        assert rec.src_code == _NID_PRE  # 선수
        assert rec.dst_code == _NID_POST  # 후행
        assert rec.edge_type == EdgeType.PREREQUISITE
        assert rec.edge_strength == 0.75

    def test_evidence_never_loaded(self, tmp_path: Path) -> None:
        # redaction/날조 회피: evidence·notes·typical_gap_signal 슬롯이 레코드에 *없다*.
        fields = set(BackendConceptEdgeRecord.__dataclass_fields__)
        assert "evidence" not in fields
        assert "notes" not in fields
        assert "typical_gap_signal" not in fields
        assert {"src_code", "dst_code", "edge_type", "edge_strength"} == fields

    def test_non_prerequisite_relation_skipped(self, tmp_path: Path) -> None:
        # 이번 범위는 선수만 — 그 외 relation은 skip(메시지 수집).
        path = self._write_graph(
            tmp_path,
            [
                {
                    "src_concept_id": _NID_PRE,
                    "dst_concept_id": _NID_POST,
                    "relation": "analogous_to",
                    "strength": 0.5,
                    "evidence": "x",
                    "evidence_source": "ncic",
                },
                {
                    "src_concept_id": _NID_PRE,
                    "dst_concept_id": _NID_POST,
                    "relation": "prerequisite",
                    "strength": 0.6,
                    "evidence": "y",
                    "evidence_source": "ncic",
                },
            ],
        )
        records, skipped = load_backend_edges_from_graph_json(path)
        assert len(records) == 1  # 선수만
        assert records[0].edge_strength == 0.6
        assert any("비-선수" in m for m in skipped)

    def test_self_edge_skipped(self, tmp_path: Path) -> None:
        # self-edge(src==dst)는 _no_self_edge 불변 위반 → 적재 전 skip.
        path = self._write_graph(
            tmp_path,
            [
                {
                    "src_concept_id": _NID_PRE,
                    "dst_concept_id": _NID_PRE,
                    "relation": "prerequisite",
                    "strength": 0.9,
                    "evidence": "z",
                    "evidence_source": "ncic",
                }
            ],
        )
        records, skipped = load_backend_edges_from_graph_json(path)
        assert records == []
        assert any("self-edge" in m for m in skipped)

    def test_missing_strength_is_none(self, tmp_path: Path) -> None:
        # strength 빈칸(전문가 미작성) → edge_strength None(graceful).
        path = self._write_graph(
            tmp_path,
            [
                {
                    "src_concept_id": _NID_PRE,
                    "dst_concept_id": _NID_POST,
                    "relation": "prerequisite",
                    "strength": "",
                    "evidence": "z",
                    "evidence_source": "ncic",
                }
            ],
        )
        records, _ = load_backend_edges_from_graph_json(path)
        assert records[0].edge_strength is None

    def test_missing_endpoint_skipped(self, tmp_path: Path) -> None:
        path = self._write_graph(
            tmp_path,
            [{"src_concept_id": _NID_PRE, "relation": "prerequisite", "strength": 0.5}],
        )
        records, skipped = load_backend_edges_from_graph_json(path)
        assert records == []
        assert any("양끝 UC 누락" in m for m in skipped)

    def test_empty_edges(self, tmp_path: Path) -> None:
        path = self._write_graph(tmp_path, [])
        assert load_backend_edges_from_graph_json(path) == ([], [])


# ──────────────────────────────────────────────────────────────────────────
# ②-b CMS 소유 보호·DB 인지 순환 검사·잠금 (P3-26)
# ──────────────────────────────────────────────────────────────────────────
class TestCmsOwnershipAndCycleGuard:
    def test_a_cms_owned_row_is_skipped_and_reported(self) -> None:
        store, engine = _fake_store()
        engine.insert_written = False
        conflicts: list[str] = []
        loaded = populate_backend_edges([_record()], store=store, conflicts=conflicts)
        assert loaded == 0
        assert conflicts == [f"concept_edge:{_NID_PRE}->{_NID_POST}"]

    def test_the_insert_is_guarded_and_overwrite_releases_the_marker(self) -> None:
        store, engine = _fake_store()
        store.populate([_record()])
        assert "cms_edited_at IS NULL" in _insert_sql(engine)
        store2, engine2 = _fake_store()
        store2.populate([_record()], overwrite_cms_edits=True)
        assert "cms_edited_at IS NULL" not in _insert_sql(engine2)

    def test_the_lock_comes_before_the_first_write(self) -> None:
        store, engine = _fake_store()
        store.populate([_record()])
        sqls = [_compile(s) for s in engine.executed]
        lock = next(i for i, s in enumerate(sqls) if "pg_advisory_xact_lock" in s)
        insert = next(i for i, s in enumerate(sqls) if "INSERT" in s)
        assert lock < insert

    def test_a_cycle_with_a_db_edge_is_refused_before_any_insert(self) -> None:
        from whymath_backend.l1.concept_graph.prerequisite_guard import PrerequisiteCycleError

        store, engine = _fake_store()
        engine.db_edges = [(_UUID_PRE, _UUID_POST)]
        with pytest.raises(PrerequisiteCycleError):
            store.populate([_record(src=_NID_POST, dst=_NID_PRE)])
        assert not any("INSERT" in _compile(s) for s in engine.executed)

    def test_a_non_cyclic_load_next_to_db_edges_passes(self) -> None:
        store, engine = _fake_store()
        engine.db_edges = [(_UUID_PRE, _UUID_POST)]
        assert store.populate([_record()])[0] == 1


# ──────────────────────────────────────────────────────────────────────────
# ② code→UUID 해석 — 단일 조회 맵·orphan skip
# ──────────────────────────────────────────────────────────────────────────
class TestCodeToUuidResolution:
    def test_resolves_both_endpoints_to_uuid(self) -> None:
        # 양끝 UC가 맵에 있으면 UUID로 해석돼 INSERT(values from/to UUID).
        store, engine = _fake_store()
        loaded, skipped = store.populate([_record()])
        assert loaded == 1
        assert skipped == []
        insert_sql = _insert_sql(engine)
        assert "INSERT INTO concept_edge" in insert_sql

    def test_orphan_endpoint_skipped(self) -> None:
        # 후행이 맵에 없으면(orphan·노드 미적재) 그 엣지는 FK 위반 방지로 skip.
        store, engine = _fake_store()
        loaded, skipped = store.populate([_record(dst=_NID_ORPHAN)])
        assert loaded == 0
        assert any("orphan" in m for m in skipped)
        # code→UUID 조회만 실행(INSERT 없음).
        assert len(engine.executed) == 1

    def test_single_code_query_no_n_plus_one(self) -> None:
        # 여러 엣지여도 code→UUID 조회는 *단 한 번*(N+1 0).
        store, engine = _fake_store()
        store.populate([_record(), _record(), _record()])
        selects = [
            s
            for s in engine.executed
            if "concept.code" in _compile(s) and "INSERT" not in _compile(s)
        ]
        assert len(selects) == 1


# ──────────────────────────────────────────────────────────────────────────
# ③ upsert SQL 구성 — ON CONFLICT(from,to,type)·edge_id/created_at 미-SET(보존)
# ──────────────────────────────────────────────────────────────────────────
class TestUpsertStatement:
    def test_on_conflict_composite_key(self) -> None:
        store, engine = _fake_store()
        store.populate([_record()])
        sql = _insert_sql(engine)
        assert "ON CONFLICT" in sql
        # 복합 충돌 키 — from·to·edge_type 셋 다.
        assert "from_concept_id" in sql
        assert "to_concept_id" in sql
        assert "edge_type" in sql

    def test_does_not_set_edge_id_or_created_at(self) -> None:
        # 멱등 보존: ON CONFLICT DO UPDATE SET이 edge_id(PK)·created_at을 *대입하지 않는다*.
        store, engine = _fake_store()
        store.populate([_record()])
        sql = _insert_sql(engine)
        assert "DO UPDATE SET" in sql
        after_set = sql.split("DO UPDATE SET", 1)[1]
        set_clause = after_set.split("RETURNING", 1)[0]
        assert "edge_id" not in set_clause
        assert "created_at" not in set_clause
        # SET은 edge_strength만 갱신.
        assert "edge_strength" in set_clause

    def test_omits_gap_signal_and_notes_columns(self) -> None:
        # 날조 회피: typical_gap_signal·notes는 INSERT 컬럼에 *없다*(NULL 유지).
        store, engine = _fake_store()
        store.populate([_record()])
        sql = _insert_sql(engine)
        assert "typical_gap_signal" not in sql
        assert "notes" not in sql
        assert "evidence" not in sql


# ──────────────────────────────────────────────────────────────────────────
# ④ populate — orphan 제외 후 행 수·멱등
# ──────────────────────────────────────────────────────────────────────────
class TestPopulate:
    def test_populate_counts_loaded_excluding_orphans(self) -> None:
        store, _ = _fake_store()
        count = populate_backend_edges([_record(), _record(dst=_NID_ORPHAN)], store=store)
        assert count == 1  # orphan 1건 제외

    def test_populate_empty_is_noop(self) -> None:
        store, engine = _fake_store()
        assert populate_backend_edges([], store=store) == 0
        assert engine.executed == []

    def test_populate_idempotent_same_statements(self) -> None:
        store, engine = _fake_store()
        records = [_record()]
        populate_backend_edges(records, store=store)
        populate_backend_edges(records, store=store)
        inserts = [s for s in engine.executed if "INSERT INTO concept_edge" in _compile(s)]
        assert len(inserts) == 2
        for stmt in inserts:
            assert "ON CONFLICT" in _compile(stmt)


def test_store_uses_default_settings_when_unset() -> None:
    store = BackendEdgeStore()
    assert isinstance(store._resolved_settings, Settings)


def test_edge_type_value_bound_as_enum_string() -> None:
    # PG enum 컬럼 — edge_type은 enum 값 문자열("PREREQUISITE")로 바인딩.
    store, engine = _fake_store()
    store.populate([_record()])
    sql = _insert_sql(engine)
    assert "edge_type" in sql


@pytest.mark.parametrize("bad", ["", "  ", None])
def test_blank_strength_variants_none(tmp_path: Path, bad: object) -> None:
    path = tmp_path / "graph.json"
    edges = [
        {
            "src_concept_id": _NID_PRE,
            "dst_concept_id": _NID_POST,
            "relation": "prerequisite",
            "strength": bad,
            "evidence": "x",
            "evidence_source": "ncic",
        }
    ]
    path.write_text(json.dumps({"edges": edges}), encoding="utf-8")
    records, _ = load_backend_edges_from_graph_json(path)
    assert records[0].edge_strength is None
