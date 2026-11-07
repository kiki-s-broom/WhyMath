"""개념 콘텐츠 생애 상태 어휘 — PED-17 A1 (상태 4종·출처 2종·전환 경로·변경 주체 종류).

이 파일은 **어휘와 전환표의 단일 정본**이다. DB 모델(`db/models/concept_content.py`의 CHECK)과
로직(`l1/concept_content/lifecycle.py`의 전환 함수·노출 관문), 마이그레이션 테스트가 모두 여기를
읽는다. 마이그레이션 리비전은 결정성을 위해 이 값을 import하지 않고 인라인으로 박는다
(`learning_state_transition` 리비전 선례) — 둘이 갈라지지 않도록 테스트가 대조한다.

────────────────────────────────────────────────────────────────────────────
상태 4종 (2026-11-06 Kiki 확정 · 값 고정)
────────────────────────────────────────────────────────────────────────────
초안 → 검증됨 → 공개됨, 그리고 회수됨. 저장 값은 지시문의 한국어 단어 그대로다. 같은 저장소의
`concept_content.scope`가 '대학'을 저장하는 선례가 있고, B6·C·D 후속 작업이 이 값을 읽으므로
영문으로 번역하면 번역 지점이 6곳으로 늘어난다.

**기존 `review_status`와 다른 축이다.** `review_status`(ai_estimated·reviewed·rejected)는 *사람
검수 라벨*이고, `lifecycle_status`는 *학생 공개 생애*다. 학생에게 나가려면 생애가 '공개됨'이어야
하고,
출처가 '사람 검수'인 행은 추가로 `review_status == reviewed`도 유지돼야 한다(`is_student_visible`).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class ConceptLifecycleState(StrEnum):
    """개념 상태 — 학생 공개 생애. 값은 4개로 고정이다."""

    DRAFT = "초안"
    VERIFIED = "검증됨"
    PUBLISHED = "공개됨"
    WITHDRAWN = "회수됨"


class ConceptContentOrigin(StrEnum):
    """개념 콘텐츠 출처 — 공개 근거가 사람 검수인지 AI 생성 후 자동 검증인지."""

    HUMAN_REVIEWED = "사람 검수"
    AI_GENERATED = "AI 생성"


class ChangedByKind(StrEnum):
    """상태를 바꾼 주체의 종류 — 규칙 이름, 에이전트 이름, Kiki 중 하나."""

    RULE = "rule"
    AGENT = "agent"
    KIKI = "kiki"


class ConceptTransitionVia(StrEnum):
    """전환 경로 — 어느 작업·기능이 상태를 바꾸는가. 전환표가 경로별로 허용을 가른다."""

    B6_PUBLIC_GATE = "B6 공개 관문"
    D4_AI_CANARY = "D4 AI 카나리"
    D5_STAGED_ROLLOUT = "D5 단계적 공개"
    D2_AI_AUDIT = "D2 AI 감사"
    D6 = "D6"
    KILL_SWITCH = "킬스위치"
    RECALL = "회수 기능"
    EMERGENCY_STOP = "긴급 정지"
    REGENERATE = "재생성"
    # 마이그레이션이 기존 행에 상태를 처음 매길 때만 쓰는 값이다. 전환표(ALLOWED_TRANSITIONS)의 어느
    # 항목에도 없으므로 `transition_concept_state`는 이 경로를 항상 거부한다(전환이 아니라 최초
    # 부여).
    INITIAL_ASSIGNMENT = "최초 부여"


_S = ConceptLifecycleState
_V = ConceptTransitionVia

# 허용 전환 5가지와 각 전환을 호출할 수 있는 경로. 이 표에 없는 (이전, 새) 쌍은 전부 거부한다.
#
# 초안→검증됨      : B6 통과 시에만
# 검증됨→공개됨    : D4 또는 D5 경로에서만
# 공개됨→회수됨    : 킬스위치, 회수 기능, 긴급 정지
# 검증됨→회수됨    : D2·D4·D6에서 오류 발견
# 회수됨→초안      : 다시 생성해 재검증
ALLOWED_TRANSITIONS: Final[
    dict[tuple[ConceptLifecycleState, ConceptLifecycleState], frozenset[ConceptTransitionVia]]
] = {
    (_S.DRAFT, _S.VERIFIED): frozenset({_V.B6_PUBLIC_GATE}),
    (_S.VERIFIED, _S.PUBLISHED): frozenset({_V.D4_AI_CANARY, _V.D5_STAGED_ROLLOUT}),
    (_S.PUBLISHED, _S.WITHDRAWN): frozenset({_V.KILL_SWITCH, _V.RECALL, _V.EMERGENCY_STOP}),
    (_S.VERIFIED, _S.WITHDRAWN): frozenset({_V.D2_AI_AUDIT, _V.D4_AI_CANARY, _V.D6}),
    (_S.WITHDRAWN, _S.DRAFT): frozenset({_V.REGENERATE}),
}

# 긴급 정지는 Kiki만 발동할 수 있다(2026-11-06 Kiki 확정). AI 에이전트·규칙이 이 경로를 쓰면
# 거부한다.
# 심각 오류 신고 1건의 자동 회수는 긴급 정지가 아니라 킬스위치 경로다.
KIKI_ONLY_VIA: Final[frozenset[ConceptTransitionVia]] = frozenset({_V.EMERGENCY_STOP})

__all__ = [
    "ALLOWED_TRANSITIONS",
    "KIKI_ONLY_VIA",
    "ChangedByKind",
    "ConceptContentOrigin",
    "ConceptLifecycleState",
    "ConceptTransitionVia",
]
