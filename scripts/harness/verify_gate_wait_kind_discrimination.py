#!/usr/bin/env python3
"""HARN-184 게이트 대기 분류의 **변별력** 검증 — 절(節)을 하나씩 끊어 RED를 확인한다.

정상 입력에서 초록인 것은 보호의 증거가 아니다(CLAUDE.md 「보호 장치를 실패 주입 없이
'보호 있음'으로 선언 금지」). 이 스크립트는 `tests/harness/test_gate_wait_kind.py`가 동결하는
절 — ① 단일 판정(inputs · verdict · person) · ② 작업 흐름 그래프 게이트 창 · ③ 보드 라벨·정지
사유·세션 브리핑 · ④ 사람 차례 문구 모듈 전수 등재 — 을 **하네스 코드에서** 하나씩 끊고, 그때마다
그 테스트 파일이 실제로 RED를 내는지 본다.

러너(주입 1건 단언 · `mutated != original` 단언 · 원복 sha256 동일 단언 · 백업 원복)는 HARN-174의
`verify_gate_graph_discrimination.py`를 그대로 재사용한다(HARN-177 하네스와 같은 방식 — 하네스가
셋이 되어도 단언은 한 벌이다).

판정: 대조군(무주입)이 GREEN이고 전 뮤테이션이 RED면 exit 0, 하나라도 어긋나면 exit 1.
실행: `python3 scripts/harness/verify_gate_wait_kind_discrimination.py`
      (pytest가 설치된 인터프리터로)
      `--list` 는 주입 목록만 출력한다.
"""

from __future__ import annotations

import argparse
import sys

from verify_gate_graph_discrimination import BOARD, HARNESS, MODELS, SELECTOR, STORE, Mutation, run

REPORT = HARNESS / "report.py"
GRAPH = HARNESS / "work_graph.py"
PAGE = HARNESS / "work_graph_page.html"
TEST_FILE = "tests/harness/test_gate_wait_kind.py"

