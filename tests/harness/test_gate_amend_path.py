"""HARN-124 — 게이트 문면·독촉 주기 정정 경로(`gates amend`)의 계약 동결.

배경(2026-09-22 실측): `--title`·`--remind-after-days`는 `gates add` 전용이었다. 한 번
등재된 게이트의 제목이 틀려도 고칠 CLI가 **0개**였고(대장 손편집은 CLAUDE.md 금지),
그 제목은 매 세션 SessionStart 브리핑에 그대로 노출돼 Kiki께 드리는 실행 안내의 원본이
된다 — 틀린 문면이 그대로 틀린 조작을 부른다. HARN-57(done 증적)·HARN-59(paths)·
HARN-67(depends/gate/notes)에 이은 **정정 경로 부재 4번째 사례**.

이 파일이 계약으로 동결하는 것 (acceptance ②③⑤):
  ② **정정이 읽는 쪽 화면까지 닿는가** — 이 축이 이 파일의 존재 이유다. 저장 필드만
     바꾸고 표시 경로가 옛 값을 보면 "정정했는데 화면은 옛 문면"이 되고, 그것은 정정
     경로가 없는 것보다 나쁘다(고쳤다고 믿게 만든다).
  ③ 거부 4종(게이트 부재·--reason 누락·정정 대상 누락·무변경)은 **파일 바이트 동일**.
  ⑤ `corrections`는 append-only이며 **YAML 왕복에서 리스트로 되읽힌다**.

**변별력 설계 — 이 파일이 실제로 무엇을 밟는가 (CLAUDE.md 「픽스처가 그 절을 실제로
밟는가」):**

첫 시도의 대조는 변별력이 0이었다. 오늘 등재한 게이트(`remind_after_days=60`)의 제목을
고치고 브리핑 before/after를 떴는데 "동일"이 나왔다 — `report.overdue_gates()`는
**독촉일이 지난 pending 게이트만** 내놓으므로 그 게이트는 before에도 after에도 애초에
없었다. 즉 "동일"은 정상 동작이었고, 내 대조가 그 절을 한 번도 밟지 않았다.

그래서 이 파일의 픽스처는 `requested`를 **40일 전으로 주입**해 게이트를 실제로 독촉
초과 상태로 만든다(`gates add`는 requested를 오늘로 박으므로 store 수준 주입이 필요하다).
그 위에서 두 축이 각각 갈린다:
  · 문면 축 — 브리핑 줄의 **텍스트**가 옛 제목 → 새 제목으로 바뀐다.
  · 주기 축 — `--remind-after-days 90`이면 40일 경과 게이트가 브리핑에서 **사라진다**
    (판정 자체가 뒤집힌다). 그리고 다시 30으로 되돌리면 **돌아온다** — 방향 양쪽을
    다 재야 "항상 사라지는" 구현도 통과하지 못한다.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest
import store

import backlog as cli

_GATE = "G-harn124-fixture"
_OLD_TITLE = "옛 문면 — 11/22 마감"
_NEW_TITLE = "새 문면 — 상한 11/22 · 선행 완료 즉시 앞당겨 판정"


@pytest.fixture
def seeded_repo(git_repo: Path, monkeypatch) -> Path:
    monkeypatch.chdir(git_repo)
    assert cli.main(["seed"]) == 0
    return git_repo


def _gates_bytes(repo: Path) -> bytes:
    return (repo / "backlog" / "gates.yaml").read_bytes()


def _gate(repo: Path):
    backlog, _ = store.load_backlog(repo)
    return backlog.gates[_GATE]


def _overdue_gate(repo: Path, *, days_ago: int = 40, remind: int = 30) -> None:
    """독촉일을 **이미 넘긴** pending 게이트를 만든다.

    왜 store로 주입하는가: `gates add`는 `requested`를 항상 오늘로 박는다(옳다 — 등재일은
    등재 시점이다). 그래서 CLI만으로는 "독촉 초과" 상태 자체를 만들 수 없고, 그 상태를
    안 만들면 브리핑 축의 검사가 정상/뮤테이션 양쪽에서 같은 화면을 낸다. 등재 자체는
    CLI 정상 경로로 통과시키고 `requested`만 과거로 옮긴다.
    """
    assert (
        cli.main(
            [
                "gates",
                "add",
                _GATE,
                "--title",
                _OLD_TITLE,
                "--remind-after-days",
                str(remind),
                # HARN-174: 여는 작업(--depends) 또는 입력 없음 사유 중 하나가 필수다
                "--no-inputs",
                "테스트 픽스처 — 입력 태스크 없음",
            ]
        )
        == 0
    )
    backlog, _ = store.load_backlog(repo)
    gate = backlog.gates[_GATE]
    gate.requested = (date.today() - timedelta(days=days_ago)).isoformat()
    store.save_gates(repo, sorted(backlog.gates.values(), key=lambda g: g.id))


def _brief(capsys) -> str:
    assert cli.main(["brief"]) == 0
    return capsys.readouterr().out


def _events(repo: Path, kind: str) -> list[dict]:
    rows: list[dict] = []
    for path in (repo / "backlog" / "events").glob("*.ndjson"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("action") == kind:
                rows.append(row)
    return rows


class TestBriefingActuallyChanges:
    """acceptance ② — 정정이 **읽는 쪽 화면**까지 닿는가."""

    def test_fixture_gate_is_genuinely_overdue(self, seeded_repo, capsys):
        """픽스처 자체의 변별력 검사 — 이게 없으면 아래 두 테스트가 공허하게 통과한다.

        브리핑에 애초에 안 나오는 게이트로 before/after를 뜨면 "동일"이 나오고, 그것을
        '변화 없음'으로 읽으면 배선 미완을 통과로 선언하게 된다(이 태스크의 첫 시도가
        정확히 그렇게 실패했다).
        """
        _overdue_gate(seeded_repo)
        out = _brief(capsys)
        assert "게이트 리마인드" in out
        assert _GATE in out
        assert "40일 경과" in out

    def test_title_correction_reaches_the_briefing(self, seeded_repo, capsys):
        _overdue_gate(seeded_repo)
        before = _brief(capsys)
        assert _OLD_TITLE in before
        assert _NEW_TITLE not in before

        assert (
            cli.main(["gates", "amend", _GATE, "--title", _NEW_TITLE, "--reason", "마감 표기 정정"])
            == 0
        )
        capsys.readouterr()

        after = _brief(capsys)
        assert _NEW_TITLE in after, "정정한 제목이 브리핑에 안 닿는다 — acceptance ② 실패"
        assert _OLD_TITLE not in after, "옛 제목이 브리핑에 남았다 — 실효값 덮어쓰기 미배선"

    def test_remind_cycle_correction_flips_the_overdue_verdict_both_ways(self, seeded_repo, capsys):
        """주기 정정이 **독촉 판정 자체**를 뒤집는지 — 양방향으로 잰다.

        한 방향만 재면 "amend 후 항상 사라진다"는 구현도 통과한다. 되돌렸을 때 다시
        나타나는 것까지 봐야 판정이 `remind_after_days`를 실제로 읽는다는 증거가 된다.
        """
        _overdue_gate(seeded_repo, days_ago=40, remind=30)
        assert _GATE in _brief(capsys)

        # 40일 경과 < 90일 독촉 → 브리핑에서 빠져야 한다
        assert (
            cli.main(
                [
                    "gates",
                    "amend",
                    _GATE,
                    "--remind-after-days",
                    "90",
                    "--reason",
                    "판정 시점을 뒤로 미룸",
                ]
            )
            == 0
        )
        capsys.readouterr()
        assert _GATE not in _brief(capsys), "주기를 늘렸는데 독촉이 그대로다 — 판정 미배선"

        # 되돌리면 다시 나타나야 한다 (대조군)
        assert (
            cli.main(["gates", "amend", _GATE, "--remind-after-days", "30", "--reason", "원복"])
            == 0
        )
        capsys.readouterr()
        assert _GATE in _brief(capsys), "주기를 되돌렸는데 독촉이 안 돌아온다 — 방향 편향"

    def test_gates_list_and_show_reflect_the_correction(self, seeded_repo, capsys):
        """브리핑 외 나머지 읽는 쪽 2곳 — 한 곳이라도 옛 값을 보면 정정이 반쪽이다."""
        _overdue_gate(seeded_repo)
        assert cli.main(["gates", "amend", _GATE, "--title", _NEW_TITLE, "--reason", "정정"]) == 0
        capsys.readouterr()

        assert cli.main(["gates", "list"]) == 0
        listed = capsys.readouterr().out
        assert _NEW_TITLE in listed and _OLD_TITLE not in listed

        assert cli.main(["gates", "show", _GATE]) == 0
        shown = capsys.readouterr().out
        assert _NEW_TITLE in shown


class TestRejectionsWriteNothing:
    """acceptance ③ — 거부 4종은 전부 exit 1 + gates.yaml **바이트 동일**.

    "거부했다"와 "거부하고 아무것도 안 썼다"는 다르다. 부분 기입이 남으면 다음 정정이
    옛 값이 아니라 반쯤 쓰인 값 위에서 일어난다.
    """

    def test_missing_gate_rejected(self, seeded_repo, capsys):
        _overdue_gate(seeded_repo)
        before = _gates_bytes(seeded_repo)
        assert (
            cli.main(["gates", "amend", "G-does-not-exist", "--title", "x", "--reason", "y"]) == 1
        )
        assert "없음" in capsys.readouterr().err
        assert _gates_bytes(seeded_repo) == before

    def test_missing_reason_rejected(self, seeded_repo, capsys):
        _overdue_gate(seeded_repo)
        before = _gates_bytes(seeded_repo)
        assert cli.main(["gates", "amend", _GATE, "--title", _NEW_TITLE]) == 1
        assert "--reason" in capsys.readouterr().err
        assert _gates_bytes(seeded_repo) == before

    def test_no_field_given_rejected(self, seeded_repo, capsys):
        _overdue_gate(seeded_repo)
        before = _gates_bytes(seeded_repo)
        assert cli.main(["gates", "amend", _GATE, "--reason", "사유만 있음"]) == 1
        assert "정정할 것이 없다" in capsys.readouterr().err
        assert _gates_bytes(seeded_repo) == before

    def test_noop_change_rejected(self, seeded_repo, capsys):
        """현행과 같은 값 = 정정이 아니다. 허용하면 실효 변화 0인 이력만 쌓여
        corrections가 '무엇이 실제로 바뀌었나'의 기록이 아니게 된다."""
        _overdue_gate(seeded_repo)
        before = _gates_bytes(seeded_repo)
        assert cli.main(["gates", "amend", _GATE, "--title", _OLD_TITLE, "--reason", "무변경"]) == 1
        assert "현행과 같다" in capsys.readouterr().err
        assert _gates_bytes(seeded_repo) == before


class TestCorrectionsAreAppendOnlyAndSurviveYaml:
    """acceptance ⑤ — 이력 보존. 정정은 *덮어쓰기*이므로 옛 값은 여기서만 복원된다."""

    def test_history_accumulates_and_keeps_the_original_title(self, seeded_repo, capsys):
        _overdue_gate(seeded_repo)
        assert cli.main(["gates", "amend", _GATE, "--title", _NEW_TITLE, "--reason", "1차"]) == 0
        assert (
            cli.main(["gates", "amend", _GATE, "--remind-after-days", "90", "--reason", "2차"]) == 0
        )
        capsys.readouterr()

        gate = _gate(seeded_repo)
        assert len(gate.corrections) == 2
        # 원 제목은 첫 기록 안에 남아 복원 가능해야 한다 — 덮어쓰기 설계의 전제다
        assert _OLD_TITLE in gate.corrections[0]
        assert "1차" in gate.corrections[0] and "2차" in gate.corrections[1]
        assert "remind_after_days: 30 → 90" in gate.corrections[1]

    def test_corrections_round_trip_as_a_list_not_a_string(self, seeded_repo, capsys):
        """YAML 왕복 계약. 종전 `dump_gates`는 전 필드를 한 줄 스칼라로 썼는데, 리스트를
        그대로 넘기면 파이썬 repr(`['a', 'b']`)이 인용돼 **문자열 하나로 되읽히고**
        이력이 조용히 뭉개진다 — 무증상이므로 계약으로 동결한다."""
        _overdue_gate(seeded_repo)
        assert cli.main(["gates", "amend", _GATE, "--title", _NEW_TITLE, "--reason", "정정"]) == 0
        capsys.readouterr()

        raw = (seeded_repo / "backlog" / "gates.yaml").read_text(encoding="utf-8")
        assert "['" not in raw, "리스트가 파이썬 repr로 직렬화됐다 — 되읽으면 문자열 1건"

        gate = _gate(seeded_repo)
        assert isinstance(gate.corrections, list)
        assert len(gate.corrections) == 1

    def test_amend_leaves_status_and_evidence_untouched(self, seeded_repo, capsys):
        """`waive`와의 경계 — amend는 요건을 **해금하지 않는다**. 이 구분이 없으면
        "문면만 고치려다 대기 태스크가 풀리는" 사고가 난다."""
        _overdue_gate(seeded_repo)
        assert cli.main(["gates", "amend", _GATE, "--title", _NEW_TITLE, "--reason", "정정"]) == 0
        capsys.readouterr()
        gate = _gate(seeded_repo)
        assert gate.status == "pending"
        assert gate.evidence is None

    def test_event_records_what_changed(self, seeded_repo, capsys):
        _overdue_gate(seeded_repo)
        assert (
            cli.main(["gates", "amend", _GATE, "--title", _NEW_TITLE, "--reason", "표기 정정"]) == 0
        )
        capsys.readouterr()
        rows = [r for r in _events(seeded_repo, "gate_amend") if r["id"] == _GATE]
        assert len(rows) == 1
        assert rows[0]["reason"] == "표기 정정"
        assert _OLD_TITLE in rows[0]["changes"] and _NEW_TITLE in rows[0]["changes"]
