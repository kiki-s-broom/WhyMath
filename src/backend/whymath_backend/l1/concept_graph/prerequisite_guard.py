"""선수 엣지 적재의 DB 인지 순환 방어 — CMS 관계와 파일 관계가 합쳐져 순환하는 것을 막는다 (P3-26).

## 왜 적재기의 기존 순환 검사로 부족한가

`atom_graph/populate.py`의 `_find_prerequisite_cycle_in_records`는 **graph.json의 엣지만** 본다.
그런데
CMS가 선수 관계를 DB에 직접 쓰게 되면(`api/admin_cms_graph.py`) DB에는 파일에 없는 엣지가 생긴다.
파일이 `B→A`를 새로 더하고 DB에 CMS가 만든 `A→B`가 있으면 **각각은 비순환이지만 합치면 순환**이다.
파일만 보는 검사는 이것을 통과시키고, 적재가 DB에 순환을 심는다.

## 이 모듈이 하는 일

적재 트랜잭션 안에서 ① CMS와 **같은 어드바이저리 잠금**을 잡고(`PREREQUISITE_GRAPH_LOCK_KEY` — 동시
쓰기 직렬화) ② DB에 이미 있는 모든 선수 엣지에 이번 적재분을 합쳐 순환을 찾고 ③ 있으면
`PrerequisiteCycleError`로 **쓰기 전에** 거부한다(트랜잭션이 롤백돼 부분 적재 없음).

DB 전체를 읽는 이유: 적재기는 기본으로 삭제하지 않으므로 파일에서 사라진 옛 엣지도 DB에 남아 있고,
그것도 순환의 재료가 될 수 있다. 원자 백본 적재는 `--retire-stale-edges apply`(KG-14 ·
`atom_graph/atom_edge_retire.py`)로 그 옛 엣지를 같은 트랜잭션에서 먼저 지운 뒤 이 검사를 부른다.
수천 건 규모라(원자 백본은 `docs/data/corpus_facts.md`의 `atom_graph.edges`) 비용은 무시할 수 있다.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from whymath_backend.db.cms_edit_marker import PREREQUISITE_GRAPH_LOCK_KEY
from whymath_backend.schema.enums import EdgeType
from whymath_backend.schema.learning_loop_contract import find_prerequisite_cycle

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection


class PrerequisiteCycleError(ValueError):
    """선수엣지에 순환이 있어 적재를 거부한다 — 학습 경로 구성 불가.

    `cycle`은 순환 경로(닫힘 노드 반복 포함)다. 가능하면 개념 **코드**로 담는다(사람이 읽는다).
    """

    def __init__(self, cycle: list[str]) -> None:
        self.cycle = cycle
        super().__init__("순환 선수관계로 적재 거부 — 학습 경로 구성 불가: " + " → ".join(cycle))


def lock_prerequisite_graph_sync(conn: Connection) -> None:
    """선수 그래프 쓰기 직렬화 — CMS API의 `lock_prerequisite_graph`와 같은 키."""
    from sqlalchemy import text

    conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": PREREQUISITE_GRAPH_LOCK_KEY})


def assert_acyclic_with_db(
    conn: Connection,
    incoming: Sequence[tuple[uuid.UUID, uuid.UUID]],
    code_of: Mapping[uuid.UUID, str],
) -> None:
    """DB의 모든 선수 엣지 ∪ `incoming`에 순환이 있으면 `PrerequisiteCycleError`.

    `incoming`은 이번에 쓸 `(선수, 후행)` UUID 쌍. `code_of`는 오류 메시지용 UUID→코드 맵(없는
    노드는
    UUID 문자열로 표기). 호출자가 이미 `lock_prerequisite_graph_sync`를 부른 트랜잭션 안이어야 한다.
    """
    from sqlalchemy import select

    from whymath_backend.db.models.concept import ConceptEdge

    existing = conn.execute(
        select(ConceptEdge.from_concept_id, ConceptEdge.to_concept_id).where(
            ConceptEdge.edge_type == EdgeType.PREREQUISITE
        )
    ).all()
    pairs = {(str(a), str(b)) for a, b in existing}
    pairs.update((str(a), str(b)) for a, b in incoming)
    cycle = find_prerequisite_cycle(sorted(pairs))
    if cycle is None:
        return
    names = {str(k): v for k, v in code_of.items()}
    raise PrerequisiteCycleError([names.get(node, node) for node in cycle])


__all__ = ["PrerequisiteCycleError", "assert_acyclic_with_db", "lock_prerequisite_graph_sync"]
