"""원자 백본 Pydantic 모델 — `AtomConcept` 노드 · `AtomEdge` 엣지.

정본: `docs/data/atom_graph_v1.md`(스키마·§3 redaction·§5 통계) +
마이그레이션 플랜 `/root/.claude/plans/api-cheerful-snowglobe.md`(Phase 1·결정 ①~⑥).

컨벤션(concept_graph/models.py 미러): `ConfigDict(extra="forbid", use_enum_values=True,
str_strip_whitespace=True)` · 관계/축은 `str`-Enum · 불변식은 `@field_validator` · 한국어 docstring.

법적(CLAUDE.md 우선순위 #2·atom_graph_v1.md §3): **K-12 원자의 핵심명제/성취기준내용은
NCIC 성취기준 *본문*** 이라 코퍼스에 절대 싣지 않는다. 그래서 이 모델은 *본문 슬롯을 일부러
두지 않는다*(concept_graph가 description/formal_definition을 슬롯 부재로 구조 차단한 패턴) —
원자는 `standard_codes`(연결성취기준 코드)로만 성취기준과 연결된다. 단, **대학 원자의 핵심명제는
자체작성**(전 513건 self-authored)이라 `core_proposition` 필드로 *보존*한다(redact 아님).
transform이 학교급으로 분기해 K-12는 core_proposition=None으로 강제한다.
"""

from __future__ import annotations

from enum import Enum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, field_validator

from data_pipeline.citation import build_ncic_citation_core

# NCIC 승계 출처 문구(concept_graph.md §1.1 미러) — 그래프 외부 노출·라이선싱 시 동봉 의무.
# 원자 백본은 자체작성이나, standard_codes로 연결한 성취기준 *코드*가 공공누리 1유형이라 동봉한다.
# S2(subject_expansion_readiness.md §9): 과목 종속부는 build_ncic_citation_core가 단일 원천 —
# 합성 방식만 빌더로 바꿨고 **값은 리팩토링 전과 바이트 동일**
# (동결 테스트: tests/data_pipeline/test_citation.py).
SOURCE_CITATION: Final[str] = (
    "원자-성취기준 매핑 근거: "
    + build_ncic_citation_core()
    + ". 원자화·교수학 주석(4요소·원자성)·대학 축은 와이매스 자체작성."
)


class NodeLevel(str, Enum):
    """3단 계층 노드 레벨(결정 ⑤). 원자(세부개념)·소단원(소개념)·단원(개념)."""

    UNIT = "단원"
    SUBUNIT = "소단원"
    ATOM = "세부개념"


class SchoolLevel(str, Enum):
    """학교급(원자 백본 4축 — 대학 신규축 포함). 원본 '초등학교' 등에서 정규화한 값."""

    ELEMENTARY = "초등"
    MIDDLE = "중학"
    HIGH = "고등"
    UNIVERSITY = "대학"


class CognitiveType(str, Enum):
    """인지축(원자_통합마스터 '인지축'). 개념/절차/표상 3종."""

    CONCEPT = "개념"
    PROCEDURE = "절차"
    REPRESENTATION = "표상"


class NodeType(str, Enum):
    """노드유형(원자_통합마스터 '노드유형'). 선행/구성/결과 3종."""

    PRECEDING = "선행"
    CONSTRUCTING = "구성"
    RESULT = "결과"


class AtomRelation(str, Enum):
    """원자 엣지 관계(선수엣지_통합 '관계'). Phase 1은 선수(PREREQUISITE) 단일."""

    PREREQUISITE = "prerequisite"


# enum 값의 단일 진실(테스트·검증 공용). 추가 시 위 Enum만 갱신.
NODE_LEVELS: Final[tuple[str, ...]] = tuple(v.value for v in NodeLevel)
SCHOOL_LEVELS: Final[tuple[str, ...]] = tuple(v.value for v in SchoolLevel)
COGNITIVE_TYPES: Final[tuple[str, ...]] = tuple(v.value for v in CognitiveType)
NODE_TYPES: Final[tuple[str, ...]] = tuple(v.value for v in NodeType)
ATOM_RELATIONS: Final[tuple[str, ...]] = tuple(v.value for v in AtomRelation)

# 엣지 evidence 합성 기본값(원본 엣지가 강도·근거 텍스트 미보유 — concept_graph 방식 미러).
DEFAULT_EDGE_EVIDENCE: Final[str] = "원자 백본 v1"
DEFAULT_EDGE_STRENGTH: Final[float] = 0.8


