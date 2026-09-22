"""L4 오답 선택 인덱스 → 오개념 역방향 조회 단위테스트 (ASM-06).

순수 계층(DB 무관)만 검증한다 — `l1.problem_bank.probe_candidates::_match_probe_rows`의
순수 코어/DB 시암 분리 관례를 답습(테스트 자체는 `test_probe_candidates.py`·
`test_distractor_validate.py` 스타일). API 결선은 별도다: 채점 경로는
`tests/backend/api/test_me.py`, 실제 학생 흐름인 코치 턴 경로는
`tests/backend/api/test_coach.py`가 관통 검증한다.

앞부분(`TestNoSelectedIndex`~`TestMalformedEntries`)은 고립 브랜치 `087859bd`의 보존 구현을
**그대로 회수**한 것이고, 뒷부분(`TestDistractorLinkMatches` 이하)은 그 사이 main이 갖게 된
오개념 후보 파이프라인에 맞춰 추가한 확장이다.

핵심 봉인:
- ① `selected_choice_index`가 `None`이면 `distractor_map`을 보지 않고 즉시 `None`(reactive).
- ② `distractor_map`이 `None`/빈 리스트면 `None`(매핑 없음).
- ③ 일치하는 `choice_index` 엔트리의 `misconception_id`를 반환.
- ④ 일치하는 엔트리가 없으면(오답 인덱스 불일치·정답 인덱스는 애초에 매핑에 없음) `None`.
- ⑤ 형태 불량 원소(매핑 아님·키 누락·빈 misconception_id)는 조용히 건너뛴다(크래시 금지).
"""

from __future__ import annotations

import pytest

from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.l4.misconception.distractor_link import (
    DISTRACTOR_LINK_CONFIDENCE,
    distractor_link_candidates,
    distractor_link_matches,
    resolve_misconception_from_choice,
)
from whymath_backend.l4.misconception.match_gate import apply_match_quality_gate
from whymath_backend.l4.misconception.models import MisconceptionMatch

_MID_A = "mis.sign-error"
_MID_B = "mis.distribute-fail"


class TestNoSelectedIndex:
    def test_none_index_returns_none_without_inspecting_map(self) -> None:
        """① selected_choice_index가 None이면 distractor_map이 있어도 즉시 None."""
        distractor_map = [{"choice_index": 0, "misconception_id": _MID_A}]
        assert resolve_misconception_from_choice(distractor_map, None) is None

    def test_none_index_with_none_map(self) -> None:
        assert resolve_misconception_from_choice(None, None) is None


class TestNoDistractorMap:
    def test_none_map_returns_none(self) -> None:
        """② distractor_map 자체가 없음(정답 인덱스가 애초에 매핑에 없는 경우와 동형 결과)."""
        assert resolve_misconception_from_choice(None, 1) is None

    def test_empty_map_returns_none(self) -> None:
        assert resolve_misconception_from_choice([], 1) is None


class TestMatching:
    def test_matching_index_returns_misconception_id(self) -> None:
        """③ 일치하는 choice_index → 그 misconception_id."""
        distractor_map = [
            {"choice_index": 0, "misconception_id": _MID_A},
            {"choice_index": 2, "misconception_id": _MID_B},
        ]
        assert resolve_misconception_from_choice(distractor_map, 2) == _MID_B

    def test_matching_index_among_multiple_entries(self) -> None:
        distractor_map = [
            {"choice_index": 0, "misconception_id": _MID_A},
            {"choice_index": 1, "misconception_id": _MID_B},
            {"choice_index": 3, "misconception_id": "mis.off-by-one"},
        ]
        assert resolve_misconception_from_choice(distractor_map, 0) == _MID_A
        assert resolve_misconception_from_choice(distractor_map, 1) == _MID_B
        assert resolve_misconception_from_choice(distractor_map, 3) == "mis.off-by-one"

    def test_entry_may_carry_optional_op_code(self) -> None:
        """DistractorEntry.model_dump() 동형 입력(op_code 포함)도 그대로 받는다."""
        distractor_map = [
            {"choice_index": 1, "misconception_id": _MID_A, "op_code": "some-op-code"}
        ]
        assert resolve_misconception_from_choice(distractor_map, 1) == _MID_A


