#!/usr/bin/env python3
"""무상한 의존 pin 차단 게이트 — 의존 선언 전수에 상한을 요구한다 (OPS-94).

왜 필요한가
----------
2026-09-25 SQLAlchemy 2.1.0 배포로 `mypy --strict`가 34건 실패해 main CI가 막혔다(OPS-91).
그때 막은 것은 **SQLAlchemy 한 패키지**였고, OPS-92가 그 패키지의 전 지점 동일 상한을
동결했다. 같은 계열의 다른 패키지는 무방비였다 — 이 검사기가 그것을 전 패키지로 일반화한다.

착수 시점(2026-10-02) 실측: `src/backend`·`src/data-pipeline` 두 pyproject의 선언 중 상한이
없는 것이 **48건**이었고(런타임·extra·dev·build-system 전부), 그와 별개로 `pytest-randomly`는
backend가 `<4`로 묶는데 `ci.yml`의 `infra-contracts`·`harness-integrity` 잡 직설치는 무상한이라
**그 순간 최신 5.0.0이 깔리고 있었다** — SQLAlchemy 사고와 같은 모양의 검증 표면 불일치다
(같은 저장소의 두 곳이 서로 다른 메이저 위에서 돈다). 이 검사기는 그 둘을 **같은 규칙**으로 막는다.

무엇을 보는가 (스캔 범위 — 이 밖의 설치 경로는 보지 않는다)
---------------------------------------------------------
- 저장소의 모든 `pyproject.toml`: `project.dependencies` · `project.optional-dependencies`
  · `dependency-groups`(PEP 735) · `build-system.requires`
- `.github/workflows/*.yml`의 모든 `run` 스텝에서 `pip install`(·`python -m pip`·`uv pip`)로
  넘기는 요구사항 인자. 로컬 경로(`-e .[dev]`·`../backend`)는 PyPI 의존이 아니므로 거른다.

보지 않는 것(정직 기술): `Dockerfile`의 `RUN pip install`, `requirements*.txt`·잠금 파일(현재
저장소에는 없다), `tool.*` 표 안의 도구별 의존 선언, `npm`·`flutter` 의존.

검증 계약
--------
① **상한 존재** — 모든 선언 지점에 상한 연산자(`<`·`<=`·`==`·`~=`·`===`)가 있다. `!=`와 `>=`는
   상한이 아니다. 문자열 grep이 아니라 `packaging.requirements.Requirement`로 specifier를
   구성한 결과를 본다(표기 변형에 뚫리지 않는다).
② **상한 일치** — 같은 패키지의 상한 집합이 모든 지점에서 같다. 한 곳만 올리거나 내리면
   검증 표면이 갈린다(OPS-92 계약의 일반화). `sqlalchemy`만은 그 동결을 OPS-92가 소유하므로
   일치 검사를 **명시적으로 위임**한다(`DELEGATED_EQUALITY`) — 상한 존재는 여전히 이 검사기도 본다.
③ **예외는 만료 있는 허용 목록으로만** — `dependency_upper_bound_allowlist.toml`. 항목마다
   사유(10자 이상)와 만료일이 필수이고, 만료일은 오늘로부터 366일 이내여야 한다(사실상 영구인
   `2099-12-31` 같은 값은 "만료 없는 유예"다). 만료된 항목은 위반이고, 어느 지점도 면제하지
   못하는 항목(이미 상한이 생겼거나 선언이 사라졌다)도 위반이다 — 목록이 거짓이 되기 때문이다.
④ **스캔 0건은 실패** — pyproject를 못 찾거나 필수 두 파일 중 하나가 없거나 선언이 0건이거나
   워크플로가 없거나 `pip install` 명령이 한 건도 인식되지 않으면 통과가 아니라 측정 실패다.
⑤ **모르는 형태는 조용히 넘기지 않는다** — 해석 못 한 요구사항 · 해석 못 한 pip 옵션 · 직접 URL
   설치 · requirements/constraints 파일 설치 · 인식 못 한 설치 명령(`pipx`·`poetry add` 등)은
   전부 측정 실패다. 값을 가진 옵션을 모르고 지나치면 그 값을 패키지로 오인해 "0건 통과"가 된다.

종료 코드 (문서·CI가 의존한다)
----------------------------
0 통과 / 1 위반(상한 없음·상한 불일치·허용 목록 만료·허위 허용) / 2 측정 실패(파싱 실패 ·
대상 파일 0건 · 허용 목록 파손 · 인자 오류)

사용:  python3 scripts/ops/check_dependency_upper_bounds.py [--root 경로] [--allowlist 경로]
                                                          [--today YYYY-MM-DD]
의존:  PyYAML·packaging (infra-contracts 잡이 이미 설치한다 — packaging은 pytest의 의존).
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import sys
import tomllib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Final

import yaml
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

_REPO_ROOT: Final = Path(__file__).resolve().parents[2]
DEFAULT_ALLOWLIST: Final = "scripts/ops/dependency_upper_bound_allowlist.toml"

# 이 두 파일이 없으면 패키지 디렉터리가 옮겨졌거나 경로가 어긋난 것이다 — 일부만 스캔하고
# 통과하지 않도록 필수로 못 박는다(스캔 0건뿐 아니라 *스캔 일부 누락*도 위장 통과다).
REQUIRED_PYPROJECTS: Final = ("src/backend/pyproject.toml", "src/data-pipeline/pyproject.toml")

# 일치 검사(계약 ②)를 다른 테스트가 소유하는 패키지 — 값은 소유자 파일(저장소 루트 기준).
DELEGATED_EQUALITY: Final = {"sqlalchemy": "tests/infra/test_sqlalchemy_upper_bound.py"}

MAX_EXPIRY_DAYS: Final = 366
MIN_REASON_CHARS: Final = 10

# 위쪽을 막는 연산자 — 이 중 하나라도 있으면 "상한 있음"으로 친다.
_UPPER_OPERATORS: Final = frozenset({"<", "<=", "==", "~=", "==="})

_SKIP_DIRS: Final = frozenset(
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

_PIP_NAMES: Final = frozenset({"pip", "pip3"})
# 설치 명령인데 이 검사기가 해석하지 못하는 형태 — 조용히 건너뛰면
# 그 경로의 무상한 설치가 통째로 빠진다.
_FOREIGN_INSTALLERS: Final = (
    ("pipx", "install"),
    ("uv", "add"),
    ("uv", "tool", "install"),
    ("poetry", "add"),
    ("conda", "install"),
    ("mamba", "install"),
    ("easy_install",),
)

# `pip install` 옵션 분류 — 값을 가진 옵션을 모르면 그 값을 패키지로 오인한다.
_VALUELESS_OPTIONS: Final = frozenset(
    {
        "-U",
        "--upgrade",
        "--no-deps",
        "--user",
        "--no-cache-dir",
        "--force-reinstall",
        "-I",
        "--ignore-installed",
        "--pre",
        "--no-build-isolation",
        "--break-system-packages",
        "--disable-pip-version-check",
        "-q",
        "--quiet",
        "-v",
        "--verbose",
        "--no-warn-script-location",
        "--prefer-binary",
        "--no-index",
        "--dry-run",
        "--no-compile",
        "--require-virtualenv",
    }
)
_VALUE_OPTIONS: Final = frozenset(
    {
        "-i",
        "--index-url",
        "--extra-index-url",
        "-f",
        "--find-links",
        "-t",
        "--target",
        "--prefix",
        "--root",
        "--python",
        "--only-binary",
        "--no-binary",
        "--progress-bar",
        "--retries",
        "--timeout",
        "--trusted-host",
        "--cache-dir",
        "--upgrade-strategy",
        "-C",
        "--config-settings",
        "--report",
    }
)
_EDITABLE_OPTIONS: Final = frozenset({"-e", "--editable"})
_FILE_OPTIONS: Final = frozenset({"-r", "--requirement", "-c", "--constraint"})

_COMMAND_SEPARATORS: Final = frozenset({";", "&&", "||", "|", "&", "(", ")"})
# 설치 도구 이름이 *단어*로 등장하는 줄만 토큰화한다 — `pip-tools`·`pip_install_x.py`·`git add`처럼
# 무관한 줄을 토큰화하면 따옴표가 어긋난 줄 하나가 모든 PR의 CI를 측정 실패로 멈춘다.
_INSTALLER_WORD = re.compile(
    r"(?<![\w.-])(?:pip3?|pipx|uv|poetry|conda|mamba|easy_install)(?![\w.-])"
)
_REDIRECT = re.compile(r"^[0-9]*[<>]+&?$")
_LOCAL_ARCHIVE_SUFFIXES: Final = (".whl", ".tar.gz", ".tgz", ".zip")


class ScanError(Exception):
    """측정 자체가 불가능한 상태 — 종료 코드 2. 통과도 위반도 아니다."""


# ── 데이터 모델 ────────────────────────────────────────────────────────────────

Bound = tuple[str, Version | str]


@dataclass(frozen=True)
class Site:
    """의존이 선언된 한 지점."""

    package: str  # canonicalize_name — 대소문자·`_`/`-` 표기 차이를 흡수한다
    origin: str  # 사람이 읽는 위치(파일 :: 섹션 또는 잡 :: 스텝)
    raw: str  # 원문 요구사항 — 진단 출력용
    upper: frozenset[Bound]  # 상한 지정자 집합(비어 있으면 상한 없음)


@dataclass(frozen=True)
class Scan:
    sites: tuple[Site, ...]
    pyprojects: tuple[str, ...]
    workflows: tuple[str, ...]
    pip_commands: int  # 인식한 `pip install` 명령 수(`-e` 로컬 설치만 있는 명령도 센다)


@dataclass(frozen=True)
class AllowEntry:
    package: str
    reason: str
    expires: date
    sites: tuple[str, ...]  # 비어 있으면 그 패키지의 모든 지점, 아니면 origin 부분 문자열

    def covers(self, site: Site) -> bool:
        if site.package != self.package:
            return False
        return not self.sites or any(part in site.origin for part in self.sites)


@dataclass
class Judgement:
    missing: list[Site] = field(default_factory=list)  # 상한 없음 — 허용 목록에도 없다
    waived: list[tuple[Site, AllowEntry]] = field(default_factory=list)
    inconsistent: dict[str, list[Site]] = field(default_factory=dict)
    expired: list[AllowEntry] = field(default_factory=list)
    stale: list[AllowEntry] = field(default_factory=list)

    @property
    def violations(self) -> int:
        return len(self.missing) + len(self.inconsistent) + len(self.expired) + len(self.stale)

    @property
    def failed(self) -> bool:
        return self.violations > 0


# ── 요구사항 해석 ──────────────────────────────────────────────────────────────


def _upper_bounds(requirement: Requirement) -> frozenset[Bound]:
    """상한 연산자를 쓰는 지정자만 모은다. `<2`와 `<2.0`은 같은 상한이다(PEP 440 정규화)."""
    bounds: set[Bound] = set()
    for spec in requirement.specifier:
        if spec.operator not in _UPPER_OPERATORS:
            continue
        try:
            bounds.add((spec.operator, Version(spec.version)))
        except InvalidVersion:
            # `==2.*` 같은 와일드카드는 Version으로 못 읽는다 — 원문을 그대로 비교 키로 쓴다.
            bounds.add((spec.operator, spec.version))
    return frozenset(bounds)


def format_bounds(bounds: frozenset[Bound]) -> str:
    return ",".join(sorted(f"{operator}{version}" for operator, version in bounds)) or "상한 없음"


def _make_site(raw: str, origin: str) -> Site:
    try:
        requirement = Requirement(raw)
    except InvalidRequirement as exc:
        raise ScanError(f"{origin}: 요구사항을 해석하지 못했다 ({exc}) — {raw!r}") from exc
    return Site(
        package=canonicalize_name(requirement.name),
        origin=origin,
        raw=raw,
        upper=_upper_bounds(requirement),
    )


# ── pyproject ──────────────────────────────────────────────────────────────────


def _iter_pyprojects(root: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        if "pyproject.toml" in filenames:
            yield Path(dirpath) / "pyproject.toml"


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _pyproject_sites(path: Path, rel: str) -> list[Site]:
    try:
        data: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ScanError(f"{rel}: TOML을 읽지 못했다 ({type(exc).__name__}: {exc})") from exc

    project = data.get("project") or {}
    own_name = project.get("name")
    own = canonicalize_name(own_name) if isinstance(own_name, str) else None

    sections: list[tuple[str, Any, bool]] = [
        ("project.dependencies", project.get("dependencies") or [], False)
    ]
    for extra, deps in (project.get("optional-dependencies") or {}).items():
        sections.append((f"project.optional-dependencies.{extra}", deps, False))
    for group, deps in (data.get("dependency-groups") or {}).items():
        # PEP 735 그룹은 `{include-group = "..."}` 표를 항목으로 가질 수 있다
        sections.append((f"dependency-groups.{group}", deps, True))
    sections.append(
        ("build-system.requires", (data.get("build-system") or {}).get("requires") or [], False)
    )

    sites: list[Site] = []
    for section, deps, allow_tables in sections:
        if not isinstance(deps, list):
            raise ScanError(f"{rel} :: {section}: 목록이 아니다({type(deps).__name__})")
        for raw in deps:
            if isinstance(raw, dict) and allow_tables:
                continue
            if not isinstance(raw, str):
                raise ScanError(f"{rel} :: {section}: 요구사항 문자열이 아니다 — {raw!r}")
            site = _make_site(raw, f"{rel} :: {section}")
            if site.package == own:
                continue  # 자기 자신을 가리키는 extra 별칭(`pkg[a,b]`)은 외부 의존이 아니다
            sites.append(site)
    return sites


# ── 워크플로 `run` 스크립트 ────────────────────────────────────────────────────


def _logical_lines(script: str) -> list[str]:
    """백슬래시 이음을 풀어 논리적 한 줄로 만든다. 주석 줄은 끝이 `\\`여도 이어 붙이지 않는다."""
    lines: list[str] = []
    buffer = ""
    for raw in script.splitlines():
        line = raw.rstrip()
        if not buffer and line.lstrip().startswith("#"):
            continue
        if line.endswith("\\"):
            buffer += line[:-1] + " "
            continue
        buffer += line
        lines.append(buffer)
        buffer = ""
    if buffer:
        lines.append(buffer)
    return lines


def _simple_commands(line: str, origin: str) -> list[list[str]]:
    """한 논리 줄을 `&&`·`||`·`|`·`;` 기준의 단순 명령 토큰 목록으로 나눈다.

    토큰화 실패는 예외로 올린다 — 조용히 빈 목록을 돌려주면 그 줄의 설치가 통째로 사라진다.
    """
    lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = "#"
    try:
        tokens = list(lexer)
    except ValueError as exc:
        raise ScanError(f"{origin}: 셸 줄을 토큰화하지 못했다 ({exc}) — 줄: {line}") from exc
    commands: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in _COMMAND_SEPARATORS:
            if current:
                commands.append(current)
            current = []
            continue
        current.append(token)
    if current:
        commands.append(current)
    return commands


def _install_arguments(command: list[str]) -> list[str] | None:
    """`pip install`(·`python -m pip install`·`uv pip install`)이면 install 뒤 토큰을 준다."""
    for index, token in enumerate(command[:-1]):
        if Path(token).name in _PIP_NAMES and command[index + 1] == "install":
            return command[index + 2 :]
    return None


def _foreign_installer(command: list[str]) -> tuple[str, ...] | None:
    for index in range(len(command)):
        for pattern in _FOREIGN_INSTALLERS:
            if tuple(command[index : index + len(pattern)]) == pattern:
                return pattern
    return None


def _strip_redirections(arguments: list[str]) -> list[str]:
    """출력 리다이렉션(`> log`·`2>&1`) 이후는 패키지 인자가 아니다."""
    for index, token in enumerate(arguments):
        if _REDIRECT.match(token):
            cut = index - 1 if index > 0 and arguments[index - 1].isdigit() else index
            return arguments[:cut]
    return arguments


def _is_local_target(token: str) -> bool:
    return token.startswith((".", "/", "~")) or token.lower().endswith(_LOCAL_ARCHIVE_SUFFIXES)


def _requirement_arguments(arguments: list[str], origin: str) -> list[str]:
    """pip install 인자에서 PyPI 요구사항 문자열만 골라낸다(옵션·로컬 경로는 거른다)."""
    found: list[str] = []
    index = 0
    arguments = _strip_redirections(arguments)
    while index < len(arguments):
        token = arguments[index]
        index += 1
        if token.startswith("-"):
            name, has_value, inline_value = (
                token.partition("=") if token.startswith("--") else (token, "", "")
            )
            if name in _VALUELESS_OPTIONS:
                continue
            if name in _FILE_OPTIONS:
                raise ScanError(
                    f"{origin}: `{name}` 파일 설치는 판정하지 않는다 — "
                    "requirements/constraints 파일 안의 상한은 읽지 못한다"
                    "(규칙을 확장하거나 인자로 직접 넘긴다)."
                )
            if name in _EDITABLE_OPTIONS:
                if has_value:
                    target = inline_value
                elif index < len(arguments):
                    target = arguments[index]
                    index += 1
                else:
                    raise ScanError(f"{origin}: `{name}` 뒤에 대상이 없다")
                if "://" in target or target.startswith("git+"):
                    raise ScanError(
                        f"{origin}: 직접 URL·VCS editable 설치는 상한을 판정할 수 없다 — {target}"
                    )
                continue
            if name in _VALUE_OPTIONS:
                if not has_value:
                    index += 1  # 값 토큰을 삼킨다(패키지로 오인하지 않는다)
                continue
            raise ScanError(
                f"{origin}: 해석하지 못한 pip 옵션 `{token}` — 값을 가진 옵션이면 그 값을 패키지로 "
                "오인할 수 있으므로 조용히 넘기지 않는다."
            )
        if "://" in token or token.startswith("git+"):
            raise ScanError(f"{origin}: 직접 URL 설치는 상한을 판정할 수 없다 — {token}")
        if _is_local_target(token):
            continue
        found.append(token)
    return found


def _script_sites(script: str, origin: str) -> tuple[list[Site], int]:
    """`run` 스크립트 하나에서 (요구사항 지점, 인식한 pip install 명령 수)를 모은다."""
    sites: list[Site] = []
    commands_seen = 0
    for line in _logical_lines(script):
        if not _INSTALLER_WORD.search(line):
            continue
        for command in _simple_commands(line, origin):
            arguments = _install_arguments(command)
            if arguments is None:
                foreign = _foreign_installer(command)
                if foreign is not None:
                    raise ScanError(
                        f"{origin}: 인식 못 한 설치 명령 `{' '.join(foreign)}` — "
                        "이 검사기는 pip install만 판정한다. 조용히 넘기면 그 경로의 "
                        f"무상한 설치가 통째로 빠진다.\n  명령: {command}"
                    )
                continue
            commands_seen += 1
            for raw in _requirement_arguments(arguments, origin):
                sites.append(_make_site(raw, origin))
    return sites, commands_seen


def _workflow_sites(root: Path) -> tuple[list[Site], int, list[str]]:
    directory = root / ".github" / "workflows"
    paths = sorted(directory.glob("*.yml")) + sorted(directory.glob("*.yaml"))
    if not paths:
        raise ScanError(f"{_rel(directory, root)}: 워크플로 파일이 하나도 없다 — 스캔 불가.")
    sites: list[Site] = []
    commands = 0
    names: list[str] = []
    for path in paths:
        rel = _rel(path, root)
        names.append(rel)
        try:
            spec: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            raise ScanError(f"{rel}: YAML을 읽지 못했다 ({type(exc).__name__})") from exc
        jobs = (spec or {}).get("jobs") if isinstance(spec, dict) else None
        if not isinstance(jobs, dict):
            raise ScanError(f"{rel}: `jobs` 표가 없다 — 워크플로 형태가 아니다")
        for job_name, job in jobs.items():
            if not isinstance(job, dict):
                continue
            for number, step in enumerate(job.get("steps") or []):
                if not isinstance(step, dict) or not isinstance(step.get("run"), str):
                    continue
                label = step.get("name") or f"step[{number}]"
                found, seen = _script_sites(step["run"], f"{rel} :: {job_name} :: {label}")
                sites.extend(found)
                commands += seen
    return sites, commands, names


# ── 스캔 · 허용 목록 · 판정 ────────────────────────────────────────────────────


def scan_repository(root: Path) -> Scan:
    pyprojects = sorted(_iter_pyprojects(root))
    if not pyprojects:
        raise ScanError(
            f"{root}: pyproject.toml을 하나도 찾지 못했다 — 경로가 틀렸거나 스캔이 깨졌다."
        )
    rels = [_rel(path, root) for path in pyprojects]
    for required in REQUIRED_PYPROJECTS:
        if required not in rels:
            raise ScanError(
                f"필수 pyproject가 없다: {required} — 패키지 디렉터리가 옮겨졌다면 이 검사기의 "
                "REQUIRED_PYPROJECTS를 함께 고친다(일부만 스캔하고 통과하지 않는다)."
            )
    sites: list[Site] = []
    for path, rel in zip(pyprojects, rels, strict=True):
        sites.extend(_pyproject_sites(path, rel))
    if not sites:
        raise ScanError(
            "pyproject에서 의존 선언을 한 건도 읽지 못했다 — 파서가 깨졌다"
            "(스캔 0건은 통과가 아니다)."
        )

    workflow_sites, commands, workflow_names = _workflow_sites(root)
    if commands == 0:
        raise ScanError(
            "워크플로에서 `pip install` 명령을 한 건도 인식하지 못했다 — 파서가 깨졌다"
            "(스캔 0건은 통과가 아니다)."
        )
    sites.extend(workflow_sites)
    return Scan(
        sites=tuple(sites),
        pyprojects=tuple(rels),
        workflows=tuple(workflow_names),
        pip_commands=commands,
    )


_ENTRY_KEYS: Final = frozenset({"package", "reason", "expires", "sites"})


def load_allowlist(path: Path, today: date) -> list[AllowEntry]:
    if not path.is_file():
        raise ScanError(
            f"허용 목록 파일이 없다: {path} — 예외가 없어도 파일은 있어야 한다"
            "(실수로 지운 것과 '예외 없음'을 구분하려고)."
        )
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ScanError(f"{path}: 허용 목록을 읽지 못했다 ({type(exc).__name__}: {exc})") from exc
    unknown_top = sorted(set(data) - {"entries"})
    if unknown_top:
        raise ScanError(
            f"{path}: 알 수 없는 최상위 키 {unknown_top} — 오타로 항목이 사라지는 것을 막는다."
        )
    raw_entries = data.get("entries")
    if not isinstance(raw_entries, list):
        raise ScanError(f"{path}: `entries` 목록이 없다 — 예외가 없으면 `entries = []`로 명시한다.")

    entries: list[AllowEntry] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for number, raw in enumerate(raw_entries, start=1):
        where = f"{path} entries[{number}]"
        if not isinstance(raw, dict):
            raise ScanError(f"{where}: 표가 아니다")
        unknown = sorted(set(raw) - _ENTRY_KEYS)
        if unknown:
            raise ScanError(
                f"{where}: 알 수 없는 키 {unknown} — "
                "오타(`expire` 등)로 만료가 사라지는 것을 막는다."
            )
        missing = sorted(_ENTRY_KEYS - {"sites"} - set(raw))
        if missing:
            raise ScanError(
                f"{where}: 필수 키가 없다 {missing} — 사유와 만료일 없는 예외는 허용하지 않는다."
            )
        package, reason, expires = raw["package"], raw["reason"], raw["expires"]
        if not isinstance(package, str) or not package.strip():
            raise ScanError(f"{where}: package가 비었다")
        if not isinstance(reason, str) or len(reason.strip()) < MIN_REASON_CHARS:
            raise ScanError(f"{where}: reason은 {MIN_REASON_CHARS}자 이상의 사유 문장이어야 한다")
        if type(expires) is not date:  # datetime은 date의 하위 클래스 — 정확히 날짜만 받는다
            raise ScanError(
                f"{where}: expires는 TOML 날짜(YYYY-MM-DD, 따옴표 없이)여야 한다 — {expires!r}"
            )
        if expires - today > timedelta(days=MAX_EXPIRY_DAYS):
            raise ScanError(
                f"{where}: 만료일 {expires}이 오늘({today})로부터 {MAX_EXPIRY_DAYS}일을 넘는다 — "
                "사실상 영구한 예외는 '만료 없는 유예'다."
            )
        raw_sites = raw.get("sites", [])
        if not isinstance(raw_sites, list) or not all(isinstance(s, str) and s for s in raw_sites):
            raise ScanError(f"{where}: sites는 비어 있지 않은 문자열의 목록이어야 한다")
        entry = AllowEntry(
            package=canonicalize_name(package),
            reason=reason.strip(),
            expires=expires,
            sites=tuple(raw_sites),
        )
        key = (entry.package, entry.sites)
        if key in seen:
            raise ScanError(f"{where}: 같은 (package, sites) 항목이 둘 이상이다")
        seen.add(key)
        entries.append(entry)
    return entries


def judge(scan: Scan, entries: Sequence[AllowEntry], today: date) -> Judgement:
    result = Judgement()
    live = [entry for entry in entries if entry.expires >= today]
    result.expired = [entry for entry in entries if entry.expires < today]

    used: set[AllowEntry] = set()
    for site in scan.sites:
        if site.upper:
            continue
        owner = next((entry for entry in live if entry.covers(site)), None)
        if owner is None:
            result.missing.append(site)
        else:
            result.waived.append((site, owner))
            used.add(owner)
    # 살아 있는 허용 항목이 어느 지점도 면제하지 못했다면 목록이 거짓이다(이미 고쳤는데 안 지웠다).
    result.stale = [entry for entry in live if entry not in used]

    groups: dict[str, list[Site]] = {}
    for site in scan.sites:
        if site.upper and site.package not in DELEGATED_EQUALITY:
            groups.setdefault(site.package, []).append(site)
    for package, members in sorted(groups.items()):
        if len({member.upper for member in members}) > 1:
            result.inconsistent[package] = members
    return result


def delegation_problems(root: Path) -> list[str]:
    """위임된 일치 검사의 소유자가 실재하는가 — 허공을 가리키는 위임은 위장이다."""
    problems: list[str] = []
    for package, owner in sorted(DELEGATED_EQUALITY.items()):
        path = root / owner
        if not path.is_file():
            problems.append(f"{package}: 위임 대상 {owner}가 없다 — 일치 검사의 소유자가 사라졌다")
        elif package not in path.read_text(encoding="utf-8").lower():
            problems.append(f"{package}: 위임 대상 {owner}가 이 패키지를 더 이상 다루지 않는다")
    return problems


# ── 출력 · 진입점 ──────────────────────────────────────────────────────────────


def render(scan: Scan, judgement: Judgement, delegation: Sequence[str], today: date) -> list[str]:
    lines = [
        f"스캔 — pyproject {len(scan.pyprojects)}개 · 의존 선언 {len(scan.sites)}건 · "
        f"워크플로 {len(scan.workflows)}개 · pip install 명령 {scan.pip_commands}건"
    ]
    for site in judgement.missing:
        lines.append(f"  x [상한 없음] {site.origin} — {site.raw}")
    for package, members in judgement.inconsistent.items():
        lines.append(
            f"  x [상한 불일치] {package} — 지점마다 상한이 다르다"
            "(올리거나 내릴 때는 전 지점을 함께)"
        )
        lines.extend(
            f"      {member.origin} — {member.raw}  (상한 {format_bounds(member.upper)})"
            for member in members
        )
    for entry in judgement.expired:
        lines.append(f"  x [허용 목록 만료] {entry.package} — {entry.expires} 만료({entry.reason})")
    for entry in judgement.stale:
        lines.append(
            f"  x [허위 허용] {entry.package} — 어느 무상한 지점도 면제하지 못한다"
            f"(이미 상한이 생겼거나 선언이 사라졌다 — 항목을 지운다) · 사유: {entry.reason}"
        )
    for problem in delegation:
        lines.append(f"  x [위임 파손] {problem}")
    for site, entry in judgement.waived:
        remaining = (entry.expires - today).days
        lines.append(f"  - [허용] {site.origin} — {site.raw} (만료 {entry.expires}, D-{remaining})")
    for package, owner in sorted(DELEGATED_EQUALITY.items()):
        lines.append(f"  - [위임] {package} 상한 일치 검사 → {owner}(OPS-92)")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check_dependency_upper_bounds",
        description="pyproject·워크플로 인라인 설치 전 의존에 상한을 요구한다 (OPS-94).",
    )
    parser.add_argument("--root", default=None, help="저장소 루트(테스트 주입용)")
    parser.add_argument(
        "--allowlist", default=None, help="허용 목록 TOML(생략 시 저장소 기본 경로)"
    )
    parser.add_argument("--today", default=None, metavar="YYYY-MM-DD")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve() if args.root else _REPO_ROOT
    try:
        today = date.fromisoformat(args.today) if args.today else date.today()
    except ValueError as exc:
        print(f"[인자 오류] --today 형식({type(exc).__name__}): {args.today!r}", file=sys.stderr)
        return 2
    allowlist = Path(args.allowlist) if args.allowlist else root / DEFAULT_ALLOWLIST

    try:
        entries = load_allowlist(allowlist, today)
        scan = scan_repository(root)
    except ScanError as exc:
        print(f"측정 실패 — {exc}", file=sys.stderr)
        return 2

    judgement = judge(scan, entries, today)
    delegation = delegation_problems(root)
    for line in render(scan, judgement, delegation, today):
        print(line)
    failed = judgement.failed or bool(delegation)
    count = judgement.violations + len(delegation)
    print(f"판정: 실패 — 위반 {count}건" if failed else "판정: 통과")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
