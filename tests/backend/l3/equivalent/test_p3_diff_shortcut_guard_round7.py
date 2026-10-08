"""P3-03 미분 은행 — 7회차(은행 감사 3회차 · 2026-10-08) 결함 원인의 기계 판정 규칙 회귀 테스트(hermetic·LLM 0).

은행 감사 3회차(`docs/data/p3_calculus1_diff_audit/bank_audit_r3/` — 6회차 교정 은행 504건 · LLM 판정자 2명 ·
처분 `disposition.json`)는 결함 11건을 원인 4종으로 찾았다(as-found k = 11 · S5 불합격 · 전부 확신 '불확실'). 그
원인을 판정기 `p3_diff_shortcut_guard`의 7회차 규칙(`ROUND7_RULE_IDS`)으로 옮겼다. 이 파일은 다섯 가지를 못 박는다.

① **재현율** — 감사 동결 원문(as-found · `bank_audit_r3/audited_bank.jsonl`)에서 결함 11건 전부를 *그 원인에
   대응하는 규칙군*이 잡는다(원인별 건수 동결). 규칙의 절을 지우면(뮤테이션) 이 단언이나 ④가 깨진다.
② **변별** — 그 은행은 6회차 규칙으로 빌드됐으므로 7회차 이전 규칙만으로는 504건 중 0건을 잡는다.
③ **과잉 거부** — 결함이 아닌 493건 중 7회차 규칙이 거부하는 것은 고정된 65건뿐이다(규칙별 건수 동결). 전부
   *같은 틀의 같은 형태*다(주어 자리 소개 없는 v(t) 25 · 오답 경로 일치 23 — c만·m만 묻기 11·x = 1 평가 9·주어진
   도함수 꼴 2·kx^m의 k 2 · 결론이 묻는 대상과 어긋남 7 · 발문에 없는 x(…) 6 · 이차곡선 기울기 4 · 속도↔가속도
   같은 값 2 · 성분 임계점 1) — 판정자 2명은 표본 판정이라 같은 형태를 모두 짚지 않았다(결함 후보로 보고한다).
   집합이 바뀌면 RED(조용히 늘거나 줄지 않는다).
④ 규칙마다 결함 문면(RED — 동결 원문 또는 그 절만 담은 손 표본)과 그 결함만 고친 문면(GREEN) 대조군이 있다.
   절이 둘 이상인 규칙은 절마다 RED를 둔다(접점/기울기 · 지수 유지/계수 누락/꼴 읽기 c·m/주어진 도함수 꼴 ·
   속도→가속도/속도→위치/가속도→속도 · v/a · 증감 대상/결론의 답).
⑤ 매개변수 거부 조건(7회차 `COINCIDENCE_RULE_IDS`)이 생성기의 라운드로빈에서 실제로 파라미터를 건너뛴다.

동결 사본 전수(504건)를 읽는 측정(①의 원인 대장 대조·②·③)은 `corpus_authoring` 표지로 저작 잡에서 돈다(backend
잡의 시간 상한 — 6회차 파일과 같은 방식). 규칙은 판정기 한 곳에만 있다(생성기 빌드 `_validate_slot`이 fail-loud로,
라운드로빈이 매개변수 거부로 같은 판정을 쓴다).
"""

from __future__ import annotations

import dataclasses
import json
from collections import Counter
from pathlib import Path

import pytest
import sympy

from whymath_backend.l3.equivalent.p3_diff_shortcut_guard import (
    COINCIDENCE_RULE_IDS,
    POST_QUALIFICATION_RULE_IDS,
    ROUND5_RULE_IDS,
    ROUND6_RULE_IDS,
    ROUND7_RULE_IDS,
    RULE_IDS,
    ShortcutProbe,
    motion_symbols_not_in_subject,
    parameter_coincidences,
    power_path_derivative,
    probe_from_record,
    shortcut_violations,
)
from whymath_backend.l3.equivalent.p3_diff_skeleton_base import (
    DiffItem,
    Frame,
    probe_of,
    round_robin_items,
)
from whymath_backend.l3.equivalent.p3_diff_tangent_line_skeleton_generator import (
    P3DiffTangentLineGenerator,
)
from whymath_backend.schema.enums import AnswerFormat

_ROOT = Path(__file__).resolve().parents[4]
_AUDIT = _ROOT / "docs" / "data" / "p3_calculus1_diff_audit" / "bank_audit_r3"

_C03, _C04, _C05 = "[12미적Ⅰ-02-03]", "[12미적Ⅰ-02-04]", "[12미적Ⅰ-02-05]"
_C08, _C10 = "[12미적Ⅰ-02-08]", "[12미적Ⅰ-02-10]"
_X, _T = sympy.Symbol("x"), sympy.Symbol("t")

