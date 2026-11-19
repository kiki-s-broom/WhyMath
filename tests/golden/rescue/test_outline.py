"""RS-R0 목차 도구(golden.rescue.outline) 테스트.

임시 폴더에 합성 파일을 만들어 네 가지를 본다.
1. 함수 2개·클래스 1개 파일의 줄 번호가 맞는가
2. 1,501줄 파일에 "큼"이 붙는가(1,500줄은 안 붙는다 — 경계)
3. 문법 오류 파일이 건너뛰어지지 않고 `파싱 실패`로 나오는가
4. 대상이 0개면 종료 코드가 0이 아닌가(진짜 `python -m` 실행으로 확인)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from golden.rescue import outline

_BACKEND = Path(__file__).resolve().parents[3] / "src" / "backend"

# 줄 번호를 눈으로 셀 수 있게 짠 합성 파일(1줄부터)
_SAMPLE = '''"""표본 모듈 설명 첫 줄.

둘째 줄은 목차에 안 나온다.
"""


def first(x):
    """첫 함수."""
    return x


@staticmethod
def second():
    pass


class Box:
    """상자."""
'''


def test_two_functions_one_class_line_numbers(tmp_path: Path) -> None:
    """함수 2개·클래스 1개의 시작~끝 줄과 개수가 맞고, 본문은 실리지 않는다."""
    src = tmp_path / "sample.py"
    src.write_text(_SAMPLE, encoding="utf-8")

    level1 = outline.level1_line(src)
    assert level1.endswith("sample.py · 18줄 · 함수 2 · 클래스 1 · 표본 모듈 설명 첫 줄. · -")

    level2 = outline.level2_lines(src)
    assert level2[1:] == [
        "def first · 7~9 · 3줄 · 첫 함수.",
        "def second · 12~14 · 3줄 · -",  # 데코레이터 줄(12)부터 센다
        "class Box · 17~18 · 2줄 · 상자.",
    ]
    assert not any("return x" in line for line in level2)


def test_big_file_mark_boundary(tmp_path: Path) -> None:
    """1,501줄이면 "큼", 1,500줄이면 표시 없음."""
    big = tmp_path / "big.py"
    big.write_text("x = 1\n" * 1501, encoding="utf-8")
    edge = tmp_path / "edge.py"
    edge.write_text("x = 1\n" * 1500, encoding="utf-8")

    assert outline.level1_line(big).endswith(" · 큼")
    assert outline.level1_line(edge).endswith(" · -")


def test_syntax_error_reported_not_skipped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """문법 오류 파일도 한 줄로 나오고, 다른 파일 목차는 계속 나온다."""
    (tmp_path / "a_broken.py").write_text("def broken(:\n    pass\n", encoding="utf-8")
    (tmp_path / "b_ok.py").write_text('"""멀쩡."""\n', encoding="utf-8")

    assert outline.main([str(tmp_path), "--level", "1"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].endswith("a_broken.py · 2줄 · 파싱 실패: SyntaxError")
    assert lines[1].endswith("b_ok.py · 1줄 · 함수 0 · 클래스 0 · 멀쩡. · -")
    assert lines[-1] == "출력 2줄"
    assert outline.level2_lines(tmp_path / "a_broken.py")[0].endswith("파싱 실패: SyntaxError")


@pytest.mark.parametrize("kind", ["empty_dir", "missing_path"])
def test_zero_targets_exit_nonzero(tmp_path: Path, kind: str) -> None:
    """.py가 하나도 없는 폴더·없는 경로는 종료 코드 0이 아니다."""
    (tmp_path / "notes.txt").write_text("파이썬 아님\n", encoding="utf-8")
    target = tmp_path if kind == "empty_dir" else tmp_path / "nope"
    proc = subprocess.run(
        [sys.executable, "-m", "golden.rescue.outline", str(target), "--level", "1"],
        cwd=_BACKEND,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 2, proc.stderr
    assert "대상 0개" in proc.stderr
