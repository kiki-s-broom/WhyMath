"""관리 콘솔 모듈 레지스트리 — 좌측 내비·권한 게이트의 **단일 진실 원천**(04 §2 원칙7).

왜 이 모듈이 있는가
------------------
관리 기능이 하나 늘 때마다 ①좌측 내비 컴포넌트 ②라우트 가드(`require_role`) ③설계 문서 표
세 곳을 사람이 각각 맞춰야 했다. 하나만 빠뜨려도 "코드엔 있는데 메뉴엔 없음"(발견 안 됨)
또는 "메뉴엔 있는데 가드가 없음"(무인가 노출)이 난다. 그래서 개발자는 **여기 엔트리 하나만**
추가하고, 메뉴와 가드는 전부 거기서 파생시킨다 — "자동 등록"의 실체는 발견 로직이 아니라
*중복 유지보수의 제거*다(04 §2 원칙7).

가드가 레지스트리에서 *파생*된다는 것이 핵심이다. 두 곳에 같은 값을 적어 두고 일치를 나중에
대조하는 방식이었다면 그 대조가 곧 드리프트의 자리가 된다. `require_module_roles(...)`는
`required_roles`를 레지스트리에서 읽어 의존성을 만들므로 불일치가 *발생할 수 없고*,
`audit_admin_route_guards`는 "그 파생 경로를 안 쓴 라우트"만 찾으면 된다.

이중 방어 (04 §2 원칙7·원칙3)
---------------------------
메뉴 필터링은 **UX 편의일 뿐 보안 경계가 아니다** — 메뉴에 안 보이는 항목도 URL을 직접 쳐서
접근을 시도할 수 있다. 그래서 각 `/v1/admin/*` 라우트는 자체 역할 가드를 별도로 가진다.
`GET /v1/admin/menu` 자신만 예외이며(`get_current_user`만 요구), 그 예외는 아래
`GUARD_EXEMPT_PATHS`에 **사유와 함께** 명시된다 — 무명 면제는 면제가 아니라 구멍이다.

시드 콘텐츠의 출처 (28건 — 숫자의 유래를 적어 둔다)
------------------------------------------------
- **22건**: [03 §5](../../../../docs/design/ui/03_admin_console_plan.md)의 22모듈 매핑 표.
  표는 19행이지만 `Version / Deployment / Monitoring` 행이 3모듈을 묶고 있어 셋으로 펼치면
  21이고, 여기에 §4 내비 트리가 "상시 상단"으로 둔 **검수 큐**를 더해 22다.
- **6건**: §5 표에는 없고 [03 §4](../../../../docs/design/ui/03_admin_console_plan.md) 내비
  트리에만 잎으로 있는 것 — 비용 리포트·빌드 하네스·사용자 조회·보호자 동의·데이터 반출/삭제·
  데이터셋 카탈로그. 레지스트리가 내비를 *파생*시키므로 트리의 잎은 전부 여기 있어야 한다
  (§5 표만 시드로 삼으면 `dataset` 섹션에 구성원이 하나도 없는 죽은 섹션 키가 생긴다 —
  `test_module_registry.py`가 그 상태를 실패로 잡는다).

`status`를 지금 시점에 어떻게 읽었는가 (정직한 공백)
-------------------------------------------------
ADMIN-04 시점에 관리 **UI는 하나도 없다**(`src/web/webapp` 부재 — ADMIN-06 소관). 그래서
`LIVE`(데이터+UI 모두 실동작) 엔트리는 **0건**이 정상이다. §5 표의 🟢/🟡 자산 행은 전부
`PARTIAL`로, 🔴 계획 행(Teacher/Parent Analytics·Learning Digital Twin·App Management)만
`PLANNED`로 적었다 — `PLANNED`의 정의가 "자산 없음"이라 자산이 실재하는 행에 붙이면 거짓이
되기 때문이다. `PARTIAL`의 "UI 일부"는 여기서 **0을 포함한 미완비**로 읽는다. UI가 실제로
서는 ADMIN-06/07에서 해당 엔트리가 `LIVE`로 올라간다.

파일 이름이 정본과 다른 이유 (04 §2 원칙7은 `admin/module_registry.py`로 적었다)
----------------------------------------------------------------------------
`api/`는 이 저장소에서 **평면**이다(하위 패키지 0·모듈 43). 게다가 EOS 기능 인벤토리
생성기의 전수성 검사가 `app.include_router(<name>_router)`의 별칭을 `api/<name>.py`로
되짚는 형태라(문자열 대조), 하위 패키지를 쓰면 CI 게이트 도구를 두 군데 더 고쳐야 한다.
설계 문서의 `admin/`은 제안이고 이 태스크의 범위를 넓힐 만한 값이 아니라서, 관례를 따르고
이름만 `admin_module_registry.py`로 붙였다. ADMIN-05가 admin 라우터를 여럿 붙일 때
패키지화를 다시 판단하면 되고, 그때는 생성기 수정 비용을 그 태스크가 진다.

7계층: 이 모듈은 선언(스키마+상수)과 그 선언에서 파생된 FastAPI 의존성뿐이며 수학 로직이 없다
(04 §2 원칙1 — 백오피스도 표현≠의미의 예외가 아니다).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Annotated

from fastapi import Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from whymath_backend.api._auth import get_current_user
from whymath_backend.db.models.user import UserProfile
from whymath_backend.schema.enums import Role


class AdminModuleStatus(str, Enum):
    """모듈의 구현 성숙도 — 3값 고정(04 §2 원칙7).

    프런트는 `PLANNED`를 **숨기지 않고 비활성("준비 중")으로 렌더**한다(`00_index.md` 구현
    상태 범례의 정직성 원칙을 메뉴에도 적용 — 존재를 숨기면 "없는 줄 알았다"가 생긴다).
    """

    LIVE = "live"
    """🟢 데이터+UI 모두 실동작."""

    PARTIAL = "partial"
    """🟡 데이터/엔진은 있고 UI가 미완비(0 포함 — 모듈 docstring 참조)."""

    PLANNED = "planned"
    """🔴 계획만(자산 없음) — 메뉴엔 노출하되 비활성 표시."""


class AdminSection(str, Enum):
    """좌측 내비 섹션 키.

    가운데 6개(`CONTENT`~`SETTINGS`)는 04 §2 원칙7이 스키마 주석에 열거한 정본 키다. 나머지
    둘은 03 §4 내비 트리에서 **그 6개 바깥에 따로 서 있는** 것이라 별도 키로 뒀다 —
    `REVIEW`는 트리가 "★ 상시 상단"으로 못박은 검수 큐이고, `DASHBOARD`는 03 §5 4계층
    프레임의 ①(KPI 한눈에)이다. 둘 다 문서에서 파생했지 새로 지어낸 구획이 아니다.
    """

    DASHBOARD = "dashboard"
    CONTENT = "content"
    LLM_PROMPT = "llm_prompt"
    COST_QUALITY = "cost_quality"
    USER_PRIVACY = "user_privacy"
    DATASET = "dataset"
    SETTINGS = "settings"
    REVIEW = "review"


# 섹션이 좌측 내비에 찍히는 순서. 내비 순서를 프런트가 자기 배열로 들고 있으면 그것 자체가
# 하드코딩 nav의 재발이므로(04 §2 원칙7), 순서도 서버가 준다. 검수 큐가 맨 위다(03 §4 "★ 상시
# 상단"), 그다음이 대시보드, 이후는 §4 트리 순서.
SECTION_ORDER: tuple[AdminSection, ...] = (
    AdminSection.REVIEW,
    AdminSection.DASHBOARD,
    AdminSection.CONTENT,
    AdminSection.LLM_PROMPT,
    AdminSection.COST_QUALITY,
    AdminSection.USER_PRIVACY,
    AdminSection.DATASET,
    AdminSection.SETTINGS,
)

SECTION_LABELS_KO: dict[AdminSection, str] = {
    AdminSection.REVIEW: "검수 큐",
    AdminSection.DASHBOARD: "운영 대시보드",
    AdminSection.CONTENT: "콘텐츠",
    AdminSection.LLM_PROMPT: "LLM·프롬프트",
    AdminSection.COST_QUALITY: "비용·품질",
    AdminSection.USER_PRIVACY: "사용자·프라이버시",
    AdminSection.DATASET: "데이터셋",
    AdminSection.SETTINGS: "설정",
}


class AdminModule(BaseModel):
    """관리 콘솔 모듈 1건의 선언 — 04 §2 원칙7 매니페스트 스키마.

    `frozen=True`인 이유: `_MODULE_REGISTRY`는 프로세스 전역 상수이고 요청 처리 중 노출되는
    객체다. 가변이면 한 요청의 필터링이 다음 요청의 권한을 바꿀 수 있다.
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(
        ...,
        min_length=1,
        description="안정 식별자 — 파일명·경로·교육과정과 독립(`concept_atom` 형태).",
    )
    section: AdminSection = Field(..., description="좌측 내비 섹션 키.")
    label_ko: str = Field(..., min_length=1, description="내비에 찍히는 한국어 라벨.")
    route: str = Field(..., description="Next.js 경로(`/admin/...`).")
    status: AdminModuleStatus = Field(..., description="구현 성숙도 3값.")
    required_roles: frozenset[Role] = Field(
        ...,
        description="이 모듈을 볼 수 있는 역할. **빈 집합 금지** — 명시 필수.",
    )
    backing_assets: tuple[str, ...] = Field(
        default=(),
        description="실 코드 경로(레포 루트 상대) — 추적성의 원천. PLANNED만 비울 수 있다.",
    )


