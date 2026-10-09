"""S4-68 ① — 교차검증 관점 조회 fail-closed.

종전엔 `_CROSS_VERIFY_PERSPECTIVES.get(kind, PROBABILITY_PERSPECTIVES)`가 등록되지 않은 kind를
확률 관점(표본공간·등확률 가정을 묻는 심사)으로 조용히 흘렸다. 실측(2026-10-09): 개념형(SymPy)
15종이 `cross_verifier` 주입 시 전부 확률 관점으로 가서 `pass`가 찍혔다.

검증 축:
  ① 관점 미등록 kind(개념형 15종)는 교차검증기를 **부르지 않고** `unverifiable`(사유 명시)이다.
  ② 등록 kind 4종은 각자의 관점 세트로 교차검증기를 부른다(확률 관점은 finite_* 2종에 *명시* 등록).
  ③ 관점 표에 죽은 키(레지스트리에 없는 kind)가 없다.

변별력: 변경 전 코드에서 ①이 RED(개념형이 `pass`), 변경 후 GREEN. ②는 finite_* 등록을 빼면 RED.
"""

from __future__ import annotations

import pytest

from whymath_backend.l3 import verifier as verifier_module
from whymath_backend.l3.cross_verify import (
    PROBABILITY_PERSPECTIVES,
    SEQUENCE_PERSPECTIVES,
    STATISTICAL_PERSPECTIVES,
    CrossVerificationResult,
    Perspective,
    ResidueSubject,
)
from whymath_backend.l3.equivalent.acceptance import _CONCEPTUAL_VERIFIERS
from whymath_backend.l3.verification_tier import VerificationTier
from whymath_backend.l3.verifier import (
    _CROSS_VERIFY_PERSPECTIVES,
    _VERIFIERS_V2,
    ProblemVerifyInput,
    Verifier,
    _DomainResult,
    _wrap_conceptual_verifier,
)
from whymath_backend.l3.verify_answer import AnswerVerdict

# 확률 관점이 *정당한* kind — 유한 표본공간 전수 열거형 2종. 나머지 개념형은 관점 미등록이다.
_FINITE_KINDS = frozenset({"finite_probability", "finite_count"})
_UNREGISTERED_CONCEPTUAL_KINDS = sorted(set(_CONCEPTUAL_VERIFIERS) - _FINITE_KINDS)


class _RecordingCrossVerifier:
    """교차검증기 대역 — 호출 여부와 넘어온 관점 세트를 기록한다(aggregate는 항상 ok)."""

    def __init__(self) -> None:
        self.calls = 0
        self.perspectives: tuple[Perspective, ...] | None = None

    def verify(
        self,
        subject: ResidueSubject,
        perspectives: tuple[Perspective, ...] | None = None,
    ) -> CrossVerificationResult:
        self.calls += 1
        self.perspectives = perspectives
        return CrossVerificationResult(
            problem_id=subject.problem_id,
            verdicts=(),
            aggregate="ok",
            defect_class="",
            reason="recording",
        )


def _problem(answer_kind: str, answer: str = "1", conditions: str = "x") -> ProblemVerifyInput:
    return ProblemVerifyInput(
        slug=f"test-{answer_kind}",
        question_text="테스트 발문",
        answer=answer,
        answer_kind=answer_kind,
        conditions=conditions,
        answer_explanation="테스트 해설",
        authored_by="corpus:TEST",
    )


def _pass_with_residual(_conditions: str, _answer: str) -> _DomainResult:
    """기계 검증 pass + 잔여 축 1개 — 교차검증 진입 *이후*의 관점 선택만 보려는 고정 도메인 결과."""
    return _DomainResult(
        verdict=AnswerVerdict(state="pass", reason=None, samples_checked=1),
        machine_axes=("probe-machine",),
        residual_axes=("probe-residual",),
    )


def test_probe_precondition_unregistered_set_is_exactly_the_15_conceptual_kinds() -> None:
    """전제 고정 — 이 테스트가 훑는 대상이 실측과 같은 15종이다(조용히 줄어들면 ①이 공허해진다)."""
    assert len(_UNREGISTERED_CONCEPTUAL_KINDS) == 15
    assert not set(_UNREGISTERED_CONCEPTUAL_KINDS) & set(_CROSS_VERIFY_PERSPECTIVES)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", _UNREGISTERED_CONCEPTUAL_KINDS)
