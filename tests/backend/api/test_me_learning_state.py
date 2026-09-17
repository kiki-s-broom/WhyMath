"""`/v1/me/learning-state`(EOS-105) — 학습 상태 표면 계약 (hermetic·FakeSession).

이 파일이 지키는 것은 **표면 계약**이다: 인증 스코프·직렬화 모양·미정의 전이의 409 거부·
정책 소유 트리거의 422 거부·전이 규칙을 클라에 복제하지 않게 하는 `allowed_next_states`.
전이표와 정책 규칙의 *의미*는 `tests/backend/l2/test_learning_state_machine.py`가 본다.

추가로 **배선 실재성**을 AST로 동결한다(축 ⑤). "저장소에 존재함"과 "서빙 경로가 부른다"는
다르다 — `submit_attempt`가 상태 머신을 실제로 호출하는지, 응답 모델에 상태 블록이 필수
필드로 있는지를 기계가 판정한다(CLAUDE.md "정본화를 집행으로 착각한 완료 선언 금지").
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from whymath_backend.api._auth import get_consented_user
from whymath_backend.api.me import (
    _POLICY_OWNED_TRIGGERS,
    AttemptSubmitResponse,
    LearningStateBlock,
)
from whymath_backend.app import create_app
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.schema.enums import Persona
from whymath_backend.schema.learning_state import (
    LearningState,
    TransitionTrigger,
    allowed_targets,
)
from whymath_backend.schema.user import UserProfile as UserProfileSchema

_UID = uuid.uuid4()
_T0 = datetime(2026, 9, 16, 9, 0, tzinfo=UTC)

_ME_SOURCE = (
    pathlib.Path(__file__).resolve().parents[3]
    / "src"
    / "backend"
    / "whymath_backend"
    / "api"
    / "me.py"
)


def _consented_user() -> UserProfile:
    return UserProfile.from_schema(
        UserProfileSchema(user_id=_UID, persona_primary=Persona.A_일반고고3)
    )


@dataclass
class _TransitionRow:
    from_state: LearningState
    to_state: LearningState
    trigger: TransitionTrigger
    occurred_at: datetime
    rule_id: str | None = None
    concept_id: str | None = None
    transition_id: uuid.UUID = field(default_factory=uuid.uuid4)
    user_id: uuid.UUID = _UID
    attempt_id: uuid.UUID | None = None


class _Scalars:
    """`.scalars()`의 결과 — 행 객체를 그대로 돌려준다(튜플로 감싸지 않는다)."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)


class FakeSession:
    """전이 원장을 리스트로 흉내 낸다.

    `get_current_state`는 스칼라 1건을, `list_transitions`는 행 목록을 기대하므로 같은
    `_Result`가 둘 다 만족하도록 만든다(질의를 구분하지 않는 대신 호출 순서에 기대지 않는다).
    """

    def __init__(self, rows: list[_TransitionRow] | None = None) -> None:
        self.rows = list(rows or [])
        self.added: list[Any] = []
        self.committed = 0

    async def execute(self, stmt: Any) -> _Result:
        ordered = sorted(self.rows, key=lambda r: r.occurred_at, reverse=True)
        # `select(LearningStateTransition.to_state)` = 현재 상태 조회(스칼라 1건).
        rendered = str(stmt)
        if "learning_state_transition.to_state" in rendered and "FROM" in rendered:
            columns = rendered.split("FROM")[0]
            if "transition_id" not in columns:
                return _Result([ordered[0].to_state] if ordered else [])
        return _Result(ordered)

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        self.rows.append(
            _TransitionRow(
                from_state=obj.from_state,
                to_state=obj.to_state,
                trigger=obj.trigger,
                occurred_at=datetime.now(UTC),
                rule_id=obj.rule_id,
                concept_id=obj.concept_id,
            )
        )

    async def commit(self) -> None:
        self.committed += 1


def _client(session: FakeSession) -> TestClient:
    app = create_app()

    async def _fake_session() -> AsyncIterator[Any]:
        yield session

    app.dependency_overrides[get_session] = _fake_session
    app.dependency_overrides[get_consented_user] = _consented_user
    return TestClient(app)


# ──────────────────────────────────────────────────────────────────────────
# 조회 표면
# ──────────────────────────────────────────────────────────────────────────


