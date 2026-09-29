#!/usr/bin/env python3
"""HARN-170 격리·누출 판별의 **변별력** 검증 — 절을 하나씩 끊어 RED를 확인한다.

정상 입력에서 초록인 것은 보호의 증거가 아니다(CLAUDE.md 「보호 장치를 실패 주입 없이
'보호 있음'으로 선언 금지」). 두 무리의 절을 하나씩 끊고, 그 절을 동결하는 테스트 파일이 실제로
RED를 내는지 본다.

  · 격리 무리(I) → `tests/harness/test_real_ledger_isolation.py`
      conftest ① 쓰기 차단 · 실제 루트 판정 · ② 세션 전후 대조(지문·차이·실패 분기·위임 배선)
  · 판별 무리(E) → `tests/harness/test_event_leaks.py`
      누출 서명 5조건(파일·호출 수·README·길이·고립·착지일) · 잇기 간격 · 샤드 분리 ·
      policy report 제외 · 기간 필터 전 판정

격리를 끊는 주입(I01·I02)에서는 프로브 테스트가 실제 저장소 대장에 실제로 쓴다 — 프로브가
호출 직전 바이트로 되돌린 뒤 실패하므로 대장은 오염된 채 남지 않는다. 그래도 이 스크립트는
**별도 워크트리**에서 돌린다(주입은 작업 트리의 파일을 잠깐 바꾼다).

러너는 HARN-174의 `verify_gate_graph_discrimination.run`(주입 1건 · `mutated != original` ·
원복 sha256 동일 단언)을 재사용한다.

판정: 두 무리 모두 대조군 GREEN이고 전 뮤테이션이 RED면 exit 0, 하나라도 어긋나면 exit 1.
실행: `python3 scripts/harness/verify_real_ledger_isolation_discrimination.py`  (`--list` 는 목록만)
"""

from __future__ import annotations

import argparse
import sys

from verify_gate_graph_discrimination import HARNESS, REPO, Mutation, run

CLI = HARNESS / "backlog.py"
LEAKS = HARNESS / "event_leaks.py"
CONFTEST = REPO / "tests" / "harness" / "conftest.py"
GUARD = REPO / "tests" / "harness" / "_ledger_guard.py"

ISOLATION_TEST_FILE = "tests/harness/test_real_ledger_isolation.py"
LEAK_TEST_FILE = "tests/harness/test_event_leaks.py"

#: 격리 무리 — ISOLATION_TEST_FILE이 각 절의 반례를 갖는지 묻는다.
ISOLATION_MUTATIONS: list[Mutation] = [
    Mutation(
        "I01-sink-disabled",
        "실제 루트를 겨눈 이벤트는 기록하지 않고 모은다(conftest ①)",
        CONFTEST,
        "        if _ledger_guard.is_real_root(root):\n",
        "        if False:  # MUTANT\n",
    ),
    Mutation(
        "I02-real-root-never-matches",
        "실제 저장소 루트를 실제 루트로 알아본다",
        GUARD,
        "        return Path(str(root)).resolve() == REPO_ROOT.resolve()\n",
        "        return False  # MUTANT\n",
    ),
    Mutation(
        "I03-fingerprint-scans-nothing",
        "전후 대조의 지문이 실제 대장 파일을 본다(스캔 0건이 아니다)",
        GUARD,
        "    base = root / LEDGER_DIR_NAME\n",
        '    base = root / "no-such-dir"  # MUTANT\n',
    ),
    Mutation(
        "I04-changes-miss-modification",
        "내용이 바뀐 파일을 변경으로 센다",
        GUARD,
        '            changes.append(f"변경 {name}")\n',
        "            pass  # MUTANT\n",
    ),
    Mutation(
        "I05-guard-never-fails",
        "대장이 바뀌었으면 세션을 실패시킨다",
        GUARD,
        "    if changes:\n",
        "    if False:  # MUTANT\n",
    ),
    Mutation(
        "I06-session-fixture-not-delegating",
        "세션 픽스처가 판정 본체에 위임한다(존재 ≠ 작동)",
        CONFTEST,
        "    yield from _ledger_guard.guard_session("
        "fail=lambda message: pytest.fail(message, pytrace=False))\n",
        "    yield  # MUTANT\n",
    ),
]

