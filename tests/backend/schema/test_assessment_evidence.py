"""EOS-12 채점 Evidence 계약 — 순수 계층(schema)의 선택 규칙·3상태·계약 집행.

이 파일이 지키는 것은 넷이다.

① **모델 B 선택 규칙** — 정답은 합동 지지, 오답은 PRIMARY 책임귀속(없으면 TESTED 폴백).
   TESTED가 오답에서 선택되면 "책임귀속이 모호한 개념에 거짓 약점 신호"가 되므로 그 경계가
   핵심이다.
② **귀속 근거 보존** — 왜 그 대상이 선택됐는지(`AttributionBasis`)가 증거에 남는가. 숙달
   delta만 반환하던 현행이 잃고 있던 바로 그 축이다.
③ **0건의 의미 3상태** — 비었는지, 보았는데 없는지, 보지 않았는지. 셋이 한 글자로 접히면
   미측정이 무활동으로 읽힌다.
④ **계약 집행** — 게이트 미통과 후보 차단(LLM·매처 비권위)과 scan↔건수 정합. 조용히
   통과시키지 않고 `ValueError`로 거부하는지 본다.

DB·계층 의존 0 — `schema`는 최하위라 여기서도 순수 함수만 부른다.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from whymath_backend.schema.assessment_evidence import (
    AssessmentEvidence,
    AttributionBasis,
    ConceptEvidence,
    EvidenceDirection,
    EvidenceKindState,
    MisconceptionCandidate,
    MisconceptionScan,
    SkillEvidence,
    build_assessment_evidence,
    select_concept_evidence,
)
from whymath_backend.schema.enums import ConceptRole

_LEARNER = uuid.uuid4()
_PROBLEM = uuid.uuid4()
_P1, _P2 = uuid.uuid4(), uuid.uuid4()
_T1, _T2 = uuid.uuid4(), uuid.uuid4()
_NOW = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)


def _gated(mid: str = "M-001", confidence: float = 0.9) -> MisconceptionCandidate:
    return MisconceptionCandidate(misconception_id=mid, confidence=confidence, gate_passed=True)


def _build(**overrides: object) -> AssessmentEvidence:
    kwargs: dict[str, object] = {
        "learner_id": _LEARNER,
        "problem_id": _PROBLEM,
        "correct": True,
        "observed_at": _NOW,
        "concept_evidence": (),
        "skill_evidence": (),
        "concept_mapping_present": True,
        "skill_bridge_present": True,
    }
    kwargs.update(overrides)
    return build_assessment_evidence(**kwargs)  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────────────
# ① 모델 B 선택 규칙
# ──────────────────────────────────────────────────────────────────────────
class TestConceptSelection:
    def test_correct_supports_every_assessed_concept(self) -> None:
        """정답 = 합동 증거 — PRIMARY와 TESTED가 함께 작동했다는 지지."""
        ev = select_concept_evidence(correct=True, primary_ids=[_P1], tested_ids=[_T1, _T2])
        assert [e.concept_id for e in ev] == [_P1, _T1, _T2]
        assert {e.direction for e in ev} == {EvidenceDirection.SUPPORTING}
        assert {e.attribution for e in ev} == {AttributionBasis.JOINT_SUPPORT}

    def test_wrong_answer_attributes_only_to_primary(self) -> None:
        """오답에 TESTED가 섞이면 책임귀속이 모호한 개념에 거짓 약점 신호가 간다."""
        ev = select_concept_evidence(correct=False, primary_ids=[_P1], tested_ids=[_T1, _T2])
        assert [e.concept_id for e in ev] == [_P1]
        assert ev[0].direction is EvidenceDirection.REFUTING
        assert ev[0].attribution is AttributionBasis.PRIMARY_ATTRIBUTION

    def test_wrong_answer_falls_back_to_tested_only_when_primary_missing(self) -> None:
        """PRIMARY 미매핑 퇴화 문항 — 기존 writer의 폴백을 승계하되 근거를 구분해 남긴다."""
        ev = select_concept_evidence(correct=False, primary_ids=[], tested_ids=[_T1])
        assert [e.concept_id for e in ev] == [_T1]
        assert ev[0].attribution is AttributionBasis.TESTED_FALLBACK
        assert ev[0].role is ConceptRole.TESTED

    def test_unmapped_problem_yields_no_evidence(self) -> None:
        assert select_concept_evidence(correct=False, primary_ids=[], tested_ids=[]) == ()
        assert select_concept_evidence(correct=True, primary_ids=[], tested_ids=[]) == ()

    def test_duplicate_concept_across_roles_is_recorded_once(self) -> None:
        """같은 개념이 두 역할로 실려도 증거는 1건 — 중복이 합동 증거를 부풀리면 안 된다."""
        ev = select_concept_evidence(correct=True, primary_ids=[_P1], tested_ids=[_P1, _T1])
        assert [e.concept_id for e in ev] == [_P1, _T1]
        assert ev[0].role is ConceptRole.PRIMARY  # 먼저 온 역할이 남는다

    def test_input_order_is_preserved(self) -> None:
        """순서가 흔들리면 같은 채점이 실행마다 다른 증거를 낸다."""
        ev = select_concept_evidence(correct=True, primary_ids=[_P2, _P1], tested_ids=[])
        assert [e.concept_id for e in ev] == [_P2, _P1]


# ──────────────────────────────────────────────────────────────────────────
# ③ 0건의 의미 3상태 (작동 비율)
# ──────────────────────────────────────────────────────────────────────────
class TestCoverageThreeState:
    def test_filled_when_evidence_present(self) -> None:
        ev = _build(
            concept_evidence=select_concept_evidence(
                correct=True, primary_ids=[_P1], tested_ids=[]
            ),
            skill_evidence=(
                SkillEvidence(
                    skill_id="skill.slope",
                    direction=EvidenceDirection.SUPPORTING,
                    resolved_from=(_P1,),
                ),
            ),
            possible_misconceptions=(_gated(),),
            misconception_scan=MisconceptionScan.RAN_WITH_CANDIDATES,
        )
        assert ev.coverage.concept is EvidenceKindState.FILLED
        assert ev.coverage.skill is EvidenceKindState.FILLED
        assert ev.coverage.misconception is EvidenceKindState.FILLED
        assert ev.coverage.filled_kinds == 3
        assert ev.coverage.unmeasured_kinds == ()

    def test_measured_empty_differs_from_not_measured(self) -> None:
        """핵심 — 같은 0건이 두 가지 다른 사실을 뜻한다."""
        measured = _build(concept_mapping_present=True)
        unmeasured = _build(concept_mapping_present=False)
        assert measured.coverage.concept is EvidenceKindState.EMPTY_MEASURED
        assert unmeasured.coverage.concept is EvidenceKindState.NOT_MEASURED
        assert measured.coverage.concept_count == unmeasured.coverage.concept_count == 0
        # 건수만 보면 구분이 안 된다 — 상태 축이 있어야 구분된다.
        assert measured.coverage.concept is not unmeasured.coverage.concept

    def test_not_run_scan_reports_misconception_as_not_measured(self) -> None:
        """오개념 0건이 "없었다"로 읽히면 안 된다 — 이 경로는 보지 않았다."""
        ev = _build(misconception_scan=MisconceptionScan.NOT_RUN)
        assert ev.coverage.misconception is EvidenceKindState.NOT_MEASURED
        assert "misconception" in ev.coverage.unmeasured_kinds

    def test_ran_no_candidate_is_a_measured_zero(self) -> None:
        """게이트가 후보를 비운 것은 *측정된* 0건이다(확실한 후보 없음)."""
        ev = _build(misconception_scan=MisconceptionScan.RAN_NO_CANDIDATE)
        assert ev.coverage.misconception is EvidenceKindState.EMPTY_MEASURED
        assert "misconception" not in ev.coverage.unmeasured_kinds

    def test_filled_kinds_counts_only_filled(self) -> None:
        ev = _build(
            concept_evidence=select_concept_evidence(
                correct=True, primary_ids=[_P1], tested_ids=[]
            ),
            skill_bridge_present=False,
        )
        assert ev.coverage.filled_kinds == 1
        assert set(ev.coverage.unmeasured_kinds) == {"skill", "misconception"}


# ──────────────────────────────────────────────────────────────────────────
# ④ 계약 집행 — 조용히 통과시키지 않는다
# ──────────────────────────────────────────────────────────────────────────
class TestContractEnforcement:
    def test_ungated_misconception_candidate_is_rejected(self) -> None:
        """LLM·매처 비권위 — 게이트를 건너뛴 후보가 증거에 실리면 확정을 매처가 한 셈이 된다."""
        ungated = MisconceptionCandidate(
            misconception_id="M-999", confidence=0.99, gate_passed=False
        )
        with pytest.raises(ValueError, match="게이트를 통과하지 않은"):
            _build(
                possible_misconceptions=(ungated,),
                misconception_scan=MisconceptionScan.RAN_WITH_CANDIDATES,
            )

    def test_not_run_with_candidates_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="not_run"):
            _build(
                possible_misconceptions=(_gated(),),
                misconception_scan=MisconceptionScan.NOT_RUN,
            )

    def test_ran_no_candidate_with_candidates_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="ran_no_candidate"):
            _build(
                possible_misconceptions=(_gated(),),
                misconception_scan=MisconceptionScan.RAN_NO_CANDIDATE,
            )

    def test_ran_with_candidates_but_empty_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="ran_with_candidates"):
            _build(misconception_scan=MisconceptionScan.RAN_WITH_CANDIDATES)

    def test_confidence_outside_unit_interval_is_rejected(self) -> None:
        with pytest.raises(Exception):  # noqa: B017 — pydantic ValidationError(버전 무관)
            MisconceptionCandidate(misconception_id="M-1", confidence=1.5, gate_passed=True)


# ──────────────────────────────────────────────────────────────────────────
# ② 증거는 관측이지 상태가 아니다 (구조적 차단)
# ──────────────────────────────────────────────────────────────────────────
class TestEvidenceIsObservationNotState:
    def test_envelope_has_no_mastery_or_delta_slot(self) -> None:
        """추정기를 BKT→DKT로 갈아 끼워도 증거 모양이 그대로여야 한다 — 값이 없는 것이 의도다."""
        forbidden = {"mastery", "delta", "mastery_delta", "new_mastery", "score", "sample_size"}
        assert not (forbidden & set(AssessmentEvidence.model_fields))

    def test_envelope_rejects_unknown_fields(self) -> None:
        with pytest.raises(Exception):  # noqa: B017 — pydantic ValidationError
            AssessmentEvidence(
                learner_id=_LEARNER,
                problem_id=_PROBLEM,
                correct=True,
                observed_at=_NOW,
                coverage=_build().coverage,
                mastery_delta=0.1,  # type: ignore[call-arg]
            )

    def test_skill_evidence_requires_its_source_concepts(self) -> None:
        """출처 없는 스킬 증거는 재구성 불가능한 주장이다."""
        ev = SkillEvidence(
            skill_id="skill.slope", direction=EvidenceDirection.REFUTING, resolved_from=(_P1,)
        )
        assert ev.resolved_from == (_P1,)

    def test_evidence_is_frozen(self) -> None:
        """조립 후 변형되면 응답과 판정 근거가 갈라진다."""
        ev = _build()
        with pytest.raises(Exception):  # noqa: B017 — pydantic ValidationError
            ev.correct = False  # type: ignore[misc]

    def test_concept_evidence_is_frozen(self) -> None:
        one = ConceptEvidence(
            concept_id=_P1,
            role=ConceptRole.PRIMARY,
            direction=EvidenceDirection.SUPPORTING,
            attribution=AttributionBasis.JOINT_SUPPORT,
        )
        with pytest.raises(Exception):  # noqa: B017 — pydantic ValidationError
            one.concept_id = _P2  # type: ignore[misc]
