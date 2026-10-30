"""[OPS-83] 잡 단위 샤딩의 종단 검증 — xdist 아래 배정·보고서·커버리지 합산이 실제로 성립하는가.

왜 tests/backend인가: 이 검증은 CI 샤드 잡과 같은 조합(pytest-xdist `-n` + pytest-cov `--cov`)을
실제 서브프로세스로 돌려야 의미가 있다. 그 플러그인들이 설치된 잡은 backend 쪽뿐이다
(tests/infra를 도는 infra-contracts 잡에는 없다). `test_layer_coverage_gate.py`가 같은 이유로
`scripts/coverage/check_layer_coverage.py`를 여기서 검증하는 선례다.

무엇을 봉인하는가 (합성 소형 패키지 — 실 스위트 전체 대조는 OPS-83 ③의 1회성 로컬 실측이 했다)
① xdist 워커 아래에서도 배정 보고서가 정확히 하나 쓰이고(gw0), 샤드 3개의 보고서가 판정기에서
   완전한 분할로 통과한다.
② 샤드별 통과 테스트 수의 합 = 비샤드 실행의 통과 수(일부만 돈 샤드가 없다).
③ 샤드 3개의 `.coverage`를 `coverage combine`한 총계(구문·실행 줄·분기·실행 분기)가 비샤드
   실행과 **완전히 같다** — 계층별 커버리지 게이트가 이 합산 결과를 읽으므로 한 자리라도 다르면
   게이트가 통과하면서 틀린 판정을 낸다(OPS-58 ② 기준).
④ `--shard` 없이 부르면 플러그인이 아무것도 하지 않는다(로컬·야간 직렬 실행 무영향).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COVERAGE_DIR = _REPO_ROOT / "scripts" / "coverage"
_VERDICT = _COVERAGE_DIR / "backend_shard_verdict.py"

_PKG = """
def classify(x):
    if x < 0:
        return "neg"
    elif x == 0:
        return "zero"
    return "pos"


def parity(n):
    return "even" if n % 2 == 0 else "odd"


def clamp(x, lo, hi):
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def never_called(y):
    if y:
        return 1
    return 2
