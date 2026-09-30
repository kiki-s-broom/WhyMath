"""Publish Gate 검증 파이프라인·전이 계획 단위 테스트 — EOS-50 ①⑩ (DB 0).

`l3/publish_gate.py`의 순수 층(`compute_content_hash`·`run_gate`·`plan_transition`)을 본다.
DB 실행 층(`create_draft`·`apply_transition`·`rollback`)은 실 PG 통합 테스트
(`test_publish_gate_integration.py`)가 본다.

원칙: 정상 입력 초록은 보호의 증거가 아니다 — 게이트마다 **검사 하나씩을 깨뜨린 입력**으로 RED를
확인하고, 같은 입력을 고친 대조군으로 GREEN을 확인한다.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from whymath_backend.l3.publish_gate import (
    VALIDATOR_BUNDLE_VERSION,
    PublishGateError,
    compute_content_hash,
    plan_transition,
    run_gate,
)
from whymath_backend.schema.concept_version import ConceptVersion, ConceptVersionPayload
from whymath_backend.schema.enums import ConceptLevel
from whymath_backend.schema.version_header import (
    GateKind,
    TransitionAction,
    VersionGovernance,
    VersionStatus,
)
from whymath_backend.schema.version_lifecycle import (
    CompoundOnlyTransitionError,
    UndefinedTransitionError,
)

_NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


def _payload(name: str = "이차함수의 꼭짓점") -> ConceptVersionPayload:
    return ConceptVersionPayload(name_ko=name, level=ConceptLevel.세부개념, aliases=["a", "b"])


def _draft(**overrides: object) -> ConceptVersion:
    base: dict[str, object] = {
        "concept_id": "HIGH-EOS50-001",
        "version_no": 1,
        "schema_version": "concept-payload@1",
        "status": VersionStatus.DRAFT,
        "governance": VersionGovernance(created_by="author"),
        "payload": _payload(),
    }
    base.update(overrides)
    return ConceptVersion(**base)  # type: ignore[arg-type]


def _walk(version: ConceptVersion, *actions: TransitionAction) -> ConceptVersion:
    cur = version
    for action in actions:
        cur = plan_transition(cur, action, actor=f"{action.value}-actor", now=_NOW)
    return cur


def _approved() -> ConceptVersion:
    return _walk(
        _draft(),
        TransitionAction.SUBMIT,
        TransitionAction.PASS_REVIEW,
        TransitionAction.APPROVE,
    )


# ── content_hash ─────────────────────────────────────────────────────────────
def test_content_hash_is_deterministic_and_content_sensitive() -> None:
    a = compute_content_hash(_payload())
    assert a == compute_content_hash(_payload())
    assert a.startswith("sha256:") and len(a) == len("sha256:") + 64
    assert a != compute_content_hash(_payload("다른 이름"))


def test_content_hash_ignores_jsonb_key_order() -> None:
    """JSONB 왕복은 키 순서를 바꾼다 — 같은 내용이면 같은 해시여야 복원 검증이 성립한다."""
    dumped = _payload().model_dump(mode="json")
    reordered = dict(reversed(list(dumped.items())))
    assert compute_content_hash(_payload()) == compute_content_hash(
        ConceptVersionPayload.model_validate(reordered)
    )


# ── 정상 흐름 ────────────────────────────────────────────────────────────────
def test_full_happy_path_records_governance_and_gate_evidence() -> None:
    published = _walk(_approved(), TransitionAction.PUBLISH)
    assert published.status == VersionStatus.PUBLISHED.value
    assert published.published_at == _NOW
    gov = published.governance
    assert (gov.created_by, gov.reviewed_by, gov.approved_by) == (
        "author",
        "pass_review-actor",
        "approve-actor",
    )
    assert published.integrity.content_hash == compute_content_hash(published.payload)
    gates = [r.gate for r in published.qa.records]
    assert gates == [GateKind.QA.value, GateKind.PUBLISH.value]
    last = published.qa.records[-1]
    # 헌법 제5조 ③·R2-03 — 판정자·일시·근거·우회 여부
    assert last.judged_by == "publish-actor"
    assert last.judged_at == _NOW
    assert "content_hash" in last.checks and "governance_complete" in last.checks
    assert last.content_hash == published.integrity.content_hash
    assert last.bypassed is False
    assert published.qa.validator_bundle_version == VALIDATOR_BUNDLE_VERSION
    assert published.qa.qa_status == "PASSED" and published.qa.qa_run_id == last.qa_run_id


def test_transitions_never_change_the_payload() -> None:
    before = _draft()
    after = _walk(before, TransitionAction.SUBMIT, TransitionAction.PASS_REVIEW)
    assert after.payload == before.payload


# ── ⑩ 미정의 전이·미승인 Publish ─────────────────────────────────────────────
@pytest.mark.parametrize(
    "setup",
    [
        (),  # DRAFT
        (TransitionAction.SUBMIT,),  # IN_REVIEW
        (TransitionAction.SUBMIT, TransitionAction.PASS_REVIEW),  # IN_QA(승인 전)
    ],
    ids=["from-draft", "from-in-review", "from-in-qa"],
)
def test_unapproved_publish_is_red(setup: tuple[TransitionAction, ...]) -> None:
    version = _walk(_draft(), *setup)
    with pytest.raises(UndefinedTransitionError):
        plan_transition(version, TransitionAction.PUBLISH, actor="x", now=_NOW)


def test_compound_only_transition_is_refused_directly() -> None:
    published = _walk(_approved(), TransitionAction.PUBLISH)
    with pytest.raises(CompoundOnlyTransitionError):
        plan_transition(published, TransitionAction.ROLLBACK, actor="x", now=_NOW)


def test_empty_actor_is_refused() -> None:
    with pytest.raises(ValueError, match="actor"):
        plan_transition(_draft(), TransitionAction.SUBMIT, actor="  ", now=_NOW)


def test_approved_row_forged_without_approval_cannot_publish() -> None:
    """상태만 APPROVED로 만든 행(승인 간선을 건너뜀) — 게이트가 승인자·해시·QA 기록 부재로 거부."""
    forged = _draft(status=VersionStatus.APPROVED)
    with pytest.raises(PublishGateError) as info:
        plan_transition(forged, TransitionAction.PUBLISH, actor="x", now=_NOW)
    text = " ".join(info.value.failures)
    assert "governance_complete" in text
    assert "content_hash" in text
    assert "qa_record_bound" in text


# ── ① 게이트 검사 — 하나씩 깨뜨려 RED, 대조군 GREEN ───────────────────────────
def test_payload_changed_after_approval_blocks_publish() -> None:
    approved = _approved()
    tampered = approved.model_copy(update={"payload": _payload("승인 후 바뀐 이름")})
    with pytest.raises(PublishGateError, match="content_hash"):
        plan_transition(tampered, TransitionAction.PUBLISH, actor="x", now=_NOW)
    # 대조군: 바꾸지 않은 판은 통과
    assert plan_transition(approved, TransitionAction.PUBLISH, actor="x", now=_NOW).status == (
        VersionStatus.PUBLISHED.value
    )


def test_missing_approver_blocks_publish() -> None:
    approved = _approved()
    stripped = approved.model_copy(
        update={"governance": approved.governance.model_copy(update={"approved_by": None})}
    )
    with pytest.raises(PublishGateError, match="governance_complete"):
        plan_transition(stripped, TransitionAction.PUBLISH, actor="x", now=_NOW)


def test_missing_reviewer_blocks_qa_gate() -> None:
    in_qa = _walk(_draft(), TransitionAction.SUBMIT, TransitionAction.PASS_REVIEW)
    stripped = in_qa.model_copy(
        update={"governance": in_qa.governance.model_copy(update={"reviewed_by": ""})}
    )
    with pytest.raises(PublishGateError, match="governance_complete"):
        plan_transition(stripped, TransitionAction.APPROVE, actor="x", now=_NOW)


def test_bad_schema_version_blocks_gate() -> None:
    in_qa = _walk(
        _draft(schema_version="v1 draft"), TransitionAction.SUBMIT, TransitionAction.PASS_REVIEW
    )
    with pytest.raises(PublishGateError, match="schema_version_format"):
        plan_transition(in_qa, TransitionAction.APPROVE, actor="x", now=_NOW)


def test_wrong_entity_type_blocks_gate() -> None:
    in_qa = _walk(
        _draft(entity_type="Problem"), TransitionAction.SUBMIT, TransitionAction.PASS_REVIEW
    )
    with pytest.raises(PublishGateError, match="entity_type"):
        plan_transition(in_qa, TransitionAction.APPROVE, actor="x", now=_NOW)


def test_schema_invalid_snapshot_blocks_gate() -> None:
    """model_copy로 계약 밖 값을 넣은 판 — 게이트의 재검증이 잡는다(검증 우회 차단)."""
    in_qa = _walk(_draft(), TransitionAction.SUBMIT, TransitionAction.PASS_REVIEW)
    broken = in_qa.model_copy(update={"version_no": 0})  # ge=1 위반
    with pytest.raises(PublishGateError, match="schema_valid"):
        plan_transition(broken, TransitionAction.APPROVE, actor="x", now=_NOW)


def test_qa_record_must_bind_the_current_content() -> None:
    """QA 기록이 있어도 *다른 내용*의 해시면 발행 불가 — 각인까지 함께 바꾼 위조를 잡는다."""
    approved = _approved()
    new_payload = _payload("다른 내용")
    forged = approved.model_copy(
        update={
            "payload": new_payload,
            "integrity": approved.integrity.model_copy(
                update={"content_hash": compute_content_hash(new_payload)}
            ),
        }
    )
    with pytest.raises(PublishGateError, match="qa_record_bound"):
        plan_transition(forged, TransitionAction.PUBLISH, actor="x", now=_NOW)


def test_restore_requires_previous_publication() -> None:
    """발행된 적 없는 판(published_at=None)은 RESTORE 게이트를 못 넘는다."""
    approved = _approved()
    deprecated_never_published = approved.model_copy(
        update={"status": VersionStatus.DEPRECATED.value}
    )
    with pytest.raises(PublishGateError, match="previously_published"):
        plan_transition(
            deprecated_never_published,
            TransitionAction.RESTORE,
            actor="x",
            now=_NOW,
            allow_compound=True,
        )


def test_gate_reports_all_failures_at_once() -> None:
    forged = _draft(status=VersionStatus.APPROVED, schema_version="bad")
    with pytest.raises(PublishGateError) as info:
        run_gate(forged, GateKind.PUBLISH)
    assert len(info.value.failures) >= 4


def test_qa_regate_restamps_hash_after_edit_cycle() -> None:
    """QA 불합격 → 초안에서 수정 → 재승인하면 새 내용의 해시로 다시 각인된다."""
    first = _walk(_draft(), TransitionAction.SUBMIT, TransitionAction.PASS_REVIEW)
    back = plan_transition(first, TransitionAction.FAIL_QA, actor="qa", now=_NOW)
    edited = back.model_copy(update={"payload": _payload("고친 이름")})
    reapproved = _walk(
        edited, TransitionAction.SUBMIT, TransitionAction.PASS_REVIEW, TransitionAction.APPROVE
    )
    assert reapproved.integrity.content_hash == compute_content_hash(_payload("고친 이름"))


def test_gate_run_ids_are_unique_per_run() -> None:
    assert _approved().qa.qa_run_id != _approved().qa.qa_run_id
