"""전 코퍼스 재검증 CLI 테스트 — 초인간 검증 S6(순수·결정론·라이브 0).

정상 레코드 통과·오염 레코드 fail(exit 1)·verify 재료 없음 skip·fuzz 모드를 동결.
픽스처는 실제 레코드처럼 `answer` 필드를 갖는다 — 승인·미승인 은행 15,042건 전부가 갖고 있고,
없으면 학생 표기 대조(OPS-150)가 대조 불가 skip 으로 드러낸다(아래 OPS-150 절).
"""

from __future__ import annotations

import json
from pathlib import Path

from whymath_backend.harness import corpus_reverify as cr

_OK = {
    "slug": "ok-1",
    "answer": "5",
    "verify": {
        "conditions": "x**2 - 5*x = 0",
        "answer_map": {"x": "5"},
        "answer_selection": "largest",
    },
}
_WRONG_ANSWER = {
    "slug": "bad-1",
    "answer": "6",
    "verify": {
        "conditions": "x**2 - 5*x = 0",
        "answer_map": {"x": "6"},  # 6은 근이 아님
        "answer_selection": "largest",
    },
}
_WRONG_SELECTION = {
    "slug": "bad-2",
    "answer": "5",
    "verify": {
        "conditions": "x**2 - 5*x = 0",
        "answer_map": {"x": "5"},
        "answer_selection": "smallest",  # 작은 근은 0
    },
}
_NO_VERIFY = {"slug": "skip-1", "question_text": "설명형 문항"}


def test_pass_on_correct_record() -> None:
    report = cr.reverify_corpus([_OK], use_fuzz=False)
    assert report.passed == 1 and report.failed == 0 and report.skipped == 0


def test_fail_on_wrong_answer() -> None:
    report = cr.reverify_corpus([_WRONG_ANSWER], use_fuzz=False)
    assert report.failed == 1
    assert report.failures[0][0] == "bad-1"


def test_fail_on_wrong_selection() -> None:
    report = cr.reverify_corpus([_WRONG_SELECTION], use_fuzz=False)
    assert report.failed == 1


def test_skip_on_missing_verify() -> None:
    report = cr.reverify_corpus([_NO_VERIFY], use_fuzz=False)
    assert report.skipped == 1 and report.failed == 0


def test_fuzz_mode_catches_wrong_answer() -> None:
    report = cr.reverify_corpus([_WRONG_ANSWER], use_fuzz=True)
    assert report.failed == 1


def test_cli_exit_zero_on_clean(tmp_path: Path) -> None:
    p = tmp_path / "clean.jsonl"
    p.write_text(json.dumps(_OK, ensure_ascii=False) + "\n", encoding="utf-8")
    assert cr.main([str(p)]) == 0