def _module(
    module_id: str,
    section: AdminSection,
    label_ko: str,
    route: str,
    module_status: AdminModuleStatus,
    *backing_assets: str,
) -> AdminModule:
    """레지스트리 엔트리 생성 축약 — v0 역할은 전부 `CONTENT_ADMIN` 하나다.

    운영 백오피스는 학생에게 열리는 화면이 아니므로 v0 2값(`STUDENT`/`CONTENT_ADMIN`) 중
    `CONTENT_ADMIN`만 쓴다(04 §2 원칙3 "신규 enum 불요"). 역할이 갈리는 모듈이 실제로 생기면
    그때 이 헬퍼를 거치지 않고 `AdminModule(...)`을 직접 쓴다 — 좌석 없는 역할을 미리 만들지
    않는다는 `Role` enum의 방침과 같다.
    """
    return AdminModule(
        id=module_id,
        section=section,
        label_ko=label_ko,
        route=route,
        status=module_status,
        required_roles=frozenset({Role.CONTENT_ADMIN}),
        backing_assets=backing_assets,
    )


_PARTIAL = AdminModuleStatus.PARTIAL
_PLANNED = AdminModuleStatus.PLANNED

# append-only 상수. 엔트리를 지우지 말고 `status`를 낮추거나 새 엔트리를 덧붙인다 — 지우면
# 그 모듈을 쓰던 라우트의 가드가 import 시점에 터지는 대신 *조용히 면제*될 여지가 생긴다.
_MODULE_REGISTRY: tuple[AdminModule, ...] = (
    # ── 검수 큐 (03 §4 "★ 상시 상단" · 03 §3 검수 큐 UI) ──────────────────────────────
    _module(
        "review_queue",
        AdminSection.REVIEW,
        "검수 큐",
        "/admin/review",
        _PARTIAL,
        "src/backend/whymath_backend/harness/needs_review_worklist.py",
        "src/backend/whymath_backend/harness/review_session.py",
        "src/backend/whymath_backend/harness/review_timer.py",
    ),
    # ── 운영 대시보드 (03 §5 4계층 프레임 ①) ────────────────────────────────────────
    _module(
        "dashboard_kpi",
        AdminSection.DASHBOARD,
        "KPI 대시보드",
        "/admin",
        _PARTIAL,
        "src/backend/whymath_backend/app.py",
        "src/backend/whymath_backend/ops/cost_report.py",
    ),
    # ── 콘텐츠 (03 §5 Curriculum·Objective·Pedagogy·KG·Misconception·Library·DSL) ────
    _module(
        "curriculum",
        AdminSection.CONTENT,
        "교육과정",
        "/admin/content/curricula",
        _PARTIAL,
        "src/backend/whymath_backend/db/models/curriculum_framework.py",
        "src/backend/whymath_backend/db/models/curriculum_entry.py",
        "src/backend/whymath_backend/l1/curriculum",
    ),
    _module(
        "learning_objective",
        AdminSection.CONTENT,
        "학습목표·성취기준",
        "/admin/content/objectives",
        _PARTIAL,
        "src/backend/whymath_backend/db/models/achievement_standard.py",
        "src/backend/whymath_backend/l1/standards",
    ),
    _module(
        "pedagogy_pack",
        AdminSection.CONTENT,
        "교수법 팩 스튜디오",
        "/admin/content/pedagogy-packs",
        _PARTIAL,
        "src/backend/whymath_backend/schema/pedagogy_pack.py",
        "src/backend/whymath_backend/l1/pedagogy",
    ),
    _module(
        "knowledge_graph",
        AdminSection.CONTENT,
        "개념·원자 그래프 스튜디오",
        "/admin/content/concepts",
        _PARTIAL,
        "src/backend/whymath_backend/db/models/concept_node.py",
        "src/backend/whymath_backend/db/models/atom_node.py",
        "src/backend/whymath_backend/l1/atom_graph",
    ),
    _module(
        "misconception",
        AdminSection.CONTENT,
        "오개념 스튜디오",
        "/admin/content/misconceptions",
        _PARTIAL,
        "src/backend/whymath_backend/db/models/misconception_catalog.py",
        "src/backend/whymath_backend/db/models/misconception_crosslink.py",
        "src/backend/whymath_backend/l1/misconception",
    ),
    _module(
        "content_library",
        AdminSection.CONTENT,
        "콘텐츠 라이브러리(문항·풀이·시각화)",
        "/admin/content/library",
        _PARTIAL,
        "src/backend/whymath_backend/db/models/problem.py",
        "src/backend/whymath_backend/db/models/solution_node.py",
        "src/backend/whymath_backend/db/models/concept_content.py",
        "src/backend/whymath_backend/db/models/concept_visualization.py",
    ),
    _module(
        "dsl_builder",
        AdminSection.CONTENT,
        "DSL 빌더(UnitDSL·ConceptDSL)",
        "/admin/content/dsl",
        _PARTIAL,
        "src/backend/whymath_backend/l1/pedagogy/unit_compiler.py",
        "src/backend/whymath_backend/schema/unit_dsl.py",
        "src/backend/whymath_backend/l3/dsl",
    ),
    # ── LLM·프롬프트 (03 §5 Generation Pipeline·AI Models·Prompt Library) ────────────
    _module(
        "generation_pipeline",
        AdminSection.LLM_PROMPT,
        "생성 파이프라인",
        "/admin/llm/generation",
        _PARTIAL,
        "src/backend/whymath_backend/l3/pregenerate",
    ),
    _module(
        "ai_models",
        AdminSection.LLM_PROMPT,
        "AI 모델 매트릭스",
        "/admin/llm/models",
        _PARTIAL,
        "src/backend/whymath_backend/l3/router.py",
    ),
    _module(
        "prompt_library",
        AdminSection.LLM_PROMPT,
        "프롬프트 라이브러리(Langfuse 임베드)",
        "/admin/llm/prompts",
        _PARTIAL,
        "src/backend/whymath_backend/l3/prompt_assets.py",
    ),
    # ── 비용·품질 (03 §5 AI Evaluation/QA·Assessment·Monitoring + §4 비용 리포트·하네스) ─
    _module(
        "ai_evaluation_qa",
        AdminSection.COST_QUALITY,
        "AI 평가·QA 게이트",
        "/admin/quality/qa",
        _PARTIAL,
        "src/backend/whymath_backend/harness/golden_benchmark.py",
        "src/backend/whymath_backend/harness/golden_promotion_gate.py",
    ),
    _module(
        "assessment",
        AdminSection.COST_QUALITY,
        "평가·문항은행(IRT·BKT)",
        "/admin/quality/assessment",
        _PARTIAL,
        "src/backend/whymath_backend/l2/irt.py",
        "src/backend/whymath_backend/l2/bkt.py",
        "src/backend/whymath_backend/l1/problem_bank",
    ),
    _module(
        "cost_report",
        AdminSection.COST_QUALITY,
        "비용 리포트",
        "/admin/quality/cost",
        _PARTIAL,
        "src/backend/whymath_backend/ops/cost_report.py",
        "src/backend/whymath_backend/ops/cost_probe.py",
    ),
    _module(
        "build_harness",
        AdminSection.COST_QUALITY,
        "빌드 하네스(백로그·게이트 대장)",
        "/admin/quality/harness",
        _PARTIAL,
        "scripts/harness/backlog.py",
    ),
    _module(
        "monitoring",
        AdminSection.COST_QUALITY,
        "모니터링(이중 회계)",
        "/admin/quality/monitoring",
        _PARTIAL,
        "src/backend/whymath_backend/ops/service_health.py",
        "src/backend/whymath_backend/ops/cost_probe.py",
    ),
    # ── 사용자·프라이버시 (03 §5 Student/Teacher Analytics·Digital Twin + §4 3잎) ─────
    _module(
        "user_lookup",
        AdminSection.USER_PRIVACY,
        "사용자 조회(PII 최소)",
        "/admin/users",
        _PARTIAL,
        "src/backend/whymath_backend/api/users.py",
    ),
    _module(
        "parental_consent",
        AdminSection.USER_PRIVACY,
        "보호자 동의 상태",
        "/admin/users/consent",
        _PARTIAL,
        "src/backend/whymath_backend/consent.py",
        "src/backend/whymath_backend/consent_grant.py",
    ),
    _module(
        "privacy_operations",
        AdminSection.USER_PRIVACY,
        "데이터 반출·삭제·보존 파기",
        "/admin/users/privacy",
        _PARTIAL,
        "src/backend/whymath_backend/privacy",
    ),
    _module(
        "student_analytics",
        AdminSection.USER_PRIVACY,
        "학생 학습 분석",
        "/admin/users/analytics",
        _PARTIAL,
        "src/backend/whymath_backend/l2/mastery_tracking.py",
        "src/backend/whymath_backend/l2/skill_mastery_tracking.py",
    ),
    _module(
        "teacher_parent_analytics",
        AdminSection.USER_PRIVACY,
        "교사·보호자 분석",
        "/admin/users/teacher-analytics",
        _PLANNED,
    ),
    _module(
        "learning_digital_twin",
        AdminSection.USER_PRIVACY,
        "학습 디지털 트윈",
        "/admin/users/digital-twin",
        _PLANNED,
    ),
    # ── 데이터셋 (03 §4 코퍼스 카탈로그·provenance·라이선스) ──────────────────────────
    _module(
        "dataset_catalog",
        AdminSection.DATASET,
        "코퍼스 카탈로그·provenance·라이선스",
        "/admin/datasets",
        _PARTIAL,
        "src/backend/whymath_backend/l1/rights",
        "src/backend/whymath_backend/ops/corpus_provenance_sidecar.py",
        "src/backend/whymath_backend/ops/provenance_audit.py",
    ),
    # ── 설정 (03 §5 Version·Deployment·System Settings·App Management) ───────────────
    _module(
        "content_version",
        AdminSection.SETTINGS,
        "버전 관리",
        "/admin/settings/versions",
        _PARTIAL,
        "src/backend/whymath_backend/db/models/concept_version.py",
    ),
    _module(
        "deployment",
        AdminSection.SETTINGS,
        "배포",
        "/admin/settings/deployment",
        _PARTIAL,
        "infra",
        ".github/workflows/deploy.yml",
    ),
    _module(
        "system_settings",
        AdminSection.SETTINGS,
        "시스템 설정·권한(기능 플래그·RBAC)",
        "/admin/settings",
        _PARTIAL,
        "src/backend/whymath_backend/config.py",
        "src/backend/whymath_backend/ops/role_grant_cli.py",
    ),
    _module(
        "app_management",
        AdminSection.SETTINGS,
        "앱·다과목 관리",
        "/admin/settings/apps",
        _PLANNED,
    ),
)

