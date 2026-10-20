"""Solution QA — 문제·정답·풀이 불일치 기계 검증 (P3-07 · 순수·결정론·LLM 0·DB 0).

수학앱은 문항 하나가 틀려도 신뢰가 무너진다. 이 모듈은 문항마다 **네 가지 검사**를 SymPy 단일 권위
경로로 돌려 3상태(통과/실패/검증 불가)를 낸다.

  C1 정답 ↔ 문제 조건   `verify.conditions` 를 정답이 만족하는가 + 레코드의 `answer` 필드가
                        검산에 쓴
                        `verify.answer_map` 과 같은 값인가(아래 "왜 새로 만들었나" 참조)
  C2 풀이 최종 답 ↔ 정답  `verify.solution_steps` 의 **마지막 단계**가 정답과 같은 값을 말하는가
  C3 선택지             객관식이면 정답이 선택지에 **정확히 한 번** 있고, 보기끼리 같은 값이 없는가
  C4 풀이 단계 연쇄      `solution_steps` 의 이웃 단계가 전부 동치인가(`verify_solution` 재사용).
                        동치가 아닌 해석 단계(근 선택 `a = -6, a = 6 → a = 6`·
                        대입 `x = 3 → y = 4`)는 문항 조건(도메인 제약·`answer_selection`·
                        정의 등식)으로 판정한다(P3-71)

왜 `corpus_reverify` 와 별개 모듈인가 (2026-10-18 실측)
-----------------------------------------------------
`corpus_reverify` 의 표준 경로는 `verify.answer_map` 만 검산하고 레코드의 **`answer` 필드는 비교하지
않는다**(집계·개념형 경로만 `answer` 를 쓴다). 대표 과정 문항 40건의 `answer` 만 틀린 값으로 바꾸는
주입을 그 도구에 태우면 0/40 이 검출된다 — 학생에게 보이는 값과 검산된 값이 갈라져도 통과한다.
또 풀이 최종 답·선택지 유일성은 어느 도구도 보지 않는다. 그래서 `corpus_reverify` 를 고치지 않고(S6
야간 상시성 게이트의 의미를 바꾸지 않는다) 문제-정답-풀이 일관성 축을 이 모듈이 맡는다.

판정 규칙 — "모른다 ≠ 아니다", 검증 불가를 통과로 세지 않는다
-------------------------------------------------------------
검사 하나의 상태는 PASS / FAIL / UNVERIFIABLE / NOT_APPLICABLE(구조상 해당 없음 — 선택지 없는 문항의
C3). 문항의 판정은 FAIL 이 하나라도 있으면 FAIL, 없고 UNVERIFIABLE 이 하나라도 있으면 UNVERIFIABLE,
아니면 PASS 다. 즉 **네 검사가 모두 결정된 문항만 통과**한다.

  Solution QA Pass = PASS / (PASS + FAIL)      ← 기계 검증 대상 = 판정이 난 문항
  검증 가능 비율    = (PASS + FAIL) / 전체      ← 분모를 줄여 통과율을 올리는 길을 막으려 함께 낸다

UNVERIFIABLE 은 **사람 검수 대기 목록**으로 사유 코드와 함께 전건 낸다(절단 없음).

종료 코드는 **실패 0건**이 합격 조건이다(비율 판정이 아니다)
-------------------------------------------------------------
코퍼스가 크면 통과율 임계(스코어카드 흡수 99.5%)는 결함 몇 건을 삼킨다 — 대표 과정 456건에서 기계로
확정된 불일치 1건을 주입해도 통과율은 99.78% 로 목표 위다(2026-10-18 실측). 그런데 이 모듈의 FAIL 은
"정답과 풀이·선택지가 서로 모순임이 SymPy 로 확정"이라는 뜻이라 오류 예산을 줄 이유가 없다. 그래서
임계는 표시용이고(`--target` 같은 효력 없는 스위치를 두지 않는다), 게이트는 실패 문항 수로 판정한다.
P3-14 ④ 는 같은 집계를 스코어카드 임계(비율)로 판정하므로 `0 < 실패 ≤ 0.5%` 구간에서 두 표면의
판정이 갈린다. 의도된 차이이며 Kiki 결정 항목으로 보고서에 올렸다.

정직 스코프 (이 수치가 말하지 않는 것)
-------------------------------------
· C1 은 정답이 **`verify.conditions` 를 만족하는지**를 본다. `conditions` 가 `question_text` 를
  충실히
  옮긴 것인지는 보지 않는다 — 일부 생성기 계열은 정답에서 역산한 식을 conditions 로 적는다
  (예: 극댓값
  108 문항의 conditions 가 `x**2 + 284*x - 42336 = 0`). 이 경우 C1 통과는 "정답이 자기 자신에게서
  유도된 식을 만족한다"는 뜻이라 **통과율은 실제 정확도의 상한**이다. 발문 ↔ conditions
  독립 재유도는
  계열별 파서가 필요한 별개 작업이다(후속 태스크로 등재).
· `answer_explanation`(서술 해설)은 기계가 읽지 않는다. 풀이 검증 대상은 구조화된
  `solution_steps` 뿐이다.
· 근 선택 규칙이 `answer_selection`(큰 근/작은 근)으로 구조화돼 있지 않은 문항은,
  `verify.conditions` 가 "그 변수의 단일 등식 + 도메인 부등식"(`a > 0`·`c >= 0, c <= 3`)일
  때만 도메인으로 후보를 걸러 판정한다(P3-71). 선택은 조건에서만 도출하고 정답에서
  역산하지 않는다(P3-24 B3 단서 — 역산하면 순환 통과다). 그 모양이 아니면 어느 쪽이
  정답인지 기계가 가릴 수 없다 → 검증 불가로 분리한다.
· 해석 단계(C4)는 조건에 근거가 있을 때만 판정한다. 대입의 정의 등식은 자유변수가 정확히
  {앞 변수, 뒤 변수}인 것만 쓴다 — 다른 매개변수가 섞이면 그 값을 정답 기록에서 빌려 와야 하므로
  판정 불가로 둔다. 변수가 바뀌는 단계는 동치 판정에서 늘 incorrect 였지만 그 판정은 동치라는 틀린
  기준의 결과였다 — 근거가 없으면 이제 검증 불가다(대장: P3-71 리뷰 문서 §위험).

사용:
    python -m whymath_backend.harness.solution_qa                      # 대표 과정 승인 문항 전수
    python -m whymath_backend.harness.solution_qa 은행.jsonl [...]     # 코퍼스 JSONL 직접 지정
    python -m whymath_backend.harness.solution_qa --queue-out q.jsonl --json out.json
종료 코드: 0=실패 0건 · 1=실패 문항이 1건이라도 있음 · 2=측정 실패(대상 0건·판정 가능 0건·적재 실패)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Final, cast

from whymath_backend.harness.corpus_reverify import _CONCEPTUAL_VERIFIERS, _iter_records
from whymath_backend.l3.safe_parse import safe_sympify
from whymath_backend.l3.verify_answer import (
    AnswerVerdict,
    RootSelection,
    classify_solvability,
    condition_relation,
    satisfies_domain,
    split_equation_domain,
    verify_answer,
    verify_root_aggregate,
    verify_root_selection,
    verify_substituted_value,
)
from whymath_backend.l3.verify_final_answer import verify_final_answer
from whymath_backend.l3.verify_solution import verify_solution

__all__ = [
    "CHECK_IDS",
    "CheckResult",
    "CheckState",
    "ItemResult",
    "SolutionQaReport",
    "Verdict",
    "judge_record",
    "main",
    "run_solution_qa",
]

EXIT_OK: Final = 0
EXIT_FAIL: Final = 1
EXIT_UNMEASURED: Final = 2

CHECK_IDS: Final = ("C1", "C2", "C3", "C4")
CHECK_TITLES: Final[Mapping[str, str]] = {
    "C1": "정답 ↔ 문제 조건 (+ answer 필드 ↔ answer_map)",
    "C2": "풀이 최종 답 ↔ 정답",
    "C3": "선택지에 정답이 정확히 한 번",
    "C4": "풀이 단계 연쇄 동치",
}

# 보고용 상한 — 화면 요약에서만 자른다(사람 검수 대기 목록은 --queue-out 으로 전건).
_PRINT_FAILURES: Final = 50


class CheckState(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNVERIFIABLE = "unverifiable"
    NOT_APPLICABLE = "not_applicable"


class Verdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNVERIFIABLE = "unverifiable"


@dataclass(frozen=True, slots=True)
class CheckResult:
    state: CheckState
    code: str | None = None
    """FAIL/UNVERIFIABLE 의 폐쇄 사유 코드(`C2_NO_STEPS` 등). PASS/NOT_APPLICABLE 은 None."""
    detail: str | None = None


_PASS: Final = CheckResult(CheckState.PASS)
_NA: Final = CheckResult(CheckState.NOT_APPLICABLE)


def _fail(code: str, detail: str | None = None) -> CheckResult:
    return CheckResult(CheckState.FAIL, code, detail)


def _unv(code: str, detail: str | None = None) -> CheckResult:
    return CheckResult(CheckState.UNVERIFIABLE, code, detail)


@dataclass(frozen=True, slots=True)
class ItemResult:
    ident: str
    unit: str
    verdict: Verdict
    checks: Mapping[str, CheckResult]

    def blocking(self, state: CheckState) -> tuple[tuple[str, CheckResult], ...]:
        return tuple(
            (cid, self.checks[cid]) for cid in CHECK_IDS if self.checks[cid].state == state
        )

    def reason_text(self) -> str:
        """FAIL 이면 실패 사유, UNVERIFIABLE 이면 검증 불가 사유를 `검사:코드(상세)`로 잇는다."""
        want = CheckState.FAIL if self.verdict is Verdict.FAIL else CheckState.UNVERIFIABLE
        return "; ".join(
            f"{cid}:{res.code}" + (f"({res.detail})" if res.detail else "")
            for cid, res in self.blocking(want)
        )


# ──────────────────────────────────────────────────────────────────────────
# 값 동치 — 정본 채점기(`verify_final_answer`)에 위임한다. SymPy 로직을 여기서 새로 만들지 않는다.
# ──────────────────────────────────────────────────────────────────────────
@dataclass(slots=True)
class _AnswerView:
    """`verify_final_answer` 가 읽는 최소 문항 필드. 선택지 모드를 끄고 값 대 값으로 비교한다."""

    answer: str | None
    choices: list[str] | None = None
    question_format: Any = None
    answer_format: Any = None
    multiple_answers: dict[str, Any] | None = None


# 유니코드 근호 — 정본 채점기가 못 읽는다(`8√3` → unverifiable, 2026-10-18 실측). 비교용으로만
# `N√M` → `N*sqrt(M)` 로 접는다(원문 레코드는 건드리지 않는다).
_RADICAL: Final = re.compile(r"(\d*)\s*√\s*(\d+|\([^()]*\))")


def _normalize(text: str) -> str:
    return _RADICAL.sub(
        lambda m: (f"{m.group(1)}*" if m.group(1) else "") + f"sqrt({m.group(2)})", text.strip()
    )


class _Same(str, Enum):
    SAME = "same"
    DIFFERENT = "different"
    UNKNOWN = "unknown"


def _same(left: str, right: str) -> _Same:
    """두 값 문자열이 수학적으로 같은가 — 3상태. 판정 불가·예외는 UNKNOWN(같음/다름 위장 금지)."""
    try:
        verdict = verify_final_answer(_normalize(left), _AnswerView(answer=_normalize(right)))
    except (
        Exception
    ):  # noqa: BLE001 - 한 쌍의 실패가 문항 전체를 죽이지 않는다(UNKNOWN 으로 드러난다)
        return _Same.UNKNOWN
    if verdict.state.value == "correct":
        return _Same.SAME
    if verdict.state.value == "incorrect":
        return _Same.DIFFERENT
    return _Same.UNKNOWN


# ──────────────────────────────────────────────────────────────────────────
# C1 — 정답 ↔ 문제 조건
# ──────────────────────────────────────────────────────────────────────────
def _conditions_of(verify: Mapping[str, object]) -> str | list[str] | None:
    raw = verify.get("conditions")
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list) and raw and all(isinstance(c, str) for c in raw):
        return [str(c) for c in raw]
    return None


def _answer_map_of(verify: Mapping[str, object]) -> dict[str, str]:
    raw = verify.get("answer_map")
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items()}


def _verdict_to_check(verdict: AnswerVerdict, label: str, unv_code: str) -> CheckResult | None:
    """`AnswerVerdict` → 검사 결과. 통과면 None(다음 단계로 진행)."""
    if verdict.state == "fail":
        return _fail(f"C1_{label}_FAIL", verdict.reason)
    if verdict.state == "unverifiable":
        return _unv(unv_code, verdict.reason)
    return None


def _check_c1(record: Mapping[str, object], verify: Mapping[str, object] | None) -> CheckResult:
    answer = record.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        return _fail("C1_ANSWER_MISSING")
    if verify is None:
        return _unv("C1_NO_VERIFY_MATERIAL")
    conditions = _conditions_of(verify)
    if conditions is None:
        return _unv("C1_BAD_CONDITIONS")

    # 근 집계(합/곱) — 답이 근이 아니라 근들의 집계값이라 `answer` 를 직접 검산한다.
    aggregate = verify.get("answer_aggregate")
    if aggregate in ("sum", "product"):
        agg = verify_root_aggregate(conditions, answer, aggregate)
        return _verdict_to_check(agg, "AGGREGATE", "C1_AGGREGATE_UNVERIFIABLE") or _PASS

    # 개념형(실근 개수·극값 개수·미분가능 판정 등) — 독립 SymPy 계산이 `answer` 를 직접 검산한다.
    kind = verify.get("answer_kind")
    if isinstance(kind, str) and kind in _CONCEPTUAL_VERIFIERS:
        cnt = _CONCEPTUAL_VERIFIERS[kind](conditions, answer)
        return _verdict_to_check(cnt, "CONCEPTUAL", "C1_CONCEPTUAL_UNVERIFIABLE") or _PASS

    amap = _answer_map_of(verify)
    if not amap:
        return _unv("C1_ANSWER_MAP_EMPTY")
    early = _verdict_to_check(verify_answer(conditions, amap), "TIER1", "C1_TIER1_UNVERIFIABLE")
    if early is not None:
        return early
    selection = verify.get("answer_selection")
    if isinstance(selection, str) and selection in ("largest", "smallest", "unique"):
        sel = verify_root_selection(conditions, amap, cast(RootSelection, selection))
        early = _verdict_to_check(sel, "SELECTION", "C1_SELECTION_UNVERIFIABLE")
        if early is not None:
            return early

    # `answer` 필드 ↔ 검산에 쓴 answer_map — 학생에게 보이는 값과 검산된 값이 같아야 한다.
    matched = _answer_vars(amap, answer)
    if matched is None:
        return _unv("C1_ANSWER_MAP_COMPARE_UNVERIFIABLE")
    if not matched:
        return _fail("C1_ANSWER_NOT_IN_ANSWER_MAP", f"answer≠answer_map 값({sorted(amap)})")
    return _PASS


def _answer_vars(amap: Mapping[str, str], answer: str) -> frozenset[str] | None:
    """`answer` 와 같은 값을 가진 answer_map 변수 집합. 하나도 못 가렸고 판정 불가가 있었으면 None.

    변수가 하나면 `answer` 가 그 값이어야 한다(엄격). 변수가 여러 개인 문항은 `answer` 가
    어느 변수의
    값인지 구조에 적혀 있지 않아 **소속**으로만 대조한다(약한 검사 — 형제 변수 값으로 바꾼 변조는 못
    잡는다. 보고서의 다변수 건수로 따로 드러낸다).
    """
    matches: set[str] = set()
    unknown = False
    for var, value in amap.items():
        relation = _same(value, answer)
        if relation is _Same.SAME:
            matches.add(var)
        elif relation is _Same.UNKNOWN:
            unknown = True
    if not matches and unknown:
        return None
    return frozenset(matches)


# ──────────────────────────────────────────────────────────────────────────
# C2 — 풀이 최종 답 ↔ 정답
# ──────────────────────────────────────────────────────────────────────────
_ASSIGN: Final = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*(\S.*?)\s*$")


def _split_top_level(text: str) -> list[str]:
    """최상위 쉼표로만 자른다 — `f(1, 2)` 안의 쉼표는 자르지 않는다."""
    parts: list[str] = []
    depth = 0
    start = 0
    for index, ch in enumerate(text):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(text[start:index])
            start = index + 1
    parts.append(text[start:])
    return parts


def _final_assignments(last_step: str) -> tuple[str, list[str]] | None:
    """마지막 단계가 `v = a` 또는 `v = a, v = b` 형태면 (변수, 값 목록). 아니면 None."""
    var: str | None = None
    values: list[str] = []
    for part in _split_top_level(last_step):
        if "==" in part or "<" in part or ">" in part:
            return None
        match = _ASSIGN.match(part)
        if match is None:
            return None
        name, value = match.group(1), match.group(2)
        if "=" in value or (var is not None and name != var):
            return None
        var = name
        values.append(value)
    return (var, values) if var is not None else None


def _float_of(value: str) -> float | None:
    try:
        return float(safe_sympify(_normalize(value)))
    except Exception:  # noqa: BLE001 - 수치화 불가는 None(근 선택 판정 불가로 드러난다)
        return None


def _distinct(values: Sequence[str]) -> list[str] | None:
    """값 목록의 서로 다른 원소. 같은지 판정이 안 되는 쌍이 있으면 None."""
    kept: list[str] = []
    for value in values:
        relations = [_same(value, other) for other in kept]
        if _Same.UNKNOWN in relations:
            return None
        if _Same.SAME not in relations:
            kept.append(value)
    return kept


# ──────────────────────────────────────────────────────────────────────────
# 근 선택 규칙 — "이 값이 조건이 요구하는 그 근인가"를 **문항 조건에서만** 판정한다
# (P3-71 · C2·C4 공용)
# ──────────────────────────────────────────────────────────────────────────
# 정답(`answer`·`answer_map`)에서 선택을 역산하지 않는다(P3-24 B3 단서 — 역산하면 순환 통과다).
# 근거는 셋뿐이다: ①그 변수 하나만 담은 조건 등식(근의 집합) ②그 변수의 도메인 부등식
# (`a > 0`·`c >= 0, c <= 3`) ③작성자가 구조에 적은 `answer_selection`(largest/smallest).
# 근의 집합은 풀이가 나열한 후보가 아니라 `verify_root_selection` 이 조건으로 직접 계산한다 — 풀이의
# 후보 나열이 불완전해도(근 하나를 빠뜨려도) 그 빈자리로 통과하지 않게 한다(PR #1703 검토 상2).
_PROVEN: Final = "proven"  # 조건이 요구하는 바로 그 근이다(조건만으로 확정)
_WRONG: Final = "wrong"  # 도메인 위반·조건의 선택 규칙과 다른 근(확정)
_UNKNOWN: Final = "unknown"  # 조건에 근거가 없거나 판정 불가


def _condition_items(verify: Mapping[str, object]) -> list[str] | None:
    conditions = _conditions_of(verify)
    if conditions is None:
        return None
    return [conditions] if isinstance(conditions, str) else list(conditions)


def _relations(verify: Mapping[str, object]) -> list[tuple[str, str, frozenset[str]]] | None:
    """조건마다 (원문, 관계 연산자, 자유변수 이름). 파싱 못 한 조건이 하나라도 있으면 None.

    파싱하지 못한 조건이 무엇을 제약하는지 모르므로, 그 상태로 "제약 없음"을 말하지 않는다.
    """
    items = _condition_items(verify)
    if items is None:
        return None
    out: list[tuple[str, str, frozenset[str]]] = []
    for condition in items:
        relation = condition_relation(condition)
        if relation is None:
            return None
        out.append((condition, relation[0], relation[1]))
    return out


def _defines_other_variable(condition: str, var: str) -> bool:
    """`w = f(var)` 꼴(한쪽이 다른 변수 하나뿐, 반대쪽은 `var` 만의 식)인가 — 그 조건은 w 를 정할 뿐
    `var` 를 제약하지 않는다. `x + z > 100`·`x**2 + y**2 = 1` 처럼 `var` 를 함께 묶는 조건은
    아니다."""
    if "<" in condition or ">" in condition or "!" in condition:
        return False
    sides = condition.split("=")
    if len(sides) != 2:
        return False
    for lone, other in ((sides[0], sides[1]), (sides[1], sides[0])):
        name = lone.strip()
        if name.isidentifier() and name != var:
            relation = condition_relation(other)
            if relation is not None and relation[1] == frozenset({var}):
                return True
    return False


def _judge_value(verify: Mapping[str, object], var: str, value: str) -> str:
    """`var = value` 가 조건이 요구하는 근인가 — `_PROVEN`·`_WRONG`·`_UNKNOWN`.

    · 도메인 부등식을 어기면 `_WRONG`(제약 위반 근).
    · `var` 를 다른 변수와 함께 담은 조건이 있으면 `_UNKNOWN` — 그 조건이 `var` 를 더 제약하는지
      (`x + z > 100`·`x**2 + y**2 = 1` 등) 모른다. 예외는 다른 변수 하나를 `var` 만의 식으로 정하는
      정의 등식(`y = f(x)`·`f(x) = y`)뿐이다 — 그것은 y 를 정할 뿐 x 를 제약하지 않는다(PR #1703
      재검토 MV2).
    · 그 변수 하나만 담은 조건 등식이 정확히 하나여야 근의 집합을 안다 — 아니면 `_UNKNOWN`.
    · 그 등식이 **실근이 있는 다항 등식**이어야 한다(`classify_solvability` 가 unique/multiple).
      초월 등식에서 `sympy.solve` 는 해의 일부만 준다(`sin(x) = 1` → [π/2]) — 그것을 "유일한 근"
      으로 읽으면 증명이 아닌 것이 증명이 된다(PR #1703 재검토 상1). 비다항이면 `_UNKNOWN` 이고,
      변수 전환 단계라면 `_check_c4` 의 단조 규칙이 종전 incorrect 를 유지한다.
    · 값이 그 등식의 근이 아니면 `_UNKNOWN`(`verify_root_selection` 이 판정 불가를 낸다 — 후보가
      다른 식의 해일 수 있다. 변수 전환 단계에서는 `_check_c4` 가 종전 incorrect 를 유지한다).
    · 선택 규칙 = `answer_selection`(largest/smallest), 없으면 unique. `verify_root_selection` 이
      조건(등식 + 도메인)만으로 허용 근을 계산해 그 근이면 `_PROVEN`. largest/smallest 인데 다른
      근이면 `_WRONG`. unique 인데 허용 근이 둘 이상이면 `_UNKNOWN`(어느 쪽도 확정 아님).
    """
    relations = _relations(verify)
    if relations is None:
        return _UNKNOWN
    domain = [c for c, op, names in relations if op != "==" and names == frozenset({var})]
    equations = [c for c, op, names in relations if op == "==" and names == frozenset({var})]
    if domain and satisfies_domain(domain, var, value) is False:
        return _WRONG
    mixed = [
        c
        for c, op, names in relations
        if var in names and len(names) > 1 and not _defines_other_variable(c, var)
    ]
    if mixed or len(equations) != 1:
        return _UNKNOWN
    if classify_solvability(equations[0]).state not in ("unique", "multiple"):
        return _UNKNOWN
    selection = verify.get("answer_selection")
    rule = selection if selection in ("largest", "smallest") else "unique"
    verdict = verify_root_selection(
        [equations[0], *domain], {var: value}, cast(RootSelection, rule)
    )
    if verdict.state == "pass":
        return _PROVEN
    if verdict.state == "fail" and rule != "unique":
        return _WRONG
    return _UNKNOWN


def _check_c2(record: Mapping[str, object], verify: Mapping[str, object] | None) -> CheckResult:
    answer = record.get("answer")
    if verify is None or not isinstance(answer, str) or not answer.strip():
        return _unv("C2_NO_VERIFY_MATERIAL")
    steps = verify.get("solution_steps")
    if not isinstance(steps, list) or not steps:
        return _unv("C2_NO_STEPS")
    parsed = _final_assignments(str(steps[-1]))
    if parsed is None:
        return _unv("C2_FINAL_STEP_NOT_ANSWER_FORM")
    var, values = parsed

    amap = _answer_map_of(verify)
    if amap:
        answer_vars = _answer_vars(amap, answer)
        if answer_vars is None:
            return _unv("C2_ANSWER_VAR_UNVERIFIABLE")
        if var not in answer_vars:
            # 마지막 단계의 변수가 정답 변수가 아니면(중간 변수) 최종 답을 말한 단계가 아니다.
            # 정답 변수에 값이 아예 안 맞는 경우는 C1 이 잡는다 — 여기서는 연결 불가로만 분리한다.
            return _unv("C2_FINAL_STEP_VAR_NOT_ANSWER_VAR", var)

    roots = _distinct(values)
    if roots is None:
        return _unv("C2_VALUE_UNVERIFIABLE")

    if len(roots) == 1:
        # 정답 변수의 단일 값 진술 — 정답과 다르면 한 레코드 안에서 같은 변수가 두 값을 갖는
        # 모순이다.
        relation = _same(roots[0], answer)
        if relation is _Same.SAME:
            return _PASS
        if relation is _Same.UNKNOWN:
            return _unv("C2_VALUE_UNVERIFIABLE")
        return _fail("C2_FINAL_ANSWER_MISMATCH", "풀이 최종 단계의 값 ≠ 정답")

    # 값이 둘 이상 — 후보(임계점·근) 나열이다. 정답이 후보에 없다고 불일치로 단정하지 않는다:
    # 정답이 후보의 함수일 수 있다(교점 개수·구간 안의 정수·극값). 2026-10-18 실측 — 이 코퍼스에서
    # "정답이 후보에 없음"으로 FAIL 을 내면 47건 전부 거짓 실패였다. 실제 오류는 C1(조건 검산·
    # 근 선택
    # 검산)과 C4(후보 도출 단계의 동치)가 따로 잡는다.
    selection = verify.get("answer_selection")
    if selection not in ("largest", "smallest"):
        if amap:
            by_domain = _check_c2_domain(verify, var, roots, answer)
            if by_domain is not None:
                return by_domain
        return _unv("C2_ROOT_CHOICE_UNSTRUCTURED", f"후보 {len(roots)}개·선택 규칙 없음")
    numeric = [_float_of(root) for root in roots]
    if any(x is None for x in numeric):
        return _unv("C2_ROOT_CHOICE_UNSTRUCTURED", "후보 수치화 불가")
    nums = [x for x in numeric if x is not None]
    picked = roots[nums.index(max(nums) if selection == "largest" else min(nums))]
    if _same(picked, answer) is _Same.SAME:
        return _PASS
    return _unv(
        "C2_ANSWER_NOT_SELECTED_CANDIDATE", f"{selection} 후보 ≠ 정답(정답이 후보의 함수일 수 있음)"
    )


def _numeric_distinct_count(values: Sequence[str]) -> int | None:
    """후보의 서로 다른 **수치** 개수(상대·절대 허용치 1e-9). 수치화 불가가 있으면 None.

    완전성 비교는 근 판정(Tier1 수치 대입)과 같은 수치 기준으로 센다. 정본 채점기(`_same`)는
    `-1.4142135623730951` 과 `-sqrt(2)` 를 다른 값으로 보므로, 그것으로 세면 근 하나를 빠뜨린 나열이
    "실근 개수와 같다"로 통과한다(PR #1703 재검토 중2 · N4a).
    """
    kept: list[float] = []
    for value in values:
        number = _float_of(value)
        if number is None:
            return None
        if not any(abs(number - other) <= max(1e-9, 1e-9 * abs(other)) for other in kept):
            kept.append(number)
    return len(kept)


def _check_c2_domain(
    verify: Mapping[str, object], var: str, roots: Sequence[str], answer: str
) -> CheckResult | None:
    """후보 나열 + 도메인 제약 → 남은 후보가 정답인가(P3-71 ②). 모양이 아니면 None(종전 사유로).

    적용 모양(전부 성립해야 한다 — "정답이 후보의 함수"인 문항을 거짓 실패로 만들지 않기 위해):
      ① 정답이 근 자체다 — 개념형(`answer_kind`)·근 집계(`answer_aggregate`)가 아니고, 마지막 단계의
         변수가 정답 변수다(호출부가 answer_map 소속으로 이미 확인).
      ② `verify.conditions` 가 "그 변수의 단일 등식 + 도메인 부등식"이다(`split_equation_domain`).
      ③ 후보 전부가 그 등식의 근이다(Tier1 대입) — 아니면 후보가 다른 식의 해라 비교 근거가 없다.
      ④ 후보가 그 등식의 서로 다른 실근 **전부**다(다항식의 실근 개수와 같다) — 근 하나를 빠뜨린
         나열에서 남은 후보 하나를 "도메인이 고른 근"으로 읽지 않는다(PR #1703 검토 상2).
    판정: 도메인을 만족하는 후보가 하나 → 정답과 다르면 FAIL, 같으면 조건만으로 계산한
    `verify_root_selection(조건, 정답, "unique")` 도 pass 일 때 PASS. 하나도 없음 → FAIL(허용되는
    근이 없는데 정답이 있다 — 모순). 둘 이상 → 검증 불가. 정답은 대조에만 쓴다.
    """
    if verify.get("answer_kind") or verify.get("answer_aggregate"):
        return None
    items = _condition_items(verify)
    split = None if items is None else split_equation_domain(items)
    if split is None or split[2] != var or not split[1]:
        return None
    equation, domain, _ = split
    for root in roots:
        state = verify_answer(equation, {var: root}).state
        if state == "fail":
            return _unv("C2_DOMAIN_CANDIDATE_NOT_ROOT", f"후보 {root} 가 조건 등식의 근이 아님")
        if state == "unverifiable":
            return _unv("C2_DOMAIN_UNVERIFIABLE", f"후보 {root} 의 등식 대입 판정 불가")
    solvability = classify_solvability(equation)
    distinct_count = _numeric_distinct_count(roots)
    if solvability.state not in ("unique", "multiple") or (
        distinct_count != solvability.n_distinct_real_roots
    ):
        return _unv(
            "C2_DOMAIN_CANDIDATES_INCOMPLETE",
            f"후보 수치 {distinct_count}개 ≠ 등식의 실근 {solvability.n_distinct_real_roots}개"
            f"({solvability.state})",
        )
    flags = [satisfies_domain(domain, var, root) for root in roots]
    if any(flag is None for flag in flags):
        return _unv("C2_DOMAIN_UNVERIFIABLE", "도메인 제약 판정 불가")
    survivors = [root for root, flag in zip(roots, flags, strict=True) if flag]
    if not survivors:
        return _fail(
            "C2_DOMAIN_NO_ADMISSIBLE_CANDIDATE",
            f"후보 {list(roots)} 전부 도메인 {list(domain)} 위반",
        )
    if len(survivors) > 1:
        return _unv("C2_DOMAIN_AMBIGUOUS", "도메인을 만족하는 후보가 둘 이상·선택 규칙 없음")
    relation = _same(survivors[0], answer)
    if relation is _Same.UNKNOWN:
        return _unv("C2_VALUE_UNVERIFIABLE")
    if relation is _Same.DIFFERENT:
        return _fail("C2_DOMAIN_PICK_MISMATCH", f"도메인이 고른 후보 {survivors[0]} ≠ 정답")
    confirm = verify_root_selection([equation, *domain], {var: answer}, "unique")
    if confirm.state != "pass":
        return _unv("C2_DOMAIN_UNVERIFIABLE", f"조건만으로 근 선택 확인 불가: {confirm.reason}")
    return _PASS


# ──────────────────────────────────────────────────────────────────────────
# C3 — 선택지
# ──────────────────────────────────────────────────────────────────────────
def _check_c3(record: Mapping[str, object]) -> CheckResult:
    choices = record.get("choices")
    is_mc = record.get("question_format") == "객관식"
    if not choices:
        return _fail("C3_MC_WITHOUT_CHOICES") if is_mc else _NA
    answer = record.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        return _fail("C3_ANSWER_MISSING")
    if not isinstance(choices, list) or not all(isinstance(c, str) for c in choices):
        return _fail("C3_CHOICES_MALFORMED")
    texts = [str(c).strip() for c in choices]
    if len(texts) < 2:
        return _fail("C3_TOO_FEW_CHOICES", f"{len(texts)}개")
    if len(set(texts)) != len(texts):
        return _fail("C3_DUPLICATE_CHOICE", "문자열이 같은 보기")

    answer_hits = 0
    undecided = False
    for text in texts:
        relation = _same(text, answer)
        if relation is _Same.SAME:
            answer_hits += 1
        elif relation is _Same.UNKNOWN:
            undecided = True
    if answer_hits >= 2:
        return _fail("C3_ANSWER_REPEATED", f"정답과 같은 값의 보기 {answer_hits}개")
    pair_unknown = False
    for i, left in enumerate(texts):
        for right in texts[i + 1 :]:
            relation = _same(left, right)
            if relation is _Same.SAME:
                return _fail("C3_DUPLICATE_CHOICE", "값이 같은 보기 쌍")
            if relation is _Same.UNKNOWN:
                pair_unknown = True
    if answer_hits == 0:
        if undecided:
            return _unv("C3_CHOICE_UNVERIFIABLE", "정답과 비교 불가한 보기")
        return _fail("C3_ANSWER_NOT_IN_CHOICES")
    if undecided or pair_unknown:
        # 정답과 같은 보기가 하나 확인됐어도, 비교 불가한 보기가 남으면 "정확히 한 번"을
        # 단정할 수 없다.
        return _unv("C3_CHOICE_UNVERIFIABLE", "값 비교 불가한 보기 존재")
    return _PASS


# ──────────────────────────────────────────────────────────────────────────
# C4 — 풀이 단계 연쇄
# ──────────────────────────────────────────────────────────────────────────
_CORRECT: Final = "correct"
_INCORRECT: Final = "incorrect"
_UNJUDGED: Final = "unverifiable"
_SELECTION: Final = "근 선택"
_SUBSTITUTION: Final = "대입"


def _numeric_assignments(step: str) -> tuple[str, list[str]] | None:
    """`v = a[, v = b …]` 이고 값이 전부 수치(자유변수 없음)면 (변수, 서로 다른 값). 아니면 None."""
    parsed = _final_assignments(step)
    if parsed is None:
        return None
    var, values = parsed
    distinct = _distinct(values)
    if distinct is None or any(_float_of(value) is None for value in distinct):
        return None
    return var, distinct


def _judge_selection(verify: Mapping[str, object], var: str, chosen: str) -> str:
    """근 선택 단계 `v = a, v = b → v = a` — 고른 값이 조건이 요구하는 근인가(`_judge_value`)."""
    verdict = _judge_value(verify, var, chosen)
    if verdict == _PROVEN:
        return _CORRECT
    return _INCORRECT if verdict == _WRONG else _UNJUDGED


def _judge_substitution(
    verify: Mapping[str, object], var: str, candidates: Sequence[str], target: str, claimed: str
) -> str:
    """대입 단계 `v = a → w = b` — 조건이 요구하는 v 를 정의 등식(자유변수가 정확히 {v, w})에
    대입한 w 가 b 인가.

    대입에 쓰는 v 는 **조건만으로 확정된 근**이어야 한다(`_judge_value` 가 `_PROVEN`). 앞 단계 값이
    하나여도 같다 — 풀이 첫 줄에 놓인 값은 들어오는 전이가 없어 아무도 검산하지 않으므로, 여기서
    도메인·등식의 근·선택 규칙을 확인하지 않으면 틀린 v 로 맞는 대입을 한 풀이가 통과한다(PR #1703
    검토 상1). 후보가 여럿이면 확정되는 후보가 정확히 하나일 때만 그것을 쓴다 — 결과값에 맞는 후보를
    거꾸로 찾지 않는다(정답 역산). 다른 매개변수가 섞인 정의 등식은 쓰지 않는다(그 값을 정답
    기록에서 빌려 오게 되므로).
    """
    # 값이 확정되지 않으면(도메인 위반·등식의 근 아님 포함) 판정 불가를 돌린다 — 변수 전환 단계는
    # 동치 판정이 늘 incorrect 이므로 `_check_c4` 가 그 incorrect 를 유지한다(성립 증명만 바꾼다).
    verdicts = [_judge_value(verify, var, candidate) for candidate in candidates]
    proven = [c for c, verdict in zip(candidates, verdicts, strict=True) if verdict == _PROVEN]
    if not proven:  # 선택 규칙(unique·largest·smallest)이 확정하는 근은 많아야 하나다.
        return _UNJUDGED
    relations = _relations(verify) or []  # 확정된 값이 있으면 조건은 이미 전부 파싱됐다.
    definitions = [c for c, op, names in relations if op == "==" and names == {var, target}]
    if not definitions:
        return _UNJUDGED
    states = [
        verify_substituted_value(definition, {var: proven[0]}, target, claimed).state
        for definition in definitions
    ]
    if "fail" in states:
        return _INCORRECT
    return _CORRECT if all(state == "pass" for state in states) else _UNJUDGED


def _interpretive_step(
    verify: Mapping[str, object], before: str, after: str
) -> tuple[str, str] | None:
    """동치가 아닌 해석 단계면 (종류, 판정). 그 모양이 아니면 None — 동치 판정을 그대로 둔다.

    모양은 좁게 잡는다(넓으면 진짜 틀린 변형이 '해석 단계'로 빠져나간다):
      · 근 선택 — 앞: 같은 변수의 서로 다른 수치 후보 ≥2, 뒤: 그중 **하나**
        (후보 밖 값은 선택이 아니다).
      · 대입 — 앞: 변수 v 의 수치 값(들), 뒤: **다른** 변수 w 의 수치 값 하나.
    """
    prev = _numeric_assignments(before)
    nxt = _numeric_assignments(after)
    if prev is None or nxt is None or len(nxt[1]) != 1:
        return None
    var, candidates = prev
    target, (claimed,) = nxt
    if target != var:
        return _SUBSTITUTION, _judge_substitution(verify, var, candidates, target, claimed)
    if _Same.SAME not in [_same(claimed, candidate) for candidate in candidates]:
        return None
    return _SELECTION, _judge_selection(verify, var, claimed)


def _check_c4(verify: Mapping[str, object] | None) -> CheckResult:
    """이웃 단계 연쇄 — 동치 전이는 `verify_solution`, 해석 단계(근 선택·대입)는 조건으로
    판정한다(P3-71).

    해석 단계는 동치가 아니라서 `verify_step` 이 incorrect/판정 불가를 낸다. 그 전이만 모양을 보고
    다시 판정한다: 성립 → 통과, 불성립 → C4_STEP_INCORRECT, 판정 불가 → C4_STEP_UNVERIFIABLE.
    단 `verify_step` 이 incorrect 를 낸 전이는 성립이 증명될 때만 바꾸고, 판정 불가면 incorrect 를
    유지한다(종전 FAIL 을 낮추지 않는다). `verify_step` 이 correct 를 낸 전이는 건드리지 않는다.
    """
    steps = None if verify is None else verify.get("solution_steps")
    if verify is None or not isinstance(steps, list) or len(steps) < 2:
        return _NA  # 단계 자료 부재는 C2 가 사유 코드로 드러낸다(같은 사유를 두 번 세지 않는다)
    texts = [str(s) for s in steps]
    chain = verify_solution(texts)
    states: list[str] = []
    kinds: dict[int, str] = {}
    for index, step in enumerate(chain.steps):
        state = step.state.value
        if state != _CORRECT:
            interpreted = _interpretive_step(verify, texts[index], texts[index + 1])
            if interpreted is not None:
                kinds[index], judged = interpreted
                # 동치 판정이 incorrect 였던 전이는 해석 판정이 **성립을 증명할 때만** 바꾼다 —
                # 근거가 없어 판정 불가인 해석 단계로 종전 FAIL 을 검증 불가로 낮추지 않는다
                # (PR #1703 검토 중4 · 기준 완화 금지가 acceptance ① 보다 상위).
                if state != _INCORRECT or judged == _CORRECT:
                    state = judged
        states.append(state)
    if _INCORRECT in states:
        first = states.index(_INCORRECT)
        kind = f"·해석 단계({kinds[first]})" if first in kinds else ""
        return _fail("C4_STEP_INCORRECT", f"전이 {first}{kind}")
    unjudged = [index for index, state in enumerate(states) if state == _UNJUDGED]
    if unjudged:
        # 해석 단계에서 막힌 전이는 따로 센다 — 사람 검수 대기 목록에서 "조건에 선택·정의 근거가
        # 없다"(생성기 쪽 과제)와 "동치 판정 불가"(판정기 쪽 과제)를 가를 수 있게 한다.
        interpretive = sum(1 for index in unjudged if index in kinds)
        note = f"·해석 단계 {interpretive}" if interpretive else ""
        return _unv("C4_STEP_UNVERIFIABLE", f"{len(unjudged)}/{len(states)}전이{note}")
    return _PASS


# ──────────────────────────────────────────────────────────────────────────
# 문항 판정·집계
# ──────────────────────────────────────────────────────────────────────────
def _guard(compute: Callable[[], CheckResult]) -> CheckResult:
    """검사 하나의 예외는 그 검사만 검증 불가로 만든다 — 예외 타입명을 남긴다(침묵 실패 금지)."""
    try:
        return compute()
    except Exception as exc:  # noqa: BLE001 - 한 검사의 예외로 전수 측정을 잃지 않는다
        return _unv("CHECK_EXCEPTION", type(exc).__name__)


def judge_record(record: Mapping[str, object]) -> ItemResult:
    """문항 1건 → 4검사 결과와 판정."""
    raw_verify = record.get("verify")
    verify = raw_verify if isinstance(raw_verify, dict) else None
    checks = {
        "C1": _guard(lambda: _check_c1(record, verify)),
        "C2": _guard(lambda: _check_c2(record, verify)),
        "C3": _guard(lambda: _check_c3(record)),
        "C4": _guard(lambda: _check_c4(verify)),
    }
    states = {res.state for res in checks.values()}
    if CheckState.FAIL in states:
        verdict = Verdict.FAIL
    elif CheckState.UNVERIFIABLE in states:
        verdict = Verdict.UNVERIFIABLE
    else:
        verdict = Verdict.PASS
    ident = str(record.get("slug") or record.get("problem_id") or "?")
    unit_codes = record.get("unit_codes")
    unit = str(unit_codes[0]) if isinstance(unit_codes, list) and unit_codes else "?"
    return ItemResult(ident=ident, unit=unit, verdict=verdict, checks=checks)


@dataclass(frozen=True, slots=True)
class SolutionQaReport:
    items: tuple[ItemResult, ...]
    multivar_membership: int = field(default=0)
    """C1 이 '소속'으로만 대조한 다변수 문항 수(약한 검사 — 보고용)."""

    @property
    def total(self) -> int:
        return len(self.items)

    def _count(self, verdict: Verdict) -> int:
        return sum(1 for item in self.items if item.verdict is verdict)

    @property
    def passed(self) -> int:
        return self._count(Verdict.PASS)

    @property
    def failed(self) -> int:
        return self._count(Verdict.FAIL)

    @property
    def unverifiable(self) -> int:
        return self._count(Verdict.UNVERIFIABLE)

    @property
    def skipped(self) -> int:
        """`corpus_reverify.ReverifyReport.skipped` 와 같은 뜻의 별칭 — P3-14 가 같게 읽는다."""
        return self.unverifiable

    @property
    def decidable(self) -> int:
        return self.passed + self.failed

    @property
    def pass_rate(self) -> float | None:
        """Solution QA Pass. 판정이 난 문항이 0건이면 None(0%도 100%도 아니다 — 측정 실패)."""
        return None if self.decidable == 0 else self.passed / self.decidable

    @property
    def decidable_ratio(self) -> float | None:
        return None if self.total == 0 else self.decidable / self.total

    @property
    def failures(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (item.ident, item.reason_text()) for item in self.items if item.verdict is Verdict.FAIL
        )

    @property
    def queue(self) -> tuple[ItemResult, ...]:
        """사람 검수 대기 목록 — 기계 검증이 불가능한 문항 전건."""
        return tuple(item for item in self.items if item.verdict is Verdict.UNVERIFIABLE)

    def check_matrix(self) -> dict[str, dict[str, int]]:
        return {
            cid: dict(Counter(item.checks[cid].state.value for item in self.items))
            for cid in CHECK_IDS
        }

    def reason_counts(self, state: CheckState) -> dict[str, int]:
        """(검사,사유) 별 문항 수 — 한 문항이 여러 사유를 가질 수 있다.

        검증 불가 사유는 **판정이 검증 불가인 문항**만 센다. 실패 문항의 부수적인 검증 불가 검사까지
        합치면 사람 검수 대기 목록(`queue`)과 숫자가 어긋난다.
        """
        owner = Verdict.FAIL if state is CheckState.FAIL else Verdict.UNVERIFIABLE
        counter: Counter[str] = Counter()
        for item in self.items:
            if item.verdict is not owner:
                continue
            for cid, res in item.blocking(state):
                counter[f"{cid}:{res.code}"] += 1
        return dict(sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])))

    def unit_breakdown(self) -> dict[str, dict[str, int]]:
        table: dict[str, Counter[str]] = {}
        for item in self.items:
            table.setdefault(item.unit, Counter())[item.verdict.value] += 1
        return {unit: dict(c) for unit, c in sorted(table.items())}


def run_solution_qa(records: Sequence[Mapping[str, object]]) -> SolutionQaReport:
    """레코드 전수 판정 → 집계(순수)."""
    items = tuple(judge_record(record) for record in records)
    multivar = sum(
        1
        for record in records
        if isinstance(record.get("verify"), dict)
        and len(_answer_map_of(cast(Mapping[str, object], record["verify"]))) > 1
        and not cast(Mapping[str, object], record["verify"]).get("answer_kind")
    )
    return SolutionQaReport(items=items, multivar_membership=multivar)


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────
def _pct(value: float | None) -> str:
    return "측정 불가" if value is None else f"{value:.2%}"


def format_report(report: SolutionQaReport, *, scope: str, target: float | None) -> str:
    lines = [
        "=" * 64,
        "Solution QA — 문제·정답·풀이 불일치 기계 검증 (P3-07)",
        "=" * 64,
        f"모집단: {scope}",
        f"총 {report.total}  통과 {report.passed}  실패 {report.failed}  "
        f"검증 불가 {report.unverifiable}",
        f"Solution QA Pass : {report.passed}/{report.decidable} = {_pct(report.pass_rate)}"
        + (
            ""
            if target is None
            else f"  (스코어카드 흡수 목표 ≥{target:.1%} — 참고·합격은 실패 0건)"
        ),
        f"검증 가능 비율    : {report.decidable}/{report.total} = {_pct(report.decidable_ratio)}"
        "  ← 통과율은 이 비율만큼의 문항에 대한 값이다",
        "",
        "[검사별 상태]",
    ]
    for cid, counts in report.check_matrix().items():
        lines.append(f"  {cid} {CHECK_TITLES[cid]}: {counts}")
    lines.append(f"  (C1 다변수 소속 대조 {report.multivar_membership}건 — 약한 검사)")
    unv = report.reason_counts(CheckState.UNVERIFIABLE)
    if unv:
        lines += ["", "[검증 불가 사유 — 사람 검수 대기]"]
        lines += [f"  {code}: {n}건" for code, n in unv.items()]
    if report.failures:
        lines += ["", "[실패 문항]"]
        lines += [f"  {ident}: {why}" for ident, why in report.failures[:_PRINT_FAILURES]]
        if len(report.failures) > _PRINT_FAILURES:
            lines.append(f"  … 외 {len(report.failures) - _PRINT_FAILURES}건 (--json 에 전건)")
    lines.append("=" * 64)
    return "\n".join(lines)


def to_json(report: SolutionQaReport, *, scope: str, target: float | None) -> dict[str, Any]:
    return {
        "scope": scope,
        "target": target,
        "total": report.total,
        "passed": report.passed,
        "failed": report.failed,
        "unverifiable": report.unverifiable,
        "pass_rate": report.pass_rate,
        "decidable_ratio": report.decidable_ratio,
        "check_matrix": report.check_matrix(),
        "fail_reasons": report.reason_counts(CheckState.FAIL),
        "unverifiable_reasons": report.reason_counts(CheckState.UNVERIFIABLE),
        "unit_breakdown": report.unit_breakdown(),
        "multivar_membership": report.multivar_membership,
        "failures": [{"ident": i, "reason": r} for i, r in report.failures],
    }


def _queue_rows(report: SolutionQaReport) -> list[dict[str, Any]]:
    return [
        {
            "ident": item.ident,
            "unit": item.unit,
            "reasons": [
                {"check": cid, "code": res.code, "detail": res.detail}
                for cid, res in item.blocking(CheckState.UNVERIFIABLE)
            ],
        }
        for item in report.queue
    ]


def _load_representative() -> tuple[list[dict[str, object]], str, float] | str:
    """대표 과정 승인 문항 원본 행 + 모집단 설명 + 목표. 못 읽으면 사유 문자열."""
    # 지연 import — ops.phase3_metrics 가 이 모듈을 import 하므로 모듈 수준 import 는 순환이다.
    from whymath_backend.ops import phase3_metrics as pm

    world = pm.load_world()
    if isinstance(world, pm.WorldFailure):
        return f"대표 과정 세계 적재 실패({world.stage}/{world.error_type}): {world.reason}"
    if len(world.qa_records) != world.qa_expected:
        return (
            f"모집단 불일치(적격 {world.qa_expected}건 vs 읽은 행 {len(world.qa_records)}건) — "
            "같은 문항을 검증했다고 말할 수 없다"
        )
    scope = f"대표 과정 승인 문항 {world.qa_expected}건 (P3-14 ④ 와 같은 모집단)"
    return [dict(r) for r in world.qa_records], scope, pm.solution_qa_target()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.solution_qa",
        description="문제·정답·풀이 불일치 기계 검증 — Solution QA Pass 산출(P3-07).",
    )
    parser.add_argument("paths", nargs="*", help="코퍼스 JSONL. 생략하면 대표 과정 승인 문항 전수.")
    parser.add_argument("--json", dest="json_path", type=Path, default=None, help="판정 JSON 저장")
    parser.add_argument(
        "--queue-out", type=Path, default=None, help="사람 검수 대기 목록 JSONL(검증 불가 전건)"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    target: float | None = None  # 표시용 — 종료 코드는 실패 문항 수로 정한다(모듈 docstring)
    records: list[dict[str, object]]
    if args.paths:
        records = []
        for raw_path in args.paths:
            records.extend(_iter_records(Path(raw_path).read_text(encoding="utf-8")))
        scope = f"JSONL {len(args.paths)}개 · {len(records)}건"
    else:
        loaded = _load_representative()
        if isinstance(loaded, str):
            print(f"측정 실패: {loaded}", file=sys.stderr)
            return EXIT_UNMEASURED
        records, scope, absorbed = loaded
        target = absorbed
    if not records:
        print(
            "측정 실패: 검증 대상 문항이 0건이다 — 위반이 없는 것이 아니라 잰 것이 없다.",
            file=sys.stderr,
        )
        return EXIT_UNMEASURED

    report = run_solution_qa(records)
    print(format_report(report, scope=scope, target=target))
    if args.json_path is not None:
        args.json_path.write_text(
            json.dumps(to_json(report, scope=scope, target=target), ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
    if args.queue_out is not None:
        args.queue_out.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in _queue_rows(report)),
            encoding="utf-8",
        )
    if report.pass_rate is None:
        print("측정 실패: 기계 검증이 가능한 문항이 0건이다 — 0%도 100%도 아니다.", file=sys.stderr)
        return EXIT_UNMEASURED
    return EXIT_FAIL if report.failed > 0 else EXIT_OK


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트
    sys.exit(main())
