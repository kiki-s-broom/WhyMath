"""업무 매뉴얼 검사기 (scripts/manuals/manual.py · HARN-316) 변별력 테스트.

결함마다 '정상 매뉴얼에 그 결함 하나만 주입 → 해당 위반이 보고됨'을 확인하고,
대조군(주입 없음)은 위반 0건임을 함께 확인한다. 주입이 실제로 적용됐는지도 단언한다.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("manual_mod", REPO / "scripts/manuals/manual.py")
manual = importlib.util.module_from_spec(_spec)
sys.modules["manual_mod"] = manual
_spec.loader.exec_module(manual)

VALID = """---
id: demo
title: "데모 업무"
version: 2
updated: 2026-10-26
readiness: ready
owner: claude
open_questions: []
toolbox:
  - path: tool.sh
    role: "도구"
verify:
  - id: V1
    check: "도구가 성공한다"
    how: cmd
    cmd: "true"
  - id: V2
    check: "결과를 읽어 대조"
    how: read
    evidence: "결과 파일"
---

## 1. 목적과 범위
x
## 2. 시작 전 입력
x
## 3. 절차
x
## 4. 판단 분기
x
## 5. 금지
x
## 6. 툴박스 사용 규칙
x
## 7. 완료 조건 자체 검사
x
## 8. 실수 카탈로그
| 증상 | 원인 | 분류 | 매뉴얼 수정 위치 | 버전 |
|---|---|---|---|---|
| 깨짐 | 이유 | 절차 누락 | §3 · V1 | v2 |

