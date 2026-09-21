"""`tests/` 하위 테스트 디렉터리 ↔ CI 실행 경로의 **배선 실재성** 동결.

왜 이 테스트가 있는가 (2026-07-26 사고)
--------------------------------------
`tests/infra/`의 운영 자산 계약 테스트 199건은 **어느 CI 잡도 실행하지 않았다**. 파일은
존재했고, 초록색 CI도 있었고, 문서도 그 계약을 인용했지만, 정작 그 테스트들은 한 번도 돌지
않았다(`grep 'tests/infra' ci.yml` 0건). "검증 장치가 있다"와 "검증 장치가 작동한다"가 분리돼
있었고, **후자를 확인하는 장치가 없었다**. OPS-03에서 `infra-contracts` 잡을 만들어 그 공백을
닫았지만, *같은 사고가 다음 디렉터리에서 반복되는 것*은 막지 못한다 — 새 테스트 디렉터리를
만들고 CI 배선을 잊으면 아무도 모른다. 이 테스트가 그 일반형을 닫는다.

같은 구조의 사고가 이번 세션에만 4건이었다(tests/infra 미실행 · required check 강제 off ·
`test_devices.py`가 뒤 테스트 덕에 우연히 통과 · 문서 잡 목록이 CI 성장을 못 따라감). 공통
원인은 "원칙은 CLAUDE.md에 있는데 적용이 사람의 기억에 걸려 있다"였다. 그래서 새 규칙을 만들지
않고 **기존 규칙(`측정 없는 기계 게이트 금지`)을 기계 장치로 바꾼다**.

검증 계약 (각 항목은 변별력이 확인된 것만)
----------------------------------------
① `tests/` 하위에서 테스트 파일을 **직접 담은 모든 디렉터리**가 CI의 실제 pytest 실행 경로로
   도달 가능하다. 배선의 단위는 언제나 **워크플로의 pytest 실행 1건**이며, 그 실행이 무엇을
   수집하는지는 실제 파일을 파싱해 얻는다 —
   (a) 명령의 경로 인자(`python3 -m pytest tests/infra`)
   (b) 인자가 없으면 그 실행의 작업 디렉터리에 적용되는 `pyproject.toml`의
       `[tool.pytest.ini_options] testpaths` (실제 `backend`·`data-pipeline` 잡의 형태)
   → `testpaths`에 적혀 있다는 사실만으로는 배선이 아니다. **그 디렉터리에서 pytest를 실제로
   돌리는 잡이 있어야** 배선이다(적혀만 있고 아무도 안 도는 상태가 곧 이번 사고였다).
   `--ignore`로 제외된 경로는 그 실행의 수집 범위에서 차감한다.
② 의도적 미배선은 **사유 필수** 허용 목록으로만 통과한다(빈 사유는 무효 — OPS-06·OPS-08 선례).
   배선을 지운 채 목록에도 안 넣으면 실패한다.
③ 파서가 위장하지 않는다 — 워크플로를 못 읽거나, 배선을 하나도 못 찾거나, 테스트 트리를 빈
   목록으로 훑으면 "위반 0 통과"가 아니라 **예외로 실패**한다(OPS-08 `test_required_checks_doc`
   의 마커 부재 처리와 동형). "0건 통과"와 "측정 실패"는 절대 같은 색이면 안 된다.
④ 판정 함수 자체의 **변별력을 상시 봉인**한다 — 가짜 레포에 결함을 주입(디렉터리 추가·CI 스텝
   제거·testpaths 제거·`--ignore` 부착·파일 인자만 배선)해 각각이 실제로 검출됨을 CI가 매번
   재확인한다. 양성 대조(정상 배선은 통과)도 함께 둬 무차별 실패가 아님을 보인다.

의도적으로 검증하지 않는 것 (정직한 공백)
--------------------------------------
- **잡의 실행 조건(`if:`)은 모델링하지 않는다.** 배선이 존재하는지만 본다. schedule 전용 잡이나
  경로 필터로 skip되는 잡도 배선으로 친다(그 축은 `test_required_checks_doc.py`가 담당).
- **파일 인자는 디렉터리를 배선하지 않는다.** `pytest .../test_e2e_vertical_slice_integration.py`
  는 그 파일만 돌리므로 같은 디렉터리의 나머지는 여전히 미실행이다 — 더 엄격한 쪽을 택했다.
- **`tests/` 밖의 스위트는 범위 밖**이다(Flutter `src/mobile/test`·웹 `src/web/**`은 각자 잡이
  전용 러너로 돌린다). 이 테스트는 파이썬 `tests/` 트리만 본다.
- `-k`·`-m` 등 **선택 필터로 실질 미실행이 되는 경우**는 보지 않는다(디렉터리 도달성만 판정).
"""

