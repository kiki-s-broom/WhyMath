"""Problem Publish Gate 검증 파이프라인·전이 계획·스냅숏 단위 테스트 — EOS-190 (DB 0).

`l3/problem_publish_gate.py`의 순수 층(`snapshot_payload`·`compute_content_hash`·`run_gate`·
`plan_transition`)을 본다. DB 실행 층(`create_draft`·`apply_transition`)과 EOS-47 시도 고정까지
이어지는 관통은 실 PG 통합 테스트(`tests/backend/db/test_problem_version_publish_integration.py`)가 본다.

원칙: 정상 입력 초록은 보호의 증거가 아니다 — 검사마다 **그 검사 하나만 깨뜨린 입력**으로 RED를
확인하고, 같은 입력을 고친 대조군으로 GREEN을 확인한다(대조군이 없으면 "전부 거부"라는 과잉 수정이
통과한다). 이 모듈 고유의 `live_content_current`는 특히 세 갈래(없음·불일치·일치)를 모두 둔다.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from whymath_backend.db.models.problem import Problem
from whymath_backend.l3.problem_publish_gate import (
    PAYLOAD_SCHEMA_VERSION,
    VALIDATOR_BUNDLE_VERSION,
    compute_content_hash,
    plan_transition,
    run_gate,
    snapshot_payload,
)
from whymath_backend.l3.publish_gate import PublishGateError
from whymath_backend.schema.enums import (
    AnswerFormat,
    Curriculum,
    QuestionFormat,
    ReviewStatus,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem_metadata import (
    FIELD_EVIDENCE,
    ProblemMetadataEvidence,
    ProblemMetadataField,
    ProblemSlot,
)
from whymath_backend.schema.problem_version import ProblemVersion, ProblemVersionPayload
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

_NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
_A = TransitionAction


def _payload(question: str = "x + 1 = 3 일 때 x 의 값은?") -> ProblemVersionPayload:
    return ProblemVersionPayload(
        source_type=SourceType.자체생성,
        subject=Subject.공통,
        curriculum_version=Curriculum.REVISION_2022,
        unit_codes=["U-EOS190"],
        question_text=question,
        answer="2",
    )


def _draft(**overrides: object) -> ProblemVersion:
    base: dict[str, object] = {
        "problem_id": uuid.uuid4(),
        "version_no": 1,
        "schema_version": PAYLOAD_SCHEMA_VERSION,
        "status": VersionStatus.DRAFT,
        "governance": VersionGovernance(created_by="author"),
        "payload": _payload(),
    }
    base.update(overrides)
    return ProblemVersion(**base)  # type: ignore[arg-type]


def _walk(version: ProblemVersion, *actions: TransitionAction, **kwargs: object) -> ProblemVersion:
    cur = version
    for action in actions:
        cur = plan_transition(cur, action, actor=f"{action.value}-actor", now=_NOW, **kwargs)  # type: ignore[arg-type]
    return cur


def _approved() -> ProblemVersion:
    return _walk(_draft(), _A.SUBMIT, _A.PASS_REVIEW, _A.APPROVE)


def _live(version: ProblemVersion) -> str:
    """라이브 문항이 판과 같은 내용일 때의 해시 — 호출자가 잠금 후 계산해 넘기는 값."""
    return compute_content_hash(version.payload)


def _complete_evidence(**overrides: object) -> ProblemMetadataEvidence:
    """7필드가 전부 채워진 증거 — 기존 발행 테스트가 **다른 한 가지 원인만** 보게 하는 대조군."""
    base: dict[str, object] = {
        "difficulty": 2.0,
        "answer": "2",
        "solution_text": "양변에서 1을 뺀다.",
        "concept_ids": ("c-1",),
        "skill_ids": ("skill-1",),
        "own_misconception_ids": ("power-rule-step-omitted",),
        "concept_misconception_ids": ("M0671",),
        "verified_hint_count": 1,
        "slots": frozenset({ProblemSlot.REPRESENTATIVE}),
    }
    base.update(overrides)
    return ProblemMetadataEvidence(**base)  # type: ignore[arg-type]


_COMPLETE = _complete_evidence()


# ── content_hash ─────────────────────────────────────────────────────────────
def test_content_hash_is_deterministic_and_content_sensitive() -> None:
    a = compute_content_hash(_payload())
    assert a == compute_content_hash(_payload())
    assert a.startswith("sha256:") and len(a) == len("sha256:") + 64
    assert a != compute_content_hash(_payload("다른 발문"))


def test_content_hash_ignores_jsonb_key_order() -> None:
    """JSONB 왕복은 키 순서를 바꾼다 — 같은 내용이면 같은 해시여야 복원 검증이 성립한다."""
    dumped = _payload().model_dump(mode="json")
    reordered = dict(reversed(list(dumped.items())))
    assert compute_content_hash(_payload()) == compute_content_hash(
        ProblemVersionPayload.model_validate(reordered)
    )


# ── 정상 흐름 ────────────────────────────────────────────────────────────────
def test_full_happy_path_records_governance_and_gate_evidence() -> None:
    approved = _approved()
    published = plan_transition(
        approved,
        _A.PUBLISH,
        actor="publisher",
        live_content_hash=_live(approved),
        metadata_evidence=_COMPLETE,
        now=_NOW,
    )
    assert published.status == VersionStatus.PUBLISHED.value
    assert published.published_at == _NOW
    gov = published.governance
    assert (gov.created_by, gov.reviewed_by, gov.approved_by) == (
        "author",
        "pass_review-actor",
        "approve-actor",
    )
    assert published.integrity.content_hash == compute_content_hash(published.payload)
    assert [r.gate for r in published.qa.records] == [GateKind.QA.value, GateKind.PUBLISH.value]
    last = published.qa.records[-1]
    # 헌법 제5조 ③·R2-03 — 판정자·일시·근거·우회 여부
    assert last.judged_by == "publisher" and last.judged_at == _NOW and last.bypassed is False
    assert {"content_hash", "governance_complete", "qa_record_bound"} <= set(last.checks)
    assert "live_content_current" in last.checks, "발행 기록에 라이브 대조가 근거로 남아야 한다"
    assert "problem_metadata_complete" in last.checks, "발행 기록에 7필드 검사가 근거로 남아야 한다"
    assert published.qa.validator_bundle_version == VALIDATOR_BUNDLE_VERSION
    assert published.qa.qa_status == "PASSED"


def test_transitions_never_change_the_payload() -> None:
    before = _draft()
    after = _walk(before, _A.SUBMIT, _A.PASS_REVIEW)
    assert after.payload == before.payload


# ── live_content_current — 이 모듈 고유 검사 (없음·불일치·일치 세 갈래) ───────
def test_publish_without_live_hash_is_refused_not_passed() -> None:
    """모른다 ≠ 통과 — 대조하지 못하면 발행하지 않는다."""
    with pytest.raises(PublishGateError, match="live_content_current: 라이브 문항 내용을 대조하지"):
        plan_transition(
            _approved(), _A.PUBLISH, actor="publisher", metadata_evidence=_COMPLETE, now=_NOW
        )


def test_publish_refuses_when_live_problem_changed_after_approval() -> None:
    approved = _approved()
    stale = compute_content_hash(_payload("승인 뒤 CMS가 고친 발문"))
    with pytest.raises(PublishGateError, match="live_content_current: 승인 이후 라이브 문항이"):
        plan_transition(
            approved,
            _A.PUBLISH,
            actor="publisher",
            live_content_hash=stale,
            metadata_evidence=_COMPLETE,
            now=_NOW,
        )


def test_publish_passes_when_live_problem_matches_control() -> None:
    """대조군 — 같은 승인본이 라이브 해시만 일치하면 통과한다(과잉 거부가 아님)."""
    approved = _approved()
    published = plan_transition(
        approved,
        _A.PUBLISH,
        actor="publisher",
        live_content_hash=_live(approved),
        metadata_evidence=_COMPLETE,
        now=_NOW,
    )
    assert published.status == VersionStatus.PUBLISHED.value


def test_live_check_applies_to_publish_only_not_to_qa() -> None:
    """QA(approve)는 라이브 해시 없이도 통과한다 — 이 검사가 PUBLISH 전용임을 고정한다."""
    assert _approved().status == VersionStatus.APPROVED.value


# ── 나머지 검사 — 하나씩 깨뜨린다 ─────────────────────────────────────────────
def test_publish_refuses_payload_tampered_after_approval() -> None:
    approved = _approved()
    tampered = approved.model_copy(update={"payload": _payload("승인 뒤 바꿔치기")})
    with pytest.raises(PublishGateError, match="content_hash: 승인 이후 payload가 바뀌었다"):
        plan_transition(
            tampered,
            _A.PUBLISH,
            actor="publisher",
            live_content_hash=_live(tampered),
            metadata_evidence=_COMPLETE,
            now=_NOW,
        )


def test_publish_refuses_forged_approval_without_qa_record() -> None:
    """QA 기록을 지운 위조 승인본 — 각인 해시가 있어도 '그 내용으로 통과한 QA 기록'이 없으면 거부."""
    approved = _approved()
    forged = approved.model_copy(update={"qa": approved.qa.model_copy(update={"records": []})})
    with pytest.raises(PublishGateError, match="qa_record_bound"):
        plan_transition(
            forged,
            _A.PUBLISH,
            actor="publisher",
            live_content_hash=_live(forged),
            metadata_evidence=_COMPLETE,
            now=_NOW,
        )


def test_governance_incomplete_is_refused_at_each_gate() -> None:
    no_reviewer = _walk(_draft(), _A.SUBMIT)  # 검토 통과 없이 IN_QA로 갈 수 없으니 직접 구성한다
    in_qa = no_reviewer.model_copy(update={"status": VersionStatus.IN_QA.value})
    with pytest.raises(PublishGateError, match=r"governance_complete: 비어 있음 \['reviewed_by'\]"):
        plan_transition(in_qa, _A.APPROVE, actor="approver", now=_NOW)


def test_wrong_entity_type_is_refused() -> None:
    """Concept 판이 이 게이트로 발행되는 오배선 차단 — entity_type 하나만 틀리게 한다."""
    in_qa = _walk(_draft(), _A.SUBMIT, _A.PASS_REVIEW).model_copy(update={"entity_type": "Concept"})
    with pytest.raises(PublishGateError, match="entity_type"):
        plan_transition(in_qa, _A.APPROVE, actor="approver", now=_NOW)


def test_bad_schema_version_format_is_refused() -> None:
    in_qa = _walk(_draft(), _A.SUBMIT, _A.PASS_REVIEW).model_copy(
        update={"schema_version": "problem schema 1"}
    )
    with pytest.raises(PublishGateError, match="schema_version_format"):
        plan_transition(in_qa, _A.APPROVE, actor="approver", now=_NOW)


def test_gate_collects_all_failures_in_one_report() -> None:
    """실패를 첫 건에서 멈추지 않는다 — 한 번에 무엇을 고쳐야 하는지 보여야 한다."""
    approved = _approved()
    broken = approved.model_copy(
        update={
            "payload": _payload("바꿔치기"),
            "qa": approved.qa.model_copy(update={"records": []}),
        }
    )
    with pytest.raises(PublishGateError) as info:
        run_gate(broken, GateKind.PUBLISH, live_content_hash=None)
    joined = " | ".join(info.value.failures)
    assert "content_hash" in joined and "qa_record_bound" in joined
    assert "live_content_current" in joined
    assert "problem_metadata_complete" in joined, "증거가 없으면 7필드 검사도 실패로 보고된다"


def test_gate_other_than_qa_publish_is_not_owned_by_this_module() -> None:
    """RESTORE는 rollback과 함께 범위 밖이다 — 조용히 통과시키지 않고 거부한다."""
    with pytest.raises(ValueError, match="QA·PUBLISH 게이트만 소유"):
        run_gate(_approved(), GateKind.RESTORE)


# ── 전이표 조회 — 도착 상태를 이 모듈이 고르지 않는다 ─────────────────────────
def test_undefined_and_compound_only_transitions_are_refused() -> None:
    with pytest.raises(UndefinedTransitionError):
        plan_transition(_draft(), _A.PUBLISH, actor="publisher", now=_NOW)
    published = plan_transition(
        _approved(),
        _A.PUBLISH,
        actor="publisher",
        live_content_hash=_live(_approved()),
        metadata_evidence=_COMPLETE,
        now=_NOW,
    )
    for compound in (_A.ROLLBACK, _A.SUPERSEDE):
        with pytest.raises(CompoundOnlyTransitionError):
            plan_transition(published, compound, actor="x", now=_NOW)


@pytest.mark.parametrize("actor", ["", "   "])
def test_blank_actor_is_refused(actor: str) -> None:
    with pytest.raises(ValueError, match="actor가 비었다"):
        plan_transition(_draft(), _A.SUBMIT, actor=actor, now=_NOW)


# ── problem_metadata_complete — P3-04 7필드 (PUBLISH 전용) ───────────────────
def _publish(evidence: ProblemMetadataEvidence | None) -> ProblemVersion:
    approved = _approved()
    return plan_transition(
        approved,
        _A.PUBLISH,
        actor="publisher",
        live_content_hash=_live(approved),
        metadata_evidence=evidence,
        now=_NOW,
    )


def _blanked(field: ProblemMetadataField, *, unmeasured: bool) -> ProblemMetadataEvidence:
    """대조군에서 한 필드의 증거 속성만 비운다 — 다른 필드는 건드리지 않는다."""
    empty: dict[str, object] = {
        "difficulty": float("nan"),
        "answer": "",
        "solution_text": "",
        "concept_ids": (),
        "skill_ids": (),
        "own_misconception_ids": (),
        "concept_misconception_ids": (),
        "verified_hint_count": 0,
    }
    changes = {attr: (None if unmeasured else empty[attr]) for attr in FIELD_EVIDENCE[field]}
    broken = _complete_evidence(**changes)
    assert broken != _COMPLETE, "주입이 적용되지 않았다 — 대조군과 같은 입력이다"
    return broken


def test_publish_with_all_seven_fields_passes_control() -> None:
    assert _publish(_COMPLETE).status == VersionStatus.PUBLISHED.value


def test_publish_without_metadata_evidence_is_refused_not_passed() -> None:
    """모른다 ≠ 통과 — 7필드를 측정하지 못했으면 발행하지 않는다."""
    with pytest.raises(
        PublishGateError, match="problem_metadata_complete: 7필드를 측정하지 못했다"
    ):
        _publish(None)


@pytest.mark.parametrize("field", list(ProblemMetadataField), ids=lambda f: f.value)
def test_publish_refuses_each_blanked_field_and_only_that_field(
    field: ProblemMetadataField,
) -> None:
    """7필드를 하나씩 비운다 → 7건 모두 거부되고, 거부 사유는 그 필드 하나뿐이다."""
    with pytest.raises(PublishGateError) as info:
        _publish(_blanked(field, unmeasured=False))
    assert info.value.failures == (f"problem_metadata_complete: {field.value}: 비어 있다",)


@pytest.mark.parametrize("field", list(ProblemMetadataField), ids=lambda f: f.value)
def test_publish_refuses_each_unmeasured_field_and_only_that_field(
    field: ProblemMetadataField,
) -> None:
    with pytest.raises(PublishGateError) as info:
        _publish(_blanked(field, unmeasured=True))
    assert info.value.failures == (f"problem_metadata_complete: {field.value}: 측정하지 못했다",)


def test_publish_reports_every_blank_field_in_one_refusal() -> None:
    both = _complete_evidence(answer="", verified_hint_count=0)
    with pytest.raises(PublishGateError) as info:
        _publish(both)
    assert info.value.failures == (
        "problem_metadata_complete: answer: 비어 있다",
        "problem_metadata_complete: hint_strategy: 비어 있다",
    )


def test_trigger_slot_with_only_inherited_misconception_is_refused_at_the_gate() -> None:
    """같은 증거가 다른 슬롯이면 통과(대조) · 오개념 유발 슬롯이면 거부 — 슬롯 규칙이 게이트까지 온다."""
    inherited_only = {"own_misconception_ids": (), "concept_misconception_ids": ("M0671",)}
    assert _publish(_complete_evidence(**inherited_only)).status == VersionStatus.PUBLISHED.value
    trigger = _complete_evidence(
        slots=frozenset({ProblemSlot.MISCONCEPTION_TRIGGER}), **inherited_only
    )
    with pytest.raises(PublishGateError) as info:
        _publish(trigger)
    assert info.value.failures == ("problem_metadata_complete: misconception_signature: 비어 있다",)


def test_missing_metadata_does_not_block_earlier_transitions() -> None:
    """7필드는 발행의 조건이다 — 제출·검토·승인은 증거 없이 진행되고 APPROVED에서 멈춘다."""
    assert _approved().status == VersionStatus.APPROVED.value
    with pytest.raises(PublishGateError):
        _publish(None)


# ── snapshot_payload — 라이브 행 → 판 payload ────────────────────────────────
def _problem(**overrides: object) -> Problem:
    base: dict[str, object] = {
        "problem_id": uuid.uuid4(),
        "source_type": SourceType.자체생성,
        "subject": Subject.공통,
        "curriculum_version": Curriculum.REVISION_2022,
        "valid_from_year": 2022,
        "unit_codes": ["U-EOS190"],
        "question_format": QuestionFormat.단답형,
        "answer_format": AnswerFormat.자연수,
        "points": 3,
        "question_text": "x + 1 = 3 일 때 x 의 값은?",
        "answer": "2",
        "answer_explanation": "양변에서 1을 뺀다.",
        "difficulty_overall": Decimal("2.50"),
    }
    base.update(overrides)
    return Problem(**base)


def test_snapshot_maps_content_fields_and_derives_hashes() -> None:
    snap = snapshot_payload(_problem())
    assert snap.source_type == SourceType.자체생성.value
    assert snap.unit_codes == ["U-EOS190"]
    assert (snap.question_text, snap.answer) == ("x + 1 = 3 일 때 x 의 값은?", "2")
    assert snap.points == 3
    # Numeric(3,2) → Decimal로 읽힌 값을 float로 — 판 계약은 float다.
    assert snap.difficulty_at_publish == 2.5 and isinstance(snap.difficulty_at_publish, float)
    assert snap.stem_hash is not None and snap.stem_hash.startswith("sha256:")
    assert snap.answer_hash is not None and snap.answer_hash != snap.stem_hash


def test_snapshot_does_not_invent_hashes_for_missing_text() -> None:
    snap = snapshot_payload(_problem(question_text=None, answer=None, difficulty_overall=None))
    assert snap.stem_hash is None and snap.answer_hash is None
    assert snap.difficulty_at_publish is None


def test_snapshot_hash_changes_with_content_but_not_with_review_axis() -> None:
    """판은 *내용* 축이다 — 검수 상태가 바뀌어도 해시는 그대로여야 두 축이 섞이지 않는다.

    (노출은 `review_status`·저작권이 소유한다. 이 해시가 검수 상태에 흔들리면 격리/해제가
    발행본을 stale로 만든다.)
    """
    base = compute_content_hash(snapshot_payload(_problem(review_status=ReviewStatus.approved)))
    same = compute_content_hash(snapshot_payload(_problem(review_status=ReviewStatus.quarantined)))
    edited = compute_content_hash(snapshot_payload(_problem(answer="3", review_status=None)))
    assert base == same
    assert base != edited


def test_snapshot_refuses_body_for_metadata_only_source() -> None:
    """저작권 불변식은 판 경로에도 걸린다 — 평가원 출처 행에 본문이 남아 있으면 스냅숏이 거부한다."""
    with pytest.raises(ValidationError, match="저작권 교정 위반"):
        snapshot_payload(_problem(source_type=SourceType.평가원))
    # 대조군 — 같은 출처라도 본문이 비어 있으면 스냅숏된다.
    ok = snapshot_payload(
        _problem(source_type=SourceType.평가원, question_text=None, answer_explanation=None)
    )
    assert ok.question_text is None


def test_snapshot_of_live_row_equals_payload_the_gate_would_compare() -> None:
    """같은 행에서 두 번 만든 스냅숏의 해시가 같다 — live_content_current가 거짓 불일치를 내지 않는다."""
    row = _problem()
    assert compute_content_hash(snapshot_payload(row)) == compute_content_hash(
        snapshot_payload(row)
    )
