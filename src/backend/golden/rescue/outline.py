"""RS-R0 목차 도구 — 파이썬 파일을 열어 읽지 않고(사람·AI가 본문을 보지 않고) 요약만 뽑는다.

실행: `cd src/backend && python -m golden.rescue.outline <폴더 또는 파일> --level 1|2 [--out 파일]`
  - `--level 1` : 모듈마다 한 줄 — 경로 · 줄 수 · 함수 수 · 클래스 수 · 설명 첫 줄 · 큰 파일 표시
  - `--level 2` : 함수·클래스마다 한 줄 — 이름 · 시작 줄~끝 줄 · 줄 수 · 설명 첫 줄
  - `--out`     : 전체 출력을 이 파일에 쓰고, 화면에는 앞 50줄만 낸다

지키는 것
- 표준 라이브러리 `ast`로 파일을 글자로만 읽는다. 대상 코드를 import·실행하지 않는다(부작용 없음).
- 함수 본문은 싣지 않는다. 이름·줄 번호·설명(docstring) 첫 줄만 낸다. LLM을 부르지 않는다.
- 문법 오류 파일은 건너뛰지 않고 `파싱 실패: <오류 이름>` 한 줄로 낸다.
- 출력이 2,000줄을 넘으면 경고한다. `--out`이 없으면 앞 50줄만 보이고 종료 코드 3으로 끝난다
  (잘린 출력을 전체로 착각하지 않게).

종료 코드: 0 정상 · 2 대상 0개(경로 없음·.py 없음) · 3 출력 초과인데 `--out` 없음
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterator
from pathlib import Path

# 이 줄 수를 넘는 파일에 "큼" 표시를 붙인다(공유 계약 「큰 파일」 기준 1,500줄 초과)
BIG_FILE_LINES = 1500
# 출력이 이 줄 수를 넘으면 경고하고 파일로만 쓴다(읽기 상한 2,000줄과 같은 값)
MAX_OUTPUT_LINES = 2000
# 화면에 올리는 최대 줄 수(화면 출력 상한)
SCREEN_LINES = 50
# 설명 첫 줄을 이 글자 수로 자른다(한 줄 요약이 길어지지 않게)
DOC_CHARS = 80
SEP = " · "

_DefNode = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


def _doc_first_line(node: ast.AST) -> str:
    """docstring의 첫 번째 비어 있지 않은 줄을 돌려준다. 없으면 '-'."""
    if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return "-"
    doc = ast.get_docstring(node)
    for line in (doc or "").splitlines():
        if line.strip():
            text = line.strip()
            return text if len(text) <= DOC_CHARS else text[: DOC_CHARS - 1] + "…"
    return "-"


def _parse(path: Path) -> tuple[int, ast.Module | None, str]:
    """파일을 바이트로 읽어 (줄 수, 구문 트리, 실패 이유)를 돌려준다. 실패하면 트리가 None이다."""
    data = path.read_bytes()
    n_lines = len(data.splitlines())
    try:
        # 바이트를 그대로 넘기면 ast가 인코딩 선언(coding:)과 BOM을 스스로 처리한다
        return n_lines, ast.parse(data, filename=str(path)), ""
    except (SyntaxError, ValueError, RecursionError) as exc:
        return n_lines, None, f"파싱 실패: {type(exc).__name__}"


def iter_targets(target: Path) -> list[Path]:
    """대상 .py 파일 목록(정렬). 폴더면 하위 전체에서 숨김 폴더·__pycache__를 뺀다."""
    if target.is_file():
        return [target] if target.suffix == ".py" else []
    if not target.is_dir():
        return []
    return sorted(
        p
        for p in target.rglob("*.py")
        if not any(part.startswith(".") or part == "__pycache__" for part in p.parts)
    )


def level1_line(path: Path) -> str:
    """모듈 한 줄 요약 — 경로 · 줄 수 · 함수 수 · 클래스 수 · 설명 첫 줄 · 큼/-."""
    n_lines, tree, error = _parse(path)
    head = f"{path.as_posix()}{SEP}{n_lines}줄"
    if tree is None:
        return f"{head}{SEP}{error}"
    nodes = list(ast.walk(tree))
    n_func = sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in nodes)
    n_class = sum(isinstance(n, ast.ClassDef) for n in nodes)
    big = "큼" if n_lines > BIG_FILE_LINES else "-"
    return SEP.join([head, f"함수 {n_func}", f"클래스 {n_class}", _doc_first_line(tree), big])


def _defs(body: list[ast.stmt], prefix: str) -> Iterator[tuple[str, _DefNode]]:
    """모듈·클래스 몸체의 함수·클래스를 차례로 낸다. 클래스 안은 '클래스.이름'으로 들어간다.
    함수 안에 정의된 함수는 본문의 일부로 보고 내지 않는다."""
    for node in body:
        if isinstance(node, ast.ClassDef):
            yield f"class {prefix}{node.name}", node
            yield from _defs(node.body, f"{prefix}{node.name}.")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            yield f"{kind} {prefix}{node.name}", node


def level2_lines(path: Path) -> list[str]:
    """파일 머리 한 줄 + 함수·클래스마다 한 줄(이름 · 시작~끝 · 줄 수 · 설명 첫 줄)."""
    n_lines, tree, error = _parse(path)
    head = f"# {path.as_posix()}{SEP}{n_lines}줄"
    if tree is None:
        return [f"{head}{SEP}{error}"]
    out = [head]
    for name, node in _defs(tree.body, ""):
        # 데코레이터 줄부터 센다 — 그 구간만 열면 함수 전체가 보이게
        start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
        end = node.end_lineno or node.lineno
        out.append(
            SEP.join([name, f"{start}~{end}", f"{end - start + 1}줄", _doc_first_line(node)])
        )
    return out


def build(target: Path, level: int) -> list[str]:
    """대상 전체의 목차 줄 목록. 대상 파일이 0개면 빈 목록."""
    lines: list[str] = []
    for path in iter_targets(target):
        lines.extend([level1_line(path)] if level == 1 else level2_lines(path))
    return lines


def main(argv: list[str] | None = None) -> int:
    """명령행 진입점. 종료 코드는 모듈 설명 참고."""
    parser = argparse.ArgumentParser(prog="python -m golden.rescue.outline", description=__doc__)
    parser.add_argument("target", type=Path, help="폴더 또는 .py 파일")
    parser.add_argument("--level", type=int, choices=(1, 2), default=1)
    parser.add_argument("--out", type=Path, default=None, help="전체 출력을 쓸 파일")
    args = parser.parse_args(argv)

    lines = build(args.target, args.level)
    if not lines:
        print(f"대상 0개: {args.target} 에 .py 파일이 없다", file=sys.stderr)
        return 2
    footer = f"출력 {len(lines)}줄"
    over = len(lines) > MAX_OUTPUT_LINES
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text("\n".join([*lines, footer]) + "\n", encoding="utf-8")
    if args.out is None and not over:
        print("\n".join([*lines, footer]))
        return 0
    # 파일로 보냈거나 너무 길면 화면에는 앞 50줄만 — 잘렸다는 사실과 분모를 함께 낸다
    print("\n".join(lines[:SCREEN_LINES]))
    if len(lines) > SCREEN_LINES:
        print(f"… 화면에는 {len(lines)}줄 중 앞 {SCREEN_LINES}줄만 표시")
    if over:
        print(f"경고: 출력이 {MAX_OUTPUT_LINES:,}줄을 넘는다({len(lines):,}줄)", file=sys.stderr)
    print(footer)
    if args.out is None:
        print("전체를 보려면 --out 파일을 지정하라 (종료 코드 3 = 잘린 출력)", file=sys.stderr)
        return 3
    print(f"전체: {args.out.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
