"""시드 추출(S16) 테스트 — 익명화·OP 분류·출력 모양·시드 반출 금지를 고정한다.

여기 쓰는 학생 입력은 모두 테스트용으로 지은 것이다(사람 출처 시드를 테스트에 옮기지 않는다 —
공통 규칙 7).
"""

from __future__ import annotations

import ast
import csv
import json
import re
from pathlib import Path

import pytest
from golden.problems import load_problems
from golden.sim.seed_extract import (
    OP_CODES,
    InputSpec,
    SeedExtractError,
    anonymize,
    build_records,
    classify_error,
    extract,
    find_identifiers,
    parse_input_spec,
    read_turns,
    records_from_s13,
    select_utterances,
    write_seed,
)

from golden.sim import seed_extract

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBLEMS = {problem["id"]: problem for problem in load_problems()}
HEADER = [
    "id",
    "problem_id",
    "turn_no",
    "kind",
    "correct",
    "student_text",
    "tutor_text",
    "created_at",
]


def _write_csv(path: Path, rows: list[list[str]], header: list[str] | None = None) -> Path:
    """턴 CSV 한 개를 만든다(열 순서는 S9·S12 내보내기 SQL과 같다)."""
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header or HEADER)
        writer.writerows(rows)
    return path


def _turn(row_id: int, pid: str, kind: str, correct: str, text: str) -> list[str]:
    return [str(row_id), pid, "1", kind, correct, text, "튜터 말(읽지 않는다)", "2026-11-16"]


# ── 익명화: 긍정 3(가리거나 버린다) ──────────────────────────────────────


def test_anonymize_masks_school_name() -> None:
    assert anonymize("가나중학교에서 배웠어요") == "[이름]에서 배웠어요"


def test_anonymize_masks_region_and_known_name() -> None:
    assert (
        anonymize("부산 사는 monglee인데요 3이요", names=("monglee",))
        == "[이름] 사는 [이름]인데요 3이요"
    )


def test_anonymize_drops_self_introduction_and_grade() -> None:
    assert anonymize("저는 홍길동이에요") is None
    assert anonymize("2학년 3반이에요") is None
    assert anonymize("제 이름은 비밀") is None


# ── 익명화: 부정 3(건드리지 않는다) ──────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "-7?",  # 숫자와 물음표뿐
        "y가 뭐예요?",  # 개념 질문
        "다시 해볼게요 2넣어요?",  # `시`로 끝나는 낱말(지역 오탐 함정)·띄어쓰기 없는 구어체
    ],
)
def test_anonymize_leaves_ordinary_utterances_untouched(text: str) -> None:
    assert anonymize(text) == text
    assert find_identifiers(text) == []


def test_find_identifiers_sees_what_anonymize_would_mask() -> None:
    """검사기 자신의 변별력 — 가려야 할 낱말이 있으면 빈 목록이 아니다."""
    assert find_identifiers("가나중학교") != []
    assert find_identifiers("monglee 3", names=("monglee",)) == ["monglee"]


# ── OP 분류: 8종 각 1 + 미분류 + 비답변 ──────────────────────────────────


@pytest.mark.parametrize(
    ("problem_id", "student_text", "expected"),
    [
        ("LF-08", "-14", "OP_01"),  # 3×5+1 → −15+1 (부호)
        ("LF-07", "9", "OP_02"),  # 2x+7, f(2) → 2+7 (x를 넣지 않음)
        ("LF-13", "1/3", "OP_03"),  # (1,2)·(4,11) → 3/9 (뒤바꿈)
        ("LF-15", "-1", "OP_04"),  # y=(2/3)x−1의 기울기를 y절편으로
        ("LF-08", "15", "OP_05"),  # 3×5까지만(중간값)
        ("LF-30", "84", "OP_06"),  # 문제에 적힌 숫자
        ("LF-18", "6", "OP_07"),  # y=−2x+6의 x절편을 y절편으로
        ("LF-26", "1", "OP_08"),  # 감소 3개를 증가 1개로
        ("LF-30", "99", "OP_00"),  # 어느 규칙에도 없음
    ],
)
def test_classify_error_each_code(problem_id: str, student_text: str, expected: str) -> None:
    assert classify_error(PROBLEMS[problem_id], student_text) == expected


