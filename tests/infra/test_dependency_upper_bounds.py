"""[OPS-94] 무상한 의존 pin 차단 게이트(`scripts/ops/check_dependency_upper_bounds.py`)의 동결.

왜 이 테스트가 필요한가
----------------------
검사기가 "통과"를 내는 것은 보호의 증거가 아니다 — *모든* 입력에서 통과하는 검사기도 같은 화면을
낸다. 그래서 이 파일은 ① 실제 저장소가 통과함을 확인하고(GREEN) ② 검사기가 막으려는 상태를
**실제로 주입해** RED가 나오는지를 상시 봉인한다. 인수 조건 ④의 4종 — 상한 제거 · `~=`→`>=`
치환 · 허용 목록 만료일 과거화 · 대상 경로 오타 — 은 각각 정상 대조군과 짝을 이룬다(대조군이
없으면 "전부 실패로 계상"하는 과잉 수정이 통과한다).

종료 코드 계약(0 통과 / 1 위반 / 2 측정 실패)이 핵심이다 — "대상 0건"과 "파싱 불가"는 위반이
아니라 **측정 실패**이고, 그것을 통과(0)나 위반(1)으로 섞으면 CI가 보는 신호가 흐려진다.

주입 자체의 실재
---------------
모든 주입은 `_swap`/`_replace`를 거쳐 *치환 대상이 실제로 있는지*를 단언한다. 주입이 조용히
실패하면 정상 입력에 대해 "통과"가 나오고, 그것이 "검출 실패"가 아니라 "검출"처럼 보인다.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import textwrap
from pathlib import Path
from types import ModuleType

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "ops" / "check_dependency_upper_bounds.py"
_CI_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_TODAY = "2026-10-02"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_dependency_upper_bounds", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclass가 문자열 주석을 풀 때 모듈 이름을 찾는다
    spec.loader.exec_module(module)
    return module


chk = _load()


# ── 픽스처 조립 ────────────────────────────────────────────────────────────────

_BACKEND_DEPS = ["pydantic>=2.9.0,<3", "pyyaml>=6.0.1,<7", "sqlalchemy[asyncio]>=2.0.35,<2.1"]
_BACKEND_EXTRAS = {"dev": ["pytest>=8.3.3,<10", "pytest-randomly>=3.15,<4"]}
_DATA_DEPS = ["pydantic>=2.9.0,<3", "pyyaml>=6.0.1,<7"]
_CONTROL_RUN = """
python -m pip install --upgrade "pip<27"
pip install -e ".[dev]"
pip install "pytest>=8.3.3,<10" "pytest-randomly>=3.15,<4" \\
            "pyyaml>=6.0.1,<7"
