"""라우터 우회 결정 스캔 게이트의 **배선 실재 + 양방향 변별력** 동결 (EOS-77 ③④).

막는 것은 넷이다.

① **미배선** — 스캐너가 저장소에 있는데 CI `backend` 잡이 부르지 않는 것("존재함"≠"돌아감").
② **무변별(red 축)** — 클라우드 티어 직접 생성·판정 미승계·위조 승계·**kwargs·model_copy 재설정을
   주입해도 통과하는 것.
③ **무변별(green 축)** — 라우터 결정의 패밀리 스왑 사본·LOCAL 고정·유효한 유예가 red면 게이트가
   아니라 개발 차단기다("무조건 red면 개발이 막히고 무조건 green이면 게이트가 아니다").
④ **유예의 침묵** — 만료된 유예·가리키는 자리가 사라진(unmatched) 유예가 조용히 통과하는 것.

마지막으로 **프로덕션 트리 자체**가 green이고 클라우드 리터럴 0건임을 동결한다 — live_preflight를
라우터 경유로 되돌리는 회귀는 이 파일이 아니라 CI 스텝이 잡지만, 그 사실("유예 0건")을 여기서
한 번 더 기계로 적는다(유예를 추가하려면 이 테스트를 의식적으로 고쳐야 한다).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_SCANNER = _REPO_ROOT / "scripts" / "ops" / "check_routing_decision_bypass.py"

_HEADER = """from whymath_backend.l3 import models
from whymath_backend.l3.models import CostTier, LocalModelTier, ModelFamily, RoutingDecision
"""

# ── green 픽스처 ──────────────────────────────────────────────────────
_ROUTED_SWAP = _HEADER + """
def swap(decision: RoutingDecision) -> RoutingDecision:
    return RoutingDecision(
        cost_tier=decision.cost_tier,
        local_family=ModelFamily.GENERAL,
        local_model=decision.local_model,
        mode=decision.mode,
        reason=decision.reason,
        est_latency_ms=decision.est_latency_ms,
        data_export_blocked=decision.data_export_blocked,
        data_export_reason=decision.data_export_reason,
    )
"""

_LOCAL_LITERAL = _HEADER + """
def fixed() -> RoutingDecision:
    return RoutingDecision(
        cost_tier=CostTier.LOCAL,
        local_family=ModelFamily.GENERAL,
        local_model=LocalModelTier.FAST,
        mode="sync",
        reason="fixed local",
        est_latency_ms=0,
    )
"""

_MODEL_COPY_OTHER = _HEADER + """
def retune(decision: RoutingDecision) -> RoutingDecision:
    return decision.model_copy(update={"local_family": ModelFamily.GENERAL})
"""


# ── red 픽스처 ────────────────────────────────────────────────────────
def _cloud_literal(tier_expr: str) -> str:
    return _HEADER + f"""
def smoke() -> RoutingDecision:
    return RoutingDecision(
        cost_tier={tier_expr},
        local_family=None,
        local_model=None,
        mode="sync",
        reason="hand-built",
        est_latency_ms=3000,
    )
"""


_DYNAMIC_NO_INHERIT = _HEADER + """
def swap(decision: RoutingDecision) -> RoutingDecision:
    return RoutingDecision(
        cost_tier=decision.cost_tier,
        local_family=ModelFamily.GENERAL,
        local_model=decision.local_model,
        mode=decision.mode,
        reason=decision.reason,
        est_latency_ms=decision.est_latency_ms,
    )
"""


def _dynamic_literal_inherit(value: str) -> str:
    return _HEADER + f"""
def swap(decision: RoutingDecision) -> RoutingDecision:
    return RoutingDecision(
        cost_tier=decision.cost_tier,
        local_family=ModelFamily.GENERAL,
        local_model=decision.local_model,
        mode=decision.mode,
        reason=decision.reason,
        est_latency_ms=decision.est_latency_ms,
        data_export_reason={value},
    )
