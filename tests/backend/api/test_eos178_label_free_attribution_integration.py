"""EOS-178 서빙 경로 — 실 PG에서 코치 대화를 **실제로 불러** 라벨만으로 올라간 단계가 도움으로 세어지지 않는가.

`used_hint`·공급 원장을 직접 쓰지 않는다(리포트 SQL 검증 한 곳만 예외 — 아래 ④). 공개 HTTP 표면(`/v1/coach/
sessions`·`…/turns`·`GET /v1/me/next-problem`)만 불러 DB에 남은 것을 본다(기본 SKIP —
`WHYMATH_RUN_INTEGRATION=1`). 판정문 `docs/reviews/eos178_beginner_label_hint_judgment_2026-10-06.md`가
지키려는 것:

① **라벨만으로 올라간 단계는 원장에 남되 도움으로 세지 않는다** — 오답 한 건이 숙달 라벨 '초보'를 만들고
   규칙 5가 신호 없는 턴의 단계를 1→2로 올린다. 원장은 `hint_level=2`와 함께 `base_level=1`·
   `ability_level='초보'`를 적고, 귀속은 그 행을 세지 않는다(`used_hint=False`).
② **학생 신호가 올린 단계는 센다** — 좌절 발화가 올린 단계(`base_level>=2`)는 라벨이 얹혀도 도움이다.
③ **킬 스위치** — `WHYMATH_L4_HINT_ATTRIBUTION_LABEL_FREE_ENABLED=false`면 같은 장면이 종전(EOS-133)처럼
   `used_hint=True`다.
④ **다음 추천까지 간다** — 라벨-단독 흐름은 EOS-39 도움 접기로 가지 않는다(`selection_help_count` 키가
   처치 기록에 없다). 리포트 §7의 실 JSONB·`bool_or` SQL은 가짜 세션이 못 보므로(stmt를 무시) 합성 원장
   행 4쌍의 **증분**으로 센다.

헬퍼는 EOS-133 통합 테스트(→ 시나리오 스위트 → 페르소나 하네스)를 경로 로딩으로 빌려 쓴다.
"""

from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import sys
import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from types import ModuleType
from typing import Any

import pytest
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from whymath_backend.config import get_settings
from whymath_backend.db.models.activity import AttemptEvent
from whymath_backend.l2.recommendation_evidence import (
    EVENT_TYPE_RECOMMENDATION_TREATMENT,
    META_KEY_POLICY_VERSION,
    META_KEY_SELECTION_HELP_COUNT,
)
from whymath_backend.ops import recommendation_reach_report as reach_report
from whymath_backend.schema.enums import EventType

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
    "_NEUTRAL",
    "_FRUSTRATED",
    "_WRONG_STEPS",
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_eos178_hint_harness", _HARNESS_PATH)
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

#: 코치 완료 문항의 난이도 라벨 3.0(b = 0.0). 추천 후보 은행은 그 밖의 문항이다.
_COACH_LABEL = 3.0
_BANK: list[float] = [1.2, 1.8, 2.4, 3.9, 4.4, 4.8]


