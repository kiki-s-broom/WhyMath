"""보정 검사(S20 · F-00) — `golden.sim.calibrate`의 세 기준 계산과 블라인드 시트.

지시서 S20 할 일 6: 세 기준 계산 함수의 통과/미통과 픽스처 각 1, 블라인드 시트에 정답 라벨이 섞이지 않음.
더해서: 판정 불가(페르소나 누락·빈칸)를 통과로 세지 않는다 · 결과 파일에 발화 원문이 섞이면 쓰지 않는다 ·
이 모듈은 LLM·네트워크를 import하지 않는다(공통 규칙 7) · 시트·키는 gitignore 대상이다.
시드 원문은 테스트에 없다 — 가짜 시드 20줄을 임시 폴더에 쓴다.
"""

from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from golden.problems import load_problems
from golden.sim.calibrate import (
    AI,
    HUMAN,
    LeakRefusedError,
    ai_utterances,
    assert_no_utterances,
    blind_accuracy,
    build_blind,
    error_criterion,
    parse_key,
    parse_sheet,
    render_blind,
    render_key,
    sheet_fingerprint,
    top_codes,
    turn_criterion,
    verdict,
)

from golden.sim import calibrate

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBLEMS = {p["id"]: p for p in load_problems()}

# 가짜 시드 — 실제 시드와 겹치지 않는 표지 낱말을 넣는다
FAKE_SEEDS = [f"사람말투표지{i:02d} 이거 맞나" for i in range(20)]

# S16 distributions.json과 같은 모양(숫자는 S16 보고의 사람 출처 합산값)
HUMAN_TURNS: dict[str, Any] = {
    "combined": {
        "to_correct": [0] * 61 + [1] * 12 + [2] * 3 + [3] * 2,
        "median_to_correct": 0.0,
        "opened_to_correct": [1] * 12 + [2] * 3 + [3] * 2,
        "median_opened_to_correct": 1.0,
    }
}
HUMAN_ERRORS: dict[str, Any] = {
    "combined": {
        "OP_00": 9,
        "OP_01": 8,
        "OP_02": 3,
        "OP_03": 4,
        "OP_04": 0,
        "OP_05": 1,
        "OP_06": 3,
        "OP_07": 0,
        "OP_08": 0,
    },
    "top3": {"combined": ["OP_01", "OP_03", "OP_02"]},
}


def _turn(n: int, student: str, kind: str, correct: bool) -> dict[str, Any]:
    return {
        "n": n,
        "student": student,
        "tutor": "어느 부분이 막혀?",
        "kind": kind,
        "correct": correct,
    }


def _session(
    persona: str,
    problem_id: str,
    wrong: list[str],
    final_correct: bool = True,
    forced: str | None = None,
    op: str | None = None,
) -> dict[str, Any]:
    """튜터 턴 len(wrong)개 뒤 graded 1줄인 세션 줄."""
    turns = [_turn(i + 1, text, "tutor_turn", False) for i, text in enumerate(wrong)]
    turns.append(_turn(len(wrong) + 1, "정답", "graded", final_correct))
    return {
        "persona": persona,
        "problem_id": problem_id,
        "turns": turns,
        "forced_answer": forced,
        "injected_op": op,
        "elapsed_s": 1.0,
        "http_status": 200,
        "leak": False,
        "render_broken": False,
    }


# ── ① 턴 수 분포 ─────────────────────────────────────────────────────────


def test_turn_criterion_pass() -> None:
    """P5 0턴 · P2·P4 1~2턴 → 전부 중앙값 1 · 열린 것 중앙값 1 → 사람(0·1)과 ±1 안."""
    sessions = [_session("P5", "LF-01", []) for _ in range(3)]
    sessions += [_session("P2", "LF-01", ["9"]) for _ in range(3)]
    sessions += [_session("P4", "LF-01", ["기울기가 뭐예요?", "9"])]
    result = turn_criterion(sessions, HUMAN_TURNS)
    assert result["ai"]["median"] == 1.0 and result["ai"]["median_opened"] == 1.0
    assert result["pass"] is True and result["status"] == "통과"


