"""변형 3종 하네스(PB-09) 테스트 — 작동한 비율 깔때기·계보 무결성·dedup 시드·무작동 exit(hermetic).

합성 부모 코퍼스(tmp_path)로 결정론 검증하고, 실 `generated_v0` 일부로 "실제 코퍼스에서도
세 모드가 전부 살아 있다"를 한 번 더 못 박는다(부착됐으나 무작동인 모드가 정상 종료로 보이지 않게).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.harness import problem_corpus_variants as mod
from whymath_backend.harness.problem_corpus_variants import (
    VariantsReport,
    main,
    run_corpus_variants,
)
from whymath_backend.l1.embedding_provider import FakeEmbeddingProvider
from whymath_backend.l1.problem_bank.embedding import ProblemEmbeddingIndex
from whymath_backend.l3.equivalent.variants import MOVES
from whymath_backend.schema.enums import GenerationType, RelationType

_REPO = Path(__file__).resolve().parents[3]
_GENERATED_V0 = _REPO / "data" / "corpus" / "problem_bank_generated_v0" / "problems.jsonl"


def _row(slug: str, conditions: str, selection: str, answer: str) -> dict[str, Any]:
    return {
        "problem_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"test:{slug}")),
        "slug": slug,
        "source_type": "자체생성",
        "curriculum_version": "2022_REVISION",
        "valid_from_year": 2022,
        "subject": "공통",
        "unit_codes": ["QUAD-EQ"],
        "question_format": "단답형",
        "answer_format": "실수",
        "question_text": f"이차방정식 {conditions} 의 근을 구하시오.",
        "answer": answer,
        "answer_explanation": "해설",
        "difficulty_overall": 2.0,
        "achievement_standard_codes": ["[9수02-20]"],
        "license": "WHYMATH_GENERATED",
        "generation_type": "FULLY_GENERATED",
        "concepts": [{"concept_src_id": "HK06", "role": "PRIMARY", "relevance": 0.95}],
        "verify": {
            "conditions": conditions,
            "answer_map": {"x": answer},
            "answer_selection": selection,
        },
    }


def _write(path: Path, rows: Sequence[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", "utf-8")
    return path


# (x−5)(x+4) 큰 근/작은 근 쌍 + (x−3)(x+2) + 비원시·무리근(부모 자격 미달)
_PARENTS = [
    _row("p-large", "x**2 - x - 20 = 0", "largest", "5"),
    _row("p-small", "x**2 - x - 20 = 0", "smallest", "-4"),
    _row("p-other", "x**2 - x - 6 = 0", "largest", "3"),
    _row("p-irr", "x**2 - 2*x - 1 = 0", "largest", "1 + sqrt(2)"),
]


def _run(tmp_path: Path, out_name: str = "out.jsonl", **kwargs: Any) -> VariantsReport:
    parents = _write(tmp_path / "parents.jsonl", _PARENTS)
    return run_corpus_variants(
        parent_paths=[parents],
        signature_paths=kwargs.pop("signature_paths", [parents]),
        out_path=tmp_path / out_name,
        **kwargs,
    )


class TestFunnelAccounting:
    def test_identities_hold_and_attempts_are_parents_times_moves(self, tmp_path: Path) -> None:
        report = _run(tmp_path)
        payload = report.to_json()  # 항등식이 깨지면 to_json이 예외를 던진다
        assert report.parents_total == 4
        assert report.parents_eligible == 3
        assert sum(report.parent_rejections.values()) == 1
        assert report.attempted_total == 3 * len(MOVES)
        for move in payload["moves"]:
            assert move["attempted"] == sum(move["skipped"].values()) + move["derived"]
            assert move["derived"] == sum(move["outcomes"].values())

    def test_broken_identity_is_not_reported_as_truth(self, tmp_path: Path) -> None:
        report = _run(tmp_path)
        report.moves[0].attempted += 1  # 시도가 조용히 유실된 상황을 주입
        with pytest.raises(AssertionError, match="유실"):
            report.to_json()

    def test_working_rate_is_stored_over_attempted_and_none_when_no_attempts(
        self, tmp_path: Path
    ) -> None:
        report = _run(tmp_path)
        assert report.working_rate == report.stored_total / report.attempted_total
        empty = run_corpus_variants(
            parent_paths=[_write(tmp_path / "e.jsonl", [_PARENTS[3]])],
            signature_paths=[],
            out_path=tmp_path / "e_out.jsonl",
        )
        assert empty.attempted_total == 0
        assert empty.working_rate is None  # 0.0으로 위장하지 않는다


class TestLineageIntegrity:
    def test_every_stored_record_has_one_lineage_edge_to_a_real_parent(
        self, tmp_path: Path
    ) -> None:
        report = _run(tmp_path)
        rows = [
            json.loads(line)
            for line in (tmp_path / "out.jsonl").read_text("utf-8").splitlines()
            if line.strip()
        ]
        assert report.written == len(rows) == report.stored_total > 0
        parent_slugs = {r["slug"] for r in _PARENTS}
        valid_relations = {r.value for r in RelationType}
        valid_generations = {
            GenerationType.VARIANT_NUMBER.value,
            GenerationType.VARIANT_STRUCTURE.value,
            GenerationType.VARIANT_CONTEXT.value,
        }
        for row in rows:
            assert len(row["relations"]) == 1  # anti-explosion: 자식당 계보 1건
            edge = row["relations"][0]
            assert edge["parent_slug"] in parent_slugs  # dangling 0
            assert edge["parent_slug"] != row["slug"]
            assert edge["relation_type"] in valid_relations
            assert edge["similarity_score"] is None  # 근거 없는 유사도 수치를 날조하지 않는다
            assert row["generation_type"] in valid_generations  # FULLY_GENERATED로 새지 않는다
            assert row["license"] == "WHYMATH_GENERATED"

    def test_report_counts_the_enum_seats_actually_used(self, tmp_path: Path) -> None:
        report = _run(tmp_path).to_json()
        assert set(report["relation_type_counts"]) <= {"심화", "선수", "변형", "대조"}
        assert "FULLY_GENERATED" not in report["generation_type_counts"]
        assert sum(report["generation_type_counts"].values()) == report["stored_total"]

    def test_output_is_byte_identical_across_runs(self, tmp_path: Path) -> None:
        _run(tmp_path, "a.jsonl")
        _run(tmp_path, "b.jsonl")
        assert (tmp_path / "a.jsonl").read_bytes() == (tmp_path / "b.jsonl").read_bytes()


class TestDedup:
    def test_signature_seed_blocks_variants_that_already_exist(self, tmp_path: Path) -> None:
        # 큰 근/작은 근 부모가 둘 다 코퍼스에 있으므로 어느 쪽의 선택 뒤집기도 기존 구조와 같다.
        report = _run(tmp_path)
        flip = next(m for m in report.moves if m.move == "condition_flip")
        assert flip.outcomes["rejected_duplicate/structural_signature"] >= 2

    def test_unseeded_run_does_not_hide_those_duplicates(self, tmp_path: Path) -> None:
        # 대조군: 시드가 비면 같은 선택 뒤집기가 중복으로 안 걸린다(= 시드가 실제로 일하고 있다).
        seeded = _run(tmp_path, "s.jsonl")
        unseeded = _run(tmp_path, "u.jsonl", signature_paths=[])
        flip_seeded = next(m for m in seeded.moves if m.move == "condition_flip")
        flip_unseeded = next(m for m in unseeded.moves if m.move == "condition_flip")
        assert flip_unseeded.stored > flip_seeded.stored

    def test_two_parents_with_the_same_roots_cannot_store_the_same_child_twice(
        self, tmp_path: Path
    ) -> None:
        # 구조 signature가 없는(연립 조건) 역문제는 자체 변형 키가 거른다.
        report = _run(tmp_path)
        inverse = next(m for m in report.moves if m.move == "inverse")
        assert inverse.outcomes["rejected_duplicate/variant_key"] == 1  # p-large/p-small 쌍

    def test_embedding_seat_reaches_the_pipeline(self, tmp_path: Path) -> None:
        class _AlwaysNear(ProblemEmbeddingIndex):
            def __init__(self) -> None:
                super().__init__(provider_name="fake", model_name="fake-hash")

            def search(  # type: ignore[override]
                self, vector: Sequence[float], *, top_k: int
            ) -> list[tuple[uuid.UUID, float]]:
                return [(uuid.uuid4(), 0.999)][:top_k]

            def upsert(  # type: ignore[override]
                self, problem_id: uuid.UUID, vector: Sequence[float], *, source_text: str
            ) -> None:
                return None

        report = _run(tmp_path, dedup_index=_AlwaysNear(), embed_provider=FakeEmbeddingProvider())
        assert report.stored_total == 0  # 전건 과유사로 차단 — 임베딩 dedup이 같은 경로로 돈다
        embedding_hits = sum(
            count
            for move in report.moves
            for key, count in move.outcomes.items()
            if key == "rejected_duplicate/embedding_near"
        )
        assert embedding_hits > 0


class TestMoveSelection:
    def test_moves_subset_limits_attempts(self, tmp_path: Path) -> None:
        report = _run(tmp_path, moves=("inverse",))
        assert [m.move for m in report.moves] == ["inverse"]
        assert report.attempted_total == 3

    def test_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        report = _run(tmp_path, write=False)
        assert report.written is None
        assert not (tmp_path / "out.jsonl").exists()


class TestCli:
    @staticmethod
    def _fake_repo(tmp_path: Path, rows: Sequence[dict[str, Any]]) -> Path:
        corpus = tmp_path / "repo" / "data" / "corpus"
        _write(corpus / "problem_bank_generated_v0" / "problems.jsonl", rows)
        return tmp_path / "repo"

    def test_exit_zero_when_every_requested_mode_stored_something(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo = self._fake_repo(tmp_path, _PARENTS[:3])
        monkeypatch.setattr(mod, "_repo_root", lambda: repo)
        out = tmp_path / "cli_out.jsonl"
        # 같은 코퍼스가 시드이므로 부모 자신과 겹치는 구조는 걸러지지만 3모드 모두 살아 있다.
        assert main(["--out", str(out)]) == 0
        report = json.loads(capsys.readouterr().out)
        assert all(report["mode_stored"][m] > 0 for m in ("ladder", "condition", "inverse"))
        assert out.exists()

    def test_exit_one_when_a_requested_mode_is_silent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # 비모닉 부모만 있으면 역문제는 전부 skip → 저장 0건. 정상 종료로 보이면 안 된다.
        rows = [_row("p-rat", "2*x**2 - 3*x - 35 = 0", "largest", "5")]
        repo = self._fake_repo(tmp_path, rows)
        monkeypatch.setattr(mod, "_repo_root", lambda: repo)
        assert main(["--out", str(tmp_path / "o.jsonl"), "--moves", "inverse"]) == 1
        assert json.loads(capsys.readouterr().out)["mode_stored"]["inverse"] == 0

    def test_exit_three_when_signature_corpora_are_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 스캔 0건은 "중복 없음"으로 위장하지 않고 환경 오류로 낸다.
        empty = tmp_path / "repo"
        (empty / "data" / "corpus").mkdir(parents=True)
        monkeypatch.setattr(mod, "_repo_root", lambda: empty)
        assert main(["--out", str(tmp_path / "o.jsonl")]) == 3

    def test_dry_run_flag_writes_no_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = self._fake_repo(tmp_path, _PARENTS[:3])
        monkeypatch.setattr(mod, "_repo_root", lambda: repo)
        out = tmp_path / "dry.jsonl"
        assert main(["--out", str(out), "--dry-run"]) == 0
        assert not out.exists()


@pytest.mark.skipif(not _GENERATED_V0.exists(), reason="실 코퍼스 부재")
class TestRealCorpusSlice:
    def test_all_three_modes_work_on_real_generated_v0(self, tmp_path: Path) -> None:
        # 앞쪽 일부만 쓴다(게이트 비용) — 합성 부모가 아닌 실 부모에서도 세 모드가 저장 ≥ 1이어야 한다.
        rows = [
            json.loads(line)
            for line in _GENERATED_V0.read_text("utf-8").splitlines()[:60]
            if line.strip()
        ]
        parents = _write(tmp_path / "real_parents.jsonl", rows)
        report = run_corpus_variants(
            parent_paths=[parents],
            signature_paths=[_GENERATED_V0],
            out_path=tmp_path / "real_out.jsonl",
        )
        report.to_json()
        stored = report.mode_stored()
        assert stored["ladder"] > 0
        assert stored["condition"] > 0
        assert stored["inverse"] > 0
        assert report.silent_modes(("ladder", "condition", "inverse")) == []
