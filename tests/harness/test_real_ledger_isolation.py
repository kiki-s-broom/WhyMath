"""HARN-170 — 실제 저장소 루트에서 조율 정책 위반을 **일부러** 발화시켜도 실제 대장은 그대로다.

acceptance ①④: 격리 대상은 claim 유무가 아니라 check-edit의 **모든 위반 경로**다 — scope_drift
(claim 있음) · path_overlap(로컬 in-flight · 원격 claim 캐시 — claim이 없어도 난다) · adhoc_edit
(claim 없이 코드 도메인). 각 경로를 결정적으로 만들어 두고:

  (가) 위반이 **실제로 발화했는가** — `real_ledger_sink`(conftest ①)에 그 규칙이 모였는가.
       이것이 없으면 "대장이 그대로"는 아무것도 증명하지 않는다(발화하지 않은 경로에서는 원래
       아무것도 안 쓴다 — 변별력 없는 검증 스텝).
  (나) 실제 `backlog/events/` 전 파일의 바이트가 호출 전후로 같은가.

격리를 제거하는 뮤테이션(`scripts/harness/verify_real_ledger_isolation_discrimination.py`)에서
이 파일이 RED다. 그때도 실제 대장이 오염된 채 남지 않도록 (나)가 어긋나면 호출 직전 바이트로
되돌린 뒤 실패한다(되돌리는 범위 = 이 테스트가 연 창 안에서 바뀐 파일뿐).

acceptance ② 전체 실행 전후 대조는 conftest ②(`real_ledger_unchanged`)가 매 실행 집행한다 —
여기서는 그 판정 함수가 추가·삭제·변경을 실제로 구별하는지를 단위로 본다.
"""

from __future__ import annotations

import ast
import io
import json
from pathlib import Path

import _ledger_guard
import pytest
import remote_claims
import store
from models import Backlog, Policy, Task

import backlog as cli

REPO_ROOT = _ledger_guard.REPO_ROOT
PROBE_BRANCH = "claude/harn170-isolation-probe"


def _events_snapshot() -> dict[Path, bytes]:
    base = REPO_ROOT / "backlog"
    paths = [*sorted((base / "events").glob("*.ndjson"))]
    legacy = base / "events.ndjson"
    if legacy.exists():
        paths.append(legacy)
    return {path: path.read_bytes() for path in paths}


def _task(task_id: str, *, status: str, session: str | None, paths: list[str]) -> Task:
    return Task(
        id=task_id,
        title="HARN-170 격리 프로브",
        track="harness",
        stage="S1",
        subject="cross",
        layer="infra",
        status=status,
        session=session,
        paths=paths,
    )


def _probe(
    monkeypatch, capsys, sink, *, rel: str, tasks: list[Task], remote: dict[str, str]
) -> tuple[int, str]:
    """실제 저장소 루트에서 check-edit 1회 — 정책·브랜치·대장·원격 캐시를 결정적으로 고정한다."""
    backlog = Backlog(tasks={t.id: t for t in tasks})
    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setattr(store, "current_branch", lambda _root: PROBE_BRANCH)
    # 정책 파일이 나중에 off로 바뀌어도 프로브가 공허해지지 않게 전부 warn으로 고정한다.
    monkeypatch.setattr(store, "load_policy", lambda _root: (Policy(), []))
    monkeypatch.setattr(cli, "_load", lambda _root: (backlog, []))
    monkeypatch.setattr(remote_claims, "load_cache", lambda _root: dict(remote))

    before = _events_snapshot()
    payload = json.dumps({"tool_input": {"file_path": str(REPO_ROOT / rel)}})
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    try:
        code = cli.main(["check-edit"])
    finally:
        after = _events_snapshot()
        leaked = [p for p in set(before) | set(after) if before.get(p) != after.get(p)]
        for path in leaked:  # 뮤테이션 상태에서도 실제 대장을 오염된 채 두지 않는다
            if path in before:
                path.write_bytes(before[path])
            else:
                path.unlink()
    assert leaked == [], f"실제 대장에 썼다: {[p.name for p in leaked]}"
    return code, capsys.readouterr().err


