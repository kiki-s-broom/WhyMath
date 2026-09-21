"""Schema v1.0 도메인8 Provenance 모델 (Pydantic) — 슬라이스 2.

설계 정본: `schemas/v1.0/schema_v1.0.md` §10(`content_provenance`·`generation_log` DDL).

Phase 메모: 코드베이스 전체가 *Pydantic-schema-only*(DB 미배포) — 이 슬라이스도 순수
Pydantic 모델이다. SQLAlchemy/alembic 매핑은 후속 Phase(슬라이스 1 `problem.py` 동일 패턴).

컨벤션(`problem.py`·`l3/models.py` 답습):
  - `ConfigDict(extra="forbid", use_enum_values=True, str_strip_whitespace=True)`.
  - enum은 `enums.py`의 `class X(str, Enum)`.
  - 불변식은 `@model_validator(mode="after")`.
  - 공유 베이스 클래스 없음(각 모델 독립).

타입 매핑 판단(DDL → Pydantic, 슬라이스 1 선례 그대로):
  - `UUID PK` → `uuid.UUID = Field(default_factory=uuid4)`
  - `UUID REFERENCES`(FK) → `uuid.UUID | None`(DDL에 NOT NULL 없음 → 보수적 Optional)
  - `JSONB` 자유형 → `dict[str, Any] | None`
  - `DECIMAL` → `float`(ge=0)
  - `TIMESTAMPTZ` → `datetime`
  - `VARCHAR(n)` → `str | None`(max_length=n)

법적 교정(이번 슬라이스의 핵심, MEMORY 2026-05-28 속편 "스키마 법적 교정"):
  평가원·EBS·교과서는 *본문 미보유*(저작권 가이드 v2.0 §32 단서·§136·§140 영리
  비친고죄). `content_provenance`가 이 본문 규칙을 *license/generation_type 차원*에서
  강제한다. 슬라이스 1 `Problem`은 본문 필드 차원, 이 모델은 출처·라이선스 차원으로
  같은 원칙을 양면 방어한다. 상세는 `ContentProvenance` 불변식 docstring 참조.
"""

from __future__ import annotations

import copy
import hashlib
import json
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from whymath_backend.schema.enums import GenerationType, LicenseType, SourceType

# 단일 출처 유지: 메타데이터 전용 출처 집합은 `problem.py`에서 가져온다(중복 정의 금지).
# (frozenset[SourceType] = {평가원, EBS, 교과서} — 본문 미보유, 저작권 가이드 v2.0 §32 단서)
from whymath_backend.schema.problem import _METADATA_ONLY_SOURCES

# ──────────────────────────────────────────────────────────────────────────
# 변형/생성류 generation_type — 메타 전용 출처가 *반드시* 거쳐야 하는 단계 집합
# (ORIGINAL="원본 그대로"는 제외 — (A) 불변식에서 이미 전면 차단됨)
# ──────────────────────────────────────────────────────────────────────────
_TRANSFORMED_GENERATION_TYPES: frozenset[GenerationType] = frozenset(
    {
        GenerationType.VARIANT_NUMBER,
        GenerationType.VARIANT_STRUCTURE,
        GenerationType.VARIANT_CONTEXT,
        GenerationType.COMPOSED,
        GenerationType.FULLY_GENERATED,
    }
)
"""메타 전용 출처(평가원/EBS/교과서)를 참조하는 레코드가 가질 수 있는 generation_type.

원본을 *그대로* 쓰지 않고 반드시 변형/생성했음을 보장한다. `ORIGINAL`은 (A) 불변식에서
별도로 막히고, `None`도 (C-2)에서 거부된다(변형/생성 단계가 명시돼야 함).
"""

# ──────────────────────────────────────────────────────────────────────────
# original_reference 본문성 키 denylist — 구조 메타만 허용, 본문은 금지
# (키를 소문자화해 부분일치로 검사 — year/exam/number/unit/code/page 등 구조 메타만 통과)
# ──────────────────────────────────────────────────────────────────────────
_BODY_KEY_DENYLIST: tuple[str, ...] = (
    "question",
    "statement",
    "body",
    "content",
    "answer",
    "solution",
    "explanation",
    "choice",
    "passage",
    "본문",
    "문제",
    "풀이",
    "정답",
    "보기",
    "지문",
    "해설",
)
"""`original_reference`에 들어오면 안 되는 *본문성* 키(부분일치·소문자화).

`original_reference`는 *구조 메타 전용*(year/exam/number/unit/code/page/문항번호 등)이다.
본문(발문·풀이·정답·보기)을 이 JSONB에 끼워 넣어 우회 저장하는 것을 차단한다.
"""


