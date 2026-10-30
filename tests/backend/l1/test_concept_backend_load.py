"""개념그래프 → backend `Concept` 런타임 적재 *단위테스트* — 브리지 슬1 (hermetic·PG 불요).

CI hermetic 잡엔 PostgreSQL이 없으므로 `BackendConceptStore`/`populate_backend_concepts`의 *실
라운드트립*은 통합테스트(`test_concept_backend_load_integration.py`·실 PG 게이트)로 미룬다. 여기서는
PG 없이 검증 가능한 것만 못 박는다(슬117 `test_concept_node_projection.py` 가짜 엔진 패턴 재사용):

  ① graph.json 로딩 — concept_id→code 브리지·source_id·aliases·필드 유도·redaction 키 미유입·
     name_ko 누락 graceful
  ② 필드 유도 — difficulty 스케일·misconception 변환·level 고정(subject 매핑은 제거됨·Overlay 이관)
  ③ upsert SQL 구성 — ON CONFLICT(code) upsert·source_id/aliases 컬럼 수록·**본문 3컬럼
     (description/formal_definition/intuitive_explanation) 0**·PK(concept_id) 미-SET(UUID 보존)
  ④ populate — 전 레코드 upsert(횟수=레코드 수)·멱등(같은 레코드 2회→같은 upsert statement)

P2b 재ID(2026-06-16): concept_id가 UC.* → `{TRACK}-{AREA}-{NNN}`(예 'HIGH-CALC-001')로 전환됐고,
각 개념이 `source_id`(원천 src_id)·`aliases`([레거시 UC, src_id])를 갖는다. 이 테스트는 새 형식
id를 쓰며(적재기는 형식 불문이라 옛 UC도 흘렀겠지만 정본은 새 형식), source_id/aliases 적재를 못
박는다. 가짜 엔진(`_FakeEngine`)은 begin() 컨텍스트 + execute()를 흉내내 실행된 statement를
기록한다 — psycopg/PG 없이 배선·redaction·멱등 키를 검증한다.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import TracebackType

import pytest

from whymath_backend.config import Settings
from whymath_backend.l1.concept_graph.backend_concept import (
    BackendConceptRecord,
    BackendConceptStore,
    load_backend_concepts_from_graph_json,
    populate_backend_concepts,
    scale_difficulty,
)
from whymath_backend.schema.enums import ConceptLevel

# 재ID 후 concept_id 규약 키 예시(`{TRACK}-{AREA}-{NNN}`·Neo4j·concept_embedding·concept_node와
# 동일 키 공간). 적재기는 *형식 불문*이라 옛 UC도 같은 경로지만 정본은 새 형식을 쓴다.
_NID_A = "HIGH-CALC-001"
_NID_B = "HIGH-ALG-002"


# ──────────────────────────────────────────────────────────────────────────
# 가짜 sync 엔진 — begin() 컨텍스트 + execute() (PG 없이 배선 관찰)
# ──────────────────────────────────────────────────────────────────────────
def _compile(statement: object) -> str:
    from sqlalchemy.dialects import postgresql

    return str(statement.compile(dialect=postgresql.dialect()))  # type: ignore[attr-defined]


class _Written:
    """`INSERT … ON CONFLICT … RETURNING` 결과 흉내 — 1행이면 '적재됨', None이면 '건너뜀'(P3-26 가드)."""

    def __init__(self, written: bool = True) -> None:
        self._written = written

    def first(self) -> object | None:
        return ("written",) if self._written else None


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

    def execute(self, statement: object) -> _Written:
        self._engine.executed.append(statement)
        return _Written(self._engine.insert_written)


class _FakeEngine:
    """SQLAlchemy sync Engine 최소 흉내 — begin() + 실행 statement 기록(upsert는 결과 미사용)."""

    def __init__(self) -> None:
        self.executed: list[object] = []
        self.insert_written = True

    def begin(self) -> _FakeConnection:
        return _FakeConnection(self)


def _fake_store() -> tuple[BackendConceptStore, _FakeEngine]:
    """가짜 엔진을 주입한 BackendConceptStore + 엔진(검사용) 페어."""
    engine = _FakeEngine()
    store = BackendConceptStore(engine=engine)  # type: ignore[arg-type]  # 가짜 엔진(구조만 충족)
    return store, engine


def _compile(statement: object) -> str:
    """SQLAlchemy statement를 PostgreSQL dialect로 컴파일한 SQL 문자열(검사용·슬117 패턴)."""
    from sqlalchemy.dialects import postgresql

    return str(statement.compile(dialect=postgresql.dialect()))  # type: ignore[attr-defined]


def _record(
    code: str = _NID_A,
    *,
    name_ko: str = "극한",
    source_id: str | None = "N1",
    aliases: list[str] | None = None,
    intrinsic_difficulty: float | None = 2.17,
    behavior_skills: list[str] | None = None,
) -> BackendConceptRecord:
    return BackendConceptRecord(
        code=code,
        name_ko=name_ko,
        # 재ID 추적성(2026-06-16) — 원천 src_id + 옛 키 별칭([레거시 UC, src_id]).
        source_id=source_id,
        aliases=(aliases if aliases is not None else ["UC.calc.alimit.epsilon-delta", "N1"]),
        level=ConceptLevel.세부개념,
        intrinsic_difficulty=intrinsic_difficulty,
        # concept→skill 브리지(Phase 2b-2·부재 시 빈 배열).
        behavior_skills=(behavior_skills if behavior_skills is not None else ["skill.compute"]),
    )


# ──────────────────────────────────────────────────────────────────────────
# ① graph.json 로딩 — concept_id→code 브리지·source_id·aliases·유도·redaction·graceful
# ──────────────────────────────────────────────────────────────────────────
class TestLoadFromGraphJson:
    def _write_graph(self, tmp_path: Path, concepts: list[dict[str, object]]) -> Path:
        path = tmp_path / "graph.json"
        path.write_text(
            json.dumps({"concepts": concepts, "edges": []}, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def test_concept_id_becomes_code_bridge(self, tmp_path: Path) -> None:
        # 핵심 브리지: graph concept_id(재ID 새 형식)가 backend Concept.code가 된다.
        path = self._write_graph(
            tmp_path,
            [
                {
                    "concept_id": _NID_A,
                    "source_id": "N1",
                    "aliases": ["UC.calc.alimit.epsilon-delta", "N1"],
                    "name_ko": "극한",
                    "domain": "[고]미적분",
                    "difficulty_tier": 7,
                    # 오염 방어: 옛 graph.json이 misconception_text를 남겨도 노드로 흡수하지 않는다.
                    "misconception_text": "극한을 대입값으로 혼동",
                    "review_status": "reviewed",
                }
            ],
        )
        loaded = load_backend_concepts_from_graph_json(path)
        assert len(loaded) == 1
        rec = loaded[0]
        assert rec.code == _NID_A  # concept_id = code(브리지 키·형식 불문 통과)
        assert rec.source_id == "N1"  # 재ID 추적성(원천 src_id)
        assert rec.aliases == ["UC.calc.alimit.epsilon-delta", "N1"]  # 옛 키 별칭 보존
        assert rec.name_ko == "극한"
        assert rec.level == ConceptLevel.세부개념  # 고정 유도(NOT NULL 충족)
        assert rec.intrinsic_difficulty == scale_difficulty(7)
        assert rec.behavior_skills == []  # graph 부재 시 빈 배열(graceful·이 항목 미탑재)
        # Part 2 §3(순수성): graph의 misconception_text는 노드로 흡수되지 않는다 — 오개념 컬럼은
        # Phase 1b로 레코드·ORM에서 아예 제거됐다(redaction 청산).
        assert not hasattr(rec, "common_misconceptions")

    def test_behavior_skills_loaded_when_present(self, tmp_path: Path) -> None:
        # concept→skill 브리지(Phase 2b-2): graph.json behavior_skills가 레코드로 직결된다.
        path = self._write_graph(
            tmp_path,
            [
                {
                    "concept_id": _NID_A,
                    "name_ko": "극한",
                    "domain": "[고]미적분",
                    "behavior_skills": ["skill.compute-limit", "skill.reasonableness-check"],
                }
            ],
        )
        rec = load_backend_concepts_from_graph_json(path)[0]
        assert rec.behavior_skills == ["skill.compute-limit", "skill.reasonableness-check"]

    def test_source_id_and_aliases_absent_graceful(self, tmp_path: Path) -> None:
        # 옛 graph.json(재ID 전·source_id/aliases 부재) → None/빈 배열 graceful(하위호환·NOT NULL
        # 정합). 적재기가 형식 불문이라 옛 데이터도 깨지지 않고 흐른다.
        path = self._write_graph(
            tmp_path,
            [{"concept_id": _NID_A, "name_ko": "극한", "domain": "[고]미적분"}],
        )
        rec = load_backend_concepts_from_graph_json(path)[0]
        assert rec.source_id is None  # 부재 → None
        assert rec.aliases == []  # 부재 → 빈 배열(NOT NULL 컬럼 정합)

    def test_aliases_blank_entries_filtered(self, tmp_path: Path) -> None:
        # 방어: 빈/공백 별칭 원소는 걸러진다(data-pipeline _validate_aliases가 금지하나 이중 방어).
        path = self._write_graph(
            tmp_path,
            [
                {
                    "concept_id": _NID_A,
                    "name_ko": "극한",
                    "domain": "[고]미적분",
                    "aliases": ["UC.x.y.z", "  ", "", "N1"],
                }
            ],
        )
        rec = load_backend_concepts_from_graph_json(path)[0]
        assert rec.aliases == ["UC.x.y.z", "N1"]  # 빈 원소 제외

    def test_description_and_formal_definition_never_loaded(self, tmp_path: Path) -> None:
        # redaction: graph 부재이나 *오염되어 들어와도* 레코드에 유입되지 않음을 못 박는다.
        path = self._write_graph(
            tmp_path,
            [
                {
                    "concept_id": _NID_A,
                    "name_ko": "극한",
                    "domain": "[고]미적분",
                    "description": "교과서 본문 근접 서술(절대 적재 금지)",
                    "formal_definition": "∀ε>0 ∃δ>0 ... (절대 적재 금지)",
                    "intuitive_explanation": "검수 책임 직관 설명(절대 적재 금지)",
                }
            ],
        )
        loaded = load_backend_concepts_from_graph_json(path)
        assert len(loaded) == 1
        # BackendConceptRecord에 본문 3슬롯·오개념 슬롯이 *없다*(구조적 차단·Phase 1b 청산).
        fields = set(BackendConceptRecord.__dataclass_fields__)
        assert "description" not in fields
        assert "formal_definition" not in fields
        assert "intuitive_explanation" not in fields
        assert "common_misconceptions" not in fields

    def test_loads_all_concepts_regardless_of_review_status(self, tmp_path: Path) -> None:
        # 전량 적재(review_status 무관·게이팅은 조회 몫·슬2/3/117 동형).
        path = self._write_graph(
            tmp_path,
            [
                {
                    "concept_id": _NID_A,
                    "name_ko": "첫째",
                    "domain": "d",
                    "review_status": "reviewed",
                },
                {
                    "concept_id": _NID_B,
                    "name_ko": "둘째",
                    "domain": "d",
                    "review_status": "pending",
                },
            ],
        )
        loaded = load_backend_concepts_from_graph_json(path)
        assert [c.code for c in loaded] == [_NID_A, _NID_B]

    def test_optional_fields_default_when_absent(self, tmp_path: Path) -> None:
        # difficulty_tier 부재 → None(날조 0). 오개념 컬럼은 Phase 1b로 레코드에서 제거됨.
        path = self._write_graph(
            tmp_path,
            [{"concept_id": _NID_A, "name_ko": "유효", "domain": "[중]수와 연산"}],
        )
        rec = load_backend_concepts_from_graph_json(path)[0]
        assert rec.intrinsic_difficulty is None  # difficulty_tier 부재
        assert not hasattr(rec, "common_misconceptions")  # Phase 1b 제거

    def test_skips_when_name_ko_missing(self, tmp_path: Path) -> None:
        # name_ko 누락(오염) → 건너뜀(NOT NULL 위반 방지·조용한 빈 적재 금지).
        path = self._write_graph(tmp_path, [{"concept_id": _NID_A, "domain": "d"}])
        assert load_backend_concepts_from_graph_json(path) == []

    def test_skips_when_name_ko_blank(self, tmp_path: Path) -> None:
        path = self._write_graph(
            tmp_path, [{"concept_id": _NID_A, "name_ko": "   ", "domain": "d"}]
        )
        assert load_backend_concepts_from_graph_json(path) == []

    def test_missing_concept_id_raises(self, tmp_path: Path) -> None:
        path = self._write_graph(tmp_path, [{"name_ko": "키 없음", "domain": "d"}])
        with pytest.raises(ValueError, match="concept_id"):
            load_backend_concepts_from_graph_json(path)


# ──────────────────────────────────────────────────────────────────────────
# ② 필드 유도 — difficulty 스케일·misconception·level 고정
#   (subject 매핑은 제거됨 — 교육과정 완전 Overlay 이관·rev f3a4b5c6d7e8)
# ──────────────────────────────────────────────────────────────────────────
class TestDifficultyScale:
    def test_linear_scale_endpoints_and_mid(self) -> None:
        # tier[0,24] → intrinsic[1,5] 선형(schema ge=1 le=5·Numeric(3,2) 정합).
        assert scale_difficulty(0) == 1.0
        assert scale_difficulty(12) == 3.0
        assert scale_difficulty(24) == 5.0

    def test_none_passthrough(self) -> None:
        assert scale_difficulty(None) is None

    def test_out_of_range_clamped(self) -> None:
        # 방어: 범위 밖도 [1,5]로 clamp(schema 제약 위반 방지).
        assert scale_difficulty(-5) == 1.0
        assert scale_difficulty(100) == 5.0


# ──────────────────────────────────────────────────────────────────────────
# ③ upsert SQL 구성 — ON CONFLICT(code)·redaction·PK 미-SET(UUID 보존)
# ──────────────────────────────────────────────────────────────────────────
class TestUpsertStatement:
    def test_upsert_executes_one_statement_with_on_conflict_code(self) -> None:
        store, engine = _fake_store()
        store.upsert(_record())
        assert len(engine.executed) == 1
        compiled = _compile(engine.executed[0])
        assert "INSERT INTO concept" in compiled
        assert "ON CONFLICT" in compiled
        # 브리지 키: 충돌 키가 code(UNIQUE)다(UUID PK가 아니라 — UC↔UUID 브리지).
        assert "(code)" in compiled or "concept.code" in compiled

    def test_upsert_omits_redacted_body_columns(self) -> None:
        # redaction: INSERT/SET 컬럼에 본문 3개·오개념 컬럼이 *없다*(Phase 1b로 컬럼 자체 제거).
        store, engine = _fake_store()
        store.upsert(_record())
        compiled = _compile(engine.executed[0])
        assert "description" not in compiled
        assert "formal_definition" not in compiled
        assert "intuitive_explanation" not in compiled
        assert "common_misconceptions" not in compiled

    def test_upsert_does_not_set_pk_or_created_at_on_conflict(self) -> None:
        # UUID 보존: ON CONFLICT DO UPDATE SET이 concept_id(PK)·created_at을 *대입하지 않아야*
        # 한다(재적재가 기존 UUID·생성시각을 덮어쓰지 않음 — L2 mastery·problem_concept FK 안정성).
        store, engine = _fake_store()
        store.upsert(_record())
        compiled = _compile(engine.executed[0])
        assert "DO UPDATE SET" in compiled
        # SET 절만 분리(뒤따르는 RETURNING concept.concept_id는 PK 대입이 아니라 신규행 PK 회신).
        after_set = compiled.split("DO UPDATE SET", 1)[1]
        set_clause = after_set.split("RETURNING", 1)[0]
        # SET이 PK·created_at을 대입하지 않음(excluded.concept_id/created_at 부재 = 보존).
        assert "concept_id" not in set_clause
        assert "created_at" not in set_clause
        assert "excluded.concept_id" not in compiled  # 어디서도 PK를 excluded로 덮지 않음

    def test_upsert_includes_runtime_identity_columns(self) -> None:
        store, engine = _fake_store()
        store.upsert(_record())
        compiled = _compile(engine.executed[0])
        # 재ID 추적성(source_id·aliases)·concept→skill 브리지(behavior_skills)도 포함된다.
        for col in (
            "code",
            "name_ko",
            "source_id",
            "aliases",
            "level",
            "intrinsic_difficulty",
            "behavior_skills",
        ):
            assert col in compiled

    def test_upsert_sets_source_id_and_aliases_on_conflict(self) -> None:
        # 재적재 갱신: ON CONFLICT DO UPDATE SET이 source_id·aliases를 excluded로 갱신한다
        # (재ID 추적성이 재적재로 최신화 — PK·본문은 여전히 보존).
        store, engine = _fake_store()
        store.upsert(_record())
        compiled = _compile(engine.executed[0])
        after_set = compiled.split("DO UPDATE SET", 1)[1]
        set_clause = after_set.split("RETURNING", 1)[0]
        assert "source_id" in set_clause
        assert "aliases" in set_clause

    def test_upsert_handles_null_source_id_without_error(self) -> None:
        # source_id None(옛 데이터·재ID 전)도 안전 — upsert가 예외 없이 statement를 만든다.
        store, engine = _fake_store()
        store.upsert(_record(source_id=None, aliases=[]))
        assert len(engine.executed) == 1
        compiled = _compile(engine.executed[0])
        assert "source_id" in compiled  # 컬럼은 여전히 upsert(값만 NULL)
        assert "aliases" in compiled


# ──────────────────────────────────────────────────────────────────────────
# ④ populate — 전 레코드 upsert·멱등
# ──────────────────────────────────────────────────────────────────────────
class TestCmsOwnership:
    """P3-26 — CMS가 만든 개념(`cms_edited_at` 있음)은 같은 코드의 파일 레코드가 덮지 못한다."""

    def test_the_upsert_is_guarded_and_overwrite_releases_the_marker(self) -> None:
        store, engine = _fake_store()
        store.upsert(_record())
        sql = _compile(engine.executed[0])
        assert "cms_edited_at IS NULL" in sql
        store2, engine2 = _fake_store()
        store2.upsert(_record(), overwrite_cms_edits=True)
        sql2 = _compile(engine2.executed[0])
        assert "cms_edited_at IS NULL" not in sql2
        assert "cms_edited_at" in sql2.split("DO UPDATE SET", 1)[1]

    def test_a_skipped_row_is_reported_and_not_counted(self) -> None:
        store, engine = _fake_store()
        engine.insert_written = False
        conflicts: list[str] = []
        count = populate_backend_concepts([_record(_NID_A)], store=store, conflicts=conflicts)
        assert count == 0 and conflicts == [f"concept:{_NID_A}"]

    def test_a_written_row_is_not_a_conflict(self) -> None:
        store, _ = _fake_store()
        conflicts: list[str] = []
        assert populate_backend_concepts([_record(_NID_A)], store=store, conflicts=conflicts) == 1
        assert conflicts == []


class TestPopulate:
    def test_populate_upserts_each_record(self) -> None:
        store, engine = _fake_store()
        count = populate_backend_concepts([_record(_NID_A), _record(_NID_B)], store=store)
        assert count == 2
        assert len(engine.executed) == 2  # 레코드당 1 upsert

    def test_populate_empty_is_noop(self) -> None:
        store, engine = _fake_store()
        assert populate_backend_concepts([], store=store) == 0
        assert engine.executed == []

    def test_populate_idempotent_same_statements(self) -> None:
        # 같은 레코드 2회 populate → 같은 upsert(ON CONFLICT) statement(멱등 — 실 행 1개는 통합).
        store, engine = _fake_store()
        records = [_record(_NID_A)]
        populate_backend_concepts(records, store=store)
        populate_backend_concepts(records, store=store)
        assert len(engine.executed) == 2
        for stmt in engine.executed:
            assert "ON CONFLICT" in _compile(stmt)


def test_record_has_no_body_slots() -> None:
    # 노출 계약: 적재 레코드는 본문 3슬롯·오개념 슬롯을 갖지 않는다(구조적 redaction·Phase 1b).
    fields = set(BackendConceptRecord.__dataclass_fields__)
    assert "description" not in fields
    assert "formal_definition" not in fields
    assert "intuitive_explanation" not in fields
    assert "common_misconceptions" not in fields
    # 런타임 식별 필드 + 재ID 추적성(source_id·aliases)은 보유.
    assert {
        "code",
        "name_ko",
        "source_id",
        "aliases",
        "level",
        "intrinsic_difficulty",
    } <= fields


def test_store_uses_default_settings_when_unset() -> None:
    # store에 settings·engine 미주입이면 전역 Settings를 지연 해석한다(엔진 생성은 첫 upsert에서).
    store = BackendConceptStore()
    assert isinstance(store._resolved_settings, Settings)
