#!/usr/bin/env python3
"""EOS-39 하강 채널 후보 실측 — 합성 학생에게 후보 규칙을 같은 조건으로 돌려 센다.

판정문 `docs/reviews/eos39_app_help_completion_selection_judgment_2026-10-06.md`가 쓴 수치의
**재현 스크립트**다. 선례 EOS-147 판정문은 "시뮬레이션 스크립트는 저장소에 없다"를 정직한 공백으로
적었다 — 이 스크립트가 그 공백을 메운다(같은 입력 → 같은 출력, 시드 고정, 저장소 실물 함수 사용).

무엇을 재는가
-------------
앱 학생의 추천열이 **학생 행동에 반응하는가**, 그리고 반응한다면 학생 수준으로 수렴하는가.
모델(방향의 증거이지 운영 수치가 아니다 — 가정은 전부 아래 상수와 `simulate`에 있다):

- 은행: 라벨 1~5 균등 401문항(`difficulty_to_logit`으로 b = −2 ~ +2). 선택은 미시도 문항 중
  `|b − θ_선택|` 최소(변별도 a=1이면 정보량 최대와 같다 — 가중 없는 기본 CAT 경로).
- 학생: 진짜 능력 θ_true(−1·0·+1). 문항 b에서 **독립 성공** 확률 σ(θ_true − b).
- 독립 성공이 아니면 코치 도움으로 완료한다(`used_hint`가 참인 정답 행 — `api/coach.py::
  _complete_problem`). 그 앞에 **명확한 오답을 먼저 제출**할 확률이 `q_wrong`이다(EOS-146 이후:
  문제당 최초 1건의 `is_correct=False` 행, `used_hint=NULL` — `_record_wrong_submission`).
- 귀속 오류: 라벨 `used_hint`가 `none_rate`만큼 미상(NULL)이고 `mislabel`만큼 뒤집힌다
  (EOS-133 귀속의 오귀속률은 **운영 측정이 없다** — 그래서 값을 정하지 않고 민감도로 센다).

후보 규칙(선택 θ만 바꾼다 — 추정 θ·SE·능력 API는 어느 후보에서도 불변):

- `pre147`    : 추정 θ 그대로(전부 정답이면 4.0) — EOS-147 이전.
- `current`   : 현행 main — 전부 정답이면 맞힌 최고 난이도 + 0.5.
- `a1`        : ⓐ 초안 — 도움 완료 **행**을 오답으로 센다(그 문항에 오답 행이 이미 있으면 뒤집지
                않는다 — 같은 어려움을 두 번 세지 않으려는 의도). 하한은 그대로(전부 오답 → −4.0).
                오답 뒤 도움 완료 흐름에서 **효과가 없음**을 보이려고 남겨 둔 대조 후보다.
- `a2`        : ⓐ 개정 — 문항 단위로 접는다. 도움을 쓴 문항은 오답 행 유무와 무관하게 **실패 응답
                1건**이다(실패를 두 번 세지 않으면서 도움 완료를 독립 성공으로 세지 않는다).
                도움 없이 오답 뒤 스스로 고친 문항은 종전대로 오답+정답 한 쌍이다. 하한은 그대로.
- `a2_sym`    : `a2` + 선택용 응답이 전부 오답일 때 하한 고정 대신 실패한 최저 난이도에서 한
                단계만 내린다(전부 정답 쪽 사다리와 대칭).
- `b`         : ⓑ 최고 난이도 앵커에서 도움 완료만 **제외**(전부 정답 이력에서만).

사용: `python3 scripts/analysis/eos39_selection_channel_sim.py [--seeds N] [--rows N]`
종료 코드 0 = 정상 출력 · 2 = 인자 오류. 판정 기준을 내는 도구가 아니라 **표를 내는** 도구다.
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from collections.abc import Callable
from dataclasses import dataclass

from whymath_backend.l2.ability_estimation import difficulty_to_logit
from whymath_backend.l2.irt import (
    _THETA_LOWER,
    _THETA_UPPER,
    ALL_CORRECT_STEP_LOGIT,
    IrtItem,
    ability_boundary,
    ability_for_selection,
    estimate_ability,
)

# (문항 인덱스, is_correct, used_hint) — `problem_attempt` 한 행의 이 시뮬레이션용 투영.
Row = tuple[int, bool, bool | None]
Policy = Callable[[list[Row]], float]

NUM_ITEMS = 401
#: 은행 난이도 b — 라벨 1~5 균등을 logit으로(오름차순 — 인덱스가 곧 순위).
BANK_B: list[float] = [
    difficulty_to_logit(1.0 + 4.0 * i / (NUM_ITEMS - 1)) for i in range(NUM_ITEMS)
]
THETA_TRUES = (-1.0, 0.0, 1.0)


def _responses(rows: list[Row]) -> list[tuple[IrtItem, bool]]:
    return [(IrtItem(difficulty=BANK_B[i]), correct) for i, correct, _ in rows]


def _flipped_responses(rows: list[Row]) -> list[tuple[IrtItem, bool]]:
    """`a1` — 도움 완료 **행**을 오답으로 센 응답. 그 문항에 오답 행이 이미 있으면 뒤집지 않는다.

    `used_hint is None`(미상)은 정답 그대로다 — 모른다는 도움을 받았다가 아니다.
    """
    wrong_items = {i for i, correct, _ in rows if not correct}
    out: list[tuple[IrtItem, bool]] = []
    for i, correct, used_hint in rows:
        counted = correct
        if correct and used_hint is True and i not in wrong_items:
            counted = False
        out.append((IrtItem(difficulty=BANK_B[i]), counted))
    return out


def _collapsed_responses(rows: list[Row]) -> list[tuple[IrtItem, bool]]:
    """`a2` — 문항 단위로 접은 선택용 응답.

    문항마다: 도움 완료 행(`used_hint is True`인 정답)이 하나라도 있으면 **오답 1건**(오답 행이
    있었든 없었든 실패는 한 번만 센다). 아니면 행을 있는 그대로 둔다 — 도움 없이 오답 뒤 스스로
    고친 문항은 오답+정답 한 쌍(반반 맞힌 문항 — 종전과 같다), 미상(`None`) 라벨의 정답은 정답.
    """
    order: list[int] = []
    by_item: dict[int, list[Row]] = {}
    for row in rows:
        if row[0] not in by_item:
            order.append(row[0])
            by_item[row[0]] = []
        by_item[row[0]].append(row)
    out: list[tuple[IrtItem, bool]] = []
    for i in order:
        item_rows = by_item[i]
        item = IrtItem(difficulty=BANK_B[i])
        if any(correct and used_hint is True for _, correct, used_hint in item_rows):
            out.append((item, False))
        else:
            out.extend((item, correct) for _, correct, _ in item_rows)
    return out


def policy_pre147(rows: list[Row]) -> float:
    return estimate_ability(_responses(rows))


def policy_current(rows: list[Row]) -> float:
    resp = _responses(rows)
    return ability_for_selection(resp, estimate_ability(resp))


def policy_a1(rows: list[Row]) -> float:
    resp = _flipped_responses(rows)
    return ability_for_selection(resp, estimate_ability(resp))


def _lower_ladder(resp: list[tuple[IrtItem, bool]]) -> float:
    """전부 오답일 때 대칭 규칙 — 실패한 최저 난이도에서 한 단계만 내린다(시작점 위로는 안 올림)."""
    cold = estimate_ability([])
    reach = min(item.difficulty for item, _ in resp) - ALL_CORRECT_STEP_LOGIT
    return max(_THETA_LOWER, min(cold, reach))


def policy_a2(rows: list[Row]) -> float:
    resp = _collapsed_responses(rows)
    return ability_for_selection(resp, estimate_ability(resp))


def policy_a2_sym(rows: list[Row]) -> float:
    resp = _collapsed_responses(rows)
    if ability_boundary(resp) == "lower":
        return _lower_ladder(resp)
    return ability_for_selection(resp, estimate_ability(resp))


def policy_b(rows: list[Row]) -> float:
    resp = _responses(rows)
    est = estimate_ability(resp)
    if ability_boundary(resp) != "upper":
        return est
    cold = estimate_ability([])
    independent = [BANK_B[i] for i, _, used_hint in rows if used_hint is not True]
    reach = (max(independent) + ALL_CORRECT_STEP_LOGIT) if independent else cold
    return min(_THETA_UPPER, max(cold, reach))


POLICIES: dict[str, Policy] = {
    "pre147": policy_pre147,
    "current": policy_current,
    "a1": policy_a1,
    "a2": policy_a2,
    "a2_sym": policy_a2_sym,
    "b": policy_b,
}


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    q_wrong: float  # 독립 성공이 아닐 때 먼저 명확한 오답을 제출할 확률(EOS-146)
    none_rate: float = 0.0  # `used_hint` 라벨이 미상(NULL)일 확률
    mislabel: float = 0.0  # 미상이 아닌 라벨이 뒤집힐 확률(EOS-133 오귀속)
    complete_after_fail: float = (
        1.0  # 독립 성공이 아닐 때 도움으로 **완료**할 확률(아니면 오답 행만)
    )


SCENARIOS = (
    Scenario("개루프(오답 제출 없음)", q_wrong=0.0),
    Scenario("오답 뒤 도움 완료 절반", q_wrong=0.5),
    Scenario("오답 뒤 도움 완료 전부", q_wrong=1.0),
    Scenario("오답 뒤 절반만 완료(나머지는 오답 행만)", q_wrong=1.0, complete_after_fail=0.5),
    Scenario("절반 + 라벨 30% 미상", q_wrong=0.5, none_rate=0.3),
    Scenario("절반 + 라벨 20% 오귀속", q_wrong=0.5, mislabel=0.2),
)


def _nearest_unattempted(remaining: list[int], theta: float) -> int:
    """미시도 문항 중 `|b − θ|` 최소(동률은 낮은 b) — `remaining`은 인덱스 오름차순(b 오름차순)."""
    best = remaining[0]
    best_gap = abs(BANK_B[best] - theta)
    for idx in remaining[1:]:
        gap = abs(BANK_B[idx] - theta)
        if gap < best_gap:
            best, best_gap = idx, gap
        elif BANK_B[idx] > theta:
            break  # 정렬돼 있어 θ를 넘긴 뒤에는 더 멀어지기만 한다
    return best


@dataclass(slots=True)
class Result:
    p_mean: float
    low_share: float  # 독립 성공확률 < 0.25 인 서빙 비율
    high_share: float  # 독립 성공확률 > 0.90 인 서빙 비율(너무 쉬움)
    label_at_10: float
    label_at_n: float
    pin_lower_share: float  # 선택 θ가 하한(−4.0)에 붙은 비율
    first_help_theta: float  # 첫 도움 완료 직후 선택 θ(없으면 NaN)


def simulate(
    policy: Policy, theta_true: float, scenario: Scenario, seed: int, n_rows: int
) -> Result:
    rng = random.Random(seed)
    # 경로와 무관하게 같은 난수열을 쓴다(정책끼리 공통 난수 — 선택이 달라도 결정이 t에 묶인다).
    u_success = [rng.random() for _ in range(n_rows)]
    u_wrong = [rng.random() for _ in range(n_rows)]
    u_none = [rng.random() for _ in range(n_rows)]
    u_mis = [rng.random() for _ in range(n_rows)]
    u_done = [rng.random() for _ in range(n_rows)]
    remaining = list(range(NUM_ITEMS))
    rows: list[Row] = []
    ps: list[float] = []
    labels: list[float] = []
    pinned = 0
    first_help_theta = math.nan
    for t in range(n_rows):
        theta_sel = policy(rows) if rows else estimate_ability([])
        if theta_sel <= _THETA_LOWER + 1e-9:
            pinned += 1
        idx = _nearest_unattempted(remaining, theta_sel)
        remaining.remove(idx)
        p = 1.0 / (1.0 + math.exp(-(theta_true - BANK_B[idx])))
        ps.append(p)
        labels.append(BANK_B[idx] + 3.0)
        independent = u_success[t] < p
        label: bool | None
        if u_none[t] < scenario.none_rate:
            label = None
        else:
            truth = not independent
            label = (not truth) if u_mis[t] < scenario.mislabel else truth
        if independent:
            rows.append((idx, True, label))
        else:
            if u_wrong[t] < scenario.q_wrong:
                rows.append((idx, False, None))
            if u_done[t] < scenario.complete_after_fail:
                rows.append((idx, True, label))
            if math.isnan(first_help_theta):
                first_help_theta = policy(rows)
    n = len(ps)
    return Result(
        p_mean=sum(ps) / n,
        low_share=sum(1 for p in ps if p < 0.25) / n,
        high_share=sum(1 for p in ps if p > 0.90) / n,
        label_at_10=labels[min(9, n - 1)],
        label_at_n=labels[-1],
        pin_lower_share=pinned / n,
        first_help_theta=first_help_theta,
    )


def _mean(values: list[float]) -> float:
    real = [v for v in values if not math.isnan(v)]
    return sum(real) / len(real) if real else math.nan


def run(seeds: int, n_rows: int) -> None:
    print(f"# EOS-39 하강 채널 후보 실측 — 시드 {seeds} · 서빙 {n_rows}건 · 은행 {NUM_ITEMS}문항")
    print("# 방향의 증거이지 운영 수치가 아니다(합성 학생 · 가정은 파일 머리 docstring).\n")
    for scenario in SCENARIOS:
        print(
            f"## {scenario.name} (q_wrong={scenario.q_wrong} · 미상={scenario.none_rate} "
            f"· 오귀속={scenario.mislabel})"
        )
        print(
            "| 규칙 | θ_true | P̄ | P<0.25 | P>0.90 | 라벨@10 | 라벨@끝 "
            "| 하한 고정 | 첫 도움 뒤 θ_선택 |"
        )
        print("|---|---|---|---|---|---|---|---|---|")
        for name, policy in POLICIES.items():
            for theta_true in THETA_TRUES:
                res = [simulate(policy, theta_true, scenario, s, n_rows) for s in range(seeds)]
                print(
                    f"| {name} | {theta_true:+.0f} | "
                    f"{_mean([r.p_mean for r in res]):.3f} | "
                    f"{_mean([r.low_share for r in res]):.2f} | "
                    f"{_mean([r.high_share for r in res]):.2f} | "
                    f"{_mean([r.label_at_10 for r in res]):.2f} | "
                    f"{_mean([r.label_at_n for r in res]):.2f} | "
                    f"{_mean([r.pin_lower_share for r in res]):.2f} | "
                    f"{_mean([r.first_help_theta for r in res]):+.2f} |"
                )
        print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EOS-39 하강 채널 후보 실측(합성 학생).")
    parser.add_argument("--seeds", type=int, default=300, help="시드 수(기본 300)")
    parser.add_argument("--rows", type=int, default=30, help="학생당 서빙 수(기본 30)")
    args = parser.parse_args(argv)
    if args.seeds < 1 or args.rows < 2:
        print("--seeds ≥ 1, --rows ≥ 2 여야 한다", file=sys.stderr)
        return 2
    run(args.seeds, args.rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
