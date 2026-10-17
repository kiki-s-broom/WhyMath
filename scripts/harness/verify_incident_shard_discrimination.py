#!/usr/bin/env python3
"""HARN-130 사고 대장 샤딩·인덱스 비커밋의 **변별력** 검증 — 절을 하나씩 끊어 RED를 확인한다.

정상 입력에서 초록인 것은 보호의 증거가 아니다(CLAUDE.md 「보호 장치를 실패 주입 없이
'보호 있음'으로 선언 금지」). 이 스크립트는 두 무리의 절을 하나씩 끊고, 그때마다 그 절을
동결하는 테스트 파일이 실제로 RED를 내는지 본다.

  · 대장 무리(L) → `tests/harness/test_incident_ledger_sharding.py`
      쓰기 샤딩 · 레거시 불변 · 세션 키 · 읽기 합집합 · 동률 순서 · 경로 탈출 방어 ·
      오류 위치 · union 배선 · 두 브랜치 실제 머지
  · 인덱스 무리(J) → `tests/harness/test_jit_rules.py`
      훅이 저장 파일이 아니라 대장을 읽음 · 0건/스키마 위반 RED · 옛 build 비기록 ·
      .gitignore 재유입 방지 · CI 스텝 배선

러너(주입 1건 단언 · `mutated != original` 단언 · 원복 sha256 동일 단언 · 백업 원복)는 HARN-174의
`verify_gate_graph_discrimination.py`를 그대로 재사용한다 — 무리마다 대상 파일이 달라 `run`을
두 번 부른다.

판정: 두 무리 모두 대조군(무주입) GREEN이고 전 뮤테이션이 RED면 exit 0, 하나라도 어긋나면 exit 1.
실행: `python3 scripts/harness/verify_incident_shard_discrimination.py`  (`--list` 는 목록만)
주의: 뮤테이션은 작업 트리의 파일을 잠깐 바꾼다 — 별도 워크트리에서 돌리는 것이 안전하다.
"""

from __future__ import annotations

import argparse
import sys

from verify_gate_graph_discrimination import HARNESS, REPO, Mutation, run

CLI = HARNESS / "backlog.py"
INCIDENTS = HARNESS / "incidents.py"
GITATTRIBUTES = REPO / ".gitattributes"
GITIGNORE = REPO / ".gitignore"
CI_WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"

LEDGER_TEST_FILE = "tests/harness/test_incident_ledger_sharding.py"
INDEX_TEST_FILE = "tests/harness/test_jit_rules.py"

#: 대장 무리 — 각 항목은 "그 절이 없으면 통과하는 반례"가 LEDGER_TEST_FILE에 실재하는지를 묻는다.
LEDGER_MUTATIONS: list[Mutation] = [
    Mutation(
        "L01-append-goes-to-legacy",
        "신규 등재는 공용(레거시) 파일이 아니라 세션 샤드에 간다",
        INCIDENTS,
        "    path = shard_path(root, shard_name)\n    path.parent.mkdir(",
        "    path = ledger_path(root)  # MUTANT\n    path.parent.mkdir(",
    ),
    Mutation(
        "L02-one-shard-for-all-sessions",
        "샤드 이름은 세션(=브랜치)마다 다르다",
        CLI,
        "        root, store.session_shard_name(store.current_branch(root)), candidate\n",
        '        root, "shared.ndjson", candidate  # MUTANT\n',
    ),
    Mutation(
        "L03-read-skips-shards",
        "읽기가 샤드를 포함한다(오늘 쓴 줄이 사라지지 않는다)",
        INCIDENTS,
        '        paths.extend(sorted(shards.glob("*.ndjson")))\n',
        "        pass  # MUTANT\n",
    ),
    Mutation(
        "L04-read-skips-legacy",
        "읽기가 레거시를 포함한다(과거가 사라지지 않는다)",
        INCIDENTS,
        "    if legacy.exists():\n        paths.append(legacy)\n",
        "    if legacy.exists():\n        pass  # MUTANT\n",
    ),
    Mutation(
        "L05-shard-order",
        "같은 날 동률은 레거시 → 샤드 이름순으로 깬다(결정적)",
        INCIDENTS,
        '        paths.extend(sorted(shards.glob("*.ndjson")))\n',
        '        paths.extend(sorted(shards.glob("*.ndjson"), reverse=True))  # MUTANT\n',
    ),
    Mutation(
        "L06-shard-name-escape",
        "샤드 이름은 파일명 하나뿐 — 디렉터리 탈출·숨김 파일 거부",
        INCIDENTS,
        "    if not shard_name or Path(shard_name).name != shard_name"
        ' or shard_name.startswith("."):\n',
        "    if False:  # MUTANT\n",
    ),
    Mutation(
        "L07-error-location",
        "스키마 오류 위치가 어느 샤드인지 말한다",
        INCIDENTS,
        "        where_prefix = path.relative_to(backlog_root).as_posix()\n",
        "        where_prefix = path.name  # MUTANT\n",
    ),
    Mutation(
        "L08-nth-date-order",
        "회차는 파일 경계를 넘어 날짜 순이다",
        INCIDENTS,
        "        for rank, index in enumerate("
        "sorted(indices, key=lambda i: (incidents[i].date, i)), 1):\n",
        "        for rank, index in enumerate(sorted(indices), 1):  # MUTANT\n",
    ),
    Mutation(
        "L09-union-shard-pattern",
        "샤드 패턴의 로컬 union 방어가 선언돼 있다",
        GITATTRIBUTES,
        "backlog/incidents/*.ndjson   merge=union\n",
        "",
    ),
    Mutation(
        "L10-union-legacy-pattern",
        "레거시 파일의 로컬 union 방어가 선언돼 있다",
        GITATTRIBUTES,
        "backlog/incidents.ndjson   merge=union\n",
        "",
    ),
]

