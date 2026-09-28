# diag_integrity.py — 파일 무결성·드리프트 점검 (단계 S01)
# 보는 것: NUL 바이트(KR-02 쓰기 손상), UTF-8이 아닌 파일, 문법이 깨진 .py/.json/.jsonl/.yaml,
#          빈 파일, 버전 꼬리표 파일(KR-03 _v2·최종·복사본), 내용이 똑같은 중복 파일,
#          큰 파일, 최상위 폴더·언어별 코드 줄 수
# 사용: python diag_integrity.py --repo <저장소> --out <결과폴더>/raw
from __future__ import annotations

import ast
import hashlib
import json
import re
from collections import Counter, defaultdict

from _diagcommon import (
    base_parser,
    check_paths,
    iter_files,
    md_table,
    rel,
    setup_console,
    write_outputs,
)

LANG = {
    ".py": "Python",
    ".dart": "Dart",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".sql": "SQL",
    ".html": "HTML",
    ".css": "CSS",
    ".sh": "Shell",
    ".ps1": "PowerShell",
    ".kt": "Kotlin",
    ".swift": "Swift",
}
DATA = {
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".toml",
    ".csv",
    ".tsv",
    ".md",
    ".txt",
    ".ini",
    ".cfg",
    ".xml",
}
TEXT = set(LANG) | DATA | {".pyi", ".cjs", ".bat", ".gradle", ".env", ".example"}
TEXT_NAMES = {"Dockerfile", "Makefile", ".gitignore", ".env"}
VERSION_KO = re.compile(r"(최종|완성|수정본|복사본|최신본|백업)")
VERSION_EN = re.compile(
    r"(?i)(_v\d+$|_v\d+[_\-.]|(^|[_\-\s.])(final|old|backup|bak|copy|orig)($|[_\-\s.\d])|\(\d+\)$)"
)
VERSION_EXT = {".bak", ".orig", ".old", ".tmp"}
DUP_MIN = 1024  # 1KB 미만(빈 __init__.py 등)은 중복 검사 제외
BIG = 5 * 1024 * 1024  # 5MB 이상은 '큰 파일'로 표시

try:
    import yaml  # PyYAML이 있으면 YAML 문법도 검사
except ImportError:
    yaml = None


