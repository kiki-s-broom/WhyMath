"""[HARN-28] 고립 브랜치 스캔 발행의 **집행 지점·소비 지점 실재성** 동결.

왜 이 테스트가 있는가
--------------------
`scan_stale_branches`는 shallow 클론이면 판정을 포기하고, 모든 CCR 세션 컨테이너가 shallow라
세션에서는 한 번도 목록을 낸 적이 없다. 해법은 실행 위치를 CI로 옮기는 것인데, 잡을 *만든 것*과
그 잡이 **full clone에서, 쓰기 권한으로, 실패를 삼키지 않고** 도는 것은 다르다
(CLAUDE.md "검증 장치를 만들고 배선 확인 없이 완료 선언 금지" · `test_claim_reap_enforcement_wiring.py`
HARN-27 동형 선례). 또 발행해도 `cmd_brief`가 읽지 않으면 아무도 못 본다 — 소비 지점도 동결한다.

검증 계약
--------
① `harness-audit.yml`이 `isolation_report.py publish`를 실제로 호출하는 스텝을 가진다.
② 그 잡의 체크아웃이 **`fetch-depth: 0`** 이다 — 이게 빠지면 잡이 shallow에서 돌아 스캔을
   포기한다(이 태스크가 고치려는 바로 그 결함).
③ 쓰기 권한(`contents: write`)은 잡 레벨, 그리고 **claim-reap과 이 잡에만** 있다. 워크플로
   기본값은 read, `flow-health` 등 관측 잡은 쓰기를 갖지 않는다.
④ `on:`에 `pull_request`가 없다(쓰기 잡이 PR에 노출되지 않는다는 보장을 조건문이 아니라
   트리거 부재로) · schedule·workflow_dispatch가 있다 · 잡은 push(main)에서 돌지 않는다.
⑤ 발행 스텝이 실패를 삼키지 않는다 — `|| true`·`continue-on-error`·`set +e`·`-q`·`| tail` 없음.
⑥ 쓰기 잡이 ci.yml(PR 검증 경로)로 새지 않는다.
⑦ 하네스 소유 브랜치 제외 목록이 두 스캐너에서 동기화돼 있다.
⑧ `cmd_brief`가 리포트 소비를 실제로 호출하고 렌더러에 넘긴다(AST).
⑨ 파서가 위장하지 않는다 — 파일을 못 읽거나 잡을 못 찾으면 "0건 통과"가 아니라 **실패**.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_AUDIT = _REPO_ROOT / ".github" / "workflows" / "harness-audit.yml"
_CI = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_BACKLOG = _REPO_ROOT / "scripts" / "harness" / "backlog.py"
_PUBLISH_INVOCATION = "isolation_report.py publish"

sys.path.insert(0, str(_REPO_ROOT / "scripts" / "harness"))

import isolation_report  # noqa: E402  (경로 삽입 후 임포트)
import remote_claims  # noqa: E402


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise AssertionError(f"{path} 이(가) 없다 — 집행 지점이 사라졌다.")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data.get("jobs"):
        raise AssertionError(
            f"{path} 파싱 결과에 jobs가 없다 — 파싱 실패를 '위반 0'으로 읽으면 안 된다."
        )
    return data


def _triggers(data: dict[str, Any]) -> dict[str, Any]:
    # PyYAML은 `on:`을 boolean True로 파싱한다(YAML 1.1) — 두 키 모두 확인한다.
    triggers = data.get("on", data.get(True))
    assert isinstance(triggers, dict), f"on: 파싱 실패({triggers!r}) — 판정 불가"
    return triggers


def _publish_job(data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    found = [
        (name, job)
        for name, job in data["jobs"].items()
        for step in job.get("steps") or []
        if _PUBLISH_INVOCATION in str(step.get("run") or "")
    ]
    if not found:
        raise AssertionError(
            f"'{_PUBLISH_INVOCATION}' 를 실행하는 스텝이 없다 — 발행 집행 지점이 사라졌다."
        )
    assert len(found) == 1, f"발행 스텝이 {len(found)}곳이다 — 한 곳이어야 CAS 경합이 없다"
    return found[0]


def _publish_step(job: dict[str, Any]) -> dict[str, Any]:
    for step in job.get("steps") or []:
        if _PUBLISH_INVOCATION in str(step.get("run") or ""):
            return step
    raise AssertionError("발행 스텝을 찾지 못했다.")


def test_publish_step_is_wired() -> None:
    """① 발행 스텝이 실제로 배선돼 있다."""
    _publish_job(_load(_AUDIT))


def test_checkout_is_a_full_clone() -> None:
    """② 체크아웃이 fetch-depth: 0 — 빠지면 잡이 shallow에서 돌아 스캔을 포기한다."""
    _, job = _publish_job(_load(_AUDIT))
    checkouts = [s for s in job["steps"] if str(s.get("uses") or "").startswith("actions/checkout")]
    assert checkouts, "발행 잡에 체크아웃이 없다"
    assert checkouts[0].get("with", {}).get("fetch-depth") == 0, (
        "발행 잡의 체크아웃이 fetch-depth: 0이 아니다 — shallow 클론에서는 scan_stale_branches가 "
        "판정을 포기한다(이 태스크가 고치려는 바로 그 결함)"
    )


def test_checkout_precedes_the_publish_step() -> None:
    """② 보강 — 순서가 뒤집히면 체크아웃 전에 스캔이 돈다."""
    _, job = _publish_job(_load(_AUDIT))
    steps = job["steps"]
    checkout_idx = next(
        i for i, s in enumerate(steps) if str(s.get("uses") or "").startswith("actions/checkout")
    )
    publish_idx = steps.index(_publish_step(job))
    assert checkout_idx < publish_idx


def test_write_permission_is_scoped_to_the_publish_job() -> None:
    """③ 쓰기 권한은 잡 레벨 — 워크플로 기본은 read이고 관측 잡은 쓰기를 갖지 않는다."""
    data = _load(_AUDIT)
    name, job = _publish_job(data)
    assert (data.get("permissions") or {}).get("contents") == "read"
    assert (job.get("permissions") or {}).get(
        "contents"
    ) == "write", "발행 잡에 contents: write가 없다 — harness-reports 푸시가 403으로 실패한다"
    writers = {
        n
        for n, j in data["jobs"].items()
        if (j.get("permissions") or {}).get("contents") == "write"
    }
    assert writers == {
        "claim-reap",
        name,
    }, f"contents: write를 가진 잡이 {sorted(writers)} — claim-reap과 발행 잡 밖으로 새면 안 된다"
    assert (data["jobs"]["flow-health"].get("permissions") or {}).get("contents") == "read"


def test_triggers_are_nightly_and_manual_only_for_this_job() -> None:
    """④ 쓰기 잡이 PR에 노출되지 않고, 야간·수동으로 돌며, push(main)에서는 돌지 않는다."""
    data = _load(_AUDIT)
    triggers = _triggers(data)
    assert "pull_request" not in triggers
    assert "pull_request_target" not in triggers
    assert "schedule" in triggers, "야간 schedule이 없다 — 리포트가 갱신되지 않는다"
    assert "workflow_dispatch" in triggers, "수동 실행 경로가 없다 — 최초 발행을 못 시킨다"
    _, job = _publish_job(data)
    condition = str(job.get("if") or "")
    assert "github.event_name" in condition and "'push'" in condition and "!=" in condition, (
        f"발행 잡이 push(main)마다 돈다(if={condition!r}) — 전체 fetch + API 조회가 main push마다 "
        "도는 것은 낭비다"
    )


def test_publish_step_does_not_swallow_failure() -> None:
    """⑤ 실패 은닉 장치가 없다 — 상시 무력화돼도 초록으로 보이는 것을 막는다."""
    _, job = _publish_job(_load(_AUDIT))
    step = _publish_step(job)
    run = str(step.get("run") or "")
    assert "continue-on-error" not in step and "continue-on-error" not in job
    # 스텝 조건문도 은닉 장치다 — `if: ${{ false }}`는 잡을 초록으로 둔 채 발행만 영구히 건너뛴다
    # (뮤테이션 M38이 이 빈틈을 찾았다). 발행은 잡 조건만 통과하면 무조건 실행돼야 한다.
    assert (
        "if" not in step
    ), f"발행 스텝에 조건문이 있다({step.get('if')!r}) — 조용히 건너뛸 수 있다"
    for banned in ("|| true", "set +e", " -q", "| tail", "| head", "--dry-run"):
        assert banned not in run, f"발행 스텝에 {banned!r} — 종료 코드를 가리거나 출력을 자른다"
    assert (step.get("env") or {}).get(
        "GITHUB_TOKEN"
    ), "발행 스텝에 GITHUB_TOKEN이 없다 — PR 열림/닫힘·처분 라벨 조회가 영구 미확인이 된다"


def test_measurement_artifact_is_uploaded_even_on_failure() -> None:
    """실패해도 증거가 남는다 — 아티팩트 업로드 스텝이 if: always()."""
    _, job = _publish_job(_load(_AUDIT))
    uploads = [
        s for s in job["steps"] if str(s.get("uses") or "").startswith("actions/upload-artifact")
    ]
    assert uploads, "측정 원본 보존 스텝이 없다 — 브랜치는 최신 1건만 들므로 추이가 사라진다"
    assert uploads[0].get("if") == "always()"


def test_write_job_is_not_leaked_into_ci_yml() -> None:
    """⑥ ci.yml(PR 검증 경로)에는 발행 호출이 없다."""
    text = _CI.read_text(encoding="utf-8")
    assert (
        _PUBLISH_INVOCATION not in text
    ), "ci.yml이 isolation_report.py publish를 부른다 — 쓰기 권한이 PR 검증 경로로 샌다"
    for name, job in _load(_CI)["jobs"].items():
        assert (job.get("permissions") or {}).get(
            "contents"
        ) != "write", f"ci.yml 잡 {name!r}이 contents: write를 갖는다"


def test_owned_branch_exclusions_are_in_sync() -> None:
    """⑦ 하네스 소유 브랜치(claim 대장·리포트)를 두 스캐너가 같은 집합으로 제외한다."""
    assert remote_claims.HARNESS_OWNED_BRANCHES == {
        remote_claims.CLAIMS_BRANCH,
        remote_claims.REPORTS_BRANCH,
    }
    assert isolation_report.REPORTS_BRANCH == remote_claims.REPORTS_BRANCH

    spec = importlib.util.spec_from_file_location(
        "flow_health_for_isolation_test", _REPO_ROOT / "scripts" / "ops" / "flow_health.py"
    )
    assert spec is not None and spec.loader is not None
    flow_health = importlib.util.module_from_spec(spec)
    # dataclass가 `sys.modules[cls.__module__]`를 조회하므로 실행 전에 등록해야 한다.
    sys.modules[spec.name] = flow_health
    try:
        spec.loader.exec_module(flow_health)
        excluded = set(flow_health.EXCLUDED)
    finally:
        sys.modules.pop(spec.name, None)
    missing = remote_claims.HARNESS_OWNED_BRANCHES - excluded
    assert not missing, (
        f"flow_health.EXCLUDED가 {sorted(missing)}를 빠뜨렸다 — 야간 잡이 멎으면 "
        "하네스 데이터 브랜치가 PR 미제출 WIP로 계상된다"
    )


def test_cmd_brief_is_wired_to_the_report_consumer() -> None:
    """⑧ cmd_brief가 리포트 소비를 호출하고 그 출처 줄을 렌더러에 넘긴다 — 소비 지점."""
    tree = ast.parse(_BACKLOG.read_text(encoding="utf-8"))
    brief = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "cmd_brief"),
        None,
    )
    assert brief is not None, "cmd_brief를 찾지 못했다 — 판정 불가"
    calls_consumer = any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "brief_for_session"
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "isolation_report"
        for n in ast.walk(brief)
    )
    assert calls_consumer, "cmd_brief가 isolation_report.brief_for_session을 호출하지 않는다"
    passes_through = any(
        isinstance(n, ast.keyword) and n.arg == "isolation_source" for n in ast.walk(brief)
    )
    assert passes_through, "cmd_brief가 render_brief에 isolation_source를 넘기지 않는다"


@pytest.mark.parametrize("which", ["missing_file", "no_jobs", "no_publish_step"])
def test_parser_does_not_masquerade_as_zero_violations(tmp_path: Path, which: str) -> None:
    """⑨ 파서가 위장하지 않는다 — 읽지 못했거나 대상이 없으면 통과가 아니라 실패다."""
    target = tmp_path / "wf.yml"
    if which == "no_jobs":
        target.write_text("name: x\non: push\n", encoding="utf-8")
    elif which == "no_publish_step":
        target.write_text(
            "name: x\non: push\njobs:\n  a:\n    steps:\n      - run: echo hi\n", encoding="utf-8"
        )
    with pytest.raises(AssertionError):
        data = _load(target)
        _publish_job(data)
