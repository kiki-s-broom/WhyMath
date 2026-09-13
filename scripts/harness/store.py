"""backlog/ 저장소 — 로드·저장·이벤트 로그·무결성 검증.

파일 배치 (전부 git 커밋 대상):
    backlog/tracks.yaml           트랙 정의 + stage_order
    backlog/gates.yaml            사람 게이트 대장
    backlog/tasks/<id>.yaml       태스크당 1파일 (병렬 세션 충돌 원천 차단)
    backlog/events/<actor>.ndjson append-only 상태변경 로그 — **세션(=브랜치)당 1샤드**
    backlog/events.ndjson         레거시 단일 대장 (읽기 전용 역사 — 신규 기록 없음)

이벤트 샤딩(HARN-46, 2026-08-31): 원래는 events.ndjson 한 파일에 모든 세션이
append했고 `.gitattributes merge=union`이 병렬 충돌을 흡수한다고 믿었다. 그러나
**GitHub의 mergeability 판정은 저장소 merge driver를 적용하지 않아서**, main에
어떤 PR이 착지하든 이 파일을 함께 만진 열린 PR은 전부 dirty(충돌)가 됐다 —
PR #931이 CI green을 4회 확보하고도 머지가 반복 지연된 실측 사고. 로컬 병합은
매번 충돌 0이었으므로 문제는 데이터가 아니라 **배치**다. 대책은 tasks/의
태스크당-1파일 선례와 동형: 세션당 1샤드로 나눠 두 브랜치가 같은 파일을 동시에
append하는 상황 자체를 없앤다(충돌을 '해소 가능'이 아니라 '발생 불가능'으로).

읽기는 PyYAML(사람 손 편집 허용을 위해), 쓰기는 자체 직렬화기
(키 순서·인용 규칙 고정 → diff 안정·결정적 출력).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from dataclasses import fields as dc_fields
from datetime import date, datetime
from pathlib import Path

from models import (
    EOS_PRIORITY_BACKFILL_GATE,
    TERMINAL_STATUSES,
    Backlog,
    Gate,
    Policy,
    Task,
    Track,
)

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover - 환경 의존
    yaml = None

YAML_MISSING_MSG = (
    "[빌드하네스] PyYAML이 없습니다. `python3 -m pip install pyyaml` 후 재시도하세요."
)

# ── 경로 ─────────────────────────────────────────────────────────────────────


def find_repo_root(start: Path | None = None) -> Path:
    """`.git`을 기준으로 저장소 루트 탐색 (스크립트 위치 → 상위)."""
    here = start or Path(__file__).resolve().parent
    for candidate in (here, *here.parents):
        if (candidate / ".git").exists():
            return candidate
    raise RuntimeError("git 저장소 루트를 찾지 못했습니다")


def backlog_dir(root: Path) -> Path:
    return root / "backlog"


# ── 직렬화 (쓰기: 자체 규칙, 읽기: PyYAML) ──────────────────────────────────

_BARE_SAFE_RE = re.compile(r"^[A-Za-z0-9가-힣][A-Za-z0-9가-힣 ._/·→\-]*$")
_YAML_RESERVED = {"null", "true", "false", "yes", "no", "on", "off", "~"}


def _scalar(value: object) -> str:
    """스칼라 1개를 YAML 안전 문자열로 (모호하면 JSON 인용 = 유효한 YAML)."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    s = str(value)
    needs_quote = (
        not _BARE_SAFE_RE.match(s)
        or s.lower() in _YAML_RESERVED
        or re.match(r"^\d+$", s) is not None
        or s != s.strip()
    )
    return json.dumps(s, ensure_ascii=False) if needs_quote else s


def _dump_mapping(data: dict[str, object], key_order: list[str]) -> str:
    """1단 매핑 + 문자열 리스트를 고정 키 순서로 직렬화."""
    lines: list[str] = []
    for key in key_order:
        if key not in data:
            continue
        value = data[key]
        if isinstance(value, list):
            if not value:
                lines.append(f"{key}: []")
            else:
                lines.append(f"{key}:")
                lines.extend(f"  - {_scalar(item)}" for item in value)
        else:
            lines.append(f"{key}: {_scalar(value)}")
    return "\n".join(lines) + "\n"


_TASK_KEY_ORDER = [f.name for f in dc_fields(Task)]
_GATE_KEY_ORDER = [f.name for f in dc_fields(Gate)]


