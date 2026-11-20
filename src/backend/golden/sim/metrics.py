"""회귀 트랙 메트릭 M1~M5(S19 · F-00) — 러너(`golden.sim.run`)가 `sessions.jsonl` 줄로 계산한다.

공유 계약 표(지시서 「메트릭 5개와 기준」)를 그대로 코드로 옮겼다. 모든 함수는 순수 함수다
(DB·네트워크·LLM 없음) — 세션 줄(dict)만 받아 숫자를 낸다. 그래서 같은 jsonl이면 언제 다시 계산해도
같은 숫자가 나온다(보정 S20이 jsonl만 들고 다시 잴 수 있다).

| 메트릭 | 정의 | 기준 | 어기면 |
| --- | --- | --- | --- |
| M1 답 유출률 | GP-5 판정 전 튜터 발화(tutor_turn)에 정답이 나온 세션 비율 | 0% | 차단 |
| M2 평균 턴 수 | P2·P4·P5에서 정답까지 쓴 튜터 턴 수의 평균 | 1.5~3.0 | 경고만 |
| M3 판정 오류율 | 시뮬레이터가 아는 정답·오답과 채점기 판정이 다른 비율 | 1% 미만 | 차단 |
| M4 크래시·시간 초과 | http_status가 200이 아닌 세션 수(null = 예외·시간 초과) | 0건 | 차단 |
| M5 렌더 깨짐 | 튜터 쪽 문장에 짝 안 맞는 `$`·깨진 `\\frac`·백틱 | 0건 | 차단 |

M1 판정 — 옛 `whymath_backend.harness.pedagogical_rubric.detect_answer_leakage`와 같은 규칙:
지시서는 그 함수를 import하라고 했지만, 그 모듈은 `golden/LEGACY_MANIFEST.txt`(158행)에 있어
골든에서 새로 import하면 import-linter 계약 `golden-no-legacy`가 막는다(CLAUDE.md 골든 규칙 —
공통 규칙보다 우선). 그래서 함수 1개와 그 상수만 이 파일로 **복사**했다(HARVEST.md "복사: 새 import
금지 목록"). 같은 입력에 같은 출력인지는 `tests/golden/test_sim_metrics.py`가 옛 함수와 나란히 불러
대조한다(S21 특성화 입력 10개 + 경계 사례). 이것은 측정용 복사이지 GP-4 연결이 아니다 —
슬롯 T1(S22)이 GP-4에 붙이는 평가기와 별개다.

정직성: 정답이 정규화 뒤 1글자(`3`·`x`)면 옛 함수는 `undecidable`을 낸다(오탐 금지 우선).
그런 세션은 유출로 세지 않되, 몇 건인지 `leak_undecidable`로 따로 센다(침묵하지 않는다 —
30문항 중 1글자 정답 문항에서는 M1이 사실상 눈을 감는다).
"""

from __future__ import annotations

import re
import statistics
import unicodedata
from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Any

# ──────────────────────────────────────────────────────────────────────
# M1 — 정답 유출 탐지(옛 pedagogical_rubric에서 복사 · 동작 동일)
# ──────────────────────────────────────────────────────────────────────

# 정답이 이보다 짧으면(정규화 후) 오탐 위험이 커 판정을 유보한다(보수·undecidable).
_MIN_DECIDABLE_LEN = 2

# 정규화 후에도 흔해서 우연 일치가 잦은 토큰 — 노출돼도 정답 유출로 단정 못 함(undecidable).
_AMBIGUOUS_TOKENS: frozenset[str] = frozenset(
    {"true", "false", "yes", "no", "참", "거짓", "없음", "정답", "해", "근"}
)

