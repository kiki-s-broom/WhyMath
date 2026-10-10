"""페르소나 적합도 백필 CLI(S3-10) — 멱등·바이트 보존·근거 감사·dry-run 단위테스트(hermetic).

핵심 봉인: ① `persona_fit`이 이미 채워진 레코드는 **바이트 무변경**(수동 큐레이션 존중) ②
비어 있는 레코드만 그 한 키가 계산값으로 교체된다(그 외 바이트 무변경) ③ 2회 실행 바이트 동일
(멱등 — 첫 실행이 채우므로 재실행은 전건 already_set) ④ 채운 레코드마다 감사 JSONL에 계산 근거가
남는다("근거 동반") ⑤ dry-run은 파일 미기록·통계만 ⑥ `KNOWN_CORPORA`가 실제 7개 코퍼스 경로를
가리킨다(오타·누락 방지 — 실 파일 시스템 접근 없이 문자열만 확인. 원 구현 6종 + 회수 시 추가된
`probability_finite_v0`). LLM·DB 0(순수 결정론).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from whymath_backend.harness.problem_corpus_persona_fit_backfill import (
    KNOWN_CORPORA,
    main,
    run_persona_fit_backfill,
)


def _record(
    *,
    slug: str,
    persona_fit: dict[str, float] | None = None,
    difficulty_overall: float = 2.0,
    question_format: str = "단답형",
    include_key: bool = True,
) -> dict[str, object]:
    """최소 유효 코퍼스 레코드(populate 로더 authoring 키 포함) — `_problem` 픽스처의 raw 버전."""
    rec: dict[str, object] = {
        "slug": slug,
        "problem_id": str(uuid.uuid5(uuid.NAMESPACE_URL, slug)),
        "source_type": "자체생성",
        "license": "WHYMATH_GENERATED",
        "generation_type": "FULLY_GENERATED",
        "curriculum_version": "2022_REVISION",
        "valid_from_year": 2022,
        "subject": "공통",
        "unit_codes": ["QUAD-EQ"],
        "question_format": question_format,
        "question_text": "이차방정식 x^2 + 4x - 2 = 0 의 서로 다른 두 근의 합의 값을 구하시오.",
        "answer": "-4",
        "difficulty_overall": difficulty_overall,
        "concepts": [],
        "verify": {"conditions": "x**2 + 4*x - 2 = 0", "answer_map": {}, "answer_aggregate": "sum"},
    }
    if include_key:
        rec["persona_fit"] = {} if persona_fit is None else persona_fit
    return rec


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8"
    )


class TestRunPersonaFitBackfill:
    def test_fills_empty_leaves_nonempty_untouched(self, tmp_path: Path) -> None:
        records = [
            _record(slug="empty-dict", persona_fit={}),
            _record(slug="already-curated", persona_fit={"A_일반고고3": 0.42}),
            _record(slug="missing-key", include_key=False),
        ]
        src = tmp_path / "src.jsonl"
        out = tmp_path / "out.jsonl"
        audit = tmp_path / "audit.jsonl"
        _write_jsonl(src, records)

        report = run_persona_fit_backfill(in_path=src, out_path=out, audit_path=audit)

        assert report.total == 3
        assert report.filled == 2
        assert report.already_set == 1
        assert report.written == 3
        assert report.audit_written == 2

        out_lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
        by_slug = {r["slug"]: r for r in out_lines}
        assert by_slug["already-curated"]["persona_fit"] == {"A_일반고고3": 0.42}  # 무변경
        # 기본 question_format="단답형" → B·E에 형식 가산 +0.05(CORE 기본표 0.60/0.35 위).
        assert by_slug["empty-dict"]["persona_fit"] == {
            "A_일반고고3": 0.9,
            "B_자사고N수": 0.65,
            "C_검정고시N수": 0.85,
            "D_학종고2": 0.5,
            "E_홈스쿨링영재": 0.4,
        }
        assert by_slug["missing-key"]["persona_fit"] == by_slug["empty-dict"]["persona_fit"]

    def test_already_curated_line_is_byte_identical(self, tmp_path: Path) -> None:
        """이미 채워진 레코드가 유일한 레코드면 파일 전체가 바이트 그대로다."""
        records = [_record(slug="already-curated", persona_fit={"A_일반고고3": 0.42})]
        src = tmp_path / "src.jsonl"
        out = tmp_path / "out.jsonl"
        audit = tmp_path / "audit.jsonl"
        _write_jsonl(src, records)

        report = run_persona_fit_backfill(in_path=src, out_path=out, audit_path=audit)

        assert report.filled == 0 and report.already_set == 1
        assert out.read_bytes() == src.read_bytes()
        assert not audit.exists()  # 채운 레코드가 없으면 감사 파일도 만들지 않는다.

    def test_rerun_is_byte_identical_idempotent(self, tmp_path: Path) -> None:
        """첫 실행이 채운 뒤 재실행하면 전건 already_set·산출 바이트 동일(멱등)."""
        records = [_record(slug="a"), _record(slug="b", difficulty_overall=4.0)]
        src = tmp_path / "src.jsonl"
        _write_jsonl(src, records)

        first = run_persona_fit_backfill(
            in_path=src, out_path=src, audit_path=tmp_path / "audit1.jsonl"
        )
        assert first.filled == 2
        after_first = src.read_bytes()

        second = run_persona_fit_backfill(
            in_path=src, out_path=src, audit_path=tmp_path / "audit2.jsonl"
        )
        assert second.filled == 0 and second.already_set == 2
        assert src.read_bytes() == after_first

    def test_audit_entries_carry_reconstructible_rationale(self, tmp_path: Path) -> None:
        """감사 항목의 band_base + 각 가산을 더하면 persona_fit과 같다("근거 동반")."""
        records = [_record(slug="killer", difficulty_overall=4.0, question_format="단답형")]
        src = tmp_path / "src.jsonl"
        out = tmp_path / "out.jsonl"
        audit = tmp_path / "audit.jsonl"
        _write_jsonl(src, records)

        run_persona_fit_backfill(in_path=src, out_path=out, audit_path=audit)

        entry = json.loads(audit.read_text(encoding="utf-8").splitlines()[0])
        assert entry["slug"] == "killer"
        assert entry["band"] == "KILLER"
        for key, value in entry["persona_fit"].items():
            reconstructed = (
                entry["band_base"][key]
                + entry["signature_bonus"].get(key, 0.0)
                + entry["complex_reasoning_bonus"].get(key, 0.0)
                + entry["format_bonus"].get(key, 0.0)
                + entry["distractor_bonus"].get(key, 0.0)
            )
            assert value == round(min(1.0, max(0.0, reconstructed)), 2)

    def test_band_counts_aggregate_only_filled_records(self, tmp_path: Path) -> None:
        records = [
            _record(slug="core", difficulty_overall=2.0),
            _record(slug="killer", difficulty_overall=4.0),
            _record(slug="curated", persona_fit={"A_일반고고3": 0.5}, difficulty_overall=4.0),
        ]
        src = tmp_path / "src.jsonl"
        out = tmp_path / "out.jsonl"
        audit = tmp_path / "audit.jsonl"
        _write_jsonl(src, records)

        report = run_persona_fit_backfill(in_path=src, out_path=out, audit_path=audit)

        assert report.band_counts == {"CORE": 1, "KILLER": 1}  # curated는 already_set이라 제외

    def test_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        records = [_record(slug="a")]
        src = tmp_path / "src.jsonl"
        out = tmp_path / "out.jsonl"
        audit = tmp_path / "audit.jsonl"
        _write_jsonl(src, records)

        report = run_persona_fit_backfill(in_path=src, out_path=out, audit_path=audit, write=False)

        assert report.filled == 1
        assert report.written is None
        assert report.audit_written is None
        assert not out.exists()
        assert not audit.exists()


class TestMainCli:
    def test_main_in_out_writes_report(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        records = [_record(slug="a"), _record(slug="b", persona_fit={"A_일반고고3": 0.5})]
        src = tmp_path / "src.jsonl"
        out = tmp_path / "out.jsonl"
        audit = tmp_path / "audit.jsonl"
        _write_jsonl(src, records)

        exit_code = main(
            [
                "--in",
                str(src),
                "--out",
                str(out),
                "--audit-out",
                str(audit),
            ]
        )
        assert exit_code == 0
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert payload["total"] == 2 and payload["filled"] == 1 and payload["already_set"] == 1
        assert out.exists() and audit.exists()

    def test_all_and_out_together_is_rejected(self) -> None:
        try:
            main(["--all", "--out", "somewhere.jsonl"])
            raised = False
        except SystemExit as exc:
            raised = True
            assert exc.code == 2  # argparse.error() exit code
        assert raised


class TestKnownCorpora:
    # 원 구현(2026-07-29) 당시 6종이었으나, S3-10을 미병합 브랜치에서 회수하며(2026-07-30)
    # 그 사이 신설된 7번째 코퍼스(`probability_finite_v0` — S4-13 확률 유한 전수형 파일럿)를
    # 추가했다. 로직 무변경 — 대상 목록만 확장(모듈 docstring 참조). 8번째는 P3-03 미분 은행
    # (`p3_calculus1_diff_v0` — 5회차 S5 감사 승인 뒤 편입, 2026-10-09).
    def test_lists_exactly_eight_corpora(self) -> None:
        assert len(KNOWN_CORPORA) == 8

    def test_paths_match_expected_layout(self) -> None:
        expected = {
            "conceptual_v0": Path("data/corpus/problem_bank_conceptual_v0/problems.jsonl"),
            "generated_v0": Path("data/corpus/problem_bank_generated_v0/problems.jsonl"),
            "killer_v0": Path("data/corpus/problem_bank_killer_v0/problems.jsonl"),
            "misconception_mc_v0": (
                Path("data/corpus/problem_bank_misconception_mc_v0/problems.jsonl")
            ),
            "rephrased_v0": Path("data/corpus/problem_bank_rephrased_v0/problems.jsonl"),
            "v1": Path("data/corpus/problem_bank_v1/problems.jsonl"),
            "probability_finite_v0": (
                Path("data/corpus/problem_bank_probability_finite_v0/problems.jsonl")
            ),
            "p3_calculus1_diff_v0": (
                Path("data/corpus/problem_bank_p3_calculus1_diff_v0/problems.jsonl")
            ),
        }
        assert KNOWN_CORPORA == expected
