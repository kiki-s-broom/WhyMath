"""P3-21 — [12미적Ⅰ-02-08] 파생 판정 3종(증감 구간·극값 x좌표·극값의 값)의 SymPy 검증 가능성 프로브.

배경: 처분 (나)(게이트 G-p318-calc-02-08-disposition)는 개형 문항을 '파생 판정 문항'으로 대체했다.
P3-18이 실측한 파생 판정은 극값 *개수* 하나뿐이라 (나)의 나머지 근거가 미측정이었다. 이 파일은
세 종류를 **기존 재검증 경로 `corpus_reverify` CLI**에 태워 가능/불가/위장으로 판정한다.

판정 규칙은 P3-18 테스트의 `judge_concept`·`run_cli`·`FileOutcome`을 **그대로 재사용**한다(재구현
금지 — acceptance ③). 정답/오답 쌍의 최소 단위는 '형태(form)'이며, 종류마다 ①값만 틀린 오답
②부호·경계 포함 여부·극대/극소를 뒤바꾼 오답을 한 형태 이상 둔다. 판정이 불가·위장·일부·정답 오거부로
나온 형태는 02-08 문항화에서 제외할 후보이지만, **세션이 문항 형태나 분모를 바꾸지 않는다** — 결정은
게이트로 올린다(acceptance ④). 검증기 코드는 고치지 않는다(acceptance ⑥).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).parent
_FIXTURES = _HERE / "fixtures"
_CORRECT = _FIXTURES / "p3_21_correct.jsonl"
_WRONG = _FIXTURES / "p3_21_wrong.jsonl"


def _load_p3_18() -> object:
    """P3-18 테스트 모듈을 경로로 적재한다 — importlib 임포트 모드라 형제 모듈 import가 안 된다."""
    name = "_p3_18_probe_for_p3_21"
    if name in sys.modules:
        return sys.modules[name]
    path = _HERE / "test_p3_18_calculus_verifiability_probe.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclass(slots)·Enum이 모듈 이름을 역참조한다
    spec.loader.exec_module(module)
    return module


_P18 = _load_p3_18()
Verdict = _P18.Verdict  # type: ignore[attr-defined]
FileOutcome = _P18.FileOutcome  # type: ignore[attr-defined]
judge_concept = _P18.judge_concept  # type: ignore[attr-defined]
run_cli = _P18.run_cli  # type: ignore[attr-defined]
_read_rows = _P18._read_rows  # type: ignore[attr-defined]  # noqa: SLF001
_outcome_of_row = _P18._outcome_of_row  # type: ignore[attr-defined]  # noqa: SLF001

_KINDS = ("증감 구간", "극값 x좌표", "극값의 값")

# 형태별 판정 — 2026-10-03 실측(corpus_reverify CLI · 정답 1행·오답 1행을 각각 따로 실행).
# 실측이 가설과 달라도 실측을 동결한다. 값이 바뀌면(검증기 개선·퇴행) RED가 되어 프로브를 다시 돌리게 한다.
_EXPECTED: dict[str, Verdict] = {  # type: ignore[valid-type]
    # 증감 구간
    "A1": Verdict.POSSIBLE,  # 경계점 = f'=0의 근 — 값만 틀린 오답이 fail
    "A2": Verdict.POSSIBLE,  # 증가 구간 소속 점 — 감소 구간 점(부호 뒤바꿈)이 fail
    "A2d": Verdict.POSSIBLE,  # 감소 구간 소속 점 — 증가 구간 점이 fail
    "A3": Verdict.PARTIAL,  # 경계 포함 뒤바꿈 — 오답이 fail이 아니라 skip(변별 불가)
    "A4": Verdict.IMPOSSIBLE,  # 구간 표기 답 그대로 — 정답이 skip
    "A5": Verdict.CORRECT_REJECTED,  # 구간 표기를 식 단독 조건으로 — 정답이 fail(오염 위장)
    # 극값 x좌표
    "B1": Verdict.POSSIBLE,  # f'=0의 근 — 값만 틀린 오답이 fail
    "B2": Verdict.POSSIBLE,  # 극대·극소 뒤바꿈 — answer_selection(작성자 사전 계산)으로 fail
    "B3": Verdict.SHAM,  # 극대·극소 뒤바꿈 — selection 없으면 둘 다 f'의 근이라 오답 통과
    # 극값의 값
    "C1": Verdict.POSSIBLE,  # 점 (x, f(x)) 검산 — 값만 틀린 오답이 fail
    "C2": Verdict.POSSIBLE,  # 부호 뒤바꿈 — x가 묶여 있어 fail
    "C3": Verdict.SHAM,  # 극대·극소 점 뒤바꿈 — 곡선 위의 점이라 오답 통과
    "C4": Verdict.CORRECT_REJECTED,  # x 없이 값만 — 자유변수 샘플 위반으로 정답도 fail
}

# 형태가 속한 종류 — 종류마다 위 판정이 아래 요약의 근거다.
_FORM_KIND: dict[str, str] = {
    "A1": "증감 구간",
    "A2": "증감 구간",
    "A2d": "증감 구간",
    "A3": "증감 구간",
    "A4": "증감 구간",
    "A5": "증감 구간",
    "B1": "극값 x좌표",
    "B2": "극값 x좌표",
    "B3": "극값 x좌표",
    "C1": "극값의 값",
    "C2": "극값의 값",
    "C3": "극값의 값",
    "C4": "극값의 값",
}

# 종류마다 기본 형태(값만 틀림)·부호/뒤바꿈 형태 — acceptance ③ '종류마다 하나 이상'.
_MAIN_FORM = {"증감 구간": "A1", "극값 x좌표": "B1", "극값의 값": "C1"}
_SWAP_FORMS = {
    "증감 구간": ("A2", "A2d", "A3"),
    "극값 x좌표": ("B2", "B3"),
    "극값의 값": ("C2", "C3"),
}


def _by_form(rows: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {str(r["probe_form"]): r for r in rows}


def _form_verdicts(tmp_dir: Path) -> dict[str, Verdict]:  # type: ignore[valid-type]
    correct = _by_form(_read_rows(_CORRECT))
    wrong = _by_form(_read_rows(_WRONG))
    verdicts: dict[str, Verdict] = {}  # type: ignore[valid-type]
    for form in _EXPECTED:
        c_out = _outcome_of_row(correct[form], tmp_dir, f"c_{form}")
        w_out = _outcome_of_row(wrong[form], tmp_dir, f"w_{form}")
        verdicts[form] = judge_concept(c_out, w_out)
    return verdicts


# ──────────────────────────────────────────────────────────────────────────
# ① fixture 형태 — 쌍 대응·종류별 구성·오답이 실제로 다른 주장인가
# ──────────────────────────────────────────────────────────────────────────


class TestProbeFixtureShape:
    def test_thirteen_forms_each_have_one_correct_and_one_wrong_row(self) -> None:
        correct = _read_rows(_CORRECT)
        wrong = _read_rows(_WRONG)
        assert len(correct) == 13 and len(wrong) == 13
        assert [r["probe_form"] for r in correct] == list(_EXPECTED)
        assert [r["probe_form"] for r in wrong] == list(_EXPECTED)
        assert {r["probe_role"] for r in correct} == {"correct"}
        assert {r["probe_role"] for r in wrong} == {"wrong"}
        for row in correct + wrong:
            assert row["achievement_standard_codes"] == ["[12미적Ⅰ-02-08]"]
            assert row["license"] == "WHYMATH_GENERATED"  # 교과서·기출 복제 0 — 자체 제작 수치

    def test_form_to_kind_map_matches_fixture(self) -> None:
        for row in _read_rows(_CORRECT) + _read_rows(_WRONG):
            assert row["probe_kind"] == _FORM_KIND[str(row["probe_form"])], row["slug"]
        assert set(_FORM_KIND.values()) == set(_KINDS)

    def test_every_kind_has_a_value_only_pair_and_a_swap_pair(self) -> None:
        # acceptance ③ — 오답은 '값만 틀리게'뿐 아니라 부호·경계 포함 여부를 뒤바꾼 형태를 종류마다 하나 이상.
        wrong = _by_form(_read_rows(_WRONG))
        for kind in _KINDS:
            assert _MAIN_FORM[kind] in wrong
            assert wrong[_MAIN_FORM[kind]]["probe_wrong_kind"] == "값만 틀림"
            swap_kinds = {wrong[f]["probe_wrong_kind"] for f in _SWAP_FORMS[kind]}
            assert swap_kinds - {"값만 틀림"}, (kind, swap_kinds)
            for f in _SWAP_FORMS[kind]:
                assert _FORM_KIND[f] == kind

    def test_wrong_row_claims_something_different_from_correct(self) -> None:
        correct = _by_form(_read_rows(_CORRECT))
        wrong = _by_form(_read_rows(_WRONG))
        for form in _EXPECTED:
            c_row, w_row = correct[form], wrong[form]
            assert c_row["question_text"] == w_row["question_text"], form
            assert c_row["answer"] != w_row["answer"], form  # 오답은 다른 주장이다
            c_verify, w_verify = c_row.get("verify"), w_row.get("verify")
            assert (c_verify is None) == (w_verify is None), form
        # 검산 재료가 정답·오답에서 같으면 그 형태는 답을 검산에 넣을 방법이 없다 — 의도한 형태(A5·
        # 구간 표기를 함수식 단독 조건으로 억지 표현)만 허용하고, 다른 형태가 우연히 같아지면 RED다.
        identical = {
            form
            for form in _EXPECTED
            if correct[form].get("verify") is not None
            and correct[form].get("verify") == wrong[form].get("verify")
        }
        assert identical == {"A5"}

    def test_slugs_are_unique_and_clean(self) -> None:
        slugs = [str(r["slug"]) for r in _read_rows(_CORRECT) + _read_rows(_WRONG)]
        assert len(set(slugs)) == 26
        problem_ids = [str(r["problem_id"]) for r in _read_rows(_CORRECT) + _read_rows(_WRONG)]
        assert len(set(problem_ids)) == 26


# ──────────────────────────────────────────────────────────────────────────
# ② 실측 — 형태별 판정을 실제 corpus_reverify CLI로 단언
# ──────────────────────────────────────────────────────────────────────────


class TestRealProbeThroughCorpusReverify:
    def test_per_form_verdicts_match_measurement(self, tmp_path: Path) -> None:
        assert _form_verdicts(tmp_path) == _EXPECTED

    def test_main_pair_of_each_kind_is_possible(self, tmp_path: Path) -> None:
        # 종류마다 '값만 틀린' 기본 쌍은 가능 — 파생 판정 3종 모두 최소한 이 형태는 기계 검증된다.
        verdicts = _form_verdicts(tmp_path)
        assert {k: verdicts[_MAIN_FORM[k]] for k in _KINDS} == {k: Verdict.POSSIBLE for k in _KINDS}

    def test_whole_file_exit_codes_and_counts(self) -> None:
        # 13행 일괄 실행. 정답 파일은 통과 7·실패 2(A5·C4 정답 오거부)·skip 1(A4)·exit 1 —
        # exit 1이므로 '검증됨'이 아니고, 일괄 판정은 종류·형태를 가리지 못한다.
        correct = run_cli(_CORRECT)
        assert (correct.exit_code, correct.passed, correct.failed, correct.skipped) == (1, 10, 2, 1)
        # 오답 파일: 통과 2(B3·C3 위장) · 실패 9 · skip 2(A3 경계 불포함·A4 표기). 통과 2가 곧 위장 2다.
        wrong = run_cli(_WRONG)
        assert (wrong.exit_code, wrong.passed, wrong.failed, wrong.skipped) == (1, 2, 9, 2)

    def test_wrong_rows_that_pass_are_exactly_the_sham_forms(self, tmp_path: Path) -> None:
        # 변별력 — 오답이 통과한 형태는 위장 판정을 받은 형태와 정확히 같다(그 밖에는 통과가 없다).
        wrong = _by_form(_read_rows(_WRONG))
        passing = {
            form
            for form in _EXPECTED
            if _outcome_of_row(wrong[form], tmp_path, f"wp_{form}").passed > 0
        }
        sham = {form for form, v in _EXPECTED.items() if v is Verdict.SHAM}
        assert passing == sham == {"B3", "C3"}

    def test_boundary_swap_wrong_row_is_skip_not_fail(self, tmp_path: Path) -> None:
        # A3: 경계 불포함 오답은 fail이 아니라 skip — 엄격 부등식의 경계점(잔차 0)은 판정 불가로 넘어간다.
        wrong = _by_form(_read_rows(_WRONG))["A3"]
        out = _outcome_of_row(wrong, tmp_path, "a3w")
        assert (out.exit_code, out.passed, out.failed, out.skipped) == (0, 0, 0, 1)

    def test_interval_notation_answer_cannot_be_verified(self, tmp_path: Path) -> None:
        # A4: 증감 구간을 학생이 쓰는 구간 표기 그대로는 verify 재료가 없다 — 정답이 skip.
        correct = _by_form(_read_rows(_CORRECT))["A4"]
        assert "verify" not in correct
        out = _outcome_of_row(correct, tmp_path, "a4c")
        assert (out.exit_code, out.passed, out.failed, out.skipped) == (0, 0, 0, 1)


# ──────────────────────────────────────────────────────────────────────────
# ③ 판정 입력의 공허함 방지 — P3-18 판정 함수를 재사용하되 이 파일의 쌍에도 반례를 건다
# ──────────────────────────────────────────────────────────────────────────


class TestJudgeReuseGuards:
    def test_judge_function_is_the_p3_18_one(self) -> None:
        # 재구현 금지(acceptance ③) — 같은 객체여야 한다.
        assert judge_concept.__module__ == "_p3_18_probe_for_p3_21"

    def test_sham_is_detected_when_wrong_row_is_replaced_by_correct_row(
        self, tmp_path: Path
    ) -> None:
        # 뮤테이션 — 오답 행을 정답 행으로 바꾸면 모든 형태가 위장이 되어야 한다(판정이 변별한다는 증거).
        correct = _by_form(_read_rows(_CORRECT))
        for form in ("A1", "B1", "C1"):
            c_out = _outcome_of_row(correct[form], tmp_path, f"m_c_{form}")
            same = _outcome_of_row(correct[form], tmp_path, f"m_w_{form}")
            assert judge_concept(c_out, same) is Verdict.SHAM, form

    @pytest.mark.parametrize("form", ["A1", "B1", "C1"])
    def test_value_only_wrong_row_fails_with_a_reason(self, form: str, tmp_path: Path) -> None:
        wrong = _by_form(_read_rows(_WRONG))[form]
        out = _outcome_of_row(wrong, tmp_path, f"v_{form}")
        assert (out.exit_code, out.failed, out.passed, out.skipped) == (1, 1, 0, 0)

    def test_fixture_files_are_valid_jsonl(self) -> None:
        for path in (_CORRECT, _WRONG):
            for line in path.read_text(encoding="utf-8").splitlines():
                assert isinstance(json.loads(line), dict)