from __future__ import annotations

import os
import re
import shlex
import tomllib
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TESTS_ROOT = _REPO_ROOT / "tests"

# 워크·스캔에서 건너뛸 디렉터리(가상환경·캐시·빌드 산출물 — 남의 pyproject·테스트가 섞인다)
_SKIP_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".dart_tool",
        "build",
        "dist",
        ".tox",
        "site-packages",
    }
)

# 배선하지 않기로 *의도한* 테스트 디렉터리 → 그 사유. 키는 레포 루트 기준 posix 상대경로.
# 빈 사유는 무효다(아래 `test_unwired_allowlist_entries_carry_a_reason`가 강제). 여기에 넣는
# 순간 "이 디렉터리는 CI에서 안 돈다"를 명시적으로 선언하는 것이며, 목록 자체가 리뷰 대상이다.
_INTENTIONALLY_UNWIRED: dict[str, str] = {}

# 셸 토큰 분해 보조 --------------------------------------------------------------
_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SEPARATORS = frozenset({"&&", "||", ";", "|", "&"})
_PYTEST_NAMES = frozenset({"pytest", "py.test"})
_PYTHON_NAMES = frozenset({"python", "python3", "python3.12", "py"})

# 값을 하나 더 먹는 옵션(다음 토큰을 경로 인자로 오인하지 않으려면 반드시 소비해야 한다)
_VALUE_OPTIONS = frozenset(
    {
        "-m",
        "-k",
        "-c",
        "-p",
        "-n",
        "-o",
        "-W",
        "--ignore",
        "--ignore-glob",
        "--deselect",
        "--rootdir",
        "--override-ini",
        "--junitxml",
        "--maxfail",
        "--cov",
    }
)
# 실행 대상을 *빼는* 옵션 — 배선 판정에서 차감한다(예: `pytest -m integration --ignore=.../l3`)
_IGNORE_OPTIONS = frozenset({"--ignore", "--ignore-glob", "--deselect"})


@dataclass(frozen=True)
class Wiring:
    """CI가 실제로 실행하는 pytest 경로 한 건.

    `roots`는 실행 대상 경로(디렉터리 또는 파일), `ignores`는 같은 실행에서 제외된 경로다.
    디렉터리 배선은 **디렉터리 root만** 인정한다(파일 root는 그 파일만 돌리므로).
    """

    source: str  # 예: "ci.yml:infra-contracts#2"
    kind: str  # "args"(명령 경로 인자) | "testpaths"(작업 디렉터리 ini 설정)
    roots: tuple[Path, ...]
    ignores: tuple[Path, ...]

    def covers(self, directory: Path) -> bool:
        """이 실행이 `directory` 안의 테스트를 (전부) 수집하는가."""
        reached = any(root.is_dir() and _is_within(directory, root) for root in self.roots)
        if not reached:
            return False
        return not any(_is_within(directory, ignored) for ignored in self.ignores)


def _is_within(child: Path, ancestor: Path) -> bool:
    """`child`가 `ancestor` 자신이거나 그 하위인가."""
    return child == ancestor or ancestor in child.parents


