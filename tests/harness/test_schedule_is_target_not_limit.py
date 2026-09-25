"""기간은 목표이지 진도 제한이 아니다 — selector가 날짜로 착수 후보를 거르지 않음을 동결한다.

기본방침(2026-09-24 Kiki 지정 · docs/standards/build_harness.md §3a):
    "기간을 세팅한 것은 적절한 목표를 설정한 것이지 진도를 제한하기 위한 것이 아냐"

착수 가능 여부는 상태·선행·게이트·claim으로만 정해진다. 달력(오늘 날짜·주차)이
후보 계산에 끼어들면 "내용은 준비됐는데 날짜가 안 와서 못 한다"가 코드로 생긴다.
이 테스트는 selector 소스를 AST로 읽어 그 경로를 막는다(문자열 검색이 아니라 구성된
결과를 본다 — 별칭 임포트·from 임포트도 잡는다).
"""

from __future__ import annotations

import ast
from pathlib import Path

_SELECTOR = Path(__file__).resolve().parents[2] / "scripts" / "harness" / "selector.py"

# 날짜·시각을 얻는 표준 모듈 — selector가 이것을 임포트하면 달력 판정이 들어올 수 있다
_CLOCK_MODULES = {"datetime", "time", "calendar", "zoneinfo"}
# 현재 시각을 읽는 호출 — 모듈을 우회해 들어와도(예: 인자로 받은 객체) 잡는다
_CLOCK_CALLS = {"today", "now", "utcnow", "time", "monotonic"}


def find_clock_usage(source: str) -> list[str]:
    """소스에서 날짜·시각 의존 지점을 찾아 사람이 읽을 설명 목록으로 돌려준다."""
    hits: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in _CLOCK_MODULES:
                    hits.append(f"L{node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in _CLOCK_MODULES:
                hits.append(f"L{node.lineno}: from {node.module} import ...")
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name in _CLOCK_CALLS:
                hits.append(f"L{node.lineno}: {name}() 호출")
    return hits


def test_selector_source_exists_and_is_nonempty() -> None:
    # 스캔 0건은 실패 — 대상 파일을 못 찾으면 아래 검사가 공허하게 통과한다
    src = _SELECTOR.read_text(encoding="utf-8")
    assert "def " in src, "selector.py를 읽지 못했거나 함수가 없다 — 검사 대상 경로를 확인하라"


def test_selector_does_not_filter_by_calendar() -> None:
    hits = find_clock_usage(_SELECTOR.read_text(encoding="utf-8"))
    assert hits == [], (
        "selector가 날짜·시각에 의존한다 — 기간은 목표이지 착수 제한이 아니다"
        f"(build_harness.md §3a). 발견: {hits}"
    )


def test_detector_flags_each_clock_form() -> None:
    # 변별력 — 검출기가 실패 상태에서 실제로 실패 신호를 내는지 형태별로 주입해 확인한다
    injected = {
        "import datetime": "import datetime\n",
        "별칭 import": "import datetime as dt\n",
        "from import": "from datetime import date\n",
        "time 모듈": "import time\n",
        "today() 호출": "x = obj.today()\n",
        "now() 호출": "x = clock.now()\n",
    }
    for label, src in injected.items():
        assert find_clock_usage(src), f"주입 '{label}'을 검출하지 못했다"


def test_detector_passes_clock_free_control() -> None:
    # 대조군 — 날짜 무관 코드(정규식·데이터클래스)는 통과해야 과잉 검출이 아니다
    control = (
        "import re\nfrom dataclasses import dataclass\n"
        "def f(t):\n    return re.match('x', t.id) and t.stage\n"
    )
    assert find_clock_usage(control) == []
