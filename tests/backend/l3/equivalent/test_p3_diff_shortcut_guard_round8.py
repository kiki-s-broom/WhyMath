"""P3-03 미분 은행 — 8회차(은행 감사 4회차 · 2026-10-08) 결함 원인의 기계 판정 규칙 회귀 테스트(hermetic·LLM 0).

은행 감사 4회차(`docs/data/p3_calculus1_diff_audit/bank_audit_r4/` — 7회차 교정 은행 504건 · LLM 판정자 2명 ·
처분 `disposition.json`)는 결함 5건을 원인 4종으로 찾았다(as-found k = 5 · S5 불합격 · 전부 확신 '불확실' · 두
판정자가 겹친 문항 0). 그 원인을 판정기 `p3_diff_shortcut_guard`의 8회차 규칙(`ROUND8_RULE_IDS`)으로 옮겼다. 이
파일은 다섯 가지를 못 박는다.

① **재현율** — 감사 동결 원문(as-found · `bank_audit_r4/audited_bank.jsonl`)에서 결함 5건 전부를 *그 원인에
   대응하는 규칙*이 잡는다(원인별 건수 동결). 규칙의 절을 지우면(뮤테이션) 이 단언이나 ④가 깨진다.
② **변별** — 그 은행은 7회차 규칙으로 빌드됐으므로 8회차 이전 규칙만으로는 504건 중 0건을 잡는다.
③ **과잉 거부** — 결함이 아닌 499건 중 8회차 규칙이 거부하는 것은 고정된 8건뿐이다(소개 없는 '직선' 6 — 같은
   해설 문장을 쓰는 02-09 틀 · 함수식을 준 f'(c) 2 — 같은 진단 틀). 판정자 2명은 표본 판정이라 같은 형태를 모두
   짚지 않았다(결함 후보로 보고한다). 집합이 바뀌면 RED(조용히 늘거나 줄지 않는다).
④ 규칙마다 결함 문면(RED — 동결 원문 또는 그 절만 담은 손 표본)과 그 결함만 고친 문면(GREEN) 대조군이 있다.
   절이 둘인 T08 규칙은 절마다 RED를 두고(기함수 대칭 · 오답 경로 — 증가·감소 방향 각각), 해설·발문 규칙은
   경계마다 GREEN 반례를 둔다(쉼표로 끊은 '…이므로 …이고, …이므로' · '이 직선' · 식으로 먼저 소개한 직선 · 발문의
   직선 · 함수식 없는 평균값 정리 결론 · 함수식이 있어도 c를 묻는 발문 · 오답 경로 범위가 다른 정수).
⑤ 매개변수 거부 조건(8회차 `COINCIDENCE_RULE_IDS`)이 생성기의 라운드로빈에서 실제로 파라미터를 건너뛴다.

동결 사본 전수(504건)를 읽는 측정(①의 원인 대장 대조·②·③)은 `corpus_authoring` 표지로 저작 잡에서 돈다(backend
잡의 시간 상한 — 6·7회차 파일과 같은 방식). 규칙은 판정기 한 곳에만 있다(생성기 빌드 `_validate_slot`이
fail-loud로, 라운드로빈이 매개변수 거부로 같은 판정을 쓴다).
"""

from __future__ import annotations

import dataclasses
import json
from collections import Counter
from pathlib import Path

import pytest

from whymath_backend.l3.equivalent.p3_diff_shortcut_guard import (
    COINCIDENCE_RULE_IDS,
    POST_QUALIFICATION_RULE_IDS,
    ROUND7_RULE_IDS,
    ROUND8_RULE_IDS,
    RULE_IDS,
    ShortcutProbe,
    parameter_coincidences,
    probe_from_record,
    shortcut_violations,
)
from whymath_backend.l3.equivalent.p3_diff_skeleton_base import (
    DiffItem,
    Frame,
    probe_of,
    round_robin_items,
)
from whymath_backend.schema.enums import AnswerFormat

