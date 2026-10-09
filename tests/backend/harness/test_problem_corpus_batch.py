"""동등문제 코퍼스 배치 CLI(S2-p) — 조성 루트·JSONL 라운드트립·결정론 단위테스트(hermetic).

핵심 봉인: ① 주입 매핑이 L4 정본과 정합(fail-fast) ② JSONL이 로더(`load_problem_bank_records`)
로 정확히 되읽힌다(라운드트립) ③ 같은 인자 재실행이 *바이트까지* 동일(결정론) ④ 수율 미달이면
종료 코드 1(조용한 실패 금지).
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from whymath_backend.harness.needs_review_worklist import build_worklist
from whymath_backend.harness.problem_corpus_batch import (
    _record_to_json,
    build_distractor_codes,
    main,
    run_corpus_batch,
)
from whymath_backend.l1.problem_bank.populate import (
    ProblemBankRecord,
    load_problem_bank_records,
)
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.l4.misconception.distractor import DISTRACTOR_BY_ID


class TestBuildDistractorCodes:
    def test_injection_targets_exist_in_l4_canon(self) -> None:
        # 조성 루트의 참조 무결성 — 주입 id 전부 L4 정본 실재 + op-code↔오개념 정합.
        codes = build_distractor_codes()
        assert set(codes) == {"opposite_root", "sign_flip"}
        for misconception_id, op_code in codes.values():
            assert misconception_id in CATALOG_BY_ID
            assert DISTRACTOR_BY_ID[op_code].misconception_id == misconception_id


class TestRunCorpusBatch:
    def test_dry_run_full_yield(self) -> None:
        # 소형 3밴드 dry-run — 전량 저장(수율 100%)·파일 미기록.
        report = run_corpus_batch(
            out_path=Path("/nonexistent/never-written.jsonl"),
            short_n=5,
            mc_n=3,
            sqrt_n=2,
            sqrt_mc_n=2,
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
            write=False,
        )
        assert report.fulfilled
        assert report.written is None
        assert [(b.name, b.requested, b.stored) for b in report.bands] == [
            ("short", 5, 5),
            ("mc", 3, 3),
            ("sqrt", 2, 2),
            ("sqrt_mc", 2, 2),
        ]
        assert all(b.failure_reasons == [] for b in report.bands)
        # 전량 수용 → 비수용 outcome 없음(워크리스트 대상 0).
        assert report.review_outcomes == []
        assert report.to_json()["review_outcomes_count"] == 0

    def test_review_outcomes_captured_on_shortfall(self) -> None:
        # 무리근 풀(122) 초과 요청 → generation_failed 8건이 review_outcomes에 포착(휘발 방지).
        # 밴드 블록 무접촉 shadowing 래퍼가 비수용 outcome만 누적함을 검증(수율·리포트는 불변).
        report = run_corpus_batch(
            out_path=Path("/nonexistent/never-written.jsonl"),
            short_n=0,
            mc_n=0,
            sqrt_n=130,
            sqrt_mc_n=0,
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
            write=False,
        )
        assert not report.fulfilled  # 수율 미달(정직)
        assert report.total_stored == 122  # 풀 전수 소진분은 저장(기존 동작 불변)
        assert len(report.review_outcomes) == 130 - 122  # 8건 포착
        assert all(o.status == "generation_failed" for o in report.review_outcomes)
        assert report.to_json()["review_outcomes_count"] == 8
        # 워크리스트 라이브러리가 이 포착분을 소비 가능(end-to-end).
        items = build_worklist(report.review_outcomes)
        assert len(items) == 8
        assert all(it.status == "generation_failed" for it in items)

    def test_authored_by_is_written_only_when_recorded_and_roundtrips(self, tmp_path: Path) -> None:
        # PB-15 — 서명은 기록이 있을 때만 JSONL에 실리고, 없으면 키 자체가 없다(기존 코퍼스와
        # 바이트 동일). 왕복: 쓴 값이 로더를 거쳐 그대로 돌아온다. 레코드는 커밋된 실제 코퍼스의
        # 첫 건을 쓴다(가공 픽스처가 아니라 로더가 실제로 받아들이는 형태).
        corpus = (
            Path(__file__).resolve().parents[3]
            / "data"
            / "corpus"
            / "problem_bank_probability_finite_v0"
            / "problems.jsonl"
        )
        committed = load_problem_bank_records(corpus)[0]
        # PB-17: 커밋된 코퍼스는 결정론 서명이 백필돼 있다 — 이 테스트의 전제(기록 없음)는 서명을
        # 지운 사본으로 만든다(기록 있는 레코드의 직렬화는 아래 recorded 가 이미 본다).
        assert committed.provenance.authored_by is not None
        base = replace(committed, provenance=replace(committed.provenance, authored_by=None))
        recorded = replace(
            base, provenance=replace(base.provenance, authored_by="llm:qwen3:30b-a3b")
        )

        assert "authored_by" not in _record_to_json(base)
        written = _record_to_json(recorded)
        assert written["authored_by"] == "llm:qwen3:30b-a3b"

        path = tmp_path / "roundtrip.jsonl"
        path.write_text(json.dumps(written, ensure_ascii=False) + "\n", encoding="utf-8")
        assert load_problem_bank_records(path)[0].provenance.authored_by == "llm:qwen3:30b-a3b"

    def test_written_corpus_roundtrips_through_loader(self, tmp_path: Path) -> None:
        # JSONL 산출물이 코퍼스 로더로 정확히 되읽힌다 — 형식·위생·Problem 검증 통과.
        out = tmp_path / "problems.jsonl"
        report = run_corpus_batch(
            out_path=out,
            short_n=6,
            mc_n=4,
            sqrt_n=3,
            sqrt_mc_n=2,
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
        assert report.fulfilled and report.written == 15

        records = load_problem_bank_records(out)
        assert len(records) == 15
        # 결정론 메타 — 전건 HK06 태깅·난이도 분산(2.5 균일 회귀 차단).
        for record in records:
            assert [t.concept_src_id for t in record.concept_tags] == ["HK06"]
            assert record.problem.difficulty_overall is not None
        assert len({r.problem.difficulty_overall for r in records}) >= 2
        # 객관식 밴드 — 실 L4 id로 distractor 태깅·answer∈choices.
        mc = [r for r in records if r.problem.question_format == "객관식"]
        assert len(mc) == 6  # 유리근 객관식 4 + 무리근 객관식 2
        for record in mc:
            problem = record.problem
            assert problem.choices is not None and problem.answer in problem.choices
            assert problem.distractor_map is not None and len(problem.distractor_map) == 3
            for entry in problem.distractor_map:
                assert entry.misconception_id in CATALOG_BY_ID
        # 무리근 밴드 — SymPy 정확값 answer.
        sqrt_records = [r for r in records if "sqrt(" in (r.problem.answer or "")]
        assert len(sqrt_records) == 5  # 무리근 단답형 3 + 무리근 객관식 2

    def test_rerun_is_byte_identical(self, tmp_path: Path) -> None:
        # 결정론 봉인 — 같은 인자 두 번 실행 = 바이트 동일(타임스탬프·uuid4·난수 오염 0).
        a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
        # calc 포함 전체 배치도 바이트 결정론(quad 4밴드 + calc 군).
        run_corpus_batch(
            out_path=a,
            short_n=5,
            mc_n=3,
            sqrt_n=2,
            sqrt_mc_n=2,
            calc_extremum_n=4,
            calc_tangent_n=4,
            calc_value_n=4,
            calc_value_mc_n=4,
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
        run_corpus_batch(
            out_path=b,
            short_n=5,
            mc_n=3,
            sqrt_n=2,
            sqrt_mc_n=2,
            calc_extremum_n=4,
            calc_tangent_n=4,
            calc_value_n=4,
            calc_value_mc_n=4,
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
        assert a.read_bytes() == b.read_bytes()

    def test_slugs_unique_across_quad_and_calc(self, tmp_path: Path) -> None:
        # slug(=멱등 upsert 키)은 문제군을 가로질러 전건 상이 — calc 도함수 방정식이 quad
        # 방정식과 signature가 겹칠 수 있어도(문제군 별 dedup) slug는 내용 해시라 충돌 없다.
        out = tmp_path / "problems.jsonl"
        run_corpus_batch(
            out_path=out,
            short_n=8,
            mc_n=4,
            sqrt_n=3,
            sqrt_mc_n=2,
            calc_extremum_n=10,
            calc_tangent_n=10,
            calc_value_n=10,
            calc_value_mc_n=10,
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
        slugs = [r.slug for r in load_problem_bank_records(out)]
        assert len(slugs) == len(set(slugs))

    def test_relations_form_linear_chain_within_group_only(self, tmp_path: Path) -> None:
        # 다중 문제군(QUAD-EQ·ARITH-SEQ) 배치 — 그룹((unit_codes,question_format,answer_format))
        # 내부에서만 "유사" 관계가 정렬순 인접 K=3 백엣지로 붙고, 그룹을 가로지르는 엣지는 0건
        # (anti-explosion 상한 준수).
        out = tmp_path / "problems.jsonl"
        run_corpus_batch(
            out_path=out,
            short_n=5,
            mc_n=0,
            sqrt_n=0,
            sqrt_mc_n=0,
            calc_extremum_n=0,
            calc_tangent_n=0,
            calc_value_n=0,
            calc_value_mc_n=0,
            calc_extremum_irr_n=0,
            exp_n=0,
            log_n=0,
            arith_n=5,
            geo_n=0,
            trig_n=0,
            arith_sum_n=0,
            geo_sum_n=0,
            trig_eq_n=0,
            seq_inductive_n=0,
            write=True,
        )
        records = load_problem_bank_records(out)
        by_slug = {r.slug: r for r in records}

        def group_key(r: ProblemBankRecord) -> tuple[Any, ...]:
            return (
                tuple(r.problem.unit_codes),
                r.problem.question_format,
                r.problem.answer_format,
            )

        groups: dict[tuple[Any, ...], list[ProblemBankRecord]] = {}
        for r in records:
            groups.setdefault(group_key(r), []).append(r)
        assert len(groups) >= 2  # 다중 문제군·형식이 실제로 분리 그룹을 이룸(테스트 전제 확인)

        for members in groups.values():
            ordered = sorted(members, key=lambda r: (r.problem.difficulty_overall or 0.0, r.slug))
            for pos, record in enumerate(ordered):
                expected_parents = [ordered[j].slug for j in range(max(0, pos - 3), pos)]
                assert [t.parent_slug for t in record.relations] == expected_parents
                for tag in record.relations:
                    assert tag.relation_type == "유사"
                    assert tag.similarity_score == 0.6
                    assert by_slug[tag.parent_slug] in members  # 그룹 내부만 참조(교차 0)

    def test_relations_field_present_even_when_empty(self, tmp_path: Path) -> None:
        # 관계 0건(단일 그룹 1레코드)도 "relations": [] 균일 기록 — 키 부재가 아니다(필드 존재
        # 자체가 "관계 계산 배선됨" 신호 — test_corpus_quality 키 집합 정합 봉인과 정합).
        out = tmp_path / "problems.jsonl"
        run_corpus_batch(
            out_path=out,
            short_n=1,
            mc_n=0,
            sqrt_n=0,
            sqrt_mc_n=0,
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
        raw = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
        assert raw["relations"] == []


class TestCliEntry:
    def test_main_exit_0_and_report_json(self, tmp_path: Path, capsys: object) -> None:
        out = tmp_path / "problems.jsonl"
        code = main(
            [
                "--out",
                str(out),
                "--short",
                "4",
                "--mc",
                "3",
                "--sqrt",
                "2",
                "--sqrt-mc",
                "2",
                "--calc-extremum",
                "0",
                "--calc-tangent",
                "0",
                "--calc-value",
                "0",
                "--calc-value-mc",
                "0",
                "--calc-extremum-irr",
                "0",
                "--exp",
                "0",
                "--log",
                "0",
                "--arith",
                "0",
                "--geo",
                "0",
                "--trig",
                "0",
                "--arith-sum",
                "0",
                "--geo-sum",
                "0",
                "--trig-eq",
                "0",
                "--seq-inductive",
                "0",
            ]
        )
        assert code == 0
        assert out.exists()
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        report = json.loads(captured.out)
        assert report["fulfilled"] is True
        assert report["total_stored"] == 11

    def test_main_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        out = tmp_path / "problems.jsonl"
        code = main(
            [
                "--out",
                str(out),
                "--short",
                "2",
                "--mc",
                "2",
                "--sqrt",
                "2",
                "--sqrt-mc",
                "2",
                "--calc-extremum",
                "0",
                "--calc-tangent",
                "0",
                "--calc-value",
                "0",
                "--calc-value-mc",
                "0",
                "--calc-extremum-irr",
                "0",
                "--exp",
                "0",
                "--log",
                "0",
                "--dry-run",
            ]
        )
        assert code == 0
        assert not out.exists()

    def test_main_exit_1_on_pool_exhaustion(self, tmp_path: Path, capsys: object) -> None:
        # 무리근 단답형 풀(파티션 후 122) 초과 요청 → generation_failed → 수율 미달 exit 1 + 사유.
        out = tmp_path / "problems.jsonl"
        code = main(
            [
                "--out",
                str(out),
                "--short",
                "0",
                "--mc",
                "0",
                "--sqrt",
                "130",
                "--sqrt-mc",
                "0",
                "--calc-extremum",
                "0",
                "--calc-tangent",
                "0",
                "--calc-value",
                "0",
                "--calc-value-mc",
                "0",
                "--calc-extremum-irr",
                "0",
                "--exp",
                "0",
                "--log",
                "0",
                "--arith",
                "0",
                "--geo",
                "0",
                "--trig",
                "0",
                "--arith-sum",
                "0",
                "--geo-sum",
                "0",
                "--trig-eq",
                "0",
                "--seq-inductive",
                "0",
            ]
        )
        assert code == 1
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        report = json.loads(captured.out)
        assert report["fulfilled"] is False
        assert report["total_stored"] == 122  # 풀 전수 소진분은 저장(정직 기록)
        sqrt_band = next(b for b in report["bands"] if b["name"] == "sqrt")
        assert sqrt_band["failure_reasons"]  # 조용한 실패 금지 — 사유 존재


class TestCalculusBand:
    def test_default_run_includes_calc_bands(self) -> None:
        # 기본 실행 = quad 4 + calc 5 + exp·log 2 + 수열·삼각 7밴드 = 총 18밴드 — 총 620.
        report = run_corpus_batch(out_path=Path("/nonexistent/x.jsonl"), write=False)
        names = [b.name for b in report.bands]
        assert names == [
            "short",
            "mc",
            "sqrt",
            "sqrt_mc",
            "calc-extremum",
            "calc-tangent",
            "calc-value",
            "calc-value-mc",
            "calc-extremum-irr",
            "exp",
            "log",
            "arith",
            "geo",
            "trig",
            "arith-sum",
            "geo-sum",
            "trig-eq",
            "seq-inductive",
        ]
        for band_name in ("calc-extremum", "calc-tangent", "calc-value"):
            band = next(b for b in report.bands if b.name == band_name)
            assert (band.requested, band.stored) == (40, 40)
        stored = dict((b.name, b.stored) for b in report.bands)
        assert stored["calc-value-mc"] == 30
        assert stored["calc-extremum-irr"] == 30
        assert stored["exp"] == 25
        assert stored["log"] == 20
        assert stored["arith"] == 60
        assert stored["geo"] == 30
        assert stored["trig"] == 13
        assert stored["arith-sum"] == 45
        assert stored["geo-sum"] == 20
        assert stored["trig-eq"] == 12
        assert stored["seq-inductive"] == 30
        assert report.total_stored == 620 and report.fulfilled

    def test_value_mc_records_have_calculus_metadata(self, tmp_path: Path) -> None:
        # calc-value-mc 밴드 산출물 — 극대·극소 태깅·객관식·4지선다·오답 오개념 2종 태깅.
        out = tmp_path / "problems.jsonl"
        run_corpus_batch(
            out_path=out,
            short_n=0,
            mc_n=0,
            sqrt_n=0,
            sqrt_mc_n=0,
            calc_extremum_n=0,
            calc_tangent_n=0,
            calc_value_n=0,
            calc_value_mc_n=12,
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
        records = load_problem_bank_records(out)
        assert len(records) == 12
        for record in records:
            problem = record.problem
            assert problem.unit_codes == ["CALC-EXTREMUM-MC"]
            assert problem.achievement_standard_codes == ["[12미적Ⅰ-02-07]"]
            assert [t.concept_src_id for t in record.concept_tags] == ["H:12미적Ⅰ02-07"]
            assert problem.question_format == "객관식"
            assert problem.choices is not None and len(problem.choices) == 4
            assert problem.answer in problem.choices
            assert problem.distractor_map is not None and len(problem.distractor_map) == 3
            assert {e.misconception_id for e in problem.distractor_map} == {
                "extremum-max-min-confused",
                "extremum-value-vs-point-confused",
            }
            for entry in problem.distractor_map:
                assert entry.misconception_id in CATALOG_BY_ID

    def test_sequence_trig_bands_metadata(self, tmp_path: Path) -> None:
        # 수열·삼각 밴드 산출물 — 단원(unit_code)·성취기준·개념 태깅·단답형·유일해 검증.
        out = tmp_path / "problems.jsonl"
        run_corpus_batch(
            out_path=out,
            short_n=0,
            mc_n=0,
            sqrt_n=0,
            sqrt_mc_n=0,
            calc_extremum_n=0,
            calc_tangent_n=0,
            calc_value_n=0,
            calc_value_mc_n=0,
            calc_extremum_irr_n=0,
            exp_n=0,
            log_n=0,
            arith_n=8,
            geo_n=6,
            trig_n=5,
            arith_sum_n=0,
            geo_sum_n=0,
            trig_eq_n=0,
            seq_inductive_n=0,
            write=True,
        )
        records = load_problem_bank_records(out)
        by_unit = {r.problem.unit_codes[0]: r for r in records}
        assert set(by_unit) == {"ARITH-SEQ", "GEO-SEQ", "TRIG-VAL"}
        expect = {
            "ARITH-SEQ": ("[12대수03-02]", "H:12대수03-02"),
            "GEO-SEQ": ("[12대수03-03]", "H:12대수03-03"),
            "TRIG-VAL": ("[12대수02-02]", "H:12대수02-02"),
        }
        for unit, (code, concept) in expect.items():
            record = by_unit[unit]
            assert record.problem.achievement_standard_codes == [code]
            assert record.problem.question_format == "단답형"
            assert record.verify.answer_selection == "unique"
            assert [t.concept_src_id for t in record.concept_tags if t.role == "PRIMARY"] == [
                concept
            ]

    def test_sum_and_trig_eq_bands_metadata(self, tmp_path: Path) -> None:
        # 수열합·삼각방정식 밴드 산출물 — 단원(unit_code)·성취기준·개념·정답 형식 봉인.
        #   등차합(ARITH-SUM)·등비합(GEO-SUM)은 유일해(unique)·자연수 답, 삼각방정식(TRIG-EQ)은
        #   근 선택(smallest/largest)·자연수 각 답. 삼각방정식은 답에 sqrt가 없어(정수 각)
        #   무리근 밴드 sqrt 필터에 혼입되지 않는다(품질 봉인과 정합).
        out = tmp_path / "problems.jsonl"
        run_corpus_batch(
            out_path=out,
            short_n=0,
            mc_n=0,
            sqrt_n=0,
            sqrt_mc_n=0,
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
            arith_sum_n=10,
            geo_sum_n=8,
            trig_eq_n=6,
            seq_inductive_n=0,
            write=True,
        )
        records = load_problem_bank_records(out)
        by_unit: dict[str, list[ProblemBankRecord]] = {}
        for record in records:
            by_unit.setdefault(record.problem.unit_codes[0], []).append(record)
        assert set(by_unit) == {"ARITH-SUM", "GEO-SUM", "TRIG-EQ"}
        expect = {
            "ARITH-SUM": ("[12대수03-02]", "H:12대수03-02"),
            "GEO-SUM": ("[12대수03-03]", "H:12대수03-03"),
            "TRIG-EQ": ("[12대수02-02]", "H:12대수02-02"),
        }
        for unit, (code, concept) in expect.items():
            for record in by_unit[unit]:
                assert record.problem.achievement_standard_codes == [code]
                assert record.problem.question_format == "단답형"
                assert record.problem.answer_format == "자연수"
                assert [t.concept_src_id for t in record.concept_tags if t.role == "PRIMARY"] == [
                    concept
                ]
        # 수열합은 유일해·삼각방정식은 근 선택(smallest/largest).
        for record in by_unit["ARITH-SUM"] + by_unit["GEO-SUM"]:
            assert record.verify.answer_selection == "unique"
        for record in by_unit["TRIG-EQ"]:
            assert record.verify.answer_selection in {"smallest", "largest"}
            assert "sqrt(" not in (record.problem.answer or "")  # 정수 각 — sqrt 필터 미혼입

    def test_value_records_have_calculus_metadata(self, tmp_path: Path) -> None:
        # calc-value 밴드 산출물 — 극대·극소 단원/성취기준/개념 태깅(극값 x좌표와 동일)·단답형·
        # 극댓값/극솟값 발문. 정답은 값이라 x좌표 대역을 벗어날 수 있다.
        out = tmp_path / "problems.jsonl"
        run_corpus_batch(
            out_path=out,
            short_n=0,
            mc_n=0,
            sqrt_n=0,
            sqrt_mc_n=0,
            calc_extremum_n=0,
            calc_tangent_n=0,
            calc_value_n=12,
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
        records = load_problem_bank_records(out)
        assert len(records) == 12
        for record in records:
            assert record.problem.unit_codes == ["CALC-EXTREMUM-VALUE"]
            assert record.problem.achievement_standard_codes == ["[12미적Ⅰ-02-07]"]
            assert [t.concept_src_id for t in record.concept_tags] == ["H:12미적Ⅰ02-07"]
            assert record.problem.question_format == "단답형"
            q = record.problem.question_text
            assert "극댓값" in q or "극솟값" in q

    def test_tangent_records_have_calculus_metadata(self, tmp_path: Path) -> None:
        # calc-tangent 밴드 산출물 — 미분계수 단원/성취기준/개념 태깅·단답형·접선 기울기 발문.
        out = tmp_path / "problems.jsonl"
        run_corpus_batch(
            out_path=out,
            short_n=0,
            mc_n=0,
            sqrt_n=0,
            sqrt_mc_n=0,
            calc_extremum_n=0,
            calc_tangent_n=12,
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
        records = load_problem_bank_records(out)
        assert len(records) == 12
        for record in records:
            assert record.problem.unit_codes == ["CALC-TANGENT"]
            assert record.problem.achievement_standard_codes == ["[12미적Ⅰ-02-01]"]
            assert [t.concept_src_id for t in record.concept_tags] == ["H:12미적Ⅰ02-01"]
            assert record.problem.question_format == "단답형"
            assert "접선의 기울기" in record.problem.question_text

    def test_calc_records_have_calculus_metadata(self, tmp_path: Path) -> None:
        # calc 밴드 산출물 — 미적분 단원/성취기준/개념 태깅·단답형(quad와 분리 확인).
        out = tmp_path / "problems.jsonl"
        run_corpus_batch(
            out_path=out,
            short_n=0,
            mc_n=0,
            sqrt_n=0,
            sqrt_mc_n=0,
            calc_extremum_n=12,
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
        records = load_problem_bank_records(out)
        assert len(records) == 12
        for record in records:
            assert record.problem.unit_codes == ["CALC-EXTREMUM"]
            assert record.problem.achievement_standard_codes == ["[12미적Ⅰ-02-07]"]
            assert [t.concept_src_id for t in record.concept_tags] == ["H:12미적Ⅰ02-07"]
            assert record.problem.question_format == "단답형"
            assert (
                "삼차함수" in record.problem.question_text or "함수" in record.problem.question_text
            )

    def test_irrational_extremum_records_have_calculus_metadata(self, tmp_path: Path) -> None:
        # calc-extremum-irr 밴드 산출물 — 극대·극소 성취기준/개념 태깅·단답형·답만 무리수(√)·
        # 삼차식은 정수계수(발문에 √ 없음)·오개념 태그 0(단답형·pending 게이트 미발생).
        out = tmp_path / "problems.jsonl"
        run_corpus_batch(
            out_path=out,
            short_n=0,
            mc_n=0,
            sqrt_n=0,
            sqrt_mc_n=0,
            calc_extremum_n=0,
            calc_tangent_n=0,
            calc_value_n=0,
            calc_value_mc_n=0,
            calc_extremum_irr_n=12,
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
        records = load_problem_bank_records(out)
        assert len(records) == 12
        for record in records:
            assert record.problem.unit_codes == ["CALC-EXTREMUM-IRR"]
            assert record.problem.achievement_standard_codes == ["[12미적Ⅰ-02-07]"]
            assert [t.concept_src_id for t in record.concept_tags] == ["H:12미적Ⅰ02-07"]
            assert record.problem.question_format == "단답형"
            assert record.problem.distractor_map is None  # 오개념 주입 0
            assert "sqrt" in record.problem.answer  # 임계점만 무리수
            assert "sqrt" not in record.problem.question_text  # 삼차식은 정수계수

    def test_calc_band_difficulty_varies(self, tmp_path: Path) -> None:
        # 난이도 변별(균일 회귀 차단) — calc 밴드도 rule-based로 여러 값·미적분 대역(3.0~5.0).
        out = tmp_path / "problems.jsonl"
        run_corpus_batch(
            out_path=out,
            short_n=0,
            mc_n=0,
            sqrt_n=0,
            sqrt_mc_n=0,
            calc_extremum_n=30,
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
        diffs = {r.problem.difficulty_overall for r in load_problem_bank_records(out)}
        assert len(diffs) >= 2
        assert all(d is not None and 3.0 <= d <= 5.0 for d in diffs)


class TestAlgebraBand:
    def test_exp_log_bands_metadata(self, tmp_path: Path) -> None:
        # 지수·로그 밴드 산출물 — 대수 개념(H:12대수01-08)·단원(EXP-EQ/LOG-EQ)·비다항 conditions.
        out = tmp_path / "problems.jsonl"
        report = run_corpus_batch(
            out_path=out,
            short_n=0,
            mc_n=0,
            sqrt_n=0,
            sqrt_mc_n=0,
            calc_extremum_n=0,
            calc_tangent_n=0,
            calc_value_n=0,
            calc_value_mc_n=0,
            calc_extremum_irr_n=0,
            exp_n=8,
            log_n=6,
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
        # quad 밴드는 n=0이어도 리포트에 남으므로(요청 0·저장 0), exp·log 저장분만 확인.
        stored = {b.name: b.stored for b in report.bands}
        assert stored["exp"] == 8 and stored["log"] == 6
        records = load_problem_bank_records(out)
        assert len(records) == 14
        for record in records:
            assert [t.concept_src_id for t in record.concept_tags] == ["H:12대수01-08"]
            assert record.problem.unit_codes[0] in {"EXP-EQ", "LOG-EQ"}
            assert record.verify.answer_selection == "unique"
        # conditions는 비다항(지수·로그) — b**x 또는 log( 포함.
        assert any("**x" in r.verify.conditions for r in records)  # 지수
        assert any("log(" in r.verify.conditions for r in records)  # 로그


class TestInductiveSequenceBand:
    def _run(self, out: Path, n: int) -> None:
        run_corpus_batch(
            out_path=out,
            short_n=0,
            mc_n=0,
            sqrt_n=0,
            sqrt_mc_n=0,
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
            seq_inductive_n=n,
            write=True,
        )

    def test_inductive_band_metadata_and_signatures(self, tmp_path: Path) -> None:
        # seq-inductive 밴드 산출물(S2-06) — 귀납적 정의 단원/성취기준/개념 태깅·단답형·조건 나열
        # 메타·**시그니처 2종 태깅**(sink 기록 직전 태거 적용·태거 단일 권위)·유일해 검증.
        out = tmp_path / "problems.jsonl"
        self._run(out, 10)
        records = load_problem_bank_records(out)
        assert len(records) == 10
        for record in records:
            problem = record.problem
            assert problem.slug is not None and problem.slug.startswith("wm-indseq-")
            assert problem.unit_codes == ["IND-SEQ"]
            assert problem.achievement_standard_codes == ["[12대수03-06]"]
            assert [t.concept_src_id for t in record.concept_tags] == ["H:12대수03-06"]
            assert problem.question_format == "단답형"
            assert problem.answer_format == "자연수"
            assert record.verify.answer_selection == "unique"
            # 조건 나열 메타 — 발문 구조의 사실((가)(나) 2건).
            assert problem.has_condition_list is True
            assert problem.condition_count == 2
            assert len(problem.conditions_parsed) == 2
            assert "(가)" in problem.question_text and "(나)" in problem.question_text
            # 시그니처 태깅 — 조건 나열(T1)·귀납 점화식(T2) 2종(enum 값 사전순).
            assert problem.signature_patterns == ["CONDITION_LIST", "INDUCTIVE_SEQUENCE"]
        # 등차 점화·등비 점화 변형이 함께 실린다(결정론 인터리브 봉인 — 운 배제).
        assert any("aₙ + " in r.problem.question_text for r in records)
        assert any("·aₙ" in r.problem.question_text for r in records)

    def test_inductive_band_rerun_byte_identical(self, tmp_path: Path) -> None:
        # 신규 밴드 포함 재실행 바이트 동일 — 태거 적용 후에도 결정론 봉인 유지.
        a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
        self._run(a, 8)
        self._run(b, 8)
        assert a.read_bytes() == b.read_bytes()

    def test_existing_bands_signatures_stay_empty(self, tmp_path: Path) -> None:
        # 비날조 원칙 — 기존 문제군(규칙 미해당)은 태거 적용 후에도 signature_patterns가 빈 배열.
        out = tmp_path / "problems.jsonl"
        run_corpus_batch(
            out_path=out,
            short_n=4,
            mc_n=2,
            sqrt_n=0,
            sqrt_mc_n=0,
            calc_extremum_n=2,
            calc_tangent_n=0,
            calc_value_n=0,
            calc_value_mc_n=0,
            calc_extremum_irr_n=0,
            exp_n=2,
            log_n=0,
            arith_n=2,
            geo_n=0,
            trig_n=0,
            arith_sum_n=0,
            geo_sum_n=0,
            trig_eq_n=0,
            seq_inductive_n=0,
            write=True,
        )
        for record in load_problem_bank_records(out):
            assert record.problem.signature_patterns == []
