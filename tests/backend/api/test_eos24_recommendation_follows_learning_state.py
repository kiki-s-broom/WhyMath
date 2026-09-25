"""EOS-24 — 오개념 오답 직후 추천이 **학습 상태 머신의 결정을 집행**하는가 (실 PG · HTTP 경로).

acceptance ③의 정본 단언이다: 오개념 오답 1건 직후 `GET /v1/me/next-problem`의 `action`이
remediation 계열(`practice_current`)이고 `reason.type`이 `unmeasured`가 아니다. 설계 정본은
`docs/reviews/eos24_recommendation_reads_learning_state_judgment_2026-09-25.md`.

**변별력은 시딩 배치에서 나온다** — Gate 2 재판정(2026-09-24 §3)의 V2를 그대로 재현한다.
개념 C(학생이 틀리는 개념 · 난이도 2.5~3.5)와 더 쉬운 개념 P(1.0~1.5)를 심는다. 오답 뒤 θ가
바닥으로 내려가면 추천기는 |b−θ|가 가장 작은 문항, 즉 **P 문항**을 고른다 — 상태 머신을 읽지
않던 EOS-24 이전의 동작이 바로 그것이었다(`diagnose · unmeasured`). 그러므로 오개념 오답 뒤
추천 문항이 C 안에 있다는 것은 "상태 경로가 후보를 제한했다"의 증거이고, 같은 시딩에서 **일반
오답**(대조군)은 P로 내려간다.

**시딩 경계**: Week 1~3 게이트와 같다 — 학습자 상태는 한 줄도 직접 쓰지 않는다(전부 HTTP
부수효과). 저작 콘텐츠만 ORM으로 심는다. 픽스처 조립기는 Week 2 하네스에서 빌린다(재구현 0).

**CI 배선**: 이 파일은 `integration` 마크라 `WHYMATH_RUN_INTEGRATION=1` + 실 PG에서만 돈다 —
그리고 CI의 `backend-migrations` 잡(`pytest -m integration --ignore=../../tests/backend/l3`)이
**마커로 수집해 PR마다 실행한다**(`scripts/harness/ci_job_coverage.py scope`로 확인). 워크플로에
파일명이 안 보인다고 "CI에서 안 돈다"로 읽지 않는다 — 초판 docstring이 그렇게 틀렸다(2026-09-25
정정 · 사고 대장). hermetic 대응분은 `tests/backend/l2/test_learning_state_recommendation.py`다.
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
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from whymath_backend.api._rate_limit import reset_store
from whymath_backend.l2.recommendation_evidence import (
    EVENT_TYPE_RECOMMENDATION_TREATMENT,
    META_KEY_LEARNING_STATE_DIRECTIVE,
    META_KEY_POLICY_VERSION,
    POLICY_VERSION_CAT_STATE_REMEDIATION,
)

pytestmark = pytest.mark.integration

_WEEK2_PATH = pathlib.Path(__file__).with_name("test_week2_gate_wrong_answer_propagation.py")
#: 빌려 쓰는 헬퍼 계약 — 하나라도 사라지면 수집 단계에서 실패한다(조용한 표류 방지).
_WEEK2_HELPERS = (
    "_UNMATCHED_WRONG_ANSWER",
    "_WRONG_ANSWER",
    "_add_all",
    "_cleanup_content",
    "_client",
    "_concept",
    "_delete_skill_node",
    "_erase_learner",
    "_login",
    "_pg_reachable",
    "_problem",
    "_problem_concept",
    "_settings",
    "_skill_node",
    "_submit_wrong",
)


def _load_week2_harness() -> ModuleType:
    """Week 2 하네스를 파일 경로로 적재한다(`--import-mode=importlib`라 이름 import 불가)."""
    spec = importlib.util.spec_from_file_location("_week2_gate_harness_eos24", _WEEK2_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Week 2 하네스 스펙 생성 실패: {_WEEK2_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    missing = [name for name in _WEEK2_HELPERS if not hasattr(module, name)]
    if missing:
        raise RuntimeError(f"Week 2 하네스의 헬퍼가 사라졌다: {missing}")
    return module


_W2 = _load_week2_harness()

#: 현재 개념 C의 난이도 — 학생이 틀릴 문항이 C 안에서 가장 쉽다(Week 3 배치 규칙과 같다).
_C_DIFFICULTIES = (2.5, 3.0, 3.5)
#: 더 쉬운 개념 P — 상태 경로가 없으면 오답 뒤 추천이 여기로 내려간다(Gate 2 V2 재현).
_P_DIFFICULTIES = (1.0, 1.5)


def _step(name: str, detail: str) -> None:
    print(f"EOS24_STEP={name} :: {detail}")


class _Content:
    """시딩한 저작 콘텐츠 — 정리가 이름을 알아야 하므로 시딩 *전에* id를 정한다."""

    def __init__(self, *, c_problems: int) -> None:
        self.sfx = uuid.uuid4().hex[:8]
        self.c_concept = uuid.uuid4()
        self.p_concept = uuid.uuid4()
        self.c_pids = [uuid.uuid4() for _ in range(c_problems)]
        self.p_pids = [uuid.uuid4() for _ in _P_DIFFICULTIES]
        self.skill_id: str | None = None

    def seed(self) -> None:
        skill_id = f"skill.eos24.{self.sfx}"
        asyncio.run(_W2._add_all(_W2._skill_node(skill_id)))
        self.skill_id = skill_id
        asyncio.run(_W2._add_all(_W2._concept(self.c_concept, f"UC.eos24c.{self.sfx}", skill_id)))
        asyncio.run(_W2._add_all(_W2._concept(self.p_concept, f"UC.eos24p.{self.sfx}", skill_id)))
        for pid, difficulty in zip(self.c_pids, _C_DIFFICULTIES, strict=False):
            asyncio.run(_W2._add_all(_W2._problem(pid, f"{self.sfx}c", difficulty)))
            asyncio.run(_W2._add_all(_W2._problem_concept(pid, self.c_concept)))
        for pid, difficulty in zip(self.p_pids, _P_DIFFICULTIES, strict=True):
            asyncio.run(_W2._add_all(_W2._problem(pid, f"{self.sfx}p", difficulty)))
            asyncio.run(_W2._add_all(_W2._problem_concept(pid, self.p_concept)))

    def teardown(self) -> None:
        """학습자 먼저, 그 다음 저작 콘텐츠(FK 순서) — 멱등(Week 2 `_teardown`과 같은 이유)."""
        try:
            with _W2._client() as client:
                _W2._erase_learner(client)
        finally:
            try:
                asyncio.run(
                    _W2._cleanup_content(
                        problem_ids=[*self.c_pids, *self.p_pids],
                        concept_ids=[self.c_concept, self.p_concept],
                    )
                )
            finally:
                if self.skill_id is not None:
                    asyncio.run(_W2._delete_skill_node(self.skill_id))


def _next_problem(client: Any, auth: dict[str, str]) -> dict[str, Any]:
    resp = client.get("/v1/me/next-problem", headers=auth)
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body


async def _treatment_meta(problem_id: str) -> dict[str, Any] | None:
    """처치 기록 meta — 작동 비율의 원자료가 실제로 영속됐는지 본다."""
    engine = create_async_engine(_W2._settings().database_url)
    try:
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT meta FROM evidence_event WHERE event_type = :et "
                        "AND meta->>'problem_id' = :pid ORDER BY time DESC LIMIT 1"
                    ),
                    {"et": EVENT_TYPE_RECOMMENDATION_TREATMENT, "pid": problem_id},
                )
            ).first()
    finally:
        await engine.dispose()
    return None if row is None else dict(row[0])


def _require_pg() -> None:
    if not asyncio.run(_W2._pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 판정 불가(WHYMATH_DATABASE_URL 확인). 통과가 아니다.")
    asyncio.run(reset_store())


def test_misconception_wrong_answer_is_remediated_in_the_same_concept_then_released() -> None:
    """acceptance ③ + 안전장치 ③ — 교정 1문항을 집행하고, 그 문항도 틀리면 고정을 푼다."""
    _require_pg()
    content = _Content(c_problems=3)
    try:
        content.seed()
        with _W2._client() as client:
            _W2._erase_learner(client)
            auth = _W2._login(client)

            # ① 오개념 오답 — 전제: 상태 머신이 R3로 REMEDIATING에 들어간다.
            wrong = _W2._submit_wrong(client, auth, content.c_pids[0], _W2._WRONG_ANSWER)
            state = wrong["learning_state"]
            assert state["to_state"] == "REMEDIATING", state
            assert (
                state["next_action"] == "REMEDIATE_MISCONCEPTION"
            ), f"전제 붕괴 — 오개념 오답에 R3가 발화하지 않았다(이 판정의 입력이 없다): {state}"
            c_mastery = next(
                u["mastery"]
                for u in wrong["mastery_updates"]
                if u["concept_id"] == str(content.c_concept)
            )
            _step("1-remediating", f"rule={state['rule_id']} · C 숙달={c_mastery}")

            # ② 다음 추천 — 상태 머신 결정을 집행한다.
            rec = _next_problem(client, auth)
            reason = rec["reason"]
            assert rec["learning_state_directive"] == "applied", rec
            assert rec["action"] == "practice_current", rec
            assert reason["type"] == "misconception_remediation", reason
            assert reason["type"] != "unmeasured"  # Gate 2 Loop 1 기준(판정문 §0)
            assert reason["basis"] == "learning_state", reason
            assert rec["target_concept"] == str(content.c_concept), rec
            assert reason["concept_id"] == str(content.c_concept), reason
            assert rec["problem_id"] in {str(p) for p in content.c_pids[1:]}, (
                f"추천 문항 {rec['problem_id']}가 교정 대상 개념 C의 것이 아니다 — 상태 경로가 "
                "후보를 제한하지 못했다(제한이 없으면 더 쉬운 개념 P로 내려간다)."
            )
            assert rec["band_calibrated"] is False  # 교정 확인은 학습 밴드(미보정)로 고른다
            assert reason["confidence"] > 0.7, reason  # 안전장치 ② — 하한 초과만 집행
            assert reason["mastery"] == pytest.approx(c_mastery), (reason, c_mastery)
            meta = asyncio.run(_treatment_meta(rec["problem_id"]))
            assert meta is not None, "추천이 나갔는데 처치 기록이 없다"
            assert meta[META_KEY_LEARNING_STATE_DIRECTIVE] == "applied", meta
            assert meta[META_KEY_POLICY_VERSION] == POLICY_VERSION_CAT_STATE_REMEDIATION, meta
            _step(
                "2-applied",
                f"problem∈C · action={rec['action']} · reason={reason['type']}/"
                f"{reason['basis']} conf={reason['confidence']} · meta 기록 확인",
            )

            # ③ 교정 문항도 오개념으로 틀린다 — 교정 국면에서의 재실패.
            again = _W2._submit_wrong(client, auth, uuid.UUID(rec["problem_id"]), _W2._WRONG_ANSWER)
            again_state = again["learning_state"]
            assert again_state["from_state"] == "REMEDIATING", again_state
            assert (
                again_state["rule_id"] == "R3-wrong-misconception"
            ), f"전제 붕괴 — 2연속 오답(< R5 임계 3)인데 R3가 아니다: {again_state}"

            # ④ 고정 해제 — 숙달 구간 경로(선수 하강 가능)로 넘긴다.
            released = _next_problem(client, auth)
            assert released["learning_state_directive"] == "released_after_repeat", released
            assert released["reason"]["basis"] != "learning_state", released
            _step(
                "3-released",
                f"교정 재실패 → directive={released['learning_state_directive']} · "
                f"action={released['action']}",
            )
    finally:
        content.teardown()


def test_undiagnosed_wrong_answer_is_not_directed() -> None:
    """대조군(Gate 2 V1) — 같은 시딩에서 **일반 오답**은 상태 경로를 타지 않는다.

    이 테스트가 위 테스트의 변별력이다: 오답 뒤 추천이 C 밖으로 내려가는 것이 기본 동작이므로,
    오개념 오답에서 C 안에 머문 것은 상태 경로 때문이다.

    **정직한 공백 동결**: 일반 오답(R6) 직후의 `diagnose · unmeasured`는 이 태스크가 고치지 않았다.
    그것을 보정으로 인정할지는 Kiki 판정(`G-eos24-loop1-undiagnosed-wrong-criterion` · 판정문 §7-1)
    이다. 아래 단언이 깨지면 그 결정이 구현됐다는 뜻이므로 단언을 새 기준으로 승격하라.
    """
    _require_pg()
    content = _Content(c_problems=3)
    try:
        content.seed()
        with _W2._client() as client:
            _W2._erase_learner(client)
            auth = _W2._login(client)

            wrong = _W2._submit_wrong(client, auth, content.c_pids[0], _W2._UNMATCHED_WRONG_ANSWER)
            state = wrong["learning_state"]
            assert (
                state["rule_id"] == "R6-wrong-undiagnosed"
            ), f"전제 붕괴 — 일반 오답인데 R6가 아니다(오개념 채널이 이 답에 반응했다): {state}"

            rec = _next_problem(client, auth)
            assert rec["learning_state_directive"] is None, rec
            assert rec["reason"]["basis"] != "learning_state", rec
            assert rec["problem_id"] not in {str(p) for p in content.c_pids}, (
                "일반 오답 뒤에도 C 안에 머물렀다 — 그러면 위 테스트의 'C 안' 단언이 상태 경로의 "
                "증거가 되지 못한다(시딩 배치가 변별력을 잃었다)."
            )
            assert rec["action"] == "diagnose", (
                "일반 오답 직후 추천이 더 이상 diagnose가 아니다 — "
                "`G-eos24-loop1-undiagnosed-wrong-criterion` 결정이 구현된 것으로 보인다. "
                "이 단언을 새 기준으로 승격하라."
            )
            _step("control", f"R6 → directive=None · action={rec['action']} · 문항∉C")
    finally:
        content.teardown()


def test_remediation_falls_back_when_the_concept_has_no_untried_problem() -> None:
    """안전장치 ④ — C에 미시도 문항이 없으면 기존 추천으로 돌아가고 그 사유를 남긴다."""
    _require_pg()
    content = _Content(c_problems=1)
    try:
        content.seed()
        with _W2._client() as client:
            _W2._erase_learner(client)
            auth = _W2._login(client)

            wrong = _W2._submit_wrong(client, auth, content.c_pids[0], _W2._WRONG_ANSWER)
            assert wrong["learning_state"]["to_state"] == "REMEDIATING", wrong["learning_state"]

            rec = _next_problem(client, auth)
            assert rec["learning_state_directive"] == "no_candidate_in_concept", rec
            assert rec["reason"]["basis"] != "learning_state", rec
            assert rec["problem_id"] != str(content.c_pids[0]), rec
            _step("fallback", f"directive={rec['learning_state_directive']} · 문항≠C")
    finally:
        content.teardown()


# ──────────────────────────────────────────────────────────────────────────
# EOS-140 — 안전장치 ①의 회차 경계: 미스캔 회차에서 옛 가설이 "방금"으로 읽히지 않는가
#
# `turns_since_evidence = 0`은 "가장 최근 *스캔* 턴에서 매치됐다"일 뿐이다. 정답·답안 없는 오답은
# 스캔하지 않으므로 옛 가설의 값이 0으로 남고, 학생 전체 가설을 읽는 R3는 다시 발화한다. 수정
# 전에는 아래 첫 변이에서 추천이 `applied`·교정 대상 P로 뚫렸다(2026-09-25 실 PG 재현).
# ──────────────────────────────────────────────────────────────────────────
def _submit_attempt(client: Any, auth: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
    """응답 1건 — Week 2 헬퍼(`_submit_wrong`)가 없는 형태(정답 · 답안 없는 오답)를 낸다."""
    resp = client.post("/v1/me/attempts", headers=auth, json=body)
    assert resp.status_code == 201, resp.text
    out: dict[str, Any] = resp.json()
    return out


async def _active_hypothesis_turns(attempt_id: str) -> list[int]:
    """그 응답을 낸 학생의 활성 가설 `turns_since_evidence` — 반례의 전제를 눈으로 확인한다."""
    engine = create_async_engine(_W2._settings().database_url)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT h.turns_since_evidence FROM misconception_hypothesis h "
                        "JOIN problem_attempt a ON a.user_id = h.user_id "
                        "WHERE a.attempt_id = :aid AND h.is_active"
                    ),
                    {"aid": attempt_id},
                )
            ).all()
    finally:
        await engine.dispose()
    return [int(row[0]) for row in rows]


@pytest.mark.parametrize(
    ("third_answer", "expected_scan", "expected_turns"),
    [
        # 반례 — 답안이 없어 스캔이 돌지 않는다. 옛 가설의 tse가 0으로 **남는다**.
        pytest.param(None, "not_run", 0, id="unscanned-answerless-wrong"),
        # 대조군 — 스캔이 돌고 매치가 없다. tse가 1이 되어 경계 없이도 막힌다.
        pytest.param(_W2._UNMATCHED_WRONG_ANSWER, "ran_no_candidate", 1, id="scanned-no-match"),
    ],
)
def test_stale_hypothesis_does_not_pin_remediation_to_another_concept(
    third_answer: str | None, expected_scan: str, expected_turns: int
) -> None:
    """EOS-140 — C에서 관측된 옛 가설로 P에 오개념 교정을 고정하지 않는다(판정문 §4 반례 S1).

    흐름: C 정답 → C 오개념 오답(스캔·매치 → tse 0) → C 정답(미스캔) → P 오답 → 추천.
    맨 앞의 정답은 경계가 **가장 늦은** 전이여야 걸러지게 만든다 — 그 정답의 전이가 옛 스캔보다
    앞에 있으므로, 경계를 가장 이른 전이로 잡는 뮤테이션(`max`→`min`)은 옛 가설을 통과시킨다.
    """
    _require_pg()
    content = _Content(c_problems=3)
    try:
        content.seed()
        with _W2._client() as client:
            _W2._erase_learner(client)
            auth = _W2._login(client)

            _submit_attempt(
                client, auth, {"problem_id": str(content.c_pids[0]), "is_correct": True}
            )
            wrong = _W2._submit_wrong(client, auth, content.c_pids[1], _W2._WRONG_ANSWER)
            assert wrong["learning_state"]["rule_id"] == "R3-wrong-misconception", wrong[
                "learning_state"
            ]
            right = _submit_attempt(
                client, auth, {"problem_id": str(content.c_pids[2]), "is_correct": True}
            )
            assert right["learning_state"]["to_state"] != "REMEDIATING", right["learning_state"]

            body: dict[str, Any] = {"problem_id": str(content.p_pids[0]), "is_correct": False}
            if third_answer is not None:
                body["student_answer"] = third_answer
            third = _submit_attempt(client, auth, body)
            coverage = third["evidence"]["coverage"]
            assert coverage["misconception_scan"] == expected_scan, coverage
            assert third["learning_state"]["rule_id"] == "R3-wrong-misconception", (
                "전제 붕괴 — 옛 가설로 R3가 다시 발화해야 이 반례가 성립한다(학생 전체 활성 가설을 "
                f"읽는 R3 · EOS-138이 그 입력을 좁히면 이 전제가 바뀐다): {third['learning_state']}"
            )
            turns = asyncio.run(_active_hypothesis_turns(third["attempt_id"]))
            assert turns == [
                expected_turns
            ], f"전제 붕괴 — 옛 가설의 tse가 {expected_turns}여야 이 변이가 재려는 것을 잰다: {turns}"

            rec = _next_problem(client, auth)
            assert rec["learning_state_directive"] == "weak_misconception_evidence", (
                "옛 가설(C에서 관측)을 '이번 회차 증거'로 읽고 P에 교정을 고정했다 — 안전장치 ①의 "
                f"회차 경계가 없다: {rec}"
            )
            assert rec["reason"]["basis"] != "learning_state", rec
            assert rec["reason"]["type"] != "misconception_remediation", rec
            _step(
                "stale",
                f"scan={expected_scan} · tse={turns} · R3 재발화 → "
                f"directive={rec['learning_state_directive']}",
            )
    finally:
        content.teardown()


def test_fresh_evidence_after_earlier_attempts_is_still_applied() -> None:
    """EOS-140 양성 대조 — 회차 경계가 **정상 집행을 막지 않는다**.

    앞선 응답(정답)이 원장에 전이를 남긴 뒤라 경계가 NULL이 아니다. 새 오개념 오답의 스캔이 만든
    가설은 그 경계보다 늦으므로 집행돼야 한다. 결정 응답 **자신**의 전이까지 경계에 넣는 뮤테이션은
    경계를 이번 스캔 너머로 밀어 이 테스트를 깨뜨린다(그 행들은 스캔 뒤에 적재된다).
    """
    _require_pg()
    content = _Content(c_problems=3)
    try:
        content.seed()
        with _W2._client() as client:
            _W2._erase_learner(client)
            auth = _W2._login(client)

            _submit_attempt(
                client, auth, {"problem_id": str(content.c_pids[0]), "is_correct": True}
            )
            wrong = _W2._submit_wrong(client, auth, content.p_pids[0], _W2._WRONG_ANSWER)
            assert wrong["learning_state"]["rule_id"] == "R3-wrong-misconception", wrong[
                "learning_state"
            ]

            rec = _next_problem(client, auth)
            assert rec["learning_state_directive"] == "applied", rec
            assert rec["reason"]["basis"] == "learning_state", rec
            assert rec["target_concept"] == str(content.p_concept), rec
            assert rec["problem_id"] == str(
                content.p_pids[1]
            ), f"교정 대상 개념 P의 미시도 문항이 아니다: {rec}"
            _step(
                "fresh", f"앞선 정답 뒤 오개념 오답 → directive={rec['learning_state_directive']}"
            )
    finally:
        content.teardown()
