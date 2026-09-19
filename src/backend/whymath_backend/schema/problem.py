"""Schema v1.0 도메인1 Problem 모델 (Pydantic).

설계 정본: `schemas/v1.0/schema_v1.0.md` §3.1(`problem` 테이블 DDL, 50+필드)·
§3.2(`problem_step`·`problem_relation`).

Phase 메모: 코드베이스 전체가 *Pydantic-schema-only*(DB 미배포) — 이 슬라이스도 순수
Pydantic 모델이다. SQLAlchemy/alembic 매핑은 후속 Phase(`ncic/models.py` 동일 패턴).

컨벤션(`l3/models.py` 답습):
  - `ConfigDict(extra="forbid", use_enum_values=True, str_strip_whitespace=True)`.
  - enum은 `enums.py`의 `class X(str, Enum)`.
  - 불변식은 `@model_validator(mode="after")`.
  - 공유 베이스 클래스 없음(각 모델 독립) — 단 하나의 예외가 SEC-24(원 SEC-15) 공개
    투영이다: `PublicProblem`(공개·학생 대면 기반) ⊂ `Problem`(내부 정본·정답류 6필드
    추가), `PublicProblemStep` ⊂ `ProblemStep`(기대답·흔한실수·흔한오류 3필드 추가).
    방향이 허용목록을 만든다(`schema/assessment.py` `StudentAssessment` ⊂ `Assessment`·
    ASM-07 선례 동형).

타입 매핑 판단(DDL → Pydantic):
  - `UUID PK` → `uuid.UUID = Field(default_factory=uuid4)`
  - `TEXT[]` → `list[str]`
  - `JSONB` → 의미가 있는 곳은 작은 서브모델(`conditions_parsed` → `list[Condition]`),
    자유형(`source_detail`·`answer_constraint`·`ebs_source` 등)은 `dict[str, ...]`
  - `DECIMAL` → `float`
  - `TIMESTAMPTZ` → `datetime`
  - `persona_fit` → `dict[Persona, float]`(페르소나별 적합도 0~1)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from whymath_backend.schema.enums import (
    AnswerFormat,
    BloomLevel,
    Curriculum,
    ExamType,
    Persona,
    QuestionFormat,
    ReasoningType,
    RelationType,
    RequiredDepth,
    ReviewStatus,
    ScoringType,
    SignaturePattern,
    SourceType,
    StepType,
    Subject,
    VisualType,
)
from whymath_backend.schema.visualization import Visualization

# ──────────────────────────────────────────────────────────────────────────
# 본문 미보유(구조 메타 전용) source_type — 법적 교정의 대상 집합
# (MEMORY 2026-05-28: 평가원·EBS·검정교과서 본문 미보유, 저작권 가이드 v2.0 §32 단서)
# ──────────────────────────────────────────────────────────────────────────
METADATA_ONLY_SOURCES: frozenset[SourceType] = frozenset(
    {SourceType.평가원, SourceType.EBS, SourceType.교과서}
)
"""이 출처의 레코드는 *구조 메타데이터 참조 전용* — 본문 필드가 비어야 한다.

`source_detail`/`ebs_source`에 단원·코드·문항번호만 둔다. 학생에게 노출·저장되는
실제 본문은 `SourceType.자체생성`(WHYMATH_GENERATED) 레코드만 가질 수 있다.

