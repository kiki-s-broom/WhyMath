"""수열 귀납 검증기 — SymPy 불가 영역 v2 단계 B 도메인 2(S4-66).

귀납적으로(점화식으로) 정의된 수열을 **정확 산술**로 실제 실행해 답을 대조한다. 설계 정본은
`docs/architecture/verifier_v2_domains.md` §5. 정수는 `int`, 유리수는 `fractions.Fraction`으로
계산하고 부동소수점은 쓰지 않는다 — 답 비교도 `==` 정확 일치뿐이다(허용오차 없음).

왜 `math.isclose`를 쓰지 않는가: `a(n+1)=2*a(n)+1, a(1)=1`의 `a(30)`은 1073741823이다. 정답에
1을 더한 1073741824는 `isclose(rel_tol=1e-9)`로 보면 **같은 값**이라 통과한다(설계서 §6.1 실측).
점화식 수열은 항이 정수라 "1 차이"가 곧 오답이므로 허용오차를 두는 순간 오답이 통과한다.

DSL(`verify.conditions`) — 절은 `;`로 구분, 키는 `start`·`init`·`rec`·`query`:
    init=a(1)=7; rec=a(n+1)=a(n)+6; query=a(12)
    init=a(1)=1,a(2)=1; rec=a(n+2)=a(n+1)+a(n); query=a(10)
    init=a(1)=1; rec=a(n+1)=if(n%2==1, a(n)+2, 2*a(n)); query=S(6)
    init=a(1)=3; rec=a(n+1)=5*a(n); query=closed(a(n)=3*5^(n-1), upto=12)

질의: `a(N)`(N번째 항 — N은 **항 번호**) · `S(N)`·`terms(N)`(첫 **N항**의 합/목록 — N은
**항 개수**라 `start=0`이면 a(0)..a(N-1)이다) · `closed(a(n)=식, upto=M)`(시작 항~항 번호 M에서
폐형과 점화식 값이 모두 같으면 1, 아니면 0).

식 평가는 `eval`·`sympify`를 쓰지 않는다. 입력 문자를 허용 집합으로 거른 뒤 파이썬 `ast`로 **구문
분석만** 하고(실행 없음), 허용 노드 화이트리스트를 통과한 트리를 이 모듈의 평가기가 `Fraction`으로
직접 접어 올린다. 지수 `^`는 식(n만 포함)이며 평가값이 0 이상 64 이하 정수여야 한다 — 설계서 §5.4는
"정수 리터럴"이라 적었으나 같은 절의 예시 `closed(a(n)=3*5^(n-1), ...)`가 n-의존 지수를 쓰므로 이쪽
(리터럴은 구문 분석 시점, n-의존은 평가 시점에 같은 범위를 검사)으로 조화시켰다.

**자원 상한**(초과는 `fail`이 아니라 `unverifiable` — "정답이 틀렸다"는 거짓 신호가 되기 때문):
단계 수 N ≤ 1000 · 항/중간값 비트 길이 ≤ 65,536 · 거듭제곱 지수 ≤ 64 · 식 노드 수 ≤ 64.
`a(n+1)=a(n)^2`에 `a(1)=2`를 주면 n=17에서 비트 길이 한도를 넘는다(가상의 위험이 아님).

**알려진 한계**: 파이썬 정수→문자열 변환은 4,300자리 이하만 허용하므로(`sys.set_int_max_str_digits`
기본값) 그보다 큰 정수는 답 문자열로 읽지도 쓰지도 못한다 — 읽기는 `unverifiable`, 쓰기(교차검증용
정확값 문자열)는 빈 문자열이다. 전역 한도를 건드리지 않는다.

7계층: L3 지역. 순수 계산(표준 라이브러리 + `VerificationTier` 열거형만) — DB 0·LLM 0·SymPy 0.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Literal

from whymath_backend.l3.verification_tier import VerificationTier

__all__ = [
    "MAX_AST_NODES",
    "MAX_BITS",
    "MAX_POW_EXPONENT",
    "MAX_STEPS",
    "SEQUENCE_MACHINE_AXIS",
    "ExactValue",
    "SequenceInductionError",
    "SequenceModel",
    "SequenceQuery",
    "SequenceRangeError",
    "SequenceResult",
    "SequenceVerification",
    "describe_sequence_model_ko",
    "execute_sequence_model",
    "format_exact_value",
    "parse_exact_value",
    "parse_sequence_model",
    "verify_sequence_induction",
]

# ── 자원 상한(설계서 §5.2) ─────────────────────────────────────────────────
MAX_STEPS = 1000
MAX_BITS = 65_536
MAX_POW_EXPONENT = 64
MAX_AST_NODES = 64

_MAX_CONDITIONS_LEN = 2_000
_MAX_EXPR_LEN = 300
_MAX_ANSWER_LEN = 20_000
# 정확값 문자열로 직렬화할 정수의 비트 상한 — 4,300자리(≈14,284비트) 미만으로 묶는다.
_MAX_SERIALIZED_BITS = 13_000

SEQUENCE_MACHINE_AXIS = "점화식 정확 산술 실행"

_RESIDUAL_BASE: tuple[str, ...] = ("발문↔점화식 정합", "인덱스 시작점·초기항 완비성")
_RESIDUAL_BRANCH = "분기 조건 해석"
_RESIDUAL_GENERAL = "모든 n에 대한 일반 주장"

ExactValue = Fraction | tuple[Fraction, ...]
QueryKind = Literal["term", "sum", "terms", "closed"]


class SequenceInductionError(ValueError):
    """DSL 파싱·모델 구성·실행 실패 — 조용한 통과 금지(호출자가 unverifiable로 변환)."""


class SequenceRangeError(SequenceInductionError):
    """자원 상한 초과 — fail이 아니라 unverifiable(사유 "범위 초과")로 돌려보낸다."""


@dataclass(frozen=True, slots=True)
class SequenceQuery:
    """질의 1건. `closed`면 `closed_tree`(n만 포함하는 폐형 식)를 든다."""

    kind: QueryKind
    n: int
    closed_source: str = ""
    closed_tree: ast.expr | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True, slots=True)
class SequenceModel:
    """형식 모델 = 첫 항 번호 + 초기항 + 점화식(트리) + 질의."""

    start: int
    inits: tuple[Fraction, ...]
    order: int
    rec_source: str
    rec_tree: ast.expr = field(compare=False, repr=False)
    query: SequenceQuery
    has_branch: bool
    source: str


@dataclass(frozen=True, slots=True)
class SequenceResult:
    """정확 실행 결과 — `value`는 스칼라(`Fraction`) 또는 목록(`tuple[Fraction, ...]`)."""

    value: ExactValue
    terms_computed: int


@dataclass(frozen=True, slots=True)
class SequenceVerification:
    """`verify_sequence_induction`의 산출 — 판정 + 잔여 축 + 등급 + 교차검증 재료.

    `unverifiable`이면 `residual_axes`는 비고 `tier`는 None이다(기계가 아무 축도 닫지 못함).
    """

    state: Literal["pass", "fail", "unverifiable"]
    reason: str | None
    samples_checked: int
    residual_axes: tuple[str, ...]
    tier: VerificationTier | None
    model: SequenceModel | None
    result: SequenceResult | None


# ──────────────────────────────────────────────────────────────────────────
# 정확값 문자열 ↔ Fraction
# ──────────────────────────────────────────────────────────────────────────
_SCALAR_RE = re.compile(r"\s*(-?\d+)\s*(?:/\s*(\d+)\s*)?")


def _parse_scalar(raw: object) -> Fraction | None:
    """정수 또는 `p/q` 하나를 정확 유리수로. 소수·근삿값·bool은 None(정확하지 않다)."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return Fraction(raw)
    if isinstance(raw, str):
        if len(raw) > _MAX_ANSWER_LEN:
            return None
        match = _SCALAR_RE.fullmatch(raw)
        if match is None:
            return None
        try:
            numerator = int(match.group(1))
            denominator = int(match.group(2)) if match.group(2) else 1
        except ValueError:  # 4,300자리 초과 정수
            return None
        if denominator == 0:
            return None
        return Fraction(numerator, denominator)
    return None


