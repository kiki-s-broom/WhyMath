"""`POST /v1/me/attempts` 응답의 채점 Evidence(EOS-12) — 표면 계약 (hermetic·FakeSession).

투영 의미(모델 B·3상태·계약 집행)는 `tests/backend/schema/test_assessment_evidence.py`와
`tests/backend/l2/test_assessment_evidence.py`가 본다. 여기서 보는 것은 **표면**이다:

① 증거가 응답에 실제로 실리는가(직렬화 모양 포함).
② **증거가 쓰기보다 먼저 만들어지는가** — 숙달 전파가 실패해도 증거는 남는가(acceptance ⑤).
   두 단계가 각각 보여야 부분 쓰기 구조를 "한 트랜잭션"처럼 가리지 않는다.
③ `coverage`가 함께 나가는가 — 0건의 의미를 응답만 보고 판정할 수 있는가(acceptance ⑥).
④ 미성년 PII 경계 — 증거에 학생 원문이 실리지 않는가.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from whymath_backend.api._auth import get_consented_user
from whymath_backend.app import create_app
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.schema.enums import Persona
from whymath_backend.schema.user import UserProfile as UserProfileSchema

_UID = uuid.uuid4()
_CONCEPT = uuid.uuid4()


def _consented_user() -> UserProfile:
    return UserProfile.from_schema(
        UserProfileSchema(user_id=_UID, persona_primary=Persona.A_일반고고3)
    )


class _Rows:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)

    def first(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalars(self) -> "_Rows":
        return self

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None


class _QueueSession:
    """execute 큐 — `mastery_error`를 주면 *증거 조립 이후* 첫 쓰기에서 터진다."""

    def __init__(self, results: list[list[Any]], *, commit_error: Exception | None = None) -> None:
        self._results = results
        self._i = 0
        self.added: list[Any] = []
        self.commits = 0
        self._commit_error = commit_error

    async def execute(self, _stmt: Any) -> _Rows:
        rows = self._results[self._i] if self._i < len(self._results) else []
        self._i += 1
        return _Rows(rows)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1
        # 첫 commit(attempt durable)은 통과시키고 그 다음부터 터뜨린다 — 증거 조립은 그 사이다.
        if self._commit_error is not None and self.commits > 1:
            raise self._commit_error

    async def rollback(self) -> None:
        return None


def _client(session: _QueueSession) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_consented_user] = _consented_user

    async def _sess() -> AsyncIterator[_QueueSession]:
        yield session

    app.dependency_overrides[get_session] = _sess
    return TestClient(app)


def _mapped_session(**kw: Any) -> _QueueSession:
    """문항-개념 매핑 있음 — 증거 3조회(PRIMARY·TESTED·스킬) + writer 조회들."""
    return _QueueSession(
        [
            [_CONCEPT],  # 증거 #1 PRIMARY
            [],  # 증거 #2 TESTED
            [],  # 증거 #3 스킬 해소(브리지 없음)
            [_CONCEPT],  # 개념 writer — 평가 개념
            [],  # 개념 writer — EOS-108 멱등 조회(이 시도는 아직 미반영)
            [],  # 개념 writer — prior 없음
            [_CONCEPT],  # 스킬 writer — 평가 개념
            [],  # 스킬 writer — 스킬 해소 0
            # 스킬 축은 해소 0건이라 멱등 조회가 아예 돌지 않는다(빈 집합 조기 반환).
        ],
        **kw,
    )


def _post(client: TestClient, *, correct: bool = False) -> Any:
    return client.post(
        "/v1/me/attempts",
        json={"problem_id": str(uuid.uuid4()), "is_correct": correct},
    )


class TestEvidenceOnResponse:
    def test_evidence_is_returned_with_concept_attribution(self) -> None:
        resp = _post(_client(_mapped_session()))
        assert resp.status_code == 201, resp.text
        evidence = resp.json()["evidence"]
        assert evidence is not None
        assert evidence["correct"] is False
        assert evidence["learner_id"] == str(_UID)
        (concept,) = evidence["concept_evidence"]
        assert concept["concept_id"] == str(_CONCEPT)
        assert concept["direction"] == "refuting"
        assert concept["attribution"] == "primary_attribution"

    def test_evidence_attempt_id_matches_the_response(self) -> None:
        """증거가 어느 시도의 것인지 이어지지 않으면 역추적이 끊긴다."""
        body = _post(_client(_mapped_session())).json()
        assert body["evidence"]["attempt_id"] == body["attempt_id"]

    def test_coverage_is_always_present(self) -> None:
        coverage = _post(_client(_mapped_session())).json()["evidence"]["coverage"]
        assert coverage["concept"] == "filled"
        assert coverage["skill"] == "empty_measured"
        assert coverage["misconception"] == "not_measured"
        assert coverage["misconception_scan"] == "not_run"
        # 작동 비율이 응답에 실린다 — 소비자가 세 상태를 각자 세지 않아도 된다(acceptance ⑥).
        assert coverage["filled_kinds"] == 1
        assert coverage["unmeasured_kinds"] == ["misconception"]

    def test_misconception_zero_is_not_measured_on_this_path(self) -> None:
        """이 경로는 오개념 매칭을 돌리지 않는다 — 0건이 "없었다"로 읽히면 거짓이다."""
        evidence = _post(_client(_mapped_session())).json()["evidence"]
        assert evidence["possible_misconceptions"] == []
        assert evidence["coverage"]["misconception_scan"] == "not_run"

    def test_unmapped_problem_reports_not_measured(self) -> None:
        session = _QueueSession([[], [], [], [], [], []])
        evidence = _post(_client(session)).json()["evidence"]
        assert evidence["concept_evidence"] == []
        assert evidence["coverage"]["concept"] == "not_measured"

    def test_correct_answer_yields_supporting_joint_evidence(self) -> None:
        session = _QueueSession(
            # 증거 3조회 → 개념 writer(평가 개념·EOS-108 멱등 조회·prior) → 스킬 writer(평가
            # 개념·스킬 해소 0 → 멱등 조회 없음).
            [[_CONCEPT], [], [], [_CONCEPT], [], [], [_CONCEPT], []],
        )
        evidence = _post(_client(session), correct=True).json()["evidence"]
        (concept,) = evidence["concept_evidence"]
        assert concept["direction"] == "supporting"
        assert concept["attribution"] == "joint_support"


class TestEvidenceSurvivesWriteFailure:
    """acceptance ⑤ — 증거는 쓰기 *이전*의 관측이라 쓰기 실패에 함께 사라지지 않는다.

    이것이 성립해야 응답의 `evidence`(쓰기 전)와 `mastery_updates`(쓰기 후)가 서로 다른
    단계를 말하게 되고, 부분 쓰기 구조가 가려지지 않는다.
    """

    def test_evidence_is_built_before_the_mastery_write(self) -> None:
        """숙달 전파 commit이 터지면 요청은 실패하지만, 증거 조립은 *그 전에* 끝나 있다.

        조립이 쓰기 뒤였다면 이 주입에서 증거를 만들 기회 자체가 없다 — 즉 이 테스트가
        RED/GREEN으로 순서를 판정한다.
        """
        boom = RuntimeError("주입된 숙달 전파 실패")
        session = _mapped_session(commit_error=boom)
        with pytest.raises(RuntimeError, match="주입된 숙달 전파 실패"):
            _post(_client(session))
        # attempt는 첫 commit으로 durable하고, 그 다음 commit에서 터졌다 —
        # 증거 조회(3건)는 두 commit 사이에 이미 소비됐다.
        assert session.commits >= 2
        assert session._i >= 3, "증거 조회가 쓰기 전에 일어나지 않았다"

    def test_success_path_commits_more_than_once(self) -> None:
        """위 주입의 대조군 — 정상 경로에서 commit이 2회 이상이라야 주입 지점이 존재한다."""
        session = _mapped_session()
        assert _post(_client(session)).status_code == 201
        assert session.commits >= 2


class TestPrivacyBoundary:
    def test_student_answer_never_appears_in_evidence(self) -> None:
        session = _mapped_session()
        client = _client(session)
        resp = client.post(
            "/v1/me/attempts",
            json={
                "problem_id": str(uuid.uuid4()),
                "is_correct": False,
                "student_answer": "내 답은 5야",
            },
        )
        assert resp.status_code == 201, resp.text
        import json

        evidence_text = json.dumps(resp.json()["evidence"], ensure_ascii=False)
        assert "내 답은 5야" not in evidence_text
        for forbidden in ("student_answer", "answer_text", "solution"):
            assert forbidden not in evidence_text