"""
_EMPTY_ALLOWLIST = "entries = []\n"
_LEGACY_ENTRY = """
[[entries]]
package = "legacy-lib"
reason = "공급사 메이저 이행 대기 — 12월 검증 뒤 해소"
expires = 2026-12-31
"""


def _toml_list(items: list[str]) -> str:
    return "[" + ", ".join(f'"{item}"' for item in items) + "]"


def _pyproject(
    deps: list[str],
    extras: dict[str, list[str]] | None = None,
    build: list[str] | None = None,
    name: str = "fake",
    extra_tables: str = "",
) -> str:
    lines = ["[project]", f'name = "{name}"', 'version = "0"', f"dependencies = {_toml_list(deps)}"]
    if extras:
        lines.append("[project.optional-dependencies]")
        lines.extend(f"{key} = {_toml_list(value)}" for key, value in extras.items())
    lines.append("[build-system]")
    lines.append(f"requires = {_toml_list(build or ['hatchling>=1.25.0,<2'])}")
    return "\n".join(lines) + "\n" + extra_tables


def _workflow(run: str) -> str:
    body = textwrap.indent(textwrap.dedent(run).strip("\n"), " " * 10)
    return (
        "name: ci\n"
        "on: push\n"
        "jobs:\n"
        "  job-a:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - name: Install\n"
        "        run: |\n"
        f"{body}\n"
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_root(
    tmp_path: Path,
    *,
    backend_deps: list[str] | None = None,
    backend_extras: dict[str, list[str]] | None = None,
    backend_build: list[str] | None = None,
    backend_text: str | None = None,
    data_deps: list[str] | None = None,
    run: str = _CONTROL_RUN,
    allowlist: str = _EMPTY_ALLOWLIST,
    owner: bool = True,
) -> Path:
    """통제 상태(전부 상한 있음)의 최소 저장소 — 인자로 한 군데씩만 어긋나게 만든다."""
    root = tmp_path / "repo"
    _write(
        root / "src/backend/pyproject.toml",
        (
            backend_text
            if backend_text is not None
            else _pyproject(
                _BACKEND_DEPS if backend_deps is None else backend_deps,
                _BACKEND_EXTRAS if backend_extras is None else backend_extras,
                backend_build,
                name="fake-backend",
            )
        ),
    )
    _write(
        root / "src/data-pipeline/pyproject.toml",
        _pyproject(_DATA_DEPS if data_deps is None else data_deps, name="fake-data"),
    )
    _write(root / ".github/workflows/ci.yml", _workflow(run))
    _write(root / chk.DEFAULT_ALLOWLIST, allowlist)
    if owner:
        # 위임된 일치 검사의 소유자 — sqlalchemy를 다루는 테스트 파일이 있어야 위임이 성립한다
        _write(root / chk.DELEGATED_EQUALITY["sqlalchemy"], "# sqlalchemy 상한 일치 검사\n")
    return root


def _swap(items: list[str], old: str, new: str) -> list[str]:
    """주입 자체의 실재 — 치환 대상이 목록에 실제로 있어야 한다."""
    assert old in items, f"주입 대상이 없다: {old!r} ∉ {items}"
    return [new if item == old else item for item in items]


def _replace(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, f"주입 앵커가 {text.count(old)}건이다: {old!r}"
    return text.replace(old, new)


def _run(capsys: pytest.CaptureFixture[str], root: Path, *extra: str) -> tuple[int, str]:
    code = chk.main(["--root", str(root), "--today", _TODAY, *extra])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


# ── 실제 저장소: 계약 ①②④ + 배선 ③ ─────────────────────────────────────────────


def test_real_repository_has_no_unbounded_dependency() -> None:
    from datetime import date

    today = date.today()  # 허용 목록 항목이 만료에 다가가면 이 테스트가 먼저 빨개진다(의도)
    entries = chk.load_allowlist(_REPO_ROOT / chk.DEFAULT_ALLOWLIST, today)
    scan = chk.scan_repository(_REPO_ROOT)
    judgement = chk.judge(scan, entries, today)
    assert not judgement.failed, "\n".join(chk.render(scan, judgement, [], today))
    assert chk.delegation_problems(_REPO_ROOT) == []


def test_real_repository_scan_covers_required_surfaces() -> None:
    """스캔이 줄어들면(경로 오타·파서 파손) 위반 0이 공허하게 통과한다."""
    scan = chk.scan_repository(_REPO_ROOT)
    assert set(chk.REQUIRED_PYPROJECTS) <= set(scan.pyprojects)
    assert any(name.endswith("ci.yml") for name in scan.workflows)
    assert len(scan.sites) >= 40, f"의존 선언을 {len(scan.sites)}건만 읽었다 — 파서가 줄었다"
    assert scan.pip_commands >= 5, f"pip install 명령 {scan.pip_commands}건 — 파서가 줄었다"
    packages = {site.package for site in scan.sites}
    # 어느 지점에서든 실제 의존이 읽혀야 한다 — 이름 몇 개로 표본 확인
    assert {"pydantic", "pytest", "pyyaml", "sqlalchemy", "pip"} <= packages


def test_cli_exits_zero_on_the_real_repository() -> None:
    result = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=_REPO_ROOT,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "판정: 통과" in result.stdout


def test_gate_is_wired_into_the_always_running_infra_contracts_job() -> None:
    """저장소에 있는 것과 도는 것은 다르다 — CI가 실제로 이 게이트를 부르는가."""
    workflow = yaml.safe_load(_CI_WORKFLOW.read_text(encoding="utf-8"))
    job = workflow["jobs"]["infra-contracts"]
    # 이 잡이 어떤 PR에서도 도는가 — needs/if 게이팅이 붙으면 "항상 도는 잡"이라는 배선 근거가 깨진다
    assert "needs" not in job and "if" not in job, "infra-contracts에 게이팅이 붙었다"
    gate_steps = [
        step
        for step in job["steps"]
        if "check_dependency_upper_bounds.py" in str(step.get("run", ""))
    ]
    assert len(gate_steps) == 1, f"게이트 스텝이 {len(gate_steps)}건이다(정확히 1건이어야 한다)"
    step = gate_steps[0]
    # 조건부 스텝·실패 허용 스텝은 조용히 건너뛰거나 삼킨다 — 게이트가 아니라 위장이다
    assert "if" not in step and not step.get("continue-on-error"), step


def test_install_step_provides_the_gate_dependencies() -> None:
    """검사기는 yaml·packaging을 import한다 — 같은 잡의 Install deps가 그것을 깔아야 한다."""
    workflow = yaml.safe_load(_CI_WORKFLOW.read_text(encoding="utf-8"))
    install = next(
        step
        for step in workflow["jobs"]["infra-contracts"]["steps"]
        if str(step.get("name", "")).startswith("Install deps")
    )
    run = str(install["run"])
    assert "pyyaml" in run, "검사기가 import하는 PyYAML이 이 잡에 설치되지 않는다"
    assert (
        "pytest" in run
    ), "packaging은 pytest의 의존이다 — pytest 설치가 사라지면 검사기가 못 돈다"


def test_delegated_equality_owner_still_owns_the_contract() -> None:
    """위임은 소유자가 실재할 때만 위임이다 — OPS-92 테스트가 사라지면 일치 검사가 허공이 된다."""
    owner = _REPO_ROOT / chk.DELEGATED_EQUALITY["sqlalchemy"]
    text = owner.read_text(encoding="utf-8")
    assert "def test_every_sqlalchemy_declaration_has_the_same_upper_bound" in text


# ── 대조군 + 인수 조건 ④의 4종 주입 ─────────────────────────────────────────────


def test_control_fully_bounded_repository_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, output = _run(capsys, _make_root(tmp_path))
    assert code == 0, output
    assert "판정: 통과" in output


def test_defect_removed_upper_bound_is_detected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """주입 ① — 상한 제거. pydantic에서 `<3`을 뺀다."""
    deps = _swap(_BACKEND_DEPS, "pydantic>=2.9.0,<3", "pydantic>=2.9.0")
    code, output = _run(capsys, _make_root(tmp_path, backend_deps=deps))
    assert code == 1, output
    assert "[상한 없음]" in output and "pydantic>=2.9.0" in output
    assert "src/backend/pyproject.toml :: project.dependencies" in output


def test_defect_compatible_release_downgraded_to_lower_bound_is_detected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """주입 ② — `~=`를 `>=`로 치환. 대조군(`~=`)은 통과해야 한다(`~=`도 상한이다)."""
    pinned = [*_BACKEND_DEPS, "httpx~=0.28"]
    code, output = _run(capsys, _make_root(tmp_path, backend_deps=pinned))
    assert code == 0, f"대조군: `~=`는 상한이다\n{output}"

    loosened = _swap(pinned, "httpx~=0.28", "httpx>=0.28")
    code, output = _run(capsys, _make_root(tmp_path / "mutated", backend_deps=loosened))
    assert code == 1, output
    assert "[상한 없음]" in output and "httpx>=0.28" in output


def test_defect_expired_allowlist_entry_is_detected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """주입 ③ — 허용 목록 만료일을 과거로. 대조군(만료 전)은 통과하고 [허용]이 보여야 한다."""
    deps = [*_BACKEND_DEPS, "legacy-lib>=1.0"]
    code, output = _run(capsys, _make_root(tmp_path, backend_deps=deps, allowlist=_LEGACY_ENTRY))
    assert code == 0, f"대조군: 만료 전 허용 항목은 통과해야 한다\n{output}"
    assert "[허용]" in output

    expired = _replace(_LEGACY_ENTRY, "2026-12-31", "2026-09-30")
    code, output = _run(
        capsys, _make_root(tmp_path / "mutated", backend_deps=deps, allowlist=expired)
    )
    assert code == 1, output
    assert "[허용 목록 만료]" in output
    # 만료된 항목은 면제 효력도 잃는다 — 그 지점이 다시 위반으로 보여야 한다
    assert "[상한 없음]" in output and "legacy-lib>=1.0" in output


def test_allowlist_expiry_day_itself_is_still_valid(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """경계 — 만료일 당일까지는 유효, 다음 날부터 위반(off-by-one 방지)."""
    deps = [*_BACKEND_DEPS, "legacy-lib>=1.0"]
    root = _make_root(tmp_path, backend_deps=deps, allowlist=_LEGACY_ENTRY)
    assert _run(capsys, root, "--today", "2026-12-31")[0] == 0
    assert _run(capsys, root, "--today", "2027-01-01")[0] == 1


@pytest.mark.parametrize(
    ("typo", "message"),
    [
        ("root", "pyproject.toml을 하나도 찾지 못했다"),
        ("backend_renamed", "필수 pyproject가 없다"),
        ("workflows_missing", "워크플로 파일이 하나도 없다"),
        ("allowlist", "허용 목록 파일이 없다"),
    ],
)
def test_defect_target_path_typo_is_a_measurement_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], typo: str, message: str
) -> None:
    """주입 ④ — 대상 경로 오타. 스캔 0건·일부 누락은 위반(1)도 통과(0)도 아닌 측정 실패(2)다."""
    root = _make_root(tmp_path)
    assert _run(capsys, root)[0] == 0, "대조군이 먼저 통과해야 한다"
    extra: tuple[str, ...] = ()
    if typo == "root":
        # 허용 목록은 원래 경로를 명시한다 — 안 그러면 루트 기준 경로가 먼저 없어서
        # 'pyproject를 못 찾음' 가드에 도달하지 못한다(가드마다 따로 밟는다)
        extra = ("--allowlist", str(root / chk.DEFAULT_ALLOWLIST))
        root = tmp_path / "no-such-repo"
    elif typo == "backend_renamed":
        (root / "src/backend/pyproject.toml").rename(root / "src/backend/pyproject.toml.bak")
    elif typo == "workflows_missing":
        (root / ".github/workflows/ci.yml").unlink()
    else:
        extra = ("--allowlist", str(root / "scripts/ops/dependency_upper_bound_allowlst.toml"))
    code, output = _run(capsys, root, *extra)
    assert code == 2, output
    assert "측정 실패" in output
    # 가드마다 고유 메시지 — 두 가드가 겹쳐 서로를 가리면 한쪽을 지워도 통과한다
    assert message in output, output


# ── 허용 목록 계약 ③ ───────────────────────────────────────────────────────────


def test_allowlist_entry_waives_exactly_what_it_names(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """면제는 이름 붙인 지점만 — 표기(대소문자·`_`)는 정규화되고, sites는 지점을 좁힌다."""
    deps = [*_BACKEND_DEPS, "Legacy_Lib>=1.0"]
    scoped = _replace(_LEGACY_ENTRY, 'package = "legacy-lib"', 'package = "LEGACY.lib"')
    code, output = _run(capsys, _make_root(tmp_path, backend_deps=deps, allowlist=scoped))
    assert code == 0, f"표기 변형(대소문자·`_`·`.`)은 같은 패키지다\n{output}"

    # sites로 좁히면 다른 지점은 면제되지 않는다 — data-pipeline 지점은 여전히 위반
    narrowed = _LEGACY_ENTRY + 'sites = ["src/backend/pyproject.toml"]\n'
    both = _make_root(
        tmp_path / "narrow",
        backend_deps=[*_BACKEND_DEPS, "legacy-lib>=1.0"],
        data_deps=[*_DATA_DEPS, "legacy-lib>=1.0"],
        allowlist=narrowed,
    )
    code, output = _run(capsys, both)
    assert code == 1, output
    assert "src/data-pipeline/pyproject.toml" in output and "[상한 없음]" in output


def test_stale_allowlist_entry_is_a_violation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """고쳤는데 항목을 안 지우면 목록이 거짓이 된다 — 어느 지점도 면제하지 못하는 항목은 위반."""
    # legacy-lib이 이미 상한을 갖는다 — 항목이 가리킬 무상한 지점이 없다
    deps = [*_BACKEND_DEPS, "legacy-lib>=1.0,<2"]
    code, output = _run(capsys, _make_root(tmp_path, backend_deps=deps, allowlist=_LEGACY_ENTRY))
    assert code == 1, output
    assert "[허위 허용]" in output and "legacy-lib" in output
    # 선언 자체가 사라진 경우도 같다
    code, output = _run(capsys, _make_root(tmp_path / "gone", allowlist=_LEGACY_ENTRY))
    assert code == 1 and "[허위 허용]" in output, output


_MALFORMED_ALLOWLISTS = {
    "reason 누락": lambda t: _replace(
        t, 'reason = "공급사 메이저 이행 대기 — 12월 검증 뒤 해소"\n', ""
    ),
    "expires 누락": lambda t: _replace(t, "expires = 2026-12-31\n", ""),
    "알 수 없는 키(오타)": lambda t: _replace(t, "expires =", "expire ="),
    "사유가 너무 짧다": lambda t: _replace(
        t, "공급사 메이저 이행 대기 — 12월 검증 뒤 해소", "임시"
    ),
    "만료일을 따옴표로 감쌌다": lambda t: _replace(
        t, "expires = 2026-12-31", 'expires = "2026-12-31"'
    ),
    "만료일이 datetime": lambda t: _replace(
        t, "expires = 2026-12-31", "expires = 2026-12-31T00:00:00Z"
    ),
    "만료일이 사실상 영구": lambda t: _replace(t, "2026-12-31", "2099-12-31"),
    "같은 항목 중복": lambda t: t + t,
    "최상위 키 오타": lambda t: _replace(t, "[[entries]]", "[[entires]]"),
    "알 수 없는 추가 키(필수 키는 다 있다)": lambda t: _replace(
        t, 'package = "legacy-lib"', 'package = "legacy-lib"\nowner = "kiki"'
    ),
    "알 수 없는 최상위 키(entries는 있다)": lambda t: 'owner = "kiki"\n' + t,
    "sites가 목록이 아님": lambda t: t + 'sites = "x"\n',
    "package가 공백": lambda t: _replace(t, 'package = "legacy-lib"', 'package = " "'),
    # 정수 항목 — 문자열이면 다음 가드(알 수 없는 키)가 우연히 같은 exit 2를 내 이 가드를 가린다
    "항목이 표가 아님": lambda _t: "entries = [1]\n",
    "TOML 문법 오류": lambda t: t + "package = = oops\n",
}


@pytest.mark.parametrize("label", sorted(_MALFORMED_ALLOWLISTS))
def test_malformed_allowlist_is_a_measurement_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], label: str
) -> None:
    """사유·만료일 없는 예외는 허용하지 않는다 — 오타로 만료가 사라지는 것도 막는다."""
    deps = [*_BACKEND_DEPS, "legacy-lib>=1.0"]
    broken = _MALFORMED_ALLOWLISTS[label](_LEGACY_ENTRY)
    assert broken != _LEGACY_ENTRY, "주입이 적용되지 않았다"
    code, output = _run(capsys, _make_root(tmp_path, backend_deps=deps, allowlist=broken))
    assert code == 2, f"{label}: {output}"
    assert "측정 실패" in output


def test_entries_must_be_a_list_even_when_empty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for text in ("", 'entries = "none"\n'):
        code, output = _run(capsys, _make_root(tmp_path / str(len(text)), allowlist=text))
        assert code == 2, f"{text!r}: {output}"


# ── 일치·위임 계약 ② ───────────────────────────────────────────────────────────


def test_defect_one_site_raised_alone_is_detected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """한 곳만 올리고 다른 곳을 잊은 상태 — 워크플로 직설치만 `<4`, pyproject는 `<3`."""
    run = _replace(_CONTROL_RUN, '"pytest-randomly>=3.15,<4"', '"pytest-randomly>=3.15,<5"')
    code, output = _run(capsys, _make_root(tmp_path, run=run))
    assert code == 1, output
    assert "[상한 불일치]" in output and "pytest-randomly" in output
    assert "상한 <5" in output and "상한 <4" in output


def test_equivalent_spellings_of_the_same_bound_are_equal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """과잉 수정 대조군 — `<3`과 `<3.0`은 같은 상한이다(PEP 440 정규화)."""
    run = _replace(_CONTROL_RUN, '"pyyaml>=6.0.1,<7"', '"pyyaml>=6.0.1,<7.0"')
    code, output = _run(capsys, _make_root(tmp_path, run=run))
    assert code == 0, output


def test_sqlalchemy_equality_is_delegated_but_presence_is_not(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """상한 일치는 OPS-92가 소유한다(여기서 중복 검사하지 않는다). 상한 *존재*는 여전히 본다."""
    differing = [*_BACKEND_DEPS[:2], "sqlalchemy>=2.0,<2.2"]  # backend `<2.2` vs data `<2.1`
    data = [*_DATA_DEPS, "sqlalchemy>=2.0,<2.1"]
    code, output = _run(capsys, _make_root(tmp_path, backend_deps=differing, data_deps=data))
    assert code == 0, f"일치 검사는 위임됐다 — 여기서 불일치로 잡으면 중복 검사다\n{output}"
    assert "[위임] sqlalchemy" in output

    unbounded = [*_BACKEND_DEPS[:2], "sqlalchemy>=2.0"]
    code, output = _run(capsys, _make_root(tmp_path / "unbounded", backend_deps=unbounded))
    assert code == 1 and "[상한 없음]" in output, output


def test_broken_delegation_is_a_violation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """허공을 가리키는 위임은 위장이다 — 소유자가 사라지면 위반."""
    code, output = _run(capsys, _make_root(tmp_path, owner=False))
    assert code == 1 and "[위임 파손]" in output, output


# ── 상한 연산자 판정 ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("spec", "bounded"),
    [
        ("<3", True),
        ("<=2.9", True),
        ("==2.9.1", True),
        ("==2.*", True),
        ("~=2.9", True),
        ("===2.9", True),
        (">=2.9", False),
        (">2", False),
        ("!=3.0", False),
        (">=2.9,!=2.9.1", False),
        (">=2.9,<3", True),
        ("", False),
    ],
)
def test_upper_bound_operators(spec: str, bounded: bool) -> None:
    site = chk._make_site(f"pkg{spec}", "fake")
    assert bool(site.upper) is bounded, f"pkg{spec}: 기대 {bounded}, 실제 {site.upper}"


def test_pep440_equivalent_bounds_compare_equal() -> None:
    assert chk._make_site("pkg<2", "a").upper == chk._make_site("pkg<2.0", "b").upper
    assert chk._make_site("pkg<2", "a").upper != chk._make_site("pkg<3", "b").upper
    assert chk._make_site("pkg<2", "a").upper != chk._make_site("pkg<=2", "b").upper


# ── pyproject 표면 ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("where", ["extra", "dependency-group", "build-system", "second-extra"])
def test_every_pyproject_section_is_scanned(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], where: str
) -> None:
    """상한 없는 선언이 어느 섹션에 숨어도 잡힌다 — 런타임만 보면 extra·build가 무방비가 된다."""
    extras = dict(_BACKEND_EXTRAS)
    build = ["hatchling>=1.25.0,<2"]
    tables = ""
    if where == "extra":
        extras["dev"] = [*extras["dev"], "sneaky-extra>=1.0"]
    elif where == "second-extra":
        extras["ocr"] = ["sneaky-ocr>=1.0"]
    elif where == "build-system":
        build = ["hatchling>=1.25.0"]
    else:
        tables = '[dependency-groups]\ndev = ["sneaky-group>=1.0", {include-group = "other"}]\n'
    text = _pyproject(_BACKEND_DEPS, extras, build, name="fake-backend", extra_tables=tables)
    code, output = _run(capsys, _make_root(tmp_path, backend_text=text))
    assert code == 1, f"{where}: {output}"
    assert "[상한 없음]" in output


def test_self_referencing_extra_alias_is_not_an_external_dependency(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`all = ["fake-backend[dev,ocr]"]` 같은 자기 별칭은 외부 의존이 아니다(과잉 수정 대조군)."""
    extras = {**_BACKEND_EXTRAS, "all": ["fake-backend[dev]", "Fake_Backend[ocr]"]}
    text = _pyproject(_BACKEND_DEPS, extras, name="fake-backend")
    code, output = _run(capsys, _make_root(tmp_path, backend_text=text))
    assert code == 0, output