#: 인덱스 무리 — INDEX_TEST_FILE이 각 절의 반례를 갖는지 묻는다.
INDEX_MUTATIONS: list[Mutation] = [
    Mutation(
        "J01-hook-reads-a-stored-file",
        "훅은 저장된 인덱스 파일이 아니라 대장에서 후보를 계산한다",
        CLI,
        "        notes, _ = _build_jit_notes(root, backlog)\n",
        "        notes = [  # MUTANT\n"
        "            jit_rules.Note(**n)\n"
        "            for n in json.loads(\n"
        '                (root / "backlog" / "jit_index.json").read_text(encoding="utf-8")\n'
        '            )["notes"]\n'
        "        ]\n",
    ),
    Mutation(
        "J02-check-passes-on-zero",
        "jit check 는 후보 0건(경로 해소 전멸)을 red로 낸다",
        CLI,
        '    if not notes:\n        print(\n            "❌ 적시 주입 후보 0건',
        '    if False:  # MUTANT\n        print(\n            "❌ 적시 주입 후보 0건',
    ),
    Mutation(
        "J03-check-ignores-schema-errors",
        "jit check 는 대장 스키마 위반을 red로 낸다",
        CLI,
        "    if errors:\n        print(\n"
        '            f"❌ 대장 스키마 위반 {len(errors)}건 — 적시 주입 후보를 믿을 수 없다:",',
        "    if False:  # MUTANT\n        print(\n"
        '            f"❌ 대장 스키마 위반 {len(errors)}건 — 적시 주입 후보를 믿을 수 없다:",',
    ),
    Mutation(
        "J04-legacy-build-writes-a-file",
        "옛 명령 jit build 는 파일을 만들지 않는다",
        CLI,
        "    if legacy_build:\n        print(\n",
        "    if legacy_build:\n"
        '        (root / "backlog" / "jit_index.json")'
        '.write_text("{}", encoding="utf-8")  # MUTANT\n'
        "        print(\n",
    ),
    Mutation(
        "J05-gitignore-lets-the-index-back",
        "옛 코드가 남긴 인덱스 파일이 git add 로 다시 들어가지 않는다",
        GITIGNORE,
        "\nbacklog/jit_index.json\n",
        "\n",
    ),
    Mutation(
        "J06-ci-step-removed",
        "CI harness-integrity 잡이 jit check 를 실제로 돌린다",
        CI_WORKFLOW,
        "        run: python3 scripts/harness/backlog.py jit check\n",
        "        run: python3 scripts/harness/backlog.py rules report  # MUTANT\n",
    ),
]

MUTATIONS: list[Mutation] = [*LEDGER_MUTATIONS, *INDEX_MUTATIONS]


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
    print(f"■ 대장 무리 → {LEDGER_TEST_FILE}")
    ledger_rc = run(names, mutations=LEDGER_MUTATIONS, test_file=LEDGER_TEST_FILE)
    print(f"\n■ 인덱스 무리 → {INDEX_TEST_FILE}")
    index_rc = run(names, mutations=INDEX_MUTATIONS, test_file=INDEX_TEST_FILE)
    return 1 if (ledger_rc or index_rc) else 0


if __name__ == "__main__":
    import _stdio  # 스크립트 실행이면 이 디렉터리가 sys.path[0]이다 (OPS-53)

    _stdio.ensure_utf8_stdio()
    sys.exit(main())