_ROOT = Path(__file__).resolve().parents[4]
_AUDIT = _ROOT / "docs" / "data" / "p3_calculus1_diff_audit" / "bank_audit_r4"

_C03, _C06, _C08, _C09 = "[12미적Ⅰ-02-03]", "[12미적Ⅰ-02-06]", "[12미적Ⅰ-02-08]", "[12미적Ⅰ-02-09]"

#: 원인(처분 문자열의 앞머리) → 그 원인을 잡아야 하는 규칙군(하나 이상 걸리면 잡은 것).
_FAMILY: dict[str, frozenset[str]] = {
    "02-03 해설 문장": frozenset({"E-double-causal"}),
    "02-06 평균값 정리": frozenset({"T06-unused-function"}),
    "02-08 증감": frozenset({"T08-interval-integer-coincidence"}),
    "02-09 해설": frozenset({"E-undefined-line"}),
}

#: 원인별 결함 건수(처분 `disposition.json` — 합 5).
_CAUSE_COUNTS: dict[str, int] = {
    "02-03 해설 문장": 2,
    "02-06 평균값 정리": 1,
    "02-08 증감": 1,
    "02-09 해설": 1,
}

#: 결함 5건이 *어느 규칙에* 걸리는지.
_DEFECT_RULES: dict[str, frozenset[str]] = {
    "49d9955a": frozenset({"E-double-causal"}),  # 'f'(x) = 4x^3이므로 f'(a)의 값은 4a^3이므로'
    "e2b88365": frozenset({"E-double-causal"}),  # 같은 틀 — x^3
    "9c9bfdb5": frozenset({"T06-unused-function"}),  # 함수식을 주고 f'(c)의 값
    "01729815": frozenset({"T08-interval-integer-coincidence"}),  # -4x^3 + 3x + 5 — 기함수 + 상수
    "c4251980": frozenset({"E-undefined-line"}),  # f(x) = 0 실근 개수 해설의 '그래프가 직선과'
}

#: 결함이 아닌 499건 중 8회차 규칙이 거부하는 문항(id 앞 8자리) — 전부 결함 문항과 *같은 틀의 같은 형태*다.
_KNOWN_CLEAN_REJECTED: frozenset[str] = frozenset(
    {
        "1687620c", "519a7346", "5de7a99d", "8c506952", "c98366d5", "d17afe56", "e44f9f57",
        "e9dd587a",
    }
)  # fmt: skip

#: 위 8건의 규칙별 거부 건수.
_KNOWN_CLEAN_RULE_COUNTS: dict[str, int] = {
    "E-undefined-line": 6,
    "T06-unused-function": 2,
}


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _round8(probe: ShortcutProbe) -> set[str]:
    return {v.rule for v in shortcut_violations(probe)} & ROUND8_RULE_IDS


def _cause_key(cause: str) -> str:
    return next(key for key in _FAMILY if cause.startswith(key))


@pytest.fixture(scope="module")
def audited() -> dict[str, dict[str, object]]:
    return {str(r["problem_id"]): r for r in _jsonl(_AUDIT / "audited_bank.jsonl")}


@pytest.fixture(scope="module")
def causes() -> dict[str, str]:
    raw = json.loads((_AUDIT / "disposition.json").read_text(encoding="utf-8"))
    return {str(it["problem_id"]): _cause_key(str(it["cause"])) for it in raw["items"]}


@pytest.fixture(scope="module")
def by_prefix(audited: dict[str, dict[str, object]]) -> dict[str, dict[str, object]]:
    return {pid[:8]: r for pid, r in audited.items()}


