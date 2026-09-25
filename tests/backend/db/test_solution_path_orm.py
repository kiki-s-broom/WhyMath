"""SolutionPath ORM(`solution_paths`) + problem_step additive 컬럼 — DB 연결 없이 검증 (S4-09).

`test_problem_orm.py` 컨벤션 미러: 살아있는 PostgreSQL을 요구하지 않는다(메타데이터 등록·
PG DDL 컴파일·컬럼 계약만). 실제 PG 적용(마이그레이션·FK 강제·CRUD)은 실 PG 통합검증 몫.

검증 핵심:
  - 메타데이터 등록: `solution_paths` 테이블·인덱스가 Base.metadata에 존재.
  - PG DDL 컴파일: TEXT PK·problem FK·JSONB·server_default가 DDL 문자열에 나타남.
  - problem_step additive 6컬럼: 전부 nullable(비파괴)·FK·JSONB `none_as_null=True`
    (SEC-06 — 전수 스캔은 `test_jsonb_none_as_null_governance.py`가 자동 검출·여기서는
    신규 컬럼을 이름으로 못박아 회귀를 지역화).
  - `embedding` 컬럼 부재(acceptance — S4-12에서 판정).
  - S4-10 추가: `gen_meta` JSONB 1컬럼(다중 풀이 생성 주관 메타·ai_estimated 게이팅 좌석) —
    `none_as_null=True`·nullable(레거시 승격 경로 비파괴).
  - alembic 마이그레이션 파일 존재·단일 head 체인(파일 시스템 검사 — DB 불요).
"""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.schema import CreateTable

from whymath_backend.db.base import Base
from whymath_backend.db.models.problem import ProblemStep
from whymath_backend.db.models.solution_path import SolutionPath

_REPO_ROOT = Path(__file__).resolve().parents[3]
_VERSIONS_DIR = _REPO_ROOT / "src" / "backend" / "alembic" / "versions"

# S4-09가 problem_step에 더한 additive 컬럼 6종(전부 nullable — 비파괴 계약).
_ADDITIVE_COLUMNS = (
    "solution_path_id",
    "concept_node_id",
    "reasoning_type",
    "justification",
    "common_errors",
    "sympy_verified",
)


class TestSolutionPathTable:
    def test_registered_in_metadata(self) -> None:
        """`solution_paths`가 Base.metadata에 등록(모델 패키지 import 경유)."""
        assert "solution_paths" in Base.metadata.tables

    def test_pg_ddl_compiles_with_expected_shapes(self) -> None:
        """PG DDL 컴파일 — TEXT PK·problem FK·JSONB·기본값이 연결 없이 생성된다."""
        ddl = str(CreateTable(SolutionPath.__table__).compile(dialect=postgresql.dialect()))
        assert "solution_paths" in ddl
        assert "PRIMARY KEY (solution_path_id)" in ddl
        assert "REFERENCES problem (problem_id)" in ddl  # 참조 실재의 DB 강제(적재 시점 책임)
        assert "JSONB" in ddl  # concept_sequence
        assert "'[]'::jsonb" in ddl  # 빈 골격 기본값(매칭 확정분만 — 날조 금지)
        assert "false" in ddl  # verified_by_human 기본 미검수(AI 자기승인 금지)

    def test_problem_index_exists(self) -> None:
        """문제 단위 조회 인덱스(`idx_solution_paths_problem`)가 선언돼 있다."""
        index_names = {index.name for index in SolutionPath.__table__.indexes}
        assert "idx_solution_paths_problem" in index_names

    def test_no_embedding_column(self) -> None:
        """`embedding` 컬럼 부재 — S4-12에서 판정(acceptance 명시)."""
        assert "embedding" not in SolutionPath.__table__.columns

    def test_concept_sequence_jsonb_none_as_null(self) -> None:
        """concept_sequence JSONB가 `none_as_null=True`(SEC-06 방침)."""
        column = SolutionPath.__table__.columns["concept_sequence"]
        assert isinstance(column.type, JSONB)
        assert column.type.none_as_null is True

    def test_gen_meta_column_nullable_jsonb_none_as_null(self) -> None:
        """S4-10: `gen_meta` JSONB 1컬럼 — nullable(비파괴)·`none_as_null=True`(SEC-06).

        다중 풀이 생성 주관 메타(elegance·educational_value·difficulty·key_insight·
        comparison + review_status=ai_estimated)의 단일 좌석(컬럼 폭발 방지 — acceptance).
        """
        column = SolutionPath.__table__.columns["gen_meta"]
        assert column.nullable is True
        assert isinstance(column.type, JSONB)
        assert column.type.none_as_null is True


