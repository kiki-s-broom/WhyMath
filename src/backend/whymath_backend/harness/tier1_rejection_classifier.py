"""Tier1 검산 거부 행 전수 분류기 — 산술 오류(ⓐ)인가 표현 불일치(ⓑ)인가 (EOS-23 ③).

배경(EOS-23 ①~③ · 근거 `docs/ops/eos121_seat_generation_diversity_verdict.md`):
EOS-121 라이브 회차에서 anthropic 좌석의 `quad-sum`(두 근의 합) 30건이 전건
`정확성 실패 — Tier1 답 검산 fail: 조건 위반 — 잔차 ≠ 0: …`으로 거부됐다. Tier1 검산은
`conditions`의 잔차에 `answer_map`을 대입해 0인지만 보므로(`l3/verify_answer.py` 단일 조건·
자유변수 전건 치환 분기), 잔차 ≠ 0은 두 경우에 **똑같이** 난다:

  ⓐ ``arithmetic_error`` — 모델이 답을 틀렸다(해도, 해에서 나오는 파생량도 아니다).
  ⓑ ``representation_mismatch`` — 문항은 옳은데 `conditions`가 구속하는 것(근)과
     `answer_map`이 담은 것(근의 합 같은 **파생량**)이 어긋났다.

두 경우는 처방이 정반대다(프롬프트 교정 vs 검산 계약 확장). 이 모듈은 그 둘을 **수식 일관성**
으로 가른다 — 인상이 아니라 행마다 SymPy로 해집합을 구하고 파생량과 대조한다.

판정 절차(행 1건):
  1. **대상 여부** — `status == "rejected_gate"`이고 `candidate_payload`가 있는 행만.
  2. **Tier1 경로 확인** — `verify.answer_aggregate`·`answer_kind`가 있으면 게이트는 Tier1이
     아니라 집계/개념형 검증기로 갔다 → 판정불가(`not_tier1_path`).
  3. **재현** — 게이트와 **같은 함수**(`verify_answer`)로 다시 검산해 정말 `fail`인지 본다.
     재현이 안 되면 판정불가(`not_reproduced`) — 그 행을 이 분류의 증거로 쓰지 않는다.
     재현은 되지만 게이트 기록 사유에 Tier1 fail이 없으면(해 없음·근 선택 등 다른 게이트가 먼저
     거부) 판정불가(`not_tier1_rejection`) — 실제 거부 원인이 Tier1이 아닌 행을 섞지 않는다.
  4. **해집합** — 조건을 게이트와 **같은 파서**(`_parse_condition`)로 잔차화하고, 단일 변수
     다항식이면 `sympy.roots`로 중복도까지 근을 구한다(복소근 포함 정확값).
  5. **대조** — 주장값(`answer_map[변수]`)을 근 자체·파생량과 비교한다.
       · 근과 일치 → 재현 결과(fail)와 모순이므로 판정불가(`inconsistent_root_match`)
       · 근과 불일치 + 파생량 하나 이상 일치 → ⓑ(일치한 파생량 이름을 근거로 남긴다)
       · 근과도 파생량과도 불일치 + 모든 비교가 확정 → ⓐ
       · 비교 중 하나라도 확정 불가(None)이고 일치 0 → 판정불가(`compare_undetermined`)
     **모른다 ≠ 아니다**: 판정불가를 조용히 ⓐ로 접지 않는다.

파생량 목록(`DERIVED_QUANTITIES`):
  - ``sum``(근의 합) · ``product``(근의 곱) — 차수 무관. **기존 게이트 검증기
    `verify_root_aggregate`에 위임**한다(SymPy 단일 권위 · 재구현 0). 그 결과가 곧
    "`answer_aggregate`가 선언됐더라면 게이트를 통과했는가"의 증거이기도 하다.
  - ``abs_difference``(두 근의 차의 절댓값) · ``sum_of_squares``(두 근의 제곱의 합) ·
    ``sum_of_reciprocals``(두 근의 역수의 합) — **2차(근 2개)일 때만** 계산한다. 차수가 다르면
    이 셋은 "해당 없음"이지 "불일치"가 아니다.

발문 보조 신호(`stem_signals`): 발문이 무엇을 묻는지("…의 합"·"…의 곱" 등)를 기록한다.
**판정의 주 근거가 아니다** — ⓑ 판정 뒤 "일치한 파생량을 발문도 묻는가"(`stem_consistent`)를
보조로 남길 뿐이다. 발문 정규식은 표기 변형에 약하므로 주 근거로 쓰면 변별력이 무너진다.

범위(명시): 이 모듈은 **읽기 전용 분류**다 — DB·네트워크·LLM 호출 0, 쓰기는 CLI의 `--out`
파일 하나뿐이다. 처방(검산 계약 확장·프롬프트 교정)은 EOS-23 ⑤가 분류 뒤에 판단한다.

사용(Phaiakes9 — 런북 `docs/ops/eos23_rejected_quad_sum_classification_runbook.md`):
    python -m whymath_backend.harness.tier1_rejection_classifier <review.jsonl> \
        [--spec quad-sum] [--json] [--out 결과.json]

종료 코드:
  0 — 대상 1건 이상을 전부 분류했고 로드 실패 행 0
  1 — 대상 1건 이상을 분류했으나 **로드 실패 행이 있다**(측정 불완전 — 결과는 그래도 낸다)
  2 — 입력 파일 없음/읽기 불가 또는 **대상 0건**(공허한 통과 금지)
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import sympy

from whymath_backend.harness.needs_review_worklist import (
    ReviewQueueEntry,
    load_review_queue_jsonl,
)
from whymath_backend.l3.verify_answer import (
    _parse_condition,  # 게이트와 같은 파서 — 표기 drift 0(counterexample_fuzz 선례)
    verify_answer,
    verify_root_aggregate,
)

__all__ = [
    "DERIVED_QUANTITIES",
    "EXIT_EMPTY",
    "EXIT_OK",
    "EXIT_PARTIAL",
    "RowClassification",
    "build_summary",
    "classify_entry",
    "classify_queue",
    "is_target",
    "main",
    "stem_signals",
]

# 침묵 실패 금지(CLAUDE.md) — 보수 회피는 예외 *타입명*을 로그와 판정 사유 양쪽에 남긴다.
# 메시지 본문은 문항 식이 섞일 수 있어 로그에는 넣지 않는다(사유 필드는 운영 산출물).
logger = logging.getLogger("whymath.harness.tier1_rejection_classifier")

EXIT_OK = 0
EXIT_PARTIAL = 1
EXIT_EMPTY = 2

Verdict = Literal["arithmetic_error", "representation_mismatch", "undecidable"]
VERDICTS: tuple[Verdict, ...] = ("arithmetic_error", "representation_mismatch", "undecidable")

# 파생량 이름 — 순서가 곧 출력 순서다(결정론).
DERIVED_QUANTITIES: tuple[str, ...] = (
    "sum",
    "product",
    "abs_difference",
    "sum_of_squares",
    "sum_of_reciprocals",
)
# 근 2개(2차)일 때만 정의하는 파생량 — 그 밖의 차수에서는 "해당 없음"(불일치 아님).
_QUADRATIC_ONLY: frozenset[str] = frozenset(
    {"abs_difference", "sum_of_squares", "sum_of_reciprocals"}
)

# 게이트가 이 행을 Tier1에서 떨어뜨렸다는 기록 사유의 표지(acceptance.py 사유 문자열).
_TIER1_FAIL_MARK = "Tier1 답 검산 fail"
# verify_answer의 직접 수치 평가 분기 사유 표지(자유변수 전건 치환 · verify_answer.py).
_DIRECT_BRANCH_MARK = "잔차 ≠ 0"

_COMPARE_TOL = 1e-9
_STEM_EXCERPT_MAX = 160


# ──────────────────────────────────────────────────────────────────────────
# 발문 보조 신호 — 주 근거 아님(모듈 docstring 참조)
# ──────────────────────────────────────────────────────────────────────────
_STEM_SQUARES = re.compile(r"제곱의\s*합")
_STEM_RECIPROCALS = re.compile(r"역수의\s*합")
_STEM_SUM = re.compile(r"의\s*합|α\s*\+\s*β|alpha\s*\+\s*beta")
_STEM_PRODUCT = re.compile(r"의\s*곱|αβ|α\s*\*\s*β")
_STEM_DIFFERENCE = re.compile(r"의\s*차|차의\s*절댓값|차이")
_STEM_ROOT = re.compile(r"(큰|작은)\s*근|한\s*근|근을\s*구하")


def stem_signals(question_text: str | None) -> list[str]:
    """발문이 묻는 대상의 표면 신호(정렬된 이름 목록) — 보조 기록용.

    "제곱의 합"·"역수의 합"은 "…의 합"보다 먼저 떼어 낸다(그렇지 않으면 합 신호가 이중 계상).
    "이차방정식"의 "차"는 "…의 차" 패턴에 걸리지 않는다(앞에 "의"가 없다).
    """
    if not isinstance(question_text, str) or not question_text:
        return []
    text = question_text
    found: set[str] = set()
    if _STEM_SQUARES.search(text):
        found.add("sum_of_squares")
    if _STEM_RECIPROCALS.search(text):
        found.add("sum_of_reciprocals")
    stripped = _STEM_RECIPROCALS.sub("", _STEM_SQUARES.sub("", text))
    if _STEM_SUM.search(stripped):
        found.add("sum")
    if _STEM_PRODUCT.search(stripped):
        found.add("product")
    if _STEM_DIFFERENCE.search(stripped):
        found.add("abs_difference")
    if _STEM_ROOT.search(stripped):
        found.add("root")
    return sorted(found)


# ──────────────────────────────────────────────────────────────────────────
# 행 판정 결과
# ──────────────────────────────────────────────────────────────────────────
@dataclass(slots=True)
class RowClassification:
    """거부 행 1건의 분류 결과 + 근거(전부 문자열/기본형 — JSON 직렬화 그대로)."""

    source_line: int | None
    spec_id: str | None
    run_id: str | None
    slug: str | None
    payload_sha256: str | None
    verdict: Verdict
    reason_code: str
    """판정 코드 — ⓐ/ⓑ면 `classified`, 판정불가면 사유 코드(`not_reproduced` 등)."""
    message: str
    """사람용 사유(한국어) — 판정불가면 무엇이 확정되지 않았는지."""
    recorded_tier1_fail: bool = False
    """게이트 기록 사유에 Tier1 fail 표지가 있었는가(재현과 별개 — 둘 다 본다)."""
    reproduced_state: str | None = None
    """`verify_answer` 재실행 상태(pass/fail/unverifiable). None=재현 단계 전에 멈춤."""
    reproduced_reason: str | None = None
    reproduced_direct_branch: bool = False
    """재현 사유가 직접 수치 평가 분기(`잔차 ≠ 0`)인가 — EOS-121 거부 사유와 같은 분기인가."""
    conditions: Any = None
    answer_map: dict[str, str] | None = None
    answer_text: str | None = None
    answer_selection: str | None = None
    variable: str | None = None
    degree: int | None = None
    roots: list[str] = field(default_factory=list)
    """근(중복도만큼 반복 · sstr) — 해집합 계산 실패면 빈 목록."""
    claimed: str | None = None
    """검산에 대입된 주장값(`answer_map[변수]`) — 표시 답(`answer_text`)이 아니다."""
    matches_root: bool | None = None
    derived: dict[str, str] = field(default_factory=dict)
    """계산된 파생량(이름 → sstr 값). 해당 없음(차수 불일치·정의 불가)은 키 자체가 없다."""
    derived_comparison: dict[str, bool | None] = field(default_factory=dict)
    """파생량별 주장값 일치 여부 — True 일치 · False 불일치 · None 확정 불가."""
    matched_derived: list[str] = field(default_factory=list)
    aggregate_gate_recheck: dict[str, str] = field(default_factory=dict)
    """`verify_root_aggregate`(게이트 검증기) 상태 — `answer_aggregate`가 선언됐다면의 결과."""
    stem_excerpt: str | None = None
    stem_signals: list[str] = field(default_factory=list)
    stem_consistent: bool | None = None
    """ⓑ일 때: 일치한 파생량을 발문 신호도 가리키는가. 판단 재료 없으면 None."""

    def compact(self) -> dict[str, Any]:
        """채팅 회신용 축약 행 — 문항 본문 없이 판정·근거 핵심만."""
        return {
            "line": self.source_line,
            "spec_id": self.spec_id,
            "verdict": self.verdict,
            "reason_code": self.reason_code,
            "conditions": self.conditions,
            "claimed": self.claimed,
            "roots": self.roots,
            "matched_derived": self.matched_derived,
            "stem_signals": self.stem_signals,
            "stem_consistent": self.stem_consistent,
            "reproduced": self.reproduced_state,
        }


def is_target(entry: ReviewQueueEntry, spec: str | None = None) -> bool:
    """분류 대상인가 — 게이트 거부 + 후보 본문 있음 + (지정 시) spec 일치."""
    if entry.status != "rejected_gate" or entry.candidate_payload is None:
        return False
    return spec is None or entry.spec_id == spec


# ──────────────────────────────────────────────────────────────────────────
# 수치 비교 — 확정 불가는 None(모른다 ≠ 아니다)
# ──────────────────────────────────────────────────────────────────────────
def _equal(actual: sympy.Expr, claimed: sympy.Expr) -> bool | None:
    """두 식이 같은가 — 기호 차 0 또는 수치 차 < tol이면 True, 확정 불가면 None."""
    try:
        diff = sympy.simplify(actual - claimed)
        if diff == 0:
            return True
        value = complex(sympy.N(diff))
    except Exception as exc:  # noqa: BLE001 — 비교 불가는 None(판정불가 경로로)
        logger.debug("tier1_rejection_classifier 비교 회피: %s", type(exc).__name__)
        return None
    if value != value:  # NaN
        return None
    return abs(value) < _COMPARE_TOL


def _derived_values(roots: Sequence[sympy.Expr], degree: int) -> dict[str, sympy.Expr]:
    """근 목록(중복도 반복) → 파생량. sum·product는 게이트 검증기가 판정하므로 표시용 값."""
    values: dict[str, sympy.Expr] = {
        "sum": sympy.simplify(sympy.Add(*roots)),
        "product": sympy.simplify(sympy.Mul(*roots)),
    }
    if degree == 2 and len(roots) == 2:
        r1, r2 = roots
        values["abs_difference"] = sympy.simplify(sympy.Abs(r1 - r2))
        values["sum_of_squares"] = sympy.simplify(r1**2 + r2**2)
        if sympy.simplify(r1 * r2) != 0:
            values["sum_of_reciprocals"] = sympy.simplify(1 / r1 + 1 / r2)
    return values


def _undecidable(row: RowClassification, code: str, message: str) -> RowClassification:
    row.verdict = "undecidable"
    row.reason_code = code
    row.message = message
    return row


def _str_map(value: object) -> dict[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    return {str(k): str(v) for k, v in value.items()}


def classify_entry(entry: ReviewQueueEntry) -> RowClassification:
    """거부 행 1건 → 분류(순수 · DB/네트워크/LLM 0). 대상 여부는 호출자가 `is_target`으로 거른다.

    대상이 아닌 행을 넘겨도 예외 없이 판정불가(`not_target`)로 돌려준다(조용한 오분류 금지).
    """
    payload = entry.candidate_payload
    row = RowClassification(
        source_line=entry.source_line,
        spec_id=entry.spec_id,
        run_id=entry.run_id,
        slug=entry.slug,
        payload_sha256=entry.payload_sha256,
        verdict="undecidable",
        reason_code="pending",
        message="",
        recorded_tier1_fail=any(_TIER1_FAIL_MARK in reason for reason in entry.reasons),
    )
    if entry.status != "rejected_gate" or payload is None:
        return _undecidable(
            row,
            "not_target",
            f"대상 아님 — status={entry.status} · payload 유무={payload is not None}",
        )

    question = payload.get("question_text")
    if isinstance(question, str):
        row.stem_excerpt = " / ".join(p for p in question.splitlines() if p)[:_STEM_EXCERPT_MAX]
    row.stem_signals = stem_signals(question if isinstance(question, str) else None)
    answer_text = payload.get("answer")
    row.answer_text = answer_text if isinstance(answer_text, str) else None

    verify = payload.get("verify")
    if not isinstance(verify, Mapping):
        return _undecidable(row, "verify_missing", "candidate_payload에 verify 재료가 없다")
    conditions = verify.get("conditions")
    answer_map = _str_map(verify.get("answer_map"))
    row.conditions = conditions
    row.answer_map = answer_map
    selection = verify.get("answer_selection")
    row.answer_selection = selection if isinstance(selection, str) else None
    if answer_map is None or not (
        isinstance(conditions, str)
        or (isinstance(conditions, list) and all(isinstance(c, str) for c in conditions))
    ):
        return _undecidable(
            row, "verify_malformed", "conditions/answer_map 형식이 검산 재료가 아니다"
        )

    # ② Tier1 경로 확인 — 집계/개념형 선언이 있으면 게이트는 Tier1을 타지 않았다.
    for key in ("answer_aggregate", "answer_kind"):
        if verify.get(key) is not None:
            return _undecidable(
                row,
                "not_tier1_path",
                f"verify.{key}={verify.get(key)!r} — 게이트가 Tier1이 아닌 검증기로 판정한 행",
            )

    # ③ 재현 — 게이트와 같은 함수로 정말 fail인지.
    try:
        reproduced = verify_answer(conditions, answer_map)
    except Exception as exc:  # noqa: BLE001 — 재현 불가도 사유로 남긴다(타입명)
        logger.warning("tier1_rejection_classifier 재현 실패: %s", type(exc).__name__)
        return _undecidable(
            row, "reproduce_error", f"verify_answer 재실행 예외 {type(exc).__name__}"
        )
    row.reproduced_state = reproduced.state
    row.reproduced_reason = reproduced.reason
    row.reproduced_direct_branch = _DIRECT_BRANCH_MARK in (reproduced.reason or "")
    if reproduced.state != "fail":
        return _undecidable(
            row,
            "not_reproduced",
            f"Tier1 재검산이 fail을 재현하지 않음(state={reproduced.state})"
            " — 이 행은 증거로 쓰지 않는다",
        )
    if not row.recorded_tier1_fail:
        # 재검산은 fail이지만 게이트는 다른 사유(해 없음·근 선택 등)로 먼저 떨어뜨렸다 — 이 행의
        # 실제 거부 원인은 Tier1이 아니므로 ⓐ/ⓑ 분류의 모집단에 넣지 않는다.
        return _undecidable(
            row,
            "not_tier1_rejection",
            "Tier1 재검산은 fail이나 게이트 기록 사유에 Tier1 fail이 없다"
            " — 다른 게이트가 거부한 행",
        )

    # ④ 해집합 — 단일 조건·단일 변수 다항 등식만.
    if isinstance(conditions, list):
        if len(conditions) != 1:
            return _undecidable(
                row, "multi_condition", f"연립 조건 {len(conditions)}개 — 단일 해집합 대조 범위 밖"
            )
        condition = conditions[0]
    else:
        condition = conditions
    try:
        residual, op = _parse_condition(condition)
    except Exception as exc:  # noqa: BLE001 — 파싱 불가는 판정불가(타입명)
        logger.debug("tier1_rejection_classifier 파싱 회피: %s", type(exc).__name__)
        return _undecidable(row, "parse_error", f"조건 파싱 불가 {type(exc).__name__}")
    if op != "==":
        return _undecidable(row, "not_equation", f"등식이 아님(관계 {op}) — 해집합 대조 범위 밖")
    free = sorted(residual.free_symbols, key=str)
    if len(free) != 1:
        return _undecidable(
            row, "multivariate", f"자유변수 {len(free)}개 — 단일 변수 방정식이 아님"
        )
    var = free[0]
    row.variable = str(var)
    claimed_text = answer_map.get(str(var))
    if claimed_text is None:
        return _undecidable(row, "claimed_missing", f"answer_map에 변수 {var}의 값이 없다")
    row.claimed = claimed_text
    try:
        claimed = sympy.sympify(claimed_text, convert_xor=True)
    except Exception as exc:  # noqa: BLE001
        logger.debug("tier1_rejection_classifier 주장값 회피: %s", type(exc).__name__)
        return _undecidable(row, "claimed_unparseable", f"주장값 파싱 불가 {type(exc).__name__}")
    if getattr(claimed, "free_symbols", None):
        return _undecidable(row, "claimed_not_numeric", "주장값에 기호가 남는다 — 수치 대조 불가")
    try:
        poly = sympy.Poly(residual, var)
        root_mult = sympy.roots(poly)
    except Exception as exc:  # noqa: BLE001 — 다항식 아님·근 계산 불가
        logger.debug("tier1_rejection_classifier 근 계산 회피: %s", type(exc).__name__)
        return _undecidable(row, "not_polynomial", f"다항식 근 계산 불가 {type(exc).__name__}")
    degree = int(poly.degree())
    row.degree = degree
    roots: list[sympy.Expr] = []
    for root, mult in root_mult.items():
        roots.extend([root] * int(mult))
    row.roots = [sympy.sstr(r) for r in roots]
    if degree < 1:
        return _undecidable(row, "no_roots", "상수 잔차 — 근이 없다(해집합 대조 불가)")
    if len(roots) != degree:
        return _undecidable(
            row, "roots_incomplete", f"근을 중복도까지 다 구하지 못함({len(roots)}/{degree})"
        )

    # ⑤ 대조 — 근 자체.
    root_hits = [_equal(r, claimed) for r in roots]
    row.matches_root = (
        True
        if any(h is True for h in root_hits)
        else (None if any(h is None for h in root_hits) else False)
    )
    if row.matches_root is True:
        return _undecidable(
            row,
            "inconsistent_root_match",
            "주장값이 근과 일치하는데 재검산은 fail — 모순(허용오차·파서 경계 의심)",
        )

    # ⑤ 대조 — 파생량. sum·product는 게이트 검증기(verify_root_aggregate)가 판정한다.
    values = _derived_values(roots, degree)
    row.derived = {name: sympy.sstr(values[name]) for name in DERIVED_QUANTITIES if name in values}
    comparison: dict[str, bool | None] = {}
    for kind in ("sum", "product"):
        gate = verify_root_aggregate(condition, claimed_text, kind)
        row.aggregate_gate_recheck[kind] = gate.state
        comparison[kind] = {"pass": True, "fail": False}.get(gate.state)
    for name in DERIVED_QUANTITIES:
        if name in _QUADRATIC_ONLY and name in values:
            comparison[name] = _equal(values[name], claimed)
    row.derived_comparison = comparison
    row.matched_derived = [name for name in DERIVED_QUANTITIES if comparison.get(name) is True]

    if row.matched_derived and row.matches_root is False:
        row.verdict = "representation_mismatch"
        row.reason_code = "classified"
        row.message = (
            "주장값이 근이 아니라 파생량(" + ", ".join(row.matched_derived) + ")과 일치 — "
            "조건은 근을 구속하고 답은 파생량을 담았다"
        )
        if row.stem_signals:
            row.stem_consistent = any(name in row.stem_signals for name in row.matched_derived)
        return row
    if row.matched_derived:
        # 근 일치 여부 확정 불가(None) + 파생량 일치 — 근이 아니라고 단정할 수 없다.
        return _undecidable(
            row, "root_compare_undetermined", "파생량과 일치하나 근과의 불일치를 확정하지 못함"
        )
    undetermined = [name for name, hit in comparison.items() if hit is None]
    if row.matches_root is None or undetermined:
        return _undecidable(
            row,
            "compare_undetermined",
            "일치 0건이나 확정 불가 비교가 있다: "
            + ", ".join((["root"] if row.matches_root is None else []) + undetermined),
        )
    row.verdict = "arithmetic_error"
    row.reason_code = "classified"
    row.message = "주장값이 근도 아니고 어떤 파생량과도 일치하지 않는다"
    return row


# ──────────────────────────────────────────────────────────────────────────
# 큐 전체 분류 + 집계
# ──────────────────────────────────────────────────────────────────────────
def classify_queue(
    entries: Sequence[ReviewQueueEntry], *, spec: str | None = None
) -> tuple[list[RowClassification], dict[str, Any]]:
    """큐 행 전체 → (대상 행 분류 목록, 비대상 사유 집계)."""
    rows: list[RowClassification] = []
    skipped_status: Counter[str] = Counter()
    skipped_no_payload = 0
    skipped_spec: Counter[str] = Counter()
    for entry in entries:
        if entry.status != "rejected_gate":
            skipped_status[entry.status] += 1
            continue
        if entry.candidate_payload is None:
            skipped_no_payload += 1
            continue
        if spec is not None and entry.spec_id != spec:
            skipped_spec[str(entry.spec_id)] += 1
            continue
        rows.append(classify_entry(entry))
    skipped = {
        "by_status": dict(sorted(skipped_status.items())),
        "rejected_gate_without_payload": skipped_no_payload,
        "by_spec_filter": dict(sorted(skipped_spec.items())),
    }
    return rows, skipped


def build_summary(
    rows: Sequence[RowClassification],
    *,
    input_path: str,
    spec: str | None,
    valid_rows: int,
    load_errors: Sequence[str],
    skipped: Mapping[str, Any],
) -> dict[str, Any]:
    """분류 결과 → 집계 요약(채팅 회신용 · 행 축약 포함)."""
    by_spec: dict[str, dict[str, int]] = {}
    for row in rows:
        bucket = by_spec.setdefault(str(row.spec_id), {v: 0 for v in VERDICTS})
        bucket[row.verdict] += 1
    verdict_counts = {v: sum(1 for r in rows if r.verdict == v) for v in VERDICTS}
    undecidable_codes = Counter(r.reason_code for r in rows if r.verdict == "undecidable")
    matched = Counter(name for r in rows for name in r.matched_derived)
    run_ids = Counter(str(r.run_id) for r in rows)
    aggregate_would_pass = Counter(
        kind for r in rows for kind, state in r.aggregate_gate_recheck.items() if state == "pass"
    )
    return {
        "tool": "tier1_rejection_classifier",
        "input": input_path,
        "spec_filter": spec,
        "rows_total": valid_rows + len(load_errors),
        "rows_valid": valid_rows,
        "load_errors": list(load_errors),
        "skipped": dict(skipped),
        "target_rows": len(rows),
        "distinct_payloads": len({r.payload_sha256 for r in rows if r.payload_sha256}),
        "recorded_tier1_fail_rows": sum(1 for r in rows if r.recorded_tier1_fail),
        "reproduced_fail_rows": sum(1 for r in rows if r.reproduced_state == "fail"),
        "reproduced_direct_branch_rows": sum(1 for r in rows if r.reproduced_direct_branch),
        "verdict_counts": verdict_counts,
        "by_spec": dict(sorted(by_spec.items())),
        "undecidable_reason_codes": dict(sorted(undecidable_codes.items())),
        "matched_derived_counts": dict(sorted(matched.items())),
        "aggregate_gate_would_pass": dict(sorted(aggregate_would_pass.items())),
        "stem_consistent_counts": {
            "true": sum(1 for r in rows if r.stem_consistent is True),
            "false": sum(1 for r in rows if r.stem_consistent is False),
            "unknown": sum(
                1
                for r in rows
                if r.verdict == "representation_mismatch" and r.stem_consistent is None
            ),
        },
        "run_ids": dict(sorted(run_ids.items())),
        "rows": [r.compact() for r in rows],
    }


def _render_json(summary: Mapping[str, Any]) -> str:
    """요약 JSON — **ASCII 전용**(`ensure_ascii=True`)이고 행은 한 줄에 하나.

    ASCII인 이유: Phaiakes9의 PowerShell 5.1은 네이티브 출력을 cp949로 디코딩·재인코딩한다
    (CLAUDE.md 인코딩 규칙 — 셸 중계 축). 한국어는 유니코드 이스케이프(백슬래시-u 4자리)로
    나가므로 그 왕복에서 바이트가 바뀌지 않는다. 행을 한 줄씩 두는 이유: 채팅 붙여넣기
    분량을 줄이고(30행 × 1줄) 콘솔 복사 중 행이 섞여도 어느 행인지 보이게 한다. 결과는
    여전히 `json.loads`로 읽히는 단일 JSON이다.
    """
    head = json.dumps(
        {key: value for key, value in summary.items() if key != "rows"},
        ensure_ascii=True,
        indent=1,
    )
    rows = ",\n".join("  " + json.dumps(row, ensure_ascii=True) for row in summary["rows"])
    return head[: -len("\n}")] + ',\n "rows": [\n' + rows + "\n ]\n}"


def _render_text(summary: Mapping[str, Any]) -> str:
    counts = summary["verdict_counts"]
    lines = [
        f"입력: {summary['input']} · spec 필터: {summary['spec_filter']}",
        f"행 {summary['rows_total']} (유효 {summary['rows_valid']} · 로드 실패 "
        f"{len(summary['load_errors'])}) · 대상 {summary['target_rows']}",
        f"판정: 산술 오류(ⓐ) {counts['arithmetic_error']} · 표현 불일치(ⓑ) "
        f"{counts['representation_mismatch']} · 판정불가 {counts['undecidable']}",
        f"spec별: {json.dumps(summary['by_spec'], ensure_ascii=False)}",
        f"판정불가 사유: {json.dumps(summary['undecidable_reason_codes'], ensure_ascii=False)}",
        f"일치 파생량: {json.dumps(summary['matched_derived_counts'], ensure_ascii=False)}",
    ]
    lines.extend(f"로드 실패: {err}" for err in summary["load_errors"])
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 진입점 — 읽기 전용(쓰기는 `--out` 하나). 종료 코드는 모듈 docstring 참조."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.tier1_rejection_classifier",
        description=(
            "검수 큐 JSONL의 Tier1 검산 거부 행을 산술 오류/표현 불일치/판정불가로 전수 분류"
        ),
    )
    parser.add_argument(
        "review_jsonl", type=Path, help="ReviewQueueEntry JSONL(예: anthropic.review.jsonl)"
    )
    parser.add_argument("--spec", default=None, help="이 spec_id 행만 분류(예: quad-sum)")
    parser.add_argument(
        "--json", action="store_true", help="요약을 JSON(ASCII 이스케이프)으로 출력"
    )
    parser.add_argument(
        "--out", type=Path, default=None, help="요약 + 행별 전체 근거를 이 JSON 파일에 저장"
    )
    args = parser.parse_args(argv)

    input_display = str(args.review_jsonl)
    try:
        entries, load_errors = load_review_queue_jsonl(args.review_jsonl)
    except (OSError, UnicodeDecodeError) as exc:
        failure = {
            "tool": "tier1_rejection_classifier",
            "input": input_display,
            "measured": False,
            "error": f"입력 파일 읽기 실패 {type(exc).__name__}",
        }
        print(json.dumps(failure, ensure_ascii=True, indent=1))
        return EXIT_EMPTY

    rows, skipped = classify_queue(entries, spec=args.spec)
    summary = build_summary(
        rows,
        input_path=input_display,
        spec=args.spec,
        valid_rows=len(entries),
        load_errors=load_errors,
        skipped=skipped,
    )
    summary["measured"] = bool(rows)

    if args.out is not None:
        full = dict(summary)
        full["rows_full"] = [asdict(r) for r in rows]
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(full, ensure_ascii=False, indent=1), encoding="utf-8")
        summary["out"] = str(args.out)

    if args.json:
        print(_render_json(summary))
    else:
        print(_render_text(summary))

    if not rows:
        return EXIT_EMPTY
    if load_errors:
        return EXIT_PARTIAL
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover — CLI 진입
    sys.exit(main())
