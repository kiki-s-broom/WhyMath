"""P3-94 ⑨ — AI 채점 패널 분석: 채점자 간 κ · 불일치 · 판정기-패널 일치율 · 좌석별 품질.

사용: python3 scripts/analysis/p3_94_ai_panel_analysis.py data/runs/p3_94
      [--adjudication <파일>] [--json <출력>]
판정 대응(규칙 판정기 축 → 패널 칸):
  answer_leak→answer_leak(1=실패) · math_correctness→math_error(1=실패)
  hint_appropriateness→hint_level_fit(1=통과)
  explanation_consistency→consistency(1=통과) · student_level_fit→level_fit(1=통과)
  hallucination→fabrication(1=실패)
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

AXES = ("answer_leak", "math_error", "hint_level_fit", "consistency", "level_fit", "fabrication")
FAIL_IS_ONE = {"answer_leak", "math_error", "fabrication"}
JUDGE_AXIS = {
    "answer_leak": "answer_leak",
    "math_error": "math_correctness",
    "hint_level_fit": "hint_appropriateness",
    "consistency": "explanation_consistency",
    "level_fit": "student_level_fit",
    "fabrication": "hallucination",
}


def kappa(a: list[int], b: list[int]) -> float | None:
    """Cohen κ(이진) — 기대 일치가 1이면(둘 다 한 값만) 정의 불가 → None."""
    n = len(a)
    if n == 0:
        return None
    po = sum(x == y for x, y in zip(a, b, strict=True)) / n
    pa1, pb1 = sum(a) / n, sum(b) / n
    pe = pa1 * pb1 + (1 - pa1) * (1 - pb1)
    if pe >= 1.0:
        return None
    return (po - pe) / (1 - pe)


def passed(axis: str, value: int) -> bool:
    return value == 0 if axis in FAIL_IS_ONE else value == 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("--adjudication", type=Path, default=None)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()
    root: Path = args.root
    ra = {
        i["번호"]: i
        for i in json.loads((root / "ai_scoring_reviewer_a.json").read_text(encoding="utf-8"))[
            "items"
        ]
    }
    rb = {
        i["번호"]: i
        for i in json.loads((root / "ai_scoring_reviewer_b.json").read_text(encoding="utf-8"))[
            "items"
        ]
    }
    assert sorted(ra) == sorted(rb) == list(range(1, 41)), "채점 40건 불완전"
    key = {
        i["번호"]: i
        for i in json.loads((root / "human_scoring_key_40.json").read_text(encoding="utf-8"))[
            "items"
        ]
    }
    adj: dict[int, dict] = {}
    if args.adjudication is not None:
        adj = {
            i["번호"]: i for i in json.loads(args.adjudication.read_text(encoding="utf-8"))["items"]
        }

    out: dict = {"axes": {}, "disagreements": [], "seat_quality": {}, "judge_vs_panel": {}}
    panel: dict[int, dict] = {n: {} for n in ra}
    for axis in AXES:
        nums = [n for n in sorted(ra) if ra[n][axis] != "-" and rb[n][axis] != "-"]
        a = [int(ra[n][axis]) for n in nums]
        b = [int(rb[n][axis]) for n in nums]
        agree = sum(x == y for x, y in zip(a, b, strict=True))
        out["axes"][axis] = {
            "n": len(nums),
            "agree": agree,
            "kappa": kappa(a, b),
            "a_ones": sum(a),
            "b_ones": sum(b),
        }
        for n, x, y in zip(nums, a, b, strict=True):
            if x == y:
                panel[n][axis] = x
            else:
                out["disagreements"].append(
                    {
                        "번호": n,
                        "axis": axis,
                        "a": x,
                        "b": y,
                        "a_reason": ra[n].get("reason", ""),
                        "b_reason": rb[n].get("reason", ""),
                    }
                )
                if n in adj and axis in adj[n]:
                    panel[n][axis] = int(adj[n][axis])
    # 좌석별 품질(두 채점자 평균) + 패널 축별 통과
    for seat in ("local-mid", "cloud-mid"):
        nums = [n for n in sorted(ra) if key[n]["seat"] == seat]
        q = [(ra[n]["quality"] + rb[n]["quality"]) / 2 for n in nums]
        axes_pass = {}
        for axis in AXES:
            decided = [n for n in nums if axis in panel[n]]
            axes_pass[axis] = {
                "decided": len(decided),
                "pass": sum(passed(axis, panel[n][axis]) for n in decided),
            }
        out["seat_quality"][seat] = {
            "n": len(nums),
            "quality_mean": round(sum(q) / len(q), 2),
            "quality_dist": dict(sorted(Counter(round(x) for x in q).items())),
            "panel_axes": axes_pass,
        }
    # 판정기 대 패널(사례별) — 판정기는 실패 사례 목록으로 재구성
    judge_fail: dict[tuple[str, str], set[str]] = {}
    judge_applicable: dict[tuple[str, str], int] = {}
    for seat in ("local-mid", "cloud-mid"):
        rep = json.loads(
            (root / f"utter-{seat}" / "live.jsonl.drafts.report.json").read_text(encoding="utf-8")
        )
        for a in rep["axes"]:
            judge_fail[(seat, a["axis"])] = {f["case_id"] for f in a["failures"]}
            judge_applicable[(seat, a["axis"])] = a["n_applicable"]
    for axis in AXES:
        jx = JUDGE_AXIS[axis]
        both = agree = 0
        mism: list[dict] = []
        for n in sorted(ra):
            if axis not in panel[n]:
                continue
            seat, cid = key[n]["seat"], key[n]["case_id"]
            if judge_applicable.get((seat, jx), 0) == 0:
                continue
            j_pass = cid not in judge_fail[(seat, jx)]
            p_pass = passed(axis, panel[n][axis])
            both += 1
            if j_pass == p_pass:
                agree += 1
            else:
                mism.append(
                    {
                        "번호": n,
                        "seat": seat,
                        "case_id": cid,
                        "judge_pass": j_pass,
                        "panel_pass": p_pass,
                    }
                )
        out["judge_vs_panel"][axis] = {
            "judge_axis": jx,
            "n": both,
            "agree": agree,
            "mismatch": mism,
        }
    text = json.dumps(out, ensure_ascii=False, indent=2)
    if args.json:
        args.json.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
