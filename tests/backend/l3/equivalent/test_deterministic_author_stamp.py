"""결정론 생성기 서명 전수 가드 (PB-17 ④) — 생성기를 추가하고 서명을 빼먹으면 RED.

PB-15는 생성자≠검증자 가드를 3상태로 바꿨지만 서명을 찍는 쪽은 LLM 생성기뿐이었다. 결정론
스켈레톤 생성기는 `@deterministic_generator`(l3/equivalent/generator.py)로 생성 시점에 서명한다.
이 파일은 그 데코레이터가 **전수** 부착됐는지를 *역할 기반*으로 검사한다 — 클래스 이름 목록이
아니라 "`generate(self, spec)`를 가진 `l3/equivalent` 클래스"를 실측해, 새 생성기가 추가되면
자동으로 대상이 된다. 스캔 0건·하한 미달은 실패다(공허 통과 금지).

CI 배선: 이 파일은 `corpus_authoring` 마커가 **없다** → backend 잡(`-m "not corpus_authoring"`)이
모든 PR에서 돌린다(생성기를 안 건드린 PR 포함).
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from collections.abc import Iterable
from pathlib import Path
from types import ModuleType

import pytest

import whymath_backend.l3.equivalent as equivalent_pkg
from whymath_backend.l3.cross_verify import deterministic_author
from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
from whymath_backend.l3.equivalent.binomial_distribution_skeleton_generator import (
    BinomialDistributionSkeletonGenerator,
)
from whymath_backend.l3.equivalent.generator import (
    DETERMINISTIC_GENERATOR_MARK,
    CandidateProblem,
    EquivalentProblemGenerator,
    ScriptedGenerator,
    deterministic_generator,
    deterministic_generator_name,
)
from whymath_backend.l3.equivalent.llm_generator import LLMEquivalentProblemGenerator

# 결정론 서명 대상이 **아닌** generate() 보유 클래스 — 사유를 명시한 닫힌 목록이다.
#   Protocol: 좌석 계약(구현 없음) · Scripted: 준비된 후보를 재생하는 테스트 대역(생성 주체가 아님)
#   LLM: `llm:<모델 id>`를 스스로 찍는다(PB-15) — 결정론으로 표시되면 오히려 위반
_NOT_DETERMINISTIC = {
    EquivalentProblemGenerator,
    ScriptedGenerator,
    LLMEquivalentProblemGenerator,
}
_MIN_GENERATORS = 55  # 2026-10 실측 60종 — 대량 삭제·스캔 실패를 잡는 하한(증가는 자유).


def _equivalent_modules() -> list[ModuleType]:
    return [
        importlib.import_module(f"{equivalent_pkg.__name__}.{info.name}")
        for info in pkgutil.iter_modules(equivalent_pkg.__path__)
    ]


def _generator_classes(modules: Iterable[ModuleType]) -> list[type]:
    """역할 기반 발견 — 모듈에서 정의된, `generate(self, spec)`를 가진 클래스."""
    found: list[type] = []
    for module in modules:
        for value in vars(module).values():
            if not (isinstance(value, type) and value.__module__ == module.__name__):
                continue
            method = vars(value).get("generate")
            if method is None or not callable(method):
                continue
            params = list(inspect.signature(method).parameters)
            if params[:2] == ["self", "spec"]:
                found.append(value)
    return found


def test_scan_is_not_vacuous() -> None:
    classes = _generator_classes(_equivalent_modules())
    assert len(classes) >= _MIN_GENERATORS + len(
        _NOT_DETERMINISTIC
    ), f"생성기 클래스 스캔 {len(classes)}건 — 하한 미달(스캔 실패 또는 대량 삭제)"


def test_every_deterministic_generator_class_is_stamped() -> None:
    """생성기 목록 대비 서명 미부착 0건 — 새 생성기에 데코레이터를 빼먹으면 여기서 RED."""
    unstamped = [
        f"{cls.__module__.rsplit('.', 1)[-1]}.{cls.__name__}"
        for cls in _generator_classes(_equivalent_modules())
        if cls not in _NOT_DETERMINISTIC and DETERMINISTIC_GENERATOR_MARK not in vars(cls)
    ]
    assert unstamped == [], f"@deterministic_generator 미부착 생성기: {unstamped}"


def test_stamped_generate_is_the_wrapper_and_name_matches_module() -> None:
    """표식만 심고 generate 를 안 감싼 위장도 막는다 — 래퍼 여부와 서명 이름을 함께 본다."""
    stamped = [
        cls for cls in _generator_classes(_equivalent_modules()) if cls not in _NOT_DETERMINISTIC
    ]
    assert stamped, "스캔 0건"
    for cls in stamped:
        assert hasattr(vars(cls)["generate"], "__wrapped__"), f"{cls.__name__}: generate 미래핑"
        assert vars(cls)[DETERMINISTIC_GENERATOR_MARK] == deterministic_generator_name(cls)
        assert vars(cls)[DETERMINISTIC_GENERATOR_MARK] == cls.__module__.rsplit(".", 1)[-1]


def test_non_deterministic_seats_are_not_marked_deterministic() -> None:
    """LLM 생성기·Scripted 대역이 결정론으로 표시되면 가드(독립성)가 거짓 면제된다."""
    for cls in _NOT_DETERMINISTIC:
        assert DETERMINISTIC_GENERATOR_MARK not in vars(cls), cls.__name__


def test_guard_detects_an_unstamped_generator_in_a_new_module() -> None:
    """변별력 — 데코레이터 없는 새 생성기가 있는 모듈을 먹이면 발견기가 그것을 지목한다."""
    module = ModuleType("whymath_backend.l3.equivalent.fake_new_skeleton_generator")

    class FakeNewSkeletonGenerator:
        def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
            return None

    FakeNewSkeletonGenerator.__module__ = module.__name__
    module.FakeNewSkeletonGenerator = FakeNewSkeletonGenerator  # type: ignore[attr-defined]
    found = _generator_classes([module])
    assert found == [FakeNewSkeletonGenerator]
    assert DETERMINISTIC_GENERATOR_MARK not in vars(FakeNewSkeletonGenerator)


# ── 데코레이터 동작 ─────────────────────────────────────────────────────
_SPEC = EquivalenceSpec(
    achievement_standard_codes=frozenset({"[12확통03-03]"}),
    target_misconception_ids=frozenset(),
    difficulty_overall=3.0,
    answer_format=None,
)


def _real_candidate() -> CandidateProblem:
    candidate = BinomialDistributionSkeletonGenerator(kind="mean").generate(_SPEC)
    assert candidate is not None
    return candidate


def test_real_generator_stamps_its_module_name() -> None:
    candidate = _real_candidate()
    assert candidate.authored_by == deterministic_author("binomial_distribution_skeleton_generator")


def test_decorator_stamps_unsigned_keeps_signed_and_passes_none() -> None:
    base = _real_candidate().model_copy(update={"authored_by": None})
    signed = base.model_copy(update={"authored_by": "llm:m"})

    @deterministic_generator
    class _Unsigned:
        def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
            return base

    @deterministic_generator
    class _AlreadySigned:
        def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
            return signed

    @deterministic_generator
    class _Failing:
        def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
            return None

    module_name = deterministic_generator_name(_Unsigned)
    assert _Unsigned().generate(_SPEC).authored_by == deterministic_author(module_name)  # type: ignore[union-attr]
    assert _AlreadySigned().generate(_SPEC).authored_by == "llm:m"  # type: ignore[union-attr]
    assert _Failing().generate(_SPEC) is None
    assert base.authored_by is None, "원본 후보를 변이하지 않는다(model_copy)"


def test_decorator_rejects_class_without_own_generate() -> None:
    class _Base:
        def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
            return None

    class _Child(_Base):
        pass

    with pytest.raises(TypeError, match="generate"):
        deterministic_generator(_Child)


def test_fresh_corpus_batch_writes_the_signature(tmp_path: Path) -> None:
    """배치 경로 관통 — 생성기 서명이 오케스트레이터→저장 레코드→JSONL 줄까지 실린다."""
    import json

    from whymath_backend.harness.binomial_distribution_batch import (
        run_binomial_distribution_batch,
    )
    from whymath_backend.l1.problem_bank.populate import load_problem_bank_records

    out = tmp_path / "problems.jsonl"
    report = run_binomial_distribution_batch(n_per_band=3, out_path=out)
    assert report.total_stored > 0
    expected = deterministic_author("binomial_distribution_skeleton_generator")
    lines = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert {row["authored_by"] for row in lines} == {expected}
    loaded = load_problem_bank_records(out)
    assert {r.provenance.authored_by for r in loaded} == {expected}