def parse_exact_value(raw: object) -> ExactValue | None:
    """답/재계산값 → 정확값. 정수·`p/q`·그 목록(`[1, 3, 6]`·`1, 3, 6`·JSON 배열)만 읽는다.

    읽을 수 없으면 None — 호출자가 `unverifiable`(검증기) 또는 `unclear`(교차검증 판정기)로
    돌린다. 소수(`0.5`)·부동소수(`73.0`)는 *정확하다고 말할 수 없으므로* 읽지 않는다.
    """
    if isinstance(raw, (list, tuple)):
        if not raw:
            return None
        items = [_parse_scalar(item) for item in raw]
        if any(item is None for item in items):
            return None
        return tuple(item for item in items if item is not None)
    if isinstance(raw, str):
        text = raw.strip()
        bracketed = text.startswith("[") and text.endswith("]")
        if bracketed:
            text = text[1:-1]
        if bracketed or "," in text:
            parts = [_parse_scalar(part) for part in text.split(",")]
            if not parts or any(part is None for part in parts):
                return None
            return tuple(part for part in parts if part is not None)
        return _parse_scalar(text)
    return _parse_scalar(raw)


def _format_scalar(value: Fraction) -> str | None:
    """정확 직렬화 — 4,300자리 변환 한도를 넘는 값은 None(말없이 잘라 쓰지 않는다)."""
    if max(value.numerator.bit_length(), value.denominator.bit_length()) > _MAX_SERIALIZED_BITS:
        return None
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def format_exact_value(value: ExactValue) -> str:
    """정확값 → 문자열(`73`·`1/2`·`[1, 3, 6]`). 직렬화할 수 없을 만큼 크면 빈 문자열."""
    if isinstance(value, tuple):
        parts = [_format_scalar(item) for item in value]
        if any(part is None for part in parts):
            return ""
        return "[" + ", ".join(part for part in parts if part is not None) + "]"
    return _format_scalar(value) or ""


