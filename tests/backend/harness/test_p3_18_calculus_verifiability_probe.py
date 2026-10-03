"""P3-18 — 미적분Ⅰ '미분' 핵심 개념 7개의 SymPy 검증 가능성 프로브(순수·결정론·LLM 0·DB 0).

배경: `docs/reviews/p3_01_scope_candidates_2026-09-30.md` §3.2가 후보 1(미적분Ⅰ '미분')의 가장
큰 위험으로 적은 "단원별 SymPy 검증 경로 가용성은 측정하지 않았다"를 *측정*으로 바꾼다.
문항 0건인 핵심 개념 7개(`[12미적Ⅰ-02-03]`·`-04`·`-05`·`-06`·`-08`·`-09`·`-10`)마다 정답 행 1개와
오답 주입 행 1개(정답 값만 틀리게 바꾼 행)를 `fixtures/p3_18_{correct,wrong}.jsonl`에 두고, **기존
재검증 경로 `whymath_backend.harness.corpus_reverify`의 CLI**(`main`)에 태워 exit code와 통과/실패/
skip 수로 개념별 판정을 낸다.

판정(태스크 acceptance ②·③ 동결):
  - 가능      : 정답 파일 exit 0 + skip 0, 오답 파일 exit 1 + 실패 수 == 오답 행 수.
  - 일부 가능 : 정답은 통과하나 오답이 전부 실패하지는 않는다(한쪽만 만족).
  - 불가      : 정답 행이 skip(unverifiable) — exit 0이어도 '검증됨'이 아니다.
  - 위장(무효): 정답·오답이 둘 다 통과 — 변별력이 없는 프로브라 무효(원인을 따로 적는다).
  - 정답 오거부(무효): 정답 행이 fail — 검증 경로가 정답을 오염으로 오판하는 프로브 결함.

`corpus_reverify`는 unverifiable을 skip으로 넘기고 fail일 때만 exit 1을 내므로, exit 0만으로
"검증됨"이라 하지 않는다 — 판정은 반드시 exit code *와* skip 수를 함께 본다.

판정 함수(`judge_concept`)는 이 파일 안의 순수 함수다(src에 새 모듈을 만들지 않는다 — 신규 모듈은
EOS 기능 인벤토리 전수 귀속 대상이라 측정 도구 하나 때문에 대장을 늘리지 않는다).
"""

from __future__ import annotations

import contextlib
import io
import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import pytest

from whymath_backend.harness import corpus_reverify as cr

_FIXTURES = Path(__file__).parent / "fixtures"
_CORRECT = _FIXTURES / "p3_18_correct.jsonl"
_WRONG = _FIXTURES / "p3_18_wrong.jsonl"
_SUPPLEMENT = _FIXTURES / "p3_18_supplement.jsonl"

_CONCEPTS: tuple[str, ...] = (
    "[12미적Ⅰ-02-03]",
    "[12미적Ⅰ-02-04]",
    "[12미적Ⅰ-02-05]",
    "[12미적Ⅰ-02-06]",
    "[12미적Ⅰ-02-08]",
    "[12미적Ⅰ-02-09]",
    "[12미적Ⅰ-02-10]",
)


# ──────────────────────────────────────────────────────────────────────────
# 판정 로직 — 순수 함수(이 파일이 동결)
# ──────────────────────────────────────────────────────────────────────────


class Verdict(str, Enum):
    """개념 1개의 검증 가능성 판정 — 3상태 + 무효 2종."""

    POSSIBLE = "가능"
    PARTIAL = "일부 가능"
    IMPOSSIBLE = "불가"
    SHAM = "위장"  # 정답·오답 둘 다 통과 — 변별력 없음(무효)
    CORRECT_REJECTED = "정답 오거부"  # 정답 행이 fail — 프로브/검증 경로 결함(무효)


