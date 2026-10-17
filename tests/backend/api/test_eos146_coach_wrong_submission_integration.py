"""EOS-146 서빙 경로 — 실 PG에서 **앱 요청 형태(코치 API)의 오답이 R3·R6까지 닿는가**.

앱은 `POST /v1/me/attempts`를 부르지 않는다(MOB-20). 앱 학생의 오답이 학습 상태 머신에 닿는 길은 코치
대화의 서버 판정 오답 하나뿐이다. 이 파일은 그 길을 **공개 HTTP 표면만으로** 지나가며 세 가지를 본다
(기본 SKIP — `WHYMATH_RUN_INTEGRATION=1`):

  ① 같은 오답에 두 채점 경로(`/v1/me/attempts` · 코치)가 **같은 전이 사슬**을 낸다 — 오개념이 걸리는
     오답은 R3, 원인 미상 오답은 R6. EOS-134의 "같은 입력 → 같은 전이"를 오답으로 확장한 것이다.
  ② 재제출 오답은 세지 않고(문제당 최초 1건), 오답 뒤 스스로 고쳐 완료하는 정상 경로가 그대로 성립한다
     (오답 행이 '완료됨' 표지를 건드리지 않는다).
  ③ 판정 불가(unverifiable) 답은 원장에 아무것도 남기지 않는다 — 모른다 ≠ 아니다.

헬퍼는 시나리오 스위트를 경로 로딩으로 빌려 쓴다(EOS-134 통합 테스트와 같다). 학습자 상태는 단 한 줄도
직접 쓰지 않는다 — 전부 HTTP 부수효과이고, 읽기 전용 SELECT만 공개 표면이 내지 않는 값(행 수)에 쓴다.
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
    "_UNMATCHED_WRONG_ANSWER",
    "_WRONG_ANSWER",
    "_add_all",
    "_attempt",
    "_begin",
    "_client",
    "_erase_learner",
    "_learning_state",
    "_login",
    "_next_problem",
    "_problem_concept",
    "_read_rows",
    "_seed_concept",
    "_user_id",
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_eos146_scenario_suite", _SUITE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"시나리오 스위트 스펙 생성 실패: {_SUITE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    missing = [name for name in _HELPERS if not hasattr(module, name)]
    if missing:
        raise RuntimeError(f"시나리오 스위트 헬퍼가 사라졌다: {missing}")
    # 문항 본문 — 오개념 검출기가 걸리는 (x+2)^2 전개 문항(Week 2 게이트가 쓰는 그 문항)이다.
    if not hasattr(module._P, "_W2") or not hasattr(module._P._W2, "_QUESTION_TEXT"):
        raise RuntimeError("Week 2 게이트 문항 본문(_QUESTION_TEXT)을 찾지 못했다")
    return module


_S = _load()

#: 코치 문항의 기대정답 — 다항식이라 서버 검증기가 "x^2+4"·"x+5"는 incorrect, 이 값은 correct로 판정한다.
_ANSWER = "x^2+4x+4"
#: 정답 도달 풀이 — 마지막 단계가 기대정답과 동치라 서버 verify가 correct로 판정한다.
_CORRECT_STEPS = ["(x+2)^2 = x^2+4x+4", "x^2+4x+4"]
#: 검증기가 다항식 정답과 비교하지 못해 `unverifiable`로 판정하는 답(실측: "7"·"8"·"x=99").
_UNVERIFIABLE_ANSWER = "7"
#: 돌아보기 응답 — 정답 도달 다음 턴이 완료를 확정한다.
_REFLECTION = "양변을 전개하면 그렇게 돼서 그렇게 풀었어요"
_NEUTRAL = "x를 구하려고 해요"


def _problem(content: Any, cid: uuid.UUID, tag: str, difficulty: float) -> uuid.UUID:
    """오답이 **서버 검증으로 incorrect가 될 수 있는** 문항(저작 콘텐츠) — 정답이 검증 가능한 식이다."""
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
                    difficulty_overall=difficulty,
                    question_text=_S._P._W2._QUESTION_TEXT,
                    answer=_ANSWER,
                )
            )
        )
    )
    asyncio.run(_S._add_all(_S._problem_concept(pid, cid)))
    content.problem_ids.append(pid)
    return pid


def _chain(client: Any, auth: dict[str, str]) -> list[tuple[Any, ...]]:
    """시간순 전이 목록 — 비교에 쓰는 축은 출발·도착·트리거·규칙·개념(시각·id 제외)."""
    ls = _S._learning_state(client, auth)
    return [
        (t["from_state"], t["to_state"], t["trigger"], t["rule_id"], t["concept_id"])
        for t in reversed(ls["transitions"])
    ]


def _attempt_rows(client: Any, auth: dict[str, str], pid: uuid.UUID) -> dict[bool, int]:
    """이 학생·문항의 attempt 행 수(정오별) — 공개 표면이 내지 않는 값이라 읽기 전용 SELECT다."""
    rows = _S._read_rows(
        "SELECT is_correct, count(*) FROM problem_attempt "
        "WHERE user_id = :u AND problem_id = :p GROUP BY is_correct",
        {"u": str(_S._user_id(client, auth)), "p": str(pid)},
    )
    return {bool(is_correct): int(n) for is_correct, n in rows}


def _open(client: Any, auth: dict[str, str], pid: uuid.UUID) -> str:
    opened = client.post(
        "/v1/coach/sessions",
        headers=auth,
        json={"student_input": _NEUTRAL, "problem_id": str(pid)},
    )
    assert opened.status_code == 201, opened.text
    did: str = opened.json()["dialogue_id"]
    return did


def _turn(
    client: Any, auth: dict[str, str], did: str, steps: list[str], text: str
) -> dict[str, Any]:
    resp = client.post(
        f"/v1/coach/sessions/{did}/turns",
        headers=auth,
        json={"student_input": text, "solution_steps": steps, "solution_step_types": ["계산"]},
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    return body


def _recommendation_view(rec: dict[str, Any]) -> tuple[Any, ...]:
    """추천이 상태 머신 결정을 어떻게 집행했는가 — 문항 id는 비교에서 뺀다(같은 개념 안 후보 중 하나)."""
    return (
        rec["learning_state_directive"],
        rec["action"],
        rec["reason"]["type"],
        rec["reason"]["basis"],
        rec["target_concept"],
    )


@pytest.mark.parametrize(
    ("wrong_answer", "final_rule", "directive", "reason_basis_is_state"),
    [
        pytest.param(
            _S._WRONG_ANSWER, "R3-wrong-misconception", "applied", True, id="오개념 걸림 → R3"
        ),
        pytest.param(
            "x+5",
            "R6-wrong-undiagnosed",
            "same_concept_probe_unsupported",
            False,
            id="원인 미상 → R6",
        ),
    ],
)
def test_coach_wrong_answer_and_attempts_record_the_same_transitions(
    wrong_answer: str, final_rule: str, directive: str, reason_basis_is_state: bool
) -> None:
    """같은 오답 · 확신도 미측정에 두 채점 경로의 전이 사슬과 **다음 추천의 집행이 완전히 같다**.

    같은 학습자 신원으로 두 번 돈다 — 한 번은 클라 자가보고, 한 번은 코치 서버 판정. 사이에 삭제권으로
    원장을 비워 둘 다 새 학습자에서 출발한다. 구조 축(둘 다 공용 진입점을 부른다)은
    `test_me_learning_state.py`의 AST 동결이 맡는다.

    추천은 **앱이 보내는 그대로**(파라미터 없는 `GET /v1/me/next-problem`)로 읽는다. 이 검사가 이
    태스크의 제목이 말한 것이다 — R3·R6 추천 집행(EOS-24·EOS-26)이 앱 학생에게 도달한다. 그 집행이 한
    번도 돌지 않는 상태(코치 오답이 원장에 안 닿음)에서는 추천이 상태 경로를 타지 않아 깨진다.
    """
    content, journal = _S._begin("EOS-146")
    try:
        cid, _code = _S._seed_concept(content, "e146", "다항식의 전개")
        # 같은 개념에 미시도 문항이 남아야 교정·같은 개념 연습이 집행된다(없으면 기존 추천으로 폴백).
        pids = [_problem(content, cid, f"a{i}", 3.0 + 0.2 * i) for i in range(3)]
        pid = pids[0]
        with _S._client() as client:
            _S._erase_learner(client)  # 지난 회차 잔여 제거(멱등)

            # 경로 A — /v1/me/attempts: 자가보고 오답 · 확신도 없음
            auth = _S._login(client)
            _S._attempt(client, auth, pid, correct=False, answer=wrong_answer)
            via_attempts = _chain(client, auth)
            rec_attempts = _S._next_problem(client, auth, weak_first=False)
            journal.record(
                "A", "attempts 경로", 전이=via_attempts, 추천=_recommendation_view(rec_attempts)
            )

            _S._erase_learner(client)
            auth = _S._login(client)
            assert _chain(client, auth) == [], "삭제권 뒤에도 전이가 남았다 — 출발점이 다르다"

            # 경로 B — 코치: 같은 문항에 같은 오답을 풀이 마지막 단계로 제출
            did = _open(client, auth, pid)
            body = _turn(client, auth, did, [wrong_answer], "이렇게 풀었어요")
            via_coach = _chain(client, auth)
            rec_coach = _S._next_problem(client, auth, weak_first=False)
            journal.record("B", "코치 경로", 전이=via_coach, 추천=_recommendation_view(rec_coach))
            # 오답 한 번으로 풀던 대화가 완료로 읽히면 안 된다 — 완료 표지를 건드리지 않았다.
            assert body["problem_complete"] is False and body["completed_attempt_id"] is None, body

            assert via_coach == via_attempts, (
                "같은 오답에 두 채점 경로의 전이가 다르다 — 코치 오답 적재가 갈라졌다.\n"
                f"attempts: {via_attempts}\ncoach:    {via_coach}"
            )
            assert via_coach[-1][3] == final_rule, via_coach
            assert [(f, t) for f, t, _trig, _r, _c in via_coach[:2]] == [
                ("NEW", "LEARNING"),
                ("LEARNING", "ASSESSING"),
            ], via_coach
            assert _attempt_rows(client, auth, pid) == {False: 1}

            # 추천 집행 — 두 경로가 같고, 설계대로다(R3: 교정 지시 적용 · R6: 같은 개념 연습).
            assert _recommendation_view(rec_coach) == _recommendation_view(
                rec_attempts
            ), f"같은 오답에 두 경로의 추천 집행이 다르다.\nattempts: {rec_attempts}\ncoach: {rec_coach}"
            assert rec_coach["learning_state_directive"] == directive, rec_coach
            assert (rec_coach["reason"]["basis"] == "learning_state") is reason_basis_is_state
            assert rec_coach["target_concept"] == str(cid), rec_coach
            assert rec_coach["problem_id"] in {str(p) for p in pids[1:]}, rec_coach
            if directive == "applied":
                assert rec_coach["reason"]["type"] == "misconception_remediation", rec_coach
            _S._erase_learner(client)
        journal.dump()
    finally:
        content.teardown()


def test_resubmission_is_not_counted_and_self_correction_still_completes() -> None:
    """② 재제출 오답은 세지 않고, 오답 뒤 스스로 고쳐 완료하는 정상 경로가 그대로 성립한다.

    Polya의 정상 경로(틀리고 → 다시 보고 → 맞힘)를 원장에 벌점처럼 쌓지 않는다. 그리고 오답 행이
    `dialogue.attempt_id`(완료 표지)를 건드리지 않았다는 사실이 여기서 **완료가 실제로 확정된다**로
    관측된다 — 링크됐다면 이 대화는 첫 오답에서 이미 '완료됨'이라 정답 턴이 no-op이 된다.
    """
    content, journal = _S._begin("EOS-146")
    try:
        cid, _code = _S._seed_concept(content, "e146b", "다항식의 전개")
        p1 = _problem(content, cid, "a", 3.0)
        p2 = _problem(content, cid, "b", 3.2)
        with _S._client() as client:
            _S._erase_learner(client)
            auth = _S._login(client)
            did = _open(client, auth, p1)

            first = _turn(client, auth, did, ["x+5"], "이렇게 풀었어요")
            assert first["problem_complete"] is False
            assert _attempt_rows(client, auth, p1) == {False: 1}
            after_first = _chain(client, auth)
            assert after_first[-1][3] == "R6-wrong-undiagnosed", after_first

            # 같은 대화·같은 문항에서 다시 틀린 답 — 행이 늘지 않는다(변별력: dedupe를 빼면 2행).
            _turn(client, auth, did, ["x+6"], "다시 봤어요")
            assert _attempt_rows(client, auth, p1) == {False: 1}
            assert _chain(client, auth) == after_first, "재제출이 전이를 새로 만들었다"

            # 오답만 있는 문항은 `/v1/me/next-problem`의 미시도 필터에서 빠진다 — `/v1/me/attempts`의
            # 오답과 같은 동작이다(시도한 문항은 다시 내지 않는다). 이 관측이 acceptance ⑦ ⓔ(1)의 판정이다.
            assert str(_S._next_problem(client, auth)["problem_id"]) == str(p2)

            # 스스로 고친 정답 → 돌아보기 → 완료. 오답 행이 완료 표지를 건드렸다면 여기서 no-op이다.
            solved = _turn(client, auth, did, _CORRECT_STEPS, "다시 풀었어요")
            assert solved["awaiting_reflection"] is True and solved["problem_complete"] is False
            done = _turn(client, auth, did, [], _REFLECTION)
            assert done["problem_complete"] is True and done["completed_attempt_id"], done
            assert _attempt_rows(client, auth, p1) == {False: 1, True: 1}

            final = _chain(client, auth)
            journal.record("완료", "오답 뒤 자가 수정", 전이=final)
            assert [r for _f, _t, _trig, r, _c in final if r] == [
                "R6-wrong-undiagnosed",
                "R2-correct-low-confidence",
            ], final
            _S._erase_learner(client)
        journal.dump()
    finally:
        content.teardown()


def test_unverifiable_final_step_leaves_no_attempt_and_no_transition() -> None:
    """③ 서버가 오답이라고 **판정하지 못한** 답은 원장에 아무것도 남기지 않는다.

    "모른다"를 "틀렸다"로 접으면 판정 불능 이력이 학생을 교정 국면으로 민다(CLAUDE.md 모른다 ≠ 아니다).
    변별력: `unverifiable`을 오답으로 접는 구현이면 이 학생의 원장에 행과 R6 전이가 생겨 깨진다.
    """
    content, journal = _S._begin("EOS-146")
    try:
        cid, _code = _S._seed_concept(content, "e146c", "다항식의 전개")
        pid = _problem(content, cid, "a", 3.0)
        with _S._client() as client:
            _S._erase_learner(client)
            auth = _S._login(client)
            did = _open(client, auth, pid)
            body = _turn(client, auth, did, [_UNVERIFIABLE_ANSWER], "이렇게 풀었어요")
            assert body["problem_complete"] is False
            assert _attempt_rows(client, auth, pid) == {}
            assert _chain(client, auth) == []
            _S._erase_learner(client)
        journal.dump()
    finally:
        content.teardown()
