"""대학 원자 `standard_codes` 채움 — 커밋된 graph.json 후처리 (원자 백본 U2).

원본 원자 xlsx(`원자_통합마스터`)는 휘발됐으므로 transform 재실행이 불가하다. 따라서 *커밋된*
코퍼스 `data/corpus/atom_graph_v1/graph.json`을 **후처리**해 대학 원자(세부개념 — 건수는
`docs/data/corpus_facts.md`의 `atom_graph.university_atoms`)의 빈 `standard_codes`를
채운다(handoff §6 허용 경로). 채움 근거는 U1 산출 `standards_university_v1` 코퍼스다 —
소단원(링크 `concept_src_id`)↔성취기준(`norm_id`→`code`)이 1:1이라 소단원 코드 → 성취기준 코드 맵을
만들고, 각 대학 원자(level=세부개념)의 `subunit_code`로 그 소단원의 성취기준 코드를 찾아 채운다.

규율(K-12 무변경·멱등):
  - **level=세부개념 + subunit_code∈대학 소단원 맵**인 원자만 채운다. K-12 원자(이미 채워짐)·
    단원/소단원 노드(K-12 관례상 비움)는 *건드리지 않는다*(코드 정합·미적 하이픈 사태 방지).
  - 소단원↔성취기준 1:1이라 각 대학 원자는 정확히 **한 코드**를 받는다(`["[CALC1-01-01]"]`).
  - **멱등**: 재실행 시 같은 코드로 덮어쓰므로 byte 동일 산출(determinism). 직렬화는 transform과
    동일(`json.dumps(ensure_ascii=False, indent=2)`·trailing newline 없음)이라 diff 최소.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from data_pipeline.atom_graph.models import NodeLevel

_DEFAULT_GRAPH = Path("data/corpus/atom_graph_v1/graph.json")
_DEFAULT_STANDARDS_DIR = Path("data/corpus/standards_university_v1")


@dataclass(slots=True)
class FillReport:
    """대학 원자 standard_codes 채움 결과(운영 가시성·테스트 단언)."""

    university_atoms_filled: int
    subunits_mapped: int
    k12_atoms_unchanged: int
    unmapped_university_atoms: list[str]

    @property
    def is_complete(self) -> bool:
        """모든 대학 원자가 매핑됐는가(미매핑 0)."""
        return not self.unmapped_university_atoms


def build_subunit_standard_map(standards_dir: Path) -> dict[str, str]:
    """U1 대학 성취기준 코퍼스 → `{소단원코드: 성취기준코드}` 맵(소단원↔성취기준 1:1).

    링크(`concept_src_id`=소단원 → `norm_id`)와 성취기준(`norm_id` → `code`)을 조인한다. 두
    파일 모두 U1 산출(`standards_university_v1`)이며 1:1이라 소단원당 정확히 한 코드가 나온다.
    """
    links = json.loads((standards_dir / "concept_standard_links.json").read_text(encoding="utf-8"))
    stds = json.loads((standards_dir / "standards.json").read_text(encoding="utf-8"))
    norm_to_code: dict[str, str] = {s["norm_id"]: s["code"] for s in stds["standards"]}
    sub_to_code: dict[str, str] = {}
    for link in links["links"]:
        norm_id = link["norm_id"]
        if norm_id not in norm_to_code:
            raise ValueError(f"링크 norm_id={norm_id}가 standards에 없음(코퍼스 무결성 위반)")
        sub_to_code[link["concept_src_id"]] = norm_to_code[norm_id]
    return sub_to_code


def fill_university_standard_codes(
    graph: dict[str, Any], sub_to_code: Mapping[str, str]
) -> FillReport:
    """graph의 대학 원자 `standard_codes`를 소단원→성취기준 맵으로 채운다(in-place·멱등).

    level=세부개념이고 `subunit_code`가 맵에 있는 원자만 `["<code>"]`로 채운다. 그 밖의 노드
    (K-12 원자·모든 단원/소단원)는 건드리지 않는다. 반환=채움 리포트.
    """
    atom_level = NodeLevel.ATOM.value
    filled = 0
    k12_unchanged = 0
    unmapped: list[str] = []
    for node in graph.get("concepts", []):
        if node.get("level") != atom_level:
            continue
        subunit = node.get("subunit_code")
        code = sub_to_code.get(subunit) if subunit is not None else None
        if code is None:
            # 맵에 없는 원자 = K-12 원자(건드리지 않음). 단, subunit_code가 대학형인데 맵에
            # 없으면 미매핑 대학 원자로 보고(코드 정합 누락 방지).
            if _looks_university(subunit):
                unmapped.append(str(node.get("code")))
            else:
                k12_unchanged += 1
            continue
        node["standard_codes"] = [code]
        filled += 1
    return FillReport(
        university_atoms_filled=filled,
        subunits_mapped=len(sub_to_code),
        k12_atoms_unchanged=k12_unchanged,
        unmapped_university_atoms=unmapped,
    )


def _looks_university(subunit_code: object) -> bool:
    """대학 소단원 코드 형태인가(라틴 대문자 시작 — `CALC1-U1-S1`). K-12는 한글 시작."""
    text = str(subunit_code or "")
    return bool(text) and text[0].isascii() and text[0].isupper()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="atom-university-standard-fill",
        description="커밋된 graph.json 대학 원자 standard_codes를 U1 성취기준으로 채움(멱등)",
    )
    parser.add_argument("--graph", type=Path, default=_DEFAULT_GRAPH, help="원자 코퍼스 graph.json")
    parser.add_argument(
        "--standards-dir",
        type=Path,
        default=_DEFAULT_STANDARDS_DIR,
        help="U1 대학 성취기준 코퍼스 디렉터리",
    )
    args = parser.parse_args(argv)

    if not args.graph.exists():
        print(f"graph.json 없음: {args.graph}")
        return 2
    if not (args.standards_dir / "standards.json").exists():
        print(f"대학 성취기준 코퍼스 없음: {args.standards_dir} — U1을 먼저 실행하세요.")
        return 2

    sub_to_code = build_subunit_standard_map(args.standards_dir)
    graph: dict[str, Any] = json.loads(args.graph.read_text(encoding="utf-8"))
    report = fill_university_standard_codes(graph, sub_to_code)

    if not report.is_complete:
        print(
            f"미매핑 대학 원자 {len(report.unmapped_university_atoms)}건 "
            f"(예: {report.unmapped_university_atoms[:5]}) — 코드 정합 실패. 쓰지 않습니다."
        )
        return 1

    # transform과 동일 직렬화(determinism·diff 최소·trailing newline 없음).
    args.graph.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    _append_provenance(args.graph.parent / "_provenance.json", report)
    print(
        f"대학 원자 standard_codes 채움 완료: {report.university_atoms_filled}건 "
        f"(소단원 맵 {report.subunits_mapped}·K-12 원자 무변경 {report.k12_atoms_unchanged})."
    )
    return 0


def _append_provenance(path: Path, report: FillReport) -> None:
    """_provenance.json에 U2 후처리 노트를 추가(있으면 갱신·멱등)."""
    if not path.exists():
        return
    prov: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    note = (
        f"[U2 {datetime.now(tz=timezone.utc).date().isoformat()}] 대학 원자 standard_codes 채움 "
        f"{report.university_atoms_filled}건(소단원→성취기준 1:1·standards_university_v1). "
        "K-12 원자·단원/소단원 무변경."
    )
    post = prov.setdefault("post_extraction", [])
    if isinstance(post, list) and note not in post:
        post.append(note)
    path.write_text(json.dumps(prov, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":  # pragma: no cover — CLI 진입점
    raise SystemExit(main())