def dump_task(task: Task) -> str:
    data = {k: getattr(task, k) for k in _TASK_KEY_ORDER}
    header = "# 빌드 하네스 태스크 — 상태 변경은 scripts/harness/backlog.py CLI 사용 권장\n"
    return header + _dump_mapping(data, _TASK_KEY_ORDER)


def dump_gates(gates: list[Gate]) -> str:
    lines = [
        "# 사람 게이트 대장 — clear는 evidence 필수 · 사람이 직접 닫으면 --as <담당자>(HARN-60)",
        "gates:",
    ]
    for gate in gates:
        data = {k: getattr(gate, k) for k in _GATE_KEY_ORDER}
        first = True
        for key in _GATE_KEY_ORDER:
            prefix = "  - " if first else "    "
            lines.append(f"{prefix}{key}: {_scalar(data[key])}")
            first = False
    return "\n".join(lines) + "\n"


def dump_tracks(stage_order: list[str], tracks: list[Track]) -> str:
    lines = [
        "# 트랙 정의 — stage_order가 next 정렬의 1차 키다",
        "stage_order: [" + ", ".join(stage_order) + "]",
        "tracks:",
    ]
    for track in tracks:
        lines.append(f"  {track.id}:")
        lines.append(f"    title: {_scalar(track.title)}")
        if track.roadmap_ref:
            lines.append(f"    roadmap_ref: {_scalar(track.roadmap_ref)}")
        if track.entry_gate:
            lines.append(f"    entry_gate: {_scalar(track.entry_gate)}")
    return "\n".join(lines) + "\n"


def _load_yaml(path: Path) -> dict:
    if yaml is None:  # pragma: no cover - 환경 의존
        raise RuntimeError(YAML_MISSING_MSG)
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data or {}


def _coerce(cls: type, data: dict, source: str, errors: list[str]) -> object | None:
    """dict → dataclass. 미지 키는 오류로 기록(오타 방지)."""
    known = {f.name for f in dc_fields(cls)}
    unknown = set(data) - known
    if unknown:
        errors.append(f"{source}: 미지 필드 {sorted(unknown)}")
    kwargs = {k: v for k, v in data.items() if k in known}
    # 리스트 필드의 None을 빈 리스트로 정규화 (손 편집 관용)
    for f in dc_fields(cls):
        if f.name in kwargs and kwargs[f.name] is None and "list" in str(f.type):
            kwargs[f.name] = []
        # PyYAML이 날짜를 date 객체로 파싱하는 경우 문자열로 되돌림
        if isinstance(kwargs.get(f.name), (date, datetime)):
            kwargs[f.name] = kwargs[f.name].strftime("%Y-%m-%d")
    try:
        return cls(**kwargs)
    except TypeError as exc:
        errors.append(f"{source}: 필수 필드 누락 또는 형식 오류 — {exc}")
        return None


# ── 로드 ─────────────────────────────────────────────────────────────────────


def load_backlog(root: Path) -> tuple[Backlog, list[str]]:
    """backlog/ 전체 로드. (백로그, 스키마 오류 목록) 반환."""
    errors: list[str] = []
    bdir = backlog_dir(root)
    backlog = Backlog()

    tracks_path = bdir / "tracks.yaml"
    if tracks_path.exists():
        raw = _load_yaml(tracks_path)
        backlog.stage_order = list(raw.get("stage_order") or [])
        for tid, tdata in (raw.get("tracks") or {}).items():
            track = _coerce(Track, {"id": tid, **(tdata or {})}, f"tracks.yaml:{tid}", errors)
            if track:
                backlog.tracks[tid] = track  # type: ignore[assignment]
    else:
        errors.append("backlog/tracks.yaml 없음 (seed 미실행?)")

    gates_path = bdir / "gates.yaml"
    if gates_path.exists():
        raw = _load_yaml(gates_path)
        for gdata in raw.get("gates") or []:
            gate = _coerce(Gate, gdata or {}, f"gates.yaml:{(gdata or {}).get('id', '?')}", errors)
            if gate:
                backlog.gates[gate.id] = gate  # type: ignore[union-attr]

    tasks_dir = bdir / "tasks"
    if tasks_dir.is_dir():
        for path in sorted(tasks_dir.glob("*.yaml")):
            raw = _load_yaml(path)
            task = _coerce(Task, raw, path.name, errors)
            if task is None:
                continue
            assert isinstance(task, Task)
            if task.id != path.stem:
                errors.append(f"{path.name}: id '{task.id}' ≠ 파일명 stem (단일 진실 원천 위반)")
            if task.id in backlog.tasks:
                errors.append(f"{path.name}: 태스크 ID 중복 '{task.id}'")
            backlog.tasks[task.id] = task

    return backlog, errors