def _rules(sink: list[dict]) -> set[str]:
    return {str(e.get("rule")) for e in sink if e.get("action") == "policy_warn"}


class TestEveryViolationPathIsIsolated:
    def test_scope_drift_with_a_claim(self, monkeypatch, capsys, real_ledger_sink) -> None:
        mine = _task(
            "HARN-970-probe", status="in_progress", session=PROBE_BRANCH, paths=["docs/**"]
        )
        code, err = _probe(
            monkeypatch, capsys, real_ledger_sink, rel="README.md", tasks=[mine], remote={}
        )
        assert code == 0 and "scope_drift" in err
        assert _rules(real_ledger_sink) == {"scope_drift"}

    def test_path_overlap_with_a_local_inflight_task(
        self, monkeypatch, capsys, real_ledger_sink
    ) -> None:
        mine = _task("HARN-970-probe", status="in_progress", session=PROBE_BRANCH, paths=["**"])
        other = _task(
            "HARN-971-other", status="in_progress", session="claude/other", paths=["README.md"]
        )
        _probe(
            monkeypatch, capsys, real_ledger_sink, rel="README.md", tasks=[mine, other], remote={}
        )
        assert _rules(real_ledger_sink) == {"path_overlap"}

    def test_path_overlap_from_the_remote_cache_without_any_claim(
        self, monkeypatch, capsys, real_ledger_sink
    ) -> None:
        """④ — claim이 없는 세션에서도 난다: 원격 claim 캐시의 타 세션 태스크가 경로를 덮으면."""
        other = _task(
            "HARN-971-other", status="todo", session=None, paths=["scripts/harness/backlog.py"]
        )
        _probe(
            monkeypatch,
            capsys,
            real_ledger_sink,
            rel="scripts/harness/backlog.py",
            tasks=[other],
            remote={"HARN-971-other": "claude/other"},
        )
        assert _rules(real_ledger_sink) == {"path_overlap"}

    def test_adhoc_edit_without_a_claim(self, monkeypatch, capsys, real_ledger_sink) -> None:
        _probe(
            monkeypatch,
            capsys,
            real_ledger_sink,
            rel="src/harn170_probe_nonexistent.py",
            tasks=[],
            remote={},
        )
        assert _rules(real_ledger_sink) == {"adhoc_edit"}

    def test_a_clean_edit_fires_nothing(self, monkeypatch, capsys, real_ledger_sink) -> None:
        """대조군 — 위반이 없으면 모이는 것도 없다(위 넷의 발화가 '늘 발화'가 아니다)."""
        mine = _task("HARN-970-probe", status="in_progress", session=PROBE_BRANCH, paths=["**"])
        _probe(monkeypatch, capsys, real_ledger_sink, rel="README.md", tasks=[mine], remote={})
        assert _rules(real_ledger_sink) == set()


class TestTemporaryReposStillWrite:
    def test_a_tmp_repo_event_passes_through(self, git_repo: Path, real_ledger_sink) -> None:
        """격리는 실제 루트만 막는다 — 임시 저장소를 겨눈 기록은 그대로 써져야 대장 테스트가 산다."""
        store.append_event(git_repo, "start", "S1-01-alpha")
        shards = list((git_repo / "backlog" / "events").glob("*.ndjson"))
        assert len(shards) == 1 and '"start"' in shards[0].read_text(encoding="utf-8")
        assert real_ledger_sink == []


