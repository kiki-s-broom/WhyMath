"""교육과정 Overlay 적재 CLI — `whymath_backend.l1.curriculum.populate`.

개념그래프 코퍼스(`data/corpus/concept_graph_v1/graph.json`)의 한국(KR) 교육과정 신호를 backend
`curriculum_entry` Overlay(개념당 1 KR 셀)로 멱등 적재한다. `l1/concept_graph/populate`(개념
임베딩+노드+엣지)·`l1/standards/populate`(성취기준)의 *Overlay* 짝이며 같은 CLI 골격을 따른다
(argparse·`main(argv)->int`·파일 부재 `return 2`·stdout 행수 보고). 교육과정 셀은 임베딩·pgvector와
무관(순수 RDB sync 적재)하므로 vector_store 게이트가 없다.

원자 축(S2-07): 기본 동작은 canonical KR 셀 + 크로스워크 전파로 유도한 **원자-키 KR 셀**을 함께
적재한다(`load_kr_curriculum_entries_with_atoms` — S2-03 이후 gating 깊이 조인이 원자 코드 공간을
보므로, 원자 행이 없으면 L6 깊이정렬 신호가 소실된다·curriculum_loader §원자 축 이관). 크로스워크
경로는 `--crosswalk`로 바꿀 수 있다.

대학 축(S4-64): 크로스워크는 대학 원자를 0건 매핑하므로 위 경로로는 대학 셀이 영원히 생기지
않는다. 그래서 `--atom-graph`(atom_graph_v1 graph.json)를 받아
`load_kr_curriculum_entries_for_university_atoms`가 유도한 **대학 원자 KR 셀**(grade_band 1~4학년
= introduced_grade 13~16 · required_depth는 원자별 cognitive_type 도출 — Kiki 결정 2026-10-09)을
canonical·원자 목록과 합쳐 같은 upsert로 적재한다. 대학 셀 건수는 canonical·원자와 별도로 보고한다.

적재 로직 0(얇은 래퍼): `load_kr_curriculum_entries_with_atoms`(빌드·원자 유도)·
`load_kr_curriculum_entries_for_university_atoms`(대학 원자 유도)·
`populate_kr_curriculum_entries`(멱등 upsert)가 파싱·매핑·전파·dedup·ON CONFLICT를 전부 담당한다.
본 CLI는 경로 결선·실행·보고만.

전제: 마이그레이션 head 적용된 실 PG 도달(`curriculum_entry`). 자격은 env(시크릿 0). 셀의
`concept_id`는 개념 그래프·원자 백본 키 공간 느슨참조라 개념 선적재(`l1.concept_graph.populate`)에
의존하지 않는다(FK 아님 — 셀은 독립 적재 가능).

사용:
    python -m whymath_backend.l1.curriculum.populate \\
        --graph data/corpus/concept_graph_v1/graph.json \\
        --crosswalk data/corpus/concept_atom_crosswalk_v1/crosswalk.jsonl \\
        --atom-graph data/corpus/atom_graph_v1/graph.json
"""

from __future__ import annotations

import argparse
from pathlib import Path

from whymath_backend.l1.curriculum.curriculum_loader import (
    load_kr_curriculum_entries_for_university_atoms,
    load_kr_curriculum_entries_with_atoms,
    populate_kr_curriculum_entries,
)

# 코퍼스 기본 경로(개념그래프 graph.json — l1.concept_graph.populate와 동일 소스).
_DEFAULT_GRAPH = Path("data/corpus/concept_graph_v1/graph.json")
# 크로스워크 기본 경로(canonical→원자 매핑 — l1.concept_atom_crosswalk와 동일 코퍼스·S2-07).
_DEFAULT_CROSSWALK = Path("data/corpus/concept_atom_crosswalk_v1/crosswalk.jsonl")
# 원자 백본 graph.json 기본 경로(대학 원자 유도용·크로스워크 미매핑 — S4-64).
_DEFAULT_ATOM_GRAPH = Path("data/corpus/atom_graph_v1/graph.json")


def main(argv: list[str] | None = None) -> int:
    """graph.json KR 신호 + 크로스워크 유도 원자 셀 + 대학 원자 셀을 `curriculum_entry`에 멱등 적재.

    반환은 프로세스 종료 코드(0=성공·2=입력 파일 부재). 적재 로직은 로더가 담당하며 본 함수는 경로
    결선·실행·stdout 보고만 한다(조용한 무동작 금지 — 부재 시 명확히 보고). canonical/원자/대학 행
    수를 각각 보고한다(축별 신호 유무를 육안 확인 가능하게 — S2-07·S4-64). 세 입력 파일은 적재
    전에 모두 확인한다(일부만 적재된 채 종료하는 부분 적재 방지).
    """
    parser = argparse.ArgumentParser(
        prog="whymath-curriculum-populate",
        description=(
            "개념그래프 graph.json → backend curriculum_entry KR 셀(canonical+원자+대학) 멱등 적재"
            "(entry_id PK 충돌 upsert·교육과정 Overlay·S2-07 원자 축·S4-64 대학 축)."
        ),
    )
    parser.add_argument(
        "--graph",
        type=Path,
        default=_DEFAULT_GRAPH,
        help=f"개념그래프 graph.json 경로(기본 {_DEFAULT_GRAPH}).",
    )
    parser.add_argument(
        "--crosswalk",
        type=Path,
        default=_DEFAULT_CROSSWALK,
        help=f"canonical→원자 크로스워크 crosswalk.jsonl 경로(기본 {_DEFAULT_CROSSWALK}).",
    )
    parser.add_argument(
        "--atom-graph",
        type=Path,
        default=_DEFAULT_ATOM_GRAPH,
        help=(
            f"원자 백본 graph.json 경로(대학 원자 KR 셀 유도용·기본 {_DEFAULT_ATOM_GRAPH}) — "
            "개념그래프 --graph와 다른 파일."
        ),
    )
    args = parser.parse_args(argv)

    graph_path: Path = args.graph
    if not graph_path.exists():
        print(f"개념그래프 graph.json 없음: {graph_path} — 코퍼스를 먼저 생성하세요.")
        return 2

    crosswalk_path: Path = args.crosswalk
    if not crosswalk_path.exists():
        print(f"크로스워크 crosswalk.jsonl 없음: {crosswalk_path} — 코퍼스를 먼저 생성하세요.")
        return 2

    atom_graph_path: Path = args.atom_graph
    if not atom_graph_path.exists():
        print(f"원자 백본 graph.json 없음: {atom_graph_path} — 코퍼스를 먼저 생성하세요.")
        return 2

    canonical, atoms = load_kr_curriculum_entries_with_atoms(graph_path, crosswalk_path)
    university = load_kr_curriculum_entries_for_university_atoms(atom_graph_path)
    count = populate_kr_curriculum_entries([*canonical, *atoms, *university])
    print(
        f"교육과정 Overlay(KR) 적재 완료: {count}건 "
        f"(canonical {len(canonical)}건 + 원자 {len(atoms)}건 + 대학 {len(university)}건 · "
        f"graph={graph_path} · crosswalk={crosswalk_path} · atom-graph={atom_graph_path})."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI 진입
    raise SystemExit(main())
