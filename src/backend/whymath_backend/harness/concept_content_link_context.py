"""검수 도구용 연결 컨텍스트 창구 — 로더는 크로스워크 패키지, 표시는 여기 (CONT-08).

검수 도구(배치 프롬프트·승격 게이트)가 쓰는 이름을 한 곳에 모은다. 구 437 `graph.json`을 읽는
로더는 화이트리스트된 `l1.concept_atom_crosswalk.content_link`에 있고, 이 모듈은 그것을 다시
내보내며 검수자(LLM·사람)에게 보일 연결 요약 문장만 만든다.
"""

from __future__ import annotations

from whymath_backend.l1.concept_atom_crosswalk.content_link import (
    ContentLink,
    load_content_links,
)

__all__ = ["ContentLink", "format_link_for_review", "load_content_links"]


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
