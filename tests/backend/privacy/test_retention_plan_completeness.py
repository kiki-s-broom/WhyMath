"""SEC-41 — 보존 기간 파기 완전성 가드(실행→계획 방향, 소유 테이블 중 파기 계획 누락 검출).

삭제권에는 `test_erasure_plan_completeness.py`가 있었다 — "소유 축을 가진 테이블인데 `_ERASURE_PLAN`·
사유 있는 허용목록 어디에도 없는 것이 있는가"를 `Base.metadata.tables` 전수에서 묻는다(SEC-35·
SEC-39가 사각을 두 번 닫았다). 보존 파기에는 그 가드가 **없었다**: `privacy/retention.py`의
`_RETENTION_PLAN`에 새 학생 테이블이 들어갔는지 기계가 묻지 않았고, `tests/backend/privacy/
test_retention.py`의 `_EXCLUDED_TABLES`는 사유 없이 이름만 나열한 집합이었다. 그 결과 소유 테이블 4건
(`evidence_event`·`job_ownership`·`learner_state`·`learning_state_transition`)이 아무도 모르게
파기 계획 밖에 있었다(2026-10-02 실측 — 소유 28테이블 중 계획 밖 15건, 그중 11건만 사유가 있었다).

이 모듈은 삭제권 가드의 **소유 판정 (A)∪(B)∪(C)를 그대로 재사용**한다(파일 경로 로드 — 판정 로직을
복제하지 않으므로 삭제권 쪽이 사각을 하나 더 닫으면 이쪽도 자동으로 따라간다). 소유 테이블은 아래
셋 중 하나에 있어야 한다:
  ① `_RETENTION_PLAN` — `purge_expired_records`가 타임스탬프 창으로 지운다.
  ② `_PURGED_ELSEWHERE` — 다른 경로가 지운다(`evidence_links` → `evidence_store.purge_expired`).
  ③ `_RETENTION_PLAN_EXEMPTIONS` — 사유와 함께 *의도적으로* 지우지 않는다.

hermetic: `Base.metadata`(선언적 메타데이터)·소스 AST·`backlog/tasks/*.yaml`만 읽는다 — DB 연결 0.
임시 제외의 만료 장치는 삭제권 쪽 SEC-39 계약을 그대로 쓴다(해소 태스크가 종결됐는데 항목이 남으면
RED — CLAUDE.md 「만료 없는 유예·제외 금지」).

**이 가드가 보지 않는 것(정직 표기)**:
  ⓐ 소유 판정의 사각은 삭제권 가드의 「남는 사각」 ①②③을 **그대로 상속**한다 — 이 모듈은 사각을 더
     닫지도 새로 만들지도 않는다.
  ⓑ 계획에 *있다*는 것만 본다 — 계획의 기준 컬럼이 NULL을 허용하면 NULL 행은 영원히 안 지워진다
     (`retention.py` 「정직 스코프」). 아래 처분 핀은 이번에 편입한 3테이블에만 NOT NULL을 단언한다.
  ⓒ 연한의 *적법성*은 보지 않는다 — 법령 판단이며 MGMT-02 회신 대기다.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import uuid
from datetime import date
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from sqlalchemy import Column, MetaData, Table, Uuid

from whymath_backend.db.models.evidence_event import EvidenceEvent
from whymath_backend.l4.misconception import evidence_store
from whymath_backend.privacy import retention_purge_cli
from whymath_backend.privacy.retention import (
    _PURGED_ELSEWHERE,
    _RETENTION_PLAN,
    _RETENTION_PLAN_EXEMPTION_EXPIRY,
    _RETENTION_PLAN_EXEMPTIONS,
    _purge_condition,
)

# ===========================================================================
# 삭제권 가드의 소유 판정 재사용 — 경로 로드(저장소에 같은 선례 다수: `spec_from_file_location`).
#
# 형제 *테스트 모듈*을 import하는 선례는 없다(`tests/backend`는 패키지가 아니고 pytest는
# importlib 모드다). 판정 로직을 이 파일로 옮기면 삭제권 가드와 갈라지고, 삭제권 가드 파일을 헬퍼로
# 쪼개면 SEC-40이 같은 파일을 고칠 때 충돌한다 — 그래서 읽기 전용으로 로드한다. 로드가 실패하면
# 수집 단계에서 시끄럽게 죽는다(조용히 건너뛰지 않는다). `test_*`로 시작하는 이름은 절대 이 모듈
# 네임스페이스에 바인딩하지 않는다 — 그러면 삭제권 가드의 테스트가 여기서 중복 수집된다.
# ===========================================================================

_ERASURE_GUARD_PATH = Path(__file__).with_name("test_erasure_plan_completeness.py")


def _load_erasure_guard() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "_erasure_plan_completeness_for_retention_guard", _ERASURE_GUARD_PATH
    )
    if spec is None or spec.loader is None:
        raise AssertionError(f"삭제권 완전성 가드를 로드할 수 없다: {_ERASURE_GUARD_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_ERASURE_GUARD = _load_erasure_guard()

# 소유 판정 — 삭제권 가드의 것을 그대로 쓴다(복제 금지). 아래 이름은 `test_`로 시작하지 않는다.
_owner_tables = _ERASURE_GUARD._owner_tables
_real_metadata = _ERASURE_GUARD._real_metadata
_NON_STUDENT_SESSION_COLUMNS: dict[tuple[str, str], str] = (
    _ERASURE_GUARD.NON_STUDENT_SESSION_COLUMNS
)
_exemption_expiry_violations = _ERASURE_GUARD._exemption_expiry_violations
_BACKLOG_TASKS_DIR: Path = _ERASURE_GUARD._BACKLOG_TASKS_DIR

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SRC_ROOT = _REPO_ROOT / "src" / "backend" / "whymath_backend"

# 만료 없는 **영구** 제외 — 기술적 자가만료로 수명이 정해지는 인증 자격 2건뿐이다. 여기에 없는 제외
# 항목은 전부 임시이며 해소 태스크가 필요하다. 영구 제외를 늘리는 것은 이 집합을 **의식적으로** 고치는
# 일이어야 한다(조용한 영구화 차단 — 삭제권 가드의 `PERMANENT_ERASURE_EXEMPTIONS`와 같은 계약).
PERMANENT_RETENTION_EXEMPTIONS: frozenset[str] = frozenset(
    {"device_credential", "refresh_token_session"}
)

_MIN_REASON_LENGTH = 20


def _planned_tables() -> frozenset[str]:
    """`_RETENTION_PLAN`이 지우는 테이블."""
    return frozenset(model.__tablename__ for model, _ in _RETENTION_PLAN)


def _uncovered_owner_tables(
    metadata: MetaData,
    *,
    planned: frozenset[str],
    elsewhere: frozenset[str],
    exemptions: frozenset[str],
    session_exclusions: dict[tuple[str, str], str] = _NON_STUDENT_SESSION_COLUMNS,
) -> frozenset[str]:
    """소유 테이블 중 ①계획 ②다른 경로 ③사유 있는 제외 — 셋 어디에도 없는 것(실행→계획)."""
    owners = _owner_tables(metadata, session_exclusions=session_exclusions)
    return owners - planned - elsewhere - exemptions


def _unreasoned(reasons: dict[str, str]) -> list[str]:
    """사유가 비었거나(공백뿐 포함) 형식적으로 짧은 항목의 이름 — 비어 있어야 정상."""
    return sorted(
        name for name, reason in reasons.items() if len(reason.strip()) < _MIN_REASON_LENGTH
    )


# ===========================================================================
# 실측 — 현행 소유 테이블 전수 검사(RED면 이 태스크에서 상환 필요)
# ===========================================================================


def test_no_owner_table_is_missing_from_the_retention_coverage() -> None:
    """실행→계획 방향 — 계획·다른 경로·사유 있는 제외 *밖*의 소유 테이블(0건이어야 함)."""
    missing = _uncovered_owner_tables(
        _real_metadata(),
        planned=_planned_tables(),
        elsewhere=frozenset(_PURGED_ELSEWHERE),
        exemptions=frozenset(_RETENTION_PLAN_EXEMPTIONS),
    )
    assert missing == frozenset(), (
        f"소유 축((A) user_profile.user_id FK · (B) 삭제권 계획 파생 컬럼명 · (C) 학생 세션 축)을 "
        f"가졌으나 _RETENTION_PLAN·_PURGED_ELSEWHERE·_RETENTION_PLAN_EXEMPTIONS 어디에도 없는 "
        f"테이블: {sorted(missing)} — 보존 기간이 지나도 영원히 지워지지 않는 테이블이다. "
        "_RETENTION_PLAN에 편입(타임스탬프 컬럼 지정)하거나, 사유와 함께 "
        "_RETENTION_PLAN_EXEMPTIONS에 등재하라(무사유 제외 금지 · 임시면 "
        "_RETENTION_PLAN_EXEMPTION_EXPIRY에 해소 태스크도). 연한이 법령 판단이면 연한을 코드가 "
        "정하지 않고 MGMT-02 회신 대기로 명시하라."
    )


def test_owner_scan_on_real_metadata_is_not_vacuous() -> None:
    """스캔 0건은 실패 — 소유 판정이 실제로 일했고 계획과 겹치는 소유 테이블이 있다.

    판정 로드가 끊겨 빈 집합을 돌려주면 위 단언은 *모든 입력에서* 초록이다(공허 통과).
    """
    owners = _owner_tables(_real_metadata())
    assert {
        "learning_session",
        "problem_attempt",
        "evidence_event",
        "user_profile",
    } <= owners, "소유 판정이 알려진 소유 테이블을 못 본다 — 삭제권 가드 로드·판정이 끊겼다."
    covered_by_plan = owners & _planned_tables()
    assert covered_by_plan, "계획과 겹치는 소유 테이블이 0건이다 — 판정 또는 계획이 끊겼다."
    assert owners - covered_by_plan, "계획 밖 소유 테이블이 0건이다 — 제외 목록 검증이 공허하다."


def test_exemption_and_elsewhere_reasons_are_nonempty() -> None:
    """제외·다른 경로 항목에 사유가 있다 — 무사유 제외 금지(CLAUDE.md 하드 게이트)."""
    assert _RETENTION_PLAN_EXEMPTIONS, "제외 목록이 비어 있으면 안 된다(감사 테이블 최소 2종)."
    assert _PURGED_ELSEWHERE, "다른 경로 목록이 비어 있으면 안 된다(evidence_links 최소 1종)."
    offenders = _unreasoned({**_RETENTION_PLAN_EXEMPTIONS, **_PURGED_ELSEWHERE})
    assert offenders == [], f"사유가 비었거나 지나치게 짧은 항목: {offenders}"


def test_exemptions_are_real_owner_tables_and_not_double_listed() -> None:
    """유령 제외·중복 등재 금지 — 제외·다른 경로 항목은 실제 소유 테이블이고 계획과 겹치지 않는다."""
    metadata = _real_metadata()
    owners = _owner_tables(metadata)
    planned = _planned_tables()
    exempt = frozenset(_RETENTION_PLAN_EXEMPTIONS)
    elsewhere = frozenset(_PURGED_ELSEWHERE)

    ghosts = (exempt | elsewhere) - owners
    assert ghosts == frozenset(), f"소유 테이블이 아닌데 등재된 유령 항목: {sorted(ghosts)}"
    assert (exempt | elsewhere) <= frozenset(metadata.tables), "존재하지 않는 테이블이 등재됐다."
    assert exempt & planned == frozenset(), f"계획과 제외에 모두 있다: {sorted(exempt & planned)}"
    assert (
        elsewhere & planned == frozenset()
    ), f"계획과 다른 경로에 모두 있다: {sorted(elsewhere & planned)}"
    assert (
        exempt & elsewhere == frozenset()
    ), f"제외와 다른 경로에 모두 있다: {sorted(exempt & elsewhere)}"


# ===========================================================================
# 임시 제외의 만료 장치 — 삭제권 SEC-39 계약 재사용(해소 태스크 종결 후 항목 잔존 = RED)
# ===========================================================================


def test_temporary_exemptions_have_a_live_resolution_task() -> None:
    """실측 — 현행 임시 제외는 전부 살아 있는(미종결) 해소 태스크를 가진다.

    해소 태스크(MGMT-02·ARCH-51·SEC-25)가 done·cancelled가 되고도 항목이 남으면 RED다.
    위반 메시지의 `_ERASURE_PLAN*` 표기는 삭제권 가드와 공유하는 문구이니 `_RETENTION_PLAN*`로
    읽는다(같은 계약·다른 대상).
    """
    assert _BACKLOG_TASKS_DIR.is_dir(), f"백로그 태스크 디렉터리가 없다: {_BACKLOG_TASKS_DIR}"
    assert any(_BACKLOG_TASKS_DIR.glob("*.yaml")), "백로그 태스크 파일이 0건이다(경로 계산 오류)."
    assert _RETENTION_PLAN_EXEMPTION_EXPIRY, "만료 등재가 0건이다 — 임시 제외 검사가 공허하다."
    violations = _exemption_expiry_violations(
        expiry=_RETENTION_PLAN_EXEMPTION_EXPIRY,
        exemptions=_RETENTION_PLAN_EXEMPTIONS,
        tasks_dir=_BACKLOG_TASKS_DIR,
    )
    assert (
        violations == []
    ), "보존 파기 임시 제외 만료 계약 위반(`_ERASURE_PLAN*` → `_RETENTION_PLAN*`로 읽을 것):\n" + "\n".join(
        violations
    )


def test_every_non_permanent_exemption_has_an_expiry() -> None:
    """제외 목록 = 영구(고정 집합) ⊔ 임시(만료 등재) — 만료 없는 임시 제외는 존재할 수 없다."""
    temporary = frozenset(_RETENTION_PLAN_EXEMPTION_EXPIRY)
    exempt = frozenset(_RETENTION_PLAN_EXEMPTIONS)
    assert not (temporary & PERMANENT_RETENTION_EXEMPTIONS), "영구 제외에 만료가 붙었다(모순)."
    undeclared = exempt - temporary - PERMANENT_RETENTION_EXEMPTIONS
    assert undeclared == frozenset(), (
        f"만료 등재 없는 비영구 제외: {sorted(undeclared)} — 임시면 "
        "_RETENTION_PLAN_EXEMPTION_EXPIRY에 해소 태스크를 등재하고, 영구면 "
        "PERMANENT_RETENTION_EXEMPTIONS를 의식적으로 갱신하라(만료 없는 제외 금지)."
    )
    assert (
        PERMANENT_RETENTION_EXEMPTIONS <= exempt
    ), "영구 제외 집합에 제외 목록에 없는 이름이 있다."


# ===========================================================================
# `_PURGED_ELSEWHERE`는 "다른 경로가 실제로 지운다"는 주장이다 — 그 경로의 실재를 대조한다.
# 주장만 있고 경로가 사라지면 그 테이블은 아무도 안 지우는데 가드는 초록이다(침묵 위장).
# ===========================================================================


def test_purged_elsewhere_claim_for_evidence_links_is_real() -> None:
    """`evidence_links`를 `purge_expired`가 실제로 지우고 CLI가 그것을 호출한다."""
    assert "evidence_links" in _PURGED_ELSEWHERE
    purge_source = inspect.getsource(evidence_store.purge_expired)
    assert "delete(EvidenceLink)" in purge_source, (
        "evidence_store.purge_expired가 EvidenceLink를 지우지 않는다 — `_PURGED_ELSEWHERE` 주장이 "
        "거짓이 됐다. 다른 경로로 옮겼으면 이 맵을 갱신하고, 없어졌으면 `_RETENTION_PLAN`에 편입하라."
    )
    cli_source = inspect.getsource(retention_purge_cli._default_purge_fn)
    assert "purge_expired(session" in cli_source, (
        "retention_purge_cli가 evidence_store.purge_expired를 호출하지 않는다 — evidence_links를 "
        "지우는 스케줄이 사라졌다(`_PURGED_ELSEWHERE` 주장이 거짓)."
    )
    assert "purge_expired_records(session" in cli_source, "CLI가 이 모듈의 파기를 호출하지 않는다."


# ===========================================================================
# 변별력 — 합성 MetaData. 각 픽스처는 *그 절이 없으면 통과해 버리는* 반례다(실 Base.metadata 무오염).
#
# 세 절(계획·다른 경로·사유 제외)은 각자 **혼자서** 소유 테이블을 덮을 수 있어야 한다. 절을 하나
# 지운 뮤테이션이 살아남지 않도록, 아래 세 테스트는 각각 *오직 그 절 하나만* 제공하는 입력을 쓴다.
# ===========================================================================


def _owner_table_meta(table_name: str = "student_note_tbl") -> MetaData:
    """`user_id` 소유 컬럼 하나를 가진 합성 테이블 — (B) 이름 축에 걸리도록 한다."""
    meta = MetaData()
    Table(
        table_name,
        meta,
        Column("id", Uuid, primary_key=True, default=uuid.uuid4),
        Column("user_id", Uuid),
        Column("created_at", sa.DateTime(timezone=True)),
    )
    return meta


_NONE = frozenset[str]()


def test_uncovered_sweep_flags_injected_leak_then_clears_when_covered() -> None:
    """대조군 + 양방향 — 아무 절도 안 덮으면 RED, 덮는 순간 GREEN(같은 테이블)."""
    meta = _owner_table_meta()
    leaked = _uncovered_owner_tables(meta, planned=_NONE, elsewhere=_NONE, exemptions=_NONE)
    assert leaked == frozenset({"student_note_tbl"}), "리크 주입에서 red가 나지 않았다(위장 검증)."

    covered = _uncovered_owner_tables(
        meta, planned=frozenset({"student_note_tbl"}), elsewhere=_NONE, exemptions=_NONE
    )
    assert covered == frozenset(), "덮은 뒤에도 red가 남았다 — 검사 로직 결함."


def test_planned_clause_alone_covers_an_owner_table() -> None:
    """절 ① 반례 — 계획에만 있는 테이블. `- planned`를 지우면 이 테스트만 RED."""
    meta = _owner_table_meta()
    assert (
        _uncovered_owner_tables(
            meta, planned=frozenset({"student_note_tbl"}), elsewhere=_NONE, exemptions=_NONE
        )
        == frozenset()
    )


def test_elsewhere_clause_alone_covers_an_owner_table() -> None:
    """절 ② 반례 — 다른 경로에만 있는 테이블. `- elsewhere`를 지우면 이 테스트만 RED."""
    meta = _owner_table_meta()
    assert (
        _uncovered_owner_tables(
            meta, planned=_NONE, elsewhere=frozenset({"student_note_tbl"}), exemptions=_NONE
        )
        == frozenset()
    )


def test_exemption_clause_alone_covers_an_owner_table() -> None:
    """절 ③ 반례 — 사유 있는 제외에만 있는 테이블. `- exemptions`를 지우면 이 테스트만 RED."""
    meta = _owner_table_meta()
    assert (
        _uncovered_owner_tables(
            meta, planned=_NONE, elsewhere=_NONE, exemptions=frozenset({"student_note_tbl"})
        )
        == frozenset()
    )


def test_coverage_is_by_exact_table_name_not_by_prefix() -> None:
    """근접 이름 함정 — `student_note_tbl_v2`를 덮었다고 `student_note_tbl`까지 덮이면 안 된다."""
    meta = _owner_table_meta()
    assert _uncovered_owner_tables(
        meta, planned=frozenset({"student_note_tbl_v2"}), elsewhere=_NONE, exemptions=_NONE
    ) == frozenset({"student_note_tbl"})


@pytest.mark.parametrize(
    ("reason", "flagged"),
    [
        ("", True),  # 빈 사유
        ("   \n\t ", True),  # 공백뿐 — `if reason:` 같은 truthiness 검사는 이것을 통과시킨다
        ("짧은 사유", True),  # 형식적으로 짧음
        ("a" * (_MIN_REASON_LENGTH - 1), True),  # 경계 −1
        ("a" * _MIN_REASON_LENGTH, False),  # 경계 정확히
        ("  " + "a" * _MIN_REASON_LENGTH + "  ", False),  # 앞뒤 공백은 길이에 안 센다
    ],
)
def test_unreasoned_helper_boundaries(reason: str, flagged: bool) -> None:
    """무사유 판정의 경계 — 공백뿐인 사유와 길이 경계(⑤ '제외 목록 사유 비움 → RED'의 판정기)."""
    assert (_unreasoned({"tbl": reason}) == ["tbl"]) is flagged


def test_session_exclusion_is_inherited_and_load_bearing_for_retention() -> None:
    """(C) 제외가 보존 가드에도 상속된다 — 검수자 세션 테이블은 소유가 아니고, 그 제외가 일을 한다.

    ① 현행: `review_timer_event`(`review_session_id`)는 소유가 아니므로 계획·제외 어디에도 없이
       초록이다. ② 제외를 걷으면 그 테이블이 *미덮임*으로 잡힌다 — (C) 이름 절에 실제로 닿는다는
       증명(닿지 않는데 제외를 둔 유령 제외가 아니다).
    """
    metadata = _real_metadata()
    args = {
        "planned": _planned_tables(),
        "elsewhere": frozenset(_PURGED_ELSEWHERE),
        "exemptions": frozenset(_RETENTION_PLAN_EXEMPTIONS),
    }
    assert "review_timer_event" not in _uncovered_owner_tables(metadata, **args)
    assert "review_timer_event" in _uncovered_owner_tables(metadata, **args, session_exclusions={})


# ===========================================================================
# 4테이블 처분 핀(acceptance ②) — 판정 기준 main `a05eb49a`
# ===========================================================================

_ADDED_TO_PLAN = {
    "evidence_event": "time",
    "learning_state_transition": "occurred_at",
    "job_ownership": "created_at",
}


@pytest.mark.parametrize(("table", "column"), sorted(_ADDED_TO_PLAN.items()))
def test_sec41_added_tables_are_planned_on_a_not_null_column(table: str, column: str) -> None:
    """편입 3건 — 계획에 있고 기준 컬럼이 NOT NULL이라 NULL-미파기 잔존이 없다."""
    plan_columns = {model.__tablename__: col for model, col in _RETENTION_PLAN}
    assert plan_columns.get(table) == column, f"{table}이 계획에 {column} 기준으로 없다."
    metadata = _real_metadata()
    assert metadata.tables[table].columns[column].nullable is False, (
        f"{table}.{column}이 NULL을 허용한다 — NULL 행은 `ts < cutoff`가 NULL이라 영원히 안 "
        "지워진다(retention.py 「정직 스코프」). NOT NULL로 되돌리거나 폴백 기준을 설계하라."
    )
    assert table not in _RETENTION_PLAN_EXEMPTIONS, f"{table}이 계획과 제외에 모두 있다."


def test_sec41_learner_state_is_a_reasoned_temporary_exemption_pending_counsel() -> None:
    """`learner_state` — 계획 밖(현재값)·임시 제외·MGMT-02 대기. 제3 상태(무사유) 없음."""
    assert "learner_state" not in _planned_tables(), (
        "learner_state가 계획에 편입됐다 — `updated_at`은 '마지막 활동'이 아니라 변경 시각이라 "
        "활동 중인 학생의 현재 상태 행이 지워진다. 편입하려면 제외 사유를 반박하고 항목을 걷어라."
    )
    assert _RETENTION_PLAN_EXEMPTION_EXPIRY.get("learner_state") == "MGMT-02"
    reason = _RETENTION_PLAN_EXEMPTIONS["learner_state"]
    for token in ("MGMT-02", "현재값", "updated_at", "erase_user"):
        assert token in reason, f"learner_state 제외 사유에 {token!r}이(가) 없다."


def test_sec41_evidence_event_retention_until_is_an_unused_reserved_column() -> None:
    """④ 판정의 사실 기반 — 파기는 `time` 기준이고 `retention_until`은 읽지도 채워지지도 않는다.

    모델 docstring이 "retention.py 소관"이라 적던 것을 "예약 컬럼"으로 정정한 근거다. 이 두 사실
    중 하나가 깨지면(누가 `retention_until`을 채우기 시작하거나 파기가 읽기 시작하면) 정정한
    서술이 다시 거짓이 되므로 RED로 재판정을 강제한다 — 그때는 `_purge_condition`이 행별 만료일을
    존중하도록 확장할지(또는 컬럼을 폐기할지) 결정하라.
    """
    where = str(_purge_condition(EvidenceEvent, "time", date(2026, 1, 1)))
    assert "evidence_event.time" in where and "retention_until" not in where, where

    writer_calls = 0
    for path in sorted(_SRC_ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "EvidenceEvent(" not in text:
            continue
        for node in ast.walk(ast.parse(text)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "EvidenceEvent"
            ):
                writer_calls += 1
                filled = [kw.arg for kw in node.keywords if kw.arg == "retention_until"]
                assert filled == [], (
                    f"{path.relative_to(_REPO_ROOT)}:{node.lineno}가 retention_until을 채운다 — "
                    "파기가 아직 읽지 않으므로 값이 있어도 무시된다(작동 신호 없는 알고리즘). "
                    "행별 만료일을 파기가 존중하게 하거나 이 채움을 걷어라."
                )
    assert writer_calls >= 3, (
        f"EvidenceEvent writer를 {writer_calls}곳만 찾았다 — 스캔이 공허하다(기대 3곳 이상: "
        "pedagogy_evidence 2·recommendation_evidence 1)."
    )
