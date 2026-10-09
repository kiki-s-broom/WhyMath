"""CMS 접근 정책 — 역할이 *무엇을 할 수 있는가*의 단일 진실 원천 (P3-12).

왜 역할이 아니라 **권한(capability)** 에 대해 묻는가
------------------------------------------------
`Role`은 의도적으로 서열이 없는 순수 `Enum`이다(`schema/enums.py` docstring — 7단 선형 서열
미도입). 그래서 "편집자 < 검수자 < 배포자" 같은 비교를 코드에 쓸 수 없고, 써서도 안 된다. 대신
CMS의 모든 쓰기 라우트는 *역할 이름*이 아니라 **이 모듈이 정한 권한**을 검사한다:

  - `VIEW`    : 조회 (목록·상세·이력)
  - `EDIT`    : 편집 (초안 작성·제자리 편집·검토 제출)
  - `REVIEW`  : 검수 (검토 통과·QA 승인·반려·검수 표시)
  - `PUBLISH` : 배포 (발행·폐기·은퇴·롤백·삭제)

역할 → 권한 매핑은 아래 `ROLE_CAPABILITIES` **한 곳**에만 있다. 메뉴 가시성(`required_roles`)도
이 매핑에서 *파생*한다(`roles_with`) — 두 곳에 같은 값을 적어 두고 나중에 대조하는 방식은 그
대조가 곧 드리프트의 자리가 된다(`admin_module_registry` 모듈 docstring과 같은 원리).

fail-closed
-----------
- 매핑에 없는 역할은 권한이 **0개**다(`capabilities_of`가 빈 집합).
- 매핑에 없는 전이 이름은 권한을 **요구할 수 없다** → `required_capability`가 `None`을 돌려주고
  호출자는 이를 거부로 읽는다. "모른다 ≠ 허용".
- 전이표(`schema/version_lifecycle.LIFECYCLE_TRANSITIONS`)에 직접 호출 가능한 전이가 새로 생기면
  `TRANSITION_CAPABILITY`에 권한을 달아야 한다 — `tests/backend/schema/test_cms_access.py`가 둘의
  일치를 동결한다(권한 없는 전이가 조용히 "아무나 가능"이 되는 것을 막는다).

`CONTENT_ADMIN`은 4개 권한을 전부 가진다. 상위 역할이 아니라 **권한 집합이 겹치는 겸임 역할**이다
(사용자 1명이 역할 컬럼 1개만 가지므로, 소규모 팀이 한 계정으로 전 과정을 돌리는 유일한 수단).

이 모듈은 선언(상수)과 조회 함수뿐이다 — DB·HTTP·시계 의존 0, 수학 로직 0.
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType

from whymath_backend.schema.enums import Role
from whymath_backend.schema.version_header import TransitionAction


class CmsCapability(StrEnum):
    """CMS 권한 4종 — 값은 감사·응답에 그대로 실린다."""

    VIEW = "view"
    EDIT = "edit"
    REVIEW = "review"
    PUBLISH = "publish"


_V = CmsCapability.VIEW
_E = CmsCapability.EDIT
_R = CmsCapability.REVIEW
_P = CmsCapability.PUBLISH

#: 역할 → 권한. `STUDENT`는 의도적으로 **없다**(키 부재 = 권한 0개). 읽기 전용 매핑이라 호출 측이
#: 요청 처리 중에 권한을 바꿀 수 없다.
ROLE_CAPABILITIES: MappingProxyType[Role, frozenset[CmsCapability]] = MappingProxyType(
    {
        Role.CONTENT_EDITOR: frozenset({_V, _E}),
        Role.CONTENT_REVIEWER: frozenset({_V, _R}),
        Role.CONTENT_PUBLISHER: frozenset({_V, _P}),
        Role.CONTENT_ADMIN: frozenset({_V, _E, _R, _P}),
    }
)

#: 개념 버전 전이(직접 호출 가능한 8종) → 요구 권한. 복합 전용(supersede·rollback·restore)은
#: 단독 전이로 부를 수 없으므로 여기에 없다 — 롤백은 별도 연산이며 `PUBLISH`를 요구한다.
TRANSITION_CAPABILITY: MappingProxyType[TransitionAction, CmsCapability] = MappingProxyType(
    {
        TransitionAction.SUBMIT: _E,
        TransitionAction.REQUEST_CHANGES: _R,
        TransitionAction.PASS_REVIEW: _R,
        TransitionAction.FAIL_QA: _R,
        TransitionAction.APPROVE: _R,
        TransitionAction.PUBLISH: _P,
        TransitionAction.DEPRECATE: _P,
        TransitionAction.RETIRE: _P,
    }
)

#: 롤백 복합 연산이 요구하는 권한.
ROLLBACK_CAPABILITY: CmsCapability = _P


def capabilities_of(role: Role) -> frozenset[CmsCapability]:
    """`role`이 가진 권한 — 매핑에 없는 역할은 **빈 집합**(fail-closed)."""
    return ROLE_CAPABILITIES.get(role, frozenset())


def has_capability(role: Role, capability: CmsCapability) -> bool:
    """`role`이 `capability`를 가졌는가."""
    return capability in capabilities_of(role)


def roles_with(capability: CmsCapability) -> frozenset[Role]:
    """`capability`를 가진 역할 전부 — 레지스트리 `required_roles`가 여기서 파생된다."""
    return frozenset(role for role, caps in ROLE_CAPABILITIES.items() if capability in caps)


def required_capability(action: TransitionAction | str) -> CmsCapability | None:
    """전이 `action`이 요구하는 권한. 어휘에 없거나 매핑에 없으면 `None`(= 호출자는 거부)."""
    try:
        action_v = TransitionAction(action)
    except ValueError:
        return None
    return TRANSITION_CAPABILITY.get(action_v)


__all__ = [
    "CmsCapability",
    "ROLE_CAPABILITIES",
    "TRANSITION_CAPABILITY",
    "ROLLBACK_CAPABILITY",
    "capabilities_of",
    "has_capability",
    "roles_with",
    "required_capability",
]