_BROKEN_PYPROJECTS = {
    "해석 불가 요구사항": lambda: _pyproject(["pydantic>=2.9.0,<"]),
    "TOML 문법 오류": lambda: "[project\nname = oops\n",
    "dependencies가 목록이 아님": lambda: '[project]\nname = "x"\ndependencies = "pydantic<3"\n',
    "요구사항이 문자열이 아님": lambda: '[project]\nname = "x"\ndependencies = [1, 2]\n',
    "project.dependencies 안의 표": lambda: (
        '[project]\nname = "x"\ndependencies = [{include-group = "dev"}]\n'
    ),
}


@pytest.mark.parametrize("label", sorted(_BROKEN_PYPROJECTS))
def test_unreadable_pyproject_is_a_measurement_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], label: str
) -> None:
    root = _make_root(tmp_path, backend_text=_BROKEN_PYPROJECTS[label]())
    code, output = _run(capsys, root)
    assert code == 2, f"{label}: {output}"
    assert "측정 실패" in output


def test_empty_dependency_surface_is_a_measurement_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """스캔 0건은 통과가 아니다 — 의존 선언이 하나도 읽히지 않으면 파서가 깨진 것이다."""
    root = _make_root(
        tmp_path,
        backend_text='[project]\nname = "x"\n',
        data_deps=[],
    )
    (root / "src/data-pipeline/pyproject.toml").write_text(
        '[project]\nname = "y"\n', encoding="utf-8"
    )
    code, output = _run(capsys, root)
    assert code == 2 and "의존 선언을 한 건도" in output, output


