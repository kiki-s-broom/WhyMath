"""P3-20 — [12미적Ⅰ-02-09] 매개변수 범위형 검증기의 필요성 판정: 수치형만으로 6슬롯이 채워지는가.

배경: 02-09 의 매개변수(k) 범위형은 검증기가 없다(P3-18 보강 ④ — skip). 그런데 이 태스크의 ②는
"그 형태가 *실제로 필요한가*"를 먼저 센다. P3-03 은 핵심 개념마다 문항 1건 이상(Content Coverage),
P3-05 는 6슬롯(대표·기본·응용·오개념 유발·진단·숙련도 확인) 충족을 요구한다. 그래서 수치형 문항
6개를 슬롯마다 한 형태씩 만들어 **기존 corpus_reverify CLI** 에 태워 가능 여부를 잰다.

판정 규칙은 P3-18 의 `judge_concept` 를 그대로 재사용한다(재구현 금지). 가능 판정이 6슬롯에서
나오면 매개변수 범위형 검증기는 구현하지 않는다(불요 — 과공학 방지). 진단 형태 X1 은 슬롯이 아니라
검증기 의미(근의 합은 중근을 중복 계산) 때문에 정답이 거부되고 오답이 통과하는 형태(위장)를
동결한 보강 행이다.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

_HERE = Path(__file__).parent
_FIXTURES = _HERE / "fixtures"
_CORRECT = _FIXTURES / "p3_20_correct.jsonl"
_WRONG = _FIXTURES / "p3_20_wrong.jsonl"


def _load_p3_18() -> object:
    """P3-18 테스트 모듈을 경로로 적재한다 — importlib 임포트 모드라 형제 모듈 import가 안 된다."""
    name = "_p3_18_probe_for_p3_20"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, _HERE / "test_p3_18_calculus_verifiability_probe.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclass(slots)·Enum 이 모듈 이름을 역참조한다
    spec.loader.exec_module(module)
    return module


_P18 = _load_p3_18()
Verdict = _P18.Verdict  # type: ignore[attr-defined]
judge_concept = _P18.judge_concept  # type: ignore[attr-defined]
run_cli = _P18.run_cli  # type: ignore[attr-defined]
_read_rows = _P18._read_rows  # type: ignore[attr-defined]  # noqa: SLF001
_outcome_of_row = _P18._outcome_of_row  # type: ignore[attr-defined]  # noqa: SLF001

# 슬롯 6개 + 진단 보강 1개. 2026-10-03 실측 — 실측이 가설과 달라도 실측을 동결한다.
_SLOT_FORMS = ("S1", "S2", "S3", "S4", "S5", "S6")
_EXPECTED: dict[str, Verdict] = {  # type: ignore[valid-type]
    "S1": Verdict.POSSIBLE,  # 대표 — 삼차 서로 다른 실근 개수(real_root_count)
    "S2": Verdict.POSSIBLE,  # 기본 — 삼차 실근 개수
    "S3": Verdict.POSSIBLE,  # 응용 — 곡선·직선 교점 개수(실근 개수로 환원)
    "S4": Verdict.POSSIBLE,  # 오개념 유발 — 중근을 두 번 세면 3(오답이 fail)
    "S5": Verdict.POSSIBLE,  # 진단 — 근과 계수의 관계(중근 중복) 합, 서로 다른 근의 합 오답이 fail
    "S6": Verdict.POSSIBLE,  # 숙련도 확인 — 부등식 해 소속 점(점 하나만 본다)
    "X1": Verdict.SHAM,  # 서로 다른 근의 합 — 중근을 중복 계산해 정답 1 거부·오답 0 통과(위장 우선)
}


def _by_form(rows: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {str(r["probe_form"]): r for r in rows}


def _skeleton(text: str) -> str:
    """문면 골격 — 숫자를 #로 접는다(scope_spec 항 8 의 distinct 기준 근사)."""
    return re.sub(r"\d+", "#", text)


