"""ProblemVersion Pydantic 계약 단위테스트 — ARCH-31.

검증:
  ① payload의 **저작권 불변식** — 평가원/EBS/교과서 출처는 버전 스냅숏을 통해서도 본문을 가질
     수 없다(버전 경로가 `schema.Problem` 불변식의 우회로가 되지 않음). 대조군(자체생성 허용) 동반.
  ② **공통 헤더 계약 공유** — `VersionHeader`의 필드가 `ProblemVersion`·`ConceptVersion` 양쪽에
     같은 타입으로 존재한다(도메인마다 제각각 버전 시스템을 만들지 않는다 — 44 §6.1 Hybrid).
  ③ Principle 1 — 엔티티 ID(`problem_id`)와 버전 ID(`version_id`)가 별개다.
  ④ `identity_id`를 복제하지 않는다(계열 소속의 정본은 `problem.identity_id` 하나).
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from whymath_backend.schema.concept_version import ConceptVersion
from whymath_backend.schema.enums import Curriculum, SourceType, Subject
from whymath_backend.schema.problem_version import ProblemVersion, ProblemVersionPayload
from whymath_backend.schema.version_header import VersionHeader, VersionStatus


def _payload(**overrides: object) -> ProblemVersionPayload:
    base: dict[str, object] = {
        "source_type": SourceType.자체생성,
        "subject": Subject.공통,
        "curriculum_version": Curriculum.REVISION_2022,
        "unit_codes": ["U-1"],
    }
    base.update(overrides)
    return ProblemVersionPayload(**base)  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────────────
# ① 저작권 불변식 — 버전 경로 재집행
# ──────────────────────────────────────────────────────────────────────────
class TestPayloadCopyrightInvariant:
    @pytest.mark.parametrize("source", [SourceType.평가원, SourceType.EBS, SourceType.교과서])
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("question_text", "x+1=2 일 때 x의 값은?"),
            ("answer_explanation", "양변에서 1을 뺀다."),
            ("choices", ["1", "2", "3"]),
        ],
    )
    def test_metadata_only_source_cannot_carry_body(
        self, source: SourceType, field: str, value: object
    ) -> None:
        with pytest.raises(ValidationError, match="저작권 교정 위반"):
            _payload(source_type=source, **{field: value})

    @pytest.mark.parametrize("source", [SourceType.평가원, SourceType.EBS, SourceType.교과서])
    def test_metadata_only_source_without_body_is_allowed(self, source: SourceType) -> None:
        """대조군 — 본문이 비어 있으면 통과한다(검증기가 출처 전체를 막는 것이 아니다)."""
        p = _payload(source_type=source, question_text="", choices=[], answer_explanation=None)
        assert p.question_text == ""

    def test_self_generated_source_may_carry_body(self) -> None:
        """대조군 — 자체생성은 본문 보유 허용(실제 서빙 문항이 여기 해당)."""
        p = _payload(
            question_text="2x=4", choices=["1", "2"], answer="2", answer_explanation="해설"
        )
        assert p.answer == "2"

    def test_difficulty_bounds(self) -> None:
        assert _payload(difficulty_at_publish=1.0).difficulty_at_publish == 1.0
        assert _payload(difficulty_at_publish=5.0).difficulty_at_publish == 5.0
        for bad in (0.9, 5.1):
            with pytest.raises(ValidationError):
                _payload(difficulty_at_publish=bad)

    def test_extra_field_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            _payload(identity_id=str(uuid.uuid4()))  # identity_id 복제 금지(④)


# ──────────────────────────────────────────────────────────────────────────
# ②③④ 헤더 계약 공유 · Principle 1 · identity_id 비복제
# ──────────────────────────────────────────────────────────────────────────
class TestHeaderContractSharing:
    # entity_id는 도메인이 자기 FK 이름으로 구현한다(Concept=concept_id 문자열, Problem=problem_id UUID).
    _ENTITY_FK = {"entity_id"}

    @pytest.mark.parametrize("model", [ProblemVersion, ConceptVersion])
    def test_every_header_field_exists_with_same_type(self, model: type) -> None:
        missing = []
        for name, info in VersionHeader.model_fields.items():
            if name in self._ENTITY_FK:
                continue
            got = model.model_fields.get(name)
            if got is None or got.annotation != info.annotation:
                missing.append(name)
        assert missing == [], f"{model.__name__}이 VersionHeader 계약과 어긋난 필드: {missing}"

    def test_problem_version_extra_fields_are_only_the_domain_ones(self) -> None:
        extra = set(ProblemVersion.model_fields) - set(VersionHeader.model_fields)
        assert extra == {"problem_id", "payload"}

    def test_entity_id_and_version_id_are_distinct_uuids(self) -> None:
        pid = uuid.uuid4()
        v = ProblemVersion(
            problem_id=pid, version_no=1, schema_version="problem-schema@1", payload=_payload()
        )
        assert v.problem_id == pid
        assert v.version_id != pid
        assert v.entity_type == "Problem"
        assert v.status == VersionStatus.DRAFT.value
        assert v.previous_version_id is None

    def test_version_no_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            ProblemVersion(
                problem_id=uuid.uuid4(),
                version_no=0,
                schema_version="problem-schema@1",
                payload=_payload(),
            )

    def test_identity_id_is_not_a_field_of_the_version_record(self) -> None:
        """계열 소속의 정본은 problem.identity_id 하나 — 버전 레코드·payload 어디에도 복제 없음."""
        assert "identity_id" not in ProblemVersion.model_fields
        assert "identity_id" not in ProblemVersionPayload.model_fields
