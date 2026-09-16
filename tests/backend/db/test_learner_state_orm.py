"""`learner_state` ORM 스키마 계약 — 확장 규약 동결 (EOS-103 acceptance ⑤).

**동결하는 것**:
  ① 학생당 1행 — PK가 `learner_id` 단일 컬럼이다(대리키를 더하면 같은 학생에게 두 행이
     생기는 상태가 *표현 가능해지고*, 그 순간 "현재 상태"의 정의가 흔들린다).
  ② 파생 축 미복제 — 숙련·오개념 맵 컬럼이 생기면 RED. 그 축의 정본은 각각
     `concept_mastery_history`·`skill_mastery_history`·`misconception_hypothesis`이고,
     여기에 복제하면 같은 사실의 두 번째 진실 원천이 된다(붕괴 연쇄 "유지보수 지옥").
  ③ **필드 추가만으로 확장** — 신규 컬럼은 nullable이거나 server_default를 가져야 한다.
     그래야 BKT/DKT 축이 생산자를 얻어 컬럼이 늘 때 기존 행 백필 없이 편입된다. 이 검사가
     없으면 "확장 가능하게 설계했다"가 주석 속 주장으로만 남는다.

**동결하지 않는 것**(있는 척 금지): 실 PG 왕복(server_default 실행·FK 제약 작동)은 여기서
보지 않는다 — 마이그레이션과 통합 테스트의 몫이다.
"""

from __future__ import annotations

import sqlalchemy as sa

from whymath_backend.db.models.learner_state import LearnerStateRecord

_TABLE = LearnerStateRecord.__table__

# 파생 축 — 이 테이블에 복제되면 안 되는 이름들. 정본 테이블이 따로 있다.
_FORBIDDEN_COLUMN_TOKENS: tuple[str, ...] = (
    "mastery",
    "misconception",
    "theta",
    "ability",
    "bkt",
    "irt",
)

# 확장 규약의 예외 — 행 생성 시점에 반드시 정해지는 축이라 "나중 백필" 문제가 성립하지 않는다.
# 사유를 값으로 강제해 "일단 여기에 던져 넣기"를 비싸게 만든다(NON_CORE_TABLES 선례).
_CREATION_REQUIRED_COLUMNS: dict[str, str] = {
    "learner_id": "PK — 행의 신원. 없으면 행이 아니다.",
    "provisioned_by": "생성 계보 — 기본값을 주면 '무엇이 이 상태를 만들었는가'가 "
    "출처 불명인 채로 행이 생길 수 있다. 계보는 추론이 아니라 기록이어야 한다.",
}


def test_table_name_is_frozen() -> None:
    assert _TABLE.name == "learner_state"


def test_primary_key_is_learner_id_alone() -> None:
    """학생당 정확히 1행 — 대리키 도입은 이 검사를 통과하지 못한다."""
    pk_columns = [c.name for c in _TABLE.primary_key.columns]
    assert pk_columns == ["learner_id"], f"PK가 바뀌었다: {pk_columns}"


def test_learner_id_references_user_profile() -> None:
    fks = {fk.target_fullname for fk in _TABLE.c.learner_id.foreign_keys}
    assert fks == {"user_profile.user_id"}, f"FK 타깃이 바뀌었다: {fks}"


def test_no_derived_axis_is_duplicated_here() -> None:
    """숙련·오개념·능력치 컬럼이 생기면 RED — 두 번째 진실 원천 금지."""
    breaches = sorted(
        c.name
        for c in _TABLE.columns
        if any(token in c.name.lower() for token in _FORBIDDEN_COLUMN_TOKENS)
    )
    assert not breaches, (
        f"파생 축이 learner_state에 복제됐다: {breaches}\n"
        "숙련은 concept_mastery_history·skill_mastery_history, 오개념은 "
        "misconception_hypothesis가 정본이다. 조립은 l2/learner_state.py::get_state."
    )


def test_every_column_is_nullable_or_has_a_default() -> None:
    """확장 규약 — 신규 컬럼이 기존 행 백필을 요구하면 RED.

    예외는 **행 생성 시점에 반드시 정해지는 두 축**뿐이다(`_CREATION_REQUIRED_COLUMNS`):
    행의 신원(PK)과 생성 계보. 이 둘은 "나중에 추가되는 축"이 아니라 행이 존재하려면 이미
    있어야 하는 값이라 백필 문제가 성립하지 않는다. 그 외의 NOT NULL·무기본값 컬럼은
    기존 행에 채울 값이 없다는 뜻이므로 RED다.

    이 예외가 조용히 늘면 규약이 무력해지므로 `test_creation_required_exemptions_are_frozen`
    이 목록 자체를 동결한다.
    """
    offenders = sorted(
        c.name
        for c in _TABLE.columns
        if c.name not in _CREATION_REQUIRED_COLUMNS
        and not c.nullable
        and c.server_default is None
        and c.default is None
    )
    assert not offenders, (
        f"백필을 요구하는 NOT NULL 컬럼: {offenders}\n"
        "EOS-103 확장 규약 — 신규 컬럼은 nullable이거나 server_default를 갖는다."
    )


def test_creation_required_exemptions_are_frozen() -> None:
    """확장 규약의 예외 목록이 늘면 RED — 예외가 자라면 규약은 위장이 된다."""
    assert set(_CREATION_REQUIRED_COLUMNS) == {"learner_id", "provisioned_by"}, (
        "확장 규약 예외가 바뀌었다 — 새 예외를 넣기 전에 '이 컬럼이 정말 생성 시점에 "
        "반드시 정해지는가'를 답하고 사유를 상수에 적어라."
    )
    for name in _CREATION_REQUIRED_COLUMNS:
        assert name in _TABLE.c, f"예외로 적힌 {name}가 테이블에 없다(상수 드리프트)"


def test_provisioning_lineage_columns_exist() -> None:
    """생성 시점·계기·변경 회계 축이 사라지면 RED(단일 쓰기 경로의 관측 축)."""
    for name in ("provisioned_at", "provisioned_by", "updated_at", "revision"):
        assert name in _TABLE.c, f"계보 컬럼 {name}가 사라졌다"
    assert isinstance(_TABLE.c.revision.type, sa.Integer)


def test_curriculum_and_objective_are_loose_references() -> None:
    """두 축은 FK 미적용이 **결정**이다 — 조용히 FK가 붙으면 사람이 판정하게 한다.

    사유는 ORM 모듈 주석: 교육과정 키(framework/version)가 미결정이고, 목표 삭제가 학생
    상태 행을 막아서는 안 된다.
    """
    assert not _TABLE.c.curriculum_id.foreign_keys
    assert not _TABLE.c.current_objective_id.foreign_keys
