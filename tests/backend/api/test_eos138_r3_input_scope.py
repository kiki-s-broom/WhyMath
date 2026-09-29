"""EOS-138 ② — 상태 머신 R3의 입력이 **이번 응답의 스캔 후보 중 하한 초과**로 좁혀졌는가 (실 PG · HTTP).

판정문: `docs/reviews/eos138_r3_input_scope_and_route_order_judgment_2026-09-28.md`.

종전에는 R3의 입력(`AttemptEvidence.confirmed_misconception_ids`)을 학생 전체의 활성 가설에서
신뢰 하한 없이 읽었다. 그래서 다른 개념에서 생긴 옛 가설 1건만 남아 있어도 이번 오답에 R3가
발화했고, `target_misconception_id`가 방금 틀린 개념과 무관한 옛 가설을 가리켰다(EOS-24 판정문
§4 반례 S1). 이 파일은 그 입구를 세 반례로 동결한다.

  (a) 옛 가설만 남은 학생이 다른 개념에서 **답안 없는 오답**(미스캔) → R3 아님(R6).
  (b) 스캔은 돌았지만 이번 후보의 가설 신뢰가 **정확히 하한(0.7)** → R3 아님(R6).
      이 학생에게는 하한을 넘는 옛 가설(C)도 살아 있다 — 이번 스캔 후보만 보는가도 함께 잰다.
  (c) 대조군: 이번 스캔 후보가 하한 **초과**(0.75) → R3, 교정 대상 = **이번 후보**.
      옛 가설(C)의 감쇠 후 신뢰(≈0.78)가 이번 후보보다 높게 배치해, 학생 전체에서 가장 높은
      가설을 고르는 종전 동작이면 교정 대상이 옛 가설로 틀리게 나온다.

**변별력 설계 — 어느 뮤테이션을 어느 픽스처가 잡는가**
  · 필터 경계 `>` → `>=`: (b)가 R3로 뒤집힌다(신뢰 0.7 정확히).
  · 필터 제거: (b)가 R3로 뒤집힌다.
  · 호출부 미전달(`this_attempt_misconceptions` 누락): (c)가 R6으로 뒤집힌다.
  · 호출부가 이번 스캔 후보가 아니라 갱신 세트 전부를 넘김: (b)가 옛 가설로 R3, (c)가 옛 가설을
    교정 대상으로 낸다.
  · 종전 동작(학생 전체 활성 가설): (a)·(b)가 R3, (c)가 옛 가설 대상.

**(b)·(c)의 이번 후보는 탐지기 주입으로 만든다.** 실 탐지기의 후보 신뢰는 상수(텍스트 0.9 ·
선지 0.8)라 HTTP로는 하한 근방 후보를 만들 수 없다. 능력은 원래 주입받는 좌석이므로
(`get_attempt_misconception_detector` — app.state 등록분) 그 의존성만 덮어쓰고, 가설 갱신·
상태 머신·원장은 전부 운영 코드 그대로 돈다. 옛 가설(C)은 **실 탐지기**로 만든다.

**시딩 경계**: Week 1~3 게이트와 같다 — 학습자 상태는 한 줄도 직접 쓰지 않는다(전부 HTTP
부수효과). 저작 콘텐츠만 ORM으로 심는다. 헬퍼는 Week 2 하네스에서 빌린다(재구현 0).

**CI 배선**: `integration` 마크라 `WHYMATH_RUN_INTEGRATION=1` + 실 PG에서만 돈다. CI의
`backend-migrations` 잡(`pytest -m integration`)이 마커로 수집한다. PG 미도달이면 skip이며,
skip은 통과가 아니다.
"""

from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from types import ModuleType
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from whymath_backend.api._rate_limit import reset_store
from whymath_backend.api._subject_capability_state import get_attempt_misconception_detector
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.schema.assessment_evidence import MisconceptionCandidate, MisconceptionScan

pytestmark = pytest.mark.integration

