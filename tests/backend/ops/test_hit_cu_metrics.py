"""HIT·CU 집계 CLI — 순수 코어·미계측 분리·실패 승격·게이트 변별력 (EOS-54 acceptance ②·④).

정본: `ops/hit_cu_metrics.py`. 검증 축:
  - CU 3분류(measured/unmeasured/unfinished) — 미계측이 **0초로 산입되지 않음**을 중앙값
    불변으로 실측(0 날조 금지).
  - 적재율("작동한 비율") — 판정 소스 있을 때 Wilson 하한 병기·없을 때 None=미산출(0% 아님).
  - 실패코드 분포 — `GenerationFailureCode` 동결 8코드 전건 키 표기(0 포함)·기계/판단 비중.
  - CU당 비용 조인 — slug·problem_id 양 경로·미조인 CU 분리(0원 산입 금지).
  - CLI exit — 입력 0건·창 내 0건·전건 미계측·**파싱 실패 혼입** 전부 **exit 1 승격**,
    정상 표본은 exit 0, 게이트는 통과/실패 **양쪽** 실측(변별력 없는 검증 스텝 금지).
  - 표본 위생(#909 codex P1×2) — 같은 event_id 재출현은 중복 제거(재시도 이중 합산 방지),
    구조 이상 세션(복수 slug/복수 종결)은 measured 불성립 강등(오염 표본 KPI 유입 금지).
  - null 메트릭(#909 codex P2) — cost_usd null 행은 "$0 계측"이 아니라 미기록 분리.
  - stdout 순수성(#909 codex P2) — 진행·판정은 stderr, stdout은 데이터 전용(--json은
    stdout 전체가 단일 JSON 문서).

hermetic — tmp_path·픽스처만(파일 I/O 외 부작용 0).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from whymath_backend.harness.review_timer import (
    abort_review,
    append_event_jsonl,
    finish_review,
    start_review,
)
from whymath_backend.harness.wilson import wilson_lower_bound
from whymath_backend.ops.hit_cu_metrics import (
    aggregate,
    classify_cus,
    classify_sessions,
    dedupe_events,
    main,
    render_report,
)
from whymath_backend.schema.enums import GenerationFailureCode
from whymath_backend.schema.review_timer import ReviewTimerEvent

_T0 = datetime(2026, 8, 31, 2, 0, tzinfo=UTC)


def _reviewed_cu(
    slug: str,
    elapsed_ms: int | None,
    *,
    verdict: str = "approved",
    failure_code: GenerationFailureCode | None = None,
    problem_id: uuid.UUID | None = None,
    occurred_at: datetime = _T0,
) -> list[ReviewTimerEvent]:
    """CU 1개를 1세션으로 검수한 이벤트 쌍(started+finished) — 픽스처 축약."""
    started = start_review(
        cu_slug=slug, reviewer_id="kiki", problem_id=problem_id, occurred_at=occurred_at
    )
    finished = finish_review(
        review_session_id=started.review_session_id,
        cu_slug=slug,
        reviewer_id="kiki",
        verdict=verdict,  # type: ignore[arg-type]  # 픽스처 — schema가 재검증
        failure_code=failure_code,
        elapsed_ms=elapsed_ms,
        problem_id=problem_id,
        occurred_at=occurred_at,
    )
    return [started, finished]


class TestSessionClassification:
    def test_paired_session_measured(self) -> None:
        sessions, anomalies = classify_sessions(_reviewed_cu("cu-a", 60_000))
        assert anomalies == 0
        assert len(sessions) == 1
        assert sessions[0].measured is True
        assert sessions[0].elapsed_ms_total == 60_000

    def test_dangling_start_is_unmeasured(self) -> None:
        """종결 신호 유실(크래시) — dangling은 measured가 아니다(신호 유실≠0초)."""
        sessions, _ = classify_sessions([start_review(cu_slug="cu-a", reviewer_id="kiki")])
        assert sessions[0].has_terminal is False
        assert sessions[0].measured is False

    def test_finished_without_elapsed_unmeasured(self) -> None:
        sessions, _ = classify_sessions(_reviewed_cu("cu-a", None))
        assert sessions[0].has_finish is True
        assert sessions[0].measured is False
        assert sessions[0].elapsed_ms_total == 0  # 합산 제외(0 날조가 아니라 미합산)


class TestSampleHygiene:
    """#909 codex P1×2 — 중복 이벤트·구조 이상 세션이 HIT 표본을 오염하지 못한다."""

    def test_duplicate_event_id_counted_once(self) -> None:
        """같은 event_id 재출현(append 재시도)은 같은 관측 — 1분 검수가 2분이 되지 않는다.

        구 코드는 종결 이벤트를 두 번 합산해 중앙값을 끌어올렸다 — 값 불변이 변별력.
        """
        events = _reviewed_cu("cu-a", 60_000)
        duplicated = events + [events[1]]  # finished를 그대로 재기록(동일 event_id)
        unique, dup_count = dedupe_events(duplicated)
        assert dup_count == 1
        assert len(unique) == 2
        report = aggregate(duplicated)
        assert report.duplicate_event_count == 1
        assert report.session_anomaly_count == 0  # 중복 제거 후엔 정상 세션
        assert report.hit_median_seconds == 60.0  # 120초로 이중 합산되지 않음
        assert report.cu_measured == 1

    def test_distinct_double_terminal_session_degraded(self) -> None:
        """한 세션에 서로 다른 종결 2건 = 구조 이상 — 합산 표본이 아니라 미계측 강등.

        구 코드는 두 경과를 합산한 채 measured로 뒀다(1분→2분 오염) — kind 전환이 변별력.
        """
        started = start_review(cu_slug="cu-a", reviewer_id="kiki")
        double = [
            started,
            finish_review(
                review_session_id=started.review_session_id,
                cu_slug="cu-a",
                reviewer_id="kiki",
                verdict="approved",  # type: ignore[arg-type]  # 픽스처 — schema가 재검증
                elapsed_ms=60_000,
            ),
            finish_review(
                review_session_id=started.review_session_id,
                cu_slug="cu-a",
                reviewer_id="kiki",
                verdict="approved",  # type: ignore[arg-type]  # 픽스처 — schema가 재검증
                elapsed_ms=60_000,
            ),
        ]
        report = aggregate(double + _reviewed_cu("cu-b", 90_000))
        assert report.session_anomaly_count == 1
        cus = {c.cu_slug: c for c in classify_cus(classify_sessions(double)[0])}
        assert cus["cu-a"].kind == "unmeasured"  # 표본 밖 + 분리 카운트로 가시화
        assert report.hit_median_seconds == 90.0  # cu-b 단독 표본 — 오염 무영향

    def test_cross_slug_session_degraded(self) -> None:
        """한 세션이 두 slug에 걸침 — 임의 slug 귀속 시간은 KPI 표본이 될 수 없다."""
        started = start_review(cu_slug="cu-a", reviewer_id="kiki")
        crossed = [
            started,
            finish_review(
                review_session_id=started.review_session_id,
                cu_slug="cu-b",  # 시작과 다른 slug
                reviewer_id="kiki",
                verdict="approved",  # type: ignore[arg-type]  # 픽스처 — schema가 재검증
                elapsed_ms=60_000,
            ),
        ]
        sessions, anomalies = classify_sessions(crossed)
        assert anomalies == 1
        assert sessions[0].measured is False


