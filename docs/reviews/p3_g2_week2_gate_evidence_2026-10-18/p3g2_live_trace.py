"""P3-G2 판정용 라이브 트레이스 — 실 PG + 실 앱(HTTP)으로 학생 오답 1건을 제출하고 관측한다.

판정 전용 스크립트다: 저장소 파일을 바꾸지 않고(스크래치패드에만 존재), 학습자 상태는 한 줄도 직접
쓰지 않는다(전부 HTTP 부수효과). 저작 콘텐츠(problem·concept)는 `populate` CLI 가 이미 적재했다.
선행 Week 1 하네스의 `_client`·`_login`·`_erase_learner` 를 경로 로딩으로 재사용한다(재구현 0).
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
from typing import Any

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[3]  # 저장소 루트(docs/reviews/<폴더>/ 에서 3단계 위)
W1 = ROOT / "tests/backend/api/test_week1_gate_closed_loop.py"
spec = importlib.util.spec_from_file_location("_w1", W1)
assert spec and spec.loader
w1 = importlib.util.module_from_spec(spec)
sys.modules["_w1"] = w1
spec.loader.exec_module(w1)

from whymath_backend.api._rate_limit import reset_store  # noqa: E402

REM = yaml.safe_load(
    (ROOT / "data/corpus/phase3_remediation_v1/remediation.yaml").read_text(encoding="utf-8")
)
FIX = {s["kebab_id"]: s["fixtures"] for s in REM["signatures"]}


def trim(obj: Any, keys: tuple[str, ...]) -> Any:
    if isinstance(obj, dict):
        return {k: obj[k] for k in keys if k in obj}
    return obj


def run(label: str, kebab: str, n_attempts: int) -> dict[str, Any]:
    """학생 1명이 그 오개념의 오답 보기를 n 회 고른다 — 매 회 응답과 다음 행동을 관측."""
    reset_store()
    out: dict[str, Any] = {"label": label, "kebab": kebab, "attempts": []}
    with w1._client() as client:
        w1._erase_learner(client)  # 선행 정리(멱등) — 지난 회차 잔여가 기준선을 깨지 않게
        auth = w1._login(client)
        out["learning_state_before"] = client.get("/v1/me/learning-state", headers=auth).json()
        wrongs = FIX[kebab]["wrong"]
        for i in range(n_attempts):
            fx = wrongs[i % len(wrongs)]
            resp = client.post(
                "/v1/me/attempts",
                headers=auth,
                json={
                    "problem_id": fx["problem_id"],
                    "is_correct": False,
                    "selected_choice_index": fx["choice_index"],
                },
            )
            row: dict[str, Any] = {
                "n": i + 1,
                "problem_id": fx["problem_id"],
                "choice_index": fx["choice_index"],
                "http": resp.status_code,
            }
            try:
                row["body"] = resp.json()
            except Exception as exc:  # noqa: BLE001 — 판정 스크립트: 형태를 그대로 남긴다
                row["body_error"] = type(exc).__name__
                row["text"] = resp.text[:400]
            nxt = client.get("/v1/me/next-problem", headers=auth)
            row["next_http"] = nxt.status_code
            try:
                row["next"] = nxt.json()
            except Exception as exc:  # noqa: BLE001
                row["next_error"] = type(exc).__name__
            out["attempts"].append(row)
        out["learning_state_after"] = client.get("/v1/me/learning-state", headers=auth).json()
        tr = client.get("/v1/me/learning-trace", headers=auth)
        out["trace_http"] = tr.status_code
        out["trace"] = tr.json() if tr.status_code == 200 else tr.text[:400]
        try:
            w1._erase_learner(client)
        except Exception as exc:  # noqa: BLE001
            out["erase_error"] = type(exc).__name__
    return out


if __name__ == "__main__":
    which = sys.argv[1]
    kebab = sys.argv[2]
    n = int(sys.argv[3])
    res = run(which, kebab, n)
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
