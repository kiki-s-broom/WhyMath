"""atom ①오개념 → misconception_catalog 승격 *단위테스트* — Slice 2 (hermetic·PG 불요).

CI hermetic 잡엔 PostgreSQL이 없으므로 실 라운드트립은 통합테스트
(`test_atom_misconception_catalog_integration.py`·실 PG 게이트)로 미룬다. 여기서는 PG 없이 검증
가능한 것만 못 박는다(`test_misconception_loader.py` 가짜 엔진 패턴 재사용):

  ① `atom_misconception_rows` — graph.json → 행 dict 투영(mis_id 'ATOM:' 접두·필드 매핑)
  ② 필터 — 비-원자(단원/소단원) skip·빈 misconception skip·code 없는 항목 skip
  ③ schema 적합 — 투영 행이 `MisconceptionCatalog`(extra=forbid)로 검증 통과
  ④ `load_atom_misconceptions` — 기존 load_misconceptions 위임·fake store populate 인자·빈 graph 0
  ⑤ store.populate 배선 — mis_id ON CONFLICT(가짜 엔진으로 SQL 관찰·기존 store 재사용 확인)
  ⑥ CLI populate_atom — `load_atom_misconceptions` monkeypatch·파일 부재 Exit 2·정상 stdout 행수
"""

from __future__ import annotations

import json
from pathlib import Path
from types import TracebackType
from typing import Any

import pytest

from whymath_backend.l1.misconception import populate_atom
from whymath_backend.l1.misconception.atom_catalog import (
    ATOM_MIS_ID_PREFIX,
    ATOM_PROVENANCE_NOTE,
    atom_misconception_rows,
    load_atom_misconceptions,
)
from whymath_backend.l1.misconception.catalog_loader import MisconceptionCatalogStore
from whymath_backend.schema.misconception_catalog import MisconceptionCatalog


# ──────────────────────────────────────────────────────────────────────────
# graph.json 픽스처 — 실 코퍼스 원자 항목 모양을 본뜬 concept dict
# ──────────────────────────────────────────────────────────────────────────
def _atom(
    code: str = "2수01-01-2",
    *,
    misconception: str | None = "끝까지 세고도 '몇 개?'에 다시 셈(기수·서수 혼동)",
    misconception_type: str | None = "개념혼동",
    school_level: str | None = "초등",
    subject_area: str | None = "수와 연산",
    subunit: str | None = "100까지의 수와 세기",
    standard_codes: list[str] | None = None,
    level: str = "세부개념",
) -> dict[str, Any]:
    """graph.json `concepts` 원자 항목 dict(실 코퍼스 row 미러)."""
    record: dict[str, Any] = {
        "code": code,
        "name": "기수 원리(마지막 수=전체 개수)",
        "level": level,
        "school_level": school_level,
        "subject_area": subject_area,
        "subunit": subunit,
        "misconception": misconception,
        "misconception_type": misconception_type,
        "standard_codes": ["[2수01-01]"] if standard_codes is None else standard_codes,
    }
    return record


def _graph(concepts: list[dict[str, Any]]) -> dict[str, Any]:
    """graph.json Collection 객체(concepts 배열) — Phase 1 산출 형태."""
    return {"version": "atom_graph_v1", "concepts": concepts}


def _write_graph(tmp_path: Path, concepts: list[dict[str, Any]]) -> Path:
    path = tmp_path / "graph.json"
    path.write_text(json.dumps(_graph(concepts), ensure_ascii=False), encoding="utf-8")
    return path


# ──────────────────────────────────────────────────────────────────────────
# 가짜 sync 엔진 — begin() 컨텍스트 + execute() (test_misconception_loader 미러)
# ──────────────────────────────────────────────────────────────────────────
class _FakeResult:
    """적재 upsert 결과 흉내 — RETURNING이 키 1행을 돌려준 상태(=적재됨). P3-25 보호 판정이 읽는다."""

    def first(self) -> tuple[int]:
        return (1,)


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

    def execute(self, statement: object) -> _FakeResult:
        self._engine.executed.append(statement)
        return _FakeResult()


class _FakeEngine:
    """SQLAlchemy sync Engine 최소 흉내 — begin() + 실행 statement 수집."""

    def __init__(self) -> None:
        self.executed: list[object] = []

    def begin(self) -> _FakeConnection:
        return _FakeConnection(self)


def _pg_dialect() -> object:
    from sqlalchemy.dialects import postgresql

    return postgresql.dialect()


def _compile(statement: object) -> str:
    return str(statement.compile(dialect=_pg_dialect()))  # type: ignore[attr-defined]


