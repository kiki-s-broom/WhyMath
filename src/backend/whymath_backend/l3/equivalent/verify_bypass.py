"""검산식 우회(동어반복) 판정 — 결정론 관문 '통과'가 실제 검증이었는가 (EOS-207 · 순수·결정론).

왜 필요한가
----------
동등문제 수용 게이트(`acceptance.evaluate_equivalent_candidate`)의 정확성 축은 후보가 스스로 적은
검산식(`verify.conditions`)에 정답(`verify.answer_map`)을 대입해 참인지 본다. 그런데 검산식이
**정답 상수를 그대로 다시 적은 것**(`n = 3`·`v - 24 = 0`)이면, 정답이 틀렸어도 생성기는 틀린 값으로
같은 식을 적으므로 **항상 통과한다** — 검증이 아니라 자기 확인이다. EOS-197 A6 회차 30 CU 중
17건이 이 형태였다(검수 메모 실측 · EOS-205가 생성기 쪽을 고친다). 이 모듈은 그 형태를 **기계로
판정**해서, 자동검증 1차 통과율(EOS-51 §6)이 우회된 통과를 '검증 통과'로 세지 않게 한다.

헌법 R13-01("정답 재도출 검증은 생성 단계의 정답을 입력으로 받지 않는다")의 사후 판정 축이다 —
재진술 검산식은 정답을 입력으로 받은 검증의 가장 단순한 꼴이다.

판정 규칙 (조건 1개 단위 → 검산식 전체로 결합)
---------------------------------------------
조건 1개(`_parse_condition` — Tier1 검산과 **같은 파서**로 읽는다):

- **IDENTITY(무조건 참)** — 등식인데 자유 기호가 하나도 없거나(`2 = 2`), 잔차가 항등적으로
  0이다(`n = n`). 정답이 무엇이든 참이므로 정답을 검증하지 않는다. 정답 변수가 아닌 기호만 쓰는
  등식(`t = 3`, 정답 변수 v)은 IDENTITY가 아니라 UNDECIDABLE이다.
- **RESTATEMENT(정답 재진술)** — 등식이고, 자유 기호가 정답 변수 **하나**뿐이며, 식 원문(AST)에
  나오는 수 리터럴 중 0·1이 아닌 것의 크기 다중집합이 **정답 표기의 그것과 정확히 같다**.
  즉 식이 정답의 수 외에는 아무 수도 쓰지 않는다 — 다시 계산할 재료(문항의 계수·좌표)가 없다.
  예: `n = 3`(정답 3) · `y + 3 = 0`(정답 -3) · `y + 1/2 = 0`(정답 -1/2) · `x - sqrt(2) = 0`.
  0·1을 빼는 이유: `+ 0`·`1*` 같은 항등 연산으로 우회하지 못하게 하려는 것이다(`n = 1*3`도 재진술).
- **RECOMPUTE(재계산)** — 등식이고 정답 변수 하나에 대해, 정답에 없는 수를 써서 정답을 다시 낸다.
  예: `v = 4*3 + 7` · `answer == (2**3 - 5*2 + 2) - 2*(3*2**2 - 5)` · `M**2 - M - 182 = 0`.
- **UNDECIDABLE(판정 불가)** — 파싱 실패 · 부등식·≠ · 정답 변수가 아닌 자유 기호가 섞임 · 정답
  변수가 둘 이상 · 정답 값을 읽지 못함.

검산식 전체(조건 목록):

1. 등식이 하나도 없으면 UNDECIDABLE(부등식만으로는 값을 재계산하지 않는다 — 범위만 준다).
2. 등식 중 RECOMPUTE가 하나라도 있으면 RECOMPUTE(우회 아님).
3. 아니고 등식 중 UNDECIDABLE이 있으면 UNDECIDABLE.
4. 나머지(등식이 전부 RESTATEMENT/IDENTITY)는 **우회**다 — RESTATEMENT가 있으면 RESTATEMENT,
   없으면 IDENTITY. 부등식(도메인 제약)은 값을 정하지 않으므로 이 결합에서 보지 않는다.
검산식이 아예 없거나(`verify` 부재·`conditions` 빈 값) `answer_map`이 비면 UNDECIDABLE이다
(유한 확률 등 다른 검산기를 쓰는 문항일 수 있다 — 모른다 ≠ 아니다).

정직한 한계(있는 척 금지)
-----------------------
- **약한 재계산은 RECOMPUTE로 센다** — `2 = -4 + b`(LLM이 미리 구한 기울기 -4를 쓴 역산)·
  `M**2 - M - 182 = 0`(극값 두 개를 근으로 거꾸로 만든 이차식)은 정답 외의 수를 쓰므로 재진술이
  아니다. 검수자는 이들도 교체를 요구했다(EOS-197 검수 메모) — 이 판정기가 잡는 것은 **가장 강한
  우회(정답 상수 재진술)** 하나이고, "미리 계산한 중간값을 쓴 검산"은 잡지 않는다. 그 축은
  블라인드 재도출(R13-01·EOS-205)의 몫이다.
- `x = 2*3`(정답 6)처럼 문항과 무관한 산술도 RECOMPUTE다 — 수 리터럴이 문항 본문에서 왔는지는
  보지 않는다(본문 대조는 표기 변형에 약해 오탐 위험이 크다).
- **1의 합으로 정답을 쓰면 놓친다** — `x = 1+1+1`(정답 3)은 0·1을 빼면 리터럴이 비어 정답의 `{3}`과
  달라 RECOMPUTE가 된다. 상수 부분식을 접으면 잡히지만 그러면 `4*3 + 7`도 19 하나로 접혀 진짜
  재계산이 재진술로 둔갑한다 — 접지 않는 쪽(미탐)을 택했다. 이 회피는 의도적 산출이라 생성기
  거부(EOS-205)에서 막을 몫이다.
"""

