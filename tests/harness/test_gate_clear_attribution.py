"""게이트 clear의 주체 기록 (HARN-60) — "누가 닫았나"를 대장이 답할 수 있는가.

**왜 이 파일이 있는가**

이벤트의 `actor`는 **브랜치명**이다(실측: 'claude/git-unshallow-repo-crr6x5', 'main').
사람이 닫았는지 에이전트가 닫았는지를 담지 못한다. 준수 감사 A3은 "에이전트의 사람 게이트
clear"를 심각도 높음으로 보는데, 그 준수를 사후 증명할 유일한 채널이 git 저자였다 — 그리고
이 저장소는 스쿼시 머지만 허용하므로(merge·rebase 405) 저자는 머지 수행자로 덮이고 브랜치
ref는 자동 삭제된다. 즉 **증거가 복원 불가능**했다. 그래서 증거를 git 메타데이터가 아니라
대장 데이터(`gates.yaml` + 이벤트)에 둔다.

**양방향으로 본다.** 사람 표기가 사람으로 기록되는 것만 확인하면, *모든 clear를 사람으로
기록하는* 구현도 절반은 통과한다. 그래서 표기 없는 clear가 **에이전트로** 기록되는지를 같은
비중으로 동결한다(CLAUDE.md "변별력 없는 검증 스텝 금지").

**금지하지 않고 기록한다.** 에이전트가 사람 게이트를 clear하는 것은 실제로 일어나는 정당한
중계다(Kiki가 자기 머신에서 실행 → 출력 전달 → 세션이 기입). 거부하면 대장 CLI를 우회한
YAML 손편집으로 밀려나고 그때는 아무 기록도 안 남는다. 목표는 금지가 아니라 증명 가능성이다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import store
from models import Gate

import backlog as cli

# seed가 만드는 사람(kiki) 소유 게이트 — 이 파일의 대상.
_KIKI_GATE = "G-phaiakes9-key"


@pytest.fixture
def seeded_repo(git_repo: Path, monkeypatch) -> Path:
    """seed까지 끝난 저장소 (cwd 고정)."""
    monkeypatch.chdir(git_repo)
    assert cli.main(["seed"]) == 0
    return git_repo


def _gate(repo: Path, gate_id: str) -> Gate:
    backlog, errors = store.load_backlog(repo)
    assert not errors, f"대장 스키마 오류: {errors}"
    return backlog.gates[gate_id]


def _clear_events(repo: Path) -> list[dict]:
    """gate_clear 이벤트만 — 레거시 + 세션 샤드 합집합(HARN-46 이후의 정본 읽기)."""
    rows: list[dict] = []
    for path in store.event_paths(repo):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("action") == "gate_clear":
                rows.append(record)
    return rows


# 이 파일의 evidence 인자에 커밋 해시가 붙어 있는 것은 HARN-68 계약 때문이다:
# `gates clear`는 evidence에 판정 기준(커밋 해시·PR 참조)을 요구한다. 이 테스트들의
# 관심사는 주체 기록(HARN-60)이지 판정 기준이 아니므로, 해시는 통과용 최소 표기다.
class TestSubjectIsRecordedBothWays:
    """주체가 **양방향**으로 갈린다 — 한쪽만 보면 '항상 같은 값'이 통과한다."""

    def test_human_self_attested_clear_records_person(self, seeded_repo: Path):
        """사람표기_clear는_사람으로_기록"""
        assert (
            cli.main(
                [
                    "gates",
                    "clear",
                    _KIKI_GATE,
                    "--as",
                    "kiki",
                    "--evidence",
                    "Kiki 실행 완료 (main 3b007e23 기준)",
                ]
            )
            == 0
        )
        gate = _gate(seeded_repo, _KIKI_GATE)
        assert gate.status == "cleared"
        assert gate.cleared_by == "kiki"
        events = _clear_events(seeded_repo)
        assert len(events) == 1
        assert events[0]["cleared_by"] == "kiki"

    def test_clear_without_attestation_records_agent(self, seeded_repo: Path):
        """표기없는_clear는_에이전트로_기록 — 이 방향이 없으면 검사가 위장이 된다.

        거부가 아니라 *사실대로 기록*이다: 대장 CLI를 우회한 손편집으로 밀려나면 아무 기록도
        남지 않아 더 나빠지기 때문이다.
        """
        assert (
            cli.main(
                [
                    "gates",
                    "clear",
                    _KIKI_GATE,
                    "--evidence",
                    "세션이 중계 기입 (main 3b007e23 기준)",
                ]
            )
            == 0
        )
        gate = _gate(seeded_repo, _KIKI_GATE)
        assert gate.status == "cleared"
        assert gate.cleared_by == "claude"
        events = _clear_events(seeded_repo)
        assert len(events) == 1
        assert events[0]["cleared_by"] == "claude"

    def test_two_directions_differ(self, seeded_repo: Path):
        """같은 게이트를 두 방식으로 닫으면 **다른 값**이 남는다 — 변별력 자체의 동결.

        위 두 테스트가 각각 통과해도 값이 같으면 주체 기록은 무의미하다. 그 축을 직접 잰다.
        """
        assert cli.main(["gates", "clear", _KIKI_GATE, "--evidence", "e1 3b007e23"]) == 0
        agent_value = _gate(seeded_repo, _KIKI_GATE).cleared_by
        assert (
            cli.main(["gates", "clear", _KIKI_GATE, "--as", "kiki", "--evidence", "e2 3b007e23"])
            == 0
        )
        human_value = _gate(seeded_repo, _KIKI_GATE).cleared_by
        assert agent_value != human_value, "두 경로가 같은 값을 내면 주체 기록이 아니다"
        assert (agent_value, human_value) == ("claude", "kiki")


class TestAttestationIsNotForgeable:
    """자기기입 표기가 아무 이름이나 통과하면 기록이 아니라 장식이다."""

    def test_mismatched_owner_rejected(self, seeded_repo: Path):
        """남의_게이트를_자기이름으로_닫기_거부 (done/start의 --as 불일치 검사와 동형)"""
        assert cli.main(["gates", "clear", _KIKI_GATE, "--as", "partner", "--evidence", "x"]) == 1
        gate = _gate(seeded_repo, _KIKI_GATE)
        assert gate.status == "pending", "거부됐는데 상태가 바뀌면 안 된다"
        assert gate.cleared_by is None
        assert _clear_events(seeded_repo) == []

    def test_claude_is_not_a_valid_attestation(self, seeded_repo: Path):
        """--as claude 는 선택지 자체가 아니다 — 에이전트가 '사람처럼' 표기할 길을 막는다."""
        with pytest.raises(SystemExit) as exc:  # argparse choices 위반 → exit 2
            cli.main(["gates", "clear", _KIKI_GATE, "--as", "claude", "--evidence", "x"])
        assert exc.value.code == 2
        assert _gate(seeded_repo, _KIKI_GATE).status == "pending"

    def test_evidence_still_required(self, seeded_repo: Path):
        """주체 표기가 evidence 필수 규칙을 무력화하지 않는다(기존 계약 보존)."""
        assert cli.main(["gates", "clear", _KIKI_GATE, "--as", "kiki"]) == 1
        assert _gate(seeded_repo, _KIKI_GATE).status == "pending"


class TestLegacyRowsStayUnknown:
    """HARN-60 이전 행은 '미상'으로 남는다 — 소급 추정은 날조다(acceptance ④)."""

    def test_cleared_row_without_subject_loads_as_unknown(self, seeded_repo: Path):
        """cleared_by 없는 기존 행이 무결성 오류를 내지 않고 None으로 적재된다.

        스쿼시 머지가 git 저자를 덮었으므로 기존 20건의 주체는 **사후에 알 수 없다**.
        추정으로 채우면 대장이 거짓을 말하게 되므로, 비어 있는 것이 정답이다.
        """
        gates_path = seeded_repo / "backlog" / "gates.yaml"
        raw = gates_path.read_text(encoding="utf-8")
        # HARN-60 이전 형태를 그대로 재현 — `cleared_by` 줄이 **아예 없는** YAML.
        legacy = raw.replace("    cleared_by: null\n", "")
        assert legacy != raw, "제거 대상이 없으면 이 테스트는 아무것도 재현하지 못한다"
        assert "cleared_by" not in legacy
        gates_path.write_text(legacy, encoding="utf-8")

        backlog, errors = store.load_backlog(seeded_repo)
        assert not errors, f"레거시 행이 스키마 오류를 내면 안 된다: {errors}"
        # 필드가 없던 행은 dataclass 기본값(None = 미상)으로 적재된다.
        assert all(g.cleared_by is None for g in backlog.gates.values())

    def test_unknown_subject_is_displayed_not_guessed(self, seeded_repo: Path, capsys):
        """목록이 미상을 '미상'으로 보인다 — 빈칸으로 숨기지도, 추정으로 채우지도 않는다."""
        # 주체 없이 cleared 상태를 직접 만든다(HARN-60 이전 행 모사).
        backlog, _ = store.load_backlog(seeded_repo)
        gate = backlog.gates[_KIKI_GATE]
        gate.status = "cleared"
        gate.evidence = "레거시 근거"
        gate.cleared_by = None
        store.save_gates(seeded_repo, sorted(backlog.gates.values(), key=lambda g: g.id))
        assert cli.main(["gates"]) == 0
        out = capsys.readouterr().out
        assert "미상(HARN-60 이전)" in out


class TestSchemaGuard:
    """자유 문자열이 주체 필드로 새어 들어오지 않는다."""

    def test_unregistered_owner_is_a_validation_error(self):
        """등록되지 않은 소유자는 무결성 오류 — 오타·임의 문자열 차단."""
        gate = Gate(
            id="G-x",
            title="t",
            status="cleared",
            evidence="e",
            cleared_by="kiki_typo",
        )
        assert any("cleared_by" in e for e in gate.validate())

    def test_registered_owner_and_none_are_both_valid(self):
        """등록 소유자와 미상(None) 둘 다 정상 — 미상을 오류로 만들면 레거시가 전부 red가 된다."""
        for value in ("kiki", "partner", "claude", None):
            gate = Gate(id="G-x", title="t", status="cleared", evidence="e", cleared_by=value)
            assert not [e for e in gate.validate() if "cleared_by" in e], value