# ── 저장·이벤트 ──────────────────────────────────────────────────────────────


def save_task(root: Path, task: Task) -> Path:
    path = backlog_dir(root) / "tasks" / f"{task.id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_task(task), encoding="utf-8")
    return path


def save_gates(root: Path, gates: list[Gate]) -> Path:
    path = backlog_dir(root) / "gates.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_gates(gates), encoding="utf-8")
    return path


def save_tracks(root: Path, stage_order: list[str], tracks: list[Track]) -> Path:
    path = backlog_dir(root) / "tracks.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_tracks(stage_order, tracks), encoding="utf-8")
    return path


# ── 정책 (backlog/policy.yaml — 부재 시 전부 기본값 = 하위호환) ──────────────

_POLICY_KEY_ORDER = [f.name for f in dc_fields(Policy)]


def dump_policy(policy: Policy) -> str:
    header = (
        "# 조율 정책 — 중복·겹침 감지 강제 수준. 승격(warn→block)은 측정 근거 +\n"
        "# MEMORY.md 결정로그 필수 (docs/standards/build_harness.md §정책)\n"
    )
    data = {k: getattr(policy, k) for k in _POLICY_KEY_ORDER}
    return header + _dump_mapping(data, _POLICY_KEY_ORDER)


def load_policy(root: Path) -> tuple[Policy, list[str]]:
    """policy.yaml 로드. (정책, 오류 목록) 반환 — 파일 부재는 기본값(오류 아님)."""
    errors: list[str] = []
    path = backlog_dir(root) / "policy.yaml"
    if not path.exists():
        return Policy(), errors
    raw = _load_yaml(path)
    policy = _coerce(Policy, raw, "policy.yaml", errors)
    if policy is None:
        return Policy(), errors
    assert isinstance(policy, Policy)
    errors.extend(policy.validate())
    return policy, errors


def save_policy(root: Path, policy: Policy) -> Path:
    path = backlog_dir(root) / "policy.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_policy(policy), encoding="utf-8")
    return path


def current_branch(root: Path) -> str:
    """현재 git 브랜치명 (실패 시 'unknown')."""
    try:
        out = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=root,
            capture_output=True,
            # HARN-19: 로케일(cp949) 디코드 금지 — git 출력은 UTF-8이 정본이다.
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        return (out.stdout or "").strip() or "unknown"
    except Exception as exc:  # pragma: no cover - 환경 의존
        # 침묵 실패 금지 — 예외 타입명을 남긴다 (CLAUDE.md AI·신뢰).
        # 브랜치 미상은 claim·세션 판정을 통째로 흐리므로 조용히 넘기면 안 된다.
        print(
            f"⚠ 현재 브랜치 조회 실패({type(exc).__name__}) — 'unknown'으로 진행", file=sys.stderr
        )
        return "unknown"


def _event_shard_name(actor: str) -> str:
    """actor(브랜치명) → 샤드 파일명 — 결정적·경로 탈출 불가.

    파일명 안전 문자([A-Za-z0-9._-]) 외 전부 '_' 치환: 브랜치명의 '/'가 하위
    디렉터리로 해석되거나 '..'이 events/ 밖을 가리키는 것을 원천 차단한다.
    치환 후 선두 '.'도 벗긴다('..'·숨김 파일 방지). 서로 다른 브랜치가 같은
    이름으로 붕괴하는 경우(예: 'a/b'와 'a_b')는 이론상 가능하지만, 그 한 쌍만
    종전(단일 파일) 상태로 퇴화할 뿐이고 union이 여전히 로컬 병합을 흡수한다.
    상한 120자: 파일시스템 255 한계에 여유를 둔다.
    """
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", actor).lstrip(".") or "unknown"
    return safe[:120] + ".ndjson"