## 9. 변경 이력
| 버전 | 날짜 | 무엇을 | 왜 |
|---|---|---|---|
| v1 | 2026-10-01 | 작성 | - |
| v2 | 2026-10-26 | 수정 | - |
"""


def _setup(tmp_path: Path, text: str, name: str = "demo") -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "tool.sh").write_text("#!/bin/sh\n")
    d = tmp_path / "manuals" / name
    d.mkdir(parents=True)
    p = d / "MANUAL.md"
    p.write_text(text, encoding="utf-8")
    return p


def _errs(tmp_path: Path, text: str, name: str = "demo") -> list[str]:
    return manual.check_manual(manual.load_manual(_setup(tmp_path, text, name)), tmp_path)


def _inject(old: str, new: str) -> str:
    assert VALID.count(old) == 1, f"주입 대상이 정확히 1건이어야 한다: {old!r}"
    out = VALID.replace(old, new)
    assert out != VALID
    return out


def test_control_valid_manual_has_no_errors(tmp_path):
    assert _errs(tmp_path, VALID) == []


@pytest.mark.parametrize(
    "old,new,expected",
    [
        ("---\nid: demo\n", "id: demo\n", "머리말(---)로 시작하지 않는다"),
        ("owner: claude\n", "owner: claude\ntitle: [\n", "YAML 파싱 실패"),
        ('title: "데모 업무"\n', "", "머리말 키 누락: title"),
        ("id: demo\n", "id: other\n", "폴더명"),
        ("version: 2\n", "version: 0\n", "version 은 1 이상"),
        ("readiness: ready\n", "readiness: done\n", "readiness 는"),
        ("open_questions: []\n", "open_questions:\n  - 누구에게?\n", "미해결 질문 1건"),
        ("path: tool.sh", "path: missing.sh", "툴박스 경로가 저장소에 없다: missing.sh"),
        ('    role: "도구"\n', "", "path·role"),
        ("  - id: V2\n", "  - id: V1\n", "verify id 중복: V1"),
        ("    how: cmd\n", "    how: maybe\n", "how 는"),
        ('    cmd: "true"\n', "", "how=cmd 인데 cmd 가 없다"),
        ('    evidence: "결과 파일"\n', "", "evidence"),
        (
            '    how: cmd\n    cmd: "true"\n',
            "    how: read\n    evidence: e\n",
            "기계 실행(cmd) 완료 조건이 0건",
        ),
        ("## 5. 금지\n", "", "본문 절 누락: '## 5. 금지'"),
        (
            "## 1. 목적과 범위\nx\n## 2. 시작 전 입력\n",
            "## 2. 시작 전 입력\nx\n## 1. 목적과 범위\n",
            "순서 어긋남",
        ),
        ("| §3 · V1 |", "| 다음엔 조심 |", "수정 위치가"),
        ("| v2 | 2026-10-26 |", "| v3 | 2026-10-26 |", "현재 버전 v2 행이 없다"),
    ],
)
def test_each_defect_is_detected(tmp_path, old, new, expected):
    errs = _errs(tmp_path, _inject(old, new))
    assert any(expected in e for e in errs), errs


def test_empty_toolbox_blocks_ready_but_not_draft(tmp_path):
    text = _inject('toolbox:\n  - path: tool.sh\n    role: "도구"\n', "toolbox: []\n")
    assert any("툴박스가 비어" in e for e in _errs(tmp_path, text))
    draft = text.replace("readiness: ready", "readiness: draft")
    assert _errs(tmp_path / "d", draft) == []


def test_empty_verify_is_rejected(tmp_path):
    start = VALID.index("verify:\n")
    end = VALID.index("---\n", start)
    text = VALID[:start] + "verify: []\n" + VALID[end:]
    assert any("완료 조건(verify)이 0건" in e for e in _errs(tmp_path, text))


def test_zero_manuals_is_failure(tmp_path, capsys):
    (tmp_path / "manuals" / "_template").mkdir(parents=True)
    assert manual.cmd_lint(tmp_path / "manuals", tmp_path) == 1
    assert "매뉴얼 0건" in capsys.readouterr().out


def test_lint_exit_codes(tmp_path):
    _setup(tmp_path, VALID)
    assert manual.cmd_lint(tmp_path / "manuals", tmp_path) == 0
    _setup(tmp_path, _inject("path: tool.sh", "path: gone.sh"), name="broken")
    assert manual.cmd_lint(tmp_path / "manuals", tmp_path) == 1


def test_repository_manuals_pass():
    """실제 manuals/ 전수가 통과해야 한다 (템플릿 포함)."""
    assert manual.cmd_lint() == 0


# ── verify 실행기 ──
def _verify_text(cmd: str) -> str:
    return _inject('    cmd: "true"\n', f"    cmd: {cmd!r}\n")


def test_verify_passes_when_cmd_succeeds(tmp_path, capsys):
    _setup(tmp_path, VALID)
    assert manual.cmd_verify("demo", [], tmp_path / "manuals", tmp_path) == 0
    out = capsys.readouterr().out
    assert "✅ V1" in out and "⏳ V2" in out


def test_verify_fails_when_cmd_fails(tmp_path):
    _setup(tmp_path, _verify_text("exit 3"))
    assert manual.cmd_verify("demo", [], tmp_path / "manuals", tmp_path) == 1


def test_verify_fills_args_and_reports_missing(tmp_path, capsys):
    _setup(tmp_path, _verify_text('test "{x}" = ok'))
    assert manual.cmd_verify("demo", ["x=ok"], tmp_path / "manuals", tmp_path) == 0
    assert manual.cmd_verify("demo", ["x=no"], tmp_path / "manuals", tmp_path) == 1
    assert manual.cmd_verify("demo", [], tmp_path / "manuals", tmp_path) == 1
    assert "인자 누락: --arg x=" in capsys.readouterr().out


def test_verify_rejects_unsafe_arg_value(tmp_path):
    _setup(tmp_path, VALID)
    assert manual.cmd_verify("demo", ["x=a;rm -rf /"], tmp_path / "manuals", tmp_path) == 1


def test_verify_refuses_broken_manual_and_missing_manual(tmp_path):
    _setup(tmp_path, _inject("## 5. 금지\n", ""))
    assert manual.cmd_verify("demo", [], tmp_path / "manuals", tmp_path) == 1
    assert manual.cmd_verify("nope", [], tmp_path / "manuals", tmp_path) == 2
