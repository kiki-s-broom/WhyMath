"""S4-65 — `Verifier` 응답 등급 부여 배선 테스트.

배경: `Verifier.verify`는 pass에 레거시 `MACHINE_EXHAUSTIVE`, fail·unverifiable에 `MACHINE_SAMPLED`만
찍었다(SymPy 계열 pass도 `MACHINE_EXHAUSTIVE`). `verification_tier.py`가 "SymPy 증명은 레거시 값에서
추론하지 않는다"고 못박은 원칙과 충돌하는 상태였다.

검증 축:
  ① 등록된 모든 kind가 **방법에 맞는 신규 등급**을 받는다 — 기대 등급은 이 파일에 *리터럴*로 적어
     소스의 등급표(`_CONCEPTUAL_TIERS`)를 그대로 베끼지 않는다(표가 틀려도 표를 따라가는 동어반복 차단).
  ② 닫은 축이 없는 응답(해석 불가·미등록 kind·등급 미지정 kind)은 하한 등급(`NUMERIC_SAMPLING`)이다.
  ③ **`RESIDUE_REVIEWED`·`HUMAN_REVIEWED`는 verify()가 절대 찍지 않는다**(Kiki 판정 2026-10-13) —
     교차검증이 ok여도 등급은 기계 축의 등급 그대로다.
  ④ 레거시 값이 verifier.py의 *구성된 결과*에 남지 않는다(AST — 문자열 금지 패턴이 아니다).
  ⑤ 개념형 16종에 교차검증 관점을 정의하지 않는다는 결정(설계서 §5.5)이 동결돼 있다.

변별력: 소스의 등급 부여를 레거시 상수로 되돌리면 ①②가, 교차검증 ok에 `RESIDUE_REVIEWED`를 찍으면
③이, 레거시 참조를 되살리면 ④가, 관점을 추가하면 ⑤가 RED다.
"""

from __future__ import annotations

import ast
import inspect
from dataclasses import dataclass

import pytest

from whymath_backend.l3 import verifier as verifier_module
from whymath_backend.l3.cross_verify import (
    CrossVerificationResult,
    Perspective,
    ResidueSubject,
    ResidueVerdictLabel,
)
from whymath_backend.l3.equivalent.acceptance import _CONCEPTUAL_VERIFIERS
from whymath_backend.l3.verification_tier import VerificationTier, read_verification_tier
from whymath_backend.l3.verifier import (
    _CONCEPTUAL_TIERS,
    _CROSS_VERIFY_PERSPECTIVES,
    _FLOOR_TIER,
    _VERIFIERS_V2,
    ProblemVerifyInput,
    Verifier,
    _wrap_conceptual_verifier,
)
from whymath_backend.l3.verify_answer import AnswerVerdict

_SYMBOLIC = VerificationTier.SYMBOLIC_PROOF
_DATA = VerificationTier.DETERMINISTIC_DATA
_FINITE = VerificationTier.FINITE_EXHAUSTIVE

# 레거시 두 값과 "로트 단위 게이트·인간 폴백" 두 값 — verify()가 찍어서는 안 되는 4종.
_LEGACY = frozenset({VerificationTier.MACHINE_EXHAUSTIVE, VerificationTier.MACHINE_SAMPLED})
_REVIEW = frozenset({VerificationTier.RESIDUE_REVIEWED, VerificationTier.HUMAN_REVIEWED})


@dataclass(frozen=True)
class _Case:
    """kind 1종의 실측 입력 — 맞는 답과 틀린 답, 그리고 기대 등급(리터럴)."""

    conditions: str
    right: str
    wrong: str
    tier: VerificationTier


_DICE = "space=dice(n=2,faces=6); event=sum==7"
_ARITH = "init=a(1)=7; rec=a(n+1)=a(n)+6; query=a(12)"

_CASES: dict[str, _Case] = {
    # 유한 전수 열거
    "finite_probability": _Case(_DICE, "1/6", "1/3", _FINITE),
    "finite_count": _Case(_DICE, "6", "5", _FINITE),
    # 주어진 유한 자료의 결정론 계산
    "statistical_claim": _Case("data=[1,2,3,4,5]; stat=mean", "3", "99", _DATA),
    "sequence_induction": _Case(_ARITH, "73", "74", _DATA),
    # 개념형 — SymPy 기호 연산이 결정 단계
    "real_root_count": _Case("x**2 - 1 = 0", "2", "1", _SYMBOLIC),
    "excluded_point_count": _Case("x**2 - 4 = 0", "2", "1", _SYMBOLIC),
    "root_loss_count": _Case("x**2 - x = 0", "2", "1", _SYMBOLIC),
    "extremum_count": _Case("x**3 - 3*x", "2", "3", _SYMBOLIC),
    "is_one_to_one": _Case("x**3", "1", "0", _SYMBOLIC),
    "limit_equals_value": _Case("(x**2 - 1)/(x - 1)", "0", "1", _SYMBOLIC),
    "is_differentiable": _Case("Abs(x)", "0", "1", _SYMBOLIC),
    # P3-65 — |x - 1| + (x + 2)|x + 2| 는 x = 1 에서만 꺾인다(x = -2 는 매끄러움 · 후보 2개를 세면 오답).
    "nondifferentiable_point_count": _Case("Abs(x - 1) + (x + 2)*Abs(x + 2)", "1", "2", _SYMBOLIC),
    "series_converges": _Case("1/n**2", "1", "0", _SYMBOLIC),
    "inequality_direction": _Case("-2*x < 6", "1", "0", _SYMBOLIC),
    # 개념형 — 문항이 준 수치에 대한 결정론 계산
    "mean_equals_median": _Case("1,2,3", "1", "0", _DATA),
    "events_independent": _Case("1/2,1/2,1/4", "1", "0", _DATA),
    "conditional_equal": _Case("1/2,1/2,1/3", "1", "0", _DATA),
    "dot_product_scalar": _Case("1,2,3,4", "0", "1", _DATA),
    "geometric_convergence": _Case("1/2", "1", "0", _DATA),
    "congruent_by_ratio": _Case("1", "1", "0", _DATA),
}
_KINDS = sorted(_CASES)


