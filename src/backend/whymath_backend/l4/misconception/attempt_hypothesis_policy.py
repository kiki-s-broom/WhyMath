"""채점 1회차가 오개념 **가설**에 무엇을 하는가 — 정오답 × 훑기 3상태의 교수학 정책 (EOS-123).

왜 따로 두는가
────────────────────────────────────────────────────────────────────────────
오개념 가설에는 원장이 둘 있다. **감쇠 시계**(`hypothesis_store.apply_candidates` →
`update_hypotheses`: 증거 없이 흐른 턴만큼 신뢰를 내린다)와 **증거 그래프**(`evidence_links` ·
`net_support`: 반박·해소 판정)다. 채점 제출 경로(`POST /v1/me/attempts`)가 건드리는 것은
감쇠 시계뿐이고, 반박·확정 권한은 서버 도구 검증을 거친 코치 경로가 소유한다(EOS-104 ④).

종전에는 "훑었으면 갱신"이라는 한 줄이 API 파일에 있었고, 정답은 훑기 함수가 조기 반환해
아예 훑지 않았다. 그래서 **다르게 틀린 답은 신뢰를 내리는데 맞힌 답은 내리지 못하는** 방향이
거꾸로 된 비대칭이 생겼다(페르소나 C: 오개념 미관측 오답 0.85 → 0.74 · 바로 뒤 정답
0.74 → 0.74). 어떤 회차가 시계를 돌리는가는 교수학 정책이므로 여기 L4 순수 함수로 둔다 —
API는 이 값으로만 분기하고, 향후 다른 경로도 같은 규칙을 재사용할 수 있다.

6칸 정책 (판정문 `docs/reviews/eos123_correct_attempt_refutation_judgment_2026-09-28.md` §0)
────────────────────────────────────────────────────────────────────────────
| 회차 | 훑기 결과           | 행동            | 가설                                  |
|------|---------------------|-----------------|---------------------------------------|
| 오답 | ran_with_candidates | `APPLY`         | 후보 강화 · 나머지 1턴 감쇠            |
| 오답 | ran_no_candidate    | `APPLY`         | 전 활성 가설 1턴 감쇠(후보 0건)        |
| 오답 | not_run             | `NONE`          | 무변화                                |
| 정답 | ran_no_candidate    | `DECAY_ONLY`    | 전 활성 가설 1턴 감쇠                  |
| 정답 | ran_with_candidates | `HOLD_CONFLICT` | 무변화 — 보고와 관측의 충돌            |
| 정답 | not_run             | `NONE`          | 무변화                                |

- **정답의 감쇠는 증거가 아니라 활동 시계다.** 정답은 "그 오개념이 넘어섰다"가 아니고, 비겨냥
  문항의 정답은 그 오개념과 접촉조차 없다. 다만 비교 기준인 "오개념 미관측 오답"도 같은 처지라
  (텍스트 채널이 보는 거짓형은 2026-09 기준 카탈로그 67종 중 2종뿐) 현행 오답 감쇠도 이미
  활동 시계다.
  같은 관측 조건에서 오답에 주던 시계를 정답에도 준다 — 낙인 방지(stale 가설 정리)와 대칭.
  강도는 오답과 같은 1턴을 넘기지 않는다. 관련성·독립성 축은 `MISC-36`이 소유한다.
- **발동 조건은 여기서 만들지 않는다.** 정답이 `ran_no_candidate`가 되는 조건은 오답과 같은
  훑기 함수(`api/_attempt_misconception_scan.py::scan_attempt_misconceptions`)가
  정한다. 정답 전용 게이트를 따로 두면
  같은 문항에서 오답은 못 내리는데 정답만 내리는 거울상 비대칭이 생긴다(독립 비판 F1).
- **충돌은 거부권으로만 쓴다(`HOLD_CONFLICT`).** 정답으로 보고됐는데 서버가 그 답에서 오개념을
  읽었다면(그 오개념의 오답 선지 인덱스 · 그 오개념의 거짓형 답), 그 회차가 그 오개념을 거꾸로
  내리지 않게 막는다. 강화에는 쓰지 않는다 — 지문식 추출 휴리스틱에 실측 오탐이 있어서다
  (유니코드 마이너스 지문에서 참 정답이 후보로 잡힌다). 오탐의 비용은 "감쇠 1회 보류"다.
- **복습 코칭은 `APPLY`에서만.** 정답 회차는 훑어도 코칭을 만들지 않는다 — 이번 관측은 그
  오개념과 반대 방향이므로 복습 권유는 증거를 거스르고 정서 안전을 해친다(MISC-35 결론 유지).

이 모듈은 DB·I/O가 없다. 학생 원문을 받지 않는다(정오답 bool과 훑기 상태만).
"""