class TestCuClassification:
    def test_three_kinds_split(self) -> None:
        """measured/unmeasured/unfinished 3분류 — 미계측·미종결은 HIT 표본 밖."""
        started = start_review(cu_slug="cu-c", reviewer_id="kiki")
        events = (
            _reviewed_cu("cu-a", 60_000)
            + _reviewed_cu("cu-b", None)  # 종결했으나 미계측
            + [
                started,
                abort_review(  # 중단만 — 미종결
                    review_session_id=started.review_session_id,
                    cu_slug="cu-c",
                    reviewer_id="kiki",
                    elapsed_ms=10_000,
                ),
            ]
        )
        cus = {c.cu_slug: c for c in classify_cus(classify_sessions(events)[0])}
        assert cus["cu-a"].kind == "measured" and cus["cu-a"].hit_seconds == 60.0
        assert cus["cu-b"].kind == "unmeasured" and cus["cu-b"].hit_seconds is None
        assert cus["cu-c"].kind == "unfinished" and cus["cu-c"].hit_seconds is None

    def test_multi_session_cu_sums_all_measured_time(self) -> None:
        """시작→중단(3분)→재시작→종결(2분) = HIT 5분 — 중단 시간도 그 CU에 쓴 인간 시간."""
        first = start_review(cu_slug="cu-a", reviewer_id="kiki")
        events = [
            first,
            abort_review(
                review_session_id=first.review_session_id,
                cu_slug="cu-a",
                reviewer_id="kiki",
                elapsed_ms=180_000,
            ),
        ] + _reviewed_cu("cu-a", 120_000)
        cus = classify_cus(classify_sessions(events)[0])
        assert len(cus) == 1
        assert cus[0].kind == "measured"
        assert cus[0].hit_seconds == 300.0
        assert cus[0].session_count == 2

    def test_one_unmeasured_session_degrades_whole_cu(self) -> None:
        """부분 계측 CU는 measured가 아니다 — 합계가 과소집계(누락 날조)되는 것을 차단."""
        first = start_review(cu_slug="cu-a", reviewer_id="kiki")
        events = [
            first,
            abort_review(
                review_session_id=first.review_session_id,
                cu_slug="cu-a",
                reviewer_id="kiki",
                elapsed_ms=None,  # 중단 경과 미계측
            ),
        ] + _reviewed_cu("cu-a", 120_000)
        cus = classify_cus(classify_sessions(events)[0])
        assert cus[0].kind == "unmeasured"
        assert cus[0].hit_seconds is None


class TestHitStatistics:
    def test_median_p90_over_measured_only(self) -> None:
        """중앙값·P90은 measured CU 표본만 — 미계측 CU가 섞여도 값이 **변하지 않는다**.

        미계측이 0초로 산입되면 중앙값이 내려간다 — 불변임을 실측해 0 산입 금지를 증명
        (acceptance ④의 핵심 변별력).
        """
        measured = (
            _reviewed_cu("cu-a", 60_000)
            + _reviewed_cu("cu-b", 120_000)
            + _reviewed_cu("cu-c", 600_000)
        )
        clean = aggregate(measured)
        polluted = aggregate(measured + _reviewed_cu("cu-z", None))
        assert clean.hit_median_seconds == 120.0
        assert clean.hit_p90_seconds == pytest.approx(504.0)  # 선형 보간(cost_report 규약)
        assert polluted.hit_median_seconds == clean.hit_median_seconds  # 미계측 무영향
        assert polluted.hit_p90_seconds == clean.hit_p90_seconds
        assert polluted.cu_unmeasured == 1  # 대신 분리 카운트로 가시화
        assert polluted.cu_measured == 3

    def test_empty_events_zero_samples_not_zero_minutes(self) -> None:
        report = aggregate([])
        assert report.cu_measured == 0
        assert report.hit_median_seconds is None  # 0.0이 아니라 None(표본 없음)
        assert report.hit_total_seconds == 0.0


