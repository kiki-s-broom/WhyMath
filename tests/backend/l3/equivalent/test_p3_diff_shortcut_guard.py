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
⑤ **4회차 재현율**(2026-10-07) — 4회차 감사 대상 은행 원문(`round4/audited_bank.jsonl`, 커밋 e110735e 시점
   as-found)에서 결함 문항 합집합 88건(둘 다 27건)을 대응 규칙군이 전부 잡고, 두 판정자 모두 ok로 본 416건 중
   거부는 고정된 2건뿐이다. 4회차 규칙을 빼면 88건 중 0건을 잡는다(그 은행은 3회차 규칙으로 빌드됐다 — 새
   규칙이 실제로 일했다는 변별 증거).

회차별 측정은 그 회차까지의 규칙 집합으로 한다: 3회차 동결(②·③)은 4회차 규칙(`ROUND4_RULE_IDS`)을 빼고
보고, 4회차 규칙이 3회차 ok 문항을 몇 건 거부하는지는 따로 동결한다(같은 원문에 대한 판정 기준이 회차마다
달랐다 — 3회차 판정자는 '<='를 결함으로 보지 않았고 4회차 판정자는 봤다).

5회차(2026-10-08 · 은행 감사 S5 · `ROUND5_RULE_IDS`)·6회차(은행 감사 2회차 · `ROUND6_RULE_IDS`) 규칙의
재현율·과잉 거부·대조군·뮤테이션 대상은 `test_p3_diff_shortcut_guard_round5.py`·`…_round6.py`가 따로
동결한다. 이 파일의 3·4회차 동결은 자격 측정 뒤에 더한 회차 규칙 전부(`POST_QUALIFICATION_RULE_IDS`)를 뺀
규칙 집합으로 본다(같은 원칙 — 6회차 규칙을 더해도 3·4회차 동결이 바뀌지 않는다).
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
    POST_QUALIFICATION_RULE_IDS,
    ROUND4_RULE_IDS,
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
_ROUND4 = _ROOT / "docs" / "data" / "p3_calculus1_diff_audit" / "round4"
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


#: 4회차 — 둘 다 ok인 416건 중 판정기가 거부하는 문항(id 앞 8자리). 둘 다 02-05 '곡선 y = x^n 위의 원점에서의
#: 접선의 기울기'다(T-zero-monomial). 판정자들은 ok로 봤지만, 같은 0 불변(정답·원함수 대입·거듭제곱 미분법의
#: 오답 경로가 모두 0) 때문에 02-03의 'x = 0 대입'형을 두 판정자 모두 bad_tag로 봤으므로 같은 규칙을 건다.
_KNOWN_OK_REJECTED_R4: frozenset[str] = frozenset({"83e19c19", "bb1345b5"})

#: 3회차 ok 382건 중 *4회차 규칙만으로* 거부되는 문항 수 — 회차 사이 판정 기준 차이의 크기(숨기지 않는다).
#: 대부분 3회차·4회차 은행에 그대로 남아 4회차 판정자가 결함으로 본 형태다('<='·'sqrt('·임계점 둘 고정·
#: 복이차·직선의 접선·등속 운동 등). 늘거나 줄면 RED.
_R4_RULES_ON_R3_OK = 53


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _rules_all(record: dict[str, object]) -> set[str]:
    return {v.rule for v in shortcut_violations(probe_from_record(record))}


def _rules(record: dict[str, object]) -> set[str]:
    """4회차까지의 규칙 — 3·4회차 동결은 자격 측정 뒤 회차 규칙(`POST_QUALIFICATION_RULE_IDS` —
    5·6회차)을 빼고 본다."""
    return _rules_all(record) - POST_QUALIFICATION_RULE_IDS


def _rules_pre4(record: dict[str, object]) -> set[str]:
    """3회차까지의 규칙만 — 3회차 동결은 그 회차의 규칙 집합으로 본다."""
    return _rules(record) - ROUND4_RULE_IDS


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


