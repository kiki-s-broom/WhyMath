"""P3-03 미분 은행 — 발문·해설·선지 문면 결함 전수 회귀 테스트(hermetic·LLM 0).

독립 감사자 7명의 전수 감사(74건)가 올린 *문면* 결함 부류를 은행 504건 전체에서 0건으로 못 박는다.
부류 5종 — ①한국어 조사(받침 불일치: "계수은"·"108가"·"-6와"·"지수 9을") ②수식 표기("+ -"·"- -"·
"1x"·"0k" 계수 1·0 표기) ③발문에 정의 없이 등장하는 함수 기호(f) ④발문·해설의 f 소개 불일치.

각 부류는 **교정 전 문면을 주입하면 RED**여야 한다(보호 장치를 실패 주입 없이 믿지 않는다) — 대조군
테스트(`test_scanner_*`)가 감사가 지적한 실제 결함 문장을 스캐너에 넣어 검출됨을 확인한다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from whymath_backend.lang.josa import has_batchim_hangul, has_batchim_text

_BANK = (
    Path(__file__).resolve().parents[4]
    / "data"
    / "corpus"
    / "problem_bank_p3_calculus1_diff_v0"
    / "problems.jsonl"
)

# 조사 → 받침 필요 여부(True=받침 뒤 형태).
_PARTICLE_NEEDS_BATCHIM = {
    "은": True,
    "을": True,
    "과": True,
    "이": True,
    "는": False,
    "를": False,
    "와": False,
    "가": False,
}
_TOKEN_JOSA = re.compile(
    r"([A-Za-z0-9_'^()\-+/.|]+|[가-힣])(은|는|이|가|을|를|와|과)(?=[\s,.?)]|$)"
)
_COPULA_NEXT = re.compile(r"이(?:다|므|며|고|어|라|면|지|니)")
_NOTATION = {
    "plus_minus": re.compile(r"\+ -|\+-"),
    "minus_minus": re.compile(r"- -|--"),
    "coef_one": re.compile(r"(?<![A-Za-z0-9_.^/])-?1[a-z](?![A-Za-z0-9_(^])"),
    "coef_zero": re.compile(r"(?<![A-Za-z0-9_.^/])0[a-z](?![A-Za-z0-9_(^])"),
    "exp_one_zero": re.compile(r"\^[01](?![0-9])"),
    "plus_plus": re.compile(r"\+ \+|\+\+"),
}
_FN_USE = {n: re.compile(rf"(?<![A-Za-z0-9_']){n}\s*[(']") for n in "fgh"}


def josa_and_notation_defects(text: str) -> list[tuple[str, str]]:
    """문장 1개의 조사·표기 결함 (부류, 문맥) 목록."""
    out: list[tuple[str, str]] = []
    for m in _TOKEN_JOSA.finditer(text):
        token, particle = m.group(1), m.group(2)
        if re.fullmatch(r"[가-힣]", token):
            # 한글 낱말 뒤는 명사형 오용만 본다(받침 無 뒤 은·을·과 / 받침 有 뒤 를·와).
            # '그은'(긋다 활용)은 조사가 아니다.
            batchim = has_batchim_hangul(token)
            wrong = (particle in ("은", "을", "과") and not batchim) or (
                particle in ("를", "와") and batchim
            )
            if wrong and m.group(0) != "그은":
                out.append(("josa_hangul", text[max(0, m.start() - 6) : m.end() + 6]))
            continue
        batchim_or_none = has_batchim_text(token)
        if batchim_or_none is None:
            continue
        if particle == "이" and _COPULA_NEXT.match(text[m.start(2) :]):
            continue
        if _PARTICLE_NEEDS_BATCHIM[particle] != batchim_or_none:
            out.append(("josa_token", text[max(0, m.start() - 8) : m.end() + 8]))
    for name, rx in _NOTATION.items():
        for m in rx.finditer(text):
            out.append((name, text[max(0, m.start() - 10) : m.end() + 10]))
    return out


def _defines(question: str, name: str) -> bool:
    return (
        re.search(
            rf"(?<![A-Za-z0-9_']){name}\((?:x|t)\)|(?<![가-힣])함수 {name}(?![A-Za-z0-9_'(])",
            question,
        )
        is not None
    )


def undefined_function_defects(question: str, explanation: str) -> list[str]:
    """발문이 소개하지 않은 함수 기호가 발문(또는 해설)에 쓰이면 기호 목록."""
    bad: list[str] = []
    for name in "fgh":
        if _defines(question, name):
            continue
        if _FN_USE[name].search(question):
            bad.append(f"{name}:발문")
        elif _FN_USE[name].search(explanation) and not re.search(
            rf"y = {name}\(x\)로 놓으면", explanation
        ):
            bad.append(f"{name}:해설")
    return bad


@pytest.fixture(scope="module")
def rows() -> list[dict[str, object]]:
    return [json.loads(line) for line in _BANK.read_text(encoding="utf-8").splitlines() if line]


def _texts(row: dict[str, object]) -> list[str]:
    out = [str(row["question_text"]), str(row["answer_explanation"])]
    choices = row.get("choices")
    if isinstance(choices, list):
        out.extend(str(c) for c in choices)
    return out


def test_bank_has_no_josa_or_notation_defects(rows: list[dict[str, object]]) -> None:
    assert len(rows) == 504
    found = [
        (str(row["problem_id"])[:8], kind, ctx)
        for row in rows
        for text in _texts(row)
        for kind, ctx in josa_and_notation_defects(text)
    ]
    assert found == []


def test_bank_never_uses_an_undefined_function_symbol(rows: list[dict[str, object]]) -> None:
    found = [
        (str(row["problem_id"])[:8], bad)
        for row in rows
        if (
            bad := undefined_function_defects(
                str(row["question_text"]), str(row["answer_explanation"])
            )
        )
    ]
    assert found == []


@pytest.mark.parametrize(
    ("defective", "kind"),
    [
        ("이므로 계수은 6이다.", "josa_hangul"),
        ("이므로 지수은 2이다.", "josa_hangul"),
        ("이 값이 108가 되는 양수 a", "josa_token"),
        ("값이 0가 되는 a는", "josa_token"),
        ("지수 9을 앞으로 내리고", "josa_token"),
        ("속도 -6와 가속도 6의 합", "josa_token"),
        ("B(4, 93)를 지나는 직선", "josa_token"),
        ("도함수 2x이 0이 되는", "josa_token"),
        ("평균변화율은 9 + -3k이다.", "plus_minus"),
        ("좌변은 (x - -3)의 제곱이므로", "minus_minus"),
        ("f(x) = 2x^3 + ax^2 - 1x에 대하여", "coef_one"),
        ("평균변화율은 3 + 1k이다.", "coef_one"),
        ("평균변화율은 1 + 0k이다.", "coef_zero"),
    ],
)
def test_scanner_flags_the_audited_defects(defective: str, kind: str) -> None:
    """교정 전 문장(감사 지적)을 넣으면 해당 부류로 검출된다 — 스캐너의 변별력 증명."""
    assert kind in {k for k, _ in josa_and_notation_defects(defective)}


@pytest.mark.parametrize(
    "healthy",
    [
        "이므로 계수는 6이다.",
        "이 값이 108이 되는 양수 a",
        "지수 9를 앞으로 내리고",
        "속도 -6과 가속도 6의 합",
        "평균변화율은 9 - 3k이다.",
        "좌변은 (x + 3)의 제곱이므로",
        "점에서 곡선 y = x^2에 그은 두 접선",
    ],
)
def test_scanner_accepts_corrected_sentences(healthy: str) -> None:
    assert josa_and_notation_defects(healthy) == []


def test_undefined_function_scanner_flags_the_audited_stems() -> None:
    stem = "곡선 y = x^2 + 4x - 3 위의 점 (a, f(a))에서의 접선이 직선 y = 10x + 28에 평행할 때"
    assert undefined_function_defects(stem, "f'(a) = 10이다.") == ["f:발문"]
    fixed = "함수 f(x) = x^2 + 4x - 3에 대하여 곡선 y = f(x) 위의 점 (a, f(a))에서의 접선이"
    assert undefined_function_defects(fixed, "f'(a) = 10이다.") == []
    # 발문이 f를 안 쓰고 해설만 쓰면 해설이 곡선 식을 y = f(x)로 놓아야 한다.
    assert undefined_function_defects("곡선 y = x^2 위의 점", "f'(1)은 2이다.") == ["f:해설"]
    # '도함수 f'(x)'의 '함수 f'는 f를 소개한 것이 아니다(스캐너 구멍 — 뮤테이션 M4가 드러냄).
    assert undefined_function_defects("곡선 y = x^6의 도함수 f'(x)를 구하시오.", "") == ["f:발문"]
    assert (
        undefined_function_defects(
            "곡선 y = x^2 위의 점", "곡선의 식을 y = f(x)로 놓으면 f'(1)은 2이다."
        )
        == []
    )


# ── 헬퍼 단위 계약 ─────────────────────────────────────────────────────────
def test_expr_helpers_never_emit_broken_notation() -> None:
    from whymath_backend.l3.equivalent.p3_diff_expr import (
        anchor_curve_function,
        render_affine,
        with_eul_reul,
        with_eun_neun,
        with_i_ga,
        with_wa_gwa,
    )

    assert render_affine(9, -3, "k") == "9 - 3k"
    assert render_affine(3, 1, "k") == "3 + k"
    assert render_affine(1, 0, "k") == "1"
    assert render_affine(0, -1, "k") == "-k"
    assert with_i_ga(108) == "108이"
    assert with_i_ga(0) == "0이"
    assert with_eun_neun("계수") == "계수는"
    assert with_eul_reul(9) == "9를"
    assert with_wa_gwa(-6) == "-6과"
    assert anchor_curve_function("함수 f(x) = x에 대하여", "f'(1)") == "f'(1)"
    assert anchor_curve_function("곡선 y = x", "f'(1)").startswith("곡선의 식을 y = f(x)")
