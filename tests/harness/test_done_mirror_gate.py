"""`done`의 CI 미러 게이트 (HARN-173) — 미러 부재를 warn에서 block으로 승격한 판정의 동결.

왜 이 파일이 있는가: 2026-09-25 EOS-24 PR #1316에서 세션이 CI 미러 도구가 있는데도 쓰지 않고
잡 스텝을 손으로 골라 재현해 `ruff check scripts tests/harness` 스텝을 빠뜨렸고, `done`의 미러
부재 경고는 한 번 떴을 뿐 아무도 멈추지 않았다(ci-local-repro-gap 4회차). 승격 판정의 정본은
`docs/standards/build_harness.md` §3c "`done` CI 미러 게이트"이고, 이 파일은 그 판정이 **문서가
아니라 exit code로 집행되는지**를 셀 단위로 동결한다.

각 절마다 "그 절이 없으면 통과해 버리는 반례"를 픽스처로 둔다. 이름이 의도를 말한다고 해서
코드가 그 의도를 실행하는 것은 아니다 — 대응은 아래 표다.

  절                                    그 절이 없으면 통과해 버리는 반례
  ─────────────────────────────────────────────────────────────────────────────────────
  unknown 차단                          block인데 결과 파일 없음/다른 커밋/깨진 JSON이 통과
  fail 차단                             block인데 실패한 미러 결과가 통과
  not_executed 면제                     조건 스텝 잡을 건드리는 done이 전부 막힘(HARN-181 전)
  `--no-pr` 면제                        investigation done이 미러 부재로 막힘
  사람 소유 면제                        Kiki의 `--as kiki` done이 미러 부재로 막힘
  사유 검증                             `--no-mirror '  '` 무사유 면제가 통과
  이벤트·notes 기록                     우회가 대장에 안 남아 사후 감시가 0건으로 보임
  정책 기본값 warn                      키 없는 저장소의 기존 done 테스트 전부가 막힘
  조회 실패 fail-open + unavailable     미러 모듈 부재 환경에서 모든 done이 막히거나, 조회 실패가
                                        pass로 접혀 기록됨(측정 실패 = 통과)
  정책 오류 = 엄격한 쪽                 policy.yaml 오타(`ci_mirror_at_dne`)가 조용히 warn으로 떨어짐
"""

from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import done_mirror_gate as gate
import pytest
import store
from models import CI_MIRROR_AT_DONE_MODES, Policy

import backlog as cli

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKLOG_CLI = _REPO_ROOT / "scripts" / "harness" / "backlog.py"
_REAL_CI = _REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _mirror():
    """`ci_mirror` 모듈 — 호출 시점의 sys.modules 항목.

    tests/infra가 같은 세션에서 이 모듈을 다른 인스턴스로 다시 올릴 수 있으므로(그 파일의
    `_load_mirror`), 최상단에서 한 번 붙잡아 두면 게이트가 부르는 인스턴스와 어긋난다.
    """
    return importlib.import_module("ci_mirror")


def _git(repo: Path, *argv: str) -> str:
    return subprocess.run(
        ["git", *argv], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def seeded_repo(git_repo: Path, monkeypatch) -> Path:
    """seed까지 끝난 저장소 (cwd 고정)."""
    monkeypatch.chdir(git_repo)
    assert cli.main(["seed"]) == 0
    return git_repo


def _claimed_task(capsys) -> str:
    """게이트 없는 착수 가능 claude 태스크 하나를 claim하고 id를 돌려준다."""
    assert cli.main(["next", "--n", "1", "--json"]) == 0
    task_id = json.loads(capsys.readouterr().out)[0]["id"]
    assert cli.main(["start", task_id, "--session", "test-branch"]) == 0
    capsys.readouterr()
    return task_id


def _human_task(capsys) -> str:
    """kiki 소유 태스크를 만들어 start까지 끝낸다(`--as kiki`)."""
    task_id = "T9-11-human-mirror-scope"
    assert (
        cli.main(
            [
                "add",
                "--eos-priority",
                "P2",
                "--id",
                task_id,
                "--title",
                "사람 판정",
                "--track",
                "math-completion",
                "--stage",
                "S1",
                "--owner",
                "kiki",
            ]
        )
        == 0
    )
    assert cli.main(["start", task_id, "--as", "kiki", "--session", "kiki-b", "--no-remote"]) == 0
    capsys.readouterr()
    return task_id


def _set_policy(repo: Path, mode: str | None) -> None:
    """policy.yaml을 쓴다. mode=None이면 키가 없는 정책(승격 이전 저장소)."""
    if mode is None:
        (repo / "backlog").mkdir(exist_ok=True)
        (repo / "backlog" / "policy.yaml").write_text(
            "version: 1\npath_overlap: warn\n", encoding="utf-8"
        )
        return
    store.save_policy(repo, Policy(ci_mirror_at_done=mode))


def _job(name: str, *steps: tuple[str, str]) -> object:
    m = _mirror()
    return m.JobResult(
        name=name,
        steps=[m.StepResult(name=n, status=s, reason=f"{n} 사유") for n, s in steps],
    )


def _write_mirror(repo: Path, kind: str) -> None:
    """미러 결과 픽스처 — 실제 `build_payload` 경로로 만든다(손으로 쓴 JSON은 형식 드리프트를 못 본다).

    kind: pass · not_executed · fail · absent · other_commit · corrupt · zero_jobs
    앞 셋은 이번 HEAD의 결과이고, 뒤 넷은 `unknown`(측정되지 않음)이 되는 서로 다른 원인이다.
    """
    m = _mirror()
    path = repo / m.DEFAULT_RESULT_PATH
    if kind == "absent":
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if kind == "corrupt":
        path.write_text("{깨진", encoding="utf-8")
        return
    jobs = {
        "pass": [_job("j", ("ok", m.PASSED))],
        "other_commit": [_job("j", ("ok", m.PASSED))],
        "not_executed": [_job("j", ("ok", m.PASSED), ("조건 게이트", m.NOT_EXECUTED))],
        "fail": [_job("j", ("boom", m.FAILED))],
        "zero_jobs": [],
    }[kind]
    payload = m.build_payload(jobs, repo, Path("ci.yml"))
    payload["commit"] = "d" * 40 if kind == "other_commit" else _git(repo, "rev-parse", "HEAD")
    m.save_payload(payload, path)


def _snapshot(repo: Path) -> dict[str, bytes]:
    """backlog/ 아래 전 파일의 바이트 — 거부가 대장에 아무것도 쓰지 않았는지 대조한다."""
    root = repo / "backlog"
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }


def _done_events(repo: Path, task_id: str) -> list[dict]:
    text = "".join(path.read_text(encoding="utf-8") for path in store.event_paths(repo))
    records = [json.loads(line) for line in text.splitlines() if line.strip()]
    return [r for r in records if r.get("id") == task_id and r.get("action") == "done"]