@pytest.fixture(scope="module")
def audited4() -> dict[str, dict[str, object]]:
    return {str(r["problem_id"]): r for r in _jsonl(_ROUND4 / "audited_bank.jsonl")}


@pytest.fixture(scope="module")
def defects4() -> list[dict[str, str]]:
    raw = json.loads((_ROUND4 / "defects.json").read_text(encoding="utf-8"))
    assert isinstance(raw, list)
    return raw


@pytest.fixture(scope="module")
def verdicts4() -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    for path in sorted(_ROUND4.glob("R*/*.jsonl")):
        for row in _jsonl(path):
            out[str(row["problem_id"])].append(str(row["verdict"]))
    return out


# ── ① 지금 은행 ────────────────────────────────────────────────────────────
# 은행 전수(504건)를 판정기·검산기에 돌리는 측정 — 저작 잡에서 돈다(backend 잡 시간 상한 · 2026-10-09 실측 108초/커버리지)
@pytest.mark.corpus_authoring
def test_current_bank_has_zero_shortcut_violations() -> None:
    rows = _jsonl(_BANK_DIR / "problems.jsonl")
    provenance = json.loads((_BANK_DIR / "_provenance.json").read_text(encoding="utf-8"))
    assert len(rows) == provenance["record_count"]
    assert len(rows) >= 200  # 감사 표본 판정 기준 n >= 200
    # 지금 은행은 5회차 규칙까지 전부 통과해야 한다(빌드가 막는다 — 은행 파일에서도 다시 본다).
    found = [(str(r["problem_id"])[:8], sorted(_rules_all(r))) for r in rows if _rules_all(r)]
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
            if not any(rule.startswith(_FAMILY[cls]) for rule in _rules_pre4(audited[pid]))
        )
        for cls, ids in by_class.items()
    }
    assert missed == {"bad_tag": [], "bad_explanation": [], "bad_wording": []}
    assert len(set().union(*by_class.values())) == 122


@pytest.mark.corpus_authoring
def test_round3_ok_over_rejection_is_the_frozen_known_set(
    audited: dict[str, dict[str, object]], verdicts: dict[str, list[str]]
) -> None:
    both_ok = [pid for pid, v in verdicts.items() if v == ["ok", "ok"]]
    assert len(both_ok) == 382
    rejected = {pid[:8]: _rules_pre4(audited[pid]) for pid in both_ok if _rules_pre4(audited[pid])}
    assert set(rejected) == _KNOWN_OK_REJECTED
    # 우회로 규칙(T)과 표기 규칙(W)은 ok 문항을 하나도 거부하지 않는다 — 과잉 거부는 해설 규칙뿐.
    assert all(rule.startswith("E-") for rules in rejected.values() for rule in rules)
    # 4회차 규칙은 3회차 판정자가 ok로 본 문항을 따로 거부한다 — 회차 사이 기준 차이(동결 값).
    by_round4 = [pid for pid in both_ok if _rules(audited[pid]) & ROUND4_RULE_IDS]
    assert len(by_round4) == _R4_RULES_ON_R3_OK


def test_round3_split_items_are_all_rejected(
    audited: dict[str, dict[str, object]], verdicts: dict[str, list[str]]
) -> None:
    """판정자 한 명만 결함으로 본 25건도 전부 잡는다(불확실 판정도 놓치지 않는다)."""
    split = [pid for pid, v in verdicts.items() if sorted(v) == ["defect", "ok"]]
    assert len(split) == 25
    assert [pid[:8] for pid in split if not _rules_pre4(audited[pid])] == []


# ── ⑤ 4회차 재현율·과잉 거부 ──────────────────────────────────────────────────
def test_audited_bank_fixture_is_the_round4_audit_target(
    audited4: dict[str, dict[str, object]], verdicts4: dict[str, list[str]]
) -> None:
    """원문 스냅샷이 4회차 라벨과 같은 504건을 덮는다(문항마다 판정자 2명)."""
    assert len(audited4) == 504
    assert set(verdicts4) == set(audited4)
    assert all(len(v) == 2 for v in verdicts4.values())