#: 원인(처분 문자열의 앞머리) → 그 원인을 잡아야 하는 규칙군(하나 이상 걸리면 잡은 것).
_FAMILY: dict[str, frozenset[str]] = {
    "이차곡선 접선": frozenset({"T05-quadratic-slope"}),
    "오답 경로가 정답과 일치": frozenset(
        {"T-power-path-coincidence", "T-component-critical-point"}
    ),
    "해설 문장": frozenset(
        {"E-motion-symbol-subject", "E-function-notation", "E-conclusion-target"}
    ),
    "위치가 (t-1)^3 꼴": frozenset({"T10-confusable-quantity"}),
}

#: 원인별 결함 건수(처분 `disposition.json`의 cause_counts와 같다 — 합 11).
_CAUSE_COUNTS: dict[str, int] = {
    "이차곡선 접선": 5,
    "오답 경로가 정답과 일치": 3,
    "해설 문장": 2,
    "위치가 (t-1)^3 꼴": 1,
}

#: 결함 11건이 *어느 규칙에* 걸리는지(원인 안에서도 문항마다 다른 절이 잡는다 — 절을 지우면 RED).
_DEFECT_RULES: dict[str, frozenset[str]] = {
    "4d287bbd": frozenset({"T05-quadratic-slope"}),
    "1006bee0": frozenset({"T05-quadratic-slope"}),
    "5209729b": frozenset({"T05-quadratic-slope"}),
    "ac28058d": frozenset({"T05-quadratic-slope"}),
    "ee5a4588": frozenset({"T05-quadratic-slope"}),
    "cbde3ec3": frozenset({"T-power-path-coincidence"}),  # f(x) = x^2의 f'(1) — 지수 유지
    "76a9f5ac": frozenset({"T-power-path-coincidence"}),  # x^8 → cx^m의 c — 꼴 읽기
    "0bcf3427": frozenset({"T-component-critical-point"}),  # g'(-1) = 0
    "b2d3bc4b": frozenset({"E-conclusion-target"}),  # 증감 전환점을 묻는데 극값으로 맺음
    "fb9ec6bc": frozenset({"E-motion-symbol-subject", "E-function-notation"}),  # v(t)·x(5)
    "30d80000": frozenset({"T10-confusable-quantity"}),  # 가속도 0인 시각의 속도도 0
}

#: 결함이 아닌 493건 중 7회차 규칙이 거부하는 문항(id 앞 8자리) — 전부 결함 문항과 *같은 틀의 같은 형태*다.
_KNOWN_CLEAN_REJECTED: frozenset[str] = frozenset(
    {
        "069e312e", "0d306fe5", "0f5bf5d6", "1179179f", "1523db07", "1777b112", "183da9df",
        "1bdcda49", "1d1ac24b", "20d192dc", "22230060", "251646ee", "29b74ece", "2fec7eaa",
        "320ede1f", "3294c5cf", "3301b000", "336c6447", "361295c7", "388a457c", "3903215e",
        "3f11d98a", "419b0df6", "4708ef1d", "486f8d56", "4ce1eb57", "51b1211a", "56ce1730",
        "58271f4d", "59c18dea", "5a14790d", "5dfae494", "6359d702", "64e893d9", "659e4344",
        "687f3ccf", "6b6884fc", "6cc457ca", "79c590e4", "7eff1361", "81cd04bd", "8590fc7c",
        "8a24f93b", "8ac7ff35", "8de9e24f", "9761582e", "98769f84", "aa7033a1", "c35c2416",
        "c57915eb", "c66d6409", "ca009e95", "cbba7d02", "d94ed47e", "d95c2434", "d9b48a16",
        "df29dfed", "e2ec6cc6", "eacd9fe7", "ef60c8fb", "f644a71b", "fb4b24a9", "fb822e89",
        "fcb277b5", "fd244fa9",
    }
)  # fmt: skip

#: 위 65건의 규칙별 거부 건수(여러 규칙에 걸린 문항은 규칙마다 센다 — 4ce1eb57은 2규칙, ef60c8fb는 3규칙이라
#: 합이 68이다).
_KNOWN_CLEAN_RULE_COUNTS: dict[str, int] = {
    "E-motion-symbol-subject": 25,
    "T-power-path-coincidence": 23,
    "E-conclusion-target": 7,
    "E-function-notation": 6,
    "T05-quadratic-slope": 4,
    "T10-confusable-quantity": 2,
    "T-component-critical-point": 1,
}


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _round7(probe: ShortcutProbe) -> set[str]:
    return {v.rule for v in shortcut_violations(probe)} & ROUND7_RULE_IDS


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
    assert sum(_CAUSE_COUNTS.values()) == 11
    assert set().union(*_FAMILY.values()) == ROUND7_RULE_IDS
    assert {pid[:8] for pid in causes} == set(_DEFECT_RULES)


