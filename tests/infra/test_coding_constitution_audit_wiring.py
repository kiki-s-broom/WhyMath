"""CONST-02 — 위헌 심사 래칫·파이프라인 검사의 CI 배선과 래칫 변별력 동결.

왜 이 테스트가 있는가
--------------------
코딩 헌법 제10조 ①은 "L4·L5 규칙은 집행 장치가 존재하고 연결되어 있어야 효력을 가진다"이다.
이 저장소는 "검증 장치를 만들고 배선 확인 없이 완료 선언"을 반복한 이력이 있어(OPS-03·08·11),
위헌 심사가 CI에서 **실제로 도는지**를 기계가 동결해야 한다. 또 래칫은 "기준선에 없는 차단이
생기면 red"라는 주장을 하므로, 그 주장을 결함 주입으로 확인한다.

검증 계약
--------
① ci.yml harness-integrity 잡에 래칫·파이프라인 검사·가드 자가시험 스텝이 실재한다(잡·스텝 0건이면 예외)
② 기준선 JSON 형식(단계 1~6 · blocking == len(items) · 판정 기준 표기)
③ 저장소 현재 상태에서 래칫 exit 0
④ 변별력(tmp 합성 등록부): 새 차단 → 1 · 동일 → 0 · 바꿔치기(하나 해소 + 하나 신규) → 1 ·
   등록부 파손 → 2 · 단계 불일치 → 2 · 증가 갱신 거부(파일 불변) → 1 · 하향 갱신 → 기록 1건 추가 ·
   단계 상향은 새 단계 규칙의 집행 장치가 있을 때만 기준선 이동 · audit.py 부재 → 2

④가 저장소의 헌법이 아니라 **합성 등록부**로 재는 이유
-----------------------------------------------------
헌법은 Kiki가 개정한다(제11조). 변별력 시험이 저장소의 현재 상태(단계 1·차단 7건)를 전제로
삼으면, Kiki가 원본 등록부를 정정하거나 단계를 올리는 **정상 개정 PR이 이 테스트 때문에 red**가
된다 — 사람이 헌법을 고칠 수 없게 막는 테스트는 보호가 아니라 제11조 위반이다(2026-09-28 자기
점검에서 발견: 초판이 '차단 7건'·'1→2단계'를 전제로 짜여 있었다). 그래서 ④는 규칙 1건·원본
2건짜리 합성 등록부를 tmp에 만들고, 기준선도 그 상태에서 `--init`으로 새로 만든다. 저장소 상태에
대한 판정은 ③(현재 상태 exit 0)이 맡는다.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_RATCHET = _REPO_ROOT / "scripts" / "constitution" / "audit_ratchet.py"
_AUDIT = _REPO_ROOT / "scripts" / "constitution" / "audit.py"
_BASELINE = _REPO_ROOT / "metrics" / "coding_constitution_audit_baseline.json"
_RATCHET_RUN = "python3 scripts/constitution/audit_ratchet.py"
_PIPE_RUN_PARTS = (
    "python3 scripts/constitution/pipeline_check.py",
    "--require copyright,backup,curriculum_review",
    "--upstream-of publish:copyright",
    "--direct-upstream-of publish:copyright",
)


def _job_runs(job: str) -> list[str]:
    data = yaml.safe_load(_CI.read_text(encoding="utf-8"))
    steps = (data.get("jobs") or {}).get(job, {}).get("steps") or []
    runs = [" ".join(str(s.get("run", "")).split()) for s in steps if s.get("run")]
    if not runs:
        raise AssertionError(f"{job} 잡의 run 스텝을 하나도 못 읽었다 — 파서 위장 금지")
    return runs


# ── ① 배선 ─────────────────────────────────────────────────────────────────


def test_ratchet_step_wired_in_harness_integrity() -> None:
    assert _RATCHET_RUN in _job_runs("harness-integrity")


def test_pipeline_check_step_wired_in_harness_integrity() -> None:
    runs = _job_runs("harness-integrity")
    assert any(all(part in run for part in _PIPE_RUN_PARTS) for run in runs), runs


def test_guard_selftest_step_wired_in_harness_integrity() -> None:
    """R0-01 의 run 명령이 **등록 문자열 그대로** CI 스텝에 있어야 3단계 심사에서 '연결됨'이다."""
    rules = yaml.safe_load((_REPO_ROOT / "constitution" / "rules.yaml").read_text(encoding="utf-8"))
    registered = [r["run"] for r in rules["rules"] if r["id"] == "R0-01"]
    assert len(registered) == 1, "R0-01 이 등록부에 정확히 1건이어야 한다"
    assert registered[0] in _job_runs("harness-integrity"), registered


# ── ② 기준선 형식 ──────────────────────────────────────────────────────────


def test_baseline_shape() -> None:
    base = json.loads(_BASELINE.read_text(encoding="utf-8"))
    assert isinstance(base["stage"], int) and 1 <= base["stage"] <= 6
    assert base["blocking"] == len(base["items"])
    assert base["judged_at"].startswith("HEAD ") and base["history"]


# ── ③ 현재 상태 ────────────────────────────────────────────────────────────


def _run(root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(root / "scripts" / "constitution" / "audit_ratchet.py"), *extra],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
        env={"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", "PATH": ""},
    )


def test_ratchet_passes_on_repo() -> None:
    proc = _run(_REPO_ROOT)
    assert proc.returncode == 0, proc.stdout + proc.stderr


# ── ④ 변별력 ───────────────────────────────────────────────────────────────


_SYNTH_RULES = """\
version: "test"
rules:
  - id: RT-01
    article: 제9조
    chapter: 0
    axis: 경계
    statement: 합성 규칙 — 2단계 L5, 집행 장치 파일이 있어야 통과
    level: L5
    check: hook/guard.py
    run: python hook/guard.py
    stage: 2