def _display(value: Fraction) -> str:
    """사유·서술용 표기 — 큰 값은 비트 수로 줄인다(사유 문자열 비대화 방지)."""
    text = _format_scalar(value)
    if text is None:
        bits = max(value.numerator.bit_length(), value.denominator.bit_length())
        return f"(약 {bits}비트 값)"
    return text if len(text) <= 60 else f"{text[:28]}…{text[-28:]}"


def _display_exact(value: ExactValue) -> str:
    if isinstance(value, tuple):
        shown = ", ".join(_display(item) for item in value[:8])
        return f"[{shown}{', …' if len(value) > 8 else ''}]"
    return _display(value)


# ──────────────────────────────────────────────────────────────────────────
# 식 구문 분석(ast, 실행 없음) + 화이트리스트 검증
# ──────────────────────────────────────────────────────────────────────────
_ALLOWED_EXPR_CHARS = re.compile(r"[0-9nafi\s()+\-*/^%=!,]+")
_IF_CALL = re.compile(r"(?<![A-Za-z0-9_])if\s*\(")


def _constant_int(node: ast.expr) -> int | None:
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and not isinstance(node.value, bool)
    ):
        return node.value
    return None


def _a_offset(arg: ast.expr) -> int | None:
    """`a(...)`의 인자가 `n`이면 0, `n+1`이면 1, 그 밖은 None."""
    if isinstance(arg, ast.Name) and arg.id == "n":
        return 0
    if (
        isinstance(arg, ast.BinOp)
        and isinstance(arg.op, ast.Add)
        and isinstance(arg.left, ast.Name)
        and arg.left.id == "n"
        and _constant_int(arg.right) == 1
    ):
        return 1
    return None