_PR = ["--artifact", "PR #1381"]


# ── 정책 키 ──────────────────────────────────────────────────────────────────


class TestPolicyKey:
    def test_default_is_warn_when_key_absent(self, tmp_path: Path):
        """키가 없는 policy.yaml·파일 부재는 warn — 이 절이 없으면 기존 저장소의 done이 전부 막힌다."""
        assert Policy().ci_mirror_at_done == "warn"
        (tmp_path / "backlog").mkdir()
        (tmp_path / "backlog" / "policy.yaml").write_text("path_overlap: warn\n", encoding="utf-8")
        policy, errors = store.load_policy(tmp_path)
        assert errors == [] and policy.ci_mirror_at_done == "warn"
        empty = tmp_path / "empty"
        empty.mkdir()
        policy, errors = store.load_policy(empty)
        assert errors == [] and policy.ci_mirror_at_done == "warn"

    @pytest.mark.parametrize("value", ["warn", "block"])
    def test_valid_values_pass_validation(self, value: str):
        assert Policy(ci_mirror_at_done=value).validate() == []

    @pytest.mark.parametrize("value", ["off", "strict", "", "BLOCK", "true"])
    def test_unknown_value_is_rejected(self, value: str):
        """`off`도 거부한다 — 끄는 값이 있으면 사유도 기록도 없는 탈출구가 된다."""
        errors = Policy(ci_mirror_at_done=value).validate()
        assert any("ci_mirror_at_done" in e for e in errors), errors

    def test_bool_value_from_yaml_is_rejected(self, tmp_path: Path):
        """YAML의 `block`이 아니라 `true`가 들어와도 warn으로 접히지 않고 오류가 된다."""
        (tmp_path / "backlog").mkdir()
        (tmp_path / "backlog" / "policy.yaml").write_text(
            "ci_mirror_at_done: true\n", encoding="utf-8"
        )
        _, errors = store.load_policy(tmp_path)
        assert any("ci_mirror_at_done" in e for e in errors), errors

    def test_roundtrip_keeps_the_key(self, tmp_path: Path):
        store.save_policy(tmp_path, Policy(ci_mirror_at_done="block"))
        loaded, errors = store.load_policy(tmp_path)
        assert errors == [] and loaded.ci_mirror_at_done == "block"
        assert "ci_mirror_at_done: block" in store.dump_policy(loaded)

    def test_modes_tuple_has_no_off(self):
        assert CI_MIRROR_AT_DONE_MODES == ("warn", "block")

    def test_this_repository_declares_block(self):
        """승격의 집행 지점 — 이 저장소의 policy.yaml이 block을 선언한다(§3c '승격 = 1줄 수정').

        이 단언이 없으면 코드만 승격되고 정작 이 저장소는 warn 그대로여도 초록이다.
        """
        policy, errors = store.load_policy(_REPO_ROOT)
        assert errors == []
        assert policy.ci_mirror_at_done == "block"


# ── 판정 표 (순수 함수) ──────────────────────────────────────────────────────

_PASS, _NOTEXEC, _FAIL, _UNKNOWN, _UNAVAIL = gate.MIRROR_STATES
assert (_PASS, _NOTEXEC, _FAIL, _UNKNOWN, _UNAVAIL) == (
    "pass",
    "not_executed",
    "fail",
    "unknown",
    "unavailable",
)

# (경로, 강제 수준, 미러 상태) → 기대 outcome — `--no-mirror` 없음. 30셀 전부 손으로 적는다.
# 판정 로직을 테스트에서 다시 계산하면 같은 오류를 두 번 쓰는 것이므로 표는 리터럴이다.
_TABLE_NO_MIRROR = {
    # PR 경로 · warn — 전부 종전 동작(거부 없음). 통과만 조용하고 나머지는 종전 경고.
    ("pr", "warn", "pass"): "pass",
    ("pr", "warn", "not_executed"): "warn",
    ("pr", "warn", "fail"): "warn",
    ("pr", "warn", "unknown"): "warn",
    ("pr", "warn", "unavailable"): "warn",
    # PR 경로 · block — unknown·fail만 거부. 미실행·조회 실패는 warn 유지.
    ("pr", "block", "pass"): "pass",
    ("pr", "block", "not_executed"): "warn",
    ("pr", "block", "fail"): "reject",
    ("pr", "block", "unknown"): "reject",
    ("pr", "block", "unavailable"): "warn",
    # 미러 대상이 아닌 경로 — 정책·상태와 무관하게 종전 그대로.
    **{
        (scope, mode, state): "exempt"
        for scope in ("no_pr", "human")
        for mode in ("warn", "block")
        for state in gate.MIRROR_STATES
    },
}


