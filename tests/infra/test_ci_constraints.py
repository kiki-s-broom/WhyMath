"""[OPS-121] CI 의존 해석 고정 도구(`scripts/ops/ci_constraints.py`)의 동결.

왜 이 테스트가 필요한가
----------------------
2026-10-08 `pydantic 2.14.0`이 올라온 지 약 20분 만에 머지 큐 3건이 `mypy --strict`에서 같은 줄로
실패했다. 해법은 제약 파일(`infra/ci/constraints-py312.txt`)로 CI의 의존 해석을 고정하고, 워크플로
최상위 `env: PIP_CONSTRAINT` 한 줄로 모든 `pip install`을 그 파일에 묶는 것이다. 그런데 **게이트가
"통과"를 내는 것은 보호의 증거가 아니다** — *모든* 입력에서 통과하는 게이트도 같은 화면을 낸다.
그래서 이 파일은 ① 실제 저장소가 통과함을 확인하고(GREEN) ② 게이트가 막으려는 상태를 **실제로
주입해** RED가 나오는지를 상시 봉인한다. 주입마다 정상 대조군이 짝을 이룬다(대조군이 없으면
"전부 위반으로 계상"하는 과잉 수정이 통과한다).

세 가지 규율
-----------
1. **주입 자체의 실재** — 모든 주입은 `assert mutated != original`을 거친다. 주입이 조용히 실패하면
   정상 입력에 대해 "통과"가 나오고, 그것이 "검출 실패"가 아니라 "검출"처럼 보인다.
2. **실제 저장소를 건드리지 않는다** — 주입은 전부 `tmp_path`의 사본에서 한다. 원복이 필요 없으니
   `git checkout`·`restore`로 원복하다 미커밋 작업을 날릴 일이 없다.
3. **종료 코드 계약(0 통과 / 1 위반 / 2 측정 실패)** — "대상 0건"·"파싱 불가"는 위반이 아니라 측정
   실패다. 섞으면 CI가 보는 신호가 흐려진다.

연령 검사(`--max-age-days`)가 PR 경로에 없음을 별도로 동결한다: 날짜는 시계에 따라 결과가 바뀌는
입력이라, 넣으면 "머지 큐의 입력은 코드뿐이다"라는 이 고정의 목적이 깨진다.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "ops" / "ci_constraints.py"
_WORKFLOWS = _REPO_ROOT / ".github" / "workflows"
_TODAY = date(2026, 10, 9)

# 사본에 가져갈 저장소 파일 — 게이트가 읽는 전부(워크플로·pyproject·OPS-94 검사기·제약 파일).
_COPY_FILES = (
    "src/backend/pyproject.toml",
    "src/data-pipeline/pyproject.toml",
    "scripts/ops/check_dependency_upper_bounds.py",
    "infra/ci/constraints-py312.txt",
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ci_constraints_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclass가 문자열 주석을 풀 때 모듈 이름을 찾는다
    spec.loader.exec_module(module)
    return module


cc = _load()


# ── 사본 조립·주입 도구 ────────────────────────────────────────────────────────


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """게이트가 읽는 파일만 담은 저장소 사본. 주입은 여기에서만 한다."""
    for rel in _COPY_FILES:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_REPO_ROOT / rel, target)
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    for source in sorted(_WORKFLOWS.glob("*.yml")):
        shutil.copyfile(source, workflows / source.name)
    return tmp_path


def _check(root: Path, *, max_age_days: int | None = None, today: date = _TODAY) -> Any:
    return cc.run_check(root, today=today, max_age_days=max_age_days)


def _violations(root: Path, **kwargs: Any) -> list[str]:
    return list(_check(root, **kwargs).violations)


def _edit_text(path: Path, edit: Callable[[str], str]) -> None:
    before = path.read_text(encoding="utf-8")
    after = edit(before)
    assert after != before, f"주입이 적용되지 않았다: {path.name}"  # 주입 자체의 실재
    path.write_text(after, encoding="utf-8")


def _edit_workflow(root: Path, name: str, edit: Callable[[dict[Any, Any]], None]) -> None:
    path = root / ".github" / "workflows" / name
    before = yaml.safe_load(path.read_text(encoding="utf-8"))
    after = yaml.safe_load(path.read_text(encoding="utf-8"))
    edit(after)
    assert after != before, f"워크플로 주입이 적용되지 않았다: {name}"
    path.write_text(yaml.safe_dump(after, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _pip_step(job: dict[Any, Any]) -> dict[Any, Any]:
    for step in job["steps"]:
        if isinstance(step.get("run"), str) and "pip install" in step["run"]:
            return step  # type: ignore[no-any-return]
    raise AssertionError("pip install 스텝이 없는 잡")


def _has(violations: list[str], needle: str) -> bool:
    return any(needle in v for v in violations)


# ── 실제 저장소: GREEN ─────────────────────────────────────────────────────────


class TestRealRepository:
    def test_real_repository_passes_every_contract(self) -> None:
        report = _check(_REPO_ROOT)
        assert report.violations == []
        # 스캔 0건은 통과가 아니다 — 실제로 무언가를 봤는지 함께 단언한다.
        assert report.pins > 100
        assert report.pip_steps >= 19
        assert report.workflows >= 5

    def test_cli_exit_zero_on_real_repository(self) -> None:
        result = subprocess.run(
            [sys.executable, str(_SCRIPT), "check", "--today", "2026-10-09"],
            capture_output=True, text=True, encoding="utf-8", check=False,
        )  # fmt: skip
        assert result.returncode == 0, result.stdout + result.stderr

    def test_control_copy_is_green(self, tree: Path) -> None:
        """대조군: 주입 전의 사본이 GREEN이어야 이후 RED가 주입 때문임을 말할 수 있다."""
        assert _violations(tree) == []

    def test_constraints_file_is_not_a_declaration_site_for_ops94(self) -> None:
        """OPS-94 스캔 대상이 아니다 — 핀(`==`)이 선언 지점으로 오인되지 않는다."""
        ops94 = cc._load_ops94(_REPO_ROOT)
        scan = ops94.scan_repository(_REPO_ROOT)
        assert scan.sites, "OPS-94 스캔이 0건이면 이 단언은 공허하다"
        assert not any(cc.CONSTRAINTS_REL in site.origin for site in scan.sites)
        assert not any(site.origin.startswith("infra/") for site in scan.sites)

    def test_pins_cover_the_incident_packages(self) -> None:
        cf = cc.load_constraints(_REPO_ROOT)
        for name in ("pydantic", "pydantic-core", "mypy", "sqlalchemy", "pip", "hatchling"):
            assert name in cf.pins, f"사고 계열 패키지 {name}에 핀이 없다"


# ── 집행 도달: 워크플로 주입 ───────────────────────────────────────────────────


class TestEnforcementReach:
    def test_every_pip_workflow_has_the_top_level_env(self) -> None:
        """실제 5개 워크플로 전부 — 일부가 옛 방식이면 RED여야 한다."""
        seen = 0
        for path in sorted(_WORKFLOWS.glob("*.yml")):
            text = path.read_text(encoding="utf-8")
            if not re.search(r"\bpip3?\s+install\b", text):
                continue
            seen += 1
            spec = yaml.safe_load(text)
            assert spec["env"][cc.ENV_NAME] == cc.EXPECTED_ENV_VALUE, path.name
        assert seen >= 5

    def test_removing_top_level_env_is_red(self, tree: Path) -> None:
        _edit_workflow(tree, "ci.yml", lambda d: d.pop("env"))
        violations = _violations(tree)
        assert _has(violations, "ci.yml") and _has(violations, "고정되지 않는다")

    def test_one_workflow_left_on_the_old_way_is_red(self, tree: Path) -> None:
        """ci.yml만 고치고 weekly-metrics.yml을 놓친 상태 — 완료 조건 ②의 바로 그 상태."""
        _edit_workflow(tree, "weekly-metrics.yml", lambda d: d.pop("env"))
        violations = _violations(tree)
        assert any("weekly-metrics.yml" in v and "고정되지 않는다" in v for v in violations)
        assert not any("ci.yml" in v for v in violations)  # 대조: 다른 파일은 그대로 GREEN

    def test_wrong_env_value_is_red(self, tree: Path) -> None:
        _edit_workflow(
            tree, "ci.yml", lambda d: d["env"].update({cc.ENV_NAME: "/tmp/nowhere/constraints.txt"})
        )
        assert _has(_violations(tree), "기대값이 아니다")

    def test_job_level_env_override_is_red(self, tree: Path) -> None:
        _edit_workflow(
            tree,
            "ci.yml",
            lambda d: d["jobs"]["backend"].setdefault("env", {}).update({cc.ENV_NAME: ""}),
        )
        assert _has(_violations(tree), "잡 env가")

    def test_step_level_env_override_is_red(self, tree: Path) -> None:
        def edit(d: dict[Any, Any]) -> None:
            _pip_step(d["jobs"]["backend"]).setdefault("env", {})[cc.ENV_NAME] = ""

        _edit_workflow(tree, "ci.yml", edit)
        assert _has(_violations(tree), "스텝 env가")

    @pytest.mark.parametrize(
        "snippet",
        [
            "export PIP_CONSTRAINT=",
            "unset PIP_CONSTRAINT",
            "PIP_CONSTRAINT=/dev/null python -m pip install x",
        ],
    )
    def test_run_script_touching_the_variable_is_red(self, tree: Path, snippet: str) -> None:
        def edit(d: dict[Any, Any]) -> None:
            step = _pip_step(d["jobs"]["backend"])
            step["run"] = snippet + "\n" + step["run"]

        _edit_workflow(tree, "ci.yml", edit)
        assert _has(_violations(tree), "건드린다")

    def test_isolated_flag_is_red(self, tree: Path) -> None:
        """`pip --isolated`는 PIP_* 환경변수를 무시한다 — 환경변수 집행의 유일한 우회로."""

        def edit(d: dict[Any, Any]) -> None:
            step = _pip_step(d["jobs"]["backend"])
            step["run"] = step["run"].replace("pip install", "pip --isolated install", 1)

        _edit_workflow(tree, "ci.yml", edit)
        assert _has(_violations(tree), "--isolated")

    def test_new_workflow_with_pip_install_and_no_env_is_red(self, tree: Path) -> None:
        extra = tree / ".github" / "workflows" / "newcomer.yml"
        extra.write_text(
            "name: n\non: push\njobs:\n  j:\n    runs-on: ubuntu-latest\n    steps:\n"
            '      - run: python -m pip install "pyyaml>=6.0.1,<7"\n',
            encoding="utf-8",
        )
        assert _has(_violations(tree), "newcomer.yml")

    def test_new_workflow_without_pip_is_not_flagged(self, tree: Path) -> None:
        """과잉 수정 대조군: pip를 안 쓰는 워크플로에 env를 요구하면 안 된다."""
        extra = tree / ".github" / "workflows" / "docs-only.yml"
        extra.write_text(
            "name: d\non: push\njobs:\n  j:\n    runs-on: ubuntu-latest\n    steps:\n"
            "      - run: echo hello\n",
            encoding="utf-8",
        )
        assert _violations(tree) == []


# ── 핀 완전성·형식·지문 ────────────────────────────────────────────────────────


def _pins_path(root: Path) -> Path:
    return root / cc.CONSTRAINTS_REL


class TestPinCompleteness:
    def test_missing_pin_is_red(self, tree: Path) -> None:
        _edit_text(_pins_path(tree), lambda t: re.sub(r"^pydantic==.*\n", "", t, flags=re.M))
        assert _has(_violations(tree), "핀 없음: pydantic")

    def test_pin_outside_declared_range_is_red(self, tree: Path) -> None:
        _edit_text(
            _pins_path(tree), lambda t: re.sub(r"^pydantic==\S+", "pydantic==3.0.0", t, flags=re.M)
        )
        assert _has(_violations(tree), "핀이 선언 범위 밖: pydantic==3.0.0")

    def test_the_incident_shape_is_red(self, tree: Path) -> None:
        """사고 형태: 상한 `<2.14`로 선언을 좁혔는데 핀이 2.14.0에 남은 상태."""

        def narrow(text: str) -> str:
            return text.replace('"pydantic>=2.9.0,<3"', '"pydantic>=2.9.0,<2.14"')

        _edit_text(tree / "src/backend/pyproject.toml", narrow)
        _edit_text(tree / "src/data-pipeline/pyproject.toml", narrow)
        assert _has(_violations(tree), "핀이 선언 범위 밖: pydantic==2.14.0")

    def test_unpinned_form_is_red(self, tree: Path) -> None:
        _edit_text(
            _pins_path(tree), lambda t: re.sub(r"^pydantic==\S+", "pydantic>=2.9", t, flags=re.M)
        )
        violations = _violations(tree)
        assert _has(violations, "형식") and _has(violations, "핀 없음: pydantic")

    def test_duplicate_pin_is_red(self, tree: Path) -> None:
        _edit_text(_pins_path(tree), lambda t: t + "pydantic==2.13.5\n")
        assert _has(_violations(tree), "두 번 나온다")

    def test_workflow_inline_install_without_pin_is_red(self, tree: Path) -> None:
        def edit(d: dict[Any, Any]) -> None:
            step = _pip_step(d["jobs"]["infra-contracts"])
            step["run"] += '\npython3 -m pip install "left-pad-py>=1,<2"\n'

        _edit_workflow(tree, "ci.yml", edit)
        assert _has(_violations(tree), "핀 없음: left-pad-py")

    def test_pip_bootstrap_is_pinned_so_the_installer_does_not_float(self, tree: Path) -> None:
        _edit_text(_pins_path(tree), lambda t: re.sub(r"^pip==.*\n", "", t, flags=re.M))
        assert _has(_violations(tree), "핀 없음: pip")

    def test_adding_a_direct_dependency_without_refresh_is_red(self, tree: Path) -> None:
        _edit_text(
            tree / "src/backend/pyproject.toml",
            lambda t: t.replace(
                '"pyyaml>=6.0.1,<7",', '"pyyaml>=6.0.1,<7",\n    "left-pad-py>=1,<2",', 1
            ),
        )
        violations = _violations(tree)
        assert _has(violations, "핀 없음: left-pad-py") and _has(violations, "직접 의존 집합")

    def test_removing_a_direct_dependency_without_refresh_is_red(self, tree: Path) -> None:
        """지문 단독 검출: 핀은 그대로 남아 있어 `핀 없음`은 안 나오고 집합 불일치만 난다.

        sympy는 backend에만 선언돼 있어(data-pipeline에는 없다) 빼면 이름 집합이 실제로 줄어든다.
        """
        _edit_text(
            tree / "src/backend/pyproject.toml",
            lambda t: t.replace('    "sympy>=1.13.3,<2",\n', "", 1),
        )
        violations = _violations(tree)
        assert _has(violations, "직접 의존 집합")
        assert not _has(violations, "핀 없음")

    def test_removing_a_dependency_still_declared_elsewhere_does_not_force_refresh(
        self, tree: Path
    ) -> None:
        """과잉 수정 대조군: pdfplumber는 data-pipeline에도 있어 이름 집합이 변하지 않는다."""
        _edit_text(
            tree / "src/backend/pyproject.toml",
            lambda t: t.replace('    "pdfplumber>=0.11.4,<1",\n', "", 1),
        )
        assert _violations(tree) == []

    def test_widening_a_range_does_not_require_refresh(self, tree: Path) -> None:
        """과잉 수정 대조군: 범위만 넓히면(이름 집합 불변·핀은 범위 안) 갱신을 강제하지 않는다."""
        for rel in ("src/backend/pyproject.toml", "src/data-pipeline/pyproject.toml"):
            _edit_text(
                tree / rel, lambda t: t.replace('"pydantic>=2.9.0,<3"', '"pydantic>=2.8.0,<3"')
            )
        assert _violations(tree) == []


class TestHeader:
    @pytest.mark.parametrize("key", ["generated", "python", "platform", "targets", "direct"])
    def test_missing_header_key_is_red(self, tree: Path, key: str) -> None:
        _edit_text(_pins_path(tree), lambda t: re.sub(rf"^# {key}:.*\n", "", t, flags=re.M))
        assert _has(_violations(tree), f"헤더 `{key}`가 없다")

    def test_python_311_header_is_red(self, tree: Path) -> None:
        _edit_text(_pins_path(tree), lambda t: t.replace("# python: 3.12", "# python: 3.11"))
        assert _has(_violations(tree), "CI는 3.12")

    def test_windows_platform_header_is_red(self, tree: Path) -> None:
        _edit_text(
            _pins_path(tree),
            lambda t: t.replace("# platform: linux-x86_64", "# platform: win-amd64"),
        )
        assert _has(_violations(tree), "CI는 linux")


# ── 연령(야간 센서 전용) ───────────────────────────────────────────────────────


class TestAgeSensor:
    def _set_generated(self, root: Path, value: str) -> None:
        _edit_text(
            _pins_path(root),
            lambda t: re.sub(r"^# generated:.*$", f"# generated: {value}", t, flags=re.M),
        )

    def test_fresh_file_passes_with_age_check(self, tree: Path) -> None:
        self._set_generated(tree, "2026-09-29")  # 10일
        assert _violations(tree, max_age_days=30) == []

    def test_boundary_30_days_passes_31_fails(self, tree: Path) -> None:
        self._set_generated(tree, "2026-09-09")  # 정확히 30일
        assert _violations(tree, max_age_days=30) == []
        self._set_generated(tree, "2026-09-08")  # 31일
        assert _has(_violations(tree, max_age_days=30), "31일 갱신되지 않았다")

    def test_future_date_cannot_evade_the_age_check(self, tree: Path) -> None:
        self._set_generated(tree, "2099-12-31")
        assert _has(_violations(tree, max_age_days=30), "미래다")

    def test_unreadable_date_is_red(self, tree: Path) -> None:
        self._set_generated(tree, "어제")
        assert _has(_violations(tree, max_age_days=30), "날짜로 읽지 못했다")

    def test_age_is_not_part_of_the_default_check(self, tree: Path) -> None:
        """연령 없는 기본 검사는 시계와 무관하다 — 같은 트리가 몇 년 뒤에도 같은 결과여야 한다."""
        assert _violations(tree, today=date(2030, 1, 1)) == []

    def test_pr_path_step_has_no_age_flag_and_nightly_sensor_does(self) -> None:
        spec = yaml.safe_load((_WORKFLOWS / "ci.yml").read_text(encoding="utf-8"))
        gate_runs = [
            step["run"]
            for step in spec["jobs"]["infra-contracts"]["steps"]
            if "ci_constraints.py" in str(step.get("run", ""))
        ]
        assert gate_runs, "infra-contracts에 제약 게이트 스텝이 배선되지 않았다"
        assert all("--max-age-days" not in run for run in gate_runs), "연령을 PR 경로에 넣었다"
        sensor = spec["jobs"]["constraints-freshness"]
        assert sensor["if"] == "github.event_name == 'schedule'"
        assert any("--max-age-days" in str(s.get("run", "")) for s in sensor["steps"])


# ── 측정 실패(2) ───────────────────────────────────────────────────────────────


class TestMeasurementFailure:
    def test_missing_constraints_file_is_exit_2(self, tree: Path) -> None:
        _pins_path(tree).unlink()
        with pytest.raises(cc.ScanError, match="제약 파일이 없다"):
            _check(tree)

    def test_empty_constraints_file_is_exit_2(self, tree: Path) -> None:
        _pins_path(tree).write_text("# generated: 2026-10-09\n", encoding="utf-8")
        with pytest.raises(cc.ScanError, match="핀이 0건"):
            _check(tree)

    def test_no_workflows_is_exit_2(self, tree: Path) -> None:
        shutil.rmtree(tree / ".github" / "workflows")
        (tree / ".github" / "workflows").mkdir()
        with pytest.raises(cc.ScanError):
            _check(tree)

    def test_workflows_without_any_pip_install_is_exit_2(self, tree: Path) -> None:
        """스캔 0건은 통과가 아니다 — 파서가 깨져 pip install을 하나도 못 봐도 GREEN이 되면 안 된다."""
        for path in (tree / ".github" / "workflows").glob("*.yml"):
            path.unlink()
        (tree / ".github" / "workflows" / "x.yml").write_text(
            "name: x\non: push\njobs:\n  j:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n",
            encoding="utf-8",
        )
        with pytest.raises(cc.ScanError):
            _check(tree)

    def test_missing_pyproject_is_exit_2(self, tree: Path) -> None:
        (tree / "src/data-pipeline/pyproject.toml").unlink()
        with pytest.raises(cc.ScanError, match="필수 pyproject가 없다"):
            _check(tree)

    def test_unknown_extra_is_exit_2(self, tree: Path) -> None:
        _edit_text(
            tree / "src/data-pipeline/pyproject.toml",
            lambda t: t.replace("neo4j = [", "neo4jx = [", 1),
        )
        with pytest.raises(cc.ScanError, match="extra 'neo4j'"):
            _check(tree)

    def test_broken_workflow_yaml_is_exit_2(self, tree: Path) -> None:
        (tree / ".github" / "workflows" / "ci.yml").write_text(
            "jobs: [unclosed\n", encoding="utf-8"
        )
        with pytest.raises(cc.ScanError, match="YAML"):
            _check(tree)

    def test_cli_exit_codes_zero_one_two(self, tree: Path) -> None:
        def run(root: Path) -> int:
            return subprocess.run(
                [sys.executable, str(_SCRIPT), "check", "--root", str(root), "--today", "2026-10-09"],
                capture_output=True, text=True, encoding="utf-8", check=False,
            ).returncode  # fmt: skip

        assert run(tree) == 0
        _edit_workflow(tree, "ci.yml", lambda d: d.pop("env"))
        assert run(tree) == 1
        _pins_path(tree).unlink()
        assert run(tree) == 2


# ── refresh ────────────────────────────────────────────────────────────────────


class TestRefresh:
    def test_refuses_foreign_interpreter(self, tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cc, "REQUIRED_PYTHON", (2, 7))
        with pytest.raises(cc.ScanError, match="python 2.7 \\+ linux에서만"):
            cc.run_refresh(tree, today=_TODAY, only=None)

    @pytest.mark.skipif(not sys.platform.startswith("linux"), reason="refresh는 linux 전용")
    def test_refresh_writes_sorted_pins_and_a_matching_fingerprint(
        self, tree: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(cc, "REQUIRED_PYTHON", sys.version_info[:2])
        old = cc.load_constraints(tree).pins
        fake = dict(old)
        fake["pydantic"] = "2.15.0"
        monkeypatch.setattr(cc, "resolve", lambda reqs, extra_constraints: fake)
        assert cc.run_refresh(tree, today=_TODAY, only=None) == 0
        written = cc.load_constraints(tree)
        assert written.pins["pydantic"] == "2.15.0"
        names = list(written.pins)
        assert names == sorted(names)
        assert written.header["direct"] == cc.direct_fingerprint(cc.collect_all(tree))

    @pytest.mark.skipif(not sys.platform.startswith("linux"), reason="refresh는 linux 전용")
    def test_only_mode_keeps_every_other_pin_fixed(
        self, tree: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(cc, "REQUIRED_PYTHON", sys.version_info[:2])
        old = cc.load_constraints(tree).pins
        captured: dict[str, str] = {}

        def fake_resolve(requirements: Any, extra_constraints: Path | None) -> dict[str, str]:
            assert extra_constraints is not None, "--only는 나머지 핀을 제약으로 넘겨야 한다"
            for line in extra_constraints.read_text(encoding="utf-8").splitlines():
                name, _, version = line.partition("==")
                captured[name] = version
            return {**old, "pydantic": "2.15.0"}

        monkeypatch.setattr(cc, "resolve", fake_resolve)
        assert cc.run_refresh(tree, today=_TODAY, only=["Pydantic"]) == 0  # 대소문자 정규화
        assert "pydantic" not in captured, "대상 패키지가 고정되면 올릴 수 없다"
        assert captured["mypy"] == old["mypy"] and captured["sqlalchemy"] == old["sqlalchemy"]
        assert len(captured) == len(old) - 1

    @pytest.mark.skipif(not sys.platform.startswith("linux"), reason="refresh는 linux 전용")
    def test_only_with_unknown_package_is_refused(
        self, tree: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(cc, "REQUIRED_PYTHON", sys.version_info[:2])
        with pytest.raises(cc.ScanError, match="제약 파일에 없다: no-such-pkg"):
            cc.run_refresh(tree, today=_TODAY, only=["no-such-pkg"])

    def test_resolution_environment_drops_a_stale_constraint_variable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """호출 셸에 남은 PIP_CONSTRAINT가 새 해석을 옛 핀으로 오염시키면 `refresh`는 무의미하다."""
        monkeypatch.setenv("PIP_CONSTRAINT", "/stale/constraints.txt")
        assert "PIP_CONSTRAINT" not in cc._clean_env()
        monkeypatch.delenv("PIP_CONSTRAINT")
        assert "PIP_CONSTRAINT" not in cc._clean_env()  # 대조: 없을 때도 같다

    def test_diff_pins_reports_added_removed_and_changed(self) -> None:
        lines = cc.diff_pins({"a": "1", "b": "1", "c": "1"}, {"a": "1", "b": "2", "d": "1"})
        assert lines == ["~ b: 1 → 2", "- c==1", "+ d==1"]


class TestParse:
    def test_parse_accepts_comments_and_blank_lines(self) -> None:
        cf = cc.parse_constraints("# generated: 2026-10-09\n\nPyYAML==6.0.3\nfoo_bar==1.0\n")
        assert cf.pins == {"pyyaml": "6.0.3", "foo-bar": "1.0"}
        assert cf.problems == ()

    @pytest.mark.parametrize(
        "line",
        [
            "pydantic>=2",
            "pydantic[email]==2.0",
            "pydantic==2.0; python_version>'3'",
            "git+https://x/y",
            "==1",
        ],
    )
    def test_parse_rejects_non_pin_forms(self, line: str) -> None:
        assert cc.parse_constraints(line + "\n").problems, line

    def test_parse_rejects_invalid_version(self) -> None:
        assert cc.parse_constraints("pydantic==not.a.version!\n").problems
