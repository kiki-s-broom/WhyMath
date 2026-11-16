"""S20A 전이 의존 예산 동결 — 골든이 쓰는 옛 모듈 수(공통 규칙 8 · 개정판 S20+1).

숫자는 측정기 `golden.measure_unreferenced --budget`과 같은 함수(`measure_budget`)로 센다.
- 직접: 골든 모듈이 import 문으로 직접 부르는 옛 모듈(서로 다른 것) — 예산 10개 이하
- 전이: 그 상류 전체(조상 패키지 보정 + 깨끗한 하위 프로세스의 런타임 실측 합집합) — 예산 30개 이하

S20A 결과(2026-11-17 실측): 직접 7 → 6 · 전이 122 → 40. `db.session` 하나를 복사해 82개를 끊었다.
남은 40은 LLM 라우터 경로(`l3.models`·`providers.factory`·`router`·`schema.enums`)가 끌고 오며
(정적 36 + 런타임 전용 3 + safe_parse 1), 라우터 경유는 CLAUDE.md 불변이라 이 세션에서 끊지 않았다
— "라우터 경유 유지 vs 프로바이더 1개 복사"는 Kiki 결정으로 넘겼다(golden/reports_phase1/S20A/보고.md).

그래서 전이는 두 겹으로 동결한다.
1) 래칫: 지금 값 40을 넘으면 RED — T1·T2·T3 import가 옛 모듈을 더 끌고 오면 막는다(넘으면 복사).
2) 목표: 30 이하 단언은 xfail(strict=True) — 목표에 들어가는 순간 XPASS가 실패로 떠서
   "래칫을 30으로 조이고 xfail을 지우라"고 알린다. 예산 숫자와 측정기는 느슨하게 하지 않는다.
"""

from __future__ import annotations

from typing import Any

import pytest
from golden.measure_unreferenced import BUDGET_DIRECT, BUDGET_TRANSITIVE, measure_budget

# S20A가 끝난 시점의 실측값 — 이보다 늘면 안 된다(줄면 이 숫자도 함께 내린다)
TRANSITIVE_RATCHET = 40


@pytest.fixture(scope="module")
def budget() -> dict[str, Any]:
    """측정은 grimp 그래프 + 하위 프로세스 1회라 몇 초 걸린다 — 모듈당 한 번만 센다."""
    return measure_budget()


def test_budget_constants_are_not_loosened() -> None:
    # 예산을 맞추려고 상한을 올리는 것을 막는다(지시서 "하지 말 것")
    assert (BUDGET_DIRECT, BUDGET_TRANSITIVE) == (10, 30)


def test_direct_imports_within_budget(budget: dict[str, Any]) -> None:
    assert budget["direct_count"] <= BUDGET_DIRECT, budget["direct"]


def test_db_package_is_cut(budget: dict[str, Any]) -> None:
    # S20A가 끊은 것 — 옛 db 패키지(ORM 모델 64개)가 다시 끌려오면 RED
    leaked = [m for m in budget["transitive"] if m.startswith("whymath_backend.db")]
    assert leaked == []


def test_transitive_does_not_grow_past_ratchet(budget: dict[str, Any]) -> None:
    assert budget["transitive_count"] <= TRANSITIVE_RATCHET, budget["by_subpackage"]


@pytest.mark.xfail(
    strict=True,
    reason="전이 40 > 예산 30 — 라우터 경로 유지/복사 Kiki 결정 대기(S20A 보고). 통과하면 래칫을 조인다",
)
def test_transitive_within_budget(budget: dict[str, Any]) -> None:
    assert budget["transitive_count"] <= BUDGET_TRANSITIVE