class TestNonMatching:
    def test_wrong_index_returns_none(self) -> None:
        """④ 불일치 인덱스(다른 오답을 골랐거나 매핑되지 않은 인덱스) → None."""
        distractor_map = [{"choice_index": 0, "misconception_id": _MID_A}]
        assert resolve_misconception_from_choice(distractor_map, 1) is None

    def test_correct_answer_index_absent_from_map_returns_none(self) -> None:
        """④ 정답 선지 인덱스는 distractor_map에 애초에 없다(정답 제외 설계) → None.

        `Problem.choices`가 4개(0~3)이고 정답이 인덱스 2, distractor_map은 오답 3개(0·1·3)만
        담는다고 가정 — 학생이 정답(2)을 골랐을 때 조회 결과는 매핑 부재와 동일하게 None.
        """
        distractor_map = [
            {"choice_index": 0, "misconception_id": _MID_A},
            {"choice_index": 1, "misconception_id": _MID_B},
            {"choice_index": 3, "misconception_id": "mis.off-by-one"},
        ]
        assert resolve_misconception_from_choice(distractor_map, 2) is None


class TestMalformedEntries:
    def test_non_mapping_entry_skipped(self) -> None:
        """⑤ dict가 아닌 원소(예: 문자열)는 형태 불량 — 조용히 건너뛰고 계속 탐색."""
        distractor_map = ["not-a-mapping", {"choice_index": 1, "misconception_id": _MID_A}]
        assert resolve_misconception_from_choice(distractor_map, 1) == _MID_A

    def test_entry_missing_choice_index_skipped(self) -> None:
        distractor_map = [{"misconception_id": _MID_A}]  # choice_index 없음
        assert resolve_misconception_from_choice(distractor_map, 0) is None

    def test_entry_with_empty_misconception_id_returns_none(self) -> None:
        """choice_index는 일치하나 misconception_id가 빈 문자열이면 None(참조 무결성은 별도 소관)."""
        distractor_map = [{"choice_index": 0, "misconception_id": ""}]
        assert resolve_misconception_from_choice(distractor_map, 0) is None

    def test_entry_missing_misconception_id_returns_none(self) -> None:
        distractor_map = [{"choice_index": 0}]
        assert resolve_misconception_from_choice(distractor_map, 0) is None

    def test_all_malformed_entries_returns_none(self) -> None:
        distractor_map = ["bad", 42, {"choice_index": 9}]
        assert resolve_misconception_from_choice(distractor_map, 0) is None


# ══════════════════════════════════════════════════════════════════════════
# 회수 확장 (2026-09-21) — 고립 브랜치 087859bd 이후 main이 갖게 된 오개념 파이프라인에
# 맞춘 두 변환기. 브랜치 판은 결과를 `AttemptSubmitResponse.matched_misconception_id`라는
# *별도 응답 필드*로 냈으나, 그 사이 main에 후보→증거→가설 좌석이 생겼으므로 그대로
# 회수하면 이중 진실원천이 된다(ASM-06 승계 제약). 아래 두 함수가 기존 좌석으로 흘려보내는
# 유일한 경로이며, 여기서 그 계약을 봉인한다.
# ══════════════════════════════════════════════════════════════════════════

#: 정본 카탈로그에 **실재**하는 id — 위 순수 함수 테스트의 가짜 id(`mis.*`)와 대비된다.
#: 두 변환기는 카탈로그 실재를 요구하므로 여기서는 실물을 쓴다(그 차이 자체가 아래
#: `TestCatalogMembership`의 검증 대상이다).
_REAL_MID = "absolute-value-keeps-sign"


