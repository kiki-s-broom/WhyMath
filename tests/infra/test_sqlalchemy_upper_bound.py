"""[OPS-92] SQLAlchemy 의존 **상한 동일성** 동결 — 선언 지점 전수에서 같은 상한을 요구한다.

왜 이 테스트가 필요한가
----------------------
2026-09-25 SQLAlchemy 2.1.0 배포로 `mypy --strict`가 34건(16파일) 실패해 main CI가 막혔다.
OPS-91(PR #1304)이 `src/backend`·`src/data-pipeline` 두 pyproject에 상한 `<2.1`을 걸어
풀었는데, 착지 후 저장소 전수 grep으로 **상한이 없는 선언 지점이 1곳 더** 나왔다 —
`ci.yml` `infra-contracts` 잡의 직설치 `"sqlalchemy>=2.0"`. 그 잡에서 `tests/infra`는
2.1.x 위에서, 백엔드는 2.0.x 위에서 도는 **검증 표면 불일치**가 남아 있었다.

한 곳을 핀하고 다른 곳을 잊는 일은 반대 방향으로도 난다 — 2.1 이행(OPS-93) 때 pyproject만
`<2.2`로 올리고 CI 직설치를 `<2.1`에 두면 이번엔 infra 잡만 옛 버전에 남는다. 그래서 이
테스트는 "상한이 있다"에서 멈추지 않고 **"전 지점의 상한이 같다"**를 요구한다. 올리거나
내릴 때 한 곳만 바꾸면 RED다.

스캔 범위 (명시 — 이 밖의 설치 경로는 보지 않는다)
------------------------------------------------
- 저장소의 모든 `pyproject.toml`: `project.dependencies`·`project.optional-dependencies`
  ·`dependency-groups`(PEP 735)
- `.github/workflows/*.yml`의 모든 `run` 스텝에서 `pip install`로 넘기는 인자

검증 계약
--------
① 선언 지점마다 상한 연산자(`<`·`<=`·`==`·`~=`·`===`)가 있다
② 전 지점의 상한 집합이 동일하다
③ **스캔 0건은 실패** — pyproject 지점이 2건 미만이면 파서·경로가 망가진 것이다
④ 파서가 위장하지 않는다 — `sqlalchemy`로 시작하는 토큰을 해석하지 못하거나, `pip
   install`이 아닌 명령에서 만나면 조용히 버리지 않고 실패한다(모르는 설치 형태를 "0건
   통과"로 흘리면 이 테스트가 막으려는 사고가 그대로 재발한다)
⑤ 결함 주입으로 ①~④의 변별력을 상시 봉인한다(아래 가짜 입력 테스트)

배선 메모: 이 파일이 도는 `infra-contracts` 잡은 백엔드를 설치하지 않는다. `packaging`은
pytest의 의존이라 그 잡에도 있다(2026-09-25 격리 venv 실측 — packaging 26.3). 셸 파서는
OPS-10 `test_test_suite_wiring.py`의 것을 재사용한다(복제하면 두 사본이 서로 어긋난다).
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

from .test_test_suite_wiring import _iter_pyprojects, _logical_lines, _rel, _simple_commands

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW_DIR = _REPO_ROOT / ".github" / "workflows"

_PACKAGE = "sqlalchemy"
# 위쪽을 막는 연산자 — 이 중 하나라도 있으면 "상한 있음"으로 친다
_UPPER_OPERATORS = frozenset({"<", "<=", "==", "~=", "==="})
_PIP_NAMES = frozenset({"pip", "pip3"})

# 현행 pyproject 선언 형태(OPS-91 핀) — 아래 가짜 입력의 기준값
_PINNED = "sqlalchemy[asyncio]>=2.0.35,<2.1"


@dataclass(frozen=True)
class Site:
    """sqlalchemy 의존이 선언된 한 지점."""

    origin: str
    requirement: Requirement


def _upper_bound(requirement: Requirement) -> frozenset[str]:
    """상한 연산자를 쓰는 지정자만 정규화된 문자열로 모은다."""
    return frozenset(
        str(spec) for spec in requirement.specifier if spec.operator in _UPPER_OPERATORS
    )


def _is_target(requirement: Requirement) -> bool:
    return canonicalize_name(requirement.name) == _PACKAGE


def _pyproject_sites(pyproject: Path, origin_prefix: str) -> list[Site]:
    """pyproject 한 파일에서 sqlalchemy 선언을 섹션별로 모은다."""
    data: dict[str, Any] = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = data.get("project") or {}
    sections: list[tuple[str, Iterable[Any]]] = [
        ("project.dependencies", project.get("dependencies") or [])
    ]
    for extra, deps in (project.get("optional-dependencies") or {}).items():
        sections.append((f"project.optional-dependencies.{extra}", deps))
    for group, deps in (data.get("dependency-groups") or {}).items():
        sections.append((f"dependency-groups.{group}", deps))

    sites: list[Site] = []
    for section, deps in sections:
        for raw in deps:
            # PEP 735 `{include-group = ...}` 같은 표 항목은 요구사항 문자열이 아니다
            if not isinstance(raw, str):
                continue
            try:
                requirement = Requirement(raw)
            except InvalidRequirement as exc:
                raise AssertionError(
                    f"{origin_prefix} :: {section}: 요구사항을 해석하지 못했다 ({exc}) — {raw!r}"
                ) from exc
            if _is_target(requirement):
                sites.append(Site(origin=f"{origin_prefix} :: {section}", requirement=requirement))
    return sites


def _install_arguments(command: list[str]) -> list[str] | None:
    """`pip install ...`(·`python -m pip install`·`uv pip install`)이면 install 뒤 토큰을 준다."""
    for index, token in enumerate(command[:-1]):
        if Path(token).name in _PIP_NAMES and command[index + 1] == "install":
            return command[index + 2 :]
    return None


def _script_sites(script: str, origin: str) -> list[Site]:
    """`run` 스크립트 하나에서 sqlalchemy 설치 인자를 모은다(계약 ④ — 모르는 형태는 실패)."""
    sites: list[Site] = []
    for line in _logical_lines(script):
        if _PACKAGE not in line.lower():
            continue
        for command in _simple_commands(line, origin, subject=_PACKAGE):
            candidates = [t for t in command if t.lower().startswith(_PACKAGE)]
            if not candidates:
                continue
            arguments = _install_arguments(command)
            if arguments is None:
                raise AssertionError(
                    f"{origin}: `pip install`이 아닌 명령에서 sqlalchemy 인자를 만났다 — "
                    f"인식 못 한 설치 형태일 수 있으므로 조용히 넘기지 않는다.\n  명령: {command}"
                )
            for token in arguments:
                if not token.lower().startswith(_PACKAGE):
                    continue
                try:
                    requirement = Requirement(token)
                except InvalidRequirement as exc:
                    raise AssertionError(
                        f"{origin}: sqlalchemy 설치 인자를 해석하지 못했다 ({exc}) — {token!r}"
                    ) from exc
                if _is_target(requirement):
                    sites.append(Site(origin=origin, requirement=requirement))
    return sites


def _workflow_sites(workflow_dir: Path, repo_root: Path) -> list[Site]:
    paths = sorted(workflow_dir.glob("*.yml")) + sorted(workflow_dir.glob("*.yaml"))
    if not paths:
        raise AssertionError(f"{workflow_dir}: 워크플로 파일이 하나도 없다 — 스캔 불가.")
    sites: list[Site] = []
    for path in paths:
        try:
            spec: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise AssertionError(f"{_rel(path, repo_root)}: YAML 파손 ({exc})") from exc
        for job_name, job in ((spec or {}).get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            for step in job.get("steps") or []:
                if isinstance(step, dict) and step.get("run"):
                    origin = f"{_rel(path, repo_root)} :: {job_name}"
                    sites.extend(_script_sites(str(step["run"]), origin))
    return sites


def _all_pyproject_sites(repo_root: Path) -> list[Site]:
    sites: list[Site] = []
    for pyproject in _iter_pyprojects(repo_root):
        sites.extend(_pyproject_sites(pyproject, _rel(pyproject, repo_root)))
    return sites


def _violations(sites: list[Site]) -> list[str]:
    """계약 ①② — 상한 누락 지점과 상한 불일치를 사람이 읽을 문장으로 돌려준다."""
    problems = [
        f"상한 없음: {site.origin} — {site.requirement}"
        for site in sites
        if not _upper_bound(site.requirement)
    ]
    bounds = {_upper_bound(site.requirement) for site in sites if _upper_bound(site.requirement)}
    if len(bounds) > 1:
        listing = "\n".join(f"    {site.origin} — {site.requirement}" for site in sites)
        problems.append(
            "상한 불일치: 지점마다 상한이 다르다 — 올리거나 내릴 때는 전 지점을 함께 바꾼다\n"
            + listing
        )
    return problems


# ── 계약 ①②③ : 실제 저장소 ─────────────────────────────────────────────────────


def test_every_sqlalchemy_declaration_has_the_same_upper_bound() -> None:
    pyproject_sites = _all_pyproject_sites(_REPO_ROOT)
    # 계약 ③ — backend·data-pipeline 두 pyproject가 각각 선언한다(2026-09-25 실측)
    assert len(pyproject_sites) >= 2, (
        f"pyproject에서 sqlalchemy 선언을 {len(pyproject_sites)}건만 찾았다 — 경로나 파서가 "
        "망가졌다. 스캔 0건을 '위반 0 통과'로 넘기지 않는다."
    )
    sites = pyproject_sites + _workflow_sites(_WORKFLOW_DIR, _REPO_ROOT)
    problems = _violations(sites)
    assert not problems, "\n".join(problems)


# ── 계약 ⑤ : 결함 주입으로 변별력 상시 봉인 ────────────────────────────────────


def _site(origin: str, text: str) -> Site:
    return Site(origin=origin, requirement=Requirement(text))


def test_control_same_bound_everywhere_passes() -> None:
    sites = [_site("a", _PINNED), _site("b", "sqlalchemy>=2.0,<2.1")]
    assert _violations(sites) == []


def test_defect_missing_upper_bound_is_detected() -> None:
    """OPS-92 착수 전 ci.yml 상태 그대로 — 상한 없는 직설치."""
    sites = [_site("pyproject", _PINNED), _site("ci", "sqlalchemy>=2.0")]
    problems = _violations(sites)
    assert any(p.startswith("상한 없음: ci") for p in problems), problems


def test_defect_one_site_raised_alone_is_detected() -> None:
    """2.1 이행(OPS-93) 때 pyproject만 올리고 CI 직설치를 잊은 상태."""
    sites = [_site("pyproject", "sqlalchemy>=2.0.35,<2.2"), _site("ci", "sqlalchemy>=2.0,<2.1")]
    problems = _violations(sites)
    assert any(p.startswith("상한 불일치") for p in problems), problems


def test_parser_finds_quoted_and_module_form_installs() -> None:
    script = (
        'pip install pytest pyyaml "sqlalchemy>=2.0,<2.1" \\\n'
        '            "ruff>=0.7.0,<0.16"\n'
        "python -m pip install -e . 'SQLAlchemy[asyncio]<2.1'\n"
        "uv pip install sqlalchemy==2.0.54\n"
    )
    sites = _script_sites(script, "fake.yml :: job")
    assert [str(s.requirement) for s in sites] == [
        "sqlalchemy<2.1,>=2.0",
        "SQLAlchemy[asyncio]<2.1",
        "sqlalchemy==2.0.54",
    ]


def test_parser_ignores_lines_without_sqlalchemy_arguments() -> None:
    script = 'pip install -e ".[dev]"\npython -c "import sqlalchemy"\n'
    assert _script_sites(script, "fake.yml :: job") == []


def test_parser_fails_loudly_on_unparseable_sqlalchemy_argument() -> None:
    with pytest.raises(AssertionError, match="해석하지 못했다"):
        _script_sites('pip install "sqlalchemy>=2.0,<"', "fake.yml :: job")


def test_parser_fails_loudly_on_unknown_install_form() -> None:
    with pytest.raises(AssertionError, match="인식 못 한 설치 형태"):
        _script_sites("poetry add sqlalchemy", "fake.yml :: job")


def test_pyproject_scan_covers_every_section(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        "[project]\n"
        'name = "fake"\n'
        f'dependencies = ["{_PINNED}", "pyyaml"]\n'
        "[project.optional-dependencies]\n"
        'db = ["sqlalchemy>=2.0"]\n'
        "[dependency-groups]\n"
        'dev = ["SQLAlchemy<2.1", {include-group = "db"}]\n',
        encoding="utf-8",
    )
    sites = _pyproject_sites(pyproject, "fake/pyproject.toml")
    assert [s.origin for s in sites] == [
        "fake/pyproject.toml :: project.dependencies",
        "fake/pyproject.toml :: project.optional-dependencies.db",
        "fake/pyproject.toml :: dependency-groups.dev",
    ]
    # optional extra의 상한 누락도 잡힌다
    assert any(p.startswith("상한 없음") for p in _violations(sites))


def test_missing_workflow_dir_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="워크플로 파일이 하나도 없다"):
        _workflow_sites(tmp_path / "nowhere", tmp_path)