# ── ① 재현율 ───────────────────────────────────────────────────────────────
@pytest.mark.corpus_authoring
def test_disposition_covers_the_frozen_audit_bank(
    audited: dict[str, dict[str, object]], causes: dict[str, str]
) -> None:
    assert len(audited) == 504
    assert set(causes) <= set(audited)
    assert dict(Counter(causes.values())) == _CAUSE_COUNTS
    assert sum(_CAUSE_COUNTS.values()) == 5
    assert set().union(*_FAMILY.values()) == ROUND8_RULE_IDS
    assert {pid[:8] for pid in causes} == set(_DEFECT_RULES)


@pytest.mark.corpus_authoring
def test_round8_defects_are_caught_by_the_matching_rule_family(
    audited: dict[str, dict[str, object]], causes: dict[str, str]
) -> None:
    missed = {
        cause: sorted(
            pid[:8]
            for pid, c in causes.items()
            if c == cause and not (_round8(probe_from_record(audited[pid])) & family)
        )
        for cause, family in _FAMILY.items()
    }
    assert missed == {cause: [] for cause in _FAMILY}


@pytest.mark.parametrize("pid", sorted(_DEFECT_RULES))
def test_each_defect_is_caught_by_its_rules(
    pid: str, by_prefix: dict[str, dict[str, object]]
) -> None:
    """결함 5건 각각을 기대한 규칙(만)이 잡는다."""
    assert _round8(probe_from_record(by_prefix[pid])) == _DEFECT_RULES[pid]


# ── ② 변별 ─────────────────────────────────────────────────────────────────
@pytest.mark.corpus_authoring
def test_round8_bank_passes_every_earlier_rule(audited: dict[str, dict[str, object]]) -> None:
    """감사 은행은 7회차 규칙으로 빌드됐다 — 8회차 이전 규칙은 504건 중 0건을 잡는다(새 규칙이 일했다)."""
    earlier = [
        pid[:8]
        for pid, r in audited.items()
        if {v.rule for v in shortcut_violations(probe_from_record(r))} - ROUND8_RULE_IDS
    ]
    assert earlier == []


# ── ③ 과잉 거부 ────────────────────────────────────────────────────────────
@pytest.mark.corpus_authoring
def test_round8_clean_over_rejection_is_the_frozen_known_set(
    audited: dict[str, dict[str, object]], causes: dict[str, str]
) -> None:
    clean = [pid for pid in audited if pid not in causes]
    assert len(clean) == 499
    rejected = {pid[:8]: _round8(probe_from_record(audited[pid])) for pid in clean}
    rejected = {pid: rules for pid, rules in rejected.items() if rules}
    assert set(rejected) == _KNOWN_CLEAN_REJECTED
    counts = Counter(rule for rules in rejected.values() for rule in rules)
    assert dict(counts) == _KNOWN_CLEAN_RULE_COUNTS


# ── ④ 규칙별 대조군 ────────────────────────────────────────────────────────
def _fix(record: dict[str, object], **changes: object) -> ShortcutProbe:
    """동결 원문 문항 → 그 결함만 고친 표본(나머지 필드는 원문 그대로)."""
    return dataclasses.replace(probe_from_record(record), **changes)  # type: ignore[arg-type]


def _interval_probe(question: str, answer: str) -> ShortcutProbe:
    """02-08 '…범위에 속하는 정수는 하나뿐' 손 표본(도함수 부등식 검산 조건 · 정답 맵 x)."""
    return ShortcutProbe(
        standard_code=_C08,
        question_text=question,
        answer=answer,
        explanation=f"f'(x)의 부호를 조사하면 범위에 속하는 정수는 {answer}뿐이다.",
        answer_map=(("x", answer),),
        answer_format="실수",
    )


#: (규칙, 원문 id 앞 8자리) — 동결 원문 그대로 RED. 절이 둘 이상인 규칙은 절마다 한 줄.
_RED_IDS: list[tuple[str, str]] = [
    ("E-double-causal", "49d9955a"),
    ("E-double-causal", "e2b88365"),
    ("E-undefined-line", "c4251980"),
    ("T06-unused-function", "9c9bfdb5"),
    (
        "T08-interval-integer-coincidence",
        "01729815",
    ),  # -4x^3 + 3x + 5 → 0(기함수·오답 경로 두 절 모두)
]

