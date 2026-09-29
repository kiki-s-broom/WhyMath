"""Hint 영속 ORM(`hints`) — graded 힌트 카탈로그 좌석 실체화 (S4-11 · D3 · HintNode 연기 해제).

설계 정본: `schemas/v1.1/hint.schema.yaml`(entity Hint·layer L4 — 필드·invariant 정본)·
`docs/architecture/solution_module_gap_review.md` §3 D3·`canonical_entity_model_v1.md` §3-B.
검증 Pydantic 정본은 `l4/hint_content/models.py`(Hint·HintReveals·SolutionStepRef) — 본 모듈은
*영속 스키마*만 둔다. ORM↔Pydantic 매핑은 L4 store(`l4/hint_content/store.py`)가 수행한다
(db가 l4를 import하지 않는다 — `db/models/solution_path.py`와 같은 계층 위생).

**연기 해제 근거(MEMORY 2026-07-08 "Phase 6b = HintNode Persistence 연기")**: 그때 이 테이블을
만들지 않은 이유는 writer 0·reader 0(dead code)였고, 도입 전제는 ① generation ② validation
③ serving 중 실 writer+reader가 함께 실재하는 것이었다. 이 슬라이스가 셋을 한 번에 세운다 —
writer = `l4/hint_content/populate.py`(오프라인 생성 CLI) → `store.write_hints`, validation =
`l4/hint_content/gates.py`(게이트 3종), reader = `store.find_served_hint` ← `api/coach.py` 세션 2경로.
그때 적어 둔 미러 선례도 그대로 승계한다: 구조 = `curriculum_entry.py`(string PK·느슨참조
가능), payload = `verified_solution.py`(JSONB). 그때 "`SolutionPath` 실테이블 부재 → FK 금지"였던
전제는 S4-09가 `solution_paths`를 세우며 해소됐으므로 이제 FK를 건다(아래).

영속 매핑 결정(근거 병기):
  - `hint_id` TEXT PK — yaml `type: string`. 생성기가 `hint-{solution_path_id}-s{order}-l{level}`
    결정론 ID를 부여한다 → 재실행 멱등(헌법 R3-01 '두 번 실행' 계약)·생성 자리 키(R3-02 동형).
  - `solution_path_id` TEXT **FK solution_paths ON DELETE CASCADE** — 힌트는 경로의 순수 파생물
    (재생성 가능)이라 경로가 사라지면 함께 사라지는 것이 정합이다. `step_order`는 정수 좌석만 —
    `problem_step`에는 `(solution_path_id, step_order)` UNIQUE가 없어 복합 FK를 걸 수 없다
    (단계 실재 검증은 생성 시점 책임 — 생성기가 실재 단계에서만 힌트를 만든다).
  - `problem_id` UUID NOT NULL FK problem — yaml에선 "조회 편의 중복"이지만 서빙 reader의 조회
    키(문제 단위)라 NOT NULL로 둔다.
  - `level` SMALLINT NOT NULL + **CHECK 1~3** — Level 4(전체 풀이)는 Hint 엔티티 *밖* 안전망이다
    (yaml `level` note·`hint_deferral.HintLevel`의 4는 이 테이블에 표현될 수 없다). Pydantic
    `Literal[1, 2, 3]`과 DB CHECK의 이중 봉인(가짜 CHECK 아님 — 실재하는 도메인 경계).
  - `reveals_*` 3 BOOL + `revealed_concept_ids` JSONB + `reveal_score` FLOAT(CHECK 0~1) — yaml
    `HintReveals` 1:1. 게이트 A가 본문에서 *파생*한 노출과 선언이 일치할 때만 verified가 된다.
  - `socratic_category` TEXT nullable — 기존 L4 6카테고리(`l4.socratic.SocraticCategory`) 값만
    담는다(**신규 힌트 유형 enum 미도입** — acceptance. PG enum도 만들지 않는다).
  - `verified` BOOL NOT NULL default false — 게이트 3종 통과분만 true. **서빙 reader는
    verified=true만 읽는다**(yaml invariant "verified=false 인 Hint 는 학생에게 제공 불가").
  - `gate_report` JSONB NOT NULL default '{}' — 게이트별 판정·사유(조용한 실패 금지 — 왜
    거부됐는지가 행에 남는다). `none_as_null=True`(SEC-06 전수 거버넌스).
  - `generator_version` TEXT NOT NULL — 어떤 템플릿 판이 만든 본문인지(재현·재생성 추적).
    yaml `generated_by_tier`(LLM 티어)는 **두지 않는다** — 이 생성기는 LLM 호출 0(템플릿)이라
    항상 NULL인 죽은 컬럼이 된다. LLM 생성 경로가 생기면 그때 라우터 결정과 함께 더한다.
  - `created_at`·`updated_at` TIMESTAMPTZ NOT NULL default now() — 재생성 시 updated_at 갱신.

인덱스: `idx_hints_serving (problem_id, level, step_order)` — coach reader가 "이 문제·이 레벨·
이 단계 이후 첫 검수 힌트"를 찾는 접근 패턴 그대로. `uq_hints_step_level` — 한 단계·한 레벨에
힌트 1개(생성 자리 유일성).

**본문 좌석 단일화**: 힌트 본문은 오직 이 테이블의 `content`에 산다. 다른 테이블에 힌트 본문
컬럼이 생기는 것은 `test_canonical_entity_model_freeze.py::test_no_table_gains_a_hint_body_column`
이 계속 막는다(그 가드는 이제 '좌석 부재'가 아니라 '좌석 단일' 동결이다).

개인정보 메모(CLAUDE.md): 시스템이 생성한 교수 콘텐츠이며 학생 PII·행동 데이터가 아니다
(`user_id` 컬럼 없음 — privacy 3종 배선 대상 아님·`verified_solutions`·`solution_paths` 동일 방침).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from whymath_backend.db.base import Base


class Hint(Base):
    """graded 힌트 1개 — 한 풀이 경로의 한 단계·한 레벨(1~3)의 본문과 노출량·검증 상태.

    한 단계에 최대 3행(L1 개념 이름·L2 단계 흐름·L3 부분 시연). Level 4(전체 풀이)는 CHECK로
    표현 불가 — WhyMath 답 미루기 4단계의 마지막 칸은 이 엔티티 밖 안전망으로 남는다.
    """

    __tablename__ = "hints"

    # ===== 식별·참조 =====
    hint_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    # 힌트는 경로의 파생물 — 경로 삭제 시 동반 삭제(재생성 가능·모듈 docstring 근거).
    solution_path_id: Mapped[str] = mapped_column(
        sa.Text,
        sa.ForeignKey("solution_paths.solution_path_id", ondelete="CASCADE"),
        nullable=False,
    )
    # 경로 안 단계 order(1부터) — 복합 FK 불가(problem_step에 해당 UNIQUE 없음)라 정수 좌석만.
    step_order: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    # 서빙 조회 키(문제 단위) — 편의 중복이지만 reader 인덱스 선두라 NOT NULL.
    problem_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("problem.problem_id"), nullable=False
    )

    # ===== graded 레벨·본문 =====
    # 1~3만(CHECK) — Level 4는 Hint 엔티티 밖 안전망(yaml level note).
    level: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # 기존 L4 소크라테스 6카테고리 값(TEXT 좌석 — 신규 enum·PG enum 미도입).
    socratic_category: Mapped[str | None] = mapped_column(sa.Text)

    # ===== 노출량(HintReveals) — graded의 정량화 핵심 =====
    reveals_concept_names: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    reveals_step_flow: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    reveals_partial_computation: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    # 노출한 개념 ID(UC 코드 공간 — concept_node.concept_id = concept.code). SEC-06 none_as_null.
    revealed_concept_ids: Mapped[list[str]] = mapped_column(
        JSONB(none_as_null=True), nullable=False, server_default=sa.text("'[]'::jsonb")
    )
    # 종합 노출 점수 0~1 — KPI '답 미루기 도달 깊이'의 정밀화 신호(CHECK로 범위 봉인).
    reveal_score: Mapped[float] = mapped_column(sa.Float, nullable=False)

    # ===== 검증·출처 =====
    # 게이트 3종 통과분만 true — 서빙 reader는 true만 읽는다.
    verified: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.false())
    # 게이트별 판정·사유(거부 이유가 행에 남는다). SEC-06 none_as_null.
    gate_report: Mapped[dict[str, Any]] = mapped_column(
        JSONB(none_as_null=True), nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    generator_version: Mapped[str] = mapped_column(sa.Text, nullable=False)

    # ===== 운영 메타 =====
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )

    __table_args__ = (
        # CHECK 이름은 명명 규약(`ck_%(table_name)s_%(constraint_name)s`)이 접두를 붙인다 —
        # 최종 이름 = ck_hints_level_graded_1_3 등(마이그레이션은 op.f로 같은 최종 이름을 적는다).
        sa.CheckConstraint("level BETWEEN 1 AND 3", name="level_graded_1_3"),
        sa.CheckConstraint("reveal_score >= 0 AND reveal_score <= 1", name="reveal_score_unit"),
        sa.CheckConstraint("step_order >= 1", name="step_order_positive"),
        sa.UniqueConstraint("solution_path_id", "step_order", "level", name="uq_hints_step_level"),
        sa.Index("idx_hints_serving", "problem_id", "level", "step_order"),
    )


__all__ = ["Hint"]
