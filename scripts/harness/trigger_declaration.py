"""acceptance에 *선언된* 미래 트리거가 `depends_on`/`requires_gates`로 *집행되는지* 대조한다.

**왜 필요한가 (사고 경위 2026-09-06 · 같은 세션 2회 반복)**
--------------------------------------------------------
추적·재확인 태스크는 "**나중에** X가 생기면 그때 다시 측정한다"를 acceptance에 적는다.
그런데 `depends_on`·`requires_gates`가 둘 다 비어 있으면 `selector.py`는 그 태스크를
**즉시 착수 후보로 계산한다** — selector는 acceptance 산문을 읽지 않는다. 그러면 어떤
세션이 지금 그것을 집어 "조건 셋 다 False"를 확인하고 종결해 버릴 수 있고, 지키려던
**미래 전이는 미추적으로 남는다**. 태스크는 done이 되었는데 감시는 사라진다.

실측 2건(둘 다 Codex 리뷰가 지적):
  · `ARCH-40`(ARCH-38 판정 재확인) — PR #997. 게이트 부착으로 착수 후보 124→123.
  · `ARCH-41`(필수층 미사용 추적) — PR #999. **같은 세션에서 같은 지적을 다시** 받음.
    후보 123→122.

1회성 실수가 아니라 등재 절차에 집행 장치가 없다는 신호다. CLAUDE.md **"선행 조건을
산문에만 적고 대장에 집행하지 않기 금지"**(2026-09-01)가 `notes`의 *선행* 축으로만
집행돼 있고(`dep_declaration`), **acceptance의 *미래 트리거* 축**에는 공백이었다.

**`dep_declaration`(HARN-52)과의 구분 — 왜 확장이 아니라 별도 모듈인가**
------------------------------------------------------------------------
`HARN-72` acceptance ③이 "확장으로 될 일이면 audit-deps를 확장하라"고 요구했다. 확장하지
않은 이유는 셋 다 다르기 때문이다:

| 축 | `dep_declaration` (HARN-52) | 이 모듈 (HARN-72) |
|---|---|---|
| 스캔 대상 | `notes` (acceptance는 오탐 4/12로 제외) | `acceptance` |
| 찾는 신호 | 순서 어구 근처의 **타 태스크 ID** | 한 문장 안의 **미래조건+재측정 동사** |
| 정정 경로 | `amend --depends <task-id>` | `amend --gate <gate-id>` |

특히 세 번째가 결정적이다. 기다릴 대상이 *태스크*가 아니라 **코드 상태**라 `depends_on`으로는
표현할 수 없다 — "필수층에 첫 호출자가 생기면"은 어떤 태스크의 done으로도
표현되지 않는다. 그래서 게이트(사람 재확인 지점)가 정답이고, 그 점에서 두 모듈은 같은
"산문↔집행" 축이되 **집행 필드가 다르다**.

**설계 3원칙** (`dep_declaration` 선례를 그대로 답습)
------------------------------------------------
1. **탐지는 보수적으로 — 한 문장 안의 동시 등장만 본다.**
   `재확인`·`재측정` 단독은 잡지 않는다. 실측(2026-09-06 전수): 단독 어구로 잡으면
   미완료 태스크 **29건**이 걸리는데 표본 검사 결과 대부분이 오탐이었다 — "…가 여전히
   유효함을 **재확인**하고 회귀 테스트로 동결한다"처럼 *이 태스크 안의 한 단계*로 쓰인
   경우다. 미래조건 어구와 **같은 문장**에 있을 때만 대기 선언으로 본다.
   오탐이 잦은 게이트는 습관화되어 무력해진다(CLAUDE.md).
2. **그랜드파더가 필요 없다 — 기존 위반 0건.**
   이 검출기를 저장소 전수(미완료 태스크)에 돌린 결과 **발화 0건**이다. 즉 만료 없는
   유예를 둘 이유 자체가 생기지 않았다. 면제 목록을 비워 두는 대신 *비어 있다는 사실과
   그 근거*를 여기 적는다(있는 척 금지의 반대 방향 — 없는 척도 하지 않는다).
3. **면제는 사유와 함께 태스크에 남는다.**
   오탐 시 탈출구는 `backlog.py add --no-trigger <사유>`이며, 그것은 태스크 `notes`에
   `[트리거 면제] <사유>` 마커를 남긴다. 면제가 코드 상수가 아니라 **태스크 자신**에
   붙으므로 나중에 읽는 사람이 왜 면제됐는지 같은 자리에서 본다(무사유 예외 금지).

**이 모듈이 하지 않는 것**: 게이트를 자동으로 만들지 않는다. 어떤 재확인 지점이 옳은지는
사람 판단이며, 정정 경로는 `backlog.py gates add` + `backlog.py amend <id> --gate <gate-id>`다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "ACTION_PHRASES",
    "SELF_REARM_PHRASES",
    "EXEMPTION_MARKER",
    "FUTURE_PHRASES",
    "Finding",
    "find_untriggered_tracking_tasks",
]

# 미래에 *상태가 바뀌는* 것을 가리키는 어구. "~하면"류 조건절 중 **전이**를 뜻하는 것만.
FUTURE_PHRASES: tuple[str, ...] = (
    "생기면",
    "생기는 시점",
    "등장하면",
    "착지하면",
    "전환되면",
    "나오면",
    "성립하면",
    "발동하면",
)

# 그 전이 이후에 *다시* 무언가를 하겠다는 동사. 재측정·재판정 계열만.
ACTION_PHRASES: tuple[str, ...] = ("재측정", "재판정", "재확인", "재생성")

# **규칙 2** — 자기 재생성 선언. 조건 어구 없이도 대기 태스크임을 확정하는 신호다.
#
# 왜 이것만 단독 신호인가: 이 저장소는 감시 태스크가 스스로를 다시 등재하는 규약을 이미
# 가지고 있다(`/drive` 안전장치: *"ARCH-* 감사 태스크 완료 시 다음 회차를 `backlog.py add`로
# 재생성 — 감시 끊김 방지"*). 즉 "이 태스크를 재생성한다"는 **한 번 실행하고 끝나는 태스크가
# 아니라 반복 감시 좌석**이라는 선언이며, 그런 좌석이 트리거 없이 즉시 착수 가능하면 정확히
# 이 게이트가 막으려는 상태다.
#
# 규칙 1(미래조건+재측정 동시 등장)만으로는 `ARCH-40`을 놓친다 — 그쪽은 트리거를 조건절이
# 아니라 **진리값 목록 평가**("셋 다 False면 … 재생성한다")로 적었기 때문이다(2026-09-06 실측:
# 규칙 1 단독 검출률 1/2). 그 문장의 구문(`False면`)을 어구 목록에 넣는 안은 **한 건에 대한
# 과적합**이라 버렸고, 대신 저장소가 이미 쓰는 *개념*을 신호로 골랐다.
#
# **표본 한계(있는 척 금지)**: 이 어구는 2026-09-06 현재 저장소 전수에서 `ARCH-40` **1건**에만
# 등장한다. 즉 이 규칙의 근거는 표본 1이며, 오탐률은 아직 측정된 적이 없다. 넓히거나 좁히는
# 판단은 실제 발화 사례가 쌓인 뒤에 한다.
SELF_REARM_PHRASES: tuple[str, ...] = (
    "이 태스크를 재생성",
    "태스크를 재생성",
    "재생성해 감시",
)

# 오탐 면제 마커 — `add --no-trigger <사유>`가 notes에 남긴다.
EXEMPTION_MARKER = "[트리거 면제]"

# 스캔 대상에서 빼는 상태 — 끝났거나 취소됐거나 이미 막힌 태스크는 착수 후보가 아니다.
_SCAN_SKIP_STATUSES = frozenset({"done", "cancelled", "blocked"})

# 문장 분리 — 한국어 백로그 산문은 마침표보다 `·`·줄바꿈으로 항목을 나누는 일이 잦다.
_SENTENCE_SPLIT = re.compile(r"(?<=[.。!?])\s+|\n+|\s+·\s+|\s+—\s+")


@dataclass(frozen=True)
class Finding:
    """트리거를 선언했으나 집행하지 않은 태스크 1건."""

    task_id: str
    sentence: str
    future_phrase: str
    action_phrase: str

    def render(self) -> str:
        excerpt = self.sentence if len(self.sentence) <= 120 else self.sentence[:117] + "…"
        return (
            f"{self.task_id}: acceptance가 미래 트리거를 선언했으나 "
            f"depends_on·requires_gates가 둘 다 비어 있다 "
            f"(어구: '{self.future_phrase}' + '{self.action_phrase}')\n"
            f"      └ {excerpt}"
        )


def _field(task: object, name: str, default: object = None) -> object:
    """모델 객체·dict 어느 쪽에서든 필드를 읽는다.

    루프 안에서 `lambda`로 접근자를 만들면 루프 변수를 늦게 바인딩해(ruff B023) 전 항목이
    마지막 태스크를 읽는 버그가 된다. 지금 코드는 같은 반복 안에서만 써서 우연히 맞지만,
    *우연히 맞는 코드*를 남기지 않는다 — 모듈 함수로 뽑아 그 함정을 없앤다.
    """
    if isinstance(task, dict):
        return task.get(name, default)
    return getattr(task, name, default)


def _declares_future_trigger(acceptance: list[str]) -> tuple[str, str, str] | None:
    """한 문장 안에 (미래조건, 재측정동사)가 함께 있으면 그 문장을 돌려준다."""
    for item in acceptance:
        for sentence in _SENTENCE_SPLIT.split(item):
            future = next((p for p in FUTURE_PHRASES if p in sentence), None)
            if future is None:
                continue
            action = next((p for p in ACTION_PHRASES if p in sentence), None)
            if action is not None:
                return sentence.strip(), future, action
    return None


def _declares_self_rearm(acceptance: list[str]) -> tuple[str, str, str] | None:
    """규칙 2 — "이 태스크를 재생성한다"(자기 재생성)를 담은 문장을 돌려준다."""
    for item in acceptance:
        for sentence in _SENTENCE_SPLIT.split(item):
            phrase = next((p for p in SELF_REARM_PHRASES if p in sentence), None)
            if phrase is not None:
                return sentence.strip(), "자기 재생성", phrase
    return None


def find_untriggered_tracking_tasks(tasks: dict) -> list[Finding]:
    """미래 트리거를 선언했는데 `depends_on`·`requires_gates`가 둘 다 빈 태스크.

    `tasks`는 `{id: Task}` 매핑(모델 객체) 또는 `{id: dict}` 어느 쪽이든 받는다 —
    테스트가 합성 dict로 뮤테이션을 주입할 수 있어야 하기 때문이다.

    **스캔 0건은 실패**(CLAUDE.md 2026-09-01 ④): 태스크를 하나도 못 받으면 "위반 없음"이
    아니라 호출측이 깨진 것이다. 위반이 0인 것과 *대상이* 0인 것은 다르다.
    """
    if not tasks:
        raise ValueError(
            "트리거 선언 검사: 스캔 대상 태스크가 0건이다 — 위반 없음이 아니라 "
            "백로그 적재가 깨진 것이다(공허한 통과 금지)."
        )

    findings: list[Finding] = []
    for task_id, task in sorted(tasks.items()):
        if _field(task, "status", "todo") in _SCAN_SKIP_STATUSES:
            continue
        if EXEMPTION_MARKER in (_field(task, "notes", "") or ""):
            continue
        if (_field(task, "depends_on") or []) or (_field(task, "requires_gates") or []):
            continue  # 트리거가 집행돼 있다 — 이 게이트의 관심사가 아니다
        acceptance = list(_field(task, "acceptance") or [])
        declared = _declares_future_trigger(acceptance)
        if declared is None:
            declared = _declares_self_rearm(acceptance)
        if declared is None:
            continue
        sentence, future, action = declared
        findings.append(
            Finding(task_id=task_id, sentence=sentence, future_phrase=future, action_phrase=action)
        )
    return findings
