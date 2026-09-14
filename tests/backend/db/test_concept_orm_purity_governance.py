"""정적 거버넌스 — **런타임** `Concept` ORM의 Concept Purity 스냅샷 동결.

배경(2026-07-21 전면 정합성 검토): 저작 노드는 `tests/data_pipeline/concept_graph/
test_concept_node_purity.py`가 금칙·스냅샷으로 동결했으나, 런타임 투영인
`db/models/concept.py`의 `Concept` ORM에는 동형 게이트가 없어 순수성 방어가
*비대칭*이었다 — 저작 단계에서 막은 혼입(renderer·prompt·본문·오개념)이 런타임
테이블로는 무단 재유입될 수 있는 공백. 이 테스트가 그 공백을 닫는다.

정책:
- **금칙 컬럼**(저작 게이트와 동일 축)은 런타임에도 0이어야 한다.
- **순수성 부채 0건** — 과거 부채 2건은 ARCH-14로 모두 청산됐다: `embedding_id`는 *제거*(죽은
  참조 컬럼), `recommended_visual_styles`는 전용 Overlay `concept_visual_style`로 *이관*(슬88 컬럼·
  rev a9b8c7d6e5f4). 둘 다 `_FORBIDDEN_COLUMNS`로 재유입을 봉인한다. 새 부채가 생기면
  `_KNOWN_PURITY_DEBT`에 등재하되 확대는 리뷰에서 반려한다(무단 확대는 스냅샷이 차단).

hermetic: DB 불요 — `__table__.columns` introspection만(엔진·세션 0).
"""

from __future__ import annotations

from whymath_backend.db.models.concept import Concept

# ──────────────────────────────────────────────────────────────────────────
# 스냅샷 — 현재 런타임 concept 테이블 컬럼 전체(추가/삭제 시 의식적 리뷰 강제).
# ──────────────────────────────────────────────────────────────────────────
_IDENTITY_COLUMNS = frozenset({"concept_id", "code", "name_ko", "name_en", "source_id", "aliases"})
_HIERARCHY_COLUMNS = frozenset({"level", "parent_concept_id"})
_SEMANTIC_COLUMNS = frozenset(
    {
        "is_signature_korean",
        "cognitive_type",
        "intrinsic_difficulty",
        "exam_frequency",
        "weight_in_curriculum",
        "behavior_skills",  # 참조 키 배열(→ SkillNode) — 내장 아님
    }
)
_OPS_COLUMNS = frozenset({"created_at"})
# 판 관리 포인터(EOS-49 §6.4) — `concept_version.version_id`를 가리키는 느슨 참조일 뿐
# 버전 payload 자체를 내장하지 않는다(behavior_skills와 동형 축 — 참조 키, 내장 아님).
_VERSIONING_COLUMNS = frozenset({"current_published_version_id"})

# 알려진 순수성 부채 — 저작 게이트 기준 금칙 축이나 런타임에 잔존하는 컬럼. **현재 0건**:
# 과거 2건(embedding_id·recommended_visual_styles)은 ARCH-14로 모두 청산됐다(전자=죽은 컬럼 제거·
# 후자=전용 Overlay `concept_visual_style` 이관·rev a9b8c7d6e5f4). 둘 다 아래 _FORBIDDEN_COLUMNS로
# 재유입 차단. 이 집합에 *새 항목을 추가하는 것*은 부채 확대이므로 금지 — 리뷰에서 반려하라.
_KNOWN_PURITY_DEBT: frozenset[str] = frozenset()

_EXPECTED_COLUMNS = (
    _IDENTITY_COLUMNS
    | _HIERARCHY_COLUMNS
    | _SEMANTIC_COLUMNS
    | _OPS_COLUMNS
    | _VERSIONING_COLUMNS
    | _KNOWN_PURITY_DEBT
)