@pytest.mark.corpus_authoring
def test_round7_defects_are_caught_by_the_matching_rule_family(
    audited: dict[str, dict[str, object]], causes: dict[str, str]
) -> None:
    missed = {
        cause: sorted(
            pid[:8]
            for pid, c in causes.items()
            if c == cause and not (_round7(probe_from_record(audited[pid])) & family)
        )
        for cause, family in _FAMILY.items()
    }
    assert missed == {cause: [] for cause in _FAMILY}


@pytest.mark.parametrize("pid", sorted(_DEFECT_RULES))
def test_each_defect_is_caught_by_its_rules(
    pid: str, by_prefix: dict[str, dict[str, object]]
) -> None:
    """결함 11건 각각을 기대한 규칙(만)이 잡는다 — 원인 안의 절마다 따로 본다."""
    assert _round7(probe_from_record(by_prefix[pid])) == _DEFECT_RULES[pid]


# ── ② 변별 ─────────────────────────────────────────────────────────────────
@pytest.mark.corpus_authoring
def test_round7_bank_passes_every_earlier_rule(audited: dict[str, dict[str, object]]) -> None:
    """감사 은행은 6회차 규칙으로 빌드됐다 — 7회차 이전 규칙은 504건 중 0건을 잡는다(새 규칙이 일했다)."""
    earlier = [
        pid[:8]
        for pid, r in audited.items()
        if {v.rule for v in shortcut_violations(probe_from_record(r))} - ROUND7_RULE_IDS
    ]
    assert earlier == []


# ── ③ 과잉 거부 ────────────────────────────────────────────────────────────
@pytest.mark.corpus_authoring
def test_round7_clean_over_rejection_is_the_frozen_known_set(
    audited: dict[str, dict[str, object]], causes: dict[str, str]
) -> None:
    clean = [pid for pid in audited if pid not in causes]
    assert len(clean) == 493
    rejected = {pid[:8]: _round7(probe_from_record(audited[pid])) for pid in clean}
    rejected = {pid: rules for pid, rules in rejected.items() if rules}
    assert set(rejected) == _KNOWN_CLEAN_REJECTED
    counts = Counter(rule for rules in rejected.values() for rule in rules)
    assert dict(counts) == _KNOWN_CLEAN_RULE_COUNTS


# ── ④ 규칙별 대조군 ────────────────────────────────────────────────────────
def _fix(record: dict[str, object], **changes: object) -> ShortcutProbe:
    """동결 원문 문항 → 그 결함만 고친 표본(나머지 필드는 원문 그대로)."""
    return dataclasses.replace(probe_from_record(record), **changes)  # type: ignore[arg-type]


#: (규칙, 원문 id 앞 8자리) — 동결 원문 그대로 RED. 절이 둘 이상인 규칙은 절마다 한 줄.
_RED_IDS: list[tuple[str, str]] = [
    ("T05-quadratic-slope", "4d287bbd"),  # 접점 절 — 기울기 8인 접점의 x좌표(y = x^2 + 4x + 3)
    ("T05-quadratic-slope", "5a14790d"),  # 기울기 절 — 이차곡선 두 점의 기울기 합
    ("T-power-path-coincidence", "cbde3ec3"),  # 평가 절·지수 유지 — x^2의 f'(1)
    ("T-power-path-coincidence", "76a9f5ac"),  # 꼴 읽기 절·c만 — 지수 유지가 c를 맞힌다
    ("T-power-path-coincidence", "f644a71b"),  # 꼴 읽기 절·m만 — 계수 누락이 m을 맞힌다
    ("T-power-path-coincidence", "8590fc7c"),  # 주어진 도함수 꼴 절 — f'(x) = 8x^7일 때 n
    ("T-component-critical-point", "0bcf3427"),
    ("T10-confusable-quantity", "30d80000"),  # 속도를 묻는데 가속도가 같은 값
    ("E-motion-symbol-subject", "fb9ec6bc"),  # v(t) 절
    ("E-function-notation", "fb9ec6bc"),  # 'x(5)'
    ("E-conclusion-target", "b2d3bc4b"),  # 증감 대상 절
    ("E-conclusion-target", "1777b112"),  # 결론의 답 절 — 'x = 3에서 극솟값을 갖는다'로 맺음
]


@pytest.mark.parametrize(("rule", "pid"), _RED_IDS, ids=[f"{r}-{p}" for r, p in _RED_IDS])
def test_round7_rule_flags_the_as_found_defect(
    rule: str, pid: str, by_prefix: dict[str, dict[str, object]]
) -> None:
    assert rule in _round7(probe_from_record(by_prefix[pid]))


