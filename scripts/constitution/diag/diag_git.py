# diag_git.py — 변경 이력 규율 점검 (단계 S03·S07·S08)
# 보는 것: 페이즈·주차별 커밋 수, Conventional Commits 준수율(9장, content 타입 포함),
#          큰 커밋(파일 25개·변경 400줄 초과), 코드·콘텐츠 혼합 커밋, 테스트 없는 fix 커밋,
#          AI 공동 작성 커밋(Claude Code 서명) 비율과 크기, 동결 항목(FZ) 동결일 이후 변경,
#          커밋 안 된 변경, 브랜치 목록
# 사용: python diag_git.py --repo <저장소> --out <결과>/raw --since 2026-08-27 [--freeze diag_freeze.json]
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

from _diagcommon import base_parser, check_paths, git, match, md_table, setup_console, write_outputs

PHASES = [
    ("Phase 0", "2026-08-27", "2026-09-06"),
    ("Phase 1", "2026-09-07", "2026-09-27"),
    ("Phase 2", "2026-09-28", "2026-10-25"),
    ("Phase 3", "2026-10-26", "2026-11-22"),
    ("Phase 4", "2026-11-23", "2026-12-13"),
    ("Phase 5", "2026-12-14", "2026-12-31"),
]
TYPES = "feat|fix|refactor|perf|docs|test|build|ci|chore|content|revert|style"
CONVENTIONAL = re.compile(
    rf"^({TYPES})(\([\w가-힣.\-/ ]+\))?!?: (?P<desc>\S.*)"
)  # 표준북 9장 형식 (타입·범위·콜론)
MIN_DESC = 5  # 9장 기준: 설명 5자 이상
TEST_PATH = re.compile(
    r"(^|/)(tests?|__tests__|integration_test)/|(^|/)test_[^/]+\.py$|_test\.(py|dart)$|\.(test|spec)\.(js|ts)$"
)
AI_SIGN = re.compile(
    r"(?i)co-authored-by:\s*claude|generated with \[?claude code|🤖 generated with"
)
BIG_FILES, BIG_LINES = 25, 400


def phase_of(day: str) -> str:
    for name, start, end in PHASES:
        if start <= day <= end:
            return name
    return "기간 밖"


