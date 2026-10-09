"""CMS 제자리 편집 리소스 선언 — 무엇을 어느 필드까지 고칠 수 있는가의 단일 진실 원천 (P3-12).

왜 선언(데이터)인가
------------------
관리자 CMS가 다루는 리소스는 8종(교육과정 판·문항·풀이 단계·오개념·교수전략·개념 설명·힌트·스킬)이고
각각 목록/상세/수정/검수표시가 필요하다. 라우트를 리소스마다 손으로 쓰면 8×4=32개 핸들러가 생기고,
그중 하나에서 "상태 컬럼도 같이 받는" 실수가 나면 그것이 곧 워크플로우 우회다. 그래서 **편집 가능
필드를 허용 목록으로 선언**하고 라우터(`api/admin_cms.py`)는 그 선언만 소비한다 — 허용 목록에 없는
필드는 요청 모델 단계가 아니라 **서버 로직에서** 거부된다(`validate_changes`).

이 모듈이 막는 것 — 워크플로우 우회
-----------------------------------
`WORKFLOW_STATE_COLUMNS`는 "사람이 직접 쓰면 검수·발행 워크플로우를 건너뛰게 되는 컬럼"의 목록이다
(`review_status`·`is_published`·`publish_at`·`quarantine_*`·`current_published_version_id`·`status`·
`verified*`). 어떤 리소스의 편집 가능 필드에도 이 컬럼이 들어갈 수 없다 — 모듈 import 시점에
`check_specs`가 검사하므로 선언을 잘못 써도 **서버가 기동되지 않는다**(조용히 통과하지 않는다).

편집이 검수 표지를 되돌리는 규칙 (안전한 방향으로만)
-------------------------------------------------
텍스트를 사람이 고치면 이전 검수는 무효다. 그래서 편집은 검수 표지를 **낮추기만** 한다:
`concept_content`·`strategy_node`는 `review_status`를 `ai_estimated`로, `hint`는 `verified`를
`False`로, `problem_step`은 `sympy_verified`를 `None`(모름)으로 되돌린다. 반대 방향(검수됨으로
올림)은 편집으로 일어나지 않고 **검수 권한이 있는 별도 동작**(`POST .../review`)으로만 일어난다.

원천 정본과의 관계 (정직한 한계)
-------------------------------
이 리소스 대부분은 파일 정본(`data/corpus/*`)을 `populate` CLI가 DB로 투영한 것이다. CMS 편집은 DB만
바꾸므로 **같은 정본을 다시 적재하면 편집이 덮어써질 수 있다.** 이 이원성의 해소(적재가 CMS 편집을
보존하게 하거나 편집을 정본으로 역기록)는 이 모듈의 범위 밖이며 후속 태스크 소관이다.

7계층: L5 `api`의 선언. 수학 로직 0.
"""

from __future__ import annotations

import math
import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Final, Literal

from pydantic import ValidationError

from whymath_backend.db.models.concept_content import (
    CONTENT_REVIEW_STATUS_AI_ESTIMATED,
    ConceptContent,
)
from whymath_backend.db.models.curriculum_version import CurriculumVersion
from whymath_backend.db.models.hint import Hint
from whymath_backend.db.models.misconception_catalog import MisconceptionCatalog
from whymath_backend.db.models.problem import Problem, ProblemStep
from whymath_backend.db.models.skill_node import SkillNode
from whymath_backend.db.models.strategy_node import STRATEGY_REVIEW_STATUS_DEFAULT, StrategyNode
from whymath_backend.schema.enums import PrivacyAuditResourceType
from whymath_backend.schema.misconception_catalog import SEVERITY_VALUES
from whymath_backend.schema.problem import Problem as ProblemSchema

#: 텍스트 검수 표지의 두 값 — `concept_content`·`strategy_node`의 `review_status`가 쓴다.
REVIEW_STATUS_AI_ESTIMATED: Final[str] = CONTENT_REVIEW_STATUS_AI_ESTIMATED
REVIEW_STATUS_REVIEWED: Final[str] = "reviewed"

