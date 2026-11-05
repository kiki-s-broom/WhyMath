"""P3-102 — EOS-194 런북 [C2] 원자 오개념 적재 블록의 실행 조건 동결.

왜 필요한가
----------
[C2]는 운영 DB(`whymath-pg`)의 `misconception_catalog`에 원자 유래 오개념(`ATOM:<code>`)을 쓰는
블록이다. 2026-11-05 운영 실측은 `PUBLISHABLE=76`·오개념 서명 결손 903건이었는데, 당시 [C2]는
`PUBLISHABLE=0`일 때만 실행되게 막혀 있어 스스로 거부했다(쓰기 0). Kiki 결정(P3-102 · A안)으로
실행 조건을 "원자 행이 0이면 실행"으로 바꿨다.

이 테스트가 막는 회귀 두 가지:
- `PUBLISHABLE` 조건이 되살아나면 운영에서 다시 거부된다(A안 실행 불가).
- `ATOM_MISCONCEPTION_ROWS == 0` 조건이 빠지면 이미 적재된 DB에 다시 쓰게 된다(재적재 방지 축 소실).
또한 적재 후 확인값(1823)이 코퍼스 정본(`docs/data/corpus_facts.md`의 `atom_graph.atoms`)과
어긋나면 정상 적재도 `ATOM_LOAD_OK=False`로 보고되므로 둘을 대조한다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_RUNBOOK = _ROOT / "docs" / "ops" / "eos194_publish_measure_runbook.md"
_FACTS = _ROOT / "docs" / "data" / "corpus_facts.md"


def _c2_block(text: str) -> str:
    """[C2] 절의 첫 powershell 펜스 본문을 돌려준다(없으면 실패)."""
    section = text.split("### [C2]", 1)
    assert len(section) == 2, "런북에 [C2] 절이 없다"
    after = section[1].split("\n### ", 1)[0]
    m = re.search(r"```powershell\n(.*?)```", after, re.S)
    assert m, "[C2] 절에 powershell 블록이 없다"
    return m.group(1)


def _atom_ready_condition(block: str) -> str:
    """`$AtomReady = …` 대입식의 오른쪽을 돌려준다."""
    m = re.search(r"^\$AtomReady\s*=\s*(.+)$", block, re.M)
    assert m, "[C2] 블록에 $AtomReady 대입이 없다"
    return m.group(1)


def _corpus_atoms() -> int:
    m = re.search(
        r"\|\s*`atom_graph\.atoms`\s*\|\s*([\d,]+)\s*\|", _FACTS.read_text(encoding="utf-8")
    )
    assert m, "corpus_facts.md에 atom_graph.atoms 행이 없다"
    return int(m.group(1).replace(",", ""))


def test_c2_runs_regardless_of_publishable() -> None:
    """실행 조건에 PUBLISHABLE 항이 없어야 운영(PUBLISHABLE=76)에서 적재가 실행된다."""
    cond = _atom_ready_condition(_c2_block(_RUNBOOK.read_text(encoding="utf-8")))
    assert "PUBLISHABLE" not in cond, cond


def test_c2_refuses_when_atom_rows_exist() -> None:
    """원자 행이 이미 있으면(0이 아니면) 거부해야 한다 — 재적재 방지 축."""
    cond = _atom_ready_condition(_c2_block(_RUNBOOK.read_text(encoding="utf-8")))
    assert re.search(r"\(\$AtomRowsBefore -eq 0\)", cond), cond


def test_c2_write_is_inside_the_guard() -> None:
    """적재(populate_atom)와 백업은 `if ($AtomReady)`/`if ($ABackupOk)` 가지 안에서만 실행된다."""
    block = _c2_block(_RUNBOOK.read_text(encoding="utf-8"))
    for line in block.splitlines():
        if "pg_dump" in line:
            assert line.startswith("if ($AtomReady) {"), line
        if "populate_atom" in line:
            assert line.startswith("if ($ABackupOk) {"), line


def test_c2_expected_rows_match_corpus_facts() -> None:
    """적재 후 확인값이 코퍼스 정본 건수와 같아야 정상 적재가 True로 보고된다."""
    block = _c2_block(_RUNBOOK.read_text(encoding="utf-8"))
    m = re.search(r'-eq "(\d+)"\)\)\s*$', block, re.M)
    assert m, "[C2] 블록에 적재 후 행 수 비교가 없다"
    assert int(m.group(1)) == _corpus_atoms()


@pytest.mark.parametrize(
    ("label", "old", "new", "test"),
    [
        # 주입 ①: PUBLISHABLE=0 조건 부활 → 운영에서 다시 거부되는 회귀
        (
            "publishable_revived",
            "-and ($AtomRowsBefore -eq 0) -and",
            '-and ($AtomRowsBefore -eq 0) -and ((Get-KvInt $PreMap "PUBLISHABLE") -eq 0) -and',
            test_c2_runs_regardless_of_publishable,
        ),
        # 주입 ②: 원자 행 0 조건 삭제 → 이미 적재된 DB에 재적재
        (
            "atom_rows_dropped",
            "-and ($AtomRowsBefore -eq 0) -and",
            "-and",
            test_c2_refuses_when_atom_rows_exist,
        ),
        # 주입 ③: 기대 행 수가 정본과 어긋남
        (
            "expected_rows_drift",
            '-eq "1823"))',
            '-eq "1837"))',
            test_c2_expected_rows_match_corpus_facts,
        ),
    ],
)
def test_mutations_are_caught(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, label: str, old: str, new: str, test
) -> None:
    """각 주입이 실제로 적용됐는지 단언한 뒤, 대응 테스트가 실패하는지 확인한다."""
    original = _RUNBOOK.read_text(encoding="utf-8")
    assert original.count(old) == 1, f"{label}: 치환 대상 {original.count(old)}건"
    mutated = original.replace(old, new)
    assert mutated != original, f"{label}: 주입이 적용되지 않았다"
    fake = tmp_path / "runbook.md"
    fake.write_text(mutated, encoding="utf-8")
    monkeypatch.setitem(globals(), "_RUNBOOK", fake)
    with pytest.raises(AssertionError):
        test()
