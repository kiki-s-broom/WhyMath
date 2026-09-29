"""EOS-147 — 첫 응답이 정답뿐인 학습자의 다음 추천이 **은행 꼭대기로 뛰지 않는가** (실 PG · HTTP 경로).

수정 전(main `a82f9449`) 실측: 난이도 `1.2 · 1.8 · 2.4 · 2.9 · 3.4 · 3.9 · 4.4 · 4.8` 8문항 은행에서 2.9를
정답으로 내면 다음 `GET /v1/me/next-problem`이 `theta=4.0`(SE 7.897)이고 추천은 **4.8**(은행 최고 난이도)
이었다. 이어서 정답을 내면 4.4 → 3.9 순으로 **내려온다**(역사다리 — 판정문 §1-1). 판정
(`docs/reviews/eos147_all_correct_theta_pin_judgment_2026-09-29.md`)은 추정기를 그대로 두고 추천의
표적 θ만 분리한다: 맞힌 최고 난이도 + 0.5 로짓(잠정 — 처음 1.0이었다가 독립 비판을 받고 내렸다).

이 파일이 지키는 것:

① **바뀌는 것** — 첫 정답 뒤 추천이 3.4(반 칸 위)이고, 정답을 이어 내면 3.4 → 3.9 → 4.4 → 4.8로 **오른
   뒤** 꼭대기 문항을 다 풀면 나머지(2.4)로 내려온다 — 가장 어려운 문항은 다섯 번째에 나간다(수정 전
   2번째·1.0 단계 3번째). 응답이 `selection_theta`(0.4·0.9·1.4·1.9·2.3)와 `theta_boundary="upper"`로
   그 사실을 말하고, 처치 기록에도 `theta_boundary`·`policy_version=cat_v4`가 남는다.
② **바뀌지 않는 것** — 응답의 `theta`(4.0)·`standard_error`(7.897)·`measurement_sufficient`, 능력 API
   (`/ability`·`/ability/history`)와 평가 캡처(ASM-03)의 판정 입력. 처치 기록의 `theta`.
③ **혼합 이력은 추정기로 넘어간다**(처치 기록에 경계 키 없음) · **하한(전부 오답)은 범위 밖이라 종전
   그대로**(선택은 추정 θ = -4.0 · 처치 기록에는 경계 키 `lower`만) — 두 경계를 동결한다.

**잠정 동작의 동결** — 정답 개수·도움 완료를 반영하지 않는 0.5 단계의 사다리다. 표적의 실측 보정과
도움 받은 완료 신호의 반영은 `EOS-39`가 소유하므로, ① 여정의 리터럴은 그 태스크에서 의도적으로 바뀔 수
있다. DB 없는 짝(사다리 순서 동결)은 `tests/backend/l2/test_eos147_selection_theta.py`의 `TestLadderSpeed`다.

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
    META_KEY_POLICY_VERSION,
    META_KEY_SELECTION_THETA,
    META_KEY_THETA,
    META_KEY_THETA_BOUNDARY,
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

#: 첫 정답(라벨 2.9 · b=-0.1) 뒤 모두 정답으로 이어질 때의 여정 — `(추천 난이도 라벨, 그 회차의
#: selection_theta)`. 유도: 표적 = min(4.0, max(0.0, 맞힌 최고 b + 0.5)), 추천 = 남은 문항 중 b가
#: 표적에 가장 가까운 것(a=1이라 정보량 최대와 같다).
_LADDER: list[tuple[float, float]] = [
    (3.4, 0.4),  # 최고 b=-0.1 → 0.4 → b=0.4(라벨 3.4)가 P=0.5로 정보량 최대
    (3.9, 0.9),  # 최고 b=0.4 → 0.9 → b=0.9(라벨 3.9)
    (4.4, 1.4),  # 최고 b=0.9 → 1.4 → b=1.4(라벨 4.4)
    (4.8, 1.9),  # 최고 b=1.4 → 1.9 → 가장 가까운 1.8(라벨 4.8) — 꼭대기, 2.9부터 다섯 번째
    (2.4, 2.3),  # 최고 b=1.8 → 2.3 → 남은 b는 전부 낮다: 가장 가까운 -0.6(라벨 2.4)로 내려온다
]


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
def test_correct_answers_climb_half_a_logit_at_a_time(weak_first: bool) -> None:
    """정답 5건 — 추천은 3.4 → 3.9 → 4.4 → 4.8 → 2.4(반 칸 위에서 시작해 오르고, 꼭대기 뒤에 내려온다).

    수정 전 같은 여정은 4.8 → 4.4 → 3.9 → 3.4 → 2.4였다(첫 정답 뒤 곧장 꼭대기). 응답의 `theta`·SE·중단
    규칙은 매번 추정기의 값 그대로이고(첫 SE는 수정 전 실측 7.897과 같다), 달라진 것은 후보를 고른
    θ(`selection_theta`)뿐이다. 첫 회차에는 처치 기록도 함께 본다 — 경계 사실(`theta_boundary`)과
    정책 식별자(`cat_v4`)가 서빙 경로에서 실제로 남는가.

    **잠정 동작의 동결** — 정답 개수·도움 완료를 반영하지 않는 0.5 단계의 여정이다. 보정은 `EOS-39`가
    소유하므로 이 리터럴은 그 태스크에서 의도적으로 바뀔 수 있다.
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
            for turn, (label, target) in enumerate(_LADDER, start=1):
                rec = _next(client, auth, weak_first=weak_first)
                # 추정 θ는 그대로 — 전부 정답이면 상한 클램프이고 경계 사실이 그것을 말한다.
                assert rec["theta"] == 4.0 and rec["theta_boundary"] == "upper", (turn, rec)
                assert rec["selection_theta"] == pytest.approx(target, abs=1e-9), (turn, rec)
                assert rec["difficulty"] == label, (turn, rec)
                assert rec["measurement_sufficient"] is False, (turn, rec)
                if turn == 1:
                    assert (
                        rec["problem_id"] != hardest
                    ), "첫 정답 뒤 은행 꼭대기로 뛰었다 — 수정 전 결함"
                    assert rec["standard_error"] == pytest.approx(_SE_ONE_CORRECT, abs=1e-3), rec
                    meta = asyncio.run(_treatment_meta(rec["problem_id"]))
                    assert meta is not None, "추천이 나갔는데 처치 기록이 없다"
                    assert meta[META_KEY_THETA] == 4.0, meta  # 기록 theta = 응답 theta(추정 θ)
                    assert meta[META_KEY_SELECTION_THETA] == pytest.approx(0.4, abs=1e-9), meta
                    assert meta[META_KEY_THETA_BOUNDARY] == "upper", meta  # 경계 사실이 남는다
                    assert meta[META_KEY_POLICY_VERSION] == "cat_v4", meta  # 선택 규칙의 판
                _answer(client, auth, rec["problem_id"], correct=True)
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
            assert META_KEY_THETA_BOUNDARY not in meta, meta  # 경계가 아니면 키 자체가 없다
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
            # 처치 기록 — 경계 사실만 남는다(선택 θ = 추정 θ = -4.0이라 selection_theta 키는 없다).
            meta = asyncio.run(_treatment_meta(rec["problem_id"]))
            assert meta is not None, "추천이 나갔는데 처치 기록이 없다"
            assert meta[META_KEY_THETA] == -4.0, meta
            assert meta[META_KEY_THETA_BOUNDARY] == "lower", meta
            assert META_KEY_SELECTION_THETA not in meta, meta
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
