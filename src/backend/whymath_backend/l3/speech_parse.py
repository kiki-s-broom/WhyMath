"""L3 수식 음성화 — LaTeX → 낭독용 AST 파서 (결정론·외부 의존성 0).

왜 자체 파서인가(설계 결정·`l5/ocr/verify.py` hermetic 철학 답습): 낭독의 핵심 난점은 *시각
그룹핑을 청각으로 보존*하는 것이다. SymPy(`parse_check_latex`)는 의미 정규화로 원 표기/그룹핑을
손실하므로 부적합하다. 외부 MathML 파서(latex2mathml 등)는 CI 의존을 늘린다 — 대신 고3 수식
부분집합을 자체 재귀하강 파서로 다루면 ① 의존성 0(hermetic), ② 그룹핑 완전 제어, ③ 미지
명령어를 *조용히 버리지 않고* 노드로 보존(엔진이 unresolved로 정직 노출)한다.

이 모듈은 *순수 파서*다(레이어 데이터·한국어 사전 import 0). 노드→한국어 변환은 `l3/speech.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

# ──────────────────────────────────────────────────────────────────────────
# AST 노드 (그룹핑 보존 — 시각 구조를 그대로 담는다)
# ──────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Seq:
    """순차열(행) — 자식 노드를 순서대로 담는다(투명 그룹 {..} 포함)."""

    items: tuple["Node", ...]


@dataclass(frozen=True)
class Num:
    """수 리터럴 — 원시 문자열(소수점 포함 가능). 한국어 수 읽기는 엔진이 담당."""

    text: str


@dataclass(frozen=True)
class Var:
    """변수·기호 — 단일 라틴 문자('x') 또는 명령어('\\pi'·'\\theta')."""

    name: str


@dataclass(frozen=True)
class Op:
    """연산자·관계·구두점 — '+'·'='·'\\cdot' 등(부호·관계는 엔진이 문맥 처리)."""

    name: str


@dataclass(frozen=True)
class Frac:
    """분수 — \\frac{num}{den}. 한국 표준 '분모 먼저' 읽기는 엔진이 적용."""

    num: "Node"
    den: "Node"


@dataclass(frozen=True)
class Power:
    """거듭제곱 — base^exp(^)."""

    base: "Node"
    exp: "Node"


@dataclass(frozen=True)
class Index:
    """아래첨자 — base_sub(_)."""

    base: "Node"
    sub: "Node"


@dataclass(frozen=True)
class Root:
    """근호 — \\sqrt[index]{radicand}(index=None이면 제곱근)."""

    radicand: "Node"
    index: "Node | None"


@dataclass(frozen=True)
class Func:
    """함수 — \\sin·\\log 등(bare 이름). 거듭제곱·밑은 Power·Index가 감싸고 인자는 형제로 읽음."""

    name: str


@dataclass(frozen=True)
class BigOp:
    """대형 연산자 — \\int·\\sum·\\prod·\\lim(상·하한을 즉시 흡수해 낭독 범위를 잡는다)."""

    name: str
    lower: "Node | None"
    upper: "Node | None"


@dataclass(frozen=True)
class Group:
    """구분자 그룹 — ( ) · [ ] · | |(절댓값). 청각 멈춤·절댓값 후치 읽기에 쓰인다."""

    body: "Node"
    left: str
    right: str


@dataclass(frozen=True)
class Binom:
    """이항계수 — \\binom{top}{bottom}(확통 콤비네이션)."""

    top: "Node"
    bottom: "Node"


@dataclass(frozen=True)
class Deriv:
    """도함수(프라임) — base에 ' 가 primes개 붙음(f'·f'')."""

    base: "Node"
    primes: int


Node = Seq | Num | Var | Op | Frac | Power | Index | Root | Func | BigOp | Group | Binom | Deriv


# ──────────────────────────────────────────────────────────────────────────
# 명령어 분류
# ──────────────────────────────────────────────────────────────────────────
_SPACING_CMDS: frozenset[str] = frozenset(
    {
        "\\,",
        "\\;",
        "\\:",
        "\\!",
        "\\ ",
        "\\quad",
        "\\qquad",
        "\\thinspace",
        "\\left",
        "\\right",
    }
)
_FRAC_CMDS: frozenset[str] = frozenset({"frac", "dfrac", "tfrac", "cfrac"})
_BINOM_CMDS: frozenset[str] = frozenset({"binom", "dbinom", "tbinom"})
_BIGOPS: frozenset[str] = frozenset(
    {"int", "iint", "iiint", "oint", "sum", "prod", "coprod", "lim", "bigcup", "bigcap"}
)
_FUNCS: frozenset[str] = frozenset(
    {
        "sin",
        "cos",
        "tan",
        "cot",
        "sec",
        "csc",
        "sinh",
        "cosh",
        "tanh",
        "arcsin",
        "arccos",
        "arctan",
        "log",
        "ln",
        "lg",
        "exp",
        "det",
        "dim",
        "gcd",
        "lcm",
        "max",
        "min",
        "deg",
        "arg",
    }
)
# 명령어 형태의 연산자/관계/기호 — Op 노드로 보낸다(나머지 명령어는 Var로).
_OP_CMDS: frozenset[str] = frozenset(
    {
        "\\cdot",
        "\\times",
        "\\div",
        "\\pm",
        "\\mp",
        "\\ast",
        "\\to",
        "\\rightarrow",
        "\\mapsto",
        "\\Rightarrow",
        "\\Leftrightarrow",
        "\\iff",
        "\\implies",
        "\\in",
        "\\notin",
        "\\cup",
        "\\cap",
        "\\setminus",
        "\\subset",
        "\\subseteq",
        "\\forall",
        "\\exists",
        "\\land",
        "\\wedge",
        "\\lor",
        "\\vee",
        "\\lnot",
        "\\neg",
        "\\leq",
        "\\le",
        "\\geq",
        "\\ge",
        "\\neq",
        "\\ne",
        "\\approx",
        "\\equiv",
        "\\sim",
        "\\propto",
        "\\circ",
        "\\bmod",
        "\\cdots",
        "\\ldots",
        "\\dots",
        "\\perp",
        "\\parallel",
        "\\therefore",
        "\\because",
    }
)

# 관계 연산자 — 엔진이 한국어 후치 어순(SOV)으로 따로 읽는다(파서는 분류만).
RELATION_OPS: frozenset[str] = frozenset(
    {"=", "<", ">", "\\leq", "\\le", "\\geq", "\\ge", "\\neq", "\\ne"}
)

_SPECIAL_CHARS = "+-*/=<>(){}[]|^_,!'"

# 유니코드 프라임(′ ″ ‴)은 ASCII `'`의 반복과 같은 기호다(MATH-06) — 토크나이저가 정규화해
# 미분 표기로 읽히게 한다. 이전에는 미지 문자로 떨어져 학년 게이트가 반응하지 않았다.
_PRIME_CHARS: dict[str, int] = {"′": 1, "″": 2, "‴": 3}


# ──────────────────────────────────────────────────────────────────────────
# 토크나이저
# ──────────────────────────────────────────────────────────────────────────
def _tokenize(s: str) -> list[tuple[str, str]]:
    """LaTeX 문자열 → (종류, 값) 토큰열. 종류: num/letter/cmd/char(공백·정렬 토큰은 버림)."""
    toks: list[tuple[str, str]] = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c.isspace():
            i += 1
            continue
        if c == "\\":
            j = i + 1
            if j < n and s[j].isalpha():
                k = j
                while k < n and s[k].isalpha():
                    k += 1
                name = s[i:k]  # 백슬래시 포함
                i = k
                if name in _SPACING_CMDS:
                    continue
                if name == "\\prime":
                    toks.append(("char", "'"))  # \prime = 프라임 하나(_PRIME_CHARS와 같은 정규화)
                    continue
                toks.append(("cmd", name))
                continue
            # 백슬래시 + 단일 비문자(\, \\ \{ 등)
            if j < n:
                two = s[i : j + 1]
                i = j + 1
                if two in _SPACING_CMDS or two == "\\\\":
                    continue  # 정렬 공백·행 구분은 버림(매트릭스는 S4)
                toks.append(("cmd", two))
                continue
            i += 1
            continue
        if c.isdigit() or (c == "." and i + 1 < n and s[i + 1].isdigit()):
            k = i
            dot = False
            while k < n and (s[k].isdigit() or (s[k] == "." and not dot)):
                if s[k] == ".":
                    dot = True
                k += 1
            toks.append(("num", s[i:k]))
            i = k
            continue
        if c.isalpha():
            toks.append(("letter", c))
            i += 1
            continue
        if c in _PRIME_CHARS:
            toks.extend([("char", "'")] * _PRIME_CHARS[c])
            i += 1
            continue
        if c in _SPECIAL_CHARS:
            toks.append(("char", c))
            i += 1
            continue
        # 정렬 구분자·물결은 버림, 그 외 미지 문자는 char로 보존(엔진이 unresolved 처리)
        if c in "&~":
            i += 1
            continue
        toks.append(("char", c))
        i += 1
    return toks


# ──────────────────────────────────────────────────────────────────────────
# 재귀하강 파서
# ──────────────────────────────────────────────────────────────────────────
class _Parser:
    """LaTeX 토큰열 → AST. 미지 명령어도 Var/Op 노드로 보존(조용히 버리지 않음)."""

    def __init__(self, toks: list[tuple[str, str]]) -> None:
        self._toks = toks
        self._i = 0

    def _peek(self) -> tuple[str, str] | None:
        return self._toks[self._i] if self._i < len(self._toks) else None

    def _is_char(self, value: str) -> bool:
        tok = self._peek()
        return tok is not None and tok[0] == "char" and tok[1] == value

    def _advance(self) -> tuple[str, str]:
        tok = self._toks[self._i]
        self._i += 1
        return tok

    def parse(self) -> Node:
        return self._parse_sequence(stop=None)

    def _parse_sequence(self, stop: str | None) -> Node:
        items: list[Node] = []
        while True:
            tok = self._peek()
            if tok is None:
                break
            if stop is not None and tok[0] == "char" and tok[1] == stop:
                break
            items.append(self._parse_postfix())
        return Seq(tuple(items))

    def _parse_postfix(self) -> Node:
        base = self._parse_atom()
        while True:
            if self._is_char("'"):
                primes = 0
                while self._is_char("'"):
                    self._advance()
                    primes += 1
                base = Deriv(base, primes)
                continue
            if self._is_char("^"):
                self._advance()
                base = Power(base, self._parse_script())
                continue
            if self._is_char("_"):
                self._advance()
                base = Index(base, self._parse_script())
                continue
            break
        return base

    def _parse_script(self) -> Node:
        """^·_ 뒤의 스크립트 — {..} 그룹이면 그 전체, 아니면 단일 atom(친화적으로 수 전체 허용)."""
        if self._is_char("{"):
            self._advance()
            body = self._parse_sequence(stop="}")
            if self._is_char("}"):
                self._advance()
            return body
        return self._parse_atom()

    def _parse_required_arg(self) -> Node:
        """\\frac 등의 인자 — {..} 그룹이면 그 전체, 아니면 단일 atom(\\sqrt2 같은 무괄호 허용)."""
        if self._is_char("{"):
            self._advance()
            body = self._parse_sequence(stop="}")
            if self._is_char("}"):
                self._advance()
            return body
        return self._parse_atom()

    def _parse_atom(self) -> Node:
        tok = self._peek()
        if tok is None:
            return Seq(())
        kind, value = tok
        if kind == "char":
            if value == "{":
                self._advance()
                body = self._parse_sequence(stop="}")
                if self._is_char("}"):
                    self._advance()
                return body  # 투명 그룹(괄호 발성 없음)
            if value == "(":
                return self._parse_delim_group("(", ")")
            if value == "[":
                return self._parse_delim_group("[", "]")
            if value == "|":
                return self._parse_delim_group("|", "|")
            # 그 외 특수문자(연산자·관계·구두점·누수된 닫는 괄호)
            self._advance()
            return Op(value)
        if kind == "num":
            self._advance()
            return Num(value)
        if kind == "letter":
            self._advance()
            return Var(value)
        # kind == "cmd"
        self._advance()
        return self._parse_command(value)

    def _parse_delim_group(self, left: str, right: str) -> Node:
        self._advance()  # 여는 구분자
        body = self._parse_sequence(stop=right)
        if self._is_char(right):
            self._advance()
        return Group(body, left, right)

    def _parse_command(self, name: str) -> Node:
        bare = name[1:]  # 백슬래시 제거
        if bare in _FRAC_CMDS:
            return Frac(self._parse_required_arg(), self._parse_required_arg())
        if bare in _BINOM_CMDS:
            return Binom(self._parse_required_arg(), self._parse_required_arg())
        if bare == "sqrt":
            index: Node | None = None
            if self._is_char("["):
                self._advance()
                index = self._parse_sequence(stop="]")
                if self._is_char("]"):
                    self._advance()
            return Root(self._parse_required_arg(), index)
        if bare in _BIGOPS:
            lower: Node | None = None
            upper: Node | None = None
            while True:
                if self._is_char("_"):
                    self._advance()
                    lower = self._parse_script()
                elif self._is_char("^"):
                    self._advance()
                    upper = self._parse_script()
                else:
                    break
            return BigOp(bare, lower, upper)
        if bare in _FUNCS:
            return Func(bare)
        if name in _OP_CMDS:
            return Op(name)
        # 그 외 명령어(\pi·\theta·\infty·미지)는 기호 변수로 — 엔진이 사전 조회·unresolved 처리.
        return Var(name)


def parse_latex_ast(latex: str) -> Node:
    """LaTeX 문자열을 낭독용 AST(Seq 루트)로 파싱한다(결정론·외부 의존성 0)."""
    return _Parser(_tokenize(latex)).parse()
