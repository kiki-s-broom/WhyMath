"""오개념 주입기(S17) 테스트 — 결정성·정답 0건·OP 8종 예시·문항 유형 판별을 고정한다.

완료 기준(지시서 S17): ①같은 입력 → 같은 틀린 답 ②30문항 × 오개념 11건(일차함수 8 + 부호 3)
= 330 조합에서 정답과 같은 출력 0건 ③OP 8종 전부 예시 1건 이상 ④유형 판별의 긍정/부정.
"""

from __future__ import annotations

import ast
import csv
import io
import json
from pathlib import Path

import pytest
from golden.problems import Problem, load_problems
from golden.sim.errors import (
    ALL_INPUTS,
    ALL_MISCONCEPTIONS,
    BOUNDARY,
    COUNT_DIRECTION,
    COUNT_QUADRANT,
    EQUATION,
    F_VALUE,
    INCREASE,
    INJECTABLE_OPS,
    LF_MISCONCEPTIONS,
    MISCONCEPTION_RULES,
    SIGN_MISCONCEPTIONS,
    SLOPE_POINTS,
    SLOPE_READ,
    SOLVE_COEF,
    TABLE_COLUMNS,
    WORD,
    X_INTERCEPT,
    Y_FROM_X_INTERCEPT,
    Y_INTERCEPT,
    WrongAnswer,
    inject,
    injection_table,
    problem_type,
)
from golden.sim.seed_extract import OP_CODES

from golden import grade
from golden.sim import errors

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBLEMS = load_problems()
BY_ID = {problem["id"]: problem for problem in PROBLEMS}
TABLE_CSV = REPO_ROOT / "golden" / "reports_phase1" / "S17" / "injection_table.csv"
MISCONCEPTIONS_JSON = REPO_ROOT / "data" / "corpus" / "misconceptions_v1" / "misconceptions.json"


@pytest.fixture(scope="module")
def results() -> dict[tuple[str, str], WrongAnswer | None]:
    """30문항 × 입력 전부(오개념 11 + OP 8)의 주입 결과 — 한 번만 계산해 여러 테스트가 쓴다."""
    return {(p["id"], item): inject(p, item) for p in PROBLEMS for item in ALL_INPUTS}


def _synthetic(stem: str, answer: str, kind: str = "number") -> Problem:
    """유형 판별·경계 검사용으로 지은 문항(30문항 파일에는 없다)."""
    return {"id": "T-00", "stem": stem, "answer": answer, "answer_kind": kind, "hint1": ""}


# ── ① 결정성 ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("problem_id", "item"),
    [
        ("LF-01", "M0037"),  # 대입 오류(OP_02)
        ("LF-06", "M0001"),  # 음수 곱셈(OP_01)
        ("LF-14", "M0568"),  # 기울기 뒤바꿈(OP_03)
        ("LF-24", "M0002"),  # 식 세우기 + 음수 뺄셈
        ("LF-01", "OP_05"),  # 한 단계 더(대입식이 정답이라 중간값)
    ],
)
def test_same_input_gives_same_wrong_answer_100_times(problem_id: str, item: str) -> None:
    """같은 (문항, 오개념) 100회 호출이 모두 같은 결과다."""
    first = inject(BY_ID[problem_id], item)
    assert first is not None
    assert all(inject(BY_ID[problem_id], item) == first for _ in range(100))


def test_whole_table_is_deterministic(results: dict[tuple[str, str], WrongAnswer | None]) -> None:
    """표 전체를 다시 계산해도 같다(문항 30 × 입력 19)."""
    again = {(p["id"], item): inject(p, item) for p in PROBLEMS for item in ALL_INPUTS}
    assert again == results