#: 오답 경로 절 손 표본 — 이차항이 있어 기함수 절은 걸리지 않고, 계수 누락 경로로 '미분한' 식의 부호
#: 범위에도 정수가 정답 하나뿐이다. 증가(f' > 0)와 감소('작아지는' — f' < 0) 방향을 각각 둔다(부호를 한
#: 방향으로 고정하는 뮤테이션은 감소 표본이 잡는다).
_RED_HANDMADE: list[tuple[str, ShortcutProbe]] = [
    # 기함수 절만 — -x^3 + 3x + 2: f' > 0의 정수는 0 하나, 계수 누락 -x^2 + 3 > 0의 정수는 -1, 0, 1(오답
    # 경로 절은 걸리지 않는다). 01729815(-4x^3 + 3x + 5)는 두 절에 함께 걸려 기함수 절을 따로 고정하지 못한다.
    (
        "T08-interval-integer-coincidence",
        _interval_probe(
            "함수 f(x) = -x^3 + 3x + 2가 증가하는 x의 값의 범위에 속하는 정수는 하나뿐이다. "
            "그 정수를 구하시오.",
            "0",
        ),
    ),
    (
        "T08-interval-integer-coincidence",
        # f'(x) = -24x^2 - 40x - 10 > 0 → 정수 -1 · 계수 누락 -8x^2 - 20x - 10 > 0 → 정수 -1
        _interval_probe(
            "함수 f(x) = -8x^3 - 20x^2 - 10x + 1이 증가하는 x의 값의 범위에 속하는 정수는 하나뿐이다. "
            "그 정수를 구하시오.",
            "-1",
        ),
    ),
    (
        "T08-interval-integer-coincidence",
        # f'(x) = 6x^2 - 10x + 2 < 0 → 정수 1 · 계수 누락 2x^2 - 5x + 2 < 0 → 정수 1
        _interval_probe(
            "곡선 y = 2x^3 - 5x^2 + 2x + 1에서 x의 값이 커질 때 y의 값이 작아지는 x의 값의 범위에 "
            "속하는 정수는 하나뿐이다. 그 정수를 구하시오.",
            "1",
        ),
    ),
]


@pytest.mark.parametrize(("rule", "pid"), _RED_IDS)
def test_round8_rule_flags_the_as_found_defect(
    rule: str, pid: str, by_prefix: dict[str, dict[str, object]]
) -> None:
    assert rule in _round8(probe_from_record(by_prefix[pid]))


@pytest.mark.parametrize(("rule", "probe"), _RED_HANDMADE)
def test_round8_rule_flags_the_handmade_clause_defect(rule: str, probe: ShortcutProbe) -> None:
    assert rule in _round8(probe)