_WEEK2_PATH = pathlib.Path(__file__).with_name("test_week2_gate_wrong_answer_propagation.py")
_WEEK2_HELPERS = (
    "_EXPECTED_MISCONCEPTION",
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
    spec = importlib.util.spec_from_file_location("_week2_gate_harness_eos138", _WEEK2_PATH)
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

#: 옛 가설 — C 문항에서 실 탐지기가 매치하는 오개념(Week 2 픽스처 정본값).
_OLD_MISCONCEPTION: str = _W2._EXPECTED_MISCONCEPTION
#: 이번 스캔 후보 — 옛 가설과 **다른** 카탈로그 오개념. 같은 id면 강화로 합쳐져 반례가 무너진다.
_THIS_MISCONCEPTION = "combine-unlike-terms"
#: 탐지기 주입 회차에 제출하는 답안 — 스텁은 내용을 보지 않지만, 답안이 있어야 텍스트 채널이 돈다.
_ANY_ANSWER = "3x"


@dataclass(frozen=True)
class _StubScan:
    """`AttemptMisconceptionScan` 구조 Protocol을 만족하는 결과(스캔 3상태 + 후보)."""

    scan: MisconceptionScan
    candidates: Sequence[MisconceptionCandidate]


class _FixedCandidateDetector:
    """게이트 통과 후보 1건을 고정 신뢰로 내는 탐지기 — 하한 근방 후보를 HTTP로 만들기 위한 좌석."""

    def __init__(self, misconception_id: str, confidence: float) -> None:
        self._candidate = MisconceptionCandidate(
            misconception_id=misconception_id, confidence=confidence, gate_passed=True
        )

    def scan_attempt_answer(self, *, question_text: str, student_answer: str | None) -> _StubScan:
        del question_text, student_answer
        return _StubScan(scan=MisconceptionScan.RAN_WITH_CANDIDATES, candidates=(self._candidate,))


def _step(name: str, detail: str) -> None:
    print(f"EOS138_STEP={name} :: {detail}")


class _Content:
    """개념 C(옛 가설이 생기는 곳)·P(이번 오답이 나는 곳) 각 2문항."""

    def __init__(self) -> None:
        self.sfx = uuid.uuid4().hex[:8]
        self.c_concept = uuid.uuid4()
        self.p_concept = uuid.uuid4()
        self.c_pids = [uuid.uuid4() for _ in range(2)]
        self.p_pids = [uuid.uuid4() for _ in range(2)]
        self.skill_id: str | None = None

    def seed(self) -> None:
        skill_id = f"skill.eos138.{self.sfx}"
        asyncio.run(_W2._add_all(_W2._skill_node(skill_id)))
        self.skill_id = skill_id
        asyncio.run(_W2._add_all(_W2._concept(self.c_concept, f"UC.eos138c.{self.sfx}", skill_id)))
        asyncio.run(_W2._add_all(_W2._concept(self.p_concept, f"UC.eos138p.{self.sfx}", skill_id)))
        for pid in self.c_pids:
            asyncio.run(_W2._add_all(_W2._problem(pid, f"{self.sfx}c", 2.5)))
            asyncio.run(_W2._add_all(_W2._problem_concept(pid, self.c_concept)))
        for pid in self.p_pids:
            asyncio.run(_W2._add_all(_W2._problem(pid, f"{self.sfx}p", 2.5)))
            asyncio.run(_W2._add_all(_W2._problem_concept(pid, self.p_concept)))

    def teardown(self) -> None:
        """학습자 먼저, 그 다음 저작 콘텐츠(FK 순서) — 멱등."""
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


def _require_pg() -> None:
    if not asyncio.run(_W2._pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 판정 불가(WHYMATH_DATABASE_URL 확인). 통과가 아니다.")
    asyncio.run(reset_store())


def _submit(client: Any, auth: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
    resp = client.post("/v1/me/attempts", headers=auth, json=body)
    assert resp.status_code == 201, resp.text
    out: dict[str, Any] = resp.json()
    assert out["is_correct"] is False, out
    return out


async def _active_hypotheses(attempt_id: str) -> dict[str, tuple[float, int]]:
    """그 응답을 낸 학생의 활성 가설 {id: (confidence, turns_since_evidence)} — 전제 확인용."""
    engine = create_async_engine(_W2._settings().database_url)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT h.misconception_id, h.confidence, h.turns_since_evidence "
                        "FROM misconception_hypothesis h "
                        "JOIN problem_attempt a ON a.user_id = h.user_id "
                        "WHERE a.attempt_id = :aid AND h.is_active"
                    ),
                    {"aid": attempt_id},
                )
            ).all()
    finally:
        await engine.dispose()
    return {str(row[0]): (float(row[1]), int(row[2])) for row in rows}


