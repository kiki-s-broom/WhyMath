#!/usr/bin/env python3
"""EOS-178 — '초보' 라벨이 힌트 단계·`used_hint`를 어떻게 움직이는가: 실제 함수로 재는 재현 스크립트.

판정문(`docs/reviews/eos178_beginner_label_hint_judgment_2026-10-06.md`)의 수치를 만든다. 합성 학생의
확률은 가정이라 **방향의 증거**이지 운영 수치가 아니다(운영 응답이 없다). 라벨·단계 규칙 자체는
저장소의 실제 함수를 그대로 부른다(`update_mastery` · `estimate_ability` · `_ability_level` ·
`decide_hint_level`) — 이 스크립트가 규칙을 복제하지 않는다. 예외는 **후보 변형**(`variant_level`)
뿐이며, 그것이 실제 `decide_hint_level`과 `current` 변형에서 전 격자 일치하는지를 먼저 단언한다
(복제가 어긋나면 비교가 무의미하다).

사용: `python3 scripts/analysis/eos178_label_trajectory.py`
종료 코드 0 = 충실도 단언 통과 + 표 출력 · 1 = 충실도 불일치.
"""

from __future__ import annotations

import itertools
import random
import sys
from typing import Literal

from whymath_backend.api.coach import _ability_level
from whymath_backend.l2.bkt import BktParameters, update_mastery
from whymath_backend.l2.irt import IrtItem, ability_boundary, estimate_ability
from whymath_backend.l4.hint_deferral import (
    DEMAND_ANSWER_TOKENS,
    FRUSTRATION_TOKENS,
    STUCK_TURN_THRESHOLD,
    counts_as_hint_usage,
    decide_hint_level,
    has_any_token,
)
from whymath_backend.l4.lthc.models import MasteryLevel

_PARAMS = BktParameters()
_ITEM = IrtItem(difficulty=0.0, discrimination=1.0)

Label = MasteryLevel | None
Variant = Literal["current", "min_evidence", "stair_cap", "signal_only"]

#: 학생 발화 3종 — 중립 / 좌절 / 답 요구(실제 토큰셋의 대표 문자열).
_UTTER = {"N": "x의 값을 다시 구해볼게요", "F": "모르겠어요", "D": "그냥 답 알려주세요"}
#: 후보 (나)의 최소 증거 수 — `l4_theta_min_responses` 기본값(3)과 같은 근거(응답 1~2개는 노이즈).
MIN_EVIDENCE = 3
#: 앱 학생의 전과목 θ 스냅샷은 적재 하한을 넘어야 존재한다 — 응답 3건 이상이고 발산 경계(전부
#: 정답·전부 오답)가 아닐 때만 적재한다(`l2/ability_snapshot_capture` · EOS-125). 하한 전의 코치는
#: θ가 없어 BKT만으로 라벨을 만든다. (API 클라이언트의 세션 종료·수동 스냅샷은 무게이트라 밖이다.)
_SNAPSHOT_MIN_RESPONSES = 3


def variant_level(
    *,
    student_input: str,
    turn_count: int,
    prev: int | None,
    label: Label,
    evidence_n: int,
    variant: Variant,
) -> int:
    """`decide_hint_level`의 후보 변형 — 규칙 5(`초보`/`숙달` 조정)만 다르다.

    - `current`: 실제 함수와 같다(충실도 단언 대상).
    - `min_evidence`(나): 증거 수 `evidence_n < MIN_EVIDENCE`면 라벨을 None으로 본다(양방향).
    - `stair_cap`(다): `초보` 상향이 5회+ 막힘 전에 사다리를 넘지 못하게 한다 — 신호 없는
      첫 턴의 1→2는 허용하되 좌절 사다리(2)와 부분 풀이(5회+ 막힘)의 순서를 지킨다.
    - `signal_only`(라): `초보` 상향을 신호(답 요구·좌절·막힘)가 있는 턴에만 적용한다.
    """
    prev_level = prev if prev is not None else 1
    text = student_input.strip()
    stuck = turn_count >= STUCK_TURN_THRESHOLD
    signal = has_any_token(text, DEMAND_ANSWER_TOKENS) or has_any_token(text, FRUSTRATION_TOKENS)
    if stuck:
        base = max(prev_level, 3)
    elif signal:
        base = min(4, prev_level + 1)
    else:
        base = 1
    eff: Label = label
    if variant == "min_evidence" and evidence_n < MIN_EVIDENCE:
        eff = None
    if eff == "숙달":
        base = max(1, base - 1)
    elif eff == "초보":
        if variant == "signal_only" and base == 1 and not stuck:
            pass
        else:
            boosted = min(4, base + 1)
            if variant == "stair_cap" and not stuck:
                boosted = min(boosted, max(base, 2))
            base = boosted
    if stuck:
        base = max(base, 3)
    return base


