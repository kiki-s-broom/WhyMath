"""배치 안전장치(batch_safety) 단위테스트 — 카나리 게이트 · 롤링 불량률 중단 (EOS-95).

**이 파일의 목적은 "초록을 확인하는 것"이 아니라 "실패 상태에서 실제로 실패하는지"다**
(CLAUDE.md 2026-09-01 — 보호 장치를 실패 주입 없이 "보호 있음"으로 선언 금지). 그래서
모든 판정 테스트가 **통과 조건과 탈락 조건을 쌍으로** 확인하고, 경계값에서 부등호 방향이
뒤집히면 깨지도록 짰다(뮤테이션 검출).
"""

from __future__ import annotations

import pytest

from whymath_backend.harness.batch_safety import (
    ACCEPTED_STATUSES,
    DEFAULT_ABORT_MIN_SAMPLES,
    DEFAULT_ABORT_THRESHOLD,
    DEFAULT_ABORT_WINDOW,
    DEFAULT_CANARY_CONFIDENCE,
    DEFAULT_CANARY_SIZE,
    DEFAULT_CANARY_THRESHOLD,
    NEUTRAL_STATUSES,
    RollingFailureWindow,
    evaluate_canary,
    is_accepted_status,
    is_neutral_status,
)
from whymath_backend.harness.wilson import wilson_lower_bound


def _statuses(successes: int, failures: int) -> list[str]:
    return ["accepted_stored"] * successes + ["rejected_gate"] * failures


class TestAcceptedStatus:
    def test_accepted_set_is_allowlist(self) -> None:
        assert ACCEPTED_STATUSES == frozenset({"accepted_stored", "accepted"})

    @pytest.mark.parametrize("status", sorted(ACCEPTED_STATUSES))
    def test_accepted_statuses_pass(self, status: str) -> None:
        assert is_accepted_status(status) is True

    @pytest.mark.parametrize(
        "status",
        ["rejected_gate", "rejected_duplicate", "generation_failed", "needs_review", ""],
    )
    def test_non_accepted_statuses_fail(self, status: str) -> None:
        assert is_accepted_status(status) is False

    def test_unknown_status_is_not_accepted(self) -> None:
        """새 status가 생겨도 자동으로 성공에 들지 않는다(fail-closed 허용목록)."""
        assert is_accepted_status("accepted_but_totally_new_variant") is False


class TestNeutralStatuses:
    """중립 status — 성공도 불량도 아니라 분모에서 통째로 빠진다."""

    def test_duplicate_is_neutral(self) -> None:
        assert NEUTRAL_STATUSES == frozenset({"rejected_duplicate"})
        assert is_neutral_status("rejected_duplicate") is True
        assert is_accepted_status("rejected_duplicate") is False

    @pytest.mark.parametrize("status", ["rejected_gate", "generation_failed", "accepted_stored"])
    def test_others_are_not_neutral(self, status: str) -> None:
        assert is_neutral_status(status) is False

    def test_canary_excludes_neutral_from_denominator(self) -> None:
        """중복 10 + 수용 2 → 2/2 판정이지 2/12가 아니다."""
        verdict = evaluate_canary(["rejected_duplicate"] * 10 + ["accepted_stored"] * 2)
        assert verdict.trials == 2
        assert verdict.successes == 2

    def test_all_neutral_is_measurement_failure_not_pass(self) -> None:
        """전건 중복이면 판정 대상이 0건 — 통과가 아니라 측정 실패다."""
        verdict = evaluate_canary(["rejected_duplicate"] * 30)
        assert verdict.measurement_failed is True
        assert verdict.passed is False

    def test_rolling_skips_neutral_observations(self) -> None:
        win = RollingFailureWindow(window=4, threshold=0.30, min_samples=4)
        for _ in range(10):
            assert win.observe_status("rejected_duplicate") is False
        assert win.observed == 0  # 관측 자체를 안 했다
        assert win.should_abort() is False
        # 실제 불량은 정상적으로 관측된다
        for _ in range(4):
            assert win.observe_status("generation_failed") is True
        assert win.should_abort() is True


class TestAbortMinSamples:
    """판정 시작점이 창 크기와 분리돼 있는가 — 기본 경로 무판정 사고의 회귀 가드."""

    def test_default_min_samples_is_independent_of_window(self) -> None:
        win = RollingFailureWindow()  # 기본 창 50
        assert win.window_size == DEFAULT_ABORT_WINDOW
        # 창 50인데 50건을 기다리면 CLI 기본 --n 20이 통째로 무판정이 된다.
        for _ in range(DEFAULT_ABORT_MIN_SAMPLES):
            win.observe(failed=True)
        assert win.should_abort() is True, "기본 창에서 최소 표본에 도달했는데 판정하지 않는다"

    def test_min_samples_never_exceeds_window(self) -> None:
        """창이 최소 표본보다 작으면 창 크기가 시작점이다(도달 불가 방지)."""
        win = RollingFailureWindow(window=3, threshold=0.30)
        for _ in range(3):
            win.observe(failed=True)
        assert win.should_abort() is True


