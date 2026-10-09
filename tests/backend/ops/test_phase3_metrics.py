"""Phase 3 지표 7종 일괄 CLI(`ops/phase3_metrics.py`, P3-14) — 위반 주입 반응 검증 스위트.

이 파일이 지키는 것
-------------------
지표 7종은 "위반이 생기면 그 지표가 떨어진다"가 증명돼야 측정 도구다. 정상 입력에서 수치가 나오는
것은 증거가 아니다(모든 입력에서 같은 값을 내는 계측기도 같은 화면을 낸다). 실 코퍼스는 ②⑦ 이
0 이라 하락을 보일 수 없으므로 **합성 대조 세계**(7종 전부 충족)가 필수다. 그래서

  1. 대조군 — 7종이 전부 충족이고 종합이 exit 0 임을 고정한다.
  2. 위반 주입 — 지표마다 위반을 하나씩 넣어 **그 지표만** 미달로 바뀌는지 본다. 주입은
     `_inject` 가 '실제로 적용됐는가'를 단언한다(변경 전후가 같으면 정상 세계로 검사가 돈 것이다).
  3. 미측정 주입 — 입력이 없거나 분모가 0 이면 **미측정**이고 종합이 측정 실패다(통과로 접히지 않음).
  4. 성공 방향 대조군 — 주입 없는 짝은 충족이어야 한다("전부 실패로 계상"이라는 과잉 수정 차단).
  5. 목표 미정(null) — 판정을 만들지 않는다.

주입 표는 이 파일이 **독립적으로** 정의한다(모듈의 `VIOLATION_INJECTIONS` 와 별개). 같은 표로
`--self-check` 와 테스트가 서로를 검증하면 둘이 같이 틀릴 수 있다.

실 코퍼스 값은 고정하지 않는다 — 진척에 따라 바뀌는 값이라 고정하면 정당한 진척이 실패가 된다.
수치는 CLI 출력과 보고 문서가 소유한다.
"""

from __future__ import annotations

import ast
import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import pytest

from whymath_backend.harness.corpus_reverify import ReverifyReport
from whymath_backend.l1.standards import phase3_coverage as p3c
from whymath_backend.l1.standards import phase3_scope as ps
from whymath_backend.ops import loop_kpi_gate as lkg
from whymath_backend.ops import phase3_metrics as pm
from whymath_backend.ops import validation_scorecard as vs

_K = pm.MetricKey
_REPO = Path(__file__).resolve().parents[3]


# ──────────────────────────────────────────────────────────────────────────
# 픽스처
# ──────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def spec() -> ps.ScopeSpec:
    return ps.load_scope_spec()


@pytest.fixture(scope="module")
def index(spec: ps.ScopeSpec) -> ps.ReferenceIndex:
    return ps.load_reference_index(spec)


@pytest.fixture(scope="module")
def control(spec: ps.ScopeSpec, index: ps.ReferenceIndex) -> pm.Bundle:
    return pm.build_control_bundle(spec, index)


def _by_key(outcomes: tuple[pm.MetricOutcome, ...]) -> dict[pm.MetricKey, pm.MetricOutcome]:
    return {o.key: o for o in outcomes}


def _signature(o: pm.MetricOutcome) -> tuple[Any, ...]:
    return (o.state, o.met, o.numerator, o.denominator)


def _world(b: pm.Bundle) -> pm.World:
    assert isinstance(b.world, pm.World)
    return b.world


def _inject(before: pm.Bundle, after: pm.Bundle) -> pm.Bundle:
    """주입 적용 단언 — 안 바뀌었으면 정상 세계에 대해 테스트가 돈 것이다."""
    assert after != before, "주입이 적용되지 않았다(변경 전후가 같다) — 하네스 결함"
    return after


def _corpus(b: pm.Bundle, **changes: Any) -> pm.Bundle:
    w = _world(b)
    return replace(b, world=replace(w, corpus=replace(w.corpus, **changes)))


def _spec_of(b: pm.Bundle, **changes: Any) -> pm.Bundle:
    w = _world(b)
    return replace(b, world=replace(w, spec=replace(w.spec, **changes)))


def _loop(num: int | None, den: int | None, reason: str | None = None) -> lkg.Observation:
    return lkg.Observation(
        kpi=lkg.LoopKpi.LOOP_COMPLETION,
        numerator=num,
        denominator=den,
        unmeasured_reason=reason,
        source="test",
    )


# ──────────────────────────────────────────────────────────────────────────
# 1. 대조군
# ──────────────────────────────────────────────────────────────────────────
class TestControl:
    def test_control_world_meets_all_seven(self, control: pm.Bundle) -> None:
        outcomes = pm.evaluate_bundle(control)
        assert [o.key for o in outcomes] == list(pm.METRIC_ORDER)
        assert len(outcomes) == 7
        for o in outcomes:
            assert o.state is pm.MetricState.MEASURED, o.key
            assert o.met is True, (o.key, o.reason)
        assert pm.compose(outcomes) is pm.Composite.ALL_MET
        assert pm.exit_code_of(pm.compose(outcomes)) == 0

    def test_control_values_are_100_percent(self, control: pm.Bundle) -> None:
        got = _by_key(pm.evaluate_bundle(control))
        for key in (
            _K.CURRICULUM_COVERAGE,
            _K.CONCEPT_COMPLETENESS,
            _K.PROBLEM_COVERAGE,
            _K.SOLUTION_QA_PASS,
            _K.GRAPH_CONNECTIVITY,
        ):
            assert got[key].value == 1.0, key
        assert got[_K.CRITICAL_DEFECT].value == 0.0
        assert got[_K.LEARNING_LOOP_SUCCESS].value == 1.0

    def test_populations_come_from_the_frozen_spec(
        self, spec: ps.ScopeSpec, control: pm.Bundle
    ) -> None:
        got = _by_key(pm.evaluate_bundle(control))
        assert got[_K.CURRICULUM_COVERAGE].denominator == len(spec.nodes)
        assert got[_K.CONCEPT_COMPLETENESS].denominator == len(spec.core_concepts)
        assert got[_K.PROBLEM_COVERAGE].denominator == len(spec.skills)
        assert got[_K.CRITICAL_DEFECT].denominator == 5
        # 범위가 이름에 박힌다 — CUR-02(분모 895) 와 구별된다.
        assert f"{len(spec.nodes)}노드" in got[_K.CURRICULUM_COVERAGE].scope
        assert "대표 과정" in got[_K.CURRICULUM_COVERAGE].scope

    def test_targets_are_read_from_their_owners(
        self, spec: ps.ScopeSpec, control: pm.Bundle
    ) -> None:
        got = _by_key(pm.evaluate_bundle(control))
        assert got[_K.CURRICULUM_COVERAGE].target == spec.targets["curriculum_coverage"].value
        assert got[_K.CONCEPT_COMPLETENESS].target == spec.targets["concept_completeness"].value
        assert got[_K.PROBLEM_COVERAGE].target == spec.targets["problem_coverage_by_skill"].value
        assert (
            got[_K.LEARNING_LOOP_SUCCESS].target
            == lkg.spec_for(lkg.LoopKpi.LOOP_COMPLETION).threshold
        )
        assert got[_K.CRITICAL_DEFECT].target == 0.0


# ──────────────────────────────────────────────────────────────────────────
# 2. 위반 주입 — 그 지표만 떨어진다 (acceptance ②)
# ──────────────────────────────────────────────────────────────────────────
def _v_add_two_nodes(b: pm.Bundle) -> pm.Bundle:
    nodes = tuple(
        ps.CurriculumNode(code=f"[99수00-0{i}]", sub_domain="합성 노드(개념 없음)") for i in (1, 2)
    )
    return _spec_of(b, nodes=_world(b).spec.nodes + nodes)


