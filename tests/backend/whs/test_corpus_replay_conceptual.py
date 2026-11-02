"""P3-95 — 개념형 답(답이 값이 아니라 개수·판정)의 corpus replay finalize 검증 (hermetic).

12미적Ⅰ-02-09 문항군(`wm-p3-diff-eqapp-*`)은 답이 "서로 다른 실근의 개수"라 `verify.answer_map`이
비어 있다. 종전 finalize는 빈 치환맵으로 `verify_answer`를 돌려 fail → 재생 39건이 전부 거부됐다.
이 파일은 ① 로더가 `answer_kind`·주장 답을 읽는다 ② finalize가 개념형 검증기로 검산한다
③ 틀린 개수·빈 답·모르는 검증기 키는 verified가 되지 않는다 ④ 값형 문항의 동작·적재 JSON은
그대로다 — 를 못 박는다.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import pytest

from whymath_backend.whs.corpus_replay import ChainReplayPolicy, ReplayItem, load_replay_items
from whymath_backend.whs.harness import (
    FinalizeAction,
    SolverState,
    _run_verify,
    _solution_path_json,
)

# 실제 코퍼스 문항(wm-p3-diff-eqapp-2bedcffed537)과 같은 형태 — 곡선 y = 2x³-3x²-12x 와 y = 9 의
# 교점 개수. 2x³-3x²-12x-9 = (x-3)(2x²+3x+3) 이고 뒤 인수의 판별식이 9-24<0 이라 실근은 1개다.
_COND = "2*x**3 - 3*x**2 - 12*x = 9"
_STEPS = [
    "Derivative(2*x**3 - 3*x**2 - 12*x, x).doit() = 0",
    "6*x**2 - 6*x - 12 = 0",
    "6*(x - 2)*(x + 1) = 0",
    "x = -1, x = 2",
]
_CORPUS = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "corpus"
    / "problem_bank_p3_calculus1_diff_v0"
    / "problems.jsonl"
)


def _count_record(answer: object = "1", kind: object = "real_root_count") -> dict[str, object]:
    verify: dict[str, object] = {
        "conditions": _COND,
        "answer_map": {},
        "solution_steps": _STEPS,
    }
    if kind is not None:
        verify["answer_kind"] = kind
    return {
        "problem_id": str(uuid.uuid5(uuid.NAMESPACE_URL, "whymath:test:p3-95")),
        "slug": "wm-p3-diff-eqapp-test",
        "answer": answer,
        "verify": verify,
    }


# ── ① 로더 ───────────────────────────────────────────────────────────


def test_loader_reads_answer_kind_and_claimed_answer() -> None:
    (item,) = load_replay_items(json.dumps(_count_record()))
    assert item.answer_kind == "real_root_count"
    assert item.claimed_answer == "1"
    assert item.answer_map == {}


def test_loader_accepts_integer_answer() -> None:
    (item,) = load_replay_items(json.dumps(_count_record(answer=1)))
    assert item.claimed_answer == "1"


@pytest.mark.parametrize("bad", [None, True, 1.5, ["1"]])
def test_loader_drops_non_scalar_answer(bad: object) -> None:
    # bool은 int의 하위형이라 "True"로 새지 않게 따로 막는다 — 주장 답이 없으면 None.
    (item,) = load_replay_items(json.dumps(_count_record(answer=bad)))
    assert item.claimed_answer is None


@pytest.mark.parametrize("kind", [None, "", "   ", 3])
def test_loader_value_type_has_no_conceptual_fields(kind: object) -> None:
    # answer_kind가 없거나 문자열이 아니면 값형 — 주장 답도 싣지 않는다(answer_map이 맡는다).
    (item,) = load_replay_items(json.dumps(_count_record(kind=kind)))
    assert item.answer_kind is None
    assert item.claimed_answer is None


# ── ② 정책이 finalize에 실어 보낸다 ──────────────────────────────────


def test_policy_finalize_carries_conceptual_fields() -> None:
    (item,) = load_replay_items(json.dumps(_count_record()))
    policy = ChainReplayPolicy(item, bad_step=None)
    state = SolverState(problem_id=item.problem_id)

    async def _drain() -> FinalizeAction:
        while True:
            action = await policy.next_action(state)
            if isinstance(action, FinalizeAction):
                return action

    final = asyncio.run(_drain())
    assert final.answer_kind == "real_root_count"
    assert final.claimed_answer == "1"
    assert final.answer == {}


# ── ③ finalize 검증 등급 ─────────────────────────────────────────────


def test_value_path_with_empty_answer_still_fails() -> None:
    # 결손 고정 — answer_kind 없이 빈 치환맵이면 종전처럼 failed(이 PR 전의 거부 원인).
    assert _run_verify([_COND], {}, _STEPS) == "failed"


def test_count_answer_verified() -> None:
    grade = _run_verify([_COND], {}, _STEPS, answer_kind="real_root_count", claimed_answer="1")
    assert grade == "verified"


@pytest.mark.parametrize("wrong", ["0", "2", "3"])
def test_wrong_count_fails(wrong: str) -> None:
    grade = _run_verify([_COND], {}, _STEPS, answer_kind="real_root_count", claimed_answer=wrong)
    assert grade == "failed"


@pytest.mark.parametrize("claimed", [None, "", "  "])
def test_missing_claim_is_unverified_not_verified(claimed: str | None) -> None:
    grade = _run_verify([_COND], {}, _STEPS, answer_kind="real_root_count", claimed_answer=claimed)
    assert grade == "unverified"


def test_unknown_kind_is_unverified_not_verified() -> None:
    grade = _run_verify([_COND], {}, _STEPS, answer_kind="no_such_kind", claimed_answer="1")
    assert grade == "unverified"


def test_wrong_step_still_fails_even_with_right_count() -> None:
    # 이중 체크(§4) — 답 개수가 맞아도 틀린 과정은 차단한다.
    bad_steps = [*_STEPS[:2], "6*(x - 2)*(x - 1) = 0", "x = 1, x = 2"]
    grade = _run_verify([_COND], {}, bad_steps, answer_kind="real_root_count", claimed_answer="1")
    assert grade == "failed"


# ── ④ 적재 JSON ─────────────────────────────────────────────────────


def test_value_type_solution_path_keys_unchanged() -> None:
    # dedup은 solution_path 정확 일치로 기존 행을 재사용한다 — 값형 JSON이 바뀌면 재적재 중복이 난다.
    action = FinalizeAction(conditions=["x = 5"], answer={"x": "5"}, steps=["x", "5"])
    assert set(_solution_path_json(action)) == {"conditions", "answer", "steps"}


def test_conceptual_solution_path_records_kind_and_claim() -> None:
    action = FinalizeAction(
        conditions=[_COND],
        answer={},
        steps=_STEPS,
        answer_kind="real_root_count",
        claimed_answer="1",
    )
    path = _solution_path_json(action)
    assert path["answer_kind"] == "real_root_count"
    assert path["claimed_answer"] == "1"


# ── 실제 코퍼스 — 인수 조건 ③의 검증기 축(DB 없이) ──────────────────


def test_real_eqapp_corpus_items_now_verify() -> None:
    items = [
        item
        for item in load_replay_items(_CORPUS.read_text(encoding="utf-8"))
        if item.slug.startswith("wm-p3-diff-eqapp-")
    ]
    # 스캔 0건은 공허 통과다 — 대상이 있어야 한다.
    assert items, "eqapp 재생 대상 0건 — 코퍼스 경로·로더 필터 확인"
    assert all(item.answer_kind == "real_root_count" for item in items)
    sample = items[:5]
    grades = [
        _run_verify(
            [item.conditions],
            item.answer_map,
            list(item.steps),
            answer_kind=item.answer_kind,
            claimed_answer=item.claimed_answer,
        )
        for item in sample
    ]
    assert grades == ["verified"] * len(sample)


def test_replay_item_defaults_keep_value_type() -> None:
    # 기존 생성자 호출(키워드 4개)이 그대로 값형으로 동작한다.
    item = ReplayItem(
        problem_id=uuid.uuid4(),
        slug="t",
        conditions="x = 5",
        answer_map={"x": "5"},
        steps=("x", "5"),
    )
    assert item.answer_kind is None
    assert item.claimed_answer is None
