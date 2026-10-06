#!/usr/bin/env python3
"""HARN-177 판정 인계의 **변별력** 검증 — 절(節)을 하나씩 끊어 RED를 확인한다.

정상 입력에서 초록인 것은 보호의 증거가 아니다(CLAUDE.md 「보호 장치를 실패 주입 없이
'보호 있음'으로 선언 금지」). 이 스크립트는 `tests/harness/test_gate_verdict_handoff.py`가
동결하는 절 — ① done 인계의 세 선택지와 무선택 거부 · ② 판정 결과 미기록 표시 · ⑥ 열린 상류
소유 태스크 — 을 **하네스 코드에서** 하나씩 끊고, 그때마다 그 테스트 파일이 실제로 RED를
내는지 본다.

러너(주입 1건 단언 · `mutated != original` 단언 · 원복 sha256 동일 단언 · 메모리/임시 파일
백업 원복)는 HARN-174의 `verify_gate_graph_discrimination.py`를 그대로 재사용한다 — 하네스가
둘이 되어도 단언은 한 벌이다.

판정: 대조군(무주입)이 GREEN이고 전 뮤테이션이 RED면 exit 0, 하나라도 어긋나면 exit 1.
실행: `python3 scripts/harness/verify_gate_verdict_handoff_discrimination.py`
      (pytest가 설치된 인터프리터로)
      `--list` 는 주입 목록만 출력한다.
"""

from __future__ import annotations

import argparse
import sys

from verify_gate_graph_discrimination import CLI, HARNESS, SELECTOR, STORE, Mutation, run

REPORT = HARNESS / "report.py"
TEST_FILE = "tests/harness/test_gate_verdict_handoff.py"

