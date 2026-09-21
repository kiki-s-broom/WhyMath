"""완료를 풀이 제출에 통합 — 서버검증 최종답→Polya 돌아보기→attempt 적재→next-problem (S3-32).

`test_coach.py`의 `_CapturingSession`/`_session_client` hermetic 패턴과 동형(로컬 자체 정의 —
`tests/backend/api`는 `__init__.py`가 없는 비패키지 디렉터리라 파일 간 상대 import를 쓰지 않는
기존 관례를 따른다·`test_coach_grade_standard_code.py` 선례).

검증 범위:
  - create_session: 정답 최종답 첫 도달 → ENTER_REVIEW(돌아보기 대기·완료 아님·attempt 미적재).
  - append_turns: 돌아보기 응답 턴(review_turns_remaining>0) → COMPLETE(ProblemAttempt
    is_correct=True 적재·숙달 헬퍼 호출·응답 problem_complete=True).
  - append_turns: 명확한 오답 최종답 → REDIRECT(재고 유도 발화·완료/attempt 없음·정답 비노출).
  - unverifiable(파싱 불가/사변) 최종답 → 완료·재고 둘 다 없음(기존 코칭 그대로·회귀 불변).
  - 이미 완료된 세션(attempt_id 보유) → 재완료 금지(중복 attempt 0).
  - 게이트 off(`WHYMATH_L4_SOLUTION_COMPLETION_ENABLED=false`) → 완료 기능 완전 inert.
  - 기대정답(`Problem.answer`) 원문이 응답 어디에도 노출되지 않는다(sentinel 검사).

`l3/verify_final_answer.py`·`l4/completion.py`의 순수 판정 로직은 각각의 단위테스트가 이미
전수 검증한다 — 여긴 `api/coach.py` *결선*(정답/오답 감지 → attempt 적재 → 응답 필드)만 본다.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from whymath_backend.api._auth import get_consented_user
from whymath_backend.api._rate_limit import reset_store
from whymath_backend.app import create_app
from whymath_backend.config import Settings, get_settings
from whymath_backend.db.models.activity import ProblemAttempt as ProblemAttemptORM
from whymath_backend.db.models.dialogue import Dialogue as DialogueORM
from whymath_backend.db.models.problem import Problem as ProblemORM
from whymath_backend.db.session import get_session
from whymath_backend.l4.completion import _REDIRECT_PROMPT
from whymath_backend.schema.dialogue import Dialogue as DialogueSchema
from whymath_backend.schema.enums import Persona
from whymath_backend.schema.user import UserProfile as UserProfileSchema

_UID = uuid.uuid4()
_SECRET = "test-secret-0123456789abcdef"

# 정답 sentinel — Problem.answer에만 존재. 응답 어디에도 새면 정답 비노출 계약 위반. 시스템
# 프롬프트 보일러플레이트(번호 매김 등)와 우연히 겹치지 않도록 충분히 특이한 문자열을 쓴다.
_ANSWER_SENTINEL = "77129"


@pytest.fixture(autouse=True)
def _reset_rate_limit_store() -> None:
    """매 테스트 격리 — sliding window 카운트 리셋(`test_coach.py` 관례 미러)."""
    import asyncio

    asyncio.run(reset_store())


def _settings() -> Settings:
    return Settings(
        jwt_secret_key=SecretStr(_SECRET),
        coach_rate_limit_read_per_minute=0,
        coach_rate_limit_write_per_minute=0,
    )


def _user() -> UserProfileSchema:
    return UserProfileSchema(user_id=_UID, persona_primary=Persona.A_일반고고3)


class _Scalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)

    def first(self) -> Any:
        return self._rows[0] if self._rows else None


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)

    def scalar_one(self) -> Any:
        return 0.0  # curate_hypothesis net_support 집계(증거 없음).

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None

    def all(self) -> list[Any]:
        return list(self._rows)


class _CapturingSession:
    """`test_coach.py`의 `_CapturingSession`과 동형 — add/add_all/commit/refresh/get/execute 캡처."""

    def __init__(
        self,
        preload: dict[Any, Any] | None = None,
        execute_rows: list[Any] | None = None,
    ) -> None:
        self.added: list[Any] = []
        self.commits = 0
        self._preload = preload or {}
        self._execute_rows = list(execute_rows or [])

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def add_all(self, objs: list[Any]) -> None:
        self.added.extend(objs)

    async def commit(self) -> None:
        self.commits += 1

    async def flush(self) -> None:
        pass

    async def refresh(self, obj: Any) -> None:
        pass

    async def get(self, model: Any, pk: Any) -> Any | None:
        return self._preload.get((model, pk))

    async def execute(self, stmt: Any) -> _Result:
        return _Result(self._execute_rows)


def _session_client(
    preload: dict[Any, Any] | None = None,
    execute_rows: list[Any] | None = None,
) -> tuple[TestClient, _CapturingSession]:
    app = create_app()
    app.dependency_overrides[get_consented_user] = _user
    app.dependency_overrides[get_settings] = _settings
    captured = _CapturingSession(preload=preload, execute_rows=execute_rows)

    async def _sess() -> AsyncIterator[_CapturingSession]:
        yield captured

    app.dependency_overrides[get_session] = _sess
    return TestClient(app), captured


def _problem(
    answer: str | None = "3", answer_constraint: dict[str, Any] | None = None
) -> SimpleNamespace:
    """`verify_final_answer`가 읽는 최소 필드만 담은 문항 스텁(구조적 타이핑).

    `domain`/`subunit`은 `verify_final_answer`와 무관하지만, WH-1 웜스타트 힌트 조립
    (`_warmstart_hints_or_empty`)이 같은 문항 로드를 재사용하며 이 필드들을 읽는다 — 없으면
    fail-open으로 경고 로그만 남기고 빈 힌트로 진행하니(무해) 굳이 없어도 테스트는 통과하지만,
    로그 소음을 줄이려 None으로 명시해둔다.
    """
    return SimpleNamespace(
        answer=answer,
        answer_constraint=answer_constraint,
        choices=None,
        question_format=None,
        answer_format=None,
        multiple_answers=None,
        domain=None,
        subunit=None,
    )


class TestCreateSessionEntersReview:
    """create_session — 정답 최종답 첫 도달 시 즉시 완료가 아니라 돌아보기 대기로 간다."""

    def test_correct_final_answer_enters_review_not_complete(self) -> None:
        pid = uuid.uuid4()
        preload = {(ProblemORM, pid): _problem(answer="3")}
        client, captured = _session_client(preload=preload)
        resp = client.post(
            "/v1/coach/sessions",
            json={
                "student_input": "이게 답인 것 같아요",
                "problem_id": str(pid),
                "solution_steps": ["2x=6", "x=3"],
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        # 완료가 *아직* 아니다 — Polya 돌아보기를 먼저 거친다(정답 빠르게 KPI 금지).
        assert body["problem_complete"] is False
        assert body["awaiting_reflection"] is True
        assert body["completed_attempt_id"] is None
        # 메타인지 확인 발화로 override됨(결정론 템플릿).
        assert "설명해줄래" in body["decision"]["prompt"]
        assert body["decision"]["socratic_category"] == "meta"
        # 이 턴엔 ProblemAttempt가 *아직* 적재되지 않는다(돌아보기 전).
        assert not any(isinstance(o, ProblemAttemptORM) for o in captured.added)

    def test_correct_final_answer_persists_review_turns_remaining(self) -> None:
        # 세션(dialogue)에 돌아보기 대기 상태가 저장돼야 다음 턴이 완료를 확정할 수 있다.
        pid = uuid.uuid4()
        preload = {(ProblemORM, pid): _problem(answer="3")}
        client, captured = _session_client(preload=preload)
        resp = client.post(
            "/v1/coach/sessions",
            json={
                "student_input": "",
                "problem_id": str(pid),
                "solution_steps": ["x=3"],
            },
        )
        assert resp.status_code == 201, resp.text
        dialogues = [o for o in captured.added if isinstance(o, DialogueORM)]
        assert len(dialogues) == 1
        assert dialogues[0].review_turns_remaining == 1

    def test_answer_not_leaked_on_correct(self) -> None:
        pid = uuid.uuid4()
        preload = {(ProblemORM, pid): _problem(answer=_ANSWER_SENTINEL)}
        client, _ = _session_client(preload=preload)
        resp = client.post(
            "/v1/coach/sessions",
            json={
                "student_input": "",
                "problem_id": str(pid),
                "solution_steps": [f"x={_ANSWER_SENTINEL}"],
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        # correct 판정이 실제로 났는지 먼저 확인(그렇지 않으면 아래 비노출 검사가 공허하다).
        assert body["awaiting_reflection"] is True
        # 정답 원문이 응답 전체(사유·발화 등) 어디에도 그대로 반향되지 않는다.
        assert _ANSWER_SENTINEL not in resp.text


class TestAppendTurnsCompletesAfterReflection:
    """append_turns — 돌아보기 응답 턴(review_turns_remaining>0)에서 완료가 확정된다."""

    def _dialogue_awaiting_reflection(self, did: uuid.UUID, pid: uuid.UUID) -> DialogueORM:
        return DialogueORM.from_schema(
            DialogueSchema(
                dialogue_id=did,
                user_id=_UID,
                problem_id=pid,
                total_turns=2,
                student_turns=1,
                assistant_turns=1,
                review_turns_remaining=1,
            )
        )

    def test_reflection_response_completes_and_records_attempt(self) -> None:
        did = uuid.uuid4()
        pid = uuid.uuid4()
        dialogue = self._dialogue_awaiting_reflection(did, pid)
        preload = {
            (DialogueORM, did): dialogue,
            (ProblemORM, pid): _problem(answer="3"),
        }
        client, captured = _session_client(preload=preload)
        resp = client.post(
            f"/v1/coach/sessions/{did}/turns",
            json={"student_input": "2x=6이니까 양변을 2로 나눠서 x=3이 나왔어요"},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["problem_complete"] is True
        assert body["awaiting_reflection"] is False
        assert body["completed_attempt_id"] is not None
        assert "다음 문제로" in body["decision"]["prompt"]

        attempts = [o for o in captured.added if isinstance(o, ProblemAttemptORM)]
        assert len(attempts) == 1
        attempt = attempts[0]
        assert attempt.is_correct is True
        assert attempt.user_id == _UID
        assert attempt.problem_id == pid
        assert attempt.used_socratic is True
        assert str(attempt.attempt_id) == body["completed_attempt_id"]
        # EOS-12: 완료 채점이 만든 증거가 **응답 조립까지** 이어지는지 — 만들어 놓고 안 싣는
        # 배선 누락을 여기서 잡는다(계약이 있어도 도달하지 않으면 없는 것과 같다).
        evidence = body["completion_evidence"]
        assert evidence is not None
        assert evidence["attempt_id"] == body["completed_attempt_id"]
        assert evidence["correct"] is True  # 이 경로의 완료는 서버 판정 정답이다
        # 이 경로는 오개념을 보지 않는다 — 0건이 "없었다"로 읽히면 안 된다.
        assert evidence["coverage"]["misconception_scan"] == "not_run"
        assert "misconception" in evidence["coverage"]["unmeasured_kinds"]

    def test_completed_attempt_inherits_dialogue_started_at(self) -> None:
        """PED-37: 완료 attempt의 `started_at`은 대화 시작 시각을 *이관*받는다(추정 아님).

        학생이 이 문항 풀이에 착수한 시점 = 이 대화가 시작된 시점이라 `dialogue.started_at`이
        유일하게 정직한 출처다. 이 값이 비면 `harness/wh1_evaluation`의 시간창 집계와
        `privacy/retention`의 파기 창이 조용히 0행이 된다(상시 NULL 버그의 코치 축).

        `_complete_problem`은 dialogue를 모르므로 호출부(append_turn)가 넘긴다 — 여기서 보는
        것은 그 *배선*이다(헬퍼를 직접 부르면 배선이 끊겨도 초록이라 라우트로 검증한다).
        """
        did = uuid.uuid4()
        pid = uuid.uuid4()
        dialogue = self._dialogue_awaiting_reflection(did, pid)
        dialogue.started_at = datetime(2026, 5, 4, 8, 15, tzinfo=timezone.utc)
        preload = {
            (DialogueORM, did): dialogue,
            (ProblemORM, pid): _problem(answer="3"),
        }
        client, captured = _session_client(preload=preload)
        resp = client.post(
            f"/v1/coach/sessions/{did}/turns",
            json={"student_input": "2x=6이니까 양변을 2로 나눠서 x=3이 나왔어요"},
        )
        assert resp.status_code == 201, resp.text
        attempts = [o for o in captured.added if isinstance(o, ProblemAttemptORM)]
        assert len(attempts) == 1
        assert attempts[0].started_at == dialogue.started_at
        # 발생/수신 분리(EOS-48) — 수신 시각은 별도 좌석에, 발생 자리를 덮지 않는다.
        assert attempts[0].ingested_at is not None
        assert attempts[0].ingested_at != attempts[0].started_at

    def test_completed_attempt_started_at_stays_null_when_dialogue_has_none(self) -> None:
        """대화 시작 시각이 없으면 NULL로 둔다 — 서버 now로 메우지 않는다(날조 금지).

        NULL은 미측정이라는 뜻이고, 그 attempt는 시간창 집계·보존 파기에서 조용히 빠진다.
        빠지는 것이 계약이다 — 없는 발생 시각을 지어내 창 안으로 끌어들이지 않는다.
        """
        did = uuid.uuid4()
        pid = uuid.uuid4()
        dialogue = self._dialogue_awaiting_reflection(did, pid)
        assert dialogue.started_at is None  # 스키마 기본값(미설정) — 전제 고정
        preload = {
            (DialogueORM, did): dialogue,
            (ProblemORM, pid): _problem(answer="3"),
        }
        client, captured = _session_client(preload=preload)
        resp = client.post(
            f"/v1/coach/sessions/{did}/turns",
            json={"student_input": "2x=6이니까 양변을 2로 나눠서 x=3이 나왔어요"},
        )
        assert resp.status_code == 201, resp.text
        attempts = [o for o in captured.added if isinstance(o, ProblemAttemptORM)]
        assert len(attempts) == 1
        assert attempts[0].started_at is None

    def test_reflection_turn_does_not_reverify_solution(self) -> None:
        # 돌아보기 응답 턴은 *이 턴 풀이 내용과 무관*하게 완료된다(자연어 근거일 뿐 — 재검증 없음).
        did = uuid.uuid4()
        pid = uuid.uuid4()
        dialogue = self._dialogue_awaiting_reflection(did, pid)
        preload = {
            (DialogueORM, did): dialogue,
            (ProblemORM, pid): _problem(answer="3"),
        }
        client, captured = _session_client(preload=preload)
        resp = client.post(
            f"/v1/coach/sessions/{did}/turns",
            # solution_steps가 아예 없어도(순수 자연어 설명) 완료가 확정된다.
            json={"student_input": "왜냐하면 양변을 2로 나눴기 때문이에요"},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["problem_complete"] is True
        assert any(isinstance(o, ProblemAttemptORM) for o in captured.added)


class TestAppendTurnsRedirectsOnIncorrect:
    """append_turns — 명확한 오답 최종답은 재고 유도(REDIRECT)로 방향을 준다(완료/attempt 없음)."""

    def _dialogue_fresh(
        self, did: uuid.UUID, pid: uuid.UUID, *, total_turns: int = 2
    ) -> DialogueORM:
        return DialogueORM.from_schema(
            DialogueSchema(
                dialogue_id=did,
                user_id=_UID,
                problem_id=pid,
                total_turns=total_turns,
                student_turns=total_turns // 2,
                assistant_turns=total_turns // 2,
                review_turns_remaining=0,
            )
        )

    def test_incorrect_final_answer_redirects_without_completing(self) -> None:
        # total_turns=0 — 이 append가 첫 교환(turn_index=1) → 일반 재고 발화(_REDIRECT_PROMPT).
        did = uuid.uuid4()
        pid = uuid.uuid4()
        dialogue = self._dialogue_fresh(did, pid, total_turns=0)
        preload = {
            (DialogueORM, did): dialogue,
            (ProblemORM, pid): _problem(answer="3"),
        }
        client, captured = _session_client(preload=preload)
        resp = client.post(
            f"/v1/coach/sessions/{did}/turns",
            json={"student_input": "답 다시 볼게요", "solution_steps": ["x=99"]},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["problem_complete"] is False
        assert body["awaiting_reflection"] is False
        assert body["completed_attempt_id"] is None
        assert body["decision"]["prompt"] == _REDIRECT_PROMPT
        assert not any(isinstance(o, ProblemAttemptORM) for o in captured.added)

    def test_incorrect_final_answer_variant_on_later_turn(self) -> None:
        # total_turns=2 — 이미 1교환 있음 → 이 append는 turn_index=2 → 구체 재고 발화로 변주.
        did = uuid.uuid4()
        pid = uuid.uuid4()
        dialogue = self._dialogue_fresh(did, pid, total_turns=2)
        preload = {
            (DialogueORM, did): dialogue,
            (ProblemORM, pid): _problem(answer="3"),
        }
        client, _ = _session_client(preload=preload)
        resp = client.post(
            f"/v1/coach/sessions/{did}/turns",
            json={"student_input": "", "solution_steps": ["x=99"]},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["decision"]["prompt"] != _REDIRECT_PROMPT
        assert "다시 확인해 보자" in body["decision"]["prompt"]

    def test_redirect_prompt_has_no_negative_affect_reinforcement(self) -> None:
        # CLAUDE.md 금기: 부정 정서강화 표현 금지(틀렸·못 하·잘못된·실수·바보·포기).
        did = uuid.uuid4()
        pid = uuid.uuid4()
        dialogue = self._dialogue_fresh(did, pid)
        preload = {
            (DialogueORM, did): dialogue,
            (ProblemORM, pid): _problem(answer="3"),
        }
        client, _ = _session_client(preload=preload)
        resp = client.post(
            f"/v1/coach/sessions/{did}/turns",
            json={"student_input": "", "solution_steps": ["x=99"]},
        )
        prompt = resp.json()["decision"]["prompt"]
        for banned in ("틀렸", "못 하", "잘못된", "실수", "바보", "포기"):
            assert banned not in prompt

    def test_incorrect_answer_not_leaked(self) -> None:
        did = uuid.uuid4()
        pid = uuid.uuid4()
        dialogue = self._dialogue_fresh(did, pid)
        preload = {
            (DialogueORM, did): dialogue,
            (ProblemORM, pid): _problem(answer=_ANSWER_SENTINEL),
        }
        client, _ = _session_client(preload=preload)
        resp = client.post(
            f"/v1/coach/sessions/{did}/turns",
            json={"student_input": "", "solution_steps": ["x=99"]},
        )
        assert resp.status_code == 201, resp.text
        assert _ANSWER_SENTINEL not in json.dumps(resp.json())


class TestUnverifiableIsInert:
    """미검증(파싱 불가·사변) 최종답 — 완료도 재고도 없음(기존 코칭 그대로·회귀 불변)."""

    def test_unparseable_last_step_no_completion_no_redirect(self) -> None:
        did = uuid.uuid4()
        pid = uuid.uuid4()
        dialogue = DialogueORM.from_schema(
            DialogueSchema(
                dialogue_id=did,
                user_id=_UID,
                problem_id=pid,
                total_turns=2,
                student_turns=1,
                assistant_turns=1,
                review_turns_remaining=0,
            )
        )
        preload = {
            (DialogueORM, did): dialogue,
            (ProblemORM, pid): _problem(answer="3"),
        }
        client, captured = _session_client(preload=preload)
        resp = client.post(
            f"/v1/coach/sessions/{did}/turns",
            json={"student_input": "음", "solution_steps": ["잘 모르겠어요"]},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["problem_complete"] is False
        assert body["awaiting_reflection"] is False
        assert body["completed_attempt_id"] is None
        assert not any(isinstance(o, ProblemAttemptORM) for o in captured.added)

    def test_no_solution_steps_no_completion(self) -> None:
        # solution_steps 미제공 — 완료 감지 트리거 자체가 없다(클라 계약: 완료를 원하면 보낸다).
        pid = uuid.uuid4()
        preload = {(ProblemORM, pid): _problem(answer="3")}
        client, _ = _session_client(preload=preload)
        resp = client.post(
            "/v1/coach/sessions",
            json={"student_input": "힌트 주세요", "problem_id": str(pid)},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["problem_complete"] is False
        assert body["awaiting_reflection"] is False


class TestAlreadyCompletedGuardsReattempt:
    """이미 완료된 세션(attempt_id 보유) — 재완료·중복 attempt 적재 금지."""

    def test_already_completed_session_does_not_reattempt(self) -> None:
        did = uuid.uuid4()
        pid = uuid.uuid4()
        existing_attempt_id = uuid.uuid4()
        dialogue = DialogueORM.from_schema(
            DialogueSchema(
                dialogue_id=did,
                user_id=_UID,
                problem_id=pid,
                attempt_id=existing_attempt_id,
                total_turns=4,
                student_turns=2,
                assistant_turns=2,
                review_turns_remaining=0,
            )
        )
        preload = {
            (DialogueORM, did): dialogue,
            (ProblemORM, pid): _problem(answer="3"),
        }
        client, captured = _session_client(preload=preload)
        resp = client.post(
            f"/v1/coach/sessions/{did}/turns",
            json={"student_input": "", "solution_steps": ["x=3"]},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["problem_complete"] is False
        assert body["completed_attempt_id"] is None
        assert not any(isinstance(o, ProblemAttemptORM) for o in captured.added)


class TestGateOffIsFullyInert:
    """게이트 off(`l4_solution_completion_enabled=False`) — 완료 기능 완전 비활성(기존 동작 불변)."""

    def test_gate_off_correct_answer_does_not_enter_review(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("WHYMATH_L4_SOLUTION_COMPLETION_ENABLED", "false")
        get_settings.cache_clear()
        try:
            pid = uuid.uuid4()
            preload = {(ProblemORM, pid): _problem(answer="3")}
            client, captured = _session_client(preload=preload)
            resp = client.post(
                "/v1/coach/sessions",
                json={
                    "student_input": "",
                    "problem_id": str(pid),
                    "solution_steps": ["x=3"],
                },
            )
            assert resp.status_code == 201, resp.text
            body = resp.json()
            assert body["problem_complete"] is False
            assert body["awaiting_reflection"] is False
            assert body["completed_attempt_id"] is None
            assert not any(isinstance(o, ProblemAttemptORM) for o in captured.added)
            dialogues = [o for o in captured.added if isinstance(o, DialogueORM)]
            assert dialogues[0].review_turns_remaining == 0
        finally:
            get_settings.cache_clear()


class TestAnswerFormWiring:
    """EOS-28 — 형태 지시 준수가 **응답에 실제로 흐르는가**, 그리고 **채점을 오염시키지 않는가**.

    `verify_answer_form`의 판정 로직은 `tests/backend/l3/test_answer_form_contract.py`가 전수
    검증한다. 여기서 보는 것은 오직 *결선*이다 — 계약과 검증기를 만들어 놓고 서빙 경로가
    부르지 않으면 아무 일도 일어나지 않는다("정본화 ≠ 집행").
    """

    _REDUCED = {"expected_form": "reduced_fraction"}

    def _post(self, *, answer: str, constraint: dict[str, Any] | None, submitted: str):
        pid = uuid.uuid4()
        client, captured = _session_client(
            preload={(ProblemORM, pid): _problem(answer=answer, answer_constraint=constraint)}
        )
        resp = client.post(
            "/v1/coach/sessions",
            json={
                "student_input": "이렇게 풀었어요",
                "problem_id": str(pid),
                "solution_steps": ["확률을 세면", submitted],
            },
        )
        assert resp.status_code == 201, resp.text
        return resp.json(), captured

    def test_form_violation_is_surfaced_in_the_response(self) -> None:
        """`2/72`는 값이 맞다. 그런데 지시는 기약분수였다 — 그 사실이 응답에 나타나야 한다."""
        body, _ = self._post(answer="1/36", constraint=self._REDUCED, submitted="2/72")
        assert body["answer_form"] == "violated"

    def test_form_compliance_is_surfaced(self) -> None:
        body, _ = self._post(answer="1/36", constraint=self._REDUCED, submitted="1/36")
        assert body["answer_form"] == "satisfied"

    def test_problem_without_form_requirement_reads_not_required(self) -> None:
        """형태 요구가 없는 99% 문항 — `satisfied`가 아니라 `not_required`여야 한다."""
        body, _ = self._post(answer="3", constraint=None, submitted="x=3")
        assert body["answer_form"] == "not_required"

    def test_form_violation_does_not_change_grading(self) -> None:
        """**핵심 금기**: 형태 위반이 정답 판정·완료 흐름을 바꾸지 않는다.

        같은 값(`1/36` ≡ `2/72`)을 형태만 다르게 제출했을 때, 완료 상태머신의 출력이
        **비트 동일**해야 한다. 하나라도 달라지면 형태가 채점에 스며든 것이다.
        """
        graded_keys = (
            "problem_complete",
            "awaiting_reflection",
            "completed_attempt_id",
        )
        ok, ok_cap = self._post(answer="1/36", constraint=self._REDUCED, submitted="1/36")
        bad, bad_cap = self._post(answer="1/36", constraint=self._REDUCED, submitted="2/72")

        assert ok["answer_form"] != bad["answer_form"], "변별력 확인 — 두 제출이 실제로 갈렸다"
        for key in graded_keys:
            assert ok[key] == bad[key], f"형태 위반이 '{key}'를 바꿨다 — 채점 오염"
        # 발화까지 동일해야 한다 — 형태 때문에 다른 말을 하면 그것이 곧 부정 강화 경로다.
        assert ok["decision"]["prompt"] == bad["decision"]["prompt"]
        assert ok["decision"]["socratic_category"] == bad["decision"]["socratic_category"]
        # 적재도 동일 — 형태 위반이 attempt 적재 여부를 바꾸지 않는다.
        assert [type(o).__name__ for o in ok_cap.added] == [type(o).__name__ for o in bad_cap.added]

    def test_form_violation_is_not_rejected_input(self) -> None:
        """형태가 틀려도 **요청은 정상 처리**된다 — 학생 입력 거부 금지.

        4xx로 되돌리거나 빈 응답을 주면 학생은 자기 답을 제출조차 못 한다. 형태 판정은
        사후 관찰이지 입력 게이트가 아니다.
        """
        body, _ = self._post(answer="1/36", constraint=self._REDUCED, submitted="2/72")
        assert body["decision"]["prompt"], "발화가 비었다 — 형태 위반이 응답을 삼켰다"
        assert body["answer_form"] == "violated"

    def test_unknown_form_vocabulary_does_not_break_grading(self) -> None:
        """저작 오타가 채점을 500으로 만들지 않는다 — 판정 불가로 흐르고 채점은 계속된다."""
        body, _ = self._post(
            answer="1/36", constraint={"expected_form": "오타난값"}, submitted="1/36"
        )
        assert body["answer_form"] == "unverifiable"
        assert body["awaiting_reflection"] is True, "형태 판정 불가가 정답 흐름을 막았다"
