"""P3-03 미분 은행 — 발문·해설·선지 문면 결함 전수 회귀 테스트(hermetic·LLM 0).

독립 감사자 7명의 전수 감사(74건)가 올린 *문면* 결함 부류를 은행 504건 전체에서 0건으로 못 박는다.
부류 5종 — ①한국어 조사(받침 불일치: "계수은"·"108가"·"-6와"·"지수 9을") ②수식 표기("+ -"·"- -"·
"1x"·"0k" 계수 1·0 표기) ③발문에 정의 없이 등장하는 함수 기호(f) ④발문·해설의 f 소개 불일치.

각 부류는 **교정 전 문면을 주입하면 RED**여야 한다(보호 장치를 실패 주입 없이 믿지 않는다) — 대조군
테스트(`test_scanner_*`)가 감사가 지적한 실제 결함 문장을 스캐너에 넣어 검출됨을 확인한다.

2차 감사(2026-10 · 90건)가 올린 부류는 아래 `round2_defects`가 문항(행) 단위로 센다 — 기계 부류(프라임
뒤 조사·'(이)라' 조사·양수 괄호·별표 곱셈·지수 뒤 변수·'놓으면 …하면' 중첩·'곡선 …의 그래프'·
'곡선 y = (상수)'·음수 시각·정답 형식 불일치·중근 단서 잔재·결론만 적은 해설·오개념 함정 미설명·미선언
상수·같은 기호의 두 점·점 P와 상수 p·출발 시 이동 거리 0 아님)와 **bad_tag 처분 동결 서명**(미분 행위
없이 선수 계산만으로 풀리던 템플릿의 발문 서명 — 되살아나면 RED). 부류마다 감사 원문 결함 문장(RED)과
교정 문장(GREEN) 대조군을 둔다.

판정 함수 3종(`josa_and_notation_defects`·`undefined_function_defects`·`round2_defects`)은 2026-10-08
`l3/equivalent/p3_diff_text_scanner.py`로 승격했다(감사자 자격 측정 강등전의 기계 게이트가 같은 스캐너를
쓴다 — 하네스가 테스트 모듈을 import하지 않게). 규칙은 그대로이고, 이 파일의 대조군이 그 모듈을 RED/GREEN으로
계속 봉인한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from whymath_backend.l3.equivalent.p3_diff_text_scanner import (
    josa_and_notation_defects,
    round2_defects,
    undefined_function_defects,
)

_BANK = (
    Path(__file__).resolve().parents[4]
    / "data"
    / "corpus"
    / "problem_bank_p3_calculus1_diff_v0"
    / "problems.jsonl"
)


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
    # 2차 감사 교정 표기 — 독립 문장 머리말과 명시 정의를 인정한다.
    assert (
        undefined_function_defects("곡선 y = x^2 위의 점", "곡선의 식을 y = f(x)라 하자. f'(1)")
        == []
    )
    assert (
        undefined_function_defects("부등식 x^4 + 3 >= 4x", "f(x) = x^4 - 4x + 3이라 하자. f'(1)")
        == []
    )
    # 정의보다 먼저 쓰면 미정의다(정의 문장이 *있기만* 하면 통과하는 구멍을 막는다).
    assert undefined_function_defects(
        "부등식 x^4 + 3 >= 4x", "f'(1) = 0이다. f(x) = x^4 - 4x + 3이라 하자."
    ) == ["f:해설"]


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
    # 해설이 f를 스스로(다른 뜻으로) 정의하면 머리말을 붙이지 않는다 — 'f를 두 번, 다르게 정의' 방지.
    own = "두 변의 차를 f(x) = x^3 - 3x + 2라 하자. f'(x) = 3x^2 - 3이다."
    assert anchor_curve_function("x > 0에서 부등식 x^3 >= 3x - 2", own) == own
    # 정의보다 사용이 앞서면 정의로 치지 않는다(머리말을 붙인다).
    late = "f'(1) = 0이다. f(x) = x^3 - 3x + 2라 하자."
    assert anchor_curve_function("곡선 y = x^3 - 3x + 2", late).startswith("곡선의 식을")


# ──────────────────────────────────────────────────────────────────────────
# 2차 감사(2026-10 · 90건) 결함 부류 — 문항(행) 단위 스캐너(`round2_defects`는 라이브러리 모듈)
# ──────────────────────────────────────────────────────────────────────────


def test_bank_has_no_round2_defect_classes(rows: list[dict[str, object]]) -> None:
    """은행 504건 전체에서 2차 감사 결함 부류·bad_tag 동결 서명이 0건이다."""
    found = [(str(row["problem_id"])[:8], d) for row in rows if (d := round2_defects(row))]
    assert found == []


def _row(
    q: str = "",
    e: str = "",
    *,
    answer: str = "1",
    fmt: str = "자연수",
    code: str = "[12미적Ⅰ-02-09]",
    slot: str = "basic",
    conditions: str | list[str] = "x = 1",
    answer_map: dict[str, str] | None = None,
    kind: str | None = None,
) -> dict[str, object]:
    """스캐너 대조군용 최소 행(은행 행과 같은 키)."""
    verify: dict[str, object] = {"conditions": conditions, "answer_map": answer_map or {}}
    if kind is not None:
        verify["answer_kind"] = kind
    return {
        "problem_id": "control",
        "question_text": q,
        "answer_explanation": e,
        "answer": answer,
        "answer_format": fmt,
        "achievement_standard_codes": [code],
        "tags": [f"p3-slot:{slot}"],
        "verify": verify,
    }


_MC_DOUBLE = "x**3 - 3*x**2 + 4 = 0"  # (x + 1)(x - 2)^2
_MC_QUAD = "x**4 - x**3 - x**2 - x - 2 = 0"  # (x - 2)(x + 1)(x^2 + 1)

#: 감사 원문(또는 같은 결함 형태)의 문항 → 검출돼야 할 부류(RED 대조군).
_R2_DEFECTIVE = [
    (_row(e="곡선의 식을 y = f(x)로 놓으면 f'는 6x이다."), "prime_josa"),
    (_row(q="g(x) = f(x) + 3라 할 때, g'(1)의 값을 구하시오."), "ira_josa"),
    (_row(e="f(x) = 2x^3 + 9x^2라 하자. f'(x) = 6x^2 + 18x이다."), "ira_josa"),
    (_row(e="평균변화율은 (f(5) - f(2))/(5 - (2)) = 3이다."), "paren_nonneg"),
    (_row(q="f(x) = 3*x^2 + 1일 때 f'(1)의 값을 구하시오."), "star_in_text"),
    (_row(e="인수분해하면 2(x + 3)^2x = 0이다."), "exp_then_var"),
    (_row(e="y = f(x)로 놓으면 두 접선이 평행하면 기울기가 같다."), "double_myeon"),
    (_row(q="곡선 y = x^6의 도함수 f'(x)를 구하시오."), "curve_derivative"),
    (
        _row(q="곡선 y = x^3 + 2x^2 - x의 그래프와 직선 y = 2의 교점의 개수로 옳은 것은?"),
        "curve_graph_dup",
    ),
    (
        _row(q="곡선 y = 7 위의 점 (2, 7)에서의 접선의 기울기를 구하시오."),
        "const_curve_named_curve",
    ),
    (
        _row(q="점 P의 시각 t에서의 위치가 x(t) = t^2이다. 시각 t = -1에서의 속도를 구하시오."),
        "negative_time",
    ),
    (_row(answer="0", fmt="자연수"), "format_mismatch"),
    (_row(answer="8", fmt="실수"), "format_mismatch"),
    (
        _row(
            q="삼차방정식 x^3 + 2x^2 - 3x = 0의 세 근의 곱을 구하시오. (단, 중근은 중복하여 센다.)",
            conditions="x**3 + 2*x**2 - 3*x = 0",
        ),
        "multiplicity_note_without_double_root",
    ),
    (
        _row(
            e="교점의 x좌표는 2x^3 + 10x^2 + 16x = -12의 실근이다. 서로 다른 실근은 1개이다.",
            kind="real_root_count",
        ),
        "count_explanation_conclusion_only",
    ),
    (
        _row(
            e="정리하면 실근은 2개이다.",
            slot="misconception_trigger",
            conditions=_MC_DOUBLE,
            kind="real_root_count",
            answer="2",
        ),
        "mc_trap_double_root_unexplained",
    ),
    (
        _row(
            e="인수분해하면 (x - 2)(x + 1)(x^2 + 1) = 0이다. 서로 다른 실근은 2개이다.",
            slot="misconception_trigger",
            conditions=_MC_QUAD,
            kind="real_root_count",
            answer="2",
        ),
        "mc_trap_irreducible_unexplained",
    ),
    (
        _row(q="곡선 y = x^3 + ax 위의 점 (1, 4)에서의 접선의 기울기가 5일 때, a의 값은?"),
        "undeclared_constant",
    ),
    (
        _row(
            e="f'(0)의 값은 0이다. 이 조건에서 k의 값은 -5이고, 이때 f(0)의 값은 -5이다.",
            answer_map={"k": "-5"},
        ),
        "explanation_conclusion_only",
    ),
    (_row(q="곡선 위의 두 점 P, Q의 x좌표가 각각 x = 1, x = 3이다."), "two_points_same_symbol"),
    (_row(q="점 P가 곡선 위를 움직인다. 상수 p에 대하여 f(p)를 구하시오."), "p_and_point_P"),
    (
        _row(q="자동차가 출발한 지 t시간 후의 이동 거리가 s(t) = t^2 + 3 (km)이다."),
        "car_distance_nonzero_at_start",
    ),
    (
        _row(q="삼차방정식 x^3 - 7x + 6 = 0의 세 근의 합을 구하시오."),
        "badtag:09_vieta",
    ),
    (
        _row(q="이차부등식 x^2 + 6x + 9 <= 0을 만족시키는 실수 x의 값을 구하시오."),
        "badtag:09_quadratic_only",
    ),
    (
        _row(
            q="함수 f(x) = 2x^3 - 3x^2 - 1은 x = 1에서 극솟값을 갖는다. 이때의 극솟값을 구하시오.",
            code="[12미적Ⅰ-02-08]",
        ),
        "badtag:08_pinned_kind_value",
    ),
    (
        _row(
            q="함수 f(x) = -2x^3 - 6x^2 + k가 x = 0에서 극댓값 -5를 가질 때, 상수 k의 값을 구하시오.",
            code="[12미적Ⅰ-02-08]",
        ),
        "badtag:08_pinned_kind_param",
    ),
    (
        _row(
            q="함수 f(x) = x^2 - 3x에 대하여 닫힌구간 [1, 4]에서의 평균변화율을 구하시오.",
            code="[12미적Ⅰ-02-06]",
        ),
        "badtag:06_avg_rate_only",
    ),
    (
        _row(q="물체를 던진 지 t초 후의 높이가 h(t) = 2t^3 - 16t^2 + 42t (m)이다."),
        "badtag:09_thrown_object_cubic",
    ),
]


@pytest.mark.parametrize(("row", "kind"), _R2_DEFECTIVE, ids=[k for _, k in _R2_DEFECTIVE])
def test_round2_scanner_flags_the_audited_defects(row: dict[str, object], kind: str) -> None:
    """교정 전 문면(감사 원문 형태)을 넣으면 그 부류로 검출된다 — 스캐너의 변별력(RED) 증명."""
    assert kind in round2_defects(row)


#: 교정된 문면(생성기가 지금 내는 형태) — 아무 부류에도 걸리지 않아야 한다(GREEN 대조군).
_R2_HEALTHY = [
    _row(e="곡선의 식을 y = f(x)라 하자. f'(x) = 6x이므로 f'(2)의 값은 12이다."),
    _row(q="g(x) = f(x) + 3이라 할 때, g'(1)의 값을 구하시오."),
    _row(e="f(x) = 2x^3 + 9x^2이라 하자. f'(x) = 6x^2 + 18x이다."),
    _row(e="평균변화율은 (f(5) - f(2))/(5 - 2) = 3이고 2 - (-3) = 5이다."),
    _row(e="인수분해하면 2x(x + 3)^2 = 0이다."),
    _row(q="곡선 y = x^3 + 2x^2 - x와 직선 y = 2의 교점의 개수로 옳은 것은?"),
    _row(q="직선 y = 7 위의 점 (2, 7)을 지나는 직선"),
    _row(answer="0", fmt="실수"),
    _row(answer="5/2", fmt="분수"),
    _row(answer="8", fmt="자연수"),
    _row(
        e="f'(x) = 6x^2 - 6x - 12 = 6(x + 1)(x - 2)이므로 f(x)는 x = -1에서 극댓값 7, x = 2에서 "
        "극솟값 -20을 갖는다.",
        kind="real_root_count",
    ),
    _row(
        e="좌변을 인수분해하면 (x + 1)(x - 2)^2 = 0이다. x = 2는 중근이므로 한 번만 센다.",
        slot="misconception_trigger",
        conditions=_MC_DOUBLE,
        kind="real_root_count",
        answer="2",
    ),
    _row(
        e="인수분해하면 (x + 1)(x - 2)(x^2 + 1) = 0이다. 이차식 x^2 + 1은 항상 양수이므로 실근이 없다.",
        slot="misconception_trigger",
        conditions=_MC_QUAD,
        kind="real_root_count",
        answer="2",
    ),
    _row(
        q="곡선 y = -x^3 - 2x^2 - x 위의 점 (1, -4)에서의 접선의 방정식을 y = mx + n이라 할 때, "
        "m + n의 값을 구하시오."
    ),
    _row(
        q="함수 f(x) = x^3 + ax^2 - 9x + 6이 x = 3에서 극솟값 -21을 가질 때, 상수 a의 값을 "
        "구하시오.",
        code="[12미적Ⅰ-02-08]",
    ),
    _row(
        q="함수 f(x) = 2x^3 - 3x^2 - 1은 x = 0과 x = 1에서 극값을 갖는다. 이 중 극솟값을 구하시오.",
        code="[12미적Ⅰ-02-08]",
    ),
    _row(
        e="f'(0)의 값은 0이다. 6a + 18 = 0에서 a = -3이고, 이 조건에서 a의 값은 -3이다.",
        answer_map={"a": "-3"},
    ),
    _row(
        q="수직선 위를 움직이는 점 P의 시각 t (t >= 0)에서의 위치가 x(t) = 2t^3 - 12t^2 + 18t이다."
    ),
    _row(q="모든 실수 x에 대하여 부등식 x^4 - 4x + 3 >= 0이 성립한다. 등호가 성립하는 x의 값은?"),
]


@pytest.mark.parametrize("row", _R2_HEALTHY, ids=[f"healthy-{i}" for i in range(len(_R2_HEALTHY))])
def test_round2_scanner_accepts_corrected_texts(row: dict[str, object]) -> None:
    assert round2_defects(row) == []