def test_turn_criterion_fail_when_ai_needs_many_more_turns() -> None:
    """정답까지 늘 3턴 → 전부 중앙값 3(사람 0과 3 차이) → 미통과."""
    sessions = [_session(p, "LF-01", ["9", "8", "7"]) for p in ("P2", "P4", "P5")]
    result = turn_criterion(sessions, HUMAN_TURNS)
    assert result["diff"]["all"] == 3.0
    assert result["pass"] is False and result["status"] == "미통과"


def test_turn_criterion_both_definitions_must_pass() -> None:
    """ⓐ 전부는 ±1 안인데 ⓑ 열린 것만이 3이면 미통과 — 한쪽만 골라 통과시키지 않는다."""
    sessions = [_session("P5", "LF-01", []) for _ in range(5)]
    sessions += [_session(p, "LF-01", ["9", "8", "7"]) for p in ("P2", "P4")]
    result = turn_criterion(sessions, HUMAN_TURNS)
    assert result["diff"]["all"] == 0.0 and result["diff"]["opened"] == 2.0
    assert result["pass"] is False


def test_turn_criterion_missing_persona_is_undecided_not_pass() -> None:
    """야간 스모크 기록(P1·P2·P5·P7)에는 P4가 없다 → 판정 불가(통과로 세지 않는다)."""
    sessions = [_session("P5", "LF-01", []), _session("P2", "LF-01", ["9"])]
    result = turn_criterion(sessions, HUMAN_TURNS)
    assert result["pass"] is None and result["status"] == "판정 불가"
    assert "P4" in result["reason"]


def test_turn_counts_only_correct_200_sessions() -> None:
    """틀리고 끝난 세션·HTTP 실패 세션은 '정답까지 턴'에 넣지 않는다."""
    wrong_end = _session("P2", "LF-01", ["9", "8", "7"], final_correct=False)
    crashed = _session("P2", "LF-01", ["9"]) | {"http_status": 500}
    assert calibrate.session_turns_to_correct(wrong_end) is None
    assert calibrate.session_turns_to_correct(crashed) is None
    assert calibrate.session_turns_to_correct(_session("P4", "LF-01", ["?", "9"])) == 2


# ── ② 오류 유형 분포 ─────────────────────────────────────────────────────


def test_error_criterion_pass() -> None:
    """AI 오답이 OP_01·OP_03·OP_02(사람 상위와 같은 셋) → 겹침 3 → 통과."""
    sessions = [
        _session("P3", "LF-08", ["-14", "-14"]),  # OP_01 × 2
        _session("P3", "LF-13", ["1/3"]),  # OP_03
        _session("P2", "LF-07", ["9"]),  # OP_02
        _session("P2", "LF-01", ["모르겠어요"]),  # 답이 아닌 말
    ]
    result = error_criterion(sessions, HUMAN_ERRORS, PROBLEMS)
    assert result["ai"]["top3"] == ["OP_01", "OP_02", "OP_03"]
    assert result["ai"]["non_answer"] == 1
    assert result["overlap"] == ["OP_01", "OP_02", "OP_03"]
    assert result["pass"] is True


def test_error_criterion_fail() -> None:
    """AI 오답이 OP_04·OP_07·OP_08뿐 → 사람 상위와 겹침 0 → 미통과."""
    sessions = [
        _session("P3", "LF-15", ["-1"]),  # OP_04
        _session("P3", "LF-18", ["6"]),  # OP_07
        _session("P3", "LF-26", ["1"]),  # OP_08
    ]
    result = error_criterion(sessions, HUMAN_ERRORS, PROBLEMS)
    assert result["overlap"] == []
    assert result["pass"] is False and result["status"] == "미통과"


def test_error_criterion_ignores_non_attempt_personas() -> None:
    """P7·P8 오답은 판정 분모에서 빠지고 전 페르소나 참고 표에만 들어간다."""
    sessions = [
        _session("P8", "LF-08", ["-14", "-14", "-14"]),
        _session("P3", "LF-15", ["-1"]),
    ]
    result = error_criterion(sessions, HUMAN_ERRORS, PROBLEMS)
    assert result["ai"]["table"]["OP_01"] == 0
    assert result["ai_all_personas"]["table"]["OP_01"] == 3
    assert result["ai"]["top3"] == ["OP_04"]