def _fidelity_check() -> int:
    """`variant_level(current)`가 실제 `decide_hint_level`과 격자 전체에서 일치하는가."""
    checked = 0
    for utter, turn, prev, label in itertools.product(
        _UTTER.values(), range(1, 8), (None, 1, 2, 3, 4), (None, "초보", "발전 중", "숙달")
    ):
        real = decide_hint_level(
            student_input=utter, turn_count=turn, prev_hint_level=prev, mastery_level=label
        )
        mine = variant_level(
            student_input=utter,
            turn_count=turn,
            prev=prev,
            label=label,
            evidence_n=99,
            variant="current",
        )
        if real != mine:
            print(f"✗ 충실도 불일치: {utter!r} turn={turn} prev={prev} label={label} {real}≠{mine}")
            return 1
        checked += 1
    print(f"충실도 단언 통과 — `current` 변형이 실제 `decide_hint_level`과 {checked}격자 일치")
    return 0


def _snapshot_theta(responses: list[tuple[IrtItem, bool]]) -> float | None:
    """적재 하한(응답 수 · 발산 경계 아님)을 넘은 뒤에만 존재하는 전과목 θ."""
    if len(responses) < _SNAPSHOT_MIN_RESPONSES or ability_boundary(responses) is not None:
        return None
    return estimate_ability(responses)


def _label_of(seq: tuple[bool, ...]) -> tuple[float | None, float | None, Label]:
    """결과열(정=True)에서 BKT 숙달 · 적재된 θ · 라벨(`_ability_level` — 현행 평균식)."""
    mastery: float | None = None
    responses: list[tuple[IrtItem, bool]] = []
    for correct in seq:
        mastery = update_mastery(0.3 if mastery is None else mastery, correct, _PARAMS)
        responses.append((_ITEM, correct))
    theta = _snapshot_theta(responses)
    return mastery, theta, _ability_level(mastery, theta)


def table_label_trajectories() -> None:
    print("\n## T1. 결과열 → 라벨과 신호 없는 턴의 단계")
    print("(O=정답 · X=오답 · 라벨 = BKT·θ 평균 · θ는 적재 하한을 넘은 뒤에만 ·")
    print(" (나) = 증거 3건 미만이면 라벨 없음)")
    print(
        "| 결과열 | BKT | 적재된 θ | 라벨(현행) | 단계(현행) | 사용으로 셈 | 라벨(나) | 단계(나) |"
    )
    print("|---|---|---|---|---|---|---|---|")
    for n in (0, 1, 2, 3):
        for seq in itertools.product((True, False), repeat=n):
            mastery, theta, label = _label_of(seq)
            level = decide_hint_level(
                student_input=_UTTER["N"], turn_count=2, prev_hint_level=None, mastery_level=label
            )
            label_b: Label = label if n >= MIN_EVIDENCE else None
            level_b = decide_hint_level(
                student_input=_UTTER["N"], turn_count=2, prev_hint_level=None, mastery_level=label_b
            )
            s = "".join("O" if c else "X" for c in seq) or "(없음)"
            bkt = "-" if mastery is None else f"{mastery:.3f}"
            th = "-" if theta is None else f"{theta:.2f}"
            use = "예" if counts_as_hint_usage(level) else "아니오"
            print(f"| {s} | {bkt} | {th} | {label} | {level} | {use} | {label_b} | {level_b} |")


