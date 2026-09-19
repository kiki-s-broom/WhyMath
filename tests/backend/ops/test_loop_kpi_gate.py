"""Phase 2 학습 루프 KPI 5종 게이트(`ops/loop_kpi_gate.py`, EOS-15) — 주입 검증 스위트.

이 파일의 중심은 **"정상 입력에서 초록"이 아니라 "위반을 주입하면 빨강"**이다(CLAUDE.md
「보호 장치를 실패 주입 없이 '보호 있음'으로 선언 금지」). 그래서 5종 각각에 대해
① 목표를 충족하는 관측치 ② 목표를 깨뜨리는 관측치를 **쌍으로** 넣고 판정이 뒤집히는지 본다 —
성공 방향 대조군이 없으면 "전부 fail로 계상"이라는 과잉 수정이 통과하기 때문이다.

구조적 선결(①⑤)은 값 주입으로는 뒤집히지 않는다. 그 축의 주입은 **원천 대장 자체를 바꾸는
것**이며(`source_registry` 몽키패치), 그래야 "세션 writer가 배선되면 자동으로 측정이 시작된다"는
설계 주장이 검증된다 — 주장만 적고 검증하지 않으면 그 문장이 위장이 된다.

실 DB 왕복은 이 파일이 다루지 않는다(`main(... --no-db)`·수집기 직접 호출 시 가짜 세션).
실 PostgreSQL 대상 수집 변별력은 별도 통합 좌석의 몫이며, 그 사실을 여기 적어 둔다.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.l2 import learning_event_trace as trace
from whymath_backend.ops import loop_kpi_gate as gate

# ──────────────────────────────────────────────────────────────────────────
# 픽스처
# ──────────────────────────────────────────────────────────────────────────
_NOW = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
_WINDOW = gate.ObservationWindow(start=_NOW - timedelta(hours=24), end=_NOW)


def _obs(kpi: gate.LoopKpi, numerator: int | None, denominator: int | None) -> gate.Observation:
    return gate.Observation(kpi=kpi, numerator=numerator, denominator=denominator, source="test")


def _evaluate_one(observation: gate.Observation) -> gate.KpiOutcome:
    report = gate.evaluate({observation.kpi: observation}, window=_WINDOW, run_id="test")
    return next(o for o in report.outcomes if o.kpi is observation.kpi)


def _all_produced_registry() -> tuple[trace.SourceCoverage, ...]:
    """모든 원천이 `PRODUCED`인 대장 — '배선되면 측정이 시작된다'를 검증하는 주입."""
    return tuple(
        c.model_copy(update={"availability": trace.SourceAvailability.PRODUCED})
        for c in trace.source_registry()
    )


# ──────────────────────────────────────────────────────────────────────────
# 계약·정본 경계 (acceptance ④)
# ──────────────────────────────────────────────────────────────────────────
def test_every_kpi_has_a_spec_with_numerator_denominator_and_seat() -> None:
    """5종 전부가 분자·분모·출처·좌석을 갖는다 — 하나라도 비면 '정의된 KPI'가 아니다."""
    assert {s.kpi for s in gate.LOOP_KPI_SPECS} == set(gate.LoopKpi)
    assert len(gate.LOOP_KPI_SPECS) == 5
    for spec in gate.LOOP_KPI_SPECS:
        assert spec.numerator_def.strip(), spec.kpi
        assert spec.denominator_def.strip(), spec.kpi
        assert spec.source.strip(), spec.kpi
        assert spec.seat_task.strip(), spec.kpi
        assert spec.title.strip(), spec.kpi


def test_axis_is_disjoint_from_validation_scorecard() -> None:
    """루프 KPI 5종과 콘텐츠 생산 KPI 12종은 **다른 축**이다 — 이름이 겹치면 정본이 둘이 된다.

    겹침이 생기는 순간 "KPI 17종"이라는 하나의 표가 만들어지고, 그 평균이 루프 붕괴를 덮는다.
    """
    from whymath_backend.ops import validation_scorecard

    scorecard_names = {s.kpi for s in validation_scorecard.KPI_SOURCES}
    scorecard_keys = {s.payload_key for s in validation_scorecard.KPI_SOURCES}
    loop_names = {s.title for s in gate.LOOP_KPI_SPECS}
    loop_keys = {k.value for k in gate.LoopKpi}
    assert scorecard_names.isdisjoint(loop_names)
    assert scorecard_keys.isdisjoint(loop_keys)


def test_gate_module_does_not_import_the_scorecard_canon() -> None:
    """경계는 산문이 아니라 의존 방향으로 지킨다 — 한쪽이 다른 쪽을 부르면 두 축이 붙는다."""
    source = Path(gate.__file__).read_text(encoding="utf-8")
    assert "import validation_scorecard" not in source
    assert "from whymath_backend.ops.validation_scorecard" not in source


def test_judgment_path_has_no_external_observability_dependency() -> None:
    """판정치를 외부 관측 SaaS에 의존시키지 않는다(인프로세스 이중 회계 — CLAUDE.md 금기).

    그 인프라가 죽으면 "측정 실패"가 보여야지 "0건 통과"로 위장되면 안 된다. 산출물도 그
    사실을 스스로 말한다.
    """
    source = Path(gate.__file__).read_text(encoding="utf-8")
    for forbidden in ("import langfuse", "from langfuse", "opentelemetry"):
        assert forbidden not in source, forbidden
    report = gate.evaluate({}, window=_WINDOW, run_id="test")
    assert report.as_dict()["accounting"] == {
        "in_process": True,
        "external_observability_dependency": None,
    }


# ──────────────────────────────────────────────────────────────────────────
# 미측정은 통과가 아니다 (설계 규칙 1)
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("kpi", list(gate.LoopKpi))
def test_zero_denominator_is_unmeasured_not_a_pass(kpi: gate.LoopKpi) -> None:
    """분모 0에서 "위반 0건 → 100% 달성"을 만들지 않는다 — 이 모듈이 존재하는 이유의 절반."""
    outcome = _evaluate_one(_obs(kpi, 0, 0))
    assert outcome.verdict is gate.KpiVerdict.unmeasured
    assert outcome.observed is None
    assert "분모가 0" in outcome.reason


def test_missing_observation_is_counted_as_unmeasured_not_dropped() -> None:
    """관측치를 내지 않은 KPI가 표에서 조용히 사라지면 '5종을 봤다'가 거짓이 된다."""
    report = gate.evaluate({}, window=_WINDOW, run_id="test")
    assert len(report.outcomes) == 5
    assert len(report.unmeasured) == 5
    assert report.exit_code == gate.EXIT_UNMEASURED


def test_impossible_ratio_is_unmeasured_not_a_pass() -> None:
    """분자>분모는 수집기 결함이다 — 비율로 접어 판정하면 결함이 통과로 위장된다."""
    outcome = _evaluate_one(_obs(gate.LoopKpi.STATE_INTEGRITY, 5, 3))
    assert outcome.verdict is gate.KpiVerdict.unmeasured
    assert "성립하지 않는다" in outcome.reason


def test_explicit_unmeasured_reason_wins_over_numbers() -> None:
    """수집기가 '못 쟀다'고 말하면 곁들여 온 숫자로 판정하지 않는다."""
    outcome = _evaluate_one(
        gate.Observation(
            kpi=gate.LoopKpi.EXPLAINABILITY,
            numerator=0,
            denominator=100,
            unmeasured_reason="수집 실패(OperationalError) — 판정 불가.",
            source="error",
            error_type="OperationalError",
        )
    )
    assert outcome.verdict is gate.KpiVerdict.unmeasured
    assert outcome.error_type == "OperationalError"


# ──────────────────────────────────────────────────────────────────────────
# 주입 검증 — 5종 각각이 위반에 반응한다 (완료 판정의 핵심)
# ──────────────────────────────────────────────────────────────────────────
#: (KPI, 충족 관측치, 위반 관측치). 위반값은 **그 KPI의 임계를 실제로 넘는** 값이어야 한다 —
#: 아슬아슬하지 않은 값을 쓰면 임계를 잘못 걸어도 테스트가 통과한다.
_INJECTION_PAIRS: tuple[tuple[gate.LoopKpi, tuple[int, int], tuple[int, int]], ...] = (
    # ① 비율 하한 — 1000건 중 990건 도달(하한 ≈0.982)은 통과, 900건(하한 ≈0.881)은 미달.
    (gate.LoopKpi.LOOP_COMPLETION, (990, 1000), (900, 1000)),
    # ② 비율 상한 — 10000건 중 위반 10건(상한 ≈0.0019)은 통과, 300건(상한 ≈0.034)은 미달.
    (gate.LoopKpi.STATE_INTEGRITY, (10, 10000), (300, 10000)),
    # ③④⑤ 무관용 — 1건이면 미달이다.
    (gate.LoopKpi.EXPLAINABILITY, (0, 500), (1, 500)),
    (gate.LoopKpi.MANUAL_INTERVENTION, (0, 500), (1, 500)),
    (gate.LoopKpi.TRACEABILITY, (0, 500), (1, 500)),
)


@pytest.mark.parametrize(("kpi", "clean", "dirty"), _INJECTION_PAIRS)
def test_each_kpi_flips_when_a_violation_is_injected(
    kpi: gate.LoopKpi, clean: tuple[int, int], dirty: tuple[int, int]
) -> None:
    """정상 → PASS, 위반 주입 → FAIL. 둘 다 확인해야 계측기라고 부를 수 있다."""
    passed = _evaluate_one(_obs(kpi, *clean))
    assert passed.verdict is gate.KpiVerdict.passed, (kpi, passed.reason)

    failed = _evaluate_one(_obs(kpi, *dirty))
    assert failed.verdict is gate.KpiVerdict.failed, (kpi, failed.reason)


def test_injection_moves_the_whole_report_exit_code() -> None:
    """한 종의 위반이 5종 표 전체의 exit code를 1로 끌어내린다(위반 우선)."""
    clean = {kpi: _obs(kpi, *c) for kpi, c, _ in _INJECTION_PAIRS}
    assert gate.evaluate(clean, window=_WINDOW, run_id="t").exit_code == gate.EXIT_OK

    for kpi, _, dirty in _INJECTION_PAIRS:
        injected = dict(clean)
        injected[kpi] = _obs(kpi, *dirty)
        report = gate.evaluate(injected, window=_WINDOW, run_id="t")
        assert report.exit_code == gate.EXIT_VIOLATION, kpi
        assert {o.kpi for o in report.failed} == {kpi}


def test_violation_outranks_unmeasured_in_the_exit_code() -> None:
    """위반과 미측정이 함께 있으면 위반이 이긴다 — 확정된 미달이 더 시급하다."""
    mixed = {
        gate.LoopKpi.EXPLAINABILITY: _obs(gate.LoopKpi.EXPLAINABILITY, 1, 500),
        gate.LoopKpi.STATE_INTEGRITY: _obs(gate.LoopKpi.STATE_INTEGRITY, 0, 0),
    }
    report = gate.evaluate(mixed, window=_WINDOW, run_id="t")
    assert report.exit_code == gate.EXIT_VIOLATION
    assert report.failed and report.unmeasured


# ──────────────────────────────────────────────────────────────────────────
# 판정 방식 — 점추정·신뢰구간의 오용을 막는다 (설계 규칙 2·3)
# ──────────────────────────────────────────────────────────────────────────
def test_ratio_kpi_is_not_judged_by_the_point_estimate() -> None:
    """표본 1건의 100%는 아무 말도 아니다 — 점추정으로 게이트를 넘기지 않는다."""
    outcome = _evaluate_one(_obs(gate.LoopKpi.LOOP_COMPLETION, 1, 1))
    assert outcome.observed == 1.0
    assert outcome.verdict is gate.KpiVerdict.failed
    assert outcome.bound is not None and outcome.bound < 0.95


def test_defect_ratio_uses_the_upper_bound_not_the_lower() -> None:
    """결함율(≤)에 하한을 쓰면 1%가 0.5% 기준을 통과한다 — 방향까지 지표가 갖는다."""
    outcome = _evaluate_one(_obs(gate.LoopKpi.STATE_INTEGRITY, 20, 1000))
    assert outcome.observed == 0.02
    assert outcome.bound is not None and outcome.bound > 0.02
    assert outcome.verdict is gate.KpiVerdict.failed


def test_zero_tolerance_does_not_smooth_a_single_violation_away() -> None:
    """무관용 축에 신뢰구간을 적용하면 1/100000이 통과한다 — 1건은 1건이다."""
    outcome = _evaluate_one(_obs(gate.LoopKpi.EXPLAINABILITY, 1, 100_000))
    assert outcome.verdict is gate.KpiVerdict.failed
    assert outcome.bound == 1.0


def test_zero_tolerance_pass_reports_residual_upper_bound() -> None:
    """관측 0을 확정 0으로 과신하지 않는다 — 통과해도 잔여 상한을 함께 낸다."""
    small = _evaluate_one(_obs(gate.LoopKpi.TRACEABILITY, 0, 10))
    large = _evaluate_one(_obs(gate.LoopKpi.TRACEABILITY, 0, 10_000))
    assert small.verdict is large.verdict is gate.KpiVerdict.passed
    assert small.residual_upper_bound is not None and large.residual_upper_bound is not None
    assert small.residual_upper_bound > large.residual_upper_bound > 0.0


# ──────────────────────────────────────────────────────────────────────────
# 구조적 선결 — 사실을 원천 대장에서 읽는가 (acceptance ②)
# ──────────────────────────────────────────────────────────────────────────
def test_loop_completion_and_traceability_are_blocked_on_main_today() -> None:
    """2026-09-19 main 기준: 세션 writer 0·추천 결합 불가·LearnerState 시각 부재.

    이 테스트가 깨진다면 그 자체가 좋은 소식이다 — 누군가 그 좌석을 배선했다는 뜻이고, 그러면
    `_REQUIRED_SOURCES`와 이 단언을 함께 갱신한다.
    """
    assert gate.blocked_preconditions(gate.LoopKpi.LOOP_COMPLETION)
    assert gate.blocked_preconditions(gate.LoopKpi.TRACEABILITY)
    for kpi in (
        gate.LoopKpi.STATE_INTEGRITY,
        gate.LoopKpi.EXPLAINABILITY,
        gate.LoopKpi.MANUAL_INTERVENTION,
    ):
        assert gate.blocked_preconditions(kpi) == ()


def test_wiring_the_registry_unblocks_the_structural_kpis(monkeypatch: Any) -> None:
    """원천이 PRODUCED로 바뀌면 선결이 자동으로 풀린다 — 사실을 두 곳에 적지 않았다는 증거.

    이것이 이 설계의 핵심 주장이고, 주장은 주입으로만 검증된다.
    """
    monkeypatch.setattr(gate, "source_registry", _all_produced_registry)
    assert gate.blocked_preconditions(gate.LoopKpi.LOOP_COMPLETION) == ()
    assert gate.blocked_preconditions(gate.LoopKpi.TRACEABILITY) == ()


def test_blocked_precondition_names_the_source_and_the_reason() -> None:
    """미측정 사유가 '미측정'이면 아무 정보도 아니다 — 어느 원천이 왜 막는지 말한다."""
    blocked = gate.blocked_preconditions(gate.LoopKpi.LOOP_COMPLETION)
    joined = " ".join(blocked)
    assert "learning_session" in joined
    assert "evidence_event" in joined
    assert "writer 0건" in joined


# ──────────────────────────────────────────────────────────────────────────
# 입력 계약 — 관측치만 받는다 (설계 규칙 4)
# ──────────────────────────────────────────────────────────────────────────
def test_input_rejects_a_self_declared_threshold() -> None:
    """입력이 자기 합격선을 써 내면 그것은 판정이 아니라 자기 신고다."""
    with pytest.raises(gate.InputContractError, match="허용되지 않은 키"):
        gate.parse_input_observations(
            {"explainability": {"numerator": 5, "denominator": 5, "threshold": 1.0}}
        )


def test_input_rejects_an_unknown_kpi_key() -> None:
    with pytest.raises(gate.InputContractError, match="알 수 없는 KPI 키"):
        gate.parse_input_observations({"loop_completion": {"numerator": 1}})


def test_input_rejects_a_typo_instead_of_silently_dropping_it() -> None:
    """오타를 조용히 버리면 제출자는 자기 값이 쓰였다고 믿는다 — 관대함이 아니라 위장이다."""
    with pytest.raises(gate.InputContractError, match="허용되지 않은 키"):
        gate.parse_input_observations({"explainability": {"numerater": 1, "denominator": 5}})


def test_input_rejects_non_integer_counts() -> None:
    with pytest.raises(gate.InputContractError, match="정수여야"):
        gate.parse_input_observations({"explainability": {"numerator": "1", "denominator": 5}})


def test_input_accepts_the_allowed_shape() -> None:
    parsed = gate.parse_input_observations(
        {"explainability": {"numerator": 0, "denominator": 7, "source": "drill"}}
    )
    assert parsed[gate.LoopKpi.EXPLAINABILITY] == gate.Observation(
        kpi=gate.LoopKpi.EXPLAINABILITY, numerator=0, denominator=7, source="drill"
    )


# ──────────────────────────────────────────────────────────────────────────
# 증거 — 실패해도 남는가 (설계 규칙 6)
# ──────────────────────────────────────────────────────────────────────────
def _read_ndjson(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_evidence_is_flushed_per_line_not_at_the_end(tmp_path: Path) -> None:
    """마지막에 한 번 저장하면 중간에 멈출 때 전부 잃는다 — 줄마다 읽을 수 있어야 한다."""
    path = tmp_path / "nested" / "ev.ndjson"
    writer = gate.EvidenceWriter(path, run_id="r1", window=_WINDOW)
    writer.record(kpi=gate.LoopKpi.EXPLAINABILITY, phase="collect_start", ok=True)
    # 아직 실행이 끝나지 않았는데도 읽힌다 = flush됐다.
    assert len(_read_ndjson(path)) == 1
    writer.record(kpi=None, phase="run_end", ok=True)
    assert len(_read_ndjson(path)) == 2


def test_every_evidence_line_carries_run_id_and_window(tmp_path: Path) -> None:
    """시간 필터가 없으면 *이전 실행*의 증거를 이번 원인으로 오독한다."""
    path = tmp_path / "ev.ndjson"
    writer = gate.EvidenceWriter(path, run_id="r2", window=_WINDOW)
    writer.record(kpi=gate.LoopKpi.TRACEABILITY, phase="verdict", ok=False)
    line = _read_ndjson(path)[0]
    assert line["run_id"] == "r2"
    assert line["window"] == _WINDOW.as_dict()
    assert line["at"]


def test_evidence_writer_without_a_path_is_a_noop() -> None:
    """경로가 없으면 아무 데도 쓰지 않는다 — 호출부가 분기를 갖지 않게 한다."""
    gate.EvidenceWriter(None, run_id="r3", window=_WINDOW).record(
        kpi=None, phase="run_start", ok=True
    )


# ──────────────────────────────────────────────────────────────────────────
# 수집 runner — 한 수집기의 실패가 나머지를 죽이지 않는다
# ──────────────────────────────────────────────────────────────────────────
async def _ok_collector(kpi: gate.LoopKpi, numerator: int, denominator: int) -> gate.Observation:
    return gate.Observation(kpi=kpi, numerator=numerator, denominator=denominator, source="fake")


def _collectors_with(**overrides: gate.CollectFn) -> dict[gate.LoopKpi, gate.CollectFn]:
    base: dict[gate.LoopKpi, gate.CollectFn] = {}
    for spec in gate.LOOP_KPI_SPECS:

        def make(kpi: gate.LoopKpi = spec.kpi) -> gate.CollectFn:
            async def collect(_session: Any, _window: gate.ObservationWindow) -> gate.Observation:
                return await _ok_collector(kpi, 0, 100)

            return collect

        base[spec.kpi] = make()
    base.update(overrides)
    return base


def test_one_failing_collector_only_unmeasures_its_own_kpi(tmp_path: Path) -> None:
    """접속 하나가 깨졌다고 판정 표 전체를 잃으면, 고칠 곳을 알 수 없게 된다."""

    async def boom(_session: Any, _window: gate.ObservationWindow) -> gate.Observation:
        raise ConnectionRefusedError("refused")

    path = tmp_path / "ev.ndjson"
    writer = gate.EvidenceWriter(path, run_id="r4", window=_WINDOW)
    observations = asyncio.run(
        gate.collect_all(
            None,  # type: ignore[arg-type]  수집기를 전량 대체하므로 세션은 쓰이지 않는다
            _WINDOW,
            evidence=writer,
            collectors=_collectors_with(**{gate.LoopKpi.STATE_INTEGRITY.value: boom}),
        )
    )
    broken = observations[gate.LoopKpi.STATE_INTEGRITY]
    assert broken.unmeasured_reason is not None
    # 침묵 실패 금지 — 예외 **타입명**이 관측치와 증거 양쪽에 남는다.
    assert broken.error_type == "ConnectionRefusedError"
    assert observations[gate.LoopKpi.EXPLAINABILITY].denominator == 100

    errors = [line for line in _read_ndjson(path) if line["phase"] == "collect_error"]
    assert len(errors) == 1
    assert errors[0]["error_type"] == "ConnectionRefusedError"
    assert errors[0]["error_module"] == "builtins"


def test_a_hanging_collector_times_out_with_evidence(tmp_path: Path) -> None:
    """무한 대기는 증거도 원인도 남기지 않고 측정 회차만 태운다 — 전부 타임아웃을 건다."""

    async def hang(_session: Any, _window: gate.ObservationWindow) -> gate.Observation:
        await asyncio.sleep(10)
        raise AssertionError("도달 불가")

    path = tmp_path / "ev.ndjson"
    writer = gate.EvidenceWriter(path, run_id="r5", window=_WINDOW)
    observations = asyncio.run(
        gate.collect_all(
            None,  # type: ignore[arg-type]
            _WINDOW,
            evidence=writer,
            timeout_seconds=0.05,
            collectors=_collectors_with(**{gate.LoopKpi.TRACEABILITY.value: hang}),
        )
    )
    assert observations[gate.LoopKpi.TRACEABILITY].error_type == "TimeoutError"
    assert any(line["phase"] == "collect_error" for line in _read_ndjson(path))


def test_a_missing_collector_is_unmeasured_not_skipped(tmp_path: Path) -> None:
    collectors = _collectors_with()
    del collectors[gate.LoopKpi.MANUAL_INTERVENTION]
    observations = asyncio.run(
        gate.collect_all(
            None,  # type: ignore[arg-type]
            _WINDOW,
            evidence=gate.EvidenceWriter(None, run_id="r6", window=_WINDOW),
            collectors=collectors,
        )
    )
    assert len(observations) == 5
    assert observations[gate.LoopKpi.MANUAL_INTERVENTION].unmeasured_reason is not None


class _ExplodingSession:
    """건드리는 순간 터지는 가짜 세션 — '조회하지 않는다'는 주장을 검증한다."""

    def __getattr__(self, name: str) -> Any:  # pragma: no cover - 호출되면 실패다
        raise AssertionError(f"구조적으로 막힌 KPI가 DB를 건드렸다: {name}")


@pytest.mark.parametrize(
    ("collector", "kpi"),
    [
        (gate.collect_loop_completion, gate.LoopKpi.LOOP_COMPLETION),
        (gate.collect_traceability, gate.LoopKpi.TRACEABILITY),
    ],
)
def test_blocked_collectors_do_not_query_the_database(
    collector: gate.CollectFn, kpi: gate.LoopKpi
) -> None:
    """선결이 막혀 있으면 조회하지 않는다 — 조회해서 나오는 0은 '도달 실패'가 아니다."""
    observation = asyncio.run(collector(_ExplodingSession(), _WINDOW))  # type: ignore[arg-type]
    assert observation.kpi is kpi
    assert observation.unmeasured_reason is not None
    assert "구조적 선결 미충족" in observation.unmeasured_reason


# ──────────────────────────────────────────────────────────────────────────
# CLI — 판정은 exit code로 낸다
# ──────────────────────────────────────────────────────────────────────────
def _write_input(tmp_path: Path, payload: dict[str, Any]) -> str:
    path = tmp_path / "obs.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _clean_input() -> dict[str, Any]:
    return {
        kpi.value: {"numerator": clean[0], "denominator": clean[1]}
        for kpi, clean, _ in _INJECTION_PAIRS
    }


def test_cli_exits_zero_when_all_five_are_measured_and_met(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = gate.main(["--no-db", "--input", _write_input(tmp_path, _clean_input())])
    assert code == gate.EXIT_OK
    assert "5종 전부 충족" in capsys.readouterr().out


@pytest.mark.parametrize(("kpi", "dirty"), [(k, d) for k, _, d in _INJECTION_PAIRS])
def test_cli_exits_one_for_each_injected_violation(
    kpi: gate.LoopKpi, dirty: tuple[int, int], tmp_path: Path
) -> None:
    """CLI 표면에서도 5종 각각이 주입에 반응한다(단위 판정만이 아니라 게이트로서)."""
    payload = _clean_input()
    payload[kpi.value] = {"numerator": dirty[0], "denominator": dirty[1]}
    assert gate.main(["--no-db", "--input", _write_input(tmp_path, payload)]) == (
        gate.EXIT_VIOLATION
    )


def test_cli_exits_two_when_nothing_was_measured(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """측정 실패가 '0건 통과'로 위장되지 않는다 — 별도 exit code를 갖는 이유."""
    code = gate.main(["--no-db"])
    assert code == gate.EXIT_UNMEASURED
    assert "미측정은 통과가 아니다" in capsys.readouterr().out


def test_cli_rejects_a_self_declared_threshold_with_a_runtime_error(tmp_path: Path) -> None:
    payload = {"explainability": {"numerator": 0, "denominator": 5, "direction": ">="}}
    assert gate.main(["--no-db", "--input", _write_input(tmp_path, payload)]) == (
        gate.EXIT_RUNTIME_ERROR
    )


def test_cli_rejects_a_non_positive_window() -> None:
    assert gate.main(["--no-db", "--since-hours", "0"]) == gate.EXIT_RUNTIME_ERROR


def test_cli_writes_json_and_evidence_for_a_failing_run(tmp_path: Path) -> None:
    """실패한 실행에서도 산출물이 남는다 — 남지 않으면 그 회차는 통째로 버려진다."""
    payload = _clean_input()
    payload[gate.LoopKpi.EXPLAINABILITY.value] = {"numerator": 3, "denominator": 500}
    json_path = tmp_path / "out" / "report.json"
    evidence_path = tmp_path / "out" / "ev.ndjson"
    code = gate.main(
        [
            "--no-db",
            "--input",
            _write_input(tmp_path, payload),
            "--json",
            str(json_path),
            "--evidence",
            str(evidence_path),
        ]
    )
    assert code == gate.EXIT_VIOLATION

    report = json.loads(json_path.read_text(encoding="utf-8"))
    assert report["counts"] == {"total": 5, "passed": 4, "failed": 1, "unmeasured": 0}
    assert report["exit_code"] == gate.EXIT_VIOLATION
    explain = next(k for k in report["kpis"] if k["kpi"] == "explainability")
    assert explain["verdict"] == "fail"
    # 결선표가 산출물에 함께 실린다 — 숫자만으로는 무엇을 잰 것인지 알 수 없다.
    assert explain["numerator_def"] and explain["denominator_def"] and explain["seat_task"]

    phases = [line["phase"] for line in _read_ndjson(evidence_path)]
    assert phases[0] == "run_start"
    assert phases[-1] == "run_end"
    assert "input_merge" in phases and "verdict" in phases


def test_render_marks_unmeasured_differently_from_pass() -> None:
    """미측정이 통과와 같은 글자로 보이면 사람이 그것을 통과로 읽는다."""
    report = gate.evaluate(
        {
            gate.LoopKpi.EXPLAINABILITY: _obs(gate.LoopKpi.EXPLAINABILITY, 0, 100),
            gate.LoopKpi.TRACEABILITY: _obs(gate.LoopKpi.TRACEABILITY, 0, 0),
        },
        window=_WINDOW,
        run_id="t",
    )
    text = gate.render(report)
    assert "[PASS]" in text
    assert "미측정" in text
    # 통과 줄에는 점추정이 있고 미측정 줄에는 없다 — 두 줄이 같은 모양이면 구별이 무의미하다.
    assert "점추정    : 0.0000" in text
    assert "분모가 0" in text


def test_manual_intervention_declares_its_blind_spot() -> None:
    """psql 직접 수정은 감사 표면을 지나지 않는다 — 0을 '개입 없음'으로 읽지 않게 적어 둔다."""
    spec = gate.spec_for(gate.LoopKpi.MANUAL_INTERVENTION)
    assert spec.coverage_note is not None
    assert "psql" in spec.coverage_note
    outcome = _evaluate_one(_obs(gate.LoopKpi.MANUAL_INTERVENTION, 0, 10))
    assert outcome.as_dict()["coverage_note"] == spec.coverage_note


def test_operator_audit_kinds_exclude_the_students_own_actions() -> None:
    """본인 반출·동의변경을 개입으로 세면 정상 시나리오가 위반으로 계상된다."""
    from whymath_backend.schema.enums import AuditEventKind

    assert AuditEventKind.export_data.value not in gate.OPERATOR_AUDIT_KINDS
    assert AuditEventKind.consent_change.value not in gate.OPERATOR_AUDIT_KINDS
    assert AuditEventKind.role_change.value in gate.OPERATOR_AUDIT_KINDS
    assert AuditEventKind.content_mutation.value in gate.OPERATOR_AUDIT_KINDS


# ──────────────────────────────────────────────────────────────────────────
# 픽스처가 없던 분기 보강 — "뮤테이션 전건 RED"는 커버리지의 증거가 아니다
# (CLAUDE.md 2026-09-08: 주입 목록에 없는 절은 애초에 검사되지 않는다)
# ──────────────────────────────────────────────────────────────────────────
def test_db_failure_is_unmeasured_not_a_runtime_error(
    monkeypatch: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """DB에 못 붙었다고 판정 표 자체가 사라지면 나머지 KPI의 결과까지 잃는다.

    모듈 docstring이 "DB 접속 실패는 exit 3이 아니라 해당 KPI의 미측정(→2)"이라고 *주장*하는
    자리다. 주장만 적고 픽스처를 두지 않으면 그 문장이 검증된 적 없는 채로 남는다.
    """

    def boom() -> Any:
        raise ConnectionRefusedError("refused")

    monkeypatch.setattr(gate, "get_sessionmaker", boom)
    code = gate.main(["--since-hours", "1"])
    assert code == gate.EXIT_UNMEASURED
    out = capsys.readouterr().out
    assert "ConnectionRefusedError" in out
    assert out.count("미측정") >= 5


def test_db_failure_records_the_exception_module_in_evidence(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """타입명만으로는 우리 코드 결함(TypeError 등)을 짚을 수 없다 — 모듈도 함께 남긴다."""

    def boom() -> Any:
        raise TypeError("bad call")

    monkeypatch.setattr(gate, "get_sessionmaker", boom)
    evidence_path = tmp_path / "ev.ndjson"
    gate.main(["--since-hours", "1", "--evidence", str(evidence_path)])
    lines = _read_ndjson(evidence_path)
    connect_errors = [line for line in lines if line["phase"] == "db_connect_error"]
    assert len(connect_errors) == 1
    assert connect_errors[0]["error_type"] == "TypeError"
    assert connect_errors[0]["error_module"] == "builtins"


def test_input_rejects_a_non_object_document() -> None:
    with pytest.raises(gate.InputContractError, match="최상위가 객체가 아니다"):
        gate.parse_input_observations([{"explainability": {}}])


def test_input_rejects_a_non_object_kpi_entry() -> None:
    with pytest.raises(gate.InputContractError, match="값이 객체가 아니다"):
        gate.parse_input_observations({"explainability": 5})


def test_input_rejects_a_non_string_unmeasured_reason() -> None:
    with pytest.raises(gate.InputContractError, match="문자열이어야"):
        gate.parse_input_observations({"explainability": {"unmeasured_reason": 7}})


def test_input_rejects_a_non_string_source() -> None:
    with pytest.raises(gate.InputContractError, match="문자열이어야"):
        gate.parse_input_observations({"explainability": {"source": 7}})


def test_unreadable_input_file_is_a_runtime_error_not_a_silent_pass(tmp_path: Path) -> None:
    """입력을 못 읽었는데 '입력 없이 판정'으로 넘어가면 주입 드릴이 조용히 무효가 된다."""
    assert gate.main(["--no-db", "--input", str(tmp_path / "없는파일.json")]) == (
        gate.EXIT_RUNTIME_ERROR
    )


def test_malformed_input_json_is_a_runtime_error(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    assert gate.main(["--no-db", "--input", str(path)]) == gate.EXIT_RUNTIME_ERROR


def test_unwritable_json_destination_is_a_runtime_error(tmp_path: Path) -> None:
    """리포트를 못 남겼는데 exit 0을 내면 '판정했다'는 기록이 어디에도 없다."""
    blocker = tmp_path / "blocker"
    blocker.write_text("파일이라 하위 경로를 만들 수 없다", encoding="utf-8")
    code = gate.main(
        [
            "--no-db",
            "--input",
            _write_input(tmp_path, _clean_input()),
            "--json",
            str(blocker / "sub" / "report.json"),
        ]
    )
    assert code == gate.EXIT_RUNTIME_ERROR


# ──────────────────────────────────────────────────────────────────────────
# 수집기 격리 — 고장 하나가 여러 개로 보고되지 않는다
# ──────────────────────────────────────────────────────────────────────────
class _RecordingSession:
    """rollback 호출만 기록하는 가짜 세션."""

    def __init__(self) -> None:
        self.rollbacks = 0

    async def rollback(self) -> None:
        self.rollbacks += 1


def test_a_failing_collector_rolls_the_session_back(tmp_path: Path) -> None:
    """중단된 트랜잭션을 되돌리지 않으면 뒤 수집기가 *거짓* 실패한다(고장 1건이 N건으로 보고).

    2026-09-19 실측: `evidence_event.meta` 하나를 개명했더니 수집기 2종이 실패로 찍혔다 —
    두 번째는 멀쩡했고 중단 트랜잭션에 걸린 것뿐이었다.
    """

    async def boom(_session: Any, _window: gate.ObservationWindow) -> gate.Observation:
        raise RuntimeError("query failed")

    session = _RecordingSession()
    asyncio.run(
        gate.collect_all(
            session,  # type: ignore[arg-type]
            _WINDOW,
            evidence=gate.EvidenceWriter(None, run_id="r7", window=_WINDOW),
            collectors=_collectors_with(**{gate.LoopKpi.EXPLAINABILITY.value: boom}),
        )
    )
    assert session.rollbacks == 1


def test_recovery_failure_is_recorded_not_swallowed(tmp_path: Path) -> None:
    """복구도 실패할 수 있다 — 조용히 넘어가면 그 다음 거짓 실패의 원인을 못 짚는다."""

    class _BrokenSession:
        async def rollback(self) -> None:
            raise ConnectionResetError("gone")

    async def boom(_session: Any, _window: gate.ObservationWindow) -> gate.Observation:
        raise RuntimeError("query failed")

    path = tmp_path / "ev.ndjson"
    asyncio.run(
        gate.collect_all(
            _BrokenSession(),  # type: ignore[arg-type]
            _WINDOW,
            evidence=gate.EvidenceWriter(path, run_id="r8", window=_WINDOW),
            collectors=_collectors_with(**{gate.LoopKpi.EXPLAINABILITY.value: boom}),
        )
    )
    recover = [line for line in _read_ndjson(path) if line["phase"] == "session_recover_error"]
    assert len(recover) == 1
    assert recover[0]["error_type"] == "ConnectionResetError"


# ──────────────────────────────────────────────────────────────────────────
# 스키마 스모크 — 빈 DB에서도 변별력이 있는 축(CI 배선 대상)
# ──────────────────────────────────────────────────────────────────────────
def test_schema_smoke_ignores_unmeasured_but_catches_collector_errors() -> None:
    """빈 DB의 미측정은 실패가 아니고, 수집기 예외는 실패다 — 그 경계가 이 모드의 전부다."""
    empty = {
        gate.LoopKpi.EXPLAINABILITY: _obs(gate.LoopKpi.EXPLAINABILITY, 0, 0),
        gate.LoopKpi.LOOP_COMPLETION: gate.Observation(
            kpi=gate.LoopKpi.LOOP_COMPLETION,
            unmeasured_reason="구조적 선결 미충족 — …",
            source="collect_loop_completion",
        ),
    }
    assert gate.schema_smoke_failures(empty) == ()

    broken = dict(empty)
    broken[gate.LoopKpi.STATE_INTEGRITY] = gate.Observation(
        kpi=gate.LoopKpi.STATE_INTEGRITY,
        unmeasured_reason="수집 실패(ProgrammingError) — 판정 불가.",
        source="error",
        error_type="ProgrammingError",
    )
    assert len(gate.schema_smoke_failures(broken)) == 1


def test_schema_smoke_cli_exits_one_when_a_collector_raises(monkeypatch: Any) -> None:
    async def fake(*_args: Any, **_kwargs: Any) -> dict[gate.LoopKpi, gate.Observation]:
        return {
            gate.LoopKpi.STATE_INTEGRITY: gate.Observation(
                kpi=gate.LoopKpi.STATE_INTEGRITY,
                unmeasured_reason="수집 실패(ProgrammingError) — 판정 불가.",
                source="error",
                error_type="ProgrammingError",
            )
        }

    monkeypatch.setattr(gate, "_collect_via_db", fake)
    assert gate.main(["--schema-smoke"]) == gate.EXIT_VIOLATION


def test_schema_smoke_cli_exits_zero_on_an_empty_but_intact_schema(monkeypatch: Any) -> None:
    async def fake(*_args: Any, **_kwargs: Any) -> dict[gate.LoopKpi, gate.Observation]:
        return {kpi: _obs(kpi, 0, 0) for kpi in gate.LoopKpi}

    monkeypatch.setattr(gate, "_collect_via_db", fake)
    assert gate.main(["--schema-smoke"]) == gate.EXIT_OK


def test_schema_smoke_refuses_to_run_without_a_database() -> None:
    """DB를 안 보는 스키마 스모크는 아무것도 검사하지 않는다 — 공허한 통과를 거부한다."""
    assert gate.main(["--schema-smoke", "--no-db"]) == gate.EXIT_RUNTIME_ERROR


def test_schema_smoke_refuses_input_instead_of_ignoring_it(tmp_path: Path) -> None:
    """스모크는 판정 전에 끝난다 — 조용히 무시하면 제출자는 자기 관측치가 쓰였다고 믿는다."""
    argv = ["--schema-smoke", "--input", _write_input(tmp_path, _clean_input())]
    assert gate.main(argv) == gate.EXIT_RUNTIME_ERROR
