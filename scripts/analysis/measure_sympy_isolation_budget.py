"""SymPy 격리 시간 상한의 근거 측정 — 정상 문항의 `verify_final_answer` 소요 분포 (OPS-96 ⑤).

상한(`sympy_isolation_timeout_s`)은 감으로 정하지 않는다. 학생이 *정답을 제출했을 때* 서버가 치르는
검증 비용을 전 코퍼스(`data/corpus/problem_bank_*`)에서 실측하고, 후보 상한마다 "정상 문항이
판정 불가로 떨어지는 비율"을 낸다. 상한이 너무 낮으면 이 비율이 0이 아니게 된다.

측정 대상은 문항 1건당 `MathFinalAnswerVerifier.verify_final_answer(정답, 문항)` 1회다 — 격리 풀을
거치지 않고 인라인으로 잰다(풀의 pickle·IPC 오버헤드는 밀리초 미만이라 분포를 바꾸지 않는다).
각 문항은 서로 다른 입력이라 SymPy 캐시에 거의 적중하지 않지만, 같은 프로세스 안에서 반복되는
하위 계산의 캐시는 남는다 — 그래서 **하한 쪽 편향**이 있을 수 있고, 이 도구는 상한 판정에 쓰는
"정상 입력의 꼬리"를 과소평가하지 않도록 최댓값·상위 10건을 함께 낸다.

**단계 입력 모드(`--mode steps`, OPS-126 ②)** — 위는 *최종답 경로*(`verify-answer`·코치 턴)만
덮는다.
학생 풀이 단계(`verify-step`·`verify-solution`) 입력의 정상 분포는 코퍼스에 없다. 그래서 이 모드는
**교육과정 형태의 합성 단계 전이**(전개·인수분해·방정식 변형·유리식·지수·삼각·오류 변형)를
시드 고정으로 생성해 `verify_step` 소요를 잰다. **합성 대리 분포이지 실제 학생 입력이 아니다** —
실 분포 판정은
파일럿 `/health/ready`의 `sympy_isolation.undecidable_ratio`(OPS-126 ①)가 쌓인 뒤의 몫이다. 별도로
`safe_parse` 구조 예산을 통과하는 *가장 느린* 부류(고차 방정식 단계)의 차수×계수 소요표를 내서,
상한이 어느 차수·계수부터 정상 입력을 판정 불가로 접는지(무릎)를 보인다.

**오답·무관 쌍 모드(`--mode slips`, OPS-126 ②의 두 번째 프록시 — wonderful-allen 회수분)** —
`steps`가 "올바른 단계가 상한에 얼마나 여유 있나"를 본다면, 이 모드는 같은 합성 입력에서
**시간 상한과 무관하게 `unverifiable`이 되는 입력**을 가른다: ①전개식↔인수분해식(올바른 단계)
②전개식의 상수항을 1 틀린 단계(전형적 오답) ③서로 무관한 방정식 쌍(느린 부류). 결과는 시간
상한으로 접혔을 입력(`over_cap`)과 구조 예산·보수적 판정으로 즉시 `unverifiable`이 된
입력(`fast_unverifiable`)을 따로 센다 — 둘은 원인이 다르고, 뒤쪽은 `/health/ready`의
`undecidable_ratio`에 **잡히지 않는다**(풀 접힘이 아니라 검증기의 판정).

사용: `python scripts/analysis/measure_sympy_isolation_budget.py`
`[--mode final|steps|slips] [--json 경로]`
종료 코드: 0 = 측정 완료, 1 = 측정 대상 0건(공허 통과 금지).
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "src" / "backend"))

from whymath_backend.l4.subject_adapter_math import MathFinalAnswerVerifier  # noqa: E402

_CANDIDATE_CAPS_S = (0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0)


def _percentile(sorted_values: list[float], q: float) -> float:
    index = min(len(sorted_values) - 1, max(0, round(q * (len(sorted_values) - 1))))
    return sorted_values[index]


def measure() -> dict[str, object]:
    verifier = MathFinalAnswerVerifier()
    durations: list[float] = []
    slowest: list[tuple[float, str, str]] = []
    states: dict[str, int] = {}
    corpus_count = 0
    for path in sorted((_ROOT / "data" / "corpus").glob("problem_bank_*/problems.jsonl")):
        corpus_count += 1
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("answer") in (None, ""):
                continue
            problem = SimpleNamespace(**record)
            started = time.perf_counter()
            outcome = verifier.verify_final_answer(str(record["answer"]), problem)
            elapsed = time.perf_counter() - started
            durations.append(elapsed)
            state = str(getattr(outcome.state, "value", outcome.state))
            states[state] = states.get(state, 0) + 1
            slowest.append((elapsed, path.parent.name, str(record.get("slug", ""))))
    slowest.sort(reverse=True)
    ordered = sorted(durations)
    return {
        "corpora": corpus_count,
        "problems_measured": len(ordered),
        "states": states,
        "seconds": {
            "p50": _percentile(ordered, 0.50) if ordered else None,
            "p90": _percentile(ordered, 0.90) if ordered else None,
            "p99": _percentile(ordered, 0.99) if ordered else None,
            "p999": _percentile(ordered, 0.999) if ordered else None,
            "max": ordered[-1] if ordered else None,
            "mean": statistics.fmean(ordered) if ordered else None,
        },
        "fall_to_unverifiable_if_cap": {
            f"{cap:g}s": {
                "count": sum(1 for d in ordered if d > cap),
                "ratio": (sum(1 for d in ordered if d > cap) / len(ordered)) if ordered else None,
            }
            for cap in _CANDIDATE_CAPS_S
        },
        "slowest_10": [
            {"seconds": round(sec, 4), "corpus": corpus, "slug": slug}
            for sec, corpus, slug in slowest[:10]
        ],
    }


def _poly(expr: str) -> str:
    """SymPy 출력 문자열을 canonical 표기(`^`)로 — 생성기 쪽 변환이며 측정 대상이 아니다."""
    return expr.replace("**", "^")


def _step_cases() -> list[tuple[str, str, str]]:
    """교육과정 형태의 합성 단계 전이 `(범주, before, after)` — 시드 고정이라 재현된다."""
    import sympy as sp

    rng = random.Random(20261012)
    x = sp.Symbol("x")
    cases: list[tuple[str, str, str]] = []

    # 전개: (ax+b)^n, n=2..5 — 올바른 전개와 흔한 오류(분배 누락) 둘 다
    for _ in range(60):
        a, b, n = (
            rng.randint(1, 5),
            rng.choice([-6, -4, -3, -2, -1, 1, 2, 3, 5, 7]),
            rng.randint(2, 5),
        )
        before = f"({a}*x+{b})^{n}".replace("+-", "-")
        cases.append(("전개_올바름", before, _poly(sp.sstr(sp.expand((a * x + b) ** n)))))
        cases.append(("전개_오류", before, _poly(f"{a}**{n}*x^{n}+{b}**{n}".replace("**", "^"))))

    # 인수분해 — 이차·삼차
    for _ in range(40):
        p, q, r = (rng.randint(-6, 6) for _ in range(3))
        cases.append(
            (
                "인수분해_이차",
                _poly(sp.sstr(sp.expand((x + p) * (x + q)))),
                f"(x+{p})*(x+{q})".replace("+-", "-"),
            )
        )
        cases.append(
            (
                "인수분해_삼차",
                _poly(sp.sstr(sp.expand((x + p) * (x + q) * (x + r)))),
                f"(x+{p})*(x+{q})*(x+{r})".replace("+-", "-"),
            )
        )

    # 일차·이차 방정식 변형(해집합 보존 경로)
    for _ in range(40):
        a, b, c = rng.randint(2, 9), rng.randint(-9, 9), rng.randint(-20, 20)
        cases.append(("일차방정식", f"{a}*x+{b}={c}".replace("+-", "-"), f"{a}*x={c - b}"))
        p, q = rng.randint(-6, 6), rng.randint(-6, 6)
        expanded = _poly(sp.sstr(sp.expand((x - p) * (x - q))))
        factored = f"(x-{p})*(x-{q})".replace("--", "+").replace("-0)", ")")
        cases.append(("이차방정식_인수", f"{expanded}=0", f"{factored}=0"))
        cases.append(("이차방정식_근", f"{factored}=0", f"x={p}, x={q}"))

    # 유리식 약분 / 지수 / 삼각 항등
    for a in range(1, 9):
        cases.append(("유리식", f"(x^2-{a * a})/(x-{a})", f"x+{a}"))
    for k in range(1, 7):
        cases.append(("지수", f"2^(x+{k})", f"{2 ** k}*2^x"))
        cases.append(("삼각", f"sin({k}*x)^2+cos({k}*x)^2", "1"))
    for before, after in (
        ("sin(2*x)", "2*sin(x)*cos(x)"),
        ("cos(2*x)", "1-2*sin(x)^2"),
        ("cos(2*x)", "2*cos(x)^2-1"),
        ("tan(x)*cos(x)", "sin(x)"),
        ("(sin(x)+cos(x))^2", "1+2*sin(x)*cos(x)"),
    ):
        cases.append(("삼각", before, after))

    # 고차 전개 — 교육과정 상단(수학Ⅱ·미적분 다항식 6~8차)
    for n in range(6, 9):
        for b in (1, 2, 3):
            cases.append(("고차전개", f"(x+{b})^{n}", _poly(sp.sstr(sp.expand((x + b) ** n)))))
    return cases


# 구조 예산(`safe_parse`)을 통과하는 가장 느린 부류 — 차수 d 방정식 `x^d+k*x+1=0 → x^(d-1)+k*x+2=0`.
_STRESS_DEGREES = (6, 8, 10, 12, 14, 16, 18, 20)
_STRESS_COEFFS = (1, 7919)


def measure_steps() -> dict[str, object]:
    """합성 단계 전이 + 고차 방정식 스트레스의 `verify_step` 소요 분포 (OPS-126 ②)."""
    from whymath_backend.l3.verify_step import verify_step

    by_category: dict[str, list[float]] = {}
    states: dict[str, int] = {}
    all_durations: list[float] = []
    slowest: list[tuple[float, str, str]] = []
    for category, before, after in _step_cases():
        started = time.perf_counter()
        result = verify_step(before, after)
        elapsed = time.perf_counter() - started
        by_category.setdefault(category, []).append(elapsed)
        all_durations.append(elapsed)
        state = str(getattr(result.state, "value", result.state))
        states[state] = states.get(state, 0) + 1
        slowest.append((elapsed, category, f"{before} -> {after}"))
    slowest.sort(reverse=True)
    ordered = sorted(all_durations)

    stress: list[dict[str, object]] = []
    for degree in _STRESS_DEGREES:
        for coeff in _STRESS_COEFFS:
            before = f"x^{degree}+{coeff}*x+1=0"
            after = f"x^{degree - 1}+{coeff}*x+2=0"
            started = time.perf_counter()
            result = verify_step(before, after)
            elapsed = time.perf_counter() - started
            stress.append(
                {
                    "degree": degree,
                    "coeff": coeff,
                    "seconds": round(elapsed, 4),
                    "state": str(getattr(result.state, "value", result.state)),
                    "folded_at_cap_5s": elapsed > 5.0,
                }
            )

    return {
        "kind": "합성 대리 분포(실제 학생 입력 아님) — 시드 20261012",
        "transitions_measured": len(ordered),
        "states": states,
        "seconds": {
            "p50": _percentile(ordered, 0.50) if ordered else None,
            "p99": _percentile(ordered, 0.99) if ordered else None,
            "max": ordered[-1] if ordered else None,
        },
        "by_category": {
            category: {
                "n": len(values),
                "p50": _percentile(sorted(values), 0.50),
                "max": max(values),
            }
            for category, values in sorted(by_category.items())
        },
        "fall_to_unverifiable_if_cap": {
            f"{cap:g}s": sum(1 for d in ordered if d > cap) for cap in _CANDIDATE_CAPS_S
        },
        "slowest_10": [
            {"seconds": round(sec, 4), "category": cat, "step": step}
            for sec, cat, step in slowest[:10]
        ],
        "high_degree_equation_stress": stress,
    }


def _fmt(expr: object) -> str:
    """SymPy 식 → `verify_step` 입력 문자열(`**` → `^`)."""
    return str(expr).replace("**", "^")


def _time_step(before: str, after: str) -> tuple[float, str]:
    from whymath_backend.l3.verify_step import verify_step

    started = time.perf_counter()
    result = verify_step(before, after)
    return time.perf_counter() - started, str(getattr(result.state, "value", result.state))


def measure_slips() -> dict[str, object]:
    """올바른 단계·전형적 오답·무관 쌍을 합성해 소요와 판정을 잰다 — 파일럿 분포가 아닌 프록시."""
    import sympy as sp

    x = sp.Symbol("x")
    rng = random.Random(7)  # 고정 시드 — 같은 입력을 다시 잴 수 있다
    classes: dict[str, list[tuple[float, str]]] = {}

    for degree in range(2, 9):
        for _ in range(10):
            roots = [rng.randint(-9, 9) for _ in range(degree)]
            factored = sp.prod([x - r for r in roots])
            poly = sp.expand(factored)
            classes.setdefault(f"equiv_expand_factor/deg{degree}", []).append(
                _time_step(f"{_fmt(poly)}=0", f"{_fmt(factored)}=0")
            )
            classes.setdefault(f"wrong_constant_slip/deg{degree}", []).append(
                _time_step(f"{_fmt(poly)}=0", f"{_fmt(poly + 1)}=0")
            )
    for label, low, high in (
        ("small1-9", 1, 9),
        ("mid10-99", 10, 99),
        ("large1000-9999", 1000, 9999),
    ):
        for degree in (4, 6, 8, 10, 12, 14):
            for _ in range(3):
                a = rng.randint(low, high)
                classes.setdefault(f"unrelated_pair/{label}/deg{degree}", []).append(
                    _time_step(f"x^{degree}+{a}*x+1=0", f"x^{degree - 1}+{a}*x+2=0")
                )

    every = [pair for rows in classes.values() for pair in rows]
    durations = sorted(sec for sec, _ in every)
    return {
        "kind": "합성 대리 분포(실제 학생 입력 아님) — 시드 7",
        "samples": len(every),
        "seconds": {
            "p50": _percentile(durations, 0.50) if durations else None,
            "p99": _percentile(durations, 0.99) if durations else None,
            "max": durations[-1] if durations else None,
        },
        "over_cap": {
            f"{cap:g}s": sum(1 for d in durations if d > cap) for cap in _CANDIDATE_CAPS_S
        },
        "by_class": {
            name: {
                "n": len(rows),
                "max_seconds": round(max(sec for sec, _ in rows), 4),
                "states": {
                    state: sum(1 for _, s in rows if s == state)
                    for state in sorted({s for _, s in rows})
                },
                # 시간과 무관하게 즉시 판정 불가가 된 입력(구조 예산·보수적 판정) — 원인이 다르다
                "fast_unverifiable": sum(1 for sec, s in rows if s == "unverifiable" and sec < 0.5),
            }
            for name, rows in classes.items()
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SymPy 격리 상한 근거 측정(정상 문항 분포).")
    parser.add_argument(
        "--mode",
        choices=("final", "steps", "slips"),
        default="final",
        help=(
            "final=정상 문항 최종답 경로(기본) · steps=합성 단계 전이+고차 방정식 스트레스 · "
            "slips=올바른 단계/전형적 오답/무관 쌍의 시간 접힘 vs 즉시 unverifiable 구분."
        ),
    )
    parser.add_argument("--json", default=None, help="결과 JSON 저장 경로(선택).")
    args = parser.parse_args(argv)
    if args.mode == "steps":
        result = measure_steps()
        measured = result["transitions_measured"]
    elif args.mode == "slips":
        result = measure_slips()
        measured = result["samples"]
    else:
        result = measure()
        measured = result["problems_measured"]
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.json:
        Path(args.json).write_text(text + "\n", encoding="utf-8")
    return 0 if measured else 1


if __name__ == "__main__":
    sys.exit(main())