#: 평가 절·계수 누락 — x = 0이면 계수 누락 도함수의 값이 일차항 계수 그대로라 정답과 같다(지수 유지는 0).
_COEFF_DROPPED = ShortcutProbe(
    standard_code=_C03,
    question_text="함수 f(x) = x^3 + 5x에 대하여 f'(0)의 값을 구하시오.",
    answer="5",
    explanation="f'(x) = 3x^2 + 5이므로 x가 0일 때의 값은 5이다.",
    conditions=("Derivative(x**3 + 5*x, x).doit().subs(x, 0) = y",),
    answer_map=(("y", "5"),),
)
#: 속도를 묻는데 그 시각의 *위치*가 같은 값(x = t^2 - t + 1 · t = 2 → 위치 3 · 속도 3 · 가속도 2).
_POSITION_SAME = ShortcutProbe(
    standard_code=_C10,
    question_text=(
        "수직선 위를 움직이는 점 P의 시각 t에서의 위치가 x = t^2 - t + 1일 때, t = 2에서의 점 P의 속도를 "
        "구하시오."
    ),
    answer="3",
    explanation="속도 v(t)는 위치 x를 시각 t로 미분한 값이므로 v(t) = 2t - 1이고, t = 2일 때의 속도는 3이다.",
    conditions=("Derivative(t**2 - t + 1, t).doit().subs(t, 2) = y",),
    answer_map=(("y", "3"),),
)
#: 가속도를 묻는데 그 시각의 *속도*가 같은 값(x = t^3 · t = 2 → 속도 12 · 가속도 12).
_VELOCITY_SAME = ShortcutProbe(
    standard_code=_C10,
    question_text=(
        "수직선 위를 움직이는 점 P의 시각 t에서의 위치가 x = t^3 + 1일 때, t = 2에서의 점 P의 가속도를 "
        "구하시오."
    ),
    answer="12",
    explanation=(
        "속도 v(t)는 위치 x를 시각 t로 미분한 값이므로 v(t) = 3t^2이고, 가속도 a(t)는 속도 v(t)를 시각 t로 "
        "미분한 값이므로 a(t) = 6t이다. 따라서 t = 2일 때의 가속도는 12이다."
    ),
    conditions=("Derivative(t**3 + 1, t, t).doit().subs(t, 2) = y",),
    answer_map=(("y", "12"),),
)
#: a(t)만 주어 자리 소개가 없다(v(t)는 머리로 소개).
_A_NOT_SUBJECT = dataclasses.replace(
    _VELOCITY_SAME,
    explanation=(
        "속도 v(t)는 위치 x를 시각 t로 미분한 값이므로 v(t) = 3t^2이고, 가속도는 속도를 시각 t로 미분한 값이므로 "
        "a(t) = 6t이다. 따라서 t = 2일 때의 가속도는 12이다."
    ),
)

#: 02-03 밖에서도 미분하는 식이 거듭제곱 하나(상수항 제외)면 거듭제곱 미분계수다 — 02-04 상수배 c·x^n의 f'(1).
_MONOMIAL_AT_ONE = ShortcutProbe(
    standard_code=_C04,
    question_text="함수 f(x) = 3x^2 + 4에 대하여 f'(1)의 값을 구하시오.",
    answer="6",
    explanation="상수배의 미분법에 따라 도함수는 6x이므로 f'(1)의 값은 6이다.",
    conditions=("Derivative(3*x**2 + 4, x).doit().subs(x, 1) = y",),
    answer_map=(("y", "6"),),
)

_RED_HANDMADE: list[tuple[str, ShortcutProbe]] = [
    ("T-power-path-coincidence", _COEFF_DROPPED),
    ("T-power-path-coincidence", _MONOMIAL_AT_ONE),  # 범위 절 — 거듭제곱 하나인 몸통
    ("T10-confusable-quantity", _POSITION_SAME),  # 속도 → 위치
    ("T10-confusable-quantity", _VELOCITY_SAME),  # 가속도 → 속도
    ("E-motion-symbol-subject", _A_NOT_SUBJECT),  # a(t) 절
]


@pytest.mark.parametrize(
    ("rule", "probe"),
    _RED_HANDMADE,
    ids=[f"{r}-hand-{i}" for i, (r, _) in enumerate(_RED_HANDMADE)],
)
def test_round7_rule_flags_the_handmade_clause_defect(rule: str, probe: ShortcutProbe) -> None:
    assert rule in _round7(probe)


