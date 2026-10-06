"""노출 계약 ↔ 서빙 스키마 양방향 대조 게이트 (hermetic) — PED-28.

왜 필요한가: 노출 계약 표(`growth_evidence_exposure._STATIC_TIER`)와 서빙 스키마
(`api.me.GrowthEvidenceResponse`)는 서로를 검증하지 않았다. 종전 거버넌스
(`test_me_growth_evidence.py`의 `_DECLARED_FIELDS = set(GrowthEvidenceResponse.model_fields)`)는
기대값을 **검증 대상 모델 자신에서 파생**해 모델이 무엇이든 통과하는 동어반복이었고(CLAUDE.md
"변별력 없는 검증 스텝 금지"), 그 사이 드리프트 두 건이 조용히 쌓였다.

  (가) 계약은 `gap_recovery_leadtime_days`(⑯·PED-13)를 STUDENT_VISIBLE로 판정했는데 응답
       스키마에는 그 필드가 없다 — 학생이 볼 수 있다고 선언된 지표가 서빙 표면에 없다.
  (나) `SurrogateMetrics`의 `Metric` 지표 3종(⑫⑬⑭)이 계약 표에 미등재라 `classify_metric_exposure`
       의 루프(`_STATIC_TIER.items()`만 순회)가 노출 판정을 아예 하지 않았다 — 판정 *대상 밖*인
       지표는 안전한 것이 아니라 **판정받지 않은 것**이다.

이 파일이 막는 세 방향:
  ① 계약이 학생·보호자·보류(PROVISIONAL) 계층으로 판정한 지표는 서빙 스키마에 필드가 있어야 한다.
  ② 서빙 스키마의 지표 필드는 계약 표에 등재돼 있어야 하고, INTERNAL_ONLY 지표는 있으면 안 된다.
  ③ `SurrogateMetrics`의 `Metric` 지표는 전부 계약 표에 등재돼야 한다(판정 대상 밖 지표 봉인).

대조 규칙은 순수 함수(`_crosswalk_violations`)로 분리했다 — 같은 함수에 *실제 표*와 *주입한 표*를
넣어, 게이트가 진짜 드리프트에서 실제로 위반을 내는지(변별력)를 이 파일 안에서 상시 확인한다.
스캔 0건 통과를 막기 위해 입력이 비면 실패한다.
"""

from __future__ import annotations

from collections.abc import Mapping, Set

import pytest

from whymath_backend.api.me import GrowthEvidenceResponse
from whymath_backend.harness.growth_evidence_exposure import _STATIC_TIER, ExposureTier
from whymath_backend.harness.wh1_evaluation import Metric, SurrogateMetrics

# 응답 봉투 필드 — 지표가 아니라 시간창·스코프 echo다. 지표 필드와 구별하려고 *명시 목록*으로 둔다
# (이름 규칙으로 추정하면 새 봉투 필드가 지표로 오인되거나 그 반대가 된다).
_ENVELOPE_FIELDS: frozenset[str] = frozenset(
    {"window_start", "window_end", "user_scoped", "mode_filter"}
)

# 학생 대면 서빙 표면에 필드가 있어야 하는 계층. PROVISIONAL은 값은 막되(`exposable_now=False`)
# 필드 자리는 있어야 한다 — 보류 사유를 서빙 층이 말해야 하기 때문이다(MISC-20).
_SERVED_TIERS: frozenset[ExposureTier] = frozenset(
    {ExposureTier.STUDENT_VISIBLE, ExposureTier.GUARDIAN_SUMMARY, ExposureTier.PROVISIONAL}
)


def _crosswalk_violations(
    tier: Mapping[str, ExposureTier],
    served_fields: Set[str],
    surrogate_metric_fields: Set[str],
) -> list[str]:
    """계약 표·서빙 필드·원천 지표 필드를 대조해 위반 목록을 낸다(빈 목록 = 일치)."""
    problems: list[str] = []
    # ① 계약이 서빙하라고 판정한 지표가 스키마에 없다.
    for name, t in sorted(tier.items()):
        if t in _SERVED_TIERS and name not in served_fields:
            problems.append(f"① 계약({t.value})인데 서빙 스키마에 필드 없음: {name}")
    # ② 서빙 스키마의 지표 필드가 계약 표에 없거나, 내부 전용이다.
    for name in sorted(served_fields):
        if name not in tier:
            problems.append(f"② 서빙 스키마 필드가 계약 표에 미등재: {name}")
        elif tier[name] is ExposureTier.INTERNAL_ONLY:
            problems.append(f"② INTERNAL_ONLY 지표가 서빙 스키마에 노출됨: {name}")
    # ③ 원천 지표가 계약 표에 없어 노출 판정을 받지 않는다.
    for name in sorted(surrogate_metric_fields):
        if name not in tier:
            problems.append(f"③ SurrogateMetrics 지표가 계약 표에 미등재(판정 대상 밖): {name}")
    return problems


