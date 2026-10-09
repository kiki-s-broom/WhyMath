"""atom ①오개념 → backend 적재 CLI — `whymath_backend.l1.misconception.populate_atom`.

Phase 1 산출 atom 백본 코퍼스(`data/corpus/atom_graph_v1/graph.json`)의 원자 ①오개념(1,837 원자)을
backend 영속 `misconception_catalog` 테이블에 멱등 적재한다. `populate.py`(misconceptions_v1 적재
CLI)의 *원자 짝*이며 같은 CLI 골격을 따른다(argparse·`main(argv)->int`·파일 부재 `return 2`·stdout
행수 보고). 오개념은 임베딩·pgvector와 무관(순수 RDB sync 적재)하므로 vector_store 게이트가 없다.

적재 로직 0(얇은 래퍼): `load_atom_misconceptions`(atom_catalog)가 graph.json 투영·기존
`load_misconceptions` 위임(검증·멱등 upsert)을 담당한다. 본 CLI는 경로 결선·실행·보고만 한다.

사용:
    python -m whymath_backend.l1.misconception.populate_atom \\
        --graph data/corpus/atom_graph_v1/graph.json
"""

from __future__ import annotations

import argparse
from pathlib import Path

from whymath_backend.db.cms_edit_marker import add_overwrite_argument, conflict_summary
from whymath_backend.l1.misconception.atom_catalog import load_atom_misconceptions

# atom 백본 코퍼스 기본 경로(Phase 1 산출 관례).
_DEFAULT_GRAPH = Path("data/corpus/atom_graph_v1/graph.json")


def main(argv: list[str] | None = None) -> int:
    """atom ①오개념(graph.json)을 `misconception_catalog`에 멱등 적재하고 행 수를 보고(CLI 본체).

    반환은 프로세스 종료 코드(0=성공·2=입력 파일 부재). 적재 로직은 `load_atom_misconceptions`가
    담당하며 본 함수는 경로 결선·실행·stdout 보고만 한다(조용한 무동작 금지 — 부재 시 명확히 보고).
    """
    parser = argparse.ArgumentParser(
        prog="whymath-atom-misconception-populate",
        description=(
            "atom 백본 ①오개념(graph.json) → backend misconception_catalog "
            "멱등 적재(mis_id 'ATOM:' 접두 PK 충돌 upsert)."
        ),
    )
    parser.add_argument(
        "--graph",
        type=Path,
        default=_DEFAULT_GRAPH,
        help=f"atom 백본 graph.json 경로(기본 {_DEFAULT_GRAPH}).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="상세 출력(현재는 표준 보고만 — 호환 자리표시).",
    )
    add_overwrite_argument(parser)
    args = parser.parse_args(argv)

    path: Path = args.graph
    if not path.exists():
        print(f"atom 백본 graph.json 없음: {path} — 원자 코퍼스를 먼저 생성하세요.")
        return 2

    conflicts: list[str] = []
    count = load_atom_misconceptions(
        path, overwrite_cms_edits=args.overwrite_cms_edits, conflicts=conflicts
    )
    print(f"atom ①오개념 적재 완료: {count}건 (src={path}).")
    if conflicts:
        print(conflict_summary(conflicts))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI 진입
    raise SystemExit(main())
