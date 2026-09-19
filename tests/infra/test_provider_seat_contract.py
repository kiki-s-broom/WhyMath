"""프로바이더 좌석 계약 게이트의 **배선 실재 + 양방향 변별력** 동결 (ARCH-46 ③④⑤).

막는 것은 넷이다.

① **미배선** — 스캐너가 저장소에 있는데 CI `backend` 잡이 부르지 않는 것("존재함"≠"돌아감").
② **무변별(red 축)** — 라우터 없이 프로바이더를 직접 부르는 코드·결정 인자 없는 호출을 주입해도
   통과하는 것.
③ **무변별(green 축)** — 라우터 경유·파이프라인 경유·조립 전용(FACTORY)·유효한 유예가 red면
   게이트가 아니라 개발 차단기다("무조건 red면 개발이 막히고 무조건 green이면 게이트가 아니다").
④ **유예의 침묵** — 만료된 유예·가리키는 자리가 사라진(unmatched) 유예가 조용히 통과하는 것.

**절마다 그 절을 밟는 픽스처를 둔다**(CLAUDE.md「픽스처가 그 절을 실제로 밟는가」). 특히
`_PIPELINE_ROUTED`는 파이프라인 인정 절이 없으면 통과해 버리는 반례다 — 그 절을 지우면
`l4/misconception/judge_seam.py` 같은 *정상* 좌석이 위반으로 잡힌다(2026-09-16 실측에서 초판
분류 기준이 실제로 그렇게 오분류했다).

마지막으로 **프로덕션 트리 자체**가 green임을 동결한다 — 유예를 늘리려면 이 테스트를 의식적으로
고쳐야 한다.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_SCANNER = _REPO_ROOT / "scripts" / "ops" / "check_provider_seat_contract.py"

_IMPORT = "from whymath_backend.l3.providers.ollama import OllamaProvider\n"

# ── red 픽스처 — 이 상태를 주입했는데 통과하면 게이트가 아니다 ────────────────
_DIRECT_CALL = _IMPORT + '''
async def run(decision):
    """라우터 증거 0 — 프로바이더를 직접 쥐고 부른다."""
    provider = OllamaProvider()
    return await provider.generate("p", "s", decision)
'''

_MISSING_DECISION = _IMPORT + '''
from whymath_backend.l3.router import Router

async def run(req):
    """라우터는 경유하나 호출에 결정을 싣지 않았다(위치 인자 2개·decision= 없음)."""
    Router().route(req)
    provider = OllamaProvider()
    return await provider.generate("p", "s")
'''

_DIRECT_CALL_ATTRIBUTE = _IMPORT + '''
class Runner:
    def __init__(self):
        self._provider = OllamaProvider()

    async def run(self, decision):
        """속성 수신자 형태의 직접 호출 — Name 수신자만 보면 놓친다."""
        return await self._provider.generate("p", "s", decision)
'''

# ── green 픽스처 — 이 상태가 red면 개발 차단기다 ─────────────────────────────
_ROUTER_ROUTED = _IMPORT + '''
from whymath_backend.l3.router import Router

async def run(req):
    """ⓐ 경유 — 라우터에서 결정을 받아 실행한다."""
    decision = Router().route(req)
    provider = OllamaProvider()
    return await provider.generate("p", "s", decision)
'''

_PIPELINE_ROUTED = _IMPORT + '''
from whymath_backend.l3.pipeline import generate as l3_generate

async def run(req, cache, trace):
    """ⓑ 경유 — 파이프라인이 내부에서 Router().route를 돈다.

    이 픽스처는 `has_router_evidence`의 **파이프라인 인정 절**을 밟는 유일한 자리다.
    그 절이 없으면 이 파일은 위반으로 잡힌다(judge_seam.py의 실제 형태).
    """
    provider = OllamaProvider()
    return await l3_generate(req, "p", "s", provider=provider, cache=cache, trace=trace)
'''

_PACKAGE_ATTR_ROUTER = _IMPORT + '''
from whymath_backend.l3 import router

async def run(req):
    """ⓐ 경유의 **패키지 속성** 형태 — `router.Router()`.

    이 픽스처는 `has_router_evidence`의 **Attribute 호출 인정 절**을 밟는 유일한 자리다.
    `from whymath_backend.l3 import router`는 `_module_of`가 `whymath_backend.l3`를 내므로
    모듈 임포트 절(M1)에 걸리지 않는다 — 그 절만 있으면 이 정상 형태가 위반으로 잡힌다.
    """
    decision = router.Router().route(req)
    provider = OllamaProvider()
    return await provider.generate("p", "s", decision)
'''

_RELATIVE_IMPORT_ROUTER = _IMPORT + '''
from .router import Router

async def run(req):
    """ⓐ 경유의 **상대 임포트** 형태.

    이 픽스처는 `has_router_evidence`의 **Name 호출 인정 절**을 밟는 유일한 자리다.
    상대 임포트(level>0)는 `_module_of`가 빈 목록을 내므로 모듈 임포트 절에 걸리지 않는다.
    """
    decision = Router().route(req)
    provider = OllamaProvider()
    return await provider.generate("p", "s", decision)
'''

_FACTORY_ONLY = _IMPORT + '''
def build():
    """조립 전용 — 프로바이더를 만들어 넘기기만 한다(app.py·residue_gate의 형태)."""
    return OllamaProvider()
'''

_STAR_KWARGS = _IMPORT + '''
from whymath_backend.l3.router import Router

async def run(req, **kwargs):
    """**kwargs 전달 — 정적으로 알 수 없으므로 보수적으로 통과시킨다(오탐 방지 대조군)."""
    Router().route(req)
    provider = OllamaProvider()
    return await provider.generate("p", "s", **kwargs)
'''

_NO_SEAT = '''
def run():
    """프로바이더를 임포트하지 않는다 — 좌석이 아니다."""
    return 1
'''


def _run_scanner(*args: str) -> subprocess.CompletedProcess[str]:
    """스캐너를 서브프로세스로 돌린다 — CI가 부르는 형태 그대로."""
    return subprocess.run(
        [sys.executable, str(_SCANNER), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


# ── ② red 축 — 위반 주입은 반드시 exit 1 ─────────────────────────────────────
@pytest.mark.parametrize(
    ("name", "body", "needle"),
    [
        ("direct.py", _DIRECT_CALL, "라우터 경유의 증거가 없다"),
        ("attr.py", _DIRECT_CALL_ATTRIBUTE, "라우터 경유의 증거가 없다"),
        ("nodecision.py", _MISSING_DECISION, "라우터 결정이 없다"),
    ],
)
def test_violation_injection_is_red(tmp_path: Path, name: str, body: str, needle: str) -> None:
    """가드가 막으려는 상태를 실제로 주입하면 RED다 — 정상 입력의 초록은 보호의 증거가 아니다."""
    _write(tmp_path, name, body)
    result = _run_scanner(str(tmp_path))
    assert result.returncode == 1, f"위반을 주입했는데 통과했다:\n{result.stdout}"
    assert needle in result.stdout, f"위반 사유가 출력에 없다:\n{result.stdout}"


# ── ③ green 축 — 정상 형태는 반드시 exit 0 ──────────────────────────────────
@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("routed.py", _ROUTER_ROUTED),
        ("piped.py", _PIPELINE_ROUTED),
        ("pkgattr.py", _PACKAGE_ATTR_ROUTER),
        ("relimport.py", _RELATIVE_IMPORT_ROUTER),
        ("factory.py", _FACTORY_ONLY),
        ("kwargs.py", _STAR_KWARGS),
    ],
)
def test_legitimate_shapes_are_green(tmp_path: Path, name: str, body: str) -> None:
    """라우터·파이프라인 경유와 조립 전용은 통과한다 — 무조건 red면 게이트가 아니라 차단기다."""
    _write(tmp_path, name, body)
    result = _run_scanner(str(tmp_path))
    assert result.returncode == 0, f"정상 형태가 red다:\n{result.stdout}"


def test_zero_seats_is_measurement_failure(tmp_path: Path) -> None:
    """좌석을 하나도 못 찾으면 '위반 0 통과'가 아니라 '측정 실패'다 — 공허한 통과 금지."""
    _write(tmp_path, "noseat.py", _NO_SEAT)
    result = _run_scanner(str(tmp_path))
    assert result.returncode == 1
    assert "측정 실패" in result.stdout


def test_parse_failure_is_not_swallowed(tmp_path: Path) -> None:
    """파싱 실패를 삼키면 '검사 못 한 파일'이 '통과한 파일'로 보인다."""
    _write(tmp_path, "broken.py", _IMPORT + "def run(:\n")
    result = _run_scanner(str(tmp_path))
    assert result.returncode == 1
    assert "파싱 실패" in result.stdout


# ── ④ 유예의 침묵 금지 ──────────────────────────────────────────────────────
def test_valid_waiver_passes(tmp_path: Path) -> None:
    """유효한 유예는 통과시키되 [WAIVED]로 드러낸다 — 조용히 통과하지 않는다."""
    path = _write(tmp_path, "direct.py", _DIRECT_CALL)
    result = _run_scanner(str(tmp_path), "--waive", f"{path.resolve().as_posix()}=2099-01-01")
    assert result.returncode == 0, result.stdout
    assert "[WAIVED]" in result.stdout


def test_expired_waiver_is_red(tmp_path: Path) -> None:
    """만료된 유예는 다시 위반이다 — 만료 없는 그랜드파더 금지."""
    path = _write(tmp_path, "direct.py", _DIRECT_CALL)
    result = _run_scanner(
        str(tmp_path),
        "--waive",
        f"{path.resolve().as_posix()}=2026-01-01",
        "--today",
        "2026-09-16",
    )
    assert result.returncode == 1
    assert "유예가 만료됐다" in result.stdout


def test_unmatched_waiver_is_red(tmp_path: Path) -> None:
    """가리키는 자리가 사라진 유예는 목록을 거짓으로 만든다 — exit 1."""
    path = _write(tmp_path, "routed.py", _ROUTER_ROUTED)
    result = _run_scanner(str(tmp_path), "--waive", f"{path.resolve().as_posix()}=2099-01-01")
    assert result.returncode == 1
    assert "유예 unmatched" in result.stdout


def test_waiver_syntax_error_is_exit_2(tmp_path: Path) -> None:
    """인자 오류는 위반(1)과 구분되는 exit 2다."""
    _write(tmp_path, "routed.py", _ROUTER_ROUTED)
    result = _run_scanner(str(tmp_path), "--waive", "경로만있음")
    assert result.returncode == 2
    assert "인자 오류" in result.stdout


def test_missing_decision_is_red_even_when_waived(tmp_path: Path) -> None:
    """결정 인자 누락은 유예 대상이 아니다 — 측정 도구도 라우터 결정은 실어야 한다."""
    path = _write(tmp_path, "nodecision.py", _MISSING_DECISION)
    result = _run_scanner(str(tmp_path), "--waive", f"{path.resolve().as_posix()}=2099-01-01")
    assert result.returncode == 1
    assert "라우터 결정이 없다" in result.stdout


# ── ① 배선 실재 + 프로덕션 트리 동결 ────────────────────────────────────────
def test_scanner_is_wired_into_ci() -> None:
    """저장소에 존재함과 CI에서 돌아감은 다르다 — `backend` 잡의 스텝을 실측한다."""
    workflow = yaml.safe_load(_CI_WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["backend"]["steps"]
    matched = [s for s in steps if "check_provider_seat_contract.py" in str(s.get("run", ""))]
    assert matched, "ci.yml `backend` 잡에 check_provider_seat_contract.py 스텝이 없다"


def test_production_tree_is_green() -> None:
    """프로덕션 트리는 위반 0건이다 — 유예를 늘리려면 이 테스트를 의식적으로 고쳐야 한다."""
    result = _run_scanner()
    assert result.returncode == 0, f"프로덕션 트리가 red다:\n{result.stdout}"
    assert "위반 0건" in result.stdout
