"""EOS-133 서빙 경로 — 실 PG에서 코치 대화 3턴을 **실제로 불러** 힌트 귀속이 남는가.

`used_hint`·`hint_usage`를 직접 쓰지 않는다. 공개 HTTP 표면(`/v1/coach/sessions`·`…/turns`·
`/v1/me/learning-trace`)만 불러 DB에 남은 것을 본다(기본 SKIP — `WHYMATH_RUN_INTEGRATION=1`):

  ① 막힘 → 단계 2 힌트 → 정답 → 돌아보기 — `used_hint=True` · `hint_usage` 1행이 그 공급 행과
     시각·단계가 같다(식별자·열람시간은 NULL — 날조 금지). 삭제권이 그 행까지 지운다.
  ② 방향(단계 1)만 받고 정답 — `used_hint=False` · 0행(기본 공급은 힌트 사용이 아니다).
  ③ 정답을 낸 **그 턴**에 단계 2가 공급됨 — `used_hint=False` · 0행. 그 공급은 답이 나온 뒤라
     이 풀이에 쓰였을 수 없다(상한 = 정답 제출 턴 · 완료 시각이 아니다).
  ④ 첫 메시지에서 바로 정답 — `used_hint=False` · 0행(창이 빈다).

SCENARIO-005(시나리오 스위트)가 ①의 장면 단언을, 이 파일이 경계 셋(②③④)과 행 내용을 맡는다.
헬퍼는 시나리오 스위트를 경로 로딩으로 빌려 쓴다(그쪽은 다시 페르소나 하네스를 빌린다).
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import uuid
from types import ModuleType
from typing import Any

import pytest

pytestmark = pytest.mark.integration

_SUITE_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "scenarios"
    / "test_phase2_scenario_regression_suite.py"
)
#: 빌려 쓰는 헬퍼 계약 — 하나라도 사라지면 수집 단계에서 이름을 지목하며 깨진다.
_HELPERS = (
    "_CORRECT_STEPS",
    "_STUCK",
    "_answered_problem",
    "_begin",
    "_client",
    "_erase_learner",
    "_hint_levels",
    "_login",
    "_read_rows",
    "_seed_concept",
    "_trace",
    "_user_id",
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_eos133_scenario_suite", _SUITE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"시나리오 스위트 스펙 생성 실패: {_SUITE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    missing = [name for name in _HELPERS if not hasattr(module, name)]
    if missing:
        raise RuntimeError(f"시나리오 스위트 헬퍼가 사라졌다: {missing}")
    return module


_S = _load()

#: 막힘 신호 없는 중립 발화 — 새 학생이면 코치가 단계 1(방향)만 공급한다.
_NEUTRAL = "x의 값을 구하려고 해요"
#: 정답을 내면서 좌절 토큰("모르겠")을 섞은 발화 — 이 턴의 결정 단계가 2로 올라간다.
_SOLVED_BUT_UNSURE = "잘 모르겠지만 이렇게 풀었어요"
#: 돌아보기 응답 — 이 턴이 완료를 확정한다.
_REFLECTION = "양변을 3으로 나누면 x만 남아서 그렇게 풀었어요"


def _open(client: Any, auth: dict[str, str], pid: uuid.UUID, text: str, **extra: Any) -> str:
    resp = client.post(
        "/v1/coach/sessions",
        headers=auth,
        json={"student_input": text, "problem_id": str(pid), **extra},
    )
    assert resp.status_code == 201, resp.text
    did: str = resp.json()["dialogue_id"]
    return did


def _turn(client: Any, auth: dict[str, str], did: str, text: str, **extra: Any) -> dict[str, Any]:
    resp = client.post(
        f"/v1/coach/sessions/{did}/turns",
        headers=auth,
        json={"student_input": text, **extra},
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    return body


def _submit_correct(client: Any, auth: dict[str, str], did: str, text: str) -> dict[str, Any]:
    body = _turn(
        client,
        auth,
        did,
        text,
        solution_steps=_S._CORRECT_STEPS,
        solution_step_types=["계산"],
    )
    assert body["awaiting_reflection"] is True and body["problem_complete"] is False, body
    return body


def _reflect(client: Any, auth: dict[str, str], did: str) -> str:
    body = _turn(client, auth, did, _REFLECTION)
    assert body["problem_complete"] is True, body
    attempt_id = body["completed_attempt_id"]
    assert attempt_id is not None, body
    return str(attempt_id)


def _attribution(uid: uuid.UUID, attempt_id: str) -> tuple[Any, list[tuple[Any, ...]]]:
    """(attempt.used_hint, 그 attempt의 hint_usage 행들[단계·요청시각·식별자·열람시간·학생])."""
    used = _S._read_rows(
        "SELECT used_hint FROM problem_attempt WHERE attempt_id = :aid AND user_id = :uid",
        {"aid": attempt_id, "uid": str(uid)},
    )
    assert len(used) == 1, used
    rows = _S._read_rows(
        "SELECT hint_level, requested_at, hint_id, view_duration_ms, user_id FROM hint_usage"
        " WHERE attempt_id = :aid ORDER BY requested_at",
        {"aid": attempt_id},
    )
    return used[0][0], rows


def _supply(uid: uuid.UUID, pid: uuid.UUID) -> list[tuple[Any, ...]]:
    """이 학생·문항의 공급 원장(`힌트제공`) — (event_at, 단계), 시각순."""
    return _S._read_rows(
        "SELECT event_at, (event_data->>'hint_level')::int FROM attempt_event"
        " WHERE user_id = :uid AND problem_id = :pid AND event_type = '힌트제공'"
        " ORDER BY event_at",
        {"uid": str(uid), "pid": str(pid)},
    )


def _run_case(tag: str, body: Any) -> None:
    content, journal = _S._begin(f"EOS-133-{tag}")
    try:
        cid, _code = _S._seed_concept(content, f"h{tag}", "일차방정식의 풀이")
        pid = _S._answered_problem(content, cid, f"h{tag}", 3.0)
        with _S._client() as client:
            _S._erase_learner(client)  # 지난 회차 잔여 제거(멱등)
            auth = _S._login(client)
            uid = _S._user_id(client, auth)
            body(client, auth, uid, pid, journal)
            _S._erase_learner(client)
        journal.dump()
    finally:
        content.teardown()


def test_hint_before_the_correct_answer_is_attributed_and_erased() -> None:
    def body(client: Any, auth: dict[str, str], uid: uuid.UUID, pid: uuid.UUID, j: Any) -> None:
        did = _open(client, auth, pid, _S._STUCK)
        assert _S._hint_levels(_S._trace(client, auth)) == [2], "막힘 신호가 단계 2를 못 만들었다"
        _submit_correct(client, auth, did, "이렇게 풀었어요")
        attempt_id = _reflect(client, auth, did)

        used, rows = _attribution(uid, attempt_id)
        supply = _supply(uid, pid)
        j.record("①", "막힘→힌트→정답", used_hint=used, 행=len(rows), 공급=[s[1] for s in supply])
        assert used is True, used
        # 첫 공급 행(막힘에 대한 단계 2)이 곧 귀속 행이다 — 시각·단계가 원장과 같다.
        assert [(r[0], r[1]) for r in rows] == [(supply[0][1], supply[0][0])], (rows, supply)
        hint_level, _requested, hint_id, view_ms, owner = rows[0]
        assert hint_level == 2 and hint_id is None and view_ms is None
        assert str(owner) == str(uid)

        # 삭제권 — 학습 행동 데이터(미성년)이므로 계정 삭제가 이 행까지 지워야 한다.
        _S._erase_learner(client)
        left = _S._read_rows(
            "SELECT count(*) FROM hint_usage WHERE user_id = :uid", {"uid": str(uid)}
        )
        assert left[0][0] == 0, left

    _run_case("1", body)


def test_direction_only_is_not_hint_usage() -> None:
    def body(client: Any, auth: dict[str, str], uid: uuid.UUID, pid: uuid.UUID, j: Any) -> None:
        did = _open(client, auth, pid, _NEUTRAL)
        assert _S._hint_levels(_S._trace(client, auth)) == [1], "중립 발화가 단계 1이 아니다"
        _submit_correct(client, auth, did, "이렇게 풀었어요")
        attempt_id = _reflect(client, auth, did)

        used, rows = _attribution(uid, attempt_id)
        j.record("②", "방향만 받고 정답", used_hint=used, 행=len(rows))
        assert used is False and rows == [], (used, rows)

    _run_case("2", body)


def test_supply_after_the_correct_submission_is_not_attributed() -> None:
    def body(client: Any, auth: dict[str, str], uid: uuid.UUID, pid: uuid.UUID, j: Any) -> None:
        did = _open(client, auth, pid, _NEUTRAL)
        _submit_correct(client, auth, did, _SOLVED_BUT_UNSURE)
        # 전제: 정답을 낸 바로 그 턴의 결정 단계가 2로 원장에 적혔다(답이 나온 *뒤*의 공급).
        levels = _S._hint_levels(_S._trace(client, auth))
        assert levels == [1, 2], levels
        attempt_id = _reflect(client, auth, did)

        used, rows = _attribution(uid, attempt_id)
        j.record("③", "정답 턴의 단계 2 공급", used_hint=used, 행=len(rows), 공급=levels)
        assert used is False and rows == [], (
            "정답을 낸 뒤에 공급된 힌트가 그 풀이에 귀속됐다 — 귀속 창의 상한이 정답 제출 턴이 "
            f"아니다(used_hint={used} · 행={rows})."
        )

    _run_case("3", body)


def test_solution_in_the_first_message_is_not_hint_usage() -> None:
    def body(client: Any, auth: dict[str, str], uid: uuid.UUID, pid: uuid.UUID, j: Any) -> None:
        resp = client.post(
            "/v1/coach/sessions",
            headers=auth,
            json={
                "student_input": _SOLVED_BUT_UNSURE,
                "problem_id": str(pid),
                "solution_steps": _S._CORRECT_STEPS,
                "solution_step_types": ["계산"],
            },
        )
        assert resp.status_code == 201, resp.text
        opened = resp.json()
        assert opened["awaiting_reflection"] is True, opened
        attempt_id = _reflect(client, auth, opened["dialogue_id"])

        used, rows = _attribution(uid, attempt_id)
        j.record("④", "첫 메시지 정답", used_hint=used, 행=len(rows))
        assert used is False and rows == [], (used, rows)

    _run_case("4", body)
