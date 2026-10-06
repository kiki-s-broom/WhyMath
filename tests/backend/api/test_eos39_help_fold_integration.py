"""EOS-39 서빙 경로 — 실 PG에서 코치 대화를 **실제로 불러** 도움 완료가 추천 표적을 낮추는가.

`used_hint`·`problem_attempt`를 직접 쓰지 않는다. 공개 HTTP 표면(`/v1/coach/sessions`·`…/turns`·
`GET /v1/me/next-problem`)만 불러 DB에 남은 것을 본다(기본 SKIP — `WHYMATH_RUN_INTEGRATION=1`).
판정문 `docs/reviews/eos39_app_help_completion_selection_judgment_2026-10-06.md`가 지키려는 것:

① **같은 완료인데 도움 여부만 다른 두 학습자의 다음 추천이 갈라진다**(규칙의 존재 이유 — 앱 학생의
   추천열이 학생 행동에 반응한다). 둘 다 `theta`(4.0)·`theta_boundary`(upper)는 **같다**(추정기 불변) —
   달라지는 것은 후보를 고른 `selection_theta`(독립 성공 0.5 · 도움 완료 −0.5)와 그 결과 문항이다.
② **오답 + 도움 완료**(EOS-146 이후의 실제 흐름)가 한 문항에서 실패 **1건**으로 접힌다 — 추정 θ는
   그 문항의 오답+정답을 반반으로 읽어 0.0이고(혼합 이력), 표적은 −0.5다.
③ **처치 기록과 리포트가 그 사실을 남긴다** — `selection_help_count`·`policy_version=cat_v5`, 그리고
   추천 도달 리포트의 실 JSONB 쿼리(`has_key`·`->>`)가 그 키를 센다.
④ **`used_hint` 라벨 프로브**(비판 #1) — 코치 흐름 몇 개에서 라벨이 실제로 어떻게 붙는가. 이것은
   **현상의 고정이지 옳다는 선언이 아니다**: 라벨은 학생이 도움을 요청했는가가 아니라 코치가 단계 2
   이상을 공급했는가이고, 오답이 숙달 라벨 '초보'를 만들면 코치가 단계를 올린다(EOS-146 acceptance ⑩ —
   판정 대기). 그 판정이 바뀌면 이 프로브가 먼저 깨져 도움 접기의 입력이 달라졌음을 눈에 보이게 한다.

헬퍼는 EOS-133 통합 테스트(→ 시나리오 스위트 → 페르소나 하네스)를 경로 로딩으로 빌려 쓴다.
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
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from whymath_backend.l2.recommendation_evidence import (
    EVENT_TYPE_RECOMMENDATION_TREATMENT,
    META_KEY_POLICY_VERSION,
    META_KEY_SELECTION_HELP_COUNT,
    META_KEY_SELECTION_HINT_UNKNOWN_COUNT,
    META_KEY_SELECTION_THETA,
    META_KEY_THETA,
)
from whymath_backend.ops import recommendation_reach_report as reach_report

pytestmark = pytest.mark.integration

_HARNESS_PATH = pathlib.Path(__file__).with_name("test_eos133_hint_attribution_integration.py")
#: 빌려 쓰는 헬퍼 계약 — 하나라도 사라지면 수집 단계에서 이름을 지목하며 깨진다.
_HELPERS = (
    "_S",
    "_open",
    "_turn",
    "_submit_correct",
    "_reflect",
    "_attribution",
    "_supply",
    "_NEUTRAL",
    "_FRUSTRATED",
    "_WRONG_STEPS",
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_eos39_hint_harness", _HARNESS_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"EOS-133 통합 하네스 스펙 생성 실패: {_HARNESS_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    missing = [name for name in _HELPERS if not hasattr(module, name)]
    if missing:
        raise RuntimeError(f"EOS-133 통합 하네스의 헬퍼가 사라졌다: {missing}")
    return module


_H = _load()
_S = _H._S
_P = _S._P

#: 코치 완료 문항의 난이도 라벨 3.0(b = 0.0). 추천 후보 은행은 그 밖의 문항이다(아래 `_BANK`).
_COACH_LABEL = 3.0
#: 추천 후보 — 라벨(`b = 라벨 − 3`): −1.8 · −1.2 · −0.6 · 0.9 · 1.4 · 1.8.
_BANK: list[float] = [1.2, 1.8, 2.4, 3.9, 4.4, 4.8]

#: 정답 1건(b = 0.0 · θ = 4.0)의 SE — 1 / sqrt(P(1−P)), P = 1/(1 + e^−4) = 0.98201 → 7.5244.
#: 라벨이 독립 성공이든 도움 완료든 **같다**(추정기가 힌트 귀속을 읽지 않는다).
_SE_ONE_CORRECT = 7.5244
#: 독립 성공 1건(b = 0.0)의 선택 θ — 전부 정답이라 EOS-147 상한 사다리: 0.0 + 0.5.
_SELECTION_INDEPENDENT = 0.5
#: 도움 완료 1건(b = 0.0)의 선택 θ — 접으면 전부 실패라 하한 사다리: min(0.0, 0.0 − 0.5).
_SELECTION_HELPED = -0.5
#: 각 선택 θ에서 |b − θ|가 최소인 후보 라벨 — 0.5 → b = 0.9(라벨 3.9) · −0.5 → b = −0.6(라벨 2.4).
_PICK_INDEPENDENT = 3.9
_PICK_HELPED = 2.4


def _seed(content: Any, tag: str) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """개념 1개 + 코치 완료 문항(라벨 3.0) + 추천 후보 은행."""
    cid, _code = _S._seed_concept(content, f"h{tag}", "EOS-39 도움 접기")
    coach_pid = _S._answered_problem(content, cid, f"h{tag}", _COACH_LABEL)
    bank = _P._seed_problems(content, cid, f"b{tag}", _BANK)
    return coach_pid, bank


async def _treatment_meta(problem_id: str) -> dict[str, Any] | None:
    """추천 처치 기록 meta(읽기 전용)."""
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


def _complete_with_stuck_opening(client: Any, auth: dict[str, str], pid: uuid.UUID) -> str:
    """막힘 신호로 시작 → 단계 2 힌트 → 정답 → 돌아보기 — 도움 완료(`used_hint=True`)."""
    did = _H._open(client, auth, pid, _S._STUCK)
    assert _S._hint_levels(_S._trace(client, auth)) == [2], "막힘 신호가 단계 2를 못 만들었다"
    _H._submit_correct(client, auth, did, "이렇게 풀었어요")
    return str(_H._reflect(client, auth, did))


def _complete_with_direction_only(client: Any, auth: dict[str, str], pid: uuid.UUID) -> str:
    """중립 발화로 시작 → 방향(단계 1)만 → 정답 → 돌아보기 — 독립 성공(`used_hint=False`)."""
    did = _H._open(client, auth, pid, _H._NEUTRAL)
    assert _S._hint_levels(_S._trace(client, auth)) == [1], "중립 발화가 단계 1이 아니다"
    _H._submit_correct(client, auth, did, "이렇게 풀었어요")
    return str(_H._reflect(client, auth, did))


def _case(tag: str, body: Any) -> None:
    content, journal = _S._begin(f"EOS-39-{tag}")
    try:
        coach_pid, bank = _seed(content, tag)
        with _S._client() as client:
            _S._erase_learner(client)  # 지난 회차 잔여 제거(멱등)
            auth = _S._login(client)
            uid = _S._user_id(client, auth)
            body(client, auth, uid, coach_pid, bank, journal)
            _S._erase_learner(client)
        journal.dump()
    finally:
        content.teardown()


# ══════════════════════════════════════════════════════════════════════════
# ① 같은 완료, 다른 표적
# ══════════════════════════════════════════════════════════════════════════
def test_independent_completion_keeps_the_ladder_up() -> None:
    """대조군 — 방향(단계 1)만 받고 푼 완료는 독립 성공이다. EOS-147 상한 사다리(0.5) 그대로."""

    def body(
        client: Any, auth: dict[str, str], uid: uuid.UUID, pid: uuid.UUID, bank: Any, j: Any
    ) -> None:
        attempt_id = _complete_with_direction_only(client, auth, pid)
        used, _rows = _H._attribution(uid, attempt_id)
        assert used is False, used  # 전제 — 도움 신호가 없다
        rec = _P._next_problem(client, auth, weak_first=False)
        j.record(
            "①대조",
            "독립 성공 → 다음 추천",
            theta=rec["theta"],
            selection_theta=rec["selection_theta"],
            difficulty=rec["difficulty"],
        )
        assert rec["theta"] == 4.0 and rec["theta_boundary"] == "upper", rec
        assert rec["standard_error"] == pytest.approx(_SE_ONE_CORRECT, abs=1e-3), rec
        assert rec["selection_theta"] == pytest.approx(_SELECTION_INDEPENDENT, abs=1e-9), rec
        assert rec["difficulty"] == _PICK_INDEPENDENT, rec
        meta = asyncio.run(_treatment_meta(rec["problem_id"]))
        assert meta is not None
        assert META_KEY_SELECTION_HELP_COUNT not in meta, meta  # 도움 채널이 닿지 않았다
        assert meta[META_KEY_POLICY_VERSION] == "cat_v5", meta

    _case("ind", body)


def test_help_completion_lowers_the_target_while_the_estimate_stays() -> None:
    """같은 완료인데 코치가 단계 2를 공급한 문항 — 추정은 그대로(4.0 upper), 표적은 −0.5로 내려온다."""

    def body(
        client: Any, auth: dict[str, str], uid: uuid.UUID, pid: uuid.UUID, bank: Any, j: Any
    ) -> None:
        attempt_id = _complete_with_stuck_opening(client, auth, pid)
        used, _rows = _H._attribution(uid, attempt_id)
        assert used is True, used  # 전제 — 도움 신호가 있다(EOS-133 귀속)
        rec = _P._next_problem(client, auth, weak_first=False)
        j.record(
            "①도움",
            "도움 완료 → 다음 추천",
            theta=rec["theta"],
            selection_theta=rec["selection_theta"],
            difficulty=rec["difficulty"],
        )
        # **추정기 불변** — 라벨이 달라도 응답의 theta·경계·SE는 독립 성공과 같다.
        assert rec["theta"] == 4.0 and rec["theta_boundary"] == "upper", rec
        assert rec["standard_error"] == pytest.approx(_SE_ONE_CORRECT, abs=1e-3), rec
        assert rec["measurement_sufficient"] is False, rec
        # 표적만 갈라진다 — 독립 성공(0.5 → 라벨 3.9)과 도움 완료(−0.5 → 라벨 2.4).
        assert rec["selection_theta"] == pytest.approx(_SELECTION_HELPED, abs=1e-9), rec
        assert rec["difficulty"] == _PICK_HELPED, rec
        assert rec["difficulty"] < _PICK_INDEPENDENT
        # ③ 처치 기록 — 접힌 문항 수와 새 판이 남는다.
        meta = asyncio.run(_treatment_meta(rec["problem_id"]))
        assert meta is not None
        assert meta[META_KEY_THETA] == 4.0, meta  # 기록 theta = 응답 theta(추정 θ)
        assert meta[META_KEY_SELECTION_THETA] == pytest.approx(_SELECTION_HELPED, abs=1e-9), meta
        assert meta[META_KEY_SELECTION_HELP_COUNT] == 1, meta
        assert meta[META_KEY_POLICY_VERSION] == "cat_v5", meta

    _case("help", body)


# ══════════════════════════════════════════════════════════════════════════
# ② 오답 + 도움 완료 — EOS-146 이후의 실제 흐름
# ══════════════════════════════════════════════════════════════════════════
def test_a_wrong_submission_plus_a_help_completion_folds_to_one_failure() -> None:
    """오답 → 좌절 → 정답 한 문항 — 추정기는 오답+정답을 반반(θ=b=0.0, 혼합)으로 읽는다.

    표적용 응답은 그 문항을 실패 1건으로 접어 전부 실패가 되고, 하한 사다리 min(0.0, 0.0 − 0.5) = −0.5다.
    접기가 없었다면(현행 main) 선택 θ는 추정 θ(0.0)와 같아 표적이 문항 난이도에 **머문다**(판정문 §1).
    """

    def body(
        client: Any, auth: dict[str, str], uid: uuid.UUID, pid: uuid.UUID, bank: Any, j: Any
    ) -> None:
        did = _H._open(client, auth, pid, _H._NEUTRAL)
        redirected = _H._turn(
            client,
            auth,
            did,
            _H._FRUSTRATED,
            solution_steps=_H._WRONG_STEPS,
            solution_step_types=["계산"],
        )
        assert redirected["problem_complete"] is False, redirected
        _H._turn(client, auth, did, _H._FRUSTRATED)  # 숙달 라벨 규칙 5 → 단계 3(⑥과 같은 장면)
        _H._submit_correct(client, auth, did, "이렇게 풀었어요")
        attempt_id = str(_H._reflect(client, auth, did))
        used, _rows = _H._attribution(uid, attempt_id)
        assert used is True, used
        rec = _P._next_problem(client, auth, weak_first=False)
        j.record(
            "②",
            "오답 + 도움 완료",
            theta=rec["theta"],
            selection_theta=rec["selection_theta"],
            boundary=rec["theta_boundary"],
        )
        assert rec["theta_boundary"] is None, rec  # 오답 행이 있어 혼합 이력 — MLE가 존재한다
        assert rec["theta"] == pytest.approx(0.0, abs=1e-6), rec
        assert rec["selection_theta"] == pytest.approx(_SELECTION_HELPED, abs=1e-9), rec
        meta = asyncio.run(_treatment_meta(rec["problem_id"]))
        assert meta is not None
        assert meta[META_KEY_SELECTION_HELP_COUNT] == 1, meta  # 두 행이 한 문항 → 1건

    _case("wrongfix", body)


def test_a_plain_attempt_has_no_hint_label_and_is_counted_as_unknown_not_as_help() -> None:
    """`POST /v1/me/attempts`로 직접 낸 정답 — 코치를 안 거쳐 `used_hint`가 NULL(모른다 ≠ 아니다).

    미상은 **독립 성공으로 센다**(선택 θ 0.5 그대로 — 모르는 라벨로 표적을 낮추지 않는다). 대신 그
    사실을 처치 기록의 `selection_hint_unknown_count`와 리포트가 남긴다. 이 키가 처치 기록에 실리는
    경로(`api/me.py` → `record_recommendation_treatment`)는 이 시나리오에서만 실 스택으로 닫힌다.
    """

    def body(
        client: Any, auth: dict[str, str], uid: uuid.UUID, pid: uuid.UUID, bank: Any, j: Any
    ) -> None:
        _P._attempt(client, auth, pid, correct=True, answer="직접 제출")
        rec = _P._next_problem(client, auth, weak_first=False)
        j.record(
            "①미상",
            "코치 없는 정답 → 다음 추천",
            theta=rec["theta"],
            selection_theta=rec["selection_theta"],
            difficulty=rec["difficulty"],
        )
        assert rec["theta"] == 4.0 and rec["theta_boundary"] == "upper", rec
        assert rec["selection_theta"] == pytest.approx(_SELECTION_INDEPENDENT, abs=1e-9), rec
        assert rec["difficulty"] == _PICK_INDEPENDENT, rec  # 미상은 표적을 낮추지 않는다
        meta = asyncio.run(_treatment_meta(rec["problem_id"]))
        assert meta is not None
        assert META_KEY_SELECTION_HELP_COUNT not in meta, meta  # 접힌 것이 없다
        assert meta[META_KEY_SELECTION_HINT_UNKNOWN_COUNT] == 1, meta
        assert meta[META_KEY_POLICY_VERSION] == "cat_v5", meta

        async def _count() -> reach_report.ReachCounts:
            engine = create_async_engine(_P._settings().database_url)
            try:
                async with async_sessionmaker(engine, class_=AsyncSession)() as session:
                    return await reach_report.fetch_reach_counts(session)
            finally:
                await engine.dispose()

        counts = asyncio.run(_count())
        assert counts.selection_hint_unknown_key_total >= 1, counts  # 하한 — 다른 회차 행이 섞인다

    _case("unknown", body)


# ══════════════════════════════════════════════════════════════════════════
# ③ 리포트 — 실 JSONB 쿼리가 그 키를 센다
# ══════════════════════════════════════════════════════════════════════════
def test_the_reach_report_counts_the_firing_of_the_rule_in_real_jsonb() -> None:
    """`has_key`·`->>`의 SQL 정확성은 가짜 세션이 못 본다(stmt를 무시) — 실 PG에서 센다."""

    def body(
        client: Any, auth: dict[str, str], uid: uuid.UUID, pid: uuid.UUID, bank: Any, j: Any
    ) -> None:
        _complete_with_stuck_opening(client, auth, pid)
        rec = _P._next_problem(client, auth, weak_first=False)
        assert rec["selection_theta"] == pytest.approx(_SELECTION_HELPED, abs=1e-9), rec

        async def _count() -> reach_report.ReachCounts:
            engine = create_async_engine(_P._settings().database_url)
            try:
                async with async_sessionmaker(engine, class_=AsyncSession)() as session:
                    return await reach_report.fetch_reach_counts(session)
            finally:
                await engine.dispose()

        counts = asyncio.run(_count())
        j.record(
            "③",
            "리포트 실 JSONB 집계",
            처치=counts.recommendation_treatment_total,
            selection_theta=counts.selection_theta_key_total,
            upper=counts.theta_boundary_upper_total,
            help=counts.selection_help_key_total,
        )
        # 다른 학습자·이전 회차의 행이 섞여 있을 수 있어 정확한 값이 아니라 **하한**으로 묻는다 — 이
        # 학습자의 처치 1건이 세 축(선택 θ 키 · upper · 도움 접기 키)에 모두 들어 있어야 한다.
        assert counts.selection_help_key_total >= 1, counts
        assert counts.selection_theta_key_total >= counts.selection_help_key_total, counts
        assert counts.theta_boundary_upper_total >= 1, counts
        assert counts.recommendation_treatment_total >= counts.selection_theta_key_total, counts
        report = reach_report.build_report(counts)
        assert report.selection_help_key_rate is not None and report.selection_help_key_rate > 0

    _case("report", body)


# ══════════════════════════════════════════════════════════════════════════
# ④ `used_hint` 라벨 프로브 — 현상의 고정(옳다는 선언이 아니다)
# ══════════════════════════════════════════════════════════════════════════
def _probe(name: str, follow_ups: list[str]) -> Any:
    """오답 한 건 뒤 `follow_ups`(학생 메시지) → 정답 → 돌아보기 — `(used_hint, 공급 단계 시퀀스)`."""

    def body(
        client: Any, auth: dict[str, str], uid: uuid.UUID, pid: uuid.UUID, bank: Any, j: Any
    ) -> None:
        did = _H._open(client, auth, pid, _H._NEUTRAL)
        _H._turn(
            client,
            auth,
            did,
            _H._NEUTRAL,
            solution_steps=_H._WRONG_STEPS,
            solution_step_types=["계산"],
        )
        for message in follow_ups:
            _H._turn(client, auth, did, message)
        _H._submit_correct(client, auth, did, "이렇게 풀었어요")
        attempt_id = str(_H._reflect(client, auth, did))
        used, _rows = _H._attribution(uid, attempt_id)
        levels = _S._hint_levels(_S._trace(client, auth))
        j.record("④", name, used_hint=used, 공급=levels)
        _PROBE_RESULTS[name] = (used, levels)

    return body


_PROBE_RESULTS: dict[str, tuple[Any, list[int]]] = {}


def test_probe_wrong_then_immediate_correct_is_not_labeled_help() -> None:
    """오답 → **곧바로** 정답: 사이에 코치 턴이 없어 공급 행이 귀속 창에 없다 → `used_hint=False`.

    이 흐름은 접히지 않고 오답+정답 **한 쌍**(반반)으로 남는다 — 비판이 "얼마나 많은 학생이 이 경로인지는
    모른다"고 한 바로 그 경로의 라벨이다. (곧바로 다음 학생 메시지가 정답이면 가로챈 턴은 적재하지
    않으므로 공급은 시작 때의 단계 1뿐이다.)
    """
    _case("p1", _probe("오답→곧바로 정답", []))
    used, levels = _PROBE_RESULTS["오답→곧바로 정답"]
    assert used is False, (used, levels)
    assert levels == [1], levels


def test_probe_wrong_then_a_neutral_chat_turn_then_correct_is_labeled_help() -> None:
    """오답 → 중립 대화 한 턴 → 정답: 학생이 아무것도 요청하지 않았는데 `used_hint=True`가 된다.

    오답 한 건이 숙달 라벨 '초보'를 만들고, 규칙 5(`decide_hint_level`)가 기본 단계 1을 2로 올린다 —
    **코치 정책이 만든 도움 라벨**이다. 도움 접기는 이것을 실패로 센다(판정문 §2-2 — 구조적 오귀속 위험의
    실제 사례). 이 라벨 규칙(EOS-146 acceptance ⑩)이 판정 대기 중이다.
    """
    _case("p2", _probe("오답→중립 대화→정답", ["x의 값을 다시 구해볼게요"]))
    used, levels = _PROBE_RESULTS["오답→중립 대화→정답"]
    assert used is True, (used, levels)
    assert levels and levels[-1] >= 2, levels  # 마지막 공급이 도움 단계(2 이상)다


def test_probe_wrong_then_frustrated_then_correct_is_labeled_help() -> None:
    """오답 → 좌절 → 정답: 통합 테스트 ⑥이 고정한 `[1, 3]`과 같은 장면 — `used_hint=True`."""
    _case("p3", _probe("오답→좌절→정답", [_H._FRUSTRATED]))
    used, levels = _PROBE_RESULTS["오답→좌절→정답"]
    assert used is True, (used, levels)
    assert levels == [1, 3], levels
