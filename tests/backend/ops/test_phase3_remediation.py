"""P3-06 오답 → 교정 전략 커버리지 CLI(`ops/phase3_remediation.py`) — 변별력·오탐 주입 스위트.

이 파일이 지키는 것
-------------------
정상 입력에서 초록인 것은 증거가 아니다. 이 CLI 가 "핵심 오개념에 교정 전략이 나온다"고 말하려면, 그것이
**깨졌을 때 실제로 RED 가 된다**는 것이 보여야 한다. 그래서

  1. 대조군 — 실 코퍼스에서 좌석 있는 오개념은 served/shadowed 이고 failed 가 0 이다(하한만 건다 —
     진척으로 오르는 수치를 고정하면 정당한 진척이 실패가 된다).
  2. 주입 — 막으려는 상태를 하나씩 **실제로 넣고**, 그 행만 RED 가 되는지 본다. 모든 주입은
     `_changed` 로 "변경 전후가 다르다"를 먼저 단언한다(주입이 조용히 안 들어갔다면 정상 세계에서 검사가
     돈 것이고 'RED 아님'이 '검출 실패'가 아니라 '당연한 초록'이 된다).
  3. 오탐 — 정답 보기를 오개념으로 잡는 상태와, 다른 오개념의 오답이 엉뚱한 후보로 나오는 상태를 넣는다.
  4. 성공 방향 대조군 — 주입 없는 짝은 충족이어야 한다("전부 실패로 계상"이라는 과잉 수정 차단).

주입 표는 모듈이 아니라 이 파일이 **독립적으로** 정의한다.
"""

from __future__ import annotations

import ast
import copy
import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.l1.misconception.crosslink_resolve import ResolvedLink
from whymath_backend.l2.remediation_policy import (
    EscalationRung,
    RemediationPolicyTable,
    select_rung,
)
from whymath_backend.l4.misconception import distractor_link, intervene
from whymath_backend.ops import phase3_remediation as pr

_REPO = Path(__file__).resolve().parents[3]

#: 실 코퍼스에서 서명 픽스처가 있는 대표 오개념 하나(자기 개념 안에서 독립 검산 가능).
_SERVED = "M0671"
_KEBAB = "power-rule-step-omitted"


@pytest.fixture(scope="module")
def base() -> pr.Inputs:
    return pr.load_inputs()


@pytest.fixture(scope="module")
def base_report(base: pr.Inputs) -> pr.RemediationReport:
    return pr.evaluate(base)


def _row(report: pr.RemediationReport, mis_id: str) -> pr.MisconceptionRow:
    return next(r for r in report.rows if r.mis_id == mis_id)


def _changed(before: object, after: object) -> None:
    """주입이 실제로 적용됐다 — 같으면 정상 세계로 검사가 돈 것이다."""
    assert before != after, "주입이 적용되지 않았다 — 이 테스트의 RED 는 신뢰할 수 없다"


