"""골든 패스 문항 공급(GP-2) — golden/data/problems_linear_fn.json 30문항을 순서대로 낸다."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# 저장소 루트 기준 문항 파일 — parents[3] = src/backend/golden → src/backend → src → 저장소 루트
PROBLEMS_PATH = Path(__file__).resolve().parents[3] / "golden" / "data" / "problems_linear_fn.json"

# 문항 1건 = 공유 계약의 문항 JSON 스키마(id·stem·answer·answer_kind·hint1·concept·source)
Problem = dict[str, str]


def load_problems() -> list[Problem]:
    """문항 파일을 읽어 문항 목록을 돌려준다(파일 순서 그대로)."""
    raw: Any = json.loads(PROBLEMS_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"문항 파일이 비었거나 배열이 아니다: {PROBLEMS_PATH}")
    return [{str(k): str(v) for k, v in item.items()} for item in raw]


def public_view(problem: Problem, index: int, total: int) -> dict[str, object]:
    """학생에게 내보낼 모양 — 정답·힌트는 빼고, GOLDEN_TEST_MODE=1일 때만 `_test_answer`를 붙인다.

    환경변수는 import 시점이 아니라 호출 시점에 읽는다(테스트 픽스처가 수집 뒤에 켜기 때문).
    """
    view: dict[str, object] = {
        "id": problem["id"],
        "stem": problem["stem"],
        "index": index,
        "total": total,
    }
    if os.environ.get("GOLDEN_TEST_MODE") == "1":
        view["_test_answer"] = problem["answer"]
    return view