def _v_drop_explanation(b: pm.Bundle) -> pm.Bundle:
    problems = list(_world(b).corpus.problems)
    assert problems[0].has_explanation is True  # 치환 대상 존재
    problems[0] = replace(problems[0], has_explanation=False)
    return _corpus(b, problems=tuple(problems))


def _v_two_uncovered_skills(b: pm.Bundle) -> pm.Bundle:
    extra = ("skill.synthetic-a", "skill.synthetic-b")
    return _spec_of(b, skills=_world(b).spec.skills + extra)


def _v_inconsistent_condition(b: pm.Bundle) -> pm.Bundle:
    records = [dict(r) for r in _world(b).qa_records]
    verify = records[1]["verify"]
    assert isinstance(verify, dict) and verify["answer_map"] == {"x": "2"}  # 치환 대상 존재
    records[1]["verify"] = {**verify, "conditions": "x + 1 = 99"}
    return replace(b, world=replace(_world(b), qa_records=tuple(records)))


def _v_loop_point_estimate_equals_target(b: pm.Bundle) -> pm.Bundle:
    # 점추정은 190/200 = 0.95 = 목표지만 Wilson 하한은 목표 아래다 — 점추정이면 통과했을 입력.
    return replace(b, loop=_loop(190, 200))


def _v_three_anchors_fail(b: pm.Bundle) -> pm.Bundle:
    assert b.defect_payload is not None
    payload = json.loads(json.dumps(b.defect_payload))
    assert payload["anchors"]["A1"] is True  # 치환 대상 존재
    for anchor in ("A1", "A2", "A3"):
        payload["anchors"][anchor] = False
    return replace(b, defect_payload=payload)


def _v_drop_crosslinks(b: pm.Bundle) -> pm.Bundle:
    assert _world(b).corpus.crosslinks  # 치환 대상 존재
    return _corpus(b, crosslinks={})


_INJECTIONS: list[tuple[str, pm.MetricKey, Callable[[pm.Bundle], pm.Bundle]]] = [
    ("교육과정 노드 2개 추가(개념 없음)", _K.CURRICULUM_COVERAGE, _v_add_two_nodes),
    ("해설 삭제", _K.CONCEPT_COMPLETENESS, _v_drop_explanation),
    ("승인 문항이 없는 스킬 2종 추가", _K.PROBLEM_COVERAGE, _v_two_uncovered_skills),
    ("재검증 조건을 정답과 모순되게", _K.SOLUTION_QA_PASS, _v_inconsistent_condition),
    (
        "루프 190/200 (점추정=목표·Wilson 하한<목표)",
        _K.LEARNING_LOOP_SUCCESS,
        _v_loop_point_estimate_equals_target,
    ),
    ("앵커 3개 미달(F-Ⅳ)", _K.CRITICAL_DEFECT, _v_three_anchors_fail),
    ("크로스링크 삭제", _K.GRAPH_CONNECTIVITY, _v_drop_crosslinks),
]


@pytest.mark.parametrize(("name", "key", "inject"), _INJECTIONS, ids=[i[0] for i in _INJECTIONS])
def test_violation_drops_exactly_that_metric(
    control: pm.Bundle, name: str, key: pm.MetricKey, inject: Callable[[pm.Bundle], pm.Bundle]
) -> None:
    before = _by_key(pm.evaluate_bundle(control))
    assert before[key].met is True  # 성공 방향 대조군 — 주입 전에는 충족이다
    after = _by_key(pm.evaluate_bundle(_inject(control, inject(control))))
    assert after[key].state is pm.MetricState.MEASURED, name
    assert after[key].met is False, f"[{name}] {key.value} 가 미달이어야 한다: {after[key].reason}"
    for other in pm.METRIC_ORDER:
        if other is not key:
            assert _signature(after[other]) == _signature(
                before[other]
            ), f"[{name}] {other.value} 는 그대로여야 하는데 바뀌었다"
    assert pm.compose(tuple(after[k] for k in pm.METRIC_ORDER)) is pm.Composite.VIOLATION
    assert pm.exit_code_of(pm.Composite.VIOLATION) == 1


def test_injection_table_covers_all_seven_metrics() -> None:
    assert {key for _, key, _ in _INJECTIONS} == set(pm.METRIC_ORDER)


@pytest.mark.parametrize(
    "inj", pm.VIOLATION_INJECTIONS, ids=[i.name for i in pm.VIOLATION_INJECTIONS]
)
def test_modules_own_injection_table_is_isolated_and_reactive(
    control: pm.Bundle, inj: pm.Injection
) -> None:
    """`--self-check` 가 쓰는 표도 같은 성질을 가져야 한다 — 표가 무반응이면 자가 점검이 위장이다."""
    assert inj.isolated is True
    before = _by_key(pm.evaluate_bundle(control))
    after = _by_key(pm.evaluate_bundle(inj.apply(control)))
    assert after[inj.key].is_violation
    for other in pm.METRIC_ORDER:
        if other is not inj.key:
            assert _signature(after[other]) == _signature(before[other])


def test_modules_injection_tables_cover_all_seven() -> None:
    assert {i.key for i in pm.VIOLATION_INJECTIONS} == set(pm.METRIC_ORDER)
    assert {i.key for i in pm.UNMEASURED_INJECTIONS} == set(pm.METRIC_ORDER)


def test_noop_injection_is_rejected(control: pm.Bundle) -> None:
    """주입이 세계를 바꾸지 못하면 던진다 — 조용히 통과하면 초록이 검출처럼 보인다."""
    noop = pm.Injection("무변경", _K.CURRICULUM_COVERAGE, lambda b: b)
    with pytest.raises(pm.InjectionNotAppliedError):
        noop.apply(control)


