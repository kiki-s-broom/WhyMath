# _diagcommon.py — 진단 도구 공통 함수
# 원칙: 표준 라이브러리만 사용 (설치 불필요), 진단 대상 저장소는 '읽기만' 한다.
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys
from pathlib import Path

# 들여다보지 않을 폴더 (의존성·캐시·빌드 산출물)
EXCLUDE_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".dart_tool",
    "build",
    "dist",
    ".idea",
    ".vscode",
    ".gradle",
    "Pods",
    ".next",
    "coverage",
    "site-packages",
    ".tox",
    ".cache",
    "htmlcov",
}
KEEP_HIDDEN = {".github", ".claude"}  # 숨김 폴더 중 예외적으로 보는 곳


def setup_console() -> None:
    """윈도우 콘솔(cp949)에서 한글·이모지가 깨지거나 오류가 나지 않도록 UTF-8로 바꾼다."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def iter_files(root: Path, exts: set[str] | None = None):
    """root 아래 파일을 순서대로 돈다. exts를 주면 그 확장자(소문자, 점 포함)만."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in EXCLUDE_DIRS and (not d.startswith(".") or d in KEEP_HIDDEN)
        )
        for name in sorted(filenames):
            p = Path(dirpath) / name
            if exts is None or p.suffix.lower() in exts:
                yield p


def rel(p: Path, root: Path) -> str:
    """root 기준 상대 경로를 '/' 구분자로 (윈도우에서도 같은 모양)"""
    try:
        return p.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return p.as_posix()


def read_text(p: Path, limit_mb: float = 50) -> str | None:
    """UTF-8(BOM 허용)로 읽는다. 너무 크거나 UTF-8이 아니거나 읽을 수 없으면 None."""
    try:
        if p.stat().st_size > limit_mb * 1024 * 1024:
            return None
        return p.read_text(encoding="utf-8-sig")
    except (UnicodeDecodeError, OSError):
        return None


def match(path: str, patterns) -> bool:
    """'**/x/**' 같은 패턴을 최상위 경로에도 맞도록 보정한 fnmatch"""
    for pat in patterns or ():
        if fnmatch.fnmatch(path, pat) or (pat.startswith("**/") and fnmatch.fnmatch(path, pat[3:])):
            return True
    return False


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 300) -> tuple[int, str]:
    """명령 실행 (읽기 전용 명령만 넘길 것). (종료 코드, 출력). 실행할 수 없으면 (-1, 사유)."""
    try:
        r = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except FileNotFoundError:
        return -1, f"명령을 찾을 수 없음: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return -1, f"{timeout}초 시간 초과"


def git(repo: Path, *args: str, timeout: int = 300) -> tuple[int, str]:
    """한글 파일명이 '\\354\\202...'처럼 깨지지 않게 옵션을 붙여 git을 실행한다."""
    return run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "core.quotepath=off",
            "-c",
            "i18n.logOutputEncoding=UTF-8",
            *args,
        ],
        timeout=timeout,
    )


def tracked_files(repo: Path) -> set[str] | None:
    """git이 관리하는 파일 목록 (git 저장소가 아니면 None)"""
    code, out = git(repo, "ls-files")
    return set(out.splitlines()) if code == 0 else None


def md_table(headers, rows, limit: int | None = None) -> str:
    """Markdown 표. limit를 넘는 행은 생략하고 개수만 알린다."""
    rows = list(rows)
    shown = rows if limit is None else rows[:limit]
    esc = lambda v: str(v).replace("|", "\\|").replace("\n", " ")
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(esc(c) for c in r) + " |" for r in shown]
    if not rows:
        lines.append("| " + " | ".join(["(없음)"] + [""] * (len(headers) - 1)) + " |")
    if limit is not None and len(rows) > limit:
        lines.append(f"\n_(상위 {limit}개만 표시 · 전체 {len(rows)}개는 JSON 파일 참조)_")
    return "\n".join(lines)


def write_outputs(out_dir: Path, name: str, data: dict, md: str) -> None:
    """결과를 JSON(기계용)·Markdown(사람용)으로 저장하고 NUL 바이트 손상 여부를 확인한다 (KR-02)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {
        out_dir / f"{name}.json": json.dumps(data, ensure_ascii=False, indent=1, default=str),
        out_dir / f"{name}.md": md,
    }
    for path, text in files.items():
        path.write_text(text, encoding="utf-8")
        if b"\x00" in path.read_bytes():
            print(f"⛔ 저장한 파일에 NUL 바이트가 생겼습니다: {path}", file=sys.stderr)
    print(f"저장: {out_dir / (name + '.md')}  ·  {out_dir / (name + '.json')}")


def base_parser(desc: str) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=desc)
    ap.add_argument("--repo", required=True, type=Path, help="진단 대상 저장소 최상위 경로")
    ap.add_argument("--out", required=True, type=Path, help="결과 폴더 (저장소 밖 권장)")
    return ap


def check_paths(repo: Path, out: Path) -> None:
    """저장소가 있는지, 결과 폴더가 저장소 밖인지 확인 (진단은 저장소를 바꾸지 않는다)"""
    if not repo.is_dir():
        sys.exit(f"⛔ 저장소 경로가 없습니다: {repo}")
    try:
        out.resolve().relative_to(repo.resolve())
        print(
            "⚠️ 결과 폴더가 저장소 안에 있습니다. 읽기 전용 원칙상 저장소 밖을 권장합니다.",
            file=sys.stderr,
        )
    except ValueError:
        pass


def load_config(path: Path | None, default: dict) -> dict:
    """설정 JSON을 기본값 위에 덮어쓴다. '_'로 시작하는 키(설명용)는 무시."""
    cfg = json.loads(json.dumps(default))
    if path:
        try:
            user = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as e:
            sys.exit(f"⛔ 설정 파일을 읽을 수 없습니다 ({path}): {e}")
        cfg.update({k: v for k, v in user.items() if not k.startswith("_")})
    return cfg
