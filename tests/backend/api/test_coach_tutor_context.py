"""P3-08 — 코치 세션 서빙 경로의 튜터 context 9종 집행 (hermetic·LLM 0·DB 0).

`test_wh1_tutor_context.py`가 판정기 계약을 본다면, 이 파일은 **서빙 코드가 그 판정기를 실제로
부르는가**(정본화 ≠ 집행)를 본다. `POST /v1/coach/sessions`와 `.../turns` 두 핸들러에서:

- 대조군: 9종을 전부 채운 요청 → 응답 `tutor_context.complete=True`·누락 로그 0·튜터 러너가 받은
  매니페스트도 완비.
- 주입 9건(파라미터화 × 두 핸들러): 슬롯 하나를 비우면 ① 응답이 201로 **진행**하고(거부 아님)
  ② 응답 `tutor_context.missing`에 그 슬롯이 뜨고 ③ 누락 로그 1줄에 슬롯명이 남고 ④ 튜터 러너
  (`run_wh1_primary_turn`)가 받은 매니페스트에도 같은 누락이 실린다 — 네 곳 중 하나라도 비면 RED.
- 조회 실패 주입: 새로 붙인 개념·스킬 조회가 예외를 던져도 201, 원인은 `lookup_failed:<타입명>`.
- 기존 subgraph 가드 경로 동결: 선수 traversal은 depth ≤ 2로, 웜스타트 탐색 표적은 기본 상한(12 ≤ 20)
  으로 불리고, 오개념은 튜터 초기 context에 preload되지 않는다(매칭 0이면 튜터가 받는 가설도 0).

튜터 러너는 캡처 스텁으로 대체한다(LLM 0) — 스텁이 None을 돌려 결정론 폴백 경로가 그대로 돈다.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from whymath_backend.api import coach
from whymath_backend.api._auth import get_consented_user
from whymath_backend.api._rate_limit import reset_store
from whymath_backend.app import create_app
from whymath_backend.config import Settings, get_settings
from whymath_backend.db.models.dialogue import Dialogue as DialogueORM
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.harness.wh1_tutor_context import TutorContextManifest, TutorContextSlot
from whymath_backend.l4.misconception import warmstart
from whymath_backend.l4.misconception.hypothesis import MisconceptionHypothesis
from whymath_backend.l4.pedagogy.pack_registry import get_pack
from whymath_backend.schema.dialogue import Dialogue as DialogueSchema
from whymath_backend.schema.enums import Persona
from whymath_backend.schema.user import UserProfile as UserProfileSchema

_UID = uuid.uuid4()
_PID = uuid.uuid4()
_CID = uuid.uuid4()
_CTX_LOGGER = "whymath.harness.wh1_tutor_context"
_HYP = MisconceptionHypothesis(
    misconception_id="distribution-over-power",
    confidence=0.8,
    turns_since_evidence=0,
    evidence_count=1,
)
_WARMSTART_MID = "sign-flip-in-inequality"


# ──────────────────────────────────────────────────────────────────────────
# hermetic 세션 — test_coach.py `_CapturingSession` 축소판(add/commit/get/execute만)
# ──────────────────────────────────────────────────────────────────────────
class _Result:
    def scalars(self) -> _Result:
        return self

    def all(self) -> list[Any]:
        return []

    def first(self) -> Any:
        return None

    def scalar_one(self) -> Any:
        return 0.0

    def scalar_one_or_none(self) -> Any:
        return None


class _Session:
    def __init__(self, preload: dict[Any, Any] | None = None) -> None:
        self.added: list[Any] = []
        self._preload = preload or {}

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def add_all(self, objs: list[Any]) -> None:
        self.added.extend(objs)

    async def commit(self) -> None:
        return None

    async def flush(self) -> None:
        return None

    async def refresh(self, obj: Any) -> None:
        return None

    async def get(self, model: Any, pk: Any) -> Any | None:
        return self._preload.get((model, pk))

    async def execute(self, stmt: Any) -> _Result:
        return _Result()

    async def scalar(self, stmt: Any) -> Any:
        return None


def _client(preload: dict[Any, Any] | None = None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_consented_user] = lambda: UserProfile.from_schema(
        UserProfileSchema(user_id=_UID, persona_primary=Persona.A_일반고고3)
    )
    app.dependency_overrides[get_settings] = lambda: Settings(
        jwt_secret_key=SecretStr("test-secret-0123456789abcdef")
    )
    session = _Session(preload)

    async def _sess() -> AsyncIterator[_Session]:
        yield session

    app.dependency_overrides[get_session] = _sess
    return TestClient(app)


@pytest.fixture(autouse=True)
def _isolation() -> Iterator[None]:
    import asyncio

    asyncio.run(reset_store())
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ──────────────────────────────────────────────────────────────────────────
# 9종 완비 상태를 만드는 서버 조회 대역 — 실제 핸들러처럼 문항이 없으면 문항 기반 값은 None
# ──────────────────────────────────────────────────────────────────────────
class _Fill:
    """슬롯별 공급 값 — 주입은 여기 한 칸을 비우는 것으로 한다."""

    def __init__(self) -> None:
        self.theta: float | None = 0.4
        self.grade: int | None = 11
        self.concept: uuid.UUID | None = _CID
        self.skills: list[str] = ["SK-ALG-01"]
        self.skill_error: Exception | None = None
        self.mastery: float | None = 0.6
        self.hypotheses: list[MisconceptionHypothesis] = [_HYP]
        self.pack = get_pack("CONCEPT")
        assert self.pack is not None


class _Spy:
    """튜터 러너·가드 좌석의 호출 인자 캡처."""

    def __init__(self) -> None:
        self.tutor_calls: list[dict[str, Any]] = []
        self.prereq_calls: list[dict[str, Any]] = []
        self.warmstart_calls: list[dict[str, Any]] = []


def _install(
    monkeypatch: pytest.MonkeyPatch,
    fill: _Fill,
    *,
    patch_hypotheses: bool = True,
) -> _Spy:
    spy = _Spy()

    async def _theta(session: Any, user_id: Any, problem_id: Any) -> float | None:
        return fill.theta

    async def _grade(session: Any, user_id: Any) -> int | None:
        return fill.grade

    async def _concept(session: Any, problem_id: Any) -> uuid.UUID | None:
        return fill.concept

    async def _skills(session: Any, concept_id: Any) -> list[str]:
        if fill.skill_error is not None:
            raise fill.skill_error
        return list(fill.skills)

    async def _mastery(session: Any, user_id: Any, problem_id: Any) -> float | None:
        return fill.mastery if problem_id is not None else None

    async def _none(*args: Any, **kwargs: Any) -> None:
        return None

    async def _pack(session: Any, problem_id: Any) -> Any:
        return fill.pack if problem_id is not None else None

    async def _hyps(session: Any, user_id: Any, matches: Any) -> list[MisconceptionHypothesis]:
        return list(fill.hypotheses)

    async def _prereq(*args: Any, **kwargs: Any) -> list[Any]:
        spy.prereq_calls.append(kwargs)
        return []

    async def _warm(*args: Any, **kwargs: Any) -> list[str]:
        spy.warmstart_calls.append(kwargs)
        return [_WARMSTART_MID]

    async def _tutor(**kwargs: Any) -> str | None:
        spy.tutor_calls.append(kwargs)
        return None  # 결정론 폴백 — LLM 0

    monkeypatch.setattr(coach, "_server_theta_for", _theta)
    monkeypatch.setattr(coach, "_grade_for", _grade)
    monkeypatch.setattr(coach, "get_primary_concept_id", _concept)
    monkeypatch.setattr(coach, "get_concept_skill_ids", _skills)
    monkeypatch.setattr(coach, "_server_mastery_for", _mastery)
    monkeypatch.setattr(coach, "_server_mastery_evidence_for", _none)
    monkeypatch.setattr(coach, "_standard_code_for", _none)
    monkeypatch.setattr(coach, "_pack_for", _pack)
    if patch_hypotheses:
        monkeypatch.setattr(coach, "_apply_hypotheses", _hyps)
    monkeypatch.setattr(coach, "recommend_prerequisite_gaps", _prereq)
    monkeypatch.setattr(coach, "assemble_warmstart_probe_hints", _warm)
    monkeypatch.setattr(coach, "run_wh1_primary_turn", _tutor)
    return spy


def _body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "student_input": "x+1=3 이니까 x=2 라고 생각했어요",
        "student_solution": "x+1=3 이니까 x=2",
        "solution_steps": ["x+1=3", "x=2"],
        "problem_id": str(_PID),
    }
    body.update(over)
    return {k: v for k, v in body.items() if v is not None}


def _post(path: str, fill: _Fill, body: dict[str, Any]) -> Any:
    if path == "create":
        return _client().post("/v1/coach/sessions", json=body)
    did = uuid.uuid4()
    problem_id = uuid.UUID(body["problem_id"]) if "problem_id" in body else None
    dialogue = DialogueORM.from_schema(
        DialogueSchema(
            dialogue_id=did,
            user_id=_UID,
            problem_id=problem_id,
            total_turns=2,
            student_turns=1,
            assistant_turns=1,
        )
    )
    turn_body = {k: v for k, v in body.items() if k != "problem_id"}
    return _client({(DialogueORM, did): dialogue}).post(
        f"/v1/coach/sessions/{did}/turns", json=turn_body
    )


def _ctx_lines(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == _CTX_LOGGER]


# 슬롯 하나를 비우는 주입 — (비울 슬롯, fill 변형, body 덮어쓰기). None 값은 body에서 키 삭제.
def _inject_learner(f: _Fill) -> None:
    f.theta = None


def _inject_concept(f: _Fill) -> None:
    f.concept = None


def _inject_skill(f: _Fill) -> None:
    f.skills = []


def _inject_misconception(f: _Fill) -> None:
    f.hypotheses = []


def _inject_mastery(f: _Fill) -> None:
    f.mastery = None


def _inject_policy(f: _Fill) -> None:
    f.pack = None


def _noop(f: _Fill) -> None:
    return None


_INJECTIONS: list[tuple[TutorContextSlot, Any, dict[str, Any]]] = [
    (TutorContextSlot.LEARNER_STATE, _inject_learner, {}),
    (TutorContextSlot.CONCEPT, _inject_concept, {}),
    (TutorContextSlot.SKILL, _inject_skill, {}),
    (TutorContextSlot.PROBLEM, _noop, {"problem_id": None}),
    (TutorContextSlot.STUDENT_ANSWER, _noop, {"student_input": "", "student_solution": None}),
    (TutorContextSlot.SOLUTION_RECORD, _noop, {"solution_steps": None}),
    (TutorContextSlot.MISCONCEPTION, _inject_misconception, {}),
    (TutorContextSlot.MASTERY, _inject_mastery, {}),
    (TutorContextSlot.PEDAGOGY_POLICY, _inject_policy, {}),
]
# 연쇄(실제 핸들러 값 조합) — 개념이 비면 스킬도, 문항이 비면 문항 기반 조회 슬롯 전부.
_CASCADE: dict[TutorContextSlot, set[TutorContextSlot]] = {
    TutorContextSlot.CONCEPT: {TutorContextSlot.CONCEPT, TutorContextSlot.SKILL},
    TutorContextSlot.PROBLEM: {
        TutorContextSlot.PROBLEM,
        TutorContextSlot.CONCEPT,
        TutorContextSlot.SKILL,
        TutorContextSlot.MASTERY,
        TutorContextSlot.PEDAGOGY_POLICY,
    },
}
_PATHS = ("create", "append")


def _tutor_manifest(spy: _Spy) -> TutorContextManifest:
    assert len(spy.tutor_calls) == 1, "튜터 러너가 정확히 한 번 불려야 한다(완료 가로채기 없음)"
    manifest = spy.tutor_calls[0]["tutor_context"]
    assert isinstance(manifest, TutorContextManifest)
    return manifest


# ──────────────────────────────────────────────────────────────────────────
# 대조군 + 주입 9건
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("path", _PATHS)
def test_control_all_nine_filled_reach_tutor_and_response(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, path: str
) -> None:
    fill = _Fill()
    spy = _install(monkeypatch, fill)
    with caplog.at_level(logging.DEBUG, logger=_CTX_LOGGER):
        resp = _post(path, fill, _body())
    assert resp.status_code == 201, resp.text
    ctx = resp.json()["tutor_context"]
    assert ctx["complete"] is True, ctx
    assert ctx["missing"] == []
    assert [s["slot"] for s in ctx["slots"]] == [s.value for s in TutorContextSlot]
    assert _ctx_lines(caplog) == []  # 완비면 누락 로그 0
    manifest = _tutor_manifest(spy)
    assert manifest.complete is True
    # 응답과 튜터가 본 판정은 같은 객체에서 나온다(단일 판정 원천).
    assert manifest.model_dump(mode="json") == ctx


@pytest.mark.parametrize("path", _PATHS)
@pytest.mark.parametrize(
    ("slot", "mutate", "body_over"), _INJECTIONS, ids=[s.value for s, _, _ in _INJECTIONS]
)
def test_each_single_slot_injection_is_disclosed_and_proceeds(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    path: str,
    slot: TutorContextSlot,
    mutate: Any,
    body_over: dict[str, Any],
) -> None:
    fill = _Fill()
    mutate(fill)
    body = _body(**body_over)
    # 주입이 실제로 적용됐다(mutated != original) — fill 또는 body 중 하나는 반드시 달라진다.
    assert body != _body() or vars(fill) != vars(_Fill())
    spy = _install(monkeypatch, fill)
    with caplog.at_level(logging.DEBUG, logger=_CTX_LOGGER):
        resp = _post(path, fill, body)
    # ① 진행(거부 아님) — 학생 경험은 깨지지 않는다.
    assert resp.status_code == 201, resp.text
    expected = {s.value for s in _CASCADE.get(slot, {slot})}
    # ② 응답 표기
    ctx = resp.json()["tutor_context"]
    assert ctx["complete"] is False
    assert set(ctx["missing"]) == expected
    status = next(s for s in ctx["slots"] if s["slot"] == slot.value)
    assert status["filled"] is False and status["cause"] is not None
    # ③ 로그 표기 — 1줄, 슬롯명이 원인과 함께 남는다.
    lines = _ctx_lines(caplog)
    assert len(lines) == 1
    assert f"{slot.value}({status['cause']})" in lines[0].getMessage()
    # ④ 튜터 러너가 받은 매니페스트에도 같은 누락 — 튜터가 '모른 채' 돌지 않는다.
    assert set(_tutor_manifest(spy).missing_names()) == expected


@pytest.mark.parametrize("path", _PATHS)
def test_new_lookup_failure_is_never_break_and_named(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, path: str
) -> None:
    fill = _Fill()
    fill.skill_error = RuntimeError("db down (test)")
    spy = _install(monkeypatch, fill)
    with caplog.at_level(logging.WARNING):
        resp = _post(path, fill, _body())
    assert resp.status_code == 201, resp.text
    skill = next(s for s in resp.json()["tutor_context"]["slots"] if s["slot"] == "skill")
    assert (skill["cause"], skill["cause_detail"]) == ("lookup_failed", "RuntimeError")
    # 조회 좌석(coach)과 판정 로그(tutor_context) 양쪽에 예외 타입명이 남는다.
    assert any(
        r.name == "whymath_backend.api.coach" and "RuntimeError" in r.getMessage()
        for r in caplog.records
    )
    (line,) = _ctx_lines(caplog)
    assert line.levelno == logging.WARNING
    assert "skill(lookup_failed·RuntimeError)" in line.getMessage()
    assert "db down" not in line.getMessage()  # 예외 메시지(값)는 남기지 않는다
    assert _tutor_manifest(spy).missing_names() == ["skill"]


def test_stateless_coach_carries_no_tutor_context() -> None:
    # stateless `/v1/coach`는 튜터를 부르지 않는다(LLM 0·DB 0) — 항상 누락인 가짜 계기판을 싣지 않는다.
    resp = _client().post("/v1/coach", json={"student_input": "음"})
    assert resp.status_code == 200, resp.text
    assert "tutor_context" not in resp.json()


# ──────────────────────────────────────────────────────────────────────────
# ③ 기존 subgraph 가드 경로 동결 — 서빙 경로가 실제로 그 가드를 탄다
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("path", _PATHS)
def test_prerequisite_traversal_on_serving_path_is_depth_bounded(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    spy = _install(monkeypatch, _Fill())
    assert _post(path, _Fill(), _body()).status_code == 201
    assert len(spy.prereq_calls) == 1, "서빙 경로가 선수 traversal 좌석을 타지 않았다"
    assert 1 <= spy.prereq_calls[0]["max_depth"] <= 2


@pytest.mark.parametrize("path", _PATHS)
def test_warmstart_probe_targets_use_bounded_default_limit(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    spy = _install(monkeypatch, _Fill())
    assert _post(path, _Fill(), _body()).status_code == 201
    assert len(spy.warmstart_calls) == 1, "서빙 경로가 웜스타트 좌석을 타지 않았다"
    # 상한을 호출부에서 풀지 않는다 — 기본 상한(12)이 max_nodes 범위(12~20) 안이다.
    assert "limit" not in spy.warmstart_calls[0]
    assert 12 <= warmstart._DEFAULT_LIMIT <= 20


@pytest.mark.parametrize("path", _PATHS)
def test_misconceptions_are_not_preloaded_into_tutor_context(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    # 실제 가설 큐레이션(_apply_hypotheses)을 태운다 — 매칭 없는 발화면 튜터가 받는 가설은 0이고,
    # 웜스타트 탐색 표적은 사적 probe 좌석(warmstart_outside_mids)으로만 간다(reactive retrieval).
    fill = _Fill()
    spy = _install(monkeypatch, fill, patch_hypotheses=False)
    resp = _post(path, fill, _body(student_input="음", student_solution=None))
    assert resp.status_code == 201, resp.text
    (call,) = spy.tutor_calls
    assert list(call["active_hypotheses"]) == []
    assert list(call["warmstart_outside_mids"]) == [_WARMSTART_MID]
    misconception = call["tutor_context"].status_of(TutorContextSlot.MISCONCEPTION)
    assert (misconception.filled, misconception.cause.value) == (False, "none_detected")