# LaTeX 명령(백슬래시 워드) 제거용 — 값 매칭 전 마크업을 벗긴다.
_LATEX_COMMANDS = re.compile(r"\\[a-zA-Z]+")
# 구조 문자(수식 구분자·중괄호·공백) 제거용 — 표현 차이를 값 비교에서 흡수한다.
_STRUCTURAL_CHARS = re.compile(r"[$\\{}()\s,]")
# 순수 정수·소수 판정(부호 허용) — 수치 정답은 단어 경계 매칭 경로로 보낸다.
_NUMERIC = re.compile(r"-?\d+(?:\.\d+)?")


class LeakageVerdict(str, Enum):
    """정답 유출 3상태 — 확신 매치만 leaked · 판정 불가는 undecidable."""

    leaked = "leaked"
    clean = "clean"
    undecidable = "undecidable"


def _normalize(text: str) -> str:
    """정규화 — NFKC·소문자·LaTeX 명령·구조 문자 제거(표현이 아니라 값으로 비교한다)."""
    normalized = unicodedata.normalize("NFKC", text).lower()
    normalized = _LATEX_COMMANDS.sub("", normalized)
    return _STRUCTURAL_CHARS.sub("", normalized)


def detect_answer_leakage(response: str, answer: str) -> LeakageVerdict:
    """튜터 문장이 정답 값을 드러내는지 판정한다(옛 함수와 같은 규칙).

    수치 정답은 단어 경계로만 맞춘다("3"이 "13"·"3.5"에 걸리지 않는다). 정규화 뒤 1글자이거나
    흔한 토큰이면 undecidable로 유보한다.
    """
    norm_answer = _normalize(answer)
    if len(norm_answer) < _MIN_DECIDABLE_LEN or norm_answer in _AMBIGUOUS_TOKENS:
        return LeakageVerdict.undecidable
    norm_response = _normalize(response)
    if _NUMERIC.fullmatch(norm_answer):
        pattern = rf"(?<![\d.]){re.escape(norm_answer)}(?![\d.])"
        matched = re.search(pattern, norm_response) is not None
    else:
        matched = norm_answer in norm_response
    return LeakageVerdict.leaked if matched else LeakageVerdict.clean


def session_leak(turns: Sequence[Mapping[str, Any]], answer: str) -> LeakageVerdict:
    """세션 1개의 유출 판정 — GP-5 판정 전 튜터 발화(kind=tutor_turn)만 본다.

    graded 줄의 피드백은 판정 뒤 정답을 알려 주는 문장(계약)이라 보지 않는다.
    하나라도 leaked면 leaked, 아니면 하나라도 undecidable이면 undecidable, 아니면 clean.
    튜터 발화가 하나도 없으면 clean(유출할 기회가 없었다).
    """
    verdicts = [
        detect_answer_leakage(str(t.get("tutor") or ""), answer)
        for t in turns
        if t.get("kind") == "tutor_turn"
    ]
    if LeakageVerdict.leaked in verdicts:
        return LeakageVerdict.leaked
    if LeakageVerdict.undecidable in verdicts:
        return LeakageVerdict.undecidable
    return LeakageVerdict.clean


# ──────────────────────────────────────────────────────────────────────
# M5 — 렌더 깨짐(정규식)
# ──────────────────────────────────────────────────────────────────────

# 이스케이프되지 않은 `$`(앞에 역슬래시가 없는 것)
_DOLLAR = re.compile(r"(?<!\\)\$")
# `\frac` 뒤에 중괄호 두 묶음이 오는 정상형(안쪽 중괄호 1단계까지 허용)
_BRACE = r"\{(?:[^{}]|\{[^{}]*\})*\}"
_FRAC_ANY = re.compile(r"\\frac")
_FRAC_OK = re.compile(r"\\frac\s*" + _BRACE + r"\s*" + _BRACE)
# 마크다운 백틱(앱 화면은 마크다운을 그리지 않는다 — 백틱이 그대로 보인다)
_BACKTICK = "`"


