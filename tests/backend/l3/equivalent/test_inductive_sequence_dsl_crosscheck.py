"""S4-66 — 귀납 수열 뼈대의 `sequence_induction` DSL 직렬화 + [12대수03-06] 코퍼스 대조.

배경: 현재 [12대수03-06] 30건은 발문에 점화식을 쓰고 `verify.conditions`에는 생성기가 계산한
**폐형식**(`x - (7 + (12 - 1)*6) = 0`)을 싣는다. 점화식과 폐형이 어긋나게 생성돼도 Tier1에서는
드러나지 않는다 — 이 테스트가 발문의 점화식을 **실제로 실행한 값**과 폐형 값을 대조해 그 정합을
처음 닫는다.

검증 축:
  ① 직렬화 형식 고정(등차·등비).
  ② 생성기 풀 전수: DSL 실행값 == 뼈대의 정답 (불일치 0).
  ③ 코퍼스 대조: 발문을 **독립적으로 다시 파싱**(생성기 코드 재사용 없이)해 DSL을 만들고 실행한
     값이 레코드의 정답과 폐형 조건(Tier1)에 모두 맞는다 — 스캔 건수 0은 실패다(공허 통과 차단).
  ④ 변별력: 발문의 공차를 일부러 바꾼 레코드는 불일치로 잡힌다(대조가 항상 초록이 아님을 증명).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from whymath_backend.l3.equivalent.inductive_sequence_skeleton_generator import (
    _build_inductive_pool,
    _InductiveSkeleton,
    skeleton_to_sequence_dsl,
)
from whymath_backend.l3.sequence_induction import execute_sequence_model, parse_sequence_model
from whymath_backend.l3.verify_answer import verify_answer

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CORPUS = _REPO_ROOT / "data" / "corpus" / "problem_bank_generated_v0" / "problems.jsonl"
_BAND_CODE = "[12대수03-06]"
_SUBSCRIPT = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")

_FIRST = re.compile(r"\(가\) a₁ = (\d+)")
_ARITH = re.compile(r"\(나\) aₙ₊₁ = aₙ \+ (\d+) \(n ≥ 1\)")
_GEO = re.compile(r"\(나\) aₙ₊₁ = (\d+)·aₙ \(n ≥ 1\)")
_TERM = re.compile(r"a([₀-₉]+)의 값을 구하시오")


def _skeleton_from_question(question_text: str) -> _InductiveSkeleton | None:
    """발문 → 뼈대. 생성기의 발문 조립 코드를 쓰지 않는 독립 파서다(양쪽이 같은 버그를 공유하지 않게)."""
    first = _FIRST.search(question_text)
    term = _TERM.search(question_text)
    arith = _ARITH.search(question_text)
    geo = _GEO.search(question_text)
    if first is None or term is None or (arith is None) == (geo is None):
        return None
    step_match = arith if arith is not None else geo
    assert step_match is not None
    return _InductiveSkeleton(
        kind="arith" if arith is not None else "geo",
        first=int(first.group(1)),
        step=int(step_match.group(1)),
        term=int(term.group(1).translate(_SUBSCRIPT)),
    )


@dataclass(frozen=True)
class _CrosscheckReport:
    scanned: int
    unparsed: int
    answer_mismatch: int
    closed_form_mismatch: int


def _load_band() -> list[dict[str, object]]:
    rows = [json.loads(line) for line in _CORPUS.read_text(encoding="utf-8").splitlines() if line]
    return [row for row in rows if _BAND_CODE in row.get("achievement_standard_codes", [])]


def _crosscheck(records: list[dict[str, object]]) -> _CrosscheckReport:
    unparsed = answer_mismatch = closed_mismatch = 0
    for record in records:
        skeleton = _skeleton_from_question(str(record["question_text"]))
        if skeleton is None:
            unparsed += 1
            continue
        model = parse_sequence_model(skeleton_to_sequence_dsl(skeleton))
        value = execute_sequence_model(model).value
        assert not isinstance(value, tuple)
        if str(value) != str(record["answer"]):
            answer_mismatch += 1
        verify = record["verify"]
        assert isinstance(verify, dict)
        # 폐형 조건 `x - (폐형) = 0`에 실행값을 대입 — 폐형의 값과 실행값이 같아야 통과한다.
        closed = verify_answer(str(verify["conditions"]), {"x": str(value)})
        if closed.state != "pass":
            closed_mismatch += 1
    return _CrosscheckReport(
        scanned=len(records),
        unparsed=unparsed,
        answer_mismatch=answer_mismatch,
        closed_form_mismatch=closed_mismatch,
    )


# ── ① 직렬화 형식 ─────────────────────────────────────────────────────
def test_serialization_format_arith_and_geo() -> None:
    arith = _InductiveSkeleton(kind="arith", first=7, step=6, term=12)
    geo = _InductiveSkeleton(kind="geo", first=2, step=3, term=5)
    assert skeleton_to_sequence_dsl(arith) == "init=a(1)=7; rec=a(n+1)=a(n) + 6; query=a(12)"
    assert skeleton_to_sequence_dsl(geo) == "init=a(1)=2; rec=a(n+1)=3*a(n); query=a(5)"


# ── ② 생성기 풀 전수 ──────────────────────────────────────────────────
def test_every_generator_skeleton_executes_to_its_own_answer() -> None:
    pool = _build_inductive_pool()
    assert len(pool) > 0  # 풀이 비면 전수 통과가 공허하다
    mismatched = []
    for skeleton in pool:
        value = execute_sequence_model(
            parse_sequence_model(skeleton_to_sequence_dsl(skeleton))
        ).value
        if value != skeleton.answer:
            mismatched.append(skeleton)
    assert mismatched == []


# ── ③ 코퍼스 대조 ────────────────────────────────────────────────────
def test_band_03_06_corpus_recurrence_matches_closed_form() -> None:
    """발문의 점화식을 실행한 값 == 정답 == 폐형 조건의 값. 불일치 0건(0건이라고 명시)."""
    records = _load_band()
    report = _crosscheck(records)
    assert report.scanned >= 30, "[12대수03-06] 밴드 스캔 건수가 30 미만 — 필터가 대상을 못 찾았다"
    assert report.unparsed == 0, f"발문 파싱 불가 {report.unparsed}건"
    assert report.answer_mismatch == 0, f"실행값≠정답 {report.answer_mismatch}건"
    assert report.closed_form_mismatch == 0, f"실행값≠폐형 {report.closed_form_mismatch}건"


# ── ④ 변별력 ─────────────────────────────────────────────────────────
def test_crosscheck_detects_question_tampering() -> None:
    """발문의 증분(+6 → +7)만 바꾼 레코드는 불일치로 잡힌다 — 대조가 항상 초록이 아니다."""
    arith_records = [r for r in _load_band() if _ARITH.search(str(r["question_text"]))]
    assert arith_records, "등차 점화 레코드가 없어 변별력을 보일 수 없다"
    original = arith_records[0]
    step = _ARITH.search(str(original["question_text"]))
    assert step is not None
    old = f"aₙ + {step.group(1)}"
    new = f"aₙ + {int(step.group(1)) + 1}"
    tampered_text = str(original["question_text"]).replace(old, new)
    assert tampered_text != original["question_text"], "주입이 적용되지 않았다"
    assert tampered_text.replace(new, old).encode("utf-8") == str(original["question_text"]).encode(
        "utf-8"
    ), "원복이 바이트 동일하지 않다"
    tampered = {**original, "question_text": tampered_text}
    report = _crosscheck([tampered])
    assert report.scanned == 1
    assert report.answer_mismatch == 1
    assert report.closed_form_mismatch == 1
    # 같은 방식으로 원본은 불일치 0 — 대조군.
    assert _crosscheck([original]).answer_mismatch == 0
