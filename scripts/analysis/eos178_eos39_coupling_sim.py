#!/usr/bin/env python3
"""EOS-178 × EOS-39 결합 합성 시뮬레이션 — 힌트 귀속 규칙이 추천 표적에 주는 영향.

판정문(`docs/reviews/eos178_beginner_label_hint_judgment_2026-10-06.md`) §3-2·§4의 "학생에게
서빙되는 문항의 독립 성공확률" 표를 만든다. 합성 학생의 확률은 가정이라 **방향의 증거**이지
운영 수치가 아니다.

이 시뮬레이터는 독립 교수학 비판(2026-10-06)이 만든 확장 시뮬레이터를 **저장소로 옮긴 것**이다
(비판 보고서의 표를 같은 입력으로 재현하는지 먼저 확인했다). 초안 스크립트
`eos178_label_trajectory.py`와 다른 점:

 1) BKT는 (학생, 개념)별 사슬이다(숙달은 저장 정밀도 소수 2자리로 반올림해 다음 사전이 된다).
 2) 전과목 θ는 스냅샷이다 — 응답 3건 이상에서 첫 적재, 이후 5건마다(`CAPTURE_STRIDE`).
    경계 θ도 적재된다.
 3) `turn_count`는 첫 메시지가 0이다(`create_session`). 제출 턴은 완료 상태머신이 가로채
    공급 행이 없다.
 4) 반사실(라벨 없는 세계)이 아니라 **추천 루프**를 돈다: EOS-39 표적 규칙
    (`policy_a2_narrow`)이 문항을 고르고 그 문항의 `used_hint` 라벨이 다음 표적을 움직인다.
    라벨 규칙만 정책별로 바꾼다.

라벨·BKT·θ 추정은 저장소의 실제 함수(`_ability_level`·`update_mastery`·`estimate_ability`)를
부른다. 표적 규칙·문항 은행은 `eos39_selection_channel_sim.py`(EOS-39 판정문의 수치를 만든
같은 스크립트)를 쓴다.

지표: P̄ = 서빙된 문항의 독립 성공확률 평균 · 어려움 = P < 0.25 비율(너무 어려움 — 정서 안전 축) ·
      쉬움 = P > 0.90 비율(너무 쉬움 — 학습 효과 축).

사용: `python3 scripts/analysis/eos178_eos39_coupling_sim.py [--seeds N]`  (기본 300)
종료 코드 0 = 표 출력.
"""

from __future__ import annotations

import argparse
import importlib.util
import math
import random
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from whymath_backend.api.coach import _ability_level
from whymath_backend.l2.bkt import BktParameters, update_mastery
from whymath_backend.l2.irt import IrtItem, ability_standard_error, estimate_ability
from whymath_backend.l4.hint_deferral import STUCK_TURN_THRESHOLD

_PARAMS = BktParameters()
Label = Literal["초보", "발전 중", "숙달"] | None

#: 발화 종류: N 중립 · F 좌절 · D 답 요구 — 학생 신호 = F 또는 D
SIGNAL = {"F", "D"}
CAPTURE_STRIDE = 5
THETA_MIN_RESPONSES = 3