async def test_unregistered_kind_is_unverifiable_and_never_reaches_cross_verifier(
    kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """① 개념형 15종 — 확률 관점으로 pass가 찍히지 않고, 교차검증기는 호출조차 되지 않는다."""
    monkeypatch.setitem(
        _VERIFIERS_V2,
        kind,
        _wrap_conceptual_verifier(
            lambda _c, _a: AnswerVerdict(state="pass", reason=None, samples_checked=1),
            machine_axis="probe-machine",
            residual_axis="probe-residual",
        ),
    )
    recorder = _RecordingCrossVerifier()
    verdict = await Verifier(cross_verifier=recorder).verify(_problem(kind))  # type: ignore[arg-type]

    assert verdict.state == "unverifiable", kind
    assert recorder.calls == 0, kind
    assert "교차검증 관점이 없음" in (verdict.reason or ""), kind
    assert kind in (verdict.reason or ""), kind
    # 기계가 닫은 축·못 닫은 축은 그대로 보존된다(관점이 없다고 기계 결과를 지우지 않는다).
    assert verdict.machine_axes == ("probe-machine",)
    assert verdict.residual_axes == ("probe-residual",)
    assert verdict.tier == VerificationTier.MACHINE_EXHAUSTIVE


@pytest.mark.asyncio
async def test_real_conceptual_input_end_to_end_is_unverifiable() -> None:
    """① 대역 없이 실제 입력(real_root_count) — 종전엔 확률 관점 pass, 이제는 unverifiable."""
    recorder = _RecordingCrossVerifier()
    verdict = await Verifier(cross_verifier=recorder).verify(  # type: ignore[arg-type]
        _problem("real_root_count", answer="2", conditions="x**2 - 1 = 0")
    )
    assert verdict.state == "unverifiable"
    assert recorder.calls == 0
    assert "SymPy 기호/수치 검산" in verdict.machine_axes
    assert "발문↔SymPy 조건 정합" in verdict.residual_axes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("finite_probability", PROBABILITY_PERSPECTIVES),
        ("finite_count", PROBABILITY_PERSPECTIVES),
        ("statistical_claim", STATISTICAL_PERSPECTIVES),
        ("sequence_induction", SEQUENCE_PERSPECTIVES),
    ],
)
async def test_registered_kind_uses_its_own_perspectives(
    kind: str, expected: tuple[Perspective, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    """② 등록 kind 4종 — 각자의 관점 세트(동일 객체)로 교차검증기를 부르고 pass가 된다."""
    monkeypatch.setitem(_VERIFIERS_V2, kind, _pass_with_residual)
    recorder = _RecordingCrossVerifier()
    verdict = await Verifier(cross_verifier=recorder).verify(_problem(kind))  # type: ignore[arg-type]

    assert verdict.state == "pass", kind
    assert recorder.calls == 1, kind
    assert recorder.perspectives is expected, kind


def test_perspective_table_has_no_dead_keys() -> None:
    """③ 관점 표의 모든 키는 v2 레지스트리에 있는 kind다(오타·삭제된 kind의 잔재를 막는다)."""
    assert set(_CROSS_VERIFY_PERSPECTIVES) <= set(_VERIFIERS_V2)


def test_fallback_default_is_gone_from_source() -> None:
    """폴백 기본값 `PROBABILITY_PERSPECTIVES`가 더는 조회식의 기본 인자로 쓰이지 않는다.

    행동 테스트(①)가 본체이고, 이것은 누가 `.get(kind, <기본값>)`을 되살리는 형태 회귀를
    값이 아니라 **조회식의 인자 개수**로 잡는다(AST — 문자열 금지 패턴이 아니라 구성된 결과 검사).
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(verifier_module))
    lookups = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "_CROSS_VERIFY_PERSPECTIVES"
    ]
    assert lookups, "관점 표 조회식을 못 찾았다 — 이 가드가 공허해졌다(스캔 0건은 실패)"
    assert all(len(call.args) == 1 for call in lookups), "관점 조회에 기본값 폴백이 되살아났다"