def _condition_parts(node: ast.expr) -> tuple[int, bool, int]:
    """분기 조건 `n%M==R` / `n%M!=R` → (M, 등호 여부, R). 그 밖의 형태는 거부."""
    if not (isinstance(node, ast.Compare) and len(node.ops) == 1 and len(node.comparators) == 1):
        raise SequenceInductionError("분기 조건은 n%정수==정수 또는 n%정수!=정수만 허용")
    op = node.ops[0]
    if not isinstance(op, (ast.Eq, ast.NotEq)):
        raise SequenceInductionError("분기 조건의 비교는 == 또는 !=만 허용")
    left = node.left
    if not (
        isinstance(left, ast.BinOp)
        and isinstance(left.op, ast.Mod)
        and isinstance(left.left, ast.Name)
        and left.left.id == "n"
    ):
        raise SequenceInductionError("분기 조건의 좌변은 n%정수 형태여야 함")
    modulus = _constant_int(left.right)
    remainder = _constant_int(node.comparators[0])
    if modulus is None or modulus < 1 or remainder is None or remainder < 0:
        raise SequenceInductionError("분기 조건의 법과 나머지는 정수 리터럴(법 ≥ 1, 나머지 ≥ 0)")
    return modulus, isinstance(op, ast.Eq), remainder


def _validate_expr(node: ast.expr, offsets: frozenset[int]) -> None:
    """화이트리스트 검증. `offsets`는 허용되는 `a(n+k)`의 k 집합(폐형·지수는 빈 집합)."""
    if isinstance(node, ast.Constant):
        if _constant_int(node) is None:
            raise SequenceInductionError("정수 리터럴만 허용(소수는 p/q 분수로 쓴다)")
        return
    if isinstance(node, ast.Name):
        if node.id != "n":
            raise SequenceInductionError(f"미지 이름 {node.id!r} — 식에는 n과 a(...)만 쓴다")
        return
    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, (ast.USub, ast.UAdd)):
            raise SequenceInductionError("허용되지 않는 단항 연산자")
        _validate_expr(node.operand, offsets)
        return
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, ast.Pow):
            literal = _constant_int(node.right)
            if literal is not None and not 0 <= literal <= MAX_POW_EXPONENT:
                raise SequenceRangeError(
                    f"거듭제곱 지수 {literal}가 허용 범위 0..{MAX_POW_EXPONENT}를 벗어남"
                )
            _validate_expr(node.left, offsets)
            _validate_expr(node.right, frozenset())  # 지수에는 항 참조 a(...) 금지
            return
        if not isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            raise SequenceInductionError("허용되지 않는 이항 연산자(+ - * / ^ 만 허용)")
        _validate_expr(node.left, offsets)
        _validate_expr(node.right, offsets)
        return
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
        if node.func.id == "a" and len(node.args) == 1:
            offset = _a_offset(node.args[0])
            if offset is None or offset not in offsets:
                raise SequenceInductionError("이 위치에서 허용되지 않는 항 참조 a(...)")
            return
        if node.func.id == "_if" and len(node.args) == 3:
            _condition_parts(node.args[0])
            _validate_expr(node.args[1], offsets)
            _validate_expr(node.args[2], offsets)
            return
        raise SequenceInductionError("허용되지 않는 함수 호출(a(...)·if(...)만 허용)")
    raise SequenceInductionError(f"허용되지 않는 식 요소 {type(node).__name__}")


