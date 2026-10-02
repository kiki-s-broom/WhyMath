"""L1 콘텐츠 4종 PG 프로젝션 — 코퍼스(concept_content_v1·university) → `concept_content` 적재.

원자 마이그레이션 Phase 3 Slice 1. `l1/atom_graph`(원자 메타 프로젝션)의 *콘텐츠* 짝이다 —
은유·오개념·정식정의·허용표현 + 설명 + 암기카드를 code 키로 멱등 투영한다.

적재(sync·`projection.py`)와 런타임 조회(async·`resolve.py`)를 나눈다(`l1/concept_visualization`
동형). 조회 소비자는 CACHE-01 공급 경로(`l4/content_supply.py`)다.
"""

from __future__ import annotations

from whymath_backend.l1.concept_content.resolve import (
    find_k12_contents_by_atom,
    get_concept_content,
)

__all__ = ["find_k12_contents_by_atom", "get_concept_content"]
