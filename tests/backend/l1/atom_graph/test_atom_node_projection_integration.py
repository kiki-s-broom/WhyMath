"""원자 메타 PG 프로젝션 *통합테스트* — 원자 마이그레이션 Phase 2a (WHYMATH_RUN_INTEGRATION·실 PG).

마이그레이션 head 적용 실 PostgreSQL(`atom_node` 테이블)에 원자 코퍼스
(`data/corpus/atom_graph_v1/graph.json`)를 end-to-end 적재한다. CI `backend — 마이그레이션·통합
(실 PG)` 잡이 `alembic upgrade head`(→ `atom_node` 포함) 후 `WHYMATH_RUN_INTEGRATION=1`로
수집·실행한다. PG 미도달 또는 코퍼스 미존재 시 graceful skip(원자 백본 통합테스트 동형).

검증:
  ① 적재 — atom_node 2,683행·level 분포(세부개념1823·소단원643·단원217)
  ② cognitive_type 표본(원자는 개념/절차/표상·단원/소단원은 NULL)
  ③ review_status 전건 'ai_estimated'(원자 메타는 AI 추정·정직 표기)
  ④ redaction — 본문 컬럼(core_proposition·description·formal_definition) 부재(조회 시 오류)
  ⑤ 멱등 — 재적재 시 atom_node 행수 불변
구 437 개념·concept_node(UC 키)와 별개(신규 테이블·additive)를 건드리지 않는다. 정리는 atom_node
code 전건.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from whymath_backend.config import Settings
from whymath_backend.l1.atom_graph.atom_node_projection import (
    load_atom_nodes_from_graph_json,
    populate_atom_nodes,
)

pytestmark = pytest.mark.integration

# 레포 루트 앵커(tests/backend/l1/atom_graph/ → parents[4]) — CWD 상대 경로는 CI(cwd=src/backend)
# 에서 항상 "코퍼스 미존재" skip(침묵 skip 결함 수정).
_CORPUS = Path(__file__).resolve().parents[4] / "data" / "corpus" / "atom_graph_v1" / "graph.json"

# 코퍼스 건수는 손으로 박지 않고 단일 원천의 기계용 사본에서 읽는다(OPS-154).
# 원본이 바뀌면 `python3 scripts/analysis/corpus_facts.py sync`가 이 파일을 갱신한다.
_FACTS = json.loads(
    (Path(__file__).resolve().parents[4] / "docs" / "data" / "corpus_facts.json").read_text(
        encoding="utf-8"
    )
)


def _sync_engine() -> object:
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    settings = Settings()
    url = settings.sync_database_url
    if settings.db_disable_pool:
        return create_engine(url, poolclass=NullPool)
    return create_engine(url)


def _reachable() -> bool:
    """실 PG 도달 + `atom_node` 테이블 존재(마이그레이션 적용) 여부."""
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.connect() as conn:  # type: ignore[attr-defined]
            conn.execute(text("SELECT count(*) FROM atom_node"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def _skip_guard() -> list[str]:
    if not _reachable():
        pytest.skip("PG 미도달 또는 마이그레이션 미적용(atom_node) — 통합 건너뜀")
    if not _CORPUS.exists():
        pytest.skip("원자 코퍼스 미존재(data/corpus/atom_graph_v1/graph.json)")
    payload = json.loads(_CORPUS.read_text(encoding="utf-8"))
    return [str(c["code"]) for c in payload["concepts"]]


def _cleanup(codes: list[str]) -> None:
    """atom_node 적재 행 정리(code 전건). FK 0이라 단순 DELETE."""
    from sqlalchemy import text

    engine = _sync_engine()
    try:
        with engine.begin() as conn:  # type: ignore[attr-defined]
            conn.execute(text("DELETE FROM atom_node WHERE code = ANY(:k)"), {"k": codes})
    finally:
        engine.dispose()  # type: ignore[attr-defined]


class TestAtomNodeProjectionLoad:
    def test_end_to_end_load_idempotent(self) -> None:
        codes = _skip_guard()
        from sqlalchemy import text
        from sqlalchemy.exc import SQLAlchemyError

        try:
            records = load_atom_nodes_from_graph_json(_CORPUS)
            count = populate_atom_nodes(records, settings=Settings())
            # ① 적재 — 원자 노드 전량(name 빈 노드 0).
            assert count == _FACTS["atom_graph.nodes"]

            engine = _sync_engine()
            try:
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    total = conn.execute(
                        text("SELECT count(*) FROM atom_node WHERE code = ANY(:k)"),
                        {"k": codes},
                    ).scalar_one()
                    assert total == _FACTS["atom_graph.nodes"]

                    # ① level 분포(세부개념·소단원·단원 — 사실 파일의 원자·소단원·단원 건수).
                    level_rows = conn.execute(
                        text(
                            "SELECT level, count(*) AS n FROM atom_node "
                            "WHERE code = ANY(:k) GROUP BY level"
                        ),
                        {"k": codes},
                    ).all()
                    by_level = {r.level: r.n for r in level_rows}
                    assert by_level.get("세부개념") == _FACTS["atom_graph.atoms"]
                    assert by_level.get("소단원") == _FACTS["atom_graph.subunits"]
                    assert by_level.get("단원") == _FACTS["atom_graph.units"]

                    # ② cognitive_type 표본 — 세부개념 원자는 인지축 보유.
                    sample = conn.execute(
                        text(
                            "SELECT cognitive_type, node_type, intrinsic_difficulty, "
                            "school_level, subject_area FROM atom_node WHERE code = :c"
                        ),
                        {"c": "2수01-01-2"},
                    ).one()
                    assert sample.cognitive_type == "개념"
                    assert sample.node_type == "구성"
                    assert sample.intrinsic_difficulty == 1
                    assert sample.school_level == "초등"
                    assert sample.subject_area == "수와 연산"

                    # 단원 노드는 인지축·난이도 NULL.
                    unit = conn.execute(
                        text(
                            "SELECT cognitive_type, intrinsic_difficulty "
                            "FROM atom_node WHERE code = :c"
                        ),
                        {"c": "초수연-U1"},
                    ).one()
                    assert unit.cognitive_type is None
                    assert unit.intrinsic_difficulty is None

                    # ③ review_status 전건 'ai_estimated'(원자 메타는 AI 추정).
                    statuses = conn.execute(
                        text("SELECT DISTINCT review_status FROM atom_node WHERE code = ANY(:k)"),
                        {"k": codes},
                    ).all()
                    assert [r.review_status for r in statuses] == ["ai_estimated"]

                    # ④ redaction — 본문 컬럼 부재(존재하면 SELECT가 성공·부재면 ProgrammingError).
                    for col in ("core_proposition", "description", "formal_definition"):
                        with pytest.raises(SQLAlchemyError):
                            with engine.connect() as c2:  # type: ignore[attr-defined]
                                c2.execute(
                                    text(f"SELECT {col} FROM atom_node LIMIT 1")  # noqa: S608
                                )
            finally:
                engine.dispose()  # type: ignore[attr-defined]

            # ⑤ 멱등 — 재적재 후 행수 불변.
            count2 = populate_atom_nodes(records, settings=Settings())
            assert count2 == _FACTS["atom_graph.nodes"]
            engine = _sync_engine()
            try:
                with engine.connect() as conn:  # type: ignore[attr-defined]
                    total2 = conn.execute(
                        text("SELECT count(*) FROM atom_node WHERE code = ANY(:k)"),
                        {"k": codes},
                    ).scalar_one()
                    assert total2 == _FACTS["atom_graph.nodes"]  # 중복 0(멱등)
            finally:
                engine.dispose()  # type: ignore[attr-defined]
        finally:
            _cleanup(codes)
