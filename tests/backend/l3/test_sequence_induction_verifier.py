"""S4-66 — `sequence_induction`의 Verifier 통합·교차검증 관점 테스트.

검증 축:
  ① 등록: `_VERIFIERS_V2`에 있고, 교차검증 관점이 **확률 관점 폴백이 아니라 명시 등록**이다.
  ② `_DomainResult` 후행 기본값 필드(`machine_value_exact`·`tier`)가 기존 생성처를 깨지 않고,
     도메인 등급이 `VerificationVerdict.tier`에 실린다(None이면 종전 상수).
  ③ 관점 ①의 판정기는 `Fraction` 정확 일치다 — 같은 쌍을 통계 판정기(`isclose`)는 통과시킨다.
  ④ 가시 필드 은닉: ①은 발문만, ②는 발문+정답, ③은 발문+기계 정의(결과 값 없음).
  ⑤ 프롬프트 자산 6개가 정본에 있고 감사기 레일 매핑이 닫혀 있다.
  ⑥ 어댑터 계약(ProblemVerifyInput 5필드·VerificationVerdict)은 바뀌지 않았다.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import fields
from pathlib import Path

import pytest

from whymath_backend.harness import qa_pipeline as qp
from whymath_backend.harness.prompt_asset_audit import L3_PROMPT_RAILS, audit_generation_prompts
from whymath_backend.l3.cross_verify import (
    SEQUENCE_PERSPECTIVES,
    STATISTICAL_PERSPECTIVES,
    CrossVerificationResult,
    CrossVerifier,
    Perspective,
    ResidueSubject,
    _judge_seq_reconstruct,
    _judge_stat_reconstruct,
    deterministic_author,
)
from whymath_backend.l3.models import GenerationResult, RoutingDecision
from whymath_backend.l3.prompt_assets import REQUIRED_ASSET_IDS, asset_registry, prompt_text
from whymath_backend.l3.verification_tier import VerificationTier
from whymath_backend.l3.verifier import (
    _CROSS_VERIFY_PERSPECTIVES,
    _VERIFIERS_V2,
    ProblemVerifyInput,
    Verifier,
    _DomainResult,
)

ARITH = "init=a(1)=7; rec=a(n+1)=a(n)+6; query=a(12)"
CLOSED = "init=a(1)=3; rec=a(n+1)=5*a(n); query=closed(a(n)=3*5^(n-1), upto=12)"
DOUBLE_PLUS_ONE = "init=a(1)=1; rec=a(n+1)=2*a(n)+1; query=a(30)"
QUESTION = "수열 {aₙ}이 다음 조건을 만족시킨다.\n(가) a₁ = 7\n(나) aₙ₊₁ = aₙ + 6 (n ≥ 1)\na₁₂의 값을 구하시오."


def _problem(conditions: str, answer: str) -> ProblemVerifyInput:
    return ProblemVerifyInput(
        slug="test-sequence-induction",
        question_text=QUESTION,
        answer=answer,
        answer_kind="sequence_induction",
        conditions=conditions,
        answer_explanation="점화식에 따라 첫째항 7에 6을 11번 더한 값이다.",
        authored_by=deterministic_author("sequence-test"),
    )


class _SpyCrossVerifier:
    """교차검증기 대역 — 받은 대상·관점을 기록하고 정한 aggregate를 돌려준다."""

    def __init__(self, aggregate: str = "ok") -> None:
        self.aggregate = aggregate
        self.subjects: list[ResidueSubject] = []
        self.perspective_sets: list[Sequence[Perspective] | None] = []

    def verify(
        self, subject: ResidueSubject, perspectives: Sequence[Perspective] | None = None
    ) -> CrossVerificationResult:
        self.subjects.append(subject)
        self.perspective_sets.append(perspectives)
        return CrossVerificationResult(
            problem_id=subject.problem_id,
            verdicts=(),
            aggregate=self.aggregate,  # type: ignore[arg-type]
            defect_class="",
            reason="spy",
        )


# ── ① 등록 ───────────────────────────────────────────────────────────
def test_registered_with_explicit_perspectives_not_probability_fallback() -> None:
    assert "sequence_induction" in _VERIFIERS_V2
    assert _CROSS_VERIFY_PERSPECTIVES["sequence_induction"] is SEQUENCE_PERSPECTIVES
    assert len(SEQUENCE_PERSPECTIVES) == 3


@pytest.mark.asyncio
async def test_cross_verifier_is_called_with_sequence_perspectives() -> None:
    spy = _SpyCrossVerifier("ok")
    await Verifier(cross_verifier=spy).verify(_problem(ARITH, "73"))  # type: ignore[arg-type]
    assert spy.perspective_sets == [SEQUENCE_PERSPECTIVES]


# ── ② 판정·등급·재료 ──────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_pass_without_cross_verifier_is_unverifiable_with_domain_tier() -> None:
    verdict = await Verifier().verify(_problem(ARITH, "73"))
    assert verdict.state == "unverifiable"
    assert verdict.tier is VerificationTier.DETERMINISTIC_DATA
    assert verdict.machine_axes == ("점화식 정확 산술 실행",)
    assert "발문↔점화식 정합" in verdict.residual_axes
    assert "cross_verifier" in (verdict.reason or "")


@pytest.mark.asyncio
async def test_fail_carries_domain_tier_and_reason() -> None:
    verdict = await Verifier().verify(_problem(DOUBLE_PLUS_ONE, "1073741824"))
    assert verdict.state == "fail"
    assert verdict.tier is VerificationTier.DETERMINISTIC_DATA
    assert "불일치" in (verdict.reason or "")


@pytest.mark.asyncio
async def test_unverifiable_input_claims_no_machine_axis() -> None:
    """형식 오류·범위 초과·답 판독 불가는 기계가 닫은 축이 없다 — 닫았다고 주장하지 않는다."""
    for conditions, answer in (
        ("init=a(1)=1; rec=a(n+1)=a(n)+0.5; query=a(2)", "1"),  # 형식 오류
        ("init=a(1)=2; rec=a(n+1)=a(n)^2; query=a(17)", "1"),  # 범위 초과
        (ARITH, "약 73"),  # 답 판독 불가
    ):
        verdict = await Verifier(cross_verifier=_SpyCrossVerifier()).verify(  # type: ignore[arg-type]
            _problem(conditions, answer)
        )
        assert verdict.state == "unverifiable", conditions
        assert verdict.machine_axes == ()
        assert verdict.residual_axes == ()
        assert verdict.tier is VerificationTier.MACHINE_SAMPLED  # 종전 상수 — 도메인 등급 아님


def test_domain_result_for_unverifiable_claims_no_axis_at_the_domain_boundary() -> None:
    """`Verifier`는 잔여 축이 비면 기계 축을 응답에 싣지 않아 위 테스트로는 도메인 결과의 허위 주장이
    보이지 않는다 — 도메인 verifier 출력 자체를 직접 본다(`machine_axes`가 닫힌 축의 목록이므로)."""
    verify = _VERIFIERS_V2["sequence_induction"]
    for conditions, answer in (
        ("init=a(1)=1; rec=a(n+1)=a(n)+0.5; query=a(2)", "1"),
        ("init=a(1)=2; rec=a(n+1)=a(n)^2; query=a(17)", "1"),
        (ARITH, "약 73"),
    ):
        result = verify(conditions, answer)
        assert result.verdict.state == "unverifiable", conditions
        assert result.machine_axes == ()
        assert result.residual_axes == ()
        assert result.tier is None
        assert result.machine_value_exact == ""
    passed = verify(ARITH, "73")
    assert passed.machine_axes == ("점화식 정확 산술 실행",)
    assert passed.machine_value_exact == "73"


def test_sequence_induction_is_excluded_from_equation_dsl_closure_check(tmp_path: Path) -> None:
    """등식 DSL 폐쇄 검사(축 2)가 수열 DSL을 위반으로 세지 않는다 — 제외 목록에서 빠지면 RED.

    기존 제외 목록 테스트는 집합 자신으로 파라미터를 만들어(`sorted(_NON_EQUATION_...)`) 항목이
    빠지면 케이스도 함께 사라진다. 그래서 이 항목은 명시적으로 고정한다.
    """
    assert "sequence_induction" in qp._NON_EQUATION_DSL_ANSWER_KINDS

    def run(answer_kind: str) -> qp.AxisResult:
        bank = tmp_path / answer_kind / "problem_bank_a"
        bank.mkdir(parents=True)
        row = {"slug": "p", "verify": {"answer_kind": answer_kind, "conditions": ARITH}}
        (bank / "problems.jsonl").write_text(json.dumps(row, ensure_ascii=False) + "\n", "utf-8")
        return qp._axis_equivalence_canonicalize(tmp_path / answer_kind)

    excluded = run("sequence_induction")
    assert excluded.status == "ok"
    assert excluded.detail == {"total_conditions_checked": 0, "violations": 0}
    # 대조군: 같은 문자열도 제외 대상이 아닌 answer_kind이면 등식 DSL 위반으로 잡힌다.
    control = run("real_root_count")
    assert control.status == "gate_fail"
    assert control.detail == {"total_conditions_checked": 1, "violations": 1}


@pytest.mark.asyncio
async def test_cross_verifier_receives_exact_value_and_definition_only() -> None:
    spy = _SpyCrossVerifier("ok")
    verdict = await Verifier(cross_verifier=spy).verify(_problem(ARITH, "73"))  # type: ignore[arg-type]
    assert verdict.state == "pass"
    assert verdict.tier is VerificationTier.DETERMINISTIC_DATA
    assert verdict.audit_labels == ["cross_verify:ok"]
    subject = spy.subjects[0]
    assert subject.machine_value_exact == "73"
    assert subject.machine_value is None  # float 경로는 쓰지 않는다
    assert "점화식" in subject.machine_model_ko
    assert "73" not in subject.machine_model_ko  # 정의만 — 결과 값은 관점 ③에 새지 않는다
    assert subject.data == ARITH


@pytest.mark.asyncio
async def test_closed_pass_keeps_finite_exhaustive_tier_through_cross_verify() -> None:
    spy = _SpyCrossVerifier("ok")
    verdict = await Verifier(cross_verifier=spy).verify(_problem(CLOSED, "1"))  # type: ignore[arg-type]
    assert verdict.state == "pass"
    assert verdict.tier is VerificationTier.FINITE_EXHAUSTIVE
    assert "모든 n에 대한 일반 주장" in verdict.residual_axes  # pass여도 잔여 축은 남는다
    assert spy.subjects[0].machine_value_exact == "1"


@pytest.mark.asyncio
@pytest.mark.parametrize("aggregate", ["defect", "unclear"])
async def test_cross_verify_defect_or_unclear_is_not_pass(aggregate: str) -> None:
    verdict = await Verifier(cross_verifier=_SpyCrossVerifier(aggregate)).verify(  # type: ignore[arg-type]
        _problem(ARITH, "73")
    )
    assert verdict.state == ("fail" if aggregate == "defect" else "unverifiable")
    assert verdict.tier is VerificationTier.DETERMINISTIC_DATA


def test_domain_result_new_fields_have_backward_compatible_defaults() -> None:
    """후행 기본값 필드 — 기존 생성처(키워드 인자)가 그대로 동작한다."""
    names = [f.name for f in fields(_DomainResult)]
    assert names[-2:] == ["machine_value_exact", "tier"]
    default = {f.name: f.default for f in fields(_DomainResult)}
    assert default["machine_value_exact"] == ""
    assert default["tier"] is None
    ResidueSubject(  # 기존 생성처 형태 — machine_value_exact 없이 구성된다
        problem_id="p",
        question_text="q",
        answer="a",
        answer_explanation="e",
        machine_model_ko="m",
        machine_total=1,
        machine_favorable=1,
        authored_by="x",
    )


def test_adapter_contract_is_unchanged() -> None:
    assert list(ProblemVerifyInput.model_fields) == [
        "slug",
        "question_text",
        "answer",
        "answer_kind",
        "conditions",
        "answer_explanation",
        "authored_by",
    ]


@pytest.mark.asyncio
async def test_existing_domains_keep_constant_tiers() -> None:
    """tier=None 도메인(기존 전부)은 종전 상수 등급 그대로다 — 이 슬라이스가 바꾼 것이 아니다."""
    stat = await Verifier().verify(
        ProblemVerifyInput(
            slug="s",
            question_text="q",
            answer="3",
            answer_kind="statistical_claim",
            conditions="data=[1,2,3,4,5]; stat=mean",
        )
    )
    assert stat.tier is VerificationTier.MACHINE_EXHAUSTIVE
    stat_fail = await Verifier().verify(
        ProblemVerifyInput(
            slug="s",
            question_text="q",
            answer="99",
            answer_kind="statistical_claim",
            conditions="data=[1,2,3,4,5]; stat=mean",
        )
    )
    assert stat_fail.tier is VerificationTier.MACHINE_SAMPLED


# ── ③ 정확 일치 판정기 ───────────────────────────────────────────────
def _subject(**overrides: object) -> ResidueSubject:
    base: dict[str, object] = {
        "problem_id": "p",
        "question_text": QUESTION,
        "answer": "73",
        "answer_explanation": "",
        "machine_model_ko": "정의",
        "machine_total": 0,
        "machine_favorable": 0,
        "authored_by": deterministic_author("sequence-test"),
        "machine_value_exact": "73",
    }
    base.update(overrides)
    return ResidueSubject(**base)  # type: ignore[arg-type]


def test_reconstruct_judge_is_exact_where_statistical_judge_is_tolerant() -> None:
    """1073741823 vs 1073741824 — 통계 판정기(isclose)는 ok, 수열 판정기(==)는 defect."""
    stat_subject = _subject(machine_value=1073741823.0)
    assert (
        _judge_stat_reconstruct(stat_subject, {"value": 1073741824}).verdict == "ok"
    )  # 결함의 증거
    seq_subject = _subject(machine_value_exact="1073741823")
    assert _judge_seq_reconstruct(seq_subject, {"value": 1073741823}).verdict == "ok"
    off_by_one = _judge_seq_reconstruct(seq_subject, {"value": 1073741824})
    assert off_by_one.verdict == "defect"
    assert off_by_one.defect_class == "model_mismatch"
    assert off_by_one.principle == "sequence_reconstruction"


@pytest.mark.parametrize(
    ("machine", "llm", "verdict"),
    [
        ("73", "73", "ok"),
        ("73", "74", "defect"),
        ("73", "146/2", "ok"),  # 같은 유리수의 다른 표기
        ("1/2", "0.5", "unclear"),  # 소수는 정확하지 않아 읽지 않는다
        ("[1, 3, 6]", [1, 3, 6], "ok"),
        ("[1, 3, 6]", ["1", "3", "6"], "ok"),
        ("[1, 3, 6]", [1, 3, 7], "defect"),
        ("[1, 3, 6]", [1, 3], "defect"),  # 길이 불일치
        ("[1, 3, 6]", 10, "defect"),  # 스칼라 vs 목록
        ("1", "1", "ok"),  # closed
        ("1", "0", "defect"),
    ],
)
def test_reconstruct_judge_cases(machine: str, llm: object, verdict: str) -> None:
    result = _judge_seq_reconstruct(
        _subject(machine_value_exact=machine), {"value": llm, "reason": "r"}
    )
    assert result.verdict == verdict


def test_reconstruct_judge_unclear_paths_are_measurement_failures() -> None:
    subject = _subject()
    assert _judge_seq_reconstruct(subject, {"value": None, "reason": "모호"}).verdict == "unclear"
    assert _judge_seq_reconstruct(subject, {}).verdict == "unclear"
    assert _judge_seq_reconstruct(subject, {"value": "abc"}).defect_class == "value_unparsed"
    missing = _judge_seq_reconstruct(_subject(machine_value_exact=""), {"value": 73})
    assert (missing.verdict, missing.defect_class) == ("unclear", "machine_value_missing")


# ── ④ 가시 필드 은닉 ─────────────────────────────────────────────────
def test_visible_fields_are_distinct_and_hiding_is_real() -> None:
    reconstruct, falsify, grounding = SEQUENCE_PERSPECTIVES
    assert reconstruct.visible_fields == {"question_text"}
    assert falsify.visible_fields == {"question_text", "answer"}
    assert grounding.visible_fields == {"question_text", "machine_model_ko"}
    subject = _subject(
        answer="ANSWER_SENTINEL_9137",
        answer_explanation="EXPLANATION_SENTINEL_5521",
        machine_model_ko="MODEL_SENTINEL_7740",
        machine_value_exact="73",
    )
    rendered_reconstruct = reconstruct.render(subject)
    assert "ANSWER_SENTINEL_9137" not in rendered_reconstruct
    assert "MODEL_SENTINEL_7740" not in rendered_reconstruct
    assert "EXPLANATION_SENTINEL_5521" not in rendered_reconstruct
    assert QUESTION in rendered_reconstruct
    rendered_falsify = falsify.render(subject)
    assert "ANSWER_SENTINEL_9137" in rendered_falsify
    assert "MODEL_SENTINEL_7740" not in rendered_falsify
    rendered_grounding = grounding.render(subject)
    assert "MODEL_SENTINEL_7740" in rendered_grounding
    assert "ANSWER_SENTINEL_9137" not in rendered_grounding
    assert "EXPLANATION_SENTINEL_5521" not in rendered_grounding


def test_sequence_perspectives_pass_independence_construction() -> None:
    """구성 시점 독립성 강제(원리·프롬프트·가시 필드 상이)를 실제 생성자로 통과한다."""

    class _Sink:
        def record(self, fields: dict[str, object]) -> None:
            del fields

    class _Unused:
        async def generate(
            self,
            prompt: str,
            system: str,
            decision: RoutingDecision,
            *,
            images: Sequence[str] | None = None,
            temperature: float | None = None,
            json_schema: Mapping[str, object] | None = None,
            seed: int | None = None,
        ) -> GenerationResult:
            raise AssertionError("구성만으로 호출되면 안 된다")

    CrossVerifier(_Unused(), perspectives=SEQUENCE_PERSPECTIVES, trace=_Sink())  # type: ignore[arg-type]
    assert {p.principle for p in SEQUENCE_PERSPECTIVES}.isdisjoint(
        {p.principle for p in STATISTICAL_PERSPECTIVES}
    )


def test_end_to_end_with_scripted_provider_exact_defect() -> None:
    """실제 CrossVerifier로 K=3을 돌려 ①의 정수 오답이 defect로 집계되는지 본다(라이브 0)."""

    class _Scripted:
        def __init__(self, responses: Sequence[str]) -> None:
            self._responses = list(responses)

        async def generate(
            self,
            prompt: str,
            system: str,
            decision: RoutingDecision,
            *,
            images: Sequence[str] | None = None,
            temperature: float | None = None,
            json_schema: Mapping[str, object] | None = None,
            seed: int | None = None,
        ) -> GenerationResult:
            return GenerationResult(self._responses.pop(0))

    class _Sink:
        def record(self, fields: dict[str, object]) -> None:
            del fields

    ok = json.dumps({"verdict": "ok", "reason": "문제 없음"}, ensure_ascii=False)
    subject = _subject(machine_value_exact="1073741823")

    def run(llm_value: int) -> CrossVerificationResult:
        provider = _Scripted([json.dumps({"value": llm_value, "reason": "전개"}), ok, ok])
        verifier = CrossVerifier(provider, perspectives=SEQUENCE_PERSPECTIVES, trace=_Sink())  # type: ignore[arg-type]
        return verifier.verify(subject)

    assert run(1073741823).aggregate == "ok"
    wrong = run(1073741824)
    assert wrong.aggregate == "defect"
    assert wrong.defect_class == "sequence_reconstruction:model_mismatch"


# ── ⑤ 프롬프트 자산 ──────────────────────────────────────────────────
SEQUENCE_ASSET_IDS = tuple(
    f"l3.cross_verify.sequence_{kind}_{role}"
    for kind in ("reconstruct", "falsify", "grounding")
    for role in ("system", "user")
)


def test_six_sequence_prompt_assets_exist_and_are_registered() -> None:
    assert len(SEQUENCE_ASSET_IDS) == 6
    registry = asset_registry()
    for asset_id in SEQUENCE_ASSET_IDS:
        assert asset_id in REQUIRED_ASSET_IDS
        assert asset_id in registry
        assert prompt_text(asset_id).strip()
        assert asset_id in L3_PROMPT_RAILS  # 감사기 레일 매핑이 닫혀 있다


def test_reconstruct_system_prompt_declares_answer_hidden() -> None:
    assert "정답은 주어지지 않는다" in prompt_text("l3.cross_verify.sequence_reconstruct_system")


def test_prompt_audit_passes_for_sequence_assets_and_catches_answer_leak() -> None:
    """감사기가 수열 재구성 자산의 정답 은닉을 실제로 본다 — 누출을 주입하면 RED."""
    clean = {a: prompt_text(a) for a in SEQUENCE_ASSET_IDS}
    # 감사기는 선언표·자산의 합집합을 순회하므로 수열 자산 6개만 보도록 선언표를 좁힌다.
    rails = {a: L3_PROMPT_RAILS[a] for a in SEQUENCE_ASSET_IDS}
    items = audit_generation_prompts(clean, rails=rails)
    assert [item.asset_id for item in items] == sorted(SEQUENCE_ASSET_IDS)  # 6건 전수 감사됨
    assert not [v for item in items for v in item.violations]

    leaked = dict(clean)
    leaked["l3.cross_verify.sequence_reconstruct_user"] += "\n\n[제시된 정답]\n{{ANSWER}}"
    assert (
        leaked["l3.cross_verify.sequence_reconstruct_user"]
        != clean["l3.cross_verify.sequence_reconstruct_user"]
    )
    assert any(item.violations for item in audit_generation_prompts(leaked, rails=rails))

    undeclared = dict(clean)
    sysid = "l3.cross_verify.sequence_reconstruct_system"
    undeclared[sysid] = clean[sysid].replace("정답은 주어지지 않는다", "정답은 알려 준다")
    assert undeclared[sysid] != clean[sysid]
    assert any(item.violations for item in audit_generation_prompts(undeclared, rails=rails))


# ── ⑦ 경계 — 코어(cross_verify)는 어댑터(sequence_induction)를 import하지 않는다 ─────────
def test_exact_value_parser_has_a_single_source_and_core_does_not_import_adapter() -> None:
    """정확값 파서는 CORE 모듈 한 곳에만 있다 — 검증기와 판정기가 같은 함수를 쓴다.

    `cross_verify`(CORE)가 `sequence_induction`(ADAPTER)을 직접 import하면 코어→어댑터 의존이
    생긴다(경계 탐침 `tests/infra`가 CI에서 잡는 결함 — 이 슬라이스가 한 번 실제로 만들었다).
    """
    import ast
    import inspect

    from whymath_backend.l3 import cross_verify, exact_value, sequence_induction

    assert cross_verify.parse_exact_value is exact_value.parse_exact_value
    assert sequence_induction.parse_exact_value is exact_value.parse_exact_value
    assert sequence_induction.format_exact_value is exact_value.format_exact_value
    tree = ast.parse(inspect.getsource(cross_verify))
    imported = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "whymath_backend.l3.sequence_induction" not in imported
    stdlib_only = ast.parse(inspect.getsource(exact_value))
    modules = {
        alias.name.split(".")[0]
        for node in ast.walk(stdlib_only)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(stdlib_only)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert modules <= {"__future__", "re", "fractions"}, modules
