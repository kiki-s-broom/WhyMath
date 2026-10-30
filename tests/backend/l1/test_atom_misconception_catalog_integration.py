"""atom ①오개념 → misconception_catalog 승격 *통합테스트* — Slice 2 (WHYMATH_RUN_INTEGRATION).

마이그레이션 head가 적용된 **실 PostgreSQL**(`misconception_catalog` 테이블·기존 테이블 재사용·신규
마이그레이션 0)에 atom 백본 코퍼스(`data/corpus/atom_graph_v1/graph.json`)의 원자 ①오개념을
end-to-end 적재한다. CI `backend — 마이그레이션·통합 (실 PG)` 잡이 `alembic upgrade head`
(→ `misconception_catalog` 포함) 후 `tests/backend/l1/`를 수집·실행한다(신규 CI 잡 불요). PG 미도달
또는 코퍼스 미존재 시 graceful skip(misconception 로더 통합테스트 동형).

검증:
  ① 실 코퍼스 적재 — atom ①오개념 1,823행(mis_id 'ATOM:' 접두)·전건 적재
  ② 멱등 — 재적재 시 행수·접두 행수 불변
  ③ 표본 행 — canonical_statement·error_type·concept_src_id(원자 code)·provenance 라운드트립
  ④ 네임스페이스 분리 — 'ATOM:' 접두 행은 모두 provenance 'atom_graph_v1'(구 카탈로그 misconceptions_v1과 무충돌)
정리는 `mis_id LIKE 'ATOM:%'` 전건(구 misconceptions_v1 행을 건드리지 않는다 — additive 병존).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from whymath_backend.config import Settings
from whymath_backend.l1.misconception.atom_catalog import (
    ATOM_MIS_ID_PREFIX,
    ATOM_PROVENANCE_NOTE,
    atom_misconception_rows,
    load_atom_misconceptions,
)

pytestmark = pytest.mark.integration

# 레포 루트 앵커(tests/backend/l1/ → parents[3]) — CWD 상대 경로는 CI·로컬 관례(cwd=src/backend)
# 에서 항상 "코퍼스 미존재" skip이 되어 적재 검증이 한 번도 실행되지 않았다(침묵 skip 결함 수정).
_CORPUS = Path(__file__).resolve().parents[3] / "data" / "corpus" / "atom_graph_v1" / "graph.json"
# atom ①오개념 전건(원자 1,823 전량이 misconception 보유 — Phase 1 산출 정합).
# 코퍼스 건수는 손으로 박지 않고 단일 원천의 기계용 사본에서 읽는다(OPS-154).
# 원본이 바뀌면 `python3 scripts/analysis/corpus_facts.py sync`가 이 파일을 갱신한다.
_FACTS = json.loads(
    (Path(__file__).resolve().parents[3] / "docs" / "data" / "corpus_facts.json").read_text(
        encoding="utf-8"
    )
)
_EXPECTED_ROWS = _FACTS["atom_graph.atoms"]


def _sync_engine() -> object:
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


def _cleanup() -> None:
    """atom 출처 행 정리 — 'ATOM:' 접두 전건(구 misconceptions_v1은 비접두라 무관)."""
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.begin() as conn:  # type: ignore[attr-defined]
            conn.execute(
                text("DELETE FROM misconception_catalog WHERE mis_id LIKE :p"),
                {"p": f"{ATOM_MIS_ID_PREFIX}%"},
            )
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def _skip_guard() -> None:
    if not _reachable():
        pytest.skip(
            "PostgreSQL 미도달(또는 마이그레이션 미적용) — 통합 테스트 건너뜀 "
            "(WHYMATH_DATABASE_URL·alembic upgrade head 확인)"
        )
    if not _CORPUS.exists():
        pytest.skip("atom 코퍼스 미존재(data/corpus/atom_graph_v1/graph.json)")


class TestRealCorpusLoad:
    """① 실 코퍼스 적재 1,823행 ②멱등 ③표본 라운드트립 ④네임스페이스 분리."""

    def test_load_real_corpus_idempotent(self) -> None:
        _skip_guard()
        from sqlalchemy import text

        try:
            # ① 적재 — atom ①오개념 전건(1,823).
            count = load_atom_misconceptions(_CORPUS, settings=Settings())
            assert count == _EXPECTED_ROWS

            engine = _sync_engine()
            try:
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    total = conn.execute(
                        text("SELECT count(*) FROM misconception_catalog WHERE mis_id LIKE :p"),
                        {"p": f"{ATOM_MIS_ID_PREFIX}%"},
                    ).scalar_one()
                    assert total == _EXPECTED_ROWS

                    # ③ 표본 행 — 첫 투영 행이 DB에 라운드트립(본문·유형·느슨참조·출처).
                    sample_row = atom_misconception_rows(_CORPUS)[0]
                    db = conn.execute(
                        text(
                            "SELECT canonical_statement, error_type, concept_src_id, "
                            "provenance_note FROM misconception_catalog WHERE mis_id = :m"
                        ),
                        {"m": sample_row["mis_id"]},
                    ).one()
                    assert db.canonical_statement == sample_row["canonical_statement"]
                    assert db.error_type == sample_row["error_type"]
                    assert db.concept_src_id == sample_row["concept_src_id"]
                    assert db.provenance_note == ATOM_PROVENANCE_NOTE

                    # ④ 네임스페이스 분리 — 접두 행은 전부 atom 출처(구 카탈로그 misconceptions_v1과 무충돌).
                    provs = conn.execute(
                        text(
                            "SELECT DISTINCT provenance_note FROM misconception_catalog "
                            "WHERE mis_id LIKE :p"
                        ),
                        {"p": f"{ATOM_MIS_ID_PREFIX}%"},
                    ).all()
                    assert [r.provenance_note for r in provs] == [ATOM_PROVENANCE_NOTE]
            finally:
                engine.dispose()  # type: ignore[attr-defined]

            # ② 멱등 — 재적재 후 접두 행수 불변.
            recount = load_atom_misconceptions(_CORPUS, settings=Settings())
            assert recount == _EXPECTED_ROWS
            engine = _sync_engine()
            try:
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    total2 = conn.execute(
                        text("SELECT count(*) FROM misconception_catalog WHERE mis_id LIKE :p"),
                        {"p": f"{ATOM_MIS_ID_PREFIX}%"},
                    ).scalar_one()
                    assert total2 == _EXPECTED_ROWS  # 중복 0(멱등)
            finally:
                engine.dispose()  # type: ignore[attr-defined]
        finally:
            _cleanup()
