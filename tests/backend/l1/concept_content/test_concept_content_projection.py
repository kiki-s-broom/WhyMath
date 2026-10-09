"""콘텐츠 4종 PG 프로젝션 적재 *단위테스트* — Phase 3 Slice 1 (hermetic·PG 불요).

PG 없이 검증 가능한 것만 못 박는다(`test_atom_node_projection.py` 가짜 엔진 패턴 미러):

  ① content.json 로딩 — code 키 + 콘텐츠 4종·설명·standard_codes·flashcards·scope·필수 누락 skip
  ② redaction 단언 — 레코드에 성취기준 본문(core_proposition/description/statement) 슬롯 없음·
     upsert SQL에 미등장(standard_codes 코드만)
  ③ upsert SQL 구성 — ON CONFLICT(code)·review_status='ai_estimated'·콘텐츠 컬럼 포함
  ④ populate — 전 레코드 upsert(횟수=레코드 수)·멱등
  ⑤ CLI — 파일 부재 종료코드 2·성공 시 두 코퍼스 적재(populate monkeypatch로 DB 우회)

가짜 엔진(`_FakeEngine`)은 begin() 컨텍스트 + execute()를 흉내내 실행된 statement를 기록한다.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import TracebackType

import pytest

from whymath_backend.config import Settings
from whymath_backend.db.models.concept_content import (
    CONTENT_REVIEW_STATUS_AI_ESTIMATED,
    CONTENT_SCOPE_K12,
    CONTENT_SCOPE_UNIVERSITY,
)
from whymath_backend.l1.concept_content import populate as populate_cli
from whymath_backend.l1.concept_content.projection import (
    ConceptContentRecord,
    ConceptContentStore,
    load_concept_content_from_json,
    populate_concept_content,
)

_K12_CODE = "N1"
_UNIV_CODE = "CALC1-U1-S1"


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
    """SQLAlchemy sync Engine 최소 흉내 — begin() + 실행 statement 기록."""

    def __init__(self) -> None:
        self.executed: list[object] = []

    def begin(self) -> _FakeConnection:
        return _FakeConnection(self)

    def connect(self) -> _FakeConnection:
        return _FakeConnection(self)


def _fake_store() -> tuple[ConceptContentStore, _FakeEngine]:
    engine = _FakeEngine()
    store = ConceptContentStore(engine=engine)  # type: ignore[arg-type]  # 가짜 엔진(구조만 충족)
    return store, engine


def _compile(statement: object) -> str:
    from sqlalchemy.dialects import postgresql

    return str(statement.compile(dialect=postgresql.dialect()))  # type: ignore[attr-defined]


def _record(code: str = _K12_CODE, *, scope: str = CONTENT_SCOPE_K12) -> ConceptContentRecord:
    return ConceptContentRecord(
        code=code,
        scope=scope,
        name="자연수",
        subject="초등수학",
        unit="수와 연산",
        metaphor="개수를 세는 도구",
        misconception="0을 자연수로 여김",
        formal_definition_internal="자연수의 정의(내부·학생 비노출)",
        accepted_expressions="자연수, 양의 정수",
        explanation="수 세기의 기초",
        standard_codes=("[2수01-01]",),
        flashcards=({"front": "자연수란?", "back": "1,2,3,...", "grade": "A"},),
        review_status=CONTENT_REVIEW_STATUS_AI_ESTIMATED,
    )


def _write_content(tmp_path: Path, content: list[dict[str, object]], *, name: str) -> Path:
    path = tmp_path / name
    path.write_text(
        json.dumps({"scope": "K-12", "content": content}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


# ──────────────────────────────────────────────────────────────────────────
# ① content.json 로딩
# ──────────────────────────────────────────────────────────────────────────
class TestLoadFromJson:
    def test_extracts_content_and_scope(self, tmp_path: Path) -> None:
        path = _write_content(
            tmp_path,
            [
                {
                    "code": _K12_CODE,
                    "name": "자연수",
                    "subject": "초등수학",
                    "unit": "수와 연산",
                    "metaphor": "개수 도구",
                    "misconception": "0 포함 오인",
                    "formal_definition_internal": "정의(내부)",
                    "accepted_expressions": "자연수",
                    "explanation": "기초",
                    "standard_codes": ["[2수01-01]"],
                    "flashcards": [{"front": "Q", "back": "A"}],
                }
            ],
            name="content.json",
        )
        loaded = load_concept_content_from_json(path, scope=CONTENT_SCOPE_K12)
        assert loaded == [
            ConceptContentRecord(
                code=_K12_CODE,
                scope=CONTENT_SCOPE_K12,
                name="자연수",
                subject="초등수학",
                unit="수와 연산",
                metaphor="개수 도구",
                misconception="0 포함 오인",
                formal_definition_internal="정의(내부)",
                accepted_expressions="자연수",
                explanation="기초",
                standard_codes=("[2수01-01]",),
                flashcards=({"front": "Q", "back": "A"},),
                review_status=CONTENT_REVIEW_STATUS_AI_ESTIMATED,
            )
        ]

    def test_load_reads_review_status_from_json(self, tmp_path: Path) -> None:
        path = _write_content(
            tmp_path,
            [
                {
                    "code": _K12_CODE,
                    "name": "자연수",
                    "subject": "초등수학",
                    "review_status": "reviewed",
                }
            ],
            name="content.json",
        )
        loaded = load_concept_content_from_json(path, scope=CONTENT_SCOPE_K12)
        assert len(loaded) == 1
        assert loaded[0].review_status == "reviewed"

    def test_load_defaults_review_status_to_ai_estimated(self, tmp_path: Path) -> None:
        path = _write_content(
            tmp_path,
            [{"code": _K12_CODE, "name": "자연수", "subject": "초등수학"}],
            name="content.json",
        )
        loaded = load_concept_content_from_json(path, scope=CONTENT_SCOPE_K12)
        assert len(loaded) == 1
        assert loaded[0].review_status == CONTENT_REVIEW_STATUS_AI_ESTIMATED

    def test_scope_is_injected_by_caller(self, tmp_path: Path) -> None:
        # 대학 코퍼스는 standard_codes 키가 없다 → () 정규화. scope는 호출자 주입(대학).
        path = _write_content(
            tmp_path,
            [{"code": _UNIV_CODE, "name": "갈루아 군", "subject": "갈루아 이론"}],
            name="content.json",
        )
        loaded = load_concept_content_from_json(path, scope=CONTENT_SCOPE_UNIVERSITY)
        assert len(loaded) == 1
        assert loaded[0].scope == CONTENT_SCOPE_UNIVERSITY
        assert loaded[0].standard_codes == ()
        assert loaded[0].flashcards == ()
        assert loaded[0].review_status == CONTENT_REVIEW_STATUS_AI_ESTIMATED

    def test_standard_codes_non_list_becomes_empty(self, tmp_path: Path) -> None:
        path = _write_content(
            tmp_path,
            [{"code": _K12_CODE, "name": "x", "subject": "초등수학", "standard_codes": "단일"}],
            name="content.json",
        )
        loaded = load_concept_content_from_json(path, scope=CONTENT_SCOPE_K12)
        assert loaded[0].standard_codes == ()

    def test_flashcards_non_list_becomes_empty(self, tmp_path: Path) -> None:
        path = _write_content(
            tmp_path,
            [{"code": _K12_CODE, "name": "x", "subject": "초등수학", "flashcards": "비-list"}],
            name="content.json",
        )
        loaded = load_concept_content_from_json(path, scope=CONTENT_SCOPE_K12)
        assert loaded[0].flashcards == ()

    def test_flashcards_skips_non_dict_items(self, tmp_path: Path) -> None:
        path = _write_content(
            tmp_path,
            [
                {
                    "code": _K12_CODE,
                    "name": "x",
                    "subject": "초등수학",
                    "flashcards": [{"front": "Q", "back": "A"}, "비-dict", 42],
                }
            ],
            name="content.json",
        )
        loaded = load_concept_content_from_json(path, scope=CONTENT_SCOPE_K12)
        assert loaded[0].flashcards == ({"front": "Q", "back": "A"},)

    def test_skips_when_code_missing(self, tmp_path: Path) -> None:
        path = _write_content(
            tmp_path, [{"name": "코드없음", "subject": "초등수학"}], name="content.json"
        )
        assert load_concept_content_from_json(path, scope=CONTENT_SCOPE_K12) == []

    def test_skips_when_name_missing(self, tmp_path: Path) -> None:
        path = _write_content(
            tmp_path, [{"code": _K12_CODE, "subject": "초등수학"}], name="content.json"
        )
        assert load_concept_content_from_json(path, scope=CONTENT_SCOPE_K12) == []

    def test_skips_when_subject_missing(self, tmp_path: Path) -> None:
        path = _write_content(tmp_path, [{"code": _K12_CODE, "name": "x"}], name="content.json")
        assert load_concept_content_from_json(path, scope=CONTENT_SCOPE_K12) == []


# ──────────────────────────────────────────────────────────────────────────
# ② redaction — 성취기준 본문 슬롯 부재 + upsert SQL 미등장
# ──────────────────────────────────────────────────────────────────────────
class TestRedaction:
    # 성취기준 *본문*류(절대 미수록). formal_definition_internal·misconception은 *자체작성 콘텐츠*라
    # 정상 컬럼이므로 여기 넣지 않는다(코퍼스에 본문 부재·standard_codes 코드만 다리).
    REDACTED_FIELDS = ("core_proposition", "description", "statement", "성취기준_본문")

    def test_record_has_no_body_slots(self) -> None:
        fields = set(ConceptContentRecord.__dataclass_fields__)
        for f in self.REDACTED_FIELDS:
            assert f not in fields, f"ConceptContentRecord에 본문 슬롯 누출: {f}"

    def test_record_keeps_only_expected_fields(self) -> None:
        fields = set(ConceptContentRecord.__dataclass_fields__)
        assert fields == {
            "code",
            "scope",
            "name",
            "subject",
            "unit",
            "metaphor",
            "misconception",
            "formal_definition_internal",
            "accepted_expressions",
            "explanation",
            "standard_codes",
            "flashcards",
            "review_status",
        }

    def test_load_ignores_body_fields_if_present(self, tmp_path: Path) -> None:
        # content.json이 오염되어 본문류가 들어와도 레코드에 유입되지 않음을 못 박는다.
        path = _write_content(
            tmp_path,
            [
                {
                    "code": _K12_CODE,
                    "name": "자연수",
                    "subject": "초등수학",
                    "core_proposition": "핵심명제(절대 적재 금지)",
                    "description": "본문 근접(절대 금지)",
                    "statement": "성취기준 본문(절대 금지)",
                }
            ],
            name="content.json",
        )
        loaded = load_concept_content_from_json(path, scope=CONTENT_SCOPE_K12)
        assert len(loaded) == 1
        assert loaded[0].name == "자연수"  # 안전 필드만

    def test_upsert_sql_omits_body_fields(self) -> None:
        store, engine = _fake_store()
        store.upsert(_record())
        compiled = _compile(engine.executed[0])
        for f in self.REDACTED_FIELDS:
            assert f not in compiled, f"upsert SQL에 본문 필드 누출: {f}"


# ──────────────────────────────────────────────────────────────────────────
# ③ upsert SQL 구성 — ON CONFLICT(code)·review_status='ai_estimated'·콘텐츠 컬럼
# ──────────────────────────────────────────────────────────────────────────
class TestUpsertStatement:
    def test_upsert_executes_one_statement_with_on_conflict(self) -> None:
        store, engine = _fake_store()
        store.upsert(_record())
        assert len(engine.executed) == 1
        compiled = _compile(engine.executed[0])
        assert "INSERT INTO concept_content" in compiled
        assert "ON CONFLICT" in compiled

    def test_upsert_targets_code_pk(self) -> None:
        store, engine = _fake_store()
        store.upsert(_record())
        compiled = _compile(engine.executed[0])
        assert "concept_content.code" in compiled or "(code)" in compiled

    def test_upsert_includes_content_columns(self) -> None:
        store, engine = _fake_store()
        store.upsert(_record())
        compiled = _compile(engine.executed[0])
        for col in (
            "scope",
            "name",
            "subject",
            "unit",
            "metaphor",
            "misconception",
            "formal_definition_internal",
            "accepted_expressions",
            "explanation",
            "standard_codes",
            "flashcards",
            "review_status",
        ):
            assert col in compiled, f"upsert SQL에 콘텐츠 컬럼 누락: {col}"

    def test_upsert_binds_review_status_from_record(self) -> None:
        from sqlalchemy.dialects import postgresql

        reviewed_record = ConceptContentRecord(
            code=_K12_CODE,
            scope=CONTENT_SCOPE_K12,
            name="자연수",
            subject="초등수학",
            unit=None,
            metaphor=None,
            misconception=None,
            formal_definition_internal=None,
            accepted_expressions=None,
            explanation=None,
            standard_codes=(),
            flashcards=(),
            review_status="reviewed",
        )
        store, engine = _fake_store()
        store.upsert(reviewed_record)
        compiled = engine.executed[0].compile(  # type: ignore[attr-defined]
            dialect=postgresql.dialect()
        )
        assert "reviewed" in compiled.params.values()


# ──────────────────────────────────────────────────────────────────────────
# ④ populate — 전 레코드 upsert·멱등
# ──────────────────────────────────────────────────────────────────────────
class TestPopulate:
    def test_populate_upserts_each_record(self) -> None:
        store, engine = _fake_store()
        records = [_record(_K12_CODE), _record(_UNIV_CODE, scope=CONTENT_SCOPE_UNIVERSITY)]
        count = populate_concept_content(records, store=store)
        assert count == 2
        assert len(engine.executed) == 2

    def test_populate_empty_is_noop(self) -> None:
        store, engine = _fake_store()
        assert populate_concept_content([], store=store) == 0
        assert engine.executed == []

    def test_populate_idempotent_same_statements(self) -> None:
        store, engine = _fake_store()
        records = [_record(_K12_CODE)]
        populate_concept_content(records, store=store)
        populate_concept_content(records, store=store)
        assert len(engine.executed) == 2
        for stmt in engine.executed:
            assert "ON CONFLICT" in _compile(stmt)


def test_store_uses_default_settings_when_unset() -> None:
    store = ConceptContentStore()
    assert isinstance(store._resolved_settings, Settings)


# ──────────────────────────────────────────────────────────────────────────
# ⑤ CLI — 파일 부재 종료코드 2·성공 시 두 코퍼스 적재(DB 우회)
# ──────────────────────────────────────────────────────────────────────────
class TestCli:
    def test_missing_file_returns_2(self, tmp_path: Path) -> None:
        rc = populate_cli.main(
            ["--k12", str(tmp_path / "nope.json"), "--university", str(tmp_path / "x.json")]
        )
        assert rc == 2

    def test_success_populates_both(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        k12 = _write_content(
            tmp_path,
            [{"code": _K12_CODE, "name": "자연수", "subject": "초등수학"}],
            name="k12.json",
        )
        univ = _write_content(
            tmp_path,
            [{"code": _UNIV_CODE, "name": "갈루아 군", "subject": "갈루아 이론"}],
            name="univ.json",
        )
        seen: list[tuple[str, int]] = []

        def _fake_populate(records: object, **_cms: object) -> int:  # type: ignore[override]
            recs = list(records)  # type: ignore[arg-type]
            seen.append((recs[0].scope, len(recs)))
            return len(recs)

        # DB 우회 — populate를 가짜로 교체(load는 실 tmp 파일로 동작).
        monkeypatch.setattr(populate_cli, "populate_concept_content", _fake_populate)
        rc = populate_cli.main(["--k12", str(k12), "--university", str(univ)])
        assert rc == 0
        assert (CONTENT_SCOPE_K12, 1) in seen
        assert (CONTENT_SCOPE_UNIVERSITY, 1) in seen
