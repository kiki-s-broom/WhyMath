#!/usr/bin/env python3
"""코딩 헌법 보호 가드 — PreToolUse(Edit|Write|MultiEdit|NotebookEdit|Bash) 훅 (CONST-02 · R0-01).

**무엇을 막는가**: AI 세션이 `constitution/`(코딩 헌법 · 규칙 등록부 · 단계 · 개정 기록 ·
판례)을 **수정·삭제·이동**하는 것. 헌법 제9조 ①("AI는 constitution/ 폴더를 수정·삭제·
이동할 수 없다")의 집행 장치이며, 목표 강도 L5(자동 차단)다.

**왜 경로가 아니라 '경로 + 변경 동작'인가**: 헌법은 AI가 **읽어야** 하는 문서다(제2조 ②
"충돌 조문·규칙 ID를 보고"). `cat constitution/rules.yaml`·`python3 scripts/constitution/
audit.py`까지 막으면 헌법을 지킬 수 없고, 그러면 사람이 훅을 끈다. 그래서 편집 도구는
대상 경로로, Bash는 **헌법 경로를 가리키는 인자와 변경 동사가 같은 명령에 함께 있을 때만**
막는다.

**판정 규칙 (Bash)**
  · 명령을 `;` `&&` `||` `|` `&` 로 나눈 단위마다 본다. `cd X` 는 뒤 단위의 기준 경로를 바꾼다.
  · 경로 인자는 현재 기준 경로로 정규화해 `<저장소>/constitution` 아래인지 본다
    (`./constitution`·`../x/constitution`·절대경로·대소문자 차이 포함 · `scripts/constitution/`
    처럼 이름만 같은 다른 폴더는 제외).
  · 변경 동사: rm·rmdir·mv·unlink·shred·touch·truncate·mkdir·chmod·chown·ln·tee·dd(of=) ·
    cp·install·rsync(대상 인자) · sed/perl `-i` · find `-delete`/`-exec 변경동사` ·
    xargs 뒤 변경동사 · git mv/rm/checkout/restore/reset/clean/apply/am/stash ·
    출력 리다이렉트(`>`·`>>`) 대상 · 출력 옵션(`--report`·`--json`·`-o`·`--out`·`--output`)
    값 · `bash -c`/`sh -c` 는 안쪽 명령을 같은 규칙으로 재귀 판정.
  · 인터프리터 인라인 코드(`-c`·`-e`·heredoc 입력) — 파이썬은 문법 트리(AST)로 읽어 **쓰기
    호출의 대상**(open 쓰기 모드·write_text·unlink·os.remove·shutil 복사 대상·subprocess 명령)에
    헌법 경로 상수가 직접 또는 변수를 거쳐 흘러들 때만 막는다. 헌법을 언급만 하고 다른 파일에
    쓰는 코드는 통과한다(2026-09-28 오탐 교정). node·perl·ruby·AST 파싱 실패는 같은 줄에
    따옴표 친 헌법 경로와 쓰기 표지가 함께 있을 때 막는다.
  · `git add constitution/` 은 막지 않는다 — 인덱스 등록은 파일을 바꾸지 않는다.

**모른다 ≠ 아니다**: 명령 파싱(`shlex`)이 실패하면 "변경 없음"으로 읽지 않는다. 명령
문자열에 헌법 경로와 변경 동사가 **둘 다** 보이면 막고 사유를 말한다. 둘 중 하나라도
없으면 통과한다(훅이 개발을 볼모로 잡지 않는다 — git_revert_guard와 같은 원칙).

**한계(명시 — 막지 못하는 것을 막는다고 말하지 않는다)**
  · Claude Code의 도구 호출만 본다. Kiki 본인의 편집·GitHub 웹 편집·외부 스크립트는 대상이
    아니며 그것이 의도다(헌법은 사람만 수정한다).
  · 변수·`eval`·별칭·스크립트 파일 안에서의 쓰기, 심볼릭 링크를 새로 만들어 우회하는 경로는
    문자열 파싱으로 보이지 않는다. 두 번째 층은 커밋 시점 검사(R0-02 check_amendment ·
    CONST-03)와 settings.json `permissions.deny`(Edit/Write/MultiEdit)다.

차단 시 exit 2 + stderr 메시지(Claude에게 전달된다). 모든 차단과 파싱 실패는
`.claude/logs/constitution_guard.jsonl`에 남는다(gitignore 대상 · 자가시험·테스트는
`CLAUDE_GUARD_LOG_DIR`로 로그 위치만 옮긴다 — 판정에는 영향이 없어 우회 수단이 아니다).

**settings.json 거부 규칙은 반드시 `/`로 고정한다** — `Edit(constitution/**)`처럼 한 단계짜리
폴더 패턴은 거부 규칙에서 '어느 깊이에서든' 일치해 `scripts/constitution/`까지 막는다(Claude Code
권한 문서 · 2026-09-28 이식 세션 실측). 프로젝트 설정의 `/constitution/**`는 저장소 최상위에만
고정된다. 이 불변식은 tests/infra/test_coding_constitution_guard.py 가 동결한다.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from datetime import UTC, datetime
from typing import Any

#: 보호 대상 폴더 이름 (저장소 최상위 기준)
PROTECTED_DIRNAME = "constitution"

#: 편집 계열 도구 — tool_input의 경로 필드로 판정한다
EDIT_TOOLS: frozenset[str] = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})

#: 인자 중 헌법 경로가 하나라도 있으면 차단하는 동사
ANY_ARG_VERBS: frozenset[str] = frozenset(
    {"rm", "rmdir", "mv", "unlink", "shred", "touch", "truncate", "mkdir", "chmod", "chown"}
    | {"chgrp", "ln", "tee", "setfacl", "chattr"}
)

#: 마지막(대상) 인자가 헌법 경로일 때만 차단하는 복사 계열 동사
DEST_ARG_VERBS: frozenset[str] = frozenset({"cp", "install", "rsync", "scp"})

#: 헌법 경로 인자와 함께 오면 차단하는 git 서브커맨드 (add는 파일을 바꾸지 않아 제외)
GIT_WRITE_SUBCOMMANDS: frozenset[str] = frozenset(
    {"mv", "rm", "checkout", "restore", "reset", "clean", "apply", "am", "stash", "switch"}
)

#: 인라인 코드를 받는 인터프리터
INTERPRETERS: frozenset[str] = frozenset(
    {"python", "python3", "py", "pypy3", "node", "perl", "ruby", "deno"}
)
SHELLS: frozenset[str] = frozenset({"bash", "sh", "zsh", "dash"})

#: 출력 파일을 받는 옵션 (값이 헌법 경로면 쓰기다)
OUTPUT_OPTIONS: frozenset[str] = frozenset(
    {"--report", "--json", "-o", "--out", "--output", "--output-file", "--outfile"}
)

_SEPARATORS: frozenset[str] = frozenset({"&&", "||", ";", "|", "&", ";;", "|&"})
_REDIRECTS: frozenset[str] = frozenset({">", ">>", ">|", "&>", "&>>", "<>"})

#: 인라인 코드의 쓰기 표지
_WRITE_HINT_RE = re.compile(
    r"open\([^)]*['\"][rwxab+]*[wax][rwxab+]*['\"]"
    r"|write_text|write_bytes|\.unlink\(|rmtree|os\.remove|os\.rename|os\.replace"
    r"|shutil\.(?:move|copy|copyfile|copy2|copytree)|\.rename\(|\.touch\(|\.mkdir\("
    r"|writeFile|appendFile|unlinkSync|rmSync|renameSync|fs\.write|File\.write|-i\b"
)
#: 셸 이외 텍스트(인라인 코드·파싱 실패 명령)에서 헌법 경로 언급을 찾는 패턴
_CONSTITUTION_REF_RE = re.compile(r"(?<![\w./-])(?:\.{1,2}/)*constitution(?![\w-])", re.I)
#: 파싱 실패 시 fallback 에 쓰는 변경 동사 패턴
_MUTATING_WORD_RE = re.compile(
    r"(?<![\w-])(?:rm|rmdir|mv|unlink|shred|touch|truncate|mkdir|chmod|chown|ln|tee|cp|"
    r"install|rsync|sed\s+-i|perl\s+-p?i)(?![\w-])|>{1,2}"
)
_HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][\w]*)\1")

_ADVICE = (
    "⛔ 코딩 헌법 제9조 ①: constitution/ 은 사람(Kiki)만 수정·삭제·이동한다.\n"
    "  이 작업을 중단하고 사람에게 보고하세요(제2조 ②: 충돌 조문·규칙 ID 포함).\n"
    "  정정이 필요하면 docs/constitution_proposals/ 에 초안을 두고 Kiki가 반영하게 한다\n"
    "  (절차: docs/ops/coding_constitution_kiki_runbook.md)."
)


# ─────────────────────────── 경로 판정 ───────────────────────────
def _find_root(start: str) -> str:
    """start에서 위로 올라가며 .git이 있는 폴더를 찾는다. 없으면 start 자신."""
    cur = os.path.abspath(start)
    while True:
        if os.path.exists(os.path.join(cur, ".git")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return os.path.abspath(start)
        cur = parent


def _norm(path: str) -> str:
    """대소문자 무시 비교용 정규화 (Windows·macOS 파일시스템과 같은 판정을 내기 위해)."""
    return os.path.normcase(os.path.normpath(path)).lower()


def is_protected(path: str, cwd: str, root: str) -> bool:
    """path가 <root>/constitution 자신이거나 그 아래인가. cwd는 상대경로의 기준."""
    if not path:
        return False
    expanded = os.path.expanduser(path.strip().strip("'\""))
    full = expanded if os.path.isabs(expanded) else os.path.join(cwd, expanded)
    target = _norm(full)
    protected = _norm(os.path.join(root, PROTECTED_DIRNAME))
    return target == protected or target.startswith(protected + os.sep.lower())


def _arg_paths(token: str) -> list[str]:
    """`--file=x`·`of=x` 같은 토큰은 값 부분도 경로 후보로 본다."""
    if "=" in token and not token.startswith("="):
        return [token, token.split("=", 1)[1]]
    return [token]


# ─────────────────────────── 명령 분해 ───────────────────────────
def _split_heredocs(command: str) -> tuple[str, list[tuple[int, str]]]:
    """heredoc 본문을 명령에서 떼어 낸다.

    반환: (본문을 뺀 명령, [(본문이 딸린 줄 번호, 본문 텍스트)]). 본문은 데이터이므로 셸
    명령으로 해석하지 않는다 — 다만 인터프리터가 받는 본문은 따로 코드 판정을 한다.
    """
    lines = command.split("\n")
    out: list[str] = []
    bodies: list[tuple[int, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        match = _HEREDOC_RE.search(line)
        i += 1
        if not match:
            continue
        delim = match.group(2)
        body: list[str] = []
        while i < len(lines) and lines[i].strip() != delim:
            body.append(lines[i])
            i += 1
        i += 1  # 종료 구분자 줄
        bodies.append((len(out) - 1, "\n".join(body)))
    return "\n".join(out), bodies


def _tokenize(text: str) -> list[str]:
    lexer = shlex.shlex(text.replace("\n", " ; "), posix=True, punctuation_chars=";&|<>")
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def _segments(tokens: list[str]) -> list[list[str]]:
    segs: list[list[str]] = [[]]
    for tok in tokens:
        if tok in _SEPARATORS:
            segs.append([])
        else:
            segs[-1].append(tok)
    return [s for s in segs if s]


def _strip_prefix(seg: list[str]) -> list[str]:
    """`sudo`·`env A=B`·`time`·`command` 같은 앞머리를 걷어 실제 동사를 드러낸다."""
    i = 0
    while i < len(seg):
        tok = seg[i]
        if tok in {"sudo", "time", "command", "nohup", "exec", "builtin", "doas"}:
            i += 1
        elif tok == "env" or re.match(r"^[A-Za-z_]\w*=", tok):
            i += 1
        else:
            break
    return seg[i:]


def _base(verb: str) -> str:
    return os.path.basename(verb).lower().removesuffix(".exe")


#: 파이썬 AST에서 '쓰기'로 보는 메서드 — 받는 객체(경로)가 대상이다
_PY_WRITE_METHODS: frozenset[str] = frozenset(
    {"write_text", "write_bytes", "unlink", "rename", "replace", "touch", "mkdir", "rmdir"}
    | {"symlink_to", "hardlink_to", "chmod", "rmtree"}
)
#: 파이썬 AST에서 '쓰기'로 보는 함수 — (모듈, 이름): 대상 인자 위치(None = 모든 인자)
_PY_WRITE_FUNCS: dict[tuple[str, str], int | None] = {
    ("os", "remove"): 0,
    ("os", "unlink"): 0,
    ("os", "rmdir"): 0,
    ("os", "removedirs"): 0,
    ("os", "mkdir"): 0,
    ("os", "makedirs"): 0,
    ("os", "chmod"): 0,
    ("os", "rename"): None,
    ("os", "replace"): None,
    ("shutil", "rmtree"): 0,
    ("shutil", "move"): None,
    ("shutil", "copy"): 1,
    ("shutil", "copy2"): 1,
    ("shutil", "copyfile"): 1,
    ("shutil", "copytree"): 1,
}
_PY_SHELL_FUNCS: frozenset[str] = frozenset(
    {"system", "run", "call", "check_call", "check_output", "Popen"}
)
#: 파이썬이 아닌 인터프리터(node·perl·ruby)는 줄 단위로 본다 — 따옴표 안 경로가 헌법으로 시작
_QUOTED_REF_RE = re.compile(r"['\"`](?:\.{1,2}/)*constitution(?:/[^'\"`]*)?['\"`]", re.I)


def _literal_protected(value: str, cwd: str, root: str) -> bool:
    """문자열 상수가 헌법 경로를 가리키는가.

    저장소 최상위 기준 조립(ROOT / 'constitution')도 본다.
    """
    value = value.strip()
    if not value or "\n" in value or len(value) > 400:
        return False  # 여러 줄 텍스트·긴 문서는 경로 상수가 아니다
    return is_protected(value, cwd, root) or is_protected(value, root, root)


def _py_expr_tainted(node: Any, tainted: set[str], cwd: str, root: str) -> bool:
    """식 안에 헌법 경로 상수나 오염된 변수가 있는가."""
    import ast

    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            if _literal_protected(sub.value, cwd, root):
                return True
        elif isinstance(sub, ast.Name) and sub.id in tainted:
            return True
    return False


def _py_code_writes_constitution(code: str, cwd: str, root: str) -> bool | None:
    """파이썬 코드를 AST로 읽어 '쓰기 호출의 대상'이 헌법 경로인지 본다.

    None = 파싱 실패(호출측이 줄 단위 판정으로 넘어간다). 헌법 경로를 **언급**만 하고 다른 파일에
    쓰는 코드(문서 작성·설정 수정)는 통과한다 — 2026-09-28 이식 세션에서 거친 판정(언급 + 쓰기
    표지)이 settings.json 수정 스크립트를 오탐 차단한 것을 고친 판정이다.
    """
    import ast

    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return None
    # 변수 오염 전파: 헌법 경로 상수(또는 오염 변수)에서 만든 이름은 오염된다 — 고정점까지 반복
    assigns: list[tuple[list[str], Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = [t.id for tgt in targets for t in ast.walk(tgt) if isinstance(t, ast.Name)]
            if node.value is not None:
                assigns.append((names, node.value))
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    names = [t.id for t in ast.walk(item.optional_vars) if isinstance(t, ast.Name)]
                    assigns.append((names, item.context_expr))
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
            names = [t.id for t in ast.walk(node.target) if isinstance(t, ast.Name)]
            assigns.append((names, node.iter))
    tainted: set[str] = set()
    changed = True
    while changed:
        changed = False
        for names, value in assigns:
            if set(names) - tainted and _py_expr_tainted(value, tainted, cwd, root):
                tainted |= set(names)
                changed = True

    def is_hit(expr: Any) -> bool:
        return _py_expr_tainted(expr, tainted, cwd, root)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "open":
            mode = node.args[1] if len(node.args) > 1 else None
            for kw in node.keywords:
                if kw.arg == "mode":
                    mode = kw.value
            writes = isinstance(mode, ast.Constant) and any(c in str(mode.value) for c in "wax+")
            if writes and node.args and is_hit(node.args[0]):
                return True
        elif isinstance(func, ast.Attribute):
            owner = func.value.id if isinstance(func.value, ast.Name) else ""
            if func.attr in _PY_WRITE_METHODS and owner not in {"os", "shutil"}:
                if is_hit(func.value):
                    return True
            if func.attr == "open" and owner not in {"os", "io"}:
                mode = node.args[0] if node.args else None
                writes = isinstance(mode, ast.Constant) and any(
                    c in str(mode.value) for c in "wax+"
                )
                if writes and is_hit(func.value):
                    return True
            spec = _PY_WRITE_FUNCS.get((owner, func.attr), -1)
            if spec != -1:
                targets = node.args if spec is None else node.args[spec : spec + 1]
                if any(is_hit(arg) for arg in targets):
                    return True
            if owner in {"os", "subprocess"} and func.attr in _PY_SHELL_FUNCS and node.args:
                first = node.args[0]
                parts: list[str] = []
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    parts = [first.value]
                elif isinstance(first, (ast.List, ast.Tuple)):
                    parts = [
                        shlex.quote(e.value)
                        for e in first.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)
                    ]
                if parts and judge_command(" ".join(parts), cwd, root):
                    return True
    return False


def _code_writes_constitution(code: str, lang: str, cwd: str, root: str) -> bool:
    """인라인 코드가 헌법 경로에 쓰는가. 파이썬은 AST, 그 밖은 줄 단위(따옴표 경로 + 쓰기 표지)."""
    if lang in {"python", "python3", "py", "pypy3"}:
        verdict = _py_code_writes_constitution(code, cwd, root)
        if verdict is not None:
            return verdict
    return any(
        _QUOTED_REF_RE.search(line) and _WRITE_HINT_RE.search(line) for line in code.splitlines()
    )


def judge_segment(seg: list[str], cwd: str, root: str) -> tuple[str | None, str]:
    """한 명령 단위를 판정한다. 반환: (차단 사유 또는 None, 다음 단위의 기준 경로)."""
    # 리다이렉트 대상은 동사와 무관하게 쓰기다
    for idx, tok in enumerate(seg):
        if tok in _REDIRECTS and idx + 1 < len(seg) and is_protected(seg[idx + 1], cwd, root):
            return f"출력 리다이렉트 대상이 헌법 경로: {seg[idx + 1]}", cwd
    words = [t for t in seg if t not in _REDIRECTS and t != "<"]
    words = _strip_prefix(words)
    if not words:
        return None, cwd
    verb = _base(words[0])
    args = words[1:]

    if verb == "cd":
        target = args[0] if args else os.path.expanduser("~")
        new = target if os.path.isabs(target) else os.path.join(cwd, target)
        return None, os.path.normpath(os.path.expanduser(new))

    def hits(candidates: list[str]) -> list[str]:
        return [a for a in candidates for p in _arg_paths(a) if is_protected(p, cwd, root)]

    # 출력 옵션 값
    for idx, tok in enumerate(args):
        if tok in OUTPUT_OPTIONS and idx + 1 < len(args) and is_protected(args[idx + 1], cwd, root):
            return f"출력 옵션 {tok} 의 값이 헌법 경로: {args[idx + 1]}", cwd
        if "=" in tok and tok.split("=", 1)[0] in OUTPUT_OPTIONS:
            if is_protected(tok.split("=", 1)[1], cwd, root):
                return f"출력 옵션 값이 헌법 경로: {tok}", cwd

    if verb in ANY_ARG_VERBS and hits(args):
        return f"'{verb}' 가 헌법 경로를 변경: {hits(args)[0]}", cwd
    if verb == "dd" and any(a.startswith("of=") and is_protected(a[3:], cwd, root) for a in args):
        return "dd 의 출력(of=)이 헌법 경로", cwd
    if verb in DEST_ARG_VERBS:
        positional = [a for a in args if not a.startswith("-")]
        if positional and hits(positional[-1:]):
            return f"'{verb}' 의 대상(마지막 인자)이 헌법 경로: {positional[-1]}", cwd
        if any(a.startswith("--target-directory") or a == "-t" for a in args) and hits(args):
            return f"'{verb} -t' 대상이 헌법 경로", cwd
    if verb in {"sed", "perl", "ruby"} and any(re.match(r"^-\w*i", a) for a in args) and hits(args):
        return f"'{verb} -i' 제자리 편집 대상이 헌법 경로: {hits(args)[0]}", cwd
    if verb == "find" and hits(args):
        if "-delete" in args or any(
            args[i] in {"-exec", "-execdir", "-ok"}
            and i + 1 < len(args)
            and _base(args[i + 1]) in ANY_ARG_VERBS | DEST_ARG_VERBS | {"sed", "perl"}
            for i in range(len(args))
        ):
            return "find -delete/-exec 변경이 헌법 경로 대상", cwd
    if verb == "git" and args:
        sub_idx = 0
        while sub_idx < len(args) and args[sub_idx].startswith("-"):
            sub_idx += 2 if args[sub_idx] in {"-C", "-c"} else 1
        if sub_idx < len(args) and args[sub_idx] in GIT_WRITE_SUBCOMMANDS:
            if hits(args[sub_idx + 1 :]):
                return f"'git {args[sub_idx]}' 가 헌법 경로를 변경", cwd
    if verb in SHELLS and "-c" in args:
        inner_idx = args.index("-c") + 1
        if inner_idx < len(args):
            reason = judge_command(args[inner_idx], cwd, root)
            if reason:
                return f"{verb} -c 안쪽: {reason}", cwd
    if verb in INTERPRETERS:
        for flag in ("-c", "-e", "-E"):
            if flag in args:
                idx = args.index(flag) + 1
                if idx < len(args) and _code_writes_constitution(args[idx], verb, cwd, root):
                    return f"{verb} {flag} 인라인 코드가 헌법 경로에 쓰기", cwd
    return None, cwd


def _xargs_mutation(segs: list[list[str]], cwd: str, root: str) -> str | None:
    """`... constitution ... | xargs rm` — 앞 단위가 헌법 경로를 내고 뒤가 xargs 변경동사."""
    mentions = any(
        is_protected(p, cwd, root) for seg in segs for tok in seg for p in _arg_paths(tok)
    )
    if not mentions:
        return None
    for seg in segs:
        words = _strip_prefix(seg)
        if words and _base(words[0]) == "xargs":
            rest = [w for w in words[1:] if not w.startswith("-")]
            if rest and _base(rest[0]) in ANY_ARG_VERBS | DEST_ARG_VERBS | {"sed", "perl"}:
                return f"xargs {rest[0]} 가 헌법 경로 목록을 받아 변경"
    return None


def judge_command(command: str, cwd: str, root: str) -> str | None:
    """Bash 명령 문자열 전체를 판정한다. 차단 사유 또는 None."""
    stripped, bodies = _split_heredocs(command)
    lines = stripped.split("\n")
    # heredoc 본문이 인터프리터 입력이면 코드로 판정한다 (cat > file <<EOF 의 본문은 데이터)
    for line_no, body in bodies:
        head_words = _strip_prefix(lines[line_no].split())
        if head_words and _base(head_words[0]) in INTERPRETERS | SHELLS:
            if _base(head_words[0]) in SHELLS:
                reason = judge_command(body, cwd, root)
                if reason:
                    return f"셸 heredoc 입력: {reason}"
            elif _code_writes_constitution(body, _base(head_words[0]), cwd, root):
                return f"{head_words[0]} heredoc 코드가 헌법 경로에 쓰기"
    try:
        tokens = _tokenize(stripped)
    except ValueError:
        # 모른다 ≠ 아니다: 파싱이 안 되면 문자열로 본다(헌법 경로 + 변경 동사가 둘 다 있을 때만)
        if _CONSTITUTION_REF_RE.search(stripped) and _MUTATING_WORD_RE.search(stripped):
            return "명령 파싱 실패 — 헌법 경로와 변경 동작이 함께 보여 보수적으로 차단"
        return None
    segs = _segments(tokens)
    current = cwd
    for seg in segs:
        reason, current = judge_segment(seg, current, root)
        if reason:
            return reason
    return _xargs_mutation(segs, cwd, root)


# ─────────────────────────── 훅 진입점 ───────────────────────────
def judge(data: dict[str, Any]) -> str | None:
    """훅 입력(JSON) 하나를 판정한다. 차단 사유 또는 None."""
    tool = data.get("tool_name") or ""
    tool_input = data.get("tool_input") or {}
    cwd = data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or "."
    root = _find_root(os.environ.get("CLAUDE_PROJECT_DIR") or cwd)
    if tool in EDIT_TOOLS:
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        if is_protected(str(path), cwd, root):
            return f"{tool} 대상이 헌법 경로: {path}"
        return None
    if tool == "Bash":
        return judge_command(str(tool_input.get("command") or ""), cwd, root)
    return None


def _log(record: dict[str, Any]) -> None:
    # CLAUDE_GUARD_LOG_DIR 은 로그 위치만 바꾼다(판정 무관) — 자가시험이 실제 기록을 오염시키지 않게
    log_dir = os.environ.get("CLAUDE_GUARD_LOG_DIR") or os.path.join(
        os.environ.get("CLAUDE_PROJECT_DIR", "."), ".claude", "logs"
    )
    try:
        os.makedirs(log_dir, exist_ok=True)
        path = os.path.join(log_dir, "constitution_guard.jsonl")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:  # 로그 실패가 작업을 막지 않는다(타입명은 남긴다)
        print(f"[guard_constitution] 로그 기록 실패({type(exc).__name__})", file=sys.stderr)


def _utf8_stderr() -> None:
    """차단 안내문(한글·⛔)을 파이프에서도 UTF-8 로 낸다 (CONST-12).

    파이프·리다이렉트에서 sys.stderr 는 로캘 인코딩(한국어 Windows = cp949)을 쓴다 — 콘솔은
    별도 경로라 멀쩡해 보여서 결함이 가려진다. cp949 에는 ⛔ 가 없어 리터럴 글자로 깨지고, 한글은
    cp949 2바이트로 나가 UTF-8 로 읽는 쪽(자가시험·훅 소비자)이 해독에 실패한다. 종료 코드(2)는
    그대로라 차단은 유지되지만 안내문이 소실·모지바케가 된다(2026-10-03 Kiki 머신 실측: 위치 7·0xc4).
    """
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):  # 재구성 불가한 스트림은 그대로 둔다(안내문 출력은 계속)
        pass


def main() -> int:
    _utf8_stderr()
    # 훅 입력은 UTF-8 JSON 이다. sys.stdin 은 로캘 인코딩(한국어 Windows = cp949)으로 해독하므로
    # 한글·'—' 가 섞인 명령에서 UnicodeDecodeError → 아래 except → **통과(fail-open)** 가 됐다
    # (2026-09-28 PYTHONIOENCODING=cp949 재현). 바이트로 읽어 UTF-8 로 직접 해독한다.
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"[guard_constitution] 입력 파싱 실패({type(exc).__name__}) — 통과", file=sys.stderr)
        return 0
    if not isinstance(data, dict):
        return 0
    reason = judge(data)
    if reason is None:
        return 0
    _log(
        {
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "session_id": data.get("session_id"),
            "tool": data.get("tool_name"),
            "reason": reason,
        }
    )
    print(f"{_ADVICE}\n  차단 사유: {reason}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