# ── 워크플로 `pip install` 파싱 ────────────────────────────────────────────────

# `{pkg}` 자리에 요구사항을 끼우는 설치 형태 — 같은 형태로 ① 상한 있는 패키지는 통과(오탐 없음)
# ② 상한 없는 패키지는 정확히 1건 검출(조용히 무시하지 않음)을 함께 본다. 오탐 검사만 있으면
# 파서가 그 줄을 통째로 무시해도 통과한다 — 검출 검사가 그 사각을 닫는다.
_PACKAGE_FORMS = {
    "기본": "pip install {pkg}",
    "pip3 + 값 없는 옵션": "pip3 install --upgrade --no-cache-dir {pkg}",
    "python -m pip": "python -m pip install {pkg}",
    "python3 -m pip": "python3 -m pip install {pkg}",
    "절대 경로 pip": "/usr/bin/pip install {pkg}",
    "uv pip": "uv pip install {pkg}",
    "--index-url 값 삼킴": "pip install --index-url https://example.invalid/simple {pkg}",
    "--opt=value 형태": "pip install --index-url=https://example.invalid/simple {pkg}",
    "출력 리다이렉션": "pip install {pkg} > /dev/null 2>&1",
    "stderr 리다이렉션": "pip install {pkg} 2>&1",
    "짧은 값 없는 옵션": "pip install -U -q --user {pkg}",
    "&& 연결": "cd src/backend && pip install {pkg} && python -m pytest",
    "공백 없는 &&": "cd src/backend&&pip install {pkg}",
    "공백 없는 ;": "true;pip install {pkg}",
    "줄 끝 주석": "pip install {pkg}  # 예전엔 pip install foo 였다",
    "editable 뒤 패키지": 'pip install -e ".[dev]" {pkg}',
    "백슬래시 이음": "pip install \\\n    {pkg}",
}
_NO_PACKAGE_FORMS = {
    "로컬 editable + extras": 'pip install -e ".[dev]"',
    "로컬 상대 경로": "python -m pip install -e ../data-pipeline",
    "--editable=경로": "pip install --editable=../data-pipeline",
    "로컬 휠 파일": "pip install ./wheels/local.whl",
    "pip 단어가 없는 줄": 'git add -A && git commit -m "add the thing"',
}
_BOUNDED = '"pyyaml>=6.0.1,<7"'


