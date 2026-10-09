#!/usr/bin/env python3
"""OPS-47 ① 호환 진입점 — OPS-100에서 전 잡 측정기로 일반화됐다.

이 파일이 원래 하던 일(backend 잡 하나의 타임아웃 여유 재측정)은
`measure_ci_job_timeout_headroom.py --only backend`와 같다. 경로를 지키는 이유는
`ci.yml` 주석과 OPS-47·HARN-183 등 기록이 이 이름을 가리키기 때문이다.

초판과 달라진 점(그래서 같은 숫자가 나오지 않을 수 있다):
· 초판은 `status=success` 실행·`conclusion=success` 잡만 봤다. 타임아웃으로 죽은 실행이
  표본에서 빠져 *가장 위험한 표본이 사라지는* 생존자 편향이 있었다. 지금은 완료된 실행
  전부를 보고, 상한에 닿아 끊긴 잡은 '상한 도달'로 센다.
· push뿐 아니라 머지 큐(merge_group) 실행도 본다 — 머지를 실제로 막는 쪽이다.

사용(구 CLI 그대로):
    python3 scripts/analysis/measure_backend_job_timeout_headroom.py <owner/repo> [branch] [--n N]
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import measure_ci_job_timeout_headroom as _generalized  # noqa: E402

_BACKEND_KEY = "backend"


def build_argv(argv: Sequence[str] | None) -> list[str]:
    """구 CLI 인자를 일반화 도구의 인자로 옮긴다."""
    p = argparse.ArgumentParser(description="backend 잡 타임아웃 여유 재측정 (호환 진입점)")
    p.add_argument("repo", help="owner/repo")
    p.add_argument("branch", nargs="?", default="main")
    p.add_argument("--n", type=int, default=None, help="이벤트별 최근 실행 수")
    args = p.parse_args(argv)
    out = [args.repo, "--branch", args.branch, "--only", _BACKEND_KEY]
    if args.n is not None:
        out += ["--n", str(args.n)]
    return out


def main(argv: Sequence[str] | None = None) -> int:
    return _generalized.main(build_argv(argv))


if __name__ == "__main__":
    raise SystemExit(main())
