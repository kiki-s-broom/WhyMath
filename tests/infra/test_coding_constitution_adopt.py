"""CONST-02 — 헌법 개정 채택 도우미(adopt_amendment.py)의 안전 계약 동결.

왜 이 테스트가 있는가
--------------------
헌법(`constitution/`)은 사람만 고친다(제9조·제11조). AI가 만든 초안을 Kiki가 채택할 때 손으로
복사하면 세 가지 사고가 난다 — ①A0002를 먼저 반영한 뒤 A0003 정정안을 통째로 복사하면 규칙 81건이
사라진다 ②PowerShell 5.1 `Set-Content`가 BOM·CRLF를 붙인다 ③개정 기록의 서명 칸이 빈 채로 남는다.
도우미는 이것을 막는다고 주장하므로, 그 주장을 결함 주입·순서 역전으로 확인한다.

검증 계약 (전부 tmp **합성** 헌법으로 잰다 — 저장소 헌법의 현재 내용에 기대지 않는다)
----------------------------------------------------------------------------------
① 미리보기는 아무것도 쓰지 않는다(전 파일 바이트 불변)
② AI 세션(CLAUDECODE)에서 --apply 는 exit 3 · 아무것도 쓰지 않는다 — merge_rules.py 도 같다
③ A0003 반영: 규칙 목록 불변 · 원본 등록부·version 은 정정안 그대로 · STAGE 한 칸 · 서명 채움 ·
   UTF-8(BOM 없음)·LF
④ 두 번 반영 거부 · 단계 두 칸 건너뛰기 거부(쓰지 않음)
⑤ 순서 역전(A0002 → A0003)에도 병합된 규칙이 사라지지 않는다
⑥ A0002 제안본이 기존 조문 문구를 바꾸면 거부(쓰지 않음)
⑦ 저장소의 실제 초안이 도우미와 형식이 맞는다(미채택이면 미리보기 exit 0 · 채택됐으면 '이미 채택')
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TOOLS = _REPO_ROOT / "scripts" / "constitution"

_ARTICLES = "".join(f"**제{n}조(조문{n})**\n본문 {n}.\n\n" for n in range(1, 12))
_CONSTITUTION = f"# 합성 헌법\n\n- 판: v1.0 (제정)\n\n{_ARTICLES}"
_PROPOSED = _CONSTITUTION.replace("- 판: v1.0 (제정)", "- 판: v1.1 (A0002 개정)").replace(
    "**제8조(조문8)**", "**제7조의2(경계)**\n① 합성 신설 조문.\n\n**제8조(조문8)**"
)
_RULE = """
  - id: RT-01
    article: 제9조
    chapter: 0
    axis: 경계
    statement: 합성 규칙
    level: L5
    check: hook/guard.py
    run: python hook/guard.py
    stage: 2
"""
_RULES_V10 = f"""# 합성 등록부 머리말 — 이식 단계 (1~5)
version: "1.0"

rules:
{_RULE}
# 원본 등록부
sources:
  - name: 원본 A
    path: data/proposed_a.yaml
"""
_RULES_V101 = f"""# 합성 등록부 머리말 — 이식 단계 (1~5)
version: "1.0.1"

rules:
{_RULE}
# 원본 등록부
sources:
  # 정정 주석
  - name: 원본 A
    path: data/real_a.yaml
    version: "합성 판 1"
"""
_ADDITIONS = """# 합성 추가분
rules:

  - id: RT-02
    article: 제7조의2
    chapter: 5
    axis: 경계
    statement: 합성 추가 규칙
    level: L3
    stage: 3
"""
_DRAFT_A0003 = """# 개정 기록 A0003 — 합성 (초안)

- 상태: **초안 — 채택 전** (합성)
- 일자: 2026-09-28 (초안 작성) · 채택일: ____ (Kiki 기입)
- 개정자: Kiki (서명란: ____)
"""
_DRAFT_A0002 = """# A0002 — 합성 (초안)

