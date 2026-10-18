"""개념형 개수 MC 생성기 테스트 — 결정론·게이트 accept·answer_kind 담김(순수·hermetic).

각 템플릿이 게이트 통과 후보를 내고(개수 SymPy 독립 검증)·오개념 개수는 fail함을 동결한다.
"""

from __future__ import annotations

import pytest

from whymath_backend.harness.misconception_mc_batch import (
    build_kebab_distractor_codes_optional,
)
from whymath_backend.l3.equivalent.acceptance import (
    EquivalenceSpec,
    evaluate_equivalent_candidate,
)
from whymath_backend.l3.equivalent.conceptual_count_mc_generator import (
    EXTREMUM_POSITIVE_COUNT,
    ConceptualCountMCSkeletonGenerator,
    CountTemplateKind,
    _build_extremum_count_pool,
    _extremum_positive_item,
)
from whymath_backend.l3.verify_answer import verify_extremum_count

_CASES: tuple[tuple[CountTemplateKind, str, tuple[str, ...]], ...] = (
    ("real_root_count", "discriminant-negative-no-real-root", ("[10공수1-02-02]",)),
    ("extremum_count", "critical-point-implies-extremum", ("[12미적Ⅰ-02-01]",)),
    ("is_one_to_one", "invertibility-without-1-1", ("[10기수2-03-03]",)),
    ("geometric_convergence", "geometric-series-always-converges", ("[12대수03-01]",)),
    ("limit_equals_value", "limit-equals-function-value", ("[12미적Ⅰ-01-01]",)),
    ("is_differentiable", "continuity-implies-differentiability", ("[12미적Ⅰ-02-02]",)),
    ("series_converges", "term-to-zero-implies-convergence", ("[12미적Ⅱ-01-04]",)),
    ("excluded_point_count", "division-by-zero", ("[9수01-03]",)),
    ("mean_equals_median", "mean-vs-median", ("[6수04-01]",)),
    (
        "events_independent",
        "mutually-exclusive-implies-independent",
        ("[12확통02-05]",),
    ),
    ("conditional_equal", "prosecutor-fallacy", ("[12확통02-04]",)),
    ("congruent_by_ratio", "similarity-vs-congruence", ("[6수03-01]",)),
    ("dot_product_scalar", "dot-product-is-vector", ("[12기하03-03]",)),
    ("inequality_direction", "sign-flip-in-inequality", ("[9수02-11]",)),
    ("root_loss_count", "root-loss-by-dividing", ("[9수02-20]",)),
)


def _spec(kebab: str, codes: tuple[str, ...]) -> EquivalenceSpec:
    return EquivalenceSpec(
        achievement_standard_codes=frozenset(codes),
        target_misconception_ids=frozenset({kebab}),
        difficulty_overall=3.0,
        answer_format=None,
    )


def _gen(template: CountTemplateKind, kebab: str) -> ConceptualCountMCSkeletonGenerator:
    return ConceptualCountMCSkeletonGenerator(
        template, build_kebab_distractor_codes_optional(kebab)
    )


def test_extremum_pool_keeps_the_approved_head_in_order() -> None:
    """P3-51 ③ — 풀 앞 24칸은 기존 승인 문항(a=1~4 × c=0~5) 그대로, 같은 순서다.

    순서가 바뀌면 같은 배치(n=24)가 다른 문항을 뽑아 승인 근거가 새 문항으로 옮겨 간다. 기대 문면은
    생성기 코드를 빌리지 않고 여기서 따로 조립한다(생성기와 같이 틀리는 일을 막는다).
    """
    expected = [
        f"삼차함수 f(x) = (x - {a})^3{f' + {c}' if c else ''} 의 극값의 개수를 구하시오."
        for a in range(1, 5)
        for c in range(0, 6)
    ]
    pool = _build_extremum_count_pool()
    assert [item.question_text for item in pool[:24]] == expected
    assert {item.answer_str for item in pool[:24]} == {"0"}


def test_extremum_pool_appends_positive_examples_after_the_head() -> None:
    """P3-51 ① — 극값이 있는 문항(정답 1·2)이 승인 머리 바로 뒤에 붙고, 정답 분포가 0 하나가 아니다."""
    pool = _build_extremum_count_pool()
    positives = pool[24 : 24 + EXTREMUM_POSITIVE_COUNT]
    assert len(positives) == EXTREMUM_POSITIVE_COUNT == 12
    assert {item.answer_str for item in positives} == {"1", "2"}
    assert len({item.conditions for item in pool}) == len(pool)  # 구조 중복 없음


