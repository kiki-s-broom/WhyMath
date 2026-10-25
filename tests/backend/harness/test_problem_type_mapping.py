"""생성기 identity → problem_type_id 매핑표(S3-27·PB-07) — 골든 분포·계보 분류·변별력·
만료 계약 테스트.

**변별력**(CLAUDE.md "변별력 없는 검증 스텝 금지"): `TestMutationDetection`이 매핑표 항목 1개를
일부러 틀리게 바꾼 뒤 골든 분포 대조가 *실제로* 어긋남을 직접 실행해 증명한다(오매핑 주입 → 검사
실패, 복원 → 검사 통과 — 두 상태 모두 이 테스트 안에서 실행·확인한다).

실제 저장소의 코퍼스 파일(`data/corpus/problem_bank_*/problems.jsonl` — 2026-07-30 S3-27 백필
+ 2026-08-11 PB-07 rephrased 계보 백필 결과물)을 직접 읽어 전수 대조한다 — 합성 fixture가
아니라 *실제 산출물*이 골든 값과 일치하는지 보는 것이 이 매핑표의 유일한 존재 이유이기 때문이다.

**전수 귀속 계약**(CONT-09·`TestCorpusSeatContract`): `data/corpus/problem_bank*` 디렉터리 전부가
정확히 한 좌석(직접 분류·계보·제외·자가 태깅)에 앉아야 한다 — S3-27 이후 추가된 코퍼스 30종
11,396문이 어느 좌석에도 없어 태깅 계약 밖에 방치됐던 사고의 재발 차단. 변별력은 코퍼스 1종을
좌석에서 빼 RED를 실측하고 되돌려 GREEN을 실측하는 것으로 증명한다.

**제외 만료 계약**(PB-07·`TestExclusionExpiryContract`): `EXCLUDED_CORPORA` 좌석의 각 항목이
①실재하는 backlog 태스크를 참조하는지 ②참조 태스크가 done인데 항목이 방치되지 않았는지를
상시 대조한다 — `ops/provenance_audit`의 `TestGrandfatherExpiryContract`(ARCH-25)와 동형.
"""

from __future__ import annotations

import ast
import json
import re
from collections import Counter
from pathlib import Path

import pytest
import yaml

from whymath_backend.harness import problem_type_mapping as ptm
from whymath_backend.schema.enums import RelationType

# tests/backend/harness/test_x.py → parents[3] = repo 루트(harness→backend→tests→root).
_REPO_ROOT = Path(__file__).resolve().parents[3]
_CORPUS_ROOT = _REPO_ROOT / "data" / "corpus"
_PROBLEM_TYPES_PATH = _CORPUS_ROOT / "problem_type_graph_v1" / "problem_types.jsonl"
# 코퍼스 건수는 손으로 박지 않고 단일 원천의 기계용 사본에서 읽는다(OPS-154).
# 원본이 바뀌면 `python3 scripts/analysis/corpus_facts.py sync`가 이 파일을 갱신한다.
_FACTS = json.loads(
    (_REPO_ROOT / "docs" / "data" / "corpus_facts.json").read_text(encoding="utf-8")
)


def _bank_total(corpus: str) -> int:
    """은행 폴더 이름(`problem_bank_<x>`) → 사실 `problem_bank.<x>`(그 은행의 전체 문항 수)."""
    return _FACTS[f"problem_bank.{corpus.removeprefix('problem_bank_')}"]


# 골든 분포(2026-07-30 S3-27 백필 실측 — `harness/problem_type_backfill.py` 산출물과 정합).
# 이 상수가 어긋나면 매핑표가 바뀌었다는 뜻이다 — 의도적 변경이면 이 상수도 함께 갱신할 것.
_GOLDEN_CORPUS_TYPE_TOTALS: dict[str, dict[str, int]] = {
    ptm.CORPUS_V1: {
        ptm.PTYPE_SOLVE_FOR_UNKNOWN: 2,
        ptm.PTYPE_DETERMINE_COEFFICIENT: 1,
        ptm.PTYPE_COUNT_SOLUTIONS: 1,
    },
    # QUAD-EQ(184)+CALC-TANGENT(40)+EXP-EQ(25)+LOG-EQ(20)+TRIG-EQ(12)=281(solve) ·
    # CALC-EXTREMUM(40)+VALUE(40)+MC(30)+IRR(30)=140(optimize) ·
    # ARITH-SEQ(60)+GEO-SEQ(30)+ARITH-SUM(45)+GEO-SUM(20)+TRIG-VAL(13)=168(evaluate) · IND-SEQ=30.
    # (QUAD-EQ 185→184: 2026-08-11 QUAL-02가 `wm-skel-92cd1ba2bbf5`를 실중복 은퇴 —
    #  docs/data/problem_duplicate_disposition_2026-08.md)
    ptm.CORPUS_GENERATED_V0: {
        ptm.PTYPE_SOLVE_FOR_UNKNOWN: 281,
        ptm.PTYPE_OPTIMIZE_EXTREMUM: 140,
        ptm.PTYPE_EVALUATE_EXPRESSION: 168,
        ptm.PTYPE_GENERALIZE_PATTERN: 30,
    },
    ptm.CORPUS_CONCEPTUAL_V0: {
        ptm.PTYPE_COUNT_SOLUTIONS: 96,  # 4밴드 × 24
        ptm.PTYPE_VERIFY_CLAIM: 264,  # 11밴드 × 24
    },
    ptm.CORPUS_KILLER_V0: {
        ptm.PTYPE_EVALUATE_EXPRESSION: _bank_total(ptm.CORPUS_KILLER_V0),  # 단일 유형 = 은행 전량
    },
    # 42밴드×24=1008(evaluate) · transpose-no-sign-change=24(solve) ·
    # combination-no-denominator·same-item-permutation-no-divide=2밴드×24=48(enumerate).
    ptm.CORPUS_MISCONCEPTION_MC_V0: {
        ptm.PTYPE_EVALUATE_EXPRESSION: 1008,
        ptm.PTYPE_SOLVE_FOR_UNKNOWN: 24,
        ptm.PTYPE_ENUMERATE_CASES: 48,
    },
    ptm.CORPUS_PROBABILITY_FINITE_V0: {
        ptm.PTYPE_EVALUATE_EXPRESSION: 26,
        ptm.PTYPE_ENUMERATE_CASES: 8,
    },
}

