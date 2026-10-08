"""P3-03 미분 은행 — 6회차(은행 감사 2회차 · 2026-10-08) 결함 원인의 기계 판정 규칙 회귀 테스트(hermetic·LLM 0).

은행 감사 2회차(`docs/data/p3_calculus1_diff_audit/bank_audit_r2/` — 5회차 교정 은행 504건 · LLM 판정자 2명 ·
처분 `disposition.json`)는 결함 23건을 원인 7종으로 찾았다(as-found k = 23 · S5 불합격). 그 원인 중 *문면·검산
조건·선지 귀속에서 기계로 읽히는 것*을 판정기 `p3_diff_shortcut_guard`의 6회차 규칙(`ROUND6_RULE_IDS`)으로
옮겼다. 이 파일은 다섯 가지를 못 박는다.

① **재현율** — 감사 동결 원문(as-found · `bank_audit_r2/audited_bank.jsonl`)에서 결함 23건 전부를 *그 원인에
   대응하는 규칙군*이 잡는다(원인별 건수 동결). 규칙의 절을 지우면(뮤테이션) 이 단언이 깨진다.
② **변별** — 그 은행은 5회차 규칙으로 빌드됐으므로 6회차 이전 규칙만으로는 504건 중 0건을 잡는다.
③ **과잉 거부** — 결함이 아닌 481건 중 6회차 규칙이 거부하는 것은 고정된 66건뿐이다(규칙별 건수 동결). 전부
   *같은 틀의 같은 형태*다(정의 없는 v(t) 38 · 상수항을 옮기면 중근 인수 11 · 구간 없는 개수 검산 8 · '곡선이
   극대' 7 · 배수 틀 1 · 근 옮겨 적기 1) — 판정자 2명은 표본 판정이라 같은 형태를 모두 짚지 않았다(결함 후보로
   보고한다). 집합이 바뀌면 RED(조용히 늘거나 줄지 않는다).
④ 규칙마다 결함 문면(RED — 동결 원문 또는 그 절만 담은 손 표본)과 그 결함만 고친 문면(GREEN) 대조군이 있다.
   절이 둘 이상인 규칙은 절마다 RED를 둔다(판독 모호/값 불일치/해설 · v/a · 비례/계수 누락/지수 유지 · 경로/
   근 옮겨 적기 · 방정식/상수항 · 선지/답 형식/해설 · 구간 없음/구간 다름 · 극대/x = a에서/감소).
⑤ 매개변수 거부 조건(6회차 `COINCIDENCE_RULE_IDS`)이 생성기의 라운드로빈에서 실제로 파라미터를 건너뛴다.

규칙은 판정기 한 곳에만 있다(생성기 빌드 `_validate_slot`이 fail-loud로, 라운드로빈이 매개변수 거부로 같은
판정을 쓴다). 개수 문항의 검산이 구간을 반영하는지(원인 6)는 검증기 `verify_real_root_count`의 범위 계약
회귀(구판 검산 RED · 새 검산 GREEN)로도 함께 본다.
"""

from __future__ import annotations

import dataclasses
import json
from collections import Counter
from pathlib import Path

import pytest
import sympy

from whymath_backend.harness.corpus_reverify import reverify_corpus
from whymath_backend.l3.equivalent.p3_diff_shortcut_guard import (
    COINCIDENCE_RULE_IDS,
    EXTREMUM_POINT_KEBAB,
    POST_QUALIFICATION_RULE_IDS,
    ROUND5_RULE_IDS,
    ROUND6_RULE_IDS,
    ROUND7_RULE_IDS,
    ROUND8_RULE_IDS,
    RULE_IDS,
    ShortcutProbe,
    extremum_point_count,
    parameter_coincidences,
    probe_from_record,
    shortcut_violations,
    undefined_motion_symbols,
)
from whymath_backend.l3.equivalent.p3_diff_skeleton_base import (
    DiffItem,
    Frame,
    probe_of,
    round_robin_items,
)
from whymath_backend.schema.enums import AnswerFormat

_ROOT = Path(__file__).resolve().parents[4]
_AUDIT = _ROOT / "docs" / "data" / "p3_calculus1_diff_audit" / "bank_audit_r2"

_C03, _C04, _C06 = "[12미적Ⅰ-02-03]", "[12미적Ⅰ-02-04]", "[12미적Ⅰ-02-06]"
_C08, _C09, _C10 = "[12미적Ⅰ-02-08]", "[12미적Ⅰ-02-09]", "[12미적Ⅰ-02-10]"
_X = sympy.Symbol("x")

#: 원인(처분 문자열의 앞머리) → 그 원인을 잡아야 하는 규칙군(하나 이상 걸리면 잡은 것).
_FAMILY: dict[str, frozenset[str]] = {
    "M0615 설명 자기모순": frozenset({"M-link-contradictory"}),
    "속도 해설에서 v(t) 소개": frozenset({"E-motion-symbol-intro"}),
    "오답 경로·비례 짐작이 정답과 일치": frozenset(
        {"T-ratio-shortcut", "T-derivative-roots-coincidence"}
    ),
    "극값이 0 또는 상수항과 같아": frozenset({"T09-factored-level"}),
    "평균속도 객관식에 c 구간 조건 누락": frozenset({"U-extra-solution"}),
    "평균값 정리 c 개수 문항의 verify": frozenset({"V-count-interval"}),
    "'곡선 … 이 극대가 되는' 용어": frozenset({"W-curve-subject"}),
}

#: 원인별 결함 건수(처분 `disposition.json`의 cause_counts와 같다 — 합 23).
_CAUSE_COUNTS: dict[str, int] = {
    "M0615 설명 자기모순": 12,
    "속도 해설에서 v(t) 소개": 3,
    "오답 경로·비례 짐작이 정답과 일치": 2,
    "극값이 0 또는 상수항과 같아": 2,
    "평균속도 객관식에 c 구간 조건 누락": 2,
    "평균값 정리 c 개수 문항의 verify": 1,
    "'곡선 … 이 극대가 되는' 용어": 1,
}