def _seed_old_hypothesis(client: Any, auth: dict[str, str], content: _Content) -> None:
    """C 오개념 오답(실 탐지기) — 옛 가설을 만든다. 전제: 그 회차는 R3였다."""
    first = _W2._submit_wrong(client, auth, content.c_pids[0], _W2._WRONG_ANSWER)
    state = first["learning_state"]
    assert (
        state["rule_id"] == "R3-wrong-misconception"
    ), f"전제 붕괴 — C 오개념 오답이 R3가 아니다(옛 가설의 출처가 없다): {state}"
    assert state["target_misconception_id"] == _OLD_MISCONCEPTION, state


def test_catalog_has_both_fixture_ids() -> None:
    """픽스처가 가리키는 오개념이 카탈로그에 실재하는가 — 없으면 저장소가 후보를 조용히 버린다.

    `apply_candidates`는 카탈로그 밖 id를 무시한다. 그러면 (b)·(c)의 이번 후보가 가설이 되지
    못하고, (b)는 *엉뚱한 이유로* 통과한다(후보 부재 = R6). PG 없이도 도는 전제 가드다.
    """
    assert _OLD_MISCONCEPTION in CATALOG_BY_ID
    assert _THIS_MISCONCEPTION in CATALOG_BY_ID
    assert _THIS_MISCONCEPTION != _OLD_MISCONCEPTION


def test_a_unscanned_wrong_answer_does_not_fire_r3_on_an_old_hypothesis() -> None:
    """(a) 옛 가설만 남은 학생 · 다른 개념의 답안 없는 오답(미스캔) → R6."""
    _require_pg()
    content = _Content()
    try:
        content.seed()
        with _W2._client() as client:
            _W2._erase_learner(client)
            auth = _W2._login(client)
            _seed_old_hypothesis(client, auth, content)

            second = _submit(
                client, auth, {"problem_id": str(content.p_pids[0]), "is_correct": False}
            )
            assert second["evidence"]["coverage"]["misconception_scan"] == "not_run", second[
                "evidence"
            ]["coverage"]
            # 전제: 옛 가설이 강한 채로(tse 0) 살아 있다 — 종전 입력이면 R3가 발화했을 상태다.
            hyps = asyncio.run(_active_hypotheses(second["attempt_id"]))
            assert set(hyps) == {_OLD_MISCONCEPTION}, hyps
            old_conf, old_tse = hyps[_OLD_MISCONCEPTION]
            assert old_conf > 0.7 and old_tse == 0, hyps

            state = second["learning_state"]
            assert state["rule_id"] == "R6-wrong-undiagnosed", (
                "미스캔 오답에 옛 가설로 R3가 발화했다 — R3 입력이 이번 응답으로 좁혀지지 않았다: "
                f"{state}"
            )
            assert state["target_misconception_id"] is None, state
            _step("a-unscanned", f"옛 가설 conf={old_conf:.3f} tse={old_tse} → {state['rule_id']}")
    finally:
        content.teardown()


