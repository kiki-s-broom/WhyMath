"""IRT 변별도 a 첫 채택 신호 테스트 (EOS-154 · hermetic — DB 불요).

신호가 막으려는 상태는 "a 보정이 처음 작동 가능해졌는데 아무도 모르는 것"이고, 같은 화면에 나오는
정반대 위험은 "아직 작동 안 하는데 로그가 조용해서 정상으로 읽히는 것"이다. 그래서 이 파일은 발화(0→1)만이
아니라 **침묵 상태가 '작동 안 함'으로 보이는지**와 **분모 0 ≠ 채택 0**, **전이는 한 번만 발화**하는지를
각각 따로 밟는다. 합성 코퍼스는 `test_item_calibration`의 400명 분위 격자와 같은 방식이다(테스트
디렉터리에 `__init__.py`가 없어 모듈 간 import를 하지 않고 자체 포함한다).
"""

from __future__ import annotations

import logging
import math
import random
import uuid
from statistics import NormalDist
from typing import Any

import pytest
from sqlalchemy import Select
from sqlalchemy.dialects import postgresql

from whymath_backend.l2 import calibrate_items
from whymath_backend.l2.calibrate_items import (
    A_STATE_ADOPTED,
    A_STATE_NO_DENOMINATOR,
    A_STATE_WAITING,
    A_TRANSITION_ADOPTION_LOST,
    A_TRANSITION_FIRST_ADOPTION,
    A_TRANSITION_NONE,
    classify_adoption,
    format_adoption_log,
    format_report_lines,
    report_to_dict,
)
from whymath_backend.l2.item_calibration import (
    _MIN_RESPONSES_FOR_DISCRIMINATION,
    A_CANDIDATE_BUCKETS,
    FALLBACK_REASONS,
    RESPONSE_COUNT_BUCKETS,
    CalibrationReport,
    _compute_calibration,
    _response_bucket,
    count_adopted_discrimination,
)


def _report(
    *,
    calibrated_b: int = 3,
    adopted: int = 0,
    distribution: dict[str, int] | None = None,
) -> CalibrationReport:
    reasons = dict.fromkeys(FALLBACK_REASONS, 0)
    reasons["insufficient_responses"] = calibrated_b - adopted
    return CalibrationReport(
        dry_run=False,
        items_with_responses=calibrated_b + 2,
        calibrated_b=calibrated_b,
        discrimination_calibrated=adopted,
        discrimination_fallback=calibrated_b - adopted,
        fallback_reasons=reasons,
        response_count_distribution=distribution or dict.fromkeys(RESPONSE_COUNT_BUCKETS, 0),
        boundary_theta_responses_excluded=0,
    )


def _synthetic_rows(n_students: int, n_items: int) -> list[tuple[uuid.UUID, uuid.UUID, bool]]:
    """결정론 2PL 합성 응답 — 학생 θ=N(0,1) 분위 격자 × 문항 n_items개 전원 응답."""
    rng = random.Random(20261009)
    nd = NormalDist()
    params = [(2.0, 0.0), (1.6, -0.5), (1.2, 0.5), (1.8, 1.0)][:n_items]
    items = [uuid.UUID(int=9000 + j) for j in range(n_items)]
    rows: list[tuple[uuid.UUID, uuid.UUID, bool]] = []
    for k in range(n_students):
        student = uuid.UUID(int=k + 1)
        theta = nd.inv_cdf((k + 0.5) / n_students)
        for item, (a, b) in zip(items, params, strict=True):
            rows.append((student, item, rng.random() < 1.0 / (1.0 + math.exp(-a * (theta - b)))))
    return rows


class TestCandidateBuckets:
    def test_a_candidate_buckets_match_the_threshold(self) -> None:
        """응답 ≥ 50 ⇔ 후보 버킷 — 임계가 바뀌었는데 튜플이 안 따라오면 사전 지표가 조용히 거짓이 된다."""
        for n in range(1, 301):
            assert (_response_bucket(n) in A_CANDIDATE_BUCKETS) == (
                n >= _MIN_RESPONSES_FOR_DISCRIMINATION
            ), n
        assert set(A_CANDIDATE_BUCKETS) <= set(RESPONSE_COUNT_BUCKETS)

    def test_candidates_count_only_items_at_or_above_fifty(self) -> None:
        dist = {"1-4": 80, "5-49": 7, "50-99": 2, "100+": 3}
        assert _report(distribution=dist).discrimination_candidates == 5

    def test_the_observed_corpus_has_zero_candidates(self) -> None:
        """EOS-129 ⑤ 운영 실측(2026-09-29): 응답 있는 80문항 전부 1~4건 → 사전 지표 0."""
        dist = {"1-4": 80, "5-49": 0, "50-99": 0, "100+": 0}
        assert _report(calibrated_b=0, distribution=dist).discrimination_candidates == 0


