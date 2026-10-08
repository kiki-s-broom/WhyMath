"""`l4/polya/prompts.py` 단위테스트 — 원칙 6 착지(PED-34) + 학년 register 치환(W0 S-2).

[PED-34 acceptance②] `docs/standards/prompt_engineering.md` §"6. 인지부하 관리"가 명문화한
5축(턴당 질문 1개·응답 길이 상한·청크 분할·무관정보/반복 금지·선 유도→후 보강)이
`l4/polya/prompts.py`의 `_BASE_SYSTEM`에 실제로 실려 있는지, 그리고 `PolyaCoach.decide()`
(→ `PedagogyDecision.system` → `/v1/coach`가 그대로 소비하는 경로)를 거쳐도 사라지지
않는지를 확인한다 — 정본화(문서)와 집행 지점(실소비 경로)을 별항으로 검증한다(CLAUDE.md
"정본화를 집행으로 착각한 완료 선언 금지"). `test_polya_engine.py::TestSystemPromptShape`
(기존 5원칙 동결)와 동형 — 새 파일로 분리한 이유는 PED-34 acceptance②가 독립 파일을
`paths`로 명시했기 때문이다.

[W0 S-2] 학년축 최단경로 계획(`docs/strategy/grade_axis_mvp_shortest_path_v1.md`) §2.3·§3 W0.
`_grade_register`·`base_system_for_grade`는 결정론적 문구 치환 함수(LLM 0회) — 여기서
매핑표 전체와 회귀 0 계약(grade=None → 학년축 도입 전 문구와 바이트 동일)을 못 박는다.
"""

from __future__ import annotations

import pytest

from whymath_backend.l4.models import PolyaStage, PolyaState
from whymath_backend.l4.polya.engine import PolyaCoach
from whymath_backend.l4.polya.prompts import (
    _BASE_SYSTEM,
    STAGE_PROMPTS,
    _grade_register,
    base_system_for_grade,
)


def _state(stage: PolyaStage) -> PolyaState:
    return PolyaState(current_stage=stage)


class TestCognitiveLoadPrincipleLandsInBaseSystem:
    """원칙 6의 5축이 `_BASE_SYSTEM`(모든 단계 공유) 문면에 실제로 있는가."""

    def test_exactly_one_question_per_turn(self) -> None:
        system = STAGE_PROMPTS[PolyaStage.UNDERSTAND].system
        assert "질문은 정확히 1개" in system
        # 원래 있던 "1-2개" 문구가 그대로 남아 있으면 원칙 6이 실제로 교체되지 않은 것.
        assert "1-2개" not in system

    def test_response_length_cap(self) -> None:
        system = STAGE_PROMPTS[PolyaStage.UNDERSTAND].system
        assert "3문장 이내" in system

    def test_manageable_chunking(self) -> None:
        system = STAGE_PROMPTS[PolyaStage.UNDERSTAND].system
        assert "하나씩 나눠" in system

    def test_no_irrelevant_info_or_repetition(self) -> None:
        system = STAGE_PROMPTS[PolyaStage.UNDERSTAND].system
        assert "반복" in system
        assert "무관한 정보" in system

    def test_guide_before_reinforce_ordering(self) -> None:
        system = STAGE_PROMPTS[PolyaStage.UNDERSTAND].system
        assert "선 유도" in system
        assert "유도 질문" in system


class TestCognitiveLoadSurvivesRealConsumptionPath:
    """정본화 ≠ 집행 — `PolyaCoach.decide()`를 거친 `PedagogyDecision.system`에도 남는가.

    이 경로가 `/v1/coach`가 실제로 소비하는 경로다(`api/coach.py`가 `PedagogyDecision`을
    그대로 LLM 호출에 넘긴다) — `STAGE_PROMPTS` 딥테스트만으로는 엔진이 중간에 문구를
    가공·삭제하지 않는지 확인할 수 없다.
    """

    @pytest.mark.parametrize(
        "stage",
        [PolyaStage.UNDERSTAND, PolyaStage.PLAN, PolyaStage.EXECUTE, PolyaStage.REVIEW],
    )
    def test_all_four_stages_carry_the_principle(self, stage: PolyaStage) -> None:
        coach = PolyaCoach()
        decision = coach.decide("아무 발화", _state(stage))
        assert "질문은 정확히 1개" in decision.system
        assert "3문장 이내" in decision.system
        assert "선 유도" in decision.system


class TestGradeRegister:
    def test_none_falls_back_to_default(self) -> None:
        assert _grade_register(None) == "중·고등학생"

    @pytest.mark.parametrize(
        ("grade", "expected"),
        [
            (1, "초등학생"),
            (6, "초등학생"),
            (7, "중학생"),
            (9, "중학생"),
            (10, "고등학생"),
            (12, "고등학생"),
            (13, "대학생"),
            (16, "대학생"),
        ],
    )
    def test_grade_band_boundaries(self, grade: int, expected: str) -> None:
        assert _grade_register(grade) == expected

    @pytest.mark.parametrize("grade", [0, -1, 17, 100])
    def test_out_of_range_falls_back_to_default(self, grade: int) -> None:
        assert _grade_register(grade) == "중·고등학생"


