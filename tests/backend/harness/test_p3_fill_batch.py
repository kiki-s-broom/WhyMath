"""빈 칸 채우기 은행 배치(P3-05 4·5단계) — 재생성 드리프트·빈 칸 정합·승인 미기록.

재생성은 1분 안팎이라 모듈에서 한 번만 돌려 테스트들이 나눠 쓴다.
"""

from __future__ import annotations

import glob
import json
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.harness import p3_fill_batch as batch
from whymath_backend.harness.p3_calculus1_diff_batch import drift_against
from whymath_backend.l1.standards import phase3_coverage as pc
from whymath_backend.l1.standards import phase3_scope as ps
from whymath_backend.schema.problem_metadata import ProblemSlot, parse_slot_tags

_REPO = Path(__file__).resolve().parents[3]
_BANK = _REPO / "data" / "corpus" / batch.CORPUS_DIR_NAME
# 코퍼스 건수는 손으로 박지 않고 단일 원천의 기계용 사본에서 읽는다(OPS-154).
# 원본이 바뀌면 `python3 scripts/analysis/corpus_facts.py sync`가 이 파일을 갱신한다.
_FACTS = json.loads((_REPO / "docs" / "data" / "corpus_facts.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def fresh(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    out = tmp_path_factory.mktemp("fill") / "problems.jsonl"
    report = batch.run_p3_fill_batch(out_path=out)
    return {
        "report": report,
        "problems": out.read_bytes(),
        "provenance": (
            json.dumps(batch.build_provenance(), ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
    }


def _rows() -> list[dict[str, Any]]:
    lines = (_BANK / "problems.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


class TestRegeneration:
    def test_every_candidate_passes_the_acceptance_gate(self, fresh: dict[str, Any]) -> None:
        report = fresh["report"]
        assert report.total_requested > 0
        assert report.total_stored == report.total_requested
        assert all(not b.failure_reasons for b in report.bands)

    def test_committed_bank_equals_the_regeneration(self, fresh: dict[str, Any]) -> None:
        assert drift_against(_BANK, fresh["problems"], fresh["provenance"]) == []

    def test_drift_is_detected_when_a_byte_changes(
        self, fresh: dict[str, Any], tmp_path: Path
    ) -> None:
        """대조군 — 은행 사본의 한 글자를 바꾸면 같은 비교가 드리프트를 낸다(변별력)."""
        (tmp_path / "problems.jsonl").write_bytes(
            (_BANK / "problems.jsonl")
            .read_bytes()
            .replace("구하시오".encode(), "구하시요".encode(), 1)
        )
        (tmp_path / "_provenance.json").write_bytes((_BANK / "_provenance.json").read_bytes())
        assert drift_against(tmp_path, fresh["problems"], fresh["provenance"]) != []

    def test_a_missing_bank_is_drift_not_a_pass(
        self, fresh: dict[str, Any], tmp_path: Path
    ) -> None:
        assert drift_against(tmp_path, fresh["problems"], fresh["provenance"]) != []


def test_batch_is_byte_deterministic(tmp_path: Path) -> None:
    """한 함수 안에서 두 번 돌린다 — 헌법 R3-01 가드(`tests/test_idempotency.py`)는 공유 픽스처의
    실행을 세지 않는다(같은 함수 안 진입점 호출 2회 + `==` 단언이 구조 증거다)."""
    first, second = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    batch.run_p3_fill_batch(out_path=first)
    batch.run_p3_fill_batch(out_path=second)
    assert first.read_bytes() == second.read_bytes()


class TestBank:
    def test_scan_is_not_vacuous(self) -> None:
        assert len(_rows()) == _FACTS["problem_bank.p3_fill_v0"]

    def test_the_batch_never_writes_an_approval(self, fresh: dict[str, Any]) -> None:
        """생성기는 승인을 쓰지 않는다 — 재생성 산출물에는 `review_status`가 없고, 저장소 은행의 전건
        `approved`는 3회차 S5 감사 뒤 코퍼스 단위 백필이 얹은 각인이다(결속 테스트가 감사 내용에 묶는다)."""
        fresh_rows = [json.loads(line) for line in fresh["problems"].decode("utf-8").splitlines()]
        assert len(fresh_rows) == _FACTS["problem_bank.p3_fill_v0"]  # 재생성 = 커밋 은행
        assert all("review_status" not in row for row in fresh_rows)
        assert {row.get("review_status") for row in _rows()} == {"approved"}

    def test_each_row_carries_exactly_one_known_slot_tag(self) -> None:
        for row in _rows():
            tags = parse_slot_tags(row["tags"])
            assert len(tags.slots) == 1 and not tags.unknown, row["tags"]

    def test_provenance_counts_match_the_file(self) -> None:
        sidecar = json.loads((_BANK / "_provenance.json").read_text(encoding="utf-8"))
        assert sidecar["record_count"] == len(_rows())
        assert sidecar["corpus_name"] == batch.CORPUS_DIR_NAME
        assert sidecar["task"] == "P3-05-triangle-density"

    def test_ids_and_slugs_do_not_collide_with_any_other_bank(self) -> None:
        mine = {(r["problem_id"], r["slug"]) for r in _rows()}
        ids = {i for i, _ in mine}
        slugs = {s for _, s in mine}
        assert len(ids) == len(slugs) == len(mine)
        for path in glob.glob(str(_REPO / "data/corpus/problem_bank_*/problems.jsonl")):
            if Path(path).parent.name == batch.CORPUS_DIR_NAME:
                continue
            for line in Path(path).read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                other = json.loads(line)
                assert other.get("problem_id") not in ids, path
                assert other.get("slug") not in slugs, path


#: 5단계 — 슬롯 칸이 아니라 *스킬*을 덮으려고 만든 개념(02-03 규칙 일반화 · 02-10 문장제). 이 개념들의
#: 6칸은 이미 승인 문항이 채웠으므로 아래 "빈 칸만 생성" 불변식의 대상이 아니다.
_SKILL_COVERAGE: dict[str, str] = {
    "[12미적Ⅰ-02-03]": "ptype.generalize-pattern",
    "[12미적Ⅰ-02-10]": "ptype.model-word-problem",
}


def _code_of(row: dict[str, Any], spec: Any) -> str:
    src = next(c["concept_src_id"] for c in row["concepts"] if c["role"] == "PRIMARY")
    return str(next(c.code for c in spec.concepts if c.source_id == src))


class TestSkillCoverageItems:
    """5단계 24건 × 2 — 스킬 pattern-generalization · word-problem-modeling 을 행사하는 문제유형."""

    def test_each_skill_concept_has_24_items_of_its_modeling_type(self) -> None:
        spec = ps.load_scope_spec()
        for code, ptype in _SKILL_COVERAGE.items():
            rows = [r for r in _rows() if _code_of(r, spec) == code]
            assert len(rows) == 24, (code, len(rows))
            assert {tuple(r["problem_type_codes"]) for r in rows} == {(ptype,)}, code

    def test_no_other_concept_borrows_a_skill_type(self) -> None:
        spec = ps.load_scope_spec()
        skill_types = set(_SKILL_COVERAGE.values())
        for row in _rows():
            if _code_of(row, spec) in _SKILL_COVERAGE:
                continue
            assert not skill_types & set(row["problem_type_codes"]), row["slug"]


class TestOnlyMissingCellsAreGenerated:
    """ "재배정 먼저, 모자라는 칸만 생성"(Kiki 결정 ②) — 이 은행의 슬롯은 기존 승인 문항이 못 채운 칸이다.

    5단계 개념(`_SKILL_COVERAGE`)은 스킬을 덮는 문항이라 이 불변식에서 제외한다.
    """

    def test_every_generated_cell_is_empty_without_this_bank(self) -> None:
        spec = ps.load_scope_spec()
        index = ps.load_reference_index(spec)
        corpus = pc.load_corpus(spec)
        mine = {r["problem_id"] for r in _rows()}
        legacy = pc.CoverageCorpus(
            **{
                **corpus.__dict__,
                "problems": tuple(p for p in corpus.problems if p.problem_id not in mine),
            }
        )
        report = pc.evaluate(spec, index, legacy)
        assert report.slots is not None
        names = {s.id: s.name_ko for s in spec.slots}
        unmet = {u.subject: " ".join(u.missing) for u in report.slots.unmet}
        by_concept: dict[str, set[str]] = {}
        for row in _rows():
            code = _code_of(row, spec)
            if code in _SKILL_COVERAGE:
                continue
            (slot,) = parse_slot_tags(row["tags"]).slots
            by_concept.setdefault(code, set()).add(slot.value)
        assert by_concept, "생성한 칸이 없다"
        for code, slots in by_concept.items():
            for slot in slots:
                assert names[slot] in unmet.get(
                    code, ""
                ), f"{code} 의 {names[slot]} 칸은 기존 승인 문항이 이미 채웠다 — 생성하지 않는다"
        assert ProblemSlot.REPRESENTATIVE.value in by_concept["[12미적Ⅰ-02-01]"]
        assert ProblemSlot.APPLIED.value in by_concept["[12미적Ⅰ-02-02]"]
        assert ProblemSlot.DIAGNOSTIC.value in by_concept["[12미적Ⅰ-02-07]"]


def test_registry_lists_the_generators_in_bank_order() -> None:
    assert [g.standard_code for g in batch.GENERATORS] == [
        "[12미적Ⅰ-02-01]",
        "[12미적Ⅰ-02-02]",
        "[12미적Ⅰ-02-07]",
        "[12미적Ⅰ-02-03]",
        "[12미적Ⅰ-02-10]",
    ]
