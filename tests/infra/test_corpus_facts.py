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


# ── 낡은 값·표식 없는 값·손 고정값 검출(변별력) ─────────────────────────────────


def _mention_repo(
    tmp_path: Path, doc: str, rel: str = "docs/data/card.md"
) -> tuple[Path, dict[str, object]]:
    root = tmp_path / "repo"
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(doc, encoding="utf-8")
    values = {"atom_graph.edges": 2278, "atom_graph.nodes": 2683, "concept_graph.edges": 581}
    return root, values


def _mentions(tmp_path: Path, doc: str, rel: str = "docs/data/card.md") -> list[str]:
    root, values = _mention_repo(tmp_path, doc, rel)
    return cf.unmarked_phrases(root, values)


def test_stale_value_in_current_doc_is_red(tmp_path: Path) -> None:
    out = _mentions(tmp_path, "원자 백본은 2,683노드·2,234엣지다.\n")
    assert any("낡은 값" in p and "2,234" in p for p in out)


def test_current_value_without_marker_is_red_in_markdown(tmp_path: Path) -> None:
    out = _mentions(tmp_path, "원자 백본은 2,683노드·2,278엣지다.\n")
    assert any("표식 없는" in p for p in out) and not any("낡은 값" in p for p in out)


def test_marked_value_is_green(tmp_path: Path) -> None:
    doc = (
        "원자 백본은 <!-- fact:atom_graph.nodes -->2,683<!-- /fact -->노드·"
        "<!-- fact:atom_graph.edges -->2,278<!-- /fact -->엣지다.\n"
    )
    assert _mentions(tmp_path, doc) == []


def test_dated_line_and_wrapped_next_line_are_exempt(tmp_path: Path) -> None:
    assert _mentions(tmp_path, "2026-08-10 실측: 엣지 2,234건.\n") == []
    assert _mentions(tmp_path, "KG-12 이전 기록(2026-10-15)\n엣지 2,231건이었다.\n") == []
    assert _mentions(tmp_path, "엣지 2,234→2,278로 정정.\n") == []


def test_history_file_is_exempt(tmp_path: Path) -> None:
    assert _mentions(tmp_path, "엣지 2,210건\n", rel="docs/reviews/r.md") == []
    assert _mentions(tmp_path, "엣지 2,210건\n", rel="MEMORY.md") == []


def test_far_value_and_year_are_not_mentions(tmp_path: Path) -> None:
    assert _mentions(tmp_path, "엣지 120건만 본다. 성취기준(2022 개정).\n") == []


def test_code_comment_current_value_is_allowed_but_stale_is_red(tmp_path: Path) -> None:
    ok = _mentions(tmp_path, "# 원자 백본 엣지 2,278건\n", rel="src/x.py")
    bad = _mentions(tmp_path, "# 원자 백본 엣지 2,213건\n", rel="src/x.py")
    assert ok == [] and any("낡은 값" in p for p in bad)


def test_value_inside_code_fence_is_not_asked_for_marker(tmp_path: Path) -> None:
    assert _mentions(tmp_path, "```\nAFTER 엣지 2,278\n```\n") == []
    assert any("낡은 값" in p for p in _mentions(tmp_path, "```\n엣지 2,210\n```\n"))


def test_hand_pin_in_test_code_is_red_and_tag_allows(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "tests").mkdir(parents=True)
    values = {"atom_graph.edges": 2278}
    (root / "tests/test_a.py").write_text("def test():\n    assert n == 2278\n", encoding="utf-8")
    assert any("손 고정값 2278" in p for p in cf.hand_pins(root, values))
    (root / "tests/test_a.py").write_text(
        "def test():\n    assert n == 2278  # corpus-pin: 시점 고정 — 예시\n", encoding="utf-8"
    )
    assert cf.hand_pins(root, values) == []
    (root / "tests/test_a.py").write_text(
        "# 주석의 2278은 숫자 토큰이 아니다\nX = '2278'\n", encoding="utf-8"
    )
    assert cf.hand_pins(root, values) == []


def test_common_numbers_are_not_pins() -> None:
    vals = cf.distinctive_values({"a": 400, "b": 409, "c": 2278, "d": 1500, "e": 399})
    assert set(vals) == {2278}


def test_year_is_not_read_as_a_count(tmp_path: Path) -> None:
    """연도 제외 절이 없으면 '성취기준(2022 개정)'의 2022가 성취기준 2,010건의 낡은 값으로 잡힌다."""
    root, _ = _mention_repo(tmp_path, "성취기준(2022 개정) 기준.\n")
    assert cf.unmarked_phrases(root, {"standards.k12": 2010}) == []
    root2, _ = _mention_repo(tmp_path / "b", "성취기준 2,022건.\n")
    assert any("낡은 값" in p for p in cf.unmarked_phrases(root2, {"standards.k12": 2010}))


def test_check_reports_stale_phrase_and_hand_pin(tmp_path: Path) -> None:
    """check가 두 검출기를 실제로 부른다 — 함수만 있고 판정에 안 들어가면 CI는 못 본다."""
    root, facts, decls = _fake_repo(tmp_path)
    (root / "docs/data/toy.md").write_text("현재 원자 백본 엣지 2,234건\n", encoding="utf-8")
    (root / "tests").mkdir()
    big = cf.Fact("큰 값", "data/corpus/toy_v1/rows.jsonl", lambda r: 2278)
    facts = {**facts, "atom_graph.edges": big}
    (root / cf.FACTS_TABLE).write_text(cf.render_table(root, facts), encoding="utf-8")
    (root / cf.FACTS_JSON).write_text(cf.render_json(root, facts), encoding="utf-8")
    (root / "tests/test_x.py").write_text("assert n == 2278\n", encoding="utf-8")
    problems = cf.check(root, facts, decls)
    assert any("손 고정값 2278" in p for p in problems)
    assert any("낡은 값" in p and "2,234" in p for p in problems)
