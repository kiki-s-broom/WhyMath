"""전이 의존 예산 동결 — 골든이 쓰는 옛 모듈 수가 다시 늘지 않게 막는다(S20A · 1단계 개정판 S20+1).

예산(공통 규칙 8): 골든이 직접 import하는 옛 모듈 10개 이하 · 전이(함께 로드되는 옛 모듈 전부) 30개 이하.
숫자는 측정기 `python -m golden.measure_unreferenced --budget`가 센다. 런타임 실측이 이 pytest
프로세스의 sys.modules에 오염되지 않도록(특성화 테스트가 옛 모듈을 import한다) 새 프로세스로 돌린다.

경과(측정기 숫자 · 기준 main cd560e32)
- S15: 직접 7 · 전이 122.
- S20A 1일째(2026-11-16): `db.session`·`config` 엔진 경로를 골든으로 복사 → 직접 5 · 전이 40.
- S20A 2일째(2026-11-17 · Kiki 결정 선택지 B): OpenRouter 프로바이더 경로를 `golden/llm/`로 복사
  → 직접 6 · 전이 28. 라우터 판정(`Router.route`)은 그대로 옛 것을 거친다.
- 바닥: 옛 코드를 고치지 않는 한 약 27이다 — 헌법 R22-03이 강제하는 `l3.safe_parse`를 import하면
  `l3/__init__`이 라우터·모델·스키마 16모듈을 함께 부른다. 남은 여유는 2~3개뿐이다.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_BACKEND = Path(__file__).resolve().parents[2] / "src" / "backend"

# 예산(지시서) — 측정기의 상수와 같아야 한다(아래 테스트가 대조한다)
DIRECT_BUDGET = 10
TRANSITIVE_BUDGET = 30

# S20A가 끊은 것 — 다시 붙으면 안 된다(패키지 이름 접두사)
_CUT_DIRECT = {"whymath_backend.db.session", "whymath_backend.l3.providers.factory"}
_CUT_PACKAGES = ("whymath_backend.db", "whymath_backend.l3.providers")


@pytest.fixture(scope="module")
def budget() -> dict[str, Any]:
    """측정기를 새 프로세스로 돌려 판정 JSON을 받는다."""
    proc = subprocess.run(
        [sys.executable, "-m", "golden.measure_unreferenced", "--budget"],
        cwd=_BACKEND,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
        check=False,
    )
    # 측정기는 예산 안이면 0, 넘으면 1로 끝난다. 그 밖의 코드는 측정 자체가 실패한 것이다.
    assert proc.returncode in (0, 1), f"측정 실패(exit {proc.returncode}): {proc.stderr[-2000:]}"
    result: dict[str, Any] = json.loads(proc.stdout)
    assert (proc.returncode == 0) == result["within_budget"]
    return result


def test_measurement_is_not_empty(budget: dict[str, Any]) -> None:
    # 0건 측정은 통과가 아니다 — 골든은 라우터·채점 파서를 옛 코드에서 쓴다
    assert budget["direct_count"] == len(budget["direct"]) >= 1
    assert budget["transitive_count"] == len(budget["transitive"]) >= budget["direct_count"]
    assert set(budget["direct"]) <= set(budget["transitive"])
    assert "whymath_backend.l3.router" in budget["direct"]  # LLM 호출은 라우터 경유(불변)
    assert "whymath_backend.l3.safe_parse" in budget["direct"]  # 헌법 R22-03 단일 진입점


def test_budget_constants_match_measurer(budget: dict[str, Any]) -> None:
    assert budget["direct_budget"] == DIRECT_BUDGET
    assert budget["transitive_budget"] == TRANSITIVE_BUDGET


def test_direct_imports_within_budget(budget: dict[str, Any]) -> None:
    assert budget["direct_count"] <= DIRECT_BUDGET, budget["direct_by_golden_module"]


def test_transitive_within_budget(budget: dict[str, Any]) -> None:
    assert budget["transitive_count"] <= TRANSITIVE_BUDGET, (
        f"골든이 끌고 오는 옛 모듈이 {budget['transitive_count']}개다(예산 {TRANSITIVE_BUDGET}). "
        "새 옛 모듈은 import하지 말고 src/backend/golden/ 아래로 복사한다(공통 규칙 8 다섯 걸음 ③). "
        f"패키지별: {budget['transitive_by_subpackage']}"
    )


def test_cut_dependencies_stay_cut(budget: dict[str, Any]) -> None:
    # S20A가 복사해 끊은 DB 엔진·프로바이더 패키지가 다시 옛 것을 가리키면 전이가 되돌아온다
    assert not (_CUT_DIRECT & set(budget["direct"]))
    back = [
        m
        for m in budget["transitive"]
        if any(m == p or m.startswith(p + ".") for p in _CUT_PACKAGES)
    ]
    assert back == []
