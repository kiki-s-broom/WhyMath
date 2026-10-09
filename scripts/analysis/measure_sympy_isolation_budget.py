"""SymPy 격리 시간 상한의 근거 측정 — 정상 문항의 `verify_final_answer` 소요 분포 (OPS-96 ⑤).

상한(`sympy_isolation_timeout_s`)은 감으로 정하지 않는다. 학생이 *정답을 제출했을 때* 서버가 치르는
검증 비용을 전 코퍼스(`data/corpus/problem_bank_*`)에서 실측하고, 후보 상한마다 "정상 문항이
판정 불가로 떨어지는 비율"을 낸다. 상한이 너무 낮으면 이 비율이 0이 아니게 된다.

측정 대상은 문항 1건당 `MathFinalAnswerVerifier.verify_final_answer(정답, 문항)` 1회다 — 격리 풀을
거치지 않고 인라인으로 잰다(풀의 pickle·IPC 오버헤드는 밀리초 미만이라 분포를 바꾸지 않는다).
각 문항은 서로 다른 입력이라 SymPy 캐시에 거의 적중하지 않지만, 같은 프로세스 안에서 반복되는
하위 계산의 캐시는 남는다 — 그래서 **하한 쪽 편향**이 있을 수 있고, 이 도구는 상한 판정에 쓰는
"정상 입력의 꼬리"를 과소평가하지 않도록 최댓값·상위 10건을 함께 낸다.

사용: `python scripts/analysis/measure_sympy_isolation_budget.py [--json 경로]`
종료 코드: 0 = 측정 완료, 1 = 측정 대상 0건(공허 통과 금지).
"""

from __future__ import annotations

import argparse
import json
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SymPy 격리 상한 근거 측정(정상 문항 분포).")
    parser.add_argument("--json", default=None, help="결과 JSON 저장 경로(선택).")
    args = parser.parse_args(argv)
    result = measure()
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.json:
        Path(args.json).write_text(text + "\n", encoding="utf-8")
    return 0 if result["problems_measured"] else 1


if __name__ == "__main__":
    sys.exit(main())
