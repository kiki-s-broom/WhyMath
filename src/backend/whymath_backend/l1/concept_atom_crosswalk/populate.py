"""437-키 자산 원자 축 이전 CLI — `whymath_backend.l1.concept_atom_crosswalk.populate` (S0-2).

커밋된 크로스워크 코퍼스(`crosswalk.jsonl`)와 구 437 코퍼스(`graph.json`·`concepts.jsonl` 다리)
를 읽어 `atom_node.behavior_skills`(#419 저작분 전파)·런타임 `concept.behavior_skills`(SKB-01·
atom_node와 같은 매핑 재사용)·`concept_content.atom_codes`(K-12 원자 연결)를 멱등 UPDATE한다.
`l1/concept_content/populate`(콘텐츠 적재 CLI)와 같은 골격을 따른다(argparse·`main(argv)->int`·
파일 부재 `return 2`·stdout 보고).

전제: 마이그레이션 head(`b2c3d4e5f0a1`) 적용 실 PG + 대상 행 선적재(`atom_node`는
`atom_node_projection`·런타임 `concept`은 `atom_graph.atom_backend_concept`·`concept_content`는
`concept_content/populate`). 대상 행 부재는 조용히 넘기지 않고 missing으로 보고한다. 이전 로직
0(얇은 래퍼): 파싱·유도·갱신은 `transfer.py` 소관.

사용:
    python -m whymath_backend.l1.concept_atom_crosswalk.populate \\
        --crosswalk data/corpus/concept_atom_crosswalk_v1/crosswalk.jsonl \\
        --concept-graph data/corpus/concept_graph_v1/graph.json \\
        --concepts data/corpus/concept_graph_v1/concepts.jsonl
"""

from __future__ import annotations

import argparse
from pathlib import Path

from whymath_backend.l1.concept_atom_crosswalk.transfer import (
    derive_atom_behavior_skills,
    derive_k12_content_atom_codes,
    load_behavior_skills_by_src,
    load_concept_src_bridge,
    load_crosswalk_records,
    transfer_atom_behavior_skills,
    transfer_concept_behavior_skills,
    transfer_k12_content_atom_codes,
)

# 코퍼스 기본 경로(S0-1 커밋 관례·저장소 루트 기준).
_DEFAULT_CROSSWALK = Path("data/corpus/concept_atom_crosswalk_v1/crosswalk.jsonl")
_DEFAULT_CONCEPT_GRAPH = Path("data/corpus/concept_graph_v1/graph.json")
_DEFAULT_CONCEPTS_JSONL = Path("data/corpus/concept_graph_v1/concepts.jsonl")


def main(argv: list[str] | None = None) -> int:
    """크로스워크 경유 437-키 자산을 원자 축에 이전하고 실측을 보고(CLI 본체).

    반환은 프로세스 종료 코드(0=성공·2=입력 파일 부재). unmapped skip·대상 행 부재(missing)는
    stdout으로 명확히 보고한다(조용한 무동작·조용한 skip 금지).
    """
    parser = argparse.ArgumentParser(
        prog="whymath-crosswalk-transfer",
        description=(
            "437↔원자 크로스워크 경유 이전 — atom_node.behavior_skills·concept.behavior_skills "
            "전파(SKB-01) + concept_content K-12 atom_codes 연결(멱등 UPDATE·S0-2)."
        ),
    )
    parser.add_argument(
        "--crosswalk",
        type=Path,
        default=_DEFAULT_CROSSWALK,
        help=f"크로스워크 crosswalk.jsonl 경로(기본 {_DEFAULT_CROSSWALK}).",
    )
    parser.add_argument(
        "--concept-graph",
        type=Path,
        default=_DEFAULT_CONCEPT_GRAPH,
        help=f"구 437 graph.json 경로 — concept_id↔src_id 다리(기본 {_DEFAULT_CONCEPT_GRAPH}).",
    )
    parser.add_argument(
        "--concepts",
        type=Path,
        default=_DEFAULT_CONCEPTS_JSONL,
        help=f"구 437 concepts.jsonl — behavior_skills 저작 좌석(기본 {_DEFAULT_CONCEPTS_JSONL}).",
    )
    args = parser.parse_args(argv)

    sources: list[Path] = [args.crosswalk, args.concept_graph, args.concepts]
    for path in sources:
        if not path.exists():
            print(f"코퍼스 없음: {path} — 커밋된 코퍼스 경로를 확인하세요.")
            return 2

    crosswalk = load_crosswalk_records(args.crosswalk)
    bridge = load_concept_src_bridge(args.concept_graph)
    skills_by_src = load_behavior_skills_by_src(args.concepts)

    unmapped = [r.concept_id for r in crosswalk if not r.atom_codes]
    if unmapped:
        # 강제 귀속 금지 — skip하되 조용히 넘기지 않는다(크로스워크 소비 계약 §4).
        print(f"unmapped 크로스워크 행 skip: {len(unmapped)}건 (예: {unmapped[:3]}).")

    atom_skills = derive_atom_behavior_skills(crosswalk, bridge, skills_by_src)
    content_atoms = derive_k12_content_atom_codes(crosswalk, bridge)

    atom_report = transfer_atom_behavior_skills(atom_skills)
    nonempty = sum(1 for skills in atom_skills.values() if skills)
    print(
        f"atom_node.behavior_skills 갱신: {atom_report.updated}건 "
        f"(비어있지 않은 스킬 {nonempty}건·대상 원자 {len(atom_skills)}건)."
    )
    if atom_report.missing:
        print(
            f"⚠ atom_node 대상 행 부재 {len(atom_report.missing)}건 "
            f"(예: {list(atom_report.missing[:3])}) — atom_node_projection 선적재를 확인하세요."
        )

    # 런타임 concept.behavior_skills(SKB-01) — atom_node와 같은 atom_skills 매핑 재사용(다리 불요).
    concept_report = transfer_concept_behavior_skills(atom_skills)
    print(
        f"concept.behavior_skills 갱신: {concept_report.updated}건 "
        f"(비어있지 않은 스킬 {nonempty}건·대상 {len(atom_skills)}건)."
    )
    if concept_report.missing:
        print(
            f"⚠ concept 대상 행 부재 {len(concept_report.missing)}건 "
            f"(예: {list(concept_report.missing[:3])}) — atom_backend_concept 선적재를 확인하세요."
        )

    content_report = transfer_k12_content_atom_codes(content_atoms)
    print(
        f"concept_content.atom_codes(K-12) 갱신: {content_report.updated}건 "
        f"(대상 {len(content_atoms)}건·대학 행 무변경)."
    )
    if content_report.missing:
        print(
            f"⚠ concept_content K-12 대상 행 부재 {len(content_report.missing)}건 "
            f"(예: {list(content_report.missing[:3])}) — concept_content 선적재를 확인하세요."
        )

    print("437-키 자산 원자 축 이전 완료.")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI 진입
    raise SystemExit(main())
