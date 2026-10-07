"""EOS-179 — 코치 라벨의 출처·증거 수 적재와 예측 타당도 리더를 **실 PG·실 JSONB**에서 본다.

가짜 세션은 쿼리를 무시한다. 리더가 쓰는 창 함수(`row_number() over (partition by …)`)·`bool_or`·
`bool_and`·JSONB 키 캐스팅의 의미는 실 DB에서만 변별된다(기본 SKIP — `WHYMATH_RUN_INTEGRATION=1`).

① **적재** — 공개 HTTP 표면(`/v1/coach/sessions`·`…/turns`)을 불러 원장(`힌트제공`) JSONB에 라벨의 출처
   (`label_source`)와 증거 수(`label_evidence_n`)가 실제로 적히는지 본다. 증거 수는 서버가 읽은 개념 숙달도
   행(`concept_mastery_history.sample_size`)과 **같은 값**이어야 한다(다른 행을 읽으면 어긋난다).
② **리더** — 합성 원장 행을 심어 첫-행 창·신호 판정·제외 분류·증거 수 하한을 **증분**으로 고정하고, 라벨-단독
   행을 신호 행으로 바꾸는 주입이 정확히 한 쌍의 결과를 뒤집는지 본다(변별력). 되돌림이 증분을 0으로
   되돌리는지로 센 것이 우리가 심은 행임을 확인한다.

헬퍼는 EOS-178 통합 테스트(→ EOS-133 통합 하네스)를 경로 로딩으로 빌려 쓴다.
"""

from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import sys
import uuid
from datetime import datetime, timedelta, timezone
from types import ModuleType
from typing import Any

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from whymath_backend.db.models.activity import AttemptEvent
from whymath_backend.ops import recommendation_reach_report as reach_report
from whymath_backend.schema.enums import EventType

pytestmark = pytest.mark.integration

