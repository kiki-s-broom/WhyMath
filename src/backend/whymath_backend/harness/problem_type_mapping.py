"""생성기 identity → `problem_type_id` 결정론 매핑표 (S3-27).

설계 정본: `docs/architecture/ai_content_generation_gap_review.md` D3(백로그 `S3-27`) ·
유보 해제 근거는 `docs/architecture/problem_bank_gap_review.md` §5-③ 편집자 부기(2026-07-30).

**핵심 통찰(D3)**: 17 `problem_type_id`는 *인지 행동* 기준이라 문항 텍스트를 읽어야만 분류할 수
있을 것 같지만, 이 코퍼스의 스켈레톤 생성기는 **생성기(혹은 생성기의 밴드 파라미터) 1종이 인지
행동 1종을 고정 산출**한다 — 그래서 "생성기 identity → 유형" 매핑표 하나로 코퍼스 전체를 텍스트
파싱 없이 결정론 분류할 수 있다. 이 모듈이 그 매핑표(정본)다.

**LLM 0·문항 텍스트 파싱/추론 0** — 아래 딕셔너리 값은 전부 사람(에이전트)이 각 생성기 코드
(`l3/equivalent/*_skeleton_generator.py`)와 `problem_type_graph_v1/problem_types.jsonl`의
`behavior_skills`를 대조해 판단한 *정본*이다. 런타임에는 이 표를 찾아보기만 한다(텍스트 추론 없음).

**코퍼스별 식별 키가 다르다** — 생성기 identity가 레코드에 남기는 흔적이 코퍼스마다 다르기 때문
(재계산 0 원칙 — 이미 있는 데이터만 읽는다):
  - `problem_bank_generated_v0`: `unit_codes`가 생성기 클래스와 1:1(quad 4-variant만 한 클래스
    `SkeletonEquivalentProblemGenerator`를 공유해 `unit_codes=('QUAD-EQ',)`로 합쳐진다 — variant
    는 발문 형식만 바꿀 뿐 인지 행동은 동일하므로 **같은 유형**이 맞다).
  - `problem_bank_conceptual_v0`·`problem_bank_misconception_mc_v0`: 한 생성기 클래스
    (`ConceptualCountMCSkeletonGenerator`·`MisconceptionEvalMCSkeletonGenerator`)가 템플릿
    파라미터별로 *다른* 인지 행동을 낸다 — 템플릿 식별자는 레코드에 직접 없지만, 배치 CLI가
    `target_misconception_ids={kebab}` 1종만 주입해 `distractor_map`의 `misconception_id`가
    템플릿을 1:1로 복원한다(`_distractor_kebab`).
  - `problem_bank_killer_v0`: 코퍼스 전체가 `RootAggregateSkeletonGenerator`(Vieta 합/곱) 1종 —
    `unit_codes=('POLY-ROOT',)` 확인만으로 충분(sum/product·차수 구분은 유형에 영향 없음 — 둘 다
    "공식에 대입해 값을 구하는" 동일 인지 행동).
  - `problem_bank_probability_finite_v0`: `unit_codes`가 확률형/개수형 2 밴드를 가른다.
  - `problem_bank_v1`(4건, 레거시 손저작): 생성기 배치 흔적이 없어 slug로 직접 판단(사람 판단·
    아래 개별 주석에 근거 명시).
  - `problem_bank_rephrased_v0`(421건): **계보(lineage) 분류** — 재서술은 발문(question_text)
    표현만 바꾸고 수치·정답·풀이 절차는 부모와 동일하므로(`_provenance.json` 계약·
    `test_corpus_quality.py` 봉인) 인지 행동도 부모와 같다. `relations`의 "변형" 계보
    (`parent_slug` — S4-14/S4-18 영속·2026-08-11 실측 421/421 전건 성립)로 부모(원 생성기
    산출물)를 찾아 부모의 유형을 그대로 승계한다(`classify_rephrased_record`). 단일 레코드만
    으로는 분류할 수 없어 `classify_record`가 아니라 부모 색인을 요구하는 별도 함수다.
    (구 "S4-14 미착지" 명시 제외는 사유 소멸로 `PB-07`이 해제 —
    `docs/architecture/problem_bank_gap_review_r3.md` §3 G2.)

경계(CLAUDE.md 7계층·`problem_bank_gap_review.md` §5-③ 판정 유지): 이 모듈은 **관측 축**이다.
`problem_type_node` FK 연결·유형별 생성 확대·추천/출제 로직은 스코프 밖 — 여기서 만드는 것은
`Problem.problem_type_codes`에 넣을 *문자열 참조*뿐이다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from whymath_backend.harness.problem_bank_coverage import CORPUS_DIR_GLOB

__all__ = [
    "ALL_PROBLEM_TYPE_IDS",
    "CORPUS_CONCEPTUAL_V0",
    "CORPUS_GENERATED_V0",
    "CORPUS_KILLER_V0",
    "CORPUS_MISCONCEPTION_MC_V0",
    "CORPUS_P3_CALCULUS1_DIFF_V0",
    "CORPUS_PROBABILITY_FINITE_V0",
    "CORPUS_REPHRASED_V0",
    "CORPUS_V1",
    "EXCLUDED_CORPORA",
    "ExclusionEntry",
    "LINEAGE_CORPORA",
    "PTYPE_CONDITION_SATISFACTION",
    "PTYPE_CONSTRUCT_OBJECT",
    "PTYPE_COUNT_SOLUTIONS",
    "PTYPE_DETERMINE_COEFFICIENT",
    "PTYPE_ENUMERATE_CASES",
    "PTYPE_EVALUATE_EXPRESSION",
    "PTYPE_EXISTENCE_DECISION",
    "PTYPE_GENERALIZE_PATTERN",
    "PTYPE_INFER_RELATIONSHIP",
    "PTYPE_MODEL_WORD_PROBLEM",
    "PTYPE_OPTIMIZE_CONSTRAINED",
    "PTYPE_OPTIMIZE_EXTREMUM",
    "PTYPE_PROVE_STATEMENT",
    "PTYPE_SKETCH_GRAPH",
    "PTYPE_SOLVE_FOR_UNKNOWN",
    "PTYPE_TRANSFORM_EXPRESSION",
    "PTYPE_VERIFY_CLAIM",
    "SELF_TAGGED_CORPORA",
    "TARGET_CORPORA",
    "UNIT_CODE_TABLE_CORPORA",
    "classify_record",
    "classify_rephrased_record",
    "default_backlog_tasks_dir",
    "default_corpus_root",
    "find_corpus_seat_violations",
    "find_exclusion_expiry_violations",
    "rephrased_parent_slug",
]

# ──────────────────────────────────────────────────────────────────────────
# 17종 problem_type_id 상수 — 정본은 `data/corpus/problem_type_graph_v1/problem_types.jsonl`
# (재정의 아님·오탈자 방지용 리터럴 상수일 뿐). 문자열 값이 정본과 어긋나면 거버넌스 테스트가
# `problem_types.jsonl`을 읽어 대조한다(`test_problem_type_mapping.py`).
# ──────────────────────────────────────────────────────────────────────────
PTYPE_SOLVE_FOR_UNKNOWN = "ptype.solve-for-unknown"
PTYPE_EVALUATE_EXPRESSION = "ptype.evaluate-expression"
PTYPE_DETERMINE_COEFFICIENT = "ptype.determine-coefficient"
PTYPE_EXISTENCE_DECISION = "ptype.existence-decision"
PTYPE_CONDITION_SATISFACTION = "ptype.condition-satisfaction"
PTYPE_COUNT_SOLUTIONS = "ptype.count-solutions"
PTYPE_ENUMERATE_CASES = "ptype.enumerate-cases"
PTYPE_OPTIMIZE_EXTREMUM = "ptype.optimize-extremum"
PTYPE_OPTIMIZE_CONSTRAINED = "ptype.optimize-constrained"
PTYPE_INFER_RELATIONSHIP = "ptype.infer-relationship"
PTYPE_GENERALIZE_PATTERN = "ptype.generalize-pattern"
PTYPE_PROVE_STATEMENT = "ptype.prove-statement"
PTYPE_MODEL_WORD_PROBLEM = "ptype.model-word-problem"
PTYPE_CONSTRUCT_OBJECT = "ptype.construct-object"
PTYPE_VERIFY_CLAIM = "ptype.verify-claim"
PTYPE_SKETCH_GRAPH = "ptype.sketch-graph"
PTYPE_TRANSFORM_EXPRESSION = "ptype.transform-expression"

ALL_PROBLEM_TYPE_IDS: frozenset[str] = frozenset(
    {
        PTYPE_SOLVE_FOR_UNKNOWN,
        PTYPE_EVALUATE_EXPRESSION,
        PTYPE_DETERMINE_COEFFICIENT,
        PTYPE_EXISTENCE_DECISION,
        PTYPE_CONDITION_SATISFACTION,
        PTYPE_COUNT_SOLUTIONS,
        PTYPE_ENUMERATE_CASES,
        PTYPE_OPTIMIZE_EXTREMUM,
        PTYPE_OPTIMIZE_CONSTRAINED,
        PTYPE_INFER_RELATIONSHIP,
        PTYPE_GENERALIZE_PATTERN,
        PTYPE_PROVE_STATEMENT,
        PTYPE_MODEL_WORD_PROBLEM,
        PTYPE_CONSTRUCT_OBJECT,
        PTYPE_VERIFY_CLAIM,
        PTYPE_SKETCH_GRAPH,
        PTYPE_TRANSFORM_EXPRESSION,
    }
)

# ──────────────────────────────────────────────────────────────────────────
# 코퍼스 디렉터리명 상수 — `data/corpus/problem_bank_*` 관례.
# ──────────────────────────────────────────────────────────────────────────
CORPUS_V1 = "problem_bank_v1"
CORPUS_GENERATED_V0 = "problem_bank_generated_v0"
CORPUS_CONCEPTUAL_V0 = "problem_bank_conceptual_v0"
CORPUS_KILLER_V0 = "problem_bank_killer_v0"
CORPUS_MISCONCEPTION_MC_V0 = "problem_bank_misconception_mc_v0"
CORPUS_PROBABILITY_FINITE_V0 = "problem_bank_probability_finite_v0"
CORPUS_REPHRASED_V0 = "problem_bank_rephrased_v0"

CORPUS_P3_CALCULUS1_DIFF_V0 = "problem_bank_p3_calculus1_diff_v0"
# P3-05 4·5단계 — 빈 칸 채우기 은행. P3-03 은행과 같은 자가 태깅(생성기가 문항마다 유형을 단다).
CORPUS_P3_FILL_V0 = "problem_bank_p3_fill_v0"

# ──────────────────────────────────────────────────────────────────────────
# CONT-09 — S3-27 이후 추가된 코퍼스 30종의 `unit_codes` → problem_type_id 표.
#
# 이 30종은 코퍼스당 `unit_codes` 값이 1~3개뿐이고 값 하나가 생성기 1종(또는 생성기의 밴드 1개)과
# 1:1이라, 위 6종처럼 오개념 kebab 같은 우회 키가 필요 없다 — `unit_codes` 튜플 자체가 키다.
# 값은 전부 사람(에이전트)이 각 코퍼스의 생성기 발문(`l3/equivalent/*_skeleton_generator.py`
# 산출 `question_text` 샘플)과 `problem_types.jsonl`의 설명·`behavior_skills`를 대조해 판단한
# 정본이다(LLM 0·런타임 텍스트 파싱 0). 판단 원칙은 기존 6종과 같다 — 문항이 **요구하는 인지
# 행동**으로 가르고, 정답이 숫자 하나라는 사실(답 형식)로 가르지 않는다.
#
# 대다수는 "식·공식에 값을 대입·연산해 값을 낸다" = evaluate-expression이다. 아래 4군(unit_codes
# 7종)만 다른 인지 행동이라 값이 다르다(이 표에서 사람 판단이 갈릴 수 있는 지점 — CONT-09 리포트
# `docs/data/problem_type_tagging_untagged_corpora_cont09_2026-10.md` §4에 근거를 명시):
#   · enumerate-cases   : REPEATED-COMBINATION·SUM-PRODUCT-PRINCIPLE·PERMUTATION (경우의 수를 센다).
#   · determine-coefficient : LINE-EQUATION (두 점 조건으로 미정계수 a·b를 역으로 결정).
#   · condition-satisfaction: LINEAR-INEQUALITY-SYSTEM·QUAD-INEQ-BOUNDARY (조건을 성립시키는
#                              범위를 판정 — 경계값은 그 범위의 끝점).
#   · transform-expression  : POLYNOMIAL-FACTORING (식을 곱의 꼴로 변형 — 상수항 읽기는 사후 단계).
# ──────────────────────────────────────────────────────────────────────────
_UNIT_CODE_TABLES: dict[str, dict[tuple[str, ...], str]] = {
    # E(X)=np 공식 대입.
    "problem_bank_binomial_distribution_v0": {
        ("BINOMIAL-DISTRIBUTION",): PTYPE_EVALUATE_EXPRESSION
    },
    # 부정적분 구한 뒤 F(0)=c로 적분상수를 맞춰 F(a)를 계산 — 절차 실행(적분 공식 대입).
    "problem_bank_calculus1_integral_v0": {("CALC1-INTEGRAL",): PTYPE_EVALUATE_EXPRESSION},
    # 삼각함수 정적분의 값을 계산.
    "problem_bank_calculus2_trig_integral_v0": {
        ("CALC2-TRIG-INTEGRAL",): PTYPE_EVALUATE_EXPRESSION
    },
    "problem_bank_combination_binomial_v0": {
        # 중복조합 H(n,r)의 경우의 수를 센다(misconception_mc의 combination-no-denominator와 동형).
        ("REPEATED-COMBINATION",): PTYPE_ENUMERATE_CASES,
        # 이항정리 공식 nCr·계수 대입 — 경우의 수를 "세는" 문제가 아니라 공식 실행.
        ("BINOMIAL-COEFFICIENT",): PTYPE_EVALUATE_EXPRESSION,
    },
    # 복소수 덧셈·곱셈 결과의 실수부/허수부를 계산.
    "problem_bank_complex_number_arithmetic_v0": {
        ("COMPLEX-NUMBER-ARITHMETIC",): PTYPE_EVALUATE_EXPRESSION
    },
    # 포물선 y²=4px의 초점 좌표 — 공식 대입.
    "problem_bank_conic_section_focus_v0": {("CONIC-SECTION-FOCUS",): PTYPE_EVALUATE_EXPRESSION},
    "problem_bank_coordinate_geometry_v0": {
        # 두 점 사이 거리 공식 대입.
        ("POINT-DISTANCE",): PTYPE_EVALUATE_EXPRESSION,
        # 두 점을 지나는 직선 y=ax+b의 a·b를 역으로 결정(wm-quad-fn-axis와 동형 — 조건→미정계수).
        ("LINE-EQUATION",): PTYPE_DETERMINE_COEFFICIENT,
    },
    # E(X)=Σ x·P(X=x) 공식 대입.
    "problem_bank_discrete_ev_v0": {("DISCRETE-EXPECTED-VALUE",): PTYPE_EVALUATE_EXPRESSION},
    # 단위 환산·겉넓이 공식 — 값을 대입·연산.
    "problem_bank_elementary_area_measure_v0": {
        ("AREA-UNIT-CONVERSION",): PTYPE_EVALUATE_EXPRESSION,
        ("RECT-PRISM-SURFACE-AREA",): PTYPE_EVALUATE_EXPRESSION,
    },
    "problem_bank_elementary_division_remainder_v0": {
        ("TWO-DIGIT-DIVISION",): PTYPE_EVALUATE_EXPRESSION
    },
    # 최대공약수 계산(misconception_mc의 gcd-lcm-confused와 동형).
    "problem_bank_elementary_gcd_lcm_v0": {("GCD-LCM",): PTYPE_EVALUATE_EXPRESSION},
    "problem_bank_elementary_rounding_v0": {("ELEMENTARY-ROUNDING",): PTYPE_EVALUATE_EXPRESSION},
    "problem_bank_elementary_v0": {("ELEM-ADDSUB-2DIGIT",): PTYPE_EVALUATE_EXPRESSION},
    "problem_bank_elementary_volume_measure_v0": {
        ("RECT-PRISM-VOLUME",): PTYPE_EVALUATE_EXPRESSION,
        ("VOLUME-UNIT-CONVERSION",): PTYPE_EVALUATE_EXPRESSION,
        ("CIRCLE-CIRCUMFERENCE",): PTYPE_EVALUATE_EXPRESSION,
    },
    # 몫의 미분법 공식 대입 후 미분계수 계산(misconception_mc의 product-rule-naive와 동형).
    "problem_bank_highschool_quotient_rule_v0": {
        ("HS-CALC2-QUOTIENT-RULE",): PTYPE_EVALUATE_EXPRESSION
    },
    # 연립일차부등식의 해 범위를 판정하고 그 경계값을 읽는다 — 조건을 성립시키는 범위 판정.
    "problem_bank_linear_inequality_system_v0": {
        ("LINEAR-INEQUALITY-SYSTEM",): PTYPE_CONDITION_SATISFACTION
    },
    "problem_bank_matrix_ops_v0": {("MATRIX-OPS",): PTYPE_EVALUATE_EXPRESSION},
    "problem_bank_measurement_unit_conversion_v0": {
        ("MEASUREMENT-UNIT-CONVERSION",): PTYPE_EVALUATE_EXPRESSION
    },
    # 일차함수 f(a)의 함숫값 — 대입.
    "problem_bank_middle_function_v0": {("LINEAR-FUNC-VALUE",): PTYPE_EVALUATE_EXPRESSION},
    # 합의 법칙·순열 — 경우의 수를 센다.
    "problem_bank_permutation_combination_v0": {
        ("SUM-PRODUCT-PRINCIPLE",): PTYPE_ENUMERATE_CASES,
        ("PERMUTATION",): PTYPE_ENUMERATE_CASES,
    },
    # 다항식 덧셈·곱셈 결과의 계수 계산(`skill.polynomial-arithmetic`이 evaluate-expression 소속).
    "problem_bank_polynomial_arithmetic_v0": {
        ("POLYNOMIAL-ARITHMETIC",): PTYPE_EVALUATE_EXPRESSION
    },
    # 이차식을 (x+p)(x+q)로 인수분해(`skill.factorization`이 transform-expression 소속).
    "problem_bank_polynomial_factoring_v0": {("POLYNOMIAL-FACTORING",): PTYPE_TRANSFORM_EXPRESSION},
    # 확률의 덧셈·여사건·곱셈 정리 공식 대입(finite_v0의 PROB-FINITE-ENUM과 동형).
    "problem_bank_probability_law_v0": {
        ("PROBABILITY-ADDITION-LAW",): PTYPE_EVALUATE_EXPRESSION,
        ("PROBABILITY-COMPLEMENT-LAW",): PTYPE_EVALUATE_EXPRESSION,
        ("PROBABILITY-MULTIPLICATION-LAW",): PTYPE_EVALUATE_EXPRESSION,
    },
    # 이차부등식 해의 범위(두 경계)를 판정 — LINEAR-INEQUALITY-SYSTEM과 같은 인지 행동.
    "problem_bank_quad_ineq_v0": {("QUAD-INEQ-BOUNDARY",): PTYPE_CONDITION_SATISFACTION},
    # 육십분법→호도법 환산 — 단위 환산 3종과 같은 인지 행동(상수배 연산)으로 일관시킨다.
    "problem_bank_radian_conversion_v0": {("RADIAN-CONVERSION",): PTYPE_EVALUATE_EXPRESSION},
    # 표본평균의 평균 E(X̄)=m 공식 대입.
    "problem_bank_sample_mean_distribution_v0": {
        ("SAMPLE-MEAN-DISTRIBUTION",): PTYPE_EVALUATE_EXPRESSION
    },
    # 시그마의 선형성·거듭제곱합 공식 대입(generated_v0의 ARITH-SUM과 동형).
    "problem_bank_sequence_sigma_v0": {
        ("SIGMA-LINEARITY",): PTYPE_EVALUATE_EXPRESSION,
        ("POWER-SUM",): PTYPE_EVALUATE_EXPRESSION,
    },
    # 몫의 미분법·연쇄법칙 공식 대입 후 미분계수 계산.
    "problem_bank_university_calc1_chain_quotient_v0": {
        ("CALC1-QUOTIENT-RULE",): PTYPE_EVALUATE_EXPRESSION,
        ("CALC1-CHAIN-RULE",): PTYPE_EVALUATE_EXPRESSION,
    },
    "problem_bank_university_calc1_v0": {("CALC1-PRODUCT-RULE",): PTYPE_EVALUATE_EXPRESSION},
    # 벡터 선형결합·위치벡터 성분 계산.
    "problem_bank_vector_operations_v0": {
        ("VECTOR-LINEAR-COMBO",): PTYPE_EVALUATE_EXPRESSION,
        ("POSITION-VECTOR",): PTYPE_EVALUATE_EXPRESSION,
    },
}

# `unit_codes` 표로 직접 분류하는 코퍼스(결정론 순서 — 이름 오름차순).
UNIT_CODE_TABLE_CORPORA: tuple[str, ...] = tuple(sorted(_UNIT_CODE_TABLES))

# 직접 분류 대상(결정론 순서) — 생성기 identity가 *레코드 자체*에 남아 `classify_record`가
# 단일 레코드로 분류하는 코퍼스: S3-27 원본 6종 + CONT-09가 편입한 `unit_codes` 표 30종.
# `problem_bank_rephrased_v0`은 여기 없다 — 제외가 아니라 **계보 분류**(`LINEAGE_CORPORA`·부모
# 유형 승계)로 태깅한다(PB-07 — 구 제외 사유였던 "S4-14 미착지"는 S4-14/S4-18 done·계보
# 421/421 실측으로 소멸).
TARGET_CORPORA: tuple[str, ...] = (
    CORPUS_V1,
    CORPUS_GENERATED_V0,
    CORPUS_CONCEPTUAL_V0,
    CORPUS_KILLER_V0,
    CORPUS_MISCONCEPTION_MC_V0,
    CORPUS_PROBABILITY_FINITE_V0,
    *UNIT_CODE_TABLE_CORPORA,
)

# 생성 시점에 레코드별 `problem_type_codes`를 직접 기록하는 코퍼스 — 백필이 **건드리지 않는**
# 네 번째 좌석. 같은 `unit_codes` 안에서도 템플릿에 따라 유형이 갈려(예: MEAN-VALUE-THEOREM은
# solve 54·evaluate 12·count 6) `unit_codes` 표로는 분류할 수 없다 — 이 코퍼스를 `TARGET_CORPORA`에
# 넣으면 백필이 저장된 유형을 빈 리스트로 덮어 지운다. 대신 "저장분이 전량 채워져 있고 카탈로그의
# 17종 안에 있는가"를 거버넌스 테스트가 상시 대조한다(`test_problem_type_mapping.py`).
SELF_TAGGED_CORPORA: tuple[str, ...] = (CORPUS_P3_CALCULUS1_DIFF_V0, CORPUS_P3_FILL_V0)

# 계보 분류 대상(결정론 순서) — 자기 레코드의 생성기 흔적이 아니라 "변형" 계보의 부모
# (원 생성기 산출물) 유형을 승계하는 코퍼스. 단일 레코드 서명(`classify_record`)으로는
# 분류 불가라 별도 축이다(`classify_rephrased_record` + 부모 색인 경유 —
# `problem_type_backfill._build_parent_type_index`가 조성).
LINEAGE_CORPORA: tuple[str, ...] = (CORPUS_REPHRASED_V0,)


# ──────────────────────────────────────────────────────────────────────────
# 제외(면제) 좌석 + 만료 계약 — PB-07 (`ops/provenance_audit` ARCH-25 계약의 동형 이식).
# ──────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ExclusionEntry:
    """유형 태깅 제외 항목 — 추적 가능한 백로그 태스크 ID 필수(PB-07 만료 계약).

    사유 문자열만 남긴 제외는 그 사유가 소멸해도(추적 태스크 done) 아무도 모른 채 방치된다 —
    실측 2회차: "S4-14 미착지" 사유의 rephrased_v0 제외가 S4-14 done 후 6일 방치
    (`docs/architecture/problem_bank_gap_review_r3.md` §3 G2·§6-ⓑ, CLAUDE.md 금기
    "만료 없는 유예·제외 금지"). `task_id`를 구조 필드로 못박아 두면
    `find_exclusion_expiry_violations`/`TestExclusionExpiryContract`가 backlog/tasks의 실제
    상태와 대조해 방치를 기계로 드러낸다(자동 해제는 아니다 — 해제는 사람 판단).
    `ops/provenance_audit.GrandfatherEntry`(ARCH-25)와 동형이되 의도적으로 공유하지 않는다
    (2회차에 좌석 열거·공용 도구화는 과공학 — PB-07 acceptance ⑤).
    """

    task_id: str
    reason: str


# 유형 태깅에서 제외하는 코퍼스 — 코퍼스명 → ExclusionEntry(task_id + 사유). 만료 계약 좌석.
# 2026-08-11 PB-07: rephrased_v0 제외를 해제했다(사유 소멸 — S4-14/S4-18 done·계보 421/421
# 실측·이제 LINEAGE_CORPORA로 계보 분류). 현재 빈 딕셔너리 — 향후 제외가 다시 필요하면
# 반드시 실존 백로그 태스크 id + 사유를 가진 ExclusionEntry로 등재한다
# (`test_problem_type_mapping.py` TestExclusionExpiryContract가 동결).
EXCLUDED_CORPORA: dict[str, ExclusionEntry] = {}


def default_backlog_tasks_dir() -> Path:
    """`backlog/tasks` 저장소 정본 경로(만료 계약 검증용) — harness 공통 `parents[4]` 관용구
    (harness/ → whymath_backend/ → backend/ → src/ → repo 루트 —
    `problem_type_backfill._REPO_ROOT`·`provenance_audit.default_backlog_tasks_dir`와 동일)."""
    return Path(__file__).resolve().parents[4] / "backlog" / "tasks"


def _load_backlog_task_statuses(tasks_dir: Path) -> dict[str, str]:
    """`backlog/tasks/*.yaml` → `{task_id: status}` 경량 조회(`provenance_audit` 동형).

    PyYAML `safe_load`만 사용(임의 객체 역직렬화 금지). 파싱 실패·비딕셔너리 문서는 조용히
    건너뛴다 — 이 함수의 책임은 제외 항목 대조이지 백로그 스키마 검증이 아니다.
    """
    statuses: dict[str, str] = {}
    if not tasks_dir.is_dir():
        return statuses
    for path in sorted(tasks_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict):
            continue
        task_id = data.get("id")
        status = data.get("status")
        if isinstance(task_id, str) and isinstance(status, str):
            statuses[task_id] = status
    return statuses


def find_exclusion_expiry_violations(tasks_dir: Path | None = None) -> list[str]:
    """제외 만료 계약 위반 목록(빈 리스트 = 위반 없음) — PB-07(`ARCH-25` 동형).

    ① `EXCLUDED_CORPORA`의 `task_id`가 `backlog/tasks/*.yaml` 어디에도 없다(오타·삭제된
       태스크 참조 — 추적 불가능한 제외).
    ② 참조된 태스크가 이미 `status: done`인데 항목이 여전히 남아 있다(사유 소멸 방치 —
       rephrased_v0 6일 방치의 재발을 기계로 차단). 자동 해제가 아니라 트립와이어다 —
       해제는 여전히 사람 판단·손 편집이다.

    `EXCLUDED_CORPORA`는 모듈 전역을 읽는다(테스트는 `monkeypatch.setattr(ptm,
    "EXCLUDED_CORPORA", ...)`로 교체) — `provenance_audit._KNOWN_GAPS`와 동일 관용구.
    """
    tdir = tasks_dir if tasks_dir is not None else default_backlog_tasks_dir()
    statuses = _load_backlog_task_statuses(tdir)

    violations: list[str] = []
    for corpus_name, entry in EXCLUDED_CORPORA.items():
        status = statuses.get(entry.task_id)
        if status is None:
            violations.append(
                f"{corpus_name}: task_id={entry.task_id!r} 이(가) backlog/tasks/*.yaml에 "
                "존재하지 않는다 — 추적 불가능한 제외."
            )
        elif status == "done":
            violations.append(
                f"{corpus_name}: task_id={entry.task_id!r} 이(가) 이미 done인데 "
                "EXCLUDED_CORPORA 제외 항목이 방치되어 있다 — 해제 검토 필요."
            )
    return violations


def default_corpus_root() -> Path:
    """`data/corpus` 저장소 정본 경로(전수 귀속 검증용 — `default_backlog_tasks_dir` 관용구)."""
    return Path(__file__).resolve().parents[4] / "data" / "corpus"


# 탐색 규칙은 계측기의 `CORPUS_DIR_GLOB`를 **가져와** 쓴다(복제 금지) — 계측기가 읽는 코퍼스 집합과
# 이 계약이 지키는 집합이 어긋나면 "계측기가 보는데 계약은 모르는" 코퍼스가 생긴다(CONT-09 사고
# 형태). 문자열 상수를 여기 다시 두면 PB-20 조사 문서의 글롭 소비처 표에 새 행도 필요해진다.
_CORPUS_DIR_GLOB = CORPUS_DIR_GLOB


def _corpus_seats() -> dict[str, list[str]]:
    """코퍼스명 → 그 코퍼스가 앉아 있는 좌석 이름 목록(모듈 전역을 매번 읽는다 — 테스트 교체용)."""
    seats: dict[str, list[str]] = {}
    groups: tuple[tuple[str, Sequence[str]], ...] = (
        ("TARGET_CORPORA", TARGET_CORPORA),
        ("LINEAGE_CORPORA", LINEAGE_CORPORA),
        ("EXCLUDED_CORPORA", tuple(EXCLUDED_CORPORA)),
        ("SELF_TAGGED_CORPORA", SELF_TAGGED_CORPORA),
    )
    for seat_name, names in groups:
        for name in names:
            seats.setdefault(name, []).append(seat_name)
    return seats


def find_corpus_seat_violations(corpus_root: Path | None = None) -> list[str]:
    """코퍼스 전수 귀속 계약 위반 목록(빈 리스트 = 위반 없음) — CONT-09.

    `data/corpus/problem_bank*` 디렉터리 **전부**가 정확히 한 좌석(`TARGET_CORPORA`·
    `LINEAGE_CORPORA`·`EXCLUDED_CORPORA`·`SELF_TAGGED_CORPORA`)에 앉아야 한다. 새 코퍼스를 만들고
    어느 좌석에도 안 넣으면 `problem_type_codes`가 영원히 빈 채로 남지만 아무 검사도 빨갛지
    않았다 — S3-27이 닫은 뒤 30종 11,396문이 계약 밖에 방치된 원인이다. 세 가지를 위반으로 본다.

    ① 어느 좌석에도 없는 코퍼스(신규 추가 누락) ② 두 좌석에 동시에 앉은 코퍼스(분류 주체 모호 —
    특히 SELF_TAGGED이면서 TARGET이면 백필이 자가 기록을 지운다) ③ 좌석에는 있으나 디렉터리가
    없는 이름(이름 변경·삭제 후 좌석 방치). 그리고 스캔이 **0건이면 그 자체가 위반**이다 — 대상을
    하나도 못 찾은 전수 가드는 공허하게 통과한다(루트 경로 오류가 "위반 없음"으로 위장되지 않게).
    """
    root = corpus_root if corpus_root is not None else default_corpus_root()
    found = (
        sorted(child.name for child in root.glob(_CORPUS_DIR_GLOB) if child.is_dir())
        if root.is_dir()
        else []
    )
    if not found:
        return [
            f"{root}: {_CORPUS_DIR_GLOB} 코퍼스 디렉터리가 0건이다 — 경로 오류이거나 코퍼스가 "
            "사라졌다(스캔 0건은 통과가 아니라 실패)."
        ]

    seats = _corpus_seats()
    violations: list[str] = []
    for name in found:
        placed = seats.get(name, [])
        if not placed:
            violations.append(
                f"{name}: 어느 좌석(TARGET/LINEAGE/EXCLUDED/SELF_TAGGED)에도 속하지 않는다 — "
                "problem_type_codes 태깅 계약 밖. 직접 분류 표에 편입하거나 사유와 함께 "
                "EXCLUDED_CORPORA에 등재한다."
            )
        elif len(placed) > 1:
            violations.append(f"{name}: 좌석이 {len(placed)}곳({', '.join(placed)})에 중복된다.")
    found_set = set(found)
    for name in sorted(seats):
        if name not in found_set:
            violations.append(
                f"{name}: 좌석({', '.join(seats[name])})에는 있으나 {root} 아래에 "
                "디렉터리가 없다 — 이름 변경·삭제 후 방치된 좌석."
            )
    return violations


def _unit_codes(record: Mapping[str, object]) -> tuple[str, ...]:
    """레코드의 `unit_codes` → 정렬된 튜플(순서 무관 매핑 키). 부재·비배열은 빈 튜플."""
    raw = record.get("unit_codes")
    if not isinstance(raw, list):
        return ()
    return tuple(sorted(v for v in raw if isinstance(v, str)))


def _distractor_kebab(record: Mapping[str, object]) -> str | None:
    """`distractor_map`이 태깅하는 오개념 kebab 1종을 복원 — 밴드(=생성기 템플릿) 식별자 대리.

    `conceptual_count_mc_batch`·`misconception_mc_batch`의 각 밴드는
    `EquivalenceSpec.target_misconception_ids={kebab}` 정확히 1종만 주입하므로, 저장된 레코드의
    `distractor_map` 오답 전부가 같은 `misconception_id`를 가리킨다(생성기 계약). 0개나 2개 이상
    이면 밴드를 복원할 수 없으므로 `None`(미태깅)을 반환한다 — 침묵 오분류 금지.
    """
    dmap = record.get("distractor_map")
    if not isinstance(dmap, list) or not dmap:
        return None
    kebabs = {
        entry.get("misconception_id")
        for entry in dmap
        if isinstance(entry, dict) and isinstance(entry.get("misconception_id"), str)
    }
    if len(kebabs) != 1:
        return None
    (kebab,) = kebabs
    return kebab


# ──────────────────────────────────────────────────────────────────────────
# `problem_bank_generated_v0` — unit_codes → problem_type_id (harness/problem_corpus_batch.py
# 밴드 대조·2026-07-30 실측: 각 unit_codes 값은 정확히 1개의 스켈레톤 생성기 클래스가 산출한다).
# ──────────────────────────────────────────────────────────────────────────
_GENERATED_V0_UNIT_TO_TYPE: dict[tuple[str, ...], str] = {
    # SkeletonEquivalentProblemGenerator(variant=short_answer/sqrt/multiple_choice/
    # sqrt_multiple_choice 4종 — 전부 같은 클래스, unit_codes로 합쳐짐) — "이차방정식의 두 근 중
    # 하나를 구하시오": 방정식을 풀어 미지수 값을 구하는 전형적 solve-for-unknown
    # (behavior_skills에 quadratic-equation-solving이 정확히 있음).
    ("QUAD-EQ",): PTYPE_SOLVE_FOR_UNKNOWN,
    # CalculusExtremumSkeletonGenerator — "극솟값을 가질 때 그 x의 값을 구하시오": 극값(x좌표)을
    # 찾는 최적화 절차(도함수=0·부호 판정) → optimize-extremum(behavior_skills: completing-square·
    # solution-checking이 이 절차와 정확히 대응).
    ("CALC-EXTREMUM",): PTYPE_OPTIMIZE_EXTREMUM,
    # CalculusExtremumValueSkeletonGenerator — "극댓값을 구하시오"(값 자체) — 같은 극값 판정
    # 절차의 산출물이 x좌표 대신 값일 뿐 인지 행동은 동일 → optimize-extremum.
    ("CALC-EXTREMUM-VALUE",): PTYPE_OPTIMIZE_EXTREMUM,
    # CalculusExtremumMCSkeletonGenerator — 극값(값) 객관식. 오개념(극대·극소 혼동·값↔좌표 혼동)
    # 자체가 "극값 판정" 절차를 표적으로 하므로 optimize-extremum.
    ("CALC-EXTREMUM-MC",): PTYPE_OPTIMIZE_EXTREMUM,
    # CalculusIrrationalExtremumSkeletonGenerator — 임계점이 p±√q인 무리수 극값. 절차 동일
    # (도함수=0의 근을 구해 극대·극소 판정) → optimize-extremum.
    ("CALC-EXTREMUM-IRR",): PTYPE_OPTIMIZE_EXTREMUM,
    # CalculusTangentSlopeSkeletonGenerator — "접선의 기울기가 m인 점의 x좌표를 구하시오": f'(x)=m
    # 이라는 *방정식을 세워 그 해(x)를 구하는* 문제라 극값 판정과 달리 solve-for-unknown이 정확
    # (극대·극소 여부를 안 따진다 — 근 자체가 답).
    ("CALC-TANGENT",): PTYPE_SOLVE_FOR_UNKNOWN,
    # ExponentialEquationSkeletonGenerator — "bˣ=bᵏ를 만족하는 x의 값을 구하시오": 지수방정식을
    # 풀어 미지수 값을 구함 → solve-for-unknown(equation-rearrangement).
    ("EXP-EQ",): PTYPE_SOLVE_FOR_UNKNOWN,
    # LogarithmicEquationSkeletonGenerator — "log_b x=k를 만족하는 x"도 동일하게 방정식 풀이 →
    # solve-for-unknown.
    ("LOG-EQ",): PTYPE_SOLVE_FOR_UNKNOWN,
    # ArithmeticSequenceSkeletonGenerator — "첫째항 a·공차 d일 때 제n항을 구하시오": 방정식을
    # 세울 필요 없이 공식(aₙ=a+(n-1)d)에 값을 대입만 하면 되는 절차 실행형 →
    # evaluate-expression(behavior_skills의 polynomial-arithmetic과 정확 대응).
    ("ARITH-SEQ",): PTYPE_EVALUATE_EXPRESSION,
    # GeometricSequenceSkeletonGenerator — 등비수열 제n항, 동일 논리(공식 대입) → evaluate-expr.
    ("GEO-SEQ",): PTYPE_EVALUATE_EXPRESSION,
    # ArithmeticSumSkeletonGenerator — Sₙ=n(2a+(n-1)d)/2 공식 대입 → evaluate-expression.
    ("ARITH-SUM",): PTYPE_EVALUATE_EXPRESSION,
    # GeometricSumSkeletonGenerator — Sₙ=a(rⁿ-1)/(r-1) 공식 대입 → evaluate-expression.
    ("GEO-SUM",): PTYPE_EVALUATE_EXPRESSION,
    # TrigonometricValueSkeletonGenerator — "sin 210°의 값을 구하시오": 특수각 값을 직접 계산 →
    # evaluate-expression(방정식을 풀 필요 없음 — 단일 함수값 평가).
    ("TRIG-VAL",): PTYPE_EVALUATE_EXPRESSION,
    # TrigonometricEquationSkeletonGenerator — "0°≤x<360°에서 cos x=1/2의 가장 작은 해를 구하시오":
    # 방정식을 풀고 구간 내 해를 선택하는 문제라 quad 근 선택과 동형 → solve-for-unknown.
    ("TRIG-EQ",): PTYPE_SOLVE_FOR_UNKNOWN,
    # InductiveSequenceSkeletonGenerator — (가)(나) 조건 나열 + 점화식으로 수열을 귀납 정의하고
    # 특정 항을 구함: 명시된 공식이 아니라 점화 규칙에서 등차/등비 패턴을 *일반화*한 뒤 계산해야
    # 하므로 ARITH-SEQ류(공식 직접 대입)와 다르다 → generalize-pattern(description이 명시적으로
    # "수열·귀납 관찰형"을 예시로 든다).
    ("IND-SEQ",): PTYPE_GENERALIZE_PATTERN,
}

# ──────────────────────────────────────────────────────────────────────────
# `problem_bank_conceptual_v0` — 오개념 kebab(=`ConceptualCountMCSkeletonGenerator`의
# `CountTemplateKind`) → problem_type_id. 15밴드 전부 `harness/conceptual_count_mc_batch.py`
# `_BANDS`·`l3/equivalent/conceptual_count_mc_generator.py` 대조(2026-07-30 실측).
# ──────────────────────────────────────────────────────────────────────────
_CONCEPTUAL_V0_KEBAB_TO_TYPE: dict[str, str] = {
    # real_root_count — "서로 다른 실근의 개수를 구하시오"(0 또는 1) → count-solutions.
    "discriminant-negative-no-real-root": PTYPE_COUNT_SOLUTIONS,
    # extremum_count — "극값의 개수를 구하시오"(임계점≠극값 함정) → count-solutions.
    "critical-point-implies-extremum": PTYPE_COUNT_SOLUTIONS,
    # excluded_point_count — 정의역에서 제외되는 점의 개수(분모=0) → count-solutions.
    "division-by-zero": PTYPE_COUNT_SOLUTIONS,
    # root_loss_count — 양변을 나눠 잃은 근을 포함한 실제 근 개수 → count-solutions.
    "root-loss-by-dividing": PTYPE_COUNT_SOLUTIONS,
    # is_one_to_one — "실수 전체에서 일대일대응이면 1, 아니면 0": 함수의 성질(역함수 존재와 직결)에
    # 대한 참/거짓 판정 — 오개념("일대일 아니어도 역함수 있음")을 직접 반박하는 주장 검증형이라
    # verify-claim(existence-decision보다 "오개념 주장의 참/거짓을 가른다"는 본질에 더 가깝다).
    "invertibility-without-1-1": PTYPE_VERIFY_CLAIM,
    # geometric_convergence — "등비급수가 수렴하는가"(오개념: 늘 수렴) 참/거짓 → verify-claim.
    "geometric-series-always-converges": PTYPE_VERIFY_CLAIM,
    # limit_equals_value — "극한값=함숫값인가"(불연속 함정) 참/거짓 → verify-claim.
    "limit-equals-function-value": PTYPE_VERIFY_CLAIM,
    # is_differentiable — "연속이면 미분가능한가"(오개념 반박) 참/거짓 → verify-claim.
    "continuity-implies-differentiability": PTYPE_VERIFY_CLAIM,
    # series_converges — "항이 0으로 가면 급수가 수렴하는가"(오개념 반박) 참/거짓 → verify-claim.
    "term-to-zero-implies-convergence": PTYPE_VERIFY_CLAIM,
    # mean_equals_median — "평균=중앙값인가" 참/거짓 → verify-claim.
    "mean-vs-median": PTYPE_VERIFY_CLAIM,
    # events_independent — "배반사건은 독립인가"(오개념 반박) 참/거짓 → verify-claim.
    "mutually-exclusive-implies-independent": PTYPE_VERIFY_CLAIM,
    # conditional_equal — "P(A|B)=P(B|A)인가"(검사 오류) 참/거짓 → verify-claim.
    "prosecutor-fallacy": PTYPE_VERIFY_CLAIM,
    # congruent_by_ratio — "닮음이면 합동인가"(오개념 반박) 참/거짓 → verify-claim.
    "similarity-vs-congruence": PTYPE_VERIFY_CLAIM,
    # dot_product_scalar — "내적이 벡터인가"(오개념 반박·실제는 스칼라) 참/거짓 → verify-claim.
    "dot-product-is-vector": PTYPE_VERIFY_CLAIM,
    # inequality_direction — "부등식 방향이 유지되는가"(음수 곱 함정) 참/거짓 → verify-claim.
    "sign-flip-in-inequality": PTYPE_VERIFY_CLAIM,
}

# ──────────────────────────────────────────────────────────────────────────
# `problem_bank_misconception_mc_v0` — 오개념 kebab(=`MisconceptionEvalMCSkeletonGenerator`의
# `TemplateKind`) → problem_type_id. `harness/misconception_mc_batch.py` `_BANDS` 45종 전수 대조
# (2026-07-30 실측 — 각 발문의 "구하시오" 대상을 확인). 대다수(42종)는 주어진 수·식을 절차대로
# 계산해 값을 내는 evaluate-expression이나, **3종은 예외**(방정식을 "푸는" 문제·경우의 수를
# "세는" 문제라 다른 인지 행동) — 아래 예외 주석 참조.
# ──────────────────────────────────────────────────────────────────────────
_MISCONCEPTION_MC_V0_KEBAB_TO_TYPE: dict[str, str] = {
    "distribution-over-power": PTYPE_EVALUATE_EXPRESSION,  # "(a+b)^2의 값을 구하시오".
    "chain-rule-inner-derivative-omitted": PTYPE_EVALUATE_EXPRESSION,  # "f'(1)의 값을 구하시오".
    "sine-distributes-over-sum": PTYPE_EVALUATE_EXPRESSION,  # "sin(A+B)의 값을 구하시오".
    "exponent-zero": PTYPE_EVALUATE_EXPRESSION,  # "값을 구하시오"(a^0 포함 식).
    "square-root-positivity": PTYPE_EVALUATE_EXPRESSION,  # "√((-p)^2)의 값을 구하시오".
    "log-distribution": PTYPE_EVALUATE_EXPRESSION,  # "log_b(...)의 값을 구하시오".
    "composite-function-commutes": PTYPE_EVALUATE_EXPRESSION,  # "(f∘g)(4)의 값을 구하시오".
    "period-of-scaled-sine": PTYPE_EVALUATE_EXPRESSION,  # "함수의 주기를 구하시오"(공식 대입).
    "translation-sign-flip": PTYPE_EVALUATE_EXPRESSION,  # "g(7)의 값을 구하시오".
    "product-rule-naive": PTYPE_EVALUATE_EXPRESSION,  # "x=6에서의 미분계수를 구하시오".
    "fraction-cancellation": PTYPE_EVALUATE_EXPRESSION,  # "값을 구하시오"(분수 계산).
    "angle-sum-non-triangle": PTYPE_EVALUATE_EXPRESSION,  # "내각의 크기의 합을 구하시오"(공식).
    "area-perimeter-confusion": PTYPE_EVALUATE_EXPRESSION,  # "직사각형의 넓이를 구하시오".
    "circle-radius-squared": PTYPE_EVALUATE_EXPRESSION,  # "원의 반지름의 길이를 구하시오".
    "gambler-fallacy": PTYPE_EVALUATE_EXPRESSION,  # "다음 시행에서 나올 확률을 구하시오".
    "fraction-addition-naive": PTYPE_EVALUATE_EXPRESSION,  # "값을 구하시오"(분수 덧셈).
    "negative-times-negative": PTYPE_EVALUATE_EXPRESSION,  # "값을 구하시오"(정수 곱셈).
    "subtract-negative-sign": PTYPE_EVALUATE_EXPRESSION,  # "값을 구하시오"(정수 뺄셈).
    "absolute-value-keeps-sign": PTYPE_EVALUATE_EXPRESSION,  # "값을 구하시오"(절댓값+정수).
    "sqrt-distributes-over-sum": PTYPE_EVALUATE_EXPRESSION,  # "√(...)의 값을 구하시오".
    "difference-of-squares-confused": PTYPE_EVALUATE_EXPRESSION,  # "x²-a²의 값을 구하시오".
    "exponent-product-multiplies": PTYPE_EVALUATE_EXPRESSION,  # "값을 구하시오"(지수 곱).
    "power-of-power-adds": PTYPE_EVALUATE_EXPRESSION,  # "(a^m)^n의 값을 구하시오".
    "negative-square-precedence": PTYPE_EVALUATE_EXPRESSION,  # "-a²+b의 값을 구하시오".
    "distribute-first-term-only": PTYPE_EVALUATE_EXPRESSION,  # "x=k일 때의 값을 구하시오"(분배).
    "negative-distribute-sign": PTYPE_EVALUATE_EXPRESSION,  # "x=k일 때의 값을 구하시오"(음수분배).
    "square-of-difference-no-cross": PTYPE_EVALUATE_EXPRESSION,  # "(a-b)²의 값을 구하시오".
    "midpoint-sum-only": PTYPE_EVALUATE_EXPRESSION,  # "중점의 좌표를 구하시오"(공식 대입).
    "scale-area-linear": PTYPE_EVALUATE_EXPRESSION,  # "넓이의 비를 구하시오"(닮음비²).
    "negative-even-power-sign": PTYPE_EVALUATE_EXPRESSION,  # "(-a)^n의 값을 구하시오".
    "combine-unlike-terms": PTYPE_EVALUATE_EXPRESSION,  # "x=k일 때의 값을 구하시오"(동류항).
    "complete-square-naive": PTYPE_EVALUATE_EXPRESSION,  # "x=k일 때의 값을 구하시오"(완전제곱).
    "conjugate-product-sum": PTYPE_EVALUATE_EXPRESSION,  # "(√a+b)(√a-b)의 값을 구하시오".
    "gcd-lcm-confused": PTYPE_EVALUATE_EXPRESSION,  # "최소공배수를 구하시오"(직접 계산).
    "decimal-mult-place": PTYPE_EVALUATE_EXPRESSION,  # "값을 구하시오"(소수 곱셈).
    "mixed-number-mult-whole": PTYPE_EVALUATE_EXPRESSION,  # "곱한 값을 구하시오"(대분수).
    "remainder-theorem-sign": PTYPE_EVALUATE_EXPRESSION,  # "나머지를 구하시오"(나머지정리 대입).
    "vieta-sign-error": PTYPE_EVALUATE_EXPRESSION,  # "두 근의 합을 구하시오"(Vieta 공식 대입).
    "trapezoid-area-no-half": PTYPE_EVALUATE_EXPRESSION,  # "사다리꼴의 넓이를 구하시오".
    "scale-volume-linear": PTYPE_EVALUATE_EXPRESSION,  # "부피비의 값을 구하시오"(닮음비³).
    "cone-volume-no-third": PTYPE_EVALUATE_EXPRESSION,  # "원뿔의 부피를 구하시오".
    "circle-area-circumference": PTYPE_EVALUATE_EXPRESSION,  # "원의 넓이를 구하시오".
    # ── 예외 3종 — "값을 구하시오"가 아니라 다른 인지 행동 ──
    # transpose-no-sign-change — "일차방정식 x+13=2의 해를 구하시오": 식이 아니라 *방정식*을
    # 풀어 미지수(해)를 구하는 문제라 solve-for-unknown(linear-equation-solving과 정확 대응).
    "transpose-no-sign-change": PTYPE_SOLVE_FOR_UNKNOWN,
    # combination-no-denominator — "서로 다른 n개에서 r개를 뽑는 조합의 수를 구하시오": 배열·
    # 선택의 경우의 수를 세는 문제 → enumerate-cases(behavior_skills와 가족 설명이 정확 대응).
    "combination-no-denominator": PTYPE_ENUMERATE_CASES,
    # same-item-permutation-no-divide — "같은 것이 있는 순열의 경우의 수를 구하시오" → 동일하게
    # enumerate-cases.
    "same-item-permutation-no-divide": PTYPE_ENUMERATE_CASES,
}

# ──────────────────────────────────────────────────────────────────────────
# `problem_bank_probability_finite_v0` — unit_codes → problem_type_id
# (`harness/finite_probability_batch.py` 4밴드 대조 — 확률형 3밴드는 unit_codes 공유).
# ──────────────────────────────────────────────────────────────────────────
_PROBABILITY_FINITE_V0_UNIT_TO_TYPE: dict[tuple[str, ...], str] = {
    # dice-sum-prob·coin-heads-prob·marble-all-red-prob — "확률을 구하시오"(전수 열거로 계산한
    # 값) → evaluate-expression(killer_v0의 Vieta·misconception_mc의 gambler-fallacy와 동일 논리
    # — 절차대로 계산해 값 하나를 낸다).
    ("PROB-FINITE-ENUM",): PTYPE_EVALUATE_EXPRESSION,
    # dice-sum-count — "경우의 수를 구하시오"(두 주사위 합이 특정 값인 경우) → enumerate-cases.
    ("COUNT-FINITE-ENUM",): PTYPE_ENUMERATE_CASES,
}

# ──────────────────────────────────────────────────────────────────────────
# `problem_bank_v1`(4건·레거시 손저작 시드) — slug → problem_type_id. 배치 흔적이 없어 발문
# 원문을 직접 읽고 판단한다(사람 판단 — acceptance가 허용하는 예외 경로).
# ──────────────────────────────────────────────────────────────────────────
_V1_SLUG_TO_TYPE: dict[str, str] = {
    # "이차방정식 ... 두 근 중 큰 근을 구하시오" — 방정식을 풀어 근 값을 구함 → solve-for-unknown.
    "wm-quad-eq-larger-root": PTYPE_SOLVE_FOR_UNKNOWN,
    # "... 두 근 중 작은 근을 구하시오" — 동일 → solve-for-unknown.
    "wm-quad-eq-smaller-root": PTYPE_SOLVE_FOR_UNKNOWN,
    # "이차함수의 그래프의 축이 직선 x=a일 때, a의 값을 구하시오" — 함수를 완전제곱꼴로 바꿔
    # 미정 좌표(축 위치)를 역으로 결정하는 문제 — solve-for-unknown보다
    # determine-coefficient("여러 조건에서 미정계수·상수를 역으로 결정" 완전제곱 스킬과 정확 대응).
    "wm-quad-fn-axis": PTYPE_DETERMINE_COEFFICIENT,
    # "이차방정식의 서로 다른 실근의 개수는?" — 판별식으로 개수를 셈 → count-solutions.
    "wm-quad-eq-root-count-mc": PTYPE_COUNT_SOLUTIONS,
}


def classify_record(corpus_name: str, record: Mapping[str, object]) -> list[str]:
    """(코퍼스명, 레코드) → `problem_type_codes` 값(0개 또는 1개·결정론).

    미태깅(빈 리스트)은 ①`corpus_name`이 이 표에 없는 코퍼스(신규 코퍼스는 매핑표부터 갱신 —
    계보 분류 코퍼스(`LINEAGE_CORPORA`)는 이 함수가 아니라 `classify_rephrased_record` 사용)
    ②밴드 식별 실패(예: `distractor_map`이 여러 오개념을 태깅해 kebab을 하나로 못 좁히는
    경우) 둘 중 하나다 — 조용한 오분류 대신 항상 빈 리스트로 정직하게 드러낸다.
    """
    ptype: str | None
    if corpus_name == CORPUS_GENERATED_V0:
        ptype = _GENERATED_V0_UNIT_TO_TYPE.get(_unit_codes(record))
    elif corpus_name == CORPUS_CONCEPTUAL_V0:
        kebab = _distractor_kebab(record)
        ptype = _CONCEPTUAL_V0_KEBAB_TO_TYPE.get(kebab) if kebab is not None else None
    elif corpus_name == CORPUS_MISCONCEPTION_MC_V0:
        kebab = _distractor_kebab(record)
        ptype = _MISCONCEPTION_MC_V0_KEBAB_TO_TYPE.get(kebab) if kebab is not None else None
    elif corpus_name == CORPUS_KILLER_V0:
        # RootAggregateSkeletonGenerator 1종뿐인 코퍼스 — unit_codes 확인은 방어적 가드일 뿐
        # (sum/product·차수 구분은 인지 행동에 영향 없어 매핑 키에 안 넣는다).
        ptype = PTYPE_EVALUATE_EXPRESSION if _unit_codes(record) == ("POLY-ROOT",) else None
    elif corpus_name == CORPUS_PROBABILITY_FINITE_V0:
        ptype = _PROBABILITY_FINITE_V0_UNIT_TO_TYPE.get(_unit_codes(record))
    elif corpus_name == CORPUS_V1:
        slug = record.get("slug")
        ptype = _V1_SLUG_TO_TYPE.get(slug) if isinstance(slug, str) else None
    elif corpus_name in _UNIT_CODE_TABLES:
        # CONT-09 — `unit_codes` 튜플이 곧 키. 표에 없는 값은 None(미태깅)으로 정직하게 드러낸다.
        ptype = _UNIT_CODE_TABLES[corpus_name].get(_unit_codes(record))
    else:
        ptype = None
    return [ptype] if ptype is not None else []


# ──────────────────────────────────────────────────────────────────────────
# `problem_bank_rephrased_v0` — 계보(lineage) 분류 (PB-07).
# ──────────────────────────────────────────────────────────────────────────

# 계보(재서술) 관계 타입 리터럴 — 정본은 `schema/enums.py` `RelationType.변형`
# (재정의 아님·오탈자 방지용, PTYPE_* 상수와 동일 원칙 — 거버넌스 테스트가 대조).
_REL_TYPE_VARIANT = "변형"


def rephrased_parent_slug(record: Mapping[str, object]) -> str | None:
    """rephrased 레코드의 `relations`에서 "변형" 계보 부모 slug 1종을 복원한다.

    S4-14/S4-18이 영속한 계보 계약: 재서술 레코드는 원본을 가리키는 "변형" 관계를 갖는다
    (2026-08-11 실측: 421/421 전건·전부 정확히 1건). 부모가 유일하게 좁혀지지 않으면
    (0건 또는 서로 다른 부모 2개 이상) `None`(미태깅)을 반환한다 — 침묵 오분류 금지
    (`_distractor_kebab`와 동일 원칙). "유사" 등 다른 관계 타입은 계보가 아니므로 무시한다.
    """
    raw = record.get("relations")
    if not isinstance(raw, list):
        return None
    parents: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        if entry.get("relation_type") != _REL_TYPE_VARIANT:
            continue
        slug = entry.get("parent_slug")
        if isinstance(slug, str):
            parents.add(slug)
    if len(parents) != 1:
        return None
    (only,) = parents
    return only


def classify_rephrased_record(
    record: Mapping[str, object], parent_types: Mapping[str, Sequence[str]]
) -> list[str]:
    """rephrased 레코드 1건을 계보로 분류 — 부모(원 생성기)의 유형을 그대로 승계한다
    (0개 또는 1개·결정론).

    재서술(LLM 발문 다양화)은 question_text 표현만 바꾸고 수치·정답·풀이 절차·unit_codes는
    부모와 동일하다(`problem_bank_rephrased_v0/_provenance.json` 계약·`test_corpus_quality.py`
    봉인) — 인지 행동이 부모와 같으므로 유형도 부모의 것이다. 이 함수가 읽는 것은 계보
    (`relations`)와 부모 색인뿐이다(문항 텍스트 파싱/추론 0·LLM 0 계약 유지).

    `parent_types`는 직접 분류 코퍼스(`TARGET_CORPORA`)의 slug → 유도 유형 색인이다
    (호출자가 구축 — `problem_type_backfill._build_parent_type_index`). 부모 slug 복원 실패·
    색인 부재는 빈 리스트(미태깅) — 건수는 백필 리포트가 정직하게 센다(침묵 누락 금지).
    """
    slug = rephrased_parent_slug(record)
    if slug is None:
        return []
    return list(parent_types.get(slug, ()))