from __future__ import annotations

import ast
import logging
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

import sympy

from whymath_backend.l3.safe_parse import safe_sympify
from whymath_backend.l3.verify_answer import _parse_condition, _relation_sides

__all__ = [
    "BypassKind",
    "ConditionBypass",
    "VerifyBypassVerdict",
    "classify_condition",
    "classify_verify_bypass",
]

logger = logging.getLogger("whymath.l3.equivalent.verify_bypass")


class BypassKind(str, Enum):
    """검산식 판정 4종 — 둘(RESTATEMENT·IDENTITY)은 우회, 하나(RECOMPUTE)는 검증, 하나는 모름."""

    RESTATEMENT = "restatement"
    IDENTITY = "identity"
    RECOMPUTE = "recompute"
    UNDECIDABLE = "undecidable"


# 우회로 세는 종류 — 이 집합 밖의 RECOMPUTE만 "실제 검증"이다.
_BYPASS_KINDS: frozenset[BypassKind] = frozenset({BypassKind.RESTATEMENT, BypassKind.IDENTITY})

# 항등 연산 리터럴 — 재진술 판정의 수 다중집합에서 뺀다(모듈 docstring RESTATEMENT).
_NEUTRAL_LITERALS: frozenset[sympy.Expr] = frozenset({sympy.Integer(0), sympy.Integer(1)})


@dataclass(frozen=True, slots=True)
class ConditionBypass:
    """조건 1개의 판정 — `condition`은 원문 그대로(감사용), `reason`은 판정 근거."""

    condition: str
    kind: BypassKind
    is_equation: bool
    reason: str


@dataclass(frozen=True, slots=True)
class VerifyBypassVerdict:
    """검산식 전체 판정. `bypassed`는 3상태다 — True=우회 · False=재계산 검증 · None=모름."""

    kind: BypassKind
    reason: str
    conditions: tuple[ConditionBypass, ...]

    @property
    def bypassed(self) -> bool | None:
        if self.kind is BypassKind.UNDECIDABLE:
            return None
        return self.kind in _BYPASS_KINDS

    def to_json(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "bypassed": self.bypassed,
            "reason": self.reason,
            "conditions": [
                {
                    "condition": c.condition,
                    "kind": c.kind.value,
                    "is_equation": c.is_equation,
                    "reason": c.reason,
                }
                for c in self.conditions
            ],
        }