def test_new_learner_reads_as_new_with_diagnosing_as_the_only_next_step() -> None:
    """이력이 없는 학생은 `NEW`이고, 갈 수 있는 곳은 `DIAGNOSING` 하나다."""
    with _client(FakeSession()) as client:
        resp = client.get("/v1/me/learning-state")
    assert resp.status_code == 200
    body = resp.json()
    assert body["current_state"] == "NEW"
    assert body["allowed_next_states"] == ["DIAGNOSING"]
    assert body["transitions"] == []


def test_allowed_next_states_mirrors_the_server_transition_table() -> None:
    """서버가 내려 주는 후보가 전이표와 정확히 일치한다.

    클라이언트가 전이 규칙을 자기 코드에 복제하지 않게 하는 것이 이 필드의 목적이다 —
    복제하면 규칙의 진실 원천이 둘(서버 표 + 클라 분기)이 된다.
    """
    rows = [
        _TransitionRow(
            from_state=LearningState.NEW,
            to_state=LearningState.DIAGNOSING,
            trigger=TransitionTrigger.DIAGNOSIS_STARTED,
            occurred_at=_T0,
        )
    ]
    with _client(FakeSession(rows)) as client:
        body = client.get("/v1/me/learning-state").json()
    assert body["current_state"] == "DIAGNOSING"
    assert body["allowed_next_states"] == sorted(
        s.value for s in allowed_targets(LearningState.DIAGNOSING)
    )


def test_transition_history_exposes_why_not_just_what() -> None:
    """이력 행에 `trigger`·`rule_id`가 실린다 — "왜 이 상태인가"의 재구성 자료."""
    rows = [
        _TransitionRow(
            from_state=LearningState.ASSESSING,
            to_state=LearningState.REMEDIATING,
            trigger=TransitionTrigger.POLICY_REMEDIATE_MISCONCEPTION,
            occurred_at=_T0,
            rule_id="R3-wrong-misconception",
            concept_id="C-frac-01",
        )
    ]
    with _client(FakeSession(rows)) as client:
        body = client.get("/v1/me/learning-state").json()
    [row] = body["transitions"]
    assert row["from_state"] == "ASSESSING"
    assert row["to_state"] == "REMEDIATING"
    assert row["trigger"] == "POLICY_REMEDIATE_MISCONCEPTION"
    assert row["rule_id"] == "R3-wrong-misconception"
    assert row["concept_id"] == "C-frac-01"


def test_learning_state_surface_has_no_slot_for_another_users_id() -> None:
    """타인 조회 경로가 **구조적으로 없다** — 경로·쿼리 어디에도 user_id 슬롯이 없다.

    학습 상태는 미성년 학습자의 학습 국면 기록이다(CLAUDE.md 미성년 PII 외부 노출 금기).
    """
    # 라우터가 지연 포함(`_IncludedRouter`)되므로 `app.routes`가 아니라 **공개 계약**인
    # OpenAPI 스키마를 본다 — 어차피 외부에 드러나는 표면이 판정 대상이다.
    with _client(FakeSession()) as client:
        schema = client.get("/openapi.json").json()
    paths = [p for p in schema["paths"] if "learning-state" in p]
    assert paths, "learning-state 라우트를 찾지 못했습니다"
    for path in paths:
        assert "{user_id}" not in path and "{learner_id}" not in path
    # 쿼리 파라미터에도 타인 지목 슬롯이 없다 — 경로만 막고 쿼리를 열어 두는 실수를 잡는다.
    for path in paths:
        for operation in schema["paths"][path].values():
            names = {param["name"] for param in operation.get("parameters", [])}
            assert not (
                names & {"user_id", "learner_id", "student_id"}
            ), f"{path}에 타인 지목 쿼리 파라미터가 있습니다: {names}"


# ──────────────────────────────────────────────────────────────────────────
# 적재 표면 — 거부는 200 + 플래그가 아니라 상태코드다
# ──────────────────────────────────────────────────────────────────────────


def test_lifecycle_transition_is_recorded_and_advances_the_state() -> None:
    session = FakeSession()
    with _client(session) as client:
        resp = client.post(
            "/v1/me/learning-state/transitions",
            json={"to_state": "DIAGNOSING", "trigger": "DIAGNOSIS_STARTED"},
        )
    assert resp.status_code == 201
    assert resp.json()["current_state"] == "DIAGNOSING"
    assert len(session.added) == 1
    assert session.added[0].from_state is LearningState.NEW


