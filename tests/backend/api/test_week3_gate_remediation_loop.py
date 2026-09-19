"""계획서 300 Phase 2 §10 **Week 3 Gate 판정** 하네스 — Remediation Loop가 자동으로 이어지는가.

판정 대상(원 문서 §10 완료 판정 그대로):

    오답 → Misconception → 교정 콘텐츠 → AI Hint → 새 문제 → 재시도

여섯 마디를 **공개 HTTP 표면만으로** 한 회차에 순서대로 관통하고, 마디마다 *산출물*을
단언한다. 판정은 pytest exit code로 나오고, 마디마다 `WEEK3_GATE_STEP=...` 줄이 표준출력에
남는다(인상 판정 금지).

**이 게이트가 재는 것은 "무엇이 다음을 촉발했는가"다**
원 문서가 요구한 것은 여섯 마디의 *존재*가 아니라 **화살표**다. 그래서 이 하네스는 마디마다
두 가지를 함께 단언한다 — ⓐ 그 마디의 산출물이 나왔는가 ⓑ **그 산출물이 앞 마디의 영속된
결과에서 나왔는가**(요청이 그 정보를 실어 보내지 않았는데도). ⓑ가 없으면 "클라이언트가
답을 알고 있어서 이어진 것"과 구별되지 않는다.

그 ⓑ를 기계로 고정하기 위해 요청 본문을 모듈 상수(`_COACH_OPEN_BODY`·`_COACH_TURN_BODY`)로
두고, **그 본문에 오개념 id·힌트 단계가 없다는 것 자체를 단언**한다(`_assert_carries_no_hint`).
즉 이 판정에서 서버가 오개념을 교정 발화로 바꾼 근거는 학생이 방금 틀린 답 하나뿐이다.

**Week 1·Week 2 게이트와 무엇이 다른가**
- Week 1(`test_week1_gate_closed_loop.py`)은 *1사이클이 DB 직접 수정 없이 도는가*를 봤다.
- Week 2(`test_week2_gate_wrong_answer_propagation.py`)는 *오답 1건이 상태 5구간에 전파되고
  이벤트와 일치하는가*를 봤다 — 거기서 끝나는 지점이 `LearnerState`다.
- 이 게이트는 그 **뒤**를 본다: 남은 상태가 *학생에게 돌아오는가*. 교정 발화·힌트·다음 문항은
  Week 1·2 어느 하네스도 한 번도 호출하지 않는다.

**시딩 경계(정직한 선언)**
Week 1·2와 같다 — *학습자 상태*는 단 한 줄도 직접 쓰지 않는다(전부 HTTP 부수효과). *저작
콘텐츠*(concept·problem·problem_concept·skill_node)만 ORM으로 심는다. 픽스처 조립기는 Week 2
하네스에서 그대로 빌려 쓴다(재구현 0) — 그쪽이 이름을 바꾸면 여기는 조용히 통과하지 않고
수집 단계에서 이름을 지목하며 깨진다.

문항을 **둘** 심는 것만이 Week 2와 다르다. 다섯 번째 마디("새 문제")가 성립하려면 *틀린 그
문항이 아닌* 후보가 하나는 있어야 하고, 후보가 0건이면 추천기는 정직하게 null을 돌려주므로
그 상태에서는 마디의 부재와 픽스처의 부재를 구별할 수 없다.

**판정 밖(원 문서 지시 + 이 게이트가 의도적으로 보지 않는 것)**
- AI 답변 품질·교정 발화의 교수학적 적절성·추천 품질은 보지 않는다(연결성만).
- `POST /v1/scene/weak-concept`(학습 장면 기반 교정 콘텐츠)는 **이 판정이 지나가지 않는다** —
  시각화 spec 생성이 LLM 라우터를 경유해 스텁이 필요하고, 교정 콘텐츠 마디는 스텁 없이
  성립하는 코치 경로로 충분히 관측된다. 그 표면의 연결성은 이 판정의 근거가 아니다.
- 학습 상태 머신의 *정책 결정*(`next_action`)은 이 여섯 마디에 없다. 다만 그 축이 기본
  학습자에게 닿지 않는다는 사실은 아래 `test_policy_directed_remediation_...`이 동결한다.
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

from whymath_backend.api._rate_limit import reset_store

pytestmark = pytest.mark.integration

# ── Week 2 게이트 하네스의 검증된 픽스처 조립기 재사용 (재구현 0) ────────────────────
# 그쪽이 Week 1의 로그인·삭제권 정리·시딩·PG 도달성을 이미 빌려 오고 있으므로, 여기서 다시
# 빌리면 같은 헬퍼의 경로가 둘이 된다. 한 줄로 이어 받는다.
#
# 경로 로딩인 이유는 Week 2 모듈 docstring과 같다 — 이 저장소의 pytest는
# `--import-mode=importlib`이라 형제 테스트 모듈이 이름으로 임포트되지 않는다.
_WEEK2_PATH = pathlib.Path(__file__).with_name("test_week2_gate_wrong_answer_propagation.py")
#: 빌려 쓰는 헬퍼 계약 — 하나라도 사라지면 수집 단계에서 실패한다(조용한 표류 방지).
_WEEK2_HELPERS = (
    "_EXPECTED_MISCONCEPTION",
    "_QUESTION_TEXT",
    "_WRONG_ANSWER",
    "_add_all",
    "_cleanup_content",
    "_client",
    "_concept",
    "_delete_skill_node",
    "_erase_learner",
    "_learner_state",
    "_login",
    "_pg_reachable",
    "_problem",
    "_problem_concept",
    "_skill_node",
    "_submit_wrong",
)


def _load_week2_harness() -> ModuleType:
    """Week 2 하네스를 파일 경로로 적재하고 헬퍼 계약을 검사한다."""
    if not _WEEK2_PATH.exists():
        raise RuntimeError(
            f"Week 2 게이트 하네스가 없다: {_WEEK2_PATH}. 이 판정은 그 픽스처 조립기를 "
            "재사용한다 — 파일이 옮겨졌으면 이 경로를 함께 고친다."
        )
    spec = importlib.util.spec_from_file_location("_week2_gate_harness", _WEEK2_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Week 2 하네스 스펙 생성 실패: {_WEEK2_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    missing = [name for name in _WEEK2_HELPERS if not hasattr(module, name)]
    if missing:
        raise RuntimeError(
            f"Week 2 하네스의 헬퍼가 사라졌다: {missing}. 이 판정이 그 조립기를 재사용하므로 "
            "이름이 바뀌면 여기도 함께 고쳐야 한다."
        )
    return module


_W2 = _load_week2_harness()
_EXPECTED_MISCONCEPTION = _W2._EXPECTED_MISCONCEPTION
_WRONG_ANSWER = _W2._WRONG_ANSWER
_add_all = _W2._add_all
_cleanup_content = _W2._cleanup_content
_client = _W2._client
_concept = _W2._concept
_delete_skill_node = _W2._delete_skill_node
_erase_learner = _W2._erase_learner
_learner_state = _W2._learner_state
_login = _W2._login
_pg_reachable = _W2._pg_reachable
_problem = _W2._problem
_problem_concept = _W2._problem_concept
_skill_node = _W2._skill_node
_submit_wrong = _W2._submit_wrong

#: 코치 세션을 여는 요청 본문 — **중립 발화**다. 오개념 id도, 힌트 단계도, 진단 결과도 없다.
#: 서버가 교정 발화를 고를 수 있는 유일한 근거는 직전에 영속된 오개념 가설뿐이다.
_COACH_OPEN_BODY: dict[str, Any] = {"student_input": "잘 모르겠어요"}
#: 후속 턴 — 역시 중립 좌절 신호뿐이다(힌트 단계를 클라가 지정하지 않는다).
_COACH_TURN_BODY: dict[str, Any] = {"student_input": "아직도 모르겠어요"}
#: 요청 본문에 있으면 "서버가 스스로 알아냈다"는 주장이 무너지는 키들.
_FORBIDDEN_REQUEST_KEYS = (
    "misconception_id",
    "misconception_ids",
    "hint_level",
    "prev_hint_level",
    "intervention",
    "polya_state",
)


def _step(name: str, detail: str) -> None:
    """마디 통과를 표준출력에 남긴다 — 판정은 exit code, 경위는 이 줄들이 말한다."""
    print(f"WEEK3_GATE_STEP={name} :: {detail}")


def _assert_carries_no_hint(body: dict[str, Any]) -> None:
    """요청 본문이 *답을 실어 보내지 않았음*을 단언한다.

    이 단언이 이 게이트의 핵심이다. 없으면 "서버가 오개념을 찾아 교정했다"와 "클라이언트가
    오개념을 알려 줬다"가 같은 통과로 보인다. 중첩 값까지 훑는 이유는 `polya_state` 같은
    구조체 안에 단계가 숨을 수 있기 때문이다.
    """
    for key in _FORBIDDEN_REQUEST_KEYS:
        assert key not in body, (
            f"요청 본문이 `{key}`를 실어 보냈다 — 그러면 이 마디는 '서버가 알아냈다'의 "
            f"증거가 되지 못한다: {body}"
        )


def _seed(cid: uuid.UUID, pids: list[uuid.UUID], sfx: str) -> tuple[str, str]:
    """저작 콘텐츠 시딩 — 개념 1·스킬 1·문항 **2**(같은 개념 PRIMARY).

    문항이 둘인 이유는 모듈 docstring 참조(다섯 번째 마디의 후보 확보).

    **난이도 순서가 판정의 변별력을 만든다.** 학생이 틀릴 문항(`pids[0]`)을 *가장 쉬운* 쪽으로
    둔다 — 오답 뒤 θ는 바닥(-4)으로 내려가고 추천기는 |b−θ|가 가장 작은 문항을 고르므로, 시도
    이력 제외가 없으면 **방금 틀린 그 문항이 1순위가 된다**. 반대로 두면(틀린 문항이 더 어려움)
    제외 로직을 통째로 지워도 다른 문항이 뽑혀 5마디 단언이 조용히 통과한다 — 그 배치에서는
    "제외했다"와 "원래 안 뽑혔다"를 구별할 수 없다(2026-09-19 뮤테이션 M5로 실측).
    """
    code = f"UC.w3gate.{sfx}"
    skill_id = f"skill.w3gate.{sfx}"
    asyncio.run(_add_all(_skill_node(skill_id)))
    asyncio.run(_add_all(_concept(cid, code, skill_id)))
    for index, pid in enumerate(pids):
        asyncio.run(_add_all(_problem(pid, sfx, 2.5 + 0.5 * index)))
        asyncio.run(_add_all(_problem_concept(pid, cid)))
    return code, skill_id


def _teardown(cid: uuid.UUID, pids: list[uuid.UUID], skill_id: str | None) -> None:
    """정리 — **학습자를 먼저**, 그 다음 저작 콘텐츠(FK 순서). Week 2와 같은 이유로 멱등."""
    try:
        with _client() as client:
            _erase_learner(client)
    finally:
        try:
            asyncio.run(_cleanup_content(problem_ids=pids, concept_ids=[cid]))
        finally:
            if skill_id is not None:
                asyncio.run(_delete_skill_node(skill_id))


def _trace(client: Any, auth: dict[str, str]) -> list[dict[str, Any]]:
    """P-02 Event Trace — 시간 오름차순 엔트리. 잘렸으면 부재 판정에 쓰지 않는다."""
    resp = client.get("/v1/me/learning-trace", headers=auth)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["truncated"] is False, "트레이스가 limit에 잘렸다 — 잘린 결과로 판정하지 않는다."
    entries: list[dict[str, Any]] = body["entries"]
    return entries


def _hint_levels(entries: list[dict[str, Any]]) -> list[int]:
    """트레이스에 남은 `힌트제공` 단계를 시간순으로.

    `is not None`으로 거른다 — truthiness로 거르면 단계 0이 *값이 없는 것*으로 접힌다. 현재
    사다리 값 공간은 1~4라 실동작은 같지만, 값 공간이 넓어지는 순간 조용히 틀려지는 형태다
    (CLAUDE.md "모른다 ≠ 아니다").
    """
    return [
        level
        for e in entries
        if e["event_type"] == "hint_provided"
        and (level := (e.get("detail") or {}).get("hint_level")) is not None
    ]


def test_week3_gate_remediation_loop_is_automatic() -> None:
    """Week 3 Gate 판정 — 여섯 마디가 사람이 값을 넣지 않고 이어지는가."""
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 판정 불가(WHYMATH_DATABASE_URL 확인). 통과가 아니다.")

    # 레이트리미터 격리 — 같은 프로세스의 앞선 통합 테스트가 IP 버킷을 소진하면 이 판정의
    # 쓰기 호출이 429를 받는다(판정은 한도 계약을 재는 자리가 아니다).
    asyncio.run(reset_store())

    sfx = uuid.uuid4().hex[:8]
    cid = uuid.uuid4()
    pids = [uuid.uuid4(), uuid.uuid4()]
    skill_id: str | None = None

    try:
        code, skill_id = _seed(cid, pids, sfx)

        with _client() as client:
            _erase_learner(client)  # 선행 정리(멱등) — 지난 회차 잔여가 기준선을 깨지 않게.
            auth = _login(client)

            # ── 1) 오답 ────────────────────────────────────────────────────────────
            # 유일한 입력은 학생이 쓴 답 문자열이다. 이 회차 어디에서도 오개념 id를 주지 않는다.
            failed_pid = pids[0]
            body = _submit_wrong(client, auth, failed_pid, _WRONG_ANSWER)
            attempt_id = body["attempt_id"]
            assert attempt_id, body
            _step("1-wrong-answer", f"POST /v1/me/attempts 201 · attempt_id={attempt_id}")

            # ── 2) Misconception ──────────────────────────────────────────────────
            # 촉발: 1마디의 답안 문자열. 산출물: 후보 + **영속된** 활성 가설.
            candidates = {
                c["misconception_id"]: c for c in body["evidence"]["possible_misconceptions"]
            }
            assert (
                _EXPECTED_MISCONCEPTION in candidates
            ), f"오답이 오개념 후보를 내지 못했다 — 1→2 화살표가 끊겼다: {list(candidates)}"
            assert candidates[_EXPECTED_MISCONCEPTION]["gate_passed"] is True, candidates
            state_after_wrong = _learner_state(client, auth)
            assert _EXPECTED_MISCONCEPTION in state_after_wrong["active_misconceptions"], (
                "후보는 나왔으나 학습자 상태에 남지 않았다 — 다음 마디가 읽을 것이 없으므로 "
                f"여기가 끊긴 지점이다: {state_after_wrong['active_misconceptions']}"
            )
            mastery_after_wrong = state_after_wrong["mastery"][code]
            _step(
                "2-misconception",
                f"{_EXPECTED_MISCONCEPTION} conf="
                f"{candidates[_EXPECTED_MISCONCEPTION]['confidence']} · 활성 가설로 영속 · "
                f"{code} 숙달={mastery_after_wrong}",
            )

            # ── 3) 교정 콘텐츠 ────────────────────────────────────────────────────
            # 촉발: 2마디의 **영속된 가설**. 요청은 중립 발화 + 문항 id뿐이다.
            _assert_carries_no_hint(_COACH_OPEN_BODY)
            open_body = dict(_COACH_OPEN_BODY, problem_id=str(failed_pid))
            opened = client.post("/v1/coach/sessions", headers=auth, json=open_body)
            assert opened.status_code == 201, opened.text
            session_body = opened.json()
            intervention = session_body["intervention"]
            assert intervention is not None, (
                "오개념이 상태에 남아 있는데 교정 개입이 결정되지 않았다 — 2→3 화살표가 "
                "끊겼다(코치가 학습자의 누적 가설을 읽지 않는다)."
            )
            assert intervention["misconception_id"] == _EXPECTED_MISCONCEPTION, (
                f"교정 개입이 *그* 오개념을 겨냥하지 않았다 — 앞 마디와 무관한 개입이면 "
                f"화살표가 아니다: {intervention}"
            )
            assert intervention["prompt"].strip(), f"교정 발화가 비어 있다: {intervention}"
            active = {h["misconception_id"] for h in session_body["active_hypotheses"]}
            assert (
                _EXPECTED_MISCONCEPTION in active
            ), f"응답의 활성 가설 세트에 그 오개념이 없다 — 개입의 출처를 확인할 수 없다: {active}"
            dialogue_id = session_body["dialogue_id"]
            _step(
                "3-remediation-content",
                f"intervention.pattern={intervention['pattern']} "
                f"target={intervention['misconception_id']} · 요청 본문이 오개념을 "
                f"실어 보내지 않았다(keys={sorted(open_body)})",
            )

            # ── 4) AI Hint ────────────────────────────────────────────────────────
            # 촉발: 3마디가 적재한 `힌트제공` 이벤트. 클라는 단계를 보내지 않는다 —
            # 서버가 직전 적재에서 되찾아(`_prev_hint_level_for`) 사다리를 올린다.
            first_hint = session_body["decision"]["hint_level"]
            assert isinstance(first_hint, int) and 1 <= first_hint <= 4, session_body["decision"]
            # 픽스처 전제 — 사다리 상한에서 시작하면 *상승*을 관측할 수 없고, 그러면 아래
            # 단언이 "서버가 직전값을 읽었는가"를 재지 못한다(변별력 0). 전제가 깨지면 픽스처를
            # 고칠 일이지 단언을 느슨하게 할 일이 아니다.
            assert first_hint < 4, (
                f"교정 턴이 이미 사다리 상한(4)에서 시작했다 — 다음 마디의 상승을 관측할 수 "
                f"없으므로 이 픽스처로는 4마디를 판정할 수 없다: {session_body['decision']}"
            )
            levels_before_turn = _hint_levels(_trace(client, auth))
            assert levels_before_turn, (
                "교정 턴이 `힌트제공` 이벤트를 남기지 않았다 — 다음 마디가 읽을 사다리 "
                "직전값이 없다(3→4 화살표의 촉발원 부재)."
            )

            _assert_carries_no_hint(_COACH_TURN_BODY)
            turn = client.post(
                f"/v1/coach/sessions/{dialogue_id}/turns", headers=auth, json=_COACH_TURN_BODY
            )
            assert turn.status_code == 201, turn.text
            turn_body = turn.json()
            next_hint = turn_body["decision"]["hint_level"]
            # **상승**이어야 한다. 같은 좌절 신호를 다시 보냈는데 단계가 그대로면 서버가
            # `힌트제공` 적재에서 직전값을 되찾지 못한 것이다 — 클라가 단계를 안 보냈으므로
            # 그 경로 말고는 사다리가 오를 근거가 없다.
            assert next_hint > first_hint, (
                f"힌트 사다리가 오르지 않았다 — 서버가 직전 단계를 영속 이벤트에서 되찾지 "
                f"못했다는 뜻이다(클라는 단계를 보내지 않았다): {first_hint} → {next_hint}"
            )
            assert turn_body["decision"]["prompt"].strip(), turn_body["decision"]
            # 즉답 금지(CLAUDE.md 교수학 금기) — 사다리 상한을 넘지 않는다.
            assert next_hint <= 4, turn_body["decision"]
            _step(
                "4-ai-hint",
                f"hint_level {first_hint} → {next_hint} (클라 미지정·서버가 "
                f"`힌트제공` 적재에서 되찾음) · turn_order="
                f"{turn_body['assistant_turn_order']}",
            )

            # ── 5) 새 문제 ────────────────────────────────────────────────────────
            # 촉발: 1마디의 attempt(미시도 필터가 틀린 문항을 뺀다) + 그 오답이 쓴 실측 숙달
            # (추천 근거의 `mastery`). 요청에 개념·오개념·난이도를 지정하지 않는다.
            recommended = client.get("/v1/me/next-problem", headers=auth)
            assert recommended.status_code == 200, recommended.text
            rec = recommended.json()
            next_pid = rec["problem_id"]
            assert (
                next_pid is not None
            ), f"다음 문항이 null이다 — 4→5 화살표가 끊겼다(사유={rec['candidate_zero_reason']})."
            assert next_pid != str(
                failed_pid
            ), "방금 틀린 그 문항을 다시 냈다 — 시도 이력이 추천에 반영되지 않았다."
            reason = rec["reason"]
            assert reason and reason["type"], f"근거 없는 추천이다(KPI 3 위반): {rec}"
            assert reason["mastery"] == pytest.approx(mastery_after_wrong), (
                f"추천 근거의 숙달이 이 오답이 쓴 값과 다르다 — 추천이 그 오답을 보고 나온 "
                f"것이 아니다: reason={reason['mastery']} state={mastery_after_wrong}"
            )
            _step(
                "5-next-problem",
                f"problem_id={next_pid}(틀린 문항 제외) · action={rec['action']} · "
                f"reason.type={reason['type']} basis={reason['basis']} "
                f"mastery={reason['mastery']}(=오답이 쓴 값)",
            )

            # ── 6) 재시도 ─────────────────────────────────────────────────────────
            # 촉발: 5마디가 고른 문항 id. 루프가 닫히려면 그 문항 제출이 다시 1마디의
            # 산출물(증거·숙달·가설 강화)을 만들어야 한다 — 그래야 다음 바퀴가 돈다.
            retry = client.post(
                "/v1/me/attempts",
                headers=auth,
                json={"problem_id": next_pid, "is_correct": False, "student_answer": _WRONG_ANSWER},
            )
            assert retry.status_code == 201, retry.text
            retry_body = retry.json()
            assert retry_body["attempt_id"] != attempt_id, retry_body
            retry_state = _learner_state(client, auth)
            assert _EXPECTED_MISCONCEPTION in retry_state["active_misconceptions"], (
                f"재시도 후 가설이 사라졌다 — 루프가 한 바퀴를 넘기지 못한다: "
                f"{retry_state['active_misconceptions']}"
            )
            _step(
                "6-retry",
                f"추천 문항 재제출 201 · attempt_id={retry_body['attempt_id']} · "
                f"숙달 {mastery_after_wrong}→{retry_state['mastery'][code]}",
            )

            # ── 이벤트 trace — 화살표의 촉발원이 한 시간선에 순서대로 남았는가 ──────
            entries = _trace(client, auth)
            timeline = [e["event_type"] for e in entries]
            for required in (
                "problem_attempted",
                "misconception_detected",
                "hint_provided",
                "mastery_updated",
            ):
                assert required in timeline, (
                    f"화살표의 촉발원 `{required}`가 트레이스에 없다 — 연결을 이벤트로 "
                    f"제시할 수 없다: {timeline}"
                )
            # 인과 순서 — 오개념 탐지가 교정 발화(힌트 적재)보다 *먼저*여야 한다.
            assert timeline.index("misconception_detected") < timeline.index(
                "hint_provided"
            ), f"교정·힌트가 오개념 탐지보다 앞선다 — 그 개입은 이 오답의 결과가 아니다: {timeline}"
            # 시도가 둘(최초 오답 + 재시도) — 루프가 닫혔다는 시간선 증거.
            assert (
                timeline.count("problem_attempted") >= 2
            ), f"시도가 한 건뿐이다 — 재시도가 시간선에 남지 않았다: {timeline}"
            escalation = _hint_levels(entries)
            _step(
                "7-event-trace",
                f"{len(entries)}건 · 힌트 사다리={escalation} · 시간선={timeline}",
            )

            _erase_learner(client)

        print(
            "WEEK3_GATE=PASS :: 오답→Misconception→교정 콘텐츠→AI Hint→새 문제→재시도 "
            "여섯 마디가 사람이 값을 넣지 않고 이어졌다"
        )
    finally:
        _teardown(cid, pids, skill_id)


def test_remediation_content_requires_a_prior_wrong_answer() -> None:
    """음성 대조군 — 오답 이력이 **없으면** 같은 호출이 교정 개입을 내지 않는다.

    이게 없으면 3마디 단언이 "코치는 언제나 개입을 낸다"인지 "이 오답 때문에 냈다"인지
    구별할 수 없다. 본 판정과 *완전히 같은 요청*(같은 중립 발화·같은 문항)을 오답 없이
    보내고 `intervention`이 None인지 본다 — None이어야 본 판정의 3마디가 증거가 된다.
    """
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 판정 불가. 통과가 아니다.")
    asyncio.run(reset_store())

    sfx = uuid.uuid4().hex[:8]
    cid = uuid.uuid4()
    pids = [uuid.uuid4(), uuid.uuid4()]
    skill_id: str | None = None

    try:
        _, skill_id = _seed(cid, pids, sfx)
        with _client() as client:
            _erase_learner(client)
            auth = _login(client)
            state = _learner_state(client, auth)
            assert (
                state["active_misconceptions"] == []
            ), f"대조군인데 이미 활성 오개념이 있다 — 기준선이 오염됐다: {state}"
            opened = client.post(
                "/v1/coach/sessions",
                headers=auth,
                json=dict(_COACH_OPEN_BODY, problem_id=str(pids[0])),
            )
            assert opened.status_code == 201, opened.text
            body = opened.json()
            assert body["intervention"] is None, (
                "오답이 한 건도 없는데 교정 개입이 나왔다 — 그렇다면 본 판정의 3마디는 "
                f"오답의 결과가 아니라 상수다(변별력 0): {body['intervention']}"
            )
            assert body["active_hypotheses"] == [], body["active_hypotheses"]
            _erase_learner(client)
        print("WEEK3_GATE_CONTROL=OK :: 오답 없음 → intervention None · 활성 가설 0건")
    finally:
        _teardown(cid, pids, skill_id)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "EOS-115 — 기본 학습자(NEW)는 `POST /v1/me/attempts`에서 정책 전이가 거부돼 "
        "`next_action`이 항상 null이다. 생애주기 전이(NEW→DIAGNOSING→READY→LEARNING)를 "
        "적재하는 서버 경로도 클라이언트 호출부도 0건이라, 사람이 손으로 전이 3건을 "
        "POST하지 않는 한 R3(오개념 교정)·R5(반복 실패)는 영원히 발동하지 않는다."
    ),
)
def test_policy_directed_remediation_fires_for_a_default_learner() -> None:
    """인접 결함 동결 — 정책이 지시하는 교정 경로가 기본 학습자에게 닿는가.

    이 마디는 게이트의 여섯 마디에 **없다**(그래서 본 판정의 합격을 막지 않는다). 그러나
    계획서 §9의 보정 정책이 실제로 도는 유일한 경로가 이것이므로, 닿지 않는다는 사실을
    조용히 두지 않는다.

    `skip`이 아니라 `xfail(strict=True)`인 이유는 저장소 선례와 같다 — skip은 "검사가 없는
    것"과 구별되지 않아 침묵 실패가 되고, strict xfail은 고쳐지는 순간 XPASS로 빨강이 되어
    이 표식의 제거를 강제한다.
    """
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 판정 불가. 통과가 아니다.")
    asyncio.run(reset_store())

    sfx = uuid.uuid4().hex[:8]
    cid = uuid.uuid4()
    pids = [uuid.uuid4(), uuid.uuid4()]
    skill_id: str | None = None

    try:
        _, skill_id = _seed(cid, pids, sfx)
        with _client() as client:
            _erase_learner(client)
            auth = _login(client)
            body = _submit_wrong(client, auth, pids[0], _WRONG_ANSWER)
            learning_state = body["learning_state"]
            try:
                assert (
                    learning_state["rejected_transition"] is None
                ), f"기본 학습자의 평가 전이가 거부됐다: {learning_state['rejected_transition']}"
                assert learning_state["next_action"] == "REMEDIATE_MISCONCEPTION", learning_state
                assert (
                    learning_state["target_misconception_id"] == _EXPECTED_MISCONCEPTION
                ), learning_state
            finally:
                _erase_learner(client)
    finally:
        _teardown(cid, pids, skill_id)
