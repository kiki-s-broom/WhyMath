"""OPS-54 — policy-guard의 EBS·평가원 본문 인용 패턴 + #codeowner-ack 우회의 변별력.

**왜 문자열 중복이 아니라 ci.yml에서 직접 읽는가**: 패턴을 이 테스트 파일에 다시 타이핑하면
ci.yml이 바뀌어도 테스트는 옛 패턴을 계속 통과시킨다(두 사본이 갈라지는 순간 이 테스트는
아무것도 지키지 않는다). PyYAML로 `run:` 블록 원문을 그대로 읽어 **실제 CI가 실행하는 스크립트
그 자체**를 서브프로세스로 돌린다 — CLAUDE.md "검사 명령의 출력을 억제하거나 잘라서 판정 금지 ·
CI가 실제로 쓰는 명령을 그대로 재현한다"와 같은 원칙.

**왜 EBS·평가원은 출판사명 단순 동시등장이 아니라 공식 인용 표기 형식인가**: 기존 검정교과서
패턴(`천재교육.*본문` 등)은 출판사명이 이 저장소에 거의 등장하지 않아 성립하지만, "EBS"·"평가원"·
"수능"은 이 저장소 **자신의 저작권 준수 docstring**(예: `schema/problem.py`의 "평가원·EBS·
검정교과서는 본문·문항 미보유")에 극도로 흔하다. 낱말 단순 동시등장 후보 2종을 저장소 전수
실측했더니 각각 292건·21건 오탐이 났다(정책 산문 자체가 매칭 대상이 됨) — 그래서 정책 산문에는
나타나지 않는 **실제 인용의 공식 표기**(평가원: 연도+학년도+시험명 · EBS: 대표 교재명+쪽수)만
잡는다. 아래 `test_ebs_kice_patterns_zero_false_positives_on_real_repo`가 그 전수 실측을 고정한다.

**자기발견 결함(구현 중 실측)**: `# codeowner-ack 주석으로 우회` 문구는 기존 검정교과서 스텝에
2026-05-28부터 주석으로만 있었고 grep이 그 마커를 실제로 걸러내지 않았다 — 매칭 라인에 마커를
붙여도 여전히 적색이었다(실측). "우회 규약"이 존재하지 않는 기능이었던 것 — 이 태스크가
`| grep -v '#codeowner-ack'`로 실제 배선하며 두 스텝(검정교과서·EBS/평가원) 모두 고쳤다.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"

_STEP_NAMES = {
    "textbook": "Forbid 검정교과서 본문 patterns",
    "ebs_kice": "Forbid EBS·평가원 본문 patterns",
}


def _load_policy_guard_steps() -> dict[str, str]:
    """ci.yml의 policy-guard 잡에서 `run:` 원문을 이름별로 뽑는다."""
    with open(CI_YML, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    steps = data["jobs"]["policy-guard"]["steps"]
    by_name = {s["name"]: s["run"] for s in steps if "run" in s}
    result = {}
    for key, name in _STEP_NAMES.items():
        assert name in by_name, f"ci.yml policy-guard에 '{name}' 스텝이 없다 — 이름이 바뀌었나?"
        result[key] = by_name[name]
    return result


@pytest.fixture(scope="module")
def steps() -> dict[str, str]:
    return _load_policy_guard_steps()


def _run_step(script: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", script],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


class TestZeroFalsePositivesOnRealRepo:
    """실제 저장소 전수 스캔 — 두 스텝 다 0건이어야 CI가 초록이다."""

    def test_textbook_patterns_pass_on_real_repo(self, steps):
        result = _run_step(steps["textbook"], REPO_ROOT)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_ebs_kice_patterns_zero_false_positives_on_real_repo(self, steps):
        """EBS·평가원 패턴이 이 저장소 자신의 저작권 준수 산문에 오탐하지 않는다.

        낱말 단순 동시등장 후보 2종(`EBS.*본문|평가원.*본문` 계열 · `수능.*본문` 계열)은
        각각 실측 292건·21건 오탐이 나서 폐기했다 — 이 테스트가 그 실패를 재발 방지한다.
        """
        result = _run_step(steps["ebs_kice"], REPO_ROOT)
        assert result.returncode == 0, result.stdout + result.stderr


class TestViolationInjectionTurnsRed:
    """위반 픽스처 주입 시 실제 적색 1회 실증 (acceptance ③)."""

    def test_ebs_page_citation_is_caught(self, tmp_path):
        (tmp_path / "leak.py").write_text(
            "# fixture: EBS 수능특강 12페이지 발췌\n", encoding="utf-8"
        )
        steps = _load_policy_guard_steps()
        result = _run_step(steps["ebs_kice"], tmp_path)
        assert result.returncode == 1, "실제 EBS 교재+쪽수 인용 형식을 통과시키면 안 된다"
        assert "EBS·평가원" in result.stdout

    def test_kice_year_citation_is_caught(self, tmp_path):
        (tmp_path / "leak.py").write_text(
            "# fixture: 2024학년도 대학수학능력시험 발췌\n", encoding="utf-8"
        )
        steps = _load_policy_guard_steps()
        result = _run_step(steps["ebs_kice"], tmp_path)
        assert result.returncode == 1, "실제 평가원 연도+시험명 인용 형식을 통과시키면 안 된다"

    def test_mock_exam_year_citation_is_caught(self, tmp_path):
        (tmp_path / "leak.py").write_text(
            "# fixture: 2025학년도 9월 모의평가 발췌\n", encoding="utf-8"
        )
        steps = _load_policy_guard_steps()
        result = _run_step(steps["ebs_kice"], tmp_path)
        assert result.returncode == 1

    def test_textbook_pattern_still_caught_after_bypass_retrofit(self, tmp_path):
        """기존 검정교과서 패턴이 우회 배선 이후에도 여전히 진짜 위반을 잡는다(회귀 방지)."""
        (tmp_path / "leak.py").write_text(
            "# fixture: 천재교육 교과서 본문 발췌\n", encoding="utf-8"
        )
        steps = _load_policy_guard_steps()
        result = _run_step(steps["textbook"], tmp_path)
        assert result.returncode == 1

    def test_unrelated_content_stays_green(self, tmp_path):
        """변별력 — 아무 위반도 없으면 두 스텝 다 통과해야 한다(전부 빨간불이면 검증이 아니다)."""
        (tmp_path / "clean.py").write_text(
            "# 이 파일은 평가원·EBS 본문을 보유하지 않는다(정책 준수 docstring)\n",
            encoding="utf-8",
        )
        steps = _load_policy_guard_steps()
        assert _run_step(steps["ebs_kice"], tmp_path).returncode == 0
        assert _run_step(steps["textbook"], tmp_path).returncode == 0


class TestCodeownerAckBypass:
    """`#codeowner-ack` 마커가 실제로 우회시키는지 — 이전에는 주석만 있고 배선이 없었다."""

    def test_ebs_violation_with_marker_is_bypassed(self, tmp_path):
        (tmp_path / "leak.py").write_text(
            "# fixture: EBS 수능특강 12페이지 발췌 # codeowner-ack\n", encoding="utf-8"
        )
        steps = _load_policy_guard_steps()
        result = _run_step(steps["ebs_kice"], tmp_path)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_kice_violation_with_marker_is_bypassed(self, tmp_path):
        (tmp_path / "leak.py").write_text(
            "# fixture: 2024학년도 대학수학능력시험 발췌 # codeowner-ack\n", encoding="utf-8"
        )
        steps = _load_policy_guard_steps()
        result = _run_step(steps["ebs_kice"], tmp_path)
        assert result.returncode == 0

    def test_textbook_violation_with_marker_is_bypassed(self, tmp_path):
        (tmp_path / "leak.py").write_text(
            "# fixture: 천재교육 교과서 본문 발췌 # codeowner-ack\n", encoding="utf-8"
        )
        steps = _load_policy_guard_steps()
        result = _run_step(steps["textbook"], tmp_path)
        assert result.returncode == 0

    def test_marker_does_not_bypass_a_violation_on_a_different_line(self, tmp_path):
        """마커는 그 *줄*만 면제한다 — 같은 파일의 다른 위반 줄까지 통째로 덮으면 안 된다."""
        (tmp_path / "leak.py").write_text(
            "# fixture: EBS 수능특강 12페이지 발췌 # codeowner-ack\n"
            "# fixture: 2024학년도 대학수학능력시험 발췌\n",
            encoding="utf-8",
        )
        steps = _load_policy_guard_steps()
        result = _run_step(steps["ebs_kice"], tmp_path)
        assert result.returncode == 1, "마커 없는 둘째 줄까지 함께 면제되면 우회가 아니라 무력화다"
        assert "2024학년도" in result.stdout
        assert "12페이지" not in result.stdout


class TestPolicyGuardStepsWiredInCi:
    """이 테스트 파일이 읽는 스텝 이름이 실제로 ci.yml policy-guard 잡에 존재한다(배선 실재성)."""

    def test_step_names_exist_in_policy_guard_job(self):
        with open(CI_YML, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        job = data["jobs"]["policy-guard"]
        names = {s["name"] for s in job["steps"] if "run" in s}
        for expected in _STEP_NAMES.values():
            assert expected in names

    def test_ebs_kice_step_comes_after_textbook_step_in_same_job(self):
        """신규 잡이 아니라 기존 잡 확장인지(acceptance ①) — 같은 잡·인접 스텝인지 확인."""
        with open(CI_YML, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        names = [s["name"] for s in data["jobs"]["policy-guard"]["steps"] if "run" in s]
        assert _STEP_NAMES["textbook"] in names
        assert _STEP_NAMES["ebs_kice"] in names
        assert names.index(_STEP_NAMES["ebs_kice"]) == names.index(_STEP_NAMES["textbook"]) + 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