#: 결함이 아닌 481건 중 6회차 규칙이 거부하는 문항(id 앞 8자리) — 전부 결함 문항과 *같은 틀의 같은 형태*다.
_KNOWN_CLEAN_REJECTED: frozenset[str] = frozenset(
    {
        "06efd327", "074f04cc", "08d0c5ec", "08daf881", "0bee0f59", "0d306fe5", "12c6e97f",
        "1523db07", "19413905", "1be2510b", "27317f2f", "297e894a", "2e976864", "30d80000",
        "34c8e0da", "361295c7", "3d3beeb2", "3fd29e59", "40ab569c", "41182573", "45f07f18",
        "4637ad98", "4bb0d16c", "57b8f7a3", "5de57aa7", "5e5ac447", "6032f184", "670f1c28",
        "6782eb62", "7116acf8", "7458ca3c", "7572edf6", "768ca0bf", "78d1da8f", "78efc8e6",
        "79d4417d", "894cfd6b", "8b397d85", "8ed49c04", "9076e5e0", "9b7ad5ff", "9c1b28d1",
        "a3dbd37f", "a5dee0f1", "aa7df0c4", "adc64c7d", "b6b0efe4", "b8bebfa5", "ba2a4743",
        "c001e351", "c019e458", "c984f160", "cb0d9dc2", "d0d60a5b", "d88e78d2", "d9b48a16",
        "da13e71b", "dc5f9301", "de68bc12", "df29dfed", "ee468650", "f63d5040", "faac642f",
        "fcf0b537", "fd299556", "ffe9ed3c",
    }
)  # fmt: skip

#: 위 66건의 규칙별 거부 건수.
_KNOWN_CLEAN_RULE_COUNTS: dict[str, int] = {
    "E-motion-symbol-intro": 38,
    "T09-factored-level": 11,
    "V-count-interval": 8,
    "W-curve-subject": 7,
    "T-ratio-shortcut": 1,
    "T-derivative-roots-coincidence": 1,
}


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _round6(probe: ShortcutProbe) -> set[str]:
    return {v.rule for v in shortcut_violations(probe)} & ROUND6_RULE_IDS


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
    assert sum(_CAUSE_COUNTS.values()) == 23
    assert set().union(*_FAMILY.values()) <= ROUND6_RULE_IDS


def test_round6_defects_are_caught_by_the_matching_rule_family(
    audited: dict[str, dict[str, object]], causes: dict[str, str]
) -> None:
    missed = {
        cause: sorted(
            pid[:8]
            for pid, c in causes.items()
            if c == cause and not (_round6(probe_from_record(audited[pid])) & family)
        )
        for cause, family in _FAMILY.items()
    }
    assert missed == {cause: [] for cause in _FAMILY}


# ── ② 변별 ─────────────────────────────────────────────────────────────────
def test_round6_bank_passes_every_earlier_rule(audited: dict[str, dict[str, object]]) -> None:
    """감사 은행은 5회차 규칙으로 빌드됐다 — 6회차 이전 규칙은 504건 중 0건을 잡는다(새 규칙이 일했다).

    6회차 *뒤에* 더한 회차 규칙(7·8회차 — `ROUND7_RULE_IDS`·`ROUND8_RULE_IDS`)도 빼고 본다: 그 규칙은
    이 은행을 빌드할 때 없었다(회차별 측정은 그 회차의 규칙 집합으로 한다)."""
    earlier = [
        pid[:8]
        for pid, r in audited.items()
        if {v.rule for v in shortcut_violations(probe_from_record(r))}
        - ROUND6_RULE_IDS
        - ROUND7_RULE_IDS
        - ROUND8_RULE_IDS
    ]
    assert earlier == []


# ── ③ 과잉 거부 ────────────────────────────────────────────────────────────
@pytest.mark.corpus_authoring
def test_round6_clean_over_rejection_is_the_frozen_known_set(
    audited: dict[str, dict[str, object]], causes: dict[str, str]
) -> None:
    clean = [pid for pid in audited if pid not in causes]
    assert len(clean) == 481
    rejected = {pid[:8]: _round6(probe_from_record(audited[pid])) for pid in clean}
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
    ("M-link-contradictory", "bd6f889f"),
    ("E-motion-symbol-intro", "639e6fc9"),  # v(t) 절
    ("T-ratio-shortcut", "c32c1d5d"),  # n = 2 — 비례 짐작·계수 누락 둘 다
    ("T-ratio-shortcut", "7458ca3c"),  # n = 3 — 계수 누락 경로만(비례 짐작 16 ≠ 4)
    ("T-derivative-roots-coincidence", "07eefccb"),  # 대칭 근 — 계수 누락 경로
    ("T-derivative-roots-coincidence", "a5dee0f1"),  # 정답이 발문의 근(-3)
    ("T09-factored-level", "9f4b4a55"),  # 상수항을 옮긴 식 2x(x - 3)^2
    ("T09-factored-level", "2cc1e0d6"),  # 상수항을 옮긴 식 x(x + 3)^2
    ("U-extra-solution", "bdc71cfe"),  # 객관식 — 구간 밖 근 -2가 선지에 있다
    ("U-extra-solution", "d524ac47"),  # 객관식 — 선지엔 없지만 해설이 발문에 없는 구간으로 버린다
    ("V-count-interval", "c743fda0"),  # 구간 없음 — '구간 [a, b]에서 평균값 정리를 만족시키는'
    ("V-count-interval", "6782eb62"),  # 구간 없음 — '-4 < x < 4인 범위에서'
    ("V-count-interval", "faac642f"),  # 구간 없음 — '시각 t (t ≥ 0)'
    ("W-curve-subject", "6fef75c7"),  # '곡선 …이 극대가 되는'
    ("W-curve-subject", "12c6e97f"),  # '곡선 …가 x = -1에서 극댓값'
    ("W-curve-subject", "b8bebfa5"),  # '곡선 …가 감소하다가'
]


