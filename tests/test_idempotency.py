"""R3-01 (헌법 제6조) — 모든 배치 스크립트는 두 번 실행해도 행 수와 결과가 같아야 한다
('두 번 실행 테스트' 필수).

이 파일은 *배치를 직접 돌리지 않는다*. 대신 **'두 번 실행 테스트가 있는가'를 전수로 강제**한다 —
배치가 새로 생기면 두 번 실행 테스트 없이는 이 파일이 실패한다. (실제 재실행 단언은 각 배치의
`tests/backend/harness/test_<이름>.py`가 한다.)

판정(AST — 이름이 아니라 구조를 본다): 배치 모듈 `<이름>_batch.py`마다
  ① `tests/backend/harness/test_<이름>_batch.py`가 있고
  ② 그 안에 *한 테스트 함수 안에서* 배치의 진입점(`main` 또는 `run_*`)을 **두 번 이상 호출**하면서
  ③ 같은 함수가 `==` 비교 assert를 갖는다.
  테스트 *이름*(`..._deterministic` 등)은 보지 않는다 — 이름이 의도를 말한다고 코드가 그 의도를
  실행하는 것은 아니다(CLAUDE.md '픽스처가 그 절을 실제로 밟는가').

범위(정직한 한계 — Kiki 정책 결정 대기): 현재는 `harness/*_batch.py` 36개만 센다.
`scripts/*.py` 적재·백필 CLI, `problem_corpus_accumulate`(라이브 LLM append — 설계상 두 번 실행하면
행이 늘어난다)·populate 계열은 '배치 스크립트'의 정의 밖에 있어 *검사하지 않는다*. 정의를 넓히면
`BATCH_GLOBS`에 더한다. `③`의 `==`는 두 실행 결과를 *비교했다*는 구조 증거이지, 비교 대상이
적절한지까지 증명하지는 않는다.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS_DIR = ROOT / "src/backend/whymath_backend/harness"
TEST_DIR = ROOT / "tests/backend/harness"
BATCH_SUFFIX = "_batch.py"

# 면제는 이유와 *만료일*을 함께 둔다(CLAUDE.md '만료 없는 유예 금지'). 현재 0건 — 있었던 1건
# (concept_content_review_batch)은 시계 필드를 뺀 재실행 동일성 테스트를 새로 써서 닫았다.
EXEMPT: dict[str, tuple[str, str]] = {}  # {배치명: (이유, 만료일 YYYY-MM-DD)}


def entry_points(module_tree: ast.Module) -> set[str]:
    """배치 모듈 최상위의 진입점 함수 이름 — `main`과 `run_*`."""
    return {
        n.name
        for n in module_tree.body
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
        and (n.name == "main" or n.name.startswith("run_"))
    }


def _imported_names(
    test_tree: ast.Module, module: str, ents: set[str]
) -> tuple[set[str], set[str]]:
    """테스트가 배치 진입점을 가리키는 이름들 — (직접 import 별칭, 모듈 별칭)."""
    direct: set[str] = set()
    mods: set[str] = set()
    for node in ast.walk(test_tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.endswith("." + module):
                direct |= {a.asname or a.name for a in node.names if a.name in ents}
            else:
                mods |= {a.asname or a.name for a in node.names if a.name == module}
    return direct, mods


def _entry_calls(fn: ast.AST, direct: set[str], mods: set[str], ents: set[str]) -> int:
    count = 0
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Name) and f.id in direct:
            count += 1
        elif (
            isinstance(f, ast.Attribute)
            and f.attr in ents
            and isinstance(f.value, ast.Name)
            and f.value.id in mods
        ):
            count += 1
    return count


def _has_eq_assert(fn: ast.AST) -> bool:
    return any(
        isinstance(a, ast.Assert)
        and any(
            isinstance(c, ast.Compare) and any(isinstance(op, ast.Eq) for op in c.ops)
            for c in ast.walk(a.test)
        )
        for a in ast.walk(fn)
    )


def rerun_tests(batch_file: Path, test_file: Path) -> list[str]:
    """`test_file` 안에서 배치 진입점을 두 번 이상 부르고 `==` 단언을 가진 테스트 함수 이름들."""
    ents = entry_points(ast.parse(batch_file.read_text(encoding="utf-8")))
    tree = ast.parse(test_file.read_text(encoding="utf-8"))
    direct, mods = _imported_names(tree, batch_file.stem, ents)
    return [
        fn.name
        for fn in ast.walk(tree)
        if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef)
        and fn.name.startswith("test")
        and _entry_calls(fn, direct, mods, ents) >= 2
        and _has_eq_assert(fn)
    ]


def batches_without_rerun_test(
    harness_dir: Path, test_dir: Path, *, exempt: dict[str, tuple[str, str]] | None = None
) -> tuple[int, list[str]]:
    """(검사한 배치 수, 위반 목록). 검사한 배치가 0이면 호출자가 실패시킨다(스캔 0건은 실패)."""
    exempt = exempt or {}
    violations: list[str] = []
    batches = sorted(harness_dir.glob(f"*{BATCH_SUFFIX}"))
    for batch in batches:
        if batch.stem in exempt:
            continue
        test_file = test_dir / f"test_{batch.stem}.py"
        if not test_file.exists():
            violations.append(f"{batch.stem}: 테스트 파일 없음({test_file.name})")
        elif not rerun_tests(batch, test_file):
            violations.append(f"{batch.stem}: 두 번 실행 테스트 없음({test_file.name})")
    return len(batches), violations


# ── 실제 저장소 ──────────────────────────────────────────────────────────────
def test_every_batch_has_a_rerun_test() -> None:
    scanned, violations = batches_without_rerun_test(HARNESS_DIR, TEST_DIR, exempt=None)
    assert scanned > 0, "배치를 하나도 찾지 못했다 — 경로가 바뀌었다(0건 통과 금지)"
    assert violations == [], "두 번 실행 테스트가 없는 배치:\n  " + "\n  ".join(violations)


def test_exemptions_are_named_and_unexpired() -> None:
    from datetime import date

    for name, (reason, until) in EXEMPT.items():
        assert reason.strip(), f"{name}: 면제 이유가 비었다"
        assert date.fromisoformat(until) >= date.today(), f"{name}: 면제가 만료됐다({until})"
        assert (HARNESS_DIR / f"{name}{BATCH_SUFFIX}").exists(), f"{name}: 없는 배치를 면제했다"


# ── 변별력: 가짜 트리로 위반을 주입한다 ──────────────────────────────────────
def _tree(tmp_path: Path, batch_src: str, test_src: str | None) -> tuple[Path, Path]:
    harness = tmp_path / "harness"
    tests = tmp_path / "tests"
    harness.mkdir()
    tests.mkdir()
    (harness / "foo_batch.py").write_text(batch_src, encoding="utf-8")
    if test_src is not None:
        (tests / "test_foo_batch.py").write_text(test_src, encoding="utf-8")
    return harness, tests


BATCH = "def run_foo_batch(n, out):\n    pass\n\ndef main(argv=None):\n    return 0\n"
GOOD_TEST = (
    "from whymath_backend.harness.foo_batch import run_foo_batch\n"
    "def test_rerun(tmp_path):\n"
    "    run_foo_batch(1, tmp_path / 'a')\n"
    "    run_foo_batch(1, tmp_path / 'b')\n"
    "    assert (tmp_path / 'a').read_bytes() == (tmp_path / 'b').read_bytes()\n"
)


def test_control_good_test_passes(tmp_path: Path) -> None:
    h, t = _tree(tmp_path, BATCH, GOOD_TEST)
    assert batches_without_rerun_test(h, t) == (1, [])


@pytest.mark.parametrize(
    ("label", "test_src"),
    [
        ("테스트 파일 없음", None),
        ("한 번만 실행", GOOD_TEST.replace("    run_foo_batch(1, tmp_path / 'b')\n", "")),
        ("두 번 실행하나 비교 단언 없음", GOOD_TEST.replace(" == ", " is not None or ")),
        (
            "이름만 결정론인 테스트(진입점 호출 0회)",
            "from whymath_backend.harness.foo_batch import run_foo_batch\n"
            "def test_rerun_is_byte_deterministic(tmp_path):\n"
            "    assert 1 == 1\n",
        ),
        (
            "다른 함수를 두 번 부름(진입점 아님)",
            "from whymath_backend.harness.foo_batch import helper\n"
            "def test_rerun(tmp_path):\n    helper()\n    helper()\n    assert 1 == 1\n",
        ),
    ],
)
def test_violations_are_detected(tmp_path: Path, label: str, test_src: str | None) -> None:
    h, t = _tree(tmp_path, BATCH, test_src)
    scanned, violations = batches_without_rerun_test(h, t)
    assert scanned == 1 and len(violations) == 1, label


def test_module_alias_call_style_is_recognised(tmp_path: Path) -> None:
    src = (
        "from whymath_backend.harness import foo_batch as fb\n"
        "def test_rerun(tmp_path):\n"
        "    fb.main(['--out', 'a'])\n    fb.main(['--out', 'b'])\n    assert 1 == 1\n"
    )
    h, t = _tree(tmp_path, BATCH, src)
    assert batches_without_rerun_test(h, t) == (1, [])


def test_new_batch_without_test_is_caught_in_a_real_tree_copy(tmp_path: Path) -> None:
    h, t = _tree(tmp_path, BATCH, GOOD_TEST)
    (h / "bar_batch.py").write_text(BATCH, encoding="utf-8")  # 새 배치 — 테스트 없음
    scanned, violations = batches_without_rerun_test(h, t)
    assert scanned == 2 and violations == ["bar_batch: 테스트 파일 없음(test_bar_batch.py)"]


def test_exempt_entry_skips_only_that_batch(tmp_path: Path) -> None:
    h, t = _tree(tmp_path, BATCH, None)
    assert batches_without_rerun_test(h, t, exempt={"foo_batch": ("사유", "2999-01-01")}) == (1, [])