"""


def _nested_cloud(tier_expr: str) -> str:
    """승계 키워드를 *갖춘* 동적 형태 안에 클라우드 리터럴을 숨긴 우회 (PR #983 Codex P1)."""
    return _HEADER + f"""
def swap(decision: RoutingDecision, force_cloud: bool) -> RoutingDecision:
    return RoutingDecision(
        cost_tier={tier_expr},
        local_family=None,
        local_model=None,
        mode=decision.mode,
        reason=decision.reason,
        est_latency_ms=decision.est_latency_ms,
        data_export_reason=decision.data_export_reason,
    )
"""


_DYNAMIC_NO_LITERAL = _HEADER + """
def pick_tier() -> CostTier:
    return CostTier.LOCAL


def swap(decision: RoutingDecision) -> RoutingDecision:
    return RoutingDecision(
        cost_tier=pick_tier(),
        local_family=None,
        local_model=None,
        mode=decision.mode,
        reason=decision.reason,
        est_latency_ms=decision.est_latency_ms,
        data_export_reason=decision.data_export_reason,
    )
"""

_STAR_KWARGS = _HEADER + """
def build(**kwargs: object) -> RoutingDecision:
    return RoutingDecision(**kwargs)
"""

_POSITIONAL = _HEADER + """
def build() -> RoutingDecision:
    return RoutingDecision(CostTier.CLOUD_MID, None, None, "sync", "x", 3000)
"""

_MODEL_COPY_TIER = _HEADER + """
def escalate(decision: RoutingDecision) -> RoutingDecision:
    return decision.model_copy(update={"cost_tier": CostTier.CLOUD_HIGH, "local_model": None})
"""


def _run(*args: str | Path) -> subprocess.CompletedProcess[str]:
    """스캐너를 CI가 부르는 방식 그대로(서브프로세스·exit code) 돌린다. 타임아웃 동봉."""
    return subprocess.run(
        [sys.executable, str(_SCANNER), *(str(a) for a in args)],
        capture_output=True,
        text=True,
        timeout=120,
    )


def _site(path: Path, func: str) -> str:
    """스캐너의 유예 키 규칙과 동일 — 저장소 밖 파일은 절대 posix 경로."""
    return f"{path.resolve().as_posix()}::{func}"


# ──────────────────────────────────────────────────────────────────────
# ① 배선 실재
# ──────────────────────────────────────────────────────────────────────
def test_scanner_exists_at_the_path_ci_references() -> None:
    assert _SCANNER.is_file(), f"스캐너 부재: {_SCANNER}"


def _backend_scanner_step() -> dict[str, object]:
    workflow = yaml.safe_load(_CI_WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["backend"]["steps"]
    matched = [s for s in steps if "check_routing_decision_bypass.py" in str(s.get("run", ""))]
    assert matched, "ci.yml `backend` 잡에 check_routing_decision_bypass.py 스텝이 없다"
    assert len(matched) == 1
    return matched[0]


def test_ci_backend_job_runs_the_scanner() -> None:
    _backend_scanner_step()


def test_ci_step_is_blocking_not_advisory() -> None:
    step = _backend_scanner_step()
    assert not step.get("continue-on-error"), "게이트 스텝이 continue-on-error로 붙어 있다"
    assert not re.search(r"\|\|\s*true|;\s*true", str(step["run"]))


# ──────────────────────────────────────────────────────────────────────
# ③ green 축 — 정당한 생성은 통과해야 게이트다
# ──────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "source",
    [_ROUTED_SWAP, _LOCAL_LITERAL, _MODEL_COPY_OTHER + _LOCAL_LITERAL],
    ids=["routed-family-swap", "local-literal", "model_copy-other-field"],
)
def test_legitimate_constructions_pass(tmp_path: Path, source: str) -> None:
    (tmp_path / "ok.py").write_text(source, encoding="utf-8")
    result = _run(tmp_path)
    assert result.returncode == 0, f"정당한 생성이 red다:\n{result.stdout}"
    assert "위반 0건" in result.stdout


# ──────────────────────────────────────────────────────────────────────
# ② red 축 — 우회를 주입하면 실제로 실패하는가
# ──────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "tier_expr",
    ["CostTier.CLOUD_MID", "CostTier.CLOUD_HIGH", '"cloud_high"', "models.CostTier.CLOUD_MID"],
)
def test_cloud_tier_literal_is_detected(tmp_path: Path, tier_expr: str) -> None:
    (tmp_path / "smoke.py").write_text(_cloud_literal(tier_expr), encoding="utf-8")
    result = _run(tmp_path)
    assert result.returncode == 1, f"클라우드 직접 생성을 못 잡았다:\n{result.stdout}"
    assert "클라우드 티어 RoutingDecision 직접 생성" in result.stdout
    assert "::smoke" in result.stdout  # 함수 단위 site가 메시지에 실린다(유예 키 안내)


