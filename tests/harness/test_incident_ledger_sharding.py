"""HARN-130 — 사고 대장 세션 샤딩 계약 동결 (HARN-46 이벤트 대장 샤딩의 2회차).

## 무엇을 왜 동결하나 (사고 경위)

사고 대장(`backlog/incidents.ndjson`)은 HARN-118로 착지하면서 HARN-46이 이벤트 대장에서
배운 두 방어(`merge=union` · 세션 샤딩) 중 **어느 것도** 받지 못했다. 등재 CLI는 대장
전체를 날짜순으로 다시 썼으므로, 같은 날 사고를 적은 두 PR은 파일 끝의 같은 자리에 서로
다른 줄을 넣어 충돌했다 — 2026-09-21 PR #1255가 머지 큐에서 `MERGE_CONFLICT`로 이탈했고,
2026-09-28 PR #1363(EOS-25)은 재병합 직후 같은 충돌을 한 번 더 냈다(계열
`incident-ledger-merge-conflict`). `merge=union`은 로컬 git만 돕는다 — GitHub 서버는 저장소
merge driver를 적용하지 않는다. 그래서 정본 방어는 샤딩이다.

그리고 대장만 나누면 끝나지 않았다. 파생 인덱스 `backlog/jit_index.json`이 사고와 함께
바뀌어(main에서 그 파일을 바꾼 커밋 26건 중 25건이 사고 대장도 바꿨다) 같은 두 PR이
거기서 다시 충돌했다. 그래서 인덱스를 커밋하지 않는다 — 적시 주입 후보는 편집 시 대장에서
계산한다(`test_jit_rules.py`의 인덱스 축 계약).

## 동결 축 (acceptance와 1:1)

  ① 배선 — `.gitattributes`에 두 사고 대장 패턴의 union(로컬 방어)이 실재
  ③ 쓰기 샤딩 — `incident add`가 세션 샤드에 append하고 레거시 대장은 바이트 불변
  ④ 읽기 합집합 — 레거시 + 샤드 전부. 회차는 파일 경계를 넘어 날짜 순이고, 같은 날은
     레거시 → 샤드 이름순. 2회차 강제(`repeat_settlement_error`)도 합집합을 본다
  ⑤ 변별력 — 두 브랜치를 실제로 git 머지한다. **이관 전 배치**(공용 파일 재기록 +
     커밋 인덱스)는 충돌을 내고, 이관 후 배치는 충돌 없이 합쳐진다. 전자가 없으면 후자의
     초록은 '원래 충돌이 안 나는 입력'과 구별되지 않는다.

임시 저장소에는 `.gitattributes`가 없다 — merge driver를 적용하지 않는 GitHub 서버와 같은
조건에서 머지한다(이 저장소의 union 선언은 로컬 방어일 뿐이라는 사실을 그대로 재현).
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict
from datetime import date
from pathlib import Path

import incidents as inc
import jit_rules
import pytest
import store

import backlog as cli

REPO_ROOT = Path(__file__).resolve().parents[2]
TODAY = date.today().isoformat()


def _git(repo: Path, *argv: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *argv],
        cwd=repo,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=check,
    )


def _incident(title: str, **overrides: object) -> inc.Incident:
    base: dict[str, object] = {
        "date": "2026-09-01",
        "cat": "G",
        "title": title,
        "fix_form": "task",
        "fix_ref": "HARN-901",
    }
    base.update(overrides)
    return inc.Incident(**base)  # type: ignore[arg-type]


def _add(title: str, *extra: str) -> int:
    argv = ["incident", "add", "--title", title, "--cat", "G"]
    if "--fix-form" not in extra:
        argv += ["--fix-form", "task", "--fix-ref", "HARN-901"]
    return cli.main([*argv, *extra])


@pytest.fixture
def seeded_repo(git_repo: Path, monkeypatch) -> Path:
    """시드 + 상환 태스크 1건(`src/x/**`) — 사고 fix_ref가 경로로 풀리게 한다."""
    monkeypatch.chdir(git_repo)
    assert cli.main(["seed"]) == 0
    assert (
        cli.main(
            [
                "add",
                "--id",
                "HARN-901-fix",
                "--title",
                "픽스처 상환 태스크",
                "--track",
                "math-completion",
                "--stage",
                "S2",
                "--path",
                "src/x/**",
                "--eos-priority",
                "P3",
            ]
        )
        == 0
    )
    return git_repo


def _shard(root: Path, branch: str) -> Path:
    return inc.shard_path(root, store.session_shard_name(branch))


# ── ① 배선 — .gitattributes 로컬 방어 ─────────────────────────────────────


class TestUnionAttributeWiring:
    def test_gitattributes_declares_both_incident_patterns(self) -> None:
        """로컬 머지 방어 — 레거시 파일과 샤드 패턴 둘 다. 서버 충돌을 막는 것은 샤딩이다."""
        lines = [
            line.split()
            for line in (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        assert ["backlog/incidents.ndjson", "merge=union"] in lines
        assert ["backlog/incidents/*.ndjson", "merge=union"] in lines


# ── ③ 쓰기 샤딩 ─────────────────────────────────────────────────────────────


class TestShardWrite:
    def test_add_appends_to_the_session_shard_and_leaves_the_legacy_ledger(
        self, seeded_repo: Path, capsys
    ) -> None:
        inc.save_incidents(seeded_repo, [_incident("레거시 1"), _incident("레거시 2")])
        legacy_before = inc.ledger_path(seeded_repo).read_bytes()
        _git(seeded_repo, "checkout", "-q", "-b", "claude/alpha")

        assert _add("알파 사고") == 0
        assert "incidents/claude_alpha.ndjson" in capsys.readouterr().out

        assert inc.ledger_path(seeded_repo).read_bytes() == legacy_before
        shard = _shard(seeded_repo, "claude/alpha")
        lines = shard.read_text(encoding="utf-8").splitlines()
        assert [json.loads(line)["title"] for line in lines] == ["알파 사고"]

    def test_repeated_adds_append_in_order(self, seeded_repo: Path) -> None:
        _git(seeded_repo, "checkout", "-q", "-b", "claude/alpha")
        assert _add("첫째") == 0
        assert _add("둘째") == 0
        lines = _shard(seeded_repo, "claude/alpha").read_text(encoding="utf-8").splitlines()
        assert [json.loads(line)["title"] for line in lines] == ["첫째", "둘째"]

    def test_incident_and_event_share_the_session_key(self, seeded_repo: Path) -> None:
        """한 세션의 기록이 대장마다 다른 파일명으로 흩어지지 않는다(같은 함수로 이름을 정한다)."""
        _git(seeded_repo, "checkout", "-q", "-b", "claude/alpha")
        assert _add("알파 사고") == 0
        name = store.session_shard_name("claude/alpha")
        events = (seeded_repo / "backlog" / "events" / name).read_text(encoding="utf-8")
        assert '"incident_add"' in events
        assert (seeded_repo / "backlog" / "incidents" / name).exists()

    def test_different_branches_write_disjoint_files(self, seeded_repo: Path) -> None:
        _git(seeded_repo, "checkout", "-q", "-b", "claude/alpha")
        assert _add("알파 사고") == 0
        _git(seeded_repo, "checkout", "-q", "-b", "claude/beta")
        assert _add("베타 사고") == 0
        alpha = _shard(seeded_repo, "claude/alpha")
        beta = _shard(seeded_repo, "claude/beta")
        assert alpha != beta
        assert "베타 사고" not in alpha.read_text(encoding="utf-8")
        assert "알파 사고" not in beta.read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        "name", ["../escape.ndjson", "a/b.ndjson", "", ".hidden.ndjson", "/abs.ndjson"]
    )
    def test_shard_path_refuses_anything_but_one_file_name(self, tmp_path: Path, name) -> None:
        with pytest.raises(ValueError):
            inc.shard_path(tmp_path, name)


# ── ④ 읽기 합집합 ───────────────────────────────────────────────────────────


def _write_shard(root: Path, name: str, incidents: list[inc.Incident]) -> None:
    path = inc.shard_path(root, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(inc.to_line(i) + "\n" for i in incidents), encoding="utf-8")


class TestReadUnion:
    def test_load_reads_legacy_then_shards_by_name(self, tmp_path: Path) -> None:
        inc.save_incidents(tmp_path, [_incident("레거시")])
        _write_shard(tmp_path, "b.ndjson", [_incident("B")])
        _write_shard(tmp_path, "a.ndjson", [_incident("A")])
        ledger, errors = inc.load_incidents(tmp_path)
        assert errors == []
        assert [i.title for i in ledger] == ["레거시", "A", "B"]

    def test_shard_only_repo_is_read(self, tmp_path: Path) -> None:
        """레거시 파일이 없어도 샤드는 읽힌다 — 레거시 부재를 '대장 없음'으로 접지 않는다."""
        _write_shard(tmp_path, "a.ndjson", [_incident("A")])
        ledger, errors = inc.load_incidents(tmp_path)
        assert errors == [] and [i.title for i in ledger] == ["A"]

    def test_nth_follows_dates_across_files(self, tmp_path: Path) -> None:
        """샤드의 더 이른 사고가 레거시의 나중 사고보다 앞 회차다 — 파일 순서가 아니다."""
        inc.save_incidents(
            tmp_path, [_incident("레거시 9/10", date="2026-09-10", series_id="alpha")]
        )
        _write_shard(
            tmp_path, "a.ndjson", [_incident("샤드 9/01", date="2026-09-01", series_id="alpha")]
        )
        ledger, _ = inc.load_incidents(tmp_path)
        nth = dict(zip([i.title for i in ledger], inc.compute_nth(ledger), strict=True))
        assert nth == {"레거시 9/10": 2, "샤드 9/01": 1}

    def test_same_date_ties_break_legacy_first_then_shard_name(self, tmp_path: Path) -> None:
        inc.save_incidents(tmp_path, [_incident("L", date="2026-09-05", series_id="alpha")])
        _write_shard(tmp_path, "z.ndjson", [_incident("Z", date="2026-09-05", series_id="alpha")])
        _write_shard(tmp_path, "a.ndjson", [_incident("A", date="2026-09-05", series_id="alpha")])
        ledger, _ = inc.load_incidents(tmp_path)
        nth = dict(zip([i.title for i in ledger], inc.compute_nth(ledger), strict=True))
        assert nth == {"L": 1, "A": 2, "Z": 3}

    def test_report_counts_legacy_plus_shards(self, seeded_repo: Path, capsys) -> None:
        inc.save_incidents(seeded_repo, [_incident("레거시 1"), _incident("레거시 2")])
        _git(seeded_repo, "checkout", "-q", "-b", "claude/alpha")
        assert _add("알파 사고") == 0
        capsys.readouterr()
        assert cli.main(["incident", "report", "--json"]) == 0
        assert json.loads(capsys.readouterr().out)["total"] == 3

    def test_repeat_enforcement_sees_the_legacy_ledger(self, seeded_repo: Path, capsys) -> None:
        """2회차 강제는 합집합으로 센다 — 레거시의 1회차를 못 보면 2회차가 1회차로 통과한다."""
        inc.save_incidents(
            seeded_repo, [_incident("1회차", series_id="alpha", fix_form="rule", fix_ref="")]
        )
        _git(seeded_repo, "checkout", "-q", "-b", "claude/alpha")
        capsys.readouterr()
        assert _add("2회차", "--date", TODAY, "--series", "alpha", "--fix-form", "rule") == 1
        assert "alpha" in capsys.readouterr().err

    def test_repeat_enforcement_sees_other_shards(self, seeded_repo: Path, capsys) -> None:
        """다른 세션 샤드의 1회차(머지돼 들어온 것)도 센다."""
        _write_shard(
            seeded_repo,
            "claude_other.ndjson",
            [_incident("1회차", series_id="alpha", fix_form="rule", fix_ref="")],
        )
        _git(seeded_repo, "checkout", "-q", "-b", "claude/alpha")
        capsys.readouterr()
        assert _add("2회차", "--date", TODAY, "--series", "alpha", "--fix-form", "rule") == 1

    def test_error_location_names_the_shard(self, tmp_path: Path) -> None:
        inc.save_incidents(tmp_path, [_incident("정상")])
        (tmp_path / "backlog" / "incidents").mkdir(parents=True)
        (tmp_path / "backlog" / "incidents" / "claude_x.ndjson").write_text(
            "{broken\n", encoding="utf-8"
        )
        _, errors = inc.load_incidents(tmp_path)
        assert len(errors) == 1
        assert errors[0].startswith("incidents/claude_x.ndjson:1")


# ── ⑤ 변별력 — 두 브랜치 실제 머지 ────────────────────────────────────────


def _legacy_dump_index(notes: list[jit_rules.Note]) -> str:
    """이관 전 커밋 인덱스의 직렬화 — 재현 전용 사본(무게·종류·날짜·문구 순 · indent=1)."""
    ordered = sorted(notes, key=lambda n: (-n.weight, n.kind, n.ref, n.text))
    payload = {"version": 1, "max_notes": 5, "notes": [asdict(n) for n in ordered]}
    return json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=False) + "\n"


def _old_style_add(root: Path, title: str) -> None:
    """이관 전 등재 경로의 재현 — 공용 대장 통째 재기록 + 커밋 인덱스 재생성."""
    ledger, errors = inc.load_incidents(root)
    assert errors == []
    ledger.append(_incident(title, date=TODAY))
    ledger.sort(key=lambda i: i.date)
    inc.save_incidents(root, ledger)
    notes, errors = cli._build_jit_notes(root)
    assert errors == []
    (root / "backlog" / "jit_index.json").write_text(_legacy_dump_index(notes), encoding="utf-8")


def _commit_all(root: Path, message: str) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)


def _merge(root: Path, into: str, other: str) -> tuple[int, set[str]]:
    _git(root, "checkout", "-q", into)
    proc = _git(root, "merge", "--no-edit", other, check=False)
    conflicted = _git(root, "diff", "--name-only", "--diff-filter=U").stdout.split()
    return proc.returncode, set(conflicted)


class TestTwoBranchMerge:
    @staticmethod
    def _base(root: Path, *, legacy_index: bool) -> None:
        # GitHub 서버와 같은 조건 — 저장소 merge driver 없음.
        assert not (root / ".gitattributes").exists()
        inc.save_incidents(root, [_incident("기존 사고", date="2026-09-01")])
        if legacy_index:
            notes, _ = cli._build_jit_notes(root)
            (root / "backlog" / "jit_index.json").write_text(
                _legacy_dump_index(notes), encoding="utf-8"
            )
        _commit_all(root, "base")

    def test_pre_migration_layout_conflicts(self, seeded_repo: Path) -> None:
        """이관 전 배치 — 같은 날 사고를 적은 두 브랜치는 대장과 인덱스 두 곳에서 충돌한다.

        이 RED 재현이 아래 초록의 변별력이다. 이것이 초록이면 아래 테스트의 입력은 원래
        충돌이 나지 않는 입력이라, 샤딩이 무엇을 막았는지 말하지 못한다.
        """
        self._base(seeded_repo, legacy_index=True)
        _git(seeded_repo, "checkout", "-q", "-b", "claude/alpha")
        _old_style_add(seeded_repo, "알파 사고")
        _commit_all(seeded_repo, "alpha")
        _git(seeded_repo, "checkout", "-q", "main")
        _git(seeded_repo, "checkout", "-q", "-b", "claude/beta")
        _old_style_add(seeded_repo, "베타 사고")
        _commit_all(seeded_repo, "beta")

        rc, conflicted = _merge(seeded_repo, "claude/alpha", "claude/beta")
        assert rc != 0
        assert conflicted == {"backlog/incidents.ndjson", "backlog/jit_index.json"}

    def test_post_migration_layout_merges_cleanly(self, seeded_repo: Path, capsys) -> None:
        """이관 후 — 같은 시나리오를 실제 CLI로 돌리면 충돌 없이 합쳐지고 아무것도 잃지 않는다."""
        self._base(seeded_repo, legacy_index=False)
        _git(seeded_repo, "checkout", "-q", "-b", "claude/alpha")
        assert _add("알파 사고") == 0
        _commit_all(seeded_repo, "alpha")
        _git(seeded_repo, "checkout", "-q", "main")
        _git(seeded_repo, "checkout", "-q", "-b", "claude/beta")
        assert _add("베타 사고") == 0
        _commit_all(seeded_repo, "beta")

        rc, conflicted = _merge(seeded_repo, "claude/alpha", "claude/beta")
        assert conflicted == set()
        assert rc == 0

        ledger, errors = inc.load_incidents(seeded_repo)
        assert errors == []
        assert sorted(i.title for i in ledger) == ["기존 사고", "베타 사고", "알파 사고"]
        tracked = _git(seeded_repo, "ls-files", "--", "backlog/jit_index.json").stdout
        assert tracked.strip() == ""

        # 머지된 트리에서 적시 주입이 두 브랜치의 사고를 모두 본다 — 재생성 명령 없이.
        capsys.readouterr()
        assert cli.main(["jit", "show", "src/x/a.py"]) == 0
        shown = capsys.readouterr().out
        assert "알파 사고" in shown and "베타 사고" in shown