def render_problems(text: str) -> list[str]:
    """튜터 쪽 문장 1개의 렌더 깨짐 사유 목록(빈 목록 = 정상)."""
    reasons: list[str] = []
    if len(_DOLLAR.findall(text)) % 2 == 1:
        reasons.append("짝 안 맞는 $")
    if len(_FRAC_ANY.findall(text)) != len(_FRAC_OK.findall(text)):
        reasons.append("깨진 \\frac")
    if _BACKTICK in text:
        reasons.append("백틱")
    return reasons


def session_render_broken(turns: Sequence[Mapping[str, Any]]) -> bool:
    """세션의 튜터 쪽 문장(되묻기·판정 피드백 모두) 중 하나라도 깨졌으면 True."""
    return any(render_problems(str(t.get("tutor") or "")) for t in turns)


# ──────────────────────────────────────────────────────────────────────
# M3 — 시뮬레이터가 답을 아는 턴
# ──────────────────────────────────────────────────────────────────────

# 정답을 낸다고 아는 페르소나(규칙 페르소나 P5 — 채점기가 떼는 꼬리만 붙인다 · S18)
KNOWN_CORRECT_PERSONAS = frozenset({"P5"})


def expected_correct(persona: str, turn_no: int, forced_answer: str | None) -> bool | None:
    """이 턴의 정답 여부를 시뮬레이터가 아는가 — 알면 True/False, 모르면 None.

    - 주입기가 답을 정한 턴 = 오답: P3는 세션 내내, P2는 첫 입력만(그 뒤는 "다시 시도" — S18).
    - P5는 매 턴 정답(채점기가 떼는 꼬리만 쓴다).
    - 그 밖(P1·P4·P6·P7·P8, P2 둘째 입력부터)은 모른다 — M3에 넣지 않는다.
    """
    if persona in KNOWN_CORRECT_PERSONAS:
        return True
    if forced_answer and (persona == "P3" or (persona == "P2" and turn_no == 1)):
        return False
    return None


def judged_mismatches(session: Mapping[str, Any]) -> tuple[int, int]:
    """(시뮬레이터가 답을 아는 턴 수, 그중 채점기 판정이 다른 턴 수)."""
    known = mismatched = 0
    forced = session.get("forced_answer")
    for turn in session.get("turns") or []:
        expected = expected_correct(str(session.get("persona")), int(turn["n"]), forced)
        if expected is None:
            continue
        known += 1
        if bool(turn.get("correct")) != expected:
            mismatched += 1
    return known, mismatched


# ──────────────────────────────────────────────────────────────────────
# 집계
# ──────────────────────────────────────────────────────────────────────

# 차단 기준(하나라도 어기면 report()가 exit 1) · M2는 경고만
BLOCKING = ("M1", "M3", "M4", "M5")
# M2를 재는 페르소나와 범위
M2_PERSONAS = frozenset({"P2", "P4", "P5"})
M2_RANGE = (1.5, 3.0)
# M3 기준(미만이어야 통과)
M3_MAX = 0.01


def is_crash(session: Mapping[str, Any]) -> bool:
    """M4 — 세션이 HTTP 200으로 끝나지 않았다(null = 예외·시간 초과·계약 위반)."""
    return session.get("http_status") != 200


def tutor_turns_to_correct(session: Mapping[str, Any]) -> int | None:
    """정답으로 끝난 세션의 튜터 턴 수(=graded 직전까지 받은 되묻기 수). 정답이 아니면 None."""
    turns = session.get("turns") or []
    if not turns or turns[-1].get("kind") != "graded" or not turns[-1].get("correct"):
        return None
    return sum(1 for t in turns if t.get("kind") == "tutor_turn")


def _metric(value: float | int | None, threshold: str, ok: bool) -> dict[str, Any]:
    """메트릭 1개의 계약 모양 {"value","threshold","pass"}."""
    return {"value": value, "threshold": threshold, "pass": ok}


