"""ProblemVersion Pydantic 계약 — ARCH-31 (44_eos_version_management.md §6.3).

Problem 엔티티(`problem` 테이블, `problem_id` UUID)의 **버전 스냅숏**. `44` §6.1 Hybrid
구조의 "도메인별 버전 테이블" 절반이며, 공통 헤더는 `schema/version_header.py`의
`VersionHeader`가 단일 진실이다. 짝 모델은 `schema/concept_version.py`(EOS-49)다 —
같은 평탄화 방식·같은 서브모델 재사용 방식을 그대로 따른다(계약 이중 정의 방지).

범위 판정(태스크 ARCH-31 승계 대조표 · 게이트 `G-eos49-content-version-seat` D안):
  범용 `ContentVersion`(Pydantic·ORM 양쪽)은 만들지 않는다. 공통 축은 `VersionHeader`
  Pydantic 계약으로만 공유하고, 영속은 도메인 테이블(`problem_version` — Problem 좌석 3번째)이
  맡는다. 원 제목의 `content_version_id`는 `Problem.problem_version_id`로 읽는다.

Principle 1(Entity ID ≠ Version ID):
  `problem_id: uuid.UUID`가 `VersionHeader.entity_id`에 대응하는 엔티티 ID다(44 §6.3
  `problem_id: UUID  # Problem entity FK`). Concept는 의미 ID(`code`, 문자열)를 쓰지만
  Problem의 PK는 UUID 대리키이고 의미 식별자(`slug`/`external_id`)는 nullable·UNIQUE라 FK
  대상으로 부적합하다 — 그래서 UUID PK를 참조한다. `version_id`는 이 버전 레코드 자체의 UUID다.

`identity_id`(변형 계열)와의 관계 — 직교하는 두 축이다(`docs/architecture/
arch31_problem_version.md` §2):
  `identity_id`는 "같은 문제의 다른 *개체*(원본+rephrase 계열)"를 묶는다(수평, 개체마다
  problem_id가 다르다). `problem_version`은 "한 *개체*의 시간에 따른 판"을 쌓는다(수직,
  problem_id는 같고 version_no만 증가). 그러므로 `ProblemVersion`은 `identity_id`를 *복제하지
  않는다* — 계열 소속은 `problem.identity_id`가 정본이고 버전 스냅숏에 박으면 두 곳이 갈라진다.

payload(`ProblemVersionPayload`)는 **Problem 전체를 복제하지 않는다** — 문항의 *내용을 정의하는*
필드만 담는다(발문·보기·정답·해설·형식·교육과정 좌표). 난이도 5축·임베딩·검수 상태·격리 사유 같은
운영/파생 축은 넣지 않는다(각자 자기 테이블·컬럼이 정본이고, 판이 갈릴 때마다 복제하면 정본이
둘이 된다). 더 필요하면 `schema_version`을 올려 확장한다.

**저작권 불변식은 payload에도 걸린다.** `problem` 쪽 교정 불변식(평가원·EBS·교과서는 본문
미보유)은 `schema.Problem`의 validator가 강제하는데, 버전 payload가 그 우회로가 되면 안 된다 —
본문을 못 갖는 출처가 *버전 스냅숏*을 통해 본문을 저장할 수 있게 되기 때문이다. 같은 출처 집합
(`METADATA_ONLY_SOURCES` — 한 벌, 복제 금지)으로 같은 필드를 막는다.

컨벤션(`schema/concept_version.py` 답습):
  - `ConfigDict(extra="forbid", use_enum_values=True, str_strip_whitespace=True)`.
  - enum은 `schema/enums.py` 재사용.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from whymath_backend.schema.enums import (
    AnswerFormat,
    Curriculum,
    QuestionFormat,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem import METADATA_ONLY_SOURCES
from whymath_backend.schema.version_header import (
    VersionChange,
    VersionGovernance,
    VersionIntegrity,
    VersionQA,
    VersionSource,
    VersionStatus,
)


# ──────────────────────────────────────────────────────────────────────────
# ProblemVersionPayload — 문항의 내용을 정의하는 필드만
# ──────────────────────────────────────────────────────────────────────────
class ProblemVersionPayload(BaseModel):
    """한 버전 시점의 Problem 내용 스냅숏 — `schema.Problem`의 *내용 정의* 필드만 포함.

    포함: 출처(`source_type` — 저작권 불변식의 근거라 반드시 동반)·과목·교육과정 좌표
    (`subject`·`curriculum_version`·`unit_codes`)·형식(`question_format`·`answer_format`·`points`)·
    본문 4종(`question_text`·`choices`·`answer`·`answer_explanation`)·44 §6.3이 지목한
    problem-specific 메타(`stem_hash`·`answer_hash`·`difficulty_at_publish`).

    제외(의도적): 난이도 5축·검수/격리 상태·임베딩·distractor_map·conditions_parsed·확장 payload.
    제외한 것들은 각자의 컬럼/테이블이 정본이다 — 여기 복제하면 정본이 둘이 된다.
    """

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    source_type: SourceType = Field(
        ..., description="출처(스냅숏 시점) — 저작권 불변식의 근거라 payload에 반드시 동반."
    )
    subject: Subject = Field(..., description="과목(스냅숏 시점).")
    curriculum_version: Curriculum = Field(..., description="교육과정 버전(스냅숏 시점).")
    unit_codes: list[str] = Field(
        default_factory=list, description="단원/성취기준 코드 배열(스냅숏 시점)."
    )
    question_format: QuestionFormat | None = Field(
        default=None, description="문항 형식(스냅숏 시점)."
    )
    answer_format: AnswerFormat | None = Field(default=None, description="답 형식(스냅숏 시점).")
    points: int | None = Field(default=None, description="배점(스냅숏 시점).", ge=0)

    question_text: str | None = Field(
        default=None, description="발문 원문(스냅숏 시점 — 본문 미보유 출처는 비어야 함)."
    )
    choices: list[str] | None = Field(
        default=None, description="객관식 보기(스냅숏 시점 — 본문 미보유 출처는 비어야 함)."
    )
    answer: str | None = Field(default=None, description="정답(스냅숏 시점 — 내부 전용).")
    answer_explanation: str | None = Field(
        default=None, description="해설(스냅숏 시점 — 본문 미보유 출처는 비어야 함)."
    )

    # 44 §6.3 "problem-specific 메타: stem_hash, answer_hash, difficulty_at_publish".
    stem_hash: str | None = Field(
        default=None, description="발문 해시(변경 탐지 — 알고리즘은 발행 경로가 정함)."
    )
    answer_hash: str | None = Field(default=None, description="정답 해시(변경 탐지).")
    difficulty_at_publish: float | None = Field(
        default=None,
        description="발행 시점 종합 난이도 1-5(이후 재보정과 무관하게 그 판의 값을 고정).",
        ge=1.0,
        le=5.0,
    )

    @model_validator(mode="after")
    def _enforce_copyright_no_body_for_metadata_sources(self) -> ProblemVersionPayload:
        """법적 교정 — 평가원/EBS/교과서 출처의 버전 스냅숏도 본문 필드를 가질 수 없다.

        `schema.Problem`의 같은 불변식을 *버전 경로에서 재집행*한다. 출처 집합은
        `METADATA_ONLY_SOURCES` 한 벌을 그대로 쓴다(두 곳에 복제하면 노출 게이트가 갈라진다).
        """
        source_value = (
            self.source_type.value if isinstance(self.source_type, SourceType) else self.source_type
        )
        if source_value not in {s.value for s in METADATA_ONLY_SOURCES}:
            return self

        offending: list[str] = []
        if self.question_text:
            offending.append("question_text")
        if self.answer_explanation:
            offending.append("answer_explanation")
        if self.choices:
            offending.append("choices")
        if offending:
            raise ValueError(
                f"저작권 교정 위반: source_type={source_value!r}(평가원/EBS/교과서)는 본문·문항 "
                f"미보유여야 한다 — 버전 스냅숏도 예외가 아니다(저작권 가이드 v2.0 §32 단서). "
                f"비어 있어야 할 본문 필드에 값이 있음: {offending}."
            )
        return self


# ──────────────────────────────────────────────────────────────────────────
# ProblemVersion — VersionHeader 평탄화 + problem_id(엔티티 FK) + payload
# ──────────────────────────────────────────────────────────────────────────
class ProblemVersion(BaseModel):
    """Problem 버전 레코드 — `VersionHeader`(§6.2) 평탄화 + `problem_id`(§6.3) + payload.

    `entity_type`은 이 도메인 버전 테이블에서 항상 `"Problem"`이다(계약상 자유 문자열로 열어
    두는 것은 `VersionHeader` 원 계약·`ConceptVersion`과 동형).

    Lifecycle 불변식(PUBLISHED payload 불변·PUBLISHED→DRAFT 금지)은 **이 Pydantic 모델이
    강제하지 않는다** — Pydantic은 구조만 검증한다. 허용 전이는 전이표
    (`schema/version_lifecycle.py`)가, PUBLISHED 불변성의 최후 방어는 DB 트리거
    (`db/models/problem_version.py` + alembic)가 맡는다.

    **전이 *실행*(게이트 경유)은 아직 이 도메인에 없다** — `l3/publish_gate.py`는 현재
    `ConceptVersion`만 안다(문항 발행 경로는 별도 태스크). 그 전까지 `problem_version`에는
    운영 writer가 없고, 이 계약은 스키마·영속 좌석·불변성 트리거까지다.
    """

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    version_id: uuid.UUID = Field(
        default_factory=uuid4,
        description="버전 PK(UUID) — Problem.problem_id(엔티티 UUID)와 별개.",
    )
    problem_id: uuid.UUID = Field(
        ...,
        description="소속 Problem의 PK(`problem.problem_id`) — VersionHeader.entity_id에 대응.",
    )
    entity_type: str = Field(
        default="Problem",
        description="엔티티 유형 — 이 도메인 테이블에서는 항상 'Problem'.",
    )
    version_no: int = Field(..., description="problem_id 내 버전 순번(1부터 증가).", ge=1)
    schema_version: str = Field(
        ..., description="payload가 따르는 스키마 버전 태그(예: 'problem-schema@1')."
    )
    status: VersionStatus = Field(
        default=VersionStatus.DRAFT, description="생명주기 상태(44 §7) — 기본 DRAFT."
    )
    previous_version_id: uuid.UUID | None = Field(
        default=None, description="직전 버전의 version_id(self-FK, 최초 버전이면 None)."
    )
    change: VersionChange = Field(default_factory=VersionChange, description="변경 성격.")
    source: VersionSource = Field(default_factory=VersionSource, description="원천 정보.")
    governance: VersionGovernance = Field(
        default_factory=VersionGovernance, description="검토·승인 이력."
    )
    integrity: VersionIntegrity = Field(
        default_factory=VersionIntegrity, description="무결성 검증 정보."
    )
    qa: VersionQA = Field(
        default_factory=VersionQA,
        description="게이트 통과 기록(§9 QA 연결) — 문항 게이트가 생기면 그 모듈만 채운다.",
    )
    payload: ProblemVersionPayload = Field(..., description="이 버전 시점의 Problem 내용 스냅숏.")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="레코드 생성 시각.")
    published_at: datetime | None = Field(
        default=None, description="PUBLISHED로 전이된 시각(발행 전이면 None)."
    )


__all__ = ["ProblemVersionPayload", "ProblemVersion"]
