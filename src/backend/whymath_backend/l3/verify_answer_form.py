"""답 **형태** 판정 — 결정론·SymPy·LLM 0 (EOS-28).

값 동치는 `verify_final_answer`가 본다. 이 모듈은 **다른 질문**에 답한다:
학생이 문항의 표기 지시를 실제로 따랐는가?

────────────────────────────────────────────────────────────────────────────
왜 값이 아니라 **표면**을 봐야 하는가
────────────────────────────────────────────────────────────────────────────
`2/72`와 `1/36`은 값이 같다. 형태 요구는 정확히 그 *같은 값들 사이*를 가르는 축이므로,
값으로 판정하면 아무것도 가를 수 없다. 그래서 표면 표기를 보존한 채 파싱한다:

    sympify("2/72")                  → 1/36   (즉시 약분 — 표면 소실)
    sympify("2/72", evaluate=False)  → 2/72   (표면 보존 ✔ 2026-09-01 실측)

이것은 이 저장소의 "표현 ≠ 의미" 원칙의 한 사례다 — 형태는 *표현* 축에 산다.

────────────────────────────────────────────────────────────────────────────
교수학 계약 (어기면 학생이 다친다)
────────────────────────────────────────────────────────────────────────────
1. **형태 위반은 오답이 아니다.** 이 모듈은 `correct`/`incorrect`를 만들지 않는다 —
   `FormVerdict`라는 별도 어휘만 낸다. 값 판정에 영향을 주는 경로가 코드에 없다.
2. **제출을 막지 않는다.** 판정은 사후 관찰이며, 입력 거부 신호를 내지 않는다
   (학생 입력 거부 금지).
3. **모르면 모른다고 한다.** 파싱 실패·미지 어휘는 `unverifiable`이며 절대
   `satisfied`로도 `violated`로도 접지 않는다. 판정 못 한 것을 위반이라 부르면
   학생이 맞은 답으로 부정 피드백을 받는다.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from sympy import Float, Integer, Rational, fraction

from whymath_backend.l3.safe_parse import safe_sympify
from whymath_backend.l3.symbolic_equivalence import split_relation_chain
from whymath_backend.schema.answer_form import (
    ExpectedForm,
    FormVerdict,
    strict_expected_form_of,
)

__all__ = ["verify_answer_form", "form_verdict_for"]

logger = logging.getLogger("whymath.l3.verify_answer_form")


def verify_answer_form(student_answer: str | None, expected: ExpectedForm | None) -> FormVerdict:
    """학생 답의 표기가 `expected` 형태를 만족하는지 4상태로 판정한다.

    `expected`가 `None`이면 판정 대상이 아니므로 `not_required`. 값 판정과 독립이며,
    이 함수는 정답을 **인자로 받지도 않는다** — 형태는 정답을 몰라도 판정할 수 있고,
    받지 않으면 정답이 이 경로로 샐 수 없다.
    """
    if expected is None:
        return FormVerdict.not_required
    if student_answer is None or not student_answer.strip():
        # 빈 제출 — 형태를 논할 대상이 없다. 위반이 아니다(제출 안 한 것을 어겼다고 하지 않는다).
        return FormVerdict.unverifiable
    if expected is ExpectedForm.reduced_fraction:
        return _check_reduced_fraction(_submitted_value(student_answer))
    # 어휘에는 있으나 검증기가 아직 없는 형태 — 있다고 위장하지 않는다.
    return FormVerdict.unverifiable


def form_verdict_for(student_answer: str | None, answer_constraint: Any) -> FormVerdict:
    """문항 제약에서 요구를 읽어 바로 판정 — 호출부용 단일 진입점.

    저작 오타(모르는 어휘)를 `not_required`로 흘리지 않는다. 요구가 *적혀 있는데* 우리가
    모르면 그것은 "요구 없음"이 아니라 판정 불가다(침묵 실패 금지).
    """
    expected, known = strict_expected_form_of(answer_constraint)
    if not known:
        return FormVerdict.unverifiable
    return verify_answer_form(student_answer, expected)


def _submitted_value(student_answer: str) -> str:
    """등식형 제출에서 **학생이 낸 값**을 표면 그대로 뽑는다 (리뷰 지적 2026-09-01).

    구조화된 풀이 단계는 최종답을 `x = 1/36` 같은 **배정 형태**로 적는 것이 흔하다. 그런데
    등식 전체를 SymPy에 넘기면 파싱이 실패해 판정이 전부 `unverifiable`이 된다 — 실측:

        x=1/36  값=correct  형태=unverifiable   ← 지시를 지켰는데 신호가 사라진다
        x=2/72  값=correct  형태=unverifiable   ← 어겼는데도 사라진다

    즉 값 판정은 등식을 읽는데 형태 판정만 못 읽어, **가장 흔한 제출 형태에서 기능이 통째로
    무력**했다. 준수·위반 양쪽이 같은 값(`unverifiable`)이 되므로 변별력 0이다.

    `split_relation_chain`을 쓰는 이유: 그것이 **정규화 전 원문 조각**을 돌려주기 때문이다
    (docstring 자인). 형태는 표면 축이라 정규화하는 파서(`read_equation_step`은 해집합을
    낸다)는 쓸 수 없다. 등호가 없으면 원문 그대로, 비교·부등이 섞이면(ValueError) 원문 그대로
    넘겨 아래 파싱이 판정 불가로 처리하게 둔다 — 여기서 삼키지 않는다.

    연쇄 등식 `a=b=c`는 **마지막 항**을 취한다(학생이 도달한 최종 표기).
    """
    try:
        pairs = split_relation_chain(student_answer)
    except ValueError:
        return student_answer  # 등식 체인이 아니다 — 원문 그대로 판정 경로로
    if not pairs:
        return student_answer  # 등호 없음 — 값 자체가 제출됐다
    return pairs[-1][1]


def _check_reduced_fraction(student_answer: str) -> FormVerdict:
    """기약분수 판정 — 분자·분모가 서로소인가.

    판정표(실측 근거는 모듈 docstring):
      `1/36` → satisfied  ·  `2/72` → violated  ·  `3`(정수) → satisfied(gcd(3,1)=1)
      `0.5`(소수) → violated — 분수로 나타내라 했는데 소수로 냈다
      `x/2`(문자식)·파싱 실패 → unverifiable
    """
    try:
        # CONST-09: 학생 원문이 닿는 자리 — 안전 진입점(표면 보존 evaluate=False는 그대로).
        expr = safe_sympify(student_answer.strip(), evaluate=False)
    except Exception as exc:  # noqa: BLE001 — SymPy는 다양한 예외를 낸다
        # 예외 타입명을 남긴다(무타입 침묵 금지). 값은 학생 원문이라 로그에 싣지 않는다.
        # (종전 `_ = type(exc).__name__`은 타입명을 *계산만* 하고 버렸다 — 로그로 옮긴다.)
        logger.debug("verify_answer_form 파싱 회피: %s", type(exc).__name__)
        return FormVerdict.unverifiable

    if not getattr(expr, "is_number", False):
        return FormVerdict.unverifiable  # 문자식 — 이 형태의 판정 대상이 아니다

    numerator, denominator = fraction(expr)

    # 소수 표기(Float)는 분수 표기가 아니다. `fraction(0.5)` = (0.5, 1)로 분모가 1이라
    # 정수와 구별되지 않으므로 **타입으로** 먼저 가른다 — 이 검사가 없으면 0.5가 통과한다.
    if isinstance(numerator, Float) or isinstance(denominator, Float):
        return FormVerdict.violated

    if not (isinstance(numerator, (Integer, Rational)) and isinstance(denominator, Integer)):
        return FormVerdict.unverifiable

    try:
        p, q = int(numerator), int(denominator)
    except (TypeError, ValueError):
        return FormVerdict.unverifiable

    if q == 0:
        return FormVerdict.unverifiable
    return FormVerdict.satisfied if math.gcd(abs(p), abs(q)) == 1 else FormVerdict.violated
