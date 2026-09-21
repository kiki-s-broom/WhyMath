"""L4 오개념 진단·개입 — 카탈로그 + 진단 매처 + 개입 결정트리.

스펙 §"오개념 진단·개입"(L121-127) + `docs/prompts/misconception_diagnosis.md` 정본.
범위: 풀이 → 규칙 기반 매칭(substring+정규식) → 결정 트리 → 자각 유도 프롬프트.

slice 104: substring 거짓음성(패러프레이즈·동의어)을 보완하는 *의미(임베딩) 매칭* 좌석을
`semantic/`에 추가했다(EmbeddingProvider·VectorIndex·SemanticMatcher). `diagnose()`는
*불변*이고 의미 매칭은 *추가 API*(`semantic_matches`, 기본 비활성). **정직 스코프**: 의미
매칭은 recall(패러프레이즈·동의어)만 개선하고 *방향·부정·등치*는 못 가린다(임베딩 방향맹
— LLM-judged/NLI 후속). PRM 단계 파싱·pgvector 영속화·LLM-judged는 후속.
"""

from __future__ import annotations

from whymath_backend.l4.misconception.catalog import CATALOG, CATALOG_BY_ID
from whymath_backend.l4.misconception.combined import combine_diagnoses, combined_diagnose
from whymath_backend.l4.misconception.diagnose import (
    correct_form_present,
    diagnose,
    is_refuted,
    reject_refuted,
)
from whymath_backend.l4.misconception.intervene import (
    select_intervention,
    select_intervention_from_hypotheses,
)
from whymath_backend.l4.misconception.models import (
    InterventionDecision,
    InterventionPattern,
    Misconception,
    MisconceptionDomain,
    MisconceptionMatch,
)
from whymath_backend.l4.misconception.semantic import (
    EmbeddingProvider,
    FakeEmbeddingProvider,
    InMemoryVectorIndex,
    LocalEmbeddingProvider,
    OpenAIEmbeddingProvider,
    SemanticMatcher,
    VectorIndex,
    build_provider,
    semantic_matches,
)
from whymath_backend.l4.misconception.validate import (
    raise_for_distractor_map,
    validate_distractor_map,
)
from whymath_backend.l4.misconception.visualize import visualize_misconception

__all__ = [
    "CATALOG",
    "CATALOG_BY_ID",
    "EmbeddingProvider",
    "FakeEmbeddingProvider",
    "InMemoryVectorIndex",
    "InterventionDecision",
    "InterventionPattern",
    "LocalEmbeddingProvider",
    "Misconception",
    "MisconceptionDomain",
    "MisconceptionMatch",
    "OpenAIEmbeddingProvider",
    "SemanticMatcher",
    "VectorIndex",
    "build_provider",
    "combine_diagnoses",
    "combined_diagnose",
    "correct_form_present",
    "is_refuted",
    "reject_refuted",
    "diagnose",
    "raise_for_distractor_map",
    "select_intervention",
    "select_intervention_from_hypotheses",
    "semantic_matches",
    "validate_distractor_map",
    "visualize_misconception",
]