def _rel(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return str(path)


# ── 셸 스크립트에서 pytest 실행 인자 추출 ───────────────────────────────────────


def _logical_lines(script: str) -> list[str]:
    """백슬래시 줄바꿈을 이어 붙여 *논리적 한 줄*로 만든다.

    ci.yml의 pytest는 `pytest \\`+`--cov=...` 형태로 여러 줄에 걸쳐 있다. 줄 단위로 보면
    경로 인자를 놓치므로 반드시 합쳐서 본다.
    """
    lines: list[str] = []
    buffer = ""
    for raw in script.splitlines():
        stripped = raw.rstrip()
        if stripped.endswith("\\"):
            buffer += stripped[:-1] + " "
            continue
        buffer += stripped
        lines.append(buffer)
        buffer = ""
    if buffer:
        lines.append(buffer)
    return lines


def _simple_commands(line: str, origin: str, subject: str = "pytest") -> list[list[str]]:
    """한 논리 줄을 `&&`·`|`·`;` 기준으로 나눠 단순 명령 토큰 목록으로 만든다.

    토큰화 실패는 **예외로 올린다** — 조용히 빈 목록을 돌려주면 그 줄의 배선이 통째로
    사라지고, 그래도 이 파일의 다른 테스트가 "통과"할 수 있다(계약 ③).

    `subject`는 실패 메시지에만 쓴다 — OPS-13의 lint 커버리지 검사가 이 함수를 그대로
    재사용하므로(중복 파서 금지), 그쪽 실패가 "pytest 줄"로 잘못 보고되지 않게 한다.
    """
    try:
        tokens = shlex.split(line, comments=True)
    except ValueError as exc:  # 따옴표 불균형 등
        raise AssertionError(
            f"{origin}: {subject}가 등장하는 셸 줄을 토큰화하지 못했다 ({exc}). "
            f"파서가 조용히 배선을 흘리지 않도록 실패시킨다.\n  줄: {line}"
        ) from exc
    commands: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in _SEPARATORS:
            if current:
                commands.append(current)
            current = []
            continue
        current.append(token)
    if current:
        commands.append(current)
    return commands


def _pytest_args(command: list[str]) -> list[str] | None:
    """단순 명령이 pytest 실행이면 그 인자 목록을, 아니면 None을 돌려준다.

    `pip install pytest pytest-randomly`처럼 pytest가 *인자로* 등장하는 줄을 실행으로
    오인하지 않는 것이 핵심이다(실제로 ci.yml에 그런 줄이 있다).
    """
    index = 0
    while index < len(command) and _ENV_ASSIGN.match(command[index]):
        index += 1  # `FOO=bar pytest ...` 형태의 앞선 env 대입 건너뛰기
    if index >= len(command):
        return None
    head = PurePosixPath(command[index]).name
    if head in _PYTEST_NAMES:
        return command[index + 1 :]
    if (
        head in _PYTHON_NAMES
        and len(command) > index + 2
        and command[index + 1] == "-m"
        and command[index + 2] in _PYTEST_NAMES
    ):
        return command[index + 3 :]
    return None


def _classify_paths(
    args: Iterable[str], workdir: Path, repo_root: Path
) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    """pytest 인자에서 (실행 대상 경로, 제외 경로)를 뽑아 절대 경로로 해소한다.

    해소되지 않는 토큰(존재하지 않거나 레포 밖)은 버린다 — 오타난 경로를 배선으로 세지
    않기 위해서다. 버리는 방향이 **안전한 실패**다(그 디렉터리는 미배선으로 검출된다).
    """
    raw_roots: list[str] = []
    raw_ignores: list[str] = []
    tokens = list(args)
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            index += 1
            continue
        if token.startswith("-"):
            name, separator, value = token.partition("=")
            if separator:
                if name in _IGNORE_OPTIONS:
                    raw_ignores.append(value)
            elif token in _VALUE_OPTIONS and index + 1 < len(tokens):
                if token in _IGNORE_OPTIONS:
                    raw_ignores.append(tokens[index + 1])
                index += 1
            index += 1
            continue
        raw_roots.append(token)
        index += 1

    def resolve(entries: list[str]) -> tuple[Path, ...]:
        resolved: list[Path] = []
        for entry in entries:
            candidate = (workdir / entry).resolve()
            if not candidate.exists():
                continue
            if not _is_within(candidate, repo_root):
                continue
            resolved.append(candidate)
        return tuple(resolved)

    return resolve(raw_roots), resolve(raw_ignores)


# ── 배선 수집 (워크플로 · pyproject) ────────────────────────────────────────────


def _default_working_directory(node: Mapping[str, Any]) -> str | None:
    defaults = node.get("defaults")
    if not isinstance(defaults, dict):
        return None
    run = defaults.get("run")
    if not isinstance(run, dict):
        return None
    value = run.get("working-directory")
    return str(value) if value else None


def _collect_workflow_wirings(repo_root: Path) -> list[Wiring]:
    """`.github/workflows/*.yml`의 모든 pytest 실행을 파싱한다 — **배선의 유일한 단위**.

    경로 인자가 없는 실행(`pytest --cov=...`)은 작업 디렉터리에 적용되는 `testpaths`가 수집
    범위가 된다(계약 ①-b). 워크플로를 못 읽는 상황(디렉터리 부재·파일 0건·jobs 공백·YAML
    파손)은 전부 **예외**다 — 파서 무력화가 곧 통과가 되면 안 된다(계약 ③).
    """
    testpaths_index = _testpaths_index(repo_root)
    workflow_dir = repo_root / ".github" / "workflows"
    if not workflow_dir.is_dir():
        raise AssertionError(f"{workflow_dir}: 워크플로 디렉터리가 없다 — CI 배선을 읽을 수 없다.")
    paths = sorted(p for p in workflow_dir.iterdir() if p.suffix in {".yml", ".yaml"})
    if not paths:
        raise AssertionError(f"{workflow_dir}: 워크플로 파일이 하나도 없다 — 배선 파싱 불가.")

    wirings: list[Wiring] = []
    for path in paths:
        spec = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(spec, dict):
            raise AssertionError(f"{path}: 워크플로 YAML이 매핑으로 파싱되지 않았다.")
        jobs = spec.get("jobs")
        if not isinstance(jobs, dict) or not jobs:
            raise AssertionError(f"{path}: jobs 블록이 비었다 — 파서가 배선을 읽지 못하는 상태다.")
        workflow_workdir = _default_working_directory(spec)
        for job_id, job in jobs.items():
            if not isinstance(job, dict):
                continue
            job_workdir = _default_working_directory(job) or workflow_workdir
            steps = job.get("steps")
            if not isinstance(steps, list):
                continue
            for step_index, step in enumerate(steps):
                if not isinstance(step, dict):
                    continue
                script = step.get("run")
                if not isinstance(script, str) or "pytest" not in script:
                    continue
                step_workdir = step.get("working-directory") or job_workdir
                workdir = repo_root / str(step_workdir) if step_workdir else repo_root
                origin = f"{path.name}:{job_id}#{step_index}"
                for args in _iter_pytest_arg_lists(script, origin):
                    roots, ignores = _classify_paths(args, workdir, repo_root)
                    kind = "args"
                    if not roots:
                        # 경로 인자 없는 실행 = ini의 testpaths가 수집 범위(pytest 기본 동작).
                        roots = _implicit_roots(workdir, testpaths_index, repo_root)
                        kind = "testpaths"
                    wirings.append(Wiring(source=origin, kind=kind, roots=roots, ignores=ignores))
    return wirings


def _implicit_roots(
    workdir: Path, index: Mapping[Path, tuple[Path, ...]], repo_root: Path
) -> tuple[Path, ...]:
    """작업 디렉터리에서 위로 올라가며 처음 만나는 ini의 `testpaths`(pytest rootdir 탐색 근사)."""
    current = workdir.resolve()
    while True:
        if current in index:
            return index[current]
        if current == repo_root or current.parent == current:
            return ()
        current = current.parent


def _iter_pytest_arg_lists(script: str, origin: str) -> Iterator[list[str]]:
    for line in _logical_lines(script):
        if "pytest" not in line:
            continue
        for command in _simple_commands(line, origin):
            args = _pytest_args(command)
            if args is not None:
                yield args


def _iter_pyprojects(repo_root: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        if "pyproject.toml" in filenames:
            yield Path(dirpath) / "pyproject.toml"


def _testpaths_index(repo_root: Path) -> dict[Path, tuple[Path, ...]]:
    """`pyproject.toml`이 있는 디렉터리 → 그 ini의 `testpaths` 절대경로 목록.

    `testpaths`가 **실재하지 않는 경로**를 가리키면 예외다 — 배선이 허공을 가리키는데
    "배선됨"으로 세면 그것이 곧 위장이다.
    """
    index: dict[Path, tuple[Path, ...]] = {}
    for path in sorted(_iter_pyprojects(repo_root)):
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        tool = data.get("tool")
        if not isinstance(tool, dict):
            continue
        ini_options = tool.get("pytest", {}).get("ini_options", {})
        if not isinstance(ini_options, dict):
            continue
        raw = ini_options.get("testpaths")
        if raw is None:
            continue
        entries = shlex.split(raw) if isinstance(raw, str) else [str(e) for e in raw]
        roots: list[Path] = []
        for entry in entries:
            resolved = (path.parent / entry).resolve()
            if not resolved.exists():
                raise AssertionError(
                    f"{_rel(path, repo_root)}: testpaths '{entry}'가 실재하지 않는다 "
                    f"({resolved}) — 배선이 허공을 가리킨다."
                )
            roots.append(resolved)
        index[path.parent.resolve()] = tuple(roots)
    return index


def _all_wirings(repo_root: Path = _REPO_ROOT) -> list[Wiring]:
    return _collect_workflow_wirings(repo_root)


# ── 테스트 트리 스캔 · 판정 ─────────────────────────────────────────────────────


def _test_directories(tests_root: Path) -> list[Path]:
    """테스트 파일(`test_*.py`)을 **직접** 담은 디렉터리 전부.

    트리를 못 읽으면 예외다 — 빈 목록을 돌려주면 아래 판정이 "위반 0"으로 통과해버린다.
    """
    if not tests_root.is_dir():
        raise AssertionError(f"{tests_root}: 테스트 루트가 없다 — 스캔 대상이 사라졌다.")
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(tests_root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        if any(f.startswith("test_") and f.endswith(".py") for f in filenames):
            found.append(Path(dirpath))
    return sorted(found)


def _unwired_directories(
    repo_root: Path,
    directories: Iterable[Path],
    wirings: Iterable[Wiring],
    allowlist: Mapping[str, str],
) -> list[str]:
    """어떤 pytest 실행에도 포함되지 않는 디렉터리의 상대경로 목록(허용 목록 제외).

    **빈 사유 등재는 면제로 치지 않는다** — 사유 없이 목록에 이름만 올려 두는 것이 가장 쉬운
    우회로이기 때문이다. 그런 항목은 여기서도 위반으로 보고되고, 사유 강제 테스트에서도 따로
    실패한다(신호 2개).
    """
    wiring_list = list(wirings)
    leaking: list[str] = []
    for directory in directories:
        relative = _rel(directory, repo_root)
        if allowlist.get(relative, "").strip():
            continue
        if not any(wiring.covers(directory) for wiring in wiring_list):
            leaking.append(relative)
    return leaking


def _wiring_report(repo_root: Path, wirings: Iterable[Wiring]) -> str:
    lines: list[str] = []
    for wiring in wirings:
        roots = ", ".join(_rel(r, repo_root) for r in wiring.roots) or "(경로 인자 없음)"
        line = f"  - {wiring.source} [{wiring.kind}] → {roots}"
        if wiring.ignores:
            line += "  (제외: " + ", ".join(_rel(i, repo_root) for i in wiring.ignores) + ")"
        lines.append(line)
    return "\n".join(lines)


# ── 계약 ① · ② : 실제 레포 판정 ────────────────────────────────────────────────


def test_every_test_directory_is_wired_to_a_ci_job() -> None:
    """계약 ① — `tests/` 하위 모든 테스트 디렉터리가 CI의 실제 pytest 경로에 닿아야 한다.

    실패 = 그 디렉터리의 테스트는 **작성됐지만 아무도 실행하지 않는다**. `tests/infra` 199건이
    정확히 그 상태로 존재했다(2026-07-26). 초록 CI는 그 사실을 알려주지 않는다.
    """
    directories = _test_directories(_TESTS_ROOT)
    wirings = _all_wirings()
    leaking = _unwired_directories(_REPO_ROOT, directories, wirings, _INTENTIONALLY_UNWIRED)
    assert not leaking, (
        "CI의 어떤 pytest 실행에도 포함되지 않는 테스트 디렉터리가 있다 — 이 파일들은 "
        "작성만 되고 실행되지 않는다:\n"
        + "\n".join(f"  · {path}" for path in leaking)
        + "\n\n현재 인식된 배선(파일 파싱 결과):\n"
        + _wiring_report(_REPO_ROOT, wirings)
        + "\n\n해결: ① ci.yml 잡에 `pytest <경로>` 스텝을 추가하거나 ② 해당 패키지 "
        "pyproject.toml의 testpaths에 포함시켜라. 정말 안 돌릴 거면 이 파일의 "
        "_INTENTIONALLY_UNWIRED에 **사유와 함께** 등재하라."
    )


def test_tests_infra_itself_is_wired() -> None:
    """계약 ①의 특칭 — 사고의 진원지(`tests/infra`)가 실제로 배선돼 있는지 별도 동결.

    이 디렉터리가 새면 이 파일 자신을 포함한 모든 계약 테스트가 침묵한다. 일반 계약이 리팩터로
    느슨해져도 이 한 줄은 남도록 경로를 박아 둔다.
    """
    wirings = _all_wirings()
    covering = [w for w in wirings if w.covers(_TESTS_ROOT / "infra")]
    assert covering, (
        "tests/infra가 어떤 CI pytest 실행에도 포함되지 않는다 — 이 파일 자신도 CI에서 "
        "돌지 않는다는 뜻이다(2026-07-26 사고의 재발).\n현재 배선:\n"
        + _wiring_report(_REPO_ROOT, wirings)
    )


def test_tests_harness_itself_is_wired() -> None:
    """계약 ①의 특칭 2 — 대장 CLI 계약(`tests/harness`)이 실제로 배선돼 있는지 별도 동결.

    왜 특칭이 하나 더 필요한가 (HARN-59 ③)
    ------------------------------------
    `backlog.py`는 사람이 **매일** 쓰는 유일한 대장 조작 경로이고, 그 CLI의 안전장치는 전부
    `tests/harness`에만 산다 — 대장 손편집 금지를 집행하는 거부들, `done`의 PR 증적 게이트,
    `amend`의 정정 축, `check-edit` 훅의 조율 정책 3분기. 이 디렉터리가 CI에서 새면 그 거부들이
    **전부 조용히 무력해진다**: 코드는 남아 있고 테스트 파일도 남아 있으므로 아무 신호가 없다.

    일반 계약(`test_every_test_directory_is_wired_to_a_ci_job`)이 이미 이 디렉터리를 덮지만,
    일반 계약은 리팩터·허용 목록 추가로 느슨해질 수 있다. `tests/infra`와 같은 이유로 경로를
    한 줄 박아 둔다 — 느슨해지는 순간 이 줄이 먼저 붉어진다.

    (HARN-59 ③이 요구한 "신규 테스트가 CI에서 실제로 실행되는지 대조"의 집행 지점이다. 배선의
    단위는 **디렉터리**이므로 파일마다 계약을 두지 않는다 — 배선된 디렉터리에 놓인 새 파일은
    pytest가 자동 수집한다. 파일 단위로 열거하면 새 파일마다 목록 갱신을 사람이 기억해야 하고,
    그 기억이 이 저장소가 이미 네 번 실패한 지점이다.)
    """
    wirings = _all_wirings()
    covering = [w for w in wirings if w.covers(_TESTS_ROOT / "harness")]
    assert covering, (
        "tests/harness가 어떤 CI pytest 실행에도 포함되지 않는다 — 대장 CLI의 거부·게이트·훅 "
        "계약이 전부 CI에서 검증되지 않는다는 뜻이다.\n현재 배선:\n"
        + _wiring_report(_REPO_ROOT, wirings)
    )


def test_unwired_allowlist_entries_carry_a_reason() -> None:
    """계약 ② — 미배선 허용은 **사유와 함께**여야 한다(빈 사유로 조용히 빠져나가지 못하게)."""
    empty = [name for name, reason in _INTENTIONALLY_UNWIRED.items() if not reason.strip()]
    assert not empty, f"미배선 허용 사유가 비어 있다(무효): {empty}"


def test_unwired_allowlist_has_no_stale_entries() -> None:
    """계약 ② 보강 — 허용 목록의 유령 항목 금지.

    이미 사라졌거나 이미 배선된 디렉터리가 목록에 남아 있으면, 나중에 같은 이름의 디렉터리가
    생겼을 때 **자동으로 면제**된다. 목록은 항상 현실과 일치해야 한다.
    """
    wirings = _all_wirings()
    stale: list[str] = []
    for relative in _INTENTIONALLY_UNWIRED:
        directory = _REPO_ROOT / relative
        if not directory.is_dir():
            stale.append(f"{relative} (디렉터리 없음)")
        elif any(w.covers(directory) for w in wirings):
            stale.append(f"{relative} (이미 배선됨 — 목록에서 제거하라)")
    assert not stale, f"미배선 허용 목록에 현실과 어긋난 항목이 있다: {stale}"


# ── 계약 ③ : 파서·스캐너가 위장하지 않는지 ──────────────────────────────────────


def test_scanner_actually_walks_the_real_test_tree() -> None:
    """계약 ③ — 스캐너가 빈/부분 목록을 돌려주면 위 판정 전체가 "위반 0"으로 위장된다.

    실제 트리를 봤음을 하한과 내부 정합으로 봉인한다: 스캔된 디렉터리들이 담은 테스트 파일의
    합이 `tests/` 전체 테스트 파일 수와 **정확히 일치**해야 한다(디렉터리를 흘리면 어긋난다).
    """
    directories = _test_directories(_TESTS_ROOT)
    assert len(directories) >= 10, (
        f"테스트 디렉터리를 {len(directories)}개만 찾았다 — 스캐너가 트리를 제대로 훑지 "
        "못하고 있다(이 상태면 미배선 판정이 무력화된다)."
    )
    scanned = sum(
        len([f for f in os.listdir(d) if f.startswith("test_") and f.endswith(".py")])
        for d in directories
    )
    actual = sum(
        1
        for path in _TESTS_ROOT.rglob("test_*.py")
        if not any(part in _SKIP_DIRS for part in path.parts)
    )
    assert (
        scanned == actual >= 100
    ), f"스캔된 테스트 파일 {scanned}건 ≠ 실제 {actual}건 — 스캐너가 디렉터리를 흘리고 있다."


def test_wiring_parser_finds_both_resolution_kinds() -> None:
    """계약 ③ — 두 수집 범위 해소 방식(명령 인자·작업 디렉터리 testpaths)을 모두 읽어냈는지.

    한쪽 파싱이 조용히 죽으면 그쪽으로 배선된 디렉터리가 전부 "미배선"으로 뜬다(안전한
    실패)지만, 그 원인을 즉시 알 수 있게 별도 신호를 둔다. 실제 CI는 두 방식을 다 쓴다 —
    `infra-contracts`/`harness-integrity`는 인자, `backend`/`data-pipeline`은 testpaths.
    """
    wirings = _all_wirings()
    kinds = {w.kind for w in wirings if any(root.is_dir() for root in w.roots)}
    assert kinds == {
        "args",
        "testpaths",
    }, f"배선 해소 방식이 {sorted(kinds)}뿐이다 — 한쪽 파서가 죽었다.\n" + _wiring_report(
        _REPO_ROOT, wirings
    )


def test_parser_fails_loudly_on_untokenizable_pytest_line() -> None:
    """계약 ③ — pytest 줄을 토큰화하지 못하면 조용히 넘어가지 않고 예외로 실패한다."""
    with pytest.raises(AssertionError, match="토큰화하지 못했다"):
        _simple_commands("pytest 'tests/infra", origin="fake.yml:job#0")


def test_pip_install_line_is_not_mistaken_for_a_pytest_run() -> None:
    """계약 ③ — `pip install pytest ...`를 실행으로 오인하면 가짜 배선이 생긴다.

    실제 ci.yml `infra-contracts` 잡에 그 줄이 있다. 오인하면 `pytest-asyncio` 같은 토큰이
    경로 인자로 해석될 여지가 생기므로 명시적으로 봉인한다.
    """
    commands = _simple_commands('pip install pytest pytest-randomly "sqlalchemy>=2.0"', "x#0")
    assert [_pytest_args(c) for c in commands] == [None]


# ── 계약 ④ : 결함 주입으로 변별력 상시 봉인 ─────────────────────────────────────
#
# 아래 테스트들은 tmp_path에 **가짜 레포**를 만들어 결함을 주입한다. 실제 저장소를 훼손하지
# 않으면서, "이 판정 장치가 실패 상태에서 실제로 실패 신호를 내는가"를 CI가 매번 재확인한다.
# (CLAUDE.md "변별력 없는 검증 스텝 금지" — 성공/실패 양쪽에서 같은 값을 내는 검사는 위장이다.)

_CI_TEMPLATE = """\
name: Fake CI
on: [push]
jobs:
  infra:
    runs-on: ubuntu-latest
    steps:
      - run: pip install pytest
{infra_step}
  package:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: src/pkg
    steps:
{package_step}"""

_INFRA_STEP = "      - run: python3 -m pytest tests/infra -q\n"
_PACKAGE_STEP = "      - run: pytest --cov=pkg{extra_args}\n"


def _build_fake_repo(
    root: Path,
    *,
    test_dirs: Iterable[str] = ("tests/infra", "tests/pkg"),
    infra_step: str = _INFRA_STEP,
    package_step: str = _PACKAGE_STEP,
    extra_args: str = "",
    testpaths: str | None = '["../../tests/pkg"]',
) -> Path:
    """결함 주입용 가짜 레포. 기본 상태는 **전부 정상 배선**(양성 대조의 기준점)."""
    for relative in test_dirs:
        directory = root / relative
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "test_sample.py").write_text("def test_x():\n    assert True\n", "utf-8")
    workflows = root / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    (workflows / "ci.yml").write_text(
        _CI_TEMPLATE.format(
            infra_step=infra_step, package_step=package_step.format(extra_args=extra_args)
        ),
        "utf-8",
    )
    package = root / "src" / "pkg"
    package.mkdir(parents=True, exist_ok=True)
    body = "[project]\nname = 'pkg'\n"
    if testpaths is not None:
        body += f"[tool.pytest.ini_options]\ntestpaths = {testpaths}\n"
    (package / "pyproject.toml").write_text(body, "utf-8")
    return root


def _leaks(root: Path, allowlist: Mapping[str, str] | None = None) -> list[str]:
    return _unwired_directories(
        root,
        _test_directories(root / "tests"),
        _all_wirings(root),
        allowlist if allowlist is not None else {},
    )


def test_control_fully_wired_repo_passes(tmp_path: Path) -> None:
    """양성 대조 — 정상 배선 상태에서는 위반 0. 이 장치가 무차별 실패기가 아님을 보인다."""
    root = _build_fake_repo(tmp_path)
    assert _leaks(root) == []


def test_defect_new_unwired_directory_is_detected(tmp_path: Path) -> None:
    """결함 ① — 새 테스트 디렉터리를 만들고 배선을 잊으면 검출된다(`tests/infra` 사고의 일반형)."""
    root = _build_fake_repo(tmp_path, test_dirs=("tests/infra", "tests/pkg", "tests/zz_probe"))
    assert _leaks(root) == ["tests/zz_probe"]


def test_defect_removed_ci_pytest_step_is_detected(tmp_path: Path) -> None:
    """결함 ② — ci.yml에서 `pytest tests/infra` 스텝을 지우면 그 디렉터리가 미배선으로 뜬다.

    2026-07-26 이전의 실제 상태를 그대로 재현한 것이다.
    """
    root = _build_fake_repo(tmp_path, infra_step="")
    assert _leaks(root) == ["tests/infra"]


def test_defect_removed_testpaths_is_detected(tmp_path: Path) -> None:
    """결함 ③ — pyproject의 `testpaths`가 사라지면 그 스위트가 미배선으로 뜬다."""
    root = _build_fake_repo(tmp_path, testpaths=None)
    assert _leaks(root) == ["tests/pkg"]


def test_defect_testpaths_without_any_job_running_it_is_detected(tmp_path: Path) -> None:
    """결함 ③-b — `testpaths`는 멀쩡한데 **그 패키지에서 pytest를 도는 잡이 없으면** 미배선.

    이번 사고의 정확한 형태다: 설정 파일에 적혀 있다는 사실은 실행의 증거가 아니다. 배선의
    단위를 "워크플로의 실제 pytest 실행"으로 잡아야만 이 누수가 잡힌다.
    """
    root = _build_fake_repo(tmp_path, package_step="      - run: echo '테스트 안 돌림'\n")
    assert _leaks(root) == ["tests/pkg"]


def test_defect_testpaths_pointing_nowhere_fails_loudly(tmp_path: Path) -> None:
    """결함 ④ — `testpaths`가 실재하지 않는 경로면 '배선됨'이 아니라 예외로 실패한다."""
    root = _build_fake_repo(tmp_path, testpaths='["../../tests/ghost"]')
    with pytest.raises(AssertionError, match="실재하지 않는다"):
        _all_wirings(root)


def test_defect_ignore_option_removes_coverage(tmp_path: Path) -> None:
    """결함 ⑤ — `--ignore`로 제외된 디렉터리는 배선으로 세지 않는다.

    이 모델이 없으면 "testpaths에 들어 있으니 배선됨"이라는 서류상 통과가 만들어진다.
    """
    root = _build_fake_repo(tmp_path, extra_args=" --ignore=../../tests/pkg")
    assert _leaks(root) == ["tests/pkg"]


def test_defect_file_argument_does_not_wire_the_directory(tmp_path: Path) -> None:
    """결함 ⑥ — 파일 인자 하나만 배선된 디렉터리는 '배선됨'이 아니다.

    그 디렉터리의 나머지 테스트는 여전히 실행되지 않는다(e2e-nightly가 파일 하나만 도는 것과
    같은 형태). 더 엄격한 쪽을 택한다.
    """
    root = _build_fake_repo(
        tmp_path,
        infra_step="      - run: python3 -m pytest tests/infra/test_sample.py\n",
    )
    assert _leaks(root) == ["tests/infra"]


def test_defect_blank_reason_allowlist_entry_stays_a_violation(tmp_path: Path) -> None:
    """결함 ⑦ — 빈 사유로 허용 목록에 넣어도 면제되지 않는다(허용 목록 = 가장 쉬운 우회로).

    양성 대조로 *제대로 된 사유*는 면제됨을 함께 확인한다 — 허용 목록이 죽은 코드가 아니라
    "사유를 쓰면 통과한다"는 실제 문이라는 뜻이고, 그래야 위반이 사유 없이 숨지 않는다.
    """
    root = _build_fake_repo(tmp_path, test_dirs=("tests/infra", "tests/pkg", "tests/zz_probe"))
    assert _leaks(root, {"tests/zz_probe": "   "}) == ["tests/zz_probe"]
    assert _leaks(root, {"tests/zz_probe": "수동 프로브 — CI 대상 아님"}) == []


def test_defect_broken_workflow_yaml_fails_loudly(tmp_path: Path) -> None:
    """결함 ⑧ — 워크플로에 jobs가 없으면 '배선 0건 통과'가 아니라 예외로 실패한다."""
    root = _build_fake_repo(tmp_path)
    (root / ".github" / "workflows" / "ci.yml").write_text("name: empty\non: [push]\n", "utf-8")
    with pytest.raises(AssertionError, match="jobs 블록이 비었다"):
        _all_wirings(root)


def test_defect_missing_workflow_dir_fails_loudly(tmp_path: Path) -> None:
    """결함 ⑨ — 워크플로 디렉터리 자체가 없으면 예외로 실패한다(측정 실패 ≠ 통과)."""
    root = _build_fake_repo(tmp_path)
    (root / ".github" / "workflows" / "ci.yml").unlink()
    with pytest.raises(AssertionError, match="워크플로 파일이 하나도 없다"):
        _all_wirings(root)
