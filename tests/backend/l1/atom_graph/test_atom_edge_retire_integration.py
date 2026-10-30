"""KG-14 실 PG 통합 — 잔존 엣지 은퇴의 트랜잭션·롤백·CMS 보존을 진짜 DB에서 확인한다.

가짜 엔진 단위 테스트(`test_atom_edge_retire.py`)가 못 보는 것: ① 삭제와 순환 검사가 실제로 같은
트랜잭션이라 실패 시 삭제가 되돌려지는가 ② `DELETE … RETURNING`의 건수 대조가 실 드라이버에서
맞는가 ③ CMS 표지(`cms_edited_at`) 행이 실제로 남는가 ④ plan이 정말 아무것도 쓰지 않는가.

합성 코드(`KG14T-*`)만 쓰고 끝나면 지운다 — 실 코퍼스와 섞이지 않는다.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from whymath_backend.config import Settings
from whymath_backend.l1.atom_graph.atom_edge_retire import RETIRE_APPLY, RETIRE_REPORT
from whymath_backend.l1.atom_graph.populate import (
    plan_atom_edge_retirement,
    populate_atom_backbone,
)
from whymath_backend.l1.concept_graph.prerequisite_guard import PrerequisiteCycleError

pytestmark = pytest.mark.integration

_CODES = [f"KG14T-{x}" for x in "ABCDE"]
A, B, C, D, E = _CODES


def _engine() -> object:
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    return create_engine(Settings().sync_database_url, poolclass=NullPool)


def _cleanup() -> None:
    from sqlalchemy import text

    eng = _engine()
    try:
        with eng.begin() as conn:  # type: ignore[attr-defined]
            ids = "(SELECT concept_id FROM concept WHERE code = ANY(:k))"
            conn.execute(
                text(
                    f"DELETE FROM concept_edge WHERE from_concept_id IN {ids} OR to_concept_id IN {ids}"
                ),
                {"k": _CODES},
            )
            conn.execute(text("DELETE FROM concept WHERE code = ANY(:k)"), {"k": _CODES})
    finally:
        eng.dispose()  # type: ignore[attr-defined]


@pytest.fixture()
def clean_db() -> Iterator[None]:
    from sqlalchemy import text

    eng = _engine()
    try:
        with eng.connect() as conn:  # type: ignore[attr-defined]
            has_marker = conn.execute(
                text(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_name = 'concept_edge' AND column_name = 'cms_edited_at'"
                )
            ).scalar_one()
    except Exception as exc:  # noqa: BLE001 — 도달 실패는 skip 사유(타입명 남김)
        pytest.skip(f"PG 미도달 — 통합 건너뜀 ({type(exc).__name__})")
    finally:
        eng.dispose()  # type: ignore[attr-defined]
    if not has_marker:
        pytest.skip("스키마가 head가 아니다(concept_edge.cms_edited_at 부재)")
    _cleanup()
    yield
    _cleanup()


def _graph(tmp_path: Path, name: str, edges: list[tuple[str, str]]) -> Path:
    path = tmp_path / name
    path.write_text(
        json.dumps(
            {
                "concepts": [
                    {"code": c, "name": f"KG14 시험 {c}", "level": "세부개념", "parent_code": None}
                    for c in _CODES
                ],
                "edges": [
                    {
                        "from_code": a,
                        "to_code": b,
                        "relation": "prerequisite",
                        "relation_subtype": "원본",
                    }
                    for a, b in edges
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def _db_pairs() -> set[tuple[str, str]]:
    from sqlalchemy import text

    eng = _engine()
    try:
        with eng.connect() as conn:  # type: ignore[attr-defined]
            rows = conn.execute(
                text(
                    "SELECT cf.code, ct.code FROM concept_edge e "
                    "JOIN concept cf ON cf.concept_id = e.from_concept_id "
                    "JOIN concept ct ON ct.concept_id = e.to_concept_id "
                    "WHERE cf.code = ANY(:k) AND ct.code = ANY(:k)"
                ),
                {"k": _CODES},
            ).all()
    finally:
        eng.dispose()  # type: ignore[attr-defined]
    return {(r[0], r[1]) for r in rows}


def _add_cms_edge(a: str, b: str) -> None:
    from sqlalchemy import text

    eng = _engine()
    try:
        with eng.begin() as conn:  # type: ignore[attr-defined]
            conn.execute(
                text(
                    "INSERT INTO concept_edge (from_concept_id, to_concept_id, edge_type, cms_edited_at) "
                    "SELECT f.concept_id, t.concept_id, 'PREREQUISITE', now() "
                    "FROM concept f, concept t WHERE f.code = :a AND t.code = :b"
                ),
                {"a": a, "b": b},
            )
    finally:
        eng.dispose()  # type: ignore[attr-defined]


def _load(graph: Path, mode: str = RETIRE_REPORT) -> object:
    return populate_atom_backbone(graph, settings=Settings(), retire_mode=mode)


V1 = [(A, B), (B, C), (C, D)]
V2 = [(A, B), (C, B), (A, C)]  # B→C 뒤집힘 · C→D 삭제 · A→C 추가


@pytest.mark.usefixtures("clean_db")
class TestRetireOnRealPostgres:
    def test_report_is_refused_plan_writes_nothing_apply_converges(self, tmp_path: Path) -> None:
        _load(_graph(tmp_path, "v1.json", V1))
        _add_cms_edge(A, E)  # 범위 안·정본 밖이지만 CMS 소유 → 지켜야 한다
        before = _db_pairs()
        assert before == set(V1) | {(A, E)}

        v2 = _graph(tmp_path, "v2.json", V2)
        # ① 종전 동작: 옛 방향 B→C가 남아 정본 C→B와 순환 → 엣지 적재 거부 · DB 엣지 무변화
        with pytest.raises(PrerequisiteCycleError):
            _load(v2, RETIRE_REPORT)
        assert _db_pairs() == before

        # ② plan: 지울 목록·두 순환 판정 · 아무것도 쓰지 않는다
        planned = plan_atom_edge_retirement(v2, settings=Settings())
        assert {r.pair for r in planned.plan.stale} == {(B, C), (C, D)}
        assert {r.pair for r in planned.plan.cms_kept} == {(A, E)}
        assert planned.cycle_without_retire is not None
        assert planned.cycle_after_retire is None
        assert _db_pairs() == before

        # ③ apply: 같은 트랜잭션에서 은퇴 → 순환 검사 통과 → upsert · CMS 행은 남는다
        report = _load(v2, RETIRE_APPLY)
        assert (report.stale_edges_found, report.edges_retired, report.stale_cms_kept) == (2, 2, 1)  # type: ignore[attr-defined]
        assert _db_pairs() == set(V2) | {(A, E)}

        # ④ 멱등: 다시 적용하면 지울 것이 없다
        again = _load(v2, RETIRE_APPLY)
        assert (again.stale_edges_found, again.edges_retired) == (0, 0)  # type: ignore[attr-defined]
        assert _db_pairs() == set(V2) | {(A, E)}

    def test_a_cycle_that_retirement_cannot_fix_rolls_the_deletes_back(
        self, tmp_path: Path
    ) -> None:
        _load(_graph(tmp_path, "v1.json", V1))
        _add_cms_edge(E, B)  # CMS 소유 E→B
        before = _db_pairs()
        v3 = _graph(tmp_path, "v3.json", [(A, B), (C, B), (B, E)])  # 정본 B→E + CMS E→B = 순환
        planned = plan_atom_edge_retirement(v3, settings=Settings())
        assert planned.plan.stale and planned.cycle_after_retire is not None
        with pytest.raises(PrerequisiteCycleError):
            _load(v3, RETIRE_APPLY)
        # 삭제가 순환 검사와 같은 트랜잭션이었으므로 B→C·C→D는 되돌려져 그대로 있다
        assert _db_pairs() == before