_E178_PATH = pathlib.Path(__file__).with_name("test_eos178_label_free_attribution_integration.py")
#: 빌려 쓰는 헬퍼 계약 — 하나라도 사라지면 수집 단계에서 이름을 지목하며 깨진다.
_HELPERS = (
    "_S",
    "_P",
    "_H",
    "_case",
    "_wrong_then",
    "_carried_label_independent_success",
    "_ledger_row",
    "_insert",
    "_purge",
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_eos179_e178_harness", _E178_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"EOS-178 통합 테스트 스펙 생성 실패: {_E178_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    missing = [name for name in _HELPERS if not hasattr(module, name)]
    if missing:
        raise RuntimeError(f"EOS-178 통합 테스트의 헬퍼가 사라졌다: {missing}")
    return module


_E = _load()
_S = _E._S
_P = _E._P


def _ledger_json(uid: uuid.UUID, pid: uuid.UUID) -> list[dict[str, Any]]:
    """이 학생·문항 공급 원장의 계측 키 — 시각순(JSONB 그대로 읽는다)."""
    rows = _S._read_rows(
        "SELECT (event_data->>'hint_level')::int, event_data->>'ability_level',"
        " event_data->>'label_source', (event_data->>'label_evidence_n')::int, event_at"
        " FROM attempt_event"
        " WHERE user_id = :uid AND problem_id = :pid AND event_type = '힌트제공'"
        " ORDER BY event_at",
        {"uid": str(uid), "pid": str(pid)},
    )
    return [
        {
            "hint_level": int(r[0]),
            "ability_level": r[1],
            "label_source": r[2],
            "label_evidence_n": r[3],
            "event_at": r[4],
        }
        for r in rows
    ]


def _mastery_history(uid: uuid.UUID) -> list[tuple[datetime, int | None]]:
    """이 학생의 개념 숙달 이력 (measured_at, sample_size) — 시각 오름차순."""
    rows = _S._read_rows(
        "SELECT measured_at, sample_size FROM concept_mastery_history WHERE user_id = :uid"
        " ORDER BY measured_at",
        {"uid": str(uid)},
    )
    return [(r[0], None if r[1] is None else int(r[1])) for r in rows]


def _size_in_effect(history: list[tuple[datetime, int | None]], at: datetime) -> int | None:
    """원장 행이 적히는 순간 서버가 읽었을 최신 측정의 sample_size(그 이후의 측정은 보지 못한다)."""
    prior = [size for measured_at, size in history if measured_at <= at]
    return prior[-1] if prior else None


# ══════════════════════════════════════════════════════════════════════════
# ① 적재 — HTTP 코치 대화가 남긴 원장 행
# ══════════════════════════════════════════════════════════════════════════
def test_a_carried_label_is_recorded_with_its_server_source_and_observation_count() -> None:
    """같은 개념의 오답 한 건 뒤 코치 세션을 연다 — **세션 생성 핸들러**의 시작 행이 라벨을 이월한다."""
    seen: dict[str, Any] = {}
    inner = _E._carried_label_independent_success()

    def body(
        client: Any, auth: dict[str, str], uid: uuid.UUID, pid: uuid.UUID, bank: Any, j: Any
    ) -> None:
        inner(client, auth, uid, pid, bank, j)
        seen["ledger"] = _ledger_json(uid, pid)
        seen["history"] = _mastery_history(uid)

    _E._case("c179", body)
    ledger, history = seen["ledger"], seen["history"]
    assert len(ledger) == 1, ledger
    row = ledger[0]
    assert row["ability_level"] == "초보", row
    assert row["label_source"] == "server_bkt", row  # 서버 L2의 개념 숙달도가 만든 라벨이다
    # 증거 수 = 그 라벨을 만들 때 서버가 읽은 최신 측정의 sample_size. 흐름이 끝난 뒤의 이력(정답 제출이
    # 한 번 더 쌓은 측정)이 아니라 *그 순간의* 값이어야 한다 — 이력 끝값으로 비교하면 어긋난다.
    expected = _size_in_effect(history, row["event_at"])
    assert expected is not None and expected >= 1, (history, row)
    assert row["label_evidence_n"] == expected, (row, history)
    assert history[-1][1] != expected, history  # 이후 측정이 있었다 — 시점이 실제로 변별된다


def test_a_turn_before_any_measurement_records_no_label_and_no_evidence() -> None:
    """오답 전에는 숙달 측정이 없다 — 라벨 없음이고 출처·증거 수도 적히지 않는다(날조 금지)."""
    seen: dict[str, Any] = {}
    inner = _E._wrong_then(["x의 값을 다시 구해볼게요"])

    def body(
        client: Any, auth: dict[str, str], uid: uuid.UUID, pid: uuid.UUID, bank: Any, j: Any
    ) -> None:
        inner(client, auth, uid, pid, bank, j)
        seen["ledger"] = _ledger_json(uid, pid)
        seen["history"] = _mastery_history(uid)

    _E._case("w179", body)
    ledger, history = seen["ledger"], seen["history"]
    assert [r["hint_level"] for r in ledger] == [1, 2], ledger
    first, second = ledger
    assert first["ability_level"] is None and first["label_source"] is None, first
    assert first["label_evidence_n"] is None, first
    # 두 번째 행(**append 핸들러**): 오답이 숙달도를 만들어 '초보'가 서버 출처로 적힌다.
    assert second["ability_level"] == "초보" and second["label_source"] == "server_bkt", second
    expected = _size_in_effect(history, second["event_at"])
    assert expected is not None and second["label_evidence_n"] == expected, (second, history)


def test_the_reader_sees_the_http_flow_as_a_labeled_server_pair_without_signal() -> None:
    """HTTP로 쌓은 원장이 §8 리더에 그대로 읽힌다 — 적재와 읽기가 같은 키를 쓰는지 잇는다."""
    seen: dict[str, Any] = {}
    inner = _E._carried_label_independent_success()

    def body(
        client: Any, auth: dict[str, str], uid: uuid.UUID, pid: uuid.UUID, bank: Any, j: Any
    ) -> None:
        seen["before"] = asyncio.run(_read())
        inner(client, auth, uid, pid, bank, j)
        seen["after"] = asyncio.run(_read())

    _E._case("r179", body)
    delta = _cell_delta(seen["before"], seen["after"])
    # 시작 행 하나: 첫 라벨 '초보'(서버 숙달도)·신호 없음(base_level=1) → 쌍 1·신호 쌍 0.
    assert delta == {("초보", "server_bkt"): (1, 0)}, delta


# ══════════════════════════════════════════════════════════════════════════
# ② 리더 — 실 JSONB·창 함수 위의 합성 원장 증분
# ══════════════════════════════════════════════════════════════════════════
async def _read(**kwargs: Any) -> Any:
    engine = create_async_engine(_P._settings().database_url)
    try:
        async with async_sessionmaker(engine, class_=AsyncSession)() as session:
            return await reach_report.fetch_label_validity(session, **kwargs)
    finally:
        await engine.dispose()


def _cells(read: Any) -> dict[tuple[str, str | None], tuple[int, int]]:
    """리더 칸 → {(라벨, 출처): (쌍 수, 신호 쌍 수)}."""
    return {(label, source): (pairs, signals) for label, source, pairs, signals in read.cells}


def _cell_delta(before: Any, after: Any) -> dict[tuple[str, str | None], tuple[int, int]]:
    """칸별 (쌍 수, 신호 쌍 수) 증분 — 기존 DB 내용과 무관하게 심은 행만 센다(0 증분은 생략)."""
    b, a = _cells(before), _cells(after)
    delta = {
        key: (
            a.get(key, (0, 0))[0] - b.get(key, (0, 0))[0],
            a.get(key, (0, 0))[1] - b.get(key, (0, 0))[1],
        )
        for key in set(a) | set(b)
    }
    return {key: d for key, d in delta.items() if d != (0, 0)}


async def _mutate(user_id: uuid.UUID, problem_id: uuid.UUID, at: datetime, **data: Any) -> None:
    """심은 원장 행 하나의 event_data를 통째로 바꾼다(주입 — 라벨-단독 행을 신호 행으로)."""
    engine = create_async_engine(_P._settings().database_url)
    try:
        async with async_sessionmaker(engine, class_=AsyncSession)() as session:
            await session.execute(
                update(AttemptEvent)
                .where(
                    AttemptEvent.user_id == user_id,
                    AttemptEvent.problem_id == problem_id,
                    AttemptEvent.event_at == at,
                )
                .values(event_data=dict(data))
            )
            await session.commit()
    finally:
        await engine.dispose()


def _synthetic_ledger() -> tuple[list[AttemptEvent], list[uuid.UUID], dict[str, Any]]:
    """열한 쌍 — 각 쌍이 리더의 한 분기를 밟는다. 반환: (행, 학생들, 주입 대상 좌표).

    칸은 (라벨, 출처) 단위로 묶여 (쌍 수, 신호 쌍 수)를 낸다.

    P1  초보·server_bkt(n=3) 라벨-단독 두 행 — 신호 없음                  → (초보,bkt) +(1,0)
    P2  같은 모양인데 둘째 행이 신호(base=2)                              → (초보,bkt) +(1,1)
    P3  숙달·server_bkt(n=40) 신호 없음                                   → (숙달,bkt) +(1,0)
    P4  **첫 행에 라벨 없음**, 둘째 행이 '초보' — 둘째 행으로 건너뛰면 안 된다 → 라벨 없음 +1
    P5  첫 행이 신호 행(base=2)인 client_bkt '초보'                       → (초보,client) +(1,1)
    P6  라벨은 있는데 둘째 행이 구판(base 없음) — 신호 없음을 확신 못 한다   → 분류 불가 +1
    P7  출처가 안 적힌(EOS-178 시기) '초보'                               → (초보,None) +(1,0)
    P8  **시각이 늦은 행(숙달)이 목록상 먼저** — 시각상 첫 행은 신호 있는 '초보' → (초보,bkt) +(1,1)
    P9  다른 event_type(`검산결과`)이 같은 키를 달고 있다 — 공급 원장이 아니다 → 어디에도 안 든다
    P10 ability_level이 빈 문자열 — 라벨 없음과 같다                      → 라벨 없음 +1
    P11 ability_level이 JSON null — 라벨 없음                             → 라벨 없음 +1
    """
    users = [uuid.uuid4() for _ in range(11)]
    pids = [uuid.uuid4() for _ in range(11)]
    t0 = datetime(2026, 10, 7, 9, 0, 0, tzinfo=timezone.utc)

    def at(n: int) -> datetime:
        return t0 + timedelta(seconds=n)

    def row(i: int, n: int, **data: Any) -> AttemptEvent:
        return _E._ledger_row(users[i - 1], pids[i - 1], at(n), **data)

    rows = [
        row(
            1,
            1,
            hint_level=2,
            base_level=1,
            ability_level="초보",
            label_source="server_bkt",
            label_evidence_n=3,
        ),
        row(
            1,
            2,
            hint_level=2,
            base_level=1,
            ability_level="초보",
            label_source="server_bkt",
            label_evidence_n=3,
        ),
        row(
            2,
            3,
            hint_level=2,
            base_level=1,
            ability_level="초보",
            label_source="server_bkt",
            label_evidence_n=3,
        ),
        row(
            2,
            4,
            hint_level=3,
            base_level=2,
            ability_level="초보",
            label_source="server_bkt",
            label_evidence_n=3,
        ),
        row(
            3,
            5,
            hint_level=1,
            base_level=1,
            ability_level="숙달",
            label_source="server_bkt",
            label_evidence_n=40,
        ),
        row(4, 6, hint_level=1, base_level=1),
        row(
            4,
            7,
            hint_level=3,
            base_level=2,
            ability_level="초보",
            label_source="server_bkt",
            label_evidence_n=3,
        ),
        row(5, 8, hint_level=3, base_level=2, ability_level="초보", label_source="client_bkt"),
        row(
            6,
            9,
            hint_level=2,
            base_level=1,
            ability_level="초보",
            label_source="server_bkt",
            label_evidence_n=2,
        ),
        row(6, 10, hint_level=2),
        row(7, 11, hint_level=2, base_level=1, ability_level="초보"),
        # P8 — 시각이 늦은 행(숙달·신호 없음)을 목록 **앞**에 둔다: 정렬 없이 '첫 행'을 고르면 틀린다.
        row(
            8,
            21,
            hint_level=1,
            base_level=1,
            ability_level="숙달",
            label_source="server_bkt",
            label_evidence_n=40,
        ),
        row(
            8,
            12,
            hint_level=3,
            base_level=2,
            ability_level="초보",
            label_source="server_bkt",
            label_evidence_n=5,
        ),
        AttemptEvent(
            event_at=at(13),
            user_id=users[8],
            problem_id=pids[8],
            event_type=EventType.검산결과,
            event_data={"hint_level": 2, "base_level": 2, "ability_level": "초보"},
        ),
        row(10, 14, hint_level=2, base_level=1, ability_level=""),
        row(11, 15, hint_level=2, base_level=1, ability_level=None),
    ]
    inject = {"user": users[0], "pid": pids[0], "at": at(2)}
    return rows, users, inject


def _noise_ledger() -> tuple[list[AttemptEvent], list[uuid.UUID]]:
    """다른 테스트가 공유 DB에 남긴 잔여 행을 흉내 내는 쌍 3개 — **baseline이 0이 아닌 상태**를 만든다.

    CI의 통합 잡은 한 DB를 스위트 전체가 공유하므로 이 테스트의 baseline은 0이 아니다(실측: 라벨 없는 쌍
    2개가 이미 있었다). 빈 DB에서만 통과하는 테스트는 baseline을 잘못 잡아도 초록이라 그 결함을 못 본다
    (PR #1503의 첫 CI가 바로 그것이었다 — 하한을 건 읽기를 하한 없는 baseline과 비교). 그래서 잔여 행을
    이 테스트가 직접 심어 어떤 DB에서도 같은 조건을 밟는다.

    N1·N2 라벨 없는 쌍(하한 아래에서는 나오지 않는다) · N3 서버 라벨 n=50 쌍(하한 10을 **통과**한다 —
    하한을 건 baseline에도 들어 있다).
    """
    users = [uuid.uuid4() for _ in range(3)]
    t0 = datetime(2026, 10, 7, 8, 0, 0, tzinfo=timezone.utc)
    rows = [
        _E._ledger_row(users[0], uuid.uuid4(), t0, hint_level=2, base_level=1),
        _E._ledger_row(
            users[1], uuid.uuid4(), t0 + timedelta(seconds=1), hint_level=1, base_level=1
        ),
        _E._ledger_row(
            users[2],
            uuid.uuid4(),
            t0 + timedelta(seconds=2),
            hint_level=1,
            base_level=1,
            ability_level="숙달",
            label_source="server_bkt",
            label_evidence_n=50,
        ),
    ]
    return rows, users


def test_the_validity_reader_in_real_jsonb_and_window_functions() -> None:
    rows, users, inject = _synthetic_ledger()
    noise, noise_users = _noise_ledger()
    clean = asyncio.run(_read())
    asyncio.run(_E._insert(noise))  # baseline을 0이 아니게 만든다 — 아래 모든 증분은 이 위에서 센다
    before = asyncio.run(_read())
    before_floored = asyncio.run(_read(min_evidence_n=10))
    asyncio.run(_E._insert(rows))
    try:
        after = asyncio.run(_read())
        floored = asyncio.run(_read(min_evidence_n=10))
        # ── 주입(변별력): P1의 **라벨-단독 둘째 행을 신호 행으로** 바꾼다 — 정확히 한 쌍의 결과만 뒤집힌다.
        asyncio.run(
            _mutate(
                inject["user"],
                inject["pid"],
                inject["at"],
                hint_level=3,
                base_level=2,
                ability_level="초보",
                label_source="server_bkt",
                label_evidence_n=3,
            )
        )
        injected = asyncio.run(_read())
    finally:
        asyncio.run(_E._purge(users + noise_users))
    restored = asyncio.run(_read())

    # 노이즈가 실제로 baseline을 0이 아니게 만들었다(이 전제가 깨지면 아래 증분 단언은 빈 DB 테스트로 후퇴한다).
    assert before.unlabeled_pair_total - clean.unlabeled_pair_total == 2, before
    assert _cell_delta(clean, before) == {("숙달", "server_bkt"): (1, 0)}, before

    delta = _cell_delta(before, after)
    assert delta == {
        ("초보", "server_bkt"): (
            3,
            2,
        ),  # P1(신호 없음)·P2(신호)·P8(삽입 역순 — 시각 첫 행이 '초보')
        ("숙달", "server_bkt"): (1, 0),  # P3
        ("초보", "client_bkt"): (1, 1),  # P5 — 첫 행 자신이 신호 행
        ("초보", None): (1, 0),  # P7 — 출처 미기록
    }, delta
    assert after.unlabeled_pair_total - before.unlabeled_pair_total == 3, after  # P4·P10·P11
    assert after.unclassified_pair_total - before.unclassified_pair_total == 1, after  # P6

    # 증거 수 하한(10): 첫 행의 label_evidence_n ≥ 10인 쌍만 — 숙달 n=40인 P3뿐이다(P8의 시각 첫 행은
    # n=5라 빠진다 — 늦은 행의 n=40으로 판정하면 틀린다). 모름(NULL)·낮은 n·라벨 없음 쌍은 전부 빠진다.
    # **하한을 건 읽기는 하한을 건 baseline과 비교한다** — 하한 없는 baseline과 비교하면 필터에 걸러진
    # 잔여 행(라벨 없는 쌍)이 음수 증분으로 나타난다.
    assert _cell_delta(before_floored, floored) == {("숙달", "server_bkt"): (1, 0)}, floored
    assert floored.unlabeled_pair_total - before_floored.unlabeled_pair_total == 0, floored
    assert floored.unclassified_pair_total - before_floored.unclassified_pair_total == 0, floored
    assert (
        before_floored.unlabeled_pair_total == 0
    ), before_floored  # 하한은 라벨 없는 잔여 쌍을 걸러 낸다

    # 주입 결과: P1이 신호 없음 → 신호 있음으로 — (초보,bkt)의 신호 쌍이 정확히 +1, 쌍 수는 그대로다.
    flipped = _cell_delta(before, injected)
    assert flipped == {
        ("초보", "server_bkt"): (3, 3),
        ("숙달", "server_bkt"): (1, 0),
        ("초보", "client_bkt"): (1, 1),
        ("초보", None): (1, 0),
    }, flipped
    assert after.unlabeled_pair_total == injected.unlabeled_pair_total  # 다른 분류는 안 건드린다

    # 되돌림 — 합성 행과 노이즈를 지우면 처음 상태다(센 것이 우리가 심은 행임을 확인).
    assert restored.cells == clean.cells
    assert restored.unlabeled_pair_total == clean.unlabeled_pair_total
    assert restored.unclassified_pair_total == clean.unclassified_pair_total


def test_the_full_report_carries_the_validity_axis_end_to_end() -> None:
    """`fetch_reach_counts → build_report → render`가 실 DB 위에서 §8을 끝까지 낸다."""
    rows, users, _ = _synthetic_ledger()

    async def counts() -> Any:
        engine = create_async_engine(_P._settings().database_url)
        try:
            async with async_sessionmaker(engine, class_=AsyncSession)() as session:
                return await reach_report.fetch_reach_counts(session, min_label_evidence_n=None)
        finally:
            await engine.dispose()

    asyncio.run(_E._insert(rows))
    try:
        report = reach_report.build_report(asyncio.run(counts()))
    finally:
        asyncio.run(_E._purge(users))
    view = report.coach_label_validity_server
    assert view.pair_total >= 4  # 심은 서버 출처 쌍(P1·P2·P3·P8) 이상
    text = reach_report.render_report(report)
    assert "## 8. 코치 라벨의 예측 타당도" in text
    assert report.coach_label_source_unknown_pair_total >= 1  # P7
