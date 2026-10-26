"""교육과정 Overlay 적재 *통합테스트* — graph.json → curriculum_entry KR 셀 (실 PG 통합).

마이그레이션 head가 적용된 **실 PostgreSQL**(`curriculum_entry` 테이블)에 KR 교육과정 셀을 적재해
Overlay가 실제로 서는지 본다. CI `backend — 마이그레이션·통합 (실 PG)` 잡이 `pgvector/pgvector:pg16`
+ `alembic upgrade head` 후 `WHYMATH_RUN_INTEGRATION=1`로 수집·실행한다(신규 CI 잡 불요 — 기존 잡이
`tests/backend/l1/`를 수집). PG 미도달 시 graceful skip(backend_concept 통합테스트 미러).

검증:
  ① 적재 → `curriculum_entry` row 존재·entry_id=`{concept_id}:KR`·매핑 필드 반영(domain_label·
     grade_band·introduced_grade·national_standard_codes·confidence·KR 상수)
  ② 멱등 — 같은 셀 재적재 시 행 1개·값 갱신·**created_at 보존**(updated_at은 갱신)
  ③ 원자 축(S2-07) — 크로스워크 유도 원자-키 행 적재 → `CurriculumDepthResolver.resolve_many
     ([원자코드])` hit(acceptance 직접 실증) + 멱등(2회 populate 행 수 안정)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from whymath_backend.config import Settings
from whymath_backend.l1.curriculum.curriculum_loader import (
    load_kr_curriculum_entries_from_graph_json,
    load_kr_curriculum_entries_with_atoms,
    populate_kr_curriculum_entries,
)

pytestmark = pytest.mark.integration

# 통합테스트 적재 키(정리 대상). 실 데이터와 충돌하지 않도록 9xx 순번 slug.
_NID = "HIGH-CALC-941"
_ENTRY_ID = f"{_NID}:KR"
_NOW = datetime(2026, 6, 30, 12, 0, 0, tzinfo=timezone.utc)
_LATER = datetime(2026, 7, 1, 9, 30, 0, tzinfo=timezone.utc)


def _sync_engine() -> object:
    """통합테스트용 sync(psycopg) 엔진 — 정리·조회용 raw 엔진."""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    settings = Settings()
    url = settings.sync_database_url
    if settings.db_disable_pool:
        return create_engine(url, poolclass=NullPool)
    return create_engine(url)


def _reachable() -> bool:
    """실 PG 도달 + `curriculum_entry` 테이블 존재(마이그레이션 적용) 여부."""
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.connect() as conn:  # type: ignore[attr-defined]
            conn.execute(text("SELECT count(*) FROM curriculum_entry"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def _cleanup(entry_ids: list[str]) -> None:
    """curriculum_entry 적재 행 정리(entry_id 기준)."""
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.begin() as conn:  # type: ignore[attr-defined]
            conn.execute(
                text("DELETE FROM curriculum_entry WHERE entry_id = ANY(:ids)"),
                {"ids": entry_ids},
            )
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def _skip_if_unreachable() -> None:
    if not _reachable():
        pytest.skip(
            "PostgreSQL 미도달(또는 마이그레이션 미적용) — 통합 테스트 건너뜀 "
            "(WHYMATH_DATABASE_URL·alembic upgrade head 확인)"
        )


def _graph(tmp_path: Path) -> Path:
    path = tmp_path / "graph.json"
    path.write_text(
        json.dumps(
            {
                "concepts": [
                    {
                        "concept_id": _NID,
                        "name_ko": "정적분",
                        "domain": "적분",
                        "grade_band_hint": "고등학교",
                        "standard_codes": ["[12미적02-05]"],
                        "prerequisite_concept_ids": ["HIGH-CALC-940"],
                        "review_status": "reviewed",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


class TestCurriculumEntryRoundtrip:
    def test_populate_creates_kr_cell(self, tmp_path: Path) -> None:
        _skip_if_unreachable()
        from sqlalchemy import text

        try:
            entries = load_kr_curriculum_entries_from_graph_json(_graph(tmp_path), now=_NOW)
            count = populate_kr_curriculum_entries(entries, settings=Settings())
            assert count == 1

            engine = _sync_engine()
            try:
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    row = conn.execute(
                        text(
                            "SELECT entry_id, concept_id, country_code, subject, domain_label, "
                            "grade_band, introduced_grade, national_standard_codes, "
                            "curriculum_revision, license_id, is_present, confidence, source_url, "
                            "required_depth, created_at, updated_at "
                            "FROM curriculum_entry WHERE entry_id = :e"
                        ),
                        {"e": _ENTRY_ID},
                    ).one()
                assert row.entry_id == _ENTRY_ID
                assert row.concept_id == _NID
                assert row.country_code == "KR"
                assert row.subject == "수학"  # S1 — KR 적재 셀은 전부 수학(교과 레벨 축)
                assert row.domain_label == "적분"
                assert row.grade_band == "고등학교"
                assert row.introduced_grade == 10
                assert row.national_standard_codes == ["[12미적02-05]"]
                assert row.curriculum_revision == "2022 개정"
                assert row.license_id == "KR-NCIC"
                assert row.is_present is True
                assert float(row.confidence) == pytest.approx(0.9)
                assert row.source_url == "https://www.ncic.go.kr"
                assert row.required_depth == "mastery"  # 고등학교 → grade_band 학년진행 휴리스틱
            finally:
                engine.dispose()  # type: ignore[attr-defined]
        finally:
            _cleanup([_ENTRY_ID])

    def test_depth_resolver_reads_heuristic_depth(self, tmp_path: Path) -> None:
        """전 체인 잠금 — graph.json grade_band → 로더 휴리스틱 → curriculum_entry → resolver 복원.

        #380 depth 휴리스틱(고등학교→mastery)이 적재된 뒤 `CurriculumDepthResolver`가 그 깊이를
        *읽어* 돌려줌을 실 PG로 입증한다(자동 커리큘럼 정렬 깊이 축이 코퍼스 신호부터 read-time
        해석까지 살아있음). 로더 통합(DB row 단언)·resolver 단위(fake 엔진·수동 depth)가 각자
        덮던 두 끝을 이 테스트가 잇는다. api 주입(`_inject_curriculum_required_depth`)이 이
        resolver를 `to_thread`로 호출하므로 그 위 계층까지 같은 신호가 흐른다.
        """
        _skip_if_unreachable()
        from whymath_backend.l1.curriculum.curriculum_resolve import CurriculumDepthResolver
        from whymath_backend.schema.enums import RequiredDepth

        try:
            entries = load_kr_curriculum_entries_from_graph_json(_graph(tmp_path), now=_NOW)
            populate_kr_curriculum_entries(entries, settings=Settings())
            resolver = CurriculumDepthResolver()
            # 고등학교 → mastery(학년진행 휴리스틱)를 resolver가 read-back한다.
            assert resolver.resolve(_NID, country_code="KR") is RequiredDepth.mastery
            # 미적재 개념은 None(graceful — 깊이 신호 없음).
            assert resolver.resolve("HIGH-CALC-UNMAPPED-941", country_code="KR") is None
        finally:
            _cleanup([_ENTRY_ID])

    def test_atom_axis_rows_hit_depth_resolver_and_idempotent(self, tmp_path: Path) -> None:
        """원자 축(S2-07) acceptance 직접 실증 — 원자-키 행 적재 → resolver 원자코드 hit + 멱등.

        S2-03 이후 gating 깊이 조인(`_fetch_problem_concept_codes` → resolver)이 모으는 코드는
        *원자 코드*다 — 크로스워크 전파로 유도한 원자-키 curriculum_entry 행이 적재되면
        `CurriculumDepthResolver.resolve_many([원자코드])`가 hit해 L6 깊이정렬 신호가 복원됨을
        실 PG로 입증한다. 2회 populate에도 행 수가 안정(멱등 — entry_id ON CONFLICT)함을 함께
        동결한다.
        """
        _skip_if_unreachable()
        from sqlalchemy import text

        from whymath_backend.l1.curriculum.curriculum_resolve import CurriculumDepthResolver
        from whymath_backend.schema.enums import RequiredDepth

        # 통합테스트 전용 원자 코드(실 데이터와 충돌하지 않도록 9xx 순번) — 크로스워크 유도 대상.
        atom_codes = ["12미적02-95-1", "12미적02-95-2"]
        entry_ids = [_ENTRY_ID, *[f"{code}:KR" for code in atom_codes]]
        crosswalk = tmp_path / "crosswalk.jsonl"
        crosswalk.write_text(
            json.dumps(
                {
                    "concept_id": _NID,
                    "atom_codes": atom_codes,
                    "primary_atom_code": atom_codes[0],
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        try:
            canonical, atoms = load_kr_curriculum_entries_with_atoms(
                _graph(tmp_path), crosswalk, now=_NOW
            )
            count = populate_kr_curriculum_entries([*canonical, *atoms], settings=Settings())
            assert count == 3  # canonical 1 + 원자 2

            # acceptance — resolver가 *원자 코드*로 깊이를 복원한다(고등학교 → mastery 승계).
            resolver = CurriculumDepthResolver()
            depth_by_code = resolver.resolve_many(atom_codes, country_code="KR")
            assert depth_by_code == {code: RequiredDepth.mastery for code in atom_codes}

            # 멱등 — 2회 populate에도 행 수 안정(entry_id ON CONFLICT upsert).
            canonical2, atoms2 = load_kr_curriculum_entries_with_atoms(
                _graph(tmp_path), crosswalk, now=_LATER
            )
            populate_kr_curriculum_entries([*canonical2, *atoms2], settings=Settings())
            engine = _sync_engine()
            try:
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    n = conn.execute(
                        text("SELECT count(*) FROM curriculum_entry WHERE entry_id = ANY(:ids)"),
                        {"ids": entry_ids},
                    ).scalar_one()
                assert n == 3  # 재적재에도 행 수 동일(멱등)
            finally:
                engine.dispose()  # type: ignore[attr-defined]
        finally:
            _cleanup(entry_ids)

    def test_reload_preserves_created_at_updates_updated_at(self, tmp_path: Path) -> None:
        _skip_if_unreachable()
        from sqlalchemy import text

        try:
            # 1차 적재(now=_NOW).
            first = load_kr_curriculum_entries_from_graph_json(_graph(tmp_path), now=_NOW)
            populate_kr_curriculum_entries(first, settings=Settings())

            # 2차 적재(now=_LATER) → 같은 entry_id 갱신·created_at 보존·updated_at 갱신.
            second = load_kr_curriculum_entries_from_graph_json(_graph(tmp_path), now=_LATER)
            populate_kr_curriculum_entries(second, settings=Settings())

            engine = _sync_engine()
            try:
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    rows = conn.execute(
                        text(
                            "SELECT created_at, updated_at FROM curriculum_entry "
                            "WHERE entry_id = :e"
                        ),
                        {"e": _ENTRY_ID},
                    ).all()
                assert len(rows) == 1  # 멱등(행 1개)
                # created_at 보존(최초 _NOW)·updated_at 갱신(_LATER).
                assert rows[0].created_at == _NOW
                assert rows[0].updated_at == _LATER
            finally:
                engine.dispose()  # type: ignore[attr-defined]
        finally:
            _cleanup([_ENTRY_ID])


class TestUniversityCellsRoundtrip:
    """대학 원자 셀(S4-64) — 적재 → DB 행 → resolver 복원 → 멱등을 실 PG로 잠근다.

    required_depth는 고정 mastery가 아니라 원자별 cognitive_type 도출(절차→procedural·개념→
    conceptual·표상→NULL)이며, NULL은 resolver가 None으로 돌려준다(깊이 신호 없음 — 정직 폴백).
    """

    # 통합테스트 전용 대학 원자 코드(실 코드계와 충돌하지 않는 ZZ 접두).
    _CODES = {
        "ZZ-UNIV-941-P": ("절차", "procedural"),
        "ZZ-UNIV-941-C": ("개념", "conceptual"),
        "ZZ-UNIV-941-R": ("표상", None),
    }

    def _atom_graph(self, tmp_path: Path) -> Path:
        atoms = [
            {
                "code": code,
                "school_level": "대학",
                "grade_band": "2학년",
                "subject_area": "선형대수",
                "cognitive_type": cognitive,
            }
            for code, (cognitive, _depth) in self._CODES.items()
        ]
        path = tmp_path / "atom_graph.json"
        path.write_text(json.dumps({"concepts": atoms}, ensure_ascii=False), encoding="utf-8")
        return path

    def test_university_cells_land_with_cognitive_type_depth_and_are_idempotent(
        self, tmp_path: Path
    ) -> None:
        _skip_if_unreachable()
        from sqlalchemy import text

        from whymath_backend.l1.curriculum.curriculum_loader import (
            load_kr_curriculum_entries_for_university_atoms,
        )
        from whymath_backend.l1.curriculum.curriculum_resolve import CurriculumDepthResolver

        entry_ids = [f"{code}:KR" for code in self._CODES]
        try:
            for now in (_NOW, _LATER):  # 2회 적재 — 멱등
                entries = load_kr_curriculum_entries_for_university_atoms(
                    self._atom_graph(tmp_path), now=now
                )
                assert populate_kr_curriculum_entries(entries, settings=Settings()) == 3

            engine = _sync_engine()
            try:
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    rows = {
                        r.concept_id: r
                        for r in conn.execute(
                            text(
                                "SELECT concept_id, introduced_grade, grade_band, required_depth, "
                                "created_at, updated_at FROM curriculum_entry "
                                "WHERE entry_id = ANY(:ids)"
                            ),
                            {"ids": entry_ids},
                        ).all()
                    }
            finally:
                engine.dispose()  # type: ignore[attr-defined]
            assert set(rows) == set(self._CODES)  # 재적재에도 행 3개(멱등)
            for code, (_cognitive, depth) in self._CODES.items():
                assert rows[code].introduced_grade == 14  # 대학 2학년 = 14
                assert rows[code].grade_band == "2학년"
                assert rows[code].required_depth == depth
                assert rows[code].created_at == _NOW  # 최초 생성 시각 보존
                assert rows[code].updated_at == _LATER

            # read-time — resolver는 깊이가 있는 두 코드만 복원하고 표상(NULL)은 신호 없음.
            resolved = CurriculumDepthResolver().resolve_many(list(self._CODES), country_code="KR")
            assert {code: d.value for code, d in resolved.items()} == {
                "ZZ-UNIV-941-P": "procedural",
                "ZZ-UNIV-941-C": "conceptual",
            }
        finally:
            _cleanup(entry_ids)
