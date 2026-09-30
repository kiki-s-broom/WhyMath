#!/usr/bin/env python3
"""HARN-205 기준 신선도 판정의 **변별력** 검증 — 절(節)을 하나씩 끊어 RED를 확인한다.

정상 입력에서 초록인 것은 보호의 증거가 아니다(CLAUDE.md 「보호 장치를 실패 주입 없이
'보호 있음'으로 선언 금지」). 이 스크립트는 `tests/harness/test_port_freshness.py`가 동결하는
절을 `scripts/harness/port_freshness.py`(와 집행 지점 `.claude/commands/drive.md`)에서 하나씩 끊고,
그때마다 그 테스트 파일이 실제로 RED를 내는지 본다.

acceptance ⑤가 요구하는 4종(P01~P04) — 교집합 계산 무력화 · 0건 가드 제거 · 파일명 매칭 제거 ·
target 기본값을 위임 기준으로 되돌림 — 에 더해, 같은 테스트 파일이 지키는 나머지 절(P05~P08)도
끊는다. 절을 지웠는데 GREEN이면 가드가 관대한 게 아니라 픽스처가 그 절을 안 밟은 것이다.

러너(주입 1건 단언 · `mutated != original` 단언 · 원복 sha256 동일 단언 · 백업 원복)는 HARN-174의
`verify_gate_graph_discrimination.py`를 그대로 재사용한다 — 하네스가 늘어도 단언은 한 벌이다.

판정: 대조군(무주입)이 GREEN이고 전 뮤테이션이 RED면 exit 0, 하나라도 어긋나면 exit 1.
실행: `python3 scripts/harness/verify_port_freshness_discrimination.py`
      (pytest가 설치된 인터프리터로)
      `--list` 는 주입 목록만 출력한다. `--only <이름>`(반복)으로 일부만.
"""

from __future__ import annotations

import argparse
import sys

from verify_gate_graph_discrimination import HARNESS, REPO, Mutation, run

TOOL = HARNESS / "port_freshness.py"
DRIVE = REPO / ".claude" / "commands" / "drive.md"
TEST_FILE = "tests/harness/test_port_freshness.py"

#: 각 항목은 "그 절이 없으면 통과하는 반례"가 test_port_freshness.py에 실재하는지를 묻는다.
MUTATIONS: list[Mutation] = [
    # ── acceptance ⑤ 필수 4종 ──
    Mutation(
        "P01-intersection-disabled",
        "교집합 계산 — 참조 경로 ∩ 기준→대상 변경",
        TOOL,
        "    hits = sorted(set(unique_paths) & drift_set)\n",
        "    hits = sorted(set(unique_paths) & set())  # MUTANT\n",
    ),
    Mutation(
        "P02-zero-guard-removed",
        "판정 대상 0건은 exit 2(스캔 0건 공허 통과 금지)",
        TOOL,
        "        if self.judged == 0:\n            return EXIT_UNJUDGEABLE\n",
        "        if False:  # MUTANT\n            return EXIT_UNJUDGEABLE\n",
    ),
    Mutation(
        "P03-basename-match-removed",
        "단독 파일명(`app.py`·CLAUDE.md)을 저장소 경로로 푼다",
        TOOL,
        "    return list(index.by_basename.get(name, ()))\n",
        "    return []  # MUTANT\n",
    ),
    Mutation(
        "P04-default-target-is-base",
        "--target 생략 = HEAD (위임 기준이면 변경 0건으로 늘 신선)",
        TOOL,
        "    target_ref = args.target if args.target is not None else DEFAULT_TARGET\n",
        "    target_ref = args.target if args.target is not None"
        " else args.delegate_base  # MUTANT\n",
    ),
    # ── 같은 파일이 지키는 나머지 절 ──
    Mutation(
        "P05-renames-folded",
        "개명은 삭제+추가로 편다(옛 경로 참조를 놓치지 않는다)",
        TOOL,
        '"diff", "--name-only", "--no-renames", "-z", base, target',
        '"-c", "diff.renames=true", "diff", "--name-only", "-z", base, target',
    ),
    Mutation(
        "P06-self-inclusion-guard-removed",
        "대상에 이식 자신이 들어 있으면 판정 불가(exit 2)",
        TOOL,
        "        if at_target is not None and at_target == art.text:\n",
        "        if False:  # MUTANT\n",
    ),
    Mutation(
        "P07-unknown-folded-to-zero",
        "모호 참조의 후보 중 변경이 있으면 '모름' — 0으로 접지 않는다",
        TOOL,
        "        if changed:\n            unknown.append((res, changed))\n",
        "        if False:  # MUTANT\n            unknown.append((res, changed))\n",
    ),
    Mutation(
        "P08-drive-pr-check-unwired",
        "집행 지점 — drive.md가 PR 직전(origin/main) 판정을 실행 줄로 갖는다",
        DRIVE,
        "--delegate-base <위임기준커밋> --target origin/main <산출물경로...>\n",
        "--delegate-base <위임기준커밋> <산출물경로...>  # MUTANT\n",
    ),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--list", action="store_true", help="주입 목록만 출력")
    parser.add_argument("--only", action="append", default=None, help="이 이름의 주입만")
    args = parser.parse_args(argv)
    if args.list:
        for mutation in MUTATIONS:
            print(f"{mutation.name}\t{mutation.path.name}\t{mutation.clause}")
        return 0
    names = set(args.only) if args.only else None
    return run(names, mutations=MUTATIONS, test_file=TEST_FILE)


if __name__ == "__main__":
    sys.exit(main())
