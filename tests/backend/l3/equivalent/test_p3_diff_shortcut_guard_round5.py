"""P3-03 미분 은행 — 5회차 은행 감사(2026-10-08) 결함 원인의 기계 판정 규칙 회귀 테스트(hermetic·LLM 0).

5회차 감사(`docs/data/p3_calculus1_diff_audit/bank_audit/` — LLM 판정자 2명 + 처분 `disposition.json`)는
4회차 규칙으로 빌드된 은행에서 결함 68건을 원인 14종으로 찾았다. 그 원인 중 *문면·검산 조건·선지 귀속에서
기계로 읽히는 것*을 판정기 `p3_diff_shortcut_guard`의 5회차 규칙(`ROUND5_RULE_IDS`)으로 옮겼다. 이 파일은
다섯 가지를 못 박는다.

① **재현율** — 감사 동결 원문(as-found)에서 결함 68건 전부를 *그 원인에 대응하는 규칙군*이 잡는다(원인별
   건수 동결). 규칙의 절을 지우면(뮤테이션) 이 단언이 깨진다.
② **변별** — 그 은행은 4회차 규칙으로 빌드됐으므로 5회차 이전 규칙만으로는 504건 중 0건을 잡는다(새 규칙이
   실제로 일했다는 증거).
③ **과잉 거부** — 결함이 아닌 436건 중 5회차 규칙이 거부하는 것은 고정된 48건뿐이다(규칙별 건수 동결).
   전부 *같은 틀의 같은 형태*라 판정자가 표본에서 못 본 것으로 판단했다 — 틀 교정은 그 형태 전부를 바꿨다.
   집합이 바뀌면 RED(조용히 늘거나 줄지 않는다).
④ 규칙마다 결함 문면(RED — 동결 원문 그대로)과 그 결함만 고친 문면(GREEN — 같은 문항의 최소 교정) 대조군이
   있다. 절이 둘 이상인 규칙은 절마다 RED를 둔다(02-06/02-10 · 중점/끝점 · 위치 축 · 미분계수 축 등).
⑤ 매개변수 거부 조건(`COINCIDENCE_RULE_IDS`)이 생성기의 라운드로빈에서 실제로 파라미터를 건너뛴다.

규칙은 판정기 한 곳에만 있다(생성기 빌드 `_validate_slot`이 fail-loud로, 라운드로빈이 매개변수 거부로 같은
판정을 쓴다).
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
    ROUND5_RULE_IDS,
    ROUND6_RULE_IDS,
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
_AUDIT = _ROOT / "docs" / "data" / "p3_calculus1_diff_audit" / "bank_audit"

#: 원인 → 그 원인을 잡아야 하는 규칙군(하나 이상 걸리면 잡은 것).
_FAMILY: dict[str, frozenset[str]] = {
    "이차 평균값 정리 = 구간 중점": frozenset({"T-quadratic-mean-value", "T-midpoint-answer"}),
    "이차 롤/속도 0 = 꼭짓점": frozenset(
        {"T10-quadratic-rest", "T-quadratic-mean-value", "T-midpoint-answer"}
    ),
    "가속도 해설 v(t) 단계 누락": frozenset({"E-velocity-before-acceleration"}),
    "극값을 발문이 알려 줌(실근 개수)": frozenset({"T09-given-extremum-values"}),
    "발문–검산 불일치(verify가 다른 문제)": frozenset({"V05-touch-verify-mismatch"}),
    "발문이 답을 알려 줌": frozenset(
        {
            "T06-roots-given",
            "T-midpoint-answer",
            "T-integer-pinned-by-interval",
            "T05-given-coordinate",
        }
    ),
    "이차 접선 = 판별식·중근": frozenset({"T05-quadratic-tangent-constant"}),
    "'극대' 문항에 임계점=극값 오개념 연결": frozenset({"M-link-procedure"}),
    "해설 문장 결함(비문·용어)": frozenset({"E-run-on", "E-term-rolle"}),
    "M0677 오개념 설명 손상·절차 미기술": frozenset({"M-link-undescribed"}),
    "해설 a=0 배제 누락": frozenset({"E-excluded-root"}),
    "오답 경로가 정답과 일치(변별 없음)": frozenset(
        {"T-function-value-path", "T-coefficient-reading", "T-constant-derivative"}
    ),
    "해설 '극값을 가지므로' 전제 역전": frozenset({"E-premise-reversal"}),
    "해설 정의 없는 k": frozenset({"E-undefined-letter"}),
}

#: 원인별 결함 건수(처분 `disposition.json`의 cause_counts와 같다 — 합 68).
_CAUSE_COUNTS: dict[str, int] = {
    "이차 평균값 정리 = 구간 중점": 18,
    "M0677 오개념 설명 손상·절차 미기술": 12,
    "이차 롤/속도 0 = 꼭짓점": 6,
    "발문이 답을 알려 줌": 6,
    "오답 경로가 정답과 일치(변별 없음)": 6,
    "가속도 해설 v(t) 단계 누락": 5,
    "이차 접선 = 판별식·중근": 3,
    "해설 정의 없는 k": 3,
    "극값을 발문이 알려 줌(실근 개수)": 2,
    "'극대' 문항에 임계점=극값 오개념 연결": 2,
    "해설 '극값을 가지므로' 전제 역전": 2,
    "발문–검산 불일치(verify가 다른 문제)": 1,
    "해설 문장 결함(비문·용어)": 1,
    "해설 a=0 배제 누락": 1,
}

#: 결함이 아닌 436건 중 5회차 규칙이 거부하는 문항(id 앞 8자리). 전부 결함 문항과 *같은 틀의 같은 형태*다 —
#: 이차 평균값 정리·이차 접선 상수·차수로 센 교점 개수·M0677 귀속 없는 같은 개수 틀·가속도 해설의 v(t)
#: 누락·롤 용어·비문 등. 판정자 2명은 표본 판정이라 같은 형태를 모두 짚지 않았다(결함 원인 처분이 '틀'
#: 단위인 이유). 틀 교정은 이 48건의 형태도 전부 바꿨다(지금 은행 위반 0건).
_KNOWN_CLEAN_REJECTED: frozenset[str] = frozenset(
    {
        "118f13f9", "12c8edb4", "1e1575e3", "1e6b101e", "250cd7d1", "2e32efa5", "31433865",
        "351942f2", "395738d5", "3ae90b49", "3f2a3ce1", "41182573", "45f3e98c", "490def28",
        "5a5033fc", "616b1e9a", "6d1ba559", "77a4057b", "79c590e4", "807830bd", "858eea39",
        "866c43bb", "8b7abd0f", "8c9b02e1", "8de9e24f", "96631026", "aa3cf1b8", "aa7033a1",
        "b11a2a8a", "b154ffa8", "b728af46", "b911df57", "b92da0d6", "c0d4ea53", "c181a084",
        "c3d82987", "d70fc97c", "d771d3d8", "e2b88365", "e4aace79", "e8e159b7", "eeb3d061",
        "ef2c5d27", "ef5462ef", "fb83d7d0", "fcf0b537", "ff555ffe", "fff9adc1",
    }
)  # fmt: skip

#: 위 48건의 규칙별 거부 건수(한 문항이 여러 규칙에 걸릴 수 있다).
_KNOWN_CLEAN_RULE_COUNTS: dict[str, int] = {
    "T09-degree-count": 10,
    "T-function-value-path": 8,
    "T05-quadratic-tangent-constant": 5,
    "T-coefficient-reading": 5,
    "T-midpoint-answer": 5,
    "T-quadratic-mean-value": 5,
    "E-run-on": 5,
    "E-term-rolle": 5,
    "E-velocity-before-acceleration": 5,
    "T09-given-extremum-values": 4,
    "E-excluded-root": 2,
    "E-y-axis-zero": 2,
    "V05-touch-verify-mismatch": 1,
    "T09-critical-count": 1,
    "E-rest-meaning": 1,
    "E-undefined-letter": 1,
    "T10-quadratic-rest": 1,
}


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _round5(probe: ShortcutProbe) -> set[str]:
    return {v.rule for v in shortcut_violations(probe)} & ROUND5_RULE_IDS


@pytest.fixture(scope="module")
def audited() -> dict[str, dict[str, object]]:
    return {str(r["problem_id"]): r for r in _jsonl(_AUDIT / "audited_bank.jsonl")}


@pytest.fixture(scope="module")
def causes() -> dict[str, str]:
    raw = json.loads((_AUDIT / "disposition.json").read_text(encoding="utf-8"))
    return {str(it["problem_id"]): str(it["cause"]) for it in raw["items"]}


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
    assert sum(_CAUSE_COUNTS.values()) == 68
    assert set(_FAMILY) == set(_CAUSE_COUNTS)
    assert set().union(*_FAMILY.values()) <= ROUND5_RULE_IDS


def test_round5_defects_are_caught_by_the_matching_rule_family(
    audited: dict[str, dict[str, object]], causes: dict[str, str]
) -> None:
    missed = {
        cause: sorted(
            pid[:8]
            for pid, c in causes.items()
            if c == cause and not (_round5(probe_from_record(audited[pid])) & family)
        )
        for cause, family in _FAMILY.items()
    }
    assert missed == {cause: [] for cause in _FAMILY}


# ── ② 변별 ─────────────────────────────────────────────────────────────────
def test_round5_bank_passes_every_earlier_rule(audited: dict[str, dict[str, object]]) -> None:
    """감사 은행은 4회차 규칙으로 빌드됐다 — 5회차 이전 규칙은 504건 중 0건을 잡는다.

    '이전 규칙'은 자격 측정 뒤에 더한 회차 규칙 전부(5·6회차 — `POST_QUALIFICATION_RULE_IDS`)를 뺀
    집합이다(6회차 규칙이 이 은행에서 거부하는 문항은 6회차 동결 `…_round6.py`가 따로 본다).
    """
    earlier = [
        pid[:8]
        for pid, r in audited.items()
        if {v.rule for v in shortcut_violations(probe_from_record(r))} - POST_QUALIFICATION_RULE_IDS
    ]
    assert earlier == []


# ── ③ 과잉 거부 ────────────────────────────────────────────────────────────
@pytest.mark.corpus_authoring
def test_round5_clean_over_rejection_is_the_frozen_known_set(
    audited: dict[str, dict[str, object]], causes: dict[str, str]
) -> None:
    clean = [pid for pid in audited if pid not in causes]
    assert len(clean) == 436
    rejected = {pid[:8]: _round5(probe_from_record(audited[pid])) for pid in clean}
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
    ("T-quadratic-mean-value", "ee393142"),  # 02-06 c를 묻는 형 — 미분 대상이 이차
    ("T-quadratic-mean-value", "033597a2"),  # 02-06 개수형 — f'(x) = 평균변화율이 일차
    ("T-quadratic-mean-value", "4eb43c2c"),  # 02-10 평균속도 = 순간속도 — 위치가 이차
    ("T10-quadratic-rest", "106fff4b"),
    ("T-midpoint-answer", "ee393142"),  # 정답 = 구간의 중점
    ("T-midpoint-answer", "1ebb69fb"),  # 끝점 미지수형 — 정답 = 2c - 고정 끝점
    ("T-integer-pinned-by-interval", "4eb43c2c"),
    ("T06-roots-given", "327a1b94"),
    ("T-function-value-path", "63407aa1"),
    ("T-coefficient-reading", "953ef7a0"),
    ("T-constant-derivative", "8a11d456"),
    ("T09-degree-count", "48e20b23"),
    ("T09-critical-count", "2359c043"),
    ("T09-given-extremum-values", "2359c043"),
    ("T05-quadratic-tangent-constant", "2fd9fad4"),
    ("T05-given-coordinate", "2d14ff84"),
    ("M-link-procedure", "38745ca2"),
    ("M-link-undescribed", "48e20b23"),
    ("E-premise-reversal", "b21b1689"),
    ("E-undefined-letter", "106fff4b"),  # 운동 기호 v — '속도'를 말하지 않는다
    ("E-undefined-letter", "e54f775f"),  # 정의 없는 k
    ("E-excluded-root", "5664f0d4"),
    ("E-velocity-before-acceleration", "1bdcda49"),
    ("E-rest-meaning", "106fff4b"),
    ("E-y-axis-zero", "953ef7a0"),
    ("E-run-on", "44e7281a"),
    ("E-term-rolle", "44e7281a"),
    ("V05-touch-verify-mismatch", "284122b4"),
]


@pytest.mark.parametrize(("rule", "pid"), _RED_IDS, ids=[f"{r}-{p}" for r, p in _RED_IDS])
def test_round5_rule_flags_the_as_found_defect(
    rule: str, pid: str, by_prefix: dict[str, dict[str, object]]
) -> None:
    assert rule in _round5(probe_from_record(by_prefix[pid]))


_C05 = "[12미적Ⅰ-02-05]"

#: 원문에 없는 절의 RED — 손으로 만든 결함 문면(같은 결함의 다른 표면형).
_RED_HANDMADE: list[tuple[str, ShortcutProbe]] = [
    # V05의 접점 고정 y절편 형태 — 기울기만 같은 다른 접선까지 담는 판별식(구판 r3 · k의 근 둘)과 발문에
    # 없는 보호 조건으로 둘째 근을 버리는 검산. 판정기는 보호 조건을 읽지 않으므로 RED.
    (
        "V05-touch-verify-mismatch",
        ShortcutProbe(
            standard_code=_C05,
            question_text="곡선 y = x^3 - 2x^2 + 4 위의 점 (2, 4)에서의 접선의 y절편을 구하시오.",
            answer="-4",
            explanation="도함수는 y' = 3x^2 - 4x이므로 기울기는 4이고, 접선은 y = 4x - 4이다.",
            conditions=("-27*k**2 + 40*k + 592 = 0", "k < 5"),
            answer_map=(("k", "-4"),),
        ),
    ),
    # 곡선의 상수 c가 미지수인 형태(구판 a4 · c의 근 둘).
    (
        "V05-touch-verify-mismatch",
        ShortcutProbe(
            standard_code=_C05,
            question_text=(
                "곡선 y = x^3 + 2x^2 - 4x + c (c는 상수) 위의 x좌표가 4인 점에서의 접선의 y절편이 "
                "-165일 때, c의 값을 구하시오."
            ),
            answer="-5",
            explanation="도함수는 y' = 3x^2 + 4x - 4이므로 x = 4에서의 접선의 기울기는 60이다.",
            conditions=("-27*c**2 - 11246*c - 55555 = 0", "c > -100"),
            answer_map=(("c", "-5"),),
        ),
    ),
]


_C06, _C09 = "[12미적Ⅰ-02-06]", "[12미적Ⅰ-02-09]"
#: 02-09 개수 객관식 — x^3 - 3x + 3 = 0(실근 1개 · 차수 3 · 임계점 2개). 선지 '1'·'2'·'3'·'4'.
_COUNT_MC = ShortcutProbe(
    standard_code=_C09,
    question_text="방정식 x^3 - 3x + 3 = 0의 서로 다른 실근의 개수로 옳은 것은?",
    answer="1",
    explanation="f(x) = x^3 - 3x + 3이라 하자. f'(x) = 3x^2 - 3 = 3(x + 1)(x - 1)이다.",
    choices=("1", "2", "3", "4"),
    conditions=("x**3 - 3*x + 3 = 0",),
    answer_kind="real_root_count",
)
#: 02-06 객관식 — 롤의 정리처럼 f'(c) = 0을 푼 값(-2/3)이 M0674의 절차 값이다.
_ROLLE_MC = ShortcutProbe(
    standard_code=_C06,
    question_text=(
        "함수 f(x) = x^3 - 2x^2 - 4x + 2에 대하여 곡선 y = f(x) 위의 두 점 A(-3, -31), B(0, 2) 사이의 "
        "곡선 위에서 직선 AB와 평행한 접선을 갖는 점의 x좌표는?"
    ),
    answer="-5/3",
    explanation="f'(x) = 3x^2 - 4x - 4이다.",
    choices=("-3", "-5/3", "-2/3", "3"),
    conditions=(
        "Derivative(x**3 - 2*x**2 - 4*x + 2, x).doit().subs(x, c) = ((2) - (-31))/((0) - (-3))",
        "c > -3",
        "c < 0",
    ),
    answer_map=(("c", "-5/3"),),
)
_RED_HANDMADE += [
    # M0615(차수만큼 근이 있다)을 차수 3이 아닌 선지 '2'에 연결 — 그 절차로 나오는 값이 아니다.
    ("M-link-procedure", dataclasses.replace(_COUNT_MC, distractors=((1, "M0615"),))),
    # M0674(롤의 정리처럼 f'(c) = 0을 푼다)를 f'(c) = 0의 근이 아닌 선지 '-3'에 연결.
    ("M-link-procedure", dataclasses.replace(_ROLLE_MC, distractors=((0, "M0674"),))),
]


@pytest.mark.parametrize(
    ("rule", "probe"),
    _RED_HANDMADE,
    ids=[f"{r}-hand-{i}" for i, (r, _) in enumerate(_RED_HANDMADE)],
)
def test_round5_rule_flags_the_handmade_clause_defect(rule: str, probe: ShortcutProbe) -> None:
    assert rule in _round5(probe)


def _green_cases(by_prefix: dict[str, dict[str, object]]) -> list[tuple[str, ShortcutProbe]]:
    """(규칙, 그 결함만 고친 표본) — 원문 문항의 해당 필드만 교정했다(나머지는 원문 그대로)."""
    r = by_prefix
    return [
        (
            "T-quadratic-mean-value",
            _fix(
                r["ee393142"],
                question_text=(
                    "함수 f(x) = x^3 - 3x에 대하여 닫힌구간 [0, 3]에서 평균값 정리를 만족시키는 상수 c의 "
                    "값을 구하시오. (단, 0 < c < 3)"
                ),
                conditions=(
                    "Derivative(x**3 - 3*x, x).doit().subs(x, c) = ((18) - (0))/((3) - (0))",
                    "c > 0",
                    "c < 3",
                ),
                answer="sqrt(3)",
                answer_map=(("c", "sqrt(3)"),),
            ),
        ),
        (
            "T-quadratic-mean-value",
            _fix(
                r["033597a2"],
                question_text=(
                    "곡선 y = x^3 - 2x^2 - 4x + 2 위의 두 점 A(-3, -31), B(0, 2)에 대하여, -3 < x < 0인 "
                    "범위에서 접선이 직선 AB와 평행한 점의 개수를 구하시오."
                ),
                conditions=("3*x**2 - 4*x - 15 = 0",),
            ),
        ),
        (
            "T-quadratic-mean-value",
            _fix(
                r["4eb43c2c"],
                question_text=(
                    "수직선 위를 움직이는 점 P의 시각 t에서의 위치가 x = t^3 - 3t^2 + 5일 때, t = 0에서 "
                    "t = 3까지의 평균속도와 순간속도가 같아지는 시각 t (0 < t < 3)를 구하시오."
                ),
                conditions=(
                    "Derivative(t**3 - 3*t**2 + 5, t).doit().subs(t, s) = 0",
                    "s > 0",
                    "s < 3",
                ),
                answer="2",
                answer_map=(("s", "2"),),
            ),
        ),
        (
            "T10-quadratic-rest",
            _fix(
                r["106fff4b"],
                question_text=(
                    "수직선 위를 움직이는 점 P의 시각 t에서의 위치가 x = t^3 - 6t^2 + 9t일 때, 점 P가 "
                    "t > 2에서 순간적으로 멈추는 시각 t를 구하시오."
                ),
                conditions=(
                    "Derivative(t**3 - 6*t**2 + 9*t, t).doit().subs(t, s) = 0",
                    "s > 2",
                ),
            ),
        ),
        # 중점 절 — 정답이 구간의 중점이 아니다(같은 문항의 답만 바꾼 최소 대조).
        ("T-midpoint-answer", _fix(r["ee393142"], answer="7/2", answer_map=(("c", "7/2"),))),
        # 끝점 절 — 정답이 2c - 고정 끝점(= 5)이 아니다.
        ("T-midpoint-answer", _fix(r["1ebb69fb"], answer="6", answer_map=(("k", "6"),))),
        (
            "T-integer-pinned-by-interval",
            _fix(
                r["4eb43c2c"],
                question_text=(
                    "수직선 위를 움직이는 점 P의 시각 t에서의 위치가 x = 2t^2 - 5t + 5일 때, t = 2에서 "
                    "t = 4까지의 평균속도와 순간속도가 같아지는 시각 t (1 < t < 5)를 구하시오."
                ),
                conditions=(
                    "Derivative(2*t**2 - 5*t + 5, t).doit().subs(t, s) = 7",
                    "s > 1",
                    "s < 5",
                ),
            ),
        ),
        (
            "T06-roots-given",
            _fix(
                r["327a1b94"],
                question_text=(
                    "함수 f(x) = x^3 - 4x^2 + 2x - 1에 대하여 f'(x) = (f(2) - f(-3))/(2 - (-3))을 "
                    "만족시키는 실수 x는 두 개이다. 이 중 열린구간 (-3, 2)에 속하는 것을 c라 할 때, "
                    "c의 값을 구하시오."
                ),
            ),
        ),
        # 함숫값 경로 f(1) = 4(1 + a)가 미분계수 경로 2a + 10과 다른 값을 낸다(16 → 20).
        (
            "T-function-value-path",
            _fix(
                r["63407aa1"],
                question_text="함수 f(x) = (x^2 + 3)(x^2 + a)에 대하여 f'(1)의 값이 20일 때, 상수 a의 값을 구하시오.",
                conditions=("Derivative((x**2 + 3)*(x**2 + a), x).doit().subs(x, 1) = 20",),
                answer="5",
                answer_map=(("a", "5"),),
            ),
        ),
        (
            "T-coefficient-reading",
            _fix(
                r["953ef7a0"],
                question_text="곡선 y = x^2 + 2x + 4 위의 x좌표가 1인 점에서의 접선의 기울기를 구하시오.",
                conditions=("Derivative(x**2 + 2*x + 4, x).doit().subs(x, 1) = y",),
                answer="4",
                answer_map=(("y", "4"),),
            ),
        ),
        (
            "T-constant-derivative",
            _fix(
                r["8a11d456"],
                question_text=(
                    "두 함수 f(x) = -2x^2 + x - 2, g(x) = -2x^2 + 3x에 대하여 f'(2) - g'(2)의 값을 "
                    "구하시오."
                ),
                conditions=(
                    "Derivative((-2*x**2 + x - 2) - (-2*x**2 + 3*x), x).doit().subs(x, 2) = y",
                ),
                answer="-2",
                answer_map=(("y", "-2"),),
            ),
        ),
        # 차수 세기 — 정답(실근 2개)이 방정식의 차수 4와 다르다.
        (
            "T09-degree-count",
            _fix(
                r["48e20b23"],
                question_text="두 곡선 y = 3x^4 + 4x^3, y = 12x^2 + 3의 교점의 개수로 옳은 것은?",
                conditions=("3*x**4 + 4*x**3 = 12*x**2 + 3",),
                answer="2",
            ),
        ),
        # 임계점 세기 — 정답(실근 3개)이 f'(x) = 0의 실근 개수 2와 다르다.
        (
            "T09-critical-count",
            _fix(r["2359c043"], conditions=("4*x**3 - 6*x**2 - 1 = -2",), answer="3"),
        ),
        (
            "T09-given-extremum-values",
            _fix(
                r["2359c043"],
                question_text="방정식 4x^3 - 6x^2 - 1 = -3의 서로 다른 실근의 개수를 구하시오.",
            ),
        ),
        (
            "T05-quadratic-tangent-constant",
            _fix(
                r["2fd9fad4"],
                question_text=(
                    "곡선 y = x^3 + 2x^2 - 4x + c (c는 상수) 위의 x좌표가 4인 점에서의 접선의 y절편이 "
                    "-165일 때, c의 값을 구하시오."
                ),
                conditions=("-c - 5 = 0",),
                answer="-5",
                answer_map=(("c", "-5"),),
            ),
        ),
        # 접점 (2, -18)의 y좌표와 정답 3이 다르다.
        (
            "T05-given-coordinate",
            _fix(
                r["2d14ff84"],
                question_text=(
                    "곡선 y = -x^3 - 2x^2 - x 위의 점 (2, -18)에서의 접선의 방정식을 y = mx + n이라 할 때, "
                    "m + n의 값을 구하시오."
                ),
                conditions=("(-21) + (24) = y",),
                answer="3",
                answer_map=(("y", "3"),),
            ),
        ),
        # '극값을 갖는 점'을 묻는다 — 임계점=극값 오개념(0)이 묻는 대상의 오답 경로가 된다.
        (
            "M-link-procedure",
            _fix(
                r["38745ca2"],
                question_text=(
                    "사차함수 f(x) = -2x^4 - 16x^3 + 4의 그래프 위의 점 (a, f(a))에서 함수 f(x)가 극값을 "
                    "가질 때, 이 점의 x좌표 a의 값은?"
                ),
            ),
        ),
        # 절차가 적힌 오개념에 귀속하지 않으면(연결 해제) 판정 불가 사유가 사라진다.
        ("M-link-undescribed", _fix(r["48e20b23"], distractors=())),
        (
            "E-premise-reversal",
            _fix(
                r["b21b1689"],
                explanation=str(r["b21b1689"]["answer_explanation"]).replace(
                    "x = 2에서 극값을 가지므로", "방정식 f'(x) = 0의 한 근이 x = 2이므로"
                ),
            ),
        ),
        (
            "E-undefined-letter",
            _fix(
                r["106fff4b"],
                explanation="속도 v(t)는 위치 x의 도함수이고 v(t) = -2t + 6 = 0에서 t는 3이다.",
            ),
        ),
        (
            "E-undefined-letter",
            _fix(
                r["e54f775f"],
                explanation="구하는 값을 k라 하자. " + str(r["e54f775f"]["answer_explanation"]),
            ),
        ),
        (
            "E-excluded-root",
            _fix(
                r["5664f0d4"],
                explanation=(
                    "f'(a)의 값은 9a^8이고 f(a)의 값은 a^9이므로 9a^8 = a^9, 즉 a^8(a - 9) = 0에서 "
                    "a = 0 또는 a = 9이다. a는 0이 아니므로 a = 9이다."
                ),
            ),
        ),
        (
            "E-velocity-before-acceleration",
            _fix(
                r["1bdcda49"],
                explanation=(
                    "속도는 v(t) = -3t^2 - 12t + 4이고 가속도는 속도를 시각 t로 미분한 값이다. "
                    "a(t) = -6t - 12이므로 t = 3일 때의 가속도는 -30이다."
                ),
            ),
        ),
        (
            "E-rest-meaning",
            _fix(
                r["106fff4b"],
                explanation=(
                    "속도 v(t)는 위치 x의 도함수이고, 점 P가 멈추는 순간 속도가 0이다. "
                    "v(t) = -2t + 6 = 0에서 t는 3이다."
                ),
            ),
        ),
        (
            "E-y-axis-zero",
            _fix(
                r["953ef7a0"],
                explanation=(
                    "y축 위의 점의 x좌표는 0이다. 접선의 기울기는 접점에서의 미분계수이다. "
                    "도함수는 2x + 2이므로 x = 0일 때 기울기는 2이다."
                ),
            ),
        ),
        (
            "E-run-on",
            _fix(
                r["44e7281a"],
                explanation=str(r["44e7281a"]["answer_explanation"]).replace(
                    "롤의 정리의 결론인데, 롤의 정리는",
                    "롤의 정리를 적용할 때 구하는 값이다. 롤의 정리는",
                ),
            ),
        ),
        (
            "E-term-rolle",
            _fix(
                r["44e7281a"],
                explanation=str(r["44e7281a"]["answer_explanation"]).replace(
                    "롤의 정리의 결론인데", "롤의 정리를 적용할 때 구하는 값인데"
                ),
            ),
        ),
        # M0615은 차수(3)인 선지 '3'에, M0674는 f'(c) = 0의 근 '-2/3'에 연결하면 절차 값이다.
        ("M-link-procedure", dataclasses.replace(_COUNT_MC, distractors=((2, "M0615"),))),
        ("M-link-procedure", dataclasses.replace(_ROLLE_MC, distractors=((2, "M0674"),))),
        ("V05-touch-verify-mismatch", _fix(r["284122b4"], conditions=("3 - q = 0",))),
        (
            "V05-touch-verify-mismatch",
            dataclasses.replace(_RED_HANDMADE[0][1], conditions=("k + 4 = 0",)),
        ),
        (
            "V05-touch-verify-mismatch",
            dataclasses.replace(_RED_HANDMADE[1][1], conditions=("-c - 5 = 0",)),
        ),
    ]


def test_round5_corrected_forms_pass_their_rule(by_prefix: dict[str, dict[str, object]]) -> None:
    """규칙마다 *그 결함만 고친* 같은 문항은 그 규칙을 통과한다(규칙이 결함 표지가 아니라 문항 전체를 막지
    않는다는 대조). 다른 규칙 위반은 여기서 보지 않는다 — 원문의 다른 결함이 남아 있을 수 있다."""
    still = [
        (rule, i, sorted(_round5(probe)))
        for i, (rule, probe) in enumerate(_green_cases(by_prefix))
        if rule in _round5(probe)
    ]
    assert still == []


def test_every_round5_rule_has_red_and_green_controls(
    by_prefix: dict[str, dict[str, object]],
) -> None:
    red = {rule for rule, _ in _RED_IDS} | {rule for rule, _ in _RED_HANDMADE}
    green = {rule for rule, _ in _green_cases(by_prefix)}
    assert red == ROUND5_RULE_IDS
    assert green == ROUND5_RULE_IDS
    # 매개변수 거부 조건은 자격 측정 뒤 회차 규칙에만 있다(5회차 몫은 5회차 규칙의 진부분집합).
    assert COINCIDENCE_RULE_IDS <= POST_QUALIFICATION_RULE_IDS
    assert COINCIDENCE_RULE_IDS & ROUND5_RULE_IDS < ROUND5_RULE_IDS
    # 5회차 규칙은 RULE_IDS에서 6회차 규칙 바로 앞의 연속 구간이다(회차 순서 — 앞 회차 동결이 이 구간을
    # 빼고 본다 · 6회차 추가로 꼬리가 아니게 됐다).
    tail = RULE_IDS[len(RULE_IDS) - len(ROUND6_RULE_IDS) - len(ROUND5_RULE_IDS) :]
    assert list(tail[: len(ROUND5_RULE_IDS)]) == [r for r in RULE_IDS if r in ROUND5_RULE_IDS]
    assert not ROUND5_RULE_IDS & ROUND6_RULE_IDS


# ── ⑤ 매개변수 거부 조건 ───────────────────────────────────────────────────
def _item(answer: str, cond: str) -> DiffItem:
    """함숫값 경로가 정답과 겹치는지만 다른 02-04 문항(f(x) = (x^2 + 3)(x^2 + a), f'(1) = 값)."""
    return DiffItem(
        slot="mastery_check",
        frame_id="test-product-coefficient",
        question_text=(
            f"함수 f(x) = (x^2 + 3)(x^2 + a)에 대하여 f'(1)의 값이 {cond}일 때, 상수 a의 값을 구하시오."
        ),
        answer_text=answer,
        explanation="곱의 미분법으로 f'(x)를 구해 x = 1을 대입한다.",
        conditions=f"Derivative((x**2 + 3)*(x**2 + a), x).doit().subs(x, 1) = {cond}",
        answer_map=(("a", answer),),
        problem_type_code="ptype.solve-for-unknown",
        answer_format=AnswerFormat.자연수,
    )


def test_round_robin_skips_coincident_parameters_only_when_asked() -> None:
    """f'(1) = 16(a = 3)은 함숫값 경로 f(1) = 4(1 + a) = 16과 겹친다 — 거부 조건이 그 파라미터만 건너뛴다.

    대조군: standard_code 없이 부르면(거부 조건 미적용) 그 파라미터가 그대로 나온다 — 거부가 파라미터
    선택 자체가 아니라 판정기에서 왔다는 변별.
    """
    coincident, honest = _item("3", "16"), _item("5", "20")
    code = "[12미적Ⅰ-02-04]"
    assert {v.rule for v in parameter_coincidences(probe_of(code, coincident))} == {
        "T-function-value-path"
    }
    assert parameter_coincidences(probe_of(code, honest)) == []
    by_value = {16: coincident, 20: honest}
    frames = [Frame("test-product-coefficient", ((16,), (20,)), lambda p: by_value[int(str(p[0]))])]
    picked = round_robin_items(frames, 2, standard_code=code)
    assert [i.answer_text for i in picked] == ["5"]
    unfiltered = round_robin_items(frames, 2)
    assert [i.answer_text for i in unfiltered] == ["3", "5"]