def _green_cases(
    by_prefix: dict[str, dict[str, object]],
) -> list[tuple[str, ShortcutProbe]]:
    """(규칙, 그 결함만 고친 표본 또는 경계 반례) — 전부 그 규칙에 걸리지 않아야 한다."""
    power = by_prefix["49d9955a"]
    line = by_prefix["c4251980"]
    mvt = by_prefix["9c9bfdb5"]
    odd = by_prefix["01729815"]
    return [
        # E-double-causal — 생성기 교정 문면(앞 절을 '…이고,'로 끊음).
        (
            "E-double-causal",
            _fix(
                power,
                explanation=(
                    "f'(x) = 4x^3이고, f'(a)의 값은 4a^3이므로 4a^3 = 108에서 a^3 = 27이다. 이를 "
                    "만족시키는 실수 a는 3 하나뿐이고 양수이므로 a = 3이다."
                ),
            ),
        ),
        # 경계 — 쉼표로 절을 끊은 '…이므로 …이고, …이므로'는 은행에 흔한 정상 꼴이다.
        (
            "E-double-causal",
            _fix(
                power,
                explanation=(
                    "x = -3에서 극값을 가지므로 f'(-3)의 값은 0이고, f'(-3)의 값은 -18 - 6a이므로 "
                    "-18 - 6a = 0에서 a = -3이다."
                ),
            ),
        ),
        # E-undefined-line — 생성기 교정 문면(차수와 실근 개수의 관계만 말한다).
        (
            "E-undefined-line",
            _fix(
                line,
                explanation=str(line["answer_explanation"]).replace(
                    "그래프가 직선과 실제로 몇 번 만나는지를 보지 않은 것이다",
                    "사차방정식의 서로 다른 실근이 많아야 4개일 뿐 늘 4개는 아니라는 점을 놓친 것이다",
                ),
            ),
        ),
        # 경계 — 앞에서 식으로 소개한 직선을 받는다('직선 y = 0' 뒤의 '직선').
        (
            "E-undefined-line",
            _fix(
                line,
                explanation=(
                    "실근의 개수는 곡선 y = f(x)와 직선 y = 0의 교점의 개수와 같다. "
                    + str(line["answer_explanation"])
                ),
            ),
        ),
        # 경계 — 지시어로 앞의 식을 받는다('접선의 방정식은 …이고, 이 직선이 점 (0, 22)를 지나므로').
        ("E-undefined-line", probe_from_record(by_prefix["44991509"])),
        # 경계 — 발문에 직선이 있다('곡선 … 와 직선 y = -55의 교점' — 같은 해설 문장도 대상이 밝혀져 있다).
        ("E-undefined-line", probe_from_record(by_prefix["d180b0a0"])),
        # T06-unused-function — 함수식 없이 f(a)·f(b)만 주고 결론을 묻는다(남긴 진단 틀).
        (
            "T06-unused-function",
            _fix(
                mvt,
                question_text=(
                    "함수 f는 닫힌구간 [-3, 2]에서 연속이고 열린구간 (-3, 2)에서 미분가능하며 "
                    "f(-3) = -70, f(2) = -5이다. 평균값 정리에 의하여 f'(c) = k인 c가 이 "
                    "열린구간에 존재할 때, k의 값을 구하시오."
                ),
            ),
        ),
        # 경계 — 함수식 없이 같은 말로 f'(c)의 값을 묻는다(함수식 조건을 고정한다).
        (
            "T06-unused-function",
            _fix(
                mvt,
                question_text=(
                    "함수 f는 닫힌구간 [-3, 2]에서 연속이고 열린구간 (-3, 2)에서 미분가능하며 "
                    "f(-3) = -70, f(2) = -5이다. 평균값 정리를 만족시키는 c가 있을 때, f'(c)의 "
                    "값을 구하시오."
                ),
            ),
        ),
        # 경계 — 함수식이 있어도 c를 묻는다(도함수가 쓰인다).
        ("T06-unused-function", probe_from_record(by_prefix["bfc41591"])),
        # T08 기함수 절 — 이차항이 있는 같은 틀(재생성 은행의 대체 문항). 오답 경로 범위는 빈 집합이다.
        (
            "T08-interval-integer-coincidence",
            _fix(
                odd,
                question_text=(
                    "함수 f(x) = -8x^3 - 24x^2 - 18x + 3이 증가하는 x의 값의 범위에 속하는 정수는 "
                    "하나뿐이다. 그 정수를 구하시오."
                ),
                answer="-1",
                answer_map=(("x", "-1"),),
            ),
        ),
        # 경계 — 감소 방향 같은 틀: 계수 누락 4x^2 - 24x + 45 < 0의 범위가 비어 있다.
        ("T08-interval-integer-coincidence", probe_from_record(by_prefix["5524145b"])),
    ]