class TestCanaryDefaults:
    """기본값이 바뀌면 모듈 docstring의 실측 표도 함께 갱신해야 한다 — 그 계약을 동결한다."""

    def test_defaults_are_the_kiki_decision(self) -> None:
        assert DEFAULT_CANARY_SIZE == 30
        assert DEFAULT_CANARY_THRESHOLD == 0.90
        assert DEFAULT_CANARY_CONFIDENCE == 0.95


class TestCanaryWilsonArithmetic:
    """설계서 임계 0.95가 왜 만족 불가능했는지를 수치로 동결한다(EOS-95 ② 근거)."""

    def test_perfect_canary_wilson_lower_is_below_095(self) -> None:
        lower = wilson_lower_bound(30, 30, 0.95)
        assert 0.916 < lower < 0.918, lower
        # 만점인데도 0.95에 못 미친다 — 설계서 명세가 만족 불가능했던 이유.
        assert lower < 0.95

    def test_perfect_canary_passes_090_but_not_095(self) -> None:
        statuses = _statuses(30, 0)
        assert evaluate_canary(statuses, threshold=0.90).passed is True
        assert evaluate_canary(statuses, threshold=0.95).passed is False

    def test_one_miss_out_of_thirty_fails_090(self) -> None:
        """임계 0.90은 관대한 값이 아니다 — 29/30(하한 86.4%)은 탈락한다."""
        verdict = evaluate_canary(_statuses(29, 1), threshold=0.90)
        assert verdict.passed is False
        assert 0.863 < verdict.wilson_lower < 0.866, verdict.wilson_lower
        # 점추정으로 판정했다면 96.7%라 통과했을 것이다 — 판정축이 점추정이 아님을 못박는다.
        assert verdict.point_estimate > 0.96

    def test_sixty_perfect_passes_095(self) -> None:
        """참값 95% 입증에 n≥60이 필요하다는 계산의 반대 방향 확인."""
        assert evaluate_canary(_statuses(60, 0), threshold=0.95).passed is True


class TestCanaryVerdict:
    def test_zero_trials_is_measurement_failure_not_pass(self) -> None:
        """시도 0건은 '불량 0% 통과'가 아니다(CLAUDE.md 2026-08-22)."""
        verdict = evaluate_canary([])
        assert verdict.passed is False
        assert verdict.measurement_failed is True
        assert verdict.trials == 0
        assert "측정 실패" in verdict.reason

    def test_all_failed_canary_blocks(self) -> None:
        verdict = evaluate_canary(_statuses(0, 30))
        assert verdict.passed is False
        assert verdict.measurement_failed is False  # 측정은 됐다 — 결과가 나빴을 뿐
        assert verdict.successes == 0

    def test_verdict_carries_evidence_not_just_boolean(self) -> None:
        """passed만 남기면 왜 막혔는지가 사라진다 — 근거 수치가 전부 실려야 한다."""
        payload = evaluate_canary(_statuses(25, 5), threshold=0.90).to_json()
        for key in (
            "passed",
            "trials",
            "successes",
            "point_estimate",
            "wilson_lower",
            "threshold",
            "confidence",
            "measurement_failed",
            "reason",
        ):
            assert key in payload, key
        assert payload["trials"] == 30
        assert payload["successes"] == 25

    def test_threshold_boundary_uses_ge_not_gt(self) -> None:
        """하한이 임계와 '같을 때' 통과다 — 부등호를 > 로 바꾸면 이 테스트가 깨진다."""
        statuses = _statuses(30, 0)
        exact = wilson_lower_bound(30, 30, 0.95)
        assert evaluate_canary(statuses, threshold=exact).passed is True
        # 임계를 아주 조금만 올리면 즉시 탈락 — 경계가 실제로 판정에 쓰인다는 증거.
        assert evaluate_canary(statuses, threshold=exact + 1e-9).passed is False

    def test_accepted_alias_counts_as_success(self) -> None:
        verdict = evaluate_canary(["accepted"] * 30)
        assert verdict.successes == 30