class TestClassifyAdoption:
    def test_zero_denominator_is_not_the_same_as_zero_adopted(self) -> None:
        """분모 0(b 보정 대상 없음)과 채택 0(대상은 있는데 안 됨)은 다른 상태다."""
        no_denominator = classify_adoption(_report(calibrated_b=0, adopted=0), 0)
        waiting = classify_adoption(_report(calibrated_b=3, adopted=0), 0)
        assert no_denominator.state == A_STATE_NO_DENOMINATOR
        assert waiting.state == A_STATE_WAITING
        assert no_denominator.state != waiting.state

    def test_adopted_state(self) -> None:
        assert classify_adoption(_report(calibrated_b=3, adopted=2), 2).state == A_STATE_ADOPTED

    @pytest.mark.parametrize(
        ("adopted", "previously", "transition"),
        [
            (0, 0, A_TRANSITION_NONE),  # 계속 대기
            (1, 0, A_TRANSITION_FIRST_ADOPTION),  # 0 → 1: 재측정 트리거
            (5, 0, A_TRANSITION_FIRST_ADOPTION),  # 0 → 여러 건도 첫 채택
            (1, 1, A_TRANSITION_NONE),  # 이미 채택 중 — 다시 발화하지 않는다
            (3, 1, A_TRANSITION_NONE),  # 늘어난 것은 첫 채택이 아니다
            (0, 1, A_TRANSITION_ADOPTION_LOST),  # 채택이 사라졌다
            (0, 4, A_TRANSITION_ADOPTION_LOST),
        ],
    )
    def test_transition_table(self, adopted: int, previously: int, transition: str) -> None:
        report = _report(calibrated_b=max(adopted, 1), adopted=adopted)
        assert classify_adoption(report, previously).transition == transition

    def test_pure_and_deterministic(self) -> None:
        report = _report(adopted=1)
        assert classify_adoption(report, 0) == classify_adoption(report, 0)


class TestAdoptionLogLine:
    def test_waiting_state_reads_as_not_working_not_as_ok(self) -> None:
        """침묵 상태가 '정상'으로 위장되지 않는다 — 대기 상태도 매 실행 줄이 나오고 채택 0을 말한다."""
        line = format_adoption_log(
            classify_adoption(_report(calibrated_b=0, adopted=0), 0), run_id="r1", dry_run=False
        )
        assert line.startswith("irt_a_signal run_id=r1 ")
        assert "state=no_denominator" in line
        assert "transition=none" in line
        assert "adopted=0" in line
        assert "candidates_ge50=0" in line
        assert "next=" not in line  # 행동 안내는 첫 채택에만 붙는다

    def test_first_adoption_line_names_the_next_action(self) -> None:
        line = format_adoption_log(
            classify_adoption(_report(adopted=2), 0), run_id="r2", dry_run=True
        )
        assert "transition=first_adoption" in line
        assert "dry_run=true" in line
        assert "next=remeasure_eos129" in line

    def test_line_carries_both_thresholds(self) -> None:
        line = format_adoption_log(classify_adoption(_report(), 0), run_id="r", dry_run=False)
        assert "min_responses=50" in line
        assert "max_se=0.3" in line


class TestOutputFields:
    def test_text_and_json_share_the_same_signal_fields(self) -> None:
        report = _report(adopted=1, distribution={"1-4": 0, "5-49": 1, "50-99": 1, "100+": 0})
        signal = classify_adoption(report, 0)
        lines = format_report_lines(report, signal)
        data = report_to_dict(report, signal)
        assert lines[0] == "calibrated_items=3"  # 첫 줄 하위호환 고정
        assert "a_adoption_state=adopted" in lines
        assert "a_adoption_transition=first_adoption" in lines
        assert "a_previously_adopted=0" in lines
        assert "a_candidates_ge50=1" in lines
        assert data["a_adoption_state"] == "adopted"
        assert data["a_adoption_transition"] == "first_adoption"
        assert data["a_previously_adopted"] == 0
        assert data["a_candidates_ge50"] == 1

    def test_without_signal_the_old_output_is_unchanged(self) -> None:
        report = _report()
        assert not any(line.startswith("a_") for line in format_report_lines(report))
        assert not any(k.startswith("a_") for k in report_to_dict(report))


