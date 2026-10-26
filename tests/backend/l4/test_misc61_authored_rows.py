"""MISC-61 — 앵커 A3 얇은 M-id 4건(M0599·M0600 1차, M0417·M0418 2차)의 신규 저작 행 계약 동결.

배경: 게이트 `G-misc40-deferred-m0599-redecision`의 보류 사유는 "4지선다 귀속을 검증할 재료(세 필드)가
없다"였고, 원천 대조(2026-10-09)로 원천부터 비어 있음이 확정돼 새로 저작했다. 이 저작이 검수를
무의미하게 만들지 않도록 세 가지를 코드로 묶는다.

  ① 세 필드가 실제로 채워졌다(빈 칸으로 되돌아가면 RED).
  ② AI 저작이 `원본`으로 위장하지 않는다 — `provenance_note`가 AI 저작 표기이고 DB 폭(32자) 안이다.
  ③ **순환 검증 금지**(Kiki 2026-10-07): 카탈로그 kebab의 `canonical_statement`·`counterexample`을
     복사하거나 바꿔 쓰지 않았다. 복사했다면 kebab↔M-id 검수는 같은 글을 자기 자신과 비교하게 된다.
     최장 공통 부분문자열이 영역 용어("합의 법칙" 등) 수준을 넘으면 RED — 대조군으로 카탈로그 문장을
     그대로 주입해 이 가드가 실제로 잡는지도 함께 검사한다(통과만 하는 가드는 보호가 아니다).
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path

import pytest

from whymath_backend.l4.misconception.catalog import CATALOG

_ROOT = Path(__file__).resolve().parents[3]
_CORPUS = _ROOT / "data" / "corpus" / "misconceptions_v1" / "misconceptions.json"

AUTHORED_IDS = ("M0599", "M0600", "M0417", "M0418")
# 2차(2026-10-17): M0417·M0418은 원천 `오개념_원인` 값이 있어 `student_wrong_thinking`만 원천 유래이고
# `distractor_rule`·`error_type`은 원천에 근거가 없어 AI 저작이다(행 전체가 검수 필요로 표시된다).
# 값은 Kiki 머신 2차 실행 결과(원천 sha256 fcf6d333…187e · sha256_matches_provenance=true).
SOURCE_DERIVED_THINKING = {"M0417": "확률 범위 미이해", "M0418": "배반사건 혼동"}
THREE_FIELDS = ("student_wrong_thinking", "distractor_rule", "error_type")
AI_NOTE_PREFIX = "AI생성-검수필요"
PROVENANCE_NOTE_MAX = 32  # db/models/misconception_catalog.py: sa.String(32)

# 영역 용어(예: 곱의법칙 8자) 수준은 허용하고 문장 단위 복사는 잡는 경계. 2026-10-12 실측 최대 8.
COPY_THRESHOLD = 14
# kebab 서술 전체가 저작문에 통째로 들어 있으면 복사로 본다 — 서술이 이보다 짧으면 영역 용어와
# 구별할 수 없어 적용하지 않는다(오탐 방지).
WHOLE_CONTAINMENT_MIN = 8
_KEBAB_FIELDS = ("canonical_statement", "counterexample")


def _norm(text: str | None) -> str:
    return re.sub(r"[\s\W_]+", "", text or "")


def _longest_common(a: str, b: str) -> int:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0
    return (
        SequenceMatcher(None, na, nb, autojunk=False)
        .find_longest_match(0, len(na), 0, len(nb))
        .size
    )


@pytest.fixture(scope="module")
def rows() -> dict[str, dict]:
    data = json.loads(_CORPUS.read_text(encoding="utf-8"))["misconceptions"]
    return {r["mis_id"]: r for r in data}


def _is_copy_of(text: str, kebab_text: str) -> bool:
    """저작문이 kebab 서술의 복사인가 — 문장 단위로 겹치거나(공통 부분문자열이 기준 이상),
    kebab 서술 전체가 저작문에 통째로 들어 있으면(서술이 짧아 기준에 못 미치는 경우의 보강) 복사다."""
    nt, nk = _norm(text), _norm(kebab_text)
    if not nt or not nk:
        return False
    if _longest_common(nt, nk) >= COPY_THRESHOLD:
        return True
    return len(nk) >= WHOLE_CONTAINMENT_MIN and nk in nt


def _copied_kebab(text: str) -> str | None:
    """복사로 판정되는 첫 kebab의 id(없으면 None). 서술 본문은 노출하지 않는다."""
    for kebab in CATALOG:
        for field in _KEBAB_FIELDS:
            if _is_copy_of(text, getattr(kebab, field, "") or ""):
                return kebab.id
    return None


# ── ① 세 필드가 채워졌다 ──────────────────────────────────────────────────
@pytest.mark.parametrize("mis_id", AUTHORED_IDS)
@pytest.mark.parametrize("field", THREE_FIELDS)
def test_three_fields_are_filled(rows: dict[str, dict], mis_id: str, field: str) -> None:
    value = rows[mis_id][field]
    assert isinstance(value, str) and value.strip(), f"{mis_id}.{field}가 비어 있다"


@pytest.mark.parametrize("mis_id", AUTHORED_IDS)
def test_error_type_and_severity_follow_the_corpus_vocabulary(
    rows: dict[str, dict], mis_id: str
) -> None:
    """error_type은 코퍼스가 이미 쓰는 어휘이고, severity는 다른 행이 보이는 error_type→severity 규칙을 따른다."""
    others = [r for r in rows.values() if r["mis_id"] not in AUTHORED_IDS and r["error_type"]]
    vocabulary = {r["error_type"] for r in others}
    rule: dict[str, set[str | None]] = {}
    for r in others:
        rule.setdefault(r["error_type"], set()).add(r["severity"])
    row = rows[mis_id]
    assert row["error_type"] in vocabulary
    assert rule[row["error_type"]] == {row["severity"]}, "다른 행의 규칙과 어긋난 severity"


# ── 원천 유래 값은 원천 그대로다 (2차) ─────────────────────────────────────────
@pytest.mark.parametrize("mis_id", sorted(SOURCE_DERIVED_THINKING))
def test_second_pass_thinking_is_the_source_value_verbatim(
    rows: dict[str, dict], mis_id: str
) -> None:
    """원천 값을 AI가 다시 쓰지 않았다 — 고쳐 쓰면 '원천 유래'라는 근거가 거짓이 된다."""
    assert rows[mis_id]["student_wrong_thinking"] == SOURCE_DERIVED_THINKING[mis_id]


def test_first_pass_rows_are_not_mistaken_for_source_derived() -> None:
    """M0599·M0600은 원천이 비어 전부 AI 저작이다 — 원천 유래 목록에 섞이면 근거 표기가 틀어진다."""
    assert set(SOURCE_DERIVED_THINKING).isdisjoint({"M0599", "M0600"})
    assert set(SOURCE_DERIVED_THINKING) <= set(AUTHORED_IDS)


# ── ② AI 저작이 원본으로 위장하지 않는다 ───────────────────────────────────
@pytest.mark.parametrize("mis_id", AUTHORED_IDS)
def test_authored_rows_are_marked_as_ai_authored_within_db_width(
    rows: dict[str, dict], mis_id: str
) -> None:
    note = rows[mis_id]["provenance_note"]
    assert note.startswith(AI_NOTE_PREFIX) and "MISC-61" in note
    assert len(note) <= PROVENANCE_NOTE_MAX


# ── ③ 순환 검증 금지 — kebab 서술을 복사하지 않았다 ─────────────────────────────
@pytest.mark.parametrize("mis_id", AUTHORED_IDS)
@pytest.mark.parametrize("field", ("student_wrong_thinking", "distractor_rule"))
def test_authored_text_is_not_a_copy_of_any_catalog_statement(
    rows: dict[str, dict], mis_id: str, field: str
) -> None:
    copied = _copied_kebab(rows[mis_id][field])
    assert copied is None, f"{mis_id}.{field}가 kebab `{copied}`의 서술과 겹친다(순환 검증)"


def test_guard_control_catches_a_verbatim_copy_of_every_catalog_statement() -> None:
    """대조군(전수): 어느 kebab의 서술이든 그대로 넣으면 이 가드가 RED를 낸다 — 통과만 하는 가드 방지.

    서술이 `WHOLE_CONTAINMENT_MIN`보다 짧은 항목은 이 가드의 사각이다(오탐 없이 구별할 수 없다) —
    그 항목은 대조군에서 제외하되, 제외 목록을 숨기지 않고 길이로 센다.
    """
    uncovered = 0
    for kebab in CATALOG:
        for field in _KEBAB_FIELDS:
            text = getattr(kebab, field, "") or ""
            if len(_norm(text)) < WHOLE_CONTAINMENT_MIN:
                uncovered += 1
                continue
            assert _copied_kebab(text) is not None, f"{kebab.id}.{field} 복사를 못 잡는다"
    assert uncovered < 2 * len(CATALOG), "대조군이 전부 제외됐다 — 가드를 검증한 것이 아니다"


def test_guard_control_catches_a_lightly_reworded_copy_of_the_paired_kebab() -> None:
    """M0599의 짝 kebab(가장 위험한 복사 경로)은 조사만 바꿔도 잡힌다."""
    kebab = next(k for k in CATALOG if k.id == "addition-multiplication-rule-confused")
    reworded = kebab.counterexample.replace("를", "을").replace("는", "은").replace("가", "이")
    assert reworded != kebab.counterexample, "치환이 적용되지 않았다 — 대조군이 아니다"
    assert _copied_kebab(reworded) is not None
