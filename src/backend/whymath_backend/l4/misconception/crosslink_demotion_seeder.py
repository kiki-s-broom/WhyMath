"""crosswalk 승인 강등전 GT 구성 — 인간 라벨 0(mutation testing·순수·결정론).

crosswalk 매핑의 정답 GT를 *사람 검수 없이* 만든다: ① **positives** = M-id가 그 kebab에 직접
대응하도록 *신규 저작*된 by-construction 정답(provenance=정답·인간 라벨 아님) ② **injected
negatives** = 같은 kebab을 *다른* M-id와 페어링(by-construction 정답이 유일하므로 나머지는 오매핑).

negatives를 두 tier로 나눠 **독립 구조 신호(성취기준 대조)가 어디까지 잡는가**를 측정 가능하게 한다:
  - `cross_standard_neg`: 성취기준이 kebab과 다른 오매핑 → 구조 게이트가 `disagree`로 *거부*(잡음).
  - `same_standard_neg`: 같은 성취기준의 형제 오개념 오매핑 → 구조 게이트가 `agree`로 *false accept*
    (못 잡음·인간 존치 구간). 이 tier가 게이트의 정직한 상한을 드러낸다.

결정론: mis_id 사전순 정렬 후 앞에서 N개(난수 0). 강등전 하니스(`crosslink_demotion_eval`)가
이 셋에 게이트를 돌려 tier별 Wilson 경계를 낸다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

__all__ = [
    "CROSSLINK_POSITIVES",
    "CrosslinkTrial",
    "build_demotion_set",
]

TrialLabel = Literal["correct", "wrong"]
TrialTier = Literal["positive", "cross_standard_neg", "same_standard_neg"]

# by-construction 정답 매핑 — M-id를 해당 kebab에 직접 대응하도록 신규 저작(MEMORY 2026-07).
# 이 대응이 유일 정답이므로 같은 kebab을 다른 M-id와 페어링하면 known-wrong(negatives).
CROSSLINK_POSITIVES: tuple[tuple[str, str], ...] = (
    ("opposite-root-selected", "M0862"),
    ("factor-sign-flip", "M0863"),
    ("extremum-max-min-confused", "M0864"),
    ("extremum-value-vs-point-confused", "M0865"),
)


@dataclass(frozen=True, slots=True)
class CrosslinkTrial:
    """강등전 시험 1건 — (kebab, M-id) 매핑 후보 + GT 라벨 + tier(측정 분해용)."""

    kebab_id: str
    mis_id: str
    label: TrialLabel
    tier: TrialTier


def build_demotion_set(
    *,
    mid_standards: Mapping[str, str | None],
    kebab_standards: Mapping[str, frozenset[str]],
    cross_per_positive: int = 60,
    same_per_positive: int = 60,
) -> list[CrosslinkTrial]:
    """positives + injected negatives(2 tier)로 강등전 셋 구성(순수·결정론).

    `mid_standards`: M-id 코퍼스(misconceptions_v1) {mis_id: standard_code}. `kebab_standards`:
    문항에서 역유도한 {kebab: 성취기준 집합}(`derive_kebab_standards`). 각 positive kebab마다:
      - positive 1건(정답 매핑),
      - cross_standard_neg: 성취기준이 kebab 집합과 겹치지 않는 M-id(standard None 제외)를 mis_id
        사전순 앞에서 `cross_per_positive`개,
      - same_standard_neg: 성취기준이 kebab 집합에 포함되나 정답 M-id가 아닌 M-id를 앞에서
        `same_per_positive`개.
    """
    trials: list[CrosslinkTrial] = []
    sorted_mids = sorted(mid_standards)  # 결정론(사전순)
    for kebab, pos_mid in CROSSLINK_POSITIVES:
        kebab_set = kebab_standards.get(kebab, frozenset())
        trials.append(
            CrosslinkTrial(kebab_id=kebab, mis_id=pos_mid, label="correct", tier="positive")
        )
        cross: list[str] = []
        same: list[str] = []
        for mid in sorted_mids:
            if mid == pos_mid:
                continue
            std = mid_standards[mid]
            if std is None:
                continue  # standard 없는 M-id는 신호 판정 불가(no_signal) — tier 오염 회피.
            if std in kebab_set:
                same.append(mid)
            else:
                cross.append(mid)
        for mid in cross[:cross_per_positive]:
            trials.append(
                CrosslinkTrial(kebab_id=kebab, mis_id=mid, label="wrong", tier="cross_standard_neg")
            )
        for mid in same[:same_per_positive]:
            trials.append(
                CrosslinkTrial(kebab_id=kebab, mis_id=mid, label="wrong", tier="same_standard_neg")
            )
    return trials