class TestSyntheticTransition:
    """acceptance ④ — 합성 응답으로 a 채택 0건 → 1건 이상 전이를 재현하고, 그 전 상태가 침묵하지 않음을 본다."""

    def test_small_corpus_stays_waiting_and_visible(self) -> None:
        """응답이 문항당 50건 미만이면 b는 보정돼도 a는 채택 0 — 신호는 `waiting`으로 보인다."""
        report = _compute_calibration(_synthetic_rows(30, 3)).report
        assert report.calibrated_b == 3  # b는 작동한다
        assert report.discrimination_calibrated == 0  # a는 작동하지 않는다
        signal = classify_adoption(report, 0)
        assert signal.state == A_STATE_WAITING
        assert signal.transition == A_TRANSITION_NONE
        assert signal.candidates_ge50 == 0  # 사전 지표도 0 — 구조적으로 채택 불가

    def test_large_corpus_fires_first_adoption_exactly_once(self) -> None:
        """같은 코퍼스를 두 번 보정: 1회차 0→N 발화, 2회차(DB에 N건 영속)는 재발화하지 않는다."""
        report = _compute_calibration(_synthetic_rows(400, 3)).report
        assert report.discrimination_calibrated >= 1
        assert (
            report.discrimination_candidates >= report.discrimination_calibrated
        )  # 사전 지표는 상한

        first = classify_adoption(report, previously_adopted=0)
        assert first.state == A_STATE_ADOPTED
        assert first.transition == A_TRANSITION_FIRST_ADOPTION

        persisted = report.discrimination_calibrated  # 1회차가 irt_a에 영속한 건수
        second = classify_adoption(report, previously_adopted=persisted)
        assert second.state == A_STATE_ADOPTED
        assert second.transition == A_TRANSITION_NONE

    def test_growth_from_small_to_large_is_the_zero_to_one_event(self) -> None:
        """응답 축적: 30명 코퍼스(채택 0) → 400명 코퍼스(채택 ≥ 1)가 정확히 신호가 잡으려는 사건이다."""
        before = _compute_calibration(_synthetic_rows(30, 3)).report
        after = _compute_calibration(_synthetic_rows(400, 3)).report
        prior = before.discrimination_calibrated  # 이 값이 DB `irt_a` 채움 수가 된다
        assert prior == 0
        assert classify_adoption(after, prior).transition == A_TRANSITION_FIRST_ADOPTION


class _FakeScalar:
    def __init__(self, value: int) -> None:
        self._value = value

    def scalar_one(self) -> int:
        return self._value


class _CapturingSession:
    def __init__(self, value: int) -> None:
        self._value = value
        self.statements: list[Any] = []

    async def execute(self, stmt: Any) -> _FakeScalar:
        self.statements.append(stmt)
        return _FakeScalar(self._value)


class TestCountAdoptedDiscrimination:
    async def test_returns_the_scalar_and_issues_one_read_only_select(self) -> None:
        sess = _CapturingSession(7)
        assert await count_adopted_discrimination(sess) == 7  # type: ignore[arg-type]
        assert len(sess.statements) == 1
        assert isinstance(sess.statements[0], Select)  # UPDATE·INSERT가 아니다

    async def test_counts_only_non_null_irt_a(self) -> None:
        """WHERE 절이 `irt_a IS NOT NULL`이어야 한다 — 전체 문항 수를 세면 신호가 항상 켜진다."""
        sess = _CapturingSession(0)
        await count_adopted_discrimination(sess)  # type: ignore[arg-type]
        sql = str(sess.statements[0].compile(dialect=postgresql.dialect()))
        assert "irt_a IS NOT NULL" in sql
        assert "count(" in sql.lower()