def table_staircase() -> None:
    print("\n## T2. 발화 패턴별 단계 사다리 (턴 1~6 · 매 턴 결과가 다음 턴 prev로 들어간다)")
    patterns = ["NNNNNN", "FNNNNN", "NFNNNN", "FFNNNN", "FFFFFF", "DNNNNN"]
    print("| 발화 | 라벨 없음 | 발전 중 | 초보(현행) | 숙달 |")
    print("|---|---|---|---|---|")
    for pat in patterns:
        cells: list[str] = []
        for label in (None, "발전 중", "초보", "숙달"):
            prev: int | None = None
            seq: list[int] = []
            for turn, ch in enumerate(pat, start=1):
                level = decide_hint_level(
                    student_input=_UTTER[ch],
                    turn_count=turn,
                    prev_hint_level=prev,
                    mastery_level=label,
                )
                seq.append(level)
                prev = level
            cells.append("".join(map(str, seq)))
        print(f"| {pat} | {cells[0]} | {cells[1]} | {cells[2]} | {cells[3]} |")


def _first_correct_help(levels: list[int]) -> bool:
    """정답 직전까지 공급된 단계 중 2 이상이 있는가 — EOS-133 귀속(`used_hint`)의 단순형."""
    return any(counts_as_hint_usage(v) for v in levels)


_VARIANTS: list[Variant] = ["current", "min_evidence", "stair_cap", "signal_only"]
_NAMES: dict[str, str] = {
    "current": "(가) 현행",
    "min_evidence": "(나) 증거 3건 미만이면 라벨 없음",
    "stair_cap": "(다) 사다리 순서 보존",
    "signal_only": "(라) 신호 없는 턴은 상향 안 함",
}


def table_candidates() -> None:
    print("\n## T3. 후보별 — 첫 시도 오답 뒤 재시도 장면의 단계 열과 `used_hint`")
    print("(오답 한 건이 적재된 직후 = T1의 `X` 행 · 증거 수 1 · 재시도 중 발화 패턴별)")
    scenes = {
        "오답 → 중립 재시도 3턴": "NNN",
        "오답 → 좌절 1턴 → 중립 2턴": "FNN",
        "오답 → 좌절 3턴": "FFF",
        "오답 → 좌절 2턴 → 중립 1턴": "FFN",
        "오답 → 답 요구 1턴": "DNN",
    }
    print("| 장면 | " + " | ".join(_NAMES[v] for v in _VARIANTS) + " |")
    print("|---|" + "---|" * len(_VARIANTS))
    for title, pat in scenes.items():
        cells: list[str] = []
        for variant in _VARIANTS:
            prev: int | None = None
            levels: list[int] = []
            for turn, ch in enumerate(pat, start=1):
                level = variant_level(
                    student_input=_UTTER[ch],
                    turn_count=turn,
                    prev=prev,
                    label="초보",
                    evidence_n=1,
                    variant=variant,
                )
                levels.append(level)
                prev = level
            help_flag = "도움" if _first_correct_help(levels) else "독립"
            cells.append(f"{''.join(map(str, levels))} · {help_flag}")
        print(f"| {title} | " + " | ".join(cells) + " |")


def _simulate_carry_over(
    q: float, abandon: float, *, seeds: int = 300, problems: int = 30
) -> tuple[float, float]:
    """문제 시작 시 `초보` 비율 · 첫 시도 독립 성공이 `초보`로 시작한 비율(교차 이월 오귀속)."""
    start = novice = indep = flagged = 0
    for seed in range(seeds):
        rng = random.Random(seed)
        mastery: float | None = None
        responses: list[tuple[IrtItem, bool]] = []
        for k in range(problems):
            label = _ability_level(mastery, _snapshot_theta(responses))
            if k >= 1:
                start += 1
                novice += label == "초보"
            if rng.random() < q:
                if k >= 1:
                    indep += 1
                    flagged += label == "초보"
                mastery = update_mastery(0.3 if mastery is None else mastery, True, _PARAMS)
                responses.append((_ITEM, True))
            else:
                mastery = update_mastery(0.3 if mastery is None else mastery, False, _PARAMS)
                responses.append((_ITEM, False))
                if rng.random() >= abandon:  # 이탈하지 않고 완료(정답 행이 이어진다)
                    mastery = update_mastery(mastery, True, _PARAMS)
                    responses.append((_ITEM, True))
    return novice / max(1, start), flagged / max(1, indep)


