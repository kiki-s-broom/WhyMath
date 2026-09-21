"""오개념 가설 영속 레코드(MisconceptionHypothesisRecord) Pydantic 스키마 — 열람·이동권 export.

`db/models/misconception_hypothesis.py`(ORM 정본·`MisconceptionHypothesisRecord`)의 검증·직렬화
표현이다. 도메인 순수 모델 `l4/misconception/hypothesis.MisconceptionHypothesis`(가설 신뢰·증거
필드만)와 달리 *영속 레코드 전체*(id·user_id·활성 플래그·타임스탬프 포함)를 담는다 — 본인 열람·
이동권 export가 행 전체를 내기 때문이다. ORM과 `to_schema`가 잇는다(parental_consent 동일 패턴).

**개인정보(CLAUDE.md)**: 활성 오개념 가설은 미성년 학생에 결부된 *민감 학생 데이터*이나 자유텍스트
PII는 없다(식별자·신뢰도·카운트·플래그·날짜만). export에 그대로 실어도 안전(redaction 불요)·민감도는
문서화로 명시(평문 저장·동의 없는 학습 사용 금지는 *저장·동의 계층* 책임).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MisconceptionHypothesisRecord(BaseModel):
    """오개념 가설 영속 레코드 1건(`misconception_hypothesis` 1행)의 검증·직렬화 표현."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: uuid.UUID = Field(description="가설 레코드 PK(UUID).")
    user_id: uuid.UUID | None = Field(
        default=None, description="데이터 주체 학생(user_profile FK·nullable)."
    )
    misconception_id: str = Field(description="오개념 카탈로그 id(kebab-case).")
    confidence: float = Field(description="가설의 현재 신뢰도(0~1).")
    turns_since_evidence: int = Field(description="마지막 증거 이후 경과 턴(감쇠 입력).")
    evidence_count: int = Field(description="이 가설을 지지한 누적 증거 수.")
    is_active: bool = Field(description="활성 여부(가지치기=비활성·행 삭제 X).")
    deactivated_reason: str | None = Field(
        default=None,
        description=(
            "비활성화 사유(resolved/refuted/decayed/capped). 활성 행·사유 미상 행은 None "
            "— 과거 행 백필 없음(MISC-20 정직 회계)."
        ),
    )
    created_at: datetime = Field(description="레코드 생성 시각(UTC).")
    updated_at: datetime = Field(description="레코드 갱신 시각(UTC).")