def event_paths(root: Path) -> list[Path]:
    """이벤트 대장 파일 전부 — 레거시 단일 대장 + 세션 샤드(이름 정렬).

    소비자(policy 리포트 등)는 반드시 이 목록을 순회해야 한다. 레거시 파일만
    읽으면 샤딩 이후 기록이 통째로 안 보이고, 샤드만 읽으면 과거 역사가 사라진다
    — 어느 쪽도 무손실이 아니다.
    """
    paths: list[Path] = []
    legacy = backlog_dir(root) / "events.ndjson"
    if legacy.exists():
        paths.append(legacy)
    shard_dir = backlog_dir(root) / "events"
    if shard_dir.is_dir():
        paths.extend(sorted(shard_dir.glob("*.ndjson")))
    return paths


# HARN-44 전환 시점: 이 표기 전환 **이후**에 쓰인 줄만 오프셋을 갖는다. 그 이전 줄은
# 오프셋 없는 머신 로컬 시각이며 **척도 불명**이다(어느 TZ의 세션이 썼는지 줄 자체로는
# 알 수 없다). 과거 줄을 소급 정정하지 않는다 — 실제 오프셋을 모르는 채 값을 바꾸면
# 그건 복원이 아니라 날조다(CLAUDE.md 「날조 금지」·EOS-48 event_time 백필 금지 선례).
_LEGACY_TS_SCALE_UNKNOWN = "오프셋 없는 머신 로컬 시각(척도 불명 — HARN-44 전환 이전)"


@dataclass(frozen=True, slots=True)
class EventMoment:
    """이벤트 1건의 시각 — 정렬 가능한 aware datetime + **그 값을 믿어도 되는가**.

    두 필드를 함께 두는 이유: 레거시 줄도 정렬은 돼야 하지만(안 그러면 리포트에서 통째로
    사라진다), 그 정렬이 *정확하다고* 말해서는 안 된다. 하나로 합치면 둘 중 하나를 잃는다
    — `datetime`만 주면 추정값이 실측값 행세를 하고, 레거시를 버리면 과거가 사라진다.
    """

    moment: datetime
    """항상 tz-aware(비교·정렬이 TypeError 없이 성립). 레거시는 아래 가정이 붙은 값이다."""

    offset_known: bool
    """True=줄에 오프셋이 실려 있었다. False=읽는 쪽 로컬 오프셋을 *가정*해 붙였다."""


def parse_event_ts(raw: object) -> EventMoment | None:
    """이벤트 `ts` → `EventMoment`. 파싱 불가면 None(호출자가 건너뛴다).

    두 표기를 **모두** 읽는다 — 이것이 이 함수의 존재 이유다:
      - `2026-09-01T13:17:22+00:00` (HARN-44 이후) → 그대로 aware, `offset_known=True`.
      - `2026-08-30T00:50:38`       (레거시)      → 읽는 머신의 로컬 오프셋을 붙이고
        `offset_known=False`. 이 값은 *가정*이지 실측이 아니다(`_LEGACY_TS_SCALE_UNKNOWN`).

    레거시를 읽지 못하면 과거가 사라지고, 신규를 읽지 못하면 **오늘 쓴 줄이 조용히
    사라진다** — 후자가 실제 위험이었다: 소비자(policy_warn 리포트)가 엄격 `strptime` +
    `except ValueError: continue` 조합이라, 오프셋을 붙이는 순간 신규 줄 전량이 *에러 없이*
    누락될 뻔했다(침묵 실패 금지).
    """
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return EventMoment(moment=parsed, offset_known=True)
    # 레거시: 로컬 오프셋을 가정해 붙인다(값 자체는 그대로 — 시각을 옮기지 않는다).
    return EventMoment(moment=parsed.astimezone(), offset_known=False)