def test_error_criterion_injector_agreement_counts_forced_inputs_only() -> None:
    """주입기 답 그대로인 입력만 라벨 일치를 센다 — 분류 규칙 불일치 진단."""
    sessions = [
        _session("P3", "LF-08", ["-14"], forced="-14", op="OP_01"),  # 일치
        _session("P3", "LF-13", ["1/3"], forced="1/3", op="OP_02"),  # 불일치(분류기는 OP_03)
        _session("P2", "LF-07", ["9"]),  # 주입 아님
    ]
    result = error_criterion(sessions, HUMAN_ERRORS, PROBLEMS)
    assert result["injector_agreement"] == {"labelled": 2, "agree": 1}


def test_top_codes_excludes_unclassified_and_breaks_ties_by_code() -> None:
    counts = {"OP_00": 9, "OP_03": 2, "OP_01": 2, "OP_05": 1, "OP_02": 1}
    assert top_codes(counts) == ["OP_01", "OP_03", "OP_02"]


# ── ③ 블라인드 ───────────────────────────────────────────────────────────


def _pool(n: int = 25) -> list[str]:
    return [f"AI말투표지{i:02d} 이게 답인가요" for i in range(n)]


def test_blind_sheet_has_no_labels_and_key_has_no_utterances() -> None:
    items, fingerprint = build_blind(FAKE_SEEDS, _pool(), rng_seed=7)
    assert len(items) == 40
    assert sum(1 for _, label in items if label == HUMAN) == 20
    assert sum(1 for _, label in items if label == AI) == 20
    sheet = render_blind(items, "2026-11-21")
    rows = [line for line in sheet.splitlines() if line.startswith("| ") and "번호" not in line]
    rows = [r for r in rows if not r.startswith("| ---")]
    assert len(rows) == 40
    # 시트의 각 줄 마지막 칸은 비어 있다(정답 라벨이 섞이지 않는다)
    assert all(row.rstrip().endswith("|  |") for row in rows)
    assert "사람말투표지" in sheet and "AI말투표지" in sheet
    for word in ("출처", "self", "adult", "P2", "P3", "P4", "P6"):
        assert word not in "\n".join(rows)
    key = render_key(items, fingerprint)
    assert "표지" not in key  # 키에는 발화 원문이 없다
    assert parse_key(key) == (fingerprint, {i: lab for i, (_, lab) in enumerate(items, 1)})


def test_blind_mixes_sources_not_in_blocks() -> None:
    """섞기가 실제로 일어났다 — 앞 20줄이 전부 사람이 아니다."""
    items, _ = build_blind(FAKE_SEEDS, _pool(), rng_seed=7)
    assert {label for _, label in items[:20]} == {HUMAN, AI}


def test_blind_refuses_small_ai_pool() -> None:
    with pytest.raises(calibrate.CalibrationError, match="AI 후보 발화"):
        build_blind(FAKE_SEEDS, _pool(19), rng_seed=1)


def _filled(items: list[tuple[str, str]], guess: list[str]) -> str:
    sheet = render_blind(items, "2026-11-21")
    lines = sheet.splitlines()
    out, k = [], 0
    for line in lines:
        if line.endswith("|  |") and line[2:].split("|")[0].strip().isdigit():
            line = line[: -len("|  |")] + f"| {guess[k]} |"
            k += 1
        out.append(line)
    return "\n".join(out) + "\n"


def test_blind_accuracy_pass_and_fail() -> None:
    items, fingerprint = build_blind(FAKE_SEEDS, _pool(), rng_seed=3)
    truth = [label for _, label in items]
    # 통과: 40개 중 24개만 맞힘(60%) — 앞 16개를 일부러 뒤집는다
    flipped = [(AI if t == HUMAN else HUMAN) if i < 16 else t for i, t in enumerate(truth)]
    texts, guesses = parse_sheet(_filled(items, flipped))
    assert sheet_fingerprint(texts) == fingerprint
    ok = blind_accuracy(guesses, dict(enumerate(truth, 1)))
    assert ok["accuracy"] == 0.6 and ok["pass"] is True
    # 미통과: 전부 맞힘(100%) — 사람과 AI가 쉽게 갈린다
    texts, guesses = parse_sheet(_filled(items, truth))
    bad = blind_accuracy(guesses, dict(enumerate(truth, 1)))
    assert bad["accuracy"] == 1.0 and bad["pass"] is False


