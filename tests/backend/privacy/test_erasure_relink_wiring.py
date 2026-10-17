"""SEC-40 — `evidence_event` 삭제 배선의 hermetic 동결(DB 없음).

실 PG 통합(`test_erasure_relink_integration.py`)이 *결과*를 재는 반면, 이 파일은 DB 없이도 항상
도는 **구조·순서** 검사다 — 통합이 skip된 환경에서도 배선 제거가 RED로 드러나게 한다.

  ① 계획 편입 — `evidence_event`가 `_ERASURE_PLAN`·`_SESSION_AXIS_MODELS`에 있고 SEC-39 임시 예외
     (허용목록·만료 맵)에서는 걷혀 있다.
  ② 순서 — `erase_user`가 세션 ID 수집 SELECT를 `learning_session` 삭제보다 **먼저** 보낸다
     (세션 행이 지워진 뒤에는 학습 세션 ID를 모을 수 없다).
  ③ 시그니처 — `settings`가 필수다(비밀키 없이 호출해 HMAC 갈래가 조용히 빠지는 것을 막는다).
  ④ 개별 세션 삭제 경로 — `_delete_owned_resource`가 LearningSession일 때만 증빙 삭제 문을 보내고,
     그 문이 세션 행 삭제보다 앞선다. 대화·진단 삭제는 증빙에 손대지 않는다.
"""

from __future__ import annotations

import asyncio
import inspect
import uuid
from typing import Any, cast

from pydantic import SecretStr
from sqlalchemy import Delete, Select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.api import me as me_api
from whymath_backend.config import Settings
from whymath_backend.db.models.activity import LearningSession
from whymath_backend.db.models.assessment import Assessment
from whymath_backend.db.models.dialogue import Dialogue
from whymath_backend.db.models.evidence_event import EvidenceEvent
from whymath_backend.privacy.erasure import (
    _ERASURE_PLAN,
    _ERASURE_PLAN_EXEMPTION_EXPIRY,
    _ERASURE_PLAN_EXEMPTIONS,
    _SESSION_AXIS_MODELS,
    erase_user,
)
from whymath_backend.schema.enums import AuditResourceType


def _settings() -> Settings:
    return Settings(jwt_secret_key=SecretStr("wiring-secret-0123456789abcdef"))


class _EmptySelect:
    def scalars(self) -> _EmptySelect:
        return self

    def all(self) -> list[Any]:
        return []


class _Result:
    rowcount = 1


class _RecordingSession:
    """실행 순서(SELECT/DELETE 대상 테이블)를 기록한다. SELECT는 빈 결과."""

    def __init__(self) -> None:
        self.log: list[tuple[str, str]] = []
        self._row: Any = None

    async def execute(self, stmt: Any) -> Any:
        if isinstance(stmt, Select):
            self.log.append(("select", str(stmt.get_final_froms()[0].name)))
            return _EmptySelect()
        assert isinstance(stmt, Delete)
        self.log.append(("delete", stmt.table.name))
        return _Result()

    def add(self, obj: Any) -> None:
        self.log.append(("add", type(obj).__name__))

    async def flush(self) -> None:
        return None

    # --- `_delete_owned_resource`용 ---
    async def get(self, model: Any, pk: Any) -> Any:
        return self._row

    async def delete(self, row: Any) -> None:
        self.log.append(("orm_delete", type(row).__name__))

    async def commit(self) -> None:
        self.log.append(("commit", ""))


def test_evidence_event_is_in_plan_and_no_longer_exempted() -> None:
    """① SEC-39 임시 예외가 걷히고 계획에 편입됐다 — 제3 상태(둘 다/둘 다 아님) 없음."""
    planned = {m.__tablename__: c for m, c in _ERASURE_PLAN}
    assert planned.get("evidence_event") == "session_id"
    assert EvidenceEvent in _SESSION_AXIS_MODELS
    assert "evidence_event" not in _ERASURE_PLAN_EXEMPTIONS
    assert "evidence_event" not in _ERASURE_PLAN_EXEMPTION_EXPIRY


