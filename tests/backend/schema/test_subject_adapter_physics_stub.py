"""축 (b) — Physics 어댑터 **스텁을 실제로 구현**해 필수 3종을 채워 본다 (ARCH-43 acceptance ②-b).

EOS-92 프로브는 Physics 값을 DTO에 *담아* 봤다(갈래 A). 이 파일은 한 발 더 나가 **어댑터를 실제로
구현**한다 — 필수층 `SubjectAdapter` 3메서드를 물리 의미로 채우고, 계약이 그것을 받는지 본다.

이 테스트가 **드러내는 것**(정직하게):
1. 필수 3종은 Physics로 *구현 가능*하다 — `NotImplementedError`를 강요당하는 메서드가 0이다.
   (History 어댑터라면 `evaluate_answer`·`validate_problem`도 채울 수 있지만 그것은 이 파일 범위 밖.)
2. 이 스텁은 **살아 있는 반증기**다: 누가 필수층에 `render_equation`·`parse_latex` 같은 수학 전용
   메서드를 더하면 이 스텁이 `runtime_checkable` Protocol을 **못 만족해 RED**가 난다 —
   `REQUIRED_METHODS` 상수 동결(two_tier_contract)이 "목록을 고쳐야 통과"인 것과 달리, 이쪽은
   *물리 구현이 실제로 깨진다*는 형태의 신호다.

이 테스트가 **드러내지 못하는 것**:
- **의미 왜곡**. 왜곡은 Core가 반환값·페이로드를 *해석하는 호출 지점*에서 일어나는데, 필수층의
  Core 호출자는 0이다(EOS-92 §4-2 · `ARCH-41` 추적). 호출 지점이 없으니 이 스텁으로는 왜곡을
  관측할 수 없다 — 그 축은 정적 게이트(`scripts/analysis/eos_opaque_payload_gate.py`)의 몫이다.
- **시그니처 적합성**(인자·반환 타입). `isinstance`는 메서드 *이름 존재*만 본다. 수학 어댑터는
  `TYPE_CHECKING` 대입으로 mypy가 증명하지만, 테스트 파일은 mypy 대상이 아니라 여기서는 못 한다.

hermetic — 저장소의 수학 검증기·DB·LLM을 전혀 부르지 않는다. 물리 내용은 EOS-92 §0의 P1 문항
(등가속도 운동 · v=12 m/s · s=24 m)을 그대로 쓴다.
"""

from __future__ import annotations

import re
from typing import Mapping, Sequence

import pytest

from whymath_backend.schema.subject_adapter import (
    AnswerEvaluation,
    MisconceptionSignal,
    ProblemStatement,
    ProblemValidation,
    SubjectAdapter,
)

_QUANTITY = re.compile(r"^\s*([-+]?\d+(?:\.\d+)?)\s*([A-Za-z/²^0-9]*)\s*$")


def _parse_quantity(text: str) -> tuple[float, str] | None:
    """`"12 m/s"` → (12.0, "m/s"). 물리 어댑터 내부 규약 — Core는 이 형식을 모른다."""
    m = _QUANTITY.match(text)
    return (float(m.group(1)), m.group(2)) if m else None


class PhysicsSubjectAdapter:
    """`SubjectAdapter`의 물리 스텁 — 필수 3종을 전부 *실제 판정*으로 채운다(빈 구현 없음)."""

    subject_id = "physics"

    def evaluate_answer(
        self, problem: ProblemStatement, answer: Mapping[str, str]
    ) -> AnswerEvaluation:
        """`problem.answer`("v=12 m/s; s=24 m")를 어댑터 규약으로 풀어 값+단위를 비교한다."""
        expected: dict[str, tuple[float, str]] = {}
        for part in problem.answer.split(";"):
            key, _, raw = part.partition("=")
            parsed = _parse_quantity(raw)
            if not key.strip() or parsed is None:
                return AnswerEvaluation(
                    state="unverifiable", reason=f"정답 규약 파싱 실패: {part!r}"
                )
            expected[key.strip()] = parsed
        axes: list[str] = []
        for key, exp in expected.items():
            got = _parse_quantity(answer.get(key, ""))
            if got is None:
                return AnswerEvaluation(state="unverifiable", reason=f"학생 답 파싱 실패: {key}")
            if got[1] != exp[1]:
                return AnswerEvaluation(
                    state="fail", reason=f"단위 불일치: {key} {got[1]}≠{exp[1]}"
                )
            if abs(got[0] - exp[0]) > 1e-9:
                return AnswerEvaluation(state="fail", reason=f"값 불일치: {key}")
            axes += ["numeric_value", "unit_match"]
        return AnswerEvaluation(state="pass", checked_axes=tuple(dict.fromkeys(axes)))

    def detect_misconception(
        self, student_work: str, *, top_k: int = 3
    ) -> Sequence[MisconceptionSignal]:
        """등가속도에 등속 공식(s=vt)을 적용한 흔적 — EOS-92 §0의 전형 오개념 하나만 안다."""
        signals = [s for s in ("s=vt", "48") if s in student_work.replace(" ", "")]
        if not signals:
            return ()
        return (
            MisconceptionSignal(
                code="physics-constant-velocity-formula-on-accelerated-motion",
                confidence=0.6 + 0.2 * len(signals),
                matched_signals=tuple(signals),
            ),
        )[:top_k]

    async def validate_problem(self, problem: ProblemStatement) -> ProblemValidation:
        """법칙 정합(F=m*a가 조건에 있는가)만 기계로 닫고, 이상화 전제는 잔여 축으로 남긴다."""
        laws = {c.strip() for c in problem.conditions.split(";")}
        if "F=m*a" not in laws:
            return ProblemValidation(
                state="unverifiable", reason="지배 법칙 미기재", residual_axes=("law_consistency",)
            )
        return ProblemValidation(
            state="pass", machine_axes=("law_consistency",), residual_axes=("idealization_stated",)
        )