class TestCoverage:
    def test_coverage_with_verdict_source(self) -> None:
        """판정 3건 중 타이머 동반 2건 = 66.7%·Wilson 하한 병기·pending 분모 제외."""
        events = _reviewed_cu("cu-a", 60_000) + _reviewed_cu("cu-b", 90_000)
        verdicts = [
            {"slug": "cu-a", "review_status": "approved"},
            {"slug": "cu-b", "review_status": "rejected"},
            {"slug": "cu-ghost", "review_status": "approved"},  # 타이머 없는 판정(미계측 검수)
            {"slug": "cu-pending", "review_status": "pending"},  # 판정 아님 — 분모 제외
        ]
        report = aggregate(events, verdict_rows=verdicts)
        assert report.verdict_total == 3
        assert report.verdict_with_timer == 2
        assert report.coverage_rate == pytest.approx(2 / 3)
        assert report.coverage_wilson_lower == pytest.approx(wilson_lower_bound(2, 3))
        assert report.coverage_wilson_lower is not None
        assert report.coverage_wilson_lower < report.coverage_rate  # 하한 < 점추정(소표본 보정)
        assert report.verdict_non_verdict_rows == 1

    def test_no_source_means_none_not_zero(self) -> None:
        """소스 미제공 = None(미산출) — 0%로 위장 금지 + 렌더에 '미산출' 명기."""
        report = aggregate(_reviewed_cu("cu-a", 60_000))
        assert report.verdict_total is None
        assert report.coverage_rate is None
        assert "미산출(판정 소스 미제공)" in render_report(report)

    def test_code_identity_key_supported(self) -> None:
        """#841 라벨 형식(code 키)도 식별자로 수용."""
        report = aggregate(
            _reviewed_cu("N1", 60_000),
            verdict_rows=[{"code": "N1", "review_status": "approved"}],
        )
        assert report.verdict_with_timer == 1

    def test_identity_missing_row_reported(self) -> None:
        report = aggregate(
            _reviewed_cu("cu-a", 60_000),
            verdict_rows=[{"review_status": "approved"}],
        )
        assert report.verdict_total == 0
        assert len(report.verdict_parse_errors) == 1
        assert "MissingIdentityKey" in report.verdict_parse_errors[0]


class TestFailureDistribution:
    def test_all_eight_codes_present_with_zero(self) -> None:
        """동결 8코드 전건 키 표기(0 포함) — enum이 분포 표의 단일 진실."""
        report = aggregate(_reviewed_cu("cu-a", 60_000))
        assert set(report.failure_code_counts) == {c.value for c in GenerationFailureCode}
        assert all(v == 0 for v in report.failure_code_counts.values())
        assert report.machine_share is None  # 반려 0 — 비중은 미산출(0% 날조 금지)

    def test_machine_judgment_shares(self) -> None:
        events = (
            _reviewed_cu("cu-a", 1_000, verdict="rejected", failure_code=GenerationFailureCode.F1)
            + _reviewed_cu("cu-b", 1_000, verdict="rejected", failure_code=GenerationFailureCode.F2)
            + _reviewed_cu("cu-c", 1_000, verdict="rejected", failure_code=GenerationFailureCode.F3)
            + _reviewed_cu("cu-d", 1_000, verdict="approved")
        )
        report = aggregate(events)
        assert report.rejected_count == 3
        assert report.failure_code_counts["F1"] == 1
        assert report.failure_code_counts["F3"] == 1
        assert report.machine_share == pytest.approx(2 / 3)  # F1+F2
        assert report.judgment_share == pytest.approx(1 / 3)  # F3+F6+F7


