"""OPS-154 — 코퍼스 사실 단일 원천의 집행.

`scripts/analysis/corpus_facts.py`가 코퍼스 건수·지문을 원본 파일에서 계산하고, 문서는 그 값을
`<!-- fact:이름 -->값<!-- /fact -->` 표식으로 인용한다. 이 테스트는 저장소 전체에 대해 그 도구의
`check`를 돌려 어긋남이 0건인지 보고, 합성 저장소에 결함을 하나씩 주입해 각 판정이 실제로 RED를
내는지(변별력) 고정한다.

원본이 바뀌어 이 테스트가 실패하면 고칠 곳을 찾지 말고 다음 한 줄을 돌린다:

    python3 scripts/analysis/corpus_facts.py sync
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load() -> ModuleType:
    path = ROOT / "scripts" / "analysis" / "corpus_facts.py"
    spec = importlib.util.spec_from_file_location("corpus_facts_under_test", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclass가 모듈을 찾을 수 있게
    spec.loader.exec_module(mod)
    return mod


cf = _load()


# ── 저장소 전체 ────────────────────────────────────────────────────────────────


def test_repository_has_no_corpus_fact_drift() -> None:
    problems = cf.check(ROOT)
    assert (
        not problems
    ), "코퍼스 사실 어긋남 — `python3 scripts/analysis/corpus_facts.py sync`:\n" + "\n".join(
        problems
    )


def test_scan_is_not_empty() -> None:
    """스캔 0건은 실패 — 표식·자기 선언·현행 문서를 하나도 못 보면 위의 통과는 공허하다."""
    values = cf.compute_all(ROOT)
    assert len(values) >= 60, f"사실이 {len(values)}개뿐 — 레지스트리가 비었다"
    assert (
        len(cf.scan_markers(ROOT, values)) >= 10
    ), "문서 표식이 10개 미만 — 인용이 표식으로 옮겨지지 않았다"
    assert len(cf._provenance_declarations(ROOT)) >= 60, "자기 선언 대조가 60건 미만"
    assert len(list(cf._current_state_files(ROOT))) >= 10, "현행 문서 범위가 10개 미만"


def test_every_problem_bank_is_a_fact() -> None:
    """은행 폴더를 새로 만들면 사실·자기 선언 대조가 저절로 늘어난다(손 등록 없음)."""
    banks = sorted(
        p.parent.name for p in (ROOT / "data/corpus").glob("problem_bank_*/problems.jsonl")
    )
    facts = cf.build_facts(ROOT)
    for name in banks:
        assert f"problem_bank.{name.removeprefix('problem_bank_')}" in facts
    values = cf.compute_all(ROOT)
    assert values["problem_bank.total"] == sum(
        values[f"problem_bank.{n.removeprefix('problem_bank_')}"] for n in banks
    )


# ── 합성 저장소로 결함 주입 ─────────────────────────────────────────────────────


def _fake_repo(
    tmp_path: Path,
) -> tuple[Path, dict[str, object], list[tuple[str, tuple[str, ...], str]]]:
    """코퍼스 1개(행 3개) · 자기 선언 1개 · 현행 문서 1개 · 사실 표가 있는 최소 저장소."""
    root = tmp_path / "repo"
    corpus = root / "data/corpus/toy_v1"
    corpus.mkdir(parents=True)
    (corpus / "rows.jsonl").write_text('{"a":1}\n{"a":2}\n{"a":3}\n', encoding="utf-8")
    (corpus / "_provenance.json").write_text(
        json.dumps({"pool": "x", "record_count": 3}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    facts = {
        "toy.rows": cf.Fact(
            "장난감 행", "data/corpus/toy_v1/rows.jsonl", cf._jsonl("data/corpus/toy_v1/rows.jsonl")
        )
    }
    decls = [("toy_v1", ("record_count",), "toy.rows")]
    (root / "docs/data").mkdir(parents=True)
    (root / "docs/data/toy.md").write_text(
        "# 장난감\n\n현재 <!-- fact:toy.rows -->3<!-- /fact -->행이다.\n", encoding="utf-8"
    )
    (root / cf.FACTS_TABLE).write_text(cf.render_table(root, facts), encoding="utf-8")
    (root / cf.FACTS_JSON).write_text(cf.render_json(root, facts), encoding="utf-8")
    return root, facts, decls


def test_fake_repo_is_green(tmp_path: Path) -> None:
    root, facts, decls = _fake_repo(tmp_path)
    assert cf.check(root, facts, decls) == []


def test_source_change_makes_unsynced_marker_red_and_sync_fixes_it(tmp_path: Path) -> None:
    root, facts, decls = _fake_repo(tmp_path)
    with (root / "data/corpus/toy_v1/rows.jsonl").open("a", encoding="utf-8") as fh:
        fh.write('{"a":4}\n')
    problems = cf.check(root, facts, decls)
    assert any("toy.rows 표식 값 '3' ≠ 실제 '4'" in p for p in problems)
    assert any("record_count=3 ≠ 실제 4" in p for p in problems)
    assert any("corpus_facts.md" in p for p in problems)
    changed = cf.sync(root, facts, decls)
    assert set(changed) == {
        "data/corpus/toy_v1/_provenance.json",
        "docs/data/toy.md",
        str(cf.FACTS_TABLE),
        str(cf.FACTS_JSON),
    }
    assert cf.check(root, facts, decls) == []
    assert "<!-- fact:toy.rows -->4<!-- /fact -->" in (root / "docs/data/toy.md").read_text(
        encoding="utf-8"
    )
    assert (
        json.loads((root / "data/corpus/toy_v1/_provenance.json").read_text(encoding="utf-8"))[
            "record_count"
        ]
        == 4
    )


def test_hand_edited_marker_is_red(tmp_path: Path) -> None:
    root, facts, decls = _fake_repo(tmp_path)
    doc = root / "docs/data/toy.md"
    doc.write_text(
        doc.read_text(encoding="utf-8").replace("-->3<!--", "-->5<!--"), encoding="utf-8"
    )
    assert any("표식 값 '5' ≠ 실제 '3'" in p for p in cf.check(root, facts, decls))


def test_unknown_fact_name_is_red_and_sync_keeps_it(tmp_path: Path) -> None:
    root, facts, decls = _fake_repo(tmp_path)
    doc = root / "docs/data/toy.md"
    doc.write_text(
        doc.read_text(encoding="utf-8") + "<!-- fact:toy.nothing -->9<!-- /fact -->\n",
        encoding="utf-8",
    )
    assert any("없는 사실 이름 'toy.nothing'" in p for p in cf.check(root, facts, decls))
    cf.sync(root, facts, decls)
    assert "<!-- fact:toy.nothing -->9<!-- /fact -->" in doc.read_text(encoding="utf-8")


def test_unclosed_marker_is_red(tmp_path: Path) -> None:
    root, facts, decls = _fake_repo(tmp_path)
    doc = root / "docs/data/toy.md"
    doc.write_text(doc.read_text(encoding="utf-8") + "<!-- fact:toy.rows -->3\n", encoding="utf-8")
    assert any("짝이 맞는 것" in p for p in cf.check(root, facts, decls))


def test_raw_marker_has_no_thousands_separator() -> None:
    assert cf.format_value(2278, raw=False) == "2,278"
    assert cf.format_value(2278, raw=True) == "2278"
    assert cf.format_value("a2424fe18727", raw=False) == "a2424fe18727"


def test_missing_declaration_key_is_red(tmp_path: Path) -> None:
    root, facts, decls = _fake_repo(tmp_path)
    prov = root / "data/corpus/toy_v1/_provenance.json"
    prov.write_text(json.dumps({"pool": "x"}, indent=2) + "\n", encoding="utf-8")
    assert any("record_count=None ≠ 실제 3" in p for p in cf.check(root, facts, decls))


def test_sync_refuses_to_reformat_non_canonical_json(tmp_path: Path) -> None:
    root, facts, decls = _fake_repo(tmp_path)
    prov = root / "data/corpus/toy_v1/_provenance.json"
    prov.write_text('{"pool": "x", "record_count": 2}\n', encoding="utf-8")  # 한 줄 JSON
    with pytest.raises(SystemExit):
        cf.sync(root, facts, decls)
    assert prov.read_text(encoding="utf-8") == '{"pool": "x", "record_count": 2}\n'


def test_stale_generated_table_is_red(tmp_path: Path) -> None:
    root, facts, decls = _fake_repo(tmp_path)
    table = root / cf.FACTS_TABLE
    table.write_text(table.read_text(encoding="utf-8").replace("| 3 |", "| 30 |"), encoding="utf-8")
    assert any("생성 문서" in p for p in cf.check(root, facts, decls))


def test_stale_facts_json_is_red(tmp_path: Path) -> None:
    root, facts, decls = _fake_repo(tmp_path)
    (root / cf.FACTS_JSON).write_text('{"toy.rows": 30}\n', encoding="utf-8")
    assert any("corpus_facts.json" in p for p in cf.check(root, facts, decls))


def test_committed_facts_json_matches_registry() -> None:
    """테스트가 읽는 기계용 사본이 원본에서 센 값과 같다 — 낡으면 테스트들이 옛 값을 기대하게 된다."""
    assert cf.load_facts_json(ROOT) == cf.compute_all(ROOT)