class AtomConcept(BaseModel):
    """원자 백본 노드 — 원자(세부개념)·소단원(소개념)·단원(개념)을 한 모델로 표현.

    `code`는 PK다 — 원자=원자ID(예 `2수01-01-2`)·소단원=소단원코드(예 `초수연-U1-S1`)·
    단원=단원코드(소단원코드의 `-S` 앞 prefix, 예 `초수연-U1`). 계층은 `parent_code`로 표현한다
    (원자.parent=소단원·소단원.parent=단원·단원.parent=None).

    원자 code 포맷은 *검증하지 않는다* — 원본 K-12 코드(`2수01-01-2`)·대학 코드(`ODE-P07`)가
    이질적이라 단일 정규식이 불가하고, 유일성·dangling은 validate가 컬렉션 레벨로 본다
    (concept_graph가 형식 정규식을 쓴 것과 *의도적으로 다른* 분담 — 원자ID는 코드 파생·형식 다양).

    법적·redaction(§3·CLAUDE.md): K-12 핵심명제(=NCIC 성취기준 본문)를 담을 슬롯을 *두지 않는다*
    — 모델에 본문 필드가 없어 구조적으로 재유입이 차단된다(누수 0). 원자는 `standard_codes`로만
    성취기준과 연결한다. `core_proposition`은 **대학 자체작성 핵심명제 전용**(transform이 K-12는
    None으로 강제). 4요소(오개념·진단·소크라테스)·전이·원자성은 자체/AI 작성이라 보존한다.
    """

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    code: str = Field(
        ...,
        min_length=1,
        description="노드 PK — 원자ID/소단원코드/단원코드. 포맷 다양(검증은 유일성·dangling).",
    )
    name: str = Field(..., min_length=1, description="원자명/소단원명/단원명(빈 문자열 금지).")
    name_display: str | None = Field(
        default=None,
        min_length=1,
        description="표시용 명칭(원자명_표시). 계층 노드는 None.",
    )
    level: NodeLevel = Field(..., description="3단 계층 레벨(단원/소단원/세부개념).")
    parent_code: str | None = Field(
        default=None,
        description="부모 노드 code(원자→소단원·소단원→단원·단원→None).",
    )
    school_level: SchoolLevel = Field(..., description="학교급(초등/중학/고등/대학).")
    grade_band: str | None = Field(
        default=None,
        description="학년/학년군(원자_통합마스터 '학년/학년군'). 계층 노드는 None 가능.",
    )
    subject_area: str | None = Field(
        default=None,
        description="영역/과목(원자_통합마스터 '영역/과목'). 계층 노드는 None 가능.",
    )
    unit: str | None = Field(default=None, description="단원명(원자_통합마스터 '단원').")
    subunit: str | None = Field(default=None, description="소단원명(원자_통합마스터 '소단원').")
    subunit_code: str | None = Field(
        default=None,
        description="소단원코드(원자_통합마스터 '소단원코드'). 원자에만 채움.",
    )
    cognitive_type: CognitiveType | None = Field(
        default=None,
        description="인지축(개념/절차/표상). 원자에만 채움 — 계층 노드는 None.",
    )
    node_type: NodeType | None = Field(
        default=None,
        description="노드유형(선행/구성/결과). 원자에만 채움 — 계층 노드는 None.",
    )
    misconception_type: str | None = Field(
        default=None,
        description="오개념유형(6종). 원자에만 채움.",
    )
    intrinsic_difficulty: int | None = Field(
        default=None,
        ge=1,
        le=5,
        description="난이도 [1, 5]. 원자에만 채움 — 계층 노드는 None.",
    )
    standard_codes: list[str] = Field(
        default_factory=list,
        description=(
            "연결성취기준 NCIC 코드(정규화 후). 본문은 복제 금지 — 코드로만 다리. "
            "대학 원자는 연결성취기준 없음 → []."
        ),
    )
    core_proposition: str | None = Field(
        default=None,
        description=(
            "핵심명제 — **대학 자체작성 전용**(보존). K-12는 NCIC 본문이라 transform이 None 강제"
            "(redact). 본문 슬롯 부재(구조 차단)는 의도이므로 description류 필드 추가 금지."
        ),
    )
    misconception: str | None = Field(
        default=None,
        description="①오개념(자체/AI 작성·Phase 3 소비). 원자에만 채움.",
    )
    diagnostic_item: str | None = Field(
        default=None,
        description="②진단문항(자체/AI 작성·Phase 3 소비). 원자에만 채움.",
    )
    diagnostic_answer: str | None = Field(
        default=None,
        description="②정답·통과기준(자체/AI 작성·Phase 3 소비). 원자에만 채움.",
    )
    diagnostic_signal: str | None = Field(
        default=None,
        description="②미통과·오답신호(자체/AI 작성·Phase 3 소비). 원자에만 채움.",
    )
    socratic: str | None = Field(
        default=None,
        description="③소크라테스질문(자체/AI 작성·Phase 3 소비). 원자에만 채움.",
    )
    transfer: str | None = Field(
        default=None,
        description="④전이(자체/AI 작성). 원자에만 채움.",
    )
    transfer_example: str | None = Field(
        default=None,
        description="④전이예시(자체/AI 작성). 원자에만 채움.",
    )
    atomicity: dict[str, str] = Field(
        default_factory=dict,
        description="원자성a~d(JSONB). 키 'a'..'d' → 값('예' 등). 계층 노드는 빈 dict.",
    )
    notes: str | None = Field(default=None, description="비고(원자_통합마스터 '비고').")
    redacted_fields: list[str] = Field(
        default_factory=list,
        description="이 레코드에서 redact된 필드 마커(예 ['핵심명제/성취기준내용']). 누수 감사용.",
    )
    behavior_skills: list[str] = Field(
        default_factory=list,
        description=(
            "인지 행동 스킬 코드(예 'skill.reasonableness-check', dedup·사전순). 원자에만 채움 — "
            "구 437 코퍼스(concept_graph_v1/concepts.jsonl)가 저작 정본, "
            "concept_atom_crosswalk 경유 union+dedup 전파(S0-2 동일 의미론·SKB-02 corpus 병합)."
            " 단원/소단원·비크로스워크 원자는 빈 리스트."
        ),
    )

    @field_validator("standard_codes", "redacted_fields", "behavior_skills")
    @classmethod
    def _validate_str_list(cls, v: list[str]) -> list[str]:
        """리스트 항목에 빈 문자열 금지(코드·마커 누락 차단)."""
        for item in v:
            if not item or not item.strip():
                raise ValueError(f"빈 항목 금지: {v!r}")
        return v