_BY_ID: dict[str, AdminModule] = {m.id: m for m in _MODULE_REGISTRY}


def all_modules() -> tuple[AdminModule, ...]:
    """레지스트리 전건(선언 순서 유지). 외부는 이 함수로만 읽는다."""
    return _MODULE_REGISTRY


def get_module(module_id: str) -> AdminModule:
    """id로 엔트리 조회 — 없으면 `KeyError`.

    가드 생성(`require_module_roles`)이 import 시점에 이걸 부르므로, 오타 난 id는 서버가
    **기동조차 못 한다**. 조용히 통과해 무인가 노출이 되는 것보다 낫다.
    """
    return _BY_ID[module_id]


def has_module(module_id: str) -> bool:
    """`module_id`가 레지스트리에 있는가 — 감사기(`ops/admin_guard_audit.py`)가 쓴다.

    `get_module`은 없으면 `KeyError`를 던지는 *기동 시점* 용도이고, 이쪽은 감사가 예외 대신
    위반 문자열을 모으기 위한 조회다.
    """
    return module_id in _BY_ID


def visible_modules(role: Role) -> tuple[AdminModule, ...]:
    """`role`이 볼 수 있는 엔트리만 — 선언 순서 유지.

    `PLANNED`도 **제외하지 않는다**(04 §2 원칙7 — 프런트가 비활성으로 렌더). 여기서 거르는
    축은 오직 권한이다.
    """
    return tuple(m for m in _MODULE_REGISTRY if role in m.required_roles)