def test_classify_error_more_shapes() -> None:
    """식 정답·소수·계산 전 식·경곗값 — 규칙 문서(op_codes.md)의 나머지 줄."""
    assert classify_error(PROBLEMS["LF-22"], "y=-3x-5") == "OP_01"  # 부호만 다른 식
    assert classify_error(PROBLEMS["LF-23"], "y=x+2") == "OP_04"  # 두 수를 바꿔 씀
    assert classify_error(PROBLEMS["LF-13"], "0.33") == "OP_03"  # 소수로 쓴 뒤바꿈
    assert classify_error(PROBLEMS["LF-08"], "3×5+2") == "OP_05"  # 값이 다른 계산 전 식
    assert classify_error(PROBLEMS["LF-27"], "2") == "OP_08"  # 경계 반대쪽
    assert classify_error(PROBLEMS["LF-17"], "4") == "OP_04"  # y절편 자리에 기울기
    assert classify_error(PROBLEMS["LF-12"], "-3") == "OP_01"  # 정답과 부호만 반대


def test_classify_error_non_answer_is_none() -> None:
    assert classify_error(PROBLEMS["LF-01"], "모르겠어요") is None
    assert classify_error(PROBLEMS["LF-01"], "y가 뭐예요?") is None
    assert classify_error(PROBLEMS["LF-01"], "2넣어요?") is None  # 숫자가 있어도 답이 아닌 말
    assert classify_error(PROBLEMS["LF-01"], "7+") == "OP_00"  # 말이 아닌데 못 읽는 입력은 미분류


def test_classify_error_is_deterministic_and_total() -> None:
    """같은 입력 → 같은 코드, 그리고 30문항 어디에 넣어도 표 안의 코드만 나온다."""
    for problem in PROBLEMS.values():
        for text in ("7", "-7", "1/7", "2x+7", "7+", "3×5+2", "7인가"):
            first = classify_error(problem, text)
            assert first == classify_error(problem, text)
            assert first is None or first in OP_CODES


def test_op_codes_doc_matches_code() -> None:
    """golden/sim/op_codes.md의 코드 표가 코드의 OP_CODES와 글자까지 같다."""
    doc = (REPO_ROOT / "golden" / "sim" / "op_codes.md").read_text(encoding="utf-8")
    table = dict(re.findall(r"^\| (OP_\d\d) \| ([^|]+?) \|", doc, flags=re.MULTILINE))
    assert table == OP_CODES
    assert list(OP_CODES) == [f"OP_{n:02d}" for n in range(9)]


# ── 입력 읽기 ────────────────────────────────────────────────────────────


def test_parse_input_spec() -> None:
    assert parse_input_spec("self=a.csv") == InputSpec("self", Path("a.csv"))
    assert parse_input_spec("adult=b.csv@80-115") == InputSpec("adult", Path("b.csv"), 80, 115)
    with pytest.raises(SeedExtractError):
        parse_input_spec("student=a.csv")  # 없는 라벨
    with pytest.raises(SeedExtractError):
        parse_input_spec("a.csv")


def test_read_turns_refuses_identifier_columns(tmp_path: Path) -> None:
    """닉네임·session_id 열이 있는 CSV는 읽지 않는다(공통 규칙 10)."""
    path = _write_csv(tmp_path / "bad.csv", [], header=[*HEADER, "nickname"])
    with pytest.raises(SeedExtractError):
        read_turns(InputSpec("self", path))


def test_read_turns_id_range_splits_one_file(tmp_path: Path) -> None:
    path = _write_csv(
        tmp_path / "mixed.csv",
        [
            _turn(1, "LF-01", "graded", "t", "-12"),
            _turn(2, "LF-01", "graded", "True", "-12"),
        ],
    )
    first = read_turns(InputSpec("self", path, 1, 1))
    second = read_turns(InputSpec("adult", path, 2, 2))
    assert [(r.source, r.row_id, r.correct) for r in first + second] == [
        ("self", 1, True),
        ("adult", 2, True),
    ]