def test_b_scanned_candidate_at_the_floor_does_not_fire_r3() -> None:
    """(b) 스캔은 돌았지만 이번 후보 신뢰가 정확히 하한(0.7) → R6 — 하한은 **초과**다."""
    _require_pg()
    content = _Content()
    try:
        content.seed()
        with _W2._client() as client:
            _W2._erase_learner(client)
            auth = _W2._login(client)
            _seed_old_hypothesis(client, auth, content)

            client.app.dependency_overrides[get_attempt_misconception_detector] = (
                lambda: _FixedCandidateDetector(_THIS_MISCONCEPTION, 0.7)
            )
            second = _submit(
                client,
                auth,
                {
                    "problem_id": str(content.p_pids[0]),
                    "is_correct": False,
                    "student_answer": _ANY_ANSWER,
                },
            )
            assert second["evidence"]["coverage"]["misconception_scan"] == "ran_with_candidates"
            hyps = asyncio.run(_active_hypotheses(second["attempt_id"]))
            # 전제 ①: 이번 후보가 가설이 됐다(카탈로그 밖이라 버려진 게 아니다) · 신뢰 정확히 0.7.
            assert hyps[_THIS_MISCONCEPTION] == (pytest.approx(0.7), 0), hyps
            # 전제 ②: 하한을 넘는 옛 가설이 함께 살아 있다 — 이번 후보만 보는가를 가른다.
            assert hyps[_OLD_MISCONCEPTION][0] > 0.7, hyps

            state = second["learning_state"]
            assert state["rule_id"] == "R6-wrong-undiagnosed", (
                "하한 이하 후보(또는 이번 후보가 아닌 옛 가설)로 R3가 발화했다: " f"{state}"
            )
            assert state["target_misconception_id"] is None, state
            _step("b-at-floor", f"이번 후보 0.7 · 옛 가설 {hyps[_OLD_MISCONCEPTION][0]:.3f} → R6")
    finally:
        content.teardown()


def test_c_scanned_candidate_above_the_floor_fires_r3_on_that_candidate() -> None:
    """(c) 대조군 — 이번 후보 0.75(하한 초과) → R3, 교정 대상 = 이번 후보(옛 가설 아님)."""
    _require_pg()
    content = _Content()
    try:
        content.seed()
        with _W2._client() as client:
            _W2._erase_learner(client)
            auth = _W2._login(client)
            _seed_old_hypothesis(client, auth, content)

            client.app.dependency_overrides[get_attempt_misconception_detector] = (
                lambda: _FixedCandidateDetector(_THIS_MISCONCEPTION, 0.75)
            )
            second = _submit(
                client,
                auth,
                {
                    "problem_id": str(content.p_pids[0]),
                    "is_correct": False,
                    "student_answer": _ANY_ANSWER,
                },
            )
            hyps = asyncio.run(_active_hypotheses(second["attempt_id"]))
            assert hyps[_THIS_MISCONCEPTION] == (pytest.approx(0.75), 0), hyps
            # 변별력 전제: 옛 가설이 이번 후보보다 **높다** — 학생 전체 최고 가설을 고르면 틀린다.
            assert hyps[_OLD_MISCONCEPTION][0] > hyps[_THIS_MISCONCEPTION][0], hyps

            state = second["learning_state"]
            assert (
                state["rule_id"] == "R3-wrong-misconception"
            ), f"이번 스캔의 하한 초과 후보가 R3에 닿지 않았다(호출부 미전달?): {state}"
            assert state["next_action"] == "REMEDIATE_MISCONCEPTION", state
            assert state["target_misconception_id"] == _THIS_MISCONCEPTION, (
                "교정 대상이 이번 후보가 아니다 — 옛 가설(다른 개념)을 가리킨다: " f"{state}"
            )
            _step(
                "c-above-floor",
                f"이번 후보 0.75 · 옛 가설 {hyps[_OLD_MISCONCEPTION][0]:.3f} → "
                f"R3 target={state['target_misconception_id']}",
            )
    finally:
        content.teardown()
