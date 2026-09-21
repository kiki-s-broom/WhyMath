"""K-12 콘텐츠 모델·검증 단위테스트 — 코드 완화·자체작성 표기·집합 invariant."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from data_pipeline.concept_content.models import ConceptContent, Flashcard
from data_pipeline.concept_content.ncic_overlap import (
    build_license_notice,
    build_source_citation,
    load_standard_statements,
    measure_overlap,
)
from data_pipeline.concept_content.validate import validate_content
from pydantic import ValidationError


def _content(code: str = "N1", **over: object) -> ConceptContent:
    base: dict[str, object] = {
        "code": code,
        "name": "수 감각",
        "subject": "수학(초1~2)",
        "metaphor": "은유",
        "misconception": "오개념",
        "formal_definition_internal": "정식정의",
        "accepted_expressions": "허용표현",
    }
    base.update(over)
    return ConceptContent(**base)  # type: ignore[arg-type]


class TestModels:
    def test_valid_content(self) -> None:
        c = _content()
        assert c.code == "N1"
        assert c.flashcards == []
        assert c.standard_codes == []

    @pytest.mark.parametrize("code", ["N1", "A1", "HK01", "F2", "10기수1-01-01", "Q2"])
    def test_accepts_varied_k12_codes(self, code: str) -> None:
        # K-12 개념ID는 형식이 다양 → 비어있지 않으면 통과(U4 SUBUNIT_PATTERN 미적용).
        assert _content(code=code).code == code

    @pytest.mark.parametrize("bad", ["", "   "])
    def test_rejects_blank_code(self, bad: str) -> None:
        with pytest.raises(ValidationError, match="공란"):
            _content(code=bad)

    def test_standard_codes_preserved(self) -> None:
        c = _content(standard_codes=["[2수01-01]", "[2수01-02]"])
        assert c.standard_codes == ["[2수01-01]", "[2수01-02]"]

    def test_flashcard_fields(self) -> None:
        card = Flashcard(front="앞", back="뒤", mnemonic="암기")
        assert card.front == "앞" and card.exposure_condition is None

    def test_forbids_extra(self) -> None:
        with pytest.raises(ValidationError):
            _content(unexpected="x")

    def test_no_ncic_body_field(self) -> None:
        # NCIC 본문(성취기준 문장/요약)은 모델 필드로 존재하지 않는다(redaction).
        fields = set(ConceptContent.model_fields)
        assert "standard_statement" not in fields
        assert "standard_summary" not in fields
        assert "standard_codes" in fields


class TestValidate:
    def test_valid_set(self) -> None:
        report = validate_content([_content()])
        assert report.is_valid
        assert report.content_count == 1

    def test_duplicate_code_error(self) -> None:
        report = validate_content([_content(), _content()])
        assert not report.is_valid
        assert any(r[1] == "code_unique" for r in report.errors)

    def test_missing_content_is_warning(self) -> None:
        # 콘텐츠 누락은 warning(검수 큐)·적재 차단 아님.
        report = validate_content([_content(metaphor=None, misconception=None)])
        assert report.is_valid
        assert any(r[1] == "content_present" for r in report.issues)

    def test_flashcard_count(self) -> None:
        c = _content(flashcards=[Flashcard(front="a", back="b")])
        report = validate_content([c])
        assert report.flashcard_count == 1


# 선언은 상수가 아니라 **빌드 시점 실측으로 합성**된다(`ncic_overlap`). 커밋된 코퍼스만 고치고
# 생성원을 놔두면 다음 재생성에서 옛 선언이 소리 없이 돌아온다 — 2026-09-06 정정에서 실제로
# 드러난 드리프트 경로다. 그래서 여기서 동결하는 것은 "선언이 옳다"가 아니라
# "**생성원이 산출물을 재현한다**"이다(집행 지점 분리).
_REPO_ROOT = Path(__file__).resolve().parents[3]
_CORPUS = _REPO_ROOT / "data" / "corpus" / "concept_content_v1" / "content.json"
_SIDECAR = _REPO_ROOT / "data" / "corpus" / "concept_content_v1" / "_provenance.json"
_STANDARDS = _REPO_ROOT / "data" / "corpus" / "standards_v1" / "standards.json"


def _measured_from_committed():
    committed = json.loads(_CORPUS.read_text(encoding="utf-8"))
    return committed, measure_overlap(
        [(c.get("explanation") or "", c.get("standard_codes") or []) for c in committed["content"]],
        load_standard_statements(_STANDARDS),
    )


def test_builders_reproduce_committed_corpus() -> None:
    """생성원 ↔ 산출물 — 커밋된 코퍼스를 빌더가 그대로 재현해야 한다."""
    committed, overlap = _measured_from_committed()
    assert committed["source_citation"] == build_source_citation(overlap), (
        "커밋된 코퍼스의 source_citation을 빌더가 재현하지 못한다 — 재생성하면 코퍼스 선언이 "
        "조용히 바뀐다. 코퍼스를 다시 생성하거나 빌더를 맞춰라."
    )
    assert committed["license_notice"] == build_license_notice(
        overlap
    ), "커밋된 코퍼스의 license_notice를 빌더가 재현하지 못한다 — 위와 같은 이유로 red."


def test_sidecar_records_measured_overlap() -> None:
    """사이드카의 기계 판독 실측치가 지금 측정한 값과 같아야 한다."""
    _, overlap = _measured_from_committed()
    declared = json.loads(_SIDECAR.read_text(encoding="utf-8"))["ncic_statement_overlap"]
    assert (declared["count"], declared["exact_after_normalization"]) == (
        overlap.count,
        overlap.exact,
    ), "사이드카 실측치가 재측정과 다르다 — 코퍼스를 재생성했다면 사이드카도 함께 갱신하라."


def test_declaration_states_attribution_when_overlap_exists() -> None:
    """겹침이 있으면 출처 표시를 담고, 거짓이 된 '미수록' 주장은 담지 않는다.

    공공누리 제1유형의 유일한 조건이 출처 표시다. 겹침이 0으로 내려가면 이 축은 해제된다 —
    그때는 출처 표시가 오히려 사실이 아니게 되므로 빌더가 다른 문장을 만든다(아래 대칭 테스트).
    """
    _, overlap = _measured_from_committed()
    if overlap.count == 0:
        pytest.skip("겹침 0건 — 출처 표시 의무가 발생하지 않는다")
    notice = build_license_notice(overlap)
    assert "미수록" not in notice
    for marker in ("NCIC", "교육부 고시 제2022-33호", "공공누리"):
        assert marker in notice, f"출처 표시에 '{marker}' 누락"
    assert "자체" in build_source_citation(overlap)
    assert "학생 비노출" in notice and "검수필요" in notice
