"""HARN-100 — 태스크 ID 개명 경로(`backlog.py rename`).

배경(2026-09-12 실측): `validate`의 번호 충돌 remedy는 "하나를 다음 빈 번호로 개명하라"인데
**개명 명령 자체가 없었다**. 실제로 충돌이 났을 때(`OPS-73`) `add`(새 번호) + 구 파일
`git rm` + `start` 재claim으로 우회했고, 그 과정에서 구 태스크의 이벤트 이력과 원격 claim이
새 ID로 이어지지 않았다. 고칠 수 없는 위반을 지적하는 게이트는 사람이 게이트를 끄게 만든다
(`EOS-62`의 `amend --depends` 부재와 같은 형태 — HARN-67이 남긴 "정정 경로 부재" 계보).

이 파일이 계약으로 동결하는 것:
  · 거부 4종 — 없는 old-id · 이미 쓰이는 new-id · 규약 밖 new-id · 번호 충돌(add와 동일 판정)
  · **성공 방향 대조군** — 정상 개명 1건이 파일·`id` 필드·`depends_on`을 전부 옮긴다.
    이것이 없으면 "전부 거부"라는 과잉 수정이 통과한다(CLAUDE.md 2026-09-08).
  · 거부 시 **파일 바이트 동일** — 부분 적용된 채 실패하지 않는다.
  · 옮기지 **않은 것**(과거 이벤트·문서 참조)을 stdout에 명시한다 — 조용한 부분 이행 금지.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import store

import backlog as cli


@pytest.fixture
def seeded_repo(git_repo: Path, monkeypatch) -> Path:
    monkeypatch.chdir(git_repo)
    assert cli.main(["seed"]) == 0
    return git_repo


def _add(task_id: str, *extra: str) -> int:
    return cli.main(
        [
            "add",
            "--eos-priority",
            "P2",
            "--id",
            task_id,
            "--title",
            "HARN-100 테스트 태스크",
            "--track",
            "math-completion",
            "--stage",
            "S1",
            *extra,
        ]
    )


def _task_bytes(repo: Path, task_id: str) -> bytes:
    return (repo / "backlog" / "tasks" / f"{task_id}.yaml").read_bytes()


def _events(repo: Path, action: str) -> list[dict]:
    return [
        json.loads(line)
        for path in store.event_paths(repo)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line).get("action") == action
    ]


class TestRenameHappyPath:
    """[성공 방향 대조군] 정상 개명이 실제로 전부 옮긴다.

    거부 테스트만 있으면 "무조건 exit 1"이라는 과잉 수정이 전건 통과한다 — 그 상태는
    개명 경로가 *없는* 것과 구별되지 않는다(그리고 그것이 이 태스크의 원 증상이다).
    """

    def test_renames_file_and_id_field(self, seeded_repo, capsys):
        """파일명과_id_필드가_함께_옮겨간다"""
        assert _add("ZQ-01-old-slug") == 0
        assert (
            cli.main(["rename", "ZQ-01-old-slug", "ZQ-02-new-slug", "--reason", "번호 충돌"]) == 0
        )

        assert not (seeded_repo / "backlog" / "tasks" / "ZQ-01-old-slug.yaml").exists()
        backlog, _ = store.load_backlog(seeded_repo)
        assert "ZQ-01-old-slug" not in backlog.tasks
        assert backlog.tasks["ZQ-02-new-slug"].id == "ZQ-02-new-slug"

    def test_dependents_are_repointed_and_counted(self, seeded_repo, capsys):
        """구_ID를_선행으로_가리키던_태스크가_전수_갱신되고_건수가_출력된다

        여기서 빠뜨리면 `audit-deps`가 존재하지 않는 선행을 지목하고, 그 태스크는 영원히
        착수 후보에서 빠진다 — 조용히.
        """
        assert _add("ZQ-01-old-slug") == 0
        assert _add("ZQ-03-dependent", "--depends", "ZQ-01-old-slug") == 0
        capsys.readouterr()
        assert cli.main(["rename", "ZQ-01-old-slug", "ZQ-02-new-slug", "--reason", "충돌"]) == 0

        backlog, _ = store.load_backlog(seeded_repo)
        assert backlog.tasks["ZQ-03-dependent"].depends_on == ["ZQ-02-new-slug"]
        assert "depends_on 갱신 1건" in capsys.readouterr().out

    def test_rename_event_links_old_to_new(self, seeded_repo):
        """rename_이벤트가_구↔신을_잇는다 — 과거 기록을 고쳐 쓰지 않는 대신 링크를 남긴다"""
        assert _add("ZQ-01-old-slug") == 0
        assert cli.main(["rename", "ZQ-01-old-slug", "ZQ-02-new-slug", "--reason", "충돌"]) == 0

        events = _events(seeded_repo, "rename")
        assert len(events) == 1
        assert events[0]["id"] == "ZQ-02-new-slug"
        assert events[0]["previous_id"] == "ZQ-01-old-slug"

    def test_reports_what_it_did_not_move(self, seeded_repo, capsys):
        """옮기지_않은_것을_화면에_명시한다 — 조용한 부분 이행이 이 CLI의 최대 실패 모드다"""
        assert _add("ZQ-01-old-slug") == 0
        capsys.readouterr()
        assert cli.main(["rename", "ZQ-01-old-slug", "ZQ-02-new-slug", "--reason", "충돌"]) == 0

        out = capsys.readouterr().out
        # 고지는 **두 건**이고 성격이 다르다 — 하나로 뭉뚱그려 단언하면 한쪽을 지워도
        # 통과한다(뮤테이션 M8 생존으로 실제로 확인하고 갈랐다).
        assert "과거 이벤트 기록" in out, "append-only 대장을 안 고쳤다는 사실이 빠졌다"
        assert "문서·커밋 메시지·PR 본문" in out, "CLI 범위 밖 참조가 남는다는 사실이 빠졌다"
        assert "git grep" in out, "남은 참조를 어떻게 찾는지까지 안내해야 실행 가능한 고지다"


class TestRenameRejections:
    """거부 4종 — 각각 *그 절이 없으면 통과해 버리는* 입력을 쓴다."""

    def test_missing_old_id_is_rejected(self, seeded_repo):
        """없는_구_ID는_거부된다"""
        assert cli.main(["rename", "ZQ-99-nope", "ZQ-02-new", "--reason", "x"]) == 1

    def test_existing_new_id_is_rejected_without_touching_either_file(self, seeded_repo):
        """이미_쓰이는_새_ID는_거부되고_두_파일_모두_바이트_동일하다

        이 단언이 없으면 "덮어쓰고 성공"이 통과한다 — 그러면 개명이 태스크 하나를 삼킨다.
        """
        assert _add("ZQ-01-old-slug") == 0
        assert _add("ZQ-02-taken") == 0
        before_old = _task_bytes(seeded_repo, "ZQ-01-old-slug")
        before_new = _task_bytes(seeded_repo, "ZQ-02-taken")

        assert cli.main(["rename", "ZQ-01-old-slug", "ZQ-02-taken", "--reason", "x"]) == 1
        assert _task_bytes(seeded_repo, "ZQ-01-old-slug") == before_old
        assert _task_bytes(seeded_repo, "ZQ-02-taken") == before_new

    def test_same_id_is_rejected_with_its_own_message(self, seeded_repo, capsys):
        """구_ID와_새_ID가_같으면_전용_문구로_거부된다

        exit 1만 보면 이 절은 **죽은 코드**다 — 같은 ID는 `new_id in backlog.tasks`에도
        걸려 어차피 거부되기 때문이다(뮤테이션 M3 생존으로 실제로 확인했다). 이 절이
        존재할 이유는 *사유가 다르다*는 것뿐이므로, 그 사유가 화면에 나오는지를 본다 —
        "이미 존재한다"는 같은 ID를 넣은 사람에게 원인을 잘못 짚어 준다.
        """
        assert _add("ZQ-01-old-slug") == 0
        capsys.readouterr()
        assert cli.main(["rename", "ZQ-01-old-slug", "ZQ-01-old-slug", "--reason", "x"]) == 1
        assert "개명할 것이 없다" in capsys.readouterr().err
        assert _events(seeded_repo, "rename") == []

    def test_malformed_new_id_is_rejected(self, seeded_repo):
        """규약_밖_새_ID는_거부된다 — 소문자 접두는 TASK_ID_RE 위반

        이 절이 없으면 `load_backlog`가 나중에 스키마 오류로 터지는데, 그때는 이미 파일이
        옮겨진 뒤라 대장이 깨진 채로 남는다.
        """
        assert _add("ZQ-01-old-slug") == 0
        before = _task_bytes(seeded_repo, "ZQ-01-old-slug")
        assert cli.main(["rename", "ZQ-01-old-slug", "zq-2-bad", "--reason", "x"]) == 1
        assert _task_bytes(seeded_repo, "ZQ-01-old-slug") == before

    def test_number_collision_uses_the_same_judgment_as_add(self, seeded_repo, capsys):
        """번호_충돌은_add와_같은_함수로_판정된다 — 판정이 두 벌로 갈라지지 않는다

        `ZQ-02`가 이미 다른 슬러그로 점유돼 있으면 `add`가 거부하는 것과 **같은 이유로**
        `rename`도 거부해야 한다. 여기서 갈라지면 개명이 번호 충돌을 새로 만든다.
        """
        assert _add("ZQ-01-old-slug") == 0
        assert _add("ZQ-02-taken-number") == 0
        capsys.readouterr()
        assert cli.main(["rename", "ZQ-01-old-slug", "ZQ-02-different-slug", "--reason", "x"]) == 1
        assert "번호 충돌" in capsys.readouterr().err