# 계보 분류 골든(2026-08-11 PB-07 실측 — 부모는 전건 generated_v0):
# QUAD-EQ(146)+CALC-TANGENT(40)+EXP-EQ(21)+LOG-EQ(14)=221(solve) ·
# CALC-EXTREMUM(37)+CALC-EXTREMUM-VALUE(34)+CALC-EXTREMUM-MC(26)=97(optimize) ·
# ARITH-SEQ(60)+GEO-SEQ(30)+TRIG-VAL(13)=103(evaluate).
_GOLDEN_REPHRASED_TYPE_TOTALS: dict[str, int] = {
    ptm.PTYPE_SOLVE_FOR_UNKNOWN: 221,
    ptm.PTYPE_OPTIMIZE_EXTREMUM: 97,
    ptm.PTYPE_EVALUATE_EXPRESSION: 103,
}

# CONT-09 골든(2026-10-12 실측) — `unit_codes` 표로 직접 분류하는 30종의 유형별 총량.
# 각 값은 코퍼스의 `unit_codes`별 문항 수(실코퍼스 순회)에서 손으로 합산했다:
#   evaluate 대다수 · 나머지 4군 = enumerate(REPEATED-COMBINATION 56·SUM-PRODUCT-PRINCIPLE 120·
#   PERMUTATION 40) · determine-coefficient(LINE-EQUATION 200) · condition-satisfaction
#   (LINEAR-INEQUALITY-SYSTEM 600·QUAD-INEQ-BOUNDARY 200) · transform-expression
#   (POLYNOMIAL-FACTORING 600).
_E = ptm.PTYPE_EVALUATE_EXPRESSION
# 단일 유형 은행 — 그 유형의 총량 = 은행 전체 문항 수이므로 값은 사실 파일에서 읽는다.
_UNIT_TABLE_SINGLE_TYPE: dict[str, str] = {
    "problem_bank_binomial_distribution_v0": _E,
    "problem_bank_calculus1_integral_v0": _E,
    "problem_bank_calculus2_trig_integral_v0": _E,
    "problem_bank_complex_number_arithmetic_v0": _E,
    "problem_bank_conic_section_focus_v0": _E,
    "problem_bank_discrete_ev_v0": _E,
    "problem_bank_elementary_area_measure_v0": _E,
    "problem_bank_elementary_division_remainder_v0": _E,
    "problem_bank_elementary_gcd_lcm_v0": _E,
    "problem_bank_elementary_rounding_v0": _E,
    "problem_bank_elementary_v0": _E,
    "problem_bank_elementary_volume_measure_v0": _E,
    "problem_bank_highschool_quotient_rule_v0": _E,
    "problem_bank_linear_inequality_system_v0": ptm.PTYPE_CONDITION_SATISFACTION,
    "problem_bank_matrix_ops_v0": _E,
    "problem_bank_measurement_unit_conversion_v0": _E,
    "problem_bank_middle_function_v0": _E,
    "problem_bank_permutation_combination_v0": ptm.PTYPE_ENUMERATE_CASES,
    "problem_bank_polynomial_arithmetic_v0": _E,
    "problem_bank_polynomial_factoring_v0": ptm.PTYPE_TRANSFORM_EXPRESSION,
    "problem_bank_probability_law_v0": _E,
    "problem_bank_quad_ineq_v0": ptm.PTYPE_CONDITION_SATISFACTION,
    "problem_bank_radian_conversion_v0": _E,
    "problem_bank_sample_mean_distribution_v0": _E,
    "problem_bank_sequence_sigma_v0": _E,
    "problem_bank_university_calc1_chain_quotient_v0": _E,
    "problem_bank_university_calc1_v0": _E,
    "problem_bank_vector_operations_v0": _E,
}
# 복수 유형 은행 — 유형 분할은 실측 골든이다(사실 파일에 없다).
_UNIT_TABLE_SPLIT_TYPE_TOTALS: dict[str, dict[str, int]] = {
    "problem_bank_combination_binomial_v0": {ptm.PTYPE_ENUMERATE_CASES: 56, _E: 65},
    "problem_bank_coordinate_geometry_v0": {_E: 200, ptm.PTYPE_DETERMINE_COEFFICIENT: 200},
}
_GOLDEN_UNIT_TABLE_TYPE_TOTALS: dict[str, dict[str, int]] = dict(
    sorted(
        {
            **{name: {ptype: _bank_total(name)} for name, ptype in _UNIT_TABLE_SINGLE_TYPE.items()},
            **_UNIT_TABLE_SPLIT_TYPE_TOTALS,
        }.items()
    )
)
# CONT-09 — 미태깅이던 문항 수 = 표 은행 30종의 전체 문항 수 합(사실 파일 기준).
_GOLDEN_UNIT_TABLE_TOTAL = sum(_bank_total(name) for name in _GOLDEN_UNIT_TABLE_TYPE_TOTALS)

