"""오답 → 교정 전략 전 구간 계측기(P3-06) — 계측기가 실제 서빙 경로를 재고 있는가, 그리고 깨진 구간을 알아채는가.

계측기가 초록을 낸다는 사실은 증거가 아니다. 두 가지를 실행으로 확인한다:

  A. **계측기는 서빙 설정에 반응한다.** 선지 연결 플래그나 훑기 킬 스위치를 끄면 결과가 떨어져야 한다.
     계측기가 서빙 함수를 거치지 않고 자체 사본으로 채널을 합류시키고 있다면 이 주입에 반응하지 않는다.
  B. **구간 하나를 망가뜨리면 해당 오개념이 FAIL이 된다**: 서명 규칙 제거 · 교정 행 제거 · 쉬운 문항
     조건이 코퍼스에 안 닿음 · 대조 무력화(오탐 전수 점검). 측정 자체가 불가하면 종료 코드 3.

기준선(2026-10-16 실측)은 핵심 12개 중 좌석 있음 7 · PASS 7 · NO_SEAT 5다. NO_SEAT는 PASS가 아니라
**후보를 낼 수 없다는 사실의 보고**이며, 이 테스트가 그 5건의 정체를 동결한다.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import select

from whymath_backend.api import _isolated_call
from whymath_backend.config import get_settings
from whymath_backend.db.models.problem import Problem
from whymath_backend.harness import wrong_answer_remediation_report as rep
from whymath_backend.l1.misconception import wrong_answer_tables as tables
from whymath_backend.l1.standards.phase3_coverage import load_corpus
from whymath_backend.l1.standards.phase3_scope import load_reference_index, load_scope_spec
from whymath_backend.l4.misconception import derivative_signature as ds

_UNSEATED = ["M0673", "M0674", "M0676", "M0677", "M0678"]
_SEATED = ["M0075", "M0080", "M0670", "M0671", "M0672", "M0864", "M0865"]


def _configure(mp: pytest.MonkeyPatch, **env: str) -> None:
    """설정 환경변수를 바꾸고 캐시를 비운다 — 기존 격리 테스트와 같은 관례."""
    mp.setenv("WHYMATH_JWT_SECRET_KEY", "test-secret-0123456789abcdef")
    mp.setenv("WHYMATH_SYMPY_ISOLATION_ENABLED", "false")
    for key, value in env.items():
        mp.setenv(key, value)
    get_settings.cache_clear()
    _isolated_call.reset_pool_for_tests()


@pytest.fixture
def inline(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """인라인(격리 끔) 설정 — 결정론·속도. 끝나면 설정 캐시를 되돌려 타 테스트로 새지 않게 한다."""
    _configure(monkeypatch)
    yield
    monkeypatch.undo()
    get_settings.cache_clear()
    _isolated_call.reset_pool_for_tests()


@pytest.fixture(scope="module")
def report() -> Iterator[rep.Report]:
    """기준선 보고서 — 모듈 안에서 한 번만 만든다(오탐 전수 점검은 별도 테스트가 재현한다)."""
    mp = pytest.MonkeyPatch()
    try:
        _configure(mp)
        yield asyncio.run(rep.build_report(rep._build_detector(), sweep=False))
    finally:
        mp.undo()
        get_settings.cache_clear()
        _isolated_call.reset_pool_for_tests()


@pytest.fixture(scope="module")
def corpus_ctx() -> tuple[Any, Any, Any]:
    spec = load_scope_spec()
    return spec, load_reference_index(spec), load_corpus(spec)


@pytest.fixture(scope="module")
def problems() -> list[rep.BankProblem]:
    rows = list(rep.iter_approved_problems())
    assert len(rows) > 3000
    return rows


def _row(mis_id: str, kebab: str) -> rep.MisconceptionRow:
    return rep.MisconceptionRow(mis_id=mis_id, concept_code="[12미적Ⅰ-02-07]", kebab_id=kebab)


# ── 기준선 ─────────────────────────────────────────────────────────────────────────────────


class TestBaseline:
    def test_twelve_core_misconceptions_seven_pass_five_have_no_seat(
        self, report: rep.Report
    ) -> None:
        assert len(report.rows) == 12
        assert sorted(r.mis_id for r in report.rows if r.status == "PASS") == sorted(_SEATED)
        assert report.gaps == _UNSEATED
        assert report.failures == []
        assert report.exit_code == 0
        assert (report.seated_total, report.seated_pass) == (7, 7)

    @pytest.mark.parametrize("mis_id", _SEATED)
    def test_every_seated_misconception_is_closed_end_to_end(
        self, report: rep.Report, mis_id: str
    ) -> None:
        row = next(r for r in report.rows if r.mis_id == mis_id)
        assert row.kebab_id is not None
        # ② 오답 → 후보: 서명 픽스처와 표시된 보기 모두 전건 후보가 난다(분모 0은 공허).
        assert row.signature_wrong[1] > 0 and row.signature_wrong[0] == row.signature_wrong[1]
        assert row.choice_reproduced[1] > 0 and row.choice_reproduced[0] == row.choice_reproduced[1]
        # ③ 오탐 픽스처: 전건 후보가 안 난다(분모 0이면 공허).
        assert row.signature_clean[1] > 0 and row.signature_clean[0] == row.signature_clean[1]
        # ④ 후보 → 교정: 사다리 세 칸 전부 ADVICE이고 선택 조건이 코퍼스에 닿는다.
        assert row.rungs_ready and all(row.rungs_ready.values()) and len(row.rungs_ready) == 3
        assert (row.easier_matches or 0) > 0
        assert (row.prerequisite_atoms or 0) > 0
        # 신뢰도: 게이트(0.65)를 넘고 1.0은 아니다(직접 증거도 포화시키지 않는다).
        assert row.min_confidence is not None and 0.65 <= row.min_confidence < 1.0
        assert row.problems == []

    def test_the_five_unseated_are_named_gaps_not_passes(self, report: rep.Report) -> None:
        for row in (r for r in report.rows if r.mis_id in _UNSEATED):
            assert row.status == "NO_SEAT" and row.kebab_id is None
            assert row.rule_ids == () and row.signature_wrong == (0, 0)
            assert row.problems, "갭의 사유가 보고에 있어야 한다"

    def test_m0674_is_reached_by_the_instrument_but_dropped_by_serving(
        self, report: rep.Report
    ) -> None:
        """계측기(phase3_coverage)는 닿았다고 세지만 서빙은 M-id 보기를 버린다 — 그 이음새가 숫자로 드러난다."""
        row = next(r for r in report.rows if r.mis_id == "M0674")
        assert row.direct_mis_id_tags == 12
        assert "서빙이 버린다" in " ".join(row.problems)

    def test_m0075_and_m0672_share_one_runtime_key(self, report: rep.Report) -> None:
        a = next(r for r in report.rows if r.mis_id == "M0075")
        b = next(r for r in report.rows if r.mis_id == "M0672")
        assert (
            a.kebab_id == b.kebab_id and a.shared_with == ("M0672",) and b.shared_with == ("M0075",)
        )

    def test_signature_reach_versus_the_independent_oracle_is_disclosed(
        self, report: rep.Report
    ) -> None:
        """서명 독법 단독 재현율이 보고에 실린다 — 선지 채널의 100%를 서명의 성과로 오독하지 않게 한다."""
        by = {r.mis_id: r.signature_vs_oracle for r in report.rows}
        assert by["M0671"] == (24, 66) and by["M0864"] == (56, 56) and by["M0080"] == (36, 36)

    def test_json_and_table_render(self, report: rep.Report) -> None:
        doc = rep.to_json(report)
        assert doc["seated_pass"] == 7 and doc["gaps"] == _UNSEATED
        assert doc["false_positive_sweep"]["ran"] is False
        text = rep.render(report)
        assert "건너뜀" in text, "오탐 점검을 건너뛴 보고가 '0건'으로 읽히면 안 된다"
        assert all(m in text for m in _SEATED + _UNSEATED)


# ── A. 계측기는 서빙 설정에 반응한다 ───────────────────────────────────────────────────────


class TestInstrumentFollowsTheServingPath:
    @staticmethod
    def _measure_choices(
        mis_id: str, kebab: str, problems: list[rep.BankProblem]
    ) -> rep.MisconceptionRow:
        row = _row(mis_id, kebab)
        asyncio.run(rep._measure_choices(row, problems, rep._build_detector(), []))
        return row

    def test_turning_off_the_distractor_channel_drops_the_reproduction(
        self, monkeypatch: pytest.MonkeyPatch, problems: list[rep.BankProblem]
    ) -> None:
        """선지 연결 플래그를 끄면 표시된 보기 재현이 떨어진다 — 계측기가 서빙의 채널 합류를 지난다는 증거."""
        _configure(monkeypatch)
        on = self._measure_choices("M0671", "power-rule-step-omitted", problems)
        assert on.choice_reproduced[0] == on.choice_reproduced[1] > 0
        _configure(monkeypatch, WHYMATH_L4_DISTRACTOR_LINK_ENABLED="false")
        off = self._measure_choices("M0671", "power-rule-step-omitted", problems)
        assert off.choice_reproduced[1] == on.choice_reproduced[1], "분모가 같아야 비교가 된다"
        assert off.choice_reproduced[0] < on.choice_reproduced[0], "끄는 주입이 결과에 닿지 않았다"
        # 끈 뒤에도 서명 채널(텍스트)이 남은 만큼은 재현된다 — 선지 채널이 아니라 서명이 일한 몫.
        assert (
            off.choice_reproduced[0] == off.signature_vs_oracle[0] or off.signature_vs_oracle[0] > 0
        )

    def test_the_master_kill_switch_silences_every_channel(
        self, monkeypatch: pytest.MonkeyPatch, problems: list[rep.BankProblem]
    ) -> None:
        _configure(monkeypatch, WHYMATH_L4_ATTEMPT_MISCONCEPTION_SCAN_ENABLED="false")
        off = self._measure_choices("M0864", "extremum-max-min-confused", problems)
        assert off.choice_reproduced[1] > 0 and off.choice_reproduced[0] == 0
        monkeypatch.undo()
        get_settings.cache_clear()

    def test_the_fake_session_refuses_columns_the_serving_function_did_not_use_before(
        self, problems: list[rep.BankProblem]
    ) -> None:
        """서빙 함수가 새 열을 읽기 시작하면 계측기가 조용히 None을 돌려주며 초록을 내지 않고 터진다."""
        session = rep._ProblemSession(problems[0])
        with pytest.raises(RuntimeError, match="모르는 열"):
            asyncio.run(session.scalar(select(Problem.problem_id)))
        assert (
            asyncio.run(session.scalar(select(Problem.question_text))) == problems[0].question_text
        )


# ── B. 구간 하나를 망가뜨리면 FAIL이 된다 ──────────────────────────────────────────────────


class TestBrokenSegmentsAreNoticed:
    def test_removing_the_signature_rules_of_a_misconception_is_noticed(
        self, inline: None, monkeypatch: pytest.MonkeyPatch, problems: list[rep.BankProblem]
    ) -> None:
        by_id = {p.problem_id: p for p in problems}
        original = ds.compile_rules()
        mutated = tuple(c for c in original if "M0864" not in c.rule.mis_ids)
        assert len(mutated) < len(original), "주입 미적용 — 테스트 무효"
        monkeypatch.setattr(ds, "compile_rules", lambda: mutated)
        row = _row("M0864", "extremum-max-min-confused")
        asyncio.run(rep._measure_signature(row, by_id, rep._build_detector(), []))
        # 표(데이터)는 규칙과 픽스처를 여전히 선언하는데 엔진이 그 규칙을 모른다 — 어긋남이 문제로 드러난다.
        assert row.rule_ids, "표의 규칙 선언은 그대로여야 이 주입이 '엔진만 빠진' 상태가 된다"
        assert row.signature_wrong[0] == 0 < row.signature_wrong[1]
        assert any("오답 픽스처에서 후보가 나오지 않았다" in p for p in row.problems)

    def test_missing_signature_hit_is_recorded_as_a_problem(
        self, inline: None, monkeypatch: pytest.MonkeyPatch, problems: list[rep.BankProblem]
    ) -> None:
        """대조를 항상 거짓으로 만들면(규칙은 그대로) 오답 픽스처가 후보를 못 내고 문제로 기록된다."""
        by_id = {p.problem_id: p for p in problems}
        monkeypatch.setattr(ds, "_same_value", lambda *_a, **_k: False)
        row = _row("M0864", "extremum-max-min-confused")
        asyncio.run(rep._measure_signature(row, by_id, rep._build_detector(), []))
        assert row.signature_wrong[0] == 0 < row.signature_wrong[1]
        assert any("후보가 나오지 않았다" in p for p in row.problems)

    def test_over_eager_comparison_is_caught_as_a_false_positive(
        self, inline: None, monkeypatch: pytest.MonkeyPatch, problems: list[rep.BankProblem]
    ) -> None:
        """대조를 항상 참으로 만들면 오탐 픽스처와 정답 오탐 전수 점검이 모두 반응한다."""
        by_id = {p.problem_id: p for p in problems}
        monkeypatch.setattr(ds, "_same_value", lambda *_a, **_k: True)
        row = _row("M0864", "extremum-max-min-confused")
        asyncio.run(rep._measure_signature(row, by_id, rep._build_detector(), []))
        assert row.signature_clean[0] < row.signature_clean[1]
        assert any("오탐" in p for p in row.problems)
        readable = [p for p in problems if "극" in p.question_text][:150]
        hits, scanned = asyncio.run(rep._false_positive_sweep(readable, rep._build_detector()))
        assert scanned == len(readable) and hits > 0

    def test_dropping_a_remediation_row_is_noticed(
        self,
        inline: None,
        monkeypatch: pytest.MonkeyPatch,
        problems: list[rep.BankProblem],
        corpus_ctx: Any,
    ) -> None:
        spec, index, corpus = corpus_ctx
        full = tables.load_remediation_spec()
        mutated = full.model_copy(
            update={"rows": tuple(r for r in full.rows if r.mis_id != "M0864")}
        )
        assert len(mutated.rows) == len(full.rows) - 1, "주입 미적용 — 테스트 무효"
        monkeypatch.setattr(tables, "load_remediation_spec", lambda: mutated)
        row = _row("M0864", "extremum-max-min-confused")
        rep._measure_strategy(row, spec, problems, (corpus, index))
        assert not all(row.rungs_ready.values()), "교정 행이 없는데 사다리가 준비됐다고 나온다"
        assert any("교정표에 M0864 행이 없다" in p for p in row.problems)

    def test_easier_problem_selector_that_reaches_nothing_is_noticed(
        self,
        inline: None,
        monkeypatch: pytest.MonkeyPatch,
        problems: list[rep.BankProblem],
        corpus_ctx: Any,
    ) -> None:
        spec, index, corpus = corpus_ctx
        full = tables.load_remediation_spec()
        victim = next(r for r in full.rows if r.mis_id == "M0864")
        too_hard = victim.easier_problem.model_copy(update={"max_difficulty": 0.1})
        assert too_hard.max_difficulty != victim.easier_problem.max_difficulty
        mutated = full.model_copy(
            update={
                "rows": tuple(
                    r.model_copy(update={"easier_problem": too_hard}) if r.mis_id == "M0864" else r
                    for r in full.rows
                )
            }
        )
        monkeypatch.setattr(tables, "load_remediation_spec", lambda: mutated)
        row = _row("M0864", "extremum-max-min-confused")
        rep._measure_strategy(row, spec, problems, (corpus, index))
        assert row.easier_matches == 0
        assert any("쉬운 문항 선택 조건이 승인 문항에 닿지 않는다" in p for p in row.problems)

    def test_unresolvable_prerequisite_concept_is_noticed(
        self,
        inline: None,
        monkeypatch: pytest.MonkeyPatch,
        problems: list[rep.BankProblem],
        corpus_ctx: Any,
    ) -> None:
        spec, index, corpus = corpus_ctx
        monkeypatch.setattr(rep, "prerequisite_sources_of", lambda *_a, **_k: ())
        row = _row("M0864", "extremum-max-min-confused")
        rep._measure_strategy(row, spec, problems, (corpus, index))
        assert row.prerequisite_atoms == 0
        assert any("선수 원자가 없다" in p for p in row.problems)


# ── 종료 코드 ──────────────────────────────────────────────────────────────────────────────


class TestExitCodes:
    def test_default_run_exits_zero_and_require_all_exits_one_because_of_the_gaps(
        self, inline: None, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert rep.main(["--no-sweep", "--json"]) == 0
        doc = json.loads(capsys.readouterr().out)
        assert doc["gaps"] == _UNSEATED
        assert rep.main(["--no-sweep", "--require-all"]) == 1
        assert "좌석 없는 핵심 오개념 5개" in capsys.readouterr().err

    def test_unmeasurable_input_exits_three_not_a_silent_pass(
        self, inline: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """승인 문항 0건(빈 코퍼스)은 통과가 아니라 측정 실패다."""
        monkeypatch.setattr(rep, "iter_approved_problems", lambda root=None: iter(()))
        assert rep.main(["--no-sweep"]) == 3
        assert "측정 불가" in capsys.readouterr().err

    def test_a_failing_row_makes_the_exit_code_one(self) -> None:
        failing = rep.Report(
            rows=[],
            seated_total=1,
            seated_pass=0,
            gaps=[],
            failures=["M0001: 깨짐"],
            scanned_problems=1,
            false_positive_sweep=(0, 0),
            swept=False,
        )
        assert failing.exit_code == 1


# ── 운영 경로(프로세스 풀 격리)에서도 새 독법이 산다 ───────────────────────────────────────


def test_signature_reading_survives_the_production_process_pool(
    monkeypatch: pytest.MonkeyPatch, problems: list[rep.BankProblem]
) -> None:
    """격리(OPS-96)를 켠 운영 설정에서 워커 프로세스가 규칙표를 읽고 후보를 낸다 — 직렬화·적재·시간 상한."""
    _configure(
        monkeypatch,
        WHYMATH_SYMPY_ISOLATION_ENABLED="true",
        WHYMATH_SYMPY_ISOLATION_MAX_WORKERS="1",
        WHYMATH_SYMPY_ISOLATION_TIMEOUT_S="30",
    )
    try:
        fx = next(
            f
            for r in tables.load_signature_spec().rules
            if r.rule_id == "sig.power-rule.omit-step.derivative-at"
            for f in r.fixtures.wrong
        )
        problem = next(p for p in problems if p.problem_id == fx.problem_id)
        candidates = asyncio.run(
            rep.trace_attempt(
                problem,
                answer=fx.answer,
                selected_choice_index=None,
                detector=rep._build_detector(),
            )
        )
        assert [c.misconception_id for c in candidates] == ["power-rule-step-omitted"]
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
        _isolated_call.reset_pool_for_tests()
