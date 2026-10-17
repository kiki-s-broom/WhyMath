"""EOS-57 writer — 해소된 스킬 배열의 `문제시도` 이벤트 적재 (hermetic·DB 없이).

검증 축 3개:
  ① **기록 계약** — event_type·source·is_correct·skill_ids가 약속대로 실린다(계약 경유).
  ② **None ≠ []** — 해소 0건은 `[]`로 적재된다(None으로 접히면 미기록과 구분 불가).
  ③ **경계 준수** — 스킬 배열이 `event_data`로 새지 않고 1급 컬럼에만 실린다.

실 PG 적재(enum 값 존재·ARRAY 왕복)는 마이그레이션·통합 축이 본다 — 여기서는 writer가 만드는
객체의 모양만 못박는다.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.l2.attempt_skill_event import AttemptSource, record_attempt_skill_event
from whymath_backend.schema.enums import EventType

_UID = uuid.uuid4()
_AID = uuid.uuid4()
_PID = uuid.uuid4()


class _FakeSession:
    """add/commit만 시뮬 — writer는 조회를 하지 않는다(해소는 호출부가 이미 끝냈다).

    `commit_error`를 주면 commit이 그 예외를 던진다(적재 실패 경로 재현).
    """

    def __init__(self, commit_error: Exception | None = None) -> None:
        self.added: list[Any] = []
        self.commits = 0
        self.rollbacks = 0
        self._commit_error = commit_error

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        if self._commit_error is not None:
            raise self._commit_error
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


async def _record(**kwargs: Any) -> tuple[_FakeSession, Any]:
    session = _FakeSession()
    event = await record_attempt_skill_event(
        cast(AsyncSession, session),
        user_id=_UID,
        attempt_id=_AID,
        problem_id=_PID,
        **kwargs,
    )
    return session, event


async def test_records_resolved_skills_with_contract_payload() -> None:
    """① 기록 계약 — `문제시도` 1건 add + commit 1회, 페이로드는 계약 2키뿐."""
    session, event = await _record(
        is_correct=True,
        skill_ids=["skill.a", "skill.b"],
        source=AttemptSource.attempt_submit,
    )
    assert len(session.added) == 1 and session.commits == 1
    assert event.event_type is EventType.문제시도
    assert event.skill_ids == ["skill.a", "skill.b"]
    assert event.event_data == {"is_correct": True, "source": "attempt_submit"}
    assert event.attempt_id == _AID and event.user_id == _UID and event.problem_id == _PID


async def test_empty_resolution_is_recorded_as_empty_list_not_none() -> None:
    """② None ≠ [] — 해소 0건은 실측이므로 `[]`로 남는다(미기록 NULL로 접지 않는다).

    이 구분이 무너지면 기록률 리포트가 "writer가 안 돌았다"와 "돌았는데 0건"을 구별할 수 없다.
    """
    _, event = await _record(is_correct=False, skill_ids=[], source=AttemptSource.coach_completion)
    assert event.skill_ids == []
    assert event.skill_ids is not None


async def test_duplicate_skills_are_deduped_in_order() -> None:
    """같은 스킬이 여러 개념에서 해소돼도 배열엔 1회만 — 집계 분모 왜곡 0(순서는 보존)."""
    _, event = await _record(
        is_correct=True,
        skill_ids=["skill.b", "skill.a", "skill.b"],
        source=AttemptSource.attempt_submit,
    )
    assert event.skill_ids == ["skill.b", "skill.a"]


async def test_skill_ids_never_leak_into_event_data() -> None:
    """③ 경계 — 스킬 배열은 1급 컬럼에만. JSONB 병기는 두 진실원을 만든다."""
    _, event = await _record(
        is_correct=True, skill_ids=["skill.a"], source=AttemptSource.attempt_submit
    )
    assert "skill_ids" not in event.event_data


async def test_event_at_is_server_time_and_event_time_stays_null() -> None:
    """`event_at`=서버 수신 시각(이 테이블 전 writer의 실측 의미)·`event_time`은 NULL.

    채점 경로엔 클라 신고 발생 시각 축이 없다 — 수신 시각을 발생으로 복제하면 날조다(EOS-48).
    """
    fixed = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)
    _, event = await _record(
        is_correct=True,
        skill_ids=["skill.a"],
        source=AttemptSource.attempt_submit,
        event_at=fixed,
    )
    assert event.event_at == fixed
    assert event.event_time is None


async def test_source_labels_are_closed_three() -> None:
    """경로 라벨은 폐쇄 3종 — 기록률 리포트의 경로별 분모가 이 집합에 의존한다."""
    assert {s.value for s in AttemptSource} == {
        "attempt_submit",
        "coach_completion",
        "coach_wrong_submission",
    }


async def test_coach_wrong_submission_records_its_own_label() -> None:
    """EOS-146 — 코치 서버 판정 오답 제출은 자기 라벨로 남는다(완료 경로 분모와 섞이지 않는다).

    변별력: `coach_completion`으로 적재하면 이 단언이 깨진다 — 완료 경로의 기록률 분모에 오답
    제출이 섞이는 것이 바로 이 라벨을 따로 둔 이유다.
    """
    _, event = await _record(
        is_correct=False,
        skill_ids=["skill.a"],
        source=AttemptSource.coach_wrong_submission,
    )
    assert event.event_data == {"is_correct": False, "source": "coach_wrong_submission"}


class TestCommitFailureIsAbsorbedButNotSilent:
    """적재 실패 정책(PR #913 리뷰 재판정) — 흡수하되 계측 가능하게 남긴다.

    전파(500)를 택하지 않은 이유는 "덜 중요해서"가 아니라 **전파해도 기록이 남지 않기
    때문**이다: `submit_attempt`에 멱등키가 없어 재시도는 *새* attempt를 만들고 숙달을 한 번 더
    적용한다 — 원래 attempt의 이벤트는 어차피 없고, 학습자 모델만 추가로 오염된다.
    """

    async def test_commit_failure_returns_none_instead_of_raising(self) -> None:
        session = _FakeSession(commit_error=RuntimeError("연결 끊김"))
        result = await record_attempt_skill_event(
            cast(AsyncSession, session),
            user_id=_UID,
            attempt_id=_AID,
            problem_id=_PID,
            is_correct=True,
            skill_ids=["skill.a"],
            source=AttemptSource.attempt_submit,
        )
        assert result is None  # 전파하지 않는다 — 채점 응답은 성공으로 끝난다
        assert session.rollbacks == 1  # 세션을 되살린다(rollback 없으면 이후 사용이 전부 실패)

    async def test_failure_log_carries_the_exception_type_name(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """무타입 경고 금지 — 8개의 서로 다른 실패가 같은 글자로 보이면 안 된다.

        변별력: 예외 타입명(`OperationalError`)이 로그에 실제로 들어가는지를 본다. 이 단언이
        없으면 "실패를 삼키되 원인을 남긴다"는 계약이 코드에서 조용히 증발할 수 있다.
        """

        class OperationalError(RuntimeError):
            """PG 계열 오류 시뮬 — 타입명이 로그에 남는지가 관심사다."""

        session = _FakeSession(commit_error=OperationalError("서버가 연결을 닫음"))
        with caplog.at_level(logging.ERROR, logger="whymath.l2.attempt_skill_event"):
            await record_attempt_skill_event(
                cast(AsyncSession, session),
                user_id=_UID,
                attempt_id=_AID,
                problem_id=_PID,
                is_correct=False,
                skill_ids=[],
                source=AttemptSource.coach_completion,
            )
        rendered = caplog.text
        assert "OperationalError" in rendered  # 예외 *타입명*
        assert "coach_completion" in rendered  # 어느 채점 경로였는지
        assert str(_AID) in rendered  # 어느 attempt가 이벤트를 잃었는지
        assert "writer 미도달" in rendered  # 계측 경로를 로그가 스스로 가리킨다

    async def test_success_path_does_not_log_an_error(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """변별력 — 정상 적재에서는 error 로그가 없다(성공/실패가 같은 화면이면 위장이다)."""
        session = _FakeSession()
        with caplog.at_level(logging.ERROR, logger="whymath.l2.attempt_skill_event"):
            result = await record_attempt_skill_event(
                cast(AsyncSession, session),
                user_id=_UID,
                attempt_id=_AID,
                problem_id=_PID,
                is_correct=True,
                skill_ids=["skill.a"],
                source=AttemptSource.attempt_submit,
            )
        assert result is not None
        assert session.rollbacks == 0
        assert caplog.text == ""
