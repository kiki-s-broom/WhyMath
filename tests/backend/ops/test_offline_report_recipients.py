"""오프라인 리포트 면제의 수취인 계약 테스트 — OPS-34.

`_OFFLINE_REPORT`("수치를 보려고 사람이 돌린다")로 면제된 CLI는 그 사람·시점을 선언해야 한다
(`runbook:` / `report-schedule:` / `pending-task:`). "성공/실패 양쪽에서 같은 값을 내는 검사는
검증이 아니라 위장"(CLAUDE.md)이라 각 판정 절마다 **그 절이 없으면 통과해 버리는 입력**을 픽스처에
넣었다 — 정상 입력에서 초록인 것은 보호의 증거가 아니다.

합성 저장소(`tmp_path`)로 절별 변별력을, 실 저장소로 종단 주입(빨강 → 복원 → 초록)을 확인한다.
실 저장소 스캔은 `build_report()` 1회가 약 15초라 모듈 픽스처 1회 + 종단 주입 2회로 제한한다.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest
import yaml

from whymath_backend.ops import declared_unwired_audit as dua

KEY = "harness.demo_report"
CMD = f"-m whymath_backend.{KEY}"


# ── 합성 저장소 도우미 ───────────────────────────────────────────────────────


def _section(
    title: str = "demo_report", *, cmd: bool = True, who: bool = True, when: bool = True
) -> str:
    """런북 한 섹션. 인자로 각 필수 요소를 뺄 수 있다(그 요소가 없으면 실패해야 하는 픽스처)."""
    lines = [f"### {title}", ""]
    if who:
        lines.append("- **수취인**: Kiki")
    if when:
        lines.append("- **시점**: 코퍼스 적재 직전")
    if cmd:
        lines += ["", "```powershell", f"& $Py {CMD}", "```"]
    return "\n".join(lines) + "\n"


def _repo(tmp_path: Path, runbook_text: str | None = None) -> Path:
    (tmp_path / "docs" / "ops").mkdir(parents=True)
    (tmp_path / "backlog" / "tasks").mkdir(parents=True)
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    if runbook_text is not None:
        (tmp_path / "docs" / "ops" / "rb.md").write_text(runbook_text, encoding="utf-8")
    return tmp_path


def _task(base: Path, task_id: str, status: str) -> None:
    path = base / "backlog" / "tasks" / f"{task_id}.yaml"
    path.write_text(yaml.safe_dump({"id": task_id, "status": status}), encoding="utf-8")


def _workflow(base: Path, name: str, text: str) -> None:
    (base / ".github" / "workflows" / name).write_text(text, encoding="utf-8")


def _cron_workflow(run: str, *, comment: str = "") -> str:
    return (
        f"{comment}\n"
        "name: nightly\n"
        "on:\n  schedule:\n    - cron: '0 3 * * 1'\n"
        "jobs:\n  j:\n    runs-on: ubuntu-latest\n    steps:\n"
        f"      - run: {run}\n"
    )


def _verdict(spec: str | None, base: Path) -> dua.ItemVerdict:
    return dua._recipient_verdict(KEY, spec, base)


RB = "runbook:docs/ops/rb.md#"

# ── 선언 자체 ────────────────────────────────────────────────────────────────


def test_missing_declaration_is_a_violation(tmp_path: Path) -> None:
    verdict = _verdict(None, _repo(tmp_path))
    assert verdict.status == "no-recipient"
    assert verdict.is_violation


def test_unknown_form_is_malformed(tmp_path: Path) -> None:
    verdict = _verdict("somebody-will-run-it", _repo(tmp_path))
    assert verdict.status == "malformed-recipient"
    assert verdict.is_violation


# ── runbook: 형식 ────────────────────────────────────────────────────────────


def test_runbook_valid_when_section_has_command_recipient_and_when(tmp_path: Path) -> None:
    base = _repo(tmp_path, _section())
    verdict = _verdict(f"{RB}demo_report", base)
    assert verdict.status == "by-design"
    assert not verdict.is_violation


@pytest.mark.parametrize("spec", ["runbook:docs/ops/rb.md", "runbook:#demo_report", "runbook:"])
def test_runbook_without_path_or_anchor_is_malformed(tmp_path: Path, spec: str) -> None:
    verdict = _verdict(spec, _repo(tmp_path, _section()))
    assert verdict.status == "malformed-recipient"


def test_runbook_path_escaping_the_repo_is_malformed(tmp_path: Path) -> None:
    """저장소 밖 파일을 가리키는 선언은 근거가 될 수 없다 — 상위 디렉터리에 진짜 런북이 있어도."""
    outer = tmp_path / "outer"
    base = _repo(outer / "repo", None)
    (outer / "rb.md").write_text(_section(), encoding="utf-8")
    verdict = _verdict("runbook:../rb.md#demo_report", base)
    assert verdict.status == "malformed-recipient"


def test_runbook_file_missing(tmp_path: Path) -> None:
    verdict = _verdict(f"{RB}demo_report", _repo(tmp_path))
    assert verdict.status == "invalid-recipient"
    assert "부재" in verdict.note


def test_runbook_anchor_missing(tmp_path: Path) -> None:
    verdict = _verdict(f"{RB}other_report", _repo(tmp_path, _section()))
    assert verdict.status == "invalid-recipient"
    assert "앵커" in verdict.note


@pytest.mark.parametrize(
    ("omit", "needle"),
    [("cmd", CMD), ("who", "수취인"), ("when", "시점")],
)
def test_runbook_section_missing_a_required_element(tmp_path: Path, omit: str, needle: str) -> None:
    """링크만 건 선언 차단 — 명령·수취인·시점 중 하나라도 빠지면 근거가 아니다."""
    kwargs = {"cmd": omit != "cmd", "who": omit != "who", "when": omit != "when"}
    base = _repo(tmp_path, _section(**kwargs))
    verdict = _verdict(f"{RB}demo_report", base)
    assert verdict.status == "invalid-recipient"
    assert needle in verdict.note


def test_runbook_command_for_a_different_module_does_not_count(tmp_path: Path) -> None:
    """다른 모듈의 명령이 있는 섹션을 가리키면 안 된다 — 한 섹션을 7개 항목이 돌려 쓰는 위장."""
    text = _section().replace(CMD, "-m whymath_backend.harness.other_report")
    verdict = _verdict(f"{RB}demo_report", _repo(tmp_path, text))
    assert verdict.status == "invalid-recipient"


def test_markers_in_the_next_section_do_not_count(tmp_path: Path) -> None:
    """섹션 경계: 수취인·시점이 *다음* 섹션에만 있으면 이 섹션은 수취인이 없는 것이다."""
    text = _section(who=False, when=False) + "\n" + _section("next_report")
    verdict = _verdict(f"{RB}demo_report", _repo(tmp_path, text))
    assert verdict.status == "invalid-recipient"
    assert "수취인" in verdict.note


def test_comment_line_inside_a_code_fence_does_not_end_the_section(tmp_path: Path) -> None:
    """PowerShell 주석(`# ...`)은 제목이 아니다 — 제목으로 오인하면 섹션이 거기서 끊겨 명령이 밀려난다."""
    text = (
        "### demo_report\n\n"
        "- **수취인**: Kiki\n- **시점**: 적재 직전\n\n"
        "```powershell\n# [시스템: Windows PowerShell]\n"
        f"& $Py {CMD}\n```\n"
    )
    verdict = _verdict(f"{RB}demo_report", _repo(tmp_path, text))
    assert verdict.status == "by-design"


def test_heading_inside_a_code_fence_is_not_an_anchor(tmp_path: Path) -> None:
    text = "```powershell\n### demo_report\n```\n" + "수취인 시점 " + CMD + "\n"
    verdict = _verdict(f"{RB}demo_report", _repo(tmp_path, text))
    assert verdict.status == "invalid-recipient"
    assert "앵커" in verdict.note


def test_deeper_subheading_stays_inside_the_section(tmp_path: Path) -> None:
    """하위 제목(####)은 섹션을 끊지 않는다 — 같은·상위 수준 제목에서만 끝난다."""
    text = "### demo_report\n\n#### 상세\n- **수취인**: Kiki\n- **시점**: x\n" + CMD + "\n"
    verdict = _verdict(f"{RB}demo_report", _repo(tmp_path, text))
    assert verdict.status == "by-design"


def test_unreadable_runbook_is_invalid_not_a_crash(tmp_path: Path) -> None:
    base = _repo(tmp_path)
    (base / "docs" / "ops" / "rb.md").write_bytes(b"\xff\xfe\x00bad")
    verdict = _verdict(f"{RB}demo_report", base)
    assert verdict.status == "invalid-recipient"
    assert "UnicodeDecodeError" in verdict.note  # 예외 타입명이 남는다(침묵 실패 금지)


def test_github_anchor_matches_github_rules() -> None:
    assert dua._github_anchor("problem_bank_coverage") == "problem_bank_coverage"
    assert dua._github_anchor("3-1. Foo Bar!") == "3-1-foo-bar"
    assert dua._github_anchor("`harness.x` 실행") == "harnessx-실행"


# ── report-schedule: ─────────────────────────────────────────────────────────


def test_schedule_valid_with_cron_workflow_running_the_module(tmp_path: Path) -> None:
    base = _repo(tmp_path)
    _workflow(base, "nightly.yml", _cron_workflow(f"python {CMD}"))
    verdict = _verdict("report-schedule:weekly", base)
    assert verdict.status == "by-design"
    assert "nightly.yml" in verdict.note


def test_schedule_with_unknown_cadence_is_malformed(tmp_path: Path) -> None:
    base = _repo(tmp_path)
    _workflow(base, "nightly.yml", _cron_workflow(f"python {CMD}"))
    verdict = _verdict("report-schedule:sometimes", base)
    assert verdict.status == "malformed-recipient"


def test_schedule_without_any_workflow_is_invalid(tmp_path: Path) -> None:
    """주기만 적은 선언 — 그것을 돌리는 스케줄러가 없으면 선언일 뿐이다."""
    verdict = _verdict("report-schedule:weekly", _repo(tmp_path))
    assert verdict.status == "invalid-recipient"


def test_schedule_mention_only_in_a_comment_does_not_count(tmp_path: Path) -> None:
    base = _repo(tmp_path)
    _workflow(base, "nightly.yml", _cron_workflow("echo hi", comment=f"# {CMD}"))
    assert _verdict("report-schedule:weekly", base).status == "invalid-recipient"


def test_schedule_workflow_without_cron_trigger_does_not_count(tmp_path: Path) -> None:
    base = _repo(tmp_path)
    text = _cron_workflow(f"python {CMD}").replace(
        "  schedule:\n    - cron: '0 3 * * 1'\n", "  workflow_dispatch:\n"
    )
    _workflow(base, "manual.yml", text)
    assert _verdict("report-schedule:weekly", base).status == "invalid-recipient"


def test_schedule_in_ci_yml_does_not_count(tmp_path: Path) -> None:
    """ci.yml은 여러 잡의 모음 — schedule 트리거가 있어도 이 호출이 야간 전용이라는 보장이 없다."""
    base = _repo(tmp_path)
    _workflow(base, "ci.yml", _cron_workflow(f"python {CMD}"))
    assert _verdict("report-schedule:weekly", base).status == "invalid-recipient"


# ── pending-task: (만료 계약 재사용) ─────────────────────────────────────────


def test_pending_task_expiry_contract(tmp_path: Path) -> None:
    base = _repo(tmp_path)
    assert _verdict("pending-task:T-1", base).status == "expired-waiver"  # 태스크 부재
    _task(base, "T-1", "done")
    assert _verdict("pending-task:T-1", base).status == "expired-waiver"  # 완료됨
    _task(base, "T-1", "todo")
    assert _verdict("pending-task:T-1", base).status == "pending-task"  # 유효
    assert not _verdict("pending-task:T-1", base).is_violation


def test_pending_task_expiry_is_one_implementation(tmp_path: Path) -> None:
    """재구현 0 — 면제 값 판정(`_classify`)과 수취인 판정이 같은 결과를 내고, 상태 조회는 한 곳뿐이다."""
    base = _repo(tmp_path)
    for status in (None, "done", "in_progress"):
        if status is not None:
            _task(base, "T-2", status)
        via_recipient = _verdict("pending-task:T-2", base)
        dua._MANIFEST.setdefault("scratch_axis", {})[KEY] = "pending-task:T-2"
        try:
            via_classify = dua._classify("scratch_axis", KEY, False, base / "backlog" / "tasks")
        finally:
            dua._MANIFEST.pop("scratch_axis", None)
        assert (via_recipient.status, via_recipient.note) == (
            via_classify.status,
            via_classify.note,
        )

    callers = [
        node.name
        for node in ast.walk(ast.parse(inspect.getsource(dua)))
        if isinstance(node, ast.FunctionDef)
        and any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "_task_status"
            for call in ast.walk(node)
        )
    ]
    assert callers == ["_pending_task_verdict"], callers