class TestProbeFixtureShape:
    def test_seven_forms_each_have_a_pair(self) -> None:
        correct, wrong = _read_rows(_CORRECT), _read_rows(_WRONG)
        assert [r["probe_form"] for r in correct] == list(_EXPECTED)
        assert [r["probe_form"] for r in wrong] == list(_EXPECTED)
        assert {r["probe_role"] for r in correct} == {"correct"}
        assert {r["probe_role"] for r in wrong} == {"wrong"}
        for row in correct + wrong:
            assert row["achievement_standard_codes"] == ["[12미적Ⅰ-02-09]"]
            assert row["license"] == "WHYMATH_GENERATED"

    def test_six_slots_cover_all_required_slots_exactly_once(self) -> None:
        slots = [r["probe_slot"] for r in _read_rows(_CORRECT) if r["probe_form"] in _SLOT_FORMS]
        assert slots == ["대표", "기본", "응용", "오개념 유발", "진단", "숙련도 확인"]

    def test_wrong_row_differs_and_questions_match(self) -> None:
        correct, wrong = _by_form(_read_rows(_CORRECT)), _by_form(_read_rows(_WRONG))
        for form in _EXPECTED:
            assert correct[form]["question_text"] == wrong[form]["question_text"], form
            assert correct[form]["answer"] != wrong[form]["answer"], form
            assert correct[form]["verify"] != wrong[form]["verify"] or (
                # 같은 검산 재료여도 답(answer)이 다르면 검증기가 answer 로 가른다.
                correct[form]["answer"]
                != wrong[form]["answer"]
            ), form

    def test_six_slot_question_skeletons_are_distinct(self) -> None:
        # 숫자를 접은 문면이 6개 모두 다르다 — scope_spec 항 8 의 '고유 문면 골격' 근사 기준.
        # P3-05 가 근사 중복 기준을 정하면 그 정의로 다시 잰다(재개 조건).
        correct = _by_form(_read_rows(_CORRECT))
        skeletons = {_skeleton(str(correct[f]["question_text"])) for f in _SLOT_FORMS}
        assert len(skeletons) == 6


class TestRealProbeThroughCorpusReverify:
    def test_per_form_verdicts_match_measurement(self, tmp_path: Path) -> None:
        correct, wrong = _by_form(_read_rows(_CORRECT)), _by_form(_read_rows(_WRONG))
        verdicts = {
            f: judge_concept(
                _outcome_of_row(correct[f], tmp_path, f"c_{f}"),
                _outcome_of_row(wrong[f], tmp_path, f"w_{f}"),
            )
            for f in _EXPECTED
        }
        assert verdicts == _EXPECTED

    def test_all_six_slots_are_possible(self, tmp_path: Path) -> None:
        # 판정의 핵심 — 6슬롯 모두 가능이므로 수치형만으로 슬롯을 채울 검증 경로가 있다.
        correct, wrong = _by_form(_read_rows(_CORRECT)), _by_form(_read_rows(_WRONG))
        for f in _SLOT_FORMS:
            verdict = judge_concept(
                _outcome_of_row(correct[f], tmp_path, f"c_{f}"),
                _outcome_of_row(wrong[f], tmp_path, f"w_{f}"),
            )
            assert verdict is Verdict.POSSIBLE, f

    def test_whole_file_exit_codes_and_counts(self) -> None:
        # 정답 파일: 통과 6·실패 1(X1 정답이 거부)·exit 1. 오답 파일: 통과 1(X1 오답 통과)·실패 6·exit 1.
        correct = run_cli(_CORRECT)
        assert (correct.exit_code, correct.passed, correct.failed, correct.skipped) == (1, 6, 1, 0)
        wrong = run_cli(_WRONG)
        assert (wrong.exit_code, wrong.passed, wrong.failed, wrong.skipped) == (1, 1, 6, 0)

    def test_distinct_roots_sum_form_is_rejected_by_multiplicity_semantics(
        self, tmp_path: Path
    ) -> None:
        # X1: 문면은 '서로 다른 근의 합'(=1)인데 검증기는 중근을 중복 계산(=0)한다 — 정답이 fail,
        # 오답 0 이 pass(판정은 위장). 문면에 '중근은 중복해서'를 명시한 S5 형태만 안전하다.
        correct = _by_form(_read_rows(_CORRECT))["X1"]
        out = _outcome_of_row(correct, tmp_path, "x1c")
        assert (out.exit_code, out.failed) == (1, 1)

    def test_parametric_range_form_remains_unverifiable(self) -> None:
        # 이 태스크는 매개변수 범위형 검증기를 만들지 않는다 — 현재도 skip 임을 P3-18 보강 행이 고정한다.
        # (P3-18 의 `-02-09` 매개변수 보강 행: 상태 skip). 여기서는 그 행이 여전히 skip 인지만 확인한다.
        supplement = _P18._read_rows(_FIXTURES / "p3_18_supplement.jsonl")  # type: ignore[attr-defined]  # noqa: SLF001
        row = next(r for r in supplement if r["probe_concept"] == "[12미적Ⅰ-02-09]")
        assert row["probe_expected_state"] == "skip"
