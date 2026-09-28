# diag_rules_scan.py — 코딩 규칙 스캔 (단계 S03)
# 운용 지침서·헌법·표준북의 '기계로 셀 수 있는' 규칙을 센다. 판정은 사람이 하고, 이 도구는 증거만 모은다.
#   korean     : 한국어 주석 비율, 코드 30줄 이상인데 한국어 주석이 0인 파일        (CR-04)
#   print      : 백엔드 코드의 print() 사용                                         (R15-01안)
#   except     : 맨 except·예외 삼키기·로그 없는 광범위 except, Dart 빈 catch       (CR-02)
#   secrets    : API 키·age 비밀키·DB 비밀번호 패턴 (값은 가려서 표시)             (CR-03, R8-01안)
#   danger     : eval·exec·sympify·parse_expr·pickle·yaml.load·shell=True           (CR-03, R22-03안, KR-06)
#   sql        : f-string·% 로 만든 SQL을 execute에 넘기는 곳 (SQL 인젝션 위험)     (CR-03)
#   destructive: 코드 안의 TRUNCATE·DROP·WHERE 없는 DELETE                          (KR-06, R23-01안)
#   magic      : 숙달·추천·진단 기준값 숫자가 여러 파일에 흩어진 곳                 (헌법 제7조 단일 원본)
#   size       : 800줄 넘는 파일, 80줄 넘는 파이썬 함수
#   todo       : TODO·FIXME·HACK 표식 수
# 사용: python diag_rules_scan.py --repo <저장소> --out <결과>/raw [--only secrets,danger] [--history]
from __future__ import annotations

import ast
import io
import re
import tokenize
from collections import Counter, defaultdict

from _diagcommon import (
    base_parser,
    check_paths,
    git,
    iter_files,
    match,
    md_table,
    read_text,
    rel,
    setup_console,
    tracked_files,
    write_outputs,
)

CODE_EXT = {
    ".py": "Python",
    ".dart": "Dart",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".jsx": "JavaScript",
    ".tsx": "TypeScript",
    ".sql": "SQL",
}
SCAN_EXT = set(CODE_EXT) | {
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".env",
    ".md",
    ".txt",
    ".sh",
    ".ps1",
    ".bat",
    ".xml",
    ".gradle",
    ".properties",
    ".example",
}
SKIP_NAMES = {
    "package-lock.json",
    "pubspec.lock",
    "poetry.lock",
    "yarn.lock",
    "uv.lock",
    "Pipfile.lock",
}
HANGUL = re.compile(r"[가-힣]")
TODO = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b")
TEST_PATHS = [
    "tests/**",
    "**/tests/**",
    "**/test_*.py",
    "**/*_test.py",
    "**/*_test.dart",
    "**/integration_test/**",
]
PRINT_OK = [
    "scripts/**",
    "tools/**",
    "**/cli*.py",
    "**/__main__.py",
    "notebooks/**",
    "migrations/**",
    "**/manage.py",
]
LOG_CALL = re.compile(r"(?i)(log|logger|warn|error|exception|critical|print|capture)")

