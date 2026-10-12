"""SymPy 격리 시간 상한의 근거 측정 — 정상 문항의 `verify_final_answer` 소요 분포 (OPS-96 ⑤).

상한(`sympy_isolation_timeout_s`)은 감으로 정하지 않는다. 학생이 *정답을 제출했을 때* 서버가 치르는
검증 비용을 전 코퍼스(`data/corpus/problem_bank_*`)에서 실측하고, 후보 상한마다 "정상 문항이
판정 불가로 떨어지는 비율"을 낸다. 상한이 너무 낮으면 이 비율이 0이 아니게 된다.

측정 대상은 문항 1건당 `MathFinalAnswerVerifier.verify_final_answer(정답, 문항)` 1회다 — 격리 풀을
거치지 않고 인라인으로 잰다(풀의 pickle·IPC 오버헤드는 밀리초 미만이라 분포를 바꾸지 않는다).
각 문항은 서로 다른 입력이라 SymPy 캐시에 거의 적중하지 않지만, 같은 프로세스 안에서 반복되는
하위 계산의 캐시는 남는다 — 그래서 **하한 쪽 편향**이 있을 수 있고, 이 도구는 상한 판정에 쓰는
"정상 입력의 꼬리"를 과소평가하지 않도록 최댓값·상위 10건을 함께 낸다.

사용: `python scripts/analysis/measure_sympy_isolation_budget.py [--steps] [--json 경로]`
종료 코드: 0 = 측정 완료, 1 = 측정 대상 0건(공허 통과 금지).

**`--steps` 모드 (OPS-126 ②의 프록시)** — 위 측정은 *최종답* 경로다. 학생 풀이 *단계*
(`verify-step`·`verify-solution`) 입력의 정상 분포는 코퍼스에 없다(`answer_explanation`은 한 줄
산문이라 단계 전이가 없다). 이 모드는 교과 수준의 전형적 단계를 **합성**해 차수·계수 크기별
소요를 잰다 —
①전개식↔인수분해식(올바른 단계) ②전개식의 상수항을 1 틀린 단계(전형적 오답) ③서로 무관한 방정식 쌍
(느린 입력 부류 — `x^d+a*x+1=0 → x^(d-1)+a*x+2=0`). **이것은 파일럿 분포가 아니다** — 상한이 정상
입력을 얼마나 여유 있게 지나가는지의 *하한 근거*일 뿐이고, 상한을 확정하는 근거는 파일럿 트래픽에서
`GET /health/ready`의 `sympy_isolation.folded_ratio`를 읽은 값이다. 결과는 시간 상한으로 접혔을 입력
(`over_cap`)과 시간과 무관하게 구조 예산·보수적 판정으로 즉시 `unverifiable`이 된
입력(`fast_unverifiable`)을 구분해 센다 — 둘은 원인이 다르다.
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

from whymath_backend.l3.verify_step import verify_step  # noqa: E402
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


def _fmt(expr: object) -> str:
    """SymPy 식 → `verify_step` 입력 문자열(`**` → `^`)."""
    return str(expr).replace("**", "^")


def _time_step(before: str, after: str) -> tuple[float, str]:
    started = time.perf_counter()
    result = verify_step(before, after, None)
    return time.perf_counter() - started, str(getattr(result.state, "value", result.state))


def measure_steps() -> dict[str, object]:
    """교과 수준 단계를 합성해 `verify_step` 소요를 잰다 — 파일럿 분포가 아닌 프록시."""
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
        "scope": "synthetic_proxy_NOT_pilot_distribution",
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
    parser.add_argument("--json", default=None, help="결과 JSON 저장 경로(선택).")
    parser.add_argument(
        "--steps",
        action="store_true",
        help="최종답 대신 풀이 *단계* 합성 프록시를 잰다(OPS-126 ②·파일럿 분포 아님).",
    )
    args = parser.parse_args(argv)
    if args.steps:
        steps_result = measure_steps()
        steps_text = json.dumps(steps_result, ensure_ascii=False, indent=2)
        print(steps_text)
        if args.json:
            Path(args.json).write_text(steps_text + "\n", encoding="utf-8")
        return 0 if steps_result["samples"] else 1
    result = measure()
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.json:
        Path(args.json).write_text(text + "\n", encoding="utf-8")
    return 0 if result["problems_measured"] else 1


if __name__ == "__main__":
    sys.exit(main())
