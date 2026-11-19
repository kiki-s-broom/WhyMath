"""RS-R1 모듈 대장 도구 테스트 — 임시 폴더의 합성 패키지와 실제 coverage JSON으로 검사한다.

합성 패키지 `rsyn`(진입점 = rsyn.app · 둘째 진입점 = rsyn.cli):
- live      : app이 import하고 경로 테스트가 함수를 실행 → 가동
- waiting   : app이 import하지만 함수는 안 부름(import만) → 대기
- constants : 함수 없는 모듈, app이 import → 맨 위 코드 실행으로 가동
- island    : 아무도 import 안 함, 단위 테스트만 실행 → 섬(cli에서는 닿아서 대기)
- debris    : 어디서도 안 닿음 → 잔해
- sub.via_init : sub/__init__.py만 import → 부모 __init__ 보정으로 닿음
- dynamic   : importlib 문자열로만 불러옴 → 가동 + 비고 '문자열로 불러옴'
- loose/orphan_fs.py : __init__.py 없는 폴더 → 그래프 밖 보정으로 대장에 들어감
"""

from __future__ import annotations

import csv
import importlib
import subprocess
import sys
from pathlib import Path

import pytest
from golden.rescue import ledger

_FILES = {
    "rsyn/__init__.py": "",
    "rsyn/app.py": (
        "import importlib\n\nfrom rsyn import constants, waiting\nfrom rsyn.sub import live\n\n\n"
        "def run():\n    live.work()\n"
        "    return importlib.import_module('rsyn.dynamic').go() + constants.X\n"
    ),
    "rsyn/cli.py": "from rsyn import island\n",
    "rsyn/constants.py": "X = 1\n",
    "rsyn/waiting.py": "def unused():\n    return 0\n",
    "rsyn/island.py": "def helper():\n    return 3\n",
    "rsyn/debris.py": "def dead():\n    return 4\n",
    "rsyn/dynamic.py": "def go():\n    return 5\n",
    "rsyn/sub/__init__.py": "from rsyn.sub import via_init\n",
    "rsyn/sub/live.py": "def work():\n    return 1\n",
    "rsyn/sub/via_init.py": "def v():\n    return 6\n",
    "rsyn/loose/orphan_fs.py": "def lost():\n    return 7\n",
}
_ENTRIES = ["rsyn.app", "rsyn.cli"]