def test_committed_table_matches_code() -> None:
    """커밋된 injection_table.csv가 지금 코드로 다시 만든 표와 글자까지 같다(다른 프로세스·다른 날의 결정성)."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=TABLE_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(injection_table(PROBLEMS))
    assert TABLE_CSV.read_text(encoding="utf-8") == buffer.getvalue()


# ── ② 정답과 같은 출력 0건 ───────────────────────────────────────────────


def test_misconception_list_is_8_linear_plus_3_sign() -> None:
    """오개념 입력은 일차함수 8 + 부호 3 = 11건이고, 30문항과 곱하면 330 조합이다."""
    assert len(LF_MISCONCEPTIONS) == 8
    assert len(SIGN_MISCONCEPTIONS) == 3
    assert len(set(ALL_MISCONCEPTIONS)) == 11
    assert set(MISCONCEPTION_RULES) == set(ALL_MISCONCEPTIONS)
    assert len(PROBLEMS) * len(ALL_MISCONCEPTIONS) == 330


def test_no_correct_answer_in_330_misconception_combinations(
    results: dict[tuple[str, str], WrongAnswer | None],
) -> None:
    """330 조합 모두 None이거나 오답이다(정답 0건)."""
    correct = [
        (pid, mid)
        for (pid, mid), result in results.items()
        if mid in ALL_MISCONCEPTIONS
        and result is not None
        and grade.is_correct(BY_ID[pid], result.text)
    ]
    assert correct == []
    assert sum(1 for (_, mid) in results if mid in ALL_MISCONCEPTIONS) == 330


def test_no_correct_answer_in_op_only_combinations(
    results: dict[tuple[str, str], WrongAnswer | None],
) -> None:
    """OP 코드만으로 부른 240 조합도 정답 0건이다."""
    correct = [
        (pid, op)
        for (pid, op), result in results.items()
        if op in INJECTABLE_OPS and result is not None and grade.is_correct(BY_ID[pid], result.text)
    ]
    assert correct == []


def test_every_wrong_answer_is_readable_by_the_grader(
    results: dict[tuple[str, str], WrongAnswer | None],
) -> None:
    """틀린 답은 채점기가 수식으로 읽을 수 있다 — 못 읽는 글자라서 오답인 것은 M3를 재지 못한다."""
    unreadable = []
    for (pid, item), result in results.items():
        if result is None:
            continue
        try:
            grade._parse(grade.normalize(result.text))
        except ValueError:
            unreadable.append((pid, item, result.text))
    assert unreadable == []


def test_wrong_answer_fields(results: dict[tuple[str, str], WrongAnswer | None]) -> None:
    """op_code는 OP_01~OP_08 · 오개념 입력이면 그 ID, OP 코드 입력이면 misconception_id=None."""
    for (_, item), result in results.items():
        if result is None:
            continue
        assert result.op_code in OP_CODES and result.op_code != "OP_00"
        if item in ALL_MISCONCEPTIONS:
            assert result.misconception_id == item
            allowed = {op for op, _ in MISCONCEPTION_RULES[item]}
            assert result.op_code in allowed
        else:
            assert result.misconception_id is None
            assert result.op_code == item


def test_one_more_step_when_first_candidate_is_correct() -> None:
    """첫 후보가 정답이면 한 단계 더 — LF-01의 대입식 `-3×5+3`은 정답이라 중간값 `-3×5`를 낸다."""
    first, second = errors._RULES["OP_05"](errors._info(BY_ID["LF-01"]), None)
    assert grade.is_correct(BY_ID["LF-01"], first)
    assert inject(BY_ID["LF-01"], "OP_05") == WrongAnswer(second, "OP_05", None)
    assert second == "-3×5"


def test_none_when_every_candidate_is_correct() -> None:
    """후보가 모두 정답이면 None — 기울기와 y절편이 같은 식(y=3x+3)에서 둘을 바꿔 읽어도 정답이다."""
    problem = _synthetic("일차함수 $y = 3x + 3$의 그래프의 기울기를 구하시오.", "3")
    assert errors._RULES["OP_04"](errors._info(problem), None) == ["3"]
    assert inject(problem, "M0034") is None
    assert inject(problem, "OP_04") is None


def test_full_substitution_strings_equal_the_answer() -> None:
    """OP_05의 첫 후보(대입식 그대로)는 값이 정답과 같다 — 다르면 식을 잘못 옮긴 것이다."""
    checked = 0
    for problem in PROBLEMS:
        candidates = errors._RULES["OP_05"](errors._info(problem), None)
        if candidates:
            assert grade.is_correct(problem, candidates[0]), problem["id"]
            checked += 1
    assert checked >= 10


def test_solution_path_reproduces_every_answer() -> None:
    """계산 과정(_solve·_solve_line)을 틀림 없이 돌리면 정답이 나온다 — 본문 읽기가 맞다는 대조."""
    solved = 0
    for problem in PROBLEMS:
        info = errors._info(problem)
        if info.kind == EQUATION:
            line = errors._solve_line(info, errors._Calc())
            if line is not None:
                assert line == info.answer_line, problem["id"]
                solved += 1
        else:
            value = errors._solve(info, errors._Calc())
            if value is not None:
                assert value == info.answer_value, problem["id"]
                solved += 1
    assert solved >= 24


def test_unknown_input_raises() -> None:
    """오타·OP_00은 조용히 None이 아니라 ValueError다."""
    for bad in ("M9999", "OP_00", "op_01", ""):
        with pytest.raises(ValueError):
            inject(BY_ID["LF-01"], bad)


# ── ③ OP 8종 예시 ────────────────────────────────────────────────────────


def test_each_op_code_has_an_example(results: dict[tuple[str, str], WrongAnswer | None]) -> None:
    """OP_01~OP_08 각각, OP 코드로 불렀을 때 최소 1문항에서 실제 틀린 답이 나온다."""
    for op in INJECTABLE_OPS:
        hits = [pid for (pid, item), result in results.items() if item == op and result]
        assert hits, op
    assert set(INJECTABLE_OPS) == set(OP_CODES) - {"OP_00"}


def test_misconception_examples_cover_their_codes(
    results: dict[tuple[str, str], WrongAnswer | None],
) -> None:
    """오개념 입력이 만든 답의 OP 코드 — DB에 짝이 있는 6종(OP_01·02·03·04·07·08)이 모두 나온다."""
    seen = {r.op_code for (_, item), r in results.items() if item in ALL_MISCONCEPTIONS and r}
    assert seen == {"OP_01", "OP_02", "OP_03", "OP_04", "OP_07", "OP_08"}


@pytest.mark.parametrize(
    ("problem_id", "item", "expected"),
    [
        ("LF-06", "M0001", WrongAnswer("-12", "OP_01", "M0001")),  # (−6)×(−1)을 −6으로
        ("LF-14", "M0002", WrongAnswer("-9/2", "OP_01", "M0002")),  # 4−(−2)를 4−2로
        ("LF-22", "M0548", WrongAnswer("-3x-7", "OP_01", "M0548")),  # (−1)−(−6)을 −1−6으로
        ("LF-08", "M0037", WrongAnswer("20", "OP_02", "M0037")),  # f(5)를 5×(3+1)로
        ("LF-13", "M0568", WrongAnswer("1/3", "OP_03", "M0568")),  # Δx/Δy
        ("LF-15", "M0034", WrongAnswer("-1", "OP_04", "M0034")),  # 기울기 자리에 y절편
        ("LF-03", "OP_05", WrongAnswer("6×2", "OP_05", None)),  # 상수항 처리 전에 멈춤
        ("LF-30", "OP_06", WrongAnswer("1", "OP_06", None)),  # 첫 숫자 12가 정답이라 다음 숫자 1
        ("LF-18", "M0036", WrongAnswer("6", "OP_07", "M0036")),  # x절편 자리에 y절편
        ("LF-26", "M0035", WrongAnswer("1", "OP_08", "M0035")),  # 감소 대신 증가를 셈
    ],
)
def test_known_examples(problem_id: str, item: str, expected: WrongAnswer) -> None:
    """OP별 대표 예시를 값까지 고정한다(규칙이 바뀌면 여기서 먼저 깨진다)."""
    assert inject(BY_ID[problem_id], item) == expected


def test_type_mismatch_returns_none() -> None:
    """문항 유형에 맞지 않는 오개념은 None — f(k) 문항에 기울기 뒤바꿈(OP_03)·함수 개념 오개념."""
    assert inject(BY_ID["LF-01"], "OP_03") is None
    assert inject(BY_ID["LF-01"], "M0036") is None
    for problem in PROBLEMS:
        assert inject(problem, "M0409") is None
        assert inject(problem, "M0567") is None


# ── ④ 문항 유형 판별 ─────────────────────────────────────────────────────

_EXPECTED_TYPES = {
    **{f"LF-{n:02d}": F_VALUE for n in range(1, 12)},
    "LF-12": SOLVE_COEF,
    "LF-13": SLOPE_POINTS,
    "LF-14": SLOPE_POINTS,
    "LF-15": SLOPE_READ,
    "LF-16": INCREASE,
    "LF-17": Y_INTERCEPT,
    "LF-18": X_INTERCEPT,
    "LF-19": X_INTERCEPT,
    "LF-20": Y_FROM_X_INTERCEPT,
    **{f"LF-{n:02d}": EQUATION for n in range(21, 26)},
    "LF-26": COUNT_DIRECTION,
    "LF-27": BOUNDARY,
    "LF-28": COUNT_QUADRANT,
    "LF-29": EQUATION,
    "LF-30": WORD,
}


def test_problem_type_positive_all_30() -> None:
    """30문항 각각의 유형(긍정 30건)."""
    assert {p["id"]: problem_type(p) for p in PROBLEMS} == _EXPECTED_TYPES


@pytest.mark.parametrize(
    ("stem", "kind", "expected"),
    [
        # 점이 하나뿐이면 두 점 기울기가 아니다
        ("일차함수 $y = 2x + 1$의 그래프의 기울기를 구하시오.", "number", SLOPE_READ),
        # 식 정답이면 본문에 '기울기'가 있어도 식 세우기다
        ("기울기가 $2$이고 점 $(0, 1)$을 지나는 직선의 식을 구하시오.", "expression", EQUATION),
        # f(3)이 있어도 일차식이 없으면 함숫값 유형이 아니다
        ("어떤 함수에서 $f(3)$의 값을 구하시오.", "number", WORD),
        # '상수'가 있어도 f(k)=v가 없으면 상수 구하기가 아니다
        ("상수 $a$에 대하여 $a + 2 = 5$일 때 $a$를 구하시오.", "number", WORD),
        # x절편이 주어지지 않은 y절편 읽기는 문자 계수 유형이 아니다
        ("일차함수 $y = -x + 2$의 그래프의 $y$절편을 구하시오.", "number", Y_INTERCEPT),
    ],
)
def test_problem_type_negative(stem: str, kind: str, expected: str) -> None:
    """비슷해 보이지만 다른 유형으로 가야 하는 본문(부정)."""
    assert problem_type(_synthetic(stem, "1", kind)) == expected


# ── 표의 출처 · 하지 말 것 ───────────────────────────────────────────────


def test_linear_misconceptions_match_the_db_recount() -> None:
    """일차함수 8건은 DB에서 `subunit=일차함수` 또는 성취기준 [9수02-14/15/16]으로 다시 센 것과 같다."""
    items = json.loads(MISCONCEPTIONS_JSON.read_text(encoding="utf-8"))["misconceptions"]
    standards = {"[9수02-14]", "[9수02-15]", "[9수02-16]"}
    recount = {
        m["mis_id"]
        for m in items
        if m.get("subunit") == "일차함수" or m.get("standard_code") in standards
    }
    assert recount == set(LF_MISCONCEPTIONS)
    by_id = {m["mis_id"]: m for m in items}
    assert all(by_id[mid]["error_type"] == "부호오류" for mid in SIGN_MISCONCEPTIONS)


def test_injector_imports_no_llm_loader_or_network() -> None:
    """주입기는 LLM·네트워크·옛 오개념 로더를 import하지 않는다(옛 자산은 T2가 다섯 걸음으로)."""
    source = Path(errors.__file__).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)
    assert imported, "import를 하나도 못 찾았다 — 검사가 공허하다"
    banned = (
        "whymath_backend",
        "httpx",
        "requests",
        "urllib",
        "socket",
        "ollama",
        "openai",
        "anthropic",
        "random",
    )
    banned_golden = ("golden.tutor", "golden.api", "golden.sim_student", "golden.store")
    hits = [name for name in imported if name.split(".")[0] in banned or name in banned_golden]
    assert hits == []


# ── S20 반복: M0568은 뒤집음(OP_03)부터 · 문항 개념의 오개념 ─────────────────────


def test_m0568_prefers_slope_inversion_on_every_slope_problem() -> None:
    """식에서 읽기(LF-15)·식 세우기(LF-23·24)에서도 M0568이 OP_03을 낸다(전에는 OP_04에 가렸다)."""
    for pid in ("LF-13", "LF-14", "LF-15", "LF-23", "LF-24"):
        wrong = inject(BY_ID[pid], "M0568")
        assert wrong is not None and wrong.op_code == "OP_03", pid


def test_topic_misconception_is_slope_only() -> None:
    """기울기를 묻거나 두 점으로 식을 세우는 5문항만 M0568, 나머지 25문항은 None."""
    from golden.sim.errors import topic_misconception

    topic = {p["id"]: topic_misconception(p) for p in PROBLEMS}
    assert {pid for pid, m in topic.items() if m} == {"LF-13", "LF-14", "LF-15", "LF-23", "LF-24"}
    assert {m for m in topic.values() if m} == {"M0568"}