@pytest.mark.parametrize(("rule", "pid"), _RED_IDS, ids=[f"{r}-{p}" for r, p in _RED_IDS])
def test_round6_rule_flags_the_as_found_defect(
    rule: str, pid: str, by_prefix: dict[str, dict[str, object]]
) -> None:
    assert rule in _round6(probe_from_record(by_prefix[pid]))


#: 6회차 처분 뒤 02-09 오개념 유발 문항(생성기 산출 그대로) — '극값·극점 혼동' 연결 선지 '0'(극점 x좌표 1,
#: 3, 4를 극값으로 넣으면 0이 모두보다 작다) · 정답 2 · 차수 4 · 극값 후보 3(둘 다 미연결).
_W_EXPLANATION = (
    "f(x) = 3x^4 - 32x^3 + 114x^2 - 144x + 41이라 하자. f'(x) = 12x^3 - 96x^2 + 228x - 144 = "
    "12(x - 1)(x - 3)(x - 4)이므로 f(x)는 x = 1에서 극솟값 -18, x = 3에서 극댓값 14, x = 4에서 극솟값 9를 "
    "갖는다. f(x)는 x < 1에서 -18보다 큰 모든 값, 1 < x < 3에서 -18과 14 사이의 값, 3 < x < 4에서 9와 "
    "14 사이의 값, x > 4에서 9보다 큰 모든 값을 한 번씩 갖는다. 0은 이 가운데 2개의 범위에 들어 있다. "
    "극대·극소가 되는 점의 x좌표 1, 3, 4를 극값으로 잘못 넣으면 0이 그 값들보다 모두 작으므로 0개로 세게 "
    "된다. 극값은 그 점에서의 함숫값이지 x좌표가 아니다. 차수 4를 그대로 실근의 개수로 세면 그래프가 직선과 "
    "실제로 몇 번 만나는지를 보지 않은 것이다. 도함수가 0이 되는 서로 다른 x의 개수 3은 극값 후보를 센 값일 "
    "뿐 실근의 개수가 아니다. 따라서 서로 다른 실근은 2개이다."
)
_POINT_MC = ShortcutProbe(
    standard_code=_C09,
    question_text="방정식 3x^4 - 32x^3 + 114x^2 - 144x + 41 = 0의 서로 다른 실근의 개수로 옳은 것은?",
    answer="2",
    explanation=_W_EXPLANATION,
    choices=("0", "2", "3", "4"),
    conditions=("3*x**4 - 32*x**3 + 114*x**2 - 144*x + 41 = 0",),
    answer_kind="real_root_count",
    answer_format="자연수",
    distractors=((0, EXTREMUM_POINT_KEBAB),),
    slot="misconception_trigger",
)
#: 두 곡선 꼴(생성기 산출 그대로) — 해설처럼 '정리하면 3x^4 + 8x^3 - 6x^2 - 24x = -17'로 읽어 극점 x좌표
#: -2, -1, 1과 -17을 비교한다(절차 값 0). 차를 통째로 0과 비교하면 판독이 갈린다(읽기 방식의 변별).
_TWO_CURVES_MC = ShortcutProbe(
    standard_code=_C09,
    question_text="두 곡선 y = 3x^4 + 8x^3, y = 6x^2 + 24x - 17의 교점의 개수로 옳은 것은?",
    answer="2",
    explanation=(
        "교점의 x좌표는 두 식을 같게 놓은 방정식의 실근이고, 정리하면 3x^4 + 8x^3 - 6x^2 - 24x = -17이다. "
        "f(x) = 3x^4 + 8x^3 - 6x^2 - 24x라 하자. f'(x) = 12x^3 + 24x^2 - 12x - 24 = "
        "12(x + 2)(x + 1)(x - 1)이므로 f(x)는 x = -2에서 극솟값 8, x = -1에서 극댓값 13, x = 1에서 극솟값 "
        "-19를 갖는다. -17은 이 가운데 2개의 범위에 들어 있다. 극대·극소가 되는 점의 x좌표 -2, -1, 1을 "
        "극값으로 잘못 넣으면 -17이 그 값들보다 모두 작으므로 0개로 세게 된다. 따라서 서로 다른 실근은 "
        "2개이다."
    ),
    choices=("0", "2", "3", "4"),
    conditions=("3*x**4 + 8*x**3 = 6*x**2 + 24*x - 17",),
    answer_kind="real_root_count",
    answer_format="자연수",
    distractors=((0, EXTREMUM_POINT_KEBAB),),
)
#: 계수 양수 삼차(x^3 - 3x + 1 = 0) — 극점 x좌표 -1(극대)·1(극소)이 극값과 순서가 반대라 0을 '사이'로 읽으면
#: 3개, 순서를 지킨 비교 규칙·구간별 값 범위로는 1개 — 판독이 갈린다.
_AMBIGUOUS_MC = ShortcutProbe(
    standard_code=_C09,
    question_text="방정식 x^3 - 3x + 1 = 0의 서로 다른 실근의 개수로 옳은 것은?",
    answer="3",
    explanation=(
        "f(x) = x^3 - 3x + 1이라 하자. 극대·극소가 되는 점의 x좌표 -1, 1을 극값으로 잘못 넣으면 0이 -1과 1 "
        "사이에 있으므로 1개로 세게 된다."
    ),
    choices=("0", "1", "2", "3"),
    conditions=("x**3 - 3*x + 1 = 0",),
    answer_kind="real_root_count",
    answer_format="자연수",
    distractors=((1, EXTREMUM_POINT_KEBAB),),
)
#: 개수 문항이 아닌 고전 형태 — 극댓값(2)을 묻는데 극점의 x좌표 -1을 답한 선지.
_CLASSIC_MC = ShortcutProbe(
    standard_code=_C08,
    question_text="함수 f(x) = x^3 - 3x의 극댓값은?",
    answer="2",
    explanation="f'(x) = 3x^2 - 3 = 3(x + 1)(x - 1)이다.",
    choices=("-2", "-1", "2", "3"),
    conditions=("Derivative(x**3 - 3*x, x).doit() = 0", "y = x**3 - 3*x"),
    answer_map=(("x", "-1"), ("y", "2")),
    distractors=((1, EXTREMUM_POINT_KEBAB),),
)
_ACCEL = ShortcutProbe(
    standard_code=_C10,
    question_text=(
        "수직선 위를 움직이는 점 P의 시각 t에서의 위치가 x = 2t^2 - 4t일 때, t = 5에서의 점 P의 가속도를 "
        "구하시오."
    ),
    answer="4",
    explanation="속도는 위치를 시각 t로 미분한 값이므로 v(t) = 4t - 4이고 a(t) = 4이다.",
    conditions=("Derivative(2*t**2 - 4*t, t, t).doit().subs(t, 5) = y",),
    answer_map=(("y", "4"),),
)
_RATIO = ShortcutProbe(
    standard_code=_C03,
    question_text="함수 f(x) = x^3 + 6x에 대하여 f'(a) = 2f'(1)을 만족시키는 양수 a의 값을 구하시오.",
    answer="2",
    explanation="f'(x) = 3x^2 + 6이므로 f'(1)의 값은 9이고 3a^2 + 6 = 18에서 a^2 = 4, a > 0이므로 a = 2이다.",
    conditions=("Derivative(x**3 + 6*x, x).doit().subs(x, a) = 18", "a > 0"),
    answer_map=(("a", "2"),),
)
_ROOTS = ShortcutProbe(
    standard_code=_C04,
    question_text=(
        "함수 f(x) = x^3 + ax^2 + bx - 8 (a, b는 상수)에 대하여 방정식 f'(x) = 0의 두 실근이 -4, 2일 때, "
        "상수 a의 값을 구하시오."
    ),
    answer="3",
    explanation="도함수는 f'(x) = 3x^2 + 2ax + b이고 두 근의 합 -2 = -2a/3이므로 a = 3이다.",
    conditions=("Derivative(x**3 + a*x**2 + (-24)*x - 8, x).doit().subs(x, -4) = 0",),
    answer_map=(("a", "3"),),
)
_LEVEL = ShortcutProbe(
    standard_code=_C09,
    question_text="방정식 x^3 - 3x + 2 = 0의 서로 다른 실근의 개수를 구하시오.",
    answer="2",
    explanation="f(x) = x^3 - 3x + 2라 하자. f'(x) = 3x^2 - 3 = 3(x + 1)(x - 1)이다.",
    conditions=("x**3 - 3*x + 2 = 0",),
    answer_kind="real_root_count",
)
#: 단답형 — 속도 0인 시각이 -1·3인데 발문에 범위가 없고 답 형식(실수)도 -1을 배제하지 않는다.
_REST = ShortcutProbe(
    standard_code=_C10,
    question_text=(
        "수직선 위를 움직이는 점 P의 시각 t에서의 위치가 x = t^3 - 3t^2 - 9t일 때, 점 P의 속도가 0이 되는 "
        "시각 t의 값을 구하시오."
    ),
    answer="3",
    explanation=(
        "속도 v(t)는 위치를 시각 t로 미분한 값이다. v(t) = 3t^2 - 6t - 9 = 3(t + 1)(t - 3)이므로 v(t) = 0에서 "
        "t = 3이다."
    ),
    conditions=("Derivative(t**3 - 3*t**2 - 9*t, t).doit().subs(t, s) = 0",),
    answer_map=(("s", "3"),),
    answer_format="실수",
)