def test_session_axis_models_are_all_planned_with_a_session_column() -> None:
    """세션 축 모델이 계획에 없거나 세션 컬럼이 아니면 `== user_id`로 오삭제·무삭제된다."""
    planned = {m: c for m, c in _ERASURE_PLAN}
    assert _SESSION_AXIS_MODELS, "세션 축 모델이 0건이다 — 이 검사가 공허해졌다."
    for model in _SESSION_AXIS_MODELS:
        assert model in planned, f"{model.__tablename__}이 _ERASURE_PLAN에 없다."
        assert planned[model] == "session_id" or planned[model].endswith("_session_id")


def test_session_ids_are_collected_before_learning_session_is_deleted() -> None:
    """② 세션 ID 수집 SELECT가 `learning_session` 삭제보다 앞선다(조인 근거 소실 방지)."""
    session = _RecordingSession()
    asyncio.run(erase_user(cast(AsyncSession, session), user_id=uuid.uuid4(), settings=_settings()))
    log = session.log
    first_session_select = next(
        i for i, (k, t) in enumerate(log) if k == "select" and t == "learning_session"
    )
    session_delete = next(
        i for i, (k, t) in enumerate(log) if k == "delete" and t == "learning_session"
    )
    evidence_delete = next(
        i for i, (k, t) in enumerate(log) if k == "delete" and t == "evidence_event"
    )
    assert first_session_select < session_delete
    # 바인딩 재계산용 evidence_event 읽기도 학습 세션 삭제 전에 끝난다.
    binding_read = next(
        i for i, (k, t) in enumerate(log) if k == "select" and t == "evidence_event"
    )
    assert binding_read < session_delete
    # 증빙 삭제 문은 반드시 실행된다(수집 결과가 비어도 한 번은 — 호출 누락 위장 방지).
    assert evidence_delete >= 0


def test_erase_user_requires_settings() -> None:
    """③ `settings` 키워드가 필수다 — 기본값이 있으면 비밀키 없이 호출해도 조용히 통과한다."""
    param = inspect.signature(erase_user).parameters["settings"]
    assert param.default is inspect.Parameter.empty
    assert param.kind is inspect.Parameter.KEYWORD_ONLY


def _delete_resource_log(model: Any, resource: AuditResourceType) -> list[tuple[str, str]]:
    session = _RecordingSession()
    uid = uuid.uuid4()
    pk = uuid.uuid4()

    class _Row:
        user_id = uid

    session._row = _Row()
    asyncio.run(
        me_api._delete_owned_resource(cast(AsyncSession, session), model, pk, uid, resource, "없음")
    )
    return session.log


def test_session_delete_removes_evidence_before_the_session_row() -> None:
    """④ 개별 세션 삭제 — 증빙 DELETE가 세션 행 삭제보다 앞서고 같은 commit 하나로 끝난다."""
    log = _delete_resource_log(LearningSession, AuditResourceType.learning_session)
    evidence = next(i for i, (k, t) in enumerate(log) if k == "delete" and t == "evidence_event")
    row_delete = next(i for i, (k, _) in enumerate(log) if k == "orm_delete")
    assert evidence < row_delete
    assert [k for k, _ in log].count("commit") == 1
    assert log.index(("commit", "")) > row_delete


def test_dialogue_and_assessment_deletes_do_not_touch_evidence() -> None:
    """④ 대조 — 증빙은 학습 세션 축 데이터라 대화·진단 삭제에서는 건드리지 않는다."""
    for model, resource in (
        (Dialogue, AuditResourceType.dialogue),
        (Assessment, AuditResourceType.assessment),
    ):
        log = _delete_resource_log(model, resource)
        assert ("delete", "evidence_event") not in log
