#!/usr/bin/env python3
"""CI 의존 해석 고정(제약 파일) 갱신·검증 도구 (OPS-121).

왜 필요한가
----------
2026-10-08 `pydantic 2.14.0`이 PyPI에 올라온 지 약 20분 만에(14:34Z → 14:54Z) 머지 큐 실행 3건의
`mypy --strict`가 같은 줄에서 실패했다. 선언이 `pydantic>=2.9.0,<3`으로 **상한은 있으나 범위가
넓어서** OPS-94(상한 유무 검사)가 못 막는 부류이고, CI가 `pip install -e .[dev]`로 **매 실행 그날의
최신**을 해석하기 때문에 범위 안의 신규 릴리스가 PR 검사를 거치지 않고 main·머지 큐에 곧장 닿는다.
같은 계열이 langfuse v2/v4 혼재 → pytest-asyncio 1.4.0 → SQLAlchemy 2.1.0 → pydantic 2.14.0으로
**4회째**다(패키지만 바뀌고 구조는 같다). 판정 근거: `docs/reviews/ops121_*.md`
(Kiki 승인 2026-10-09).

해법: 해석 결과를 **제약 파일**(`infra/ci/constraints-py312.txt`)로 저장소 안에 고정한다.
제약 파일은 "이 패키지는 정확히 이 버전만 설치하라"는 목록이고, pip는 이를 어기는 버전을 고르지
않는다. 범위 안의 신규 릴리스는 **이 파일을 바꾸는 갱신 PR을 거쳐서만** main에 닿고,
그 PR이 전체 CI를 돌므로 깨지면 병합 전에 걸린다. 입력(의존 해석)이 코드와 같은 저장소 안에
있으므로 머지 큐의 입력은 코드뿐이다.

집행 방식: 워크플로 **최상위 `env: PIP_CONSTRAINT`** 한 줄. 새 잡이 생겨도 자동으로 고정되고, 설치
명령 19곳을 하나씩 고치다 빠뜨리는 일이 없다. pip는 이 환경변수를 빌드 격리 환경(hatchling 등)의
설치에도 전파한다.

두 하위 명령
-----------
- `refresh` — 제약 파일을 **새로 해석해 다시 쓴다.** python 3.12 + linux에서만 돈다(CI와 같은 해석을
  내려면 인터프리터·플랫폼이 같아야 한다 — 다르면 측정 실패). `--only a,b`는 긴급 경로: 그 패키지만
  올리고 나머지 핀은 그대로 둔다(영업일 1일 이내 보안 패치용).
- `check` — 네트워크 없이 도는 **정적 게이트.** 아래 계약을 본다.

`check`의 검증 계약
------------------
① **파일 형식** — 헤더(`generated`·`python`·`platform`·`targets`·`direct`)가 있고
   python 3.12·linux이며, 본문은 `이름==버전` 한 줄씩만, 같은 패키지가 두 번 나오지 않는다.
② **집행 도달** — `pip install`이 있는 **모든 워크플로 파일**의 최상위 `env`에 `PIP_CONSTRAINT`가
   기대 경로로 있다. 어느 잡·스텝의 `env`도, 어느 `run` 스크립트도 `PIP_CONSTRAINT`를 건드리지 않고,
   어느 pip 명령도 `--isolated`(환경변수를 무시한다)를 쓰지 않는다. 일부 잡이 옛 방식이면 RED.
③ **핀 완전성** — CI가 설치하는 구성(`CI_TARGETS`)의 직접 의존 전부와 빌드 의존(hatchling)에 핀이
   있고, 핀 버전이 선언 범위 안이다. 워크플로가 인라인으로 직접 설치하는 패키지(pytest·ruff, 그리고
   설치기 자신인 `pip<27` 부트스트랩)도 같다 — 설치기 버전이 떠다니면 같은 부류의 사고가 난다.
④ **직접 의존 집합 지문** — 헤더의 `direct`가 현재 선언(③의 전부)의 이름 집합 해시와 같다.
   의존을 추가·삭제하면 `refresh`를 다시 돌려야 한다(새 직접 의존의 전이 의존이 고정 없이
   떠다니는 것을 막는다).
⑤ **스캔 0건은 실패** — 워크플로가 없거나 `pip install`이 한 건도 인식되지 않거나 대상 pyproject가
   없으면 통과가 아니라 측정 실패다.
⑥ **연령(선택)** — `--max-age-days N`을 주면 `generated`가 N일보다 오래됐거나 미래 날짜인
   것을 위반으로 본다. **PR 경로에서는 쓰지 않는다**: 날짜는 시계에 따라 결과가 바뀌는
   입력이라, PR·머지 큐 CI에 넣으면 "코드만 바뀐다"는 이 파일의 목적이 깨진다.
   야간(schedule) 잡에서만 센서로 쓴다.

한계(정직 기술): 오프라인으로는 전이 의존의 일관성을 직접 볼 수 없다 — 직접 의존의 핀과 집합 지문만
본다. 전이 의존의 정합은 `refresh`가 해석할 때 pip 리졸버가 보장한다. Dockerfile 설치 표면과 `pip`
부트스트랩 상한은 OPS-103 소관이다.

종료 코드 (CI·문서가 의존한다)
----------------------------
0 통과 / 1 위반 / 2 측정 실패(파일·YAML 파싱 불가 · 스캔 0건 · refresh 환경 불일치 · pip 해석 실패)

사용:
  python3.12 scripts/ops/ci_constraints.py refresh [--only pydantic,mypy] [--today YYYY-MM-DD]
  python3 scripts/ops/ci_constraints.py check [--root 경로] [--today YYYY-MM-DD] [--max-age-days 30]
의존: check는 PyYAML·packaging (infra-contracts 잡이 이미 설치한다) + OPS-94 검사기(같은 디렉터리).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

import yaml
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

# ── 상수 ───────────────────────────────────────────────────────────────────────

CONSTRAINTS_REL: Final = "infra/ci/constraints-py312.txt"
ENV_NAME: Final = "PIP_CONSTRAINT"
# 잡마다 working-directory가 달라(src/backend 등) 상대경로는 깨진다 — 워크스페이스 절대경로로 고정.
EXPECTED_ENV_VALUE: Final = "${{ github.workspace }}/" + CONSTRAINTS_REL

# CI가 설치하는 구성. (pyproject 경로, 설치하는 extras). ci.yml의 `-e ".[dev]"`·`.[dev,postgres]`·
# `.[dev,neo4j]` 합집합이다. Dockerfile(백엔드 기본 구성)은 이 구성의 부분집합이다.
CI_TARGETS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("src/backend/pyproject.toml", ("dev",)),
    ("src/data-pipeline/pyproject.toml", ("dev", "neo4j", "postgres")),
)
REQUIRED_PYTHON: Final = (3, 12)
REQUIRED_PLATFORM_PREFIX: Final = "linux"
HEADER_KEYS: Final = ("generated", "python", "platform", "targets", "direct")
DEFAULT_MAX_AGE_DAYS: Final = 30

# 마커 평가 환경 — 실행 인터프리터가 아니라 **CI(ubuntu·3.12)** 기준으로 고정한다.
_MARKER_ENV: Final = {
    "python_version": "3.12",
    "python_full_version": "3.12.0",
    "sys_platform": "linux",
    "platform_system": "Linux",
    "os_name": "posix",
    "implementation_name": "cpython",
    "platform_machine": "x86_64",
    "extra": "",
}

_PIN_LINE: Final = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[A-Za-z0-9][A-Za-z0-9.!+_-]*)$"
)
_HEADER_LINE: Final = re.compile(r"^#\s*(?P<key>[a-z]+):\s*(?P<value>.*?)\s*$")
_PIP_INSTALL: Final = re.compile(r"\bpip3?\s+install\b")
_PIP_ISOLATED: Final = re.compile(r"(?<![\w-])--isolated\b")
_PIP_TIMEOUT_SECONDS: Final = 900


class ScanError(Exception):
    """측정 자체가 불가능한 상태 — 위반(1)이 아니라 측정 실패(2)다."""


# ── 데이터 ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Direct:
    """CI 구성이 직접 선언하는 의존 한 건."""

    name: str  # canonicalize_name
    requirement: Requirement
    source: str  # 사람이 읽는 출처 (파일 :: 섹션)


@dataclass(frozen=True)
class ConstraintsFile:
    header: dict[str, str]
    pins: dict[str, str]  # canonical name -> version
    problems: tuple[str, ...]  # 형식 위반 (파싱은 끝까지 해서 한꺼번에 보고한다)


@dataclass
class Report:
    violations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    workflows: int = 0
    pip_steps: int = 0
    pins: int = 0

    @property
    def failed(self) -> bool:
        return bool(self.violations)


# ── 직접 의존 수집 ─────────────────────────────────────────────────────────────


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ScanError(f"{path}: pyproject를 읽지 못했다 ({type(exc).__name__})") from exc


def _applies(requirement: Requirement) -> bool:
    """환경 마커가 CI(ubuntu·3.12)에서 참인가. 마커가 없으면 항상 참."""
    if requirement.marker is None:
        return True
    return bool(requirement.marker.evaluate(dict(_MARKER_ENV)))


def collect_direct(root: Path) -> list[Direct]:
    """`CI_TARGETS`가 설치하는 직접 의존 + 빌드 의존을 모은다."""
    found: list[Direct] = []
    for rel, extras in CI_TARGETS:
        path = root / rel
        if not path.is_file():
            raise ScanError(
                f"{rel}: 필수 pyproject가 없다 — 경로가 옮겨졌다면 CI_TARGETS를 고친다."
            )
        data = _read_toml(path)
        project = data.get("project")
        if not isinstance(project, dict):
            raise ScanError(f"{rel}: [project] 표가 없다")
        groups: list[tuple[str, list[str]]] = [
            ("dependencies", list(project.get("dependencies", [])))
        ]
        optional = project.get("optional-dependencies", {})
        for extra in extras:
            if extra not in optional:
                raise ScanError(f"{rel}: extra {extra!r}가 없다 — CI_TARGETS가 현실과 어긋났다.")
            groups.append((f"extra[{extra}]", list(optional[extra])))
        build = data.get("build-system", {}).get("requires", [])
        groups.append(("build-system", list(build)))
        for section, raws in groups:
            for raw in raws:
                try:
                    requirement = Requirement(raw)
                except InvalidRequirement as exc:
                    raise ScanError(
                        f"{rel} :: {section}: 요구사항을 해석하지 못했다 — {raw!r} ({exc})"
                    ) from exc
                if not _applies(requirement):
                    continue
                found.append(
                    Direct(canonicalize_name(requirement.name), requirement, f"{rel} :: {section}")
                )
    if not found:
        raise ScanError(
            "직접 의존을 한 건도 읽지 못했다 — 파서가 깨졌다 (스캔 0건은 통과가 아니다)"
        )
    return found


def collect_inline(root: Path) -> list[Direct]:
    """워크플로가 **인라인으로 직접 설치**하는 요구사항(pytest·ruff·`pip<27` 부트스트랩 등).

    OPS-94 스캔 결과를 재사용한다. 이 목록이 해석 대상에 빠지면 설치기·도구가 고정 없이 떠다닌다.
    """
    ops94 = _load_ops94(root)
    try:
        scan = ops94.scan_repository(root)
    except ops94.ScanError as exc:
        raise ScanError(f"OPS-94 스캔 실패: {exc}") from exc
    found: list[Direct] = []
    seen: set[tuple[str, str]] = set()
    for site in scan.sites:
        if not site.origin.startswith(".github/workflows/"):
            continue
        try:
            requirement = Requirement(site.raw)
        except InvalidRequirement as exc:
            raise ScanError(
                f"{site.origin}: 요구사항을 해석하지 못했다 — {site.raw!r} ({exc})"
            ) from exc
        name = canonicalize_name(requirement.name)
        if (name, site.raw) in seen or not _applies(requirement):
            continue
        seen.add((name, site.raw))
        found.append(Direct(name, requirement, site.origin))
    return found


def collect_all(root: Path) -> list[Direct]:
    """고정 대상 전부 = CI 구성의 pyproject 직접 의존 + 워크플로 인라인 직접 설치."""
    return collect_direct(root) + collect_inline(root)


def direct_fingerprint(directs: Sequence[Direct]) -> str:
    """직접 의존 **이름 집합**의 해시. 범위(버전 지정자)가 바뀌어도 변하지 않는다."""
    names = sorted({d.name for d in directs})
    return hashlib.sha256("\n".join(names).encode("utf-8")).hexdigest()


def targets_label() -> str:
    return " ".join(f"{Path(rel).parent.name}[{','.join(extras)}]" for rel, extras in CI_TARGETS)


# ── 제약 파일 읽기·쓰기 ────────────────────────────────────────────────────────


def parse_constraints(text: str) -> ConstraintsFile:
    header: dict[str, str] = {}
    pins: dict[str, str] = {}
    problems: list[str] = []
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            match = _HEADER_LINE.match(stripped)
            if match and match["key"] in HEADER_KEYS:
                header[match["key"]] = match["value"]
            continue
        match = _PIN_LINE.match(stripped)
        if match is None:
            problems.append(f"L{number}: `이름==버전` 형식이 아니다 — {stripped!r}")
            continue
        name = canonicalize_name(match["name"])
        try:
            Version(match["version"])
        except InvalidVersion:
            problems.append(f"L{number}: 버전을 해석하지 못했다 — {stripped!r}")
            continue
        if name in pins:
            problems.append(f"L{number}: 같은 패키지가 두 번 나온다 — {name}")
            continue
        pins[name] = match["version"]
    return ConstraintsFile(header, pins, tuple(problems))


def load_constraints(root: Path) -> ConstraintsFile:
    path = root / CONSTRAINTS_REL
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ScanError(f"{CONSTRAINTS_REL}: 제약 파일이 없다 — `refresh`로 만든다.") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise ScanError(f"{CONSTRAINTS_REL}: 읽지 못했다 ({type(exc).__name__})") from exc
    return parse_constraints(text)


def render_constraints(pins: dict[str, str], *, today: date, directs: Sequence[Direct]) -> str:
    lines = [
        "# CI 의존 해석 고정 파일 (OPS-121) — 직접 수정하지 않는다.",
        "# 갱신: python3.12 scripts/ops/ci_constraints.py refresh  (긴급: --only <패키지>)",
        "# 설명: docs/ops/ci_constraints_refresh_runbook.md",
        f"# generated: {today.isoformat()}",
        f"# python: {REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]}",
        "# platform: linux-x86_64",
        f"# targets: {targets_label()}",
        f"# direct: {direct_fingerprint(directs)}",
    ]
    lines += [f"{name}=={version}" for name, version in sorted(pins.items())]
    return "\n".join(lines) + "\n"


# ── check ──────────────────────────────────────────────────────────────────────


def _load_ops94(root: Path) -> Any:
    """OPS-94 검사기를 모듈로 읽는다 — 워크플로 인라인 직접 설치 패키지 목록을 재사용한다."""
    path = root / "scripts" / "ops" / "check_dependency_upper_bounds.py"
    if not path.is_file():
        raise ScanError(
            f"{path}: OPS-94 검사기가 없다 — 워크플로 인라인 설치 스캔을 재사용할 수 없다."
        )
    spec = importlib.util.spec_from_file_location("check_dependency_upper_bounds_for_ops121", path)
    if spec is None or spec.loader is None:
        raise ScanError(f"{path}: 모듈로 읽지 못했다")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclass가 문자열 주석을 풀 때 모듈 이름을 찾는다
    spec.loader.exec_module(module)
    return module


def _iter_workflows(root: Path) -> list[Path]:
    directory = root / ".github" / "workflows"
    paths = sorted(directory.glob("*.yml")) + sorted(directory.glob("*.yaml"))
    if not paths:
        raise ScanError(".github/workflows: 워크플로 파일이 하나도 없다 — 스캔 불가")
    return paths


def _env_mentions(env: Any) -> bool:
    return isinstance(env, dict) and ENV_NAME in env


def check_workflows(root: Path, report: Report) -> None:
    """계약 ② — `pip install`이 있는 모든 워크플로의 최상위 env 도달과 무력화 금지."""
    for path in _iter_workflows(root):
        rel = path.relative_to(root).as_posix()
        try:
            spec: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            raise ScanError(f"{rel}: YAML을 읽지 못했다 ({type(exc).__name__})") from exc
        jobs = spec.get("jobs") if isinstance(spec, dict) else None
        if not isinstance(jobs, dict):
            raise ScanError(f"{rel}: `jobs` 표가 없다 — 워크플로 형태가 아니다")
        report.workflows += 1
        installs: list[str] = []  # 이 파일의 pip install 스텝 위치
        for job_name, job in jobs.items():
            if not isinstance(job, dict):
                continue
            if _env_mentions(job.get("env")):
                report.violations.append(f"{rel} :: {job_name}: 잡 env가 {ENV_NAME}를 재정의한다")
            for number, step in enumerate(job.get("steps") or []):
                if not isinstance(step, dict):
                    continue
                label = f"{rel} :: {job_name} :: {step.get('name') or f'step[{number}]'}"
                if _env_mentions(step.get("env")):
                    report.violations.append(f"{label}: 스텝 env가 {ENV_NAME}를 재정의한다")
                script = step.get("run")
                if not isinstance(script, str):
                    continue
                if ENV_NAME in script:
                    report.violations.append(f"{label}: run 스크립트가 {ENV_NAME}를 건드린다")
                if _PIP_INSTALL.search(script):
                    installs.append(label)
                    if _PIP_ISOLATED.search(script):
                        report.violations.append(
                            f"{label}: `--isolated`는 PIP_* 환경변수를 무시한다 — 고정이 풀린다"
                        )
        if not installs:
            continue
        report.pip_steps += len(installs)
        top = spec.get("env")
        value = top.get(ENV_NAME) if isinstance(top, dict) else None
        if value != EXPECTED_ENV_VALUE:
            shown = "없음" if value is None else repr(value)
            report.violations.append(
                f"{rel}: pip install {len(installs)}곳이 있는데 "
                f"최상위 env {ENV_NAME}가 기대값이 아니다 "
                f"(실제 {shown}, 기대 {EXPECTED_ENV_VALUE!r}) — 이 파일의 설치는 고정되지 않는다"
            )
    if report.pip_steps == 0:
        raise ScanError("워크플로에서 pip install을 한 건도 인식하지 못했다 — 스캔이 깨졌다")


def check_pins(cf: ConstraintsFile, directs: Sequence[Direct], report: Report) -> None:
    """계약 ③ — 직접 의존 전부(pyproject + 워크플로 인라인 설치)에 핀이 있고 선언 범위 안이다."""
    for d in directs:
        pinned = cf.pins.get(d.name)
        if pinned is None:
            report.violations.append(f"핀 없음: {d.name} ({d.source}) — `refresh`가 필요하다")
        elif not d.requirement.specifier.contains(pinned, prereleases=True):
            report.violations.append(
                f"핀이 선언 범위 밖: {d.name}=={pinned} ∉ {d.requirement.specifier} ({d.source})"
            )


def check_header(cf: ConstraintsFile, directs: Sequence[Direct], report: Report) -> None:
    """계약 ①의 헤더 부분과 ④."""
    for problem in cf.problems:
        report.violations.append(f"형식: {problem}")
    missing = [key for key in HEADER_KEYS if key not in cf.header]
    for key in missing:
        report.violations.append(f"헤더 `{key}`가 없다")
    python = cf.header.get("python")
    if python is not None and python != f"{REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]}":
        report.violations.append(
            f"헤더 python={python!r} — CI는 {REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]}다"
        )
    platform = cf.header.get("platform")
    if platform is not None and not platform.startswith(REQUIRED_PLATFORM_PREFIX):
        report.violations.append(f"헤더 platform={platform!r} — CI는 linux다")
    direct = cf.header.get("direct")
    expected = direct_fingerprint(directs)
    if direct is not None and direct != expected:
        report.violations.append(
            "직접 의존 집합이 제약 파일 생성 시점과 다르다"
            "(의존을 추가·삭제했는데 `refresh`를 안 돌렸다) — "
            f"헤더 {direct[:12]}… ≠ 현재 {expected[:12]}…"
        )


def check_age(cf: ConstraintsFile, today: date, max_age_days: int, report: Report) -> None:
    """계약 ⑥ — 야간 센서 전용. 오래됐거나 미래 날짜인 `generated`는 위반."""
    raw = cf.header.get("generated")
    if raw is None:
        return  # 헤더 누락은 check_header가 이미 위반으로 센다
    try:
        generated = date.fromisoformat(raw)
    except ValueError:
        report.violations.append(f"헤더 generated={raw!r}를 날짜로 읽지 못했다")
        return
    age = (today - generated).days
    if age < 0:
        report.violations.append(
            f"generated={raw}가 오늘({today})보다 미래다 — 연령 검사를 우회하는 값이다"
        )
    elif age > max_age_days:
        report.violations.append(
            f"제약 파일이 {age}일 갱신되지 않았다(상한 {max_age_days}일, generated={raw}) — "
            "`refresh`로 갱신 PR을 낸다 (런북: docs/ops/ci_constraints_refresh_runbook.md)"
        )
    else:
        report.notes.append(f"연령 {age}일 (상한 {max_age_days}일)")


def run_check(root: Path, *, today: date, max_age_days: int | None) -> Report:
    report = Report()
    directs = collect_all(root)
    cf = load_constraints(root)
    report.pins = len(cf.pins)
    if report.pins == 0:
        raise ScanError(f"{CONSTRAINTS_REL}: 핀이 0건이다 — 빈 파일은 고정이 아니다")
    check_header(cf, directs, report)
    check_workflows(root, report)
    check_pins(cf, directs, report)
    if max_age_days is not None:
        check_age(cf, today, max_age_days, report)
    return report


# ── refresh ────────────────────────────────────────────────────────────────────


def _clean_env() -> dict[str, str]:
    """해석은 **고정 없이** 한다 — 셸에 남은 PIP_CONSTRAINT가 새 해석을 오염시키지 않게 비운다."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("PIP_CONSTRAINT")}
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["PIP_NO_INPUT"] = "1"
    return env