_RED_HANDMADE: list[tuple[str, ShortcutProbe]] = [
    # M-link-extremum-point — 값 절: 연결 선지가 극값 후보 개수 '3'(절차 값 0이 아니다).
    (
        "M-link-extremum-point",
        dataclasses.replace(_POINT_MC, distractors=((2, EXTREMUM_POINT_KEBAB),)),
    ),
    # 판독 절: 계수 양수 삼차는 극점 x좌표 순서가 극값과 반대라 절차 값이 판독에 따라 갈린다.
    ("M-link-extremum-point", _AMBIGUOUS_MC),
    # 고전 절(개수 문항 아님): 극점의 x좌표가 아닌 선지 '3'에 연결.
    (
        "M-link-extremum-point",
        dataclasses.replace(_CLASSIC_MC, distractors=((3, EXTREMUM_POINT_KEBAB),)),
    ),
    # 읽기 절: 좌변이 상수인 꼴('0 = f(x)')은 생성기가 쓰지 않아 읽지 않는다 — 판정 불가를 결함으로 낸다.
    (
        "M-link-extremum-point",
        dataclasses.replace(
            _POINT_MC, conditions=("0 = 3*x**4 - 32*x**3 + 114*x**2 - 144*x + 41",)
        ),
    ),
    # 해설 절: 값은 맞지만 해설이 절차(x좌표를 극값으로 넣어 센 개수)를 보이지 않는다.
    (
        "M-link-extremum-point",
        dataclasses.replace(
            _POINT_MC,
            explanation=_W_EXPLANATION.replace(
                "극대·극소가 되는 점의 x좌표 1, 3, 4를 극값으로 잘못 넣으면 0이 그 값들보다 모두 작으므로 "
                "0개로 세게 된다. ",
                "",
            ),
        ),
    ),
    # E-motion-symbol-intro — a(t) 절: v(t)는 정의했지만 a(t)는 정의 없이 쓴다.
    ("E-motion-symbol-intro", _ACCEL),
    # '가속도는 …'의 '속도는'을 속도 정의로 읽지 않는다(뒤 lookbehind) — a(t)는 정의됐지만(가속도는 속도를
    # 미분한 값) v(t)는 정의가 없다. lookbehind가 없으면 '가속도는' 안의 '속도는 … 위치 … 미분한 값'을 v(t)
    # 정의로 오독한다(이 표본만 그 절을 지나간다 — a(t) 절은 통과한다).
    (
        "E-motion-symbol-intro",
        dataclasses.replace(
            _ACCEL,
            explanation=(
                "가속도는 속도를 시각 t로 미분한 값으로, 위치를 두 번 미분한 값이다. v(t) = 4t - 4이고 "
                "a(t) = 4이다."
            ),
        ),
    ),
    # T-ratio-shortcut — 비례 짐작 절만: f(x) = x^3 + 6x, f'(a) = 2f'(1)의 정답 2 = 2 × 1(계수 누락 √8 ·
    # 지수 유지 무리수).
    ("T-ratio-shortcut", _RATIO),
    # 지수 유지 절만 — 정답 칸에 지수 유지 경로의 값(2a^2 = 8 → 2)을 넣은 *합성 표본*이다. 자연스러운
    # 매개변수에서 지수 유지 경로만 정답과 겹치는 예는 찾지 못했다(정수 계수 삼차·이차 전수 탐색 0건) —
    # 절의 변별력만 본다(비례 짐작 4 · 계수 누락 4 ≠ 2).
    (
        "T-ratio-shortcut",
        ShortcutProbe(
            standard_code=_C03,
            question_text="함수 f(x) = x^2에 대하여 f'(a) = 4f'(1)을 만족시키는 양수 a의 값을 구하시오.",
            answer="2",
            explanation="f'(x) = 2x이다.",
            conditions=("Derivative(x**2, x).doit().subs(x, a) = 8", "a > 0"),
            answer_map=(("a", "2"),),
        ),
    ),
    # T-derivative-roots-coincidence — 미분하지 않은 식 절만: f(x) = x^3 + ax^2 + bx - 8(상수항이 있어 계수
    # 누락 경로 a = 2와 갈린다)의 f(-4) = f(2) = 0을 풀어도 정답 a = 3.
    ("T-derivative-roots-coincidence", _ROOTS),
    # 계수 누락 경로만: 상수항이 있는 f(x) = x^3 + ax^2 + bx + 2에서 두 근 ±3 — 계수 누락(x^2 + ax + b)은
    # a = 0으로 정답과 같고, 미분하지 않은 식은 f(±3) = 0에서 a = -2/9라 갈린다(근 옮겨 적기도 아님).
    (
        "T-derivative-roots-coincidence",
        dataclasses.replace(
            _ROOTS,
            question_text=(
                "함수 f(x) = x^3 + ax^2 + bx + 2 (a, b는 상수)에 대하여 방정식 f'(x) = 0의 두 실근이 "
                "-3, 3일 때, 상수 a의 값을 구하시오."
            ),
            answer="0",
            conditions=("Derivative(x**3 + a*x**2 + (-27)*x + 2, x).doit().subs(x, -3) = 0",),
            answer_map=(("a", "0"),),
        ),
    ),
    # T09-factored-level — 방정식 자체 절: x^3 - 3x + 2 = (x - 1)^2(x + 2)(상수항을 옮긴 x^3 - 3x는 중근 없음).
    ("T09-factored-level", _LEVEL),
    # U-extra-solution — 단답형 절: 답 형식(실수)이 구간 밖 근 -1을 배제하지 않는다.
    ("U-extra-solution", _REST),
    # V-count-interval의 구간 다름 절은 동결 원문을 고친 표본이라 `test_count_interval_differ_clause`가 본다.
]
_C743 = "c743fda0"


