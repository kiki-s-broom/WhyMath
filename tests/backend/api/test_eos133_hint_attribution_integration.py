"""EOS-133 서빙 경로 — 실 PG에서 코치 대화 3턴을 **실제로 불러** 힌트 귀속이 남는가.

`used_hint`·`hint_usage`를 직접 쓰지 않는다. 공개 HTTP 표면(`/v1/coach/sessions`·`…/turns`·
`/v1/me/learning-trace`)만 불러 DB에 남은 것을 본다(기본 SKIP — `WHYMATH_RUN_INTEGRATION=1`):

  ① 막힘 → 단계 2 힌트 → 정답 → 돌아보기 — `used_hint=True` · `hint_usage` 1행이 그 공급 행과
     시각·단계가 같다(식별자·열람시간은 NULL — 날조 금지). 삭제권이 그 행까지 지운다.
  ② 방향(단계 1)만 받고 정답 — `used_hint=False` · 0행(기본 공급은 힌트 사용이 아니다).
  ③ 정답을 낸 **그 턴**의 결정 단계가 2로 올라도(좌절 토큰) — 그 턴은 돌아보기 진입으로 가로채여
     공급 원장에 행이 남지 않는다(EOS-30). `used_hint=False` · 0행. 귀속 창의 상한(정답 제출 턴 ·
     완료 시각이 아니다)은 이중 방어로 남았고, 그 경계 자체는 단위 테스트가 맡는다.
  ④ 첫 메시지에서 바로 정답 — `used_hint=False` · 0행(창이 빈다).
  ⑤ 오답을 내고 재고 유도를 받은 턴(EOS-30) — 그 턴의 단계 2가 원장에 적히지 않고, 다음 턴 사다리는
     **실제로 받은** 단계(1)에서 이어 오른다(받지 않은 2를 건너뛰어 3으로 도약하지 않는다).

SCENARIO-005(시나리오 스위트)가 ①의 장면 단언을, 이 파일이 경계(②③④)와 행 내용·사다리(⑤)를 맡는다.
헬퍼는 시나리오 스위트를 경로 로딩으로 빌려 쓴다(그쪽은 다시 페르소나 하네스를 빌린다).
"""

from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import sys
import uuid
from types import ModuleType
from typing import Any

import pytest

from whymath_backend.l4.completion import _REDIRECT_PROMPT, _REDIRECT_PROMPT_SPECIFIC

pytestmark = pytest.mark.integration

