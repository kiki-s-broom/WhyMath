"""K-12 개념 콘텐츠 행 ↔ 연결 원자 컨텍스트 — 검수 입력·승격 게이트가 같은 연결을 본다 (CONT-08).

배경: 크로스워크 역조회(CONT-06)가 착지하면 K-12 콘텐츠 행의 `reviewed`는 곧 "그 행에 연결된
원자들"의 학생 공급을 연다. 그런데 연결(`concept_content.atom_codes`)은 크로스워크 437행 전건이
`ai_estimated`이고(confidence 0.5~0.9), 종전 검수 입력(배치 프롬프트·승인 라벨)에는 연결 원자도
신뢰도도 없었다. 검수자는 콘텐츠만 보고 `reviewed`를 찍으므로 "콘텐츠가 맞다"가 "이 원자에 대한
콘텐츠로 맞다"로 읽혔다.

이 모듈은 검수 도구들이 **공급 경로와 같은 연결**을 보게 하는 읽기 전용 로더다. 연결 규칙은 새로
만들지 않고 `l1.concept_atom_crosswalk.transfer`의 것을 그대로 쓴다 — 콘텐츠 `code`는 구 437
코퍼스의 `src_id`이고, 크로스워크 `concept_id`는 `graph.json` 다리로 `src_id`에 이어진다
(`derive_k12_content_atom_codes`와 같은 축). 규칙을 여기서 다시 쓰면 두 곳이 어긋난다.

정직한 한계: 이 연결은 **기계 추정**이다. 여기서 싣는 `mapping_review_status`·`confidence`는 그
사실을 검수자에게 보이려는 것이며, 연결이 맞다는 보증이 아니다. 연결이 맞는지는 사람이
`link_approved` 라벨로 따로 말한다(승격 도구가 그것을 요구한다).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from whymath_backend.l1.concept_atom_crosswalk.transfer import load_concept_src_bridge

# 레포 루트: src/backend/whymath_backend/harness/ → 4단 상승(`concept_content_review_batch` 동형).
_REPO_ROOT = Path(__file__).resolve().parents[4]

DEFAULT_CROSSWALK = Path("data/corpus/concept_atom_crosswalk_v1/crosswalk.jsonl")
DEFAULT_CONCEPT_GRAPH = Path("data/corpus/concept_graph_v1/graph.json")
DEFAULT_ATOM_GRAPH = Path("data/corpus/atom_graph_v1/graph.json")


@dataclass(frozen=True, slots=True)
class ContentLink:
    """K-12 콘텐츠 행 1건의 연결 컨텍스트 — 원자 코드·명칭과 크로스워크의 자기 평가."""

    atom_codes: tuple[str, ...]
    """연결 원자 코드(사전순·dedup) — `concept_content.atom_codes`와 같은 값."""

    atom_names: Mapping[str, str]
    """원자 코드 → 명칭(원자 그래프). 명칭을 못 찾은 코드는 키가 없다(지어내지 않는다)."""

    primary_atom_code: str | None
    confidence: float | None
    match_method: str | None
    mapping_review_status: str
    """크로스워크 행의 검수 상태 — 현재 전건 `ai_estimated`."""


def _resolve(path: Path | None, default: Path) -> Path:
    return path if path is not None else _REPO_ROOT / default


def _load_atom_names(atom_graph_path: Path) -> dict[str, str]:
    payload = json.loads(atom_graph_path.read_text(encoding="utf-8"))
    names: dict[str, str] = {}
    for node in payload.get("concepts", []):
        code = str(node.get("code") or "").strip()
        name = str(node.get("name") or "").strip()
        if code and name:
            names[code] = name
    return names


def load_content_links(
    crosswalk_path: Path | None = None,
    concept_graph_path: Path | None = None,
    atom_graph_path: Path | None = None,
) -> dict[str, ContentLink]:
    """콘텐츠 `code`(=src_id) → 연결 컨텍스트. 원자가 없는(unmapped) 행은 포함하지 않는다.

    Raises:
        FileNotFoundError: 입력 파일 부재(조용히 빈 결과로 대체하지 않는다 — 빈 결과는
            "연결 없음"으로 읽혀 승격 게이트가 통째로 풀린다).
        ValueError: 크로스워크 `concept_id`가 다리에 없거나 한 콘텐츠 행에 크로스워크 행이 둘 닿음.
    """
    crosswalk = _resolve(crosswalk_path, DEFAULT_CROSSWALK)
    bridge = load_concept_src_bridge(_resolve(concept_graph_path, DEFAULT_CONCEPT_GRAPH))
    atom_names = _load_atom_names(_resolve(atom_graph_path, DEFAULT_ATOM_GRAPH))

    links: dict[str, ContentLink] = {}
    for line in crosswalk.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        raw_codes = row.get("atom_codes")
        codes = (
            tuple(sorted(dict.fromkeys(str(c) for c in raw_codes)))
            if isinstance(raw_codes, (list, tuple))
            else ()
        )
        if not codes:  # unmapped — 강제 귀속 금지(연결 없음)
            continue
        concept_id = str(row.get("concept_id") or "").strip()
        src_id = bridge.get(concept_id)
        if src_id is None:
            raise ValueError(f"크로스워크 concept_id가 graph.json에 없음: {concept_id!r}")
        if src_id in links:
            raise ValueError(f"콘텐츠 code {src_id!r}에 크로스워크 행이 중복으로 닿음")
        confidence = row.get("confidence")
        primary = row.get("primary_atom_code")
        method = row.get("match_method")
        links[src_id] = ContentLink(
            atom_codes=codes,
            atom_names={c: atom_names[c] for c in codes if c in atom_names},
            primary_atom_code=str(primary) if primary else None,
            confidence=float(confidence) if isinstance(confidence, (int, float)) else None,
            match_method=str(method) if method else None,
            mapping_review_status=str(row.get("review_status") or "unknown"),
        )
    return links


def format_link_for_review(link: ContentLink) -> str:
    """검수자(LLM·사람)에게 보이는 연결 요약 한 줄 — 신뢰도와 '기계 추정·미검수'를 숨기지 않는다."""
    parts = []
    for code in link.atom_codes:
        name = link.atom_names.get(code, "(명칭 미상)")
        mark = "[대표]" if code == link.primary_atom_code else ""
        parts.append(f"{code}({name}){mark}")
    confidence = "미상" if link.confidence is None else f"{link.confidence:.2f}"
    return (
        f"{', '.join(parts)} — 크로스워크 {link.mapping_review_status}"
        f"(기계 추정·미검수, confidence={confidence}, 방식={link.match_method or '미상'})"
    )
