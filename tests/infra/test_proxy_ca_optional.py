"""[FLOW-HEALTH 후속] 프록시 CA 경로가 **선택적**임을 저장소 전체에 동결한다.

사고 경위 (2026-09-01 main red)
--------------------------------
`/root/.ccr/ca-bundle.crt`는 **에이전트 프록시가 있는 실행 환경에만** 존재한다.
GitHub 러너에는 없고, 게다가 `runner` 유저는 `/root`(mode 700)를 **통과조차 할 수
없다**. 두 가지가 동시에 터졌다:

① `pr_delivery_audit.py`·`pr_merge_readiness.py`·`measure_merge_gate_latency.py`가
   `--cacert <경로>`를 **무조건** 넘겨 러너에서 `curl (77) error setting certificate
   file`. 이 셋은 CI 호출처가 0건이었기 때문에 **아무도 몰랐다** — 배선하는 순간
   드러났다("존재함"과 "돌아감"은 다르다의 정확한 실례).
② `flow_health.py`는 `if Path(_CA).exists()`로 가드했는데, **`Path.exists()`는
   EACCES를 삼키지 않는다** — `pathlib._IGNORED_ERRNOS`는
   `(ENOENT, ENOTDIR, EBADF, ELOOP)`뿐이다. 그래서 "없으면 건너뛴다"는 의도가
   "없으면 `PermissionError`로 죽는다"가 됐고 잡이 통째로 실패했다.

계약
----
① 저장소의 어떤 스크립트도 `--cacert`를 무조건 넘기지 않는다.
② 그 가드는 **권한 오류에서도** 살아남는다(존재 여부만이 아니라 접근 불가도).
③ CA를 못 쓰는 환경에서 curl 인자에 `--cacert`가 아예 들어가지 않는다.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CA_LITERAL = "/root/.ccr/ca-bundle.crt"

# 이 상수를 쓰는 스크립트 전부 — 새 파일이 생겨도 자동 포함된다(하드코딩 목록 아님).
_SCRIPTS = sorted(
    p
    for p in (_REPO_ROOT / "scripts").rglob("*.py")
    if _CA_LITERAL in p.read_text(encoding="utf-8")
)


def _load(path: Path):
    """`path`를 독립 모듈로 로드한다 — 형제 모듈(`from models import ...` 등)을
    import하는 스크립트도 로드되도록 그 디렉터리를 임시로 `sys.path`에 넣는다
    (`scripts/harness/backlog.py` 자신이 쓰는 것과 같은 패턴). 스캔이 새 스크립트를
    자동 편입하므로, 로더가 형제-import를 못 버티면 그 스크립트의 계약 검사 전체가
    `ModuleNotFoundError`로 공허하게 실패한다 — 이 로더 결함 자체가 위장이 된다.
    """
    parent = str(path.parent)
    inserted = parent not in sys.path
    if inserted:
        sys.path.insert(0, parent)
    try:
        spec = importlib.util.spec_from_file_location(f"_ca_{path.stem}", path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        if inserted:
            sys.path.remove(parent)


def _ca_args_span(tree: ast.AST) -> tuple[int, int] | None:
    """`_ca_args` 함수의 줄 범위. 없으면 None."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_ca_args":
            return node.lineno, (node.end_lineno or node.lineno)
    return None