# ─────────────────────────────────────────────────────────────────────────────────────
# 라우트 가드 — 레지스트리에서 *파생*된다(두 곳에 같은 값을 적지 않는다)
# ─────────────────────────────────────────────────────────────────────────────────────

#: `require_module_roles`가 만든 의존성에 붙는 태그 속성명. `audit_admin_route_guards`가
#: 이 속성으로 "레지스트리 파생 가드인가"를 판정한다(함수 이름 비교는 데코레이터·functools
#: 래핑에서 깨지므로 속성으로 단다).
GUARD_MODULE_ATTR = "__whymath_admin_module__"


def require_module_roles(module_id: str) -> Callable[..., Awaitable[UserProfile]]:
    """모듈 `module_id`의 `required_roles`를 강제하는 FastAPI 의존성을 만든다.

    `api/_auth.require_role`과 같은 형태지만 역할을 **호출부가 적지 않는다** — 레지스트리에서
    읽는다. 그래서 메뉴 필터와 라우트 가드가 어긋날 수 없다(04 §2 원칙7 "레지스트리의
    `required_roles`와 라우트 가드는 같은 값을 참조해야 한다"를 *대조*가 아니라 *구조*로
    이행한다).

    무인증 요청은 여기 도달하기 전에 `get_current_user`가 401을 낸다 — 이 함수의 403은
    "인증은 됐는데 역할이 안 맞는" 경우에만 발화한다(`require_role` 주석과 동일한 체인 순서).
    """
    module = get_module(module_id)
    allowed = module.required_roles

    async def _dependency(
        user: Annotated[UserProfile, Depends(get_current_user)],
    ) -> UserProfile:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="권한이 없습니다(관리 콘솔 전용 모듈).",
            )
        return user

    setattr(_dependency, GUARD_MODULE_ATTR, module_id)
    return _dependency


#: 레지스트리 파생 가드를 **의도적으로** 달지 않는 `/v1/admin/*` 경로와 그 사유.
#: 빈 사유는 무효다(면제가 실재하고 이름이 있어야 면제다 — CLAUDE.md "의도적 미배선은 사유
#: 필수 허용 목록"). 여기 적힌 경로가 앱에 실재하지 않으면 그것도 위반이다(낡은 면제 금지).
GUARD_EXEMPT_PATHS: dict[str, str] = {
    "/v1/admin/menu": (
        "메뉴 자신은 모듈이 아니라 *모듈 목록*이다 — 04 §2 원칙7이 `get_current_user`만 요구"
        "하도록 못박았다(권한이 없는 사용자는 403이 아니라 빈 메뉴를 받는다). 이 경로를"
        " 모듈 가드로 막으면 역할 없는 운영자가 콘솔 셸조차 못 그린다."
    ),
}

#: `/v1/admin/` 접두 — 가드 감사의 판정 대상은 라우터 객체가 아니라 **경로 접두**다
#: (누가 어느 라우터에 달든 이 접두로 서빙되면 감사에 걸린다).
ADMIN_PATH_PREFIX = "/v1/admin/"
