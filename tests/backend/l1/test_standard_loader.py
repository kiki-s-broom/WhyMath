"""NCIC 성취기준 코퍼스 → backend 적재 *단위테스트* — P1 코퍼스 로더 (hermetic·PG 불요).

CI hermetic 잡엔 PostgreSQL이 없으므로 `AchievementStandardStore`/`ConceptStandardLinkStore`의 *실
라운드트립*은 통합테스트(`test_standard_loader_integration.py`·실 PG 게이트)로 미룬다.
여기서는 PG 없이
검증 가능한 것만 못 박는다(`test_concept_backend_load.py`·`test_concept_backend_edge_load.py` 가짜
엔진 패턴 재사용):

  ① Collection JSON 파싱 — 단일 객체(jsonl 아님)·`standards`/`links` 배열·dict|Path 입력
  ② 키 rename seam — 코퍼스 `code`→`official_code`·`concept_src_id`→`concept_code` 슬롯
  ③ 성취기준 upsert SQL — ON CONFLICT(norm_id)·official_code 충돌쌍 2행·input dedup·멱등
  ④ 링크 upsert SQL — **P2b**: src_id→새 code 해석(resolve-via-map·N+1 0)·ON CONFLICT(concept_code,
     norm_id,link_type)·link_id 미-SET·orphan skip(개념 해석 실패 + 성취기준 실 FK 둘 다)

P2b 재ID(2026-06-16): 코퍼스 링크의 `concept_src_id`는 *원천 src_id*다. 적재기가 backend `concept`을
`{source_id: code}`로 단일 조회해 재ID된 새 `code`로 해석한다(backend_edge UC→UUID 해석과 동형).
가짜 엔진(`_FakeEngine`)은 begin()/connect() 컨텍스트 + execute()를 흉내내 실행 statement·norm_id
존재 조회·src_id→code 해석 조회 결과를 제어한다 — psycopg/PG 없이 배선·rename·해석·멱등 키·orphan
skip을 검증한다.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import TracebackType
from typing import Any, Literal

import pytest

from whymath_backend.config import Settings
from whymath_backend.l1.standards.standard_loader import (
    AchievementStandardStore,
    ConceptStandardLinkStore,
    load_links,
    load_standards,
)
from whymath_backend.schema.standard import ConceptStandardLink

# NCIC 형식 B(고1 공통수학) norm_id·official_code 예시 — schema 패턴 통과 값.
_NORM_A = "2022_10공수1_01_01"
_NORM_B = "2015_10공수1_01_01"  # 같은 official_code·다른 개정(충돌쌍)
_CODE_AB = "[10공수1-01-01]"  # 2022·2015 양쪽에 동일(official_code 비유일)
# P2b 재ID: 코퍼스 링크의 `concept_src_id`는 *원천 src_id*다. 적재기가 `{source_id: code}` 맵으로
# 재ID된 새 `code`로 해석한다. _SRC_ID(원천)→_CODE(해석된 새 형식). _SRC_ID_ORPHAN은 맵에 없는
# src_id(개념 미적재·재ID 전 — 개념 orphan).
_SRC_ID = "N1"  # 링크 concept_src_id(원천 src_id·해석 전)
_CODE = "HIGH-ALG-001"  # _SRC_ID가 해석되는 backend concept.code(재ID 새 형식·느슨참조)
_SRC_ID_ORPHAN = "ZZ99"  # 맵에 없는 src_id(개념 orphan)
_NORM_ORPHAN = "2022_2수_09_09"  # 적재 성취기준 집합에 없는 norm_id(성취기준 orphan)


# ──────────────────────────────────────────────────────────────────────────
# 코퍼스 Collection JSON 픽스처 (인라인 합성 — data/corpus/ 미기록)
# ──────────────────────────────────────────────────────────────────────────
def _standard_row(
    norm_id: str = _NORM_A,
    code: str = _CODE_AB,
    *,
    curriculum_revision: str = "2022 개정",
    statement: str = "다항식의 사칙연산을 할 수 있다.",
) -> dict[str, Any]:
    """코퍼스 성취기준 dict — *코퍼스 키 `code`* 사용(rename seam 검증용)."""
    return {
        "norm_id": norm_id,
        "code": code,  # ← 코퍼스 키(backend는 official_code로 rename)
        "grade_band": "고등학교",
        "school_type": "고등학교",
        "subject": "공통수학1",
        "domain": "다항식",
        "sub_domain": None,
        "statement": statement,
        "commentary": None,
        "big_idea": None,
        "curriculum_revision": curriculum_revision,
        "effective_from": None,
        "parent_codes": [],
        "source_url": "https://www.ncic.go.kr/mobile.kri.org4.inventoryList.do",
        "source_document": None,
    }


def _standards_collection(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """성취기준 Collection 객체(표지 메타 + standards 배열) — write_json 산출 형태."""
    return {
        "source_citation": "출처: 교육부 고시 ...",
        "license_notice": "공공누리 제1유형 ...",
        "curriculum_revision": "2022 개정",
        "collected_at": "2026-06-16T00:00:00+00:00",
        "crawler_version": "0.1.0",
        "standards": rows,
    }


def _link_row(
    concept_src_id: str = _SRC_ID,
    norm_id: str = _NORM_A,
    *,
    link_type: str = "직접",
    note: str | None = None,
) -> dict[str, Any]:
    """코퍼스 링크 dict — *코퍼스 키 `concept_src_id`*(src_id) 사용(rename·해석 seam 검증용)."""
    return {
        "concept_src_id": concept_src_id,  # ← 코퍼스 키(src_id·backend가 새 code로 해석)
        "norm_id": norm_id,
        "link_type": link_type,
        "note": note,
    }


def _links_collection(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """링크 Collection 객체(표지 메타 + links 배열) — write_links_json 산출 형태."""
    return {
        "source_citation": "출처: 교육부 고시 ...",
        "license_notice": "공공누리 제1유형 ...",
        "curriculum_revision": "2022 개정",
        "collected_at": "2026-06-16T00:00:00+00:00",
        "crawler_version": "0.1.0",
        "links": rows,
    }


# ──────────────────────────────────────────────────────────────────────────
# 가짜 sync 엔진 — begin()/connect() 컨텍스트 + execute() (PG 없이 배선 관찰)
# ──────────────────────────────────────────────────────────────────────────
class _FakeResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


class _NormRow:
    """norm_id 존재 조회 결과 행 흉내 — `.norm_id` 속성 접근(성취기준 orphan 대조)."""

    def __init__(self, norm_id: str) -> None:
        self.norm_id = norm_id


class _ConceptRow:
    """src_id→code 조회 결과 행 흉내 — `.source_id`·`.code` 속성 접근(개념 해석·P2b)."""

    def __init__(self, source_id: str | None, code: str) -> None:
        self.source_id = source_id
        self.code = code


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
        compiled = str(statement.compile(dialect=_pg_dialect()))  # type: ignore[attr-defined]
        is_select = "SELECT" in compiled and "INSERT" not in compiled
        # src_id→code 해석 조회(SELECT concept.source_id, concept.code)면
        # 개념 맵 행을 돌려준다(P2b).
        if is_select and "concept.source_id" in compiled and "concept.code" in compiled:
            return _FakeResult(self._engine.concept_rows)
        # norm_id 존재 조회(SELECT achievement_standard.norm_id)면 알려진 norm_id 행을 돌려준다.
        if is_select and "achievement_standard.norm_id" in compiled:
            return _FakeResult(self._engine.norm_rows)
        return _FakeResult([])


def _pg_dialect() -> object:
    from sqlalchemy.dialects import postgresql

    return postgresql.dialect()


class _FakeEngine:
    """SQLAlchemy sync Engine 최소 흉내
    — begin()/connect() + 실행 statement·norm_id/concept맵 제어."""

    def __init__(
        self,
        norm_rows: list[object] | None = None,
        concept_rows: list[object] | None = None,
    ) -> None:
        self.executed: list[object] = []
        # norm_id 존재 조회가 돌려줄 행. 기본: A·B 둘 다 적재됨(성취기준 orphan 아님).
        self.norm_rows: list[object] = (
            norm_rows if norm_rows is not None else [_NormRow(_NORM_A), _NormRow(_NORM_B)]
        )
        # src_id→code 조회가 돌려줄 행(P2b). 기본: _SRC_ID→_CODE 1건(개념 해석됨·orphan 아님).
        self.concept_rows: list[object] = (
            concept_rows if concept_rows is not None else [_ConceptRow(_SRC_ID, _CODE)]
        )

    def begin(self) -> _FakeConnection:
        return _FakeConnection(self)

    def connect(self) -> _FakeConnection:
        return _FakeConnection(self)


def _compile(statement: object) -> str:
    return str(statement.compile(dialect=_pg_dialect()))  # type: ignore[attr-defined]


def _std_store() -> tuple[AchievementStandardStore, _FakeEngine]:
    engine = _FakeEngine()
    store = AchievementStandardStore(engine=engine)  # type: ignore[arg-type]  # 가짜 엔진(구조만 충족)
    return store, engine


def _link_store(
    norm_rows: list[object] | None = None,
    concept_rows: list[object] | None = None,
) -> tuple[ConceptStandardLinkStore, _FakeEngine]:
    engine = _FakeEngine(norm_rows, concept_rows)
    store = ConceptStandardLinkStore(engine=engine)  # type: ignore[arg-type]  # 가짜 엔진(구조만 충족)
    return store, engine


# ──────────────────────────────────────────────────────────────────────────
# ① Collection JSON 파싱 — 단일 객체·배열 키·dict|Path 입력
# ──────────────────────────────────────────────────────────────────────────
class TestCollectionParsing:
    def test_standards_from_dict_collection(self) -> None:
        # 단일 Collection dict(jsonl 아님)의 standards 배열을 적재한다.
        store, engine = _std_store()
        count = load_standards(None, _standards_collection([_standard_row()]), store=store)
        assert count == 1
        assert len(engine.executed) == 1  # 행당 1 upsert

    def test_standards_from_path_collection(self, tmp_path: Path) -> None:
        # Path 입력 — 파일을 단일 JSON 객체로 로드(write_json 산출 미러).
        path = tmp_path / "standards.json"
        path.write_text(
            json.dumps(_standards_collection([_standard_row()]), ensure_ascii=False),
            encoding="utf-8",
        )
        store, engine = _std_store()
        count = load_standards(None, path, store=store)
        assert count == 1

    def test_links_from_dict_collection(self) -> None:
        store, engine = _link_store()
        count = load_links(None, _links_collection([_link_row()]), store=store)
        assert count == 1

    def test_empty_standards_collection_is_noop(self) -> None:
        store, engine = _std_store()
        assert load_standards(None, _standards_collection([]), store=store) == 0
        assert engine.executed == []

    def test_empty_links_collection_is_noop(self) -> None:
        store, engine = _link_store()
        assert load_links(None, _links_collection([]), store=store) == 0
        assert engine.executed == []

    def test_missing_standards_key_is_noop(self) -> None:
        # 표지만 있고 standards 키가 없는 컬렉션 → 0(graceful).
        store, _ = _std_store()
        assert load_standards(None, {"collected_at": "x"}, store=store) == 0

    def test_invalid_input_type_raises(self) -> None:
        store, _ = _std_store()
        with pytest.raises(TypeError):
            load_standards(None, ["not", "a", "collection"], store=store)  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────────────
# ② 키 rename·해석 seam — code→official_code·concept_src_id(src_id)→해석된 새 code
# ──────────────────────────────────────────────────────────────────────────
def _link_inserts(engine: _FakeEngine) -> list[object]:
    """link upsert INSERT statement만 추린다(SELECT 2종 사이에서 위치 무관 — 위치 의존 제거)."""
    return [s for s in engine.executed if "INSERT INTO concept_standard_link" in _compile(s)]


class TestRenameSeam:
    def test_code_renamed_to_official_code_in_sql(self) -> None:
        # 코퍼스 `code`가 official_code 컬럼으로 적재되고,
        # `code` 컬럼은 없다(개념 code와 혼동 회피).
        store, engine = _std_store()
        load_standards(None, _standards_collection([_standard_row(code=_CODE_AB)]), store=store)
        sql = _compile(engine.executed[0])
        assert "official_code" in sql
        # achievement_standard엔 'code' 컬럼이 없으므로 INSERT 컬럼 목록에도 없다.
        insert_cols = sql.split(")", 1)[0]
        assert " code" not in insert_cols and "(code" not in insert_cols

    def test_concept_src_id_resolved_to_new_code_in_sql(self) -> None:
        # P2b 핵심: 코퍼스 `concept_src_id`(src_id)가 `{source_id: code}` 맵으로 *해석*돼 새 code가
        # concept_code 컬럼에 실린다(store-direct 아님 — src_id 자체가 아니라 해석된 code).
        store, engine = _link_store()
        load_links(None, _links_collection([_link_row(concept_src_id=_SRC_ID)]), store=store)
        inserts = _link_inserts(engine)
        assert len(inserts) == 1
        insert_sql = _compile(inserts[0])
        assert "concept_code" in insert_sql
        # 바인딩된 concept_code 값은 *해석된 새 code*(_CODE)지 원천 src_id(_SRC_ID)가 아니다.
        params = inserts[0].compile(dialect=_pg_dialect()).params  # type: ignore[attr-defined]
        assert _CODE in params.values()
        assert _SRC_ID not in params.values()

    def test_official_code_value_preserved(self) -> None:
        # rename은 *키만* 바꾼다 — 값(고시 원문코드)은 그대로 적재된다.
        store, engine = _std_store()
        load_standards(None, _standards_collection([_standard_row(code=_CODE_AB)]), store=store)
        # 컴파일된 statement의 바인딩 파라미터에 official_code 값이 실린다.
        params = engine.executed[0].compile(dialect=_pg_dialect()).params  # type: ignore[attr-defined]
        assert _CODE_AB in params.values()


# ──────────────────────────────────────────────────────────────────────────
# ③ 성취기준 upsert — ON CONFLICT(norm_id)·official_code 충돌쌍 2행·dedup·멱등
# ──────────────────────────────────────────────────────────────────────────
class TestStandardUpsert:
    def test_on_conflict_norm_id_pk(self) -> None:
        store, engine = _std_store()
        load_standards(None, _standards_collection([_standard_row()]), store=store)
        sql = _compile(engine.executed[0])
        assert "INSERT INTO achievement_standard" in sql
        assert "ON CONFLICT" in sql
        # 충돌 키는 norm_id(PK) — official_code가 아니다(official_code는 비유일).
        assert "norm_id" in sql

    def test_does_not_set_norm_id_on_conflict(self) -> None:
        # 멱등 보존: ON CONFLICT DO UPDATE SET이 norm_id(PK)를 *대입하지 않는다*.
        store, engine = _std_store()
        load_standards(None, _standards_collection([_standard_row()]), store=store)
        sql = _compile(engine.executed[0])
        assert "DO UPDATE SET" in sql
        after_set = sql.split("DO UPDATE SET", 1)[1]
        set_clause = after_set.split("RETURNING", 1)[0]
        assert "norm_id" not in set_clause
        # SET은 official_code·statement 등 나머지 컬럼을 갱신한다.
        assert "official_code" in set_clause
        assert "statement" in set_clause

    def test_official_code_collision_pair_loads_two_rows(self) -> None:
        # official_code 충돌쌍: 같은 code('[10공수1-01-01]')가 2022·2015에 — norm_id가 달라 2행.
        store, engine = _std_store()
        count = load_standards(
            None,
            _standards_collection(
                [
                    _standard_row(_NORM_A, _CODE_AB, curriculum_revision="2022 개정"),
                    _standard_row(_NORM_B, _CODE_AB, curriculum_revision="2015 개정"),
                ]
            ),
            store=store,
        )
        assert count == 2  # 같은 official_code라도 norm_id 다르면 2행(PK 충돌 아님)
        assert len(engine.executed) == 2

    def test_input_dedup_last_wins_on_norm_id(self) -> None:
        # 입력 내 같은 norm_id 중복 → 마지막 우선 dedup(단일 배치 ON CONFLICT 중복행 오류 방지).
        store, engine = _std_store()
        count = load_standards(
            None,
            _standards_collection(
                [
                    _standard_row(_NORM_A, statement="첫 본문"),
                    _standard_row(_NORM_A, statement="둘째 본문"),
                ]
            ),
            store=store,
        )
        assert count == 1  # dedup → 1행
        assert len(engine.executed) == 1
        params = engine.executed[0].compile(dialect=_pg_dialect()).params  # type: ignore[attr-defined]
        assert "둘째 본문" in params.values()  # 마지막 우선

    def test_idempotent_same_statements(self) -> None:
        # 같은 컬렉션 2회 load → 같은 upsert(ON CONFLICT) statement(멱등 — 실 행 1개는 통합).
        store, engine = _std_store()
        collection = _standards_collection([_standard_row()])
        load_standards(None, collection, store=store)
        load_standards(None, collection, store=store)
        inserts = [s for s in engine.executed if "INSERT INTO achievement_standard" in _compile(s)]
        assert len(inserts) == 2
        for stmt in inserts:
            assert "ON CONFLICT" in _compile(stmt)


# ──────────────────────────────────────────────────────────────────────────
# ④ 링크 upsert — src_id→code 해석·ON CONFLICT(의미키)·link_id 미-SET·orphan skip(개념+성취기준)
# ──────────────────────────────────────────────────────────────────────────
class TestLinkUpsert:
    def test_on_conflict_semantic_key(self) -> None:
        store, engine = _link_store()
        load_links(None, _links_collection([_link_row()]), store=store)
        inserts = _link_inserts(engine)
        assert len(inserts) == 1
        sql = _compile(inserts[0])
        assert "ON CONFLICT" in sql
        # 복합 의미키 — concept_code·norm_id·link_type 셋 다.
        assert "concept_code" in sql
        assert "norm_id" in sql
        assert "link_type" in sql

    def test_does_not_set_link_id_on_conflict(self) -> None:
        # 멱등 보존: ON CONFLICT DO UPDATE SET이 link_id(UUID PK)를 *대입하지 않는다*. note만 갱신.
        store, engine = _link_store()
        load_links(None, _links_collection([_link_row(note="근거")]), store=store)
        sql = _compile(_link_inserts(engine)[0])
        assert "DO UPDATE SET" in sql
        after_set = sql.split("DO UPDATE SET", 1)[1]
        set_clause = after_set.split("RETURNING", 1)[0]
        assert "link_id" not in set_clause
        assert "note" in set_clause

    def test_resolves_src_id_via_single_concept_query(self) -> None:
        # P2b: concept_code(src_id)는 *해석한다* — backend `concept`을 단일 조회해 새 code로 매핑.
        # SELECT는 둘(concept.source_id/code 해석 + achievement_standard.norm_id 존재)이고, 개념
        # 해석 조회는 *단 한 번*이다(N+1 0·backend_edge resolve-via-map 미러).
        store, engine = _link_store()
        load_links(
            None,
            _links_collection([_link_row(), _link_row(norm_id=_NORM_B)]),
            store=store,
        )
        concept_selects = [
            s
            for s in engine.executed
            if "concept.source_id" in _compile(s)
            and "concept.code" in _compile(s)
            and "INSERT" not in _compile(s)
        ]
        assert len(concept_selects) == 1  # 개념 해석 조회 단일(N+1 0)

    def test_single_norm_query_no_n_plus_one(self) -> None:
        # 여러 링크여도 norm_id 존재 조회는 *단 한 번*(N+1 0·backend_edge 미러).
        store, engine = _link_store()
        load_links(
            None,
            _links_collection([_link_row(), _link_row(norm_id=_NORM_B)]),
            store=store,
        )
        selects = [
            s
            for s in engine.executed
            if "achievement_standard.norm_id" in _compile(s) and "INSERT" not in _compile(s)
        ]
        assert len(selects) == 1

    def test_orphan_norm_id_skipped(self) -> None:
        # 성취기준 orphan: 실 FK norm_id가 적재 집합에 없으면 그 링크는 FK 위반 방지로 skip.
        store, engine = _link_store()
        loaded = load_links(None, _links_collection([_link_row(norm_id=_NORM_ORPHAN)]), store=store)
        assert loaded == 0
        # 해석·norm_id 조회는 돌되 INSERT는 없다.
        assert _link_inserts(engine) == []

    def test_orphan_unresolved_src_id_skipped(self) -> None:
        # 개념 orphan(P2b): src_id가 `{source_id: code}` 맵에 없으면(개념 미적재) 그 링크는 skip.
        # backend_edge가 맵에 없는 UC를 orphan으로 거른 것의 짝(개념 해석 실패).
        store, engine = _link_store()
        loaded = load_links(
            None,
            _links_collection([_link_row(concept_src_id=_SRC_ID_ORPHAN)]),
            store=store,
        )
        assert loaded == 0
        assert _link_inserts(engine) == []  # 해석 실패 → INSERT 없음

    def test_orphan_skip_reports_message_norm(self) -> None:
        # 조용한 누락 금지 — 성취기준 orphan은 메시지로 보고된다(store.populate 둘째 반환).
        store, _ = _link_store()
        loaded, skipped = store.populate([_link_from_schema(norm_id=_NORM_ORPHAN)])
        assert loaded == 0
        assert any("orphan" in m and "성취기준" in m for m in skipped)

    def test_orphan_skip_reports_message_concept(self) -> None:
        # 조용한 누락 금지 — 개념 해석 실패(맵에 없는 src_id)도 메시지로 보고된다.
        store, _ = _link_store()
        loaded, skipped = store.populate([_link_from_schema(src_id=_SRC_ID_ORPHAN)])
        assert loaded == 0
        assert any("orphan" in m and "개념" in m for m in skipped)

    def test_mixed_orphan_and_valid(self) -> None:
        # 유효 1 + 성취기준 orphan 1 + 개념 orphan 1 → 유효만 적재(둘 다 제외).
        store, engine = _link_store()
        loaded = load_links(
            None,
            _links_collection(
                [
                    _link_row(norm_id=_NORM_A),  # 유효(개념·성취기준 둘 다 해석)
                    _link_row(norm_id=_NORM_ORPHAN),  # 성취기준 orphan
                    _link_row(concept_src_id=_SRC_ID_ORPHAN),  # 개념 orphan
                ]
            ),
            store=store,
        )
        assert loaded == 1

    def test_input_dedup_last_wins_on_resolved_key(self) -> None:
        # 입력 내 같은 (해석된 code, norm_id, link_type) 중복 → 마지막 우선 dedup(해석 후 키 기준).
        store, engine = _link_store()
        loaded = load_links(
            None,
            _links_collection(
                [
                    _link_row(note="첫 근거"),
                    _link_row(note="둘째 근거"),  # 같은 src_id→같은 code·norm·link_type
                ]
            ),
            store=store,
        )
        assert loaded == 1  # dedup → 1행
        assert len(_link_inserts(engine)) == 1

    def test_idempotent_same_statements(self) -> None:
        store, engine = _link_store()
        collection = _links_collection([_link_row()])
        load_links(None, collection, store=store)
        load_links(None, collection, store=store)
        inserts = _link_inserts(engine)
        assert len(inserts) == 2
        for stmt in inserts:
            assert "ON CONFLICT" in _compile(stmt)


def _link_from_schema(
    src_id: str = _SRC_ID,
    norm_id: str = _NORM_A,
    *,
    link_type: Literal["직접", "재매핑", "준용"] = "직접",
    note: str | None = None,
) -> ConceptStandardLink:
    """schema.ConceptStandardLink 헬퍼(store.populate 직접 호출용 — load_links 우회).

    `concept_code` 슬롯엔 *해석 전 src_id*를 넣는다(populate가 `{source_id: code}`로 해석 — 적재기
    계약상 슬롯이 해석 전 lookup 키를 담는다). schema 검증은 src_id 문자열에도 통과(느슨참조).
    """
    return ConceptStandardLink(
        concept_code=src_id,
        norm_id=norm_id,
        link_type=link_type,
        note=note,
    )


# ──────────────────────────────────────────────────────────────────────────
# store 기본 설정 해석 (backend_concept·backend_edge 미러)
# ──────────────────────────────────────────────────────────────────────────
def test_standard_store_uses_default_settings_when_unset() -> None:
    store = AchievementStandardStore()
    assert isinstance(store._resolved_settings, Settings)


def test_link_store_uses_default_settings_when_unset() -> None:
    store = ConceptStandardLinkStore()
    assert isinstance(store._resolved_settings, Settings)


# ──────────────────────────────────────────────────────────────────────────
# 실 대학 성취기준 코퍼스 hermetic 적재 (U3 — PG 불요·가짜 엔진으로 전 경로)
# ──────────────────────────────────────────────────────────────────────────
def test_load_real_university_corpus_via_fake_engine() -> None:
    """실 `standards_university_v1` 코퍼스 409건이 로더 전 경로를 통과(자체작성·대학 code·PG 불요).

    가짜 엔진으로 `load_standards`를 실 코퍼스에 돌려 ① 409건 파싱·schema 검증(code→official_code
    rename·school_type=대학교·`[CALC1-01-01]` 형식) ② 행마다 ON CONFLICT(norm_id) upsert 구성을
    확인한다(실 PG 적재는 통합테스트). 대학은 NCIC 아닌 자체작성이나 *같은 범용 로더*로 적재된다."""
    corpus = (
        Path(__file__).resolve().parents[3]
        / "data"
        / "corpus"
        / "standards_university_v1"
        / "standards.json"
    )
    if not corpus.exists():
        pytest.skip("대학 코퍼스 미존재(U1 산출 필요)")
    store, engine = _std_store()
    count = load_standards(None, corpus, store=store)
    # 대학 성취기준 건수는 단일 원천의 기계용 사본에서 읽는다(OPS-154 — 손 고정 금지).
    facts_path = Path(__file__).resolve().parents[3] / "docs" / "data" / "corpus_facts.json"
    expected = json.loads(facts_path.read_text(encoding="utf-8"))["standards.university"]
    assert count == expected  # 대학 성취기준 전건
    assert len(engine.executed) == expected  # 행마다 upsert statement
    compiled = _compile(engine.executed[0])
    assert "INSERT INTO achievement_standard" in compiled
    assert "ON CONFLICT" in compiled