def _int_literal(node: ast.AST) -> int | None:
    """정수 리터럴(부호 포함)이면 그 값.

    `-1/2`는 파이썬 AST에서 `(-1)/2`로 읽히므로 부호를 벗겨야 분수 리터럴 하나로 접힌다.
    """
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        inner = _int_literal(node.operand)
        if inner is None:
            return None
        return -inner if isinstance(node.op, ast.USub) else inner
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value
    return None


def _literal_magnitudes(text: str) -> Counter[sympy.Expr] | None:
    """식 원문 → 0·1이 아닌 수 리터럴 크기의 다중집합. 읽지 못하면 None.

    `정수 / 정수`(분수 표기)는 하나의 리터럴로 접는다 — 정답 `-1/2`를 `y + 1/2 = 0`으로 적은 것을
    재진술로 읽으려면 분수 표기가 리터럴 둘로 쪼개지면 안 된다. 그 밖의 연산은 접지 않는다(접으면
    `4*3 + 7`이 리터럴 19 하나가 되어 재계산이 재진술로 둔갑한다).
    """
    stripped = text.strip()
    if not stripped:
        return Counter()
    try:
        safe_sympify(stripped)  # 공식 진입점의 허용 문자·예산 검사를 먼저 통과해야 한다
        tree = ast.parse(stripped.replace("^", "**"), mode="eval")
    except Exception as exc:  # noqa: BLE001 — 읽지 못한 식은 판정 불가(호출부가 UNDECIDABLE)
        logger.debug("verify_bypass 리터럴 수집 불가: %s", type(exc).__name__)
        return None
    found: Counter[sympy.Expr] = Counter()

    def walk(node: ast.AST) -> None:
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            numerator = _int_literal(node.left)
            denominator = _int_literal(node.right)
            if numerator is not None and denominator:
                found[abs(sympy.Rational(numerator, denominator))] += 1
                return
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            found[abs(sympy.nsimplify(node.value))] += 1
            return
        for child in ast.iter_child_nodes(node):
            walk(child)

    walk(tree.body)
    for neutral in _NEUTRAL_LITERALS:
        found.pop(neutral, None)
    return found


def classify_condition(condition: str, answer_map: Mapping[str, object]) -> ConditionBypass:
    """조건 1개를 4종 중 하나로 판정한다(모듈 docstring '판정 규칙').

    `answer_map`은 `verify.answer_map`(정답 변수 → 정답 표기)이다 — 재진술 판정이 정답 표기의 수
    리터럴과 대조하므로 변수 이름만이 아니라 값이 필요하다.
    """
    answer_vars = frozenset(str(k) for k in answer_map)
    try:
        residual, op = _parse_condition(condition)
    except Exception as exc:  # noqa: BLE001 — Tier1과 같은 파서가 거부하면 판정 불가다
        return ConditionBypass(
            condition, BypassKind.UNDECIDABLE, False, f"파싱 불가({type(exc).__name__})"
        )
    if op != "==":
        return ConditionBypass(
            condition, BypassKind.UNDECIDABLE, False, f"등식 아님({op}) — 값을 정하지 않는다"
        )
    free = {str(s) for s in residual.free_symbols}
    if not free:
        return ConditionBypass(
            condition, BypassKind.IDENTITY, True, "자유 기호가 없는 등식 — 정답과 무관하게 참"
        )
    if sympy.simplify(residual) == 0:
        return ConditionBypass(
            condition, BypassKind.IDENTITY, True, "잔차가 항등적으로 0 — 정답과 무관하게 참"
        )
    # 정답 변수가 아닌 기호가 있으면(정답 변수를 아예 안 써도) 값 하나로 정해지지 않는다
    # — 판정 불가.
    # 종전 순서는 `t = 3`(정답 변수 v)을 '정답 변수 미포함'으로 IDENTITY 처리했다(EOS-207 리뷰 P3).
    if not free <= answer_vars:
        return ConditionBypass(
            condition,
            BypassKind.UNDECIDABLE,
            True,
            f"정답 변수 밖의 자유 기호 {sorted(free - answer_vars)} — 값 하나로 정해지지 않는다",
        )
    if len(free) != 1:
        return ConditionBypass(
            condition, BypassKind.UNDECIDABLE, True, "정답 변수 둘 이상이 엮인 등식(연립)"
        )
    (var,) = free
    answer_text = str(next(v for k, v in answer_map.items() if str(k) == var))
    answer_literals = _literal_magnitudes(answer_text)
    if answer_literals is None:
        return ConditionBypass(condition, BypassKind.UNDECIDABLE, True, "정답 표기를 읽지 못함")
    condition_literals: Counter[sympy.Expr] = Counter()
    for side in _relation_sides(condition):
        side_literals = _literal_magnitudes(side)
        if side_literals is None:
            return ConditionBypass(condition, BypassKind.UNDECIDABLE, True, "식 원문 AST 해석 불가")
        condition_literals.update(side_literals)
    if condition_literals == answer_literals:
        return ConditionBypass(
            condition,
            BypassKind.RESTATEMENT,
            True,
            f"정답({answer_text})의 수 외에는 아무 수도 쓰지 않는다 — 다시 계산할 재료가 없다",
        )
    return ConditionBypass(
        condition,
        BypassKind.RECOMPUTE,
        True,
        f"정답에 없는 수로 정답을 다시 낸다(리터럴 {_render_literals(condition_literals)})",
    )


