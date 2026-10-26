"""원자 백본 → backend `concept` 적재 *단위테스트*(hermetic·PG 불요).

가짜 sync 엔진(`_FakeEngine`)으로 PG 없이 검증한다(`test_concept_backend_edge_load.py` 패턴 재사용):
  ① graph.json 로딩 — code/name/level/parent_code/난이도·level 직대응·본문 미유입(subject 제거)
  ② clamp_difficulty — 1~5 clamp·None
  ③ upsert SQL — ON CONFLICT(code)·concept_id/created_at/parent_concept_id 미-SET(보존·2-pass)
  ④ resolve_parents — code→UUID 해석 UPDATE·미해소 skip
  ⑤ populate — 적재 수·parent skip
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import TracebackType

import pytest

from whymath_backend.config import Settings
from whymath_backend.l1.atom_graph.atom_backend_concept import (
    AtomBackendConceptRecord,
    AtomBackendConceptStore,
    clamp_difficulty,
    load_atom_concepts_from_graph_json,
    populate_atom_concepts,
)
from whymath_backend.schema.enums import ConceptLevel

_ATOM = "2수01-01-2"
_SUBUNIT = "초수연-U1-S1"
_UNIT = "초수연-U1"

_UUID_ATOM = uuid.uuid4()
_UUID_SUBUNIT = uuid.uuid4()
_UUID_UNIT = uuid.uuid4()


# ──────────────────────────────────────────────────────────────────────────
# 가짜 sync 엔진
# ──────────────────────────────────────────────────────────────────────────
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
        return _FakeResult([])


class _FakeEngine:
    def __init__(self, code_rows: list[object] | None = None) -> None:
        self.insert_written = True
        self.executed: list[object] = []
        self.code_rows: list[object] = (
            code_rows
            if code_rows is not None
            else [
                _Row(_ATOM, _UUID_ATOM),
                _Row(_SUBUNIT, _UUID_SUBUNIT),
                _Row(_UNIT, _UUID_UNIT),
            ]
        )

    def begin(self) -> _FakeConnection:
        return _FakeConnection(self)

    def connect(self) -> _FakeConnection:
        return _FakeConnection(self)


def _fake_store(
    code_rows: list[object] | None = None,
) -> tuple[AtomBackendConceptStore, _FakeEngine]:
    engine = _FakeEngine(code_rows)
    store = AtomBackendConceptStore(engine=engine)  # type: ignore[arg-type]
    return store, engine


def _record(
    code: str = _ATOM,
    *,
    level: ConceptLevel = ConceptLevel.세부개념,
    parent_code: str | None = _SUBUNIT,
    difficulty: float | None = 1.0,
) -> AtomBackendConceptRecord:
    return AtomBackendConceptRecord(
        code=code,
        name_ko="기수 원리",
        level=level,
        parent_code=parent_code,
        intrinsic_difficulty=difficulty,
    )


# ──────────────────────────────────────────────────────────────────────────
# ① graph.json 로딩
# ──────────────────────────────────────────────────────────────────────────
class TestLoadFromGraphJson:
    def _write(self, tmp_path: Path, concepts: list[dict[str, object]]) -> Path:
        path = tmp_path / "graph.json"
        path.write_text(
            json.dumps({"concepts": concepts, "edges": []}, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def test_maps_core_fields_and_level(self, tmp_path: Path) -> None:
        path = self._write(
            tmp_path,
            [
                {
                    "code": _ATOM,
                    "name": "기수 원리",
                    "level": "세부개념",
                    "parent_code": _SUBUNIT,
                    "school_level": "초등",
                    "subject_area": "수와 연산",
                    "intrinsic_difficulty": 3,
                    # 본문성 필드(적재 금지)
                    "core_proposition": "성취기준 본문류",
                    "description": "x",
                    "formal_definition": "y",
                }
            ],
        )
        records = load_atom_concepts_from_graph_json(path)
        assert len(records) == 1
        rec = records[0]
        assert rec.code == _ATOM
        assert rec.name_ko == "기수 원리"
        assert rec.level == ConceptLevel.세부개념
        assert rec.parent_code == _SUBUNIT
        assert rec.intrinsic_difficulty == 3.0

    def test_all_three_levels(self, tmp_path: Path) -> None:
        path = self._write(
            tmp_path,
            [
                {
                    "code": _UNIT,
                    "name": "수와 연산",
                    "level": "단원",
                    "parent_code": None,
                },
                {
                    "code": _SUBUNIT,
                    "name": "100까지",
                    "level": "소단원",
                    "parent_code": _UNIT,
                },
                {
                    "code": _ATOM,
                    "name": "기수",
                    "level": "세부개념",
                    "parent_code": _SUBUNIT,
                    "intrinsic_difficulty": 1,
                },
            ],
        )
        records = load_atom_concepts_from_graph_json(path)
        by_code = {r.code: r for r in records}
        assert by_code[_UNIT].level == ConceptLevel.단원
        assert by_code[_UNIT].parent_code is None
        assert by_code[_SUBUNIT].level == ConceptLevel.소단원
        assert by_code[_SUBUNIT].intrinsic_difficulty is None  # 소단원은 난이도 없음
        assert by_code[_ATOM].level == ConceptLevel.세부개념

    def test_body_fields_have_no_record_slot(self) -> None:
        # redaction: 레코드에 본문 슬롯이 *없다*(구조적 차단).
        fields = set(AtomBackendConceptRecord.__dataclass_fields__)
        for body in (
            "description",
            "formal_definition",
            "core_proposition",
            "misconception",
        ):
            assert body not in fields
        assert fields == {
            "code",
            "name_ko",
            "level",
            "parent_code",
            "intrinsic_difficulty",
        }

    def test_missing_name_skipped(self, tmp_path: Path) -> None:
        path = self._write(
            tmp_path,
            [
                {
                    "code": _ATOM,
                    "name": "  ",
                    "level": "세부개념",
                    "parent_code": _SUBUNIT,
                }
            ],
        )
        assert load_atom_concepts_from_graph_json(path) == []

    def test_bad_level_skipped(self, tmp_path: Path) -> None:
        path = self._write(
            tmp_path,
            [{"code": _ATOM, "name": "x", "level": "잘못된레벨", "parent_code": None}],
        )
        assert load_atom_concepts_from_graph_json(path) == []

    def test_missing_code_raises(self, tmp_path: Path) -> None:
        path = self._write(tmp_path, [{"name": "x", "level": "단원"}])
        with pytest.raises(ValueError, match="code가 없습니다"):
            load_atom_concepts_from_graph_json(path)


# ──────────────────────────────────────────────────────────────────────────
# ② clamp_difficulty
# ──────────────────────────────────────────────────────────────────────────
class TestClampDifficulty:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [(1, 1.0), (3, 3.0), (5, 5.0), (0, 1.0), (6, 5.0), ("4", 4.0)],
    )
    def test_clamp(self, raw: object, expected: float) -> None:
        assert clamp_difficulty(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "  ", "abc"])
    def test_none(self, raw: object) -> None:
        assert clamp_difficulty(raw) is None


# ──────────────────────────────────────────────────────────────────────────
# ③ upsert SQL
# ──────────────────────────────────────────────────────────────────────────
class TestUpsertStatement:
    def test_on_conflict_code(self) -> None:
        store, engine = _fake_store()
        store.upsert(_record())
        sql = _compile(engine.executed[0])
        assert "INSERT INTO concept" in sql
        assert "ON CONFLICT" in sql
        assert "code" in sql

    def test_does_not_set_pk_created_or_parent(self) -> None:
        store, engine = _fake_store()
        store.upsert(_record())
        sql = _compile(engine.executed[0])
        set_clause = sql.split("DO UPDATE SET", 1)[1].split("RETURNING", 1)[0]
        assert "concept_id" not in set_clause
        assert "created_at" not in set_clause
        # parent_concept_id는 upsert에서 다루지 않는다(2-pass).
        assert "parent_concept_id" not in set_clause
        for col in ("name_ko", "level", "intrinsic_difficulty"):
            assert col in set_clause

    def test_upsert_omits_body_columns(self) -> None:
        store, engine = _fake_store()
        store.upsert(_record())
        sql = _compile(engine.executed[0])
        assert "description" not in sql
        assert "formal_definition" not in sql


# ──────────────────────────────────────────────────────────────────────────
# ④ resolve_parents
# ──────────────────────────────────────────────────────────────────────────
class TestCmsOwnership:
    """P3-26 — CMS가 만든 개념(`cms_edited_at` 있음)은 같은 코드의 파일 레코드가 덮지 못한다."""

    def test_the_upsert_is_guarded_and_overwrite_releases_the_marker(self) -> None:
        store, engine = _fake_store()
        store.upsert(_record())
        sql = _compile(engine.executed[0])
        assert "cms_edited_at IS NULL" in sql
        assert "cms_edited_at" not in sql.split("DO UPDATE SET", 1)[1].split("WHERE", 1)[0]
        store2, engine2 = _fake_store()
        store2.upsert(_record(), overwrite_cms_edits=True)
        sql2 = _compile(engine2.executed[0])
        assert "cms_edited_at IS NULL" not in sql2
        assert "cms_edited_at" in sql2.split("DO UPDATE SET", 1)[1]

    def test_a_skipped_row_is_reported_and_not_counted(self) -> None:
        store, engine = _fake_store()
        engine.insert_written = False
        conflicts: list[str] = []
        written, _ = populate_atom_concepts([_record()], store=store, conflicts=conflicts)
        assert written == 0 and conflicts == [f"concept:{_record().code}"]

    def test_a_written_row_is_not_a_conflict(self) -> None:
        store, _ = _fake_store()
        conflicts: list[str] = []
        written, _ = populate_atom_concepts([_record()], store=store, conflicts=conflicts)
        assert written == 1 and conflicts == []

    def test_resolving_parents_never_rewrites_a_cms_owned_row(self) -> None:
        store, engine = _fake_store()
        store.resolve_parents([_record(parent_code=_UNIT)])
        updates = [_compile(s) for s in engine.executed if "UPDATE" in _compile(s)]
        assert updates and all("cms_edited_at IS NULL" in u for u in updates)


class TestResolveParents:
    def test_resolves_parent_to_uuid_update(self) -> None:
        store, engine = _fake_store()
        resolved, skipped = store.resolve_parents([_record(parent_code=_SUBUNIT)])
        assert resolved == 1
        assert skipped == []
        # SELECT(code맵) + UPDATE 1.
        sqls = [_compile(s) for s in engine.executed]
        assert any("UPDATE concept SET parent_concept_id" in s for s in sqls)

    def test_skips_root_without_parent(self) -> None:
        store, engine = _fake_store()
        resolved, skipped = store.resolve_parents([_record(parent_code=None)])
        assert resolved == 0
        assert skipped == []
        # parent 없는 노드는 UPDATE 안 함(SELECT만).
        assert all("UPDATE" not in _compile(s) for s in engine.executed)

    def test_unresolved_parent_skipped(self) -> None:
        # parent_code가 맵에 없으면 skip + 메시지.
        store, _ = _fake_store(code_rows=[_Row(_ATOM, _UUID_ATOM)])  # 맵에 부모 없음
        resolved, skipped = store.resolve_parents([_record(parent_code="없는코드")])
        assert resolved == 0
        assert any("parent 미해소" in m for m in skipped)


# ──────────────────────────────────────────────────────────────────────────
# ⑤ populate
# ──────────────────────────────────────────────────────────────────────────
class TestPopulate:
    def test_populate_counts_and_resolves(self) -> None:
        store, _ = _fake_store()
        loaded, parent_skipped = populate_atom_concepts(
            [_record(), _record(code=_UNIT, level=ConceptLevel.단원, parent_code=None)],
            store=store,
        )
        assert loaded == 2
        assert parent_skipped == []

    def test_default_settings(self) -> None:
        store = AtomBackendConceptStore()
        assert isinstance(store._resolved_settings, Settings)
