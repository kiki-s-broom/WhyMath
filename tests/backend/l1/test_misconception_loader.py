"""오개념 카탈로그 코퍼스 → backend 적재 *단위테스트* — B.3 로더 (hermetic·PG 불요).

CI hermetic 잡엔 PostgreSQL이 없으므로 `MisconceptionCatalogStore`의 *실 라운드트립*은
통합테스트(`test_misconception_loader_integration.py`·실 PG 게이트)로 미룬다. 여기서는 PG 없이
검증 가능한 것만 못 박는다(`test_standard_loader.py`·`test_concept_backend_load.py` 가짜 엔진
패턴 재사용):

  ① Collection JSON 파싱 — 단일 객체(jsonl 아님)·`misconceptions` 배열·dict|Path·TypeError
  ② `_misconception_from_row` — rename 0(전체 16필드·최소 {mis_id}만)
  ③ `load_misconceptions` — 빈 컬렉션→0·fake store로 populate 인자 검증(monkeypatch)
  ④ CLI populate — `load_misconceptions` monkeypatch·파일 부재 Exit 2·정상 stdout 행수

성취기준 로더와 달리 오개념엔 rename·해석 seam이 없다(코퍼스 키=schema 필드·느슨참조 원천 저장).
따라서 가짜 엔진은 begin() 컨텍스트 + execute()만 흉내내면 된다(개념 해석/norm_id 조회 불요).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import TracebackType
from typing import Any

import pytest

from whymath_backend.config import Settings
from whymath_backend.l1.misconception import populate
from whymath_backend.l1.misconception.catalog_loader import (
    MisconceptionCatalogStore,
    _as_collection,
    _misconception_from_row,
    load_misconceptions,
)
from whymath_backend.schema.misconception_catalog import MisconceptionCatalog

# 실 코퍼스 행 모양을 본뜬 전체 16필드 row(채우율 100% 케이스).
_MIS_ID = "M0425"


def _full_row(mis_id: str = _MIS_ID) -> dict[str, Any]:
    """코퍼스 오개념 dict — 전체 16필드(실 코퍼스 row0 미러·rename 0)."""
    return {
        "mis_id": mis_id,
        "canonical_statement": "서수와 기수를 혼동한다.",
        "student_wrong_thinking": "셀 때 사물을 건너뛰거나 두 번 센다.",
        "distractor_rule": "잘못 처리한 결과를 오답 보기로 배치",
        "error_type": "순서오류",
        "difficulty": "하",
        "correction_point": "0~100까지 세고 읽고 쓴다.",
        "ccss_code": "1.NBT.A.1",
        "concept_src_id": "N1",
        "standard_code": "[2수01-01]",
        "school_level": "초등(1~2학년군)",
        "domain": "수와 연산",
        "subunit": "수 개념과 세기(0~100)",
        "mapping_confidence": "기준(원본)",
        "mapping_score": 1.0,
        "provenance_note": "원본",
    }


def _collection(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """오개념 Collection 객체(표지 메타 + misconceptions 배열) — 코퍼스 산출 형태."""
    return {
        "source_citation": "출처: WhyMath 자체 저작 ...",
        "license_notice": "와이매스 자체 저작물 ...",
        "collected_at": "2026-06-20T00:00:00+00:00",
        "count": len(rows),
        "misconceptions": rows,
    }


# ──────────────────────────────────────────────────────────────────────────
# 가짜 sync 엔진 — begin() 컨텍스트 + execute() (PG 없이 배선 관찰)
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


def _store() -> tuple[MisconceptionCatalogStore, _FakeEngine]:
    engine = _FakeEngine()
    store = MisconceptionCatalogStore(engine=engine)  # type: ignore[arg-type]  # 가짜 엔진
    return store, engine


# ──────────────────────────────────────────────────────────────────────────
# ① Collection JSON 파싱 — dict|Path|TypeError
# ──────────────────────────────────────────────────────────────────────────
class TestAsCollection:
    def test_dict_passthrough(self) -> None:
        coll = _collection([_full_row()])
        assert _as_collection(coll) is coll

    def test_path_loads_single_object(self, tmp_path: Path) -> None:
        path = tmp_path / "misconceptions.json"
        path.write_text(
            json.dumps(_collection([_full_row()]), ensure_ascii=False),
            encoding="utf-8",
        )
        loaded = _as_collection(path)
        assert loaded["misconceptions"][0]["mis_id"] == _MIS_ID

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(TypeError):
            _as_collection(["not", "a", "collection"])  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────────────
# ② _misconception_from_row — rename 0(전체 16필드·최소 {mis_id})
# ──────────────────────────────────────────────────────────────────────────
class TestMisconceptionFromRow:
    def test_full_row_roundtrips(self) -> None:
        model = _misconception_from_row(_full_row())
        assert isinstance(model, MisconceptionCatalog)
        assert model.mis_id == _MIS_ID
        # rename 0 — 코퍼스 키가 그대로 schema 필드.
        assert model.concept_src_id == "N1"
        assert model.standard_code == "[2수01-01]"
        assert model.error_type == "순서오류"
        assert model.mapping_score == 1.0

    def test_minimal_row_only_mis_id(self) -> None:
        # mis_id만 있는 최소 row — 나머지는 None default(채우율 52~100%).
        model = _misconception_from_row({"mis_id": "M9999"})
        assert model.mis_id == "M9999"
        assert model.canonical_statement is None
        assert model.mapping_score is None


# ──────────────────────────────────────────────────────────────────────────
# ③ load_misconceptions — 빈 컬렉션→0·fake store populate 인자 검증·dict/Path
# ──────────────────────────────────────────────────────────────────────────
class _RecordingStore:
    """populate 인자를 기록하는 fake store(load_misconceptions 배선 검증)."""

    def __init__(self) -> None:
        self.received: list[MisconceptionCatalog] | None = None

    def populate(self, records: list[MisconceptionCatalog], **_cms: object) -> int:
        self.received = list(records)
        return len(self.received)


class TestLoadMisconceptions:
    def test_empty_collection_is_zero(self) -> None:
        store, engine = _store()
        assert load_misconceptions(None, _collection([]), store=store) == 0  # type: ignore[arg-type]
        assert engine.executed == []

    def test_missing_key_is_zero(self) -> None:
        store, _ = _store()
        assert load_misconceptions(None, {"count": 0}, store=store) == 0  # type: ignore[arg-type]

    def test_invalid_input_type_raises(self) -> None:
        store, _ = _store()
        with pytest.raises(TypeError):
            load_misconceptions(None, ["bad"], store=store)  # type: ignore[arg-type]

    def test_store_receives_validated_models(self) -> None:
        store = _RecordingStore()
        count = load_misconceptions(
            None,
            _collection([_full_row("M0001"), _full_row("M0002")]),
            store=store,  # type: ignore[arg-type]
        )
        assert count == 2
        assert store.received is not None
        assert {m.mis_id for m in store.received} == {"M0001", "M0002"}
        assert all(isinstance(m, MisconceptionCatalog) for m in store.received)

    def test_from_path(self, tmp_path: Path) -> None:
        path = tmp_path / "misconceptions.json"
        path.write_text(
            json.dumps(_collection([_full_row()]), ensure_ascii=False),
            encoding="utf-8",
        )
        store, engine = _store()
        assert load_misconceptions(None, path, store=store) == 1  # type: ignore[arg-type]
        assert len(engine.executed) == 1  # 행당 1 upsert


# ──────────────────────────────────────────────────────────────────────────
# ④ store.populate — mis_id ON CONFLICT·PK 미-SET·dedup·멱등 (가짜 엔진)
# ──────────────────────────────────────────────────────────────────────────
class TestPopulate:
    def test_on_conflict_mis_id_pk(self) -> None:
        store, engine = _store()
        store.populate([_misconception_from_row(_full_row())])
        sql = _compile(engine.executed[0])
        assert "INSERT INTO misconception_catalog" in sql
        assert "ON CONFLICT" in sql
        assert "mis_id" in sql

    def test_does_not_set_mis_id_on_conflict(self) -> None:
        store, engine = _store()
        store.populate([_misconception_from_row(_full_row())])
        sql = _compile(engine.executed[0])
        assert "DO UPDATE SET" in sql
        after_set = sql.split("DO UPDATE SET", 1)[1]
        set_clause = after_set.split("RETURNING", 1)[0]
        assert "mis_id" not in set_clause
        # SET은 canonical_statement 등 나머지 컬럼을 갱신한다.
        assert "canonical_statement" in set_clause

    def test_input_dedup_last_wins(self) -> None:
        store, engine = _store()
        count = store.populate(
            [
                _misconception_from_row({"mis_id": _MIS_ID, "canonical_statement": "첫"}),
                _misconception_from_row({"mis_id": _MIS_ID, "canonical_statement": "둘째"}),
            ]
        )
        assert count == 1  # dedup → 1행
        assert len(engine.executed) == 1
        params = engine.executed[0].compile(dialect=_pg_dialect()).params  # type: ignore[attr-defined]
        assert "둘째" in params.values()  # 마지막 우선

    def test_empty_records_is_zero(self) -> None:
        store, engine = _store()
        assert store.populate([]) == 0
        assert engine.executed == []


def test_store_uses_default_settings_when_unset() -> None:
    store = MisconceptionCatalogStore()
    assert isinstance(store._resolved_settings, Settings)


# ──────────────────────────────────────────────────────────────────────────
# ⑤ CLI populate — load_misconceptions monkeypatch·파일 부재 Exit 2·stdout 행수
# ──────────────────────────────────────────────────────────────────────────
def _touch(path: Path) -> Path:
    """빈 Collection JSON 자리표시(존재 검사용 — load_*는 monkeypatch라 내용 무관)."""
    path.write_text("{}", encoding="utf-8")
    return path


class TestPopulateMain:
    def test_loads_and_reports_count(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        src = _touch(tmp_path / "misconceptions.json")
        calls: dict[str, Path] = {}

        def _fake_load(session: Any, path: Path, **_cms: Any) -> int:
            calls["path"] = path
            return 839

        monkeypatch.setattr(populate, "load_misconceptions", _fake_load)
        rc = populate.main(["--misconceptions", str(src)])
        assert rc == 0
        assert calls == {"path": src}
        out = capsys.readouterr().out
        assert "839" in out

    def test_missing_file_exits_2(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(populate, "load_misconceptions", lambda _s, _p, **_c: 0)
        rc = populate.main(["--misconceptions", str(tmp_path / "nope.json")])
        assert rc == 2

    def test_verbose_flag_accepted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        src = _touch(tmp_path / "misconceptions.json")
        monkeypatch.setattr(populate, "load_misconceptions", lambda _s, _p, **_c: 5)
        rc = populate.main(["--misconceptions", str(src), "--verbose"])
        assert rc == 0


class TestCorpusFitsOrmColumns:
    """실 코퍼스 전건이 ORM varchar 폭에 맞는지 hermetic 검증 — 실 PG 오버플로 사전 차단.

    schema(Pydantic)는 문자열 필드에 max_length가 없어(느슨참조·자체 저작 보유) 길이 초과를
    검증하지 못한다 — 오버플로는 실 PG 통합 잡에서만 `value too long for type character
    varying(N)`로 터진다(2026-07-06 S2-p M0862 provenance_note 실측). 이 테스트가 ORM 컬럼의
    String 폭을 introspection해 코퍼스 전건 문자열 필드 길이를 PG 없이 미리 봉인한다.
    """

    def _corpus_path(self) -> Path:
        return (
            Path(__file__).resolve().parents[3]
            / "data"
            / "corpus"
            / "misconceptions_v1"
            / "misconceptions.json"
        )

    def test_all_string_fields_fit_orm_limits(self) -> None:
        import sqlalchemy as sa

        from whymath_backend.db.models.misconception_catalog import MisconceptionCatalog as OrmModel

        corpus = self._corpus_path()
        if not corpus.exists():
            pytest.skip("실 코퍼스 미존재(data/corpus/misconceptions_v1/misconceptions.json)")

        # ORM 컬럼 → String 폭(길이 제약이 있는 문자열 컬럼만).
        limits: dict[str, int] = {}
        for column in sa.inspect(OrmModel).mapper.columns:
            column_type = column.type
            if isinstance(column_type, sa.String) and column_type.length is not None:
                limits[column.key] = column_type.length

        payload = json.loads(corpus.read_text(encoding="utf-8"))
        offenders: list[str] = []
        for row in payload["misconceptions"]:
            for field, limit in limits.items():
                value = row.get(field)
                if isinstance(value, str) and len(value) > limit:
                    offenders.append(
                        f"{row.get('mis_id')}.{field} len={len(value)} > {limit}: {value!r}"
                    )
        assert not offenders, "ORM varchar 폭 초과(실 PG 오버플로 위험):\n" + "\n".join(offenders)
