#!/usr/bin/env python3
"""빌드 하네스 CLI — 작업일정 단일 진실 원천(backlog/)의 유일한 조작 창구.

사용:
    python3 scripts/harness/backlog.py status [--json]
    python3 scripts/harness/backlog.py next [--n 3] [--layer L] [--subject S] [--track T]
    python3 scripts/harness/backlog.py start <id> [--session <branch>]
                                                 [--no-remote | --ignore-remote-claim]
    python3 scripts/harness/backlog.py done <id> --artifact <PR/커밋> [--artifact ...]
                                                 [--no-pr <예외사유>]
    python3 scripts/harness/backlog.py block <id> --reason <사유>
    python3 scripts/harness/backlog.py unblock <id>
    python3 scripts/harness/backlog.py review <id>                (in_progress → review)
    python3 scripts/harness/backlog.py cancel <id> --reason <사유>  (todo/blocked → cancelled)
    python3 scripts/harness/backlog.py gates [list]
    python3 scripts/harness/backlog.py gates add <G-id> --title <제목>
                                                 [--kind human|external|decision]
                                                 [--assignee <담당자>] [--remind-after-days N]
    python3 scripts/harness/backlog.py gates clear <G-id> [--as <담당자>] --evidence <근거>
    python3 scripts/harness/backlog.py gates waive <G-id> [--reason <사유>]
    python3 scripts/harness/backlog.py amend <id> --reason <사유>
      [--acceptance ...] [--gate <G-id>] [--remove-gate <G-id>] [--track ...]
      [--depends <full-id>] [--remove-depends <full-id>] [--notes-replace <구문자> <신문자>]
      [--priority N] [--artifact <PR/커밋>] [--path <glob>] [--title <제목>]
  python3 scripts/harness/backlog.py add --id ... --title ... --track ... --stage ... (상세는 -h)
    python3 scripts/harness/backlog.py validate [--quiet]
    python3 scripts/harness/backlog.py brief [--format hook]
    python3 scripts/harness/backlog.py check-stop        (Stop 훅 전용 — stdin JSON)
    python3 scripts/harness/backlog.py seed [--force]    (최초 1회 초기 시딩)

종료 코드: 0 정상 / 1 거부(규칙 위반) / 2 Stop 훅 차단 신호 / 3 환경 오류
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dep_declaration
import pathscope
import remote_claims
import report
import ruleset_drift
import selector
import similar
import store
from models import (
    EOS_PRIORITIES,
    GATE_KINDS,
    OWNERS,
    STATUS_TRANSITIONS,
    TASK_ID_RE,
    TERMINAL_STATUSES,
    Backlog,
    Gate,
    Task,
)
from seed_data import build_seed


def _today() -> str:
    return date.today().strftime("%Y-%m-%d")


def _load(root: Path):
    backlog, schema_errors = store.load_backlog(root)
    return backlog, schema_errors


def _fail(message: str, code: int = 1) -> int:
    print(f"❌ {message}", file=sys.stderr)
    return code


# ── 전이 거부의 해소 경로 안내 (HARN-86) ────────────────────────────────────
# 거부는 장애물이 아니라 판정이다(CLAUDE.md 프로세스·안내). 다만 "허용 목록"만 내는
# 거부는 *전이표를 이미 아는 사람*에게만 유용하다 — 안내자가 규칙을 모른 채 런북에
# 명령을 적으면 그 런북은 실행 시점에 exit 1로 공전한다(2026-09-07 실측: LIC-07의
# done 안내가 todo→done 거부로 왕복 1회 낭비). 그래서 거부가 **해소 경로 자체**를
# 함께 낸다 — 안내자가 규칙을 몰라도 실행자가 막히지 않게. "고칠 수 없는 위반을
# 지적하는 게이트는 사람이 게이트를 끄게 만든다"(HARN-52 등재 사유)의 같은 축이다.
_CLI = "python3 scripts/harness/backlog.py"


# 전이표가 허용하는 전이가 곧 **실행 가능한** 전이는 아니다 (Codex P2 · PR #1067).
# `cmd_start`는 전이 검사를 통과한 뒤 `selector.classify_todo`를 부르고, 그것이 session을
# 보유한 태스크를 `claimed`로 거부한다(selector.py:206). 그래서 session을 든 채 in_progress로
# 가는 홉은 전이표상 합법이어도 반드시 exit 1이다. 그래서 경로 탐색을 (상태, session 보유)
# 쌍 위에서 한다: 최단이 아니라 **실행 가능한 것 중 최단**을 고른다.
#
# (HARN-95 — 2026-09-10) 이 모델이 실측으로 잡은 진짜 결함 2건은 **모델을 정확히 하는 것을
# 넘어 근본 원인을 고쳤다**(경로를 우회하는 것으로 끝내지 않았다):
#   ⓐ `cmd_unblock`이 원격 claim만 걷고 `task.session`은 비우지 않아, in_progress→todo
#      직행(unblock) 뒤의 `start`가 여전히 claimed로 거부됐다 — "더 짧은 경로가 깨진
#      경로"였다. `cmd_unblock`도 `cmd_block`처럼 session을 비우도록 고쳐 이제 직행이
#      실제로 통한다(아래 `_HOP_FREES_SESSION`에 `todo`도 포함).
#   ⓑ `review`의 비-done 출구가 `in_progress` 하나뿐인데 그 홉은 session 보유 시 항상
#      거부되고 review에서 나가는 다른 전이가 없어, review 태스크는 done 말고 나갈 길이
#      없는 막다른 길이었다(재작업·PR 폐기 시 대장 손편집 말고는 방법이 없었다).
#      `models.py`에 `review → blocked` 엣지를 추가했다 — `cmd_block`은 이미 어느
#      상태에서든 session을 비우고 blocked로 내리는 범용 동사라 새 코드가 필요 없었다.
# 두 수정을 합치면 이 그래프에서 session이 원인이 되어 전 구간이 막히는 (출발, 도착) 쌍이
# 0건이 된다(전수 스캔 — `TestNoSessionCausedDeadEnds`). 그래도 이 (상태, session) 모델
# 자체는 남긴다 — review→in_progress 직행은 여전히 session 보유 시 거부되므로(review는
# 여전히 in-flight) 세션 인지 경로 탐색이 계속 필요하다.
_HOP_NEEDS_FREE_SESSION = "in_progress"  # start — classify_todo의 claimed 검사
# block과 unblock 둘 다 session을 비운다 — (HARN-95) `unblock`은 이전에는 원격 claim만
# 걷고 로컬 `task.session`은 그대로 둬서 in_progress→todo 직행이 session을 든 todo를
# 만들었다(그 뒤 start가 claimed로 거부). `cmd_unblock`을 `cmd_block`과 같은 계약으로
# 맞췄으므로(todo = 아무도 안 쥔 상태) 여기도 함께 넓힌다.
_HOP_FREES_SESSION = frozenset({"blocked", "todo"})


def _hop_is_executable(target: str, session_held: bool) -> bool:
    """이 홉의 CLI 명령이 지금 상태에서 실제로 성공하는가."""
    return not (target == _HOP_NEEDS_FREE_SESSION and session_held)


def _session_after(target: str, session_held: bool) -> bool:
    """홉을 밟은 뒤의 session 보유 상태.

    `block`·`unblock`(HARN-95 이후)은 비우고(`task.session = None`), `start`는 채운다.
    `review`(HARN-20)는 보존한다 — 여전히 in-flight라는 뜻이므로 `session_held` 그대로.
    """
    if target in _HOP_FREES_SESSION:
        return False
    if target == _HOP_NEEDS_FREE_SESSION:
        return True
    return session_held


def _transition_route(source: str, target: str, *, session_held: bool) -> list[str] | None:
    """source → target **실행 가능한** 최단 경로(source 제외 경유 상태). 없으면 None.

    (상태, session 보유) 쌍 위의 BFS다 — 상태만으로 탐색하면 실행 불가한 홉을 최단이라는
    이유로 고른다. `session_held`는 호출부가 실제 태스크에서 읽어 넘긴다(가정 금지).
    `seen`을 enqueue 시점에 채우므로 같은 쌍을 두 번 거치는 경로는 나오지 않는다.
    """
    if source == target:
        # 같은 상태로의 "이동"은 경로가 아니라 무의미다 — 빈 리스트를 돌려주면 호출부가
        # 그것을 0단계 경로로 렌더해 **명령이 하나도 없는 안내**를 낸다(2026-09-08 실측:
        # 세션이 죽은 in_progress 태스크에 start를 걸면 "해소 경로 (0단계): in_progress").
        # 순환(같은 상태로 되돌아오는 최단 고리)이 필요하면 _transition_cycle이 따로 낸다.
        return None
    seen = {(source, session_held)}
    queue: deque[tuple[str, bool, list[str]]] = deque([(source, session_held, [])])
    while queue:
        node, held, path = queue.popleft()
        for nxt in STATUS_TRANSITIONS.get(node, ()):
            if not _hop_is_executable(nxt, held):
                continue
            nxt_held = _session_after(nxt, held)
            if (nxt, nxt_held) in seen:
                continue
            step = [*path, nxt]
            if nxt == target:
                return step
            seen.add((nxt, nxt_held))
            queue.append((nxt, nxt_held, step))
    return None


def _transition_cycle(status: str, *, session_held: bool) -> list[str] | None:
    """status를 떠났다가 **다시 status로** 돌아오는 최단 고리. 없으면 None.

    쓰임: 이미 그 상태인 태스크에 같은 전이를 걸었을 때(예: 세션이 죽은 `in_progress`
    태스크의 재착수). 전이표는 자기 자신으로의 전이를 열지 않으므로 한 바퀴 돌아야 한다.

    선정 기준은 두 단계다. **1차는 실행 가능성** — 실행 불가한 홉은 후보에서 제외한다
    (`_hop_is_executable`). `in_progress` 재진입은 (HARN-95 이후) 2단계 `unblock`→`start`가
    직접 실행된다 — `unblock`이 이제 session을 비우므로 뒤따르는 `start`가 claimed로
    거부되지 않는다(HARN-95 이전에는 이 홉이 거부돼 3단계 `block`→`unblock`→`start`를
    골라야 했다). **2차는 동률일 때 `todo` 경유** — session이 없어 두 후보가 다 도는 경우
    `review` 경유는 원격 claim을 유지하고 `todo` 경유(`unblock`)는 해제한다. 같은 상태로의
    재진입은 앞 홀더가 사라졌다는 뜻이므로 자리를 비우는 쪽이 옳다.
    """
    best: list[str] | None = None
    for first in sorted(STATUS_TRANSITIONS.get(status, ()), key=lambda st: st != "todo"):
        if not _hop_is_executable(first, session_held):
            continue
        rest = _transition_route(first, status, session_held=_session_after(first, session_held))
        if rest is None:
            continue
        candidate = [first, *rest]
        if best is None or len(candidate) < len(best):
            best = candidate
    return best


def _status_command(task: Task, status: str) -> str:
    """목표 status로 가는 CLI 한 줄.

    `--as <owner>` 표기는 owner 거부 메시지(HARN-06, cmd_start·cmd_done)가 이미 쓰는
    형식을 그대로 재사용한다 — 새 어휘를 만들지 않는다. `--as`를 받는 것은 start·done
    두 명령뿐이므로 나머지 홉에는 붙이지 않는다(붙이면 argparse가 거부한다).
    `<증적>`·`<사유>`는 그 명령의 required 인자 자리이며, 안내를 보는 사람이 원래
    알고 있는 값이다(앞 명령이 만들어 내는 값이 아니다 — CLAUDE.md 자리표시자 규칙).
    """
    as_flag = f" --as {task.owner}" if task.owner != "claude" else ""
    commands = {
        "in_progress": f"{_CLI} start {task.id}{as_flag}",
        "review": f"{_CLI} review {task.id}",
        "done": f"{_CLI} done {task.id}{as_flag} --artifact <증적>",
        "blocked": f"{_CLI} block {task.id} --reason '<사유>'",
        "cancelled": f"{_CLI} cancel {task.id} --reason '<사유>'",
        "todo": f"{_CLI} unblock {task.id}",
    }
    return commands[status]


def _blocked_by_session_note(task: Task, new_status: str, session_held: bool) -> str:
    """실행 가능한 경로가 없을 때, 그 원인이 session 보유인지 구조인지 가려 말한다.

    없는 경로를 지어내지 않는 것만으로는 부족하다 — 왜 없는지를 말하지 않으면 읽는 사람이
    전이표를 뒤지다 "표에는 있는데?"에서 멈춘다. 실제로 그 경로는 표에는 있고 CLI로만 막힌다.
    """
    if not session_held:
        return ""
    if _transition_route(task.status, new_status, session_held=False) is None:
        return ""  # session을 비워도 못 간다 — 구조적 부재이므로 호출부의 설명이 맞다
    return (
        f"\n  실행 가능한 해소 경로 없음 — 전이표에는 '{task.status}' → … → '{new_status}' 경로가 "
        f"있으나 그 경로가 `start`를 지나고, 이 태스크는 session('{task.session}')을 들고 있어 "
        f"`start`가 claim 검사에서 거부한다(selector.classify_todo). "
        f"'{task.status}'에서는 session을 비우는 전이(`block`)가 전이표에 없어 우회로도 없다. "
        f"→ 갈 수 있는 곳: {list(STATUS_TRANSITIONS.get(task.status, ())) or '없음'} "
        f"(세션 소유자 본인이면 그 세션에서 이어서 작업하는 것이 정상 경로다)"
    )


def _transition_guidance(task: Task, new_status: str) -> str:
    """거부에 덧붙일 해소 경로 블록 — 그대로 붙여 넣을 수 있는 명령 목록."""
    held = bool(task.session)
    if new_status == task.status:
        # 이미 그 상태다. "0단계 경로"를 내는 것은 안내가 아니라 위장이다 — 답처럼 보이는데
        # 실행할 것이 없다. 무엇이 사실인지 말하고, 재진입이 필요한 경우의 고리만 준다.
        head = f"\n  이미 '{task.status}' 상태다 — 이 명령이 바꿀 것이 없다."
        cycle = _transition_cycle(task.status, session_held=held)
        if cycle is None:
            return head + _blocked_by_session_note(task, task.status, held)
        lines = [
            head,
            f"\n  같은 상태로 **다시** 들어가려면 (예: 세션이 끊긴 태스크의 재착수) "
            f"({len(cycle)}단계): {' → '.join([task.status, *cycle])}",
        ]
        lines += [f"\n    {i}) {_status_command(task, st)}" for i, st in enumerate(cycle, 1)]
        return "".join(lines)
    route = _transition_route(task.status, new_status, session_held=held)
    if route is None:
        # 현행 전이표에서 도달 불가는 곧 "출발이 종결 상태"다. 그래도 종결 여부를
        # 따로 묻는다 — 전이표가 바뀌어 다른 도달 불가 쌍이 생겨도 없는 사실을
        # 단정하지 않기 위해서다(모르면 모른다고 — CLAUDE.md AI·신뢰).
        if task.status in TERMINAL_STATUSES:
            return (
                f"\n  해소 경로 없음 — '{task.status}'은(는) 종결 상태이며 나가는 전이가 없다. "
                f"후속 작업은 새 태스크로 등재한다: {_CLI} add ... "
                f"(대장 YAML 손편집으로 되돌리지 않는다 — CLAUDE.md 거부 우회 금지)"
            )
        note = _blocked_by_session_note(task, new_status, held)
        if note:
            return note
        return (
            f"\n  해소 경로 없음 — 전이표에 '{task.status}'에서 '{new_status}'로 가는 "
            f"경로가 없다(models.py STATUS_TRANSITIONS 확인)"
        )
    chain = " → ".join([task.status, *route])
    lines = [f"\n  해소 경로 ({len(route)}단계): {chain}"]
    lines += [f"\n    {i}) {_status_command(task, status)}" for i, status in enumerate(route, 1)]
    return "".join(lines)


def _transition(task: Task, new_status: str) -> str | None:
    """상태 전이 검사 — 허용되지 않으면 오류 메시지 반환.

    거부 메시지에는 항상 해소 경로가 붙는다. 정상 전이는 None을 돌려주므로 안내
    문자열이 나올 자리가 구조적으로 없다 — 성공/실패가 같은 화면을 내면 그 안내는
    변별력이 0이고, 변별력 없는 안내는 위장이다(CLAUDE.md 2026-07-17).
    """
    allowed = STATUS_TRANSITIONS.get(task.status, ())
    if new_status not in allowed:
        return (
            f"{task.id}: {task.status} → {new_status} 전이 불가 "
            f"(허용: {list(allowed) or '없음(종결 상태)'})"
            f"{_transition_guidance(task, new_status)}"
        )
    return None


def _append_note(original: str, reason: str, tag: str) -> str:
    """사유를 원 notes 뒤에 append — 원문을 지우지 않는다 (HARN-20).

    구 구현(`task.notes = args.reason`)은 태스크의 발견 경위·설계 근거를 호출마다
    통째로 덮어써 데이터 손실을 냈다(2026-08-10 통합점검 실측 — blocked 4건 전건
    원 notes 소실). append 방식은 원문 뒤에 `[tag YYYY-MM-DD] 사유`를 이어붙여
    이력을 누적한다 — unblock 이후에도 "왜 한번 막혔었는지"가 notes에 남는다.
    """
    stamp = f"[{tag} {_today()}] {reason}"
    if not original.strip():
        return stamp
    return f"{original}\n\n{stamp}"


# ── PR 증적 게이트 (HARN-23) ────────────────────────────────────────────────
# 규칙 정본은 CLAUDE.md "✅ 절대 원칙 → 완료·병합": 산출물이 있으면 요청 없이 PR을 연다.
# 여기는 그 규칙의 *집행 지점*이다 — 정본화만 하고 집행을 빠뜨리면 규칙은 세션 기억에만
# 의존하게 되고, 이 저장소는 그 실패를 이미 겪었다(미병합 고립 4회차·미머지 브랜치 19건).
#
# 판정은 "artifact 문자열에 PR 참조가 있는가" 하나뿐이다. 스쿼시 머지 커밋 메시지의
# `(#758)` 관례를 그대로 수용하므로 머지된 커밋 해시 증적도 손댈 필요 없이 통과한다.
#
# 한계(의도적): PR의 *실재*는 확인하지 않는다 — `#999` 같은 유령 번호도 통과한다.
# GitHub API 조회는 오프라인·프록시 환경에서 fail-open이 되고, 상시 실패하는 보호는
# 보호가 아니다(CLAUDE.md 금기). 이 게이트가 막는 것은 *망각*이지 *위조*가 아니다.
_PR_REFERENCE_RE = re.compile(r"#\d+|/pull/\d+")

# PR 없이 done을 허용하는 예외 4종 (2026-08-11 Kiki 지정 — 이외의 사유로 보류 금지).
# 자유 서술을 받지 않고 choices로 강제한다: 사유를 적을 수 있으면 무엇이든 사유가 된다.
NO_PR_REASONS: tuple[str, ...] = (
    "investigation",  # 조사·계획 전용 — 코드·문서 산출물이 없음
    "incomplete",  # 미완 또는 사람 게이트 대기 — 아직 열 PR이 아님
    "ci-red",  # CI 적색 — 먼저 고친다
    "kiki-hold",  # Kiki의 명시적 보류 지시
)


def _reason_created_declarations(
    backlog: object, task_id: str, before: set[tuple[str, str]]
) -> list[object]:
    """이 명령의 `--reason`이 **새로** 만든 의존 선언 위반 (HARN-53).

    `--reason`은 notes에 append되고 notes는 의존 선언 스캐너의 입력이다. 그래서 정정·차단
    사유가 선행 어구와 태스크 ID를 한 문장에 담으면 그 인용이 새 선언이 된다(실측 2건).
    notes는 append 전용이라 기록된 뒤에는 되돌릴 CLI 경로가 없으므로 **쓰기 전에** 막는다.

    *기존* 위반은 이 명령의 책임이 아니다 — 그것까지 막으면 위반 하나가 대장에 있는 동안
    그 태스크의 모든 정정이 봉쇄되고, 게이트가 자기 정정 경로를 막게 된다.
    """
    tasks = getattr(backlog, "tasks", {})
    return [
        f
        for f in dep_declaration.find_undeclared_dependencies(tasks)
        if f.task_id == task_id and (f.task_id, f.referenced) not in before
    ]


def _fail_on_reason_feedback(
    backlog: object,
    task_id: str,
    before: set[tuple[str, str]],
    *,
    flag: str = "--reason",
    appended: bool = True,
    hint: str = "",
) -> int:
    """새 선언이 생겼으면 stderr에 근거를 찍고 exit 1 — 호출부는 이 값을 그대로 반환한다.

    `flag`는 그 문구를 실제로 넘긴 인자 이름이다 — `block`·`amend`는 `--reason`, `add`는
    `--notes`. 잘못된 플래그를 지목하면 사람이 없는 인자를 고치려다 왕복을 태운다.

    `appended`는 그 문구가 *이미 기록됐는지*를 가른다. `block`·`amend`는 append 후 검사라
    "기록된 뒤에는 되돌릴 수 없다"가 참이지만, `add`는 **저장 전** 검사라 아직 아무것도
    쓰이지 않았다(HARN-71) — 그 차이를 안내가 정직하게 말해야 사람이 대장 상태를 오해하지
    않는다.

    hint: 되먹임이 `--reason` 외의 축에서도 생길 수 있는 호출부(amend의 depends 제거·notes
    치환 — HARN-67)가 그 가능성을 덧붙인다. 없으면 종전 문구 그대로.
    """
    created = _reason_created_declarations(backlog, task_id, before)
    if not created:
        return 0
    for f in created:
        print(f"  · {f.render()}", file=sys.stderr)  # type: ignore[attr-defined]
    tail = (
        "(notes는 append 전용이라 기록된 뒤에는 되돌릴 수 없다)"
        if appended
        else "(아직 대장에 쓰이지 않았다 — 이 명령은 아무것도 남기지 않고 멈췄다)"
    )
    return _fail(
        f"{task_id}: {flag} 문구가 새 의존 선언을 만든다 — 선행 어구와 태스크 ID가 "
        f"한 문장에 함께 오지 않게 고치거나, 실제 선행이면 `--depends <full-id>`를 함께 "
        f"주고 다시 실행하라{tail}." + (f" {hint}" if hint else "")
    )


def _has_pr_reference(artifacts: list[str]) -> bool:
    """증적 목록 중 하나라도 PR 참조(`#12`·`/pull/12`)를 담고 있는가."""
    return any(_PR_REFERENCE_RE.search(a) for a in artifacts)


# `done --no-pr <사유>`가 notes에 남기는 마커와, 그 사후 해소 마커 (HARN-57 ②).
# 해소 마커는 `[PR 보류 해소 …]`라 `_NO_PR_HOLD_RE`(사유 자리에 날짜가 오는 형태)에
# 걸리지 않는다 — '해소'는 숫자가 아니므로 정규식이 두 마커를 구조적으로 가른다.
_NO_PR_HOLD_TAG = "PR 보류"
_NO_PR_RESOLVED_TAG = "PR 보류 해소"
_NO_PR_HOLD_RE = re.compile(r"\[PR 보류 \d{4}-\d{2}-\d{2}\][ \t]*(\S+)")


def _pending_no_pr_reason(notes: str) -> str | None:
    """아직 해소되지 않은 `--no-pr` 보류 사유. 없으면 None (HARN-57 ②).

    **3상태를 접지 않는다**: "보류 마커가 없다"(None)와 "마커는 있는데 사유를 못 읽었다"는
    다른 상태다. 후자는 `'사유 미상'`을 돌려준다 — 모르는 것을 '없음'으로 접으면 사후 해소
    기록 자체가 조용히 사라진다(모른다 ≠ 아니다).
    """
    if _NO_PR_RESOLVED_TAG in notes:
        return None  # 이미 해소가 기록됐다 — 중복 기록은 대장 소음이다
    if f"[{_NO_PR_HOLD_TAG} " not in notes:
        return None
    matches = _NO_PR_HOLD_RE.findall(notes)
    return matches[-1] if matches else "사유 미상"


def _reject_meaningless(task_id: str, axis: str, raw: str) -> str | None:
    """무의미 입력 3종(빈 문자열·공백만·자기 id) 판정 — 사유 문자열이거나 None (HARN-57 ③).

    빈 문자열과 공백만을 **다른 메시지로** 가른다: 셸 변수가 비어 전달된 경우와 공백이 섞여
    전달된 경우는 사람이 고칠 지점이 다르다. 한 메시지로 접으면 진단이 사라진다.

    4번째 축인 '기존과 동일한 값'은 여기서 보지 않는다 — 비교 대상이 필드마다 다르므로
    (리스트 포함 · 스칼라 일치 · 집합 일치) 각 호출부가 자기 축의 메시지로 판정한다.
    """
    if raw == "":
        return f"{task_id}: 빈 {axis} 값은 받지 않는다 (인자가 비어 전달됐는지 확인하라)"
    if not raw.strip():
        return f"{task_id}: {axis} 값이 공백 문자뿐이다 — 실제 내용을 지정하라"
    if raw.strip() == task_id:
        return (
            f"{task_id}: {axis}에 자기 태스크 id를 넣을 수 없다 — "
            "자기 자신을 가리키는 값은 아무것도 말하지 않는다"
        )
    return None


# ── 판정 기준 게이트 (HARN-68) ──────────────────────────────────────────────
# 규칙 정본은 CLAUDE.md "미머지 존재를 '충족'으로 단정 금지"(2026-09-06 등재).
# 여기는 그 규칙의 **게이트 clear 축** 집행 지점이다.
#
# 판정은 시점에 종속된다. "그 산출물이 있다"는 *언제의 트리에서* 봤느냐에 따라 참이거나
# 거짓이며, 기준 시점이 없는 판정은 재현할 수 없고 재현 불가한 판정은 며칠 뒤 조용히
# 거짓이 된다. 사고 경위: 2026-09-05 Gate 0 검토가 **미머지** PR #986을 Gate 0-B 근거로
# 달았고, 같은 세션의 "고아 3건 소유자 부여 완료" 보고도 셋 다 미머지였다 — main 기준
# 그날의 실제 변화는 하나뿐이었다.
#
# 그래서 evidence에 **기준을 가리키는 것**(커밋 해시 또는 PR 참조)을 요구한다. sha256
# 같은 긴 해시도 받는다(문서 §정규화 해시를 증적으로 쓴 선례 — G0 검증설계 동결).
# 경계에 `\b`를 쓰면 안 된다: 파이썬 정규식의 `\w`는 유니코드라 **한글도 단어문자**이므로
# "커밋 fbbcc53에"처럼 한글이 바로 붙는 흔한 표기에서 경계가 성립하지 않는다(실측: 기존
# 게이트 evidence 1건이 이 이유로 오탐됐다). ASCII 영숫자만 경계로 본다.
_JUDGMENT_BASE_RE = re.compile(r"(?:#\d+|/pull/\d+|(?<![0-9A-Za-z])[0-9a-f]{7,64}(?![0-9A-Za-z]))")


def _has_judgment_base(evidence: str) -> bool:
    """evidence가 판정 기준(커밋 해시·PR 참조)을 담고 있는가."""
    return bool(_JUDGMENT_BASE_RE.search(evidence))


# ── 서브커맨드 ───────────────────────────────────────────────────────────────


def cmd_status(root: Path, args: argparse.Namespace) -> int:
    backlog, schema_errors = _load(root)
    errors = store.validate_backlog(backlog, schema_errors)
    if args.json:
        print(report.render_status_json(backlog, errors, date.today()))
    else:
        print(report.render_status(backlog, errors, date.today()))
    return 0


def _remote_claim_map(root: Path, policy, skip: bool = False) -> tuple[dict[str, str], str]:
    """원격 claim 조회 best-effort — (task_id→branch, 상태). 실패는 빈 dict (fail-open).

    성공 시 스냅샷을 .git/ 캐시에 남긴다 — check-edit 훅이 편집마다
    네트워크를 타지 않고 이 캐시로 교차 세션 겹침을 판정한다.
    """
    if skip or not policy.remote_claims:
        return {}, "disabled"
    claims, status = remote_claims.list_claims(root, with_meta=True)
    if status != "ok":
        return {}, status
    remote_claims.save_cache(root, claims)
    return {c.task_id: (c.branch or "?") for c in claims}, "ok"


def _overlap_block_map(root: Path, backlog, policy) -> dict[str, list[str]] | None:
    """block 모드일 때만 — todo 태스크별 in-flight 겹침 근거 (selector 제외용)."""
    if policy.path_overlap != "block":
        return None
    inflight = [
        t for t in backlog.tasks.values() if t.status in ("in_progress", "review") and t.paths
    ]
    if not inflight:
        return None
    files = pathscope.repo_files(root)
    result: dict[str, list[str]] = {}
    for task in backlog.tasks.values():
        if task.status != "todo" or not task.paths:
            continue
        for other in inflight:
            hit = pathscope.overlap(task.id, task.paths, other.id, other.paths, files)
            if hit:
                result[task.id] = [other.id, hit.describe()]
                break
    return result or None


def cmd_next(root: Path, args: argparse.Namespace) -> int:
    backlog, _ = _load(root)
    policy, _ = store.load_policy(root)
    remote_claimed, remote_status = _remote_claim_map(
        root, policy, skip=getattr(args, "no_remote", False)
    )
    ready, excluded = selector.candidates(
        backlog,
        layer=args.layer,
        subject=args.subject,
        track=args.track,
        remote_claimed=remote_claimed,
        overlap_block=_overlap_block_map(root, backlog, policy),
    )
    if remote_status not in ("ok", "disabled"):
        print(
            f"⚠ 원격 claim 조회 불가({remote_status}) — 로컬 claim 정보만 반영",
            file=sys.stderr,
        )

    # 미머지 done 제외 (HARN-11) — 타 세션이 끝냈으나 머지 전인 태스크는 후보가 아니다.
    # fetch 없이 캐시된 remote-tracking ref만 본다(네트워크 0·실측 12ms): `next`는 자주
    # 도는 조회이고, 확정 지점인 `start`가 fetch=True로 다시 본다(2선).
    if policy.remote_claims and not getattr(args, "no_remote", False) and ready:
        done_map, done_status = remote_claims.scan_remote_done(root, [t.id for t in ready])
        if done_map:
            for task_id, finishers in sorted(done_map.items()):
                print(
                    f"⚠ 후보 제외 {task_id} — 이미 완료(미머지): "
                    f"{', '.join(f.branch for f in finishers)}",
                    file=sys.stderr,
                )
            ready = [t for t in ready if t.id not in done_map]
        elif done_status != "ok":
            print(
                f"⚠ 미머지 done 탐지 불가({done_status}) — 완료분이 섞였을 수 있음",
                file=sys.stderr,
            )
    # 취소된 선행에 차단된 todo (HARN-67 ②) — 후보 0건 여부·--json 여부와 무관하게 **매번**
    # 경고한다. 차단 자체는 옳을 수 있으나(결정 불가 → 차단 유지) 조용한 차단만은 금지다:
    # 선행을 cancel한 세션은 후속이 사라진 것을 못 보고, 다음 세션은 "왜 안 나오지"를 다시
    # 조사한다(2026-09-05 EOS-96 실측). stderr에 내는 이유는 위 두 경고와 같다 — --json의
    # stdout은 기계가 읽으므로 오염하면 안 된다.
    _warn_cancelled_dep_blocks(backlog)
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "id": t.id,
                        "layer": t.layer,
                        "subject": t.subject,
                        "title": t.title,
                        "rationale": selector.selection_rationale(backlog, t),
                    }
                    for t in ready[: args.n]
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if not ready:
        code, detail = selector.stall_reason(backlog, excluded)
        print(f"착수 가능 태스크 없음 — 사유: {code}")
        for item in detail:
            print(f"  · {item}")
        return 0
    shown = min(args.n, len(ready))
    # 분모를 함께 낸다 — "상위 N건"만 적으면 *얼마나* 잘렸는지 안 보이고, 그 출력을
    # 부재 판정("후보에 없다 = 차단됐다")에 쓰는 순간 무효가 된다. 실제로 그렇게 오독해
    # 정상·뮤테이션 양쪽에서 같은 값을 얻은 사고가 있었다(2026-09-01 · CLAUDE.md
    # "검사 명령의 출력을 억제하거나 잘라서 판정 금지" 확장 축). 잘렸을 때는 전건 조회
    # 방법까지 같이 알려 준다 — 규칙을 아는 것과 그 순간 떠올리는 것은 다르다.
    if shown < len(ready):
        print(f"착수 가능 후보 (전체 {len(ready)}건 중 상위 {shown}건):")
    else:
        print(f"착수 가능 후보 (전체 {len(ready)}건):")
    for i, task in enumerate(ready[: args.n], start=1):
        print(f"{i}. {task.id} [{task.layer}/{task.subject}] {task.title}")
        print(f"   사유: {selector.selection_rationale(backlog, task)}")
    if shown < len(ready):
        print(
            f"\n※ {len(ready) - shown}건이 표시되지 않았다 — 특정 태스크가 후보인지"
            f" 판정하려면 전건 조회: backlog.py next --n {len(ready)} --json",
        )
    return 0


def _warn_cancelled_dep_blocks(backlog: object) -> None:
    """취소된 선행에 차단된 todo 태스크마다 정정 명령을 실은 경고 1줄 — stderr (HARN-67 ②).

    기존 "⚠ 후보 제외 … 이미 완료(미머지)" 경고와 같은 자리·같은 형식이다. 정정 명령을
    같이 싣는 이유: 규칙을 아는 것과 그 순간 떠올리는 것은 다르다(next의 전건 조회 안내와
    같은 원칙).

    왜 `excluded`(classify_todo 결과)가 아니라 대장을 직접 훑는가: classify는 owner·트랙
    게이트 제외를 먼저 돌려주므로 사람 소유·E축 태스크의 취소 선행은 `deps_cancelled`로
    나오지 않는다 — 그 태스크는 영구 차단인데 경고 0건인 침묵 상태가 정확히 그 경로에서
    재현됐다(PR #1025 Codex P2-2). status/brief 요약이 쓰는 `cancelled_dependency_blocks`와
    같은 계산을 쓴다(단일 진실 원천). --layer/--subject 필터와 무관하게 전건이다.
    """
    for task, deps in selector.cancelled_dependency_blocks(backlog):
        print(
            f"⚠ 후보 제외 {task.id} — 취소된 선행 {', '.join(deps)}에 차단됨 · 정정: "
            f"backlog.py amend {task.id} --remove-depends {deps[0]} --reason '...'",
            file=sys.stderr,
        )


def cmd_start(root: Path, args: argparse.Namespace) -> int:
    backlog, _ = _load(root)
    task = backlog.tasks.get(args.id)
    if task is None:
        return _fail(f"태스크 '{args.id}' 없음")
    error = _transition(task, "in_progress")
    if error:
        return _fail(error)
    # 사람-소유 태스크 기입 경로(HARN-06): 소유자 본인이 `--as <owner>`를 명시하면
    # owner 제외만 건너뛴다(deps·게이트·claim 검사는 동일). next 후보 계산은 불변.
    as_owner = getattr(args, "as_owner", None)
    if as_owner is not None and as_owner != task.owner:
        return _fail(f"{task.id}: --as {as_owner} 불일치 — 이 태스크의 owner는 '{task.owner}'")
    human = as_owner is not None and as_owner == task.owner
    exclusion = selector.classify_todo(backlog, task, allow_human_owner=human)
    if exclusion is not None:
        message = f"{task.id} 착수 거부 — {exclusion.reason}: {exclusion.detail}"
        if exclusion.reason == "owner":
            # 거부→소유자 이관 규칙(CLAUDE.md 프로세스·안내)의 CLI 구현 — 우회 대신 안내.
            message += (
                f"\n  사람 소유 태스크 — 소유자 본인이 직접 기입하세요: "
                f"python3 scripts/harness/backlog.py start {task.id} --as {task.owner}"
            )
        return _fail(message)
    session = args.session or store.current_branch(root)
    policy, _ = store.load_policy(root)

    # 원격 claim 스냅샷 — 다른 세션의 in-flight는 로컬 backlog 사본에 안 보이므로
    # (claim은 각 브랜치의 worktree에만 기록) 원격 ref로만 교차 세션 겹침을 알 수 있다
    remote_claimed, _ = _remote_claim_map(root, policy, skip=getattr(args, "no_remote", False))

    # [프리플라이트 0] 미머지 done — 타 세션이 이미 끝냈으나 머지 전인 태스크 (HARN-11).
    # claim 대장은 done 시 release돼 비어 있고 트렁크 사본은 아직 todo라, 다른 어떤
    # 검사도 이걸 못 본다. 되돌리기 비싼 지점이므로 fetch=True로 최신 상태를 본다.
    if policy.remote_claims and not getattr(args, "no_remote", False):
        done_map, done_status = remote_claims.scan_remote_done(root, [task.id], fetch=True)
        finishers = done_map.get(task.id, [])
        if finishers:
            branches = ", ".join(f.branch for f in finishers)
            message = (
                f"{task.id} 착수 거부 — 이미 **완료된** 태스크다(미머지): {branches}\n"
                f"  그 브랜치의 백로그 사본이 status: done — 착수하면 중복 구현이 된다.\n"
                f"  확인: git show origin/<branch>:backlog/tasks/{task.id}.yaml\n"
                f"  그래도 착수해야 하면(예: 그 브랜치가 폐기됨): --ignore-remote-claim"
            )
            if getattr(args, "ignore_remote_claim", False):
                print(
                    f"⚠ 미머지 done 무시하고 진행({branches}) — 중복 구현 위험을 감수합니다",
                    file=sys.stderr,
                )
                store.append_event(root, "start_ignored_unmerged_done", task.id, branches=branches)
            else:
                return _fail(message)
        elif done_status != "ok":
            # 판정 불가를 '완료분 없음'으로 위장하지 않는다 (측정 실패 ≠ 통과)
            print(
                f"⚠ 미머지 done 탐지 불가({done_status}) — 타 세션 완료분을 못 봤을 수 있음",
                file=sys.stderr,
            )

        # [프리플라이트 0.5] 트렁크 의존·게이트 시차 (HARN-91) — classify_todo는 로컬
        # 백로그 사본만 보므로, 내 마지막 fetch 뒤 트렁크에 새로 착지한 의존·게이트(조건이
        # *강화*되는 방향)는 그쪽 판정에 안 보인다. 위 done 스캔이 이미 fetch=True로 최신
        # remote-tracking ref를 받아 뒀으므로 같은 fetch에 편승한다(추가 네트워크 없음).
        # done_status != "ok"면 그 fetch 자체가 실패한 것이라 이 검사도 신뢰할 근거가
        # 없다 — 같은 원인이므로 별도 경고를 내지 않고 위 경고 하나로 묶는다.
        if done_status == "ok":
            drift_result = remote_claims.scan_trunk_task_drift(root, task)
            if drift_result.status == "ok" and drift_result.drift:
                lines = [
                    f"  - {'의존 미충족' if d.kind == 'dep' else '게이트 미통과'}: "
                    f"{d.ref_id} (트렁크 상태: {d.trunk_state})"
                    for d in drift_result.drift
                ]
                message = (
                    f"{task.id} 착수 거부 — 트렁크 사본에 로컬엔 없는 조건이 새로 "
                    f"착지했다(HARN-91):\n"
                    + "\n".join(lines)
                    + f"\n  확인: git show {drift_result.trunk_ref}:backlog/tasks/{task.id}.yaml\n"
                    f"  로컬을 최신화(git fetch && git merge {drift_result.trunk_ref})한 뒤 "
                    f"재시도하거나, 그래도 착수해야 하면: --ignore-remote-claim"
                )
                if getattr(args, "ignore_remote_claim", False):
                    print(
                        f"⚠ 트렁크 의존·게이트 시차 무시하고 진행 — 착수 조건 미충족 위험을 "
                        f"감수합니다: {', '.join(d.ref_id for d in drift_result.drift)}",
                        file=sys.stderr,
                    )
                    store.append_event(
                        root,
                        "start_ignored_trunk_drift",
                        task.id,
                        drift=[f"{d.kind}:{d.ref_id}" for d in drift_result.drift],
                    )
                else:
                    return _fail(message)
            elif drift_result.status != "ok":
                # 판정 불가를 '시차 없음'으로 위장하지 않는다 (측정 실패 ≠ 통과)
                print(
                    f"⚠ 트렁크 의존·게이트 시차 탐지 불가({drift_result.status}) — "
                    f"트렁크에 새로 착지한 조건을 못 봤을 수 있음",
                    file=sys.stderr,
                )

    # [프리플라이트 1] 파일 범위 겹침 — 타 in-flight(로컬 ∪ 원격 claim) paths와 교차
    overlap_error = _check_path_overlap(
        root, backlog, task, policy, remote_claimed=remote_claimed, session=session
    )
    if overlap_error:
        return _fail(overlap_error)

    # [프리플라이트 2] 원격 claim — 로컬 검사 전부 통과 후 마지막 (dangling ref 방지).
    # conflict만 차단, offline/error는 읽기측 교차 세션 탐지(프리플라이트 3)로 폴백.
    remote_status = "disabled"
    if policy.remote_claims and not getattr(args, "no_remote", False):
        result = remote_claims.claim(root, task.id, session)
        remote_status = result.status
        if result.status == "conflict":
            other = result.claim
            detail = f" (세션: {other.branch or '?'}, {other.ts or '시각 불명'})" if other else ""
            if other is not None and other.kind == "block":
                # 차단 홀드는 착수 점유가 아니다 — 해소 경로가 다르므로 그렇게 안내한다.
                # 이 분기가 없으면 "남이 작업 중"으로 읽혀 --force 탈취를 유도한다(HARN-42).
                message = (
                    f"{task.id} 착수 거부 — 다른 세션이 **차단**해 둔 태스크{detail}\n"
                    f"  사유: {other.reason or '(기록 없음)'}\n"
                    f"  해소는 차단 사유를 없앤 뒤 `unblock {task.id}` — "
                    f"claims release --force는 차단 우회이므로 쓰지 않는다"
                )
                return _fail(message)
            message = (
                f"{task.id} 착수 거부 — 다른 세션이 이미 원격 claim{detail}\n"
                f"  본인 claim이 확실하면: claims release {task.id} --force 후 재시도"
            )
            if getattr(args, "ignore_remote_claim", False):
                # 플래그의 사정거리를 명시 — 무엇을 껐는지 착각하게 두지 않는다.
                message += (
                    "\n  ※ --ignore-remote-claim은 *읽기측* 판정만 무시합니다 — "
                    "CAS claim conflict는 확정 신호라 우회 대상이 아닙니다"
                )
            return _fail(message)
        if result.status in ("offline", "error"):
            print(
                f"⚠ 원격 CAS claim 불가({result.status}): {result.message}",
                file=sys.stderr,
            )
            store.append_event(root, "claim_remote_unavailable", task.id, status=result.status)
            # [프리플라이트 3] 읽기측 교차 세션 탐지 (HARN-07) — CAS(쓰기)가 막힌
            # 환경의 2선 방어. HARN-09가 claim을 `harness-claims` 브랜치로 옮겨 CAS를
            # 복구하기 전까지, 이 환경의 프록시는 refs/claims/* push를 403 거부해
            # CAS가 **한 번도 성공하지 못했고** fail-open이 중복 방지를 영구 무력화했다
            # (OPS-07·OPS-12 병렬 구현 사고 2회). 이제 CAS가 1선이지만, 진짜 오프라인·
            # 권한 문제로 실패하는 환경이 남아 있으므로 이 경로는 유지한다.
            # CAS 성공 시에는 돌지 않는다 — 전체 브랜치 fetch(~5초)를 불필요하게 물지 않는다.
            scan = remote_claims.scan_remote_in_progress(root, task.id, session)
            remote_status = f"{result.status}+readscan_{scan.status}"
            # 규칙 A·B로 걸러낸 stale 홀더를 조용히 버리지 않는다 (HARN-08 관측성)
            skipped_summary = _readside_skipped_summary(scan)
            if skipped_summary:
                print(skipped_summary, file=sys.stderr)
                store.append_event(
                    root,
                    "claim_readside_stale_skipped",
                    task.id,
                    trunk=f"{scan.trunk_branch}:{scan.trunk_status or '없음'}"
                    f"({scan.trunk_source})",
                    skipped=[f"{s.branch}:{s.reason}" for s in scan.skipped],
                )
            conflict = _readside_conflict_message(task, scan, result.status)
            if conflict and getattr(args, "ignore_remote_claim", False):
                # [규칙 C] 태스크 단위 세분 우회 — 무엇을 포기하는지 명시하고 이벤트로 남긴다.
                print(_readside_ignore_warning(task, scan), file=sys.stderr)
                store.append_event(
                    root,
                    "claim_readside_ignored",
                    task.id,
                    cas_status=result.status,
                    holders=[f"{h.branch}:{h.session}" for h in scan.holders],
                )
                remote_status += "+ignored"
                conflict = None
            if conflict:
                store.append_event(
                    root,
                    "claim_readside_conflict",
                    task.id,
                    cas_status=result.status,
                    holders=[f"{h.branch}:{h.session}" for h in scan.holders],
                )
                return _fail(conflict)
            # 홀더가 남아 있는데 여기 도달했다면 규칙 C로 무시하고 온 경로다 —
            # 그 경우 '중복 없음'이라고 말하면 거짓말이므로 아래 안내를 내지 않는다.
            if scan.status == "ok" and not scan.holders:
                extra = " (브랜치 수 상한 도달 — 일부만 확인)" if scan.truncated else ""
                unused = (
                    " · --ignore-remote-claim은 무시할 판정이 없어 효과 없음"
                    if getattr(args, "ignore_remote_claim", False)
                    else ""
                )
                print(
                    f"  ↳ 읽기측 교차 세션 탐지로 폴백: 원격 브랜치 {scan.scanned_refs}개에서 "
                    f"중복 in_progress 없음{extra}.{unused}\n"
                    f"    ※ *부분* 방어입니다 — 상대가 브랜치를 push한 뒤에만 보이며 "
                    f"CAS의 원자성은 대체하지 못합니다.",
                    file=sys.stderr,
                )
            elif scan.status != "ok":
                # 침묵 실패 금지 — 폴백까지 실패했으면 '보호 없음'을 명시적으로 말한다.
                print(
                    f"  ↳ 읽기측 교차 세션 탐지도 불가({scan.status}) — "
                    f"로컬 claim만으로 진행합니다.\n"
                    f"    ⚠ 이 착수에는 중복 착수 보호가 전혀 없습니다 "
                    f"(다른 세션이 같은 태스크를 잡고 있어도 알 수 없음): {scan.message}",
                    file=sys.stderr,
                )
                store.append_event(
                    root,
                    "claim_readside_unavailable",
                    task.id,
                    cas_status=result.status,
                    scan_status=scan.status,
                )

    task.status = "in_progress"
    task.session = session
    task.updated = _today()
    store.save_task(root, task)
    # 사람 기입(--as)은 이벤트에 as_owner를 남겨 claude 기입과 대장에서 구분한다(HARN-06).
    start_extra: dict[str, object] = {"session": task.session, "remote": remote_status}
    if human:
        start_extra["as_owner"] = as_owner
    store.append_event(root, "start", task.id, **start_extra)
    print(f"▶ {task.id} 착수 (세션: {task.session}, 원격 claim: {remote_status})")
    print(f"  완료 조건: {task.acceptance or '(acceptance 미정의 — 정의 권장)'}")
    if not task.paths:
        print(
            "  ⚠ paths 미선언 — 겹침 검사에서 제외됩니다. "
            "태스크 YAML에 paths(작업 파일 glob) 선언을 권장",
            file=sys.stderr,
        )
    for warning in task.layer_drift_warnings():
        print(f"  ⚠ {warning}", file=sys.stderr)
    return 0


_SKIP_REASON_HINT = {
    "trunk_not_session": "트렁크는 세션이 아님 — 대장 위생 실패(done 미기입 머지)",
}


def _readside_skipped_summary(scan) -> str | None:
    """규칙 A·B로 홀더에서 제외한 내역 요약 (없으면 None).

    stale을 조용히 버리면 '보호가 안 걸린 것'과 '보호를 껐던 것'이 구분되지 않는다.
    """
    if not scan.skipped:
        return None
    parts = []
    for s in scan.skipped[:5]:
        hint = _SKIP_REASON_HINT.get(
            s.reason, f"{scan.trunk_branch}가 {scan.trunk_status} — 작업이 이미 착륙"
        )
        parts.append(f"origin/{s.branch}(session={s.session}, {s.reason}: {hint})")
    more = f" 외 {len(scan.skipped) - 5}건" if len(scan.skipped) > 5 else ""
    return (
        f"  ↳ stale 홀더 {len(scan.skipped)}건 제외: "
        + " · ".join(parts)
        + more
        + f"\n    (기준 트렁크: {scan.trunk_ref or '?'} "
        f"= {scan.trunk_source}, 태스크 status={scan.trunk_status or '없음'})"
    )


def _readside_ignore_warning(task: Task, scan) -> str:
    """규칙 C(--ignore-remote-claim) 사용 시 경고 — 무엇을 포기하는지 명시."""
    lines = [
        f"⚠ --ignore-remote-claim: {task.id}의 읽기측 교차 세션 판정을 " f"무시하고 착수합니다."
    ]
    for holder in scan.holders[:3]:
        lines.append(
            f"  · 무시된 홀더: origin/{holder.branch} "
            f"(status=in_progress, session={holder.session})"
        )
    if len(scan.holders) > 3:
        lines.append(f"  · … 외 {len(scan.holders) - 3}건")
    lines.append(
        "  포기하는 것: 이 태스크의 중복 착수 보호. 상대 세션이 실제로 살아 있어도 "
        "이 착수는 막히지 않습니다 — 지금부터 중복 구현일 수 있습니다."
    )
    lines.append(
        "  (CAS claim conflict는 이 플래그로 무시되지 않습니다. 보호를 통째로 끄는 "
        "것은 여전히 --no-remote입니다.)"
    )
    if scan.holders:
        lines.append(
            "  상대 브랜치가 정말 죽었는지 확인: "
            f"git log -1 --format='%cr %h %s' origin/{scan.holders[0].branch}"
        )
    return "\n".join(lines)


def _readside_conflict_message(task: Task, scan, cas_status: str) -> str | None:
    """읽기측 탐지 결과 → 착수 거부 메시지 (충돌 없으면 None).

    status가 ok가 아니면 *판정 불가*이므로 거부하지 않는다(호출측이 '보호 없음'을
    별도로 경고한다) — 측정 실패를 '충돌 없음'으로 위장하지 않기 위한 분기다.
    """
    if scan.status != "ok" or not scan.holders:
        return None
    lines = [
        f"{task.id} 착수 거부 — 다른 세션이 이미 in_progress "
        f"(원격 브랜치 읽기 탐지 · CAS claim은 {cas_status})"
    ]
    for holder in scan.holders[:3]:
        lines.append(
            f"  · origin/{holder.branch} 의 backlog 사본: "
            f"status=in_progress, session={holder.session}"
        )
    if len(scan.holders) > 3:
        lines.append(f"  · … 외 {len(scan.holders) - 3}건")
    lines.append(
        "  ※ 이 탐지는 CAS claim(harness-claims 브랜치)이 불가할 때 도는 *부분* 방어입니다 — "
        "상대가 브랜치를 push한 뒤에만 보이며, 원자성은 대체하지 못합니다."
    )
    lines.append(
        f"  트렁크({scan.trunk_branch or '?'})의 이 태스크 status="
        f"{scan.trunk_status or '없음'} — done/cancelled였다면 자동으로 stale 처리됩니다"
        f" (규칙 A)."
    )
    lines.append(
        f"  상대 브랜치가 이미 죽었으면(stale in_progress) 확인 후 이 태스크만 무시: "
        f"git log -1 --format='%cr %h %s' origin/{scan.holders[0].branch} → "
        f"python3 scripts/harness/backlog.py start {task.id} --ignore-remote-claim\n"
        f"  (원격 검사 전체를 끄는 것은 여전히 --no-remote — 보호 범위가 다릅니다)"
    )
    return "\n".join(lines)


def _inflight_tasks(
    backlog, remote_claimed: dict[str, str] | None, session: str | None
) -> list[Task]:
    """in-flight 태스크 = 로컬(in_progress·review) ∪ 원격 claim (내 세션 제외).

    태스크 정의(YAML·paths)는 git으로 전 세션에 공유되지만, 상태(in_progress)는
    claim한 브랜치의 사본에만 있다 — 원격 claim ref가 교차 세션의 유일한 신호다.
    """
    result: dict[str, Task] = {
        t.id: t for t in backlog.tasks.values() if t.status in ("in_progress", "review")
    }
    for tid, branch in (remote_claimed or {}).items():
        if session and branch == session:
            continue  # 내 claim은 겹침 대상 아님
        t = backlog.tasks.get(tid)
        if t is not None and t.id not in result:
            # 로컬 사본에선 todo로 보여도 원격 claim이 있으면 in-flight로 취급
            t_session = t.session or branch
            result[t.id] = t
            if not t.session:
                t.session = t_session  # 경고 메시지용 (저장하지 않음 — 메모리만)
    return list(result.values())


def _overlap_candidates(
    backlog, remote_claimed: dict[str, str] | None, session: str | None, include_todo: bool
) -> list[Task]:
    """겹침 검사 대상 태스크 집합.

    기본적으로 in-flight(in_progress·review) ∪ 원격 claim 을 포함한다.
    include_todo=True면 todo 상태 태스크도 추가해 *등재 시점* 중복 검사가 가능하게 한다.
    """
    candidates = _inflight_tasks(backlog, remote_claimed, session)
    if include_todo:
        seen = {t.id for t in candidates}
        for t in backlog.tasks.values():
            if t.status == "todo" and t.id not in seen and t.paths:
                candidates.append(t)
    return candidates


def _is_inflight_task(task: Task, remote_claimed: dict[str, str] | None) -> bool:
    """원격 claim이 있거나 로컬 상태가 in_progress/review면 in-flight로 본다."""
    if task.status in ("in_progress", "review"):
        return True
    if remote_claimed and task.id in remote_claimed:
        return True
    return False


def _check_path_overlap(
    root: Path,
    backlog,
    task: Task,
    policy,
    remote_claimed: dict[str, str] | None = None,
    session: str | None = None,
) -> str | None:
    """start/add 프리플라이트 — 타 in-flight·todo 태스크와 paths 교차 검사.

    in-flight 겹침: policy.path_overlap 에 따라 warn/block.
    todo    겹침: 항상 warn (등재 시점 중복을 사용자에게 알리되 차단은 안 함).

    warn: stderr 경고 + policy_warn 이벤트 후 진행(None 반환).
    block: 오류 메시지 반환(호출측이 exit 1).
    """
    if policy.path_overlap == "off" or not task.paths:
        return None
    candidates = [
        t
        for t in _overlap_candidates(backlog, remote_claimed, session, include_todo=True)
        if t.id != task.id and t.paths
    ]
    if not candidates:
        return None
    files = pathscope.repo_files(root)
    block_message: str | None = None
    for other in candidates:
        hit = pathscope.overlap(task.id, task.paths, other.id, other.paths, files)
        if hit is None:
            continue
        is_inflight = _is_inflight_task(other, remote_claimed)
        desc = (
            f"{task.id} ↔ {other.id}(세션: {other.session or '?'}) "
            f"파일 범위 겹침 — {hit.describe()}"
        )
        store.append_event(
            root,
            "policy_warn",
            task.id,
            rule="path_overlap",
            other=other.id,
            detail=hit.describe(),
            mode=policy.path_overlap if is_inflight else "warn",
        )
        if is_inflight and policy.path_overlap == "block":
            block_message = (
                f"착수 거부 — {desc}\n  겹침 해소(paths 조정·상대 태스크 완료 대기) 후 재시도"
            )
            continue  # todo 겹침도 경고로 계속 출력
        print(f"⚠ {desc}", file=sys.stderr)
    return block_message


def cmd_done(root: Path, args: argparse.Namespace) -> int:
    backlog, _ = _load(root)
    task = backlog.tasks.get(args.id)
    if task is None:
        return _fail(f"태스크 '{args.id}' 없음")
    if not args.artifact:
        return _fail(f"{task.id}: --artifact <PR/커밋> 필수 (증적 없는 done 금지)")
    # 사람-소유 태스크의 done도 소유자 본인의 `--as <owner>` 명시 필수(HARN-06) —
    # start와 동일한 소유자 확인. claude 태스크에는 --as가 불필요하다(있으면 불일치 검사).
    as_owner = getattr(args, "as_owner", None)
    if as_owner is not None and as_owner != task.owner:
        return _fail(f"{task.id}: --as {as_owner} 불일치 — 이 태스크의 owner는 '{task.owner}'")
    if task.owner != "claude" and as_owner != task.owner:
        return _fail(
            f"{task.id}: 사람 소유 태스크({task.owner}) — 소유자 본인이 직접 기입하세요: "
            f"python3 scripts/harness/backlog.py done {task.id} --as {task.owner} --artifact <증적>"
        )
    # PR 증적 게이트 (HARN-23) — 증적에 PR 참조가 없으면 거부한다.
    # 거부는 장애물이 아니라 판정이다. 다만 예외 4종에 해당하면 `--no-pr <사유>`로
    # 언제든 통과할 수 있으므로 이 게이트가 세션을 볼모로 잡지는 않는다.
    no_pr_reason = getattr(args, "no_pr", None)
    if no_pr_reason is None and not _has_pr_reference(args.artifact):
        return _fail(
            f"{task.id}: 증적에 PR 참조(#12 또는 .../pull/12)가 없습니다 — "
            f"산출물이 있으면 요청 없이 PR을 여는 것이 기본값입니다(CLAUDE.md 완료·병합). "
            f"PR을 열었다면 그 번호를 증적에 담고, 예외라면 사유를 명시하세요: "
            f"--no-pr {{{'|'.join(NO_PR_REASONS)}}} "
            f"(investigation=산출물 없는 조사·계획 / incomplete=미완·게이트 대기 / "
            f"ci-red=CI 적색 / kiki-hold=Kiki 보류 지시)"
        )
    error = _transition(task, "done")
    if error:
        return _fail(error)
    prev_session = task.session
    task.status = "done"
    task.artifacts = list(dict.fromkeys(task.artifacts + args.artifact))
    task.session = None
    if no_pr_reason is not None:
        # PR 없이 종결한 사실을 태스크에 남긴다 — 나중에 "왜 이건 PR이 없지"를
        # 브랜치 고고학으로 되짚지 않아도 되게(미병합 고립 4회차의 실제 비용).
        task.notes = _append_note(task.notes, no_pr_reason, "PR 보류")
    task.updated = _today()
    store.save_task(root, task)
    done_extra: dict[str, object] = {"artifacts": args.artifact}
    if as_owner is not None:
        done_extra["as_owner"] = as_owner
    if no_pr_reason is not None:
        done_extra["no_pr_reason"] = no_pr_reason
    store.append_event(root, "done", task.id, **done_extra)
    _release_remote_claim(root, task.id, prev_session)
    print(f"✔ {task.id} 완료 — 증적: {', '.join(args.artifact)}")
    if no_pr_reason is not None:
        print(f"⚠ PR 없이 완료 — 사유: {no_pr_reason}")
    # 이 완료로 해금된 후속 태스크 안내 (순차 조율의 연결 고리)
    unlocked = [
        t
        for t in backlog.tasks.values()
        if task.id in t.depends_on
        and t.status == "todo"
        and not selector.unmet_dependencies(backlog, t)
    ]
    if unlocked:
        print("해금된 후속 태스크:")
        for t in sorted(unlocked, key=lambda x: x.id):
            gates = selector.unmet_gates(backlog, t)
            suffix = f" (게이트 대기: {gates})" if gates else " — 착수 가능"
            print(f"  · {t.id} {t.title}{suffix}")
    return 0


def cmd_block(root: Path, args: argparse.Namespace) -> int:
    backlog, _ = _load(root)
    task = backlog.tasks.get(args.id)
    if task is None:
        return _fail(f"태스크 '{args.id}' 없음")
    _pre_block_findings = {
        (f.task_id, f.referenced)
        for f in dep_declaration.find_undeclared_dependencies(backlog.tasks)
    }
    error = _transition(task, "blocked")
    if error:
        return _fail(error)
    prev_session = task.session
    task.status = "blocked"
    task.session = None
    task.notes = _append_note(task.notes, args.reason, "차단")  # 덮어쓰지 않고 append (HARN-20)
    # `block --reason`도 notes에 append된다 — amend와 같은 되먹임 위험(HARN-53).
    # `done`·`cancel`은 스캐너가 건너뛰는 상태(done/cancelled)로 바꾸므로 위반을 만들 수 없다.
    if _fail_on_reason_feedback(backlog, task.id, _pre_block_findings):
        return 1
    task.updated = _today()
    store.save_task(root, task)
    handover = bool(getattr(args, "handover", False))
    store.append_event(root, "block", task.id, reason=args.reason, handover=handover)
    if handover:
        # 인계 의도 — 자리를 비운다. 게이트 대기와 달리 "남이 이어받아야" 하는 차단이다.
        _release_remote_claim(root, task.id, prev_session)
        print(f"✖ {task.id} 차단(인계) — {args.reason}")
        print("  · 원격 홀드를 두지 않았다 — 다른 세션이 이 태스크를 착수할 수 있다")
        return 0
    _publish_block_hold(root, task.id, prev_session, args.reason)
    print(f"✖ {task.id} 차단 — {args.reason}")
    return 0


def _publish_block_hold(root: Path, task_id: str, prev_session: str | None, reason: str) -> None:
    """차단을 원격 대장에 게시 — 머지 없이 병렬 세션에 즉시 보이게 (HARN-42).

    구현은 원격 claim을 *해제*했다. 그 결과 차단은 보호를 거는 순간 유일한 교차
    세션 신호를 지웠고, 태스크 YAML이 main에 머지되기까지(CI ~30분 + base 경합)
    다른 세션은 아무 마찰 없이 착수할 수 있었다 — CUR-11 실사고(2026-08-31).

    실패는 침묵하지 않는다(예외 타입·상태를 로그와 이벤트에 남긴다). 게시 실패 시
    차단은 로컬에만 남으므로 **보호가 없는 상태임을 명시**한다 — fail-open을
    "보호 있음"으로 위장하지 않는다(CLAUDE.md 금기).
    """
    policy, _ = store.load_policy(root)
    if not policy.remote_claims:
        return
    branch = prev_session or store.current_branch(root)
    result = remote_claims.hold(root, task_id, branch, reason)
    if result.status == "ok":
        return
    print(
        f"⚠ 원격 차단 홀드 게시 실패({result.status}): {result.message}\n"
        f"  → 이 차단은 **로컬에만** 있습니다. 이 PR이 머지되기 전까지 병렬 세션은 "
        f"{task_id}을(를) 착수할 수 있습니다",
        file=sys.stderr,
    )
    store.append_event(root, "block_hold_failed", task_id, status=result.status)


def cmd_review(root: Path, args: argparse.Namespace) -> int:
    """in_progress → review 전이 (HARN-20) — 구현 완료·검토 대기 상태로 전환.

    review는 여전히 in-flight(원격 claim 유지·session 필드 보존) — done/block과 달리
    세션이 계속 이 태스크를 들고 있다는 뜻이라 `_release_remote_claim`을 부르지 않는다.
    전이표(STATUS_TRANSITIONS)가 `in_progress → review`만 허용하므로 다른 상태에서의
    호출은 `_transition`이 자연히 거부한다.
    """
    backlog, _ = _load(root)
    task = backlog.tasks.get(args.id)
    if task is None:
        return _fail(f"태스크 '{args.id}' 없음")
    error = _transition(task, "review")
    if error:
        return _fail(error)
    task.status = "review"
    task.updated = _today()
    store.save_task(root, task)
    store.append_event(root, "review", task.id)
    print(f"👀 {task.id} 검토 대기 (세션: {task.session or '?'})")
    return 0


def cmd_cancel(root: Path, args: argparse.Namespace) -> int:
    """todo/blocked → cancelled 전이 (HARN-20) — 종결 상태.

    전이표는 `in_progress`에서 `cancelled`로의 직접 경로를 열지 않는다 — 진행 중인
    태스크를 취소하려면 먼저 `block` 또는 `todo`로 내린 뒤 취소해야 한다는 기존 설계를
    그대로 존중한다(우회 아님). cancelled는 종결 상태이므로 block과 동일하게 원격
    claim을 해제한다.
    """
    backlog, _ = _load(root)
    task = backlog.tasks.get(args.id)
    if task is None:
        return _fail(f"태스크 '{args.id}' 없음")
    error = _transition(task, "cancelled")
    if error:
        return _fail(error)
    # 이 태스크를 선행으로 가진 미종결 태스크 (HARN-67 ②) — 취소는 막지 않는다(취소 자체는
    # 정당할 수 있다). 다만 그 후속들은 selector가 취소 선행을 해소로 치지 않으므로 이
    # 순간부터 후보에서 빠진다 — 그 사실을 취소한 사람이 **지금** 보게 한다. in_progress·
    # review도 센다: 진행 중 태스크의 depends_on에 남은 취소 선행은 대장 오염이다.
    dependents = sorted(
        t.id
        for t in backlog.tasks.values()
        if task.id in t.depends_on and t.status not in TERMINAL_STATUSES
    )
    prev_session = task.session
    task.status = "cancelled"
    task.session = None
    task.notes = _append_note(task.notes, args.reason, "취소")  # block과 동일 — 덮어쓰지 않음
    task.updated = _today()
    store.save_task(root, task)
    store.append_event(root, "cancel", task.id, reason=args.reason, blocked_dependents=dependents)
    _release_remote_claim(root, task.id, prev_session)
    print(f"🗑 {task.id} 취소 — {args.reason}")
    if dependents:
        print(
            f"⚠ 이 취소로 {len(dependents)}건이 차단된다: {', '.join(dependents)} · 정정: "
            f"backlog.py amend <id> --remove-depends {task.id} --reason '...'"
        )
    return 0


def _release_remote_claim(root: Path, task_id: str, prev_session: str | None) -> None:
    """done/block 후 원격 claim 해제 — best-effort (실패해도 진행, reap이 나중에 청소)."""
    policy, _ = store.load_policy(root)
    if not policy.remote_claims:
        return
    result = remote_claims.release(root, task_id, prev_session or store.current_branch(root))
    if result.status not in ("ok", "offline"):
        print(
            f"⚠ 원격 claim 해제 실패({result.status}): {result.message} — "
            f"`claims reap`이 이후 청소합니다",
            file=sys.stderr,
        )
        store.append_event(root, "claim_release_failed", task_id, status=result.status)


def cmd_unblock(root: Path, args: argparse.Namespace) -> int:
    """전이표의 모든 `→ todo` 홉이 이 명령을 거친다(blocked→todo가 주 용도지만
    `_status_command`가 in_progress→todo에도 이 명령을 안내한다 — HARN-95).

    `task.session`을 **비운다**(HARN-95 이전에는 원격 claim만 걷고 로컬 session은
    남겼다) — `cmd_block`과 같은 계약: `todo` = 아무도 쥐지 않은 상태. 이전 계약대로
    두면 in_progress→todo 직행(unblock) 뒤의 `start`가 여전히 claimed로 거부돼, 전이표가
    합법으로 표시하는 홉이 실제로는 항상 실패했다(실측 2026-09-08).
    """
    backlog, _ = _load(root)
    task = backlog.tasks.get(args.id)
    if task is None:
        return _fail(f"태스크 '{args.id}' 없음")
    error = _transition(task, "todo")
    if error:
        return _fail(error)
    prev_session = task.session
    task.status = "todo"
    task.session = None
    task.updated = _today()
    store.save_task(root, task)
    store.append_event(root, "unblock", task.id)
    # 차단 홀드도 함께 걷는다 — 안 걷으면 해제된 태스크가 영구 차단으로 보인다(HARN-42)
    _release_remote_claim(root, task.id, prev_session)
    print(f"· {task.id} 차단 해제 → todo")
    return 0


def cmd_gates(root: Path, args: argparse.Namespace) -> int:
    backlog, _ = _load(root)
    if args.gate_action == "list" or args.gate_action is None:
        # HARN-94: 경과일만 찍던 화면을 **처리 상황**으로 바꾼다. 계산·정렬은 report에 한 곳
        # (pending_gate_views) — 여기서 따로 세면 status 화면과 두 숫자가 갈라진다.
        views = report.pending_gate_views(backlog, date.today())
        others = [g for g in backlog.gates.values() if g.status != "pending"]
        overdue_n = sum(1 for v in views if v.overdue)
        print(f"⏳ 대기 중 게이트 {len(views)}건 (독촉 초과 {overdue_n}건) — 급한 순:")
        for view in views:
            gate = view.gate
            # 대기 태스크는 0건도 찍는다 — 줄이 없으면 "0건"과 "안 셌다"를 구분할 수 없다.
            dep = f"대기 태스크 {len(view.dependents)}건"
            if view.dependents:
                dep += f" ({', '.join(view.dependents)})"
            mark = "⚠" if view.overdue else "·"
            print(f"  {mark} {gate.id} [{gate.assignee}/{gate.kind}]")
            print(f"      {view.status_text()} · {dep}")
            print(f"      {gate.title}")
        if others:
            print("✔ 통과/면제:")
            for gate in sorted(others, key=lambda g: g.id):
                # HARN-60: cleared는 주체를 함께 보인다. 미상(None)은 HARN-60 이전 행이며
                # 그대로 '미상'으로 표시한다 — 추정으로 채우지 않는다(날조 금지·acceptance ④).
                by = ""
                if gate.status == "cleared":
                    by = f" [clear 주체: {gate.cleared_by or '미상(HARN-60 이전)'}]"
                print(f"  {gate.id} ({gate.status}){by} {gate.title}")
        return 0

    if args.gate_action == "add":
        return _cmd_gates_add(root, args, backlog)

    if args.gate_action == "show":
        return _cmd_gates_show(args, backlog)

    gate = backlog.gates.get(args.gate_id)
    if gate is None:
        return _fail(f"게이트 '{args.gate_id}' 없음")
    # HARN-60: clear 주체(사람/에이전트)를 대장에 남긴다. 이벤트의 `actor`는 브랜치명이라
    # 신원을 담지 못하고, 스쿼시 머지가 git 저자를 덮으므로 증거는 여기(대장)에 있어야 한다.
    extra: dict[str, object] = {}
    if args.gate_action == "clear":
        if not args.evidence:
            return _fail(f"{gate.id}: clear에는 --evidence <근거> 필수")
        # 판정 기준 게이트 (HARN-68) — evidence가 "언제의 트리로 판정했는가"를 담아야 한다.
        # done의 PR 증적 검사(HARN-23)와 동형이되 탈출구는 **자유 서술**이다: 사람 게이트의
        # 정당한 근거에는 커밋과 무관한 것이 많고(환경 생성·서명·법률 검토·외부 등록),
        # 그 유형을 미리 열거하면 정상 상태에서 거부하는 검사가 된다 — 그러면 사람은
        # 게이트를 끄거나 대장을 손편집하고, 그때는 아무 기록도 남지 않아 더 나빠진다.
        no_base_reason = getattr(args, "no_base", None)
        if no_base_reason is None and not _has_judgment_base(args.evidence):
            return _fail(
                f"{gate.id}: evidence에 판정 기준이 없다 — 커밋 해시나 PR 참조(#12)를 넣어라.\n"
                "  판정은 시점에 종속된다: 기준 없는 판정은 재현할 수 없고, 재현 불가한\n"
                "  판정은 며칠 뒤 조용히 거짓이 된다(CLAUDE.md 미머지 존재를 충족으로 단정 금지).\n"
                "  커밋과 무관한 근거(환경 생성·서명·외부 등록 등)라면 --no-base <사유>."
            )
        as_owner = getattr(args, "as_owner", None)
        # 불일치 검사는 done/start와 동형(HARN-06) — 남의 게이트를 자기 이름으로 못 닫는다.
        if as_owner is not None and as_owner != gate.assignee:
            return _fail(
                f"{gate.id}: --as {as_owner} 불일치 — 이 게이트의 assignee는 '{gate.assignee}'"
            )
        # **거부하지 않고 사실대로 적는다.** 에이전트가 사람 게이트를 clear하는 것은 실제로
        # 일어나는 정당한 중계다(Kiki가 자기 머신에서 실행하고 출력을 전달 → 세션이 기입 —
        # 기존 20건 중 다수가 그 형태다). 그걸 막으면 대장 CLI를 우회한 YAML 손편집으로
        # 밀려나고(CLAUDE.md 금지), 그때는 아무 기록도 남지 않아 더 나빠진다. 목표는 금지가
        # 아니라 **사후 증명 가능성**이므로 주체를 항상 명시적으로 남기는 쪽을 택한다.
        gate.status = "cleared"
        gate.evidence = args.evidence
        gate.cleared_by = as_owner or "claude"
        extra["cleared_by"] = gate.cleared_by
        # 탈출구를 쓴 사실과 사유를 **대장과 이벤트 양쪽**에 남긴다. 남지 않는 탈출구는
        # 게이트를 끄는 것과 같다 — 나중에 "왜 기준이 없었나"를 물을 수 있어야 한다.
        if no_base_reason is not None:
            gate.notes = _append_note(gate.notes, no_base_reason, "판정기준 없음")
            extra["no_base_reason"] = no_base_reason
    elif args.gate_action == "waive":
        gate.status = "waived"
        gate.notes = args.reason or gate.notes
    store.save_gates(root, sorted(backlog.gates.values(), key=lambda g: g.id))
    # 이 게이트를 기다리던 blocked 태스크 (HARN-74 ①②) — 게이트 status를 바꾼 **뒤** 계산한다:
    # "다른 게이트 대기"가 방금 해소된 이 게이트를 빼고 남는 것만 세야 하기 때문이다(헬퍼도
    # gate_id를 명시적으로 빼지만, 이 순서면 unmet_gates 관점과도 일치한다). 이벤트에도 남긴다 —
    # 화면은 휘발되지만 대장은 남는다(cancel의 blocked_dependents와 동형).
    attached = selector.gate_attached_blocked(backlog, gate.id)
    notes_ref = selector.gate_notes_referenced_blocked(backlog, gate.id)
    store.append_event(
        root,
        f"gate_{args.gate_action}",
        gate.id,
        evidence=gate.evidence,
        reason=args.reason,
        blocked_attached=[t.id for t, _others in attached],
        blocked_notes_ref=[t.id for t in notes_ref],
        **extra,
    )
    # 주체를 화면에도 되비춘다 — 기입자가 "내가 사람으로 기록됐는지"를 즉시 확인할 수 있어야
    # 잘못된 기입(에이전트가 --as 없이 사람 게이트를 닫음)이 조용히 지나가지 않는다.
    subject = f" (clear 주체: {gate.cleared_by})" if args.gate_action == "clear" else ""
    print(f"✔ {gate.id} → {gate.status}{subject}")
    _print_gate_release_reminder(gate.id, attached, notes_ref)
    return 0


def _print_gate_release_reminder(
    gate_id: str,
    attached: list[tuple[Task, list[str]]],
    notes_ref: list[Task],
) -> None:
    """gates clear·waive 직후 — 그 게이트를 기다리던 blocked 태스크와 다음 명령 (HARN-74 ①②).

    왜 필요한가: 게이트 해소는 태스크 status를 건드리지 않는다(옳다 — 차단 사유가 게이트뿐인지
    기계는 모른다). 그러나 종전 화면은 `✔ 게이트 → cleared` 한 줄뿐이라, clear한 세션은 부착
    태스크가 있다는 사실 자체를 몰랐고 그 태스크는 blocked로 방치됐다(2026-09-06 실측 3건·5일).
    보드(HARN-41)는 이 목록을 계산했지만 CLI·브리핑에는 없었다 — 이 함수가 그 CLI 축이다.

    **0건도 '0건'으로 찍는다** — 이 화면은 그 명령의 *결과 보고*라, 줄이 없으면 "검사했는데
    없었다"와 "검사하지 않았다"를 구분할 수 없다(침묵 실패 금지 · acceptance ①).
    ①(부착)은 unblock 명령을 그대로 낸다. ②(산문 참조)는 기계가 의도를 모르므로 명령 대신
    두 갈래(부착 / 해제) 중 사람이 고르라는 안내를 낸다(모른다 ≠ 아니다).
    """
    if attached:
        print(
            f"  · 부착 blocked 태스크 {len(attached)}건 — 이 게이트를 기다리던 차단. "
            "해제 여부를 확인하라:"
        )
        for task, others in attached:
            # 남은 pending 게이트가 있으면 unblock해도 후보가 되지 않는다 — 그 이유를 미리 알린다.
            # `#` 뒤에 두어 줄을 통째로 복사해도 셸에서 그대로 실행된다.
            suffix = (
                f"  # (다른 게이트 대기: {', '.join(others)} — unblock해도 후보가 되지 않는다)"
                if others
                else ""
            )
            print(f"    python3 scripts/harness/backlog.py unblock {task.id}{suffix}")
    else:
        print("  · 부착 blocked 태스크 0건")
    if notes_ref:
        print(
            f"  · 산문 참조(requires_gates 미부착) {len(notes_ref)}건 — "
            "notes에만 이 게이트를 적은 blocked 태스크. 기계는 의도를 모르므로 사람이 고른다:"
        )
        for task in notes_ref:
            print(
                f"    {task.id} — 부착: backlog.py amend {task.id} --gate {gate_id} "
                f"--reason '...' · 또는 해제: backlog.py unblock {task.id}"
            )
    else:
        print("  · 산문 참조(requires_gates 미부착) 0건")


def _cmd_gates_show(args: argparse.Namespace, backlog) -> int:
    """게이트 단건 브리핑 — `status`·근거를 `title`보다 먼저 낸다 (HARN-92).

    왜 필요한가: `gates.yaml`의 `title`은 게이트 최초 등재 시점의 질문 문구이고
    append 전용 설계(HARN-76)라 `status`가 `pending → cleared/waived`로 바뀌어도
    갱신되지 않는다. `gates list`는 `title`과 `status`를 함께 보여도 근거(evidence/
    notes)는 안 보이므로, 사람에게 게이트를 서술할 때 `title`만 옮겨 적으면 이미
    뒤집힌 질문을 다시 묻게 된다(2026-09-07~08 실측: `G-merge-queue-or-strict-relax`
    가 이미 cleared·재판정됐는데 title을 그대로 인용해 사용자에게 다시 물었다).

    `status`별로 근거 필드가 다르다(Codex P2 리뷰 지적 — `gates.py`의 clear/waive
    저장 위치가 다르다): `cleared`는 `evidence`, `waived`는 `notes`(waive 사유는
    evidence가 아니라 notes에 적힌다), `pending`은 아직 근거가 없다는 사실 자체를
    "없음(아직 결정 전)"으로 명시한다(CLAUDE.md "모른다 ≠ 아니다" — 조회 실패와
    아직-없음을 구분). 근거는 **전문 출력**(절단 없음)이다 — 앞 N자 미리보기는
    핵심 정정 문구가 뒷부분에 있으면 통째로 잘라낼 수 있다(같은 리뷰 지적 —
    `G-merge-queue-or-strict-relax`의 993자 evidence 중 재판정 문구는 403번째
    글자부터 시작한다).
    """
    gate_id = args.gate_id
    if not gate_id:
        return _fail("gates show: 게이트 id 필요 (예: gates show G-xxx)")
    gate = backlog.gates.get(gate_id)
    if gate is None:
        return _fail(f"게이트 '{gate_id}' 없음")

    header = f"게이트: {gate.id}  [{gate.assignee}/{gate.kind}]"
    if gate.status == "cleared":
        header += f"  상태: cleared (clear 주체: {gate.cleared_by or '미상(HARN-60 이전)'})"
    else:
        header += f"  상태: {gate.status}"
    print(header)

    if gate.status == "cleared":
        print("evidence (전문):")
        print(gate.evidence or "(이상 상태 — cleared인데 evidence 없음. validate로 확인)")
    elif gate.status == "waived":
        print("notes — waive 사유 (전문):")
        print(gate.notes or "(이상 상태 — waived인데 notes 없음)")
    else:
        print("evidence: 없음(아직 결정 전)")
    print()
    print(f"title(등재 시점 질문 — 최신 판정을 반영하지 않을 수 있다): {gate.title}")
    return 0


def _cmd_gates_add(root: Path, args: argparse.Namespace, backlog) -> int:
    """게이트 대장(gates.yaml)에 새 게이트를 CLI로 등재한다 (HARN-18).

    "대장은 CLI로만 조작한다"(손편집 금지) 규약의 구멍을 메운다 — 기존에는 gates에
    add 경로가 없어 새 게이트 등재가 손편집뿐이었다(HARN-06과 동형 설계 공백).

    task `add`(cmd_add)와 동일한 검사 골격을 답습한다:
      ① id 필수·형식 ② title 필수 ③ id 중복 거부 ④ 스키마 무결성(Gate.validate)
      ⑤ events.ndjson 감사 로그 append(누가·언제·무엇을 만들었나).
    거부는 전부 명확한 종료코드(1)+메시지 — 침묵 실패 금지.
    """
    gate_id = args.gate_id
    # ② 필수 필드 검증 — 누락 시 명확한 거부 (argparse required로 걸면 list/clear/waive가
    #    같이 --title을 요구하게 되므로, add 액션 안에서 수동 검증한다)
    if not gate_id:
        return _fail("gates add <G-id> — 게이트 ID 필수")
    if not args.title:
        return _fail(f"{gate_id}: gates add 에는 --title <제목> 필수 (필수 필드 누락)")
    # ③ id 중복 거부 — 게이트는 원격 claim 대상이 아니다(원격 claim 대장은 task_id 전용이라
    #    G-* 게이트 id는 애초에 그 대장에 실리지 않는다). 따라서 gates.yaml 내 중복만 본다.
    if gate_id in backlog.gates:
        return _fail(f"게이트 ID 중복: {gate_id} (이미 gates.yaml에 존재)")

    gate = Gate(
        id=gate_id,
        title=args.title,
        kind=args.kind,
        assignee=args.assignee,
        status="pending",
        requested=_today(),
        remind_after_days=args.remind_after_days,
    )
    backlog.gates[gate.id] = gate
    # ④ 스키마/무결성 검증 — 새 게이트가 유발한 오류만 걸러 거부(기존 대장의 무관한
    #    경고에 볼모 잡히지 않게 — cmd_add의 own_errors 패턴 답습). id 형식 위반(예:
    #    소문자 kebab·G- 접두 아님)은 여기서 잡힌다.
    errors = store.validate_backlog(backlog)
    own_errors = [e for e in errors if gate_id in e]
    if own_errors:
        for e in own_errors:
            print(f"  · {e}", file=sys.stderr)
        return _fail(f"{gate_id}: 스키마/무결성 위반으로 게이트 추가 거부")

    store.save_gates(root, sorted(backlog.gates.values(), key=lambda g: g.id))
    # ⑤ 감사 로그 — gate clear/waive·task add의 이벤트 append 패턴 답습
    store.append_event(
        root,
        "gate_add",
        gate.id,
        kind=gate.kind,
        assignee=gate.assignee,
        title=gate.title,
    )
    print(
        f"＋ 게이트 {gate.id} 추가 " f"(kind={gate.kind}, assignee={gate.assignee}, status=pending)"
    )
    return 0


def _taken_id_numbers(root: Path, backlog: object, policy: object) -> dict[str, tuple[str, str]]:
    """이미 쓰인 `<PREFIX>-<번호>` → (점유 태스크의 full ID, 출처 라벨).

    **로컬 백로그 + 원격 claim 대장 + 원격 브랜치 backlog/tasks/ 파일명** 세 곳을 본다.
    원격을 보는 것이 핵심이다 — ARCH-13·OPS-15 두 사고 모두 병렬 세션이 *서로의
    브랜치를 못 봐서* 같은 번호를 각각 등재한 것이라, 로컬만 검사하면 재발을 하나도
    막지 못한다(HARN-10).

    세 번째 출처(원격 브랜치 파일명 스캔)는 HARN-15 — 원격 claim 대장은 **in_progress로
    claim된** 태스크만 기록하므로, "다른 브랜치에 이미 backlog/tasks/<ID>.yaml로
    등재만 되고 아직 착수(claim)되지 않은" 번호는 claim 대장에 원천적으로 안 잡힌다
    (OPS-17·OPS-18이 main과 미머지 브랜치에 각각 다른 슬러그로 이중 등재된 사고,
    HARN-10의 3번째 재발). `remote_claims.scan_remote_task_files`가 이미 있는
    remote-tracking ref만 읽어(fetch 없음) 이 맹점을 메운다.

    full ID를 함께 돌려주는 이유: 충돌은 **슬러그가 다를 때만** 성립한다. 같은 태스크를
    다른 클론에서 재등재하는 것(시딩·복제 세션)은 정상이므로 막으면 안 된다.

    원격 조회 실패는 등재를 막지 않는다(fail-open) — 다만 호출부가 그 사실을
    **경고로 표시**한다. 조용한 축소는 "검사했는데 안 걸림"으로 위장되기 때문이다.
    claim 대장 조회는 기존 관례대로 상태를 조용히 버린다(genuine 예외만 이 함수를
    벗어나 cmd_add의 fail-open 경로로 흘러간다). 파일명 스캔은 "offline"(원격 자체가
    없음 — 로컬 테스트·오프라인 클론의 일상적 상태)은 같은 관례로 조용히 넘기되,
    "error:<타입명>"(scan_remote_task_files 내부에서 이미 예외 타입명을 포장해 돌려줌)
    은 **여기서 바로 경고**한다 — list_claims는 이미 성공했는데 파일명 스캔만 실패한
    경우까지 통째로 예외로 승격하면 이미 확보한 claim 정보까지 버리게 되기 때문이다.
    """
    taken: dict[str, tuple[str, str]] = {}
    for task_id in getattr(backlog, "tasks", {}):
        number = store.id_number_of(str(task_id))
        if number:
            taken.setdefault(number, (str(task_id), "로컬 백로그"))
    if getattr(policy, "remote_claims", False):
        claims, _status = remote_claims.list_claims(root)
        for claim in claims:
            number = store.id_number_of(claim.task_id)
            if number:
                taken.setdefault(number, (claim.task_id, "원격 claim"))
        task_files, files_status = remote_claims.scan_remote_task_files(root)
        if files_status.startswith("error"):
            # 침묵 금지(CLAUDE.md) — status 자체에 이미 예외 타입명이 담겨 있다
            # (scan_remote_task_files 내부의 f"error:{type(exc).__name__}" 포장).
            print(
                f"  ⚠ 원격 브랜치 backlog/tasks/ 파일명 스캔 실패({files_status}) — "
                "등재만 되고 아직 claim되지 않은 원격 번호는 놓칠 수 있다",
                file=sys.stderr,
            )
        for task_file in task_files:
            number = store.id_number_of(task_file.task_id)
            if number:
                taken.setdefault(
                    number,
                    (task_file.task_id, f"원격 브랜치 backlog/tasks/({task_file.branch})"),
                )
    return taken


def _next_free_number(
    prefix: str, taken: Mapping[str, tuple[str, str]], *, cap: int = 99
) -> str | None:
    """`<PREFIX>-<n>` 다음 빈 번호(2자리 zero-padded, 100 이상은 3자리) — **최대 사용
    번호 +1**부터 `cap`까지 찾는다.

    가장 작은 빈 번호를 주면 과거에 비워진 낮은 번호(예 HARN-01)를 제안하게 되는데,
    그건 "이 트랙의 다음 작업"이라는 사람의 기대와 어긋나 제안이 오히려 혼선을 준다.

    `{index:02d}`는 **최소** 2자리이지 **정확히** 2자리가 아니다 — index가 100을 넘으면
    "100"(3자리)을 그대로 낸다(Python format spec은 최소 폭이지 절단이 아니다). HARN-21
    시점에는 `models.TASK_ID_RE`가 정확히 2자리만 허용해 그 3자리 출력이 형식 위반
    ID였다 — 그래서 기본 `cap=99`는 그대로 두어 이 함수 자신과 HARN-73의 tier 1(상향)
    동작·기존 테스트를 전혀 바꾸지 않는다. HARN-97이 `models.TASK_ID_RE`를 2~3자리
    (100~999는 선행 0 없이)로 넓히면서, `_suggest_number`의 tier 3(하위 미사용 번호도
    없을 때의 최종 폴백)만 `cap=999`로 이 함수를 다시 불러 3자리 번호를 제안한다 —
    호출부를 분리해 두어 "언제 3자리를 제안해도 되는가"라는 정책 판단은
    `_suggest_number`가 갖고, 이 함수는 순수하게 "주어진 상한 안에서 다음 빈 번호"만
    계산한다.
    """
    used = [
        int(number.rsplit("-", 1)[1])
        for number in taken
        if number.rsplit("-", 1)[0] == prefix and number.rsplit("-", 1)[1].isdigit()
    ]
    index = max(used) + 1 if used else 1
    while index <= cap and (f"{prefix}-{index}" in taken or f"{prefix}-{index:02d}" in taken):
        index += 1
    if index > cap:
        return None
    return f"{prefix}-{index:02d}"


# HARN-97: 2자리뿐 아니라 3자리(100~999) 파일명도 이력에 잡아야 향후 3자리 번호의
# "한 번이라도 쓰인 적 있음"을 정확히 판정한다 — models.TASK_ID_RE와 폭을 맞춘다.
_HISTORY_TASK_FILE_RE = re.compile(r"^backlog/tasks/([A-Z][A-Z0-9]{0,7})-(\d{2,3})(?:-|\.yaml$)")


def _historically_used_numbers(root: Path, prefix: str) -> tuple[set[int] | None, str]:
    """`<PREFIX>-NN`로 **한 번이라도** 등재된 적 있는 번호(모든 ref·삭제분·rename 포함)와 사유.

    반환 = (번호 집합 또는 None, 사유). 사유 어휘: "ok" · "shallow" · "git_error:<단계> rc=<n>"
    · "exception:<타입명>" · "no_stdout". None일 때 호출부는 사유별로 다른 조치를 안내한다.

    번호 재사용의 안전 조건은 "지금 비어 있음"이 아니라 "**한 번도 쓰인 적 없음**"이다 —
    과거에 등재됐다 삭제·이관된 번호를 다시 주면 문서·커밋의 `EOS-07` 같은 짧은 참조가
    두 태스크를 가리킨다(HARN-10이 막는 상태를 시간축으로 재생산). 그래서 taken(현재
    로컬·원격 파일·claim)만으로는 부족하고 git 이력(`--all --diff-filter=A`)을 본다.

    **fail-closed**: shallow 클론(이력 일부 없음)·git 실패·타임아웃·디코딩 실패는 전부
    None — "모른다"를 "없다"로 접지 않는다(CLAUDE.md 2026-09-01 ③). 호출부는 None이면
    폴백 제안을 내지 않고 **원인을 해소한 뒤 같은 명령을 다시 돌리게** 한다(shallow면
    unshallow — 그 클론에 `git log`를 손으로 돌려 봐야 같은 불완전 이력이다). 출력
    디코딩은 HARN-19 헬퍼(`remote_claims._git`, utf-8 고정)를 재사용한다. (HARN-73)

    `--no-renames`: rename 탐지를 끈다. 켜져 있으면(git 2.9+ 기본) `git mv`로 처음 이
    번호를 얻은 파일이 `R`로 분류돼 `--diff-filter=A`에서 빠지고, 그 파일이 뒤에 삭제되면
    "한 번도 안 쓰인 번호"로 오판된다(PR #1002 Codex P2). 끄면 D+A 쌍이 되어 목적지
    경로가 A로 잡힌다.
    """
    try:
        shallow = remote_claims._git(root, "rev-parse", "--is-shallow-repository", timeout=15)
        if shallow.returncode != 0:
            return None, f"git_error:rev-parse rc={shallow.returncode}"
        if (shallow.stdout or "").strip() == "true":
            return None, "shallow"
        log = remote_claims._git(
            root,
            "log",
            "--all",
            "--no-renames",
            "--diff-filter=A",
            "--name-only",
            "--format=",
            "--",
            f"backlog/tasks/{prefix}-*",
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError, remote_claims.GitOutputDecodeError) as exc:
        return None, f"exception:{type(exc).__name__}"
    if log.returncode != 0:
        return None, f"git_error:log rc={log.returncode}"
    if log.stdout is None:
        return None, "no_stdout"
    used: set[int] = set()
    for line in log.stdout.splitlines():
        match = _HISTORY_TASK_FILE_RE.match(line.strip())
        if match and match.group(1) == prefix:
            used.add(int(match.group(2)))
    return used, "ok"


@dataclass(frozen=True)
class NumberSuggestion:
    """`_suggest_number` 결과 — 제안과 그 근거 수치(문구 조립은 호출부 몫)."""

    suggestion: str | None
    max_used: int  # 점유된 최대 번호(없으면 0)
    free_lower: tuple[int, ...]  # taken에 없는 01~99 번호 — 상위 소진 시에만 계산
    retired: tuple[int, ...]  # free_lower 중 이력상 쓰였다 사라진 번호(재사용 금지)
    history: str  # "not_needed" | "ok" | "extended" | "unavailable"
    history_reason: str = "ok"  # unavailable일 때 원인("shallow"·"exception:…"·"git_error:…")


def _suggest_number(
    prefix: str,
    taken: Mapping[str, tuple[str, str]],
    history_lookup: Callable[[str], tuple[set[int] | None, str]],
) -> NumberSuggestion:
    """번호 제안 3단계 — ① 최대+1 상향(HARN-21, 01~99) ② 상위 소진 시 하위 미사용
    폴백(HARN-73, 01~99 범위 한정) ③ ②도 없으면 3자리(100~999)로 확장 제안(HARN-97).

    ①②는 **그대로 유지한다** — HARN-73에서 이미 Kiki가 결정한 동작(A안: 하위 미사용
    번호 재사용)과 그 테스트를 이 태스크가 바꿀 이유가 없다. `_next_free_number`의
    기본 `cap=99`가 그 경계를 그대로 지킨다.

    ②의 후보는 taken에 없고 **이력에도 없는** 번호 중 가장 낮은 것. "낮은 번호 제안은
    '다음 작업' 기대와 어긋난다"는 ①의 설계 의도는 유지된다 — 폴백은 ①이 불가능할 때만
    작동하고, 이력 조회(`history_lookup`)도 그때만 부른다(비용·부작용 최소화). 후보
    공간은 **01~99**로 한정한다 — 100 이상은 아직 아무도 안 써 본 새 번호이지 "재사용할
    옛 빈자리"가 아니다. `00`은 `TASK_ID_RE`상 형식적으로 유효하지만 `_next_free_number`가
    1부터 세듯 제안 대상이 아니다(PR #1002 Codex P2 — 00을 세지 않으면서 "00~99 소진"이라
    말하던 불일치 정정).

    ③이 HARN-97의 실제 신설분이다 — 2026-09-09 실측: `--id EOS-100`을 직접 지정해도
    `models.TASK_ID_RE`가 정확히 2자리만 허용해 **형식 검증 단계에서** 거부됐다(①②의
    "탐색 소진" 판정과는 다른 길 — ①②는 여기 도달하기 전에 이미 안전한 2자리 번호를
    찾아낼 수도 있었지만, 사람이 "다음은 100번대"라는 순차 기대로 3자리를 직접 썼을
    때도 형식 자체가 막았다). `models.TASK_ID_RE`를 2~3자리(100~999, 선행 0 없이)로
    넓혔으므로, ②까지 전부 실패했을 때(01~99가 지금 점유돼 있거나 이력상 전부
    쓰인 적 있음) `_next_free_number(prefix, taken, cap=999)`로 100 이상을 다시 시도한다
    — `history="extended"`로 표시해 호출부(`cmd_add`)가 "하위 재사용"과 "3자리 확장"을
    다른 문구로 알린다(같은 값이면 사람이 왜 100번대를 받았는지 알 수 없다).

    사고 경위(2026-09-06 · HARN-73): EOS-99가 원격 브랜치에 선점되자 ①이 None을 내고
    cmd_add가 "00~99번을 모두 소진"이라고 보고했다 — 실측은 59/100 사용·40개는 한 번도
    안 쓰임. 오보고가 사람 결정 게이트를 열었다(G-eos-task-prefix-exhausted, Kiki 결정
    A = 하위 재사용). 사고 경위(2026-09-09 · HARN-97): 그 A안으로 우회하며 실제 상한에
    처음 부딪혔다 — ARCH·EOS 두 접두 모두 01~99 소진에 근접·`--id EOS-100`이 형식
    위반으로 거부. ③은 그 다음 층을 연다.
    """
    used = [
        int(number.rsplit("-", 1)[1])
        for number in taken
        if number.rsplit("-", 1)[0] == prefix and number.rsplit("-", 1)[1].isdigit()
    ]
    max_used = max(used) if used else 0
    upward = _next_free_number(prefix, taken)
    if upward is not None:
        return NumberSuggestion(upward, max_used, (), (), "not_needed")
    free_lower = tuple(
        n
        for n in range(1, 100)
        if f"{prefix}-{n:02d}" not in taken and f"{prefix}-{n}" not in taken
    )
    if not free_lower:
        extended = _next_free_number(prefix, taken, cap=999)
        return NumberSuggestion(extended, max_used, (), (), "extended" if extended else "ok")
    history, reason = history_lookup(prefix)
    if history is None:
        return NumberSuggestion(None, max_used, free_lower, (), "unavailable", reason)
    retired = tuple(n for n in free_lower if n in history)
    candidates = [n for n in free_lower if n not in history]
    if not candidates:
        extended = _next_free_number(prefix, taken, cap=999)
        return NumberSuggestion(
            extended, max_used, free_lower, retired, "extended" if extended else "ok"
        )
    return NumberSuggestion(f"{prefix}-{candidates[0]:02d}", max_used, free_lower, retired, "ok")


# 원격 ref 신선도 고지 임계 — 이 저장소는 main이 대략 30분 간격으로 전진한다(2026-08-31
# 실측: #922·#924·#927·#928·#930·#932·#933가 한나절에 착지). 그보다 오래된 스냅샷으로
# 판정했다면 "그 사이 등재된 번호는 못 봤다"가 실질적 가능성이 된다.
_STALE_REFS_SECONDS = 1800


def _format_age(seconds: float) -> str:
    """경과 초 → 사람이 읽는 표기(분 단위 이하는 뭉갠다 — 정밀도를 날조하지 않는다)."""
    minutes = int(seconds // 60)
    if minutes < 1:
        return "1분 미만"
    if minutes < 60:
        return f"{minutes}분"
    hours, rem = divmod(minutes, 60)
    return f"{hours}시간 {rem}분" if rem else f"{hours}시간"


def _print_visibility_notice(root: Path, task_id: str, policy: object) -> None:
    """등재 직후 **가드의 관측 사각**을 사람에게 고지한다 (HARN-43).

    **탐지가 아니라 고지다.** 미push 브랜치를 실제로 관측하는 수단은 없으므로(그
    브랜치는 세 출처 어디에도 나타나지 않는다 — `remote_claims` §등재 가시성 고지),
    가드가 할 수 있는 최선은 자기 관측 범위의 구멍을 말하는 것뿐이다. 이 함수는
    무엇도 차단하지 않으며, 어떤 판정도 뒤집지 않는다.

    **조용할 때는 조용하다** — push된 브랜치에서 ref도 신선하면 아무것도 출력하지
    않는다. 무조건 뜨는 고지는 소음이 되어 습관적으로 무시되고, 그러면 정작 필요한
    순간에 보이지 않는다(CLAUDE.md "상시 실패하는 fail-open 보호" 선례와 동형).

    판정 불가(`None`)는 침묵한다 — 여기서 추측을 출력하면 "측정 실패"가 "경고 없음"
    또는 "경고 있음"으로 위장된다. 조회 실패 자체의 고지는 이미 `cmd_add`의 fail-open
    경고가 담당한다.
    """
    if not getattr(policy, "remote_claims", False):
        return
    lines: list[str] = []

    branch = store.current_branch(root)
    pushed, _pushed_status = remote_claims.branch_has_remote_ref(root, branch)
    if pushed is False:
        lines.append(
            f"이 번호는 **push 전까지 다른 세션에 보이지 않는다** — 현재 브랜치 "
            f"'{branch}'의 원격 ref가 이 클론에 없다(미push 추정)."
        )

    age, _age_status = remote_claims.remote_refs_age_seconds(root)
    if age is not None and age >= _STALE_REFS_SECONDS:
        lines.append(
            f"번호 가드가 읽은 원격 스냅샷이 {_format_age(age)} 지났다 — 그 이후 원격에 "
            "등재된 번호는 구조적으로 보지 못했다(`scan_remote_task_files`는 네트워크를 "
            "타지 않는다). 최신 판정이 필요하면 `git fetch origin` 후 재확인."
        )
    if not lines:
        return
    print(f"  ⓘ {task_id} 가시성 고지 — **가드 통과 ≠ 충돌 없음**", file=sys.stderr)
    for line in lines:
        print(f"     · {line}", file=sys.stderr)


def _print_similar_notice(root: Path, backlog, task: Task, policy: object) -> None:
    """의미 중복 후보 고지 (HARN-51) — **탐지가 아니라 고지이며, 차단하지 않는다.**

    번호 가드가 막는 것은 *같은 이름*이다. 이 고지가 겨누는 것은 **다른 이름·같은 문제**로,
    2026-08-31 `HARN-45`↔`HARN-48` 이중 구현이 어떤 가드에도 걸리지 않은 축이다.

    대조군은 **로컬 in-flight + 원격 브랜치 사본**이다(acceptance ③). 로컬만 보면 그
    실사고를 재현조차 못 한다 — `HARN-48`은 별도 브랜치에서 진행 중이었고 트렁크에는
    없었다. 원격 읽기는 `fetch=False` 계약을 승계하므로 **네트워크 0**이다.

    원격 조회가 실패하면 침묵하지 않고 '판정 불가'라고 말한다 — 조회 실패를 '중복 없음'과
    같은 색으로 두면 측정 실패가 통과로 위장된다(CLAUDE.md 침묵 실패 금지).
    """
    corpus = {
        tid: similar.task_text(other.title, other.notes, other.acceptance)
        for tid, other in backlog.tasks.items()
    }
    pool = {
        tid: text
        for tid, text in corpus.items()
        if tid != task.id
        and backlog.tasks[tid].status in ("todo", "in_progress", "blocked", "review")
    }
    origins: dict[str, str] = {}
    remote_status = "disabled"
    if getattr(policy, "remote_claims", False):
        # 고지는 관측 기능이다 — 원격 조회가 어떤 식으로 죽든 `add` 자체를 막지 않는다.
        # 다만 **예외 타입명을 남긴다**(CLAUDE.md 침묵 실패 금지): 무타입 경고는
        # langfuse v2 쓰기가 8일간 무증상 전멸한 원인이었다.
        try:
            files, remote_status = remote_claims.scan_remote_task_files(root)
        except Exception as exc:
            files, remote_status = [], f"error:{type(exc).__name__}"
        if remote_status == "ok":
            # 로컬에 이미 있는 ID는 읽기 *앞*에서 제외한다 — 같은 태스크의 원격 사본은
            # 의미 중복 후보가 아니라 같은 것의 다른 사본이다(번호 축은 번호 가드의 몫).
            try:
                texts, branch_of, read_status = remote_claims.read_remote_task_texts(
                    root, files, skip=set(corpus) | {task.id}
                )
            except Exception as exc:
                texts, branch_of, read_status = {}, {}, f"error:{type(exc).__name__}"
            for tid, raw in texts.items():
                pool[tid] = raw
                corpus[tid] = raw
                origins[tid] = f"origin/{branch_of.get(tid, '?')}"
            if read_status != "ok":
                remote_status = read_status

    index = similar.SimilarityIndex(corpus)
    found = index.candidates(
        similar.task_text(task.title, task.notes, task.acceptance), pool, origins=origins
    )
    if not found and remote_status in ("ok", "disabled"):
        return  # 조용할 때는 조용하다
    if found:
        print(
            f"  ⓘ {task.id} 의미 중복 후보 — **번호가 달라도 같은 문제일 수 있다**",
            file=sys.stderr,
        )
        for item in found:
            terms = ", ".join(item.shared_terms)
            print(
                f"     · {item.task_id} [{item.origin}] 유사도 {item.score:.2f}"
                f"{chr(10)}       공유 희소어: {terms}",
                file=sys.stderr,
            )
        print(
            "     차단이 아니라 고지다 — 무관하면 그냥 진행하고, 겹치면 그쪽 세션과 "
            "조율하거나 한쪽을 cancel한다(HARN-45 선례).",
            file=sys.stderr,
        )
    if remote_status not in ("ok", "disabled"):
        print(
            f"  ⚠ 의미 중복 대조가 원격을 다 보지 못했다({remote_status}) — "
            f"미머지 브랜치의 중복은 **판정 불가**다",
            file=sys.stderr,
        )


# ── EOS 등급 집행 (HARN-55 — 계획서 100 Rule 1·3·4) ──────────────────────────
#
# 계획서 100은 세 규칙을 **산문으로** 요구했고(Rule 1 신규 기능 금지·Rule 3 전 기능 등급·
# Rule 4 One In → One Out), 저장소는 그것을 선언 §0-5에 옮겨 적었을 뿐 집행 지점이 0이었다
# (전환계획 준수 감사 A1 "높음"). 산문 규칙은 그것을 읽은 세션에만 작동한다 — 대장을 만지는
# 경로가 CLI 하나뿐이므로, 집행 지점도 CLI여야 한다.
#
# 여기서 "집행"은 **등재를 거부하는 것**이다. 경고는 집행이 아니다: 이 저장소는 상시 실패하는
# fail-open 경고가 습관화돼 보호가 통째로 무력해진 사고를 이미 겪었다(refs/claims 403).

_EOS_PRIORITY_HELP = (
    "P0 = 없으면 12월 검증(G0~G5)이 성립하지 않는다 | "
    "P1 = 품질을 크게 높이지만 우회 가능 | "
    "P2 = 판정 이후(2027 Q1~Q2) | "
    "P3 = 장기 연구·플랫폼"
)

_EOS_PRIORITY_QUESTION = (
    "판정 질문(계획서 100 §3.5): "
    '"이 기능이 없으면 12월 31일 EOS 검증의 폐쇄루프가 깨지는가?" '
    "YES = P0 후보. 애매하면 P0가 아니다 — 애매한 것을 P0에 넣는 것이 270개를 그대로 "
    "12월 범위로 삼는 실패의 시작이다."
)


def _active_p0(backlog: Backlog) -> list[str]:
    """예산을 점유 중인 P0 = 종결되지 않은 P0. 끝난 P0는 12월 범위를 먹지 않는다."""
    return sorted(
        t.id
        for t in backlog.tasks.values()
        if t.eos_priority == "P0" and t.status not in TERMINAL_STATUSES
    )


def _id_number_conflict(
    root: Path, backlog: object, new_id: str, *, verb: str = "add"
) -> tuple[str | None, bool]:
    """`new_id`의 `<PREFIX>-<번호>`가 이미 점유돼 있으면 **거부 문구**를 돌려준다 (HARN-10).

    반환: `(거부 문구 또는 None, 원격_조회_성공)`. 문구가 `None`이면 통과다.

    왜 함수로 빼는가 — 이 판정은 이제 `add`(신규 등재)와 `rename`(개명) **두 곳**이 쓴다.
    같은 판정을 두 벌로 두면 한쪽만 고쳐지고, 그때 갈라지는 것은 *번호 충돌을 막는 규칙*
    자체다(HARN-100). `verb`는 거부 문구 안의 재실행 안내에만 쓴다 — 판정 자체는 동일하다.
    """
    # 규약 밖 ID(번호 없음)는 검사 대상이 아니다 — 그 경우에도 반환 계약은 지켜야 하므로
    # 루프 밖에서 초기화한다(안 하면 `return None, remote_ok`가 NameError로 터진다).
    remote_ok = True

    def _no(message: str) -> tuple[str, bool]:
        """거부 문구를 반환 계약 `(문구, 원격_조회_성공)`에 맞춰 싣는다.

        `remote_ok`를 클로저로 읽는다 — 거부 시점에는 이미 확정돼 있다. 이 래퍼가
        없으면 각 거부 지점이 문자열만 돌려주고, 호출부의 튜플 언패킹이 문자열을
        글자 단위로 풀어 `ValueError`가 난다(추출 중 실제로 이 형태로 6건 RED).
        """
        return message, remote_ok

    remote_ok = True
    number = store.id_number_of(new_id)
    if number:
        policy, _ = store.load_policy(root)
        try:
            taken = _taken_id_numbers(root, backlog, policy)
            remote_ok = True
        except Exception as exc:  # 원격 조회 실패는 등재를 막지 않는다 — 단 침묵 금지
            taken = _taken_id_numbers(root, backlog, None)
            remote_ok = False
            print(
                f"  ⚠ 원격 claim 대장 조회 실패({type(exc).__name__}) — 번호 충돌 검사가 "
                "로컬 백로그로 축소됨(병렬 세션의 인플라이트 번호는 못 본다)",
                file=sys.stderr,
            )
        owner, source = taken.get(number, ("", ""))
        # 같은 full ID의 재등재(다른 클론에서의 시딩 등)는 충돌이 아니다 — 슬러그가
        # 다를 때만 번호 참조가 모호해진다.
        if owner and owner != new_id:
            prefix = number.rsplit("-", 1)[0]
            verdict = _suggest_number(prefix, taken, lambda p: _historically_used_numbers(root, p))
            base = f"태스크 ID 번호 충돌: '{number}' 는 이미 {owner}({source}) 가 쓰고 있다. "
            tail = "(같은 번호를 나눠 쓰면 문서·커밋의 번호 참조가 결정 불가가 된다 — HARN-10)"
            if verdict.suggestion is not None and verdict.history == "not_needed":
                return _no(base + f"다음 빈 번호 제안: {verdict.suggestion}. " + tail)
            top = f"{prefix}-{verdict.max_used:02d}"
            if verdict.suggestion is not None and verdict.history == "extended":
                # 하위(01~99) 재사용도 없다 — 3자리(100~999)로 확장 제안(HARN-97).
                usable = len(verdict.free_lower) - len(verdict.retired)
                return _no(
                    base + f"상위 2자리 번호 소진(최대 {top}) · 미사용 하위 번호 {usable}개도 "
                    f"없음 — 3자리로 확장해 {verdict.suggestion} 제안(HARN-97). " + tail
                )
            if verdict.suggestion is not None:
                # 상위(최대+1)는 막혔지만 한 번도 쓰인 적 없는 하위 번호가 있다(HARN-73).
                usable = len(verdict.free_lower) - len(verdict.retired)
                return _no(
                    base + f"상위 번호 소진(최대 {top}) — 미사용 하위 번호 {usable}개 중 가장 낮은 "
                    f"{verdict.suggestion} 제안(이력상 쓰였다 사라진 {len(verdict.retired)}개는 "
                    "제외 — HARN-73). " + tail
                )
            if verdict.history == "unavailable":
                # 후보는 있으나 "한 번도 쓰인 적 없음"을 확인할 수 없다 — 모른다를 없다로
                # 접지 않고, **원인을 해소한 뒤 같은 명령을 다시 돌리게** 한다(fail-closed).
                # shallow 클론에 `git log`를 손으로 돌리라고 안내하면 방금 거부한 것과 같은
                # 불완전 이력을 재탐색할 뿐이므로(PR #1002 Codex P2) 수동 --id 추론은
                # 안내하지 않는다 — 배정은 도구가 확인할 수 있을 때까지 막힌 채로 둔다.
                preview = ", ".join(f"{prefix}-{n:02d}" for n in verdict.free_lower[:10])
                if len(verdict.free_lower) > 10:
                    preview += " …"
                if verdict.history_reason == "shallow":
                    remedy = (
                        "이 클론은 shallow(이력 일부 없음)라 로컬 이력 조회로도 확인할 수 없다 — "
                        "`git fetch --unshallow origin`으로 전체 이력을 받은 뒤 같은 "
                        f"{verb} 명령을 다시 실행하라"
                    )
                else:
                    remedy = (
                        f"사유 {verdict.history_reason} — 원인을 해소한 뒤 같은 {verb} 명령을 "
                        "다시 실행하라"
                    )
                return _no(
                    base
                    + f"상위 번호 소진(최대 {top}) · 미사용 하위 후보 {len(verdict.free_lower)}개"
                    f"({preview}) — git 이력 조회 불가로 '한 번도 쓰인 적 없음'을 확인할 수 "
                    f"없어 제안하지 않는다. {remedy}. 번호를 손으로 추론해 --id로 넣지 말 것"
                    "(HARN-73). " + tail
                )
            # 정말 다 찼다 — 001~999(HARN-97 확장 상한) 전부가 지금 점유돼 있거나
            # 이력상 쓰였다 사라진 번호다. TASK_ID_RE(2~3자리, 999 상한)를 지키는 다음
            # 번호를 더 이상 제안할 수 없다 — 이 규모(접두당 999개)에 실제로 도달하는
            # 것은 이 저장소 관측 이력상 전무하므로 사람의 결정이 필요하다(HARN-97).
            return _no(
                base + f"게다가 프리픽스 '{prefix}'는 001~999번을 모두 소진했다(번호 공간은 01부터 "
                f"센다 · 미사용 0개 · 이력상 쓰였다 사라진 {len(verdict.retired)}개는 재사용 "
                "금지) — TASK_ID_RE(2~3자리 숫자, 999 상한)를 지키는 다음 번호를 더 이상 제안할 "
                "수 없다. 새 프리픽스로 분리하는 등 사람의 결정이 필요하다(HARN-97). " + tail
            )
    return None, remote_ok


def cmd_add(root: Path, args: argparse.Namespace) -> int:
    backlog, _ = _load(root)
    if args.id in backlog.tasks:
        return _fail(f"태스크 ID 중복: {args.id}")

    # [Rule 1·3 집행] 등급 없는 등재를 거부한다. 이것이 "신규 기능 게이트"의 집행 지점이다
    # — 등급을 고르려면 12월 검증 관여 여부를 판정할 수밖에 없기 때문이다.
    if args.eos_priority is None:
        return _fail(
            f"{args.id}: --eos-priority 미지정 — EOS 등급 없는 신규 등재는 거부한다.\n"
            f"    {_EOS_PRIORITY_HELP}\n"
            f"    {_EOS_PRIORITY_QUESTION}\n"
            "    (계획서 100 Rule 1·3 / 전환 선언 §0-5의 집행 지점. "
            "산문 규칙만 있고 집행이 0이던 것이 준수 감사 A1이다)"
        )
    if args.eos_priority not in EOS_PRIORITIES:
        return _fail(
            f"{args.id}: --eos-priority '{args.eos_priority}' 미등록 "
            f"(허용: {list(EOS_PRIORITIES)})"
        )

    err, remote_ok = _id_number_conflict(root, backlog, args.id)
    if err:
        return _fail(err)
        if not remote_ok:
            print("  · 번호 충돌 검사: 로컬만 통과 — 머지 시 validate가 2선 방어한다")
    task = Task(
        id=args.id,
        title=args.title,
        track=args.track,
        stage=args.stage,
        subject=args.subject,
        layer=args.layer,
        priority=args.priority,
        eos_priority=args.eos_priority,
        owner=args.owner,
        depends_on=args.depends or [],
        requires_gates=args.gates or [],
        acceptance=args.acceptance or [],
        paths=args.paths or [],
        notes=_notes_with_trigger_exemption(args),
        updated=_today(),
    )
    # [프리플라이트] 파일 범위 겹침 — 등재 시점에도 todo·in-flight 중복을 검출
    # (start와 동일한 함수를 재사용; todo 겹침은 경고, in-flight 겹침은 policy에 따름)
    policy, _ = store.load_policy(root)
    overlap_error = _check_path_overlap(
        root, backlog, task, policy, remote_claimed=None, session=None
    )
    if overlap_error:
        return _fail(overlap_error)

    # [Rule 4 집행] One In → One Out. 예산에 닿은 뒤의 P0 신규 등재는 교환을 요구한다.
    # 교환 대상은 *비종결* P0여야 한다 — 이미 끝난 P0를 내주는 것은 아무것도 내주지 않는 것이다.
    swapped: str | None = None
    if task.eos_priority == "P0":
        active = _active_p0(backlog)
        budget = policy.eos_p0_budget
        if len(active) >= budget:
            if not args.swap_out:
                return _fail(
                    f"{args.id}: P0 예산 소진 — 현재 비종결 P0 {len(active)}건 / 예산 "
                    f"{budget}건. P0 신규 등재는 기존 P0 하나와 **교환**해야 한다"
                    " (One In → One Out · 계획서 100 Rule 4).\n"
                    "    --swap-out <기존 P0 태스크 id> 로 내보낼 태스크를 지정하라"
                    " (그 태스크는 P1로 강등된다).\n"
                    f"    현재 P0: {', '.join(active[:10])}"
                    f"{' 외 ' + str(len(active) - 10) + '건' if len(active) > 10 else ''}"
                )
            out = backlog.tasks.get(args.swap_out)
            if out is None:
                return _fail(f"--swap-out '{args.swap_out}': 그런 태스크가 없다")
            if out.eos_priority != "P0":
                return _fail(
                    f"--swap-out '{args.swap_out}': P0가 아니다"
                    f"(현재 {out.eos_priority!r}) — 교환은 P0 자리를 내주는 것이다"
                )
            if out.status in TERMINAL_STATUSES:
                return _fail(
                    f"--swap-out '{args.swap_out}': 이미 {out.status} — 종결 태스크는 예산을 "
                    "점유하지 않으므로 내줄 자리가 없다(교환이 아니라 무상 추가가 된다)"
                )
            out.eos_priority = "P1"
            out.notes = _append_note(
                out.notes,
                f"P0 → P1 강등 — {args.id} 등재와 교환(One In → One Out · Rule 4)",
                "등급",
            )
            out.updated = _today()
            swapped = out.id
        elif args.swap_out:
            return _fail(
                f"--swap-out 불필요: 현재 비종결 P0 {len(active)}건 < 예산 {budget}건이라 "
                "교환 없이 등재된다. 예산 여유가 있는데 교환하면 P0가 줄어든다"
            )
    elif args.swap_out:
        return _fail("--swap-out 은 --eos-priority P0 일 때만 쓴다")

    backlog.tasks[task.id] = task
    errors = store.validate_backlog(backlog)
    # 새 태스크가 유발한 오류만 걸러 거부 (기존 백로그의 무관한 경고에 볼모 잡히지 않게)
    own_errors = [e for e in errors if args.id in e]
    if own_errors:
        for e in own_errors:
            print(f"  · {e}", file=sys.stderr)
        return _fail(f"{args.id}: 스키마/무결성 위반으로 추가 거부")
    # [쓰기측 선검사 · HARN-71] `--notes`가 선행 어구로 타 태스크를 지목하는데 `--depends`가
    # 비어 있으면 **파일을 쓰기 전에** 거부한다. `block`·`amend`는 이미 같은 검사를 갖고
    # 있었고(`_fail_on_reason_feedback`) `add`만 빠져 있었다 — 그래서 등재는 조용히 성공하고
    # CI `harness-integrity`의 `audit-deps`가 나중에 red를 냈다(실측: add EXIT 0 · audit EXIT 1).
    # 신규 태스크라 "이전 상태"가 없으므로 `before`는 빈 집합이다 — 이 태스크가 만든 선언은
    # 전부 새 선언이다. 위에서 `backlog.tasks`에 넣은 뒤 검사하므로 참조 대상 해소 여부
    # (done/cancelled면 순서 제약이 실효 없다)까지 읽기측과 **같은 함수**로 판정한다.
    if _fail_on_reason_feedback(backlog, task.id, set(), flag="--notes", appended=False):
        # 대장은 무변경이어야 한다 — `save_task` 이전이라 디스크에 아무것도 쓰이지 않았고,
        # `backlog.tasks`는 이 프로세스의 메모리라 종료와 함께 사라진다(부분 쓰기 없음).
        return 1
    path = store.save_task(root, task)
    store.append_event(root, "add", task.id, eos_priority=task.eos_priority)
    print(f"＋ {task.id} 추가 → {path.relative_to(root)} [EOS {task.eos_priority}]")
    if swapped:
        # 교환은 두 태스크를 바꾸므로 **양쪽 다** 디스크·대장에 남겨야 한다.
        # 한쪽만 남기면 예산 회계가 조용히 어긋난다.
        store.save_task(root, backlog.tasks[swapped])
        store.append_event(
            root,
            "amend",
            swapped,
            reason=f"P0 → P1 교환 (One In → One Out, {task.id} 등재)",
            field="eos_priority",
            before="P0",
            after="P1",
        )
        print(f"  ⇄ One In → One Out: {swapped} P0 → P1 강등")
    # HARN-43 — 등재는 끝났고, 이제 가드가 *못 본* 범위를 말한다(차단 아님).
    _print_visibility_notice(root, task.id, policy)
    # HARN-51 — 번호가 아니라 *의미*가 겹치는 태스크를 고지한다(차단 아님).
    _print_similar_notice(root, backlog, task, policy)
    return 0


def _notes_with_trigger_exemption(args: argparse.Namespace) -> str:
    """등재 시점 트리거 면제(HARN-72)를 notes에 마커로 붙인다.

    면제를 코드 상수가 아니라 태스크 자신에 두는 이유는 `dep_declaration.LEGACY_EXEMPT`와
    반대 방향의 선택이다: 그쪽은 *기존* 위반을 일괄 유예하므로 목록 관리가 필요했지만,
    이쪽은 *개별* 오탐이라 사유가 태스크 옆에 있는 편이 읽는 사람에게 낫다. 무사유 면제는
    argparse가 값을 요구하므로 구조적으로 불가능하다.
    """
    notes = args.notes or ""
    reason = getattr(args, "no_trigger", None)
    if not reason:
        return notes
    from trigger_declaration import EXEMPTION_MARKER

    marker = f"{EXEMPTION_MARKER} {reason}"
    return f"{notes}\n\n{marker}" if notes else marker


def cmd_amend(root: Path, args: argparse.Namespace) -> int:
    """등재된 태스크의 acceptance·gates·track·depends_on·priority·artifacts·paths·title 정정.

    (HARN-24+49+52+57)


    **왜 필요한가 (두 뿌리)**:
    - *acceptance 축(HARN-24)*: 이 CLI에 등재된 태스크의 acceptance를 고치는 서브커맨드가
      0건이었다. 그래서 정정이 문서에만 착지하고 태스크 YAML에 도달하지 못했고, 그 정정을
      조상으로 가진 세션이 stale acceptance를 그대로 집행했다(ADMIN-02 → subscription_*
      3컬럼 드롭, 커밋 b3a58b02). 일반형: "문서가 소유자"라는 우회는 착수 세션이 그 문서를
      읽을 때만 성립한다 — 태스크 YAML은 **반드시** 읽히지만 참조 문서는 선택이다.
    - *track 축(HARN-49)*: 등재 시 잘못 붙은 `track`은 그 트랙의 `entry_gate`를 상속시켜
      태스크를 **영구 착수 불가**로 만든다. `start`에 우회 플래그는 없고(설계상 옳다) 대장
      손편집은 금지이므로 정정 경로 자체가 없었다 — S1-16이 그렇게 12일 막혔다.

    **통합 경위(2026-08-31)**: 두 태스크가 같은 verb를 독립 구현해 머지에서 충돌했다.
    HARN-49가 이 저장소에 먼저 착지했고 그 docstring이 "HARN-24가 --acceptance·--gate를
    덧붙일 수 있는 형태로 둔다"고 명시했으므로, **양쪽 동작을 모두 보존해** 하나로 합쳤다.
    어느 한쪽을 버리지 않은 이유: track 축은 이전 값을 notes에 남기고 진입 게이트 변화를
    즉석에서 보고하는데(HARN-49), acceptance 축은 append 전용 규약과 정정 후 무결성 재검사를
    갖는다(HARN-24) — 둘 다 각자의 사고에서 배운 것이라 버리면 그 교훈이 사라진다.

    **설계 원칙 3**:
    1. **append만, 덮어쓰기 금지** — acceptance·requires_gates·depends_on·artifacts는 정정
       항을 *추가*한다. HARN-20이 notes에서 배운 교훈(덮어쓰기가 blocked 4건 전건의 원
       notes를 소실시킴)을 승계한다. 기존 항의 개별 제거는 열지 않는다.
    2. **상태 전이 표면은 불변, 정정 표면은 열린다** (HARN-57에서 원칙 2를 *정밀화*).
       - **여전히 닫힌 것 = `id`·`status`·`session`**. 상태 전이는 start/done/block/review/
         cancel의 몫이고 이 verb가 그 경로를 우회하면 안 된다. `session`은 claim 소유권이라
         손으로 옮기면 병렬 세션의 겹침 판정이 통째로 거짓이 된다. `id`는 계보를 끊는다.
       - **열린 것 = `artifacts`·`paths`·`title`**. 이 셋은 상태가 아니라 *기술(記述)*인데
         정정 경로가 없어 실측 사고를 냈다. ⓐ`artifacts`: done을 PR 생성 전에 부르면 잘못된
         증적이 영구 고정된다(HARN-44 → "커밋 예정(PR 동반)"이 남고 실제 PR #965는 대장에서
         추적 불가). ⓑ`paths`: 넓게 잡은 glob이 고정되면 overlap 경보가 대량 오탐이 되고,
         상시 오탐은 병렬 세션이 경보를 무시하게 만든다(2026-09-03 MOB-20 — 경보 17건,
         YAML 손편집으로 정정). ⓒ`title`: SessionStart 브리핑과 `next`가 노출하는 것은
         **title 한 줄**이라, 범위가 정정된 태스크의 옛 제목이 남으면 다음 세션이 정정 전
         처방을 읽고 착수한다(MOB-20 실측 — paths보다 위험하다).
       - 셋의 *정정 방식*은 성질에 따라 갈린다: `artifacts`는 **append만**(증적을 지우는 것은
         위조 표면이다), `paths`·`title`은 **이전 값을 notes에 남기고 교체**한다(HARN-49의
         track 선례). 좁히는 것이 목적인 필드를 append로 두면 목적 자체가 성립하지 않는다 —
         넓은 glob을 append로 좁힐 방법은 없다.
    3. **사유 필수 + 이벤트 기록** — 왜 고쳤는지가 대장에 남지 않으면 정정 자체가 추적 불가다.

    **정정 경로 3축 추가(HARN-67 — 원칙 1의 예외를 *제거·치환*으로 한정해 연다)**:
    - `--remove-depends`: 취소·오등재된 선행을 뗀다. 없으면 오등재를 바로잡을 때 그것에
      의존하던 정상 태스크가 영구 차단된다(2026-09-05 EOS-94 cancel → EOS-96 침묵 차단).
    - `--remove-gate`: 오부착 게이트를 뗀다. `gates clear`는 게이트를 *통과*시키는 것이라
      잘못 걸린 게이트의 정정이 아니다(산출 태스크 자신에 검수 게이트를 걸면 교착 — MP-01).
    - `--notes-replace 구문자 신문자`: notes의 한 어구를 치환한다. audit-deps가 notes의
      '선행' 어구를 위반으로 판정하는데 notes를 고칠 CLI가 없었다 — 고칠 수 없는 위반을
      지적하는 게이트는 사람이 게이트를 끄게 만든다. 구문자는 **정확히 1회** 등장해야 한다
      (0회는 치환 0건이 성공으로 보이는 위장, 2회+는 어느 쪽인지 결정 불가).
    셋 다 사유 필수·이벤트 기록(removed_depends·removed_gates·notes_replace)이며, 제거된
    값·치환 원문은 **이벤트 대장에만** 남긴다 — notes에 원문을 인용하면 스캐너가 인용문 속
    선행 어구를 다시 위반으로 잡는 되먹임이 된다.

    **여전히 열지 않는 것**: 태스크 삭제·ID 변경(rename)·acceptance/artifacts 항목 개별 제거.
    대장 손편집의 우회 표면이 되거나 ID 계보를 끊는다. rename 미구현 사유는
    `docs/standards/build_harness.md` §7a 정정 경로 표 참조.

    **알려진 한계**: `--title`의 *이전* 제목도 notes에 append되므로, 옛 제목이 선행 어구와 타
    태스크 ID를 한 문장에 담고 있으면 HARN-53 되먹임 가드가 이 정정을 거부한다. 그때는 같은
    호출에 `--depends`로 그 선행을 함께 부착하면 통과한다(가드는 *새로* 생긴 위반만 본다).
    """
    backlog, _ = _load(root)
    # 정정 *전* 위반 스냅샷 — 아래 가드가 "이 정정이 새로 만든 것"만 판정하기 위한 기준선.
    _pre_amend_findings = {
        (f.task_id, f.referenced)
        for f in dep_declaration.find_undeclared_dependencies(backlog.tasks)
    }
    task = backlog.tasks.get(args.id)
    if task is None:
        return _fail(f"태스크 '{args.id}' 없음")

    # 변경 요청이 하나도 없으면 거부 — 사유만 남기고 아무것도 안 바꾸는 호출은
    # 이벤트 대장을 오염시킨다(무변경 amend가 '정정했다'로 읽힌다).
    # priority는 `is not None` — 0은 falsy라 `or args.priority`로 쓰면 `--priority 0`이
    # "인자 없음"으로 처리돼 범위 오류가 아니라 엉뚱한 메시지가 난다(테스트가 실측).
    remove_depends: list[str] = list(getattr(args, "remove_depends", None) or [])
    remove_gates: list[str] = list(getattr(args, "remove_gates", None) or [])
    notes_replace = getattr(args, "notes_replace", None)
    if not (
        args.acceptance
        or args.gates
        or args.track
        or args.depends
        or args.priority is not None
        or args.eos_priority
        or getattr(args, "no_trigger", None)
        or remove_depends
        or remove_gates
        or notes_replace
        or getattr(args, "artifacts", None)
        or getattr(args, "paths", None)
        # title은 truthiness가 아니라 `is not None`으로 본다 — `--title ""`은 *지정됐다*.
        # truthiness로 접으면 빈 제목이 이 가드에 먼저 걸려 "변경 항목이 없다"로 거부되고,
        # 정작 그 경우를 위해 쓴 진단("인자가 비어 전달됐는지 확인하라")에 닿지 못한다.
        or getattr(args, "title", None) is not None
    ):
        return _fail(
            f"{task.id}: 변경 항목이 없다 — --acceptance / --gate / --remove-gate / --track / "
            "--depends / --remove-depends / --priority / --eos-priority / --no-trigger / "
            "--notes-replace / --artifact / --path / --title 중 하나 이상을 지정하라"
        )

    # 같은 호출에서 같은 id를 부착+제거하면 결과가 옵션 처리 순서에 좌우된다 — 결정 불가는
    # 실행하지 않고 거부한다(HARN-67 ③·⑤).
    both_deps = sorted(set(args.depends) & set(remove_depends))
    if both_deps:
        return _fail(f"{task.id}: 같은 의존을 부착하면서 제거할 수 없다 — {', '.join(both_deps)}")
    both_gates = sorted(set(args.gates) & set(remove_gates))
    if both_gates:
        return _fail(
            f"{task.id}: 같은 게이트를 부착하면서 제거할 수 없다 — {', '.join(both_gates)}"
        )

    changed: list[str] = []
    note_lines: list[str] = []
    track_before: str | None = None
    paths_before: list[str] | None = None
    added_artifacts: list[str] = []

    # ① acceptance: append만 (덮어쓰기 금지 — HARN-20 승계)
    for item in args.acceptance or []:
        text = item.strip()
        if not text:
            return _fail(f"{task.id}: 빈 acceptance 항은 추가할 수 없다")
        if text in task.acceptance:
            return _fail(f"{task.id}: 동일한 acceptance 항이 이미 있다 — {text[:60]}")
        task.acceptance.append(text)
        changed.append(f"acceptance +1 ({text[:40]}…)")

    # ② requires_gates: 중복 없이 추가. 게이트 *통과*는 gates clear의 몫이고, 오부착의
    #    *탈착*은 아래 ②-b(HARN-67 ⑤)가 맡는다 — 둘은 다른 일이다.
    for gid in args.gates or []:
        if gid in task.requires_gates:
            return _fail(f"{task.id}: 게이트 '{gid}' 가 이미 붙어 있다")
        if gid not in backlog.gates:
            return _fail(
                f"{task.id}: 게이트 '{gid}' 가 gates.yaml에 없다 — "
                "먼저 `gates add` 로 등재하라(존재하지 않는 게이트는 영구 차단이 된다)"
            )
        task.requires_gates.append(gid)
        changed.append(f"requires_gates +{gid}")

    # ②-b requires_gates 탈착 (HARN-67 ⑤) — 오부착을 되돌릴 유일한 CLI 경로.
    #
    # 왜 필요한가: `requires_gates`는 done 조건이 아니라 **착수 조건**이다(selector.py). 산출물을
    # 검수하는 게이트를 그 산출물을 *만드는* 태스크에 걸면 교착이 되는데(2026-09-06 MP-01), 그
    # 실수를 되돌릴 경로가 없어 cancel+재등재로만 고칠 수 있었고 번호가 소모됐다. 게이트
    # 자체(gates.yaml)의 status는 건드리지 않는다 — 탈착은 태스크 쪽 작업이다.
    for gid in remove_gates:
        if gid not in task.requires_gates:
            return _fail(
                f"{task.id}: 게이트 '{gid}' 는 requires_gates에 없다 — 뗄 것이 없다 "
                f"(현재: {task.requires_gates or '없음'})"
            )
        task.requires_gates.remove(gid)
        changed.append(f"requires_gates -{gid}")
        note_lines.append(f"requires_gates -{gid}: {args.reason}")

    # ③ priority 재배정 — 등재 후 우선순위를 고칠 유일한 CLI 경로(HARN-52 후속).
    #
    # 왜 필요한가: `depends_on`과 같은 부류의 공백이었다. 등재 시점에 정한 priority가
    # 나중에 틀린 것으로 드러나도(선행 태스크가 급해졌다·차단 해소 지점이 됐다) 고칠
    # 경로가 없어 대장 손편집 외에 방법이 없었다(CLAUDE.md 금기). track(HARN-49)·
    # acceptance/gate(HARN-24)·depends(HARN-52)에 이은 마지막 필드다.
    #
    # 이전 값을 notes에 남긴다(HARN-49 관례) — 흔적 없이 덮어쓰면 왜 올렸는지 사라진다.
    if args.priority is not None:
        if not 1 <= args.priority <= 5:
            return _fail(f"{task.id}: priority는 1(최고)~5 범위 — 받은 값 {args.priority}")
        if args.priority == task.priority:
            return _fail(f"{task.id}: priority가 이미 {args.priority} — 바꿀 것이 없다")
        priority_before = task.priority
        changed.append(f"priority {priority_before} → {args.priority}")
        note_lines.append(f"priority {priority_before} → {args.priority}: {args.reason}")
        task.priority = args.priority

    # ⑤ 트리거 면제 — HARN-72 검출기의 오탐 탈출구.
    #
    # 왜 필요한가: 검출기는 acceptance 한 문장 안의 (미래조건 + 재측정동사)를 대기 선언으로
    # 본다. 그런데 *트리거 장치를 만드는* 태스크는 그 어구를 **예시로 인용**하므로 걸린다 —
    # 실제로 HARN-72 자신이 첫 사례였다. 고칠 수 없는 위반을 지적하는 게이트는 사람이
    # 게이트를 끄게 만들므로(위 ④ 주석과 같은 이유) 탈출구를 함께 연다.
    #
    # 면제는 **코드 상수가 아니라 태스크 notes**에 사유와 함께 남는다 — 나중에 읽는 사람이
    # 왜 면제됐는지 같은 자리에서 본다(무사유 예외 금지).
    if getattr(args, "no_trigger", None):
        from trigger_declaration import EXEMPTION_MARKER

        if EXEMPTION_MARKER in task.notes:
            return _fail(f"{task.id}: 이미 트리거 면제가 기록돼 있다")
        note_lines.append(f"{EXEMPTION_MARKER} {args.no_trigger}")
        changed.append(f"트리거 면제 기록 ({args.no_trigger[:40]}…)")

    # ④ depends_on 부착 — 등재 후 의존을 붙일 유일한 CLI 경로(HARN-52).
    #
    # 왜 필요한가: notes에 "선행: X 착지 후"라고 적어도 `selector.py`는 notes를 읽지 않는다
    # — `depends_on`만 본다. 그런데 add 시점 외에 depends_on을 고칠 경로가 0건이라, 등재 후
    # 발견한 선행 관계는 **대장 손편집 외에 방법이 없었다**(CLAUDE.md 금기). `dep_declaration`
    # 게이트가 그 불일치를 red로 만드는 이상, 고칠 경로가 반드시 함께 있어야 한다 — 고칠 수
    # 없는 위반을 지적하는 게이트는 사람이 게이트를 끄게 만든다.
    #
    # 의존 *해소*의 정상 경로는 선행 태스크를 done으로 만드는 것이다. *제거*는 아래 ④-b가
    # 맡는다(HARN-67 ③) — 취소·오등재된 선행은 done이 될 일이 없으므로 정상 경로로는 못 푼다.
    for dep in args.depends or []:
        if dep == task.id:
            return _fail(f"{task.id}: 자기 자신을 의존으로 걸 수 없다")
        if dep in task.depends_on:
            return _fail(f"{task.id}: 의존 '{dep}' 가 이미 있다")
        if dep not in backlog.tasks:
            return _fail(
                f"{task.id}: 의존 대상 '{dep}' 가 백로그에 없다 — "
                "존재하지 않는 의존은 영구 차단이 된다(full id로 지정하라)"
            )
        # 순환 검사: dep에서 출발해 task.id에 도달하면 사이클이다. 사이클은 양쪽 태스크를
        # 영구 착수 불가로 만들고, validate가 잡더라도 그때는 이미 대장이 오염된 뒤다.
        stack, seen = [dep], set()
        while stack:
            cur = stack.pop()
            if cur == task.id:
                return _fail(f"{task.id}: 의존 '{dep}' 는 순환을 만든다 ({dep} → … → {task.id})")
            if cur in seen:
                continue
            seen.add(cur)
            nxt = backlog.tasks.get(cur)
            if nxt is not None:
                stack.extend(nxt.depends_on)
        task.depends_on.append(dep)
        changed.append(f"depends_on +{dep}")

    # ④-b depends_on 제거 (HARN-67 ③) — 취소·오등재된 선행을 떼는 유일한 CLI 경로.
    #
    # 왜 필요한가: selector는 cancelled 선행을 해소로 치지 않는다(결정 불가 → 차단 유지).
    # 그러면 오등재를 cancel로 바로잡는 순간 그것에 의존하던 정상 태스크가 영구 차단되는데,
    # 부착만 있고 제거가 없으면 정정은 cancel+재등재뿐이고 번호가 소모된다(2026-09-05
    # EOS-96 → EOS-97). 제거된 id는 이벤트(removed_depends)에 남는다. HARN-53 되먹임 가드는
    # 그대로 적용된다 — notes에 "선행: X"가 남은 채 X를 떼면 새 미집행 선언이 되므로 같은
    # 호출에서 --notes-replace로 어구를 함께 고쳐야 한다.
    for dep in remove_depends:
        if dep not in task.depends_on:
            return _fail(
                f"{task.id}: 의존 '{dep}' 는 depends_on에 없다 — 뗄 것이 없다"
                f"(full id로 지정하라 · 현재: {task.depends_on or '없음'})"
            )
        task.depends_on.remove(dep)
        changed.append(f"depends_on -{dep}")
    if remove_depends:
        # notes 요약에는 **건수만** — 제거한 ID는 이벤트(removed_depends)와 stdout에만 남긴다.
        # 실측(2026-09-07): `depends_on -T7-01-blocker: 오등재 선행 제거`처럼 ID와 사유를 한
        # 줄에 적으면 사유 속 "선행" 낱말이 스캐너 창(60자)에서 그 ID를 새 선언으로 잡아
        # amend 자신이 HARN-53 가드에 거부됐다. 제거 사유에 "선행"이 들어가는 것은 가장
        # 자연스러운 경우라 표기 규칙으로 피할 수 없다 — ⑦ notes 치환의 원문 비인용과 같은 원칙.
        note_lines.append(f"depends_on 제거 {len(remove_depends)}건: {args.reason}")

    # ⑤ track 이관 — 이전 값을 notes에 남긴다(HARN-49: 흔적 없이 덮어쓰면 왜 옮겼는지 사라진다)
    if args.track:
        if args.track == task.track:
            return _fail(f"{task.id}: track이 이미 '{args.track}' — 바꿀 것이 없다")
        if args.track not in backlog.tracks:
            known = ", ".join(sorted(backlog.tracks))
            return _fail(f"track '{args.track}' 은 tracks.yaml에 없다. 등록된 트랙: {known}")
        track_before = task.track
        changed.append(f"track {track_before} → {args.track}")
        note_lines.append(f"track {track_before} → {args.track}: {args.reason}")
        task.track = args.track

    # ⑥ eos_priority — 등급 지정·정정. 기존 489건 백필의 **유일한 합법 경로**다
    #    (대장 손편집 금지 · 그랜드파더 만료 시 validate가 미지정을 위반으로 만든다).
    #    P0 예산은 여기서 강제하지 않는다: add의 교환제와 달리 amend는 *분류*이고,
    #    분류 결과 P0가 예산을 넘는다면 그것은 우회가 아니라 **보고해야 할 사실**이다
    #    (여기서 막으면 사람이 등급을 낮춰 적어 예산을 맞추게 된다 — 측정의 자기기만).
    if args.eos_priority:
        if args.eos_priority not in EOS_PRIORITIES:
            return _fail(
                f"{task.id}: --eos-priority '{args.eos_priority}' 미등록 "
                f"(허용: {list(EOS_PRIORITIES)})"
            )
        if args.eos_priority == task.eos_priority:
            return _fail(f"{task.id}: eos_priority가 이미 '{args.eos_priority}' — 바꿀 것이 없다")
        eos_before = task.eos_priority
        task.eos_priority = args.eos_priority
        changed.append(f"eos_priority {eos_before or 'null'} → {args.eos_priority}")
        note_lines.append(
            f"eos_priority {eos_before or 'null'} → {args.eos_priority}: {args.reason}"
        )

    # ⑦ artifacts 사후 보정 — append만 (HARN-57 ①).
    #
    # 왜 필요한가: `done`은 종결 상태라 재실행이 거부되고(done→done 전이 불가) `amend`에는
    # `--artifact`가 없었다. 그래서 done을 PR 생성 *전에* 부른 순간 잘못된 증적이 영구
    # 고정된다 — HARN-44의 artifacts에 "커밋 예정(PR 동반)"이 남고 실제 PR #965는 대장에서
    # 추적 불가가 됐다. 고칠 수 없는 위반을 지적하는 게이트는 사람이 게이트를 끄게 만든다.
    #
    # **왜 `done`의 사후 플래그가 아니라 `amend`인가**: `done`은 *상태 전이* verb다. 종결된
    # 태스크에 다시 들어갈 수 있는 모드를 만들면 그 자체가 전이 우회 표면이 된다(위 설계
    # 원칙 2가 닫아 둔 바로 그것). `amend`는 이미 정정 verb이고 --reason 필수·이벤트 기록·
    # 되먹임 가드(HARN-53)를 갖추고 있어 세 원칙이 전부 이미 서 있다.
    #
    # **제거는 열지 않는다** — 증적을 지울 수 있으면 이 CLI가 위조 표면이 된다.
    for raw in getattr(args, "artifacts", None) or []:
        bad = _reject_meaningless(task.id, "증적", raw)
        if bad:
            return _fail(bad)
        text = raw.strip()
        if text in task.artifacts:
            return _fail(f"{task.id}: 동일한 증적이 이미 있다 — {text[:60]}")
        task.artifacts.append(text)
        added_artifacts.append(text)
        changed.append(f"artifacts +1 ({text[:40]})")

    # ⑧ paths 범위 정정 — 교체 (HARN-57 ④).
    #
    # 왜 append가 아닌가: 이 축의 목적은 **좁히는 것**이다. 넓게 잡은 glob이 고정되면 overlap
    # 경보가 대량 오탐이 되고(2026-09-03 MOB-20 — `src/mobile/lib/**`로 17건), 상시 오탐은
    # 병렬 세션이 경보를 무시하게 만든다(이 저장소가 이미 겪은 fail-open 습관화). append로는
    # 넓은 패턴을 좁힐 방법이 자체가 없으므로 교체가 이 축의 본질이다.
    #
    # 대신 **이전 값을 notes에 남긴다**(HARN-49의 track 선례) — 흔적 없이 덮어쓰면 원래 무엇을
    # 선언했는지, 왜 좁혔는지가 사라진다. 지정한 `--path` 전체가 새 목록이 된다(부분 갱신 아님).
    if getattr(args, "paths", None):
        new_paths: list[str] = []
        for raw in args.paths:
            bad = _reject_meaningless(task.id, "paths 패턴", raw)
            if bad:
                return _fail(bad)
            text = raw.strip()
            if text in new_paths:
                return _fail(f"{task.id}: --path '{text}' 가 한 호출에 중복 지정됐다")
            new_paths.append(text)
        if new_paths == task.paths:
            return _fail(
                f"{task.id}: paths가 이미 {new_paths} — 바꿀 것이 없다 "
                "(지정한 목록이 새 paths 전체가 된다)"
            )

        # HARN-81 — 축소가 무증상이면 미탐이 된다. 두 가지를 한다: ⓐ제거분을 **항상 열거**하고
        # ⓑ "덧붙이려다 교체된" 형태만 **거부**한다.
        #
        # 왜 모든 축소를 거부하지 않는가: 좁히기가 이 축의 목적이고 실사용의 절반이다
        # (HARN-57). 절반에서 매번 요구되는 확인 플래그는 사람이 항상 붙이게 되고, 항상
        # 붙이는 플래그는 가드가 아니다 — 이 저장소가 fail-open 경고에서 겪은 습관화가
        # fail-closed 쪽으로 뒤집힌 형태일 뿐이다.
        #
        # 그래서 **사고의 형태**만 거부한다: 잃은 파일과 얻은 파일이 **동시에** 있는 경우.
        # 순수 축소(잃기만)는 의도적 좁히기이고, 순수 확장(얻기만)은 위험 방향이 아니다.
        # 둘이 같이 나면 "새 경로를 덧붙이려 했는데 교체라 옛것이 사라진" SEC-32 형태다.
        dropped, lost_scope, gained_scope, delta_error = _path_scope_delta(
            root, task.id, task.paths, new_paths
        )
        if delta_error:
            # 침묵 실패 금지 — 타입명을 남긴다. 파일 전개 없이는 ⓑ 판정이 불가능하므로
            # 거부는 못 하지만 ⓐ 열거는 아래에서 그대로 수행된다(가드가 반만 산다).
            print(
                f"  ⚠ 범위 델타 계산 실패({delta_error}) — 축소 거부 판정은 생략, "
                "제거 목록만 열거한다",
                file=sys.stderr,
            )
        if lost_scope and gained_scope and not getattr(args, "drop_scope", False):
            return _fail(
                f"{task.id}: paths 교체로 **기존 범위가 사라지면서 새 범위가 늘었다** — "
                "덧붙이려다 교체된 형태다(--path는 append가 아니라 교체·HARN-57).\n"
                f"  제거되는 패턴 {len(dropped)}건: {dropped}\n"
                f"  범위를 잃는 패턴 {len(lost_scope)}건: {lost_scope}\n"
                f"  새로 잡는 영역 {len(gained_scope)}건: {gained_scope}\n"
                "  paths는 병렬 세션 겹침 탐지의 유일한 입력이라 좁아지면 *미탐*이 된다 — "
                "경보가 안 뜨므로 사람이 알아챌 기회 자체가 없다(HARN-81).\n"
                "  의도한 것이라면: 남길 경로를 **전부** --path로 다시 명시하거나, "
                "정말 버리는 것이면 --drop-scope 를 붙여라(사유는 --reason에 남는다)."
            )

        paths_before = list(task.paths)
        task.paths = new_paths
        changed.append(f"paths {paths_before} → {new_paths}")
        note_lines.append(f"paths {paths_before} → {new_paths}: {args.reason}")
        # ⓐ 제거분 전건 열거 — 순수 축소(정당한 좁히기)에서도 조용하지 않게 한다.
        # 정상(유지·확장) 케이스에서는 이 줄이 아예 안 나온다(대조군 — 양쪽이 같은 화면이면
        # 검증이 아니라 위장이다).
        if dropped:
            changed.append(f"paths 제거 {len(dropped)}건: {dropped}")
            note_lines.append(f"paths 제거 {len(dropped)}건: {dropped}")

    # ⑨ title 정정 — 교체 (HARN-57 ⑤).
    #
    # **paths보다 위험도가 높다**: SessionStart 브리핑과 `next`가 노출하는 것은 title 한 줄이다.
    # 범위가 정정된 태스크의 옛 제목이 남으면 다음 세션이 *정정 전 처방*을 읽고 착수한다 —
    # MOB-20이 acceptance로 범위를 고친 뒤에도 title이 옛 처방("POST /v1/me/attempts 클라 호출
    # 착지")을 1순위 후보로 노출했고, 그대로 구현했으면 attempt·숙달 이중 적재였다.
    #
    # paths와 같은 이유로 교체이고, 같은 이유로 이전 값을 notes에 남긴다.
    if getattr(args, "title", None) is not None:
        bad = _reject_meaningless(task.id, "title", args.title)
        if bad:
            return _fail(bad)
        new_title = args.title.strip()
        if new_title == task.title:
            return _fail(f"{task.id}: title이 이미 '{new_title}' — 바꿀 것이 없다")
        title_before = task.title
        task.title = new_title
        changed.append(f"title '{title_before}' → '{new_title}'")
        note_lines.append(f"title '{title_before}' → '{new_title}': {args.reason}")

    # `--no-pr` 사후 해소 (HARN-57 ②) — incomplete/ci-red로 종결한 뒤 PR이 실제로 열렸으면
    # 그 사실이 대장에 남아야 한다. 별도 플래그를 두지 않고 *증적에서 파생*시키는 이유:
    # 사람이 기억해야 하는 플래그를 하나 더 만들면 그것이 다음 망각 지점이 된다. PR 참조를
    # 담은 증적을 붙이는 행위 자체가 해소의 증거다.
    no_pr_resolved: str | None = None
    if added_artifacts and _has_pr_reference(added_artifacts):
        no_pr_resolved = _pending_no_pr_reason(task.notes)

    # ⑩ notes 치환 (HARN-67 ⑥) — notes를 고칠 유일한 CLI 경로. 반드시 `_append_note`로 사유를
    #    붙이기 **전의** notes에 적용한다 — 사유 문장이 구문자를 담고 있어도 그것이 치환되면
    #    안 되고, 정정 스탬프는 치환 결과 뒤에 와야 이력 순서가 맞다.
    #
    # 구문자는 **정확히 1회** 등장해야 한다. 0회면 "치환 0건인데 exit 0"이 되어 정정이 된
    # 것처럼 보인다(CLAUDE.md "주입 자체의 실재" 규칙의 CLI판 — 적용되지 않은 뮤테이션이
    # 통과로 위장된 사고와 같은 형태). 2회 이상이면 어느 쪽인지 결정 불가다. 신문자는 빈
    # 문자열을 허용한다(어구 삭제). 원문(old/new)은 **이벤트 대장에만** 남긴다 — notes에
    # 인용하면 스캐너가 인용문 속 선행 어구를 다시 잡는 되먹임이 된다.
    notes_replace_record: dict[str, str] | None = None
    if notes_replace:
        old_text, new_text = notes_replace
        if not old_text:
            return _fail(f"{task.id}: --notes-replace 구문자가 비어 있다 — 무엇을 바꿀지 지정하라")
        hits = task.notes.count(old_text)
        if hits == 0:
            return _fail(
                f"{task.id}: --notes-replace 구문자가 notes에 없다 — 치환 0건은 성공이 아니다"
                "(현재 notes에서 그대로 복사해 다시 지정하라)"
            )
        if hits > 1:
            return _fail(
                f"{task.id}: --notes-replace 구문자가 notes에 {hits}회 등장 — 모호하다"
                "(한 곳만 가리키도록 구문자를 앞뒤로 늘려라)"
            )
        task.notes = task.notes.replace(old_text, new_text, 1)
        changed.append(f"notes 치환 1건 ({len(old_text)}자 → {len(new_text)}자)")
        note_lines.append(f"notes 치환 — {args.reason}")
        notes_replace_record = {"old": old_text, "new": new_text}

    # 되먹임 가드의 마스크 — 기본은 정정 *전* 위반(기존 위반은 이 명령의 책임이 아니다).
    # 치환이 있으면 마스크를 (정정 전) ∩ (치환 직후·사유 append 전)으로 좁힌다: 치환이 없앤
    # 쌍이 마스크에 남아 있으면 --reason이 같은 쌍을 다시 만들어도 "기존 위반"으로 오판돼
    # amend는 exit 0인데 audit-deps는 red인 채 남는다 — 대장은 손편집 금지라 거짓 성공을 낸
    # 정정 경로는 갈 곳이 없다(PR #1025 Codex P2-3). 치환이 *만든* 쌍은 정정 전에 없었으므로
    # 교집합에도 없다 — 양쪽 다 새 위반으로 잡힌다.
    feedback_mask = _pre_amend_findings
    if notes_replace:
        post_replace = {
            (f.task_id, f.referenced)
            for f in dep_declaration.find_undeclared_dependencies(backlog.tasks)
            if f.task_id == task.id
        }
        feedback_mask = {p for p in _pre_amend_findings if p[0] != task.id or p in post_replace}

    task.notes = _append_note(
        # note_lines를 **전부** 남긴다. 예전 구현은 `note_lines[0]`만 기록해 다축 정정
        # (`--title` + `--priority` 등)에서 뒤 축의 *이전 값*이 조용히 사라졌다 — 이전 값을
        # 남기는 것이 교체 축의 유일한 안전장치인데 그것이 침묵으로 유실되는 형태였다.
        task.notes,
        "\n".join(note_lines) if note_lines else args.reason,
        "정정",
    )
    if no_pr_resolved is not None:
        task.notes = _append_note(
            task.notes,
            f"{no_pr_resolved} → PR 증적 보강: {', '.join(added_artifacts)}",
            _NO_PR_RESOLVED_TAG,
        )
    task.updated = _today()

    errors = store.validate_backlog(backlog)
    own_errors = [e for e in errors if args.id in e]
    if own_errors:
        for e in own_errors:
            print(f"  · {e}", file=sys.stderr)
        return _fail(f"{args.id}: 스키마/무결성 위반으로 정정 거부")

    # HARN-53: `--reason`은 notes에 append되고 notes는 의존 선언 스캐너의 입력이다. 그래서
    # *정정 사유가 새 위반을 만드는* 되먹임이 실재한다 — 실측: "…'선결'이라 선언한 방향을
    # 부착한다" 같은 사유가 그 문장 안의 태스크 ID를 새 선행 선언으로 만들었다(2건).
    # notes는 append 전용이라 되돌릴 CLI 경로가 없으므로 **쓰기 전에** 막는다.
    # 판정은 "이 정정이 *새로* 만든 findings"만 — 기존 위반은 이 명령의 책임이 아니다.
    # HARN-67: depends 제거·notes 치환도 같은 되먹임을 만들 수 있다(notes의 "선행: X"가 남은
    # 채 X를 떼면 미집행 선언이 된다) — 그 경우의 정정 경로를 힌트로 덧붙인다.
    feedback_hint = ""
    if remove_depends or notes_replace:
        feedback_hint = (
            "depends 제거·notes 치환이 원인이면 같은 호출에서 --notes-replace로 선행 어구를 "
            "함께 고쳐라."
        )
    if _fail_on_reason_feedback(backlog, task.id, feedback_mask, hint=feedback_hint):
        return 1

    store.save_task(root, task)
    event_extra: dict[str, object] = {"reason": args.reason, "changed": changed}
    if track_before is not None:
        # track 축은 field/before/after도 함께 남긴다 — HARN-49가 쓰던 형태를 깨지 않는다.
        event_extra.update(field="track", before=track_before, after=args.track)
    # HARN-67 — 제거·치환은 notes에 원문을 남기지 않으므로 이벤트가 유일한 복원 근거다.
    if remove_depends:
        event_extra["removed_depends"] = remove_depends
    if remove_gates:
        event_extra["removed_gates"] = remove_gates
    if notes_replace_record is not None:
        event_extra["notes_replace"] = notes_replace_record
    if added_artifacts:
        # done 이벤트의 `artifacts` 키와 같은 이름으로 남긴다 — 증적의 출처(done인가 사후
        # 보정인가)는 action(`done`/`amend`)이 이미 구분하므로 키를 새로 만들 이유가 없다.
        event_extra["artifacts"] = added_artifacts
    if no_pr_resolved is not None:
        # 사후 해소는 **이벤트에도** 남긴다. notes만 남기면 "PR 없이 끝난 태스크" 집계가
        # 이벤트 대장만 보는 도구에서 영영 틀린 채로 남는다.
        event_extra["no_pr_resolved"] = no_pr_resolved
    store.append_event(root, "amend", task.id, **event_extra)
    print(f"✎ {task.id} 정정 — {args.reason}")
    for c in changed:
        print(f"  · {c}")
    if no_pr_resolved is not None:
        print(f"  PR 보류 해소: '{no_pr_resolved}' → 증적에 PR 참조가 들어왔다")

    # 제거·탈착이 실제로 착수 가능성을 바꿨는지 그 자리에서 보여준다(정본화 ≠ 집행) — 다른
    # 사유로 여전히 막혀 있으면 "뗐는데 왜 안 나오지"를 다시 조사하게 되기 때문이다.
    if (remove_depends or remove_gates) and task.status == "todo":
        exclusion = selector.classify_todo(backlog, task)
        if exclusion is None:
            print("  착수 가능 후보가 됐다 — `next --n 500 --json`(전건)으로 직접 확인하라")
        else:
            print(f"  ⚠ 여전히 후보 아님: {exclusion.reason} {exclusion.detail}")

    # 정정이 실제로 착수 가능성을 바꿨는지 그 자리에서 보여준다
    # (정본화 ≠ 집행 — 사람이 확인해야 한다).
    if track_before is not None:
        old_gate = (
            backlog.tracks[track_before].entry_gate if track_before in backlog.tracks else None
        )
        new_gate = backlog.tracks[args.track].entry_gate
        if old_gate and not new_gate:
            print(f"  진입 게이트 해소: '{old_gate}' → 없음 (이제 start 가능 — 직접 확인하라)")
        elif new_gate:
            print(f"  ⚠ 새 트랙에도 진입 게이트가 있다: '{new_gate}'")
    if paths_before is not None:
        _print_overlap_delta(root, backlog, task, paths_before)
    return 0


def _path_scope_delta(
    root: Path, task_id: str, before: list[str], after: list[str]
) -> tuple[list[str], list[str], list[str], str | None]:
    """paths 교체의 축소분 — (제거된 패턴, 범위를 잃은 패턴, 새 영역 패턴, 계산실패 사유).

    **왜 필요한가 (HARN-81)**: `--path`는 append가 아니라 교체다(HARN-57 ④ — 좁히는 것이
    이 축의 목적이라 append로는 좁힐 방법이 없다). 그런데 교체가 **무증상**이라, 신규 경로만
    넘기면 기존 경로가 조용히 사라진다. 2026-09-07 SEC-32에서 실제로 났다 — 신규 6건만 넘겨
    원 7건이 소실됐고 구현자가 우연히 알아채 13건을 다시 명시해 복원했다(설계가 아니라 운).

    **왜 위험한가**: `paths`는 병렬 세션 겹침 탐지의 유일한 입력이다. 넓어지면 오탐이지만
    (HARN-59가 다룬 축 — 시끄러워서 자가교정된다) **좁아지면 미탐**이고, 미탐은 경보가 아예
    안 뜨므로 사람이 알아챌 기회 자체가 없다. 두 세션이 같은 파일을 모르고 병렬 구현하는
    형태(2026-07-27 OPS-07 735줄 폐기 · 2026-09-06 MP-04 전량 폐기)의 재발 경로다.

    **판정은 `pathscope.overlap`으로 한다** — `start`·`overlap`이 쓰는 것과 **같은** 함수다.
    여기서 따로 세면 두 숫자가 갈라진다(`_print_overlap_delta`가 세운 규약을 승계).
    파일 차집합으로 재지 *않는* 이유: 패턴이 아직 아무 파일도 안 덮을 수 있고(신규 디렉터리),
    그러면 파일 기준 판정은 **정상·사고 양쪽에서 0건**을 내 공허하게 통과한다(실측 —
    시드 저장소에서 이 가드가 그렇게 뚫렸다. CLAUDE.md "스캔 0건은 실패").
    `overlap`은 정적 프리픽스 축을 함께 보므로 파일이 0건이어도 판정이 산다.

    · *잃은 패턴* = 제거됐고, 새 목록의 **어느 패턴과도 더는 겹치지 않는** 것.
      (`lib/**` → `lib/core/**`처럼 새 패턴이 옛 범위 안이면 겹치므로 잃은 것으로 세지 않는다 —
       그건 세분화이지 포기가 아니다.)
    · *새 영역 패턴* = 옛 목록의 어느 패턴과도 겹치지 않는 신규 패턴.

    실패해도 판정을 멈추지 않는다(fail-open) — 대신 사유를 돌려주고 호출부가 타입명과 함께
    경고한다(침묵 실패 금지). 전개가 불가능해도 *제거된 패턴 목록*은 정확하므로 열거는 산다.
    """
    removed = [p for p in before if p not in after]
    added = [p for p in after if p not in before]
    try:
        files = pathscope.repo_files(root)
    except Exception as exc:  # noqa: BLE001 — 전개 실패가 정정을 막으면 사람이 가드를 끈다
        return removed, [], [], type(exc).__name__
    lost = [
        p
        for p in removed
        if after and pathscope.overlap(task_id, [p], task_id, after, files) is None
    ]
    gained = [
        p
        for p in added
        if before and pathscope.overlap(task_id, [p], task_id, before, files) is None
    ]
    return removed, lost, gained, None


def _print_overlap_delta(root: Path, backlog, task, paths_before: list[str]) -> None:
    """paths 정정 전/후의 겹침 건수를 그 자리에서 보여준다 (HARN-57 ④).

    **왜 세는가**: ④의 목적은 오탐 감소인데, "정정했다"만 출력하면 그 목적이 달성됐는지 아무도
    모른다. 알고리즘을 붙였으면 *작동한 비율*을 말해야 한다는 이 저장소의 원칙(CLAUDE.md
    "작동 신호 없는 알고리즘 부착 금지")의 적용이다. 판정 자체는 `start`·`overlap`이 쓰는 것과
    **같은** `pathscope.overlap`을 쓴다 — 여기서 따로 세면 두 숫자가 갈라진다.

    **차단이 아니라 보고다**: 겹침이 늘어나는 정정도 정당할 수 있다(범위를 실제로 넓혀야 하는
    경우). 사람이 보고 판단한다.
    """
    try:
        files = pathscope.repo_files(root)
        others = [
            t
            for t in _overlap_candidates(
                backlog, remote_claimed=None, session=None, include_todo=True
            )
            if t.id != task.id and t.paths
        ]
        before_n = sum(
            1 for o in others if pathscope.overlap(task.id, paths_before, o.id, o.paths, files)
        )
        after_n = sum(
            1 for o in others if pathscope.overlap(task.id, task.paths, o.id, o.paths, files)
        )
    except Exception as exc:  # noqa: BLE001 — 보고용 부가 출력이 정정을 실패시키면 안 된다
        # 침묵 실패 금지 — 예외 *타입명*을 남긴다(무타입 경고는 8일 무증상 전멸의 원인이었다).
        print(f"  ⚠ 겹침 재계산 실패({type(exc).__name__}) — 정정 자체는 반영됐다")
        return
    verdict = "감소" if after_n < before_n else ("증가" if after_n > before_n else "변화 없음")
    print(f"  겹침 후보 {before_n}건 → {after_n}건 ({verdict}, 비교 대상 {len(others)}건)")


def _stage_outliers_on_gated_tracks(backlog: Backlog) -> list[str]:
    """진입 게이트가 있는 트랙에서 stage가 다른 모든 소속 태스크보다 앞서는 태스크 (HARN-49 ⑤).

    **잡으려는 결함**: 트랙을 잘못 붙이면 그 트랙의 `entry_gate`를 상속해 태스크가 영구
    착수 불가가 된다. 자기 stage가 게이트가 지키는 시기보다 *앞선다면* 그 태스크는 그
    트랙 소속일 수 없다 — S1-16이 stage S1인데 E축(S5 게이트) 트랙에 있었다.

    **게이트 id를 파싱하지 않는다**(`G-s5-...`의 's5'를 읽는 방식은 명명 관례에 의존해
    깨지기 쉽다). 대신 `stage_order`와 *같은 트랙 다른 태스크들*의 stage만 쓴다 — 어떤
    태스크의 stage가 동료 전원보다 엄격히 앞서면 그 태스크가 이질적이라는 뜻이다.

    **경고이지 오류가 아니다**: 의도적으로 이른 stage를 붙이는 경우를 막지 않는다. 또한
    `add` 거부로 만들지 않은 이유는 — 이 결함은 *이미 등재된* 태스크에서 발견되므로
    등재 시점 거부로는 S1-16 같은 기존 건을 하나도 잡지 못한다.

    실측(2026-08-31·480태스크): 적중 1건(S1-16), 오탐 0건.
    """
    rank = {stage: i for i, stage in enumerate(backlog.stage_order)}
    out: list[str] = []
    for name, track in backlog.tracks.items():
        if not getattr(track, "entry_gate", None):
            continue
        members = [t for t in backlog.tasks.values() if t.track == name]
        if len(members) < 2:
            continue  # 비교 대상이 없으면 이질성을 말할 수 없다
        for task in members:
            mine = rank.get(task.stage)
            peers = [rank.get(o.stage) for o in members if o.id != task.id]
            if mine is None or any(p is None for p in peers):
                continue  # stage_order 밖 값은 스키마 검증이 따로 잡는다
            if all(mine < p for p in peers):  # type: ignore[operator]
                out.append(
                    f"{task.id}: stage={task.stage} 인데 트랙 '{name}'(진입 게이트 "
                    f"{track.entry_gate})의 다른 태스크 전원보다 앞선다 — 트랙 오분류 의심. "
                    f"정정: backlog.py amend {task.id} --track <올바른 트랙> --reason ..."
                )
    return out


def cmd_rename(root: Path, args: argparse.Namespace) -> int:
    """태스크 ID 개명 — 번호 충돌의 **유일한 정정 경로** (HARN-100).

    왜 필요한가: `validate`의 번호 충돌 remedy는 "하나를 다음 빈 번호로 개명하라"인데
    그 개명을 수행할 명령이 없었다. 실제로 충돌이 났을 때(2026-09-12 `OPS-73`)
    `add`(새 번호) + 구 파일 `git rm` + `start` 재claim으로 우회했고, 그 과정에서 구
    태스크의 이벤트 이력과 원격 claim이 새 ID로 이어지지 않았다. **고칠 수 없는 위반을
    지적하는 게이트는 사람이 게이트를 끄게 만든다**(`EOS-62`의 `amend --depends` 부재와
    같은 형태).

    무엇을 함께 옮기는가 — 옮기는 것과 **옮기지 않는 것**을 둘 다 stdout에 낸다
    (조용한 부분 이행 금지):

      옮긴다   ① 태스크 YAML 파일명과 `id` 필드
               ② 다른 태스크의 `depends_on` 안의 구 ID (전수 · 건수 출력)
               ③ 원격 claim — 구 ID 해제, `in_progress`면 새 ID로 재claim
      안 옮긴다 ④ **과거 이벤트 기록**. 이벤트 대장은 append-only이고(HARN-20 사고 이후의
                 설계), 과거 기록의 ID를 고쳐 쓰면 "그때 무엇이 일어났는가"가 사라진다.
                 대신 `rename` 이벤트 한 건을 append해 구↔신을 잇는다 — 추적은 그 링크로
                 하고, 이 사실을 실행 때마다 화면에 적는다.

    프리픽스 변경은 막지 않는다(`OPS-73-x` → `HARN-100-y` 허용). 번호 충돌 검사는
    `add`와 **같은 함수**(`_id_number_conflict`)를 거치므로 판정이 갈라지지 않는다.
    """
    backlog, _ = _load(root)
    old = backlog.tasks.get(args.old_id)
    if old is None:
        return _fail(f"태스크 '{args.old_id}' 없음 — 개명할 대상이 없다")
    if args.new_id == args.old_id:
        return _fail("구 ID와 새 ID가 같다 — 개명할 것이 없다")
    if args.new_id in backlog.tasks:
        return _fail(
            f"새 ID '{args.new_id}' 가 이미 존재한다 — 개명은 빈 ID로만 간다"
            "(기존 태스크와 합치려면 한쪽을 cancel하라)"
        )
    if not TASK_ID_RE.match(args.new_id):
        return _fail(
            f"새 ID '{args.new_id}' 가 ID 규약을 벗어난다 — " f"형식: {TASK_ID_RE.pattern}"
        )
    err, remote_ok = _id_number_conflict(root, backlog, args.new_id, verb="rename")
    if err:
        return _fail(err)

    old_path = store.backlog_dir(root) / "tasks" / f"{old.id}.yaml"
    prev_session, prev_status = old.session, old.status

    # ② 구 ID를 선행으로 가리키는 다른 태스크 — 전수 갱신. 여기서 빠뜨리면 `audit-deps`가
    #    존재하지 않는 선행을 지목하고, 그 태스크는 영원히 착수 후보에서 빠진다.
    updated_dependents: list[str] = []
    for other in backlog.tasks.values():
        if other.id == old.id or old.id not in other.depends_on:
            continue
        other.depends_on = [args.new_id if d == old.id else d for d in other.depends_on]
        other.updated = _today()
        store.save_task(root, other)
        updated_dependents.append(other.id)

    # ① 태스크 자신 — 새 파일을 먼저 쓰고 구 파일을 지운다. 순서가 반대면 중간에 죽었을 때
    #    태스크가 통째로 사라진다(새 파일도 구 파일도 없는 상태). 이 순서면 최악이 중복이고,
    #    중복은 validate가 번호 충돌로 즉시 잡는다 — 소실보다 낫다.
    old.id = args.new_id
    old.notes = _append_note(old.notes, f"{args.old_id} → {args.new_id}: {args.reason}", "개명")
    old.updated = _today()
    new_path = store.save_task(root, old)
    old_path.unlink(missing_ok=True)

    store.append_event(
        root,
        "rename",
        args.new_id,
        previous_id=args.old_id,
        reason=args.reason,
        updated_dependents=updated_dependents,
    )

    # ③ 원격 claim — 구 ID의 claim은 이제 존재하지 않는 태스크를 가리킨다.
    _release_remote_claim(root, args.old_id, prev_session)
    reclaimed = ""
    if prev_status == "in_progress":
        result = remote_claims.claim(root, args.new_id, prev_session or store.current_branch(root))
        reclaimed = result.status
        if result.status not in ("ok", "offline"):
            print(
                f"⚠ 새 ID 원격 claim 실패({result.status}): {result.message} — "
                f"`backlog.py start {args.new_id}`로 다시 잡으라",
                file=sys.stderr,
            )

    print(f"✎ {args.old_id} → {args.new_id} 개명 — {args.reason}")
    print(f"  · 태스크 파일: {old_path.name} → {new_path.name}")
    if updated_dependents:
        print(f"  · depends_on 갱신 {len(updated_dependents)}건: {', '.join(updated_dependents)}")
    else:
        print("  · depends_on 갱신 0건 (이 태스크를 선행으로 가리킨 태스크 없음)")
    if prev_status == "in_progress":
        print(f"  · 원격 claim: 구 ID 해제 + 새 ID 재claim({reclaimed or '미시도'})")
    # 안 옮긴 것을 반드시 말한다 — 조용한 부분 이행이 이 CLI의 최대 실패 모드다.
    print(
        f"  ⚠ 과거 이벤트 기록의 '{args.old_id}' 참조는 **옮기지 않았다**(append-only 대장 — "
        f"고쳐 쓰면 그때의 사실이 사라진다). `rename` 이벤트가 구↔신을 잇는다."
    )
    print(
        f"  ⚠ 문서·커밋 메시지·PR 본문의 '{args.old_id}' 참조도 옮기지 않았다 — "
        f"이 CLI 범위 밖이다. 필요하면 손으로 확인하라: git grep -n {args.old_id}"
    )
    if not remote_ok:
        print("  · 번호 충돌 검사: 로컬만 통과 — 머지 시 validate가 2선 방어한다")
    return 0


def cmd_audit_deps(root: Path, args: argparse.Namespace) -> int:
    """의존 선언↔집행 대조 (HARN-52) — exit 0/1.

    notes가 순서를 단언하는 어구로 타 태스크를 선행으로 지목하는데 `depends_on`이 비어 있으면
    위반이다. `selector.py`는 notes를 읽지 않으므로, 그런 태스크는 사람이 "막아 뒀다"고 믿는
    동안 다른 세션에 착수 가능 후보로 노출된다(#911 리뷰 P2 · EOS-62 실사례).

    판정은 exit code로 한다(CLAUDE.md: 출력 문자열로 통과 선언 금지). `--all`은 그랜드파더를
    무시하고 전건을 보여 준다 — 레거시 분류(HARN-53) 작업용이며 판정에는 쓰지 않는다.
    """
    backlog, _ = _load(root)
    expiry = dep_declaration.find_expiry_violations(backlog.tasks)
    soft_violations = dep_declaration.find_soft_declaration_violations(backlog.tasks)
    findings = dep_declaration.find_undeclared_dependencies(
        backlog.tasks, apply_exemptions=not args.all
    )
    exempt = len(dep_declaration.LEGACY_EXEMPT)
    soft = len(dep_declaration.SOFT_DECLARED)

    if args.all:
        # 감사 모드 — 그랜드파더분까지 전부 보여 주되 판정은 하지 않는다(항상 exit 0).
        print(f"[감사] 전건 스캔 — 위반 {len(findings)}건 (그랜드파더 {exempt}건 포함)")
        for f in findings:
            print(f"  · {f.render()}")
        # 소프트 분류는 스캔에서 억제되므로 여기서 **따로** 보여 준다 — 안 보여 주면
        # "고칠 것 없음" 판정이 보이지 않게 쌓인다(HARN-53).
        print(f"[감사] 소프트 선행 분류 {soft}건 (하드가 *틀린* 경우 — 만료 없음):")
        for (task_id, ref), (code, reason) in sorted(dep_declaration.SOFT_DECLARED.items()):
            print(f"  · {task_id} → {ref} [{code}] {reason}")
        return 0

    if not findings and not expiry and not soft_violations:
        print(
            f"✔ 의존 선언↔집행 green — 위반 0건 "
            f"(레거시 그랜드파더 {exempt}건 · 소프트 분류 {soft}건)"
        )
        return 0

    if expiry:
        print(f"❌ 그랜드파더 만료 계약 위반 {len(expiry)}건:", file=sys.stderr)
        for v in expiry:
            print(f"  · {v}", file=sys.stderr)
    if soft_violations:
        print(f"❌ 소프트 선행 분류 계약 위반 {len(soft_violations)}건:", file=sys.stderr)
        for v in soft_violations:
            print(f"  · {v}", file=sys.stderr)
    if findings:
        print(f"❌ 선언되었으나 집행되지 않은 의존 {len(findings)}건:", file=sys.stderr)
        for f in findings:
            print(f"  · {f.render()}", file=sys.stderr)
        print(
            "\n정정: python3 scripts/harness/backlog.py amend <id> "
            "--depends <선행-태스크-full-id> --reason '...'\n"
            "의존이 아니라 단순 참조라면 notes의 표현을 고쳐라(선행/선결 어구 제거): "
            "amend <id> --notes-replace '<구문자>' '<신문자>' --reason '...' (HARN-67 ⑥).\n"
            "하드가 *틀린* 경우(방향 반대·택일·로드맵 순서 위반·과거 사실·오탐 ID)는 "
            "dep_declaration.SOFT_DECLARED에 사유 코드와 근거를 함께 등재하라(HARN-53).",
            file=sys.stderr,
        )
    return 1


def cmd_validate(root: Path, args: argparse.Namespace) -> int:
    backlog, schema_errors = _load(root)
    errors = store.validate_backlog(backlog, schema_errors)
    warnings = _stage_outliers_on_gated_tracks(backlog)
    # 취소된 선행 차단 (HARN-67 ②) — 무결성 위반이 아니다(대장은 정합하다·차단은 결정 대기).
    # red로 만들면 정당한 cancel이 CI를 깨고, 그러면 사람이 cancel 대신 손편집으로 도망간다.
    # 경고로만 내되 있을 때만 낸다.
    cancelled_line = report.cancelled_dep_blocked_line(backlog)
    if not errors:
        if not args.quiet:
            print(
                f"✔ 백로그 무결성 green — 태스크 {len(backlog.tasks)}건, "
                f"게이트 {len(backlog.gates)}건, 트랙 {len(backlog.tracks)}건"
            )
        for warning in warnings:
            # 무결성 위반이 아니라 구조 의심 — exit 0을 바꾸지 않는다(경고를 오류로 승격하면
            # 의도적 배치까지 막고, 그러면 사람이 경고 자체를 끄게 된다)
            print(f"⚠ 트랙 구조 의심 — {warning}", file=sys.stderr)
        if cancelled_line:
            print(f"⚠ {cancelled_line}", file=sys.stderr)
        return 0
    print(f"❌ 무결성 위반 {len(errors)}건:", file=sys.stderr)
    for error in errors:
        print(f"  · {error}", file=sys.stderr)
    for warning in warnings:
        print(f"⚠ 트랙 구조 의심 — {warning}", file=sys.stderr)
    if cancelled_line:
        print(f"⚠ {cancelled_line}", file=sys.stderr)
    return 1


def cmd_brief(root: Path, args: argparse.Namespace) -> int:
    backlog, schema_errors = _load(root)
    errors = store.validate_backlog(backlog, schema_errors)
    policy, _ = store.load_policy(root)
    try:
        remote_claimed, remote_status = _remote_claim_map(root, policy)
    except Exception as exc:  # 훅 진입점 — 어떤 실패도 브리핑을 막지 않는다(fail-open·침묵 금지)
        remote_claimed, remote_status = {}, "error"
        print(
            f"⚠ 원격 claim 조회 실패({type(exc).__name__}) — 로컬 정보만 반영",
            file=sys.stderr,
        )

    # 장기 미머지 브랜치 경고 (HARN-13 + 2026-08-05 3분류 확장) — SessionStart 1회 비용,
    # 정보성(브리핑을 막지 않음). active_branches는 이미 계산해둔 remote_claimed의 브랜치
    # 집합을 재사용한다 — 새 원격 조회 없이 "타 세션 진행중"을 판별하기 위함.
    stale_branches: list[tuple[str, float, int, str, str]] = []
    stale_branch_status = "ok"
    stale_branch_message = ""
    pr_state_lookup_ok = True
    pr_state_lookup_error = ""
    if policy.remote_claims:
        try:
            scan = remote_claims.scan_stale_branches(
                root, active_branches=frozenset(remote_claimed.values())
            )
            stale_branch_status = scan.status
            stale_branch_message = scan.message
            pr_state_lookup_ok = scan.pr_state_lookup_ok
            pr_state_lookup_error = scan.pr_state_lookup_error
            if scan.status == "ok":
                stale_branches = [
                    (
                        s.branch,
                        s.age_days,
                        s.ahead,
                        s.status,
                        s.evidence,
                        s.partial_port,
                        s.port_scan_error,
                    )
                    for s in scan.stale
                ]
        except Exception as exc:  # 훅 진입점 — 어떤 실패도 브리핑을 막지 않는다 (fail-open)
            # 침묵 실패 금지 — 예외 타입명을 브리핑 문자열에 남긴다(훅은 stderr를 버린다).
            stale_branch_status = "error"
            stale_branch_message = f"{type(exc).__name__}: {exc}"
    else:
        stale_branch_status = "disabled"

    # 설계 문서 중복 착수 탐지 (HARN-14) — SessionStart 1회 비용, 나이 임계 없음(HARN-13의
    # 3일 임계 아래에서 새는 것이 이 스캔의 존재 이유 — 문서 중복은 착수 당일이 가장 위험).
    #
    # 2026-08-06 병렬 세션 충돌 정정: 동일 브랜치명(claude/harn-14-doc-series-duplicate-
    # detection)에서 독립 세션이 같은 태스크를 병행 구현해 커밋 41f42a82(scan_new_review_
    # docs)를 먼저 푸시했다. 그 구현은 후보 파일을 3-dot diff(`{trunk}...{ref}`, merge-base
    # 기준)로 얻는데, 이 저장소의 SQUASH 머지 관행에서는 **이미 병합된 브랜치도 오탐**한다
    # — squash는 원본 브랜치 커밋을 트렁크의 조상으로 만들지 않아 merge-base가 옛 분기점에
    # 고정되고, 그 시점 이후 트렁크에 흡수된 파일이 "신규 추가"로 계속 잡힌다(실측: 이미
    # PR #666으로 머지된 claude/whymath-gamification-design-n3mf50에 대해 3-dot은
    # gamification_module_gap_review.md를 거짓 양성으로 보고, 2-dot 직접 diff는 빈 목록을
    # 정확히 반환 — 브랜치가 삭제되지 않는 한 이 오탐은 영구화된다). 이 아래 구현(2-dot
    # 직접 diff, scan_doc_series_duplicates)을 정본으로 유지하고 3-dot 버전은 폐기한다.
    doc_series_candidates: list[tuple[str, tuple[str, ...], str]] = []
    doc_series_status = "ok"
    if policy.remote_claims:
        try:
            doc_scan = remote_claims.scan_doc_series_duplicates(root)
            doc_series_status = doc_scan.status
            if doc_scan.status == "ok":
                doc_series_candidates = [
                    (c.branch, c.files, c.last_commit_at.isoformat()) for c in doc_scan.candidates
                ]
        except Exception:  # 훅 진입점 — 어떤 실패도 브리핑을 막지 않는다 (fail-open)
            doc_series_status = "error"
    else:
        doc_series_status = "disabled"

    # 미머지 done 제외 (HARN-12 — next의 HARN-11 필터를 브리핑에도 배선). render_brief가
    # 내부에서 계산하는 후보 집합과 동일하게(layer/subject/track 미지정) 구해 그 id만
    # scan_remote_done에 묻는다 — fetch 없이 캐시 ref만(훅은 빠르고 네트워크 0이어야 함).
    # 어떤 실패도 브리핑을 막지 않는다(fail-open) — 단 판정 불가를 조용히 넘기지 않는다.
    done_excluded: dict[str, list[str]] = {}
    try:
        if policy.remote_claims:
            ready, _ = selector.candidates(backlog, remote_claimed=remote_claimed)
            if ready:
                done_map, done_status = remote_claims.scan_remote_done(root, [t.id for t in ready])
                done_excluded = {
                    tid: [f.branch for f in finishers] for tid, finishers in done_map.items()
                }
                if done_status != "ok" and not done_excluded:
                    print(
                        f"⚠ 미머지 done 탐지 불가({done_status}) — 완료분이 후보에 섞였을 수 있음",
                        file=sys.stderr,
                    )
    except Exception as exc:  # 훅 진입점 — 어떤 실패도 브리핑을 막지 않는다(fail-open·침묵 금지)
        done_excluded = {}
        print(
            f"⚠ 미머지 done 필터 실패({type(exc).__name__}) — 완료분이 후보에 섞였을 수 있음",
            file=sys.stderr,
        )

    # 브랜치 보호 라이브 확인 리마인드 (HARN-63 ④ 집행 지점) — 문서·ci.yml 대조는 둘 다
    # 저장소 *안*이라 라이브 설정이 비어도 전부 초록으로 통과한다(3회차 사고의 구조적 원인).
    # 조회는 사람만 할 수 있으므로(관리자 토큰), 기계는 "얼마나 오래 확인하지 않았는가"를 센다.
    try:
        ruleset_reminder = ruleset_drift.state_reminder(root, date.today())
    except Exception as exc:  # 훅 진입점 — 어떤 실패도 브리핑을 막지 않는다(fail-open·침묵 금지)
        ruleset_reminder = f"⚠ 브랜치 보호 확인 리마인드 실패({type(exc).__name__})"

    print(
        report.render_brief(
            backlog,
            errors,
            store.current_branch(root),
            date.today(),
            remote_claimed=remote_claimed,
            remote_status=remote_status,
            stale_branches=stale_branches,
            stale_branch_status=stale_branch_status,
            stale_branch_message=stale_branch_message,
            pr_state_lookup_ok=pr_state_lookup_ok,
            pr_state_lookup_error=pr_state_lookup_error,
            done_excluded=done_excluded,
            doc_series_candidates=doc_series_candidates,
            doc_series_status=doc_series_status,
            ruleset_reminder=ruleset_reminder,
        )
    )
    return 0


def cmd_check_stop(root: Path, args: argparse.Namespace) -> int:
    """Stop 훅 — 진행 중 태스크가 있는데 상태 갱신 없이 세션이 끝나면 차단(exit 2).

    무한 루프 방지: stop_hook_active=true(이미 이 훅이 개입한 재정지)면 즉시 통과.
    판정이 불확실한 모든 경우는 통과(exit 0) — 훅이 개발을 볼모로 잡으면 안 된다.
    """
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}
    if payload.get("stop_hook_active"):
        return 0

    branch = store.current_branch(root)
    if branch in ("unknown", "main", ""):
        return 0

    try:
        backlog, _ = _load(root)
    except Exception:
        return 0

    mine = [t for t in backlog.tasks.values() if t.status == "in_progress" and t.session == branch]

    # [무결성 게이트] 이 세션이 유발한 대장 위반이 있으면 정지를 막는다 (HARN-49).
    #
    # 왜 Stop 훅인가: 2026-08-31 실측 사고 — `validate` 가 "1세션이 2개 태스크 동시
    # claim" 위반을 정확히 냈는데, 명령을 `;` 로 이어 붙여 exit code 를 판정에 쓰지
    # 않은 채 push 했다. 2선 방어인 CI harness-integrity 잡은 그 push 에 **트리거가
    # 걸리지 않아**(HARN-30) 무증상이었다. 규칙(CLAUDE.md 2026-08-09 "출력 억제·판정
    # 건너뛰기 금지")은 이미 있었고 재발했다 — 그래서 코드로 옮긴다.
    #
    # **남의 위반에 볼모 잡히지 않는다**: 저장소 전역 위반이 아니라 이 브랜치·이 세션이
    # 잡은 태스크를 지목하는 오류만 본다(cmd_add 의 own_errors 와 같은 방식). main 에
    # 이미 있던 위반 때문에 모든 세션의 정지가 막히면 그 훅은 곧 무력화된다.
    own_ids = {t.id for t in backlog.tasks.values() if t.session == branch}
    violations = [
        e
        for e in store.validate_backlog(backlog)
        if branch in e or any(tid in e for tid in own_ids)
    ]
    if violations:
        print(
            "❌ 대장 무결성 위반 — 이 세션이 유발한 것이므로 정지를 막습니다:",
            file=sys.stderr,
        )
        for v in violations:
            print(f"  · {v}", file=sys.stderr)
        print(
            "  해소 후 다시 종료하세요 (예: 완료분은 `done <id> --artifact ...`,\n"
            "  보류분은 `block <id> --reason ...`). 진단: "
            "`python3 scripts/harness/backlog.py validate; echo EXIT=$?`",
            file=sys.stderr,
        )
        return 2

    if not mine:
        return 0

    def _git(*argv: str) -> str:
        result = subprocess.run(
            ["git", *argv],
            cwd=root,
            capture_output=True,
            # HARN-19: 로케일(cp949) 디코드 금지 — git 출력은 UTF-8이 정본이다.
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        return (result.stdout or "").strip()

    try:
        base = _git("merge-base", "origin/main", "HEAD") or _git("merge-base", "main", "HEAD")
        if not base:
            return 0
        ahead = int(_git("rev-list", "--count", f"{base}..HEAD") or "0")
        if ahead == 0:
            return 0  # 커밋한 작업이 없으면 갱신을 강제하지 않음
        changed = set(_git("diff", "--name-only", f"{base}..HEAD").splitlines())
        changed |= {
            line[3:] for line in _git("status", "--porcelain").splitlines() if len(line) > 3
        }
    except Exception:
        return 0

    stale = [t for t in mine if f"backlog/tasks/{t.id}.yaml" not in changed]
    if not stale:
        return 0
    ids = ", ".join(t.id for t in stale)
    print(
        f"[빌드하네스] 이 브랜치가 claim한 태스크({ids})의 상태가 갱신되지 않았습니다. "
        f"완료했다면 PR을 연 뒤 "
        f"`python3 scripts/harness/backlog.py done <id> --artifact <PR 번호를 담은 증적>`, "
        f"미완이면 태스크 파일의 notes에 진행 메모를 남기거나 "
        f"`block <id> --reason ...` 처리 후 종료하세요.",
        file=sys.stderr,
    )
    return 2


def cmd_check_edit(root: Path, args: argparse.Namespace) -> int:
    """PostToolUse(Edit|Write) 훅 — 편집 파일에 따라 두 갈래 검사.

    1) backlog/ 파일 직접 편집 → 무결성 validate (기존 동작, 위반 시 exit 2).
    2) 그 외 파일 → 조율 정책 검사 (harness v1.1):
        ① scope_drift  — 내 claim 태스크의 paths 밖 편집
        ② path_overlap — 다른 in-flight 태스크의 paths 안 편집
        ③ adhoc_edit   — claim 없이 코드 도메인(src/ 등) 편집
       warn = stderr 1줄 + policy_warn 이벤트 + exit 0 / block = exit 2.
    판정 불확실·예외는 전부 통과(exit 0) — 훅이 개발을 볼모로 잡으면 안 된다.
    """
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0
    file_path = str((payload.get("tool_input") or {}).get("file_path", ""))
    if "backlog/" in file_path.replace("\\", "/"):
        backlog, schema_errors = _load(root)
        errors = store.validate_backlog(backlog, schema_errors)
        if errors:
            print(
                f"[빌드하네스] backlog 직접 편집 후 무결성 위반 {len(errors)}건:",
                file=sys.stderr,
            )
            for error in errors[:10]:
                print(f"  · {error}", file=sys.stderr)
            return 2
        return 0
    try:
        return _check_edit_policy(root, file_path)
    except Exception:  # 정책 검사 실패는 무조건 통과 (fail-open)
        return 0


def _check_edit_policy(root: Path, file_path: str) -> int:
    """비-backlog 파일 편집의 조율 정책 검사 — check-edit ①②③."""
    from models import CODE_DOMAIN_PREFIXES

    if not file_path:
        return 0
    try:
        rel = str(Path(file_path).resolve().relative_to(root.resolve()))
    except ValueError:
        return 0  # 레포 밖 파일 — 관할 아님
    rel = rel.replace("\\", "/")

    policy, _ = store.load_policy(root)
    branch = store.current_branch(root)
    if branch in ("unknown", "main", ""):
        return 0
    backlog, _ = _load(root)
    mine = [t for t in backlog.tasks.values() if t.status == "in_progress" and t.session == branch]
    violations: list[tuple[str, str, str]] = []  # (rule, mode, 메시지)

    if mine:
        # ① scope_drift — 내 claim 태스크가 paths를 선언했는데 그 밖을 편집.
        # 처방 문구는 `amend --path`를 가리킨다: 구 문구("태스크 YAML의 paths에 추가")는
        # 정정 CLI가 없던 시절의 것이라 **사람을 대장 손편집으로 보내고 있었다** —
        # CLAUDE.md "거부의 우회 금지"가 금지한 바로 그 행위를 경고문이 처방한 셈이다.
        # `--path`는 교체이므로 확장 시 기존 항목도 함께 지정해야 한다(HARN-57 ④).
        me = mine[0]
        if me.paths and policy.scope_drift != "off" and not pathscope.path_in_scope(rel, me.paths):
            violations.append(
                (
                    "scope_drift",
                    policy.scope_drift,
                    f"'{rel}' 은 claim 태스크 {me.id}의 선언 범위(paths) 밖 — "
                    f"범위 확장이 맞으면 `backlog.py amend {me.id} --path <기존 전부> "
                    f"--path '{rel}' --reason <사유>`로 정정하라 (HARN-59)",
                )
            )
    elif policy.adhoc_edit != "off" and rel.startswith(CODE_DOMAIN_PREFIXES):
        # ③ adhoc_edit — claim 없이 코드 도메인 편집 (하네스에 불가시한 ad-hoc 작업)
        violations.append(
            (
                "adhoc_edit",
                policy.adhoc_edit,
                f"claim한 태스크 없이 코드 파일 '{rel}' 편집 — "
                f"`backlog.py next` 후 `start <id>`로 착수 등록 권장 (중복작업 방지)",
            )
        )

    # ② path_overlap — 다른 세션 in-flight 태스크의 선언 범위 안을 편집.
    # 교차 세션 claim은 로컬 backlog에 안 보이므로 원격 claim 캐시(.git/)를 병합
    # (캐시는 brief/next/start가 원격 조회 성공 시 갱신 — 훅은 네트워크 미사용)
    if policy.path_overlap != "off":
        cached = remote_claims.load_cache(root)
        for other in _inflight_tasks(backlog, cached, branch):
            if not other.paths or other.session == branch:
                continue
            if pathscope.path_in_scope(rel, other.paths):
                violations.append(
                    (
                        "path_overlap",
                        policy.path_overlap,
                        f"'{rel}' 은 다른 세션 태스크 {other.id}"
                        f"(세션: {other.session or '?'})의 작업 범위 — 동시 편집 충돌 위험",
                    )
                )
                break

    if not violations:
        return 0
    blocked = False
    for rule, mode, message in violations:
        store.append_event(root, "policy_warn", "-", rule=rule, file=rel, mode=mode, detail=message)
        print(f"[빌드하네스/{rule}:{mode}] {message}", file=sys.stderr)
        if mode == "block":
            blocked = True
    return 2 if blocked else 0


def cmd_claims(root: Path, args: argparse.Namespace) -> int:
    """원격 claim 관리 — list(기본)·release·reap."""
    backlog, _ = _load(root)
    policy, _ = store.load_policy(root)

    if args.claims_action == "release":
        if not args.claims_id:
            return _fail("claims release <task-id> — 태스크 ID 필수")
        result = remote_claims.release(
            root, args.claims_id, store.current_branch(root), force=args.force
        )
        if result.status != "ok":
            return _fail(f"해제 실패({result.status}): {result.message}")
        store.append_event(root, "claim_release", args.claims_id, forced=args.force)
        print(f"✔ {args.claims_id} 원격 claim 해제")
        return 0

    if args.claims_action == "reap":
        ttl = args.ttl_hours or policy.claim_ttl_hours
        # `--auto`(HARN-27) = 무인 집행 모드. 삭제를 켜되 사유를 확정 신호로 좁힌다.
        # 사람이 치는 `--apply`는 기존대로 전 사유를 지운다(판단 주체가 사람이므로).
        auto = getattr(args, "auto", False)
        apply_ = args.apply or auto
        reaped, scan_status, warnings = remote_claims.reap(
            root,
            backlog,
            ttl,
            dry_run=not apply_,
            branch_grace_hours=policy.claim_branch_grace_hours,
            reasons=remote_claims.AUTO_REAP_REASONS if auto else None,
        )
        if scan_status != "ok":
            # 조회 실패를 "stale 없음"으로 위장하지 않는다 — 이 구분이 없어서 CI
            # 교차검증이 공전했다(HARN-09). 판정 불가는 판정 불가라고 말한다.
            print(f"원격 claim 조회 불가 ({scan_status}) — stale 판정 불가")
            return 0 if scan_status == "offline" else 1
        if warnings:
            # reap에서 제외됐지만 침묵시키면 안 되는 것들 — 유예 구간 claim
            # (`task_missing_recent` HARN-21 · `branch_gone_recent` HARN-26)과
            # 홀더 브랜치 조회 실패(판정 미수행). 둘 다 "지우지 않았다"인데 이유가 다르므로
            # 사유 문자열을 그대로 노출한다(CLAUDE.md 침묵 실패 금지).
            print(
                f"⚠ reap 제외 {len(warnings)}건 — 유예 구간이거나 판정 불가"
                "(경합 조건 가능성: 다른 세션이 방금 add+claim했거나 아직 첫 push 전일 수 있다):"
            )
            for item in warnings:
                print(f"  · {item}")
        if not reaped:
            print("stale claim 없음")
            return 0
        label = "삭제됨" if apply_ else "삭제 대상 (dry-run — 실제 삭제는 --apply)"
        print(f"stale claim {len(reaped)}건 {label}:")
        for item in reaped:
            print(f"  · {item}")
        if apply_:
            store.append_event(root, "claim_reap", "-", reaped=reaped, auto=auto)
        return 0

    # list (기본)
    claims, status = remote_claims.list_claims(root, with_meta=args.verbose or args.json)
    if status != "ok":
        print(f"원격 claim 조회 불가 ({status})")
        return 0 if status == "offline" else 1
    if args.json:
        print(
            json.dumps(
                [{"task": c.task_id, "branch": c.branch, "ts": c.ts, "sha": c.sha} for c in claims],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if not claims:
        print("원격 claim 없음")
        return 0
    print(f"원격 claim {len(claims)}건:")
    for c in sorted(claims, key=lambda x: x.task_id):
        meta = f" — {c.branch} ({c.ts})" if c.branch else ""
        local = backlog.tasks.get(c.task_id)
        state = f" [로컬: {local.status}]" if local else " [로컬: 미존재]"
        print(f"  · {c.task_id}{meta}{state}")
    return 0


def cmd_branches(root: Path, args: argparse.Namespace) -> int:
    """장기 미머지 브랜치를 고립/PR제출로 갈라 보고한다 (HARN-47).

    **왜 별도 verb인가 — 집행 지점**: HARN-13이 만든 이 스캔은 SessionStart 훅에서만
    돌았다. 즉 사람이 대화형 세션을 열 때만 존재했고, CI에서는 한 번도 실행되지 않았다.
    이 저장소는 같은 형태의 실패를 반복했다(`tests/infra` 199건이 어떤 잡도 실행하지
    않던 상태·브랜치 보호 required check가 통째 미강제였던 상태). "저장소에 존재함"과
    "돌아감"은 다르다 — 그래서 CI가 부를 수 있는 표면을 별도로 낸다.

    종료 코드:
      0 — 스캔 성공(고립 0건이든 N건이든). 이 명령은 **게이트가 아니라 관측**이다.
          다른 사람의 방치 브랜치 때문에 무관한 PR의 CI를 red로 만들지 않는다.
      2 — 스캔 자체가 불가(offline·shallow·error). 호출부는 이것을 "고립 0건"으로
          읽어서는 안 된다. 측정 실패와 통과는 같은 색이면 안 된다.
    """
    # 원격 claim 맵을 먼저 읽어 `active`(타 세션 진행중)를 CI에서도 판별한다.
    # 이걸 빠뜨리면 **지금 누가 작업 중인 브랜치가 "🔴 회수 또는 삭제 필요"로 경고된다** —
    # 삭제를 유도하는 오경보이자, 문서가 4분류라고 말하면서 이 경로는 3분류만 낼 수 있는
    # 상태다(Codex 리뷰 P1 지적, 2026-08-31). `cmd_brief`와 동일한 재료를 쓴다.
    policy, _ = store.load_policy(root)
    active_branches: frozenset[str] = frozenset()
    claim_warning = ""
    if policy.remote_claims:
        try:
            remote_claimed, _ = _remote_claim_map(root, policy)
            active_branches = frozenset(remote_claimed.values())
        except Exception as exc:  # noqa: BLE001 - 환경 의존
            # 침묵 실패 금지 — 타입명을 남긴다. claim을 못 읽었으면 `active`가 `isolated`로
            # 오분류될 수 있으므로 그 사실 자체를 출력에 남겨야 한다.
            claim_warning = f"원격 claim 조회 실패({type(exc).__name__}: {exc})"

    scan = remote_claims.scan_stale_branches(
        root,
        days_threshold=args.days,
        fetch=not args.no_fetch,
        active_branches=active_branches,
    )
    if scan.status != "ok":
        print(f"측정 불가: status={scan.status} — {scan.message or '사유 미상'}")
        return 2
    if claim_warning:
        # 진행 중 브랜치가 고립으로 오분류될 수 있는 상태 — 조용히 넘기지 않는다.
        print(f"⚠ {claim_warning} — 'active'(타 세션 진행중)가 고립으로 오분류될 수 있다")

    buckets: dict[str, list[remote_claims.StaleBranch]] = {}
    for item in scan.stale:
        buckets.setdefault(item.status, []).append(item)

    isolated = buckets.get("isolated", [])
    pr_filed = buckets.get("pr_filed", [])
    pr_closed = buckets.get("pr_closed", [])
    undetermined = buckets.get("unresolved", [])

    # PR 대조를 못 했으면 "고립 N건"이라는 문장 자체를 만들지 않는다 — 조회 실패
    # 상태에서 고립 건수를 말하면 그 수는 측정이 아니라 추측이다.
    if not scan.pr_lookup_ok:
        reason = scan.pr_lookup_error or "사유 미상"
        print(
            f"PR 대조 실패({reason}) — 고립/PR제출 분리 미수행. 미머지 {len(scan.stale)}건 중 "
            f"고립 여부 미판정 {len(undetermined)}건"
        )
        return 2

    active = buckets.get("active", [])
    ported = buckets.get("ported", [])
    print(
        f"고립(PR 이력 0건): {len(isolated)}건 · PR 닫힘(미머지): {len(pr_closed)}건 · "
        f"PR 제출됨: {len(pr_filed)}건 · 타 세션 진행중: {len(active)}건 · "
        f"포팅됨: {len(ported)}건"
    )
    # (HARN-78) pr_filed의 열림/닫힘 조회 결과 — 토큰 없으면 시도조차 안 되므로 그
    # 사실을 명시한다("확인함"과 "확인 못함"은 다른 사실이다).
    if pr_filed and not scan.pr_state_lookup_ok:
        reason = scan.pr_state_lookup_error or "사유 미상"
        print(
            f"⚠ PR 열림/닫힘 조회 미수행({reason}) — PR 제출됨 {len(pr_filed)}건은 수동 확인 필요"
        )
    # (HARN-93 ②) 처분 라벨(eos-merge/rework/postpone/close) 조회 결과 — 이 라벨은
    # "닫는다/미룬다"는 결정인데 만료 지점이 없어 방치되기 쉽다(CLAUDE.md "만료 없는
    # 유예·제외 금지"). 토큰이 없으면 조회 자체를 안 하므로 그 사실을 먼저 밝힌다.
    disposal_labeled = [item for item in pr_filed if item.disposal_labels]
    if pr_filed and not scan.pr_label_lookup_ok:
        reason = scan.pr_label_lookup_error or "사유 미상"
        print(
            f"⚠ 처분 라벨 조회 미수행({reason}) — PR 제출됨 {len(pr_filed)}건은 라벨 수동 확인 필요"
        )
    for item in isolated:
        print(f"  [고립] {item.branch} — {item.age_days:.0f}일 전 · trunk 대비 {item.ahead}커밋")
    for item in pr_closed:
        print(f"  [PR-닫힘] {item.branch} — {item.evidence} · {item.age_days:.0f}일 전")
    for item in pr_filed:
        label_note = ""
        if item.disposal_labels:
            label_note = f" · 라벨: {','.join(item.disposal_labels)}(정체 {item.age_days:.0f}일)"
        print(f"  [PR]   {item.branch} — {item.evidence} · {item.age_days:.0f}일 전{label_note}")
    if disposal_labeled:
        print(
            f"⚠ 처분 라벨 붙은 열린 PR {len(disposal_labeled)}건 — 닫기 전 "
            "`python3 scripts/ops/pr_disposal_precheck.py --pr <N>`로 회수 선행 확인 (HARN-93 ③)"
        )
    return 0


def cmd_overlap(root: Path, args: argparse.Namespace) -> int:
    """태스크 간 파일 범위 겹침 진단 — 착수 전 수동 확인용.

    기본적으로 todo를 포함한 전체 상태를 비교한다. 오직 in-flight만 보려면
    --in-flight-only 를 사용한다.
    """
    backlog, _ = _load(root)
    task = backlog.tasks.get(args.id)
    if task is None:
        return _fail(f"태스크 '{args.id}' 없음")
    if not task.paths:
        print(f"{task.id}: paths 미선언 — 겹침 판정 불가 (paths 선언 권장)")
        return 0
    if args.against:
        others = [backlog.tasks[args.against]] if args.against in backlog.tasks else []
        if not others:
            return _fail(f"태스크 '{args.against}' 없음")
    else:
        include_todo = not args.in_flight_only
        others = [
            t
            for t in _overlap_candidates(
                backlog, remote_claimed=None, session=None, include_todo=include_todo
            )
            if t.id != task.id and t.paths
        ]
    if not others:
        scope_msg = "전체" if not args.in_flight_only else "in-flight"
        print(f"비교 대상 {scope_msg} 태스크 없음")
        return 0
    files = pathscope.repo_files(root)
    found = False
    for other in others:
        hit = pathscope.overlap(task.id, task.paths, other.id, other.paths, files)
        if hit:
            found = True
            print(f"⚠ {task.id} ↔ {other.id} (세션: {other.session or '?'}): {hit.describe()}")
    if not found:
        scope_msg = "전체" if not args.in_flight_only else "in-flight"
        print(f"✔ {task.id}: {scope_msg} 범위에서 겹침 없음 ({len(others)}건 비교)")
    return 0


def cmd_policy(root: Path, args: argparse.Namespace) -> int:
    """조율 정책 — show(현재 값)·report(warn 측정 요약: warn→block 승격 근거)."""
    policy, policy_errors = store.load_policy(root)
    if policy_errors:
        for e in policy_errors:
            print(f"  · {e}", file=sys.stderr)
        return _fail("policy.yaml 오류")

    if args.policy_action == "show" or args.policy_action is None:
        print(store.dump_policy(policy), end="")
        return 0

    # report — 이벤트 대장(레거시 + 세션 샤드 전부)의 policy_warn을 rule별 집계.
    # HARN-46: 샤딩 이후 기록은 backlog/events/*.ndjson에 흩어져 있으므로
    # store.event_paths()가 주는 전 파일을 읽어야 무손실이다. 파일 간 순서는
    # 무의미해졌으므로(샤드별 append) ts로 정렬해 rule별 tail 표시를 시간순으로 만든다.
    from datetime import datetime, timedelta

    # HARN-44: cutoff도 **aware**여야 한다 — 대장의 ts가 오프셋을 갖게 됐으므로 naive와
    # 비교하면 TypeError다. store.parse_event_ts가 레거시 줄에도 오프셋을 붙여 주므로
    # 양쪽 표기가 같은 축에서 비교된다.
    cutoff = datetime.now().astimezone() - timedelta(days=args.days)
    collected: list[tuple[datetime, dict, bool]] = []
    for path in store.event_paths(root):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("action") != "policy_warn":
                continue
            # HARN-44: 엄격 strptime("%Y-%m-%dT%H:%M:%S") + except ValueError: continue 조합은
            # 오프셋이 붙은 신규 줄을 **에러 없이 통째로 누락**시킨다(침묵 실패). 두 표기를
            # 모두 읽는 공용 파서를 경유한다 — 레거시 줄의 오프셋은 가정값이라 정렬 위치가
            # 부정확할 수 있고, 그 사실은 아래 렌더에서 별도로 말한다.
            moment = store.parse_event_ts(event.get("ts"))
            if moment is None:
                continue
            if moment.moment < cutoff:
                continue
            collected.append((moment.moment, event, moment.offset_known))
    collected.sort(key=lambda pair: pair[0])
    by_rule: dict[str, list[dict]] = {}
    total = 0
    unknown_offset = 0
    for _ts, event, offset_known in collected:
        total += 1
        if not offset_known:
            unknown_offset += 1
        by_rule.setdefault(str(event.get("rule", "?")), []).append(event)
    print(f"조율 정책 warn 리포트 — 최근 {args.days}일, 총 {total}건")
    if unknown_offset:
        # 추정 정렬을 실측 정렬인 척하지 않는다(HARN-44 ② — 레거시는 척도 불명).
        print(
            f"  ⚠ 그중 {unknown_offset}건은 오프셋 없는 레거시 줄이라 읽는 머신의 로컬 "
            "오프셋을 가정해 정렬했다 — 다른 TZ 세션이 쓴 줄이면 순서가 어긋날 수 있다."
        )
    if not by_rule:
        print("  (경고 없음 — 오탐 0. 승격 기준 충족 여부는 정탐 사례와 함께 판단)")
        return 0
    for rule in sorted(by_rule):
        events = by_rule[rule]
        actors = sorted({str(e.get("actor", "?")) for e in events})
        print(f"  {rule}: {len(events)}건 (세션 {len(actors)}개)")
        for event in events[-3:]:
            detail = event.get("detail") or event.get("file") or event.get("other") or ""
            print(f"    · {event.get('ts')} {detail}")
    print(
        "승격 기준: 2주/30세션 관찰 후 (a)충돌 예방 사례 ≥1 또는 정탐률 ≥50% "
        "(b)오탐 개발중단 0건 → 해당 rule만 block (MEMORY.md 결정로그 필수)"
    )
    return 0


def cmd_seed(root: Path, args: argparse.Namespace) -> int:
    bdir = store.backlog_dir(root)
    if (bdir / "tracks.yaml").exists() and not args.force:
        return _fail("backlog/ 이미 존재 — 재시딩은 --force (기존 상태를 덮어씀에 주의)")
    stage_order, tracks, gates, tasks = build_seed()
    store.save_tracks(root, stage_order, tracks)
    store.save_gates(root, gates)
    for task in tasks:
        store.save_task(root, task)
    backlog, schema_errors = _load(root)
    errors = store.validate_backlog(backlog, schema_errors)
    if errors:
        for error in errors:
            print(f"  · {error}", file=sys.stderr)
        return _fail("시딩 결과 무결성 위반 — seed_data.py 수정 필요")
    store.append_event(
        root, "seed", "backlog", tasks=len(tasks), gates=len(gates), tracks=len(tracks)
    )
    print(
        f"🌱 시딩 완료 — 태스크 {len(tasks)}건, 게이트 {len(gates)}건, "
        f"트랙 {len(tracks)}건 (validate green)"
    )
    return 0


# ── argparse 배선 ────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="backlog.py", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status", help="프로젝트 현재 상태 한 화면")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("next", help="착수 가능 후보 계산")
    p.add_argument("--n", type=int, default=3)
    p.add_argument("--layer")
    p.add_argument("--subject")
    p.add_argument("--track")
    p.add_argument("--json", action="store_true")
    p.add_argument(
        "--no-remote",
        action="store_true",
        dest="no_remote",
        help="원격 claim 조회 생략",
    )
    p.set_defaults(func=cmd_next)

    p = sub.add_parser("start", help="태스크 착수 (claim)")
    p.add_argument("id")
    p.add_argument("--session")
    p.add_argument(
        "--no-remote",
        action="store_true",
        dest="no_remote",
        help="원격 claim 생략 (오프라인·긴급용) — CAS·읽기측 보호 전체 포기",
    )
    p.add_argument(
        "--ignore-remote-claim",
        action="store_true",
        dest="ignore_remote_claim",
        help="이 태스크의 읽기측 판정만 무시 — 교차 세션(stale 홀더 확인 후, HARN-08)·"
        "미머지 done(HARN-11)·트렁크 의존·게이트 시차(HARN-91). CAS conflict는 무시되지 않는다",
    )
    p.add_argument(
        "--as",
        dest="as_owner",
        default=None,
        choices=[o for o in OWNERS if o != "claude"],
        help="사람-소유 태스크를 소유자 본인이 기입할 때 명시 (HARN-06)",
    )
    p.set_defaults(func=cmd_start)

    p = sub.add_parser("done", help="태스크 완료 (증적 필수 · PR 참조 필수)")
    p.add_argument("id")
    p.add_argument("--artifact", action="append", default=[])
    p.add_argument(
        "--as",
        dest="as_owner",
        default=None,
        choices=[o for o in OWNERS if o != "claude"],
        help="사람-소유 태스크를 소유자 본인이 기입할 때 명시 (HARN-06)",
    )
    p.add_argument(
        "--no-pr",
        dest="no_pr",
        default=None,
        choices=list(NO_PR_REASONS),
        help="PR 없이 완료하는 예외 사유 (HARN-23 — 예외 4종만 허용)",
    )
    p.set_defaults(func=cmd_done)

    p = sub.add_parser("block", help="태스크 차단")
    p.add_argument("id")
    p.add_argument("--reason", required=True)
    p.add_argument(
        "--handover",
        action="store_true",
        help="인계 차단 — 원격 홀드를 두지 않아 다른 세션이 이어받을 수 있다"
        " (기본은 홀드 게시: 자리를 지킨다 — HARN-45/48)",
    )
    p.set_defaults(func=cmd_block)

    p = sub.add_parser(
        "unblock", help="→ todo 전이(session 해제) — 차단 해제뿐 아니라 in_progress 재진입에도 사용"
    )
    p.add_argument("id")
    p.set_defaults(func=cmd_unblock)

    p = sub.add_parser("review", help="검토 대기로 전환 (in_progress → review, HARN-20)")
    p.add_argument("id")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("cancel", help="태스크 취소 (todo/blocked → cancelled, HARN-20)")
    p.add_argument("id")
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_cancel)

    p = sub.add_parser("rename", help="태스크 ID 개명 — 번호 충돌 정정 경로 (HARN-100)")
    p.add_argument("old_id")
    p.add_argument("new_id")
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_rename)

    p = sub.add_parser("gates", help="사람 게이트 대장")
    p.add_argument("gate_action", nargs="?", choices=["list", "add", "clear", "waive", "show"])
    p.add_argument("gate_id", nargs="?")
    p.add_argument("--evidence")
    p.add_argument("--reason")
    # gates clear 전용 — 사람이 본인 게이트를 직접 닫을 때 주체를 명시한다 (HARN-60).
    # 플래그 이름·선택지는 done/start의 `--as`(HARN-06)를 그대로 재사용한다(새 어휘 금지).
    # 생략하면 거부하지 않고 `cleared_by="claude"`(에이전트 중계)로 **사실대로** 기록한다.
    p.add_argument(
        "--as",
        dest="as_owner",
        default=None,
        choices=[o for o in OWNERS if o != "claude"],
        help="gates clear: 본인 게이트를 직접 닫을 때 주체 명시 (HARN-60 · 생략 시 에이전트 기록)",
    )
    # gates clear 전용 — 판정 기준(커밋 해시·PR 참조)이 없는 근거의 탈출구 (HARN-68).
    # 자유 서술이다: 사람 게이트의 정당한 근거에는 커밋과 무관한 것이 많고(환경 생성·
    # 서명·법률 검토), 유형을 열거하면 정상 상태에서 거부하는 검사가 된다.
    p.add_argument(
        "--no-base",
        dest="no_base",
        default=None,
        metavar="사유",
        help="gates clear: 판정 기준(커밋·PR)이 없는 근거일 때 사유 명시 (HARN-68)",
    )
    # gates add 전용 플래그 (다른 액션에서는 무시됨 — 기본값이 간섭하지 않음)
    p.add_argument("--title", help="gates add: 게이트 제목 (필수)")
    p.add_argument(
        "--kind",
        choices=list(GATE_KINDS),
        default="human",
        help="gates add: 게이트 종류 (기본 human)",
    )
    p.add_argument("--assignee", default="kiki", help="gates add: 담당자 (기본 kiki)")
    p.add_argument(
        "--remind-after-days",
        type=int,
        dest="remind_after_days",
        default=None,
        help="gates add: 경과 시 SessionStart 브리핑 리마인드 일수",
    )
    p.set_defaults(func=cmd_gates)

    p = sub.add_parser("add", help="태스크 추가 (/plan의 산출물)")
    p.add_argument("--id", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--track", required=True)
    p.add_argument("--stage", required=True)
    p.add_argument("--subject", default="math")
    p.add_argument("--layer", default="backend")
    p.add_argument("--priority", type=int, default=3)
    p.add_argument(
        "--eos-priority",
        dest="eos_priority",
        default=None,
        help=(
            "EOS 12월 검증 등급 (P0|P1|P2|P3) — **필수**. "
            "미지정은 exit 1 (계획서 100 Rule 1·3 집행 지점). " + _EOS_PRIORITY_HELP
        ),
    )
    p.add_argument(
        "--swap-out",
        dest="swap_out",
        default=None,
        help=(
            "P0 예산 소진 시 내보낼 기존 P0 태스크 id — 그 태스크는 P1로 강등된다 "
            "(One In → One Out · 계획서 100 Rule 4)"
        ),
    )
    p.add_argument("--owner", default="claude")
    p.add_argument("--depends", action="append", default=[])
    p.add_argument(
        "--no-trigger",
        metavar="사유",
        help="HARN-72 트리거 검출기 오탐 면제 — 사유를 notes에 [트리거 면제] 마커로 남긴다",
    )
    p.add_argument("--gates", action="append", default=[])
    p.add_argument("--acceptance", action="append", default=[])
    p.add_argument(
        "--path",
        action="append",
        default=[],
        dest="paths",
        help="작업 파일 범위 glob (겹침 검사용 — 반복 지정 가능)",
    )
    p.add_argument("--notes")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser(
        "amend",
        help="등재된 태스크의 acceptance·게이트·트랙·의존·notes·증적·범위·제목 정정 "
        "(HARN-24+49+52+57+67)",
    )
    p.add_argument("id")
    p.add_argument(
        "--acceptance",
        action="append",
        default=[],
        help="acceptance 정정 항 추가 (append만 — 기존 항은 지우지 않는다)",
    )
    p.add_argument(
        "--gate",
        action="append",
        default=[],
        dest="gates",
        help="requires_gates에 게이트 부착 (add 시점 외 유일 경로)",
    )
    p.add_argument(
        "--remove-gate",
        action="append",
        default=[],
        dest="remove_gates",
        metavar="G-ID",
        help="requires_gates에서 게이트 탈착 (오부착 정정 — HARN-67 ⑤). 게이트 자체의 status는 "
        "건드리지 않는다. 미부착 게이트·같은 호출의 --gate와 겹치면 거부",
    )
    p.add_argument(
        "--remove-depends",
        action="append",
        default=[],
        dest="remove_depends",
        metavar="FULL-ID",
        help="depends_on에서 선행 제거 (취소·오등재 선행 정정 — HARN-67 ③). full id로 지정. "
        "없는 의존·같은 호출의 --depends와 겹치면 거부",
    )
    p.add_argument(
        "--notes-replace",
        nargs=2,
        metavar=("구문자", "신문자"),
        dest="notes_replace",
        help="notes의 어구 치환 (HARN-67 ⑥ — audit-deps 위반 어구 정정용). 구문자는 notes에 "
        "정확히 1회 등장해야 한다(0회·2회+ 거부). 신문자 ''는 어구 삭제. 원문은 이벤트에만 남는다",
    )
    p.add_argument("--track", help="트랙 이관 (entry_gate 하드락으로의 강등 등)")
    p.add_argument(
        "--no-trigger",
        metavar="사유",
        help="HARN-72 트리거 검출기 오탐 면제 — 사유를 notes에 [트리거 면제] 마커로 남긴다. "
        "트리거 어구를 *예시로 인용*하는 태스크(검출기 자신 등)용. 사유 없는 면제 불가",
    )
    p.add_argument(
        "--depends",
        action="append",
        default=[],
        help="depends_on에 선행 태스크 부착 (add 시점 외 유일 경로 — HARN-52). "
        "full id로 지정. 자기 의존·순환·미존재 대상은 거부",
    )
    p.add_argument(
        "--priority",
        type=int,
        help="priority 재배정 1(최고)~5 (add 시점 외 유일 경로 — HARN-52 후속)",
    )
    p.add_argument(
        "--eos-priority",
        dest="eos_priority",
        default=None,
        help=(
            "EOS 등급 지정·변경 (P0|P1|P2|P3) — 기존 태스크 백필의 **유일한 합법 경로**"
            "(대장 손편집 금지). " + _EOS_PRIORITY_HELP
        ),
    )
    p.add_argument(
        "--artifact",
        action="append",
        default=[],
        dest="artifacts",
        help="artifacts에 증적 추가 (append만 — 기존 증적은 지우지 않는다·HARN-57). "
        "done 이후 PR이 열린 경우의 유일한 합법 보정 경로. PR 참조를 담은 증적을 붙이면 "
        "`--no-pr` 보류 사유의 사후 해소가 대장에 함께 기록된다",
    )
    p.add_argument(
        "--path",
        action="append",
        default=[],
        dest="paths",
        help="paths 범위 교체 (지정한 --path 전체가 새 목록이 된다 — HARN-57). "
        "넓게 잡은 glob을 좁히는 용도이므로 append가 아니라 교체다. 이전 값은 notes에 남고, "
        "정정 직후 겹침 건수 변화를 함께 보고한다",
    )
    p.add_argument(
        "--drop-scope",
        action="store_true",
        dest="drop_scope",
        help="paths 교체로 기존 범위를 *버리는* 것이 의도임을 확인 (HARN-81). "
        "잃는 파일과 얻는 파일이 동시에 있으면 '덧붙이려다 교체된' 사고 형태라 기본 거부한다 — "
        "정말 버리는 경우에만 붙여라. 제거된 패턴은 어느 경우든 notes·이벤트에 열거된다",
    )
    p.add_argument(
        "--title",
        help="title 교체 (HARN-57). 브리핑·next가 노출하는 유일한 문자열이라 "
        "옛 제목이 남으면 다음 세션이 정정 전 처방을 읽고 착수한다. 이전 값은 notes에 남는다",
    )
    p.add_argument("--reason", required=True, help="정정 사유 (notes·이벤트에 기록)")
    p.set_defaults(func=cmd_amend)

    p = sub.add_parser(
        "audit-deps", help="의존 선언↔집행 대조 — notes의 '선행'이 depends_on에 있는가 (HARN-52)"
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="그랜드파더 무시하고 전건 표시 (감사 모드 — 항상 exit 0)",
    )
    p.set_defaults(func=cmd_audit_deps)

    p = sub.add_parser("validate", help="백로그 무결성 전수 검증")
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("brief", help="SessionStart 훅용 압축 브리핑")
    p.add_argument("--format", choices=["hook", "text"], default="text")
    p.set_defaults(func=cmd_brief)

    p = sub.add_parser("check-stop", help="Stop 훅 — 상태 갱신 강제")
    p.set_defaults(func=cmd_check_stop)

    p = sub.add_parser("check-edit", help="PostToolUse 훅 — backlog 직접 편집 검증")
    p.set_defaults(func=cmd_check_edit)

    p = sub.add_parser("claims", help="원격 claim(harness-claims 브랜치) 조회·해제·청소")
    p.add_argument("claims_action", nargs="?", default="list", choices=["list", "release", "reap"])
    p.add_argument("claims_id", nargs="?")
    p.add_argument("--json", action="store_true")
    p.add_argument("--verbose", action="store_true", help="claim 메타(브랜치·시각) 포함")
    p.add_argument("--force", action="store_true", help="남의 claim 강제 해제")
    p.add_argument(
        "--ttl-hours",
        type=int,
        dest="ttl_hours",
        help="reap TTL (기본: policy.claim_ttl_hours)",
    )
    p.add_argument("--apply", action="store_true", help="reap 실제 삭제 (기본 dry-run)")
    p.add_argument(
        "--auto",
        action="store_true",
        help="reap 무인 집행 — 삭제하되 확정 사유(task_done·branch_gone)로만 한정. CI 전용",
    )
    p.set_defaults(func=cmd_claims)

    p = sub.add_parser("branches", help="장기 미머지 브랜치 — 고립/PR제출 분리 (HARN-47)")
    p.add_argument("--days", type=int, default=remote_claims.STALE_BRANCH_DEFAULT_DAYS)
    p.add_argument("--no-fetch", action="store_true", help="원격 fetch 생략(캐시된 ref만)")
    p.set_defaults(func=cmd_branches)

    p = sub.add_parser("overlap", help="태스크 간 파일 범위 겹침 진단")
    p.add_argument("id")
    p.add_argument("--against", help="특정 태스크와만 비교 (기본: 전체)")
    p.add_argument(
        "--in-flight-only",
        action="store_true",
        help="비교 대상에서 todo 태스크 제외 (기존 동작)",
    )
    p.set_defaults(func=cmd_overlap)

    p = sub.add_parser("policy", help="조율 정책 표시·warn 측정 리포트")
    p.add_argument("policy_action", nargs="?", choices=["show", "report"])
    p.add_argument("--days", type=int, default=14)
    p.set_defaults(func=cmd_policy)

    p = sub.add_parser("seed", help="초기 백로그 시딩 (최초 1회)")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_seed)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = find_root_for_cli()
    except RuntimeError as exc:
        return _fail(str(exc), code=3)
    try:
        return args.func(root, args)
    except RuntimeError as exc:  # PyYAML 부재 등 환경 오류
        return _fail(str(exc), code=3)


def find_root_for_cli() -> Path:
    """CLI 실행 위치와 무관하게 저장소 루트 결정 (worktree 대응: cwd 우선)."""
    cwd = Path.cwd()
    for candidate in (cwd, *cwd.parents):
        if (candidate / ".git").exists():
            return candidate
    return store.find_repo_root()


if __name__ == "__main__":
    sys.exit(main())
