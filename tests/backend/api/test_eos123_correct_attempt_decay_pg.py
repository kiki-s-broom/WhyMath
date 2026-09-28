"""EOS-123 — 정답 회차 오개념 가설 정책의 **실 PG 서빙 경로** 판정.

`POST /v1/me/attempts` 한 경로에서 정책 4행동(`APPLY` · `DECAY_ONLY` · `HOLD_CONFLICT` · `NONE`)이
실제 DB의 가설 행을 어떻게 바꾸는지 한 학습자로 차례로 잰다. 단위 테스트(`test_attempt_hypothesis
_policy.py`)는 표를, `test_me.py::TestAttemptCorrectAnswerHypothesis`는 배선을 보지만, 둘 다
`apply_candidates`를 대역으로 바꾸므로 **감쇠가 실제로 영속되는가 · 보류가 정말 행을 안
건드리는가 · 증거 그래프에 아무것도 안 쓰는가**는 여기서만 드러난다.

판정 포인트(판정문 `docs/reviews/eos123_correct_attempt_refutation_judgment_2026-09-28.md`):
  ① 정답 + 훑었는데 후보 없음 → 1턴 감쇠(0.90 → 0.78 · tse 0 → 1 · evidence_count 불변)
  ② 그 강도는 오개념 미관측 **오답**과 같은 1턴이다(0.78 → 0.68) — 정답을 반증으로 과대 계상 금지
  ③ 정답 보고 + 그 오개념의 거짓형 답 → 보류(행 전체 불변 — `updated_at`까지)
  ④ 답안 없는 정답 → 무변화(관측하지 않은 것을 근거로 깎지 않는다)
  ⑤ 어느 경우에도 증거 그래프(`evidence_links` — 반출 `misconception_evidence`)에 쓰지 않는다
  ⓪ 가설이 없는 학습자의 정답 → 201 · 행 0건(빈 세트 감쇠가 부작용을 만들지 않는다)

**시딩 경계** — Week 1·2 게이트와 같다: 학습자 상태는 한 줄도 직접 쓰지 않는다(전부 HTTP
부수효과). 저작 콘텐츠(concept·skill_node·problem·problem_concept)만 ORM으로 심고, 관측은 부수
효과가 없는 본인 반출(`/v1/me/export`)에서 한다. 헬퍼는 Week 2 하네스에서 빌려 쓴다(재구현 0).
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

# ── Week 2 게이트 하네스의 검증된 조립기 재사용 (재구현 0) ──────────────────────
# 경로 로딩인 이유: 이 저장소의 pytest는 `--import-mode=importlib`이라 형제 테스트 모듈이 이름으로
# 임포트되지 않는다(페르소나 하네스와 같은 방식).
_WEEK2_PATH = pathlib.Path(__file__).with_name("test_week2_gate_wrong_answer_propagation.py")
#: 빌려 쓰는 헬퍼 계약 — 하나라도 사라지면 수집 단계에서 실패한다(조용한 표류 방지).
_WEEK2_HELPERS = (
    "_EXPECTED_MISCONCEPTION",
    "_UNMATCHED_WRONG_ANSWER",
    "_WRONG_ANSWER",
    "_add_all",
    "_cleanup_content",
    "_client",
    "_delete_skill_node",
    "_erase_learner",
    "_login",
    "_pg_reachable",
    "_problem",
    "_problem_concept",
    "_seed",
)


def _load_week2_harness() -> ModuleType:
    """Week 2 하네스를 파일 경로로 적재하고 헬퍼 계약을 검사한다."""
    if not _WEEK2_PATH.exists():
        raise RuntimeError(
            f"Week 2 게이트 하네스가 없다: {_WEEK2_PATH}. 이 판정은 그 조립기를 재사용한다 — "
            "파일이 옮겨졌으면 이 경로를 함께 고친다."
        )
    spec = importlib.util.spec_from_file_location("_eos123_week2_harness", _WEEK2_PATH)
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
_EXPECTED_MISCONCEPTION: str = _W2._EXPECTED_MISCONCEPTION
_UNMATCHED_WRONG_ANSWER: str = _W2._UNMATCHED_WRONG_ANSWER
_WRONG_ANSWER: str = _W2._WRONG_ANSWER

#: 발문 `다음 식을 전개하시오: (x+2)^2`의 참 정답 — ⓪ 거짓 등식 가드가 막아 후보 0건이어야 한다.
_TRUE_ANSWER = "x^2+4x+4"
#: 1턴 감쇠 배율(`hypothesis.decay` · 반감기 5턴). 값은 리터럴로 둔다 — 상수를 import하면 상수
#: 뮤테이션을 따라 기대값도 움직인다(MISC-30 교훈).
_ONE_TURN = 0.5 ** (1 / 5)
#: 행 전체 불변을 볼 때 비교하는 필드 — `updated_at`이 핵심이다(UPDATE가 한 번도 안 났다는 증거).
_ROW_FIELDS = (
    "confidence",
    "turns_since_evidence",
    "evidence_count",
    "is_active",
    "deactivated_reason",
    "updated_at",
)


def _export(client: Any, auth: dict[str, str]) -> dict[str, Any]:
    resp = client.get("/v1/me/export", headers=auth)
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json().get("data", {})
    return data


def _hypothesis_rows(client: Any, auth: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = _export(client, auth).get("misconception_hypotheses") or []
    return rows


def _row_of(client: Any, auth: dict[str, str], mid: str) -> dict[str, Any]:
    matches = [r for r in _hypothesis_rows(client, auth) if r.get("misconception_id") == mid]
    assert len(matches) == 1, f"가설 행이 정확히 1건이 아니다({mid}): {matches}"
    return matches[0]


def _evidence_count(client: Any, auth: dict[str, str]) -> int:
    return len(_export(client, auth).get("misconception_evidence") or [])


def _submit(
    client: Any, auth: dict[str, str], pid: uuid.UUID, *, correct: bool, answer: str | None
) -> dict[str, Any]:
    payload: dict[str, Any] = {"problem_id": str(pid), "is_correct": correct}
    if answer is not None:
        payload["student_answer"] = answer
    resp = client.post("/v1/me/attempts", headers=auth, json=payload)
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    assert body["is_correct"] is correct, body
    return body


def _scan_of(body: dict[str, Any]) -> str:
    scan: str = body["evidence"]["coverage"]["misconception_scan"]
    return scan


def _snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return {k: row.get(k) for k in _ROW_FIELDS}


def test_correct_attempt_hypothesis_policy_on_real_pg() -> None:
    """정답 회차 4행동이 실 PG 가설 행에 남기는 흔적 — 한 학습자로 차례로 잰다."""
    if not asyncio.run(_W2._pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 판정 불가(WHYMATH_DATABASE_URL 확인). 통과가 아니다.")
    # 레이트리미터 격리 — 앞선 통합 테스트가 IP 버킷을 소진하면 쓰기 호출이 429를 받는다.
    asyncio.run(reset_store())

    sfx = uuid.uuid4().hex[:8]
    cid = uuid.uuid4()
    pids = [uuid.uuid4() for _ in range(5)]
    # 시딩 *전에* 선언한다 — 시딩이 중간에 실패해도 정리가 이름을 알아야 지운다.
    skill_id: str | None = None
    try:
        _code, skill_id = _W2._seed(cid, pids[0], sfx)
        # 문항과 매핑을 **따로** 커밋한다 — 한 세션에 섞으면 ORM이 FK 의존을 모른 채(관계 미정의)
        # 매핑을 먼저 넣어 ForeignKeyViolation이 난다(2026-09-28 실측).
        extra_pids = pids[1:]
        asyncio.run(
            _W2._add_all(
                *(_W2._problem(pid, f"{sfx}-{i}", 3.0) for i, pid in enumerate(extra_pids, 1))
            )
        )
        asyncio.run(_W2._add_all(*(_W2._problem_concept(pid, cid) for pid in extra_pids)))

        with _W2._client() as client:
            _W2._erase_learner(client)
            auth = _W2._login(client)

            # ⓪ 가설이 없는 학습자의 정답 — 감쇠할 대상이 없어도 201이고 행이 생기지 않는다.
            body0 = _submit(client, auth, pids[0], correct=True, answer=_TRUE_ANSWER)
            assert _scan_of(body0) == "ran_no_candidate", body0["evidence"]
            assert _hypothesis_rows(client, auth) == []

            # 기준 가설 — 오개념 오답 1회(0.90 · tse 0 · count 1).
            _submit(client, auth, pids[1], correct=False, answer=_WRONG_ANSWER)
            base = _row_of(client, auth, _EXPECTED_MISCONCEPTION)
            assert float(base["confidence"]) == pytest.approx(0.90)
            assert base["turns_since_evidence"] == 0
            assert base["evidence_count"] == 1
            assert base["is_active"] is True
            # 채점 경로는 어느 행동에서도 증거 그래프에 쓰지 않는다(EOS-104 ④ · ⑤).
            assert _evidence_count(client, auth) == 0

            # ③ HOLD_CONFLICT — 정답 보고인데 그 오개념의 거짓형 답. 행 전체가 그대로여야 한다.
            body_hold = _submit(client, auth, pids[2], correct=True, answer=_WRONG_ANSWER)
            assert _scan_of(body_hold) == "ran_with_candidates"
            assert body_hold["misconception_review_coaching"] is None
            held = _row_of(client, auth, _EXPECTED_MISCONCEPTION)
            assert _snapshot(held) == _snapshot(base), (
                "정답 보고 + 오개념 거짓형 답인데 가설 행이 바뀌었다 — 충돌 회차는 감쇠도 강화도 "
                f"하지 않아야 한다(EOS-123 보류): {_snapshot(base)} → {_snapshot(held)}"
            )

            # ④ NONE — 답안 없는 정답. 훑지 않았으므로 행 전체가 그대로다.
            body_none = _submit(client, auth, pids[3], correct=True, answer=None)
            assert _scan_of(body_none) == "not_run"
            untouched = _row_of(client, auth, _EXPECTED_MISCONCEPTION)
            assert _snapshot(untouched) == _snapshot(
                base
            ), f"훑지 않은 정답 회차가 가설을 바꿨다: {_snapshot(base)} → {_snapshot(untouched)}"

            # ① DECAY_ONLY — 겨냥 문항의 참 정답. 1턴 감쇠(0.90 → 0.78) · 증거 수 불변.
            body_decay = _submit(client, auth, pids[4], correct=True, answer=_TRUE_ANSWER)
            assert _scan_of(body_decay) == "ran_no_candidate"
            assert body_decay["misconception_review_coaching"] is None
            decayed = _row_of(client, auth, _EXPECTED_MISCONCEPTION)
            conf_base = float(base["confidence"])
            conf_decayed = float(decayed["confidence"])
            assert conf_decayed == pytest.approx(
                round(conf_base * _ONE_TURN, 2), abs=1e-9
            ), f"정답 회차가 1턴 감쇠가 아니다: {conf_base} → {conf_decayed}"
            assert decayed["turns_since_evidence"] == 1
            assert decayed["evidence_count"] == 1  # 감쇠는 증거가 아니다 — 누적 수 불변.
            assert decayed["is_active"] is True
            assert _evidence_count(client, auth) == 0

            # ② 같은 강도 — 오개념 미관측 **오답**도 같은 1턴(0.78 → 0.68 · tse 2).
            _submit(client, auth, pids[0], correct=False, answer=_UNMATCHED_WRONG_ANSWER)
            wrong_decayed = _row_of(client, auth, _EXPECTED_MISCONCEPTION)
            conf_wrong = float(wrong_decayed["confidence"])
            assert conf_wrong == pytest.approx(
                round(conf_decayed * _ONE_TURN, 2), abs=1e-9
            ), f"오개념 미관측 오답의 감쇠가 정답과 다른 강도다: {conf_decayed} → {conf_wrong}"
            assert wrong_decayed["turns_since_evidence"] == 2
            assert _evidence_count(client, auth) == 0

            print(
                "EOS123_PG_TRACE :: "
                f"기준={conf_base} · 보류={float(held['confidence'])} · "
                f"무변화={float(untouched['confidence'])} · 정답감쇠={conf_decayed} · "
                f"오답감쇠={conf_wrong}"
            )
    finally:
        try:
            with _W2._client() as client:
                _W2._erase_learner(client)
        finally:
            try:
                asyncio.run(_W2._cleanup_content(problem_ids=pids, concept_ids=[cid]))
            finally:
                if skill_id is not None:
                    asyncio.run(_W2._delete_skill_node(skill_id))