# 직접 6종 + 계보(rephrased_v0) (S3-27·PB-07) + CONT-09 `unit_codes` 표 30종.
# p3_calculus1_diff_v0·p3_fill_v0(자가 태깅)는 `classify_record` 소관이 아니라 이 합계에 없다.
_GOLDEN_DIRECT_TOTAL = sum(
    _bank_total(name)
    for name in (
        ptm.CORPUS_V1,
        ptm.CORPUS_GENERATED_V0,
        ptm.CORPUS_CONCEPTUAL_V0,
        ptm.CORPUS_KILLER_V0,
        ptm.CORPUS_MISCONCEPTION_MC_V0,
        ptm.CORPUS_PROBABILITY_FINITE_V0,
    )
)
_GOLDEN_LINEAGE_TOTAL = _bank_total(ptm.CORPUS_REPHRASED_V0)  # rephrased_v0 총량
_GOLDEN_TOTAL_TAGGED = _GOLDEN_DIRECT_TOTAL + _GOLDEN_LINEAGE_TOTAL + _GOLDEN_UNIT_TABLE_TOTAL


def _load_corpus_lines(name: str) -> list[dict[str, object]]:
    path = _CORPUS_ROOT / name / "problems.jsonl"
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _distribution_for(name: str) -> Counter[str]:
    """코퍼스 1종의 실제 레코드에 `classify_record`를 적용한 유형별 분포(빈 리스트는 무시)."""
    counts: Counter[str] = Counter()
    for record in _load_corpus_lines(name):
        for ptype in ptm.classify_record(name, record):
            counts[ptype] += 1
    return counts


def _parent_type_index() -> dict[str, list[str]]:
    """직접 분류 6종의 slug → 유도 유형 색인 — 계보 분류 입력
    (`problem_type_backfill._build_parent_type_index`와 동형·실 코퍼스는 slug 중복 0건)."""
    index: dict[str, list[str]] = {}
    for name in ptm.TARGET_CORPORA:
        for record in _load_corpus_lines(name):
            slug = record.get("slug")
            assert isinstance(slug, str)
            assert slug not in index, f"slug 중복: {slug} — 계보 조인 전제 붕괴"
            index[slug] = ptm.classify_record(name, record)
    return index


def _lineage_distribution_for(name: str) -> Counter[str]:
    """계보 코퍼스 1종의 실제 레코드에 `classify_rephrased_record`를 적용한 유형별 분포."""
    index = _parent_type_index()
    counts: Counter[str] = Counter()
    for record in _load_corpus_lines(name):
        for ptype in ptm.classify_rephrased_record(record, index):
            counts[ptype] += 1
    return counts


class TestGoldenDistribution:
    """매핑표를 실제 코퍼스 전량에 적용한 결과가 골든 값과 정확히 일치하는지 — 정상 매핑 대조."""

    @pytest.mark.parametrize("corpus_name", list(_GOLDEN_CORPUS_TYPE_TOTALS))
    def test_corpus_distribution_matches_golden(self, corpus_name: str) -> None:
        assert dict(_distribution_for(corpus_name)) == _GOLDEN_CORPUS_TYPE_TOTALS[corpus_name]

    @pytest.mark.parametrize("corpus_name", list(_GOLDEN_UNIT_TABLE_TYPE_TOTALS))
    def test_unit_table_corpus_distribution_matches_golden(self, corpus_name: str) -> None:
        # CONT-09: 30종 각각의 유형별 분포가 손 합산 골든과 정확히 일치.
        assert dict(_distribution_for(corpus_name)) == _GOLDEN_UNIT_TABLE_TYPE_TOTALS[corpus_name]

    def test_unit_table_golden_covers_exactly_the_unit_table_corpora(self) -> None:
        # 골든 키 집합 == 표 코퍼스 집합 — 표에 코퍼스를 넣고 골든을 빠뜨리거나 그 반대를 막는다.
        assert set(_GOLDEN_UNIT_TABLE_TYPE_TOTALS) == set(ptm.UNIT_CODE_TABLE_CORPORA)
        assert sum(sum(v.values()) for v in _GOLDEN_UNIT_TABLE_TYPE_TOTALS.values()) == (
            _GOLDEN_UNIT_TABLE_TOTAL
        )

    def test_rephrased_distribution_matches_golden(self) -> None:
        # PB-07 계보 백필 골든 — 부모(generated_v0) 유형 승계 결과가 실측 골든과 정확히 일치.
        assert dict(_lineage_distribution_for(ptm.CORPUS_REPHRASED_V0)) == (
            _GOLDEN_REPHRASED_TYPE_TOTALS
        )

    def test_total_tagged_matches_golden(self) -> None:
        # 직접 분류 36종(classify_record) + 계보 1종(classify_rephrased_record) = 14,034.
        direct = sum(
            sum(dist.values()) for name in ptm.TARGET_CORPORA for dist in [_distribution_for(name)]
        )
        lineage = sum(
            sum(dist.values())
            for name in ptm.LINEAGE_CORPORA
            for dist in [_lineage_distribution_for(name)]
        )
        assert direct + lineage == _GOLDEN_TOTAL_TAGGED

    def test_rephrased_v0_is_lineage_target_not_excluded(self) -> None:
        # PB-07: rephrased는 직접 분류 대상이 아니라 *계보 분류* 대상이며, 더 이상 제외가 아니다
        # (구 사유 "S4-14 미착지" 소멸 — problem_bank_gap_review_r3.md §3 G2).
        assert ptm.CORPUS_REPHRASED_V0 not in ptm.TARGET_CORPORA
        assert ptm.LINEAGE_CORPORA == (ptm.CORPUS_REPHRASED_V0,)
        assert ptm.EXCLUDED_CORPORA == {}  # 제외 좌석은 비었다 — 만료 계약이 재등재를 규율.
        assert len(_load_corpus_lines(ptm.CORPUS_REPHRASED_V0)) == _GOLDEN_LINEAGE_TOTAL

    def test_classify_record_returns_empty_for_lineage_corpus(self) -> None:
        # 계보 코퍼스는 단일 레코드 서명으로 분류 불가 — `classify_record`는 침묵 오분류 대신
        # 빈 리스트로 정직하게 미분류를 드러낸다(분류는 `classify_rephrased_record` 소관).
        sample = _load_corpus_lines(ptm.CORPUS_REPHRASED_V0)[0]
        assert ptm.classify_record(ptm.CORPUS_REPHRASED_V0, sample) == []


