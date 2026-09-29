"""EOS-33 판정 근거 계산 — 숙달 구간 관계 행위(선수 복귀·전진)의 증거 하한 효과.

판정문 `docs/reviews/eos33_mastery_band_relational_evidence_floor_judgment_2026-09-29.md`가
인용하는 수치를 **실제 코드 경로로** 다시 낸다(재현용 · 결정론 · DB 불요).

네 절(판정문 절 번호와 대응):
  ① 실측 고정(§1) — `l2/bkt.py::update_mastery` 커널 값과, 적재 경로(`compute_mastery_record`:
     소수 둘째 자리 반올림·표본·신뢰도)로 콜드스타트부터 관계 구간이 처음 발화하는 응답 수.
  ② 전진 하한(§3-2) — BKT 생성 모형(추정기와 같은 모수)에서 숨은 상태 경로까지 정확 열거해,
     발화 순간(응답 직후)의 상태로 거짓 전진(L=0에서 전진)·숙달자 하강을 가른다. 전진 하한만
     바꾼 행과, 독립 비판으로 폐기된 대칭 하한(선수 3·전진 3) 행을 함께 낸다.
  ③ 결손 학생(§3-3) — 선수 결손 때문에 C를 배울 수 없는 학생(정답률 고정·학습 없음)에서
     앵커 하한이 하강을 늦추고 거짓 전진을 늘리는지 잰다.
  ④ 수능 가중 편향(§7) — 권위·시그니처가 비었을 때 수능 가중(1+난이도)이 고르는 문항의 정답
     확률과 선수 구간 진입률. 희소 합성 풀(9문항)의 최악값이다 — 풀이 조밀하면 편향이 준다.

한계(판정문 §3-2·§8): 학생 모형은 BKT 자신의 가정(문항 무관 정답률·흡수 숙달·망각 0)이다.
모수가 맞는 BKT에서 사후 숙달은 충분통계라, 표본 하한의 가치는 모형 오지정에서 온다 — 이 계산은
방향을 보일 뿐 크기를 보증하지 않는다. 선수 개념 P는 모형에 없다.
"""

from __future__ import annotations

import argparse
import itertools
from types import SimpleNamespace

from whymath_backend.l2.ability_estimation import resolve_item_difficulty_b
from whymath_backend.l2.bkt import BktModel, BktParameters, update_mastery
from whymath_backend.l2.irt import IrtItem, probability_correct, select_weighted_item
from whymath_backend.l2.mastery_contract import compute_mastery_record
from whymath_backend.l2.recommendation_contract import ReasonType, select_reason_type
from whymath_backend.l6.suneung.recommendation import suneung_item_weight

_PARAMS = BktParameters()
_MODEL = BktModel(_PARAMS)
_RELATIONAL = (ReasonType.PREREQUISITE_GAP, ReasonType.NEXT_CONCEPT)


def _first_fire(
    observations: tuple[str, ...], k_pre: int, k_adv: int
) -> tuple[ReasonType, int] | None:
    """관측 경로 → (처음 발화한 관계 구간, 그 응답의 0-기반 위치). 발화 없으면 None.

    발화 = 적재 경로 추정의 구간이 관계 구간이고 그 개념의 표본이 방향별 하한 이상.
    """
    mastery: float | None = None
    sample: int | None = None
    for index, mark in enumerate(observations):
        record = compute_mastery_record(mastery, sample, mark == "C", _MODEL)
        mastery, sample = record.mastery, record.sample_size
        band = select_reason_type(mastery)
        floor = k_pre if band is ReasonType.PREREQUISITE_GAP else k_adv
        if band in _RELATIONAL and sample >= floor:
            return band, index
    return None