class TestDecisionTable:
    @pytest.mark.parametrize(("cell", "expected"), sorted(_TABLE_NO_MIRROR.items()))
    def test_cell_without_no_mirror(self, cell: tuple[str, str, str], expected: str):
        scope, mode, state = cell
        decision = gate.decide(scope=scope, mode=mode, state=state)
        assert decision.outcome == expected, f"{cell} → {decision.outcome} (기대 {expected})"

    def test_table_covers_every_cell(self):
        """표가 30셀 전부를 덮는다 — 셀이 빠지면 그 조합은 아무 테스트도 밟지 않는다."""
        assert len(_TABLE_NO_MIRROR) == 3 * 2 * 5

    @pytest.mark.parametrize("blank", ["", " ", "   ", "\t", "\n "])
    @pytest.mark.parametrize("scope", gate.SCOPES)
    @pytest.mark.parametrize("mode", CI_MIRROR_AT_DONE_MODES)
    @pytest.mark.parametrize("state", gate.MIRROR_STATES)
    def test_blank_reason_is_rejected_in_every_cell(self, blank, scope, mode, state):
        """사유 검증은 경로·정책·상태와 무관하다 — 무사유 면제가 통과하는 셀이 하나도 없다."""
        decision = gate.decide(scope=scope, mode=mode, state=state, no_mirror_reason=blank)
        assert decision.rejected
        assert "무사유 면제는 없다" in (decision.reject_message or "")
        assert decision.event_fields == {}, "거부인데 이벤트 필드가 남으면 대장에 쓰인다"

    def test_empty_and_blank_reasons_get_different_messages(self):
        """빈 인자(셸 변수가 비어 전달됨)와 공백만은 고칠 지점이 다르다 — 한 문구로 접지 않는다."""
        assert "비어 있다" in (gate.check_no_mirror_reason("") or "")
        assert "공백 문자뿐" in (gate.check_no_mirror_reason("   ") or "")
        assert "비어 있다" not in (gate.check_no_mirror_reason("   ") or "")
        assert gate.check_no_mirror_reason(None) is None
        assert gate.check_no_mirror_reason("사유") is None

    @pytest.mark.parametrize("state", [_FAIL, _UNKNOWN])
    def test_reason_rescues_only_the_blocked_states(self, state: str):
        """block이 거부했을 상태 + 유효한 사유 → 우회(기록 필수)."""
        decision = gate.decide(
            scope="pr", mode="block", state=state, no_mirror_reason="Windows 전용 스텝"
        )
        assert decision.outcome == "bypass"
        assert not decision.warn_legacy, "우회한 done에 재현 처방을 또 내면 사유가 무시된 것이다"
        assert decision.note == "Windows 전용 스텝"
        assert decision.event_fields["no_mirror_reason"] == "Windows 전용 스텝"
        assert decision.event_fields["mirror_outcome"] == "bypass"
        assert decision.event_fields["mirror_state"] == state
        assert any("Windows 전용 스텝" in n for n in decision.notices)

    @pytest.mark.parametrize("state", [_PASS, _NOTEXEC, _UNAVAIL])
    def test_reason_on_unblocked_state_is_recorded_but_flagged_unnecessary(self, state: str):
        """거부 대상이 아닌 상태에 사유를 주면 기록은 하되 우회로 세지 않는다."""
        decision = gate.decide(scope="pr", mode="block", state=state, no_mirror_reason="사유")
        assert decision.outcome != "bypass"
        assert decision.note == "사유"
        assert decision.event_fields["no_mirror_reason"] == "사유"
        assert decision.event_fields["mirror_outcome"] != "bypass"
        assert any("필요하지 않았다" in n for n in decision.notices)

    @pytest.mark.parametrize("scope", ["no_pr", "human"])
    def test_reason_on_exempt_scope_is_recorded(self, scope: str):
        decision = gate.decide(scope=scope, mode="block", state=None, no_mirror_reason="사유")
        assert decision.outcome == "exempt" and decision.note == "사유"
        assert decision.event_fields == {"mirror_scope": scope, "no_mirror_reason": "사유"}

    def test_reason_is_stripped_before_recording(self):
        decision = gate.decide(scope="pr", mode="block", state=_FAIL, no_mirror_reason="  사유  ")
        assert decision.note == "사유"
        assert decision.event_fields["no_mirror_reason"] == "사유"

    def test_block_rejection_is_state_scoped_not_mode_scoped(self):
        """warn 정책에서는 같은 상태(fail·unknown)가 거부되지 않는다 — 정책 스위치의 변별력."""
        for state in (_FAIL, _UNKNOWN):
            assert gate.decide(scope="pr", mode="warn", state=state).outcome == "warn"
            assert gate.decide(scope="pr", mode="block", state=state).outcome == "reject"

    def test_unknown_state_string_folds_to_strict_not_to_pass(self):
        """모르는 상태 문자열은 pass로 접히지 않는다 — unknown으로 취급해 block이 거부한다."""
        decision = gate.decide(scope="pr", mode="block", state="처음 보는 값")
        assert decision.rejected
        decision = gate.decide(scope="pr", mode="warn", state=None)
        assert decision.event_fields["mirror_state"] == "unknown"

    def test_unknown_mode_string_folds_to_block(self):
        assert gate.decide(scope="pr", mode="off", state=_FAIL).rejected
        assert gate.decide(scope="pr", mode="", state=_UNKNOWN).rejected

    def test_reject_carries_prescription_and_writes_nothing(self):
        lookup = gate.MirrorLookup(_UNKNOWN, "CI 미러 결과 없음(x.json)", "a" * 40)
        decision = gate.decide(scope="pr", mode="block", state=_UNKNOWN, lookup=lookup)
        msg = decision.reject_message or ""
        assert "ci_mirror.py run" in msg and "--no-mirror" in msg
        assert "CI 미러 결과 없음(x.json)" in msg
        assert "측정되지 않았다" in msg and "실패했다" not in msg
        assert "대장에는 아무것도 쓰지 않았습니다" in msg
        assert decision.event_fields == {} and decision.note is None

    def test_fail_reject_message_says_failed_not_unmeasured(self):
        lookup = gate.MirrorLookup(_FAIL, "CI 미러가 실패로 끝났다(잡: j)", "a" * 40)
        msg = gate.decide(scope="pr", mode="block", state=_FAIL, lookup=lookup).reject_message
        assert msg is not None and "실패했다" in msg and "측정되지 않았다" not in msg

    def test_event_fields_for_pr_scope(self):
        lookup = gate.MirrorLookup(_PASS, "통과", "c" * 40)
        fields = gate.decide(scope="pr", mode="block", state=_PASS, lookup=lookup).event_fields
        assert fields == {
            "mirror_scope": "pr",
            "mirror_gate_mode": "block",
            "mirror_state": "pass",
            "mirror_commit": "c" * 40,
            "mirror_outcome": "pass",
        }

    def test_unavailable_has_no_commit_field_and_is_not_pass(self):
        """조회 실패는 커밋을 모르므로 필드가 없고, 상태는 unavailable이지 pass가 아니다."""
        lookup = gate.MirrorLookup(_UNAVAIL, "확인 못함", None, "OSError")
        fields = gate.decide(scope="pr", mode="block", state=_UNAVAIL, lookup=lookup).event_fields
        assert "mirror_commit" not in fields
        assert fields["mirror_state"] == "unavailable"
        assert fields["mirror_outcome"] == "warn"

    def test_block_with_unavailable_explains_fail_open(self):
        decision = gate.decide(scope="pr", mode="block", state=_UNAVAIL)
        assert any("fail-open" in n and "통과로 세지 않는다" in n for n in decision.notices)
        assert not gate.decide(scope="pr", mode="warn", state=_UNAVAIL).notices

    def test_warn_legacy_flag_matches_outcome(self):
        """종전 경고를 내야 하는 결과(warn·exempt)와 조용해야 하는 결과(pass·bypass)를 가른다."""
        for cell, outcome in _TABLE_NO_MIRROR.items():
            scope, mode, state = cell
            decision = gate.decide(scope=scope, mode=mode, state=state)
            assert decision.warn_legacy is (outcome in ("warn", "exempt")), cell


# ── 정책 값 해석 ─────────────────────────────────────────────────────────────


class TestModeResolution:
    def test_valid_value_without_errors_is_used_as_is(self):
        assert gate.resolve_mode("warn", []).mode == "warn"
        assert gate.resolve_mode("block", []).mode == "block"
        assert not gate.resolve_mode("warn", []).fail_closed

    def test_any_policy_error_folds_to_block(self):
        """오류가 하나라도 있으면 값을 믿지 않는다 — 오타가 조용히 warn으로 떨어지지 않는다."""
        resolution = gate.resolve_mode("warn", ["policy.yaml: 미지 필드 ['ci_mirror_at_dne']"])
        assert resolution.mode == "block" and resolution.fail_closed
        assert "ci_mirror_at_dne" in resolution.errors[0]

    def test_unregistered_value_folds_to_block_even_without_reported_errors(self):
        assert gate.resolve_mode("strict", []).mode == "block"

    def test_reject_message_names_the_policy_problem(self):
        resolution = gate.resolve_mode("warn", ["policy.yaml: 미지 필드 ['x']"])
        decision = gate.decide(
            scope="pr", mode=resolution.mode, state=_UNKNOWN, mode_errors=resolution.errors
        )
        assert decision.rejected
        assert "정책 값을 확정하지 못해 block으로 취급" in (decision.reject_message or "")
        assert "미지 필드" in (decision.reject_message or "")


