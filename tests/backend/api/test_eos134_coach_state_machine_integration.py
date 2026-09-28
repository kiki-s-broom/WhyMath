"""EOS-134 서빙 경로 — 실 PG에서 **두 채점 경로가 같은 입력에 같은 전이를 내는가**.

같은 학습자 신원으로 두 번 돈다. 한 번은 `/v1/me/attempts`(클라 자가보고 정답 · 확신도 없음), 한 번은
코치 대화 완료(서버 판정 정답 · 확신도 입력 없음)다. 사이에 삭제권(`DELETE /v1/me`)으로 원장을 비워
둘 다 새 학습자에서 출발한다. 두 원장이 **같은 문항 2개를 같은 순서로** 맞힌 결과를 비교한다
(기본 SKIP — `WHYMATH_RUN_INTEGRATION=1`):

  ① 두 경로의 전이 목록(출발·도착 상태 · 트리거 · 규칙 · 개념)이 **완전히 같다**.
  ② 그 목록이 설계대로다 — 학습 진입 → 평가 → R2(확신도 미측정 정답은 같은 개념 연습) → 평가 → R2.

①이 acceptance ②의 실측 축이고, 구조 축(두 경로가 같은 공용 진입점을 부르고 하위 함수를 직접
부르지 않는다)은 `test_me_learning_state.py`가 AST로 동결한다. 헬퍼는 시나리오 스위트를 경로
로딩으로 빌려 쓴다(그쪽은 다시 페르소나 하네스를 빌린다).
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
    "_COMPLETION_ANSWER",
    "_CORRECT_STEPS",
    "_answered_problem",
    "_attempt",
    "_begin",
    "_client",
    "_erase_learner",
    "_learning_state",
    "_login",
    "_seed_concept",
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_eos134_scenario_suite", _SUITE_PATH)
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

#: 막힘 신호 없는 중립 발화(코치 대화 시작).
_NEUTRAL = "x의 값을 구하려고 해요"
#: 돌아보기 응답 — 이 턴이 완료를 확정한다.
_REFLECTION = "양변을 3으로 나누면 x만 남아서 그렇게 풀었어요"

#: 정답 2회(확신도 미측정)의 설계상 전이 — (출발, 도착, 규칙). 원장은 최신순이라 뒤집어 본다.
_EXPECTED = [
    ("NEW", "LEARNING", None),
    ("LEARNING", "ASSESSING", None),
    ("ASSESSING", "PRACTICING", "R2-correct-low-confidence"),
    ("PRACTICING", "ASSESSING", None),
    ("ASSESSING", "PRACTICING", "R2-correct-low-confidence"),
]


def _chain(client: Any, auth: dict[str, str]) -> list[tuple[Any, ...]]:
    """시간순 전이 목록 — 비교에 쓰는 축은 출발·도착·트리거·규칙·개념(시각·id 제외)."""
    ls = _S._learning_state(client, auth)
    return [
        (t["from_state"], t["to_state"], t["trigger"], t["rule_id"], t["concept_id"])
        for t in reversed(ls["transitions"])
    ]


def _complete_via_coach(client: Any, auth: dict[str, str], pid: uuid.UUID) -> None:
    opened = client.post(
        "/v1/coach/sessions",
        headers=auth,
        json={"student_input": _NEUTRAL, "problem_id": str(pid)},
    )
    assert opened.status_code == 201, opened.text
    did = opened.json()["dialogue_id"]
    solved = client.post(
        f"/v1/coach/sessions/{did}/turns",
        headers=auth,
        json={
            "student_input": "이렇게 풀었어요",
            "solution_steps": _S._CORRECT_STEPS,
            "solution_step_types": ["계산"],
        },
    )
    assert solved.status_code == 201, solved.text
    assert solved.json()["awaiting_reflection"] is True, solved.json()
    done = client.post(
        f"/v1/coach/sessions/{did}/turns", headers=auth, json={"student_input": _REFLECTION}
    )
    assert done.status_code == 201, done.text
    body = done.json()
    assert body["problem_complete"] is True and body["completed_attempt_id"], body


def test_coach_completion_and_attempts_record_the_same_transitions() -> None:
    content, journal = _S._begin("EOS-134")
    try:
        cid, _code = _S._seed_concept(content, "e134", "일차방정식의 풀이")
        pids = [_S._answered_problem(content, cid, f"e134{i}", 3.0 + 0.2 * i) for i in range(2)]
        with _S._client() as client:
            _S._erase_learner(client)  # 지난 회차 잔여 제거(멱등)

            # 경로 A — /v1/me/attempts: 정답 2회 · 확신도 없음(하네스가 싣지 않는다)
            auth = _S._login(client)
            for pid in pids:
                _S._attempt(client, auth, pid, correct=True, answer=_S._COMPLETION_ANSWER)
            via_attempts = _chain(client, auth)
            journal.record("A", "attempts 경로", 전이=via_attempts)

            # 삭제권으로 원장을 비우고 같은 신원으로 새 학습자를 만든다
            _S._erase_learner(client)
            auth = _S._login(client)
            assert (
                _chain(client, auth) == []
            ), "삭제권 뒤에도 전이가 남았다 — 두 경로의 출발점이 다르다"

            # 경로 B — 코치 완료: 같은 문항 2개를 같은 순서로
            for pid in pids:
                _complete_via_coach(client, auth, pid)
            via_coach = _chain(client, auth)
            journal.record("B", "코치 완료 경로", 전이=via_coach)

            assert via_coach == via_attempts, (
                "같은 입력(정답 · 확신도 미측정)에 두 채점 경로의 전이가 다르다 — 비대칭이 재발했다.\n"
                f"attempts: {via_attempts}\ncoach:    {via_coach}"
            )
            assert [(f, t, r) for f, t, _trig, r, _c in via_coach] == _EXPECTED, via_coach
            _S._erase_learner(client)
        journal.dump()
    finally:
        content.teardown()
