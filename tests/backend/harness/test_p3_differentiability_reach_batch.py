"""[12미적Ⅰ-02-02] 스킬 도달 은행 배치(P3-65) — 재생성 드리프트·게이트 통과·승인 미기록·범위.

재생성은 1분 30초 안팎이라 모듈에서 한 번만 돌려 테스트들이 나눠 쓴다. 저작 도구 회귀라
`corpus_authoring` 잡(생성기·배치를 건드리는 PR + 야간)에서 돈다 — backend 잡의 시간 상한 보호.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.harness import p3_differentiability_reach_batch as batch
from whymath_backend.harness.p3_calculus1_diff_batch import drift_against
from whymath_backend.harness.p3_fill_batch import CORPUS_DIR_NAME as FILL_CORPUS

pytestmark = pytest.mark.corpus_authoring

_REPO = Path(__file__).resolve().parents[3]
_BANK = _REPO / "data" / "corpus" / batch.CORPUS_DIR_NAME
_FACTS = json.loads((_REPO / "docs" / "data" / "corpus_facts.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def fresh(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    out = tmp_path_factory.mktemp("reach") / "problems.jsonl"
    report = batch.run_p3_differentiability_reach_batch(out_path=out)
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
        assert report.total_requested == 300
        assert report.total_stored == report.total_requested
        assert all(not b.failure_reasons for b in report.bands)

    def test_committed_bank_equals_the_regeneration(self, fresh: dict[str, Any]) -> None:
        assert drift_against(_BANK, fresh["problems"], fresh["provenance"]) == []

    def test_drift_is_detected_when_a_byte_changes(
        self, fresh: dict[str, Any], tmp_path: Path
    ) -> None:
        """대조군 — 은행 사본의 한 글자를 바꾸면 같은 비교가 드리프트를 낸다(변별력)."""
        original = (_BANK / "problems.jsonl").read_bytes()
        mutated = original.replace("구하시오".encode(), "구하시요".encode(), 1)
        assert mutated != original
        (tmp_path / "problems.jsonl").write_bytes(mutated)
        (tmp_path / "_provenance.json").write_bytes((_BANK / "_provenance.json").read_bytes())
        assert drift_against(tmp_path, fresh["problems"], fresh["provenance"]) != []


class TestBankShape:
    def test_record_count_matches_the_single_source_of_facts(self) -> None:
        assert len(_rows()) == 300
        assert _FACTS["problem_bank.p3_differentiability_reach_v0"] == 300

    def test_no_record_carries_a_review_status(self) -> None:
        """승인은 감사 라운드(사람 게이트)의 몫 — 저작 도구는 그 키를 쓰지 않는다."""
        assert all("review_status" not in r for r in _rows())

    def test_one_concept_only(self) -> None:
        """범위 ② — [12미적Ⅰ-02-02] 하나만(02-06 등 다른 개념은 채우지 않는다)."""
        for r in _rows():
            assert r["achievement_standard_codes"] == ["[12미적Ⅰ-02-02]"]
            assert [c["concept_src_id"] for c in r["concepts"]] == ["H:12미적Ⅰ02-02"]
            assert {c["role"] for c in r["concepts"]} == {"PRIMARY"}

    def test_types_and_kinds_are_carried_into_the_record(self) -> None:
        kinds = {(r["problem_type_codes"][0], r["verify"].get("answer_kind")) for r in _rows()}
        assert kinds == {
            ("ptype.count-solutions", "nondifferentiable_point_count"),
            ("ptype.verify-claim", "is_differentiable"),
        }

    def test_every_record_has_solution_steps(self) -> None:
        assert all(len(r["verify"]["solution_steps"]) >= 2 for r in _rows())

    def test_self_authored_license(self) -> None:
        for r in _rows():
            assert r["license"] == "WHYMATH_GENERATED"
            assert r["source_type"] == "자체생성"
            assert r["is_published"] is False

    def test_it_is_a_new_bank_not_the_approved_fill_bank(self) -> None:
        assert batch.CORPUS_DIR_NAME != FILL_CORPUS
        provenance = json.loads((_BANK / "_provenance.json").read_text(encoding="utf-8"))
        assert provenance["record_count"] == 300
        assert provenance["task"] == "P3-65-calc1-02-02-skill-reaching-bank"


def test_batch_is_byte_deterministic(tmp_path: Path) -> None:
    """한 함수 안에서 두 번 돌린다(헌법 R3-01 가드 — 같은 함수 안 진입점 호출 2회 + `==` 단언)."""
    first, second = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    batch.run_p3_differentiability_reach_batch(out_path=first)
    batch.run_p3_differentiability_reach_batch(out_path=second)
    assert first.read_bytes() == second.read_bytes()