def _green_cases(by_prefix: dict[str, dict[str, object]]) -> list[tuple[str, ShortcutProbe]]:
    """(규칙, 그 결함만 고친 표본) — 원문 문항의 해당 필드만 교정했다(나머지는 원문 그대로)."""
    r = by_prefix
    return [
        # 7회차 처분 뒤 생성기 산출 그대로 — 삼차곡선에서 기울기 5인 접점(f'(a) = 5의 근 -1/3·1 중 양수).
        (
            "T05-quadratic-slope",
            _fix(
                r["4d287bbd"],
                question_text=(
                    "곡선 y = x^3 - x^2 + 4x + 2 위의 x좌표가 a인 점에서의 접선의 기울기가 5일 때, 양수 a의 "
                    "값을 구하시오."
                ),
                answer="1",
                conditions=("Derivative(x**3 - x**2 + 4*x + 2, x).doit().subs(x, a) = 5", "a > 0"),
                answer_map=(("a", "1"),),
            ),
        ),
        # 기울기 절의 대조 — 삼차곡선 두 점의 기울기 합(검산 몸통 f(x) + f(x + 4)는 Tier1 표기 제약일 뿐이다).
        (
            "T05-quadratic-slope",
            _fix(
                r["5a14790d"],
                question_text=(
                    "곡선 y = x^3 - 3x^2 - x - 5 위의 x좌표가 -1인 점과 3인 점에서의 접선의 기울기의 합을 "
                    "구하시오."
                ),
                answer="16",
                conditions=(
                    "Derivative(x**3 - 3*x**2 - x - 5 + (x**3 + 9*x**2 + 23*x + 7), x).doit()"
                    ".subs(x, -1) = y",
                ),
                answer_map=(("y", "16"),),
            ),
        ),
        # x = -2에서 묻으면 지수 유지 n·(-2)^n · 계수 누락 (-2)^(n - 1) 모두 정답 -4와 갈린다.
        (
            "T-power-path-coincidence",
            _fix(
                r["cbde3ec3"],
                question_text="함수 f(x) = x^2에 대하여 f'(-2)의 값을 구하시오.",
                answer="-4",
                conditions=("Derivative(x**2, x).doit().subs(x, -2) = y",),
                answer_map=(("y", "-4"),),
            ),
        ),
        # c + m을 묻으면 지수 유지(8 + 8)·계수 누락(1 + 7) 모두 정답 15와 갈린다.
        (
            "T-power-path-coincidence",
            _fix(
                r["76a9f5ac"],
                question_text=(
                    "함수 f(x) = x^8의 도함수 f'(x)를 cx^m (c, m은 상수) 꼴로 나타낼 때, c + m의 값을 구하시오."
                ),
                answer="15",
                conditions=("Derivative(x**8, x).doit().subs(x, 2) = (s - 7)*2**7",),
                answer_map=(("s", "15"),),
            ),
        ),
        # 주어진 도함수의 지수만 주고 계수 k를 묻으면 계수 누락(k = 1)·지수 유지(k = 7)와 갈린다.
        (
            "T-power-path-coincidence",
            _fix(
                r["8590fc7c"],
                question_text=(
                    "함수 f(x) = x^n (n은 2 이상의 자연수)의 도함수가 f'(x) = kx^7 (k는 상수)일 때, k의 값을 "
                    "구하시오."
                ),
                answer="8",
                conditions=("Derivative(x**8, x).doit().subs(x, 2) = k*2**7",),
                answer_map=(("k", "8"),),
            ),
        ),
        # f(x) = x(항등함수)의 계수 누락 x^0 = 1은 참 도함수다 — 오답 경로가 아니다(대조).
        (
            "T-power-path-coincidence",
            ShortcutProbe(
                standard_code=_C03,
                question_text="함수 f(x) = x에 대하여 f'(2)의 값을 구하시오.",
                answer="1",
                explanation="f(x) = x는 지수가 1인 거듭제곱이므로 도함수는 1이다.",
                conditions=("Derivative(x, x).doit().subs(x, 2) = y",),
                answer_map=(("y", "1"),),
            ),
        ),
        # 평가점 x = -1이면 g'(-1) = 0(임계점) — x = 2로 옮기면 f'(2) = -4 · g'(2) = -9로 둘 다 0이 아니다.
        (
            "T-component-critical-point",
            _fix(
                r["0bcf3427"],
                question_text=str(r["0bcf3427"]["question_text"]).replace("x = -1", "x = 2"),
                answer="19",
                conditions=(
                    "Derivative(2*(-x**2 - 2) - 3*(-x**3 + 3*x + 7), x).doit().subs(x, 2) = y",
                ),
                answer_map=(("y", "19"),),
            ),
        ),
        # 위치 t^3 - 6t^2 - 3t: 가속도 0인 t = 2에서 속도 -15(가속도 0 · 위치 -22와 다르다).
        (
            "T10-confusable-quantity",
            _fix(
                r["30d80000"],
                question_text=str(r["30d80000"]["question_text"]).replace(
                    "t^3 - 3t^2 + 3t + 2", "t^3 - 6t^2 - 3t"
                ),
                answer="-15",
                conditions=("Derivative(t**3 - 6*t**2 - 3*t, t).doit().subs(t, 2) = y",),
                answer_map=(("y", "-15"),),
            ),
        ),
        # 기호를 주어 자리에서 소개하면(머리 '속도 v(t)는 …이므로 v(t) = …') 통과한다.
        (
            "E-motion-symbol-subject",
            _fix(
                r["fb9ec6bc"],
                explanation=(
                    "속도 v(t)는 위치 x를 시각 t로 미분한 값이므로 v(t) = 4t - 6이고, t = 5일 때의 속도는 "
                    "14이다. t = 5일 때의 위치 25는 속도가 아니다."
                ),
            ),
        ),
        # 6회차 머리('속도 v(t)는 … 값이다. v(t) = …')도 기호를 주어 자리에서 소개한다(판정기는 형태만 본다).
        (
            "E-motion-symbol-subject",
            dataclasses.replace(
                _VELOCITY_SAME,
                explanation=(
                    "속도 v(t)는 위치를 시각 t로 미분한 값이고, 가속도 a(t)는 속도를 시각 t로 미분한 값이다. "
                    "v(t) = 3t^2, a(t) = 6t이므로 t = 2일 때의 가속도는 12이다."
                ),
            ),
        ),
        # 함수 표기를 말로 풀면 통과한다.
        (
            "E-function-notation",
            _fix(
                r["fb9ec6bc"],
                explanation=str(r["fb9ec6bc"]["answer_explanation"]).replace(
                    "이 시각의 위치 x(5) = 25는", "t = 5일 때의 위치 25는"
                ),
            ),
        ),
        # 발문이 이미 함수 표기로 보인 기호(f(x) = …)는 해설이 소개 없이 f'(2)로 써도 된다.
        (
            "E-function-notation",
            ShortcutProbe(
                standard_code=_C04,
                question_text="함수 f(x) = x^3 - 2x에 대하여 f'(2)의 값을 구하시오.",
                answer="10",
                explanation="도함수는 3x^2 - 2이므로 f'(2)의 값은 10이다.",
                conditions=("Derivative(x**3 - 2*x, x).doit().subs(x, 2) = y",),
                answer_map=(("y", "10"),),
            ),
        ),
        # 기호를 먼저 정의하면('위치를 x(t)라 하자') 함수 표기를 써도 된다.
        (
            "E-function-notation",
            _fix(
                r["fb9ec6bc"],
                explanation="위치를 x(t)라 하자. " + str(r["fb9ec6bc"]["answer_explanation"]),
            ),
        ),
        (
            "E-conclusion-target",
            _fix(
                r["b2d3bc4b"],
                explanation=str(r["b2d3bc4b"]["answer_explanation"]).replace(
                    "따라서 f'(x) = 0의 근 중 극값을 갖는 x좌표는 6뿐이다.",
                    "따라서 f'(x)의 부호가 바뀌는 x = 6에서만 증가·감소가 바뀌므로, 증가·감소가 바뀌는 점의 "
                    "x좌표는 6이다.",
                ),
            ),
        ),
        (
            "E-conclusion-target",
            _fix(
                r["1777b112"],
                explanation=str(r["1777b112"]["answer_explanation"]).replace(
                    "따라서 x = 3에서 극솟값을 갖는다.",
                    "따라서 x = 3에서 실제로 극솟값 -21을 가지므로 구하는 a의 값은 -3이다.",
                ),
            ),
        ),
    ]