#: 판별 무리 — LEAK_TEST_FILE이 각 절의 반례를 갖는지 묻는다.
LEAK_MUTATIONS: list[Mutation] = [
    Mutation(
        "E01-files-clause",
        "① 누출 파일(backlog.py·README.md) 밖의 경고가 섞이면 누출이 아니다",
        LEAKS,
        "    if not files <= LEAK_FILES or HOT_FILE not in files:  # ①\n",
        "    if HOT_FILE not in files:  # MUTANT\n",
    ),
    Mutation(
        "E02-hot-count-clause",
        "② backlog.py 경고는 규칙마다 정확히 3건",
        LEAKS,
        "    if any(count != HOT_CALLS_PER_RULE for count in hot):  # ②\n",
        "    if False:  # MUTANT\n",
    ),
    Mutation(
        "E03-cold-clause",
        "③ README.md 경고는 0~1건이고 scope_drift뿐",
        LEAKS,
        "    if sum(count for _rule, count in cold) > 1"
        ' or any(rule != "scope_drift" for rule, _ in cold):\n',
        "    if False:  # MUTANT\n",
    ),
    Mutation(
        "E04-span-clause",
        "④ 묶음 전체 길이 상한",
        LEAKS,
        "    return (bundle[-1].moment - bundle[0].moment).total_seconds()"
        " <= SPAN_SECONDS  # ④ 길이\n",
        "    return True  # MUTANT\n",
    ),
    Mutation(
        "E05-isolation-before",
        "④ 앞쪽 고립 — 사람의 연속 편집은 앞에 다른 경고가 붙어 있다",
        LEAKS,
        "                and (bundle[0].moment - before).total_seconds() < ISOLATION_SECONDS\n",
        "                and False  # MUTANT\n",
    ),
    Mutation(
        "E06-isolation-after",
        "④ 뒤쪽 고립",
        LEAKS,
        "                and (after - bundle[-1].moment).total_seconds() < ISOLATION_SECONDS\n",
        "                and False  # MUTANT\n",
    ),
    Mutation(
        "E07-epoch-clause",
        "⑤ 누출 경로 착지일 이전은 누출이 아니다",
        LEAKS,
        "            if bundle[0].moment.date() < LEAK_EPOCH:  # ⑤\n",
        "            if False:  # MUTANT\n",
    ),
    Mutation(
        "E08-join-gap",
        "이웃 간격이 상한을 넘으면 묶음이 끊긴다",
        LEAKS,
        "(event.moment - bundles[-1][-1].moment).total_seconds() <= GAP_SECONDS:\n",
        "(event.moment - bundles[-1][-1].moment).total_seconds()"
        " <= GAP_SECONDS * 3:  # MUTANT\n",
    ),
    Mutation(
        "E09-shards-mixed",
        "다른 세션(샤드)의 경고는 한 묶음으로 섞지 않는다",
        LEAKS,
        "        by_shard.setdefault(event.shard, []).append(event)\n",
        '        by_shard.setdefault("all", []).append(event)  # MUTANT\n',
    ),
    Mutation(
        "E10-report-does-not-exclude",
        "policy report 가 누출 묶음을 집계에서 뺀다",
        CLI,
        "        if record.key in leaked:\n            excluded += 1\n            continue\n",
        "        pass  # MUTANT\n",
    ),
    Mutation(
        "E11-report-judges-after-the-window",
        "누출 판정은 기간 필터 전 전체에서 한다(경계에서 잘린 반쪽도 뺀다)",
        CLI,
        "    leaked = event_leaks.leak_keys(record for record, _event, _known in warns)\n",
        "    leaked = event_leaks.leak_keys(\n"
        "        record for record, _e, _k in warns if record.moment >= cutoff  # MUTANT\n"
        "    )\n",
    ),
]

MUTATIONS: list[Mutation] = [*ISOLATION_MUTATIONS, *LEAK_MUTATIONS]


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
    print(f"■ 격리 무리 → {ISOLATION_TEST_FILE}")
    isolation_rc = run(names, mutations=ISOLATION_MUTATIONS, test_file=ISOLATION_TEST_FILE)
    print(f"\n■ 판별 무리 → {LEAK_TEST_FILE}")
    leak_rc = run(names, mutations=LEAK_MUTATIONS, test_file=LEAK_TEST_FILE)
    return 1 if (isolation_rc or leak_rc) else 0


if __name__ == "__main__":
    sys.exit(main())
