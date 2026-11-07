"""P3-94 ⑨ — AI 채점 패널 분석: 채점자 간 κ · 불일치 · 판정기-패널 일치율 · 좌석별 품질.

사용(앞 회차 40건 — 기본값 그대로):
  python3 scripts/analysis/p3_94_ai_panel_analysis.py data/runs/p3_94
      [--adjudication <파일>] [--json <출력>]
사용(본 수집 477건 — 채점 파일이 묶음별로 나뉜 경우):
  python3 scripts/analysis/p3_94_ai_panel_analysis.py data/runs/p3_94
      --reviewer-a data/runs/p3_94/full_panel/reviewer_a_part*.json
      --reviewer-b data/runs/p3_94/full_panel/reviewer_b_part*.json
      --key data/runs/p3_94/full_panel/key_full.json --run-prefix full
      --packet data/runs/p3_94/full_panel/packet_full.jsonl
      [--adjudication <파일>] [--json <출력>]

판정 대응(규칙 판정기 축 → 패널 칸):
  answer_leak→answer_leak(1=실패) · math_correctness→math_error(1=실패)
  hint_appropriateness→hint_level_fit(1=통과)
  explanation_consistency→consistency(1=통과) · student_level_fit→level_fit(1=통과)
  hallucination→fabrication(1=실패)

좌석별 패널 비율에는 Wilson 단측 95% 경계를 붙인다 — 실패 축은 실패율 상한, 통과 축은
통과율 하한(점추정으로 임계값을 정하지 않는다 · 단일 원천 `harness/wilson.py`).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src" / "backend"))
from whymath_backend.harness.wilson import (  # noqa: E402
    wilson_lower_bound,
    wilson_upper_bound,
)

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
SEATS = ("local-mid", "cloud-mid")


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


def _load_items(paths: list[Path]) -> dict[int, dict]:
    """채점 파일 여러 개를 번호로 합친다 — 같은 번호가 두 파일에 있으면 거부."""
    merged: dict[int, dict] = {}
    for p in paths:
        for item in json.loads(p.read_text(encoding="utf-8"))["items"]:
            n = int(item["번호"])
            if n in merged:
                raise SystemExit(f"번호 {n} 중복 — {p}")
            merged[n] = item
    return merged


def _rate_bound(axis: str, passes: int, decided: int) -> dict:
    """실패 축은 실패율 상한, 통과 축은 통과율 하한을 낸다(decided=0이면 측정 불가)."""
    if decided == 0:
        return {"rate": None, "bound": None, "bound_kind": None}
    if axis in FAIL_IS_ONE:
        fails = decided - passes
        return {
            "rate": round(fails / decided, 4),
            "bound": round(wilson_upper_bound(fails, decided), 4),
            "bound_kind": "fail_rate_upper",
        }
    return {
        "rate": round(passes / decided, 4),
        "bound": round(wilson_lower_bound(passes, decided), 4),
        "bound_kind": "pass_rate_lower",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("--reviewer-a", type=Path, nargs="+", default=None)
    ap.add_argument("--reviewer-b", type=Path, nargs="+", default=None)
    ap.add_argument("--key", type=Path, default=None)
    ap.add_argument("--run-prefix", default="utter")
    ap.add_argument("--packet", type=Path, default=None)
    ap.add_argument("--adjudication", type=Path, default=None)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()
    root: Path = args.root
    ra = _load_items(args.reviewer_a or [root / "ai_scoring_reviewer_a.json"])
    rb = _load_items(args.reviewer_b or [root / "ai_scoring_reviewer_b.json"])
    key_path = args.key or root / "human_scoring_key_40.json"
    key = {i["번호"]: i for i in json.loads(key_path.read_text(encoding="utf-8"))["items"]}
    # 완결성 — 두 채점자와 대응표의 번호 집합이 같아야 한다(빠진 칸은 침묵 통과가 아니라 중단)
    if not (sorted(ra) == sorted(rb) == sorted(key)):
        missing_a = sorted(set(key) - set(ra))[:10]
        missing_b = sorted(set(key) - set(rb))[:10]
        raise SystemExit(f"채점 불완전 — A 누락 {missing_a} · B 누락 {missing_b}")
    adj: dict[int, dict] = {}
    if args.adjudication is not None:
        # 같은 번호에 칸이 여럿이면 항목도 여럿이다 — 덮어쓰지 않고 칸별로 합친다
        for i in json.loads(args.adjudication.read_text(encoding="utf-8"))["items"]:
            adj.setdefault(int(i["번호"]), {}).update(i)
    packet: dict[int, dict] = {}
    if args.packet is not None:
        for line in args.packet.read_text(encoding="utf-8").splitlines():
            if line.strip():
                o = json.loads(line)
                packet[o["번호"]] = o

    out: dict = {
        "n_items": len(ra),
        "axes": {},
        "disagreements": [],
        "unresolved": [],
        "seat_quality": {},
        "judge_vs_panel": {},
    }
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
                continue
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
            else:
                out["unresolved"].append({"번호": n, "axis": axis})
    # 좌석별 품질(두 채점자 평균) + 패널 축별 통과 + Wilson 경계
    for seat in SEATS:
        nums = [n for n in sorted(ra) if key[n]["seat"] == seat]
        q = [(ra[n]["quality"] + rb[n]["quality"]) / 2 for n in nums]
        axes_pass = {}
        for axis in AXES:
            decided = [n for n in nums if axis in panel[n]]
            p = sum(passed(axis, panel[n][axis]) for n in decided)
            axes_pass[axis] = {"decided": len(decided), "pass": p, **_rate_bound(axis, p, len(decided))}
        seat_out: dict = {
            "n": len(nums),
            "quality_mean": round(sum(q) / len(q), 2) if q else None,
            "quality_dist": dict(sorted(Counter(round(x) for x in q).items())),
            "panel_axes": axes_pass,
        }
        if packet:
            # 상황·힌트 단계별 품질과 단계 적합 — 3단계 구조 결함을 수치로 본다
            by_slot: dict[str, list[int]] = defaultdict(list)
            for n in nums:
                o = packet[n]
                slot = f"hint-L{o['힌트_단계']}" if o["상황"].startswith("힌트") else "choice"
                by_slot[slot].append(n)
            slots = {}
            for slot, ns in sorted(by_slot.items()):
                qs = [(ra[n]["quality"] + rb[n]["quality"]) / 2 for n in ns]
                fit = [n for n in ns if "hint_level_fit" in panel[n]]
                slots[slot] = {
                    "n": len(ns),
                    "quality_mean": round(sum(qs) / len(qs), 2),
                    "hint_level_fit_pass": sum(panel[n]["hint_level_fit"] == 1 for n in fit),
                    "hint_level_fit_decided": len(fit),
                }
            seat_out["by_slot"] = slots
        out["seat_quality"][seat] = seat_out
    # 판정기 대 패널(사례별) — 판정기는 실패 사례 목록으로 재구성
    judge_fail: dict[tuple[str, str], set[str]] = {}
    judge_applicable: dict[tuple[str, str], int] = {}
    for seat in SEATS:
        rep_path = root / f"{args.run_prefix}-{seat}" / "live.jsonl.drafts.report.json"
        rep = json.loads(rep_path.read_text(encoding="utf-8"))
        for a in rep["axes"]:
            judge_fail[(seat, a["axis"])] = {f["case_id"] for f in a["failures"]}
            judge_applicable[(seat, a["axis"])] = a["n_applicable"]
    for axis in AXES:
        jx = JUDGE_AXIS[axis]
        both = agree = false_pass = false_fail = 0
        mism: list[dict] = []
        for n in sorted(ra):
            if axis not in panel[n]:
                continue
            seat, cid = key[n]["seat"], key[n]["case_id"]
            # 리포트는 사례별 적용 여부를 싣지 않는다 — 축 전체가 대상 0이면 비교에서 뺀다
            if judge_applicable.get((seat, jx), 0) == 0:
                continue
            j_pass = cid not in judge_fail[(seat, jx)]
            p_pass = passed(axis, panel[n][axis])
            both += 1
            if j_pass == p_pass:
                agree += 1
                continue
            if j_pass:
                false_pass += 1
            else:
                false_fail += 1
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
            "false_pass": false_pass,
            "false_fail": false_fail,
            "mismatch": mism,
        }
    text = json.dumps(out, ensure_ascii=False, indent=2)
    if args.json:
        args.json.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
