"""[OPS-55] 데이터 무결성 게이트의 **배선 실재성** 동결.

왜 이 테스트가 있는가
--------------------
`ops/integrity_violations_gate.py`가 저장소에 존재하는 것과 CI가 실제로 그것을 실행하는 것은
다르다(CLAUDE.md "검증 장치를 만들고 배선 확인 없이 완료 선언 금지" — OPS-03·OPS-08 동일계열
사고). 이 게이트는 실 DB가 필요해(orphan·dangling·duplicate는 빈 스키마가 아니라 *데이터*의
문제) `backend`(hermetic)가 아니라 `backend-migrations`(실 PG service) 잡에 배선한다 —
`provenance_audit`(`test_provenance_audit_wiring.py`)의 `backend` 잡 선례를 잡만 바꿔 미러링.

이 테스트가 없으면 `ci.yml`에서 이 스텝이 조용히 삭제돼도 아무 신호가 나지 않는다.

검증 계약
--------
① `backend-migrations` 잡에 `integrity_violations_gate` 모듈을 호출하는 `run` 스텝이 있다
② 그 스텝이 `-m whymath_backend.ops.integrity_violations_gate` 형태로 호출한다(파일 경로 직접
   실행 같은 변형이 아니라 패키지 모듈 실행 — venv·PYTHONPATH 문제 없이 항상 도는 형태)
③ 그 스텝이 `alembic upgrade head`(스키마 준비) *다음*에 온다 — 스키마 없는 DB에 대고 도는
   순서 결함을 잡는다
④ 파서가 위장하지 않는다 — 워크플로/잡을 못 찾으면 "위반 0 통과"가 아니라 **실패**
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_JOB_KEY = "backend-migrations"
_MODULE_INVOCATION = "-m whymath_backend.ops.integrity_violations_gate"
_MIGRATION_INVOCATION = "alembic upgrade head"


def _job_steps() -> list[dict[str, Any]]:
    if not _CI_PATH.is_file():
        raise AssertionError(f"{_CI_PATH} 이(가) 없다 — 게이트 배선을 확인할 수 없다.")
    spec: Any = yaml.safe_load(_CI_PATH.read_text(encoding="utf-8"))
    jobs = (spec or {}).get("jobs") or {}
    if _JOB_KEY not in jobs:
        raise AssertionError(
            f"ci.yml에 `{_JOB_KEY}` 잡이 없다 — 잡을 개명했다면 이 테스트도 함께 고쳐라."
        )
    steps = (jobs[_JOB_KEY] or {}).get("steps") or []
    if not steps:
        raise AssertionError(f"`{_JOB_KEY}` 잡에 스텝이 하나도 없다.")
    return [s for s in steps if isinstance(s, dict)]


def _run_scripts() -> list[str]:
    return [str(s.get("run", "")) for s in _job_steps() if s.get("run")]


def test_integrity_gate_step_exists_in_backend_migrations_job() -> None:
    scripts = _run_scripts()
    assert any(_MODULE_INVOCATION in script for script in scripts), (
        f"`{_JOB_KEY}` 잡에 `{_MODULE_INVOCATION}` 호출 스텝이 없다 — 데이터 무결성 게이트가 "
        "CI에서 조용히 빠졌다(코드는 존재하나 실행되지 않는 상태)."
    )


def test_integrity_gate_step_uses_module_invocation_not_bare_script() -> None:
    """`python path/to/integrity_violations_gate.py` 같은 변형은 cwd·PYTHONPATH에 취약하다 —
    `-m` 패키지 실행만 인정한다(다른 게이트 스텝들과 동일 관용구)."""
    scripts = _run_scripts()
    matching = [s for s in scripts if "integrity_violations_gate" in s]
    assert matching, "integrity_violations_gate를 언급하는 스텝이 하나도 없다."
    assert all(
        _MODULE_INVOCATION in s for s in matching
    ), f"integrity_violations_gate 스텝이 `-m` 모듈 실행 형태가 아니다: {matching}"


def test_integrity_gate_step_runs_after_migrations_applied() -> None:
    """스키마가 없는 fresh DB에 대고 돌면 매 테이블이 존재하지 않아 의미 없이 통과(공허한
    통과 — CLAUDE.md '스캔 0건은 실패'와 같은 계열)한다. 마이그레이션 적용 스텝보다 뒤에
    와야 한다."""
    scripts = _run_scripts()
    migration_idx = next((i for i, s in enumerate(scripts) if _MIGRATION_INVOCATION in s), None)
    gate_idx = next((i for i, s in enumerate(scripts) if _MODULE_INVOCATION in s), None)
    assert migration_idx is not None, f"`{_MIGRATION_INVOCATION}` 스텝을 찾지 못했다."
    assert gate_idx is not None, f"`{_MODULE_INVOCATION}` 스텝을 찾지 못했다."
    assert gate_idx > migration_idx, (
        "데이터 무결성 게이트 스텝이 `alembic upgrade head`보다 먼저 온다 — "
        "스키마 미적용 DB에 대고 도는 순서 결함."
    )