class _FakeCrossVerifier:
    """교차검증기 대역 — 정한 aggregate를 돌려준다(관점 세트는 검사하지 않는다)."""

    def __init__(self, aggregate: ResidueVerdictLabel) -> None:
        self.aggregate = aggregate

    def verify(
        self,
        subject: ResidueSubject,
        perspectives: tuple[Perspective, ...] | None = None,
    ) -> CrossVerificationResult:
        del perspectives
        return CrossVerificationResult(
            problem_id=subject.problem_id,
            verdicts=(),
            aggregate=self.aggregate,
            defect_class="",
            reason="fake",
        )


def _problem(kind: str, answer: str, conditions: str) -> ProblemVerifyInput:
    return ProblemVerifyInput(
        slug=f"tier-{kind}",
        question_text="테스트 발문",
        answer=answer,
        answer_kind=kind,
        conditions=conditions,
        answer_explanation="테스트 해설",
        authored_by="deterministic:test",
    )


# ── 전제 고정 ─────────────────────────────────────────────────────────
def test_case_table_covers_every_registered_kind() -> None:
    """이 파일이 훑는 kind가 레지스트리 전부다 — kind가 늘면 등급 결정 없이 지나가지 못한다."""
    assert set(_CASES) == set(_VERIFIERS_V2)
    assert len(_CASES) == 20  # 개념형 16 + 유한 전수 2 + 통계 1 + 수열 1


def test_conceptual_tier_table_matches_registry_exactly() -> None:
    """등급표 키 = `_CONCEPTUAL_VERIFIERS`에서 `finite_*`(전용 래퍼가 등급을 싣는다)를 뺀 16종."""
    expected = set(_CONCEPTUAL_VERIFIERS) - {"finite_probability", "finite_count"}
    assert set(_CONCEPTUAL_TIERS) == expected
    assert len(expected) == 16
    assert set(_CONCEPTUAL_TIERS.values()) <= {_SYMBOLIC, _DATA}


@pytest.mark.parametrize("kind", sorted(_CONCEPTUAL_TIERS))
def test_source_tier_table_agrees_with_literal_expectation(kind: str) -> None:
    """소스 표 ↔ 이 파일의 리터럴 기대 — 한쪽만 바꾸면 RED(표를 베낀 동어반복 차단)."""
    assert _CONCEPTUAL_TIERS[kind] is _CASES[kind].tier, kind


def test_floor_tier_is_what_the_legacy_sampled_value_reads_as() -> None:
    """하한 등급은 레거시 `MACHINE_SAMPLED`를 읽을 때의 해석과 같은 칸이다(의미 불변)."""
    legacy = read_verification_tier({"verification_tier": "machine_sampled"})
    assert legacy is _FLOOR_TIER
    assert _FLOOR_TIER is VerificationTier.NUMERIC_SAMPLING


# ── ① 방법에 맞는 신규 등급 ────────────────────────────────────────────
@pytest.mark.asyncio
@pytest.mark.parametrize("kind", _KINDS)
async def test_pass_input_carries_method_tier(kind: str) -> None:
    case = _CASES[kind]
    verdict = await Verifier().verify(_problem(kind, case.right, case.conditions))
    assert verdict.state != "fail", (kind, verdict.reason)
    assert verdict.machine_axes, kind  # 기계가 축을 하나라도 닫았다
    assert verdict.tier is case.tier, kind


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", _KINDS)
async def test_wrong_answer_is_fail_with_method_tier(kind: str) -> None:
    case = _CASES[kind]
    verdict = await Verifier().verify(_problem(kind, case.wrong, case.conditions))
    assert verdict.state == "fail", (kind, verdict.reason)
    assert verdict.tier is case.tier, kind


# ── ② 닫은 축이 없으면 하한 등급 ─────────────────────────────────────
@pytest.mark.asyncio
@pytest.mark.parametrize("kind", _KINDS)
async def test_unreadable_input_gets_floor_tier(kind: str) -> None:
    """해석 불가 입력 → `unverifiable` + 하한 등급 (잔여 축이 남는 finite_*도 같다)."""
    verdict = await Verifier().verify(_problem(kind, "1", "???"))
    assert verdict.state == "unverifiable", (kind, verdict.reason)
    assert verdict.tier is _FLOOR_TIER, kind