@dataclass(frozen=True, slots=True)
class FileOutcome:
    """코퍼스 파일 1개를 `corpus_reverify` CLI에 태운 결과 — exit code + 통과/실패/skip 수."""

    exit_code: int
    passed: int
    failed: int
    skipped: int

    def __post_init__(self) -> None:
        if min(self.passed, self.failed, self.skipped) < 0:
            raise ValueError("건수는 음수일 수 없다")
        # corpus_reverify는 fail이 1건이라도 있을 때만 exit 1이다 — 어긋나면 측정이 깨진 것이다.
        expected = 1 if self.failed > 0 else 0
        if self.exit_code != expected:
            raise ValueError(f"exit code {self.exit_code} 가 실패 수 {self.failed} 와 모순")

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.skipped


def judge_concept(correct: FileOutcome, wrong: FileOutcome) -> Verdict:
    """정답 파일·오답 파일 결과로 개념의 검증 가능성을 판정한다(순수·결정론).

    우선순위: ①오답 통과(위장) → ②정답 fail(오거부) → ③정답 skip(불가) → ④가능/일부 가능.
    ③이 ④보다 앞이므로 '정답 skip + 오답 전부 fail'도 *일부*가 아니라 *불가*다(정답이 검증 안
    되는 개념은 오답이 실패해도 정답 문항을 코퍼스에 세울 수 없다).
    스캔 0건·행 수 불일치는 판정하지 않고 ValueError — 공허한 통과를 막는다.
    """
    if correct.total == 0 or wrong.total == 0:
        raise ValueError("판정 대상 0건 — 공허한 통과 금지")
    if correct.total != wrong.total:
        raise ValueError(f"정답 {correct.total}행 ≠ 오답 {wrong.total}행 — 쌍이 어긋났다")

    if wrong.passed > 0:
        # 오답을 받아들이는 검증 경로는 정답 통과가 있든 없든 변별력이 없다.
        return Verdict.SHAM
    if correct.failed > 0:
        return Verdict.CORRECT_REJECTED
    if correct.skipped > 0:
        return Verdict.IMPOSSIBLE

    # 여기서 정답은 전부 통과(exit 0·skip 0·fail 0). 오답이 *전부 fail*이어야 '가능'.
    wrong_all_rejected = wrong.exit_code == 1 and wrong.failed == wrong.total
    return Verdict.POSSIBLE if wrong_all_rejected else Verdict.PARTIAL


# ──────────────────────────────────────────────────────────────────────────
# 실행 도구 — 실제 CLI 경로(main)를 태우고 출력 요약행에서 건수를 읽는다
# ──────────────────────────────────────────────────────────────────────────

_SUMMARY = re.compile(r"총 (\d+)\s+통과 (\d+)\s+실패 (\d+)\s+skip (\d+)")