class TestBaseSystemForGrade:
    def test_none_is_byte_identical_to_base_system_constant(self) -> None:
        assert base_system_for_grade(None) == _BASE_SYSTEM

    def test_none_keeps_pre_w0_identity_sentence_verbatim(self) -> None:
        """회귀 0의 실검증 — 위 동어반복 테스트(`_BASE_SYSTEM`은 정의상 이 함수의 grade=None
        결과)를 보완한다. 템플릿화(줄 이음 `\\`)에서 실제로 틀어질 수 있는 지점은 정체성 문장의
        공백·어순이므로, 학년축 도입 전 문구를 리터럴로 고정해 직접 비교한다."""
        assert base_system_for_grade(None).startswith(
            "너는 한국 중·고등학생을 돕는 *수학 메타인지 코치*다. 다음 원칙을 절대 지킨다:\n\n1. "
        )
        # 템플릿 치환 표식이 결과에 남으면(포맷 누락) 학생 프롬프트에 `{register}`가 새어 나간다.
        assert "{register}" not in base_system_for_grade(None)
        assert "{register}" not in base_system_for_grade(14)

    def test_high_school_range_uses_high_school_register_not_legacy_combined(self) -> None:
        # grade=11(현재 UserProfile 실호출 범위 10~14 안)은 "고등학생"이지 구 결합 표현
        # "중·고등학생"이 아니다 — 그 표현은 grade=None(미상) 폴백 전용.
        out = base_system_for_grade(11)
        assert "너는 한국 고등학생을 돕는" in out
        assert out != _BASE_SYSTEM

    def test_elementary_register_appears_verbatim(self) -> None:
        out = base_system_for_grade(3)
        assert "너는 한국 초등학생을 돕는" in out
        assert "중·고등학생" not in out

    def test_university_register_appears_verbatim(self) -> None:
        out = base_system_for_grade(14)
        assert "너는 한국 대학생을 돕는" in out

    def test_only_identity_clause_varies_rest_is_grade_invariant(self) -> None:
        """원칙·톤 본문은 register와 무관하게 4축 공용(구조 분기 아님) — 문구만 다르다."""
        elementary = base_system_for_grade(3)
        university = base_system_for_grade(14)
        # 정체성 문구 제외 나머지 본문은 바이트 동일해야.
        elementary_rest = elementary.split("을 돕는", 1)[1]
        university_rest = university.split("을 돕는", 1)[1]
        assert elementary_rest == university_rest

    def test_all_stage_systems_are_the_shared_base_system(self) -> None:
        """`decide()`는 단계별 `StagePrompt.system`이 아니라 `base_system_for_grade(grade)` 하나만
        쓴다(W0) — 지금은 4단계 system이 전부 `_BASE_SYSTEM`이라 동치지만, 한 단계에 별도
        system이 정의되는 순간 그 값이 조용히 무시된다(침묵 실패). 갈라지면 이 테스트가 red가
        되어 `decide`가 단계별 system을 어떻게 합성할지 의식적으로 정하게 만든다."""
        for stage, stage_prompt in STAGE_PROMPTS.items():
            assert stage_prompt.system == _BASE_SYSTEM, f"{stage}: 단계별 system이 공통과 다름"

    @pytest.mark.parametrize(
        "stage",
        [PolyaStage.UNDERSTAND, PolyaStage.PLAN, PolyaStage.EXECUTE, PolyaStage.REVIEW],
    )
    def test_decide_applies_grade_register_in_every_stage(self, stage: PolyaStage) -> None:
        """실소비 경로(`decide()` → `PedagogyDecision.system`)에서 grade가 register에 착지한다 —
        `base_system_for_grade` 단위 테스트만으로는 엔진이 그 결과를 실제로 쓰는지 알 수 없다."""
        coach = PolyaCoach()
        assert "너는 한국 대학생을 돕는" in coach.decide("발화", _state(stage), grade=14).system
        # grade 미전달은 학년축 도입 전 문구 그대로(회귀 0).
        assert "너는 한국 중·고등학생을 돕는" in coach.decide("발화", _state(stage)).system

    def test_every_register_keeps_cognitive_load_principle(self) -> None:
        """PED-34 원칙 6은 학년 register와 무관하게 모든 학년의 system에 실려야 한다 —
        W0 템플릿화가 main의 원칙 6을 누락한 채 이식되는 회귀(분기 이후 본문 변경)를 막는다."""
        for grade in (None, 3, 8, 11, 14):
            assert "질문은 정확히 1개" in base_system_for_grade(grade)