# ── 미러 조회 ────────────────────────────────────────────────────────────────


class TestLookupStates:
    @pytest.mark.parametrize(
        ("kind", "expected"),
        [
            ("pass", "pass"),
            ("not_executed", "not_executed"),
            ("fail", "fail"),
            ("absent", "unknown"),
            ("other_commit", "unknown"),
            ("corrupt", "unknown"),
            ("zero_jobs", "unknown"),
        ],
    )
    def test_each_fixture_maps_to_its_state(self, git_repo: Path, kind: str, expected: str):
        _write_mirror(git_repo, kind)
        lookup = gate.lookup_mirror(git_repo)
        assert lookup.state == expected, lookup
        assert lookup.commit == _git(git_repo, "rev-parse", "HEAD")
        assert lookup.error_type is None

    def test_state_names_are_ci_mirror_verdict_constants(self):
        """상태 문자열이 `ci_mirror.VERDICT_*`와 같다 — 한쪽만 바뀌면 조회가 조용히 unknown으로 샌다."""
        m = _mirror()
        assert gate.STATE_PASS == m.VERDICT_PASS
        assert gate.STATE_NOT_EXECUTED == m.VERDICT_NOT_EXECUTED
        assert gate.STATE_FAIL == m.VERDICT_FAIL
        assert gate.STATE_UNKNOWN == m.VERDICT_UNKNOWN

    @pytest.mark.parametrize(
        "boom",
        [OSError("디스크"), subprocess.SubprocessError("git"), subprocess.TimeoutExpired("g", 1)],
    )
    def test_lookup_failure_is_unavailable_with_type_name(
        self, git_repo: Path, monkeypatch, boom: Exception
    ):
        """조회 실패는 pass가 아니다 — 상태 unavailable + 예외 타입명(침묵 실패 금지)."""
        m = _mirror()

        def _raise(root):
            raise boom

        monkeypatch.setattr(m, "current_commit", _raise)
        lookup = gate.lookup_mirror(git_repo)
        assert lookup.state == "unavailable"
        assert lookup.error_type == type(boom).__name__
        assert type(boom).__name__ in lookup.reason
        assert lookup.commit is None

    def test_missing_module_is_unavailable(self, git_repo: Path, monkeypatch):
        """미러 모듈이 없는 환경 — ImportError도 unavailable이다(done을 죽이지 않는다)."""
        monkeypatch.setitem(sys.modules, "ci_mirror", None)
        lookup = gate.lookup_mirror(git_repo)
        # sys.modules[..] = None 의 import 실패는 ImportError의 하위 클래스인 ModuleNotFoundError다.
        assert lookup.state == "unavailable" and lookup.error_type == "ModuleNotFoundError"

    def test_unrecognized_verdict_state_is_unknown_not_pass(self, git_repo: Path, monkeypatch):
        m = _mirror()
        monkeypatch.setattr(m, "mirror_verdict", lambda path, commit: m.Verdict("weird", "이유"))
        lookup = gate.lookup_mirror(git_repo)
        assert lookup.state == "unknown" and "weird" in lookup.reason

    @pytest.mark.parametrize("kind", ["pass", "not_executed", "fail", "absent", "other_commit"])
    def test_lookup_agrees_with_the_legacy_warning(self, git_repo: Path, capsys, kind: str):
        """게이트 조회와 종전 경고 헬퍼가 같은 사실을 본다 — 조회 코드가 두 벌이라 어긋남을 동결한다."""
        _write_mirror(git_repo, kind)
        capsys.readouterr()
        cli._warn_if_ci_mirror_missing(git_repo)
        err = capsys.readouterr().err
        state = gate.lookup_mirror(git_repo).state
        assert (err == "") is (state == "pass"), (kind, state, err)
        if state == "not_executed":
            assert "돌지 않은 검사" in err
        if state == "fail":
            assert "실패" in err


class TestJudgeScopeShortCircuit:
    def test_exempt_scope_never_touches_lookup_or_policy(self, monkeypatch, tmp_path: Path):
        """미러 대상이 아닌 경로는 조회조차 하지 않는다 — 깨진 정책·미러 모듈 부재가 이 경로를 막지 않는다."""

        def _forbidden(*a, **k):
            raise AssertionError("면제 경로가 조회를 불렀다")

        monkeypatch.setattr(gate, "lookup_mirror", _forbidden)
        monkeypatch.setattr(gate, "load_mode", _forbidden)
        for owner, no_pr in (("claude", "investigation"), ("kiki", None), ("kiki", "ci-red")):
            decision = gate.judge(tmp_path, owner=owner, no_pr_reason=no_pr, no_mirror_reason=None)
            assert decision.outcome == "exempt"

    def test_pr_scope_does_consult_lookup_and_policy(self, monkeypatch, tmp_path: Path):
        """대조군 — PR 경로는 조회한다(면제 판정이 전 경로에 번지는 과잉 수정을 잡는다)."""
        calls: list[str] = []

        def _lookup(root):
            calls.append("lookup")
            return gate.MirrorLookup("fail", "실패", "a" * 40)

        def _mode(root):
            calls.append("mode")
            return gate.ModeResolution("block")

        monkeypatch.setattr(gate, "lookup_mirror", _lookup)
        monkeypatch.setattr(gate, "load_mode", _mode)
        decision = gate.judge(tmp_path, owner="claude", no_pr_reason=None, no_mirror_reason=None)
        assert decision.rejected and sorted(calls) == ["lookup", "mode"]

    def test_blank_reason_is_rejected_before_lookup(self, monkeypatch, tmp_path: Path):
        def _forbidden(*a, **k):
            raise AssertionError("무사유 면제를 조회 뒤에야 거부했다")

        monkeypatch.setattr(gate, "lookup_mirror", _forbidden)
        decision = gate.judge(tmp_path, owner="claude", no_pr_reason=None, no_mirror_reason=" ")
        assert decision.rejected


# ── done CLI 종단 ────────────────────────────────────────────────────────────


