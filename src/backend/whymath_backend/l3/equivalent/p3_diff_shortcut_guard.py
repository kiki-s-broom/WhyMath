"""P3-03 미분 문항 은행 — '선수 계산 우회로' 판정기(순수 함수·결정론·LLM 0).

독립 감사 3회차(`docs/data/p3_calculus1_diff_audit/round3/defects.json`·κ 0.854)의 결함
대부분은 "미분 없이 선수 계산만으로 풀린다"(bad_tag) 한 부류였다. 생성기가 기계 검증을 위해
정수 중근·깔끔한 인수를 가진 다항식을 고르는데, 바로 그 성질이 인수분해·판별식·대입 우회로를
연다. 1·2회차 교정은 지적된 *발문 서명*을 지우는 방식이라 같은 원인이 새 틀로 재발했다
(74 → 90 → 122).

이 모듈은 서명이 아니라 **수학 재료**를 본다 — 발문에 보이는 다항식·검산 조건(`verify`)·
해설에서 "이 문항이 그 개념의 인지 행동(미분) 없이 풀리는가"를 개념별 규칙으로 판정한다.
생성기 빌드(`p3_diff_skeleton_base.P3DiffSlotGenerator._validate_slot`)가 문항마다 부르고
위반이 하나라도 있으면 빌드를 멈춘다(fail-loud). 은행 전수 0건은 테스트
(`test_p3_diff_shortcut_guard`)가 단언한다.

입력은 생성기의 `DiffItem`이 아니라 **중립 표본**(`ShortcutProbe`)이다 — 같은 판정기를 은행
JSONL 레코드(`probe_from_record`)에도 그대로 적용해 감사 회차의 교정 전 은행에서 재현율을 잴
수 있게 한다.

독립 감사 4회차(`round4/defects.json`·합집합 88·둘 다 27)는 이 판정기를 통과한 은행에서 다시
결함을 찾았다 — ① 학생 대면 텍스트의 코드식 부등호 '<='·'>='와 근호 'sqrt(' ② 극값 위치를 둘
이상 주는 02-08 문항(대입·대소 비교) ③ 복이차 사차식(완전제곱) ④ 포물선 꼭짓점의 수평 접선·직선의
접선(02-05) ⑤ 위치가 일차 이하인 운동의 속도·가속도(02-10) ⑥ x^n의 도함수를 0에서 보는 문항(오답
경로도 전부 0) ⑦ 방정식·부등식 맥락이 없는 02-09 최솟값 ⑧ 발문에 없는 '두 점'·'접점'을 쓰는 해설.
4회차 규칙(아래 [4회차])이 그 부류를 생성 시점에 막는다.

규칙(위반 id — 사유는 `ShortcutViolation.reason`)
--------------------------------------------
[공통 · 표기]
  W-notation         학생 대면 문면(발문·선지·해설·정답)에 SymPy 표기('*'·'Derivative(' 등)가
                     있다.
  W-ascii-inequality [4회차] 학생 대면 문면에 코드식 부등호 '<='·'>='가 있다 — 승인 은행 4종은
                     '≤'·'≥'만 쓴다(Flutter 렌더는 '<='를 그대로 두 글자로 낸다).
  W-sqrt-call        [4회차] 학생 대면 문면에 함수 호출꼴 근호 'sqrt('가 있다 — 승인 은행 관례는
                     '8√3'이다(3회차 교정이 고른 '8sqrt(3)'은 감사자 둘이 모두 코드 표기로 봤다).
  W-point-x          '곡선 … 위의 x = 1에서의'처럼 점을 x값으로만 부른다('x좌표가 1인 점').
  W-trivial-ineq     '(-1 < 0 < 2)'처럼 상수만으로 된 자명한 부등식이 괄호로 붙어 있다
                     (템플릿 흔적).
  W-zero-hour        '출발 후 0시간부터'(템플릿 값 0이 그대로 들어간 시각 표현).
  W-extremum-josa    'f(x) …의 극값을 갖는'(주어 조사 오류)·'점이 x = '(점을 x값과 등치).
[공통 · 해설(핵심 중간 단계)]
  E-derivative       발문이 다항함수를 주는데 해설에 도함수 식(f'(x) = …·도함수는 …·
                     v(t) = …)이 없다.
  E-parameter        발문 함수식의 미지 상수(x^n의 n·ax^2의 a)가 해설에 결론('n은 3')으로만
                     나오고 세운 식(nx^(n - 1)·6a + 18 = 0) 안에 한 번도 들지 않는다.
  E-kinematics       발문이 (순간)속도·운동 방향을 다루는데 해설에 v(t) 식이 없거나,
                     가속도를 다루는데 a(t) 식이 없다.
  E-sign             운동 방향 전환을 묻는데 해설에 속도의 부호 판정이 없다.
  E-symbol-intro     해설이 발문에 없는 기호(f'(c)의 c)를 소개 없이 쓴다.
  E-tautology        'q = 3에서 q = 3이다' 같은 순환 서술.
  E-term             '기울기 0인 일차함수'(상수함수를 일차함수라 부름).
  E-object-intro     [4회차] 해설이 발문에 없는 도형 대상('두 점을 잇는 직선'·'접점'·'접선')을
                     소개 없이 쓴다(발문에 점·곡선·직선·그래프가 하나도 없다).
[개념 · 우회로(bad_tag)]
  T05-quadratic-tangency  (02-05) 접할 조건·곡선 밖의 점에서 그은 접선을 묻는데 곡선이
                          이차 이하라 판별식만으로 풀린다(곡선 차수 ≥ 3이어야 한다).
  T-value-determines      (02-05·02-08) 발문의 함숫값 조건(극값의 값·두 곡선이 만나는 점)
                          만으로 구하는 상수가 정해진다 — 미분계수 조건이 풀이에 쓰이지 않는다.
  T06-given-rate          (02-06) 발문이 평균변화율의 값을 직접 준다(평균값 정리의 행위가
                          빠진다).
  T08-derivative-inequality
                          (02-08) 발문이 f'(x) < 0 같은 도함수 부등식을 직접 준다(증감 판정이
                          빠진다).
  T08-pinned-kind         (02-08) 극값의 위치(x = a)와 종류를 함께 주고 그 값을 묻는다(대입만).
  T09-rational-root       (02-09) 발문에 보이는 방정식·부등식의 다항식이 유리수 근을 갖는다
                          (인수정리).
  T09-biquadratic         (02-09) 발문의 사차식이 어떤 x = h에 대해 대칭이라((x - h)^2 = u)
                          이차방정식으로 환원된다(복이차식 — 근의 공식·판별식).
  T09-repeated-root       (02-09) 등호가 성립하는 점(근)을 묻는데 그 점이 중근이다
                          (완전제곱·인수 우회로).
  T09-low-degree          (02-09) 발문에 보이는 방정식이 이차 이하다(판별식·근의 공식).
  T09-pinned-minimizer    (02-09) 최솟값을 묻는데 발문이 최솟값을 갖는 x를 알려 주거나 그 x가
                          0이다(상수항이 곧 답 — 대입만).
  T10-average-only        (02-10) 평균속도만 묻는다(위치 대입·차분몫 — 미분 불요).
  T-zero-monomial         [4회차] (전 개념) 발문의 함수가 단항식 c·x^n(n ≥ 2)인데 x = 0(원점)에서의
                          미분계수나 방정식 f'(x) = 0의 근을 묻는다 — 정답도, 원함수 대입도,
                          거듭제곱 미분법의 어떤 오답 경로도 0이라 변별이 없다.
  T05-vertex-tangent      [4회차] (02-05) 곡선이 이차 이하인데 꼭짓점·x축에 평행한 접선·기울기 0을
                          묻는다 — 꼭짓점 공식 -b/(2a)·완전제곱으로 풀린다.
  T05-line-tangent        [4회차] (02-05) 직선 위의 점에서의 접선을 묻는다 — 직선의 기울기를 읽기만
                          하면 된다.
  T08-given-critical-points
                          [4회차] (02-08) 발문이 극값을 갖는 x 위치를 둘 이상 준다 — 대입하고 대소를
                          비교하면 극댓값·극솟값이 정해진다(삼차·사차에서 '큰 값이 극댓값'이 늘
                          맞는다). 부호가 바뀌지 않는 임계점이 섞여 *극값인지* 가려야 하는 경우는
                          세지 않는다(극값 위치는 둘 미만이 된다).
  T08-biquadratic         [4회차] (02-08) 발문의 사차식이 x = h에 대해 대칭(복이차)이라
                          (x - h)^2 = u로 두면 완전제곱만으로 극값의 위치·값이 나온다.
  T09-no-application      [4회차] (02-09) 발문에 방정식·부등식·교점·위치 관계 맥락이 없다 — 최댓값·
                          최솟값 기술(02-07/02-08 영역)만으로 풀리는 문항이다.
  T10-linear-position     [4회차] (02-10) 위치가 일차 이하(x = 7·x = 2t + 1)인데 속도·가속도를
                          묻는다 — 정지·등속이라는 상식(일차함수의 기울기)으로 풀린다.

정직 범위(이 판정기가 보증하지 **않는** 것)
-------------------------------------------
· 발문 문자열의 *템플릿 표현*을 정규식으로 읽는 휴리스틱이 섞여 있다. 같은 수학을 다른 어휘로
  쓴 문항(예: '접할 때' 대신 '한 점에서만 만날 때')은 T05 규칙이 읽지 못할 수 있다.
· '미분 없이 풀린다'의 판정은 이 규칙들이 아는 우회로(인수정리·판별식·대입·이차부등식·
  평균속도 차분몫)에 한정된다. 학생이 쓸 수 있는 모든 우회로(산술·기하 평균 등)를 열거하지
  않는다.
· 해설 규칙은 *형식*(도함수 식·세운 식의 존재)을 본다 — 그 식이 옳은지는 Tier1·
  corpus_reverify의 몫이다.

7계층: L3 지역. SymPy 문자열 파싱은 `l3.safe_parse`(CONST-09 단일 진입점)로만 한다 — 입력은
저작 코퍼스·생성기 산출이지만 진입점을 우회하지 않는다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import sympy

from whymath_backend.l3.safe_parse import safe_sympify

__all__ = [
    "ROUND4_RULE_IDS",
    "RULE_IDS",
    "ShortcutProbe",
    "ShortcutViolation",
    "has_rational_root",
    "is_shifted_biquadratic",
    "probe_from_record",
    "shortcut_violations",
    "violations_by_rule",
    "visible_polynomials",
]

#: 판정기가 낼 수 있는 규칙 id 전부(테스트·보고가 참조하는 단일 원천).
RULE_IDS: Final[tuple[str, ...]] = (
    "W-notation",
    "W-point-x",
    "W-trivial-ineq",
    "W-zero-hour",
    "W-extremum-josa",
    "E-derivative",
    "E-parameter",
    "E-kinematics",
    "E-sign",
    "E-symbol-intro",
    "E-tautology",
    "E-term",
    "T05-quadratic-tangency",
    "T-value-determines",
    "T06-given-rate",
    "T08-derivative-inequality",
    "T08-pinned-kind",
    "T09-rational-root",
    "T09-biquadratic",
    "T09-repeated-root",
    "T09-low-degree",
    "T09-pinned-minimizer",
    "T10-average-only",
    # ── 4회차(2026-10-07) 결함 부류 — `ROUND4_RULE_IDS` ──
    "W-ascii-inequality",
    "W-sqrt-call",
    "E-object-intro",
    "T-zero-monomial",
    "T05-vertex-tangent",
    "T05-line-tangent",
    "T08-given-critical-points",
    "T08-biquadratic",
    "T09-no-application",
    "T10-linear-position",
)

#: 4회차 감사(합집합 88·둘 다 27)를 계기로 더한 규칙 — 3회차 재현율·과잉 거부 동결 테스트는 이
#: 규칙들을 빼고 본다(3회차 판정자는 '<=' 등을 결함으로 보지 않았다 — 같은 원문에 대한 기준이
#: 회차마다 다르므로, 회차별 측정은 그 회차의 규칙 집합으로 한다).
ROUND4_RULE_IDS: Final[frozenset[str]] = frozenset(RULE_IDS[RULE_IDS.index("W-ascii-inequality") :])

_C05: Final = "[12미적Ⅰ-02-05]"
_C06: Final = "[12미적Ⅰ-02-06]"
_C08: Final = "[12미적Ⅰ-02-08]"
_C09: Final = "[12미적Ⅰ-02-09]"
_C10: Final = "[12미적Ⅰ-02-10]"
_REAL_ROOT_COUNT: Final = "real_root_count"


@dataclass(frozen=True, slots=True)
class ShortcutProbe:
    """판정 대상 문항 1건의 중립 표본 — 생성기 문항과 은행 레코드가 같은 모양으로 들어온다."""

    standard_code: str
    question_text: str
    answer: str
    explanation: str
    choices: tuple[str, ...] = ()
    conditions: tuple[str, ...] = ()
    answer_map: tuple[tuple[str, str], ...] = ()
    answer_kind: str | None = None

    @property
    def answer_dict(self) -> dict[str, str]:
        return dict(self.answer_map)


@dataclass(frozen=True, slots=True)
class ShortcutViolation:
    """위반 1건 — 어느 규칙을 왜 어겼는지(사람이 틀을 고칠 수 있게)."""

    rule: str
    reason: str

    def __str__(self) -> str:
        return f"[{self.rule}] {self.reason}"


def probe_from_record(record: Mapping[str, object]) -> ShortcutProbe:
    """은행 JSONL 레코드 → 표본(`verify` 재료·선지·해설을 그대로 옮긴다)."""
    codes = record.get("achievement_standard_codes")
    code = str(codes[0]) if isinstance(codes, list) and codes else ""
    verify = record.get("verify")
    conditions: tuple[str, ...] = ()
    answer_map: tuple[tuple[str, str], ...] = ()
    answer_kind: str | None = None
    if isinstance(verify, Mapping):
        raw = verify.get("conditions")
        if isinstance(raw, str):
            conditions = (raw,)
        elif isinstance(raw, list):
            conditions = tuple(str(c) for c in raw)
        amap = verify.get("answer_map")
        if isinstance(amap, Mapping):
            answer_map = tuple((str(k), str(v)) for k, v in amap.items())
        kind = verify.get("answer_kind")
        answer_kind = str(kind) if isinstance(kind, str) else None
    choices = record.get("choices")
    return ShortcutProbe(
        standard_code=code,
        question_text=str(record.get("question_text") or ""),
        answer=str(record.get("answer") or ""),
        explanation=str(record.get("answer_explanation") or ""),
        choices=tuple(str(c) for c in choices) if isinstance(choices, list) else (),
        conditions=conditions,
        answer_map=answer_map,
        answer_kind=answer_kind,
    )


# ──────────────────────────────────────────────────────────────────────────
# 학생 표기 다항식 읽기 — '2x^3 - 3x + 1'·'x^3 + ax^2 - 9x + 4'·'x^n'
# ──────────────────────────────────────────────────────────────────────────
# 항: (정수 계수)(문자^지수)… 또는 정수. 지수는 숫자 또는 문자 하나(x^n).
_TERM = r"(?:\d+)?(?:[a-z](?:\^(?:\d+|[a-z]))?)+|\d+"
#: 발문의 다항식 덩어리 — 함수 기호의 인자 'f(x)'의 x나 프라임 'f'(x)'의 일부는 잡지 않는다.
_POLY_RE = re.compile(
    rf"(?<![A-Za-z0-9'^(/])-?(?:{_TERM})(?:\s[-+]\s(?:{_TERM}))*(?![A-Za-z0-9^'(/])"
)


def _student_to_sympy_text(text: str) -> str:
    """학생 표기 → SymPy 표기('2ax^2' → '2*a*x**2'). 곱을 명시하고 캐럿을 거듭제곱으로 바꾼다."""
    out = re.sub(r"(\d)([a-z])", r"\1*\2", text)
    while True:
        nxt = re.sub(r"([a-z])([a-z])", r"\1*\2", out)
        if nxt == out:
            break
        out = nxt
    out = re.sub(r"([a-z0-9])\^", r"\1**", out)
    return out


def _parse_student(text: str) -> sympy.Expr | None:
    try:
        value = safe_sympify(_student_to_sympy_text(text.strip()))
    except (ValueError, TypeError, SyntaxError, sympy.SympifyError):
        return None
    return value if isinstance(value, sympy.Expr) else None


def visible_polynomials(question_text: str) -> list[sympy.Expr]:
    """발문에 학생이 *보는* 다항식 덩어리(문자를 하나 이상 포함한 것)를 SymPy 식으로 모은다."""
    out: list[sympy.Expr] = []
    for match in _POLY_RE.finditer(question_text):
        chunk = match.group(0)
        if not re.search(r"[a-z]", chunk):
            continue
        expr = _parse_student(chunk)
        if expr is not None and expr.free_symbols:
            out.append(sympy.expand(expr))
    return out


# ──────────────────────────────────────────────────────────────────────────
# 검산 조건 읽기
# ──────────────────────────────────────────────────────────────────────────
_REL_RE = re.compile(r"\s(<=|>=|!=|=|<|>)\s")


@dataclass(frozen=True, slots=True)
class _Relation:
    lhs: sympy.Expr
    op: str
    rhs: sympy.Expr

    @property
    def difference(self) -> sympy.Expr:
        return sympy.expand(self.lhs - self.rhs)


def _parse_relation(condition: str) -> _Relation | None:
    """'lhs op rhs'(공백으로 감싼 관계 연산자 하나) → 관계. 미분 조건은 읽지 않는다(None)."""
    if "Derivative" in condition:
        return None
    match = _REL_RE.search(condition)
    if match is None:
        return None
    try:
        lhs = safe_sympify(condition[: match.start()])
        rhs = safe_sympify(condition[match.end() :])
    except (ValueError, TypeError, SyntaxError, sympy.SympifyError):
        return None
    if not isinstance(lhs, sympy.Expr) or not isinstance(rhs, sympy.Expr):
        return None
    return _Relation(lhs, match.group(1), rhs)


def _variable_of(probe: ShortcutProbe) -> sympy.Symbol:
    """문항의 독립변수 — 검산 조건에 t가 있으면 t(운동), 아니면 x."""
    joined = " ".join(probe.conditions)
    return (
        sympy.Symbol("t") if re.search(r"(?<![A-Za-z])t(?![A-Za-z])", joined) else sympy.Symbol("x")
    )


def has_rational_root(expr: sympy.Expr, var: sympy.Symbol) -> bool:
    """유리수 근이 있는가(일차 인수) — 생성기가 같은 술어로 미리 거른다(판정 정의의 단일 원천)."""
    _, factors = sympy.factor_list(expr, var)
    return any(sympy.degree(f, var) == 1 for f, _ in factors)


def is_shifted_biquadratic(expr: sympy.Expr, var: sympy.Symbol) -> bool:
    """사차식이 어떤 x = h에 대해 대칭인가 — P(x + h)가 짝수 차 항만 가지면 이차식으로 환원된다."""
    poly = sympy.Poly(expr, var)
    if poly.degree() != 4:
        return False
    coeffs = poly.all_coeffs()
    h = sympy.Rational(-coeffs[1], 4 * coeffs[0])
    shifted = sympy.Poly(sympy.expand(expr.subs(var, var + h)), var)
    return all(c == 0 for (e,), c in shifted.terms() if e % 2 == 1)


def _has_repeated_factor(expr: sympy.Expr, var: sympy.Symbol) -> bool:
    _, factors = sympy.factor_list(expr, var)
    return any(mult >= 2 and sympy.degree(f, var) >= 1 for f, mult in factors)


# ──────────────────────────────────────────────────────────────────────────
# [공통 · 표기]
# ──────────────────────────────────────────────────────────────────────────
#: 학생 문면에 새어 나온 SymPy 함수명(근호 'sqrt('는 4회차 규칙 W-sqrt-call이 따로 본다).
_SYMPY_FUNCTION = re.compile(r"\b(?:Derivative|Abs|Rational|Integer|Symbol|Poly|Eq)\(")
#: [4회차] 코드식 부등호 — 학생 표기는 '≤'·'≥'(승인 은행 관례). '=>'·'=<'는 쓰지 않으므로
#: 보지 않는다.
_W_ASCII_INEQ = re.compile(r"<=|>=")
#: [4회차] 함수 호출꼴 근호 — 학생 표기는 '√3'·'8√3'.
_W_SQRT_CALL = re.compile(r"sqrt\(")
_W_POINT_X = re.compile(r"위의 [xt] = -?\d+(?:/\d+)?에서")
_NUM = r"-?\d+(?:/\d+)?"
#: 부등호는 코드식('<=')과 학생 표기('≤') 둘 다 읽는다 — 표기를 바꿔도 자명 부등식 검출이 꺼지지
#: 않게(4회차 표기 교정이 이 규칙을 무력화하지 않게) 한다.
_LE = r"(?:<=?|≤)"
_W_TRIVIAL_INEQ = re.compile(rf"\(\s*{_NUM}\s*{_LE}\s*{_NUM}\s*{_LE}\s*{_NUM}\s*\)")
_W_ZERO_HOUR = re.compile(r"(?<!\d)0\s*시간\s*(?:부터|후|동안)|후\s+0\s*시간")
_W_EXTREMUM_JOSA = re.compile(r"의 극(?:값|댓값|솟값)을 갖는|점이 [xt] = ")


def _notation_rules(probe: ShortcutProbe) -> list[ShortcutViolation]:
    out: list[ShortcutViolation] = []
    fields = [("발문", probe.question_text), ("해설", probe.explanation)]
    fields += [(f"선지 {i + 1}", c) for i, c in enumerate(probe.choices)]
    fields += [("정답", probe.answer)]
    for name, text in fields:
        if "*" in text or _SYMPY_FUNCTION.search(text):
            out.append(
                ShortcutViolation(
                    "W-notation",
                    f"{name} {text!r}에 SymPy 표기('*'·'Derivative(' 등)가 학생에게 노출된다 — "
                    "곱은 이어 쓴다('3x^2'·'8√3').",
                )
            )
        if _W_ASCII_INEQ.search(text):
            out.append(
                ShortcutViolation(
                    "W-ascii-inequality",
                    f"{name} {text!r}에 코드식 부등호('<='·'>=')가 있다 — 학생 표기 "
                    "'≤'·'≥'로 쓴다.",
                )
            )
        if _W_SQRT_CALL.search(text):
            out.append(
                ShortcutViolation(
                    "W-sqrt-call",
                    f"{name} {text!r}에 함수 호출꼴 근호 'sqrt('가 있다 — 학생 표기 '√'로 쓴다"
                    "('8sqrt(3)' → '8√3').",
                )
            )
    q = probe.question_text
    if _W_POINT_X.search(q):
        out.append(
            ShortcutViolation(
                "W-point-x", "'위의 x = a에서의'는 점을 x값으로만 부른다 — 'x좌표가 a인 점'."
            )
        )
    if _W_TRIVIAL_INEQ.search(q):
        out.append(
            ShortcutViolation(
                "W-trivial-ineq",
                "상수만으로 된 자명한 부등식 괄호(예 '(-1 < 0 < 2)')는 템플릿 흔적이다.",
            )
        )
    if _W_ZERO_HOUR.search(q):
        out.append(
            ShortcutViolation("W-zero-hour", "'출발 후 0시간'은 템플릿 값 0이 그대로 든 표현이다.")
        )
    if _W_EXTREMUM_JOSA.search(q):
        out.append(
            ShortcutViolation(
                "W-extremum-josa",
                "'f(x)…의 극값을 갖는'(주어 조사)·'점이 x = '(점과 x값 등치)는 잘못된 표현이다.",
            )
        )
    return out


# ──────────────────────────────────────────────────────────────────────────
# [공통 · 해설]
# ──────────────────────────────────────────────────────────────────────────
#: 도함수 식의 머리 — 'f'(x) = …'·"f'(x)는 3x^2"·"y' = …"·'v(t) = …'·'a(t) = …'·'dy/dx = …'·
#: "f'(a)는 9a^8"(문자에서의 미분계수를 문자식으로)·'도함수는 6x^2 - 2'·'도함수 -3x^2 + 4x'.
#: 우변(그룹 rhs)이 독립변수(또는 괄호 안 문자)를 품어야 *식*이다 — 'f'(x) = 0의 근'은 식이 아니다.
_DERIV_FORMULA = re.compile(
    r"(?<![A-Za-z])(?:(?P<fn>[a-z]'{1,2})\((?P<arg>[a-z])\)|y'|v\(t\)|a\(t\)|dy/dx)"
    r"\s*(?:=|는|은)\s*(?P<rhs>[^가-힣]+)"
    r"|도함수(?:는|가|인|)\s+(?P<rhs2>\(?-?[\dxt(][^가-힣]*)"
)
_VELOCITY_FORMULA = re.compile(r"(?<![A-Za-z])(?:v\(t\)|[a-z]'\(t\))\s*=\s*\S")
_ACCEL_FORMULA = re.compile(r"(?<![A-Za-z])(?:a\(t\)|v'\(t\)|[a-z]''\(t\))\s*=\s*\S")
#: 함수 정의 — 'f(x) = …'·'y = …'·'x = …'(운동의 위치)·'x(t) = …'·'s(t) = …'.
_DEFINITION = re.compile(
    r"(?<![A-Za-z'])(?P<name>[a-z])(?:\((?P<arg>[xt])\))?\s*=\s*(?P<rhs>[^가-힣,=]+)"
)
_FUNCTION_NAMES: Final = frozenset("fghy")


def _clean_rhs(raw: str, var: str) -> str:
    """정의 우변에서 다항식 부분만 남긴다.

    닫히지 않은 괄호 꼬리('(n')·변수 없는 괄호 꼬리('(km)')를 뗀다.
    """
    rhs = raw.strip()
    rhs = re.sub(r"\s*\([^)]*$", "", rhs)
    tail = re.search(r"\s+\(([^()]*)\)\s*$", rhs)
    if tail and var not in tail.group(1):
        rhs = rhs[: tail.start()]
    return rhs.strip()


def _definitions(text: str, var: str) -> list[tuple[str, str]]:
    """발문의 다항함수 정의 (이름, 우변) — 'x = a'(점 지정)·'h(x) = 4f(x) - 2g(x)'(추상 함수 결합)는
    다항함수 정의가 아니다."""
    out: list[tuple[str, str]] = []
    for m in _DEFINITION.finditer(text):
        name, rhs = m.group("name"), _clean_rhs(m.group("rhs"), var)
        if m.group("arg") is None and name == var:
            continue
        if m.group("arg") is None and name not in ("y", "x"):
            continue
        if re.search(r"[a-z]\(", rhs):
            continue
        if not re.search(rf"(?<![A-Za-z]){var}|\d*{var}", rhs):
            continue
        out.append((name, rhs))
    return out


def _max_degree(definitions: Iterable[tuple[str, str]], var: str) -> int:
    """정의된 다항함수의 최고 차수(파싱 불가는 2로 본다 — 상수 도함수 예외를 열지 않는다)."""
    symbol = sympy.Symbol(var)
    best = 0
    for _, rhs in definitions:
        expr = _parse_student(rhs)
        if expr is None or symbol not in expr.free_symbols:
            best = max(best, 2 if expr is None else 0)
            continue
        try:
            best = max(best, int(sympy.degree(sympy.expand(expr), symbol)))
        except sympy.PolynomialError:
            best = max(best, 2)
    return best


def _has_derivative_formula(explanation: str, var: str, max_degree: int) -> bool:
    """해설에 도함수 *식*이 있는가 — 우변이 독립변수(또는 미분계수의 문자 인자)를 품거나, 함수가
    일차 이하라 도함수가 상수일 때(우변 상수 허용)."""
    for m in _DERIV_FORMULA.finditer(explanation):
        rhs = m.group("rhs") if m.group("rhs") is not None else (m.group("rhs2") or "")
        letters = {var}
        if m.group("arg"):
            letters.add(m.group("arg"))
        if any(re.search(rf"\d*{letter}(?![A-Za-z(])", rhs) for letter in letters):
            return True
        # 미분 차수 — 프라임 개수(f''는 2)·a(t)는 2계·그 밖(y'·v(t)·dy/dx·'도함수')은 1계.
        head = m.group(0)
        order = len(m.group("fn")) - 1 if m.group("fn") else (2 if head.startswith("a(") else 1)
        if max_degree <= order and re.search(r"-?\d", rhs):
            return True  # 차수 이하로 미분한 도함수는 상수다(우변 상수 허용)
    return False


def _parameters(definitions: Iterable[tuple[str, str]], var: str) -> set[str]:
    """함수 정의 우변의 미지 상수 — 독립변수·함수 기호(뒤에 '('가 오는 문자)를 뺀 문자."""
    params: set[str] = set()
    for _, rhs in definitions:
        for m in re.finditer(r"[a-z]", rhs):
            letter = m.group(0)
            after = rhs[m.end() : m.end() + 1]
            if letter == var or after == "(" or letter in _FUNCTION_NAMES:
                continue
            params.add(letter)
    return params


def _algebraic_use(text: str, letter: str) -> bool:
    """해설에서 `letter`가 결론('a = 3'·'n은 3')이 아니라 *세운 식* 안에 한 번이라도 드는가."""
    for m in re.finditer(letter, text):
        i, j = m.start(), m.end()
        prev = text[i - 1] if i > 0 else ""
        nxt = text[j] if j < len(text) else ""
        if prev and (prev.isascii() and (prev.isalnum() or prev in ")^")):
            return True
        if nxt and (nxt.isascii() and (nxt.isalnum() or nxt in "^(")):
            return True
        before = text[:i].rstrip()
        after = text[j:].lstrip()
        if before and before[-1] in "+-*/^(":
            return True
        if after and after[0] in "+-*/^)":
            return True
    return False


_INTRO = (
    r"{L}\s*(?:이라|라)\s*(?:하|두|놓)|{L}로\s*(?:두|놓)|[을를]\s+{L}(?![A-Za-z])"
    r"|[xt]\s*=\s*{L}(?![A-Za-z])|인\s+{L}(?:가|이|는|를|의)"
)
_TAUTOLOGY = re.compile(
    r"(?<![A-Za-z0-9])([a-z])\s*=\s*(-?\d+(?:/\d+)?)에서\s*\1\s*=\s*\2(?![\d/])"
)
_TERM_LINEAR = re.compile(r"기울기(?:가)?\s*((?:-?\d+)(?:\s*,\s*-?\d+)*)\s*인\s*일차함수")
#: [4회차] 해설이 꺼내는 도형 대상 — 발문(`_Q_OBJECT`)에 그 대상을 소개하는 말이 하나도 없으면 결함.
_E_OBJECT = re.compile(r"두 점을 잇는|접점|접선")
_Q_OBJECT = re.compile(r"점|접|곡선|직선|그래프")


def _explanation_rules(probe: ShortcutProbe) -> list[ShortcutViolation]:
    out: list[ShortcutViolation] = []
    q, e = probe.question_text, probe.explanation
    var = str(_variable_of(probe))
    defs = _definitions(q, var)
    if defs and not _has_derivative_formula(e, var, _max_degree(defs, var)):
        out.append(
            ShortcutViolation(
                "E-derivative",
                "발문이 다항함수를 주는데 해설에 도함수 식(f'(x) = …·도함수는 …·v(t) = …)이 없다 — "
                "결론만 적은 해설이다.",
            )
        )
    for letter in sorted(_parameters(defs, var)):
        if not _algebraic_use(e, letter):
            out.append(
                ShortcutViolation(
                    "E-parameter",
                    f"발문 함수식의 미지 상수 {letter}가 해설에 세운 식(예 {letter}를 포함한 "
                    "방정식) "
                    "없이 결론으로만 나온다.",
                )
            )
    instant_q = re.sub(r"평균\s*속도", "", q).replace("가속도", "")
    if re.search(r"속도|속력|멈추|정지|운동 방향|방향을 바|방향이 바뀌", instant_q):
        if not _VELOCITY_FORMULA.search(e):
            out.append(
                ShortcutViolation("E-kinematics", "속도를 다루는 문항인데 해설에 v(t) 식이 없다.")
            )
    if "가속도" in q and not _ACCEL_FORMULA.search(e):
        out.append(
            ShortcutViolation("E-kinematics", "가속도를 묻는 문항인데 해설에 a(t) 식이 없다.")
        )
    if re.search(r"방향을 바|방향이 바뀌", q) and "부호" not in e:
        out.append(
            ShortcutViolation(
                "E-sign",
                "운동 방향 전환을 묻는데 해설에 속도의 부호 판정이 없다(v = 0이 곧 방향 전환은 "
                "아니다).",
            )
        )
    q_letters = set(re.findall(r"(?<![A-Za-z])[a-z](?![A-Za-z])", q))
    for m in re.finditer(r"(?<![A-Za-z])[a-z]'{1,2}\(([a-z])\)", e):
        letter = m.group(1)
        if letter in ("x", "t") or letter in q_letters:
            continue
        if not re.search(_INTRO.format(L=letter), e):
            out.append(
                ShortcutViolation(
                    "E-symbol-intro",
                    f"해설이 발문에 없는 기호 {letter}를 소개 없이 쓴다('구하는 x좌표를 {letter}라 "
                    "하자').",
                )
            )
            break
    if _TAUTOLOGY.search(e):
        out.append(ShortcutViolation("E-tautology", "'q = 3에서 q = 3이다' 같은 순환 서술이 있다."))
    for m in _TERM_LINEAR.finditer(e):
        slopes = [s.strip() for s in m.group(1).split(",")]
        if "0" in slopes:
            out.append(
                ShortcutViolation("E-term", "기울기가 0인 함수는 상수함수이지 일차함수가 아니다.")
            )
    named = _E_OBJECT.search(e)
    if named is not None and not _Q_OBJECT.search(q):
        out.append(
            ShortcutViolation(
                "E-object-intro",
                f"해설이 발문에 없는 대상 '{named.group(0)}'을(를) 소개 없이 쓴다 — 발문에 점·곡선·"
                "직선·그래프가 없으면 '구간에서의 평균변화율'·'f'(c)'처럼 발문의 말로 쓴다.",
            )
        )
    return out


# ──────────────────────────────────────────────────────────────────────────
# [개념 · 우회로]
# ──────────────────────────────────────────────────────────────────────────
_TANGENCY = re.compile(r"접할 때|접하도록|접한다|접하는 (?:점|직선)|그은 (?:두 )?접선")
_CURVE = re.compile(r"곡선 y = ")


def _curve_degrees(q: str) -> list[int]:
    degrees: list[int] = []
    for m in _CURVE.finditer(q):
        chunk = _POLY_RE.match(q, m.end())
        if chunk is None:
            continue
        expr = _parse_student(chunk.group(0))
        if expr is None:
            continue
        x = sympy.Symbol("x")
        if x in expr.free_symbols:
            degrees.append(int(sympy.degree(expr, x)))
    return degrees


#: [4회차] 수평 접선을 묻는 표현 — 포물선이면 꼭짓점 공식으로 바로 풀린다.
_HORIZONTAL = re.compile(r"꼭짓점|x축에 평행|수평|기울기가 0(?:일|인)")
#: [4회차] 직선 위의 점에서의 접선 — '직선 y = 2x - 5 위의 점 (2, -1)에서의 접선'.
_LINE_POINT = re.compile(r"직선 y = [^가-힣]+ 위의")


def _tangent_rules(probe: ShortcutProbe) -> list[ShortcutViolation]:
    q = probe.question_text
    out: list[ShortcutViolation] = []
    degrees = _curve_degrees(q)
    if _TANGENCY.search(q) and degrees and max(degrees) <= 2:
        out.append(
            ShortcutViolation(
                "T05-quadratic-tangency",
                "접할 조건을 묻는데 곡선이 이차 이하라 연립 이차방정식의 판별식만으로 풀린다 — "
                "곡선 차수가 3 이상이거나 접점의 미분계수가 풀이에 필수여야 한다.",
            )
        )
    if degrees and max(degrees) <= 2 and _HORIZONTAL.search(q):
        out.append(
            ShortcutViolation(
                "T05-vertex-tangent",
                "곡선이 이차 이하인데 꼭짓점·x축에 평행한 접선(기울기 0)을 묻는다 — 포물선의 수평 "
                "접선은 꼭짓점에만 생기므로 -b/(2a)·완전제곱으로 미분 없이 풀린다.",
            )
        )
    if "접선" in q and _LINE_POINT.search(q):
        out.append(
            ShortcutViolation(
                "T05-line-tangent",
                "직선 위의 점에서의 접선을 묻는다 — 직선의 접선은 그 직선 자신이라 기울기를 읽기만 "
                "하면 되고, 미분계수 개념이 없는 학생도 맞힌다.",
            )
        )
    return out


#: [4회차] x = 0에서의 값을 묻는 표현 — 대입('10을 대입'은 아니다)·미분계수 f'(0)·원점·
#: 'x좌표가 0인'.
#: 'x = 0'은 x 위치 고정 읽기(`_PIN_X` — 분수까지 수 하나를 통째로 읽는다)를 그대로 쓴다.
_ZERO_PHRASE = re.compile(r"(?<!\d)0을 대입|[a-z]'\(0\)|원점|x좌표가 0인")
#: [4회차] 방정식 f'(x) = 0의 근을 묻는 표현.
_DERIV_ROOT = re.compile(r"[a-z]'\(x\) = 0의 (?:실근|근|해)")


def _is_power_monomial(expr: sympy.Expr, var: sympy.Symbol) -> bool:
    """x에 대해 항이 하나뿐이고 차수가 2 이상인가(c·x^n).

    계수 c는 문자여도 된다 — kx^2도 x = 0에서의 미분계수가 0이다.
    """
    try:
        poly = sympy.Poly(expr, var)
    except sympy.PolynomialError:
        return False
    return len(poly.terms()) == 1 and poly.degree() >= 2


def _zero_monomial_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """단항식 c·x^n의 x = 0(또는 f'(x) = 0의 근) — 정답·원함수 대입·오답 경로가 모두 0이다."""
    q = probe.question_text
    x = sympy.Symbol("x")
    if not any(_is_power_monomial(p, x) for p in visible_polynomials(q)):
        return []
    pinned = {sympy.Rational(v) for v in _PIN_X.findall(q)}  # `_PIN_X`는 02-08 절에 정의(같은 경계)
    at_zero = _ZERO_PHRASE.search(q) is not None or 0 in pinned
    if at_zero or _DERIV_ROOT.search(q):
        return [
            ShortcutViolation(
                "T-zero-monomial",
                "단항식 c·x^n(n ≥ 2)의 x = 0에서의 미분계수(또는 f'(x) = 0의 근)를 묻는다 — "
                "정답이 0이고 원함수에 대입해도, 지수를 안 줄이거나 계수를 빠뜨려도 0이라 거듭제곱 "
                "미분법을 변별하지 못한다.",
            )
        ]
    return []


_EXTREMUM_VALUE = re.compile(r"(?<![A-Za-z])[xt] = (-?\d+)에서 극(?:댓|솟)?값 (-?\d+)")
_TOUCH_AT = re.compile(r"(?:(?<![A-Za-z])x = |x좌표가 )(-?\d+)인 점에서 (?:서로 )?접")
_ASKED_CONSTANT = re.compile(r"상수 ([a-z])의 값")


def _asked_parameter(probe: ShortcutProbe) -> str | None:
    amap = probe.answer_dict
    for key, value in amap.items():
        if key not in ("x", "y", "t", "s") and value.strip() == probe.answer.strip():
            return key
    m = _ASKED_CONSTANT.search(probe.question_text)
    return m.group(1) if m else None


def _value_equations(probe: ShortcutProbe, var: sympy.Symbol) -> list[sympy.Expr]:
    """발문이 주는 *미분 없는* 조건 — 극값의 값(f(a) = V)·두 곡선이 a에서 만남(C1(a) = C2(a))."""
    q = probe.question_text
    defs = _definitions(q, str(var))
    funcs = [e for e in (_parse_student(rhs) for _, rhs in defs) if e is not None]
    eqs: list[sympy.Expr] = []
    m = _EXTREMUM_VALUE.search(q)
    if m and funcs:
        a, value = int(m.group(1)), int(m.group(2))
        with_params = [f for f in funcs if f.free_symbols - {var}]
        if with_params:
            eqs.append(with_params[0].subs(var, a) - value)
    touch = _TOUCH_AT.search(q)
    curves = visible_polynomials(q)
    curves = [c for c in curves if var in c.free_symbols and sympy.degree(c, var) >= 1]
    if touch and len(curves) >= 2:
        a = int(touch.group(1))
        eqs.append(curves[0].subs(var, a) - curves[1].subs(var, a))
    return eqs


def _value_determines_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    var = _variable_of(probe)
    asked = _asked_parameter(probe)
    if asked is None:
        return []
    eqs = _value_equations(probe, var)
    if not eqs:
        return []
    target = sympy.Symbol(asked)
    unknowns = sorted(set().union(*(e.free_symbols for e in eqs)) - {var}, key=str)
    if target not in unknowns:
        return []
    solutions = sympy.solve(eqs, unknowns, dict=True)
    values = {sol.get(target) for sol in solutions}
    if len(values) == 1 and None not in values and not next(iter(values)).free_symbols:
        return [
            ShortcutViolation(
                "T-value-determines",
                f"발문의 함숫값 조건만으로 상수 {asked}가 정해진다 — 미분계수 조건이 풀이에 쓰이지 "
                "않는다(대입만으로 풀린다).",
            )
        ]
    return []


_GIVEN_RATE = re.compile(r"평균변화율(?:은|이|는)?\s+-?\d")


def _mvt_rules(probe: ShortcutProbe) -> list[ShortcutViolation]:
    if _GIVEN_RATE.search(probe.question_text):
        return [
            ShortcutViolation(
                "T06-given-rate",
                "발문이 평균변화율의 값을 직접 준다 — 평균변화율을 구해 미분계수와 잇는 평균값 "
                "정리의 "
                "행위가 빠진다.",
            )
        ]
    return []


#: 도함수 부등식 — 코드식('<=')과 학생 표기('≤') 둘 다 읽는다(표기 교정이 규칙을 끄지 않게).
_DERIV_INEQ = re.compile(r"(?<![A-Za-z])[a-z]'\((?:x|t)\)\s*(?:<|>|<=|>=|≤|≥)\s")
_PINNED_KIND = re.compile(r"(?<![A-Za-z])x = -?\d+에서(?:의)? 극(?:댓|솟)값")
#: [4회차] 발문이 고정한 x 위치 — 'x = -1과 x = 3'·'x = 1/2'.
_PIN_X = re.compile(r"(?<![A-Za-z])x = (-?\d+(?:/\d+)?)")


def _sign_change_roots(expr: sympy.Expr, var: sympy.Symbol) -> set[sympy.Rational]:
    """f'의 유리수 근 중 좌우에서 부호가 바뀌는 근(= 극값을 갖는 x) — 판정 정의의 단일 원천."""
    deriv = sympy.expand(sympy.diff(expr, var))
    if deriv.free_symbols != {var}:
        return set()
    roots = sorted(
        r for r in sympy.roots(sympy.Poly(deriv, var)) if r.is_rational  # 정수·분수 근만
    )
    if not roots:
        return set()
    middles = [(a + b) / 2 for a, b in zip(roots, roots[1:], strict=False)]
    probes = [roots[0] - 1, *middles, roots[-1] + 1]
    signs = [sympy.sign(deriv.subs(var, p)) for p in probes]
    return {r for i, r in enumerate(roots) if signs[i] * signs[i + 1] < 0}


def _graph_shape_round4_rules(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[4회차] 02-08 — 극값 위치를 둘 이상 준 문항·복이차 사차식."""
    q = probe.question_text
    x = sympy.Symbol("x")
    pins = {sympy.Rational(v) for v in _PIN_X.findall(q)}
    out: list[ShortcutViolation] = []
    given = False
    biquadratic = False
    for poly in visible_polynomials(q):
        if x not in poly.free_symbols:
            continue
        if len(pins & _sign_change_roots(poly, x)) >= 2:
            given = True
        if poly.free_symbols == {x} and is_shifted_biquadratic(poly, x):
            biquadratic = True
    if given:
        out.append(
            ShortcutViolation(
                "T08-given-critical-points",
                "발문이 극값을 갖는 x 위치를 둘 이상 준다 — 그 위치에 대입해 대소를 비교하면 "
                "극댓값·극솟값이 정해져(삼차·사차에서 '큰 값이 극댓값') 도함수와 부호 판정이 필요 "
                "없다. 임계점은 학생이 f'(x) = 0을 풀어 찾게 한다.",
            )
        )
    if biquadratic:
        out.append(
            ShortcutViolation(
                "T08-biquadratic",
                "발문의 사차식이 x = h에 대해 대칭(복이차)이라 (x - h)^2 = u로 두면 완전제곱만으로 "
                "극값의 위치·값이 나온다 — 비대칭 사차식을 쓴다.",
            )
        )
    return out


def _graph_shape_rules(probe: ShortcutProbe) -> list[ShortcutViolation]:
    q = probe.question_text
    out: list[ShortcutViolation] = []
    if _DERIV_INEQ.search(q):
        out.append(
            ShortcutViolation(
                "T08-derivative-inequality",
                "발문이 도함수 부등식(f'(x) < 0 등)을 직접 준다 — 증가·감소 판정 없이 이차부등식만 "
                "풀면 된다.",
            )
        )
    if _PINNED_KIND.search(q) and _asked_parameter(probe) is None:
        out.append(
            ShortcutViolation(
                "T08-pinned-kind",
                "극값의 위치와 종류를 발문이 모두 주고 그 값을 묻는다 — 대입만으로 풀린다.",
            )
        )
    return out


def _equation_rules(probe: ShortcutProbe) -> list[ShortcutViolation]:
    var = _variable_of(probe)
    amap = probe.answer_dict
    out: list[ShortcutViolation] = []
    has_derivative_condition = any("Derivative" in c for c in probe.conditions)
    if probe.answer_kind == _REAL_ROOT_COUNT:
        form = "count"
    elif set(amap) == {str(var)} and not has_derivative_condition:
        form = "root"
    elif str(var) in amap and has_derivative_condition:
        form = "extremum"
    else:
        return []
    if form == "extremum":
        pinned = amap[str(var)]
        if pinned.strip() == "0":
            out.append(
                ShortcutViolation(
                    "T09-pinned-minimizer",
                    "최솟값(극값)을 x = 0에서 갖는다 — 다항식의 상수항이 곧 답이라 미분이 필요 "
                    "없다.",
                )
            )
        if re.search(rf"(?<![A-Za-z]){var} = {re.escape(pinned)}(?![\d/])", probe.question_text):
            out.append(
                ShortcutViolation(
                    "T09-pinned-minimizer",
                    "최솟값(극값)을 묻는데 발문이 그 값을 갖는 x를 알려 준다 — 대입만으로 풀린다.",
                )
            )
        return out
    relation = next((r for r in map(_parse_relation, probe.conditions) if r is not None), None)
    if relation is None:
        return []
    poly = relation.difference
    if poly.free_symbols != {var}:
        return []
    visible = visible_polynomials(probe.question_text)
    for side in (relation.lhs, relation.rhs):
        if side.free_symbols and not any(sympy.expand(side - v) == 0 for v in visible):
            return []  # 학생이 보지 못하는 대표 함수(극값 증인)로 검산하는 문항
    if sympy.degree(poly, var) <= 2:
        out.append(
            ShortcutViolation(
                "T09-low-degree",
                "발문의 방정식·부등식이 이차 이하라 판별식·근의 공식만으로 풀린다.",
            )
        )
    if has_rational_root(poly, var):
        out.append(
            ShortcutViolation(
                "T09-rational-root",
                f"발문에 보이는 다항식 {poly}이 유리수 근을 갖는다 — 인수정리·인수분해로 근(또는 "
                "등호점)을 바로 얻어 도함수가 필요 없다.",
            )
        )
    if is_shifted_biquadratic(poly, var):
        out.append(
            ShortcutViolation(
                "T09-biquadratic",
                "발문의 사차식이 x = h에 대해 대칭(짝수 차 항만)이라 (x - h)^2 = u로 두면 "
                "이차방정식이 "
                "된다 — 도함수 없이 근의 공식·판별식으로 풀린다.",
            )
        )
    if form == "root" and _has_repeated_factor(poly, var):
        out.append(
            ShortcutViolation(
                "T09-repeated-root",
                "등호가 성립하는 점(근)을 묻는데 그 점이 중근이다 — 완전제곱·인수로 바로 얻는다.",
            )
        )
    return out


#: [4회차] 02-09의 '활용' 맥락 — 방정식·부등식·교점·위치 관계 중 하나는 발문에 있어야 한다.
_APPLICATION = re.compile(
    r"방정식|부등식|실근|만나|교점|위쪽|아래쪽|보이려|성립|보다 크|보다 작|오른쪽|왼쪽"
    r"|시각의 개수|x축"
)


def _application_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    if _APPLICATION.search(probe.question_text):
        return []
    return [
        ShortcutViolation(
            "T09-no-application",
            "발문에 방정식·부등식·교점·위치 관계 맥락이 없는 최댓값·최솟값 문항이다 — "
            "02-09(방정식과 부등식에의 활용)의 인지 행동 없이 극값 비교(02-07/02-08 영역)만으로 "
            "풀린다.",
        )
    ]


#: [4회차] 운동 문항의 위치 함수 — '위치가 x = 7로'·'위치가 x = -3t + 2일 때'·'위치가 x(t) = …'.
_POSITION = re.compile(r"위치가 (?:x|x\(t\)) = (?P<rhs>[^가-힣,]+)")


def _velocity_rules(probe: ShortcutProbe) -> list[ShortcutViolation]:
    q = probe.question_text
    instant = re.sub(r"평균\s*속도", "", q)
    out: list[ShortcutViolation] = []
    if re.search(r"평균\s*속도", q) and not re.search(r"속도|속력|멈추|정지|방향", instant):
        out.append(
            ShortcutViolation(
                "T10-average-only",
                "평균속도만 묻는다 — 위치에 두 시각을 대입한 차분몫이라 미분(순간속도)이 필요 "
                "없다.",
            )
        )
    t = sympy.Symbol("t")
    if re.search(r"속도|속력", instant):
        for m in _POSITION.finditer(q):
            expr = _parse_student(_clean_rhs(m.group("rhs"), "t"))
            if expr is None:
                continue
            degree = int(sympy.degree(expr, t)) if t in expr.free_symbols else 0
            if degree <= 1:
                out.append(
                    ShortcutViolation(
                        "T10-linear-position",
                        f"위치 {m.group('rhs').strip()!r}가 t의 일차 이하인데 속도·가속도를 "
                        "묻는다 — "
                        "정지(속도 0)·등속(가속도 0)·일차함수의 기울기라는 선수 지식으로 풀린다.",
                    )
                )
                break
    return out


def shortcut_violations(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """문항 1건의 우회로·해설·표기 위반 목록 — 빈 리스트면 통과."""
    out = _notation_rules(probe) + _explanation_rules(probe) + _zero_monomial_rule(probe)
    code = probe.standard_code
    if code == _C05:
        out += _tangent_rules(probe)
    if code in (_C05, _C08):
        out += _value_determines_rule(probe)
    if code == _C06:
        out += _mvt_rules(probe)
    if code == _C08:
        out += _graph_shape_rules(probe) + _graph_shape_round4_rules(probe)
    if code == _C09:
        out += _equation_rules(probe) + _application_rule(probe)
    if code == _C10:
        out += _velocity_rules(probe)
    return out


def violations_by_rule(probes: Sequence[ShortcutProbe]) -> dict[str, int]:
    """표본 묶음의 규칙별 위반 문항 수(보고용) — 한 문항이 같은 규칙을 여러 번 어겨도 1로 센다."""
    counts: dict[str, int] = {rule: 0 for rule in RULE_IDS}
    for probe in probes:
        for rule in {v.rule for v in shortcut_violations(probe)}:
            counts[rule] += 1
    return counts