@pytest.mark.parametrize("label", sorted(_PACKAGE_FORMS))
def test_package_install_forms_yield_no_false_violation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], label: str
) -> None:
    run = _CONTROL_RUN + _PACKAGE_FORMS[label].format(pkg=_BOUNDED) + "\n"
    code, output = _run(capsys, _make_root(tmp_path, run=run))
    assert code == 0, f"{label}: 오탐이다\n{output}"


@pytest.mark.parametrize("label", sorted(_PACKAGE_FORMS))
def test_package_install_forms_detect_an_unbounded_package(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], label: str
) -> None:
    """같은 형태에서 상한 없는 패키지는 정확히 1건 검출돼야 한다 — 형태를 못 읽고 넘기면 안 된다."""
    run = _CONTROL_RUN + _PACKAGE_FORMS[label].format(pkg="ruff") + "\n"
    code, output = _run(capsys, _make_root(tmp_path, run=run))
    assert code == 1, f"{label}: 검출하지 못했다\n{output}"
    flagged = [line for line in output.splitlines() if "[상한 없음]" in line]
    assert len(flagged) == 1 and flagged[0].endswith("— ruff"), f"{label}: {flagged}"


@pytest.mark.parametrize("label", sorted(_NO_PACKAGE_FORMS))
def test_forms_without_a_package_yield_no_false_violation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], label: str
) -> None:
    run = _CONTROL_RUN + _NO_PACKAGE_FORMS[label] + "\n"
    code, output = _run(capsys, _make_root(tmp_path, run=run))
    assert code == 0, f"{label}: 오탐이다\n{output}"


