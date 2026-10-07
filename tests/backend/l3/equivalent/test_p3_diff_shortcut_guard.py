"""P3-03 미분 은행 — '선수 계산 우회로' 판정기 회귀 테스트(hermetic·LLM 0).

판정기 `l3/equivalent/p3_diff_shortcut_guard`는 독립 감사 3회차(κ 0.854·결함 122건)의 구조 원인 —
기계 검증용 정수 근이 인수정리·판별식·대입 우회로를 연다 — 을 *생성 시점에* 막는다. 이 파일은 네 가지를
못 박는다.

① 지금 은행 전 문항이 판정기 위반 0건이다(빌드가 막고, 은행 파일에서도 다시 본다).
② **재현율** — 3회차 감사 대상 은행 원문(`round3/audited_bank.jsonl`, 커밋 880589af 시점 as-found)에서
   결함 문항 122건 전부를 *그 결함 부류에 대응하는 규칙군*(bad_tag→T·bad_explanation→E·bad_wording→W)이
   잡는다. 규칙 하나를 지우면(뮤테이션) 이 단언이 깨진다.
③ **과잉 거부** — 두 판정자가 모두 ok로 본 382건 중 판정기가 거부하는 것은 고정된 11건뿐이며 전부 해설
   규칙(E)이다(우회로 규칙 T는 ok 문항을 하나도 거부하지 않는다). 집합이 바뀌면 RED — 조용히 늘거나
   줄지 않게 한다.
④ 규칙마다 결함 문면(RED)과 교정 문면(GREEN) 대조군이 있고, 생성기 빌드가 위반 문항에서 멈춘다.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path

import pytest

from whymath_backend.l3.equivalent import p3_diff_skeleton_base as base
from whymath_backend.l3.equivalent.p3_diff_mean_value_theorem_skeleton_generator import (
    KindedDiffItem,
)
from whymath_backend.l3.equivalent.p3_diff_shortcut_guard import (
    RULE_IDS,
    ShortcutProbe,
    probe_from_record,
    shortcut_violations,
    violations_by_rule,
)
from whymath_backend.l3.equivalent.p3_diff_skeleton_base import (
    DiffItem,
    P3DiffSlotGenerator,
    answer_format_for,
)

_ROOT = Path(__file__).resolve().parents[4]
_BANK_DIR = _ROOT / "data" / "corpus" / "problem_bank_p3_calculus1_diff_v0"
_ROUND3 = _ROOT / "docs" / "data" / "p3_calculus1_diff_audit" / "round3"
_FAMILY = {"bad_tag": "T", "bad_explanation": "E", "bad_wording": "W"}

#: 둘 다 ok인 382건 중 판정기가 거부하는 문항(id 앞 8자리) — 전부 '해설 규칙'(E)이다.
#: · 02-06 끝점·중점 6건: '이차함수에서 c는 구간의 중점'이라는 결론만 적어 도함수 식이 없다.
#: · 02-06 롤의 정리 가정 3건: f(a) = f(b)만으로 k를 구해 도함수가 한 번도 나오지 않는다(틀 삭제).
#: · 02-10 등속 운동의 가속도 2건: 'v(t) = 2이므로 가속도는 0' — a(t) 식이 없다.
#: 판정자들은 이 11건을 ok로 봤다. 판정기가 더 엄격한 것은 과업 규칙('해설에 도함수 식과 세운 식')을
#: 그대로 집행하기 때문이며, 재설계 은행에서는 해설에 그 단계를 넣어 해소했다.
_KNOWN_OK_REJECTED: frozenset[str] = frozenset(
    {
        "490def28",
        "24d7eb97",
        "db749952",
        "fff9adc1",
        "62d2b1fc",
        "1ebb69fb",
        "c2fb33ed",
        "b43aad1a",
        "bbedc40c",
        "491c88ce",
        "6dd4ea57",
    }
)


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _rules(record: dict[str, object]) -> set[str]:
    return {v.rule for v in shortcut_violations(probe_from_record(record))}


@pytest.fixture(scope="module")
def audited() -> dict[str, dict[str, object]]:
    return {str(r["problem_id"]): r for r in _jsonl(_ROUND3 / "audited_bank.jsonl")}


@pytest.fixture(scope="module")
def defects() -> list[dict[str, str]]:
    raw = json.loads((_ROUND3 / "defects.json").read_text(encoding="utf-8"))
    assert isinstance(raw, list)
    return raw


@pytest.fixture(scope="module")
def verdicts() -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    for path in sorted(_ROUND3.glob("R*/*.jsonl")):
        for row in _jsonl(path):
            out[str(row["problem_id"])].append(str(row["verdict"]))
    return out


# ── ① 지금 은행 ────────────────────────────────────────────────────────────
def test_current_bank_has_zero_shortcut_violations() -> None:
    rows = _jsonl(_BANK_DIR / "problems.jsonl")
    provenance = json.loads((_BANK_DIR / "_provenance.json").read_text(encoding="utf-8"))
    assert len(rows) == provenance["record_count"]
    assert len(rows) >= 200  # 감사 표본 판정 기준 n >= 200
    found = [(str(r["problem_id"])[:8], sorted(_rules(r))) for r in rows if _rules(r)]
    assert found == []


# ── ② 재현율 ───────────────────────────────────────────────────────────────
def test_audited_bank_fixture_is_the_round3_audit_target(
    audited: dict[str, dict[str, object]], verdicts: dict[str, list[str]]
) -> None:
    """원문 스냅샷이 3회차 라벨과 같은 504건을 덮는다(라벨 id 전부가 원문에 있다)."""
    assert len(audited) == 504
    assert set(verdicts) == set(audited)
    assert all(len(v) == 2 for v in verdicts.values())  # 문항마다 판정자 2명


def test_round3_defects_are_caught_by_the_matching_rule_family(
    audited: dict[str, dict[str, object]], defects: list[dict[str, str]]
) -> None:
    by_class: dict[str, set[str]] = defaultdict(set)
    for d in defects:
        by_class[d["defect_class"]].add(d["problem_id"])
    assert {k: len(v) for k, v in by_class.items()} == {
        "bad_tag": 87,
        "bad_explanation": 23,
        "bad_wording": 12,
    }
    missed = {
        cls: sorted(
            pid[:8]
            for pid in ids
            if not any(rule.startswith(_FAMILY[cls]) for rule in _rules(audited[pid]))
        )
        for cls, ids in by_class.items()
    }
    assert missed == {"bad_tag": [], "bad_explanation": [], "bad_wording": []}
    assert len(set().union(*by_class.values())) == 122


def test_round3_ok_over_rejection_is_the_frozen_known_set(
    audited: dict[str, dict[str, object]], verdicts: dict[str, list[str]]
) -> None:
    both_ok = [pid for pid, v in verdicts.items() if v == ["ok", "ok"]]
    assert len(both_ok) == 382
    rejected = {pid[:8]: _rules(audited[pid]) for pid in both_ok if _rules(audited[pid])}
    assert set(rejected) == _KNOWN_OK_REJECTED
    # 우회로 규칙(T)과 표기 규칙(W)은 ok 문항을 하나도 거부하지 않는다 — 과잉 거부는 해설 규칙뿐.
    assert all(rule.startswith("E-") for rules in rejected.values() for rule in rules)


def test_round3_split_items_are_all_rejected(
    audited: dict[str, dict[str, object]], verdicts: dict[str, list[str]]
) -> None:
    """판정자 한 명만 결함으로 본 25건도 전부 잡는다(불확실 판정도 놓치지 않는다)."""
    split = [pid for pid, v in verdicts.items() if sorted(v) == ["defect", "ok"]]
    assert len(split) == 25
    assert [pid[:8] for pid in split if not _rules(audited[pid])] == []


# ── ④ 규칙별 대조군 ───────────────────────────────────────────────────────
def _probe(
    q: str,
    e: str = "f'(x) = 2x이다.",
    *,
    code: str = "[12미적Ⅰ-02-03]",
    answer: str = "1",
    choices: tuple[str, ...] = (),
    conditions: tuple[str, ...] = (),
    answer_map: tuple[tuple[str, str], ...] = (),
    kind: str | None = None,
) -> ShortcutProbe:
    return ShortcutProbe(
        standard_code=code,
        question_text=q,
        answer=answer,
        explanation=e,
        choices=choices,
        conditions=conditions,
        answer_map=answer_map,
        answer_kind=kind,
    )


_C05, _C06, _C08, _C09, _C10 = (
    "[12미적Ⅰ-02-05]",
    "[12미적Ⅰ-02-06]",
    "[12미적Ⅰ-02-08]",
    "[12미적Ⅰ-02-09]",
    "[12미적Ⅰ-02-10]",
)
_DERIV_OK = "f'(x) = 3x^2 - 3 = 3(x + 1)(x - 1)이므로 f(x)는 x = -1에서 극댓값 3, x = 1에서 극솟값 -1을 갖는다."

#: (규칙, 결함 문면 표본) — 3회차 감사 원문 형태(또는 같은 결함 형태).
_RED: list[tuple[str, ShortcutProbe]] = [
    ("W-notation", _probe("f'(a) = 192인 양수 a의 값은?", choices=("4", "8", "8*sqrt(3)", "64"))),
    ("W-notation", _probe("Derivative(x**3, x)의 값을 구하시오.")),
    (
        "W-point-x",
        _probe("곡선 y = -x^2 + 4x + 4 위의 x = 1에서의 접선의 기울기를 구하시오.", code=_C05),
    ),
    ("W-trivial-ineq", _probe("접점의 x좌표가 0 (-1 < 0 < 2)일 때, 상수 k의 값을 구하시오.")),
    ("W-zero-hour", _probe("출발 후 0시간부터 3시간까지의 평균 속도와 순간 속도가 같아지는 시각")),
    ("W-extremum-josa", _probe("사차함수 f(x) = x^4 - 26x^2의 극값을 갖는 점이 x = -4일 때")),
    (
        "E-derivative",
        _probe(
            "곡선 y = -2x^2 - 12x + 3의 꼭짓점에서의 접선의 기울기를 구하시오.",
            "꼭짓점의 x좌표는 -3이고 그 점에서 도함수의 값은 0이므로 접선의 기울기는 0이다.",
            code=_C05,
        ),
    ),
    (
        "E-parameter",
        _probe(
            "함수 f(x) = x^n (n은 2 이상의 자연수)에 대하여 f'(2)의 값이 12일 때, f'(3)의 값을 "
            "구하시오.",
            "f'(2)가 12이므로 n은 3이고, 도함수 3x^2에서 x가 3일 때의 값은 27이다.",
        ),
    ),
    (
        "E-kinematics",
        _probe(
            "수직선 위를 움직이는 점 P의 시각 t에서의 위치가 x = t^3 + 3t^2 - 6t + 2일 때, t = 1에서 "
            "t = 3까지 점 P의 속도의 변화량을 구하시오.",
            "t = 3일 때의 속도 39에서 t = 1일 때의 속도 3을 빼면 36이다.",
            code=_C10,
            conditions=("Derivative(t**3, t).doit().subs(t, 1) = y",),
        ),
    ),
    (
        "E-sign",
        _probe(
            "위치가 x = 2t^3 - 9t^2 + 12t일 때, 점 P가 처음 운동 방향을 바꿀 때의 점 P의 위치를 "
            "구하시오.",
            "v(t) = 6(t - 1)(t - 2) = 0에서 처음 방향을 바꾸는 시각은 1이다.",
            code=_C10,
            conditions=("2*t**3 = y",),
        ),
    ),
    (
        "E-symbol-intro",
        _probe(
            "두 점 A, B 사이에서 직선 AB와 평행한 접선을 갖는 점의 x좌표는?",
            "f'(x) = 3x^2 - 4x - 4이다. f'(c) = 11에서 c = -5/3이다.",
            code=_C06,
        ),
    ),
    (
        "E-tautology",
        _probe("상수 q의 값을 구하시오.", "x = 1을 대입하면 q이다. q = 3에서 q = 3이다."),
    ),
    (
        "E-term",
        _probe(
            "f(2)의 값이 될 수 있는 가장 큰 값과 가장 작은 값의 합을 구하시오.",
            "두 끝값은 각각 f(x)가 기울기 0, 6인 일차함수일 때 나온다.",
            code=_C06,
        ),
    ),
    (
        "T05-quadratic-tangency",
        _probe(
            "직선 y = x가 곡선 y = x^2 + px + 4에 접할 때, 상수 p의 값을 구하시오. (단, p > 1)",
            "연립하면 x^2 + (p - 1)x + 4 = 0이고 판별식이 0이다. y' = 2x + p",
            code=_C05,
        ),
    ),
    (
        "T05-quadratic-tangency",
        _probe(
            "점 (1, -9)에서 곡선 y = x^2 - 1에 그은 두 접선 중 기울기가 더 큰 접선의 기울기를 "
            "구하시오.",
            "y' = 2x이다.",
            code=_C05,
        ),
    ),
    (
        "T-value-determines",
        _probe(
            "함수 f(x) = x^3 + ax^2 - 9x + 6이 x = 3에서 극솟값 -21을 가질 때, 상수 a의 값을 "
            "구하시오.",
            "f'(x) = 3x^2 + 2ax - 9이고 6a + 18 = 0에서 a = -3이다.",
            code=_C08,
            answer="-3",
            answer_map=(("x", "3"), ("a", "-3")),
        ),
    ),
    (
        "T-value-determines",
        _probe(
            "곡선 y = x^2 + 25x + q가 곡선 y = x^3 + 4x와 x = 3인 점에서 접할 때, 상수 q의 값을 "
            "구하시오.",
            "y' = 2x + 25이고 84 + q = 39에서 q = -45이다.",
            code=_C05,
            answer="-45",
            answer_map=(("q", "-45"),),
        ),
    ),
    (
        "T06-given-rate",
        _probe(
            "함수 f(x) = x^2 + 3x에 대하여 구간 [2, 5]에서의 평균변화율은 10이다. f'(c) = 10을 "
            "만족시키는 c의 값을 구하시오.",
            "f'(x) = 2x + 3이므로 2c + 3 = 10에서 c = 7/2이다.",
            code=_C06,
        ),
    ),
    (
        "T08-derivative-inequality",
        _probe(
            "함수 f(x) = x^3 + 6x^2 + 9x - 5에 대하여 f'(x) < 0을 만족시키는 정수 x는 하나뿐이다.",
            _DERIV_OK,
            code=_C08,
        ),
    ),
    (
        "T08-pinned-kind",
        _probe(
            "함수 f(x) = 2x^3 - 3x^2 - 1은 x = 1에서 극솟값을 갖는다. x = 1에서의 극솟값을 "
            "구하시오.",
            _DERIV_OK,
            code=_C08,
        ),
    ),
    (
        "T09-rational-root",
        _probe(
            "방정식 x^3 + 3x^2 - 4 = 0의 서로 다른 실근의 개수를 구하시오.",
            _DERIV_OK,
            code=_C09,
            answer="2",
            conditions=("x**3 + 3*x**2 - 4 = 0",),
            kind="real_root_count",
        ),
    ),
    (
        "T09-repeated-root",
        _probe(
            "모든 실수 x에 대하여 부등식 x^4 - 4x + 3 >= 0이 성립한다. 등호가 성립하는 실수 x의 "
            "값을 구하시오.",
            _DERIV_OK,
            code=_C09,
            conditions=("x**4 - 4*x + 3 = 0",),
            answer_map=(("x", "1"),),
        ),
    ),
    (
        "T09-biquadratic",
        _probe(
            "사차함수 f(x) = 3x^4 - 24x^2에 대하여 방정식 f(x) = -16의 서로 다른 실근의 개수를 "
            "구하시오.",
            _DERIV_OK,
            code=_C09,
            answer="4",
            conditions=("3*x**4 - 24*x**2 = -16",),
            kind="real_root_count",
        ),
    ),
    (
        "T09-low-degree",
        _probe(
            "방정식 x^2 - 2x - 1 = 0의 서로 다른 실근의 개수를 구하시오.",
            _DERIV_OK,
            code=_C09,
            answer="2",
            conditions=("x**2 - 2*x - 1 = 0",),
            kind="real_root_count",
        ),
    ),
    (
        "T09-pinned-minimizer",
        _probe(
            "x >= 0에서 함수 f(x) = x^3 - 3x + 3은 x = 1에서 최솟값을 갖는다. 그 최솟값을 "
            "구하시오.",
            _DERIV_OK,
            code=_C09,
            conditions=("Derivative(x**3 - 3*x + 3, x).doit() = 0", "y = x**3 - 3*x + 3"),
            answer_map=(("x", "1"), ("y", "1")),
        ),
    ),
    (
        "T09-pinned-minimizer",
        _probe(
            "모든 실수 x에 대하여 부등식 x^4 + 3 > 0이 성립함을 보이려 한다. 좌변의 최솟값을 "
            "구하시오.",
            _DERIV_OK,
            code=_C09,
            answer="3",
            conditions=("Derivative(x**4 + 3, x).doit() = 0", "y = x**4 + 3"),
            answer_map=(("x", "0"), ("y", "3")),
        ),
    ),
    (
        "T10-average-only",
        _probe(
            "위치가 x = -2t^2 + 3t + 1일 때, t = 1에서 t = 4까지 점 P의 평균속도를 구하시오.",
            "v(t) = -4t + 3이다.",
            code=_C10,
            conditions=("t = y",),
        ),
    ),
]

#: 교정 문면(재설계 은행이 내는 형태) — 어떤 규칙에도 걸리지 않는다.
_GREEN: list[ShortcutProbe] = [
    _probe("f'(a) = 192인 양수 a의 값은?", choices=("4", "8", "8sqrt(3)", "64")),
    _probe(
        "곡선 y = -2x^2 - 12x + 3의 꼭짓점에서의 접선의 기울기를 구하시오.",
        "y = -2(x + 3)^2 + 21이므로 꼭짓점의 x좌표는 -3이다. 도함수는 y' = -4x - 12이므로 "
        "x = -3에서의 미분계수는 -4(-3) - 12 = 0이다.",
        code=_C05,
    ),
    _probe(
        "함수 f(x) = x^n (n은 2 이상의 자연수)에 대하여 f'(2)의 값이 12일 때, f'(3)의 값을 "
        "구하시오.",
        "f'(x) = nx^(n - 1)이므로 방정식 n(2^(n - 1)) = 12를 풀면 n = 3이다.",
    ),
    _probe(
        "직선 y = 6x + k가 곡선 y = 2x^3 + 3x^2 - 30x - 1 위의 x좌표가 양수인 점에서 이 곡선에 "
        "접할 때, 상수 k의 값을 구하시오.",
        "f'(x) = 6x^2 + 6x - 30이고 -33 = 6(2) + k에서 k = -45이다.",
        code=_C05,
        answer="-45",
        answer_map=(("k", "-45"), ("s", "-11/2")),
    ),
    _probe(
        "곡선 y = x^2 + px + q가 곡선 y = x^3 + 4x와 x = 3인 점에서 접할 때, 상수 q의 값을 "
        "구하시오. (단, p, q는 상수이다.)",
        "y' = 2x + p이다. 6 + p = 31이므로 p = 25이고 9 + 25(3) + q = 39이므로 q = -45이다.",
        code=_C05,
        answer="-45",
        answer_map=(("q", "-45"), ("p", "25"), ("r", "5")),
    ),
    _probe(
        "함수 f(x) = x^3 + ax^2 + bx + 6이 x = 3에서 극솟값 -21을 가질 때, 상수 a의 값을 "
        "구하시오. (단, a, b는 상수이다.)",
        "f'(x) = 3x^2 + 2ax + b이다. 6a + b + 27 = 0, 9a + 3b + 54 = 0이다.",
        code=_C08,
        answer="-3",
        answer_map=(("x", "3"), ("a", "-3"), ("b", "-9")),
    ),
    _probe(
        "함수 f(x) = x^3 + 6x^2 + 9x - 5가 감소하는 x의 값의 범위에 속하는 정수는 하나뿐이다.",
        _DERIV_OK,
        code=_C08,
    ),
    _probe(
        "곡선 y = x^3 - 3x^2 - 9x와 직선 y = -18이 만나는 서로 다른 점의 개수를 구하시오.",
        _DERIV_OK,
        code=_C09,
        answer="3",
        conditions=("x**3 - 3*x**2 - 9*x = -18",),
        kind="real_root_count",
    ),
    # 극값 증인 — 학생이 볼 다항식이 없으면 대표 함수의 유리근은 우회로가 아니다.
    _probe(
        "최고차항의 계수가 양수인 삼차함수 f(x)의 극댓값이 1, 극솟값이 -1이다. 방정식 f(x) = 0의 "
        "서로 다른 실근의 개수를 구하시오.",
        "최고차항의 계수가 양수인 삼차함수의 그래프는 증가하다가 극댓값에서 감소로 바뀐다.",
        code=_C09,
        answer="3",
        conditions=("4*x**3 - 6*x**2 + 1 = 0",),
        kind="real_root_count",
    ),
    _probe(
        "x >= 0일 때 부등식 x^3 > 3x - 3이 성립함을 보이려 한다. x >= 0에서 두 변의 차 "
        "x^3 - (3x - 3)의 최솟값을 구하시오.",
        "두 변의 차를 f(x) = x^3 - 3x + 3이라 하자. f'(x) = 3x^2 - 3 = 3(x + 1)(x - 1)이다.",
        code=_C09,
        conditions=("Derivative(x**3 - 3*x + 3, x).doit() = 0", "y = x**3 - 3*x + 3", "x >= 0"),
        answer_map=(("x", "1"), ("y", "1")),
    ),
    _probe(
        "위치가 x = t^3 + 3t^2 - 6t + 2일 때, t = 1에서 t = 3까지 점 P의 속도의 변화량을 "
        "구하시오.",
        "v(t) = 3t^2 + 6t - 6이므로 t = 3일 때의 속도는 39, t = 1일 때의 속도는 3이다.",
        code=_C10,
        conditions=("Derivative(t**3, t).doit().subs(t, 1) = y",),
    ),
    _probe(
        "위치가 x = 2t^3 - 9t^2 + 12t일 때, 점 P가 처음 운동 방향을 바꿀 때의 점 P의 위치를 "
        "구하시오.",
        "v(t) = 6(t - 1)(t - 2)이므로 두 시각의 좌우에서 속도의 부호가 바뀐다.",
        code=_C10,
        conditions=("2*t**3 = y",),
    ),
    _probe(
        "두 점 A, B 사이에서 직선 AB와 평행한 접선을 갖는 점의 x좌표는?",
        "그 점의 x좌표를 c라 하자. f'(x) = 3x^2 - 4x - 4이다. f'(c) = 11에서 c = -5/3이다.",
        code=_C06,
    ),
    _probe(
        "f(2)의 값이 될 수 있는 가장 큰 값과 가장 작은 값의 합을 구하시오.",
        "두 끝값은 각각 f(x)가 상수함수일 때와 기울기가 6인 일차함수일 때 나온다.",
        code=_C06,
    ),
]


@pytest.mark.parametrize(("rule", "probe"), _RED, ids=[f"{r}-{i}" for i, (r, _) in enumerate(_RED)])
def test_rule_flags_the_audited_defect_form(rule: str, probe: ShortcutProbe) -> None:
    """결함 문면을 넣으면 그 규칙이 걸린다 — 판정기의 변별력(RED) 증명."""
    assert rule in {v.rule for v in shortcut_violations(probe)}


@pytest.mark.parametrize("probe", _GREEN, ids=[f"green-{i}" for i in range(len(_GREEN))])
def test_corrected_forms_pass_every_rule(probe: ShortcutProbe) -> None:
    assert [str(v) for v in shortcut_violations(probe)] == []


def test_every_rule_has_a_red_control() -> None:
    """규칙 id 전부가 RED 대조군을 가진다 — 대조군 없는 규칙은 지워져도 아무도 모른다."""
    assert {rule for rule, _ in _RED} == set(RULE_IDS)


def test_violations_by_rule_counts_each_probe_once() -> None:
    probe = _RED[0][1]
    counts = violations_by_rule([probe, probe])
    assert counts["W-notation"] == 2
    assert set(counts) == set(RULE_IDS)


# ── ④ 생성기 빌드가 멈춘다(fail-loud) ───────────────────────────────────────
class _BrokenEqGenerator(P3DiffSlotGenerator):
    """대표 슬롯에 정수 근 방정식(인수정리 우회로) 문항을 내는 가짜 생성기."""

    standard_code = "[12미적Ⅰ-02-09]"
    concept_src_id = "H:12미적Ⅰ02-09"
    unit_code = "P3-TEST"
    slug_prefix = "wm-p3-test"
    slot_difficulty = {
        "representative": 2.5,
        "basic": 2.5,
        "applied": 3.5,
        "misconception_trigger": 3.0,
        "diagnostic": 2.5,
        "mastery_check": 4.0,
    }

    @classmethod
    def _slot_items(cls, slot: str, claimed: set[str]) -> list[DiffItem]:
        return [
            KindedDiffItem(
                slot=slot,
                frame_id="broken-factorable-count",
                question_text="방정식 x^3 - 3x + 2 = 0의 서로 다른 실근의 개수를 구하시오.",
                answer_text="2",
                explanation=_DERIV_OK,
                conditions="x**3 - 3*x + 2 = 0",
                answer_map=(),
                problem_type_code="ptype.count-solutions",
                answer_format=answer_format_for("2"),
                answer_kind="real_root_count",
            )
        ]


@pytest.fixture
def _clean_cache() -> Iterator[None]:
    yield
    for slot in base.SLOT_IDS:
        base._ITEM_CACHE.pop((_BrokenEqGenerator, slot), None)


@pytest.mark.usefixtures("_clean_cache")
def test_generator_build_stops_on_a_shortcut_item() -> None:
    with pytest.raises(ValueError, match="우회로 판정기 위반") as caught:
        _BrokenEqGenerator.items("representative")
    assert "T09-rational-root" in str(caught.value)