class TestCostJoin:
    def test_join_by_slug_and_problem_id_with_separation(self) -> None:
        """slug·problem_id 양 조인 경로 + 미조인 CU 분리(0원 산입 금지) + 미매칭 행 카운트."""
        pid = uuid.uuid4()
        events = (
            _reviewed_cu("cu-a", 60_000)
            + _reviewed_cu("cu-b", 90_000, problem_id=pid)
            + _reviewed_cu("cu-c", 30_000)  # 비용 행 없음 — 분리 대상
        )
        genlog = [
            {"slug": "cu-a", "input_tokens": 1000, "output_tokens": 500, "cost_usd": 0.02},
            {"slug": "cu-a", "input_tokens": 400, "output_tokens": 100, "cost_usd": 0.01},
            {"problem_id": str(pid), "input_tokens": 2000, "output_tokens": 800, "cost_usd": 0.05},
            {"slug": "cu-unrelated", "cost_usd": 9.99},  # 타이머 CU 밖 — 미매칭
        ]
        report = aggregate(events, genlog_rows=genlog)
        assert report.cost_rows_matched == 3
        assert report.cost_rows_unmatched == 1
        assert report.cu_with_cost == 2
        assert report.cu_without_cost == 1  # cu-c — 0원 산입이 아니라 분리
        assert report.cost_usd_total == pytest.approx(0.08)
        assert report.tokens_total == 4800
        assert report.cost_usd_per_cu_p50 == pytest.approx(0.04)  # CU별 [0.03, 0.05] 중앙

    def test_no_source_means_none(self) -> None:
        report = aggregate(_reviewed_cu("cu-a", 60_000))
        assert report.cost_usd_total is None  # 소스 미제공 — $0이 아니라 미산출
        assert "미산출(GenerationLog 소스 미제공)" in render_report(report)

    def test_null_cost_row_stays_unmetered(self) -> None:
        """#909 codex P2 — cost_usd null 행은 "$0 계측"이 아니라 미기록 분리.

        구 코드는 null→0 변환 후 CU를 비용 계측으로 셌다(백분위·cu_without_cost 오염).
        null 행이 섞인 CU는 부분합(하한)이라 백분위 표본에서도 제외됨을 동결.
        """
        events = _reviewed_cu("cu-a", 60_000) + _reviewed_cu("cu-b", 90_000)
        genlog = [
            {"slug": "cu-a", "input_tokens": 1000, "output_tokens": 500, "cost_usd": 0.03},
            # cu-b: 실기록 1행 + 미기록(null) 1행 — 부분 기록 CU
            {"slug": "cu-b", "input_tokens": 2000, "output_tokens": 800, "cost_usd": 0.05},
            {"slug": "cu-b", "input_tokens": None, "output_tokens": None, "cost_usd": None},
        ]
        report = aggregate(events, genlog_rows=genlog)
        assert report.cost_rows_matched == 3  # 조인 자체는 성립(조인≠계측)
        assert report.cost_rows_unmetered == 1
        assert report.cu_with_cost == 1  # cu-a만 완전 계측
        assert report.cu_cost_incomplete == 1  # cu-b — $0.05로 위장하지 않고 분리
        assert report.cu_without_cost == 0
        assert report.cost_usd_per_cu_p50 == pytest.approx(0.03)  # cu-b 부분합 미유입
        assert report.cost_usd_total == pytest.approx(0.08)  # 기록된 비용의 합(하한)
        assert report.tokens_total == 4300  # 기록된 토큰만 — null은 0 산입 없음


class TestReportRender:
    def test_enforcement_footnote_always_present(self) -> None:
        """acceptance ③ — 집행 상태(생산자 배선 + 남은 간극)를 리포트가 상시 명기.

        [EOS-78 갱신] 초판은 "결선은 후속 태스크(HARN-24 amend CLI 부재)"를 단언했으나 그
        서술은 생산자가 0이던 시절의 것이다. `harness/review_session` CLI가 착지해 생산자가
        생겼으므로, footer가 말해야 하는 사실이 바뀌었다 — ①생산자는 배선됐다 ②그러나 강제는
        그 CLI·Admin BFF 경로에 한정되고 이전·밖 경로의 판정은 적재율로 드러난다(ADMIN-18로 갱신).
        둘 다 명기되는지 동결한다
        (완료를 과장하지도, 이미 된 일을 미결로 남기지도 않는다).
        """
        text = render_report(aggregate(_reviewed_cu("cu-a", 60_000)))
        assert "정본화≠집행" in text
        # ① 생산자 배선 사실
        assert "review_session" in text
        assert "EOS-78" in text
        # ② 남은 간극 — 이 API 밖 경로의 판정은 타이머 없이 있을 수 있다(ADMIN-18 배선 명기)
        assert "ADMIN-18" in text

    def test_unmeasured_counts_rendered(self) -> None:
        text = render_report(aggregate(_reviewed_cu("cu-a", 60_000) + _reviewed_cu("cu-b", None)))
        assert "미계측 1" in text
        assert "0초 산입 금지" in text


# ==========================================================================
# CLI shell — exit code 전건 실측(성공/실패 양쪽 — 변별력).
# ==========================================================================


def _write_events(path: Path, events: list[ReviewTimerEvent]) -> None:
    for event in events:
        append_event_jsonl(path, event)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


