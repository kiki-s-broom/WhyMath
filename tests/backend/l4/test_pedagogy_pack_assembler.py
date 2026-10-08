"""L4 교수법 팩 런타임 단위테스트 — 레지스트리·4계층 조립기·금지모드 가드·decide 옵트인 훅.

hermetic: 실 코퍼스 YAML(`data/corpus/pedagogy_packs_v1/*.yaml`)을 파일에서 읽는다(네트워크·DB 0).
플래그 토글은 env+`get_settings.cache_clear()`(coach_prose_leak_eval·primary flip 테스트 관례).

핵심 봉인:
  - OFF/무팩 **비트동일** — `build_system_prompt(pack=None)`은 base_system을 바이트 동일 반환하고,
    `decide(pack=None)`·플래그 OFF는 `PedagogyDecision.system`이 기존과 동일하다(회귀 0 계약).
  - 4계층 순서·`{domain_example}` 치환.
  - 가드는 위반에 reason_code, clean에 None을 내고, 미등록(deferred) 모드는 판정하지 않는다(정직).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from whymath_backend.config import get_settings
from whymath_backend.l4.misconception.hypothesis import MisconceptionHypothesis
from whymath_backend.l4.models import PolyaStage, PolyaState
from whymath_backend.l4.pedagogy.mode_guard import (
    DEFERRED_MODES,
    FORBIDDEN_MODE_DETECTORS,
    RULE_DETECTABLE_MODES,
    check_forbidden_modes,
)
from whymath_backend.l4.pedagogy.pack_registry import (
    get_pack,
    get_pedagogy_packs,
    reset_pack_cache,
)
from whymath_backend.l4.pedagogy.prompt_assembler import (
    build_system_prompt,
    render_misconceptions,
    render_student_state,
)
from whymath_backend.l4.polya.engine import PolyaCoach
from whymath_backend.l4.polya.prompts import STAGE_PROMPTS
from whymath_backend.schema.enums import KnowledgeType
from whymath_backend.schema.pedagogy_pack import FORBIDDEN_MODE_VOCAB

_CONCEPT = KnowledgeType.CONCEPT.value
_PROCEDURE = KnowledgeType.PROCEDURE.value


@pytest.fixture(autouse=True)
def _restore_settings_cache() -> Iterator[None]:
    """각 테스트 후 설정 캐시 원복 — env 토글이 다른 테스트로 새지 않게."""
    yield
    get_settings.cache_clear()


def _enable_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """교수법 팩 발문 플래그 ON — env+cache_clear."""
    monkeypatch.setenv("WHYMATH_PEDAGOGY_PACK_PROMPT_ENABLED", "true")
    get_settings.cache_clear()


def _disable_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """교수법 팩 발문 플래그 OFF 명시 — env+cache_clear."""
    monkeypatch.setenv("WHYMATH_PEDAGOGY_PACK_PROMPT_ENABLED", "false")
    get_settings.cache_clear()


# ──────────────────────────────────────────────────────────────────────────
# 레지스트리
# ──────────────────────────────────────────────────────────────────────────
class TestPackRegistry:
    def test_loads_exactly_seven_packs_keyed_by_k_type(self) -> None:
        reset_pack_cache()
        packs = get_pedagogy_packs()
        assert len(packs) == 7
        # 7 지식유형 전부 문자열 키로 존재(use_enum_values → 문자열).
        assert set(packs) == {kt.value for kt in KnowledgeType}
        # 값은 자기 k_type과 일치(키 = pack.k_type).
        for key, pack in packs.items():
            assert pack.k_type == key

    def test_cached_returns_same_object(self) -> None:
        reset_pack_cache()
        first = get_pedagogy_packs()
        second = get_pedagogy_packs()
        assert first is second  # lru_cache — 재로딩 0(DB-free·1회 로드).

    def test_get_pack_hit_and_miss(self) -> None:
        reset_pack_cache()
        assert get_pack(_CONCEPT) is not None
        assert get_pack(_CONCEPT).k_type == _CONCEPT  # type: ignore[union-attr]
        # 미등록 k_type은 None(fail-soft 조회 — 예외 아님).
        assert get_pack("NOT_A_KTYPE") is None

    def test_concept_pack_forbids_worked_example_first(self) -> None:
        reset_pack_cache()
        concept = get_pack(_CONCEPT)
        assert concept is not None
        assert "WORKED_EXAMPLE_FIRST" in concept.forbidden_modes
        assert "{domain_example}" in concept.socratic_prompt  # schema 불변식(a) 재확인.


# ──────────────────────────────────────────────────────────────────────────
# 4계층 조립기
# ──────────────────────────────────────────────────────────────────────────
class TestAssembler:
    def test_pack_none_returns_base_system_byte_identical(self) -> None:
        base = STAGE_PROMPTS[PolyaStage.UNDERSTAND].system
        out = build_system_prompt(base_system=base, pack=None)
        # 바이트 동일(동일 문자열) — OFF/무팩 회귀 0 계약의 단일 지점.
        assert out == base
        # 무팩은 misconception·student를 줘도 무변경(pack None 조기 반환).
        hyp = MisconceptionHypothesis(
            misconception_id="MC-x", confidence=0.8, turns_since_evidence=0, evidence_count=1
        )
        assert build_system_prompt(base_system=base, pack=None, misconceptions=[hyp]) == base

    def test_composes_layers_in_order_with_domain_example_substituted(self) -> None:
        reset_pack_cache()
        base = STAGE_PROMPTS[PolyaStage.UNDERSTAND].system
        concept = get_pack(_CONCEPT)
        assert concept is not None
        hyp = MisconceptionHypothesis(
            misconception_id="MC-정의혼동", confidence=0.7, turns_since_evidence=1, evidence_count=2
        )
        out = build_system_prompt(
            base_system=base,
            pack=concept,
            domain_example="이차방정식의 근",
            misconceptions=[hyp],
            student_state="숙달",
        )
        # 계층 1: base_system이 맨 앞(prefix).
        assert out.startswith(base)
        # 계층 2: {domain_example} 치환됨(자리표시자 잔류 X, 주입값 등장).
        assert "이차방정식의 근" in out
        assert "{domain_example}" not in out
        # 계층 3: 오개념 블록(반응적) — id 등장·내용(canonical) 미주입.
        assert "MC-정의혼동" in out
        assert "의심 오개념 가설" in out
        # 계층 4: 학습자 상태 블록.
        assert "숙달" in out
        # 순서: base < 소크라테스(정의 유도 문구) < 오개념 < 학습자.
        idx_base = out.index(base)
        idx_socratic = out.index("이차방정식의 근")
        idx_mis = out.index("의심 오개념 가설")
        idx_state = out.index("학습자 숙달 수준")
        assert idx_base < idx_socratic < idx_mis < idx_state
        # \n\n로 계층 결합.
        assert "\n\n" in out

    def test_neutral_default_when_no_domain_example(self) -> None:
        reset_pack_cache()
        base = STAGE_PROMPTS[PolyaStage.UNDERSTAND].system
        concept = get_pack(_CONCEPT)
        assert concept is not None
        out = build_system_prompt(base_system=base, pack=concept)
        # domain_example 미지정 → 중립 기본값 치환(리터럴 브레이스 잔류 X).
        assert "{domain_example}" not in out
        assert "지금 다루는 문제" in out

    def test_optional_layers_empty_when_absent(self) -> None:
        reset_pack_cache()
        base = STAGE_PROMPTS[PolyaStage.UNDERSTAND].system
        concept = get_pack(_CONCEPT)
        assert concept is not None
        out = build_system_prompt(base_system=base, pack=concept)
        # 오개념·학습자 미주입 → 해당 블록 없음(계층 3·4 생략).
        assert "의심 오개념 가설" not in out
        assert "학습자 숙달 수준" not in out

    def test_render_helpers_empty_on_none(self) -> None:
        assert render_misconceptions(None) == ""
        assert render_misconceptions([]) == ""
        assert render_student_state(None) == ""

    # ──────────────────────────────────────────────────────────────────
    # PED-05 — grade·standard_code 개인화 슬롯
    # ──────────────────────────────────────────────────────────────────
    def test_render_student_state_grade_and_standard_code_alone(self) -> None:
        # student_state 없이도 grade·standard_code만으로 블록이 렌더된다.
        out = render_student_state(None, grade=2, standard_code="[10공수1-02-06]")
        assert "학년: 2" in out
        assert "성취기준: [10공수1-02-06]" in out
        assert "학습자 숙달 수준" not in out  # student_state 없음 → 그 조각 생략

    def test_render_student_state_all_three_combined(self) -> None:
        out = render_student_state("숙달", grade=3, standard_code="[12미적01-01]")
        assert "학습자 숙달 수준: 숙달" in out
        assert "학년: 3" in out
        assert "성취기준: [12미적01-01]" in out

    def test_render_student_state_grade_only_no_pii_leak(self) -> None:
        # grade(학년 정수)·standard_code 외에는 이 함수 시그니처에 자리가 없다 — 학교명·지역·
        # 이름·목표점수/등급/대학 문자열이 등장할 자리 자체가 구조적으로 없음을 재확인.
        out = render_student_state(None, grade=1)
        for forbidden in ("학교", "지역", "목표", "대학", "이름"):
            assert forbidden not in out

    def test_build_system_prompt_threads_grade_and_standard_code(self) -> None:
        reset_pack_cache()
        base = STAGE_PROMPTS[PolyaStage.UNDERSTAND].system
        concept = get_pack(_CONCEPT)
        assert concept is not None
        out = build_system_prompt(
            base_system=base, pack=concept, grade=2, standard_code="[10공수1-02-06]"
        )
        assert "학년: 2" in out
        assert "성취기준: [10공수1-02-06]" in out

    def test_build_system_prompt_pack_none_ignores_grade_standard_code(self) -> None:
        # pack None 회귀 0 계약 — grade/standard_code를 줘도 base_system 바이트 동일.
        base = STAGE_PROMPTS[PolyaStage.UNDERSTAND].system
        out = build_system_prompt(
            base_system=base, pack=None, grade=2, standard_code="[10공수1-02-06]"
        )
        assert out == base


# ──────────────────────────────────────────────────────────────────────────
# 금지모드 가드
# ──────────────────────────────────────────────────────────────────────────
class TestModeGuard:
    def test_coverage_is_explicit_and_honest(self) -> None:
        # v1 규칙 검출 가능 = WORKED_EXAMPLE_FIRST 1축, 나머지 6종은 deferred(정직한 공백).
        assert RULE_DETECTABLE_MODES == frozenset({"WORKED_EXAMPLE_FIRST"})
        assert DEFERRED_MODES == FORBIDDEN_MODE_VOCAB - RULE_DETECTABLE_MODES
        assert len(DEFERRED_MODES) == 6
        assert set(FORBIDDEN_MODE_DETECTORS) == RULE_DETECTABLE_MODES

    def test_returns_reason_code_on_injected_violation(self) -> None:
        reset_pack_cache()
        concept = get_pack(_CONCEPT)
        assert concept is not None
        # 정의·정답 단정 + 유도 부재 → WORKED_EXAMPLE_FIRST 위반.
        violating = "이 개념의 정의는 주변보다 큰 값이다. 정답은 그대로 외우면 된다."
        assert check_forbidden_modes(concept, violating) == "WORKED_EXAMPLE_FIRST"

    def test_returns_none_on_clean_socratic_reply(self) -> None:
        reset_pack_cache()
        concept = get_pack(_CONCEPT)
        assert concept is not None
        # 정의어를 언급해도 명백히 유도 → 위반 아님(오검출 방어).
        clean = "이걸 뭐라고 정의하면 좋을까? 네 생각을 말해 줄래?"
        assert check_forbidden_modes(concept, clean) is None

    def test_worked_chain_conclusion_is_violation(self) -> None:
        reset_pack_cache()
        concept = get_pack(_CONCEPT)
        assert concept is not None
        # `=` + 결론 마커(따라서) + 유도 부재 → 완전예제 결론 제시.
        chain = "먼저 f=2x-4, 2x-4=0, 따라서 x=2가 최종 결론이다."
        assert check_forbidden_modes(concept, chain) == "WORKED_EXAMPLE_FIRST"

    def test_deferred_mode_pack_is_not_ruled(self) -> None:
        reset_pack_cache()
        procedure = get_pack(_PROCEDURE)
        assert procedure is not None
        # 절차형은 PRODUCTIVE_FAILURE(deferred·검출기 없음)만 금지 → 어떤 응답도 규칙 판정 안 함.
        assert "PRODUCTIVE_FAILURE" in procedure.forbidden_modes
        # 정의 단정 응답이어도 절차형 팩엔 WORKED_EXAMPLE_FIRST 금지가 없어 None(교차 오검출 방지).
        assert check_forbidden_modes(procedure, "정의는 이렇다. 그대로 외워라.") is None


# ──────────────────────────────────────────────────────────────────────────
# decide() 옵트인 훅 — 비트동일 회귀 + 플래그 ON 조립
# ──────────────────────────────────────────────────────────────────────────
class TestDecideWiring:
    def test_decide_pack_none_system_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 플래그 ON이어도 pack 미주입이면 base_system 무변경(옵트인·기존 호출자 무영향).
        _enable_flag(monkeypatch)
        coach = PolyaCoach()
        d = coach.decide("음", PolyaState(current_stage=PolyaStage.UNDERSTAND))
        assert d.system == STAGE_PROMPTS[PolyaStage.UNDERSTAND].system

    def test_decide_flag_off_with_pack_system_unchanged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # pack 주입해도 플래그 OFF면 조립기 미호출 → 비트동일(회귀 0).
        _disable_flag(monkeypatch)
        reset_pack_cache()
        concept = get_pack(_CONCEPT)
        coach = PolyaCoach()
        d = coach.decide("음", PolyaState(current_stage=PolyaStage.UNDERSTAND), pack=concept)
        assert d.system == STAGE_PROMPTS[PolyaStage.UNDERSTAND].system

    def test_decide_flag_on_with_pack_layers_system(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 플래그 ON + pack 주입 → 팩 4계층 조립으로 system 대체(base prefix 유지).
        _enable_flag(monkeypatch)
        reset_pack_cache()
        concept = get_pack(_CONCEPT)
        coach = PolyaCoach()
        base = STAGE_PROMPTS[PolyaStage.UNDERSTAND].system
        d = coach.decide("음", PolyaState(current_stage=PolyaStage.UNDERSTAND), pack=concept)
        assert d.system != base
        assert d.system.startswith(base)  # 기존 역할 규칙 보존(계층 1).
        assert "지금 다루는 문제" in d.system  # 중립 domain_example(해석 seam 후속).
        # 나머지 결정 필드는 무변경(system만 대체).
        assert d.prompt == STAGE_PROMPTS[PolyaStage.UNDERSTAND].prompt

    # ──────────────────────────────────────────────────────────────────
    # PED-05 — decide()의 grade·standard_code 개인화 슬롯 회귀 + 착지
    # ──────────────────────────────────────────────────────────────────
    def test_decide_grade_standard_code_default_none_no_regression(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 기존 호출자(grade/standard_code 미전달) — 플래그 ON + pack 주입이어도 완전 동일 동작.
        _enable_flag(monkeypatch)
        reset_pack_cache()
        concept = get_pack(_CONCEPT)
        coach = PolyaCoach()
        state = PolyaState(current_stage=PolyaStage.UNDERSTAND)
        with_kwargs = coach.decide("음", state, pack=concept)
        without_kwargs = coach.decide("음", state, pack=concept, grade=None, standard_code=None)
        assert with_kwargs.system == without_kwargs.system

    def test_decide_flag_off_ignores_standard_code_but_grade_still_sets_register(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 플래그 OFF면 pack 4계층 조립(팩 발문·오개념·standard_code)은 여전히 미호출 — 회귀 0.
        # 단 grade는 W0(S-2)부터 팩 플래그와 *독립*으로 base_system의 register를 바꾼다
        # (`base_system_for_grade` — 결정론 문구 치환이라 팩 조립기의 fidelity 게이트 대상이
        # 아님). 이 테스트는 더 이상 "grade도 비트동일"을 주장하지 않는다 — 그 계약은
        # test_polya_engine.py::TestGradeRegisterWiring이 대신 못 박는다.
        _disable_flag(monkeypatch)
        reset_pack_cache()
        concept = get_pack(_CONCEPT)
        coach = PolyaCoach()
        d = coach.decide(
            "음",
            PolyaState(current_stage=PolyaStage.UNDERSTAND),
            pack=concept,
            grade=2,
            standard_code="[10공수1-02-06]",
        )
        assert "초등학생" in d.system  # grade=2 → register 반영(팩 플래그와 무관)
        assert "성취기준" not in d.system  # standard_code는 팩 계층 4 미조립이라 여전히 미노출
        assert "[10공수1-02-06]" not in d.system

    def test_decide_flag_on_with_pack_lands_grade_and_standard_code(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 플래그 ON + pack 주입 + grade/standard_code 제공 → system에 실제로 착지.
        _enable_flag(monkeypatch)
        reset_pack_cache()
        concept = get_pack(_CONCEPT)
        coach = PolyaCoach()
        d = coach.decide(
            "음",
            PolyaState(current_stage=PolyaStage.UNDERSTAND),
            pack=concept,
            grade=2,
            standard_code="[10공수1-02-06]",
        )
        assert "학년: 2" in d.system
        assert "성취기준: [10공수1-02-06]" in d.system
        # PII 가드: decide()의 어떤 인자에도 학교·지역·이름·목표 필드가 없어 노출될 자리가 없음.
        for forbidden in ("학교", "지역", "목표", "대학", "이름"):
            assert forbidden not in d.system
