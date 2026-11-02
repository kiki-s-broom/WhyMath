"""P3-32 힌트 연결 런북(`docs/ops/p3_32_hint_link_runbook.md`)과 읽기 전용 프로브의 계약 동결.

이 런북은 **운영 DB에 세 번 쓴다**(재생 · 경로 승격 `--apply` · 힌트 `--apply`). 문서가 사람의 눈 확인에
기대지 않고 구조로 안전하다는 것을 기계로 고정한다.

① **쓰기 가드** — 세 쓰기 명령이 각각 단일 최상위 `if (…) { … } else { "WRITE_REFUSED=True …" }` 안에 있고,
   그 조건이 백업(`$BackupOk`)과 직전 단계 판정을 **다시 검사**한다. 재생은 확인 입력(`$ConfirmOk`)도 본다.
② **표기** — 모든 코드 펜스에 언어 태그가 있고, 실행 블록에 자리표시자·프롬프트 접두·화살표 주석이 없다.
③ **실재** — 런북이 부르는 CLI 플래그·프로브 서브커맨드·프로브가 내는 키가 코드에 실제로 있다.
④ **공유 작업 사본 불간섭** — 체크아웃을 옮기는 git 명령이 없고 `worktree add --detach`를 쓴다.
⑤ **프로브는 쓰지 못한다** — 프로브 소스에 SQL 변이·commit이 없고 읽기 전용 트랜잭션 선언이 있다.
⑥ **프로브 집계** — 개념별 수·판정(READY/PARTIAL/NONE)·요약의 결손 키 처리.

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
_RUNBOOK = _REPO_ROOT / "docs" / "ops" / "p3_32_hint_link_runbook.md"
_PROBE = _REPO_ROOT / "scripts" / "ops" / "p3_32_hint_link_probe.py"
_HINT_PROBE = _REPO_ROOT / "scripts" / "ops" / "p3_81_hint_catalog_probe.py"
_REPLAY = _REPO_ROOT / "src" / "backend" / "whymath_backend" / "whs" / "corpus_replay.py"
_PROMOTION = _REPO_ROOT / "src" / "backend" / "whymath_backend" / "whs" / "path_promotion.py"
_POPULATE = (
    _REPO_ROOT / "src" / "backend" / "whymath_backend" / "l4" / "hint_content" / "populate.py"
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
    return _load(_PROBE, "p3_32_probe_under_test")


@pytest.fixture(scope="module")
def runbook() -> str:
    return _RUNBOOK.read_text(encoding="utf-8")


def _blocks(text: str) -> list[tuple[str, str]]:
    return [(m.group(1).strip(), m.group(2)) for m in _FENCE.finditer(text)]


def _powershell(text: str) -> list[str]:
    return [body for tag, body in _blocks(text) if tag == "powershell"]


# ── ① 쓰기 가드 ─────────────────────────────────────────────────────────

#: 쓰기 명령 패턴 → 그 줄의 `if (…)` 조건이 반드시 참조해야 하는 변수.
_WRITES: dict[str, tuple[str, ...]] = {
    r"whymath_backend\.whs\.corpus_replay\b": ("$BackupOk", "$ConfirmOk", "$BeforeOk"),
    r"whymath_backend\.whs\.path_promotion --apply": ("$BackupOk", "$ReplayOk", "$PromoPlanOk"),
    r"hint_content\.populate --apply": ("$BackupOk", "$PromoOk", "$HintPlanOk"),
}
_IF_LINE = re.compile(r"^if \((?P<cond>[^\n]*?)\) \{ (?P<body>.*) \} else \{ (?P<else>.*) \}$")


def _guard_violations(text: str) -> list[str]:
    """쓰기 명령마다 — 있는가 · 가드 줄 안에 있는가 · 조건이 필요한 변수를 보는가 · 거부 가지가 말하는가."""
    out: list[str] = []
    lines = [line for body in _powershell(text) for line in body.splitlines()]
    for pattern, needed in _WRITES.items():
        hits = [line for line in lines if re.search(pattern, line)]
        if not hits:
            out.append(f"쓰기 명령 없음: {pattern}")
            continue
        for line in hits:
            m = _IF_LINE.match(line.strip())
            if m is None or not re.search(pattern, m.group("body")):
                out.append(f"가드 밖 쓰기: {line.strip()[:80]}")
                continue
            # 조건 변수 — 조건 식에 직접 있거나, 조건이 참조하는 준비 변수(`$…Ready`)의 정의에 있다.
            cond = m.group("cond")
            scope = cond
            for ready in re.findall(r"\$\w+Ready\b", cond):
                defs = [x for x in lines if x.strip().startswith(f"{ready} =")]
                scope += " " + " ".join(defs)
            missing = [v for v in needed if v not in scope]
            if missing:
                out.append(f"가드가 {missing}를 재검사하지 않음: {pattern}")
            # 거부 *문장* 자체에 변수가 있어야 한다 — 같은 가지의 다른 대입(`$X = -1`)은 말이 아니다.
            refusal = re.search(r'"WRITE_REFUSED=True[^"]*"', m.group("else"))
            if refusal is None or "$" not in refusal.group(0):
                out.append(f"거부 가지가 무엇이 False였는지 말하지 않음: {pattern}")
    return out


def test_write_commands_are_guarded(runbook: str) -> None:
    assert _guard_violations(runbook) == []


@pytest.mark.parametrize(
    ("label", "old", "new"),
    [
        # 재생 가드에서 백업 판정을 뺀다
        (
            "replay_without_backup",
            "$ReplayReady = $BackupOk -and $ConfirmOk",
            "$ReplayReady = $ConfirmOk",
        ),
        # 승격 적재를 가드 밖으로 꺼낸다
        (
            "promotion_outside_guard",
            'if ($PromoPlanOk -and $ReplayOk -and $BackupOk) { cmd /c "$Py -m whymath_backend.whs.path_promotion --apply',
            'cmd /c "$Py -m whymath_backend.whs.path_promotion --apply 1> x 2> y"\nif ($PromoPlanOk -and $ReplayOk -and $BackupOk) { cmd /c "$Py -m whymath_backend.whs.path_promotion',
        ),
        # 힌트 적재 가드에서 시험 실행 판정을 뺀다
        (
            "hints_without_plan",
            "if ($HintPlanOk -and $PromoOk -and $BackupOk) {",
            "if ($PromoOk -and $BackupOk) {",
        ),
        # 거부 가지가 침묵한다
        (
            "silent_refusal",
            '"WRITE_REFUSED=True — HINT_PLAN_OK=$HintPlanOk PROMO_OK=$PromoOk BACKUP_OK=$BackupOk · 전부 True여야 힌트를 적재합니다"',
            '"WRITE_REFUSED=True"',
        ),
    ],
)
def test_guard_mutations_are_caught(runbook: str, label: str, old: str, new: str) -> None:
    mutated = runbook.replace(old, new, 1)
    assert mutated != runbook, f"뮤테이션 미적용: {label}"
    assert _guard_violations(mutated), f"뮤테이션 미검출: {label}"


# ── ② 표기 ──────────────────────────────────────────────────────────────


def test_every_fence_has_a_language_tag(runbook: str) -> None:
    assert all(tag for tag, _ in _blocks(runbook))


_PLACEHOLDER = re.compile(r"<[^>\n]*>|여기에_|YOUR_|PLACEHOLDER", re.IGNORECASE)
_PROMPT_PREFIX = re.compile(r"^\s*(PS [A-Z]:\\|PS>|\$ )", re.MULTILINE)
_ARROW_NOTE = re.compile(r"←")


def _notation_violations(text: str) -> list[str]:
    out = []
    for body in _powershell(text):
        code = "\n".join(line for line in body.splitlines() if not line.lstrip().startswith("#"))
        if _PLACEHOLDER.search(code):
            out.append("자리표시자")
        if _PROMPT_PREFIX.search(body):
            out.append("프롬프트 접두")
        if _ARROW_NOTE.search(body):
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


# ── ③ 실재 ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("source", "needle"),
    [
        (_REPLAY, '"--only-existing-problems"'),
        (_REPLAY, '"--no-bad-branch"'),
        (_REPLAY, '"--json"'),
        (_PROMOTION, '"--apply"'),
        (_POPULATE, '"--apply"'),
        (_HINT_PROBE, '"run-summary"'),
        (_HINT_PROBE, '"serve-sample"'),
        (_HINT_PROBE, '"catalog-scan"'),
        (_HINT_PROBE, '"--problems"'),
        (_HINT_PROBE, '"--levels"'),
    ],
)
def test_cli_surfaces_used_by_runbook_exist(source: Path, needle: str) -> None:
    assert needle in source.read_text(encoding="utf-8")


def test_promotion_summary_goes_to_stderr() -> None:
    # 런북 [G]는 표준오류 파일을 요약한다 — CLI가 요약을 표준출력으로 옮기면 [G]가 요약을 못 읽는다.
    text = _PROMOTION.read_text(encoding="utf-8")
    assert re.search(r"print\(json\.dumps\(summary[^\n]*file=sys\.stderr\)", text)


def test_probe_keys_read_by_runbook_exist(runbook: str, probe: ModuleType) -> None:
    hint_probe = _load(_HINT_PROBE, "p3_81_probe_for_p3_32")
    known = set(probe.ALL_KEYS) | set(hint_probe.ALL_KEYS)
    read = set(re.findall(r'(?:Map|BeforeMap|AfterMap)\["([A-Z0-9_]+)"\]', runbook))
    read |= set(re.findall(r'Get-KvInt \$\w+ "([A-Z0-9_]+)"', runbook))
    assert read, "런북이 읽는 키 0건 — 정규식 확인"
    assert sorted(read - known) == []


# ── ④ 공유 작업 사본 불간섭 ───────────────────────────────────────────


def test_no_checkout_moves_and_uses_detached_worktree(runbook: str) -> None:
    code = "\n".join(_powershell(runbook))
    assert not re.search(r"\bgit\b[^\n]*\b(checkout|switch|reset|stash|pull)\b", code)
    assert "git worktree add --detach $Wt origin/main" in code


# ── ⑤ 프로브는 쓰지 못한다 ──────────────────────────────────────────────


def test_probe_is_read_only() -> None:
    text = _PROBE.read_text(encoding="utf-8")
    assert "SET TRANSACTION READ ONLY" in text
    assert not re.search(r"\b(INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|TRUNCATE)\b", text)
    assert ".commit(" not in text


# ── ⑥ 프로브 집계 ──────────────────────────────────────────────────────


def test_measure_link_counts_and_ready(probe: ModuleType) -> None:
    m = probe.measure_link(
        [("A", frozenset({"1", "2", "3"})), ("B", frozenset({"4"}))],
        in_db=frozenset({"1", "2", "4"}),
        replayable_by_bank={"bank_x": frozenset({"1", "9"}), "bank_y": frozenset({"4"})},
        with_solution=frozenset({"1"}),
        with_path=frozenset({"1"}),
        with_hint=frozenset(),
    )
    a, b = m.concepts
    assert (a.eligible, a.in_db, a.replayable_in_db, a.verified_solution) == (3, 2, 1, 1)
    assert (b.eligible, b.in_db, b.replayable_in_db) == (1, 1, 1)
    assert m.replay_banks == ("bank_x", "bank_y")
    assert m.verdict == probe.VERDICT_READY


def test_measure_link_partial_and_none(probe: ModuleType) -> None:
    common = {
        "replayable_by_bank": {"bank_x": frozenset({"1"})},
        "with_solution": frozenset(),
        "with_path": frozenset(),
        "with_hint": frozenset(),
    }
    partial = probe.measure_link(
        [("A", frozenset({"1"})), ("B", frozenset({"2"}))], in_db=frozenset({"1", "2"}), **common
    )
    assert partial.verdict == probe.VERDICT_PARTIAL
    none = probe.measure_link([("A", frozenset({"1"}))], in_db=frozenset(), **common)
    assert none.verdict == probe.VERDICT_NONE
    assert none.replay_banks == ()


def test_measure_link_excludes_banks_without_wanted_problems(probe: ModuleType) -> None:
    # 핵심 개념 문항이 없는 은행은 재생 목록에 넣지 않는다.
    m = probe.measure_link(
        [("A", frozenset({"1"}))],
        in_db=frozenset({"1", "7"}),
        replayable_by_bank={"core": frozenset({"1"}), "other": frozenset({"7"})},
        with_solution=frozenset(),
        with_path=frozenset(),
        with_hint=frozenset(),
    )
    assert m.replay_banks == ("core",)


def test_emit_link_uses_declared_keys(
    probe: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    m = probe.measure_link(
        [("H:12미적Ⅰ02-09", frozenset({"1"}))],
        in_db=frozenset({"1"}),
        replayable_by_bank={"b": frozenset({"1"})},
        with_solution=frozenset({"1"}),
        with_path=frozenset({"1"}),
        with_hint=frozenset({"1"}),
    )
    probe.emit_link(m)
    out = capsys.readouterr().out
    assert out.isascii()
    assert "CONCEPTS_HINT_LINKED=1" in out
    assert "VERDICT=READY" in out


def test_summarize_missing_key_is_not_wellformed(probe: ModuleType) -> None:
    full = {
        "total_records": 3,
        "replayed": 3,
        "finalized_verified": 3,
        "finalized_other": 0,
        "skipped_problem_missing": 2,
        "failures": [],
    }
    pairs = dict(probe.summarize("replay", full))
    assert pairs["SUMMARY_WELLFORMED"] is True
    assert pairs["REPLAY_SKIPPED_MISSING"] == 2
    del full["skipped_problem_missing"]
    pairs = dict(probe.summarize("replay", full))
    # 빠진 키는 0으로 읽지 않는다
    assert pairs["SUMMARY_WELLFORMED"] is False
    assert pairs["REPLAY_SKIPPED_MISSING"] == "missing"


def test_summary_reads_last_json_line_with_bom(
    probe: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # 승격 CLI의 표준오류 파일 — 앞줄 로그 + 끝줄 JSON, PowerShell 5.1이 BOM을 붙일 수 있다.
    path = tmp_path / "promo.json"
    path.write_text(
        "\ufeffWARNING something\n"
        '{"mode": "apply", "total_input": 5, "promoted": 4, "already_promoted": 1,'
        ' "skipped_problem_missing": 0, "queued_approach_unmappable": 0,'
        ' "pydantic_rejected": 0, "failures": []}\n',
        encoding="utf-8",
    )
    rc = probe.main(["summary", "--kind", "promotion", "--json", str(path)])
    out = capsys.readouterr().out
    assert rc == probe.EXIT_OK
    assert "PROMO_PROMOTED=4" in out
    assert "SUMMARY_WELLFORMED=True" in out


def test_summary_empty_file_is_unmeasured(
    probe: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "empty.json"
    path.write_text("", encoding="utf-8")
    assert probe.main(["summary", "--kind", "replay", "--json", str(path)]) == probe.EXIT_UNMEASURED
    assert "PROBE_ERROR=" in capsys.readouterr().out
