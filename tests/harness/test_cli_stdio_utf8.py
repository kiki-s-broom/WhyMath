"""OPS-53 — CLI 진입점의 출력 인코딩이 cp949 파이프에서 죽지 않음을 동결한다.

왜 이 테스트가 있는가
--------------------
한국어 Windows 에서 파이프·리다이렉트의 stdout/stderr 은 cp949 를 쓴다. 콘솔은 별도 경로라 멀쩡해 보여
결함이 가려진다. `backlog.py gates list`(⏳ U+23F3)·`amend --help`(— U+2014)가 실제로
UnicodeEncodeError 로 죽었다(2026-09-01 Kiki 머신). 해법은 '문자 금지'가 아니라 진입점에서 스트림을
UTF-8 로 재구성하는 것이다(acceptance ⑤ · docs/ops/windows_utf8_setup.md §1).

재현은 Windows 가 필요 없다 — Linux 에서 PYTHONIOENCODING=cp949 로 파이프 인코딩을 강제하면 같은
UnicodeEncodeError 가 난다(tests/infra/test_hook_tool_output_utf8.py 와 같은 기법).

범위: scripts/harness/*.py 의 `__main__` 진입점 전수 + `python -m whymath_backend.*` 전체(패키지
__init__ 가 임포트 시 호출). scripts/ 의 다른 디렉터리는 이 태스크 범위 밖이다.
"""

from __future__ import annotations

import ast
import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_HARNESS = _ROOT / "scripts" / "harness"
_HELPER_SCRIPT = _HARNESS / "_stdio.py"
_HELPER_PKG = _ROOT / "src" / "backend" / "whymath_backend" / "_stdio.py"
_PKG_INIT = _ROOT / "src" / "backend" / "whymath_backend" / "__init__.py"

# cp949 로 인코딩할 수 없는 글자들 — 실제 CLI 출력에서 죽은 것들.
_UNENCODABLE = "— ⏳"