class TestRollingFailureWindowGuards:
    @pytest.mark.parametrize("window", [0, -1])
    def test_non_positive_window_rejected(self, window: int) -> None:
        with pytest.raises(ValueError):
            RollingFailureWindow(window=window)

    @pytest.mark.parametrize("threshold", [-0.01, 1.01])
    def test_threshold_out_of_range_rejected(self, threshold: float) -> None:
        with pytest.raises(ValueError):
            RollingFailureWindow(threshold=threshold)

    def test_defaults(self) -> None:
        win = RollingFailureWindow()
        assert win.window_size == DEFAULT_ABORT_WINDOW
        assert win.threshold == DEFAULT_ABORT_THRESHOLD


class TestRollingFailureWindowJudgement:
    def test_does_not_abort_before_window_is_full(self) -> None:
        """첫 1건이 불량이어도 멈추지 않는다 — 창이 차기 전 판정은 소음이다."""
        win = RollingFailureWindow(window=10, threshold=0.30)
        win.observe(failed=True)
        assert win.rate() == 1.0  # 순간 비율은 100%지만
        assert win.should_abort() is False  # 판정은 하지 않는다

    def test_aborts_when_full_window_exceeds_threshold(self) -> None:
        win = RollingFailureWindow(window=10, threshold=0.30)
        for _ in range(4):
            win.observe(failed=True)
        for _ in range(6):
            win.observe(failed=False)
        assert win.rate() == pytest.approx(0.4)
        assert win.should_abort() is True

    def test_clean_full_window_does_not_abort(self) -> None:
        """정상 배치는 멈추지 않는다 — 상시 참인 가드는 보호가 아니다."""
        win = RollingFailureWindow(window=10, threshold=0.30)
        for _ in range(10):
            win.observe(failed=False)
        assert win.should_abort() is False

    def test_threshold_is_strict_greater_not_ge(self) -> None:
        """비율이 임계와 '같으면' 멈추지 않는다 — >= 로 바꾸면 이 테스트가 깨진다."""
        win = RollingFailureWindow(window=10, threshold=0.30)
        # 정상 7건을 **먼저** 넣는다 — 다음 관측에서 밀려나는 것이 정상이어야 비율이 오른다.
        for _ in range(7):
            win.observe(failed=False)
        for _ in range(3):
            win.observe(failed=True)
        assert win.rate() == pytest.approx(0.3)
        assert win.should_abort() is False  # 같음은 초과가 아니다
        # 한 건 더 불량 → 가장 오래된 *정상*이 밀려나 4/10 = 40% > 30% → 중단
        win.observe(failed=True)
        assert win.rate() == pytest.approx(0.4)
        assert win.should_abort() is True

    def test_window_slides_and_recovers(self) -> None:
        """옛 불량이 창 밖으로 밀려나면 판정도 회복된다 — 누적이 아니라 '최근'을 본다."""
        win = RollingFailureWindow(window=5, threshold=0.30)
        for _ in range(5):
            win.observe(failed=True)
        assert win.should_abort() is True
        for _ in range(5):
            win.observe(failed=False)
        assert win.rate() == 0.0
        assert win.should_abort() is False
        # 창 밖으로 밀려나도 누적 집계는 정직하게 남는다(리포트용).
        assert win.failures_total == 5
        assert win.observed == 10

    def test_observe_status_maps_non_accepted_to_failure(self) -> None:
        win = RollingFailureWindow(window=4, threshold=0.30)
        win.observe_status("accepted_stored")
        win.observe_status("accepted")
        win.observe_status("rejected_gate")
        win.observe_status("generation_failed")
        assert win.rate() == pytest.approx(0.5)
        assert win.should_abort() is True

    def test_min_samples_override_allows_early_judgement(self) -> None:
        win = RollingFailureWindow(window=50, threshold=0.30, min_samples=2)
        win.observe(failed=True)
        assert win.should_abort() is False  # 아직 1건
        win.observe(failed=True)
        assert win.should_abort() is True  # min_samples 도달

    def test_abort_reason_carries_numbers(self) -> None:
        """조용한 중단 금지 — 사유에 관측 비율·창 크기·임계가 전부 있어야 한다."""
        win = RollingFailureWindow(window=4, threshold=0.30)
        for _ in range(4):
            win.observe(failed=True)
        reason = win.abort_reason()
        assert "100.0%" in reason
        assert "30%" in reason
        assert "4" in reason

    def test_to_json_reports_even_without_abort(self) -> None:
        """중단이 없어도 감시가 돌았다는 작동 신호가 남는다(작동한 비율 원칙)."""
        win = RollingFailureWindow(window=3, threshold=0.30)
        for _ in range(3):
            win.observe(failed=False)
        payload = win.to_json()
        assert payload["observed"] == 3
        assert payload["failures_total"] == 0
        assert payload["current_rate"] == 0.0
        assert payload["threshold"] == 0.30
