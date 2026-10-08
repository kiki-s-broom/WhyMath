"""교육과정 표기 범위 게이트(MATH-04) 학생 경로 차단 — 소스 스캔 거버넌스.

왜 기계로 동결하는가: 이 게이트는 *생성물 회계 전용*이다. 학생 입력에 배선하면 "고2 방법은 쓰지
마세요"를 시스템이 말하게 되고, 그것은 부정적 피드백의 정서적 강화이자 앞서 배운 방법으로 푸는 학생을
처벌하는 교수학 금기다(CLAUDE.md 교수학 금기·gap_review §2-⑤). 선언으로만 두면 다음 세션이 학생
입력 경로에 배선한다 — 모듈이 아직 아무 데서도 쓰이지 않는 지금은 이 검사가 **자명하게 green**이므로,
합성 트리에 import를 주입해 RED가 나는지(변별력)를 상시 테스트로 함께 동결한다.

두 겹으로 막는다:
  ① 명시 금지 — `api/`·`l4/polya/`·`l4/socratic/`(학생 입력이 흐르는 경로)에서 게이트 모듈·데이터 파일의
     언급이 0건. 금지 토큰 방식이라 `import`·상대 import·`importlib` 문자열·데이터 파일 직접 읽기를
     한꺼번에 잡는다(표기 형태에 의존하지 않는다).
  ② 허용 목록(deny-by-default) — 게이트를 언급할 수 있는 `.py`는 엔진·CLI 둘뿐이다. 명시 3개 디렉터리
     밖의 학생 대면 경로(`l4/solution_coaching` 등)로 새는 것도 막는다. 정당한 신규 사용처(생성 파이프라인
     등)는 이 목록에 *의식적으로* 더한다 — 그 마찰이 곧 의도다.

스캔이 대상을 0건 찾으면 실패한다(공허한 통과 금지).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

# tests/backend/l3/ → parents[3] = 레포 루트.
_ROOT = Path(__file__).resolve().parents[3]
_PKG = _ROOT / "src" / "backend" / "whymath_backend"

# 금지 토큰 — `curriculum_notation_gate`는 엔진·CLI 두 모듈명을 모두 잡고, `curriculum_notation_range`는
# 표(`..._ranges.json`)·베이스라인(`..._range_baseline.json`)을 모듈 우회로 직접 읽는 경로를 잡는다.
FORBIDDEN_TOKENS: tuple[str, ...] = ("curriculum_notation_gate", "curriculum_notation_range")

# 학생 입력이 흐르는 경로(task 명시). 패키지 루트 기준 상대 경로.
STUDENT_PATH_DIRS: tuple[str, ...] = ("api", "l4/polya", "l4/socratic")

# 게이트를 언급할 수 있는 유일한 소스 파일(패키지 루트 기준) — 엔진과 그것을 부르는 CLI.
ALLOWED_REFERENCERS: frozenset[str] = frozenset(
    {"l3/curriculum_notation_gate.py", "harness/curriculum_notation_gate_cli.py"}
)


def scan_references(pkg_root: Path, subdirs: Sequence[str] | None = None) -> dict[str, list[str]]:
    """`pkg_root` 아래 `.py` 중 금지 토큰을 포함한 파일 → 발견 토큰. `subdirs`면 그 하위만 본다.

    Raises:
        AssertionError: 대상 디렉터리 부재 또는 스캔 파일 0건(공허한 통과 금지).
    """
    bases = [pkg_root / s for s in subdirs] if subdirs else [pkg_root]
    files: list[Path] = []
    for base in bases:
        assert (
            base.is_dir()
        ), f"스캔 대상 디렉터리 부재: {base} — 경로가 바뀌었다면 거버넌스를 갱신하라"
        files.extend(sorted(base.rglob("*.py")))
    assert files, f"스캔 파일 0건: {bases} — 공허한 통과를 막기 위해 실패한다"
    hits: dict[str, list[str]] = {}
    for path in files:
        text = path.read_text(encoding="utf-8")
        found = [t for t in FORBIDDEN_TOKENS if t in text]
        if found:
            hits[path.relative_to(pkg_root).as_posix()] = found
    return hits


# ──────────────────────────────────────────────────────────────────────────
# 실트리 — 현재 상태
# ──────────────────────────────────────────────────────────────────────────
class TestRealTree:
    @pytest.mark.parametrize("subdir", STUDENT_PATH_DIRS)
    def test_student_path_does_not_reference_the_gate(self, subdir: str) -> None:
        hits = scan_references(_PKG, [subdir])
        assert hits == {}, (
            f"학생 입력 경로 {subdir}/ 가 교육과정 표기 범위 게이트를 참조한다: {hits}. 이 게이트는 "
            "생성물 회계 전용이다 — 학생 풀이를 학년 범위로 거르는 것은 교수학 금기다."
        )

    @pytest.mark.parametrize("subdir", STUDENT_PATH_DIRS)
    def test_student_path_scan_is_not_vacuous(self, subdir: str) -> None:
        files = list((_PKG / subdir).rglob("*.py"))
        assert (
            len(files) >= 3
        ), f"{subdir}/ 스캔 파일이 {len(files)}건 — 경로가 비어 있으면 검사가 공허하다"

    def test_only_allowlisted_modules_reference_the_gate(self) -> None:
        hits = scan_references(_PKG)
        stray = sorted(set(hits) - ALLOWED_REFERENCERS)
        assert not stray, (
            f"허용 목록 밖 파일이 게이트를 참조한다: {stray}. 정당한 생성 파이프라인 사용처라면 "
            "ALLOWED_REFERENCERS에 의식적으로 더하라(학생 대면 경로가 아님을 확인한 뒤)."
        )

    def test_allowlist_has_no_stale_entries(self) -> None:
        hits = scan_references(_PKG)
        assert set(hits) >= ALLOWED_REFERENCERS, (
            f"허용 목록의 파일이 실재하지 않거나 더는 게이트를 가리키지 않는다: "
            f"{sorted(ALLOWED_REFERENCERS - set(hits))}"
        )


# ──────────────────────────────────────────────────────────────────────────
# 변별력 — 합성 트리에 import를 주입하면 RED가 나는가 (이게 없으면 현재의 green은 위장이다)
# ──────────────────────────────────────────────────────────────────────────
_INJECTIONS: dict[str, str] = {
    "from-import": "from whymath_backend.l3.curriculum_notation_gate import run_gate\n",
    "plain-import": "import whymath_backend.l3.curriculum_notation_gate\n",
    "from-package-import": "from whymath_backend.l3 import curriculum_notation_gate\n",
    "relative-import": "from ...l3 import curriculum_notation_gate\n",
    "cli-import": "from whymath_backend.harness import curriculum_notation_gate_cli\n",
    "importlib-string": 'import importlib\nm = importlib.import_module("whymath_backend.l3.curriculum_notation_gate")\n',
    "data-file-read": 'import json\nt = json.load(open("data/curriculum_notation_ranges.json"))\n',
    "baseline-read": 'import json\nb = json.load(open("data/curriculum_notation_range_baseline.json"))\n',
}


def _make_tree(root: Path, subdirs: Sequence[str], *, injected: dict[str, str]) -> Path:
    """합성 패키지 — 각 서브디렉터리에 깨끗한 파일 2개, `injected`면 추가로 오염 파일 1개."""
    pkg = root / "whymath_backend"
    for sub in subdirs:
        d = pkg / sub
        d.mkdir(parents=True)
        (d / "clean_a.py").write_text("x = 1\n", encoding="utf-8")
        (d / "clean_b.py").write_text("def f() -> int:\n    return 2\n", encoding="utf-8")
        for name, body in injected.items():
            (d / f"injected_{name}.py").write_text(body, encoding="utf-8")
    return pkg


class TestDiscrimination:
    def test_clean_synthetic_tree_is_green(self, tmp_path: Path) -> None:
        pkg = _make_tree(tmp_path, STUDENT_PATH_DIRS, injected={})
        for sub in STUDENT_PATH_DIRS:
            assert scan_references(pkg, [sub]) == {}

    @pytest.mark.parametrize("form", sorted(_INJECTIONS))
    @pytest.mark.parametrize("subdir", STUDENT_PATH_DIRS)
    def test_every_injection_form_is_caught_in_every_student_dir(
        self, tmp_path: Path, subdir: str, form: str
    ) -> None:
        pkg = _make_tree(tmp_path, STUDENT_PATH_DIRS, injected={form: _INJECTIONS[form]})
        hits = scan_references(pkg, [subdir])
        assert list(hits) == [
            f"{subdir}/injected_{form}.py"
        ], f"{subdir}/ 에 주입한 '{form}' 형태를 스캔이 못 잡았다 — 검사가 변별력이 없다"

    def test_injection_outside_student_dirs_is_caught_by_the_allowlist_scan(
        self, tmp_path: Path
    ) -> None:
        pkg = _make_tree(
            tmp_path, ["l4/solution_coaching"], injected={"x": _INJECTIONS["from-import"]}
        )
        hits = scan_references(pkg)
        assert set(hits) - ALLOWED_REFERENCERS == {"l4/solution_coaching/injected_x.py"}

    def test_scan_refuses_a_missing_or_empty_target(self, tmp_path: Path) -> None:
        pkg = tmp_path / "whymath_backend"
        (pkg / "api").mkdir(parents=True)
        with pytest.raises(AssertionError, match="스캔 파일 0건"):
            scan_references(pkg, ["api"])
        with pytest.raises(AssertionError, match="부재"):
            scan_references(pkg, ["l4/polya"])