def test_extremum_positive_items_are_checked_by_independent_sympy_and_misc_is_honest() -> None:
    """P3-51 ② ④ — 정답은 SymPy 독립 검증을 통과하고, 오개념 오답(임계점 수)은 정답과 다르며 fail 한다."""
    pool = _build_extremum_count_pool()
    positives = pool[24 : 24 + EXTREMUM_POSITIVE_COUNT]
    assert positives
    for item in positives:
        assert item.misc_str != item.answer_str, item.question_text
        assert verify_extremum_count(item.conditions, item.answer_str).state == "pass"
        assert verify_extremum_count(item.conditions, item.misc_str).state == "fail"


def test_extremum_positive_candidates_pass_the_acceptance_gate_with_the_misconception_tagged() -> (
    None
):
    """양성 예도 수용 게이트를 통과하고, 오답 선지 1건에만 오개념이 귀속된다(filler 미태깅)."""
    kebab = "critical-point-implies-extremum"
    gen = _gen("extremum_count", kebab)
    spec = _spec(kebab, ("[12미적Ⅰ-02-01]", "[12미적Ⅰ-02-07]"))
    candidates = [gen.generate(spec) for _ in range(24 + EXTREMUM_POSITIVE_COUNT)]
    assert all(c is not None for c in candidates)
    for c in candidates[24:]:
        assert c is not None
        verdict = evaluate_equivalent_candidate(
            spec,
            c.problem,
            provenance=c.provenance,
            conditions=c.conditions,
            answer_map=c.answer_map,
            answer_kind=c.answer_kind,
        )
        assert verdict.accepted, verdict.reasons
        (entry,) = c.problem.distractor_map or []
        assert c.problem.choices[entry.choice_index] != c.problem.answer
        assert entry.misconception_id == kebab


def test_extremum_positive_item_refuses_specs_that_would_misattribute_the_misconception() -> None:
    """P3-51 ② 보호 장치의 변별력 — 거짓 귀속이 될 설계는 조용히 문항이 되지 않고 멈춘다.

    정상 입력에서 초록인 것은 보호의 증거가 아니다. 막으려는 상태를 직접 넣어 본다:
      · 단순근만(x³-3x 꼴): 임계점 수 = 극값 수라 오개념 오답이 정답과 같다.
      · 이중근만(극값 0): 양성 예가 아니다.
    """
    simple_only = (6, ((1, 1), (-1, 1)))  # f' = 6(x-1)(x+1) → f = 2x³-6x
    double_only = (12, ((0, 2), (1, 2)))  # f' = 12x²(x-1)² → 극값 0
    for bad in (simple_only, double_only):
        with pytest.raises(ValueError):
            _extremum_positive_item(0, bad)
    good = _extremum_positive_item(0, (12, ((0, 2), (1, 1))))
    assert (good.answer_str, good.misc_str) == ("1", "2")


def test_extremum_positive_item_recounts_with_sympy_and_catches_a_duplicated_root() -> None:
    """스펙 구조만으로는 조건을 통과하지만 실제 함수는 다른 경우 — SymPy 독립 재계산이 잡는다.

    근 1 이 두 번 적힌 스펙은 구조로 세면 극값 2·임계점 3(조건 통과)이지만, 실제 f' = 12(x-1)³x 의 근은
    1(3중)·0 뿐이라 임계점은 2개다. 구조 계산만 믿으면 오개념 오답을 3 으로 잘못 달게 된다.
    """
    duplicated_root = (12, ((1, 2), (1, 1), (0, 1)))
    with pytest.raises(ValueError, match="SymPy 재계산"):
        _extremum_positive_item(0, duplicated_root)


def test_extremum_positive_explanation_uses_the_right_josa_for_the_misconception_answer() -> None:
    """해설 끝 '…세면 N(으)로 잘못 답한다' 의 조사 — 3 은 '으로', 2 는 '로' (실측 결함 교정)."""
    pool = _build_extremum_count_pool()
    by_misc = {item.misc_str: item for item in pool[24 : 24 + EXTREMUM_POSITIVE_COUNT]}
    assert "세면 3으로 잘못 답한다" in by_misc["3"].answer_explanation
    assert "세면 2로 잘못 답한다" in by_misc["2"].answer_explanation