def _served_metric_fields() -> set[str]:
    return set(GrowthEvidenceResponse.model_fields) - _ENVELOPE_FIELDS


def _surrogate_metric_fields() -> set[str]:
    """`SurrogateMetrics`에서 타입이 `Metric`인 필드 — 표본 수·시간창·R15 판정 같은 비지표 제외."""
    return {name for name, f in SurrogateMetrics.model_fields.items() if f.annotation is Metric}


# ── 실제 표에 대한 게이트 ─────────────────────────────────────────────────────


def test_scan_is_not_vacuous() -> None:
    """대조 입력이 비면 모든 검사가 공허하게 통과한다 — 0건 스캔은 실패다."""
    assert len(_STATIC_TIER) >= 10
    assert len(_served_metric_fields()) >= 8
    assert len(_surrogate_metric_fields()) >= 10


def test_contract_and_serving_schema_agree_in_both_directions() -> None:
    """계약 표 ↔ 서빙 스키마 ↔ 원천 지표가 세 방향 모두 일치한다(위반 0건)."""
    problems = _crosswalk_violations(
        _STATIC_TIER, _served_metric_fields(), _surrogate_metric_fields()
    )
    assert not problems, "노출 계약과 서빙 스키마가 어긋났다:\n  " + "\n  ".join(problems)


# ── 변별력 — 같은 대조 함수가 진짜 드리프트에서 실제로 위반을 낸다 ──────────────────


def _real() -> tuple[dict[str, ExposureTier], set[str], set[str]]:
    return dict(_STATIC_TIER), _served_metric_fields(), _surrogate_metric_fields()


def test_gate_catches_contract_metric_missing_from_serving_schema() -> None:
    """① 계약 표에만 있고 스키마에 없는 지표 — 종전 드리프트 (가)의 재현."""
    tier, served, surrogate = _real()
    tier["phantom_student_metric"] = ExposureTier.STUDENT_VISIBLE
    problems = _crosswalk_violations(tier, served, surrogate)
    assert any(p.startswith("①") and "phantom_student_metric" in p for p in problems)


def test_gate_catches_serving_field_missing_from_contract() -> None:
    """② 스키마에만 있고 계약 표에 없는 필드."""
    tier, served, surrogate = _real()
    served.add("phantom_served_metric")
    problems = _crosswalk_violations(tier, served, surrogate)
    assert any(p.startswith("②") and "phantom_served_metric" in p for p in problems)


def test_gate_catches_internal_only_metric_served() -> None:
    """② INTERNAL_ONLY로 판정된 지표가 스키마에 필드로 있다(구조적 배제 위반)."""
    tier, served, surrogate = _real()
    internal = next(n for n, t in tier.items() if t is ExposureTier.INTERNAL_ONLY)
    served.add(internal)
    problems = _crosswalk_violations(tier, served, surrogate)
    assert any(p.startswith("②") and internal in p for p in problems)


def test_gate_catches_surrogate_metric_outside_contract() -> None:
    """③ 원천 지표가 계약 표에 없다 — 종전 드리프트 (나)의 재현."""
    tier, served, surrogate = _real()
    surrogate.add("phantom_surrogate_metric")
    problems = _crosswalk_violations(tier, served, surrogate)
    assert any(p.startswith("③") and "phantom_surrogate_metric" in p for p in problems)


def test_gate_is_silent_on_a_matching_triple() -> None:
    """대조 쌍이 정확히 맞을 때는 위반이 없다 — 항상 위반을 내는 검사는 변별력이 없다."""
    tier = {
        "a": ExposureTier.STUDENT_VISIBLE,
        "b": ExposureTier.PROVISIONAL,
        "c": ExposureTier.INTERNAL_ONLY,
    }
    assert _crosswalk_violations(tier, {"a", "b"}, {"a", "b", "c"}) == []


@pytest.mark.parametrize(
    "tier_value", [ExposureTier.STUDENT_VISIBLE, ExposureTier.GUARDIAN_SUMMARY]
)
def test_guardian_and_student_tiers_both_require_a_served_field(
    tier_value: ExposureTier,
) -> None:
    """보호자 요약 계층도 학생 계층과 같이 서빙 필드를 요구한다(현재 범위의 상속 규칙)."""
    problems = _crosswalk_violations({"x": tier_value}, set(), set())
    assert any(p.startswith("①") and "x" in p for p in problems)