- 상태: **초안 — 채택 전** (합성)
- 작성: 2026-09-26
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    const = root / "constitution"
    _write(const / "CONSTITUTION.md", _CONSTITUTION)
    _write(const / "rules.yaml", _RULES_V10)
    _write(const / "STAGE", "1\n")
    _write(const / "amendments" / "A0001_제정.md", "# A0001\n")
    _write(root / "data" / "real_a.yaml", "{}\n")
    prop = root / "docs" / "constitution_proposals"
    _write(prop / "rules_v1.0.1_sources_fixed.yaml", _RULES_V101)
    _write(prop / "A0003_sources_registry_draft.md", _DRAFT_A0003)
    _write(prop / "CONSTITUTION_v1.1_A0002_proposed.md", _PROPOSED)
    _write(prop / "rules_additions_v1.1.yaml", _ADDITIONS)
    _write(prop / "A0002_parts_II-VII_rules_draft.md", _DRAFT_A0002)
    tools = root / "scripts" / "constitution"
    tools.mkdir(parents=True)
    for name in ("adopt_amendment.py", "merge_rules.py", "audit.py"):
        shutil.copy2(_TOOLS / name, tools / name)
    return root


def _env(ai_session: bool) -> dict[str, str]:
    env = {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", "PATH": os.environ.get("PATH", "")}
    if ai_session:
        env["CLAUDECODE"] = "1"
    return env


def _adopt(root: Path, *args: str, ai: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(root / "scripts" / "constitution" / "adopt_amendment.py"), *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        env=_env(ai),
    )


def _snapshot(root: Path) -> dict[str, str]:
    """저장소의 모든 파일 지문 — '아무것도 쓰지 않았다'를 바이트로 단언한다."""
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }


def _rules(root: Path) -> dict:
    return yaml.safe_load((root / "constitution" / "rules.yaml").read_text(encoding="utf-8"))


# ── ① 미리보기 ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("args", [("A0003", "--stage", "2"), ("A0002",)])
def test_preview_writes_nothing(sandbox: Path, args: tuple[str, ...]) -> None:
    before = _snapshot(sandbox)
    proc = _adopt(sandbox, *args)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "ADOPT_RESULT=preview" in proc.stdout
    assert _snapshot(sandbox) == before


# ── ② AI 세션 거부 ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("args", [("A0003", "--stage", "2"), ("A0002",)])
def test_apply_refused_in_ai_session(sandbox: Path, args: tuple[str, ...]) -> None:
    before = _snapshot(sandbox)
    proc = _adopt(sandbox, *args, "--apply", ai=True)
    assert proc.returncode == 3 and "ADOPT_RESULT=refused_ai_session" in proc.stdout
    assert _snapshot(sandbox) == before


def test_merge_rules_apply_refused_in_ai_session(sandbox: Path) -> None:
    before = _snapshot(sandbox)
    proc = subprocess.run(
        [
            sys.executable,
            "scripts/constitution/merge_rules.py",
            "docs/constitution_proposals/rules_additions_v1.1.yaml",
            "--apply",
        ],
        cwd=sandbox,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        env=_env(True),
    )
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert _snapshot(sandbox) == before


# ── ③ A0003 반영 ───────────────────────────────────────────────────────────


def test_a0003_apply_replaces_only_sources_and_version(sandbox: Path) -> None:
    rules_before = _rules(sandbox)["rules"]
    proc = _adopt(sandbox, "A0003", "--stage", "2", "--apply")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "ADOPT_RESULT=applied" in proc.stdout
    after = _rules(sandbox)
    assert after["rules"] == rules_before, "규칙 목록은 바뀌면 안 된다"
    proposal = yaml.safe_load(_RULES_V101)
    assert after["sources"] == proposal["sources"] and after["version"] == "1.0.1"
    raw = (sandbox / "constitution" / "rules.yaml").read_bytes()
    assert raw == _RULES_V101.encode("utf-8"), "기준이 같으면 결과는 정정안과 바이트 동일"
    assert (sandbox / "constitution" / "STAGE").read_bytes() == b"2\n"
    amendment = sandbox / "constitution" / "amendments" / "A0003_원본등록부정정.md"
    text = amendment.read_bytes()
    assert not text.startswith(b"\xef\xbb\xbf") and b"\r\n" not in text, "BOM·CRLF 금지"
    body = text.decode("utf-8")
    assert "- 상태: **채택**" in body and "____" not in body
    assert "STAGE 1 → 2" in body and not body.splitlines()[0].endswith("(초안)")