class AtomEdge(BaseModel):
    """원자 백본 엣지 — `from_유형=원자ID` 선수 엣지(2,213). evidence/strength 합성.

    `(from_code, to_code, relation)` 복합키. `relation_subtype`(관계유형: 원본/소단원내/
    소단원간/학년간/학교급간(추정))은 신규 메타 컬럼. **서술형 엣지(1,007)는 이 모델로 만들지 않고**
    transform이 `narrative_edges_raw`로 패스스루한다(FK 불가 — from이 원자ID가 아닌 서술 문자열).
    """

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    from_code: str = Field(..., min_length=1, description="선수(출발) 원자ID.")
    from_name: str | None = Field(
        default=None, min_length=1, description="선수 원자명(가독·검수용)."
    )
    to_code: str = Field(..., min_length=1, description="후행(도착) 원자ID.")
    to_name: str | None = Field(default=None, min_length=1, description="후행 원자명(가독·검수용).")
    relation: AtomRelation = Field(
        default=AtomRelation.PREREQUISITE, description="관계 유형(Phase 1 선수 단일)."
    )
    relation_subtype: str | None = Field(
        default=None,
        description="관계유형 메타(원본/소단원내/소단원간/학년간/학교급간(추정)).",
    )
    school_link: bool = Field(
        default=False,
        description="학교급연계 여부(원본 '학교급연계'=Y → True). 저신뢰 표기.",
    )
    strength: float = Field(
        default=DEFAULT_EDGE_STRENGTH,
        ge=0.0,
        le=1.0,
        description="관계 강도 [0.0, 1.0](합성).",
    )
    evidence: str = Field(
        default=DEFAULT_EDGE_EVIDENCE,
        min_length=1,
        description="관계 근거(빈 문자열 금지 — 합성 기본값).",
    )


__all__ = [
    "ATOM_RELATIONS",
    "COGNITIVE_TYPES",
    "DEFAULT_EDGE_EVIDENCE",
    "DEFAULT_EDGE_STRENGTH",
    "NODE_LEVELS",
    "NODE_TYPES",
    "SCHOOL_LEVELS",
    "SOURCE_CITATION",
    "AtomConcept",
    "AtomEdge",
    "AtomRelation",
    "CognitiveType",
    "NodeLevel",
    "NodeType",
    "SchoolLevel",
]
