"""achievement_criteria_v1 코퍼스 → backend 적재 *단위테스트* — CUR-07 신규 로더 (hermetic·PG 불요).

`test_standard_loader.py`의 `_FakeEngine` 패턴을 재사용한다(PG 없이 배선·SQL 구성·매칭/미매칭
계상을 검증). 실 PG 라운드트립은 통합테스트로 미룬다(이 세션은 라이브 DB가 없는 샌드박스 —
`docs/architecture/curriculum_module_gap_review_r2.md` §3 D5·태스크 지시대로 hermetic만 정직히
수행하고 실 적용은 마이그레이션 파일 정적 검토로 대체).

여기서 못 박는 것:
  ① 코퍼스 파싱 — 바로 배열(Collection 표지 없음)·list|Path 입력·비배열 거부
  ② 평탄화 — standard_criteria_coverage → {code: criteria_codes}·achievement_levels_by_unit →
     AchievementLevelUnit 목록
  ③ 평가준거 매칭 UPDATE — (curriculum_revision, official_code) 대조·매칭/미매칭 정직 계상(조용한
     스킵 금지)·SQL 구성(UPDATE·WHERE·evaluation_criteria_codes)
  ④ 단원 등급 upsert — ON CONFLICT(자연키)·dedup(마지막 우선)·unit_id 미-SET
  ⑤ 오케스트레이션 — load_achievement_criteria가 두 store를 조합
  ⑥ **실 코퍼스 교차검증** — achievement_criteria_v1(459 coverage 항목)이 standards_v1의 2015
     개정 official_code 집합과 실측 전량(459/459) 일치함을 회귀 테스트로 고정(오프라인 분석
     결과를 CI가 상시 재확인 — "정직 계상" 수치의 근거)
  ⑦ CLI(main) — 코퍼스 부재 시 exit 2·정상 실행 시 exit 0
"""

from __future__ import annotations

import json
from pathlib import Path
from types import TracebackType
from typing import Any

import pytest

from whymath_backend.config import Settings
from whymath_backend.l1.standards.criteria_loader import (
    DEFAULT_CURRICULUM_REVISION,
    AchievementLevelUnitStore,
    CriteriaCoverageStore,
    _as_records,
    _extract_coverage,
    _extract_level_units,
    load_achievement_criteria,
    main,
)
from whymath_backend.schema.standard import AchievementLevelUnit

# ──────────────────────────────────────────────────────────────────────────
# 코퍼스 레코드 픽스처 (인라인 합성 — 실제 achievement_criteria.json 원소 축소판)
# ──────────────────────────────────────────────────────────────────────────
_CODE_A = "[10수학01-01]"
_CODE_B = "[10수학01-02]"
_CODE_UNMATCHED = "[99수학99-99]"  # 어떤 known_pairs에도 없는 코드(미매칭 표본)