# ──────────────────────────────────────────────────────────────────────────
# 1. 대조군 — 실 코퍼스
# ──────────────────────────────────────────────────────────────────────────
class TestControl:
    def test_denominator_is_the_frozen_scope_spec(
        self, base: pr.Inputs, base_report: pr.RemediationReport
    ) -> None:
        """분모는 복제본이 아니라 P3-01 명세의 핵심 오개념이다."""
        assert [r.mis_id for r in base_report.rows] == [
            m.mis_id for m in base.scope.core_misconceptions
        ]
        assert len(base_report.rows) == 12

    def test_no_seated_misconception_fails(self, base_report: pr.RemediationReport) -> None:
        """좌석이 있는데 체인이 깨진 오개념은 0 이다(failed 는 어떤 진척으로도 정당화되지 않는다)."""
        failed = [
            (r.mis_id, r.failures) for r in base_report.rows if r.status is pr.RowStatus.FAILED
        ]
        assert failed == []

    def test_produced_floor(self, base_report: pr.RemediationReport) -> None:
        """하한 7 — 좌석 있는 오개념 전부. 좌석이 늘면 오르고, 줄면 이 테스트가 RED 다."""
        assert base_report.produced >= 7

    def test_blocked_rows_carry_the_gate_not_a_fabricated_signature(
        self, base_report: pr.RemediationReport
    ) -> None:
        for r in base_report.rows:
            if r.status is pr.RowStatus.BLOCKED:
                assert r.kebab_id is None and r.evidence is None
                assert "G-misc40-unseated-concepts-disposition" in r.note

    def test_exit_code_is_nonzero_while_any_core_misconception_is_unserved(
        self, base_report: pr.RemediationReport
    ) -> None:
        unserved = [
            r for r in base_report.rows if r.status in (pr.RowStatus.BLOCKED, pr.RowStatus.FAILED)
        ]
        assert (base_report.exit_code == 0) == (not unserved)

    def test_served_row_has_full_evidence(self, base_report: pr.RemediationReport) -> None:
        row = _row(base_report, _SERVED)
        assert row.status is pr.RowStatus.SERVED and row.kebab_id == _KEBAB
        e = row.evidence
        assert e is not None
        assert e.wrong_checked >= 2 and e.correct_checked >= 1
        assert e.ladder == tuple(r.value for r in pr.EXPECTED_LADDER)
        assert all(e.ladder_resolved)
        assert e.pedagogy is not None and e.action == "practice_current"

    def test_working_ratio_exposes_silently_dropped_ids(
        self, base_report: pr.RemediationReport
    ) -> None:
        """측정은 'M-id 를 그대로 단 보기'를 닿았다고 세지만 서빙은 조용히 버린다 — 숫자로 드러난다."""
        w = base_report.working
        assert w.wrong_picks >= w.with_candidate > 0
        assert (
            w.wrong_picks
            == w.with_candidate + sum(w.dropped_unknown.values()) + w.dropped_below_floor
        )
        assert w.short_answer_problems > 0  # 단답형은 범위 밖이지만 크기를 숨기지 않는다


# ──────────────────────────────────────────────────────────────────────────
# 2. 주입 — 서명·링크·정책을 하나씩 깨뜨린다
# ──────────────────────────────────────────────────────────────────────────
def _wrong_fixture(base: pr.Inputs) -> tuple[str, int]:
    sig = base.remediation.by_kebab()[_KEBAB]
    return sig.wrong[0].problem_id, sig.wrong[0].choice_index


def _with_rows(base: pr.Inputs, mutate: Callable[[dict[str, Any]], None]) -> pr.Inputs:
    rows = copy.deepcopy(dict(base.rows))
    mutate(rows)
    _changed(json.dumps(dict(base.rows), sort_keys=True), json.dumps(rows, sort_keys=True))
    return replace(base, rows=rows)


class TestSignatureInjection:
    def test_removing_the_signature_makes_the_misconception_unserved(self, base: pr.Inputs) -> None:
        """서명(픽스처)이 없으면 그 오개념은 산출 목록에서 빠진다 — 변별력의 핵심."""
        kept = tuple(s for s in base.remediation.signatures if s.kebab_id != _KEBAB)
        mutated = replace(base, remediation=replace(base.remediation, signatures=kept))
        _changed(len(base.remediation.signatures), len(kept))
        report = pr.evaluate(mutated)
        assert _row(report, _SERVED).status is pr.RowStatus.BLOCKED
        # 대조군: 다른 오개념은 영향이 없다 — "전부 실패로 계상"하는 과잉 수정이 통과하지 못한다.
        assert _row(report, "M0864").status is pr.RowStatus.SERVED

    def test_removing_the_distractor_entry_breaks_that_row_only(self, base: pr.Inputs) -> None:
        pid, idx = _wrong_fixture(base)

        def drop(rows: dict[str, Any]) -> None:
            rows[pid]["distractor_map"] = [
                e for e in rows[pid]["distractor_map"] if e["choice_index"] != idx
            ]

        report = pr.evaluate(_with_rows(base, drop))
        row = _row(report, _SERVED)
        assert row.status is pr.RowStatus.FAILED
        assert any("distractor_map" in f for f in row.failures)
        assert _row(report, "M0864").status is pr.RowStatus.SERVED

    def test_mislabeling_to_another_misconception_is_caught_as_wrong_candidate(
        self, base: pr.Inputs
    ) -> None:
        """엉뚱한 오개념으로 라벨이 바뀌면 — 다른 좌석 kebab 이 높은 신뢰로 나오는 상태 — RED 다."""
        pid, idx = _wrong_fixture(base)

        def relabel(rows: dict[str, Any]) -> None:
            for e in rows[pid]["distractor_map"]:
                if e["choice_index"] == idx:
                    e["misconception_id"] = "extremum-max-min-confused"

        report = pr.evaluate(_with_rows(base, relabel))
        row = _row(report, _SERVED)
        assert row.status is pr.RowStatus.FAILED
        assert any("distractor_map 이 이 보기를" in f for f in row.failures)

    def test_unknown_misconception_id_is_not_silently_green(self, base: pr.Inputs) -> None:
        """카탈로그에 없는 raw id(M0674 사례)는 후보를 못 내고, 그 사유가 값으로 남는다."""
        pid, idx = _wrong_fixture(base)

        def raw_id(rows: dict[str, Any]) -> None:
            for e in rows[pid]["distractor_map"]:
                if e["choice_index"] == idx:
                    e["misconception_id"] = "M0674"

        mutated = _with_rows(base, raw_id)
        result = pr.run_choice_chain(
            problem_id=pid,
            distractor_map=mutated.rows[pid]["distractor_map"],
            selected_choice_index=idx,
            is_correct=False,
        )
        assert result.candidate_ids == () and result.strategy is None
        assert result.dropped_reason == "unknown_misconception"
        assert _row(pr.evaluate(mutated), _SERVED).status is pr.RowStatus.FAILED
        assert pr.evaluate(mutated).working.dropped_unknown.get("M0674", 0) > 0


