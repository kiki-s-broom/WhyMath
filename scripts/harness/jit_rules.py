"""적시 규칙 주입 — 편집하는 경로에서 실제로 났던 사고·규칙만 보여준다 (HARN-121 ③).

왜 이 모듈이 있는가
-------------------
`CLAUDE.md`는 63,017자이고 세션마다 통째로 읽힌다. 규칙 85건 중 지금 편집하는 파일과
관계있는 것은 대개 0~3건인데, 나머지를 함께 읽는 비용이 세션 고정비의 큰 몫이다
(`docs/reviews/recurring_failure_taxonomy_2026-09-20.md` §6 E1).

그래서 반대로 한다 — **편집 순간에, 그 경로에서 났던 것만** stderr로 최대 5줄 준다.
관련 항목이 없으면 **아무 말도 하지 않는다**. 늘 떠드는 알림은 곧 습관화되어 소음이
되고(이 저장소의 `policy_warn` 89% 선례), 소음이 된 경고는 보호가 아니다.

경로는 어디서 오는가 (정직한 한계)
----------------------------------
사고 대장에는 경로 필드가 없다. 실재하는 연결은 **사고 → 상환 태스크 → 그 태스크의
`paths`** 이고, 실측 262/676건(39%)이 이 경로로 해소된다. 규칙은 `enforced_by`가
경로이거나 태스크 ID이므로 같은 방식으로 해소된다(17/85건).

나머지 414건은 경로를 모른다 — **모르는 것을 아무 경로에나 붙이지 않는다**. 그러면
모든 편집에 5줄이 뜨고 위에 적은 소음이 된다.

왜 인덱스를 미리 만드는가
------------------------
훅은 매 Edit/Write마다 돈다. 대장 3종을 그때 읽으면 **2.3초**가 든다(실측 — 태스크
757개 YAML 파싱이 병목). 사람이 2초를 기다리는 훅은 곧 꺼진다. 그래서 빌드 타임에
`backlog/jit_index.json`으로 접어 두고 훅은 그것만 읽는다. 인덱스가 대장과 어긋나는
것은 `jit check`가 CI에서 막는다(문서 렌더와 같은 패턴).

의존성: 표준 라이브러리만.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pathscope

INDEX_NAME = "jit_index.json"
MAX_NOTES = 5  # 주입 상한 — 보고서 §6 E1

_TASK_REF_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,7}-\d{2,3})\b")

# 피해 등급의 주목도 — 같은 경로에 여러 건이 걸릴 때 무엇을 먼저 보여줄지.
# `none`이 낮은 이유: 피해 0은 대개 "운이 좋았다"이지만, 지면이 5줄뿐이라면 실제로
# 시간을 태운 것부터 보여주는 편이 낫다.
_DAMAGE_WEIGHT = {
    "data_loss": 6,
    "false_pass": 5,
    "latent_days": 4,
    "discarded_work": 3,
    "ci_red": 2,
    "wasted_round": 1,
    "none": 0,
}


@dataclass
class Note:
    """주입 후보 1건 — 경로 범위와 한 줄 문구."""

    kind: str  # "rule" | "incident"
    ref: str  # 규칙 id 또는 사고 날짜
    paths: list[str] = field(default_factory=list)
    text: str = ""
    weight: int = 0  # 클수록 먼저

    def line(self) -> str:
        marker = "규칙" if self.kind == "rule" else "사고"
        return f"[{marker} {self.ref}] {self.text}"


def _task_paths(backlog: object) -> dict[str, list[str]]:
    """태스크 번호 프리픽스(`HARN-118`) → 선언 paths 합집합."""
    result: dict[str, list[str]] = {}
    tasks = getattr(backlog, "tasks", {}) or {}
    for task_id, task in tasks.items():
        match = re.match(r"^([A-Z][A-Z0-9]*-\d+)", task_id)
        if not match:
            continue
        result.setdefault(match.group(1), []).extend(getattr(task, "paths", []) or [])
    return result


def _paths_from_ref(ref: str, by_task: dict[str, list[str]]) -> list[str]:
    """집행 참조 문자열 → 경로 목록. 경로면 그대로, 태스크 ID면 그 태스크의 paths."""
    ref = ref.strip()
    if not ref:
        return []
    if "/" in ref:
        return [ref.split("::", 1)[0]]
    return list(by_task.get(ref, []))


def build_notes(backlog: object, rules: list, incidents: list) -> list[Note]:
    """대장 3종 → 주입 후보 목록. 순수 함수 — I/O 0.

    경로를 모르는 항목은 **버린다**(빈 paths는 '모든 경로'가 아니다).
    """
    by_task = _task_paths(backlog)
    notes: list[Note] = []

    for rule in rules:
        paths: list[str] = []
        for ref in getattr(rule, "enforced_by", []) or []:
            paths.extend(_paths_from_ref(ref, by_task))
        paths = sorted(set(paths))
        if not paths:
            continue
        notes.append(
            Note(
                kind="rule",
                ref=rule.id,
                paths=paths,
                text=rule.title,
                # 규칙은 일반화된 교훈이라 개별 사고보다 먼저 보여준다.
                weight=100,
            )
        )

    for incident in incidents:
        paths = []
        for num in _TASK_REF_RE.findall(getattr(incident, "fix_ref", "") or ""):
            paths.extend(by_task.get(num, []))
        paths = sorted(set(paths))
        if not paths:
            continue
        notes.append(
            Note(
                kind="incident",
                ref=incident.date,
                paths=paths,
                text=incident.title,
                weight=_DAMAGE_WEIGHT.get(incident.damage_class, 0),
            )
        )
    return notes


def index_path(root: Path) -> Path:
    return root / "backlog" / INDEX_NAME


def dump_index(notes: list[Note]) -> str:
    """결정적 직렬화 — 같은 대장이면 같은 바이트(diff 안정·`check`가 성립하려면 필수)."""
    ordered = list(notes)
    payload = {"version": 1, "max_notes": MAX_NOTES, "notes": [asdict(n) for n in ordered]}
    return json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=False) + "\n"


def load_index(root: Path) -> list[Note]:
    """인덱스 읽기 — 없거나 깨졌으면 빈 목록(훅은 절대 개발을 볼모로 잡지 않는다)."""
    path = index_path(root)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw = payload["notes"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return []
    notes: list[Note] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            notes.append(Note(**item))
        except TypeError:
            continue
    return notes


def notes_for_path(notes: list[Note], rel_path: str, *, limit: int = MAX_NOTES) -> list[Note]:
    """이 경로에 걸리는 주입 후보 — 무게 순 상위 `limit`건. 0건이면 빈 목록(침묵)."""
    if not rel_path:
        return []
    matched = [n for n in notes if n.paths and pathscope.path_in_scope(rel_path, n.paths)]
    matched.sort(key=lambda n: (-n.weight, n.kind, n.ref))
    return matched[:limit]


def render_injection(matched: list[Note], rel_path: str) -> str:
    """stderr에 낼 문자열. 빈 목록이면 빈 문자열 — 호출측이 침묵을 결정할 수 있게."""
    if not matched:
        return ""
    lines = [f"[적시 규칙] '{rel_path}' 경로에서 실제로 났던 것 {len(matched)}건:"]
    lines.extend(f"  · {note.line()}" for note in matched)
    return "\n".join(lines)
