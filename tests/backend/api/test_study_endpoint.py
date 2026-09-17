"""학습 공급 엔드포인트 HTTP 관통 — `POST /v1/me/objectives/{id}/study`·`/outcome` (MOB-13).

`api/study.py` 모듈 docstring은 "이 라우터가 그 사슬을 학생 요청에 연결한다"고 현재형으로
서술하지만, OPS-22 `declared_unwired_audit` 실측(2026-08-09) 결과 **그 요청을 실제로 보내는
쪽이 어디에도 없었다** — 기존 `test_study_integration.py`는 `record_pedagogy_treatment`/
`record_pedagogy_outcome`을 *함수로 직접* 호출할 뿐 라우터를 경유하지 않는다. 즉 라우팅·의존성
주입(`ConsentedUser`·`SessionDep`·`get_cache`)·요청/응답 스키마·상태코드는 한 번도 실행된 적이
없는 구간이었다.

이 파일이 그 구간을 HTTP로 관통한다(hermetic — 실 PG·LLM·네트워크 0):

  ① `/study` 201 — 라우팅·DI·`supply()` 호출 인자·처치 기록·응답 직렬화
  ② `/outcome` 201 — `/study`가 준 `session_id`를 되돌려 보내 결과 행이 같은 축으로 묶이는지
  ③ 목표 없음 404 · 개념 미연결 404 · 렌더 불가 404 — 정직한 에러 구분(500이 아니다)
  ④ 무토큰 401 — 학생 스코프 보호

**정직 표기**: 이것은 *도달 증명*이지 학생 앱 배선이 아니다. Flutter 학습 화면이 이 두 경로를
부르는 것은 아직 없다(MOB-13 acceptance가 "학생 학습 화면 **또는** 최소 HTTP 관통 통합테스트"를
둘 다 인정해 후자를 택했다). 실 PG 왕복 축은 `test_study_integration.py`가 계속 담당한다.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from whymath_backend.api import study as study_module
from whymath_backend.api._auth import get_consented_user
from whymath_backend.app import create_app
from whymath_backend.db.models.evidence_event import EvidenceEvent
from whymath_backend.db.models.learner_state import LearnerStateRecord
from whymath_backend.db.models.pedagogy_dsl import LearningObjective
from whymath_backend.db.session import get_session
from whymath_backend.l3.render.adapter import RenderedUnit, RenderSegment
from whymath_backend.l4.content_supply import SupplyResult
from whymath_backend.l4.pedagogy.runtime_selector import StudentSignals
from whymath_backend.schema.enums import KnowledgeType, PedagogyStrategy

_OBJECTIVE_ID = "obj-mob13"
_CONCEPT_CODE = "math.calculus.limit"

_USER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")

# 경로는 호출부에 **리터럴로 인라인**한다(상수로 묶지 않는다). OPS-22 감사기의 도달 판정은
# `.post("/v1/...")` 형태의 리터럴만 잡고 상수 경유 호출은 못 본다(대장에 명시된 알려진 정밀도
# 한계 — `POST /v1/ocr/pages` 항목이 같은 이유로 by-design 처리돼 있다). 여기서 상수를 쓰면
# 테스트가 실제로 라우터를 때리는데도 감사기에는 "미도달"로 남아, 이 태스크가 없애려는 바로 그
# 신호를 다시 만든다. 중복 문자열 4곳의 비용보다 도달 가시성이 크다.


class _User:
    """`ConsentedUser`가 반환하는 최소 표면 — 라우터는 `user_id`만 읽는다."""

    user_id = _USER_ID


async def _user() -> _User:
    return _User()


class _StagedScalars:
    """`add()`로 적재된 행 중 select 조건에 맞는 것들 — `.first()`/`.all()`만 제공."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows

    def first(self) -> Any:
        return self._rows[0] if self._rows else None


class _StagedResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _StagedScalars:
        return _StagedScalars(self._rows)

    def all(self) -> list[Any]:
        return self._rows

    def scalar(self) -> int:
        return len(self._rows)

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None

    def first(self) -> Any:
        return self._rows[0] if self._rows else None