class TestFalsePositiveInjection:
    def test_labeling_the_correct_choice_as_a_misconception_is_caught(
        self, base: pr.Inputs
    ) -> None:
        """정답 보기를 오개념으로 잡는 오탐 — 정답 픽스처가 RED 가 되어야 한다."""
        sig = base.remediation.by_kebab()[_KEBAB]
        pid, correct = sig.correct[0].problem_id, sig.correct[0].choice_index

        def poison(rows: dict[str, Any]) -> None:
            rows[pid]["distractor_map"] = [
                *rows[pid]["distractor_map"],
                {"choice_index": correct, "misconception_id": _KEBAB},
            ]

        row = _row(pr.evaluate(_with_rows(base, poison)), _SERVED)
        assert row.status is pr.RowStatus.FAILED
        assert any("오탐" in f for f in row.failures)

    def test_declaring_a_correct_choice_as_wrong_fixture_is_rejected(self, base: pr.Inputs) -> None:
        sig = base.remediation.by_kebab()[_KEBAB]
        # 로더가 아니라 값 객체를 직접 바꿔 CLI 쪽 방어(정답 보기를 오답이라 선언)를 시험한다.
        # 같은 문항일 때만 정답 보기와 겹치므로 정답 픽스처의 문항에 맞춘다.
        bad = replace(
            sig,
            wrong=(
                replace(
                    sig.wrong[0],
                    problem_id=sig.correct[0].problem_id,
                    choice_index=sig.correct[0].choice_index,
                ),
            ),
        )
        sigs = tuple(bad if s.kebab_id == _KEBAB else s for s in base.remediation.signatures)
        mutated = replace(base, remediation=replace(base.remediation, signatures=sigs))
        _changed(base.remediation.signatures, sigs)
        row = _row(pr.evaluate(mutated), _SERVED)
        assert row.status is pr.RowStatus.FAILED
        assert any("정답 보기를 오답이라 선언" in f for f in row.failures)