@pytest.mark.parametrize(
    ("rule", "probe"),
    _RED_HANDMADE,
    ids=[f"{r}-hand-{i}" for i, (r, _) in enumerate(_RED_HANDMADE)],
)
def test_round6_rule_flags_the_handmade_clause_defect(rule: str, probe: ShortcutProbe) -> None:
    assert rule in _round6(probe)


def test_count_interval_differ_clause(by_prefix: dict[str, dict[str, object]]) -> None:
    """V-count-interval 구간 다름 절 — 발문 (-4, 4)인데 검산이 닫힌 범위로 센다(RED), 같으면 GREEN.

    끝마다 따로 본다 — 한쪽 끝의 닫힘만 다른 검산도 다른 문제다(한 끝의 닫힘 판정만 빠져도 RED가 남지 않게).
    """
    eq = "6*x**2 - 4*x - 32 = 0"
    for bounds in (("x >= -4", "x <= 4"), ("x >= -4", "x < 4"), ("x > -4", "x <= 4")):
        closed = _fix(by_prefix[_C743], conditions=(eq, *bounds))
        assert "V-count-interval" in _round6(closed), bounds
    same = _fix(by_prefix[_C743], conditions=("6*x**2 - 4*x - 32 = 0", "x > -4", "x < 4"))
    assert "V-count-interval" not in _round6(same)


