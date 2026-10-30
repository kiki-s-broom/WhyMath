"""원자 ②진단문항·③소크라테스 → atom_probe 승격 *통합테스트* — Slice 3 (WHYMATH_RUN_INTEGRATION).

마이그레이션 head가 적용된 **실 PostgreSQL**(`atom_probe` 테이블·신규 마이그레이션 `b9c0d1e2f3a4`)에
atom 백본 코퍼스(`data/corpus/atom_graph_v1/graph.json`)의 원자 ②진단문항·③소크라테스를 end-to-end
적재한다. CI `backend — 마이그레이션·통합 (실 PG)` 잡이 `alembic upgrade head`(→ `atom_probe` 포함)
후 `tests/backend/l1/`를 수집·실행한다(신규 CI 잡 불요). PG 미도달 또는 코퍼스 미존재 시 graceful
skip(misconception/concept_content 로더 통합테스트 동형).

검증:
  ① 실 코퍼스 적재 — 원자 1,823행(②③ 전건)·전건 적재
  ② 멱등 — 재적재 시 행수 불변
  ③ 표본 행 — diagnostic_item/answer/signal·socratic_question·난이도·review_status 라운드트립
  ④ review_status — 전 행 'ai_estimated'(정직 표기)
정리는 `atom_probe` 전건(atom 전용 테이블·다른 테이블 무관).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from whymath_backend.config import Settings
from whymath_backend.db.models.atom_probe import ATOM_PROBE_REVIEW_STATUS_AI_ESTIMATED
from whymath_backend.l1.atom_probe.projection import (
    load_atom_probes_from_json,
    populate_atom_probes,
)

pytestmark = pytest.mark.integration

# 레포 루트 앵커(tests/backend/l1/ → parents[3]) — CWD 상대 경로는 CI(cwd=src/backend)에서 항상
# "코퍼스 미존재" skip(침묵 skip 결함 수정).
_CORPUS = Path(__file__).resolve().parents[3] / "data" / "corpus" / "atom_graph_v1" / "graph.json"
# 원자 ②③ 전건(원자 1,823 전량이 진단문항·소크라테스 보유 — Phase 1 산출 정합).
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
    """실 PG 도달 + `atom_probe` 테이블 존재(마이그레이션 적용) 여부."""
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.connect() as conn:  # type: ignore[attr-defined]
            conn.execute(text("SELECT count(*) FROM atom_probe"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def _cleanup() -> None:
    """atom_probe 전건 정리 — atom 백본 전용 테이블이라 다른 데이터 무관."""
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.begin() as conn:  # type: ignore[attr-defined]
            conn.execute(text("DELETE FROM atom_probe"))
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


def _load() -> int:
    """코퍼스 → atom_probe 멱등 적재(load + populate 결선) — 반환 적재 행 수."""
    records = load_atom_probes_from_json(_CORPUS)
    return populate_atom_probes(records, settings=Settings())


class TestRealCorpusLoad:
    """① 실 코퍼스 적재 1,823행 ②멱등 ③표본 라운드트립 ④review_status 상수."""

    def test_load_real_corpus_idempotent(self) -> None:
        _skip_guard()
        from sqlalchemy import text

        try:
            # ① 적재 — 원자 ②③ 전건(1,823).
            count = _load()
            assert count == _EXPECTED_ROWS

            engine = _sync_engine()
            try:
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    total = conn.execute(text("SELECT count(*) FROM atom_probe")).scalar_one()
                    assert total == _EXPECTED_ROWS

                    # ③ 표본 행 — 첫 투영 레코드가 DB에 라운드트립(②3필드·③·난이도·review).
                    sample = load_atom_probes_from_json(_CORPUS)[0]
                    db = conn.execute(
                        text(
                            "SELECT diagnostic_item, diagnostic_answer, diagnostic_signal, "
                            "socratic_question, intrinsic_difficulty, review_status "
                            "FROM atom_probe WHERE code = :c"
                        ),
                        {"c": sample.code},
                    ).one()
                    assert db.diagnostic_item == sample.diagnostic_item
                    assert db.diagnostic_answer == sample.diagnostic_answer
                    assert db.diagnostic_signal == sample.diagnostic_signal
                    assert db.socratic_question == sample.socratic_question
                    assert db.intrinsic_difficulty == sample.intrinsic_difficulty
                    assert db.review_status == ATOM_PROBE_REVIEW_STATUS_AI_ESTIMATED

                    # ④ review_status — 전 행 'ai_estimated'(정직 표기·검수 게이팅).
                    statuses = conn.execute(
                        text("SELECT DISTINCT review_status FROM atom_probe")
                    ).all()
                    assert [r.review_status for r in statuses] == [
                        ATOM_PROBE_REVIEW_STATUS_AI_ESTIMATED
                    ]
            finally:
                engine.dispose()  # type: ignore[attr-defined]

            # ② 멱등 — 재적재 후 행수 불변(중복 0).
            recount = _load()
            assert recount == _EXPECTED_ROWS
            engine = _sync_engine()
            try:
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    total2 = conn.execute(text("SELECT count(*) FROM atom_probe")).scalar_one()
                    assert total2 == _EXPECTED_ROWS
            finally:
                engine.dispose()  # type: ignore[attr-defined]
        finally:
            _cleanup()
