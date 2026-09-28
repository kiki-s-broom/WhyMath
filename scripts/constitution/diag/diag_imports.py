# diag_imports.py — 모듈 경계·의존 방향 점검 (단계 S03·S04)
# 설정(diag_layers.json)의 계층 정의에 따라 다섯 가지를 찾는다:
#   ① 금지된 계층 간 import (예: 코어 → 수학 어댑터)      → 계획 PH1-12·GATE0, 헌법안 제7조의2
#   ② 코어·계약 계층에 들어온 수학 전용 라이브러리 (sympy 등)
#   ③ AI 게이트웨이 밖에서 AI SDK를 직접 호출하는 파일    → FZ-14 AI 호출 규약
#   ④ 허용 위치 밖에서 DB 드라이버를 직접 쓰는 파일
#   ⑤ 파이썬 모듈 사이의 순환 import
# Dart는 package:/상대 경로 import를 파일 경로로 풀어 같은 계층 규칙을 적용한다.
# 사용: python diag_imports.py --repo <저장소> --out <결과>/raw --config <결과>/diag_layers.json
from __future__ import annotations

import ast
import re
from collections import Counter, defaultdict
from pathlib import Path

from _diagcommon import (
    base_parser,
    check_paths,
    iter_files,
    load_config,
    match,
    md_table,
    read_text,
    rel,
    setup_console,
    write_outputs,
)

DEFAULT = {
    "python_roots": ["src", "backend", ""],  # 모듈 이름을 셀 기준 폴더 (앞에서부터 우선)
    "layers": {  # 계층 이름 → 경로 패턴 (먼저 맞는 계층으로 분류)
        "core": ["eos/core/**"],
        "contracts": ["eos/contracts/**"],
        "adapter_math": ["eos/adapters/math/**"],
        "app": ["eos/apps/**", "apps/**"],
    },
    "forbidden": [
        ["core", "adapter_math"],
        ["core", "app"],
        ["contracts", "adapter_math"],
        ["contracts", "app"],
        ["adapter_math", "app"],
    ],  # [출발, 도착]: 출발은 도착을 import 금지
    "math_only_libs": ["sympy", "latex2sympy2", "antlr4", "texteller", "mpmath"],
    "math_free_layers": ["core", "contracts"],
    "ai_sdks": [
        "anthropic",
        "openai",
        "google.generativeai",
        "google.genai",
        "ollama",
        "litellm",
        "langchain",
        "langchain_core",
        "groq",
        "mistralai",
        "cohere",
    ],
    "dart_ai_packages": [
        "google_generative_ai",
        "dart_openai",
        "openai_dart",
        "anthropic_sdk_dart",
        "langchain",
        "firebase_vertexai",
    ],
    "ai_gateway": ["eos/core/ai/**"],
    "db_drivers": [
        "psycopg",
        "psycopg2",
        "asyncpg",
        "sqlalchemy",
        "sqlite3",
        "pymongo",
        "supabase",
    ],
    "db_allowed": [
        "**/infra/**",
        "**/repository/**",
        "**/repositories/**",
        "**/db/**",
        "migrations/**",
        "scripts/**",
    ],
    "test_paths": [
        "tests/**",
        "**/tests/**",
        "**/test_*.py",
        "**/*_test.py",
        "**/*_test.dart",
        "**/integration_test/**",
    ],
}
DART_IMPORT = re.compile(r"""^\s*(?:import|export)\s+['"]([^'"]+)['"]""", re.M)


def layer_of(path: str, layers: dict) -> str | None:
    for name, pats in layers.items():
        if match(path, pats):
            return name
    return None


def lib_hit(fullname: str, libs) -> str | None:
    """'google.generativeai.types' 가 'google.generativeai' 목록에 해당하는지"""
    for lib in libs:
        if fullname == lib or fullname.startswith(lib + "."):
            return lib
    return None


def build_index(repo: Path, roots: list[str]):
    """파이썬 모듈 이름 → 파일, 파일 → 대표 모듈 이름"""
    index, file_mod = {}, {}
    for p in iter_files(repo, {".py"}):
        r = rel(p, repo)
        for root in roots:
            prefix = (root.strip("/") + "/") if root else ""
            if not r.startswith(prefix):
                continue
            mod = r[len(prefix) : -3].replace("/", ".")
            if mod == "__init__":
                continue
            if mod.endswith(".__init__"):
                mod = mod[: -len(".__init__")]
            index.setdefault(mod, r)
            file_mod.setdefault(r, mod)
    return index, file_mod


def resolve(name: str, index: dict) -> str | None:
    parts = name.split(".")
    for i in range(len(parts), 0, -1):
        cand = ".".join(parts[:i])
        if cand in index:
            return index[cand]
    return None