def test_undefined_transition_is_rejected_with_409_not_a_success_flag() -> None:
    """미정의 전이는 409다 — 200에 "실패했음" 플래그를 실어 보내지 않는다.

    플래그 형태는 호출부가 그것을 안 읽는 순간 조용한 통과가 된다. 상태코드는 못 본 척하기가
    훨씬 어렵다.
    """
    session = FakeSession()
    with _client(session) as client:
        resp = client.post(
            "/v1/me/learning-state/transitions",
            json={"to_state": "ADVANCING", "trigger": "ADVANCE_COMPLETED"},
        )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    # 예외 타입명이 detail에 들어간다(CLAUDE.md 무타입 경고 금지).
    assert "UndefinedTransitionError" in detail
    assert "DIAGNOSING" in detail  # 무엇이 가능한지 알려 준다
    assert session.added == [], "거부된 전이가 적재됐습니다"


@pytest.mark.parametrize("trigger", sorted(t.value for t in _POLICY_OWNED_TRIGGERS))
def test_policy_owned_triggers_cannot_be_posted_by_the_client(trigger: str) -> None:
    """정책 소유 트리거는 클라이언트가 적재할 수 없다 — 422.

    허용하면 클라이언트가 정책을 우회해 임의 상태로 점프한다(예: 오답인데
    `POLICY_ADVANCE`를 직접 던져 진급).
    """
    session = FakeSession(
        [
            _TransitionRow(
                from_state=LearningState.NEW,
                to_state=LearningState.DIAGNOSING,
                trigger=TransitionTrigger.DIAGNOSIS_STARTED,
                occurred_at=_T0,
            )
        ]
    )
    with _client(session) as client:
        resp = client.post(
            "/v1/me/learning-state/transitions",
            json={"to_state": "READY", "trigger": trigger},
        )
    assert resp.status_code == 422
    assert session.added == []


def test_policy_owned_trigger_set_covers_every_policy_trigger() -> None:
    """트리거를 추가하고 차단 목록을 잊으면 RED — 이름 규약에 기대지 않는다.

    `startswith("POLICY_")` 같은 접두사 판정은 리팩터링으로 조용히 깨지고, 그때 이 게이트도
    함께 열린다. 열거된 집합 + 이 대조가 그 실패 모드를 막는다.
    """
    by_name = {t for t in TransitionTrigger if t.name.startswith("POLICY_")}
    assert (
        by_name | {TransitionTrigger.ATTEMPT_SUBMITTED} == _POLICY_OWNED_TRIGGERS
    ), "정책 소유 트리거를 추가했다면 api/me.py::_POLICY_OWNED_TRIGGERS에도 넣으십시오."


# ──────────────────────────────────────────────────────────────────────────
# 배선 실재성 — "존재함" ≠ "서빙 경로가 부른다"
# ──────────────────────────────────────────────────────────────────────────


def test_submit_attempt_actually_calls_the_state_machine() -> None:
    """`submit_attempt` 본문이 `advance_on_attempt`를 호출한다 — AST 판정.

    이 가드가 없으면 상태 머신 모듈·전이표·정책이 전부 존재하는데 **아무 학생의 상태도
    움직이지 않는** 상태가 통과한다(CLAUDE.md "정본화를 집행으로 착각한 완료 선언 금지" ·
    PED-06 선례).
    """
    tree = ast.parse(_ME_SOURCE.read_text(encoding="utf-8"))
    handlers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "submit_attempt"
    ]
    assert len(handlers) == 1, f"submit_attempt 핸들러를 찾지 못했습니다(실측 {len(handlers)}개)"

    called = {
        node.func.id
        for node in ast.walk(handlers[0])
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "advance_on_attempt" in called, "서빙 경로가 상태 머신을 부르지 않습니다"
    assert "build_attempt_evidence" in called, "서빙 경로가 증거를 조립하지 않습니다"


def test_attempt_response_carries_the_state_block_as_a_required_field() -> None:
    """응답의 `learning_state`가 **필수**다 — Optional이면 조용히 빠져도 아무도 모른다."""
    field = AttemptSubmitResponse.model_fields["learning_state"]
    assert field.is_required(), "learning_state가 선택 필드입니다 — 누락이 관측되지 않습니다"
    assert field.annotation is LearningStateBlock


def test_state_block_can_carry_a_rejection_without_a_decision() -> None:
    """거부 블록의 모양 — 결정은 없고 거부 설명만 있다.

    "결정이 없었다"와 "결정이 났는데 못 적재했다"를 같은 값으로 접지 않는다.
    """
    block = LearningStateBlock(
        from_state=LearningState.NEW,
        to_state=LearningState.NEW,
        rejected_transition="NEW → ASSESSING (UndefinedTransitionError)",
    )
    assert block.rule_id is None
    assert block.next_action is None
    assert block.rejected_transition is not None