# ── evaluate_offline_recipients ──────────────────────────────────────────────


def _by_design(key: str) -> dua.ItemVerdict:
    return dua.ItemVerdict(dua.AXIS_CLI, key, "by-design", "사유")


def test_only_offline_report_exemptions_require_a_recipient(tmp_path: Path) -> None:
    """다른 면제 사유(라이브 의존 등)에는 수취인을 요구하지 않는다 — 계약의 범위."""
    base = _repo(tmp_path)
    out = dua.evaluate_offline_recipients((_by_design("harness.live"),), frozenset(), {}, base)
    assert [v.status for v in out] == ["by-design"]


def test_already_violating_item_is_not_double_counted(tmp_path: Path) -> None:
    base = _repo(tmp_path)
    stale = dua.ItemVerdict(dua.AXIS_CLI, KEY, "stale-waiver", "이미 도달")
    out = dua.evaluate_offline_recipients((stale,), frozenset({KEY}), {}, base)
    assert [v.status for v in out] == ["stale-waiver"]


def test_offline_item_without_recipient_becomes_a_violation(tmp_path: Path) -> None:
    base = _repo(tmp_path)
    out = dua.evaluate_offline_recipients((_by_design(KEY),), frozenset({KEY}), {}, base)
    assert [v.status for v in out] == ["no-recipient"]