@pytest.mark.parametrize(
    "tier_expr",
    [
        "CostTier.CLOUD_MID if force_cloud else decision.cost_tier",
        'models.CostTier("cloud_high") if force_cloud else decision.cost_tier',
        "(decision.cost_tier, CostTier.CLOUD_HIGH)[force_cloud]",
    ],
    ids=["ifexp-attr", "call-string", "subscript-tuple"],
)
def test_cloud_literal_nested_in_dynamic_expression_is_detected(
    tmp_path: Path, tier_expr: str
) -> None:
    """승계 키워드가 있어도 표현식 안에 숨긴 클라우드 리터럴은 위반 (Codex P1·PR #983)."""
    (tmp_path / "swap.py").write_text(_nested_cloud(tier_expr), encoding="utf-8")
    result = _run(tmp_path)
    assert result.returncode == 1, f"중첩 클라우드 리터럴을 못 잡았다:\n{result.stdout}"
    assert "클라우드 티어 RoutingDecision 직접 생성" in result.stdout


def test_dynamic_tier_without_any_literal_passes_with_inheritance(tmp_path: Path) -> None:
    """리터럴이 전혀 없는 동적 티어는 승계만 있으면 통과 — 정적으로 더 알 수 없다(문서화된 공백)."""
    (tmp_path / "swap.py").write_text(_DYNAMIC_NO_LITERAL, encoding="utf-8")
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout


def test_dynamic_tier_without_inheritance_is_detected(tmp_path: Path) -> None:
    (tmp_path / "swap.py").write_text(_DYNAMIC_NO_INHERIT, encoding="utf-8")
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "승계가 없다" in result.stdout


@pytest.mark.parametrize("value", ['"EXPORT_ALLOWED"', "None"])
def test_literal_inheritance_is_forgery(tmp_path: Path, value: str) -> None:
    (tmp_path / "swap.py").write_text(_dynamic_literal_inherit(value), encoding="utf-8")
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "위조" in result.stdout


@pytest.mark.parametrize(
    ("source", "needle"),
    [(_STAR_KWARGS, "**kwargs"), (_POSITIONAL, "위치 인자"), (_MODEL_COPY_TIER, "model_copy")],
    ids=["star-kwargs", "positional", "model_copy-cost_tier"],
)
def test_static_proof_evasions_are_detected(tmp_path: Path, source: str, needle: str) -> None:
    (tmp_path / "evade.py").write_text(source, encoding="utf-8")
    result = _run(tmp_path)
    assert result.returncode == 1, f"우회를 못 잡았다:\n{result.stdout}"
    assert needle in result.stdout


# ──────────────────────────────────────────────────────────────────────
# ④ 유예 기계 — 유효하면 green, 만료·unmatched는 red, 형식 오류는 exit 2
# ──────────────────────────────────────────────────────────────────────
def test_valid_waiver_passes_and_is_visible(tmp_path: Path) -> None:
    path = tmp_path / "smoke.py"
    path.write_text(_cloud_literal("CostTier.CLOUD_MID"), encoding="utf-8")
    result = _run(
        tmp_path, "--waive", f"{_site(path, 'smoke')}=2099-12-31", "--today", "2026-09-05"
    )
    assert result.returncode == 0, result.stdout
    assert "[WAIVED]" in result.stdout
    assert "유예 1건" in result.stdout


