# diag_merge.py — 단계별 발견 기록 통합·검증·표본 추출 (단계 S09·S10)
# 1) 모든 S??_findings.jsonl의 형식을 검사한다 (필수 필드·허용 값·ID 중복)
# 2) 진단 규칙을 강제한다: 증거 등급 E0·E1인데 심각도 '차단'·'높음'이면 '중간'으로 내리고 기록
# 3) S09_verification.jsonl(교차 검증 판정)이 있으면 반영한다: 반박 → 제외, 수정 → 값 갱신
# 4) 심각도·범주·축·게이트·근본 원인별로 집계하고, 진단이 들여다보지 않은 폴더(범위 밖)를 찾는다
# 5) 사람 검토 시트를 만든다
# 사용: python diag_merge.py --results <결과폴더>             (통합)
#       python diag_merge.py --results <결과폴더> --sample    (S09 교차 검증 대상 추출)
from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path

from _diagcommon import md_table, setup_console, write_outputs

REQUIRED = [
    "id",
    "step",
    "title",
    "severity",
    "category",
    "axis",
    "criteria",
    "evidence_level",
    "evidence",
    "locations",
    "impact",
    "fix_hint",
    "plain",
]
ENUM = {
    "severity": ["차단", "높음", "중간", "낮음"],
    "evidence_level": ["E3", "E2", "E1", "E0"],
    "axis": ["흐름", "진실", "경계", "변경", "확신", "회복"],
    "category": [
        "코딩규칙",
        "헌법",
        "헌법안",
        "계획",
        "표준북권고",
        "결함",
        "보안",
        "데이터",
        "규칙충돌",
    ],
}
WEIGHT = {"차단": 8, "높음": 4, "중간": 2, "낮음": 1}


def load_findings(results: Path):
    items, errors, seen = [], [], {}
    for f in sorted(results.glob("S[0-9][0-9]_findings.jsonl")):
        for n, line in enumerate(f.read_text(encoding="utf-8-sig").splitlines(), 1):
            if not line.strip():
                continue
            try:
                x = json.loads(line)
            except json.JSONDecodeError as e:
                errors.append(f"{f.name}:{n} JSON 오류 — {e.msg}")
                continue
            miss = [k for k in REQUIRED if k not in x or x[k] in (None, "", [])]
            bad = [
                f"{k}={x.get(k)!r}" for k, allowed in ENUM.items() if k in x and x[k] not in allowed
            ]
            if miss or bad:  # 형식이 틀린 항목은 집계에서 빼고 오류로 알린다
                errors.append(
                    f"{f.name}:{n} {x.get('id', '?')} — 누락 {miss or '-'} / 허용 밖 값 {bad or '-'} → 집계 제외"
                )
                continue
            if x["id"] in seen:  # 같은 ID는 처음 것만 쓴다
                errors.append(
                    f"{f.name}:{n} ID 중복 {x['id']} (먼저 나온 {seen[x['id']]} 사용) → 집계 제외"
                )
                continue
            seen[x["id"]] = f.name
            x["_file"] = f.name
            items.append(x)
    return items, errors


def enforce(items: list, policy: list) -> None:
    """진단 규칙: 증거 등급 E0·E1(추정·문서 주장)로는 '차단'·'높음'을 매길 수 없다 → '중간'으로 내린다."""
    for x in items:
        if x["severity"] in ("차단", "높음") and x["evidence_level"] in ("E1", "E0"):
            policy.append(
                f"{x['id']}: {x['severity']}·{x['evidence_level']} → 중간으로 하향 (증거 보강 필요)"
            )
            x["severity"], x["_downgraded"] = "중간", True


