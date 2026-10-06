#!/usr/bin/env python3
"""EOS-178 — '초보' 라벨이 힌트 단계·`used_hint`를 어떻게 움직이는가: 재현 스크립트(v2).

판정문(`docs/reviews/eos178_beginner_label_hint_judgment_2026-10-06.md`)의 수치를 만든다.
합성 학생의 확률은 가정이라 **방향의 증거**이지 운영 수치가 아니다(운영 응답이 없다).

라벨·단계·귀속 규칙은 저장소의 **실제 함수**를 그대로 부른다 — `update_mastery` ·
`estimate_ability` · `ability_standard_error` · `_ability_level` · `decide_hint_level` ·
`decide_base_hint_level` · `counts_as_help_supply`. 이 스크립트가 규칙을 복제하지 않는다. 복제는
**후보 변형 3종**(`theta_only_lt3`·`none_lt3` — 라벨 입력을 바꾸는 후보, `signal_only` — 상향
조건)뿐이며,
`signal_only`의 라벨 없는 갈래가 실제 함수와 격자에서 일치하는지와 출하된 라벨 없는 단계가 격자에서
`base≥2 ⟺ 학생 신호`임을 먼저 단언한다(복제가 어긋나면 비교가 무의미하다).

v1(독립 비판 전)에서 고친 모델 결함 4건: ① 개념별 BKT — 숙달은 (학생, 개념) 단위라 새 개념의 첫
오답은 그 개념의 BKT를 처음부터 쌓는다 ② 전과목 θ 스냅샷의 실제 적재 규칙 — 응답 3건에서 처음
적재하고 이후 5건마다 갱신하며, 전부 정답이어도 SE는 유한이라 **경계 θ(4.0)도 적재된다**(v1은
경계를 제외했다) ③ 턴 수는 0부터다(`create_session`의 첫 결정이 `turn_count=0`) ④ v1은 후보 (나)를
"라벨 없음"으로 측정했으나 제안문은 "BKT를 빼고 θ만"이었다 — 둘을 다른 후보로 나눠 잰다.

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
from whymath_backend.l2.irt import (
    IrtItem,
    ability_standard_error,
    estimate_ability,
    theta_to_mastery_proxy,
)
from whymath_backend.l4.hint_deferral import (
    DEMAND_ANSWER_TOKENS,
    FRUSTRATION_TOKENS,
    STUCK_TURN_THRESHOLD,
    counts_as_help_supply,
    counts_as_hint_usage,
    decide_base_hint_level,
    decide_hint_level,
    has_any_token,
)
from whymath_backend.l4.lthc.adapt import mastery_to_level
from whymath_backend.l4.lthc.models import MasteryLevel

_PARAMS = BktParameters()
_ITEM = IrtItem(difficulty=0.0, discrimination=1.0)

Label = MasteryLevel | None
Variant = Literal["current", "theta_only_lt3", "none_lt3", "signal_only"]

#: 학생 발화 3종 — 중립 / 좌절 / 답 요구(실제 토큰셋의 대표 문자열).
_UTTER = {"N": "x의 값을 다시 구해볼게요", "F": "모르겠어요", "D": "그냥 답 알려주세요"}
#: 후보의 최소 증거 수 — `l4_theta_min_responses` 기본값(3)과 같은 근거(응답 1~2개는 노이즈).
MIN_EVIDENCE = 3
#: 전과목 θ 스냅샷 적재 규칙(`l2/ability_snapshot_capture`): 응답 3건에서 처음, 이후 5건마다.
_CAPTURE_FIRST = 3
_CAPTURE_STRIDE = 5


class Student:
    """합성 학생 — 개념별 BKT · 전과목 응답 · 적재된 θ 스냅샷(최신 1건)."""

    def __init__(self) -> None:
        self.bkt: dict[int, float] = {}
        self.n_concept: dict[int, int] = {}
        self.responses: list[tuple[IrtItem, bool]] = []
        self.snapshot: float | None = None
        self._captured_at = 0

    def record(self, concept: int, correct: bool) -> None:
        prior = self.bkt.get(concept, 0.3)
        self.bkt[concept] = update_mastery(prior, correct, _PARAMS)
        self.n_concept[concept] = self.n_concept.get(concept, 0) + 1
        self.responses.append((_ITEM, correct))
        n = len(self.responses)
        due = (self.snapshot is None and n >= _CAPTURE_FIRST) or (
            self.snapshot is not None and n - self._captured_at >= _CAPTURE_STRIDE
        )
        if due:
            theta = estimate_ability(self.responses)
            if ability_standard_error(theta, [i for i, _ in self.responses]) != float("inf"):
                self.snapshot = (
                    theta  # 경계 θ(전부 정답 4.0·전부 오답 −4.0)도 SE가 유한이라 적재된다
                )
                self._captured_at = n

    def label(self, concept: int, variant: Variant = "current") -> Label:
        """이 개념 문항에서 코치가 쓰는 라벨 — 실제 `_ability_level`을 부른다(변형은 입력만)."""
        bkt = self.bkt.get(concept)
        theta = self.snapshot
        thin = self.n_concept.get(concept, 0) < MIN_EVIDENCE
        if variant == "theta_only_lt3" and thin:
            bkt = None  # 제안문 그대로: 증거 3건 미만이면 BKT 성분을 뺀다(θ만 남는다)
        if variant == "none_lt3" and thin:
            return None  # v1이 잰 것: 증거 3건 미만이면 라벨 자체가 없다
        return _ability_level(bkt, theta)


def variant_level(
    *, student_input: str, turn_count: int, prev: int | None, label: Label, variant: Variant
) -> int:
    """`decide_hint_level` 호출 + `signal_only` 변형(라벨 상향을 신호 있는 턴에만 적용)."""
    if variant != "signal_only":
        return decide_hint_level(
            student_input=student_input,
            turn_count=turn_count,
            prev_hint_level=prev,
            mastery_level=label,
        )
    text = student_input.strip()
    stuck = turn_count >= STUCK_TURN_THRESHOLD
    signal = has_any_token(text, DEMAND_ANSWER_TOKENS) or has_any_token(text, FRUSTRATION_TOKENS)
    use = label if (label != "초보" or signal or stuck) else None
    return decide_hint_level(
        student_input=student_input, turn_count=turn_count, prev_hint_level=prev, mastery_level=use
    )


def _fidelity_check() -> int:
    """① `signal_only`의 라벨 없는 갈래가 실제 함수와 같다 ② 출하된 base가 신호와 동치다."""
    checked = 0
    for utter, turn, prev in itertools.product(_UTTER.values(), range(0, 8), (None, 1, 2, 3, 4)):
        signal = (
            has_any_token(utter, DEMAND_ANSWER_TOKENS)
            or has_any_token(utter, FRUSTRATION_TOKENS)
            or turn >= STUCK_TURN_THRESHOLD
        )
        base = decide_base_hint_level(student_input=utter, turn_count=turn, prev_hint_level=prev)
        if (base >= 2) is not signal:
            print(f"✗ base≥2 ⟺ 신호 불일치: {utter!r} turn={turn} prev={prev} base={base}")
            return 1
        for label in (None, "발전 중", "숙달"):
            mine = variant_level(
                student_input=utter, turn_count=turn, prev=prev, label=label, variant="signal_only"
            )
            real = decide_hint_level(
                student_input=utter, turn_count=turn, prev_hint_level=prev, mastery_level=label
            )
            if mine != real:
                print(f"✗ 충실도 불일치: {utter!r} turn={turn} prev={prev} label={label}")
                return 1
        checked += 1
    print(f"충실도 단언 통과 — 격자 {checked}점(발화 3 × 턴 0~7 × prev 5): base≥2 ⟺ 학생 신호")
    return 0


def _legacy_help(levels: list[int]) -> bool:
    """EOS-133 귀속(종전): 공급 단계 중 2 이상이 하나라도 있는가."""
    return any(counts_as_hint_usage(v) for v in levels)


def _free_help(rows: list[tuple[int, int]]) -> bool:
    """출하된 귀속(EOS-178): 실제 `counts_as_help_supply`(검수 힌트 미실림 가정 — 카탈로그 없음)."""
    return any(counts_as_help_supply(hint_level=lv, base_level=b, served=False) for lv, b in rows)


def _run_turns(
    pattern: str, label: Label, variant: Variant, *, start_turn: int
) -> tuple[list[int], list[int]]:
    """발화열을 돌려 (최종 단계열, 라벨 없는 단계열) — 최종 단계가 다음 턴 prev로 피드백된다."""
    prev: int | None = None
    levels: list[int] = []
    bases: list[int] = []
    for turn, ch in enumerate(pattern, start=start_turn):
        level = variant_level(
            student_input=_UTTER[ch], turn_count=turn, prev=prev, label=label, variant=variant
        )
        levels.append(level)
        bases.append(
            decide_base_hint_level(student_input=_UTTER[ch], turn_count=turn, prev_hint_level=prev)
        )
        prev = level
    return levels, bases


def table_label_trajectories() -> None:
    print("\n## T1. 결과열 → 라벨(한 개념 · 개념 BKT + 적재 θ)")
    print("(O=정답 · X=오답 · BKT 사전 0.3 · θ는 응답 3건에서 처음 적재 — 경계 θ 포함 ·")
    print(
        " 신호 없는 첫 재시도 턴(turn 1) 기준 · (나θ)=증거 3건 미만이면 BKT를 뺌 · (나')=라벨 없음)"
    )
    print("| 결과열 | BKT | θ | 라벨(가) | 단계(가) | 라벨(나θ) | 단계(나θ) | 라벨(나') |")
    print("|---|---|---|---|---|---|---|---|")
    for n in (1, 2, 3):
        for seq in itertools.product((True, False), repeat=n):
            s = Student()
            for correct in seq:
                s.record(0, correct)
            cur = s.label(0)
            th = s.label(0, "theta_only_lt3")
            non = s.label(0, "none_lt3")
            lv_c = decide_hint_level(
                student_input=_UTTER["N"], turn_count=1, prev_hint_level=None, mastery_level=cur
            )
            lv_t = decide_hint_level(
                student_input=_UTTER["N"], turn_count=1, prev_hint_level=None, mastery_level=th
            )
            theta = "-" if s.snapshot is None else f"{s.snapshot:.2f}"
            seq_s = "".join("O" if c else "X" for c in seq)
            print(
                f"| {seq_s} | {s.bkt[0]:.3f} | {theta} | {cur} | {lv_c} | {th} | {lv_t} | {non} |"
            )


def table_staircase() -> None:
    print("\n## T2. 발화 패턴별 단계 사다리 (턴 0~5 · 매 턴 결과가 다음 턴 prev로 들어간다)")
    patterns = ["NNNNNN", "FNNNNN", "NFNNNN", "FFNNNN", "NFFNNN", "FFFFFF", "DNNNNN"]
    print("| 발화 | 라벨 없음 | 발전 중 | 초보(현행) | 숙달 |")
    print("|---|---|---|---|---|")
    for pat in patterns:
        cells = [
            "".join(map(str, _run_turns(pat, label, "current", start_turn=0)[0]))
            for label in (None, "발전 중", "초보", "숙달")
        ]
        print(f"| {pat} | {cells[0]} | {cells[1]} | {cells[2]} | {cells[3]} |")


def table_scenes() -> None:
    print("\n## T3. 오답 뒤 재시도 장면 — 최종 단계 · 라벨 없는 단계 · 귀속(종전 / 출하)")
    print("(오답 한 건이 적재된 직후의 '초보' · 재시도 턴 1부터 · 귀속 열 = `도움`/`독립`)")
    scenes = {
        "오답 → 중립 재시도 3턴": "NNN",
        "오답 → 좌절 1턴 → 중립 2턴": "FNN",
        "오답 → 좌절 3턴": "FFF",
        "오답 → 중립 1턴 → 좌절 1턴": "NF",
        "오답 → 답 요구 1턴": "DNN",
    }
    print("| 장면 | 최종 단계 | 라벨 없는 단계 | 종전(가) 귀속 | 출하(마) 귀속 |")
    print("|---|---|---|---|---|")
    for title, pat in scenes.items():
        levels, bases = _run_turns(pat, "초보", "current", start_turn=1)
        rows = list(zip(levels, bases, strict=True))
        print(
            f"| {title} | {''.join(map(str, levels))} | {''.join(map(str, bases))} | "
            f"{'도움' if _legacy_help(levels) else '독립'} | "
            f"{'도움' if _free_help(rows) else '독립'} |"
        )


def _simulate_carry_over(
    q: float, abandon: float, concepts: int, *, seeds: int = 300, problems: int = 30
) -> tuple[float, float]:
    """문항 시작 시 '초보' 비율 · 첫 시도 독립 성공이 시작 행(turn 0)의 단계 2로 도움이 된 비율.

    뒤의 비율은 종전(EOS-133) 귀속 기준이다 — 시작 행이 귀속 창에 든다.
    """
    start = novice = indep = flagged = 0
    for seed in range(seeds):
        rng = random.Random(seed)
        s = Student()
        for k in range(problems):
            concept = rng.randrange(concepts)
            label = s.label(concept)
            opening = decide_hint_level(
                student_input=_UTTER["N"], turn_count=0, prev_hint_level=None, mastery_level=label
            )
            if k >= 1:
                start += 1
                novice += label == "초보"
            if rng.random() < q:
                if k >= 1:
                    indep += 1
                    flagged += counts_as_hint_usage(opening)  # 시작 행이 귀속 창에 든다
                s.record(concept, True)
            else:
                s.record(concept, False)
                if rng.random() >= abandon:  # 이탈하지 않고 완료
                    s.record(concept, True)
    return novice / max(1, start), flagged / max(1, indep)


def table_carry_over() -> None:
    print("\n## T4. 교차 이월 — 새 문항의 **시작 행**이 이전 이력의 '초보' 때문에 도움이 되는 비율")
    print("(합성 학생 · 시드 300 · 30문항 · 개념 수 K는 문항마다 균등 선택 · 출하(마)는 0 —")
    print(" 시작 행의 라벨 없는 단계는 항상 1이다)")
    print("| 개념 수 K | q | 이탈률 | 문항 시작 시 '초보' 비율 | 독립 성공의 종전 오귀속 비율 |")
    print("|---|---|---|---|---|")
    for concepts in (1, 3, 6):
        for q in (0.5, 0.7, 0.9):
            for abandon in (0.0, 0.4):
                novice, flagged = _simulate_carry_over(q, abandon, concepts)
                print(f"| {concepts} | {q} | {abandon} | {novice:.3f} | {flagged:.3f} |")


def _simulate_wrong_first(
    q: float, signal_p: float, concepts: int, *, seeds: int = 300, problems: int = 30
) -> tuple[float, float, float]:
    """오답 뒤 재시도 2턴을 거쳐 완료한 문항 중 (종전 귀속, 출하 귀속, 종전 중 라벨-단독) 비율."""
    wrong_first = legacy = free = label_only = 0
    for seed in range(seeds):
        rng = random.Random(seed)
        s = Student()
        for _ in range(problems):
            concept = rng.randrange(concepts)
            if rng.random() < q:
                s.record(concept, True)
                continue
            s.record(concept, False)  # 첫 시도 오답 적재 → 라벨이 바뀐 뒤의 재시도 턴들
            label = s.label(concept)
            pat = "".join("F" if rng.random() < signal_p else "N" for _ in range(2))
            levels, bases = _run_turns(pat, label, "current", start_turn=1)
            wrong_first += 1
            is_legacy = _legacy_help(levels)
            is_free = _free_help(list(zip(levels, bases, strict=True)))
            legacy += is_legacy
            free += is_free
            label_only += is_legacy and not is_free
            s.record(concept, True)
    return (
        legacy / max(1, wrong_first),
        free / max(1, wrong_first),
        label_only / max(1, legacy),
    )


def table_wrong_first() -> None:
    print("\n## T5. 오답 뒤 완료한 문항 — 종전 귀속 / 출하 귀속 / 종전 귀속 중 라벨-단독")
    print("(합성 학생 · 시드 300 · 30문항 · 재시도 2턴 · 신호 확률 = 턴마다 좌절을 말할 확률)")
    print("| K | q | 신호 확률 | 종전 귀속 | 출하 귀속 | 종전 중 라벨-단독 |")
    print("|---|---|---|---|---|---|")
    for concepts in (1, 4):
        for q in (0.5, 0.7, 0.9):
            for sig in (0.0, 0.3, 0.6):
                legacy, free, only = _simulate_wrong_first(q, sig, concepts)
                print(f"| {concepts} | {q} | {sig} | {legacy:.2f} | {free:.2f} | {only:.2f} |")


def table_theta_only_harm() -> None:
    print("\n## T6. 후보 (나θ)의 해 — 이력이 쌓인 학생이 **새 개념**에서 오답 한 건을 냈을 때")
    print(
        "(다른 개념에서 k건 정답 → 새 개념 첫 문항 오답 · 새 개념의 BKT는 0.146 · θ는 적재 스냅샷)"
    )
    print("(단계 열 = 같은 첫 재시도 턴(turn 1)의 최종 단계 — 중립 발화 / 좌절 발화 '모르겠어요')")
    print("| k | θ(적재) | θ 프록시 | 라벨(가) | 라벨(나θ) | 라벨(나') | (가) N/F | (나θ) N/F |")
    print("|---|---|---|---|---|---|---|---|")
    for k in (3, 5, 8):
        s = Student()
        for _ in range(k):
            s.record(0, True)
        s.record(1, False)
        theta = s.snapshot
        proxy = "-" if theta is None else f"{theta_to_mastery_proxy(theta):.3f}"
        cur = s.label(1)
        th = s.label(1, "theta_only_lt3")
        non = s.label(1, "none_lt3")
        levels = {
            (who, ch): decide_hint_level(
                student_input=_UTTER[ch], turn_count=1, prev_hint_level=None, mastery_level=label
            )
            for who, label in (("c", cur), ("t", th))
            for ch in ("N", "F")
        }
        theta_s = "-" if theta is None else f"{theta:.2f}"
        cn, cf = levels[("c", "N")], levels[("c", "F")]
        tn, tf = levels[("t", "N")], levels[("t", "F")]
        print(f"| {k} | {theta_s} | {proxy} | {cur} | {th} | {non} | {cn}/{cf} | {tn}/{tf} |")
    # 라벨 경계 확인 — 평균식이 0.4·0.8을 어떻게 끊는지(`mastery_to_level`)
    print(f"\n(경계: 0.39 → {mastery_to_level(0.39)} · 0.8 → {mastery_to_level(0.8)})")


def main() -> int:
    if _fidelity_check() != 0:
        return 1
    table_label_trajectories()
    table_staircase()
    table_scenes()
    table_carry_over()
    table_wrong_first()
    table_theta_only_harm()
    return 0


if __name__ == "__main__":
    sys.exit(main())
