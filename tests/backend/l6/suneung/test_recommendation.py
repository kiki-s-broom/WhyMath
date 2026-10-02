"""L6 수능 적응 추천 단위테스트 — 게이팅(진실 게이트) × IRT CAT 결합·가중·인덱스 역매핑.

검증(`recommend_suneung_index`·`suneung_item_weight`):
  ① 적격 0(저작권 차단 / 비응시 페르소나 D·E / 수능 신호 전무) → None.
  ② 평가원 출처는 시그니처가 있어도 진실 게이트가 제외한다(저작권 재검증).
  ③ 동일 가중이면 b≈θ 후보 선택(IRT 정보량 최대 — CAT 본질).
  ④ 가중 단조성 — 동일 b에서 시그니처 보유 > 미보유·권위 가중 높은 쪽 우선.
  ⑤ extra_weights 곱 결합·길이 불일치 ValueError(l2 길이 계약 미러).
  ⑥ b 소스(보정 b·전문가 난이도) 없는 후보 제외 + 원 인덱스 역매핑 보존.
  ⑦ 동률 → 낮은 인덱스(l2 결정론 계승).
  ⑧ `suneung_item_weight`는 항상 양수(전-0 퇴화 방지)·priority 단조 보존.

합성 픽스처만(실데이터 0). `_problem(**over)` 빌더는 `test_gating.py` 패턴 답습.
레이어(CLAUDE.md): 테스트는 L1(schema)·L6(l6.suneung)만 import한다(추천 내부의 L2 호출은
구현 세부 — 결과 계약만 검증).
"""

from __future__ import annotations

import pytest