def _map(index: int, mid: str) -> list[dict[str, object]]:
    return [{"choice_index": index, "misconception_id": mid}]


class TestDistractorLinkMatches:
    def test_matching_choice_yields_single_gated_match(self) -> None:
        matches = distractor_link_matches(_map(1, _REAL_MID), 1)
        assert [m.misconception.id for m in matches] == [_REAL_MID]
        assert matches[0].confidence == DISTRACTOR_LINK_CONFIDENCE

    def test_no_index_yields_no_match(self) -> None:
        assert distractor_link_matches(_map(1, _REAL_MID), None) == []

    def test_non_matching_index_yields_no_match(self) -> None:
        assert distractor_link_matches(_map(1, _REAL_MID), 0) == []


class TestCatalogMembership:
    def test_unknown_misconception_id_yields_no_match(self) -> None:
        """카탈로그에 없는 id는 후보가 되지 못한다 — 하류가 *조용히* 버리기 때문이다.

        `apply_candidates`·`curate_hypothesis`는 미등록 id를 무시하므로, 여기서 거르지
        않으면 "후보 1건 산출"과 "가설 0건 반영"이 어긋난 채 아무도 모르게 남는다.
        """
        assert "mis.sign-error" not in CATALOG_BY_ID  # 위 순수 함수 테스트가 쓰는 가짜 id
        assert distractor_link_matches(_map(1, "mis.sign-error"), 1) == []

    def test_pure_lookup_still_returns_unknown_id(self) -> None:
        """변별: 순수 조회는 카탈로그를 보지 않는다 — 거르는 주체가 변환기임을 고정한다."""
        assert resolve_misconception_from_choice(_map(1, "mis.sign-error"), 1) == "mis.sign-error"


