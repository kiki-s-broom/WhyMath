"""게이트 clear의 판정 기준 요구 계약 동결 (HARN-68).

규칙 정본은 CLAUDE.md "미머지 존재를 '충족'으로 단정 금지"(2026-09-06 등재)이고, 이 파일은
그 규칙의 **게이트 clear 축** 집행이 실제로 변별력을 갖는지를 동결한다.

판정은 시점에 종속된다 — "그 산출물이 있다"는 *언제의 트리에서* 봤느냐에 따라 참이거나
거짓이다. 사고 경위: 2026-09-05 Gate 0 검토가 **미머지** PR #986을 Gate 0-B 근거로 달았고,
같은 세션의 "고아 3건 소유자 부여 완료" 보고도 셋 다 미머지였다.

양방향으로 본다: 기준 없으면 거부(①), 있으면 통과(②③), 탈출구는 흔적을 남긴다(④).
②③이 없으면 "항상 거부"하는 검사도 ①을 통과하고, 그런 검사는 정상 상태에서 사람이
게이트를 끄게 만든다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import store

import backlog as cli


@pytest.fixture
def repo_with_gate(git_repo: Path, monkeypatch) -> Path:
    """시딩된 저장소 + pending 게이트 하나."""
    monkeypatch.chdir(git_repo)
    assert cli.main(["seed"]) == 0
    return git_repo


def _events(repo: Path) -> str:
    return "".join(path.read_text(encoding="utf-8") for path in store.event_paths(repo))


def _gate(repo: Path, gate_id: str = "G-phaiakes9-key"):
    backlog, _ = store.load_backlog(repo)
    return backlog.gates[gate_id]


class TestJudgmentBaseRequired:
    def test_evidence_without_base_is_rejected(self, repo_with_gate: Path):
        """기준_없는_evidence는_거부 — 이 검사의 존재 이유."""
        rc = cli.main(["gates", "clear", "G-phaiakes9-key", "--evidence", "확인했고 문제 없었다"])
        assert rc == 1
        # 거부해 놓고 상태를 바꾸면 최악이다 — 대장은 그대로여야 한다.
        assert _gate(repo_with_gate).status == "pending"
        assert _gate(repo_with_gate).evidence is None

    def test_commit_hash_passes(self, repo_with_gate: Path):
        """커밋_해시가_있으면_통과 — 대조군."""
        rc = cli.main(
            [
                "gates",
                "clear",
                "G-phaiakes9-key",
                "--evidence",
                "main 3b007e23 기준으로 키 등록 확인",
            ]
        )
        assert rc == 0
        assert _gate(repo_with_gate).status == "cleared"

    def test_pr_reference_passes(self, repo_with_gate: Path):
        """PR_참조도_기준으로_인정 — done의 PR 증적(HARN-23)과 같은 표기를 받는다."""
        rc = cli.main(["gates", "clear", "G-phaiakes9-key", "--evidence", "PR #908 머지 후 확인"])
        assert rc == 0
        assert _gate(repo_with_gate).status == "cleared"

    def test_long_hash_passes(self, repo_with_gate: Path):
        """sha256도_받는다 — 문서 정규화 해시를 증적으로 쓴 선례(G0 검증설계 동결)."""
        sha = "a9ad9f6ab7d4b065bf0c89d67e57e1d7cf827b6a4f4db4866a49c605d3553e3a"
        rc = cli.main(["gates", "clear", "G-phaiakes9-key", "--evidence", f"§5 sha256={sha}"])
        assert rc == 0
        assert _gate(repo_with_gate).status == "cleared"

    def test_date_alone_is_not_a_base(self, repo_with_gate: Path):
        """날짜만으로는_통과하지_않는다 — 날짜는 '언제 봤나'지 '무엇을 봤나'가 아니다."""
        rc = cli.main(
            ["gates", "clear", "G-phaiakes9-key", "--evidence", "2026-09-06 Kiki 확인 완료"]
        )
        assert rc == 1
        assert _gate(repo_with_gate).status == "pending"


class TestEscapeHatch:
    def test_no_base_allows_clear(self, repo_with_gate: Path):
        """탈출구는_실제로_열린다 — 사람 게이트의 정당한 근거에는 커밋과 무관한 것이 많다."""
        rc = cli.main(
            [
                "gates",
                "clear",
                "G-phaiakes9-key",
                "--evidence",
                "GitHub 환경 생성 및 리뷰어 등록 완료",
                "--no-base",
                "저장소 밖 설정 작업이라 대응 커밋이 없다",
            ]
        )
        assert rc == 0
        assert _gate(repo_with_gate).status == "cleared"

    def test_no_base_reason_is_recorded_in_ledger_and_events(self, repo_with_gate: Path):
        """탈출구_사용은_흔적을_남긴다 (acceptance ②).

        남지 않는 탈출구는 게이트를 끄는 것과 같다 — 나중에 "왜 기준이 없었나"를
        물을 수 있어야 한다. 대장(notes)과 이벤트 **양쪽**에 남는지 본다.
        """
        reason = "저장소 밖 설정 작업이라 대응 커밋이 없다"
        assert (
            cli.main(
                [
                    "gates",
                    "clear",
                    "G-phaiakes9-key",
                    "--evidence",
                    "GitHub 환경 생성 완료",
                    "--no-base",
                    reason,
                ]
            )
            == 0
        )
        assert reason in (_gate(repo_with_gate).notes or "")
        assert reason in _events(repo_with_gate)

    def test_normal_clear_leaves_no_escape_marker(self, repo_with_gate: Path):
        """기준이_있으면_탈출구_흔적이_없다 — 대조군.

        정상 경로가 조용해야 탈출구 흔적이 신호가 된다. 모든 clear에 마커가 붙으면
        그 마커는 아무것도 구별하지 못한다.
        """
        assert (
            cli.main(["gates", "clear", "G-phaiakes9-key", "--evidence", "main 3b007e23 기준 확인"])
            == 0
        )
        assert "판정기준 없음" not in (_gate(repo_with_gate).notes or "")


class TestUnaffectedPaths:
    def test_waive_is_not_gated(self, repo_with_gate: Path):
        """waive는_이_검사의_대상이_아니다 — 면제는 '판정했다'가 아니라 '판정하지 않기로 했다'다."""
        rc = cli.main(["gates", "waive", "G-phaiakes9-key", "--reason", "범위에서 제외"])
        assert rc == 0
        assert _gate(repo_with_gate).status == "waived"

    def test_empty_evidence_still_rejected_first(self, repo_with_gate: Path):
        """evidence_자체가_없으면_기존_거부가_먼저 — 새 검사가 기존 계약을 가리지 않는다."""
        rc = cli.main(["gates", "clear", "G-phaiakes9-key"])
        assert rc == 1
        assert _gate(repo_with_gate).status == "pending"