def _load_eos39_sim() -> Any:
    """EOS-39 표적 규칙 시뮬레이터를 경로로 불러온다(`scripts/analysis`는 패키지가 아니다)."""
    path = Path(__file__).with_name("eos39_selection_channel_sim.py")
    spec = importlib.util.spec_from_file_location("_eos39_selection_channel_sim", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"EOS-39 시뮬레이터 스펙 생성 실패: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


e39 = _load_eos39_sim()


def sig(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def ladder(
    utter: str, turn_count: int, prev: int | None, label: Label, variant: str = "current"
) -> tuple[int, int]:
    """(최종 단계, 규칙 5 이전 단계) — `decide_hint_level`과 같은 구조 + 변형 `signal_only`."""
    prev_level = prev if prev is not None else 1
    stuck = turn_count >= STUCK_TURN_THRESHOLD
    signal = utter in SIGNAL
    if stuck:
        base = max(prev_level, 3)
    elif signal:
        base = min(4, prev_level + 1)
    else:
        base = 1
    base0 = base
    if label == "숙달":
        base = max(1, base - 1)
    elif label == "초보":
        if variant == "signal_only" and base == 1 and not stuck:
            pass
        else:
            base = min(4, base + 1)
    if stuck:
        base = max(base, 3)
    return base, base0


@dataclass
class Student:
    theta_true: float
    concept_mastery: dict[int, tuple[float, int]] = field(default_factory=dict)
    responses: list[tuple[IrtItem, bool]] = field(default_factory=list)
    snap_theta: float | None = None
    snap_count: int = 0

    def observe(self, concept: int, b: float, correct: bool) -> None:
        m, n = self.concept_mastery.get(concept, (None, 0))  # type: ignore[assignment]
        prior = 0.3 if m is None else m
        self.concept_mastery[concept] = (round(update_mastery(prior, correct, _PARAMS), 2), n + 1)
        self.responses.append((IrtItem(difficulty=b), correct))
        graded = len(self.responses)
        if self.snap_theta is None and graded < THETA_MIN_RESPONSES:
            return
        if self.snap_theta is not None and graded - self.snap_count < CAPTURE_STRIDE:
            return
        theta = estimate_ability(self.responses)
        if math.isinf(ability_standard_error(theta, [i for i, _ in self.responses])):
            return
        self.snap_theta, self.snap_count = theta, graded

    def label(self, concept: int, min_evidence: int = 0, mode: str = "obs") -> Label:
        """mode `obs`: 증거 미달이면 BKT만 뺀다(θ만 남는다) · `obs_none_all`: 라벨 자체를 뺀다."""
        m, n = self.concept_mastery.get(concept, (None, 0))
        if mode == "obs_none_all":
            if n < min_evidence:
                return None
        elif m is not None and n < min_evidence:
            m = None
        return _ability_level(m, self.snap_theta)


@dataclass
class Flow:
    pre: list[str]  # 첫 제출 전 발화
    first_correct: bool  # 첫 제출이 정답인가
    retries: list[str]  # 오답 뒤 재시도 발화
    complete: bool  # 오답 뒤 완료하는가(아니면 이탈)


def run_dialogue(
    flow: Flow, label_before: Label, label_after_wrong: Label, variant: str
) -> tuple[list[int], list[int]]:
    """공급 행 열(최종 단계) · 라벨 없는 단계 열. 메시지 k의 turn_count는 k(첫 메시지 0).

    제출 턴은 가로챈 턴이라 공급 행이 없다(EOS-30). 첫 제출이 정답이면 그 뒤도 행이 없다.
    """
    levels: list[int] = []
    bases: list[int] = []
    prev: int | None = None
    k = 0
    for u in flow.pre:
        lv, b0 = ladder(u, k, prev, label_before, variant)
        levels.append(lv)
        bases.append(b0)
        prev = lv
        k += 1
    k += 1  # 제출 턴
    if flow.first_correct:
        return levels, bases
    for u in flow.retries:
        lv, b0 = ladder(u, k, prev, label_after_wrong, variant)
        levels.append(lv)
        bases.append(b0)
        prev = lv
        k += 1
    return levels, bases


def used(levels: list[int]) -> bool:
    """종전(EOS-133) 귀속 — 공급 단계 중 2 이상이 하나라도 있는가."""
    return any(v >= 2 for v in levels)


@dataclass
class Cfg:
    K: int = 20
    theta_true: float = 0.0
    p_sig: float = 0.3
    q_wrong: float = 0.7
    complete_prob: float = 0.85
    pre_dist: tuple[float, float, float] = (0.5, 0.3, 0.2)
    ret_dist: tuple[float, float, float, float] = (0.15, 0.35, 0.30, 0.20)
    min_evidence: int = 0
    evid_mode: str = "obs"
    variant: str = "current"


def gen_flow(rng: random.Random, cfg: Cfg, p: float) -> tuple[Flow, str]:
    """한 문항의 대화 흐름 — 독립 성공 / 오답 선제출 후 재시도 / 오답 없이 막혀 대화한 뒤 정답."""
    m0 = rng.choices([0, 1, 2], cfg.pre_dist)[0]
    pre = ["F" if rng.random() < cfg.p_sig else "N" for _ in range(m0)]
    if rng.random() < p:
        return Flow(pre, True, [], True), "indep"
    if rng.random() < cfg.q_wrong:
        r = rng.choices([0, 1, 2, 3], cfg.ret_dist)[0]
        retries = ["F" if rng.random() < cfg.p_sig else "N" for _ in range(r)]
        return Flow(pre, False, retries, rng.random() < cfg.complete_prob), "wrong"
    extra = rng.choices([1, 2, 3], [0.3, 0.4, 0.3])[0]
    chat = pre + ["F" if rng.random() < max(cfg.p_sig, 0.5) else "N" for _ in range(extra)]
    return Flow(chat, True, [], True), "helpchat"


#: 정책 = (표적 규칙, 라벨 변형 인자). 귀속 `final` = 종전(최종 단계 2+) · `base` = 출하(EOS-178).
POLICIES: dict[str, tuple[str, dict[str, Any]]] = {
    "EOS-39 끔(접기 없음)": ("current", {}),
    "(가) 현행 라벨·종전 귀속": ("a2_narrow", {}),
    "(나θ) 증거<3이면 BKT 뺌": ("a2_narrow", dict(min_evidence=3)),
    "(나') 증거<3이면 라벨 없음": ("a2_narrow", dict(min_evidence=3, evid_mode="obs_none_all")),
    "(라) 신호 없는 턴 상향 안 함": ("a2_narrow", dict(variant="signal_only")),
    "(마) 출하 — 라벨 없는 단계로 귀속": ("a2_narrow", dict(attr="base")),
}


def one(args: tuple[str, float, int, float, float, int, int]) -> tuple[float, float, float]:
    """학생 1명(시드 1개) — 30행 동안 추천 → 대화 → 귀속 → 다음 표적. (P̄, 어려움, 쉬움 비율)."""
    name, theta_true, n_concepts, p_sig, q_wrong, seed, n_rows = args
    sel, kw = POLICIES[name]
    kw = dict(kw)
    attr = kw.pop("attr", "final")
    cfg = Cfg(K=n_concepts, theta_true=theta_true, p_sig=p_sig, q_wrong=q_wrong, **kw)
    rng = random.Random(seed * 104729 + 7)
    concept_of = [rng.randrange(n_concepts) for _ in range(e39.NUM_ITEMS)]
    st = Student(theta_true)
    rows: list[tuple[int, bool, bool | None]] = []
    remaining = list(range(e39.NUM_ITEMS))
    ps: list[float] = []
    pol = e39.policy_a2_narrow if sel == "a2_narrow" else e39.policy_current
    for _ in range(n_rows):
        theta_sel = pol(rows) if rows else e39.estimate_ability([])
        idx = e39._nearest_unattempted(remaining, theta_sel)
        remaining.remove(idx)
        b = e39.BANK_B[idx]
        p = sig(theta_true - b)
        ps.append(p)
        c = concept_of[idx]
        flow, kind = gen_flow(rng, cfg, p)
        lab_before = st.label(c, cfg.min_evidence, cfg.evid_mode)
        if kind == "wrong":
            rows.append((idx, False, None))
            st.observe(c, b, False)
            lab_after = st.label(c, cfg.min_evidence, cfg.evid_mode)
        else:
            lab_after = lab_before
        lv, bs = run_dialogue(flow, lab_before, lab_after, cfg.variant)
        if flow.first_correct or flow.complete:
            flag = used(lv) if attr == "final" else any(x >= 2 for x in bs)
            rows.append((idx, True, flag))
            st.observe(c, b, True)
    n = len(ps)
    return (
        sum(ps) / n,
        sum(1 for p in ps if p < 0.25) / n,
        sum(1 for p in ps if p > 0.90) / n,
    )


def run_cell(
    pool: ProcessPoolExecutor,
    name: str,
    theta_true: float,
    n_concepts: int,
    p_sig: float,
    q_wrong: float,
    seeds: int,
) -> tuple[float, float, float]:
    args = [(name, theta_true, n_concepts, p_sig, q_wrong, s, 30) for s in range(seeds)]
    res = list(pool.map(one, args, chunksize=10))
    return tuple(sum(r[i] for r in res) / len(res) for i in range(3))  # type: ignore[return-value]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=300)
    args = parser.parse_args()
    print("# EOS-178 × EOS-39 결합 — 서빙된 문항의 독립 성공확률 P̄ | 너무 어려움(P<0.25) 비율")
    print(
        "(합성 학생 · K=20 개념 · 학생당 30행 · 시드 %d · 열 = 능력 θ_true −1 / 0 / +1)"
        % args.seeds
    )
    with ProcessPoolExecutor(4) as pool:
        for p_sig in (0.0, 0.3, 0.6):
            for q_wrong in (0.5, 1.0):
                print(f"\n## 좌절을 말할 확률 {p_sig} · 첫 시도 오답 확률 {q_wrong}")
                print("| 정책 | θ=−1 | θ=0 | θ=+1 |")
                print("|---|---|---|---|")
                for name in POLICIES:
                    cells = []
                    for th in (-1.0, 0.0, 1.0):
                        pbar, hard, _easy = run_cell(pool, name, th, 20, p_sig, q_wrong, args.seeds)
                        cells.append(f"{pbar:.3f} \\| {hard:.2f}")
                    print(f"| {name} | " + " | ".join(cells) + " |", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
