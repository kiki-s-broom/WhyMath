"""COLLAB-02 — 파기 계획 완전성 검사의 *방향 역전*(실행→계획, 소유 테이블 중 계획 누락 검출).

`test_erasure.py:94 test_covers_all_planned_tables`는 "`_ERASURE_PLAN`에 있는 테이블은 전부 실제
삭제 순서(`_delete_order`)에 등장하는가"(계획→실행, `planned <= order`)만 단언한다. 그 역방향 —
"소유 컬럼을 가진 테이블인데 `_ERASURE_PLAN`에 아예 없는 것이 있는가"(실행→계획) — 는
검사되지 않았다. 새 테이블을 만들며 사용자 데이터를 담는데 실수로
`_ERASURE_PLAN` 등재를 깜빡하면, 그 테이블은 삭제권 요청에도 영원히 안 지워지는데 아무 테스트도
잡지 못했다. 본 모듈이 그 역방향을 강제한다.

hermetic: `Base.metadata.tables`(SQLAlchemy 선언적 메타데이터)만 읽는다 — DB 연결 0
(`tests/backend/l1/test_edge_relation_governance.py` 순수 메타데이터 스윕 선례). 예외: 임시 예외의
만료 장치(SEC-39)는 `backlog/tasks/*.yaml`의 `status`를 읽는다 — 백로그가 태스크 상태의 단일 진실
원천이라 새 대장을 만들지 않는다(`ops/provenance_audit.py` ARCH-25 그랜드파더 만료 계약 선례).

소유 판정 방식: **(A) FK 산출물 검사 ∪ (B) 계획 파생 이름 ∪ (C) 학생 세션 축**의 합집합이다.
(A)·(B)는 SEC-35(2026-09-18)가 종전 고정 3종 컬럼명 열거를 대체하며 만들었고, (C)는 SEC-39
(2026-09-30)가 더했다 — 근거·실측·남는 사각은 아래 `_owner_tables` 위의 주석 블록이 정본이다.

실측(2026-09-18 SEC-35, 현행 82테이블 전수 · 판정 기준 main `a34d31d4`):
  (A) FK→`user_profile.user_id` 보유 = 18건 · (B) 계획 파생 이름 보유 = 26건 · 합집합 = 27건
  (A)에만 있고 (B)에 없던 것 = **`learner_state` 1건**(소유 컬럼 `learner_id` — 이 별칭이 종전
    3종 열거의 사각이었다). (B)에만 있고 (A)에 없는 것 = 9건(느슨참조·FK 0).
  → 합집합 27건 = `_ERASURE_PLAN` 24개 + `user_profile` + `deletion_audit`·`privacy_audit`
    (E형 감사 — `_ERASURE_PLAN_EXEMPTIONS`에 사유와 함께 등재) → **누락 0건**.

  전환 이전 상태(반증): 같은 스캔을 고정 3종 열거로 돌리면 누락 0건이 나왔다 — `learner_state`가
  스윕 대상에 **들어오지 않았기 때문**이지 계획에 있었기 때문이 아니다. 가드가 초록인데 테이블은
  파기 계획 밖이었고, 그 상태에서 삭제권 요청은 FK 위반으로 전면 실패했다(축 ② 통합 테스트).

실측(2026-09-30 SEC-39, 현행 83테이블 전수 · 판정 기준 main `6d891518`):
  (A) = 18건 · (B) = 27건(SEC-35가 `learner_id`를 계획에 등재해 `learner_state`가 (B)에도 편입)
  · (A)∪(B) = 27건. (C) 학생 세션 축 = 3건(`evidence_event`·`evidence_links`·`problem_attempt`)
  이고, 그중 (A)∪(B) 밖은 **`evidence_event` 1건**이다 — user 컬럼도 user FK도 없이
  `session_id`(느슨참조)로만 학생에 묶인다. (C) 도입 직후 스윕이 이 테이블을 RED로 잡는 것을
  실측했고(누락 1건), 처분(삭제 배선)은 SEC-40이 소유하므로 이 태스크는
  `_ERASURE_PLAN_EXEMPTIONS`에 **만료 있는 임시 예외**로 등재했다 → 누락 0건.

  보강 이전 상태(반증): (A)∪(B)만으로 돌리면 누락 0건이었다 — `evidence_event`가 스윕 대상에
  **들어오지 않았기 때문**이다. 한편 `privacy/export.py`는 `learning_session` 조인으로 이 행을
  학생 데이터로 반출한다(EOS-131 ⑤) — 열람권엔 있고 삭제권엔 없는 비대칭이 가드에 안 보였다.
  SEC-35(`learner_id` 별칭)와 같은 계열의 다른 형태다: 둘 다 "소유 축의 *이름*이 가드의 상상 밖".

허용목록(`_ERASURE_PLAN_EXEMPTIONS`)은 `privacy/erasure.py`에 사유와 함께 정의돼 있다 — 무사유
예외 금지(CLAUDE.md). 임시 예외는 `_ERASURE_PLAN_EXEMPTION_EXPIRY`에 해소 태스크를 함께 등재해야
하고, 그 태스크가 종결(done·cancelled)됐는데 항목이 남아 있으면 이 모듈이 RED를 낸다(CLAUDE.md
「만료 없는 유예·제외 금지」). 협업(다자 소유) 스키마가 만들 B·C·D형 테이블의 파기 규칙은
`docs/architecture/collaboration_landing_design.md` §2.2·§3(5분류·3배관 처리표·변호사 검토
대상)이 정본이다 — 이 테스트는 "분류·지정이 있어야 한다"는 *구조적 요건*만 기계로 강제한다.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
import yaml
from sqlalchemy import Column, MetaData, Table, Uuid

from whymath_backend.privacy.erasure import (
    _ERASURE_PLAN,
    _ERASURE_PLAN_EXEMPTION_EXPIRY,
    _ERASURE_PLAN_EXEMPTIONS,
    _SESSION_AXIS_MODELS,
)

# ===========================================================================
# 소유 테이블 판정 — **(A) 산출물 검사 ∪ (B) 계획 파생 이름 ∪ (C) 학생 세션 축**
#
# 종전 판은 `OWNER_COLUMN_NAMES = {"user_id","student_id","target_user_id"}` **고정 3종 열거**
# 하나였다. 그 형태는 CLAUDE.md 「금지 패턴 열거 대신 산출물 검사」가 겨냥하는 바로 그 구조이고,
# 실제로 뚫렸다 — `learner_state`는 소유 컬럼 이름이 `learner_id`라 전수 스윕에 **한 번도
# 걸리지 않았고**(실측: 82테이블 중 이름 스윕 26건에 미포함), 그 사이 그 테이블은 파기 계획
# 밖에 있었다. 더구나 그것은 조용한 누락이 아니라 **삭제 불능**이었다(FK NO ACTION → 삭제권
# 요청 자체가 ForeignKeyViolationError로 전체 롤백 · `test_erasure_learner_state_integration.py`).
#
# 그래서 판정을 여러 축의 **합집합**으로 바꾼다. 어느 한쪽도 단독으로는 완전하지 않다(실측):
#   (A) **FK 기반 산출물 검사** — `user_profile.user_id`를 참조하는 FK를 가진 테이블 전건.
#       컬럼 *이름과 무관*하므로 `learner_id` 같은 별칭을 구조적으로 본다. 단독으로는 18건.
#   (B) **계획 파생 이름** — `_ERASURE_PLAN`이 *실제로 쓰는* 컬럼명 + 아래 EXTRA.
#       느슨참조(FK 0·hypertable) 테이블을 잡는다 — 그쪽은 FK가 없어 (A)가 구조적으로 못 본다.
#       실측 9건(ability_snapshot·attempt_event·concept_mastery_history·daily_learning_metrics·
#       skill_mastery_history·user_behavior_metrics·deletion_audit·privacy_audit·user_profile).
#   (C) **학생 세션 축**(SEC-39) — 학생 학습 세션(`learning_session.session_id`)을 가리키는
#       컬럼을 가진 테이블. user 축이 *전혀 없이* 세션으로만 학생에 묶이는 테이블을 잡는다 —
#       (A)·(B)는 둘 다 *user* 축만 보므로 구조적으로 못 본다. 실측 3건 중 (A)∪(B) 밖 1건
#       (`evidence_event`). 판정 기준은 아래 「(C) 포함·제외 기준」 블록이 정본이다.
#   → 어느 축으로 다른 축을 *대체*하면 그 축만 보던 테이블을 통째로 잃는다. 합집합이 fail-safe다.
#
# (B)를 **계획에서 파생**시키는 것이 종전과의 차이다: 새 테이블을 `_ERASURE_PLAN`에 다른 별칭
# (`learner_id` 등)으로 등재하는 순간 그 이름이 스윕 대상에 자동 편입되므로, 사람이 이 파일의
# 리터럴을 기억해야 하는 유지보수 지점이 사라진다(종전 구조는 그 기억에 의존해 실패했다).
#
# **남는 사각(정직 표기 — SEC-39 갱신)**: 아래는 세 축 어디에도 안 걸린다. 그런 테이블을 만들
# 때는 `_ERASURE_PLAN` 등재가 유일한 방어이며, 이 파일이 자동으로 잡아 주지 못한다 — "전수
# 방어"라고 쓰지 않는다.
#   ① FK가 없고(느슨참조) 이름도 계획에 없는 **user 축 새 별칭**(예: FK 0인 `owner_uid`).
#   ② FK가 없고 이름이 `session_id`/`*_session_id` 형태도 아닌 **세션 축 새 별칭**
#      (예: FK 0인 `sitting_uuid`). FK를 걸면 (C)의 FK 절이 이름과 무관하게 잡는다.
#   ③ **세션 외 다른 소유 테이블을 경유한 전이 소유** — 예: `problem_attempt.attempt_id`나
#      `dialogue.dialogue_id`만 느슨참조로 들고 user·세션 축이 없는 테이블. 실측(2026-09-30):
#      비소유 테이블 중 소유 테이블을 가리키는 FK를 가진 것은 `dialogue_turn` 1건뿐이며 그것은
#      `dialogue` 삭제의 DB CASCADE로 지워진다(erasure.py 삭제 순서 주석). 느슨참조 형태는
#      소유 테이블 PK 이름과 같은 컬럼을 전수 대조해 `evidence_event.session_id`(= 이번 (C)
#      대상) 외에 `curriculum_entry.concept_id` 1건이 나왔으나 개념 키라 학생 축이 아니다.
#      이 축을 일반화하는 전이 폐포 스윕은 이 태스크 범위 밖이다.

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

# ---------------------------------------------------------------------------
# (C) 포함·제외 기준 (SEC-39)
#
# **앵커** = `learning_session.session_id`(학생 학습 세션의 PK). 이 테이블 자신은 (C)에 넣지
# 않는다 — 앵커는 *가리켜지는 쪽*이지 가리키는 쪽이 아니며, 그 소유는 `user_id`(→ user_profile
# FK)로 (A)·(B)가 이미 판정한다. 대신 "앵커 자신이 (A)∪(B)로 소유 판정되고 `_ERASURE_PLAN`에
# 있다"를 별도 테스트로 강제한다 — 앵커가 소유 축을 잃으면 (C) 전체가 의미를 잃기 때문이다.
#
# **포함** — 다음 두 절 중 하나라도 해당하는 컬럼을 가진 테이블(앵커 테이블 제외):
#   (C-FK)  앵커를 참조하는 FK — **구조로** 판정, 컬럼명 무관. 제외 목록으로도 끌 수 없다
#           (FK가 학생 세션을 가리킨다는 것은 해석이 아니라 스키마 사실이다).
#   (C-이름) 이름이 `session_id`이거나 `_session_id`로 끝나는 컬럼 — 하이퍼테이블 느슨참조처럼
#           FK를 걸 수 없는 축을 잡는다. **오탐 방향(fail-safe)**을 택했다: 학생 세션이 아닌
#           `*_session_id`가 새로 생기면 이 가드가 RED를 내고, 개발자가 아래
#           `NON_STUDENT_SESSION_COLUMNS`에 **사유와 함께** 올려야 초록이 된다. 조용히 통과하는
#           반대 방향(이름을 좁게 잡아 미탐)보다 낫다 — 미탐의 비용은 삭제권 누락이고 오탐의
#           비용은 사유 한 줄이다. 접미 `_session_id`까지 넓힌 것은 `learning_session_id` 같은
#           별칭 느슨참조를 잡기 위해서다(SEC-35는 정확히 별칭에서 뚫렸다).
# **제외** — `NON_STUDENT_SESSION_COLUMNS`에 사유와 함께 등재된 (테이블, 컬럼)만. 이름 절에만
#   적용되며, 실존·이름 절 해당·FK 아님을 테스트가 강제한다(유령 제외·구조 덮어쓰기 금지).
#
# 이 목록은 `_ERASURE_PLAN_EXEMPTIONS`와 의미가 다르다: 저쪽은 "학생 소유이지만 삭제하지 않는
# 정당한 이유"(법적 판단)이고, 이쪽은 "애초에 학생 세션을 가리키는 컬럼이 아니다"(분류)다.
STUDENT_SESSION_ANCHOR = "learning_session.session_id"
_STUDENT_SESSION_ANCHOR_TABLE = STUDENT_SESSION_ANCHOR.split(".", maxsplit=1)[0]

NON_STUDENT_SESSION_COLUMNS: dict[tuple[str, str], str] = {
    ("review_timer_event", "review_session_id"): (
        "검수자 세션(sitting) 페어링 축 — HIT 검수 타이머의 writer가 발급하는 상관 id이며 학생 "
        "학습 세션이 아니다(`db/models/review_timer_event.py` docstring: 세션 정본 테이블 없음·FK "
        "날조 금지). 행위자는 검수자(`reviewer_id`)라 학생 소유 축 자체가 없다 — "
        "`tests/backend/db/test_review_timer_event_orm.py::TestNoStudentAxis`가 동결한다."
    ),
    ("refresh_token_session", "token_session_id"): (
        "인증 토큰 세션의 PK(리프레시 토큰 jti) — 로그인 세션이지 학습 세션이 아니다. 테이블 "
        "자체는 `user_id`(→ user_profile FK)로 (A) 소유이고 `_ERASURE_PLAN`에 등재돼 있어, 이 "
        "제외는 삭제 여부가 아니라 (C) 분류만 바로잡는다."
    ),
}


def owner_column_names() -> frozenset[str]:
    """(B) 스윕이 볼 컬럼명 — `_ERASURE_PLAN`이 쓰는 **user 축** 이름 + EXTRA(파생·하드코딩 아님).

    SEC-40: 세션 축 계획 항목(`_SESSION_AXIS_MODELS` — `evidence_event.session_id`)은 뺀다. (B)는
    *user* 축 스윕이고 세션 축은 (C)가 맡는다 — 세션 컬럼명이 (B)로 새어 들어오면 `session_id`를
    가진 모든 테이블이 (B)로도 걸려, (C)를 지워도 가드가 초록인 상태(= (C)가 하는 일이 사라진
    상태)가 된다. SEC-39의 사각 핀(`test_evidence_event_is_caught_only_by_student_session_axis`·
    `test_session_name_clause_catches_loose_reference_that_user_axes_miss`)이 이 분리를 동결한다.
    """
    return (
        frozenset(column for model, column in _ERASURE_PLAN if model not in _SESSION_AXIS_MODELS)
        | OWNER_COLUMN_NAMES_EXTRA
    )


def is_session_reference_name(name: str) -> bool:
    """(C-이름) 절 — `session_id` 또는 `*_session_id`(접미 일치·fail-safe 방향)."""
    return name == "session_id" or name.endswith("_session_id")


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


def _tables_with_student_session_fk(metadata: MetaData) -> frozenset[str]:
    """(C-FK) — 앵커(`learning_session.session_id`)를 참조하는 FK 보유 테이블(앵커 자신 제외)."""
    return frozenset(
        name
        for name, table in metadata.tables.items()
        if name != _STUDENT_SESSION_ANCHOR_TABLE
        and any(fk.target_fullname == STUDENT_SESSION_ANCHOR for fk in table.foreign_keys)
    )


def _tables_with_session_reference_name(
    metadata: MetaData,
    *,
    exclusions: dict[tuple[str, str], str],
) -> frozenset[str]:
    """(C-이름) — 세션 참조 이름 컬럼 보유 테이블(앵커 자신·사유 명시 제외 컬럼 빼고)."""
    return frozenset(
        name
        for name, table in metadata.tables.items()
        if name != _STUDENT_SESSION_ANCHOR_TABLE
        and any(
            is_session_reference_name(column.name) and (name, column.name) not in exclusions
            for column in table.columns
        )
    )


def _tables_on_student_session_axis(
    metadata: MetaData,
    *,
    exclusions: dict[tuple[str, str], str] = NON_STUDENT_SESSION_COLUMNS,
) -> frozenset[str]:
    """(C) 학생 세션 축 = (C-FK) ∪ (C-이름). 제외 목록은 이름 절에만 적용된다."""
    return _tables_with_student_session_fk(metadata) | _tables_with_session_reference_name(
        metadata, exclusions=exclusions
    )


def _owner_tables(
    metadata: MetaData,
    *,
    session_exclusions: dict[tuple[str, str], str] = NON_STUDENT_SESSION_COLUMNS,
) -> frozenset[str]:
    """소유 테이블 전건 = (A) ∪ (B) ∪ (C). 어느 한쪽도 단독 완전 아님."""
    return (
        _tables_with_owner_fk(metadata)
        | _tables_with_owner_column_name(metadata)
        | _tables_on_student_session_axis(metadata, exclusions=session_exclusions)
    )


def _missing_from_plan(
    metadata: MetaData,
    *,
    planned: frozenset[str],
    exemptions: dict[str, str],
    session_exclusions: dict[tuple[str, str], str] = NON_STUDENT_SESSION_COLUMNS,
) -> frozenset[str]:
    """소유 테이블 중 계획(`planned`)·허용목록(`exemptions`) 둘 다에 없는 것(실행→계획)."""
    owners = _owner_tables(metadata, session_exclusions=session_exclusions)
    return owners - planned - frozenset(exemptions)


def _real_metadata() -> MetaData:
    """실 `Base.metadata` — 모델 패키지 import로 전 테이블을 등록한 뒤 반환한다."""
    import whymath_backend.db.models  # noqa: F401  # 전 테이블 Base.metadata 등록(실측 필수)
    from whymath_backend.db.base import Base

    return Base.metadata


def _planned_tables() -> frozenset[str]:
    """`_ERASURE_PLAN` 테이블 + `erase_user()`가 마지막에 명시 삭제하는 `user_profile`."""
    return frozenset({m.__tablename__ for m, _ in _ERASURE_PLAN}) | {"user_profile"}


# ===========================================================================
# 실측 — 현행 83테이블 실제 검사(red면 이 태스크에서 상환 필요)
# ===========================================================================


def test_no_owner_column_table_missing_from_erasure_plan() -> None:
    """실행→계획 방향 — `_ERASURE_PLAN`·허용목록 밖의 소유 테이블 검출(0건이어야 함).

    `user_profile`은 `_ERASURE_PLAN` 튜플엔 없지만 `erase_user()`가 자식 삭제 후 마지막에 명시
    삭제하므로(erasure.py 삭제 순서 주석) 별도로 "계획됨"에 합류시킨다 — 미계획 누락이 아니다.
    """
    missing = _missing_from_plan(
        _real_metadata(), planned=_planned_tables(), exemptions=_ERASURE_PLAN_EXEMPTIONS
    )

    assert missing == frozenset(), (
        f"소유 축((A) user_profile.user_id FK · (B) 계획 파생 컬럼명 · (C) 학생 세션 축)을 "
        f"가졌으나 _ERASURE_PLAN에도 _ERASURE_PLAN_EXEMPTIONS에도 없는 테이블: {sorted(missing)} — "
        "삭제권 요청에도 영원히 지워지지 않는 테이블이다. _ERASURE_PLAN에 추가하거나, "
        "정당한 사유와 함께 _ERASURE_PLAN_EXEMPTIONS에 등재하라(무사유 예외 금지 · 임시면 "
        "_ERASURE_PLAN_EXEMPTION_EXPIRY에 해소 태스크도). (C)에 걸린 컬럼이 학생 학습 세션을 "
        "가리키지 않는다면 NON_STUDENT_SESSION_COLUMNS에 사유와 함께 올려라."
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
    metadata = _real_metadata()
    owner_tables = frozenset(_owner_tables(metadata))
    planned = frozenset({m.__tablename__ for m, _ in _ERASURE_PLAN})
    for table_name in _ERASURE_PLAN_EXEMPTIONS:
        if table_name == "user_profile":
            # user_profile은 user_id가 PK(소유 컬럼과 동일 이름) — 실제 테이블로 존재 확인.
            assert table_name in metadata.tables, "user_profile 테이블이 존재하지 않는다."
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
    plan_columns = {column for model, column in _ERASURE_PLAN if model not in _SESSION_AXIS_MODELS}
    assert plan_columns <= names, "계획이 쓰는 컬럼명이 스윕 대상에서 빠졌다."
    # SEC-40: 세션 축 계획 항목(evidence_event.session_id)은 (B)에 *들어오지 않는다* — (B)는 user
    # 축 스윕이고 세션 축은 (C)의 몫이다. 새어 들어오면 (C)를 지워도 가드가 초록이 된다.
    session_axis_columns = {
        column for model, column in _ERASURE_PLAN if model in _SESSION_AXIS_MODELS
    }
    assert session_axis_columns, "세션 축 계획 항목이 0건이다 — 이 분리 단언이 공허해졌다."
    assert not (session_axis_columns - plan_columns) & names, "세션 축 컬럼명이 (B)로 새어 들었다."
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
    metadata = _real_metadata()

    planned = {model.__tablename__ for model, _ in _ERASURE_PLAN}
    assert "learner_state" in planned, "learner_state가 _ERASURE_PLAN에서 빠졌다(파기 누락 재발)."

    table = metadata.tables["learner_state"]
    legacy_names = frozenset({"user_id", "student_id", "target_user_id"})
    assert not (
        {c.name for c in table.columns} & legacy_names
    ), "learner_state가 종전 3종 열거에 걸리는 컬럼을 갖게 됐다 — 사각 서술이 낡았다."
    # FK 축이 이 테이블을 보는 것이 이번 전환의 집행 지점이다.
    assert "learner_state" in _tables_with_owner_fk(metadata)


# ===========================================================================
# SEC-39 — (C) 학생 세션 축: 실 메타데이터 핀
# ===========================================================================


def test_student_session_anchor_exists_and_is_owned_by_user_axis() -> None:
    """앵커 `learning_session.session_id`가 실재하는 PK이고, 앵커 테이블은 user 축으로 소유된다.

    (C)는 "앵커를 가리키면 학생 데이터"라는 추론이다. 그 추론은 앵커 자신이 학생 소유이고
    삭제 계획에 있을 때만 성립한다 — 이 전제가 깨지면 (C)는 헛것을 지킨다(유령 앵커 방지).
    앵커 테이블은 (C)에 넣지 않는다(가리켜지는 쪽 — 모듈 상단 「(C) 포함·제외 기준」).
    """
    metadata = _real_metadata()
    assert _STUDENT_SESSION_ANCHOR_TABLE in metadata.tables, "앵커 테이블이 없다(유령 앵커)."
    anchor_table = metadata.tables[_STUDENT_SESSION_ANCHOR_TABLE]
    anchor_column = STUDENT_SESSION_ANCHOR.split(".", maxsplit=1)[1]
    assert anchor_column in anchor_table.columns, "앵커 컬럼이 없다(유령 앵커)."
    assert anchor_table.columns[anchor_column].primary_key, "앵커 컬럼이 PK가 아니다."

    user_axis = _tables_with_owner_fk(metadata) | _tables_with_owner_column_name(metadata)
    assert (
        _STUDENT_SESSION_ANCHOR_TABLE in user_axis
    ), "앵커 테이블이 user 축((A)∪(B))으로 소유 판정되지 않는다 — (C)의 전제가 무너졌다."
    assert _STUDENT_SESSION_ANCHOR_TABLE in {m.__tablename__ for m, _ in _ERASURE_PLAN}
    assert _STUDENT_SESSION_ANCHOR_TABLE not in _tables_on_student_session_axis(
        metadata
    ), "앵커 테이블 자신이 (C)에 들어갔다 — 앵커 제외 절이 빠졌다."


def test_evidence_event_is_caught_only_by_student_session_axis() -> None:
    """SEC-39 사각 핀 — `evidence_event`는 (A)·(B) 밖이고 (C)로만 소유 판정된다.

    세 단언이 함께 있어야 의미가 있다: (A)·(B) 부재는 *왜 종전 가드가 초록이었는가*, (C) 포함은
    *지금 무엇이 잡는가*다. (C)를 지우는 뮤테이션에서 마지막 두 단언이 RED가 된다(④ 실측).
    """
    metadata = _real_metadata()
    table = metadata.tables["evidence_event"]

    # 픽스처 전제 — 실 스키마가 "user 축 0 · 세션 느슨참조 1"인 형태여야 이 핀이 그 사각을 밟는다.
    assert not table.foreign_keys, "evidence_event에 FK가 생겼다 — 사각 서술이 낡았다."
    assert "session_id" in table.columns, "evidence_event.session_id가 사라졌다."

    assert "evidence_event" not in _tables_with_owner_fk(metadata)
    assert "evidence_event" not in _tables_with_owner_column_name(metadata)
    assert "evidence_event" in _tables_on_student_session_axis(metadata), (
        "evidence_event가 (C) 학생 세션 축에 안 잡힌다 — session_id로만 학생에 묶이는 테이블이 "
        "다시 삭제권 가드의 사각에 들어갔다(SEC-39 회귀)."
    )
    assert "evidence_event" in _owner_tables(metadata)


def test_evidence_event_is_erased_or_temporarily_exempted_with_expiry() -> None:
    """`evidence_event`는 계획에 있거나(SEC-40 착지 후) 만료 있는 임시 예외다(SEC-39) — 제3 상태 없음.

    두 가지 중 하나만 성립해야 한다. SEC-40이 `_ERASURE_PLAN`에 편입하고 예외를 걷으면 앞 갈래로
    넘어간다 — 이 테스트는 수정 없이 그 전이를 받아들인다(조건부 공허 통과가 아니라 배타적 논리합).
    """
    planned = {m.__tablename__ for m, _ in _ERASURE_PLAN}
    in_plan = "evidence_event" in planned
    exempted = "evidence_event" in _ERASURE_PLAN_EXEMPTIONS
    assert in_plan != exempted, (
        f"evidence_event 상태가 모호하다(계획={in_plan}·예외={exempted}) — 계획 편입(SEC-40) 또는 "
        "만료 있는 임시 예외(SEC-39) 중 정확히 하나여야 한다."
    )
    if in_plan:
        return
    assert (
        _ERASURE_PLAN_EXEMPTION_EXPIRY.get("evidence_event") == "SEC-40"
    ), "evidence_event 임시 예외의 해소 태스크가 SEC-40이 아니다(만료 없는 유예 금지)."
    reason = _ERASURE_PLAN_EXEMPTIONS["evidence_event"]
    # 사유 문면 핀 — 재연결 경로 2건·처분 태스크·결정 게이트가 사유에서 사라지면 RED.
    for token in (
        "SEC-40",
        "G-eos37-erasure-kpi-disposition",
        "deletion_audit",
        "user_binding",
        "export",
    ):
        assert token in reason, f"evidence_event 예외 사유에 {token!r}이(가) 없다."


def test_non_student_session_columns_are_excluded_and_the_exclusion_is_load_bearing() -> None:
    """검수자·인증 세션 컬럼은 (C)에 안 들어가고, 그 제외가 실제로 일을 한다(오탐 회귀 방지).

    ① 현행: `review_timer_event`·`refresh_token_session`은 (C) 밖이다.
    ② 제외를 걷으면 둘 다 (C)에 들어온다 — 이름 절이 그 컬럼에 **실제로 닿는다**는 증명이다
       (닿지 않는데 제외를 두면 유령 제외다).
    ③ 그 상태에서 `review_timer_event`는 계획·허용목록 밖이라 스윕이 RED를 낸다 — 학생 세션이
       아닌 `*_session_id`가 새로 생기면 조용히 통과하지 않는다(fail-safe 방향의 실측).
    """
    metadata = _real_metadata()
    on_axis = _tables_on_student_session_axis(metadata)
    assert "review_timer_event" not in on_axis, (
        "검수자 세션(review_session_id)이 학생 세션 축으로 오분류됐다 — "
        "NON_STUDENT_SESSION_COLUMNS 제외가 사라졌거나 이름 절이 바뀌었다."
    )
    assert "refresh_token_session" not in on_axis

    unexcluded = _tables_on_student_session_axis(metadata, exclusions={})
    assert {"review_timer_event", "refresh_token_session"} <= unexcluded

    missing_unexcluded = _missing_from_plan(
        metadata,
        planned=_planned_tables(),
        exemptions=_ERASURE_PLAN_EXEMPTIONS,
        session_exclusions={},
    )
    assert "review_timer_event" in missing_unexcluded


def test_non_student_session_exclusions_are_real_reasoned_and_do_not_override_fk() -> None:
    """제외 목록 거버넌스 — 실존 컬럼 · 이름 절 해당 · FK 아님 · 사유 20자 이상.

    이름 절에 해당하지 않는 컬럼을 올리면 아무것도 제외하지 않는 유령 항목이 되고, 앵커 FK
    컬럼을 올리면 구조적 사실을 해석으로 덮는 셈이다 — 둘 다 거부한다.
    """
    metadata = _real_metadata()
    for (table_name, column_name), reason in NON_STUDENT_SESSION_COLUMNS.items():
        assert table_name in metadata.tables, f"제외 대상 테이블이 없다: {table_name}"
        table = metadata.tables[table_name]
        assert column_name in table.columns, f"제외 대상 컬럼이 없다: {table_name}.{column_name}"
        assert is_session_reference_name(
            column_name
        ), f"{table_name}.{column_name}은 이름 절에 안 걸린다 — 제외할 것이 없는 유령 항목이다."
        column = table.columns[column_name]
        assert not any(
            fk.target_fullname == STUDENT_SESSION_ANCHOR for fk in column.foreign_keys
        ), f"{table_name}.{column_name}은 학생 세션 FK다 — 제외 목록으로 구조를 덮을 수 없다."
        assert len(reason.strip()) >= 20, f"{table_name}.{column_name} 제외 사유가 지나치게 짧다."


def test_student_session_axis_on_real_metadata_is_not_vacuous() -> None:
    """(C) 스캔 0건은 실패 — 실 메타데이터에서 두 절이 각각 최소 1건을 잡는다.

    (C-FK)는 `problem_attempt.session_id`(→ learning_session FK), (C-이름)은 느슨참조
    `evidence_event`·`evidence_links`다. 어느 절이 0건이면 그 절의 구현이 끊긴 것이다.
    """
    metadata = _real_metadata()
    assert "problem_attempt" in _tables_with_student_session_fk(metadata)
    by_name = _tables_with_session_reference_name(metadata, exclusions=NON_STUDENT_SESSION_COLUMNS)
    assert {"evidence_event", "evidence_links"} <= by_name


# ===========================================================================
# SEC-39 — (C)의 절별 변별력(합성 MetaData). 각 픽스처는 *그 절이 없으면 통과해 버리는* 반례다.
# ===========================================================================


def _synthetic_learning_session(metadata: MetaData) -> Table:
    """합성 앵커 — user_id(→ user_profile FK)를 가진 학습 세션. 실 메타데이터 무오염."""
    return Table(
        "learning_session",
        metadata,
        Column("session_id", Uuid, primary_key=True, default=uuid.uuid4),
        Column("user_id", Uuid, sa.ForeignKey("user_profile.user_id")),
    )


def _synthetic_session_meta() -> MetaData:
    meta = MetaData()
    _synthetic_user_profile(meta)
    _synthetic_learning_session(meta)
    return meta


_SYNTHETIC_PLANNED = frozenset({"user_profile", "learning_session"})


def test_session_name_clause_catches_loose_reference_that_user_axes_miss() -> None:
    """(C-이름) 반례 — user 축 0 + `session_id` 느슨참조(= evidence_event 형태).

    (A)·(B)·(C-FK) 어디에도 안 걸리는 것을 대조군으로 먼저 단언한다 — 그래야 이 픽스처가
    (C-이름) 절을 실제로 밟는다(절을 지우면 이 테스트만 RED).
    """
    meta = _synthetic_session_meta()
    Table(
        "treatment_log_tbl",
        meta,
        Column("event_id", sa.BigInteger, primary_key=True),
        Column("session_id", Uuid),  # FK 없음 — 하이퍼테이블 느슨참조
        Column("payload", sa.Text),
    )
    assert "treatment_log_tbl" not in _tables_with_owner_fk(meta)
    assert "treatment_log_tbl" not in _tables_with_owner_column_name(meta)
    assert "treatment_log_tbl" not in _tables_with_student_session_fk(meta)

    assert "treatment_log_tbl" in _tables_with_session_reference_name(meta, exclusions={})
    missing = _missing_from_plan(meta, planned=_SYNTHETIC_PLANNED, exemptions={})
    assert missing == frozenset({"treatment_log_tbl"}), "세션 느슨참조 주입에서 red가 나지 않았다."


def test_session_name_clause_matches_suffix_alias() -> None:
    """(C-이름) 접미 절 반례 — `learning_session_id` 별칭 느슨참조(정확 일치만 보면 놓친다)."""
    meta = _synthetic_session_meta()
    Table(
        "aliased_session_tbl",
        meta,
        Column("id", Uuid, primary_key=True, default=uuid.uuid4),
        Column("learning_session_id", Uuid),  # FK 없음 — 별칭
    )
    assert "aliased_session_tbl" not in _tables_with_student_session_fk(meta)
    missing = _missing_from_plan(meta, planned=_SYNTHETIC_PLANNED, exemptions={})
    assert missing == frozenset({"aliased_session_tbl"}), "접미 별칭 주입에서 red가 나지 않았다."


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("session_id", True),
        ("learning_session_id", True),
        ("review_session_id", True),
        # 근접 비일치(실 스키마에 실재하는 이름들 포함) — 세션 *참조*가 아니다.
        ("session_type", False),  # learning_session.session_type
        ("session_position", False),  # problem.session_position
        ("avg_session_quality", False),  # user_state_snapshot.avg_session_quality
        ("session_ids", False),
        ("sessionid", False),
        ("session_id_hash", False),
    ],
)
def test_session_reference_name_clause_boundaries(name: str, expected: bool) -> None:
    """(C-이름) 절의 경계 — 정확 일치·접미 일치만. 근접 이름은 잡지 않는다."""
    assert is_session_reference_name(name) is expected


def test_session_fk_clause_catches_alias_that_name_clause_misses() -> None:
    """(C-FK) 반례 — 앵커 FK + 세션처럼 안 보이는 별칭 컬럼. 이름 절은 구조적으로 못 본다."""
    meta = _synthetic_session_meta()
    Table(
        "sitting_note_tbl",
        meta,
        Column("id", Uuid, primary_key=True, default=uuid.uuid4),
        Column("sitting_ref", Uuid, sa.ForeignKey("learning_session.session_id")),
    )
    assert "sitting_note_tbl" not in _tables_with_session_reference_name(meta, exclusions={})
    assert "sitting_note_tbl" not in _tables_with_owner_fk(meta)
    assert "sitting_note_tbl" not in _tables_with_owner_column_name(meta)

    assert "sitting_note_tbl" in _tables_with_student_session_fk(meta)
    missing = _missing_from_plan(meta, planned=_SYNTHETIC_PLANNED, exemptions={})
    assert missing == frozenset({"sitting_note_tbl"}), "세션 FK 별칭 주입에서 red가 나지 않았다."


def test_anchor_clause_keeps_learning_session_off_the_session_axis() -> None:
    """앵커 제외 절 반례 — 앵커 테이블은 `session_id` PK를 가지므로 절이 없으면 (C)에 들어간다."""
    meta = _synthetic_session_meta()
    assert "learning_session" not in _tables_on_student_session_axis(meta, exclusions={})
    # 앵커는 user 축으로 소유된다 — (C)에서 빠져도 소유 판정에서 빠지지 않는다.
    assert "learning_session" in _owner_tables(meta, session_exclusions={})


def test_exclusions_suppress_name_clause_but_never_fk_clause() -> None:
    """제외 목록은 이름 절만 끈다 — 같은 테이블이 앵커 FK를 가지면 여전히 (C)다."""
    meta = _synthetic_session_meta()
    Table(
        "reviewer_tbl",
        meta,
        Column("id", Uuid, primary_key=True, default=uuid.uuid4),
        Column("review_session_id", Uuid),  # 비학생 세션 — 제외 대상
    )
    Table(
        "mixed_tbl",
        meta,
        Column("id", Uuid, primary_key=True, default=uuid.uuid4),
        Column("audit_session_id", Uuid),  # 제외 대상 이름
        Column("sitting_ref", Uuid, sa.ForeignKey("learning_session.session_id")),  # 구조
    )
    exclusions = {
        ("reviewer_tbl", "review_session_id"): "검수자 세션 — 학생 학습 세션이 아니다(합성).",
        ("mixed_tbl", "audit_session_id"): "감사 세션 — 학생 학습 세션이 아니다(합성 픽스처).",
    }
    # 대조군 — 제외 없으면 둘 다 (C).
    assert {"reviewer_tbl", "mixed_tbl"} <= _tables_on_student_session_axis(meta, exclusions={})

    on_axis = _tables_on_student_session_axis(meta, exclusions=exclusions)
    assert "reviewer_tbl" not in on_axis, "사유 명시 제외가 이름 절을 끄지 못했다."
    assert "mixed_tbl" in on_axis, "제외 목록이 앵커 FK(구조)까지 덮었다."


# ===========================================================================
# SEC-39 — 임시 예외의 **만료 장치**(CLAUDE.md 「만료 없는 유예·제외 금지」).
#
# 선례: `ops/provenance_audit.py`의 `GrandfatherEntry` + `find_grandfather_expiry_violations`
# (ARCH-25 — CLAUDE.md가 "PB-02 그랜드파더 만료 계약"으로 부르는 코드 착지)와
# `ops/declared_unwired_audit.py`의 `pending-task:<id>`. 같은 계약을 따른다:
#   · 임시 예외는 `_ERASURE_PLAN_EXEMPTION_EXPIRY`에 **해소 태스크 ID**를 구조 필드로 등재한다
#     (사유 문자열 속 태스크 ID는 기계가 대조할 수 없다 — ARCH-25 `_S3_11_PENDING` 방치 선례).
#   · 그 태스크가 **없거나**(오타·삭제) **종결**(done·cancelled)이면 RED. 자동 해제가 아니다 —
#     항목을 걷으라는 신호이고, 걷는 것은 처분을 구현하는 사람이다.
#   · ARCH-25와의 차이: `cancelled`도 만료로 본다. 해소 태스크가 취소되면 이 예외는 추적자를
#     잃은 영구 예외가 되는데, 그것이 정확히 「만료 없는 유예」다(재계획 대상으로 드러나야 한다).
#   · 모르는 상태 값·파싱 실패·해석 모호(후보 2건 이상)도 RED — 모른다 ≠ 아니다(CLAUDE.md).
#
# **발화 시점의 한계(정직 표기)**: CI backend 잡의 경로 필터(`.github/workflows/ci.yml`)는
# `backlog/tasks/`를 보지 않는다. 그래서 해소 태스크 상태만 바꾸는 PR에서는 이 검사가 돌지 않고,
# 그 다음 backend를 건드리는 PR에서 RED가 난다 — 늦지만 조용하지는 않다(ARCH-25와 같은 성질).
# 정상 경로에서는 SEC-40 자신의 구현 PR이 erasure.py를 고치므로 backend 잡이 그 PR에서 돈다.
# ===========================================================================

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKLOG_TASKS_DIR = _REPO_ROOT / "backlog" / "tasks"

# `scripts/harness/models.py` STATUSES 미러(백엔드 테스트는 하네스 패키지를 import하지 않는다).
# 하네스에 새 상태가 생기면 아래 "알 수 없는 상태" 위반으로 드러난다 — 조용히 통과하지 않는다.
_EXPIRED_TASK_STATUSES = frozenset({"done", "cancelled"})
_PENDING_TASK_STATUSES = frozenset({"todo", "in_progress", "blocked", "review"})

# 만료 없는 **영구** 예외 — 법적 성격상 계정 삭제 뒤에도 남아야 하는 것(E형 감사)과, 튜플 밖에서
# 명시 삭제되는 `user_profile`. 여기에 없는 허용목록 항목은 전부 임시이며 해소 태스크가 필요하다.
# 영구 예외를 늘리는 것은 이 집합을 **의식적으로** 고치는 일이어야 한다(조용한 영구화 차단).
PERMANENT_ERASURE_EXEMPTIONS: frozenset[str] = frozenset(
    {"user_profile", "deletion_audit", "privacy_audit"}
)


def _resolve_task_status(tasks_dir: Path, task_id: str) -> tuple[str | None, str | None]:
    """`backlog/tasks`에서 `task_id`의 상태를 찾는다 — (status, 오류). 찾지 못하면 오류.

    파일명은 `<id>.yaml`(짧은 ID) 또는 `<id>-<슬러그>.yaml`(full ID) 두 형태다. `SEC-40*.yaml`
    같은 접두 글롭은 `SEC-400.yaml`까지 삼키므로 쓰지 않고, 두 형태만 모은 뒤 파일 안의 `id`를
    다시 대조한다. 후보 0건은 "스캔 0건 = 실패", 2건 이상은 "해석 모호 = 실패"다.
    """
    candidates = sorted({*tasks_dir.glob(f"{task_id}.yaml"), *tasks_dir.glob(f"{task_id}-*.yaml")})
    matches: list[tuple[Path, dict[str, object]]] = []
    for path in candidates:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            return None, f"{path.name} 파싱 실패({type(exc).__name__}) — 상태를 판정할 수 없다."
        if not isinstance(data, dict):
            return None, f"{path.name}이(가) 매핑이 아니다 — 상태를 판정할 수 없다."
        found_id = data.get("id")
        if isinstance(found_id, str) and (
            found_id == task_id or found_id.startswith(f"{task_id}-")
        ):
            matches.append((path, data))
    if not matches:
        return None, f"해소 태스크 {task_id!r}의 백로그 파일이 없다(스캔 0건 — 추적 불가능한 예외)."
    if len(matches) > 1:
        names = sorted(p.name for p, _ in matches)
        return None, f"해소 태스크 {task_id!r}의 후보가 여럿이다: {names} — 해석 모호."
    path, data = matches[0]
    status = data.get("status")
    if not isinstance(status, str):
        return None, f"{path.name}에 status가 없다 — 상태를 판정할 수 없다."
    return status, None


def _exemption_expiry_violations(
    *,
    expiry: dict[str, str],
    exemptions: dict[str, str],
    tasks_dir: Path,
) -> list[str]:
    """임시 예외 만료 계약 위반 목록(빈 리스트 = 위반 없음)."""
    violations: list[str] = []
    for table_name, task_id in sorted(expiry.items()):
        if table_name not in exemptions:
            violations.append(
                f"{table_name}: 만료 등재는 있는데 _ERASURE_PLAN_EXEMPTIONS에 없다(유령 만료)."
            )
            continue
        if task_id not in exemptions[table_name]:
            violations.append(
                f"{table_name}: 예외 사유가 해소 태스크 {task_id}를 언급하지 않는다(사유·구조 불일치)."
            )
        status, error = _resolve_task_status(tasks_dir, task_id)
        if error is not None:
            violations.append(f"{table_name}: {error}")
        elif status in _EXPIRED_TASK_STATUSES:
            violations.append(
                f"{table_name}: 해소 태스크 {task_id}가 이미 {status}인데 임시 예외가 남아 있다 — "
                "만료됐다. _ERASURE_PLAN에 편입하고 예외·만료 등재를 걷거나(done), 새 해소 "
                "태스크로 재계획하라(cancelled)."
            )
        elif status not in _PENDING_TASK_STATUSES:
            violations.append(f"{table_name}: 해소 태스크 {task_id}의 상태 {status!r}를 모른다.")
    return violations


def test_temporary_exemptions_have_a_live_expiry_task() -> None:
    """실측 — 현행 임시 예외는 전부 살아 있는(미종결) 해소 태스크를 가진다.

    SEC-40이 done이 되고도 `evidence_event` 항목이 남아 있으면 여기서 RED다(④ 뮤테이션 실측).
    """
    assert _BACKLOG_TASKS_DIR.is_dir(), f"백로그 태스크 디렉터리가 없다: {_BACKLOG_TASKS_DIR}"
    assert any(_BACKLOG_TASKS_DIR.glob("*.yaml")), "백로그 태스크 파일이 0건이다(경로 계산 오류)."
    violations = _exemption_expiry_violations(
        expiry=_ERASURE_PLAN_EXEMPTION_EXPIRY,
        exemptions=_ERASURE_PLAN_EXEMPTIONS,
        tasks_dir=_BACKLOG_TASKS_DIR,
    )
    assert violations == [], "임시 예외 만료 계약 위반:\n" + "\n".join(violations)


def test_every_non_permanent_exemption_has_an_expiry() -> None:
    """허용목록 = 영구(고정 집합) ⊔ 임시(만료 등재) — 만료 없는 임시 예외는 존재할 수 없다."""
    temporary = frozenset(_ERASURE_PLAN_EXEMPTION_EXPIRY)
    assert not (temporary & PERMANENT_ERASURE_EXEMPTIONS), "영구 예외에 만료가 붙었다(모순)."
    undeclared = frozenset(_ERASURE_PLAN_EXEMPTIONS) - temporary - PERMANENT_ERASURE_EXEMPTIONS
    assert undeclared == frozenset(), (
        f"만료 등재 없는 비영구 예외: {sorted(undeclared)} — 임시면 _ERASURE_PLAN_EXEMPTION_EXPIRY에 "
        "해소 태스크를 등재하고, 영구(E형 감사 등)면 PERMANENT_ERASURE_EXEMPTIONS를 의식적으로 "
        "갱신하라(만료 없는 유예 금지)."
    )
    assert PERMANENT_ERASURE_EXEMPTIONS <= frozenset(
        _ERASURE_PLAN_EXEMPTIONS
    ), "영구 예외 집합에 허용목록에 없는 이름이 있다(유령 영구 예외)."


def _write_task(tasks_dir: Path, filename: str, body: str) -> None:
    tasks_dir.mkdir(parents=True, exist_ok=True)
    (tasks_dir / filename).write_text(body, encoding="utf-8")


_SYNTH_EXEMPTIONS = {"tmp_tbl": "임시 예외 — 해소 태스크 SEC-40이 처분한다(합성 픽스처 사유)."}
_SYNTH_EXPIRY = {"tmp_tbl": "SEC-40"}


@pytest.mark.parametrize("status", ["todo", "in_progress", "blocked", "review"])
def test_expiry_passes_while_task_is_pending(tmp_path: Path, status: str) -> None:
    """대조군 — 해소 태스크가 미종결이면 위반 0(모든 미종결 상태)."""
    _write_task(tmp_path, "SEC-40.yaml", f"id: SEC-40\nstatus: {status}\n")
    violations = _exemption_expiry_violations(
        expiry=_SYNTH_EXPIRY, exemptions=_SYNTH_EXEMPTIONS, tasks_dir=tmp_path
    )
    assert violations == []


@pytest.mark.parametrize("status", ["done", "cancelled"])
def test_expiry_fires_when_task_is_terminal(tmp_path: Path, status: str) -> None:
    """만료 — 해소 태스크가 done·cancelled인데 예외가 남아 있으면 위반."""
    _write_task(tmp_path, "SEC-40.yaml", f"id: SEC-40\nstatus: {status}\n")
    violations = _exemption_expiry_violations(
        expiry=_SYNTH_EXPIRY, exemptions=_SYNTH_EXEMPTIONS, tasks_dir=tmp_path
    )
    assert len(violations) == 1 and status in violations[0], violations


def test_expiry_resolves_full_id_filename(tmp_path: Path) -> None:
    """full-ID 파일명(`<id>-<슬러그>.yaml`)도 해석한다 — 대조군(미종결)과 만료(done) 양쪽."""
    _write_task(tmp_path, "SEC-40-relink-block.yaml", "id: SEC-40-relink-block\nstatus: todo\n")
    assert (
        _exemption_expiry_violations(
            expiry=_SYNTH_EXPIRY, exemptions=_SYNTH_EXEMPTIONS, tasks_dir=tmp_path
        )
        == []
    )
    _write_task(tmp_path, "SEC-40-relink-block.yaml", "id: SEC-40-relink-block\nstatus: done\n")
    assert _exemption_expiry_violations(
        expiry=_SYNTH_EXPIRY, exemptions=_SYNTH_EXEMPTIONS, tasks_dir=tmp_path
    )


@pytest.mark.parametrize(
    ("files", "needle"),
    [
        ({}, "스캔 0건"),  # 파일 자체가 없다
        ({"SEC-400.yaml": "id: SEC-400\nstatus: todo\n"}, "스캔 0건"),  # 접두 글롭 함정
        ({"SEC-40.yaml": "id: SEC-41\nstatus: todo\n"}, "스캔 0건"),  # 파일명↔id 불일치
        (
            {
                "SEC-40.yaml": "id: SEC-40\nstatus: todo\n",
                "SEC-40-dup.yaml": "id: SEC-40-dup\nstatus: todo\n",
            },
            "해석 모호",
        ),
        ({"SEC-40.yaml": "id: SEC-40\nstatus: archived\n"}, "모른다"),
        ({"SEC-40.yaml": "id: SEC-40\n"}, "status가 없다"),
        ({"SEC-40.yaml": "id: [SEC-40\nstatus: todo\n"}, "파싱 실패"),
        ({"SEC-40.yaml": "- id: SEC-40\n"}, "매핑이 아니다"),
    ],
)
def test_expiry_fails_closed_when_status_is_unknowable(
    tmp_path: Path, files: dict[str, str], needle: str
) -> None:
    """모른다 ≠ 아니다 — 태스크를 못 찾거나 상태를 판정할 수 없으면 조용히 통과하지 않는다."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    for filename, body in files.items():
        _write_task(tmp_path, filename, body)
    violations = _exemption_expiry_violations(
        expiry=_SYNTH_EXPIRY, exemptions=_SYNTH_EXEMPTIONS, tasks_dir=tmp_path
    )
    assert len(violations) == 1 and needle in violations[0], violations


def test_expiry_rejects_ghost_entry_and_reason_mismatch(tmp_path: Path) -> None:
    """만료 등재가 허용목록에 없거나(유령), 사유가 해소 태스크를 언급하지 않으면 위반."""
    _write_task(tmp_path, "SEC-40.yaml", "id: SEC-40\nstatus: todo\n")
    ghost = _exemption_expiry_violations(expiry=_SYNTH_EXPIRY, exemptions={}, tasks_dir=tmp_path)
    assert len(ghost) == 1 and "유령 만료" in ghost[0], ghost

    mismatched = _exemption_expiry_violations(
        expiry=_SYNTH_EXPIRY,
        exemptions={"tmp_tbl": "임시 예외 — 사유에 해소 태스크 번호를 빠뜨린 합성 픽스처."},
        tasks_dir=tmp_path,
    )
    assert len(mismatched) == 1 and "언급하지 않는다" in mismatched[0], mismatched
