"""coach↔WH-1 하네스 도구 단일 진실원천 봉인 — S1-11 flip-없는 수렴 거버넌스(hermetic).

"이중 경로" 위험(s1_structure_audit §상환 #3·유지보수 지옥)은 두 오케스트레이터(결정론
coach·WH-1 하네스)가 *같은 순수 도구의 다른 사본*을 소비하게 될 때 현실화된다 — 한쪽만
수정되면 두 경로가 같은 입력에 다른 판정을 낸다. 본 테스트는 공유 도구가 **동일 함수
객체**(is — import 경로가 달라도 원천이 하나)임을 동결해, 사본 분기 유입 시 즉시 red를
낸다. primary flip(오케스트레이션 수렴·Kiki 게이트)과 무관하게 지금 지켜야 하는 불변식.

DB 0·LLM 0·순수 import 검사만(gate3 governance의 AST 검사와 상보 — 이쪽은 identity).
"""

from __future__ import annotations

from whymath_backend.api import coach
from whymath_backend.harness import wh1_loop
from whymath_backend.l4 import subject_adapter_math
from whymath_backend.l4.misconception import hypothesis, hypothesis_store


def test_diagnose_single_source() -> None:
    # 오개념 진단 — coach(패키지 재수출 경유)와 하네스(모듈 직수입)가 같은 함수 객체.
    assert coach.diagnose is wh1_loop.diagnose


def test_intervention_single_source() -> None:
    # 가설 기반 개입 선택 — 양 경로 동일 원천.
    assert coach.select_intervention_from_hypotheses is wh1_loop.select_intervention_from_hypotheses


def test_curate_single_source() -> None:
    """가설 큐레이션 — 두 경로가 같은 *구현*을 소비한다(#191 재사용 계약의 identity 동결).

    [MISC-20] coach 경로(영속 래퍼 `curate_hypothesis` 내부)는 탈락 *사유*가 필요해
    `curate_with_reasons`를, 하네스(in-memory 루프)는 생존 세트만 필요해 `curate`를 부른다.
    이름이 갈렸어도 **구현은 하나**다 — `curate`가 `curate_with_reasons`의 얇은 래퍼이기
    때문이다. 그래서 identity 동결 지점을 그 단일 구현으로 옮긴다. 사본 분기가 생기면(둘 중
    하나가 파이프라인을 자체 구현하면) 아래 두 단언 중 하나가 즉시 red다.
    """
    assert hypothesis_store.curate_with_reasons is hypothesis.curate_with_reasons
    assert wh1_loop.curate is hypothesis.curate
    # 래퍼 계약 — `curate`는 `curate_with_reasons`의 생존 세트를 그대로 돌려준다(사본 0).
    # **비퇴화 입력으로 확인한다**: 빈 입력은 어떤 구현이든 []를 내므로 변별력이 0이다
    # (감쇠·반박 제거·캡 절단 세 규칙이 전부 관측되도록 입력을 만든다).
    fixture = [
        hypothesis.MisconceptionHypothesis(
            misconception_id=f"mc-{i}",
            confidence=0.9 - i * 0.05,
            turns_since_evidence=0,
            evidence_count=1,
        )
        for i in range(7)
    ]
    for refuted, cap in ((frozenset(), 5), (frozenset({"mc-1"}), 3), (frozenset({"mc-0"}), 6)):
        assert (
            hypothesis.curate(fixture, [], turns_elapsed=2, refuted=refuted, max_active=cap)
            == hypothesis.curate_with_reasons(
                fixture, [], turns_elapsed=2, refuted=refuted, max_active=cap
            )[0]
        )


def test_verify_solution_single_source() -> None:
    # Tier2 단계 검증 — coach 경로의 검산 코칭(solution_coaching)과 하네스가 같은
    # l3.verify_solution을 소비한다(두 경로가 같은 풀이에 다른 판정을 낼 수 없음).
    #
    # [EOS-86] solution_coaching은 더 이상 verify_solution을 직접 import하지 않는다 —
    # StepChainVerifier 선택층 주입(기본 구현 `l4.subject_adapter_math.MathStepChainVerifier`
    # → `l3.verify_solution.verify_solution` 위임)으로 대체됐다(CORE→ADAPTER 직접 의존 제거).
    # identity 동결 지점을 그 실제 위임처로 옮긴다 — 사본 분기가 생기면 여전히 여기서 red다.
    assert subject_adapter_math.verify_solution is wh1_loop.verify_solution
