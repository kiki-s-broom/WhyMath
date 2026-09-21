"""[FLOW-HEALTH 후속] GitHub API를 부르는 스크립트는 **토큰을 실제로 소비**해야 한다.

사고 경위 (2026-09-01 main red, 2회차)
--------------------------------------
`harness-audit` 잡이 `GITHUB_TOKEN: ${{ github.token }}`을 스텝 env로 넘겼지만
`pr_delivery_audit.py`는 그 값을 **읽지 않았다**. 결과는 미인증 요청이고, GitHub API의
미인증 한도는 **IP당 60req/h**인데 러너는 IP를 공유하므로 실질 상시 소진이다:

    ❌ 측정 실패 — PR 목록 조회: API rate limit exceeded for 52.157.2.240

**환경변수를 넘기는 것과 스크립트가 소비하는 것은 다른 일이다.** 토큰 지원을
`flow_health.py`에만 넣고 두 스텝 모두에 env를 설정하면서, 다른 스크립트도 쓸 것이라고
**가정**했다(CLAUDE.md "검증 없는 실행 안내 금지 · 가정 기반 런북 금지"의 코드 축).

이 실패는 **간헐적**이라 더 위험하다 — 같은 코드가 직전 실행(`66e9587e`)에서는 통과했다.
그때는 공유 IP의 한도가 남아 있었을 뿐이다. "한 번 초록이었다"는 안전의 증거가 아니다.

계약
----
① `api.github.com`을 호출하는 스크립트는 `GITHUB_TOKEN`(또는 `GH_TOKEN`)을 읽는다.
② 그 토큰이 **실제로 curl 인자에 실린다**(읽기만 하고 안 쓰는 상태를 막는다).
③ 토큰이 없으면 인자를 넣지 않는다(로컬·오프라인에서 빈 Bearer를 보내지 않는다).
④ 워크플로가 그 스크립트를 부르는 스텝은 `GITHUB_TOKEN`을 env로 넘긴다 — 스크립트가
   읽을 준비가 돼 있어도 넘기지 않으면 여전히 미인증이다(양쪽이 다 있어야 성립).
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_API_HOST = "api.github.com"

# API를 호출하는 스크립트 전부 — 새 파일이 생겨도 자동 포함된다.
_SCRIPTS = sorted(
    p for p in (_REPO_ROOT / "scripts").rglob("*.py") if _API_HOST in p.read_text(encoding="utf-8")
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
        spec = importlib.util.spec_from_file_location(f"_auth_{path.stem}", path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        if inserted:
            sys.path.remove(parent)


def _curl_lists(tree: ast.AST) -> list[ast.List]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.List) and node.elts:
            first = node.elts[0]
            if isinstance(first, ast.Constant) and first.value == "curl":
                out.append(node)
    return out


class TestScriptsConsumeTheToken:
    def test_api_calling_scripts_were_found(self):
        """스캔 0건이면 아래 검사가 공허하게 통과한다 — 위장 방지."""
        assert _SCRIPTS, f"{_API_HOST}를 부르는 스크립트를 못 찾았다 — 스캔이 깨졌다"

    @pytest.mark.parametrize("path", _SCRIPTS, ids=lambda p: p.name)
    def test_reads_a_token_env_var(self, path: Path):
        src = path.read_text(encoding="utf-8")
        assert "GITHUB_TOKEN" in src or "GH_TOKEN" in src, (
            f"{path.name}이 토큰을 읽지 않는다 — 미인증 60req/h(러너는 IP 공유)로 "
            "상시 rate limit에 걸린다"
        )

    @pytest.mark.parametrize("path", _SCRIPTS, ids=lambda p: p.name)
    def test_token_actually_reaches_the_curl_args(self, path: Path):
        """② 읽기만 하고 안 쓰는 상태를 막는다 — 구성된 인자를 본다."""
        tree = ast.parse(path.read_text(encoding="utf-8"))
        lists = _curl_lists(tree)
        assert lists, f"{path.name}에서 curl 인자 목록을 못 찾았다 — 스캔이 깨졌다"
        for lst in lists:
            spliced = any(
                isinstance(e, ast.Starred)
                and isinstance(e.value, ast.Call)
                and isinstance(e.value.func, ast.Name)
                and e.value.func.id == "_auth_args"
                for e in lst.elts
            )
            assert spliced, (
                f"{path.name}:{lst.lineno} — curl 인자에 *_auth_args()가 없다. "
                "토큰을 읽어도 인자에 싣지 않으면 여전히 미인증이다"
            )


class TestAuthHelperBehaviour:
    @pytest.mark.parametrize("path", _SCRIPTS, ids=lambda p: p.name)
    def test_token_present_yields_bearer_header(self, path: Path, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "test-token-value")
        mod = _load(path)
        assert mod._auth_args() == ["-H", "Authorization: Bearer test-token-value"]

    @pytest.mark.parametrize("path", _SCRIPTS, ids=lambda p: p.name)
    def test_no_token_yields_empty_args(self, path: Path, monkeypatch):
        """③ 빈 Bearer를 보내지 않는다 — 로컬·오프라인에서 정상 동작해야 한다."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        mod = _load(path)
        assert mod._auth_args() == []


class TestWorkflowPassesTheToken:
    """④ 스크립트가 읽을 준비가 돼 있어도 워크플로가 안 넘기면 미인증이다."""

    def test_harness_audit_steps_pass_the_token(self):
        wf = _REPO_ROOT / ".github" / "workflows" / "harness-audit.yml"
        assert wf.exists(), f"워크플로 부재: {wf}"
        doc = yaml.safe_load(wf.read_text(encoding="utf-8"))
        jobs = (doc or {}).get("jobs") or {}
        assert jobs, "jobs가 비었다"
        checked = 0
        for job in jobs.values():
            for step in job.get("steps", []):
                run = str(step.get("run", ""))
                if _API_HOST in run or any(s.name in run for s in _SCRIPTS):
                    env = step.get("env") or {}
                    assert "GITHUB_TOKEN" in env or "GH_TOKEN" in env, (
                        f"'{step.get('name')}' 스텝이 API 스크립트를 부르면서 "
                        "토큰을 넘기지 않는다"
                    )
                    checked += 1
        assert checked, "API 스크립트를 부르는 스텝을 못 찾았다 — 스캔이 깨졌다"