def section_measurements() -> None:
    """① 커널 값(acceptance ① 대조)과 적재 경로의 최초 발화 응답 수."""
    print("① 커널 update_mastery(반올림 전) — acceptance ① 대조")
    for prior, marks in ((0.55, "W"), (0.55, "C"), (0.80, "W"), (0.80, "WW"), (0.30, "W")):
        value = prior
        for mark in marks:
            value = update_mastery(value, mark == "C", _PARAMS)
        band = select_reason_type(value).value
        print(f"   사전 {prior:.2f} · 관측 {marks:<2} → {value:.3f} ({band})")
    print("① 적재 경로(콜드스타트 사전 0.30) — 응답 2개 이하에서 관계 구간에 닿는 경로")
    for length in (1, 2):
        for observations in itertools.product("CW", repeat=length):
            mastery: float | None = None
            sample: int | None = None
            confidence = 0.0
            for mark in observations:
                record = compute_mastery_record(mastery, sample, mark == "C", _MODEL)
                mastery, sample, confidence = (
                    record.mastery,
                    record.sample_size,
                    record.confidence,
                )
            assert mastery is not None
            band = select_reason_type(mastery)
            if band in _RELATIONAL:
                print(
                    f"   관측 {''.join(observations):<2} → 숙달 {mastery:.2f} · "
                    f"신뢰도 {confidence:.2f} · 표본 {sample} ({band.value})"
                )


def _classified_rates(start_mastered: float, k_pre: int, k_adv: int, horizon: int) -> dict:
    """숨은 상태 경로까지 열거해 발화 순간 상태로 분류한 확률."""
    rates = {"false_advance": 0.0, "true_advance": 0.0, "master_demoted": 0.0, "other": 0.0}
    for observations in itertools.product("CW", repeat=horizon):
        fired = _first_fire(observations, k_pre, k_adv)
        for start_state in (0, 1):
            weight = start_mastered if start_state == 1 else 1.0 - start_mastered
            if weight == 0.0:
                continue
            for transitions in itertools.product((0, 1), repeat=horizon):
                probability, state = weight, start_state
                after: list[int] = []
                feasible = True
                for index, mark in enumerate(observations):
                    if state == 1:
                        probability *= (1 - _PARAMS.p_slip) if mark == "C" else _PARAMS.p_slip
                        if transitions[index]:
                            feasible = False  # 숙달은 흡수 상태(망각 0) — 1→0 경로 없음
                            break
                    else:
                        probability *= _PARAMS.p_guess if mark == "C" else 1 - _PARAMS.p_guess
                        step = _PARAMS.p_transit if transitions[index] else 1 - _PARAMS.p_transit
                        probability *= step
                        state = 1 if transitions[index] else 0
                    after.append(state)
                if not feasible or probability == 0.0:
                    continue
                if fired is None:
                    rates["other"] += probability
                    continue
                band, index = fired
                if band is ReasonType.NEXT_CONCEPT:
                    rates["true_advance" if after[index] == 1 else "false_advance"] += probability
                elif after[index] == 1:
                    rates["master_demoted"] += probability
                else:
                    rates["other"] += probability
    return rates


def section_false_moves(horizon: int) -> None:
    """② 전진 하한만 바꿀 때(판정 §3-2) + 폐기된 대칭 하한 비교(§10 추적용)."""
    print(f"② 발화 순간 상태로 가른 관계 행위 확률(응답 {horizon}개 안 · 처음 발화만)")
    for label, start in (
        ("진짜 숙달자(L=1)", 1.0),
        ("비숙달자(L=0 출발)", 0.0),
        ("콜드스타트(사전 0.30)", _PARAMS.p_init),
    ):
        print(f"   {label}")
        for k_pre, k_adv in ((1, 1), (1, 3), (1, 4), (1, 5), (3, 3)):
            r = _classified_rates(start, k_pre, k_adv, horizon)
            tag = " (폐기안 · 대칭)" if k_pre > 1 else ""
            print(
                f"     선수 하한 {k_pre} · 전진 하한 {k_adv}: 거짓 전진 {r['false_advance']:.3f} · "
                f"정당 전진 {r['true_advance']:.3f} · 숙달자 하강 {r['master_demoted']:.3f}{tag}"
            )