def main() -> int:
    setup_console()
    ap = base_parser("파일 무결성·드리프트 점검")
    args = ap.parse_args()
    repo, out = args.repo, args.out
    check_paths(repo, out)

    nul, non_utf8, parse_err, empty, versioned, big = [], [], [], [], [], []
    hashes = defaultdict(list)
    dirs = defaultdict(lambda: {"files": 0, "loc": Counter()})
    loc_total = Counter()
    n_files = n_text = yaml_skipped = 0

    for p in iter_files(repo):
        r = rel(p, repo)
        n_files += 1
        top = r.split("/")[0] if "/" in r else "(최상위)"
        dirs[top]["files"] += 1
        try:
            size = p.stat().st_size
            raw = p.read_bytes() if size <= 50 * 1024 * 1024 else None
        except OSError as e:
            parse_err.append({"path": r, "kind": "읽기", "line": 0, "msg": str(e)})
            continue
        ext = p.suffix.lower()
        if size == 0 and p.name not in ("__init__.py", ".gitkeep"):
            empty.append(r)
        if size >= BIG:
            big.append({"path": r, "mb": round(size / 1024 / 1024, 1)})
        if ext in VERSION_EXT or VERSION_KO.search(p.stem) or VERSION_EN.search(p.stem):
            versioned.append(r)
        if raw is not None and size >= DUP_MIN:
            hashes[hashlib.sha256(raw).hexdigest()].append(r)
        if raw is None or not (ext in TEXT or p.name in TEXT_NAMES):
            continue
        n_text += 1
        if b"\x00" in raw:
            nul.append({"path": r, "count": raw.count(b"\x00")})
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            guess = "cp949로 읽힘" if _decodes(raw, "cp949") else "인코딩 불명"
            non_utf8.append({"path": r, "guess": guess})
            continue
        if ext in LANG:
            n = sum(1 for line in text.splitlines() if line.strip())
            dirs[top]["loc"][LANG[ext]] += n
            loc_total[LANG[ext]] += n
        # 문법 검사
        if ext == ".py":
            try:
                ast.parse(text, filename=r)
            except SyntaxError as e:
                parse_err.append({"path": r, "kind": "Python", "line": e.lineno or 0, "msg": e.msg})
            except ValueError as e:  # 'source code cannot contain null bytes'
                parse_err.append({"path": r, "kind": "Python", "line": 0, "msg": str(e)})
        elif ext == ".json":
            try:
                json.loads(text)
            except json.JSONDecodeError as e:
                parse_err.append({"path": r, "kind": "JSON", "line": e.lineno, "msg": e.msg})
        elif ext == ".jsonl":
            for i, line in enumerate(text.splitlines(), 1):
                if line.strip():
                    try:
                        json.loads(line)
                    except json.JSONDecodeError as e:
                        parse_err.append({"path": r, "kind": "JSONL", "line": i, "msg": e.msg})
                        break
        elif ext in (".yaml", ".yml"):
            if yaml is None:
                yaml_skipped += 1
            else:
                try:
                    list(yaml.safe_load_all(text))
                except yaml.YAMLError as e:
                    mark = getattr(e, "problem_mark", None)
                    parse_err.append(
                        {
                            "path": r,
                            "kind": "YAML",
                            "line": (mark.line + 1) if mark else 0,
                            "msg": str(getattr(e, "problem", e)),
                        }
                    )

    dups = sorted((sorted(v) for v in hashes.values() if len(v) > 1), key=lambda g: (-len(g), g[0]))
    data = {
        "repo": str(repo),
        "summary": {
            "files": n_files,
            "text_files": n_text,
            "loc_by_lang": dict(loc_total.most_common()),
            "nul_files": len(nul),
            "non_utf8": len(non_utf8),
            "parse_errors": len(parse_err),
            "empty_files": len(empty),
            "version_tagged": len(versioned),
            "duplicate_groups": len(dups),
            "big_files": len(big),
            "yaml_checked": yaml is not None,
            "yaml_skipped": yaml_skipped,
        },
        "nul_files": nul,
        "non_utf8": non_utf8,
        "parse_errors": parse_err,
        "empty_files": empty,
        "version_tagged": versioned,
        "duplicates": dups,
        "big_files": big,
        "dirs": [
            {"dir": d, "files": v["files"], "loc": dict(v["loc"])} for d, v in sorted(dirs.items())
        ],
    }
    s = data["summary"]
    md = [
        f"# 파일 무결성·드리프트 점검\n\n대상: `{repo}`\n",
        md_table(
            ["항목", "값"],
            [
                ["전체 파일 / 텍스트 파일", f"{s['files']} / {s['text_files']}"],
                [
                    "코드 줄 수(빈 줄 제외)",
                    ", ".join(f"{k} {v:,}" for k, v in s["loc_by_lang"].items()) or "-",
                ],
                ["⛔ NUL 바이트 포함 파일 (KR-02 쓰기 손상 의심)", s["nul_files"]],
                ["⛔ 문법 오류 (Python·JSON·JSONL·YAML)", s["parse_errors"]],
                ["UTF-8이 아닌 텍스트 파일", s["non_utf8"]],
                ["버전 꼬리표 파일 (KR-03 드리프트)", s["version_tagged"]],
                ["내용이 같은 중복 파일 묶음", s["duplicate_groups"]],
                ["빈 파일", s["empty_files"]],
                ["5MB 이상 큰 파일", s["big_files"]],
                [
                    "YAML 검사",
                    "실행" if s["yaml_checked"] else f"건너뜀 (PyYAML 없음, {s['yaml_skipped']}개)",
                ],
            ],
        ),
        "\n## NUL 바이트 포함 파일\n",
        md_table(["파일", "NUL 개수"], [[x["path"], x["count"]] for x in nul], 50),
        "\n## 문법 오류\n",
        md_table(
            ["파일", "종류", "줄", "내용"],
            [[x["path"], x["kind"], x["line"], x["msg"]] for x in parse_err],
            50,
        ),
        "\n## UTF-8이 아닌 파일\n",
        md_table(["파일", "추정"], [[x["path"], x["guess"]] for x in non_utf8], 50),
        "\n## 버전 꼬리표 파일\n",
        md_table(["파일"], [[x] for x in versioned], 50),
        "\n## 중복 파일 묶음 (같은 내용)\n",
        md_table(["개수", "파일들"], [[len(g), ", ".join(g[:4])] for g in dups], 30),
        "\n## 최상위 폴더별 규모\n",
        md_table(
            ["폴더", "파일 수", "코드 줄 수"],
            [
                [d["dir"], d["files"], ", ".join(f"{k} {v:,}" for k, v in d["loc"].items()) or "-"]
                for d in data["dirs"]
            ],
        ),
    ]
    write_outputs(out, "diag_integrity", data, "\n".join(md) + "\n")
    return 0


def _decodes(raw: bytes, enc: str) -> bool:
    try:
        raw.decode(enc)
        return True
    except UnicodeDecodeError:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