def test_blind_accuracy_blank_is_undecided() -> None:
    """빈칸이 있으면 판정 불가 — 답을 비워 정확도를 낮추는 길을 막는다."""
    items, _ = build_blind(FAKE_SEEDS, _pool(), rng_seed=3)
    truth = [label for _, label in items]
    guess = [AI if t == HUMAN else HUMAN for t in truth]
    guess[5] = " "
    _, guesses = parse_sheet(_filled(items, guess))
    result = blind_accuracy(guesses, dict(enumerate(truth, 1)))
    assert result["pass"] is None and result["blank"] == 1


def test_parse_sheet_accepts_korean_and_lowercase() -> None:
    items, _ = build_blind(FAKE_SEEDS, _pool(), rng_seed=3)
    guess = ["사람" if i % 2 else "a" for i in range(40)]
    _, guesses = parse_sheet(_filled(items, guess))
    assert set(guesses.values()) == {HUMAN, AI}


def test_parse_sheet_keeps_pipes_inside_utterance() -> None:
    items = [("x|y 이거요", HUMAN), ("두 번째", AI)]
    texts, _ = parse_sheet(render_blind(items, "2026-11-21"))
    assert texts == ["x|y 이거요", "두 번째"]


def test_ai_utterances_skip_rule_personas_forced_text_and_seed_copies() -> None:
    sessions = [
        _session("P2", "LF-01", ["음 9인가 ㅁㄹ", "음 9인가 ㅁㄹ"]),  # 중복은 1번
        _session("P3", "LF-08", ["-14"], forced="-14", op="OP_01"),  # 주입기 답 그대로 → 제외
        _session("P5", "LF-01", ["9 맞아요?"]),  # 규칙 페르소나 → 제외
        _session("P4", "LF-01", [FAKE_SEEDS[0]]),  # 시드와 같은 말 → 제외
        _session("P6", "LF-01", ["배고파"]),
    ]
    pool = ai_utterances(sessions, FAKE_SEEDS)
    assert "음 9인가 ㅁㄹ" in pool and "배고파" in pool
    assert "-14" not in pool and "9 맞아요?" not in pool and FAKE_SEEDS[0] not in pool
    assert "정답" in pool  # graded 줄의 학생 발화(P2·P4·P6)도 후보다


# ── 판정·출력 ────────────────────────────────────────────────────────────


def test_verdict_words() -> None:
    def _r(a: bool | None, b: bool | None, c: bool | None) -> dict[str, Any]:
        return {"turns": {"pass": a}, "errors": {"pass": b}, "blind": {"pass": c}}

    assert verdict(_r(True, True, True)) == "통과"
    assert verdict(_r(True, False, None)) == "미통과 — 기준 2"
    assert verdict(_r(False, True, False)) == "미통과 — 기준 1,3"
    assert verdict(_r(True, True, None)) == "대기 — 기준 3 판정 전"


def test_assert_no_utterances_refuses() -> None:
    with pytest.raises(LeakRefusedError):
        assert_no_utterances('{"x": "사람말투표지03 이거 맞나"}', FAKE_SEEDS)
    assert_no_utterances('{"x": 1}', FAKE_SEEDS)


def _write_seed(seed_dir: Path) -> None:
    seed_dir.mkdir()
    (seed_dir / "utterances.txt").write_text(
        "".join(f"{s}\tself\n" for s in FAKE_SEEDS), encoding="utf-8"
    )
    (seed_dir / "distributions.json").write_text(
        json.dumps({"turns": HUMAN_TURNS, "errors": HUMAN_ERRORS}, ensure_ascii=False),
        encoding="utf-8",
    )


def _write_sessions(path: Path) -> None:
    # 고유한 말(숫자 없음 · 분류기가 답이 아닌 말로 본다) — 블라인드 AI 후보 20개 이상
    words = "가나다라마바사아자차카타파하거너더러머버서어"
    rows = [_session("P5", "LF-01", []) for _ in range(30)]
    rows += [_session("P2", "LF-08", ["-14요"]) for _ in range(4)]  # OP_01
    rows += [_session("P3", "LF-13", ["1/3"], forced="1/3", op="OP_03") for _ in range(3)]
    rows += [_session("P2", "LF-07", ["9"]) for _ in range(2)]  # OP_02
    rows += [_session("P4", "LF-07", [f"기울기 {w}게 뭐예요 아닌가", "9"]) for w in words]
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")
    _write_meta(path, len(rows))


