"""교육과정 Overlay 적재 *단위테스트* — graph.json → curriculum_entry KR 셀 (hermetic·PG 불요).

CI hermetic 잡엔 PostgreSQL이 없으므로 `CurriculumEntryStore`/`populate_kr_curriculum_entries`의
*실 라운드트립*은 통합테스트(`test_curriculum_entry_loader_integration.py`·실 PG 게이트)로 미룬다.
여기서는 PG 없이 검증 가능한 것만 못 박는다(backend_concept `test_concept_backend_load.py` 가짜
엔진 패턴 재사용):

  ① graph.json 로딩 — concept_id→KR 셀 매핑(domain→domain_label·grade_band_hint→grade_band/
     introduced_grade·standard_codes→national_standard_codes·review_status→confidence)·KR 상수·
     entry_id 형식·concept_id 누락 graceful skip
  ② upsert SQL 구성 — ON CONFLICT(entry_id) upsert·created_at는 SET에서 제외(보존)·updated_at은
     SET에 포함(갱신)
  ③ populate — 전 셀 upsert(횟수=dedup 후 수)·입력 내 entry_id 중복 dedup
  ④ 원자 축 유도(S2-07) — 크로스워크 전파(atom_codes 전체·최심 승계·사전순 tie-break)·미매핑
     원자 행 0·canonical 존치·결정론·실 코퍼스 원자 행 수 하한 동결(드리프트 감지)
  ⑤ 대학 원자 직접 유도(W0 — S-1) — atom_graph_v1 대학 원자(school_level="대학") grade_band
     ("1학년".."4학년")→introduced_grade(13~16)·required_depth(mastery 천장) 매핑·미상 라벨/
     None grade_band 조용히 건너뜀(날조 금지)·결정론·실 코퍼스 하한 동결
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType

from whymath_backend.l1.concept_atom_crosswalk.transfer import (
    CrosswalkRecord,
    load_crosswalk_records,
)
from whymath_backend.l1.curriculum.curriculum_loader import (
    CurriculumEntryStore,
    derive_atom_curriculum_entries,
    load_kr_curriculum_entries_for_university_atoms,
    load_kr_curriculum_entries_from_graph_json,
    load_kr_curriculum_entries_with_atoms,
    populate_kr_curriculum_entries,
)

# 결정적 created_at/updated_at(테스트 주입 — schema required datetime).
_NOW = datetime(2026, 6, 30, 12, 0, 0, tzinfo=timezone.utc)


# ──────────────────────────────────────────────────────────────────────────
# 가짜 sync 엔진 — begin() 컨텍스트 + execute() (PG 없이 배선 관찰·backend_concept 미러)
# ──────────────────────────────────────────────────────────────────────────
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

    def execute(self, statement: object) -> None:
        self._engine.executed.append(statement)


class _FakeEngine:
    """SQLAlchemy sync Engine 최소 흉내 — begin() + 실행 statement 기록(upsert는 결과 미사용)."""

    def __init__(self) -> None:
        self.executed: list[object] = []

    def begin(self) -> _FakeConnection:
        return _FakeConnection(self)


def _fake_store() -> tuple[CurriculumEntryStore, _FakeEngine]:
    """가짜 엔진을 주입한 CurriculumEntryStore + 엔진(검사용) 페어."""
    engine = _FakeEngine()
    store = CurriculumEntryStore(engine=engine)  # type: ignore[arg-type]  # 가짜 엔진(구조만 충족)
    return store, engine


def _compile(statement: object) -> str:
    """SQLAlchemy statement를 PostgreSQL dialect로 컴파일한 SQL 문자열(검사용)."""
    from sqlalchemy.dialects import postgresql

    return str(statement.compile(dialect=postgresql.dialect()))  # type: ignore[attr-defined]


# ──────────────────────────────────────────────────────────────────────────
# ① graph.json 로딩 — concept_id→KR 셀 매핑·KR 상수·graceful skip
# ──────────────────────────────────────────────────────────────────────────
class TestLoadFromGraphJson:
    def _write_graph(self, tmp_path: Path, concepts: list[dict[str, object]]) -> Path:
        path = tmp_path / "graph.json"
        path.write_text(
            json.dumps({"concepts": concepts, "edges": []}, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def test_maps_kr_fields_and_constants(self, tmp_path: Path) -> None:
        path = self._write_graph(
            tmp_path,
            [
                {
                    "concept_id": "HIGH-CALC-001",
                    "name_ko": "극한",
                    "domain": "극한과 연속",
                    "grade_band_hint": "고등학교",
                    "standard_codes": ["[12미적01-01]"],
                    "prerequisite_concept_ids": ["HIGH-CALC-000"],
                    "review_status": "reviewed",
                }
            ],
        )
        entries = load_kr_curriculum_entries_from_graph_json(path, now=_NOW)
        assert len(entries) == 1
        e = entries[0]
        # 식별 — 복합키 3-튜플 + 결정적 entry_id(수학 셀 무접미 불변 — S1 entry_id 규약)
        assert e.concept_id == "HIGH-CALC-001"
        assert e.country_code == "KR"
        assert e.subject == "수학"  # 이 로더는 KR 수학 셀만 적재(S1 subject 축)
        assert e.entry_id == "HIGH-CALC-001:KR"
        # 매핑
        assert e.domain_label == "극한과 연속"
        assert e.grade_band == "고등학교"
        assert e.introduced_grade == 10  # 고등학교 = KR 1~12 번호 하한 10
        assert e.national_standard_codes == ["[12미적01-01]"]
        assert e.prerequisite_concept_ids == ["HIGH-CALC-000"]
        assert e.confidence == 0.9  # reviewed
        # KR 상수
        assert e.license_id == "KR-NCIC"  # use_enum_values → 하이픈 값
        assert e.curriculum_revision == "2022 개정"
        assert e.is_present is True
        assert e.source_url and e.source_url.startswith("https://www.ncic.go.kr")
        assert e.created_at == _NOW
        assert e.updated_at == _NOW
        # 깊이 — grade_band 학년진행 휴리스틱(고등학교 → mastery·use_enum_values 문자열)
        assert e.required_depth == "mastery"
        # 미매핑(소스에 신호 없음 → 기본/None)
        assert e.is_assessed is None

    def test_introduced_grade_band_lower_bounds(self, tmp_path: Path) -> None:
        bands = {
            "초등학교 1~2학년군": 1,
            "초등학교 3~4학년군": 3,
            "초등학교 5~6학년군": 5,
            "중학교 1~3학년군": 7,
            "고등학교": 10,
        }
        concepts = [
            {
                "concept_id": f"C-{i}",
                "name_ko": "x",
                "domain": "d",
                "grade_band_hint": band,
                "standard_codes": [],
                "review_status": "pending",
            }
            for i, band in enumerate(bands)
        ]
        # grade_band 학년진행 → required_depth 휴리스틱(use_enum_values 문자열).
        expected_depth = {
            "초등학교 1~2학년군": "awareness",
            "초등학교 3~4학년군": "procedural",
            "초등학교 5~6학년군": "procedural",
            "중학교 1~3학년군": "conceptual",
            "고등학교": "mastery",
        }
        path = self._write_graph(tmp_path, concepts)  # type: ignore[arg-type]
        loaded = load_kr_curriculum_entries_from_graph_json(path, now=_NOW)
        by_code = {e.concept_id: e for e in loaded}
        for i, (band, grade) in enumerate(bands.items()):
            assert by_code[f"C-{i}"].introduced_grade == grade
            assert by_code[f"C-{i}"].grade_band == band
            assert by_code[f"C-{i}"].required_depth == expected_depth[band]

    def test_unknown_grade_band_introduced_grade_none(self, tmp_path: Path) -> None:
        # 매핑에 없는 밴드 → introduced_grade None(추정 안 함·정직). grade_band는 원문 보존.
        path = self._write_graph(
            tmp_path,
            [
                {
                    "concept_id": "C1",
                    "name_ko": "x",
                    "domain": "d",
                    "grade_band_hint": "대학교",
                    "standard_codes": [],
                    "review_status": "reviewed",
                }
            ],
        )
        e = load_kr_curriculum_entries_from_graph_json(path, now=_NOW)[0]
        assert e.grade_band == "대학교"
        assert e.introduced_grade is None
        assert e.required_depth is None  # 미지 밴드 → 깊이 휴리스틱도 None(정직 폴백)

    def test_pending_review_lower_confidence(self, tmp_path: Path) -> None:
        path = self._write_graph(
            tmp_path,
            [
                {
                    "concept_id": "C1",
                    "name_ko": "x",
                    "domain": "d",
                    "grade_band_hint": "고등학교",
                    "standard_codes": [],
                    "review_status": "pending",
                }
            ],
        )
        e = load_kr_curriculum_entries_from_graph_json(path, now=_NOW)[0]
        assert e.confidence == 0.6  # 비-reviewed → 보수적

    def test_skips_when_concept_id_missing(self, tmp_path: Path) -> None:
        # concept_id 누락 → 건너뜀(복합키 구성 불가·조용한 빈 적재 금지).
        path = self._write_graph(
            tmp_path,
            [{"name_ko": "키 없음", "domain": "d", "grade_band_hint": "고등학교"}],
        )
        assert load_kr_curriculum_entries_from_graph_json(path, now=_NOW) == []

    def test_all_loaded_cells_subject_math_entry_id_unsuffixed(self, tmp_path: Path) -> None:
        """KR 적재 셀 *전부* subject=='수학' + entry_id 무접미 `{concept_id}:KR`(S1 규약).

        수학 셀 entry_id는 기존 형식 불변(데이터 churn 0) — `:{subject}` 접미는 비수학 셀만
        (미래 규약·이 로더 미해당). Phase 1 '수학' 외 subject 산출물 금지 범위 가드의 로더 측
        동결이다.
        """
        concepts = [
            {
                "concept_id": f"HIGH-CALC-{i:03d}",
                "name_ko": "x",
                "domain": "d",
                "grade_band_hint": "고등학교",
                "standard_codes": [],
                "review_status": "reviewed",
            }
            for i in range(5)
        ]
        path = self._write_graph(tmp_path, concepts)  # type: ignore[arg-type]
        entries = load_kr_curriculum_entries_from_graph_json(path, now=_NOW)
        assert len(entries) == 5
        assert all(e.subject == "수학" for e in entries)
        assert all(e.entry_id == f"{e.concept_id}:KR" for e in entries)  # 무접미 불변


# ──────────────────────────────────────────────────────────────────────────
# ② upsert SQL 구성 — ON CONFLICT(entry_id)·created_at 보존·updated_at 갱신
# ──────────────────────────────────────────────────────────────────────────
def _entry(tmp_path: Path, concept_id: str = "C1") -> object:
    path = tmp_path / "g.json"
    path.write_text(
        json.dumps(
            {
                "concepts": [
                    {
                        "concept_id": concept_id,
                        "name_ko": "x",
                        "domain": "d",
                        "grade_band_hint": "고등학교",
                        "standard_codes": ["[x]"],
                        "review_status": "reviewed",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return load_kr_curriculum_entries_from_graph_json(path, now=_NOW)[0]


class TestUpsertSql:
    def test_on_conflict_entry_id(self, tmp_path: Path) -> None:
        store, engine = _fake_store()
        store.populate([_entry(tmp_path)])  # type: ignore[list-item]
        compiled = _compile(engine.executed[0])
        assert "ON CONFLICT" in compiled
        assert "entry_id" in compiled

    def test_created_at_preserved_updated_at_set(self, tmp_path: Path) -> None:
        store, engine = _fake_store()
        store.populate([_entry(tmp_path)])  # type: ignore[list-item]
        compiled = _compile(engine.executed[0])
        set_clause = compiled.split("DO UPDATE SET", 1)[1]
        # created_at은 SET 절에 없어야(보존), updated_at은 있어야(갱신).
        assert "created_at" not in set_clause
        assert "updated_at" in set_clause

    def test_subject_included_in_insert_and_update_set(self, tmp_path: Path) -> None:
        """subject(S1)가 INSERT 컬럼·ON CONFLICT SET 양쪽에 포함(재적재 멱등 갱신 경로).

        populate는 mapper 컬럼키 필터로 값을 뽑으므로 subject 컬럼이 자동 포함된다 —
        server_default에만 의존하지 않고 로더가 '수학'을 명시 충전함을 SQL로 동결.
        """
        store, engine = _fake_store()
        store.populate([_entry(tmp_path)])  # type: ignore[list-item]
        compiled = _compile(engine.executed[0])
        insert_clause, set_clause = compiled.split("DO UPDATE SET", 1)
        assert "subject" in insert_clause  # INSERT 컬럼 목록에 포함
        assert "subject" in set_clause  # 재적재 시 갱신 대상(멱등 — 같은 값 '수학')


# ──────────────────────────────────────────────────────────────────────────
# ③ populate — 전 셀 upsert·dedup
# ──────────────────────────────────────────────────────────────────────────
class TestPopulate:
    def test_populate_upserts_each(self, tmp_path: Path) -> None:
        store, engine = _fake_store()
        entries = [_entry(tmp_path, "C1"), _entry(tmp_path, "C2")]
        count = populate_kr_curriculum_entries(entries, store=store)  # type: ignore[arg-type]
        assert count == 2
        assert len(engine.executed) == 2

    def test_populate_empty_is_noop(self, tmp_path: Path) -> None:
        store, engine = _fake_store()
        assert populate_kr_curriculum_entries([], store=store) == 0
        assert engine.executed == []

    def test_dedups_duplicate_entry_id_last_wins(self, tmp_path: Path) -> None:
        # 같은 concept_id → 같은 entry_id → 단일 배치 dedup(마지막 우선·중복행 오류 방지).
        store, engine = _fake_store()
        entries = [_entry(tmp_path, "C1"), _entry(tmp_path, "C1")]
        count = populate_kr_curriculum_entries(entries, store=store)  # type: ignore[arg-type]
        assert count == 1
        assert len(engine.executed) == 1


# ──────────────────────────────────────────────────────────────────────────
# ④ 원자 축 유도(S2-07) — 크로스워크 전파·충돌 규칙·결정론·실 코퍼스 하한
# ──────────────────────────────────────────────────────────────────────────
# 레포 루트 앵커(tests/backend/l1/ → parents[3]) — CWD 상대 경로는 CI(cwd=src/backend)에서 깨진다
# (atom_probe·relink governance `_ROOT` 선례). 실 코퍼스 하한 동결 테스트가 사용.
_ROOT = Path(__file__).resolve().parents[3]
_REAL_GRAPH = _ROOT / "data" / "corpus" / "concept_graph_v1" / "graph.json"
_REAL_CROSSWALK = _ROOT / "data" / "corpus" / "concept_atom_crosswalk_v1" / "crosswalk.jsonl"


def _canonical(
    tmp_path: Path,
    specs: list[dict[str, object]],
) -> list[object]:
    """graph.json 스펙 목록 → 검증된 canonical KR 셀 목록(기존 로더 경유·헬퍼).

    각 spec은 최소 concept_id를 담고, grade_band_hint(깊이 휴리스틱 축)·domain(승자 구분 축)·
    standard_codes를 선택적으로 덮어쓴다. 유도 테스트의 원천 셀을 실제 로더 산출물로 만들어
    schema 검증(불변식 게이트)을 그대로 통과시킨다.
    """
    concepts = [
        {
            "concept_id": spec["concept_id"],
            "name_ko": "x",
            "domain": spec.get("domain", "d"),
            "grade_band_hint": spec.get("grade_band_hint", "고등학교"),
            "standard_codes": spec.get("standard_codes", []),
            "review_status": "reviewed",
        }
        for spec in specs
    ]
    path = tmp_path / "graph_atoms.json"
    path.write_text(
        json.dumps({"concepts": concepts, "edges": []}, ensure_ascii=False), encoding="utf-8"
    )
    return list(load_kr_curriculum_entries_from_graph_json(path, now=_NOW))


class TestDeriveAtomEntries:
    def test_propagates_to_all_atoms_with_inherited_fields(self, tmp_path: Path) -> None:
        """매핑 concept의 atom_codes *전체*에 전파 — 원자별 entry_id `{원자}:KR`·필드 승계."""
        canonical = _canonical(
            tmp_path,
            [{"concept_id": "math.calc.c1", "standard_codes": ["[12미적01-01]"]}],
        )
        records = [
            CrosswalkRecord(
                concept_id="math.calc.c1",
                atom_codes=("12미적01-01-1", "12미적01-01-2", "12미적01-01-3"),
                primary_atom_code="12미적01-01-2",
            )
        ]
        atoms = derive_atom_curriculum_entries(canonical, records)  # type: ignore[arg-type]
        # primary만이 아니라 atom_codes 3개 전부(방송형 depth 전파 — mastery 배타 귀속과 다름).
        assert len(atoms) == 3
        assert [a.concept_id for a in atoms] == [
            "12미적01-01-1",
            "12미적01-01-2",
            "12미적01-01-3",
        ]
        for a in atoms:
            assert a.entry_id == f"{a.concept_id}:KR"  # S1 수학 셀 무접미 규약 승계
            assert a.country_code == "KR"
            assert a.subject == "수학"
            # 원천 셀 승계 — 깊이(고등학교→mastery 휴리스틱)·존재·출처·신뢰도·표준코드.
            assert a.required_depth == "mastery"
            assert a.is_present is True
            assert a.source_url == "https://www.ncic.go.kr"
            assert a.confidence == 0.9
            assert a.national_standard_codes == ["[12미적01-01]"]
            assert a.grade_band == "고등학교"

    def test_conflict_deepest_depth_wins(self, tmp_path: Path) -> None:
        """복수 canonical → 같은 원자: required_depth 최심 원천 승계(_DEPTH_ORDER 위계)."""
        canonical = _canonical(
            tmp_path,
            [
                # 중학교 → conceptual(얕음), 고등학교 → mastery(깊음) — 휴리스틱 매핑.
                {"concept_id": "math.a", "grade_band_hint": "중학교 1~3학년군", "domain": "얕음"},
                {"concept_id": "math.b", "grade_band_hint": "고등학교", "domain": "깊음"},
            ],
        )
        records = [
            CrosswalkRecord(
                concept_id="math.a", atom_codes=("9수01-01-1",), primary_atom_code=None
            ),
            CrosswalkRecord(
                concept_id="math.b", atom_codes=("9수01-01-1",), primary_atom_code=None
            ),
        ]
        atoms = derive_atom_curriculum_entries(canonical, records)  # type: ignore[arg-type]
        assert len(atoms) == 1
        assert atoms[0].required_depth == "mastery"  # 최심 승계
        assert atoms[0].domain_label == "깊음"  # 승자 셀 *전체* 승계(깊이만 아님)

    def test_conflict_none_depth_loses_to_explicit(self, tmp_path: Path) -> None:
        """depth None(미지 밴드) 원천은 명시 깊이 원천에 진다 — 신호 보존(미상이 덮어쓰기 금지)."""
        canonical = _canonical(
            tmp_path,
            [
                {"concept_id": "math.z", "grade_band_hint": "대학교", "domain": "미상"},  # None
                {"concept_id": "math.a", "grade_band_hint": "초등학교 1~2학년군", "domain": "명시"},
            ],
        )
        records = [
            CrosswalkRecord(
                concept_id="math.z", atom_codes=("2수01-01-1",), primary_atom_code=None
            ),
            CrosswalkRecord(
                concept_id="math.a", atom_codes=("2수01-01-1",), primary_atom_code=None
            ),
        ]
        atoms = derive_atom_curriculum_entries(canonical, records)  # type: ignore[arg-type]
        assert len(atoms) == 1
        # awareness(최저 명시 깊이)라도 None(신호 없음)을 이긴다.
        assert atoms[0].required_depth == "awareness"
        assert atoms[0].domain_label == "명시"

    def test_conflict_tie_breaks_by_source_concept_id_lexicographic(self, tmp_path: Path) -> None:
        """동순위 깊이 충돌 — 원천 concept_id 사전순 앞선 셀 승계(결정론)."""
        canonical = _canonical(
            tmp_path,
            [
                {"concept_id": "math.bbb", "domain": "뒤"},  # 둘 다 고등학교 → mastery 동순위
                {"concept_id": "math.aaa", "domain": "앞"},
            ],
        )
        records = [
            CrosswalkRecord(
                concept_id="math.bbb", atom_codes=("10공수1-01-1",), primary_atom_code=None
            ),
            CrosswalkRecord(
                concept_id="math.aaa", atom_codes=("10공수1-01-1",), primary_atom_code=None
            ),
        ]
        atoms = derive_atom_curriculum_entries(canonical, records)  # type: ignore[arg-type]
        assert len(atoms) == 1
        assert atoms[0].domain_label == "앞"  # 사전순 "math.aaa" < "math.bbb"

    def test_unmapped_and_missing_yield_zero_atoms(self, tmp_path: Path) -> None:
        """미매핑(atom_codes 빈)·canonical 셀 없는 크로스워크 concept — 원자 행 0(날조 금지)."""
        canonical = _canonical(tmp_path, [{"concept_id": "math.only.canonical"}])
        records = [
            # canonical은 있으나 크로스워크 미매핑(unmapped) — 강제 귀속 금지.
            CrosswalkRecord(
                concept_id="math.only.canonical", atom_codes=(), primary_atom_code=None
            ),
            # 크로스워크에만 있고 canonical 셀 없음 — 원천 신호 부재.
            CrosswalkRecord(
                concept_id="math.ghost", atom_codes=("9수01-99-1",), primary_atom_code=None
            ),
        ]
        assert derive_atom_curriculum_entries(canonical, records) == []  # type: ignore[arg-type]

    def test_canonical_entries_are_not_mutated(self, tmp_path: Path) -> None:
        """유도는 canonical 셀을 변경하지 않는다(원자 행은 *추가* 축·in-place 오염 금지)."""
        canonical = _canonical(tmp_path, [{"concept_id": "math.keep"}])
        before = [e.model_dump() for e in canonical]  # type: ignore[attr-defined]
        records = [
            CrosswalkRecord(
                concept_id="math.keep", atom_codes=("10공수1-02-1",), primary_atom_code=None
            )
        ]
        derive_atom_curriculum_entries(canonical, records)  # type: ignore[arg-type]
        assert [e.model_dump() for e in canonical] == before  # type: ignore[attr-defined]

    def test_derivation_is_deterministic(self, tmp_path: Path) -> None:
        """같은 입력 2회 유도 — 동일 산출(entry_id 정렬·승자 결정론). 입력 순서 뒤집어도 동일."""
        canonical = _canonical(
            tmp_path,
            [
                {"concept_id": "math.p", "grade_band_hint": "중학교 1~3학년군"},
                {"concept_id": "math.q", "grade_band_hint": "고등학교"},
            ],
        )
        records = [
            CrosswalkRecord(
                concept_id="math.p", atom_codes=("9수01-05-1", "9수01-05-2"), primary_atom_code=None
            ),
            CrosswalkRecord(
                concept_id="math.q", atom_codes=("9수01-05-2", "9수01-05-3"), primary_atom_code=None
            ),
        ]
        first = derive_atom_curriculum_entries(canonical, records)  # type: ignore[arg-type]
        second = derive_atom_curriculum_entries(canonical, list(reversed(records)))  # type: ignore[arg-type]
        assert [e.model_dump() for e in first] == [e.model_dump() for e in second]
        assert [e.entry_id for e in first] == sorted(e.entry_id for e in first)  # 정렬 산출

    def test_assembly_returns_canonical_plus_atoms(self, tmp_path: Path) -> None:
        """조립 함수 — canonical(기존 로더와 동일 산출·무변경) + 원자 행을 함께 반환."""
        graph = tmp_path / "g.json"
        graph.write_text(
            json.dumps(
                {
                    "concepts": [
                        {
                            "concept_id": "math.asm",
                            "name_ko": "x",
                            "domain": "d",
                            "grade_band_hint": "고등학교",
                            "standard_codes": [],
                            "review_status": "reviewed",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        crosswalk = tmp_path / "cw.jsonl"
        crosswalk.write_text(
            json.dumps(
                {
                    "concept_id": "math.asm",
                    "atom_codes": ["10공수1-03-1", "10공수1-03-2"],
                    "primary_atom_code": "10공수1-03-1",
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        canonical, atoms = load_kr_curriculum_entries_with_atoms(graph, crosswalk, now=_NOW)
        # canonical은 기존 로더 산출과 동일(하위호환 — 기존 함수 무변경).
        plain = load_kr_curriculum_entries_from_graph_json(graph, now=_NOW)
        assert [e.model_dump() for e in canonical] == [e.model_dump() for e in plain]
        assert [a.concept_id for a in atoms] == ["10공수1-03-1", "10공수1-03-2"]
        assert all(a.required_depth == "mastery" for a in atoms)

    def test_real_corpus_atom_floor_frozen(self) -> None:
        """실 코퍼스(graph.json+crosswalk.jsonl) 유도 — 원자 행 수 하한 동결(드리프트 감지).

        2026-07-09 실측: canonical 437 셀 → 유도 원자 행 1,324개(크로스워크 전 437 concept 매핑·
        고유 원자 1,324). 코퍼스 재유도로 수치가 내려가면 여기서 잡는다(relink governance ⑤
        하한 동결 스타일 — 소스는 repo 커밋 코퍼스라 hermetic·PG 불요).
        """
        assert _REAL_GRAPH.exists(), f"실 코퍼스 부재: {_REAL_GRAPH}"
        assert _REAL_CROSSWALK.exists(), f"실 코퍼스 부재: {_REAL_CROSSWALK}"
        canonical = load_kr_curriculum_entries_from_graph_json(_REAL_GRAPH, now=_NOW)
        atoms = derive_atom_curriculum_entries(canonical, load_crosswalk_records(_REAL_CROSSWALK))
        assert (
            len(canonical) >= 437
        ), f"canonical {len(canonical)} < 하한 437(코퍼스 축소 드리프트?)"
        assert (
            len(atoms) >= 1311
        ), f"원자 행 {len(atoms)} < 하한 1311(코퍼스 축소 드리프트? — 병합 13건 반영 2026-07-28)"
        # entry_id 유일(원자당 1셀·충돌 승자 단일) + 무접미 `{원자}:KR` 규약.
        entry_ids = [a.entry_id for a in atoms]
        assert len(set(entry_ids)) == len(entry_ids)
        assert all(eid == f"{a.concept_id}:KR" for eid, a in zip(entry_ids, atoms, strict=True))
        # canonical 키 공간(`math.*`)과 원자 키 공간 무교차 — 축 분리 보존(덮어쓰기 오염 0).
        assert not any(a.concept_id.startswith("math.") for a in atoms)


# ──────────────────────────────────────────────────────────────────────────
# ⑤ 대학 원자 직접 유도 (W0 — S-1: 학년축 최단경로 계획 §2.3·§3)
# ──────────────────────────────────────────────────────────────────────────
_REAL_ATOM_GRAPH = _ROOT / "data" / "corpus" / "atom_graph_v1" / "graph.json"


def _write_atom_graph(tmp_path: Path, atoms: list[dict[str, object]]) -> Path:
    path = tmp_path / "atom_graph.json"
    path.write_text(json.dumps({"concepts": atoms}, ensure_ascii=False), encoding="utf-8")
    return path


class TestUniversityAtomDerivation:
    def test_maps_grade_band_to_introduced_grade_and_mastery_depth(self, tmp_path: Path) -> None:
        path = _write_atom_graph(
            tmp_path,
            [
                {
                    "code": "CALC1-C01",
                    "school_level": "대학",
                    "grade_band": "1학년",
                    "subject_area": "미적분학 I",
                    "standard_codes": ["[CALC1-01-01]"],
                }
            ],
        )
        entries = load_kr_curriculum_entries_for_university_atoms(path, now=_NOW)
        assert len(entries) == 1
        e = entries[0]
        assert e.concept_id == "CALC1-C01"
        assert e.entry_id == "CALC1-C01:KR"  # S1 수학 셀 무접미 규약(canonical과 동일)
        assert e.country_code == "KR"
        assert e.subject == "수학"
        assert e.grade_band == "1학년"
        assert e.introduced_grade == 13  # 고3(12) 다음 이어붙인 로더 내부 관례
        assert e.domain_label == "미적분학 I"
        assert e.required_depth == "mastery"  # 4단계 천장(고등학교와 동일 서열)
        assert e.national_standard_codes == ["[CALC1-01-01]"]
        assert e.is_present is True
        assert e.confidence == 0.6  # 원자 코퍼스는 review_status 신호 없음 — 보수적 기본값
        assert e.created_at == _NOW

    def test_all_four_university_grade_bands_map(self, tmp_path: Path) -> None:
        expected = {"1학년": 13, "2학년": 14, "3학년": 15, "4학년": 16}
        path = _write_atom_graph(
            tmp_path,
            [
                {
                    "code": f"C-{band}",
                    "school_level": "대학",
                    "grade_band": band,
                    "subject_area": "d",
                }
                for band in expected
            ],
        )
        entries = load_kr_curriculum_entries_for_university_atoms(path, now=_NOW)
        by_band = {e.grade_band: e for e in entries}
        assert set(by_band) == set(expected)
        for band, grade in expected.items():
            assert by_band[band].introduced_grade == grade

    def test_non_university_school_level_excluded(self, tmp_path: Path) -> None:
        """school_level이 '대학'이 아닌 원자는 대학 grade_band 라벨을 써도 유도 대상 아님."""
        path = _write_atom_graph(
            tmp_path,
            [{"code": "K12-X", "school_level": "고등", "grade_band": "1학년", "subject_area": "d"}],
        )
        assert load_kr_curriculum_entries_for_university_atoms(path, now=_NOW) == []

    def test_atom_missing_grade_band_skipped(self, tmp_path: Path) -> None:
        """단원·소단원 헤더 등 grade_band=None인 대학 원자 — 신호 없음, 건너뜀(날조 금지)."""
        path = _write_atom_graph(
            tmp_path,
            [{"code": "CALC1-U1", "school_level": "대학", "grade_band": None, "subject_area": "d"}],
        )
        assert load_kr_curriculum_entries_for_university_atoms(path, now=_NOW) == []

    def test_atom_unmapped_grade_band_label_skipped(self, tmp_path: Path) -> None:
        """ "1학년" 계열이 아닌 미지 라벨(예: "고3" 오적재)은 매핑에 없어 건너뜀 — 추정 안 함."""
        path = _write_atom_graph(
            tmp_path,
            [{"code": "X", "school_level": "대학", "grade_band": "고3", "subject_area": "d"}],
        )
        assert load_kr_curriculum_entries_for_university_atoms(path, now=_NOW) == []

    def test_skips_when_code_missing(self, tmp_path: Path) -> None:
        path = _write_atom_graph(
            tmp_path, [{"school_level": "대학", "grade_band": "1학년", "subject_area": "d"}]
        )
        assert load_kr_curriculum_entries_for_university_atoms(path, now=_NOW) == []

    def test_deterministic_entry_id_sorted_output(self, tmp_path: Path) -> None:
        path = _write_atom_graph(
            tmp_path,
            [
                {
                    "code": "Z-01",
                    "school_level": "대학",
                    "grade_band": "2학년",
                    "subject_area": "d",
                },
                {
                    "code": "A-01",
                    "school_level": "대학",
                    "grade_band": "1학년",
                    "subject_area": "d",
                },
            ],
        )
        entries = load_kr_curriculum_entries_for_university_atoms(path, now=_NOW)
        assert [e.entry_id for e in entries] == sorted(e.entry_id for e in entries)
        assert [e.concept_id for e in entries] == ["A-01", "Z-01"]

    def test_real_corpus_university_floor_frozen(self) -> None:
        """실 코퍼스(atom_graph_v1) 유도 — 대학 원자 행 수 하한 동결(드리프트 감지).

        2026-08-05 실측: atom_graph_v1의 대학 원자 1,069건 중 grade_band(1~4학년)가 채워진
        건 512건(나머지 557건은 단원·소단원 헤더 등 level != 세부개념·grade_band None).
        코퍼스 재생성으로 이 수치가 내려가면 여기서 잡는다(canonical 원자 하한 동결과 동형
        패턴 — `test_real_corpus_atom_floor_frozen`).
        """
        assert _REAL_ATOM_GRAPH.exists(), f"실 코퍼스 부재: {_REAL_ATOM_GRAPH}"
        entries = load_kr_curriculum_entries_for_university_atoms(_REAL_ATOM_GRAPH, now=_NOW)
        assert len(entries) >= 512, f"대학 원자 행 {len(entries)} < 하한 512(코퍼스 축소 드리프트?)"
        # entry_id 유일 + 무접미 `{원자}:KR` 규약 + 전량 mastery(4단계 천장) + KR 셀 상수.
        entry_ids = [e.entry_id for e in entries]
        assert len(set(entry_ids)) == len(entry_ids)
        assert all(eid == f"{e.concept_id}:KR" for eid, e in zip(entry_ids, entries, strict=True))
        assert all(e.required_depth == "mastery" for e in entries)
        assert all(e.grade_band in {"1학년", "2학년", "3학년", "4학년"} for e in entries)
        # canonical·K-12 원자 키 공간과 무교차(둘 다 `math.*`/NCIC 원자코드, 대학은 자체 코드계).
        assert not any(e.concept_id.startswith("math.") for e in entries)