def main() -> int:
    setup_console()
    ap = argparse.ArgumentParser(description="발견 기록 통합")
    ap.add_argument(
        "--results", required=True, type=Path, help="진단 결과 폴더 (S??_findings.jsonl이 있는 곳)"
    )
    ap.add_argument("--sample", action="store_true", help="S09 교차 검증 대상 목록만 만든다")
    ap.add_argument("--seed", type=int, default=260927, help="표본 추출 난수 씨앗 (재현용)")
    args = ap.parse_args()
    items, errors = load_findings(args.results)
    if not items:
        raise SystemExit("⛔ 발견 기록(S??_findings.jsonl)이 없습니다")

    policy: list[str] = []
    if args.sample:
        enforce(items, policy)
        strong = [x for x in items if x["severity"] in ("차단", "높음")]
        rest = sorted(
            (x for x in items if x["severity"] not in ("차단", "높음")), key=lambda x: x["id"]
        )
        k = math.ceil(len(rest) * 0.2)
        picked = strong + random.Random(args.seed).sample(rest, k) if rest else strong
        md = [
            "# S09 교차 검증 대상\n",
            f"차단·높음 전부 {len(strong)}건 + 나머지 {len(rest)}건 중 20% 무작위 {k}건 (씨앗 {args.seed})\n",
            md_table(
                ["ID", "심각도", "증거", "제목", "재현"],
                [
                    [x["id"], x["severity"], x["evidence_level"], x["title"], x.get("repro", "")]
                    for x in picked
                ],
            ),
        ]
        (args.results / "S09_검증대상.md").write_text("\n".join(md) + "\n", encoding="utf-8")
        print(f"검증 대상 {len(picked)}건 → {args.results / 'S09_검증대상.md'}")
        return 0

    verif, rejected = {}, []
    vfile = args.results / "S09_verification.jsonl"
    if vfile.exists():
        for line in vfile.read_text(encoding="utf-8-sig").splitlines():
            if line.strip():
                v = json.loads(line)
                verif[v["id"]] = v
    final = []
    for x in items:
        v = verif.get(x["id"])
        if v and v.get("verdict") == "반박":
            rejected.append({"id": x["id"], "title": x["title"], "note": v.get("note", "")})
            continue
        if v and v.get("verdict") == "수정":
            for k in ("severity", "evidence_level"):
                if v.get(f"new_{k}"):
                    x[k] = v[f"new_{k}"]
        x["_verified"] = v.get("verdict") if v else "미검증"
        final.append(x)
    enforce(final, policy)  # 교차 검증으로 바뀐 값에도 같은 규칙 적용

    sev = Counter(x["severity"] for x in final)
    cat = Counter(x["category"] for x in final)
    axis = Counter(x["axis"] for x in final)
    ev = Counter(x["evidence_level"] for x in final)
    gates = defaultdict(Counter)
    for x in final:
        for g in x.get("gates") or []:
            gates[g][x["severity"]] += 1
    roots = defaultdict(lambda: {"score": 0, "ids": [], "sev": Counter()})
    for x in final:
        r = roots[x.get("root_cause") or "(근본 원인 미기재)"]
        r["score"] += WEIGHT[x["severity"]]
        r["ids"].append(x["id"])
        r["sev"][x["severity"]] += 1
    root_rows = sorted(roots.items(), key=lambda kv: -kv[1]["score"])

    # 범위 밖 폴더: 인벤토리의 최상위 폴더 중 어떤 단계도 들여다보지 않았고 발견도 없는 곳
    covered = set()
    for m in args.results.glob("S[0-9][0-9]_meta.json"):
        try:
            covered.update(
                p.replace("\\", "/").strip("./")
                for p in json.loads(m.read_text(encoding="utf-8-sig")).get("examined_paths", [])
            )
        except (OSError, json.JSONDecodeError):
            errors.append(f"{m.name} 읽기 실패")
    for x in final:
        covered.update(loc.replace("\\", "/").split(":")[0] for loc in x["locations"])
    uncovered = []
    inv = args.results / "raw" / "diag_integrity.json"
    if inv.exists():
        for d in json.loads(inv.read_text(encoding="utf-8")).get("dirs", []):
            name = d["dir"]
            loc = sum(d.get("loc", {}).values())
            if name == "(최상위)":  # 최상위 파일은 '/' 없는 경로가 하나라도 보였으면 본 것으로
                seen_top = any(c and "/" not in c for c in covered)
            else:
                seen_top = any(
                    c == name or c.startswith(name + "/") or name.startswith(c.rstrip("/") + "/")
                    for c in covered
                )
            if loc and not seen_top:
                uncovered.append({"dir": name, "loc": loc})

    data = {
        "total": len(final),
        "rejected": rejected,
        "severity": dict(sev),
        "category": dict(cat),
        "axis": dict(axis),
        "evidence": dict(ev),
        "gates": {g: dict(c) for g, c in gates.items()},
        "root_causes": [
            {"root": k, "score": v["score"], "severity": dict(v["sev"]), "ids": v["ids"]}
            for k, v in root_rows
        ],
        "uncovered_dirs": uncovered,
        "format_errors": errors,
        "policy_downgrades": policy,
        "findings": [{k: v for k, v in x.items()} for x in final],
    }
    order = {"차단": 0, "높음": 1, "중간": 2, "낮음": 3}
    md = [
        "# 통합 집계\n",
        f"발견 {len(final)}건 (교차 검증에서 반박되어 제외 {len(rejected)}건)\n",
        md_table(["심각도", "건수"], [[s, sev.get(s, 0)] for s in ENUM["severity"]]),
        "\n## 증거 등급\n",
        md_table(["등급", "건수"], [[e, ev.get(e, 0)] for e in ENUM["evidence_level"]]),
        "\n## 근본 원인별 (가중 점수: 차단 8·높음 4·중간 2·낮음 1)\n",
        md_table(
            ["근본 원인", "점수", "심각도 분포", "발견 ID"],
            [[k, v["score"], dict(v["sev"]), ", ".join(v["ids"][:8])] for k, v in root_rows],
        ),
        "\n## 게이트별 영향\n",
        md_table(
            ["게이트", "차단", "높음", "중간", "낮음"],
            [
                [g, c.get("차단", 0), c.get("높음", 0), c.get("중간", 0), c.get("낮음", 0)]
                for g, c in sorted(gates.items())
            ],
        ),
        "\n## 범주·축\n",
        md_table(["범주", "건수"], cat.most_common()),
        "\n",
        md_table(["축", "건수"], axis.most_common()),
        "\n## 진단이 보지 않은 폴더 (범위 밖)\n",
        md_table(["폴더", "코드 줄 수"], [[u["dir"], u["loc"]] for u in uncovered]),
        "\n## 진단 규칙에 따라 하향된 발견\n" + ("\n".join(f"- {p}" for p in policy) or "- 없음"),
        "\n## 형식 오류\n" + ("\n".join(f"- {e}" for e in errors) or "- 없음"),
        "\n## 전체 발견 (심각도순)\n",
        md_table(
            ["ID", "심각도", "증거", "검증", "제목", "근거 기준"],
            [
                [
                    x["id"],
                    x["severity"],
                    x["evidence_level"],
                    x["_verified"],
                    x["title"],
                    ", ".join(x["criteria"][:3]),
                ]
                for x in sorted(final, key=lambda x: (order[x["severity"]], x["id"]))
            ],
        ),
    ]
    write_outputs(args.results, "통합_집계", data, "\n".join(md) + "\n")
    sheet = [
        "# 사람 검토 시트 — 차단·높음\n",
        "각 행의 '판정' 칸에 동의 / 반려 / 보류 중 하나를 적고, 필요하면 메모를 남깁니다. 반려한 항목은 이유를 적어 두면 다음 진단의 판례가 됩니다.\n",
        md_table(
            ["ID", "심각도", "제목", "쉬운 설명", "증거", "판정", "메모"],
            [
                [
                    x["id"],
                    x["severity"],
                    x["title"],
                    x["plain"],
                    f"{x['evidence_level']} {x['evidence'][:60]}",
                    "",
                    "",
                ]
                for x in sorted(final, key=lambda x: (order[x["severity"]], x["id"]))
                if x["severity"] in ("차단", "높음")
            ],
        ),
    ]
    (args.results / "사람검토시트.md").write_text("\n".join(sheet) + "\n", encoding="utf-8")
    print(f"사람 검토 시트: {args.results / '사람검토시트.md'}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