@pytest.mark.asyncio
async def test_unregistered_kind_gets_floor_tier() -> None:
    verdict = await Verifier().verify(_problem("no_such_kind", "1", "x"))
    assert verdict.state == "unverifiable"
    assert verdict.tier is _FLOOR_TIER


@pytest.mark.asyncio
async def test_kind_without_assigned_tier_falls_to_floor_never_to_exhaustive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """등급을 정하지 못한 kind(표에 없는 신규 kind)는 더 강한 등급이 아니라 *하한*으로 내려간다."""
    monkeypatch.setitem(
        _VERIFIERS_V2,
        "probe_kind",
        _wrap_conceptual_verifier(
            lambda _c, _a: AnswerVerdict(state="pass", reason=None, samples_checked=1),
            machine_axis="probe-machine",
        ),
    )
    verdict = await Verifier().verify(_problem("probe_kind", "1", "x"))
    assert verdict.state == "unverifiable"  # 잔여 축 + 교차검증기 없음
    assert verdict.tier is _FLOOR_TIER


# ── ③ RESIDUE_REVIEWED·HUMAN_REVIEWED는 찍지 않는다 ───────────────────────
@pytest.mark.asyncio
@pytest.mark.parametrize("aggregate", ["ok", "defect", "unclear"])
@pytest.mark.parametrize("kind", ["finite_probability", "finite_count", "statistical_claim"])
async def test_cross_verification_never_changes_tier_to_review_grades(
    kind: str, aggregate: ResidueVerdictLabel
) -> None:
    """교차검증이 어떤 결과든 등급은 기계 축의 등급 그대로다 — 결과는 state·audit_labels로만 흐른다."""
    case = _CASES[kind]
    without = await Verifier().verify(_problem(kind, case.right, case.conditions))
    with_cross = await Verifier(cross_verifier=_FakeCrossVerifier(aggregate)).verify(  # type: ignore[arg-type]
        _problem(kind, case.right, case.conditions)
    )
    assert with_cross.tier is without.tier is case.tier
    assert with_cross.tier not in _REVIEW
    assert f"cross_verify:{aggregate}" in with_cross.audit_labels


@pytest.mark.asyncio
async def test_cross_ok_pass_keeps_residual_axes_visible() -> None:
    """ok여도 잔여 축은 지우지 않는다 — '서술 축은 어느 등급에서도 미검증'을 응답이 계속 말한다."""
    case = _CASES["finite_probability"]
    verdict = await Verifier(cross_verifier=_FakeCrossVerifier("ok")).verify(  # type: ignore[arg-type]
        _problem("finite_probability", case.right, case.conditions)
    )
    assert verdict.state == "pass"
    assert verdict.residual_axes
    assert verdict.tier is _FINITE


# ── ④ 레거시 값이 소스에 남지 않는다 (AST) ───────────────────────────────
def _verifier_source_tree() -> ast.Module:
    return ast.parse(inspect.getsource(verifier_module))


def test_source_has_no_reference_to_legacy_or_review_tiers() -> None:
    """등급 *참조*와 *문자열 값* 양쪽에 레거시·검수 등급이 없다.

    주석·독스트링은 AST에 노드로 잡히지 않으므로(설명을 막지 않는다) 코드 참조만 센다.
    """
    tree = _verifier_source_tree()
    forbidden_names = {t.name for t in _LEGACY | _REVIEW}
    forbidden_values = {t.value for t in _LEGACY | _REVIEW}
    referenced = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "VerificationTier"
    }
    # 공허 통과 방지(스캔 0건은 실패) — 신규 등급 4종은 실제로 참조되고 있어야 한다.
    assert {
        "FINITE_EXHAUSTIVE",
        "SYMBOLIC_PROOF",
        "DETERMINISTIC_DATA",
        "NUMERIC_SAMPLING",
    } <= referenced
    assert not referenced & forbidden_names, referenced & forbidden_names
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert not literals & forbidden_values, literals & forbidden_values


# ── ⑤ 개념형 관점 미정의 결정 동결 ───────────────────────────────────────
def test_concept_perspective_decision_is_frozen() -> None:
    """개념형(SymPy) 16종에는 교차검증 관점을 정의하지 않는다(설계서 §5.5, Kiki 판정 2026-10-13).

    관점을 새로 등록하려면 이 테스트와 설계서 §5.5을 함께 고쳐야 한다 — 프롬프트 자산·감사기 레일·
    강등전 측정이 따라와야 하는 결정이라 조용히 늘어나지 않게 막는다.
    """
    assert set(_CROSS_VERIFY_PERSPECTIVES) == {
        "finite_probability",
        "finite_count",
        "statistical_claim",
        "sequence_induction",
    }
    assert not set(_CROSS_VERIFY_PERSPECTIVES) & set(_CONCEPTUAL_TIERS)