def run_cli(path: Path) -> FileOutcome:
    """`corpus_reverify.main`을 파일 1개에 실행 → exit code·건수(CLI 출력 요약행에서 파싱)."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        exit_code = cr.main([str(path)])
    match = _SUMMARY.search(buffer.getvalue())
    assert match is not None, f"CLI 요약행을 못 읽었다: {buffer.getvalue()!r}"
    _, passed, failed, skipped = (int(g) for g in match.groups())
    return FileOutcome(exit_code=exit_code, passed=passed, failed=failed, skipped=skipped)


def _read_rows(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _write_rows(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )
    return path


def _outcome_of_row(row: dict[str, object], tmp_dir: Path, name: str) -> FileOutcome:
    """행 1개를 1행짜리 파일로 써서 CLI에 태운다(개념별 exit code 근거)."""
    return run_cli(_write_rows(tmp_dir / f"{name}.jsonl", [row]))


def _by_concept(rows: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {str(r["probe_concept"]): r for r in rows}


def _probe_verdicts(tmp_dir: Path) -> dict[str, Verdict]:
    correct = _by_concept(_read_rows(_CORRECT))
    wrong = _by_concept(_read_rows(_WRONG))
    verdicts: dict[str, Verdict] = {}
    for code in _CONCEPTS:
        tag = code.strip("[]").replace("Ⅰ", "I")
        c_out = _outcome_of_row(correct[code], tmp_dir, f"c_{tag}")
        w_out = _outcome_of_row(wrong[code], tmp_dir, f"w_{tag}")
        verdicts[code] = judge_concept(c_out, w_out)
    return verdicts


# ──────────────────────────────────────────────────────────────────────────
# ① 판정 함수 — 3상태 + 무효 2종 전부에 픽스처 반례
# ──────────────────────────────────────────────────────────────────────────


def _out(passed: int = 0, failed: int = 0, skipped: int = 0) -> FileOutcome:
    return FileOutcome(exit_code=1 if failed else 0, passed=passed, failed=failed, skipped=skipped)


class TestJudgeConcept:
    def test_possible_when_correct_all_pass_and_wrong_all_fail(self) -> None:
        assert judge_concept(_out(passed=1), _out(failed=1)) is Verdict.POSSIBLE
        assert judge_concept(_out(passed=7), _out(failed=7)) is Verdict.POSSIBLE

    def test_partial_when_correct_passes_but_wrong_not_all_failed(self) -> None:
        # 오답이 skip — 정답은 통과하지만 오답은 걸러내지 못한다(한쪽만 만족).
        assert judge_concept(_out(passed=1), _out(skipped=1)) is Verdict.PARTIAL
        # 오답 일부만 fail(2/3) — 실패 수 != 오답 행 수.
        assert judge_concept(_out(passed=3), _out(failed=2, skipped=1)) is Verdict.PARTIAL

    def test_impossible_when_correct_row_skipped(self) -> None:
        assert judge_concept(_out(skipped=1), _out(skipped=1)) is Verdict.IMPOSSIBLE
        # 정답 skip + 오답 fail(한쪽만 만족)이어도 '일부'가 아니라 '불가' — 정답이 검증되지 않는다.
        assert judge_concept(_out(skipped=1), _out(failed=1)) is Verdict.IMPOSSIBLE
        # 정답 파일 일부 skip(exit 0)은 '검증됨'이 아니다.
        assert judge_concept(_out(passed=6, skipped=1), _out(failed=7)) is Verdict.IMPOSSIBLE

    def test_sham_when_both_correct_and_wrong_pass(self) -> None:
        assert judge_concept(_out(passed=1), _out(passed=1)) is Verdict.SHAM
        # 오답이 하나라도 통과하면 위장 — 나머지가 fail이어도.
        assert judge_concept(_out(passed=2), _out(passed=1, failed=1)) is Verdict.SHAM
        # 정답이 skip이어도 오답을 받아들이면 변별력 문제가 먼저다.
        assert judge_concept(_out(skipped=1), _out(passed=1)) is Verdict.SHAM

    def test_correct_rejected_when_correct_row_fails(self) -> None:
        assert judge_concept(_out(failed=1), _out(failed=1)) is Verdict.CORRECT_REJECTED
        assert judge_concept(_out(passed=6, failed=1), _out(failed=7)) is Verdict.CORRECT_REJECTED

    def test_vacuous_scan_is_refused(self) -> None:
        with pytest.raises(ValueError, match="0건"):
            judge_concept(_out(), _out())
        with pytest.raises(ValueError, match="0건"):
            judge_concept(_out(), _out(failed=1))

    def test_mismatched_pair_is_refused(self) -> None:
        with pytest.raises(ValueError, match="어긋"):
            judge_concept(_out(passed=2), _out(failed=1))

    def test_file_outcome_rejects_contradictory_exit_code(self) -> None:
        with pytest.raises(ValueError, match="모순"):
            FileOutcome(exit_code=0, passed=0, failed=1, skipped=0)
        with pytest.raises(ValueError, match="모순"):
            FileOutcome(exit_code=1, passed=1, failed=0, skipped=0)
        with pytest.raises(ValueError, match="음수"):
            FileOutcome(exit_code=0, passed=-1, failed=0, skipped=0)


# ──────────────────────────────────────────────────────────────────────────
# ② 프로브 fixture 형태 — 14행·쌍 대응·'정답 값만 틀리게'
# ──────────────────────────────────────────────────────────────────────────


class TestProbeFixtureShape:
    def test_seven_concepts_each_have_one_correct_and_one_wrong_row(self) -> None:
        correct = _read_rows(_CORRECT)
        wrong = _read_rows(_WRONG)
        assert len(correct) == 7 and len(wrong) == 7
        assert [r["probe_concept"] for r in correct] == list(_CONCEPTS)
        assert [r["probe_concept"] for r in wrong] == list(_CONCEPTS)
        assert {r["probe_role"] for r in correct} == {"correct"}
        assert {r["probe_role"] for r in wrong} == {"wrong"}
        for row in correct + wrong:
            assert row["achievement_standard_codes"] == [row["probe_concept"]]
            assert row["license"] == "WHYMATH_GENERATED"  # 교과서·기출 복제 0 — 자체 제작 수치

    def test_wrong_row_differs_from_correct_only_in_the_answer(self) -> None:
        correct = _by_concept(_read_rows(_CORRECT))
        wrong = _by_concept(_read_rows(_WRONG))
        for code in _CONCEPTS:
            c_row, w_row = correct[code], wrong[code]
            assert c_row["question_text"] == w_row["question_text"]
            assert c_row["answer"] != w_row["answer"], code
            c_verify, w_verify = c_row.get("verify"), w_row.get("verify")
            if c_verify is None:
                assert w_verify is None, code
                continue
            assert isinstance(c_verify, dict) and isinstance(w_verify, dict)
            # 조건식·검증 종류는 같고, 검산에 쓰이는 답 값만 다르다.
            assert c_verify["conditions"] == w_verify["conditions"], code
            assert c_verify.get("answer_kind") == w_verify.get("answer_kind"), code
            assert (c_verify["answer_map"], c_row["answer"]) != (
                w_verify["answer_map"],
                w_row["answer"],
            ), code

    def test_slugs_are_unique_and_clean(self) -> None:
        slugs = [r["slug"] for r in _read_rows(_CORRECT) + _read_rows(_WRONG)]
        assert len(set(slugs)) == 14
        assert all(re.fullmatch(r"p3-18-probe-02-\d\d-(correct|wrong)", str(s)) for s in slugs)


# ──────────────────────────────────────────────────────────────────────────
# ③ 실측 — 프로브를 실제 corpus_reverify CLI에 태워 개념별 판정을 단언
#     (가설: 03·04·10 가능 / 05·06·09 일부 / 08 불가 — 실측이 가설과 달라도 실측을 동결한다)
# ──────────────────────────────────────────────────────────────────────────

# 2026-10-01 실측. 가설과 다른 곳: -02-05(접선식)는 '이중근 항등식' 조건으로 표본 검증이 통과·오답이
# fail이라 가능, -02-06(c값)·-02-09(실근 개수)도 수치형은 가능. 단 가능의 한계(표본 검증·구간
# 소속 미검증·매개변수형 skip)는 아래 보강 진단 행(`p3_18_supplement.jsonl`)이 동결한다.
_EXPECTED_VERDICTS: dict[str, Verdict] = {
    "[12미적Ⅰ-02-03]": Verdict.POSSIBLE,
    "[12미적Ⅰ-02-04]": Verdict.POSSIBLE,
    "[12미적Ⅰ-02-05]": Verdict.POSSIBLE,
    "[12미적Ⅰ-02-06]": Verdict.POSSIBLE,
    "[12미적Ⅰ-02-08]": Verdict.IMPOSSIBLE,
    "[12미적Ⅰ-02-09]": Verdict.POSSIBLE,
    "[12미적Ⅰ-02-10]": Verdict.POSSIBLE,
}


class TestRealProbeThroughCorpusReverify:
    def test_per_concept_verdicts_match_measurement(self, tmp_path: Path) -> None:
        assert _probe_verdicts(tmp_path) == _EXPECTED_VERDICTS

    def test_no_concept_is_sham_or_correct_rejected(self, tmp_path: Path) -> None:
        # 위장·정답 오거부는 프로브가 무효라는 뜻 — 어느 개념에도 있어서는 안 된다.
        bad = {
            code: v
            for code, v in _probe_verdicts(tmp_path).items()
            if v in (Verdict.SHAM, Verdict.CORRECT_REJECTED)
        }
        assert bad == {}

    def test_whole_file_exit_codes_and_counts(self) -> None:
        # 7행 일괄 실행: 정답 파일은 exit 0이지만 skip 1(-02-08)이라 '검증됨'이 아니다.
        correct = run_cli(_CORRECT)
        assert (correct.exit_code, correct.passed, correct.failed, correct.skipped) == (0, 6, 0, 1)
        # 오답 파일은 exit 1·실패 6(= 개념 6개). -02-08 오답은 skip이라 실패 수 6 != 행 수 7.
        wrong = run_cli(_WRONG)
        assert (wrong.exit_code, wrong.passed, wrong.failed, wrong.skipped) == (1, 0, 6, 1)
        # 일괄 판정은 정답 skip이므로 '불가' — 개념별로 쪼개야 불가가 1개뿐임이 보인다.
        assert judge_concept(correct, wrong) is Verdict.IMPOSSIBLE

    def test_wrong_rows_actually_fail_for_every_verifiable_concept(self, tmp_path: Path) -> None:
        # 변별력(acceptance ③): 오답 주입 행이 실제로 fail한다 — exit 1이고 실패 1건.
        wrong = _by_concept(_read_rows(_WRONG))
        for code in _CONCEPTS:
            if _EXPECTED_VERDICTS[code] is not Verdict.POSSIBLE:
                continue
            out = _outcome_of_row(wrong[code], tmp_path, f"w_{code[-5:]}")
            assert (out.exit_code, out.failed, out.passed, out.skipped) == (1, 1, 0, 0), code

    def test_graph_shape_impossibility_reason_is_frozen(self) -> None:
        # -02-08 '불가'의 원인 = 개형 판정 검증기가 현행 디스패치에 없다. 누가 등록하면 이 테스트가
        # RED가 되어 프로브를 다시 돌리게 만든다(가설이 사실로 굳어 낡는 것을 막는다).
        kinds = sorted(cr._CONCEPTUAL_VERIFIERS)
        offending = [
            k
            for k in kinds
            if any(t in k for t in ("graph", "shape", "sketch", "mean_value", "lagrange"))
        ]
        assert (
            offending == []
        ), f"개형·평균값 정리 검증기가 등록됐다 — 프로브 재실행 필요: {offending}"
        c_row = _by_concept(_read_rows(_CORRECT))["[12미적Ⅰ-02-08]"]
        assert "verify" not in c_row  # 개형은 verify 재료를 만들 방법이 없다(보강 진단 08 참고)


# ──────────────────────────────────────────────────────────────────────────
# ④ 보강 진단 — 14행 판정에 불산입. '가능'의 한계와 불가 원인을 행동으로 동결
# ──────────────────────────────────────────────────────────────────────────


class TestSupplementDiagnostics:
    def test_each_supplement_row_behaves_as_recorded(self) -> None:
        rows = _read_rows(_SUPPLEMENT)
        assert len(rows) == 7
        for row in rows:
            report = cr.reverify_corpus([row], use_fuzz=False)
            state = "pass" if report.passed else "fail" if report.failed else "skip"
            assert state == row["probe_expected_state"], (row["slug"], row["probe_why"])

    def test_interval_membership_makes_02_06_possible_not_sham(self, tmp_path: Path) -> None:
        # P3-19 수정 뒤: 구간 밖 근(-√3)은 fail이라 정답 통과와 짝지어도 위장이 아니다.
        supplement = {str(r["slug"]): r for r in _read_rows(_SUPPLEMENT)}
        leak = supplement["p3-18-supplement-06-interval-leak"]
        correct_06 = _by_concept(_read_rows(_CORRECT))["[12미적Ⅰ-02-06]"]
        verdict = judge_concept(
            _outcome_of_row(correct_06, tmp_path, "c06"),
            _outcome_of_row(leak, tmp_path, "leak06"),
        )
        assert verdict is Verdict.POSSIBLE

    def test_two_roots_one_inside_pairs_pass_and_fail(self) -> None:
        # 방정식 3c²=9 의 근이 ±√3 둘이고 (0,3) 안은 √3 하나 — 정답 pass·구간 밖 근 fail.
        rows = {str(r["slug"]): r for r in _read_rows(_SUPPLEMENT)}
        ok = cr.reverify_corpus([rows["p3-18-supplement-06-interval-ok"]], use_fuzz=False)
        bad = cr.reverify_corpus([rows["p3-18-supplement-06-interval-leak"]], use_fuzz=False)
        assert (ok.passed, ok.failed, ok.skipped) == (1, 0, 0)
        assert (bad.passed, bad.failed, bad.skipped) == (0, 1, 0)

    def test_equation_only_condition_still_leaks_so_interval_clauses_are_load_bearing(
        self,
    ) -> None:
        # 뮤테이션: 구간 조건 절을 지우면(방정식만 남기면) 오답이 다시 통과한다 — 절이 실제 보호.
        leak = {str(r["slug"]): r for r in _read_rows(_SUPPLEMENT)}[
            "p3-18-supplement-06-interval-leak"
        ]
        conditions = leak["verify"]["conditions"]
        assert isinstance(conditions, list) and len(conditions) == 5
        mutated = json.loads(json.dumps(leak))
        mutated["verify"]["conditions"] = conditions[0]  # 방정식 절만 남김
        assert mutated["verify"]["conditions"] != conditions  # 주입이 실제로 적용됐다
        report = cr.reverify_corpus([mutated], use_fuzz=False)
        assert (report.passed, report.failed) == (1, 0)

    def test_open_interval_endpoint_is_a_fail_not_a_skip(self) -> None:
        # 끝점이 방정식의 근이어도 열린구간 (0,3) 밖이라 fail이다. 엄격 부등식(c < 3)만 쓰면
        # 끝점에서 '경계 모호'로 skip이 되므로 >=·!= 쌍으로 쓴다.
        for endpoint in ("0", "3"):
            record: dict[str, object] = {
                "slug": f"endpoint-{endpoint}",
                "answer": endpoint,
                "verify": {
                    "conditions": ["c*(c - 3) = 0", "c >= 0", "c <= 3", "c != 0", "c != 3"],
                    "answer_map": {"c": endpoint},
                },
            }
            report = cr.reverify_corpus([record], use_fuzz=True)
            assert (report.passed, report.failed, report.skipped) == (0, 1, 0), endpoint

    def test_malformed_condition_list_is_skipped_not_passed(self) -> None:
        # 빈 목록·비문자열 원소는 형식 부적합 skip — 통과로 위장하지 않는다.
        for bad in ([], ["c = 1", 2]):
            record: dict[str, object] = {
                "slug": "malformed",
                "answer": "1",
                "verify": {"conditions": bad, "answer_map": {"c": "1"}},
            }
            report = cr.reverify_corpus([record], use_fuzz=False)
            assert (report.passed, report.failed, report.skipped) == (0, 0, 1)

    def test_derived_extremum_form_is_possible_for_graph_concept(self, tmp_path: Path) -> None:
        # 처분안 '나'(파생 판정으로 대체)의 근거: -02-08을 극값 개수로 바꾸면 기존 검증기로 가능.
        supplement = {str(r["slug"]): r for r in _read_rows(_SUPPLEMENT)}
        verdict = judge_concept(
            _outcome_of_row(
                supplement["p3-18-supplement-08-derived-extremum-ok"], tmp_path, "d_ok"
            ),
            _outcome_of_row(
                supplement["p3-18-supplement-08-derived-extremum-bad"], tmp_path, "d_bad"
            ),
        )
        assert verdict is Verdict.POSSIBLE

    def test_bare_expression_graph_attempt_is_a_false_fail_not_a_skip(self, tmp_path: Path) -> None:
        # 개형을 함수식 단독 조건으로 억지 표현하면 정답도 fail(exit 1) — 불가가 아니라 오염으로
        # 위장된다. 그래서 -02-08 본 프로브는 verify 재료를 두지 않는다.
        row = {str(r["slug"]): r for r in _read_rows(_SUPPLEMENT)}[
            "p3-18-supplement-08-bare-expression"
        ]
        out = _outcome_of_row(row, tmp_path, "bare")
        assert (out.exit_code, out.failed) == (1, 1)