def test_orphan_recipient_is_a_violation(tmp_path: Path) -> None:
    """면제를 걷고 수취인 줄만 남기는 드리프트."""
    base = _repo(tmp_path)
    out = dua.evaluate_offline_recipients((), frozenset(), {"harness.gone": "pending-task:T"}, base)
    assert [(v.key, v.status) for v in out] == [("harness.gone", "orphan-recipient")]
    assert out[0].is_violation


def test_valid_pending_task_recipient_shows_the_task_state(tmp_path: Path) -> None:
    base = _repo(tmp_path)
    _task(base, "T-3", "in_progress")
    out = dua.evaluate_offline_recipients(
        (_by_design(KEY),), frozenset({KEY}), {KEY: "pending-task:T-3"}, base
    )
    assert [v.status for v in out] == ["pending-task"]
    assert "T-3" in out[0].note


# ── 실 저장소 ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def real_report() -> dua.Report:
    return dua.build_report()


def _offline_keys() -> frozenset[str]:
    manifest = dua._MANIFEST[dua.AXIS_CLI]
    return frozenset(k for k, v in manifest.items() if v == dua._OFFLINE_REPORT)


def test_real_repo_passes_and_recipient_keys_equal_offline_keys(real_report: dua.Report) -> None:
    assert real_report.exit_code == 0, [v.to_json() for v in real_report.violations]
    offline = _offline_keys()
    assert offline, "면제 항목이 0건이면 이 계약이 아무것도 검사하지 않는다(공허 통과)"
    assert set(dua._OFFLINE_REPORT_RECIPIENTS) == offline


