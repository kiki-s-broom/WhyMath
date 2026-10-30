"""실 대학 콘텐츠 코퍼스 검증 — 산출(concept_content_university_v1) 정합성(ground truth)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from data_pipeline.concept_content_university.models import SUBUNIT_PATTERN

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CORPUS = _REPO_ROOT / "data" / "corpus" / "concept_content_university_v1" / "content.json"

# 코퍼스 건수는 손으로 박지 않고 단일 원천의 기계용 사본에서 읽는다(OPS-154).
# 원본이 바뀌면 `python3 scripts/analysis/corpus_facts.py sync`가 이 파일을 갱신한다.
# 고정 지점이 사실 파일 한 곳이다 — 값이 바뀌면 그 파일의 diff가 의식적 리뷰 지점이다.
_FACTS = json.loads(
    (_REPO_ROOT / "docs" / "data" / "corpus_facts.json").read_text(encoding="utf-8")
)
_EXPECTED = _FACTS["concept_content.university"]


def _load() -> dict:
    if not _CORPUS.exists():
        pytest.skip("대학 콘텐츠 코퍼스 미생성")
    return json.loads(_CORPUS.read_text(encoding="utf-8"))


def test_corpus_counts_and_codes() -> None:
    data = _load()
    content = data["content"]
    assert len(content) == _EXPECTED
    assert len({c["code"] for c in content}) == _EXPECTED  # 소단원 코드 유일
    for c in content:
        assert SUBUNIT_PATTERN.match(c["code"]), c["code"]
        assert c["name"].strip()


def test_corpus_self_authored_and_internal_definition() -> None:
    data = _load()
    # 자체작성·정식정의 학생비노출 표기(redaction 불요·검수필요).
    assert "자체" in data["source_citation"]
    assert "학생 비노출" in data["license_notice"]
    # 콘텐츠 4종 전수 채움(검수보고: 대학 은유·허용표현 409칸 채움).
    for fld in (
        "metaphor",
        "misconception",
        "formal_definition_internal",
        "accepted_expressions",
    ):
        assert all(c[fld] for c in data["content"]), fld


def test_corpus_flashcards_present() -> None:
    data = _load()
    total = sum(len(c["flashcards"]) for c in data["content"])
    assert total == _EXPECTED  # 소단원당 1 카드(1:1)
    sample = data["content"][0]["flashcards"][0]
    assert sample["front"] and sample["back"]
