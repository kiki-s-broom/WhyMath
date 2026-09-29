"""[S4-01 슬라이스 2] traversal 성능 예산 실부하 판정의 **CI 배선 실재성** 동결.

왜 이 테스트가 있는가
--------------------
판정 CLI(`whymath_backend.harness.traversal_load_probe`)는 실 PG가 있어야 성립한다. 단위
테스트는 판정 로직만 보고 실 SQL은 보지 않으므로, "CLI가 저장소에 있다"와 "CI가 실 PG에서 그
판정을 돌린다"는 다르다(OPS-03/08/11 선례 — 배선은 산문이 아니라 기계가 붙든다).

검증 계약 (각 항목은 아래 결함 주입 테스트로 변별력을 확인한다)
------------------------------------------------------------
① 판정 CLI 모듈이 디스크에 실재한다.
② **실 PG 서비스가 있는 잡**에 판정 CLI를 `python -m`으로 실행하는 스텝이 있다.
③ 같은 잡에서 원자 백본 적재 스텝이 판정 스텝보다 **앞에** 있다 — 적재 없이 돌면 exit 2(측정
   불성립)로 red가 되긴 하지만, 적재가 판정 *뒤*로 밀리는 배선 실수는 여기서 먼저 잡는다.
④ 판정 스텝이 fail-open이 아니다(`continue-on-error` 없음) · DB를 우회하는 `--structural-only`가
   아니다.
⑤ 그 잡이 PR·push에서 돈다 — schedule 전용 잡이면 이 PR에서 배선을 검증할 방법이 없다.
⑥ 파서가 위장하지 않는다 — ci.yml을 못 읽거나 jobs가 비면 실패한다.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"

PROBE_MODULE = "whymath_backend.harness.traversal_load_probe"
POPULATE_MODULE = "whymath_backend.l1.atom_graph.populate"
PROBE_FILE = _REPO_ROOT / "src/backend/whymath_backend/harness/traversal_load_probe.py"


def _load_workflow() -> dict[str, Any]:
    """ci.yml 파싱 — 못 읽거나 jobs가 비면 '통과'가 아니라 AssertionError(⑥)."""
    if not _CI_PATH.is_file():
        raise AssertionError(f"{_CI_PATH} 이(가) 없다 — 배선을 확인할 수 없다(위장 통과 금지).")
    spec: Any = yaml.safe_load(_CI_PATH.read_text(encoding="utf-8"))
    if not isinstance(spec, dict) or not spec.get("jobs"):
        raise AssertionError("ci.yml에 jobs가 없다 — 워크플로 파싱이 위장 통과할 수 없다.")
    return spec


def _runs_module(script: str, module: str) -> bool:
    """`python* -m <module>` 토큰 순서로 판정 — 주석·문자열 우연 일치를 잡지 않는다."""
    tokens = script.replace("\\\n", " ").split()
    for i, token in enumerate(tokens[:-2]):
        if Path(token).name.startswith("python") and tokens[i + 1] == "-m":
            if tokens[i + 2] == module:
                return True
    return False


def _step_index(steps: list[dict[str, Any]], module: str) -> int | None:
    for i, step in enumerate(steps):
        if _runs_module(str(step.get("run", "")), module):
            return i
    return None


def wiring_violations(spec: dict[str, Any]) -> list[str]:
    """배선 계약 ②~⑤ 위반 목록 — 비면 정상. 판정 스텝이 있는 잡마다 검사한다."""
    jobs: dict[str, Any] = spec.get("jobs") or {}
    carriers = [
        (name, job)
        for name, job in jobs.items()
        if _step_index(job.get("steps") or [], PROBE_MODULE) is not None
    ]
    if not carriers:
        return [f"② 판정 CLI({PROBE_MODULE})를 실행하는 스텝이 어느 잡에도 없다"]
    violations: list[str] = []
    for name, job in carriers:
        steps = job.get("steps") or []
        probe_at = _step_index(steps, PROBE_MODULE)
        assert probe_at is not None
        probe = steps[probe_at]
        if "postgres" not in (job.get("services") or {}):
            violations.append(f"② {name}: 실 PG 서비스 없는 잡에서 판정한다")
        populate_at = _step_index(steps, POPULATE_MODULE)
        if populate_at is None:
            violations.append(f"③ {name}: 원자 백본 적재 스텝이 없다")
        elif populate_at > probe_at:
            violations.append(f"③ {name}: 적재 스텝이 판정 스텝보다 뒤에 있다")
        if probe.get("continue-on-error"):
            violations.append(f"④ {name}: 판정 스텝이 continue-on-error(fail-open)다")
        if "--structural-only" in str(probe.get("run", "")):
            violations.append(f"④ {name}: --structural-only라 실 PG를 측정하지 않는다")
        condition = str(job.get("if", ""))
        if "== 'schedule'" in condition or '== "schedule"' in condition:
            violations.append(f"⑤ {name}: schedule 전용 잡이라 PR에서 배선을 검증할 수 없다")
    return violations


# ── 실 워크플로 ─────────────────────────────────────────────────────────────


def test_probe_module_exists() -> None:
    assert PROBE_FILE.is_file(), f"① 판정 CLI 부재: {PROBE_FILE}"


def test_real_workflow_wires_probe_after_populate_on_real_pg() -> None:
    assert wiring_violations(_load_workflow()) == []


# ── 결함 주입 — 판정 함수의 변별력 봉인 ────────────────────────────────────────


def _carrier(spec: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    for name, job in spec["jobs"].items():
        if _step_index(job.get("steps") or [], PROBE_MODULE) is not None:
            return name, job
    raise AssertionError("대조군에 판정 잡이 없다")


def _mutate_remove_probe(spec: dict[str, Any]) -> None:
    _, job = _carrier(spec)
    job["steps"] = [
        s for s in job["steps"] if not _runs_module(str(s.get("run", "")), PROBE_MODULE)
    ]


def _mutate_remove_populate(spec: dict[str, Any]) -> None:
    _, job = _carrier(spec)
    job["steps"] = [
        s for s in job["steps"] if not _runs_module(str(s.get("run", "")), POPULATE_MODULE)
    ]


def _mutate_swap_order(spec: dict[str, Any]) -> None:
    _, job = _carrier(spec)
    steps = job["steps"]
    p, q = _step_index(steps, POPULATE_MODULE), _step_index(steps, PROBE_MODULE)
    assert p is not None and q is not None
    steps[p], steps[q] = steps[q], steps[p]


def _mutate_fail_open(spec: dict[str, Any]) -> None:
    _, job = _carrier(spec)
    job["steps"][_step_index(job["steps"], PROBE_MODULE)]["continue-on-error"] = True


def _mutate_structural_only(spec: dict[str, Any]) -> None:
    _, job = _carrier(spec)
    step = job["steps"][_step_index(job["steps"], PROBE_MODULE)]
    step["run"] = str(step["run"]) + " --structural-only"


def _mutate_drop_postgres(spec: dict[str, Any]) -> None:
    _, job = _carrier(spec)
    job.pop("services", None)


def _mutate_schedule_only(spec: dict[str, Any]) -> None:
    _, job = _carrier(spec)
    job["if"] = "github.event_name == 'schedule'"


@pytest.mark.parametrize(
    "mutate",
    [
        _mutate_remove_probe,
        _mutate_remove_populate,
        _mutate_swap_order,
        _mutate_fail_open,
        _mutate_structural_only,
        _mutate_drop_postgres,
        _mutate_schedule_only,
    ],
)
def test_each_injected_defect_is_detected(mutate: Any) -> None:
    spec = copy.deepcopy(_load_workflow())
    before = copy.deepcopy(spec)
    mutate(spec)
    assert spec != before, "주입이 적용되지 않았다 — 검출 여부를 판정할 수 없다"
    assert wiring_violations(spec), f"{mutate.__name__} 결함을 판정 함수가 놓쳤다"


def test_runs_module_ignores_mentions_outside_python_m() -> None:
    assert not _runs_module(f"echo {PROBE_MODULE}", PROBE_MODULE)
    assert not _runs_module(f"python -m {PROBE_MODULE}_v2", PROBE_MODULE)
    assert _runs_module(f"python3 -m {PROBE_MODULE} --concurrency 1,8", PROBE_MODULE)


def test_unparseable_workflow_is_not_a_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = tmp_path / "ci.yml"
    empty.write_text("name: x\n", encoding="utf-8")
    monkeypatch.setitem(globals(), "_CI_PATH", empty)
    with pytest.raises(AssertionError):
        _load_workflow()