# ──────────────────────────────────────────────────────────────────────────
# ① atom_misconception_rows — 투영·mis_id 접두·필드 매핑
# ──────────────────────────────────────────────────────────────────────────
class TestAtomMisconceptionRows:
    def test_maps_atom_fields(self, tmp_path: Path) -> None:
        path = _write_graph(tmp_path, [_atom()])
        rows = atom_misconception_rows(path)
        assert len(rows) == 1
        row = rows[0]
        # mis_id 합성(ATOM: 접두 + code) — 구 M-series와 네임스페이스 분리.
        assert row["mis_id"] == f"{ATOM_MIS_ID_PREFIX}2수01-01-2"
        # 본문·유형·느슨참조 매핑.
        assert row["canonical_statement"].startswith("끝까지 세고도")
        assert row["error_type"] == "개념혼동"
        assert row["concept_src_id"] == "2수01-01-2"
        assert row["standard_code"] == "[2수01-01]"  # standard_codes[0]
        assert row["school_level"] == "초등"
        assert row["domain"] == "수와 연산"  # ← subject_area
        assert row["subunit"] == "100까지의 수와 세기"
        assert row["provenance_note"] == ATOM_PROVENANCE_NOTE

    def test_only_schema_fields_emitted(self, tmp_path: Path) -> None:
        # 투영 행 키는 MisconceptionCatalog 필드 부분집합(extra=forbid 호환 — 미보유는 미방출).
        path = _write_graph(tmp_path, [_atom()])
        row = atom_misconception_rows(path)[0]
        allowed = set(MisconceptionCatalog.model_fields)
        assert set(row).issubset(allowed)
        # 원천 미보유 칸은 방출하지 않는다(None default로 남김 — 날조 금지).
        absent_fields = (
            "student_wrong_thinking",
            "distractor_rule",
            "correction_point",
            "ccss_code",
        )
        for absent in absent_fields:
            assert absent not in row

    def test_standard_code_none_when_codes_empty(self, tmp_path: Path) -> None:
        path = _write_graph(tmp_path, [_atom(standard_codes=[])])
        row = atom_misconception_rows(path)[0]
        assert row["standard_code"] is None

    def test_university_atom_synthetic_standard_code(self, tmp_path: Path) -> None:
        # 대학 원자도 합성 standard_code(예 [CALC1-01-01])를 느슨참조로 보존.
        uni = _atom(
            code="CALC1-C01",
            misconception="한 입력에 출력이 여러 개 나와도 함수라 부를 수 있다",
            misconception_type="정의·표기오류",
            school_level="대학",
            subject_area="미적분학 I",
            subunit="함수의 종류",
            standard_codes=["[CALC1-01-01]"],
        )
        row = atom_misconception_rows(_write_graph(tmp_path, [uni]))[0]
        assert row["mis_id"] == f"{ATOM_MIS_ID_PREFIX}CALC1-C01"
        assert row["standard_code"] == "[CALC1-01-01]"
        assert row["domain"] == "미적분학 I"