def main() -> int:
    setup_console()
    ap = base_parser("변경 이력 규율 점검")
    ap.add_argument(
        "--since", default="2026-08-27", help="이 날짜 이후 커밋만 (기본: Phase 0 시작일)"
    )
    ap.add_argument(
        "--freeze",
        type=Path,
        help="동결 항목 설정 JSON {'FZ-05 ConceptNode': {'date': '2026-09-06', 'paths': [...]}}",
    )
    ap.add_argument(
        "--content-dirs", default="content/,data/", help="콘텐츠 폴더 (쉼표 구분, 혼합 커밋 판정용)"
    )
    args = ap.parse_args()
    repo, out = args.repo, args.out
    check_paths(repo, out)
    content_dirs = [c.strip() for c in args.content_dirs.split(",") if c.strip()]

    code, head = git(repo, "log", "-1", "--date=iso-strict", "--pretty=format:%H%x1f%aI%x1f%s")
    if code != 0:
        raise SystemExit(f"⛔ git 저장소가 아니거나 git을 실행할 수 없습니다: {head.strip()[:200]}")
    code, raw = git(
        repo,
        "log",
        "--no-merges",
        f"--since={args.since}",
        "--no-renames",
        "--numstat",
        "--pretty=format:%x1e%H%x1f%aI%x1f%s%x1f%b%x1f",
        timeout=600,
    )
    commits = []
    for chunk in raw.split("\x1e"):
        if not chunk.strip():
            continue
        parts = chunk.split("\x1f")
        if len(parts) < 5:
            continue
        sha, when, subject, body, rest = parts[0], parts[1], parts[2], parts[3], parts[-1]
        files, added, deleted = [], 0, 0
        for line in rest.strip().splitlines():
            cols = line.split("\t")
            if len(cols) == 3:
                files.append(cols[2])
                added += int(cols[0]) if cols[0].isdigit() else 0
                deleted += int(cols[1]) if cols[1].isdigit() else 0
        commits.append(
            {
                "sha": sha[:10],
                "date": when[:10],
                "subject": subject.strip(),
                "ai": bool(AI_SIGN.search(subject + "\n" + body)),
                "files": files,
                "lines": added + deleted,
            }
        )

    by_phase, by_week = Counter(), Counter()
    non_conv, short_desc, big, mixed, fix_no_test = [], [], [], [], []
    ai_sizes, human_sizes = [], []
    for c in commits:
        by_phase[phase_of(c["date"])] += 1
        y, w, _ = date.fromisoformat(c["date"]).isocalendar()
        by_week[f"{y}-W{w:02d}"] += 1
        m = CONVENTIONAL.match(c["subject"])
        if not m and not c["subject"].startswith(("Merge ", 'Revert "')):
            non_conv.append(c)
        elif m and len(m.group("desc").strip()) < MIN_DESC:
            short_desc.append(
                c
            )  # 형식은 맞지만 설명이 너무 짧음 (한국어는 짧아도 뜻이 통할 수 있어 따로 셈)
        if len(c["files"]) > BIG_FILES or c["lines"] > BIG_LINES:
            big.append(c)
        kinds = {
            "content" if any(f.startswith(d) for d in content_dirs) else "code" for f in c["files"]
        }
        if len(kinds) > 1:
            mixed.append(c)
        if c["subject"].startswith("fix") and not any(TEST_PATH.search(f) for f in c["files"]):
            fix_no_test.append(c)
        (ai_sizes if c["ai"] else human_sizes).append(c["lines"])

    freeze_hits = {}
    if args.freeze:
        try:
            groups = {
                k: v
                for k, v in json.loads(args.freeze.read_text(encoding="utf-8-sig")).items()
                if not k.startswith("_")
            }
        except (OSError, json.JSONDecodeError) as e:
            raise SystemExit(f"⛔ 동결 설정을 읽을 수 없습니다: {e}")
        for name, g in groups.items():
            hits = []
            for c in commits:
                if c["date"] > g["date"]:
                    touched = [f for f in c["files"] if match(f, g["paths"])]
                    if touched:
                        hits.append(
                            {
                                "sha": c["sha"],
                                "date": c["date"],
                                "subject": c["subject"],
                                "files": touched[:5],
                                "ai": c["ai"],
                            }
                        )
            freeze_hits[name] = {"date": g["date"], "paths": g["paths"], "changes": hits}

    _, status = git(repo, "status", "--porcelain")
    status_lines = [l for l in status.splitlines() if l.strip()]
    _, branches = git(
        repo, "for-each-ref", "--format=%(refname:short)%09%(committerdate:short)", "refs/heads"
    )
    _, merges = git(repo, "rev-list", "--merges", "--count", f"--since={args.since}", "HEAD")

    n = len(commits) or 1
    avg = lambda xs: round(sum(xs) / len(xs)) if xs else 0
    data = {
        "head": head.split("\x1f"),
        "since": args.since,
        "commits": len(commits),
        "merges": merges.strip(),
        "by_phase": dict(by_phase),
        "by_week": dict(sorted(by_week.items())),
        "conventional_rate": round(1 - len(non_conv) / n, 3) if commits else None,
        "ai_commits": len(ai_sizes),
        "ai_avg_lines": avg(ai_sizes),
        "human_avg_lines": avg(human_sizes),
        "non_conventional": non_conv,
        "short_description": short_desc,
        "big_commits": big,
        "mixed_commits": mixed,
        "fix_without_test": fix_no_test,
        "freeze": freeze_hits,
        "uncommitted": len([l for l in status_lines if not l.startswith("??")]),
        "untracked": len([l for l in status_lines if l.startswith("??")]),
        "branches": [b.split("\t") for b in branches.splitlines() if b.strip()],
    }
    short = lambda c: [
        c["sha"],
        c["date"],
        c["subject"][:70],
        len(c["files"]),
        c["lines"],
        "AI" if c["ai"] else "",
    ]
    md = [
        "# 변경 이력 규율 점검\n",
        f"대상: `{repo}` · {args.since} 이후 커밋 {len(commits)}개 (병합 커밋 {merges.strip()}개 제외)\n",
        md_table(
            ["항목", "값"],
            [
                [
                    "Conventional Commits 형식 준수율 (표준북 9장)",
                    f"{data['conventional_rate']:.0%}" if commits else "-",
                ],
                [f"형식은 맞지만 설명이 {MIN_DESC}자 미만", len(short_desc)],
                [f"큰 커밋 (파일 {BIG_FILES}개 또는 변경 {BIG_LINES}줄 초과)", len(big)],
                ["코드·콘텐츠 혼합 커밋", len(mixed)],
                ["테스트 변경 없는 fix 커밋", len(fix_no_test)],
                [
                    "AI 공동 작성 커밋 (Claude Code 서명)",
                    f"{len(ai_sizes)}개 · 평균 {data['ai_avg_lines']}줄 (사람 단독 평균 {data['human_avg_lines']}줄)",
                ],
                [
                    "커밋 안 된 변경 / 추적 안 되는 파일",
                    f"{data['uncommitted']} / {data['untracked']}",
                ],
            ],
        ),
        "\n## 페이즈별 커밋 수 (계획 문서 일정 기준)\n",
        md_table(
            ["페이즈", "기간", "커밋 수"],
            [[p, f"{s}~{e}", by_phase.get(p, 0)] for p, s, e in PHASES]
            + [["기간 밖", "-", by_phase.get("기간 밖", 0)]],
        ),
        "\n## 주차별 커밋 수\n",
        md_table(["주차", "커밋 수"], sorted(by_week.items())),
        "\n## 동결 항목의 동결일 이후 변경\n",
        (
            md_table(
                ["동결 항목", "동결일", "이후 변경 커밋 수", "예시"],
                [
                    [
                        k,
                        v["date"],
                        len(v["changes"]),
                        "; ".join(f"{h['sha']} {h['subject'][:40]}" for h in v["changes"][:2]),
                    ]
                    for k, v in freeze_hits.items()
                ],
            )
            if args.freeze
            else "_(동결 설정 없이 실행 — --freeze로 지정하세요)_"
        ),
        "\n## 큰 커밋\n",
        md_table(["커밋", "날짜", "제목", "파일", "줄", "AI"], [short(c) for c in big], 30),
        "\n## 형식을 지키지 않은 커밋 메시지\n",
        md_table(["커밋", "날짜", "제목", "파일", "줄", "AI"], [short(c) for c in non_conv], 30),
        "\n## 테스트 변경 없는 fix 커밋\n",
        md_table(["커밋", "날짜", "제목", "파일", "줄", "AI"], [short(c) for c in fix_no_test], 30),
        "\n## 코드·콘텐츠 혼합 커밋\n",
        md_table(["커밋", "날짜", "제목", "파일", "줄", "AI"], [short(c) for c in mixed], 30),
    ]
    write_outputs(out, "diag_git", data, "\n".join(md) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
