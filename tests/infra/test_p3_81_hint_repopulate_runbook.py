"""P3-81 힌트 재적재 런북(`docs/ops/p3_81_hint_repopulate_runbook.md`)과 읽기 전용 프로브의 계약 동결.

이 런북은 **운영 DB에 쓴다**(`populate --apply`). 그래서 문서가 사람의 눈 확인에 기대지 않고 구조로 안전하다는
것을 기계로 고정한다. 막는 것은 다섯이다.

① **쓰기 블록의 가드** — `--apply`가 단일 최상위 `if ($ApplyReady) { … } else { …REFUSED… }` 안에만 있고,
   `$ApplyReady`가 dry-run 판정(`$DryOk`)·백업(`$BackupOk`)·확인 입력(`$ConfirmOk`)·코드 출처(`$CodeOk`)·
   worktree(`$WtOk`)·적재 전 실측(`$BeforeOk`)·DB 도달(`$ReachExit`)을 **전부 재검사**한다. 거부 가지는 그 변수들을
   출력한다(침묵 가드는 위장이다).
② **표기** — 모든 코드 펜스에 언어 태그가 있고, 자리표시자·프롬프트 접두·출력 줄·화살표 주석이 실행 블록에 없다.
③ **실재** — 런북이 부르는 CLI 인자(`populate`의 `--apply`)·모듈 경로·프로브 서브커맨드/플래그·프로브가 읽는 키가 코드에
   실제로 있다. 문서가 코드와 어긋나면 Kiki 머신에서 `argparse` 오류나 `-1`(없음)로 읽혀 조용히 어긋난다.
④ **공유 작업 사본 불간섭** — 체크아웃을 옮기는 git 명령이 없고 `worktree add --detach`를 쓴다.
⑤ **프로브는 쓰지 못한다** — 프로브 소스에 SQL 변이·commit이 없고 읽기 전용 트랜잭션 선언이 있다.

**절마다 그 절을 밟는 뮤테이션을 둔다**(CLAUDE.md 「픽스처가 그 절을 실제로 밟는가」). 뮤테이션은 런북 **텍스트의
메모리 사본**에 가하고(원본 파일·git 작업 트리는 건드리지 않는다), 주입이 실제로 적용됐는지(`mutated != original`)를
먼저 단언한다 — 주입이 안 들어갔는데 "검출"로 보이는 위장을 막는다. 정상 문서는 모든 검사가 통과해야 하고(green 대조군),
뮤테이션은 **그 절을 담당하는 검사만이** 잡아야 한다.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUNBOOK = _REPO_ROOT / "docs" / "ops" / "p3_81_hint_repopulate_runbook.md"
_PROBE = _REPO_ROOT / "scripts" / "ops" / "p3_81_hint_catalog_probe.py"
_SCANNER = _REPO_ROOT / "scripts" / "ops" / "check_runbook_blocks.py"
_BACKEND_SRC = _REPO_ROOT / "src" / "backend"
_POPULATE = _BACKEND_SRC / "whymath_backend" / "l4" / "hint_content" / "populate.py"
_CMS_MARKER = _BACKEND_SRC / "whymath_backend" / "db" / "cms_edit_marker.py"

_LABEL = "# [Windows PowerShell · Phaiakes9]"
_CLONE_CD = r"cd C:\Users\kiki\Desktop\__AI\WhyMath"


def _load_probe() -> ModuleType:
    spec = importlib.util.spec_from_file_location("p3_81_hint_catalog_probe", _PROBE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_probe = _load_probe()


# ── 런북 파싱 ──────────────────────────────────────────────────────────────


def _fences(text: str) -> list[tuple[str, str, int]]:
    """(언어 태그, 본문, 여는 줄 번호) 목록. 닫히지 않은 펜스는 태그 `<UNCLOSED>`로 남긴다."""
    out: list[tuple[str, str, int]] = []
    info: str | None = None
    start = 0
    body: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if info is None:
            match = re.match(r"^```(\S*)\s*$", line)
            if match:
                info, start, body = match.group(1), number, []
            continue
        if re.match(r"^```\s*$", line):
            out.append((info, "\n".join(body), start))
            info = None
            continue
        body.append(line)
    if info is not None:
        out.append(("<UNCLOSED>", "\n".join(body), start))
    return out


def _blocks(text: str) -> list[str]:
    return [body for tag, body, _ in _fences(text) if tag == "powershell"]


def _code_lines(block: str) -> list[str]:
    return [
        line for line in block.splitlines() if line.strip() and not line.lstrip().startswith("#")
    ]


# ── 검사 함수(문서 텍스트 → 위반 목록). 정상 문서는 전부 빈 목록이어야 한다 ──────────


def check_fence_tags(text: str) -> list[str]:
    """모든 코드 펜스가 `powershell` 태그 — 태그 없는 펜스는 실행 대상으로 읽힌다."""
    return [f"{line}행 펜스 태그 `{tag}`" for tag, _, line in _fences(text) if tag != "powershell"]


_PROMPT_PREFIX = re.compile(r"^\s*(?:PS[^>\n]*>|\$ )")


def check_block_notation(text: str) -> list[str]:
    """자리표시자·프롬프트 접두·출력 줄·화살표·생략 문자 금지, 시스템 라벨 필수."""
    problems: list[str] = []
    for index, block in enumerate(_blocks(text), start=1):
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines or not lines[0].startswith(_LABEL):
            problems.append(f"블록 #{index}: 첫 줄이 시스템 라벨 주석이 아니다")
        for line in block.splitlines():
            if "여기에_" in line:
                problems.append(f"블록 #{index}: 자리표시자 `여기에_` — {line.strip()[:50]}")
            if re.search(r"<[A-Za-z가-힣_][^<>\n]*>", line):
                problems.append(f"블록 #{index}: 꺾쇠 자리표시자 — {line.strip()[:50]}")
            if "…" in line:
                problems.append(f"블록 #{index}: 생략 문자 `…` — {line.strip()[:50]}")
            if re.search(r"[←→]", line):
                problems.append(f"블록 #{index}: 화살표 주석 — {line.strip()[:50]}")
            if _PROMPT_PREFIX.match(line):
                problems.append(f"블록 #{index}: 프롬프트 접두 — {line.strip()[:50]}")
    blocks = _blocks(text)
    if len(blocks) < 2 or not all(_CLONE_CD in blocks[i] for i in (0, 1)):
        problems.append("A·B 블록이 고정 작업 디렉터리로 `cd`하지 않는다")
    return problems


_DRY_REQUIRED = ("$WtOk", "$CodeOk", "$BeforeOk", "$ReachExit")
_APPLY_REQUIRED = ("$DryOk", "$BackupOk", "$ConfirmOk", *_DRY_REQUIRED)
_GUARDED_LINE = re.compile(
    r"^if \((?P<cond>[^\n]*?)\) \{ (?P<body>.*?) \} else \{ (?P<other>.*) \}$"
)


def _populate_lines(block: str) -> list[str]:
    return [line for line in block.splitlines() if "hint_content.populate" in line]


def _check_guarded_line(
    block: str, line: str, ready_var: str, required: tuple[str, ...]
) -> list[str]:
    problems: list[str] = []
    match = _GUARDED_LINE.match(line.strip())
    if not match:
        shown = line.strip()[:60]
        return ["`" + shown + "` — 단일 최상위 `if` 한 줄 가드(`} else {` 포함)가 아니다"]
    if match.group("cond").strip() != f"${ready_var}":
        problems.append(f"가드 조건이 `${ready_var}` 하나가 아니다: {match.group('cond')}")
    if "hint_content.populate" not in match.group("body"):
        problems.append("실행이 가드의 참 가지 안에 없다")
    if "REFUSED=True" not in match.group("other"):
        problems.append("거부 가지가 `REFUSED=True`를 출력하지 않는다(침묵 가드)")
    for var in required:
        if var not in match.group("other"):
            problems.append(
                f"거부 가지가 {var} 값을 출력하지 않는다(무엇이 False인지 말하지 않는다)"
            )
    ready = re.search(rf"^\${ready_var} = (?P<expr>.+)$", block, re.M)
    if ready is None:
        problems.append(f"`${ready_var}` 판정 대입이 같은 블록에 없다")
    else:
        for var in required:
            if var not in ready.group("expr"):
                problems.append(f"`${ready_var}`가 {var}를 재검사하지 않는다")
    return problems


def check_write_guards(text: str) -> list[str]:
    """`populate` 실행(dry-run·`--apply`)은 전부 자가거부 가드 안에 있고, 쓰기는 정확히 한 곳이다."""
    problems: list[str] = []
    blocks = _blocks(text)
    apply_blocks = [b for b in blocks if "--apply" in b]
    runs = [(b, line) for b in blocks for line in _populate_lines(b)]
    if sum(b.count("--apply") for b in blocks) != 1 or len(apply_blocks) != 1:
        problems.append("`--apply`는 코드 블록 전체에서 정확히 1회, 1개 블록에만 있어야 한다")
    if len(runs) != 2:
        problems.append(f"populate 실행 줄이 정확히 2개(dry-run·apply)여야 한다: {len(runs)}")
    for block, line in runs:
        if "--apply" in line:
            problems += _check_guarded_line(block, line, "ApplyReady", _APPLY_REQUIRED)
            if "--overwrite-cms-edits" in line:
                problems.append(
                    "적재 줄이 `--overwrite-cms-edits`를 쓴다(편집 소실은 Kiki 결정 사항)"
                )
            if '$ConfirmOk = ($Confirm -ceq "APPLY")' not in block:
                problems.append('적재 블록이 `$Confirm -ceq "APPLY"` 확인 판정을 하지 않는다')
        else:
            problems += _check_guarded_line(block, line, "DryReady", _DRY_REQUIRED)
    # 확인 입력 블록은 혼자여야 한다 — 입력 대기 중 붙여넣은 다음 줄이 입력으로 먹히는 것을 막는다.
    confirm_blocks = [b for b in blocks if "Read-Host" in b]
    if len(confirm_blocks) != 1 or len(_code_lines(confirm_blocks[0])) != 1:
        problems.append("`Read-Host`는 한 줄짜리 블록 하나에만 있어야 한다")
    # 순서: dry-run → 백업 → 확인 → 적재
    positions = {
        key: next((i for i, b in enumerate(blocks) if marker in b), -1)
        for key, marker in (
            ("dry", "$DryReady ="),
            ("backup", "$BackupOk ="),
            ("confirm", "Read-Host"),
            ("apply", "$ApplyReady ="),
        )
    }
    ordered = [positions[k] for k in ("dry", "backup", "confirm", "apply")]
    if -1 in ordered or ordered != sorted(ordered) or len(set(ordered)) != 4:
        problems.append(f"블록 순서가 dry-run → 백업 → 확인 → 적재가 아니다: {positions}")
    # DB를 SQL로 바꾸는 우회 경로 금지
    all_code = "\n".join(blocks)
    if re.search(
        r"\b(?:insert\s+into|update\s+\w+\s+set|delete\s+from|truncate|drop\s+table)\b",
        all_code,
        re.I,
    ):
        problems.append(
            "런북 코드 블록에 SQL 변이가 있다(적재는 populate --apply 하나뿐이어야 한다)"
        )
    return problems


def check_shared_clone_untouched(text: str) -> list[str]:
    """공유 클론의 체크아웃·미커밋 변경을 건드리는 명령 금지 + worktree 우회·코드 출처 확인."""
    problems: list[str] = []
    code = "\n".join(_blocks(text))
    for pattern in (
        r"git\s+checkout\b",
        r"git\s+switch\b",
        r"git\s+reset\b",
        r"git\s+restore\b",
        r"git\s+stash\b",
        r"git\s+clean\b",
        r"git\s+pull\b",
    ):
        if re.search(pattern, code):
            problems.append(f"공유 클론을 바꾸는 명령 `{pattern}`")
    if "git worktree add --detach $Wt origin/main" not in code:
        problems.append("`git worktree add --detach … origin/main` 우회가 없다")
    for needle in ("$HasProbe", "$HasValueAxis", "$WtClean", "$WtHead -eq $MainSha"):
        wt_ok = re.search(r"^\$WtOk = (?P<expr>.+)$", code, re.M)
        if wt_ok is None or needle not in wt_ok.group("expr"):
            problems.append(f"`$WtOk`가 {needle}를 재검사하지 않는다")
    # 코드 출처 동결 — import된 파일의 경로가 worktree 아래인지 본다.
    code_ok = re.search(r"^\$CodeOk = (?P<expr>.+)$", code, re.M)
    if code_ok is None:
        problems.append("`$CodeOk`(실행 코드 출처 확인)가 없다")
    else:
        for key in ("CODE_POPULATE", "CODE_STORE", "CODE_PROBE"):
            if f'$BeforeMap["{key}"] -like "$Wt\\*"' not in code_ok.group("expr"):
                problems.append(f"`$CodeOk`가 {key} 경로를 worktree와 대조하지 않는다")
    return problems


def _populate_flags() -> set[str]:
    """`populate.py`가 argparse에 선언한 플래그 — AST로 읽는다(백엔드 의존성 불요)."""
    flags: set[str] = set()
    tree = ast.parse(_POPULATE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
        ):
            flags |= {
                arg.value
                for arg in node.args
                if isinstance(arg, ast.Constant)
                and isinstance(arg.value, str)
                and arg.value.startswith("--")
            }
    marker = ast.parse(_CMS_MARKER.read_text(encoding="utf-8"))
    for node in ast.walk(marker):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "OVERWRITE_FLAG"
            and isinstance(node.value, ast.Constant)
        ):
            flags.add(str(node.value.value))
    return flags


def _probe_subcommands() -> dict[str, set[str]]:
    parser = _probe.build_parser()
    group = next(a for a in parser._actions if hasattr(a, "choices") and a.choices)
    return {
        name: {opt for opt in sub._option_string_actions if opt.startswith("--")}
        for name, sub in group.choices.items()
    }


def _module_exists(dotted: str) -> bool:
    base = _BACKEND_SRC / dotted.replace(".", "/")
    return base.with_suffix(".py").is_file() or (base / "__init__.py").is_file()


def check_cli_and_paths_exist(text: str) -> list[str]:
    """런북이 부르는 populate 플래그·모듈 경로·프로브 경로/서브커맨드/플래그가 코드에 실재한다."""
    problems: list[str] = []
    code = "\n".join(_blocks(text))
    declared = _populate_flags()
    if "--apply" not in declared:
        problems.append("populate.py에 `--apply`가 선언돼 있지 않다(런북이 가정하는 인자)")
    for _, line in ((b, ln) for b in _blocks(text) for ln in _populate_lines(b)):
        used = set(
            re.findall(r"(?<![\w-])--[a-z][a-z0-9-]*", line.split("hint_content.populate", 1)[1])
        )
        for flag in sorted(used - declared):
            problems.append(f"populate에 없는 인자 `{flag}`")
    for dotted in sorted(set(re.findall(r"whymath_backend(?:\.[a-z0-9_]+)+", code))):
        if not _module_exists(dotted):
            problems.append(f"존재하지 않는 모듈 `{dotted}`")
    probe_paths = set(re.findall(r"scripts\\ops\\([A-Za-z0-9_]+\.py)", code))
    if probe_paths != {_PROBE.name}:
        problems.append(f"런북이 가리키는 프로브 파일이 {_PROBE.name}이 아니다: {probe_paths}")
    subs = _probe_subcommands()
    invocations = re.findall(r"\$Probe\s+([a-z][a-z-]*)([^\n]*)", code)
    if not invocations:
        problems.append("`$Probe <서브커맨드>` 호출이 하나도 없다(스캔 0건)")
    for sub, rest in invocations:
        if sub not in subs:
            problems.append(f"프로브에 없는 서브커맨드 `{sub}`")
            continue
        for flag in re.findall(r"(?<![\w-])--[a-z][a-z0-9-]*", rest):
            if flag not in subs[sub]:
                problems.append(f"프로브 `{sub}`에 없는 플래그 `{flag}`")
    used_subs = {sub for sub, _ in invocations}
    for needed in ("stats", "run-summary", "serve-sample", "catalog-scan"):
        if needed not in used_subs:
            problems.append(f"런북이 프로브 `{needed}`를 쓰지 않는다")
    return problems


_KEY_LITERAL = re.compile(r'"([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+(?:\$L)?)"')


def check_probe_keys_exist(text: str) -> list[str]:
    """PowerShell이 이름으로 읽는 프로브 키가 프로브의 출력 키 선언(`ALL_KEYS`)에 있다."""
    problems: list[str] = []
    keys: set[str] = set()
    for literal in _KEY_LITERAL.findall("\n".join(_blocks(text))):
        if literal.endswith("$L"):
            keys |= {literal[:-2] + str(level) for level in (1, 2, 3)}
        else:
            keys.add(literal)
    keys |= {
        f"{m.group(1)}{level}"
        for m in re.finditer(r'"([A-Z][A-Z0-9_]*_L)\$L"', "\n".join(_blocks(text)))
        for level in (1, 2, 3)
    }
    if len(keys) < 15:
        problems.append(f"런북이 읽는 프로브 키가 {len(keys)}개뿐이다(스캔이 비정상적으로 적다)")
    for key in sorted(keys - set(_probe.ALL_KEYS)):
        problems.append(f"프로브가 내지 않는 키 `{key}`")
    return problems


def check_secrets_and_content(text: str) -> list[str]:
    """시크릿 부재·DB 접속 정보 규칙·6항목 브리핑·추정치·정직 고지의 존재."""
    problems: list[str] = []
    code = "\n".join(_blocks(text))
    if "postgresql+asyncpg://whymath@127.0.0.1:5433/whymath?ssl=disable" not in code:
        problems.append(
            "prod DB 접속 문자열이 로컬 DB 지도 규칙(127.0.0.1:5433, user/db=whymath)과 다르다"
        )
    if re.search(r"://[A-Za-z0-9_]+:[^@\s]+@", code) or re.search(
        r"(?i)api[_-]?key|password|secret", code
    ):
        problems.append("코드 블록에 시크릿·비밀번호 형태가 있다")
    if re.search(r"127\.0\.0\.1:(?!5433\b)\d+", code) or "localhost" in code:
        problems.append("5433 외의 DB 주소가 코드 블록에 있다")
    for heading in ("과제 명칭", "목적", "구체적 절차", "성공 기준", "실행 환경", "창 구분"):
        if not re.search(rf"^## \d+\. {heading}", text, re.M):
            problems.append(f"6항목 브리핑 `{heading}` 절이 없다")
    for needle in (
        "판정 기준: main",
        "3,461",
        "2,734",
        "2,845",
        "396",
        "324",
        "worktree",
        "__file__",
        "이 샌드박스에서는 실행 검증하지 못함",
        "WRITE_REFUSED",
        "acceptance",
    ):
        if needle not in text:
            problems.append(f"런북에 `{needle}`이(가) 없다")
    return problems


CHECKS: dict[str, Callable[[str], list[str]]] = {
    "fence_tags": check_fence_tags,
    "block_notation": check_block_notation,
    "write_guards": check_write_guards,
    "shared_clone": check_shared_clone_untouched,
    "cli_and_paths": check_cli_and_paths_exist,
    "probe_keys": check_probe_keys_exist,
    "content": check_secrets_and_content,
}


def _runbook_text() -> str:
    return _RUNBOOK.read_text(encoding="utf-8")


# ── green 대조군: 정상 런북은 모든 검사를 통과한다 ───────────────────────────────


@pytest.mark.parametrize("name", sorted(CHECKS))
def test_runbook_passes_every_check(name: str) -> None:
    assert CHECKS[name](_runbook_text()) == []


def test_runbook_is_in_scanner_default_glob_and_not_waived() -> None:
    """HARN-106 스캐너의 기본 글롭에 들고 유예 없이 통과한다(스캔 0건 금지)."""
    assert _RUNBOOK.match("*runbook*.md")
    scanner_src = _SCANNER.read_text(encoding="utf-8")
    assert "p3_81_hint_repopulate_runbook" not in scanner_src
    done = subprocess.run(
        [sys.executable, str(_SCANNER), str(_RUNBOOK.relative_to(_REPO_ROOT))],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    # 스캐너가 이 런북의 쓰기 블록을 실제로 인식한다 — 0개면 인식 범위 회귀(문자열 안 실행 등)다.
    match = re.search(r"쓰기 블록 (\d+)개", done.stdout)
    assert match is not None and int(match.group(1)) >= 2, done.stdout


# ── 뮤테이션: 텍스트 사본에 결함을 주입하면 담당 검사가 RED여야 한다 ────────────────


def _mutate(text: str, old: str, new: str, *, count: int = 1) -> str:
    assert text.count(old) == count, f"주입 대상이 {text.count(old)}건(기대 {count}): {old[:50]!r}"
    mutated = text.replace(old, new)
    assert mutated != text, "주입이 적용되지 않았다(검출처럼 보이는 위장 방지)"
    assert len(mutated) == len(text) - len(old) * count + len(new) * count
    return mutated


def _apply_line(text: str) -> str:
    return next(line for line in text.splitlines() if line.startswith("if ($ApplyReady)"))


def _dry_line(text: str) -> str:
    return next(line for line in text.splitlines() if line.startswith("if ($DryReady)"))


_Mutation = tuple[str, Callable[[str], str], str]

MUTATIONS: list[_Mutation] = [
    (
        "M01 적재 거부 가지 침묵",
        lambda t: _mutate(
            t,
            _apply_line(t),
            re.sub(r"\} else \{.*\}$", "} else { $ApplyExit = -1 }", _apply_line(t)),
        ),
        "write_guards",
    ),
    (
        "M02 ApplyReady가 DryOk를 재검사하지 않음",
        lambda t: _mutate(t, "$ApplyReady = $DryOk -and ", "$ApplyReady = "),
        "write_guards",
    ),
    (
        "M03 ApplyReady가 확인 입력을 재검사하지 않음",
        lambda t: _mutate(t, "$BackupOk -and $ConfirmOk -and ", "$BackupOk -and "),
        "write_guards",
    ),
    (
        "M04 ApplyReady가 백업을 재검사하지 않음",
        lambda t: _mutate(t, "$DryOk -and $BackupOk -and $ConfirmOk", "$DryOk -and $ConfirmOk"),
        "write_guards",
    ),
    (
        "M33 ApplyReady가 worktree 판정을 재검사하지 않음",
        lambda t: _mutate(t, "$ConfirmOk -and $WtOk -and $CodeOk", "$ConfirmOk -and $CodeOk"),
        "write_guards",
    ),
    (
        "M34 ApplyReady가 코드 출처를 재검사하지 않음",
        lambda t: _mutate(
            t,
            '$WtOk -and $CodeOk -and $BeforeOk -and ($ReachExit -eq 0)\n"APPLY_READY',
            '$WtOk -and $BeforeOk -and ($ReachExit -eq 0)\n"APPLY_READY',
        ),
        "write_guards",
    ),
    (
        "M35 ApplyReady가 적재 전 실측을 재검사하지 않음",
        lambda t: _mutate(
            t,
            '$CodeOk -and $BeforeOk -and ($ReachExit -eq 0)\n"APPLY_READY',
            '$CodeOk -and ($ReachExit -eq 0)\n"APPLY_READY',
        ),
        "write_guards",
    ),
    (
        "M36 ApplyReady가 DB 도달을 재검사하지 않음",
        lambda t: _mutate(
            t, '$BeforeOk -and ($ReachExit -eq 0)\n"APPLY_READY', '$BeforeOk\n"APPLY_READY'
        ),
        "write_guards",
    ),
    (
        "M05 적재가 가드 밖",
        lambda t: _mutate(
            t,
            _apply_line(t),
            "$ApplyOut = & $Py -m whymath_backend.l4.hint_content.populate --apply",
        ),
        "write_guards",
    ),
    (
        "M06 적재 줄에 --overwrite-cms-edits",
        lambda t: _mutate(
            t,
            "hint_content.populate --apply; $ApplyExit",
            "hint_content.populate --apply --overwrite-cms-edits; $ApplyExit",
        ),
        "write_guards",
    ),
    (
        "M07 dry-run 줄에 --apply 혼입(쓰기 2곳)",
        lambda t: _mutate(
            t,
            "hint_content.populate; $DryExit",
            "hint_content.populate --apply; $DryExit",
        ),
        "write_guards",
    ),
    (
        "M08 확인 입력 판정이 항상 참",
        lambda t: _mutate(t, '$ConfirmOk = ($Confirm -ceq "APPLY")', "$ConfirmOk = $true"),
        "write_guards",
    ),
    (
        "M09 Read-Host 블록에 다른 명령 동거",
        lambda t: _mutate(
            t,
            '대문자 APPLY 를 입력하고 Enter"\n',
            '대문자 APPLY 를 입력하고 Enter"\n"CONFIRM_ECHO=$Confirm"\n',
        ),
        "write_guards",
    ),
    (
        "M10 SQL 변이 우회 경로",
        lambda t: _mutate(
            t,
            '"JUDGED_AGAINST_MAIN=$MainSha"\n',
            '"JUDGED_AGAINST_MAIN=$MainSha"\ndocker exec -i whymath-pg psql -U whymath -d whymath -c "UPDATE hints SET verified = false"\n',
        ),
        "write_guards",
    ),
    (
        "M11 dry-run 가드가 코드 출처를 재검사하지 않음",
        lambda t: _mutate(t, "$DryReady = $WtOk -and $CodeOk -and ", "$DryReady = $WtOk -and "),
        "write_guards",
    ),
    (
        "M12 거부 가지가 변수를 출력하지 않음",
        lambda t: _mutate(
            t,
            "WRITE_REFUSED=True — DRY_OK=$DryOk BACKUP_OK=$BackupOk CONFIRMED=$ConfirmOk "
            "WT_OK=$WtOk CODE_OK=$CodeOk BEFORE_OK=$BeforeOk REACH_EXIT=$ReachExit · ",
            "WRITE_REFUSED=True — ",
        ),
        "write_guards",
    ),
    (
        "M13 공유 클론 체크아웃 이동",
        lambda t: _mutate(
            t, "git worktree add --detach $Wt origin/main", "git checkout --detach origin/main"
        ),
        "shared_clone",
    ),
    (
        "M14 worktree 판정에서 프로브 존재 확인 제거",
        lambda t: _mutate(t, "-and $HasProbe -and $HasValueAxis", "-and $HasValueAxis"),
        "shared_clone",
    ),
    (
        "M15 코드 출처 대조에서 store 경로 제거",
        lambda t: _mutate(t, ' -and ($BeforeMap["CODE_STORE"] -like "$Wt\\*")', ""),
        "shared_clone",
    ),
    (
        "M16 stash로 클론 정리",
        lambda t: _mutate(t, '"CLONE_HEAD_UNCHANGED="', 'git stash\n"CLONE_HEAD_UNCHANGED="'),
        "shared_clone",
    ),
    (
        "M17 자리표시자",
        lambda t: _mutate(t, "$OutDir = ", '$Key = "여기에_키_전체"\n$OutDir = '),
        "block_notation",
    ),
    (
        "M18 프롬프트 접두",
        lambda t: _mutate(
            t, "git fetch origin main\n$CloneHead", "$ git fetch origin main\n$CloneHead"
        ),
        "block_notation",
    ),
    (
        "M19 출력 화살표 주석",
        lambda t: _mutate(
            t, "$ReachExit = $LASTEXITCODE\n", "$ReachExit = $LASTEXITCODE  # ← 여기가 0이어야\n"
        ),
        "block_notation",
    ),
    (
        "M20 시스템 라벨 누락",
        lambda t: _mutate(
            t, "# [Windows PowerShell · Phaiakes9] 같은 창 · C 환경", "# 같은 창 · C 환경"
        ),
        "block_notation",
    ),
    (
        "M21 태그 없는 펜스",
        lambda t: _mutate(
            t,
            "```powershell\n# [Windows PowerShell · Phaiakes9] 같은 창 · I 서빙",
            "```\n# [Windows PowerShell · Phaiakes9] 같은 창 · I 서빙",
        ),
        "fence_tags",
    ),
    (
        "M22 존재하지 않는 populate 인자",
        lambda t: _mutate(
            t, "hint_content.populate; $DryExit", "hint_content.populate --dry-run; $DryExit"
        ),
        "cli_and_paths",
    ),
    (
        "M23 존재하지 않는 모듈 경로",
        lambda t: _mutate(
            t, "whymath_backend.ops.db_host_reachability", "whymath_backend.ops.db_host_reachabilty"
        ),
        "cli_and_paths",
    ),
    (
        "M24 프로브 서브커맨드 오타",
        lambda t: _mutate(t, "$Probe serve-sample", "$Probe serve-sampl"),
        "cli_and_paths",
    ),
    (
        "M25 프로브 플래그 오타",
        lambda t: _mutate(t, "run-summary --json $DryJson", "run-summary --jsn $DryJson"),
        "cli_and_paths",
    ),
    (
        "M26 프로브 파일명 오타",
        lambda t: _mutate(
            t,
            "scripts\\ops\\p3_81_hint_catalog_probe.py",
            "scripts\\ops\\p3_81_hint_catalog_prob.py",
            count=2,
        ),
        "cli_and_paths",
    ),
    (
        "M27 프로브가 내지 않는 키를 읽음",
        lambda t: _mutate(t, '"HINTS_CMS_COLUMN"', '"HINTS_CMS_COLUMNN"'),
        "probe_keys",
    ),
    (
        "M28 레벨 템플릿 키 오타",
        lambda t: _mutate(t, '"CARRY_VERIFIED_L1"', '"CARRY_VERIFIED_LL1"', count=3),
        "probe_keys",
    ),
    (
        "M29 접속 문자열에 비밀번호",
        lambda t: _mutate(
            t,
            "postgresql+asyncpg://whymath@127.0.0.1:5433",
            "postgresql+asyncpg://whymath:pw@127.0.0.1:5433",
            count=1,
        ),
        "content",
    ),
    (
        "M30 추정치(최종판) 삭제",
        lambda t: _mutate(t, "2,734", "N/A", count=t.count("2,734")),
        "content",
    ),
    (
        "M31 정직 고지 삭제",
        lambda t: _mutate(t, "이 샌드박스에서는 실행 검증하지 못함", "검증 완료"),
        "content",
    ),
    (
        "M32 데모 DB 포트로 접속",
        lambda t: _mutate(
            t, "127.0.0.1:5433/whymath?ssl=disable", "127.0.0.1:55432/whymath?ssl=disable"
        ),
        "content",
    ),
]


@pytest.mark.parametrize(("label", "inject", "check"), MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_mutation_is_caught_by_responsible_check(
    label: str, inject: Callable[[str], str], check: str
) -> None:
    original = _runbook_text()
    mutated = inject(original)
    assert mutated != original, f"{label}: 주입이 적용되지 않았다"
    assert CHECKS[check](mutated), f"{label}: `{check}` 검사가 결함을 놓쳤다"
    # 정상 문서는 이 검사에서 깨끗하다(대조군) — 결함 때문에만 RED가 된다.
    assert CHECKS[check](original) == []


def test_every_check_is_exercised_by_a_mutation() -> None:
    """뮤테이션이 닿지 않는 검사는 보호가 아니다 — 모든 검사에 최소 1개 뮤테이션이 있다."""
    covered = {check for _, _, check in MUTATIONS}
    assert covered == set(CHECKS), set(CHECKS) - covered


def test_mutation_catalog_is_not_trivially_small() -> None:
    assert len(MUTATIONS) >= 36


# ── 선택: PowerShell 파서(있을 때만) — 문법 오류 ───────────────────────────────


def _pwsh() -> str | None:
    return os.environ.get("WHYMATH_PWSH") or shutil.which("pwsh")


@pytest.mark.skipif(_pwsh() is None, reason="pwsh 없음 — 로컬에서 WHYMATH_PWSH로 지정하면 돈다")
def test_every_block_parses_in_powershell(tmp_path: Path) -> None:
    pwsh = _pwsh()
    assert pwsh is not None
    for index, block in enumerate(_blocks(_runbook_text()), start=1):
        script = tmp_path / f"block{index}.ps1"
        script.write_text(block, encoding="utf-8")
        probe = (
            "$e=$null;$t=$null;"
            f"[void][System.Management.Automation.Language.Parser]::ParseFile('{script}',[ref]$t,[ref]$e);"
            "$e.Count"
        )
        done = subprocess.run(
            [pwsh, "-NoProfile", "-Command", probe],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "DOTNET_SYSTEM_GLOBALIZATION_INVARIANT": "1"},
        )
        assert done.stdout.strip() == "0", f"블록 #{index} 문법 오류: {done.stdout}{done.stderr}"


# ── 프로브: 읽기 전용 계약 + 순수 로직 ────────────────────────────────────────


def _probe_source() -> str:
    return _PROBE.read_text(encoding="utf-8")


_SQL_MUTATION = re.compile(
    r"\b(?:insert\s+into|update\s+\w+\s+set|delete\s+from|truncate|drop\s+table|alter\s+table"
    r"|create\s+table)\b",
    re.IGNORECASE,
)


def probe_write_violations(source: str) -> list[str]:
    """프로브 소스의 쓰기 경로 — SQL 변이 문자열·commit/add/flush 호출·읽기 전용 선언 부재."""
    tree = ast.parse(source)
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    problems: list[str] = []
    saw_read_only = False
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            if _SQL_MUTATION.search(node.value):
                problems.append(f"SQL 변이 문자열: {node.value[:50]!r}")
            if "SET TRANSACTION READ ONLY" in node.value:
                saw_read_only = True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {"commit", "add", "add_all", "flush", "merge", "delete"}:
                problems.append(f"쓰기 의심 호출 `.{node.func.attr}()`")
    if not saw_read_only:
        problems.append("`SET TRANSACTION READ ONLY` 선언이 없다")
    return problems


def test_probe_has_no_write_path() -> None:
    assert probe_write_violations(_probe_source()) == []


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ('"SELECT count(*) FROM hints"', '"DELETE FROM hints"'),
        ("await session.rollback()\n", "await session.commit()\n"),
        ('"SET TRANSACTION READ ONLY"', '"SET TRANSACTION READ WRITE"'),
        ('"SELECT count(*) FROM hints WHERE verified"', '"UPDATE hints SET verified = true"'),
    ],
    ids=["delete", "commit", "no-read-only", "update"],
)
def test_probe_write_mutations_are_caught(old: str, new: str) -> None:
    source = _probe_source()
    assert source.count(old) >= 1, old
    mutated = source.replace(old, new, 1)
    assert mutated != source
    assert probe_write_violations(mutated)


def test_probe_subcommands_are_exactly_the_read_only_four() -> None:
    assert set(_probe_subcommands()) == {"stats", "run-summary", "serve-sample", "catalog-scan"}


_FULL_REPORT: dict[str, object] = {
    "applied": True,
    "paths_seen": 4,
    "paths_loaded": 4,
    "paths_skipped_missing_header": 0,
    "paths_skipped_noncontiguous_steps": 0,
    "generated": 26,
    "generated_by_level": {"1": 10, "2": 10, "3": 6},
    "verified": 25,
    "verified_by_level": {"1": 10, "2": 10, "3": 5},
    "verified_rate": 25 / 26,
    "value_exposure_verdicts": {"clean": 25, "exposed": 1},
    "writes": {
        "inserted": 0,
        "updated": 26,
        "unchanged": 0,
        "retired": 0,
        "cms_edit_conflicts": [],
    },
}


def _summary(report: dict[str, object]) -> dict[str, object]:
    return dict(_probe.summarize_run(report))


def test_run_summary_of_a_good_report_is_wellformed_and_accounted() -> None:
    summary = _summary(_FULL_REPORT)
    assert summary["RUN_WELLFORMED"] is True
    assert summary["RUN_VALUE_ACCOUNTED"] is True
    assert summary["RUN_VERIFIED_L3"] == 5
    assert summary["RUN_VALUE_EXPOSED"] == 1
    assert summary["RUN_VALUE_NOT_RUN"] == 0
    assert summary["RUN_CMS_CONFLICTS"] == 0


def test_run_summary_keys_are_all_declared() -> None:
    """프로브가 낼 수 있는 `RUN_*` 키는 `ALL_KEYS` 선언 안에 있다(런북이 이름으로 읽는다)."""
    dry = {k: v for k, v in _FULL_REPORT.items() if k != "writes"} | {"writes": None}
    for report in (_FULL_REPORT, dry, {}):
        assert {key for key, _ in _probe.summarize_run(report)} <= set(_probe.ALL_KEYS)


@pytest.mark.parametrize(
    ("mutation", "expect_key", "expect_value"),
    [
        (
            lambda r: {k: v for k, v in r.items() if k != "value_exposure_verdicts"},
            "RUN_WELLFORMED",
            False,
        ),
        (lambda r: {k: v for k, v in r.items() if k != "generated"}, "RUN_WELLFORMED", False),
        (lambda r: {**r, "generated": "26"}, "RUN_WELLFORMED", False),
        (lambda r: {**r, "value_exposure_verdicts": {"clean": 20}}, "RUN_VALUE_ACCOUNTED", False),
        (
            lambda r: {**r, "value_exposure_verdicts": {"clean": 25, "mystery": 1}},
            "RUN_VALUE_ACCOUNTED",
            False,
        ),
        (
            lambda r: {**r, "generated": 0, "value_exposure_verdicts": {}},
            "RUN_VALUE_ACCOUNTED",
            False,
        ),
        (lambda r: {**r, "value_exposure_verdicts": {"not_run": 26}}, "RUN_VALUE_NOT_RUN", 26),
    ],
    ids=[
        "no-verdicts",
        "no-generated",
        "str-generated",
        "short-sum",
        "unknown-verdict",
        "zero-gen",
        "not-run",
    ],
)
def test_run_summary_does_not_read_missing_or_broken_as_ok(
    mutation: Callable[[dict[str, object]], dict[str, object]],
    expect_key: str,
    expect_value: object,
) -> None:
    broken = mutation(dict(_FULL_REPORT))
    assert broken != _FULL_REPORT
    assert _summary(broken)[expect_key] == expect_value


def test_run_summary_missing_counts_are_reported_not_zero() -> None:
    """빠진 필드는 0이 아니라 `missing`이다(모른다 ≠ 0)."""
    summary = _summary({k: v for k, v in _FULL_REPORT.items() if k != "paths_seen"})
    assert summary["RUN_PATHS_SEEN"] == "missing"
    assert summary["RUN_WELLFORMED"] is False


def test_run_summary_cli_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_FULL_REPORT, ensure_ascii=False) + "\n", encoding="utf-8")
    assert _probe.main(["run-summary", "--json", str(good)]) == 0
    assert "RUN_WELLFORMED=True" in capsys.readouterr().out
    for name, content in (("empty.json", ""), ("junk.json", "not json\n"), ("list.json", "[1]\n")):
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        assert _probe.main(["run-summary", "--json", str(path)]) == 2, name
    assert _probe.main(["run-summary", "--json", str(tmp_path / "missing.json")]) == 2


def test_kv_output_is_ascii_and_rejects_undeclared_keys(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _probe.kv("PROBE_ERROR", "한글 사유")
    out = capsys.readouterr().out
    assert out.isascii() and out.startswith("PROBE_ERROR=")
    with pytest.raises(KeyError):
        _probe.kv("NOT_DECLARED_KEY", 1)


def test_even_sample_is_deterministic_and_bounded() -> None:
    items = list(range(1000))
    first = _probe._even_sample(items, 7)
    assert first == _probe._even_sample(items, 7)
    assert len(first) == 7 and first == sorted(set(first))
    assert _probe._even_sample(items, 0) == items
    assert _probe._even_sample(items, 5000) == items