def _write_meta(path: Path, n: int, mode: str = "live", planned: int | None = None) -> None:
    """러너가 jsonl 옆에 쓰는 run_meta.json(완주 대조에 쓰는 칸만)."""
    meta = {
        "mode": mode,
        "planned_sessions": n if planned is None else planned,
        "count_sessions": n,
    }
    (path.parent / "run_meta.json").write_text(json.dumps(meta), encoding="utf-8")


def test_main_check_then_score_end_to_end(tmp_path: Path) -> None:
    """check → 시트·키·결과 JSON·CALIBRATION.md → Kiki가 채움 → score → 최종 판정."""
    seed_dir, jsonl = tmp_path / "seed", tmp_path / "sessions.jsonl"
    _write_seed(seed_dir)
    _write_sessions(jsonl)
    paths = {
        "--blind": tmp_path / "blind.md",
        "--key": tmp_path / "key.txt",
        "--result": tmp_path / "out" / "calibration.json",
        "--doc": tmp_path / "CALIBRATION.md",
    }
    common = ["--seed-dir", str(seed_dir), "--date", "2026-11-21"]
    for flag, path in paths.items():
        common += [flag, str(path)]
    code = calibrate.main(["check", *common, "--sessions", str(jsonl), "--blind-seed", "11"])
    assert code == 0
    result = json.loads(paths["--result"].read_text(encoding="utf-8"))
    assert result["verdict"] == "대기 — 기준 3 판정 전"
    assert result["turns"]["pass"] is True and result["errors"]["pass"] is True
    doc = paths["--doc"].read_text(encoding="utf-8")
    assert doc.splitlines()[0] == "대기 (2026-11-21) — 기준 3 판정 전 · 실학생 0명"
    assert "실제 중학생 0명" in doc and "진실 트랙만 말할 수 있다" in doc
    for word in ("이탈률", "세션 길이", "만족도"):
        assert word in doc
    # 결과 파일에는 발화 원문이 없다(시트에는 있다)
    for output in (paths["--result"], paths["--doc"]):
        text = output.read_text(encoding="utf-8")
        assert "표지" not in text and "아닌가" not in text
    assert "사람말투표지" in paths["--blind"].read_text(encoding="utf-8")

    # 두 번째 check는 시트를 덮어쓰지 않는다(Kiki가 보던 시트가 바뀌지 않게)
    before = paths["--blind"].read_text(encoding="utf-8")
    assert calibrate.main(["check", *common, "--sessions", str(jsonl)]) == 0
    assert paths["--blind"].read_text(encoding="utf-8") == before

    # Kiki가 전부 반대로 적음 → 정확도 0 → 통과
    _, labels = parse_key(paths["--key"].read_text(encoding="utf-8"))
    sheet = before.splitlines()
    filled = []
    for line in sheet:
        head = line[2:].split("|")[0].strip() if line.startswith("| ") else ""
        if head.isdigit():
            line = line[: -len("|  |")] + f"| {AI if labels[int(head)] == HUMAN else HUMAN} |"
        filled.append(line)
    paths["--blind"].write_text("\n".join(filled) + "\n", encoding="utf-8")
    assert calibrate.main(["score", *common]) == 0
    final = json.loads(paths["--result"].read_text(encoding="utf-8"))
    assert final["verdict"] == "통과" and final["blind"]["accuracy"] == 0.0
    assert paths["--doc"].read_text(encoding="utf-8").startswith("통과 (2026-11-21) · 실학생 0명\n")


def test_main_score_refuses_edited_sheet(tmp_path: Path) -> None:
    """시트 발화를 고치면 지문이 달라져 채점하지 않는다(exit 2)."""
    seed_dir, jsonl = tmp_path / "seed", tmp_path / "sessions.jsonl"
    _write_seed(seed_dir)
    _write_sessions(jsonl)
    common = ["--seed-dir", str(seed_dir), "--date", "2026-11-21"]
    for flag, name in (("--blind", "b.md"), ("--key", "k.txt"), ("--result", "r.json")):
        common += [flag, str(tmp_path / name)]
    common += ["--doc", str(tmp_path / "C.md")]
    assert calibrate.main(["check", *common, "--sessions", str(jsonl), "--blind-seed", "5"]) == 0
    sheet = (tmp_path / "b.md").read_text(encoding="utf-8").replace("표지00", "표지99")
    (tmp_path / "b.md").write_text(sheet, encoding="utf-8")
    assert calibrate.main(["score", *common]) == 2