def test_extremum_count_is_filed_under_02_07_primary() -> None:
    """P3-49 집행 지점 — 극값의 개수는 02-07(증가·감소, 극대·극소)의 행동이다.

    생성기 표(_TEMPLATE_META)가 02-01 로 돌아가면 24건이 02-01 PRIMARY 로 되살아난다(P3-43 근거 ④).
    성취기준 코드(02-01·02-07 둘 다)는 spec 이 공급하므로 여기서 건드리지 않는다.
    """
    kebab = "critical-point-implies-extremum"
    gen = _gen("extremum_count", kebab)
    spec = _spec(kebab, ("[12미적Ⅰ-02-01]", "[12미적Ⅰ-02-07]"))
    candidates = [gen.generate(spec) for _ in range(24)]
    assert all(c is not None for c in candidates)  # 0건 스캔은 통과가 아니다
    for c in candidates:
        assert c is not None
        assert [(t.concept_src_id, t.role) for t in c.concept_tags] == [
            ("H:12미적Ⅰ02-07", "PRIMARY")
        ]


@pytest.mark.parametrize("template,kebab,codes", _CASES)
def test_yields_and_deterministic(
    template: CountTemplateKind, kebab: str, codes: tuple[str, ...]
) -> None:
    a = _gen(template, kebab)
    b = _gen(template, kebab)
    spec = _spec(kebab, codes)
    out_a = [a.generate(spec) for _ in range(24)]
    out_b = [b.generate(spec) for _ in range(24)]
    assert all(c is not None for c in out_a)  # 풀 ≥24
    assert [c.conditions for c in out_a if c] == [c.conditions for c in out_b if c]  # 결정론


@pytest.mark.parametrize("template,kebab,codes", _CASES)
def test_gate_accepts_correct_count(
    template: CountTemplateKind, kebab: str, codes: tuple[str, ...]
) -> None:
    spec = _spec(kebab, codes)
    cand = _gen(template, kebab).generate(spec)
    assert cand is not None and cand.answer_kind == template
    v = evaluate_equivalent_candidate(
        spec,
        cand.problem,
        provenance=cand.provenance,
        conditions=cand.conditions,
        answer_map=cand.answer_map,
        answer_kind=cand.answer_kind,
    )
    assert v.verification == "verified"  # 정답 개수는 SymPy 독립 검증 통과


class TestS312DefectRemediation:
    """S3-12 계통 결함 회귀 봉인 — 극한 부호·확률 공리·조사(결함 상태면 실패하는 변별 테스트)."""

    def test_limit_explanation_sign_is_a_minus_b(self) -> None:
        # 감사 확정 explanation_slip 13건 — (x−a)(x−b)/(x−a)의 x→a 극한은 a−b인데 구버전은
        # b−a로 부호를 뒤집어 적었다. 해설의 극한값 문구를 SymPy 독립 계산과 대조해 봉인한다.
        import re

        import sympy

        from whymath_backend.l3.equivalent.conceptual_count_mc_generator import (
            _build_limit_equals_value_pool,
        )

        x = sympy.Symbol("x")
        pool = _build_limit_equals_value_pool()
        assert len(pool) >= 24
        for item in pool:
            expr = sympy.sympify(item.conditions.replace("f(x) = ", ""))
            pole = sympy.solve(sympy.denom(sympy.together(expr)), x)[0]
            true_limit = sympy.limit(expr, x, pole)
            match = re.search(r"극한값은 (-?\d+)", item.answer_explanation)
            assert match is not None, item.answer_explanation
            assert int(match.group(1)) == int(true_limit), (item.conditions, true_limit)

    def test_conditional_probability_axiom_guard(self) -> None:
        # 감사 확정 condition_mismatch 7건 — P(A∩B)=P(A|B)·P(B) ≤ min(P(A),P(B)) 위반 시드는
        # 거부된다(예 P(A)=1/12·P(B)=1/2·P(A|B)=1/2 → P(A∩B)=1/4>P(A)). 전 시드 공리 준수 봉인.
        import sympy

        from whymath_backend.l3.equivalent.conceptual_count_mc_generator import (
            _build_conditional_equal_pool,
        )

        pool = _build_conditional_equal_pool()
        assert len(pool) >= 24  # 가드 후에도 밴드 요청 수(24)를 채운다
        for item in pool:
            pa, pb, pab = (sympy.Rational(x) for x in item.conditions.split(","))
            assert pab * pb <= min(pa, pb), item.conditions
            assert pab * pb / pa <= 1  # P(B|A) ≤ 1(확률 공리)
        # 감사 원문 대조 확정 모순 조합(P(A)=1/12·P(B)=1/2)이 실제로 배제됐는지 표적 확인.
        assert all(item.conditions != "1/12,6/12,6/12" for item in pool)

    @pytest.mark.parametrize("template,kebab,codes", _CASES)
    def test_question_and_explanation_pass_hygiene_gate(
        self, template: CountTemplateKind, kebab: str, codes: tuple[str, ...]
    ) -> None:
        # 발문·해설 전건이 결정론 위생 게이트(조사 받침 정합 포함) 통과 — 구버전의
        # '1 가'·'-3로'·'1/2 와'·'= 5 은' 류 조사 하드코딩이면 JOSA_ERROR로 즉시 실패한다.
        from whymath_backend.l3.equivalent.rephrase_hygiene import question_hygiene_violations

        gen = _gen(template, kebab)
        spec = _spec(kebab, codes)
        for _ in range(24):
            cand = gen.generate(spec)
            assert cand is not None
            assert question_hygiene_violations(cand.problem.question_text) == (), cand.problem.slug
            assert question_hygiene_violations(cand.problem.answer_explanation or "") == (), (
                cand.problem.slug,
                cand.problem.answer_explanation,
            )