class TestQualityGateReuse:
    def test_confidence_clears_the_shared_floor(self) -> None:
        """상수가 게이트 floor 이상이라 통과한다 — 이 관계가 깨지면 채널이 조용히 죽는다."""
        probe = apply_match_quality_gate(
            [
                MisconceptionMatch(
                    misconception=CATALOG_BY_ID[_REAL_MID],
                    confidence=DISTRACTOR_LINK_CONFIDENCE,
                )
            ]
        )
        assert probe.no_confident_match is False

    def test_confidence_below_floor_would_empty_the_channel(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """**변별력**: 상수를 floor 미만으로 낮추면 실제로 후보가 비워지는가.

        게이트 재사용이 장식이 아님을 보이는 주입이다 — 이 단언이 없으면 "게이트를 통과시켰다"는
        주장이 `gate_passed=True`를 상수로 박은 것과 화면상 구분되지 않는다.
        """
        monkeypatch.setattr(
            "whymath_backend.l4.misconception.distractor_link.DISTRACTOR_LINK_CONFIDENCE",
            0.1,
        )
        assert distractor_link_matches(_map(1, _REAL_MID), 1) == []

    def test_distractor_channel_does_not_rescue_weak_text_candidates(self) -> None:
        """채널을 **따로** 게이트하는 이유 — 섞으면 약한 텍스트 후보가 함께 통과한다.

        게이트 ①은 top-1 하나로 목록 전체를 판정하므로, 신뢰도 0.8짜리 선지 후보를 약한
        텍스트 후보와 같은 호출에 넣으면 원래 floor에서 걸러졌어야 할 것까지 살아난다.
        여기서 그 합산 호출이 실제로 그런 결과를 내는지 보이고(반례), 구현이 그 경로를
        쓰지 않는다는 사실을 위 `distractor_link_matches` 계약과 대비시킨다.
        """
        weak = MisconceptionMatch(
            misconception=CATALOG_BY_ID["area-perimeter-confusion"], confidence=0.2
        )
        strong = MisconceptionMatch(
            misconception=CATALOG_BY_ID[_REAL_MID], confidence=DISTRACTOR_LINK_CONFIDENCE
        )
        # 약한 후보만 넣으면 게이트가 비운다(정상).
        assert apply_match_quality_gate([weak]).matches == []
        # 강한 선지 후보를 top-1으로 섞으면 약한 후보까지 통과한다 — 그래서 섞지 않는다.
        mixed = apply_match_quality_gate([strong, weak]).matches
        assert [m.misconception.id for m in mixed] == [_REAL_MID, "area-perimeter-confusion"]
        # 구현은 선지 채널을 단독으로만 게이트하므로 텍스트 후보를 실어 나르지 않는다.
        assert [m.misconception.id for m in distractor_link_matches(_map(1, _REAL_MID), 1)] == [
            _REAL_MID
        ]


class TestDistractorLinkCandidates:
    def test_candidate_carries_gate_passed_and_no_text_quality_flags(self) -> None:
        (candidate,) = distractor_link_candidates(_map(2, _REAL_MID), 2)
        assert candidate.misconception_id == _REAL_MID
        assert candidate.confidence == DISTRACTOR_LINK_CONFIDENCE
        assert candidate.gate_passed is True
        # 둘 다 *텍스트 입력*의 결함 축이라 선지 탭에는 대응물이 없다 — 없는 결함을 표시하지 않는다.
        assert candidate.low_quality is False
        assert candidate.attribution_unclear is False

    def test_no_match_yields_empty_tuple(self) -> None:
        assert distractor_link_candidates(_map(2, _REAL_MID), 3) == ()

    def test_confidence_is_not_certainty(self) -> None:
        """**오답을 오개념으로 단정 금지**(ASM-06 승계 제약)의 수치 집행.

        학생이 그 보기를 골랐다는 *사실*은 확실하지만 귀속은 아니다 — 찍었을 수 있다.
        1.0이면 가설 저장소에서 감쇠·반박이 사실상 무력해진다.
        """
        assert 0.0 < DISTRACTOR_LINK_CONFIDENCE < 1.0


class TestBooleanIndexIsNotAnIndex:
    """`bool`은 `int`의 서브클래스다 — 잘못 실린 불린이 조용히 인덱스로 해석되면 안 된다."""

    def test_true_is_not_index_one(self) -> None:
        assert resolve_misconception_from_choice(_map(1, _REAL_MID), True) is None

    def test_false_is_not_index_zero(self) -> None:
        assert resolve_misconception_from_choice(_map(0, _REAL_MID), False) is None

    def test_boolean_entry_index_does_not_match_integer_choice(self) -> None:
        assert (
            resolve_misconception_from_choice(
                [{"choice_index": True, "misconception_id": _REAL_MID}], 1
            )
            is None
        )


class TestMisconceptionIdMustBeString:
    def test_non_string_misconception_id_returns_none(self) -> None:
        """숫자·리스트 등 비문자열 id는 형태 불량 — `str()`로 억지 변환하지 않는다."""
        assert (
            resolve_misconception_from_choice([{"choice_index": 0, "misconception_id": 7}], 0)
            is None
        )


@pytest.mark.parametrize("index", [0, 1, 2, 3])
def test_every_mapped_index_resolves_independently(index: int) -> None:
    """인덱스별 독립 해소 — 순회 순서·조기 반환이 특정 위치만 맞추고 있지 않은지."""
    ids = [
        "absolute-value-keeps-sign",
        "area-perimeter-confusion",
        "angle-sum-non-triangle",
        "addition-multiplication-rule-confused",
    ]
    dmap: list[dict[str, object]] = [
        {"choice_index": i, "misconception_id": mid} for i, mid in enumerate(ids)
    ]
    assert resolve_misconception_from_choice(dmap, index) == ids[index]
    assert [m.misconception.id for m in distractor_link_matches(dmap, index)] == [ids[index]]