def test_round7_corrected_forms_pass_their_rule(by_prefix: dict[str, dict[str, object]]) -> None:
    """규칙마다 *그 결함만 고친* 같은 문항은 그 규칙을 통과한다(규칙이 결함 표지가 아니라 문항 전체를 막지
    않는다는 대조). 다른 규칙 위반은 여기서 보지 않는다 — 원문의 다른 결함이 남아 있을 수 있다."""
    still = [
        (rule, i, sorted(_round7(probe)))
        for i, (rule, probe) in enumerate(_green_cases(by_prefix))
        if rule in _round7(probe)
    ]
    assert still == []


def test_every_round7_rule_has_red_and_green_controls(
    by_prefix: dict[str, dict[str, object]],
) -> None:
    red = {rule for rule, _ in _RED_IDS} | {rule for rule, _ in _RED_HANDMADE}
    green = {rule for rule, _ in _green_cases(by_prefix)}
    assert red == ROUND7_RULE_IDS
    assert green == ROUND7_RULE_IDS
    # 7회차 규칙은 RULE_IDS의 꼬리 구간이고(회차 순서) 앞 회차와 겹치지 않는다. 자격 측정 뒤 회차 규칙 전부가
    # 투표 제외 집합이다.
    assert list(RULE_IDS[-len(ROUND7_RULE_IDS) :]) == [r for r in RULE_IDS if r in ROUND7_RULE_IDS]
    assert not (ROUND5_RULE_IDS | ROUND6_RULE_IDS) & ROUND7_RULE_IDS
    assert POST_QUALIFICATION_RULE_IDS == ROUND5_RULE_IDS | ROUND6_RULE_IDS | ROUND7_RULE_IDS
    assert {
        "T-power-path-coincidence",
        "T-component-critical-point",
        "T10-confusable-quantity",
    } == COINCIDENCE_RULE_IDS & ROUND7_RULE_IDS


