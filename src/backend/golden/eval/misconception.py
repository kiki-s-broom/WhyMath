"""슬롯 T2 매칭(S27 · 다섯 걸음 ③) — 틀린 답 → 오개념 ID 또는 None.

옛 코드에는 일차함수용 "틀린 답 → 오개념 ID" 함수가 없다(S26 HARVEST T2 경계).
그래서 지시서 할 일 1의 ②대로 **주입기 규칙을 거꾸로** 쓴다:

- 주입기(`golden.sim.errors`)가 30문항 × 오개념 11건에 대해 만드는 틀린 답을 미리 계산해
  `golden/data/misconception_answers_lf.json`(70행)에 커밋해 두었다
  (`python -m golden.sim.errors --answers-json …`).
  커밋본과 지금 주입기가 같은지는 테스트가 대조한다.
- 학생 답을 그 문항의 틀린 답들과 **채점기 규칙 그대로**(`grade.is_correct` — SymPy 값·식 동치,
  말꼬리·마지막 `=` 뒤 처리 포함) 비교해, 파일 순서로 처음 같은 것의 오개념 ID를 돌려준다.

이 모듈은 시뮬레이터 패키지(`golden.sim`)를 import하지 않는다 — 학생 응답 경로(api)가 시드를 읽는
코드와 한 프로세스 import 그래프로 묶이지 않게, 표는 파일로만 받는다(공통 규칙 7의 취지).

한계(숨기지 않는다): 같은 문항에서 두 오개념이 **같은 틀린 답**을 내면 답만으로는 둘을 가를 수 없다.
그때는 파일 순서상 앞의 ID가 나온다(S27 보고 「충돌」 — M0035·M0569 · M0034·M0568 · M0002·M0548).
플래그 `GOLDEN_T2_MISCONCEPTION=1`일 때만 api가 부르고, 결과는 `golden.eval_log`에 기록한다.

S28은 매칭이 있으면 그 오개념의 한 줄 설명(`misconception_description` — 오개념 파일의
`prompt_description`)을 튜터 사용자 프롬프트에 넣었다. S30 판정(효과 없음 · 잠정 · AI 대체)으로
그 주입은 되돌렸다 — 지금 튜터는 설명을 받지 않는다. 설명 데이터와 이 함수는 기록·측정용으로
남겼고, 설명에 숫자가 없다는 데이터 계약은 테스트가 지킨다.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from golden import grade
from golden.problems import Problem

# 플래그 이름(공유 계약 · 기본 0)
FLAG_ENV = "GOLDEN_T2_MISCONCEPTION"

# eval_log에 함께 남기는 매칭기 판 — 표나 규칙이 바뀌면 올린다(기록끼리 섞어 세지 않게)
T2_MATCHER_VERSION = "t2-match-v1"

# 매칭용 표 — parents[4] = src/backend/golden/eval → golden → backend → src → 저장소 루트
ANSWERS_PATH = (
    Path(__file__).resolve().parents[4] / "golden" / "data" / "misconception_answers_lf.json"
)

# 오개념 파일(S26 · S28이 prompt_description·keywords를 더함)
# — 한 줄 설명·검출 낱말을 여기서 읽는다(튜터 주입은 S30이 되돌림)
MISCONCEPTIONS_PATH = (
    Path(__file__).resolve().parents[4] / "golden" / "data" / "misconceptions_lf.json"
)


def misconception_enabled() -> bool:
    """`GOLDEN_T2_MISCONCEPTION=1`일 때만 참. 호출 시점에 읽는다(기본 끔)."""
    return os.environ.get(FLAG_ENV) == "1"


@lru_cache(maxsize=1)
def answer_table() -> dict[str, tuple[tuple[str, str], ...]]:
    """문항 ID → ((오개념 ID, 틀린 답), …) 파일 순서 그대로. 처음 한 번만 읽는다.

    틀린 파일은 빈 표로 두지 않고 멈춘다 — 빈 표는 "어떤 답도 오개념이 아니다"와 구별되지 않아
    매칭률 0이 측정 실패가 아니라 결과처럼 보이게 된다.
    """
    raw = json.loads(ANSWERS_PATH.read_text(encoding="utf-8"))
    rows = raw.get("answers") if isinstance(raw, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"매칭용 표에 answers 목록이 없다: {ANSWERS_PATH}")
    if raw.get("count") != len(rows):
        raise ValueError(f"매칭용 표 count({raw.get('count')})와 실제 행 수({len(rows)})가 다르다")
    table: dict[str, list[tuple[str, str]]] = {}
    for row in rows:
        table.setdefault(str(row["problem_id"]), []).append(
            (str(row["mis_id"]), str(row["wrong_answer"]))
        )
    return {problem_id: tuple(pairs) for problem_id, pairs in table.items()}


def match_misconception(problem: Problem, student_text: str) -> str | None:
    """학생 답이 이 문항의 어떤 오개념 틀린 답과 같으면 그 오개념 ID, 아니면 None.

    비교는 채점기와 같은 규칙이다.
    틀린 답을 "정답" 자리에 넣은 문항으로 `grade.is_correct`를 부른다.
    그래서 `12요`·`f(5)=12`·`-3×5+3=12`처럼 채점기가 받아들이는 모양은 여기서도 같은 답으로 본다.
    """
    for mis_id, wrong_answer in answer_table().get(problem["id"], ()):
        if grade.is_correct({**problem, "answer": wrong_answer}, student_text):
            return mis_id
    return None


@lru_cache(maxsize=1)
def description_table() -> dict[str, str]:
    """오개념 ID → 튜터 프롬프트용 한 줄 설명(`prompt_description`). 처음 한 번만 읽는다.

    틀린 파일은 멈춘다(빈 표 금지 — 설명이 없으면 매칭이 있어도 튜터에 아무것도 안 가는데,
    그것이 "매칭 없음"과 구별되지 않는다).
    """
    raw = json.loads(MISCONCEPTIONS_PATH.read_text(encoding="utf-8"))
    rows = raw.get("misconceptions") if isinstance(raw, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"오개념 파일에 misconceptions 목록이 없다: {MISCONCEPTIONS_PATH}")
    table: dict[str, str] = {}
    for row in rows:
        description = str(row.get("prompt_description") or "").strip()
        if not description:
            raise ValueError(f"{row.get('mis_id')}: prompt_description이 비어 있다")
        table[str(row["mis_id"])] = description
    return table


def misconception_description(mis_id: str) -> str:
    """오개념 ID → 한 줄 설명. 표에 없는 ID면 KeyError(매칭표와 오개념 파일이 어긋난 것)."""
    return description_table()[mis_id]