def test_real_repo_every_offline_item_names_a_runbook_section_with_its_own_command() -> None:
    """실 런북 섹션이 각 모듈의 명령과 수취인·시점을 실제로 갖는다(링크만 걸린 선언 없음)."""
    base = dua.repo_root()
    for key, spec in dua._OFFLINE_REPORT_RECIPIENTS.items():
        verdict = dua._recipient_verdict(key, spec, base)
        assert not verdict.is_violation, (key, verdict.to_json())


def test_real_repo_injection_removing_one_recipient_goes_red(
    real_report: dua.Report,
) -> None:
    """종단 주입(경량) — 실 저장소 CLI 판정에서 수취인 1건을 빼면 정확히 그 항목이 red."""
    cli = next(a for a in real_report.axes if a.axis == dua.AXIS_CLI).verdicts
    victim = sorted(dua._OFFLINE_REPORT_RECIPIENTS)[0]
    without = {k: v for k, v in dua._OFFLINE_REPORT_RECIPIENTS.items() if k != victim}
    injected = dua.evaluate_offline_recipients(cli, _offline_keys(), without, dua.repo_root())
    red = [(v.key, v.status) for v in injected if v.is_violation]
    assert red == [(victim, "no-recipient")]
    restored = dua.evaluate_offline_recipients(
        cli, _offline_keys(), dua._OFFLINE_REPORT_RECIPIENTS, dua.repo_root()
    )
    assert [v for v in restored if v.is_violation] == []


def test_build_report_end_to_end_red_then_green(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC ④ — 수취인 선언이 없는 면제 1건을 주입하면 CI 게이트(exit 1), 되돌리면 exit 0."""
    victim = sorted(dua._OFFLINE_REPORT_RECIPIENTS)[0]
    with monkeypatch.context() as patch:
        patch.delitem(dua._OFFLINE_REPORT_RECIPIENTS, victim)
        red = dua.build_report()
    assert red.exit_code == 1
    assert [(v.key, v.status) for v in red.violations] == [(victim, "no-recipient")]
    green = dua.build_report()
    assert green.exit_code == 0


def test_render_names_the_recipient_forms_on_failure() -> None:
    victim = dua.ItemVerdict(dua.AXIS_CLI, KEY, "no-recipient", "x")
    report = dua.Report(axes=(dua.AxisResult(dua.AXIS_CLI, (victim,)),))
    text = dua.render_report(report)
    assert "runbook:" in text and "report-schedule:" in text and "OPS-34" in text