def _record(
    *,
    school_level: str = "고등학교",
    subject: str = "공통수학",
    coverage: list[dict[str, Any]] | None = None,
    levels_by_unit: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """코퍼스 레코드 1건(school_level×subject 세트) — achievement_criteria.json 원소 형태."""
    return {
        "school_level": school_level,
        "subject": subject,
        "unit_hierarchy": ["(1) 문자와 식"],
        "standard_criteria_coverage": coverage if coverage is not None else [],
        "achievement_levels_by_unit": levels_by_unit if levels_by_unit is not None else [],
    }


# ──────────────────────────────────────────────────────────────────────────
# 가짜 sync 엔진 — begin()/connect() 컨텍스트 + execute() (PG 없이 배선 관찰)
# ──────────────────────────────────────────────────────────────────────────
class _FakeResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


class _PairRow:
    """(curriculum_revision, official_code) 조회 결과 행 흉내."""

    def __init__(self, curriculum_revision: str, official_code: str) -> None:
        self.curriculum_revision = curriculum_revision
        self.official_code = official_code


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
        compiled = _compile(statement)
        is_select = compiled.strip().upper().startswith("SELECT")
        if is_select and "achievement_standard.curriculum_revision" in compiled:
            return _FakeResult(self._engine.pair_rows)
        return _FakeResult([])


def _pg_dialect() -> object:
    from sqlalchemy.dialects import postgresql

    return postgresql.dialect()


def _compile(statement: object) -> str:
    return str(statement.compile(dialect=_pg_dialect()))  # type: ignore[attr-defined]


class _FakeEngine:
    """SQLAlchemy sync Engine 최소 흉내 — begin()/connect() + 실행 statement·(revision,code) 제어."""

    def __init__(self, pair_rows: list[object] | None = None) -> None:
        self.executed: list[object] = []
        self.pair_rows: list[object] = pair_rows if pair_rows is not None else []

    def begin(self) -> _FakeConnection:
        return _FakeConnection(self)

    def connect(self) -> _FakeConnection:
        return _FakeConnection(self)


def _criteria_store(
    pair_rows: list[object] | None = None,
) -> tuple[CriteriaCoverageStore, _FakeEngine]:
    engine = _FakeEngine(pair_rows)
    store = CriteriaCoverageStore(engine=engine)  # type: ignore[arg-type]  # 가짜 엔진(구조만 충족)
    return store, engine


def _level_store() -> tuple[AchievementLevelUnitStore, _FakeEngine]:
    engine = _FakeEngine()
    store = AchievementLevelUnitStore(engine=engine)  # type: ignore[arg-type]  # 가짜 엔진(구조만 충족)
    return store, engine


# ──────────────────────────────────────────────────────────────────────────
# ① 코퍼스 파싱 — 바로 배열·list|Path·비배열 거부
# ──────────────────────────────────────────────────────────────────────────
class TestRecordParsing:
    def test_list_input_passthrough(self) -> None:
        records = [_record()]
        assert _as_records(records) is records

    def test_path_input_loads_json_array(self, tmp_path: Path) -> None:
        path = tmp_path / "achievement_criteria.json"
        path.write_text(json.dumps([_record()], ensure_ascii=False), encoding="utf-8")
        result = _as_records(path)
        assert result == [_record()]

    def test_path_with_non_array_top_level_raises(self, tmp_path: Path) -> None:
        # standards_v1처럼 Collection *표지 dict*로 잘못 준 경우 — 이 코퍼스는 바로 배열이어야 한다.
        path = tmp_path / "wrong_shape.json"
        path.write_text(json.dumps({"standards": []}), encoding="utf-8")
        with pytest.raises(TypeError, match="배열"):
            _as_records(path)

    def test_invalid_input_type_raises(self) -> None:
        with pytest.raises(TypeError):
            _as_records({"not": "a list or path"})  # type: ignore[arg-type]

    def test_missing_file_raises_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            _as_records(tmp_path / "does_not_exist.json")


# ──────────────────────────────────────────────────────────────────────────
# ② 평탄화 — standard_criteria_coverage → 맵 / achievement_levels_by_unit → 모델 목록
# ──────────────────────────────────────────────────────────────────────────
class TestFlattening:
    def test_extract_coverage_flattens_across_records(self) -> None:
        records = [
            _record(coverage=[{"standard_code": _CODE_A, "criteria_codes": ["[10수학01-01-00]"]}]),
            _record(subject="수학Ⅰ", coverage=[{"standard_code": _CODE_B, "criteria_codes": []}]),
        ]
        coverage = _extract_coverage(records)
        assert coverage == {_CODE_A: ["[10수학01-01-00]"], _CODE_B: []}

    def test_extract_coverage_missing_criteria_codes_defaults_empty(self) -> None:
        records = [_record(coverage=[{"standard_code": _CODE_A}])]
        assert _extract_coverage(records) == {_CODE_A: []}

    def test_extract_coverage_duplicate_code_last_wins(self) -> None:
        # 실 코퍼스엔 없지만(전역 유일 실측) 방어적으로 마지막 우선.
        records = [
            _record(coverage=[{"standard_code": _CODE_A, "criteria_codes": ["첫"]}]),
            _record(
                subject="수학Ⅰ", coverage=[{"standard_code": _CODE_A, "criteria_codes": ["둘째"]}]
            ),
        ]
        assert _extract_coverage(records) == {_CODE_A: ["둘째"]}

    def test_extract_level_units_inherits_school_level_and_subject(self) -> None:
        records = [
            _record(
                school_level="고등학교",
                subject="공통수학",
                levels_by_unit=[{"unit": "(1) 다항식", "levels": ["A", "B", "C", "D", "E"]}],
            )
        ]
        units = _extract_level_units(records, source_document="achievement_criteria_v1")
        assert len(units) == 1
        unit = units[0]
        assert isinstance(unit, AchievementLevelUnit)
        assert unit.school_level == "고등학교"
        assert unit.subject == "공통수학"
        assert unit.unit == "(1) 다항식"
        assert unit.levels == ["A", "B", "C", "D", "E"]
        assert unit.source_document == "achievement_criteria_v1"

    def test_extract_level_units_missing_levels_defaults_empty(self) -> None:
        records = [_record(levels_by_unit=[{"unit": "(1) 문항 개발 목록"}])]
        units = _extract_level_units(records, source_document=None)
        assert units[0].levels == []
        assert units[0].source_document is None


# ──────────────────────────────────────────────────────────────────────────
# ③ 평가준거 매칭 UPDATE — 매칭/미매칭 정직 계상·SQL 구성
# ──────────────────────────────────────────────────────────────────────────
class TestCriteriaCoverageStore:
    def test_matched_code_produces_update(self) -> None:
        store, engine = _criteria_store([_PairRow(DEFAULT_CURRICULUM_REVISION, _CODE_A)])
        result = store.apply({_CODE_A: ["[10수학01-01-00]"]})
        assert result.matched == 1
        assert result.unmatched == 0
        assert result.unmatched_codes == ()
        updates = [s for s in engine.executed if _compile(s).strip().upper().startswith("UPDATE")]
        assert len(updates) == 1
        sql = _compile(updates[0])
        assert "UPDATE achievement_standard" in sql
        assert "evaluation_criteria_codes" in sql
        assert "WHERE" in sql.upper()

    def test_unmatched_code_is_counted_not_silently_skipped(self) -> None:
        store, engine = _criteria_store([_PairRow(DEFAULT_CURRICULUM_REVISION, _CODE_A)])
        result = store.apply({_CODE_UNMATCHED: ["뭔가"]})
        assert result.matched == 0
        assert result.unmatched == 1
        assert result.unmatched_codes == (_CODE_UNMATCHED,)
        # 매칭 대조 SELECT는 돌되 UPDATE는 없다(미매칭이라 스킵).
        updates = [s for s in engine.executed if _compile(s).strip().upper().startswith("UPDATE")]
        assert updates == []

    def test_mixed_matched_and_unmatched(self) -> None:
        store, engine = _criteria_store([_PairRow(DEFAULT_CURRICULUM_REVISION, _CODE_A)])
        result = store.apply({_CODE_A: ["a"], _CODE_UNMATCHED: ["b"]})
        assert result.matched == 1
        assert result.unmatched == 1
        assert result.unmatched_codes == (_CODE_UNMATCHED,)

    def test_wrong_curriculum_revision_is_unmatched(self) -> None:
        # official_code는 있지만 *다른 개정*으로 적재돼 있으면 대조 실패(2022 개정에만 있음).
        store, _ = _criteria_store([_PairRow("2022 개정", _CODE_A)])
        result = store.apply({_CODE_A: ["a"]}, curriculum_revision="2015 개정")
        assert result.matched == 0
        assert result.unmatched == 1

    def test_empty_coverage_is_noop(self) -> None:
        store, engine = _criteria_store()
        result = store.apply({})
        assert result == type(result)(matched=0, unmatched=0, unmatched_codes=())
        assert engine.executed == []

    def test_single_select_query_no_n_plus_one(self) -> None:
        # 여러 코드여도 (revision, official_code) 대조 조회는 *단 한 번*(N+1 0).
        store, engine = _criteria_store(
            [
                _PairRow(DEFAULT_CURRICULUM_REVISION, _CODE_A),
                _PairRow(DEFAULT_CURRICULUM_REVISION, _CODE_B),
            ]
        )
        store.apply({_CODE_A: ["a"], _CODE_B: ["b"]})
        selects = [
            s
            for s in engine.executed
            if _compile(s).strip().upper().startswith("SELECT")
            and "achievement_standard.curriculum_revision" in _compile(s)
        ]
        assert len(selects) == 1

    def test_unmatched_logged_not_silent(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        store, _ = _criteria_store([])
        with caplog.at_level(logging.WARNING):
            store.apply({_CODE_UNMATCHED: ["x"]})
        assert "매칭 실패" in caplog.text
        assert _CODE_UNMATCHED in caplog.text

    def test_default_settings_used_when_unset(self) -> None:
        store = CriteriaCoverageStore()
        assert isinstance(store._resolved_settings, Settings)


# ──────────────────────────────────────────────────────────────────────────
# ④ 단원 등급 upsert — ON CONFLICT·dedup(마지막 우선)·unit_id 미-SET
# ──────────────────────────────────────────────────────────────────────────
class TestAchievementLevelUnitStore:
    def test_populate_creates_upsert_statement(self) -> None:
        store, engine = _level_store()
        unit = AchievementLevelUnit(
            school_level="고등학교", subject="공통수학", unit="(1) 다항식", levels=["A", "B"]
        )
        count = store.populate([unit])
        assert count == 1
        assert len(engine.executed) == 1
        sql = _compile(engine.executed[0])
        assert "INSERT INTO achievement_level_unit" in sql
        assert "ON CONFLICT" in sql

    def test_does_not_set_unit_id_on_conflict(self) -> None:
        # 멱등 보존: ON CONFLICT DO UPDATE SET이 unit_id(UUID PK)를 *대입하지 않는다*(PK 보존).
        # SQLAlchemy가 PG용으로 암묵 RETURNING achievement_level_unit.unit_id를 자동 부가하므로
        # SET절 검사는 그 앞부분만 본다(standard_loader의 link_id 동일 검사 패턴 미러).
        store, engine = _level_store()
        unit = AchievementLevelUnit(school_level="고등학교", subject="공통수학", unit="(1) 다항식")
        store.populate([unit])
        sql = _compile(engine.executed[0])
        assert "DO UPDATE SET" in sql
        after_set = sql.split("DO UPDATE SET", 1)[1]
        set_clause = after_set.split("RETURNING", 1)[0]
        assert "unit_id" not in set_clause
        assert "levels" in set_clause

    def test_input_dedup_last_wins_on_natural_key(self) -> None:
        store, engine = _level_store()
        units = [
            AchievementLevelUnit(
                school_level="초중학교", subject="중학교1-3학년군", unit="(가) 1학년", levels=["A"]
            ),
            AchievementLevelUnit(
                school_level="초중학교", subject="중학교1-3학년군", unit="(가) 1학년", levels=["B"]
            ),
        ]
        count = store.populate(units)
        assert count == 1  # dedup → 1행
        assert len(engine.executed) == 1
        params = engine.executed[0].compile(dialect=_pg_dialect()).params  # type: ignore[attr-defined]
        assert ["B"] in params.values()  # 마지막 우선

    def test_empty_units_is_noop(self) -> None:
        store, engine = _level_store()
        assert store.populate([]) == 0
        assert engine.executed == []

    def test_default_settings_used_when_unset(self) -> None:
        store = AchievementLevelUnitStore()
        assert isinstance(store._resolved_settings, Settings)


# ──────────────────────────────────────────────────────────────────────────
# ⑤ 오케스트레이션 — load_achievement_criteria가 두 store를 조합
# ──────────────────────────────────────────────────────────────────────────
class TestLoadAchievementCriteria:
    def test_wires_both_stores(self) -> None:
        c_store, c_engine = _criteria_store([_PairRow(DEFAULT_CURRICULUM_REVISION, _CODE_A)])
        l_store, l_engine = _level_store()
        records = [
            _record(
                coverage=[{"standard_code": _CODE_A, "criteria_codes": ["x"]}],
                levels_by_unit=[{"unit": "(1) 다항식", "levels": ["A"]}],
            )
        ]
        result = load_achievement_criteria(records, criteria_store=c_store, level_store=l_store)
        assert result.criteria.matched == 1
        assert result.level_units_loaded == 1
        assert len(c_engine.executed) >= 1
        assert len(l_engine.executed) == 1

    def test_independent_axes_one_empty_other_proceeds(self) -> None:
        # coverage 0건이어도 단원 등급은 정상 적재된다(강제 결합 없음).
        c_store, _ = _criteria_store([])
        l_store, _ = _level_store()
        records = [_record(levels_by_unit=[{"unit": "(1) 다항식", "levels": ["A"]}])]
        result = load_achievement_criteria(records, criteria_store=c_store, level_store=l_store)
        assert result.criteria.matched == 0
        assert result.criteria.unmatched == 0  # coverage 자체가 0건 — 미매칭도 0
        assert result.level_units_loaded == 1

    def test_path_input_via_orchestrator(self, tmp_path: Path) -> None:
        path = tmp_path / "achievement_criteria.json"
        path.write_text(
            json.dumps(
                [_record(coverage=[{"standard_code": _CODE_A, "criteria_codes": []}])],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        c_store, _ = _criteria_store([_PairRow(DEFAULT_CURRICULUM_REVISION, _CODE_A)])
        l_store, _ = _level_store()
        result = load_achievement_criteria(path, criteria_store=c_store, level_store=l_store)
        assert result.criteria.matched == 1


# ──────────────────────────────────────────────────────────────────────────
# ⑥ 실 코퍼스 교차검증 — achievement_criteria_v1 ↔ standards_v1(2015 개정) 459/459 회귀 고정
# ──────────────────────────────────────────────────────────────────────────
def _repo_root() -> Path:
    # tests/backend/l1/test_criteria_loader.py → parents[3] = 레포 루트(standard_loader 선례와 동형).
    return Path(__file__).resolve().parents[3]


class TestRealCorpusCrossValidation:
    """오프라인 분석(이 태스크 설계 단계)에서 확인한 459/459 일치를 CI가 상시 재확인.

    실 DB 없이(hermetic) 실 두 코퍼스 파일(achievement_criteria_v1·standards_v1)만으로 매칭
    로직 전 경로를 검증한다 — known_pairs를 standards_v1의 2015 개정 official_code 실측 집합으로
    채운 가짜 엔진에 실 achievement_criteria.json을 흘린다.
    """

    def test_all_459_coverage_entries_match_standards_v1_2015(self) -> None:
        criteria_path = (
            _repo_root()
            / "data"
            / "corpus"
            / "achievement_criteria_v1"
            / "achievement_criteria.json"
        )
        standards_path = _repo_root() / "data" / "corpus" / "standards_v1" / "standards.json"
        if not criteria_path.exists() or not standards_path.exists():
            pytest.skip("실 코퍼스 미존재(achievement_criteria_v1 또는 standards_v1)")

        standards_payload = json.loads(standards_path.read_text(encoding="utf-8"))
        pair_rows = [
            _PairRow(s["curriculum_revision"], s["code"])
            for s in standards_payload["standards"]
            if s["curriculum_revision"] == "2015 개정"
        ]
        # 2015 개정 subset 건수는 단일 원천의 기계용 사본에서 읽는다(OPS-154 — 손 고정 금지).
        facts = json.loads(
            (_repo_root() / "docs" / "data" / "corpus_facts.json").read_text(encoding="utf-8")
        )
        assert len(pair_rows) == facts["standards.k12_2015"]  # standards_v1의 2015 개정 subset

        c_store, _ = _criteria_store(pair_rows)
        l_store, _ = _level_store()
        result = load_achievement_criteria(
            criteria_path, criteria_store=c_store, level_store=l_store
        )

        # 오프라인 분석 실측치 그대로 — 매칭 실패 0건(억지 매칭 아님, 자연 일치).
        assert result.criteria.matched == 459
        assert result.criteria.unmatched == 0
        assert result.criteria.unmatched_codes == ()

    def test_real_corpus_level_units_dedup_to_51(self) -> None:
        criteria_path = (
            _repo_root()
            / "data"
            / "corpus"
            / "achievement_criteria_v1"
            / "achievement_criteria.json"
        )
        if not criteria_path.exists():
            pytest.skip("실 코퍼스 미존재(achievement_criteria_v1)")

        c_store, _ = _criteria_store([])  # coverage 매칭은 이 테스트 관심사 아님
        l_store, l_engine = _level_store()
        result = load_achievement_criteria(
            criteria_path, criteria_store=c_store, level_store=l_store
        )

        # 원본 54건 중 3건이 (school_level,subject,unit) 완전 중복(값도 동일) — dedup 후 51.
        assert result.level_units_loaded == 51
        assert len(l_engine.executed) == 51


# ──────────────────────────────────────────────────────────────────────────
# ⑦ CLI(main) — 코퍼스 부재 exit 2 · 정상 실행 exit 0
# ──────────────────────────────────────────────────────────────────────────
class TestCli:
    def test_missing_corpus_returns_exit_2(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        missing = tmp_path / "nope.json"
        code = main(["--corpus", str(missing)])
        assert code == 2
        assert "없음" in capsys.readouterr().out

    def test_successful_run_reports_counts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / "achievement_criteria.json"
        path.write_text(
            json.dumps(
                [_record(coverage=[{"standard_code": _CODE_A, "criteria_codes": []}])],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        c_store, _ = _criteria_store([_PairRow(DEFAULT_CURRICULUM_REVISION, _CODE_A)])
        l_store, _ = _level_store()

        import whymath_backend.l1.standards.criteria_loader as mod

        monkeypatch.setattr(mod, "CriteriaCoverageStore", lambda **_kw: c_store)
        monkeypatch.setattr(mod, "AchievementLevelUnitStore", lambda **_kw: l_store)

        code = main(["--corpus", str(path)])
        assert code == 0
        out = capsys.readouterr().out
        assert "1건 매칭" in out
        assert "0건" in out  # 미매칭 0건