def test_cli_exit_one_on_corruption(tmp_path: Path) -> None:
    p = tmp_path / "dirty.jsonl"
    p.write_text(
        json.dumps(_OK, ensure_ascii=False)
        + "\n"
        + json.dumps(_WRONG_ANSWER, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    assert cr.main([str(p)]) == 1


def test_cli_multiple_paths(tmp_path: Path) -> None:
    clean = tmp_path / "a.jsonl"
    clean.write_text(json.dumps(_OK, ensure_ascii=False) + "\n", encoding="utf-8")
    dirty = tmp_path / "b.jsonl"
    dirty.write_text(json.dumps(_WRONG_ANSWER, ensure_ascii=False) + "\n", encoding="utf-8")
    # 하나라도 실패면 전체 exit 1.
    assert cr.main([str(clean), str(dirty)]) == 1


# ── 근 집계(합/곱) 문항 재검증 ─────────────────────────────────────────────
_AGG_OK = {
    "slug": "agg-ok",
    "answer": "10",
    "verify": {
        "conditions": "x**3 - 9*x - 10 = 0",
        "answer_map": {},
        "answer_aggregate": "product",
    },
}
_AGG_BAD = {
    "slug": "agg-bad",
    "answer": "11",
    "verify": {
        "conditions": "x**3 - 9*x - 10 = 0",
        "answer_map": {},
        "answer_aggregate": "product",
    },
}


def test_aggregate_pass() -> None:
    report = cr.reverify_corpus([_AGG_OK], use_fuzz=False)
    assert report.passed == 1 and report.failed == 0


def test_aggregate_wrong_fails() -> None:
    report = cr.reverify_corpus([_AGG_BAD], use_fuzz=False)
    assert report.failed == 1


# ── Tier2 단계 재검증(S2-02) — solution_steps 보유 레코드의 전이 연쇄 검산 ──

_STEPS_OK = {
    "slug": "steps-ok",
    "answer": "5",
    "verify": {
        "conditions": "x**2 - 3*x - 10 = 0",
        "answer_map": {"x": "5"},
        "answer_selection": "largest",
        "solution_steps": ["x**2 - 3*x - 10", "(x - 5)*(x + 2)"],
    },
}
_STEPS_BAD = {
    "slug": "steps-bad",
    "answer": "5",
    "verify": {
        "conditions": "x**2 - 3*x - 10 = 0",
        "answer_map": {"x": "5"},
        "answer_selection": "largest",
        # 부호 반전 인수분해 — 원식과 비동치(확정 오염) → Tier2 fail
        "solution_steps": ["x**2 - 3*x - 10", "(x + 5)*(x - 2)"],
    },
}


def test_steps_correct_chain_passes() -> None:
    report = cr.reverify_corpus([_STEPS_OK], use_fuzz=False)
    assert report.passed == 1 and report.failed == 0


def test_steps_incorrect_chain_fails() -> None:
    # Tier1(답=근)이 통과해도 단계 전이가 비동치면 Tier2가 잡는다(단계 오염 검출).
    report = cr.reverify_corpus([_STEPS_BAD], use_fuzz=False)
    assert report.failed == 1
    assert "Tier2" in report.failures[0][1]


# ──────────────────────────────────────────────────────────────────────────
# S4-68 ④ — v2 전용 kind(statistical_claim·sequence_induction)의 야간 재검증 디스패치
# ──────────────────────────────────────────────────────────────────────────
# 종전엔 디스패치 표가 acceptance 표만 써서 이 두 kind가 개념형 분기에 못 들어가고 Tier1로 떨어져
# (통계·수열 DSL을 못 읽어) unverifiable → **skip**으로 조용히 건너뛰어졌다. 오답이 있어도 fail이
# 아니라 skip이었다는 점이 위험이다 — 야간 재검증이 통과하는 척만 했다.
def _v2_record(slug: str, kind: str, conditions: object, answer: str) -> dict[str, object]:
    return {
        "slug": slug,
        "answer": answer,
        "verify": {"conditions": conditions, "answer_map": {}, "answer_kind": kind},
    }


_STAT = "data=[1,2,3,4,5]; stat=mean"
_SEQ = "init=a(1)=7; rec=a(n+1)=a(n)+6; query=a(12)"


def test_statistical_claim_correct_passes_and_wrong_fails() -> None:
    ok = cr.reverify_corpus(
        [_v2_record("stat-ok", "statistical_claim", _STAT, "3")], use_fuzz=False
    )
    bad = cr.reverify_corpus(
        [_v2_record("stat-bad", "statistical_claim", _STAT, "99")], use_fuzz=False
    )
    assert (ok.passed, ok.failed, ok.skipped) == (1, 0, 0)
    assert (bad.passed, bad.failed, bad.skipped) == (0, 1, 0)
    assert "statistical_claim 불일치" in bad.failures[0][1]


def test_sequence_induction_correct_passes_and_wrong_fails() -> None:
    ok = cr.reverify_corpus(
        [_v2_record("seq-ok", "sequence_induction", _SEQ, "73")], use_fuzz=False
    )
    bad = cr.reverify_corpus(
        [_v2_record("seq-bad", "sequence_induction", _SEQ, "74")], use_fuzz=False
    )
    assert (ok.passed, ok.failed, ok.skipped) == (1, 0, 0)
    assert (bad.passed, bad.failed, bad.skipped) == (0, 1, 0)
    assert "sequence_induction 불일치" in bad.failures[0][1]


def test_v2_only_kind_with_list_conditions_is_skipped_with_reason_not_truncated() -> None:
    """연립(목록) conditions는 v2 도메인 검증기가 못 받는다 — 첫 항만 쓰지 않고 skip 사유를 남긴다."""
    state, reason = cr._reverify_one(
        _v2_record("stat-list", "statistical_claim", [_STAT, _STAT], "3"), use_fuzz=False
    )
    assert state == "skip"
    assert reason is not None and "연립" in reason


def test_every_v2_kind_is_dispatchable_by_nightly_reverify() -> None:
    """v2 레지스트리에 kind가 늘면 야간 재검증 디스패치에도 자동으로 들어온다(수동 등록 불요)."""
    from whymath_backend.l3.verifier import _VERIFIERS_V2

    assert set(_VERIFIERS_V2) <= set(cr._CONCEPTUAL_VERIFIERS)
    # v2 전용 kind가 실제로 둘 이상 있다는 전제 — 어댑터 경로가 공허하지 않다.
    assert {"statistical_claim", "sequence_induction"} <= set(cr._CONCEPTUAL_VERIFIERS)


def test_acceptance_kinds_keep_their_original_dispatch_entries() -> None:
    """대조군 — acceptance 표에 있던 kind는 어댑터로 바뀌지 않고 원래 함수 그대로다(동작 불변)."""
    from whymath_backend.l3.equivalent import acceptance

    table = acceptance._CONCEPTUAL_VERIFIERS
    assert all(cr._CONCEPTUAL_VERIFIERS[k] is fn for k, fn in table.items())


# ──────────────────────────────────────────────────────────────────────────
# OPS-150 — 학생 표기(`answer` 필드) ↔ 검산 재료(`verify.answer_map`) 대조
# ──────────────────────────────────────────────────────────────────────────
# 종전 Tier1 경로는 answer_map 만 검산해서, `answer` 만 틀린 값으로 바꾼 변조를 통과시켰다
# (대표 과정 40건 → 0/40 검출, P3-07 2026-10-18 실측). 아래는 그 구멍이 닫혔는지와, 닫는 과정에서
# 표기만 다른 정답을 거짓 실패로 만들지 않는지, 대조 불가를 통과로 접지 않는지를 함께 동결한다.
import ast  # noqa: E402 — OPS-150 절에서만 쓴다
import contextlib  # noqa: E402
import io  # noqa: E402
import re  # noqa: E402
from collections import Counter  # noqa: E402
from collections.abc import Callable  # noqa: E402

import pytest  # noqa: E402
import sympy  # noqa: E402

_HALF = {"slug": "half", "verify": {"conditions": "2*x - 1 = 0", "answer_map": {"x": "1/2"}}}
# 프로브 테스트 3종(P3-18·P3-20·P3-21)이 이 요약행을 정규식으로 읽는다 — 형식 불변을 함께 동결한다.
_SUMMARY = re.compile(r"총 (\d+)\s+통과 (\d+)\s+실패 (\d+)\s+skip (\d+)")


def _with_answer(record: dict[str, object], answer: str | None) -> dict[str, object]:
    out = json.loads(json.dumps(record))
    if answer is None:
        out.pop("answer", None)
    else:
        out["answer"] = answer
    return out


def _cli(paths: list[Path]) -> tuple[int, str]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = cr.main([str(p) for p in paths])
    return code, buffer.getvalue()


def _write(path: Path, records: list[dict[str, object]]) -> Path:
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8"
    )
    return path


# ── 1. 단일 문항 — 변조 RED · 대조군 GREEN ────────────────────────────────
def test_answer_only_tamper_fails_and_cli_exits_1(tmp_path: Path) -> None:
    tampered = _with_answer(_OK, "6")  # answer_map 은 그대로 정답(5)
    state, reason = cr._reverify_one(tampered, use_fuzz=False)
    assert state == "fail"
    assert reason is not None and reason.startswith(cr.ANSWER_MISMATCH_REASON)
    report = cr.reverify_corpus([tampered], use_fuzz=False)
    assert (report.passed, report.failed, report.skipped) == (0, 1, 0)
    assert report.answer_mismatched == 1
    assert cr.main([str(_write(tmp_path / "t.jsonl", [tampered]))]) == 1


def test_untampered_control_passes_with_answer_matched(tmp_path: Path) -> None:
    report = cr.reverify_corpus([_OK], use_fuzz=False)
    assert (report.passed, report.failed, report.skipped) == (1, 0, 0)
    assert (report.answer_matched, report.answer_mismatched, report.answer_uncomparable) == (
        1,
        0,
        0,
    )
    assert cr.main([str(_write(tmp_path / "c.jsonl", [_OK]))]) == 0


def test_tamper_is_caught_even_when_tier1_is_unverifiable() -> None:
    """Tier1 이 판정 불가여도 두 필드가 확정적으로 갈라졌으면 레코드 결함이다(검산 성패와 무관)."""
    # 미정의 함수 `f` — Tier1 은 수치 평가 불가로 unverifiable 이다.
    opaque = {
        "slug": "opaque",
        "answer": "1",
        "verify": {"conditions": "f(x) = 0", "answer_map": {"x": "1"}},
    }
    state, reason = cr._reverify_one(opaque, use_fuzz=False)
    assert state == "skip"  # 대조군: 일치하면 종전대로 Tier1 판정 불가 skip
    assert reason is not None and reason.startswith("Tier1 unverifiable")
    state, reason = cr._reverify_one(_with_answer(opaque, "2"), use_fuzz=False)
    assert state == "fail"
    assert reason is not None and reason.startswith(cr.ANSWER_MISMATCH_REASON)


# ── 2. 표기만 다르고 값이 같으면 통과(거짓 실패 금지) ─────────────────────
@pytest.mark.parametrize(
    "answer", ["1/2", "0.5", "0.50", "\\frac{1}{2}", " 1 / 2 ", "1/2 ", "2/4", "x = 1/2"]
)
def test_same_value_in_other_notation_passes(answer: str) -> None:
    ledger: Counter[str] = Counter()
    state, reason = cr._reverify_one(
        _with_answer(_HALF, answer), use_fuzz=False, answer_ledger=ledger
    )
    assert (state, reason) == ("pass", None)
    assert ledger == Counter({cr.ANSWER_MATCHED: 1})


@pytest.mark.parametrize(
    ("amap_value", "answer"),
    [
        ("-3/2", "-\\frac{3}{2}"),
        ("-3/2", "-1.5"),
        ("2*sqrt(3)", "2\\sqrt{3}"),
        ("sqrt(3)/2", "√3/2"),
    ],
)
def test_radicals_and_signed_fractions_in_other_notation_pass(amap_value: str, answer: str) -> None:
    record = {
        "slug": "nota",
        "answer": answer,
        "verify": {"conditions": f"x - ({amap_value}) = 0", "answer_map": {"x": amap_value}},
    }
    assert cr._reverify_one(record, use_fuzz=False) == ("pass", None)


@pytest.mark.parametrize("answer", ["1/3", "0.49", "-1/2", "2"])
def test_near_but_different_value_still_fails(answer: str) -> None:
    """대조군(과잉 관대 방지) — 비슷해 보여도 다른 값은 fail 이다."""
    state, _ = cr._reverify_one(_with_answer(_HALF, answer), use_fuzz=False)
    assert state == "fail"


# ── 3. 대조 불가는 통과로 접지 않는다 — skip 으로 드러내고 건수를 따로 센다 ──
@pytest.mark.parametrize(
    ("answer", "detail"),
    [(None, "answer 없음"), ("", "answer 없음"), ("\\dfrac{1}{2}", "판정 불가")],
)
def test_uncomparable_answer_is_skip_not_pass(answer: str | None, detail: str) -> None:
    record = _with_answer(_HALF, answer)
    state, reason = cr._reverify_one(record, use_fuzz=False)
    assert state == "skip"
    assert reason is not None and reason.startswith(cr.ANSWER_UNCOMPARABLE_REASON)
    assert detail in reason
    report = cr.reverify_corpus([record], use_fuzz=False)
    assert (report.passed, report.failed, report.skipped) == (0, 0, 1)
    assert report.answer_uncomparable == 1
    assert report.answer_decided == 0


def test_empty_answer_map_is_uncomparable_not_mismatch() -> None:
    """검산 재료(answer_map)가 비어 있으면 '불일치(fail)'가 아니라 '대조 불가(skip)'다.

    빈 지도를 '모든 변수가 다르다'로 읽으면 재료가 없는 문항이 거짓 red가 된다(2026-10-21 리뷰 P2).
    """
    from whymath_backend.l3.verify_solution import answer_map_vars_matching

    assert answer_map_vars_matching({}, "2") is None
    record = {
        "slug": "empty",
        "answer": "2",
        "verify": {"conditions": "1 + 1 = 2", "answer_map": {}},
    }
    state, reason = cr._reverify_one(record, use_fuzz=False)
    assert state == "skip"
    assert reason is not None and reason.startswith(cr.ANSWER_UNCOMPARABLE_REASON)
    assert "answer_map 비어 있음" in reason


@pytest.mark.parametrize(
    "amap",
    [{"x": "2"}, {"x": "1", "y": "2"}],
)
def test_braced_answer_without_backslash_is_not_latex_normalised(amap: dict[str, str]) -> None:
    """백슬래시 없는 `{2}`(집합 표기)는 LaTeX 정규화를 거치지 않는다 — 괄호로 바뀌어 `2`와 같아지면 안 된다.

    정규화를 항상 걸면 `{2}` → `(2)` 가 되어 스칼라 2와 일치(통과)로 잘못 접힌다(2026-10-21 리뷰 R1 생존).
    """
    record = {
        "slug": "brace",
        "answer": "{2}",
        "verify": {"conditions": [f"{k} - ({v}) = 0" for k, v in amap.items()], "answer_map": amap},
    }
    state, _ = cr._reverify_one(record, use_fuzz=False)
    assert state != "pass"


def test_report_line_counts_uncomparable_and_working_ratio(tmp_path: Path) -> None:
    records = [
        _with_answer(_HALF, "0.5"),  # 일치
        _with_answer(_HALF, None),  # 대조 불가
        _with_answer(_HALF, "1/3"),  # 불일치
        _NO_VERIFY,  # 대조 대상 아님(재료 없음)
    ]
    code, out = _cli([_write(tmp_path / "mix.jsonl", records)])
    assert code == 1
    match = _SUMMARY.search(out)
    assert match is not None and match.groups() == ("4", "1", "1", "2")
    assert "answer 대조(OPS-150): 대상 3" in out
    assert "일치 1" in out and "불일치 1" in out and "대조 불가 1" in out
    assert "작동 2/3" in out


def test_report_line_says_when_comparison_never_ran(tmp_path: Path) -> None:
    """근 집계·개념형만 있는 코퍼스(야간 killer 은행 등)는 대조가 0건이다 — 0건임을 숨기지 않는다."""
    code, out = _cli([_write(tmp_path / "agg.jsonl", [_AGG_OK])])
    assert code == 0
    assert "대상 0건" in out


# ── 4. 다변수 — 소속 대조(약한 검사)로 따로 센다 ──────────────────────────
_TWO_VARS = {
    "slug": "two",
    "verify": {"conditions": ["x - 2 = 0", "y - 3 = 0"], "answer_map": {"x": "2", "y": "3"}},
}


def test_multivariable_membership_is_counted_separately() -> None:
    ledger: Counter[str] = Counter()
    assert cr._reverify_one(_with_answer(_TWO_VARS, "3"), use_fuzz=False, answer_ledger=ledger) == (
        "pass",
        None,
    )
    assert ledger == Counter({cr.ANSWER_MEMBERSHIP: 1})
    state, _ = cr._reverify_one(_with_answer(_TWO_VARS, "4"), use_fuzz=False)
    assert state == "fail"  # 어느 변수의 값도 아니면 불일치


# ── 5. P3-07 재현 — 대표 과정 승인 문항 40건의 answer 만 변조 → 40/40 fail · exit 1 ──
def _float(text: str) -> float | None:
    try:
        return float(sympy.sympify(text))
    except (sympy.SympifyError, TypeError, ValueError, SyntaxError):
        return None


def _wrong_value(answer: str, amap: dict[str, str]) -> str | None:
    """answer 에 1을 더한 값 — answer_map 의 어느 값과도 수치로 다를 때만(구성 자체를 검증한다)."""
    base = _float(answer)
    if base is None:
        return None
    wrong = str(sympy.nsimplify(sympy.sympify(answer)) + 1)
    targets = [_float(v) for v in amap.values()]
    if any(t is None or abs(t - (base + 1)) < 1e-9 for t in targets):
        return None
    return wrong


@pytest.fixture(scope="module")
def representative_tier1_40() -> list[dict[str, object]]:
    """대표 과정(P3-14 ④ 모집단) 승인 문항 중 Tier1 경로 40건 — 등간격 결정론 추출."""
    from whymath_backend.ops import phase3_metrics as pm

    world = pm.load_world()
    assert not isinstance(world, pm.WorldFailure), world
    pool = [
        dict(r)
        for r in world.qa_records
        if isinstance(r.get("verify"), dict)
        and not r["verify"].get("answer_kind")
        and r["verify"].get("answer_aggregate") not in ("sum", "product")
        and r["verify"].get("answer_map")
        and isinstance(r.get("answer"), str)
        and _wrong_value(
            str(r["answer"]), {k: str(v) for k, v in r["verify"]["answer_map"].items()}
        )
    ]
    assert len(pool) >= 40, f"Tier1 경로 후보 {len(pool)}건 — 40건을 뽑을 수 없다"
    step = len(pool) // 40
    picked = [pool[i * step] for i in range(40)]
    # 다변수 소속 문항도 섞여 있어야 P3-07 형태다(단일 변수만이면 약한 검사 경로를 안 밟는다).
    assert any(len(r["verify"]["answer_map"]) > 1 for r in picked)  # type: ignore[index]
    return picked


def test_p3_07_control_40_passes_with_all_answers_compared(
    representative_tier1_40: list[dict[str, object]], tmp_path: Path
) -> None:
    code, out = _cli([_write(tmp_path / "ctrl.jsonl", representative_tier1_40)])
    match = _SUMMARY.search(out)
    assert match is not None
    assert code == 0, out
    assert match.groups() == ("40", "40", "0", "0")
    report = cr.reverify_corpus(representative_tier1_40, use_fuzz=False)
    assert report.answer_decided == 40 and report.answer_uncomparable == 0


def test_p3_07_answer_only_tamper_40_of_40_fail_exit_1(
    representative_tier1_40: list[dict[str, object]], tmp_path: Path
) -> None:
    tampered: list[dict[str, object]] = []
    for record in representative_tier1_40:
        out = json.loads(json.dumps(record))
        amap = {k: str(v) for k, v in out["verify"]["answer_map"].items()}
        wrong = _wrong_value(str(out["answer"]), amap)
        assert wrong is not None
        out["answer"] = wrong
        assert out["verify"] == record["verify"]  # answer 필드만 바뀌었다(주입 실재 단언)
        assert out["answer"] != record["answer"]
        tampered.append(out)
    report = cr.reverify_corpus(tampered, use_fuzz=False)
    assert (report.passed, report.failed, report.skipped) == (0, 40, 0)
    assert report.answer_mismatched == 40
    assert all(reason.startswith(cr.ANSWER_MISMATCH_REASON) for _, reason in report.failures)
    code, _ = _cli([_write(tmp_path / "tampered.jsonl", tampered)])
    assert code == 1


# ── 6. 공용 판정 거버넌스 — 두 게이트가 한 함수를 쓴다(사본 금지) ─────────
_PKG = Path(cr.__file__).resolve().parents[1]
_SHARED = "answer_map_vars_matching"


def _called(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                names.add(node.func.attr)
    return names


def _functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}


def _imports_shared(tree: ast.Module) -> set[str]:
    """`l3.verify_solution` 에서 공용 함수를 가져온 지역 이름(별칭 포함)."""
    local: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "whymath_backend.l3.verify_solution":
            local |= {a.asname or a.name for a in node.names if a.name == _SHARED}
    return local


def test_nightly_reverify_compares_answer_through_the_shared_function() -> None:
    tree = ast.parse((_PKG / "harness/corpus_reverify.py").read_text(encoding="utf-8"))
    funcs = _functions(tree)
    assert _imports_shared(tree) == {_SHARED}
    assert _SHARED in _called(funcs["_compare_answer_field"])
    assert "_compare_answer_field" in _called(funcs["_reverify_one"])
    assert _SHARED not in funcs  # 사본 정의 없음


def test_solution_qa_c1_uses_the_same_shared_function() -> None:
    tree = ast.parse((_PKG / "harness/solution_qa.py").read_text(encoding="utf-8"))
    funcs = _functions(tree)
    local = _imports_shared(tree)
    assert local, "solution_qa 가 공용 대조 함수를 import 하지 않는다"
    assert local & _called(funcs["_check_c1"])
    assert not ({"_answer_vars", _SHARED} & set(funcs))  # 옛 사본이 되살아나지 않았다


def test_shared_function_is_exported_once_from_l3() -> None:
    from whymath_backend.l3 import verify_solution as vs

    assert _SHARED in vs.__all__
    fn: Callable[..., object] = getattr(vs, _SHARED)
    assert fn({"x": "1/2"}, "0.5") == frozenset({"x"})
    assert fn({"x": "1/2"}, "1/3") == frozenset()
    assert fn({"x": "1/2"}, "\\dfrac{1}{2}") is None  # 모르면 None — 빈 집합(불일치)으로 위장 금지
