"""EOS-26 — 원인 미상 오답(R6) 직후 추천이 **선수 개념으로 향하는가** (실 PG · HTTP 경로).

acceptance ④의 집행 확인이다: `l2/learning_state_recommendation.py::route_by_learning_state`가 후보를
선수 개념으로 제한하고, 그 제한이 서빙 응답(`GET /v1/me/next-problem`)을 **실제로 지나가는가**.
설계 정본은 `docs/reviews/eos26_r6_diagnosis_prerequisite_directed_judgment_2026-09-26.md`.

**변별력은 배치에서 나온다** — 오답 개념 C(2.5~3.3) · C의 직접 선수 P(1.2~1.8) · 어느 개념과도
엣지가 없는 방해 개념 D(1.0·1.1)를 심는다. 오답 뒤 θ는 하한 -4.0이라 기본 경로는 가장 쉬운 D 문항을
고른다(EOS-26 이전 동작 — 판정문 §1-1). 그러므로 추천이 P 안에 있다는 것은 "R6 경로가 후보를
선수로 제한했다"의 증거다. P에는 자기 선수 R(1.3·1.5)을 하나 더 둔다 — 탐침을 틀린 뒤 연속 판정이
빠지면 추천이 P를 연습하는 대신 R을 탐침하러 더 내려가므로, **그 절을 이 배치가 밟는다**(R이 없으면
연속 판정을 지워도 P에 선수가 없어 같은 결과가 나온다 — 절을 밟지 않는 픽스처).

**요청 형태 2종**(`prioritize_weak_concepts` 전송 · 미전송 — 실제 모바일 앱은 미전송)으로 같은 여정을
돈다. 한 형태에서만 서는 하강은 약점 가중의 우연이다(판정문 §1-2).

**시딩 경계**: 학습자 상태는 한 줄도 직접 쓰지 않는다(전부 HTTP 부수효과). 저작 콘텐츠만 ORM으로
심는다. 조립기는 페르소나 여정 하네스에서 빌린다(재구현 0). `integration` 마커라 CI
`backend-migrations` 잡이 PR마다 수집한다. hermetic 대응분은
`tests/backend/l2/test_learning_state_recommendation.py`(⑤~⑦절)다.
"""

from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import sys
import uuid
from dataclasses import dataclass
from types import ModuleType
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from whymath_backend.l2.recommendation_evidence import (
    EVENT_TYPE_RECOMMENDATION_TREATMENT,
    META_KEY_LEARNING_STATE_DIRECTIVE,
    META_KEY_POLICY_VERSION,
    POLICY_VERSION_CAT_STATE_UNDIAGNOSED,
)

pytestmark = pytest.mark.integration

_PERSONA_PATH = pathlib.Path(__file__).with_name("test_e2e_persona_journeys.py")
#: 빌려 쓰는 헬퍼 계약 — 하나라도 사라지면 수집 단계에서 이름을 지목하며 실패한다.
_PERSONA_HELPERS = (
    "_UNMATCHED_WRONG_ANSWER",
    "_WRONG_ANSWER",
    "_add_all",
    "_attempt",
    "_begin",
    "_client",
    "_erase_learner",
    "_get",
    "_login",
    "_prereq_edge",
    "_seed_concept",
    "_seed_problems",
    "_settings",
)


