"""원자 백본 → backend `concept`/`concept_edge` *통합테스트*(WHYMATH_RUN_INTEGRATION·실 PG).

마이그레이션 head 적용 실 PostgreSQL에 원자 코퍼스(`data/corpus/atom_graph_v1/graph.json`)를
end-to-end 적재한다. CI `backend — 마이그레이션·통합 (실 PG)` 잡이 `alembic upgrade head`(→
`concept_edge.relation_subtype` 포함) 후 `WHYMATH_RUN_INTEGRATION=1`로 수집·실행한다. PG 미도달
또는 코퍼스 미존재 시 graceful skip.

검증:
  ① 적재 — concepts 2,683(원자1823·단원217·소단원643)·edges 2,234(orphan 0 기대 · 2,210 + S4-60 고→대 24)
  ② parent 위계 — 원자→소단원→단원 체인(2수01-01-2 → 초수연-U1-S1 → 초수연-U1)
  ③ relation_subtype 적재(관계유형)·edge 방향(from=선수)
  ④ redaction — 본문 컬럼(description·formal_definition)은 Phase 1b에서 물리 제거(컬럼 부재)
  ⑤ 멱등 — 재적재 시 concept/edge 행수 불변
구 437 개념과 병존(code 공간 무충돌)을 건드리지 않는다. 정리는 원자 code 전건(FK 안전 순서).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from whymath_backend.config import Settings
from whymath_backend.l1.atom_graph.populate import populate_atom_backbone

pytestmark = pytest.mark.integration

# 레포 루트 앵커(tests/backend/l1/atom_graph/ → parents[4]) — CWD 상대 경로는 CI(cwd=src/backend)
# 에서 항상 "코퍼스 미존재" skip(침묵 skip 결함 수정).
_CORPUS = Path(__file__).resolve().parents[4] / "data" / "corpus" / "atom_graph_v1" / "graph.json"


def _sync_engine() -> object:
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    settings = Settings()
    url = settings.sync_database_url
    if settings.db_disable_pool:
        return create_engine(url, poolclass=NullPool)
    return create_engine(url)


def _reachable() -> bool:
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.connect() as conn:  # type: ignore[attr-defined]
            # relation_subtype 컬럼 존재(마이그레이션 적용) 동시 확인.
            conn.execute(text("SELECT relation_subtype FROM concept_edge LIMIT 1"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def _skip_guard() -> list[str]:
    if not _reachable():
        pytest.skip("PG 미도달 또는 마이그레이션 미적용(relation_subtype) — 통합 건너뜀")
    if not _CORPUS.exists():
        pytest.skip("원자 코퍼스 미존재(data/corpus/atom_graph_v1/graph.json)")
    payload = json.loads(_CORPUS.read_text(encoding="utf-8"))
    return [str(c["code"]) for c in payload["concepts"]]


def _cleanup(codes: list[str]) -> None:
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.begin() as conn:  # type: ignore[attr-defined]
            conn.execute(
                text(
                    "DELETE FROM concept_edge WHERE from_concept_id IN "
                    "(SELECT concept_id FROM concept WHERE code = ANY(:k)) "
                    "OR to_concept_id IN "
                    "(SELECT concept_id FROM concept WHERE code = ANY(:k))"
                ),
                {"k": codes},
            )
            conn.execute(text("DELETE FROM concept WHERE code = ANY(:k)"), {"k": codes})
    finally:
        engine.dispose()  # type: ignore[attr-defined]


class TestAtomBackboneLoad:
    def test_end_to_end_load_idempotent(self) -> None:
        codes = _skip_guard()
        from sqlalchemy import text

        try:
            report = populate_atom_backbone(_CORPUS, settings=Settings())
            # ① 적재 — concepts 2,683·edges 2,234(orphan 0 기대 · 2,210 + S4-60 고→대 24).
            assert report.concepts_loaded == 2683
            assert report.edges_loaded == 2234
            assert report.edges_skipped == 0
            assert report.parents_skipped == 0

            engine = _sync_engine()
            try:
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    # ② parent 위계 체인 — 원자 → 소단원 → 단원.
                    chain = conn.execute(
                        text(
                            "SELECT a.code AS atom, su.code AS subunit, u.code AS unit, "
                            "a.level AS atom_level "
                            "FROM concept a "
                            "JOIN concept su ON a.parent_concept_id = su.concept_id "
                            "JOIN concept u ON su.parent_concept_id = u.concept_id "
                            "WHERE a.code = :c"
                        ),
                        {"c": "2수01-01-2"},
                    ).one()
                    assert chain.subunit == "초수연-U1-S1"
                    assert chain.unit == "초수연-U1"
                    assert chain.atom_level == "세부개념"
                    # ④ redaction — 본문 컬럼(description·formal_definition)은 Phase 1b에서
                    # *물리 제거*됐다(NULL 아님·컬럼 부재). 재등장하면 redaction 회귀 →
                    # 컬럼 부재를 단언한다(구 SELECT a.description은 컬럼 제거로 UndefinedColumn).
                    redacted_cols = (
                        conn.execute(
                            text(
                                "SELECT column_name FROM information_schema.columns "
                                "WHERE table_name = 'concept' "
                                "AND column_name IN ('description', 'formal_definition')"
                            )
                        )
                        .scalars()
                        .all()
                    )
                    assert redacted_cols == []

                    # ③ relation_subtype 적재(관계유형 비어있지 않은 엣지 존재).
                    subtype_count = conn.execute(
                        text(
                            "SELECT count(*) FROM concept_edge "
                            "WHERE relation_subtype IS NOT NULL"
                        )
                    ).scalar_one()
                    assert subtype_count > 0

                    # 노드 레벨 분포(원자 code 전건 기준).
                    level_rows = conn.execute(
                        text(
                            "SELECT level, count(*) AS n FROM concept "
                            "WHERE code = ANY(:k) GROUP BY level"
                        ),
                        {"k": codes},
                    ).all()
                    by_level = {r.level: r.n for r in level_rows}
                    assert by_level.get("세부개념") == 1823
                    assert by_level.get("소단원") == 643
                    assert by_level.get("단원") == 217
            finally:
                engine.dispose()  # type: ignore[attr-defined]

            # ⑤ 멱등 — 재적재 후 행수 불변.
            report2 = populate_atom_backbone(_CORPUS, settings=Settings())
            assert report2.concepts_loaded == 2683
            assert report2.edges_loaded == 2234
            engine = _sync_engine()
            try:
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    total_nodes = conn.execute(
                        text("SELECT count(*) FROM concept WHERE code = ANY(:k)"),
                        {"k": codes},
                    ).scalar_one()
                    assert total_nodes == 2683  # 중복 0(멱등)
            finally:
                engine.dispose()  # type: ignore[attr-defined]
        finally:
            _cleanup(codes)