def _green_cases(by_prefix: dict[str, dict[str, object]]) -> list[tuple[str, ShortcutProbe]]:
    """(규칙, 그 결함만 고친 표본) — 원문 문항의 해당 필드만 교정했다(나머지는 원문 그대로)."""
    r = by_prefix
    return [
        # M0615 연결을 떼면(연결 없는 오답 선지는 결함이 아니다) 자기모순 사유가 사라진다.
        ("M-link-contradictory", _fix(r["bd6f889f"], distractors=())),
        # 6회차 처분 뒤 생성기 산출 그대로 — 절차 값 0 · 해설이 절차를 보인다.
        ("M-link-extremum-point", _POINT_MC),
        # 고전 형태 — 극점의 x좌표 -1에 연결하면 그 절차의 값이다.
        ("M-link-extremum-point", _CLASSIC_MC),
        # 두 곡선 꼴 — 해설처럼 상수항을 우변으로 넘긴 f(x) = k로 읽는다.
        ("M-link-extremum-point", _TWO_CURVES_MC),
        (
            "E-motion-symbol-intro",
            _fix(
                r["639e6fc9"],
                explanation=(
                    "속도 v(t)는 위치를 시각 t로 미분한 값이다. v(t) = -4t + 5이므로 -4t + 5 = -7에서 "
                    "t = 3이다."
                ),
            ),
        ),
        (
            "E-motion-symbol-intro",
            dataclasses.replace(
                _ACCEL,
                explanation=(
                    "속도는 위치를 시각 t로 미분한 값이므로 v(t) = 4t - 4이고, 가속도는 속도를 시각 t로 "
                    "미분한 값이므로 a(t) = 4이다."
                ),
            ),
        ),
        # '속도 v(t)는 위치 x의 도함수' 형태(5회차 멈춤 틀 관례)도 정의로 읽는다.
        (
            "E-motion-symbol-intro",
            dataclasses.replace(
                _ACCEL,
                explanation=(
                    "속도 v(t)는 위치 x를 시각 t로 미분한 도함수이고 v(t) = 4t - 4이다. 가속도 a(t)는 속도의 "
                    "도함수이므로 a(t) = 4이다."
                ),
            ),
        ),
        # f'가 원점을 지나지 않고(f(x) = x^2 + 2x) 정답 5가 비례 짐작 3·계수 누락 7·지수 유지 2와 다르다.
        (
            "T-ratio-shortcut",
            ShortcutProbe(
                standard_code=_C03,
                question_text=(
                    "함수 f(x) = x^2 + 2x에 대하여 f'(a) = 3f'(1)을 만족시키는 양수 a의 값을 구하시오."
                ),
                answer="5",
                explanation="f'(x) = 2x + 2이므로 2a + 2 = 12에서 a = 5이다.",
                conditions=("Derivative(x**2 + 2*x, x).doit().subs(x, a) = 12", "a > 0"),
                answer_map=(("a", "5"),),
            ),
        ),
        # 근 -4, 2(합 -2) — 정답 a = 3, 계수 누락·미분하지 않은 경로 a = 2, 발문의 근과도 다르다.
        (
            "T-derivative-roots-coincidence",
            _fix(
                r["07eefccb"],
                question_text=(
                    "함수 f(x) = x^3 + ax^2 + bx (a, b는 상수)에 대하여 방정식 f'(x) = 0의 두 실근이 -4, "
                    "2일 때, 상수 a의 값을 구하시오."
                ),
                answer="3",
                answer_map=(("a", "3"),),
            ),
        ),
        # 상수항을 옮긴 식 x^3 - 3x = x(x^2 - 3)에도, 방정식 x^3 - 3x + 1에도 중근 인수가 없다.
        (
            "T09-factored-level",
            dataclasses.replace(
                _LEVEL,
                question_text="방정식 x^3 - 3x + 1 = 0의 서로 다른 실근의 개수를 구하시오.",
                answer="3",
                conditions=("x**3 - 3*x + 1 = 0",),
            ),
        ),
        # 발문에 구간을 넣으면 구간 밖 근 -2가 발문 조건으로 배제된다(선지에 있어도 정답이 하나).
        (
            "U-extra-solution",
            _fix(
                r["bdc71cfe"],
                question_text=str(r["bdc71cfe"]["question_text"]).replace(
                    "c의 값은?", "c의 값은? (단, 0 < c < 4)"
                ),
            ),
        ),
        (
            "U-extra-solution",
            _fix(
                r["d524ac47"],
                question_text=str(r["d524ac47"]["question_text"]).replace(
                    "c의 값은?", "c의 값은? (단, 1 < c < 4)"
                ),
            ),
        ),
        # 객관식에서 구간 밖 근 -2가 선지에 없고 해설도 버리지 않으면 선지가 해를 가른다(규칙 그대로의 경계).
        (
            "U-extra-solution",
            _fix(
                r["d524ac47"],
                explanation=str(r["d524ac47"]["answer_explanation"]).replace(
                    "c = 8/3이고, -2는 열린구간에 속하지 않으므로 버린다.", "c = 8/3이다."
                ),
            ),
        ),
        # 답 형식이 자연수면 음수 근 -1은 답이 될 수 없다(해설도 버리지 않는다).
        ("U-extra-solution", dataclasses.replace(_REST, answer_format="자연수")),
        # '(단, t는 양수)'도 발문의 범위다(검산 미지수 s는 발문의 시각 t).
        (
            "U-extra-solution",
            dataclasses.replace(
                _REST,
                question_text=_REST.question_text.replace(
                    "값을 구하시오.", "값을 구하시오. (단, t는 양수)"
                ),
            ),
        ),
        # 서수('처음으로')가 근을 고른다 — 구간 밖 해가 아니라 선택 문항이다.
        ("U-extra-solution", probe_from_record(r["ed8cd073"])),
        # '열린구간 (a, b)에 오직 하나 존재'·'두 점 A, B 사이'도 발문의 범위로 읽는다.
        ("U-extra-solution", probe_from_record(r["8087d779"])),
        ("U-extra-solution", probe_from_record(r["c4283f23"])),
        (
            "V-count-interval",
            _fix(r[_C743], conditions=("6*x**2 - 4*x - 32 = 0", "x > -4", "x < 4")),
        ),
        (
            "V-count-interval",
            _fix(r["6782eb62"], conditions=("-6*x**2 + 4*x + 32 = 0", "x > -4", "x < 4")),
        ),
        (
            "V-count-interval",
            _fix(r["faac642f"], conditions=("2*t**3 - 15*t**2 + 36*t = 29", "t >= 0")),
        ),
        (
            "W-curve-subject",
            _fix(
                r["6fef75c7"],
                question_text="함수 f(x) = -x^4 + 4x^3 + 8x^2 + 3이 극대가 되는 x좌표 중 큰 값을 구하시오.",
            ),
        ),
    ]


def test_round6_corrected_forms_pass_their_rule(by_prefix: dict[str, dict[str, object]]) -> None:
    """규칙마다 *그 결함만 고친* 같은 문항은 그 규칙을 통과한다(규칙이 결함 표지가 아니라 문항 전체를 막지
    않는다는 대조). 다른 규칙 위반은 여기서 보지 않는다 — 원문의 다른 결함이 남아 있을 수 있다."""
    still = [
        (rule, i, sorted(_round6(probe)))
        for i, (rule, probe) in enumerate(_green_cases(by_prefix))
        if rule in _round6(probe)
    ]
    assert still == []


