"""[OPS-83] backend 집계 판정기(`scripts/coverage/backend_shard_verdict.py`)와 샤드 배정의 단위 검증.

무엇을 보는가
-------------
① **needs 판정** — `toJSON(needs)`의 결과 조합별 exit code. success만 통과이고 failure·cancelled·
   skipped는 전부 exit 1이다. 비었거나 형식이 아니면 exit 2(측정 실패 — 위반 0으로 접지 않는다).
② **분할 완전성** — 플러그인(`backend_shard_plugin.py`)이 실제로 만드는 보고서로 판정기를 돌려
   정상 분할은 통과, 겹침·누락·N 불일치·우주 불일치·빈 샤드는 각각 위반으로 잡힌다.
③ **배정 규칙** — 결정론(입력 순서와 무관)·완전 분할·부하 균형·인자 검증.

플러그인은 `pytest`만 import하므로 tests/infra(infra-contracts 잡 — whymath_backend 미설치)에서
돈다. xdist·커버리지 합산까지 거치는 종단 검증은 `tests/backend/test_backend_shard_plugin_e2e.py`가
맡는다(그 잡에만 xdist·pytest-cov가 있다).
"""

from __future__ import annotations

import importlib.util
import json
import random
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COVERAGE_DIR = _REPO_ROOT / "scripts" / "coverage"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"{name}_under_test", _COVERAGE_DIR / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


verdict = _load("backend_shard_verdict")
plugin = _load("backend_shard_plugin")


# ── ① needs 판정 ──────────────────────────────────────────────────────────


def _needs(**results: str) -> dict[str, Any]:
    return {job: {"result": r, "outputs": {}} for job, r in results.items()}


_ALL_SUCCESS = dict(
    changes="success",
    backend="success",
    **{"backend-pytest-1": "success", "backend-pytest-2": "success", "backend-pytest-3": "success"},
)


def _run_needs(monkeypatch: pytest.MonkeyPatch, payload: Any) -> int:
    monkeypatch.setenv("NEEDS_JSON", payload if isinstance(payload, str) else json.dumps(payload))
    return int(verdict.main(["needs"]))


def test_needs_all_success_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _run_needs(monkeypatch, _needs(**_ALL_SUCCESS)) == 0


@pytest.mark.parametrize("bad", ["failure", "cancelled", "skipped", None, "neutral"])
@pytest.mark.parametrize("job", ["backend", "backend-pytest-2", "changes"])
def test_needs_any_non_success_fails(
    monkeypatch: pytest.MonkeyPatch, job: str, bad: str | None
) -> None:
    """한 잡이라도 success가 아니면 exit 1 — skipped도 통과가 아니다(검증이 일어나지 않았다)."""
    results: dict[str, Any] = dict(_ALL_SUCCESS)
    results[job] = bad
    assert _run_needs(monkeypatch, _needs(**results)) == 1


def test_needs_all_skipped_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """전부 skipped(= 아무것도 안 돌았다)는 통과가 아니다 — 이 잡이 가장 막아야 하는 형태."""
    assert _run_needs(monkeypatch, _needs(**{k: "skipped" for k in _ALL_SUCCESS})) == 1


@pytest.mark.parametrize("payload", ["{}", "[]", "not json", '"x"', json.dumps({"a": "success"})])
def test_needs_unreadable_is_measurement_failure(
    monkeypatch: pytest.MonkeyPatch, payload: str
) -> None:
    """비었거나 형식이 아니면 exit 2. 문자열 값(`{"a": "success"}`)은 result 키가 없으므로 위반(1)."""
    rc = _run_needs(monkeypatch, payload)
    if payload == json.dumps({"a": "success"}):
        assert rc == 1
    else:
        assert rc == 2


def test_needs_missing_env_is_measurement_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEEDS_JSON", raising=False)
    assert verdict.main(["needs"]) == 2


# ── ② 분할 완전성 — 플러그인이 만드는 보고서로 판정 ─────────────────────────


