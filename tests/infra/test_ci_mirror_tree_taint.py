"""CI 미러의 실행 도중 작업 트리 변경 감지 — HARN-194 계약 동결.

왜 있는가 (2026-09-28 EOS-134 · 같은 계열 1회차 2026-09-21):
  전체 CI 미러가 도는 동안 통합 테스트 정리 코드를 고쳐 작업 트리를 바꿨다. 스스로 알아채 그
  실행을 폐기했지만 도구는 아무것도 알리지 않았고, 그대로 두었으면 바뀐 트리의 결과가 원래 커밋의
  결과로 기록됐을 것이다. 런타임에 소스를 읽는 검사는 바뀐 소스를 보고 *거짓 실패*를 내고, 거짓
  실패는 없는 회귀를 쫓게 만들어 통과보다 비싸다.

이 파일이 지키는 것:
  · 실행 도중 파일을 바꾸는 가짜 실행은 **오염**으로 잡히고(exit 4 · `tainted: true`), 바꾸지
    않는 실행은 잡히지 않는다 — 양쪽 픽스처 (acceptance ①④)
  · 상태 두 글자(` M` → ` M`)가 같아도 **내용**이 바뀌면 잡힌다 (이미 더러운 파일·추적 안 된 파일)
  · HEAD만 바뀌어도(경로 변경 없이 커밋) 잡히고, `commit`은 시작 시점의 HEAD다
  · 오염이면 스텝이 실패였어도 exit 4가 앞서고 verdict는 "실패"가 아니라 "측정되지 않음"이다
  · 지문을 못 잡은 것은 안정이 아니다(`tainted: null` · exit 4)
  · 미러 자신의 산출물·`.gitignore`가 거른 경로는 오염이 아니다 (상시 발화 경고는 소음이다)
  · 도구가 스스로 만드는 알려진 변경(HARN-170 이벤트 대장 누수)은 오염과 **따로** 보고하되,
    `policy_warn` 줄만 *덧붙인* 변경에 한한다 (acceptance ②)
  · `done`이 쓰는 verdict가 오염 결과를 통과로 읽지 않는다 (acceptance ③)

각 절마다 "그 절이 없으면 통과해 버리는 반례"를 픽스처로 두고, 뮤테이션 22종이 시나리오를
RED로 만드는지 확인한다(`TestTaintMutationSelfCheck`). 이름이 의도를 말한다고 코드가 그 의도를
실행하는 것은 아니다 — 시나리오가 그 절을 실제로 밟는지는 뮤테이션 생존 여부로만 알 수 있다.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MIRROR_PATH = _REPO_ROOT / "scripts" / "harness" / "ci_mirror.py"
_BACKLOG_CLI = _REPO_ROOT / "scripts" / "harness" / "backlog.py"

#: 이벤트 대장 샤드의 경로 — `store.event_paths`가 읽는 위치와 같은 모양이다.
_SHARD = "backlog/events/s.ndjson"


def _load_mirror():
    """이미 등록된 `ci_mirror`를 그대로 쓴다 — `sys.modules`를 덮어쓰지 않는다.

    `test_ci_mirror.py`는 자기 사본의 `current_commit`을 가짜로 바꾸는데, `backlog.py`는
    `sys.modules["ci_mirror"]`를 읽는다. 여기서 사본을 새로 만들어 덮어쓰면(수집 순서상 이
    파일이 나중이다) 그 가짜가 읽히지 않아 같은 프로세스의 기존 4건이 깨진다 — 부분 실행으로는
    보이지 않고 전체 `tests/infra` 실행(CI·미러)에서만 드러난다(HARN-194 첫 미러 실행 실측).
    """
    sys.path.insert(0, str(_MIRROR_PATH.parent))
    return importlib.import_module("ci_mirror")


mirror = _load_mirror()


# ── 픽스처: 임시 저장소와 가짜 실행 ───────────────────────────────────────────
def _git(repo: Path, *argv: str) -> str:
    proc = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *argv],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return proc.stdout.decode("utf-8", errors="replace").strip()


def _head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD")


def _warn_line(rule: str = "scope_drift", ts: str = "2026-10-08T00:00:00+09:00") -> str:
    """HARN-170이 남기던 누출 줄의 모양 — `policy_warn` 이벤트."""
    return json.dumps({"ts": ts, "action": "policy_warn", "rule": rule}) + "\n"


def _make_repo(tmp_path: Path, name: str = "repo") -> Path:
    """커밋 1건짜리 저장소 — 추적 파일·이벤트 샤드·`.gitignore`(캐시·무시 디렉터리)를 갖춘다."""
    repo = tmp_path / name
    (repo / "backlog" / "events").mkdir(parents=True)
    (repo / "sub").mkdir()
    (repo / "src.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "sub" / "deep.py").write_text("y = 1\n", encoding="utf-8")
    (repo / "notes.ndjson").write_text('{"action": "start"}\n', encoding="utf-8")
    # 샤드의 첫 두 줄은 같은 길이다 — 기존 줄을 같은 길이로 바꾸는 재작성(prefix 위반)을 만들려는 것.
    (repo / _SHARD).write_text(
        '{"action": "start", "id": "T1"}\n{"action": "start", "id": "T2"}\n', encoding="utf-8"
    )
    (repo / ".gitignore").write_text(".claude/cache/\n__pycache__/\nignored/\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _run(
    module,
    repo: Path,
    tmp_path: Path,
    monkeypatch,
    script: str,
    *,
    result: Path | None = None,
    jobs: dict | None = None,
) -> tuple[int, dict]:
    """가짜 워크플로(스텝 1개)를 `repo`에서 실제 `main`으로 돌리고 (종료 코드, 결과 JSON)을 돌려준다."""
    workflow = jobs or {"jobs": {"demo": {"steps": [{"name": "act", "run": script}]}}}
    wf_path = tmp_path / "ci.yml"  # 저장소 밖 — 워크플로 파일이 지문에 섞이지 않게 한다
    wf_path.write_text(yaml.safe_dump(workflow), encoding="utf-8")
    result_path = result or (tmp_path / "r.json")
    monkeypatch.chdir(repo)
    rc = module.main(
        ["--workflow", str(wf_path), "--result", str(result_path), "run", "--job", "demo"]
    )
    return rc, json.loads(result_path.read_text(encoding="utf-8"))


def _changes(payload: dict) -> dict[str, str]:
    return {c["path"]: c["kind"] for c in payload["tree"]["changes"]}


# ── 시나리오: (모듈, tmp_path, monkeypatch, capsys)를 받아 단언한다 ─────────────
# 같은 함수가 원본 모듈(GREEN)과 뮤테이션 사본(RED)에 모두 쓰인다.
def scn_clean_run_is_not_tainted(module, tmp_path, monkeypatch, capsys):
    """대조군 — 트리를 건드리지 않는 실행은 오염이 아니다 (acceptance ④의 한쪽)."""
    capsys.readouterr()
    repo = _make_repo(tmp_path)
    rc, payload = _run(module, repo, tmp_path, monkeypatch, "cat src.py > /dev/null\ntrue")
    assert rc == 0, payload["tree"]
    assert payload["tainted"] is False and payload["tree"]["state"] == "stable"
    assert payload["tree"]["changes_total"] == 0 and payload["tree"]["known"] == []
    out = capsys.readouterr().out
    assert "오염" not in out and out.strip().splitlines()[-1] == "✔ 전 잡 통과"


def scn_tracked_edit_is_tainted(module, tmp_path, monkeypatch, capsys):
    """실행 도중 추적 파일을 고치면 오염이다 — exit 4 · `tainted: true` · 바뀐 경로 이름."""
    capsys.readouterr()
    repo = _make_repo(tmp_path)
    rc, payload = _run(module, repo, tmp_path, monkeypatch, "echo 'x = 2' >> src.py")
    assert rc == module.EXIT_TAINTED == 4, payload["tree"]
    assert payload["tainted"] is True and payload["exit"] == 4
    assert payload["step_exit"] == 0, "스텝 자체는 통과였다 — 그 사실도 남아야 한다"
    assert _changes(payload) == {"src.py": "modified"}
    out = capsys.readouterr().out
    assert "src.py (수정)" in out, "요약에 바뀐 경로를 열거하지 않았다"
    last = out.strip().splitlines()[-1]
    assert last.startswith("✗ 오염") and "src.py" in last, "tail -1로 읽어도 통과로 보이면 안 된다"


def scn_already_dirty_file_edit_is_tainted(module, tmp_path, monkeypatch, capsys):
    """상태 두 글자가 같아도(` M` → ` M`) 내용이 바뀌면 오염이다 — 내용 해시 절의 반례."""
    capsys.readouterr()
    repo = _make_repo(tmp_path)
    (repo / "src.py").write_text("x = 'dirty-A'\n", encoding="utf-8")
    # 같은 길이로 고친다 — 길이가 달라지면 크기 비교만으로 잡혀 내용 해시 절을 밟지 못한다.
    rc, payload = _run(module, repo, tmp_path, monkeypatch, "sed -i 's/dirty-A/dirty-B/' src.py")
    assert rc == 4 and payload["tainted"] is True, payload["tree"]
    assert _changes(payload) == {"src.py": "changed_again"}


def scn_untracked_content_edit_is_tainted(module, tmp_path, monkeypatch, capsys):
    """추적 안 된 파일(`??` → `??`)의 내용이 바뀌어도 오염이다."""
    capsys.readouterr()
    repo = _make_repo(tmp_path)
    (repo / "scratch.txt").write_text("before\n", encoding="utf-8")
    # "before\n"과 "after!\n"은 길이가 같다 — 내용 해시 절만이 이 변경을 가른다.
    rc, payload = _run(module, repo, tmp_path, monkeypatch, "printf 'after!\\n' > scratch.txt")
    assert rc == 4 and payload["tainted"] is True, payload["tree"]
    assert _changes(payload) == {"scratch.txt": "changed_again"}


def scn_untracked_directory_file_edit_is_tainted(module, tmp_path, monkeypatch, capsys):
    """추적 안 된 **디렉터리 안** 파일을 고쳐도 오염이다 — `-uall`이 없으면 `dir/` 한 줄로 접힌다."""
    capsys.readouterr()
    repo = _make_repo(tmp_path)
    (repo / "newpkg").mkdir()
    (repo / "newpkg" / "a.txt").write_text("before\n", encoding="utf-8")
    rc, payload = _run(module, repo, tmp_path, monkeypatch, "printf 'after!\\n' > newpkg/a.txt")
    assert rc == 4 and payload["tainted"] is True, payload["tree"]
    assert _changes(payload) == {"newpkg/a.txt": "changed_again"}


def scn_new_file_is_tainted(module, tmp_path, monkeypatch, capsys):
    """실행 도중 새 파일이 생겨도 오염이다."""
    capsys.readouterr()
    repo = _make_repo(tmp_path)
    rc, payload = _run(module, repo, tmp_path, monkeypatch, "echo hi > added.txt")
    assert rc == 4, payload["tree"]
    assert _changes(payload) == {"added.txt": "added"}


def scn_deleted_file_is_tainted(module, tmp_path, monkeypatch, capsys):
    """추적 파일을 지워도 오염이다."""
    capsys.readouterr()
    repo = _make_repo(tmp_path)
    rc, payload = _run(module, repo, tmp_path, monkeypatch, "rm src.py")
    assert rc == 4, payload["tree"]
    assert _changes(payload) == {"src.py": "deleted"}


def scn_dirty_file_reverted_is_tainted(module, tmp_path, monkeypatch, capsys):
    """시작 때 더러웠던 파일이 깨끗해져도(되돌림) 오염이다 — 한쪽에만 있는 경로도 변경이다."""
    capsys.readouterr()
    repo = _make_repo(tmp_path)
    (repo / "src.py").write_text("x = 'dirty'\n", encoding="utf-8")
    rc, payload = _run(module, repo, tmp_path, monkeypatch, "git checkout -q -- src.py")
    assert rc == 4, payload["tree"]
    assert _changes(payload) == {"src.py": "reverted"}


def scn_commit_during_run_is_tainted(module, tmp_path, monkeypatch, capsys):
    """경로 변경 없이 커밋만 해도 오염이다(HEAD 절) — `commit`은 **시작 시점**의 HEAD다."""
    capsys.readouterr()
    repo = _make_repo(tmp_path)
    start = _head(repo)
    script = "git -c user.name=t -c user.email=t@e.com commit -q --allow-empty -m mid-run"
    rc, payload = _run(module, repo, tmp_path, monkeypatch, script)
    assert rc == 4 and payload["tainted"] is True, payload["tree"]
    assert payload["tree"]["changes_total"] == 0, "경로 변경 없이 HEAD만 움직인 실행이어야 한다"
    assert payload["tree"]["head_start"] == start != payload["tree"]["head_end"] == _head(repo)
    assert payload["commit"] == start, "끝 시점 HEAD를 적으면 도중 커밋이 새 커밋의 결과로 둔갑한다"
    assert "HEAD:" in capsys.readouterr().out


def scn_failure_plus_mutation_is_tainted_not_failed(module, tmp_path, monkeypatch, capsys):
    """오염은 실패보다 앞선다 — 바뀐 트리에서 난 실패는 거짓 실패일 수 있다. 스텝 판정은 남는다."""
    capsys.readouterr()
    repo = _make_repo(tmp_path)
    rc, payload = _run(module, repo, tmp_path, monkeypatch, "echo more >> src.py\nexit 1")
    assert rc == 4, "실패(1)가 오염(4)을 덮었다"
    assert payload["step_exit"] == 1 and payload["tainted"] is True
    last = capsys.readouterr().out.strip().splitlines()[-1]
    assert last.startswith("✗ 오염") and "실패 잡: demo" in last, "참고용 스텝 판정이 사라졌다"


def scn_ignored_writes_do_not_taint(module, tmp_path, monkeypatch, capsys):
    """`.gitignore`가 거른 경로(캐시·`__pycache__`)의 쓰기는 오염이 아니다 — 상시 소음 방지."""
    capsys.readouterr()
    repo = _make_repo(tmp_path)
    script = "mkdir -p ignored __pycache__ .claude/cache\necho x > ignored/o.txt\n"
    script += "echo x > __pycache__/m.pyc\necho x > .claude/cache/c.json"
    rc, payload = _run(module, repo, tmp_path, monkeypatch, script)
    assert rc == 0 and payload["tainted"] is False, payload["tree"]


def scn_own_outputs_do_not_taint(module, tmp_path, monkeypatch, capsys):
    """미러 자신의 산출물(결과 JSON·스텝 로그)은 오염이 아니다 — 무시되지 않는 경로에 둬도.

    제외가 없으면 도구가 스스로 트리를 바꾼 것으로 읽혀 *모든* 실행이 오염이 된다.
    """
    capsys.readouterr()
    repo = _make_repo(tmp_path)
    rc, payload = _run(
        module,
        repo,
        tmp_path,
        monkeypatch,
        "true",
        result=repo / "out" / "result.json",  # .gitignore에 없는 경로
    )
    assert rc == 0 and payload["tainted"] is False, payload["tree"]
    assert (
        repo / "out" / "result.steps.ndjson"
    ).exists(), "스텝 로그가 이 경로에 생겨야 대조가 된다"


def scn_no_git_is_unverifiable(module, tmp_path, monkeypatch, capsys):
    """git이 없으면 안정이 아니라 **모름**이다 — `tainted: null` · exit 4 · 원인 예외 타입명."""
    capsys.readouterr()
    plain = tmp_path / "plain"
    plain.mkdir()
    rc, payload = _run(module, plain, tmp_path, monkeypatch, "true")
    assert rc == 4, payload["tree"]
    assert payload["tainted"] is None and payload["tree"]["state"] == "unverifiable"
    assert payload["tree"]["error_type"] == "GitExitError", "원인 타입명이 남지 않았다"
    assert payload["step_exit"] == 0
    out = capsys.readouterr().out
    assert "미확인" in out and out.strip().splitlines()[-1].startswith("⚠ 트리 안정성 미확인")


def scn_many_changes_are_listed_with_total(module, tmp_path, monkeypatch, capsys):
    """바뀐 경로가 많아도 총수를 말한다 — 8건만 늘어놓고 "외 N건"으로 줄인다."""
    capsys.readouterr()
    repo = _make_repo(tmp_path)
    rc, payload = _run(
        module, repo, tmp_path, monkeypatch, "for i in $(seq 1 12); do echo $i > f$i.txt; done"
    )
    assert rc == 4 and payload["tree"]["changes_total"] == 12
    out = capsys.readouterr().out
    assert "바뀐 경로 12건" in out and "외 4건" in out


def scn_subdirectory_root_still_detects(module, tmp_path, monkeypatch, capsys):
    """`root`가 하위 디렉터리여도 파일을 저장소 루트에서 읽는다 — 어긋나면 모든 해시가 `absent`다."""
    capsys.readouterr()
    repo = _make_repo(tmp_path)
    (repo / "sub" / "deep.py").write_text("y = 'dirty'\n", encoding="utf-8")
    monkeypatch.chdir(repo / "sub")
    watch = module.TreeWatch.begin(repo / "sub")
    (repo / "sub" / "deep.py").write_text("y = 'edited during the run'\n", encoding="utf-8")
    tree = watch.finish()
    assert tree.state == module.TREE_MUTATED, tree
    assert [(c.path, c.kind) for c in tree.changes] == [("sub/deep.py", "changed_again")]


def scn_rename_entry_does_not_shift_following_entries(module, tmp_path, monkeypatch, capsys):
    """이름 바꾸기(`R`)는 원래 경로 칸이 하나 더 붙는다 — 건너뛰지 않으면 뒤 항목이 전부 어긋난다."""
    capsys.readouterr()
    repo = _make_repo(tmp_path)
    _git(repo, "mv", "src.py", "renamed.py")
    (repo / "other.txt").write_text("untracked\n", encoding="utf-8")
    monkeypatch.chdir(repo)
    paths = module.take_fingerprint(repo).paths
    assert set(paths) == {"renamed.py", "other.txt"}, sorted(paths)
    assert paths["other.txt"].status == "??", "뒤 항목이 한 칸 어긋났다"


# ── 시나리오: 알려진 부작용 (acceptance ②) ────────────────────────────────────
def scn_ledger_leak_is_reported_not_tainted(module, tmp_path, monkeypatch, capsys):
    """이벤트 대장에 `policy_warn`을 덧붙인 변경은 오염이 아니라 **알려진 부작용**으로 따로 보고한다."""
    capsys.readouterr()
    repo = _make_repo(tmp_path)
    script = f"printf '%s\\n' '{_warn_line().strip()}' >> {_SHARD}"
    rc, payload = _run(module, repo, tmp_path, monkeypatch, script)
    assert rc == 0, payload["tree"]  # 오염으로 뭉개지 않는다
    assert payload["tainted"] is False and payload["tree"]["changes_total"] == 0
    (effect,) = payload["tree"]["known"]
    assert effect["kind"] == "ledger_policy_warn_leak" and effect["task"] == "HARN-170"
    assert effect["paths"] == [_SHARD] and effect["lines"] == 1
    out = capsys.readouterr().out
    assert "알려진 부작용" in out and "HARN-170" in out and _SHARD in out, "침묵했다"
    last = out.strip().splitlines()[-1]
    assert last.startswith("✔ 전 잡 통과") and "알려진 부작용" in last, last


def scn_ledger_leak_in_untracked_shard(module, tmp_path, monkeypatch, capsys):
    """시작 때 이미 추적 안 된 샤드(`??`)에 덧붙인 경우 — 기준선이 시작 시점의 (크기, sha256)이다."""
    capsys.readouterr()
    repo = _make_repo(tmp_path)
    shard = repo / "backlog" / "events" / "mine.ndjson"
    shard.write_text('{"action": "start", "id": "T9"}\n', encoding="utf-8")
    script = f"printf '%s\\n' '{_warn_line().strip()}' >> backlog/events/mine.ndjson"
    rc, payload = _run(module, repo, tmp_path, monkeypatch, script)
    assert rc == 0 and payload["tainted"] is False, payload["tree"]
    assert [k["lines"] for k in payload["tree"]["known"]] == [1]


def scn_new_ledger_shard_is_known(module, tmp_path, monkeypatch, capsys):
    """실행 중 새로 생긴 샤드에 `policy_warn`만 있으면 알려진 부작용이다(줄 수는 전부)."""
    capsys.readouterr()
    repo = _make_repo(tmp_path)
    line = _warn_line().strip()
    script = f"printf '%s\\n%s\\n' '{line}' '{line}' > backlog/events/new.ndjson"
    rc, payload = _run(module, repo, tmp_path, monkeypatch, script)
    assert rc == 0 and payload["tainted"] is False, payload["tree"]
    assert [k["lines"] for k in payload["tree"]["known"]] == [2]


def scn_other_event_append_is_tainted(module, tmp_path, monkeypatch, capsys):
    """대장에 `policy_warn`이 아닌 이벤트를 덧붙이면 알려진 부작용이 아니다 — 오염이다."""
    capsys.readouterr()
    repo = _make_repo(tmp_path)
    script = f'printf \'%s\\n\' \'{{"action": "done", "id": "T1"}}\' >> {_SHARD}'
    rc, payload = _run(module, repo, tmp_path, monkeypatch, script)
    assert rc == 4 and payload["tainted"] is True, payload["tree"]
    assert payload["tree"]["known"] == [] and _changes(payload) == {_SHARD: "modified"}


def scn_ledger_rewrite_is_tainted(module, tmp_path, monkeypatch, capsys):
    """기존 줄을 **같은 길이로** 고치고 `policy_warn`을 덧붙이면 덧붙임이 아니다 — 오염이다.

    덧붙인 부분만 보면 알려진 부작용처럼 보이므로, 기준선 접두 대조(HEAD 내용)가 없으면 통과한다.
    """
    capsys.readouterr()
    repo = _make_repo(tmp_path)
    script = f"sed -i 's/T1/X1/' {_SHARD}\nprintf '%s\\n' '{_warn_line().strip()}' >> {_SHARD}"
    rc, payload = _run(module, repo, tmp_path, monkeypatch, script)
    assert rc == 4 and payload["tainted"] is True, payload["tree"]
    assert payload["tree"]["known"] == []


def scn_dirty_shard_rewrite_is_tainted(module, tmp_path, monkeypatch, capsys):
    """시작 때 더러웠던 샤드의 기존 줄을 고친 경우도 같다 — 기준선은 시작 시점의 sha256이다."""
    capsys.readouterr()
    repo = _make_repo(tmp_path)
    shard = repo / "backlog" / "events" / "mine.ndjson"
    shard.write_text('{"action": "start", "id": "T9"}\n', encoding="utf-8")
    script = "sed -i 's/T9/X9/' backlog/events/mine.ndjson\n"
    script += f"printf '%s\\n' '{_warn_line().strip()}' >> backlog/events/mine.ndjson"
    rc, payload = _run(module, repo, tmp_path, monkeypatch, script)
    assert rc == 4 and payload["tainted"] is True, payload["tree"]
    assert payload["tree"]["known"] == []


def scn_policy_warn_outside_ledger_is_tainted(module, tmp_path, monkeypatch, capsys):
    """`policy_warn`이어도 이벤트 대장 경로가 아니면 알려진 부작용이 아니다 — 경로 조건의 반례."""
    capsys.readouterr()
    repo = _make_repo(tmp_path)
    script = f"printf '%s\\n' '{_warn_line().strip()}' >> notes.ndjson"
    rc, payload = _run(module, repo, tmp_path, monkeypatch, script)
    assert rc == 4 and payload["tainted"] is True, payload["tree"]
    assert payload["tree"]["known"] == [] and _changes(payload) == {"notes.ndjson": "modified"}


def scn_unclosed_last_line_is_tainted(module, tmp_path, monkeypatch, capsys):
    """기준선의 마지막 줄이 닫히지 않았으면(개행 없음) 덧붙임이 그 줄과 섞인다 — 알려진 부작용 아님."""
    capsys.readouterr()
    repo = _make_repo(tmp_path)
    shard = repo / "backlog" / "events" / "open.ndjson"
    shard.write_bytes(b'{"action": "start", "id": "T9"}')  # 개행 없음
    script = f"printf '\\n%s\\n' '{_warn_line().strip()}' >> backlog/events/open.ndjson"
    rc, payload = _run(module, repo, tmp_path, monkeypatch, script)
    assert rc == 4 and payload["tainted"] is True, payload["tree"]
    assert payload["tree"]["known"] == []


def scn_known_and_unexpected_are_separated(module, tmp_path, monkeypatch, capsys):
    """알려진 부작용과 진짜 변경이 함께 있으면 오염이고, 둘은 **섞이지 않고** 각자 보고된다."""
    capsys.readouterr()
    repo = _make_repo(tmp_path)
    script = f"printf '%s\\n' '{_warn_line().strip()}' >> {_SHARD}\necho more >> src.py"
    rc, payload = _run(module, repo, tmp_path, monkeypatch, script)
    assert rc == 4 and payload["tainted"] is True, payload["tree"]
    assert _changes(payload) == {"src.py": "modified"}, "알려진 변경이 오염 목록에 섞였다"
    assert [k["paths"] for k in payload["tree"]["known"]] == [[_SHARD]]
    out = capsys.readouterr().out
    assert "src.py (수정)" in out and "알려진 부작용" in out


def scn_head_change_disables_known_classification(module, tmp_path, monkeypatch, capsys):
    """HEAD가 바뀌었으면 알려진 부작용 분류를 하지 않는다 — 다른 기준선을 보는 `git status`다."""
    capsys.readouterr()
    repo = _make_repo(tmp_path)
    script = f"printf '%s\\n' '{_warn_line().strip()}' >> {_SHARD}\n"
    script += "git -c user.name=t -c user.email=t@e.com commit -q --allow-empty -m mid-run"
    rc, payload = _run(module, repo, tmp_path, monkeypatch, script)
    assert rc == 4 and payload["tainted"] is True, payload["tree"]
    assert payload["tree"]["known"] == [] and _SHARD in _changes(payload)


# ── 시나리오: verdict (acceptance ③) ──────────────────────────────────────────
def scn_tainted_verdict_is_unmeasured(module, tmp_path, monkeypatch, capsys):
    """오염된 결과는 verdict가 "측정되지 않음"(unknown)으로 답한다 — 통과도 실패도 아니다."""
    capsys.readouterr()
    repo = _make_repo(tmp_path)
    result = tmp_path / "r.json"
    _run(module, repo, tmp_path, monkeypatch, "echo more >> src.py", result=result)
    verdict = module.mirror_verdict(result, _head(repo))
    assert verdict.state == module.VERDICT_UNKNOWN, verdict
    assert verdict.exit_code == 1
    assert "오염" in verdict.reason and "src.py" in verdict.reason, verdict.reason
    # 같은 오염에 스텝 실패가 겹쳐도 FAIL이 아니다 — 바뀐 트리의 실패는 거짓 실패일 수 있다.
    _run(module, repo, tmp_path, monkeypatch, "echo more >> src.py\nexit 1", result=result)
    fail_verdict = module.mirror_verdict(result, _head(repo))
    assert fail_verdict.state == module.VERDICT_UNKNOWN, fail_verdict


def scn_stable_verdict_is_pass(module, tmp_path, monkeypatch, capsys):
    """대조군 — 같은 경로로 만든 안정 결과는 통과다(전부 unknown으로 접는 과잉 수정이 걸린다)."""
    capsys.readouterr()
    repo = _make_repo(tmp_path)
    result = tmp_path / "r.json"
    _run(module, repo, tmp_path, monkeypatch, "true", result=result)
    verdict = module.mirror_verdict(result, _head(repo))
    assert verdict.state == module.VERDICT_PASS, verdict
    assert verdict.exit_code == 0


def scn_unverified_tree_shapes_are_unmeasured(module, tmp_path, monkeypatch, capsys):
    """`tainted`가 **명시적 False**가 아니면 전부 측정되지 않음이다 — 키 부재·None·문자열 모양 이탈."""
    capsys.readouterr()
    repo = _make_repo(tmp_path)
    result = tmp_path / "r.json"
    _run(module, repo, tmp_path, monkeypatch, "true", result=result)
    good = json.loads(result.read_text(encoding="utf-8"))
    assert module.mirror_verdict(result, _head(repo)).state == module.VERDICT_PASS
    variants: list[dict] = []
    absent = dict(good)
    del absent["tainted"]
    variants += [absent, {**good, "tainted": None}, {**good, "tainted": "false"}]
    variants += [{**good, "tainted": 0}]
    for payload in variants:
        result.write_text(json.dumps(payload), encoding="utf-8")
        verdict = module.mirror_verdict(result, _head(repo))
        assert verdict.state == module.VERDICT_UNKNOWN, (payload.get("tainted", "<부재>"), verdict)


def scn_old_schema_is_unmeasured(module, tmp_path, monkeypatch, capsys):
    """schema 2(트리 판정 없음) 결과는 그 외가 멀쩡해도 "형식이 다르다"로 측정되지 않는다."""
    capsys.readouterr()
    repo = _make_repo(tmp_path)
    result = tmp_path / "r.json"
    _run(module, repo, tmp_path, monkeypatch, "true", result=result)
    old = json.loads(result.read_text(encoding="utf-8"))
    old["schema"] = 2
    for key in ("tainted", "tree", "step_exit"):
        old.pop(key)
    result.write_text(json.dumps(old), encoding="utf-8")
    verdict = module.mirror_verdict(result, _head(repo))
    assert verdict.state == module.VERDICT_UNKNOWN and "형식" in verdict.reason, verdict


def scn_build_payload_without_tree_is_unverified(module, tmp_path, monkeypatch, capsys):
    """트리 판정 없이 만든 결과는 안정이 아니다 — `tainted: null` · exit 4 (기본값이 fail-closed)."""
    capsys.readouterr()
    job = module.JobResult("j", [module.StepResult("ok", module.PASSED)])
    payload = module.build_payload([job], tmp_path, Path("ci.yml"))
    assert payload["tainted"] is None and payload["exit"] == 4
    assert payload["step_exit"] == 0 and payload["tree"]["state"] == "unverifiable"


SCENARIOS: dict[str, Callable] = {
    name[4:]: fn for name, fn in sorted(globals().items()) if name.startswith("scn_")
}


class TestScenariosOnTheRealTool:
    """원본 모듈에서 모든 시나리오가 GREEN이다 — 뮤테이션 RED의 대조 기준."""

    @pytest.mark.parametrize("name", sorted(SCENARIOS))
    def test_scenario(self, name, tmp_path, monkeypatch, capsys):
        SCENARIOS[name](mirror, tmp_path, monkeypatch, capsys)

    def test_scenario_count_floor(self):
        """시나리오 수가 조용히 줄지 않는다 — 스캔 0건·절반은 통과가 아니다."""
        assert len(SCENARIOS) >= 30, sorted(SCENARIOS)


# ── 지문 단위 계약 ────────────────────────────────────────────────────────────
class TestFingerprintUnits:
    def test_clean_repo_has_head_and_no_paths(self, tmp_path):
        repo = _make_repo(tmp_path)
        fp = mirror.take_fingerprint(repo)
        assert fp.head == _head(repo) and fp.paths == {}

    def test_fingerprint_of_a_non_repo_raises_with_type_name(self, tmp_path):
        with pytest.raises(mirror.TreeFingerprintError) as info:
            mirror.take_fingerprint(tmp_path)
        assert info.value.error_type == "GitExitError" and "exit" in str(info.value)

    def test_git_timeout_is_a_typed_fingerprint_error(self, tmp_path, monkeypatch):
        """멈춘 git은 무한 대기가 아니라 타임아웃 타입명이 남는 오류다 — 서브프로세스 상한 계약."""
        repo = _make_repo(tmp_path)

        def boom(*_args, **kwargs):
            assert kwargs.get("timeout") == mirror._GIT_TIMEOUT, "git 호출에 타임아웃이 없다"
            raise subprocess.TimeoutExpired("git", kwargs["timeout"])

        monkeypatch.setattr(mirror.subprocess, "run", boom)
        with pytest.raises(mirror.TreeFingerprintError) as info:
            mirror.take_fingerprint(repo)
        assert info.value.error_type == "TimeoutExpired"

    def test_end_fingerprint_failure_is_unverifiable_with_start_head(self, tmp_path, monkeypatch):
        repo = _make_repo(tmp_path)
        start_head = _head(repo)  # git을 막기 전에 — 테스트 헬퍼도 subprocess.run을 쓴다
        watch = mirror.TreeWatch.begin(repo)

        def boom(*_args, **_kwargs):
            raise OSError("git 없음")

        monkeypatch.setattr(mirror.subprocess, "run", boom)
        tree = watch.finish()
        assert tree.state == mirror.TREE_UNVERIFIABLE and tree.tainted is None
        assert tree.head_start == start_head and tree.error_type == "OSError"
        assert "종료 시점" in tree.reason

    def test_symlink_target_change_is_detected(self, tmp_path):
        repo = _make_repo(tmp_path)
        link = repo / "lnk"
        link.symlink_to("src.py")
        before = mirror.take_fingerprint(repo)
        link.unlink()
        link.symlink_to("sub/deep.py")
        after = mirror.take_fingerprint(repo)
        assert [c.path for c in mirror.diff_fingerprints(before, after)] == ["lnk"]

    def test_oversized_file_falls_back_to_size_and_mtime(self, tmp_path, monkeypatch):
        repo = _make_repo(tmp_path)
        monkeypatch.setattr(mirror, "_HASH_SIZE_LIMIT", 4)
        (repo / "big.bin").write_bytes(b"0123456789")
        before = mirror.take_fingerprint(repo).paths["big.bin"]
        assert before.digest.startswith("big:") and before.size is None
        (repo / "big.bin").write_bytes(b"0123456789ab")
        after = mirror.take_fingerprint(repo).paths["big.bin"]
        assert before != after, "상한을 넘는 파일도 크기가 바뀌면 잡혀야 한다"

    def test_excluded_path_outside_repo_is_ignored(self, tmp_path):
        repo = _make_repo(tmp_path)
        (repo / "x.txt").write_text("1", encoding="utf-8")
        fp = mirror.take_fingerprint(repo, exclude=[tmp_path / "elsewhere.json", repo / "x.txt"])
        assert "x.txt" not in fp.paths

    def test_parse_status_z_handles_rename_copy_and_short_tokens(self):
        raw = b"R  new.txt\0old.txt\0?? c.txt\0 M d.txt\0\0xx\0"
        assert mirror._parse_status_z(raw) == [
            ("R ", "new.txt"),
            ("??", "c.txt"),
            (" M", "d.txt"),
        ]

    def test_summary_survives_malformed_tree_shapes(self):
        """verdict가 손상된 `tree` 매핑으로 죽지 않는다 — 판정 대신 크래시가 남으면 안 된다."""
        for shape in (None, 3, [], {}, {"state": "mutated"}, {"state": "mutated", "changes": 5}):
            assert isinstance(mirror.summarize_tree(shape), str)
        text = mirror.summarize_tree(
            {"state": "mutated", "head_start": "a" * 40, "head_end": "b" * 40, "changes_total": 0}
        )
        assert "HEAD aaaaaaaaaaaa → bbbbbbbbbbbb" in text


# ── done 종단 (acceptance ③의 실제 소비처) ────────────────────────────────────
class TestDonePreflightSeesTaint:
    """`backlog.py done`의 미러 신선도 검사가 오염을 통과로 읽지 않는다.

    판정 모듈(`done_mirror_gate`)과 종전 경고 헬퍼는 모두 `mirror_verdict`를 통해 읽으므로
    verdict가 바뀌면 둘이 함께 바뀐다 — 그 연결이 실제로 이어져 있는지를 실제 실행 결과로 본다.
    block 정책에서의 거부 종단은 `tests/harness/test_done_mirror_gate.py`가 동결한다.
    """

    @pytest.fixture
    def backlog_cli(self, monkeypatch):
        monkeypatch.setattr(sys, "path", [str(_BACKLOG_CLI.parent), *sys.path])
        import backlog  # noqa: PLC0415  (scripts/harness 단독 실행 모듈)

        return backlog

    def _mirror_default_path_run(self, repo: Path, tmp_path: Path, monkeypatch, script: str):
        _run(
            mirror,
            repo,
            tmp_path,
            monkeypatch,
            script,
            result=repo / mirror.DEFAULT_RESULT_PATH,
        )

    def test_legacy_warning_calls_a_tainted_result_unmeasured(
        self, backlog_cli, tmp_path, monkeypatch, capsys
    ):
        repo = _make_repo(tmp_path)
        self._mirror_default_path_run(repo, tmp_path, monkeypatch, "echo more >> src.py")
        capsys.readouterr()
        backlog_cli._warn_if_ci_mirror_missing(repo)
        err = capsys.readouterr().err
        assert "오염" in err and "src.py" in err and "측정되지 않았다" in err, err

    def test_gate_lookup_maps_a_tainted_result_to_unknown(self, tmp_path, monkeypatch):
        monkeypatch.syspath_prepend(str(_BACKLOG_CLI.parent))
        import done_mirror_gate as gate  # noqa: PLC0415

        repo = _make_repo(tmp_path)
        self._mirror_default_path_run(repo, tmp_path, monkeypatch, "echo more >> src.py")
        lookup = gate.lookup_mirror(repo)
        assert lookup.state == gate.STATE_UNKNOWN and "오염" in lookup.reason, lookup
        # 대조군: 트리를 건드리지 않은 실행은 통과다.
        clean = _make_repo(tmp_path, "clean")
        self._mirror_default_path_run(clean, tmp_path, monkeypatch, "true")
        assert gate.lookup_mirror(clean).state == gate.STATE_PASS


# ── 뮤테이션: 도구를 깨뜨리면 시나리오가 RED인가 ──────────────────────────────
def _mutated_module(tmp_path: Path, old: str, new: str):
    original = _MIRROR_PATH.read_text(encoding="utf-8")
    assert original.count(old) == 1, f"치환 대상이 1건이 아니다: {old[:50]!r}"
    mutated = original.replace(old, new, 1)
    assert mutated != original, "주입이 적용되지 않았다 — 하네스 결함"
    tmp_path.mkdir(parents=True, exist_ok=True)
    name = f"ci_mirror_taint_mutant_{abs(hash(old)) % 10**8}"
    target = tmp_path / f"{name}.py"
    target.write_text(mutated, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(name, target)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # exec_module *전에* 등록해야 한다 — dataclass가 sys.modules[cls.__module__]를 조회한다.
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module, original


#: (라벨, 주입 전, 주입 후, RED가 되어야 하는 시나리오들, GREEN을 유지해야 하는 대조 시나리오들)
_MUTATIONS = [
    (
        "M1-content-digest-ignored",
        "return size, digest.hexdigest()",
        'return size, "constant"',
        ["already_dirty_file_edit_is_tainted", "untracked_content_edit_is_tainted"],
        ["tracked_edit_is_tainted", "clean_run_is_not_tainted"],
    ),
    (
        "M2-head-comparison-dropped",
        "state = TREE_MUTATED if (head_changed or changes) else TREE_STABLE",
        "state = TREE_MUTATED if changes else TREE_STABLE",
        ["commit_during_run_is_tainted"],
        ["tracked_edit_is_tainted"],
    ),
    (
        "M3-untracked-directories-folded",
        '"status", "--porcelain=v1", "-z", "-uall"',
        '"status", "--porcelain=v1", "-z"',
        ["untracked_directory_file_edit_is_tainted"],
        ["untracked_content_edit_is_tainted"],
    ),
    (
        "M4-own-outputs-not-excluded",
        "        if rel in skip:\n            continue\n",
        "        if False:\n            continue\n",
        ["own_outputs_do_not_taint"],
        ["clean_run_is_not_tainted"],
    ),
    (
        "M5-unverifiable-folded-into-stable",
        "        if self.state == TREE_MUTATED:\n            return True\n        return None\n",
        "        if self.state == TREE_MUTATED:\n            return True\n        return False\n",
        ["no_git_is_unverifiable", "build_payload_without_tree_is_unverified"],
        ["tracked_edit_is_tainted"],
    ),
    (
        "M6-verdict-ignores-taint",
        'if payload.get("tainted") is not False:',
        "if False:",
        ["tainted_verdict_is_unmeasured", "unverified_tree_shapes_are_unmeasured"],
        ["stable_verdict_is_pass"],
    ),
    (
        "M7-exit-code-ignores-taint",
        '"exit": step_exit if check.tainted is False else EXIT_TAINTED,',
        '"exit": step_exit,',
        ["tracked_edit_is_tainted", "failure_plus_mutation_is_tainted_not_failed"],
        ["clean_run_is_not_tainted"],
    ),
    (
        "M8-any-ledger-event-counts-as-known",
        'if not isinstance(event, dict) or event.get("action") != "policy_warn":',
        "if not isinstance(event, dict):",
        ["other_event_append_is_tainted"],
        ["ledger_leak_is_reported_not_tainted"],
    ),
    (
        "M9a-no-baseline-prefix-check-clean-shard",
        "if base is None or not new.startswith(base):",
        "if base is None:",
        ["ledger_rewrite_is_tainted"],
        ["ledger_leak_is_reported_not_tainted"],
    ),
    (
        "M9b-no-baseline-prefix-check-dirty-shard",
        "if len(new) < base_len or hashlib.sha256(new[:base_len]).hexdigest() != before.digest:",
        "if len(new) < base_len:",
        ["dirty_shard_rewrite_is_tainted"],
        ["ledger_leak_in_untracked_shard"],
    ),
    (
        "M10-known-effects-never-recognised",
        'if change.kind in ("added", "modified", "changed_again") and _LEDGER_PATH_RE.match(',
        'if False and change.kind in ("added", "modified") and _LEDGER_PATH_RE.match(',
        [
            "ledger_leak_is_reported_not_tainted",
            "ledger_leak_in_untracked_shard",
            "new_ledger_shard_is_known",
        ],
        ["other_event_append_is_tainted"],
    ),
    (
        "M11-ledger-path-pattern-too-broad",
        '_LEDGER_PATH_RE = re.compile(r"^backlog/(?:events\\.ndjson|events/[^/]+\\.ndjson)$")',
        '_LEDGER_PATH_RE = re.compile(r".*\\.ndjson$")',
        ["policy_warn_outside_ledger_is_tainted"],
        ["ledger_leak_is_reported_not_tainted"],
    ),
    (
        "M12-known-effects-reported-silently",
        "    for effect in tree.known:\n        lines.append(",
        "    for effect in []:\n        lines.append(",
        ["ledger_leak_is_reported_not_tainted"],
        ["other_event_append_is_tainted"],
    ),
    (
        "M13-known-effects-folded-into-taint",
        "known, changes = split_known_effects(Path(end.toplevel), start, changes)",
        "known, _ = split_known_effects(Path(end.toplevel), start, changes)",
        ["ledger_leak_is_reported_not_tainted", "known_and_unexpected_are_separated"],
        ["other_event_append_is_tainted"],
    ),
    (
        "M14-final-line-hides-taint",
        "    if tree.tainted is True:\n        return (",
        "    if False:\n        return (",
        ["tracked_edit_is_tainted"],
        ["clean_run_is_not_tainted"],
    ),
    (
        "M15-commit-recorded-at-end-of-run",
        "commit = check.head_start or current_commit(repo_root)",
        "commit = current_commit(repo_root)",
        ["commit_during_run_is_tainted"],
        ["tracked_edit_is_tainted"],
    ),
    (
        "M16-missing-taint-key-read-as-stable",
        'if payload.get("tainted") is not False:',
        'if payload.get("tainted") is True:',
        ["unverified_tree_shapes_are_unmeasured"],
        ["tainted_verdict_is_unmeasured"],
    ),
    (
        "M17-rename-original-path-not-skipped",
        '        if "R" in status or "C" in status:\n            index += 1\n',
        "",
        ["rename_entry_does_not_shift_following_entries"],
        ["clean_run_is_not_tainted"],
    ),
    (
        "M18-files-read-relative-to-subdirectory-root",
        "size, digest = _hash_file(toplevel / rel)",
        "size, digest = _hash_file(root / rel)",
        ["subdirectory_root_still_detects"],
        ["tracked_edit_is_tainted"],
    ),
    (
        "M19-unclosed-baseline-line-accepted",
        'if base_len and new[base_len - 1 : base_len] != b"\\n":',
        "if False:",
        ["unclosed_last_line_is_tainted"],
        ["ledger_leak_is_reported_not_tainted"],
    ),
    (
        "M20-only-eight-changes-listed-without-total",
        "more = total - len(shown)",
        "more = 0",
        [],
        [],
    ),
    (
        "M21-head-change-still-classifies-known-effects",
        "if changes and not head_changed:",
        "if changes:",
        ["head_change_disables_known_classification"],
        ["ledger_leak_is_reported_not_tainted"],
    ),
]


class TestTaintMutationSelfCheck:
    """실행 파일을 건드리지 않고, 동일 로직을 깨뜨린 사본으로 변별력을 확인한다."""

    @pytest.mark.parametrize(
        ("label", "old", "new", "red", "green"),
        [m for m in _MUTATIONS if m[3]],
        ids=[m[0] for m in _MUTATIONS if m[3]],
    )
    def test_mutation_turns_the_scenarios_red(
        self, label, old, new, red, green, tmp_path, monkeypatch, capsys
    ):
        before = _MIRROR_PATH.read_bytes()
        mutant, _original = _mutated_module(tmp_path / "mutant", old, new)
        for name in red:
            sandbox = tmp_path / f"red_{name}"
            sandbox.mkdir()
            with pytest.raises(AssertionError):
                SCENARIOS[name](mutant, sandbox, monkeypatch, capsys)
        # 대조: 주입이 닿지 않아야 하는 시나리오는 사본에서도 GREEN이다 — 하네스 결함이 RED로
        # 위장되지 않았다는 증거다(전부 RED면 가드가 아니라 하네스를 의심한다).
        for name in green:
            sandbox = tmp_path / f"green_{name}"
            sandbox.mkdir()
            SCENARIOS[name](mutant, sandbox, monkeypatch, capsys)
        assert _MIRROR_PATH.read_bytes() == before, "뮤테이션이 원본 소스를 건드렸다"

    def test_m20_total_count_is_stated_when_the_listing_is_cut(self, tmp_path):
        """M20: 8건 초과 목록에서 "외 N건"을 빼면 총수가 사라진다 — 요약 문장 단위로 확인한다."""
        mutant, _ = _mutated_module(tmp_path / "mutant", "more = total - len(shown)", "more = 0")
        tree = {
            "state": "mutated",
            "head_start": "a",
            "head_end": "a",
            "changes_total": 12,
            "changes": [{"path": f"f{i}", "kind": "added"} for i in range(12)],
        }
        assert "외 4건" in mirror.summarize_tree(tree)
        assert "외 4건" not in mutant.summarize_tree(tree), "주입이 닿지 않았다"

    def test_every_mutation_has_a_distinct_anchor_and_label(self):
        assert len({m[0] for m in _MUTATIONS}) == len(_MUTATIONS) == 22
        assert len({(m[1], m[2]) for m in _MUTATIONS}) == len(_MUTATIONS), "같은 주입이 중복이다"
        referenced = {n for m in _MUTATIONS for n in (*m[3], *m[4])}
        assert referenced <= set(SCENARIOS), sorted(referenced - set(SCENARIOS))
