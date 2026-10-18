"""개념형 개수 MC 배치 테스트 — 수율·라운드트립(answer_kind 보존)·결정론·S6·커버리지(hermetic).

배치가 게이트(개수/판정 SymPy 검증) 통과분만 적재하고, answer_kind가 로더·재검증에 보존되며,
15 kebab이 machine-decidable로 승격됨을 동결한다.
"""

from __future__ import annotations

import json
from pathlib import Path

from whymath_backend.harness import corpus_reverify as cr
from whymath_backend.harness.conceptual_count_mc_batch import (
    run_conceptual_count_mc_batch,
)
from whymath_backend.harness.crosslink_demotion_eval import (
    _default_misconceptions,
    _default_problem_corpora,
    run,
)
from whymath_backend.l1.problem_bank.populate import load_problem_bank_records
from whymath_backend.l1.standards.phase3_stem_fold import distinct_count
from whymath_backend.l3.equivalent.conceptual_count_mc_generator import (
    EXTREMUM_POSITIVE_COUNT,
)
from whymath_backend.l3.verify_answer import verify_extremum_count
from whymath_backend.l4.misconception.crosslink_standard_signal import (
    derive_kebab_standards,
)

_KEBABS = {
    "discriminant-negative-no-real-root",
    "critical-point-implies-extremum",
    "invertibility-without-1-1",
    "geometric-series-always-converges",
    "limit-equals-function-value",
    "continuity-implies-differentiability",
    "term-to-zero-implies-convergence",
    "division-by-zero",
    "mean-vs-median",
    "mutually-exclusive-implies-independent",
    "prosecutor-fallacy",
    "similarity-vs-congruence",
    "dot-product-is-vector",
    "sign-flip-in-inequality",
    "root-loss-by-dividing",
}
_KINDS = {
    "real_root_count",
    "extremum_count",
    "is_one_to_one",
    "geometric_convergence",
    "limit_equals_value",
    "is_differentiable",
    "series_converges",
    "excluded_point_count",
    "mean_equals_median",
    "events_independent",
    "conditional_equal",
    "congruent_by_ratio",
    "dot_product_scalar",
    "inequality_direction",
    "root_loss_count",
}


def test_dry_run_full_yield() -> None:
    report = run_conceptual_count_mc_batch(
        n_per_band=24, out_path=Path("/nonexistent/never.jsonl"), write=False
    )
    assert report.fulfilled
    assert [(b.name, b.stored) for b in report.bands] == [
        ("discriminant-negative-no-real-root", 24),
        ("critical-point-implies-extremum", 24 + EXTREMUM_POSITIVE_COUNT),
        ("invertibility-without-1-1", 24),
        ("geometric-series-always-converges", 24),
        ("limit-equals-function-value", 24),
        ("continuity-implies-differentiability", 24),
        ("term-to-zero-implies-convergence", 24),
        ("division-by-zero", 24),
        ("mean-vs-median", 24),
        ("mutually-exclusive-implies-independent", 24),
        ("prosecutor-fallacy", 24),
        ("similarity-vs-congruence", 24),
        ("dot-product-is-vector", 24),
        ("sign-flip-in-inequality", 24),
        ("root-loss-by-dividing", 24),
    ]


def test_roundtrip_preserves_answer_kind(tmp_path: Path) -> None:
    out = tmp_path / "problems.jsonl"
    report = run_conceptual_count_mc_batch(n_per_band=24, out_path=out, write=True)
    assert report.fulfilled and report.written == 360 + EXTREMUM_POSITIVE_COUNT
    records = load_problem_bank_records(out)
    kinds = {r.verify.answer_kind for r in records}
    assert kinds == _KINDS
    for r in records:
        assert r.verify.answer_kind in _KINDS
        assert r.verify.answer_map == {}  # 개수/판정은 근 대입 아님
        assert r.problem.choices == ["0", "1", "2", "3"]
        assert r.problem.answer in r.problem.choices


def test_rerun_byte_identical(tmp_path: Path) -> None:
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    run_conceptual_count_mc_batch(n_per_band=24, out_path=a, write=True)
    run_conceptual_count_mc_batch(n_per_band=24, out_path=b, write=True)
    assert a.read_bytes() == b.read_bytes()


def test_s6_reverify_zero_fail(tmp_path: Path) -> None:
    # 개수/판정 문항이 S6 재검증에서 SymPy 독립 계산으로 전건 pass(콘텐츠 무결성).
    out = tmp_path / "problems.jsonl"
    run_conceptual_count_mc_batch(n_per_band=24, out_path=out, write=True)
    records = cr._iter_records(out.read_text(encoding="utf-8"))
    report = cr.reverify_corpus(records, use_fuzz=False)
    assert report.failed == 0 and report.passed == 360 + EXTREMUM_POSITIVE_COUNT


def test_committed_corpus_covers_thirteen_kebabs() -> None:
    # 커밋 코퍼스 전체 — 15 개념형 kebab이 machine-decidable(구조 신호 有)·정답 오거부 0.
    records = []
    for path in _default_problem_corpora():
        records.extend(load_problem_bank_records(path))
    derived = derive_kebab_standards(records)
    for kebab in _KEBABS:
        assert kebab in derived  # 문항 등장 → 성취기준 역유도됨
    report, _ = run(
        problem_corpora=_default_problem_corpora(),
        misconceptions=_default_misconceptions(),
        cross_per_positive=60,
        same_per_positive=60,
    )
    assert report.kebabs_decidable >= 32
    assert report.positive_false_reject == 0


_CONCEPT_02_01 = "H:12미적Ⅰ02-01"
_CONCEPT_02_07 = "H:12미적Ⅰ02-07"