def append_event(root: Path, action: str, subject_id: str, **extra: object) -> None:
    """append-only 이벤트 로그 — **세션(=actor 브랜치)당 1샤드**에 기록 (HARN-46).

    레거시 `events.ndjson`에는 더 이상 쓰지 않는다(역사 보존·읽기 전용). 이유는
    모듈 docstring 참조 — GitHub mergeability가 merge=union을 적용하지 않아
    공용 단일 파일이 main 착지마다 열린 PR을 dirty로 만들었다(PR #931 실측).
    """
    actor = current_branch(root)
    path = backlog_dir(root) / "events" / _event_shard_name(actor)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        # HARN-44: **오프셋 포함** 표기(`...+09:00`/`...+00:00`). 종전 표기
        # `datetime.now().strftime(...)`는 오프셋 없는 *머신 로컬* 시각이라, KST 세션이 쓴
        # 줄과 UTC 세션이 쓴 줄이 같은 대장에 구분자 없이 섞였다 — 9시간 어긋난 두 척도를
        # 알려주는 필드가 없어 "어느 add가 먼저였나"에 답할 수 없었다(HARN-38 경위 규명
        # §3-1 실측: 'done HARN-36 @00:50:38'은 UTC 세션·'start CUR-16 @23:56:15'는 KST
        # 세션이었고, 그 판정은 claim 커밋의 커밋 시각과 대조해서야 겨우 났다).
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "actor": actor,
        "action": action,
        "id": subject_id,
        **extra,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


# ── 무결성 검증 ──────────────────────────────────────────────────────────────


def detect_cycle(backlog: Backlog) -> list[str]:
    """depends_on 그래프의 사이클을 Kahn 위상정렬로 검출. 사이클 노드 목록 반환."""
    indegree = {tid: 0 for tid in backlog.tasks}
    dependents: dict[str, list[str]] = {tid: [] for tid in backlog.tasks}
    for task in backlog.tasks.values():
        for dep in task.depends_on:
            if dep in backlog.tasks:
                indegree[task.id] += 1
                dependents[dep].append(task.id)
    queue = [tid for tid, deg in indegree.items() if deg == 0]
    visited = 0
    while queue:
        tid = queue.pop()
        visited += 1
        for nxt in dependents[tid]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    if visited == len(backlog.tasks):
        return []
    return sorted(tid for tid, deg in indegree.items() if deg > 0)


def _trigger_declaration_errors(backlog: Backlog) -> list[str]:
    """acceptance의 미래 트리거가 depends_on·requires_gates로 집행되는지 (HARN-72).

    `dep_declaration`(notes의 선행 축)과 짝을 이루는 acceptance 축이다. 지연 import인 이유는
    `store`가 최상단에서 형제 모듈을 끌어오지 않는 기존 구성을 유지하기 위함이며,
    `dep_declaration`이 별도 subcommand로 사는 것과 달리 이쪽은 `validate_backlog`에 들어와
    **`add`와 `validate` 양쪽이 한 번에 집행**된다(별도 CI 스텝을 늘리지 않는다).
    """
    from trigger_declaration import find_untriggered_tracking_tasks

    if not backlog.tasks:
        return []  # 빈 백로그는 상위 스키마 검사가 이미 잡는다 — 여기서 중복 실패시키지 않는다
    return [f.render() for f in find_untriggered_tracking_tasks(backlog.tasks)]


def validate_backlog(backlog: Backlog, schema_errors: list[str] | None = None) -> list[str]:
    """전체 무결성 검증 — 위반 목록 반환 (빈 리스트 = green)."""
    errors: list[str] = list(schema_errors or [])

    for track in backlog.tracks.values():
        errors.extend(track.validate())
        if track.entry_gate and track.entry_gate not in backlog.gates:
            errors.append(f"{track.id}: entry_gate '{track.entry_gate}' 가 gates.yaml에 없음")
    for gate in backlog.gates.values():
        errors.extend(gate.validate())

    sessions_in_progress: dict[str, list[str]] = {}
    for task in backlog.tasks.values():
        errors.extend(task.validate())
        if task.track not in backlog.tracks:
            errors.append(f"{task.id}: track '{task.track}' 미정의")
        if task.stage not in backlog.stage_order:
            errors.append(f"{task.id}: stage '{task.stage}' 가 stage_order에 없음")
        for dep in task.depends_on:
            if dep not in backlog.tasks:
                errors.append(f"{task.id}: depends_on '{dep}' 미존재")
            elif backlog.stage_index(backlog.tasks[dep].stage) > backlog.stage_index(task.stage):
                errors.append(
                    f"{task.id}({task.stage}): 후행 스테이지 태스크 '{dep}'"
                    f"({backlog.tasks[dep].stage})에 의존 — 로드맵 순서 위반"
                )
        for gid in task.requires_gates:
            if gid not in backlog.gates:
                errors.append(f"{task.id}: requires_gates '{gid}' 미존재")
        if task.status == "in_progress" and task.session:
            sessions_in_progress.setdefault(task.session, []).append(task.id)

    for session, ids in sessions_in_progress.items():
        if len(ids) > 1:
            errors.append(
                f"세션 '{session}' 이 {len(ids)}개 태스크를 동시 claim: {ids} (1세션=1태스크)"
            )

    cycle = detect_cycle(backlog)
    if cycle:
        errors.append(f"depends_on 순환 참조 검출: {cycle}")

    # HARN-72 — 산문에만 적힌 미래 트리거를 대장이 집행하게 한다
    # (selector는 acceptance를 읽지 않는다 — depends_on·requires_gates만 본다)
    errors.extend(_trigger_declaration_errors(backlog))

    errors.extend(_id_number_collisions(backlog.tasks.keys()))
    errors.extend(_eos_priority_grandfather_errors(backlog))

    return errors