def test_every_round6_rule_has_red_and_green_controls(
    by_prefix: dict[str, dict[str, object]],
) -> None:
    red = {rule for rule, _ in _RED_IDS} | {rule for rule, _ in _RED_HANDMADE}
    green = {rule for rule, _ in _green_cases(by_prefix)}
    assert red == ROUND6_RULE_IDS
    assert green == ROUND6_RULE_IDS
    # 6회차 규칙은 RULE_IDS에서 7회차 첫 규칙 바로 앞까지의 연속 구간이고(회차 순서) 5회차와 겹치지 않는다.
    # 자격 측정 뒤 회차 규칙 전부가 투표 제외 집합이다.
    start = RULE_IDS.index("M-link-contradictory")
    end = RULE_IDS.index("T05-quadratic-slope")
    assert list(RULE_IDS[start:end]) == [r for r in RULE_IDS if r in ROUND6_RULE_IDS]
    assert not ROUND5_RULE_IDS & ROUND6_RULE_IDS
    assert not ROUND6_RULE_IDS & (ROUND7_RULE_IDS | ROUND8_RULE_IDS)
    assert POST_QUALIFICATION_RULE_IDS == (
        ROUND5_RULE_IDS | ROUND6_RULE_IDS | ROUND7_RULE_IDS | ROUND8_RULE_IDS
    )
    assert {"T-ratio-shortcut", "T-derivative-roots-coincidence", "T09-factored-level"} == (
        COINCIDENCE_RULE_IDS & ROUND6_RULE_IDS
    )


# ── '극값·극점 혼동' 절차 정의 · 운동 기호 정의 ─────────────────────────────
def test_extremum_point_count_returns_one_value_only_when_every_reading_agrees() -> None:
    w = 3 * _X**4 - 32 * _X**3 + 114 * _X**2 - 144 * _X + 41  # 극점 1(극소)·3(극대)·4(극소)
    assert extremum_point_count(w, _X, sympy.Integer(0)) == 0  # 0이 모든 x좌표보다 작다
    assert extremum_point_count(w, _X, sympy.Integer(1)) == 1  # 작은 '극솟값' 1과 같다
    assert extremum_point_count(w, _X, sympy.Integer(10)) == 2  # 모든 x좌표보다 크다
    # 3 < k < 4('극댓값' 3과 큰 '극솟값' 4 사이) — 순서를 지킨 규칙은 2, '사이'를 대칭으로 읽으면 4 — 모호.
    assert extremum_point_count(w, _X, sympy.Rational(7, 2)) is None
    # 계수 양수 삼차 — 극대 x좌표 -1 < 극소 x좌표 1(실제 극값과 순서가 반대): 사이에 든 k는 판독이 갈린다.
    cubic = _X**3 - 3 * _X + 1
    assert extremum_point_count(cubic, _X, sympy.Integer(0)) is None
    assert extremum_point_count(cubic, _X, sympy.Integer(5)) == 1  # 둘 다보다 크면 어느 판독도 1
    # 계수 음수 삼차 — 극소 x좌표 -1 < 극대 x좌표 1(순서 일치): 사이면 3, 같으면 2, 밖이면 1.
    negative = -(_X**3) + 3 * _X
    assert extremum_point_count(negative, _X, sympy.Integer(0)) == 3
    assert extremum_point_count(negative, _X, sympy.Integer(1)) == 2
    assert extremum_point_count(negative, _X, sympy.Integer(4)) == 1
    # 극점 x좌표가 무리수(x^3 - 6x)거나 부호가 바뀌지 않는 임계점(x^3)이면 절차 값을 정하지 않는다.
    assert extremum_point_count(_X**3 - 6 * _X, _X, sympy.Integer(0)) is None
    assert extremum_point_count(_X**3, _X, sympy.Integer(1)) is None
    assert extremum_point_count(cubic, _X, sympy.Rational(1, 2) + sympy.sqrt(2)) is None
    # 극점이 없으면(일차식 · 도함수의 실근 없음) 절차가 없다.
    assert extremum_point_count(2 * _X, _X, sympy.Integer(1)) is None
    assert extremum_point_count(_X**3 + _X, _X, sympy.Integer(1)) is None


_SHAPES = [
    pytest.param(_X**3 - 3 * _X, id="cubic-up"),
    pytest.param(-(_X**3) + 3 * _X, id="cubic-down"),
    pytest.param(3 * _X**4 - 4 * _X**3 - 12 * _X**2, id="w-quartic"),  # 극솟값 -5·-32, 극댓값 0
    pytest.param(_X**4 - 2 * _X**2, id="w-symmetric"),  # 두 극솟값이 같다(-1)
    pytest.param(-3 * _X**4 + 4 * _X**3 + 12 * _X**2, id="m-quartic"),
    pytest.param(-(_X**4) + 2 * _X**2, id="m-symmetric"),
    pytest.param(_X**4 - 4 * _X, id="single-min"),
    pytest.param(-(_X**4) + 4 * _X, id="single-max"),
]


@pytest.mark.parametrize("function", _SHAPES)
def test_comparison_rule_with_true_extrema_counts_the_real_roots(function: sympy.Expr) -> None:
    """비교 규칙(판독 B·C)에 *실제 극값*을 넣으면 f(x) = k의 서로 다른 실근 수와 같다 — 조항 하나가 빠지거나
    틀리면 어떤 k에서 SymPy 근 개수와 어긋난다(모든 영역·경계값 k를 훑는다). 혼동 절차는 같은 규칙에 x좌표를
    넣는 것이므로, 규칙 자체가 옳다는 것이 절차 값의 전제다."""
    from whymath_backend.l3.equivalent.p3_diff_shortcut_guard import (
        _extremum_points,
        _verbal_counts,
    )

    points = _extremum_points(function, _X)
    assert points is not None
    values = [function.subs(_X, x) for x, _ in points]
    marks = sorted(set(values))
    levels = {marks[0] - 1, marks[-1] + 1, *marks}
    levels |= {(a + b) / 2 for a, b in zip(marks, marks[1:], strict=False)}
    for level in sorted(levels):
        actual = len(set(sympy.real_roots(sympy.Poly(function - level, _X))))
        for symmetric in (False, True):
            assert _verbal_counts(points, values, level, symmetric=symmetric) == {actual}, (
                function,
                level,
                symmetric,
            )