def py_imports(path: str, text: str, mod: str, index: dict):
    """(줄 번호, 내부 파일 또는 None, 외부 이름 또는 None) 목록"""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    is_pkg = path.endswith("__init__.py")
    base_parts = mod.split(".") if is_pkg else mod.split(".")[:-1]
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                found.append((node.lineno, resolve(a.name, index), a.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # 상대 import: from . import x
                keep = len(base_parts) - (node.level - 1)
                base = base_parts[:keep] if keep > 0 else []
                full = ".".join(base + ([node.module] if node.module else []))
                for a in node.names:
                    target = resolve(f"{full}.{a.name}" if full else a.name, index) or (
                        resolve(full, index) if full else None
                    )
                    found.append((node.lineno, target, None))
            elif node.module:
                for a in node.names:
                    target = resolve(f"{node.module}.{a.name}", index)
                    found.append((node.lineno, target, None if target else node.module))
    return [(ln, t, None if t else ext) for ln, t, ext in found]


def dart_packages(repo: Path) -> dict:
    """pubspec.yaml의 name → 패키지 폴더 (저장소 기준 상대 경로)"""
    pk = {}
    for p in iter_files(repo, {".yaml"}):
        if p.name == "pubspec.yaml":
            text = read_text(p) or ""
            m = re.search(r"^name:\s*([A-Za-z0-9_]+)", text, re.M)
            if m:
                folder = rel(p.parent, repo)
                pk[m.group(1)] = "" if folder in (".", "") else folder
    return pk


def dart_resolve(src: str, target: str, packages: dict) -> tuple[str | None, str | None]:
    """(내부 파일 경로, 외부 패키지 이름)"""
    if target.startswith("dart:"):
        return None, None
    if target.startswith("package:"):
        name, _, sub = target[len("package:") :].partition("/")
        if name in packages:
            base = packages[name]
            return (f"{base}/lib/{sub}" if base else f"lib/{sub}"), None
        return None, name
    parts = src.split("/")[:-1]
    for seg in target.split("/"):
        if seg == "..":
            parts = parts[:-1]
        elif seg != ".":
            parts.append(seg)
    return "/".join(parts), None


def tarjan(graph: dict) -> list[list[str]]:
    """강한 연결 요소 (크기 2 이상 = 순환 import 묶음). 재귀 없이 구현해 깊은 그래프도 안전."""
    index, low, on, stack, out, counter = {}, {}, set(), [], [], 0
    for start in graph:
        if start in index:
            continue
        index[start] = low[start] = counter
        counter += 1
        stack.append(start)
        on.add(start)
        work = [(start, iter(sorted(graph.get(start, ()))))]
        while work:
            v, it = work[-1]
            pushed = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on.add(w)
                    work.append((w, iter(sorted(graph.get(w, ())))))
                    pushed = True
                    break
                if w in on:
                    low[v] = min(low[v], index[w])
            if pushed:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[v])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                if len(comp) > 1:
                    out.append(sorted(comp))
    return sorted(out, key=len, reverse=True)


def main() -> int:
    setup_console()
    ap = base_parser("모듈 경계·의존 방향 점검")
    ap.add_argument("--config", type=Path, help="계층 설정 JSON (없으면 기본값: eos/core 등)")
    args = ap.parse_args()
    repo, out = args.repo, args.out
    check_paths(repo, out)
    cfg = load_config(args.config, DEFAULT)
    layers, forbidden = cfg["layers"], {tuple(x) for x in cfg["forbidden"]}

    index, file_mod = build_index(repo, cfg["python_roots"])
    graph = defaultdict(set)
    edges = Counter()
    violations, math_in_core, ai_calls, db_calls, unparsed = [], [], [], [], []
    layer_count = Counter()

    def record(src: str, line: int, target: str | None, external: str | None, lang: str):
        is_test = match(src, cfg["test_paths"])
        s_layer = layer_of(src, layers)
        if target:
            t_layer = layer_of(target, layers)
            if s_layer and t_layer and s_layer != t_layer:
                edges[(s_layer, t_layer)] += 1
            if (s_layer, t_layer) in forbidden:
                violations.append(
                    {
                        "src": f"{src}:{line}",
                        "target": target,
                        "rule": f"{s_layer} → {t_layer} 금지",
                        "test": is_test,
                        "lang": lang,
                    }
                )
        if external:
            if s_layer in cfg["math_free_layers"] and lib_hit(external, cfg["math_only_libs"]):
                math_in_core.append(
                    {"src": f"{src}:{line}", "lib": external, "layer": s_layer, "test": is_test}
                )
            ai = (
                lib_hit(external, cfg["ai_sdks"])
                if lang == "Python"
                else (external if external in cfg["dart_ai_packages"] else None)
            )
            if ai:
                ok = lang == "Python" and match(src, cfg["ai_gateway"])
                ai_calls.append(
                    {
                        "src": f"{src}:{line}",
                        "sdk": ai,
                        "gateway": ok,
                        "test": is_test,
                        "lang": lang,
                    }
                )
            db = lib_hit(external, cfg["db_drivers"]) if lang == "Python" else None
            if db:
                db_calls.append(
                    {
                        "src": f"{src}:{line}",
                        "driver": db,
                        "allowed": match(src, cfg["db_allowed"]),
                        "test": is_test,
                    }
                )

    # 파이썬
    n_py = 0
    for src, mod in sorted(file_mod.items()):
        n_py += 1
        layer_count[layer_of(src, layers) or "(미분류)"] += 1
        text = read_text(repo / src)
        imps = py_imports(src, text, mod, index) if text is not None else None
        if imps is None:
            unparsed.append(src)
            continue
        for line, target, external in imps:
            if target and target != src:
                graph[src].add(target)
            record(src, line, target, external, "Python")
    for node in list(graph):
        for t in graph[node]:
            graph.setdefault(t, set())
    cycles = tarjan(graph)

    # Dart
    packages = dart_packages(repo)
    n_dart = 0
    dart_external = Counter()
    for p in iter_files(repo, {".dart"}):
        src = rel(p, repo)
        n_dart += 1
        layer_count[layer_of(src, layers) or "(미분류)"] += 1
        text = read_text(p) or ""
        for m in DART_IMPORT.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            target, external = dart_resolve(src, m.group(1), packages)
            if external:
                dart_external[external] += 1
            record(src, line, target, external, "Dart")

    ai_bad = [a for a in ai_calls if not a["gateway"] and not a["test"]]
    db_bad = [d for d in db_calls if not d["allowed"] and not d["test"]]
    real_viol = [v for v in violations if not v["test"]]
    data = {
        "config": cfg,
        "python_files": n_py,
        "dart_files": n_dart,
        "dart_packages": packages,
        "layer_files": dict(layer_count),
        "layer_edges": [{"from": a, "to": b, "count": c} for (a, b), c in edges.most_common()],
        "violations": violations,
        "math_libs_in_core": math_in_core,
        "ai_sdk_calls": ai_calls,
        "db_driver_calls": db_calls,
        "cycles": cycles,
        "unparsed_python": unparsed,
        "dart_external_packages": dict(dart_external.most_common()),
        "summary": {
            "forbidden_imports": len(real_viol),
            "forbidden_imports_in_tests": len(violations) - len(real_viol),
            "math_libs_in_core": len([m for m in math_in_core if not m["test"]]),
            "ai_calls_outside_gateway": len(ai_bad),
            "db_calls_outside_allowed": len(db_bad),
            "import_cycles": len(cycles),
            "unassigned_files": layer_count.get("(미분류)", 0),
        },
    }
    s = data["summary"]
    md = [
        "# 모듈 경계·의존 방향 점검\n",
        f"대상: `{repo}` · Python {n_py}개 · Dart {n_dart}개 · 설정: `{args.config or '기본값'}`\n",
        "> 계층 분류가 틀리면 결과도 틀립니다. '(미분류)' 파일이 많으면 설정의 layers 패턴을 먼저 고치세요.\n",
        md_table(
            ["항목", "값"],
            [
                ["⛔ 금지된 계층 간 import (테스트 제외)", s["forbidden_imports"]],
                ["⛔ 코어·계약 계층의 수학 전용 라이브러리", s["math_libs_in_core"]],
                ["⛔ AI 게이트웨이 밖 AI SDK 직접 사용", s["ai_calls_outside_gateway"]],
                ["허용 위치 밖 DB 드라이버 사용", s["db_calls_outside_allowed"]],
                ["순환 import 묶음", s["import_cycles"]],
                ["계층 미분류 파일", s["unassigned_files"]],
                ["문법 오류로 분석 못 한 파이썬 파일", len(unparsed)],
            ],
        ),
        "\n## 계층별 파일 수\n",
        md_table(["계층", "파일 수"], sorted(layer_count.items())),
        "\n## 계층 사이 import 횟수 (출발 → 도착)\n",
        md_table(
            ["출발", "도착", "횟수"],
            [[e["from"], e["to"], e["count"]] for e in data["layer_edges"]],
        ),
        "\n## 금지된 import\n",
        md_table(
            ["위치", "대상", "규칙", "테스트"],
            [[v["src"], v["target"], v["rule"], "예" if v["test"] else ""] for v in violations],
            60,
        ),
        "\n## 코어·계약 계층의 수학 전용 라이브러리\n",
        md_table(
            ["위치", "라이브러리", "계층"],
            [[m["src"], m["lib"], m["layer"]] for m in math_in_core],
            40,
        ),
        "\n## AI SDK 사용 위치\n",
        md_table(
            ["위치", "SDK", "게이트웨이 안", "언어"],
            [
                [a["src"], a["sdk"], "예" if a["gateway"] else "⛔ 아니오", a["lang"]]
                for a in ai_calls
            ],
            60,
        ),
        "\n## DB 드라이버 사용 위치\n",
        md_table(
            ["위치", "드라이버", "허용 위치"],
            [[d["src"], d["driver"], "예" if d["allowed"] else "아니오"] for d in db_calls],
            60,
        ),
        "\n## 순환 import 묶음\n",
        md_table(["크기", "파일들"], [[len(c), ", ".join(c[:6])] for c in cycles], 20),
    ]
    write_outputs(out, "diag_imports", data, "\n".join(md) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
