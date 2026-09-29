"""학생 입력 CAS 파싱 안전 진입점(`l3/safe_parse.py`) 계약 — 코딩 헌법 R22-03 집행 장치(CONST-09).

세 축을 동결한다.
  ① 대조군 — 기존 스위트·저작 코퍼스가 파서에 넣던 정상 입력은 원 파서와 **같은 결과**로 통과한다.
  ② 적대 입력 — 재현표(2026-09-29 실측: `9^9^9` 등이 학생 답 경로에서 20초 timeout)의 입력은
     전부 **거부**되고, 거부는 200ms 안에 끝난다(시간 예산 = 결정론적 구조 상한의 증명).
  ③ 계산 후 재검사 — 구조 검사를 통과해도 계산이 키운 값(`factorial(1000)*factorial(1000)`·
     `root(x, 1/100)` → `x^100`)은 거부된다.

거버넌스(진입점 밖 직접 파싱 0건)는 `tests/infra/test_cas_parse_entrypoint_governance.py`가 본다.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import sympy
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication,
    parse_expr,
    standard_transformations,
)

from whymath_backend.l3 import safe_parse
from whymath_backend.l3.safe_parse import (
    MAX_INPUT_LENGTH,
    UnsafeExpressionError,
    ensure_within_budget,
    safe_parse_expr,
    safe_parse_latex,
    safe_subs,
    safe_sympify,
)
from whymath_backend.l3.symbolic_equivalence import (
    IdentityVerdict,
    identity_status,
    latex_to_plain,
)

# 동치 권위·사전생성 검증기가 쓰는 변환(암묵곱·^) — 두 번째 파싱 모드.
_T_IMPLICIT = standard_transformations + (implicit_multiplication, convert_xor)
_REPO_ROOT = Path(__file__).resolve().parents[3]
# 시간 예산(초) — 모듈 상수와 같은 값. 적대 입력 거부가 이 안에 끝나야 한다.
_BUDGET_S = 0.2

_X = sympy.Symbol("x")


@pytest.fixture(autouse=True)
def _fresh_parse_cache() -> Iterator[None]:
    """테스트마다 판정 캐시를 비운다 — 관측 로그·설정을 바꾸는 테스트가 앞 테스트의 캐시 칸에
    가려져 순서에 따라 결과가 달라지지 않게 한다(pytest-randomly 무작위 순서)."""
    safe_parse.clear_parse_cache()
    yield
    safe_parse.clear_parse_cache()


def _srepr_or_fail(fn: Callable[[], Any]) -> str:
    """결과의 구조 표현(srepr) — 실패면 "FAIL"(원 파서·안전 파서 양쪽 비교용)."""
    try:
        return str(sympy.srepr(fn()))
    except Exception:  # noqa: BLE001 — 비교용: 실패 자체가 관측값이다
        return "FAIL"


# ──────────────────────────────────────────────────────────────────────
# ① 대조군 — 정상 입력은 원 파서와 같은 결과
# ──────────────────────────────────────────────────────────────────────

# 기존 스위트가 파서에 실제로 넣던 입력(2026-09-29 수집 680,211건 중 형태별 대표)·저작 코퍼스
# 조건식 형태·중고교 표준 표기. 한 줄에 한 형태씩.
_CONTROL_SYMPIFY: tuple[str, ...] = (
    "x**2 - 5*x + 6",
    "x^2 - 5*x + 6",
    "2*a*x",
    "b/(2*a)",
    "x**2 >= 4",
    "x > 0",
    "a*x <= 0",
    "x != 1",
    "Eq(x**2, 9)",
    "sin(x)**2 + cos(x)**2",
    "sqrt(3)/2",
    "sqrt(2)",
    "1/36",
    "2/72",
    "0.5",
    "0.0277777777",
    "1.3333333333333333",
    "100000000",
    "16777216",
    "2^28",
    "2^27 + 2^27",
    "2*2^27",
    "(2^3)^8",
    "(-3)^6",
    "(-1)^2025",
    " (2+22)**2",
    "x ",
    " 30",
    "log(2**27 + 2**27, 2)",
    "x - (factorial(2 + 7 - 1)/(factorial(7) * factorial(2 - 1)))",
    "Derivative((-1*x**2 + -3*x + -3) / (-3*x + -10), x).doit().subs(x, -3)",
    "Derivative((-4*x + 5)**5, x).doit().subs(x, 2)",
    "Integral(4*x**2+x-2,(x,0,2)) + 8",
    "floor(7/2)",
    "ceiling(7/2)",
    "gcd(12, 18)",
    "lcm(4, 6)",
    "Abs(-3)",
    "x - (((24 - -6)/(-12 - -6)) + (-6 - ((24 - -6)/(-12 - -6))*-6))",
    "(x - 1)**3",
    "(x+1)^20",
    "x^(1/2)",
    "pi/6",
    "sin(pi/6)",
    "E**2",
    "3*I + 2",
    "True",
    "largest_root(2, 8)",
    "whymathfinalanswervalue - 3",
    "C2*P3",
    "a1 + x2",
)

_CONTROL_IMPLICIT: tuple[str, ...] = (
    "2x + 1",
    "(x+1)(x-1)",
    "2(x+1)",
    "x y",
    "3x^2 - 2x",
    "서술형 논증",  # 한글 단어는 현행 파서가 기호로 읽는다 — 판정이 그에 의존한다
    "정답은 3",
    "2개",
    "C2 P3",
    "a**0",
    "x^2",
)


@pytest.mark.parametrize("text", _CONTROL_SYMPIFY)
def test_control_sympify_parses_identically(text: str) -> None:
    """정상 입력 — 안전 진입점 결과가 `sympy.sympify(convert_xor=True)`와 같다."""
    original = _srepr_or_fail(lambda: sympy.sympify(text, convert_xor=True))
    assert original != "FAIL", f"대조군 입력이 원 파서에서도 실패한다: {text!r}"
    assert _srepr_or_fail(lambda: safe_sympify(text)) == original


@pytest.mark.parametrize("text", _CONTROL_SYMPIFY)
def test_control_sympify_evaluate_false_parses_identically(text: str) -> None:
    """표면 보존(evaluate=False) 모드도 같은 결과 — 답 형태·오개념 정합이 쓰는 모드."""
    original = _srepr_or_fail(lambda: sympy.sympify(text, evaluate=False))
    assert _srepr_or_fail(lambda: safe_sympify(text, evaluate=False)) == original


@pytest.mark.parametrize("text", _CONTROL_IMPLICIT)
def test_control_implicit_multiplication_parses_identically(text: str) -> None:
    """암묵곱 모드(`parse_expr`) — 동치 권위(`identity_status`)·해집합 경로의 파싱과 같다."""
    original = _srepr_or_fail(lambda: parse_expr(text, transformations=_T_IMPLICIT))
    assert original != "FAIL", f"대조군 입력이 원 파서에서도 실패한다: {text!r}"
    assert _srepr_or_fail(lambda: safe_parse_expr(text, transformations=_T_IMPLICIT)) == original


def test_control_local_dict_names_are_trusted() -> None:
    """DSL 제약식 — 호출부가 명시한 `local_dict` 이름·`%`는 통과하고 결과가 같다."""
    local = {"a": 3, "b": 2, "c": 11}
    text = "(c - b) % a == 0"
    original = parse_expr(text, local_dict=dict(local), transformations=_T_IMPLICIT)
    assert safe_parse_expr(text, local_dict=dict(local), transformations=_T_IMPLICIT) == original


def _corpus_condition_sides(stride: int) -> list[str]:
    """저작 코퍼스(problem_bank_*)의 조건식 양변·답산맵 값 — 결정론적 간격 표본."""
    sides: set[str] = set()
    for path in sorted((_REPO_ROOT / "data" / "corpus").glob("problem_bank_*/problems.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                verify = json.loads(line).get("verify") or {}
            except (json.JSONDecodeError, AttributeError):
                continue
            conditions = verify.get("conditions")
            items = [conditions] if isinstance(conditions, str) else list(conditions or [])
            items += [v for v in (verify.get("answer_map") or {}).values() if isinstance(v, str)]
            for item in items:
                if not isinstance(item, str):
                    continue
                for op in ("<=", ">=", "!=", "==", "<", ">", "="):
                    if op in item:
                        sides.update(item.split(op, 1))
                        break
                else:
                    sides.add(item)
    return sorted(sides)[::stride]


def test_authored_corpus_sample_parses_identically() -> None:
    """저작 코퍼스 조건식 표본 — 원 파서가 읽던 것은 안전 진입점도 **같은 결과**로 읽는다.

    전수(12,475 고유 식·2026-09-29 실측: 거짓 거부 0·결과 차이 0)는 42초라 여기서는 간격
    표본만 돈다. 표본이 비면(코퍼스 경로가 바뀌면) 공허하게 통과하지 않고 실패한다.
    """
    sample = _corpus_condition_sides(stride=30)
    assert len(sample) > 100, f"코퍼스 표본이 너무 적다({len(sample)}) — 경로를 확인하라"
    mismatches = []
    for text in sample:
        original = _srepr_or_fail(lambda t=text: sympy.sympify(t, convert_xor=True))
        if original == "FAIL":
            continue
        if _srepr_or_fail(lambda t=text: safe_sympify(t)) != original:
            mismatches.append(text)
    assert not mismatches, f"코퍼스 식 {len(mismatches)}건이 달라졌다: {mismatches[:5]}"


# ──────────────────────────────────────────────────────────────────────
# ② 적대 입력 — 거부 + 시간 예산
# ──────────────────────────────────────────────────────────────────────

# (입력, 기대 사유 코드). 재현표(①)의 입력 + 같은 부류의 변형.
_ADVERSARIAL: tuple[tuple[str, str], ...] = (
    ("9^9^9", "power_too_large"),
    ("9**9**9", "power_too_large"),
    ("2^100000", "power_too_large"),
    ("2^1000000000", "power_too_large"),
    ("(x^99)^99", "degree_too_high"),
    ("x^99+x+1", "degree_too_high"),
    ("(x+y+z+w+v)^60", "degree_too_high"),
    ("(a+b+c+d+e)^20", "expansion_too_large"),
    ("(10^9)!", "factorial_too_large"),
    ("99999!", "factorial_too_large"),
    ("factorial(10**9)", "factorial_too_large"),
    ("binomial(10^6, 5*10^5)", "binomial_too_large"),
    ("exp(10^6)", "power_too_large"),
    ("Derivative(x**3, x, 1000000000).doit()", "derivative_order_too_large"),
    ("Integral(exp(x**2)*sin(x)**40, x).doit()", "heavy_operator_doit"),
    ("7" * 5000, "too_long"),
    ("7" * 200, "literal_too_long"),
    ("1e999999", "float_exponent_too_large"),
    ("(" * 200 + "1" + ")" * 200, "nesting_too_deep"),
    ("(" * 90 + "x" + ")" * 90, "nesting_too_deep"),
    ("^".join(["x"] * 70), "tree_too_deep"),
    ("exec(chr(49))", "disallowed_name"),
    ("__import__", "disallowed_name"),
    ("ｅｘｅｃ(1)", "disallowed_name"),  # 전각 — 파이썬은 식별자를 NFKC로 정규화한다
    ("S(12)", "disallowed_name"),
    ("var(x)", "disallowed_name"),
    ("lambdify(x, x)", "disallowed_name"),
    ("x if x else 1", "disallowed_name"),
    ("x.evalf()", "disallowed_attribute"),
    ("(1).__class__", "disallowed_attribute"),
    ("sympify('x')", "disallowed_char"),
    ("x # 주석", "disallowed_char"),
)


@pytest.fixture(scope="module", autouse=True)
def _warm_up() -> None:
    """첫 호출의 지연 초기화(SymPy 내부)를 시간 측정에서 뺀다 — 정상 입력 1회."""
    safe_sympify("x + 1")
    safe_parse_expr("2x + 1", transformations=_T_IMPLICIT)


@pytest.mark.parametrize(("text", "code"), _ADVERSARIAL, ids=[c for _, c in _ADVERSARIAL])
def test_adversarial_input_is_rejected_within_budget(text: str, code: str) -> None:
    """적대 입력 — 두 파싱 모드 모두 기대 사유로 거부되고, 각각 200ms 안에 끝난다."""
    for parse in (
        lambda: safe_sympify(text),
        lambda: safe_parse_expr(text, transformations=_T_IMPLICIT),
    ):
        started = time.perf_counter()
        with pytest.raises(UnsafeExpressionError) as info:
            parse()
        elapsed = time.perf_counter() - started
        assert info.value.code == code
        assert elapsed < _BUDGET_S, f"거부에 {elapsed:.3f}s — 시간 예산 {_BUDGET_S}s 초과"


# 예산 사유(구조 검사가 거르는 것) — 문자열 검사(①②③)에서 걸리는 사유는 여기 해당하지 않는다.
_BUDGET_CODES = frozenset(
    {
        "power_too_large",
        "exponent_too_large",
        "degree_too_high",
        "expansion_too_large",
        "factorial_too_large",
        "binomial_too_large",
        "derivative_order_too_large",
        "tree_too_deep",
        "integer_too_large",
    }
)


@pytest.mark.parametrize(
    ("text", "code"),
    [(t, c) for t, c in _ADVERSARIAL if c in _BUDGET_CODES],
    ids=[c for _, c in _ADVERSARIAL if c in _BUDGET_CODES],
)
def test_structural_stage_alone_rejects_budget_inputs(text: str, code: str) -> None:
    """구조 단계(계산 없음)만으로 예산 입력이 거부된다 — 실제 파서는 한 번도 돌지 않는다.

    이 단계가 뚫리면 다음 단계인 실제 파싱이 `9^9^9`를 *계산*하므로(재현표: 20초 timeout),
    거부는 반드시 계산 전에 나야 한다. 여기서 확인하는 것은 그 순서다.
    """
    transformations = standard_transformations + (convert_xor,)
    started = time.perf_counter()
    with pytest.raises(UnsafeExpressionError) as info:
        safe_parse._check_tree(
            safe_parse._structural_parse(text, transformations=transformations, local_dict=None)
        )
    assert info.value.code == code
    assert time.perf_counter() - started < _BUDGET_S


def test_rejection_is_a_sympify_error_without_student_text() -> None:
    """거부는 SympifyError(→ValueError) — 기존 except가 받는다. 메시지에 원문이 없다(PII)."""
    with pytest.raises(UnsafeExpressionError) as info:
        safe_sympify("9^9^9")
    assert isinstance(info.value, sympy.SympifyError)
    assert isinstance(info.value, ValueError)
    assert "9^9^9" not in str(info.value)
    assert "power_too_large" in str(info.value)


def test_rejection_logs_reason_code_not_text(caplog: pytest.LogCaptureFixture) -> None:
    """침묵 실패 금지 — 거부 사유 코드를 로그에 남기되 학생 원문은 싣지 않는다."""
    with caplog.at_level(logging.INFO, logger="whymath.l3.safe_parse"):
        with pytest.raises(UnsafeExpressionError):
            safe_sympify("99999!")
    messages = [r.getMessage() for r in caplog.records]
    assert any("factorial_too_large" in m for m in messages), messages
    assert not any("99999" in m for m in messages), messages


def test_length_cap_boundary() -> None:
    """길이 상한 경계 — 정확히 상한이면 통과, 한 글자 넘으면 거부."""
    assert safe_sympify("a" * MAX_INPUT_LENGTH) == sympy.Symbol("a" * MAX_INPUT_LENGTH)
    with pytest.raises(UnsafeExpressionError, match="too_long"):
        safe_sympify("a" * (MAX_INPUT_LENGTH + 1))


def test_exec_payload_does_not_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """허용 문자(영문자·숫자·괄호·`+`)만으로 된 코드 실행 입력이 **실행되지 않는다**.

    대조군이 먼저다: 같은 입력을 원 `sympy.sympify`에 넣으면 실제로 파일이 생긴다(재현표의
    임의 코드 실행). 그 뒤 안전 진입점은 거부하고 파일이 생기지 않는다. 대조군 없이 "안
    생겼다"만 보면 페이로드가 애초에 무효였을 때도 초록이다.
    """
    # 상대 경로로 짧게 — 페이로드 길이가 길이 상한에 걸려 *다른 사유*로 거부되면 식별자
    # 검사의 변별력을 증명하지 못한다.
    monkeypatch.chdir(tmp_path)
    control = tmp_path / "c"
    guarded = tmp_path / "g"

    def payload(target: Path) -> str:
        code = f"open({target.name!r},'w')"
        return "exec(" + "+".join(f"chr({ord(ch)})" for ch in code) + ")"

    control_text = payload(control)
    assert set(control_text) <= set("exchr()+0123456789")
    sympy.sympify(control_text)  # 원 파서 — 실행된다(이것이 막아야 할 상태)
    assert control.exists(), "대조군 페이로드가 실행되지 않았다 — 이 테스트는 변별력이 없다"

    with pytest.raises(UnsafeExpressionError, match="disallowed_name"):
        safe_sympify(payload(guarded))
    assert not guarded.exists()


def test_allowed_attributes_and_names_pass() -> None:
    """허용 속성(`.doit`·`.subs`)·허용 함수는 통과 — 거부 목록이 과잉이 아님을 확인."""
    assert safe_sympify("Derivative(x**2, x).doit().subs(x, 3)") == 6
    assert safe_sympify("Max(2, 3) + Min(1, 4)") == 4
    assert safe_sympify("root(8, 3)") == 2


def test_non_text_values() -> None:
    """문자열이 아닌 값 — SymPy 값·수는 그대로 감싸고, 문자열을 품은 컨테이너는 거부."""
    assert safe_sympify(3) == sympy.Integer(3)
    assert safe_sympify(_X + 1) == _X + 1
    with pytest.raises(UnsafeExpressionError, match="not_text"):
        safe_sympify(["9**9**9"])


def test_time_budget_overrun_only_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """시간 예산 초과는 관측 로그만 — 판정(결과)은 바뀌지 않는다(결정론)."""
    monkeypatch.setattr(safe_parse, "PARSE_TIME_BUDGET_S", -1.0)
    with caplog.at_level(logging.WARNING, logger="whymath.l3.safe_parse"):
        assert safe_sympify("x + 1") == _X + 1
    assert any("시간 예산 초과" in r.getMessage() for r in caplog.records)


# ──────────────────────────────────────────────────────────────────────
# ③ 계산 후 재검사
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("factorial(1000)*factorial(1000)", "integer_too_large"),
        ("root(x, 1/100)", "degree_too_high"),
    ],
)
def test_post_evaluation_recheck(text: str, code: str) -> None:
    """구조 검사는 통과하지만 계산이 값을 키우는 입력 — 계산 후 재검사가 거부한다.

    구조 검사 통과를 먼저 확인한다: 그래야 이 거부가 *재검사*에서 나온 것임이 증명된다
    (구조 검사에서 걸렸다면 재검사를 지워도 이 테스트가 초록이다).
    """
    transformations = standard_transformations + (convert_xor,)
    tree = safe_parse._structural_parse(text, transformations=transformations, local_dict=None)
    safe_parse._check_tree(tree)  # 구조 검사 통과
    with pytest.raises(UnsafeExpressionError) as info:
        safe_sympify(text)
    assert info.value.code == code


def test_book_example_power_of_power_is_rejected() -> None:
    """R22-03 해설의 예 — `(x^99)^99`는 계산하면 `x^9801`(구조·재검사 어느 쪽에서든 거부)."""
    with pytest.raises(UnsafeExpressionError):
        safe_sympify("(x^99)^99")
    with pytest.raises(UnsafeExpressionError, match="degree_too_high"):
        ensure_within_budget(_X**9801)


def test_substitution_is_checked_before_it_computes() -> None:
    """대입 폭발 — `2^x`에 `x = 10^100`은 계산 없는 대입 미리보기에서 거부(재현표 항목)."""
    started = time.perf_counter()
    with pytest.raises(UnsafeExpressionError, match="exponent_too_large"):
        safe_subs(2**_X, {_X: sympy.Integer(10) ** 100})
    assert time.perf_counter() - started < _BUDGET_S
    assert safe_subs(2**_X, {_X: sympy.Integer(10)}) == 1024
    with pytest.raises(UnsafeExpressionError, match="factorial_too_large"):
        safe_subs(sympy.factorial(_X), {_X: sympy.Integer(10) ** 9})


# ──────────────────────────────────────────────────────────────────────
# LaTeX 진입점 — antlr 미설치 환경에서도 결선을 검증(가짜 파서 주입)
# ──────────────────────────────────────────────────────────────────────


def test_latex_tower_is_rejected_before_the_parser_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """`9^{9^{9}}`는 평문 구조 검사에서 거부 — LaTeX 파서는 불리지도 않는다."""
    calls: list[str] = []
    import sympy.parsing.latex as latex_module

    monkeypatch.setattr(latex_module, "parse_latex", lambda s: calls.append(s) or _X)
    with pytest.raises(UnsafeExpressionError, match="power_too_large"):
        safe_parse_latex(r"9^{9^{9}}", plain=latex_to_plain)
    assert calls == []
    assert safe_parse_latex(r"\frac{1}{2} x", plain=latex_to_plain) == _X
    assert calls == [r"\frac{1}{2} x"]


def test_latex_parser_result_is_rechecked(monkeypatch: pytest.MonkeyPatch) -> None:
    """LaTeX 파서가 돌려준 식도 재검사한다 — 파서가 키운 값은 거부."""
    import sympy.parsing.latex as latex_module

    monkeypatch.setattr(latex_module, "parse_latex", lambda s: _X**9801)
    with pytest.raises(UnsafeExpressionError, match="degree_too_high"):
        safe_parse_latex("x", plain=latex_to_plain)


# ──────────────────────────────────────────────────────────────────────
# 학생 답 경로 결선 — 재현표 경로가 전부 안전 진입점을 거쳐 빨리 끝난다
# ──────────────────────────────────────────────────────────────────────


def _problem(answer: str) -> SimpleNamespace:
    return SimpleNamespace(
        answer=answer,
        choices=None,
        question_format=None,
        answer_format=None,
        multiple_answers=None,
    )


def _student_paths() -> list[tuple[str, Callable[[str], Any]]]:
    from whymath_backend.l3.verify_answer import verify_answer
    from whymath_backend.l3.verify_answer_form import form_verdict_for
    from whymath_backend.l3.verify_final_answer import verify_final_answer
    from whymath_backend.l3.verify_step import verify_step
    from whymath_backend.l4.misconception.answer_signature import scan_attempt_answer
    from whymath_backend.l5.ocr.verify import parse_check_latex

    return [
        ("verify_answer(답)", lambda s: verify_answer("x = 3", {"x": s}).state),
        ("verify_answer(조건)", lambda s: verify_answer(f"x = {s}", {"x": "3"}).state),
        ("verify_step", lambda s: verify_step(s, "1", None).state.value),
        ("verify_final_answer", lambda s: verify_final_answer(s, _problem("3")).state.value),
        (
            "scan_attempt_answer",
            lambda s: scan_attempt_answer(question_text="(x+2)^2 = ?", student_answer=s).scan,
        ),
        ("form_verdict_for", lambda s: form_verdict_for(s, {"expected_form": "reduced_fraction"})),
        ("parse_check_latex", lambda s: parse_check_latex(s).ok),
    ]


@pytest.mark.parametrize(
    ("text", "check_value"),
    [
        ("9^9^9", True),
        ("9**9**9", True),
        (r"9^{9^{9}}", True),
        ("(10^9)!", True),
        ("(x+y+z+w+v)^60", True),
        ("x^99+x+1", True),
        # 등식은 좌변만 거부되고 우변 `0`은 여전히 읽힌다 — 최종답 검증은 기존 폴백(마지막 우변
        # 비교)으로 판정하므로 값이 아니라 *속도*만 본다(재현표에서는 20초 timeout이었다).
        ("x^99+x+1=0", False),
    ],
)
def test_student_answer_paths_end_quickly_as_unverifiable(text: str, check_value: bool) -> None:
    """재현표에서 20초 timeout이던 입력 — 전 경로가 빠르게 '판정 불가' 쪽으로 끝난다."""
    unverifiable_like = {
        "unverifiable",
        False,
        "not_run",
        "ran_no_candidate",
    }
    for name, path in _student_paths():
        started = time.perf_counter()
        outcome = path(text)
        elapsed = time.perf_counter() - started
        value = getattr(outcome, "value", outcome)
        assert elapsed < 1.0, f"{name}: {elapsed:.2f}s — 20초 timeout 부류가 다시 열렸다"
        if check_value:
            assert value in unverifiable_like, f"{name}: {value!r}"


def test_identity_status_folds_rejection_into_parse_error() -> None:
    """거부 → 동치 권위의 기존 parse_error 경로(학생 화면은 기존 parse_error 분기 문구)."""
    assert identity_status("9^9^9", "1") is IdentityVerdict.parse_error
    assert identity_status("2x+2", "2(x+1)") is IdentityVerdict.identity


# ──────────────────────────────────────────────────────────────────────
# ④ 판정 캐시 — 같은 문자열을 다시 읽지 않되, 판정·안전은 바뀌지 않는다
# ──────────────────────────────────────────────────────────────────────


def test_cache_reuses_the_same_result() -> None:
    """같은 문자열·옵션의 두 번째 호출은 캐시에서 같은 (불변) 객체를 돌려준다."""
    first = safe_sympify("x**2 - 5*x + 6")
    before = safe_parse._sympify_cached.cache_info().hits
    second = safe_sympify("x**2 - 5*x + 6")
    assert second is first
    assert safe_parse._sympify_cached.cache_info().hits == before + 1


def test_cached_rejection_still_rejects_and_logs_every_time(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """거부 판정도 기억하지만, 다시 들어오면 매번 거부 예외와 로그를 새로 낸다(침묵 금지)."""
    with caplog.at_level(logging.INFO, logger="whymath.l3.safe_parse"):
        for _ in range(2):
            with pytest.raises(UnsafeExpressionError):
                safe_sympify("9^9^9")
    rejections = [r for r in caplog.records if "safe_parse 거부" in r.getMessage()]
    assert len(rejections) == 2
    assert safe_parse._sympify_cached.cache_info().hits >= 1


def test_mutable_result_is_not_shared_through_the_cache() -> None:
    """리스트처럼 바뀔 수 있는 결과는 기억하지 않는다 — 호출부가 고쳐도 다음 호출은 새 값이다."""
    first = safe_sympify("[1, 2]")
    assert isinstance(first, list)
    first.append(3)
    assert safe_sympify("[1, 2]") == [1, 2]


def test_global_evaluate_mode_is_part_of_the_cache_key() -> None:
    """전역 평가 모드가 다르면 다른 칸이다 — 평가된 결과가 비평가 문맥으로 새지 않는다."""
    assert safe_sympify("x + x") == 2 * _X
    with sympy.evaluate(False):
        unevaluated = safe_sympify("x + x")
    assert isinstance(unevaluated, sympy.Add)
    assert unevaluated.args == (_X, _X)


def test_global_distribute_mode_is_part_of_the_cache_key() -> None:
    """`distribute(False)` 문맥도 다른 칸이다 — `2*(x+1)`이 전개된 채로 새지 않는다."""
    from sympy.core.parameters import distribute

    assert safe_sympify("2*(x + 1)") == 2 * _X + 2
    with distribute(False):
        kept = safe_sympify("2*(x + 1)")
    assert isinstance(kept, sympy.Mul)
    assert kept.args == (sympy.Integer(2), _X + 1)


def test_immutable_python_results_are_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    """파서가 파이썬 불·튜플을 돌려줘도 불변이면 기억한다(`x == y` 같은 조건식이 반복된다).

    `False`는 파이썬 단일 객체라 `is`로 가릴 수 없고, '매번 새로 계산' 표시 칸도 캐시 적중으로
    세므로 적중 수로도 가릴 수 없다 — 실제 파싱 본체가 몇 번 불렸는지로 본다.
    """
    calls: list[str] = []
    original = safe_parse._sympify_uncached

    def counting(text: str, **kwargs: Any) -> Any:
        calls.append(text)
        return original(text, **kwargs)

    monkeypatch.setattr(safe_parse, "_sympify_uncached", counting)
    for _ in range(3):
        assert safe_sympify("x == y") is False
        assert safe_sympify("1, 2") == (1, 2)
    assert calls == ["x == y", "1, 2"]


def test_tuple_holding_a_mutable_value_is_not_shared() -> None:
    """튜플이어도 안에 바뀔 수 있는 값이 있으면 기억하지 않는다 — 원소를 고쳐도 새 값이 나온다."""
    first = safe_sympify("(1, [2])")
    assert isinstance(first, tuple)
    first[1].append(3)
    assert safe_sympify("(1, [2])") == (1, [2])


def test_parse_expr_with_local_dict_is_not_cached() -> None:
    """`local_dict`가 있는 호출은 사전 내용이 결과를 바꾸므로 기억하지 않는다."""
    one = safe_parse_expr("a + 0", transformations=_T_IMPLICIT, local_dict={"a": sympy.Integer(1)})
    two = safe_parse_expr("a + 0", transformations=_T_IMPLICIT, local_dict={"a": sympy.Integer(2)})
    assert (one, two) == (sympy.Integer(1), sympy.Integer(2))


def test_parse_expr_without_local_dict_is_cached() -> None:
    """`local_dict` 없는 `parse_expr`는 판정을 기억한다(스위트 호출의 대부분)."""
    first = safe_parse_expr("2x + 1", transformations=_T_IMPLICIT)
    before = safe_parse._parse_expr_cached.cache_info().hits
    assert safe_parse_expr("2x + 1", transformations=_T_IMPLICIT) is first
    assert safe_parse._parse_expr_cached.cache_info().hits == before + 1