#: 각 항목은 "그 절이 없으면 통과하는 반례"가 test_gate_wait_kind.py에 실재하는지를 묻는다.
MUTATIONS: list[Mutation] = [
    # ── ① 단일 판정 — store.gate_wait_kind ──
    Mutation(
        "W01-open-input-is-inputs",
        "미종결 입력이 남은 게이트는 inputs 다(판정할 때가 아니다)",
        STORE,
        "            return GATE_WAITS_INPUTS\n",
        "            pass  # MUTANT\n",
    ),
    Mutation(
        "W02-done-input-is-not-open",
        "끝난 입력은 열린 입력으로 세지 않는다",
        STORE,
        "        if task is not None and task.status not in TERMINAL_STATUSES:\n"
        "            return GATE_WAITS_INPUTS\n",
        "        if task is not None:  # MUTANT\n            return GATE_WAITS_INPUTS\n",
    ),
    Mutation(
        "W03-unrecorded-is-verdict",
        "입력이 끝났는데 판정 기록이 현행이 아니면 verdict 다(사람 차례가 아니다)",
        STORE,
        '    if gate_judgment_state(backlog, gate) in (JUDGMENT_UNRECORDED, "judged:FAIL"):\n',
        "    if False:  # MUTANT\n",
    ),
    Mutation(
        "W04-detached-fail-is-verdict",
        "소유 태스크가 끊긴 현행 FAIL 기록도 verdict 다",
        STORE,
        '(JUDGMENT_UNRECORDED, "judged:FAIL"):\n',
        "(JUDGMENT_UNRECORDED,):  # MUTANT\n",
    ),
    Mutation(
        "W05-passed-gate-is-none",
        "통과한 게이트는 기다리는 것이 없다(None)",
        STORE,
        '    if getattr(gate, "passed", False):\n        return None\n',
        "    if False:  # MUTANT\n        return None\n",
    ),
    # ── ② 작업 흐름 그래프 ──
    Mutation(
        "W06-graph-reads-shared-kind",
        "그래프 게이트 창이 공용 분류를 받는다(자체 판정 금지)",
        GRAPH,
        "            wait_kind = store.gate_wait_kind(backlog, gate)\n",
        "            wait_kind = store.GATE_WAITS_PERSON  # MUTANT\n",
    ),
    Mutation(
        "W07-graph-verdict-state",
        "판정 결과 미기록은 gate_turn('사람 차례')이 아니라 gate_verdict 로 그린다",
        GRAPH,
        '    store.GATE_WAITS_VERDICT: "gate_verdict",\n',
        '    store.GATE_WAITS_VERDICT: "gate_turn",  # MUTANT\n',
    ),
    Mutation(
        "W08-graph-counts-verdict",
        "집계가 gate_verdict 를 따로 센다(합 = 창 수)",
        GRAPH,
        '            "gate_verdict": all_counts.get("gate_verdict", 0),\n',
        "            # MUTANT\n",
    ),
    Mutation(
        "W09-graph-text-summary",
        "--text 요약이 판정 결과 미기록을 사람 차례와 따로 센다",
        GRAPH,
        "        f\"· 사람 차례 {counts['gate_turn']} · "
        "판정 결과 미기록 {counts['gate_verdict']} \"\n",
        "        f\"· 사람 차례 {counts['gate_turn'] + counts['gate_verdict']} \"  # MUTANT\n",
    ),
    Mutation(
        "W10-graph-flow-lines",
        "--text 흐름 줄이 판정 결과 미기록 게이트를 따로 적는다",
        GRAPH,
        '            ("gate_verdict", "판정 결과 미기록"),\n',
        "            # MUTANT\n",
    ),
    Mutation(
        "W11-graph-group",
        "이어진 창이 없는 판정 미기록 게이트도 그룹 프레임에 들어간다(무손실)",
        GRAPH,
        '    if state in ("gate_turn", "gate_verdict", "gate_wait", "human"):\n',
        '    if state in ("gate_turn", "gate_wait", "human"):  # MUTANT\n',
    ),
    Mutation(
        "W12-graph-inputs-reason",
        "입력이 남은 사람 게이트의 사유 문구가 작업 차례를 말한다",
        GRAPH,
        "            elif wait_kind == store.GATE_WAITS_INPUTS:\n",
        "            elif False:  # MUTANT\n",
    ),
    Mutation(
        "W13-page-humans-turn-list",
        "화면 '사람 차례' 목록에 판정 결과 미기록 게이트를 넣지 않는다",
        PAGE,
        "    const human = KEYS.filter(k => ['gate_turn', 'human'].includes(NODES[k].state))\n",
        "    const human = KEYS.filter(k => ['gate_turn', 'gate_verdict', 'human']"
        ".includes(NODES[k].state))\n",
    ),
    Mutation(
        "W14-page-verdict-section",
        "화면이 판정 결과 미기록 게이트를 자기 목록으로 보여 준다",
        PAGE,
        "    const unrecorded = KEYS.filter(k => NODES[k].state === 'gate_verdict').sort();\n",
        "    const unrecorded = [];  // MUTANT\n",
    ),
    Mutation(
        "W15-page-people-chip",
        "'사람 작업' 칩이 게이트 창 세 상태를 전부 센다",
        PAGE,
        "c.human + c.gate_turn + c.gate_verdict + c.gate_wait",
        "c.human + c.gate_turn + c.gate_wait",
    ),
    Mutation(
        "W16-page-filter-group",
        "걸러 보기 '사람 작업' 묶음이 판정 결과 미기록 게이트를 포함한다",
        PAGE,
        "['human', 'gate_turn', 'gate_verdict', 'gate_wait'].includes(n.state)",
        "['human', 'gate_turn', 'gate_wait'].includes(n.state)",
    ),
    # ── ③ 보드 · 정지 사유 · 세션 브리핑 ──
    Mutation(
        "W17-board-card-label",
        "보드 카드의 게이트 대기 라벨이 공용 분류를 따른다",
        BOARD,
        '    if exclusion.reason == "gates":\n',
        "    if False:  # MUTANT\n",
    ),
    Mutation(
        "W18-board-label-priority",
        "여러 게이트가 막으면 사람 차례는 모든 게이트가 사람 차례일 때만",
        BOARD,
        "    for kind in (store.GATE_WAITS_VERDICT, store.GATE_WAITS_INPUTS, "
        "store.GATE_WAITS_PERSON):\n",
        "    for kind in (store.GATE_WAITS_PERSON, store.GATE_WAITS_VERDICT, "
        "store.GATE_WAITS_INPUTS):  # MUTANT\n",
    ),
    Mutation(
        "W19-board-gate-card",
        "보드 게이트 카드가 대기 분류 라벨을 싣는다",
        BOARD,
        '        "wait_label": GATE_WAIT_LABEL.get(wait_kind, ""),\n',
        '        "wait_label": "사람 게이트 대기",  # MUTANT\n',
    ),
    Mutation(
        "W20-board-panel-title",
        "보드 게이트 패널 제목이 미통과 게이트 전부를 '사람 행동 대기'로 부르지 않는다",
        BOARD,
        "`미통과 게이트 ${pending.length}건 — `",
        "`사람 게이트 — 행동 대기 ${pending.length}건 — `",
    ),
    Mutation(
        "W21-stall-verdict",
        "정지 사유가 판정 결과 미기록 게이트를 human_gate 로 접지 않는다",
        SELECTOR,
        '    if verdict:\n        return "gate_verdict", verdict\n',
        '    if False:  # MUTANT\n        return "gate_verdict", verdict\n',
    ),
    Mutation(
        "W22-stall-first-site",
        "게이트만 남은 정체(첫 지점)가 공용 분류를 거친다",
        SELECTOR,
        "    if pending_gates and not other_reasons:\n"
        "        return _gate_stall(backlog, pending_gates)\n",
        "    if pending_gates and not other_reasons:\n"
        '        return "human_gate", pending_gates  # MUTANT\n',
    ),
    Mutation(
        "W23-stall-second-site",
        "선행 대기가 섞인 정체(두 번째 지점)도 공용 분류를 거친다",
        SELECTOR,
        "    if pending_gates and not cancelled_detail:\n"
        "        return _gate_stall(backlog, pending_gates)\n",
        "    if pending_gates and not cancelled_detail:\n"
        '        return "human_gate", pending_gates  # MUTANT\n',
    ),
    Mutation(
        "W24-brief-label",
        "세션 브리핑이 gate_verdict 정지 사유를 사람이 읽는 문구로 낸다",
        REPORT,
        '            "gate_verdict": "게이트 판정 결과 미기록 — '
        '입력은 끝났는데 판정이 게이트에 없다"\n',
        '            "gate_verdict_x": "게이트 판정 결과 미기록 — '
        '입력은 끝났는데 판정이 게이트에 없다"  # MUTANT\n',
    ),
    # ── ④ 사람 차례 문구 모듈 전수 등재 ──
    Mutation(
        "W25-registry-catches-new-surface",
        "사람 차례 문구를 새로 내는 모듈이 등재표 밖에 있으면 RED",
        MODELS,
        'GATE_KINDS: tuple[str, ...] = ("human", "external", "decision")\n',
        'GATE_KINDS: tuple[str, ...] = ("human", "external", "decision")  # 사람 차례 MUTANT\n',
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