#: 사람이 직접 쓰면 검수·발행 워크플로우를 건너뛰는 컬럼. 어떤 리소스의 `editable`에도 들어갈 수
#: 없다(`check_specs`가 import 시점에 강제). 새 상태 컬럼이 생기면 여기에 더한다.
WORKFLOW_STATE_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "review_status",
        "review_score",
        "is_published",
        "publish_at",
        "quarantine_reason",
        "quarantined_at",
        "current_published_version_id",
        "status",
        "verified",
        "verified_by_human",
        "sympy_verified",
        "k_type_verified",
        "gate_report",
        "created_by",
    }
)

#: 문자열 키 리소스의 감사 `resource_id`(UUID 전용 컬럼)를 만드는 uuid5 네임스페이스. 값은 고정
#: 상수다 — 바꾸면 과거 감사 행과 같은 대상이 다른 id로 보인다.
_AUDIT_NAMESPACE: Final[uuid.UUID] = uuid.UUID("5b0d6c1e-3f7a-4c9e-9a1d-70c3d4e5f6a7")

#: 경로 인자로 받는 문자열 키의 허용 형태. `/`·공백·제어문자를 막는다(경로 분해 방지).
_STRING_PK = re.compile(r"^[A-Za-z0-9_.:\-]{1,200}$")

FieldKind = Literal["text", "longtext", "int", "float", "date", "choice"]
PkKind = Literal["uuid", "str"]


class FieldError(ValueError):
    """편집 요청의 한 필드가 거부됐다 — `code`는 안정 식별자, 문구는 사람용이다."""

    def __init__(self, field: str, code: str, message: str) -> None:
        self.field = field
        self.code = code
        self.message = message
        super().__init__(f"{field}: {code}: {message}")


@dataclass(frozen=True)
class FieldSpec:
    """편집 가능한 필드 1개의 선언 — 종류·범위·길이가 서버 검증의 정본이다."""

    name: str
    label_ko: str
    kind: FieldKind
    max_length: int | None = None
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] | None = None
    nullable: bool = False

    def coerce(self, value: object) -> object:
        """요청 값을 DB에 쓸 값으로 바꾼다. 거부는 `FieldError`.

        `bool`은 `int`의 하위 클래스라 숫자 필드가 `True`를 1로 받아들이지 않게 먼저 걸러낸다.
        """
        if value is None:
            if self.nullable:
                return None
            raise FieldError(self.name, "required", "비워 둘 수 없습니다.")
        if self.kind in ("text", "longtext", "choice"):
            return self._coerce_text(value)
        if self.kind == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                raise FieldError(self.name, "type", "정수여야 합니다.")
            return self._check_range(float(value), value)
        if self.kind == "float":
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise FieldError(self.name, "type", "숫자여야 합니다.")
            number = float(value)
            if not math.isfinite(number):
                raise FieldError(self.name, "type", "유한한 숫자여야 합니다.")
            return self._check_range(number, number)
        # date
        if not isinstance(value, str):
            raise FieldError(self.name, "type", "YYYY-MM-DD 문자열이어야 합니다.")
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise FieldError(self.name, "type", "YYYY-MM-DD 형식이 아닙니다.") from exc

    def _coerce_text(self, value: object) -> object:
        if not isinstance(value, str):
            raise FieldError(self.name, "type", "문자열이어야 합니다.")
        text = value.strip()
        if not text:
            if self.nullable:
                return None
            raise FieldError(self.name, "required", "비워 둘 수 없습니다.")
        if self.max_length is not None and len(text) > self.max_length:
            raise FieldError(self.name, "too_long", f"{self.max_length}자를 넘을 수 없습니다.")
        if self.choices is not None and text not in self.choices:
            raise FieldError(self.name, "choice", f"허용 값: {', '.join(self.choices)}")
        return text

    def _check_range(self, number: float, original: int | float) -> int | float:
        if self.minimum is not None and number < self.minimum:
            raise FieldError(self.name, "range", f"{self.minimum} 이상이어야 합니다.")
        if self.maximum is not None and number > self.maximum:
            raise FieldError(self.name, "range", f"{self.maximum} 이하여야 합니다.")
        return original


#: 편집 직전 추가 검증 — 병합 결과가 도메인 불변식을 지키는지 본다. 위반은 `FieldError`.
MergedValidator = Callable[[Any, Mapping[str, object]], None]


