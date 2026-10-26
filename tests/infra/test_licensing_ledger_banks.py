"""LIC-10 — 문제은행 폴더가 라이선스 대장에 빠짐없이 등재돼 있는가.

CLAUDE.md "모든 데이터 소스의 라이선스를 `docs/data/licensing_safety.md`에 기록" 원칙의 **문제은행 축 집행 지점**.
등재 전(2026-10-26) 대장은 은행 39개 중 7개만 행으로 갖고 있었고, 나머지 32개는 폴더가 생길 때 아무것도
대장을 고치라고 요구하지 않았다. 이 테스트가 그 요구다.

검사(대장 = `<!-- bank-ledger:start -->` ~ `<!-- bank-ledger:end -->` 사이 표):
  ① `data/corpus/problem_bank_*` 폴더 집합 ⊆ 대장 등재 집합 — 새 은행을 추가하면 행을 넣기 전까지 RED
  ② 대장 행의 `pool`·`copyright_rail` 기재 여부가 그 은행 `_provenance.json`과 같다 — 대장이 provenance와
     다른 말을 하면 RED(옮겨 적은 값이 낡는 것을 막는다. 건수는 `test_corpus_facts.py`가 따로 본다)
  ③ 스캔 0건은 실패 — 폴더를 하나도 못 찾거나 대장 행을 하나도 못 읽으면 통과가 아니라 실패다
     (경로·정규식이 낡아 아무것도 검사하지 않는 위장 통과 방지)

대장에만 있고 폴더가 없는 행(은퇴 은행)은 막지 않는다 — 요구는 ⊆ 이다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LEDGER_DOC = Path("docs/data/licensing_safety.md")
CORPUS = Path("data/corpus")
BANK_GLOB = "problem_bank_*"

START = "<!-- bank-ledger:start -->"
END = "<!-- bank-ledger:end -->"
MISSING = "**미기재**"
_BANK_CELL = re.compile(r"^`(problem_bank_[a-z0-9_]+)`$")
_POOL_CELL = re.compile(r"^`([^`]+)`$")


def parse_ledger(text: str) -> dict[str, list[str]]:
    """대장 표를 {은행 폴더명: 칸 목록}으로 읽는다. 앵커가 없으면 ValueError."""
    if text.count(START) != 1 or text.count(END) != 1:
        raise ValueError(f"대장 앵커가 정확히 1쌍이 아니다({START} ×{text.count(START)} · {END} ×{text.count(END)})")
    body = text[text.index(START) + len(START) : text.index(END)]
    rows: dict[str, list[str]] = {}
    for line in body.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        m = _BANK_CELL.match(cells[0])
        if m:  # 머리행·구분행은 첫 칸이 은행명이 아니므로 건너뛴다
            rows[m.group(1)] = cells
    return rows


def bank_dirs(root: Path) -> list[Path]:
    return sorted(p for p in (root / CORPUS).glob(BANK_GLOB) if p.is_dir())


def violations(root: Path) -> list[str]:
    """어긋남 목록 — 빈 목록이면 통과."""
    try:
        ledger = parse_ledger((root / LEDGER_DOC).read_text(encoding="utf-8"))
    except ValueError as e:
        return [str(e)]
    dirs = bank_dirs(root)
    out: list[str] = []
    if not dirs:
        out.append(f"스캔 0건 — {CORPUS / BANK_GLOB} 폴더를 하나도 찾지 못했다")
    if not ledger:
        out.append("스캔 0건 — 대장 표에서 은행 행을 하나도 읽지 못했다")
    for d in dirs:
        row = ledger.get(d.name)
        if row is None:
            out.append(f"{d.name}: 대장 미등재 — {LEDGER_DOC} 은행별 대장에 행을 추가하라")
            continue
        prov_path = d / "_provenance.json"
        if not prov_path.is_file():
            out.append(f"{d.name}: _provenance.json 없음 — 대장 칸을 대조할 원본이 없다")
            continue
        prov = json.loads(prov_path.read_text(encoding="utf-8"))
        if len(row) < 4:
            out.append(f"{d.name}: 대장 행의 칸 수가 모자란다({len(row)})")
            continue
        pool_cell, rail_cell = row[2], row[3]
        pool_m = _POOL_CELL.match(pool_cell)
        shown_pool = pool_m.group(1) if pool_m else None
        if shown_pool != prov.get("pool"):
            out.append(f"{d.name}: pool 불일치 — 대장 {pool_cell!r} · provenance {prov.get('pool')!r}")
        has_rail = bool(prov.get("copyright_rail"))
        shown_rail = rail_cell != MISSING
        if has_rail != shown_rail:
            out.append(f"{d.name}: copyright_rail 기재 여부 불일치 — 대장 {rail_cell!r} · provenance 기재={has_rail}")
    return out


# ── 실저장소 판정 ────────────────────────────────────────────────────────────────


def test_every_bank_folder_is_registered_in_license_ledger() -> None:
    assert bank_dirs(ROOT), "스캔 0건 — 문제은행 폴더를 하나도 찾지 못했다"
    found = violations(ROOT)
    assert not found, "라이선스 대장 ↔ 문제은행 폴더 어긋남:\n" + "\n".join(found)


# ── 변별력(실패 주입) — 가짜 저장소에서 각 절이 실제로 RED를 내는지 ─────────────────


def _row(name: str, pool: str = "`whymath-original`", rail: str = MISSING) -> str:
    return f"| `{name}` | 1 | {pool} | {rail} | x | x | x | x |"


def _make_repo(
    tmp_path: Path,
    banks: dict[str, dict[str, object] | None],
    rows: list[str],
    *,
    anchors: bool = True,
) -> Path:
    for name, prov in banks.items():
        d = tmp_path / CORPUS / name
        d.mkdir(parents=True)
        if prov is not None:
            (d / "_provenance.json").write_text(json.dumps(prov), encoding="utf-8")
    table = "| 은행 | 건수 | pool | copyright_rail | a | b | c | d |\n|---|---|---|---|---|---|---|---|\n" + "\n".join(rows)
    body = f"{START}\n{table}\n{END}\n" if anchors else table + "\n"
    doc = tmp_path / LEDGER_DOC
    doc.parent.mkdir(parents=True)
    doc.write_text("# 대장\n\n" + body, encoding="utf-8")
    return tmp_path


_POOL = {"pool": "whymath-original"}
_RAILED = {"pool": "whymath-original", "copyright_rail": ["복제 0"]}


def test_control_consistent_repo_is_green(tmp_path: Path) -> None:
    # 대조군 — 아래 RED 주입들이 '항상 RED'인 가드가 아님을 보인다
    repo = _make_repo(
        tmp_path,
        {"problem_bank_a_v0": _POOL, "problem_bank_b_v0": _RAILED},
        [_row("problem_bank_a_v0"), _row("problem_bank_b_v0", rail="기재(1항)")],
    )
    assert violations(repo) == []


def test_control_retired_ledger_row_without_folder_is_allowed(tmp_path: Path) -> None:
    # 요구는 폴더 ⊆ 대장 — 대장에만 있는 행(은퇴 은행)은 막지 않는다
    repo = _make_repo(tmp_path, {"problem_bank_a_v0": _POOL}, [_row("problem_bank_a_v0"), _row("problem_bank_gone_v0")])
    assert violations(repo) == []


def test_new_bank_folder_without_ledger_row_is_red(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, {"problem_bank_a_v0": _POOL, "problem_bank_new_v0": _POOL}, [_row("problem_bank_a_v0")])
    found = violations(repo)
    assert len(found) == 1 and "problem_bank_new_v0: 대장 미등재" in found[0]


def test_zero_bank_folders_is_red(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, {}, [_row("problem_bank_a_v0")])
    assert any("폴더를 하나도 찾지 못했다" in v for v in violations(repo))


def test_empty_ledger_table_is_red(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, {"problem_bank_a_v0": _POOL}, [])
    found = violations(repo)
    assert any("은행 행을 하나도 읽지 못했다" in v for v in found)
    assert any("대장 미등재" in v for v in found)


def test_missing_anchors_is_red(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, {"problem_bank_a_v0": _POOL}, [_row("problem_bank_a_v0")], anchors=False)
    assert any("앵커" in v for v in violations(repo))


def test_pool_mismatch_is_red(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, {"problem_bank_a_v0": _POOL}, [_row("problem_bank_a_v0", pool="`other-pool`")])
    assert any("pool 불일치" in v for v in violations(repo))


def test_pool_shown_but_absent_in_provenance_is_red(tmp_path: Path) -> None:
    # provenance에 pool이 없으면 대장은 미기재여야 한다 — 추측 기입을 막는다
    repo = _make_repo(tmp_path, {"problem_bank_a_v0": {}}, [_row("problem_bank_a_v0")])
    assert any("pool 불일치" in v for v in violations(repo))


@pytest.mark.parametrize(
    ("prov", "rail_cell"),
    [(_POOL, "기재(1항)"), (_RAILED, MISSING)],
    ids=["ledger-claims-rail-provenance-lacks", "ledger-says-missing-provenance-has"],
)
def test_copyright_rail_presence_mismatch_is_red(tmp_path: Path, prov: dict[str, object], rail_cell: str) -> None:
    repo = _make_repo(tmp_path, {"problem_bank_a_v0": prov}, [_row("problem_bank_a_v0", rail=rail_cell)])
    assert any("copyright_rail 기재 여부 불일치" in v for v in violations(repo))


def test_bank_without_provenance_is_red(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, {"problem_bank_a_v0": None}, [_row("problem_bank_a_v0")])
    assert any("_provenance.json 없음" in v for v in violations(repo))