def resolve(requirements: Sequence[str], *, extra_constraints: Path | None) -> dict[str, str]:
    """pip 리졸버로 전이 포함 해석 결과를 얻는다 (설치하지 않는다: --dry-run)."""
    with tempfile.TemporaryDirectory(prefix="ci-constraints-") as tmp:
        req_file = Path(tmp) / "requirements.txt"
        report_file = Path(tmp) / "report.json"
        req_file.write_text("\n".join(requirements) + "\n", encoding="utf-8")
        command = [
            sys.executable, "-m", "pip", "install", "--dry-run", "--ignore-installed",
            "--quiet", "--report", str(report_file), "-r", str(req_file),
        ]  # fmt: skip
        if extra_constraints is not None:
            command += ["-c", str(extra_constraints)]
        try:
            result = subprocess.run(  # noqa: S603 — 인자는 전부 이 파일이 만든 리터럴
                command, env=_clean_env(), capture_output=True, text=True,
                encoding="utf-8", timeout=_PIP_TIMEOUT_SECONDS, check=False,
            )  # fmt: skip
        except subprocess.TimeoutExpired as exc:
            raise ScanError(
                f"pip 해석이 {_PIP_TIMEOUT_SECONDS}초를 넘겨 중단했다 (TimeoutExpired)"
            ) from exc
        if result.returncode != 0:
            tail = (result.stderr or result.stdout or "")[-2000:]
            raise ScanError(f"pip 해석 실패 (exit {result.returncode}) — 마지막 출력:\n{tail}")
        try:
            data = json.loads(report_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ScanError(f"pip report를 읽지 못했다 ({type(exc).__name__})") from exc
    pins: dict[str, str] = {}
    for item in data.get("install", []):
        meta = item.get("metadata", {})
        pins[canonicalize_name(meta["name"])] = meta["version"]
    if not pins:
        raise ScanError("pip 해석 결과가 0건이다 — report 형식이 바뀌었거나 해석이 비었다")
    return pins


def diff_pins(old: dict[str, str], new: dict[str, str]) -> list[str]:
    lines: list[str] = []
    for name in sorted(old.keys() | new.keys()):
        before, after = old.get(name), new.get(name)
        if before == after:
            continue
        if before is None:
            lines.append(f"+ {name}=={after}")
        elif after is None:
            lines.append(f"- {name}=={before}")
        else:
            lines.append(f"~ {name}: {before} → {after}")
    return lines


def run_refresh(root: Path, *, today: date, only: Sequence[str] | None) -> int:
    if sys.version_info[:2] != REQUIRED_PYTHON or not sys.platform.startswith("linux"):
        raise ScanError(
            f"refresh는 python {REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]} + linux에서만 돈다 "
            f"(지금 python {sys.version_info[0]}.{sys.version_info[1]} · {sys.platform}) — "
            "CI(ubuntu·3.12)와 같은 해석을 내려면 같은 환경이어야 한다. "
            "WSL 또는 CI 러너에서 실행한다."
        )
    directs = collect_all(root)
    requirements = sorted({str(d.requirement) for d in directs})
    path = root / CONSTRAINTS_REL
    old = parse_constraints(path.read_text(encoding="utf-8")).pins if path.is_file() else {}

    extra: Path | None = None
    keep_dir: tempfile.TemporaryDirectory[str] | None = None
    if only:
        if not old:
            raise ScanError("--only는 기존 제약 파일이 있어야 한다 — 먼저 전체 `refresh`를 돌린다.")
        targets = {canonicalize_name(n) for n in only}
        unknown = sorted(targets - old.keys())
        if unknown:
            raise ScanError(f"--only 대상이 제약 파일에 없다: {', '.join(unknown)}")
        keep_dir = tempfile.TemporaryDirectory(prefix="ci-constraints-keep-")
        extra = Path(keep_dir.name) / "keep.txt"
        extra.write_text(
            "\n".join(f"{n}=={v}" for n, v in sorted(old.items()) if n not in targets) + "\n",
            encoding="utf-8",
        )
    try:
        pins = resolve(requirements, extra_constraints=extra)
    finally:
        if keep_dir is not None:
            keep_dir.cleanup()

    # 로컬 프로젝트(editable)는 requirements에 넣지 않았으므로 pins에 섞이지 않는다.
    text = render_constraints(pins, today=today, directs=directs)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".txt.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    os.replace(tmp_path, path)

    changes = diff_pins(old, pins)
    print(f"제약 파일 갱신: {CONSTRAINTS_REL} — 핀 {len(pins)}건 (generated {today.isoformat()})")
    print(f"변경 {len(changes)}건" + (" (--only: 나머지 핀 고정)" if only else ""))
    for line in changes:
        print(f"  {line}")
    return 0


# ── CLI ────────────────────────────────────────────────────────────────────────


def _today() -> date:
    return datetime.now(UTC).date()


def _render_check(report: Report) -> None:
    print(
        f"스캔 — 워크플로 {report.workflows}개 · pip install 스텝 {report.pip_steps}곳 · "
        f"핀 {report.pins}건"
    )
    for note in report.notes:
        print(f"  ⓘ {note}")
    if report.failed:
        print(f"✘ 위반 {len(report.violations)}건:")
        for violation in report.violations:
            print(f"  · {violation}")
        print(
            "조치: 제약 파일 문제는 `python3.12 scripts/ops/ci_constraints.py refresh`, "
            "워크플로 문제는 최상위 env 복구."
        )
    else:
        print("✔ 위반 0건 — 모든 pip install이 제약 파일로 고정되고 핀이 선언과 정합한다")


def main(argv: Sequence[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    common.add_argument(
        "--today", type=date.fromisoformat, default=None, help="YYYY-MM-DD (테스트용)"
    )
    parser = argparse.ArgumentParser(
        description="CI 의존 해석 고정(제약 파일) 갱신·검증 (OPS-121)."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    refresh = sub.add_parser(
        "refresh", parents=[common], help="제약 파일을 새로 해석해 다시 쓴다 (python3.12 + linux)"
    )
    refresh.add_argument("--only", default=None, help="긴급 경로: 쉼표로 구분한 패키지만 올린다")
    check = sub.add_parser("check", parents=[common], help="정적 게이트 (네트워크 불요)")
    check.add_argument(
        "--max-age-days", type=int, default=None, help="야간 센서 전용 — PR 경로에서 쓰지 않는다"
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse 오류는 측정 실패(2)로 통일한다
        return int(exc.code) if isinstance(exc.code, int) else 2
    root: Path = args.root.resolve()
    today: date = args.today or _today()
    try:
        if args.command == "refresh":
            only = [n.strip() for n in args.only.split(",") if n.strip()] if args.only else None
            if args.only is not None and not only:
                raise ScanError("--only 값이 비었다")
            return run_refresh(root, today=today, only=only)
        report = run_check(root, today=today, max_age_days=args.max_age_days)
    except ScanError as exc:
        print(f"측정 실패: {exc}", file=sys.stderr)
        return 2
    _render_check(report)
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