# ── ④ 거부 ─────────────────────────────────────────────────────────────────


def test_a0003_twice_is_refused(sandbox: Path) -> None:
    assert _adopt(sandbox, "A0003", "--apply").returncode == 0
    before = _snapshot(sandbox)
    proc = _adopt(sandbox, "A0003", "--apply")
    assert proc.returncode == 1 and "이미 채택" in proc.stderr
    assert _snapshot(sandbox) == before


def test_stage_skip_is_refused(sandbox: Path) -> None:
    before = _snapshot(sandbox)
    proc = _adopt(sandbox, "A0003", "--stage", "3", "--apply")
    assert proc.returncode == 1 and "한 칸" in proc.stderr
    assert _snapshot(sandbox) == before


# ── ⑤ 순서 역전 ────────────────────────────────────────────────────────────


def test_a0002_then_a0003_keeps_merged_rules(sandbox: Path) -> None:
    first = _adopt(sandbox, "A0002", "--apply")
    assert first.returncode == 0, first.stdout + first.stderr
    assert [r["id"] for r in _rules(sandbox)["rules"]] == ["RT-01", "RT-02"]
    second = _adopt(sandbox, "A0003", "--stage", "2", "--apply")
    assert second.returncode == 0, second.stdout + second.stderr
    after = _rules(sandbox)
    assert [r["id"] for r in after["rules"]] == ["RT-01", "RT-02"], "A0002 규칙이 사라졌다"
    assert after["sources"] == yaml.safe_load(_RULES_V101)["sources"]
    const = (sandbox / "constitution" / "CONSTITUTION.md").read_text(encoding="utf-8")
    assert "**제7조의2(경계)**" in const
    assert "이식 단계 (1~6)" in (sandbox / "constitution" / "rules.yaml").read_text("utf-8")
    names = sorted(p.name for p in (sandbox / "constitution" / "amendments").glob("A*.md"))
    assert names == ["A0001_제정.md", "A0002_파트II-VII규칙.md", "A0003_원본등록부정정.md"]


# ── ⑥ A0002 제안본 변조 ────────────────────────────────────────────────────


def test_a0002_refuses_proposal_that_changes_existing_text(sandbox: Path) -> None:
    proposed = sandbox / "docs" / "constitution_proposals" / "CONSTITUTION_v1.1_A0002_proposed.md"
    original = proposed.read_text(encoding="utf-8")
    mutated = original.replace("본문 9.", "본문 9 — 몰래 바꾼 문구.")
    assert mutated != original
    proposed.write_text(mutated, encoding="utf-8")
    before = _snapshot(sandbox)
    proc = _adopt(sandbox, "A0002", "--apply")
    assert proc.returncode == 1 and "그대로 포함하지 않는다" in proc.stderr
    assert _snapshot(sandbox) == before


# ── ⑦ 실제 초안과의 형식 정합 ──────────────────────────────────────────────


def _real_adopted(number: str) -> bool:
    return any((_REPO_ROOT / "constitution" / "amendments").glob(f"{number}_*.md"))


def test_real_a0003_draft_is_adoptable_or_already_adopted() -> None:
    stage = int((_REPO_ROOT / "constitution" / "STAGE").read_text(encoding="utf-8").strip())
    args = ["A0003"] + (["--stage", str(stage + 1)] if stage < 6 else [])
    proc = _adopt(_REPO_ROOT, *args)
    if _real_adopted("A0003"):
        assert proc.returncode == 1 and "이미 채택" in proc.stderr
    else:
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "ADOPT_RESULT=preview" in proc.stdout


def test_real_a0002_draft_is_adoptable_or_already_adopted() -> None:
    proc = _adopt(_REPO_ROOT, "A0002")
    if _real_adopted("A0002"):
        assert proc.returncode == 1 and "이미 채택" in proc.stderr
    else:
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "ADOPT_RESULT=preview" in proc.stdout