class TestCliExitCodes:
    def test_missing_events_file_exit1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["--events", str(tmp_path / "absent.jsonl")]) == 1
        assert "FileNotFoundError" in capsys.readouterr().err  # 예외 타입명 보존(stderr)

    def test_zero_events_exit1(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """입력 0건 = 성공 0이 아니라 측정 실패(acceptance ④)."""
        path = tmp_path / "events.jsonl"
        path.write_text("", encoding="utf-8")
        assert main(["--events", str(path)]) == 1
        assert "측정 실패" in capsys.readouterr().err

    def test_all_unmeasured_exit1(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """판정은 있으나 전건 미계측 — '0분'이 아니라 측정 실패로 승격."""
        path = tmp_path / "events.jsonl"
        _write_events(path, _reviewed_cu("cu-a", None))
        assert main(["--events", str(path)]) == 1
        assert "계측 CU 0건" in capsys.readouterr().err

    def test_measured_fixture_exit0(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / "events.jsonl"
        _write_events(path, _reviewed_cu("cu-a", 60_000))
        assert main(["--events", str(path)]) == 0
        captured = capsys.readouterr()
        assert "측정 성공" in captured.err  # 판정은 stderr
        assert "HIT·CU 생산 계측 리포트" in captured.out  # 데이터(리포트)는 stdout

    def test_json_output_is_sole_stdout_document(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """#909 codex P2 — --json이면 stdout **전체**가 유효한 JSON 문서 하나여야 한다.

        구 코드는 진행 메시지가 stdout에 섞여 `json.load` 소비자가 깨졌다(테스트도
        중괄호 발췌로만 통과) — 발췌 없는 전체 파싱이 변별력.
        """
        path = tmp_path / "events.jsonl"
        _write_events(path, _reviewed_cu("cu-a", 60_000))
        assert main(["--events", str(path), "--json"]) == 0
        captured = capsys.readouterr()
        payload = json.loads(captured.out)  # 발췌 금지 — stdout 전체가 곧 문서
        assert payload["cu_measured"] == 1
        assert payload["hit_median_seconds"] == 60.0
        assert "[① 이벤트]" in captured.err  # 진행 메시지는 stderr로 분리됐다

    def test_malformed_event_line_fails_gate(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """#909 codex P1 — 파싱 실패 행 혼입 = 측정 실패(부분 입력으로 판정 금지).

        깨진 행이 하필 '느린 finished'였다면 표본에서 사라진 채 게이트가 통과한다 —
        유효 표본이 있어도 exit 1이어야 하고, 리포트(증거)는 그래도 출력된다.
        """
        path = tmp_path / "events.jsonl"
        _write_events(path, _reviewed_cu("cu-a", 60_000))
        with path.open("a", encoding="utf-8") as fh:
            fh.write("{깨진 행\n")
        assert main(["--events", str(path), "--max-median-minutes", "4"]) == 1
        captured = capsys.readouterr()
        assert "파싱 실패" in captured.err
        assert "HIT·CU 생산 계측 리포트" in captured.out  # 실패해도 증거는 남는다

    def test_malformed_verdict_line_fails_gate(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """보조 소스(판정 JSONL)의 파싱 실패도 동일하게 측정 실패로 승격."""
        events_path = tmp_path / "events.jsonl"
        verdicts_path = tmp_path / "verdicts.jsonl"
        _write_events(events_path, _reviewed_cu("cu-a", 60_000))
        verdicts_path.write_text(
            json.dumps({"slug": "cu-a", "review_status": "approved"}) + "\nnot-json\n",
            encoding="utf-8",
        )
        assert main(["--events", str(events_path), "--verdicts", str(verdicts_path)]) == 1
        assert "파싱 실패" in capsys.readouterr().err


class TestCliGates:
    def test_median_gate_both_sides(self, tmp_path: Path) -> None:
        """게이트 통과/실패 양쪽 실측 — 변별력 없는 검증 스텝 금지."""
        path = tmp_path / "events.jsonl"
        _write_events(path, _reviewed_cu("cu-a", 300_000))  # 5분
        assert main(["--events", str(path), "--max-median-minutes", "4"]) == 1  # 5>4 FAIL
        assert main(["--events", str(path), "--max-median-minutes", "6"]) == 0  # 5<6 PASS

    def test_p90_gate_both_sides(self, tmp_path: Path) -> None:
        path = tmp_path / "events.jsonl"
        _write_events(path, _reviewed_cu("cu-a", 540_000))  # 9분
        assert main(["--events", str(path), "--max-p90-minutes", "8"]) == 1
        assert main(["--events", str(path), "--max-p90-minutes", "10"]) == 0

    def test_min_coverage_without_source_exit1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """게이트를 잴 소스가 없으면 통과가 아니라 측정 실패."""
        path = tmp_path / "events.jsonl"
        _write_events(path, _reviewed_cu("cu-a", 60_000))
        assert main(["--events", str(path), "--min-coverage", "0.5"]) == 1
        assert "--verdicts" in capsys.readouterr().err

    def test_min_coverage_judged_by_wilson_both_sides(self, tmp_path: Path) -> None:
        """적재율 게이트는 Wilson 하한 판정 — 전건 동반이어도 소표본 하한만큼만 통과."""
        events_path = tmp_path / "events.jsonl"
        verdicts_path = tmp_path / "verdicts.jsonl"
        _write_events(events_path, _reviewed_cu("cu-a", 60_000) + _reviewed_cu("cu-b", 60_000))
        _write_jsonl(
            verdicts_path,
            [
                {"slug": "cu-a", "review_status": "approved"},
                {"slug": "cu-b", "review_status": "approved"},
            ],
        )
        lower = wilson_lower_bound(2, 2)  # 점추정 100%지만 하한은 그보다 훨씬 낮다
        args = ["--events", str(events_path), "--verdicts", str(verdicts_path)]
        assert main([*args, "--min-coverage", f"{lower + 0.05:.4f}"]) == 1  # 하한 미달 FAIL
        assert main([*args, "--min-coverage", f"{lower - 0.05:.4f}"]) == 0  # 하한 충족 PASS


class TestCliTimeWindow:
    def test_since_filter_both_sides(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """이전 실행 증거 오독 방지 — 창 밖 전건이면 exit 1, 창 안이면 exit 0."""
        path = tmp_path / "events.jsonl"
        old = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
        _write_events(path, _reviewed_cu("cu-a", 60_000, occurred_at=old))
        assert main(["--events", str(path), "--since", "2026-08-30T00:00:00+00:00"]) == 1
        assert "창 내 이벤트 0건" in capsys.readouterr().err
        assert main(["--events", str(path), "--since", "2026-07-01T00:00:00+00:00"]) == 0

    def test_bad_since_exit1(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        path = tmp_path / "events.jsonl"
        _write_events(path, _reviewed_cu("cu-a", 60_000))
        assert main(["--events", str(path), "--since", "not-a-date"]) == 1
        assert "ValueError" in capsys.readouterr().err


class TestApprovalResolutionSplit:
    """EOS-62 ③ — 승인율을 무손질/손질 포함으로 분리 보고한다.

    하나로 뭉친 승인율은 사람이 고쳐서 만든 성공을 AI의 성공으로 계상한다. 두 값을 나란히
    내야 "HIT 4분 달성"이 품질 실태를 오독시키지 않는다.
    """

    #: EOS-62 착지 경계 — 픽스처 이벤트(_T0)보다 하루 전이라 전건이 '경계 이후'다.
    BOUNDARY = _T0 - timedelta(days=1)

    @staticmethod
    def _mixed() -> list[ReviewTimerEvent]:
        """무손질 2 · 손질 1 · 반려 1 — 승인율 두 값이 서로 달라지는 최소 구성."""
        return [
            *_reviewed_cu("cu-clean-1", 60_000),
            *_reviewed_cu("cu-clean-2", 60_000),
            *_reviewed_cu(
                "cu-edited",
                180_000,
                verdict="approved_with_edit",
                failure_code=GenerationFailureCode.F7,
            ),
            *_reviewed_cu(
                "cu-rejected", 60_000, verdict="rejected", failure_code=GenerationFailureCode.F2
            ),
        ]

    def test_two_approval_rates_are_reported_and_differ(self) -> None:
        report = aggregate(self._mixed(), edit_aware_since=self.BOUNDARY)
        assert report.decided_count == 4
        assert report.approved_clean_count == 2
        assert report.approved_with_edit_count == 1
        assert report.rejected_count == 1
        assert report.approval_rate_clean == pytest.approx(2 / 4)
        assert report.approval_rate_including_edit == pytest.approx(3 / 4)
        # 두 값이 같으면 이 지표는 아무것도 구분하지 못한다 — 격차 자체가 산출물이다.
        assert report.approval_rate_clean != report.approval_rate_including_edit

    def test_clean_approval_rate_carries_wilson_lower_bound(self) -> None:
        """점추정 금지(초인간 검증 표준) — 단측 하한 병기."""
        report = aggregate(self._mixed(), edit_aware_since=self.BOUNDARY)
        assert report.approval_clean_wilson_lower == pytest.approx(wilson_lower_bound(2, 4))
        assert report.approval_clean_wilson_lower < report.approval_rate_clean

    def test_edit_codes_are_kept_separate_from_rejection_distribution(self) -> None:
        """★ F-Ⅲ 분모 보호 — 손질 코드가 반려 분포에 섞이면 12월 판정 임계가 조용히 흔들린다.

        F-Ⅲ("실패 분포에서 판단형 > 60%")의 '실패 분포'는 EOS-51 §5에서 동결된 의미다.
        여기서 F7(판단형) 손질 1건을 반려 분포에 넣으면 판단형 비중이 0%→50%로 바뀐다.
        """
        report = aggregate(self._mixed(), edit_aware_since=self.BOUNDARY)
        assert report.failure_code_counts["F2"] == 1  # 반려 축
        assert report.failure_code_counts["F7"] == 0  # 손질분은 여기 없다
        assert report.edit_failure_code_counts["F7"] == 1  # 별도 축
        # 반려 1건이 전부 기계형(F2)이므로 판단형 비중은 0 — 손질분 혼입 시 0.5가 된다.
        assert report.judgment_share == pytest.approx(0.0)
        assert report.machine_share == pytest.approx(1.0)

    def test_edit_without_code_is_counted_not_hidden(self) -> None:
        """부기는 선택 — 미기재를 0으로 위장하지 않고 센다."""
        report = aggregate(
            [
                *_reviewed_cu("cu-edited-1", 90_000, verdict="approved_with_edit"),
                *_reviewed_cu(
                    "cu-edited-2",
                    90_000,
                    verdict="approved_with_edit",
                    failure_code=GenerationFailureCode.F3,
                ),
            ],
            edit_aware_since=self.BOUNDARY,
        )
        assert report.approved_with_edit_count == 2
        assert report.edit_without_code_count == 1
        assert report.edit_failure_code_counts["F3"] == 1

    def test_no_decisions_reports_none_not_zero(self) -> None:
        """미측정 ≠ 0 — 판정 종결이 없으면 승인율은 0%가 아니라 미산출."""
        report = aggregate([start_review(cu_slug="cu-a", reviewer_id="kiki")])
        assert report.decided_count == 0
        assert report.approval_rate_clean is None
        assert report.approval_rate_including_edit is None
        assert report.approval_clean_wilson_lower is None

    def test_render_shows_both_rates(self) -> None:
        body = render_report(aggregate(self._mixed(), edit_aware_since=self.BOUNDARY))
        assert "무손질 승인율 50.0%" in body
        assert "손질 포함 승인율 **75.0%**" in body
        assert "손질 승인 1" in body

    def test_render_states_unmeasured_when_no_decision(self) -> None:
        body = render_report(aggregate([start_review(cu_slug="cu-a", reviewer_id="kiki")]))
        assert "미산출(판정 종결 0건)" in body

    def test_edit_verdict_rows_count_as_decisions_in_coverage(self) -> None:
        """★ 손질 승인이 적재율 분모에서 조용히 빠지지 않는다.

        파서가 `approved_with_edit`를 모르면 그 행은 '비판정'으로 분류돼 분모에서 사라진다 —
        측정에서 사라지는 것이 이 태스크가 없애려는 바로 그 현상이다.
        """
        report = aggregate(
            _reviewed_cu("cu-edited", 90_000, verdict="approved_with_edit"),
            verdict_rows=[
                {"slug": "cu-edited", "verdict": "approved_with_edit"},
                {"slug": "cu-pending", "review_status": "pending"},
            ],
            edit_aware_since=self.BOUNDARY,
        )
        assert report.verdict_total == 1  # 손질 승인이 판정으로 계상됐다
        assert report.verdict_non_verdict_rows == 1  # pending만 비판정
        assert report.verdict_with_timer == 1

    def test_json_output_carries_the_split(self, tmp_path: Path, capsys) -> None:
        """--json 소비자(EOS-61 스코어카드)가 두 값을 기계로 읽을 수 있어야 한다."""
        events_path = tmp_path / "events.jsonl"
        _write_events(events_path, self._mixed())
        assert (
            main(
                [
                    "--events",
                    str(events_path),
                    "--edit-aware-since",
                    self.BOUNDARY.isoformat(),
                    "--json",
                ]
            )
            == 0
        )
        payload = json.loads(capsys.readouterr().out)
        assert payload["approved_clean_count"] == 2
        assert payload["approved_with_edit_count"] == 1
        assert payload["approval_rate_clean"] == pytest.approx(0.5)
        assert payload["approval_rate_including_edit"] == pytest.approx(0.75)
        assert payload["edit_failure_code_counts"]["F7"] == 1


class TestPreRolloutApprovalAmbiguity:
    """Codex P1-a — 착지 이전 `approved`를 무손질로 계상하면 소급 재분류다.

    EOS-62 이전에는 손질을 표현할 값 자체가 없었다. 그래서 그 시절의 `approved`는 "무손질"이
    아니라 **손질 여부 미상**이다. 경계 없이 clean 버킷에 넣으면 무손질 승인율이 조용히
    과대추정되고, 그것이 정확히 acceptance ④가 금지한 소급 재분류다. `golden_benchmark`는
    같은 문제를 `--edit-aware-since`로 풀었고 이 집계기도 같은 기조를 따른다.
    """

    _BOUNDARY = _T0

    def test_without_boundary_every_approval_is_ambiguous(self) -> None:
        """★ fail-closed — 경계를 안 주면 무손질 승인율은 점값으로 나오지 않는다."""
        report = aggregate(_reviewed_cu("cu-a", 60_000, verdict="approved"))
        assert report.approved_clean_count == 0
        assert report.approved_ambiguous_count == 1
        assert report.approval_rate_clean is None
        assert report.approval_clean_wilson_lower is None
        assert report.edit_aware_boundary is None

    def test_pre_boundary_approval_is_ambiguous(self) -> None:
        report = aggregate(
            _reviewed_cu(
                "cu-old", 60_000, verdict="approved", occurred_at=self._BOUNDARY - timedelta(days=1)
            ),
            edit_aware_since=self._BOUNDARY,
        )
        assert report.approved_ambiguous_count == 1
        assert report.approved_clean_count == 0

    def test_post_boundary_approval_is_clean(self) -> None:
        report = aggregate(
            _reviewed_cu(
                "cu-new", 60_000, verdict="approved", occurred_at=self._BOUNDARY + timedelta(days=1)
            ),
            edit_aware_since=self._BOUNDARY,
        )
        assert report.approved_clean_count == 1
        assert report.approved_ambiguous_count == 0
        assert report.approval_rate_clean == pytest.approx(1.0)

    def test_ambiguity_becomes_an_interval_not_a_point(self) -> None:
        """무지는 구간으로 보고한다 — 하나의 수로 찍으면 없는 정밀도가 생긴다."""
        report = aggregate(
            [
                *_reviewed_cu(
                    "cu-old",
                    60_000,
                    verdict="approved",
                    occurred_at=self._BOUNDARY - timedelta(days=1),
                ),
                *_reviewed_cu(
                    "cu-new",
                    60_000,
                    verdict="approved",
                    occurred_at=self._BOUNDARY + timedelta(days=1),
                ),
                *_reviewed_cu(
                    "cu-rej",
                    60_000,
                    verdict="rejected",
                    failure_code=GenerationFailureCode.F1,
                    occurred_at=self._BOUNDARY + timedelta(days=1),
                ),
            ],
            edit_aware_since=self._BOUNDARY,
        )
        assert report.approval_rate_clean is None  # 점값 없음
        assert report.approval_rate_clean_lower == pytest.approx(1 / 3)  # 판별불가=전부 손질
        assert report.approval_rate_clean_upper == pytest.approx(2 / 3)  # 판별불가=전부 무손질

    def test_including_edit_rate_stays_exact_under_ambiguity(self) -> None:
        """판별불가는 '손질했는가'의 불확실이지 '승인인가'의 불확실이 아니다."""
        report = aggregate(
            [
                *_reviewed_cu("cu-a", 60_000, verdict="approved"),
                *_reviewed_cu(
                    "cu-rej", 60_000, verdict="rejected", failure_code=GenerationFailureCode.F1
                ),
            ]
        )
        assert report.approved_ambiguous_count == 1
        assert report.approval_rate_including_edit == pytest.approx(0.5)

    def test_render_states_the_interval_and_how_to_resolve_it(self) -> None:
        body = render_report(aggregate(_reviewed_cu("cu-a", 60_000, verdict="approved")))
        assert "점값 미산출" in body
        assert "--edit-aware-since" in body
        assert "소급" in body

    def test_cli_rejects_unparsable_boundary_as_measurement_failure(self, tmp_path: Path) -> None:
        """경계 인자 오류를 조용히 무시하면 사용자는 경계가 먹은 줄 안다."""
        events_path = tmp_path / "events.jsonl"
        _write_events(events_path, _reviewed_cu("cu-a", 60_000))
        assert main(["--events", str(events_path), "--edit-aware-since", "어제"]) == 1


class TestApprovalSampleRepresentativeness:
    """Codex P1-b — 승인율은 *계측된* 세션의 비율이지 전체 판정의 비율이 아니다.

    검수 UI 미결선 구간에서는 타이머 커버리지가 100% 미만인 것이 정상이다(그 사실 자체를
    적재율이 보고한다). 그때 승인 해상도를 계측 표본에서만 세면, 미계측 판정이 다른 분포를
    가질 경우 승인율이 편향된다 — 편향된 수를 전체의 비율로 읽지 못하게 리포트가 자인해야 한다.
    """

    def test_incomplete_coverage_is_flagged(self) -> None:
        """계측 2건 · 판정 10건 → 표본 불완전 표시."""
        report = aggregate(
            _reviewed_cu("cu-a", 60_000, verdict="approved"),
            verdict_rows=[{"slug": f"cu-{i}", "verdict": "approved"} for i in range(10)],
        )
        assert report.verdict_total == 10
        assert report.decided_count == 1
        assert report.approval_sample_is_complete is False

    def test_complete_coverage_is_flagged_complete(self) -> None:
        report = aggregate(
            _reviewed_cu("cu-a", 60_000, verdict="approved"),
            verdict_rows=[{"slug": "cu-a", "verdict": "approved"}],
        )
        assert report.approval_sample_is_complete is True

    def test_unknown_without_verdict_source(self) -> None:
        """판정 소스가 없으면 대표성은 '통과'가 아니라 '판별 불가'다."""
        report = aggregate(_reviewed_cu("cu-a", 60_000, verdict="approved"))
        assert report.approval_sample_is_complete is None

    def test_render_warns_on_biased_sample(self) -> None:
        body = render_report(
            aggregate(
                _reviewed_cu("cu-a", 60_000, verdict="approved"),
                verdict_rows=[{"slug": f"cu-{i}", "verdict": "approved"} for i in range(10)],
            )
        )
        assert "계측 부분표본 경고" in body
        assert "전체 판정의 비율로 읽지 말 것" in body

    def test_render_states_unknown_representativeness(self) -> None:
        body = render_report(_no_verdict_source_report())
        assert "표본 대표성 미판별" in body


def _no_verdict_source_report():
    return aggregate(_reviewed_cu("cu-a", 60_000, verdict="approved"))


# ==========================================================================
# --from-db (ADMIN-18) — DB 적재분 직접 읽기. 실 PG 실측은 api 통합 테스트가 맡고, 여기서는 CLI 배선과
# 실패 경로를 로더 대역으로 고정한다.
# ==========================================================================


class TestFromDbMode:
    @staticmethod
    def _patch_loader(
        monkeypatch: pytest.MonkeyPatch,
        events: list[ReviewTimerEvent],
        verdicts: list[dict[str, object]],
        errors: list[str] | None = None,
    ) -> None:
        async def _fake(
            *, database_url: str | None = None
        ) -> tuple[list[ReviewTimerEvent], list[str], list[dict[str, object]]]:
            return events, list(errors or []), verdicts

        monkeypatch.setattr("whymath_backend.ops.hit_cu_metrics.load_db_sources", _fake)

    def test_db_verdicts_become_the_coverage_denominator(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._patch_loader(
            monkeypatch,
            _reviewed_cu("cu-a", 60_000),
            [
                {"slug": "cu-a", "review_status": "approved"},
                {"slug": "cu-legacy", "review_status": "approved"},  # 타이머 없는 옛 판정
            ],
        )
        assert main(["--from-db", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert (payload["verdict_total"], payload["verdict_with_timer"]) == (2, 1)
        assert payload["coverage_rate"] == 0.5

    def test_explicit_verdicts_file_wins_over_db_verdicts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._patch_loader(
            monkeypatch,
            _reviewed_cu("cu-a", 60_000),
            [{"slug": "x", "review_status": "approved"}] * 5,
        )
        verdicts = tmp_path / "v.jsonl"
        _write_jsonl(verdicts, [{"slug": "cu-a", "review_status": "approved"}])
        assert main(["--from-db", "--verdicts", str(verdicts), "--json"]) == 0
        assert json.loads(capsys.readouterr().out)["verdict_total"] == 1

    def test_db_failure_is_a_measurement_failure_with_the_exception_type(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        async def _boom(*, database_url: str | None = None) -> None:
            raise ConnectionRefusedError("db down")

        monkeypatch.setattr("whymath_backend.ops.hit_cu_metrics.load_db_sources", _boom)
        assert main(["--from-db"]) == 1
        err = capsys.readouterr().err
        assert "ConnectionRefusedError" in err and "측정 실패" in err

    def test_empty_db_is_a_measurement_failure_not_zero_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_loader(monkeypatch, [], [])
        assert main(["--from-db"]) == 1

    def test_db_row_validation_failures_block_the_gate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """깨진 DB 행이 있으면 부분 입력으로 통과시키지 않는다(파일 입력과 같은 규율)."""
        self._patch_loader(
            monkeypatch, _reviewed_cu("cu-a", 60_000), [], errors=["db row 1: ValidationError"]
        )
        assert main(["--from-db"]) == 1

    def test_requires_a_source(self) -> None:
        with pytest.raises(SystemExit) as info:
            main([])
        assert info.value.code == 2
