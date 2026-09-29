"""EOS-147 — 첫 응답이 정답뿐인 학습자의 다음 추천이 **은행 꼭대기로 뛰지 않는가** (실 PG · HTTP 경로).

수정 전(main `a82f9449`) 실측: 난이도 `1.2 · 1.8 · 2.4 · 2.9 · 3.4 · 3.9 · 4.4 · 4.8` 8문항 은행에서 2.9를
정답으로 내면 다음 `GET /v1/me/next-problem`이 `theta=4.0`(SE 7.897)이고 추천은 **4.8**(은행 최고 난이도)
이었다. 이어서 정답을 내면 4.4 → 3.9 순으로 **내려온다**(역사다리 — 판정문 §1-1). 판정
(`docs/reviews/eos147_all_correct_theta_pin_judgment_2026-09-29.md`)은 추정기를 그대로 두고 추천의
표적 θ만 분리한다: 맞힌 최고 난이도 + 1단계.

이 파일이 지키는 것:

① **바뀌는 것** — 첫 정답 뒤 추천이 3.9(한 칸 위)이고, 정답을 이어 내면 3.9 → 4.8 → 4.4로 **오른 뒤**
   꼭대기에서 내려온다. 응답이 `selection_theta`(0.9·1.9·2.8)와 `theta_boundary="upper"`로 그 사실을 말한다.
② **바뀌지 않는 것** — 응답의 `theta`(4.0)·`standard_error`(7.897)·`measurement_sufficient`, 능력 API
   (`/ability`·`/ability/history`)와 평가 캡처(ASM-03)의 판정 입력. 처치 기록의 `theta`.
③ **혼합 이력은 추정기로 넘어간다** · **하한(전부 오답)은 범위 밖이라 종전 그대로** — 두 경계를 동결한다.

**요청 형태 2종**(`prioritize_weak_concepts` 전송·미전송 — 실제 모바일 앱은 미전송)으로 같은 여정을
돈다. 한 형태에서만 서는 결과는 약점 가중의 우연이다(EOS-26 판정문 §1-2).

**시딩 경계**: 학습자 상태는 한 줄도 직접 쓰지 않는다(전부 HTTP 부수효과). 저작 콘텐츠만 ORM으로 심는다.
조립기는 페르소나 여정 하네스에서 빌린다(재구현 0). `integration` 마커라 CI `backend-migrations` 잡이
PR마다 수집한다.
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

from whymath_backend.l2.recommendation_evidence import (
    EVENT_TYPE_RECOMMENDATION_TREATMENT,
    META_KEY_SELECTION_THETA,
    META_KEY_THETA,
)

pytestmark = pytest.mark.integration

_PERSONA_PATH = pathlib.Path(__file__).with_name("test_e2e_persona_journeys.py")
#: 빌려 쓰는 헬퍼 계약 — 하나라도 사라지면 수집 단계에서 이름을 지목하며 실패한다.
_PERSONA_HELPERS = (
    "_attempt",
    "_begin",
    "_client",
    "_erase_learner",
    "_get",
    "_login",
    "_seed_concept",
    "_seed_problems",
    "_settings",
)


def _load_persona_harness() -> ModuleType:
    """페르소나 하네스를 파일 경로로 적재한다(`--import-mode=importlib`라 이름 import 불가)."""
    spec = importlib.util.spec_from_file_location("_eos147_persona_harness", _PERSONA_PATH)
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

#: 요청 형태 — `prioritize_weak_concepts=true` 전송 여부. 실제 모바일 앱은 보내지 않는다.
_REQUEST_SHAPES: dict[str, bool] = {"weak-first": True, "app-default": False}

#: 한 개념 8문항 — 난이도 라벨(`b = 라벨 − 3`). 콜드스타트 추천은 θ=0에 가장 가까운 2.9다.
_BANK: list[float] = [1.2, 1.8, 2.4, 2.9, 3.4, 3.9, 4.4, 4.8]
_SE_ONE_CORRECT = 7.8966  # 수정 전 실측(b=-0.1 정답 1건 · θ=4.0에서의 SE) — 리터럴로 동결한다


def _next(client: Any, auth: dict[str, str], *, weak_first: bool) -> dict[str, Any]:
    suffix = "?prioritize_weak_concepts=true" if weak_first else ""
    body: dict[str, Any] = _P._get(client, auth, f"/v1/me/next-problem{suffix}")
    return body


def _answer(client: Any, auth: dict[str, str], pid: uuid.UUID | str, *, correct: bool) -> None:
    _P._attempt(client, auth, uuid.UUID(str(pid)), correct=correct, answer="정답")


async def _treatment_meta(problem_id: str) -> dict[str, Any] | None:
    """처치 기록 meta — 후보 점수가 어느 θ로 계산됐는지 사후에 되짚을 수 있는지 본다(읽기 전용)."""
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
def test_first_correct_answers_climb_one_step_at_a_time(weak_first: bool) -> None:
    """정답 3건 — 추천은 3.9 → 4.8 → 4.4(한 칸 위에서 시작해 오르고, 꼭대기 뒤에 내려온다).

    수정 전 같은 여정은 4.8 → 4.4 → 3.9였다. 응답의 `theta`·SE·중단 규칙은 세 번 모두 추정기의 값
    그대로이고(첫 SE는 수정 전 실측 7.897과 같다), 달라진 것은 후보를 고른 θ(`selection_theta`)뿐이다.
    """
    content, _journal = _P._begin("E147-ladder")
    try:
        cid, _code = _P._seed_concept(content, "k", "EOS-147 K")
        pids = _P._seed_problems(content, cid, "e147k", _BANK)
        hardest = str(pids[_BANK.index(4.8)])
        with _P._client() as client:
            _P._erase_learner(client)
            auth = _P._login(client)

            _answer(client, auth, pids[_BANK.index(2.9)], correct=True)
            first = _next(client, auth, weak_first=weak_first)
            assert first["theta"] == 4.0, first  # 추정 θ는 그대로 — 전부 정답이면 상한 클램프
            assert first["theta_boundary"] == "upper", first
            assert first["selection_theta"] == pytest.approx(0.9, abs=1e-9), first
            assert first["problem_id"] != hardest, "첫 정답 뒤 은행 꼭대기로 뛰었다 — 수정 전 결함"
            assert first["difficulty"] == 3.9, first  # 맞힌 2.9에서 한 칸 위
            assert first["standard_error"] == pytest.approx(_SE_ONE_CORRECT, abs=1e-3), first
            assert first["measurement_sufficient"] is False, first

            meta = asyncio.run(_treatment_meta(first["problem_id"]))
            assert meta is not None, "추천이 나갔는데 처치 기록이 없다"
            assert meta[META_KEY_THETA] == 4.0, meta  # 기록 theta = 응답 theta(추정 θ)
            assert meta[META_KEY_SELECTION_THETA] == pytest.approx(0.9, abs=1e-9), meta

            _answer(client, auth, first["problem_id"], correct=True)
            second = _next(client, auth, weak_first=weak_first)
            assert second["theta"] == 4.0 and second["theta_boundary"] == "upper", second
            assert second["selection_theta"] == pytest.approx(1.9, abs=1e-9), second
            assert second["difficulty"] == 4.8, second  # 사다리가 꼭대기에 닿는다

            _answer(client, auth, second["problem_id"], correct=True)
            third = _next(client, auth, weak_first=weak_first)
            assert third["selection_theta"] == pytest.approx(2.8, abs=1e-9), third
            assert third["difficulty"] == 4.4, third  # 꼭대기 문항을 다 풀었으니 다음으로 어려운 것
    finally:
        content.teardown()


def test_a_wrong_answer_hands_the_selection_back_to_the_estimator() -> None:
    """혼합 이력 — 오답이 하나라도 있으면 MLE가 존재하고, 선택 θ는 그 추정 θ와 같다(규칙 밖)."""
    content, _journal = _P._begin("E147-mixed")
    try:
        cid, _code = _P._seed_concept(content, "k", "EOS-147 K")
        pids = _P._seed_problems(content, cid, "e147k", _BANK)
        with _P._client() as client:
            _P._erase_learner(client)
            auth = _P._login(client)
            _answer(client, auth, pids[_BANK.index(2.9)], correct=True)  # b = -0.1
            _answer(client, auth, pids[_BANK.index(3.9)], correct=False)  # b = 0.9
            rec = _next(client, auth, weak_first=False)
            assert rec["theta_boundary"] is None, rec
            assert -4.0 < rec["theta"] < 4.0, rec
            assert rec["selection_theta"] == rec["theta"], rec
            # 정답 b=-0.1 · 오답 b=0.9의 MLE는 0.4(두 문항의 중점) — 리터럴로 동결한다.
            assert rec["theta"] == pytest.approx(0.4, abs=1e-6), rec
            meta = asyncio.run(_treatment_meta(rec["problem_id"]))
            assert meta is not None
            assert META_KEY_SELECTION_THETA not in meta, meta  # 다를 때만 남긴다
    finally:
        content.teardown()


def test_first_wrong_answer_is_reported_but_keeps_the_easiest_pick() -> None:
    """하한 비대칭 동결 — 전부 오답이면 경계 사실만 싣고 선택은 종전(-4.0 → 가장 쉬운 문항)이다.

    범위 밖으로 둔 근거는 판정문 §4-4다. EOS-24·EOS-26의 기준선이 이 동작을 전제로 서 있다.
    """
    content, _journal = _P._begin("E147-lower")
    try:
        cid, _code = _P._seed_concept(content, "k", "EOS-147 K")
        pids = _P._seed_problems(content, cid, "e147k", _BANK)
        with _P._client() as client:
            _P._erase_learner(client)
            auth = _P._login(client)
            _answer(client, auth, pids[_BANK.index(2.9)], correct=False)
            rec = _next(client, auth, weak_first=False)
            assert rec["theta"] == -4.0, rec
            assert rec["theta_boundary"] == "lower", rec
            assert rec["selection_theta"] == -4.0, rec
            assert rec["difficulty"] == 1.2, rec  # 가장 쉬운 문항
    finally:
        content.teardown()


def test_estimator_surfaces_and_the_capture_boundary_are_unchanged() -> None:
    """**바뀌지 않는 것** — 능력 API 3종과 평가 캡처가 읽는 값은 전부 정답 이력에서도 종전 그대로다.

    추정기를 바꾸는 안(A·B)은 여기가 깨진다: `/ability`가 4.0이 아니게 되고 SE가 작아져 중단 규칙이
    앞당겨진다(판정문 §3). 이 테스트는 그 소비처들이 추정 θ(4.0)를 계속 읽는다는 것을 실 PG로 동결한다.
    """
    content, _journal = _P._begin("E147-frozen")
    try:
        cid, _code = _P._seed_concept(content, "k", "EOS-147 K")
        pids = _P._seed_problems(content, cid, "e147k", _BANK)
        with _P._client() as client:
            _P._erase_learner(client)
            auth = _P._login(client)
            _answer(client, auth, pids[_BANK.index(2.9)], correct=True)

            ability = _P._get(client, auth, "/v1/me/ability")
            assert ability["theta"] == 4.0, ability
            assert ability["response_count"] == 1, ability
            assert ability["standard_error"] == pytest.approx(_SE_ONE_CORRECT, abs=1e-3), ability

            history = _P._get(client, auth, "/v1/me/ability/history")
            assert [round(point["theta"], 6) for point in history] == [4.0], history

            resp = client.post("/v1/me/assessments/capture", headers=auth)
            assert resp.status_code == 200, resp.text
            capture = resp.json()
            assert capture["written"] is False, capture
            assert capture["reason"] == "insufficient_measurement", capture
            assert capture["measurement_sufficient"] is False, capture
            assert capture["administered_count"] == 1, capture
            assert capture["standard_error"] == pytest.approx(_SE_ONE_CORRECT, abs=1e-3), capture
    finally:
        content.teardown()