def _universe(n_files: int = 40, seed: int = 7) -> dict[str, int]:
    rng = random.Random(seed)
    return {f"tests/backend/x/test_{i:03d}.py": rng.randint(1, 60) for i in range(n_files)}


def _reports(counts: dict[str, int], n: int) -> list[dict[str, Any]]:
    assignment = plugin.assign_files(counts, n)
    return [plugin.build_report(k, n, counts, assignment) for k in range(1, n + 1)]


def _write(tmp_path: Path, reports: list[dict[str, Any]]) -> Path:
    out = tmp_path / "pytest-shard"
    out.mkdir()
    for r in reports:
        (out / f"report-{r['shard']}.json").write_text(json.dumps(r), encoding="utf-8")
    return out


@pytest.mark.parametrize("n", [1, 2, 3, 5])
def test_plugin_reports_form_a_complete_partition(tmp_path: Path, n: int) -> None:
    reports = _reports(_universe(), n)
    assert verdict.partition_violations(reports) == []
    assert verdict.main(["reports", str(_write(tmp_path, reports))]) == 0


def test_plugin_digest_matches_verdict_digest() -> None:
    """두 파일이 지문 정의를 각자 갖고 있다 — 어긋나면 정상 분할이 '우주 불일치'로 red가 된다."""
    paths = list(_universe())
    assert plugin.files_digest(paths) == verdict._digest(paths)
    assert plugin.REPORT_SCHEMA == verdict.EXPECTED_REPORT_SCHEMA


def _mutate_missing_shard(reports: list[dict[str, Any]]) -> None:
    reports.pop()


def _mutate_duplicate_file(reports: list[dict[str, Any]]) -> None:
    reports[1]["selected_files"].append(reports[0]["selected_files"][0])


def _mutate_unassigned_file(reports: list[dict[str, Any]]) -> None:
    dropped = reports[0]["selected_files"].pop()
    reports[0]["selected_items"] -= 1
    assert dropped


def _mutate_n_mismatch(reports: list[dict[str, Any]]) -> None:
    reports[2]["total_shards"] = 4


def _mutate_duplicate_shard_number(reports: list[dict[str, Any]]) -> None:
    reports[2]["shard"] = 2


def _mutate_universe_drift(reports: list[dict[str, Any]]) -> None:
    reports[1]["total_items"] -= 5


def _mutate_digest_drift(reports: list[dict[str, Any]]) -> None:
    reports[0]["files_digest"] = "0" * 64


def _mutate_item_sum(reports: list[dict[str, Any]]) -> None:
    reports[0]["selected_items"] += 1


def _mutate_empty_shard(reports: list[dict[str, Any]]) -> None:
    moved = reports[2]["selected_files"]
    reports[1]["selected_files"] += moved
    reports[1]["selected_items"] += reports[2]["selected_items"]
    reports[2]["selected_files"] = []
    reports[2]["selected_items"] = 0


@pytest.mark.parametrize(
    ("mutate", "needle"),
    [
        (_mutate_missing_shard, "보고서가 없는 샤드"),
        (_mutate_duplicate_file, "두 샤드에 배정"),
        (_mutate_unassigned_file, "어느 샤드에도 배정되지 않은"),
        (_mutate_n_mismatch, "N이 다르다"),
        (_mutate_duplicate_shard_number, "두 번 이상"),
        (_mutate_universe_drift, "수집 우주가 다르다"),
        (_mutate_digest_drift, "수집 우주가 다르다"),
        (_mutate_item_sum, "항목 합"),
        (_mutate_empty_shard, "배정 0건"),
    ],
)
def test_broken_partition_is_detected(tmp_path: Path, mutate: Any, needle: str) -> None:
    reports = _reports(_universe(), 3)
    before = json.dumps(reports, sort_keys=True)
    mutate(reports)
    assert json.dumps(reports, sort_keys=True) != before, "주입이 적용되지 않았다"
    violations = verdict.partition_violations(reports)
    assert any(needle in x for x in violations), violations
    assert verdict.main(["reports", str(_write(tmp_path, reports))]) == 1