def test_expired_waiver_is_a_violation_again(tmp_path: Path) -> None:
    path = tmp_path / "smoke.py"
    path.write_text(_cloud_literal("CostTier.CLOUD_MID"), encoding="utf-8")
    result = _run(
        tmp_path, "--waive", f"{_site(path, 'smoke')}=2026-01-01", "--today", "2026-09-05"
    )
    assert result.returncode == 1, "만료된 유예가 통과했다"
    assert "만료" in result.stdout


def test_unmatched_waiver_is_a_violation(tmp_path: Path) -> None:
    """고친 뒤 유예를 안 지우면 목록이 거짓이 된다 — 가리키는 자리가 없으면 red."""
    path = tmp_path / "ok.py"
    path.write_text(_LOCAL_LITERAL, encoding="utf-8")
    result = _run(tmp_path, "--waive", f"{_site(path, 'fixed')}=2099-12-31")
    assert result.returncode == 1
    assert "unmatched" in result.stdout


def test_waiver_on_wrong_function_does_not_cover_the_site(tmp_path: Path) -> None:
    path = tmp_path / "smoke.py"
    path.write_text(_cloud_literal("CostTier.CLOUD_MID"), encoding="utf-8")
    result = _run(tmp_path, "--waive", f"{_site(path, 'other')}=2099-12-31")
    assert result.returncode == 1
    assert "직접 생성" in result.stdout and "unmatched" in result.stdout


@pytest.mark.parametrize("bad", ["no-double-colon=2099-12-31", "a.py::f=not-a-date", "a.py::f"])
def test_malformed_waiver_is_an_argument_error(tmp_path: Path, bad: str) -> None:
    (tmp_path / "ok.py").write_text(_LOCAL_LITERAL, encoding="utf-8")
    result = _run(tmp_path, "--waive", bad)
    assert result.returncode == 2, result.stdout
    assert "인자 오류" in result.stdout


# ──────────────────────────────────────────────────────────────────────
# 측정 실패의 위장 방지
# ──────────────────────────────────────────────────────────────────────
def test_zero_decision_calls_is_a_measurement_failure(tmp_path: Path) -> None:
    (tmp_path / "unrelated.py").write_text("X = 1\n", encoding="utf-8")
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "측정 실패" in result.stdout


def test_unparseable_file_is_counted_as_a_violation(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text(_LOCAL_LITERAL, encoding="utf-8")
    (tmp_path / "broken.py").write_text("def f(:\n", encoding="utf-8")
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "파싱 실패" in result.stdout


def test_missing_target_is_a_measurement_failure(tmp_path: Path) -> None:
    result = _run(tmp_path / "does-not-exist")
    assert result.returncode == 1
    assert "측정 실패" in result.stdout


# ──────────────────────────────────────────────────────────────────────
# 프로덕션 트리 — green이며 클라우드 리터럴·유예 0건 (2026-09-05 실측 동결)
# ──────────────────────────────────────────────────────────────────────
def test_production_tree_has_no_cloud_direct_construction() -> None:
    result = _run()
    assert result.returncode == 0, f"프로덕션 트리에 라우터 우회가 있다:\n{result.stdout}"
    summary = re.search(
        r"생성 호출 (\d+)건 / 클라우드 리터럴 (\d+)건\(유예 (\d+)건\) / 위반 (\d+)건",
        result.stdout,
    )
    assert summary, f"요약 줄 형식이 바뀌었다:\n{result.stdout}"
    calls, cloud, waived, violations = (int(g) for g in summary.groups())
    assert calls >= 8, "생성 호출이 너무 적다 — 스캔 범위가 줄었는지 확인하라"
    assert (cloud, waived, violations) == (0, 0, 0)
