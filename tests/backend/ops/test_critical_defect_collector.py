"""P3-107 — 지표 ⑥ Critical Defect 입력 수집기(`ops.critical_defect_collector`) 시험.

주입 4종(태스크 지시): F-Ⅱ 위반 → ⑥ FAIL · F-Ⅴ 위반 → ⑥ FAIL · 입력 부재 → unmeasured ·
정상 → PASS(대조군). 대조군 세계는 두 회차로 만든다:

  · 실 회차 `eos197-a6`(커밋된 바이트를 tmp 로 **복사**) — F-Ⅴ 의미 축 표본 n=30 k=0 을 준다.
    F-Ⅱ 는 검수 통과 28건 전부 C2_NO_STEPS(검증 불가)라 판정 0건이다(실측과 같다).
  · 합성 회차 `syn` — 검수 통과 CU 150건(Solution QA 가 결정하는 형태). 0/150 의 Wilson 단측
    95% 상한은 1.8% 로 F-Ⅱ 문턱(2%) 아래다 — 대조군이 PASS 가 되려면 표본이 이만큼 필요하다.

주입은 tmp 사본에만 하고, 적용 자체(바이트가 바뀌었다)와 커밋 원본 무변경(sha256 동일)을 단언한다.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.ops import critical_defect_collector as cdc
from whymath_backend.ops import phase3_metrics as pm
from whymath_backend.schema.review_timer import review_content_fingerprint

_REPO = Path(__file__).resolve().parents[3]
_RUNS = _REPO / "data" / "runs"
_REAL_ROUND = "eos197-a6"
_REAL_DIRS = (f"{_REAL_ROUND}-local", f"{_REAL_ROUND}-openrouter", f"{_REAL_ROUND}-review")
_SYN_N = 150


# ──────────────────────────────────────────────────────────────────────────
# 픽스처 — 커밋 원본은 읽기만, 주입은 tmp 사본에
# ──────────────────────────────────────────────────────────────────────────
def _tree_digest(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def _syn_record(n: int, *, wrong: bool = False) -> dict[str, Any]:
    """Solution QA 가 결정하는 최소 CU — `wrong` 이면 정답이 조건과 모순(C1·C2 FAIL)."""
    answer = "3" if wrong else "2"
    return {
        "problem_id": f"00000000-0000-0000-0000-{n:012d}",
        "slug": f"syn-cu-{n}",
        "answer": answer,
        "verify": {
            "conditions": f"x + {n} = {n + 2}",
            "answer_map": {"x": answer},
            "solution_steps": [f"x + {n} = {n + 2}", f"x = {answer}"],
        },
    }


def _write_syn_round(root: Path, *, wrong: int = 0) -> None:
    seat = root / "syn-seat"
    review = root / "syn-review"
    seat.mkdir(parents=True)
    review.mkdir(parents=True)
    records = [_syn_record(n, wrong=n < wrong) for n in range(_SYN_N)]
    (seat / "cu.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8"
    )
    (seat / "cu.genlog.jsonl").write_text("", encoding="utf-8")
    verdicts = [
        {
            "slug": r["slug"],
            "review_status": "approved",
            "verdict": "approved",
            "reviewer_id": "syn",
            "failure_code": None,
            "content_fingerprint": review_content_fingerprint(r),
        }
        for r in records
    ]
    (review / "canary_review_verdicts.jsonl").write_text(
        "".join(json.dumps(v, ensure_ascii=False) + "\n" for v in verdicts), encoding="utf-8"
    )


@pytest.fixture(scope="module")
def committed_digest() -> dict[str, str]:
    for name in _REAL_DIRS:
        assert (_RUNS / name).is_dir(), f"커밋된 회차 폴더 {name} 이(가) 없다 — 픽스처 전제 붕괴"
    return {name: json.dumps(_tree_digest(_RUNS / name), sort_keys=True) for name in _REAL_DIRS}


@pytest.fixture
def world(tmp_path: Path, committed_digest: dict[str, str]) -> Path:
    """대조군 세계(실 회차 사본 + 합성 회차). 테스트가 끝나면 커밋 원본 무변경을 단언한다."""
    root = tmp_path / "runs"
    root.mkdir()
    for name in _REAL_DIRS:
        shutil.copytree(_RUNS / name, root / name)
    _write_syn_round(root)
    yield root
    for name in _REAL_DIRS:
        assert json.dumps(_tree_digest(_RUNS / name), sort_keys=True) == committed_digest[name]


def _defect(result: cdc.CollectorResult) -> pm.MetricOutcome:
    payload = None if result.runtime_error else result.payload()
    return pm._critical_defect(payload, injected=False, source_facts=result.summary_facts())


def _mutate(path: Path, edit: Callable[[str], str]) -> None:
    before = path.read_bytes()
    path.write_text(edit(before.decode("utf-8")), encoding="utf-8")
    assert path.read_bytes() != before, f"주입이 적용되지 않았다: {path.name}"


# ──────────────────────────────────────────────────────────────────────────
# 주입 4종
# ──────────────────────────────────────────────────────────────────────────
def test_control_world_passes(world: Path) -> None:
    """대조군 — 두 게이트 다 measured · 미해당 → ⑥ 충족(0건)."""
    result = cdc.collect(world)
    assert result.exit_code == cdc.EXIT_COMPLETE
    assert (result.f2.hits, result.f2.trials) == (0, _SYN_N)
    assert (result.f5.hits, result.f5.trials) == (0, 30)
    outcome = _defect(result)
    assert outcome.state is pm.MetricState.MEASURED
    assert outcome.met is True and outcome.value == 0.0 and outcome.target == 0.0


def test_f2_violation_fails(tmp_path: Path, world: Path) -> None:
    """F-Ⅱ 위반 — 검수 통과 CU 10/150 이 SymPy 재검증 FAIL → ⑥ 미달."""
    shutil.rmtree(world / "syn-seat")
    shutil.rmtree(world / "syn-review")
    _write_syn_round(world, wrong=10)
    result = cdc.collect(world)
    assert (result.f2.hits, result.f2.trials) == (10, _SYN_N)
    outcome = _defect(result)
    assert outcome.state is pm.MetricState.MEASURED
    assert outcome.met is False
    assert any(u.startswith("F-Ⅱ") for u in outcome.unmet)


def test_f5_violation_fails(world: Path) -> None:
    """F-Ⅴ 위반 — 의미 축 표본 30건 중 5건을 '누설'로 바꾼다 → ⑥ 미달."""
    path = world / f"{_REAL_ROUND}-review" / "hint_verdicts.jsonl"
    flipped = 0

    def edit(text: str) -> str:
        nonlocal flipped
        out = []
        for line in text.splitlines():
            row = json.loads(line)
            if row["purpose"] == "semantic_sample" and flipped < 5:
                row["verdict"] = "leaked"
                flipped += 1
            out.append(json.dumps(row, ensure_ascii=False))
        return "\n".join(out) + "\n"

    _mutate(path, edit)
    assert flipped == 5
    result = cdc.collect(world)
    assert (result.f5.hits, result.f5.trials) == (5, 30)
    outcome = _defect(result)
    assert outcome.state is pm.MetricState.MEASURED
    assert outcome.met is False
    assert any(u.startswith("F-Ⅴ") for u in outcome.unmet)


def test_absent_input_is_unmeasured(tmp_path: Path) -> None:
    """입력 부재 — 회차 0개면 두 게이트 다 unmeasured · exit 2 · ⑥ 측정 실패(0건 통과 위장 금지)."""
    empty = tmp_path / "empty-runs"
    empty.mkdir()
    result = cdc.collect(empty)
    assert result.exit_code == cdc.EXIT_UNMEASURED
    assert not result.f2.measured and "원천 0건" in result.f2.reason
    assert not result.f5.measured and "원천 0건" in result.f5.reason
    assert result.payload() == {"content": {}}
    outcome = _defect(result)
    assert outcome.state is pm.MetricState.UNMEASURED
    assert outcome.met is None


# ──────────────────────────────────────────────────────────────────────────
# 실측 재현 · 결정론 · 오류 전파
# ──────────────────────────────────────────────────────────────────────────
def test_real_round_alone_matches_main_measurement(tmp_path: Path) -> None:
    """커밋된 회차만 — F-Ⅱ 판정 0건(28건 전부 C2_NO_STEPS)이라 ⑥ 은 측정 실패, F-Ⅴ 는 0/30."""
    root = tmp_path / "runs"
    root.mkdir()
    for name in _REAL_DIRS:
        shutil.copytree(_RUNS / name, root / name)
    result = cdc.collect(root)
    assert result.exit_code == cdc.EXIT_UNMEASURED
    (survey,) = result.rounds
    assert survey.f2_passed == 28 and survey.f2_stale == 0
    assert (survey.f2_pass, survey.f2_fail, survey.f2_unverifiable) == (0, 0, 28)
    assert survey.f2_unverifiable_reasons == {"C2:C2_NO_STEPS": 28}
    assert survey.cu_review_f8_labels == 2
    assert not result.f2.measured and "판정 0건" in result.f2.reason
    assert (result.f5.state, result.f5.hits, result.f5.trials) == (cdc.STATE_MEASURED, 0, 30)
    assert result.payload() == {"content": {"hint_leak_hits": 0, "hint_leak_sample": 30}}
    outcome = _defect(result)
    assert outcome.state is pm.MetricState.UNMEASURED
    assert "F-Ⅱ" in outcome.reason


def test_same_input_same_bytes_regardless_of_location(tmp_path: Path, world: Path) -> None:
    first = cdc.collect(world).dumps()
    assert cdc.collect(world).dumps() == first
    moved = tmp_path / "elsewhere" / "runs"
    shutil.copytree(world, moved)
    assert cdc.collect(moved).dumps() == first  # 절대 경로·시각이 출력에 없다
    assert str(tmp_path) not in first


def test_stale_fingerprint_is_not_counted(world: Path) -> None:
    """검수 뒤 내용이 바뀐 CU 는 '검수 통과'로 세지 않는다."""
    path = world / "syn-seat" / "cu.jsonl"
    _mutate(
        path, lambda t: t.replace('"slug": "syn-cu-0"', '"slug": "syn-cu-0", "note": "edit"', 1)
    )
    result = cdc.collect(world)
    syn = next(r for r in result.rounds if r.round_id == "syn")
    assert syn.f2_stale == 1
    assert result.f2.trials == _SYN_N - 1


def test_corrupt_round_makes_gate_unmeasured_not_dropped(world: Path) -> None:
    """망가진 회차를 빼고 판정하지 않는다 — 한 줄 파싱 실패면 F-Ⅱ 전체가 unmeasured."""
    path = world / "syn-seat" / "cu.jsonl"
    _mutate(path, lambda t: t + "{not json\n")
    result = cdc.collect(world)
    assert not result.f2.measured and "입력 오류" in result.f2.reason
    assert "reviewed_cu_total" not in result.payload()["content"]
    assert _defect(result).state is pm.MetricState.UNMEASURED


def test_missing_manifest_makes_f5_unmeasured(world: Path) -> None:
    manifest = world / f"{_REAL_ROUND}-review" / "hint_sample_manifest.json"
    manifest.unlink()
    result = cdc.collect(world)
    assert not result.f5.measured and "원천 0건" in result.f5.reason
    assert result.f2.measured  # 다른 게이트는 영향 없음
    assert _defect(result).state is pm.MetricState.UNMEASURED


def test_semantic_not_measurable_is_error_not_dropped(world: Path) -> None:
    """표본은 냈는데 판정이 모자라면(n<30) 그 회차를 빼지 않고 F-Ⅴ 전체를 unmeasured 로 둔다."""
    path = world / f"{_REAL_ROUND}-review" / "hint_verdicts.jsonl"
    dropped = 0

    def edit(text: str) -> str:
        nonlocal dropped
        out = []
        for line in text.splitlines():
            if dropped == 0 and json.loads(line)["purpose"] == "semantic_sample":
                dropped += 1
                continue
            out.append(line)
        return "\n".join(out) + "\n"

    _mutate(path, edit)
    result = cdc.collect(world)
    real = next(r for r in result.rounds if r.round_id == _REAL_ROUND)
    assert real.f5_semantic_status == "NOT_MEASURABLE"
    assert not result.f5.measured and "입력 오류" in result.f5.reason
    assert "hint_leak_sample" not in result.payload()["content"]


def test_runs_root_not_a_directory_is_runtime_error(tmp_path: Path) -> None:
    result = cdc.collect(tmp_path / "nope")
    assert result.exit_code == cdc.EXIT_RUNTIME_ERROR
    assert _defect(result).state is pm.MetricState.UNMEASURED


# ──────────────────────────────────────────────────────────────────────────
# CLI · phase3_metrics 배선
# ──────────────────────────────────────────────────────────────────────────
def test_cli_writes_deterministic_json(tmp_path: Path, world: Path) -> None:
    out1, out2 = tmp_path / "a.json", tmp_path / "b.json"
    assert cdc.main(["--runs-root", str(world), "--json", str(out1)]) == cdc.EXIT_COMPLETE
    assert cdc.main(["--runs-root", str(world), "--json", str(out2)]) == cdc.EXIT_COMPLETE
    assert out1.read_bytes() == out2.read_bytes()
    data = json.loads(out1.read_text(encoding="utf-8"))
    assert data["payload"]["content"]["reviewed_cu_total"] == _SYN_N


def test_cli_absent_input_exit_nonzero(tmp_path: Path) -> None:
    empty = tmp_path / "e"
    empty.mkdir()
    assert cdc.main(["--runs-root", str(empty)]) == cdc.EXIT_UNMEASURED


def test_phase3_metrics_rejects_collect_with_injection(tmp_path: Path) -> None:
    payload = tmp_path / "p.json"
    payload.write_text("{}", encoding="utf-8")
    argv = [
        "--no-db",
        "--sample-basis",
        "synthetic",
        "--critical-defect-from-runs",
        "--hard-gate-input",
        str(payload),
    ]
    assert pm.main(argv) == pm.EXIT_RUNTIME_ERROR


def test_phase3_metrics_rejects_runs_root_without_flag(tmp_path: Path) -> None:
    assert pm.main(["--no-db", "--runs-root", str(tmp_path)]) == pm.EXIT_RUNTIME_ERROR


def test_phase3_metrics_self_check_rejects_collector_flag() -> None:
    assert pm.main(["--self-check", "--critical-defect-from-runs"]) == pm.EXIT_RUNTIME_ERROR


def test_evaluate_all_measures_defect_from_collected_payload(world: Path) -> None:
    """배선 — 수집 payload 는 주입이 아니라 측정(basis)으로 ⑥ 에 들어가고 사실 줄이 붙는다."""
    result = cdc.collect(world)
    outcome = pm._critical_defect(
        result.payload(), injected=False, source_facts=result.summary_facts()
    )
    assert outcome.basis == pm.BASIS_MEASURED
    labels = [label for label, _ in outcome.facts]
    assert labels[:2] == ["F-Ⅱ", "F-Ⅴ"] and "수집기" in labels