def _cp949_env() -> dict[str, str]:
    """파이프 출력 인코딩을 cp949 로 강제한 환경(한국어 Windows 파이프 모사)."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    env["PYTHONIOENCODING"] = "cp949"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _run(args: list[str], *, cwd: Path = _ROOT, extra_env: dict[str, str] | None = None):
    env = _cp949_env()
    env.update(extra_env or {})
    return subprocess.run(args, cwd=cwd, env=env, capture_output=True, check=False)  # noqa: S603


def _entrypoints() -> list[Path]:
    """`__main__` 가드가 있는 scripts/harness/*.py (헬퍼 자신 제외)."""
    out = []
    for path in sorted(_HARNESS.glob("*.py")):
        if path.name == "_stdio.py":
            continue
        if 'if __name__ == "__main__"' in path.read_text(encoding="utf-8"):
            out.append(path)
    return out


def _main_guard_calls(path: Path) -> set[str]:
    """`if __name__ == "__main__":` 블록 안에서 호출되는 이름들(`a.b` 형태 포함)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "__name__"
        ):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute):
                base = inner.func.value
                if isinstance(base, ast.Name):
                    names.add(f"{base.id}.{inner.func.attr}")
    return names


class TestHelperBehaviour:
    """헬퍼 단위 동작 — 서브프로세스 없이 가짜 스트림으로."""

    @staticmethod
    def _load(path: Path):
        import importlib.util

        spec = importlib.util.spec_from_file_location(f"_stdio_{path.parent.name}", path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    @pytest.fixture(params=[_HELPER_SCRIPT, _HELPER_PKG], ids=["scripts", "package"])
    def helper(self, request):
        return self._load(request.param)

    def test_cp949_stream_becomes_utf8_and_stops_crashing(self, helper, monkeypatch):
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding="cp949", write_through=True)
        # 수정 전 상태 확인 — 이 스트림은 실제로 죽는다(성공/실패 양쪽에서 같은 값을 내면 위장).
        with pytest.raises(UnicodeEncodeError):
            stream.write(_UNENCODABLE)
        monkeypatch.setattr(sys, "stdout", stream)
        monkeypatch.setattr(sys, "stderr", io.TextIOWrapper(io.BytesIO(), encoding="cp949"))
        helper.ensure_utf8_stdio()
        stream.write(_UNENCODABLE + "한글")
        stream.flush()
        assert stream.encoding.lower().replace("-", "") == "utf8"
        assert raw.getvalue().endswith((_UNENCODABLE + "한글").encode("utf-8"))

    def test_unpaired_surrogate_does_not_crash_either(self, helper, monkeypatch):
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding="cp949", write_through=True)
        monkeypatch.setattr(sys, "stdout", stream)
        monkeypatch.setattr(sys, "stderr", io.TextIOWrapper(io.BytesIO(), encoding="cp949"))
        helper.ensure_utf8_stdio()
        stream.write("a\ud800b")  # 짝 없는 surrogate — strict 였다면 죽는다
        stream.flush()
        assert b"a" in raw.getvalue() and b"b" in raw.getvalue()

    def test_already_utf8_stream_is_left_alone(self, helper, monkeypatch):
        calls: list[dict] = []

        class _Stream:
            encoding = "UTF-8"

            def reconfigure(self, **kw):
                calls.append(kw)

        monkeypatch.setattr(sys, "stdout", _Stream())
        monkeypatch.setattr(sys, "stderr", _Stream())
        helper.ensure_utf8_stdio()
        assert calls == []

    def test_stream_without_reconfigure_is_skipped(self, helper, monkeypatch):
        class _Capture:  # pytest 캡처 객체처럼 reconfigure 가 없다
            encoding = "cp949"

        monkeypatch.setattr(sys, "stdout", _Capture())
        monkeypatch.setattr(sys, "stderr", _Capture())
        helper.ensure_utf8_stdio()  # 예외 없이 지나가야 한다

    def test_reconfigure_failure_leaves_a_typed_warning_not_silence(self, helper, monkeypatch):
        class _Broken:
            encoding = "cp949"

            def reconfigure(self, **kw):
                raise ValueError("secret-field-value")

        seen = io.StringIO()
        monkeypatch.setattr(sys, "stdout", _Broken())
        monkeypatch.setattr(sys, "stderr", _Broken())
        monkeypatch.setattr(sys, "__stderr__", seen)
        helper.ensure_utf8_stdio()
        text = seen.getvalue()
        assert "ValueError" in text  # 예외 타입명은 남긴다
        assert "secret-field-value" not in text  # 값은 남기지 않는다

    def test_two_copies_are_the_same_function(self):
        """scripts 사본과 패키지 사본이 어긋나면 한쪽만 고쳐진 것이다."""

        def body(path: Path) -> str:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            parts = []
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.Assign)):
                    parts.append(ast.dump(node))
            return "\n".join(parts)

        assert body(_HELPER_SCRIPT) == body(_HELPER_PKG)


class TestRealCliOverCp949Pipe:
    """실 CLI 를 cp949 파이프 환경에서 돌린다 — 콘솔이 아니라 파이프 축."""

    def test_backlog_gates_list_survives_and_emits_utf8(self):
        proc = _run([sys.executable, str(_HARNESS / "backlog.py"), "gates", "list"])
        assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")[-500:]
        assert b"UnicodeEncodeError" not in proc.stderr
        proc.stdout.decode("utf-8")  # UTF-8 로 해독돼야 한다
        assert "⏳".encode() in proc.stdout  # cp949 에 없는 글자가 실제로 나갔다

    def test_backend_package_cli_survives_unencodable_print(self):
        code = f"import whymath_backend; print({_UNENCODABLE!r}); print({_UNENCODABLE!r}, file=__import__('sys').stderr)"
        proc = _run(
            [sys.executable, "-c", code],
            extra_env={"PYTHONPATH": str(_ROOT / "src" / "backend")},
        )
        assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")[-500:]
        assert _UNENCODABLE.encode() in proc.stdout
        assert _UNENCODABLE.encode() in proc.stderr


class TestEveryEntrypointIsWired:
    def test_entrypoints_were_found(self):
        # 스캔 0건은 실패다 — 공허하게 통과하는 전수 가드 방지.
        assert len(_entrypoints()) >= 15

    @pytest.mark.parametrize("path", _entrypoints(), ids=lambda p: p.name)
    def test_main_guard_calls_ensure_utf8_stdio(self, path):
        assert "_stdio.ensure_utf8_stdio" in _main_guard_calls(path), (
            f"{path.name}: `__main__` 블록이 _stdio.ensure_utf8_stdio() 를 부르지 않는다 — "
            "cp949 파이프에서 UnicodeEncodeError 로 죽는다(OPS-53)"
        )

    def test_package_init_calls_the_helper_at_import(self):
        text = _PKG_INIT.read_text(encoding="utf-8")
        tree = ast.parse(text)
        called = any(
            isinstance(n, ast.Expr)
            and isinstance(n.value, ast.Call)
            and isinstance(n.value.func, ast.Name)
            and n.value.func.id == "ensure_utf8_stdio"
            for n in tree.body
        )
        assert (
            called
        ), "whymath_backend/__init__.py 가 임포트 시 ensure_utf8_stdio() 를 부르지 않는다"