# ──────────────────────────────────────────────────────────────────────────
# 핵심: ContentProvenance (§10.1 content_provenance 테이블)
# ──────────────────────────────────────────────────────────────────────────
class ContentProvenance(BaseModel):
    """콘텐츠 변형·생성 이력 — §10.1 `content_provenance`(감사 추적).

    한 `problem`이 어떤 원본 출처에서 어떤 변형/생성 단계를 거쳐 만들어졌는지, 검증·승인·
    저작권 메타데이터까지 추적한다. 특성 #11·#33·#36·#37의 영속 모델.

    FK Optional 판단(docstring 1줄): DDL의 `problem_id`·`parent_problem_id`·`approved_by`는
    모두 `UUID REFERENCES`이지만 *NOT NULL이 없으므로* 보수적으로 Optional로 둔다(슬라이스
    1 `Problem.created_by`와 동일 정책 — NOT NULL 명시 FK만 required, 예: `ProblemStep.
    problem_id`).

    법적 불변식(`@model_validator(mode="after")`로 강제 — 이번 슬라이스의 핵심,
    근거: MEMORY 2026-05-28 속편 "스키마 법적 교정", 저작권 가이드 v2.0 §32 단서·§136·§140):

      (A) `generation_type == ORIGINAL` → ValueError.
          ORIGINAL="원본 그대로"=본문 복제 전제 → 공식 제휴(Phase 3+) 전까지 전면 미사용.

      (B) `license == EBS_LICENSED` → ValueError.
          공식 제휴(Phase 3+) 전까지 전면 미사용.

      (C) `original_source ∈ {평가원, EBS, 교과서}`(= `problem._METADATA_ONLY_SOURCES`)이면:
        (C-1) `license != WHYMATH_GENERATED` → ValueError.
              이 레코드가 가리키는 본문 문제는 우리가 만든 *동등문제*이므로 지배
              license는 WHYMATH_GENERATED. 원본의 license는 통과하지 못한다.
        (C-2) `generation_type`이 None이거나 변형류(VARIANT_NUMBER·VARIANT_STRUCTURE·
              VARIANT_CONTEXT·COMPOSED·FULLY_GENERATED)가 아니면 → ValueError.
              원본을 그대로 쓰지 않고 *반드시 변형/생성*했음을 보장(ORIGINAL은 (A)에서 차단).
        (C-3) `original_reference`의 키에 본문성 키(question/statement/body/answer/풀이/
              정답/… denylist)가 있으면 → ValueError. 구조 메타(year/exam/number/unit/
              code/page/문항번호)만 허용. DDL 예시 `{"year":2025,"exam":"수능","number":30}`
              은 통과한다.

      use_enum_values=True 환경: `original_source`·`license`·`generation_type`가 *문자열
      값일 수 있으므로* enum/문자열 양쪽을 정규화해 비교한다(`problem.py` L430-435 패턴 답습).
    """

    model_config = ConfigDict(
        # 추가 필드 금지 — Pydantic 모델이 스키마의 단일 진실
        extra="forbid",
        # 직렬화 시 enum 값을 그대로(영어 값 보존)
        use_enum_values=True,
        # 문자열 양끝 공백 제거
        str_strip_whitespace=True,
    )

    # ===== 기본 식별 =====
    provenance_id: uuid.UUID = Field(
        default_factory=uuid4,
        description="이력 PK (UUID)",
    )
    problem_id: uuid.UUID | None = Field(
        default=None,
        description="대상 문제 FK (DDL NOT NULL 없음 → Optional)",
    )

    # ===== 원본 출처 =====
    original_source: SourceType | None = Field(
        default=None,
        description="원본 출처 — 평가원/EBS/AIHub 등(메타 전용 출처는 본문 미보유)",
    )
    original_reference: dict[str, Any] | None = Field(
        default=None,
        description=(
            '원본 참조 *구조 메타 전용* {"year":2025,"exam":"수능","number":30} 등 '
            "(본문성 키 금지 — (C-3) 불변식으로 차단)"
        ),
    )

    # ===== 변형·생성 단계 =====
    generation_type: GenerationType | None = Field(
        default=None,
        description="변형/생성 단계 — VARIANT_*/COMPOSED/FULLY_GENERATED (ORIGINAL 미사용)",
    )
    transformation: dict[str, Any] | None = Field(
        default=None,
        description='변형 메타 {"operations":[{"type":"swap_numbers","from":3,"to":5}]} 등',
    )
    parent_problem_id: uuid.UUID | None = Field(
        default=None,
        description="원본 문제 FK(변형의 경우; DDL NOT NULL 없음 → Optional)",
    )
    transformation_pipeline: dict[str, Any] | None = Field(
        default=None,
        description='변형 파이프라인 {"steps":["Qwen3-32B 초안","Claude 검증","사람 검수"]}',
    )

    # ===== 검증·승인 =====
    auto_validation: dict[str, Any] | None = Field(
        default=None,
        description="자동 검증 결과(자유형 JSONB)",
    )
    human_review: dict[str, Any] | None = Field(
        default=None,
        description='사람 검수 결과 {"reviewer_id":"...","score":4.5,"comments":"..."}',
    )
    approved_at: datetime | None = Field(default=None, description="승인 시각")
    approved_by: uuid.UUID | None = Field(
        default=None,
        description="승인 주체 FK(DDL NOT NULL 없음 → Optional)",
    )

    # ===== 저작권·법적 메타데이터 =====
    license: LicenseType | None = Field(
        default=None,
        description="라이선스 — 본문 보유 문제의 지배 license는 WHYMATH_GENERATED",
    )
    copyright_notice: str | None = Field(
        default=None,
        description="저작권 고지 문구",
    )
    usage_restrictions: dict[str, Any] | None = Field(
        default=None,
        description="사용 제약(자유형 JSONB)",
    )

    # ===== 운영 메타 =====
    created_at: datetime | None = Field(default=None, description="생성 시각")

    # ── 불변식 ────────────────────────────────────────────────────
    @model_validator(mode="after")
    def _enforce_license_and_generation_legal_corrections(self) -> ContentProvenance:
        """법적 교정 — license/generation_type 차원의 저작권 불변식 강제.

        근거: MEMORY 2026-05-28 속편 "스키마 법적 교정"(저작권 가이드 v2.0 §32 단서·
        §136·§140 영리 비친고죄). 슬라이스 1 `Problem`이 *본문 필드* 차원을 막았고, 이
        validator는 *출처·라이선스* 차원을 막아 같은 원칙을 양면 방어한다.

        분기 (A)·(B)·(C-1·2·3)는 클래스 docstring 참조. use_enum_values=True 환경이라
        enum/문자열 양쪽이 들어올 수 있으므로 모두 *문자열 값*으로 정규화해 비교한다
        (`problem.py` L430-435 패턴).
        """
        # ── enum/문자열 정규화 (use_enum_values=True 대응) ──
        gen_value = (
            self.generation_type.value
            if isinstance(self.generation_type, GenerationType)
            else self.generation_type
        )
        license_value = (
            self.license.value if isinstance(self.license, LicenseType) else self.license
        )
        source_value = (
            self.original_source.value
            if isinstance(self.original_source, SourceType)
            else self.original_source
        )

        # ── (A) ORIGINAL 전면 차단 ──
        if gen_value == GenerationType.ORIGINAL.value:
            raise ValueError(
                "저작권 교정 위반(A): generation_type=ORIGINAL은 *원본 그대로*(본문 복제) "
                "전제이므로 공식 제휴(Phase 3+) 전까지 전면 미사용이다(저작권 가이드 v2.0 "
                "§32 단서·영리 금지). 변형/생성(VARIANT_*/COMPOSED/FULLY_GENERATED)을 "
                "사용하라 (MEMORY 2026-05-28 속편)."
            )

        # ── (B) EBS_LICENSED 전면 차단 ──
        if license_value == LicenseType.EBS_LICENSED.value:
            raise ValueError(
                "저작권 교정 위반(B): license=EBS_LICENSED는 공식 제휴(Phase 3+) 전까지 "
                "전면 미사용이다(MEMORY 2026-05-28 속편). 본문 보유 문제의 지배 license는 "
                "WHYMATH_GENERATED이다."
            )

        # ── (C) 메타 전용 출처(평가원/EBS/교과서) 추가 규칙 ──
        metadata_only_values = {s.value for s in _METADATA_ONLY_SOURCES}
        if source_value in metadata_only_values:
            # (C-1) 지배 license는 WHYMATH_GENERATED만 허용
            if license_value != LicenseType.WHYMATH_GENERATED.value:
                raise ValueError(
                    f"저작권 교정 위반(C-1): original_source={source_value!r}"
                    "(평가원/EBS/교과서)가 가리키는 본문 문제는 우리가 만든 *동등문제*이므로 "
                    f"지배 license는 WHYMATH_GENERATED여야 한다. 현재 license={license_value!r} "
                    "(MEMORY 2026-05-28 속편·저작권 가이드 v2.0)."
                )

            # (C-2) 반드시 변형/생성류여야 함(None·비변형 거부; ORIGINAL은 (A)에서 차단)
            transformed_values = {g.value for g in _TRANSFORMED_GENERATION_TYPES}
            if gen_value not in transformed_values:
                raise ValueError(
                    f"저작권 교정 위반(C-2): original_source={source_value!r}"
                    "(평가원/EBS/교과서)는 원본을 그대로 쓰지 않고 *반드시 변형/생성*해야 한다. "
                    "generation_type은 VARIANT_NUMBER/VARIANT_STRUCTURE/VARIANT_CONTEXT/"
                    f"COMPOSED/FULLY_GENERATED 중 하나여야 한다. 현재 generation_type="
                    f"{gen_value!r} (MEMORY 2026-05-28 속편)."
                )

            # (C-3) original_reference에 본문성 키 금지(구조 메타만)
            if self.original_reference is not None:
                offending_keys = [
                    key
                    for key in self.original_reference
                    if any(banned in str(key).lower() for banned in _BODY_KEY_DENYLIST)
                ]
                if offending_keys:
                    raise ValueError(
                        f"저작권 교정 위반(C-3): original_source={source_value!r}의 "
                        "original_reference는 *구조 메타 전용*(year/exam/number/unit/code/"
                        f"page/문항번호 등)이다. 본문성 키 발견: {offending_keys}. 발문·풀이·"
                        "정답·보기 등 본문을 이 JSONB에 끼워 넣을 수 없다 "
                        "(MEMORY 2026-05-28 속편·저작권 가이드 v2.0)."
                    )

        return self