class _Recorder:
    """호출 순서 기록 — 직전 채택 수 조회가 보정보다 **먼저**여야 전이가 보인다."""

    def __init__(self) -> None:
        self.order: list[str] = []


class _FakeSession:
    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


class TestCliWiring:
    def _wire(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        previously: int,
        adopted: int,
        calibrated_b: int = 3,
    ) -> _Recorder:
        rec = _Recorder()

        async def _prior(session: Any) -> int:
            rec.order.append("count_prior")
            return previously

        async def _calibrate(session: Any, *, dry_run: bool = False) -> CalibrationReport:
            rec.order.append("calibrate")
            return _report(calibrated_b=calibrated_b, adopted=adopted)

        async def _dispose() -> None:
            return None

        monkeypatch.setattr(calibrate_items, "get_sessionmaker", lambda settings=None: _FakeSession)
        monkeypatch.setattr(calibrate_items, "count_adopted_discrimination", _prior)
        monkeypatch.setattr(calibrate_items, "calibrate_item_difficulties", _calibrate)
        monkeypatch.setattr(calibrate_items, "dispose_engine", _dispose)
        return rec

    def _signal_records(self, caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
        return [
            r
            for r in caplog.records
            if r.name == "whymath.l2.calibrate_items" and r.getMessage().startswith("irt_a_signal ")
        ]

    def test_prior_count_is_read_before_the_calibration_writes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rec = self._wire(monkeypatch, previously=0, adopted=1)
        assert calibrate_items.main([]) == 0
        assert rec.order == ["count_prior", "calibrate"]

    def test_first_adoption_is_logged_at_warning_with_the_transition(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        self._wire(monkeypatch, previously=0, adopted=1)
        with caplog.at_level("INFO", logger="whymath.l2.calibrate_items"):
            assert calibrate_items.main([]) == 0
        records = self._signal_records(caplog)
        assert len(records) == 1
        assert records[0].levelno == logging.WARNING  # 전이는 매일 찍히는 INFO 줄과 구별된다
        assert "transition=first_adoption" in records[0].getMessage()

    def test_waiting_state_still_emits_one_info_line_every_run(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """채택 0건이어도 줄은 나온다 — 줄이 없는 것과 '대기 중'을 구별할 수 있어야 신호다."""
        self._wire(monkeypatch, previously=0, adopted=0)
        with caplog.at_level("INFO", logger="whymath.l2.calibrate_items"):
            assert calibrate_items.main([]) == 0
        records = self._signal_records(caplog)
        assert len(records) == 1
        assert records[0].levelno == logging.INFO
        message = records[0].getMessage()
        assert "state=waiting" in message
        assert "transition=none" in message
        assert "adopted=0" in message

    def test_adoption_lost_is_a_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        self._wire(monkeypatch, previously=2, adopted=0)
        with caplog.at_level("INFO", logger="whymath.l2.calibrate_items"):
            assert calibrate_items.main([]) == 0
        (record,) = self._signal_records(caplog)
        assert record.levelno == logging.WARNING
        assert "transition=adoption_lost" in record.getMessage()

    def test_stdout_first_line_contract_and_signal_fields(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._wire(monkeypatch, previously=0, adopted=1)
        assert calibrate_items.main([]) == 0
        lines = capsys.readouterr().out.splitlines()
        assert lines[0] == "calibrated_items=3"
        assert "a_adoption_transition=first_adoption" in lines

    def test_prior_count_failure_is_logged_as_failed_with_the_type_name(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """직전 채택 수를 못 읽으면 보정도 하지 않는다 — 전이를 '모르는' 채로 쓰기를 진행하지 않는다."""
        rec = self._wire(monkeypatch, previously=0, adopted=1)

        async def _boom(session: Any) -> int:
            rec.order.append("count_prior")
            raise ConnectionRefusedError("secret-host:5432")

        monkeypatch.setattr(calibrate_items, "count_adopted_discrimination", _boom)
        with caplog.at_level("ERROR", logger="whymath.l2.calibrate_items"):
            with pytest.raises(ConnectionRefusedError):
                calibrate_items.main([])
        assert rec.order == ["count_prior"]  # calibrate는 호출되지 않았다
        messages = " ".join(r.getMessage() for r in caplog.records)
        assert "status=failed" in messages
        assert "error_type=ConnectionRefusedError" in messages
        assert "secret-host" not in messages
