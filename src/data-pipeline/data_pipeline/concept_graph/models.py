"""개념 그래프 Pydantic 모델 — `Concept` 노드 · `ConceptEdge` 엣지.

정본: `docs/data/concept_graph.md`(§2 모델·§2.4 ID 규약·§5 invariant) +
`schemas/v1.1/concept.schema.yaml`·`schemas/v1.1/edge.schema.yaml`.

컨벤션(ncic/models.py·backend schema 답습): `ConfigDict(extra="forbid",
use_enum_values=True, str_strip_whitespace=True)` · 관계/출처는 `str`-Enum · 불변식은
`@field_validator` · 한국어 docstring.

법적(CLAUDE.md·concept_graph.md §1.1): `standard_codes`는 NCIC 성취기준 *코드*만 가리키고
성취기준 *본문(statement)*은 어느 필드에도 복제하지 않는다. 외부 노출 시 `SOURCE_CITATION`
동봉 의무(공공누리 1유형 승계).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from enum import Enum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, field_validator

from data_pipeline.citation import build_ncic_citation_core

# NCIC 승계 출처 문구(concept_graph.md §1.1) — 그래프 외부 노출·라이선싱 시 동봉 의무.
# S2(subject_expansion_readiness.md §9): 과목 종속부는 build_ncic_citation_core가 단일 원천 —
# 합성 방식만 빌더로 바꿨고 **값은 리팩토링 전과 바이트 동일**
# (동결 테스트: tests/data_pipeline/test_citation.py).
SOURCE_CITATION: Final[str] = "개념-성취기준 매핑 근거: " + build_ncic_citation_core()

# concept_id 규약(§2.4) — **2026-07-02 P2d·Part 9 전환**: 교육과정·언어·렌더러 무관 의미론적
# canonical ID `math.<area>.<slug>`(예 'math.geometry.samgakhyeongui-hapdong').
#   math  = 고정 subject(Phase 1 전건 수학),
#   <area> = 교육과정-독립 영역어(소문자 로마자·하이픈 허용, 예 geometry·place-value),
#   <slug> = name_ko의 결정론적 로마자화(hangul_romanize.romanize·충돌 시 -2/-3 접미).
# 2026-06-16 P2a의 `{TRACK}-{AREA}-{NNN}`(학년대=교육과정 결합 안티패턴)을 *되돌린* breaking
# 마이그레이션 — 옛 키(교육과정축 코드·UC)는 `aliases`·`ids.yaml` registry로 보존(추적·롤백).
# ★ 영역어(place-value·ai-math 등)는 하이픈을 포함하므로 area 세그먼트도 하이픈 그룹을 허용한다.
#
# [ADR-009 · ADR-003] 접두(subject)는 정규식 리터럴이 아니라 **코드 상수 집합**이다. 과목이 늘면
# 아래 집합에 토큰 1개를 더하는 것으로 끝나야 하며, 패턴은 이 집합에서 조립한다. 집합을 비우면
# 조립 단계에서 즉시 실패한다(빈 접두가 `.area.slug` 같은 ID를 통과시키는 것을 막는다).
SUBJECT_PREFIXES: Final[frozenset[str]] = frozenset({"math"})

_PREFIX_TOKEN = re.compile(r"[a-z]+")


def build_concept_id_pattern(prefixes: Iterable[str]) -> re.Pattern[str]:
    """접두 유효 집합에서 concept_id 패턴을 조립한다(`<접두>.<area>.<slug>`).

    - 접두 토큰은 소문자 로마자(`[a-z]+`)만 허용한다 — 점·대문자·빈 문자열은 ValueError.
    - 집합이 비어 있으면 ValueError(빈 alternation은 접두 없는 ID를 통과시킨다).
    - 비캡처 그룹 `(?:…)`을 써서 area·slug 쪽 캡처 그룹 번호가 리터럴 시절과 같다.
    - 정렬해서 조립하므로 같은 집합은 항상 같은 패턴 문자열이다(결정론).
    """
    tokens = sorted(set(prefixes))
    if not tokens:
        raise ValueError("concept_id 접두 집합이 비어 있다 — 최소 1개 필요(ADR-009)")
    for token in tokens:
        if not _PREFIX_TOKEN.fullmatch(token):
            raise ValueError(f"concept_id 접두 토큰 규약 위반: {token!r} (소문자 [a-z]+만 허용)")
    alternation = "|".join(tokens)
    return re.compile(rf"^(?:{alternation})\.[a-z]+(-[a-z]+)*\.[a-z0-9]+(-[a-z0-9]+)*$")


CONCEPT_ID_PATTERN: Final[re.Pattern[str]] = build_concept_id_pattern(SUBJECT_PREFIXES)

# 교육과정축 코드 규약(옛 P2a 형식 `{TRACK}-{AREA}-{NNN}`·예 'ELEM-GEO-001') — 이제 정본이 아니라
# `aliases`에 보존하는 **오버레이/별칭("curriculum-axis code")**이다(curriculum_matrix '개념 축').
# 새 PK는 CONCEPT_ID_PATTERN(math.<area>.<slug>)을 쓴다. 이 패턴은 별칭값이 옛 규약 준수인지 확인만.
CURRICULUM_AXIS_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(ELEM|MID|HIGH|RT|OLY)-[A-Z0-9]{2,8}-\d{3}$"
)

# 레거시 UC 규약(전환 *이전* 형식) — `aliases`에 보존하는 옛 키 검증 전용(롤백·하위호환 join).
# 새 PK는 CONCEPT_ID_PATTERN을 쓴다. 이 패턴은 별칭값이 옛 규약을 지키는지 *확인*만 한다.
LEGACY_UC_PATTERN: Final[re.Pattern[str]] = re.compile(r"^UC\.[a-z0-9]+\.[a-z0-9-]+\.[a-z0-9-]+$")


def _require_concept_id(value: str) -> str:
    """concept_id가 새 규약(`math.<area>.<slug>`)을 지키는지 검증(노드 PK·엣지 src/dst 공용)."""
    if not CONCEPT_ID_PATTERN.match(value):
        raise ValueError(
            f"concept_id 규약 위반: {value!r}. 예상 'math.<area>.<slug>' "
            "(area=교육과정-독립 영역어·slug=name_ko 로마자화, 예: 'math.geometry.hapdong')"
        )
    return value


class Relation(str, Enum):
    """개념 관계 유형 — `edge.schema.yaml` values와 1:1.

    주의: `concept_graph.md` 산문은 '6종'이라 적었으나 §2.2 코드블록과 edge.schema.yaml의
    *열거 값은 7종*이다(notation_variant 포함). 열거를 정본으로 채택한다(산문 카운트는 stale).
    """

    PREREQUISITE = "prerequisite"
    GENERALIZATION = "generalization"
    SPECIALIZATION = "specialization"
    CONTRAST = "contrast"
    APPLICATION = "application"
    COMPOSITION = "composition"
    NOTATION_VARIANT = "notation_variant"


class EvidenceSource(str, Enum):
    """엣지 근거의 출처 계열(`edge.schema.yaml`)."""

    NCIC = "ncic"
    CURRICULUM_MATRIX = "curriculum_matrix"
    MATH_EDUCATION_LITERATURE = "math_education_literature"
    EXPERT_REVIEW = "expert_review"


class ReviewStatus(str, Enum):
    """개념 검수 상태 — 적재 보류 표식(concept_graph_dataset_v1.md §4).

    데이터셋 `definition_provenance`가 "수기 검수"면 `REVIEWED`(우선 적재 후보·114건),
    그 외 자동생성·검수필요 계열이면 `PENDING`(전문가 검수 후 적재·289건). 슬라이스 1은
    이 표식만 *부여*하고 게이팅(보류분 제외 적재)은 후속 슬라이스(적재) 몫이다.
    """

    REVIEWED = "reviewed"
    PENDING = "pending"


# 관계·출처·검수상태 enum의 단일 진실(§2.2 "한 곳에서 관리"). 추가 시 위 Enum만 갱신.
RELATION_TYPES: Final[tuple[str, ...]] = tuple(r.value for r in Relation)
EVIDENCE_SOURCES: Final[tuple[str, ...]] = tuple(e.value for e in EvidenceSource)
REVIEW_STATUSES: Final[tuple[str, ...]] = tuple(s.value for s in ReviewStatus)

# 엣지 strength 하한(플레이북 Part 3 "낮은 weight는 제거되나?" — build-time floor 게이트).
# strength가 이 값 미만인 엣지는 *약한 관계*로 간주한다(그래프 dense화·traversal 희석 방어).
# Phase 1 정책상 위반은 **warning**(validate.py `weak_edge`)이며 적재를 막지 않는다(§3.3).
# 현재 데이터는 전 엣지 strength=0.8이라 이 하한은 no-op이다 — 향후 자동 제안·약한 관계가
# 유입될 때를 대비한 단일 진실 임계값(단일 원천: 이 상수만 갱신). 런타임 동적 pruning(소비처
# 생길 때)은 후속 — 여기서는 *데이터 품질 하한*만 명문화한다(premature 기계 금지).
MIN_EDGE_STRENGTH: Final[float] = 0.3


class Concept(BaseModel):
    """개념 그래프 노드 — `concept.schema.yaml` + 데이터셋 v1 풍부 필드 확장.

    `concept_id`는 새 규약(`math.<area>.<slug>`·예 'math.geometry.samgakhyeongui-hapdong') PK
    (curriculum_entry·textbook_mapping과 공유 키). 2026-07-02 P2d로 옛 `{TRACK}-{AREA}-{NNN}`(P2a)를
    *교육과정-독립 의미론 ID*로 전환했고, 추적성은 `source_id`(원천 src_id)·`aliases`(교육과정축 +
    옛 UC + src_id)·`ids.yaml` registry로 보존한다(롤백·하위호환). `standard_codes`는 NCIC 성취기준
    코드 참조(truth source) — 본문은 복제하지 않는다.

    **표시이름(name_ko/en/ja) 비내장(2026-07-02 P2d·Part 9 · Concept Purity)**: 표시이름은 노드
    identity에서 *제거*했고 locale 레이어(`locales/ko.json` 등·canonical_id 키)로 분리한다. 노드는
    언어-무관 식별자(concept_id·source_id·aliases)만 보유 — 표기는 locale 조인으로 재소싱한다(값
    동일·재임베딩 0). canonical `<slug>`가 name_ko에서 *파생*되지만 발급 후 동결이므로, name_en을
    나중에 저작해도 canonical_id는 불변이고 locale만 개선된다(§동결 정책).

    풍부 필드(데이터셋 v1·concept_graph_dataset_v1.md §2 — 2026-06-12 모델 확장 결정):
    `ccss_code`(매칭 CCSS)·`difficulty_tier`(난이도층 0~24)·`review_status`(적재 보류 표식).

    노드 계층(리치 Part 2 9계층 — 물리 내장은 identity+semantic(self-authored)만·나머지는 참조/투영;
    ADR `concept_node_layering_decision.md` §1):
      - identity: `concept_id`·`source_id`·`aliases`·`domain`(표시이름 name_*는 노드 비내장·P2d
        locale 레이어가 단일 진실 — 위 §표시이름 비내장 참조).
      - **semantic(내장·가장 중요)**: core_meaning·intuition·representations(self-authored) +
        difficulty_tier·standard_codes·ccss_code. formal_definition_ref는 참조(본문 미내장).
      - pedagogy: 설명·flashcards는 ConceptContent. 노드엔 선수관계만.
      - visualization: visualization_card_keys(참조만·L5 자산은 노드 밖).
      - assessment: difficulty_tier·ccss_code + assessment_ids(참조).
      - misconception: misconception_codes(카탈로그 참조·실체는 독립 DB).
      - cognition: cognitive_type(후속)·behavior_skills(참조)·cognitive_load·abstraction_required.
      - graph_links: ConceptEdge(별 엔티티·7종) + prerequisite_concept_ids 캐시.
      - ast_binding: formula_refs(FormulaNode 참조·AST 미내장).

    **semantic 복원(2026-07-03 Part 2 전면 채택 Phase 1·Stage B 역방향)**: 리치 기준 은유·허용표현은
    semantic(intuition·representations)이라 노드로 **복원**했다(Stage B의 pedagogy 외부화를 정정).
    값은 raw concepts.jsonl(metaphor·accepted_expressions)에서 소싱 — pre-Stage-B와 바이트 동일
    (재임베딩 0). 단 **self-authored만**: 자유텍스트 오개념 misconception_text는 여전히 노드 비내장
    (독립 오개념 DB·CLAUDE.md #6), 성취기준 본문 근접 description·formal_definition도 비내장.

    법적·redaction(concept_graph_dataset_v1.md §3·CLAUDE.md): 성취기준 *본문* 근접 복제
    위험인 `description`·`formal_definition`은 이 모델에 **일부러 부재** — 모델에 슬롯이
    없어 구조적으로 재유입이 차단된다(누수 0). 이 부재는 의도이므로 추가 금지.
    """

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    concept_id: str = Field(
        ...,
        description=(
            "concept_id (PK). 'math.<area>.<slug>'(예 'math.geometry.samgakhyeongui-hapdong'). "
            "2026-07-02 P2d로 옛 {TRACK}-{AREA}-{NNN}를 교육과정-독립 의미론 ID로 전환(breaking) — "
            "추적성은 source_id·aliases·ids.yaml로 보존."
        ),
    )
    source_id: str = Field(
        ...,
        min_length=1,
        description=(
            "원천 데이터셋 src_id(예 'N1'·'HK01'·'H:12대수01-01'). 재ID 전 식별자 보존 — "
            "concept_id가 src_id에서 *파생*되었음을 추적(롤백·재현)."
        ),
    )
    aliases: list[str] = Field(
        default_factory=list,
        description=(
            "옛 키 별칭 목록 — [교육과정축 코드({TRACK}-{AREA}-{NNN}), 레거시 UC, src_id]. 새 "
            "concept_id로 전환한 뒤에도 옛 키·원천 키로 join/조회하게 보존(하위호환·matrix 개념축)."
        ),
    )
    domain: str = Field(
        ..., min_length=1, description="영역명(NCIC 영역 어휘와 정렬, 예 '미적분')."
    )
    grade_band_hint: str | None = Field(
        default=None,
        description="전형적 도입 학년군(NCIC grade_band 어휘 재사용). 단정 아닌 힌트.",
    )
    prerequisite_concept_ids: list[str] = Field(
        default_factory=list,
        description="선수개념 concept_id 목록. Edge(prerequisite)와 중복 저장(조회 캐시).",
    )
    misconception_codes: list[str] = Field(
        default_factory=list,
        description="오개념 카탈로그 키(Phase 1 30개 — dangling 가능, 검증은 경고).",
    )
    visualization_card_keys: list[str] = Field(
        default_factory=list,
        description="L5 시각화 자산 키(L1은 참조만 — dangling 가능, 검증은 경고).",
    )
    standard_codes: list[str] = Field(
        default_factory=list,
        description="매핑된 NCIC 성취기준 코드(truth source 연결). 본문은 복제 금지.",
    )
    ccss_code: str | None = Field(
        default=None,
        description="매칭 미국 CCSS 코드(국제 비교 축). CCSS 본문(statement)은 복제 금지.",
    )
    difficulty_tier: int | None = Field(
        default=None,
        ge=0,
        le=24,
        description="난이도층 [0, 24](데이터셋 v1). 0=가장 기초.",
    )
    review_status: ReviewStatus = Field(
        default=ReviewStatus.PENDING,
        description=(
            "적재 보류 표식. definition_provenance가 '수기 검수'면 reviewed, "
            "그 외 자동·검수필요면 pending(§4). 게이팅은 후속 적재 슬라이스 몫."
        ),
    )
    notes: str | None = Field(
        default=None,
        description="전문가 검수 메모. 개념 합치기·쪼개기 이력도 기록(ID 안정성 §3.5).",
    )
    # ── semantic 계층(리치 9계층·"가장 중요") — self-authored만(성취기준 본문 금지·redaction) ──
    core_meaning: str | None = Field(
        default=None,
        description="핵심 의미 1줄(자체 작성·리치 semantic.coreMeaning). 현재 코퍼스 부재→None.",
    )
    intuition: str | None = Field(
        default=None,
        description="직관적 은유(리치 semantic.intuition·= metaphor 복원·raw 소싱).",
    )
    representations: str | None = Field(
        default=None,
        description="허용 표현형(리치 semantic.representations·= accepted_expressions 복원).",
    )
    formal_definition_ref: str | None = Field(
        default=None,
        description=(
            "형식 정의 *참조 키*(ConceptContent.formal_definition_internal·본문 미내장·redaction). "
            "성취기준·교과서 본문은 노드에 담지 않는다 — 참조만·초기 None."
        ),
    )
    # ── cognition 계층(리치 9계층) — 스칼라/참조만(자유텍스트 금지) ──
    behavior_skills: list[str] = Field(
        default_factory=list,
        description="행동영역(SkillNode·Phase 2) 참조 키. 초기 dangling 허용(신규 엣지 타입 0).",
    )
    cognitive_load: int | None = Field(
        default=None, ge=1, le=5, description="인지 부하 [1,5](리치 cognitiveLoad). 초기 None."
    )
    abstraction_required: int | None = Field(
        default=None,
        ge=1,
        le=5,
        description="요구 추상화 수준 [1,5](리치 abstractionRequired). 초기 None.",
    )
    # ── assessment 계층(참조) ──
    assessment_ids: list[str] = Field(
        default_factory=list,
        description="평가 자산(AssessmentNode) 참조 키. 초기 dangling 허용.",
    )
    # ── ast_binding 계층(참조) — AST는 참조만(엔진 미내장·Phase 5 FormulaNode) ──
    formula_refs: list[str] = Field(
        default_factory=list,
        description="canonical formula(FormulaNode·Phase 5) 참조 키. AST 참조만·초기 dangling.",
    )

    @field_validator("concept_id")
    @classmethod
    def _validate_concept_id(cls, v: str) -> str:
        """concept_id가 새 규약(`math.<area>.<slug>`)을 지키는지(§2.4)."""
        return _require_concept_id(v)

    @field_validator("aliases")
    @classmethod
    def _validate_aliases(cls, v: list[str]) -> list[str]:
        """별칭은 빈 문자열 금지(추적성 키 누락 차단). 형식 자체는 자유 — 옛 UC·src_id 혼재 허용."""
        for alias in v:
            if not alias or not alias.strip():
                raise ValueError(f"aliases에 빈 별칭 금지: {v!r}")
        return v


class ConceptEdge(BaseModel):
    """개념 그래프 엣지 — `edge.schema.yaml`.

    `(src_concept_id, dst_concept_id, relation)` 복합키. `evidence`는 빈 문자열 금지 —
    근거 없는 엣지를 차단한다(§3.2 관계 판정의 주관성 방어). `strength`는 [0.0, 1.0].
    """

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    src_concept_id: str = Field(..., description="관계 출발 개념(canonical concept_id).")
    dst_concept_id: str = Field(..., description="관계 도착 개념(canonical concept_id).")
    relation: Relation = Field(..., description="관계 유형(7종 enum). 6종 산문은 stale.")
    strength: float = Field(..., ge=0.0, le=1.0, description="관계 강도 [0.0, 1.0].")
    evidence: str = Field(
        ...,
        min_length=1,
        description="관계 판단 근거(빈 문자열 금지 — 근거 없는 엣지 차단).",
    )
    evidence_source: EvidenceSource = Field(..., description="근거 출처 계열(4종 enum).")

    @field_validator("src_concept_id", "dst_concept_id")
    @classmethod
    def _validate_endpoints(cls, v: str) -> str:
        """엣지 양끝도 canonical 규약을 지키는지(노드 PK와 동일 키 공간)."""
        return _require_concept_id(v)