def _curl_lists(tree: ast.AST) -> list[ast.List]:
    """`"curl"`로 시작하는 리스트 리터럴 = curl 인자 목록."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.List) and node.elts:
            first = node.elts[0]
            if isinstance(first, ast.Constant) and first.value == "curl":
                out.append(node)
    return out


class TestNoUnconditionalCacert:
    """① `--cacert`는 **가드 헬퍼 안에서만** 등장해야 한다.

    왜 정규식이 아니라 AST인가 (Codex P2 #3900419624, 2026-09-01): 초판 가드는
    부정 전방탐색 `(?!_PATH)`를 쓴 정규식이었는데, 그것이 **막으려던
    회귀를 그대로 면제했다** — `cmd = [..., "--cacert", _CA_PATH, ...]`가 통과한다.
    헬퍼 검사도 `"_ca_args" in src` 문자열 존재만 봐서, 헬퍼를 정의해 놓고 **쓰지
    않아도** 통과했다. 즉 러너가 다시 접근 불가 경로를 받아 curl 77로 죽는데
    이 저장소 전역 가드는 초록인 상태가 성립했다.

    그래서 문자열이 아니라 **구성된 curl 인자**를 본다.
    """

    def test_scripts_using_the_ca_were_found(self):
        """스캔이 0건이면 아래 검사들이 공허하게 통과한다 — 위장 방지."""
        assert _SCRIPTS, "CA 상수를 쓰는 스크립트를 하나도 못 찾았다 — 스캔이 깨졌다"

    @pytest.mark.parametrize("path", _SCRIPTS, ids=lambda p: p.name)
    def test_cacert_appears_only_inside_the_guard_helper(self, path: Path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        span = _ca_args_span(tree)
        assert span, f"{path.name}에 _ca_args 헬퍼가 정의돼 있지 않다"
        lo, hi = span
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value == "--cacert":
                assert lo <= node.lineno <= hi, (
                    f"{path.name}:{node.lineno} — '--cacert'가 가드 헬퍼 밖에 있다. "
                    "리터럴이든 _CA_PATH든 직접 넘기면 CA 없는 환경에서 curl 77이 난다"
                )

    @pytest.mark.parametrize("path", _SCRIPTS, ids=lambda p: p.name)
    def test_every_curl_invocation_splices_the_guard(self, path: Path):
        """헬퍼를 정의만 하고 **쓰지 않는** 상태를 막는다."""
        tree = ast.parse(path.read_text(encoding="utf-8"))
        lists = _curl_lists(tree)
        assert lists, f"{path.name}에서 curl 인자 목록을 찾지 못했다 — 스캔이 깨졌다"
        for lst in lists:
            spliced = any(
                isinstance(e, ast.Starred)
                and isinstance(e.value, ast.Call)
                and isinstance(e.value.func, ast.Name)
                and e.value.func.id == "_ca_args"
                for e in lst.elts
            )
            assert spliced, (
                f"{path.name}:{lst.lineno} — curl 인자에 *_ca_args()가 없다. "
                "헬퍼가 있어도 쓰지 않으면 보호가 아니다"
            )


class TestGuardSurvivesPermissionError:
    """② 핵심 — 존재하지 않는 경우뿐 아니라 **접근 불가**에서도 살아야 한다."""

    @pytest.mark.parametrize("path", _SCRIPTS, ids=lambda p: p.name)
    def test_permission_error_yields_empty_args(self, path: Path, monkeypatch):
        mod = _load(path)
        monkeypatch.setattr(
            mod,
            "open",
            lambda *a, **k: (_ for _ in ()).throw(PermissionError(13, "Permission denied")),
            raising=False,
        )
        assert (
            mod._ca_args() == []
        ), "권한 오류에서 빈 목록을 내야 한다 — Path.exists()는 EACCES를 전파한다"

    @pytest.mark.parametrize("path", _SCRIPTS, ids=lambda p: p.name)
    def test_missing_file_yields_empty_args(self, path: Path, monkeypatch):
        mod = _load(path)
        monkeypatch.setattr(mod, "_CA_PATH", "/nonexistent/definitely/not/here.crt")
        assert mod._ca_args() == []

    @pytest.mark.parametrize("path", _SCRIPTS, ids=lambda p: p.name)
    def test_readable_file_yields_cacert_args(self, path: Path, monkeypatch, tmp_path):
        """변별력 — 실제로 읽히는 CA가 있으면 인자를 내야 한다."""
        ca = tmp_path / "ca.crt"
        ca.write_bytes(b"dummy")
        mod = _load(path)
        monkeypatch.setattr(mod, "_CA_PATH", str(ca))
        assert mod._ca_args() == ["--cacert", str(ca)]