def test_reports_zero_files_or_bad_schema_is_measurement_failure(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert verdict.main(["reports", str(empty)]) == 2
    assert verdict.main(["reports", str(tmp_path / "없음")]) == 2
    reports = _reports(_universe(), 2)
    reports[0]["schema"] = 99
    assert verdict.main(["reports", str(_write(tmp_path, reports))]) == 2


# ── ③ 배정 규칙 ────────────────────────────────────────────────────────────


def test_assignment_is_deterministic_regardless_of_input_order() -> None:
    counts = _universe(200, seed=3)
    shuffled = dict(sorted(counts.items(), key=lambda kv: random.Random(1).random()))
    assert plugin.assign_files(counts, 3) == plugin.assign_files(shuffled, 3)


def test_assignment_is_a_partition_and_spreads_files() -> None:
    """모든 파일이 정확히 한 샤드에 가고, 파일 수가 크게 치우치지 않는다(해시의 분산 확인)."""
    paths = [f"tests/backend/d{i % 17}/test_{i:04d}.py" for i in range(3000)]
    assignment = plugin.assign_files(paths, 3)
    assert set(assignment) == set(paths) and set(assignment.values()) == {1, 2, 3}
    sizes = [sum(1 for s in assignment.values() if s == k) for k in (1, 2, 3)]
    assert min(sizes) >= 900 and max(sizes) <= 1100, sizes  # 기대 1000 ± 10%


def test_assignment_of_a_file_does_not_depend_on_other_files() -> None:
    """파일의 샤드는 그 경로만의 함수다 — 다른 파일이 추가·누락돼도 움직이지 않는다.

    LPT·라운드로빈은 수집 우주 전체에 의존해서, 샤드·워커마다 수집이 조금만 달라도 배정이 어긋난다.
    해시 규칙은 그 결합을 없앤다(판정기는 여전히 어긋남을 잡지만 애초에 생기지 않게 한다).
    """
    base = [f"tests/backend/x/test_{i:03d}.py" for i in range(200)]
    full = plugin.assign_files(base, 3)
    more = plugin.assign_files([*base, "tests/backend/new/test_added.py"], 3)
    fewer = plugin.assign_files(base[::2], 3)
    assert all(more[p] == full[p] for p in base)
    assert all(fewer[p] == full[p] for p in base[::2])
    assert plugin.shard_of("tests/backend/x/test_000.py", 3) == full["tests/backend/x/test_000.py"]
    with pytest.raises(ValueError):
        plugin.shard_of("a.py", 0)


def test_assignment_with_fewer_files_than_shards_leaves_an_empty_shard() -> None:
    """빈 샤드는 판정기가 '배정 0건'으로 잡는다(조용히 통과하지 않는다)."""
    counts = {"a.py": 3, "b.py": 1}
    reports = [plugin.build_report(k, 3, counts, plugin.assign_files(counts, 3)) for k in (1, 2, 3)]
    assert any("배정 0건" in x for x in verdict.partition_violations(reports))


@pytest.mark.parametrize("spec", ["", "3", "0/3", "4/3", "1/0", "a/b", "-1/3", "1/3/4"])
def test_parse_shard_rejects_malformed(spec: str) -> None:
    with pytest.raises(ValueError):
        plugin.parse_shard(spec)


def test_parse_shard_accepts_valid() -> None:
    assert plugin.parse_shard("1/3") == (1, 3)
    assert plugin.parse_shard(" 3/3 ") == (3, 3)
    assert plugin.parse_shard("1/1") == (1, 1)


def test_file_of_strips_test_path() -> None:
    assert plugin.file_of("tests/backend/a/test_x.py::TestC::test_y[1-2]") == (
        "tests/backend/a/test_x.py"
    )
