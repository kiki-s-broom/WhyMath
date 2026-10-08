"""CMS 리소스 선언·검증 단위테스트 — P3-12 (`api/admin_cms_resources.py`, hermetic).

이 파일이 막는 것:

  ① **워크플로우 우회** — 어떤 리소스의 편집 가능 필드에도 상태·발행 컬럼
     (`WORKFLOW_STATE_COLUMNS`)이 들어갈 수 없고, 들어간 선언은 `check_specs`가 거부한다.
     정상 선언이 통과한다는 것은 증거가 아니다 → **결함을 주입한 선언**으로 거부를 직접 본다.
  ② **허용 목록 동결** — 리소스별 편집 가능 필드를 이 파일에 명시해 둔다. 필드를 하나 더하려면
     이 테스트를 의도적으로 고쳐야 한다(조용한 확장 방지).
  ③ **편집의 검수 되돌림은 안전한 방향뿐** — 검수됨으로 *올리는* 값이 `reset_on_edit`에 들어가면 RED.
  ④ **서버 측 값 검증** — 타입·범위·길이·선택지·bool-as-int 같은 흔한 구멍.
"""

from __future__ import annotations

import dataclasses
import math
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from whymath_backend.api.admin_cms_resources import (
    RESOURCES,
    WORKFLOW_STATE_COLUMNS,
    FieldError,
    FieldSpec,
    ResourceSpec,
    apply_changes,
    audit_resource_id,
    check_specs,
    get_resource,
    parse_pk,
    to_jsonable,
    validate_changes,
)
from whymath_backend.db.models.problem import Problem
from whymath_backend.schema.enums import (
    ConceptLevel,
    Curriculum,
    PrivacyAuditResourceType,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem import Problem as ProblemSchema

# ② 허용 목록 동결 — 리소스 → 편집 가능 필드(순서 포함).
_EXPECTED_EDITABLE: dict[str, tuple[str, ...]] = {
    "curriculum_version": ("version_label", "effective_from", "effective_to"),
    "problem": ("question_text", "answer", "answer_explanation", "difficulty_overall"),
    "problem_step": ("step_title", "socratic_prompt", "expected_answer"),
    "misconception": (
        "canonical_statement",
        "student_wrong_thinking",
        "distractor_rule",
        "correction_point",
        "severity",
    ),
    "strategy_node": ("name_ko", "description"),
    "concept_content": ("explanation", "metaphor", "misconception"),
    "hint": ("content",),
    "skill_node": (),
}

# ③ 편집 시 서버가 되돌리는 표지 — 전부 *신뢰를 낮추는* 방향이어야 한다.
_EXPECTED_RESETS: dict[str, tuple[tuple[str, object], ...]] = {
    "problem_step": (("sympy_verified", None),),
    "strategy_node": (("review_status", "ai_estimated"),),
    "concept_content": (("review_status", "ai_estimated"),),
    "hint": (("verified", False),),
}


class TestDeclarations:
    def test_resource_set_is_frozen(self) -> None:
        assert [spec.key for spec in RESOURCES] == list(_EXPECTED_EDITABLE)

    @pytest.mark.parametrize("spec", RESOURCES, ids=lambda s: s.key)
    def test_editable_fields_match_the_frozen_allowlist(self, spec: ResourceSpec) -> None:
        assert spec.editable_names == _EXPECTED_EDITABLE[spec.key]

    @pytest.mark.parametrize("spec", RESOURCES, ids=lambda s: s.key)
    def test_no_editable_field_is_a_workflow_state_column(self, spec: ResourceSpec) -> None:
        assert not set(spec.editable_names) & WORKFLOW_STATE_COLUMNS

    @pytest.mark.parametrize("spec", RESOURCES, ids=lambda s: s.key)
    def test_primary_key_is_never_editable(self, spec: ResourceSpec) -> None:
        assert spec.pk not in spec.editable_names

    @pytest.mark.parametrize("spec", RESOURCES, ids=lambda s: s.key)
    def test_resets_only_lower_trust(self, spec: ResourceSpec) -> None:
        """③ `reviewed`/`True`로 올리는 값이 reset에 있으면 편집이 곧 검수 통과가 된다."""
        assert spec.reset_on_edit == _EXPECTED_RESETS.get(spec.key, ())

    def test_every_writable_resource_has_an_audit_type(self) -> None:
        for spec in RESOURCES:
            writable = bool(spec.editable) or spec.review_column is not None
            assert (spec.audit_type is not None) == writable, spec.key

    def test_only_skill_node_is_read_only(self) -> None:
        assert [spec.key for spec in RESOURCES if spec.read_only] == ["skill_node"]

    def test_audit_types_are_registered_enum_members(self) -> None:
        known = {t.value for t in PrivacyAuditResourceType}
        for spec in RESOURCES:
            if spec.audit_type is not None:
                assert spec.audit_type.value in known

    def test_audit_values_fit_the_string_columns(self) -> None:
        """`privacy_audit.resource_type`은 String(32) — 넘으면 INSERT가 런타임에 터진다."""
        for t in PrivacyAuditResourceType:
            assert len(t.value) <= 32, t.value

    def test_get_resource_roundtrip_and_miss(self) -> None:
        assert get_resource("problem").model is Problem
        with pytest.raises(KeyError):
            get_resource("nope")


class TestCheckSpecsDiscriminates:
    """① 정상 선언이 통과하는 것은 증거가 아니다 — 결함 선언이 거부되는지 직접 본다."""

    def _base(self, key: str = "concept_content") -> ResourceSpec:
        return get_resource(key)

    def test_baseline_passes(self) -> None:
        check_specs(RESOURCES)

    @pytest.mark.parametrize("column", sorted(WORKFLOW_STATE_COLUMNS))
    def test_every_workflow_state_column_is_rejected_as_editable(self, column: str) -> None:
        base = self._base()
        injected = dataclasses.replace(
            base, editable=(*base.editable, FieldSpec(column, "주입", "text", nullable=True))
        )
        # 모델에 없는 컬럼이면 '모델에 없는 컬럼'으로 먼저 거부될 수 있다 — 어느 쪽이든 거부여야 한다.
        with pytest.raises(RuntimeError):
            check_specs((injected,))

    def test_state_column_on_the_model_is_rejected_for_the_right_reason(self) -> None:
        """모델에 *실재하는* 상태 컬럼(`review_status`)은 정확히 '워크플로우 상태 컬럼'으로 거부된다."""
        base = self._base()
        injected = dataclasses.replace(
            base,
            editable=(*base.editable, FieldSpec("review_status", "주입", "text")),
        )
        with pytest.raises(RuntimeError, match="워크플로우 상태 컬럼"):
            check_specs((injected,))

    def test_unknown_column_is_rejected(self) -> None:
        base = self._base()
        injected = dataclasses.replace(
            base, editable=(*base.editable, FieldSpec("no_such_column", "주입", "text"))
        )
        with pytest.raises(RuntimeError, match="모델에 없는 컬럼"):
            check_specs((injected,))

    def test_editable_primary_key_is_rejected(self) -> None:
        base = self._base()
        injected = dataclasses.replace(
            base, editable=(*base.editable, FieldSpec(base.pk, "주입", "text"))
        )
        with pytest.raises(RuntimeError, match="기본키"):
            check_specs((injected,))

    def test_duplicate_key_is_rejected(self) -> None:
        base = self._base()
        with pytest.raises(RuntimeError, match="중복"):
            check_specs((base, base))

    def test_writable_resource_without_audit_type_is_rejected(self) -> None:
        injected = dataclasses.replace(self._base(), audit_type=None)
        with pytest.raises(RuntimeError, match="감사 대상"):
            check_specs((injected,))

    def test_review_column_missing_from_detail_is_rejected(self) -> None:
        base = self._base()
        injected = dataclasses.replace(
            base, detail_columns=tuple(c for c in base.detail_columns if c != "review_status")
        )
        with pytest.raises(RuntimeError, match="검수 표지"):
            check_specs((injected,))


class TestFieldCoerce:
    def test_text_is_stripped(self) -> None:
        assert FieldSpec("a", "a", "text").coerce("  안녕  ") == "안녕"

    def test_blank_text_is_rejected_unless_nullable(self) -> None:
        with pytest.raises(FieldError) as raised:
            FieldSpec("a", "a", "text").coerce("   ")
        assert raised.value.code == "required"
        assert FieldSpec("a", "a", "text", nullable=True).coerce("   ") is None

    def test_none_is_rejected_unless_nullable(self) -> None:
        with pytest.raises(FieldError):
            FieldSpec("a", "a", "text").coerce(None)
        assert FieldSpec("a", "a", "text", nullable=True).coerce(None) is None

    def test_text_length_is_enforced_after_stripping(self) -> None:
        spec = FieldSpec("a", "a", "text", max_length=3)
        assert spec.coerce("  abc ") == "abc"
        with pytest.raises(FieldError) as raised:
            spec.coerce("abcd")
        assert raised.value.code == "too_long"

    def test_non_string_text_is_rejected(self) -> None:
        with pytest.raises(FieldError) as raised:
            FieldSpec("a", "a", "text").coerce(123)
        assert raised.value.code == "type"

    def test_choice_accepts_only_declared_values(self) -> None:
        spec = FieldSpec("sev", "심각도", "choice", choices=("blocking", "local"))
        assert spec.coerce("local") == "local"
        with pytest.raises(FieldError) as raised:
            spec.coerce("cosmetic")
        assert raised.value.code == "choice"

    def test_bool_is_not_an_int(self) -> None:
        """`True`는 파이썬에서 `1`이다 — 숫자 필드가 그대로 받으면 안 된다."""
        with pytest.raises(FieldError):
            FieldSpec("n", "n", "int").coerce(True)
        with pytest.raises(FieldError):
            FieldSpec("n", "n", "float").coerce(False)

    def test_int_range(self) -> None:
        spec = FieldSpec("n", "n", "int", minimum=1, maximum=3)
        assert spec.coerce(2) == 2
        for bad in (0, 4):
            with pytest.raises(FieldError) as raised:
                spec.coerce(bad)
            assert raised.value.code == "range"

    def test_int_rejects_float_and_string(self) -> None:
        for bad in (1.5, "1"):
            with pytest.raises(FieldError):
                FieldSpec("n", "n", "int").coerce(bad)

    @pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
    def test_float_rejects_non_finite(self, bad: float) -> None:
        with pytest.raises(FieldError):
            FieldSpec("x", "x", "float").coerce(bad)

    def test_float_accepts_int_and_enforces_range(self) -> None:
        spec = FieldSpec("x", "x", "float", minimum=0.0, maximum=1.0)
        assert spec.coerce(1) == 1
        assert spec.coerce(0.25) == 0.25
        with pytest.raises(FieldError):
            spec.coerce(1.01)

    def test_date_parses_iso_only(self) -> None:
        spec = FieldSpec("d", "d", "date", nullable=True)
        assert spec.coerce("2026-03-01") == date(2026, 3, 1)
        for bad in ("2026/03/01", "내일", 20260301):
            with pytest.raises(FieldError):
                spec.coerce(bad)


class TestValidateChanges:
    def test_empty_changes_are_rejected(self) -> None:
        with pytest.raises(FieldError) as raised:
            validate_changes(get_resource("hint"), {})
        assert raised.value.code == "empty"

    def test_unknown_field_is_rejected(self) -> None:
        with pytest.raises(FieldError) as raised:
            validate_changes(get_resource("hint"), {"no_such": "x"})
        assert raised.value.code == "unknown_field"

    @pytest.mark.parametrize("column", sorted(WORKFLOW_STATE_COLUMNS))
    @pytest.mark.parametrize("spec", [s for s in RESOURCES if s.editable], ids=lambda s: s.key)
    def test_workflow_state_columns_are_rejected_before_any_row_is_read(
        self, spec: ResourceSpec, column: str
    ) -> None:
        """② 상태·발행 컬럼은 어떤 리소스에서도 `field_not_editable` — 행을 읽기 전에 거부된다."""
        with pytest.raises(FieldError) as raised:
            validate_changes(spec, {column: "approved"})
        assert raised.value.code == "field_not_editable"
        assert raised.value.field == column

    def test_one_bad_field_rejects_the_whole_request(self) -> None:
        """부분 적용이 없다 — 첫 위반에서 멈추고 아무것도 돌려주지 않는다."""
        with pytest.raises(FieldError):
            validate_changes(
                get_resource("concept_content"), {"explanation": "ok", "review_status": "reviewed"}
            )

    def test_valid_changes_are_coerced(self) -> None:
        out = validate_changes(get_resource("hint"), {"content": "  새 문구  "})
        assert out == {"content": "새 문구"}


class TestApplyChanges:
    @staticmethod
    def _row(**kw: Any) -> SimpleNamespace:
        return SimpleNamespace(**kw)

    def test_changed_field_is_written_and_marker_is_lowered(self) -> None:
        spec = get_resource("concept_content")
        row = self._row(
            explanation="옛", metaphor=None, misconception=None, review_status="reviewed"
        )
        changed, resets = apply_changes(spec, row, {"explanation": "새"})
        assert changed == ["explanation"]
        assert resets == ["review_status"]
        assert row.review_status == "ai_estimated"
        assert row.explanation == "새"

    def test_same_value_is_a_noop_and_keeps_the_review(self) -> None:
        """같은 값을 다시 저장해도 검수가 풀리면 검수자가 저장 한 번에 일을 잃는다."""
        spec = get_resource("concept_content")
        row = self._row(
            explanation="같음", metaphor=None, misconception=None, review_status="reviewed"
        )
        changed, resets = apply_changes(spec, row, {"explanation": "같음"})
        assert (changed, resets) == ([], [])
        assert row.review_status == "reviewed"

    def test_marker_already_low_is_not_reported_as_reset(self) -> None:
        spec = get_resource("concept_content")
        row = self._row(
            explanation="옛", metaphor=None, misconception=None, review_status="ai_estimated"
        )
        _, resets = apply_changes(spec, row, {"explanation": "새"})
        assert resets == []

    def test_hint_edit_clears_verified_and_step_edit_makes_it_unknown(self) -> None:
        hint = self._row(content="옛", verified=True)
        apply_changes(get_resource("hint"), hint, {"content": "새"})
        assert hint.verified is False
        step = self._row(
            step_title=None, socratic_prompt=None, expected_answer="1", sympy_verified=True
        )
        apply_changes(get_resource("problem_step"), step, {"expected_answer": "2"})
        assert step.sympy_verified is None  # 거짓이 아니라 '모름'


class TestAuditResourceId:
    def test_uuid_key_passes_through(self) -> None:
        pk = uuid.uuid4()
        assert audit_resource_id(get_resource("problem"), pk) == pk

    def test_uuid_resource_rejects_non_uuid(self) -> None:
        with pytest.raises(TypeError):
            audit_resource_id(get_resource("problem"), "not-a-uuid")

    def test_string_key_is_deterministic(self) -> None:
        spec = get_resource("misconception")
        assert audit_resource_id(spec, "M0425") == audit_resource_id(spec, "M0425")
        assert audit_resource_id(spec, "M0425") != audit_resource_id(spec, "M0426")

    def test_same_key_in_different_resources_does_not_collide(self) -> None:
        a = audit_resource_id(get_resource("hint"), "X1")
        b = audit_resource_id(get_resource("strategy_node"), "X1")
        assert a != b

    def test_read_only_resource_has_no_audit_id(self) -> None:
        with pytest.raises(ValueError):
            audit_resource_id(get_resource("skill_node"), "S1")


class TestParsePk:
    def test_uuid(self) -> None:
        pk = uuid.uuid4()
        assert parse_pk(get_resource("problem"), str(pk)) == pk
        assert parse_pk(get_resource("problem"), "nope") is None

    @pytest.mark.parametrize("ok", ["M0425", "hint-sp.1-s2-l3", "math.calculus.limit", "a:b_c-d"])
    def test_string_keys_accepted(self, ok: str) -> None:
        assert parse_pk(get_resource("misconception"), ok) == ok

    @pytest.mark.parametrize("bad", ["", "a/b", "a b", "한글", "x" * 201, "a\nb", "../etc"])
    def test_string_keys_rejected(self, bad: str) -> None:
        assert parse_pk(get_resource("misconception"), bad) is None


class TestToJsonable:
    def test_scalar_conversions(self) -> None:
        uid = uuid.uuid4()
        assert to_jsonable(uid) == str(uid)
        assert to_jsonable(Decimal("0.25")) == 0.25
        assert to_jsonable(date(2026, 1, 2)) == "2026-01-02"
        assert to_jsonable(datetime(2026, 1, 2, tzinfo=UTC)).startswith("2026-01-02T")  # type: ignore[union-attr]
        assert to_jsonable(ConceptLevel.단원) == "단원"
        assert to_jsonable(None) is None

    def test_containers_are_converted_recursively(self) -> None:
        uid = uuid.uuid4()
        # 집합은 순서가 정의되지 않아 단언에 쓰지 않는다 — 튜플·리스트·중첩 dict만 정확히 비교한다.
        assert to_jsonable({"a": [uid, (1, 2)], "b": {"c": Decimal("1.5")}}) == {
            "a": [str(uid), [1, 2]],
            "b": {"c": 1.5},
        }


class TestProblemMergeValidator:
    """문항 편집은 `schema.Problem` 불변식(본문 보유 금지 등)을 통과해야 한다."""

    @staticmethod
    def _row(source: SourceType) -> Problem:
        return Problem.from_schema(
            ProblemSchema(
                source_type=source,
                curriculum_version=Curriculum.REVISION_2015,
                valid_from_year=2014,
                subject=Subject.미적분,
                unit_codes=["CAL-INT-DEF"],
            )
        )

    def test_own_generated_problem_may_hold_body(self) -> None:
        spec = get_resource("problem")
        assert spec.merged_validator is not None
        spec.merged_validator(self._row(SourceType.자체생성), {"question_text": "본문"})

    def test_copyright_restricted_source_cannot_gain_a_body(self) -> None:
        """평가원 출처에 본문을 심으려는 편집은 스키마 불변식이 거부한다."""
        spec = get_resource("problem")
        assert spec.merged_validator is not None
        with pytest.raises(FieldError) as raised:
            spec.merged_validator(self._row(SourceType.평가원), {"question_text": "복제된 본문"})
        assert raised.value.code == "schema"
