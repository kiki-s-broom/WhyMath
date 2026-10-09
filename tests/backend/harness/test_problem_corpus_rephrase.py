"""발문 다양화 후처리 CLI(S2-p 후속) — 수치·정답 불변·fail-closed·리포트 단위테스트(hermetic).

FakeProvider 주입 rephraser로 라이브 0. 핵심: question_text만 바뀌고 수치·정답·선지·distractor는
불변, 검증 실패는 원문 유지(fail-closed)·리포트에 정직 관측.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from whymath_backend.harness.problem_corpus_batch import run_corpus_batch
from whymath_backend.harness.problem_corpus_rephrase import main, run_corpus_rephrase
from whymath_backend.l1.problem_bank.populate import load_problem_bank_records
from whymath_backend.l3.equivalent.rephrase import QuestionRephraser
from whymath_backend.l3.models import GenerationResult, RoutingDecision


class _EchoRephraseProvider:
    """발문의 방정식을 보존한 채 접미사만 붙여 '다양화'를 흉내낸다(결정론·hermetic).

    실제 LLM 없이 rephrase 성공 경로를 만들려면 방정식 substring을 보존하고 추가 등식이 없는
    문자열을 돌려줘야 한다 — 원 발문 끝에 자연어 접미사를 붙인다.
    """

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        *,
        images: Sequence[str] | None = None,
        temperature: float | None = None,
        json_schema: Mapping[str, object] | None = None,
        seed: int | None = None,  # EOS-73 — LLMProvider 계약 정합(대역은 시드를 쓰지 않는다)
    ) -> GenerationResult:
        # 프롬프트의 '원 발문: ...' 줄에서 발문을 되읽어 접미사를 붙인다(방정식 보존).
        for line in prompt.splitlines():
            if line.startswith("원 발문: "):
                return GenerationResult(line[len("원 발문: ") :] + " (다양화)")
        return GenerationResult("무효")  # pragma: no cover — 프롬프트 형식 보증


def _seed_corpus(tmp_path: Path) -> Path:
    """소형 결정론 코퍼스를 생성해 rephrase 입력으로 쓴다(스켈레톤 배치 재사용).

    rephrase는 이차방정식 발문(방정식 substring 추출)이 대상이라 **quad 밴드만** 시드한다
    (calc_* 밴드 전건 0 — extremum·tangent·value·value-mc·extremum-irr) — 삼차 계열 발문은
    방정식 추출 대상이 아니라 rephrase 범위 밖이다.
    """
    src = tmp_path / "src.jsonl"
    report = run_corpus_batch(
        out_path=src,
        short_n=6,
        mc_n=3,
        sqrt_n=2,
        sqrt_mc_n=1,
        calc_extremum_n=0,
        calc_tangent_n=0,
        calc_value_n=0,
        calc_value_mc_n=0,
        calc_extremum_irr_n=0,
        exp_n=0,
        log_n=0,
        arith_n=0,
        geo_n=0,
        trig_n=0,
        arith_sum_n=0,
        geo_sum_n=0,
        trig_eq_n=0,
        seq_inductive_n=0,
        write=True,
    )
    assert report.fulfilled
    return src


def _rephraser(provider: object) -> QuestionRephraser:
    return QuestionRephraser(provider)  # type: ignore[arg-type]


class TestRunCorpusRephrase:
    def test_rephrases_all_and_preserves_math(self, tmp_path: Path) -> None:
        src = _seed_corpus(tmp_path)
        out = tmp_path / "rephrased.jsonl"
        before = load_problem_bank_records(src)

        report = run_corpus_rephrase(
            in_path=src, out_path=out, rephraser=_rephraser(_EchoRephraseProvider()), write=True
        )
        assert report.total == 12
        assert report.rephrased == 12  # 전건 방정식 보존 접미사 → 검증 통과
        assert report.written == 12

        after = load_problem_bank_records(out)
        assert len(after) == len(before) == 12
        by_slug_before = {r.slug: r for r in before}
        for record in after:
            original = by_slug_before[record.slug]
            # 발문은 바뀌고(접미사) 수치·정답·선지·distractor·조건은 불변.
            assert record.problem.question_text != original.problem.question_text
            assert record.problem.question_text.endswith("(다양화)")
            assert record.problem.answer == original.problem.answer
            assert record.problem.choices == original.problem.choices
            assert record.verify.conditions == original.verify.conditions
            assert record.verify.answer_selection == original.verify.answer_selection
            assert record.problem.distractor_map == original.problem.distractor_map

    def test_rephrased_corpus_still_passes_acceptance_gate(self, tmp_path: Path) -> None:
        # 다양화 후에도 코퍼스가 S2-a 게이트를 통과(수치·정답 불변이라 정확성 게이트 무료 재통과).
        from whymath_backend.l3.equivalent.acceptance import (
            EquivalenceSpec,
            evaluate_equivalent_candidate,
        )
        from whymath_backend.schema.provenance import ContentProvenance

        src = _seed_corpus(tmp_path)
        out = tmp_path / "rephrased.jsonl"
        run_corpus_rephrase(
            in_path=src, out_path=out, rephraser=_rephraser(_EchoRephraseProvider()), write=True
        )
        for record in load_problem_bank_records(out):
            problem = record.problem
            misc = frozenset(e.misconception_id for e in (problem.distractor_map or []))
            spec = EquivalenceSpec(
                achievement_standard_codes=frozenset(problem.achievement_standard_codes),
                target_misconception_ids=misc,
                difficulty_overall=problem.difficulty_overall or 3.0,
                answer_format=problem.answer_format,
            )
            verdict = evaluate_equivalent_candidate(
                spec,
                problem,
                provenance=ContentProvenance(
                    generation_type=record.provenance.generation_type,
                    license=record.provenance.license,
                    original_source=record.provenance.original_source,
                ),
                conditions=record.verify.conditions,
                answer_map=record.verify.answer_map,
                answer_selection=record.verify.answer_selection,
            )
            assert verdict.accepted is True, f"{record.slug} 미수용: {verdict.reasons}"

    def test_failed_rephrase_keeps_original(self, tmp_path: Path) -> None:
        # provider가 방정식을 변조 → 전건 fail-closed(원문 유지)·리포트에 사유 관측.
        class _CorruptProvider:
            async def generate(self, *args: object, **kwargs: object) -> GenerationResult:
                return GenerationResult("이차방정식 9x^2 = 0 큰 근은?")  # 방정식 substring 미보존

        src = _seed_corpus(tmp_path)
        out = tmp_path / "rephrased.jsonl"
        before = {r.slug: r.problem.question_text for r in load_problem_bank_records(src)}
        report = run_corpus_rephrase(
            in_path=src, out_path=out, rephraser=_rephraser(_CorruptProvider()), write=True
        )
        assert report.rephrased == 0
        assert report.unchanged == 12
        assert report.unchanged_reason_sample  # 조용한 실패 금지 — 사유 표본 존재
        after = {r.slug: r.problem.question_text for r in load_problem_bank_records(out)}
        assert after == before  # 전건 원문 유지

    def test_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        src = _seed_corpus(tmp_path)
        out = tmp_path / "rephrased.jsonl"
        report = run_corpus_rephrase(
            in_path=src, out_path=out, rephraser=_rephraser(_EchoRephraseProvider()), write=False
        )
        assert report.written is None
        assert not out.exists()


class TestCliEntry:
    def test_main_without_live_provider_fails_closed(
        self, tmp_path: Path, capsys: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # fail-closed 계약(전건 provider 예외 → unchanged)은 환경 무관이어야 한다.
        # [OPS-44 사고 경위] "이 환경 LLM 0" 전제였으나 Kiki 머신은 Ollama가 상시 기동이라
        # 실제 변형이 일어나 깨졌다 — provider 해소를 예외로 강제 차단해 전제를 코드로 봉인.
        def _blocked(self: QuestionRephraser) -> None:
            raise RuntimeError("테스트 강제 차단 — 라이브 provider 해소 금지")

        monkeypatch.setattr(QuestionRephraser, "_resolve_provider", _blocked)
        src = _seed_corpus(tmp_path)
        out = tmp_path / "rephrased.jsonl"
        code = main(["--in", str(src), "--out", str(out)])
        assert code == 0
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        report = json.loads(captured.out)
        assert report["total"] == report["unchanged"]
        assert report["rephrased"] == 0
        assert report["unchanged_reason_sample"]  # 사유 관측


class TestRephraseAuthorSignature:
    """PB-17 — LLM 이 다시 쓴 레코드는 소스의 결정론 서명을 승계하지 않는다."""

    def test_rephrased_records_drop_deterministic_signature_unchanged_keep_it(
        self, tmp_path: Path
    ) -> None:
        src = _seed_corpus(tmp_path)
        lines = [json.loads(x) for x in src.read_text(encoding="utf-8").splitlines() if x.strip()]
        # 신규 배치는 서명을 찍는다(생성 시점 서명) — 전제 확인.
        assert all(r["authored_by"].startswith("deterministic:") for r in lines)

        out = tmp_path / "rephrased.jsonl"
        report = run_corpus_rephrase(
            in_path=src, out_path=out, rephraser=_rephraser(_EchoRephraseProvider())
        )
        assert report.rephrased > 0

        before = {r["slug"]: r for r in lines}
        after = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines() if x.strip()]
        changed = [r for r in after if r["question_text"] != before[r["slug"]]["question_text"]]
        assert changed, "다양화 성공 레코드가 없다 — 대역/전제 점검"
        for record in changed:
            assert "authored_by" not in record, "LLM 재작성분이 결정론 서명을 승계했다"
        for record in after:
            if record["question_text"] == before[record["slug"]]["question_text"]:
                assert record["authored_by"] == before[record["slug"]]["authored_by"]