def test_undefined_motion_symbols_reads_definition_order() -> None:
    assert undefined_motion_symbols("v(t) = 2t이므로 속도는 위치를 미분한 값이다.") == ("v(t)",)
    assert undefined_motion_symbols("속도는 위치를 시각 t로 미분한 값이므로 v(t) = 2t이다.") == ()
    assert undefined_motion_symbols("위치의 그래프를 본다.") == ()
    assert undefined_motion_symbols(
        "속도 v(t)는 위치를 시각 t로 미분한 값이다. v(t) = 2t, a(t) = 2이다."
    ) == ("a(t)",)


# ── 원인 6: 개수 문항 검산의 구간 — 구판 검산 RED · 새 검산 GREEN ───────────
def _count_record(conditions: str | list[str], answer: str) -> dict[str, object]:
    """'닫힌구간 [1, 4]에서 평균값 정리를 만족시키는 c의 개수'(f'(x) = 11의 근 -2·8/3 — 하나만 구간 안)."""
    return {
        "slug": "mvt-count-one-outside",
        "answer": answer,
        "verify": {"conditions": conditions, "answer_map": {}, "answer_kind": "real_root_count"},
    }


def test_count_verify_with_an_outside_root_needs_the_interval() -> None:
    """구간 밖 근이 하나 생기는 매개변수 — 구판 검산(방정식 하나)은 실수 전체의 근 2개를 세어 정답 1을
    거부하고(RED), 새 검산(방정식 + 열린구간)은 정답 1을 받는다(GREEN). 판정기도 구판을 거부한다."""
    old = reverify_corpus([_count_record("3*x**2 - 2*x - 16 = 0", "1")], use_fuzz=False)
    assert old.failed == 1, old
    new_conditions = ["3*x**2 - 2*x - 16 = 0", "x > 1", "x < 4"]
    new = reverify_corpus([_count_record(new_conditions, "1")], use_fuzz=False)
    assert new.failed == 0 and new.passed == 1, new
    wrong = reverify_corpus([_count_record(new_conditions, "2")], use_fuzz=False)
    assert wrong.failed == 1, wrong  # 범위 안에서 세면 2는 오답이다
    question = (
        "함수 f(x) = x^3 - x^2 - 5x + 3에 대하여 닫힌구간 [1, 4]에서 평균값 정리를 만족시키는 실수 c의 "
        "개수를 구하시오."
    )
    probe = ShortcutProbe(
        standard_code=_C06,
        question_text=question,
        answer="1",
        explanation="f'(x) = 3x^2 - 2x - 5이다.",
        conditions=("3*x**2 - 2*x - 16 = 0",),
        answer_kind="real_root_count",
    )
    assert "V-count-interval" in _round6(probe)
    assert "V-count-interval" not in _round6(
        dataclasses.replace(probe, conditions=tuple(new_conditions))
    )


# ── ⑤ 매개변수 거부 조건 ───────────────────────────────────────────────────
def _ratio_item(n: int, k: int, a: int) -> DiffItem:
    """02-03 배수 틀 — f(x) = x^n의 f'(a) = k·f'(1)(계수 n이 양변에서 약분된다)."""
    function, value, shown = f"x**{n}", k * n, f"x^{n}"
    return DiffItem(
        slot="applied",
        frame_id="test-ratio",
        question_text=(
            f"함수 f(x) = {shown}에 대하여 f'(a) = {k}f'(1)을 만족시키는 양수 a의 값을 구하시오."
        ),
        answer_text=str(a),
        explanation="f'(x)를 구해 비교한다.",
        conditions=(f"Derivative({function}, x).doit().subs(x, a) = {value}", "a > 0"),
        answer_map=(("a", str(a)),),
        problem_type_code="ptype.solve-for-unknown",
        answer_format=AnswerFormat.자연수,
    )


def test_round_robin_skips_round6_coincident_parameters_only_when_asked() -> None:
    """f(x) = x^2의 f'(a) = 3f'(1)(a = 3)은 비례 짐작·계수 누락과 겹친다 — 거부 조건이 그 파라미터만 건너뛴다.

    대조군: standard_code 없이 부르면(거부 조건 미적용) 그 파라미터가 그대로 나온다.
    """
    coincident = _ratio_item(2, 3, 3)
    honest = DiffItem(
        slot="applied",
        frame_id="test-ratio",
        question_text="함수 f(x) = x^2 + 2x에 대하여 f'(a) = 3f'(1)을 만족시키는 양수 a의 값을 구하시오.",
        answer_text="5",
        explanation="f'(x) = 2x + 2이다.",
        conditions=("Derivative(x**2 + 2*x, x).doit().subs(x, a) = 12", "a > 0"),
        answer_map=(("a", "5"),),
        problem_type_code="ptype.solve-for-unknown",
        answer_format=AnswerFormat.자연수,
    )
    assert {v.rule for v in parameter_coincidences(probe_of(_C03, coincident))} == {
        "T-ratio-shortcut"
    }
    assert parameter_coincidences(probe_of(_C03, honest)) == []
    by_key = {1: coincident, 2: honest}
    frames = [Frame("test-ratio", ((1,), (2,)), lambda p: by_key[int(str(p[0]))])]
    assert [i.answer_text for i in round_robin_items(frames, 2, standard_code=_C03)] == ["5"]
    assert [i.answer_text for i in round_robin_items(frames, 2)] == ["3", "5"]