class _FakeSession:
    """`session.get`/`add`/`commit` + **EvidenceEvent select만** 대역 실행(test_me.py 동형 확장).

    대부분의 stmt는 여전히 무시하고 빈 행셋을 준다 — `_build_signals`가 부르는 `get_state()`가
    "신규 학생"(숙달 신호 없음) 경로를 타는 것이 라우터의 정상 분기라 그것으로 충분하다.

    **SEC-24(원 SEC-16) 이후 확장 이유**: `/outcome`의 유일 writer(`record_pedagogy_outcome`)가
    stage 전에 ①처치 행 조회(소유권) ②중복 outcome 조회를 *실제로 실행*한다. 예전처럼 모든
    select에 빈 결과를 주면 `/study`가 방금 남긴 처치 행을 못 찾아 정당한 소유자도 403이 된다 —
    즉 이 대역이 실 DB의 "add한 행은 이후 select에 보인다"를 모델링하지 못하는 것이 원인이지,
    라우터·writer의 결함이 아니다. 그래서 EvidenceEvent select에 한해 `self.added`를
    stmt의 바인딩 파라미터(session_id·objective_id·event_type)로 걸러 돌려준다.
    """

    def __init__(self, get_map: dict[Any, Any] | None = None) -> None:
        self._get_map = get_map or {}
        self.added: list[Any] = []
        self.commits = 0

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    @staticmethod
    def _selects_evidence_event(stmt: Any) -> bool:
        descriptions = getattr(stmt, "column_descriptions", None) or []
        return any(desc.get("entity") is EvidenceEvent for desc in descriptions)

    def _matching_evidence_rows(self, stmt: Any) -> list[Any]:
        """stmt의 바인딩 값으로 staged EvidenceEvent를 필터 — WHERE를 값 대조로 근사한다.

        파라미터 *이름*(`session_id_1` 등)에 의존하지 않고 **값 집합 포함 여부**로 본다 —
        SQLAlchemy가 붙이는 접미사가 바뀌어도 깨지지 않는다.
        """
        values = set(getattr(stmt, "compile", lambda: None)().params.values())
        rows = []
        for row in self.added:
            if not isinstance(row, EvidenceEvent):
                continue
            if row.session_id not in values:
                continue
            if row.objective_id not in values:
                continue
            if row.event_type not in values:
                continue
            rows.append(row)
        return rows

    async def execute(self, stmt: Any) -> Any:
        if self._selects_evidence_event(stmt):
            return _StagedResult(self._matching_evidence_rows(stmt))
        return _EmptyResult()

    async def get(self, model: Any, pk: Any) -> Any:
        """PK 단건 조회 — **모델까지 보고** 돌려준다.

        EOS-103 이후 라우터가 같은 요청에서 두 모델을 PK로 찾는다(`LearningObjective` /
        `LearnerStateRecord`). pk만 키로 쓰면 학생 id와 목표 id가 우연히 겹치지 않는 한
        동작하지만, *모델이 다른데 같은 맵을 뒤지는* 대역은 실 DB를 모델링하지 못한다 —
        조회 대상이 하나 더 늘 때마다 조용히 틀린 행을 돌려줄 수 있다.
        """
        return self._get_map.get((model, pk), self._get_map.get(pk))

    async def commit(self) -> None:
        self.commits += 1


class _EmptyScalars:
    def all(self) -> list[Any]:
        return []

    def first(self) -> None:
        return None


class _EmptyResult:
    def scalars(self) -> _EmptyScalars:
        return _EmptyScalars()

    def all(self) -> list[Any]:
        return []

    def scalar(self) -> int:
        return 0

    def scalar_one_or_none(self) -> None:
        return None

    def first(self) -> None:
        return None


def _objective(concept_nodes: list[str] | None = None) -> LearningObjective:
    """`k_type`(팩 축)·`concept_nodes`(원자 code)가 라우터가 읽는 두 축이다.

    `k_type`은 **enum 멤버**로 둔다 — ORM이 `Mapped[KnowledgeType]`이라 실제 DB에서 읽어온
    objective는 항상 멤버다. 예전엔 여기서 평문 `"CONCEPT"`을 썼는데, 그 불일치가
    `str(objective.k_type)` 결함을 *fake에서만 통과시켜* 실 PG 잡에서야 드러나게 했다
    (2026-08-11 SEC-24 회수 실측). fake가 실물과 다르면 검출기가 아니라 위장이 된다.
    """
    return LearningObjective(
        id=_OBJECTIVE_ID,
        unit_id="unit-mob13",
        unit_version=1,
        statement="테스트 학습목표",
        achievement_std="[9수02-01]",
        k_type=KnowledgeType.CONCEPT,
        concept_nodes=[_CONCEPT_CODE] if concept_nodes is None else concept_nodes,
        slot_manifest={},
        exit_evidence={},
    )