# ── 오답 경로 도함수 · 운동 기호 주어 판정 ──────────────────────────────────
def test_power_path_derivative_applies_each_wrong_step_termwise() -> None:
    f = 2 * _X**3 - 5 * _X + 7
    assert power_path_derivative(f, _X, "계수 누락") == sympy.expand(2 * _X**2 - 5)
    assert power_path_derivative(f, _X, "지수 유지") == sympy.expand(6 * _X**3 - 5 * _X)
    n = sympy.Symbol("n")  # 문자 지수도 읽는다(x^n)
    assert power_path_derivative(_X**n, _X, "계수 누락") == _X ** (n - 1)
    assert power_path_derivative(_X**n, _X, "지수 유지") == n * _X**n
    assert power_path_derivative(2**_X, _X, "계수 누락") is None  # c·x^e 꼴이 아니다
    assert power_path_derivative(_T**4, _T, "지수 유지") == 4 * _T**4


def test_motion_symbols_not_in_subject_reads_first_use() -> None:
    assert motion_symbols_not_in_subject(
        "속도는 위치를 시각 t로 미분한 값이다. v(t) = 2t이다."
    ) == ("v(t)",)
    assert (
        motion_symbols_not_in_subject(
            "속도 v(t)는 위치 x를 시각 t로 미분한 값이므로 v(t) = 2t이다."
        )
        == ()
    )
    # 머리보다 앞에 기호가 먼저 나오면 소개가 아니다.
    assert motion_symbols_not_in_subject(
        "v(t) = 2t이다. 속도 v(t)는 위치 x를 시각 t로 미분한 값이다."
    ) == ("v(t)",)
    # '가속도 a(t)는 …'의 '속도'를 속도 머리로 읽지 않는다.
    assert motion_symbols_not_in_subject(
        "가속도 a(t)는 속도 v(t)를 시각 t로 미분한 값이므로 a(t) = 2이다."
    ) == ("v(t)",)
    assert motion_symbols_not_in_subject("위치의 그래프를 본다.") == ()


# ── ⑤ 매개변수 거부 조건 ───────────────────────────────────────────────────
def _value_item(n: int, point: int) -> DiffItem:
    """02-03 진단 — f(x) = x^n의 f'(point)."""
    value = n * point ** (n - 1)
    return DiffItem(
        slot="diagnostic",
        frame_id="test-power-value",
        question_text=f"함수 f(x) = x^{n}에 대하여 f'({point})의 값을 구하시오.",
        answer_text=str(value),
        explanation=f"x^{n}의 도함수는 {n}x^{n - 1}이다.",
        conditions=f"Derivative(x**{n}, x).doit().subs(x, {point}) = y",
        answer_map=(("y", str(value)),),
        problem_type_code="ptype.evaluate-expression",
        answer_format=AnswerFormat.자연수 if value > 0 else AnswerFormat.실수,
    )


def _sum_item(f: str, g: str, shown: tuple[str, str], point: int, value: int) -> DiffItem:
    """02-04 숙련도 — h = 2f - 3g의 h'(point)."""
    return DiffItem(
        slot="mastery_check",
        frame_id="test-linear-combination",
        question_text=(
            f"두 함수 f(x) = {shown[0]}, g(x) = {shown[1]}에 대하여 함수 h(x) = 2f(x) - 3g(x)의 "
            f"x = {point}에서의 미분계수를 구하시오."
        ),
        answer_text=str(value),
        explanation="h'(x)는 2f'(x)에서 3g'(x)를 뺀 것이다.",
        conditions=f"Derivative(2*({f}) - 3*({g}), x).doit().subs(x, {point}) = y",
        answer_map=(("y", str(value)),),
        problem_type_code="ptype.evaluate-expression",
        answer_format=AnswerFormat.자연수,
    )


def test_round_robin_skips_round7_coincident_parameters_only_when_asked() -> None:
    """x^3의 f'(1)(지수 유지와 일치)·성분 임계점 x = -1은 매개변수 거부 조건이 건너뛴다.

    대조군: standard_code 없이 부르면(거부 조건 미적용) 그 파라미터가 그대로 나온다.
    """
    at_one, at_two = _value_item(3, 1), _value_item(3, 2)
    assert {v.rule for v in parameter_coincidences(probe_of(_C03, at_one))} == {
        "T-power-path-coincidence"
    }
    assert parameter_coincidences(probe_of(_C03, at_two)) == []
    by_key = {1: at_one, 2: at_two}
    frames = [Frame("test-power-value", ((1,), (2,)), lambda p: by_key[int(str(p[0]))])]
    assert [i.answer_text for i in round_robin_items(frames, 2, standard_code=_C03)] == ["12"]
    assert [i.answer_text for i in round_robin_items(frames, 2)] == ["3", "12"]

    f, g = "-x**2 - 2", "-x**3 + 3*x + 7"
    critical = _sum_item(f, g, ("-x^2 - 2", "-x^3 + 3x + 7"), -1, 4)
    honest = _sum_item(f, g, ("-x^2 - 2", "-x^3 + 3x + 7"), 2, 19)
    assert {v.rule for v in parameter_coincidences(probe_of(_C04, critical))} == {
        "T-component-critical-point"
    }
    assert parameter_coincidences(probe_of(_C04, honest)) == []


