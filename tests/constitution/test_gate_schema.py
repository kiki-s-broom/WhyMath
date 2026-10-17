"""R2-03 (헌법 제5조 ③) — 게이트 기록에는 판정자·일시·근거·우회 여부가 있어야 한다.

대상: `GateRecord`(schema/version_header.py) — 버전 전이 게이트(QA·PUBLISH·RESTORE)의 통과 기록.
이 파일은 두 겹으로 지킨다.
  ① 모델 계약 — 필수 필드 5개(judged_by·judged_at·checks·content_hash·bypassed)가 *모델에* 있고,
     판정자·일시·근거는 생략하면 거부된다(기본값으로 조용히 채워지지 않는다).
  ② 실제 생성 경로 — `plan_transition`이 만든 기록이 네 요건을 *채워서* 내는가(필드가 있어도
     비어 있으면 요건 위반이다).

범위(정직한 한계): 사람 검수 이벤트(`ReviewTimerEvent`)·기계 사유 큐(`ReviewQueueEntry`)는
'게이트 기록'으로 세지 않았다 — 판정 기록이 아니거나 우회 개념이 없다. 그 판단은 Kiki 몫이고,
포함하기로 하면 `GATE_RECORD_MODELS`에 더한다. `bypassed`는 지금 어느 경로에서도 True가 되지
않는다(제9조 ②) — 필드의 *존재*는 지키지만 우회가 생겼을 때의 기록은 이 테스트가 보지 못한다.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import BaseModel, ValidationError, create_model

from whymath_backend.l3.publish_gate import plan_transition
from whymath_backend.schema.concept_version import ConceptVersion, ConceptVersionPayload
from whymath_backend.schema.enums import ConceptLevel
from whymath_backend.schema.version_header import (
    GateKind,
    GateRecord,
    TransitionAction,
    VersionGovernance,
    VersionStatus,
)

# 헌법이 말하는 4요건 → 이 저장소 필드. 근거는 두 필드(검사 이름·대상 해시)를 모두 요구한다.
REQUIRED_FIELDS = {
    "판정자": ("judged_by",),
    "일시": ("judged_at",),
    "근거": ("checks", "content_hash"),
    "우회 여부": ("bypassed",),
}
# 생략하면 거부돼야 하는 필드(우회 여부는 기본값 False가 정책이므로 제외).
MUST_BE_SUPPLIED = ("judged_by", "judged_at", "checks", "content_hash")
GATE_RECORD_MODELS: tuple[type[BaseModel], ...] = (GateRecord,)

_NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def missing_requirements(model: type[BaseModel]) -> list[str]:
    """모델에 없는 요건 필드 이름들(빈 리스트면 충족)."""
    return [
        f"{family}:{name}"
        for family, names in REQUIRED_FIELDS.items()
        for name in names
        if name not in model.model_fields
    ]


def _valid_kwargs() -> dict[str, object]:
    return {
        "gate": GateKind.QA,
        "action": TransitionAction.APPROVE,
        "judged_by": "reviewer",
        "judged_at": _NOW,
        "checks": ["content_hash"],
        "content_hash": "sha256:" + "0" * 64,
        "validator_bundle_version": "v1",
        "qa_run_id": "QA-test",
    }


def _approved_then_published() -> ConceptVersion:
    cur = ConceptVersion(
        concept_id="HIGH-R203-001",
        version_no=1,
        schema_version="concept-payload@1",
        status=VersionStatus.DRAFT,
        governance=VersionGovernance(created_by="author"),
        payload=ConceptVersionPayload(
            name_ko="이차함수의 꼭짓점", level=ConceptLevel.세부개념, aliases=["a", "b"]
        ),
    )
    for action in (
        TransitionAction.SUBMIT,
        TransitionAction.PASS_REVIEW,
        TransitionAction.APPROVE,
        TransitionAction.PUBLISH,
    ):
        cur = plan_transition(cur, action, actor=f"{action.value}-actor", now=_NOW)
    return cur


# ── ① 모델 계약 ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("model", GATE_RECORD_MODELS, ids=lambda m: m.__name__)
def test_gate_record_models_have_all_four_requirements(model: type[BaseModel]) -> None:
    assert missing_requirements(model) == []


def test_registry_is_not_empty() -> None:
    """스캔 0건은 통과가 아니다 — 대상 모델이 하나도 없으면 위 검사는 공허하다."""
    assert GATE_RECORD_MODELS


@pytest.mark.parametrize("drop", sorted({n for names in REQUIRED_FIELDS.values() for n in names}))
def test_dropping_any_required_field_is_detected(drop: str) -> None:
    """변별력 — 필드 하나를 뺀 모델을 같은 검사 함수에 넣으면 정확히 그 필드가 지목된다."""
    kept = {k: (v.annotation, v) for k, v in GateRecord.model_fields.items() if k != drop}
    broken = create_model("BrokenGateRecord", **kept)  # type: ignore[call-overload]
    missing = missing_requirements(broken)
    assert len(missing) == 1 and missing[0].endswith(f":{drop}")


def test_control_valid_record_builds() -> None:
    rec = GateRecord(**_valid_kwargs())  # type: ignore[arg-type]
    assert rec.bypassed is False and rec.verdict == "PASSED"


@pytest.mark.parametrize("field", MUST_BE_SUPPLIED)
def test_omitting_a_required_field_is_rejected(field: str) -> None:
    kwargs = _valid_kwargs()
    del kwargs[field]
    with pytest.raises(ValidationError):
        GateRecord(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "empty"), [("judged_by", ""), ("judged_by", "   "), ("checks", [])]
)
def test_empty_evidence_is_rejected(field: str, empty: object) -> None:
    kwargs = _valid_kwargs()
    kwargs[field] = empty
    with pytest.raises(ValidationError):
        GateRecord(**kwargs)  # type: ignore[arg-type]


def test_bypassed_is_a_bool_defaulting_to_false() -> None:
    info = GateRecord.model_fields["bypassed"]
    assert info.annotation is bool and info.default is False


# ── ② 실제 생성 경로 ─────────────────────────────────────────────────────────
def test_real_transition_path_fills_every_requirement() -> None:
    published = _approved_then_published()
    records = published.qa.records
    assert [r.gate for r in records] == [GateKind.QA.value, GateKind.PUBLISH.value]
    for rec in records:
        assert rec.judged_by.strip(), "판정자가 비었다"
        assert rec.judged_at.tzinfo is not None, "일시가 tz 없는 시각이다"
        assert rec.checks and all(c.strip() for c in rec.checks), "근거(검사 이름)가 비었다"
        assert rec.content_hash.startswith("sha256:"), "근거(대상 해시)가 비었다"
        assert rec.bypassed is False


def test_judge_is_the_actor_who_requested_the_transition() -> None:
    """판정자 필드가 상수가 아니라 전이를 요청한 행위자를 담는다."""
    published = _approved_then_published()
    assert [r.judged_by for r in published.qa.records] == ["approve-actor", "publish-actor"]