def test_round8_corrected_forms_pass_their_rule(by_prefix: dict[str, dict[str, object]]) -> None:
    still = [
        (i, rule)
        for i, (rule, probe) in enumerate(_green_cases(by_prefix))
        if rule in _round8(probe)
    ]
    assert still == []


def test_every_round8_rule_has_red_and_green_controls(
    by_prefix: dict[str, dict[str, object]],
) -> None:
    red = {rule for rule, _ in _RED_IDS} | {rule for rule, _ in _RED_HANDMADE}
    green = {rule for rule, _ in _green_cases(by_prefix)}
    assert red == ROUND8_RULE_IDS
    assert green == ROUND8_RULE_IDS
    # 8회차 규칙은 RULE_IDS의 꼬리 구간이고(회차 순서) 7회차와 겹치지 않는다. 자격 측정 뒤 회차 규칙 전부가
    # 투표 제외 집합이다.
    assert list(RULE_IDS[-len(ROUND8_RULE_IDS) :]) == [r for r in RULE_IDS if r in ROUND8_RULE_IDS]
    assert not ROUND7_RULE_IDS & ROUND8_RULE_IDS
    assert ROUND8_RULE_IDS <= POST_QUALIFICATION_RULE_IDS
    assert {"T08-interval-integer-coincidence"} == COINCIDENCE_RULE_IDS & ROUND8_RULE_IDS


# ── ⑤ 매개변수 거부 조건 ───────────────────────────────────────────────────
def _interval_item(poly_text: str, poly_code: str, answer: int) -> DiffItem:
    """02-08 기초 — '증가하는 x의 값의 범위에 속하는 정수는 하나뿐'(생성기 틀과 같은 발문)."""
    return DiffItem(
        slot="basic",
        frame_id="test-increasing-integer",
        question_text=(
            f"함수 f(x) = {poly_text}이 증가하는 x의 값의 범위에 속하는 정수는 하나뿐이다. "
            "그 정수를 구하시오."
        ),
        answer_text=str(answer),
        explanation=f"f'(x)의 부호를 조사하면 범위에 속하는 정수는 {answer}뿐이다.",
        conditions=f"Derivative({poly_code}, x).doit() > 0",
        answer_map=(("x", str(answer)),),
        problem_type_code="ptype.solve-inequality",
        answer_format=AnswerFormat.실수,
    )


def test_round_robin_skips_interval_integer_coincidences_only_when_asked() -> None:
    """기함수 + 상수 -4x^3 + 3x + 5(답 0)는 매개변수 거부 조건이 건너뛴다.

    대조군: standard_code 없이 부르면(거부 조건 미적용) 그 파라미터가 그대로 나온다.
    """
    odd = _interval_item("-4x^3 + 3x + 5", "-4*x**3 + 3*x + 5", 0)
    honest = _interval_item("-8x^3 - 24x^2 - 18x + 3", "-8*x**3 - 24*x**2 - 18*x + 3", -1)
    assert {v.rule for v in parameter_coincidences(probe_of(_C08, odd))} == {
        "T08-interval-integer-coincidence"
    }
    assert parameter_coincidences(probe_of(_C08, honest)) == []
    by_key = {1: odd, 2: honest}
    frames = [Frame("test-increasing-integer", ((1,), (2,)), lambda p: by_key[int(str(p[0]))])]
    assert [i.answer_text for i in round_robin_items(frames, 2, standard_code=_C08)] == ["-1"]
    assert [i.answer_text for i in round_robin_items(frames, 2)] == ["0", "-1"]


def test_interval_rule_needs_the_unique_integer_wording() -> None:
    """'정수는 하나뿐' 단서가 없는 발문(예: 범위를 직접 묻는 문항)은 이 규칙의 대상이 아니다."""
    probe = _interval_probe(
        "함수 f(x) = -4x^3 + 3x + 5가 증가하는 x의 값의 범위에서 x의 최댓값을 구하시오.", "1/2"
    )
    assert "T08-interval-integer-coincidence" not in _round8(probe)