def _parse_expr(source: str, offsets: frozenset[int]) -> tuple[ast.expr, bool]:
    """식 문자열 → (검증된 ast 트리, 분기 사용 여부). 실행하지 않는다."""
    text = " ".join(source.split())
    if not text:
        raise SequenceInductionError("식이 비어 있음")
    if len(text) > _MAX_EXPR_LEN:
        raise SequenceRangeError(f"식 길이 {len(text)}가 한도 {_MAX_EXPR_LEN} 초과")
    if _ALLOWED_EXPR_CHARS.fullmatch(text) is None:
        raise SequenceInductionError("식에 허용되지 않는 문자가 있음")
    has_branch = _IF_CALL.search(text) is not None
    python_text = _IF_CALL.sub("_if(", text).replace("^", "**")
    try:
        tree = ast.parse(python_text, mode="eval").body
    except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
        raise SequenceInductionError(f"식 구문 오류({type(exc).__name__})") from exc
    node_count = sum(isinstance(node, ast.expr) for node in ast.walk(tree))
    if node_count > MAX_AST_NODES:
        raise SequenceRangeError(f"식 노드 수 {node_count}가 한도 {MAX_AST_NODES} 초과")
    _validate_expr(tree, offsets)
    return tree, has_branch


# ──────────────────────────────────────────────────────────────────────────
# DSL 파서
# ──────────────────────────────────────────────────────────────────────────
_CLAUSE_KEYS = frozenset({"start", "init", "rec", "query"})
_INIT_ENTRY = re.compile(r"a\((\d+)\)\s*=\s*(-?\d+(?:\s*/\s*\d+)?)")
_REC_CLAUSE = re.compile(r"a\(n\+([12])\)\s*=\s*(.+)")
_QUERY_SIMPLE = re.compile(r"(a|S|terms)\(\s*(\d+)\s*\)")
_QUERY_CLOSED = re.compile(r"closed\(\s*a\(n\)\s*=\s*(.+),\s*upto\s*=\s*(\d+)\s*\)")


def _split_clauses(conditions: str) -> dict[str, str]:
    if len(conditions) > _MAX_CONDITIONS_LEN:
        raise SequenceRangeError(f"조건 길이 {len(conditions)}가 한도 {_MAX_CONDITIONS_LEN} 초과")
    clauses: dict[str, str] = {}
    for piece in conditions.split(";"):
        text = " ".join(piece.split())
        if not text:
            continue
        key, separator, value = text.partition("=")
        key = key.strip()
        if not separator:
            raise SequenceInductionError("절 형식 오류(키=값이 아님)")
        if key not in _CLAUSE_KEYS:
            raise SequenceInductionError(f"미지 절 키: {key!r}")
        if key in clauses:
            raise SequenceInductionError(f"절 중복: {key}")
        clauses[key] = value.strip()
    return clauses


def _parse_inits(raw: str, start: int, order: int) -> tuple[Fraction, ...]:
    """초기항 절 — 번호가 start..start+order-1과 정확히 일치해야 한다(부족·초과·불연속 거부)."""
    found: dict[int, Fraction] = {}
    for entry in raw.split(","):
        match = _INIT_ENTRY.fullmatch(" ".join(entry.split()))
        if match is None:
            raise SequenceInductionError("초기항 형식 오류(a(정수)=정수 또는 a(정수)=p/q)")
        index = int(match.group(1))
        value = _parse_scalar(match.group(2))
        if value is None:
            raise SequenceInductionError("초기항 값을 읽을 수 없음(분모 0 등)")
        if index in found:
            raise SequenceInductionError(f"초기항 a({index}) 중복")
        found[index] = value
    expected = list(range(start, start + order))
    if sorted(found) != expected:
        raise SequenceInductionError(
            f"초기항 번호가 {expected}와 달라야 함 — 점화식 {order}단계는 초기항 {order}개가 "
            f"시작 항({start})부터 연속으로 필요(실제 {sorted(found)})"
        )
    return tuple(found[index] for index in expected)


