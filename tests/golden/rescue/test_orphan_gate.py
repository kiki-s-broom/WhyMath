"""RS-G1 고아 게이트 — 골든 구역(`src/backend/golden/`)에 아무 진입점에서도 닿지 않는 모듈이 새로 생기면 실패한다.

고아 = 진입점에서 정적으로 닿지 않는 골든 모듈(RS 공유 계약 「등급」의 섬·잔해). 옛 코드가 "만들었는데
아무도 부르지 않는 모듈"로 가득 찬 일이 골든 구역에서 반복되지 않게 한다.

- 진입점: 서버 `golden.api`와 명령줄로 직접 실행하는 모듈. 명령줄 진입점은 아래 `ENTRYPOINTS`에
  부르는 법과 함께 **손으로 선언**하고, `if __name__ == "__main__":`이 있는 골든 모듈(AST로 찾는다)과
  정확히 같아야 한다 — 고아에 `__main__` 가드만 붙여 몰래 통과시키지 못하게, 새 진입점은 PR에 보이게 한다.
- 닿는지: RS-R1 대장 도구(`golden.rescue.ledger`)의 `reach_from`(grimp 정적 그래프 + 부모 `__init__` 보정)과
  `filesystem_modules`(`__init__.py` 없는 폴더 보정)로 잰다. 모듈을 import하지 않는다.
- 기준선 `orphan_baseline.txt`: 한 줄 = `모듈 | 이유`. 이유 없는 줄은 실패. 기준선에 없는 고아가 생겨도
  실패하고, 이미 해결된(이제 닿는) 줄이 남아 있어도 실패한다 — 기준선은 줄어들기만 한다.
- 옛 구역(`whymath_backend`)에는 걸지 않는다(새 코드가 쌓이지 않고 LEGACY_MANIFEST로 격리돼 있다).
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Iterable
from pathlib import Path

import grimp
import pytest
from golden.rescue import ledger

GATE_PACKAGE = "golden"
SERVER_ENTRY = "golden.api"
# 진입점 → 부르는 법. 명령줄 진입점을 더하거나 빼면 여기도 같이 고친다(테스트가 `__main__` 가드와 대조).
ENTRYPOINTS: dict[str, str] = {
    SERVER_ENTRY: "서버 — uvicorn golden.api:app",
    "golden.check": "python src/backend/golden/check.py (골든 검사 명령 · GOLD-21)",
    "golden.driver.next_task": "python -m golden.driver.next_task [--json] (다음 지시문 계산)",
    "golden.llm.sync": "python -m golden.llm.sync (LLM 좌석 동기화)",
    "golden.measure_unreferenced": "python -m golden.measure_unreferenced (미참조 측정)",
    "golden.rescue.ledger": "python -m golden.rescue.ledger (RS-R1 모듈 대장)",
    "golden.rescue.outline": "python -m golden.rescue.outline (RS-R0 목차)",
    "golden.rescue.testmap": "python -m golden.rescue.testmap (RS 테스트 지도)",
    "golden.sim.calibrate": "python -m golden.sim.calibrate check|score (보정 검사 · S20)",
    "golden.sim.errors": "python -m golden.sim.errors --csv <경로> (오개념 주입기 표 · S17)",
    "golden.sim.run": "python -m golden.sim.run --sessions 120 (시뮬레이터 러너 · S19)",
    "golden.sim.seed_extract": "python -m golden.sim.seed_extract (시뮬레이션 씨앗 추출)",
    "golden.sim.student_compare": "python -m golden.sim.student_compare (S18 학생 모델 비교)",
    "golden.sim.t1_summary": "python -m golden.sim.t1_summary summarize|compare (T1 집계 · S23)",
    "golden.sim_student": "python -m golden.sim_student (가상 학생 시뮬레이션)",
}
BASELINE = Path(__file__).with_name("orphan_baseline.txt")


def has_main_guard(path: Path) -> bool:
    """파일 맨 위 수준에 `if __name__ == "__main__":`이 있는가(AST — 주석·문자열 속 글자는 세지 않는다)."""
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if not (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)):
            continue
        sides = [node.test.left, *node.test.comparators]
        names = {s.id for s in sides if isinstance(s, ast.Name)}
        consts = {s.value for s in sides if isinstance(s, ast.Constant)}
        if names == {"__name__"} and consts == {"__main__"}:
            return True
    return False


def main_guard_modules(src_root: Path, package: str) -> set[str]:
    """`__main__` 가드가 있는 패키지 모듈 = 명령줄 진입점 후보."""
    files = ledger.filesystem_modules(src_root, (package,))
    return {mod for mod, path in files.items() if has_main_guard(path)}


def find_orphans(
    src_root: Path, packages: Iterable[str], gate_package: str, entries: Iterable[str]
) -> tuple[set[str], set[str]]:
    """(게이트 패키지 모듈 전체, 그중 어느 진입점에서도 닿지 않는 고아)."""
    packages = tuple(packages)
    sys.path.insert(0, str(src_root))
    try:
        graph = grimp.build_graph(*packages, cache_dir=None)
    finally:
        sys.path.remove(str(src_root))
    reached: set[str] = set()
    for entry in entries:
        if entry not in graph.modules:
            raise ValueError(f"진입점 {entry}이 그래프에 없다")
        reached |= ledger.reach_from(graph, entry)
    files = ledger.filesystem_modules(src_root, packages)
    pkg = {m for m in files if m == gate_package or m.startswith(gate_package + ".")}
    return pkg, pkg - reached


def read_baseline(path: Path) -> dict[str, str]:
    """기준선 → {모듈: 이유}. `#` 줄과 빈 줄은 건너뛴다. 이유 없는 줄·중복 줄은 ValueError."""
    known: dict[str, str] = {}
    for no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        mod, sep, reason = (part.strip() for part in line.partition("|"))
        if not sep or not mod or not reason:
            raise ValueError(
                f"{path.name}:{no} 이유 없는 줄 — '모듈 | 이유' 형식이어야 한다: {raw!r}"
            )
        if mod in known:
            raise ValueError(f"{path.name}:{no} 중복 줄: {mod}")
        known[mod] = reason
    return known


def gate(orphans: set[str], known: Iterable[str]) -> tuple[list[str], list[str]]:
    """(새 고아 = 기준선에 없는 고아, 해결된 줄 = 기준선에 있는데 이제 고아가 아닌 모듈)."""
    known = set(known)
    return sorted(orphans - known), sorted(known - orphans)


# ── 실제 저장소 ─────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def golden_orphans() -> tuple[set[str], set[str]]:
    return find_orphans(ledger.BACKEND, ledger.PACKAGES, GATE_PACKAGE, ENTRYPOINTS)


def test_declared_entrypoints_match_main_guards() -> None:
    found = main_guard_modules(ledger.BACKEND, GATE_PACKAGE)
    declared = set(ENTRYPOINTS) - {SERVER_ENTRY}
    assert found, "`__main__` 가드 모듈 0개 — 스캔 실패(공허 통과 금지)"
    assert (
        sorted(found - declared) == []
    ), "`__main__`이 있는데 ENTRYPOINTS에 없다 — 부르는 법과 함께 선언"
    assert sorted(declared - found) == [], "ENTRYPOINTS에 있는데 `__main__`이 없다 — 선언을 지운다"


def test_baseline_lines_have_reasons() -> None:
    read_baseline(BASELINE)  # 이유 없는 줄·중복 줄이면 ValueError


def test_no_new_orphans_and_baseline_only_shrinks(
    golden_orphans: tuple[set[str], set[str]],
) -> None:
    modules, orphans = golden_orphans
    assert len(modules) >= 10, f"골든 모듈 {len(modules)}개 — 스캔 실패(공허 통과 금지)"
    new, resolved = gate(orphans, read_baseline(BASELINE))
    assert (
        new == []
    ), f"새 고아(어느 진입점에서도 안 닿는 골든 모듈): {new} — 진입점에서 import하거나 지운다"
    assert resolved == [], f"이미 해결된 기준선 줄: {resolved} — {BASELINE.name}에서 지운다"


# ── 합성 패키지(게이트 로직 자체가 막는지) ──────────────────────────────────────

_SYN = {
    "gsyn/__init__.py": "",
    "gsyn/api.py": "from gsyn import used\n",
    "gsyn/used.py": "X = 1\n",
    "gsyn/tool.py": "from gsyn import helper\n\nif __name__ == '__main__':\n    print(helper.Y)\n",
    "gsyn/helper.py": "Y = 2\n",
    "gsyn/lonely.py": "Z = 3\n",
    "gsyn/fake.py": "S = 'if __name__ == \"__main__\":'\n# if __name__ == '__main__':\n",
}


@pytest.fixture()
def syn_root(tmp_path: Path) -> Path:
    for rel, text in _SYN.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    return tmp_path


def test_synthetic_orphan_detected(syn_root: Path) -> None:
    assert main_guard_modules(syn_root, "gsyn") == {"gsyn.tool"}  # 문자열·주석 속 가드는 안 센다
    entries = ["gsyn.api", "gsyn.tool"]
    _, orphans = find_orphans(syn_root, ["gsyn"], "gsyn", entries)
    assert orphans == {"gsyn.lonely", "gsyn.fake"}
    assert gate(orphans, {"gsyn.fake"}) == (["gsyn.lonely"], [])  # 새 고아
    assert gate(orphans, {"gsyn.fake", "gsyn.lonely", "gsyn.used"}) == (
        [],
        ["gsyn.used"],
    )  # 해결된 줄


def test_synthetic_baseline_rejects_reasonless_and_duplicate(tmp_path: Path) -> None:
    good = tmp_path / "ok.txt"
    good.write_text("# 주석\n\ngsyn.lonely | 다음 PR에서 연결\n", encoding="utf-8")
    assert read_baseline(good) == {"gsyn.lonely": "다음 PR에서 연결"}
    for text in ("gsyn.lonely\n", "gsyn.lonely |  \n", "a | x\na | y\n"):
        bad = tmp_path / "bad.txt"
        bad.write_text(text, encoding="utf-8")
        with pytest.raises(ValueError):
            read_baseline(bad)