# ──────────────────────────────────────────────────────────────────────────
# 생성 Run 재현 계약 — 입력 스냅샷 canonical 직렬화·해시 (EOS-55)
#
# "동일 Run 레코드로 재실행 시 동일 입력이 복원된다"를 성립시키는 순수 함수 3종.
# 스냅샷은 **자기완결**이어야 한다(#912 codex P1-1): 자유 텍스트(프롬프트·시스템)는
# **전문(verbatim)을 담고** sha256 핀을 무결성용으로 병기한다 — 해시만 남기면 원본
# specs 파일이 바뀌거나 사라진 뒤 모델 입력을 재구성할 수 없다(해시 복원≠입력 복원).
# 두 생성 경로의 문면은 자체 정본 템플릿+자체 스펙 조합이라 저작권 무관이고, 행당 수
# KB는 로그 테이블에 허용 용량이다. 이 모듈은 l3를 import하지 않는다(7계층 역방향
# 금지) — 스냅샷 *조립*은 각 생성 경로(L3측 `l3/pregenerate/provenance_bridge.py`·
# `l3/equivalent/llm_generator.py`)가 하고, 여기는 직렬화·해시·복원 검증의 단일
# 정본만 둔다.
# ──────────────────────────────────────────────────────────────────────────
def text_sha256(text: str) -> str:
    """자유 텍스트(프롬프트·시스템·응답)의 sha256 hex — 바이트 동일성 핀(utf-8 기준).

    스냅샷에 전문과 *병기*해 무결성 대조 축으로 쓴다(해시 일치 = 바이트 동일). 전문
    없이 이 해시만 남기는 용법은 재현 계약 미성립이다(#912 P1-1 — 해시로는 입력을
    재구성할 수 없다) — 스냅샷 조립부는 전문을 함께 담는다.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_input_json(snapshot: Mapping[str, Any]) -> str:
    """입력 스냅샷의 canonical JSON 직렬화 — 키 정렬·compact·유니코드 원문(결정론).

    같은 내용이면 키 순서·공백과 무관하게 항상 같은 문자열이 나온다(해시 안정성의 전제).
    `allow_nan=False` — NaN/Infinity는 JSON 표준 밖이라 PostgreSQL JSONB 왕복이 불가하므로,
    저장 불가 값은 여기서 시끄럽게 실패시킨다(조용한 이식 불가 스냅샷 금지).
    JSON 비직렬화 값(enum·set 등)도 TypeError로 실패한다 — 조립부가 원시형으로 정규화한
    뒤 넘겨야 한다(복원 계약: DB JSONB 왕복 후에도 같은 canonical 문자열이어야 함).
    """
    return json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def input_snapshot_sha256(snapshot: Mapping[str, Any]) -> str:
    """입력 스냅샷 → sha256 hex — canonical 직렬화(utf-8) 위에서만 계산한다(단일 정본)."""
    return hashlib.sha256(canonical_input_json(snapshot).encode("utf-8")).hexdigest()


def restore_input_snapshot(log: GenerationLog) -> dict[str, Any]:
    """Run 레코드만으로 입력 스냅샷을 복원한다 — 해시 재계산·대조 통과분만 반환(재현 계약).

    계약(EOS-55 acceptance ②): ① `input_snapshot` 미기록이면 복원 불가를 *정직하게*
    ValueError로 알린다(빈 dict 위장 금지) ② 재계산 해시가 `input_sha256`과 다르면
    스냅샷이 변조/파손된 것 — 조용히 돌려주지 않고 ValueError(무결성 실패). 반환은
    깊은 복사본이라 호출자가 수정해도 레코드가 오염되지 않는다.
    """
    if log.input_snapshot is None:
        raise ValueError(
            "입력 스냅샷 미기록 — 이 GenerationLog 레코드로는 입력을 복원할 수 없다"
            "(구 레코드 또는 스냅샷 미배선 경로·NULL=미기록)."
        )
    if log.input_sha256 is None:
        # 모델 validator가 스냅샷 존재 시 해시를 자동 보충하므로 정상 경로에선 불가능하나,
        # 방어적으로 명시 실패(해시 없는 스냅샷은 무결성 검증 불가 = 재현 계약 미성립).
        raise ValueError("input_sha256 미기록 — 스냅샷 무결성을 검증할 수 없다(재현 계약 미성립).")
    recomputed = input_snapshot_sha256(log.input_snapshot)
    if recomputed != log.input_sha256:
        raise ValueError(
            "입력 스냅샷 해시 불일치 — 기록 이후 스냅샷이 변조/파손됐다"
            f"(기록 {log.input_sha256[:12]}… ≠ 재계산 {recomputed[:12]}…)."
        )
    return copy.deepcopy(dict(log.input_snapshot))


# ──────────────────────────────────────────────────────────────────────────
# 보조: GenerationLog (§10.1 generation_log 테이블)
# ──────────────────────────────────────────────────────────────────────────
class GenerationLog(BaseModel):
    """LLM 생성 호출 이력 — §10.1 `generation_log`(비용·품질 분석).

    문제 1개를 생성/변형하며 호출한 LLM의 모델·토큰·비용·지연·성공 여부를 기록한다.
    `l3/pregenerate` 동등문제 엔진의 호출 결과를 이 모델로 적재한다(연결 코드는 계층
    규칙상 L3쪽 `l3/pregenerate/provenance_bridge.py`에 둔다 — schema는 l3를 import하지
    않는다).

    이 모델은 *순수 데이터 모델*로 유지한다 — l3를 import하지 않는다(역방향 의존 금지,
    7계층 절대원칙). 검증 불변식 없음(로그 레코드는 가능한 한 관대하게 받아 적재).

    FK Optional 판단: `problem_id`·`provenance_id`·`prompt_template_id`는 모두 `UUID
    REFERENCES`이나 DDL에 NOT NULL이 없으므로 Optional로 둔다(`ContentProvenance` 동일 정책).
    """

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    log_id: uuid.UUID = Field(default_factory=uuid4, description="로그 PK (UUID)")
    problem_id: uuid.UUID | None = Field(
        default=None,
        description="대상 문제 FK(DDL NOT NULL 없음 → Optional)",
    )
    provenance_id: uuid.UUID | None = Field(
        default=None,
        description="대상 이력 FK(DDL NOT NULL 없음 → Optional)",
    )
    model_name: str | None = Field(
        default=None,
        description="모델명 — 'qwen3-32b'/'claude-opus-4-7' 등",
        max_length=64,
    )
    prompt_template_id: uuid.UUID | None = Field(
        default=None,
        description="프롬프트 템플릿 FK(DDL NOT NULL 없음 → Optional)",
    )
    input_tokens: int | None = Field(
        default=None,
        description="입력 토큰 수",
        ge=0,
    )
    output_tokens: int | None = Field(
        default=None,
        description="출력 토큰 수",
        ge=0,
    )
    cache_read_input_tokens: int | None = Field(
        default=None,
        description=(
            "프롬프트 캐시에서 *읽힌* 프리픽스 토큰 수(EOS-99 적중 축). `input_tokens`와 "
            "**합산 관계가 아니라 배타 관계**다 — Anthropic은 캐시 적중분을 input_tokens에서 "
            "빼고 여기에 따로 센다. None=미기록(캐시 개념이 없는 로컬 Ollama 경로·응답 미노출·"
            "이 컬럼 신설 이전 구행)이고 0=읽었는데 적중 0(실측)이다. 캐싱 플래그가 켜진 "
            "회차에서 0이 이어지면 '켰지만 작동 안 함'이다(작동 신호 없는 알고리즘 부착 금지)."
        ),
        ge=0,
    )
    cache_creation_input_tokens: int | None = Field(
        default=None,
        description=(
            "프롬프트 캐시에 *쓰인* 프리픽스 토큰 수(EOS-99 — 첫 회차 호출에서 발생·약 1.25배 "
            "과금). 의미 규약은 `cache_read_input_tokens`와 동일(None=미기록·0=실측 0)."
        ),
        ge=0,
    )
    cost_usd: float | None = Field(
        default=None,
        description="호출 비용(USD) — DECIMAL(8,4)",
        ge=0,
    )
    latency_ms: int | None = Field(
        default=None,
        description="지연 시간(ms)",
        ge=0,
    )
    success: bool | None = Field(default=None, description="성공 여부")
    error_detail: str | None = Field(default=None, description="실패 사유(있으면)")
    generated_at: datetime | None = Field(default=None, description="생성 시각")

    # ── 생성 Run 재현 좌석 (EOS-55) — 전부 Optional·NULL=미기록(0/빈값 날조 금지) ──
    prompt_version: str | None = Field(
        default=None,
        description=(
            "실제 사용한 프롬프트 정본의 식별자 — 별도 버전 체계가 없으므로(2026-08-30 실측: "
            "prompt_template_id 적재 0·Langfuse 프롬프트 버전 미사용) 정본 자산 내용 해시로 "
            "식별한다(예 'l3.equivalent@sha256:abc123def456'). 템플릿 체계가 없는 경로"
            "(pregenerate 인제스트 등)는 None=미기록."
        ),
        max_length=128,
    )
    seed: int | None = Field(
        default=None,
        description=(
            "생성 호출에 *실제로 쓰인* 샘플링 시드(EOS-73 스레딩 착지 — LOCAL/Ollama "
            "options.seed). 값이 있으면 '이 시드로 모델에 보냈다'는 뜻이고, None은 미기록이다 "
            "— 시드를 물리적으로 실을 수 없는 경로(클라우드 Anthropic Messages API에 seed "
            "파라미터 부재)와 호출 자체가 없었던 항목(인제스트·스킵)이 None이다. 보내지 않은 "
            "숫자를 적으면 그 행은 재현 가능하다고 거짓말하게 된다(날조 금지)."
        ),
    )
    input_sha256: str | None = Field(
        default=None,
        description=(
            "입력 스냅샷의 sha256 hex(canonical 직렬화 기준) — 무결성 축. 스냅샷이 있으면 "
            "validator가 자동 보충·대조하므로 호출자가 직접 계산할 필요 없다."
        ),
        pattern=r"^[0-9a-f]{64}$",
    )
    input_snapshot: dict[str, Any] | None = Field(
        default=None,
        description=(
            "입력 스냅샷(자기완결 복원 재료) — 프롬프트·시스템 **전문(verbatim)** + sha256 "
            "무결성 핀 + 라우팅 request·스펙 필드 원문. 해시만으로는 입력을 재구성할 수 "
            "없으므로 전문을 담는다(#912 P1-1 — 자체 문면이라 저작권 무관·행당 수 KB 허용). "
            "복원은 `restore_input_snapshot`(해시 대조 통과분만 반환)."
        ),
    )
    run_id: str | None = Field(
        default=None,
        description=(
            "이 호출이 속한 **생성 회차(Run) 식별자** — 리콜의 조인 축(EOS-97). 종전에는 "
            "run_id가 `AccumulateReport`·`ReviewQueueEntry`에만 있고 GenerationLog에는 없어 "
            "'이 배치로 만든 산출물'을 기계가 특정할 수 없었다(설계서 §3 리콜 시나리오가 "
            "짚은 실제 공백). 값은 회차 시작 시 호출자가 정하고 JSONL append 시 스탬프된다 "
            "— 회차 개념이 없는 경로(pregenerate 단발 인제스트)는 None=미기록(날조 금지)."
        ),
        max_length=64,
    )
    # ── 관측 좌석 (EOS-112) — 위 필드들이 '설정이 뭐라고 했나'라면 이 둘은 '누가 실제로
    # 답했나'다. `model_name`은 설정 유래 **선언값**이라(ARCH-58) provider 측 대체·폴백·
    # 프록시 라우팅이 일어나도 그대로다 — 그 어긋남을 볼 수 있는 유일한 축이 여기다.
    served_model: str | None = Field(
        default=None,
        description=(
            "응답이 *실제로 어느 모델에서 왔는지* — provider 응답 최상위의 모델 식별자"
            "(OpenAI 호환 `model` · Anthropic `message.model` · Ollama `model`). "
            "None=미관측이며 **설정값으로 접지 않는다** — 접으면 `model_name`의 복사본이 "
            "되어 대조 축이 영영 0건 어긋남을 보고한다. `model_name`과 다른 것이 곧 "
            "이상은 아니다: 별칭→버전 해소(`claude-sonnet-4-6` → 날짜 붙은 ID)도 같은 "
            "차이로 나타나므로, 이 값은 *판정*이 아니라 *볼 자리*를 가리키는 신호다."
        ),
        max_length=128,
    )
    retries: int | None = Field(
        default=None,
        description=(
            "이 호출 1건에서 일어난 재시도 횟수. None=미계측(Anthropic SDK·Ollama는 우리 "
            "전송기를 타지 않아 카운터가 없다)이고 0=계측했고 한 번에 성공(실측)이다. "
            "재시도는 측정을 가린다 — 30% 실패를 재시도로 덮으면 리포트가 100% 성공으로 "
            "보이고 운영에서 같은 부하를 만났을 때 지연·쿼터 소모가 설명되지 않는다."
        ),
        ge=0,
    )
    cu_slug: str | None = Field(
        default=None,
        description=(
            "생산된 CU(콘텐츠 단위)의 안정 slug — 코퍼스 키·검수 타이머 `cu_slug`와 동일 "
            "산식(#912 P1-2: `ops/hit_cu_metrics --generation-log` CU 조인 정체성). 호출이 "
            "후보 조립까지 도달하지 못했거나(파싱 실패 등) 경로에 CU 정체성이 없으면"
            "(pregenerate 캐시 시드) None=미기록 — 날조 금지."
        ),
        max_length=128,
    )

    @model_validator(mode="after")
    def _enforce_input_snapshot_integrity(self) -> GenerationLog:
        """스냅샷↔해시 정합 강제 — 재현 계약의 쓰기측 봉인.

        ① 스냅샷이 있는데 해시가 없으면 canonical 해시를 *자동 보충*한다(호출자 계산
           드리프트 원천 제거 — 해시 계산 정본은 `input_snapshot_sha256` 하나).
        ② 둘 다 있는데 불일치면 ValueError — 변조/파손된 재현 주장을 적재 단계에서 거부한다
           (DB `to_schema`·JSONL 로드가 model_validate를 거치므로 읽기측도 같은 봉인을 지난다).
        해시만 있고 스냅샷이 없는 레코드는 허용한다(참조가 외부에 있는 경로의 정직한 부분
        기록 — 복원 시도는 `restore_input_snapshot`이 ValueError로 정직 실패).
        """
        if self.input_snapshot is not None:
            recomputed = input_snapshot_sha256(self.input_snapshot)
            if self.input_sha256 is None:
                # validator 안 대입 — mode="after"라 재검증 루프 없음(pydantic v2 규약).
                self.input_sha256 = recomputed
            elif self.input_sha256 != recomputed:
                raise ValueError(
                    "input_sha256이 input_snapshot의 canonical 해시와 불일치 — "
                    f"기록 {self.input_sha256[:12]}… ≠ 재계산 {recomputed[:12]}… "
                    "(변조/파손된 재현 주장은 적재 거부)."
                )
        return self