def _supply_result(rendered: bool = True) -> SupplyResult:
    """`supply()`가 돌려주는 형태 — 렌더 성공(dsl_render) 또는 렌더 불가(rendered=None)."""
    unit = (
        RenderedUnit(
            strategy=PedagogyStrategy.SOCRATIC,
            dsl_code=_CONCEPT_CODE,
            segments=(
                RenderSegment(kind="question", content=r"$\lim_{x\to 0}$ 는 무엇을 묻고 있을까?"),
            ),
        )
        if rendered
        else None
    )
    return SupplyResult(
        content_source="dsl_render",
        strategy=PedagogyStrategy.SOCRATIC,
        rendered=unit,
        gate_reason_code=None,
    )


_DEFAULT = object()  # "미지정"과 "명시적 None(목표 없음)"을 구분하는 센티널.


def _learner_state() -> LearnerStateRecord:
    """진단을 완료한 학생의 LearnerState 행 — EOS-103 루프 진입 게이트의 통과 조건.

    이 대역이 없으면 `/study`가 409(진단 미완)로 막힌다. 그것이 정상 동작이며, 막히는 쪽의
    검증은 `TestStudyRequiresLearnerState`가 따로 한다.
    """
    now = datetime(2026, 9, 1, tzinfo=UTC)
    return LearnerStateRecord(
        learner_id=_USER_ID,
        curriculum_id=None,
        current_objective_id=None,
        provisioned_at=now,
        provisioned_by="diagnosis_capture",
        updated_at=now,
        revision=1,
    )


def _client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    objective: Any = _DEFAULT,
    result: SupplyResult | None = None,
    learner_state: Any = _DEFAULT,
) -> tuple[TestClient, _FakeSession, list[dict[str, Any]]]:
    """라우터를 HTTP로 때리는 hermetic 클라이언트.

    `supply()`만 대역으로 바꾼다 — 그 안쪽(선택·게이트·렌더)은 L4 자체 테스트가 검증하는 축이고,
    여기서 증명할 것은 *라우터가 그것을 실제로 부르는가*다. 호출 인자를 캡처해 라우터가 개념
    code·k_type을 올바로 넘기는지도 함께 본다(가짜 통과 방지).
    """
    calls: list[dict[str, Any]] = []

    async def _fake_supply(**kwargs: Any) -> SupplyResult:
        calls.append(kwargs)
        return result if result is not None else _supply_result()

    monkeypatch.setattr(study_module, "supply", _fake_supply)

    obj = _objective() if objective is _DEFAULT else objective
    state = _learner_state() if learner_state is _DEFAULT else learner_state
    get_map: dict[Any, Any] = {}
    if obj is not None:
        get_map[_OBJECTIVE_ID] = obj
    if state is not None:
        get_map[(LearnerStateRecord, _USER_ID)] = state
    fake = _FakeSession(get_map=get_map)

    app = create_app()
    app.dependency_overrides[get_consented_user] = _user

    async def _sess() -> AsyncIterator[_FakeSession]:
        yield fake

    app.dependency_overrides[get_session] = _sess
    return TestClient(app), fake, calls


