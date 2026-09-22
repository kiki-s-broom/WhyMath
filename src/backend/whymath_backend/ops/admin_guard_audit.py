"""`/v1/admin/*` 라우트 가드 감사 — 메뉴와 가드가 갈라지지 않음을 기계로 본다(04 §2 원칙7).

무엇을 막는가
------------
04 §2 원칙7은 "메뉴 필터링은 **UX 편의일 뿐 보안 경계가 아니다**"라고 못박는다 — 메뉴에 안
보이는 항목도 URL을 직접 쳐서 접근을 시도할 수 있으므로 각 라우트는 자체 역할 가드를 가져야
한다. 그 가드를 깜빡한 라우트가 곧 "메뉴엔 없는데 URL로는 됨" 회귀다. 이 모듈이 그 상태를
CI에서 매번 다시 본다.

가드는 `module_registry.require_module_roles(...)`가 레지스트리에서 **파생**시키므로 역할값
불일치는 구조적으로 발생할 수 없다. 그래서 여기서 찾는 것은 값의 불일치가 아니라 **그 파생
경로를 안 쓴 라우트**다(가드 부재·미등재 모듈 id·낡은 면제).

왜 `api/`가 아니라 `ops/`에 있는가
--------------------------------
라우트를 보려면 만들어진 앱을 걸어야 하고, 그 평탄화의 유일한 구현인
`declared_unwired_audit.walk_routes`는 같은 모듈에서 `create_app`을 import한다. 감사기를
`api/`에 두면 `app.py → api.admin_module_registry → ops.declared_unwired_audit → app.py`
순환이 된다. 선언(레지스트리)은 `api/admin_module_registry.py`에, 그 선언을 *검사하는*
코드는 여기에 둔다.

`walk_routes`를 재구현하지 않는 이유는 그쪽 모듈 docstring이 적어 둔 그대로다 — FastAPI
0.140부터 `include_router()`가 하위 라우트를 `app.routes`로 평탄화하지 않고 `_IncludedRouter`
래퍼로 감싸므로, 순진하게 `app.routes`를 훑으면 **admin 라우트가 한 건도 안 잡힌다**. 그
상태에서 "위반 0"은 통과가 아니라 측정 실패다 — 그래서 아래 감사 함수는 위반 목록과 함께
**검사한 라우트 수(분모)**를 돌려준다(CLAUDE.md "스캔 0건은 실패").
"""

from __future__ import annotations

from whymath_backend.api.admin_module_registry import (
    ADMIN_PATH_PREFIX,
    GUARD_EXEMPT_PATHS,
    GUARD_MODULE_ATTR,
    has_module,
)
from whymath_backend.ops.declared_unwired_audit import walk_routes


def _guarded_module_ids(dependant: object) -> set[str]:
    """`route.dependant` 트리를 훑어 레지스트리 파생 가드의 module_id를 모은다.

    함수 *이름*이 아니라 속성 태그로 판정한다 — 이름 비교는 데코레이터·`functools` 래핑에서
    조용히 깨지고, 깨진 쪽은 "가드 없음"이 아니라 "가드 있음"으로 오판될 여지가 있다.
    """
    found: set[str] = set()
    stack: list[object] = [dependant]
    while stack:
        node = stack.pop()
        call = getattr(node, "call", None)
        tag = getattr(call, GUARD_MODULE_ATTR, None)
        if isinstance(tag, str):
            found.add(tag)
        stack.extend(getattr(node, "dependencies", ()))
    return found


def audit_admin_route_guards(app: object) -> tuple[list[str], int]:
    """앱의 `/v1/admin/*` 라우트가 전부 레지스트리 파생 가드를 쓰는지 검사한다.

    반환은 `(위반 목록, 검사한 라우트 수)`. 호출측이 "위반 0"만 보고 통과를 선언하지 못하게
    분모를 강제로 손에 쥐여 준다(모듈 docstring 마지막 문단).
    """
    violations: list[str] = []
    scanned = 0
    for route in walk_routes(getattr(app, "routes", ())):
        path = getattr(route, "path", "")
        if not isinstance(path, str) or not path.startswith(ADMIN_PATH_PREFIX):
            continue
        scanned += 1
        methods = ",".join(sorted(getattr(route, "methods", None) or ()))
        if path in GUARD_EXEMPT_PATHS:
            continue
        dependant = getattr(route, "dependant", None)
        if dependant is None:
            violations.append(f"{methods} {path}: dependant 부재 — 가드 판정 불가")
            continue
        module_ids = _guarded_module_ids(dependant)
        if not module_ids:
            violations.append(
                f"{methods} {path}: 레지스트리 파생 가드 없음 —"
                " require_module_roles(...)를 쓰거나 GUARD_EXEMPT_PATHS에 사유와 함께 등재하라"
            )
            continue
        for module_id in sorted(module_ids):
            if not has_module(module_id):
                violations.append(f"{methods} {path}: 미등재 모듈 {module_id!r}로 가드됨")
    return violations, scanned


def stale_guard_exemptions(app: object) -> list[str]:
    """앱에 실재하지 않는 면제 경로 — 낡은 면제는 면제가 아니라 사각이다.

    면제 목록이 실체보다 오래 살면, 경로를 지운 뒤에도 그 이름이 "검토됐다"는 인상만 남긴다.
    """
    live = {
        path
        for route in walk_routes(getattr(app, "routes", ()))
        if isinstance(path := getattr(route, "path", ""), str)
        and path.startswith(ADMIN_PATH_PREFIX)
    }
    return sorted(path for path in GUARD_EXEMPT_PATHS if path not in live)
