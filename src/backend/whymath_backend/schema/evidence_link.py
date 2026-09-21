"""학습 증거 그래프 엣지(EvidenceLink) Pydantic 스키마 — 열람·이동권 export·API 표현.

`db/models/evidence_link.py`(ORM 정본)의 검증·직렬화 표현이다. 한 행 = 한 학습 이벤트가 한 학생의
한 오개념 가설을 `polarity`(+1 지지/−1 반박)로 지지/반박한다는 증거(설계 04a §2.3). ORM과
`to_schema`가 잇는다(parental_consent·audit 동일 패턴).

**개인정보(04a §2.3·CLAUDE.md)**: 본 레코드는 *식별자·극성·가중치·날짜*만 담고 자유텍스트 PII가
없다(학생 풀이 원문·채팅은 별도 store·암호화 대상). 그래서 본인 열람·이동권 export에 *그대로*
실어도 안전하다(redaction 불요·민감도는 문서화로 명시).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class EvidenceLink(BaseModel):
    """학습 증거 엣지 1건(`evidence_links` 1행)의 검증·직렬화 표현."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    link_id: int = Field(description="증거 엣지 PK(BIGSERIAL·DB 할당).")
    session_id: uuid.UUID = Field(description="세션 맥락(느슨참조·FK 아님).")
    student_id: uuid.UUID = Field(
        description="데이터 주체 학생(user_profile FK·삭제권 ON DELETE CASCADE)."
    )
    event_id: int | None = Field(default=None, description="학습 이벤트(느슨참조)·미연결 None.")
    misconception_id: str = Field(description="오개념 카탈로그 id(kebab-case).")
    node_id: str | None = Field(
        default=None, description="커리큘럼 노드 concept_id(느슨참조)·맥락 없으면 None."
    )
    polarity: int = Field(description="증거 극성 — +1 지지·−1 반박.")
    weight: float | None = Field(default=None, description="verify/PRM 기반 가중치·미평가 None.")
    provenance: str | None = Field(
        default=None,
        description=(
            "증거 출처 표식(MISC-20). 기계가 확인한 사실만 값으로 남긴다 — 예: "
            "correct_form_demonstrated(정정 형태 실측). 모르면 None(해소 판정에서 제외)."
        ),
    )
    retention_until: date | None = Field(
        default=None, description="보존 기한(경과 시 야간 배치 파기)·미설정 None."
    )
    created_at: datetime = Field(description="증거 적재 시각(UTC).")
