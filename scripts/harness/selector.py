"""순차 조율 알고리즘 — "다음 할 일"을 결정적으로 계산한다.

후보 조건 (전부 만족해야 착수 가능):
    status == todo
    ∧ depends_on 전부 done
    ∧ requires_gates 전부 cleared/waived
    ∧ owner == claude          (사람 소유 태스크는 자동 착수 금지)
    ∧ 소속 트랙 entry_gate 통과 (예: E축은 S5 게이트 전 하드락)
    ∧ session == null          (다른 세션이 claim하지 않음)

정렬 (결정적 — 같은 입력이면 항상 같은 순서):
    (stage_order 인덱스, priority, -해금 후속 수, id)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from models import Backlog, Task


@dataclass
class Exclusion:
    """todo 태스크가 후보에서 제외된 사유 (정지 사유 판별·설명에 사용)."""

    task_id: str
    reason: str  # deps|deps_cancelled|gates|owner|track_gate|claimed|claimed_remote|path_overlap
    detail: list[str] = field(default_factory=list)


def track_gate_passed(backlog: Backlog, task: Task) -> bool:
    track = backlog.tracks.get(task.track)
    if track is None or not track.entry_gate:
        return True
    gate = backlog.gates.get(track.entry_gate)
    return gate is not None and gate.passed


def unmet_dependencies(backlog: Backlog, task: Task) -> list[str]:
    return [
        dep
        for dep in task.depends_on
        if dep not in backlog.tasks or backlog.tasks[dep].status != "done"
    ]


def cancelled_dependencies(backlog: Backlog, task: Task) -> list[str]:
    """depends_on 중 **취소된** 선행 — 영구 차단의 후보 (HARN-67 ②).

    왜 따로 세는가: `unmet_dependencies`는 done만 해소로 치므로 cancelled 선행은 그 안에
    묻혀 일반 "의존 미충족"으로 보인다. 그런데 cancelled는 done과 달리 **앞으로도 해소되지
    않는다** — 선행이 "불필요해서 취소"됐는지 "잘못 등재돼 취소"됐는지 기계는 모르므로
    (모른다 ≠ 아니다) 해소로 간주하지 않고 차단을 유지하되, 따로 세어 화면에 드러낸다.
    정정 경로는 `amend <id> --remove-depends <dep>`이다 — 차단은 영구가 아니라 *결정 대기*다.
    (사고 경위 2026-09-05: EOS-94를 cancel하자 EOS-96이 후보에서 조용히 사라졌다)
    """
    return [
        dep
        for dep in task.depends_on
        if dep in backlog.tasks and backlog.tasks[dep].status == "cancelled"
    ]


def cancelled_dependency_blocks(backlog: Backlog) -> list[tuple[Task, list[str]]]:
    """취소된 선행에 차단된 **todo** 태스크 전건 — status·brief·validate 요약용 (HARN-67 ②).

    classify_todo의 `excluded`가 아니라 직접 훑는 이유: classify는 owner·트랙 게이트 제외가
    먼저라 사람 소유·게이트 대기 태스크의 취소 선행이 그 뒤에 숨는다. 요약은 "결정이 필요한
    태스크"를 빠짐없이 보여 주는 것이 목적이므로 순서에 가려지면 안 된다. id 정렬(결정적).
    """
    result = [
        (task, cancelled_dependencies(backlog, task))
        for task in sorted(backlog.tasks.values(), key=lambda t: t.id)
        if task.status == "todo"
    ]
    return [(task, deps) for task, deps in result if deps]


def unmet_gates(backlog: Backlog, task: Task) -> list[str]:
    return [
        gid
        for gid in task.requires_gates
        if gid not in backlog.gates or not backlog.gates[gid].passed
    ]


def _gate_id_mentioned(text: str, gate_id: str) -> bool:
    """notes 산문에 게이트 ID가 *단어로* 등장하는가 — 부분 문자열 오탐 방지 (HARN-74 ②).

    왜 필요한가: 단순 `in` 검사는 `G-eos`가 `G-eos-verification-…` 안에서도 참이 되어, 짧은
    ID의 게이트를 clear할 때 무관한 blocked 태스크가 '산문 참조'로 잡힌다. ID 문자 집합
    (`[A-Za-z0-9_-]`) 밖의 경계에서 끝나는 일치만 참조로 친다.
    """
    pattern = rf"(?<![A-Za-z0-9_-]){re.escape(gate_id)}(?![A-Za-z0-9_-])"
    return re.search(pattern, text) is not None


def gate_dependent_tasks(backlog: Backlog, gate_id: str) -> list[Task]:
    """이 게이트를 `requires_gates`로 건 **미종결** 태스크 전건 — id 정렬 (단일 진실 원천).

    왜 여기 있는가: 보드(`board.gate_dependents`)와 `gates clear` 화면(HARN-74 ①)이 같은
    목록을 각자의 comprehension으로 만들면 한쪽만 고쳐질 때 두 화면이 서로 다른 사실을
    말한다. 계산은 이 한 곳이고 소비자는 status로 좁혀 쓴다. ⚠ 이 목록은 *의존 관계*이지
    "현재 차단"이 아니다 — 해소된 게이트를 아직 달고 있는 태스크도 포함된다.
    """
    return [
        t
        for t in sorted(backlog.tasks.values(), key=lambda t: t.id)
        if gate_id in t.requires_gates and t.status not in ("done", "cancelled")
    ]


def gate_attached_blocked(backlog: Backlog, gate_id: str) -> list[tuple[Task, list[str]]]:
    """이 게이트를 건 **blocked** 태스크 전건 + 각각의 *다른* 미통과 게이트 (HARN-74 ①).

    왜 필요한가: `gates clear`는 게이트 status만 바꾸고 태스크는 건드리지 않는다 — 그 자체는
    옳다(차단 사유가 게이트뿐인지 기계는 모르므로 자동 unblock은 하지 않는다 · 모른다 ≠ 아니다).
    그러나 *알리지도* 않으면 clear한 세션은 부착 태스크의 존재를 모른 채 끝나고 그 태스크는
    blocked로 방치된다(2026-09-06 실측: 게이트 해소 뒤 ADMIN-02·CUR-17·CUR-18이 5일 이상
    blocked로 남아 /status가 Kiki 대기로 오보고). 그래서 clear 시점에 전건을 계산해 화면과
    이벤트 양쪽에 남긴다.

    둘째 원소는 `gate_id`를 **명시적으로 뺀** 미통과 게이트다 — 이 게이트가 아직 pending일 때
    불러도, 이미 cleared일 때 불러도 같은 답을 내게 하기 위해서다(호출 순서 의존 제거). 비어
    있지 않으면 unblock해도 후보가 되지 않으므로 화면이 그 사실을 미리 알린다.
    """
    result: list[tuple[Task, list[str]]] = []
    for task in gate_dependent_tasks(backlog, gate_id):
        if task.status != "blocked":
            continue
        others = [g for g in unmet_gates(backlog, task) if g != gate_id]
        result.append((task, others))
    return result


def gate_notes_referenced_blocked(backlog: Backlog, gate_id: str) -> list[Task]:
    """notes 산문에만 게이트 ID를 적고 `requires_gates`에는 안 건 **blocked** 태스크 (HARN-74 ②).

    왜 필요한가: `block --reason "G-x 대기"`로 막아 둔 태스크는 게이트를 산문으로만 참조한다 —
    ①의 부착 목록에는 구조적으로 안 잡히며, 이것이 CUR-17·CUR-18이 방치된 정확한 형태다.
    기계는 그 산문이 "이 게이트를 기다린다"는 뜻인지 단순 언급인지 모르므로 unblock 명령을
    내지 않고, 부착(`amend --gate`)과 해제(`unblock`) 중 사람이 고르게 한다. id 정렬.
    """
    return [
        t
        for t in sorted(backlog.tasks.values(), key=lambda t: t.id)
        if t.status == "blocked"
        and gate_id not in t.requires_gates
        and _gate_id_mentioned(t.notes, gate_id)
    ]


def stale_gate_blocked(backlog: Backlog) -> list[tuple[Task, list[str]]]:
    """기다릴 게이트가 없는데 blocked로 남은 태스크 — (태스크, 이미 통과한 게이트) (HARN-74 ③).

    대상 = status가 blocked이고 `requires_gates`가 비어 있지 않으며 **전부** passed(cleared/
    waived). 왜 따로 세는가: ①은 clear *시점*의 알림이라 그 화면을 놓치면 끝이다 — 다음
    세션이 같은 사실을 다시 보려면 대장에서 매번 계산해야 한다(집행 지점 별항). 기계는 차단
    사유가 게이트뿐이었는지 모르므로 자동 unblock하지 않고 확인 명령만 낸다. id 정렬.
    """
    result: list[tuple[Task, list[str]]] = []
    for task in sorted(backlog.tasks.values(), key=lambda t: t.id):
        if task.status != "blocked" or not task.requires_gates:
            continue
        if unmet_gates(backlog, task):
            continue
        result.append((task, list(task.requires_gates)))
    return result


def classify_todo(
    backlog: Backlog,
    task: Task,
    *,
    remote_claimed: dict[str, str] | None = None,
    overlap_block: dict[str, list[str]] | None = None,
    allow_human_owner: bool = False,
) -> Exclusion | None:
    """todo 태스크의 제외 사유 (None = 착수 가능 후보).

    remote_claimed: task_id → 원격 claim 브랜치 (refs/claims/* — 병렬 세션 가시성).
    overlap_block: task_id → 겹침 근거 (policy.path_overlap=block일 때만 채워짐).
    allow_human_owner: True면 owner!=claude 제외를 건너뛴다 — **소유자 본인이 `--as
        <owner>`로 기입하는 start 경로 전용**(HARN-06). candidates()는 기본값(False)만
        쓰므로 next/status/brief의 자동 착수 후보에서 사람 태스크는 계속 제외된다.
        deps·게이트·claim 등 나머지 검사는 사람 기입에도 동일 적용(우회 아님).
    """
    if not allow_human_owner and task.owner != "claude":
        return Exclusion(task.id, "owner", [task.owner])
    if not track_gate_passed(backlog, task):
        track = backlog.tracks[task.track]
        return Exclusion(task.id, "track_gate", [track.entry_gate or "?"])
    # 취소된 선행은 일반 deps보다 **먼저** 판정한다 — 같은 "미충족"이라도 done을 기다리면
    # 풀리는 것과 영원히 안 풀리는 것을 한 사유로 뭉치면 후자가 조용한 영구 차단이 된다
    # (HARN-67 ②: 침묵 실패 금지). unmet_dependencies의 의미(done만 해소)는 그대로다.
    cancelled = cancelled_dependencies(backlog, task)
    if cancelled:
        return Exclusion(task.id, "deps_cancelled", cancelled)
    deps = unmet_dependencies(backlog, task)
    if deps:
        return Exclusion(task.id, "deps", deps)
    gates = unmet_gates(backlog, task)
    if gates:
        return Exclusion(task.id, "gates", gates)
    if task.session:
        return Exclusion(task.id, "claimed", [task.session])
    if remote_claimed and task.id in remote_claimed:
        return Exclusion(task.id, "claimed_remote", [remote_claimed[task.id]])
    if overlap_block and task.id in overlap_block:
        return Exclusion(task.id, "path_overlap", overlap_block[task.id])
    return None


def unblock_count(backlog: Backlog, task: Task) -> int:
    """이 태스크 완료가 직접 해금하는 후속 태스크 수 (병목 우선 지표)."""
    return sum(1 for other in backlog.tasks.values() if task.id in other.depends_on)


def sort_key(backlog: Backlog, task: Task) -> tuple[int, int, int, str]:
    return (
        backlog.stage_index(task.stage),
        task.priority,
        -unblock_count(backlog, task),
        task.id,
    )


def candidates(
    backlog: Backlog,
    layer: str | None = None,
    subject: str | None = None,
    track: str | None = None,
    *,
    remote_claimed: dict[str, str] | None = None,
    overlap_block: dict[str, list[str]] | None = None,
) -> tuple[list[Task], list[Exclusion]]:
    """(정렬된 착수 가능 후보, 제외 사유 목록) 반환."""
    ready: list[Task] = []
    excluded: list[Exclusion] = []
    for task in backlog.tasks.values():
        if task.status != "todo":
            continue
        if layer and task.layer != layer:
            continue
        if subject and task.subject != subject:
            continue
        if track and task.track != track:
            continue
        exclusion = classify_todo(
            backlog, task, remote_claimed=remote_claimed, overlap_block=overlap_block
        )
        if exclusion is None:
            ready.append(task)
        else:
            excluded.append(exclusion)
    ready.sort(key=lambda t: sort_key(backlog, t))
    return ready, excluded


def selection_rationale(backlog: Backlog, task: Task) -> str:
    """왜 이 태스크가 지금 최우선인지 한 줄 설명."""
    parts = [f"stage={task.stage}", f"priority={task.priority}"]
    unlocks = unblock_count(backlog, task)
    if unlocks:
        parts.append(f"완료 시 후속 {unlocks}건 해금")
    if task.depends_on:
        parts.append(f"의존성 {len(task.depends_on)}건 전부 해소됨")
    if task.requires_gates:
        parts.append(f"게이트 {len(task.requires_gates)}건 전부 통과")
    return " · ".join(parts)


def stall_reason(backlog: Backlog, excluded: list[Exclusion]) -> tuple[str, list[str]]:
    """후보 0일 때의 정지 사유 판별 — /drive 정지 신호.

    반환: (사유 코드, 상세 목록)
        all_done    : 진행할 태스크 자체가 없음 → 스테이지/트랙 전환 제안
        human_gate  : 사람 게이트만 해소되면 진행 가능 → 게이트 목록 제시
        in_progress : 다른 세션이 진행 중 → 대기 또는 다른 layer 선택
        blocked     : 나머지 (blocked 태스크·미해소 의존성 연쇄)
    """
    active = [t for t in backlog.tasks.values() if t.status in ("in_progress", "review")]
    open_todo = [t for t in backlog.tasks.values() if t.status in ("todo", "blocked")]
    if not open_todo and not active:
        return "all_done", []

    # 사람 게이트만 걷어내면 풀리는가 — 게이트 제외 + owner 제외만 남은 경우
    gate_ids: list[str] = []
    remote_held: list[str] = []
    # 취소된 선행에 막힌 태스크 → 상세 목록에 사유를 병기하기 위해 따로 모은다 (HARN-67 ②).
    # blocked 계열(other_reasons)로 취급하되, 목록에서 일반 차단과 구별되지 않으면 "왜
    # 안 풀리는가"를 사람이 다시 조사해야 한다 — 취소는 done과 달리 기다려도 안 풀린다.
    cancelled_detail: dict[str, list[str]] = {}
    # 게이트 대기 태스크의 게이트 ID — 아래에서 human_gate 대신 blocked로 접을 때 목록에서
    # 게이트 정보가 사라지지 않게 태스크별로 따로 둔다(PR #1025 Codex P2-1).
    gate_detail: dict[str, list[str]] = {}
    other_reasons = False
    for exc in excluded:
        if exc.reason in ("gates", "track_gate"):
            gate_ids.extend(exc.detail)
            gate_detail[exc.task_id] = list(exc.detail)
        elif exc.reason == "owner":
            continue  # 사람 소유 태스크도 사람 대기의 일종
        elif exc.reason == "claimed_remote":
            # 다른 세션이 원격 claim 중 — in_progress 대기의 일종
            remote_held.append(f"{exc.task_id} (원격: {exc.detail[0] if exc.detail else '?'})")
        elif exc.reason == "deps_cancelled":
            cancelled_detail[exc.task_id] = list(exc.detail)
            other_reasons = True
        else:
            other_reasons = True
    pending_gates = sorted(
        {g for g in gate_ids if g in backlog.gates and not backlog.gates[g].passed}
    )
    if pending_gates and not other_reasons:
        return "human_gate", pending_gates

    if active or remote_held:
        local = [f"{t.id} ({t.session or '?'})" for t in active]
        return "in_progress", sorted(local + remote_held)
    # 취소된 선행이 하나라도 있으면 human_gate로 접지 않는다 — 게이트를 전부 열어도 그
    # 태스크는 남으므로 "사람 게이트만 해소되면 진행 가능"은 거짓 정지 사유가 된다
    # (PR #1025 Codex P2-1: 혼합 정체는 blocked). 일반 deps만 섞인 경우는 종전 동작(human_gate).
    if pending_gates and not cancelled_detail:
        return "human_gate", pending_gates

    def _label(task: Task) -> str:
        # 취소된 선행 표기 — 정정 경로(amend --remove-depends)가 있음을 목록에서 바로 알린다.
        # 게이트 대기 표기 — human_gate를 포기한 대가로 게이트 ID가 목록에서 사라지면 안 된다.
        deps = cancelled_detail.get(task.id)
        if deps:
            return f"{task.id} (취소된 선행: {', '.join(deps)})"
        gates = gate_detail.get(task.id)
        if gates:
            return f"{task.id} (게이트 대기: {', '.join(gates)})"
        return task.id

    return "blocked", sorted(_label(t) for t in open_todo)