def test_main_refuses_missing_seed_with_exit_2(tmp_path: Path) -> None:
    jsonl = tmp_path / "s.jsonl"
    _write_sessions(jsonl)
    code = calibrate.main(
        ["check", "--seed-dir", str(tmp_path / "없음"), "--sessions", str(jsonl)]
        + ["--result", str(tmp_path / "r.json"), "--doc", str(tmp_path / "C.md")]
        + ["--blind", str(tmp_path / "b.md"), "--key", str(tmp_path / "k.txt")]
    )
    assert code == 2
    assert not (tmp_path / "r.json").exists()


# ── 시드 반출 금지(공통 규칙 7) ──────────────────────────────────────────


def test_calibrate_imports_no_llm_or_network() -> None:
    """시드를 읽는 이 모듈은 클라우드 프로바이더·HTTP·튜터를 import하지 않는다."""
    source = Path(calibrate.__file__).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert imported, "import를 하나도 못 찾았다 — 검사가 공허하다"
    banned = ("whymath_backend", "httpx", "requests", "urllib", "socket", "ollama", "openai")
    banned_golden = (
        "golden.tutor",
        "golden.api",
        "golden.sim_student",
        "golden.store",
        "golden.sim.student",
        "golden.sim.ollama_client",
        "golden.sim.run",
        "golden.llm",
    )
    hits = [n for n in imported if n.split(".")[0] in banned or n.startswith(banned_golden)]
    assert hits == []


@pytest.mark.parametrize("name", ["CALIBRATION_blind.md", "CALIBRATION_key.txt"])
def test_blind_sheet_and_key_are_gitignored(name: str) -> None:
    """시트(시드 원문 포함)와 정답 키는 커밋 대상이 아니다 — git이 실제로 무시하는지 본다."""
    rel = f"golden/sim/{name}"
    done = subprocess.run(
        ["git", "check-ignore", "-q", rel], cwd=REPO_ROOT, capture_output=True, check=False
    )
    assert done.returncode == 0, f"{rel}이 gitignore되지 않는다"


def test_calibration_doc_is_not_ignored() -> None:
    """CALIBRATION.md(숫자만)는 커밋 대상이다 — 무시 규칙이 너무 넓지 않은지."""
    done = subprocess.run(
        ["git", "check-ignore", "-q", "golden/sim/CALIBRATION.md"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    assert done.returncode == 1


def _check_args(tmp_path: Path, jsonl: Path) -> list[str]:
    seed_dir = tmp_path / "seed"
    if not seed_dir.exists():
        _write_seed(seed_dir)
    return [
        "check",
        "--seed-dir",
        str(seed_dir),
        "--sessions",
        str(jsonl),
        "--blind",
        str(tmp_path / "b.md"),
        "--key",
        str(tmp_path / "k.txt"),
        "--result",
        str(tmp_path / "r.json"),
        "--doc",
        str(tmp_path / "C.md"),
    ]


@pytest.mark.parametrize(
    ("meta", "why"),
    [
        (None, "보고서 없음(도중에 죽음)"),
        ({"planned": 120}, "계획 120 · 줄 수 적음(S20 실측 46/120)"),
        ({"mode": "fake"}, "가짜 모드"),
    ],
)
def test_check_refuses_incomplete_or_fake_run(
    tmp_path: Path, meta: dict[str, Any] | None, why: str
) -> None:
    """끝까지 돈 실제 실행이 아니면 판정하지 않는다(exit 2 · 결과 파일 안 씀)."""
    jsonl = tmp_path / "sessions.jsonl"
    _write_sessions(jsonl)
    rows = len(jsonl.read_text(encoding="utf-8").splitlines())
    if meta is None:
        (tmp_path / "run_meta.json").unlink()
    else:
        _write_meta(jsonl, rows, mode=meta.get("mode", "live"), planned=meta.get("planned"))
    assert calibrate.main(_check_args(tmp_path, jsonl)) == 2, why
    assert not (tmp_path / "r.json").exists()