def compute(sessions: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """세션 줄 목록 → M1~M5(계약 모양). 세션 0개면 차단 메트릭이 전부 실패다(공허한 통과 금지)."""
    n = len(sessions)
    leaked = sum(1 for s in sessions if s.get("leak") is True)
    m1 = leaked / n if n else None

    m2_turns = [
        t
        for s in sessions
        if s.get("persona") in M2_PERSONAS
        for t in [tutor_turns_to_correct(s)]
        if t is not None
    ]
    m2 = round(statistics.fmean(m2_turns), 3) if m2_turns else None
    m2_ok = m2 is not None and M2_RANGE[0] <= m2 <= M2_RANGE[1]

    known = mismatched = 0
    for s in sessions:
        k, m = judged_mismatches(s)
        known += k
        mismatched += m
    m3 = mismatched / known if known else None

    m4 = sum(1 for s in sessions if is_crash(s))
    m5 = sum(1 for s in sessions if s.get("render_broken") is True)

    return {
        "M1": _metric(None if m1 is None else round(m1, 4), "0%", n > 0 and leaked == 0),
        "M2": _metric(m2, f"{M2_RANGE[0]}~{M2_RANGE[1]}", m2_ok),
        "M3": _metric(None if m3 is None else round(m3, 4), "<1%", m3 is not None and m3 < M3_MAX),
        "M4": _metric(m4, "0", n > 0 and m4 == 0),
        "M5": _metric(m5, "0", n > 0 and m5 == 0),
    }


def counts(sessions: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """메트릭의 분모·보조 숫자(보고·run_meta용) — 숫자가 어디서 왔는지 남긴다."""
    known = mismatched = 0
    for s in sessions:
        k, m = judged_mismatches(s)
        known += k
        mismatched += m
    return {
        "sessions": len(sessions),
        "leaked_sessions": sum(1 for s in sessions if s.get("leak") is True),
        "m2_sessions": sum(
            1
            for s in sessions
            if s.get("persona") in M2_PERSONAS and tutor_turns_to_correct(s) is not None
        ),
        "m3_known_turns": known,
        "m3_mismatched_turns": mismatched,
        "crashed_sessions": sum(1 for s in sessions if is_crash(s)),
        "render_broken_sessions": sum(1 for s in sessions if s.get("render_broken") is True),
    }


def _session_failed(session: Mapping[str, Any]) -> bool:
    """차단 기준 하나라도 어긴 세션인가(유출·렌더 깨짐·크래시·판정 불일치)."""
    return (
        session.get("leak") is True
        or session.get("render_broken") is True
        or is_crash(session)
        or judged_mismatches(session)[1] > 0
    )


def worst_persona(sessions: Sequence[Mapping[str, Any]]) -> str | None:
    """가장 많이 실패한 페르소나.

    순서: ①차단 기준을 어긴 세션 수 ②정답으로 끝나지 못한 세션 수 ③페르소나 ID(동률 깨기).
    세션이 없으면 None.
    """
    tally: dict[str, tuple[int, int]] = {}
    for s in sessions:
        persona = str(s.get("persona"))
        failed, not_correct = tally.get(persona, (0, 0))
        tally[persona] = (
            failed + int(_session_failed(s)),
            not_correct + int(tutor_turns_to_correct(s) is None),
        )
    if not tally:
        return None
    return sorted(tally.items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0]))[0][0]


def slowest_problem(sessions: Sequence[Mapping[str, Any]]) -> str | None:
    """세션 평균 소요 시간이 가장 긴 문항(동률이면 문항 ID 순). 세션이 없으면 None."""
    times: dict[str, list[float]] = {}
    for s in sessions:
        times.setdefault(str(s.get("problem_id")), []).append(float(s.get("elapsed_s") or 0.0))
    if not times:
        return None
    return sorted(times.items(), key=lambda kv: (-statistics.fmean(kv[1]), kv[0]))[0][0]


def blocking_failures(metrics: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """차단 기준 중 통과하지 못한 메트릭 이름."""
    return [name for name in BLOCKING if not metrics[name]["pass"]]
