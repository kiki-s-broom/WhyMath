"""HARN-33 — 대장 저장이 사람이 쓴 블록 스칼라(`notes: |`)를 뭉개지 않는다.

배경(2026-08-21 실측): `G-amd395-perf-baseline` 등재 때 `gates add` 1회가
`G-operator-seat-first-grant`의 60줄 런북형 notes를 `\\n` 이스케이프된 한 줄 문자열로
바꿨다. 내용은 같지만 사람이 읽는 형태가 파손됐고, 대장 손편집은 금지라 되돌릴 수도 없었다.

이 파일이 동결하는 것:
  ① 재현 — 블록 스칼라를 가진 대장에 `gates add`를 1회 하면 그 줄이 바뀌던 것.
  ② 판정치 — "내용 동일"이 아니라 **`git diff --numstat` 삭제 줄 0**(순수 추가분만).
  ③ 집행 지점 — add/clear/waive와 태스크 저장이 전부 저장 함수 1곳(`save_gates`·
     `save_task`)을 지나고, 그 경로를 타는 이 테스트가 CI(`tests/harness`)에서 돈다.
  ④ 범위 밖 — **기존 JSON 인용 값은 그대로 둔다**(일괄 재포맷은 사람 판단). 실측: 현재
     대장에는 블록 스칼라가 0건이고 개행 포함 값이 JSON 한 줄로 26줄 실려 있다. 그래서
     "개행이 있으면 무조건 블록으로"는 첫 조작에 그 26줄을 전부 바꾼다 — 이 파일이
     `TestLegacyQuotedIsLeftAlone`로 막는 반대편 실패다.

**픽스처가 각 절을 밟는가** (CLAUDE.md 보호 장치 규칙): 텍스트가 `status:`·`- id:`·`#`로
시작하는 줄, 선행 공백 줄, 후행 개행 0/1/2개, 공백만 있는 줄, 탭·CR·유니코드 줄바꿈 문자를
일부러 넣었다 — 블록 스칼라는 이런 값에서 조용히 내용을 바꾸는 표기이기 때문이다.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import store
import yaml
from models import Gate, Task

import backlog as cli

_RUNBOOK_GATE = "G-runbook-fixture"
_OTHER_GATE = "G-zother-fixture"  # 정렬상 런북 게이트 뒤 — 조작 대상(사고의 형태)
_PLACEHOLDER = "PLACEHOLDER_NOTES"


def _runbook_text(lines: int = 60) -> str:
    """런북형 notes — 블록 스칼라에서 위험한 줄 형태를 골고루 섞는다."""
    body = [f'{i:02d}. 단계 설명 줄 — 콜론: 포함, "인용" 포함' for i in range(lines - 8)]
    body += [
        "",  # 중간 빈 줄
        "status: cleared",  # 줄 파서가 키로 오인할 수 있는 형태
        "- id: G-not-a-gate",  # 게이트 경계로 오인할 수 있는 형태
        "# 주석처럼 보이는 줄",
        "  들여쓴 줄(선행 공백)",
        "\t탭으로 시작하는 줄",
        "끝줄 — 후행 공백  ",
    ]
    return "\n".join(body) + "\n"


def _as_block(key: str, text: str, indent: str = "      ") -> str:
    """사람이 손으로 쓰는 블록 스칼라 표기(clip). 줄마다 indent, 빈 줄은 빈 줄."""
    out = [f"    {key}: |"]
    for line in text.rstrip("\n").split("\n"):
        out.append(f"{indent}{line}" if line else "")
    return "\n".join(out) + "\n"


def _git(repo: Path, *argv: str) -> str:
    result = subprocess.run(["git", *argv], cwd=repo, capture_output=True, text=True, check=True)
    return result.stdout


def _numstat(repo: Path, relpath: str) -> tuple[int, int]:
    """(추가 줄, 삭제 줄) — 커밋된 HEAD 대비 작업 트리."""
    out = _git(repo, "diff", "--numstat", "HEAD", "--", relpath).split()
    return int(out[0]), int(out[1])


def _seed_runbook_repo(repo: Path, monkeypatch, *, block: bool = True) -> str:
    """블록 스칼라 notes를 가진 게이트가 커밋된 대장을 만든다. 만든 notes 원문을 돌려준다.

    나머지 줄이 전부 `dump_gates`의 정본 표기여야 "삭제 줄 0"이 notes 줄만 겨냥한다 —
    그래서 손으로 쓰지 않고 dumper로 쓴 뒤 notes 한 줄만 블록 표기로 치환한다.
    """
    monkeypatch.chdir(repo)
    store.save_tracks(repo, ["S1"], [])
    store.save_gates(
        repo,
        [
            Gate(
                id=_RUNBOOK_GATE,
                title="런북형 게이트",
                requested="2026-08-01",
                notes=_PLACEHOLDER,
                no_inputs_reason="테스트 픽스처 — 입력 태스크 없음",
            ),
            Gate(
                id=_OTHER_GATE,
                title="다른 게이트",
                requested="2026-08-01",
                no_inputs_reason="테스트 픽스처 — 입력 태스크 없음",
            ),
        ],
    )
    path = repo / "backlog" / "gates.yaml"
    text = path.read_text(encoding="utf-8")
    notes = _runbook_text()
    anchor = f"    notes: {_PLACEHOLDER}\n"
    assert text.count(anchor) == 1, "픽스처 앵커가 정확히 1건이어야 한다(치환 대상 실재)"
    replaced = text.replace(anchor, _as_block("notes", notes) if block else anchor)
    assert (replaced != text) is block, "블록 치환이 실제로 적용됐는지 단언(주입 실재)"
    path.write_text(replaced, encoding="utf-8")
    # 손으로 쓴 형태가 PyYAML이 읽는 값과 같은지 먼저 못 박는다 — 픽스처 자체의 검증.
    loaded = yaml.safe_load(replaced)["gates"][0]["notes"]
    assert loaded == (notes if block else _PLACEHOLDER)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "fixture: 런북형 notes")
    return notes


def _gate_notes_on_disk(repo: Path) -> str:
    backlog, errors = store.load_backlog(repo)
    assert not [e for e in errors if _RUNBOOK_GATE in e], errors
    return backlog.gates[_RUNBOOK_GATE].notes


class TestGateCliKeepsBlockScalar:
    """①②③ — 사람이 읽는 블록 표기가 add/clear/waive 1회로 바뀌지 않는다."""

    def test_gates_add_changes_only_additions(self, git_repo: Path, monkeypatch):
        """gates_add는_순수_추가분만_diff에_뜬다(삭제_줄_0)"""
        notes = _seed_runbook_repo(git_repo, monkeypatch)
        assert (
            cli.main(["gates", "add", "G-added-after", "--title", "추가분", "--no-inputs", "사유"])
            == 0
        )
        added, deleted = _numstat(git_repo, "backlog/gates.yaml")
        assert deleted == 0, "기존 게이트 표기가 조작 1회로 바뀌었다(60줄 → 1줄 사고의 재현)"
        assert added > 0
        text = (git_repo / "backlog" / "gates.yaml").read_text(encoding="utf-8")
        assert "    notes: |\n" in text, "블록 스칼라 헤더가 사라졌다"
        assert "\\n" not in text.split("G-added-after")[0], "notes가 이스케이프 한 줄로 뭉개졌다"
        assert _gate_notes_on_disk(git_repo) == notes

    @pytest.mark.parametrize(
        "argv",
        [
            ["gates", "clear", _OTHER_GATE, "--evidence", "커밋 abc1234 확인", "--as", "kiki"],
            ["gates", "waive", _OTHER_GATE, "--reason", "대체 결정으로 불필요"],
        ],
        ids=["clear", "waive"],
    )
    def test_operating_on_another_gate_keeps_the_runbook_block(
        self, git_repo: Path, monkeypatch, argv
    ):
        """다른_게이트_clear·waive도_같은_저장_함수를_지나_런북_블록을_보존(사고의_형태)"""
        notes = _seed_runbook_repo(git_repo, monkeypatch)
        assert cli.main(argv) == 0
        text = (git_repo / "backlog" / "gates.yaml").read_text(encoding="utf-8")
        assert _as_block("notes", notes) in text, "notes 블록이 원문 그대로 남아야 한다"
        assert _gate_notes_on_disk(git_repo) == notes

    def test_clearing_the_runbook_gate_itself_keeps_its_notes(self, git_repo: Path, monkeypatch):
        """런북_게이트_자신을_clear해도_notes_블록은_그대로(clear는_notes를_안_건드린다)"""
        notes = _seed_runbook_repo(git_repo, monkeypatch)
        argv = ["gates", "clear", _RUNBOOK_GATE, "--evidence", "커밋 abc1234 확인", "--as", "kiki"]
        assert cli.main(argv) == 0
        text = (git_repo / "backlog" / "gates.yaml").read_text(encoding="utf-8")
        assert _as_block("notes", notes) in text
        assert _gate_notes_on_disk(git_repo) == notes


class TestLegacyQuotedIsLeftAlone:
    """④ — 이미 JSON 한 줄인 기존 값은 건드리지 않는다(대량 재포맷은 사람 판단)."""

    def test_quoted_multiline_notes_stay_byte_identical(self, git_repo: Path, monkeypatch):
        """JSON_인용_개행_notes는_gates_add_후에도_바이트_동일"""
        monkeypatch.chdir(git_repo)
        store.save_tracks(git_repo, ["S1"], [])
        notes = "첫 줄\n둘째 줄\n\n[정정] 넷째 줄\n"
        # '현재 대장의 26줄'과 같은 상태를 dumper 비의존으로 만든다: 자리표시자로 쓴 뒤
        # notes 줄만 JSON 인용 한 줄로 교체한다.
        store.save_gates(
            git_repo,
            [
                Gate(
                    id=_RUNBOOK_GATE,
                    title="레거시",
                    requested="2026-08-01",
                    notes=_PLACEHOLDER,
                    no_inputs_reason="픽스처",
                )
            ],
        )
        path = git_repo / "backlog" / "gates.yaml"
        quoted_line = f"    notes: {json.dumps(notes, ensure_ascii=False)}\n"
        anchor = f"    notes: {_PLACEHOLDER}\n"
        text = path.read_text(encoding="utf-8")
        assert text.count(anchor) == 1
        path.write_text(text.replace(anchor, quoted_line), encoding="utf-8")
        assert yaml.safe_load(path.read_text(encoding="utf-8"))["gates"][0]["notes"] == notes
        _git(git_repo, "add", "-A")
        _git(git_repo, "commit", "-qm", "fixture: 레거시 인용 notes")

        args = ["gates", "add", "G-added-after", "--title", "추가", "--no-inputs", "사유"]
        assert cli.main(args) == 0
        added, deleted = _numstat(git_repo, "backlog/gates.yaml")
        assert added > 0
        assert deleted == 0, "레거시 JSON 값이 블록으로 일괄 재포맷됐다(④ 범위 밖 위반)"
        assert quoted_line in path.read_text(encoding="utf-8")


class TestFreshMultilineBecomesBlock:
    """새로 쓰는 개행 값은 사람이 읽는 블록으로 — 그리고 왕복이 바이트 안정이다."""

    def test_new_gate_with_multiline_notes_is_a_block(self, tmp_path: Path):
        notes = _runbook_text(12)
        store.save_gates(
            tmp_path,
            [
                Gate(
                    id="G-fresh",
                    title="새",
                    requested="2026-08-01",
                    notes=notes,
                    no_inputs_reason="픽스처",
                )
            ],
        )
        text = (tmp_path / "backlog" / "gates.yaml").read_text(encoding="utf-8")
        assert "    notes: |\n" in text
        backlog, errors = store.load_backlog(tmp_path)
        assert backlog.gates["G-fresh"].notes == notes

    def test_roundtrip_is_byte_stable(self, tmp_path: Path):
        """저장 → 로드 → 저장이 같은 바이트(멱등) — 두 번째 저장이 diff를 만들지 않는다"""
        gates = [
            Gate(
                id="G-one",
                title="하나",
                requested="2026-08-01",
                notes=_runbook_text(10),
                evidence="근거 1줄\n근거 2줄\n",
                no_inputs_reason="픽스처",
            ),
            Gate(
                id="G-two",
                title="둘",
                requested="2026-08-01",
                notes="단일 줄",
                no_inputs_reason="픽스처",
            ),
        ]
        store.save_gates(tmp_path, gates)
        first = (tmp_path / "backlog" / "gates.yaml").read_bytes()
        loaded, _ = store.load_backlog(tmp_path)
        store.save_gates(tmp_path, sorted(loaded.gates.values(), key=lambda g: g.id))
        assert (tmp_path / "backlog" / "gates.yaml").read_bytes() == first


# 블록 스칼라가 조용히 내용을 바꾸는 값들 — 어느 쪽으로 쓰든 읽은 값은 원문과 같아야 한다.
_TRICKY = {
    "no_trailing_newline": "a\nb",
    "one_trailing_newline": "a\nb\n",
    "two_trailing_newlines": "a\nb\n\n",
    "three_trailing_newlines": "a\n\n\n",
    "leading_blank_line": "\nlead",
    "leading_space_first_line": "  indented first\nsecond",
    "leading_space_then_blank": " x\n\ny\n",
    "only_newline": "\n",
    "only_newlines": "\n\n",
    "internal_blank_runs": "a\n\n\nb\n",
    "whitespace_only_line": "a\n   \nb\n",
    "trailing_spaces": "trail  \nspaces  \n",
    "tab_content": "x\n\ttab\n",
    "key_like_lines": "status: x\n- id: y\n# c\n",
    "yaml_special_start": "- a\n? b\n: c\n",
    "unicode": "한글\n日本語\nemoji 😀\n",
    "carriage_return": "a\r\nb\r\n",
    "nel": "a\x85b\n",
    "line_separator": "a b\nc",
    "paragraph_separator": "a b\nc",
    "control_char": "a\x01b\nc",
    "c1_control": "a\x9fb\nc",
    "del_char": "a\x7fb\nc",
    "bom": "﻿a\nb",
    "colon_space": "k: v\nk2: v2",
    "hash_space": "a #b\nc",
    "document_marker": "---\n...\n",
}


@pytest.mark.parametrize("name", sorted(_TRICKY))
def test_tricky_values_roundtrip_exactly(tmp_path: Path, name: str):
    """어떤 값도 저장 후 읽은 값이 원문과 다르지 않다(블록으로 못 쓰면 인용으로 물러난다)"""
    value = _TRICKY[name]
    store.save_gates(
        tmp_path,
        [
            Gate(
                id="G-edge",
                title="경계",
                requested="2026-08-01",
                notes=value,
                no_inputs_reason="픽스처",
            )
        ],
    )
    backlog, errors = store.load_backlog(tmp_path)
    assert not [e for e in errors if "G-edge" in e], errors
    assert backlog.gates["G-edge"].notes == value, f"{name}: 내용이 바뀌었다"


class TestTaskSaveSharesTheRule:
    """③ — 태스크 저장(`save_task`)도 같은 규칙을 탄다. 별도 구현이 아니다."""

    def _task(self, **kw) -> Task:
        base = dict(id="S1-01-alpha", title="알파", track="t", stage="S1", updated="2026-08-01")
        base.update(kw)
        return Task(**base)

    def test_new_task_multiline_notes_is_a_block(self, tmp_path: Path):
        notes = "첫 줄\n\n[정정 2026-09-01] 둘째 줄\n"
        store.save_task(tmp_path, self._task(notes=notes))
        text = (tmp_path / "backlog" / "tasks" / "S1-01-alpha.yaml").read_text(encoding="utf-8")
        # 들여쓰기 칸수(키 열 0 + 2)까지 못 박는다 — 어긋나도 내용은 같게 읽혀 왕복만으론 못 잡는다.
        assert "\nnotes: |\n  첫 줄\n\n  [정정 2026-09-01] 둘째 줄\n" in text
        assert yaml.safe_load(text)["notes"] == notes

    def test_existing_quoted_task_notes_stay_quoted(self, tmp_path: Path):
        """현재 대장 태스크 560건의 상태 — 저장 1회로 560건이 바뀌면 안 된다"""
        notes = "첫 줄\n\n[정정] 둘째 줄"
        store.save_task(tmp_path, self._task(notes="PLACEHOLDER"))
        path = tmp_path / "backlog" / "tasks" / "S1-01-alpha.yaml"
        quoted = f"notes: {json.dumps(notes, ensure_ascii=False)}\n"
        path.write_text(
            path.read_text(encoding="utf-8").replace("notes: PLACEHOLDER\n", quoted),
            encoding="utf-8",
        )
        before = path.read_bytes()
        loaded, _ = store.load_backlog(tmp_path)
        store.save_task(tmp_path, loaded.tasks["S1-01-alpha"])
        assert path.read_bytes() == before, "레거시 인용 notes가 재포맷됐다"


# 블록으로 *써야* 하는 값 / 인용으로 *물러나야* 하는 값. 왕복 동일성만 보면 블록 생성이 조용히
# 인용으로 물러나도(들여쓰기 지시자·chomping 누락 등) 통과한다 — 그래서 표기 자체를 단언한다.
_MUST_BE_BLOCK = [
    "no_trailing_newline",
    "one_trailing_newline",
    "two_trailing_newlines",
    "three_trailing_newlines",
    "leading_blank_line",
    "leading_space_first_line",
    "leading_space_then_blank",
    "internal_blank_runs",
    "whitespace_only_line",
    "trailing_spaces",
    "tab_content",
    "key_like_lines",
    "yaml_special_start",
    "unicode",
    "colon_space",
    "hash_space",
    "document_marker",
]
_MUST_BE_QUOTED = [
    "carriage_return",
    "nel",
    "line_separator",
    "paragraph_separator",
    "control_char",
    "c1_control",
    "del_char",
    "bom",
]


def _notes_line(tmp_path: Path, value: str) -> str:
    store.save_gates(
        tmp_path,
        [
            Gate(
                id="G-edge",
                title="경계",
                requested="2026-08-01",
                notes=value,
                no_inputs_reason="픽스처",
            )
        ],
    )
    text = (tmp_path / "backlog" / "gates.yaml").read_text(encoding="utf-8")
    return next(line for line in text.splitlines() if line.startswith("    notes:"))


@pytest.mark.parametrize("name", _MUST_BE_BLOCK)
def test_blockable_values_are_actually_written_as_blocks(tmp_path: Path, name: str):
    """블록으로 쓸 수 있는 값이 조용히 인용으로 물러나지 않는다(표기 단언)"""
    assert _notes_line(tmp_path, _TRICKY[name]).startswith("    notes: |"), name


@pytest.mark.parametrize("name", _MUST_BE_QUOTED)
def test_unsafe_values_fall_back_to_escaped_quotes(tmp_path: Path, name: str):
    """블록에 날것으로 못 두는 문자는 인용으로 물러나고, 인용 안에서도 날것으로 남지 않는다"""
    line = _notes_line(tmp_path, _TRICKY[name])
    assert not line.startswith("    notes: |"), name
    # YAML이 줄바꿈·비출력으로 취급하는 문자는 인용 안에서도 \\uXXXX로 쓴다(\\x85가 \\n으로
    # 읽히던 기존 결함의 재발 방지 — 이 파일 맨 위 `nel` 케이스가 변경 전에도 RED였다).
    assert not any(ch in line for ch in "\x85\x9f\x7f  "), name


def test_folded_scalar_is_rewritten_as_literal_with_same_content(git_repo: Path, monkeypatch):
    """손으로 쓴 `>`(접힌 스칼라)는 `|`로 바뀔 수 있어도 읽은 값은 같다(한계의 동결)"""
    _seed_runbook_repo(git_repo, monkeypatch, block=False)
    path = git_repo / "backlog" / "gates.yaml"
    anchor = f"    notes: {_PLACEHOLDER}\n"
    text = path.read_text(encoding="utf-8")
    assert text.count(anchor) == 1
    folded = "    notes: >\n      alpha\n      beta\n\n      gamma\n"
    path.write_text(text.replace(anchor, folded), encoding="utf-8")
    expected = yaml.safe_load(path.read_text(encoding="utf-8"))["gates"][0]["notes"]
    assert (
        expected == "alpha beta\ngamma\n"
    ), "픽스처가 접힘 의미를 실제로 밟는지(접힘이 없으면 무의미)"
    _git(git_repo, "add", "-A")
    _git(git_repo, "commit", "-qm", "fixture: 접힌 스칼라")

    assert (
        cli.main(["gates", "add", "G-added-after", "--title", "추가", "--no-inputs", "사유"]) == 0
    )
    assert _gate_notes_on_disk(git_repo) == expected
    # 접힌 스칼라가 JSON 한 줄로 뭉개지지 않았다 — 표기는 블록(`|`)으로 남는다.
    assert "    notes: |" in (git_repo / "backlog" / "gates.yaml").read_text(encoding="utf-8")


def test_unparseable_existing_file_still_saves_and_names_the_exception(tmp_path: Path, capsys):
    """기존 파일이 깨져 있어도 저장은 되고, 스캔 실패는 예외 타입명과 함께 stderr에 남는다"""
    path = tmp_path / "backlog" / "gates.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("gates: [unclosed\n", encoding="utf-8")
    store.save_gates(
        tmp_path,
        [Gate(id="G-ok", title="정상", requested="2026-08-01", no_inputs_reason="픽스처")],
    )
    err = capsys.readouterr().err
    try:
        yaml.compose("gates: [unclosed\n")
    except yaml.YAMLError as exc:
        expected_name = type(exc).__name__
    else:  # pragma: no cover - 픽스처가 깨진 YAML이 아니면 이 테스트는 의미가 없다
        raise AssertionError("픽스처가 파싱돼 버렸다")
    assert expected_name in err, f"예외 타입명({expected_name})이 로그에 없다(무타입 경고 금지)"
    backlog, errors = store.load_backlog(tmp_path)
    assert "G-ok" in backlog.gates