@pytest.fixture
def label_free_disabled(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """킬 스위치를 끈다 — 환경변수를 **먼저** 지운 뒤 캐시를 비워 다른 테스트로 새지 않게 한다."""
    monkeypatch.setenv("WHYMATH_L4_HINT_ATTRIBUTION_LABEL_FREE_ENABLED", "false")
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("WHYMATH_L4_HINT_ATTRIBUTION_LABEL_FREE_ENABLED", raising=False)
    get_settings.cache_clear()


def _seed(content: Any, tag: str) -> tuple[uuid.UUID, list[uuid.UUID]]:
    cid, _code = _S._seed_concept(content, f"l{tag}", "EOS-178 라벨-단독 공급")
    coach_pid = _S._answered_problem(content, cid, f"l{tag}", _COACH_LABEL)
    bank = _P._seed_problems(content, cid, f"k{tag}", _BANK)
    return coach_pid, bank


def _case(tag: str, body: Any) -> None:
    content, journal = _S._begin(f"EOS-178-{tag}")
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


def _ledger(uid: uuid.UUID, pid: uuid.UUID) -> list[tuple[int, int | None, str | None]]:
    """이 학생·문항 공급 원장 — (hint_level, base_level, ability_level), 시각순."""
    rows = _S._read_rows(
        "SELECT (event_data->>'hint_level')::int, (event_data->>'base_level')::int,"
        " event_data->>'ability_level' FROM attempt_event"
        " WHERE user_id = :uid AND problem_id = :pid AND event_type = '힌트제공'"
        " ORDER BY event_at",
        {"uid": str(uid), "pid": str(pid)},
    )
    return [(int(r[0]), r[1], r[2]) for r in rows]


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


def _wrong_then(follow_ups: list[str]) -> Any:
    """오답 한 건 뒤 `follow_ups` → 정답 → 돌아보기 — 본문이 `(used_hint, 원장)`을 돌려준다."""
    result: dict[str, Any] = {}

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
        result["used"] = used
        result["ledger"] = _ledger(uid, pid)
        rec = _P._next_problem(client, auth, weak_first=False)
        result["rec"] = rec
        result["meta"] = asyncio.run(_treatment_meta(rec["problem_id"]))
        j.record("EOS-178", "오답 뒤 흐름", used_hint=used, 원장=result["ledger"])

    body.result = result  # type: ignore[attr-defined]
    return body


# ══════════════════════════════════════════════════════════════════════════
# ① 라벨만 올린 단계 — 원장에는 남고 귀속에서는 빠진다
# ══════════════════════════════════════════════════════════════════════════
def test_label_only_supply_is_recorded_but_not_counted_as_help() -> None:
    body = _wrong_then(["x의 값을 다시 구해볼게요"])
    _case("p2", body)
    used, ledger = body.result["used"], body.result["ledger"]  # type: ignore[attr-defined]
    levels = [lv for lv, _b, _a in ledger]
    assert levels == [1, 2], ledger  # 중립 발화인데 최종 단계가 2다 — 라벨이 올렸다
    # 마지막 행: 최종 2, 라벨 없는 단계 1, 적용된 라벨 '초보' — 원장이 라벨의 효과를 그대로 적는다.
    assert ledger[-1] == (2, 1, "초보"), ledger
    # 첫 행(오답 전 — 숙달 미관측): 라벨 없이 결정됐다.
    assert ledger[0][1] == 1 and ledger[0][2] is None, ledger
    assert used is False, (used, ledger)  # 신호도 전달도 없는 내부 수치는 도움이 아니다


# ══════════════════════════════════════════════════════════════════════════
# ② 학생 신호가 올린 단계는 도움이다
# ══════════════════════════════════════════════════════════════════════════
def test_a_frustration_signal_supply_is_help_and_records_the_signal_base() -> None:
    body = _wrong_then([_H._FRUSTRATED])
    _case("p3", body)
    used, ledger = body.result["used"], body.result["ledger"]  # type: ignore[attr-defined]
    assert [lv for lv, _b, _a in ledger] == [1, 3], ledger
    # 좌절 신호 턴: 라벨 없는 단계 2(= prev 1 + 1) + '초보' 한 칸 = 최종 3.
    assert ledger[-1] == (3, 2, "초보"), ledger
    assert used is True, (used, ledger)


# ══════════════════════════════════════════════════════════════════════════
# ③ 킬 스위치 — 같은 장면이 EOS-133 규칙으로 돌아간다
# ══════════════════════════════════════════════════════════════════════════
def test_kill_switch_restores_the_eos133_counting(label_free_disabled: None) -> None:
    body = _wrong_then(["x의 값을 다시 구해볼게요"])
    _case("off", body)
    used, ledger = body.result["used"], body.result["ledger"]  # type: ignore[attr-defined]
    assert ledger[-1] == (2, 1, "초보"), ledger  # 원장 기록은 스위치와 무관하다(재료는 항상 남긴다)
    assert used is True, (used, ledger)  # 귀속만 종전으로 — 라벨-단독도 도움


# ══════════════════════════════════════════════════════════════════════════
# ④ 다음 추천 — 라벨-단독 흐름은 EOS-39 도움 접기로 가지 않는다
# ══════════════════════════════════════════════════════════════════════════
def test_a_label_only_flow_reaches_the_next_recommendation_without_the_help_fold() -> None:
    body = _wrong_then(["x의 값을 다시 구해볼게요"])
    _case("rec", body)
    rec, meta = body.result["rec"], body.result["meta"]  # type: ignore[attr-defined]
    assert meta is not None
    assert META_KEY_SELECTION_HELP_COUNT not in meta, meta  # 접힌 문항이 없다
    assert meta[META_KEY_POLICY_VERSION] == "cat_v5", meta
    # 오답+정답이 접히지 않고 한 쌍(반반)으로 남아 선택 θ가 추정 θ와 같다 — 표적이 내려가지 않는다.
    assert rec["selection_theta"] == pytest.approx(rec["theta"], abs=1e-9), rec


def test_the_same_flow_with_the_kill_switch_off_is_folded_by_eos39(
    label_free_disabled: None,
) -> None:
    """대조군 — 스위치를 끄면 같은 흐름이 도움 완료로 접혀 표적이 내려간다(EOS-39 입력이 달라진다)."""
    body = _wrong_then(["x의 값을 다시 구해볼게요"])
    _case("recoff", body)
    rec, meta = body.result["rec"], body.result["meta"]  # type: ignore[attr-defined]
    assert meta is not None
    assert meta[META_KEY_SELECTION_HELP_COUNT] == 1, meta
    assert rec["selection_theta"] < rec["theta"], rec


# ══════════════════════════════════════════════════════════════════════════
# ⑥ 교차 이월 — 이전 오답의 '초보'가 새 세션의 **시작 행**을 단계 2로 올려도 독립 성공이다
# ══════════════════════════════════════════════════════════════════════════
def _carried_label_independent_success() -> Any:
    """같은 개념의 다른 문항에서 오답 한 건(코치 없이 직접 제출) → 코치 세션 → 곧바로 정답 → 돌아보기."""
    result: dict[str, Any] = {}

    def body(
        client: Any, auth: dict[str, str], uid: uuid.UUID, pid: uuid.UUID, bank: Any, j: Any
    ) -> None:
        _P._attempt(client, auth, bank[0], correct=False, answer="오답")  # BKT가 낮아져 '초보'
        did = _H._open(client, auth, pid, _H._NEUTRAL)
        _H._submit_correct(client, auth, did, "이렇게 풀었어요")
        attempt_id = str(_H._reflect(client, auth, did))
        used, _rows = _H._attribution(uid, attempt_id)
        result["used"] = used
        result["ledger"] = _ledger(uid, pid)
        j.record("EOS-178", "교차 이월", used_hint=used, 원장=result["ledger"])

    body.result = result  # type: ignore[attr-defined]
    return body


def test_a_carried_label_does_not_make_an_independent_success_a_help_completion() -> None:
    """시작 행(`turn_count=0`)이 이전 이력의 라벨만으로 단계 2다 — 학생은 아무 말도 하지 않았다.

    종전(EOS-133)에는 학생이 곧바로 정답을 내도 그 시작 행이 귀속 창에 들어 `used_hint=True`였다
    (판정문 T4 — 교차 이월). 이제 시작 행의 라벨 없는 단계는 1이라 독립 성공이다. 이 시나리오는 **세션
    생성 핸들러**가 라벨('초보')을 원장에 적는지도 처음 밟는다 — 오답 전에는 라벨이 없다.
    """
    body = _carried_label_independent_success()
    _case("carry", body)
    used, ledger = body.result["used"], body.result["ledger"]  # type: ignore[attr-defined]
    assert ledger == [(2, 1, "초보")], ledger  # 최종 2 · 라벨 없는 단계 1 · 적용된 라벨 '초보'
    assert used is False, (used, ledger)


def test_the_same_carry_over_with_the_kill_switch_off_is_a_help_completion(
    label_free_disabled: None,
) -> None:
    """대조군 — 스위치를 끄면 같은 장면이 종전처럼 도움 완료다(분리가 실제로 일하는 것의 반대 방향)."""
    body = _carried_label_independent_success()
    _case("carryoff", body)
    used, ledger = body.result["used"], body.result["ledger"]  # type: ignore[attr-defined]
    assert ledger == [(2, 1, "초보")], ledger
    assert used is True, (used, ledger)


# ══════════════════════════════════════════════════════════════════════════
# ⑤ 리포트 §7 — 실 JSONB·bool_or SQL을 합성 원장 4쌍의 증분으로 센다
# ══════════════════════════════════════════════════════════════════════════
def _ledger_row(uid: uuid.UUID, pid: uuid.UUID, at: datetime, **data: Any) -> AttemptEvent:
    return AttemptEvent(
        event_at=at,
        user_id=uid,
        problem_id=pid,
        event_type=EventType.힌트제공,
        event_data=dict(data),
    )


async def _counts() -> reach_report.ReachCounts:
    engine = create_async_engine(_P._settings().database_url)
    try:
        async with async_sessionmaker(engine, class_=AsyncSession)() as session:
            return await reach_report.fetch_reach_counts(session)
    finally:
        await engine.dispose()


async def _insert(rows: list[AttemptEvent]) -> None:
    engine = create_async_engine(_P._settings().database_url)
    try:
        async with async_sessionmaker(engine, class_=AsyncSession)() as session:
            session.add_all(rows)
            await session.commit()
    finally:
        await engine.dispose()


async def _purge(user_ids: list[uuid.UUID]) -> None:
    engine = create_async_engine(_P._settings().database_url)
    try:
        async with async_sessionmaker(engine, class_=AsyncSession)() as session:
            await session.execute(delete(AttemptEvent).where(AttemptEvent.user_id.in_(user_ids)))
            await session.commit()
    finally:
        await engine.dispose()


def test_the_report_section7_counts_in_real_jsonb_and_bool_or() -> None:
    """일곱 쌍(학생·문항)을 심고 §7 카운트의 **증분**을 리터럴로 고정한다.

    A  — 라벨-단독 행만(신호 없음): 라벨이 학생 행동으로 확인되지 않은 쌍. 3행 중 1행만 검수 힌트가
         실렸고(`hint_id`), 1행은 `hint_id=""`(빈 문자열은 실린 것이 아니다)
    A2 — A와 **같은 학생의 다른 문항**에서 신호 행: 문항별로 갈라 센다는 증거(학생 단위로 합치면 A가
         '확인된 쌍'이 된다)
    B  — 라벨-단독 행 + 신호 행: 확인된 쌍
    C  — 신호 행 + 방향(단계 1) 행: 라벨-단독 쌍이 아니다
    D  — 구판 행(base 없음)뿐: 분류 불가 — 라벨-단독 쌍에 들어가면 안 된다(NULL이 거짓으로 접히는지)
    E  — **다른 event_type**(`검산결과`)이 같은 키를 달고 있다: 공급 원장이 아니므로 어느 축에도 안 든다
    F  — A와 같은 모양의 두 번째 신호 없는 쌍: 신호 없는 쌍(2)이 확인된 쌍(1)보다 많게 해 두 집합을
         뒤바꿔 세는 결함이 같은 숫자로 가려지지 않게 한다
    """
    users = [uuid.uuid4() for _ in range(6)]
    pa, pa2, pb, pc, pd, pe, pf = (uuid.uuid4() for _ in range(7))
    t0 = datetime(2026, 10, 6, 9, 0, 0, tzinfo=timezone.utc)

    def at(n: int) -> datetime:
        return t0 + timedelta(seconds=n)

    rows = [
        _ledger_row(users[0], pa, at(1), hint_level=2, base_level=1, ability_level="초보"),
        _ledger_row(users[0], pa, at(2), hint_level=2, base_level=1, hint_id="h-a"),
        _ledger_row(users[0], pa, at(3), hint_level=2, base_level=1, hint_id=""),
        _ledger_row(users[0], pa2, at(4), hint_level=2, base_level=2),
        _ledger_row(users[1], pb, at(5), hint_level=2, base_level=1, ability_level="초보"),
        _ledger_row(users[1], pb, at(6), hint_level=3, base_level=2, ability_level="초보"),
        _ledger_row(users[2], pc, at(7), hint_level=2, base_level=2),
        _ledger_row(users[2], pc, at(8), hint_level=1, base_level=1),
        _ledger_row(users[3], pd, at(9), hint_level=2),
        _ledger_row(users[3], pd, at(10), hint_level=3),
        _ledger_row(users[5], pf, at(12), hint_level=2, base_level=1, ability_level="초보"),
        AttemptEvent(
            event_at=at(11),
            user_id=users[4],
            problem_id=pe,
            event_type=EventType.검산결과,
            event_data={"hint_level": 2, "base_level": 1, "hint_id": "h-e"},
        ),
    ]
    before = asyncio.run(_counts())
    asyncio.run(_insert(rows))
    try:
        after = asyncio.run(_counts())
    finally:
        asyncio.run(_purge(users))
    restored = asyncio.run(_counts())

    def delta(name: str) -> int:
        return int(getattr(after, name) - getattr(before, name))

    assert (
        delta("coach_supply_help_row_total") == 10
    ), after  # 단계 2+ 힌트제공 — A3·A2 1·B2·C1·D2·F1
    assert delta("coach_supply_classified_row_total") == 8, after  # base 있는 행(D 2행 제외)
    assert delta("coach_supply_label_only_row_total") == 5, after  # A 3 + B 1 + F 1
    assert delta("coach_supply_label_only_served_row_total") == 1, after  # A의 hint_id="h-a" 행뿐
    assert delta("coach_label_only_pair_total") == 3, after  # A·B·F (A2·C는 신호뿐·D는 분류 불가)
    assert delta("coach_label_only_unsignaled_pair_total") == 2, after  # A·F(B는 신호 있음)
    # 되돌림 — 합성 행을 지우면 증분이 0이다(양방향 변별: 센 것이 우리가 심은 행임을 확인).
    assert restored == before, (before, restored)
