"""루프 KPI ①②④ 판정 표본 산출 경로(EOS-38) — hermetic 단위 테스트(DB 불요).

실 DB 위의 변별력(위반 주입 → FAIL · 정상 대조군 → PASS)은
`test_loop_kpi_sample_path_integration.py`가 잰다. 여기서는 DB 없이 지킬 수 있는 계약만 동결한다:

  · 최소 표본이 임계에서 **계산**된다(52·268을 상수로 적지 않는다).
  · 전용 DB 가드가 실DB 이름을 거부한다 — 이름 검사는 fail-closed다.
  · 표본 성격 표지(`--sample-basis`)가 판정 숫자를 바꾸지 않고 산출물에만 각인된다.
  · 이 모듈은 학습자를 **지우지 않는다**(판정 4회 공전의 원인이 판정 하네스의 자기 삭제였다).
"""

from __future__ import annotations

import ast
import inspect
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from whymath_backend.harness.wilson import wilson_lower_bound, wilson_upper_bound
from whymath_backend.ops import loop_kpi_gate as gate
from whymath_backend.ops import loop_kpi_sample_load as load


class TestRequiredSampleSizes:
    def test_minimums_are_the_numbers_the_judgment_record_cites(self) -> None:
        """EOS-141 판정문 §5의 52·268과 같아야 한다 — 계산이 어긋나면 기록과 코드가 갈라진다."""
        needed = load.required_sample_sizes()
        assert needed.loop_completion_sessions == 52
        assert needed.state_integrity_rows == 268

    def test_minimum_is_the_first_passing_sample_not_merely_a_passing_one(self) -> None:
        """경계 양쪽 — 최소치는 통과하고 한 건 모자라면 통과하지 못한다(공허한 최소치 방지)."""
        needed = load.required_sample_sizes()
        n1, n2 = needed.loop_completion_sessions, needed.state_integrity_rows
        loop = gate.spec_for(gate.LoopKpi.LOOP_COMPLETION)
        integrity = gate.spec_for(gate.LoopKpi.STATE_INTEGRITY)
        assert wilson_lower_bound(n1, n1, gate.CONFIDENCE) >= loop.threshold
        assert wilson_lower_bound(n1 - 1, n1 - 1, gate.CONFIDENCE) < loop.threshold
        assert wilson_upper_bound(0, n2, gate.CONFIDENCE) <= integrity.threshold
        assert wilson_upper_bound(0, n2 - 1, gate.CONFIDENCE) > integrity.threshold

    def test_default_load_clears_the_minimum_with_margin(self) -> None:
        """기본 학습자 수는 최소치 위여야 한다 — 최소치 그대로면 한 건 어긋나도 FAIL이다."""
        default = load.required_sample_sizes().loop_completion_sessions + load._DEFAULT_MARGIN
        assert default > load.required_sample_sizes().loop_completion_sessions
        assert (
            wilson_lower_bound(default, default, gate.CONFIDENCE)
            >= gate.spec_for(gate.LoopKpi.LOOP_COMPLETION).threshold
        )

    def test_load_yields_enough_integrity_rows_for_the_default_learner_count(self) -> None:
        """② 분모는 attempt_event다 — 학습자당 이벤트 수 × 기본 학습자 수가 268을 넘어야 한다.

        시도 3건이 `문제시도`를 남기고 조작 이벤트가 `_INTERACTIONS_PER_LEARNER`건이다.
        (실측: 60명 → attempt_event 540건 · 스캔 분모 542.)
        """
        per_learner = 3 + load._INTERACTIONS_PER_LEARNER
        learners = load.required_sample_sizes().loop_completion_sessions + load._DEFAULT_MARGIN
        assert per_learner * learners >= load.required_sample_sizes().state_integrity_rows


