"""problem_attempt.selected_choice_index — 학생이 고른 객관식 보기 인덱스 (ASM-06)

학생이 실제로 고른 객관식 보기의 0-기반 인덱스를 적재해 `Problem.distractor_map`과
대조하면 어느 오개념이 이 오답을 유발했는지 역추적할 수 있다
(`l4.misconception.distractor_link`). 지금까지 `student_answer`는 자유텍스트뿐이라
"몇 번 보기를 골랐는가" 자체가 채점 레이어에 없었다 — 선택 인덱스는 **클라이언트만 아는
사실**이라 요청 슬롯이 없으면 서버는 영원히 알 수 없다(선행 조사 결론: NLP-02 shadow
채점은 수치/기호식 검산 오프라인 배치이지 선택 인덱스를 포착하지 않는다).

사장 규모 실측은 `harness/distractor_signal_dormancy_report.py`(ASM-09)가 낸다 — MC 선지
보유 문항의 distractor_map은 완비돼 있고 포착 슬롯만 없어 `unreachable_no_capture_slot`
상태였다. 이 리비전이 그 리포트가 예약해 둔 슬롯명을 실제 컬럼으로 착지시킨다.

- **additive·nullable**: 기존 행은 전부 NULL(자유응답형·구버전 클라 등)로 남는다. 데이터
  백필 대상 없음 — "안 골랐다"와 "보고하지 않았다"를 0으로 뭉뚱그리지 않는다(NULL=미보고).
- `ge=0` 구조 검증은 `schema.activity.ProblemAttempt`(Pydantic) 책임 — DB CHECK는 두지
  않는다(`db/models/activity.py` 모듈 docstring의 "가짜 CHECK 금지" 방침과 정합).
- SEC-31 봉투 암호화 대상이 **아니다**: 그 보호는 답안·풀이 *본문*이고, 선지 번호는 같은
  행의 평문 `problem_id` 없이는 의미가 없는 작은 정수다.

부모 리비전은 2026-09-21 실측 단일 head `d2a9e4b71c35`(EOS-112)다. 고립 브랜치
`claude/subject-problems-theory-check-7n9n72`의 원 리비전 `0afd40ce1867`은 down_revision이
`7ef2b5a8e69e`(#738에서 건너뛴 폐기 리비전)이라 그대로 포트하면 multiple heads가 된다 —
재채번이 이 파일의 존재 이유다(ASM-06 acceptance ④).

Revision ID: 5b3e9c27a1f6
Revises: d2a9e4b71c35
Create Date: 2026-09-21 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "5b3e9c27a1f6"
down_revision: str | None = "d2a9e4b71c35"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """`problem_attempt.selected_choice_index` 추가(nullable INTEGER·기존 행 무영향)."""
    op.add_column(
        "problem_attempt",
        sa.Column("selected_choice_index", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    """컬럼 제거 — 선택 인덱스 기록만 소실(원본 attempt·student_answer·채점 결과는 무영향)."""
    op.drop_column("problem_attempt", "selected_choice_index")