from whymath_backend.l6.suneung.recommendation import (
    recommend_suneung_index,
    suneung_item_weight,
)
from whymath_backend.schema.enums import (
    Curriculum,
    ExamType,
    Persona,
    ReviewStatus,
    SignaturePattern,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem import Problem


def _problem(**over: object) -> Problem:
    """본문 보유가 허용되는 최소 자체생성 Problem 빌더(합성 픽스처 — test_gating.py 답습)."""
    kwargs: dict[str, object] = {
        "source_type": SourceType.자체생성,
        # PB-03 — 검수 노출 게이트(`is_review_cleared`) 추가로 기본값도 approved가 필요.
        "review_status": ReviewStatus.approved,
        "curriculum_version": Curriculum.REVISION_2022,
        "valid_from_year": 2022,
        "subject": Subject.미적분,
        "unit_codes": ["CAL-INT-DEF"],
        # EOS-31 — 수능 출제 범위 축(범위 안 코드). 주입이 없으면 게이트가 `UNKNOWN`으로 거절한다.
        "achievement_standard_codes": ["[12대수01-01]"],
    }
    kwargs.update(over)
    return Problem(**kwargs)  # type: ignore[arg-type]


def _eligible(**over: object) -> Problem:
    """수능 적격(수능 exam_type 신호) + 난이도 b 보유(난이도 3.0)인 기본 후보."""
    kwargs: dict[str, object] = {"exam_type": ExamType.수능, "difficulty_overall": 3.0}
    kwargs.update(over)
    return _problem(**kwargs)


# ──────────────────────────────────────────────────────────────────────
# suneung_item_weight — 양수 보장·단조성
# ──────────────────────────────────────────────────────────────────────
class TestSuneungItemWeight:
    def test_always_positive_even_with_zero_priority(self) -> None:
        """신호 전무(priority 0.0) 문항도 가중 1.0(> 0) — 전-0 퇴화 방지 바닥."""
        bare = _problem()  # 권위·시그니처·난이도 전부 없음 → priority 0.0
        assert suneung_item_weight(bare) == 1.0
        assert suneung_item_weight(bare) > 0.0

    def test_preserves_priority_monotonicity(self) -> None:
        """priority가 큰 문항이 가중도 크다(1+x 단조증가 — 상대 순서 보존)."""
        high = _problem(
            exam_authority_weight=1.0,
            signature_patterns=[SignaturePattern.COMPOUND_CHOICES],
            difficulty_overall=4.0,
        )  # priority 2.0+1.0+4.0=7.0 → 가중 8.0
        low = _problem(difficulty_overall=2.0)  # priority 2.0 → 가중 3.0
        assert suneung_item_weight(high) == 8.0
        assert suneung_item_weight(low) == 3.0
        assert suneung_item_weight(high) > suneung_item_weight(low)


# ──────────────────────────────────────────────────────────────────────
# recommend_suneung_index — 적격 축소(진실 게이트·b 필수)
# ──────────────────────────────────────────────────────────────────────
class TestEligibilityReduction:
    def test_no_eligible_candidates_returns_none(self) -> None:
        """적격 0 — 저작권 차단·신호 전무만 있으면 None(추천 불가)."""
        blocked = _problem(  # 평가원 → 저작권 게이트 차단
            source_type=SourceType.평가원,
            exam_type=ExamType.수능,
            difficulty_overall=3.0,
        )
        no_signal = _problem(difficulty_overall=3.0)  # 수능 신호 전무
        assert recommend_suneung_index(0.0, [blocked, no_signal]) is None

    def test_empty_candidates_returns_none(self) -> None:
        """빈 후보 → None."""
        assert recommend_suneung_index(0.0, []) is None

    def test_non_target_personas_get_none(self) -> None:
        """비응시 페르소나(D 학종·E 영재) → 적격 후보가 있어도 전부 차단·None."""
        candidates = [_eligible(), _eligible()]
        for persona in (Persona.D_학종고2, Persona.E_홈스쿨링영재):
            assert recommend_suneung_index(0.0, candidates, persona) is None, persona

    def test_copyright_blocked_even_with_signature(self) -> None:
        """평가원 출처는 시그니처 패턴이 있어도 진실 게이트가 제외한다(저작권 재검증).

        api SQL 사전필터가 놓쳐도(예: 사전필터 변경 사고) 게이트가 재차단하는 계약 —
        수능 모드 핵심(평가원 기출 본문 절대 노출 불가·자체생성 동등문제만).
        """
        blocked = _problem(
            source_type=SourceType.평가원,
            signature_patterns=[SignaturePattern.GRAPH_SHAPE_INFERENCE],
            difficulty_overall=3.0,
        )
        assert recommend_suneung_index(0.0, [blocked]) is None

    def test_candidate_without_b_source_excluded(self) -> None:
        """보정 b·전문가 난이도 둘 다 없는 후보는 제외(정보량 계산 불가)."""
        no_b = _eligible(difficulty_overall=None)  # 수능 신호는 있으나 b 소스 없음
        assert recommend_suneung_index(0.0, [no_b]) is None

    def test_excluded_candidates_preserve_original_index(self) -> None:
        """앞이 제외(차단·b 없음)돼도 반환은 *원 인덱스*다(역매핑 보존)."""
        blocked = _problem(source_type=SourceType.평가원, difficulty_overall=3.0)
        no_b = _eligible(difficulty_overall=None)
        ok = _eligible()
        # 인덱스 0(차단)·1(b 없음) 제외 → 적격은 인덱스 2뿐 → 2 반환(축소 인덱스 0 아님).
        assert recommend_suneung_index(0.0, [blocked, no_b, ok]) == 2


# ──────────────────────────────────────────────────────────────────────
# recommend_suneung_index — IRT CAT 선택(정보량·가중)
# ──────────────────────────────────────────────────────────────────────
class TestCatSelection:
    def test_equal_weights_pick_b_nearest_theta(self) -> None:
        """동일 가중(같은 신호·난이도 라벨)이면 b가 θ에 가까운 후보(정보량 최대) 선택.

        가중을 같게 두려고 difficulty_overall은 3.0으로 고정하고(priority 동일), b만
        보정값(irt_difficulty_b)으로 갈라놓는다 — b는 보정값 우선(resolve 계약).
        """
        far = _eligible(irt_difficulty_b=2.0)  # |b-θ|=2
        near = _eligible(irt_difficulty_b=0.0)  # |b-θ|=0 → 정보량 최대
        assert recommend_suneung_index(0.0, [far, near]) == 1

    def test_signature_weight_wins_at_same_b(self) -> None:
        """동일 b(같은 난이도)에서 시그니처 보유 문항이 미보유보다 우선(가중 단조성)."""
        without_sig = _eligible()
        with_sig = _eligible(signature_patterns=[SignaturePattern.CONDITION_LIST])
        # 정보량 동일·가중은 with_sig가 큼(+1.0) → 인덱스 1 선택(동률이면 0이었을 것).
        assert recommend_suneung_index(0.0, [without_sig, with_sig]) == 1

    def test_higher_authority_wins_at_same_b(self) -> None:
        """동일 b에서 출처 권위 가중 높은 쪽(수능 1.0 > 학평 0.5)이 우선."""
        hakpyeong = _eligible(exam_type=ExamType.학평, exam_authority_weight=0.5)
        suneung = _eligible(exam_authority_weight=1.0)
        assert recommend_suneung_index(0.0, [hakpyeong, suneung]) == 1

    def test_tie_picks_lower_index(self) -> None:
        """완전 동률(같은 b·같은 가중)은 낮은 인덱스(l2 결정론 계승)."""
        assert recommend_suneung_index(0.0, [_eligible(), _eligible(), _eligible()]) == 0


# ──────────────────────────────────────────────────────────────────────
# recommend_suneung_index — extra_weights(약점 가중) 곱 결합
# ──────────────────────────────────────────────────────────────────────
class TestExtraWeights:
    def test_extra_weights_multiply_and_reorder(self) -> None:
        """동률 후보에 extra_weights를 곱하면 큰 가중 쪽이 선택된다(곱 결합)."""
        candidates = [_eligible(), _eligible()]
        # extra 없이는 동률 → 0. extra [1.0, 2.0] 곱 결합 → 1.
        assert recommend_suneung_index(0.0, candidates) == 0
        assert recommend_suneung_index(0.0, candidates, extra_weights=[1.0, 2.0]) == 1

    def test_extra_weights_indexed_by_original_position(self) -> None:
        """extra_weights는 *원 인덱스* 기준으로 대응한다(제외 후보가 앞에 있어도)."""
        blocked = _problem(source_type=SourceType.평가원, difficulty_overall=3.0)
        a, b = _eligible(), _eligible()
        # 원 인덱스: 0=차단, 1=a, 2=b. extra는 원 인덱스 2(b)만 크게 → 2 선택.
        result = recommend_suneung_index(0.0, [blocked, a, b], extra_weights=[9.0, 1.0, 2.0])
        assert result == 2

    def test_length_mismatch_raises_value_error(self) -> None:
        """extra_weights 길이가 candidates와 다르면 ValueError(l2 길이 계약 미러)."""
        with pytest.raises(ValueError, match="extra_weights"):
            recommend_suneung_index(0.0, [_eligible()], extra_weights=[1.0, 2.0])

    def test_length_mismatch_checked_before_reduction(self) -> None:
        """길이 검증은 적격 축소 *전*에 수행 — 후보가 전부 부적격이어도 불일치는 오류."""
        blocked = _problem(source_type=SourceType.평가원, difficulty_overall=3.0)
        with pytest.raises(ValueError, match="extra_weights"):
            recommend_suneung_index(0.0, [blocked], extra_weights=[])