def section_blocked_students(horizon: int) -> None:
    """③ 선수 결손으로 C를 배울 수 없는 학생(판정 §3-3) — 정답률 q 고정·학습 없음.

    선수 복귀가 돕기로 한 집단이다. 앵커(C) 하한이 이 집단의 하강을 늦추는지 잰다.
    """
    print(f"③ 결손 학생(정답률 고정·학습 없음 · 응답 {horizon}개 안)")
    for q in (0.2, 0.35):
        for k_pre, k_adv, label in ((1, 1, "없음"), (3, 3, "선수 3·전진 3"), (1, 3, "전진만 3")):
            advance = descent = wrongs_weighted = 0.0
            for observations in itertools.product("CW", repeat=horizon):
                probability = 1.0
                for mark in observations:
                    probability *= q if mark == "C" else 1.0 - q
                fired = _first_fire(observations, k_pre, k_adv)
                if fired is None:
                    continue
                band, index = fired
                if band is ReasonType.NEXT_CONCEPT:
                    advance += probability
                else:
                    descent += probability
                    wrongs_weighted += probability * observations[: index + 1].count("W")
            mean_wrongs = wrongs_weighted / descent if descent else float("nan")
            print(
                f"   q={q:.2f} 하한 {label}: 거짓 전진 {advance:.3f} · 하강 {descent:.3f} · "
                f"하강 전 평균 오답 {mean_wrongs:.2f}회"
            )


def _band_entry(correct_rate: float, floor: int, horizon: int) -> tuple[float, float]:
    """정답률 q(문항 무관·학습 없음)로 같은 개념을 풀 때 처음 발화하는 관계 구간의 확률."""
    prerequisite = advance = 0.0
    for observations in itertools.product("CW", repeat=horizon):
        probability = 1.0
        for mark in observations:
            probability *= correct_rate if mark == "C" else 1.0 - correct_rate
        fired = _first_fire(observations, floor, floor)
        if fired is None:
            continue
        if fired[0] is ReasonType.PREREQUISITE_GAP:
            prerequisite += probability
        else:
            advance += probability
    return prerequisite, advance


def section_suneung_bias(horizon: int) -> None:
    """④ 수능 가중(1+난이도)이 고르는 문항의 정답 확률과 선수 구간 진입률(희소 합성 풀 최악값)."""
    levels = [1.0 + 0.5 * i for i in range(9)]
    problems = [
        SimpleNamespace(exam_authority_weight=None, signature_patterns=[], difficulty_overall=d)
        for d in levels
    ]
    items = []
    for level in levels:
        b = resolve_item_difficulty_b(None, level)
        assert b is not None
        items.append(IrtItem(difficulty=b))
    weights = [suneung_item_weight(p) for p in problems]  # type: ignore[arg-type]
    print("④ 수능 가중 편향(권위·시그니처 없음 · 난이도 1.0~5.0 각 1문항 · Rasch 폴백 · 최악값)")
    for theta in (-1.0, 0.0, 1.0):
        default_index = select_weighted_item(theta, items)
        suneung_index = select_weighted_item(theta, items, weights=weights)
        assert default_index is not None and suneung_index is not None
        rates = []
        for name, index in (("정보량 최대", default_index), ("수능 가중", suneung_index)):
            q = probability_correct(theta, items[index])
            loose = _band_entry(q, 1, horizon)
            floored = _band_entry(q, 3, horizon)
            rates.append(
                f"{name} 난이도 {levels[index]:.1f}·정답 {q:.3f} → 선수 진입 "
                f"하한 없음 {loose[0]:.3f} · 하한 3 {floored[0]:.3f}"
            )
        print(f"   θ={theta:+.1f}: " + " | ".join(rates))
    # 대조 — 학습 밴드(purpose=learning · LEARNING_BAND_LOW~HIGH) 양끝 정답률. 학생 앱은 이
    # 인자를 보내지 않는다(2026-09-29 `problems_api.dart`) — 앱 기본 출제는 위 '정보량 최대'다.
    for q in (0.70, 0.85):
        loose = _band_entry(q, 1, horizon)
        floored = _band_entry(q, 3, horizon)
        print(
            f"   대조 학습 밴드 정답 {q:.2f} → 선수 진입 하한 없음 {loose[0]:.3f} · "
            f"하한 3 {floored[0]:.3f} (전진 {loose[1]:.3f} · {floored[1]:.3f})"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--horizon", type=int, default=8, help="② ③의 개념당 응답 수 상한(기본 8)")
    parser.add_argument(
        "--bias-horizon", type=int, default=6, help="④ 선수 진입률의 응답 수 상한(기본 6)"
    )
    args = parser.parse_args()
    section_measurements()
    section_false_moves(args.horizon)
    section_blocked_students(args.horizon)
    section_suneung_bias(args.bias_horizon)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