class TestSessionGuardDiscriminates:
    """conftest ②의 판정 함수 — 추가·삭제·변경을 각각 구별하고, 무변경은 빈 목록이다."""

    @pytest.mark.parametrize(
        ("before", "after", "expected"),
        [
            ({"a": "1"}, {"a": "1"}, []),
            ({"a": "1"}, {"a": "2"}, ["변경 a"]),
            ({"a": "1"}, {"a": "1", "b": "9"}, ["추가 b"]),
            ({"a": "1", "b": "9"}, {"a": "1"}, ["삭제 b"]),
        ],
    )
    def test_ledger_changes(self, before, after, expected) -> None:
        assert _ledger_guard.ledger_changes(before, after) == expected

    def test_fingerprint_sees_the_real_ledger(self) -> None:
        """스캔 0건이면 전후 대조가 공허하게 통과한다 — 실제 대장 파일이 보여야 한다."""
        fingerprint = _ledger_guard.ledger_fingerprint()
        assert any(name.startswith("backlog/events/") for name in fingerprint)
        assert any(name.startswith("backlog/tasks/") for name in fingerprint)


class TestSessionGuardBranches:
    """conftest ②의 본체(`_ledger_guard.guard_session`) — 가짜 지문으로 두 분기를 모두 밟는다."""

    @staticmethod
    def _drive(first: dict[str, str], second: dict[str, str]) -> list[str]:
        calls = iter([first, second])
        failures: list[str] = []
        gen = _ledger_guard.guard_session(fingerprint=lambda: next(calls), fail=failures.append)
        next(gen)
        with pytest.raises(StopIteration):
            next(gen)
        return failures

    def test_unchanged_ledger_does_not_fail(self) -> None:
        assert self._drive({"a": "1"}, {"a": "1"}) == []

    def test_changed_ledger_fails_and_names_the_file(self) -> None:
        failures = self._drive({"a": "1"}, {"a": "2", "b": "3"})
        assert len(failures) == 1
        assert "변경 a" in failures[0] and "추가 b" in failures[0]

    def test_empty_scan_is_a_failure_not_a_pass(self) -> None:
        gen = _ledger_guard.guard_session(fingerprint=dict, fail=lambda _m: None)
        with pytest.raises(AssertionError):
            next(gen)


class TestConftestWiresBothGuards:
    """배선 — 두 픽스처가 autouse로 걸려 있고 실제 판정 함수에 위임하는가(존재 ≠ 작동).

    판정 함수가 옳아도 픽스처가 그것을 부르지 않으면 보호는 0이다. conftest를 AST로 읽어
    ① 함수 단위 픽스처가 autouse이고 `store.append_event`를 갈아 끼우는지 ② 세션 픽스처가
    session·autouse이고 `_ledger_guard.guard_session`에 위임하는지를 본다.
    """

    @staticmethod
    def _fixtures() -> dict[str, ast.FunctionDef]:
        tree = ast.parse((Path(__file__).parent / "conftest.py").read_text(encoding="utf-8"))
        return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    @staticmethod
    def _fixture_kwargs(node: ast.FunctionDef) -> dict[str, object]:
        for deco in node.decorator_list:
            if isinstance(deco, ast.Call) and ast.unparse(deco.func) == "pytest.fixture":
                return {kw.arg: ast.literal_eval(kw.value) for kw in deco.keywords}
        return {}

    def test_function_guard_is_autouse_and_patches_append_event(self) -> None:
        node = self._fixtures()["real_ledger_sink"]
        assert self._fixture_kwargs(node).get("autouse") is True
        patches = [
            call
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
            and ast.unparse(call.func) == "monkeypatch.setattr"
            and [ast.unparse(a) for a in call.args[:2]] == ["store", "'append_event'"]
        ]
        assert len(patches) == 1

    def test_session_guard_is_autouse_and_delegates(self) -> None:
        node = self._fixtures()["real_ledger_unchanged"]
        kwargs = self._fixture_kwargs(node)
        assert kwargs.get("scope") == "session" and kwargs.get("autouse") is True
        delegations = [
            y
            for y in ast.walk(node)
            if isinstance(y, ast.YieldFrom)
            and isinstance(y.value, ast.Call)
            and ast.unparse(y.value.func) == "_ledger_guard.guard_session"
        ]
        assert len(delegations) == 1