def _render_literals(literals: Counter[sympy.Expr]) -> str:
    """리터럴 다중집합의 결정론 표기 — 감사 사유용."""
    return "{" + ", ".join(sorted(f"{k}×{v}" for k, v in literals.items())) + "}"


def _condition_list(raw: object) -> list[str] | None:
    """`verify.conditions` → 문자열 목록. 형식이 맞지 않으면 None."""
    if isinstance(raw, str):
        return [raw] if raw.strip() else []
    if isinstance(raw, Sequence) and all(isinstance(item, str) for item in raw):
        return [item for item in raw if item.strip()]
    return None


def classify_verify_bypass(verify: Mapping[str, object] | None) -> VerifyBypassVerdict:
    """CU의 `verify` 블록 전체를 판정한다(모듈 docstring '검산식 전체')."""
    if not isinstance(verify, Mapping):
        return VerifyBypassVerdict(BypassKind.UNDECIDABLE, "verify 블록 없음", ())
    conditions = _condition_list(verify.get("conditions"))
    if not conditions:
        return VerifyBypassVerdict(BypassKind.UNDECIDABLE, "검산 조건 없음·형식 불일치", ())
    answer_map = verify.get("answer_map")
    if not isinstance(answer_map, Mapping) or not answer_map:
        return VerifyBypassVerdict(
            BypassKind.UNDECIDABLE, "answer_map 비어 있음 — 정답 변수를 알 수 없다", ()
        )
    judged = tuple(classify_condition(condition, answer_map) for condition in conditions)
    return _combine(judged)


def _combine(judged: tuple[ConditionBypass, ...]) -> VerifyBypassVerdict:
    """조건별 판정 → 검산식 전체 판정(규칙 1~4)."""
    equations = [c for c in judged if c.is_equation]
    if not equations:
        return VerifyBypassVerdict(
            BypassKind.UNDECIDABLE, "등식 없음 — 부등식만으로는 값을 재계산하지 않는다", judged
        )
    kinds = {c.kind for c in equations}
    if BypassKind.RECOMPUTE in kinds:
        return VerifyBypassVerdict(BypassKind.RECOMPUTE, "재계산 등식이 있다", judged)
    if BypassKind.UNDECIDABLE in kinds:
        return VerifyBypassVerdict(BypassKind.UNDECIDABLE, "판정 불가 등식이 있다", judged)
    if BypassKind.RESTATEMENT in kinds:
        return VerifyBypassVerdict(
            BypassKind.RESTATEMENT, "등식이 전부 정답 재진술·무조건 참 — 검증 우회", judged
        )
    return VerifyBypassVerdict(BypassKind.IDENTITY, "등식이 전부 무조건 참 — 검증 우회", judged)
