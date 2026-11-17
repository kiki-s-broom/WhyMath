"""시드 추출(S16) — 사람 출처 턴 CSV에서 말투 시드 20개와 비교 기준 분포 2개를 뽑는다.

실행(저장소의 src/backend 폴더에서):
    python -m golden.sim.seed_extract --input self=../../golden/logs/self1_turns.csv \
        --input adult=../../golden/logs/adult2_turns.csv

- 입력: 턴 CSV(열 `id,problem_id,turn_no,kind,correct,student_text,tutor_text,created_at`).
  `라벨=경로` 꼴로 주고, 한 파일에 두 출처가 섞였으면 `라벨=경로@시작id-끝id`로 자른다.
  라벨은 `self`(본인)·`adult`(성인) 둘뿐이다. 실제 중학생 로그는 2026-11-15 현재 0건이다.
- 출력(`golden/sim/seed/` — gitignore 대상, 로컬에만 둔다):
  `utterances.txt`(발화<TAB>라벨 20줄) · `distributions.json`(턴 수·오류 유형 분포) · `README.md`.
- 원본 CSV가 없으면 `--s13-problems`로 S13 집계본(`problems.csv`)에서 턴 수 분포만 만든다.

이 모듈은 LLM·네트워크를 전혀 부르지 않는다(공통 규칙 7 — 시드는 로컬 Ollama 외 어디로도
보내지 않는다. `tests/golden/test_sim_seed.py`가 이 파일의 import를 검사해 동결한다).
튜터 발화(`tutor_text`)는 읽지 않는다. 발화는 고르기만 하고 다듬지 않는다.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import statistics
import sys
from collections import Counter
from dataclasses import dataclass
from fractions import Fraction
from itertools import product
from pathlib import Path

import sympy

from golden import grade
from golden.problems import Problem, load_problems

logger = logging.getLogger(__name__)

# 저장소 루트 — parents[4] = sim → golden → backend → src → 저장소 루트
REPO_ROOT = Path(__file__).resolve().parents[4]
SEED_DIR = REPO_ROOT / "golden" / "sim" / "seed"

# 출처 라벨(공유 계약: 사람 출처 = 본인·성인. 실학생이 생기면 그때 라벨을 더한다)
SOURCE_LABELS = ("self", "adult")

# 시드로 고르는 발화 수(지시서 S16)
SEED_COUNT = 20

# 오류 유형 코드(정본 설명은 golden/sim/op_codes.md — 주입기 S17·보정 검사 S20이 같은 표를 쓴다)
OP_CODES: dict[str, str] = {
    "OP_00": "미분류",
    "OP_01": "부호 오류(음수 곱·뺄셈)",
    "OP_02": "대입 오류(x 자리에 넣지 않음·곱 대신 더함·자리 붙임)",
    "OP_03": "기울기 분자·분모 뒤바꿈",
    "OP_04": "기울기·y절편 혼동",
    "OP_05": "계산을 끝내지 않음(식만 쓰거나 중간값에서 멈춤)",
    "OP_06": "식 세우기 실패(문제 속 숫자 하나 찍기)",
    "OP_07": "x절편·y절편 혼동",
    "OP_08": "증가·감소 방향 혼동",
}

README_LINE = (
    "이 폴더의 내용은 로컬 Ollama 외 어디로도 보내지 않는다. "
    "실제 중학생 로그 0건 · 사람 출처 = 본인·성인(2026-11-15)\n"
)

# 턴 CSV에 반드시 있어야 하는 열
_REQUIRED_COLUMNS = ("id", "problem_id", "kind", "correct", "student_text")

# 있으면 안 되는 열(공통 규칙 10 — 식별자는 CSV를 뽑을 때 이미 빠져 있어야 한다)
_FORBIDDEN_COLUMNS = ("nickname", "session_id")


class SeedExtractError(RuntimeError):
    """시드 추출을 계속할 수 없는 입력 오류."""


# ──────────────────────────────────────────────────────────────────────
# 입력 읽기
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class InputSpec:
    """입력 파일 1건 — 출처 라벨·경로·(선택) id 범위."""

    label: str
    path: Path
    id_min: int | None = None
    id_max: int | None = None


@dataclass(frozen=True)
class TurnRow:
    """턴 CSV 한 줄에서 이 모듈이 쓰는 값만 담는다(튜터 발화는 담지 않는다)."""

    source: str
    row_id: int
    problem_id: str
    kind: str
    correct: bool
    student_text: str


@dataclass(frozen=True)
class Record:
    """문제 기록 1건 — 한 사람이 한 문제를 받은 뒤 판정까지."""

    source: str
    problem_id: str
    tutor_turns: int
    graded: bool
    correct: bool


def parse_input_spec(text: str) -> InputSpec:
    """`라벨=경로` 또는 `라벨=경로@시작id-끝id`를 읽는다."""
    label, sep, rest = text.partition("=")
    if not sep or label not in SOURCE_LABELS:
        raise SeedExtractError(f"입력은 라벨=경로 꼴이고 라벨은 {SOURCE_LABELS} 중 하나다: {text}")
    path_text, at, id_range = rest.rpartition("@")
    if not at:
        return InputSpec(label=label, path=Path(rest))
    match = re.fullmatch(r"(\d+)-(\d+)", id_range)
    if match is None:
        raise SeedExtractError(f"id 범위는 @시작-끝 꼴이다: {text}")
    return InputSpec(label, Path(path_text), int(match.group(1)), int(match.group(2)))


def read_turns(spec: InputSpec) -> list[TurnRow]:
    """턴 CSV를 읽는다. 닉네임·session_id 열이 있으면 읽지 않고 멈춘다."""
    with spec.path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = tuple(reader.fieldnames or ())
        forbidden = [name for name in _FORBIDDEN_COLUMNS if name in columns]
        if forbidden:
            raise SeedExtractError(f"식별자 열이 있는 CSV는 읽지 않는다: {forbidden}")
        missing = [name for name in _REQUIRED_COLUMNS if name not in columns]
        if missing:
            raise SeedExtractError(f"턴 CSV에 열이 없다: {missing} ({spec.path.name})")
        rows: list[TurnRow] = []
        for raw in reader:
            row_id = int(raw["id"])
            if spec.id_min is not None and row_id < spec.id_min:
                continue
            if spec.id_max is not None and row_id > spec.id_max:
                continue
            rows.append(
                TurnRow(
                    source=spec.label,
                    row_id=row_id,
                    problem_id=raw["problem_id"],
                    kind=raw["kind"],
                    correct=raw["correct"].strip().lower() in ("t", "true", "1"),
                    student_text=raw["student_text"],
                )
            )
    return sorted(rows, key=lambda row: row.row_id)


def build_records(rows: list[TurnRow]) -> list[Record]:
    """한 파일(한 출처)의 턴 줄을 문제 기록으로 묶는다 — 같은 문제의 줄을 판정 줄까지 모은다."""
    records: list[Record] = []
    current: str | None = None
    turns = 0
    source = rows[0].source if rows else ""
    for row in rows:
        if current is not None and row.problem_id != current:
            # 판정 없이 다음 문제로 넘어감 — 끝나지 않은 기록
            records.append(Record(source, current, turns, graded=False, correct=False))
            turns = 0
        current = row.problem_id
        if row.kind == "graded":
            records.append(Record(source, current, turns, graded=True, correct=row.correct))
            current, turns = None, 0
        else:
            turns += 1
    if current is not None:
        records.append(Record(source, current, turns, graded=False, correct=False))
    return records


# S13 집계본(problems.csv)의 출처 열 → 라벨
_S13_SOURCE = {"본인": "self", "성인": "adult"}


def records_from_s13(path: Path) -> list[Record]:
    """원본 CSV가 없을 때 — S13 집계본에서 사람 출처 문제 기록만 읽는다(학생 입력 열은 없다)."""
    records: list[Record] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            label = _S13_SOURCE.get(raw["출처"])
            if label is None:
                continue  # AI 시뮬레이션 줄은 시드가 아니다
            verdict = raw["판정"]
            records.append(
                Record(
                    source=label,
                    problem_id=raw["문제"],
                    tutor_turns=int(raw["튜터턴"]),
                    graded=verdict in ("맞음", "틀림"),
                    correct=verdict == "맞음",
                )
            )
    return records


# ──────────────────────────────────────────────────────────────────────
# 익명화
# ──────────────────────────────────────────────────────────────────────

# 학교·학원 이름(낱말 끝이 이 말이면 낱말 전체를 가린다)
_SCHOOL = re.compile(r"[가-힣A-Za-z0-9]+(?:초등학교|중학교|고등학교|여중|여고|학원)")

# 지역 이름(광역 시·도 — 낱말 끝 글자(시·구·동)로 잡으면 `다시` 같은 말이 걸려서 목록으로만 본다)
_REGION = re.compile(
    r"(?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)"
    r"(?:특별시|광역시|도|시)?"
)

# 가릴 수 없어 발화를 통째로 버리는 꼴 — 자기소개·학년·반·연락처
_DROP = re.compile(
    r"이름[은이]|(?:저는|나는|전|난)\s*[가-힣]{2,4}(?:이에요|예요|입니다|이야|야)(?:\s|$|[.!?])"
    r"|\d\s*학년|\d\s*반(?:\s|$|[.!?,])|01\d[- ]?\d{3,4}[- ]?\d{4}|@"
)

MASK = "[이름]"


def anonymize(text: str, names: tuple[str, ...] = ()) -> str | None:
    """발화 1건을 익명화한다. 이름·학교·지역 낱말은 `[이름]`으로 바꾸고, 확신이 없으면 None(버림).

    `names`는 알고 있는 닉네임·이름 목록이다(명령줄 `--name`). 발화의 나머지는 건드리지 않는다.
    """
    if _DROP.search(text):
        return None
    out = text
    for name in names:
        if name:
            out = out.replace(name, MASK)
    out = _SCHOOL.sub(MASK, out)
    out = _REGION.sub(MASK, out)
    return out


def find_identifiers(text: str, names: tuple[str, ...] = ()) -> list[str]:
    """익명화 뒤에도 남은 식별 낱말을 찾는다(완료 기준 검사용 — 빈 목록이어야 한다)."""
    found = [m.group(0) for m in _SCHOOL.finditer(text)]
    found += [m.group(0) for m in _REGION.finditer(text)]
    found += [m.group(0) for m in _DROP.finditer(text)]
    found += [name for name in names if name and name in text]
    return found


# ──────────────────────────────────────────────────────────────────────
# 발화 고르기
# ──────────────────────────────────────────────────────────────────────

_HANGUL = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")
_PLAIN_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _speech_rank(text: str) -> tuple[int, int, str]:
    """고르는 순서 — 구어체(한글·물음표) → 식·오타 섞인 입력 → 숫자만. 묶음 안에서는 짧은 것."""
    if _HANGUL.search(text) or "?" in text:
        group = 0
    elif _PLAIN_NUMBER.fullmatch(text.strip()):
        group = 2
    else:
        group = 1
    return (group, len(text), text)


def select_utterances(
    rows: list[TurnRow], names: tuple[str, ...] = (), count: int = SEED_COUNT
) -> tuple[list[tuple[str, str]], int]:
    """학생 발화를 익명화하고 `count`개를 고른다. (고른 (발화, 라벨) 목록, 버린 수)를 돌려준다.

    "잘 쓴" 긴 문장보다 짧고 구어체인 것을 먼저 고른다. 같은 발화는 한 번만 넣는다.
    """
    seen: dict[str, str] = {}
    dropped = 0
    for row in rows:
        text = row.student_text.strip()
        if not text:
            continue
        clean = anonymize(text, names)
        if clean is None:
            dropped += 1
            continue
        seen.setdefault(clean, row.source)
    ranked = sorted(seen.items(), key=lambda item: _speech_rank(item[0]))
    return ranked[:count], dropped


# ──────────────────────────────────────────────────────────────────────
# 오류 유형 분류(OP 코드) — 규칙만 쓴다. 모르면 OP_00.
# ──────────────────────────────────────────────────────────────────────

_FRAC = re.compile(r"\\frac\{(-?\d+)\}\{(\d+)\}")
_LINEAR = re.compile(r"(?:f\(x\)|y)=(?P<a>-?\d*(?:/\d+)?)x(?P<b>[+-]\d+(?:/\d+)?)?(?![\dx(+\-*/])")
_F_OF_K = re.compile(r"f\((-?\d+)\)")
_X_IS_K = re.compile(r"x=(-?\d+)일때")
_POINT = re.compile(r"\((-?\d+),(-?\d+)\)")
_BOUNDARY = re.compile(r"\(a-(\d+)\)x")
_STEM_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _flat_stem(stem: str) -> str:
    """문항 본문에서 LaTeX 겉모양을 걷어 규칙이 읽기 쉬운 한 줄로 만든다."""
    flat = _FRAC.sub(r"\1/\2", stem)
    return re.sub(r"[\s$]", "", flat.replace("\u2212", "-"))


def _coefficient(text: str) -> Fraction:
    """`-`·``(빈칸)·`3`·`1/2` 같은 계수 표기를 분수로 바꾼다."""
    if text in ("", "+"):
        return Fraction(1)
    if text == "-":
        return Fraction(-1)
    return Fraction(text)


def _linear_of(flat: str) -> tuple[Fraction, Fraction] | None:
    """본문 첫 일차식의 (기울기, y절편). 문자 계수(`ax+5`·`3x+b`)면 None."""
    match = _LINEAR.search(flat)
    if match is None:
        return None
    return _coefficient(match.group("a")), Fraction(match.group("b") or "0")


def _student_value(text: str) -> sympy.Expr | None:
    """학생 입력을 채점기와 같은 정규화·파서로 읽는다. 읽을 수 없으면 None."""
    try:
        return grade._parse(grade.normalize(text))
    except Exception as exc:  # noqa: BLE001 — 읽지 못한 입력은 미분류로 간다. 타입명은 남긴다
        logger.debug("golden.sim.seed_extract 입력 파싱 실패 예외=%s", type(exc).__name__)
        return None


def _as_fraction(value: sympy.Expr) -> Fraction | None:
    """SymPy 수를 분수로. 변수가 남아 있으면 None."""
    if value.free_symbols:
        return None
    number = sympy.nsimplify(value)
    if not number.is_Rational:
        return None
    return Fraction(int(number.p), int(number.q))


def _hit(value: Fraction, candidates: set[Fraction], *, loose: bool) -> bool:
    """값이 후보 중 하나와 같은가. 학생이 소수로 썼으면(`-0.67`) 0.01 안쪽을 같다고 본다."""
    if loose:
        return any(abs(value - cand) <= Fraction(1, 100) for cand in candidates)
    return value in candidates


def _sign_variants(a: Fraction, k: Fraction, b: Fraction) -> set[Fraction]:
    """a·k + b에서 부호를 하나 이상 틀렸을 때 나올 수 있는 값들."""
    return {sa * a * sk * k + sb * b for sa, sk, sb in product((1, -1), repeat=3)}


def _concat(a: Fraction, k: Fraction) -> Fraction | None:
    """`6x`의 x 자리에 2를 붙여 62로 읽는 자리 붙임 값. 정수가 아니면 None."""
    if a.denominator != 1 or k.denominator != 1 or k < 0:
        return None
    return Fraction(int(f"{a.numerator}{k.numerator}"))


def _classify_equation(answer: sympy.Expr | None, student: sympy.Expr, x: sympy.Symbol) -> str:
    """식 정답 문항 — 학생 식과 정답 식의 (기울기, y절편)을 견준다."""
    if answer is None:
        return "OP_00"
    try:
        ans = sympy.Poly(answer, x).all_coeffs()
        stu = sympy.Poly(student, x).all_coeffs()
    except sympy.PolynomialError:
        return "OP_00"
    if len(ans) != 2 or len(stu) != 2:
        return "OP_00"
    if stu[0] == ans[1] and stu[1] == ans[0]:
        return "OP_04"
    if abs(stu[0]) == abs(ans[0]) and abs(stu[1]) == abs(ans[1]):
        return "OP_01"
    return "OP_00"


def classify_error(problem: Problem, student_text: str) -> str | None:
    """오답 1건을 OP 코드로 분류한다. 답을 낸 것이 아니면 None.

    답을 낸 것이 아닌 입력 = 숫자가 없거나("모르겠어요"), 한글이 섞여 채점기가 수식으로 읽지 못한
    말("5넣어요?"). 이런 입력은 오류 유형이 아니라 `non_answer`로 따로 센다.

    정답인 입력을 넣으면 안 된다(부르는 쪽이 오답만 넘긴다). 규칙에 안 걸리면 OP_00.
    순서: 문항 유형별 오개념 규칙 → 부호 반대(OP_01) → 식만 씀(OP_05) → 본문 숫자(OP_06).
    """
    if not re.search(r"\d", student_text):
        return None
    student = _student_value(student_text)
    if student is None:
        return None if _HANGUL.search(grade.normalize(student_text)) else "OP_00"
    x = sympy.Symbol("x")
    if problem["answer_kind"] == "expression":
        return _classify_equation(_student_value(problem["answer"]), student, x)

    value = _as_fraction(student)
    answer_expr = _student_value(problem["answer"])
    answer = _as_fraction(answer_expr) if answer_expr is not None else None
    if value is None or answer is None:
        return "OP_00"
    loose = "." in student_text
    flat = _flat_stem(problem["stem"])
    linear = _linear_of(flat)
    points = [(Fraction(px), Fraction(py)) for px, py in _POINT.findall(flat)]

    # ① 두 점의 기울기 — 뒤바꿈(OP_03)
    if "기울기를구하" in flat and len(points) == 2:
        dx, dy = points[1][0] - points[0][0], points[1][1] - points[0][1]
        if dy != 0 and _hit(value, {dx / dy, -dx / dy}, loose=loose):
            return "OP_03"
    # ② 식에서 기울기·절편 읽기 — 혼동(OP_04·OP_07)·뒤바꿈(OP_03)
    elif linear is not None and "기울기를구하" in flat:
        a, b = linear
        if _hit(value, {b}, loose=loose):
            return "OP_04"
        if a != 0 and _hit(value, {1 / a}, loose=loose):
            return "OP_03"
    elif linear is not None and "y절편을구하" in flat:
        a, b = linear
        if _hit(value, {a}, loose=loose):
            return "OP_04"
        if a != 0 and _hit(value, {-b / a}, loose=loose):
            return "OP_07"
    elif linear is not None and "x절편을구하" in flat:
        a, b = linear
        if _hit(value, {b}, loose=loose):
            return "OP_07"
        if _hit(value, {a}, loose=loose):
            return "OP_04"
    # ③ 증가·감소 — 반대 방향(OP_08)
    elif "증가할때" in flat and "몇개" in flat:
        total = Fraction(len(re.findall(r"y=", flat)))
        if _hit(value, {total - answer} - {answer}, loose=loose):
            return "OP_08"
    elif "증가할때" in flat and _BOUNDARY.search(flat):
        boundary = Fraction(_BOUNDARY.search(flat).group(1))  # type: ignore[union-attr]
        if _hit(value, {2 * boundary - answer}, loose=loose):
            return "OP_08"
    # ④ 함숫값 f(k) — 부호(OP_01)·대입(OP_02)·중간값(OP_05)
    elif linear is not None:
        k_match = _F_OF_K.search(flat) or _X_IS_K.search(flat)
        if k_match is not None:
            a, b = linear
            k = Fraction(k_match.group(1))
            if _hit(value, _sign_variants(a, k, b) - {answer}, loose=loose):
                return "OP_01"
            subst = {a + b, a + k + b, k * (a + b)}
            glued = _concat(a, k)
            if glued is not None:
                subst.add(glued + b)
            if _hit(value, subst - {answer}, loose=loose):
                return "OP_02"
            if b != 0 and _hit(value, {a * k}, loose=loose):
                return "OP_05"

    # ⑤ 어느 유형이든 — 정답과 부호만 반대
    if answer != 0 and _hit(value, {-answer}, loose=loose):
        return "OP_01"
    # ⑥ 수 하나가 아니라 계산 전 식을 그대로 씀
    if not isinstance(student, sympy.Number) or re.search(
        r"\d\)?[+*/]|\d\)?-\(?\d", grade.normalize(student_text)
    ):
        return "OP_05"
    # ⑦ 문제에 적힌 숫자 하나를 그대로 냄
    stem_numbers = {Fraction(n) for n in _STEM_NUMBER.findall(flat)}
    if abs(value) in stem_numbers:
        return "OP_06"
    return "OP_00"


# ──────────────────────────────────────────────────────────────────────
# 분포
# ──────────────────────────────────────────────────────────────────────


def _median(values: list[int]) -> float | None:
    """중앙값. 빈 목록이면 None."""
    return float(statistics.median(values)) if values else None


def _turn_summary(records: list[Record]) -> dict[str, object]:
    """문제 기록 묶음 하나의 턴 수 요약."""
    to_correct = [r.tutor_turns for r in records if r.graded and r.correct]
    opened = [n for n in to_correct if n > 0]
    return {
        "records": len(records),
        "to_correct": to_correct,
        "median_to_correct": _median(to_correct),
        "opened_to_correct": opened,
        "median_opened_to_correct": _median(opened),
        "forced_wrong": sum(1 for r in records if r.graded and not r.correct),
        "unfinished": sum(1 for r in records if not r.graded),
    }


def turn_distribution(records: list[Record]) -> dict[str, object]:
    """정답까지 튜터 턴 수 — 출처별·합산·문항별.

    `to_correct`는 정답으로 끝난 기록의 튜터 턴 수(첫 입력 정답 = 0)다. `opened_to_correct`는 그중
    튜터가 한 번 이상 열린 것만이다. 3턴을 다 쓰고 틀린 기록은 `forced_wrong`으로 따로 센다.
    """
    by_source = {
        label: _turn_summary([r for r in records if r.source == label]) for label in SOURCE_LABELS
    }
    per_problem: dict[str, dict[str, list[int]]] = {}
    for record in records:
        if record.graded and record.correct:
            slot = per_problem.setdefault(record.problem_id, {})
            slot.setdefault(record.source, []).append(record.tutor_turns)
    return {
        "definition": "정답으로 끝난 문제 기록의 튜터 턴 수(첫 입력 정답 = 0)",
        "by_source": by_source,
        "combined": _turn_summary(records),
        "per_problem": dict(sorted(per_problem.items())),
    }


def error_distribution(rows: list[TurnRow], problems: dict[str, Problem]) -> dict[str, object]:
    """오답 입력을 OP 코드로 분류한 빈도 — 출처별·합산·상위 3개."""
    counts: dict[str, Counter[str]] = {label: Counter() for label in SOURCE_LABELS}
    non_answer: Counter[str] = Counter()
    for row in rows:
        problem = problems.get(row.problem_id)
        if row.correct or problem is None or not row.student_text.strip():
            continue
        code = classify_error(problem, row.student_text)
        if code is None:
            non_answer[row.source] += 1
        else:
            counts[row.source][code] += 1
    combined: Counter[str] = Counter()
    for counter in counts.values():
        combined.update(counter)

    def _table(counter: Counter[str]) -> dict[str, int]:
        return {code: counter.get(code, 0) for code in OP_CODES}

    def _top3(counter: Counter[str]) -> list[str]:
        # 미분류(OP_00)는 유형이 아니므로 상위 3개에 넣지 않는다(S20 보정 기준 ②가 이 목록을 쓴다)
        ranked = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
        return [code for code, _ in ranked if code != "OP_00"][:3]

    return {
        "definition": "오답 처리된 학생 입력의 OP 코드 빈도(답이 아닌 말은 non_answer로 따로)",
        "by_source": {label: _table(counts[label]) for label in SOURCE_LABELS},
        "combined": _table(combined),
        "top3": {
            "combined": _top3(combined),
            **{label: _top3(counts[label]) for label in SOURCE_LABELS},
        },
        "non_answer": {label: non_answer.get(label, 0) for label in SOURCE_LABELS},
    }


# ──────────────────────────────────────────────────────────────────────
# 조립·쓰기
# ──────────────────────────────────────────────────────────────────────


def extract(
    specs: list[InputSpec],
    *,
    names: tuple[str, ...] = (),
    s13_problems: Path | None = None,
) -> tuple[list[tuple[str, str]], dict[str, object]]:
    """입력들에서 (시드 발화 목록, 분포 사전)을 만든다. 파일은 쓰지 않는다."""
    rows: list[TurnRow] = []
    records: list[Record] = []
    inputs: list[dict[str, object]] = []
    for spec in specs:
        part = read_turns(spec)
        rows.extend(part)
        records.extend(build_records(part))
        inputs.append({"label": spec.label, "file": spec.path.name, "rows": len(part)})
    turns_from = "턴 CSV"
    if s13_problems is not None:
        # 집계본이 문제 기록 전부를 갖고 있으므로 턴 수 분포는 집계본에서 낸다
        records = records_from_s13(s13_problems)
        turns_from = f"S13 집계본({s13_problems.name}) — 원본 CSV 없이"
    selected, dropped = select_utterances(rows, names)
    leftovers = [hit for text, _ in selected for hit in find_identifiers(text, names)]
    if leftovers:
        raise SeedExtractError(f"익명화 뒤에도 식별 낱말이 {len(leftovers)}건 남았다 — 쓰지 않는다")
    collected = Counter(row.source for row in rows if row.student_text.strip())
    problems = {problem["id"]: problem for problem in load_problems()}
    distributions: dict[str, object] = {
        "note": README_LINE.strip(),
        "inputs": inputs,
        "turns_from": turns_from,
        "utterances": {
            "collected": {label: collected.get(label, 0) for label in SOURCE_LABELS},
            "dropped_by_anonymizer": dropped,
            "selected": len(selected),
            "selected_by_source": dict(Counter(label for _, label in selected)),
        },
        "turns": turn_distribution(records),
        "errors": error_distribution(rows, problems) if rows else None,
        "op_codes": OP_CODES,
    }
    return selected, distributions


def write_seed(
    out_dir: Path, selected: list[tuple[str, str]], distributions: dict[str, object]
) -> None:
    """시드 폴더에 파일 3개를 쓴다(발화는 받은 그대로 — 다듬지 않는다)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = [f"{text}\t{label}\n" for text, label in selected]
    (out_dir / "utterances.txt").write_text("".join(lines), encoding="utf-8")
    (out_dir / "distributions.json").write_text(
        json.dumps(distributions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "README.md").write_text(README_LINE, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """명령줄 진입점. 발화 원문은 화면에 찍지 않는다(건수와 라벨만)."""
    parser = argparse.ArgumentParser(description="사람 출처 턴 CSV → golden/sim/seed/")
    parser.add_argument("--input", action="append", default=[], help="라벨=경로[@시작id-끝id]")
    parser.add_argument("--s13-problems", type=Path, default=None, help="S13 problems.csv(대체)")
    parser.add_argument("--name", action="append", default=[], help="가릴 닉네임·이름(반복 가능)")
    parser.add_argument("--out", type=Path, default=SEED_DIR, help="출력 폴더")
    args = parser.parse_args(argv)
    if not args.input and args.s13_problems is None:
        parser.error("--input 또는 --s13-problems 중 하나는 있어야 한다")
    try:
        specs = [parse_input_spec(text) for text in args.input]
        selected, distributions = extract(
            specs, names=tuple(args.name), s13_problems=args.s13_problems
        )
    except (SeedExtractError, OSError) as exc:
        print(f"SEED_REFUSED=True — {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    write_seed(args.out, selected, distributions)
    summary = {
        "out": str(args.out),
        "utterances": distributions["utterances"],
        "turns_from": distributions["turns_from"],
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