class TestProblemStepAdditiveColumns:
    def test_all_additive_columns_exist_and_nullable(self) -> None:
        """additive 6컬럼 전부 존재·nullable — 기존 행·응답 비파괴 계약."""
        columns = ProblemStep.__table__.columns
        for name in _ADDITIVE_COLUMNS:
            assert name in columns, f"problem_step.{name} 부재"
            assert columns[name].nullable is True, f"problem_step.{name}은 nullable이어야 한다"

    def test_solution_path_fk_targets_new_table(self) -> None:
        """solution_path_id FK가 `solution_paths.solution_path_id`를 가리킨다."""
        fks = {
            fk.target_fullname
            for fk in ProblemStep.__table__.columns["solution_path_id"].foreign_keys
        }
        assert fks == {"solution_paths.solution_path_id"}

    def test_new_jsonb_columns_declare_none_as_null(self) -> None:
        """신규 JSONB 2컬럼(justification·common_errors)이 `none_as_null=True`(SEC-06).

        전수 스캔은 거버넌스 테스트가 자동 검출하지만, S4-09 신규분을 이름으로 못박아
        회귀 원인을 지역화한다.
        """
        for name in ("justification", "common_errors"):
            column = ProblemStep.__table__.columns[name]
            assert isinstance(column.type, JSONB)
            assert column.type.none_as_null is True, f"problem_step.{name}: none_as_null 필요"

    def test_existing_columns_untouched(self) -> None:
        """기존 컬럼 8종이 그대로 남아 있다(additive만 — 제거·개명 0)."""
        columns = set(ProblemStep.__table__.columns.keys())
        assert {
            "step_id",
            "problem_id",
            "step_order",
            "step_type",
            "step_title",
            "socratic_prompt",
            "expected_answer",
            "common_mistakes",
        } <= columns

    def test_unique_constraint_unchanged(self) -> None:
        """`UNIQUE(problem_id, step_order)` 불변 — 다중 경로 단계 영속은 S4-10 재론 경계."""
        unique_sets = [
            tuple(constraint.columns.keys())
            for constraint in ProblemStep.__table__.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        ]
        assert ("problem_id", "step_order") in unique_sets


