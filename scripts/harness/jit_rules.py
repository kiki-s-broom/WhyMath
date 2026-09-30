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

왜 인덱스 파일을 커밋하지 않는가 (HARN-130 — 종전 설계의 정정)
-----------------------------------------------------------------
처음(HARN-121 ③)에는 대장 3종을 `backlog/jit_index.json`으로 접어 커밋하고 훅은 그것만
읽었다. 근거는 "대장을 편집마다 읽으면 2.3초"였고, 어긋남은 CI `jit check`가 막았다.

그 파일이 두 가지 사고를 만들었다.
  · **머지 충돌** — 사고를 등재하는 PR은 거의 전부 이 파일도 바꿨다(main 실측: 이 파일을
    바꾼 커밋 26건 중 25건이 사고 대장도 바꿨다). 새 사고 줄은 무게·날짜 순 정렬에서 대개
    같은 자리에 끼므로, 사고를 등재한 두 PR은 이 파일에서 서로 충돌했다. 사고 대장을
    세션 샤드로 나눠도(HARN-130) 이 파일이 남으면 충돌도 남는다.
  · **재생성 망각 → CI red** — 사고를 적고 `jit build`를 안 돌리면 CI가 red였다(HARN-179).

그리고 근거였던 2.3초는 **이미 치르고 있던 비용**이었다. `check-edit`의 조율 정책 검사가
브랜치 위의 편집마다 태스크 대장을 통째로 읽는다(실측 1.98초). 대장이 메모리에 올라온 뒤
주입 후보를 계산하는 데는 규칙 1ms + 사고 13ms + 계산 4ms가 든다. 그래서 훅은 대장을 한 번
읽어 두 검사가 함께 쓰고, 주입 후보는 편집 시 계산한다(`backlog.py`의 `_build_jit_notes`).
커밋할 파생물이 없으니 충돌도, 낡음도, 재생성 명령도 없다 — 생성 인벤토리를 저장소에서
뺀 OPS-76과 같은 방향이다. `jit check`는 이제 "대장에서 계산되는가(스키마 위반·0건이면
실패)"만 본다.

의존성: 표준 라이브러리만.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pathscope

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