def _parse_query(raw: str, start: int) -> SequenceQuery:
    simple = _QUERY_SIMPLE.fullmatch(raw)
    if simple is not None:
        function, number = simple.group(1), int(simple.group(2))
        if number > MAX_STEPS:
            raise SequenceRangeError(f"질의 번호 {number}가 단계 한도 {MAX_STEPS} 초과")
        if function == "a":
            if number < start:
                raise SequenceInductionError(
                    f"질의 항 번호 {number}가 시작 항 번호 {start}보다 작음"
                )
            return SequenceQuery(kind="term", n=number)
        if number < 1:
            raise SequenceInductionError("S(N)·terms(N)의 N은 항 개수라 1 이상이어야 함")
        return SequenceQuery(kind="sum" if function == "S" else "terms", n=number)
    closed = _QUERY_CLOSED.fullmatch(raw)
    if closed is not None:
        upto = int(closed.group(2))
        if upto > MAX_STEPS:
            raise SequenceRangeError(f"closed의 upto {upto}가 단계 한도 {MAX_STEPS} 초과")
        if upto < start:
            raise SequenceInductionError(f"closed의 upto {upto}가 시작 항 번호 {start}보다 작음")
        tree, _ = _parse_expr(closed.group(1), frozenset())
        return SequenceQuery(
            kind="closed",
            n=upto,
            closed_source=" ".join(closed.group(1).split()),
            closed_tree=tree,
        )
    raise SequenceInductionError(
        "질의 형식 오류(a(N)·S(N)·terms(N)·closed(a(n)=식, upto=M)만 허용 — 극한·수렴은 SymPy 소관)"
    )


def parse_sequence_model(conditions: str) -> SequenceModel:
    """`verify.conditions` 문자열 → `SequenceModel`. 형식 오류는 `SequenceInductionError`."""
    clauses = _split_clauses(conditions)
    missing = [key for key in ("init", "rec", "query") if key not in clauses]
    if missing:
        raise SequenceInductionError(f"필수 절 누락: {', '.join(missing)}")

    start_raw = clauses.get("start", "1")
    if start_raw not in ("0", "1"):
        raise SequenceInductionError("start는 0 또는 1만 허용")
    start = int(start_raw)

    rec_match = _REC_CLAUSE.fullmatch(clauses["rec"])
    if rec_match is None:
        raise SequenceInductionError("rec 형식 오류(a(n+1)=식 또는 a(n+2)=식)")
    order = int(rec_match.group(1))
    offsets = frozenset({0}) if order == 1 else frozenset({0, 1})
    rec_tree, rec_branch = _parse_expr(rec_match.group(2), offsets)

    inits = _parse_inits(clauses["init"], start, order)
    query = _parse_query(clauses["query"], start)
    closed_branch = query.closed_tree is not None and any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_if"
        for node in ast.walk(query.closed_tree)
    )
    return SequenceModel(
        start=start,
        inits=inits,
        order=order,
        rec_source=" ".join(rec_match.group(2).split()),
        rec_tree=rec_tree,
        query=query,
        has_branch=rec_branch or closed_branch,
        source=conditions,
    )


# ──────────────────────────────────────────────────────────────────────────
# 정확 평가기(Fraction)
# ──────────────────────────────────────────────────────────────────────────
def _bits(value: Fraction) -> int:
    return max(value.numerator.bit_length(), value.denominator.bit_length())


def _check_bits(value: Fraction) -> Fraction:
    if _bits(value) > MAX_BITS:
        raise SequenceRangeError(f"항 비트 길이가 한도 {MAX_BITS}를 초과")
    return value