class TestDetectorLevelInjection:
    def test_a_correct_fixture_that_is_really_wrong_is_named_as_such(self, base: pr.Inputs) -> None:
        """정답 픽스처가 사실은 오답 보기를 가리키는 데이터 오류 — 그 사실 자체를 메시지로 지목한다."""
        sig = base.remediation.by_kebab()[_KEBAB]
        wrong = sig.wrong[0]
        bad = replace(
            sig,
            correct=(
                replace(
                    sig.correct[0], problem_id=wrong.problem_id, choice_index=wrong.choice_index
                ),
            ),
        )
        sigs = tuple(bad if s.kebab_id == _KEBAB else s for s in base.remediation.signatures)
        _changed(base.remediation.signatures, sigs)
        row = _row(
            pr.evaluate(replace(base, remediation=replace(base.remediation, signatures=sigs))),
            _SERVED,
        )
        assert row.status is pr.RowStatus.FAILED
        assert any("이 보기가 정답이 아니다" in f for f in row.failures)

    def test_a_detector_that_also_emits_an_unrelated_misconception_is_caught(
        self, base: pr.Inputs, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """탐지기가 엉뚱한 오개념을 높은 신뢰로 **같이** 내는 상태 — 단일 후보 검사가 도달 가능해야 한다."""
        from whymath_backend.l4.misconception import remediation_strategy as rs
        from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
        from whymath_backend.l4.misconception.models import MisconceptionMatch

        original = rs.distractor_link_matches

        def noisy(dmap: Any, idx: Any) -> list[MisconceptionMatch]:
            found = original(dmap, idx)
            if found:
                found = [
                    *found,
                    MisconceptionMatch(
                        misconception=CATALOG_BY_ID["extremum-max-min-confused"], confidence=0.79
                    ),
                ]
            return found

        monkeypatch.setattr(rs, "distractor_link_matches", noisy)
        row = _row(pr.evaluate(base), _SERVED)
        assert row.status is pr.RowStatus.FAILED
        assert any("단 하나가 아니다" in f for f in row.failures)


class TestCrosswalkInjection:
    def test_removing_the_crosslink_unseats_the_misconception(self, base: pr.Inputs) -> None:
        links = {k: v for k, v in base.crosslinks.items() if k != _KEBAB}
        _changed(len(base.crosslinks), len(links))
        report = pr.evaluate(replace(base, crosslinks=links))
        assert _row(report, _SERVED).status is pr.RowStatus.BLOCKED

    def test_canonical_flip_moves_the_shadow(self, base: pr.Inputs) -> None:
        """product-rule-naive 의 canonical 이 바뀌면 SERVED/SHADOWED 가 뒤집힌다(M-id 경유 증명)."""
        original = base.crosslinks["product-rule-naive"]
        flipped = tuple(
            ResolvedLink(
                mis_id=link.mis_id,
                link_type=link.link_type,
                confidence=0.99 if link.mis_id == "M0672" else 0.5,
            )
            for link in original
        )
        _changed(original, flipped)
        report = pr.evaluate(
            replace(base, crosslinks={**base.crosslinks, "product-rule-naive": flipped})
        )
        assert _row(report, "M0672").status is pr.RowStatus.SERVED
        assert _row(report, "M0075").status is pr.RowStatus.SHADOWED

    def test_canonical_tie_is_never_resolved_by_guessing(self, base: pr.Inputs) -> None:
        tied = tuple(
            ResolvedLink(mis_id=link.mis_id, link_type=link.link_type, confidence=0.9)
            for link in base.crosslinks["product-rule-naive"]
        )
        report = pr.evaluate(
            replace(base, crosslinks={**base.crosslinks, "product-rule-naive": tied})
        )
        for mid in ("M0075", "M0672"):
            row = _row(report, mid)
            assert row.status is pr.RowStatus.SHADOWED and row.reports_as is None
            assert "동률" in row.note


class TestPolicyInjection:
    def test_shifting_the_ladder_boundary_breaks_every_served_row(
        self, base: pr.Inputs, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """P-09 사다리 경계를 한 칸 밀면(2회→3회) 기대 사다리와 어긋나 RED — 기대가 표 밖에 있기 때문이다."""
        shifted = RemediationPolicyTable(
            escalation_ladder=(
                (5, EscalationRung.PREREQUISITE_CONCEPT),
                (4, EscalationRung.EASIER_PROBLEM),
                (3, EscalationRung.CORRECTIVE_EXPLANATION),
            )
        )
        monkeypatch.setattr(intervene, "select_rung", lambda n: select_rung(n, shifted))
        report = pr.evaluate(base)
        row = _row(report, _SERVED)
        assert row.status is pr.RowStatus.FAILED
        assert any("사다리" in f for f in row.failures)

    def test_confidence_below_the_gate_floor_yields_no_candidate_not_a_confident_guess(
        self, base: pr.Inputs, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """신호가 약하면(게이트 floor 0.65 미만) 후보 자체가 비고 단정하지 않는다(no_confident_match)."""
        before = distractor_link.DISTRACTOR_LINK_CONFIDENCE
        monkeypatch.setattr(distractor_link, "DISTRACTOR_LINK_CONFIDENCE", 0.6)
        _changed(before, distractor_link.DISTRACTOR_LINK_CONFIDENCE)
        pid, idx = _wrong_fixture(base)
        result = pr.run_choice_chain(
            problem_id=pid,
            distractor_map=base.rows[pid]["distractor_map"],
            selected_choice_index=idx,
            is_correct=False,
        )
        assert result.candidate_ids == () and result.strategy is None
        assert result.dropped_reason == "below_floor"
        assert _row(pr.evaluate(base), _SERVED).status is pr.RowStatus.FAILED

    @pytest.mark.parametrize(
        ("confidence", "expect_served"),
        [(0.70, False), (0.71, True)],
        ids=["at-floor-not-eligible", "just-above-floor-eligible"],
    )
    def test_remediation_floor_is_exceeded_not_met(
        self,
        base: pr.Inputs,
        monkeypatch: pytest.MonkeyPatch,
        confidence: float,
        expect_served: bool,
    ) -> None:
        """P-09: 신뢰도가 0.7 을 **초과**해야 교정으로 간다 — 경계 양쪽(0.70 / 0.71)을 밟는다.

        두 값 모두 품질 게이트 floor(0.65)는 넘으므로 후보는 나온다. 갈리는 것은 교정 하한뿐이다.
        """
        monkeypatch.setattr(distractor_link, "DISTRACTOR_LINK_CONFIDENCE", confidence)
        row = _row(pr.evaluate(base), _SERVED)
        if expect_served:
            assert row.status is pr.RowStatus.SERVED
        else:
            assert row.status is pr.RowStatus.FAILED
            assert any("교정 하한" in f for f in row.failures)

    def test_no_easier_problem_leaves_the_rung_unresolved(self, base: pr.Inputs) -> None:
        """쉬운 문항이 코퍼스에 없으면 '쉬운 문항' 등급은 해소 실패다 — 있는 척 채우지 않는다."""
        # 픽스처 난이도(3.0) 미만 문항만 지운다 — 픽스처 문항과 선수 간선은 그대로라 이 등급만 깨진다.
        floor = 3.0
        harder = tuple(p for p in base.corpus.problems if (p.difficulty or 0) >= floor)
        corpus = replace(base.corpus, problems=harder)
        _changed(len(base.corpus.problems), len(harder))
        row = _row(pr.evaluate(replace(base, corpus=corpus)), _SERVED)
        assert row.status is pr.RowStatus.FAILED
        assert any("easier_problem" in f and "해소되지 않는다" in f for f in row.failures)
        assert not any("prerequisite_concept" in f for f in row.failures)

    def test_no_prerequisite_edges_leaves_the_last_rung_unresolved(self, base: pr.Inputs) -> None:
        corpus = replace(base.corpus, prerequisite_edges=())
        _changed(len(base.corpus.prerequisite_edges), 0)
        row = _row(pr.evaluate(replace(base, corpus=corpus)), _SERVED)
        assert row.status is pr.RowStatus.FAILED
        assert any("prerequisite_concept" in f for f in row.failures)


class TestFixtureReference:
    def test_fixture_pointing_at_a_missing_problem_is_a_failure_not_a_skip(
        self, base: pr.Inputs
    ) -> None:
        rows = {k: v for k, v in base.rows.items() if k != _wrong_fixture(base)[0]}
        _changed(len(base.rows), len(rows))
        row = _row(pr.evaluate(replace(base, rows=rows)), _SERVED)
        assert row.status is pr.RowStatus.FAILED
        assert any("없다" in f for f in row.failures)


# ──────────────────────────────────────────────────────────────────────────
# 3. 규율 — LLM 미경유 · reactive retrieval
# ──────────────────────────────────────────────────────────────────────────
class TestFixtureSoundness:
    """픽스처가 수학적으로 옳은지 — `distractor_map` 라벨과 독립인 SymPy 계산으로 검산한다.

    오답 보기 라벨은 문항 저작 시점의 주장이다(가설의 근거이지 판정이 아니다). 픽스처가 그 라벨만 믿으면
    라벨이 틀렸을 때 체인이 틀린 것을 맞게 재현한다. 그래서 문면을 파싱해 **정답 보기 = 실제 계산값**,
    **오답 보기 = 그 오개념이 만드는 값**임을 여기서 따로 확인한다.
    """

    @staticmethod
    def _value(row: Mapping[str, Any], index: int) -> Any:
        import sympy

        return sympy.Rational(str(row["choices"][index]).replace("−", "-"))

    @staticmethod
    def _fixtures(base: pr.Inputs, kebab: str, kind: str) -> list[tuple[Mapping[str, Any], int]]:
        sig = base.remediation.by_kebab()[kebab]
        return [(base.rows[f.problem_id], f.choice_index) for f in getattr(sig, kind)]

    def test_power_rule(self, base: pr.Inputs) -> None:
        import re

        import sympy

        x = sympy.Symbol("x")
        for row, idx in self._fixtures(base, "power-rule-step-omitted", "wrong"):
            text = row["question_text"]
            n = int(re.search(r"x\^(\d+)", text).group(1))  # type: ignore[union-attr]
            a = int(re.search(r"(?:f'\(|x = )(\d+)", text).group(1))  # type: ignore[union-attr]
            true = sympy.diff(x**n, x).subs(x, a)
            coefficient_dropped = sympy.Integer(a) ** (n - 1)
            exponent_kept = n * sympy.Integer(a) ** n
            assert self._value(row, idx) in {coefficient_dropped, exponent_kept}, text
            assert self._value(row, idx) != true
        for row, idx in self._fixtures(base, "power-rule-step-omitted", "correct"):
            text = row["question_text"]
            n = int(re.search(r"x\^(\d+)", text).group(1))  # type: ignore[union-attr]
            a = int(re.search(r"(?:f'\(|x = )(\d+)", text).group(1))  # type: ignore[union-attr]
            assert self._value(row, idx) == sympy.diff(x**n, x).subs(x, a)

    def test_product_rule(self, base: pr.Inputs) -> None:
        import re

        import sympy

        x = sympy.Symbol("x")
        for kind in ("wrong", "correct"):
            for row, idx in self._fixtures(base, "product-rule-naive", kind):
                text = row["question_text"]
                p, q, a = map(int, re.search(r"x\^(\d), g\(x\) = x\^(\d).*x = (\d+)", text).groups())  # type: ignore[union-attr]
                f, g = x**p, x**q
                true = sympy.diff(f * g, x).subs(x, a)
                naive = (sympy.diff(f, x) * sympy.diff(g, x)).subs(x, a)
                assert true != naive, "이 문항은 두 값이 같아 오개념을 변별하지 못한다"
                assert self._value(row, idx) == (naive if kind == "wrong" else true), text

    def test_critical_point_without_sign_change(self, base: pr.Inputs) -> None:
        import re

        import sympy

        x = sympy.Symbol("x", real=True)
        for kind in ("wrong", "correct"):
            for row, idx in self._fixtures(base, "critical-point-implies-extremum", kind):
                c = int(re.search(r"\(x - (\d+)\)\^3", row["question_text"]).group(1))  # type: ignore[union-attr]
                f = (x - c) ** 3
                crit = sympy.solve(sympy.diff(f, x), x)
                # 극값은 도함수의 부호가 바뀌는 점이다 — 좌우 한 점씩 잡아 부호 변화를 확인한다.
                extrema = [
                    r
                    for r in crit
                    if sympy.sign(sympy.diff(f, x).subs(x, r - 1))
                    != sympy.sign(sympy.diff(f, x).subs(x, r + 1))
                ]
                expected = len(crit) if kind == "wrong" else len(extrema)
                assert len(crit) == 1 and len(extrema) == 0
                assert self._value(row, idx) == expected

    def test_continuity_vs_differentiability(self, base: pr.Inputs) -> None:
        for kind in ("wrong", "correct"):
            for row, idx in self._fixtures(base, "continuity-implies-differentiability", kind):
                assert (
                    "|x -" in row["question_text"]
                )  # |x-c| 는 x=c 에서 연속이나 미분 불가(좌우 기울기 -1 ≠ +1)
                # 연속이므로 '미분가능'(=1)으로 단정하면 오개념, 실제 답은 0.
                assert self._value(row, idx) == (1 if kind == "wrong" else 0)

    def test_extremum_value_and_point(self, base: pr.Inputs) -> None:
        import re

        import sympy

        x = sympy.Symbol("x", real=True)
        for kebab in ("extremum-max-min-confused", "extremum-value-vs-point-confused"):
            for kind in ("wrong", "correct"):
                for row, idx in self._fixtures(base, kebab, kind):
                    text = row["question_text"]
                    body = re.search(r"f\(x\) = ([^ ]+(?: [+-] [^ ]+)*) (?:의|가)", text).group(1)  # type: ignore[union-attr]
                    f = sympy.sympify(
                        re.sub(r"(\d)x", r"\1*x", body.replace("^", "**")), locals={"x": x}
                    )
                    crit = sorted(sympy.solve(sympy.diff(f, x), x))
                    values = [f.subs(x, c) for c in crit]
                    maximum, minimum = max(values), min(values)
                    asked_max = "극댓값" in text
                    true, opposite = (maximum, minimum) if asked_max else (minimum, maximum)
                    chosen = self._value(row, idx)
                    if kind == "correct":
                        assert chosen == true
                    elif kebab == "extremum-max-min-confused":
                        assert chosen == opposite
                    else:
                        assert chosen in set(crit) and chosen != true


class TestDiscipline:
    _FORBIDDEN = ("anthropic", "openai", "ollama", "providers", "router", "langfuse")

    @pytest.mark.parametrize(
        "relative",
        [
            "src/backend/whymath_backend/l4/misconception/remediation_strategy.py",
            "src/backend/whymath_backend/ops/phase3_remediation.py",
            "src/backend/whymath_backend/l1/standards/phase3_remediation_spec.py",
        ],
    )
    def test_chain_modules_never_import_an_llm_path(self, relative: str) -> None:
        """학습 상태를 LLM 이 결정하지 않는다 — 이 슬라이스의 모듈은 LLM 경로를 임포트조차 하지 않는다."""
        tree = ast.parse((_REPO / relative).read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
            elif isinstance(node, ast.Import):
                imported.extend(a.name for a in node.names)
        bad = [m for m in imported if any(f in m.split(".") for f in self._FORBIDDEN)]
        assert bad == []

    def test_correct_pick_and_missing_inputs_never_touch_the_catalog(
        self, base: pr.Inputs, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """reactive retrieval — 오개념 카탈로그는 역추적된 id 하나를 확인할 때만 건드린다."""
        from whymath_backend.l4.misconception import remediation_strategy as rs

        class Bomb(dict[str, Any]):
            def get(self, *a: Any, **k: Any) -> Any:  # type: ignore[override]
                raise AssertionError("카탈로그를 미리 조회했다")

            def __getitem__(self, key: str) -> Any:
                raise AssertionError("카탈로그를 미리 조회했다")

            def __contains__(self, key: object) -> bool:
                raise AssertionError("카탈로그를 미리 조회했다")

        monkeypatch.setattr(rs, "CATALOG_BY_ID", Bomb())
        sig = base.remediation.by_kebab()[_KEBAB]
        pid, correct = sig.correct[0].problem_id, sig.correct[0].choice_index
        row = base.rows[pid]
        # 인덱스 미보고 · 매핑 없음 · 정답 보기 — 셋 다 카탈로그를 건드리면 안 된다.
        none_idx = rs.run_choice_chain(
            problem_id=pid,
            distractor_map=row["distractor_map"],
            selected_choice_index=None,
            is_correct=False,
        )
        no_map = rs.run_choice_chain(
            problem_id=pid, distractor_map=None, selected_choice_index=0, is_correct=False
        )
        right = rs.run_choice_chain(
            problem_id=pid,
            distractor_map=row["distractor_map"],
            selected_choice_index=correct,
            is_correct=True,
        )
        assert none_idx.scan.value == "not_run" and no_map.scan.value == "not_run"
        assert right.candidate_ids == () and right.signature is None


class TestCli:
    """`main()` 의 종료 코드 계약 — 막힘이 있으면 1, 입력을 못 읽으면 2(통과로 위장하지 않는다)."""

    def test_exit_code_is_one_while_any_core_misconception_is_unserved(
        self, capsys: pytest.CaptureFixture[str], base_report: pr.RemediationReport
    ) -> None:
        unserved = [
            r for r in base_report.rows if r.status in (pr.RowStatus.BLOCKED, pr.RowStatus.FAILED)
        ]
        rc = pr.main([])
        out = capsys.readouterr().out
        assert rc == (1 if unserved else 0)
        assert "핵심 오개념" in out and "작동한 비율" in out

    def test_json_output_is_machine_readable_and_matches_the_report(
        self, capsys: pytest.CaptureFixture[str], base_report: pr.RemediationReport
    ) -> None:
        rc = pr.main(["--json"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["exit_code"] == rc == base_report.exit_code
        assert payload["total"] == 12 and payload["produced"] == base_report.produced
        assert [r["mis_id"] for r in payload["rows"]] == [r.mis_id for r in base_report.rows]

    def test_unreadable_data_is_a_measurement_failure_not_a_pass(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        rc = pr.main(["--data", str(tmp_path / "없는파일.yaml")])
        assert rc == 2
        assert "[적재 실패]" in capsys.readouterr().err