def test_round_robin_skips_confusable_quantity_parameters() -> None:
    """02-10 '가속도가 0이 되는 시각의 속도' — 위치 (t - 1)^3 + 2는 그 시각의 속도도 0이라 건너뛴다."""

    def item(position: str, shown: str, t: int, v: int) -> DiffItem:
        return DiffItem(
            slot="mastery_check",
            frame_id="test-velocity-at-zero-acceleration",
            question_text=(
                f"수직선 위를 움직이는 점 P의 시각 t에서의 위치가 x = {shown}일 때, 점 P의 가속도가 0이 되는 "
                "시각의 속도를 구하시오."
            ),
            answer_text=str(v),
            explanation="속도 v(t)는 위치 x를 시각 t로 미분한 값이므로 v(t) = …이다.",
            conditions=f"Derivative({position}, t).doit().subs(t, {t}) = y",
            answer_map=(("y", str(v)),),
            problem_type_code="ptype.evaluate-expression",
            answer_format=AnswerFormat.실수,
        )

    flat = item("t**3 - 3*t**2 + 3*t + 2", "t^3 - 3t^2 + 3t + 2", 1, 0)
    honest = item("t**3 - 6*t**2 - 3*t", "t^3 - 6t^2 - 3t", 2, -15)
    assert {v.rule for v in parameter_coincidences(probe_of(_C10, flat))} == {
        "T10-confusable-quantity"
    }
    assert parameter_coincidences(probe_of(_C10, honest)) == []
    by_key = {1: flat, 2: honest}
    frames = [Frame("test-va", ((1,), (2,)), lambda p: by_key[int(str(p[0]))])]
    assert [i.answer_text for i in round_robin_items(frames, 2, standard_code=_C10)] == ["-15"]


def test_quadratic_slope_reads_the_curve_not_the_tier1_body() -> None:
    """검산 몸통이 이차(삼차 f의 f(x + d) - f(x))여도 발문의 곡선이 삼차면 걸지 않는다 — 이차 곡선만 건다."""
    cubic = ShortcutProbe(
        standard_code=_C05,
        question_text=(
            "곡선 y = x^3 - 3x^2 + 3x - 5 위의 x좌표가 2인 점에서의 접선의 기울기에서 x좌표가 -2인 점에서의 "
            "접선의 기울기를 뺀 값을 구하시오."
        ),
        answer="-24",
        explanation="곡선의 식을 y = f(x)라 하자. f'(x) = 3x^2 - 6x + 3이다.",
        conditions=(
            "Derivative((x**3 + 9*x**2 + 27*x + 23) - (x**3 - 3*x**2 + 3*x - 5), x).doit()"
            ".subs(x, -2) = y",
        ),
        answer_map=(("y", "-24"),),
    )
    assert "T05-quadratic-slope" not in _round7(cubic)
    quadratic = dataclasses.replace(
        cubic,
        question_text=cubic.question_text.replace("x^3 - 3x^2 + 3x - 5", "x^2 + 3x - 5"),
    )
    assert "T05-quadratic-slope" in _round7(quadratic)


#: 7회차에 이차 → 삼차로 바꾼 02-05 '기울기 → 접점' 틀(원인 ① 교정 대상).
_SLOPE_TO_POINT_FRAMES: frozenset[str] = frozenset(
    {"rep-find-point-for-slope", "applied-parallel-to-line", "applied-perpendicular-to-line"}
)


@pytest.mark.corpus_authoring
def test_rewritten_slope_frames_never_answer_one() -> None:
    """7회차에 삼차로 바꾼 02-05 '기울기 → 접점' 틀 3종은 접점 x = 1을 답으로 내지 않는다.

    a = 1이면 지수를 줄이지 않는 오개념의 도함수 Σ n·c·a^n도 a = 1에서 참 도함수와 같은 값이라 거듭제곱
    미분 오류로도 정답에 닿는다(3회차 감사 cbde3ec3과 같은 형태 — 원인 ① 교정이 원인 ②를 새로 만들지
    않게 한다). 이 틀들은 판정기 거듭제곱 경로 규칙의 범위(02-03·거듭제곱 하나·거듭제곱 오개념 선지) 밖이라
    판정기가 아니라 생성기의 접점 축 `_SLOPE_POINTS`가 막는다 — 축에 1을 되돌리면 이 단언이 깨진다.
    """
    seen = [
        item
        for slot in ("representative", "applied")
        for item in P3DiffTangentLineGenerator.items(slot)
        if item.frame_id in _SLOPE_TO_POINT_FRAMES
    ]
    # 공허 통과 방지 — 틀 3종이 슬롯에 실제로 뽑혀 있어야 단언이 무언가를 본다.
    assert {item.frame_id for item in seen} == _SLOPE_TO_POINT_FRAMES
    assert [item.question_text for item in seen if item.answer_text == "1"] == []
