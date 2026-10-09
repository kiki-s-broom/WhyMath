"""`done`의 CI 미러 게이트 — 미러 부재를 warn에서 block으로 승격하는 판정 (HARN-173).

왜 있는가 (ci-local-repro-gap 4회차 · 2026-09-25 EOS-24 PR #1316):
  `backlog.py done`은 같은 커밋의 CI 미러 결과(`.claude/cache/ci_mirror.json`)가 없어도 경고만
  했다(HARN-119 ② "1단계 warn"). 세션은 미러를 쓰지 않고 잡 스텝을 손으로 골라 재현했고
  `harness-integrity`의 `ruff check scripts tests/harness` 스텝을 빠뜨려 PR CI가 red가 됐다.
  1~3회차 대책(HARN-129·HARN-172)은 **도구**를 고쳤고, 이번 회차는 도구가 있는데 **쓰지 않은**
  축이다. 경고는 `done`에서 한 번 떴고 아무도 멈추지 않았다.

판정 (정본 = `docs/standards/build_harness.md` §3c "`done` CI 미러 게이트"):
  · 적용 범위 = 소유자가 claude이고 PR 증적 경로(`--no-pr` 미지정)인 done. 그 밖(`--no-pr` 경로·
    사람 소유)은 미러 대상이 아니므로 종전 그대로다(경고조차 새로 만들지 않는다).
  · `ci_mirror_at_done=block`이면 미러 상태가 unknown(결과 없음·다른 커밋·형식 깨짐·잡 0건)
    또는 fail일 때 거부한다. **not_executed(식·조건 스텝이라 원리상 로컬에서 못 도는 검사)는
    warn을 유지한다** — 조건 스텝을 로컬에서 평가하는 HARN-181 전까지 그런 잡은 항상 exit 3이라,
    막으면 그 잡을 건드리는 모든 done이 막힌다.
  · 예외 경로 = `done --no-mirror '<사유>'`. 사유가 비었거나 공백뿐이면 거부한다(무사유 면제
    없음). 사유는 태스크 notes와 이벤트 대장 양쪽에 남는다 — 남지 않는 탈출구는 게이트를
    끄는 것과 같다.
  · 조회 자체가 실패한 환경(미러 모듈 부재·git 없음)은 fail-open(경고 후 통과)이되 상태를
    `unavailable`로 **따로** 기록한다 — "모른다"는 통과로 세지 않는다(측정 실패 ≠ 통과).

이 모듈은 판정만 한다(순수 함수 + 조회). 출력·대장 쓰기는 `backlog.cmd_done`의 몫이다 —
`backlog.py`는 동시에 가장 많이 고쳐지는 파일이라 배선을 몇 줄로 묶어 두려고 분리했다.

한계 (명시):
  · 이 게이트는 `done`(완료 선언) 시점에만 선다. `/drive` 순서가 커밋→PR(푸시)→done이라 red
    푸시 자체는 막지 못하고 **미검증 완료 선언**을 막는다. 푸시 시점 신호(미러 결과 커밋과 푸시 대상
    HEAD의 불일치 고지)는 `push_mirror_notice.py`(HARN-209)가 맡는다.
  · 거부(exit 1)는 대장에 아무것도 쓰지 않는 계약이라 **거부 건수는 대장에 남지 않는다**. 사후
    감시는 통과한 done의 `mirror_state`·`no_mirror_reason` 분포(`policy report`)로 근사한다.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import store
from models import CI_MIRROR_AT_DONE_MODES

MODE_WARN = "warn"
MODE_BLOCK = "block"

# 미러 상태 5종 — 앞 4개는 `ci_mirror.VERDICT_*`와 같은 문자열이고(계약 동결 테스트가 대조),
# unavailable은 조회 자체가 실패했다는 이 모듈만의 상태다. 3상태 이상을 2상태로 접지 않는다:
# pass가 아닌 것을 전부 "실패"로 접으면 미실행(원리상 못 돎)과 모름(측정 안 함)이 같은 값이 된다.
STATE_PASS = "pass"
STATE_NOT_EXECUTED = "not_executed"
STATE_FAIL = "fail"
STATE_UNKNOWN = "unknown"
STATE_UNAVAILABLE = "unavailable"
MIRROR_STATES: tuple[str, ...] = (
    STATE_PASS,
    STATE_NOT_EXECUTED,
    STATE_FAIL,
    STATE_UNKNOWN,
    STATE_UNAVAILABLE,
)

# 이 done이 어느 경로인가 — 미러 대상은 SCOPE_PR뿐이다.
SCOPE_PR = "pr"
SCOPE_NO_PR = "no_pr"
SCOPE_HUMAN = "human"
SCOPES: tuple[str, ...] = (SCOPE_PR, SCOPE_NO_PR, SCOPE_HUMAN)

# 판정 결과 — 호출측이 무엇을 할지의 분류.
OUTCOME_PASS = "pass"  # 미러 통과 — 할 말 없음
OUTCOME_WARN = "warn"  # 종전 경고 경로 — 거부하지 않는다(warn 정책·미실행·조회 실패)
OUTCOME_BYPASS = "bypass"  # block이 거부했을 상태를 `--no-mirror` 사유로 통과 (기록 필수)
OUTCOME_REJECT = "reject"  # 거부 — 대장에 아무것도 쓰지 않는다
OUTCOME_EXEMPT = "exempt"  # 미러 대상이 아닌 경로 — 종전 그대로

# block이 거부하는 상태 — not_executed·unavailable은 여기 넣지 않는 것이 판정이다.
_BLOCKED_STATES: frozenset[str] = frozenset({STATE_UNKNOWN, STATE_FAIL})


# ── 사유·범위 ────────────────────────────────────────────────────────────────


def check_no_mirror_reason(reason: str | None) -> str | None:
    """`--no-mirror` 사유의 유효성 — 문제가 있으면 거부 문구, 없으면 None.

    미지정(None)과 "지정했는데 비었다"를 가른다: 후자는 셸 변수가 비어 전달된 경우일 수 있어
    조용히 통과시키면 무사유 면제가 된다.
    """
    if reason is None:
        return None
    if reason == "":
        return "--no-mirror 사유가 비어 있다 — 무사유 면제는 없다(인자가 비어 전달됐는지 확인하라)"
    if not reason.strip():
        return "--no-mirror 사유가 공백 문자뿐이다 — 무사유 면제는 없다. 실제 사유를 적어라"
    return None


def scope_of(owner: str, no_pr_reason: str | None) -> str:
    """done 경로 분류. 사람 소유가 먼저다 — 소유자가 사람이면 미러를 요구할 주체가 아니다."""
    if owner != "claude":
        return SCOPE_HUMAN
    if no_pr_reason is not None:
        return SCOPE_NO_PR
    return SCOPE_PR


# ── 정책 값 해석 ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ModeResolution:
    """`ci_mirror_at_done`의 유효 값과, 그 값을 확정하지 못했을 때의 사유."""

    mode: str
    errors: tuple[str, ...] = ()

    @property
    def fail_closed(self) -> bool:
        """정책 파일이 깨져 값을 확정하지 못해 block으로 취급했는가."""
        return bool(self.errors)


def resolve_mode(configured: str, policy_errors: Iterable[str]) -> ModeResolution:
    """정책 값을 유효 강제 수준으로 옮긴다 — **모르면 엄격한 쪽**(CLAUDE.md 제2조 잠정 해석).

    policy.yaml에 오류가 하나라도 있으면 값을 믿지 않는다: 미지 필드 오타(`ci_mirror_at_dne`)는
    조용히 기본값 warn으로 떨어지고, 잘못된 값은 검증만 실패하므로 "승격했다고 믿는 정책이
    실은 꺼져 있는" 상태를 만든다. 그 상태를 통과로 두면 상시 실패하는 fail-open이 된다.
    출구는 있다 — 정책을 고치거나 `--no-mirror '<사유>'`.
    """
    errors = tuple(policy_errors)
    if errors:
        return ModeResolution(MODE_BLOCK, errors)
    if configured not in CI_MIRROR_AT_DONE_MODES:
        return ModeResolution(
            MODE_BLOCK, (f"policy.ci_mirror_at_done: '{configured}' 미등록 — 값을 확정할 수 없다",)
        )
    return ModeResolution(configured)


def load_mode(root: Path) -> ModeResolution:
    """policy.yaml을 읽어 유효 강제 수준을 돌려준다. 읽기 실패도 엄격한 쪽으로 접는다."""
    yaml_errors: tuple[type[Exception], ...] = (
        (store.yaml.YAMLError,) if store.yaml is not None else ()
    )
    try:
        policy, errors = store.load_policy(root)
    except (OSError, RuntimeError, *yaml_errors) as exc:
        return ModeResolution(
            MODE_BLOCK, (f"policy.yaml 읽기 실패({type(exc).__name__}) — 값을 확정할 수 없다",)
        )
    return resolve_mode(policy.ci_mirror_at_done, errors)


# ── 미러 조회 ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MirrorLookup:
    """이번 커밋의 미러 판정 — `state`는 MIRROR_STATES 중 하나다."""

    state: str
    reason: str
    commit: str | None = None
    #: 조회 자체가 실패했을 때의 예외 타입명(침묵 실패 금지 — 타입명은 항상 남긴다).
    error_type: str | None = None


def lookup_mirror(root: Path) -> MirrorLookup:
    """미러 결과 파일을 이번 HEAD와 대조해 5상태 중 하나로 답한다.

    `ci_mirror`는 호출 시점에 임포트한다(선택 의존 — 없으면 unavailable). 모듈 최상단에서
    임포트하면 이 모듈 임포트가 실패해 `backlog.py` 전체가 죽는다.
    """
    try:
        harness_dir = str(Path(__file__).resolve().parent)
        if harness_dir not in sys.path:
            sys.path.append(harness_dir)
        import ci_mirror  # noqa: PLC0415  (선택 의존 — 없으면 unavailable)

        commit = ci_mirror.current_commit(root)
        verdict = ci_mirror.mirror_verdict(root / ci_mirror.DEFAULT_RESULT_PATH, commit)
        known = {
            ci_mirror.VERDICT_PASS: STATE_PASS,
            ci_mirror.VERDICT_NOT_EXECUTED: STATE_NOT_EXECUTED,
            ci_mirror.VERDICT_FAIL: STATE_FAIL,
            ci_mirror.VERDICT_UNKNOWN: STATE_UNKNOWN,
        }
    except (ImportError, OSError, subprocess.SubprocessError) as exc:
        name = type(exc).__name__
        return MirrorLookup(
            STATE_UNAVAILABLE,
            f"CI 미러 상태를 확인하지 못했다({name}) — 측정 실패는 통과가 아니다",
            None,
            name,
        )
    state = known.get(verdict.state)
    if state is None:
        # ci_mirror가 새 상태를 도입했는데 이 표가 따라오지 않은 경우 — 통과로 접지 않고 모름.
        return MirrorLookup(
            STATE_UNKNOWN,
            f"CI 미러가 알 수 없는 판정 상태({verdict.state!r})를 돌려줬다 — {verdict.reason}",
            commit,
        )
    return MirrorLookup(state, verdict.reason, commit)


# ── 판정 ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Decision:
    """게이트 판정 — 호출측(`cmd_done`)이 출력·대장 쓰기를 이 값대로 한다."""

    outcome: str
    #: 종전 경고(`_warn_if_ci_mirror_missing`)를 호출측이 출력해야 하는가.
    warn_legacy: bool = False
    #: OUTCOME_REJECT일 때의 거부 문구(처방 포함). 그 밖에는 None.
    reject_message: str | None = None
    #: stderr로 덧붙일 안내 줄들.
    notices: tuple[str, ...] = ()
    #: done 이벤트에 얹을 필드 — 거부면 비어 있다(대장에 아무것도 쓰지 않는다).
    event_fields: Mapping[str, object] = field(default_factory=dict)
    #: 태스크 notes에 append할 `--no-mirror` 사유(없으면 None).
    note: str | None = None

    @property
    def rejected(self) -> bool:
        return self.outcome == OUTCOME_REJECT


def _reject_text(mode: str, lookup: MirrorLookup, mode_errors: tuple[str, ...]) -> str:
    failed = lookup.state == STATE_FAIL
    head = (
        f"CI 미러 게이트(ci_mirror_at_done={mode}) — 이번 커밋의 로컬 재현이 "
        f"{'실패했다' if failed else '측정되지 않았다'}: {lookup.reason}"
    )
    lines = [head]
    if mode_errors:
        lines.append(
            "  · 정책 값을 확정하지 못해 block으로 취급했다(모르면 엄격한 쪽): "
            + " / ".join(mode_errors)
        )
    fix = "실패한 잡·스텝을 고친 뒤 이 커밋을 다시 재현하세요" if failed else "이 커밋을 재현하세요"
    lines.append(
        f"  → {fix}: python3 scripts/harness/ci_mirror.py run [--prepend-path <python 디렉터리>] "
        "(통과 또는 미실행이면 done이 통과합니다)"
    )
    lines.append(
        "  → 환경 때문에 재현할 수 없다면: done <id> --artifact ... --no-mirror '<사유>' — "
        "사유는 태스크 notes와 이벤트 대장에 남습니다(무사유 면제는 없습니다)"
    )
    lines.append("  → 대장에는 아무것도 쓰지 않았습니다")
    return "\n".join(lines)


def decide(
    *,
    scope: str,
    mode: str,
    state: str | None,
    no_mirror_reason: str | None = None,
    lookup: MirrorLookup | None = None,
    mode_errors: tuple[str, ...] = (),
) -> Decision:
    """(경로·강제 수준·미러 상태·`--no-mirror`) → 판정. 부수효과 없는 순수 함수다.

    알 수 없는 상태·강제 수준은 **엄격한 쪽**으로 접는다(상태 → unknown, 수준 → block).
    """
    reason_error = check_no_mirror_reason(no_mirror_reason)
    if reason_error is not None:
        return Decision(OUTCOME_REJECT, reject_message=reason_error)
    cleaned = None if no_mirror_reason is None else no_mirror_reason.strip()
    events: dict[str, object] = {"mirror_scope": scope}
    if cleaned is not None:
        events["no_mirror_reason"] = cleaned

    if scope != SCOPE_PR:
        # 미러 대상이 아닌 경로 — 종전 그대로(경고는 호출측이 종전 헬퍼로 낸다).
        notices: tuple[str, ...] = ()
        if cleaned is not None:
            notices = (
                f"ℹ --no-mirror는 이 경로({scope})에서 필요하지 않았다 — 미러 대상이 아니다. "
                "사유는 그대로 기록된다",
            )
        return Decision(
            OUTCOME_EXEMPT,
            warn_legacy=True,
            notices=notices,
            event_fields=events,
            note=cleaned,
        )

    if mode not in CI_MIRROR_AT_DONE_MODES:
        mode = MODE_BLOCK
    if state not in MIRROR_STATES:
        state = STATE_UNKNOWN
    # 판정에 쓰는 상태는 정규화된 `state`다 — 조회 원본의 사유·커밋만 이어받는다.
    view = MirrorLookup(
        state,
        lookup.reason if lookup else "(조회 사유 미제공)",
        lookup.commit if lookup else None,
        lookup.error_type if lookup else None,
    )
    events["mirror_gate_mode"] = mode
    events["mirror_state"] = state
    if view.commit:
        events["mirror_commit"] = view.commit

    if mode == MODE_BLOCK and state in _BLOCKED_STATES:
        if cleaned is None:
            return Decision(
                OUTCOME_REJECT,
                reject_message=_reject_text(mode, view, mode_errors),
            )
        events["mirror_outcome"] = OUTCOME_BYPASS
        return Decision(
            OUTCOME_BYPASS,
            notices=(
                f"⚠ --no-mirror로 CI 미러 게이트를 우회한다(미러 상태: {state}) — "
                f"사유 '{cleaned}'는 태스크 notes와 이벤트 대장에 기록된다",
            ),
            event_fields=events,
            note=cleaned,
        )

    extra: list[str] = []
    if cleaned is not None:
        extra.append(
            f"ℹ --no-mirror 사유는 기록되지만 이번 판정(미러 상태: {state})에는 필요하지 않았다"
        )
    if state == STATE_PASS:
        events["mirror_outcome"] = OUTCOME_PASS
        return Decision(OUTCOME_PASS, notices=tuple(extra), event_fields=events, note=cleaned)
    if state == STATE_UNAVAILABLE and mode == MODE_BLOCK:
        extra.append(
            "ℹ ci_mirror_at_done=block이지만 미러 상태를 조회하지 못해 거부하지 않았다"
            "(fail-open) — 이 done은 mirror_state=unavailable로 기록되며 통과로 세지 않는다"
        )
    events["mirror_outcome"] = OUTCOME_WARN
    return Decision(
        OUTCOME_WARN,
        warn_legacy=True,
        notices=tuple(extra),
        event_fields=events,
        note=cleaned,
    )


def judge(
    root: Path,
    *,
    owner: str,
    no_pr_reason: str | None,
    no_mirror_reason: str | None,
    lookup: MirrorLookup | None = None,
    mode: ModeResolution | None = None,
) -> Decision:
    """정책·미러 조회를 모아 판정한다. 미러 대상이 아닌 경로는 조회조차 하지 않는다."""
    scope = scope_of(owner, no_pr_reason)
    if scope != SCOPE_PR:
        return decide(scope=scope, mode=MODE_WARN, state=None, no_mirror_reason=no_mirror_reason)
    # 값싼 입력 검증이 먼저다 — 무사유 면제는 조회보다 앞서 거부한다.
    reason_error = check_no_mirror_reason(no_mirror_reason)
    if reason_error is not None:
        return Decision(OUTCOME_REJECT, reject_message=reason_error)
    resolution = mode or load_mode(root)
    view = lookup or lookup_mirror(root)
    return decide(
        scope=scope,
        mode=resolution.mode,
        state=view.state,
        no_mirror_reason=no_mirror_reason,
        lookup=view,
        mode_errors=resolution.errors,
    )


# ── CI 도달 잡 안내 (HARN-173 ⑤) ─────────────────────────────────────────────

CI_REACH_COMPUTED = "computed"
CI_REACH_NO_WORKFLOW = "no_workflow"
CI_REACH_FAILED = "failed"

DEFAULT_WORKFLOW = Path(".github/workflows/ci.yml")


@dataclass(frozen=True)
class CiReach:
    """변경 파일이 닿는 CI 잡 — `ci_job_coverage.py scope`의 답을 done에 붙인다."""

    status: str
    jobs: tuple[str, ...] = ()
    changed_count: int = 0
    base: str = ""
    error_type: str | None = None
    detail: str = ""

    @property
    def event_fields(self) -> dict[str, object]:
        fields: dict[str, object] = {"ci_reach_status": self.status}
        if self.status == CI_REACH_COMPUTED:
            fields["ci_reach_jobs"] = list(self.jobs)
            fields["ci_reach_changed"] = self.changed_count
        if self.error_type is not None:
            fields["ci_reach_error"] = self.error_type
        return fields

    def stdout_line(self) -> str | None:
        """정상 산출일 때만 한 줄 안내. 못 구했으면 None(경고는 `warning_line`)."""
        if self.status != CI_REACH_COMPUTED:
            return None
        listing = ", ".join(self.jobs) or "(없음)"
        tail = ""
        if self.changed_count == 0:
            tail = " — 변경 0건: 이미 트렁크에 있는 커밋이면 이 판정은 의미가 없다"
        return f"ℹ CI 도달 잡(트렁크 {self.base} 대비 변경 {self.changed_count}건): {listing}{tail}"

    def warning_line(self) -> str | None:
        if self.status != CI_REACH_FAILED:
            return None
        return (
            f"⚠ CI 도달 잡을 계산하지 못했다({self.error_type}) — done은 막지 않는다. "
            f"로컬 재현 범위는 `python3 scripts/harness/ci_job_coverage.py scope`로 직접 확인하라"
            f"{': ' + self.detail if self.detail else ''}"
        )


def ci_reach(root: Path, base: str = "origin/main") -> CiReach:
    """변경 파일(트렁크 대비 diff)이 닿는 CI 잡을 계산한다. 실패해도 done을 막지 않는다.

    워크플로 파일이 없는 저장소(hermetic 임시 저장소 등)는 CI가 없는 것이므로 오류가 아니라
    `no_workflow`다. 그 밖의 실패는 예외 타입명을 남긴다 — 무타입 경고 금지.
    """
    workflow_path = root / DEFAULT_WORKFLOW
    if not workflow_path.exists():
        return CiReach(CI_REACH_NO_WORKFLOW, base=base)
    yaml_errors: tuple[type[Exception], ...] = (
        (store.yaml.YAMLError,) if store.yaml is not None else ()
    )
    try:
        harness_dir = str(Path(__file__).resolve().parent)
        if harness_dir not in sys.path:
            sys.path.append(harness_dir)
        import ci_job_coverage as coverage  # noqa: PLC0415  (선택 의존)

        workflow = coverage.load_workflow(workflow_path)
        changed = coverage.changed_files_from_git(base, root)
        scopes = coverage.classify_jobs(workflow, changed)
        jobs = coverage.jobs_to_cover(scopes)
    except (
        ImportError,
        OSError,
        subprocess.SubprocessError,
        RuntimeError,
        ValueError,
        *yaml_errors,
    ) as exc:
        return CiReach(
            CI_REACH_FAILED,
            base=base,
            error_type=type(exc).__name__,
            detail=str(exc).splitlines()[0][:160] if str(exc) else "",
        )
    return CiReach(CI_REACH_COMPUTED, tuple(jobs), len(changed), base)


# ── 사후 감시 — `policy report` 절 ────────────────────────────────────────────


@dataclass
class MirrorSummary:
    """done 이벤트의 미러 필드 집계 — 승격 판정의 사후 감시 근거."""

    total_done: int = 0
    #: HARN-173 이전에 기록되어 mirror_scope 필드가 없는 done.
    untracked: int = 0
    by_scope: dict[str, int] = field(default_factory=dict)
    pr_by_state: dict[str, int] = field(default_factory=dict)
    no_mirror_used: int = 0
    bypassed: int = 0
    ci_reach_failed: int = 0
    #: 읽지 못해 세지 못한 줄 — 침묵하지 않는다.
    unreadable_lines: int = 0


def summarize_done_events(events: Iterable[Mapping[str, object]]) -> MirrorSummary:
    """done 이벤트만 골라 미러 필드를 센다. done이 아닌 이벤트는 무시한다.

    PR 경로의 상태 집계에서 알 수 없는 값은 `미분류`로 따로 센다 — 5상태로 접지 않는다.
    """
    summary = MirrorSummary()
    for event in events:
        if event.get("action") != "done":
            continue
        summary.total_done += 1
        scope = event.get("mirror_scope")
        if scope is None:
            summary.untracked += 1
            continue
        key = str(scope)
        summary.by_scope[key] = summary.by_scope.get(key, 0) + 1
        if "no_mirror_reason" in event:
            summary.no_mirror_used += 1
        if event.get("mirror_outcome") == OUTCOME_BYPASS:
            summary.bypassed += 1
        if event.get("ci_reach_status") == CI_REACH_FAILED:
            summary.ci_reach_failed += 1
        if scope == SCOPE_PR:
            state = str(event.get("mirror_state", "미분류"))
            if state not in MIRROR_STATES:
                state = "미분류"
            summary.pr_by_state[state] = summary.pr_by_state.get(state, 0) + 1
    return summary


def collect_done_events(root: Path, days: int) -> tuple[list[dict[str, object]], int]:
    """최근 N일의 done 이벤트와 읽지 못한 줄 수 — 세션 샤드 전부를 읽는다(HARN-46)."""
    cutoff = datetime.now().astimezone() - timedelta(days=days)
    events: list[dict[str, object]] = []
    unreadable = 0
    for path in store.event_paths(root):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                unreadable += 1
                continue
            if not isinstance(event, dict):
                unreadable += 1  # 유효한 JSON이지만 이벤트가 아니다 — 조용히 버리지 않는다
                continue
            if event.get("action") != "done":
                continue
            moment = store.parse_event_ts(event.get("ts"))
            if moment is None:
                unreadable += 1
                continue
            if moment.moment < cutoff:
                continue
            events.append(event)
    return events, unreadable


def render_summary(summary: MirrorSummary, days: int) -> list[str]:
    """`policy report`에 얹는 절 — 통과한 done만 센다는 한계를 함께 적는다."""
    lines = [f"done CI 미러 게이트 (HARN-173) — 최근 {days}일, done {summary.total_done}건"]
    if summary.total_done == 0:
        lines.append("  (done 없음)")
    else:
        pr_total = sum(summary.pr_by_state.values())
        ordered = [*MIRROR_STATES, "미분류"]
        states = " · ".join(
            f"{name} {summary.pr_by_state[name]}" for name in ordered if name in summary.pr_by_state
        )
        lines.append(f"  PR 증적 경로(claude 소유) {pr_total}건 — 미러 상태: {states or '(없음)'}")
        lines.append(
            f"  미러 대상 아닌 경로 — --no-pr {summary.by_scope.get(SCOPE_NO_PR, 0)}건 · "
            f"사람 소유 {summary.by_scope.get(SCOPE_HUMAN, 0)}건"
        )
        lines.append(
            f"  --no-mirror 사용 {summary.no_mirror_used}건(우회 성립 {summary.bypassed}건) · "
            f"게이트 이전 기록(mirror_scope 없음) {summary.untracked}건"
        )
        if summary.ci_reach_failed:
            lines.append(
                f"  ⚠ CI 도달 잡 계산 실패 {summary.ci_reach_failed}건 (ci_reach_error 참조)"
            )
    if summary.unreadable_lines:
        lines.append(f"  ⚠ 판독 불가 줄 {summary.unreadable_lines}건 — 위 집계에서 빠졌다")
    lines.append(
        "  · unavailable(조회 실패)은 통과가 아니라 측정 실패다 — 따로 세며 통과로 합치지 않는다"
    )
    lines.append(
        "  · 거부된 done은 대장에 남지 않아 이 표에 없다 — 통과한 done의 분포로만 사후 감시한다"
    )
    return lines


def render_report(root: Path, days: int) -> list[str]:
    """이벤트 대장에서 집계해 `policy report` 절을 만든다."""
    events, unreadable = collect_done_events(root, days)
    summary = summarize_done_events(events)
    summary.unreadable_lines = unreadable
    return render_summary(summary, days)
