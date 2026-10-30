"""개념 그래프 쓰기 규칙 — 선수 엣지의 비순환 검사와 개념·엣지 삭제 가능 판정 (P3-26).

관리자 CMS(`api/admin_cms_graph.py`)와 기존 개념 삭제 라우트(`api/concepts.py`)가 **같은 규칙**을
쓰도록 한곳에 둔다 — 두 라우트가 따로 판정하면 한쪽이 우회로가 된다. 규약 정본:
`docs/standards/cms_concept_graph_write_contract.md`.

## 이 모듈이 지키는 것

- **비순환(DAG)**: 선수 엣지 `A→B`("A를 알아야 B를 안다")를 더하면 `B`에서 선수 방향으로 `A`에
  닿을 수 있는지 본다(Reachability Check — 구축 플레이북 12-3). 닿으면 순환이라 거부한다.
  검사와 쓰기 사이 틈을 막으려고 **어드바이저리 잠금**을 잡은 트랜잭션 안에서 검사한다.
  적재 CLI도 같은 키(`PREREQUISITE_GRAPH_LOCK_KEY`)를 쓴다.
- **행 단위 소유권**: `cms_edited_at`이 NULL인 행은 graph.json 적재가 소유한다 — 파일이 되살리므로
  CMS는 지우지 않는다. 값이 있는 행은 CMS가 만든 행이라 DB가 정본이다.
- **삭제 가능 판정**: 개념은 CMS가 만들었고, 발행본이 없고, 엣지·자식이 없을 때만 지운다.

DB 접근은 ORM/쿼리 빌더만 쓴다(원시 SQL은 잠금 호출 1건). `ConceptVersion` ORM은 import하지 않는다
(AST 동결 R1) — 판 상태는 `publish_gate`가 읽어 준다.
"""

from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.cms_edit_marker import PREREQUISITE_GRAPH_LOCK_KEY
from whymath_backend.db.models.concept import Concept, ConceptEdge
from whymath_backend.l3 import publish_gate as gate
from whymath_backend.schema.enums import EdgeType
from whymath_backend.schema.learning_loop_contract import reachable_from


@dataclass(frozen=True, slots=True)
class WriteBlock:
    """쓰기를 막는 사유 1건 — `code`는 화면이 분기하는 안정 식별자, `message`는 사람이 읽는 문장."""

    code: str
    message: str
    extra: dict[str, object] = field(default_factory=dict)


async def lock_prerequisite_graph(session: AsyncSession) -> None:
    """선수 그래프 쓰기를 직렬화한다(트랜잭션 수명 어드바이저리 잠금). 검사 **전에** 부른다."""
    await session.execute(
        sa.text("SELECT pg_advisory_xact_lock(:key)"), {"key": PREREQUISITE_GRAPH_LOCK_KEY}
    )


async def find_cycle_if_added(
    session: AsyncSession, from_id: uuid.UUID, to_id: uuid.UUID
) -> list[uuid.UUID] | None:
    """선수 엣지 `from→to`를 더하면 생기는 순환의 경로를 돌려준다(없으면 None).

    경로는 `[from, to, …, from]`처럼 **닫힘 노드를 반복**해 사람이 어디를 끊을지 바로 알게 한다.
    DB에 저장된 모든 선수 엣지를 읽는다(수천 건 규모 — 요청당 한 번의 단순 조회. 원자 백본 규모는
    `docs/data/corpus_facts.md`의 `atom_graph.edges`).
    """
    rows = (
        await session.execute(
            select(ConceptEdge.from_concept_id, ConceptEdge.to_concept_id).where(
                ConceptEdge.edge_type == EdgeType.PREREQUISITE
            )
        )
    ).all()
    pairs = [(str(a), str(b)) for a, b in rows]
    if str(from_id) not in reachable_from(str(to_id), pairs):
        return None
    # 순환이 확정됐으니 `to`에서 `from`까지의 경로를 BFS로 복원한다(visited로 멈춤을 보장).
    adjacency: dict[str, list[str]] = {}
    for prerequisite, dependent in pairs:
        adjacency.setdefault(prerequisite, []).append(dependent)
    start, goal = str(to_id), str(from_id)
    parent: dict[str, str | None] = {start: None}
    queue: deque[str] = deque([start])
    while queue:
        node = queue.popleft()
        if node == goal:
            break
        for nxt in adjacency.get(node, ()):
            if nxt not in parent:
                parent[nxt] = node
                queue.append(nxt)
    chain: list[str] = []
    cursor: str | None = goal
    while cursor is not None:
        chain.append(cursor)
        cursor = parent.get(cursor)
    chain.reverse()  # to … from
    return [from_id, *(uuid.UUID(node) for node in chain)]