sources:
  - name: 기준 원본 A
    path: data/a.yaml
  - name: 기준 원본 B
    path: data/b.yaml
"""


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    """합성 등록부(단계 1 · 차단 2건: 원본 A·B 부재)와 그 상태의 기준선을 가진 tmp 저장소."""
    root = tmp_path / "repo"
    (root / "constitution").mkdir(parents=True)
    (root / "constitution" / "rules.yaml").write_text(_SYNTH_RULES, encoding="utf-8")
    (root / "constitution" / "STAGE").write_text("1\n", encoding="utf-8")
    (root / "scripts" / "constitution").mkdir(parents=True)
    shutil.copy2(_AUDIT, root / "scripts" / "constitution" / "audit.py")
    shutil.copy2(_RATCHET, root / "scripts" / "constitution" / "audit_ratchet.py")
    init = _run(root, "--init")
    assert init.returncode == 0, init.stdout + init.stderr
    base = json.loads((root / "metrics" / _BASELINE.name).read_text(encoding="utf-8"))
    assert base["items"] == ["원본:기준 원본 A", "원본:기준 원본 B"], "전제: 합성 차단 2건"
    return root


def _mutate(path: Path, old: str, new: str) -> None:
    original = path.read_text(encoding="utf-8")
    assert original.count(old) == 1, f"주입 대상이 정확히 1건이어야 한다: {old!r}"
    mutated = original.replace(old, new)
    assert mutated != original
    path.write_text(mutated, encoding="utf-8")


def _touch(root: Path, rel: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{}\n", encoding="utf-8")


_NEW_SOURCE = "sources:\n  - name: 주입 원본\n    path: no/such/file.yaml\n"


def test_init_refuses_when_baseline_exists(sandbox: Path) -> None:
    baseline = sandbox / "metrics" / _BASELINE.name
    before = baseline.read_bytes()
    proc = _run(sandbox, "--init")
    assert proc.returncode == 1 and "이미 있다" in proc.stderr
    assert baseline.read_bytes() == before


def test_identical_state_passes(sandbox: Path) -> None:
    assert _run(sandbox).returncode == 0


def test_new_blocking_item_fails(sandbox: Path) -> None:
    _mutate(sandbox / "constitution" / "rules.yaml", "sources:\n", _NEW_SOURCE)
    proc = _run(sandbox)
    assert proc.returncode == 1 and "주입 원본" in proc.stderr


def test_swap_is_caught(sandbox: Path) -> None:
    """하나를 고치고 하나를 새로 만들면 개수는 같지만 red여야 한다(집합 비교)."""
    _touch(sandbox, "data/a.yaml")
    _mutate(sandbox / "constitution" / "rules.yaml", "sources:\n", _NEW_SOURCE)
    proc = _run(sandbox, "--json")
    verdict = json.loads(proc.stdout)
    assert verdict["current_blocking"] == verdict["baseline_blocking"], "전제: 개수는 같다"
    assert verdict["new_blocking"] == ["원본:주입 원본"]
    assert proc.returncode == 1


def test_broken_registry_is_measurement_failure(sandbox: Path) -> None:
    (sandbox / "constitution" / "rules.yaml").write_text("rules: [\n", encoding="utf-8")
    assert _run(sandbox).returncode == 2


def test_stage_mismatch_is_measurement_failure(sandbox: Path) -> None:
    baseline = sandbox / "metrics" / _BASELINE.name
    data = json.loads(baseline.read_text(encoding="utf-8"))
    data["stage"] = 3
    baseline.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    proc = _run(sandbox)
    assert proc.returncode == 2 and "단계 불일치" in proc.stderr


def test_update_baseline_refuses_increase(sandbox: Path) -> None:
    baseline = sandbox / "metrics" / _BASELINE.name
    before = baseline.read_bytes()
    _mutate(sandbox / "constitution" / "rules.yaml", "sources:\n", _NEW_SOURCE)
    proc = _run(sandbox, "--update-baseline")
    assert proc.returncode == 1 and "증가 갱신 거부" in proc.stderr
    assert baseline.read_bytes() == before


def test_update_baseline_lowers_and_records(sandbox: Path) -> None:
    _touch(sandbox, "data/a.yaml")
    baseline = sandbox / "metrics" / _BASELINE.name
    before = json.loads(baseline.read_text(encoding="utf-8"))
    proc = _run(sandbox, "--update-baseline")
    assert proc.returncode == 0, proc.stderr
    after = json.loads(baseline.read_text(encoding="utf-8"))
    assert after["items"] == ["원본:기준 원본 B"]
    assert after["blocking"] == before["blocking"] - 1
    assert len(after["history"]) == len(before["history"]) + 1


def test_stage_raise_moves_baseline_only_without_new_blocking(sandbox: Path) -> None:
    """단계를 올리면 새로 켜지는 규칙의 집행 장치가 있어야 기준선이 새 단계로 옮겨진다(부록 C)."""
    (sandbox / "constitution" / "STAGE").write_text("2\n", encoding="utf-8")
    baseline = sandbox / "metrics" / _BASELINE.name
    before = baseline.read_bytes()
    # ① 2단계 규칙 RT-01 의 집행 장치가 없으면 새 차단 → 거부, 파일 불변
    refused = _run(sandbox, "--update-baseline")
    assert refused.returncode == 1 and "RT-01" in refused.stderr
    assert baseline.read_bytes() == before
    # ② 집행 장치를 두면 새 차단 없음 → 기준선이 2단계로 이동하고 기록이 남는다
    _touch(sandbox, "hook/guard.py")
    moved = _run(sandbox, "--update-baseline")
    assert moved.returncode == 0, moved.stdout + moved.stderr
    after = json.loads(baseline.read_text(encoding="utf-8"))
    assert after["stage"] == 2 and "단계 이동 1→2" in after["history"][-1]["reason"]
    assert _run(sandbox).returncode == 0


def test_missing_audit_is_measurement_failure(sandbox: Path) -> None:
    (sandbox / "scripts" / "constitution" / "audit.py").unlink()
    assert _run(sandbox).returncode == 2