def _validate_problem_merge(row: Any, changes: Mapping[str, object]) -> None:
    """문항 편집 결과를 `schema.Problem`으로 재검증한다 — 본문 보유 금지 등 불변식 유지.

    기존 `PATCH /v1/problems`와 같은 검증(병합 → 스키마)이다. 다만 여기서는 **검증만** 하고,
    DB에 쓰는 것은 편집 가능 필드 몇 개뿐이다(`session.merge`로 행 전체를 갈아끼우지 않는다).
    """
    merged = row.to_schema().model_dump()
    merged.update(changes)
    try:
        ProblemSchema.model_validate(merged)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(part) for part in first["loc"]) or "problem"
        raise FieldError(loc, "schema", str(first["msg"])) from exc


#: 편집 허용 조건 — 라우터가 세션으로 평가한다. 위반은 409.
EditGuard = Literal["none", "problem_not_approved", "parent_problem_not_approved"]


@dataclass(frozen=True)
class ResourceSpec:
    """CMS 리소스 1종의 선언."""

    key: str
    label_ko: str
    module_id: str
    model: type[Any]
    pk: str
    pk_kind: PkKind
    #: 쓰기 감사 대상. 읽기 전용 리소스는 `None`(쓰기가 없으니 감사할 것도 없다).
    audit_type: PrivacyAuditResourceType | None
    list_columns: tuple[str, ...]
    detail_columns: tuple[str, ...]
    editable: tuple[FieldSpec, ...] = ()
    search_column: str | None = None
    order_by: str | None = None
    #: 편집 시 서버가 안전한 방향으로 되돌리는 컬럼 → 값. 사람이 보낼 수 없는 컬럼이라
    #: 여기서만 쓴다.
    reset_on_edit: tuple[tuple[str, object], ...] = ()
    #: 텍스트 검수 표지 컬럼(`ai_estimated`/`reviewed`). 있으면 `POST .../review`가 열린다.
    review_column: str | None = None
    edit_guard: EditGuard = "none"
    merged_validator: MergedValidator | None = None

    @property
    def editable_names(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.editable)

    @property
    def read_only(self) -> bool:
        return not self.editable and self.review_column is None