class TestStudyEndpointReach:
    """`POST /{objective_id}/study` — 라우터 관통(도달 증명의 본체)."""

    def test_study_201_returns_rendered_unit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """201 + 응답 스키마 — 전략·공급경로·세그먼트가 그대로 직렬화된다."""
        client, fake, calls = _client(monkeypatch)
        resp = client.post("/v1/me/objectives/obj-mob13/study", json={})

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["objective_id"] == _OBJECTIVE_ID
        assert body["concept_code"] == _CONCEPT_CODE
        assert body["strategy"] == PedagogyStrategy.SOCRATIC.value
        assert body["content_source"] == "dsl_render"
        assert body["gate_reason_code"] is None
        assert [seg["kind"] for seg in body["segments"]] == ["question"]
        # session_id는 결과 기록 시 되돌려 보내야 하는 축 — UUID로 파싱돼야 한다.
        uuid.UUID(body["session_id"])
        # 처치가 실제로 stage되고 commit됐는가(가짜 처치 금지).
        assert fake.added, "처치 행이 stage되지 않았다"
        assert fake.commits >= 1

    def test_study_calls_supply_with_objective_axes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """라우터가 `supply()`에 개념 code·k_type·신호를 넘긴다 — 배선의 실체."""
        client, _fake, calls = _client(monkeypatch)
        assert client.post("/v1/me/objectives/obj-mob13/study", json={}).status_code == 201

        assert len(calls) == 1
        kwargs = calls[0]
        assert kwargs["code"] == _CONCEPT_CODE
        assert kwargs["k_type"] == "CONCEPT"
        assert isinstance(kwargs["signals"], StudentSignals)

    def test_study_404_when_objective_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """목표 없음 → 404(서버 결함이 아니라 데이터 상태)."""
        client, _fake, _calls = _client(monkeypatch, objective=None)
        assert client.post("/v1/me/objectives/obj-mob13/study", json={}).status_code == 404

    def test_study_404_when_no_concept_linked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """목표에 개념 미연결 → 404."""
        client, _fake, _calls = _client(monkeypatch, objective=_objective(concept_nodes=[]))
        assert client.post("/v1/me/objectives/obj-mob13/study", json={}).status_code == 404

    def test_study_404_when_render_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """렌더 불가(DSL 미적재) → 404이고 **처치를 기록하지 않는다**(가짜 처치 금지)."""
        client, fake, _calls = _client(monkeypatch, result=_supply_result(rendered=False))
        assert client.post("/v1/me/objectives/obj-mob13/study", json={}).status_code == 404
        assert fake.added == [], "학생이 아무것도 못 봤는데 처치가 기록됐다"


