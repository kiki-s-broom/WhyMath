"""오개념 카탈로그 코퍼스 → backend 적재 *통합테스트* — B.3 로더 (WHYMATH_RUN_INTEGRATION).

마이그레이션 head가 적용된 **실 PostgreSQL**(`misconception_catalog` 테이블)에 코퍼스 Collection을
적재해 B.3 로더가 실제로 서는지 본다. CI `backend — 마이그레이션·통합 (실 PG)` 잡이
`pgvector/pgvector:pg16` + `alembic upgrade head` 후 수집·실행한다(기존 잡이 `tests/backend/l1/`를
수집 — 신규 CI 잡 불요). PG 미도달 시 graceful skip(`test_standard_loader_integration.py` 미러).

검증:
  ① 합성 row 적재 → 컬럼 라운드트립(mis_id·canonical_statement·concept_src_id/standard_code 원천
     저장·mapping_score Decimal)
  ② 멱등 — 재적재 행수 불변·값 갱신
  ③ 실 코퍼스(`data/corpus/misconceptions_v1/misconceptions.json`) 적재 → 코퍼스 전건(`misconceptions.count`)·멱등·cleanup
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from whymath_backend.config import Settings
from whymath_backend.l1.misconception.catalog_loader import load_misconceptions

pytestmark = pytest.mark.integration

# 통합테스트 적재 키 — 실 데이터·코퍼스와 충돌하지 않도록 it 슬러그 mis_id.
_MIS_A = "MIT001"
_MIS_B = "MIT002"


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
    """실 PG 도달 + `misconception_catalog` 테이블 존재(마이그레이션 적용) 여부."""
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.connect() as conn:  # type: ignore[attr-defined]
            conn.execute(text("SELECT count(*) FROM misconception_catalog"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def _cleanup(mis_ids: list[str]) -> None:
    """오개념 카탈로그 정리 — mis_id 기준 DELETE."""
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.begin() as conn:  # type: ignore[attr-defined]
            conn.execute(
                text("DELETE FROM misconception_catalog WHERE mis_id = ANY(:ids)"),
                {"ids": mis_ids},
            )
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def _skip_if_unreachable() -> None:
    if not _reachable():
        pytest.skip(
            "PostgreSQL 미도달(또는 마이그레이션 미적용) — 통합 테스트 건너뜀 "
            "(WHYMATH_DATABASE_URL·alembic upgrade head 확인)"
        )


def _mis_row(
    mis_id: str, *, canonical_statement: str = "서수와 기수를 혼동한다."
) -> dict[str, object]:
    """코퍼스 오개념 dict — rename 0(코퍼스 키=schema 필드)."""
    return {
        "mis_id": mis_id,
        "canonical_statement": canonical_statement,
        "student_wrong_thinking": "셀 때 건너뛴다.",
        "distractor_rule": "잘못 처리한 결과를 오답 보기로.",
        "error_type": "순서오류",
        "difficulty": "하",
        "correction_point": "0~100까지 센다.",
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


def _collection(rows: list[dict[str, object]]) -> dict[str, object]:
    return {
        "collected_at": "2026-06-20T00:00:00+00:00",
        "count": len(rows),
        "misconceptions": rows,
    }


class TestRoundtrip:
    """① 적재 → 컬럼 라운드트립(원천 저장·mapping_score Decimal)."""

    def test_populate_creates_row_with_columns(self) -> None:
        _skip_if_unreachable()
        from sqlalchemy import text

        try:
            count = load_misconceptions(None, _collection([_mis_row(_MIS_A)]), settings=Settings())
            assert count == 1

            engine = _sync_engine()
            try:
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    row = conn.execute(
                        text(
                            "SELECT mis_id, canonical_statement, concept_src_id, standard_code, "
                            "error_type, mapping_score FROM misconception_catalog "
                            "WHERE mis_id = :m"
                        ),
                        {"m": _MIS_A},
                    ).one()
                assert row.mis_id == _MIS_A
                assert row.canonical_statement == "서수와 기수를 혼동한다."
                # 느슨참조 원천 저장(해소 없음 — 성취기준 링크 로더와 대비).
                assert row.concept_src_id == "N1"
                assert row.standard_code == "[2수01-01]"
                assert row.error_type == "순서오류"
                # mapping_score는 Numeric(5,3) → Decimal.
                assert isinstance(row.mapping_score, Decimal)
                assert row.mapping_score == Decimal("1.000")
            finally:
                engine.dispose()  # type: ignore[attr-defined]
        finally:
            _cleanup([_MIS_A])


class TestIdempotent:
    """② 멱등 — 재적재 행수 불변·값 갱신."""

    def test_reload_updates_in_place(self) -> None:
        _skip_if_unreachable()
        from sqlalchemy import text

        try:
            load_misconceptions(
                None,
                _collection([_mis_row(_MIS_A, canonical_statement="첫 서술")]),
                settings=Settings(),
            )
            load_misconceptions(
                None,
                _collection([_mis_row(_MIS_A, canonical_statement="둘째 서술")]),
                settings=Settings(),
            )
            engine = _sync_engine()
            try:
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    rows = conn.execute(
                        text(
                            "SELECT mis_id, canonical_statement FROM misconception_catalog "
                            "WHERE mis_id = :m"
                        ),
                        {"m": _MIS_A},
                    ).all()
                assert len(rows) == 1  # 멱등(행 1개)
                assert rows[0].canonical_statement == "둘째 서술"  # 값 갱신
            finally:
                engine.dispose()  # type: ignore[attr-defined]
        finally:
            _cleanup([_MIS_A])

    def test_multi_row_idempotent(self) -> None:
        _skip_if_unreachable()
        from sqlalchemy import text

        try:
            coll = _collection([_mis_row(_MIS_A), _mis_row(_MIS_B)])
            assert load_misconceptions(None, coll, settings=Settings()) == 2
            assert load_misconceptions(None, coll, settings=Settings()) == 2
            engine = _sync_engine()
            try:
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    total = conn.execute(
                        text("SELECT count(*) FROM misconception_catalog WHERE mis_id = ANY(:ids)"),
                        {"ids": [_MIS_A, _MIS_B]},
                    ).scalar_one()
                assert total == 2  # 2회 적재 후에도 2행
            finally:
                engine.dispose()  # type: ignore[attr-defined]
        finally:
            _cleanup([_MIS_A, _MIS_B])


class TestRealCorpusLoad:
    """③ 실 코퍼스(`data/corpus/misconceptions_v1`) 적재 — 코퍼스 전건·멱등(#290 코퍼스 정합).

    합성 행이 아니라 #290이 커밋한 실 Collection JSON을 `load_misconceptions`로 적재해 B.3 로더가
    실 데이터에 서는지 본다(건수는 `docs/data/corpus_facts.md`의 `misconceptions.count`). 정리는 코퍼스 mis_id 전건.
    """

    def test_load_real_corpus_idempotent(self) -> None:
        _skip_if_unreachable()
        import json
        from pathlib import Path

        from sqlalchemy import text

        # 레포 루트 앵커(parents[3]) — CWD 상대 경로는 CI(cwd=src/backend)에서 항상 미존재 skip.
        repo_root = Path(__file__).resolve().parents[3]
        corpus = repo_root / "data" / "corpus" / "misconceptions_v1" / "misconceptions.json"
        if not corpus.exists():
            pytest.skip("실 코퍼스 미존재(data/corpus/misconceptions_v1/misconceptions.json)")
        payload = json.loads(corpus.read_text(encoding="utf-8"))
        mis_ids = [str(m["mis_id"]) for m in payload["misconceptions"]]
        try:
            count = load_misconceptions(None, corpus, settings=Settings())
            assert count == 843  # 극값 MC: 신규 M-id 2건(M0864·M0865) 저작으로 841→843.
            # 재적재 멱등 — 같은 코퍼스 → DB 행수 불변.
            recount = load_misconceptions(None, corpus, settings=Settings())
            assert recount == 843
            engine = _sync_engine()
            try:
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    total = conn.execute(
                        text("SELECT count(*) FROM misconception_catalog WHERE mis_id = ANY(:ids)"),
                        {"ids": mis_ids},
                    ).scalar_one()
                assert total == 843  # 멱등(2회 적재 후에도 843행·극값 MC +2)
            finally:
                engine.dispose()  # type: ignore[attr-defined]
        finally:
            _cleanup(mis_ids)
