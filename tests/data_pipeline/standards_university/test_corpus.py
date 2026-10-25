"""실 대학 성취기준 코퍼스 검증 — 산출(standards_university_v1) 정합성(atom test_corpus 미러).

합성 행이 아닌 *실제 커밋된 코퍼스*로 ground truth를 못 박는다(handoff 규율: 실 코퍼스 재검증).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from data_pipeline.standards_university.models import (
    UNIV_CODE_PATTERN,
    UNIV_NORM_ID_PATTERN,
    UNIV_SUBUNIT_PATTERN,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]

# 코퍼스 건수는 손으로 박지 않고 단일 원천의 기계용 사본에서 읽는다(OPS-154).
# 원본이 바뀌면 `python3 scripts/analysis/corpus_facts.py sync`가 이 파일을 갱신한다.
# 고정 지점이 사실 파일 한 곳이다 — 값이 바뀌면 그 파일의 diff가 의식적 리뷰 지점이다.
_FACTS = json.loads(
    (_REPO_ROOT / "docs" / "data" / "corpus_facts.json").read_text(encoding="utf-8")
)
_EXPECTED_STANDARDS = _FACTS["standards.university"]
_EXPECTED_SUBJECTS = _FACTS["standards.university_subjects"]


def test_corpus_counts(corpus_standards: dict, corpus_links: dict) -> None:
    stds = corpus_standards["standards"]
    links = corpus_links["links"]
    assert len(stds) == _EXPECTED_STANDARDS
    assert len(links) == _EXPECTED_STANDARDS  # 소단원↔성취기준 1:1


def test_corpus_codes_and_norm_ids_valid(corpus_standards: dict) -> None:
    for s in corpus_standards["standards"]:
        assert UNIV_CODE_PATTERN.match(s["code"]), s["code"]
        assert UNIV_NORM_ID_PATTERN.match(s["norm_id"]), s["norm_id"]
        assert s["curriculum_revision"] == "대학"
        assert s["school_type"] == "대학교"
        assert s["statement"].strip()  # 본문 비공란


def test_corpus_norm_id_and_code_unique(corpus_standards: dict) -> None:
    stds = corpus_standards["standards"]
    assert len({s["norm_id"] for s in stds}) == len(stds)
    assert len({s["code"] for s in stds}) == len(stds)


def test_corpus_subject_count(corpus_standards: dict) -> None:
    assert len({s["subject"] for s in corpus_standards["standards"]}) == _EXPECTED_SUBJECTS


def test_corpus_links_reference_standards(corpus_standards: dict, corpus_links: dict) -> None:
    norm_ids = {s["norm_id"] for s in corpus_standards["standards"]}
    subunits = set()
    for link in corpus_links["links"]:
        assert UNIV_SUBUNIT_PATTERN.match(link["concept_src_id"]), link["concept_src_id"]
        assert link["norm_id"] in norm_ids  # referential
        assert link["link_type"] == "직접"
        subunits.add(link["concept_src_id"])
    assert len(subunits) == _EXPECTED_STANDARDS  # 소단원 유일·1:1


def test_corpus_is_self_authored(corpus_standards: dict, corpus_provenance: dict) -> None:
    # 자체작성 표지(공공누리 아님·redaction 불요)·소단원 코드는 원자DB 재사용 명시.
    assert "자체" in corpus_standards["source_citation"]
    assert "공공누리" in corpus_standards["license_notice"]
    assert corpus_provenance["counts"]["standards"] == _EXPECTED_STANDARDS
    assert re.fullmatch(r"[0-9a-f]{64}", corpus_provenance["source_sha256"])