@pytest.fixture
def p1() -> ProblemStatement:
    return ProblemStatement(
        problem_ref="physics.mechanics.uniform-acceleration-0001",
        question_text="질량 2.0 kg 물체에 6.0 N 알짜힘을 4.0초 작용. 4.0초 후 속력과 이동 거리는?",
        answer="v=12 m/s; s=24 m",
        answer_kind="physics.quantity_with_unit",
        conditions="F=m*a; v=a*t; s=0.5*a*t^2; m=2.0 kg; F=6.0 N; t=4.0 s; v0=0",
    )


def test_physics_stub_satisfies_the_required_tier_without_notimplemented() -> None:
    """필수 3종 전부 실제 구현 — 스텁 어디에도 NotImplementedError가 없다(빈 구현 강요 0)."""
    adapter = PhysicsSubjectAdapter()
    assert isinstance(adapter, SubjectAdapter)
    for name in ("evaluate_answer", "detect_misconception", "validate_problem"):
        assert callable(getattr(adapter, name))
    import inspect

    assert "NotImplementedError" not in inspect.getsource(PhysicsSubjectAdapter)


def test_physics_evaluate_answer_passes_and_fails_on_physics_semantics(
    p1: ProblemStatement,
) -> None:
    """과목 의미(단위·값)로 pass/fail이 갈린다 — DTO는 그 판정을 3상태로 그대로 담는다."""
    adapter = PhysicsSubjectAdapter()
    ok = adapter.evaluate_answer(p1, {"v": "12 m/s", "s": "24 m"})
    assert ok.state == "pass" and ok.checked_axes == ("numeric_value", "unit_match")
    wrong_unit = adapter.evaluate_answer(p1, {"v": "12 km/h", "s": "24 m"})
    assert wrong_unit.state == "fail" and "단위" in (wrong_unit.reason or "")
    wrong_value = adapter.evaluate_answer(p1, {"v": "12 m/s", "s": "48 m"})
    assert wrong_value.state == "fail"
    unparsable = adapter.evaluate_answer(p1, {"v": "빠름", "s": "24 m"})
    assert unparsable.state == "unverifiable"  # 측정 실패를 fail로 접지 않는다


def test_physics_misconception_signal_fits_the_neutral_dto() -> None:
    adapter = PhysicsSubjectAdapter()
    [sig] = adapter.detect_misconception("s = vt = 12 × 4 = 48 m")
    assert sig.code.startswith("physics-") and 0.0 <= sig.confidence <= 1.0
    assert sig.matched_signals == ("s=vt", "48")
    assert adapter.detect_misconception("s = ½at² = 24 m") == ()  # 없는 오개념을 지어내지 않는다


async def test_physics_validate_problem_closes_law_axis_and_leaves_residual(
    p1: ProblemStatement,
) -> None:
    adapter = PhysicsSubjectAdapter()
    v = await adapter.validate_problem(p1)
    assert v.state == "pass" and v.machine_axes == ("law_consistency",)
    assert v.residual_axes == ("idealization_stated",)
    no_law = p1.model_copy(update={"conditions": "m=2.0 kg; F=6.0 N"})
    assert (await adapter.validate_problem(no_law)).state == "unverifiable"


def test_stub_is_a_live_falsifier_for_math_only_required_methods() -> None:
    """필수층에 수학 전용 메서드가 더해지면 물리 스텁이 Protocol을 못 만족한다 — 그 형태의 RED를 시연.

    실제 계약을 고치지 않고, 같은 3메서드에 `parse_latex`를 더한 *가상 필수층*을 만들어 대조한다.
    이것이 이 스텁의 반증력이다: "Physics·History에도 반드시 존재하는가?"의 답이 '아니오'인
    메서드가 필수층에 들어오면 실제 과목 구현이 깨진다.
    """
    from typing import Protocol, runtime_checkable

    @runtime_checkable
    class GrownRequiredTier(Protocol):
        subject_id: str

        def evaluate_answer(self, problem: object, answer: object) -> object: ...
        def detect_misconception(self, student_work: str, *, top_k: int = 3) -> object: ...
        async def validate_problem(self, problem: object) -> object: ...
        def parse_latex(self, expr: str) -> str: ...  # 수학 전용 — 물리에는 없다

    adapter = PhysicsSubjectAdapter()
    assert isinstance(adapter, SubjectAdapter)  # 현행 필수층: 만족
    assert not isinstance(adapter, GrownRequiredTier)  # 수학 전용이 더해진 필수층: 즉시 불만족