# ──────────────────────────────────────────────────────────────────────────
# 3. 미측정 — 0도 100%도 아니다
# ──────────────────────────────────────────────────────────────────────────
class TestUnmeasured:
    def test_each_unmeasured_injection_is_unmeasured_not_pass(self, control: pm.Bundle) -> None:
        for inj in pm.UNMEASURED_INJECTIONS:
            outcomes = pm.evaluate_bundle(inj.apply(control))
            got = _by_key(outcomes)
            assert got[inj.key].state is pm.MetricState.UNMEASURED, inj.name
            assert got[inj.key].value is None and got[inj.key].met is None
            assert pm.compose(outcomes) is pm.Composite.MEASUREMENT_FAILED, inj.name
            assert pm.exit_code_of(pm.compose(outcomes)) == 2

    def test_loop_without_any_observation_is_unmeasured(self, control: pm.Bundle) -> None:
        got = _by_key(pm.evaluate_bundle(replace(control, loop=None)))
        assert got[_K.LEARNING_LOOP_SUCCESS].state is pm.MetricState.UNMEASURED

    def test_loop_denominator_zero_is_unmeasured_not_100_percent(self, control: pm.Bundle) -> None:
        got = _by_key(pm.evaluate_bundle(replace(control, loop=_loop(0, 0))))
        o = got[_K.LEARNING_LOOP_SUCCESS]
        assert o.state is pm.MetricState.UNMEASURED
        assert o.value is None

    def test_loop_db_failure_keeps_the_exception_type(self, control: pm.Bundle) -> None:
        failed = lkg.Observation(
            kpi=lkg.LoopKpi.LOOP_COMPLETION,
            unmeasured_reason="DB 세션 확보 실패(ConnectionRefusedError) — 판정 불가.",
            source="db_unavailable",
            error_type="ConnectionRefusedError",
        )
        o = _by_key(pm.evaluate_bundle(replace(control, loop=failed)))[_K.LEARNING_LOOP_SUCCESS]
        assert o.state is pm.MetricState.UNMEASURED
        assert o.error_type == "ConnectionRefusedError"

    def test_world_failure_makes_five_metrics_unmeasured_and_keeps_the_rest(
        self, control: pm.Bundle
    ) -> None:
        failure = pm.WorldFailure("corpus", "CoverageError", "문항 코퍼스 0건")
        got = _by_key(pm.evaluate_bundle(replace(control, world=failure)))
        for key in (
            _K.CURRICULUM_COVERAGE,
            _K.CONCEPT_COMPLETENESS,
            _K.PROBLEM_COVERAGE,
            _K.SOLUTION_QA_PASS,
            _K.GRAPH_CONNECTIVITY,
        ):
            assert got[key].state is pm.MetricState.UNMEASURED
            assert got[key].error_type == "CoverageError"
        # 세계를 못 읽어도 ⑤⑥ 은 자기 입력으로 계속 판정된다(한 지표의 실패가 나머지를 죽이지 않는다).
        assert got[_K.LEARNING_LOOP_SUCCESS].met is True
        assert got[_K.CRITICAL_DEFECT].met is True

    def test_metric_exception_becomes_that_metrics_unmeasured_with_type_name(
        self, control: pm.Bundle, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(*_: Any, **__: Any) -> pm.MetricOutcome:
            raise ZeroDivisionError("x")

        monkeypatch.setattr(pm, "_problem_coverage", boom)
        got = _by_key(pm.evaluate_bundle(control))
        assert got[_K.PROBLEM_COVERAGE].state is pm.MetricState.UNMEASURED
        assert got[_K.PROBLEM_COVERAGE].error_type == "ZeroDivisionError"
        assert got[_K.CURRICULUM_COVERAGE].met is True  # 나머지는 살아 있다


# ──────────────────────────────────────────────────────────────────────────
# 4. 판정 경계
# ──────────────────────────────────────────────────────────────────────────
class TestBoundary:
    def test_value_equal_to_target_is_met(self) -> None:
        assert pm.judge_ratio(0.95, 0.95) is True
        assert pm.judge_ratio(0.9499999, 0.95) is False
        assert pm.judge_ratio(1.0, 0.95) is True

    def test_ratio_outcome_at_exactly_the_target_is_met(self) -> None:
        met = pm._ratio_outcome(
            _K.PROBLEM_COVERAGE, "s", numerator=19, denominator=20, target=0.95,
            no_target_reason=None, reason="r",
        )  # fmt: skip
        below = pm._ratio_outcome(
            _K.PROBLEM_COVERAGE, "s", numerator=18, denominator=20, target=0.95,
            no_target_reason=None, reason="r",
        )  # fmt: skip
        assert met.met is True and below.met is False

    def test_zero_denominator_is_unmeasured(self) -> None:
        o = pm._ratio_outcome(
            _K.PROBLEM_COVERAGE, "s", numerator=0, denominator=0, target=0.95,
            no_target_reason=None, reason="r",
        )  # fmt: skip
        assert o.state is pm.MetricState.UNMEASURED
        assert o.value is None and o.met is None


# ──────────────────────────────────────────────────────────────────────────
# 5. 목표 미정(null) — 판정을 만들지 않는다
# ──────────────────────────────────────────────────────────────────────────
class TestNoTarget:
    def _pending(self, control: pm.Bundle) -> tuple[pm.MetricOutcome, ...]:
        w = _world(control)
        targets = dict(w.spec.targets)
        targets["graph_connectivity_coverage"] = ps.Target(value=None, reason="아직 안 정했다")
        return pm.evaluate_bundle(_inject(control, _spec_of(control, targets=targets)))

    def test_null_target_gives_value_without_verdict(self, control: pm.Bundle) -> None:
        o = _by_key(self._pending(control))[_K.GRAPH_CONNECTIVITY]
        assert o.state is pm.MetricState.NO_TARGET
        assert o.value == 1.0 and o.target is None and o.met is None
        assert "아직 안 정했다" in o.reason

    def test_composite_with_no_target_is_not_all_met(self, control: pm.Bundle) -> None:
        outcomes = self._pending(control)
        assert pm.compose(outcomes) is pm.Composite.TARGET_PENDING
        assert pm.exit_code_of(pm.Composite.TARGET_PENDING) == 2

    def test_violation_outranks_target_pending(self, control: pm.Bundle) -> None:
        pending = _by_key(self._pending(control))
        bad = replace(pending[_K.LEARNING_LOOP_SUCCESS], met=False, value=0.5)
        pending[_K.LEARNING_LOOP_SUCCESS] = bad
        assert pm.compose(tuple(pending[k] for k in pm.METRIC_ORDER)) is pm.Composite.VIOLATION

    def test_real_spec_has_null_graph_target_so_real_run_is_never_all_met(
        self, spec: ps.ScopeSpec
    ) -> None:
        """현재 사실의 기록 — 명세가 ⑦ 목표를 정하기 전에는 실 코퍼스 종합이 충족일 수 없다."""
        if spec.targets["graph_connectivity_coverage"].value is not None:
            pytest.skip("⑦ 목표가 확정됐다 — 이 사실 기록은 더 이상 유효하지 않다")
        assert spec.targets["graph_connectivity_coverage"].reason


# ──────────────────────────────────────────────────────────────────────────
# 6. 종합 규칙 — 미측정이 위반보다 먼저, 7종이 아니면 측정 실패
# ──────────────────────────────────────────────────────────────────────────
def _synthetic_outcomes(**override: pm.MetricOutcome) -> tuple[pm.MetricOutcome, ...]:
    out: list[pm.MetricOutcome] = []
    for key in pm.METRIC_ORDER:
        if key.value in override:
            out.append(override[key.value])
        else:
            out.append(
                pm.MetricOutcome(
                    key=key, state=pm.MetricState.MEASURED, scope="s", reason="r", source="x",
                    value=1.0, target=0.5, met=True, numerator=1, denominator=1,
                )  # fmt: skip
            )
    return tuple(out)


def _violation(key: pm.MetricKey) -> pm.MetricOutcome:
    return pm.MetricOutcome(
        key=key, state=pm.MetricState.MEASURED, scope="s", reason="r", source="x",
        value=0.1, target=0.5, met=False, numerator=1, denominator=10,
    )  # fmt: skip


def _unmeasured(key: pm.MetricKey) -> pm.MetricOutcome:
    return pm._unmeasured(key, "s", "사유")


class TestComposite:
    def test_all_met(self) -> None:
        assert pm.compose(_synthetic_outcomes()) is pm.Composite.ALL_MET

    def test_violation_only(self) -> None:
        outcomes = _synthetic_outcomes(
            **{_K.PROBLEM_COVERAGE.value: _violation(_K.PROBLEM_COVERAGE)}
        )
        assert pm.compose(outcomes) is pm.Composite.VIOLATION

    def test_unmeasured_only(self) -> None:
        outcomes = _synthetic_outcomes(
            **{_K.SOLUTION_QA_PASS.value: _unmeasured(_K.SOLUTION_QA_PASS)}
        )
        assert pm.compose(outcomes) is pm.Composite.MEASUREMENT_FAILED

    def test_unmeasured_outranks_violation(self) -> None:
        outcomes = _synthetic_outcomes(
            **{
                _K.PROBLEM_COVERAGE.value: _violation(_K.PROBLEM_COVERAGE),
                _K.SOLUTION_QA_PASS.value: _unmeasured(_K.SOLUTION_QA_PASS),
            }
        )
        assert pm.compose(outcomes) is pm.Composite.MEASUREMENT_FAILED
        assert pm.exit_code_of(pm.compose(outcomes)) == 2

    def test_not_exactly_seven_is_measurement_failure(self) -> None:
        full = _synthetic_outcomes()
        assert pm.compose(full[:6]) is pm.Composite.MEASUREMENT_FAILED
        assert pm.compose(()) is pm.Composite.MEASUREMENT_FAILED
        assert pm.compose(full + (full[0],)) is pm.Composite.MEASUREMENT_FAILED
        # 7개여도 한 키가 두 번이고 다른 키가 없으면 7종이 아니다.
        dup = full[:6] + (full[0],)
        assert len(dup) == 7 and pm.compose(dup) is pm.Composite.MEASUREMENT_FAILED

    def test_exit_codes(self) -> None:
        assert (pm.EXIT_ALL_MET, pm.EXIT_VIOLATION, pm.EXIT_UNMEASURED, pm.EXIT_RUNTIME_ERROR) == (
            0, 1, 2, 3,
        )  # fmt: skip
        assert pm.exit_code_of(pm.Composite.ALL_MET) == 0
        assert pm.exit_code_of(pm.Composite.VIOLATION) == 1
        assert pm.exit_code_of(pm.Composite.MEASUREMENT_FAILED) == 2

    def test_there_is_no_aggregate_score(self, control: pm.Bundle) -> None:
        report = pm.MetricsReport(
            run_id="t", observed_at=datetime.now(UTC), sample_basis="synthetic",
            spec_id="s", outcomes=pm.evaluate_bundle(control),
        )  # fmt: skip
        payload = report.as_dict()
        assert not any("score" in k or "average" in k for k in payload)
        text = pm.render(report)
        assert "종합 점수 없음" in text


class TestOutcomeInvariants:
    def test_measured_requires_value_target_and_verdict(self) -> None:
        with pytest.raises(ValueError):
            pm.MetricOutcome(key=_K.PROBLEM_COVERAGE, state=pm.MetricState.MEASURED, scope="s",
                             reason="r", source="x", value=1.0, target=None, met=True)  # fmt: skip

    def test_unmeasured_cannot_carry_a_value_or_verdict(self) -> None:
        with pytest.raises(ValueError):
            pm.MetricOutcome(key=_K.PROBLEM_COVERAGE, state=pm.MetricState.UNMEASURED, scope="s",
                             reason="r", source="x", value=0.0)  # fmt: skip
        with pytest.raises(ValueError):
            pm.MetricOutcome(key=_K.PROBLEM_COVERAGE, state=pm.MetricState.UNMEASURED, scope="s",
                             reason="r", source="x", met=True)  # fmt: skip

    def test_no_target_cannot_carry_a_verdict(self) -> None:
        with pytest.raises(ValueError):
            pm.MetricOutcome(key=_K.PROBLEM_COVERAGE, state=pm.MetricState.NO_TARGET, scope="s",
                             reason="r", source="x", value=1.0, met=True)  # fmt: skip


# ──────────────────────────────────────────────────────────────────────────
# 7. ④ Solution QA Pass — skip 은 통과가 아니고, evaluable 0 은 측정 실패
# ──────────────────────────────────────────────────────────────────────────
def _qa_world(control: pm.Bundle, n: int) -> pm.World:
    records = tuple({"problem_id": f"r{i}", "slug": f"r{i}"} for i in range(n))
    return replace(_world(control), qa_records=records, qa_expected=n)


def _stub(passed: int, failed: int, skipped: int) -> Callable[..., ReverifyReport]:
    def run(records: list[dict[str, object]], *, use_fuzz: bool) -> ReverifyReport:
        failures = tuple((f"f{i}", "사유") for i in range(failed))
        return ReverifyReport(passed=passed, failed=failed, skipped=skipped, failures=failures)

    return run


class TestSolutionQa:
    def _run(self, control: pm.Bundle, n: int, report: tuple[int, int, int]) -> pm.MetricOutcome:
        return pm._solution_qa(_qa_world(control, n), "scope", _stub(*report))

    def test_threshold_is_absorbed_from_the_scorecard(self) -> None:
        ceiling = next(
            t.value for k, t in vs.CONTENT_KPI_THRESHOLDS.items() if k.startswith("수학적 오류율")
        )
        assert pm.solution_qa_target() == pytest.approx(1.0 - ceiling)
        assert pm.solution_qa_target() == pytest.approx(0.995)

    def test_target_follows_the_scorecard_when_it_changes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        name = next(k for k in vs.CONTENT_KPI_THRESHOLDS if k.startswith("수학적 오류율"))
        monkeypatch.setitem(vs.CONTENT_KPI_THRESHOLDS, name, vs.KpiThreshold("ceiling", 0.02))
        assert pm.solution_qa_target() == pytest.approx(0.98)

    def test_wrong_direction_in_scorecard_is_a_config_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        name = next(k for k in vs.CONTENT_KPI_THRESHOLDS if k.startswith("수학적 오류율"))
        monkeypatch.setitem(vs.CONTENT_KPI_THRESHOLDS, name, vs.KpiThreshold("floor", 0.92))
        with pytest.raises(pm.MetricsConfigError):
            pm.solution_qa_target()

    def test_boundary_398_of_400_met_397_of_400_violation(self, control: pm.Bundle) -> None:
        at = self._run(control, 400, (398, 2, 0))
        below = self._run(control, 400, (397, 3, 0))
        assert at.met is True and at.value == pytest.approx(0.995)
        assert below.met is False

    def test_skip_is_not_counted_as_pass(self, control: pm.Bundle) -> None:
        """9 통과 + 1 검증 불가 — 통과율은 9/9 이고 검증 불가가 따로 보인다(10/10 이 아니다)."""
        o = self._run(control, 10, (9, 0, 1))
        assert (o.numerator, o.denominator) == (9, 9)
        facts = dict(o.facts)
        assert facts["검증 불가 비율"].startswith("1/10")

    def test_skip_does_not_hide_a_failure(self, control: pm.Bundle) -> None:
        o = self._run(control, 400, (300, 3, 97))
        assert (o.numerator, o.denominator) == (300, 303)
        assert o.met is False

    def test_all_skipped_is_unmeasured_not_100_percent(self, control: pm.Bundle) -> None:
        o = self._run(control, 10, (0, 0, 10))
        assert o.state is pm.MetricState.UNMEASURED
        assert o.value is None
        # ④ 전용 가드(`evaluable <= 0`)를 실제로 밟았는지 — `_ratio_outcome` 의 분모 0 방어선도
        # 같은 상태(UNMEASURED)를 내므로 상태만 보면 두 경로를 구별하지 못한다(독립 뮤테이션 M4
        # 생존으로 발각). 이 가드만이 '전부 검증 불가 N건' 사유와 검증 불가 비율 근거를 남긴다.
        assert "전부 검증 불가 10건" in o.reason
        assert dict(o.facts)["검증 불가 비율"].startswith("10/10")

    def test_population_mismatch_is_unmeasured(self, control: pm.Bundle) -> None:
        w = replace(_qa_world(control, 10), qa_expected=11)
        o = pm._solution_qa(w, "scope", _stub(10, 0, 0))
        assert o.state is pm.MetricState.UNMEASURED
        assert "어긋" in o.reason

    def test_zero_population_is_unmeasured(self, control: pm.Bundle) -> None:
        w = replace(_world(control), qa_records=(), qa_expected=0)
        assert pm._solution_qa(w, "scope", _stub(0, 0, 0)).state is pm.MetricState.UNMEASURED

    def test_reverify_exception_keeps_the_type_name(self, control: pm.Bundle) -> None:
        def boom(records: list[dict[str, object]], *, use_fuzz: bool) -> ReverifyReport:
            raise MemoryError("x")

        o = pm._solution_qa(_qa_world(control, 10), "scope", boom)
        assert o.state is pm.MetricState.UNMEASURED
        assert o.error_type == "MemoryError"

    def test_failure_list_is_reported(self, control: pm.Bundle) -> None:
        o = self._run(control, 400, (397, 3, 0))
        assert len(o.unmet) == 3 and all("사유" in line for line in o.unmet)

    def test_population_caveat_vs_scorecard_is_in_the_output(self, control: pm.Bundle) -> None:
        o = self._run(control, 10, (10, 0, 0))
        assert "모집단 주의" in dict(o.facts)


# ──────────────────────────────────────────────────────────────────────────
# 8. ③ Problem Coverage — 명세 스킬 × 승인 문항, 목표는 명세에서 읽는다
# ──────────────────────────────────────────────────────────────────────────
class TestProblemCoverage:
    def test_target_is_read_from_the_spec_not_hardcoded(self, control: pm.Bundle) -> None:
        """명세 목표를 바꾸면 판정이 따라 움직인다 — 하드코딩이면 두 판정이 같다."""
        w = _world(control)
        extra = _v_two_uncovered_skills(control)  # 8/10 = 80%
        loose = dict(_world(extra).spec.targets)
        strict = dict(loose)
        loose["problem_coverage_by_skill"] = ps.Target(value=0.5, reason=None)
        strict["problem_coverage_by_skill"] = ps.Target(value=0.99, reason=None)
        assert w.spec.targets["problem_coverage_by_skill"].value not in (0.5, 0.99)
        ok = pm._problem_coverage(
            replace(_world(extra), spec=replace(_world(extra).spec, targets=loose)), "s"
        )
        bad = pm._problem_coverage(
            replace(_world(extra), spec=replace(_world(extra).spec, targets=strict)), "s"
        )
        assert ok.met is True and ok.target == 0.5
        assert bad.met is False and bad.target == 0.99

    def test_pending_problem_is_not_counted(self, control: pm.Bundle) -> None:
        """승인(approved)만 센다 — 미검수 문항이 스킬을 덮은 것으로 계상되지 않는다."""
        before = pm._problem_coverage(_world(control), "s")
        problems = tuple(
            replace(p, review_status="pending") for p in _world(control).corpus.problems
        )
        after = pm._problem_coverage(_world(_corpus(control, problems=problems)), "s")
        assert before.value == 1.0
        assert after.value == 0.0 and after.met is False

    def test_only_spec_skills_are_counted(self, control: pm.Bundle) -> None:
        w = _world(control)
        skills = dict(w.corpus.type_skills)
        skills["ptype.syn-0"] = skills["ptype.syn-0"] + ("skill.not-in-spec",)
        got = pm._problem_coverage(_world(_corpus(control, type_skills=skills)), "s")
        assert got.denominator == len(w.spec.skills)

    def test_uncovered_skills_are_named(self, control: pm.Bundle) -> None:
        got = pm._problem_coverage(_world(_v_two_uncovered_skills(control)), "s")
        assert {line.split(":")[0] for line in got.unmet} == {
            "skill.synthetic-a",
            "skill.synthetic-b",
        }

    def test_zero_skills_is_unmeasured(self, control: pm.Bundle) -> None:
        got = pm._problem_coverage(_world(_spec_of(control, skills=())), "s")
        assert got.state is pm.MetricState.UNMEASURED

    def test_missing_target_key_is_a_config_error_not_a_pass(self, control: pm.Bundle) -> None:
        targets = {
            k: v
            for k, v in _world(control).spec.targets.items()
            if k != "problem_coverage_by_skill"
        }
        broken = _spec_of(control, targets=targets)
        with pytest.raises(pm.MetricsConfigError):
            pm._problem_coverage(_world(broken), "s")
        got = _by_key(pm.evaluate_bundle(broken))[_K.PROBLEM_COVERAGE]
        assert got.state is pm.MetricState.UNMEASURED  # 가드가 그 지표만 측정 실패로 만든다


# ──────────────────────────────────────────────────────────────────────────
# 9. ② Concept Completeness — 측정 불가 연결은 충족도 미달도 아니다
# ──────────────────────────────────────────────────────────────────────────
class TestCompletenessInterval:
    def test_unmeasured_hint_with_everything_else_linked_is_unmeasured(
        self, control: pm.Bundle
    ) -> None:
        o = _by_key(pm.evaluate_bundle(_corpus(control, hint_problem_ids=None)))[
            _K.CONCEPT_COMPLETENESS
        ]
        assert o.state is pm.MetricState.UNMEASURED
        assert "hint" in o.reason

    def test_unmeasured_hint_with_a_missing_link_is_a_confirmed_violation(
        self, control: pm.Bundle
    ) -> None:
        """교수 연결이 모든 개념에서 끊겨 있으면 힌트가 어떻든 미달이 확정이다(오늘의 실 상태)."""
        injected = _inject(control, _corpus(control, hint_problem_ids=None, objectives=()))
        o = _by_key(pm.evaluate_bundle(injected))[_K.CONCEPT_COMPLETENESS]
        assert o.state is pm.MetricState.MEASURED and o.met is False
        assert o.numerator == 0

    def test_unmeasured_hint_does_not_rescue_a_concept(self, control: pm.Bundle) -> None:
        """한 개념의 해설을 지우고 힌트도 측정 불가 — 나머지는 '미정' 구간이라도 목표 95% 는 불가능."""
        no_hint = _inject(control, _corpus(control, hint_problem_ids=None))
        injected = _inject(no_hint, _v_drop_explanation(no_hint))
        o = _by_key(pm.evaluate_bundle(injected))[_K.CONCEPT_COMPLETENESS]
        # c = 0, 가능 상한 = 9/10 = 90% < 95% → 미달 확정
        assert o.state is pm.MetricState.MEASURED and o.met is False

    def test_measured_hint_everywhere_is_met(self, control: pm.Bundle) -> None:
        o = _by_key(pm.evaluate_bundle(control))[_K.CONCEPT_COMPLETENESS]
        assert o.met is True and o.numerator == o.denominator

    def test_measured_empty_hint_is_a_violation_not_unmeasured(self, control: pm.Bundle) -> None:
        o = _by_key(pm.evaluate_bundle(_corpus(control, hint_problem_ids=frozenset())))[
            _K.CONCEPT_COMPLETENESS
        ]
        assert o.state is pm.MetricState.MEASURED and o.met is False


# ──────────────────────────────────────────────────────────────────────────
# 10. ⑤ Learning Loop — LOOP_COMPLETION 재사용, 주입은 측정이 아니다
# ──────────────────────────────────────────────────────────────────────────
class TestLearningLoop:
    def _eval(self, observation: lkg.Observation | None, *, injected: bool = True,
              basis: str = "synthetic") -> pm.MetricOutcome:  # fmt: skip
        return pm._loop_outcome(
            observation,
            injected=injected,
            window=pm._SELF_CHECK_WINDOW,
            run_id="t",
            sample_basis=basis,
        )

    def test_judgement_is_the_loop_gates_own(self) -> None:
        """같은 관측치에 대한 판정이 loop_kpi_gate 의 것과 일치한다(새 정의를 만들지 않았다)."""
        for num, den in ((200, 200), (190, 200), (150, 200), (20, 20), (1, 1)):
            mine = self._eval(_loop(num, den))
            theirs = lkg.evaluate(
                {lkg.LoopKpi.LOOP_COMPLETION: _loop(num, den)},
                window=pm._SELF_CHECK_WINDOW, run_id="t", sample_basis="synthetic",
            ).outcomes[0]  # fmt: skip
            assert mine.met is (theirs.verdict is lkg.KpiVerdict.passed), (num, den)

    def test_target_is_the_loop_gates_threshold(self) -> None:
        assert (
            self._eval(_loop(200, 200)).target
            == lkg.spec_for(lkg.LoopKpi.LOOP_COMPLETION).threshold
        )

    def test_injected_numbers_are_labelled_as_not_a_measurement(self) -> None:
        injected = self._eval(_loop(200, 200), injected=True)
        measured = self._eval(_loop(200, 200), injected=False, basis="live")
        assert injected.basis == pm.BASIS_INJECTED
        assert measured.basis == pm.BASIS_MEASURED
        assert "주입 경고" in dict(injected.facts)
        assert "주입 경고" not in dict(measured.facts)

    def test_synthetic_sample_basis_is_stamped(self) -> None:
        facts = dict(self._eval(_loop(200, 200), basis="synthetic").facts)
        assert facts["표본 기준"] == "synthetic"
        assert "합성 표본" in facts
        assert "합성 표본" not in dict(self._eval(_loop(200, 200), basis="live").facts)

    def test_missing_observation_is_unmeasured(self) -> None:
        o = self._eval(None)
        assert o.state is pm.MetricState.UNMEASURED and o.value is None


# ──────────────────────────────────────────────────────────────────────────
# 11. ⑥ Critical Defect — Hard Gate 흡수, '해당 없음'과 '판정 불가'는 다르다
# ──────────────────────────────────────────────────────────────────────────
class TestCriticalDefect:
    def _payload(self, control: pm.Bundle) -> dict[str, Any]:
        assert control.defect_payload is not None
        return json.loads(json.dumps(control.defect_payload))

    def test_control_payload_has_zero_defects_over_five_gates(self, control: pm.Bundle) -> None:
        o = pm._critical_defect(control.defect_payload, injected=True)
        assert (o.numerator, o.denominator, o.met) == (0, 5, True)
        assert [label for label, _ in o.facts] == list(pm._HARD_GATE_CODES)

    @pytest.mark.parametrize("gate", ["F-Ⅰ", "F-Ⅱ", "F-Ⅲ", "F-Ⅳ", "F-Ⅴ"])
    def test_each_gate_triggers_exactly_one_defect(self, control: pm.Bundle, gate: str) -> None:
        payload = self._payload(control)
        if gate == "F-Ⅰ":
            payload["hit"]["baseline_anchor_median_minutes"] = {"A3": 13.0, "A4": 6.0}
        elif gate == "F-Ⅱ":
            payload["content"]["reviewed_math_errors"] = 50
        elif gate == "F-Ⅲ":
            payload["failure_distribution"]["judgment_hits"] = 95
        elif gate == "F-Ⅳ":
            for a in ("A1", "A2", "A3"):
                payload["anchors"][a] = False
        else:
            payload["content"]["hint_leak_hits"] = 30
        o = pm._critical_defect(payload, injected=True)
        assert o.state is pm.MetricState.MEASURED and o.met is False
        assert o.numerator == 1, o.unmet
        assert o.unmet[0].startswith(gate)

    def test_empty_payload_is_unmeasured_not_zero_defects(self) -> None:
        o = pm._critical_defect({}, injected=True)
        assert o.state is pm.MetricState.UNMEASURED
        assert o.value is None

    def test_none_payload_is_unmeasured(self) -> None:
        assert pm._critical_defect(None, injected=False).state is pm.MetricState.UNMEASURED

    def test_partial_payload_without_a_trigger_is_unmeasured(self, control: pm.Bundle) -> None:
        """F-Ⅱ 만 있고 해당 없음 — 나머지 4게이트는 판정 불가라 '0건'이라 말할 수 없다."""
        full = self._payload(control)
        partial = {
            "content": {
                k: full["content"][k] for k in ("reviewed_math_errors", "reviewed_cu_total")
            }
        }
        o = pm._critical_defect(partial, injected=True)
        assert o.state is pm.MetricState.UNMEASURED
        assert "판정 불가" in o.reason

    def test_partial_payload_with_a_trigger_is_a_confirmed_defect(self, control: pm.Bundle) -> None:
        """해당 1건이면 나머지가 판정 불가여도 확정 위반이다(알 수 없는 것이 확정을 지우지 않는다)."""
        partial = {"content": {"reviewed_math_errors": 50, "reviewed_cu_total": 1000}}
        o = pm._critical_defect(partial, injected=True)
        assert o.state is pm.MetricState.MEASURED and o.met is False and o.numerator == 1

    def test_malformed_payload_is_unmeasured_with_the_type_name(self) -> None:
        o = pm._critical_defect({"hit": "문자열"}, injected=True)
        assert o.state is pm.MetricState.UNMEASURED
        assert o.error_type == "AttributeError"

    def test_malformed_baseline_values_do_not_crash(self) -> None:
        o = pm._critical_defect(
            {"hit": {"baseline_anchor_median_minutes": {"A3": "x"}}}, injected=True
        )
        assert o.state is pm.MetricState.UNMEASURED
        assert o.error_type == "ValueError"

    def test_gate_codes_are_the_scorecards(self, control: pm.Bundle) -> None:
        codes = tuple(g.code for g in vs.evaluate_hard_gates(self._payload(control)))
        assert codes == pm._HARD_GATE_CODES


# ──────────────────────────────────────────────────────────────────────────
# 12. 평면·이름 — 정본이 셋이 되지 않는다
# ──────────────────────────────────────────────────────────────────────────
class TestPlanes:
    def test_metric_names_do_not_collide_with_other_planes(self) -> None:
        mine = {k.value for k in pm.MetricKey}
        assert mine.isdisjoint({k.value for k in lkg.LoopKpi})
        assert mine.isdisjoint({s.payload_key for s in vs.KPI_SOURCES})

    def test_render_names_both_planes_and_stamps_run_id_and_time(self, control: pm.Bundle) -> None:
        report = pm.MetricsReport(
            run_id="abc123", observed_at=datetime(2026, 10, 9, tzinfo=UTC),
            sample_basis="synthetic", spec_id="phase3-scope-v1",
            outcomes=pm.evaluate_bundle(control),
        )  # fmt: skip
        text = pm.render(report)
        assert "제품 완성도 평면" in text
        assert "생산 공정 평면" in text and "KPI 12종" in text
        assert "abc123" in text and "2026-10-09" in text
        payload = report.as_dict()
        assert payload["plane"] == pm.PLANE_NAME and payload["other_plane"] == pm.OTHER_PLANE_NAME
        assert payload["run_id"] == "abc123" and payload["observed_at"].startswith("2026-10-09")

    def test_unmeasured_is_not_rendered_like_a_pass(self, control: pm.Bundle) -> None:
        report = pm.MetricsReport(
            run_id="r", observed_at=datetime.now(UTC), sample_basis="live", spec_id=None,
            outcomes=pm.evaluate_bundle(replace(control, loop=None, defect_payload=None)),
        )  # fmt: skip
        text = pm.render(report)
        assert "[ 미측정]" in text
        assert "측정 불가" in text
        assert "종합: 측정 실패" in text


# ──────────────────────────────────────────────────────────────────────────
# 13. 거버넌스 — 수치 복제 금지·소스 일치
# ──────────────────────────────────────────────────────────────────────────
class TestGovernance:
    def test_problem_glob_matches_the_p3_02_loader(self) -> None:
        assert pm._PROBLEM_GLOB == p3c._PROBLEM_GLOB

    def test_absorbed_numbers_are_not_duplicated_in_source(self) -> None:
        """0.995(=1-0.005)·0.98·0.005 는 다른 정본이 갖는 수치다 — 이 모듈 코드에 리터럴로 있으면 복제다."""
        tree = ast.parse(Path(pm.__file__).read_text(encoding="utf-8"))
        floats = {
            n.value
            for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, float)
        }
        assert floats.isdisjoint({0.995, 0.005, 0.98}), floats & {0.995, 0.005, 0.98}

    def test_module_imports_scorecard_threshold_table(self) -> None:
        assert pm.CONTENT_KPI_THRESHOLDS is vs.CONTENT_KPI_THRESHOLDS

    def test_loop_reuse_is_by_import(self) -> None:
        assert pm.lkg is lkg
        assert pm.evaluate_hard_gates is vs.evaluate_hard_gates

    def test_p3_02_module_is_untouched_by_name(self) -> None:
        """P3-02 의 공개 함수만 쓴다 — 비공개 심볼은 이 모듈 소스에 나타나지 않는다."""
        src = Path(pm.__file__).read_text(encoding="utf-8")
        assert "p3c._" not in src