class TestDedicatedDatabaseGuard:
    @pytest.mark.parametrize(
        "url",
        [
            "postgresql+asyncpg://whymath@127.0.0.1:5432/whymath_kpi_sample",
            "postgresql+asyncpg://u:p@db.internal:5433/whymath_ci_ab12_kpi_sample",
        ],
    )
    def test_dedicated_names_pass(self, url: str) -> None:
        assert load.assert_dedicated_database_name(url).endswith(load.SAMPLE_DB_SUFFIX)

    @pytest.mark.parametrize(
        "url",
        [
            "postgresql+asyncpg://whymath@127.0.0.1:5432/whymath",  # 운영·개발 기본 DB
            "postgresql+asyncpg://whymath@127.0.0.1:5433/whymath_kpi_sample_old",  # 접미가 아니다
            "postgresql+asyncpg://whymath@127.0.0.1:5432/kpi_sample_whymath",  # 접두는 아니다
            "postgresql+asyncpg://whymath@127.0.0.1:5432/",  # 이름 없음
            "postgresql+asyncpg://whymath@127.0.0.1:5432",  # 이름 없음
        ],
    )
    def test_everything_else_is_refused(self, url: str) -> None:
        with pytest.raises(load.DedicatedDatabaseError):
            load.assert_dedicated_database_name(url)

    def test_refusal_happens_before_any_work(self) -> None:
        """실DB 이름이면 연결 시도 이전에 거부된다 — 존재하지 않는 호스트로도 같은 예외여야 한다."""
        with pytest.raises(load.DedicatedDatabaseError):
            load.run_load(1, database_url="postgresql+asyncpg://x@does-not-exist.invalid:1/whymath")

    def test_cli_exit_3_on_refusal(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv(
            "WHYMATH_DATABASE_URL", "postgresql+asyncpg://whymath@127.0.0.1:5432/whymath"
        )
        assert load.main(["--learners", "1"]) == 3
        assert "거부" in capsys.readouterr().err

    def test_synthetic_email_domain_is_reserved_tld(self) -> None:
        """`.invalid`는 RFC 2606 예약 — 합성 학습자 주소가 실주소와 겹치지 않는다."""
        assert load.SYNTHETIC_EMAIL_DOMAIN.endswith(".invalid")
        assert load.synthetic_email(7).endswith("@" + load.SYNTHETIC_EMAIL_DOMAIN)
        assert load.synthetic_email(7) != load.synthetic_email(8)


def _report(basis: str | None) -> gate.LoopKpiReport:
    now = datetime.now(UTC)
    window = gate.ObservationWindow(start=now - timedelta(hours=1), end=now)
    observations = {
        gate.LoopKpi.LOOP_COMPLETION: gate.Observation(
            kpi=gate.LoopKpi.LOOP_COMPLETION, numerator=60, denominator=60, source="t"
        )
    }
    if basis is None:
        return gate.evaluate(observations, window=window, run_id="t")
    return gate.evaluate(observations, window=window, run_id="t", sample_basis=basis)


class TestSampleBasisLabel:
    def test_default_is_live(self) -> None:
        assert _report(None).sample_basis == gate.SAMPLE_BASIS_LIVE

    def test_label_does_not_change_any_verdict_or_number(self) -> None:
        """표지는 라벨이다 — 판정·분자·분모가 live와 한 글자도 다르면 안 된다(규칙의 이원화 금지)."""
        live = _report(gate.SAMPLE_BASIS_LIVE).as_dict()
        synthetic = _report(gate.SAMPLE_BASIS_SYNTHETIC).as_dict()
        assert live["kpis"] == synthetic["kpis"]
        assert live["counts"] == synthetic["counts"]
        assert live["exit_code"] == synthetic["exit_code"]

    def test_synthetic_is_stamped_in_json_and_text(self) -> None:
        report = _report(gate.SAMPLE_BASIS_SYNTHETIC)
        assert report.as_dict()["sample_basis"] == "synthetic"
        text = gate.render(report)
        assert "synthetic" in text
        assert "실사용 검증으로 계상하지 않는다" in text

    def test_live_report_carries_no_synthetic_disclaimer(self) -> None:
        """실사용 판정에 합성 경고가 붙으면 경고가 소음이 된다 — 변별해야 한다."""
        text = gate.render(_report(gate.SAMPLE_BASIS_LIVE))
        assert "실사용 검증으로 계상하지 않는다" not in text

    def test_unknown_basis_is_rejected_not_defaulted_to_live(self) -> None:
        """오타가 `live`로 위장되면 합성 표본 판정이 실사용 판정으로 읽힌다."""
        with pytest.raises(ValueError):
            _report("syntetic")

    def test_cli_stamps_basis_into_the_json_file(self, tmp_path: Path) -> None:
        out = tmp_path / "r.json"
        code = gate.main(["--no-db", "--sample-basis", "synthetic", "--json", str(out)])
        assert code == gate.EXIT_UNMEASURED  # 관측치 없음 → 전부 미측정(표지와 무관)
        assert json.loads(out.read_text(encoding="utf-8"))["sample_basis"] == "synthetic"

    def test_cli_rejects_unknown_basis(self) -> None:
        with pytest.raises(SystemExit):
            gate.main(["--no-db", "--sample-basis", "real"])


def _deletes_anything(source: str) -> list[str]:
    """모듈 소스에서 **삭제 호출**을 찾는다 — docstring 속 설명은 세지 않는다(AST 기반)."""
    tree = ast.parse(source)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            # 정확한 이름이 아니라 부분 문자열 — `_exec_delete`·`erase_all` 같은 변형이 빠져나가지 못한다.
            if "delete" in name.lower() or "erase" in name.lower():
                found.append(f"호출 {name}()")
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value.strip().upper()
            if value == "DELETE" or value.startswith("DELETE FROM") or "DELETE_MY_ACCOUNT" in value:
                found.append(f"문자열 {node.value[:30]!r}")
    # 모듈 docstring은 제외 — 설명이 아니라 실행 경로를 본다.
    return [f for f in found if "DELETE /v1/me" not in f]


class TestTheLoadNeverDeletes:
    def test_module_source_has_no_delete_path(self) -> None:
        """삭제하지 않는다 — 판정 하네스가 스스로 지운 데이터 위에서 4회 공전했던 원인의 부정."""
        assert _deletes_anything(inspect.getsource(load)) == []

    def test_the_detector_is_discriminating(self) -> None:
        """부정 대조군 — 삭제 경로가 *있는* 소스에서는 탐지기가 실제로 걸려야 한다."""
        assert _deletes_anything('client.request("DELETE", "/v1/me")')
        assert _deletes_anything('conn.execute(text("DELETE FROM learning_session"))')
        assert _deletes_anything("client.delete('/v1/me')")
        assert _deletes_anything("privacy.erase_user(session, uid)")
        assert _deletes_anything("erase_user(session, uid)")
        assert _deletes_anything("asyncio.run(_exec_delete(url))")  # 이름 변형 — 부분 일치
        assert _deletes_anything("await erase_all_learners(url)")


class TestInsufficientSampleIsNotRelabelledUnmeasured:
    """(다) "표본 부족 FAIL은 미측정과 같게 계상"을 채택하지 않은 이유의 실증(결정적·DB 불요).

    표본이 모자란 측정은 **위반(FAIL)**이고 분모 0은 **미측정**이다 — 두 상태는 exit code도 다르다
    (1 vs 2). 이 경로는 FAIL을 미측정으로 바꾸지 않고 표본을 *쌓아서* 해결한다.
    """

    @staticmethod
    def _verdict(kpi: gate.LoopKpi, num: int, den: int) -> gate.KpiVerdict:
        now = datetime.now(UTC)
        window = gate.ObservationWindow(start=now - timedelta(hours=1), end=now)
        report = gate.evaluate(
            {kpi: gate.Observation(kpi=kpi, numerator=num, denominator=den, source="t")},
            window=window,
            run_id="t",
        )
        return next(o.verdict for o in report.outcomes if o.kpi is kpi)

    def test_one_success_in_one_is_a_failure_not_unmeasured(self) -> None:
        assert self._verdict(gate.LoopKpi.LOOP_COMPLETION, 1, 1) is gate.KpiVerdict.failed

    def test_zero_violations_in_twelve_rows_is_a_failure_not_unmeasured(self) -> None:
        assert self._verdict(gate.LoopKpi.STATE_INTEGRITY, 0, 12) is gate.KpiVerdict.failed

    def test_empty_denominator_is_unmeasured_and_is_a_different_state(self) -> None:
        assert self._verdict(gate.LoopKpi.LOOP_COMPLETION, 0, 0) is gate.KpiVerdict.unmeasured
        assert gate.EXIT_VIOLATION != gate.EXIT_UNMEASURED

    def test_the_minimum_turns_both_into_passes(self) -> None:
        needed = load.required_sample_sizes()
        n1, n2 = needed.loop_completion_sessions, needed.state_integrity_rows
        assert self._verdict(gate.LoopKpi.LOOP_COMPLETION, n1, n1) is gate.KpiVerdict.passed
        assert self._verdict(gate.LoopKpi.STATE_INTEGRITY, 0, n2) is gate.KpiVerdict.passed
        assert self._verdict(gate.LoopKpi.LOOP_COMPLETION, n1 - 1, n1 - 1) is gate.KpiVerdict.failed
