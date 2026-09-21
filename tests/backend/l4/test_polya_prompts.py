"""L4 Polya 프롬프트 원칙 6(인지부하 관리) 착지 — 실소비 경로 동결 (PED-34 acceptance②).

`docs/standards/prompt_engineering.md` §"6. 인지부하 관리"가 명문화한 5축(턴당 질문
1개·응답 길이 상한·청크 분할·무관정보/반복 금지·선 유도→후 보강)이 `l4/polya/prompts.py`의
`_BASE_SYSTEM`에 실제로 실려 있는지, 그리고 `PolyaCoach.decide()`(→ `PedagogyDecision.system`
→ `/v1/coach`가 그대로 소비하는 경로)를 거쳐도 사라지지 않는지를 확인한다 — 정본화(문서)와
집행 지점(실소비 경로)을 별항으로 검증한다(CLAUDE.md "정본화를 집행으로 착각한 완료 선언 금지").

`test_polya_engine.py::TestSystemPromptShape`(기존 5원칙 동결)와 동형 — 새 파일로 분리한
이유는 이 태스크(PED-34)의 acceptance②가 독립 파일을 `paths`로 명시했기 때문이다.
"""

from __future__ import annotations

import pytest

from whymath_backend.l4.models import PolyaStage, PolyaState
from whymath_backend.l4.polya.engine import PolyaCoach
from whymath_backend.l4.polya.prompts import STAGE_PROMPTS


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
