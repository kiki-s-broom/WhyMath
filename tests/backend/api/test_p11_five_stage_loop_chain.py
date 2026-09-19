"""[P-11] Phase 2 필수 API 표면의 **5단계 내부 연결** 동결 하네스.

동결 대상(계획서 300 §12 P-11 핵심 판정 문면 그대로):

    Attempt → Event → Assessment → LearnerState → Recommendation

P-11이 지시하는 것은 *API 12개가 각각 200을 내는가*가 아니라 **이 연결이 내부에서 실제로
이어지는가**다. 그래서 이 모듈은 단계를 하나씩 검사하지 않고 **인접 단계 사이의 넘김(handoff)
4건**을 단언한다 — 앞 단계의 *산출물 자체*가 뒤 단계의 입력으로 나타나는지를 본다. 단계가
개별적으로 멀쩡해도 넘김이 끊기면 루프는 돌지 않는다.

    H1 Attempt  → Event          : 제출이 낸 `attempt_id`가 이벤트 시간선에 실린다
    H2 Event    → Assessment     : 그 같은 시도가 Evidence(채점 근거)로 해소된다
    H3 Assessment → LearnerState : 그 Evidence의 개념·스킬이 학습자 상태에 *값으로* 남는다
    H4 LearnerState → Recommendation : 추천이 그 상태를 **읽고** 근거로 인용한다

**기존 두 게이트와 무엇이 다른가(중복 회피 — 재구현 0)**
- `test_week1_gate_closed_loop.py`(Week 1 Gate)는 *루프가 한 바퀴 도는가*(7단계 완주)를 본다.
  Evidence·Event Trace·LearnerState 단일 표면을 한 번도 보지 않는다(실측: 그 파일의
  `learner-state`·`learning-trace` 참조 0건).
- `test_week2_gate_wrong_answer_propagation.py`(Week 2 Gate)는 *오답 1건이 전파되는가*를 보고
  H1~H3에 해당하는 구간을 이미 촘촘히 덮는다. 그러나 **추천 구간을 통째로 지나가지 않는다**
  (실측: 그 파일의 `next-problem`·`recommendation` 참조 0건).
- 즉 이 모듈의 고유 기여는 **H4**이고, H1~H3은 Week 2 하네스의 검증된 시딩·제출 헬퍼를 그대로
  빌려 *연결의 관점으로* 다시 묶는다. 헬퍼를 재구현하지 않으므로 그쪽이 바뀌면 이 모듈은
  조용히 낡는 대신 수집 단계에서 이름을 지목하며 깨진다.

**H4를 "200이 왔다"로 판정하지 않는다("작동한 비율" 원칙)**
추천 응답이 오는 것은 추천이 학습자 상태를 *읽었다*는 증거가 아니다. 그래서 세 가지를 본다:
  (가) 추천이 방금 푼 문항을 **제외**했다(시도 이력을 읽었다)
  (나) `weak_concept_signal_count >= 1` — 후보 중 숙달 기록이 있어 가중이 실제로 **적용됐다**
       (이 값이 0이면 축을 켰으나 신호가 없었다는 뜻이고, 그러면 상태는 추천에 닿지 않았다)
  (다) 추천 근거가 인용한 숙달값이 LearnerState의 그 값과 **같다**(두 표면의 값 불일치 금지)

**시딩 경계(정직한 선언)** — Week 1·2와 동일하다. *학습자 상태*는 단 한 줄도 직접 쓰지 않고
전부 HTTP 부수효과로만 만든다. *저작 콘텐츠*(concept·skill_node·problem·problem_concept)만 ORM으로
심는다. 이 모듈은 Week 2의 시딩에 **후보 문항 1건을 더한다** — 추천이 고를 것이 있어야 H4가
성립하고, 방금 푼 문항은 미시도 필터에서 빠지기 때문이다.

**판정 밖**: 추천 품질(무엇을 골랐어야 하는가)·AI 품질·UI는 보지 않는다. 연결만 본다.
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

# ── Week 2 게이트 하네스의 검증된 헬퍼 재사용 (재구현 0) ──────────────────────────
# Week 2는 다시 Week 1의 로그인·정리·PG 도달성 헬퍼를 재노출한다. 경로 로딩을 쓰는 이유는
# 그쪽과 같다: 이 저장소의 pytest는 `--import-mode=importlib`이라 형제 테스트 모듈이 이름으로
# 임포트되지 않는다.
_WEEK2_PATH = pathlib.Path(__file__).with_name("test_week2_gate_wrong_answer_propagation.py")
#: 빌려 쓰는 헬퍼 계약 — 하나라도 사라지면 수집 단계에서 이름을 지목하며 실패한다.
_WEEK2_HELPERS = (
    "_add_all",
    "_cleanup_content",
    "_client",
    "_delete_skill_node",
    "_erase_learner",
    "_learner_state",
    "_login",
    "_pg_reachable",
    "_problem",
    "_problem_concept",
    "_seed",
    "_submit_wrong",
    "_WRONG_ANSWER",
)


def _load_week2_harness() -> ModuleType:
    """Week 2 하네스를 파일 경로로 적재하고 헬퍼 계약을 검사한다."""
    if not _WEEK2_PATH.exists():
        raise RuntimeError(
            f"Week 2 게이트 하네스가 없다: {_WEEK2_PATH}. 이 동결은 그 시딩·제출 경로를 "
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
            f"Week 2 하네스의 헬퍼가 사라졌다: {missing}. 이 동결이 그 경로를 재사용하므로 "
            "이름이 바뀌면 여기도 함께 고쳐야 한다(조용한 표류 방지)."
        )
    return module


_W2 = _load_week2_harness()
_add_all = _W2._add_all
_cleanup_content = _W2._cleanup_content
_client = _W2._client
_delete_skill_node = _W2._delete_skill_node
_erase_learner = _W2._erase_learner
_learner_state = _W2._learner_state
_login = _W2._login
_pg_reachable = _W2._pg_reachable
_problem = _W2._problem
_problem_concept = _W2._problem_concept
_seed = _W2._seed
_submit_wrong = _W2._submit_wrong
_WRONG_ANSWER = _W2._WRONG_ANSWER


def _teardown_all(cid: uuid.UUID, problem_ids: list[uuid.UUID], skill_id: str | None) -> None:
    """정리 — **학습자를 먼저**, 그 다음 저작 콘텐츠를 *한 번에* 지운다.

    Week 2의 `_teardown`을 문항마다 부르지 않는 이유: 그 함수는 호출마다 개념까지 지우므로,
    문항 2건에 두 번 부르면 첫 호출이 개념을 지우는 순간 남은 문항의 `problem_concept`이
    그 개념을 참조한 채로 남아 `ForeignKeyViolationError`가 난다. 정리가 터지면 그 예외가
    원래의 단언 실패를 가린다(Week 2 하네스가 같은 함정을 주석으로 남겨 뒀다). 그래서 문항
    전건을 한 번에 넘긴다 — 순서(problem_concept → problem → concept)는 `_cleanup_content`가
    보장한다.
    """
    try:
        with _client() as client:
            _erase_learner(client)
    finally:
        try:
            asyncio.run(_cleanup_content(problem_ids=problem_ids, concept_ids=[cid]))
        finally:
            if skill_id is not None:
                asyncio.run(_delete_skill_node(skill_id))


def _step(name: str, detail: str) -> None:
    """넘김 통과를 표준출력에 남긴다 — 판정은 exit code, 경위는 이 줄들이 말한다."""
    print(f"P11_CHAIN_HANDOFF={name} :: {detail}")


def _seed_candidate(cid: uuid.UUID, sfx: str) -> uuid.UUID:
    """추천 후보 문항 1건 — 같은 개념에 매달아 둔다(H4가 고를 것이 있어야 한다).

    방금 푼 문항은 `GET /v1/me/next-problem`의 미시도 필터에서 빠지므로, 후보가 이것뿐이면
    "추천이 방금 푼 문항을 제외했다"와 "추천이 무언가를 골랐다"를 한 번에 볼 수 있다.
    """
    candidate_pid = uuid.uuid4()
    asyncio.run(_add_all(_problem(candidate_pid, f"{sfx}c", 3.0)))
    asyncio.run(_add_all(_problem_concept(candidate_pid, cid)))
    return candidate_pid


def _concept_code(client: Any, auth: dict[str, str], concept_id: str) -> str:
    """개념 UUID → 개념 **코드**. `LearnerState.mastery`가 코드로 키를 잡기 때문이다.

    두 축을 섞으면 "상태에 값이 없다"는 거짓 미통과가 난다(Week 2 하네스가 같은 함정을
    주석으로 남겨 뒀다). 그래서 추론하지 않고 `GET /v1/concepts/{id}`로 실제 코드를 받는다.
    """
    resp = client.get(f"/v1/concepts/{concept_id}", headers=auth)
    assert resp.status_code == 200, resp.text
    code: str = resp.json()["code"]
    return code


def test_p11_five_stage_loop_chain_is_connected() -> None:
    """P-11 핵심 판정 — Attempt→Event→Assessment→LearnerState→Recommendation 넘김 4건."""
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 판정 불가(WHYMATH_DATABASE_URL 확인). 통과가 아니다.")

    # 레이트리미터 격리 — 앞선 통합 테스트가 IP 버킷을 소진하면 이 판정의 쓰기가 429를 받는다.
    asyncio.run(reset_store())

    sfx = uuid.uuid4().hex[:8]
    cid = uuid.uuid4()
    pid = uuid.uuid4()
    skill_id: str | None = None
    candidate_pid: uuid.UUID | None = None

    try:
        code, skill_id = _seed(cid, pid, sfx)
        candidate_pid = _seed_candidate(cid, sfx)

        with _client() as client:
            _erase_learner(client)  # 선행 정리(멱등) — 지난 회차 잔여가 기준선을 깨지 않게.
            auth = _login(client)

            # ── 단계 1) Attempt — 오답 1건을 공개 표면으로 투입한다. ──────────────────
            submitted = _submit_wrong(client, auth, pid, _WRONG_ANSWER)
            attempt_id = submitted["attempt_id"]
            assert attempt_id, submitted

            # ── H1) Attempt → Event : 그 attempt_id가 이벤트 시간선에 실렸는가. ────────
            trace = client.get("/v1/me/learning-trace", headers=auth)
            assert trace.status_code == 200, trace.text
            trace_body = trace.json()
            assert (
                trace_body["truncated"] is False
            ), "트레이스가 limit에 잘렸다 — 잘린 결과로 부재를 판정하면 안 된다."
            traced = [e for e in trace_body["entries"] if e.get("attempt_id") == attempt_id]
            assert traced, (
                f"방금 제출한 attempt({attempt_id})가 이벤트 시간선에 없다 — Attempt→Event가 "
                f"끊겼다. 시도는 적재됐는데 이벤트가 남지 않으면 뒤 단계는 근거 없이 돈다."
            )
            _step(
                "H1-attempt-to-event",
                f"attempt_id={attempt_id} · 트레이스 {len(trace_body['entries'])}건 중 "
                f"이 시도 귀속 {len(traced)}건 "
                f"(event_type={sorted({e['event_type'] for e in traced})})",
            )

            # ── H2) Event → Assessment : 그 같은 시도가 Evidence로 해소됐는가. ─────────
            evidence = submitted["evidence"]
            assert evidence is not None, (
                "시도는 이벤트에 남았는데 Evidence가 없다 — Event→Assessment가 끊겼다. "
                "정답 여부가 숙달로 직행했다면 Assessment 단계 자체가 존재하지 않는 것이다."
            )
            concept_ev = {e["concept_id"]: e for e in evidence["concept_evidence"]}
            assert (
                str(cid) in concept_ev
            ), f"시도가 귀속된 개념이 개념 증거에 없다: {list(concept_ev)}"
            skill_ev = {e["skill_id"] for e in evidence["skill_evidence"]}
            assert (
                skill_id in skill_ev
            ), f"개념의 행동 스킬이 스킬 증거로 해소되지 않았다: {skill_ev}"
            coverage = evidence["coverage"]
            _step(
                "H2-event-to-assessment",
                f"evidence filled={coverage['filled_kinds']}/3 · "
                f"concept={coverage['concept_count']}건 skill={coverage['skill_count']}건 "
                f"misconception={coverage['misconception_count']}건",
            )

            # ── H3) Assessment → LearnerState : 그 증거가 상태에 *값으로* 남았는가. ────
            state = _learner_state(client, auth)
            assert code in state["mastery"], (
                f"Evidence는 그 개념을 지목했는데 LearnerState에 값이 없다 — "
                f"Assessment→LearnerState가 끊겼다(부분 쓰기): {list(state['mastery'])}"
            )
            assert (
                skill_id in state["skill_mastery"]
            ), f"스킬 증거가 나왔는데 스킬 숙달이 상태에 없다: {list(state['skill_mastery'])}"
            state_mastery = state["mastery"][code]
            assert state_mastery is not None, f"숙달값이 NULL이다: {state['mastery']}"
            _step(
                "H3-assessment-to-learner-state",
                f"{code} mastery={state_mastery} · skill_mastery {len(state['skill_mastery'])}건",
            )

            # ── H4) LearnerState → Recommendation : 추천이 그 상태를 읽었는가. ─────────
            # 200이 아니라 *읽었다는 증거*를 본다 — (가) 시도 제외 (나) 가중 실적용 (다) 값 일치.
            nxt = client.get(
                "/v1/me/next-problem",
                headers=auth,
                params={"prioritize_weak_concepts": "true"},
            )
            assert nxt.status_code == 200, nxt.text
            rec = nxt.json()

            # (가) 시도 이력을 읽었다 — 방금 푼 문항은 다시 내지 않는다.
            assert rec["problem_id"] is not None, (
                f"추천이 아무 문항도 내지 못했다 — LearnerState→Recommendation이 끊겼다 "
                f"(candidate_zero_reason={rec.get('candidate_zero_reason')})."
            )
            assert rec["problem_id"] != str(
                pid
            ), "추천이 방금 푼 문항을 다시 냈다 — 추천이 시도 이력을 읽지 않았다는 뜻이다."

            # (나) 숙달 가중이 *실제로 적용*됐다 — 축을 켠 것과 신호가 있은 것은 다르다.
            assert "weak_concept" in rec["weight_axes_applied"], (
                f"prioritize_weak_concepts=true인데 약점 축이 적용 목록에 없다: "
                f"{rec['weight_axes_applied']}"
            )
            assert rec["weak_concept_signal_count"] >= 1, (
                f"약점 축은 켜졌는데 숙달 신호가 0건이다 — 추천이 LearnerState를 읽지 않고 "
                f"돌았다(200은 작동의 증거가 아니다): "
                f"candidate_pool_size={rec['candidate_pool_size']}"
            )

            # (다) 두 표면의 값이 같다 — 추천이 인용한 숙달 = 상태에 있는 숙달.
            reason = rec["reason"]
            assert (
                reason["concept_id"] is not None
            ), f"추천이 근거 개념 없이 나왔다 — 상태를 인용하지 않았다: {reason}"
            reason_code = _concept_code(client, auth, reason["concept_id"])
            assert reason_code in state["mastery"], (
                f"추천이 근거로 든 개념({reason_code})이 LearnerState에 없다 — 추천이 상태 "
                f"밖의 무언가를 인용했다: {list(state['mastery'])}"
            )
            assert reason["mastery"] == pytest.approx(state["mastery"][reason_code]), (
                f"추천이 인용한 숙달과 LearnerState의 숙달이 다르다 — 두 표면이 어긋났다: "
                f"reason={reason['mastery']} state={state['mastery'][reason_code]}"
            )
            _step(
                "H4-learner-state-to-recommendation",
                f"problem_id={rec['problem_id']}(≠시도 {pid}) · action={rec['action']} · "
                f"reason.type={reason['type']} concept={reason_code} "
                f"mastery={reason['mastery']}(state 일치) · "
                f"weak_concept_signal_count={rec['weak_concept_signal_count']}/"
                f"{rec['candidate_pool_size']}",
            )

            _erase_learner(client)

        print(
            "P11_CHAIN=PASS :: Attempt→Event→Assessment→LearnerState→Recommendation 넘김 4건 연결"
        )
    finally:
        seeded = [pid] if candidate_pid is None else [pid, candidate_pid]
        _teardown_all(cid, seeded, skill_id)
