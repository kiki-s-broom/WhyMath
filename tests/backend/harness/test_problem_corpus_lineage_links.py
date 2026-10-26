"""PB-20 — 계보만 걸기(`harness/problem_corpus_lineage_links.py`) 계약 동결.

이 테스트가 막는 것(= 뮤테이션으로 RED를 확인한 축):
  ① 구조가 같은 기존 문항이 있으면 (부모 → 그 문항) 관계 후보를 낸다 — 방향·유형이 이동 표와 일치
  ② 구조가 코퍼스에 없으면 연결하지 않는다(새 자식은 PB-09 소관) — 연결 과잉 방지
  ③ 이미 어느 방향이든 관계가 있는 쌍은 덧얹지 않는다(PB-19 역할 모순 방지)
  ④ 문항당 관계 수 상한(anti-explosion)이 거버넌스 테스트의 값을 승계하고 실제로 집행된다
  ⑤ 깔때기 항등식 — 깨진 리포트는 직렬화에서 터진다
  ⑥ signature 판정이 PB-09 오케스트레이터와 같다(차분) — 판정 기준 이원화 방지
  ⑦ 연결 0건이면 exit 1 — 부착됐으나 무작동이 정상 종료로 위장되지 않는다
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.harness import problem_corpus_lineage_links as links
from whymath_backend.harness.problem_corpus_accumulate import load_corpus_index
from whymath_backend.harness.problem_corpus_batch import JsonlCorpusSink
from whymath_backend.l2.next_problem_selection import classify_relations
from whymath_backend.l3.equivalent.generator import ScriptedGenerator
from whymath_backend.l3.equivalent.orchestrator import RoundDedupScope, run_equivalent_generation
from whymath_backend.l3.equivalent.variants import (
    MOVE_SPECS,
    MOVES,
    ParentRejection,
    VariantDraft,
    derive_variants,
    parse_parent,
)

_ROOT = Path(__file__).resolve().parents[3]
_CORPUS = _ROOT / "data" / "corpus"
_GENERATED = _CORPUS / "problem_bank_generated_v0" / "problems.jsonl"
_STAGING = _CORPUS / "problem_variants_staging_v0" / "problems.jsonl"
_GOVERNANCE = _ROOT / "tests" / "backend" / "l1" / "problem_bank" / "test_relation_governance.py"
# 시드가 작아야 단위 테스트가 빠르다(전체 시드는 CLI 실측 — 약 1분). 구조 불변식은 시드 크기와 무관하다.
_SMALL_SEEDS = [
    _GENERATED,
    _CORPUS / "problem_bank_rephrased_v0" / "problems.jsonl",
    _CORPUS / "problem_bank_v1" / "problems.jsonl",
]


def _rows(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _write(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows),
        encoding="utf-8",
    )
    return path


def _twin_fixture(tmp_path: Path, *, keep_relation: bool) -> tuple[Path, Path, dict[str, Any], str]:
    """부모 1건 + 그 부모의 `ladder_harder` 자식과 **같은 구조인 기존 문항**(트윈) 1건의 소형 시드.

    트윈은 스테이징 로트의 실제 `심화` 행이다 — 구조가 PB-09 파생기의 출력 그 자체이므로 부모에서
    같은 이동을 다시 파생하면 signature가 정확히 겹친다. `keep_relation=False`면 트윈의 기존
    관계를 지워 "관계가 아직 없는 기존 문항"을 만든다.
    """
    staged = next(r for r in _rows(_STAGING) if r["relations"][0]["relation_type"] == "심화")
    parent_slug = staged["relations"][0]["parent_slug"]
    parent = next(r for r in _rows(_GENERATED) if r["slug"] == parent_slug)
    twin = dict(staged)
    if not keep_relation:
        twin["relations"] = []
    parent_file = _write(tmp_path / "parent" / "problems.jsonl", [parent])
    seed_file = _write(tmp_path / "problem_bank_seed" / "problems.jsonl", [parent, twin])
    return parent_file, seed_file, twin, parent_slug


# ── ① 방향·유형 ───────────────────────────────────────────────────────────────


def test_links_parent_to_structural_twin_with_move_relation_type(tmp_path: Path) -> None:
    parent_file, seed_file, twin, parent_slug = _twin_fixture(tmp_path, keep_relation=False)
    report = links.run_lineage_links(
        parent_paths=[parent_file], seed_paths=[seed_file], write=False, moves=("ladder_harder",)
    )
    assert [(c.parent_slug, c.target_slug, c.relation_type) for c in report.links] == [
        (parent_slug, twin["slug"], "심화")
    ]
    assert report.links[0].move == "ladder_harder"
    assert report.links[0].alternatives == 0


def test_every_move_maps_to_the_pb09_relation_type() -> None:
    """연결 후보의 유형 표는 PB-09 이동 표 그대로다 — 이 모듈이 표를 따로 갖지 않는다."""
    assert {m: MOVE_SPECS[m].relation_type.value for m in MOVES} == {
        "ladder_harder": "심화",
        "ladder_easier": "선수",
        "condition_flip": "변형",
        "condition_sign": "변형",
        "inverse": "대조",
    }


# ── 소유 문항 선택 규칙 (L7 생존으로 추가 — 부모 자신 제외 절을 직접 밟는다) ─────────


def _owner(slug: str, corpus: str = "problem_bank_a", status: str | None = None) -> links.Owner:
    return links.Owner(slug=slug, corpus=corpus, review_status=status)


def test_pick_owner_never_returns_the_parent_itself() -> None:
    """자식 구조가 부모 자신과 같아도 부모를 '기존 문항'으로 고르지 않는다(자기 관계 금지).

    이 절의 반례 = 소유 문항 목록에 부모 slug가 들어 있는 입력. 실코퍼스 파생에서는 만들어지지
    않아 전수 테스트가 밟지 못하므로 함수를 직접 부른다.
    """
    assert links._pick_owner([_owner("p")], "p") is None  # 부모뿐이면 대상 없음
    picked = links._pick_owner([_owner("p"), _owner("q")], "p")
    assert picked is not None and picked[0].slug == "q"
    assert picked[1] == 0  # 부모는 대안으로도 세지 않는다


def test_pick_owner_order_is_approved_then_corpus_then_slug() -> None:
    owners = [
        _owner("z", "problem_bank_a", "approved"),
        _owner("b", "problem_bank_b", "approved"),
        _owner("a", "problem_bank_a", None),
        _owner("a2", "problem_bank_a", "approved"),
    ]
    picked = links._pick_owner(owners, "p")
    assert picked is not None
    # 검수 통과 중 코퍼스명 → slug 순: problem_bank_a 의 a2 < z
    assert picked[0].slug == "a2"
    assert picked[1] == 3  # 고른 문항을 뺀 나머지 전부가 대안
    # 입력 순서를 바꿔도 결과가 같다(결정론)
    assert links._pick_owner(list(reversed(owners)), "p") == picked


# ── ② 새 자식은 연결하지 않는다 ──────────────────────────────────────────────────


def test_no_structural_twin_means_no_link(tmp_path: Path) -> None:
    parent_file, _, _, _ = _twin_fixture(tmp_path, keep_relation=False)
    parent_only = _write(
        tmp_path / "problem_bank_only_parent" / "problems.jsonl", _rows(parent_file)
    )
    report = links.run_lineage_links(
        parent_paths=[parent_file], seed_paths=[parent_only], write=False
    )
    assert report.linked_total == 0
    for move in report.moves:
        # 파생된 시도는 전부 '새 구조'로 센다 — 조용히 사라지지 않는다.
        assert move.outcomes.get(links.OUT_LINKED, 0) == 0
        assert move.outcomes.get(links.OUT_NOT_DUP, 0) == move.derived


# ── ③ 이미 이어진 쌍 ───────────────────────────────────────────────────────────


def test_pair_with_existing_relation_is_not_linked_again(tmp_path: Path) -> None:
    parent_file, seed_file, _, _ = _twin_fixture(tmp_path, keep_relation=True)
    report = links.run_lineage_links(
        parent_paths=[parent_file], seed_paths=[seed_file], write=False, moves=("ladder_harder",)
    )
    assert report.linked_total == 0
    assert report.moves[0].outcomes == {links.OUT_PAIR_RELATED: 1}


# ── ④ anti-explosion 상한 ──────────────────────────────────────────────────────


def test_cap_constant_inherits_the_governance_test_value() -> None:
    """상한은 거버넌스 테스트의 `_MAX_RELATIONS_PER_RECORD`와 같은 값이다(두 곳이 갈라지지 않는다)."""
    match = re.search(
        r"^_MAX_RELATIONS_PER_RECORD\s*=\s*(\d+)", _GOVERNANCE.read_text("utf-8"), re.M
    )
    assert match is not None, "거버넌스 테스트에서 상한 상수를 찾지 못했다 — 스캔이 공허하다"
    assert links.MAX_RELATIONS_PER_RECORD == int(match.group(1))


def test_cap_is_enforced_and_counted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    parent_file, seed_file, _, _ = _twin_fixture(tmp_path, keep_relation=False)
    monkeypatch.setattr(links, "MAX_RELATIONS_PER_RECORD", 0)
    report = links.run_lineage_links(
        parent_paths=[parent_file], seed_paths=[seed_file], write=False, moves=("ladder_harder",)
    )
    assert report.linked_total == 0
    assert report.moves[0].outcomes == {links.OUT_TARGET_CAP: 1}


# ── ⑤ 깔때기 항등식 ────────────────────────────────────────────────────────────


def test_tampered_report_refuses_to_serialize(tmp_path: Path) -> None:
    parent_file, seed_file, _, _ = _twin_fixture(tmp_path, keep_relation=False)
    report = links.run_lineage_links(
        parent_paths=[parent_file], seed_paths=[seed_file], write=False
    )
    assert report.to_json()["linked_total"] == 1  # 정상 리포트는 직렬화된다(대조군)
    report.moves[0].attempted += 1  # 시도가 조용히 늘어난 거짓 리포트
    with pytest.raises(AssertionError, match="attempted"):
        report.to_json()


# ── ⑥ PB-09 오케스트레이터와의 차분 ──────────────────────────────────────────────


def test_seed_index_keys_equal_pb09_corpus_index() -> None:
    """역인덱스의 키 집합 = PB-09 `load_corpus_index`의 signature 집합(같은 산식)."""
    signatures, slugs, total = load_corpus_index(_SMALL_SEEDS)
    seed = links.load_seed_index(_SMALL_SEEDS)
    assert set(seed.owners) == signatures
    assert seed.total_records == total
    assert set(seed.review_status) == slugs
    assert signatures, "시드 signature 0건 — 비교가 공허하다"


def test_signature_decision_matches_the_orchestrator() -> None:
    """각 자식 후보에 대해 `signature ∈ 역인덱스` ⇔ 오케스트레이터의 구조 중복 판정.

    오케스트레이터는 라운드 안에서 먼저 저장된 자식도 중복으로 보지만(출처=round), 여기서는 후보마다
    **빈 라운드**로 부르므로 시드 유래 중복만 남는다 — 연결 대상이 되는 부류와 정확히 같다.
    """
    seed = links.load_seed_index(_SMALL_SEEDS)
    parents = [
        p
        for p in (parse_parent(r) for r in _rows(_GENERATED))
        if not isinstance(p, ParentRejection)
    ]
    compared = dup = fresh = 0
    for parent in parents:
        for item in derive_variants(parent, MOVES):
            if not isinstance(item, VariantDraft):
                continue
            signature = links._draft_signature(item)
            outcome = run_equivalent_generation(
                item.spec,
                ScriptedGenerator([item.candidate]),
                signature_index=set(seed.owners),
                round_scope=RoundDedupScope(),
                store=JsonlCorpusSink(),
            )
            orchestrator_says_dup = outcome.duplicate_detector == "structural_signature"
            assert (signature in seed.owners) == orchestrator_says_dup, (parent.slug, item.move)
            compared += 1
            dup += orchestrator_says_dup
            fresh += not orchestrator_says_dup
    # 대조군이 양쪽 모두 실재해야 차분이 의미 있다(한쪽만 있으면 그 방향은 검증된 적이 없다).
    assert compared > 100 and dup > 0 and fresh > 0, (compared, dup, fresh)


# ── 실코퍼스 구조 불변식(소형 시드) ─────────────────────────────────────────────


def test_real_corpus_links_obey_structural_invariants() -> None:
    report = links.run_lineage_links(
        parent_paths=[_GENERATED], seed_paths=_SMALL_SEEDS, write=False
    )
    assert report.linked_total > 0, "연결 0건 — 경로가 무작동이다"
    pairs: set[frozenset[str]] = set()
    seen_targets: dict[str, int] = {}
    for link in report.links:
        assert link.parent_slug != link.target_slug
        assert link.relation_type == MOVE_SPECS[link.move].relation_type.value
        pair = frozenset((link.parent_slug, link.target_slug))
        assert pair not in pairs, "같은 쌍이 두 번 이어졌다"
        pairs.add(pair)
        seen_targets[link.target_slug] = seen_targets.get(link.target_slug, 0) + 1
    assert report.max_target_relations_after <= links.MAX_RELATIONS_PER_RECORD
    # 역방향 혼재 금지: 이어진 쌍의 한쪽이 다른 쪽의 부모이면서 동시에 자식인 경우가 없다.
    assert len({(link.parent_slug, link.target_slug) for link in report.links}) == len(pairs)
    # 대조(역문제)는 새 구조만 낳으므로 연결 후보가 될 수 없다 — 나오면 signature 산식이 깨진 것이다.
    assert all(link.relation_type != "대조" for link in report.links)
    json.dumps(report.to_json(), ensure_ascii=False)  # 항등식 통과 + 직렬화 가능


def test_link_relation_types_are_classified_by_the_pb19_policy() -> None:
    """연결 후보가 쓰는 유형은 PB-19 분류기가 역할을 아는 유형이다(소비 정책 없이 계보가 CAT에 닿지 않는다)."""
    wrong, other = uuid.uuid4(), uuid.uuid4()
    roles = {}
    for relation_type in ("변형", "선수", "심화"):
        # 오답 문항이 parent인 방향(PB-09/PB-20의 저작 방향)으로 분류한다.
        roles[relation_type] = classify_relations(wrong, [(wrong, other, relation_type)])
    assert other in roles["변형"].siblings
    assert other in roles["선수"].easier
    assert other in roles["심화"].harder


# ── ⑦ 무작동 exit 1 ───────────────────────────────────────────────────────────


def test_cli_exits_one_when_nothing_is_linked(tmp_path: Path) -> None:
    parent_file, _, _, _ = _twin_fixture(tmp_path, keep_relation=False)
    # CLI는 시드를 data/corpus 글롭으로 찾으므로 함수 경로로 같은 조건(무연결)을 만든다.
    only_parent = _write(tmp_path / "problem_bank_p" / "problems.jsonl", _rows(parent_file))
    report = links.run_lineage_links(
        parent_paths=[parent_file], seed_paths=[only_parent], write=False
    )
    assert report.linked_total == 0  # main()은 이 값이 0이면 1을 돌려준다(아래 소스 대조)
    source = Path(links.__file__).read_text(encoding="utf-8")
    assert "if report.linked_total == 0:" in source and "return 1" in source


def test_write_creates_sidecar_jsonl_outside_the_corpus_glob(tmp_path: Path) -> None:
    parent_file, seed_file, twin, parent_slug = _twin_fixture(tmp_path, keep_relation=False)
    out = tmp_path / "links.jsonl"
    report = links.run_lineage_links(
        parent_paths=[parent_file], seed_paths=[seed_file], out_path=out, moves=("ladder_harder",)
    )
    assert report.written == 1
    row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert (row["parent_slug"], row["child_slug"], row["relation_type"]) == (
        parent_slug,
        twin["slug"],
        "심화",
    )
    assert row["similarity_score"] is None  # 유사도를 날조하지 않는다