async def concept_codes(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """개념 UUID → 코드. 경로를 사람이 읽는 문장으로 바꿀 때만 쓴다."""
    if not ids:
        return {}
    rows = (
        await session.execute(
            select(Concept.concept_id, Concept.code).where(Concept.concept_id.in_(set(ids)))
        )
    ).all()
    return {cid: code for cid, code in rows}


def edge_delete_block(edge: ConceptEdge) -> WriteBlock | None:
    """CMS가 이 엣지를 지울 수 있는가. 적재가 소유한 엣지(표지 없음)는 파일이 되살리므로 거부."""
    if edge.cms_edited_at is None:
        return WriteBlock(
            "file_owned",
            "이 관계는 graph.json(원천 파일)이 정본이라 CMS에서 지울 수 없습니다. 파일에서 고친 뒤 "
            "다시 적재해야 합니다(그렇지 않으면 다음 적재가 되살립니다).",
        )
    return None


async def concept_delete_block(session: AsyncSession, concept: Concept) -> WriteBlock | None:
    """개념 행을 지워도 되는가. 허용하는 것은 **CMS가 만들었고 더는 쓰이지 않는 개념**뿐이다.

    판정 순서(앞이 우선): 적재 소유 → 발행본 있음 → 관계 있음 → 자식 있음. 그 밖의 참조(학습 기록·
    문항 연결 등)는 DB 외래키가 마지막 방어선이다 — 호출자가 `IntegrityError`를 409로 바꾼다.
    """
    if concept.cms_edited_at is None:
        return WriteBlock(
            "file_owned",
            "이 개념은 graph.json(원천 파일)이 정본이라 CMS에서 지울 수 없습니다. "
            "지워도 다음 적재가 되살립니다 — 파일에서 제거해야 합니다.",
        )
    if concept.current_published_version_id is not None or await gate.has_published_version(
        session, concept.code
    ):
        return WriteBlock(
            "has_published_version",
            "발행본이 있는 개념은 지울 수 없습니다. 먼저 발행본을 폐기(deprecate)하세요.",
        )
    edge_count = (
        await session.execute(
            select(func.count())
            .select_from(ConceptEdge)
            .where(
                sa.or_(
                    ConceptEdge.from_concept_id == concept.concept_id,
                    ConceptEdge.to_concept_id == concept.concept_id,
                )
            )
        )
    ).scalar_one()
    if edge_count:
        return WriteBlock(
            "has_edges",
            f"이 개념에 연결된 관계가 {int(edge_count)}건 있습니다. 관계를 먼저 지우세요.",
            {"edge_count": int(edge_count)},
        )
    child_count = (
        await session.execute(
            select(func.count())
            .select_from(Concept)
            .where(Concept.parent_concept_id == concept.concept_id)
        )
    ).scalar_one()
    if child_count:
        return WriteBlock(
            "has_children",
            f"이 개념을 부모로 삼는 하위 개념이 {int(child_count)}건 있습니다.",
            {"child_count": int(child_count)},
        )
    return None


__all__ = [
    "WriteBlock",
    "concept_codes",
    "concept_delete_block",
    "edge_delete_block",
    "find_cycle_if_added",
    "lock_prerequisite_graph",
]