#: 각 항목은 "그 절이 없으면 통과하는 반례"가 test_gate_verdict_handoff.py에 실재하는지를 묻는다.
MUTATIONS: list[Mutation] = [
    # ── ① done 인계 — 세 선택지와 무선택 거부 ──
    Mutation(
        "H01-done-handoff-required",
        "decision 게이트 입력의 done 은 FAIL/PASS/판정 무관 중 하나가 없으면 거부한다",
        CLI,
        "    if verdict is None and no_verdict is None:\n",
        "    if False:  # MUTANT\n",
    ),
    Mutation(
        "H02-done-both-rejected",
        "--verdict 와 --no-verdict 를 함께 주면 거부한다",
        CLI,
        "    if verdict is not None and no_verdict is not None:\n",
        "    if False:  # MUTANT\n",
    ),
    Mutation(
        "H03-no-verdict-needs-reason",
        "--no-verdict 의 빈 사유는 거부한다",
        CLI,
        "        if not no_verdict.strip():\n",
        "        if False:  # MUTANT\n",
    ),
    Mutation(
        "H04-no-verdict-rejects-verdict-material",
        "--no-verdict 에 근거·소유 태스크를 붙이면 거부한다",
        CLI,
        "        if evidence or named_owners or attach:\n",
        "        if False:  # MUTANT\n",
    ),
    Mutation(
        "H05-fail-needs-owner",
        "FAIL 은 미종결 소유 태스크 1건 이상(새 부착 또는 열린 상류)이 없으면 거부한다",
        CLI,
        "    if not owners:\n        raise _VerdictRejectedError(\n",
        "    if False:  # MUTANT\n        raise _VerdictRejectedError(\n",
    ),
    Mutation(
        "H06-fail-snapshot-recorded",
        "FAIL 기록에 기록 시점 done 입력 스냅샷이 실린다",
        CLI,
        "    return [store.format_fail_verdict(owners, evidence, done_inputs)]\n",
        "    return [store.format_fail_verdict(owners, evidence, [])]  # MUTANT\n",
    ),
    Mutation(
        "H07-pass-snapshot-recorded",
        "PASS 기록에 기록 시점 done 입력 스냅샷이 실린다",
        CLI,
        "        return [store.format_pass_verdict(done_inputs, evidence)]\n",
        "        return [store.format_pass_verdict([], evidence)]  # MUTANT\n",
    ),
    Mutation(
        "H08-pass-rejects-owners",
        "PASS 에 소유 태스크를 붙이면 거부한다",
        CLI,
        "        if add_deps or named_owners:\n",
        "        if False:  # MUTANT\n",
    ),
    Mutation(
        "H09-done-appends-gate-correction",
        "done 인계가 게이트 corrections 에 기록을 붙인다",
        CLI,
        "        gate.corrections = list(gate.corrections) + [record]\n"
        "        own_errors = [e for e in store.validate_backlog(backlog) if gate.id in e]\n",
        "        own_errors = [e for e in store.validate_backlog(backlog) if gate.id in e]"
        "  # MUTANT\n",
    ),
    Mutation(
        "H10-done-saves-gates",
        "done 인계가 gates.yaml 을 실제로 쓴다",
        CLI,
        "    if handoff is not None:\n        _write_gate_handoff(root, backlog, task, handoff)\n",
        "    if False:  # MUTANT\n        _write_gate_handoff(root, backlog, task, handoff)\n",
    ),
    Mutation(
        "H11-flags-on-non-input-rejected",
        "게이트 입력이 아닌 태스크의 판정 플래그는 거부한다",
        CLI,
        "        if flags_given:\n",
        "        if False:  # MUTANT\n",
    ),
    Mutation(
        "H12-multi-gate-needs-gate-flag",
        "입력 게이트가 2건 이상이면 --gate 없이는 거부한다",
        CLI,
        "    if len(targets) > 1 and gate_id is None:\n",
        "    if False:  # MUTANT\n",
    ),
    Mutation(
        "H13-gate-flag-must-be-input",
        "--gate 는 이 태스크를 입력으로 둔 게이트여야 한다",
        CLI,
        "        gate = next((g for g in targets if g.id == gate_id), None)\n",
        "        gate = targets[0]  # MUTANT\n",
    ),
    Mutation(
        "H14-human-gate-not-a-target",
        "판정 인계는 decision 게이트의 입력에만 요구한다",
        CLI,
        '        if g.status == "pending" and g.kind == "decision" and task.id in g.depends_on\n',
        '        if g.status == "pending" and task.id in g.depends_on  # MUTANT\n',
    ),
    # ── ⑥ 열린 상류 소유 태스크 ──
    Mutation(
        "H15-owner-must-be-open-upstream",
        "--owner 는 게이트의 열린 상류에 있어야 한다(끝난 태스크 너머는 연결이 아니다)",
        CLI,
        "        if owner not in reachable:\n",
        "        if False:  # MUTANT\n",
    ),
    Mutation(
        "H16-owner-must-be-open",
        "끝난 태스크는 --owner 가 될 수 없다",
        CLI,
        "        if task.status in TERMINAL_STATUSES:\n            raise _VerdictRejectedError(\n",
        "        if False:  # MUTANT\n            raise _VerdictRejectedError(\n",
    ),
    Mutation(
        "H17-named-owner-counted",
        "--owner 로 지목한 태스크가 소유자로 실제로 기록된다",
        CLI,
        "        if owner not in owners:\n            owners.append(owner)\n",
        "        pass  # MUTANT\n",
    ),
    Mutation(
        "H18-amend-owner-needs-verdict",
        "gates amend 의 --owner 는 --verdict 없이는 거부한다",
        CLI,
        "    if named_owners and verdict is None:\n",
        "    if False:  # MUTANT\n",
    ),
    Mutation(
        "H19-upstream-open-only-stops-at-done",
        "열린 상류 계산이 끝난 태스크에서 멈춘다",
        STORE,
        "                if open_only and backlog.tasks[pid].status in TERMINAL_STATUSES:\n",
        "                if False:  # MUTANT\n",
    ),
    Mutation(
        "H20-validate-uses-open-upstream",
        "validate 의 소유 태스크 대조가 열린 상류를 본다",
        STORE,
        "        upstream = upstream_tasks(backlog, (GATE_NODE, gid), graph, open_only=True)\n",
        "        upstream = upstream_tasks(backlog, (GATE_NODE, gid), graph, open_only=False)"
        "  # MUTANT\n",
    ),
    # ── ② 표시 정직성 ──
    Mutation(
        "H21-state-compares-snapshot",
        "판정 기록은 스냅샷이 지금 done 인 입력 집합과 같을 때만 현행이다",
        STORE,
        "    if record is None or set(record.inputs) != done_inputs:\n",
        "    if record is None:  # MUTANT\n",
    ),
    Mutation(
        "H22-state-none-for-non-decision",
        "판정 상태는 decision 게이트에만 있다",
        STORE,
        '    if getattr(gate, "status", None) != "pending" or getattr(gate, "kind", None) '
        '!= "decision":\n',
        '    if getattr(gate, "status", None) != "pending":  # MUTANT\n',
    ),
    Mutation(
        "H23-label-unrecorded",
        "'판정 결과 미기록' 문구가 실제로 난다",
        STORE,
        "    if state == JUDGMENT_UNRECORDED:\n",
        "    if False:  # MUTANT\n",
    ),
    Mutation(
        "H24-wait-tail-uses-state",
        "대기 경로 꼬리가 판정 상태를 본다(무조건 '사람 판정 대기'가 아니다)",
        SELECTOR,
        '        suffix = gate_tail_suffix(backlog, tail[-1]) if waiting_on_person else ""\n',
        '        suffix = " (사람 판정 대기)" if waiting_on_person else ""  # MUTANT\n',
    ),
    Mutation(
        "H25-inputs-text-carries-state",
        "gates show/list·status 의 여는 작업 줄이 판정 상태를 싣는다",
        REPORT,
        "        if state is not None and state != store.JUDGMENT_OPEN:\n",
        "        if False:  # MUTANT\n",
    ),
    Mutation(
        "H26-status-json-judgment",
        "status --json 의 pending_gates 가 judgment 를 낸다",
        REPORT,
        '                "judgment": store.gate_judgment_state(backlog, v.gate),\n',
        '                "judgment": None,  # MUTANT\n',
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
    return run(set(args.only) if args.only else None, mutations=MUTATIONS, test_file=TEST_FILE)


if __name__ == "__main__":
    import _stdio  # 스크립트 실행이면 이 디렉터리가 sys.path[0]이다 (OPS-53)

    _stdio.ensure_utf8_stdio()
    sys.exit(main())
