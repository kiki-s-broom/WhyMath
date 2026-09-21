"""COLLAB-02 — 파기 계획 완전성 검사의 *방향 역전*(실행→계획, 소유 테이블 중 계획 누락 검출).

`test_erasure.py:94 test_covers_all_planned_tables`는 "`_ERASURE_PLAN`에 있는 테이블은 전부 실제
삭제 순서(`_delete_order`)에 등장하는가"(계획→실행, `planned <= order`)만 단언한다. 그 역방향 —
"소유 컬럼을 가진 테이블인데 `_ERASURE_PLAN`에 아예 없는 것이 있는가"(실행→계획) — 는
검사되지 않았다. 새 테이블을 만들며 사용자 데이터를 담는데 실수로
`_ERASURE_PLAN` 등재를 깜빡하면, 그 테이블은 삭제권 요청에도 영원히 안 지워지는데 아무 테스트도
잡지 못했다. 본 모듈이 그 역방향을 강제한다.

hermetic: `Base.metadata.tables`(SQLAlchemy 선언적 메타데이터)만 읽는다 — DB 연결 0
(`tests/backend/l1/test_edge_relation_governance.py` 순수 메타데이터 스윕 선례).

소유 판정 방식(SEC-35, 2026-09-18 전환): 종전 **고정 3종 컬럼명 열거**에서
**FK 산출물 검사 ∪ 계획 파생 이름**의 합집합으로 바꿨다 — 근거·실측·남는 사각은 아래
`_owner_tables` 위의 주석 블록이 정본이다.

실측(2026-09-18 SEC-35, 현행 82테이블 전수 · 판정 기준 main `a34d31d4`):
  (A) FK→`user_profile.user_id` 보유 = 18건 · (B) 계획 파생 이름 보유 = 26건 · 합집합 = 27건
  (A)에만 있고 (B)에 없던 것 = **`learner_state` 1건**(소유 컬럼 `learner_id` — 이 별칭이 종전
    3종 열거의 사각이었다). (B)에만 있고 (A)에 없는 것 = 9건(느슨참조·FK 0).
  → 합집합 27건 = `_ERASURE_PLAN` 24개 + `user_profile` + `deletion_audit`·`privacy_audit`
    (E형 감사 — `_ERASURE_PLAN_EXEMPTIONS`에 사유와 함께 등재) → **누락 0건**.

  전환 이전 상태(반증): 같은 스캔을 고정 3종 열거로 돌리면 누락 0건이 나왔다 — `learner_state`가
  스윕 대상에 **들어오지 않았기 때문**이지 계획에 있었기 때문이 아니다. 가드가 초록인데 테이블은
  파기 계획 밖이었고, 그 상태에서 삭제권 요청은 FK 위반으로 전면 실패했다(축 ② 통합 테스트).

허용목록(`_ERASURE_PLAN_EXEMPTIONS`)은 `privacy/erasure.py`에 사유와 함께 정의돼 있다 — 무사유
예외 금지(CLAUDE.md). 협업(다자 소유) 스키마가 만들 B·C·D형 테이블의 파기 규칙은
`docs/architecture/collaboration_landing_design.md` §2.2·§3(5분류·3배관 처리표·변호사 검토
대상)이 정본이다 — 이 테스트는 "분류·지정이 있어야 한다"는 *구조적 요건*만 기계로 강제한다.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy import Column, MetaData, Table, Uuid

from whymath_backend.privacy.erasure import _ERASURE_PLAN, _ERASURE_PLAN_EXEMPTIONS

# ===========================================================================
# 소유 테이블 판정 — **산출물 검사 ∪ 계획 파생 이름** (SEC-35, 2026-09-18)
#
# 종전 판은 `OWNER_COLUMN_NAMES = {"user_id","student_id","target_user_id"}` **고정 3종 열거**
# 하나였다. 그 형태는 CLAUDE.md 「금지 패턴 열거 대신 산출물 검사」가 겨냥하는 바로 그 구조이고,
# 실제로 뚫렸다 — `learner_state`는 소유 컬럼 이름이 `learner_id`라 전수 스윕에 **한 번도
# 걸리지 않았고**(실측: 82테이블 중 이름 스윕 26건에 미포함), 그 사이 그 테이블은 파기 계획
# 밖에 있었다. 더구나 그것은 조용한 누락이 아니라 **삭제 불능**이었다(FK NO ACTION → 삭제권
# 요청 자체가 ForeignKeyViolationError로 전체 롤백 · `test_erasure_learner_state_integration.py`).
#
# 그래서 판정을 두 축의 **합집합**으로 바꾼다. 어느 한쪽도 단독으로는 완전하지 않다(실측):
#   (A) **FK 기반 산출물 검사** — `user_profile.user_id`를 참조하는 FK를 가진 테이블 전건.
#       컬럼 *이름과 무관*하므로 `learner_id` 같은 별칭을 구조적으로 본다. 단독으로는 18건.
#   (B) **계획 파생 이름** — `_ERASURE_PLAN`이 *실제로 쓰는* 컬럼명 + 아래 EXTRA.
#       느슨참조(FK 0·hypertable) 테이블을 잡는다 — 그쪽은 FK가 없어 (A)가 구조적으로 못 본다.
#       실측 9건(ability_snapshot·attempt_event·concept_mastery_history·daily_learning_metrics·
#       skill_mastery_history·user_behavior_metrics·deletion_audit·privacy_audit·user_profile).
#   → (A)로 (B)를 *대체*하면 그 9건을 통째로 잃는다. 합집합이 fail-safe 방향이다.
#
# (B)를 **계획에서 파생**시키는 것이 종전과의 차이다: 새 테이블을 `_ERASURE_PLAN`에 다른 별칭
# (`learner_id` 등)으로 등재하는 순간 그 이름이 스윕 대상에 자동 편입되므로, 사람이 이 파일의
# 리터럴을 기억해야 하는 유지보수 지점이 사라진다(종전 구조는 그 기억에 의존해 실패했다).
#
# **남는 사각(정직 표기)**: FK가 없고(느슨참조) 이름도 계획에 없는 새 별칭(예: FK 0인
# `owner_uid` 컬럼)은 여전히 두 축 모두에 안 걸린다. 그런 테이블을 만들 때는 `_ERASURE_PLAN`
# 등재가 유일한 방어이며, 이 파일이 자동으로 잡아 주지 못한다 — "전수 방어"라고 쓰지 않는다.

# `_ERASURE_PLAN`이 쓰지 않지만 소유 표지인 컬럼명. `target_user_id`는 `privacy_audit`
# (다른 사용자의 데이터가 대상일 때의 소유 표지)에만 있고 그 테이블은 계획이 아니라 허용목록
# 소속이라 (B)의 계획 파생으로는 나오지 않는다. 실측상 이 컬럼을 *단독으로*(user_id 없이)
# 가진 테이블은 현재 0건이지만, 생기는 날을 대비해 남긴다.
#
# 여기에 이름을 더하는 것은 최후 수단이다 — 새 소유 축은 `_ERASURE_PLAN` 등재((B)가 자동
# 반영)나 FK((A)가 자동 반영)로 표현하는 쪽이 옳다.
OWNER_COLUMN_NAMES_EXTRA: frozenset[str] = frozenset({"target_user_id"})

# 소유 축의 정본 참조 — 이 FK를 가진 테이블은 컬럼명과 무관하게 "이 사용자의 데이터"다.
USER_OWNER_FK_TARGET = "user_profile.user_id"


def owner_column_names() -> frozenset[str]:
    """(B) 스윕이 볼 컬럼명 — `_ERASURE_PLAN`이 실제로 쓰는 이름 + EXTRA(파생·하드코딩 아님)."""
    return frozenset(column for _, column in _ERASURE_PLAN) | OWNER_COLUMN_NAMES_EXTRA


def _tables_with_owner_fk(metadata: MetaData) -> frozenset[str]:
    """(A) 산출물 검사 — `user_profile.user_id`를 참조하는 FK 보유 테이블(컬럼명 무관)."""
    return frozenset(
        name
        for name, table in metadata.tables.items()
        if any(fk.target_fullname == USER_OWNER_FK_TARGET for fk in table.foreign_keys)
    )


def _tables_with_owner_column_name(metadata: MetaData) -> frozenset[str]:
    """(B) 이름 기반 — 계획 파생 컬럼명을 가진 테이블(느슨참조·FK 0 축)."""
    names = owner_column_names()
    return frozenset(
        name for name, table in metadata.tables.items() if {c.name for c in table.columns} & names
    )


def _owner_tables(metadata: MetaData) -> frozenset[str]:
    """소유 테이블 전건 = (A) FK 산출물 ∪ (B) 계획 파생 이름. 어느 한쪽도 단독 완전 아님."""
    return _tables_with_owner_fk(metadata) | _tables_with_owner_column_name(metadata)


def _missing_from_plan(
    metadata: MetaData,
    *,
    planned: frozenset[str],
    exemptions: dict[str, str],
) -> frozenset[str]:
    """소유 테이블 중 계획(`planned`)·허용목록(`exemptions`) 둘 다에 없는 것(실행→계획)."""
    return _owner_tables(metadata) - planned - frozenset(exemptions)


# ===========================================================================
# 실측 — 현행 62테이블 실제 검사(red면 이 태스크에서 상환 필요)
# ===========================================================================


def test_no_owner_column_table_missing_from_erasure_plan() -> None:
    """실행→계획 방향 — `_ERASURE_PLAN`·허용목록 밖의 소유 컬럼 보유 테이블 검출(0건이어야 함).

    `user_profile`은 `_ERASURE_PLAN` 튜플엔 없지만 `erase_user()`가 자식 삭제 후 마지막에 명시
    삭제하므로(erasure.py 삭제 순서 주석) 별도로 "계획됨"에 합류시킨다 — 미계획 누락이 아니다.
    """
    import whymath_backend.db.models  # noqa: F401  # 62테이블 전부 Base.metadata에 등록(실측 필수)
    from whymath_backend.db.base import Base

    planned = frozenset({m.__tablename__ for m, _ in _ERASURE_PLAN}) | {"user_profile"}
    missing = _missing_from_plan(
        Base.metadata, planned=planned, exemptions=_ERASURE_PLAN_EXEMPTIONS
    )

    assert missing == frozenset(), (
        f"소유 축(user_profile.user_id FK 또는 계획 파생 컬럼명)을 가졌으나 _ERASURE_PLAN에도 "
        f"_ERASURE_PLAN_EXEMPTIONS에도 없는 테이블: {sorted(missing)} — "
        "삭제권 요청에도 영원히 지워지지 않는 테이블이다. _ERASURE_PLAN에 추가하거나, "
        "정당한 사유와 함께 _ERASURE_PLAN_EXEMPTIONS에 등재하라(무사유 예외 금지)."
    )


def test_exemptions_have_nonempty_reasons() -> None:
    """허용목록의 모든 예외는 사유가 비어 있지 않다 — 무사유 예외 금지(CLAUDE.md 하드 게이트)."""
    assert _ERASURE_PLAN_EXEMPTIONS, "허용목록이 비어 있으면 안 된다(감사 테이블 최소 2종 존재)."
    for table_name, reason in _ERASURE_PLAN_EXEMPTIONS.items():
        assert reason.strip(), f"{table_name}의 예외 사유가 비어 있다(무사유 예외 금지)."
        assert (
            len(reason.strip()) >= 20
        ), f"{table_name}의 예외 사유가 지나치게 짧다(형식적 사유 의심)."


def test_exemptions_are_subset_of_actual_owner_tables() -> None:
    """허용목록에 등재된 테이블은 실제로 소유 컬럼을 가진 실존 테이블이어야 한다(유령 예외 방지)."""
    import whymath_backend.db.models  # noqa: F401
    from whymath_backend.db.base import Base

    owner_tables = frozenset(_owner_tables(Base.metadata))
    planned = frozenset({m.__tablename__ for m, _ in _ERASURE_PLAN})
    for table_name in _ERASURE_PLAN_EXEMPTIONS:
        if table_name == "user_profile":
            # user_profile은 user_id가 PK(소유 컬럼과 동일 이름) — 실제 테이블로 존재 확인.
            assert table_name in Base.metadata.tables, "user_profile 테이블이 존재하지 않는다."
            continue
        assert table_name in owner_tables, f"{table_name}은 소유 컬럼이 없는데 예외로 등재돼 있다."
        assert table_name not in planned, f"{table_name}은 이미 _ERASURE_PLAN에 있다(중복 예외)."


# ===========================================================================
# 변별력 (④) — 합성 MetaData로 리크 테이블을 주입→red, 제거→green을 같은 세션에서 실측.
#
# 실 Base.metadata를 오염시키지 않기 위해(선언적 베이스는 프로세스 전역 싱글턴 — 여기서 서브클래싱
# 하면 이후 alembic·다른 테스트가 보는 메타데이터가 영구 오염된다) 독립 MetaData로 "소유 컬럼을
# 가진 테이블 중 계획 밖의 것"을 합성 구성해 `_missing_from_plan` 자체의 변별력을 증명한다. 실
# Base.metadata에 대한 실제 red/green 재현은 세션 보고에 별도 스크립트 실행 기록으로 남긴다
# ("실패 상태에서 실제로 실패 신호를 내는지 확인된 검사만 동봉" — CLAUDE.md).
# ===========================================================================


def test_sweep_flags_injected_leak_table_then_clears_after_removal() -> None:
    """더미 user_id 테이블 주입 → red 실측 → 제거 → green 실측(양방향 변별력 증명)."""
    planned = frozenset({"planned_tbl"})

    # ── 주입 상태: 계획에 없는 leaked_tbl이 user_id를 가짐 → red ──
    meta_with_leak = MetaData()
    Table(
        "planned_tbl",
        meta_with_leak,
        Column("id", Uuid, primary_key=True, default=uuid.uuid4),
        Column("user_id", Uuid),
    )
    Table(
        "leaked_tbl",  # ← 방금 만들었는데 _ERASURE_PLAN 등재를 깜빡한 신설 테이블 시뮬레이션
        meta_with_leak,
        Column("id", Uuid, primary_key=True, default=uuid.uuid4),
        Column("user_id", Uuid),
        Column("payload", sa.Text),
    )
    missing_with_leak = _missing_from_plan(meta_with_leak, planned=planned, exemptions={})
    assert missing_with_leak == frozenset(
        {"leaked_tbl"}
    ), "리크 테이블 주입 상태에서 red가 나지 않았다 — 검사에 변별력이 없다(위장 검증)."

    # ── 제거 상태: leaked_tbl 없이 동일 스윕 → green ──
    meta_clean = MetaData()
    Table(
        "planned_tbl",
        meta_clean,
        Column("id", Uuid, primary_key=True, default=uuid.uuid4),
        Column("user_id", Uuid),
    )
    missing_clean = _missing_from_plan(meta_clean, planned=planned, exemptions={})
    assert missing_clean == frozenset(), "리크 테이블 제거 후에도 red가 남았다 — 검사 로직 결함."


def test_sweep_respects_exemptions() -> None:
    """허용목록에 등재된 테이블은 소유 컬럼이 있어도 red를 내지 않는다(사유 명시 예외 경로 검증)."""
    meta = MetaData()
    Table(
        "audit_tbl",
        meta,
        Column("id", Uuid, primary_key=True, default=uuid.uuid4),
        Column("user_id", Uuid),
    )
    missing_without_exemption = _missing_from_plan(meta, planned=frozenset(), exemptions={})
    assert missing_without_exemption == frozenset({"audit_tbl"})  # 예외 미등재 시 red(대조군)

    missing_with_exemption = _missing_from_plan(
        meta, planned=frozenset(), exemptions={"audit_tbl": "감사 로그 — 계정 삭제 후에도 잔존."}
    )
    assert missing_with_exemption == frozenset()  # 사유 명시 예외 등재 시 green


# ===========================================================================
# SEC-35 축 ④ — 합집합 스윕의 **실패 주입** 변별력.
#
# CLAUDE.md 「보호 장치를 실패 주입 없이 "보호 있음"으로 선언 금지」 + 「픽스처가 그 절을 실제로
# 밟는가」. 아래 각 테스트는 *합집합의 한 축을 지우면 통과해 버리는* 입력을 픽스처로 쓴다 —
# 그 절의 반례를 고른 것이지 추상적 경계 케이스가 아니다:
#   · (A) FK 축의 반례 = 계획에 없는 **별칭 컬럼 + FK**  → (B)만 남기면 GREEN이 된다
#   · (B) 이름 축의 반례 = 계획 컬럼명 + **FK 0**(느슨참조) → (A)만 남기면 GREEN이 된다
# 한 축만 검증하는 픽스처를 쓰면 다른 축이 뮤테이션에서 살아남는다(2026-09-07 MISC-07 선례).
# ===========================================================================


def _synthetic_user_profile(metadata: MetaData) -> Table:
    """FK 대상이 되는 합성 `user_profile` — 실 Base.metadata를 오염시키지 않는다."""
    return Table(
        "user_profile",
        metadata,
        Column("user_id", Uuid, primary_key=True, default=uuid.uuid4),
    )


def test_fk_axis_catches_alias_owner_column_that_name_axis_misses() -> None:
    """(A) 반례 — 계획 밖 별칭 컬럼 + FK. 이름 축만으론 못 보는 것을 FK 축이 잡는다.

    별칭으로 `learner_id`를 쓰면 안 된다 — SEC-35가 그것을 `_ERASURE_PLAN`에 등재한 순간
    계획 파생 이름에 편입돼(B) 이 픽스처가 FK 축을 **한 번도 밟지 않게** 된다. 아래 대조군
    단언이 그 상태를 실제로 잡았다(초안이 `learner_id`였고 red로 발각됐다).
    """
    meta = MetaData()
    _synthetic_user_profile(meta)
    Table(
        "aliased_owner_tbl",
        meta,
        # 계획 파생 이름 어디에도 없는 별칭 — (B)는 이 테이블을 구조적으로 못 본다.
        Column("pupil_uid", Uuid, sa.ForeignKey("user_profile.user_id"), primary_key=True),
    )
    assert "pupil_uid" not in owner_column_names(), "픽스처 별칭이 계획에 편입됐다 — 다른 이름으로."

    # 대조군 — 이름 축 단독이면 이 테이블이 안 보인다(= 종전 가드의 실패 재현).
    assert "aliased_owner_tbl" not in _tables_with_owner_column_name(meta), (
        "픽스처가 이름 축에 걸려 버렸다 — 이 컬럼명이 계획 파생 이름에 들어갔다는 뜻이고, "
        "그러면 이 테스트는 FK 축을 한 번도 밟지 않는다(변별력 0)."
    )
    # 본 검사 — FK 축이 잡는다.
    assert "aliased_owner_tbl" in _tables_with_owner_fk(meta)
    missing = _missing_from_plan(meta, planned=frozenset({"user_profile"}), exemptions={})
    assert missing == frozenset({"aliased_owner_tbl"}), "FK 축 주입에서 red가 나지 않았다."


def test_name_axis_catches_loose_reference_that_fk_axis_misses() -> None:
    """(B) 반례 — 계획 컬럼명 + FK 0(느슨참조·hypertable 형태). FK 축만으론 못 본다."""
    meta = MetaData()
    _synthetic_user_profile(meta)
    Table(
        "loose_metrics_tbl",
        meta,
        Column("id", Uuid, primary_key=True, default=uuid.uuid4),
        Column("user_id", Uuid),  # FK 없음 — (A)는 이 테이블을 구조적으로 못 본다.
    )

    # 대조군 — FK 축 단독이면 안 보인다.
    assert "loose_metrics_tbl" not in _tables_with_owner_fk(
        meta
    ), "픽스처에 FK가 생겼다 — 그러면 이 테스트는 이름 축을 한 번도 밟지 않는다(변별력 0)."
    assert "loose_metrics_tbl" in _tables_with_owner_column_name(meta)
    missing = _missing_from_plan(meta, planned=frozenset({"user_profile"}), exemptions={})
    assert missing == frozenset({"loose_metrics_tbl"}), "이름 축 주입에서 red가 나지 않았다."


def test_owner_column_names_are_derived_from_plan_not_hardcoded() -> None:
    """(B)의 이름 집합은 `_ERASURE_PLAN`에서 *파생*된다 — 계획에 별칭을 등재하면 자동 편입.

    종전 구조는 이 파일의 리터럴을 사람이 기억해 갱신해야 했고, 그 기억이 실패한 결과가 SEC-35다.
    """
    names = owner_column_names()
    plan_columns = {column for _, column in _ERASURE_PLAN}
    assert plan_columns <= names, "계획이 쓰는 컬럼명이 스윕 대상에서 빠졌다."
    # SEC-35가 편입한 별칭이 파생으로 따라왔는지 — 하드코딩이면 이 단언이 의미를 잃는다.
    assert "learner_id" in names, (
        "learner_id가 스윕 이름 집합에 없다 — _ERASURE_PLAN 파생이 끊겼거나 "
        "learner_state 등재가 사라졌다."
    )
    assert OWNER_COLUMN_NAMES_EXTRA <= names


def test_learner_state_is_covered_and_was_invisible_to_legacy_name_enumeration() -> None:
    """실 메타데이터 회귀 핀 — `learner_state`가 계획에 있고, 종전 3종 열거로는 안 보였다.

    두 단언이 함께 있어야 의미가 있다: 앞은 *지금 지워지는가*, 뒤는 *왜 종전 가드가 초록이었는가*.
    뒤 단언이 깨지면(= learner_id 외 3종 중 하나가 생기면) 이 사각의 서술이 낡은 것이므로
    위 주석 블록과 함께 갱신하라.
    """
    import whymath_backend.db.models  # noqa: F401
    from whymath_backend.db.base import Base

    planned = {model.__tablename__ for model, _ in _ERASURE_PLAN}
    assert "learner_state" in planned, "learner_state가 _ERASURE_PLAN에서 빠졌다(파기 누락 재발)."

    table = Base.metadata.tables["learner_state"]
    legacy_names = frozenset({"user_id", "student_id", "target_user_id"})
    assert not (
        {c.name for c in table.columns} & legacy_names
    ), "learner_state가 종전 3종 열거에 걸리는 컬럼을 갖게 됐다 — 사각 서술이 낡았다."
    # FK 축이 이 테이블을 보는 것이 이번 전환의 집행 지점이다.
    assert "learner_state" in _tables_with_owner_fk(Base.metadata)