def _committed_conceptual_rows() -> list[dict]:
    path = (
        Path(__file__).resolve().parents[3]
        / "data/corpus/problem_bank_conceptual_v0/problems.jsonl"
    )
    rows = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert rows, f"코퍼스를 한 줄도 못 읽었다: {path}"  # 스캔 0건은 공허한 통과다
    return rows


def _primary_concepts(row: dict) -> list[str]:
    return [c["concept_src_id"] for c in row["concepts"] if c["role"] == "PRIMARY"]


def _committed_extremum_rows() -> list[dict]:
    return [
        r
        for r in _committed_conceptual_rows()
        if (r.get("verify") or {}).get("answer_kind") == "extremum_count"
    ]


def test_committed_extremum_count_items_have_no_02_01_primary() -> None:
    """P3-49 집행 지점 — 극값의 개수 문항이 02-01 PRIMARY 로 되살아나는 길을 코퍼스 쪽에서 막는다.

    answer_kind(구조)와 발문(표면) 두 축으로 모두 잡는다 — 한쪽만 보면 다른 쪽 표기 변형에서 뚫린다.
    P3-51 이 양성 예 12건을 더해 대상은 36건(기존 24 + 12)이다.
    """
    rows = _committed_conceptual_rows()
    by_kind = _committed_extremum_rows()
    by_stem = [r for r in rows if "극값의 개수" in r["question_text"]]
    expected = 24 + EXTREMUM_POSITIVE_COUNT
    assert (
        len(by_kind) == expected and len(by_stem) == expected
    )  # 대상이 사라지면 가드가 공허해진다
    for r in by_kind + by_stem:
        assert _primary_concepts(r) == [_CONCEPT_02_07], r["problem_id"]
        assert _CONCEPT_02_01 not in _primary_concepts(r)


def test_committed_extremum_count_concept_matches_a_fresh_generation(tmp_path: Path) -> None:
    """커밋 코퍼스가 생성기 표와 따로 놀지 않는다 — 다시 생성해도 같은 문항은 같은 개념이다."""
    out = tmp_path / "problems.jsonl"
    run_conceptual_count_mc_batch(n_per_band=24, out_path=out, write=True)
    fresh = {
        r["problem_id"]: _primary_concepts(r)
        for r in map(json.loads, out.read_text(encoding="utf-8").splitlines())
        if (r.get("verify") or {}).get("answer_kind") == "extremum_count"
    }
    committed = {r["problem_id"]: _primary_concepts(r) for r in _committed_extremum_rows()}
    assert len(fresh) == 24 + EXTREMUM_POSITIVE_COUNT and fresh == committed


def test_committed_extremum_count_has_positive_examples_awaiting_review() -> None:
    """P3-51 ① ③ ④ — 정답이 0 하나가 아니고, 승인 문항은 그대로이며, 새 문항은 승인 전에 멈춘다.

    기존 24건(정답 0)은 승인 상태 그대로 두고, 양성 예(정답 ≠ 0)는 `pending` 이다 — 표본 검수(200/360)가
    보지 않은 문항에 코퍼스 판정을 빌려 오지 않는다.
    """
    rows = _committed_extremum_rows()
    zeros = [r for r in rows if r["answer"] == "0"]
    positives = [r for r in rows if r["answer"] != "0"]
    assert len(zeros) == 24 and len(positives) == EXTREMUM_POSITIVE_COUNT
    assert {r["review_status"] for r in zeros} == {"approved"}
    assert {r["review_status"] for r in positives} == {"pending"}
    assert {r["answer"] for r in positives} == {"1", "2"}  # 정답 분포가 0 하나에서 벗어난다


def test_committed_extremum_count_positives_have_honest_misconception_attribution() -> None:
    """P3-51 ② — 오개념 오답 선지는 오개념이 *실제로 내는* 답(임계점 수)이고 정답과 다르다.

    "임계점 = 극값" 오개념은 임계점 개수를 답한다. 임계점 수가 극값 수와 같은 함수(x³-3x)에 이 오개념을
    붙이면 오답 선지가 곧 정답이라 거짓 귀속이다. 그런 문항이 코퍼스에 없음을 SymPy 독립 검증으로 막는다:
    정답은 pass, 귀속된 오답은 fail 이어야 한다.
    """
    positives = [r for r in _committed_extremum_rows() if r["answer"] != "0"]
    assert positives  # 0건 스캔은 통과가 아니다
    for r in positives:
        (entry,) = r["distractor_map"]
        tagged = r["choices"][entry["choice_index"]]
        assert tagged != r["answer"], r["problem_id"]
        conditions = r["verify"]["conditions"]
        assert verify_extremum_count(conditions, r["answer"]).state == "pass", r["problem_id"]
        assert verify_extremum_count(conditions, tagged).state == "fail", r["problem_id"]


def test_extremum_count_distinct_problems_grew_beyond_two() -> None:
    """P3-51 ③ — 숫자만 다른 복제가 아니다: stem_fold 기준 서로 다른 문제 수가 2개에서 늘었다.

    기존 24건은 접으면 문면이 2종(c=0 / c≠0)뿐이다. 양성 예를 더한 36건은 그보다 많아야 한다.
    """
    rows = _committed_extremum_rows()
    zeros = distinct_count(r["question_text"] for r in rows if r["answer"] == "0")
    assert zeros.distinct == 2  # 비교 기준이 흔들리면 아래 단언이 의미를 잃는다
    everything = distinct_count(r["question_text"] for r in rows)
    assert everything.unfolded == 0
    assert everything.distinct >= 10