RESOURCES: Final[tuple[ResourceSpec, ...]] = (
    ResourceSpec(
        key="curriculum_version",
        label_ko="교육과정 판",
        module_id="curriculum",
        model=CurriculumVersion,
        pk="version_id",
        pk_kind="uuid",
        audit_type=PrivacyAuditResourceType.curriculum_version,
        list_columns=("version_id", "framework_id", "version_label", "effective_from", "status"),
        detail_columns=(
            "version_id",
            "framework_id",
            "version_label",
            "effective_from",
            "effective_to",
            "status",
            "source_id",
            "updated_at",
        ),
        editable=(
            FieldSpec("version_label", "판 이름", "text", max_length=120),
            FieldSpec("effective_from", "시행 시작일", "date", nullable=True),
            FieldSpec("effective_to", "시행 종료일", "date", nullable=True),
        ),
        search_column="version_label",
        order_by="framework_id",
    ),
    ResourceSpec(
        key="problem",
        label_ko="문항",
        module_id="content_library",
        model=Problem,
        pk="problem_id",
        pk_kind="uuid",
        audit_type=PrivacyAuditResourceType.problem,
        list_columns=("problem_id", "subject", "domain", "difficulty_overall", "review_status"),
        detail_columns=(
            "problem_id",
            "subject",
            "domain",
            "question_text",
            "answer",
            "answer_explanation",
            "difficulty_overall",
            "review_status",
            "quarantine_reason",
        ),
        editable=(
            FieldSpec("question_text", "문제 본문", "longtext", nullable=True),
            FieldSpec("answer", "정답", "longtext", max_length=2000, nullable=True),
            FieldSpec("answer_explanation", "해설", "longtext", nullable=True),
            # 범위는 `schema.Problem.difficulty_overall`(1.0~5.0)과 같다.
            # 최종 권위는 스키마 재검증이다(`_validate_problem_merge`).
            FieldSpec(
                "difficulty_overall", "난이도", "float", minimum=1.0, maximum=5.0, nullable=True
            ),
        ),
        search_column="domain",
        order_by="problem_id",
        edit_guard="problem_not_approved",
        merged_validator=_validate_problem_merge,
    ),
    ResourceSpec(
        key="problem_step",
        label_ko="풀이 단계",
        module_id="content_library",
        model=ProblemStep,
        pk="step_id",
        pk_kind="uuid",
        audit_type=PrivacyAuditResourceType.problem_step,
        list_columns=("step_id", "problem_id", "step_order", "step_title", "sympy_verified"),
        detail_columns=(
            "step_id",
            "problem_id",
            "step_order",
            "step_title",
            "socratic_prompt",
            "expected_answer",
            "sympy_verified",
        ),
        editable=(
            FieldSpec("step_title", "단계 제목", "text", max_length=300, nullable=True),
            FieldSpec("socratic_prompt", "소크라테스 질문", "longtext", nullable=True),
            FieldSpec("expected_answer", "기대 답", "longtext", max_length=2000, nullable=True),
        ),
        search_column="step_title",
        order_by="step_order",
        # 기대 답이 바뀌면 이전 기계 검증 결과는 무효다 — 거짓(False)이 아니라 "모름"(None)으로
        # 되돌린다.
        reset_on_edit=(("sympy_verified", None),),
        edit_guard="parent_problem_not_approved",
    ),
    ResourceSpec(
        key="misconception",
        label_ko="오개념",
        module_id="misconception",
        model=MisconceptionCatalog,
        pk="mis_id",
        pk_kind="str",
        audit_type=PrivacyAuditResourceType.misconception,
        list_columns=("mis_id", "canonical_statement", "severity", "domain"),
        detail_columns=(
            "mis_id",
            "canonical_statement",
            "student_wrong_thinking",
            "distractor_rule",
            "correction_point",
            "severity",
            "domain",
            "standard_code",
        ),
        editable=(
            FieldSpec("canonical_statement", "오개념 서술(Signature)", "longtext", nullable=True),
            FieldSpec("student_wrong_thinking", "학생의 잘못된 생각", "longtext", nullable=True),
            FieldSpec("distractor_rule", "오답 보기 생성 규칙", "longtext", nullable=True),
            FieldSpec("correction_point", "교정 포인트", "longtext", nullable=True),
            FieldSpec(
                "severity", "심각도", "choice", choices=tuple(SEVERITY_VALUES), nullable=True
            ),
        ),
        search_column="canonical_statement",
        order_by="mis_id",
    ),
    ResourceSpec(
        key="strategy_node",
        label_ko="교수전략",
        module_id="pedagogy_pack",
        model=StrategyNode,
        pk="strategy_id",
        pk_kind="str",
        audit_type=PrivacyAuditResourceType.strategy_node,
        list_columns=("strategy_id", "name_ko", "family", "review_status"),
        detail_columns=(
            "strategy_id",
            "name_ko",
            "family",
            "description",
            "review_status",
            "updated_at",
        ),
        editable=(
            FieldSpec("name_ko", "전략 이름", "text", max_length=200),
            FieldSpec("description", "전략 설명", "longtext"),
        ),
        search_column="name_ko",
        order_by="strategy_id",
        reset_on_edit=(("review_status", STRATEGY_REVIEW_STATUS_DEFAULT),),
        review_column="review_status",
    ),
    ResourceSpec(
        key="concept_content",
        label_ko="개념 설명",
        module_id="content_library",
        model=ConceptContent,
        pk="code",
        pk_kind="str",
        audit_type=PrivacyAuditResourceType.concept_content,
        list_columns=("code", "name", "scope", "review_status"),
        detail_columns=(
            "code",
            "name",
            "scope",
            "explanation",
            "metaphor",
            "misconception",
            "review_status",
            "updated_at",
        ),
        editable=(
            FieldSpec("explanation", "개념 설명", "longtext", nullable=True),
            FieldSpec("metaphor", "비유", "longtext", nullable=True),
            FieldSpec("misconception", "흔한 오개념", "longtext", nullable=True),
        ),
        search_column="name",
        order_by="code",
        reset_on_edit=(("review_status", REVIEW_STATUS_AI_ESTIMATED),),
        review_column="review_status",
    ),
    ResourceSpec(
        key="hint",
        label_ko="힌트",
        module_id="content_library",
        model=Hint,
        pk="hint_id",
        pk_kind="str",
        audit_type=PrivacyAuditResourceType.hint,
        list_columns=("hint_id", "problem_id", "step_order", "level", "verified"),
        detail_columns=(
            "hint_id",
            "problem_id",
            "step_order",
            "level",
            "content",
            "verified",
            "updated_at",
        ),
        editable=(FieldSpec("content", "힌트 문구", "longtext"),),
        search_column="content",
        order_by="hint_id",
        # 고친 힌트는 검증 게이트를 다시 통과해야 서빙된다 — 검증 표지를 내린다(올리는 길은
        # CMS에 없다).
        reset_on_edit=(("verified", False),),
    ),
    ResourceSpec(
        key="skill_node",
        label_ko="스킬",
        module_id="knowledge_graph",
        model=SkillNode,
        pk="skill_id",
        pk_kind="str",
        audit_type=None,
        list_columns=("skill_id", "name_ko", "behavior_area", "family", "review_status"),
        detail_columns=(
            "skill_id",
            "name_ko",
            "behavior_area",
            "family",
            "description",
            "prerequisite_skill_ids",
            "review_status",
        ),
        search_column="name_ko",
        order_by="skill_id",
    ),
)