class TestOutcomeEndpointReach:
    """`POST /{objective_id}/outcome` — 처치와 같은 session_id로 결과를 잇는다."""

    def test_outcome_201_records(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """201 + `recorded=true` + 결과 행 stage.

        SEC-24(원 SEC-16) 계약 변경 수용: 임의 `session_id`로는 더 이상 201이 아니다(403) —
        `/outcome`은 `/study`가 *이 학생에게* 발급한 session_id만 받는다. 그래서 이 테스트는
        실제 클라이언트와 같은 순서로 `/study`를 먼저 호출해 정당한 session_id를 얻는다.
        위조·타인·중복 세션의 거부 축은 `test_study_outcome_ownership.py`가 담당한다.
        """
        client, fake, _calls = _client(monkeypatch)
        study = client.post("/v1/me/objectives/obj-mob13/study", json={})
        assert study.status_code == 201, study.text
        session_id = study.json()["session_id"]

        resp = client.post(
            "/v1/me/objectives/obj-mob13/outcome",
            json={"session_id": session_id, "correct": True, "rt_ms": 4200},
        )

        assert resp.status_code == 201, resp.text
        assert resp.json() == {"recorded": True}
        assert fake.added, "결과 행이 stage되지 않았다"
        assert fake.commits >= 1

    def test_study_then_outcome_share_session_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """관통 루프 — `/study`가 준 session_id를 `/outcome`이 그대로 받는다(집계 조인 축).

        SEC-24(원 SEC-16) 이후 이 축은 *집계 정합*이자 *인가 축*이다 — session_id가 어긋나면
        예전처럼 "행은 남되 집계 제외"가 아니라 403으로 **기입 자체가 거부**된다(고아 outcome이
        오염 벡터라 기입 거부로 승격). 두 호출이 같은 축으로 묶이는지가 이 슬라이스의 실질이다.
        """
        client, fake, _calls = _client(monkeypatch)
        study = client.post("/v1/me/objectives/obj-mob13/study", json={})
        assert study.status_code == 201
        session_id = study.json()["session_id"]

        outcome = client.post(
            "/v1/me/objectives/obj-mob13/outcome", json={"session_id": session_id, "correct": False}
        )
        assert outcome.status_code == 201
        # 처치 1행 + 결과 1행이 같은 세션 축으로 stage됐다.
        assert len(fake.added) == 2
        assert {str(getattr(row, "session_id", "")) for row in fake.added} == {session_id}

    def test_outcome_404_when_objective_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """목표 없음 → 404."""
        client, _fake, _calls = _client(monkeypatch, objective=None)
        resp = client.post(
            "/v1/me/objectives/obj-mob13/outcome",
            json={"session_id": str(uuid.uuid4()), "correct": True},
        )
        assert resp.status_code == 404

    def test_outcome_422_rejects_student_freeform(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """학생 원문 풀이 슬롯 부재(B1 구조적 차단) — extra 필드는 422로 거부된다."""
        client, _fake, _calls = _client(monkeypatch)
        resp = client.post(
            "/v1/me/objectives/obj-mob13/outcome",
            json={
                "session_id": str(uuid.uuid4()),
                "correct": True,
                "student_work": "x=1 이라고 풀었어요",
            },
        )
        assert resp.status_code == 422


class TestStudyAuthScope:
    """무토큰 401 — 학생 스코프 보호(의존성 override 없이 실 인증 경로)."""

    def test_endpoints_require_auth(self) -> None:
        app = create_app()

        async def _sess() -> AsyncIterator[_FakeSession]:
            yield _FakeSession()

        app.dependency_overrides[get_session] = _sess
        client = TestClient(app)

        assert client.post("/v1/me/objectives/obj-mob13/study", json={}).status_code == 401
        assert (
            client.post(
                "/v1/me/objectives/obj-mob13/outcome",
                json={"session_id": str(uuid.uuid4()), "correct": True},
            ).status_code
            == 401
        )


class TestStudyRequiresLearnerState:
    """EOS-103 루프 진입 게이트 — LearnerState 없이 들어오면 **명시적으로** 실패한다.

    이 클래스가 결함 주입 축이다. 나머지 테스트는 LearnerState 행이 *있는* 정상 상태를
    대역으로 깔고 돌아가므로 전부 초록이고, 그 초록은 게이트가 작동한다는 증거가 아니다
    (CLAUDE.md "보호 장치를 실패 주입 없이 '보호 있음'으로 선언 금지"). 여기서 그 행을
    **없애고** 라우터가 실제로 멈추는지를 본다.
    """

    def test_study_409_when_learner_state_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """진단 미완 학생의 `/study`는 201이 아니라 409다 — 조용한 기본값 진행 금지."""
        client, _fake, calls = _client(monkeypatch, learner_state=None)
        resp = client.post("/v1/me/objectives/obj-mob13/study", json={})
        assert resp.status_code == 409, resp.text
        assert "진단" in resp.json()["detail"]

    def test_supply_is_not_called_when_learner_state_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """게이트는 `supply()` **앞**에 선다 — 근거 0으로 고른 교수법이 학생에게 가지 않는다."""
        client, _fake, calls = _client(monkeypatch, learner_state=None)
        client.post("/v1/me/objectives/obj-mob13/study", json={})
        assert calls == [], f"게이트가 열려 supply()가 {len(calls)}회 호출됐다"

    def test_no_treatment_row_is_recorded_when_learner_state_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """처치 행도 남지 않는다 — 남으면 나중 집계가 그것을 '개인화된 처치'로 계상한다."""
        client, fake, _calls = _client(monkeypatch, learner_state=None)
        client.post("/v1/me/objectives/obj-mob13/study", json={})
        assert fake.added == [], f"게이트가 막았는데 행이 {len(fake.added)}건 적재됐다"

    def test_gate_passes_when_learner_state_exists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """성공 방향 대조군 — 행이 있으면 통과한다(게이트가 *항상* 막는 것이 아님을 확인).

        대조군이 없으면 "전부 409로 계상"이라는 과잉 수정도 위 세 검사를 통과한다.
        """
        client, _fake, calls = _client(monkeypatch)
        resp = client.post("/v1/me/objectives/obj-mob13/study", json={})
        assert resp.status_code == 201, resp.text
        assert len(calls) == 1
