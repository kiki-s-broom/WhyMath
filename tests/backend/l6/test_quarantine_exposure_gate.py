"""EOS-71 — 격리(`quarantined`) 문항이 L6 노출 경로 **전건**에서 빠지는지 동결.

이 파일은 **코드를 바꾸지 않은 축**의 동결이다. L6 6모드 게이팅(retake·suneung·school_progress·
thinking·metacognition·gifted)과 blueprint 조립은 전부 `_shared.is_review_cleared`(값 판정은
`schema.enums.is_review_status_cleared`)를 경유하는데, 그 술어는 **`approved`만 통과시키는
허용목록**이라 새 상태값 `quarantined`를 *자동으로* 배제한다 — EOS-71에서 이쪽 코드는 한 줄도
건드리지 않았다(격리 계약 `docs/standards/problem_quarantine_contract.md` §4 집행 지점 표 상단 4행).

그래서 여기서 동결하는 것은 "구현했다"가 아니라 **"허용목록 방향이 유지된다"**이다. 누군가
`is_review_cleared`를 차단목록(`!= rejected` 같은 형태)으로 바꾸면 격리 문항이 6모드 전체로 조용히
새 나가는데, 그 회귀는 EOS-71이 실제로 손댄 파일(`api/problems.py`)에 아무 흔적도 남기지 않는다.
자동 배제는 *공짜로 얻은 것*이라 아무도 그것을 지키고 있지 않다 — 그래서 여기서 지킨다.

**대표 1모드가 아니라 7경로 전건을 돈다.** 기존 `tests/backend/l6/retake/test_gating.py`의
`TestReviewStatusGateIndependentFromCopyrightGate`는 "retake가 대표·전건 반복은 범위 밖"이라고
스스로 밝혔는데(PB-03 지시), 상태값이 늘어난 지금 그 대표성은 약해진다 — 새 값이 7경로 중 6곳에서만
배제되는 상태를 대표 검증은 구조적으로 볼 수 없다.

**양성 대조 동반(무력화 하한)**: 같은 픽스처가 `approved`에서는 7경로 전부 *적격*이어야 한다. 대조가
없으면 "픽스처가 어차피 부적격이라 통과"가 격리 차단으로 위장된다.

레이어(CLAUDE.md): L1(`schema.problem`·`schema.enums`)·L6만 import한다.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from whymath_backend.l6.blueprint.assembly import (
    BlueprintCell,
    ExamBlueprint,
    assemble_test_set,
    is_blueprint_eligible,
)
from whymath_backend.l6.gifted.gating import is_gifted_eligible
from whymath_backend.l6.metacognition.gating import is_metacognition_eligible
from whymath_backend.l6.retake.gating import is_retake_eligible
from whymath_backend.l6.school_progress.gating import is_school_progress_eligible
from whymath_backend.l6.suneung.gating import is_suneung_eligible
from whymath_backend.l6.thinking.gating import is_thinking_eligible
from whymath_backend.schema.enums import (
    BloomLevel,
    Curriculum,
    Persona,
    QuestionFormat,
    ReviewStatus,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem import DistractorEntry, Problem


def _problem(**over: object) -> Problem:
    """**7경로 전부에서 적격이 되는** 최소 자체생성 문항 빌더(합성 픽스처·실데이터 0).

    한 픽스처로 7경로를 동시에 만족시키려면 각 모드의 주신호를 전부 켜야 한다:
      · 저작권 축 — `source_type=자체생성`(본문 미보유 출처가 아님).
      · 페르소나 축 — 5종 전부 0.95(gifted의 빡빡한 기본 임계 0.7까지 넘긴다).
      · retake — `question_format=재수전용형`(RT 라벨).
      · thinking·gifted — `bloom_level=CREATE`(사고력 상위 3단계 + 영재 창안 신호).
      · gifted — `difficulty_overall=5.0`(심화 하한 4.0 초과) + `is_cross_unit=True`.
      · metacognition — `distractor_map` 1건(오답→오개념 역추적 자원).
      · school_progress — 타깃 진도를 주지 않으면 `persona_fit` 폴백으로 통과.
    `review_status`만 오버라이드하면 다른 축은 그대로 둔 채 검수 축만 시험할 수 있다
    (`tests/backend/l6/retake/test_gating.py`의 `_problem` 패턴 답습 — `type: ignore`도 동일).
    """
    kwargs: dict[str, object] = {
        "source_type": SourceType.자체생성,
        "review_status": ReviewStatus.approved,
        "curriculum_version": Curriculum.REVISION_2022,
        "valid_from_year": 2022,
        "subject": Subject.미적분,
        "unit_codes": ["CAL-INT-DEF"],
        # EOS-31 — 수능 출제 범위 축(범위 안 코드). 주입이 없으면 게이트가 `UNKNOWN`으로 거절한다.
        "achievement_standard_codes": ["[12대수01-01]"],
        "question_format": QuestionFormat.재수전용형,
        "bloom_level": BloomLevel.CREATE,
        "difficulty_overall": 5.0,
        "is_cross_unit": True,
        "persona_fit": {p.value: 0.95 for p in Persona},
        "distractor_map": [DistractorEntry(choice_index=1, misconception_id="M-ALG-001")],
    }
    kwargs.update(over)
    return Problem(**kwargs)  # type: ignore[arg-type]


#: 노출 경로 7건 — (경로명, `Problem` 1개를 받아 적격 여부를 내는 호출).
#: 페르소나는 각 모드의 대상 집합에서 고른다(gifted=E 전용·retake=B/C 전용 등 닫힌 집합이 있다).
_EXPOSURE_PATHS: tuple[tuple[str, Callable[[Problem], bool]], ...] = (
    ("retake", lambda p: is_retake_eligible(p, Persona.B_자사고N수)),
    ("suneung", lambda p: is_suneung_eligible(p, Persona.A_일반고고3)),
    ("school_progress", lambda p: is_school_progress_eligible(p, Persona.A_일반고고3)),
    ("thinking", lambda p: is_thinking_eligible(p, Persona.D_학종고2)),
    ("metacognition", lambda p: is_metacognition_eligible(p, Persona.A_일반고고3)),
    ("gifted", lambda p: is_gifted_eligible(p, Persona.E_홈스쿨링영재)),
    ("blueprint", is_blueprint_eligible),
)


class TestQuarantineBlockedOnEveryExposurePath:
    """7경로 × (양성 대조 → 격리 차단) — 한 경로라도 열려 있으면 red."""

    @pytest.mark.parametrize(("name", "is_eligible"), _EXPOSURE_PATHS)
    def test_approved_fixture_is_eligible_everywhere(
        self, name: str, is_eligible: Callable[[Problem], bool]
    ) -> None:
        """양성 대조(무력화 하한) — 같은 픽스처가 `approved`에서는 전 경로 적격이다.

        이 단언이 없으면 아래 차단 단언이 "픽스처가 애초에 부적격"이라는 이유로도 통과한다.
        """
        assert is_eligible(_problem()) is True, f"{name}: 픽스처가 approved에서도 부적격"

    @pytest.mark.parametrize(("name", "is_eligible"), _EXPOSURE_PATHS)
    def test_quarantined_is_blocked_everywhere(
        self, name: str, is_eligible: Callable[[Problem], bool]
    ) -> None:
        """`review_status=quarantined`면 7경로 전부에서 부적격 — 다른 축은 손대지 않았다."""
        quarantined = _problem(
            review_status=ReviewStatus.quarantined,
            quarantine_reason="복수 정답 — 조건 (나)에서 x<0도 해가 된다",
        )
        assert is_eligible(quarantined) is False, f"{name}: 격리 문항이 노출됐다"

    @pytest.mark.parametrize(("name", "is_eligible"), _EXPOSURE_PATHS)
    def test_quarantine_is_not_confused_with_rejected(
        self, name: str, is_eligible: Callable[[Problem], bool]
    ) -> None:
        """`rejected`도 여전히 차단 — 새 값이 기존 fail-closed를 느슨하게 만들지 않았다."""
        assert is_eligible(_problem(review_status=ReviewStatus.rejected)) is False, name


class TestBlueprintAssemblyExcludesQuarantined:
    """술어(`is_blueprint_eligible`)가 아니라 **조립 결과**에서도 빠지는지 — 실 서빙 형태.

    술어만 보면 "적격 판정은 False인데 조립기가 그 판정을 안 부른다"는 배선 누락을 볼 수 없다
    (CLAUDE.md "정본화를 집행으로 착각한 완료 선언 금지"의 테스트 축).
    """

    @staticmethod
    def _one_cell_blueprint() -> ExamBlueprint:
        return ExamBlueprint(title="격리 배제 확인", cells=[BlueprintCell(count=1)])

    def test_approved_problem_fills_the_cell(self) -> None:
        """양성 대조 — approved 1건이면 칸이 채워지고 세트가 충족된다."""
        result = assemble_test_set(self._one_cell_blueprint(), [_problem()])
        assert result.satisfied is True
        assert len(result.problem_ids) == 1

    def test_quarantined_problem_leaves_the_cell_empty(self) -> None:
        """격리 1건뿐이면 적격 후보 0 — 조용한 부분 반환이 아니라 부족 사유가 남는다."""
        quarantined = _problem(review_status=ReviewStatus.quarantined)
        result = assemble_test_set(self._one_cell_blueprint(), [quarantined])
        assert result.satisfied is False
        assert result.problem_ids == []
        assert result.unsatisfied_reasons, "부족 사유가 비어 있다(조용한 실패)"