def test_build_records_counts_tutor_turns(tmp_path: Path) -> None:
    path = _write_csv(
        tmp_path / "t.csv",
        [
            _turn(1, "LF-01", "graded", "t", "-12"),  # 첫 입력 정답 = 0턴
            _turn(2, "LF-02", "tutor_turn", "f", "7"),
            _turn(3, "LF-02", "graded", "t", "1"),  # 1턴 뒤 정답
            _turn(4, "LF-03", "tutor_turn", "f", "20"),
            _turn(5, "LF-03", "tutor_turn", "f", "12"),
            _turn(6, "LF-03", "tutor_turn", "f", "-4"),
            _turn(7, "LF-03", "graded", "f", "-4"),  # 3턴 뒤 틀림
            _turn(8, "LF-04", "tutor_turn", "f", "y가 뭐예요?"),  # 판정 없이 끝남
        ],
    )
    records = build_records(read_turns(InputSpec("self", path)))
    assert [(r.problem_id, r.tutor_turns, r.graded, r.correct) for r in records] == [
        ("LF-01", 0, True, True),
        ("LF-02", 1, True, True),
        ("LF-03", 3, True, False),
        ("LF-04", 1, False, False),
    ]


# ── 발화 고르기·출력 모양 ────────────────────────────────────────────────


def _sample_inputs(tmp_path: Path) -> list[InputSpec]:
    self_rows = [
        _turn(1, "LF-01", "tutor_turn", "f", "y가 뭐예요?"),
        _turn(2, "LF-01", "tutor_turn", "f", "18"),
        _turn(3, "LF-01", "graded", "t", "-12"),
        _turn(4, "LF-08", "tutor_turn", "f", "가나중학교에서는 15래요"),
        _turn(5, "LF-08", "graded", "t", "16이요"),
        _turn(6, "LF-07", "tutor_turn", "f", "저는 홍길동이에요"),
        _turn(7, "LF-07", "graded", "f", "9"),
    ]
    adult_rows = [
        _turn(1, "LF-01", "graded", "t", "-12"),
        _turn(2, "LF-13", "tutor_turn", "f", "1/3"),
        _turn(3, "LF-13", "graded", "t", "3"),
    ]
    return [
        InputSpec("self", _write_csv(tmp_path / "self.csv", self_rows)),
        InputSpec("adult", _write_csv(tmp_path / "adult.csv", adult_rows)),
    ]


def test_select_utterances_prefers_speech_and_never_edits(tmp_path: Path) -> None:
    rows = [row for spec in _sample_inputs(tmp_path) for row in read_turns(spec)]
    selected, dropped = select_utterances(rows, count=3)
    texts = [text for text, _ in selected]
    assert dropped == 1  # 자기소개 한 줄은 버린다
    assert texts[0] == "16이요"  # 구어체 가운데 가장 짧은 것부터
    assert "y가 뭐예요?" in texts
    assert all(find_identifiers(text) == [] for text in texts)
    # 고른 발화는 원문(또는 낱말만 가린 원문) 그대로다 — 다듬지 않는다
    originals = {row.student_text for row in rows} | {"[이름]에서는 15래요"}
    assert set(texts) <= originals