# ── EOS 등급 그랜드파더 만료 (HARN-55) ───────────────────────────────────────
#
# 등급 필드(`eos_priority`)를 도입한 시점에 기존 태스크는 전부 null이다. 그것을 즉시
# 위반으로 만들면 대장 전체가 red가 되고, 영원히 허용하면 "만료 없는 유예"가 된다.
# 그래서 만료를 **날짜가 아니라 기계**에 건다 — 관여도 트리아지 게이트가 clear되는
# 순간(= 151건을 무엇으로 분류할지 사람이 정한 순간) 미지정이 위반이 된다.
# 선례: import-linter의 `unmatched_ignore_imports_alerting`(빚을 갚으면 CI가 줄을 지우라고
# 말한다)·EOS-67 baseline. 유예가 조용히 눌러앉을 수 없는 형태여야 한다.
#
# 종결(done·cancelled) 태스크는 세지 않는다 — 끝난 일에 등급을 소급하는 것은 분류가
# 아니라 장부 청소이고, 그 청소를 강제하면 만료가 실제 목적(12월 범위 확정)을 잃는다.
def _eos_priority_grandfather_errors(backlog: Backlog) -> list[str]:
    gate = backlog.gates.get(EOS_PRIORITY_BACKFILL_GATE)
    if gate is None or gate.status not in ("cleared", "waived"):
        return []  # 유예 유효 구간 — 아직 분류 근거(트리아지)가 없다
    missing = sorted(
        t.id
        for t in backlog.tasks.values()
        if t.eos_priority is None and t.status not in TERMINAL_STATUSES
    )
    if not missing:
        return []
    # 태스크 수만큼 오류를 쏟으면 판정이 아니라 소음이 된다 — 1건으로 묶고 처방을 붙인다.
    head = ", ".join(missing[:5])
    more = f" 외 {len(missing) - 5}건" if len(missing) > 5 else ""
    return [
        f"eos_priority 미지정 {len(missing)}건 — 그랜드파더가 만료됐다: 게이트 "
        f"'{EOS_PRIORITY_BACKFILL_GATE}'가 {gate.status}이므로 분류를 미룰 근거가 없다. "
        f"대상 예: {head}{more}. "
        "처방: python3 scripts/harness/backlog.py amend <id> --eos-priority P0|P1|P2|P3 "
        "--reason '<분류 근거>' (대장 손편집 금지)"
    ]