def _eval(node: ast.expr, n: int, cur: Fraction | None, nxt: Fraction | None) -> Fraction:
    """검증된 트리를 정확 산술로 접는다. `cur`=a(n), `nxt`=a(n+1)(없으면 None)."""
    if isinstance(node, ast.Constant):
        literal = _constant_int(node)
        if literal is None:  # 검증을 통과한 트리에는 없다 — 방어
            raise SequenceInductionError("정수 리터럴이 아님")
        return Fraction(literal)
    if isinstance(node, ast.Name):
        return Fraction(n)
    if isinstance(node, ast.UnaryOp):
        operand = _eval(node.operand, n, cur, nxt)
        return -operand if isinstance(node.op, ast.USub) else operand
    if isinstance(node, ast.BinOp):
        left = _eval(node.left, n, cur, nxt)
        if isinstance(node.op, ast.Pow):
            exponent = _eval(node.right, n, None, None)
            if exponent.denominator != 1 or not 0 <= exponent <= MAX_POW_EXPONENT:
                raise SequenceRangeError(
                    f"거듭제곱 지수가 0..{MAX_POW_EXPONENT} 정수여야 함(실제 {_display(exponent)})"
                )
            power = int(exponent)
            if _bits(left) * power > MAX_BITS:  # 계산 전에 거절 — 거대 정수를 만들지 않는다
                raise SequenceRangeError(f"거듭제곱 결과가 비트 길이 한도 {MAX_BITS}를 초과")
            return _check_bits(left**power)
        right = _eval(node.right, n, cur, nxt)
        if isinstance(node.op, ast.Add):
            return _check_bits(left + right)
        if isinstance(node.op, ast.Sub):
            return _check_bits(left - right)
        if isinstance(node.op, ast.Mult):
            return _check_bits(left * right)
        if right == 0:
            raise SequenceInductionError("0으로 나눔 — 수열이 정의되지 않음")
        return _check_bits(left / right)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id == "a":
            offset = _a_offset(node.args[0])
            referenced = cur if offset == 0 else nxt
            if referenced is None:  # 검증을 통과한 트리에는 없다 — 방어
                raise SequenceInductionError("참조할 수 없는 항")
            return referenced
        modulus, want_equal, remainder = _condition_parts(node.args[0])
        taken = (n % modulus == remainder) == want_equal
        return _eval(node.args[1] if taken else node.args[2], n, cur, nxt)  # 선택 가지만 평가
    raise SequenceInductionError(f"평가할 수 없는 식 요소 {type(node).__name__}")


def _compute_terms(model: SequenceModel, last_index: int) -> list[Fraction]:
    """a(start)..a(last_index) — `terms[i] == a(start + i)`."""
    terms = list(model.inits)
    index = model.start + len(terms) - 1
    while index < last_index:
        index += 1
        n = index - model.order  # a(n+order) = 식(n, a(n), a(n+1))
        current = terms[-model.order]
        following = terms[-1] if model.order == 2 else None
        terms.append(_check_bits(_eval(model.rec_tree, n, current, following)))
    return terms[: last_index - model.start + 1]


def execute_sequence_model(model: SequenceModel) -> SequenceResult:
    """질의를 정확 실행한다. 자원 상한 초과는 `SequenceRangeError`."""
    query = model.query
    if query.kind == "term":
        terms = _compute_terms(model, query.n)
        return SequenceResult(value=terms[query.n - model.start], terms_computed=len(terms))
    if query.kind in ("sum", "terms"):
        terms = _compute_terms(model, model.start + query.n - 1)
        if query.kind == "terms":
            return SequenceResult(value=tuple(terms), terms_computed=len(terms))
        return SequenceResult(value=_check_bits(sum(terms, Fraction(0))), terms_computed=len(terms))
    # closed — 시작 항부터 upto까지 폐형과 점화식 값이 모두 같은가
    terms = _compute_terms(model, query.n)
    closed_tree = query.closed_tree
    if closed_tree is None:  # parse_sequence_model이 항상 채운다 — 방어
        raise SequenceInductionError("closed 질의에 폐형 식이 없음")
    for offset, term in enumerate(terms):
        if _eval(closed_tree, model.start + offset, None, None) != term:
            return SequenceResult(value=Fraction(0), terms_computed=len(terms))
    return SequenceResult(value=Fraction(1), terms_computed=len(terms))