_SUITE_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "scenarios"
    / "test_phase2_scenario_regression_suite.py"
)
#: 빌려 쓰는 헬퍼 계약 — 하나라도 사라지면 수집 단계에서 이름을 지목하며 깨진다.
_HELPERS = (
    "Curriculum",
    "Problem",
    "ProblemSchema",
    "ReviewStatus",
    "SourceType",
    "Subject",
    "_COMPLETION_ANSWER",
    "_CORRECT_STEPS",
    "_STUCK",
    "_add_all",
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
#: 오답 최종 단계 — 서버 verify가 incorrect로 판정해 재고 유도(REDIRECT)가 발화한다.
_WRONG_STEPS = ["3*x = 174639", "x = 999"]
#: 좌절 토큰만 담은 발화 — 직전 공급 단계에서 한 단계 올린다(`decide_hint_level` 규칙 3).
_FRUSTRATED = "모르겠어요"


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


def _unmapped_problem(content: Any, tag: str) -> uuid.UUID:
    """개념에 매핑하지 않은 문항(저작 콘텐츠) — 오답이 숙달을 움직이지 못한다.

    코치 오답이 원장에 적재되면(EOS-146) 숙달이 낮아져 힌트 사다리의 **숙달 라벨 축**(규칙 5)이 켜진다.
    이 파일의 ⑤는 그 축이 아니라 "재고 유도 턴이 가짜 공급 행을 남기지 않는다"를 본다 — 두 축을 섞지
    않으려고 숙달이 측정되지 않는 문항으로 격리한다. 숙달 축 자체는 아래 ⑥이 따로 고정한다.
    """
    pid = uuid.uuid4()
    asyncio.run(
        _S._add_all(
            _S.Problem.from_schema(
                _S.ProblemSchema(
                    problem_id=pid,
                    source_type=_S.SourceType.자체생성,
                    review_status=_S.ReviewStatus.approved,
                    curriculum_version=_S.Curriculum.REVISION_2022,
                    valid_from_year=2022,
                    subject=_S.Subject.공통,
                    unit_codes=[f"U-{content.sfx}{tag}"],
                    difficulty_overall=3.0,
                    question_text=f"3x = 174639 일 때 x의 값을 구하시오. ({tag})",
                    answer=_S._COMPLETION_ANSWER,
                )
            )
        )
    )
    content.problem_ids.append(pid)
    return pid


def _run_case(tag: str, body: Any, *, concept_mapped: bool = True) -> None:
    content, journal = _S._begin(f"EOS-133-{tag}")
    try:
        cid, _code = _S._seed_concept(content, f"h{tag}", "일차방정식의 풀이")
        pid = (
            _S._answered_problem(content, cid, f"h{tag}", 3.0)
            if concept_mapped
            else _unmapped_problem(content, f"h{tag}")
        )
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


def test_handled_turn_supply_is_neither_recorded_nor_attributed() -> None:
    def body(client: Any, auth: dict[str, str], uid: uuid.UUID, pid: uuid.UUID, j: Any) -> None:
        did = _open(client, auth, pid, _NEUTRAL)
        submitted = _submit_correct(client, auth, did, _SOLVED_BUT_UNSURE)
        # 전제: 정답을 낸 바로 그 턴의 결정 단계는 2로 올랐다(좌절 토큰). EOS-30 이전에는 이 2가
        # 원장에 적혔다(학생은 돌아보기 템플릿을 받았는데도) — 이 전제가 있어야 아래 [1]이 공허하지
        # 않다(결정 단계가 처음부터 1이면 가로챈 턴의 행이 없어도 [1]이다).
        assert submitted["decision"]["hint_level"] == 2, submitted["decision"]
        levels = _S._hint_levels(_S._trace(client, auth))
        assert levels == [1], (
            "가로챈 턴(돌아보기 진입)의 결정 단계가 공급 원장에 적혔다 — 학생이 받지 않은 단계가 "
            f"'제공'으로 남는다: {levels}"
        )
        attempt_id = _reflect(client, auth, did)
        # 돌아보기 응답 턴(완료 인정)도 가로챈 턴이라 원장은 그대로다.
        assert _S._hint_levels(_S._trace(client, auth)) == [1]

        used, rows = _attribution(uid, attempt_id)
        j.record("③", "가로챈 턴의 단계 2", used_hint=used, 행=len(rows), 공급=levels)
        assert used is False and rows == [], (
            "정답을 낸 턴의 가짜 공급이 그 풀이에 귀속됐다 — " f"used_hint={used} · 행={rows}"
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


def test_redirect_turn_records_no_supply_and_the_ladder_does_not_skip() -> None:
    def body(client: Any, auth: dict[str, str], uid: uuid.UUID, pid: uuid.UUID, j: Any) -> None:
        did = _open(client, auth, pid, _NEUTRAL)
        assert _S._hint_levels(_S._trace(client, auth)) == [1], "중립 발화가 단계 1이 아니다"
        redirected = _turn(
            client,
            auth,
            did,
            _FRUSTRATED,
            solution_steps=_WRONG_STEPS,
            solution_step_types=["계산"],
        )
        # 전제 ① 오답이라 재고 유도로 가로챘다(완료도 돌아보기도 아니다) ② 이 턴의 결정 단계는 2였다.
        # 두 전제가 있어야 아래 단언이 공허하지 않다 — EOS-30 이전에는 이 2가 원장에 적혔다.
        assert redirected["problem_complete"] is False, redirected
        assert redirected["awaiting_reflection"] is False, redirected
        assert redirected["decision"]["prompt"] in {_REDIRECT_PROMPT, _REDIRECT_PROMPT_SPECIFIC}
        assert redirected["decision"]["hint_level"] == 2, redirected["decision"]
        after_redirect = _S._hint_levels(_S._trace(client, auth))
        assert after_redirect == [1], (
            "재고 유도 턴의 결정 단계가 공급 원장에 적혔다 — "
            f"학생은 힌트를 받지 않았다: {after_redirect}"
        )

        # 이어지는 턴 — 사다리는 학생이 **실제로 받은** 단계(1)에서 한 칸 오른 2다. 받지 않은 2를
        # 건너뛰어 3(부분 풀이)으로 도약하면 "가장 빠른 단계에서 멈춤" 계약이 깨진다.
        follow = _turn(client, auth, did, _FRUSTRATED)
        levels = _S._hint_levels(_S._trace(client, auth))
        j.record(
            "⑤",
            "재고 유도 뒤 사다리",
            재고턴결정=redirected["decision"]["hint_level"],
            다음턴결정=follow["decision"]["hint_level"],
            공급=levels,
        )
        assert follow["decision"]["hint_level"] == 2, (
            "사다리가 받지 않은 단계를 건너뛰어 올랐다 — 재고 유도 턴의 가짜 공급이 다음 턴 입력을 "
            f"부풀렸다(다음 턴 단계={follow['decision']['hint_level']})."
        )
        assert levels == [1, 2], levels

    # 숙달이 측정되지 않는 문항 — EOS-146 이후 코치 오답이 숙달을 움직이므로(아래 ⑥) 그 축을 끈다.
    _run_case("5", body, concept_mapped=False)


def test_first_wrong_answer_lowers_mastery_so_the_next_hint_rises_an_extra_step() -> None:
    """⑥ (EOS-146) 오답 한 건이 적재되면 같은 대화의 다음 힌트가 숙달 라벨 규칙으로 한 칸 더 오른다.

    ⑤와 같은 장면이지만 문항이 개념에 매핑돼 있다. 코치가 서버 판정 오답을 원장에 적재하면 숙달이
    낮아져(BKT 0.4 미만) 라벨이 `초보`가 되고, 힌트 단계 규칙 5(`decide_hint_level` — `초보`이면
    `min(4, base+1)`)가 좌절 신호의 상승분(1→2)에 한 칸을 더한다: 1→3. **가짜 공급이 아니다** — 3은
    학생에게 실제로 공급된 단계라 원장(`[1, 3]`)이 그대로 말한다. 재고 유도 턴의 단계 2는 여전히 원장에
    적히지 않는다.

    이 테스트는 그 상호작용을 **고정**한다 — 옳다고 선언하는 것이 아니다. 오답 한 건으로 `초보`가 되어
    부분 풀이(3)가 두 칸 도약하는 것이 교수학적으로 허용되는지는 판정 대기다(EOS-146 acceptance ⑩).
    그 판정이 바뀌면 이 테스트가 먼저 깨져 결정이 눈에 보이게 한다.
    """

    def body(client: Any, auth: dict[str, str], uid: uuid.UUID, pid: uuid.UUID, j: Any) -> None:
        did = _open(client, auth, pid, _NEUTRAL)
        assert _S._hint_levels(_S._trace(client, auth)) == [1]
        redirected = _turn(
            client,
            auth,
            did,
            _FRUSTRATED,
            solution_steps=_WRONG_STEPS,
            solution_step_types=["계산"],
        )
        assert redirected["decision"]["prompt"] in {_REDIRECT_PROMPT, _REDIRECT_PROMPT_SPECIFIC}
        # 재고 유도 턴의 결정 단계는 여전히 원장에 적히지 않는다(EOS-30 불변).
        assert _S._hint_levels(_S._trace(client, auth)) == [1]

        follow = _turn(client, auth, did, _FRUSTRATED)
        levels = _S._hint_levels(_S._trace(client, auth))
        j.record(
            "⑥",
            "오답 뒤 사다리(숙달 라벨)",
            다음턴결정=follow["decision"]["hint_level"],
            공급=levels,
        )
        assert follow["decision"]["hint_level"] == 3, follow["decision"]
        assert levels == [1, 3], levels

    _run_case("6", body)