class TestMigrationFileChain:
    def test_migration_file_exists_with_symmetric_updown(self) -> None:
        """S4-09 마이그레이션 파일이 존재하고 up/down이 대칭 대상(테이블·6컬럼)을 다룬다."""
        matches = list(_VERSIONS_DIR.glob("*solution_path_materialization.py"))
        assert len(matches) == 1, "S4-09 마이그레이션 파일이 정확히 1개여야 한다"
        source = matches[0].read_text(encoding="utf-8")
        assert 'op.create_table(\n        "solution_paths"' in source
        assert 'op.drop_table("solution_paths")' in source
        for name in _ADDITIVE_COLUMNS:
            assert f'sa.Column("{name}"' in source, f"upgrade에 {name} 추가 누락"
            assert (
                f'op.drop_column("problem_step", "{name}")' in source
            ), f"downgrade에 {name} 제거 누락(대칭 위반)"

    def test_single_head_chain(self) -> None:
        """versions 전체가 단일 head — down_revision으로 참조되지 않는 revision이 1개뿐."""
        revisions: set[str] = set()
        downs: set[str] = set()
        for path in _VERSIONS_DIR.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            # 타입 주석 유무 두 형식 모두 실재(무주석 선례: dialogue_image_envelope) — 둘 다 수용.
            rev = re.search(r'^revision(?:: str)? = "([0-9a-f]+)"', source, re.MULTILINE)
            down = re.search(
                r'^down_revision(?:: str \| None)? = "([0-9a-f]+)"', source, re.MULTILINE
            )
            if rev:
                revisions.add(rev.group(1))
            if down:
                downs.add(down.group(1))
        heads = revisions - downs
        assert len(heads) == 1, f"단일 head여야 한다 — 실제 heads: {sorted(heads)}"
        # SEC-33 ⑥이 problem_attempt.ingested_at에 server_default를 부여 — MISC-20 2건
        # (d2f4a68b91e7·e3b5c79d02f8) 위로 재부모화해 선형 적재(병렬 착지로 head가 갈라져
        # 재부모화·마이그레이션 docstring 참조). 건드리는 객체가 겹치지 않아 순서 의존 0.
        # 이 상수는 `db/schema_version.py::KNOWN_REVISIONS`의 마지막 항과 **함께** 움직인다 —
        # 마이그레이션을 더하면 두 곳을 같이 갱신해야 한다(둘 다 head를 고정한다).
        # SEC-29가 f2662166a661(SEC-27) 위에 4c6dfb1527a9(privacy_audit.resource_type/
        # resource_id/action)를 얹어 head를 이동.
        # SEC-31이 4c6dfb1527a9 위에 3f5c83f51246(학생 답안/풀이 3테이블 봉투 암호화)를 얹어
        # head를 다시 이동.
        # EOS-49가 3f5c83f51246 위에 67cf48ad3bce(concept_version 테이블 + PUBLISHED
        # 불변성 트리거)를 얹어 head를 다시 이동.
        # EOS-103이 67cf48ad3bce 위에 a7d41c9e0b52(learner_state 테이블 — 학습자 현재 상태
        # 1행 + 진단 완료 시 자동 생성 계보)를 얹어 head를 이동.
        # EOS-105가 그 위에 5a7c31d9e0b4(learning_state_transition 원장 + 상태·트리거 enum
        # 2종)를 얹어 head를 다시 이동. 두 PR이 같은 부모 위에서 병행 개발돼 head가 둘이 될
        # 뻔했고, 병합 시 EOS-105의 down_revision을 재지정해 직렬로 되돌렸다.
        # EOS-108이 그 위에 c1f5a8b2d740(concept/skill_mastery_history.attempt_id 멱등 키 +
        # 부분 유니크 인덱스 2종)을 얹어 head를 다시 이동.
        # EOS-112가 그 위에 d2a9e4b71c35(generation_log 관측 좌석)를, 이어서 ASM-06이
        # 5b3e9c27a1f6(problem_attempt.selected_choice_index)을
        # 얹어 head를 다시 이동. 이 리터럴은 head를 고정하는 **세 번째** 좌석이다
        # (schema_version.KNOWN_REVISIONS·probe_prod_schema_revision.sql이 나머지 둘) —
        # 손으로 유지하는 사본이 셋이라 마이그레이션마다 전부 갱신해야 한다(= MISC-31).
        # EOS-131이 그 위에 8e4c2a7f1b93(learning_session.last_activity_at + 학생당 열린 서버
        # 세션 부분 유니크 인덱스)을 얹어 head를 다시 이동.
        assert heads == {"8e4c2a7f1b93"}

    def test_gen_meta_migration_file_exists_with_symmetric_updown(self) -> None:
        """S4-10 `gen_meta` 마이그레이션 파일이 존재하고 up/down이 대칭(컬럼 add/drop)이다."""
        matches = list(_VERSIONS_DIR.glob("*solution_paths_gen_meta.py"))
        assert len(matches) == 1, "S4-10 gen_meta 마이그레이션 파일이 정확히 1개여야 한다"
        source = matches[0].read_text(encoding="utf-8")
        assert 'op.add_column(\n        "solution_paths"' in source
        assert 'op.drop_column("solution_paths", "gen_meta")' in source
        # down_revision이 CUR-16 리비전을 가리켜 체인이 이어진다(단일 head 불변의 짝).
        assert 'down_revision: str | None = "fad7f750090d"' in source
