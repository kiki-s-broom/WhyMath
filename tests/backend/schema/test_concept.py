"""Schema v1.0 Concept Graph 모델 단위 테스트 — 생성·extra forbid·범위·불변식.

설계 정본: `schemas/v1.0/schema_v1.0.md` §4.2(concept·concept_edge·problem_concept·
concept_fusion). 4테이블 + 신규 ENUM 4종(ConceptLevel·CognitiveType·EdgeType·ConceptRole).

불변식 분기 커버리지:
  - Concept._no_self_parent: 자기부모 거부 / 자기부모 아님 통과 / parent=None 통과
  - ConceptEdge._no_self_edge: 자기엣지 거부 / 정상 통과
범위·제약: intrinsic_difficulty·exam_frequency·edge_strength·relevance·semester 등 +
ConceptFusion.concept_ids 빈 배열(min_length) 거부.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from whymath_backend.schema.concept import (
    Concept,
    ConceptEdge,
    ConceptFusion,
    ProblemConcept,
)
from whymath_backend.schema.enums import (
    CognitiveType,
    ConceptLevel,
    ConceptRole,
    EdgeType,
    VisualizationStyle,
)


# ──────────────────────────────────────────────────────────────────────
# 신규 ENUM 4종 — 값 검증(§4.2 인라인 DDL 정본)
# ──────────────────────────────────────────────────────────────────────
class TestConceptEnumValues:
    def test_concept_level_values_korean(self) -> None:
        """ConceptLevel — 한글 값(단원/소단원/세부개념)."""
        assert ConceptLevel.단원.value == "단원"
        assert ConceptLevel.소단원.value == "소단원"
        assert ConceptLevel.세부개념.value == "세부개념"
        assert {e.value for e in ConceptLevel} == {"단원", "소단원", "세부개념"}

    def test_cognitive_type_values_english(self) -> None:
        """CognitiveType — 영어 5종."""
        assert {e.value for e in CognitiveType} == {
            "DEFINITION",
            "THEOREM",
            "TECHNIQUE",
            "PATTERN",
            "VISUAL_REASONING",
        }

    def test_edge_type_values_english(self) -> None:
        """EdgeType — 영어 6종(슬108 TRIGGERS_DISTRACTOR 어휘 추가)."""
        assert {e.value for e in EdgeType} == {
            "PREREQUISITE",
            "COMPOSED_OF",
            "ANALOGOUS_TO",
            "EXTENDS",
            "CONTRASTS",
            "TRIGGERS_DISTRACTOR",
        }

    def test_concept_role_values_english(self) -> None:
        """ConceptRole — 영어 4종."""
        assert {e.value for e in ConceptRole} == {
            "PRIMARY",
            "SUPPORTING",
            "IMPLICIT",
            "TESTED",
        }

    def test_str_enum_equality(self) -> None:
        """str-Enum — 문자열 값과 동등 비교(라우터·필터 안정성)."""
        assert ConceptLevel.단원 == "단원"
        assert EdgeType.PREREQUISITE == "PREREQUISITE"


# ──────────────────────────────────────────────────────────────────────
# Concept — 생성·기본값·roundtrip
# ──────────────────────────────────────────────────────────────────────
class TestConceptCreation:
    def test_minimal_concept_valid(self) -> None:
        """필수 필드(code·name_ko·level)만으로 생성 — 나머지 기본값."""
        c = Concept(code="CAL-INT-DEF", name_ko="정적분", level=ConceptLevel.소단원)
        assert isinstance(c.concept_id, uuid.UUID)
        assert c.code == "CAL-INT-DEF"
        assert c.name_ko == "정적분"
        assert c.name_en is None
        assert c.parent_concept_id is None
        assert c.aliases == []
        assert c.cognitive_type == []
        assert c.recommended_visual_styles == []
        assert c.is_signature_korean is False

    def test_full_fields_roundtrip(self) -> None:
        """전 필드를 채운 합법 인스턴스 — 값 보존 확인."""
        parent = uuid.uuid4()
        now = datetime.now(timezone.utc)
        c = Concept(
            code="CAL-INT-DEF-FUNDAMENTAL",
            name_ko="미적분학의 기본정리",
            name_en="Fundamental Theorem of Calculus",
            aliases=["FTC", "Fundamental Theorem of Calculus"],
            level=ConceptLevel.세부개념,
            parent_concept_id=parent,
            is_signature_korean=True,
            cognitive_type=[CognitiveType.THEOREM, CognitiveType.TECHNIQUE],
            recommended_visual_styles=[
                VisualizationStyle.넓이모델,
                VisualizationStyle.함수그래프,
            ],
            intrinsic_difficulty=4.5,
            exam_frequency=0.82,
            weight_in_curriculum=0.6,
            created_at=now,
        )
        assert c.parent_concept_id == parent
        assert c.cognitive_type == [CognitiveType.THEOREM, CognitiveType.TECHNIQUE]
        assert c.recommended_visual_styles == [
            VisualizationStyle.넓이모델,
            VisualizationStyle.함수그래프,
        ]
        assert c.intrinsic_difficulty == pytest.approx(4.5)

    def test_extra_forbidden(self) -> None:
        """extra='forbid' — 알 수 없는 필드 거부."""
        with pytest.raises(ValidationError):
            Concept(  # type: ignore[call-arg]
                code="X", name_ko="x", level=ConceptLevel.단원, bogus="x"
            )

    def test_missing_required_rejected(self) -> None:
        """code·name_ko·level은 필수 — 누락 시 거부."""
        with pytest.raises(ValidationError):
            Concept(name_ko="정적분", level=ConceptLevel.단원)  # type: ignore[call-arg]

    def test_enum_value_serialization_korean_level(self) -> None:
        """use_enum_values → level이 한글 값('단원')으로 직렬화·보존."""
        c = Concept(code="C", name_ko="공통수학", level=ConceptLevel.단원)
        dumped = c.model_dump()
        assert dumped["level"] == "단원"

    def test_cognitive_type_list_serialization(self) -> None:
        """use_enum_values → cognitive_type 배열이 문자열 값 배열로 직렬화."""
        c = Concept(
            code="C",
            name_ko="개념",
            level=ConceptLevel.세부개념,
            cognitive_type=[CognitiveType.DEFINITION, CognitiveType.VISUAL_REASONING],
        )
        assert c.model_dump()["cognitive_type"] == ["DEFINITION", "VISUAL_REASONING"]

    def test_recommended_visual_styles_serialization(self) -> None:
        """use_enum_values → recommended_visual_styles 배열이 한글 값 배열로 직렬화(슬라이스 88)."""
        c = Concept(
            code="C",
            name_ko="삼각함수",
            level=ConceptLevel.세부개념,
            recommended_visual_styles=[
                VisualizationStyle.단위원,
                VisualizationStyle.함수그래프,
            ],
        )
        assert c.model_dump()["recommended_visual_styles"] == ["단위원", "함수그래프"]

    def test_code_max_length(self) -> None:
        """code는 max_length=64 — 초과 거부."""
        with pytest.raises(ValidationError):
            Concept(code="x" * 65, name_ko="x", level=ConceptLevel.단원)

    def test_name_ko_max_length(self) -> None:
        """name_ko는 max_length=200 — 초과 거부."""
        with pytest.raises(ValidationError):
            Concept(code="C", name_ko="가" * 201, level=ConceptLevel.단원)


# ──────────────────────────────────────────────────────────────────────
# Concept — 범위 제약
# ──────────────────────────────────────────────────────────────────────
class TestConceptRanges:
    def test_intrinsic_difficulty_too_high_rejected(self) -> None:
        """intrinsic_difficulty는 1.0-5.0 — 5 초과 거부."""
        with pytest.raises(ValidationError):
            Concept(code="C", name_ko="x", level=ConceptLevel.단원, intrinsic_difficulty=5.5)

    def test_intrinsic_difficulty_too_low_rejected(self) -> None:
        """intrinsic_difficulty는 1.0-5.0 — 1 미만 거부."""
        with pytest.raises(ValidationError):
            Concept(code="C", name_ko="x", level=ConceptLevel.단원, intrinsic_difficulty=0.5)

    def test_exam_frequency_too_high_rejected(self) -> None:
        """exam_frequency는 0.0-1.0 — 1 초과 거부."""
        with pytest.raises(ValidationError):
            Concept(code="C", name_ko="x", level=ConceptLevel.단원, exam_frequency=1.5)

    def test_weight_in_curriculum_too_high_rejected(self) -> None:
        """weight_in_curriculum은 0.0-1.0(보수 설정) — 1 초과 거부."""
        with pytest.raises(ValidationError):
            Concept(code="C", name_ko="x", level=ConceptLevel.단원, weight_in_curriculum=1.2)

    def test_curriculum_introduced_fields_removed(self) -> None:
        """grade_introduced·semester_introduced는 노드에서 제거됨(교육과정 Overlay 분리) —
        extra='forbid'라 넘기면 거부된다(curriculum_entry가 단일 진실)."""
        with pytest.raises(ValidationError):
            Concept(  # type: ignore[call-arg]
                code="C", name_ko="x", level=ConceptLevel.단원, grade_introduced=12
            )
        with pytest.raises(ValidationError):
            Concept(  # type: ignore[call-arg]
                code="C", name_ko="x", level=ConceptLevel.단원, semester_introduced=1
            )


# ──────────────────────────────────────────────────────────────────────
# Concept — 불변식 _no_self_parent
# ──────────────────────────────────────────────────────────────────────
class TestConceptSelfParent:
    def test_self_parent_rejected(self) -> None:
        """parent_concept_id == concept_id → ValidationError(자기부모 금지)."""
        cid = uuid.uuid4()
        with pytest.raises(ValidationError, match="자기 자신이 부모"):
            Concept(
                concept_id=cid,
                code="C",
                name_ko="x",
                level=ConceptLevel.소단원,
                parent_concept_id=cid,
            )

    def test_distinct_parent_passes(self) -> None:
        """parent_concept_id != concept_id → 통과."""
        c = Concept(
            code="C",
            name_ko="x",
            level=ConceptLevel.세부개념,
            parent_concept_id=uuid.uuid4(),
        )
        assert c.parent_concept_id != c.concept_id

    def test_none_parent_passes(self) -> None:
        """parent_concept_id=None(루트 개념) → 검사 대상 아님 → 통과."""
        c = Concept(code="C", name_ko="x", level=ConceptLevel.단원)
        assert c.parent_concept_id is None


# ──────────────────────────────────────────────────────────────────────
# ConceptEdge — 생성·범위·불변식 _no_self_edge
# ──────────────────────────────────────────────────────────────────────
class TestConceptEdge:
    def test_valid_edge(self) -> None:
        """from·to·edge_type 필수 + 선택 필드 — 값 보존."""
        frm = uuid.uuid4()
        to = uuid.uuid4()
        e = ConceptEdge(
            from_concept_id=frm,
            to_concept_id=to,
            edge_type=EdgeType.PREREQUISITE,
            edge_strength=0.9,
            typical_gap_signal="B를 못 푸는 건 보통 A를 몰라서다",
            notes="강한 선수 관계",
        )
        assert e.from_concept_id == frm
        assert e.to_concept_id == to
        assert e.edge_strength == pytest.approx(0.9)

    def test_self_edge_rejected(self) -> None:
        """from == to → ValidationError(자기엣지 금지)."""
        same = uuid.uuid4()
        with pytest.raises(ValidationError, match="자기 자신을 가리키는 엣지"):
            ConceptEdge(
                from_concept_id=same,
                to_concept_id=same,
                edge_type=EdgeType.ANALOGOUS_TO,
            )

    def test_edge_strength_range_rejected(self) -> None:
        """edge_strength는 0.0-1.0 — 1 초과 거부."""
        with pytest.raises(ValidationError):
            ConceptEdge(
                from_concept_id=uuid.uuid4(),
                to_concept_id=uuid.uuid4(),
                edge_type=EdgeType.EXTENDS,
                edge_strength=1.5,
            )

    def test_missing_required_rejected(self) -> None:
        """from·to·edge_type은 필수(NOT NULL) — 누락 거부."""
        with pytest.raises(ValidationError):
            ConceptEdge(from_concept_id=uuid.uuid4())  # type: ignore[call-arg]

    def test_extra_forbidden(self) -> None:
        """extra='forbid'."""
        with pytest.raises(ValidationError):
            ConceptEdge(  # type: ignore[call-arg]
                from_concept_id=uuid.uuid4(),
                to_concept_id=uuid.uuid4(),
                edge_type=EdgeType.CONTRASTS,
                bogus="x",
            )

    def test_edge_type_enum_value_serialization(self) -> None:
        """use_enum_values → edge_type 문자열 저장."""
        e = ConceptEdge(
            from_concept_id=uuid.uuid4(),
            to_concept_id=uuid.uuid4(),
            edge_type=EdgeType.COMPOSED_OF,
        )
        assert e.model_dump()["edge_type"] == "COMPOSED_OF"


# ──────────────────────────────────────────────────────────────────────
# ProblemConcept — N:M, 복합 PK 요소 required
# ──────────────────────────────────────────────────────────────────────
class TestProblemConcept:
    def test_valid_mapping(self) -> None:
        """problem_id·concept_id·role 필수 + relevance 선택."""
        pid = uuid.uuid4()
        cid = uuid.uuid4()
        pc = ProblemConcept(
            problem_id=pid,
            concept_id=cid,
            relevance=0.95,
            role=ConceptRole.PRIMARY,
        )
        assert pc.problem_id == pid
        assert pc.concept_id == cid
        assert pc.relevance == pytest.approx(0.95)

    def test_role_required(self) -> None:
        """role은 복합 PK 구성요소라 required — 누락 거부."""
        with pytest.raises(ValidationError):
            ProblemConcept(  # type: ignore[call-arg]
                problem_id=uuid.uuid4(), concept_id=uuid.uuid4()
            )

    def test_relevance_range_rejected(self) -> None:
        """relevance는 0.0-1.0 — 1 초과 거부."""
        with pytest.raises(ValidationError):
            ProblemConcept(
                problem_id=uuid.uuid4(),
                concept_id=uuid.uuid4(),
                role=ConceptRole.SUPPORTING,
                relevance=1.5,
            )

    def test_relevance_optional(self) -> None:
        """relevance는 Optional — 생략 가능."""
        pc = ProblemConcept(
            problem_id=uuid.uuid4(),
            concept_id=uuid.uuid4(),
            role=ConceptRole.IMPLICIT,
        )
        assert pc.relevance is None

    def test_extra_forbidden(self) -> None:
        """extra='forbid'."""
        with pytest.raises(ValidationError):
            ProblemConcept(  # type: ignore[call-arg]
                problem_id=uuid.uuid4(),
                concept_id=uuid.uuid4(),
                role=ConceptRole.TESTED,
                bogus="x",
            )

    def test_role_enum_value_serialization(self) -> None:
        """use_enum_values → role 문자열 저장."""
        pc = ProblemConcept(
            problem_id=uuid.uuid4(),
            concept_id=uuid.uuid4(),
            role=ConceptRole.TESTED,
        )
        assert pc.model_dump()["role"] == "TESTED"


# ──────────────────────────────────────────────────────────────────────
# ConceptFusion — concept_ids min_length, fusion_difficulty 범위
# ──────────────────────────────────────────────────────────────────────
class TestConceptFusion:
    def test_minimal_fusion_valid(self) -> None:
        """concept_ids(최소 1개)만으로 생성 — 나머지 기본값."""
        cid = uuid.uuid4()
        f = ConceptFusion(concept_ids=[cid])
        assert isinstance(f.fusion_id, uuid.UUID)
        assert f.concept_ids == [cid]
        assert f.name is None
        assert f.exemplar_problem_ids == []

    def test_full_fields_roundtrip(self) -> None:
        """전 필드 채운 융합 — 값 보존."""
        c1, c2 = uuid.uuid4(), uuid.uuid4()
        ex = uuid.uuid4()
        f = ConceptFusion(
            name="수열의 극한 + 부등식",
            concept_ids=[c1, c2],
            fusion_difficulty=4.0,
            typical_question_pattern="극한값을 부등식으로 가두어 샌드위치 정리 적용",
            exemplar_problem_ids=[ex],
        )
        assert f.concept_ids == [c1, c2]
        assert f.fusion_difficulty == pytest.approx(4.0)
        assert f.exemplar_problem_ids == [ex]

    def test_empty_concept_ids_rejected(self) -> None:
        """concept_ids는 min_length=1(UUID[] NOT NULL) — 빈 배열 거부."""
        with pytest.raises(ValidationError):
            ConceptFusion(concept_ids=[])

    def test_concept_ids_required(self) -> None:
        """concept_ids는 required — 누락 거부."""
        with pytest.raises(ValidationError):
            ConceptFusion()  # type: ignore[call-arg]

    def test_fusion_difficulty_range_rejected(self) -> None:
        """fusion_difficulty는 1.0-5.0(난이도 척도 보수 설정) — 5 초과 거부."""
        with pytest.raises(ValidationError):
            ConceptFusion(concept_ids=[uuid.uuid4()], fusion_difficulty=5.5)

    def test_name_max_length(self) -> None:
        """name은 max_length=200 — 초과 거부."""
        with pytest.raises(ValidationError):
            ConceptFusion(concept_ids=[uuid.uuid4()], name="가" * 201)

    def test_extra_forbidden(self) -> None:
        """extra='forbid'."""
        with pytest.raises(ValidationError):
            ConceptFusion(concept_ids=[uuid.uuid4()], bogus="x")  # type: ignore[call-arg]


# ──────────────────────────────────────────────────────────────────────
# Concept — 노드 필드 거버넌스 가드 (math_dsl_risk_register.md Q10-③ "노드는 의미만")
# ──────────────────────────────────────────────────────────────────────
class TestConceptNodeFieldGovernance:
    """개념 *노드*에 의미 외(렌더·교육과정·프롬프트·런타임·사용자) 필드 재유입을 막는 회귀 가드.

    `extra="forbid"`는 *입력* 미지 필드만 막는다 — 누군가 `Concept`에 `grade_introduced`(교육과정)
    나 `fps`(렌더) 같은 필드를 *모델에 다시 선언*하는 PR은 못 막는다. 교육과정 4필드는 이미
    제거됐으나(Overlay `CurriculumEntry` 이관·rev f3a4b5c6d7e8) 그 부채가 *다시 들어오는* 경로를
    동결한다. 플레이북 "노드에 넣지 말 10가지"(principles_review §3.4)의 실행 가능 게이트다.
    """

    # 노드에 절대 재유입되면 안 되는 필드명(의미 외 관심사) — Q10-③·plays §3.4.
    #   · 교육과정(Overlay 단일 진실): subject·curriculum_version·grade/semester_introduced
    #   · 렌더(L5 클라 책임·표현≠의미): fps·shader·pixel·canvas·color
    #   · 프롬프트/런타임/사용자(외부화 대상): prompt·runtime_state·user_id·session_id
    _FORBIDDEN_NODE_FIELDS = frozenset(
        {
            # 교육과정(노드 비내장·Overlay 이관) — 제거된 부채의 회귀 차단.
            "subject",
            "curriculum_version",
            "grade_introduced",
            "semester_introduced",
            # 렌더 기술(L5 클라·spec 책임) — 노드는 렌더를 모른다.
            "fps",
            "shader",
            "pixel",
            "canvas",
            "color",
            # 시각화 가능성 분류(노드 비내장·Overlay `concept_visualization` 이관) — 재내장 차단.
            # ADR concept_node_layering §1(visualization=노드 비내장)·subject Overlay 선례 동형.
            "visualizability",
            # 본문 근접 자유 서술·자유텍스트 오개념(redaction·Phase 1b 청산) — 재내장 차단.
            #   앞 3개=성취기준·교과서 본문 근접(정본=identity 노드 semantic·ConceptContent),
            #   마지막=자유텍스트 오개념(정본=독립 오개념 카탈로그·CLAUDE.md #6). 2026-07-03 제거.
            "description",
            "formal_definition",
            "intuitive_explanation",
            "common_misconceptions",
            # 프롬프트·런타임·사용자(외부화 — 노드에 결합 금지).
            "prompt",
            "runtime_state",
            "user_id",
            "session_id",
        }
    )

    # 현재 허용 필드 화이트리스트(동결) — 새 필드 추가 PR이 *의식적으로* 이 집합을 갱신하게 한다.
    # "노드는 의미만"(Q10-③) 원칙상 새 필드는 개념의 *의미*여야 하며, 의미 외 필드면 위 금지집합에
    # 들어가야 한다. 이 동결이 그 판단을 코드리뷰로 끌어낸다(조용한 결합 부채 누적 차단).
    _ALLOWED_NODE_FIELDS = frozenset(
        {
            "concept_id",
            "code",
            "source_id",
            "name_ko",
            "name_en",
            "aliases",
            "level",
            "parent_concept_id",
            "is_signature_korean",
            "cognitive_type",
            "recommended_visual_styles",
            "behavior_skills",  # cognition 참조(Phase 2b-2)·concept→skill 브리지·참조 키(본문 아님)
            "intrinsic_difficulty",
            "exam_frequency",
            "weight_in_curriculum",
            "created_at",
            "current_published_version_id",  # 판 관리 포인터(EOS-49 §6.4)·참조 키(본문 아님)
        }
    )

    def test_no_forbidden_fields_present(self) -> None:
        """의미 외(렌더·교육과정·프롬프트·런타임·사용자) 필드가 노드에 *부재*임을 단언."""
        present = set(Concept.model_fields) & self._FORBIDDEN_NODE_FIELDS
        assert present == set(), (
            f"개념 노드에 의미 외 필드 재유입 — {sorted(present)}. 교육과정은 CurriculumEntry "
            "Overlay·렌더는 L5 spec·프롬프트/런타임/사용자는 외부화 대상(Q10-③ '노드는 의미만')."
        )

    def test_field_set_frozen(self) -> None:
        """현재 필드 집합 동결 — 새 필드 추가 시 화이트리스트를 의식적으로 갱신하게 강제.

        실패하면 추가/제거된 필드를 확인하고, *개념의 의미*면 화이트리스트에 추가, *의미 외*면
        금지집합에 넣고 모델에서 제거하라(노드는 의미만·Q10-③).
        """
        assert set(Concept.model_fields) == self._ALLOWED_NODE_FIELDS

    def test_forbidden_and_allowed_disjoint(self) -> None:
        """금지집합과 허용 화이트리스트는 서로소 — 같은 필드가 양쪽에 들어가는 모순 방지."""
        assert self._FORBIDDEN_NODE_FIELDS & self._ALLOWED_NODE_FIELDS == set()