class TestDoneBlocksUnknownAndFail:
    @pytest.mark.parametrize("kind", ["absent", "other_commit", "corrupt", "zero_jobs", "fail"])
    def test_block_rejects_and_leaves_ledger_byte_identical(
        self, seeded_repo: Path, capsys, kind: str
    ):
        """unknown 4원인(결과 없음·다른 커밋·깨짐·잡 0건)과 fail — 전부 exit 1이고 대장 무변경."""
        task_id = _claimed_task(capsys)
        _set_policy(seeded_repo, "block")
        _write_mirror(seeded_repo, kind)
        before = _snapshot(seeded_repo)
        assert cli.main(["done", task_id, *_PR]) == 1
        err = capsys.readouterr().err
        assert "CI 미러 게이트(ci_mirror_at_done=block)" in err
        assert "ci_mirror.py run" in err and "--no-mirror" in err
        assert _snapshot(seeded_repo) == before, "거부했는데 대장이 바뀌었다(반쪽 적용)"
        backlog, _ = store.load_backlog(seeded_repo)
        assert backlog.tasks[task_id].status == "in_progress"

    def test_fail_message_differs_from_unknown_message(self, seeded_repo: Path, capsys):
        task_id = _claimed_task(capsys)
        _set_policy(seeded_repo, "block")
        _write_mirror(seeded_repo, "fail")
        assert cli.main(["done", task_id, *_PR]) == 1
        assert "실패했다" in capsys.readouterr().err
        _write_mirror(seeded_repo, "absent")
        assert cli.main(["done", task_id, *_PR]) == 1
        assert "측정되지 않았다" in capsys.readouterr().err

    def test_rejected_done_can_be_retried_after_reproducing(self, seeded_repo: Path, capsys):
        """거부는 볼모가 아니다 — 재현 결과를 남기면 같은 명령이 통과한다."""
        task_id = _claimed_task(capsys)
        _set_policy(seeded_repo, "block")
        assert cli.main(["done", task_id, *_PR]) == 1
        capsys.readouterr()
        _write_mirror(seeded_repo, "pass")
        assert cli.main(["done", task_id, *_PR]) == 0
        backlog, _ = store.load_backlog(seeded_repo)
        assert backlog.tasks[task_id].status == "done"


class TestDoneAllowsPassAndNotExecuted:
    def test_pass_is_silent_and_recorded(self, seeded_repo: Path, capsys):
        task_id = _claimed_task(capsys)
        _set_policy(seeded_repo, "block")
        _write_mirror(seeded_repo, "pass")
        assert cli.main(["done", task_id, *_PR]) == 0
        assert "⚠" not in capsys.readouterr().err, "통과에 경고가 붙으면 습관화된다"
        (event,) = _done_events(seeded_repo, task_id)
        assert event["mirror_scope"] == "pr" and event["mirror_state"] == "pass"
        assert event["mirror_gate_mode"] == "block" and event["mirror_outcome"] == "pass"
        assert event["mirror_commit"] == _git(seeded_repo, "rev-parse", "HEAD")

    def test_not_executed_is_allowed_with_warning_under_block(self, seeded_repo: Path, capsys):
        """미실행은 block에서도 거부하지 않는다(HARN-181 전까지 조건 스텝 잡은 항상 exit 3)."""
        task_id = _claimed_task(capsys)
        _set_policy(seeded_repo, "block")
        _write_mirror(seeded_repo, "not_executed")
        assert cli.main(["done", task_id, *_PR]) == 0
        err = capsys.readouterr().err
        assert "돌지 않은 검사" in err and "조건 게이트" in err, "통과로도 침묵으로도 접지 않는다"
        (event,) = _done_events(seeded_repo, task_id)
        assert event["mirror_state"] == "not_executed" and event["mirror_outcome"] == "warn"


class TestWarnPolicyKeepsLegacyBehavior:
    @pytest.mark.parametrize("kind", ["absent", "fail", "other_commit"])
    def test_explicit_warn_never_rejects(self, seeded_repo: Path, capsys, kind: str):
        task_id = _claimed_task(capsys)
        _set_policy(seeded_repo, "warn")
        _write_mirror(seeded_repo, kind)
        assert cli.main(["done", task_id, *_PR]) == 0
        err = capsys.readouterr().err
        assert "재현한 뒤" in err or "실패" in err, "종전 경고가 그대로 나야 한다"
        assert "CI 미러 게이트" not in err
        (event,) = _done_events(seeded_repo, task_id)
        assert event["mirror_gate_mode"] == "warn"

    def test_missing_key_behaves_as_warn(self, seeded_repo: Path, capsys):
        """키가 없는 policy.yaml(승격 이전 저장소) — 기존 done 흐름이 그대로 통과한다."""
        task_id = _claimed_task(capsys)
        _set_policy(seeded_repo, None)
        assert cli.main(["done", task_id, *_PR]) == 0
        (event,) = _done_events(seeded_repo, task_id)
        assert event["mirror_gate_mode"] == "warn" and event["mirror_state"] == "unknown"

    def test_no_policy_file_behaves_as_warn(self, seeded_repo: Path, capsys):
        task_id = _claimed_task(capsys)
        (seeded_repo / "backlog" / "policy.yaml").unlink(missing_ok=True)
        assert cli.main(["done", task_id, *_PR]) == 0


class TestExemptPaths:
    def test_no_pr_path_is_not_asked_for_a_mirror(self, seeded_repo: Path, capsys):
        """`--no-pr investigation` done은 block 정책에서도 통과한다.

        이 면제 절이 없으면 산출물 없는 조사 세션이 미러 부재로 막힌다(미러는 코드 변경을
        재현하는 도구다).
        """
        task_id = _claimed_task(capsys)
        _set_policy(seeded_repo, "block")
        _write_mirror(seeded_repo, "absent")
        assert (
            cli.main(["done", task_id, "--artifact", "조사 문서", "--no-pr", "investigation"]) == 0
        )
        err = capsys.readouterr().err
        assert "CI 미러 게이트" not in err
        assert "CI 미러 결과 없음" in err, "종전 경고는 그대로 난다(경고조차 새로 만들지 않는다)"
        (event,) = _done_events(seeded_repo, task_id)
        assert event["mirror_scope"] == "no_pr"
        assert "mirror_state" not in event, "면제 경로에 미러 상태를 기록하면 감시 지표가 오염된다"
        assert "ci_reach_status" not in event

    @pytest.mark.parametrize("reason", ["incomplete", "ci-red", "kiki-hold"])
    def test_every_no_pr_reason_is_exempt(self, seeded_repo: Path, capsys, reason: str):
        task_id = _claimed_task(capsys)
        _set_policy(seeded_repo, "block")
        assert cli.main(["done", task_id, "--artifact", "커밋", "--no-pr", reason]) == 0

    def test_human_owned_done_is_not_asked_for_a_mirror(self, seeded_repo: Path, capsys):
        """`--as kiki` done은 block 정책에서도 통과한다 — 사람 판정 기입은 미러 대상이 아니다."""
        task_id = _human_task(capsys)
        _set_policy(seeded_repo, "block")
        _write_mirror(seeded_repo, "absent")
        assert cli.main(["done", task_id, "--as", "kiki", *_PR]) == 0
        assert "CI 미러 게이트" not in capsys.readouterr().err
        (event,) = _done_events(seeded_repo, task_id)
        assert event["mirror_scope"] == "human" and "mirror_state" not in event

    def test_pr_scope_control_is_still_blocked(self, seeded_repo: Path, capsys):
        """대조군 — 같은 저장소·같은 정책·같은 결과 부재에서 PR 경로 claude done은 막힌다."""
        task_id = _claimed_task(capsys)
        _set_policy(seeded_repo, "block")
        _write_mirror(seeded_repo, "absent")
        assert cli.main(["done", task_id, *_PR]) == 1


