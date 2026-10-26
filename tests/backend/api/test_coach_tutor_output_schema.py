"""P3-09 — 코치 세션 서빙 경로의 튜터 출력 스키마 집행 (hermetic·LLM 0·DB 0).

`harness/test_wh1_tutor_output.py`가 스키마·검증기·러너를 본다면, 이 파일은 **서빙 코드가 그것을
실제로 경유하는가**(정본화 ≠ 집행)를 두 세션 핸들러(`POST /v1/coach/sessions`·`.../turns`)에서 본다.

- 대조군: 정상 튜터 발화 → `decision.prompt`와 `tutor_output.explanation`이 같은 문자열, 진단은 DB 조회
  개념·활성 가설, `mastery_update_allowed=false`.
- 1단계 주입(LLM 원시 출력): 상태 권위 주장·깨진 JSON·필드 누락·타입 오류 → LLM 문자열(표지)이 응답
  어디에도 없다.
- 2단계 주입(러너 스키마): 과길이 발화 → 결정론 Polya 발화·`tutor_output=null`.
- 3단계 주입(승격 직전): 러너 영수증 변조(`mastery_update_allowed=True`·조회하지 않은 개념 id·발화
  불일치·구조체 부재) → 결정론 발화·`tutor_output=null`·사유 코드 WARNING.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
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
from whymath_backend.harness.wh1_loop import ENCOURAGE_FALLBACK_UTTERANCE
from whymath_backend.harness.wh1_tutor_context import ProblemBrief
from whymath_backend.harness.wh1_tutor_output import TutorOutputReceipt, TutorTurnOutput
from whymath_backend.l3.models import GenerationResult, RoutingDecision
from whymath_backend.l4.misconception import select_intervention_from_hypotheses
from whymath_backend.l4.misconception.hypothesis import MisconceptionHypothesis
from whymath_backend.schema.dialogue import Dialogue as DialogueSchema
from whymath_backend.schema.enums import Persona
from whymath_backend.schema.user import UserProfile as UserProfileSchema

_UID = uuid.uuid4()
_PID = uuid.uuid4()
_CID = uuid.uuid4()
_CONCEPT_CODE = "math.algebra.linear-equation"
_MID = "distribution-over-power"
_MARK = "ZZP309MARKZZ"
_UTTERANCE = f"{_MARK} 이항할 때 무엇을 근거로 했는지 말해줄래?"
_COACH_LOGGER = "whymath_backend.api.coach"
_HYP = MisconceptionHypothesis(
    misconception_id=_MID, confidence=0.8, turns_since_evidence=0, evidence_count=1
)
_PATHS = ("create", "append")


# ──────────────────────────────────────────────────────────────────────────
# hermetic 세션
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
    async def __aenter__(self) -> _Nested:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        return False


class _Session:
    def __init__(self, preload: dict[Any, Any] | None = None) -> None:
        self._preload = preload or {}

    def add(self, obj: Any) -> None:
        return None

    def add_all(self, objs: list[Any]) -> None:
        return None

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
        return _Nested()


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


class _Provider:
    """튜터 정책 도구 선택 대역 — 원시 출력을 차례로 돌려준다(마지막은 반복·네트워크 0)."""

    def __init__(self, raw: str | Sequence[str]) -> None:
        self._raws = [raw] if isinstance(raw, str) else list(raw)

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        *,
        images: Sequence[str] | None = None,
    ) -> GenerationResult:
        return GenerationResult(self._raws.pop(0) if len(self._raws) > 1 else self._raws[0])


Tamper = Callable[[TutorOutputReceipt, str | None], None]


def _install(
    monkeypatch: pytest.MonkeyPatch, raw: str | Sequence[str], tamper: Tamper | None = None
) -> None:
    """서빙 경로 대역 — 9종 조회는 고정값, 튜터 러너는 **실제 러너**(스텁 provider)를 돌린다.

    `tamper`는 러너가 돌아온 *뒤* 영수증을 변조한다 — 3단계(승격 직전 재검증) 주입 좌석이다.
    """
    real_runner = wh1_primary.run_wh1_primary_turn
    monkeypatch.setenv("WHYMATH_WH1_PRIMARY_ENABLED", "true")
    get_settings.cache_clear()

    async def _theta(session: Any, user_id: Any, problem_id: Any) -> float | None:
        return 0.3

    async def _grade(session: Any, user_id: Any) -> int | None:
        return 11

    async def _concept(session: Any, problem_id: Any) -> uuid.UUID | None:
        return _CID

    async def _skills(session: Any, concept_id: Any) -> list[str]:
        return ["SK-ALG-01"]

    async def _none(*args: Any, **kwargs: Any) -> None:
        return None

    async def _pack(session: Any, problem_id: Any) -> Any:
        return None

    async def _hyps(session: Any, user_id: Any, matches: Any) -> list[MisconceptionHypothesis]:
        return [_HYP]

    async def _empty(*args: Any, **kwargs: Any) -> list[Any]:
        return []

    async def _tutor(**kwargs: Any) -> str | None:
        result = await real_runner(**{**kwargs, "provider": _Provider(raw), "session": None})
        if tamper is not None:
            tamper(kwargs["output_receipt"], result)
        return result

    async def _problem_brief(session: Any, problem_id: Any) -> ProblemBrief | None:
        return ProblemBrief(
            question_format="단답형", bloom_level="APPLY", has_visual=False, condition_count=2
        )

    async def _concept_label(session: Any, concept_id: Any) -> tuple[str, str] | None:
        return (_CONCEPT_CODE, "일차방정식")

    async def _skill_labels(session: Any, skill_ids: Any) -> list[tuple[str, str]]:
        return [("SK-ALG-01", "등식의 성질로 이항하기")]

    monkeypatch.setattr(coach, "_server_theta_for", _theta)
    monkeypatch.setattr(coach, "_grade_for", _grade)
    monkeypatch.setattr(coach, "get_primary_concept_id", _concept)
    monkeypatch.setattr(coach, "get_concept_skill_ids", _skills)
    monkeypatch.setattr(coach, "_server_mastery_for", _none)
    monkeypatch.setattr(coach, "_server_mastery_evidence_for", _none)
    monkeypatch.setattr(coach, "_standard_code_for", _none)
    monkeypatch.setattr(coach, "_pack_for", _pack)
    monkeypatch.setattr(coach, "_apply_hypotheses", _hyps)
    monkeypatch.setattr(coach, "recommend_prerequisite_gaps", _empty)
    monkeypatch.setattr(coach, "assemble_warmstart_probe_hints", _empty)
    monkeypatch.setattr(coach, "run_wh1_primary_turn", _tutor)
    monkeypatch.setattr(coach, "_problem_brief_for", _problem_brief)
    monkeypatch.setattr(coach, "_concept_label_for", _concept_label)
    monkeypatch.setattr(coach, "_skill_labels_for", _skill_labels)


def _body(*, wrong: bool = False) -> dict[str, Any]:
    answer = "3" if wrong else "2"
    return {
        "student_input": f"x+1=3 이니까 x={answer} 라고 생각했어요",
        "student_solution": f"x+1=3 이니까 x={answer}",
        # 정답 풀이(기본) — 정책 명시 발화가 존중되는 턴. wrong=True는 오답 턴(정답 억제 백스톱).
        "solution_steps": ["x+1=3", f"x={answer}"],
        "problem_id": str(_PID),
    }


def _post(path: str, *, wrong: bool = False) -> Any:
    body = _body(wrong=wrong)
    if path == "create":
        return _client().post("/v1/coach/sessions", json=body)
    did = uuid.uuid4()
    dialogue = DialogueORM.from_schema(
        DialogueSchema(
            dialogue_id=did,
            user_id=_UID,
            problem_id=_PID,
            total_turns=2,
            student_turns=1,
            assistant_turns=1,
        )
    )
    turn_body = {k: v for k, v in body.items() if k != "problem_id"}
    return _client({(DialogueORM, did): dialogue}).post(
        f"/v1/coach/sessions/{did}/turns", json=turn_body
    )


def _end_turn(utterance: str, **extra: Any) -> str:
    return json.dumps({"kind": "end_turn", "action_type": "질문", "utterance": utterance, **extra})


# ──────────────────────────────────────────────────────────────────────────
# 대조군
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("path", _PATHS)
def test_control_validated_output_is_delivered(monkeypatch: pytest.MonkeyPatch, path: str) -> None:
    _install(monkeypatch, _end_turn(_UTTERANCE))
    resp = _post(path)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    out = data["tutor_output"]
    assert data["decision"]["prompt"] == _UTTERANCE
    assert out["explanation"] == data["decision"]["prompt"]
    assert out["mastery_update_allowed"] is False
    assert out["schema_version"] == "tutor-output-v1"
    assert out["diagnosis"] == {
        "concept_id": _CONCEPT_CODE,
        "misconception_id": _MID,
        "confidence": pytest.approx(0.8),
    }
    assert out["hint_level"] == data["decision"]["hint_level"]
    assert out["response_strategy"] == "guided_question"
    assert out["next_action"] == "continue_dialogue"
    assert out["explanation_source"] == "llm"
    # 응답 구조체는 스키마를 그대로 통과한다(직렬화 왕복).
    TutorTurnOutput.model_validate(out)


# ──────────────────────────────────────────────────────────────────────────
# 1단계 — LLM 원시 출력 주입: 표지 문자열이 응답 어디에도 없다
# ──────────────────────────────────────────────────────────────────────────
_LLM_INJECTIONS = {
    "mastery_true": _end_turn(_UTTERANCE, mastery_update_allowed=True),
    "mastery_string": _end_turn(_UTTERANCE, mastery_update_allowed="false"),
    "mastery_level_key": _end_turn(_UTTERANCE, mastery_level="숙달"),
    "broken_json": '{"kind": "end_turn", "action_type": "질문", "utterance": "' + _UTTERANCE,
    "missing_action_type": json.dumps({"kind": "end_turn", "utterance": _UTTERANCE}),
    "utterance_type": json.dumps(
        {"kind": "end_turn", "action_type": "질문", "utterance": [_UTTERANCE]}
    ),
}
_EXPECTED_REASON = {
    "mastery_true": "STATE_AUTHORITY_CLAIM",
    "mastery_string": "STATE_AUTHORITY_CLAIM",
    "mastery_level_key": "STATE_AUTHORITY_CLAIM",
    "broken_json": "NOT_JSON_OBJECT",
    "missing_action_type": "MISSING_FIELD",
    "utterance_type": "FIELD_TYPE",
}


@pytest.mark.parametrize("path", _PATHS)
@pytest.mark.parametrize("name", sorted(_LLM_INJECTIONS))
def test_llm_output_violation_never_reaches_student(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, path: str, name: str
) -> None:
    _install(monkeypatch, _LLM_INJECTIONS[name])
    with caplog.at_level(logging.WARNING):
        resp = _post(path)
    assert resp.status_code == 201, resp.text
    assert _MARK not in resp.text  # LLM 문자열 0 — 결정론 강등 발화만
    out = resp.json()["tutor_output"]
    assert out is not None and out["mastery_update_allowed"] is False
    assert out["explanation"] == resp.json()["decision"]["prompt"]
    reason = _EXPECTED_REASON[name]
    assert any(f"출력 스키마 위반({reason})" in r.getMessage() for r in caplog.records)
    assert all(_MARK not in r.getMessage() for r in caplog.records)


# ──────────────────────────────────────────────────────────────────────────
# 2단계 — 러너 스키마 주입: 과길이 발화
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("path", _PATHS)
def test_overlong_utterance_falls_back_to_deterministic_prompt(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, path: str
) -> None:
    _install(monkeypatch, _end_turn(_UTTERANCE + " " + "가" * 450))
    with caplog.at_level(logging.WARNING):
        resp = _post(path)
    assert resp.status_code == 201, resp.text
    assert _MARK not in resp.text
    assert resp.json()["tutor_output"] is None
    assert any(
        "튜터 출력 스키마 거부(SCHEMA_STRING_TOO_LONG)" in r.getMessage() for r in caplog.records
    )


# ──────────────────────────────────────────────────────────────────────────
# 3단계 — 승격 직전 재검증: 영수증 변조
# ──────────────────────────────────────────────────────────────────────────
def _forge(**over: Any) -> Tamper:
    def _tamper(receipt: TutorOutputReceipt, result: str | None) -> None:
        assert receipt.output is not None and result == _UTTERANCE  # 주입 전 정상 통과 단언
        fields: dict[str, Any] = dict(receipt.output)
        fields.update(over)
        receipt.output = TutorTurnOutput.model_construct(**fields)
        for key, value in over.items():
            assert getattr(receipt.output, key) == value  # 주입 실재 단언

    return _tamper


def _drop(receipt: TutorOutputReceipt, result: str | None) -> None:
    assert receipt.output is not None
    receipt.output = None


def _forge_concept(receipt: TutorOutputReceipt, result: str | None) -> None:
    assert receipt.output is not None
    diagnosis = receipt.output.diagnosis.model_construct(
        concept_id="math.fake.hallucinated",
        misconception_id=receipt.output.diagnosis.misconception_id,
        confidence=receipt.output.diagnosis.confidence,
    )
    fields: dict[str, Any] = dict(receipt.output)
    fields["diagnosis"] = diagnosis
    receipt.output = TutorTurnOutput.model_construct(**fields)
    assert receipt.output.diagnosis.concept_id == "math.fake.hallucinated"


_STAGE3: dict[str, tuple[Tamper, str]] = {
    "mastery_true": (_forge(mastery_update_allowed=True), "STATE_AUTHORITY_CLAIM"),
    "unconfirmed_concept": (_forge_concept, "UNKNOWN_CONCEPT_ID"),
    "explanation_mismatch": (_forge(explanation="다른 문장으로 바뀐 발화"), "EXPLANATION_MISMATCH"),
    "out_of_range_hint": (_forge(hint_level=9), "SCHEMA_LITERAL_ERROR"),
    "missing_output": (_drop, "MISSING_OUTPUT"),
}


@pytest.mark.parametrize("path", _PATHS)
@pytest.mark.parametrize("name", sorted(_STAGE3))
def test_promotion_rejects_tampered_receipt(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, path: str, name: str
) -> None:
    tamper, reason = _STAGE3[name]
    _install(monkeypatch, _end_turn(_UTTERANCE), tamper=tamper)
    with caplog.at_level(logging.WARNING, logger=_COACH_LOGGER):
        resp = _post(path)
    assert resp.status_code == 201, resp.text
    assert _MARK not in resp.text  # 러너는 통과시켰지만 승격 게이트가 막았다
    assert resp.json()["tutor_output"] is None
    lines = [r.getMessage() for r in caplog.records if r.name == _COACH_LOGGER]
    assert any(f"튜터 출력 승격 거부({reason})" in line for line in lines), lines


# ──────────────────────────────────────────────────────────────────────────
# PR #1713 검토 중2 — 오답 턴의 환각 개념 id: 그 도구만 실패하고 학생 발화는 main과 같은 질문
# ──────────────────────────────────────────────────────────────────────────
_VERIFY = '{"kind": "verify_step"}'
_END_Q = json.dumps({"kind": "end_turn", "action_type": "질문", "utterance": _UTTERANCE})


@pytest.mark.parametrize("path", _PATHS)
@pytest.mark.parametrize(
    "tool",
    [
        '{"kind": "query_curriculum", "node_id": "일차방정식", "relation": "선수"}',
        '{"kind": "read_student_state", "node_ids": ["math.fake.node"]}',
    ],
)
def test_wrong_answer_turn_with_bad_concept_id_is_not_encouraged(
    monkeypatch: pytest.MonkeyPatch, path: str, tool: str
) -> None:
    _install(monkeypatch, [_VERIFY, tool, _END_Q])
    resp = _post(path, wrong=True)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    prompt = data["decision"]["prompt"]
    # main e609c543과 같은 발화 — 오답 턴의 하네스 소크라테스 개입(활성 가설 결선). 격려가 아니다.
    expected = select_intervention_from_hypotheses([_HYP])
    assert expected is not None
    assert prompt == expected.prompt
    assert prompt != ENCOURAGE_FALLBACK_UTTERANCE
    assert _MARK not in resp.text  # 오답 턴 정책 명시 발화는 억제된다(기존 백스톱)
    out = data["tutor_output"]
    assert (out["response_strategy"], out["next_action"]) == ("guided_question", "revise_solution")
    assert out["explanation_source"] == "harness_template"


@pytest.mark.parametrize("path", _PATHS)
def test_wrong_answer_degraded_turn_is_not_encouraged(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    """검증 뒤 LLM 출력이 깨져 강등돼도 오답 턴이면 격려가 아니라 질문."""
    _install(monkeypatch, [_VERIFY, '{"kind": "end_turn"'])
    resp = _post(path, wrong=True)
    assert resp.status_code == 201, resp.text
    assert resp.json()["decision"]["prompt"] != ENCOURAGE_FALLBACK_UTTERANCE
    assert resp.json()["tutor_output"]["response_strategy"] == "guided_question"
