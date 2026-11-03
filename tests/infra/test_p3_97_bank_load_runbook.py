"""P3-97 문제은행 적재 런북(`docs/ops/p3_97_bank_load_runbook.md`)과 읽기 전용 미리보기 프로브의 계약 동결.

① **쓰기 가드** — 적재 명령(두 은행)이 단일 최상위 `if (…) { … } else { "WRITE_REFUSED=True …" }` 안에 있고,
   조건이 백업·확인 입력·미리보기 판정을 **다시 검사**하며 거부 문장이 무엇이 False였는지 말한다.
② **범위** — 런북이 적재하는 은행은 Kiki 결정(2026-11-03)의 두 개뿐이다(fill 은행 금지).
③ **표기·실재·불간섭** — 언어 태그·자리표시자 0·프로브 키 실재·`worktree add --detach`·`--overwrite-cms-edits` 금지.
④ **프로브는 쓰지 못한다** · ⑤ **미리보기 집계**(slug 충돌·보호 행·판정).
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUNBOOK = _REPO_ROOT / "docs" / "ops" / "p3_97_bank_load_runbook.md"
_PROBE = _REPO_ROOT / "scripts" / "ops" / "p3_97_bank_load_probe.py"
_LINK_PROBE = _REPO_ROOT / "scripts" / "ops" / "p3_32_hint_link_probe.py"
_FENCE = re.compile(r"^```([^\n`]*)\n(.*?)^```", re.MULTILINE | re.DOTALL)
_ALLOWED_BANKS = {
    "data/corpus/problem_bank_p3_calculus1_diff_v0/problems.jsonl",
    "data/corpus/problem_bank_conceptual_v0/problems.jsonl",
}


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def probe() -> ModuleType:
    return _load(_PROBE, "p3_97_probe_under_test")


@pytest.fixture(scope="module")
def runbook() -> str:
    return _RUNBOOK.read_text(encoding="utf-8")


def _powershell(text: str) -> list[str]:
    return [m.group(2) for m in _FENCE.finditer(text) if m.group(1).strip() == "powershell"]


# ── ① 쓰기 가드 ─────────────────────────────────────────────────────────

_IF_LINE = re.compile(r"^if \((?P<cond>[^\n]*?)\) \{ (?P<body>.*) \} else \{ (?P<else>.*) \}$")
_NEEDED = ("$BackupOk", "$ConfirmOk", "$PreviewOk")


def _guard_violations(text: str) -> list[str]:
    lines = [line for body in _powershell(text) for line in body.splitlines()]
    hits = [line for line in lines if "problem_bank.populate" in line]
    if len(hits) != 1:
        return [f"적재 줄이 1개가 아니다: {len(hits)}"]
    m = _IF_LINE.match(hits[0].strip())
    if m is None or "problem_bank.populate" not in m.group("body"):
        return ["가드 밖 적재"]
    scope = m.group("cond")
    for ready in re.findall(r"\$\w+Ready\b", scope):
        scope += " " + " ".join(x for x in lines if x.strip().startswith(f"{ready} ="))
    out = [f"가드가 {v}를 재검사하지 않음" for v in _NEEDED if v not in scope]
    refusal = re.search(r'"WRITE_REFUSED=True[^"]*"', m.group("else"))
    if refusal is None or "$" not in refusal.group(0):
        out.append("거부 문장이 무엇이 False였는지 말하지 않음")
    return out


def test_load_is_guarded(runbook: str) -> None:
    assert _guard_violations(runbook) == []


@pytest.mark.parametrize(
    ("label", "old", "new"),
    [
        (
            "no_backup",
            "$LoadReady = $BackupOk -and $ConfirmOk",
            "$LoadReady = $ConfirmOk",
        ),
        (
            "no_preview",
            '-and $CodeOk -and $PreviewOk -and ($ReachExit -eq 0)\n"LOAD_READY',
            '-and $CodeOk -and ($ReachExit -eq 0)\n"LOAD_READY',
        ),
        (
            "silent_refusal",
            '"WRITE_REFUSED=True — BACKUP_OK=$BackupOk CONFIRMED=$ConfirmOk WT_OK=$WtOk CODE_OK=$CodeOk PREVIEW_OK=$PreviewOk REACH_EXIT=$ReachExit · 전부 True/0이어야 적재합니다. [B]~[E]를 같은 창에서 순서대로 실행하세요"',
            '"WRITE_REFUSED=True"',
        ),
    ],
)
def test_guard_mutations_are_caught(runbook: str, label: str, old: str, new: str) -> None:
    mutated = runbook.replace(old, new, 1)
    assert mutated != runbook, f"뮤테이션 미적용: {label}"
    assert _guard_violations(mutated), f"뮤테이션 미검출: {label}"


# ── ② 범위 ──────────────────────────────────────────────────────────────


def test_only_decided_banks_are_loaded(runbook: str) -> None:
    code = "\n".join(_powershell(runbook))
    banks = set(re.findall(r'"(data/corpus/problem_bank_[\w]+/problems\.jsonl)"', code))
    assert banks == _ALLOWED_BANKS
    assert "problem_bank_p3_fill_v0" not in code


def test_never_overwrites_cms_edits(runbook: str) -> None:
    assert "--overwrite-cms-edits" not in "\n".join(_powershell(runbook))


# ── ③ 표기·실재·불간섭 ────────────────────────────────────────────────


def test_fences_tagged_and_no_placeholders(runbook: str) -> None:
    assert all(m.group(1).strip() for m in _FENCE.finditer(runbook))
    for body in _powershell(runbook):
        code = "\n".join(x for x in body.splitlines() if not x.lstrip().startswith("#"))
        assert not re.search(r"<[^>\n]*>|여기에_", code)


def test_probe_keys_read_by_runbook_exist(runbook: str, probe: ModuleType) -> None:
    link = _load(_LINK_PROBE, "p3_32_probe_for_p3_97")
    known = set(probe.ALL_KEYS) | set(link.ALL_KEYS)
    read = set(re.findall(r'\$\w+Map\["([A-Z0-9_]+)"\]', runbook))
    read |= set(re.findall(r'Get-KvInt \$\w+ "([A-Z0-9_]+)"', runbook))
    assert read
    assert sorted(read - known) == []


def test_no_checkout_moves(runbook: str) -> None:
    code = "\n".join(_powershell(runbook))
    assert not re.search(r"\bgit\b[^\n]*\b(checkout|switch|reset|stash|pull)\b", code)
    assert "git worktree add --detach $Wt origin/main" in code


# ── ④ 프로브는 쓰지 못한다 ──────────────────────────────────────────────


def test_probe_is_read_only() -> None:
    text = _PROBE.read_text(encoding="utf-8")
    assert "SET TRANSACTION READ ONLY" in text
    assert not re.search(r"\b(INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|TRUNCATE)\b", text)
    assert ".commit(" not in text


# ── ⑤ 미리보기 집계 ────────────────────────────────────────────────────


def _rows(probe: ModuleType) -> list[object]:
    return [
        probe.BankRow("id-a", "slug-a", True),
        probe.BankRow("id-b", "slug-b", False),
        probe.BankRow("id-c", "slug-c", True),
        probe.BankRow("id-d", "slug-d", True),
    ]


def test_preview_counts(probe: ModuleType) -> None:
    p = probe.preview_bank(
        "bank",
        _rows(probe),
        db_ids=frozenset({"id-a"}),
        db_slug_to_id={"slug-a": "id-a", "slug-c": "OTHER"},
        protected_ids=frozenset({"id-a"}),
    )
    # a=이미 있음(보호) · b=새 행(미승인) · c=slug 충돌 · d=새 행(승인)
    assert (p.rows, p.approved, p.in_db_same_id, p.protected) == (4, 3, 1, 1)
    assert (p.new, p.new_approved, p.slug_conflict) == (2, 1, 1)
    assert p.new_ids == frozenset({"id-b", "id-d"})
    assert probe.load_verdict([p]) == probe.VERDICT_SLUG_CONFLICT


def test_preview_verdicts(probe: ModuleType) -> None:
    rows = _rows(probe)
    fresh = probe.preview_bank(
        "b", rows, db_ids=frozenset(), db_slug_to_id={}, protected_ids=frozenset()
    )
    assert probe.load_verdict([fresh]) == probe.VERDICT_OK
    loaded = probe.preview_bank(
        "b",
        rows,
        db_ids=frozenset({"id-a", "id-b", "id-c", "id-d"}),
        db_slug_to_id={},
        protected_ids=frozenset(),
    )
    assert probe.load_verdict([loaded]) == probe.VERDICT_NOTHING_NEW


def test_same_slug_same_id_is_not_a_conflict(probe: ModuleType) -> None:
    # 같은 slug가 같은 id로 이미 있으면 갱신 대상이지 충돌이 아니다.
    p = probe.preview_bank(
        "b",
        [probe.BankRow("id-a", "slug-a", True)],
        db_ids=frozenset({"id-a"}),
        db_slug_to_id={"slug-a": "id-a"},
        protected_ids=frozenset(),
    )
    assert (p.in_db_same_id, p.slug_conflict, p.new) == (1, 0, 0)


def test_kv_rejects_undeclared_key(probe: ModuleType) -> None:
    with pytest.raises(KeyError):
        probe.kv("NOT_DECLARED", 1)