# ──────────────────────────────────────────────────────────────────────────
# 서술(교차검증 관점 ③ 입력) · 검증 진입점
# ──────────────────────────────────────────────────────────────────────────
def describe_sequence_model_ko(model: SequenceModel) -> str:
    """기계가 실행한 수열 **정의**를 한국어로 — 계산 결과 값은 싣지 않는다(번역 대조 전용).

    관점 ③(`sequence_grounding`)은 "발문과 같은 수열을 실행했는가"만 보므로 결과 값을 숨겨
    값 앵커링을 막고, 값 대조는 관점 ①이 기계 정확 일치로 한다.
    """
    inits = ", ".join(
        f"a({model.start + offset})={_display(value)}" for offset, value in enumerate(model.inits)
    )
    query = model.query
    if query.kind == "term":
        asked = f"구하는 것: a({query.n})의 값"
    elif query.kind == "sum":
        asked = (
            f"구하는 것: 첫 {query.n}항의 합 "
            f"(a({model.start})부터 a({model.start + query.n - 1})까지)"
        )
    elif query.kind == "terms":
        asked = (
            f"구하는 것: 첫 {query.n}항의 목록 "
            f"(a({model.start})부터 a({model.start + query.n - 1})까지)"
        )
    else:
        asked = (
            f"구하는 것: 일반항 후보 a(n) = {query.closed_source} 가 "
            f"n = {model.start}부터 {query.n}까지 점화식이 만드는 항과 모두 같으면 1, 아니면 0"
        )
    return (
        f"수열의 첫 항 번호는 {model.start}이다. 초기항: {inits}. "
        f"점화식: a(n+{model.order}) = {model.rec_source} (n ≥ {model.start}인 모든 n에서 성립). "
        f"{asked}."
    )


def _residual_axes(model: SequenceModel) -> tuple[str, ...]:
    axes = list(_RESIDUAL_BASE)
    if model.has_branch:
        axes.append(_RESIDUAL_BRANCH)
    if model.query.kind == "closed":
        # 유한 일치는 "모든 n"이 아니다 — closed에서는 이 축을 절대 비우지 않는다.
        axes.append(_RESIDUAL_GENERAL)
    return tuple(axes)


def _unverifiable(reason: str, model: SequenceModel | None = None) -> SequenceVerification:
    return SequenceVerification(
        state="unverifiable",
        reason=reason,
        samples_checked=0,
        residual_axes=(),
        tier=None,
        model=model,
        result=None,
    )


def verify_sequence_induction(conditions: str, answer: str) -> SequenceVerification:
    """점화식 정확 실행 후 답과 `==` 정확 일치로 대조한다.

    pass: 실행값과 주장값이 정확히 같음. fail: 다름(허용오차 없음). unverifiable: DSL 형식
    오류·자원 상한 초과·답을 정수/`p/q`/목록으로 읽을 수 없음·답의 형태가 질의와 다름.
    """
    try:
        model = parse_sequence_model(conditions)
        result = execute_sequence_model(model)
    except SequenceRangeError as exc:
        return _unverifiable(f"수열귀납검증 — 범위 초과: {exc}")
    except SequenceInductionError as exc:
        return _unverifiable(f"수열귀납검증 — {exc}")

    claimed = parse_exact_value(answer)
    if claimed is None:
        return _unverifiable("수열귀납검증 — 주장값을 정수·p/q·목록으로 읽을 수 없음", model)
    if isinstance(claimed, tuple) != (model.query.kind == "terms"):
        return _unverifiable("수열귀납검증 — 주장값의 형태(스칼라/목록)가 질의와 다름", model)
    if model.query.kind == "closed" and claimed not in (Fraction(0), Fraction(1)):
        return _unverifiable("수열귀납검증 — closed 질의의 답은 0 또는 1이어야 함", model)

    tier = (
        VerificationTier.FINITE_EXHAUSTIVE
        if model.query.kind == "closed"
        else VerificationTier.DETERMINISTIC_DATA
    )
    residual = _residual_axes(model)
    if claimed == result.value:
        return SequenceVerification(
            state="pass",
            reason=None,
            samples_checked=result.terms_computed,
            residual_axes=residual,
            tier=tier,
            model=model,
            result=result,
        )
    return SequenceVerification(
        state="fail",
        reason=(
            f"수열귀납검증 — 실행값 {_display_exact(result.value)}와 "
            f"주장 {_display_exact(claimed)} 불일치(정확 일치만 인정)"
        ),
        samples_checked=result.terms_computed,
        residual_axes=residual,
        tier=tier,
        model=model,
        result=result,
    )