# 절대 금칙 — 재유입 시 즉시 red(저작 게이트 `_FORBIDDEN_NODE_FIELDS`와 동일 축 + 런타임
# 청산 이력 컬럼). Phase 1b redaction·Overlay 분리로 *제거된* 컬럼들의 부활을 막는다.
_FORBIDDEN_COLUMNS = frozenset(
    {
        # 자유텍스트 오개념(독립 오개념 DB·CLAUDE.md 구조원칙 #6)
        "misconception_text",
        "misconception",
        "common_misconceptions",
        # 본문 근접 자유 서술(redaction — 성취기준·교과서 본문 복제 위험)
        "description",
        "formal_definition",
        "intuitive_explanation",
        # 렌더러·프롬프트·시각화 실체(Concept → Intent → Adapter)
        "renderer",
        "visualization_spec",
        "prompt",
        # 벡터 실체·참조(별도 pgvector 테이블이 code 키로 소유 — 노드는 참조조차 금지)
        "embedding",
        "embedding_id",  # ARCH-14로 죽은 참조 컬럼 청산 — 재유입 금지
        # 권장 시각화 양식(노드 비내장·전용 Overlay `concept_visual_style` 이관 — rev a9b8c7d6e5f4)
        "recommended_visual_styles",  # ARCH-14 ③으로 Overlay 이관 — 재유입 금지
        # 교육과정 Overlay(CurriculumEntry 단일 진실 — rev f3a4b5c6d7e8 제거 이력)
        "curriculum",
        "subject",
        "curriculum_version",
        "grade_introduced",
        "semester_introduced",
    }
)


def _runtime_columns() -> set[str]:
    """런타임 concept 테이블 컬럼명 집합 — DB 없이 매핑 introspection."""
    return set(Concept.__table__.columns.keys())


def test_forbidden_columns_absent() -> None:
    """청산·금칙 컬럼(본문·오개념·렌더러·프롬프트·교육과정·벡터 실체)의 재유입은 즉시 red."""
    leaked = _runtime_columns() & _FORBIDDEN_COLUMNS
    assert not leaked, (
        f"런타임 Concept ORM에 금칙 컬럼이 재유입됐다: {sorted(leaked)}. "
        "본문·오개념·렌더러·프롬프트·교육과정은 노드에 넣지 말 것(Concept Purity) — "
        "ConceptContent·오개념 독립 DB·Overlay(CurriculumEntry 등)로 외부화하라."
    )


def test_columns_snapshot_frozen() -> None:
    """컬럼 전체 스냅샷 동결 — 추가/삭제 시 이 파일의 계층 집합 갱신(의식적 리뷰)을 강제."""
    assert _runtime_columns() == set(_EXPECTED_COLUMNS), (
        "런타임 Concept ORM 컬럼 구성이 바뀌었다. 새 컬럼이 순수성(참조만·내장 금지)을 "
        "깨지 않는지 검토하고 이 테스트의 계층 집합을 갱신하라. 부채 축소(embedding_id·"
        "recommended_visual_styles 이관)면 _KNOWN_PURITY_DEBT에서도 제거할 것."
    )


def test_purity_debt_is_tracked_not_grown() -> None:
    """순수성 부채 0건 — embedding_id·recommended_visual_styles 모두 ARCH-14로 청산·이관 완료.

    embedding_id=죽은 컬럼 제거, recommended_visual_styles=전용 Overlay `concept_visual_style`
    이관(rev a9b8c7d6e5f4). 둘 다 _FORBIDDEN_COLUMNS로 재유입 차단한다. 부채가 남아 있다면
    _KNOWN_PURITY_DEBT에 등재해야 하며(선언 컬럼은 실제 런타임에 존재해야 정합), 확대는 금지다.
    """
    # 선언된 부채는 실제 런타임에 존재해야 한다(빈 집합이면 공집합 부분집합으로 자명히 성립).
    assert _KNOWN_PURITY_DEBT <= _runtime_columns()
    # 부채는 0건 — 이관·청산 착륙(무단 확대 금지).
    assert _KNOWN_PURITY_DEBT == frozenset()
    # 이관·청산된 컬럼은 런타임 노드에서 완전히 사라졌다.
    assert "recommended_visual_styles" not in _runtime_columns()
    assert "embedding_id" not in _runtime_columns()
