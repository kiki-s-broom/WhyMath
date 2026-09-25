#!/usr/bin/env python3
"""HARN-174 게이트 그래프 편입의 **변별력** 검증 — 절(節)을 하나씩 끊어 RED를 확인한다.

정상 입력에서 초록인 것은 보호의 증거가 아니다(CLAUDE.md 「보호 장치를 실패 주입 없이
'보호 있음'으로 선언 금지」). 이 스크립트는 `tests/harness/test_gate_graph.py`가 동결하는
절 — 입력 필수 · 순환 · 막다른 길 · clear 집행 · FAIL 기록 · 전이 해금 수 · 대기 경로 — 을
**하네스 코드에서** 하나씩 끊고, 그때마다 그 테스트 파일이 실제로 RED를 내는지 본다.

주입 자체의 실재를 단언한다(CLAUDE.md 「주입 자체의 실재」 2026-09-06):
  ① 치환 대상이 파일 안에 **정확히 1건**인가(0건이면 주입이 조용히 실패하고, 2건 이상이면
     엉뚱한 자리를 고친다)
  ② 치환 후 내용이 원본과 **다른가**(mutated != original)
  ③ 원복 후 파일이 **바이트 동일**한가(sha256 대조)
원복은 `git checkout`이 아니라 메모리·임시 파일 백업 복원이다(CLAUDE.md 2026-08-10 —
git 계열 원복은 미커밋 작업분까지 되돌린다).

판정: 대조군(무주입)이 GREEN이고 전 뮤테이션이 RED면 exit 0, 하나라도 어긋나면 exit 1.
실행: `python3 scripts/harness/verify_gate_graph_discrimination.py` (pytest가 설치된 인터프리터로)
      `--list` 는 주입 목록만 출력한다.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HARNESS = REPO / "scripts" / "harness"
TEST_FILE = "tests/harness/test_gate_graph.py"

MODELS = HARNESS / "models.py"
STORE = HARNESS / "store.py"
SELECTOR = HARNESS / "selector.py"
BOARD = HARNESS / "board.py"
CLI = HARNESS / "backlog.py"


@dataclass(frozen=True)
class Mutation:
    name: str
    clause: str  # 끊기는 절 — 이 절이 없으면 무엇이 통과하는가
    path: Path
    original: str
    replacement: str


#: 각 항목은 "그 절이 없으면 통과하는 반례"가 test_gate_graph.py에 실재하는지를 묻는다.
MUTATIONS: list[Mutation] = [
    # ── v2-1 · v2-6 입력 필수 ──
    Mutation(
        "M01-add-inputs-precheck",
        "gates add 가 입력 없는 게이트를 쓰기 전에 거부한다",
        CLI,
        "    if not depends and no_inputs is None:\n",
        "    if False:  # MUTANT\n",
    ),
    Mutation(
        "M02-add-both-precheck",
        "gates add 가 --depends 와 --no-inputs 동시 지정을 거부한다",
        CLI,
        "    if depends and no_inputs is not None:\n",
        "    if False:  # MUTANT\n",
    ),
    Mutation(
        "M03-model-pending-needs-inputs",
        "validate 가 입력 없는 pending 게이트를 잡는다",
        MODELS,
        '        if self.status == "pending" and not has_inputs and not has_reason:\n',
        "        if False:  # MUTANT\n",
    ),
    Mutation(
        "M04-model-both-fields",
        "validate 가 입력·사유 동시 보유를 잡는다",
        MODELS,
        "        if has_inputs and has_reason:\n",
        "        if False:  # MUTANT\n",
    ),
    Mutation(
        "M05-dump-omit-empty",
        "빈 입력 칸은 gates.yaml 에 쓰지 않는다",
        STORE,
        "            if key in _GATE_OMIT_WHEN_EMPTY and not value:\n",
        "            if False:  # MUTANT\n",
    ),
    # ── v2-2 순환 (통합 그래프) ──
    Mutation(
        "M06-edge-gate-input",
        "게이트 입력 간선(입력 태스크 → 게이트)이 그래프에 있다",
        STORE,
        '                link((TASK_NODE, dep), (GATE_NODE, gid), "gate_input")\n',
        "                pass  # MUTANT\n",
    ),
    Mutation(
        "M07-edge-requires-gates",
        "요구 간선(게이트 → 태스크)이 그래프에 있다",
        STORE,
        '                link((GATE_NODE, gid), me, "requires_gates")\n',
        "                pass  # MUTANT\n",
    ),
    Mutation(
        "M08-edge-entry-gate",
        "트랙 진입 게이트 간선(진입 게이트 → 트랙 태스크)이 그래프에 있다",
        STORE,
        '            link((GATE_NODE, track.entry_gate), me, "entry_gate")\n',
        "            pass  # MUTANT\n",
    ),
    Mutation(
        "M09-validate-cycle",
        "validate 가 통합 그래프의 순환을 보고한다",
        STORE,
        "    errors.extend(graph_cycle_errors(backlog, graph))\n",
        "    pass  # MUTANT\n",
    ),
    Mutation(
        "M10-amend-depends-precheck",
        "task amend --depends 가 게이트 경유 고리를 쓰기 전에 거부한다",
        CLI,
        "        cycle = store.cycle_if_linked(backlog, (store.TASK_NODE, dep), "
        "(store.TASK_NODE, task.id))\n",
        "        cycle = None  # MUTANT\n",
    ),
    Mutation(
        "M11-amend-gate-precheck",
        "task amend --gate 가 자기가 여는 게이트의 부착을 거부한다(사고 1)",
        CLI,
        "        cycle = store.cycle_if_linked(backlog, (store.GATE_NODE, gid), "
        "(store.TASK_NODE, task.id))\n",
        "        cycle = None  # MUTANT\n",
    ),
    Mutation(
        "M12-gate-input-cycle-precheck",
        "gates add/amend --depends 가 고리를 닫는 입력을 거부한다",
        CLI,
        "    cycle = store.cycle_if_linked(backlog, (store.TASK_NODE, dep), "
        "(store.GATE_NODE, gate_id))\n",
        "    cycle = None  # MUTANT\n",
    ),
    # ── v2-3 막다른 길 ──
    Mutation(
        "M13-validate-missing-input",
        "validate 가 대장에 없는 게이트 입력을 잡는다",
        STORE,
        '            if verdict == "missing":\n',
        "            if False:  # MUTANT\n",
    ),
    Mutation(
        "M14-validate-cancelled-input",
        "validate 가 pending 게이트의 cancelled 입력을 잡는다",
        STORE,
        '            elif verdict == "cancelled" and gate.status == "pending":\n',
        "            elif False:  # MUTANT\n",
    ),
    Mutation(
        "M15-precheck-missing-input",
        "gates add/amend 가 대장에 없는 입력을 쓰기 전에 거부한다",
        CLI,
        '    if verdict == "missing":\n        return (\n',
        "    if False:  # MUTANT\n        return (\n",
    ),
    Mutation(
        "M16-precheck-cancelled-input",
        "gates add/amend 가 cancelled 입력을 쓰기 전에 거부한다",
        CLI,
        '    if verdict == "cancelled":\n        return (\n',
        "    if False:  # MUTANT\n        return (\n",
    ),
    Mutation(
        "M17-cancel-guard",
        "pending 게이트의 입력 태스크는 cancel 이 거부된다",
        CLI,
        "    if gate_inputs:\n",
        "    if False:  # MUTANT\n",
    ),
    Mutation(
        "M18-rename-carries-gate-input",
        "rename 이 게이트 입력의 구 ID를 새 ID로 옮긴다",
        CLI,
        "        if old.id not in gate.depends_on:\n            continue\n",
        "        if True:  # MUTANT\n            continue\n",
    ),
    # ── v2-7 clear 집행 ──
    Mutation(
        "M19-clear-inputs-done",
        "gates clear 가 입력 미완이면 거부한다",
        CLI,
        "        if unfinished:\n",
        "        if False:  # MUTANT\n",
    ),
    # ── v2-8 FAIL 판정 기록 (사고 3) ──
    Mutation(
        "M20-fail-needs-owner",
        "FAIL 판정은 미종결 소유 태스크 1건 이상을 새로 붙여야 한다",
        CLI,
        "        if not owners:\n            return _fail(\n",
        "        if False:  # MUTANT\n            return _fail(\n",
    ),
    Mutation(
        "M21-fail-owner-must-be-open",
        "이미 끝난 태스크는 FAIL 소유자로 세지 않는다",
        CLI,
        "        owners = [dep for dep in add_deps if backlog.tasks[dep].status not in "
        "TERMINAL_STATUSES]\n",
        "        owners = list(add_deps)  # MUTANT\n",
    ),
    Mutation(
        "M22-fail-attaches-owner",
        "FAIL 소유 태스크가 게이트 입력으로 실제로 붙는다",
        CLI,
        '        gate.depends_on.append(dep)\n        changes.append(f"depends_on +{dep}")\n',
        '        changes.append(f"depends_on +{dep}")  # MUTANT\n',
    ),
    Mutation(
        "M23-verdict-decision-only",
        "--verdict 는 decision 게이트 전용이다",
        CLI,
        '        if gate.kind != "decision":\n',
        "        if False:  # MUTANT\n",
    ),
    Mutation(
        "M24-verdict-judgment-base",
        "FAIL 판정 evidence 는 판정 기준(커밋·PR)을 담아야 한다",
        CLI,
        "        if not _has_judgment_base(args.evidence):\n",
        "        if False:  # MUTANT\n",
    ),
    Mutation(
        "M25-evidence-needs-verdict",
        "amend 의 --evidence 는 --verdict 와 함께만 쓴다",
        CLI,
        "    if args.evidence and verdict is None:\n",
        "    if False:  # MUTANT\n",
    ),
    Mutation(
        "M26-validate-zero-owner-record",
        "validate 가 소유 태스크 0건인 FAIL 기록을 잡는다",
        STORE,
        "        if not owners:\n            errors.append(\n",
        "        if False:  # MUTANT\n            errors.append(\n",
    ),
    Mutation(
        "M27-validate-detached-owner",
        "validate 가 지목됐으나 상류에 없는 소유 태스크를 잡는다(사고 3 대장 상태)",
        STORE,
        "        if detached:\n",
        "        if False:  # MUTANT\n",
    ),
    # ── v2-4 전이 해금 수 ──
    Mutation(
        "M28-unlock-direct-only",
        "해금 수가 게이트 너머까지 끝까지 센다",
        SELECTOR,
        "    return len(store.open_descendant_tasks(backlog, (store.TASK_NODE, task.id), graph))\n",
        "    return sum(1 for o in backlog.tasks.values() if task.id in o.depends_on)  # MUTANT\n",
    ),
    Mutation(
        "M29-unlock-stops-at-finished-task",
        "끝난 태스크 너머는 세지 않는다",
        STORE,
        "                if task.status in TERMINAL_STATUSES:\n",
        "                if False:  # MUTANT\n",
    ),
    Mutation(
        "M30-unlock-stops-at-passed-gate",
        "통과한 게이트 너머는 세지 않는다",
        STORE,
        "                if backlog.gates[nid].passed:\n",
        "                if False:  # MUTANT\n",
    ),
    Mutation(
        "M31-board-same-value",
        "보드 해금 수가 next 정렬과 같은 값이다",
        BOARD,
        "                unlocks=unlocks[task.id],\n",
        "                unlocks=sum(1 for o in backlog.tasks.values() if task.id in o.depends_on),"
        "  # MUTANT\n",
    ),
    # ── v2-5 대기 경로 ──
    Mutation(
        "M32-wait-chain-walks",
        "대기 경로가 게이트 뒤의 여는 작업까지 거슬러 올라간다",
        SELECTOR,
        "        if not waiting:\n",
        "        if True:  # MUTANT\n",
    ),
    Mutation(
        "M33-wait-groups-collected",
        "게이트 대기 태스크가 대기 경로별로 묶여 화면에 실린다",
        SELECTOR,
        "        groups.setdefault(tuple(chain[1:]), []).append(exc.task_id)\n",
        "        pass  # MUTANT\n",
    ),
    Mutation(
        "M34-next-prints-waits",
        "next 가 후보 목록 뒤에 대기 경로를 찍는다",
        CLI,
        "    _print_gate_waits(backlog, excluded)\n    return 0\n",
        "    return 0  # MUTANT\n",
    ),
]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _run_tests() -> tuple[int, str]:
    """대상 테스트 파일을 돌린다 — (종료 코드, 출력 꼬리). 첫 실패에서 멈춘다(-x)."""
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            TEST_FILE,
            "-q",
            "-x",
            "-p",
            "no:randomly",
            "-p",
            "no:cacheprovider",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
    )
    tail = "\n".join((proc.stdout or "").strip().splitlines()[-3:])
    return proc.returncode, tail


def check_anchor(mutation: Mutation) -> str:
    """주입 전 단언 ①②: 치환 대상 정확히 1건 · 치환 결과가 원본과 다름. 원본 텍스트 반환."""
    original = mutation.path.read_text(encoding="utf-8")
    count = original.count(mutation.original)
    if count != 1:
        raise AssertionError(
            f"{mutation.name}: 치환 대상이 {mutation.path.name}에 {count}건 — 정확히 1건이어야 한다"
        )
    mutated = original.replace(mutation.original, mutation.replacement)
    if mutated == original:
        raise AssertionError(f"{mutation.name}: 치환 결과가 원본과 같다 — 주입이 아니다")
    return original


def run(names: set[str] | None = None) -> int:
    targets = [m for m in MUTATIONS if names is None or m.name in names]
    # 대조군 — 무주입 GREEN이 아니면 뮤테이션 결과는 아무것도 말하지 않는다.
    rc, tail = _run_tests()
    print(
        f"대조군(무주입): {'GREEN' if rc == 0 else 'RED'} — {tail.splitlines()[-1] if tail else ''}"
    )
    if rc != 0:
        print("✗ 대조군이 RED — 변별력 판정 불가", file=sys.stderr)
        return 1

    survived: list[str] = []
    backup_dir = Path(tempfile.mkdtemp(prefix="harn174-mut-"))
    for mutation in targets:
        original = check_anchor(mutation)
        raw = mutation.path.read_bytes()
        (backup_dir / f"{mutation.name}.{mutation.path.name}.bak").write_bytes(raw)
        before_sha = _sha(raw)
        try:
            mutation.path.write_text(
                original.replace(mutation.original, mutation.replacement), encoding="utf-8"
            )
            if _sha(mutation.path.read_bytes()) == before_sha:
                raise AssertionError(f"{mutation.name}: 쓰기 후 파일이 원본과 같다 — 주입 실패")
            rc, tail = _run_tests()
        finally:
            mutation.path.write_bytes(raw)
        # 단언 ③ — 원복 바이트 동일
        if _sha(mutation.path.read_bytes()) != before_sha:
            raise AssertionError(f"{mutation.name}: 원복 후 sha256 불일치 — {backup_dir} 참조")
        verdict = "RED" if rc != 0 else "GREEN(생존)"
        last = tail.splitlines()[-1] if tail else ""
        print(f"  {mutation.name}: {verdict} — {mutation.clause} · {last}")
        if rc == 0:
            survived.append(mutation.name)

    print(
        f"\n뮤테이션 {len(targets)}종 · RED {len(targets) - len(survived)} · 생존 {len(survived)}"
    )
    if survived:
        print(f"✗ 생존: {survived} — 그 절의 반례가 픽스처에 없다", file=sys.stderr)
        return 1
    print("✔ 전건 RED · 대조군 GREEN · 주입 적용·원복 바이트 동일 단언 통과")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--list", action="store_true", help="주입 목록만 출력")
    parser.add_argument("--only", action="append", default=None, help="이 이름의 주입만")
    args = parser.parse_args(argv)
    if args.list:
        for mutation in MUTATIONS:
            print(f"{mutation.name}\t{mutation.path.name}\t{mutation.clause}")
        return 0
    return run(set(args.only) if args.only else None)


if __name__ == "__main__":
    sys.exit(main())