# ──────────────────────────────────────────────────────────────────────────
# ② 필터 — 비-원자·빈 misconception·code 없는 항목 skip
# ──────────────────────────────────────────────────────────────────────────
class TestFilter:
    def test_non_atom_levels_skipped(self, tmp_path: Path) -> None:
        unit = _atom(code="초수연-U1", level="단원")
        subunit = _atom(code="초수연-U1-S1", level="소단원")
        path = _write_graph(tmp_path, [unit, subunit, _atom()])
        rows = atom_misconception_rows(path)
        assert [r["concept_src_id"] for r in rows] == ["2수01-01-2"]  # 원자만.

    def test_empty_misconception_skipped(self, tmp_path: Path) -> None:
        path = _write_graph(
            tmp_path,
            [_atom(code="A1", misconception=None), _atom(code="A2", misconception="  "), _atom()],
        )
        rows = atom_misconception_rows(path)
        assert [r["concept_src_id"] for r in rows] == ["2수01-01-2"]

    def test_missing_code_skipped(self, tmp_path: Path) -> None:
        bad = _atom()
        del bad["code"]
        path = _write_graph(tmp_path, [bad, _atom()])
        rows = atom_misconception_rows(path)
        assert len(rows) == 1

    def test_empty_or_missing_concepts(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.json"
        empty.write_text(json.dumps({"version": "x"}), encoding="utf-8")
        assert atom_misconception_rows(empty) == []


# ──────────────────────────────────────────────────────────────────────────
# ③ schema 적합 — 투영 행이 MisconceptionCatalog(extra=forbid) 검증 통과
# ──────────────────────────────────────────────────────────────────────────
class TestSchemaConformance:
    def test_rows_validate_as_catalog(self, tmp_path: Path) -> None:
        path = _write_graph(tmp_path, [_atom(), _atom(code="9수01-01-1")])
        for row in atom_misconception_rows(path):
            model = MisconceptionCatalog.model_validate(row)  # extra=forbid 통과(미스 시 예외).
            assert model.mis_id.startswith(ATOM_MIS_ID_PREFIX)
            assert model.canonical_statement is not None


# ──────────────────────────────────────────────────────────────────────────
# ④ load_atom_misconceptions — load_misconceptions 위임·빈 graph 0
# ──────────────────────────────────────────────────────────────────────────
class _RecordingStore:
    """populate 인자를 기록하는 fake store(load 위임 배선 검증)."""

    def __init__(self) -> None:
        self.received: list[MisconceptionCatalog] | None = None

    def populate(self, records: list[MisconceptionCatalog], **_cms: object) -> int:
        self.received = list(records)
        return len(self.received)


class TestLoadAtomMisconceptions:
    def test_delegates_to_store(self, tmp_path: Path) -> None:
        store = _RecordingStore()
        path = _write_graph(tmp_path, [_atom(code="A1"), _atom(code="A2")])
        count = load_atom_misconceptions(path, store=store)  # type: ignore[arg-type]
        assert count == 2
        assert store.received is not None
        # 투영 행이 검증된 MisconceptionCatalog로 store에 전달된다(접두 mis_id).
        assert {m.mis_id for m in store.received} == {
            f"{ATOM_MIS_ID_PREFIX}A1",
            f"{ATOM_MIS_ID_PREFIX}A2",
        }
        assert all(isinstance(m, MisconceptionCatalog) for m in store.received)

    def test_empty_graph_is_zero(self, tmp_path: Path) -> None:
        store = _RecordingStore()
        path = _write_graph(tmp_path, [_atom(level="단원")])  # 원자 0.
        assert load_atom_misconceptions(path, store=store) == 0  # type: ignore[arg-type]

    def test_idempotent_reload_same_count(self, tmp_path: Path) -> None:
        store = _RecordingStore()
        path = _write_graph(tmp_path, [_atom(code="A1")])
        assert load_atom_misconceptions(path, store=store) == 1  # type: ignore[arg-type]
        assert load_atom_misconceptions(path, store=store) == 1  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────────────
# ⑤ store.populate 배선 — mis_id ON CONFLICT(가짜 엔진·기존 store 재사용 확인)
# ──────────────────────────────────────────────────────────────────────────
class TestStoreWiring:
    def test_on_conflict_mis_id_via_existing_store(self, tmp_path: Path) -> None:
        engine = _FakeEngine()
        store = MisconceptionCatalogStore(engine=engine)  # type: ignore[arg-type]  # 가짜 엔진
        path = _write_graph(tmp_path, [_atom()])
        count = load_atom_misconceptions(path, store=store)
        assert count == 1
        sql = _compile(engine.executed[0])
        assert "INSERT INTO misconception_catalog" in sql
        assert "ON CONFLICT" in sql
        assert "mis_id" in sql
        # PK는 SET하지 않는다(보존·멱등) — 나머지 컬럼만 갱신.
        set_clause = sql.split("DO UPDATE SET", 1)[1].split("RETURNING", 1)[0]
        assert "mis_id" not in set_clause
        assert "canonical_statement" in set_clause


# ──────────────────────────────────────────────────────────────────────────
# ⑥ CLI populate_atom — load monkeypatch·파일 부재 Exit 2·stdout 행수
# ──────────────────────────────────────────────────────────────────────────
class TestPopulateAtomMain:
    def test_loads_and_reports_count(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        src = tmp_path / "graph.json"
        src.write_text("{}", encoding="utf-8")  # 존재 검사용(load는 monkeypatch).
        calls: dict[str, Path] = {}

        def _fake_load(path: Path, **_cms: object) -> int:
            calls["path"] = path
            return 1837

        monkeypatch.setattr(populate_atom, "load_atom_misconceptions", _fake_load)
        rc = populate_atom.main(["--graph", str(src)])
        assert rc == 0
        assert calls == {"path": src}
        assert "1837" in capsys.readouterr().out

    def test_missing_file_exits_2(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(populate_atom, "load_atom_misconceptions", lambda _p, **_c: 0)
        rc = populate_atom.main(["--graph", str(tmp_path / "nope.json")])
        assert rc == 2

    def test_verbose_flag_accepted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        src = tmp_path / "graph.json"
        src.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(populate_atom, "load_atom_misconceptions", lambda _p, **_c: 5)
        rc = populate_atom.main(["--graph", str(src), "--verbose"])
        assert rc == 0
