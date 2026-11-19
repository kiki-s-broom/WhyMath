"""RS-X1 특성화 — 수확 대기열 1순위: 학생 최종답 동치 판정(옛 자산).

대상(옛 자리 그대로 · 고치지 않는다):
- `whymath_backend.l3.verify_final_answer` — 최종답 3상태(correct·incorrect·unverifiable)
- `whymath_backend.l3.symbolic_equivalence` — 식 항등 4상태(identity·not_identity·undecidable·parse_error)

입력 10개는 명세 `golden/reports_rescue/P1/명세.md` ⑦ 그대로다(정상 6 · 경계 2 · 잘못된 입력 2).
기대값은 2026-11-19 main `2d12b938`에서 실제로 돌려 나온 출력이다. 맞는지는 묻지 않는다 —
바뀌지 않는지만 본다. 나중에 연결·복사할 때 동작이 바뀌면 이 테스트가 빨개진다.

옛 모듈은 이 테스트에서만 import한다(`src/backend/golden/`은 import하지 않는다 — 규칙 14).
입력은 모두 합성이다(학생 실데이터 0건 — 규칙 15).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from whymath_backend.l3.symbolic_equivalence import (
    identity_status_detail,
    verify_relation_chain,
)
from whymath_backend.l3.verify_final_answer import (
    budget_exceeded_result,
    verify_final_answer,
)


def _problem(**kw: Any) -> SimpleNamespace:
    """문항 스텁 — 명세의 `P(**kw)`. 5필드 중 적지 않은 것은 None이다."""
    fields: dict[str, Any] = {
        "answer": None,
        "choices": None,
        "question_format": None,
        "answer_format": None,
        "multiple_answers": None,
    }
    fields.update(kw)
    return SimpleNamespace(**fields)


_MC_CHOICES = ["1", "2", "3", "4"]

# (번호, 학생 답, 문항, 기대 상태, 기대 사유) — verify_final_answer 입력 8개
_FINAL_CASES: list[tuple[str, str, SimpleNamespace, str, str | None]] = [
    # N1 같은 정수 값
    ("N1", "3", _problem(answer="3"), "correct", None),
    # N2 등식으로 낸 답 ↔ 맨 값 정답(해집합 경로)
    ("N2", "x=3", _problem(answer="3"), "correct", None),
    # N3 식 정답 폴백 + 마지막 `=` 우변 떼기
    ("N3", "y=2x+1", _problem(answer="1+2x", answer_format="식"), "correct", None),
    # N4 값 불일치 → 상태와 사유 문자열
    ("N4", "4", _problem(answer="3"), "incorrect", "학생 최종답이 기대정답과 불일치"),
    # N5 객관식 + 수량 꼬리말 떼기
    (
        "N5",
        "2개",
        _problem(answer="2", choices=_MC_CHOICES, question_format="객관식"),
        "correct",
        None,
    ),
    # B1 분수 ↔ 소수
    ("B1", "1/2", _problem(answer="0.5"), "correct", None),
    # B2 원문자 라벨 — 명세 ⑤-8의 [추측]이 실제로 correct였다(NFKC가 ①을 1로 바꾼다)
    (
        "B2",
        "①",
        _problem(answer="1", choices=_MC_CHOICES, question_format="객관식"),
        "correct",
        None,
    ),
    # I1 수식이 아닌 글 → 판정 불가(오답이 아니다)
    (
        "I1",
        "모르겠어요!!",
        _problem(answer="3"),
        "unverifiable",
        "서버 검증 불가 — 판정 안전 회피",
    ),
]


@pytest.mark.parametrize(
    ("student", "problem", "state", "reason"),
    [c[1:] for c in _FINAL_CASES],
    ids=[c[0] for c in _FINAL_CASES],
)
def test_verify_final_answer_is_frozen(
    student: str, problem: SimpleNamespace, state: str, reason: str | None
) -> None:
    """최종답 판정의 상태와 사유가 고정값과 같다."""
    result = verify_final_answer(student, problem)
    assert result.state == state
    assert result.reason == reason


def test_n6_identity_detail_is_frozen() -> None:
    """N6 — 암묵 곱셈 `2(x+1)`과 `2x+2`는 항등이고 변수 불일치 표시가 없다."""
    detail = identity_status_detail("2(x+1)", "2x+2")
    assert detail.verdict == "identity"
    assert detail.variable_mismatch is False


def test_i2_relation_chain_with_comparison_raises() -> None:
    """I2 — 비교 기호가 섞인 체인은 ValueError(모듈 설명의 parse_error가 아니다 · 명세 ⑤-10)."""
    with pytest.raises(ValueError, match="등식\\(=\\) 체인만 지원"):
        verify_relation_chain("y=2x+1<=5")


def test_budget_exceeded_result_is_frozen() -> None:
    """시간 초과 고정값 — 인자가 없어 입력 10개 밖에서 한 줄로 고정한다(명세 ⑦ 끝)."""
    result = budget_exceeded_result()
    assert result.state == "unverifiable"
    assert result.reason == "계산 시간 상한 초과 — 서버 검증 불가"
