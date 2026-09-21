"""CI 잡 커버리지 열거·대조 도구의 계약 동결 — HARN-109.

이 파일이 지키는 것은 도구의 출력 형식이 아니라 **판정의 변별력**이다:
  · 잡을 하나 빼고 돌리면 그 이름을 지목하는가 (acceptance ④)
  · path filter 정본이 바뀌면 판정도 따라 바뀌는가 (acceptance ②·뮤테이션)
  · 모르는 것을 "안 닿음"으로 접지 않는가 (3값 논리)
  · 재현 불가 잡을 "돌렸다"로 계상하지 않는가 (acceptance ⑥)

정상 입력에서 초록인 것은 보호의 증거가 아니므로, 각 절마다 **그 절이 없으면 통과하는
입력**을 픽스처로 둔다(CLAUDE.md 2026-09-07 픽스처 접촉 규칙).
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TOOL_PATH = _REPO_ROOT / "scripts" / "harness" / "ci_job_coverage.py"
_CI_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _load_tool():
    """도구를 모듈로 임포트한다(scripts/는 패키지가 아니므로 경로 로드)."""
    spec = importlib.util.spec_from_file_location("ci_job_coverage", _TOOL_PATH)
    assert spec and spec.loader, f"도구 로드 실패: {_TOOL_PATH}"
    module = importlib.util.module_from_spec(spec)
    sys.modules["ci_job_coverage"] = module
    spec.loader.exec_module(module)
    return module


tool = _load_tool()


@pytest.fixture(scope="module")
def workflow() -> dict:
    return tool.load_workflow(_CI_PATH)


# ── ① 잡 전수 열거 · 스캔 0건은 실패 ──────────────────────────────────────
class TestEnumeration:
    def test_enumerates_every_job_in_ci_yml(self, workflow):
        jobs = tool.enumerate_jobs(workflow)
        raw = yaml.safe_load(_CI_PATH.read_text(encoding="utf-8"))
        assert set(jobs) == set(raw["jobs"]), "열거가 ci.yml의 잡 집합과 다르다"
        assert len(jobs) >= 10, f"잡 {len(jobs)}건 — ci.yml 규모에 비해 비정상적으로 적다"

    def test_empty_scan_is_failure_not_pass(self):
        """스캔 0건은 통과가 아니라 실패다(CLAUDE.md 2026-09-01 축 ④)."""
        with pytest.raises(tool.ScanEmptyError):
            tool.enumerate_jobs({"jobs": {}})
        with pytest.raises(tool.ScanEmptyError):
            tool.enumerate_jobs({})

    def test_missing_workflow_file_raises(self, tmp_path):
        with pytest.raises(tool.ScanEmptyError):
            tool.load_workflow(tmp_path / "does-not-exist.yml")


# ── ② path filter를 정본으로 읽는다 ───────────────────────────────────────
class TestFilterIsReadFromSource:
    def test_flag_patterns_parsed_from_changes_job(self, workflow):
        patterns = tool.parse_flag_patterns(workflow)
        assert patterns, "path filter 정본을 하나도 읽지 못했다"
        # 잡 if가 참조하는 플래그는 전부 정본에 정의돼 있어야 한다.
        for name, job in tool.enumerate_jobs(workflow).items():
            for flag in tool.referenced_flags(job.get("if")):
                assert flag in patterns, f"{name}이 참조하는 플래그 '{flag}'의 정의를 못 찾았다"

    def test_backend_source_change_triggers_docker_build(self, workflow):
        """4회차 실례(PR #1216) 회귀 — 'Dockerfile 미변경'은 docker-build 면제 근거가 아니다.

        docker 필터는 src/backend/를 명시적으로 포함한다(이미지가 그 소스를 굽기 때문).
        이 절이 없으면 세션이 지어낸 근거가 다시 통과한다.
        """
        scopes = tool.classify_jobs(workflow, ["src/backend/whymath_backend/l3/router.py"])
        by_name = {s.name: s for s in scopes}
        assert (
            by_name["docker-build"].status == tool.TRIGGERED
        ), "src/backend 변경인데 docker-build를 '안 닿음'으로 판정했다 — 4회차 사고 재생산"
        assert "docker-build" in tool.jobs_to_cover(scopes)

    def test_docs_only_change_does_not_trigger_backend(self, workflow):
        """성공 방향 대조군 — 전부 'triggered'로 접는 과잉 수정을 막는다."""
        scopes = tool.classify_jobs(workflow, ["docs/reviews/some_review.md"])
        by_name = {s.name: s for s in scopes}
        assert by_name["backend"].status == tool.NOT_TRIGGERED
        assert by_name["mobile"].status == tool.NOT_TRIGGERED

    def test_frozen_input_doc_triggers_backend(self, workflow):
        """동결 입력 문서는 backend를 깨운다 — 필터가 그렇게 적혀 있다."""
        scopes = tool.classify_jobs(workflow, ["docs/architecture/canonical_entity_model_v1.md"])
        assert {s.name: s.status for s in scopes}["backend"] == tool.TRIGGERED


# ── ③ 로컬 재현 커버리지 대조 ─────────────────────────────────────────────
class TestCoverageCheck:
    def test_missing_job_is_named(self, workflow, capsys):
        """잡을 하나 빼면 exit 1이고 그 이름이 출력된다(acceptance ③·④)."""
        scopes = tool.classify_jobs(workflow, ["backlog/tasks/X.yaml"])
        required = [n for n in tool.jobs_to_cover(scopes)]
        assert len(required) >= 2, "대조 픽스처가 성립하려면 필수 잡이 2건 이상이어야 한다"
        dropped = required[-1]
        ran = [n for n in required if n != dropped]

        args = tool.build_parser().parse_args(
            ["--workflow", str(_CI_PATH), "check", "--changed-file", "backlog/tasks/X.yaml"]
            + [a for n in ran for a in ("--ran", n)]
        )
        rc = tool.cmd_check(args)
        out = capsys.readouterr().out
        assert rc == 1, f"잡 '{dropped}'를 빼고 돌렸는데 통과로 판정했다"
        assert dropped in out, f"빠진 잡 '{dropped}'를 이름으로 지목하지 않았다"

    def test_full_coverage_passes(self, workflow, capsys):
        scopes = tool.classify_jobs(workflow, ["backlog/tasks/X.yaml"])
        required = tool.jobs_to_cover(scopes)
        args = tool.build_parser().parse_args(
            ["--workflow", str(_CI_PATH), "check", "--changed-file", "backlog/tasks/X.yaml"]
            + [a for n in required for a in ("--ran", n)]
        )
        assert tool.cmd_check(args) == 0
        assert "커버리지 충족" in capsys.readouterr().out

    def test_unknown_job_name_is_rejected(self, workflow, capsys):
        """ci.yml에 없는 잡을 '돌렸다'고 주장하면 통과시키지 않는다."""
        scopes = tool.classify_jobs(workflow, ["backlog/tasks/X.yaml"])
        required = tool.jobs_to_cover(scopes)
        args = tool.build_parser().parse_args(
            ["--workflow", str(_CI_PATH), "check", "--changed-file", "backlog/tasks/X.yaml"]
            + [a for n in required for a in ("--ran", n)]
            + ["--ran", "존재하지-않는-잡"]
        )
        assert tool.cmd_check(args) == 1
        assert "존재하지-않는-잡" in capsys.readouterr().out

    def test_irreproducible_job_is_not_counted_as_run(self, workflow, capsys):
        """재현 불가 잡(docker-build)은 별도로 보고되고 exit 1을 내지 않는다(acceptance ⑥)."""
        changed = ["src/backend/whymath_backend/l3/router.py"]
        scopes = tool.classify_jobs(workflow, changed)
        required = tool.jobs_to_cover(scopes)
        assert "docker-build" in required
        ran = [n for n in required if n != "docker-build"]
        args = tool.build_parser().parse_args(
            ["--workflow", str(_CI_PATH), "check", "--changed-file", changed[0]]
            + [a for n in ran for a in ("--ran", n)]
        )
        rc = tool.cmd_check(args)
        out = capsys.readouterr().out
        assert rc == 0, "재현 불가 잡을 빠뜨렸다고 실패 판정하면 사람이 도구를 끈다"
        assert "재현 불가" in out and "docker-build" in out


# ── ④ 3값 논리 — 모른다 ≠ 아니다 ──────────────────────────────────────────
class TestThreeValuedLogic:
    def test_unknown_propagates_through_and(self):
        assert tool.evaluate_condition("unknown.ctx == 'x' && true", {}) is tool.UNKNOWN_VALUE

    def test_false_short_circuits_and(self):
        """UNKNOWN && False = False — 3값 논리가 보수적으로만 접힌다."""
        expr = "unknown.ctx == 'x' && github.event_name == 'schedule'"
        assert tool.evaluate_condition(expr, {}, event_name="pull_request") is False

    def test_true_short_circuits_or(self):
        expr = "unknown.ctx == 'x' || github.event_name == 'pull_request'"
        assert tool.evaluate_condition(expr, {}, event_name="pull_request") is True

    def test_unmatched_syntax_is_unknown_not_false(self):
        """모르는 문법은 UNKNOWN — False로 접으면 잡이 조용히 면제된다."""
        assert tool.evaluate_condition("contains(github.ref, 'main')", {}) is tool.UNKNOWN_VALUE

    def test_unknown_job_is_included_in_coverage(self):
        """판정 불가 잡은 '봐야 하는 잡'에 포함된다 — 면제하면 도구가 위장이 된다."""
        wf = {
            "jobs": {
                "changes": {"steps": []},
                "mystery": {"if": "contains(github.ref, 'main')", "steps": []},
            }
        }
        scopes = tool.classify_jobs(wf, ["any/file.py"])
        by_name = {s.name: s for s in scopes}
        assert by_name["mystery"].status == tool.UNKNOWN
        assert "mystery" in tool.jobs_to_cover(scopes)

    def test_flag_referenced_but_undefined_is_unknown(self):
        """필터 정본에 없는 플래그를 참조하면 '안 닿음'이 아니라 '판정 불가'다."""
        wf = {
            "jobs": {
                "changes": {"steps": []},
                "ghost": {"if": "needs.changes.outputs.nonexistent == 'true'", "steps": []},
            }
        }
        scopes = tool.classify_jobs(wf, ["any/file.py"])
        by_name = {s.name: s for s in scopes}
        assert by_name["ghost"].status == tool.UNKNOWN
        assert (
            "nonexistent" in by_name["ghost"].reason
        ), "판정 불가의 *사유*가 플래그 미정의임을 말하지 않으면 사람이 원인을 못 찾는다"

    def test_partially_undefined_flag_does_not_silently_exempt_job(self, tmp_path):
        """미정의 플래그 검사 절의 반례 — 이 절이 없으면 통과하는 입력.

        정의된 플래그가 false이고 미정의 플래그와 AND로 묶이면 조건 평가기만으로는
        `False && UNKNOWN = False` → NOT_TRIGGERED가 된다. 즉 **모르는 조건이 섞인 잡이
        조용히 면제된다**. 앞 테스트의 픽스처(단일 미정의 플래그)는 두 경로 모두 UNKNOWN을
        내므로 이 절을 밟지 않는다(CLAUDE.md 2026-09-07 픽스처 접촉 규칙).
        """
        wf = yaml.safe_load(_CI_PATH.read_text(encoding="utf-8"))
        wf["jobs"]["hybrid"] = {
            "if": "needs.changes.outputs.backend == 'true' && needs.changes.outputs.ghost == 'true'",
            "steps": [],
        }
        target = tmp_path / "ci.yml"
        target.write_text(yaml.safe_dump(wf, allow_unicode=True), encoding="utf-8")

        scopes = tool.classify_jobs(tool.load_workflow(target), ["docs/reviews/only.md"])
        by_name = {s.name: s for s in scopes}
        assert (
            by_name["backend"].status == tool.NOT_TRIGGERED
        ), "픽스처 전제(backend=false)가 깨졌다"
        assert (
            by_name["hybrid"].status == tool.UNKNOWN
        ), "미정의 플래그가 섞였는데 '안 닿음'으로 접었다 — 모른다를 아니다로 읽은 것"
        assert "hybrid" in tool.jobs_to_cover(scopes)


# ── ⑤ 잡 경계의 환경 차 ───────────────────────────────────────────────────
class TestJobEnvironment:
    def test_working_directory_differs_across_jobs(self, workflow):
        jobs = tool.enumerate_jobs(workflow)
        envs = {n: tool.describe_job_env(j) for n, j in jobs.items()}
        assert envs["backend"].working_directory == "src/backend"
        assert envs["infra-contracts"].working_directory is None  # 레포 루트
        assert len({e.working_directory for e in envs.values()}) >= 3

    def test_service_container_marks_irreproducible(self, workflow):
        jobs = tool.enumerate_jobs(workflow)
        env = tool.describe_job_env(jobs["backend-migrations"])
        assert "postgres" in env.services
        assert env.reproducible_locally is False
        assert env.irreproducible_reason and "postgres" in env.irreproducible_reason

    def test_install_hints_are_captured(self, workflow):
        jobs = tool.enumerate_jobs(workflow)
        env = tool.describe_job_env(jobs["infra-contracts"])
        assert any(
            "pip install" in h for h in env.install_hints
        ), "설치 스텝을 못 읽으면 사람이 잡 경계에서 같은 자리를 또 틀린다"

    def test_plain_job_is_reproducible(self, workflow):
        """대조군 — 모든 잡을 '재현 불가'로 접는 과잉 수정을 막는다."""
        env = tool.describe_job_env(tool.enumerate_jobs(workflow)["policy-guard"])
        assert env.reproducible_locally is True


# ── ⑥ 뮤테이션 — 정본이 바뀌면 판정도 바뀐다 ──────────────────────────────
class TestMutation:
    """path filter 정본을 깨뜨려 판정이 실제로 뒤집히는지 확인한다.

    주입이 조용히 실패하면 "정상 파일에 대해 테스트가 돌고 GREEN"이 되므로,
    치환이 실제로 적용됐는지(mutated != original)를 먼저 단언한다
    (CLAUDE.md 2026-09-06 '주입 자체의 실재').
    """

    @staticmethod
    def _mutate(tmp_path: Path, old: str, new: str) -> tuple[Path, str]:
        original = _CI_PATH.read_text(encoding="utf-8")
        assert original.count(old) >= 1, f"치환 대상이 정본에 없다: {old!r}"
        mutated = original.replace(old, new, 1)
        assert mutated != original, "주입이 적용되지 않았다 — 하네스 결함"
        target = tmp_path / "ci.yml"
        target.write_text(mutated, encoding="utf-8")
        return target, original

    def test_removing_backend_from_docker_filter_flips_verdict(self, tmp_path):
        """M1: docker 필터에서 src/backend/를 빼면 docker-build가 '안 닿음'이 된다."""
        changed = ["src/backend/whymath_backend/l3/router.py"]
        before = {
            s.name: s.status for s in tool.classify_jobs(tool.load_workflow(_CI_PATH), changed)
        }
        assert before["docker-build"] == tool.TRIGGERED

        # 앞의 `|`까지 함께 지운다 — 대안만 비우면 `(…||…)`가 되어 **빈 대안**이 생기고
        # 빈 대안은 모든 파일에 매치한다(뮤테이션이 의도와 반대 방향으로 작동).
        # 하네스가 뜻대로 깨뜨렸는지는 아래 판정 역전으로만 확인된다.
        target, original = self._mutate(
            tmp_path,
            "|src/backend/|tests/infra/test_deploy_artifacts",
            "|tests/infra/test_deploy_artifacts",
        )
        after = {s.name: s.status for s in tool.classify_jobs(tool.load_workflow(target), changed)}
        assert (
            after["docker-build"] == tool.NOT_TRIGGERED
        ), "필터를 깨뜨렸는데 판정이 그대로다 — 도구가 정본을 읽지 않는다는 증거"
        assert _CI_PATH.read_text(encoding="utf-8") == original, "원본이 오염됐다"

    def test_removing_job_shrinks_enumeration(self, tmp_path):
        """M2: 잡 하나를 지우면 열거에서 사라진다(열거가 실제 파싱인지)."""
        original = _CI_PATH.read_text(encoding="utf-8")
        wf = yaml.safe_load(original)
        del wf["jobs"]["policy-guard"]
        target = tmp_path / "ci.yml"
        target.write_text(yaml.safe_dump(wf, allow_unicode=True), encoding="utf-8")
        assert "policy-guard" not in tool.enumerate_jobs(tool.load_workflow(target))
        assert "policy-guard" in tool.enumerate_jobs(tool.load_workflow(_CI_PATH))

    def test_breaking_output_echo_loses_flag_mapping(self, tmp_path):
        """M3: echo 매핑을 깨뜨리면 그 플래그가 '판정 불가'가 된다 — 조용히 false가 아니다."""
        target, original = self._mutate(
            tmp_path,
            'echo "docker=$dk" >> "$GITHUB_OUTPUT"',
            'echo "dockerX=$dk" >> "$GITHUB_OUTPUT"',
        )
        scopes = tool.classify_jobs(tool.load_workflow(target), ["Dockerfile"])
        by_name = {s.name: s.status for s in scopes}
        assert by_name["docker-build"] == tool.UNKNOWN
        assert "docker-build" in tool.jobs_to_cover(scopes)
        assert _CI_PATH.read_text(encoding="utf-8") == original

    def test_mutation_restores_bytes_identical(self, tmp_path):
        """원복 충실도 — 이 테스트들이 정본 파일을 건드리지 않음을 해시로 단언한다."""
        digest = hashlib.sha256(_CI_PATH.read_bytes()).hexdigest()
        self._mutate(tmp_path, "src/backend/", "src/backend_MUTATED/")
        assert hashlib.sha256(_CI_PATH.read_bytes()).hexdigest() == digest


# ── ⑦ CLI 계약 ────────────────────────────────────────────────────────────
class TestCli:
    def test_enumerate_exits_zero(self, capsys):
        args = tool.build_parser().parse_args(["--workflow", str(_CI_PATH), "enumerate"])
        assert tool.cmd_enumerate(args) == 0
        assert "CI 잡" in capsys.readouterr().out

    def test_scope_json_shape(self, capsys):
        args = tool.build_parser().parse_args(
            ["--workflow", str(_CI_PATH), "scope", "--changed-file", "README.md", "--json"]
        )
        assert tool.cmd_scope(args) == 0
        import json as _json

        payload = _json.loads(capsys.readouterr().out)
        assert {"changed_files", "jobs", "to_cover"} <= set(payload)
        assert payload["jobs"], "잡 목록이 비어 있다"

    def test_main_returns_one_on_empty_scan(self, tmp_path, capsys):
        empty = tmp_path / "ci.yml"
        empty.write_text("name: x\njobs: {}\n", encoding="utf-8")
        rc = tool.main(["--workflow", str(empty), "enumerate"])
        assert rc == 1, "잡 0건은 exit 1이어야 한다"
