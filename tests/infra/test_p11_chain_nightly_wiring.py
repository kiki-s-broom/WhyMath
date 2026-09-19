"""[P-11] 5단계 연결 동결 하네스의 **야간 배선 실재성** 동결.

왜 이 테스트가 있는가
--------------------
`tests/backend/api/test_p11_five_stage_loop_chain.py`는 실 PG가 있어야 판정한다. PG가 없으면
그 하네스는 **판정하지 않고 skip**하고, pytest는 skip에 exit 0을 낸다 — 즉 *아무것도 검증하지
않은 실행*이 초록으로 보인다.

이것은 가정이 아니라 이 저장소의 **현재 상태**다(2026-09-19 실측): `backend` 잡에는 postgres
service가 없어 Week 1·Week 2 게이트 하네스가 `1 skipped`·exit 0으로 끝나고, 실 PG가 있는
`e2e-nightly` 잡은 그 파일들을 이름으로 부르지 않는다. 그래서 그 두 판정 하네스는 **어느
CI 잡에서도 실제로 돈 적이 없다**(별건 등재 — 이 파일의 관심 밖).

그러므로 이 배선 가드는 "스텝이 있는가"로 끝나지 않고 **그 스텝이 실제로 판정에 도달하는가**를
본다. 세 축이 전부 있어야 한다:

  ① 배선 대상이 실재한다(파일이 디스크에 있다)
  ②③④ 스텝이 schedule 잡에 fail-closed로, `python -m pytest`로 얹혀 있다
     → 이 축은 `test_anchor_e2e_nightly_wiring.anchor_wiring_violations`를 **재사용**한다
       (재구현 0 — 그쪽이 이미 변별력을 봉인해 둔 순수 함수다)
  ⑤ **그 잡이 실 PG를 준다** — postgres service + `WHYMATH_RUN_INTEGRATION`
     → 이 축이 이 파일의 고유 기여다. 앵커 관통은 hermetic이라 그쪽 함수가 보지 않는다.
       이 축이 없으면 스텝은 멀쩡히 배선된 채로 매일 밤 skip하고 초록을 낸다.

변별력은 합성 워크플로 주입으로 매번 재확인한다(정상 입력에서 초록인 것은 증거가 아니다).
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from collections.abc import Mapping
from types import ModuleType
from typing import Any

import yaml

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CI_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"

#: 배선 대상 — P-11 5단계 연결 동결 하네스(실 PG 필요).
CHAIN_TEST_PATH = "tests/backend/api/test_p11_five_stage_loop_chain.py"

_ANCHOR_PATH = pathlib.Path(__file__).with_name("test_anchor_e2e_nightly_wiring.py")


def _load_anchor_module() -> ModuleType:
    """앵커 배선 가드를 파일 경로로 적재한다 — ②③④ 판정 함수를 빌려 쓴다(재구현 0)."""
    if not _ANCHOR_PATH.exists():
        raise AssertionError(
            f"앵커 배선 가드가 없다: {_ANCHOR_PATH}. 이 파일은 그 판정 함수를 재사용한다."
        )
    spec = importlib.util.spec_from_file_location("_anchor_wiring_guard", _ANCHOR_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"앵커 배선 가드 스펙 생성 실패: {_ANCHOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if not hasattr(module, "anchor_wiring_violations"):
        raise AssertionError(
            "앵커 배선 가드에 `anchor_wiring_violations`가 없다 — 이름이 바뀌었으면 여기도 "
            "함께 고쳐야 한다(조용한 표류 방지)."
        )
    return module


_ANCHOR = _load_anchor_module()
_wiring_violations = _ANCHOR.anchor_wiring_violations
_runs_pytest_on = _ANCHOR._runs_anchor_pytest


def _load_workflow() -> dict[str, Any]:
    """ci.yml 파싱 — 못 읽거나 jobs가 비면 '통과'가 아니라 실패한다."""
    if not _CI_PATH.is_file():
        raise AssertionError(f"{_CI_PATH} 이(가) 없다 — 배선을 확인할 수 없다(위장 통과 금지).")
    spec: Any = yaml.safe_load(_CI_PATH.read_text(encoding="utf-8"))
    if not isinstance(spec, dict) or not spec.get("jobs"):
        raise AssertionError("ci.yml에 jobs가 없다 — 워크플로 파싱이 위장 통과할 수 없다.")
    return spec


def real_pg_violations(spec: Mapping[str, Any], *, test_path: str = CHAIN_TEST_PATH) -> list[str]:
    """⑤ 그 스텝이 **실 PG에 도달하는가** — 이 파일의 고유 축(순수 함수).

    스텝을 담은 잡에 postgres service가 있고, 그 스텝(또는 잡)이 `WHYMATH_RUN_INTEGRATION`을
    켜는지 본다. 둘 중 하나라도 없으면 하네스는 배선된 채로 **매일 밤 skip**한다 — 배선의
    실재와 배선의 *도달*은 다르다.
    """
    violations: list[str] = []
    jobs = spec.get("jobs") or {}
    if not isinstance(jobs, dict) or not jobs:
        return ["ci.yml에 jobs가 없다 — 판정 불가(위장 통과 금지)."]

    hosting: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for job_key, job in jobs.items():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if not isinstance(step, dict) or not step.get("run"):
                continue
            if _runs_pytest_on(str(step["run"]), test_path=test_path):
                hosting.append((job_key, job, step))

    if not hosting:
        return [f"`{test_path}`를 pytest로 도는 스텝이 없다 — PG 도달 여부를 볼 대상 자체가 없다."]

    for job_key, job, step in hosting:
        services = job.get("services") or {}
        # 서비스 **이름**과 **이미지**를 둘 다 본다. 이 저장소의 PG 서비스 이미지는
        # `pgvector/pgvector:pg16`이라 "postgres" 부분문자열이 들어 있지 않다 — 이미지만
        # 보면 정상 배선을 미배선으로 오판한다(이 파일의 양성 대조군이 실제로 잡아낸 결함).
        haystack = " ".join(
            [str(name) for name in services]
            + [str(svc.get("image", "")) for svc in services.values() if isinstance(svc, dict)]
        ).lower()
        if not any(token in haystack for token in ("postgres", "pgvector")):
            violations.append(
                f"`{job_key}` 잡에 postgres service가 없다 — 이 하네스는 PG 미도달 시 판정을 "
                "내리지 않고 skip하고, skip은 exit 0이다. 즉 배선은 됐는데 매일 밤 아무것도 "
                "검증하지 않는 상태가 된다."
            )
        env = {**(job.get("env") or {}), **(step.get("env") or {})}
        if str(env.get("WHYMATH_RUN_INTEGRATION", "")) != "1":
            violations.append(
                f"`{job_key}` 잡의 P-11 스텝이 WHYMATH_RUN_INTEGRATION=1을 켜지 않는다 — "
                "integration 마크는 기본 skip이라 스텝이 조용히 수집 0건으로 초록이 된다."
            )
        if not str(env.get("WHYMATH_DATABASE_URL", "")) and not str(
            (job.get("env") or {}).get("WHYMATH_DATABASE_URL", "")
        ):
            violations.append(
                f"`{job_key}` 잡에 WHYMATH_DATABASE_URL이 없다 — 기본값이 러너의 PG를 "
                "가리킨다는 보장이 없고, 어긋나면 역시 skip으로 위장된다."
            )
    return violations


# ══════════════════════════════════════════════════════════════════════════
# 실 워크플로 판정
# ══════════════════════════════════════════════════════════════════════════
def test_chain_harness_file_exists() -> None:
    """① 배선 대상이 실재한다 — 없으면 야간 스텝은 매일 '수집 0건 통과'가 된다."""
    target = _REPO_ROOT / CHAIN_TEST_PATH
    assert target.is_file(), (
        f"{target} 이(가) 없다 — ci.yml이 가리키는 연결 동결 하네스가 사라지면 스텝은 조용히 "
        "초록이 된다(측정 실패가 통과로 위장되는 형태)."
    )


def test_chain_harness_is_wired_into_nightly_schedule() -> None:
    """②③④ schedule 잡에 fail-closed로·`python -m pytest`로 얹혀 있다(앵커 함수 재사용)."""
    violations = _wiring_violations(_load_workflow(), test_path=CHAIN_TEST_PATH)
    assert violations == [], "야간 배선 계약 위반:\n" + "\n".join(f"- {v}" for v in violations)


def test_chain_harness_job_actually_reaches_real_postgres() -> None:
    """⑤ 그 잡이 실 PG를 준다 — 배선의 실재와 배선의 *도달*은 다르다."""
    violations = real_pg_violations(_load_workflow())
    assert violations == [], "실 PG 도달 계약 위반:\n" + "\n".join(f"- {v}" for v in violations)


def test_parser_refuses_to_pass_on_broken_workflow() -> None:
    """파서가 위장하지 않는다 — jobs 없는 워크플로는 '위반 0'이 아니다."""
    assert real_pg_violations({"jobs": {}}) != []
    assert real_pg_violations({}) != []


# ══════════════════════════════════════════════════════════════════════════
# 변별력 봉인 — 축마다 그 축의 반례를 주입해 검출을 확인한다
# ══════════════════════════════════════════════════════════════════════════
def _synthetic(
    *,
    with_postgres: bool = True,
    run_integration: str | None = "1",
    database_url: str | None = "postgresql+asyncpg://whymath@127.0.0.1:5432/whymath",
    runs_target: bool = True,
) -> dict[str, Any]:
    """정상 배선 1건짜리 합성 워크플로 — 인자로 ⑤의 축을 하나씩 깨뜨린다."""
    path = CHAIN_TEST_PATH if runs_target else "tests/backend/api/test_other.py"
    step: dict[str, Any] = {"name": "P-11 연결", "run": f"python -m pytest ../../{path}"}
    step_env: dict[str, str] = {}
    if run_integration is not None:
        step_env["WHYMATH_RUN_INTEGRATION"] = run_integration
    if step_env:
        step["env"] = step_env
    job: dict[str, Any] = {"if": "github.event_name == 'schedule'", "steps": [step]}
    if with_postgres:
        job["services"] = {"postgres": {"image": "pgvector/pgvector:pg16"}}
    if database_url is not None:
        job["env"] = {"WHYMATH_DATABASE_URL": database_url}
    return {
        "on": {"push": {"branches": ["main"]}, "schedule": [{"cron": "0 18 * * *"}]},
        "jobs": {"e2e-nightly": job},
    }


def test_positive_control_synthetic_wiring_passes() -> None:
    """양성 대조 — 정상 합성 배선은 위반 0(무차별 실패가 아님을 보인다)."""
    assert real_pg_violations(_synthetic()) == []
    assert _wiring_violations(_synthetic(), test_path=CHAIN_TEST_PATH) == []


def test_detects_job_without_postgres_service() -> None:
    """주입 ⓐ — postgres service가 없으면 검출된다(이 절이 없으면 매일 밤 skip이 통과한다)."""
    assert real_pg_violations(_synthetic(with_postgres=False)) != []


def test_detects_missing_run_integration_env() -> None:
    """주입 ⓑ — WHYMATH_RUN_INTEGRATION이 없으면 검출된다(integration은 기본 skip)."""
    assert real_pg_violations(_synthetic(run_integration=None)) != []


def test_detects_run_integration_set_to_zero() -> None:
    """주입 ⓒ — 켰다고 적었는데 값이 0이면 검출된다(표기만 있고 효과가 없는 상태)."""
    assert real_pg_violations(_synthetic(run_integration="0")) != []


def test_detects_missing_database_url() -> None:
    """주입 ⓓ — DSN이 없으면 검출된다(기본값이 러너 PG를 가리킨다는 보장이 없다)."""
    assert real_pg_violations(_synthetic(database_url=None)) != []


def test_detects_step_that_does_not_run_the_target() -> None:
    """주입 ⓔ — 다른 테스트를 도는 스텝은 이 하네스의 배선이 아니다."""
    assert real_pg_violations(_synthetic(runs_target=False)) != []