class TestNoMirrorEscapeHatch:
    def test_reason_passes_and_is_recorded_in_notes_and_event(self, seeded_repo: Path, capsys):
        task_id = _claimed_task(capsys)
        original_notes = store.load_backlog(seeded_repo)[0].tasks[task_id].notes
        _set_policy(seeded_repo, "block")
        _write_mirror(seeded_repo, "absent")
        reason = "Windows 전용 PowerShell 스텝은 이 환경에서 못 돈다"
        assert cli.main(["done", task_id, *_PR, "--no-mirror", reason]) == 0
        err = capsys.readouterr().err
        assert "--no-mirror로 CI 미러 게이트를 우회한다" in err and reason in err
        assert "재현한 뒤" not in err, "우회한 done에 재현 처방을 또 내면 사유가 무시된 것이다"
        backlog, _ = store.load_backlog(seeded_repo)
        task = backlog.tasks[task_id]
        assert task.status == "done"
        assert "[미러 면제 " in task.notes and reason in task.notes
        if original_notes.strip():
            assert original_notes in task.notes, "원 notes를 덮어쓰면 안 된다(HARN-20)"
        (event,) = _done_events(seeded_repo, task_id)
        assert event["no_mirror_reason"] == reason
        assert event["mirror_outcome"] == "bypass" and event["mirror_state"] == "unknown"

    @pytest.mark.parametrize("blank", ["", "   ", "\t"])
    @pytest.mark.parametrize("kind", ["absent", "pass"])
    def test_blank_reason_is_rejected_and_writes_nothing(
        self, seeded_repo: Path, capsys, blank: str, kind: str
    ):
        """무사유 면제 없음 — 미러가 통과 상태여도(사유 검증은 상태와 무관) 공백 사유는 거부한다."""
        task_id = _claimed_task(capsys)
        _set_policy(seeded_repo, "block")
        _write_mirror(seeded_repo, kind)
        before = _snapshot(seeded_repo)
        assert cli.main(["done", task_id, *_PR, "--no-mirror", blank]) == 1
        assert "무사유 면제는 없다" in capsys.readouterr().err
        assert _snapshot(seeded_repo) == before

    def test_blank_reason_is_rejected_under_warn_policy_too(self, seeded_repo: Path, capsys):
        task_id = _claimed_task(capsys)
        _set_policy(seeded_repo, "warn")
        assert cli.main(["done", task_id, *_PR, "--no-mirror", " "]) == 1

    def test_blank_reason_is_rejected_on_exempt_path_too(self, seeded_repo: Path, capsys):
        task_id = _claimed_task(capsys)
        _set_policy(seeded_repo, "block")
        assert (
            cli.main(
                ["done", task_id, "--artifact", "x", "--no-pr", "investigation", "--no-mirror", " "]
            )
            == 1
        )

    def test_reason_does_not_rescue_a_different_task(self, seeded_repo: Path, capsys):
        """사유는 그 done 호출 1회에만 유효하다 — 다음 done은 다시 막힌다(상태 저장 없음)."""
        first = _claimed_task(capsys)
        _set_policy(seeded_repo, "block")
        assert cli.main(["done", first, *_PR, "--no-mirror", "사유"]) == 0
        capsys.readouterr()
        second = _claimed_task(capsys)
        assert cli.main(["done", second, *_PR]) == 1


class TestLookupFailureFailsOpen:
    def test_unavailable_passes_with_warning_and_is_recorded_as_unavailable(
        self, seeded_repo: Path, capsys, monkeypatch
    ):
        """조회 자체가 실패한 환경 — block에서도 경고 후 통과(fail-open), 상태는 unavailable."""
        task_id = _claimed_task(capsys)
        _set_policy(seeded_repo, "block")

        def _raise(root):
            raise OSError("git 없음")

        monkeypatch.setattr(_mirror(), "current_commit", _raise)
        assert cli.main(["done", task_id, *_PR]) == 0
        err = capsys.readouterr().err
        assert "OSError" in err, "예외 타입명이 없는 경고는 침묵 실패다"
        assert "통과로 세지 않는다" in err
        (event,) = _done_events(seeded_repo, task_id)
        assert event["mirror_state"] == "unavailable"
        assert event["mirror_state"] != "pass"
        assert "mirror_commit" not in event

    def test_missing_module_does_not_kill_done(self, seeded_repo: Path, capsys, monkeypatch):
        task_id = _claimed_task(capsys)
        _set_policy(seeded_repo, "block")
        monkeypatch.setitem(sys.modules, "ci_mirror", None)
        assert cli.main(["done", task_id, *_PR]) == 0
        assert "ModuleNotFoundError" in capsys.readouterr().err


class TestBrokenPolicyFailsClosed:
    def test_unregistered_value_blocks_and_names_the_problem(self, seeded_repo: Path, capsys):
        task_id = _claimed_task(capsys)
        (seeded_repo / "backlog" / "policy.yaml").write_text(
            "ci_mirror_at_done: strict\n", encoding="utf-8"
        )
        before = _snapshot(seeded_repo)
        assert cli.main(["done", task_id, *_PR]) == 1
        err = capsys.readouterr().err
        assert "정책 값을 확정하지 못해 block으로 취급" in err and "strict" in err
        assert _snapshot(seeded_repo) == before

    def test_typoed_key_does_not_silently_fall_back_to_warn(self, seeded_repo: Path, capsys):
        """승격했다고 믿는 정책이 오타로 조용히 꺼지는 상태 — 오타 키는 미지 필드 오류이고 값은 warn 기본값이다."""
        task_id = _claimed_task(capsys)
        (seeded_repo / "backlog" / "policy.yaml").write_text(
            "ci_mirror_at_dne: block\n", encoding="utf-8"
        )
        assert cli.main(["done", task_id, *_PR]) == 1
        assert "미지 필드" in capsys.readouterr().err

    def test_yaml_syntax_error_blocks_instead_of_crashing(self, seeded_repo: Path, capsys):
        task_id = _claimed_task(capsys)
        (seeded_repo / "backlog" / "policy.yaml").write_text(
            "ci_mirror_at_done: [block\n", encoding="utf-8"
        )
        assert cli.main(["done", task_id, *_PR]) == 1
        err = capsys.readouterr().err
        assert "policy.yaml 읽기 실패(ParserError)" in err, "예외 타입명이 없는 경고는 침묵 실패다"

    def test_broken_policy_does_not_block_exempt_paths(self, seeded_repo: Path, capsys):
        """깨진 정책이 미러 대상이 아닌 경로까지 막지는 않는다(정책을 읽지 않는다).

        값이 미등록인 정책으로 검증한다. YAML 문법 오류 정책은 done 끝의 원격 claim 해제
        (`_release_remote_claim`)가 정책을 따로 읽다 죽는 별건이라 이 시험의 대상이 아니다.
        """
        task_id = _claimed_task(capsys)
        (seeded_repo / "backlog" / "policy.yaml").write_text(
            "ci_mirror_at_done: strict\n", encoding="utf-8"
        )
        assert cli.main(["done", task_id, "--artifact", "x", "--no-pr", "investigation"]) == 0

    def test_no_mirror_reason_rescues_under_broken_policy(self, seeded_repo: Path, capsys):
        """출구는 있다 — 정책이 깨져도 사유를 적으면 통과하고 사유가 남는다."""
        task_id = _claimed_task(capsys)
        (seeded_repo / "backlog" / "policy.yaml").write_text(
            "ci_mirror_at_done: strict\n", encoding="utf-8"
        )
        assert cli.main(["done", task_id, *_PR, "--no-mirror", "정책 수리 전 임시"]) == 0


