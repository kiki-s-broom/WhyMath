"""CONST-02 — 진단 도구 벤더링(scripts/constitution/diag)과 기준선 러너의 스모크·변별력 동결.

왜 이 테스트가 있는가
--------------------
이식 완성 결과를 검증하는 사람 축은 260927 EOS 통합정밀진단(S00~S10)이고, 그 기계 축의 재료가
진단 도구 7종이다. 도구가 저장소 안에서 조용히 깨지면(의존성·경로·형식 정리 중 사고) 이식 후
재측정이 "0건"으로 위장된다. 그래서 도구가 실제로 돌고, 결함을 심으면 실제로 잡는지를 확인한다.

검증 계약
--------
① 벤더 파일 9종 실재 + UPSTREAM.md에 원본 sha256 줄
② 저장소용 계층 설정 2종이 유효 JSON이고, 모든 계층 패턴이 실제 파이썬 파일에 1건 이상 맞는다
   (0건 패턴은 그 계층을 공허하게 비워 금지 import를 못 본다)
③ tmp 초소형 git 저장소에서 러너가 integrity·rules_scan을 돌려 exit 0 + summary.json 생성
④ 변별력: NUL 바이트를 심은 파일을 integrity가 1건으로 보고한다 / 알 수 없는 도구 이름은 exit 2
"""

from __future__ import annotations

import fnmatch
import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DIAG = _REPO_ROOT / "scripts" / "constitution" / "diag"
_RUNNER = _REPO_ROOT / "scripts" / "constitution" / "run_baseline.py"
_VENDORED = (
    "_diagcommon.py",
    "diag_content.py",
    "diag_git.py",
    "diag_graph.py",
    "diag_imports.py",
    "diag_integrity.py",
    "diag_merge.py",
    "diag_rules_scan.py",
    "diag_layers.example.json",
)


def test_vendored_files_and_upstream_hashes() -> None:
    upstream = (_DIAG / "UPSTREAM.md").read_text(encoding="utf-8")
    for name in _VENDORED:
        assert (_DIAG / name).is_file(), f"벤더 파일 없음: {name}"
        line = next((ln for ln in upstream.splitlines() if f"`{name}`" in ln), "")
        assert (
            len(line.split("`")) >= 4 and len(line.split("`")[3]) == 64
        ), f"sha256 기록 없음: {name}"


@pytest.mark.parametrize("config", ["whymath_layers.json", "whymath_layers_7layer.json"])
def test_layer_patterns_match_real_files(config: str) -> None:
    data = json.loads((_DIAG / config).read_text(encoding="utf-8"))
    files = [
        p.relative_to(_REPO_ROOT).as_posix()
        for p in (_REPO_ROOT / "src").rglob("*.py")
        if "__pycache__" not in p.parts
    ]
    assert files, "src/ 파이썬 파일 0건 — 스캔 실패"
    empty = [
        (layer, pat)
        for layer, pats in data["layers"].items()
        for pat in pats
        if not any(fnmatch.fnmatch(f, pat) for f in files)
    ]
    assert not empty, f"실제 파일이 없는 계층 패턴(공허 계층): {empty}"


def _mini_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "mini"
    repo.mkdir()
    (repo / "a.py").write_text("# 한국어 주석\nx = 1\n", encoding="utf-8")
    (repo / "b.md").write_text("# 문서\n", encoding="utf-8")
    for cmd in (
        ["git", "init", "-q"],
        ["git", "add", "-A"],
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
    ):
        subprocess.run(cmd, cwd=repo, check=True, capture_output=True)
    return repo


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_RUNNER), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )


def test_runner_smoke(tmp_path: Path) -> None:
    repo = _mini_repo(tmp_path)
    out = tmp_path / "out"
    proc = _run("--repo", str(repo), "--out", str(out), "--only", "integrity,rules_scan")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert [r["tool"] for r in summary["results"]] == ["integrity", "rules_scan"]
    assert all(r["exit"] == 0 for r in summary["results"])


def test_integrity_detects_injected_nul(tmp_path: Path) -> None:
    repo = _mini_repo(tmp_path)
    (repo / "broken.py").write_bytes(b"x = 1\x00\n")
    out = tmp_path / "out"
    _run("--repo", str(repo), "--out", str(out), "--only", "integrity")
    report = json.loads((out / "raw" / "diag_integrity.json").read_text(encoding="utf-8"))
    text = json.dumps(report, ensure_ascii=False)
    assert "broken.py" in text, "NUL을 심은 파일이 보고되지 않았다"


def test_unknown_tool_is_argument_error(tmp_path: Path) -> None:
    proc = _run("--out", str(tmp_path / "out"), "--only", "no_such_tool")
    assert proc.returncode == 2 and "알 수 없는 도구" in proc.stderr
