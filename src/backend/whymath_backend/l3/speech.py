"""L3 수식 음성화 — AST → 한국어 낭독 토큰 → 검증된 SpeechSpec (결정론·LLM 0).

설계 정본: `docs/architecture/05_interaction.md` §5 접근성. 변환은 *결정론 규칙 엔진*이다(LLM
아님) — CLAUDE.md 우선순위 1(안전)·2(법·윤리)·3(정확성)·6(비용)을 동시에 만족한다: 환각 0,
오프라인, 저비용, 골든 코퍼스로 정확성 단언 가능. DNA가 `parse_check_latex`(결정론·LLM 0)에 가깝다.

7계층: 이 엔진은 한국어 사전(L4)을 *직접 import 하지 않고* 함수 인자로 주입받는다(L3→L4 역방향
의존 회피 — `generate_visualization_spec(recommended_styles=...)` DI 선례). 배선은 L4(`l4/speech/
__init__.py`)가 한다(L4→L3 forward 호출). 게이트 함수는 `parse_visualization_spec` 패턴 답습.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from pydantic import ValidationError

from whymath_backend.l3.speech_parse import (
    RELATION_OPS,
    BigOp,
    Binom,
    Deriv,
    Frac,
    Func,
    Group,
    Index,
    Node,
    Num,
    Op,
    Power,
    Root,
    Seq,
    Var,
    parse_latex_ast,
)
from whymath_backend.schema.speech import (
    BreakToken,
    GradeProfile,
    SpeechGradeBand,
    SpeechSpec,
    SpeechToken,
    TextToken,
    text_of,
)

__all__ = [
    "InvalidSpeechSpecError",
    "generate_speech_spec",
    "parse_speech_spec",
]


class InvalidSpeechSpecError(ValueError):
    """SpeechSpec 검증 게이트 실패 — 학생 미노출(API에서 422 매핑·parse_visualization_spec 선례)."""


# 한국어 수 읽기 — 한자어 수사(영/일/이…). 단위·개수의 고유어는 단위 처리 시 별도(S3).
_DIGITS = ("영", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구")
_SMALL_UNITS = ((1000, "천"), (100, "백"), (10, "십"))
_BIG_UNITS = ("", "만", "억", "조")


def _sino_under_man(n: int) -> str:
    """0~9999를 한자어로 — 10은 '십'(일십 아님)·110은 '백십'(순수)."""
    out = ""
    for value, unit in _SMALL_UNITS:
        d, n = divmod(n, value)
        if d:
            out += ("" if d == 1 else _DIGITS[d]) + unit
    if n:
        out += _DIGITS[n]
    return out


def sino_korean(n: int) -> str:
    """음이 아닌 정수를 한자어 수사로 — 만/억/조 단위 묶음(음수는 부호를 엔진이 따로 읽음)."""
    if n == 0:
        return "영"
    parts: list[str] = []
    i = 0
    while n > 0 and i < len(_BIG_UNITS):
        chunk = n % 10000
        n //= 10000
        if chunk:
            parts.append(_sino_under_man(chunk) + _BIG_UNITS[i])
        i += 1
    if n > 0:  # 조 초과(매우 큼) — 보수적으로 묶음 그대로(드뭄)
        parts.append(sino_korean(n) + "조")
    return "".join(reversed(parts))


def _read_number(text: str) -> str:
    """수 리터럴 낭독 — 정수는 한자어, 소수는 '정수부 점 소수자리 개별'(3.14 → 삼 점 일 사)."""
    if "." in text:
        ip, fp = text.split(".", 1)
        head = sino_korean(int(ip)) if ip else "영"
        tail = " ".join(_DIGITS[int(d)] for d in fp if d.isdigit())
        return f"{head} 점 {tail}".strip()
    return sino_korean(int(text))


# 부호의 단항/이항 판별에서 '앞이 연산자면 단항'으로 보는 기준.
def _is_open_context(prev: Node | None) -> bool:
    return prev is None or isinstance(prev, Op)


# 삼각함수 구조로 게이트하는 함수 — 역삼각(arc*)은 삼각의 역함수라 같은 구조 키(trig)로 묶는다.
# 구조 키 어휘를 새로 만들지 않는다(profiles.py가 정본). sinh·cosh·tanh는 아직 게이트하지 않는다.
_TRIG_FUNCS: frozenset[str] = frozenset(
    {"sin", "cos", "tan", "cot", "sec", "csc", "arcsin", "arccos", "arctan"}
)


def _is_point_name(node: Node) -> bool:
    """대문자 ASCII 한 글자(A·B′의 밑) — 도형의 점 이름이다."""
    return (
        isinstance(node, Var)
        and len(node.name) == 1
        and node.name.isascii()
        and node.name.isupper()
    )


def _unwrap(node: Node) -> Node:
    """단일 원소 Seq를 벗긴다 — {10}·[3] 같은 그룹 인자를 Num으로 환원(제곱·근호 라벨 정합)."""
    if isinstance(node, Seq) and len(node.items) == 1:
        return node.items[0]
    return node


class _Reader:
    """AST → 낭독 토큰 변환기 — 주입된 프로파일·사전으로 한국어를 만든다(미지 기호는 정직 노출)."""

    def __init__(
        self,
        profile: GradeProfile,
        token_ko: dict[str, str],
        func_ko: dict[str, str],
        latin_ko: dict[str, str],
    ) -> None:
        self._profile = profile
        self._token_ko = token_ko
        self._func_ko = func_ko
        self._latin_ko = latin_ko
        self.unresolved: list[str] = []

    # ── 게이팅·헬퍼 ──────────────────────────────────────────────────────
    def _gate(self, construct: str, label: str) -> None:
        """구조가 그 학년에 미도입이면 unresolved로 정직 표시(읽기는 계속 — 조용히 버리지 않음)."""
        if construct not in self._profile.introduced_constructs:
            self.unresolved.append(label)

    def _mark_unknown(self, name: str) -> list[SpeechToken]:
        """사전에 없는 기호 — unresolved에 적재하고 명시적 안내 음절 반환(환각·침묵 금지)."""
        self.unresolved.append(name)
        return [TextToken(text="알 수 없는 기호")]

    @staticmethod
    def _t(text: str) -> SpeechToken:
        return TextToken(text=text)

    @staticmethod
    def _brk(ms: int = 150) -> SpeechToken:
        return BreakToken(duration_ms=ms)

    # ── 디스패치 ────────────────────────────────────────────────────────
    def read(self, node: Node) -> list[SpeechToken]:
        if isinstance(node, Seq):
            return self._read_seq(node.items)
        if isinstance(node, Num):
            return [self._t(_read_number(node.text))]
        if isinstance(node, Var):
            return self._read_var(node)
        if isinstance(node, Op):
            return self._read_op(node)
        if isinstance(node, Frac):
            return self._read_frac(node)
        if isinstance(node, Power):
            return self._read_power(node)
        if isinstance(node, Index):
            return self._read_index(node)
        if isinstance(node, Root):
            return self._read_root(node)
        if isinstance(node, Func):
            return self._read_func(node)
        if isinstance(node, BigOp):
            return self._read_bigop(node)
        if isinstance(node, Group):
            return self._read_group(node)
        if isinstance(node, Binom):
            return self._read_binom(node)
        if isinstance(node, Deriv):
            return self._read_deriv(node)
        return []  # 도달 불가(완전 유니온) — 방어적 빈 결과

    # ── 순차열·관계(한국어 후치 어순) ────────────────────────────────────
    def _read_seq(self, items: tuple[Node, ...]) -> list[SpeechToken]:
        # 최상위 관계 연산자가 있으면 SOV 후치 어순으로 좌·우를 나눠 읽는다.
        for idx, it in enumerate(items):
            if isinstance(it, Op) and it.name in RELATION_OPS:
                return self._read_relation(items[:idx], it.name, items[idx + 1 :])
        out: list[SpeechToken] = []
        prev: Node | None = None
        for it in items:
            if isinstance(it, Op) and it.name in {"+", "-"}:
                unary = _is_open_context(prev)
                if it.name == "-":
                    out.append(self._t("마이너스" if unary else "빼기"))
                elif not unary:
                    out.append(self._t("더하기"))
                # 선두 단항 +는 발성하지 않음
            else:
                out.extend(self.read(it))
            prev = it
        return out

    def _read_relation(
        self, left: tuple[Node, ...], relname: str, right: tuple[Node, ...]
    ) -> list[SpeechToken]:
        lhs = self._read_seq(left)
        rhs = self._read_seq(right)
        if relname == "=":
            return [*lhs, self._t("는"), *rhs]
        if relname == "<":
            return [*lhs, self._t("는"), *rhs, self._t("보다 작다")]
        if relname == ">":
            return [*lhs, self._t("는"), *rhs, self._t("보다 크다")]
        if relname in {"\\leq", "\\le"}:
            return [*lhs, self._t("는"), *rhs, self._t("보다 작거나 같다")]
        if relname in {"\\geq", "\\ge"}:
            return [*lhs, self._t("는"), *rhs, self._t("보다 크거나 같다")]
        if relname in {"\\neq", "\\ne"}:
            return [*lhs, self._t("는"), *rhs, self._t("와 같지 않다")]
        return [*lhs, *rhs]  # 도달 불가(RELATION_OPS 전수)

    # ── 잎 노드 ─────────────────────────────────────────────────────────
    def _read_var(self, node: Var) -> list[SpeechToken]:
        name = node.name
        if name == "\\partial":
            self._gate("derivative", "\\partial")  # 편미분 — 미분 구조가 도입되기 전엔 미해결 표시
        if len(name) == 1 and name.isalpha():
            ko = self._latin_ko.get(name)
        else:
            ko = self._token_ko.get(name)
        if ko is None:
            return self._mark_unknown(name)
        return [self._t(ko)]

    def _read_op(self, node: Op) -> list[SpeechToken]:
        name = node.name
        if name in {"+", "\\ast"}:
            return [self._t("더하기")]
        if name == "-":
            return [self._t("빼기")]
        if name in {"*", "\\cdot", "\\times"}:
            return [self._t("곱하기")]
        if name in {"/", "\\div"}:
            return [self._t("나누기")]
        if name == ",":
            return [self._brk(120)]
        if name == "!":
            return [self._t("팩토리얼")]
        ko = self._token_ko.get(name)
        if ko is None:
            return self._mark_unknown(name)
        return [self._t(ko)]

    # ── 구조 노드 ───────────────────────────────────────────────────────
    def _read_frac(self, node: Frac) -> list[SpeechToken]:
        self._gate("fraction", "\\frac")
        # 한국 표준: 분모 먼저 — "{분모}분의 {분자}".
        return [
            self._brk(80),
            *self.read(node.den),
            self._t("분의"),
            *self.read(node.num),
            self._brk(80),
        ]

    def _power_suffix(self, exp: Node) -> list[SpeechToken]:
        """거듭제곱 접미 — 2→제곱·3→세제곱·그 외 정수→'n제곱'·일반식→'의 … 제곱'."""
        exp = _unwrap(exp)
        if isinstance(exp, Num) and "." not in exp.text:
            n = int(exp.text)
            if n == 2:
                return [self._t("제곱")]
            if n == 3:
                return [self._t("세제곱")]
            return [self._t(f"{sino_korean(n)}제곱")]
        return [self._t("의"), *self.read(exp), self._t("제곱")]

    def _read_power(self, node: Power) -> list[SpeechToken]:
        self._gate("power", "^")
        base = node.base
        # 함수 거듭제곱: \sin^2 x → "사인 제곱"(+ 인자 x는 형제로).
        if isinstance(base, Func):
            return [*self.read(base), *self._power_suffix(node.exp)]
        # 그룹 거듭제곱: (x+1)^2 → "엑스 더하기 일 전체의 제곱".
        if isinstance(base, Group):
            return [
                *self.read(base.body),
                self._t("전체의"),
                *self._power_suffix(node.exp),
            ]
        # 초등 전개: x^2 → "엑스 곱하기 엑스"(power_style="multiply"·작은 정수·단순 밑).
        if (
            self._profile.power_style == "multiply"
            and isinstance(node.exp, Num)
            and node.exp.text in {"2", "3"}
            and isinstance(base, (Var, Num))
        ):
            count = int(node.exp.text)
            parts: list[SpeechToken] = []
            for k in range(count):
                if k > 0:
                    parts.append(self._t("곱하기"))
                parts.extend(self.read(base))
            return parts
        return [*self.read(base), *self._power_suffix(node.exp)]

    def _read_index(self, node: Index) -> list[SpeechToken]:
        # 함수 밑(\log_2 → "로그 이")·일반 아래첨자(a_n → "에이 엔") 모두 병치 읽기.
        if not isinstance(node.base, Func):
            self._gate("subscript", "_")
        return [*self.read(node.base), *self.read(node.sub)]

    def _read_root(self, node: Root) -> list[SpeechToken]:
        self._gate("root", "\\sqrt")
        if node.index is None:
            label = self._profile.sqrt_label or "루트"
            if self._profile.sqrt_label is None:
                self.unresolved.append("\\sqrt")  # 미도입 학년(초등) 정직 표시
            return [self._t(label), self._brk(60), *self.read(node.radicand)]
        return [
            *self._nth_root_label(node.index),
            self._brk(60),
            *self.read(node.radicand),
        ]

    def _nth_root_label(self, index: Node) -> list[SpeechToken]:
        """n제곱근 라벨 — 2→제곱근·3→세제곱근·그 외 정수→'n제곱근'·일반식→'… 제곱근'."""
        index = _unwrap(index)
        if isinstance(index, Num) and "." not in index.text:
            n = int(index.text)
            if n == 2:
                return [self._t("제곱근")]
            if n == 3:
                return [self._t("세제곱근")]
            return [self._t(f"{sino_korean(n)}제곱근")]
        return [*self.read(index), self._t("제곱근")]

    def _read_func(self, node: Func) -> list[SpeechToken]:
        if node.name in _TRIG_FUNCS:
            self._gate("trig", f"\\{node.name}")
        elif node.name in {"log", "ln", "lg"}:
            self._gate("log", f"\\{node.name}")
        ko = self._func_ko.get(node.name)
        if ko is None:
            return self._mark_unknown(f"\\{node.name}")
        return [self._t(ko)]

    def _read_bigop(self, node: BigOp) -> list[SpeechToken]:
        name = node.name
        if name in {"int", "iint", "iiint", "oint"}:
            self._gate("integral", f"\\{name}")
            word = "선적분" if name == "oint" else "적분"
            if node.lower is not None and node.upper is not None:
                return [
                    *self.read(node.lower),
                    self._t("부터"),
                    *self.read(node.upper),
                    self._t("까지"),
                    self._t(word),
                ]
            if node.lower is not None:
                return [*self.read(node.lower), self._t("부터"), self._t(word)]
            return [self._t(word)]
        if name in {"sum", "bigcup", "bigcap"}:
            self._gate("sum", f"\\{name}")
            word = {"sum": "합", "bigcup": "합집합", "bigcap": "교집합"}[name]
            if node.lower is not None and node.upper is not None:
                return [
                    *self.read(node.lower),
                    self._t("부터"),
                    *self.read(node.upper),
                    self._t("까지의"),
                    self._t(word),
                ]
            return [self._t(word)]
        if name in {"prod", "coprod"}:
            self._gate("product", f"\\{name}")
            if node.lower is not None and node.upper is not None:
                return [
                    *self.read(node.lower),
                    self._t("부터"),
                    *self.read(node.upper),
                    self._t("까지의"),
                    self._t("곱"),
                ]
            return [self._t("곱")]
        if name == "lim":
            self._gate("limit", "\\lim")
            if node.lower is not None:
                return [*self._read_lim_cond(node.lower), self._t("의 극한")]
            return [self._t("극한")]
        return self._mark_unknown(f"\\{name}")

    def _read_lim_cond(self, sub: Node) -> list[SpeechToken]:
        """극한 조건 — 'x \\to 0' → '엑스가 영으로 갈 때'(\\to 분해)."""
        if isinstance(sub, Seq):
            for idx, it in enumerate(sub.items):
                if isinstance(it, Op) and it.name in {"\\to", "\\rightarrow"}:
                    var = self._read_seq(sub.items[:idx])
                    target = self._read_seq(sub.items[idx + 1 :])
                    return [*var, self._t("가"), *target, self._t("으로 갈 때")]
        return [*self.read(sub), self._t("일 때")]

    def _read_group(self, node: Group) -> list[SpeechToken]:
        if node.left == "|":
            return [*self.read(node.body), self._t("의 절댓값")]
        # 괄호·대괄호: 발성 없이 멈춤으로 청각 그룹핑(괄호 거듭제곱은 Power가 '전체'로 처리).
        return [self._brk(120), *self.read(node.body), self._brk(120)]

    def _read_binom(self, node: Binom) -> list[SpeechToken]:
        self._gate("binom", "\\binom")
        return [*self.read(node.top), self._t("콤비네이션"), *self.read(node.bottom)]

    def _read_deriv(self, node: Deriv) -> list[SpeechToken]:
        # 대문자 한 글자 + 프라임은 도형의 점 이름(A′·B″ — 중등 대칭이동·평행이동)이지 미분 표기가
        # 아니다. 소문자 함수명(f′·g″)만 미분으로 게이트한다(MATH-06 — 교육과정 표기 범위 게이트의
        # `prime-call` 구조 패턴과 같은 구분 규칙).
        if not _is_point_name(node.base):
            self._gate("derivative", "'")
        return [*self.read(node.base), *([self._t("프라임")] * node.primes)]


def _plain_from_tokens(tokens: list[SpeechToken]) -> str:
    """토큰열 → 폴백 낭독 문자열(텍스트만 공백으로 잇고 정규화·break는 무시)."""
    return " ".join(piece for piece in (text_of(t) for t in tokens) if piece).strip()


def _ssml_from_tokens(tokens: list[SpeechToken]) -> str:
    """토큰열 → SSML(break·emphasis 보존·텍스트 XML 이스케이프). 지원 엔진에서만 사용."""
    parts: list[str] = ["<speak>"]
    for t in tokens:
        if isinstance(t, BreakToken):
            parts.append(f'<break time="{t.duration_ms}ms"/>')
        elif isinstance(t, TextToken):
            parts.append(escape(t.text))
        else:  # EmphasisToken
            parts.append(f'<emphasis level="{t.level}">{escape(t.text)}</emphasis>')
    parts.append("</speak>")
    return " ".join(parts)


def generate_speech_spec(
    latex: str,
    grade_band: SpeechGradeBand | str,
    *,
    profile: GradeProfile,
    token_ko: dict[str, str],
    func_ko: dict[str, str],
    latin_ko: dict[str, str],
) -> SpeechSpec:
    """LaTeX → 검증된 SpeechSpec — 결정론 규칙 엔진(LLM 0). 사전·프로파일은 주입(L4 배선).

    절차: ① 빈 입력 거부 → ② AST 파싱(`speech_parse`) → ③ 한국어 토큰 변환(`_Reader`) →
    ④ plain_text/SSML 조립 → ⑤ `SpeechSpec` 불변식 게이트(실패 시 `InvalidSpeechSpecError`).

    Args:
        latex: 원본 LaTeX 수식.
        grade_band: 낭독 학년 밴드(프로파일과 일치해야 의미 정합).
        profile: 주입된 학년 프로파일(L4 `PROFILES`).
        token_ko/func_ko/latin_ko: 주입된 한국어 사전(L4 `symbols`).

    Returns:
        검증 통과한 `SpeechSpec`(plain_text·tokens·ssml·unresolved_symbols).

    Raises:
        InvalidSpeechSpecError: 빈 입력 또는 불변식 위반(빈 낭독·추적성 등).
    """
    if not latex.strip():
        raise InvalidSpeechSpecError("빈 LaTeX — 읽을 원본 수식이 없습니다.")
    band = SpeechGradeBand(grade_band)  # str·enum 모두 수용해 정규화(직접 호출자 친화)
    ast = parse_latex_ast(latex)
    reader = _Reader(profile, token_ko, func_ko, latin_ko)
    tokens = reader.read(ast)
    plain = _plain_from_tokens(tokens)
    if not plain.strip():
        raise InvalidSpeechSpecError(f"낭독 결과가 비었습니다(읽을 수 있는 기호 없음): {latex!r}")
    try:
        return SpeechSpec(
            source_latex=latex,
            grade_band=band,
            plain_text=plain,
            tokens=tokens,
            ssml=_ssml_from_tokens(tokens),
            unresolved_symbols=sorted(set(reader.unresolved)),
        )
    except ValidationError as exc:
        raise InvalidSpeechSpecError(f"SpeechSpec 검증 실패: {exc}") from exc


def parse_speech_spec(data: dict[str, object]) -> SpeechSpec:
    """외부 dict → 검증된 SpeechSpec(불변식 게이트). 위반 시 `InvalidSpeechSpecError`.

    엔진이 내부 생성한 명세는 `generate_speech_spec`이 직접 검증하므로, 이 게이트는 *외부에서
    들어온* 명세(라운드트립·수동 구성)를 학생 노출 전에 거른다(parse_visualization_spec 선례).
    """
    try:
        return SpeechSpec.model_validate(data)
    except ValidationError as exc:
        raise InvalidSpeechSpecError(f"SpeechSpec 검증 실패: {exc}") from exc
