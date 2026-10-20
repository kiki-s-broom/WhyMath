"""P3-08 — 코치 세션 서빙 경로의 튜터 context 9종 집행 (hermetic·LLM 0·DB 0).

`test_wh1_tutor_context.py`가 판정기·러너 계약을 본다면, 이 파일은 **서빙 코드가 그것을 실제로
부르고 사실대로 표기하는가**(정본화 ≠ 집행)를 본다. `POST /v1/coach/sessions`와 `.../turns`에서:

- 대조군: 9종을 전부 얻은 턴 → `complete=True`. P3-72 이후 개념·스킬·문제·팩은 프롬프트 경로로
  실리고, 숙달만 결정 (가)에 따라 `not_delivered`로 응답·로그에 드러난다(완비 턴도 무증상이 아니다).
  전달 표기는 **실제 튜터 러너**(스텁 provider)가 정책이 실제로 넘긴 프롬프트·보유값으로 계산한 것이다.
- 주입 9건 × 두 핸들러: 슬롯 하나를 비우면 201로 진행하고, 응답·로그·튜터가 받은 매니페스트
  세 곳에 그 누락이 뜬다.
- 튜터 미호출 턴(primary OFF·완료 상태머신 가로채기): `tutor_invoked=false`·전달 0·WARNING 없음.
- 배선 절마다의 픽스처(A 사진 제출 답안 · B 텍스트 답안 · C 개념 조회 실패 · D/E/F 플래그 OFF ·
  G 숙달 라벨만): 각 절을 지우는 뮤테이션이 RED가 되도록 그 절을 실제로 밟는다.
- 기존 subgraph 가드 경로 동결: 선수 traversal depth ≤ 2, 웜스타트 상한 12 ≤ 20, 오개념 preload 금지.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator, Iterator, Sequence
from types import TracebackType
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
from whymath_backend.harness import wh1_primary
from whymath_backend.harness.wh1_tutor_context import (
    ProblemBrief,
    TutorContextManifest,
    TutorContextSlot,
)
from whymath_backend.l3.models import GenerationResult, RoutingDecision
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
_COACH_LOGGER = "whymath_backend.api.coach"
_HYP = MisconceptionHypothesis(
    misconception_id="distribution-over-power",
    confidence=0.8,
    turns_since_evidence=0,
    evidence_count=1,
)
_WARMSTART_MID = "sign-flip-in-inequality"
S = TutorContextSlot
_DELIVERED = {
    "learner_state",
    "concept",
    "skill",
    "problem",
    "student_answer",
    "solution_record",
    "misconception",
    "pedagogy_policy",
}
_NOT_DELIVERED = ["mastery"]  # Kiki 결정 (가) — 숙달은 어떤 경로로도 튜터에 실리지 않는다
# P3-72 ⑦ 대조군 경로표(가드 OFF 기본) — 보고서 §2 표와 같다.
_PATHS_CONTROL: dict[str, list[str]] = {
    "learner_state": ["private_tool"],
    "concept": ["prompt"],
    "skill": ["prompt"],
    "problem": ["prompt"],
    "student_answer": ["private_tool"],
    "solution_record": ["private_tool"],
    "misconception": ["prompt", "private_tool"],
    "mastery": [],
    "pedagogy_policy": ["prompt"],
}


# ──────────────────────────────────────────────────────────────────────────
# hermetic 세션 — add/commit/get/execute + SAVEPOINT(begin_nested) 캡처
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


class _Nested:
    def __init__(self, session: _Session) -> None:
        self._session = session

    async def __aenter__(self) -> _Nested:
        self._session.nested_depth += 1
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._session.nested_depth -= 1
        if exc is not None:
            self._session.rolled_back.append(exc)


class _Session:
    def __init__(self, preload: dict[Any, Any] | None = None) -> None:
        self.added: list[Any] = []
        self._preload = preload or {}
        self.nested_depth = 0
        self.rolled_back: list[BaseException] = []
        # P3-08 개념·스킬 조회가 SAVEPOINT 안에서 실행됐는가(조회 시점의 중첩 깊이 기록).
        self.lookup_depths: list[int] = []

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

    def begin_nested(self) -> _Nested:
        return _Nested(self)


_SESSIONS: list[_Session] = []


def _client(preload: dict[Any, Any] | None = None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_consented_user] = lambda: UserProfile.from_schema(
        UserProfileSchema(user_id=_UID, persona_primary=Persona.A_일반고고3)
    )
    app.dependency_overrides[get_settings] = lambda: Settings(
        jwt_secret_key=SecretStr("test-secret-0123456789abcdef")
    )
    session = _Session(preload)
    _SESSIONS.append(session)

    async def _sess() -> AsyncIterator[_Session]:
        yield session

    app.dependency_overrides[get_session] = _sess
    return TestClient(app)


@pytest.fixture(autouse=True)
def _isolation() -> Iterator[None]:
    import asyncio

    asyncio.run(reset_store())
    _SESSIONS.clear()
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def _none_async(*args: Any, **kwargs: Any) -> None:
    return None


def _set_flag(monkeypatch: pytest.MonkeyPatch, name: str, value: bool) -> None:
    monkeypatch.setenv(f"WHYMATH_{name.upper()}", "true" if value else "false")
    get_settings.cache_clear()


# ──────────────────────────────────────────────────────────────────────────
# 9종 공급 대역 — 실제 핸들러처럼 문항이 없으면 문항 기반 값은 None
# ──────────────────────────────────────────────────────────────────────────
class _Fill:
    def __init__(self) -> None:
        self.theta: float | None = 0.4137  # 프롬프트 누출 감시 표지(다른 수치와 겹치지 않게)
        self.grade: int | None = 11
        self.concept: uuid.UUID | None = _CID
        self.concept_error: Exception | None = None
        self.skills: list[str] = ["SK-ALG-01"]
        self.skill_error: Exception | None = None
        self.mastery: float | None = 0.5813
        self.hypotheses: list[MisconceptionHypothesis] = [_HYP]
        self.pack = get_pack("CONCEPT")
        assert self.pack is not None
        # P3-72 내용 요약 원천(개념 이름표·스킬 이름표·문제 구조).
        self.concept_label: tuple[str, str] | None = ("math.algebra.linear-equation", "일차방정식")
        self.skill_labels: list[tuple[str, str]] = [("SK-ALG-01", "등식의 성질로 이항하기")]
        self.problem_brief: ProblemBrief | None = ProblemBrief(
            question_format="단답형", bloom_level="APPLY", has_visual=False, condition_count=2
        )
        self.content_error: Exception | None = None


class _StubProvider:
    """튜터 정책의 도구 선택 대역 — 항상 end_turn(질문)만(실 네트워크 0). 프롬프트를 캡처한다."""

    def __init__(self, sink: _Spy) -> None:
        self._sink = sink

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        *,
        images: Sequence[str] | None = None,
    ) -> GenerationResult:
        self._sink.prompts.append(prompt)
        self._sink.systems.append(system)
        return GenerationResult('{"kind": "end_turn", "action_type": "질문"}')


class _Spy:
    def __init__(self) -> None:
        self.tutor_calls: list[dict[str, Any]] = []
        self.prereq_calls: list[dict[str, Any]] = []
        self.warmstart_calls: list[dict[str, Any]] = []
        self.prompts: list[str] = []
        self.systems: list[str] = []
        self.content_depths: list[int] = []


def _install(
    monkeypatch: pytest.MonkeyPatch, fill: _Fill, *, patch_hypotheses: bool = True
) -> _Spy:
    spy = _Spy()
    real_runner = wh1_primary.run_wh1_primary_turn

    async def _theta(session: Any, user_id: Any, problem_id: Any) -> float | None:
        return fill.theta

    async def _grade(session: Any, user_id: Any) -> int | None:
        return fill.grade

    async def _concept(session: Any, problem_id: Any) -> uuid.UUID | None:
        session.lookup_depths.append(session.nested_depth)
        if fill.concept_error is not None:
            raise fill.concept_error
        return fill.concept

    async def _skills(session: Any, concept_id: Any) -> list[str]:
        session.lookup_depths.append(session.nested_depth)
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
        # 실제 러너를 돌린다(스텁 provider·DB 미사용) — 전달 판정은 러너가 정책 보유값으로 낸다.
        spy.tutor_calls.append(kwargs)
        return await real_runner(**{**kwargs, "provider": _StubProvider(spy), "session": None})

    async def _problem_brief(session: Any, problem_id: Any) -> ProblemBrief | None:
        spy.content_depths.append(session.nested_depth)
        if fill.content_error is not None:
            raise fill.content_error
        return fill.problem_brief

    async def _concept_label(session: Any, concept_id: Any) -> tuple[str, str] | None:
        spy.content_depths.append(session.nested_depth)
        return fill.concept_label

    async def _skill_labels(session: Any, skill_ids: Any) -> list[tuple[str, str]]:
        spy.content_depths.append(session.nested_depth)
        return [pair for pair in fill.skill_labels if pair[0] in skill_ids]

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
    monkeypatch.setattr(coach, "_problem_brief_for", _problem_brief)
    monkeypatch.setattr(coach, "_concept_label_for", _concept_label)
    monkeypatch.setattr(coach, "_skill_labels_for", _skill_labels)
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


def _post(path: str, body: dict[str, Any]) -> Any:
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


def _slot(ctx: dict[str, Any], name: str) -> dict[str, Any]:
    found: dict[str, Any] = next(s for s in ctx["slots"] if s["slot"] == name)
    return found


def _tutor_manifest(spy: _Spy) -> TutorContextManifest:
    assert len(spy.tutor_calls) == 1, "튜터 러너가 정확히 한 번 불려야 한다(완료 가로채기 없음)"
    manifest = spy.tutor_calls[0]["tutor_context"]
    assert isinstance(manifest, TutorContextManifest)
    return manifest


_PATHS = ("create", "append")


# ──────────────────────────────────────────────────────────────────────────
# 대조군 — 완비 턴에서도 '튜터 미전달'이 드러난다
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("path", _PATHS)
def test_control_complete_turn_still_discloses_not_delivered(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, path: str
) -> None:
    spy = _install(monkeypatch, _Fill())
    with caplog.at_level(logging.DEBUG, logger=_CTX_LOGGER):
        resp = _post(path, _body())
    assert resp.status_code == 201, resp.text
    ctx = resp.json()["tutor_context"]
    assert ctx["tutor_invoked"] is True
    assert ctx["complete"] is True and ctx["missing"] == []
    assert ctx["not_delivered"] == _NOT_DELIVERED
    delivered = {s["slot"] for s in ctx["slots"] if s["delivered_to_tutor"]}
    assert delivered == _DELIVERED
    assert {s["slot"]: s["delivery_paths"] for s in ctx["slots"]} == _PATHS_CONTROL
    assert _slot(ctx, "student_answer")["size"] is None  # 답안 길이 비노출
    assert "cause_detail" not in resp.text
    (line,) = _ctx_lines(caplog)
    assert line.levelno == logging.INFO
    assert "튜터 미전달 1: mastery" in line.getMessage()
    assert "프롬프트 5: concept skill problem misconception pedagogy_policy" in line.getMessage()
    # 응답 = 러너 영수증(실제 전달 판정) — 핸들러가 추정한 값이 아니다.
    receipt = spy.tutor_calls[0]["delivery"]
    assert receipt.manifest is not None
    assert receipt.manifest.model_dump(mode="json") == ctx


# ──────────────────────────────────────────────────────────────────────────
# 주입 9건 × 두 핸들러
# ──────────────────────────────────────────────────────────────────────────
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


_INJECTIONS: list[tuple[TutorContextSlot, Any, dict[str, Any], str]] = [
    (S.LEARNER_STATE, _inject_learner, {}, "no_history"),
    (S.CONCEPT, _inject_concept, {}, "coverage_gap"),
    (S.SKILL, _inject_skill, {}, "coverage_gap"),
    (S.PROBLEM, _noop, {"problem_id": None}, "not_supplied"),
    (S.STUDENT_ANSWER, _noop, {"student_input": "", "student_solution": None}, "not_supplied"),
    (S.SOLUTION_RECORD, _noop, {"solution_steps": None}, "not_supplied"),
    (S.MISCONCEPTION, _inject_misconception, {}, "none_detected"),
    (S.MASTERY, _inject_mastery, {}, "no_history"),
    (S.PEDAGOGY_POLICY, _inject_policy, {}, "coverage_gap"),
]
_CASCADE: dict[TutorContextSlot, set[str]] = {
    S.CONCEPT: {"concept", "skill"},
    S.PROBLEM: {"problem", "concept", "skill", "mastery", "pedagogy_policy"},
}


@pytest.mark.parametrize("path", _PATHS)
@pytest.mark.parametrize(
    ("slot", "mutate", "body_over", "cause"), _INJECTIONS, ids=[s.value for s, *_ in _INJECTIONS]
)
def test_each_single_slot_injection_is_disclosed_and_proceeds(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    path: str,
    slot: TutorContextSlot,
    mutate: Any,
    body_over: dict[str, Any],
    cause: str,
) -> None:
    fill = _Fill()
    mutate(fill)
    body = _body(**body_over)
    assert body != _body() or vars(fill) != vars(_Fill())  # 주입 적용 단언
    spy = _install(monkeypatch, fill)
    with caplog.at_level(logging.DEBUG, logger=_CTX_LOGGER):
        resp = _post(path, body)
    assert resp.status_code == 201, resp.text  # ① 진행(거부 아님)
    expected = _CASCADE.get(slot, {slot.value})
    ctx = resp.json()["tutor_context"]
    assert ctx["complete"] is False and set(ctx["missing"]) == expected  # ② 응답
    status = _slot(ctx, slot.value)
    assert (status["resolved"], status["delivered_to_tutor"], status["cause"]) == (
        False,
        False,
        cause,
    )
    (line,) = _ctx_lines(caplog)  # ③ 로그 1줄 — 학생 측 부재·커버리지 공백이라 INFO
    assert f"{slot.value}({cause})" in line.getMessage()
    assert line.levelno == logging.INFO
    assert set(_tutor_manifest(spy).missing_names()) == expected  # ④ 튜터가 받은 매니페스트


# ──────────────────────────────────────────────────────────────────────────
# 튜터 미호출 턴 — tutor_invoked=false · 전달 0 · WARNING 없음(시스템 결함이 있어도 표기만)
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("path", _PATHS)
def test_primary_off_turn_is_marked_not_invoked_without_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, path: str
) -> None:
    fill = _Fill()
    fill.theta = None
    spy = _install(monkeypatch, fill)
    _set_flag(monkeypatch, "wh1_primary_enabled", False)
    _set_flag(monkeypatch, "l4_server_theta_enabled", False)  # 시스템 결함 원인을 일부러 넣는다
    with caplog.at_level(logging.DEBUG, logger=_CTX_LOGGER):
        resp = _post(path, _body())
    assert resp.status_code == 201, resp.text
    ctx = resp.json()["tutor_context"]
    assert ctx["tutor_invoked"] is False
    assert not any(s["delivered_to_tutor"] for s in ctx["slots"])
    assert _slot(ctx, "learner_state")["cause"] == "source_disabled"
    assert spy.tutor_calls == []
    (line,) = _ctx_lines(caplog)
    assert line.levelno == logging.INFO and "tutor_invoked=False" in line.getMessage()


@pytest.mark.parametrize("path", _PATHS)
def test_completion_intercepted_turn_is_marked_not_invoked(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    spy = _install(monkeypatch, _Fill())
    original = coach._resolve_completion

    async def _handled(*args: Any, **kwargs: Any) -> Any:
        return (await original(*args, **kwargs))._replace(handled=True)

    monkeypatch.setattr(coach, "_resolve_completion", _handled)
    resp = _post(path, _body())
    assert resp.status_code == 201, resp.text
    ctx = resp.json()["tutor_context"]
    assert ctx["tutor_invoked"] is False
    assert not any(s["delivered_to_tutor"] for s in ctx["slots"])
    assert spy.tutor_calls == []


@pytest.mark.parametrize("path", _PATHS)
def test_system_defect_on_invoked_turn_warns(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, path: str
) -> None:
    fill = _Fill()
    fill.theta = None
    _install(monkeypatch, fill)
    _set_flag(monkeypatch, "l4_server_theta_enabled", False)
    with caplog.at_level(logging.DEBUG, logger=_CTX_LOGGER):
        resp = _post(path, _body())
    assert resp.status_code == 201, resp.text
    (line,) = _ctx_lines(caplog)
    assert line.levelno == logging.WARNING
    assert "learner_state(source_disabled)" in line.getMessage()


# ──────────────────────────────────────────────────────────────────────────
# 배선 절 픽스처 A~G — 각 절을 지우면 RED가 되도록 그 절을 실제로 밟는다
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("path", _PATHS)
def test_a_photo_submission_answer_is_read_from_student_solution(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    # 사진(OCR) 제출 턴 — 발화는 비고 풀이만 있다. 튜터는 `student_solution or student_input`을 받는다.
    _install(monkeypatch, _Fill())
    resp = _post(path, _body(student_input="", student_solution="x=2"))
    assert resp.status_code == 201, resp.text
    answer = _slot(resp.json()["tutor_context"], "student_answer")
    assert answer["resolved"] is True and answer["delivered_to_tutor"] is True


@pytest.mark.parametrize("path", _PATHS)
def test_b_text_turn_answer_is_read_from_student_input(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    _install(monkeypatch, _Fill())
    resp = _post(path, _body(student_input="x=2 같아요", student_solution=None))
    assert resp.status_code == 201, resp.text
    answer = _slot(resp.json()["tutor_context"], "student_answer")
    assert answer["resolved"] is True and answer["delivered_to_tutor"] is True


@pytest.mark.parametrize("path", _PATHS)
@pytest.mark.parametrize("stage", ["concept", "skill"])
def test_c_lookup_failure_is_never_break_named_and_savepointed(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, path: str, stage: str
) -> None:
    fill = _Fill()
    if stage == "concept":
        fill.concept_error = RuntimeError("db down (test)")
    else:
        fill.skill_error = RuntimeError("db down (test)")
    spy = _install(monkeypatch, fill)
    # 선수 코칭 좌석도 같은 개념 해석을 쓰므로 그쪽 실패와 분리한다 — 이 테스트는 새 조회만 본다.
    monkeypatch.setattr(coach, "_prerequisite_coaching_for", _none_async)
    with caplog.at_level(logging.WARNING):
        resp = _post(path, _body())
    assert resp.status_code == 201, resp.text
    ctx = resp.json()["tutor_context"]
    failed = {"concept", "skill"} if stage == "concept" else {"skill"}
    for name in failed:
        assert _slot(ctx, name)["cause"] == "lookup_failed"
    assert "RuntimeError" not in resp.text  # 예외 타입명은 응답에 없다(로그에만)
    coach_lines = [r for r in caplog.records if r.name == _COACH_LOGGER]
    assert any(
        f"튜터 context {stage} 조회 실패(RuntimeError)" in r.getMessage() for r in coach_lines
    )
    assert all("db down" not in r.getMessage() for r in caplog.records)
    (line,) = _ctx_lines(caplog)
    assert line.levelno == logging.WARNING  # 시스템 결함 ∧ 튜터 호출
    # SAVEPOINT 안에서 실패했고 롤백됐다(바깥 트랜잭션 aborted 방지).
    (session,) = _SESSIONS
    assert session.lookup_depths and all(d > 0 for d in session.lookup_depths)
    injected = fill.concept_error if stage == "concept" else fill.skill_error
    assert any(e is injected for e in session.rolled_back)
    assert set(_tutor_manifest(spy).missing_names()) == failed


@pytest.mark.parametrize("path", _PATHS)
def test_lookup_success_runs_inside_one_savepoint(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    _install(monkeypatch, _Fill())
    monkeypatch.setattr(coach, "_prerequisite_coaching_for", _none_async)  # 같은 seam의 다른 소비처
    assert _post(path, _body()).status_code == 201
    (session,) = _SESSIONS
    assert len(session.lookup_depths) == 2  # 개념 1 + 스킬 1 — 둘 다 SAVEPOINT 안
    assert all(d > 0 for d in session.lookup_depths)


@pytest.mark.parametrize("path", _PATHS)
@pytest.mark.parametrize(
    ("flag", "slot", "mutate"),
    [
        ("l4_server_theta_enabled", "learner_state", _inject_learner),  # D
        ("l4_server_mastery_enabled", "mastery", _inject_mastery),  # E
        ("pedagogy_pack_prompt_enabled", "pedagogy_policy", _inject_policy),  # F
    ],
    ids=["d-theta", "e-mastery", "f-pack"],
)
def test_def_flag_off_is_reported_as_source_disabled(
    monkeypatch: pytest.MonkeyPatch, path: str, flag: str, slot: str, mutate: Any
) -> None:
    # 플래그 OFF면 핸들러의 조회 좌석이 None을 낸다(대역은 그 결과를 재현) — 원인은 '이력 없음'·
    # '커버리지 공백'이 아니라 '꺼짐'이어야 한다. 플래그를 읽지 않고 상수로 두면 RED.
    fill = _Fill()
    mutate(fill)
    _install(monkeypatch, fill)
    _set_flag(monkeypatch, flag, False)
    resp = _post(path, _body())
    assert resp.status_code == 201, resp.text
    assert _slot(resp.json()["tutor_context"], slot)["cause"] == "source_disabled"


@pytest.mark.parametrize("path", _PATHS)
def test_g_mastery_label_alone_resolves_mastery(monkeypatch: pytest.MonkeyPatch, path: str) -> None:
    fill = _Fill()
    fill.mastery = None
    _install(monkeypatch, fill)
    resp = _post(path, _body(mastery_level="숙달"))
    assert resp.status_code == 201, resp.text
    mastery = _slot(resp.json()["tutor_context"], "mastery")
    assert mastery["resolved"] is True and mastery["delivered_to_tutor"] is False


@pytest.mark.parametrize("path", _PATHS)
def test_g_bkt_mastery_alone_resolves_mastery(monkeypatch: pytest.MonkeyPatch, path: str) -> None:
    fill = _Fill()
    fill.mastery = None
    _install(monkeypatch, fill)
    resp = _post(path, _body(bkt_mastery=0.5))
    assert resp.status_code == 201, resp.text
    assert _slot(resp.json()["tutor_context"], "mastery")["resolved"] is True


def test_stateless_coach_carries_no_tutor_context() -> None:
    # stateless `/v1/coach`는 튜터를 부르지 않는다(LLM 0·DB 0) — 늘 누락인 가짜 계기판을 싣지 않는다.
    resp = _client().post("/v1/coach", json={"student_input": "음"})
    assert resp.status_code == 200, resp.text
    assert "tutor_context" not in resp.json()


# ──────────────────────────────────────────────────────────────────────────
# 기존 subgraph 가드 경로 동결 — 서빙 경로가 실제로 그 가드를 탄다
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("path", _PATHS)
def test_prerequisite_traversal_on_serving_path_is_depth_bounded(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    spy = _install(monkeypatch, _Fill())
    assert _post(path, _body()).status_code == 201
    assert len(spy.prereq_calls) == 1, "서빙 경로가 선수 traversal 좌석을 타지 않았다"
    assert 1 <= spy.prereq_calls[0]["max_depth"] <= 2


@pytest.mark.parametrize("path", _PATHS)
def test_warmstart_probe_targets_use_bounded_default_limit(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    spy = _install(monkeypatch, _Fill())
    assert _post(path, _body()).status_code == 201
    assert len(spy.warmstart_calls) == 1, "서빙 경로가 웜스타트 좌석을 타지 않았다"
    assert "limit" not in spy.warmstart_calls[0]
    assert 12 <= warmstart._DEFAULT_LIMIT <= 20


@pytest.mark.parametrize("path", _PATHS)
def test_misconceptions_are_not_preloaded_into_tutor_context(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    # 실제 가설 큐레이션을 태운다 — 매칭 없는 발화면 튜터가 받는 가설은 0이고, 웜스타트 표적은
    # 사적 probe 좌석(warmstart_outside_mids)으로만 간다(reactive retrieval).
    spy = _install(monkeypatch, _Fill(), patch_hypotheses=False)
    resp = _post(path, _body(student_input="음", student_solution=None))
    assert resp.status_code == 201, resp.text
    (call,) = spy.tutor_calls
    assert list(call["active_hypotheses"]) == []
    assert list(call["warmstart_outside_mids"]) == [_WARMSTART_MID]
    misconception = _slot(resp.json()["tutor_context"], "misconception")
    assert (misconception["resolved"], misconception["cause"]) == (False, "none_detected")


# ──────────────────────────────────────────────────────────────────────────
# P3-72 — 서빙 경로 내용 요약 전달 · 결정 (가) 동결 · 정답 억제 · 조회 안전
# ──────────────────────────────────────────────────────────────────────────
def _prompt_summaries(spy: _Spy) -> list[dict[str, Any]]:
    assert spy.prompts, "튜터 정책이 좌석에 프롬프트를 한 번도 넘기지 않았다"
    out: list[dict[str, Any]] = []
    for prompt in spy.prompts:
        start, end = prompt.index("{"), prompt.rindex("}")
        out.append(json.loads(prompt[start : end + 1]))
    return out


def _all_keys(node: Any) -> set[str]:
    if isinstance(node, dict):
        keys = {str(k) for k in node}
        for v in node.values():
            keys |= _all_keys(v)
        return keys
    if isinstance(node, list):
        out: set[str] = set()
        for v in node:
            out |= _all_keys(v)
        return out
    return set()


# 학생 개인 학습 데이터·학년의 *키* — 프롬프트 요약 어디에도 있으면 안 된다(결정 (가)·학년 판정).
_FORBIDDEN_KEYS = {
    "theta",
    "ability",
    "mastery",
    "mastery_level",
    "bkt_mastery",
    "grade",
    "learner",
}
# 숙달 파생 라벨(`l4.lthc.models.MasteryLevel`) — 값으로도 있으면 안 된다.
_MASTERY_LABELS = ("초보", "발전 중", "숙달")


def _load_freeze() -> Any:
    """⑥ 동결 판정기(키 트리 허용 목록·수치 잎 감시)의 단일 정본 — 하네스 테스트 모듈에서 읽는다.

    `--import-mode=importlib`라 테스트 모듈끼리 import가 안 된다 — 허용 목록을 두 곳에 복제하면
    한쪽만 고쳐지는 순간 동결이 갈라지므로 파일 경로로 같은 정본을 적재한다.
    """
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "harness" / "test_wh1_tutor_slot_delivery.py"
    spec = importlib.util.spec_from_file_location("_p372_prompt_freeze", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_FREEZE = _load_freeze()


def _numeric_forms(value: float) -> list[str]:
    return [str(value), f"{value:.2f}", f"{value:.3f}", str(round(value * 100))]


@pytest.mark.parametrize("path", _PATHS)
@pytest.mark.parametrize(
    "extra",
    [{}, {"mastery_level": "숙달"}, {"bkt_mastery": 0.3917}],
    ids=["server", "label", "bkt"],
)
def test_prompt_carries_content_summary_but_no_student_learning_data(
    monkeypatch: pytest.MonkeyPatch, path: str, extra: dict[str, Any]
) -> None:
    fill = _Fill()
    spy = _install(monkeypatch, fill)
    resp = _post(path, _body(**extra))
    assert resp.status_code == 201, resp.text
    summaries = _prompt_summaries(spy)
    first = summaries[0]
    # ⑤ 실린다 — 개념 code·이름 · 스킬 수·이름 · 문제 구조 · 팩 요약.
    assert first["concept"] == {"code": "math.algebra.linear-equation", "name": "일차방정식"}
    assert first["skills"] == {"count": 1, "names": ["등식의 성질로 이항하기"]}
    assert first["problem"] == {
        "question_format": "단답형",
        "bloom_level": "APPLY",
        "has_visual": False,
        "condition_count": 2,
    }
    assert fill.pack is not None
    assert first["pedagogy_policy"]["k_type"] == fill.pack.k_type
    assert first["context_not_delivered"] == ["mastery"]
    assert first["context_held_privately"] == ["learner_state", "student_answer", "solution_record"]
    # ⑥ 동결 — θ·숙달 값·파생 라벨·학년이 프롬프트·시스템 프롬프트 어디에도 없다.
    sentinels = [*_numeric_forms(0.4137), *_numeric_forms(0.5813), *_numeric_forms(0.3917)]
    for prompt, system, summary in zip(spy.prompts, spy.systems, summaries, strict=True):
        # 1차 축 — 키 트리 허용 목록 + 수치 잎(θ·숙달·클라 숙달 근방·학년 값) 감시(검토 중1).
        conf = [_HYP.confidence]  # Kiki 결정 2026-10-20 — 가설 confidence도 수치로 싣지 않는다
        _FREEZE.assert_prompt_summary_frozen(
            summary, theta=0.4137, mastery=0.5813, grade=11, hypothesis_confidences=conf
        )
        _FREEZE.assert_prompt_summary_frozen(
            summary, theta=0.3917, mastery=0.5813, grade=11, hypothesis_confidences=conf
        )
        assert not (_all_keys(summary) & _FORBIDDEN_KEYS), _all_keys(summary) & _FORBIDDEN_KEYS
        for text in (prompt, system):
            for sentinel in sentinels:
                assert sentinel not in text, sentinel
            for label in _MASTERY_LABELS:
                assert label not in text, label
            assert "학년" not in text
    # 응답 경로표도 같은 판정 — 숙달은 경로 0, 학생 상태는 사적 보유뿐.
    ctx = resp.json()["tutor_context"]
    assert _slot(ctx, "mastery")["delivery_paths"] == []
    assert _slot(ctx, "learner_state")["delivery_paths"] == ["private_tool"]


@pytest.mark.parametrize("path", _PATHS)
def test_content_lookup_failure_leaves_those_slots_undelivered_and_named(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, path: str
) -> None:
    fill = _Fill()
    fill.content_error = RuntimeError("db down (test)")
    spy = _install(monkeypatch, fill)
    with caplog.at_level(logging.WARNING):
        resp = _post(path, _body())
    assert resp.status_code == 201, resp.text
    ctx = resp.json()["tutor_context"]
    # 값(id)은 얻었으나 이름표 조회가 실패 — 프롬프트에 안 실렸으니 미전달로 정직하게 표기한다.
    assert ctx["not_delivered"] == ["concept", "skill", "problem", "mastery"]
    assert _slot(ctx, "pedagogy_policy")["delivery_paths"] == ["prompt"]  # 팩은 DB 없이 요약
    summary = _prompt_summaries(spy)[0]
    assert not {"concept", "skills", "problem"} & set(summary)
    coach_lines = [r for r in caplog.records if r.name == _COACH_LOGGER]
    assert any(
        "튜터 내용 요약 problem 조회 실패(RuntimeError)" in r.getMessage() for r in coach_lines
    )
    assert all("db down" not in r.getMessage() for r in caplog.records)
    (session,) = _SESSIONS
    assert any(e is fill.content_error for e in session.rolled_back)  # SAVEPOINT 롤백


@pytest.mark.parametrize("path", _PATHS)
def test_content_lookups_run_inside_savepoint_and_only_when_tutor_may_run(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    spy = _install(monkeypatch, _Fill())
    assert _post(path, _body()).status_code == 201
    assert len(spy.content_depths) == 3 and all(d > 0 for d in spy.content_depths)
    off = _install(monkeypatch, _Fill())
    _set_flag(monkeypatch, "wh1_primary_enabled", False)
    assert _post(path, _body()).status_code == 201
    assert off.content_depths == []  # 튜터를 못 부르는 턴은 요약 조회 0


@pytest.mark.parametrize("path", _PATHS)
def test_completion_intercepted_turn_runs_no_content_lookup(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    # 검토 하3 — 완료 상태머신이 가로챈 턴은 튜터를 부르지 않으므로 요약 조회도 0이어야 한다.
    spy = _install(monkeypatch, _Fill())
    original = coach._resolve_completion

    async def _handled(*args: Any, **kwargs: Any) -> Any:
        return (await original(*args, **kwargs))._replace(handled=True)

    monkeypatch.setattr(coach, "_resolve_completion", _handled)
    assert _post(path, _body()).status_code == 201
    assert spy.tutor_calls == [] and spy.content_depths == []


def test_problem_brief_query_reads_only_allowlisted_columns() -> None:
    # 정답 억제 계약 — 문제 요약 조회는 지문·보기·정답·해설·오답 선지·정답 제약 열을 읽지 않는다.
    # 문자열 금지 목록이 아니라 **구성된 SELECT의 실제 열**을 본다.
    stmt = coach._problem_brief_query(_PID)
    selected = {c.name for c in stmt.selected_columns}
    assert selected == {"question_format", "bloom_level", "has_visual", "condition_count"}
    forbidden = {
        "question_text",
        "question_text_md",
        "choices",
        "answer",
        "answer_explanation",
        "multiple_answers",
        "distractor_map",
        "answer_constraint",
        "answer_transform",
        "answer_format",
        "conditions_parsed",
    }
    assert not selected & forbidden


# ──────────────────────────────────────────────────────────────────────────
# 검토 중2 — 실제 조회 헬퍼 3종을 **실행**한다(대역 없이). 문을 캡처해 실행된 SQL로 동결한다.
# 실 PG 왕복은 `test_coach_tutor_content_integration.py`(integration)가 본다.
# ──────────────────────────────────────────────────────────────────────────
class _Rows:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def first(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None

    def all(self) -> list[tuple[Any, ...]]:
        return list(self._rows)


class _RecordingSession:
    """`execute`가 받은 문을 PG 방언으로 컴파일해 기록하고, 대상 테이블별 행을 돌려준다.

    `get`(ORM 엔티티 전체 로드)은 금지다 — 문제 요약은 허용 열 SELECT로만 읽어야 한다(정답 열
    미로드). 호출되면 즉시 실패한다.
    """

    def __init__(self, rows: dict[str, list[tuple[Any, ...]]]) -> None:
        self._rows = rows
        self.sql: list[str] = []

    async def execute(self, stmt: Any) -> _Rows:
        from sqlalchemy.dialects import postgresql

        self.sql.append(
            str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        )
        (table,) = {t.name for t in stmt.get_final_froms()}
        return _Rows(self._rows.get(table, []))

    async def get(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError(
            "문제 요약이 ORM 엔티티 전체를 로드했다(정답 열 포함) — 허용 열만 읽어야 한다"
        )


_ANSWER_COLUMNS = (
    "question_text",
    "choices",
    "answer",
    "answer_explanation",
    "multiple_answers",
    "distractor_map",
    "answer_constraint",
    "answer_transform",
    "answer_format",
    "conditions_parsed",
)


def test_problem_brief_helper_reads_only_allowlisted_columns_and_caps() -> None:
    import asyncio

    from whymath_backend.schema.enums import BloomLevel, QuestionFormat

    session = _RecordingSession({"problem": [(QuestionFormat.단답형, BloomLevel.APPLY, True, 35)]})
    brief = asyncio.run(coach._problem_brief_for(session, _PID))  # type: ignore[arg-type]
    assert brief == ProblemBrief(
        question_format="단답형", bloom_level="APPLY", has_visual=True, condition_count=20
    )
    (sql,) = session.sql
    selected = sql.split("FROM")[0]
    for col in ("question_format", "bloom_level", "has_visual", "condition_count"):
        assert f"problem.{col}" in selected
    for col in _ANSWER_COLUMNS:
        assert f"problem.{col}" not in sql, col
    assert str(_PID) in sql  # PK 단건


def test_problem_brief_helper_returns_none_without_row() -> None:
    import asyncio

    session = _RecordingSession({})
    assert asyncio.run(coach._problem_brief_for(session, _PID)) is None  # type: ignore[arg-type]


def test_concept_label_helper_returns_code_then_name() -> None:
    import asyncio

    session = _RecordingSession({"concept": [("math.algebra.linear-equation", "일차방정식")]})
    label = asyncio.run(coach._concept_label_for(session, _CID))  # type: ignore[arg-type]
    assert label == ("math.algebra.linear-equation", "일차방정식")
    (sql,) = session.sql
    assert sql.split("FROM")[0].index("concept.code") < sql.split("FROM")[0].index(
        "concept.name_ko"
    )


def test_skill_labels_helper_queries_only_first_five_sorted_ids() -> None:
    import asyncio

    ids = [f"SK-{i:02d}" for i in (9, 3, 7, 1, 8, 2, 6, 4)]
    session = _RecordingSession({"skill_node": [("SK-01", "a"), ("SK-02", "b")]})
    labels = asyncio.run(coach._skill_labels_for(session, ids))  # type: ignore[arg-type]
    assert labels == [("SK-01", "a"), ("SK-02", "b")]
    (sql,) = session.sql
    for kept in ("SK-01", "SK-02", "SK-03", "SK-04", "SK-06"):
        assert f"'{kept}'" in sql, kept
    for dropped in ("SK-07", "SK-08", "SK-09"):
        assert f"'{dropped}'" not in sql, dropped


def test_skill_labels_helper_skips_query_without_ids() -> None:
    import asyncio

    session = _RecordingSession({})
    assert asyncio.run(coach._skill_labels_for(session, [])) == []  # type: ignore[arg-type]
    assert session.sql == []