_BY_KEY: Final[dict[str, ResourceSpec]] = {spec.key: spec for spec in RESOURCES}


def get_resource(key: str) -> ResourceSpec:
    """키로 조회 — 없으면 `KeyError`."""
    return _BY_KEY[key]


def audit_resource_id(spec: ResourceSpec, pk_value: object) -> uuid.UUID:
    """감사 행의 `resource_id`(UUID 전용 컬럼). 문자열 키는 uuid5로 결정론 변환한다.

    같은 (리소스, 키)는 항상 같은 UUID라, 키를 아는 사람이 감사 행을 되짚을 수 있다.
    """
    if spec.audit_type is None:
        raise ValueError(f"{spec.key}: 읽기 전용 리소스는 감사 대상이 아니다")
    if spec.pk_kind == "uuid":
        if not isinstance(pk_value, uuid.UUID):
            raise TypeError(f"{spec.key}: uuid 키가 필요하다: {pk_value!r}")
        return pk_value
    return uuid.uuid5(_AUDIT_NAMESPACE, f"{spec.audit_type.value}:{pk_value}")


def parse_pk(spec: ResourceSpec, raw: str) -> uuid.UUID | str | None:
    """경로 인자를 키로 바꾼다. 형태가 틀리면 `None`(호출자는 404로 읽는다)."""
    if spec.pk_kind == "uuid":
        try:
            return uuid.UUID(raw)
        except ValueError:
            return None
    return raw if _STRING_PK.match(raw) else None


def to_jsonable(value: object) -> object:
    """응답용 값 변환 — 명시한 컬럼만 이 함수를 지난다(`__dict__`를 통째로 내지 않는다).

    **Enum 분기가 원시형 분기보다 앞이다.** 이 저장소의 열거형은 대부분 `(str, Enum)`이라 멤버가
    `str`이기도 한데, 원시형 분기가 먼저면 멤버가 그대로 통과하고 호출부의 `str(...)`이
    `'ConceptLevel.단원'` 같은 *이름 문자열*을 만든다(실백엔드 종단 검증에서 발견 — 개념 목록의
    `level`·관계의 `edge_type`이 그렇게 나갔다). 결과는 항상 순수 원시형이다.
    """
    if isinstance(value, Enum):
        return to_jsonable(value.value)
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Mapping):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [to_jsonable(v) for v in value]
    return str(value)


