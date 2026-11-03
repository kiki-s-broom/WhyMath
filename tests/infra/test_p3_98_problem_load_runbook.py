"""P3-98 문항은행 적재 런북(`docs/ops/p3_98_problem_load_runbook.md`)과 읽기 전용 프로브의 계약 동결.

이 런북은 **운영 DB에 한 번 쓴다**(은행별 `l1.problem_bank.populate --problems`). 문서가 사람의 눈 확인에
기대지 않고 구조로 안전하다는 것을 기계로 고정한다.

① **쓰기 가드** — 적재 명령이 단일 최상위 `if (…) { … } else { "WRITE_REFUSED=True …" }` 안에 있고, 그
   조건이 백업(`$BackupOk`)·확인 입력(`$ConfirmOk`)·적재 전 판정(`$BeforeOk`)을 **다시 검사**한다.
② **대상 고정** — 적재 대상은 두 은행뿐이고 `--all`(전 코퍼스 적재)을 쓰지 않는다.
③ **표기** — 모든 코드 펜스에 언어 태그가 있고, 실행 블록에 자리표시자·프롬프트 접두·화살표 주석이 없다.
④ **실재** — 런북이 부르는 CLI 플래그·프로브가 내는 키가 코드에 실제로 있다.
⑤ **공유 작업 사본 불간섭** · **새 증거 폴더** — 체크아웃을 옮기지 않고, 증거 폴더 이름에 실행 시각이 있다.
⑥ **프로브는 쓰지 못한다** — 프로브 소스에 SQL 변이·commit이 없고 읽기 전용 트랜잭션 선언이 있다.
⑦ **프로브 분류** — 새 행·이미 있음·ID 이탈·기본키 충돌·보호 행과 판정(READY/DONE/BLOCKED).

뮤테이션은 런북 **텍스트의 메모리 사본**에 가하고, 주입이 실제로 적용됐는지(`mutated != original`)를 먼저
단언한다.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUNBOOK = _REPO_ROOT / "docs" / "ops" / "p3_98_problem_load_runbook.md"
_PROBE = _REPO_ROOT / "scripts" / "ops" / "p3_98_problem_load_probe.py"
_LINK_PROBE = _REPO_ROOT / "scripts" / "ops" / "p3_32_hint_link_probe.py"
_POPULATE = (
    _REPO_ROOT / "src" / "backend" / "whymath_backend" / "l1" / "problem_bank" / "populate.py"
)
_BANKS = (
    "data/corpus/problem_bank_p3_calculus1_diff_v0/problems.jsonl",
    "data/corpus/problem_bank_p3_fill_v0/problems.jsonl",
)

_FENCE = re.compile(r"^```([^\n`]*)\n(.*?)^```", re.MULTILINE | re.DOTALL)


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def probe() -> ModuleType:
    return _load(_PROBE, "p3_98_probe_under_test")


@pytest.fixture(scope="module")
def runbook() -> str:
    return _RUNBOOK.read_text(encoding="utf-8")


def _blocks(text: str) -> list[tuple[str, str]]:
    return [(m.group(1).strip(), m.group(2)) for m in _FENCE.finditer(text)]


def _powershell(text: str) -> list[str]:
    return [body for tag, body in _blocks(text) if tag == "powershell"]


# ── ① 쓰기 가드 ─────────────────────────────────────────────────────────

_WRITE = re.compile(r"whymath_backend\.l1\.problem_bank\.populate\b")
_NEEDED = ("$BackupOk", "$ConfirmOk", "$BeforeOk")
_IF_LINE = re.compile(r"^if \((?P<cond>[^\n]*?)\) \{ (?P<body>.*) \} else \{ (?P<else>.*) \}$")


def _guard_violations(text: str) -> list[str]:
    """적재 명령이 있는가 · 가드 줄 안에 있는가 · 조건이 필요한 변수를 보는가 · 거부 가지가 말하는가."""
    out: list[str] = []
    lines = [line for body in _powershell(text) for line in body.splitlines()]
    hits = [line for line in lines if _WRITE.search(line)]
    if not hits:
        return ["적재 명령 없음"]
    for line in hits:
        m = _IF_LINE.match(line.strip())
        if m is None or not _WRITE.search(m.group("body")):
            out.append(f"가드 밖 쓰기: {line.strip()[:80]}")
            continue
        cond = m.group("cond")
        scope = cond
        for ready in re.findall(r"\$\w+Ready\b", cond):
            defs = [x for x in lines if x.strip().startswith(f"{ready} =")]
            scope += " " + " ".join(defs)
        missing = [v for v in _NEEDED if v not in scope]
        if missing:
            out.append(f"가드가 {missing}를 재검사하지 않음")
        refusal = re.search(r'"WRITE_REFUSED=True[^"]*"', m.group("else"))
        if refusal is None or "$" not in refusal.group(0):
            out.append("거부 가지가 무엇이 False였는지 말하지 않음")
    # 적재 전 판정이 READY와 차단 사유 0을 실제로 요구하는가 — 가드가 보는 변수의 *내용*.
    before = [x for x in lines if x.strip().startswith("$BeforeOk =")]
    if not before:
        out.append("$BeforeOk 정의 없음")
    else:
        for needle in ('-ceq "READY"', '"PK_COLLISION"', '"ID_DRIFT"', '"SRC_UNRESOLVED"'):
            if needle not in before[0]:
                out.append(f"$BeforeOk가 {needle}를 보지 않음")
    return out


def test_write_command_is_guarded(runbook: str) -> None:
    assert _guard_violations(runbook) == []


@pytest.mark.parametrize(
    ("label", "old", "new"),
    [
        (
            "load_without_backup",
            "$LoadReady = $BackupOk -and $ConfirmOk",
            "$LoadReady = $ConfirmOk",
        ),
        (
            "load_without_confirm",
            "$LoadReady = $BackupOk -and $ConfirmOk",
            "$LoadReady = $BackupOk",
        ),
        (
            "load_outside_guard",
            "if ($LoadReady) { $T0 = Get-Date;",
            "& $Py -m whymath_backend.l1.problem_bank.populate --all\nif ($LoadReady) { $T0 = Get-Date;",
        ),
        ("before_ignores_collision", '-and ((Get-KvInt $BeforeMap "PK_COLLISION") -eq 0) ', " "),
        ("before_accepts_any_verdict", '($Verdict -ceq "READY")', "($true)"),
        (
            "silent_refusal",
            '"WRITE_REFUSED=True — BACKUP_OK=$BackupOk CONFIRMED=$ConfirmOk WT_OK=$WtOk CODE_OK=$CodeOk BEFORE_OK=$BeforeOk REACH_EXIT=$ReachExit · 전부 True/0이어야 적재합니다. [B]~[E]를 같은 창에서 순서대로 실행하세요"',
            '"WRITE_REFUSED=True"',
        ),
    ],
)
def test_guard_mutations_are_caught(runbook: str, label: str, old: str, new: str) -> None:
    mutated = runbook.replace(old, new, 1)
    assert mutated != runbook, f"뮤테이션 미적용: {label}"
    assert _guard_violations(mutated), f"뮤테이션 미검출: {label}"


# ── ② 대상 고정 ─────────────────────────────────────────────────────────


def _target_violations(text: str) -> list[str]:
    code = "\n".join(_powershell(text))
    out = []
    if re.search(r"problem_bank\.populate[^\n]*--all\b", code):
        out.append("--all 적재")
    m = re.search(r"^\$BankRel = @\((?P<items>[^)]*)\)$", code, re.MULTILINE)
    if m is None:
        return out + ["$BankRel 정의 없음"]
    listed = tuple(re.findall(r'"([^"]+)"', m.group("items")))
    if listed != _BANKS:
        out.append(f"적재 대상이 고정 목록과 다르다: {listed}")
    return out


def test_targets_are_the_two_banks_only(runbook: str) -> None:
    assert _target_violations(runbook) == []
    for rel in _BANKS:
        assert (_REPO_ROOT / rel).is_file(), rel


def test_target_mutations_are_caught(runbook: str) -> None:
    widened = runbook.replace(
        '"data/corpus/problem_bank_p3_fill_v0/problems.jsonl")',
        '"data/corpus/problem_bank_p3_fill_v0/problems.jsonl", "data/corpus/problem_bank_rephrased_v0/problems.jsonl")',
        1,
    )
    assert widened != runbook
    assert _target_violations(widened)
    all_load = runbook.replace("populate --problems $R", "populate --all", 1)
    assert all_load != runbook
    assert _target_violations(all_load)


# ── ③ 표기 ──────────────────────────────────────────────────────────────


def test_every_fence_has_a_language_tag(runbook: str) -> None:
    assert all(tag for tag, _ in _blocks(runbook))


_PLACEHOLDER = re.compile(r"<[^>\n]*>|여기에_|YOUR_|PLACEHOLDER", re.IGNORECASE)
_PROMPT_PREFIX = re.compile(r"^\s*(PS [A-Z]:\\|PS>|\$ )", re.MULTILINE)


def _notation_violations(text: str) -> list[str]:
    out = []
    for body in _powershell(text):
        code = "\n".join(line for line in body.splitlines() if not line.lstrip().startswith("#"))
        if _PLACEHOLDER.search(code):
            out.append("자리표시자")
        if _PROMPT_PREFIX.search(body):
            out.append("프롬프트 접두")
        if "←" in body:
            out.append("화살표 주석")
    return out


def test_no_placeholders_prompts_or_arrows(runbook: str) -> None:
    assert _notation_violations(runbook) == []


def test_notation_mutation_is_caught(runbook: str) -> None:
    mutated = runbook.replace(
        "cd C:\\Users\\kiki\\Desktop\\__AI\\WhyMath\ngit fetch origin main",
        "cd <작업 폴더>\ngit fetch origin main",
        1,
    )
    assert mutated != runbook
    assert _notation_violations(mutated)


def test_confirm_prompt_is_alone_in_its_block(runbook: str) -> None:
    blocks = [b for b in _powershell(runbook) if "Read-Host" in b]
    assert len(blocks) == 1
    code = [
        line
        for line in blocks[0].splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert len(code) == 1


# ── ④ 실재 ──────────────────────────────────────────────────────────────


def test_populate_has_problems_flag() -> None:
    assert '"--problems"' in _POPULATE.read_text(encoding="utf-8")


def test_link_probe_has_link_subcommand() -> None:
    assert '"link"' in _LINK_PROBE.read_text(encoding="utf-8")


def test_probe_keys_read_by_runbook_exist(runbook: str, probe: ModuleType) -> None:
    link = _load(_LINK_PROBE, "p3_32_probe_for_p3_98")
    known = set(probe.ALL_KEYS) | set(link.ALL_KEYS)
    read = set(re.findall(r'(?:BeforeMap|AfterMap|HandoffMap)\["([A-Z0-9_]+)"\]', runbook))
    read |= set(re.findall(r'Get-KvInt \$\w+ "([A-Z0-9_]+)"', runbook))
    assert read, "런북이 읽는 키 0건 — 정규식 확인"
    assert sorted(read - known) == []


# ── ⑤ 공유 작업 사본 불간섭 · 새 증거 폴더 ────────────────────────────


def test_no_checkout_moves_and_uses_detached_worktree(runbook: str) -> None:
    code = "\n".join(_powershell(runbook))
    assert not re.search(r"\bgit\b[^\n]*\b(checkout|switch|reset|stash|pull)\b", code)
    assert "git worktree add --detach $Wt origin/main" in code


def test_evidence_folder_is_fresh_per_run(runbook: str) -> None:
    # 지난 실행의 파일을 이번 결과로 읽지 않게 — 폴더 이름에 실행 시각이 들어가야 한다.
    code = "\n".join(_powershell(runbook))
    assert re.search(r'^\$Stamp = Get-Date -Format "yyyyMMddHHmmss"$', code, re.MULTILINE)
    assert re.search(r"^\$OutDir = [^\n]*\$Stamp$", code, re.MULTILINE)


# ── ⑥ 프로브는 쓰지 못한다 ──────────────────────────────────────────────


def test_probe_is_read_only() -> None:
    text = _PROBE.read_text(encoding="utf-8")
    assert "SET TRANSACTION READ ONLY" in text
    assert not re.search(r"\b(INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|TRUNCATE)\b", text)
    assert ".commit(" not in text
    assert ".populate(" not in text  # 적재기의 쓰기 메서드를 부르지 않는다(해석 함수만)


# ── ⑦ 프로브 분류 ──────────────────────────────────────────────────────


def _row(probe: ModuleType, pid: str, slug: str, protected: bool = False):  # type: ignore[no-untyped-def]
    return probe.DbRow(problem_id=pid, slug=slug, protected=protected)


def test_classify_counts_each_kind(probe: ModuleType) -> None:
    bank = probe.BankRows(
        path="b",
        rows=(
            ("s-present", "1"),
            ("s-new", "2"),
            ("s-drift", "3"),
            ("s-collide", "4"),
            ("s-prot", "5"),
        ),
    )
    db = [
        _row(probe, "1", "s-present"),
        _row(probe, "99", "s-drift"),  # 같은 slug · 다른 id
        _row(probe, "4", "other-slug"),  # 같은 id · 다른 slug
        _row(probe, "5", "s-prot", protected=True),
    ]
    by_slug = {r.slug: r for r in db}
    by_id = {r.problem_id: r for r in db}
    c = probe.classify_bank(bank, by_slug, by_id)
    assert (c.rows, c.present, c.new, c.id_drift, c.pk_collision, c.protected) == (5, 2, 1, 1, 1, 1)
    assert c.new_ids == frozenset({"2"})


def test_verdict_ready_done_blocked(probe: ModuleType) -> None:
    eligible = [("A", frozenset({"1", "2"})), ("B", frozenset({"3"}))]
    bank = probe.BankRows(path="b", rows=(("s1", "1"), ("s3", "3")))
    ready = probe.measure_load(
        [bank],
        [_row(probe, "1", "s1")],
        eligible,
        src_needed=frozenset({"x"}),
        src_resolved=frozenset({"x"}),
    )
    assert ready.verdict == "READY"
    assert ready.concepts == (("A", 2, 1, 1), ("B", 1, 0, 1))
    done = probe.measure_load(
        [bank],
        [_row(probe, "1", "s1"), _row(probe, "3", "s3")],
        eligible,
        src_needed=frozenset({"x"}),
        src_resolved=frozenset({"x"}),
    )
    assert done.verdict == "DONE"
    unresolved = probe.measure_load(
        [bank],
        [],
        eligible,
        src_needed=frozenset({"x", "y"}),
        src_resolved=frozenset({"x"}),
    )
    assert unresolved.verdict == "BLOCKED"
    assert unresolved.block_reasons == ("SRC_UNRESOLVED",)


def test_blocked_rows_are_not_predicted(probe: ModuleType) -> None:
    """ID 이탈·충돌 행은 적재해도 코퍼스 ID로 생기지 않는다 — 예측에 넣으면 거짓 10/10이 된다."""
    eligible = [("A", frozenset({"7"})), ("B", frozenset({"8"}))]
    bank = probe.BankRows(path="b", rows=(("s7", "7"), ("s8", "8")))
    m = probe.measure_load(
        [bank],
        [_row(probe, "70", "s7"), _row(probe, "8", "elsewhere")],
        eligible,
        src_needed=frozenset(),
        src_resolved=frozenset(),
    )
    assert m.verdict == "BLOCKED"
    assert set(m.block_reasons) == {"ID_DRIFT", "PK_COLLISION"}
    assert [c[3] for c in m.concepts] == [0, 1]  # B의 8은 다른 slug로 *이미* DB에 있다(지금 1)


def test_emit_uses_declared_keys(probe: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    bank = probe.BankRows(path="data/x.jsonl", rows=(("s1", "1"),))
    m = probe.measure_load(
        [bank],
        [],
        [("H:12미적Ⅰ02-01", frozenset({"1"}))],
        src_needed=frozenset(),
        src_resolved=frozenset(),
    )
    probe.emit_measure(m, 0)
    out = capsys.readouterr().out
    assert out.isascii()
    keys = {line.split("=", 1)[0] for line in out.splitlines()}
    assert keys <= set(probe.ALL_KEYS)
    assert "VERDICT=READY" in out and "NEW_ROWS=1" in out and "PREDICTED_CONCEPTS_IN_DB=1" in out


def test_kv_rejects_undeclared_key(probe: ModuleType) -> None:
    with pytest.raises(KeyError):
        probe.kv("NOT_A_KEY", 1)


def test_measure_without_bank_is_unmeasured(
    probe: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    assert probe.main(["measure"]) == probe.EXIT_UNMEASURED
    assert "PROBE_ERROR=" in capsys.readouterr().out