@pytest.mark.parametrize("template,kebab,codes", _CASES)
def test_gate_fails_misconception_count(
    template: CountTemplateKind, kebab: str, codes: tuple[str, ...]
) -> None:
    # 오답 선지(오개념 개수)를 answer로 바꿔치면 게이트가 fail(진짜 개념 검증).
    spec = _spec(kebab, codes)
    cand = _gen(template, kebab).generate(spec)
    assert cand is not None
    misc_index = cand.problem.distractor_map[0].choice_index  # type: ignore[index]
    misc_answer = cand.problem.choices[misc_index]  # type: ignore[index]
    v = evaluate_equivalent_candidate(
        spec,
        cand.problem.model_copy(update={"answer": misc_answer}),
        provenance=cand.provenance,
        conditions=cand.conditions,
        answer_map=cand.answer_map,
        answer_kind=cand.answer_kind,
    )
    assert v.verification == "failed"


class TestP331IsDifferentiableSolutionSteps:
    """P3-31 — is_differentiable 밴드만 풀이 단계(`solution_steps`)를 단다.

    단계는 Phase 3 계측기 'solution' 연결(해설 + 비어 있지 않은 단계)을 위해 붙는다. 다른 14밴드는
    단계가 없는 그대로여야 한다(승인 내용을 건드리지 않는다).
    """

    def test_only_the_differentiability_band_carries_steps(self) -> None:
        for template, kebab, codes in _CASES:
            cand = _gen(template, kebab).generate(_spec(kebab, codes))
            assert cand is not None
            if template == "is_differentiable":
                assert cand.solution_steps, "is_differentiable 후보에 단계가 없다"
            else:
                assert cand.solution_steps is None, f"{template}: 단계가 새어 들어왔다"

    def test_every_pool_item_chain_is_verified_correct_by_tier2(self) -> None:
        from whymath_backend.l3.equivalent.conceptual_count_mc_generator import (
            _build_is_differentiable_pool,
        )
        from whymath_backend.l3.verify_solution import verify_solution

        pool = _build_is_differentiable_pool()
        assert len(pool) >= 24
        for item in pool:
            assert item.solution_steps is not None
            result = verify_solution(list(item.solution_steps))
            assert result.n_transitions == len(item.solution_steps) - 1
            # 전이 전건 correct — incorrect·unverifiable 0건(모르는 것을 통과로 세지 않는다).
            assert result.n_correct == result.n_transitions, item.conditions
            assert not result.has_incorrect

    def test_chain_ends_at_the_nonzero_gap_of_one_sided_derivatives(self) -> None:
        from whymath_backend.l3.equivalent.conceptual_count_mc_generator import (
            _is_differentiable_steps,
        )

        steps = _is_differentiable_steps(3, 2)
        assert steps[0] == ("(Derivative(x - 3 + 2, x) - Derivative(-(x - 3) + 2, x)).doit()")
        assert steps[-1] == "2"  # 우미분계수 1 − 좌미분계수 (−1) = 2 ≠ 0 → 미분 불가(정답 0)
        assert (
            "Derivative(x - 4, x)" in _is_differentiable_steps(4, 0)[0]
        )  # c=0 은 '+ 0' 을 쓰지 않는다

    def test_branch_guard_rejects_swapped_or_wrong_branches(self) -> None:
        import sympy

        from whymath_backend.l3.equivalent.conceptual_count_mc_generator import (
            _assert_abs_branches,
        )

        x = sympy.Symbol("x")
        _assert_abs_branches(2, 1, x - 2 + 1, -(x - 2) + 1)  # 대조군 — 맞는 가지는 통과
        with pytest.raises(ValueError):
            _assert_abs_branches(2, 1, -(x - 2) + 1, x - 2 + 1)  # 좌우가 뒤바뀐 가지
        with pytest.raises(ValueError):
            _assert_abs_branches(2, 1, x - 2 + 2, -(x - 2) + 1)  # 상수항이 틀린 가지