def validate_changes(spec: ResourceSpec, changes: Mapping[str, object]) -> dict[str, object]:
    """요청의 `changes`를 검증·변환한다. **허용 목록 밖의 필드는 전부 거부**한다.

    상태·발행 컬럼은 이 허용 목록에 존재할 수 없으므로(`check_specs`) 이 함수가 "CMS가 워크플로우를
    우회해 Published를 쓰는 경로"의 서버 측 차단점이다. 거부는 첫 위반에서 멈춘다(부분 적용 없음).
    """
    if not changes:
        raise FieldError("changes", "empty", "수정할 필드가 없습니다.")
    by_name = {f.name: f for f in spec.editable}
    coerced: dict[str, object] = {}
    for name, value in changes.items():
        field_spec = by_name.get(name)
        if field_spec is None:
            code = "field_not_editable" if name in WORKFLOW_STATE_COLUMNS else "unknown_field"
            raise FieldError(name, code, f"이 경로로 수정할 수 없는 필드입니다: {name}")
        coerced[name] = field_spec.coerce(value)
    return coerced


def apply_changes(
    spec: ResourceSpec, row: object, coerced: Mapping[str, object]
) -> tuple[list[str], list[str]]:
    """`coerced`를 행에 쓰고 (바뀐 필드, 서버가 되돌린 표지)를 돌려준다. 값이 같으면 건너뛴다.

    표지 되돌림은 **실제로 바뀐 필드가 있을 때만** 일어난다 — 같은 값을 다시 저장해도 검수가
    풀리면 검수자가 저장 한 번에 일을 잃는다.
    """
    changed: list[str] = []
    for name, value in coerced.items():
        if getattr(row, name) != value:
            setattr(row, name, value)
            changed.append(name)
    resets: list[str] = []
    if changed:
        for column, reset_value in spec.reset_on_edit:
            if getattr(row, column) != reset_value:
                setattr(row, column, reset_value)
                resets.append(column)
    return changed, resets


def check_specs(specs: tuple[ResourceSpec, ...]) -> None:
    """선언 자기검증 — 틀리면 `RuntimeError`. import 시점에 `RESOURCES`로 호출된다.

    조용히 통과하는 선언 오류가 워크플로우 우회가 되므로, 런타임이 아니라 기동 시점에 잡는다.
    인자를 받는 형태라 테스트가 **결함을 주입한 선언**으로 이 검사의 변별력을 직접 확인한다.
    """
    seen: set[str] = set()
    for spec in specs:
        if spec.key in seen:
            raise RuntimeError(f"CMS 리소스 키 중복: {spec.key}")
        seen.add(spec.key)
        columns = {c.key for c in spec.model.__table__.columns}
        wanted = {
            spec.pk,
            *spec.list_columns,
            *spec.detail_columns,
            *spec.editable_names,
            *(c for c, _ in spec.reset_on_edit),
        }
        for optional in (spec.search_column, spec.order_by, spec.review_column):
            if optional is not None:
                wanted.add(optional)
        missing = sorted(wanted - columns)
        if missing:
            raise RuntimeError(f"{spec.key}: 모델에 없는 컬럼 선언: {missing}")
        forbidden = sorted(set(spec.editable_names) & WORKFLOW_STATE_COLUMNS)
        if forbidden:
            raise RuntimeError(f"{spec.key}: 편집 가능 필드에 워크플로우 상태 컬럼: {forbidden}")
        if spec.pk in spec.editable_names:
            raise RuntimeError(f"{spec.key}: 기본키는 편집할 수 없다")
        if spec.review_column is not None and spec.review_column not in spec.detail_columns:
            raise RuntimeError(f"{spec.key}: 검수 표지 컬럼이 상세 응답에 없다")
        if spec.edit_guard != "none" and not spec.editable:
            raise RuntimeError(f"{spec.key}: 편집 불가 리소스에 편집 가드가 있다")
        writable = bool(spec.editable) or spec.review_column is not None
        if writable and spec.audit_type is None:
            raise RuntimeError(f"{spec.key}: 쓰기가 있는 리소스에 감사 대상이 없다")


check_specs(RESOURCES)

__all__ = [
    "REVIEW_STATUS_AI_ESTIMATED",
    "REVIEW_STATUS_REVIEWED",
    "RESOURCES",
    "WORKFLOW_STATE_COLUMNS",
    "FieldError",
    "FieldSpec",
    "ResourceSpec",
    "apply_changes",
    "audit_resource_id",
    "check_specs",
    "get_resource",
    "parse_pk",
    "to_jsonable",
    "validate_changes",
]
