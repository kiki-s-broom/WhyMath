"""코치 힌트 귀속의 라벨-단독 공급 분리 — EOS-178 (DB 무접근 단위).

`api/coach._attribute_hints`는 귀속 창 안의 공급 원장(`힌트제공`) 행에서 '힌트 사용'으로 셀 행을
고른다. EOS-178 이전에는 최종 단계가 2 이상이면 전부 셌다 — 숙달 라벨 '초보'가 학생 신호 없이 1→2로
올린 공급까지. 이제 행의 `base_level`(라벨 없이 계산한 단계)이 2 미만이고 검수 힌트도 실리지 않았으면
세지 않는다. 이 파일은 그 분기를 행 단위로 고정한다:

  - 신판 행(base 있음)과 구판 행(base 없음)이 섞였을 때 각자의 규칙으로 센다.
  - 킬 스위치를 끄면 구판 규칙(EOS-133)으로 완전히 돌아간다.
  - `base_level`·`hint_id` 판독은 깨진 값에 관대하지 않다(모르면 종전 규칙).

실 PG 위의 전 경로(HTTP 코치 대화 → 원장 적재 → 귀속 → 다음 추천)는
`test_eos178_label_free_attribution_integration.py`가 본다.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

import whymath_backend.api.coach as coach_module
from whymath_backend.config import get_settings

_T0 = datetime(2026, 10, 6, 9, 0, 0, tzinfo=timezone.utc)
_UID = uuid.UUID("00000000-0000-0000-0000-00000000e178")
_PID = uuid.UUID("00000000-0000-0000-0000-0000000a0178")
_WINDOW = (_T0, _T0 + timedelta(minutes=5))


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _Session:
    """`execute` 결과를 준비된 행으로 낸다(문장은 무시 — 행 단위 규칙만 본다)."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    async def execute(self, _stmt: Any) -> _Result:
        return _Result(self._rows)


def _row(i: int, **payload: Any) -> tuple[datetime, dict[str, Any]]:
    return (_T0 + timedelta(seconds=10 * (i + 1)), dict(payload))


def _attribute(rows: list[Any]) -> Any:
    return asyncio.run(
        coach_module._attribute_hints(
            _Session(rows),  # type: ignore[arg-type]
            user_id=_UID,
            problem_id=_PID,
            window=_WINDOW,
        )
    )


