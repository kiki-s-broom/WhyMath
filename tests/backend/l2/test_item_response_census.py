"""EOS-129 ⑤ — 문항 응답 축적 실측(`l2/item_response_census`) 단위테스트 (hermetic).

이 도구의 출력이 "a를 추정할 수 있는 문항이 몇 건인가"의 근거가 된다. 그래서 세는 방식의 각
절(학생 수로 센다 · 정답·오답이 둘 다 있어야 한다 · 임계 경계 · 구간 경계)마다 **그 절이 없으면
틀리는 입력**을 둔다. 운영 DB에서 돌기 때문에 안전 절(읽기 전용 선언 · 실패를 0건으로 위장하지
않음 · 식별자 비출력)도 각각 검사한다.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.l2 import item_calibration
from whymath_backend.l2 import item_response_census as census


def _rows(item: str, corrects: list[bool], *, students: list[str] | None = None) -> list[Any]:
    """문항 하나의 응답 행 — 학생을 지정하지 않으면 응답마다 다른 학생."""
    who = students if students is not None else [f"s-{item}-{k}" for k in range(len(corrects))]
    return [(student, item, correct) for student, correct in zip(who, corrects, strict=True)]


def _mixed(n: int) -> list[bool]:
    """정답·오답이 섞인 n개(첫 응답 정답·두 번째 오답을 보장)."""
    return [k % 2 == 0 for k in range(n)]


class TestEmptyAndShape:
    def test_empty_input_is_zero_not_missing(self) -> None:
        summary = census.summarize_item_responses([], problems_total=12)
        assert summary["graded_responses"] == 0
        assert summary["items_answered"] == 0
        assert summary["b_calibratable_items"] == 0
        assert summary["a_estimable_items_by_min_students"] == {
            "30": 0,
            "100": 0,
            "200": 0,
            "500": 0,
        }
        assert summary["max_students_per_item"] == 0
        assert summary["median_students_per_item"] is None  # 미상 ≠ 0
        assert summary["problems_total"] == 12

    def test_histograms_always_carry_every_bucket(self) -> None:
        summary = census.summarize_item_responses([], problems_total=None)
        expected = ["1", "2-4", "5-9", "10-29", "30-99", "100-199", "200-499", "500+"]
        assert list(summary["per_item_responses_histogram"]) == expected  # type: ignore[call-overload]
        assert list(summary["per_item_students_histogram"]) == expected  # type: ignore[call-overload]


class TestCountingRules:
    def test_students_not_responses_decide_a_candidacy(self) -> None:
        # 같은 학생 1명이 40번 풀었다 — 응답은 40이지만 a 추정 재료는 학생 1명뿐이다.
        rows = _rows("I1", _mixed(40), students=["s-1"] * 40)
        summary = census.summarize_item_responses(rows, problems_total=None)
        assert summary["a_estimable_items_by_min_students"]["30"] == 0  # type: ignore[index]
        assert summary["per_item_responses_histogram"]["30-99"] == 1  # type: ignore[index]
        assert summary["per_item_students_histogram"]["1"] == 1  # type: ignore[index]

    def test_items_with_a_single_outcome_are_not_a_candidates(self) -> None:
        # 학생 40명이 전부 맞혔다 — 어떤 모수도 유한하게 추정되지 않는다.
        rows = _rows("I1", [True] * 40)
        summary = census.summarize_item_responses(rows, problems_total=None)
        assert summary["items_with_both_outcomes"] == 0
        assert summary["a_estimable_items_by_min_students"]["30"] == 0  # type: ignore[index]

    def test_threshold_is_inclusive_at_exactly_thirty_students(self) -> None:
        at = census.summarize_item_responses(_rows("I1", _mixed(30)), problems_total=None)
        below = census.summarize_item_responses(_rows("I1", _mixed(29)), problems_total=None)
        assert at["a_estimable_items_by_min_students"]["30"] == 1  # type: ignore[index]
        assert below["a_estimable_items_by_min_students"]["30"] == 0  # type: ignore[index]

    def test_each_threshold_counts_separately(self) -> None:
        rows = _rows("A", _mixed(120)) + _rows("B", _mixed(35)) + _rows("C", _mixed(3))
        counts = census.summarize_item_responses(rows, problems_total=None)[
            "a_estimable_items_by_min_students"
        ]
        assert counts == {"30": 2, "100": 1, "200": 0, "500": 0}

    def test_b_calibratable_matches_the_calibrator_rule(self) -> None:
        # b 보정기와 같은 기준 — 응답 수 ≥ 임계(결과 다양성은 보지 않는다).
        floor = item_calibration._MIN_RESPONSES_FOR_CALIBRATION
        rows = _rows("AT", [True] * floor) + _rows("BELOW", [True] * (floor - 1))
        summary = census.summarize_item_responses(rows, problems_total=None)
        assert summary["b_min_responses"] == floor
        assert summary["b_calibratable_items"] == 1

    def test_histogram_bucket_edges(self) -> None:
        rows = (
            _rows("n1", _mixed(1))
            + _rows("n4", _mixed(4))
            + _rows("n5", _mixed(5))
            + _rows("n9", _mixed(9))
            + _rows("n10", _mixed(10))
        )
        histogram = census.summarize_item_responses(rows, problems_total=None)[
            "per_item_responses_histogram"
        ]
        assert histogram["1"] == 1  # type: ignore[index]
        assert histogram["2-4"] == 1  # type: ignore[index]
        assert histogram["5-9"] == 2  # type: ignore[index]
        assert histogram["10-29"] == 1  # type: ignore[index]

    def test_totals_and_median(self) -> None:
        rows = _rows("A", _mixed(3)) + _rows("B", _mixed(5)) + _rows("C", _mixed(10))
        summary = census.summarize_item_responses(rows, problems_total=40)
        assert summary["graded_responses"] == 18
        assert summary["distinct_students"] == 18
        assert summary["items_answered"] == 3
        assert summary["max_students_per_item"] == 10
        assert summary["median_students_per_item"] == 5.0

    def test_output_carries_no_identifiers(self) -> None:
        student, item = str(uuid.uuid4()), str(uuid.uuid4())
        summary = census.summarize_item_responses(
            [(student, item, True), (student, item, False)], problems_total=1
        )
        dumped = json.dumps(summary)
        assert student not in dumped and item not in dumped


class TestPopulationIsShared:
    """두 소비자가 **같은 로더를 실제로 탄다** — 조회문 동일성이 아니라 실행 경로로 확인한다.

    실측이 보정기와 다른 것을 세면(따로 조건을 적으면) 그 결과는 보정기가 먹는 데이터의 증거가
    아니다. 그리고 실측이 DB를 직접 잡으면 데이터 접근 지점이 하나 늘어난다(ARCH-48 처분 (b)).
    둘 다 "공용 로더를 거친다" 하나로 막힌다.
    """

    @pytest.mark.asyncio
    async def test_census_reads_through_the_calibrator_loader_read_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[bool] = []

        async def _loader(_session: Any, *, read_only: bool = False) -> list[Any]:
            calls.append(read_only)
            return _rows("A", _mixed(7))

        async def _count(_session: Any) -> int:
            return 11

        monkeypatch.setattr(item_calibration, "load_graded_responses", _loader)
        monkeypatch.setattr(item_calibration, "count_problems", _count)
        summary = await census.collect_census(object())  # type: ignore[arg-type]
        assert calls == [True]  # 실측은 읽기 전용으로 부른다
        assert summary["graded_responses"] == 7
        assert summary["problems_total"] == 11

    @pytest.mark.asyncio
    async def test_calibrator_reads_through_the_same_loader_writable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[bool] = []

        async def _loader(_session: Any, *, read_only: bool = False) -> list[Any]:
            calls.append(read_only)
            return []

        class _CommitOnly:
            async def commit(self) -> None:
                return None

        monkeypatch.setattr(item_calibration, "load_graded_responses", _loader)
        calibrated = await item_calibration.calibrate_item_difficulties(
            _CommitOnly()  # type: ignore[arg-type]
        )
        assert calibrated == 0
        # 보정기는 같은 트랜잭션에서 UPDATE하므로 읽기 전용 선언 없이 부른다.
        assert calls == [False]


class _Result:
    def __init__(self, rows: list[Any] | None = None, scalar: int | None = None) -> None:
        self._rows = rows or []
        self._scalar = scalar

    def all(self) -> list[Any]:
        return self._rows

    def scalar_one(self) -> int:
        assert self._scalar is not None
        return self._scalar


class _RecordingSession:
    """실행된 문장을 기록한다 — 첫 문장이 READ ONLY 선언인지 본다."""

    def __init__(self, rows: list[Any], problems_total: int) -> None:
        self.statements: list[str] = []
        self._rows = rows
        self._problems_total = problems_total

    async def execute(self, stmt: Any) -> _Result:
        text = str(stmt)
        self.statements.append(text)
        if "READ ONLY" in text:
            return _Result()
        if "count(" in text.lower():
            return _Result(scalar=self._problems_total)
        return _Result(rows=self._rows)


class TestCollectIsReadOnly:
    @pytest.mark.asyncio
    async def test_transaction_is_declared_read_only_before_any_query(self) -> None:
        # 대역 없이 실제 로더를 탄다 — 선언이 이 트랜잭션의 **첫 문장**인지 본다.
        session = _RecordingSession(_rows("A", _mixed(6)), problems_total=9)
        summary = await census.collect_census(session)  # type: ignore[arg-type]
        assert "SET TRANSACTION READ ONLY" in session.statements[0]
        assert summary["graded_responses"] == 6
        assert summary["problems_total"] == 9

    @pytest.mark.asyncio
    async def test_loader_default_does_not_declare_read_only(self) -> None:
        # 기본값이 읽기 전용이면 보정기의 UPDATE가 운영 DB에서 거부된다 — 대역 세션은 그것을
        # 모르므로 여기서 직접 막는다.
        session = _RecordingSession(_rows("A", _mixed(6)), problems_total=9)
        rows = await item_calibration.load_graded_responses(session)  # type: ignore[arg-type]
        assert len(rows) == 6
        assert not any("READ ONLY" in stmt for stmt in session.statements)


class TestCliExitCodes:
    def test_success_prints_ascii_json_and_writes_copy(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        async def _fake_run() -> dict[str, object]:
            return census.summarize_item_responses(_rows("A", _mixed(6)), problems_total=3)

        monkeypatch.setattr(census, "_run", _fake_run)
        out = tmp_path / "census.json"
        assert census.main(["--out", str(out)]) == 0
        printed = capsys.readouterr().out.strip()
        assert printed.isascii()
        payload = json.loads(printed)
        assert payload["graded_responses"] == 6
        assert "measured_at" in payload
        assert json.loads(out.read_text(encoding="ascii")) == payload

    def test_measurement_failure_is_exit_3_not_a_zero_report(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        async def _broken_run() -> dict[str, object]:
            raise ConnectionRefusedError("db down")

        monkeypatch.setattr(census, "_run", _broken_run)
        assert census.main([]) == 3
        captured = capsys.readouterr()
        assert captured.out == ""  # 0건 JSON으로 위장하지 않는다
        assert "CENSUS_FAILED error=ConnectionRefusedError" in captured.err
        assert "db down" not in captured.err  # 메시지 본문(DSN이 섞일 수 있다)은 남기지 않는다
