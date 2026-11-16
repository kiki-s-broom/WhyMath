"""전이 의존 예산 동결 — 골든이 쓰는 옛 모듈 수가 다시 늘지 않게 막는다(S20A · 1단계 개정판 S20+1).

예산(공통 규칙 8): 골든이 직접 import하는 옛 모듈 10개 이하 · 전이(함께 로드되는 옛 모듈 전부) 30개 이하.
숫자는 측정기 `python -m golden.measure_unreferenced --budget`가 센다. 런타임 실측이 이 pytest
프로세스의 sys.modules에 오염되지 않도록(특성화 테스트가 옛 모듈을 import한다) 새 프로세스로 돌린다.

현재 상태(2026-11-16 실측 · 기준 main cd560e32)
- 직접 5개(예산 10 안) · 전이 40개(예산 30을 10 초과).
- 남은 40개는 전부 "LLM 호출은 라우터 경유" 불변(CLAUDE.md)을 지키는 한 끊을 수 없다 —
  `l3/__init__`·`l3/providers/__init__`·`schema/__init__`가 형제 모듈을 일괄 import한다.
  끊는 방법(프로바이더·라우터 복사)은 Kiki 결정 사항이라 이 세션에서 하지 않았다
  (게이트 `G-s20a-router-path-transitive-budget` · golden/reports_phase1/S20A/보고.md).
- 그래서 전이는 두 겹으로 동결한다: ①다시 늘지 못한다(상한 = 실측 40) ②목표 30은 strict xfail —
  30 안으로 들어오는 날 이 테스트가 "표시를 지워라"라고 실패해 임시 상한을 걷어내게 한다.
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

# 임시 상한: 전이 실측값(2026-11-16). 예산 30이 아니다 — "더 늘지 않는다"만 지킨다.
# 줄였으면 이 숫자도 같이 내린다. 30 이하가 되면 이 상수와 xfail 표시를 지운다.
TRANSITIVE_CEILING = 40

# S20A가 끊은 것 — 다시 붙으면 안 된다
_CUT_DIRECT = {"whymath_backend.config", "whymath_backend.db.session"}
_CUT_PREFIX = "whymath_backend.db"


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
    assert "whymath_backend.l3.router" in budget["direct"]


def test_budget_constants_match_measurer(budget: dict[str, Any]) -> None:
    assert budget["direct_budget"] == DIRECT_BUDGET
    assert budget["transitive_budget"] == TRANSITIVE_BUDGET
    assert TRANSITIVE_CEILING > TRANSITIVE_BUDGET  # 상한이 예산 이하가 되면 상한 자체를 지운다


def test_direct_imports_within_budget(budget: dict[str, Any]) -> None:
    assert budget["direct_count"] <= DIRECT_BUDGET, budget["direct_by_golden_module"]


def test_transitive_does_not_grow(budget: dict[str, Any]) -> None:
    assert budget["transitive_count"] <= TRANSITIVE_CEILING, (
        f"골든이 끌고 오는 옛 모듈이 {budget['transitive_count']}개로 늘었다(상한 "
        f"{TRANSITIVE_CEILING}). 새 옛 모듈은 import하지 말고 src/backend/golden/ 아래로 복사한다"
        f"(공통 규칙 8 다섯 걸음 ③). 패키지별: {budget['transitive_by_subpackage']}"
    )


@pytest.mark.xfail(
    strict=True,
    reason="전이 40 > 예산 30 — 라우터 경유 LLM 경로 유지 여부는 Kiki 결정 대기(S20A 보고)",
)
def test_transitive_within_budget(budget: dict[str, Any]) -> None:
    assert budget["transitive_count"] <= TRANSITIVE_BUDGET


def test_cut_dependencies_stay_cut(budget: dict[str, Any]) -> None:
    # S20A가 복사해 끊은 설정·DB 엔진이 다시 옛 것을 가리키면 전이 80여 개가 되돌아온다
    assert not (_CUT_DIRECT & set(budget["direct"]))
    back = [m for m in budget["transitive"] if m == _CUT_PREFIX or m.startswith(_CUT_PREFIX + ".")]
    assert back == []