# ──────────────────────────────────────────────────────────────────────────
# 14. 자가 점검
# ──────────────────────────────────────────────────────────────────────────
class TestSelfCheck:
    def test_self_check_passes_on_the_real_spec(self) -> None:
        result = pm.run_self_check()
        assert result.exit_code == 0, result.failures
        assert len(result.rows) >= 1 + 7 + 7 + 3

    def test_self_check_reports_failure_when_a_metric_does_not_react(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """무반응 지표를 만들면(위반을 주입해도 충족을 내는 판정) 자가 점검이 exit 1 을 낸다."""
        monkeypatch.setattr(pm, "judge_ratio", lambda value, target: True)
        result = pm.run_self_check()
        assert result.exit_code == 1
        assert result.failures

    def test_self_check_fails_on_noop_injection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        noop = pm.Injection("무변경", _K.CURRICULUM_COVERAGE, lambda b: b)
        monkeypatch.setattr(pm, "VIOLATION_INJECTIONS", (noop,))
        result = pm.run_self_check()
        assert result.exit_code == 1
        assert any("무변경" in name for name, ok, _ in result.rows if not ok)

    def test_self_check_fails_when_unmeasured_folds_to_pass(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real = pm.compose

        def lenient(outcomes: Any) -> pm.Composite:
            kept = tuple(o for o in outcomes if o.state is not pm.MetricState.UNMEASURED)
            return real(kept) if len(kept) == len(tuple(outcomes)) else pm.Composite.ALL_MET

        monkeypatch.setattr(pm, "compose", lenient)
        assert pm.run_self_check().exit_code == 1

    def test_self_check_fails_when_a_violation_injection_moves_other_metrics(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """'그 지표만 떨어진다' — 주입이 다른 지표까지 흔들면(두 지표가 같은 것을 재는 신호) 실패여야 한다."""

        def drop_all_problems(b: pm.Bundle) -> pm.Bundle:
            return _corpus(b, problems=())

        wide = pm.Injection("문항 전부 삭제", _K.CURRICULUM_COVERAGE, drop_all_problems)
        monkeypatch.setattr(pm, "VIOLATION_INJECTIONS", (wide,))
        result = pm.run_self_check()
        assert result.exit_code == 1
        failing = [d for name, ok, d in result.rows if not ok and "문항 전부 삭제" in name]
        assert failing and "함께 변한 지표" in failing[0]

    def test_self_check_fails_when_an_isolated_unmeasured_injection_moves_others(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def no_core_concepts(b: pm.Bundle) -> pm.Bundle:
            concepts = tuple(replace(c, core=False) for c in _world(b).spec.concepts)
            return _spec_of(b, concepts=concepts)

        claims_isolated = pm.Injection(
            "핵심 개념 0건(격리라고 주장)", _K.GRAPH_CONNECTIVITY, no_core_concepts, isolated=True
        )
        monkeypatch.setattr(pm, "UNMEASURED_INJECTIONS", (claims_isolated,))
        assert pm.run_self_check().exit_code == 1

    def test_self_check_is_deterministic(self) -> None:
        a = pm.run_self_check()
        b = pm.run_self_check()
        assert a.rows == b.rows


# ──────────────────────────────────────────────────────────────────────────
# 15. CLI
# ──────────────────────────────────────────────────────────────────────────
@pytest.fixture
def patched_world(monkeypatch: pytest.MonkeyPatch, control: pm.Bundle) -> pm.World:
    """실 코퍼스(약 20초) 대신 합성 세계를 `load_world` 로 돌려준다."""
    world = _world(control)
    monkeypatch.setattr(pm, "load_world", lambda spec_path=None, repo_root=None: world)
    return world


def _write(tmp_path: Path, name: str, payload: Any) -> str:
    target = tmp_path / name
    target.write_text(json.dumps(payload), encoding="utf-8")
    return str(target)


class TestCli:
    def test_self_check_exit_zero_and_json(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out = tmp_path / "sc.json"
        assert pm.main(["--self-check", "--json", str(out)]) == 0
        text = capsys.readouterr().out
        assert "자가 점검" in text and "run_id" in text and "관측 시각" in text
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["mode"] == "self-check" and data["exit_code"] == 0 and data["run_id"] != "-"

    @pytest.mark.parametrize(
        "flag", [["--no-db"], ["--sample-basis", "synthetic"], ["--spec", "x.yaml"]]
    )
    def test_self_check_rejects_measurement_options(self, flag: list[str]) -> None:
        assert pm.main(["--self-check", *flag]) == 3

    def test_argparse_errors_exit_3_not_2(self, capsys: pytest.CaptureFixture[str]) -> None:
        """argparse 기본 종료코드 2 는 '측정 실패'와 겹친다 — 인자 오류는 3 이다."""
        assert pm.main(["--no-such-flag"]) == 3
        assert pm.main(["--sample-basis", "bogus"]) == 3

    def test_nonpositive_window_is_a_runtime_error(self) -> None:
        assert pm.main(["--since-hours", "0", "--no-db"]) == 3

    def test_injection_without_sample_basis_is_refused(
        self, tmp_path: Path, patched_world: pm.World
    ) -> None:
        path = _write(
            tmp_path, "loop.json", {"loop_completion_rate": {"numerator": 1, "denominator": 1}}
        )
        assert pm.main(["--no-db", "--input", path]) == 3
        payload = _write(tmp_path, "p.json", {})
        assert pm.main(["--no-db", "--hard-gate-input", payload]) == 3

    def test_no_db_without_inputs_is_measurement_failure_exit_2(
        self, patched_world: pm.World, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert pm.main(["--no-db"]) == 2
        text = capsys.readouterr().out
        assert "[ 미측정] 5." in text and "[ 미측정] 6." in text
        assert "종합: 측정 실패" in text

    def test_full_injection_run_is_exit_0_and_labelled_injected(
        self,
        tmp_path: Path,
        patched_world: pm.World,
        control: pm.Bundle,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        loop = _write(
            tmp_path, "loop.json", {"loop_completion_rate": {"numerator": 200, "denominator": 200}}
        )
        gates = _write(tmp_path, "gates.json", control.defect_payload)
        out = tmp_path / "out.json"
        code = pm.main(
            ["--no-db", "--sample-basis", "synthetic", "--input", loop, "--hard-gate-input", gates,
             "--json", str(out)]
        )  # fmt: skip
        captured = capsys.readouterr()
        assert code == 0, captured.out
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["exit_code"] == 0 and data["composite"] == "all_met"
        assert data["sample_basis"] == "synthetic" and data["run_id"] and data["observed_at"]
        by = {m["key"]: m for m in data["metrics"]}
        assert by["learning_loop_success"]["basis"] == "injected"
        assert by["critical_defect"]["basis"] == "injected"
        assert by["curriculum_coverage"]["basis"] == "measured"
        assert "주입값(--input)" in captured.out  # 사람이 읽는 표에도 '측정이 아님'이 각인된다

    def test_violation_with_everything_measured_is_exit_1(
        self, tmp_path: Path, patched_world: pm.World, control: pm.Bundle
    ) -> None:
        loop = _write(
            tmp_path, "loop.json", {"loop_completion_rate": {"numerator": 100, "denominator": 200}}
        )
        gates = _write(tmp_path, "gates.json", control.defect_payload)
        code = pm.main(
            ["--no-db", "--sample-basis", "synthetic", "--input", loop, "--hard-gate-input", gates]
        )
        assert code == 1

    def test_input_rejects_thresholds_and_foreign_kpis(
        self, tmp_path: Path, patched_world: pm.World
    ) -> None:
        with_threshold = _write(
            tmp_path, "a.json",
            {"loop_completion_rate": {"numerator": 1, "denominator": 1, "threshold": 0.1}},
        )  # fmt: skip
        foreign = _write(
            tmp_path, "b.json", {"state_integrity": {"numerator": 0, "denominator": 5}}
        )
        for path in (with_threshold, foreign):
            assert pm.main(["--no-db", "--sample-basis", "synthetic", "--input", path]) == 3

    def test_unreadable_inputs_are_runtime_errors(
        self, tmp_path: Path, patched_world: pm.World
    ) -> None:
        missing = str(tmp_path / "nope.json")
        assert pm.main(["--no-db", "--sample-basis", "synthetic", "--input", missing]) == 3
        assert (
            pm.main(["--no-db", "--sample-basis", "synthetic", "--hard-gate-input", missing]) == 3
        )
        array = _write(tmp_path, "arr.json", [1, 2])
        assert pm.main(["--no-db", "--sample-basis", "synthetic", "--hard-gate-input", array]) == 3

    def test_unexpected_exception_is_exit_3_not_1(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def boom(spec_path: Any = None, repo_root: Any = None) -> pm.World:
            raise RuntimeError("예상 밖")

        monkeypatch.setattr(pm, "load_world", boom)
        assert pm.main(["--no-db"]) == 3
        assert "RuntimeError" in capsys.readouterr().err

    def test_unwritable_json_is_runtime_error(
        self, tmp_path: Path, patched_world: pm.World
    ) -> None:
        blocker = tmp_path / "file"
        blocker.write_text("x", encoding="utf-8")
        assert pm.main(["--no-db", "--json", str(blocker / "sub" / "o.json")]) == 3

    def test_evidence_lines_carry_run_id_and_per_metric_progress(
        self, tmp_path: Path, patched_world: pm.World
    ) -> None:
        ev = tmp_path / "ev.ndjson"
        pm.main(["--no-db", "--evidence", str(ev)])
        lines = [json.loads(x) for x in ev.read_text(encoding="utf-8").splitlines()]
        assert len({ln["run_id"] for ln in lines}) == 1
        done = [ln["metric"] for ln in lines if ln["phase"] == "metric_done"]
        assert sorted(done) == sorted(k.value for k in pm.METRIC_ORDER)
        assert lines[0]["phase"] == "run_start" and lines[-1]["phase"] == "run_end"

    def test_world_load_failure_is_measurement_failure_with_type_name(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        failure = pm.WorldFailure("corpus", "CoverageError", "코퍼스 0건")
        monkeypatch.setattr(pm, "load_world", lambda spec_path=None, repo_root=None: failure)
        assert pm.main(["--no-db"]) == 2
        out = capsys.readouterr().out
        assert "CoverageError" in out and "[ 미측정] 1." in out


class TestDbCollection:
    def test_connect_failure_is_unmeasured_with_exception_type(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def no_dispose() -> None:
            return None

        def boom() -> Any:
            raise ConnectionRefusedError("x")

        monkeypatch.setattr(pm, "get_sessionmaker", boom)
        monkeypatch.setattr(pm, "dispose_engine", no_dispose)
        evidence = lkg.EvidenceWriter(None, run_id="t", window=pm._SELF_CHECK_WINDOW)
        obs = asyncio.run(
            pm._collect_loop_observation(
                pm._SELF_CHECK_WINDOW, evidence=evidence, timeout_seconds=1.0
            )
        )
        assert obs.unmeasured_reason is not None and obs.error_type == "ConnectionRefusedError"
        # 이 관측치는 ⑤ 를 미측정으로 만든다(0 도 통과도 아니다).
        o = pm._loop_outcome(
            obs, injected=False, window=pm._SELF_CHECK_WINDOW, run_id="t", sample_basis="live"
        )
        assert o.state is pm.MetricState.UNMEASURED and o.error_type == "ConnectionRefusedError"

    def test_db_mode_uses_the_collected_observation(
        self,
        monkeypatch: pytest.MonkeyPatch,
        patched_world: pm.World,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        async def fake(window: Any, *, evidence: Any, timeout_seconds: float) -> lkg.Observation:
            return lkg.Observation(
                kpi=lkg.LoopKpi.LOOP_COMPLETION, unmeasured_reason="DB 세션 확보 실패(OSError)",
                source="db_unavailable", error_type="OSError",
            )  # fmt: skip

        monkeypatch.setattr(pm, "_collect_loop_observation", fake)
        assert pm.main([]) == 2
        out = capsys.readouterr().out
        assert "OSError" in out


# ──────────────────────────────────────────────────────────────────────────
# 16. 실 코퍼스 적재 — 구조 사실만 고정한다(수치는 고정하지 않는다)
# ──────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def loaded() -> pm.World:
    world = pm.load_world()
    assert isinstance(world, pm.World), getattr(world, "reason", "")
    return world


class TestRealCorpusWiring:
    def test_qa_records_are_exactly_the_eligible_problems(self, loaded: pm.World) -> None:
        eligible = {
            p.problem_id
            for p in loaded.corpus.problems
            if p.review_status == p3c.PROBLEM_ELIGIBLE_STATUS
        }
        assert loaded.qa_expected == len(eligible) > 0
        assert len(loaded.qa_records) == loaded.qa_expected
        assert {r["problem_id"] for r in loaded.qa_records} == eligible

    def test_seven_outcomes_with_stubbed_reverify(self, loaded: pm.World) -> None:
        """재검증만 스텁(실 재검증은 약 15초) — 나머지 6종은 실 코퍼스로 계산된다."""
        outcomes = pm.evaluate_all(
            loaded,
            loop_observation=None, loop_injected=False,
            defect_payload=None, defect_injected=False,
            window=pm._SELF_CHECK_WINDOW, run_id="t", sample_basis="live",
            reverify=_stub(len(loaded.qa_records), 0, 0),
        )  # fmt: skip
        assert [o.key for o in outcomes] == list(pm.METRIC_ORDER)
        got = _by_key(outcomes)
        # 입력이 없는 두 지표는 0 이 아니라 측정 실패다 — 오늘의 실 상태에서 종합은 측정 실패.
        assert got[_K.LEARNING_LOOP_SUCCESS].state is pm.MetricState.UNMEASURED
        assert got[_K.CRITICAL_DEFECT].state is pm.MetricState.UNMEASURED
        assert pm.compose(outcomes) is pm.Composite.MEASUREMENT_FAILED
        assert got[_K.CURRICULUM_COVERAGE].denominator == len(loaded.spec.nodes)

    def test_unreadable_spec_path_is_a_world_failure_not_an_exception(self, tmp_path: Path) -> None:
        failure = pm.load_world(tmp_path / "missing.yaml")
        assert isinstance(failure, pm.WorldFailure)
        assert failure.stage == "spec" and failure.error_type

    def test_empty_corpus_root_is_a_world_failure(self, tmp_path: Path) -> None:
        failure = pm.load_world(None, tmp_path)
        assert isinstance(failure, pm.WorldFailure)
        assert failure.error_type