# ── CI 도달 잡 안내 (acceptance ⑤) ────────────────────────────────────────────


def _with_workflow_and_change(repo: Path, changed: str) -> None:
    """실제 ci.yml을 옮기고 origin/main 기준선을 만든 뒤, 변경 파일 1개를 커밋한다."""
    wf = repo / ".github" / "workflows"
    wf.mkdir(parents=True)
    shutil.copy(_REAL_CI, wf / "ci.yml")
    _git(repo, "add", ".github")
    _git(repo, "commit", "-m", "워크플로")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    target = repo / changed
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# 변경\n", encoding="utf-8")
    _git(repo, "add", changed)
    _git(repo, "commit", "-m", "변경")


class TestCiReach:
    def test_backend_test_file_reaches_backend_migrations(self, seeded_repo: Path, capsys):
        """변별력 — `tests/backend/` 파일 1개를 바꾸면 `backend-migrations`가 도달 목록에 나온다.

        (CI의 `integration` 마커 통합 테스트는 이 잡이 돌린다. 도달은 마커가 아니라 경로
        필터가 정하므로, 통합 테스트 파일이 사는 `tests/backend/`가 그 잡을 깨운다.)
        """
        task_id = _claimed_task(capsys)
        _with_workflow_and_change(seeded_repo, "tests/backend/api/test_marker_integration.py")
        assert cli.main(["done", task_id, *_PR]) == 0
        out = capsys.readouterr().out
        line = next(ln for ln in out.splitlines() if ln.startswith("ℹ CI 도달 잡"))
        assert "backend-migrations" in line and "변경 1건" in line
        (event,) = _done_events(seeded_repo, task_id)
        assert event["ci_reach_status"] == "computed" and event["ci_reach_changed"] == 1
        assert "backend-migrations" in event["ci_reach_jobs"]
        assert "harness-integrity" in event["ci_reach_jobs"], "상시 잡도 빠지지 않는다"

    def test_docs_only_change_does_not_reach_backend_migrations(self, seeded_repo: Path, capsys):
        """대조군 — 문서 변경은 그 잡을 깨우지 않는다(항상 '전부 나열'하는 과잉 수정을 잡는다)."""
        task_id = _claimed_task(capsys)
        _with_workflow_and_change(seeded_repo, "docs/reviews/x.md")
        assert cli.main(["done", task_id, *_PR]) == 0
        (event,) = _done_events(seeded_repo, task_id)
        assert "backend-migrations" not in event["ci_reach_jobs"]
        assert "harness-integrity" in event["ci_reach_jobs"]

    def test_single_line_only(self, seeded_repo: Path, capsys):
        task_id = _claimed_task(capsys)
        _with_workflow_and_change(seeded_repo, "docs/reviews/x.md")
        assert cli.main(["done", task_id, *_PR]) == 0
        lines = [ln for ln in capsys.readouterr().out.splitlines() if "CI 도달" in ln]
        assert len(lines) == 1

    def test_computation_failure_warns_with_type_and_does_not_block(
        self, seeded_repo: Path, capsys
    ):
        """워크플로는 있는데 트렁크 기준선(origin/main)이 없다 — done을 막지 않고 타입명을 남긴다."""
        task_id = _claimed_task(capsys)
        wf = seeded_repo / ".github" / "workflows"
        wf.mkdir(parents=True)
        shutil.copy(_REAL_CI, wf / "ci.yml")
        assert cli.main(["done", task_id, *_PR]) == 0
        captured = capsys.readouterr()
        assert "CI 도달 잡을 계산하지 못했다(RuntimeError)" in captured.err
        assert "CI 도달 잡(" not in captured.out
        (event,) = _done_events(seeded_repo, task_id)
        assert event["ci_reach_status"] == "failed" and event["ci_reach_error"] == "RuntimeError"
        assert "ci_reach_jobs" not in event

    def test_no_workflow_is_not_an_error(self, seeded_repo: Path, capsys):
        """CI가 없는 저장소는 오류가 아니다 — 안내도 경고도 없고 상태만 no_workflow로 남는다."""
        task_id = _claimed_task(capsys)
        assert cli.main(["done", task_id, *_PR]) == 0
        captured = capsys.readouterr()
        assert "CI 도달" not in captured.out and "CI 도달" not in captured.err
        (event,) = _done_events(seeded_repo, task_id)
        assert event["ci_reach_status"] == "no_workflow"

    def test_zero_changed_files_says_it_is_meaningless(self, seeded_repo: Path, capsys):
        task_id = _claimed_task(capsys)
        wf = seeded_repo / ".github" / "workflows"
        wf.mkdir(parents=True)
        shutil.copy(_REAL_CI, wf / "ci.yml")
        _git(seeded_repo, "add", ".github")
        _git(seeded_repo, "commit", "-m", "워크플로")
        _git(seeded_repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        assert cli.main(["done", task_id, *_PR]) == 0
        assert "변경 0건" in capsys.readouterr().out

    def test_does_not_apply_to_exempt_paths(self, seeded_repo: Path, capsys):
        task_id = _claimed_task(capsys)
        _with_workflow_and_change(seeded_repo, "docs/reviews/x.md")
        assert cli.main(["done", task_id, "--artifact", "x", "--no-pr", "investigation"]) == 0
        assert "CI 도달" not in capsys.readouterr().out


# ── 사후 감시 — policy report ────────────────────────────────────────────────


def _event(**extra) -> dict:
    return {"action": "done", "id": "T-1", **extra}


class TestSummary:
    def test_counts_states_separately_and_never_merges_unavailable_into_pass(self):
        events = [
            _event(mirror_scope="pr", mirror_state="pass"),
            _event(mirror_scope="pr", mirror_state="pass"),
            _event(mirror_scope="pr", mirror_state="unavailable"),
            _event(
                mirror_scope="pr",
                mirror_state="unknown",
                no_mirror_reason="사유",
                mirror_outcome="bypass",
            ),
            _event(mirror_scope="pr", mirror_state="fail"),
            _event(mirror_scope="no_pr"),
            _event(mirror_scope="human", no_mirror_reason="불필요 사유"),
            _event(),  # HARN-173 이전 기록
            {"action": "start", "id": "T-1"},  # done이 아닌 이벤트는 무시
        ]
        s = gate.summarize_done_events(events)
        assert s.total_done == 8 and s.untracked == 1
        assert s.pr_by_state == {"pass": 2, "unavailable": 1, "unknown": 1, "fail": 1}
        assert s.by_scope == {"pr": 5, "no_pr": 1, "human": 1}
        assert s.no_mirror_used == 2 and s.bypassed == 1

    def test_unrecognized_state_is_counted_as_unclassified_not_folded(self):
        s = gate.summarize_done_events([_event(mirror_scope="pr", mirror_state="???")])
        assert s.pr_by_state == {"미분류": 1}

    def test_missing_state_on_pr_scope_is_unclassified(self):
        s = gate.summarize_done_events([_event(mirror_scope="pr")])
        assert s.pr_by_state == {"미분류": 1}

    def test_collect_applies_the_window_reads_both_ledgers_and_counts_unreadable(
        self, tmp_path: Path
    ):
        """최근 N일 창 · 레거시+샤드 합집합 · 판독 불가 줄을 조용히 버리지 않는다."""
        now = datetime.now().astimezone()
        recent = now.isoformat(timespec="seconds")
        old = (now - timedelta(days=30)).isoformat(timespec="seconds")
        shard_dir = tmp_path / "backlog" / "events"
        shard_dir.mkdir(parents=True)
        shard_lines = [
            json.dumps({"ts": recent, "action": "done", "id": "A", "mirror_scope": "pr"}),
            json.dumps({"ts": old, "action": "done", "id": "OLD"}),
            json.dumps({"ts": recent, "action": "start", "id": "S"}),
            "{깨진 줄",
            json.dumps({"ts": "잘못된 시각", "action": "done", "id": "BADTS"}),
            json.dumps([1, 2]),
        ]
        (shard_dir / "x.ndjson").write_text("\n".join(shard_lines) + "\n", encoding="utf-8")
        legacy = json.dumps({"ts": recent, "action": "done", "id": "LEGACY"})
        (tmp_path / "backlog" / "events.ndjson").write_text(legacy + "\n", encoding="utf-8")
        events, unreadable = gate.collect_done_events(tmp_path, 14)
        assert sorted(e["id"] for e in events) == ["A", "LEGACY"], "창 밖·done 아님이 섞였다"
        assert unreadable == 3, "깨진 JSON·잘못된 ts·이벤트 아닌 JSON 3건을 세야 한다"

    def test_render_states_the_rejection_blind_spot(self):
        lines = gate.render_summary(gate.MirrorSummary(), 14)
        text = "\n".join(lines)
        assert "거부된 done은 대장에 남지 않아" in text
        assert "unavailable" in text and "측정 실패" in text

    def test_render_reports_unreadable_lines(self):
        s = gate.MirrorSummary(total_done=1, unreadable_lines=3)
        assert "판독 불가 줄 3건" in "\n".join(gate.render_summary(s, 14))

    def test_policy_report_prints_the_section_from_real_events(self, seeded_repo: Path, capsys):
        """종단 — 실제 done 3건(통과·조회 실패·우회)이 `policy report`에 상태별로 나온다."""
        _set_policy(seeded_repo, "block")
        first = _claimed_task(capsys)
        _write_mirror(seeded_repo, "pass")
        assert cli.main(["done", first, *_PR]) == 0
        capsys.readouterr()
        second = _claimed_task(capsys)
        _write_mirror(seeded_repo, "absent")
        assert cli.main(["done", second, *_PR, "--no-mirror", "환경 제약"]) == 0
        capsys.readouterr()
        assert cli.main(["policy", "report"]) == 0
        out = capsys.readouterr().out
        assert "done CI 미러 게이트 (HARN-173)" in out
        assert "pass 1" in out and "unknown 1" in out
        assert "--no-mirror 사용 1건(우회 성립 1건)" in out


# ── 배선 실재 — 정본화와 집행 지점의 분리 ─────────────────────────────────────


def _done_body() -> str:
    source = _BACKLOG_CLI.read_text(encoding="utf-8")
    return source.split("def cmd_done(", 1)[1].split("\ndef ", 1)[0]


class TestWiring:
    def test_done_calls_the_gate_before_any_write(self):
        """판정 지점이 상태 전이·대장 쓰기보다 앞선다 — 거부가 반쪽 적용을 남기지 않는다."""
        body = _done_body()
        judge_at = body.index("done_mirror_gate.judge(")
        for write in ('task.status = "done"', "store.save_task(root, task)", "store.append_event("):
            assert judge_at < body.index(write), f"게이트가 {write} 뒤에 있다"

    def test_done_records_gate_fields_in_the_event(self):
        body = _done_body()
        assert "done_extra.update(mirror_decision.event_fields)" in body
        assert "done_extra.update(ci_reach.event_fields)" in body

    def test_done_appends_the_bypass_reason_to_notes(self):
        assert "_append_note(task.notes, mirror_decision.note" in _done_body()

    def test_legacy_warning_is_still_wired_and_stays_warn_only(self):
        """종전 경고 헬퍼는 그대로 호출되고(infra 계약), 거부 판정은 그 안에 없다."""
        assert "_warn_if_ci_mirror_missing(root)" in _done_body()
        source = _BACKLOG_CLI.read_text(encoding="utf-8")
        helper = source.split("def _warn_if_ci_mirror_missing(", 1)[1].split("\ndef ", 1)[0]
        assert "_fail(" not in helper

    def test_parser_exposes_no_mirror(self):
        parser = cli.build_parser()
        args = parser.parse_args(["done", "X-01", "--artifact", "#1", "--no-mirror", "사유"])
        assert args.no_mirror == "사유"
        args = parser.parse_args(["done", "X-01", "--artifact", "#1"])
        assert args.no_mirror is None

    def test_policy_report_calls_the_summary(self):
        source = _BACKLOG_CLI.read_text(encoding="utf-8")
        body = source.split("def cmd_policy(", 1)[1].split("\ndef ", 1)[0]
        assert "done_mirror_gate.render_report(" in body