def table_carry_over() -> None:
    print("\n## T4. 교차 이월 — 이전 문항의 오답이 **새 문항**의 독립 성공을 도움으로 오귀속하는가")
    print("(합성 학생 · 시드 300 · 30문항 · 오답 뒤 이탈률은 실측이 없어 격자로 둔다 — EOS-41)")
    print("| 첫 시도 정답확률 q | 이탈률 | 문항 시작 시 `초보` 비율 | 독립 성공의 오귀속 비율 |")
    print("|---|---|---|---|")
    for q in (0.5, 0.7, 0.9):
        for abandon in (0.0, 0.2, 0.4, 0.6):
            novice, flagged = _simulate_carry_over(q, abandon)
            print(f"| {q} | {abandon} | {novice:.3f} | {flagged:.3f} |")


def _simulate_wrong_first(
    variant: Variant, q: float, signal_p: float, *, seeds: int = 300, problems: int = 30
) -> tuple[float, float]:
    """오답 뒤 완료한 문항 중 도움으로 귀속되는 비율 · 그중 학생 신호 없이 라벨 때문인 비율.

    오답 뒤 재시도 2턴에서 학생은 확률 `signal_p`로 좌절을 말한다(나머지는 중립). 단계는 변형
    규칙으로 정한다. 라벨 = 이력의 BKT·적재 θ(현행 평균식) · 증거 수 = 누적 관측 수.
    """
    wrong_first = helped = label_only = 0
    for seed in range(seeds):
        rng = random.Random(seed)
        mastery: float | None = None
        responses: list[tuple[IrtItem, bool]] = []
        for _ in range(problems):
            if rng.random() < q:
                mastery = update_mastery(0.3 if mastery is None else mastery, True, _PARAMS)
                responses.append((_ITEM, True))
                continue
            # 첫 시도 오답 적재 — 라벨이 바뀐 뒤의 재시도 턴들
            mastery = update_mastery(0.3 if mastery is None else mastery, False, _PARAMS)
            responses.append((_ITEM, False))
            label = _ability_level(mastery, _snapshot_theta(responses))
            n_evidence = len(responses)
            prev: int | None = None
            levels: list[int] = []
            had_signal = False
            for turn in (1, 2):
                frustrated = rng.random() < signal_p
                had_signal = had_signal or frustrated
                utter = _UTTER["F"] if frustrated else _UTTER["N"]
                level = variant_level(
                    student_input=utter,
                    turn_count=turn,
                    prev=prev,
                    label=label,
                    evidence_n=n_evidence,
                    variant=variant,
                )
                levels.append(level)
                prev = level
            wrong_first += 1
            if _first_correct_help(levels):
                helped += 1
                label_only += not had_signal
            mastery = update_mastery(mastery, True, _PARAMS)
            responses.append((_ITEM, True))
    return helped / max(1, wrong_first), label_only / max(1, helped)


def table_wrong_first() -> None:
    print("\n## T5. 오답 뒤 완료한 문항 — 도움 귀속 비율 / 그중 신호 없이 라벨 때문인 비율")
    print("(합성 학생 · 시드 300 · 30문항 · 재시도 2턴 · 신호 확률 = 턴마다 좌절을 말할 확률)")
    print("| q | 신호 확률 | " + " | ".join(_NAMES[v] for v in _VARIANTS) + " |")
    print("|---|---|" + "---|" * len(_VARIANTS))
    for q in (0.5, 0.7, 0.9):
        for sig in (0.0, 0.3, 0.6):
            cells: list[str] = []
            for variant in _VARIANTS:
                helped, only = _simulate_wrong_first(variant, q, sig)
                cells.append(f"{helped:.2f} / {only:.2f}")
            print(f"| {q} | {sig} | " + " | ".join(cells) + " |")


def main() -> int:
    if _fidelity_check() != 0:
        return 1
    table_label_trajectories()
    table_staircase()
    table_candidates()
    table_carry_over()
    table_wrong_first()
    return 0


if __name__ == "__main__":
    sys.exit(main())