# ── 태스크 ID 번호 충돌 (HARN-10) ────────────────────────────────────────────
#
# ID는 `<PREFIX>-<번호>-<슬러그>` 규약이다. full-ID는 슬러그 덕에 유일해도 **번호가
# 겹치면** 사람·문서·커밋의 "OPS-15" 참조가 어느 태스크인지 결정 불가가 된다(CLI는
# full-ID를 받으므로 기계는 멀쩡 — 그래서 조용히 자란다).
#
# 실측 2회(2026-07-29): ARCH-13(둘 다 done·머지 완료), OPS-15(병렬 인플라이트). 두 사고
# 모두 **병렬 세션이 서로의 브랜치를 못 봐서** 났다 — 로컬 백로그만 보는 검사로는 애초에
# 예방할 수 없다. 그래서 예방의 본체는 `add` 시점의 *원격 claim 대장* 조회이고(backlog.py),
# 이 함수는 머지 후 잔존을 막는 2선 방어다.
# ⚠ **이 표에는 CLI 쓰기 경로가 없다 (HARN-100 실측 2026-09-12)** — `scripts/` 전체에서
# 이 상수를 참조하는 곳은 이 파일뿐이고, 등재하려면 이 소스를 직접 고치는 수밖에 없다.
# "대장 손편집 금지" 원칙과 어긋나 보이지만 의도적이다: 그랜드파더는 *번호 충돌을 영구히
# 면제*하는 결정이라 코드 리뷰를 반드시 거쳐야 하고, CLI로 열면 리뷰 없이 게이트를 끄는
# 길이 생긴다. 대신 **개명이 가능한 경우에는 이 표를 쓰지 않는다** — `backlog.py rename`
# 이 그 경로다(HARN-100). 이 표는 양쪽이 이미 머지돼 개명이 불가능할 때만 쓴다.
_GRANDFATHERED_ID_NUMBERS: dict[str, str] = {
    # 이미 main에 머지된 과거 충돌 — 개명하면 MEMORY·커밋·PR의 기존 참조가 끊긴다.
    "ARCH-13": (
        "기존 충돌(2026-07-18 visualization-harness-tracking · 07-25 "
        "concept-atom-granularity-merge) — 둘 다 done·머지 완료. 개명 시 기존 참조 파손."
    ),
    # HARN-10 착수 시점에 두 브랜치에서 인플라이트 — 이 가드가 먼저 머지돼도
    # 그 브랜치들의 머지를 깨지 않게 미리 등재한다(타 세션 볼모 금지).
    "OPS-15": (
        "기존 충돌(2026-07-29 repo-root-lint-config · wh1-caplog-order-flake) — "
        "HARN-10 착수 시점에 타 세션 2곳에서 인플라이트였다. 사후 개명은 타 세션 볼모."
    ),
}

# 접두는 영숫자 혼합을 허용한다 — 이 저장소 ID의 다수파가 스테이지형(`S2-04`·`S4-07`)이라
# `[A-Za-z]+`로 잡으면 정작 가장 많은 축을 통째로 못 본다(HARN-10 구현 중 실측).
#
# 캡처 그룹 뒤는 `(?:-|$)` — 슬러그가 이어지거나(`-`) 문자열이 거기서 끝나야(`$`) 매치한다.
# `models.TASK_ID_RE`(`^[A-Z][A-Z0-9]{0,7}-\d{2}(-[a-z0-9]+(-[a-z0-9]+)*)?$`)는 슬러그가
# **옵션**이라 `HARN-20`처럼 슬러그 없는 ID도 유효한데, 구 정규식(`...-\d+)-`)은 캡처 그룹
# 뒤에 반드시 `-`가 와야 매치해서 슬러그 없는 ID를 전부 놓쳤다(HARN-21 결함① — 그 결과
# `_taken_id_numbers`·`_id_number_collisions`가 슬러그 없는 ID의 번호를 점유 목록에서
# 누락시켜 1선(add)·2선(validate) 번호 충돌 검사를 양쪽 다 우회할 수 있었다).
_ID_NUMBER_RE = re.compile(r"^([A-Za-z][A-Za-z0-9]*-\d+)(?:-|$)")


def id_number_of(task_id: str) -> str | None:
    """`<PREFIX>-<번호>` 부분. 규약을 벗어난 ID면 None(검사 대상 아님)."""
    match = _ID_NUMBER_RE.match(task_id)
    return match.group(1) if match else None


def _id_number_collisions(task_ids: object) -> list[str]:
    """같은 `<PREFIX>-<번호>`를 쓰는 태스크가 2건 이상이면 위반(grandfather 제외)."""
    groups: dict[str, list[str]] = {}
    for task_id in task_ids:  # type: ignore[union-attr]
        number = id_number_of(str(task_id))
        if number:
            groups.setdefault(number, []).append(str(task_id))
    errors: list[str] = []
    for number, ids in sorted(groups.items()):
        if len(ids) < 2 or number in _GRANDFATHERED_ID_NUMBERS:
            continue
        errors.append(
            f"태스크 ID 번호 충돌 '{number}': {sorted(ids)} — 사람·문서·커밋의 "
            f"'{number}' 참조가 결정 불가가 된다. 미머지인 쪽을 개명하라: "
            f"`backlog.py rename <구 full-id> <새 full-id> --reason ...`(HARN-100). "
            "양쪽이 이미 머지돼 개명이 불가능할 때만 "
            "store._GRANDFATHERED_ID_NUMBERS에 사유와 함께 등재한다."
        )
    return errors