from __future__ import annotations

from enum import Enum
from types import MappingProxyType
from typing import Final

from whymath_backend.schema.assessment_evidence import MisconceptionScan

__all__ = [
    "ATTEMPT_HYPOTHESIS_POLICY",
    "AttemptHypothesisAction",
    "decide_attempt_hypothesis_action",
]


class AttemptHypothesisAction(str, Enum):
    """채점 1회차가 가설 원장(감쇠 시계)에 하는 일 — 4종."""

    APPLY = "apply"
    """오답이고 훑었다 — 후보로 가설을 갱신한다(후보 강화 · 증거를 못 받은 가설 1턴 감쇠).
    복습 코칭을 계산하는 유일한 행동이다."""

    DECAY_ONLY = "decay_only"
    """정답이고 훑었는데 후보가 없다 — 후보 없이 1턴 갱신한다(활성 가설 전부 1턴 감쇠).
    증거 그래프에는 쓰지 않는다(반증이 아니라 활동 시계). 코칭 없음."""

    HOLD_CONFLICT = "hold_conflict"
    """정답으로 보고됐는데 서버가 이 답에서 오개념 후보를 읽었다 — 보고와 관측의 충돌.
    가설을 건드리지 않는다(감쇠도 강화도 없음). 코칭 없음. 호출자는 충돌을 로그로 남긴다."""

    NONE = "none"
    """훑지 않았다(`not_run`) — 볼 재료가 없었으므로 가설을 건드리지 않는다."""


ATTEMPT_HYPOTHESIS_POLICY: Final[
    MappingProxyType[tuple[bool, MisconceptionScan], AttemptHypothesisAction]
] = MappingProxyType(
    {
        (False, MisconceptionScan.RAN_WITH_CANDIDATES): AttemptHypothesisAction.APPLY,
        (False, MisconceptionScan.RAN_NO_CANDIDATE): AttemptHypothesisAction.APPLY,
        (False, MisconceptionScan.NOT_RUN): AttemptHypothesisAction.NONE,
        (True, MisconceptionScan.RAN_NO_CANDIDATE): AttemptHypothesisAction.DECAY_ONLY,
        (True, MisconceptionScan.RAN_WITH_CANDIDATES): AttemptHypothesisAction.HOLD_CONFLICT,
        (True, MisconceptionScan.NOT_RUN): AttemptHypothesisAction.NONE,
    }
)
"""(정답 여부, 훑기 결과) → 행동. 6칸을 **전부 명시**한다 — 빠진 칸을 기본값으로 메우지 않는다.
훑기 상태가 새로 생기면 이 표에 없는 조합이 되어 `decide_attempt_hypothesis_action`이
`ValueError`로 멈춘다(조용히 어느 한쪽으로 접지 않는다)."""


def decide_attempt_hypothesis_action(
    *, is_correct: bool, scan: MisconceptionScan
) -> AttemptHypothesisAction:
    """채점 1회차의 정오답과 훑기 결과로 가설 행동을 정한다(순수·결정론).

    `is_correct`는 이 경로의 정오답 보고 값 그대로다(v1 클라이언트 보고 — 판정문 §1 ⑦).
    `bool`이 아니면 거부한다: `None`(모름)을 오답으로 접으면 모르는 회차가 가설을 움직인다
    (CLAUDE.md "모른다 ≠ 아니다").
    """
    if not isinstance(is_correct, bool):
        raise TypeError(f"is_correct는 bool이어야 한다: {type(is_correct).__name__}")
    try:
        return ATTEMPT_HYPOTHESIS_POLICY[(is_correct, scan)]
    except KeyError:
        raise ValueError(
            f"정책 표에 없는 회차 조합이다: is_correct={is_correct} scan={scan!r}"
        ) from None