def test_extract_output_schema(tmp_path: Path) -> None:
    selected, dist = extract(_sample_inputs(tmp_path))
    out = tmp_path / "seed"
    write_seed(out, selected, dist)

    lines = (out / "utterances.txt").read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(selected) <= seed_extract.SEED_COUNT
    assert all(line.rsplit("\t", 1)[1] in ("self", "adult") for line in lines)
    assert "로컬 Ollama 외 어디로도 보내지 않는다" in (out / "README.md").read_text(
        encoding="utf-8"
    )

    loaded = json.loads((out / "distributions.json").read_text(encoding="utf-8"))
    assert set(loaded) == {
        "note",
        "inputs",
        "turns_from",
        "utterances",
        "turns",
        "errors",
        "op_codes",
    }
    turns = loaded["turns"]
    assert set(turns) == {"definition", "by_source", "combined", "per_problem"}
    assert set(turns["by_source"]) == {"self", "adult"}
    assert turns["by_source"]["self"]["to_correct"] == [2, 1]
    assert turns["by_source"]["self"]["forced_wrong"] == 1
    assert turns["by_source"]["adult"]["median_to_correct"] == 0.5
    assert turns["combined"]["median_to_correct"] == 1.0
    assert turns["per_problem"]["LF-01"] == {"self": [2], "adult": [0]}
    errors = loaded["errors"]
    assert set(errors["combined"]) == set(OP_CODES)
    assert errors["by_source"]["self"]["OP_01"] == 1  # 18 = 15+3
    assert errors["by_source"]["self"]["OP_02"] == 1  # 9 = 2+7
    assert errors["by_source"]["adult"]["OP_03"] == 1
    assert errors["non_answer"] == {"self": 3, "adult": 0}
    assert errors["by_source"]["self"]["OP_00"] == 0
    assert "OP_00" not in errors["top3"]["combined"]
    assert errors["top3"]["adult"] == ["OP_03"]
    assert loaded["utterances"]["collected"] == {"self": 7, "adult": 3}


def test_extract_refuses_when_identifier_survives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """익명화가 망가져 식별 낱말이 남으면 파일을 쓰기 전에 멈춘다(완료 기준 ①의 스크립트 검사)."""
    monkeypatch.setattr(seed_extract, "anonymize", lambda text, names=(): text)
    with pytest.raises(SeedExtractError):
        extract(_sample_inputs(tmp_path))


def test_s13_fallback_gives_turns_only() -> None:
    """원본 CSV가 없을 때 — 저장소의 S13 집계본에서 사람 출처 95건의 턴 수 분포만 낸다."""
    path = REPO_ROOT / "golden" / "reports_no_students" / "S13" / "problems.csv"
    records = records_from_s13(path)
    assert len(records) == 95
    assert {r.source for r in records} == {"self", "adult"}
    selected, dist = extract([], s13_problems=path)
    assert selected == []
    assert dist["errors"] is None
    assert "S13 집계본" in str(dist["turns_from"])


def test_main_prints_counts_not_utterances(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """명령줄 출력에는 건수만 있고 발화 원문은 없다(시드를 화면·로그로 흘리지 않는다)."""
    specs = _sample_inputs(tmp_path)
    args = [f"--input={spec.label}={spec.path}" for spec in specs] + [f"--out={tmp_path / 'o'}"]
    assert seed_extract.main(args) == 0
    printed = capsys.readouterr().out
    assert '"selected"' in printed
    assert "뭐예요" not in printed and "16이요" not in printed


def test_main_refuses_bad_input_with_exit_1(tmp_path: Path) -> None:
    bad = _write_csv(tmp_path / "bad.csv", [], header=[*HEADER, "session_id"])
    assert seed_extract.main([f"--input=self={bad}", f"--out={tmp_path / 'o'}"]) == 1
    assert not (tmp_path / "o").exists()


# ── 시드 반출 금지(공통 규칙 7) ──────────────────────────────────────────


def test_seed_module_imports_no_llm_or_network() -> None:
    """시드를 읽는 모듈은 클라우드 프로바이더·HTTP·튜터를 import하지 않는다."""
    source = Path(seed_extract.__file__).read_text(encoding="utf-8")
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
    )
    banned_golden = ("golden.tutor", "golden.api", "golden.sim_student", "golden.store")
    hits = [name for name in imported if name.split(".")[0] in banned or name in banned_golden]
    assert hits == []


def test_seed_folders_are_gitignored() -> None:
    """golden/sim/.gitignore가 seed/와 out/을 막는다(시드·실행 결과는 커밋 대상이 아니다)."""
    lines = (REPO_ROOT / "golden" / "sim" / ".gitignore").read_text(encoding="utf-8").split()
    assert "seed/" in lines and "out/" in lines