def test_unrelated_shell_lines_are_not_tokenized(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """설치 도구 이름이 없는 줄은 토큰화하지 않는다 — 따옴표가 어긋난 무관한 줄이 CI를 멈추면 안 된다."""
    run = _CONTROL_RUN + "echo \"it's an unbalanced line, nothing to add here\n"
    code, output = _run(capsys, _make_root(tmp_path, run=run))
    assert code == 0, output


def test_unbounded_package_after_a_backslash_ending_comment_is_still_found(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """주석 줄이 `\\`로 끝나도 다음 줄을 삼키지 않는다 — 삼키면 그 줄의 무상한 설치가 사라진다."""
    run = _CONTROL_RUN + '# 설명 줄이 백슬래시로 끝난다 \\\npip install "ruff"\n'
    code, output = _run(capsys, _make_root(tmp_path, run=run))
    assert code == 1, output
    assert "[상한 없음]" in output and "— ruff" in output


def test_bare_package_in_workflow_install_is_detected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """OPS-94 착수 시점의 실제 모양 — `pip install pytest pytest-randomly` 직설치."""
    run = _replace(_CONTROL_RUN, '"pytest-randomly>=3.15,<4"', "pytest-randomly")
    code, output = _run(capsys, _make_root(tmp_path, run=run))
    assert code == 1, output
    assert "[상한 없음]" in output and "pytest-randomly" in output
    assert "ci.yml :: job-a :: Install" in output


_UNRECOGNIZED_INSTALL_FORMS = {
    "requirements 파일": ("pip install -r requirements.txt", "파일 설치는 판정하지 않는다"),
    "constraints 파일": (
        'pip install -c constraints.txt "pyyaml>=6.0.1,<7"',
        "파일 설치는 판정하지 않는다",
    ),
    "해석 못 한 옵션": ('pip install --frobnicate "pyyaml>=6.0.1,<7"', "해석하지 못한 pip 옵션"),
    "-- 구분자": ('pip install -- "pyyaml>=6.0.1,<7"', "해석하지 못한 pip 옵션"),
    "git+ 직접 설치": ("pip install git+https://example.invalid/x.git", "직접 URL 설치"),
    "URL 직접 설치": (
        "pip install https://example.invalid/x-1.0-py3-none-any.whl",
        "직접 URL 설치",
    ),
    "VCS editable": (
        "pip install -e git+https://example.invalid/x.git#egg=x",
        "직접 URL·VCS editable",
    ),
    "editable 대상 누락": ("pip install -e", "뒤에 대상이 없다"),
    "--editable=VCS": (
        "pip install --editable=git+https://example.invalid/x.git",
        "직접 URL·VCS editable",
    ),
    "해석 불가 요구사항": ('pip install "pyyaml>=6.0.1,<"', "요구사항을 해석하지 못했다"),
    "따옴표 불균형": ('pip install "pyyaml>=6.0.1,<7', "토큰화하지 못했다"),
    "미확장 변수": ('pip install "$EXTRA_PACKAGE"', "요구사항을 해석하지 못했다"),
    "pipx": ("pipx install black", "인식 못 한 설치 명령"),
    "poetry add": ("poetry add requests", "인식 못 한 설치 명령"),
    "uv add": ("uv add requests", "인식 못 한 설치 명령"),
    "uv tool install": ("uv tool install ruff", "인식 못 한 설치 명령"),
    "conda install": ("conda install numpy", "인식 못 한 설치 명령"),
    "mamba install": ("mamba install numpy", "인식 못 한 설치 명령"),
    "easy_install": ("python -m easy_install requests", "인식 못 한 설치 명령"),
}


@pytest.mark.parametrize("label", sorted(_UNRECOGNIZED_INSTALL_FORMS))
def test_unrecognized_install_forms_are_measurement_failures(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], label: str
) -> None:
    """모르는 설치 형태를 '0건 통과'로 흘리면 이 검사기가 막으려는 사고가 그대로 재발한다."""
    command, message = _UNRECOGNIZED_INSTALL_FORMS[label]
    code, output = _run(capsys, _make_root(tmp_path, run=_CONTROL_RUN + command + "\n"))
    assert code == 2, f"{label}: 위반(1)이나 통과(0)로 흘렀다\n{output}"
    assert "측정 실패" in output
    # 가드마다 고유 메시지 — 한 가드가 빠져도 다른 가드가 같은 exit 2를 내므로 메시지로 구분한다
    assert message in output, f"{label}: 기대한 가드가 아니다\n{output}"


def test_no_pip_install_command_anywhere_is_a_measurement_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, output = _run(capsys, _make_root(tmp_path, run="echo hello\n"))
    assert code == 2 and "pip install` 명령을 한 건도" in output, output


def test_broken_workflow_yaml_is_a_measurement_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _make_root(tmp_path)
    (root / ".github/workflows/ci.yml").write_text("jobs: [unclosed\n", encoding="utf-8")
    code, output = _run(capsys, root)
    assert code == 2, output
    (root / ".github/workflows/ci.yml").write_text("name: no-jobs\n", encoding="utf-8")
    code, output = _run(capsys, root)
    assert code == 2 and "`jobs` 표가 없다" in output, output


# ── 출력·CLI ──────────────────────────────────────────────────────────────────


def test_waived_site_stays_visible_with_days_left(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """면제된 지점도 로그에 남는다 — 눈에 안 보이는 예외는 만료가 와도 아무도 모른다."""
    deps = [*_BACKEND_DEPS, "legacy-lib>=1.0"]
    code, output = _run(capsys, _make_root(tmp_path, backend_deps=deps, allowlist=_LEGACY_ENTRY))
    assert code == 0, output
    assert "[허용]" in output and "만료 2026-12-31" in output and "D-90" in output


def test_cli_exit_codes_via_subprocess(tmp_path: Path) -> None:
    """종료 코드는 CI가 읽는 유일한 신호다 — 프로세스 경계에서 0/1/2를 확인한다."""

    def run(root: Path) -> int:
        return subprocess.run(
            [sys.executable, str(_SCRIPT), "--root", str(root), "--today", _TODAY],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        ).returncode

    assert run(_make_root(tmp_path / "ok")) == 0
    deps = _swap(_BACKEND_DEPS, "pydantic>=2.9.0,<3", "pydantic>=2.9.0")
    assert run(_make_root(tmp_path / "unbounded", backend_deps=deps)) == 1
    assert run(tmp_path / "no-such-repo") == 2


def test_bad_today_argument_is_an_argument_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = chk.main(["--root", str(_make_root(tmp_path)), "--today", "2026/10/02"])
    assert code == 2
    assert "--today" in capsys.readouterr().err


def test_yaml_extension_workflows_are_scanned(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`.yaml` 확장자 워크플로도 같은 규칙을 받는다 — `*.yml`만 보면 확장자 하나로 우회된다."""
    root = _make_root(tmp_path)
    _write(root / ".github/workflows/extra.yaml", _workflow("pip install ruff\n"))
    code, output = _run(capsys, root)
    assert code == 1 and "extra.yaml" in output, output


def test_unnamed_step_gets_a_positional_label(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """이름 없는 스텝도 위치(`step[N]`)로 지목된다 — `None`이 찍히면 어디를 고칠지 알 수 없다."""
    root = _make_root(tmp_path)
    unnamed = _replace(
        _workflow(_CONTROL_RUN + "pip install ruff\n"),
        "      - name: Install\n        run: |\n",
        "      - run: |\n",
    )
    _write(root / ".github/workflows/ci.yml", unnamed)
    code, output = _run(capsys, root)
    assert code == 1 and "job-a :: step[0]" in output and "None" not in output, output


def test_delegation_owner_that_no_longer_covers_the_package_is_a_violation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """소유자 파일이 있어도 그 패키지를 더 안 다루면 위임은 허공을 가리킨다."""
    root = _make_root(tmp_path)
    (root / chk.DELEGATED_EQUALITY["sqlalchemy"]).write_text("# 다른 내용\n", encoding="utf-8")
    code, output = _run(capsys, root)
    assert code == 1 and "더 이상 다루지 않는다" in output, output