def test_round4_defects_are_caught_by_the_matching_rule_family(
    audited4: dict[str, dict[str, object]],
    defects4: list[dict[str, str]],
    verdicts4: dict[str, list[str]],
) -> None:
    by_class: dict[str, set[str]] = defaultdict(set)
    for d in defects4:
        by_class[d["defect_class"]].add(d["problem_id"])
    assert {k: len(v) for k, v in by_class.items()} == {
        "bad_wording": 39,
        "bad_explanation": 3,
        "bad_tag": 46,
    }
    union = {pid for pid, v in verdicts4.items() if "defect" in v}
    both = {pid for pid, v in verdicts4.items() if v == ["defect", "defect"]}
    assert set().union(*by_class.values()) == union and len(union) == 88 and len(both) == 27
    missed = {
        cls: sorted(
            pid[:8]
            for pid in ids
            if not any(rule.startswith(_FAMILY[cls]) for rule in _rules(audited4[pid]))
        )
        for cls, ids in by_class.items()
    }
    assert missed == {"bad_wording": [], "bad_explanation": [], "bad_tag": []}


def test_round4_defects_need_the_round4_rules(
    audited4: dict[str, dict[str, object]], verdicts4: dict[str, list[str]]
) -> None:
    """변별 — 4회차 은행은 3회차 규칙으로 빌드됐으므로 3회차 규칙만으로는 결함 88건 중 0건을 잡는다.

    4회차 규칙이 재현율 88/88을 *실제로* 만든다는 증거다(규칙을 지우면 이 은행의 결함은 다시 통과한다).
    """
    union = [pid for pid, v in verdicts4.items() if "defect" in v]
    assert [pid[:8] for pid in union if _rules_pre4(audited4[pid])] == []
    assert all(_rules(audited4[pid]) & ROUND4_RULE_IDS for pid in union)


@pytest.mark.corpus_authoring
def test_round4_ok_over_rejection_is_the_frozen_known_set(
    audited4: dict[str, dict[str, object]], verdicts4: dict[str, list[str]]
) -> None:
    both_ok = [pid for pid, v in verdicts4.items() if v == ["ok", "ok"]]
    assert len(both_ok) == 416
    rejected = {pid[:8]: _rules(audited4[pid]) for pid in both_ok if _rules(audited4[pid])}
    assert set(rejected) == _KNOWN_OK_REJECTED_R4
    assert all(rules == {"T-zero-monomial"} for rules in rejected.values()), rejected