class TestMappingIntegrity:
    """매핑표 값의 구조적 정합 — 정본 카탈로그(problem_type_graph_v1)와의 대조."""

    def test_all_mapped_type_ids_exist_in_real_catalog(self) -> None:
        # 이 모듈의 PTYPE_* 상수 값이 정본 problem_types.jsonl에 실재하는지 교차 확인
        # (오탈자·정본 드리프트 방지 — 모듈 docstring의 "재정의 아님" 전제를 기계로 검증).
        catalog_ids = {
            json.loads(line)["problem_type_id"]
            for line in _PROBLEM_TYPES_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
        assert catalog_ids == ptm.ALL_PROBLEM_TYPE_IDS

    def test_no_untagged_records_in_target_corpora(self) -> None:
        # acceptance③: 직접 분류 대상 36개 코퍼스는 전량 태깅됨(0건 미태깅) — 실측 확인.
        for name in ptm.TARGET_CORPORA:
            records = _load_corpus_lines(name)
            untagged = sum(1 for r in records if not ptm.classify_record(name, r))
            assert untagged == 0, f"{name}에 미태깅 {untagged}건 — 매핑표 공백"

    def test_no_untagged_records_in_lineage_corpora(self) -> None:
        # PB-07 acceptance①·②: 계보 코퍼스도 전량 태깅(계보 추적 성립 421/421 — 추적 불가
        # 잔여 0건을 저장소 차원에서 동결한다. 잔여가 생기면 이 테스트가 건수를 드러낸다).
        index = _parent_type_index()
        for name in ptm.LINEAGE_CORPORA:
            records = _load_corpus_lines(name)
            untagged = sum(1 for r in records if not ptm.classify_rephrased_record(r, index))
            assert untagged == 0, f"{name}에 계보 추적 불가(미태깅) {untagged}건"

    def test_stored_codes_match_derivation_in_all_target_corpora(self) -> None:
        # 저장된 problem_type_codes(백필 산출물)가 유도 값과 전건 일치 — 리뷰 지적(CONT-09 PR):
        # 위 테스트들은 `classify_record` **유도**만 대조해 저장분을 못 본다. 배치 CLI가 코퍼스를
        # 재생성하면(`problem_type_codes=[]` 기본값) 저장 태그가 조용히 사라지는데 그때 이 테스트만
        # RED가 된다. 실패 시 어느 코퍼스에 몇 건이 어긋났는지 드러낸다.
        mismatched: dict[str, int] = {}
        for name in ptm.TARGET_CORPORA:
            bad = sum(
                1
                for record in _load_corpus_lines(name)
                if record.get("problem_type_codes") != ptm.classify_record(name, record)
            )
            if bad:
                mismatched[name] = bad
        assert (
            mismatched == {}
        ), f"저장 태그가 유도값과 어긋난 코퍼스: {mismatched} — 백필 재실행 필요"

    def test_stored_rephrased_codes_match_lineage_derivation(self) -> None:
        # 저장된 problem_type_codes(PB-07 백필 산출물)가 계보 유도 값과 전건 일치 — 멱등 계약의
        # 저장소 대조판(백필 2회 실행 바이트 동일의 정적 등가물).
        index = _parent_type_index()
        for record in _load_corpus_lines(ptm.CORPUS_REPHRASED_V0):
            derived = ptm.classify_rephrased_record(record, index)
            assert record.get("problem_type_codes") == derived, record.get("slug")


class TestMutationDetection:
    """변별력 증명(acceptance⑤) — 매핑표 항목 1개를 오염시키면 골든 대조가 실제로 실패한다.

    한 테스트 안에서 ①오염 상태(불일치 확인) ②원복 상태(일치 확인) 둘 다 실행한다 —
    monkeypatch가 테스트 종료 시 자동 원복하므로 그 전에 명시적으로 두 상태를 모두 관측한다.
    """

    def test_mutated_generated_v0_entry_breaks_golden_check(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        golden = _GOLDEN_CORPUS_TYPE_TOTALS[ptm.CORPUS_GENERATED_V0]

        # 오염 전 — 정상 매핑은 골든과 일치해야 한다(대조군).
        assert dict(_distribution_for(ptm.CORPUS_GENERATED_V0)) == golden

        # 오염 — QUAD-EQ(184건 — QUAL-02 은퇴 1건 반영) 매핑을 일부러 틀린 유형으로 바꾼다.
        corrupted = dict(ptm._GENERATED_V0_UNIT_TO_TYPE)
        corrupted[("QUAD-EQ",)] = ptm.PTYPE_SKETCH_GRAPH  # 명백히 틀린 유형(방정식 풀이가 아님).
        monkeypatch.setattr(ptm, "_GENERATED_V0_UNIT_TO_TYPE", corrupted)

        mutated_distribution = dict(_distribution_for(ptm.CORPUS_GENERATED_V0))
        # 이것이 변별력의 핵심 단언 — 오매핑 주입 시 골든과 실제로 달라져야 한다(실패를 실패로
        # 잡아낸다). 이 단언 자체가 통과하지 못하면(=오염 전후가 같으면) 골든 체크가 무의미하다는
        # 뜻이라 이 테스트가 실패해야 정상이다.
        assert mutated_distribution != golden
        assert mutated_distribution[ptm.PTYPE_SKETCH_GRAPH] == 184
        assert (
            mutated_distribution[ptm.PTYPE_SOLVE_FOR_UNKNOWN]
            == golden[ptm.PTYPE_SOLVE_FOR_UNKNOWN] - 184
        )

        # 원복(monkeypatch.undo는 fixture teardown에서도 자동 실행되지만, 같은 테스트 안에서
        # "복원 후 재통과"까지 명시적으로 확인한다 — acceptance⑤가 요구하는 두 상태 모두 실행).
        monkeypatch.undo()
        assert dict(_distribution_for(ptm.CORPUS_GENERATED_V0)) == golden

    def test_mutated_misconception_kebab_entry_breaks_golden_check(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        golden = _GOLDEN_CORPUS_TYPE_TOTALS[ptm.CORPUS_MISCONCEPTION_MC_V0]
        assert dict(_distribution_for(ptm.CORPUS_MISCONCEPTION_MC_V0)) == golden

        corrupted = dict(ptm._MISCONCEPTION_MC_V0_KEBAB_TO_TYPE)
        corrupted["transpose-no-sign-change"] = ptm.PTYPE_EVALUATE_EXPRESSION  # 실제는 방정식 풀이.
        monkeypatch.setattr(ptm, "_MISCONCEPTION_MC_V0_KEBAB_TO_TYPE", corrupted)

        mutated = dict(_distribution_for(ptm.CORPUS_MISCONCEPTION_MC_V0))
        assert mutated != golden
        assert ptm.PTYPE_SOLVE_FOR_UNKNOWN not in mutated  # 24건이 evaluate-expression으로 흡수됨.
        assert mutated[ptm.PTYPE_EVALUATE_EXPRESSION] == golden[ptm.PTYPE_EVALUATE_EXPRESSION] + 24

        monkeypatch.undo()
        assert dict(_distribution_for(ptm.CORPUS_MISCONCEPTION_MC_V0)) == golden


class TestUnitTableIntegrity:
    """CONT-09 `unit_codes` 표의 구조 정합 — 표 키 집합이 실코퍼스의 `unit_codes` 집합과 같아야 한다.

    표에 없는 값은 `classify_record`가 침묵 대신 빈 리스트(미태깅)로 드러내고(전수 태깅 테스트가
    잡는다), 코퍼스에 없는 키는 죽은 항목이다 — 후자는 이 테스트가 잡는다.
    """

    @pytest.mark.parametrize("corpus_name", list(ptm.UNIT_CODE_TABLE_CORPORA))
    def test_table_keys_equal_observed_unit_codes(self, corpus_name: str) -> None:
        observed = {
            tuple(sorted(r["unit_codes"]))  # type: ignore[arg-type]
            for r in _load_corpus_lines(corpus_name)
        }
        assert set(ptm._UNIT_CODE_TABLES[corpus_name]) == observed

    def test_table_corpora_are_all_direct_targets_and_ordered(self) -> None:
        assert set(ptm.UNIT_CODE_TABLE_CORPORA) <= set(ptm.TARGET_CORPORA)
        assert list(ptm.UNIT_CODE_TABLE_CORPORA) == sorted(ptm.UNIT_CODE_TABLE_CORPORA)
        assert len(ptm.TARGET_CORPORA) == len(set(ptm.TARGET_CORPORA))  # 좌석 내 중복 0.

    def test_every_table_value_is_a_real_catalog_type(self) -> None:
        for corpus_name, table in ptm._UNIT_CODE_TABLES.items():
            for unit_codes, ptype in table.items():
                assert ptype in ptm.ALL_PROBLEM_TYPE_IDS, (corpus_name, unit_codes)

    def test_unmapped_unit_code_stays_untagged_not_misclassified(self) -> None:
        # 표에 없는 unit_codes(예: 신규 밴드 추가) → 빈 리스트. 다른 값으로 둔갑하지 않는다.
        record = {"unit_codes": ["NOT-IN-TABLE"], "slug": "x"}
        assert ptm.classify_record("problem_bank_polynomial_arithmetic_v0", record) == []

    def test_mutated_unit_table_entry_breaks_golden_check(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 변별력: POLYNOMIAL-ARITHMETIC(1,500건)을 틀린 유형으로 바꾸면 골든 대조가 실제로 어긋난다.
        name = "problem_bank_polynomial_arithmetic_v0"
        golden = _GOLDEN_UNIT_TABLE_TYPE_TOTALS[name]
        assert dict(_distribution_for(name)) == golden  # 대조군.

        corrupted = {
            **ptm._UNIT_CODE_TABLES,
            name: {("POLYNOMIAL-ARITHMETIC",): ptm.PTYPE_SKETCH_GRAPH},
        }
        monkeypatch.setattr(ptm, "_UNIT_CODE_TABLES", corrupted)
        mutated = dict(_distribution_for(name))
        assert mutated != golden
        assert mutated == {ptm.PTYPE_SKETCH_GRAPH: 1500}

        monkeypatch.undo()
        assert dict(_distribution_for(name)) == golden


class TestCorpusSeatContract:
    """전수 귀속(CONT-09) — 모든 `problem_bank*` 디렉터리가 정확히 한 좌석에 앉는다.

    ``find_corpus_seat_violations``의 세 위반(미귀속·중복·죽은 좌석)과 스캔 0건 실패를 각각
    주입해 RED를 실측하고, 정상 상태에서 GREEN을 실측한다 — 정상 입력의 초록만으로는 보호의 증거가
    아니다(CLAUDE.md "보호 장치를 실패 주입 없이 보호 있음으로 선언 금지").
    """

    @staticmethod
    def _mirror_seats(root: Path) -> None:
        """현재 좌석 전체와 같은 이름의 빈 코퍼스 디렉터리를 `root` 아래 만든다(정상 상태 재현)."""
        for name in ptm._corpus_seats():
            (root / name).mkdir(parents=True)

    def test_seat_glob_equals_coverage_meter_glob(self) -> None:
        # 이 계약이 지키는 코퍼스 집합과 계측기가 읽는 집합을 묶는다 — 한쪽 glob만 바뀌면
        # "계측기는 보는데 계약은 모르는" 코퍼스(CONT-09 사고 형태)가 다시 생긴다.
        from whymath_backend.harness import problem_bank_coverage as pbc

        assert ptm._CORPUS_DIR_GLOB is pbc.CORPUS_DIR_GLOB  # 값 복제가 아니라 같은 상수 객체.

        # PB-20 `test_investigation_doc_names_every_glob_consumer`와 같은 AST 규칙: 이 모듈에
        # `problem_bank`+`*` 문자열 상수가 다시 생기면 조사 문서 소비처 표에 새 행이 필요해진다.
        tree = ast.parse(Path(ptm.__file__).read_text(encoding="utf-8"))
        duplicated = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and re.fullmatch(r"[\w./*\[\]{}\-]+", node.value)
            and "problem_bank" in node.value
            and "*" in node.value
        ]
        assert duplicated == [], f"글롭 상수 복제 금지(PB-20): {duplicated}"

    def test_real_repo_has_no_seat_violations(self) -> None:
        assert ptm.find_corpus_seat_violations() == []

    def test_real_repo_seat_count_equals_directory_count(self) -> None:
        # 좌석 합계 == 디스크의 코퍼스 디렉터리 수 — 한쪽만 늘어난 드리프트를 숫자로 드러낸다.
        on_disk = sorted(p.name for p in _CORPUS_ROOT.glob("problem_bank*") if p.is_dir())
        seats = ptm._corpus_seats()
        assert on_disk == sorted(seats)
        assert on_disk, "스캔 0건"

    def test_normal_mirror_is_green(self, tmp_path: Path) -> None:
        self._mirror_seats(tmp_path)
        assert ptm.find_corpus_seat_violations(tmp_path) == []

    def test_unseated_new_corpus_is_red(self, tmp_path: Path) -> None:
        self._mirror_seats(tmp_path)
        (tmp_path / "problem_bank_brand_new_v0").mkdir()
        violations = ptm.find_corpus_seat_violations(tmp_path)
        assert len(violations) == 1
        assert "problem_bank_brand_new_v0" in violations[0]
        assert "어느 좌석" in violations[0]

    def test_removing_one_real_corpus_from_its_seat_is_red_then_green(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # acceptance④ 변별력: 실제 코퍼스 1종을 좌석에서 빼면 RED, 되돌리면 GREEN.
        victim = ptm.UNIT_CODE_TABLE_CORPORA[0]
        assert ptm.find_corpus_seat_violations() == []  # 정상 상태 GREEN.

        monkeypatch.setattr(
            ptm, "TARGET_CORPORA", tuple(n for n in ptm.TARGET_CORPORA if n != victim)
        )
        red = ptm.find_corpus_seat_violations()
        assert len(red) == 1 and victim in red[0]

        monkeypatch.undo()
        assert ptm.find_corpus_seat_violations() == []  # 원복 후 GREEN.

    def test_corpus_on_two_seats_is_red(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # 자가 태깅이면서 직접 분류이기도 하면 백필이 저장 유형을 지운다 — 중복 좌석을 막는다.
        self._mirror_seats(tmp_path)
        both = ptm.UNIT_CODE_TABLE_CORPORA[0]
        monkeypatch.setattr(ptm, "SELF_TAGGED_CORPORA", (*ptm.SELF_TAGGED_CORPORA, both))
        violations = ptm.find_corpus_seat_violations(tmp_path)
        assert len(violations) == 1 and both in violations[0] and "중복" in violations[0]

    def test_stale_seat_without_directory_is_red(self, tmp_path: Path) -> None:
        self._mirror_seats(tmp_path)
        gone = ptm.UNIT_CODE_TABLE_CORPORA[0]
        (tmp_path / gone).rmdir()
        violations = ptm.find_corpus_seat_violations(tmp_path)
        assert len(violations) == 1 and gone in violations[0] and "디렉터리가 없다" in violations[0]

    def test_zero_scan_is_a_failure_not_a_pass(self, tmp_path: Path) -> None:
        # 빈 루트·존재하지 않는 루트 모두 "위반 없음"이 아니라 위반이다(공허한 통과 금지).
        assert ptm.find_corpus_seat_violations(tmp_path)  # 빈 디렉터리.
        assert ptm.find_corpus_seat_violations(tmp_path / "does-not-exist")  # 없는 경로.


class TestSelfTaggedSeat:
    """자가 태깅 좌석(p3_calculus1_diff_v0) — 백필이 쓰지 않으므로 저장분 자체를 상시 대조한다."""

    def test_seat_membership(self) -> None:
        assert ptm.SELF_TAGGED_CORPORA == (
            ptm.CORPUS_P3_CALCULUS1_DIFF_V0,
            ptm.CORPUS_P3_FILL_V0,
        )
        # 직접 분류 대상이면 백필이 저장된 유형을 지운다 — 좌석이 서로소여야 한다.
        assert ptm.CORPUS_P3_CALCULUS1_DIFF_V0 not in ptm.TARGET_CORPORA
        assert ptm.CORPUS_P3_CALCULUS1_DIFF_V0 not in ptm.LINEAGE_CORPORA
        assert ptm.CORPUS_P3_FILL_V0 not in ptm.TARGET_CORPORA
        assert ptm.CORPUS_P3_FILL_V0 not in ptm.LINEAGE_CORPORA

    def test_classify_record_cannot_derive_it(self) -> None:
        # 같은 unit_codes 안에서 유형이 갈리므로 표 분류는 불가 — 침묵 오분류 대신 빈 리스트.
        sample = _load_corpus_lines(ptm.CORPUS_P3_CALCULUS1_DIFF_V0)[0]
        assert ptm.classify_record(ptm.CORPUS_P3_CALCULUS1_DIFF_V0, sample) == []

    def test_every_stored_record_is_tagged_with_a_catalog_type(self) -> None:
        for name in ptm.SELF_TAGGED_CORPORA:
            records = _load_corpus_lines(name)
            assert records, f"{name}: 스캔 0건"
            for record in records:
                codes = record.get("problem_type_codes")
                assert isinstance(codes, list) and len(codes) == 1, record.get("slug")
                assert codes[0] in ptm.ALL_PROBLEM_TYPE_IDS, record.get("slug")


class TestLineageClassification:
    """계보 분류(PB-07) 단위 계약 — 부모 slug 복원·유형 승계·침묵 오분류 금지."""

    def test_rel_type_variant_literal_matches_schema_enum(self) -> None:
        # `_REL_TYPE_VARIANT` 리터럴이 정본(schema/enums.py RelationType.변형)과 정확히 일치 —
        # PTYPE_* 상수의 "재정의 아님·정본 대조" 원칙과 동일한 드리프트 방지 거버넌스.
        assert ptm._REL_TYPE_VARIANT == RelationType.변형.value

    def test_parent_slug_resolved_from_single_variant_relation(self) -> None:
        record = {
            "relations": [
                {"parent_slug": "wm-skel-abc", "relation_type": "변형", "similarity_score": 1.0}
            ]
        }
        assert ptm.rephrased_parent_slug(record) == "wm-skel-abc"

    def test_parent_slug_ignores_non_variant_relations(self) -> None:
        # "유사"(S4-14 형제 태깅) 등 다른 관계 타입은 계보가 아니다 — 섞여 있어도 "변형"만 본다.
        record = {
            "relations": [
                {"parent_slug": "wm-sibling", "relation_type": "유사", "similarity_score": 0.9},
                {"parent_slug": "wm-skel-abc", "relation_type": "변형", "similarity_score": 1.0},
            ]
        }
        assert ptm.rephrased_parent_slug(record) == "wm-skel-abc"

    def test_parent_slug_none_when_no_relations_or_ambiguous(self) -> None:
        # 침묵 오분류 금지 — 0건·서로 다른 부모 2건·비정상 형태는 전부 None(미태깅).
        assert ptm.rephrased_parent_slug({}) is None
        assert ptm.rephrased_parent_slug({"relations": []}) is None
        assert ptm.rephrased_parent_slug({"relations": "not-a-list"}) is None
        two_parents = {
            "relations": [
                {"parent_slug": "wm-a", "relation_type": "변형"},
                {"parent_slug": "wm-b", "relation_type": "변형"},
            ]
        }
        assert ptm.rephrased_parent_slug(two_parents) is None

    def test_classify_inherits_parent_type_and_handles_missing_parent(self) -> None:
        record = {
            "relations": [{"parent_slug": "wm-skel-abc", "relation_type": "변형"}],
        }
        index = {"wm-skel-abc": [ptm.PTYPE_SOLVE_FOR_UNKNOWN]}
        assert ptm.classify_rephrased_record(record, index) == [ptm.PTYPE_SOLVE_FOR_UNKNOWN]
        # 색인에 부모가 없으면(계보로도 추적 불가) 빈 리스트 — 백필 리포트 untagged가 센다.
        assert ptm.classify_rephrased_record(record, {}) == []
        # 부모가 미태깅이면 자식도 미태깅(승계할 유형이 없다 — 날조 금지).
        assert ptm.classify_rephrased_record(record, {"wm-skel-abc": []}) == []

    def test_real_corpus_lineage_resolves_for_all_records(self) -> None:
        # acceptance① 동결 — 실 코퍼스 421건 전건이 "변형" 계보 1건을 갖고, 부모 slug가 직접
        # 분류 6종 색인에서 유일하게 해석된다(2026-08-11 실측: 421/421·부모 전건 generated_v0).
        index = _parent_type_index()
        records = _load_corpus_lines(ptm.CORPUS_REPHRASED_V0)
        assert len(records) == _GOLDEN_LINEAGE_TOTAL
        for record in records:
            slug = ptm.rephrased_parent_slug(record)
            assert slug is not None, f"{record.get('slug')} 계보 부재"
            assert slug in index, f"{record.get('slug')} 부모 {slug} 색인 미해석"


def _write_task_yaml(tasks_dir: Path, task_id: str, status: str) -> None:
    """백로그 태스크 YAML 최소 픽스처(만료 계약 테스트 전용) —
    `find_exclusion_expiry_violations`가 실제로 읽는 `id`·`status`만 담는다
    (`tests/backend/ops/test_provenance_audit.py` 동명 헬퍼와 동형)."""
    tasks_dir.mkdir(parents=True, exist_ok=True)
    (tasks_dir / f"{task_id}.yaml").write_text(
        yaml.safe_dump({"id": task_id, "status": status}, allow_unicode=True),
        encoding="utf-8",
    )


class TestExclusionExpiryContract:
    """제외 만료 계약(PB-07) — task_id 참조 무결성 + done 방치 트립와이어.

    `EXCLUDED_CORPORA`의 각 항목이 ①실재하는 backlog 태스크를 참조하는지 ②참조된 태스크가
    이미 done인데 항목이 방치되지 않았는지를 상시 대조한다. `ops/provenance_audit`의
    `TestGrandfatherExpiryContract`(ARCH-25)와 동형 — 같은 성격의 좌석(`EXCLUDED_CORPORA`)이
    계약 밖에 남아 rephrased 제외가 사유 소멸 후 6일 방치된 2회차 재발 방지
    (`problem_bank_gap_review_r3.md` §6-ⓑ). 자동 해제가 아니다 — 해제는 여전히 사람 판단이고,
    이 계약은 방치를 구조적으로 드러내는 트립와이어일 뿐이다.

    변별력 확인(CLAUDE.md "변별력 없는 검증 스텝 금지"): monkeypatch로 `EXCLUDED_CORPORA`를
    테스트 전용 딕셔너리로 교체해 ①②가 실제로 위반을 검출하는지(red)와, 정상 상태에서는
    검출하지 않는지(green)를 모두 확인한다 — 성공/성공 또는 실패/실패로 같은 값이 나오면
    위장이다. 실좌석 뮤테이션 red 실측(acceptance ④)은 구현 세션이 cp 백업 방식으로 별도
    수행했다(PB-07 리포트).
    """

    def test_real_excluded_corpora_reference_real_and_non_done_tasks(self) -> None:
        """저장소의 실 `EXCLUDED_CORPORA`(PB-07 해제 후 빈 딕셔너리)가 계약을 위반하지 않는다.
        비어 있으면 자명 통과 — 지금 뭔가를 잡으려는 게 아니라, 향후 항목이 재등재될 때
        방치를 기계로 드러내는 상시 트립와이어로 배선해 두는 것이 핵심이다(아래 monkeypatch
        테스트가 변별력을 실측한다). ARCH-25의 빈 `_KNOWN_GAPS` 테스트와 동형."""
        violations = ptm.find_exclusion_expiry_violations()
        assert violations == [], f"제외 만료 계약 위반: {violations}"

    def test_real_seat_is_empty_after_pb07_release(self) -> None:
        """PB-07 해제 상태 동결 — 좌석이 다시 채워지려면 ExclusionEntry(task_id 강제)를 거쳐야
        하고, 그 항목은 위 상시 테스트의 대조를 받는다(빈 상태에서도 계약 유효 — acceptance ③)."""
        assert ptm.EXCLUDED_CORPORA == {}

    def test_nonexistent_task_id_is_flagged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """① 실존하지 않는 task_id를 가리키는 제외 항목은 위반으로 잡혀야 한다(red).

        참조 대상 태스크 파일을 아예 만들지 않는다 — "존재하지 않는 ID" 시나리오 재현."""
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        monkeypatch.setattr(
            ptm,
            "EXCLUDED_CORPORA",
            {
                "fake_corpus": ptm.ExclusionEntry(
                    task_id="NONEXISTENT-TASK-ID-XYZ", reason="테스트용 사유"
                )
            },
        )
        violations = ptm.find_exclusion_expiry_violations(tasks_dir=tasks_dir)
        assert len(violations) == 1
        assert "NONEXISTENT-TASK-ID-XYZ" in violations[0]

    def test_done_task_still_excluded_is_flagged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """② 참조된 태스크가 이미 done인데 제외 항목이 남아 있으면 위반으로 잡혀야 한다(red)
        — 이번 사고 그 자체("S4-14 done 후 6일 방치")를 시나리오로 재현한다."""
        tasks_dir = tmp_path / "tasks"
        _write_task_yaml(tasks_dir, "FAKE-DONE-TASK", status="done")
        monkeypatch.setattr(
            ptm,
            "EXCLUDED_CORPORA",
            {"fake_corpus": ptm.ExclusionEntry(task_id="FAKE-DONE-TASK", reason="테스트용 사유")},
        )
        violations = ptm.find_exclusion_expiry_violations(tasks_dir=tasks_dir)
        assert len(violations) == 1
        assert "FAKE-DONE-TASK" in violations[0]

    def test_todo_task_is_not_flagged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """대조군(green) — 참조된 태스크가 아직 done이 아니면 위반이 아니다. ②가 done 여부로
        실제 갈리는지(같은 코드 경로에서 done만 다르게) 확인해 변별력을 보강한다."""
        tasks_dir = tmp_path / "tasks"
        _write_task_yaml(tasks_dir, "FAKE-TODO-TASK", status="todo")
        monkeypatch.setattr(
            ptm,
            "EXCLUDED_CORPORA",
            {"fake_corpus": ptm.ExclusionEntry(task_id="FAKE-TODO-TASK", reason="테스트용 사유")},
        )
        violations = ptm.find_exclusion_expiry_violations(tasks_dir=tasks_dir)
        assert violations == []