**공개 이름인 이유**(EOS-19): 같은 집합이 `l6/_shared.py`에 한 벌 더 있었고, 그 중복의 명시된
사유가 "여기가 private이라 import할 수 없다"였다. 저작권 차단 집합이 두 곳에 있으면 한쪽만
고쳐지는 날 *노출 게이트가 갈라진다* — 법적 축에서 가장 위험한 형태의 드리프트다. 이름을 열어
그 사유를 없앴고, L6·L2는 이제 이 **하나**를 가리킨다. 기존 참조를 위해 아래 private 별칭은
남긴다(같은 객체 — 드리프트 불가).
"""

#: 구 이름 별칭 — `schema.provenance`·`whs.self_evolution` 등 기존 참조 보존용(동일 객체).
_METADATA_ONLY_SOURCES: frozenset[SourceType] = METADATA_ONLY_SOURCES

# ──────────────────────────────────────────────────────────────────────────
# SEC-24(원 SEC-15) — 공개(무인증·학생 대면) 응답에서 **키 자체가 없어야 하는** 정답류 필드
# (`functional_security_audit_2026-08-08.md` M1 · 저작권 강제-비움과는 독립 축)
# ──────────────────────────────────────────────────────────────────────────
#: 공개 투영(`PublicProblem`)에 자리가 없는 `Problem`의 정답류 필드 — 거버넌스 테스트
#: (`tests/backend/api/test_problems_public_projection.py`)가 함께 읽는 단일 진실 원천.
#: `answer`·`answer_explanation`·`distractor_map`은 감사 M1이 지목한 직접 노출이고,
#: `multiple_answers`(복수 정답 후보 자유형)·`answer_transform`(예: {"p":3,"q":5} — 정답
#: 성분 직접 포함)·`answer_constraint`(자유형 제약 — min==max 등으로 정답 유도 가능)는
#: 전 필드 실사에서 추가로 판정한 *정답 유도 가능* 필드다. 공식 Flutter 클라의 안전
#: 주석(`problem_models.dart` — answer 계열 5필드 의도적 미선언)과도 정합.
PUBLIC_HIDDEN_ANSWER_FIELDS: frozenset[str] = frozenset(
    {
        "answer",
        "answer_explanation",
        "distractor_map",
        "multiple_answers",
        "answer_transform",
        "answer_constraint",
    }
)

#: 공개 투영(`PublicProblemStep`)에 자리가 없는 `ProblemStep`의 정답·힌트류 필드.
#: `expected_answer`는 단계별 정답(S4-09 승격 어댑터가 `SolutionStep.content`를 여기 싣는다)
#: 이고, `common_mistakes`는 [{"error","hint"}] 힌트류라 사전 일괄 노출이 Polya 단계별 제공
#: 원칙·오개념 reactive retrieval(preload 금지)과 상충한다 — 코치(L4)가 서버 내부에서
#: 반응적으로만 쓴다. `common_errors`(S4-09 additive)는 같은 축의 오개념 서술 목록이라
#: 이식 시 함께 비공개로 판정했다(허용목록 원칙: 새 필드는 기본 비공개 쪽에 둔다).
PUBLIC_HIDDEN_STEP_ANSWER_FIELDS: frozenset[str] = frozenset(
    {
        "expected_answer",
        "common_mistakes",
        "common_errors",
    }
)

#: 공개 투영(`PublicProblem`)에 자리가 없는 `Problem`의 **운영 메타** 필드 — 격리 축(EOS-71).
#: 정답류(`PUBLIC_HIDDEN_ANSWER_FIELDS`)와 **다른 축이라 집합을 합치지 않는다**: 전자는 "교수학·
#: 보안상 학생에게 주면 안 되는 것"(정답 노출 금지·SEC-24)이고 이쪽은 "운영자만 알면 되는 것"
#: (격리 사유·시각)이다. 합치면 한 축의 완화 압력이 다른 축까지 조용히 열고, "왜 안 나가는가"를
#: 구분할 수 없다(`is_exposable`(저작권)/`is_review_cleared`(검수) 두 축 분리와 같은 논거).
#: 격리 사유를 공개 투영에 두지 않는 이유: `api/problems.py` GET 4종은 **무인증**이라 여기 자리를
#: 만드는 순간 운영 판단 메모(실중복 판정·출제 오류 서술 등)가 그대로 공개된다 — 애초에 샐 표면을
#: 만들지 않는다(허용목록 원칙: 새 필드는 기본 비공개 쪽). 계약 정본은
#: `docs/standards/problem_quarantine_contract.md` §3·§4.
PUBLIC_HIDDEN_OPS_FIELDS: frozenset[str] = frozenset(
    {
        "quarantine_reason",
        "quarantined_at",
    }
)


# ──────────────────────────────────────────────────────────────────────────
# 서브모델: 발문 조건 (§3.1 conditions_parsed JSONB)
# ──────────────────────────────────────────────────────────────────────────
class Condition(BaseModel):
    """발문의 (가)(나)(다) 조건 1개 — §3.1 `conditions_parsed` JSONB 원소.

    예: {"label":"가", "text":"f(x)는 실수 전체에서 미분가능",
         "formal":"differentiable(f, R)"}
    """

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    label: str = Field(..., description="조건 라벨 (예: '가', '나', '다')")
    text: str = Field(..., description="조건 자연어 본문")
    formal: str | None = Field(
        default=None,
        description="조건의 형식(수식) 표현 (선택)",
    )


# ──────────────────────────────────────────────────────────────────────────
# 서브모델: SchemaVersion — EOS Content Schema 계약 버전 (011_2)
# ──────────────────────────────────────────────────────────────────────────
class SchemaVersion(BaseModel):
    """콘텐츠가 따르는 EOS Content Schema 계약 버전.

    콘텐츠 자체의 버전(content_version)과는 별개이며, Contract 변경 시
    하위호환/호환성 판정에 사용. Major.Minor.Patch 형식을 권장.
    """

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    name: str = Field(
        default="whymath-problem",
        description="스키마 네임스페이스/이름",
        min_length=1,
    )
    version: str = Field(
        default="1.1.0",
        description="스키마 버전 (Semantic Versioning 권장)",
        min_length=1,
    )


# ──────────────────────────────────────────────────────────────────────────
# 서브모델: MathExtension — 수학 과목 확장 (011_2)
# ──────────────────────────────────────────────────────────────────────────
class MathExtension(BaseModel):
    """수학 문항에 특화된 확장 필드 — Core Problem Schema가 아닌 math extension으로 분리.

    011_2 Subject-neutral Content Contract: 과목 특화 필드는 Core가 아니라
    Domain Extension으로 분리해 다른 과목(물리·역사 등)이 다른 extension을
    사용할 수 있도록 한다.

    **SEC-24 경계**: `answer_transform`·`answer_constraint`는 정답 유도 가능 필드로
    `PublicProblem`에는 노출되지 않는다 — `PublicProblem.from_problem`이 이들을
    제거하고 `MathExtensionPublic`으로 검증.
    """

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    answer_transform: dict[str, Any] | None = Field(
        default=None,
        description='자연수 답 변환 패턴 {"type":"p_plus_q","p":3,"q":5} 등(자유형 JSONB)',
    )
    answer_constraint: dict[str, Any] | None = Field(
        default=None,
        description='정답 제약 {"min":1,"max":999,"is_natural":true} 등(자유형 JSONB)',
    )
    signature_patterns: list[SignaturePattern] = Field(
        default_factory=list,
        description="한국 수능 시그니처 패턴 배열(10종 중)",
    )
    requires_graph_sketch: bool = Field(
        default=False,
        description="그래프를 그려야 풀리는가",
    )
    sketch_step_count: int | None = Field(
        default=None,
        description="개형 추론 단계 수(보통 5-6)",
        ge=0,
    )


#: legacy top-level과 `extensions.math`가 공유하는 필드 이름 — 두 축의 동기화
#: (`Problem._sync_math_extensions`)가 도는 유일한 목록. 두 축이 같은 표를 보게 하려고
#: 상수로 뽑았다 — 필드를 늘리면 여기만 고치면 된다.
MATH_EXTENSION_FIELDS: tuple[str, ...] = (
    "answer_transform",
    "answer_constraint",
    "signature_patterns",
    "requires_graph_sketch",
    "sketch_step_count",
)


# ──────────────────────────────────────────────────────────────────────────
# 서브모델: MathExtensionPublic — 공개 투영용 수학 확장 (SEC-24)
# ──────────────────────────────────────────────────────────────────────────
class MathExtensionPublic(BaseModel):
    """공개 투영(`PublicProblem`)용 수학 확장 — 정답 유도 가능 필드 제외.

    `PublicProblem.from_problem`이 `Problem.extensions.math`에서
    `answer_transform`·`answer_constraint`를 제거한 뒤 이 모델로 검증한다.
    """

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    signature_patterns: list[SignaturePattern] = Field(
        default_factory=list,
        description="한국 수능 시그니처 패턴 배열(10종 중)",
    )
    requires_graph_sketch: bool = Field(
        default=False,
        description="그래프를 그려야 풀리는가",
    )
    sketch_step_count: int | None = Field(
        default=None,
        description="개형 추론 단계 수(보통 5-6)",
        ge=0,
    )


# ──────────────────────────────────────────────────────────────────────────
# 서브모델: ProblemExtensions — 과목별 확장 묶음 (011_2)
# ──────────────────────────────────────────────────────────────────────────
class ProblemExtensions(BaseModel):
    """Subject-neutral Core를 확장하는 과목별 payload 묶음.

    과목 추가 시 math/physics/history 등의 서브 필드를 추가하지만,
    Core API는 그대로 유지. 현재는 math extension만 정의.
    """

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    math: MathExtension | None = Field(
        default=None,
        description="수학 과목 확장",
    )


# ──────────────────────────────────────────────────────────────────────────
# 서브모델: ProblemExtensionsPublic — 공개 투영용 과목별 확장 묶음
# ──────────────────────────────────────────────────────────────────────────
class ProblemExtensionsPublic(BaseModel):
    """공개 투영(`PublicProblem`)용 과목별 확장 묶음.

    정답 유도 가능 필드를 제외한 `MathExtensionPublic`만 포함.
    """

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    math: MathExtensionPublic | None = Field(
        default=None,
        description="수학 과목 확장(공개 투영)",
    )


# ──────────────────────────────────────────────────────────────────────────
# 서브모델: DistractorEntry (객관식 오답 선지 → 오개념 매핑)
# ──────────────────────────────────────────────────────────────────────────
class DistractorEntry(BaseModel):
    """객관식 *오답 선지 1개* → 오개념 코드 매핑 — `Problem.distractor_map` 원소.

    객관식 문항의 *오답 선지*(distractor)는 보통 *특정 오개념*이 만들어낸 값이다. 이 엔트리는
    "몇 번째 선지(`choice_index`)가 어떤 오개념(`misconception_id`)에서 비롯됐는가"를 담아,
    학생이 고른 오답을 오개념으로 *역추적*하거나 *자체 동등문제*의 오답을 설명하는 데 쓴다.

    **레이어 규칙(CLAUDE.md 역방향 의존 금지)**: 이 L1 모델은 *구조 검증만* 한다 — `choice_index`가
    음수 아님·`misconception_id`가 비지 않음 같은 형태만 본다. `misconception_id`가 정본 카탈로그
    (`l4.misconception.catalog.CATALOG_BY_ID`)에 *실재*하는지의 **참조 무결성**은 L4 검증자
    (`l4/misconception/validate.py`)가 본다 — L1은 L4를 *알지 못하므로* 여기서 카탈로그를
    import하지 않는다(L4→L1 방향만 허용). `op_code`도 같은 이유로 여기선 문자열 형태만 본다.

    **저작권 레일(CLAUDE.md 우선순위 #2)**: `op_code`는 *추상 오류연산* op-code(예:
    'power-distributed-no-cross-term')일 뿐 평가원·EBS·교과서의 *선지 본문* 복제가 아니다 —
    선지 텍스트 자체는 담지 않는다(`l4/misconception/distractor.py` 설계와 정합).
    """

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    choice_index: int = Field(
        ...,
        description="오답 선지의 0-기반 인덱스(`Problem.choices` 위치). 정답 선지는 제외한다.",
        ge=0,
    )
    misconception_id: str = Field(
        ...,
        description=(
            "이 오답을 유발한 오개념 — 정본 `l4.misconception.catalog.CATALOG_BY_ID`의 id "
            "(kebab-case). L1은 형태(비지 않음)만 검증하고 카탈로그 실재 여부는 L4 검증자 소관."
        ),
        min_length=1,
    )
    op_code: str | None = Field(
        default=None,
        description=(
            "추상 오류연산 op-code(선택) — `l4.misconception.distractor.DISTRACTOR_BY_ID`의 키. "
            "*일반 오류연산 서술*을 가리키는 식별자일 뿐 평가원/EBS 선지 본문 복제가 아니다(저작권 "
            "레일). NULL이면 op-code 미상(오개념만 매핑). 카탈로그 실재·정합 검증은 L4 소관."
        ),
    )


# ──────────────────────────────────────────────────────────────────────────
# 공개 투영: PublicProblem (SEC-24(원 SEC-15) — 무인증·학생 대면 응답 정본)
# ──────────────────────────────────────────────────────────────────────────
class PublicProblem(BaseModel):
    """문제의 **공개(무인증·학생 대면) 응답 정본** — 정답류 필드에 자리가 없다(SEC-24).

    `Problem`(내부 정본)에서 정답류(`PUBLIC_HIDDEN_ANSWER_FIELDS` 6종)를 **뺀 것이
    아니라**, 이쪽이 기반이고 `Problem`이 그 6필드를 *더한다*. 방향이 중요하다 —
    나중에 누가 `Problem`에 새 정답류 필드를 붙여도 공개 응답에는 자동으로 새지
    않는다(허용목록이지 차단목록이 아니다 · `schema/assessment.py` `StudentAssessment`
    ⊂ `Assessment` ASM-07 선례 동형).

    **왜 런타임 필터가 아닌가**: `response_model_exclude` 같은 필터는 데코레이터 인자
    한 줄이 빠지면 조용히 무력화되고 OpenAPI 광고도 계속된다. 필터는 꺼질 수 있으나
    *필드의 부재*는 꺼지지 않는다(`PED-08` 노출 계약 ③ 선례 — 키 부재가 계약).

    **사고 경위**(`docs/reviews/functional_security_audit_2026-08-08.md` M1): SEC-07
    D1은 문항 *본문·메타*의 공개 카탈로그 결정이었지 정답 동봉 결정이 아니었는데,
    저작권 강제-비움(`_METADATA_ONLY_SOURCES`)이 평가원/EBS/교과서 *본문*만 다뤄
    자체생성 문항의 `answer` 등이 무인증 GET에 그대로 나가고 있었다(의도가 아니라
    누락). "막혔을 때 바로 정답 제공 금지"(CLAUDE.md 절대 금기·우선순위 #3 교수학 ≫
    #5 UX)의 기계적 집행이 이 모델이다. **재량 판단 명시**: 닫는 것은 가역이다 —
    Kiki가 D1을 정답까지 공개로 확장하기로 결정하면 라우터의 response_model을 되돌리면
    된다(여는 것은 상시 위험이라 안전측으로 닫았다).
    """

    model_config = ConfigDict(
        # 추가 필드 금지 — Pydantic 모델이 스키마의 단일 진실
        extra="forbid",
        # 직렬화 시 enum 값을 그대로(한글 값 보존)
        use_enum_values=True,
        # 문자열 양끝 공백 제거
        str_strip_whitespace=True,
    )

    @classmethod
    def from_problem(cls, problem: Problem) -> PublicProblem:
        """내부 정본 → 공개 투영. 정답류 필드는 애초에 대상 모델에 자리가 없다.

        `model_dump(exclude=...)` 후 재검증 — 값이 채워진 내부 정본을 넣어도 정답류는
        변환에서 구조적으로 사라진다(ASM-07 `from_assessment` 동형).

        제외 집합은 **두 축의 합집합**이다(EOS-71): 정답류(`PUBLIC_HIDDEN_ANSWER_FIELDS`) +
        운영 메타(`PUBLIC_HIDDEN_OPS_FIELDS` — 격리 사유·시각). 두 집합을 하나로 합쳐 두지 않는
        이유는 각 상수의 주석에 있다(축이 다르면 완화 압력도 따로 와야 한다). 여기서 합집합을
        쓰는 것은 *투영 연산*이지 축의 병합이 아니다.

        **중첩 축(011_2·S1-16)**: top-level 제외만으로는 부족하다 — 같은 정답 유도 필드가
        `extensions.math` 안에도 산다. 그쪽도 제거한 뒤 `MathExtensionPublic`으로 검증해야
        SEC-24 "키 부재" 계약이 중첩 필드에서 뚫리지 않는다. 두 축(평면 제외·중첩 제거)은
        서로를 대체하지 않으므로 **둘 다** 적용한다.
        """
        hidden = set(PUBLIC_HIDDEN_ANSWER_FIELDS | PUBLIC_HIDDEN_OPS_FIELDS)
        data = problem.model_dump(exclude=hidden)
        math_ext = (
            data.get("extensions", {}).get("math")
            if isinstance(data.get("extensions"), dict)
            else None
        )
        if isinstance(math_ext, dict):
            math_ext.pop("answer_transform", None)
            math_ext.pop("answer_constraint", None)
        return cls.model_validate(data)

    # ===== 스키마 계약 버전 (011_2) =====
    schema_version: SchemaVersion = Field(
        default_factory=SchemaVersion,
        description="EOS Content Schema 계약 버전 (Content Version과 별개)",
    )

    # ===== 과목별 확장 (011_2) =====
    extensions: ProblemExtensionsPublic = Field(
        default_factory=ProblemExtensionsPublic,
        description="과목별 확장 payload — Core Schema에 과목 특화 필드를 직접 넣지 않음",
    )

    # ===== 기본 식별 =====
    problem_id: uuid.UUID = Field(
        default_factory=uuid4,
        description="문제 PK (UUID)",
    )
    external_id: str | None = Field(
        default=None,
        description="평가원/EBS 원본 ID(구조 식별자, UNIQUE)",
        max_length=64,
    )
    slug: str | None = Field(
        default=None,
        description="사람이 읽는 식별자(UNIQUE)",
        max_length=128,
    )
    identity_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "변형 계열 식별자(Identity·Canonical 분리·S4-18) — 원본과 그 rephrase 등 "
            "변형들이 공유하는 고정 값. problem_id는 개체마다 절대 불변, identity_id로만 "
            "'같은 문제의 다른 표현' 계열을 묶는다. None=계열 없음(단일 개체)."
        ),
    )

    # ===== 출처 =====
    source_type: SourceType = Field(..., description="출처 — 평가원/EBS/AIHub/자체생성 등")
    source_detail: dict[str, Any] | None = Field(
        default=None,
        description="출처 구조 메타 {publisher, year, edition, page} 등(본문 X)",
    )

    # ===== 시험 컨텍스트 =====
    exam_type: ExamType | None = Field(
        default=None,
        description="시험 유형 — 수능/모평/학평/EBS교재/N제/자체생성",
    )
    exam_year: int | None = Field(default=None, description="학년도 (예: 2026)")
    exam_month: int | None = Field(
        default=None,
        description="시행 월 (6/9/11 등)",
        ge=1,
        le=12,
    )
    problem_number: int | None = Field(
        default=None,
        description="문항 번호 (예: 22/30)",
        ge=1,
    )
    exam_authority_weight: float | None = Field(
        default=None,
        description="출처 권위 가중치 — 학평0.5/모평0.8/수능1.0",
        ge=0.0,
        le=1.0,
    )

    # ===== 교육과정 버전 =====
    # 문항 본질 속성(개정판 정합)·제거 금지 — L6 게이트 ③ 살아있는 소비처(오등록 상환
    # 2026-07-02·`Curriculum` docstring). 개념 노드와 달리 Overlay 이관 대상 아님.
    curriculum_version: Curriculum = Field(..., description="교육과정 버전(2015/2022 개정 등)")
    valid_from_year: int = Field(..., description="적용 시작 학년도(예: 2014)")
    valid_to_year: int | None = Field(
        default=None,
        description="적용 종료 학년도(NULL이면 현재까지)",
    )

    # ===== 과목·단원 =====
    subject: Subject = Field(..., description="과목 — 공통/미적분/확통/기하/인공지능수학")
    # P3a 신규: domain은 subject(과목)보다 세분, topic(주제)보다 광역인 *광역 영역 코드*.
    # subject=미적분 < domain=미분법/적분법 < (topic) < subunit=소단원의 위계. nullable·점진 채움.
    domain: str | None = Field(
        default=None,
        description="광역 영역 코드 — subject보다 세분·topic보다 광역(예: 'CAL-DIFF')",
        max_length=64,
    )
    unit_codes: list[str] = Field(
        ...,
        description="단원 코드 배열 (예: ['CAL-INT-DEF', 'FUN-COMPOSITE'])",
        min_length=1,
    )
    # P3a 신규: 소단원명(자연어). unit_codes(코드 배열)와 다른 *사람이 읽는 소단원 이름*.
    subunit: str | None = Field(
        default=None,
        description="소단원명 (예: '합성함수의 미분')",
        max_length=128,
    )

    # ===== 문항 형식 =====
    question_format: QuestionFormat | None = Field(
        default=None,
        description="문항 형식 — 객관식/단답형/합답형/서술형",
    )
    points: int | None = Field(default=None, description="배점 (2/3/4점)", ge=0)
    answer_format: AnswerFormat | None = Field(
        default=None,
        description="정답 형식 — 자연수/분수/실수/식",
    )
    # P3a 신규: 문항이 요구하는 인지 수준(개정 Bloom 6단계)·채점 유형. 문항 형식·난이도와 다른 축.
    bloom_level: BloomLevel | None = Field(
        default=None,
        description="Bloom 인지 수준 — REMEMBER/UNDERSTAND/APPLY/ANALYZE/EVALUATE/CREATE",
    )
    scoring_type: ScoringType | None = Field(
        default=None,
        description="채점 유형 — 정오답/진단/부분점수/시간/루브릭",
    )
    # (answer_constraint·answer_transform은 정답 유도 가능 필드 — Problem 서브클래스로 이동,
    #  SEC-24(원 SEC-15) `PUBLIC_HIDDEN_ANSWER_FIELDS` 참조)

    # ===== 본문(공개 가능 축) =====
    # 법적 교정: 평가원/EBS/교과서 출처면 question_text/answer_explanation/choices는 비어야 함
    # (불변식은 Problem 서브클래스의 validator가 강제 — answer_explanation이 그쪽에 있으므로).
    question_text: str | None = Field(
        default=None,
        description="발문 원문(자체생성만 보유; 평가원/EBS/교과서는 비어야 함)",
    )
    question_text_md: str | None = Field(
        default=None,
        description="마크다운+LaTeX 발문",
    )
    question_image_uri: str | None = Field(
        default=None,
        description="도형/그래프 이미지 URI(MinIO)",
    )
    choices: list[str] | None = Field(
        default=None,
        description="객관식 보기(자체생성만; 평가원/EBS/교과서는 비어야 함)",
    )
    # (answer·answer_explanation·multiple_answers·distractor_map은 정답류 —
    #  Problem 서브클래스로 이동, SEC-24(원 SEC-15) `PUBLIC_HIDDEN_ANSWER_FIELDS` 참조)

    # ===== 한국 시그니처 패턴 =====
    signature_patterns: list[SignaturePattern] = Field(
        default_factory=list,
        description="한국 수능 시그니처 패턴 배열(10종 중)",
    )

    # ===== 문제 유형(problem_type) 참조 =====
    # S3-27 신규(Problem↔ProblemType 연결 — `problem_bank_gap_review.md` §5-③ 유보 해제,
    # `ai_content_generation_gap_review.md` D3). `signature_patterns` 동형의 *순수 참조 배열*
    # (문자열 목록·ORM 관계 아님) — 단 **영속 축에서는 `signature_patterns`와 동형이 아니다**:
    # 후자는 ORM 컬럼(`db/models/problem.py:157`)이고 이 필드는 아니라서 `from_schema`의
    # `mapper.column_attrs` 필터(`db/models/problem.py:295-297`)가 적재 시 **드롭**한다. 즉 이
    # 필드는 코퍼스 JSONL·빌드타임 관측에만 존재하고 DB에는 없다(2026-08-11 R3 §정정-4 · G6).
    # 의도된 스코프이나(`S3-27` acceptance ② "관측 축 한정"), "동형"이라는 표현이 "DB에도
    # 있겠지"라는 가정을 낳을 수 있어 명시한다. 영속화 발화 조건은 R3 §5-⑤ 참조.
    # `data/corpus/problem_type_graph_v1/problem_types.jsonl`의
    # `problem_type_id`(예 'ptype.solve-for-unknown')를 가리키는 문자열만 담는다. 이 필드는
    # **관측 축 한정**이다: problem_type_node FK 연결·유형별 생성 확대·유형 기반 추천/출제는
    # 스코프 밖(`problem_bank_gap_review.md` §5-③ 판정 준수) — L1 스키마가 L6(응용 모드) 소비
    # 로직을 알 필요가 없다(역방향 의존 금지). 결정론 백필은 `harness/problem_type_backfill.py`
    # (생성기 identity → 유형 매핑표, LLM 0·텍스트 파싱 0)가 채운다. 참조 무결성(값이 카탈로그에
    # 실재하는지)은 이 스키마가 아니라 백필 CLI·거버넌스 테스트 소관(L1은 형태만 검증).
    problem_type_codes: list[str] = Field(
        default_factory=list,
        description=(
            "문제 유형(problem_type_id) 참조 배열 — problem_type_graph_v1의 id만 담는 문자열 "
            "목록(signature_patterns 동형). ORM 관계 아님·관측 축 한정(생성/추천 로직은 스코프 밖)."
        ),
    )

    # ===== 발문 구조 =====
    has_condition_list: bool = Field(
        default=False,
        description="(가)(나)(다) 조건 나열형 여부",
    )
    condition_count: int | None = Field(
        default=None,
        description="조건 개수",
        ge=0,
    )
    conditions_parsed: list[Condition] = Field(
        default_factory=list,
        description="파싱된 조건 목록(label·text·formal)",
    )

    # ===== 시각자료 =====
    has_visual: bool = Field(default=False, description="시각자료 포함 여부")
    visual_type: list[VisualType] = Field(
        default_factory=list,
        description="시각자료 유형 배열 — 그래프/도형/표/좌표평면",
    )
    visual_complexity: int | None = Field(
        default=None,
        description="시각자료 복잡도 1-5",
        ge=1,
        le=5,
    )
    visualizations: list[Visualization] = Field(
        default_factory=list,
        description=(
            "선언적 시각화 명세 배열(05 §5.2 — type·spec·caption·interactive). "
            "has_visual/visual_type(메타 태그)와 다른 축 — L5 ④ 비상구가 렌더(슬라이스 91)"
        ),
    )

    # ===== 다차원 난이도 (5축, 원칙 2) =====
    difficulty_overall: float | None = Field(
        default=None,
        description="종합 난이도 1.0-5.0",
        ge=1.0,
        le=5.0,
    )
    diff_calculation: float | None = Field(
        default=None,
        description="계산 복잡도 1.0-5.0",
        ge=1.0,
        le=5.0,
    )
    diff_interpretation: float | None = Field(
        default=None,
        description="조건 해석 난이도 1.0-5.0",
        ge=1.0,
        le=5.0,
    )
    diff_case_analysis: float | None = Field(
        default=None,
        description="케이스 분류 깊이 1.0-5.0",
        ge=1.0,
        le=5.0,
    )
    diff_visual: float | None = Field(
        default=None,
        description="시각자료 복잡도 1.0-5.0",
        ge=1.0,
        le=5.0,
    )
    diff_integration: float | None = Field(
        default=None,
        description="단원 융합도 1.0-5.0",
        ge=1.0,
        le=5.0,
    )
    irt_difficulty_b: float | None = Field(
        default=None,
        description=(
            "JMLE 보정 문항 난이도 b(logit). 응답 데이터로 적합(l2.fit_jmle), 없으면 전문가 "
            "난이도(difficulty_overall) 휴리스틱 폴백. logit 척도(1~5 아님)·범위 비제한."
        ),
    )
    # P3a 신규: IRT 2PL 변별 모수 a(slope·기울기). 기존 1PL b(irt_difficulty_b)를 보완해
    # 2PL로 확장할 때의 변별도. NULL=미적합(1PL 고정 a=1 가정). logit 척도·범위 비제한.
    irt_a: float | None = Field(
        default=None,
        description=(
            "IRT 2PL 변별 모수 a(slope). 기존 1PL b(irt_difficulty_b) 보완. NULL=미적합. "
            "logit 척도·범위 비제한(고전 변별도 discrimination_D와 다른 축 — IRT 모형 모수)."
        ),
    )
    # P3a 신규: 고전 검사이론(CTT) 변별도 D(상위/하위 정답률 차 등). irt_a(IRT 2PL 모수)와
    # *다른 축*이다 — discrimination_D는 *모형 비의존 경험 통계*(보통 0~1·상위27% 정답률 −
    # 하위27% 정답률), irt_a는 *2PL 잠재특성 모형의 기울기 모수*(logit·비제한). 둘 다 "변별"을
    # 재지만 추정 방식·척도가 달라 별도 보존한다.
    # 필드명 'discrimination_D'는 고전 검사이론의 *변별도 지수 D*(item discrimination index D)
    # 정본 표기라 대문자 D를 그대로 둔다(enums.py `iPhone` noqa 선례 — 도메인 정본명 보존).
    discrimination_D: float | None = Field(  # noqa: N815
        default=None,
        description=(
            "고전 변별도 D — 상위/하위 집단 정답률 차(모형 비의존 경험 통계). "
            "irt_a(IRT 2PL 기울기 모수)와 다른 축. 보통 0.0~1.0."
        ),
    )

    # ===== 정답률·통계 =====
    historical_correct_rate: float | None = Field(
        default=None,
        description="역대 정답률 0.0-1.0 (예: 0.0822 = 8.22%)",
        ge=0.0,
        le=1.0,
    )
    rate_top_grade: float | None = Field(
        default=None,
        description="1등급 학생 정답률 0.0-1.0",
        ge=0.0,
        le=1.0,
    )
    rate_mid_grade: float | None = Field(
        default=None,
        description="3-4등급 정답률 0.0-1.0",
        ge=0.0,
        le=1.0,
    )
    rate_low_grade: float | None = Field(
        default=None,
        description="6등급 이하 정답률 0.0-1.0",
        ge=0.0,
        le=1.0,
    )

    # ===== 시간 예상치 =====
    expected_solve_seconds: int | None = Field(
        default=None,
        description="평균 풀이 시간(초)",
        ge=0,
    )
    expected_solve_seconds_p90: int | None = Field(
        default=None,
        description="상위 10% 기준 풀이 시간(초)",
        ge=0,
    )
    # P3a 신규: 세션(문제 세트) 내 권장 출제 순서(0부터). NULL=세션 비배치. 학습 흐름 배치용.
    session_position: int | None = Field(
        default=None,
        description="세션 내 권장 출제 순서(0부터). NULL=세션 비배치",
        ge=0,
    )
    # P3a 신규: 피드백 템플릿 *느슨참조*(FK 아님 — 외부 피드백 카탈로그 키). NULL=기본 피드백.
    feedback_id: str | None = Field(
        default=None,
        description="피드백 템플릿 느슨참조 키(FK 아님). NULL=기본 피드백",
        max_length=64,
    )

    # ===== 페르소나 적합도 (원칙 5) =====
    persona_fit: dict[Persona, float] = Field(
        default_factory=dict,
        description="페르소나별 적합도 0.0-1.0 {Persona: score}",
    )

    # ===== 성취기준 코드 (비영속 — L5 게이팅 조인 주입) =====
    # 이 필드는 ORM에 *매핑되지 않는다*(db/models/problem.py의 from_schema/to_schema가
    # mapper.column_attrs로 매핑 컬럼만 추리므로 자동 무시 → 마이그레이션 0·ORM 무변경).
    # to_schema()는 이 필드를 채우지 않고 항상 default(빈 리스트)로 둔다. 값 주입은 L5 api
    # 게이팅(`api/gating.py`)의 4단계 조인(Problem→problem_concept→concept→concept_standard_link
    # →achievement_standard)이 official_code를 모아 넣는다. 성취기준 코퍼스·문항 태깅이 없으면
    # 빈 리스트로 남아 L6 학교진도 게이팅이 단원(unit_codes)·persona_fit 폴백으로 동작한다.
    achievement_standard_codes: list[str] = Field(
        default_factory=list,
        description="이 문항이 다루는 성취기준 고시코드(official_code, 예 '[12미적01-01]') 집합 "
        "— 비영속(ORM 비매핑). to_schema()가 채우지 않고 L5 api 게이팅 조인이 주입. "
        "데이터 없으면 빈 리스트(폴백).",
    )

    # ===== 교육과정 요구 깊이 (비영속 — L5 게이팅 + curriculum_entry resolver 주입) =====
    # achievement_standard_codes와 동일하게 ORM 비매핑(비영속)이라 마이그레이션·ORM 무변경
    # (from_schema/to_schema가 mapper.column_attrs로 매핑 컬럼만 추려 자동 무시). to_schema()는
    # 채우지 않고 default(None)로 둔다. 값 주입은 L5 api 게이팅이 문항→개념(problem_concept→
    # concept)으로 concept code를 모은 뒤 curriculum_entry resolver(l1/curriculum/curriculum_
    # resolve.py)로 그 개념들의 한국(KR) required_depth를 조회해 *가장 깊은 깊이*를 넣는다(자동
    # 커리큘럼 정렬 깊이 축·06_application_modes.md §자동정렬-3). 데이터(curriculum_entry 적재·
    # required_depth 큐레이션)가 없으면 None으로 남아 L6 깊이정렬이 무신호(0.0)로 폴백한다.
    curriculum_required_depth: RequiredDepth | None = Field(
        default=None,
        description="이 문항 개념들이 한국 교육과정에서 요구되는 가장 깊은 깊이(required_depth) "
        "— 비영속(ORM 비매핑). to_schema()가 채우지 않고 L5 api 게이팅이 curriculum_entry "
        "resolver로 주입. 데이터 없으면 None(L6 깊이정렬 무신호 폴백).",
    )

    # ===== EBS 연계 =====
    ebs_linked: bool = Field(default=False, description="EBS 연계 여부")
    ebs_source: dict[str, Any] | None = Field(
        default=None,
        description='EBS 구조 메타 {"book":"수능특강","chapter":3,"page":47}(본문 X)',
    )

    # ===== 단원 융합 =====
    is_cross_unit: bool = Field(default=False, description="단원 융합 여부")
    cross_unit_pairs: list[list[str]] = Field(
        default_factory=list,
        description='융합 단원 쌍 [["수열","극한"],["미분","함수"]]',
    )

    # ===== 그래프 개형 추론 =====
    requires_graph_sketch: bool = Field(
        default=False,
        description="그래프를 그려야 풀리는가",
    )
    sketch_step_count: int | None = Field(
        default=None,
        description="개형 추론 단계 수(보통 5-6)",
        ge=0,
    )

    # ===== 라벨링 =====
    tags: list[str] = Field(
        default_factory=list,
        description="검색·필터 태그 (예: ['킬러','22번고정'])",
    )
    keywords: list[str] = Field(
        default_factory=list,
        description="키워드 (예: ['합성함수','미분가능성'])",
    )

    # ===== 사용자 노출 정책 =====
    is_premium: bool = Field(default=False, description="프리미엄 콘텐츠 여부")
    is_published: bool = Field(default=False, description="게시 여부")
    publish_at: datetime | None = Field(default=None, description="게시 예정 시각")

    # ===== 운영 메타 =====
    created_at: datetime | None = Field(default=None, description="생성 시각")
    updated_at: datetime | None = Field(default=None, description="수정 시각")
    created_by: uuid.UUID | None = Field(
        default=None,
        description="생성 주체(인간 검수자 또는 AI 에이전트)",
    )
    review_status: ReviewStatus | None = Field(
        default=None,
        description=(
            "검수 상태 — pending/approved/rejected/quarantined "
            "(quarantined=사후 결함 판정으로 회수·EOS-71. rejected와 다르다: 삭제가 아닌 격리)"
        ),
    )
    review_score: float | None = Field(
        default=None,
        description="검수 점수 0-5",
        ge=0.0,
        le=5.0,
    )


# ──────────────────────────────────────────────────────────────────────────
# 핵심: Problem (§3.1 problem 테이블) — 내부 정본 = 공개 투영 + 정답류 6필드
# ──────────────────────────────────────────────────────────────────────────
class Problem(PublicProblem):
    """단일 문제 — §3.1 `problem` 테이블(50+ 메타데이터). WhyMath 최중요 단일 모델.

    **내부·영속 정본**이다. 무인증·학생 대면 응답에는 이 모델을 쓰지 않는다 —
    `PublicProblem`을 쓴다(SEC-24(원 SEC-15) · 정답류 6필드는 이 서브클래스만 가진다).

    법적 교정 불변식(MEMORY 2026-05-28, `@model_validator(mode="after")`로 강제):
      평가원·EBS·검정교과서는 *본문·문항 미보유*(상업 영리금지, 저작권 가이드 v2.0
      §32 단서). 따라서 `source_type ∈ {평가원, EBS, 교과서}`이면
      `question_text`·`answer_explanation`·`choices`가 *반드시 비어 있어야* 한다
      (있으면 ValueError → ValidationError). 이 출처 레코드는 구조 메타데이터 참조
      전용이며 `source_detail`/`ebs_source`에 단원·코드·문항번호만 둔다.

      *왜*: 검정 교과서·평가원·EBS 본문의 복제·영리이용은 저작권법 §32 단서·§136·
      §140(영리 비친고죄)로 금지된다. 학생에게 노출·저장되는 실제 문제는
      `source_type=자체생성`(WHYMATH_GENERATED)이며 자체 `question_text`를 가진다.

      (license/generation_type 강제는 ContentProvenance = 슬라이스 2 소관. 이 모델은
      Problem 본문 규칙만 강제한다. SEC-24 정답류 비노출은 이 저작권 축과 *독립* —
      저작권 축은 "무엇을 저장하면 안 되는가", SEC-24는 "저장한 것 중 무엇을 공개
      응답에 싣지 않는가"다.)

    DDL의 `question_text`·`answer`는 `NOT NULL`이지만, 본문 미보유 출처의 *메타 전용*
    레코드를 표현하려면 이들이 비어 있을 수 있어야 하므로 Pydantic에서는 Optional로
    완화한다(법적 교정과 정합). 실제 본문 레코드(자체생성)는 `question_text`를 채운다.
    """

    model_config = ConfigDict(
        # 추가 필드 금지 — Pydantic 모델이 스키마의 단일 진실
        extra="forbid",
        # 직렬화 시 enum 값을 그대로(한글 값 보존)
        use_enum_values=True,
        # 문자열 양끝 공백 제거
        str_strip_whitespace=True,
    )

    # ===== 정답·풀이(내부 정본 전용 — SEC-24 PUBLIC_HIDDEN_ANSWER_FIELDS) =====
    answer_constraint: dict[str, Any] | None = Field(
        default=None,
        description='정답 제약 {"min":1,"max":999,"is_natural":true} 등(자유형 JSONB)',
    )
    answer_transform: dict[str, Any] | None = Field(
        default=None,
        description='자연수 답 변환 패턴 {"type":"p_plus_q","p":3,"q":5} 등(자유형 JSONB)',
    )
    answer: str | None = Field(
        default=None,
        description="정답(자체생성만 본문 보유; 메타 전용 레코드는 비움)",
    )
    answer_explanation: str | None = Field(
        default=None,
        description="공식 해설(자체생성만; 평가원/EBS/교과서는 비어야 함)",
    )
    multiple_answers: dict[str, Any] | None = Field(
        default=None,
        description="복수해 가능성(출제오류 검증, 자유형 JSONB)",
    )
    # P3b 신규: 객관식 오답 선지 → 오개념 코드 매핑(rich list). 정답 선지는 제외하고 *오답*만
    # 싣는다. 각 원소는 (choice_index, misconception_id, op_code?). misconception_id는 정본
    # CATALOG_BY_ID의 id, op_code는 선택(추상 오류연산·평가원/EBS 본문 복제 아님). L1은 구조만
    # 검증하고, 카탈로그 실재·op_code 정합의 *참조 무결성*은 L4 검증자(validate_distractor_map)
    # 소관이다(역방향 의존 금지 — schema는 l4를 import하지 않음). NULL=미매핑(점진 채움).
    # 오답 선지의 *여집합*이 정답 선지를 드러내므로 정답류로 분류(SEC-24 감사 M1).
    distractor_map: list[DistractorEntry] | None = Field(
        default=None,
        description=(
            "객관식 오답 선지→오개념코드 매핑(rich list). 정답 선지 제외·오답만. 각 원소 "
            "(choice_index·misconception_id=CATALOG_BY_ID id·op_code 선택). 참조 무결성은 L4 검증."
        ),
    )

    # ===== 운영 격리(EOS-71 — 내부 정본 전용·PUBLIC_HIDDEN_OPS_FIELDS) =====
    # `review_status == quarantined`의 **근거 기록**. 상태값만 있고 사유가 없으면 "왜 회수됐는가"가
    # 사람 기억에만 남아 해제(재승인) 판단도 재발 방지도 불가능해진다(격리 계약 §3 기록 의무).
    # 두 필드를 `PublicProblem`(기반)이 아니라 이 서브클래스에 두는 이유: 공개 GET 4종은 무인증이라
    # 기반에 자리를 만드는 순간 운영 판단 메모가 그대로 공개된다(`PUBLIC_HIDDEN_OPS_FIELDS` 주석).
    quarantine_reason: str | None = Field(
        default=None,
        description=(
            "격리 사유(운영 메타·공개 투영 제외) — 정답 오류/복수 정답/모호 문장/실중복 등 "
            "사후 결함 판정의 근거 서술. NULL=미격리"
        ),
    )
    quarantined_at: datetime | None = Field(
        default=None,
        description=(
            "격리 시각(운영 메타·공개 투영 제외) — 이 시각 *이전* attempt는 결함 문항 응답일 수 "
            "있다. NULL=미격리(기본값 없음 — 백필 날조 방지)"
        ),
    )

    # ===== 과목별 확장 (011_2·S1-16) — 내부 정본용 =====
    # `PublicProblem.extensions`(`ProblemExtensionsPublic`)을 오버라이드. `MathExtension`
    # 에는 정답 유도 가능 필드 2종을 포함하며, `PublicProblem.from_problem`이 이들을
    # 제거한 뒤 `MathExtensionPublic`으로 검증(SEC-24).
    extensions: ProblemExtensions = Field(  # type: ignore[assignment]
        default_factory=ProblemExtensions,
        description="과목별 확장 payload — math extension에 수학 특화 필드(정답 유도 2종 포함)",
    )

    # ── 불변식 ────────────────────────────────────────────────────
    @model_validator(mode="after")
    def _enforce_copyright_no_body_for_metadata_sources(self) -> Problem:
        """법적 교정 — 평가원/EBS/교과서는 본문 필드를 가질 수 없다.

        MEMORY 2026-05-28 결정: 평가원·EBS·검정교과서는 *본문·문항 미보유*(상업
        영리금지, 저작권법 §32 단서·§136·§140 영리 비친고죄). 이 출처의 레코드는
        구조 메타데이터 참조 전용이므로 본문 필드가 비어 있어야 한다. 본문이 있으면
        ValueError를 던져 ValidationError로 전파한다.

        대상 본문 필드: `question_text`·`answer_explanation`·`choices`·`conditions_parsed`.
        (`conditions_parsed`는 각 `Condition.text`가 *조건 자연어 본문*이라 저작권 민감 — P3a/P3b
        신규 필드라 초기 명세[question_text·answer_explanation·choices]에 누락됐던 갭을 보정.
        WH-S export의 #261/#262 게이트는 이 보정으로 *중복 심층 방어*가 된다.)
        (license/generation_type 강제는 슬라이스 2 ContentProvenance 소관.)

        use_enum_values=True 환경: `source_type`이 문자열 값일 수 있으므로
        enum/문자열 양쪽을 정규화해 비교한다(`l3/models.py` 패턴 답습).
        """
        source_value = (
            self.source_type.value if isinstance(self.source_type, SourceType) else self.source_type
        )
        metadata_only_values = {s.value for s in _METADATA_ONLY_SOURCES}

        if source_value not in metadata_only_values:
            # 자체생성·AIHub·사용자자작 등은 본문 보유 허용 → 규칙 비적용
            return self

        # 비어 있어야 하는 본문 필드를 점검(None/빈 문자열/빈 리스트만 허용)
        offending: list[str] = []
        if self.question_text:
            offending.append("question_text")
        if self.answer_explanation:
            offending.append("answer_explanation")
        if self.choices:
            offending.append("choices")
        if self.conditions_parsed:
            offending.append("conditions_parsed")  # Condition.text=조건 자연어 본문(갭 보정)

        if offending:
            raise ValueError(
                f"저작권 교정 위반: source_type={source_value!r}(평가원/EBS/교과서)는 "
                f"본문·문항 미보유여야 한다(저작권 가이드 v2.0 §32 단서·영리 금지). "
                f"비어 있어야 할 본문 필드에 값이 있음: {offending}. "
                f"이 출처는 구조 메타데이터 참조 전용이며 본문은 "
                f"source_type='자체생성'(WHYMATH_GENERATED) 레코드만 가질 수 있다 "
                f"(MEMORY 2026-05-28)."
            )
        return self

    # ── 011_2: legacy 수학 특화 필드 ↔ extensions.math 양방향 동기화 ──
    @model_validator(mode="after")
    def _sync_math_extensions(self) -> Problem:
        """legacy top-level 필드와 `extensions.math`를 양방향 동기화.

        하위호환: 기존 top-level 필드를 채우는 호출자에게는 자동으로
        `extensions.math`가 채워지고, 새로 `extensions.math`를 채우는
        호출자에게는 top-level legacy 필드가 동기화된다.

        DB 마이그레이션 없이 Pydantic/ORM 매핑 레벨에서 처리 —
        `db/models/problem.py`의 `from_schema`/`to_schema`는 여전히 legacy
        컬럼만 사용하며, 이 validator가 `extensions.math`를 채우고 비운다.

        동기화 규칙 — **legacy top-level이 정본, `extensions.math`는 그 투영**:
          - 입력에 *명시된* legacy 필드가 언제나 이긴다.
          - `extensions.math`는 **입력이 언급하지 않은** legacy 필드만 끌어올린다
            (새 축만 채우는 호출자를 위한 하위호환 방향).
          - 그 결과로 `extensions.math`를 항상 재생성한다 — 두 축이 다른 값을
            들고 있는 상태 자체가 생기지 않는다.

        *왜 값 비교(기본값이 아닌 쪽이 이김)가 아닌가*: 값만 보면 **명시적 비우기를
        표현할 수 없다**. 재태깅으로 `signature_patterns`가 `[]`가 되거나
        `requires_graph_sketch`를 `False`로 되돌리면, 값 비교는 그것을 "안 채운 것"으로
        읽고 낡은 extension 값을 되살린다. 어느 방향이든 결과는 침묵 손실이다 —
        실제로 반대 방향(legacy에만 쓰는 `l1.problem_bank`의 시그니처 태거가
        `model_copy(update=...)`로 갱신 → JSONL 왕복 재검증에서 빈 extension이 태깅을
        `[]`로 덮음)이 먼저 터졌고, 값 비교로 고치자 이 방향이 남았다. 그래서
        "무엇이 채워졌나"(값)가 아니라 **"입력이 무엇을 말했나"**(`model_fields_set`)로
        판정한다. 전체 덤프의 왕복에서는 두 축이 모두 명시되므로 정본인 legacy가
        이기고, 그 시점의 legacy는 직렬화 직전 이 validator가 맞춰 둔 값이다.

        DB 왕복에서도 정합한다 — `db/models/problem.py`는 legacy 컬럼만 쓰므로
        `to_schema`는 legacy만 주고 `extensions.math`는 여기서 재생성된다.
        """
        provided = self.model_fields_set
        legacy: dict[str, Any] = {name: getattr(self, name) for name in MATH_EXTENSION_FIELDS}

        ext = self.extensions.math if self.extensions is not None else None
        if ext is not None:
            for name in MATH_EXTENSION_FIELDS:
                if name not in provided:
                    legacy[name] = getattr(ext, name)

        for name, value in legacy.items():
            setattr(self, name, value)

        math = MathExtension(**legacy)
        self.extensions = (
            ProblemExtensions(math=math)
            if self.extensions is None
            else self.extensions.model_copy(update={"math": math})
        )
        return self


# ──────────────────────────────────────────────────────────────────────────
# 공개 투영: PublicProblemStep (SEC-24(원 SEC-15)) + 보조: ProblemStep (§3.2 problem_step)
# ──────────────────────────────────────────────────────────────────────────
class PublicProblemStep(BaseModel):
    """풀이 단계의 **공개(무인증·학생 대면) 응답 정본** — 기대답·힌트류에 자리가 없다.

    `ProblemStep`(내부 정본)이 이 기반에 `PUBLIC_HIDDEN_STEP_ANSWER_FIELDS` 3필드
    (`expected_answer`·`common_mistakes`·`common_errors`)를 *더한다*(`PublicProblem` ⊂
    `Problem`과 동일 방향·SEC-24). `socratic_prompt`는 답을 제공하지 않는 교수학 발문이라
    공개 유지. S4-09(D1) additive 중 구조 메타 축(`solution_path_id`·`concept_node_id`·
    `reasoning_type`·`justification`·`sympy_verified`)도 정답을 드러내지 않으므로 공개
    유지 — 단계 *내용*이 실리는 `expected_answer`만 내부 정본으로 남는다.
    """

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    @classmethod
    def from_step(cls, step: ProblemStep) -> PublicProblemStep:
        """내부 정본 → 공개 투영. 기대답·흔한실수/오류는 애초에 대상 모델에 자리가 없다."""
        return cls.model_validate(step.model_dump(exclude=set(PUBLIC_HIDDEN_STEP_ANSWER_FIELDS)))

    step_id: uuid.UUID = Field(default_factory=uuid4, description="단계 PK (UUID)")
    problem_id: uuid.UUID = Field(..., description="소속 문제 FK")
    step_order: int = Field(..., description="단계 순서(1부터)", ge=1)
    step_type: StepType | None = Field(
        default=None,
        description="단계 유형 — 조건해석/케이스분류/그래프스케치/계산/검산",
    )
    step_title: str | None = Field(
        default=None,
        description="단계 제목",
        max_length=200,
    )
    socratic_prompt: str | None = Field(
        default=None,
        description="소크라테스 발문 (예: '조건 (가)를 수식으로 표현해보세요')",
    )

    # ===== S4-09(D1) additive 중 구조 메타 축(공개 유지 — 정답 비노출) =====
    solution_path_id: str | None = Field(
        default=None,
        description="소속 풀이 경로 ID(`solution_paths` FK). None=경로 미소속(레거시 단계).",
    )
    concept_node_id: str | None = Field(
        default=None,
        description="이 단계가 통과하는 L1 개념 노드 ID. None=매칭 검수 대기(사람 검수 큐).",
    )
    reasoning_type: ReasoningType | None = Field(
        default=None,
        description=(
            "스텝 추론 유형 — 기존 단일 좌석 ReasoningType(폐쇄 7종) 소비. "
            "폐쇄집합 밖은 검증 거부. None=미태깅(하위호환)."
        ),
    )
    justification: dict[str, Any] | None = Field(
        default=None,
        description=(
            "정당화 근거 참조 JSONB — 구조 정본은 `l3.solution_path.Justification`"
            "(theorem_concept_ids·concept_node_ids·prior_step_orders 얇은 3종 묶음). "
            "schema 계층은 L 계층을 import하지 않으므로(역방향 의존 금지) 여기서는 자유형 "
            "dict로 통과시킨다."
        ),
    )
    sympy_verified: bool | None = Field(
        default=None,
        description=(
            "SymPy 자동 검증 통과 여부(WH-S 승계 시 직전 스텝→이 스텝 전이 Tier2 correct). "
            "None=미판정(레거시 단계)."
        ),
    )


class ProblemStep(PublicProblemStep):
    """문항 풀이 단계 — §3.2 `problem_step`(Socratic 코칭 시 사용). **내부 정본**.

    `UNIQUE(problem_id, step_order)` — 한 문제 안에서 step_order는 유일(런타임/DB
    제약; 단일 모델 레벨에서는 표현하지 않음). 무인증 steps 응답에는 이 모델을 쓰지
    않는다 — `PublicProblemStep`을 쓴다(SEC-24(원 SEC-15)).

    S4-09(D1) additive 필드 6종: SolutionPath 실체화(`l3/solution_path.py`)의 단계가
    `problem_step`에 영속되면서 이 스키마로 서빙된다. 전부 기본 None(선택)이라 기존 필드
    제거·의미 변경 0 — 기존 소비자 호환 유지. 단 그중 `common_errors`는 SEC-24 공개 투영
    경계에서 내부 정본 쪽(비공개)에 둔다(오개념 preload 금지 축).
    """

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    # ===== 기대답·힌트류(내부 정본 전용 — SEC-24 PUBLIC_HIDDEN_STEP_ANSWER_FIELDS) =====
    expected_answer: str | None = Field(
        default=None,
        description="이 단계의 기대 답",
    )
    common_mistakes: list[dict[str, Any]] = Field(
        default_factory=list,
        description='흔한 실수 목록 [{"error":"...","hint":"..."}](자유형 JSONB)',
    )
    common_errors: list[str] | None = Field(
        default=None,
        description=(
            "이 단계의 흔한 오류(오개념 카탈로그 코드/패턴 서술) — yaml SolutionStep."
            "common_errors 1:1 좌석. 기존 common_mistakes(자유형 dict 리스트)와 별개 축."
        ),
    )


# ──────────────────────────────────────────────────────────────────────────
# 보조: ProblemRelation (§3.2 problem_relation)
# ──────────────────────────────────────────────────────────────────────────
class ProblemRelation(BaseModel):
    """문항 간 관계 — §3.2 `problem_relation`(전형성·유사도).

    복합 PK `(parent_problem_id, related_problem_id, relation_type)` — DB 제약.
    불변식: 자기 자신과의 관계 금지(parent ≠ related).
    """

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    parent_problem_id: uuid.UUID = Field(..., description="기준 문제 FK")
    related_problem_id: uuid.UUID = Field(..., description="관계 대상 문제 FK")
    relation_type: RelationType = Field(
        ...,
        description="관계 유형 — 변형/유사/선수/심화/대조",
    )
    similarity_score: float | None = Field(
        default=None,
        description="유사도 0.0-1.0",
        ge=0.0,
        le=1.0,
    )

    @model_validator(mode="after")
    def _no_self_relation(self) -> ProblemRelation:
        """자기 자신과의 관계 금지 — parent_problem_id ≠ related_problem_id."""
        if self.parent_problem_id == self.related_problem_id:
            raise ValueError(
                "문항 관계 위반: parent_problem_id와 related_problem_id가 같을 수 없다 "
                "(자기 자신과의 관계 금지)"
            )
        return self