def test_round4_split_items_are_all_rejected(
    audited4: dict[str, dict[str, object]], verdicts4: dict[str, list[str]]
) -> None:
    """판정자 한 명만 결함으로 본 61건도 전부 잡는다(4회차는 일치도 κ 0.412 — 분할이 많았다)."""
    split = [pid for pid, v in verdicts4.items() if sorted(v) == ["defect", "ok"]]
    assert len(split) == 61
    assert [pid[:8] for pid in split if not _rules(audited4[pid])] == []


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
    # 학생 표기로 쓴 부등호도 자명 부등식·도함수 부등식으로 읽는다(표기 교정이 규칙을 끄지 않게).
    ("W-trivial-ineq", _probe("접점의 x좌표가 0 (0 ≤ 1 < 3)일 때, 상수 k의 값을 구하시오.")),
    (
        "T08-derivative-inequality",
        _probe(
            "함수 f(x) = x^3 - 3x에 대하여 f'(x) ≤ 0을 만족시키는 정수 x의 개수",
            _DERIV_OK,
            code=_C08,
        ),
    ),
    (
        "T08-derivative-inequality",
        _probe(
            "함수 f(x) = x^3 - 3x에 대하여 f'(x) ≥ 0을 만족시키는 x의 범위", _DERIV_OK, code=_C08
        ),
    ),
    # ── 4회차 규칙(4회차 감사 원문 형태) ─────────────────────────────────────────
    (
        "W-ascii-inequality",
        _probe(
            "함수 f(x)는 모든 실수 x에서 미분가능하고 f'(x) <= 4이다. f(2) = 6일 때, f(4)의 값이 될 "
            "수 있는 가장 큰 값을 구하시오.",
            code=_C06,
        ),
    ),
    ("W-ascii-inequality", _probe("상수 k의 값을 구하시오.", "f(x)는 x >= 1에서 증가한다.")),
    ("W-sqrt-call", _probe("f'(a) = 192인 양수 a의 값은?", choices=("4", "8", "8sqrt(3)", "64"))),
    # 정답 필드만 코드 표기인 경우(선지·발문·해설은 깨끗) — 정답도 학생 대면 문면이다.
    ("W-sqrt-call", _probe("f'(a) = 12인 양수 a의 값을 구하시오.", answer="2sqrt(3)")),
    (
        "E-object-intro",
        _probe(
            "함수 f(x) = x^3 + kx^2에 대하여 닫힌구간 [-1, 3]에서 평균값 정리를 만족시키는 c의 값이 "
            "1/3일 때, 상수 k의 값을 구하시오.",
            "f'(x) = 3x^2 + 2kx이다. 두 점을 잇는 직선의 기울기는 7 + 2k이다. k = -5이다.",
            code=_C06,
        ),
    ),
    (
        "E-object-intro",
        _probe(
            "닫힌구간 [0, 2]에서 평균값 정리를 만족시키는 c의 값을 구하시오.",
            "f'(x) = 2x이다. 접점 x = c에서 f'(c) = 2이다.",
            code=_C06,
        ),
    ),
    (
        "E-object-intro",
        _probe(
            "닫힌구간 [0, 2]에서 평균값 정리를 만족시키는 c의 값을 구하시오.",
            "f'(x) = 2x이다. 접선의 기울기 f'(c)가 2이다.",
            code=_C06,
        ),
    ),
    # T-zero-monomial — x = 0을 가리키는 표현마다(대입·f'(0)·원점·x = 0·x좌표 0) 하나씩, 그리고 f'(x) = 0의 근.
    ("T-zero-monomial", _probe("함수 f(x) = x^6의 도함수 f'(x)에 0을 대입한 값을 구하시오.")),
    ("T-zero-monomial", _probe("함수 f(x) = x^4에 대하여 f'(0)의 값을 구하시오.")),
    (
        "T-zero-monomial",
        _probe("곡선 y = x^5 위의 원점에서의 접선의 기울기를 구하시오.", code=_C05),
    ),
    ("T-zero-monomial", _probe("곡선 y = 2x^3의 접선 중 x = 0에서의 접선의 기울기를 구하시오.")),
    (
        "T-zero-monomial",
        _probe("곡선 y = 2x^4 위의 x좌표가 0인 점에서의 접선의 기울기를 구하시오."),
    ),
    ("T-zero-monomial", _probe("함수 f(x) = x^3에 대하여 방정식 f'(x) = 0의 실근을 구하시오.")),
    ("T-zero-monomial", _probe("함수 f(x) = x^4에 대하여 방정식 f'(x) = 0의 근을 구하시오.")),
    ("T-zero-monomial", _probe("함수 f(x) = 3x^2에 대하여 방정식 f'(x) = 0의 해를 구하시오.")),
    # 계수가 문자여도 단항식이면 0에서의 미분계수는 0이다(kx^2 — 계수와 무관하게 변별이 없다).
    (
        "T-zero-monomial",
        _probe("함수 f(x) = kx^2에 대하여 f'(0)의 값을 구하시오.", "f'(x) = 2kx이다."),
    ),
    # T05-vertex-tangent — 수평 접선 표현마다 하나씩(꼭짓점·x축에 평행·기울기 0·수평).
    (
        "T05-vertex-tangent",
        _probe("곡선 y = -x^2 + 2x + 3의 꼭짓점에서의 접선의 기울기를 구하시오.", code=_C05),
    ),
    (
        "T05-vertex-tangent",
        _probe(
            "곡선 y = 3x^2 + 12x 위의 점 중 접선이 x축에 평행한 점의 x좌표를 구하시오.", code=_C05
        ),
    ),
    (
        "T05-vertex-tangent",
        _probe(
            "곡선 y = -x^2 + 2x + 3 위의 x좌표가 a인 점에서의 접선의 기울기가 0일 때, 양수 a의 값을 "
            "구하시오.",
            code=_C05,
        ),
    ),
    (
        "T05-vertex-tangent",
        _probe("곡선 y = x^2 - 4x 위의 점 중 접선이 수평인 점의 x좌표", code=_C05),
    ),
    (
        "T05-vertex-tangent",
        _probe("곡선 y = 2x^2 + 8x + 1 위의 점 중 접선의 기울기가 0인 점의 x좌표", code=_C05),
    ),
    (
        "T05-line-tangent",
        _probe("직선 y = 2x - 5 위의 점 (2, -1)에서의 접선의 기울기를 구하시오.", code=_C05),
    ),
    (
        "T05-line-tangent",
        _probe("직선 y = 7 위의 점 (-1, 7)에서의 접선의 기울기를 구하시오.", code=_C05),
    ),
    (
        "T08-given-critical-points",
        _probe(
            "함수 f(x) = 2x^3 - 3x^2 - 1은 x = 0과 x = 1에서 극값을 갖는다. 이 중 극솟값을 구하시오.",
            _DERIV_OK,
            code=_C08,
        ),
    ),
    # 미지 상수 k는 도함수에서 사라진다 — 임계점 판정은 k와 무관하게 선다.
    (
        "T08-given-critical-points",
        _probe(
            "함수 f(x) = x^3 - 3x^2 - 9x + k는 x = -1과 x = 3에서 극값을 갖는다. 극댓값이 7일 때, "
            "상수 k의 값을 구하시오.",
            _DERIV_OK,
            code=_C08,
        ),
    ),
    (
        "T08-biquadratic",
        _probe(
            "사차함수 f(x) = x^4 - 8x^2 - 2가 극소가 되는 x좌표 중 큰 값을 구하시오.",
            _DERIV_OK,
            code=_C08,
        ),
    ),
    # x = 1에 대해 대칭인 사차식((x - 1)^4 - 2(x - 1)^2 - 0)을 전개한 꼴 — 평행이동한 복이차식.
    (
        "T08-biquadratic",
        _probe(
            "사차함수 f(x) = x^4 - 4x^3 + 4x^2 - 1이 극소가 되는 x좌표 중 큰 값을 구하시오.",
            _DERIV_OK,
            code=_C08,
        ),
    ),
    (
        "T09-no-application",
        _probe(
            "사차함수 f(x) = 3x^4 + 96x + 147의 최솟값을 구하시오.",
            _DERIV_OK,
            code=_C09,
            answer="3",
            conditions=("Derivative(3*x**4 + 96*x + 147, x).doit() = 0", "y = 3*x**4 + 96*x + 147"),
            answer_map=(("x", "-2"), ("y", "3")),
        ),
    ),
    (
        "T10-linear-position",
        _probe(
            "수직선 위의 점 P의 시각 t에서의 위치가 x = 7로 일정할 때, t = 1에서의 점 P의 속도를 "
            "구하시오.",
            "v(t) = 0이다.",
            code=_C10,
        ),
    ),
    (
        "T10-linear-position",
        _probe(
            "수직선 위를 움직이는 점 P의 시각 t에서의 위치가 x = -3t + 2일 때, t = 2에서의 점 P의 "
            "속도를 구하시오.",
            "v(t) = -3이다.",
            code=_C10,
        ),
    ),
    (
        "T10-linear-position",
        _probe(
            "수직선 위를 움직이는 점 P의 시각 t에서의 위치가 x = 5t - 1일 때, t = 3에서의 점 P의 "
            "속력을 구하시오.",
            "v(t) = 5이다.",
            code=_C10,
        ),
    ),
    (
        "T10-linear-position",
        _probe(
            "수직선 위를 움직이는 점 P의 시각 t에서의 위치가 x(t) = 2t + 1일 때, t = 2에서의 점 P의 "
            "가속도를 구하시오.",
            "v(t) = 2이고 a(t) = 0이다.",
            code=_C10,
        ),
    ),
]

