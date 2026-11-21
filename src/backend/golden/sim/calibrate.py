"""보정 검사(S20 · 관문 ① · F-00) — AI 학생 시뮬레이터가 사람 출처를 닮았는지 세 기준으로 잰다.

실행(저장소의 src/backend 폴더 · Kiki 머신 — 시드와 실제 실행 기록이 거기에만 있다):
    python -m golden.sim.calibrate check --sessions <실제 실행 sessions.jsonl> [--sessions ...]
    (Kiki가 CALIBRATION_blind.md 마지막 열에 H/A를 채운 뒤)
    python -m golden.sim.calibrate score

세 기준(공유 계약 「시뮬레이터 입출력 모양」):
- ① 턴 수 분포 — P2·P4·P5 합산 "정답까지 튜터 턴 수" 중앙값이 사람 출처 중앙값 ±1턴.
  같은 정의를 두 가지로 잰다(S16 `distributions.json`의 두 칸): ⓐ 정답으로 끝난 기록 전부
  (첫 입력 정답 = 0) ⓑ 그중 튜터가 한 번 이상 열린 기록만. **둘 다** ±1이어야 통과다(더 엄격한 쪽 —
  한쪽만 골라 통과시키지 않는다). P2·P4·P5 중 하나라도 기록이 없으면 판정 불가(통과 아님).
- ② 오류 유형 분포 — AI 오답 입력을 사람 출처와 **같은 분류기**(`seed_extract.classify_error`)로
  OP 코드에 넣고, 미분류(OP_00)를 뺀 상위 3개가 사람 출처 합산 상위 3개와 2개 이상 겹치면 통과.
  AI 쪽 분모는 문제를 풀려는 페르소나(P2·P3·P4·P5·P6)의 오답 입력이다 — P1(답만 요구)·P7(적대)·
  P8(아무 숫자)은 사람 출처에 대응하는 행동이 없어 뺀다(전 페르소나 표는 참고로 함께 낸다).
- ③ 블라인드 — 사람 발화 20(시드) + AI 발화 20(실제 실행분 · 로컬 Ollama가 말투를 입힌
  P2·P3·P4·P6의 학생 발화)을 무작위로 섞어 번호만 붙인 시트를 만든다. Kiki가 H(사람)/A(AI)를 적으면
  정확도를 계산한다. 70% 이하면 통과(구분이 어려울수록 좋다).

시드 반출 금지(공통 규칙 7): 블라인드 시트(`CALIBRATION_blind.md`)와 정답 키
(`CALIBRATION_key.txt`)에는 시드 원문이 들어가므로 둘 다 `golden/sim/.gitignore`로 막고
이 PC에만 둔다. 결과 JSON(`calibration.json`)과 `CALIBRATION.md`에는 숫자만 쓴다 — 쓰기 전에
발화 원문이 섞였는지 검사하고 섞였으면 쓰지 않는다(exit 3). 이 모듈은 LLM·네트워크를 부르지
않는다(테스트가 import를 동결).

통과 전 시뮬레이터 숫자는 튜터 판단에 쓰지 않는다(계획서 원칙 3). 미통과면 고칠 것은 튜터가 아니라
시뮬레이터(`seed/`·`personas.md`·`errors.py`·`student.py`)다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import random
import secrets
import statistics
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from golden.problems import Problem, load_problems
from golden.sim.seed_extract import OP_CODES, REPO_ROOT, SEED_COUNT, SEED_DIR, classify_error

# ──────────────────────────────────────────────────────────────────────
# 상수(공유 계약)
# ──────────────────────────────────────────────────────────────────────

SIM_DIR = REPO_ROOT / "golden" / "sim"
BLIND_PATH = SIM_DIR / "CALIBRATION_blind.md"
KEY_PATH = SIM_DIR / "CALIBRATION_key.txt"
DOC_PATH = SIM_DIR / "CALIBRATION.md"
RESULT_PATH = REPO_ROOT / "golden" / "reports_phase1" / "S20" / "calibration.json"
# 러너(S19)가 sessions.jsonl 옆에 쓰는 보조 숫자 파일 — 완주 여부 대조용
META_NAME = "run_meta.json"

# ① 턴 수 — 비교 페르소나와 허용 폭(턴)
TURN_PERSONAS = ("P2", "P4", "P5")
TURN_TOLERANCE = 1.0

# ② 오류 유형 — 문제를 풀려는 페르소나만(모듈 설명 참고) · 겹침 최소 수
ERROR_PERSONAS = ("P2", "P3", "P4", "P5", "P6")
TOP_K = 3
OVERLAP_MIN = 2

# ③ 블라인드 — 각 출처 발화 수 · 통과 상한 정확도 · AI 발화를 뽑는 페르소나(로컬 Ollama 말투)
BLIND_PER_SOURCE = SEED_COUNT
BLIND_MAX_ACCURACY = 0.70
VOICED_PERSONAS = ("P2", "P3", "P4", "P6")
HUMAN, AI = "H", "A"

# 정답 키 파일의 머리 줄(키 검증용)
_KEY_HEADER = "# CALIBRATION_key v1"

# 첫 줄 꼬리(공유 계약 첫 표 — "실학생 0"을 CALIBRATION.md 첫 줄에 적는다 · 2026-11-21 현재 0명)
REAL_STUDENTS_NOTE = " · 실학생 0명"

# 진실 트랙만 말할 수 있는 것(지시서 S20 할 일 3)
NOT_COMPARABLE: tuple[tuple[str, str], ...] = (
    ("이탈률", "AI 학생은 중간에 그만두지 않는다 — 러너가 끝까지 돌린다(항상 0)"),
    (
        "세션 길이",
        "AI 학생은 지루해하거나 지치지 않는다 — 시간·문항 수가 사람 행동을 닮을 이유가 없다",
    ),
    ("만족도", "AI 학생은 '다시 할래?'에 답할 감정이 없다"),
)


class CalibrationError(RuntimeError):
    """보정 검사를 계속할 수 없는 입력 오류(파일 없음·모양 틀림·키 불일치)."""


class LeakRefusedError(RuntimeError):
    """결과 파일에 발화 원문이 섞였다 — 쓰지 않는다(시드 반출 금지)."""


# ──────────────────────────────────────────────────────────────────────
# 입력 읽기
# ──────────────────────────────────────────────────────────────────────


def load_sessions(paths: Sequence[Path]) -> list[dict[str, Any]]:
    """sessions.jsonl 여러 개를 읽는다(한 줄 = 세션 1개 · 빈 줄 무시)."""
    rows: list[dict[str, Any]] = []
    for path in paths:
        if not path.is_file():
            raise CalibrationError(f"실행 기록이 없다: {path}")
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict) or "persona" not in row or "turns" not in row:
                raise CalibrationError(f"{path.name}:{number} 세션 줄 모양이 아니다")
            rows.append(row)
    if not rows:
        raise CalibrationError("실행 기록에 세션이 0개다 — 빈 입력으로는 판정하지 않는다")
    return rows


def check_complete(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    """실행 기록이 끝까지 돈 실제(live) 실행 하나의 것인지 — 옆의 `run_meta.json`과 대조한다.

    러너가 도중에 죽으면 `sessions.jsonl`은 앞부분만 남고 보고서는 없다(또는 지난 실행 것이 남는다).
    그런 기록으로 판정하면 숫자가 틀어지므로 거부한다. 가짜 모드(고정 대본)는 보정 대상이 아니다.
    (S20 · 2026-11-21 Kiki 머신 실측: 120세션 계획 중 46줄만 남은 기록 옆에
    앞 실행의 보고서가 있었다)
    """
    meta_path = path.parent / META_NAME
    if not meta_path.is_file():
        raise CalibrationError(f"{META_NAME}이 없다 — 실행이 끝나지 않았다: {path.parent}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("mode") != "live":
        raise CalibrationError(f"가짜 모드 기록은 보정 대상이 아니다(mode={meta.get('mode')})")
    planned, counted = meta.get("planned_sessions"), meta.get("count_sessions")
    if planned != len(rows) or counted != len(rows):
        raise CalibrationError(
            f"{path.name} {len(rows)}줄 ≠ 보고서 계획 {planned}·집계 {counted} — "
            "실행이 중간에 멈췄거나 보고서가 다른 실행 것이다(다시 돌린다)"
        )


def load_distributions(seed_dir: Path) -> dict[str, Any]:
    """S16 `distributions.json`(사람 출처 분포)."""
    path = seed_dir / "distributions.json"
    if not path.is_file():
        raise CalibrationError(f"사람 출처 분포가 없다: {path} (S16 시드 — Kiki 머신에만 있다)")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "turns" not in data or not data.get("errors"):
        raise CalibrationError("distributions.json에 turns·errors가 없다")
    return data


def load_seed_texts(seed_dir: Path) -> list[str]:
    """S16 `utterances.txt`(발화<TAB>라벨 20줄)의 발화만."""
    path = seed_dir / "utterances.txt"
    if not path.is_file():
        raise CalibrationError(f"시드 발화가 없다: {path} (S16 — Kiki 머신에만 있다)")
    texts = [line.split("\t")[0] for line in path.read_text(encoding="utf-8").splitlines()]
    texts = [t for t in texts if t.strip()]
    if len(texts) != SEED_COUNT:
        raise CalibrationError(f"시드 발화가 {len(texts)}줄이다({SEED_COUNT}줄이어야 한다)")
    return texts


# ──────────────────────────────────────────────────────────────────────
# ① 턴 수 분포
# ──────────────────────────────────────────────────────────────────────


def session_turns_to_correct(row: Mapping[str, Any]) -> int | None:
    """정답으로 끝난 세션의 튜터 턴 수(첫 입력 정답 = 0). 정답으로 안 끝났으면 None.

    사람 출처 정의(`seed_extract.build_records`)와 같다: graded 앞의 tutor_turn 줄 수.
    """
    if row.get("http_status") != 200:
        return None
    turns = row.get("turns") or []
    if not turns:
        return None
    last = turns[-1]
    if last.get("kind") != "graded" or not last.get("correct"):
        return None
    return sum(1 for turn in turns if turn.get("kind") == "tutor_turn")


def _median(values: Sequence[int]) -> float | None:
    """중앙값. 빈 목록이면 None."""
    return float(statistics.median(values)) if values else None


def turn_criterion(
    sessions: Sequence[Mapping[str, Any]], human_turns: Mapping[str, Any]
) -> dict[str, Any]:
    """기준 ① — P2·P4·P5 합산 중앙값 vs 사람 출처 합산 중앙값(ⓐ 전부 · ⓑ 열린 것만)."""
    combined = human_turns.get("combined") or {}
    human_all = combined.get("median_to_correct")
    human_opened = combined.get("median_opened_to_correct")
    per_persona: dict[str, dict[str, Any]] = {}
    to_correct: list[int] = []
    for persona in TURN_PERSONAS:
        rows = [r for r in sessions if r.get("persona") == persona]
        values = [v for r in rows if (v := session_turns_to_correct(r)) is not None]
        per_persona[persona] = {
            "sessions": len(rows),
            "to_correct": len(values),
            "median_to_correct": _median(values),
        }
        to_correct.extend(values)
    opened = [v for v in to_correct if v > 0]
    ai_all, ai_opened = _median(to_correct), _median(opened)
    missing = [p for p, info in per_persona.items() if info["sessions"] == 0]

    def _diff(ai: float | None, human: object) -> float | None:
        if ai is None or not isinstance(human, (int, float)):
            return None
        return round(abs(ai - float(human)), 3)

    diff_all, diff_opened = _diff(ai_all, human_all), _diff(ai_opened, human_opened)
    if missing or diff_all is None or diff_opened is None:
        status = "판정 불가"
        reason = (
            f"페르소나 기록 없음: {','.join(missing)}"
            if missing
            else "중앙값을 낼 정답 세션이 없다(AI 또는 사람)"
        )
        passed: bool | None = None
    else:
        passed = diff_all <= TURN_TOLERANCE and diff_opened <= TURN_TOLERANCE
        status = "통과" if passed else "미통과"
        reason = f"|차이| ⓐ {diff_all} · ⓑ {diff_opened} (허용 {TURN_TOLERANCE}턴 — 둘 다)"
    return {
        "definition": "정답으로 끝난 세션의 튜터 턴 수(첫 입력 정답 = 0)"
        " · ⓐ 전부 · ⓑ 튜터가 열린 것만",
        "personas": list(TURN_PERSONAS),
        "per_persona": per_persona,
        "ai": {
            "n": len(to_correct),
            "median": ai_all,
            "n_opened": len(opened),
            "median_opened": ai_opened,
        },
        "human": {
            "n": len(combined.get("to_correct") or []),
            "median": human_all,
            "n_opened": len(combined.get("opened_to_correct") or []),
            "median_opened": human_opened,
        },
        "diff": {"all": diff_all, "opened": diff_opened},
        "tolerance": TURN_TOLERANCE,
        "status": status,
        "pass": passed,
        "reason": reason,
    }


# ──────────────────────────────────────────────────────────────────────
# ② 오류 유형 분포
# ──────────────────────────────────────────────────────────────────────


def top_codes(counts: Mapping[str, int], k: int = TOP_K) -> list[str]:
    """미분류(OP_00)를 뺀 상위 k개 — 동률은 코드 순(S16 `seed_extract`와 같은 규칙)."""
    ranked = sorted(
        ((c, n) for c, n in counts.items() if n > 0), key=lambda item: (-item[1], item[0])
    )
    return [code for code, _ in ranked if code != "OP_00"][:k]


@dataclass(frozen=True)
class WrongInput:
    """AI 세션의 오답 입력 1건(분류 결과만 — 원문은 들고 다니지 않는다)."""

    persona: str
    code: str | None  # None = 답이 아닌 말
    injected_op: str | None  # 이 입력이 주입기 답 그대로일 때 주입기가 단 라벨


def ai_wrong_inputs(
    sessions: Sequence[Mapping[str, Any]], problems: Mapping[str, Problem]
) -> list[WrongInput]:
    """AI 세션에서 오답 처리된 학생 입력을 사람 출처와 같은 분류기로 분류한다."""
    out: list[WrongInput] = []
    for row in sessions:
        problem = problems.get(str(row.get("problem_id")))
        if problem is None:
            continue
        forced = row.get("forced_answer")
        for turn in row.get("turns") or []:
            text = str(turn.get("student") or "")
            if turn.get("correct") or not text.strip():
                continue
            injected = (
                row.get("injected_op") if forced and text.strip() == str(forced).strip() else None
            )
            out.append(WrongInput(str(row.get("persona")), classify_error(problem, text), injected))
    return out


def _code_table(inputs: Iterable[WrongInput]) -> tuple[dict[str, int], int]:
    """(OP 코드 빈도 표, 답이 아닌 말 수)."""
    counter: Counter[str] = Counter()
    non_answer = 0
    for item in inputs:
        if item.code is None:
            non_answer += 1
        else:
            counter[item.code] += 1
    return {code: counter.get(code, 0) for code in OP_CODES}, non_answer


def error_criterion(
    sessions: Sequence[Mapping[str, Any]],
    human_errors: Mapping[str, Any],
    problems: Mapping[str, Problem],
) -> dict[str, Any]:
    """기준 ② — AI 상위 3개 OP(미분류 제외)와 사람 출처 합산 상위 3개의 겹침 수."""
    human_top = list((human_errors.get("top3") or {}).get("combined") or [])
    human_table = dict(human_errors.get("combined") or {})
    every = ai_wrong_inputs(sessions, problems)
    chosen = [w for w in every if w.persona in ERROR_PERSONAS]
    table, non_answer = _code_table(chosen)
    all_table, all_non_answer = _code_table(every)
    ai_top = top_codes(table)
    overlap = sorted(set(ai_top) & set(human_top))
    classified = sum(n for c, n in table.items() if c != "OP_00")
    # 주입기 라벨과 사람 분류기의 일치율 — 원인 후보 "분류 규칙 불일치"를 가르는 진단 숫자
    labelled = [w for w in chosen if w.injected_op]
    agree = sum(1 for w in labelled if w.code == w.injected_op)
    if not human_top:
        status, passed, reason = "판정 불가", None, "사람 출처 상위 코드가 없다"
    elif classified == 0:
        status, passed, reason = "판정 불가", None, "AI 오답 중 분류된 것이 0건"
    else:
        passed = len(overlap) >= OVERLAP_MIN
        status = "통과" if passed else "미통과"
        reason = f"겹침 {len(overlap)}개(필요 {OVERLAP_MIN}개 이상)"
    return {
        "definition": "오답 처리된 학생 입력의 OP 코드"
        "(seed_extract.classify_error · 미분류 OP_00 제외 상위 3개)",
        "personas": list(ERROR_PERSONAS),
        "ai": {
            "wrong_inputs": len(chosen),
            "non_answer": non_answer,
            "table": table,
            "top3": ai_top,
            "unclassified_share": round(table["OP_00"] / max(1, len(chosen) - non_answer), 3),
        },
        "ai_all_personas": {
            "wrong_inputs": len(every),
            "non_answer": all_non_answer,
            "table": all_table,
        },
        "human": {
            "wrong_inputs": sum(human_table.values()),
            "table": human_table,
            "top3": human_top,
        },
        "overlap": overlap,
        "overlap_min": OVERLAP_MIN,
        "injector_agreement": {"labelled": len(labelled), "agree": agree},
        "status": status,
        "pass": passed,
        "reason": reason,
    }


# ──────────────────────────────────────────────────────────────────────
# ③ 블라인드
# ──────────────────────────────────────────────────────────────────────


def _flat(text: str) -> str:
    """공백을 지운 비교용 문자열."""
    return "".join(text.split())


def ai_utterances(sessions: Sequence[Mapping[str, Any]], seeds: Sequence[str]) -> list[str]:
    """블라인드 후보 AI 발화 — 로컬 Ollama 말투 페르소나의 학생 발화(중복·빈 말·시드 같은 말 제외).

    주입기 답과 글자가 똑같은 발화는 모델이 아니라 규칙이 만든 말이라 뺀다(말투 검사가 목적).
    """
    seed_flats = {_flat(s) for s in seeds}
    seen: set[str] = set()
    out: list[str] = []
    for row in sessions:
        if row.get("persona") not in VOICED_PERSONAS:
            continue
        forced = _flat(str(row.get("forced_answer") or ""))
        for turn in row.get("turns") or []:
            text = " ".join(str(turn.get("student") or "").split())
            flat = _flat(text)
            if not flat or flat == forced or flat in seed_flats or flat in seen:
                continue
            seen.add(flat)
            out.append(text)
    return sorted(out)


def _cell(text: str) -> str:
    """표 칸에 넣을 수 있게 `|`를 가린다."""
    return text.replace("|", "\\|")


def build_blind(
    seeds: Sequence[str], ai_pool: Sequence[str], rng_seed: int
) -> tuple[list[tuple[str, str]], str]:
    """(번호 순 [(발화, 출처)], 시트 지문). 사람 20 + AI 20을 섞는다."""
    if len(seeds) != BLIND_PER_SOURCE:
        raise CalibrationError(f"사람 발화가 {len(seeds)}개다({BLIND_PER_SOURCE}개 필요)")
    if len(ai_pool) < BLIND_PER_SOURCE:
        raise CalibrationError(
            f"AI 후보 발화가 {len(ai_pool)}개뿐이다({BLIND_PER_SOURCE}개 필요) — "
            f"{'·'.join(VOICED_PERSONAS)}가 든 실제 실행 기록을 넣는다"
        )
    rng = random.Random(rng_seed)
    picked = rng.sample(list(ai_pool), BLIND_PER_SOURCE)
    items = [(" ".join(s.split()), HUMAN) for s in seeds] + [(t, AI) for t in picked]
    rng.shuffle(items)
    return items, sheet_fingerprint([text for text, _ in items])


def sheet_fingerprint(texts: Sequence[str]) -> str:
    """시트 발화 목록의 지문(키와 시트가 같은 회차인지 확인)."""
    return hashlib.sha256("\n".join(texts).encode("utf-8")).hexdigest()[:16]


def render_blind(items: Sequence[tuple[str, str]], date: str) -> str:
    """블라인드 시트 — 번호와 발화만. 출처 라벨은 넣지 않는다."""
    lines = [
        f"# 보정 블라인드 시트 (S20 · {date})",
        "",
        "> 이 파일은 이 PC에만 둔다(시드 원문 포함 · gitignore). 세션·채팅에 붙이지 않는다.",
        "> 각 줄 마지막 칸에 사람이 쓴 말 같으면 `H`, AI가 만든 말 같으면 `A`를 적고 저장한다.",
        f"> 사람 {BLIND_PER_SOURCE}줄·AI {BLIND_PER_SOURCE}줄이 섞여 있다. 다 적은 뒤 "
        "`python -m golden.sim.calibrate score`를 돌린다.",
        "",
        "| 번호 | 발화 | 추측(H/A) |",
        "| --- | --- | --- |",
    ]
    lines += [f"| {i} | {_cell(text)} |  |" for i, (text, _) in enumerate(items, 1)]
    return "\n".join(lines) + "\n"


def render_key(items: Sequence[tuple[str, str]], fingerprint: str) -> str:
    """정답 키 — 번호<TAB>출처. 발화 원문은 넣지 않는다(지문으로 시트와 짝을 맞춘다)."""
    lines = [_KEY_HEADER, f"# fingerprint\t{fingerprint}"]
    lines += [f"{i}\t{label}" for i, (_, label) in enumerate(items, 1)]
    return "\n".join(lines) + "\n"


def parse_key(text: str) -> tuple[str, dict[int, str]]:
    """(지문, {번호: 출처})."""
    lines = text.splitlines()
    if not lines or lines[0] != _KEY_HEADER:
        raise CalibrationError("정답 키 머리 줄이 다르다")
    fingerprint = ""
    labels: dict[int, str] = {}
    for line in lines[1:]:
        if line.startswith("# fingerprint\t"):
            fingerprint = line.split("\t", 1)[1].strip()
        elif line.strip():
            number, label = line.split("\t")
            labels[int(number)] = label.strip()
    return fingerprint, labels


_GUESS = {"H": HUMAN, "사람": HUMAN, "A": AI, "AI": AI}


def parse_sheet(text: str) -> tuple[list[str], dict[int, str | None]]:
    """채운 시트 → (발화 목록(번호 순), {번호: 추측 H/A 또는 None(빈칸·알 수 없는 값)})."""
    texts: list[str] = []
    guesses: dict[int, str | None] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if (
            not stripped.startswith("|")
            or stripped.startswith("| 번호")
            or stripped.startswith("| ---")
        ):
            continue
        body, _, guess = stripped.rstrip("|").rpartition("|")
        number_text, _, utterance = body.lstrip("|").partition("|")
        if not number_text.strip().isdigit():
            continue
        texts.append(utterance.strip().replace("\\|", "|"))
        raw = guess.strip()
        guesses[int(number_text)] = _GUESS.get(raw.upper() if raw.isascii() else raw)
    return texts, guesses


def blind_accuracy(guesses: Mapping[int, str | None], labels: Mapping[int, str]) -> dict[str, Any]:
    """정확도 = 맞힌 수 ÷ 전체. 빈칸이 하나라도 있으면 판정 불가다.

    빈칸을 틀린 것으로 세면 답을 비워 정확도를 낮출 수 있다 — 그래서 빈칸은 통과·미통과가 아니다.
    """
    total = len(labels)
    blank = sorted(n for n in labels if guesses.get(n) is None)
    correct = sum(1 for n, label in labels.items() if guesses.get(n) == label)
    accuracy = correct / total if total else 0.0
    if blank:
        status, passed = "판정 불가", None
        reason = f"빈칸 {len(blank)}개 — 모두 채운 뒤 다시"
    else:
        passed = accuracy <= BLIND_MAX_ACCURACY
        status = "통과" if passed else "미통과"
        reason = f"정확도 {accuracy:.1%}(통과 상한 {BLIND_MAX_ACCURACY:.0%})"
    return {
        "items": total,
        "correct": correct,
        "accuracy": round(accuracy, 3),
        "blank": len(blank),
        "threshold": BLIND_MAX_ACCURACY,
        "status": status,
        "pass": passed,
        "reason": reason,
    }


# ──────────────────────────────────────────────────────────────────────
# 판정·출력
# ──────────────────────────────────────────────────────────────────────


def verdict(result: Mapping[str, Any]) -> str:
    """첫 줄 판정 — 통과 / 미통과 — 기준 N / 대기(블라인드 전)."""
    failed = [
        str(i)
        for i, key in enumerate(("turns", "errors", "blind"), 1)
        if result[key].get("pass") is False
    ]
    if failed:
        return f"미통과 — 기준 {','.join(failed)}"
    if all(result[key].get("pass") is True for key in ("turns", "errors", "blind")):
        return "통과"
    pending = [
        str(i)
        for i, key in enumerate(("turns", "errors", "blind"), 1)
        if result[key].get("pass") is None
    ]
    return f"대기 — 기준 {','.join(pending)} 판정 전"


def assert_no_utterances(text: str, utterances: Iterable[str]) -> None:
    """결과 문자열에 발화 원문(공백 무시 · 4글자 이상)이 섞였으면 LeakRefusedError."""
    flat = _flat(text)
    hits = [u for u in utterances if len(_flat(u)) >= 4 and _flat(u) in flat]
    if hits:
        raise LeakRefusedError(f"결과에 발화 원문 {len(hits)}개가 섞였다 — 쓰지 않는다")


def _fmt(value: object) -> str:
    """표에 넣을 값(None → —)."""
    return "—" if value is None else str(value)


def _row(*cells: object) -> str:
    """표 한 줄."""
    return "| " + " | ".join(str(c) for c in cells) + " |"


def _codes_row(label: str, table: Mapping[str, int], non_answer: object) -> str:
    """OP 코드 빈도 표 한 줄."""
    return _row(label, *(table.get(code, 0) for code in OP_CODES), non_answer)


def render_doc(result: Mapping[str, Any]) -> str:
    """`golden/sim/CALIBRATION.md` — 첫 줄 판정 + 세 기준 숫자 + 비교 불가 항목. 숫자만."""
    turns, errors, blind = result["turns"], result["errors"], result["blind"]
    t_ai, t_hu, e_ai, e_hu = turns["ai"], turns["human"], errors["ai"], errors["human"]
    word, _, detail = str(result["verdict"]).partition(" — ")
    # 첫 줄: 판정 (날짜)[ — 기준 N] · 실학생 0명(공유 계약 — CALIBRATION.md 첫 줄에 "실학생 0")
    head = f"{word} ({result['date']})" + (f" — {detail}" if detail else "") + REAL_STUDENTS_NOTE
    sources = ", ".join(f"`{item['file']}`({item['sessions']}세션)" for item in result["inputs"])
    agree = errors["injector_agreement"]
    human_unclassified = e_hu["table"].get("OP_00", 0)
    lines = [
        head,
        "",
        "# 보정 검사 결과 (S20 · 관문 ① · F-00)",
        "",
        "> **실제 중학생 0명.** 사람 출처는 본인(`self-*`)·성인(`adult-*`) 기록뿐이다"
        "(S16 시드 · FINDINGS 「피험자 한계」). 이 보정은 AI 학생이 **대체 피험자**를 닮았는지를"
        " 잰다 — 중학생을 닮았는지가 아니다.",
        "",
        "- 사람 출처: `golden/sim/seed/distributions.json`(S16 · Kiki 머신에만)",
        f"- AI 실제 실행 기록: {sources}",
        "- 계산: `python -m golden.sim.calibrate check` → `score`(S20)",
        f"- 판정: **{result['verdict']}** — 세 기준 모두 통과해야 통과다."
        " 조건부 통과는 Kiki 결정으로만 적는다.",
        "",
        "## 세 기준",
        "",
        _row("기준", "AI", "사람 출처", "차이·겹침", "통과 조건", "결과"),
        _row("---", "---", "---", "---", "---", "---"),
        _row(
            "①ⓐ 정답까지 튜터 턴 중앙값(전부)",
            f"{_fmt(t_ai['median'])} (n={t_ai['n']})",
            f"{_fmt(t_hu['median'])} (n={t_hu['n']})",
            _fmt(turns["diff"]["all"]),
            "±1턴",
            turns["status"],
        ),
        _row(
            "①ⓑ 같은 것(튜터가 열린 것만)",
            f"{_fmt(t_ai['median_opened'])} (n={t_ai['n_opened']})",
            f"{_fmt(t_hu['median_opened'])} (n={t_hu['n_opened']})",
            _fmt(turns["diff"]["opened"]),
            "±1턴",
            "(①은 ⓐⓑ 둘 다)",
        ),
        _row(
            "② 오답 OP 상위 3개(미분류 제외)",
            f"{' · '.join(e_ai['top3']) or '—'} (오답 {e_ai['wrong_inputs']})",
            f"{' · '.join(e_hu['top3']) or '—'} (오답 {e_hu['wrong_inputs']})",
            f"{len(errors['overlap'])}개({' · '.join(errors['overlap']) or '—'})",
            "2개 이상",
            errors["status"],
        ),
        _row(
            "③ 블라인드 구분 정확도",
            f"사람 {BLIND_PER_SOURCE} + AI {BLIND_PER_SOURCE}",
            "Kiki 판정",
            f"{_fmt(blind.get('accuracy'))} ({_fmt(blind.get('correct'))}/"
            f"{_fmt(blind.get('items'))})",
            "70% 이하",
            blind["status"],
        ),
        "",
        "## 페르소나별 턴(①)",
        "",
        _row("페르소나", "세션", "정답으로 끝남", "중앙값"),
        _row("---", "---", "---", "---"),
    ]
    lines += [
        _row(p, info["sessions"], info["to_correct"], _fmt(info["median_to_correct"]))
        for p, info in turns["per_persona"].items()
    ]
    lines += [
        "",
        "## OP 코드 빈도(②)",
        "",
        _row("출처", *OP_CODES, "답이 아닌 말"),
        _row(*("---" for _ in range(len(OP_CODES) + 2))),
        _codes_row(f"AI({'·'.join(errors['personas'])})", e_ai["table"], e_ai["non_answer"]),
        _codes_row(
            "AI(전 페르소나 · 참고)",
            errors["ai_all_personas"]["table"],
            errors["ai_all_personas"]["non_answer"],
        ),
        _codes_row("사람(합산)", e_hu["table"], "—"),
        "",
        f"- 주입기 라벨 ↔ 사람 분류기 일치: {agree['agree']}/{agree['labelled']}"
        '(주입기 답 그대로인 입력만) — 낮으면 원인 후보 "분류 규칙 불일치".',
        f"- AI 미분류 비율 {e_ai['unclassified_share']} · 사람 출처 오답 {e_hu['wrong_inputs']}건"
        f"(그중 미분류 {human_unclassified}건) — 표본이 작다.",
        "",
        "## 비교 불가 — 진실 트랙만 말할 수 있다",
        "",
    ]
    lines += [f"- **{name}**: {why}." for name, why in NOT_COMPARABLE]
    lines += [
        "",
        "이 셋은 실학생 세션(진실 트랙 · S24·S29·S33)에서만 잰다."
        " 시뮬레이터 숫자로 대신하지 않는다.",
        "",
    ]
    return "\n".join(lines)


def write_outputs(
    result: dict[str, Any], utterances: Sequence[str], result_path: Path, doc_path: Path
) -> None:
    """결과 JSON·CALIBRATION.md를 쓴다 — 쓰기 전에 발화 원문 혼입 검사."""
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    doc = render_doc(result)
    assert_no_utterances(payload + doc, utterances)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(payload, encoding="utf-8")
    doc_path.write_text(doc, encoding="utf-8")


def pending_blind() -> dict[str, Any]:
    """블라인드 판정 전 칸."""
    return {"status": "판정 대기", "pass": None, "reason": "Kiki 판정 전(score 미실행)"}


# ──────────────────────────────────────────────────────────────────────
# 명령줄
# ──────────────────────────────────────────────────────────────────────


def _check(args: argparse.Namespace) -> int:
    seed_dir = Path(args.seed_dir)
    per_file = [(Path(p), load_sessions([Path(p)])) for p in args.sessions]
    for path, rows in per_file:
        check_complete(path, rows)
    sessions = [row for _, rows in per_file for row in rows]
    distributions = load_distributions(seed_dir)
    seeds = load_seed_texts(seed_dir)
    problems = {p["id"]: p for p in load_problems()}
    pool = ai_utterances(sessions, seeds)
    blind_path, key_path = Path(args.blind), Path(args.key)
    if blind_path.exists() and not args.new_blind:
        print(f"BLIND_KEPT — 시트가 이미 있다(새로 만들려면 --new-blind): {blind_path}")
    else:
        items, fingerprint = build_blind(seeds, pool, args.blind_seed or secrets.randbits(32))
        blind_path.write_text(render_blind(items, args.date), encoding="utf-8")
        key_path.write_text(render_key(items, fingerprint), encoding="utf-8")
        print(f"BLIND_WRITTEN items={len(items)} fingerprint={fingerprint}")
    result: dict[str, Any] = {
        "date": args.date,
        "inputs": [{"file": path.name, "sessions": len(rows)} for path, rows in per_file],
        "turns": turn_criterion(sessions, distributions["turns"]),
        "errors": error_criterion(sessions, distributions["errors"], problems),
        "blind": pending_blind(),
        "blind_pool": len(pool),
        "not_comparable": [name for name, _ in NOT_COMPARABLE],
        "real_students": 0,
    }
    result["verdict"] = verdict(result)
    write_outputs(result, [*seeds, *pool], Path(args.result), Path(args.doc))
    print(_summary(result))
    return 0


def _score(args: argparse.Namespace) -> int:
    result_path = Path(args.result)
    if not result_path.is_file():
        raise CalibrationError(f"check 결과가 없다: {result_path} — check를 먼저")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    key_fp, labels = parse_key(Path(args.key).read_text(encoding="utf-8"))
    sheet_texts, guesses = parse_sheet(Path(args.blind).read_text(encoding="utf-8"))
    if key_fp != sheet_fingerprint(sheet_texts) or set(guesses) != set(labels):
        raise CalibrationError(
            "시트와 정답 키가 같은 회차가 아니다(지문 불일치) — 시트 발화를 고치지 않았는지 확인"
        )
    result["blind"] = blind_accuracy(guesses, labels)
    result["blind"]["scored_on"] = args.date
    result["verdict"] = verdict(result)
    seeds = load_seed_texts(Path(args.seed_dir))
    write_outputs(result, [*seeds, *sheet_texts], result_path, Path(args.doc))
    print(_summary(result))
    return 0 if result["verdict"] == "통과" else 1


def _summary(result: Mapping[str, Any]) -> str:
    """화면 한 줄 요약(숫자만)."""
    t, e, b = result["turns"], result["errors"], result["blind"]
    t_ai, t_hu = t["ai"], t["human"]
    return (
        f"CALIBRATION verdict={result['verdict']} | "
        f"①{t['status']} AI={t_ai['median']}/{t_ai['median_opened']} "
        f"사람={t_hu['median']}/{t_hu['median_opened']} | "
        f"②{e['status']} AI={','.join(e['ai']['top3'])} 사람={','.join(e['human']['top3'])} "
        f"겹침={len(e['overlap'])} | ③{b['status']} 정확도={b.get('accuracy')}"
    )


def main(argv: list[str] | None = None) -> int:
    """`check`(①② + 블라인드 시트) · `score`(③ 정확도 + 최종 판정)."""
    parser = argparse.ArgumentParser(description="AI 학생 시뮬레이터 보정 검사(S20)")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "score"):
        p = sub.add_parser(name)
        p.add_argument("--seed-dir", default=str(SEED_DIR))
        p.add_argument("--blind", default=str(BLIND_PATH))
        p.add_argument("--key", default=str(KEY_PATH))
        p.add_argument("--result", default=str(RESULT_PATH))
        p.add_argument("--doc", default=str(DOC_PATH))
        p.add_argument("--date", default=dt.date.today().isoformat())
    check = sub.choices["check"]
    check.add_argument(
        "--sessions", action="append", required=True, help="sessions.jsonl(반복 가능)"
    )
    check.add_argument("--new-blind", action="store_true", help="시트·키를 새로 만든다")
    check.add_argument(
        "--blind-seed", type=int, default=None, help="섞기 시드(테스트용 · 기본 무작위)"
    )
    args = parser.parse_args(argv)
    try:
        return _check(args) if args.command == "check" else _score(args)
    except (CalibrationError, OSError, json.JSONDecodeError) as exc:
        print(f"CALIBRATE_REFUSED=True — {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    except LeakRefusedError as exc:
        print(f"CALIBRATE_REFUSED=True — {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