def _load_persona_harness() -> ModuleType:
    """페르소나 하네스를 파일 경로로 적재한다(`--import-mode=importlib`라 이름 import 불가)."""
    spec = importlib.util.spec_from_file_location("_eos26_persona_harness", _PERSONA_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"페르소나 하네스 스펙 생성 실패: {_PERSONA_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    missing = [name for name in _PERSONA_HELPERS if not hasattr(module, name)]
    if missing:
        raise RuntimeError(f"페르소나 하네스의 헬퍼가 사라졌다: {missing}")
    return module


_P = _load_persona_harness()

#: 요청 형태 — `prioritize_weak_concepts=true` 전송 여부. 실제 모바일 앱은 보내지 않는다
#: (`src/mobile/lib/features/problems/data/problems_api.dart::getNextProblem` 기본값 false).
_REQUEST_SHAPES: dict[str, bool] = {"weak-first": True, "app-default": False}

#: 원인 미상 오답 규칙 id — 시도 응답의 `learning_state.rule_id`에서 관측한다.
_R6 = "R6-wrong-undiagnosed"


@dataclass
class _Layout:
    """시딩한 배치 — 개념 id와 개념별 문항 id."""

    concept: dict[str, uuid.UUID]
    items: dict[str, list[uuid.UUID]]

    def ids(self, tag: str) -> set[str]:
        return {str(pid) for pid in self.items[tag]}


def _seed(content: Any, bands: dict[str, list[float]], edges: list[tuple[str, str]]) -> _Layout:
    """개념·문항·선수 엣지를 심는다(로그인 *전*). `edges`는 `(선수, 후행)` 태그 쌍이다."""
    concept: dict[str, uuid.UUID] = {}
    items: dict[str, list[uuid.UUID]] = {}
    for tag, difficulties in bands.items():
        concept[tag], _code = _P._seed_concept(content, f"e26-{tag}", f"EOS-26 {tag}")
        items[tag] = _P._seed_problems(content, concept[tag], f"e26{tag}", difficulties)
    for before, after in edges:
        asyncio.run(_P._add_all(_P._prereq_edge(concept[before], concept[after])))
    return _Layout(concept=concept, items=items)


#: 탐침 배치 — C의 직접 선수 P · P의 선수 R · 엣지 없는 방해 개념 D(가장 쉽다).
_PROBE_BANDS: dict[str, list[float]] = {
    "C": [2.5, 2.9, 3.3],
    "P": [1.2, 1.4, 1.6, 1.8],
    "R": [1.3, 1.5],
    "D": [1.0, 1.1],
}
_PROBE_EDGES: list[tuple[str, str]] = [("P", "C"), ("R", "P")]


def _next_problem(client: Any, auth: dict[str, str], *, weak_first: bool) -> dict[str, Any]:
    suffix = "?prioritize_weak_concepts=true" if weak_first else ""
    body: dict[str, Any] = _P._get(client, auth, f"/v1/me/next-problem{suffix}")
    return body


def _wrong(client: Any, auth: dict[str, str], pid: uuid.UUID | str) -> dict[str, Any]:
    """원인 미상 오답 1건 — 오개념 카탈로그 어느 거짓형에도 걸리지 않는 답."""
    body: dict[str, Any] = _P._attempt(
        client, auth, uuid.UUID(str(pid)), correct=False, answer=_P._UNMATCHED_WRONG_ANSWER
    )
    return body


def _rule(body: dict[str, Any]) -> str | None:
    value: str | None = (body.get("learning_state") or {}).get("rule_id")
    return value


async def _treatment_meta(problem_id: str) -> dict[str, Any] | None:
    """처치 기록 meta — 작동 비율의 원자료가 실제로 영속됐는지 본다(읽기 전용)."""
    engine = create_async_engine(_P._settings().database_url)
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


@pytest.mark.parametrize("weak_first", list(_REQUEST_SHAPES.values()), ids=list(_REQUEST_SHAPES))
def test_probe_then_descend_then_release(weak_first: bool) -> None:
    """R6 여정 전체 — 선수 탐침(ⓐ) → 탐침 오답 뒤 선수 연습(ⓑ) → 셋째 오답은 R5라 해제(ⓒ).

    판정문 §0: 개입은 구조적으로 최대 2문항이다. 셋째에서 지시가 사라지는 것까지 봐야 그
    주장이 서빙 경로에서 성립한다.
    """
    content, _journal = _P._begin("E26-probe")
    try:
        layout = _seed(content, _PROBE_BANDS, _PROBE_EDGES)
        with _P._client() as client:
            _P._erase_learner(client)
            auth = _P._login(client)

            # ① 원인 미상 오답 — C의 가장 쉬운 문항. 전제: 상태 머신이 R6로 PRACTICING.
            first = _wrong(client, auth, layout.items["C"][0])
            assert _rule(first) == _R6, f"전제 붕괴 — 원인 미상 오답인데 R6가 아니다: {first}"

            # ② 선수 탐침 — 가장 쉬운 문항은 방해 개념 D에 있지만 추천은 C의 직접 선수 P로 간다.
            probe = _next_problem(client, auth, weak_first=weak_first)
            assert probe["learning_state_directive"] == "prerequisite_probe", probe
            assert probe["problem_id"] in layout.ids("P"), (
                f"탐침 문항이 선수 P가 아니다({probe['problem_id']}) — D면 기본 경로(가장 쉬운 문항), "
                "R이면 탐침이 직접 선수를 넘어 내려갔다."
            )
            assert probe["action"] == "diagnose", probe
            assert probe["target_concept"] == str(layout.concept["P"]), probe
            assert probe["reason"]["type"] == "unmeasured", probe
            assert probe["reason"]["basis"] != "learning_state", probe  # 근거는 숙달 파생이다
            meta = asyncio.run(_treatment_meta(probe["problem_id"]))
            assert meta is not None, "탐침 추천이 나갔는데 처치 기록이 없다"
            assert meta[META_KEY_LEARNING_STATE_DIRECTIVE] == "prerequisite_probe", meta
            assert meta[META_KEY_POLICY_VERSION] == POLICY_VERSION_CAT_STATE_UNDIAGNOSED, meta

            # ③ 탐침도 원인 미상으로 틀린다 — 연속 두 번째 R6.
            second = _wrong(client, auth, probe["problem_id"])
            assert (
                _rule(second) == _R6
            ), f"전제 붕괴 — 2연속 오답(< R5 임계 3)인데 R6가 아니다: {second}"

            # ④ 선수 연습으로 하강 — 방금 틀린 P로 제한 · 근거는 막힌 C · 목표는 P(EOS-124 (나)).
            descend = _next_problem(client, auth, weak_first=weak_first)
            assert descend["learning_state_directive"] == "same_concept_repeat", descend
            assert descend["problem_id"] in layout.ids("P"), (
                f"하강 문항이 P가 아니다({descend['problem_id']}) — R이면 연속 판정 없이 또 탐침했고, "
                "D면 기본 경로로 돌아갔다."
            )
            assert descend["action"] == "practice_prerequisite", descend
            assert descend["target_concept"] == str(layout.concept["P"]), descend
            assert descend["reason"]["concept_id"] == str(layout.concept["C"]), descend
            assert descend["reason"]["type"] == "prerequisite_gap", descend
            assert descend["intent_resolution"] == "served", descend

            # ⑤ 셋째 오답은 R5(반복 실패) — 이 경로를 타지 않는다(집행하지 않는 규칙 · 판정문 §3 ⓒ).
            third = _wrong(client, auth, descend["problem_id"])
            assert _rule(third) == "R5-repeated-failure", third
            released = _next_problem(client, auth, weak_first=weak_first)
            assert released["learning_state_directive"] is None, released
    finally:
        content.teardown()


def test_correct_answer_is_not_directed() -> None:
    """ⓓ — 정답(확신도 미보고 = R2)의 PRACTICING은 지시가 아니다. 탐침도 같은 개념 제한도 없다."""
    content, _journal = _P._begin("E26-r2")
    try:
        layout = _seed(content, _PROBE_BANDS, _PROBE_EDGES)
        with _P._client() as client:
            _P._erase_learner(client)
            auth = _P._login(client)
            right = _P._attempt(client, auth, layout.items["C"][0], correct=True, answer="정답")
            assert _rule(right) == "R2-correct-low-confidence", right
            rec = _next_problem(client, auth, weak_first=False)
            assert rec["learning_state_directive"] is None, rec
            assert rec["reason"]["basis"] != "learning_state", rec
    finally:
        content.teardown()


def test_mastered_prerequisite_is_not_probed() -> None:
    """ⓐ 폴백(반증) — 직접 선수가 이미 숙달이면 원인 후보가 아니다. 같은 개념 C를 연습한다.

    선수 숙달은 HTTP 정답 2회로 만든다(BKT 기본값에서 1회 0.693 · 2회 0.919 — 경계 0.7을 넘는다).
    """
    content, _journal = _P._begin("E26-refuted")
    try:
        layout = _seed(content, _PROBE_BANDS, _PROBE_EDGES)
        with _P._client() as client:
            _P._erase_learner(client)
            auth = _P._login(client)
            for pid in layout.items["P"][:2]:
                _P._attempt(client, auth, pid, correct=True, answer="정답")
            wrong = _wrong(client, auth, layout.items["C"][0])
            assert _rule(wrong) == _R6, wrong
            rec = _next_problem(client, auth, weak_first=False)
            assert rec["learning_state_directive"] == "same_concept_probe_refuted", rec
            assert rec["problem_id"] in layout.ids("C"), rec
            assert rec["target_concept"] == str(layout.concept["C"]), rec
    finally:
        content.teardown()


def test_misconception_on_the_probe_hands_over_to_remediation() -> None:
    """ⓔ R6 → R3 합성 — 탐침 문항을 오개념으로 틀리면 최신 결정은 R3이고 EOS-24 경로가 잇는다.

    요청마다 지시는 하나다(원장 최신 결정). 교정 대상은 탐침 문항의 개념 P다. 반대 방향(R3 → R6)은
    HTTP로 곧바로 만들 수 없다 — R3는 학생 전체의 활성 가설을 읽어, 교정 문항을 매칭 없이 틀려도
    가설이 살아 있는 한 R3가 다시 발화한다(`EOS-138` 범위). 그 방향은 hermetic 테스트
    (`test_non_r6_previous_decision_probes[...R3...]`)가 판정 트리 수준에서 잰다.
    """
    content, _journal = _P._begin("E26-r6r3")
    try:
        layout = _seed(content, _PROBE_BANDS, _PROBE_EDGES)
        with _P._client() as client:
            _P._erase_learner(client)
            auth = _P._login(client)
            first = _wrong(client, auth, layout.items["C"][0])
            assert _rule(first) == _R6, first
            probe = _next_problem(client, auth, weak_first=False)
            assert probe["learning_state_directive"] == "prerequisite_probe", probe
            assert probe["problem_id"] in layout.ids("P"), probe

            miscon = _P._attempt(
                client, auth, uuid.UUID(probe["problem_id"]), correct=False, answer=_P._WRONG_ANSWER
            )
            assert _rule(miscon) == "R3-wrong-misconception", miscon
            remediation = _next_problem(client, auth, weak_first=False)
            assert remediation["learning_state_directive"] == "applied", remediation
            assert remediation["reason"]["type"] == "misconception_remediation", remediation
            assert remediation["target_concept"] == str(layout.concept["P"]), remediation
            assert remediation["problem_id"] in layout.ids("P"), remediation
    finally:
        content.teardown()