@pytest.fixture
def label_free_disabled(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """킬 스위치를 끈다 — 환경변수를 **먼저** 지운 뒤 캐시를 비워 다른 테스트로 새지 않게 한다."""
    monkeypatch.setenv("WHYMATH_L4_HINT_ATTRIBUTION_LABEL_FREE_ENABLED", "false")
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("WHYMATH_L4_HINT_ATTRIBUTION_LABEL_FREE_ENABLED", raising=False)
    get_settings.cache_clear()


class TestBaseAndServedReaders:
    @pytest.mark.parametrize("base", [1, 2, 3, 4])
    def test_reads_the_closed_range(self, base: int) -> None:
        assert coach_module._supplied_base_level({"base_level": base}) == base

    @pytest.mark.parametrize(
        "payload",
        [
            {"base_level": 0},
            {"base_level": 5},
            {"base_level": "2"},
            {"base_level": 2.0},
            {"base_level": None},
            {"base_level": True},  # bool은 int의 하위형 — 단계 1로 읽히면 안 된다
            {},
            None,
            "base_level=2",
            [2],
        ],
    )
    def test_unreadable_is_none(self, payload: object) -> None:
        assert coach_module._supplied_base_level(payload) is None

    @pytest.mark.parametrize(
        ("payload", "expected"),
        [
            ({"hint_id": "hint-sp-x-s2-l2"}, True),
            ({"hint_id": ""}, False),
            ({"hint_id": None}, False),
            ({"hint_id": 7}, False),
            ({}, False),
            (None, False),
        ],
    )
    def test_served_marker(self, payload: object, expected: bool) -> None:
        assert coach_module._served_hint_marked(payload) is expected


class TestAttributionByRow:
    def test_label_only_supply_is_not_help(self) -> None:
        """'초보'가 신호 없이 올린 2 — 학생은 아무것도 요청하지 않았고 검수 힌트도 안 나갔다."""
        result = _attribute([_row(0, hint_level=2, base_level=1)])
        assert result.used_hint is False and result.hints == ()

    def test_signal_supply_is_help(self) -> None:
        """좌절 발화가 올린 2(base 2) — 학생이 막힘을 말했다."""
        rows = [_row(0, hint_level=2, base_level=2)]
        result = _attribute(rows)
        assert result.used_hint is True and result.hints == ((rows[0][0], 2),)

    def test_signal_plus_label_supply_is_help(self) -> None:
        """신호(base 2)에 '초보' 한 칸이 얹힌 3 — 신호가 있으므로 도움이다."""
        rows = [_row(0, hint_level=3, base_level=2)]
        assert _attribute(rows).hints == ((rows[0][0], 3),)

    def test_label_only_supply_with_a_served_hint_is_help(self) -> None:
        """라벨이 올렸어도 검수 힌트가 응답에 실렸으면 내용이 나간 도움이다."""
        rows = [_row(0, hint_level=2, base_level=1, hint_id="hint-x-s2")]
        result = _attribute(rows)
        assert result.used_hint is True and result.hints == ((rows[0][0], 2),)

    def test_legacy_row_without_base_keeps_the_old_rule(self) -> None:
        """구판 행(base 없음) — 라벨의 영향을 가를 수 없어 종전대로 센다."""
        rows = [_row(0, hint_level=2)]
        assert _attribute(rows).hints == ((rows[0][0], 2),)

    def test_relaxed_signal_turn_is_not_counted(self) -> None:
        """'숙달'이 신호 턴(base 2)을 1로 내렸다 — 공급한 것은 방향뿐이라 세지 않는다."""
        assert _attribute([_row(0, hint_level=1, base_level=2)]).used_hint is False

    def test_mixed_rows_count_each_by_its_own_rule(self) -> None:
        rows = [
            _row(0, hint_level=2, base_level=1),  # 라벨-단독 — 아니오
            _row(1, hint_level=2),  # 구판 — 예
            _row(2, hint_level=2, base_level=1, hint_id="h"),  # 라벨-단독 + 서빙 — 예
            _row(3, hint_level=3, base_level=2),  # 신호 — 예
            _row(4, hint_level=1, base_level=1),  # 방향 — 아니오
        ]
        result = _attribute(rows)
        assert [lv for _, lv in result.hints] == [2, 2, 3]
        assert [at for at, _ in result.hints] == [rows[1][0], rows[2][0], rows[3][0]]

    def test_unreadable_base_falls_back_to_the_old_rule(self) -> None:
        """깨진 base는 '라벨 때문이 아니다'로도 '라벨 때문이다'로도 확정하지 않는다 — 종전대로."""
        rows = [_row(0, hint_level=2, base_level="1")]
        assert _attribute(rows).used_hint is True

    def test_only_label_only_rows_make_a_false_not_unknown(self) -> None:
        """판독 불가 행이 없으므로 미상(None)이 아니라 확정 거짓이다."""
        result = _attribute(
            [_row(0, hint_level=2, base_level=1), _row(1, hint_level=2, base_level=1)]
        )
        assert result.used_hint is False


class TestKillSwitch:
    def test_default_is_on(self) -> None:
        assert get_settings().l4_hint_attribution_label_free_enabled is True

    def test_off_restores_the_eos133_rule(self, label_free_disabled: None) -> None:
        """끄면 라벨-단독 공급도 도움이다 — base가 있어도 읽지 않는다."""
        assert get_settings().l4_hint_attribution_label_free_enabled is False
        rows = [_row(0, hint_level=2, base_level=1)]
        result = _attribute(rows)
        assert result.used_hint is True and result.hints == ((rows[0][0], 2),)

    def test_off_keeps_directional_supply_uncounted(self, label_free_disabled: None) -> None:
        """끈 상태에서도 1(방향)은 세지 않는다 — 스위치가 되돌리는 것은 라벨 분리뿐이다."""
        assert _attribute([_row(0, hint_level=1, base_level=1)]).used_hint is False


class _CaptureSession:
    """`session.add`로 들어온 ORM 행을 모은다(commit은 호출 핸들러 몫이라 여기엔 없다)."""

    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)


class TestLogHintEventCarriesTheMeasurementFields:
    def _log(self, **kwargs: Any) -> dict[str, Any]:
        session = _CaptureSession()
        asyncio.run(
            coach_module._log_hint_event(
                session,  # type: ignore[arg-type]
                user_id=_UID,
                problem_id=_PID,
                attempt_id=None,
                hint_level=2,
                **kwargs,
            )
        )
        assert len(session.added) == 1
        return dict(session.added[0].event_data)

    def test_base_and_label_are_written_to_the_ledger_row(self) -> None:
        data = self._log(base_hint_level=1, ability_level="초보")
        assert data["hint_level"] == 2
        assert data["base_level"] == 1
        assert data["ability_level"] == "초보"

    def test_omitted_fields_read_as_a_legacy_row(self) -> None:
        """호출부가 넘기지 않으면 구판 행과 같다 — 귀속은 종전 규칙으로 센다."""
        data = self._log()
        assert data["base_level"] is None and data["ability_level"] is None
        assert _attribute_payload(data) is True


def _attribute_payload(data: dict[str, Any]) -> bool:
    """원장 payload 하나를 귀속에 통과시킨 결과 — 적재와 귀속이 같은 표현을 쓰는지 잇는다."""
    return bool(_attribute([_row(0, **data)]).used_hint)