def _coverage(root: Path, script: str, name: str) -> Path:
    """실제 coverage로 스크립트를 돌려 JSON을 만든다(형식 가정을 실물 도구로 검증)."""
    (root / f"{name}.py").write_text(script, encoding="utf-8")
    out = root / f"{name}.json"
    run = [sys.executable, "-m", "coverage", "run", f"--data-file={root / name}.cov"]
    subprocess.run([*run, f"{name}.py"], cwd=root, check=True)
    subprocess.run(
        [sys.executable, "-m", "coverage", "json", f"--data-file={root / name}.cov", "-o", out],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return out


@pytest.fixture()
def syn(tmp_path: Path) -> tuple[Path, Path, Path]:
    """합성 패키지 + 경로 테스트 실행 기록 + 단위 테스트 실행 기록."""
    for rel, body in _FILES.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(body, encoding="utf-8")
    importlib.invalidate_caches()
    journey = _coverage(tmp_path, "from rsyn import app\napp.run()\n", "journey")
    unit = _coverage(tmp_path, "from rsyn import island\nisland.helper()\n", "unit")
    return tmp_path, journey, unit


def _grades(root: Path, journey: Path | None, unit: Path | None) -> dict[str, ledger.Row]:
    rows = ledger.build_ledger(_ENTRIES, [journey, None], unit, root, ("rsyn",))
    return {r.module: r for r in rows}


def test_four_grades_and_corrections(syn: tuple[Path, Path, Path]) -> None:
    root, journey, unit = syn
    rows = _grades(root, journey, unit)
    golden = {m: r.grades[0] for m, r in rows.items()}
    assert golden["rsyn.sub.live"] == "가동"
    assert golden["rsyn.constants"] == "가동"  # 함수 없는 모듈 = 맨 위 코드 기준
    assert golden["rsyn.waiting"] == "대기"  # import만 됨 = 실행 아님
    assert golden["rsyn.island"] == "섬"
    assert golden["rsyn.debris"] == "잔해"
    # 보정 ①: sub/__init__.py가 import하는 via_init은 닿는다
    assert rows["rsyn.sub.via_init"].reached[0] is True
    # 보정 ②: __init__.py 없는 폴더의 파일이 대장에 있고 비고가 붙는다
    assert "rsyn.loose.orphan_fs" in rows
    assert golden["rsyn.loose.orphan_fs"] == "잔해"
    assert "그래프 밖" in rows["rsyn.loose.orphan_fs"].notes[0]
    # 보정 ③: 경로 테스트는 실행했지만 정적으로 안 닿음
    assert golden["rsyn.dynamic"] == "가동"
    assert "문자열로 불러옴(골든)" in rows["rsyn.dynamic"].notes
    # 진입점마다 따로: island는 cli에서 닿고 실행 기록이 없다
    assert rows["rsyn.island"].grades[1] == "대기(실행 기록 없음)"


def test_without_records_marks_unknown(syn: tuple[Path, Path, Path]) -> None:
    root, _, _ = syn
    rows = _grades(root, None, None)
    assert rows["rsyn.waiting"].grades[0] == "대기(실행 기록 없음)"
    assert rows["rsyn.debris"].grades[0] == "섬/잔해(실행 기록 없음)"


def test_csv_columns_and_summary(syn: tuple[Path, Path, Path]) -> None:
    root, journey, unit = syn
    out = root / "ledger.csv"
    argv = ["--entry", "rsyn.app", "--entry", "rsyn.cli", "--journey-golden", str(journey)]
    argv += ["--unit", str(unit), "--csv", str(out)]
    assert ledger.main(argv, root, ("rsyn",), root) == 0
    with out.open(encoding="utf-8-sig") as fh:
        table = list(csv.reader(fh))
    assert tuple(table[0]) == ledger.CSV_HEADER
    by_mod = {r[0]: dict(zip(table[0], r, strict=True)) for r in table[1:]}
    assert by_mod["rsyn.sub.live"]["경로 테스트가 실행"] == "예(골든)"
    assert by_mod["rsyn.island"]["단위 테스트가 실행"] == "예"
    assert by_mod["rsyn.island"]["이 모듈을 import하는 모듈 수"] == "1"
    summary = ledger.summarize(list(_grades(root, journey, unit).values()), _ENTRIES)
    assert len(summary) <= 50
    assert summary[-1] == "전부 잔해인 패키지 1개: rsyn.loose"


def test_gate_fails_on_new_orphan(syn: tuple[Path, Path, Path]) -> None:
    root, journey, unit = syn
    base = root / "baseline.txt"
    argv = ["--entry", "rsyn.app", "--journey-golden", str(journey), "--unit", str(unit)]
    argv += ["--csv", str(root / "l.csv"), "--baseline", str(base), "--gate-package", "rsyn"]
    assert ledger.main([*argv, "--update"], root, ("rsyn",), root) == 0
    assert ledger.main(argv, root, ("rsyn",), root) == 0  # 기준선과 같으면 통과
    (root / "rsyn" / "new_unwired.py").write_text("def n():\n    return 8\n", encoding="utf-8")
    importlib.invalidate_caches()
    assert ledger.main(argv, root, ("rsyn",), root) == 1  # 연결 안 된 새 파일 → 실패


def test_coverage_without_functions_is_rejected(syn: tuple[Path, Path, Path]) -> None:
    root, _, _ = syn
    bad = root / "bad.json"
    bad.write_text('{"files": {"rsyn/app.py": {"executed_lines": [1]}}}', encoding="utf-8")
    with pytest.raises(ValueError, match="functions"):
        _grades(root, bad, None)