"""

# 파일 6개 — 서로 다른 함수·분기를 밟는다. 일부 분기는 한 파일만 밟아, 그 파일이 어느 샤드로
# 가든 합산에서 정확히 한 번 잡혀야 한다.
_TESTS: dict[str, str] = {
    "test_neg.py": "from pkg.mod import classify\n\ndef test_neg():\n    assert classify(-1) == 'neg'\n",
    "test_zero.py": (
        "from pkg.mod import classify\n\ndef test_zero():\n    assert classify(0) == 'zero'\n\n"
        "def test_zero_again():\n    assert classify(0) == 'zero'\n"
    ),
    "test_pos.py": "from pkg.mod import classify\n\ndef test_pos():\n    assert classify(3) == 'pos'\n",
    "test_parity.py": (
        "import pytest\nfrom pkg.mod import parity\n\n"
        "@pytest.mark.parametrize('n', [1, 2, 3, 4, 5])\ndef test_parity(n):\n"
        "    assert parity(n) in ('even', 'odd')\n"
    ),
    "test_clamp_lo.py": "from pkg.mod import clamp\n\ndef test_lo():\n    assert clamp(-5, 0, 9) == 0\n",
    "test_clamp_mid.py": (
        "from pkg.mod import clamp\n\ndef test_mid():\n    assert clamp(4, 0, 9) == 4\n\n"
        "def test_hi():\n    assert clamp(99, 0, 9) == 9\n"
    ),
}
_TOTAL_TESTS = 12


def _clean_env() -> dict[str, str]:
    """바깥 pytest·coverage·xdist의 흔적을 지운 환경 — 서브프로세스가 이 실행에 결합되지 않게."""
    drop = ("COV_CORE", "COVERAGE_", "PYTEST_", "PYTHONPATH")
    env = {k: v for k, v in os.environ.items() if not k.startswith(drop)}
    return env


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "mod.py").write_text(_PKG, encoding="utf-8")
    (root / "tests").mkdir()
    for name, body in _TESTS.items():
        (root / "tests" / name).write_text(body, encoding="utf-8")
    (root / "pytest.ini").write_text(
        "[pytest]\ntestpaths = tests\npythonpath = .\naddopts = -p no:cacheprovider\n",
        encoding="utf-8",
    )
    (root / ".coveragerc").write_text("[run]\nbranch = True\nsource = pkg\n", encoding="utf-8")
    return root


def _run(cwd: Path, args: list[str], *, plugin: bool = False) -> subprocess.CompletedProcess[str]:
    env = _clean_env()
    if plugin:
        env["PYTHONPATH"] = str(_COVERAGE_DIR)
    return subprocess.run(
        [sys.executable, *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=180
    )


def _pytest(cwd: Path, extra: list[str], *, plugin: bool = False) -> int:
    proc = _run(
        cwd,
        [
            "-m",
            "pytest",
            "-n",
            "2",
            "--dist",
            "loadfile",
            "--cov=pkg",
            "--cov-report=",
            "-q",
            *extra,
        ],
        plugin=plugin,
    )
    assert proc.returncode == 0, f"pytest 실패 rc={proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    return _passed(proc.stdout)


def _passed(stdout: str) -> int:
    for line in reversed(stdout.splitlines()):
        if " passed" in line:
            return int(line.strip().strip("=").split(" passed")[0].split()[-1])
    raise AssertionError(f"통과 수를 읽지 못했다:\n{stdout}")


def _totals(cwd: Path, data_file: Path) -> dict[str, Any]:
    out = cwd / "cov.json"
    proc = _run(cwd, ["-m", "coverage", "json", "--data-file", str(data_file), "-o", str(out)])
    assert proc.returncode == 0, proc.stderr
    totals = json.loads(out.read_text(encoding="utf-8"))["totals"]
    return {
        k: totals[k]
        for k in (
            "num_statements",
            "covered_lines",
            "missing_lines",
            "num_branches",
            "covered_branches",
        )
    }


def test_shards_partition_and_combined_coverage_equal_unsharded(tree: Path) -> None:
    # 기준: 샤딩 없이 같은 xdist·커버리지 조합으로 한 번.
    base_passed = _pytest(tree, [])
    assert base_passed == _TOTAL_TESTS
    base = _totals(tree, tree / ".coverage")

    out = tree / "pytest-shard"
    out.mkdir()
    shard_passed = 0
    for k in (1, 2, 3):
        shard_passed += _pytest(
            tree,
            [
                "-p",
                "backend_shard_plugin",
                "--shard",
                f"{k}/3",
                "--shard-report",
                f"pytest-shard/report-{k}.json",
            ],
            plugin=True,
        )
        shutil.move(str(tree / ".coverage"), str(out / f"coverage-{k}.data"))
        # ① xdist 아래에서도 보고서는 정확히 하나(임시 파일 잔여 없음).
        assert sorted(p.name for p in out.glob(f"report-{k}.json*")) == [f"report-{k}.json"]

    # ② 샤드 통과 합 = 비샤드 통과 수.
    assert shard_passed == base_passed

    # ① 판정기가 완전 분할로 통과시킨다.
    proc = _run(tree, [str(_VERDICT), "reports", str(out)])
    assert proc.returncode == 0, proc.stdout + proc.stderr

    # ③ 합산 총계 = 비샤드 총계(한 자리도 다르면 안 된다).
    combined = tree / "combined.data"
    proc = _run(
        tree,
        [
            "-m",
            "coverage",
            "combine",
            "--keep",
            "--data-file",
            str(combined),
            *(str(out / f"coverage-{k}.data") for k in (1, 2, 3)),
        ],
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _totals(tree, combined) == base
    # 변별력 대조: 샤드 하나를 빼고 합산하면 총계가 달라진다(이 비교가 공허하지 않다).
    partial = tree / "partial.data"
    proc = _run(
        tree,
        [
            "-m",
            "coverage",
            "combine",
            "--keep",
            "--data-file",
            str(partial),
            *(str(out / f"coverage-{k}.data") for k in (1, 2)),
        ],
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _totals(tree, partial) != base


def test_reassigned_shard_count_still_partitions(tree: Path) -> None:
    """샤드 수를 바꿔도(배정이 달라져도) 통과 합이 같다 — OPS-83 ④의 소형 판."""
    out = tree / "pytest-shard"
    out.mkdir()
    total = 0
    for k in (1, 2):
        total += _pytest(
            tree,
            [
                "-p",
                "backend_shard_plugin",
                "--shard",
                f"{k}/2",
                "--shard-report",
                f"pytest-shard/report-{k}.json",
            ],
            plugin=True,
        )
    assert total == _TOTAL_TESTS
    proc = _run(tree, [str(_VERDICT), "reports", str(out)])
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_plugin_is_inert_without_shard_flag(tree: Path) -> None:
    """④ `--shard` 없이 플러그인만 실어도 전건이 돈다."""
    assert _pytest(tree, ["-p", "backend_shard_plugin"], plugin=True) == _TOTAL_TESTS


@pytest.mark.parametrize(
    "extra",
    [
        ["--shard", "1/3"],  # 보고서 없는 샤드 — 완전성을 증명할 수 없다
        ["--shard-report", "r.json"],  # 샤드 없는 보고서
        ["--shard", "4/3", "--shard-report", "r.json"],
    ],
)
def test_plugin_usage_errors_fail_loudly(tree: Path, extra: list[str]) -> None:
    proc = _run(tree, ["-m", "pytest", "-p", "backend_shard_plugin", "-q", *extra], plugin=True)
    assert proc.returncode == 4, f"UsageError(4)가 아니다: rc={proc.returncode}\n{proc.stderr}"