SECRETS = [
    ("Anthropic API 키", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"), 0),
    ("OpenAI API 키", re.compile(r"sk-(?!ant-)(?:proj-)?[A-Za-z0-9_\-]{32,}"), 0),
    ("Google API 키", re.compile(r"AIza[0-9A-Za-z_\-]{35}"), 0),
    ("AWS 액세스 키", re.compile(r"AKIA[0-9A-Z]{16}"), 0),
    ("GitHub 토큰", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"), 0),
    ("age 비밀키 (백업 복호화 키)", re.compile(r"AGE-SECRET-KEY-1[0-9A-Z]{50,}"), 0),
    ("개인 키 파일", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |)PRIVATE KEY-----"), 0),
    (
        "DB 접속 문자열 속 비밀번호",
        re.compile(r"postgres(?:ql)?(?:\+\w+)?://[^:\s/'\"@]+:([^@\s'\"]+)@"),
        1,
    ),
    (
        "비밀번호·토큰 직접 대입",
        re.compile(
            r"(?i)\b(password|passwd|pwd|secret|api_key|apikey|access_token|auth_token)\s*[:=]\s*['\"]([^'\"\s]{6,})['\"]"
        ),
        2,
    ),
]
PLACEHOLDER = re.compile(
    r"(?i)(x{4,}|your|example|dummy|changeme|placeholder|<[^>]*>|\.\.\.|\$\{|\{\{|environ|getenv|test|sample|fake|\*{3,}|^password$|^secret$)"
)
DESTRUCTIVE = [
    ("TRUNCATE", re.compile(r"(?i)\btruncate\s+(?:table\s+)?[\"\w]")),
    ("DROP", re.compile(r"(?i)\bdrop\s+(?:table|schema|database)\b")),
    ("WHERE 없는 DELETE", re.compile(r"(?i)\bdelete\s+from\s+[\w.\"]+\s*(?:;|\"|'|$)")),
]
MAGIC_KEY = re.compile(
    r"(?i)(mastery|master|숙달|threshold|임계|p_known|\bp_l\b|guess|slip|bkt|akt|recommend|추천|prereq|선수|diagnos|진단|cutoff|기준값)"
)
MAGIC_NUM = re.compile(r"(?<![\w.])(0\.\d{1,3}|1\.0)(?![\w.])")
ALL_CHECKS = [
    "korean",
    "print",
    "except",
    "secrets",
    "danger",
    "sql",
    "destructive",
    "magic",
    "size",
    "todo",
]


def mask(v: str) -> str:
    return f"{v[:4]}…({len(v)}자)"


def py_comments(text: str):
    """(코드 줄 수, 주석 수, 한국어 주석 수, TODO 수) — 토큰 단위로 정확히 센다. 실패하면 None."""
    code_lines, comments, korean, todo = set(), 0, 0, 0
    skip = {
        tokenize.COMMENT,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENCODING,
        tokenize.ENDMARKER,
    }
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                comments += 1
                korean += bool(HANGUL.search(tok.string))
                todo += bool(TODO.search(tok.string))
            elif tok.type not in skip:
                code_lines.update(range(tok.start[0], tok.end[0] + 1))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return None
    try:  # docstring(함수·클래스 설명문)도 한국어 설명으로 인정
        tree = ast.parse(text)
        for node in [tree] + [
            n
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ]:
            doc = ast.get_docstring(node)
            if doc:
                comments += 1
                korean += bool(HANGUL.search(doc))
    except (SyntaxError, ValueError):
        pass
    return len(code_lines), comments, korean, todo


def line_comment_index(line: str, marker: str) -> int:
    """따옴표 밖에 있는 주석 표식 위치 (없으면 -1). URL의 '//'는 문자열 안이라 제외된다."""
    quote, i = None, 0
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in ("'", '"', "`"):
            quote = ch
        elif line.startswith(marker, i):
            return i
        i += 1
    return -1


def c_comments(text: str, marker: str):
    """Dart·JS·TS(//, /* */)·SQL(--) 주석 세기 (근사치)"""
    code = comments = korean = todo = 0
    in_block = False
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue
        if in_block or (marker == "//" and s.startswith("/*")):
            comments += 1
            korean += bool(HANGUL.search(s))
            todo += bool(TODO.search(s))
            in_block = "*/" not in s[2:] if not in_block else "*/" not in s
            continue
        if s.startswith(marker):
            comments += 1
            korean += bool(HANGUL.search(s))
            todo += bool(TODO.search(s))
            continue
        code += 1
        idx = line_comment_index(raw, marker)
        if idx >= 0:
            comments += 1
            korean += bool(HANGUL.search(raw[idx:]))
            todo += bool(TODO.search(raw[idx:]))
    return code, comments, korean, todo


def call_name(func) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        base = func.value.id if isinstance(func.value, ast.Name) else ""
        return f"{base}.{func.attr}" if base else func.attr
    return ""


def py_ast_checks(path: str, text: str, want: set, res: dict, is_test: bool) -> None:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return
    printable = not is_test and not match(path, PRINT_OK)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = call_name(node.func)
            short = name.split(".")[-1]
            if "print" in want and name == "print" and printable:
                res["print"][path] += 1
            if "danger" in want:
                kw = {k.arg: k.value for k in node.keywords if k.arg}
                hit = None
                if short in ("eval", "exec") and "." not in name:
                    hit = short
                elif short in ("sympify", "parse_expr", "parse_latex"):
                    hit = f"{short} (내부적으로 eval — 학생 입력이면 위험)"
                elif name in ("pickle.loads", "pickle.load", "dill.loads", "marshal.loads"):
                    hit = name
                elif name == "yaml.load" and not (
                    isinstance(kw.get("Loader"), (ast.Name, ast.Attribute))
                    and "Safe" in call_name(kw["Loader"])
                ):
                    hit = "yaml.load (SafeLoader 아님)"
                elif name in ("os.system", "os.popen"):
                    hit = name
                elif (
                    short in ("run", "call", "Popen", "check_output", "check_call")
                    and isinstance(kw.get("shell"), ast.Constant)
                    and kw["shell"].value is True
                ):
                    hit = f"{name}(shell=True)"
                if hit:
                    res["danger"].append(
                        {"loc": f"{path}:{node.lineno}", "call": hit, "test": is_test}
                    )
            if (
                "sql" in want
                and short in ("execute", "executemany", "exec_driver_sql", "mogrify", "text")
                and node.args
            ):
                a = node.args[0]
                risky = (
                    isinstance(a, ast.JoinedStr)
                    or (isinstance(a, ast.BinOp) and isinstance(a.op, (ast.Mod, ast.Add)))
                    or (
                        isinstance(a, ast.Call)
                        and isinstance(a.func, ast.Attribute)
                        and a.func.attr == "format"
                    )
                )
                if risky:
                    res["sql"].append(
                        {"loc": f"{path}:{node.lineno}", "call": short, "test": is_test}
                    )
        if "except" in want and isinstance(node, ast.ExceptHandler):
            t = node.type
            names = (
                [
                    e.id
                    for e in (t.elts if isinstance(t, ast.Tuple) else [t])
                    if isinstance(e, ast.Name)
                ]
                if t
                else []
            )
            broad = t is None or any(n in ("Exception", "BaseException") for n in names)
            trivial = all(
                isinstance(s, ast.Pass)
                or (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
                for s in node.body
            )
            if t is None:
                kind = "맨 except: (모든 오류를 잡음)"
            elif broad and trivial:
                kind = "예외 삼키기 (except Exception: pass)"
            elif (
                broad
                and not any(isinstance(s, ast.Raise) for s in ast.walk(node))
                and not any(
                    isinstance(s, ast.Call) and LOG_CALL.search(call_name(s.func))
                    for s in ast.walk(node)
                )
            ):
                kind = "로그·재발생 없는 광범위 except"
            else:
                kind = None
            if kind:
                res["except"].append(
                    {"loc": f"{path}:{node.lineno}", "kind": kind, "test": is_test}
                )
        if "size" in want and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            length = (getattr(node, "end_lineno", node.lineno) or node.lineno) - node.lineno + 1
            if length > 80:
                res["long_functions"].append(
                    {"loc": f"{path}:{node.lineno}", "name": node.name, "lines": length}
                )


def main() -> int:
    setup_console()
    ap = base_parser("코딩 규칙 스캔")
    ap.add_argument("--only", default=",".join(ALL_CHECKS), help="실행할 검사 (쉼표 구분)")
    ap.add_argument(
        "--history",
        action="store_true",
        help="git 이력의 추가된 줄에서도 비밀값 검색 (느릴 수 있음)",
    )
    ap.add_argument("--since", default="2026-05-01", help="--history 검색 시작일")
    args = ap.parse_args()
    repo, out = args.repo, args.out
    check_paths(repo, out)
    want = {c.strip() for c in args.only.split(",") if c.strip()}
    tracked = tracked_files(repo)

    res = {
        "files": [],
        "print": Counter(),
        "except": [],
        "secrets": [],
        "danger": [],
        "sql": [],
        "destructive": [],
        "magic": defaultdict(list),
        "big_files": [],
        "long_functions": [],
        "todo": Counter(),
        "dart_empty_catch": [],
        "unreadable": [],
    }
    placeholder_hits = 0
    ignored_cache: dict[str, bool] = {}
    for p in iter_files(repo):
        r = rel(p, repo)
        is_env = p.name.startswith(".env")  # .env, .env.local, .env.production 등
        if p.name in SKIP_NAMES or not (p.suffix.lower() in SCAN_EXT or is_env):
            continue
        text = read_text(p, limit_mb=2)
        if text is None:
            continue
        ext = p.suffix.lower()
        is_test = match(r, TEST_PATHS)
        lang = CODE_EXT.get(ext)
        top = r.split("/")[0] if "/" in r else "(최상위)"

        if "secrets" in want:
            for label, pat, grp in SECRETS:
                for m in pat.finditer(text):
                    value = m.group(grp) if grp else m.group(0)
                    if PLACEHOLDER.search(value):
                        placeholder_hits += 1
                        continue
                    line = text.count("\n", 0, m.start()) + 1
                    if tracked is not None and r in tracked:
                        state = "⛔ git 추적 중"
                    elif tracked is None:
                        state = "git 아님"
                    else:  # 추적 안 되는 파일: .gitignore에 있으면 안전, 없으면 실수로 커밋될 위험
                        if r not in ignored_cache:
                            ignored_cache[r] = git(repo, "check-ignore", "-q", r)[0] == 0
                        state = (
                            "추적 안 됨 (.gitignore 등록)"
                            if ignored_cache[r]
                            else "⚠️ 추적 안 됨 (.gitignore에 없음 — 커밋될 위험)"
                        )
                    res["secrets"].append(
                        {"loc": f"{r}:{line}", "kind": label, "value": mask(value), "git": state}
                    )
        if not lang:
            continue
        n_lines = text.count("\n") + 1
        if "size" in want and n_lines > 800:
            res["big_files"].append({"path": r, "lines": n_lines})
        if "korean" in want or "todo" in want:
            stats = (
                py_comments(text)
                if lang == "Python"
                else c_comments(text, "--" if lang == "SQL" else "//")
            )
            if stats is None:
                res["unreadable"].append(r)
            else:
                code, comments, korean, todo = stats
                res["files"].append(
                    {
                        "path": r,
                        "lang": lang,
                        "code": code,
                        "comments": comments,
                        "korean": korean,
                        "test": is_test,
                    }
                )
                res["todo"][top] += todo
        if lang == "Python":
            py_ast_checks(r, text, want, res, is_test)
        if lang == "Dart" and "except" in want:
            for m in re.finditer(r"catch\s*\([^)]*\)\s*\{\s*\}", text):
                res["dart_empty_catch"].append(f"{r}:{text.count(chr(10), 0, m.start()) + 1}")
        if "destructive" in want:
            for i, line in enumerate(text.splitlines(), 1):
                for label, pat in DESTRUCTIVE:
                    if pat.search(line):
                        res["destructive"].append(
                            {
                                "loc": f"{r}:{i}",
                                "kind": label,
                                "migration": match(r, ["migrations/**", "**/migrations/**"]),
                                "test": is_test,
                                "text": line.strip()[:100],
                            }
                        )
        if "magic" in want and not is_test:
            for i, line in enumerate(text.splitlines(), 1):
                if MAGIC_KEY.search(line):
                    for m in MAGIC_NUM.finditer(line):
                        res["magic"][m.group(1)].append(
                            {"loc": f"{r}:{i}", "file": r, "text": line.strip()[:100]}
                        )

    history = []
    if args.history and "secrets" in want:
        code, logp = git(
            repo,
            "log",
            "-p",
            "--no-color",
            "-U0",
            f"--since={args.since}",
            "--pretty=format:@@COMMIT %h %ad",
            "--date=short",
            timeout=900,
        )
        commit = ""
        for line in logp.splitlines():
            if line.startswith("@@COMMIT"):
                commit = line[9:]
            elif line.startswith("+") and not line.startswith("+++"):
                for label, pat, grp in SECRETS:
                    m = pat.search(line)
                    if m:
                        value = m.group(grp) if grp else m.group(0)
                        if not PLACEHOLDER.search(value):
                            history.append({"commit": commit, "kind": label, "value": mask(value)})

    files = res["files"]
    no_korean = [f for f in files if f["code"] >= 30 and f["korean"] == 0 and not f["test"]]
    # '희박': 코드 50줄 이상인데 한국어 주석이 100줄당 2개 미만 (0개인 파일은 위 목록에 이미 있음)
    sparse = [
        dict(f, per100=round(f["korean"] * 100 / f["code"], 1))
        for f in files
        if f["code"] >= 50 and 0 < f["korean"] * 100 / f["code"] < 2 and not f["test"]
    ]
    code_files = [f for f in files if not f["test"]]
    total_comments = sum(f["comments"] for f in code_files)
    korean_rate = (
        round(sum(f["korean"] for f in code_files) / total_comments, 3) if total_comments else None
    )
    magic_dup = {
        v: sorted({x["file"] for x in hits})
        for v, hits in res["magic"].items()
        if len({x["file"] for x in hits}) >= 2
    }
    real = lambda xs: [x for x in xs if not x.get("test")]
    data = {
        "checks": sorted(want),
        "summary": {
            "code_files": len(code_files),
            "korean_comment_rate": korean_rate,
            "files_without_korean_comments": len(no_korean),
            "files_sparse_korean": len(sparse),
            "print_calls": sum(res["print"].values()),
            "except_issues": len(real(res["except"])),
            "dart_empty_catch": len(res["dart_empty_catch"]),
            "secrets": len(res["secrets"]),
            "secrets_tracked": len([s for s in res["secrets"] if "추적 중" in s["git"]]),
            "secrets_in_history": len(history),
            "placeholders_ignored": placeholder_hits,
            "danger_calls": len(real(res["danger"])),
            "sql_building": len(real(res["sql"])),
            "destructive_sql": len(
                [d for d in res["destructive"] if not d["migration"] and not d["test"]]
            ),
            "magic_values_scattered": len(magic_dup),
            "big_files": len(res["big_files"]),
            "long_functions": len(res["long_functions"]),
            "todo_markers": sum(res["todo"].values()),
            "unreadable": len(res["unreadable"]),
        },
        "files_without_korean_comments": no_korean,
        "files_sparse_korean": sparse,
        "print_by_file": dict(res["print"].most_common()),
        "except": res["except"],
        "dart_empty_catch": res["dart_empty_catch"],
        "secrets": res["secrets"],
        "secrets_in_history": history,
        "danger": res["danger"],
        "sql": res["sql"],
        "destructive": res["destructive"],
        "magic_scattered": magic_dup,
        "magic_all": dict(res["magic"]),
        "big_files": res["big_files"],
        "long_functions": res["long_functions"],
        "todo_by_dir": dict(res["todo"]),
        "unreadable": res["unreadable"],
    }
    s = data["summary"]
    md = [
        "# 코딩 규칙 스캔\n",
        f"대상: `{repo}` · 검사: {', '.join(sorted(want))}\n",
        "> 이 도구는 '셀 수 있는 증거'만 모읍니다. 위반 여부·심각도 판정은 진단 단계의 사람·AI가 코드를 보고 확정합니다.\n",
        md_table(
            ["항목 (근거 규칙)", "값"],
            [
                [
                    "한국어 주석 비율 (CR-04, 테스트 제외)",
                    f"{korean_rate:.0%}" if korean_rate is not None else "-",
                ],
                [
                    "코드 30줄 이상인데 한국어 주석 0인 파일 (CR-04)",
                    s["files_without_korean_comments"],
                ],
                [
                    "코드 50줄 이상인데 한국어 주석이 100줄당 2개 미만인 파일",
                    s["files_sparse_korean"],
                ],
                ["⛔ git이 추적하는 파일 속 비밀값 (CR-03)", s["secrets_tracked"]],
                [
                    "추적 안 되는 파일 속 비밀값 (.env 등 — .gitignore 확인)",
                    s["secrets"] - s["secrets_tracked"],
                ],
                [
                    "git 이력 속 비밀값 (--history)",
                    s["secrets_in_history"] if args.history else "미실행",
                ],
                ["위험 호출 eval·sympify·parse_expr 등 (CR-03, KR-06)", s["danger_calls"]],
                ["문자열로 조립한 SQL 실행 (SQL 인젝션 위험)", s["sql_building"]],
                [
                    "코드 속 TRUNCATE·DROP·WHERE 없는 DELETE (마이그레이션·테스트 제외)",
                    s["destructive_sql"],
                ],
                [
                    "예외 처리 문제 (CR-02, 테스트 제외) / Dart 빈 catch",
                    f"{s['except_issues']} / {s['dart_empty_catch']}",
                ],
                ["백엔드 print() 호출 (R15-01안)", s["print_calls"]],
                ["여러 파일에 흩어진 기준값 숫자 (헌법 제7조)", s["magic_values_scattered"]],
                ["800줄 넘는 파일 / 80줄 넘는 함수", f"{s['big_files']} / {s['long_functions']}"],
                ["TODO·FIXME·HACK 표식", s["todo_markers"]],
            ],
        ),
        "\n## 비밀값 (값은 앞 4자만)\n",
        md_table(
            ["위치", "종류", "값", "git"],
            [[x["loc"], x["kind"], x["value"], x["git"]] for x in res["secrets"]],
            40,
        ),
        "\n## git 이력 속 비밀값\n",
        (
            md_table(
                ["커밋", "종류", "값"], [[h["commit"], h["kind"], h["value"]] for h in history], 40
            )
            if args.history
            else "_(미실행)_"
        ),
        "\n## 위험 호출\n",
        md_table(
            ["위치", "호출", "테스트"],
            [[x["loc"], x["call"], "예" if x["test"] else ""] for x in res["danger"]],
            40,
        ),
        "\n## 문자열로 조립한 SQL\n",
        md_table(["위치", "호출"], [[x["loc"], x["call"]] for x in res["sql"]], 40),
        "\n## 파괴적 SQL\n",
        md_table(
            ["위치", "종류", "마이그레이션", "내용"],
            [
                [x["loc"], x["kind"], "예" if x["migration"] else "", x["text"]]
                for x in res["destructive"]
            ],
            40,
        ),
        "\n## 흩어진 기준값 (같은 숫자가 2개 이상 파일에)\n",
        md_table(
            ["값", "파일 수", "파일"],
            [[v, len(fs), ", ".join(fs[:5])] for v, fs in sorted(magic_dup.items())],
        ),
        "\n## 한국어 주석이 없는 파일 (코드 30줄 이상)\n",
        md_table(
            ["파일", "언어", "코드 줄", "주석 수"],
            [
                [f["path"], f["lang"], f["code"], f["comments"]]
                for f in sorted(no_korean, key=lambda f: -f["code"])
            ],
            50,
        ),
        "\n## 한국어 주석이 희박한 파일 (100줄당 2개 미만)\n",
        md_table(
            ["파일", "코드 줄", "한국어 주석", "100줄당"],
            [
                [f["path"], f["code"], f["korean"], f["per100"]]
                for f in sorted(sparse, key=lambda f: f["per100"])
            ],
            30,
        ),
        "\n## 예외 처리 문제\n",
        md_table(["위치", "종류"], [[x["loc"], x["kind"]] for x in real(res["except"])], 40),
        "\n## print() 사용 파일\n",
        md_table(["파일", "횟수"], res["print"].most_common(), 30),
        "\n## 긴 함수 (80줄 초과)\n",
        md_table(
            ["위치", "함수", "줄 수"],
            [
                [x["loc"], x["name"], x["lines"]]
                for x in sorted(res["long_functions"], key=lambda x: -x["lines"])
            ],
            30,
        ),
    ]
    write_outputs(out, "diag_rules_scan", data, "\n".join(md) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