#: 교정 문면(재설계 은행이 내는 형태) — 어떤 규칙에도 걸리지 않는다.
_GREEN: list[ShortcutProbe] = [
    # 4회차 표기 교정 — 근호는 '8√3'(3회차 교정의 '8sqrt(3)'은 4회차에서 코드 표기로 판정됐다).
    _probe("f'(a) = 192인 양수 a의 값은?", choices=("4", "8", "8√3", "64")),
    # 해설 규칙(E-derivative) 교정형 — 4회차에 꼭짓점 문면 자체가 우회로(T05-vertex-tangent)로 판정돼
    # 같은 곡선의 꼭짓점이 아닌 점으로 바꿨다(해설에 도함수 식과 대입 과정을 보이는 형태는 그대로).
    _probe(
        "곡선 y = -2x^2 - 12x + 3 위의 x좌표가 1인 점에서의 접선의 기울기를 구하시오.",
        "도함수는 y' = -4x - 12이므로 x = 1에서의 미분계수는 -4(1) - 12 = -16이다.",
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
        "x ≥ 0일 때 부등식 x^3 > 3x - 3이 성립함을 보이려 한다. x ≥ 0에서 두 변의 차 "
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
    # ── 4회차 규칙의 경계 대조군(각 규칙의 *면제 절*이 없으면 걸리는 문면) ─────────────────
    _probe(
        "함수 f(x)는 모든 실수 x에서 미분가능하고 f'(x) ≤ 4이다. f(2) = 6일 때, f(4)의 값이 될 수 "
        "있는 가장 큰 값을 구하시오.",
        "평균값 정리에 의해 f(4) - f(2) = 2f'(c)인 c가 있고 f'(c) ≤ 4이므로 f(4) ≤ 14이다.",
        code=_C06,
    ),
    # E-object-intro — 해설의 대상을 발문이 소개한 경우(점·접·곡선·직선·그래프 표현마다 하나).
    _probe(
        "곡선 y = f(x) 위의 두 점 A, B를 잇는 직선에 평행한 접선",
        "두 점을 잇는 직선의 기울기",
        code=_C06,
    ),
    _probe("점 A의 x좌표 c를 구하시오.", "f'(x) = 2x이다. 접점의 x좌표는 c이다.", code=_C06),
    _probe("x축에 접하는 c의 값을 구하시오.", "f'(x) = 2x이다. 접점의 x좌표는 c이다.", code=_C06),
    _probe(
        "곡선 y = x^2에 대하여 c의 값을 구하시오.",
        "f'(x) = 2x이다. 접선의 기울기는 2c이다.",
        code=_C06,
    ),
    _probe(
        "직선 y = 3x와 평행한 c의 값을 구하시오.",
        "f'(x) = 2x이다. 접선의 기울기는 3이다.",
        code=_C06,
    ),
    _probe(
        "함수의 그래프에서 c의 값을 구하시오.", "f'(x) = 2x이다. 접선의 기울기는 2c이다.", code=_C06
    ),
    # 지운 해설 표현을 평균변화율·f'(c)로 바꾼 교정형(발문에 점이 없다).
    _probe(
        "함수 f(x) = x^3 + kx^2에 대하여 닫힌구간 [-1, 3]에서 평균값 정리를 만족시키는 c의 값이 "
        "1/3일 때, 상수 k의 값을 구하시오.",
        "f'(x) = 3x^2 + 2kx이다. 구간 [-1, 3]에서의 평균변화율은 7 + 2k이다. 평균값 정리에 따라 "
        "f'(c)가 이 평균변화율과 같고 c의 값이 1/3이므로 3(1/3)^2 + 2(1/3)k = 7 + 2k이다. "
        "따라서 k = -5이다.",
        code=_C06,
    ),
    # T-zero-monomial — 단항식이지만 0이 아닌 점·0이지만 단항식이 아닌 함수·일차 단항식.
    _probe("곡선 y = x^5 위의 점 (-1, -1)에서의 접선의 y절편을 구하시오.", code=_C05),
    _probe("함수 f(x) = x^3 + 2x에 대하여 f'(0)의 값을 구하시오."),
    _probe("함수 f(x) = 3x에 대하여 f'(0)의 값을 구하시오.", "f'(x) = 3이다."),
    _probe("함수 f(x) = x^3의 도함수 f'(x)에 10을 대입한 값을 구하시오.", "f'(x) = 3x^2이다."),
    # T05-line-tangent — '직선 y = … 위의'가 있어도 접선을 묻지 않으면 걸지 않는다.
    _probe("직선 y = 2x + 1 위의 점 (1, 3)의 y좌표와 x좌표의 차를 구하시오.", code=_C05),
    # T05-vertex-tangent — 삼차 곡선의 수평 접선은 꼭짓점 공식으로 풀리지 않는다.
    _probe(
        "곡선 y = -x^3 + 12x + 2 위의 점 중 접선이 x축에 평행하고 x좌표가 양수인 점의 x좌표를 "
        "구하시오.",
        "도함수는 y' = -3x^2 + 12 = -3(x + 2)(x - 2)이다.",
        code=_C05,
    ),
    # T08-given-critical-points — 임계점 하나 고정 + 미지 계수(재설계형), 평평한 임계점이 섞인 고정.
    _probe(
        "함수 f(x) = x^3 + ax^2 - 9x + 2가 x = -1에서 극값을 가질 때, f(x)의 극솟값을 구하시오. "
        "(단, a는 상수이다.)",
        "f'(x) = 3x^2 + 2ax - 9이다. f'(-1)의 값은 -6 - 2a이므로 a = -3이다.",
        code=_C08,
        answer="-25",
        answer_map=(("x", "3"), ("a", "-3"), ("y", "-25")),
    ),
    _probe(
        "사차함수 f(x) = x^4 - 4x^3 + 1에 대하여 방정식 f'(x) = 0의 실근은 x = 0과 x = 3이다. "
        "f(x)의 극값을 구하시오.",
        "f'(x) = 4x^3 - 12x^2 = 4x^2(x - 3)이다.",
        code=_C08,
    ),
    # 'x = 수'가 문자 뒤에 붙은 곳('3ax = 1')은 x 위치 고정이 아니다(T08 고정 읽기의 경계).
    _probe(
        "함수 f(x) = x^3 - 3x에 대하여 3ax = 1과 3ax = -1을 만족시키는 a의 값을 구하시오.",
        _DERIV_OK,
        code=_C08,
    ),
    # f'의 근이 실수가 아니면(3x^2 + 6) 극값 위치가 없다 — 판정기가 허근을 극값으로 세지 않는다.
    _probe(
        "함수 f(x) = x^3 + 6x에 대하여 x = 1과 x = 2에서의 함숫값의 차를 구하시오.",
        "f'(x) = 3x^2 + 6이다.",
        code=_C08,
    ),
    # T08-biquadratic — 비대칭 사차식·미지 계수가 든 사차식(대칭 판정 불가 — 건너뛴다).
    _probe(
        "사차함수 f(x) = x^4 - 14x^2 + 24x - 2가 극소가 되는 x좌표 중 큰 값을 구하시오.",
        _DERIV_OK,
        code=_C08,
    ),
    _probe(
        "사차함수 f(x) = x^4 + ax^3 + b가 x = 3에서 극솟값 -29를 가질 때, 상수 b의 값을 구하시오. "
        "(단, a, b는 상수이다.)",
        "f'(x) = 4x^3 + 3ax^2이다. 108 + 27a = 0이고 81 + 27a + b = -29이다.",
        code=_C08,
        answer="-2",
        answer_map=(("x", "3"), ("b", "-2"), ("a", "-4")),
    ),
    # T09-no-application — 같은 최솟값을 그래프와 x축의 위치 관계로 묻는 교정형.
    _probe(
        "사차함수 y = 3x^4 + 96x + 147의 그래프가 x축과 만나지 않음을 보이려 한다. 이 함수의 "
        "최솟값을 구하시오.",
        "f(x) = 3x^4 + 96x + 147이라 하자. f'(x) = 12x^3 + 96이다.",
        code=_C09,
        answer="3",
        conditions=("Derivative(3*x**4 + 96*x + 147, x).doit() = 0", "y = 3*x**4 + 96*x + 147"),
        answer_map=(("x", "-2"), ("y", "3")),
    ),
    # T10-linear-position — 이차 위치의 가속도(차수 절), 일차 위치지만 속도를 묻지 않는 문면(속도 절).
    _probe(
        "수직선 위를 움직이는 점 P의 시각 t에서의 위치가 x = t^2 - 4t + 3일 때, t = 2에서의 점 P의 "
        "가속도를 구하시오.",
        "v(t) = 2t - 4이고 a(t) = 2이다.",
        code=_C10,
    ),
    _probe(
        "수직선 위를 움직이는 점 P의 시각 t에서의 위치가 x = 2t + 1일 때, t = 3에서의 점 P의 위치를 "
        "구하시오.",
        code=_C10,
    ),
]


@pytest.mark.parametrize(("rule", "probe"), _RED, ids=[f"{r}-{i}" for i, (r, _) in enumerate(_RED)])
def test_rule_flags_the_audited_defect_form(rule: str, probe: ShortcutProbe) -> None:
    """결함 문면을 넣으면 그 규칙이 걸린다 — 판정기의 변별력(RED) 증명."""
    assert rule in {v.rule for v in shortcut_violations(probe)}


@pytest.mark.parametrize("probe", _GREEN, ids=[f"green-{i}" for i in range(len(_GREEN))])
def test_corrected_forms_pass_every_rule(probe: ShortcutProbe) -> None:
    """3·4회차 교정형은 그 회차까지의 규칙을 전부 통과한다.

    5회차 규칙은 이 목록의 두 교정형(삼차 실근 개수 = 차수 3 · 극값 증인)을 다시 결함으로 본다 — 5회차
    감사가 그 형태를 결함으로 판정했기 때문이다(`test_p3_diff_shortcut_guard_round5.py`
    `test_round4_corrected_forms_superseded_by_round5`가 그 두 건을 동결한다).
    """
    assert [
        str(v) for v in shortcut_violations(probe) if v.rule not in POST_QUALIFICATION_RULE_IDS
    ] == []


#: 02-09 '활용' 맥락 어휘 — 판정기 정규식과 *독립된* 목록(정규식에서 어휘 하나를 지우면 아래 테스트가 RED).
_APPLICATION_WORDS = (
    "방정식",
    "부등식",
    "실근",
    "만나",
    "교점",
    "위쪽",
    "아래쪽",
    "보이려",
    "성립",
    "보다 크",
    "보다 작",
    "오른쪽",
    "왼쪽",
    "시각의 개수",
    "x축",
)


@pytest.mark.parametrize("word", _APPLICATION_WORDS)
def test_each_application_word_alone_exempts_a_09_minimum_item(word: str) -> None:
    """어휘 하나만 있는 02-09 문면은 T09-no-application을 통과하고, 어휘가 없으면 걸린다."""
    with_word = _probe(f"{word} 맥락의 최솟값을 구하시오.", code=_C09)
    without = _probe("함수의 최솟값을 구하시오.", code=_C09)
    assert "T09-no-application" not in {v.rule for v in shortcut_violations(with_word)}
    assert "T09-no-application" in {v.rule for v in shortcut_violations(without)}


def test_every_rule_has_a_red_control() -> None:
    """규칙 id 전부가 RED 대조군을 가진다 — 대조군 없는 규칙은 지워져도 아무도 모른다.

    5·6회차 규칙의 RED 대조군은 `test_p3_diff_shortcut_guard_round5.py`·`…_round6.py`에 있다(각 파일이
    그 회차 전부를 덮는지 단언한다). 이 파일은 4회차까지를 덮는다.
    """
    assert {rule for rule, _ in _RED} == set(RULE_IDS) - POST_QUALIFICATION_RULE_IDS


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
