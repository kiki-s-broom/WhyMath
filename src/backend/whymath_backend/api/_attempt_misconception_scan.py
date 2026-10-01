"""오답 1건 → 오개념 후보 훑기 — 두 채점 경로가 함께 쓰는 좌석.

출처: EOS-104 · ASM-06 · EOS-123 · 이동 EOS-146.

`api/me.py`(클라 자가보고 `/v1/me/attempts`)에 있던 훑기 함수를 **그대로
옮겼다**(동작 불변 — 이름에서 밑줄 접두만 뗐다). 코치 서버 판정 오답 적재
(EOS-146)가 같은 훑기를 같은 조건으로 돌려야 두 경로가 같은 입력에 같은 R3
입력을 내기 때문이다. EOS-134가 상태 머신 진입점에서 세운 규율과 같다 —
경로마다 훑기를 따로 적으면 한쪽만 채널을 늘렸을 때 비대칭이 조용히 재발한다.

로거 이름은 `whymath.api.me`를 **일부러 유지**한다. 이 함수의 경고를 그
이름으로 보던 운영 필터가 이동으로 조용히 끊기지 않게 한다(침묵 실패 금지).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.config import get_settings
from whymath_backend.db.models.problem import Problem
from whymath_backend.l4.misconception.distractor_link import distractor_link_candidates
from whymath_backend.l4.misconception.hypothesis import MisconceptionHypothesis
from whymath_backend.schema.assessment_evidence import (
    MisconceptionCandidate,
    MisconceptionScan,
)
from whymath_backend.schema.verification_capabilities import AttemptMisconceptionDetector

__all__ = [
    "NOT_SCANNED",
    "AttemptMisconceptionScan",
    "merge_misconception_candidates",
    "scan_attempt_misconceptions",
    "this_attempt_misconceptions_from",
]

_logger = logging.getLogger("whymath.api.me")


@dataclass(frozen=True)
class AttemptMisconceptionScan:
    """`scan_attempt_misconceptions`의 결과 — 훑기 3상태 + 게이트 통과 후보.

    능력 구현이 돌려주는 리치 타입을 Core 안에 들이지 않으려는 좌석이다. Core가 읽는 것은
    `scan`·`candidates` 둘뿐이므로(능력 Protocol이 노출하는 것과 동일) 여기서 그 둘만 고정한다.
    """

    scan: MisconceptionScan
    candidates: tuple[MisconceptionCandidate, ...]


NOT_SCANNED = AttemptMisconceptionScan(scan=MisconceptionScan.NOT_RUN, candidates=())
"""훑지 않음 — 답안·선지 인덱스 미제출·문항 부재·킬 스위치 OFF. **"오개념 없음"이 아니다.**

정답은 사유가 아니다 — 정답 회차도 오답과 같은 조건으로 훑는다(EOS-123)."""


async def scan_attempt_misconceptions(
    session: AsyncSession,
    detector: AttemptMisconceptionDetector,
    *,
    problem_id: uuid.UUID,
    answer: str | None,
    selected_choice_index: int | None,
) -> AttemptMisconceptionScan:
    """채점 1건에서 오개념 후보를 훑는다 — 재료가 없으면 훑지 않았다고 말한다.

    **독립된 두 채널**을 훑고 결과를 합친다. 둘은 재료도 실패 모드도 다르므로 서로의 실행
    조건이 되지 않는다 — 한쪽이 못 돌아도 다른 쪽은 돈다:

      ① **텍스트 채널**(EOS-104): 과목 어댑터가 문항 지문 + 제출 답안(자유 텍스트)을 이어
         오류 서명을 읽는다. 지문이나 답안이 없으면 이 채널은 돌지 않는다.
      ② **선지 채널**(ASM-06): 학생이 고른 보기 인덱스를 그 문항의 `distractor_map`에
         대조해 역추적한다(`l4.misconception.distractor_link`). 답안 텍스트도 지문도 필요
         없다 — 인덱스와 매핑만 있으면 된다. 그래서 "보기만 탭하고 아무것도 쓰지 않은"
         제출에서 **유일하게** 도는 채널이다(종전엔 그런 제출이 통째로 not_run이었다).

    훑지 않는 조건(두 채널 *모두* 미실행일 때만 `NOT_RUN`): 킬 스위치 OFF ·
    (텍스트 채널) 답안 미제출·문항 지문 부재(또는 지문에서 식 추출 실패) · (선지 채널) 인덱스
    미보고·선지 플래그 OFF·매핑 부재. 이들을 빈 후보 리스트로 뭉뚱그리지 않는 이유는, 그러면
    하류가 *미측정*을 *측정된 0*으로 읽기 때문이다(`MisconceptionScan` 3상태의 존재 이유).

    **정답 회차도 같은 조건으로 훑는다(EOS-123).** 이 함수는 정오답을 받지 않는다. 종전에는
    정답을 두 채널 모두에서 조기 반환했는데, 그러면 호출자가 정답 회차의 가설을 전혀 움직이지
    못해 "다르게 틀리면 신뢰가 내려가고 맞히면 그대로"인 역방향 비대칭이 생겼다(페르소나 C
    0.85 → 0.74 → 0.74). 정답 전용 조건을 따로 두지 않고 조기 반환만 걷은 이유는, 그래야 정답이
    감쇠를 받는 조건과 오답이 감쇠를 받는 조건이 **이 함수 하나로 같게** 정해지기 때문이다 —
    정답 쪽 조건이 넓으면 같은 문항에서 오답은 못 내리는데 정답만 내리는 거울상 비대칭이 된다.

    정답 답안은 텍스트 채널의 ⓪ 거짓 등식 가드가 막아 후보가 없는 것이 정상이고(`RAN_NO_CANDIDATE`),
    정답 선지 인덱스는 `distractor_map`(오답 선지만 담는다)에 없어 역시 후보가 없다. 정답으로
    보고됐는데 후보가 나오면 그것은 보고와 서버 관측의 **충돌**이다. 훑기 결과를 가설에 어떻게
    반영할지(충돌이면 보류)는 호출자가 `l4.misconception.attempt_hypothesis_policy`로 정한다 —
    이 함수는 본 것을 그대로 보고할 뿐이다.
    """
    if not get_settings().l4_attempt_misconception_scan_enabled:
        return NOT_SCANNED

    # ── 채널 ②(선지) — 텍스트보다 먼저. DB 1회(distractor_map 단일 컬럼)이고, 인덱스를
    # 보고하지 않았으면 그 조회조차 하지 않는다(reactive retrieval — 카탈로그·다른 오개념을
    # 미리 싣지 않는다·CLAUDE.md 협상 불가).
    choice_candidates: tuple[MisconceptionCandidate, ...] = ()
    choice_ran = False
    if selected_choice_index is not None and get_settings().l4_distractor_link_enabled:
        distractor_map = await session.scalar(
            select(Problem.distractor_map).where(Problem.problem_id == problem_id)
        )
        # 매핑이 아예 없는 문항이면 이 채널은 *돌 재료가 없다* — 돌았는데 0건인 것과 구분해
        # ran으로 세지 않는다(작동한 비율을 부풀리지 않는다).
        if distractor_map:
            choice_ran = True
            choice_candidates = distractor_link_candidates(distractor_map, selected_choice_index)

    # ── 채널 ①(텍스트) — 기존 EOS-104 경로. 조건·폴백·로그 전부 불변.
    text_candidates: tuple[MisconceptionCandidate, ...] = ()
    text_scan = MisconceptionScan.NOT_RUN
    if answer is not None:
        question_text = await session.scalar(
            select(Problem.question_text).where(Problem.problem_id == problem_id)
        )
        if question_text:
            # 능력은 **주입받는다**(app.state 등록분·EOS-89 push 형태) — Core가 합성 루트를
            # 이름으로 알지 않는다. Core가 아는 것은 인터페이스 타입 하나뿐이다.
            try:
                result = detector.scan_attempt_answer(
                    question_text=question_text, student_answer=answer
                )
            except Exception as exc:  # noqa: BLE001 — 관측이 채점을 깨뜨리지 않는다(아래 주석)
                # **never-break**: 이 시점에 attempt는 *이미 commit됐다*. 훑기는 관측이므로
                # 여기서 터지면 기록된 제출이 500으로 돌아가 학생이 다시 풀게 된다 — 관측
                # 실패가 채점 실패를 만드는 셈. 그래서 삼키되, **예외 타입명을 반드시 남긴다**
                # (CLAUDE.md 침묵 실패 금지 — 무타입 경고가 langfuse v2 쓰기 8일 무증상 전멸의
                # 원인이었다). 학생 답안·지문은 로그에 넣지 않는다(PII).
                _logger.warning(
                    "오개념 훑기 실패 — 채점은 계속한다(텍스트 채널 not_run). "
                    "exc_type=%s problem_id=%s",
                    type(exc).__name__,
                    problem_id,
                )
            else:
                text_scan = result.scan
                text_candidates = tuple(result.candidates)

    # ── 합류. 같은 오개념을 두 채널이 함께 지목하면 *더 높은 신뢰도 하나*만 남긴다 — 같은
    # 사실의 사본 둘이 가설 저장소에서 서로를 덮어쓰는 순서 의존을 만들지 않기 위해서다.
    merged = merge_misconception_candidates(choice_candidates, text_candidates)
    text_ran = text_scan is not MisconceptionScan.NOT_RUN
    if not choice_ran and not text_ran:
        return NOT_SCANNED
    scan = MisconceptionScan.RAN_WITH_CANDIDATES if merged else MisconceptionScan.RAN_NO_CANDIDATE
    return AttemptMisconceptionScan(scan=scan, candidates=merged)


def merge_misconception_candidates(
    *channels: Sequence[MisconceptionCandidate],
) -> tuple[MisconceptionCandidate, ...]:
    """여러 채널의 오개념 후보를 id 기준으로 합친다 — 중복은 신뢰도 높은 쪽만, 순서는 결정론.

    앞 채널의 등장 순서를 보존하고(첫 등장 위치 고정), 같은 id가 뒤에서 더 높은 신뢰도로
    다시 나오면 *그 자리에서* 값만 교체한다. 정렬을 새로 하지 않는 이유는 각 채널이 이미
    자기 기준으로 정렬돼 왔고, 여기서 재정렬하면 채널 간 신뢰도 척도가 서로 다른데도 한 줄로
    비교하는 셈이 되기 때문이다(`semantic_similarity`와 `confidence`를 섞지 않는 것과 동형).
    """
    merged: dict[str, MisconceptionCandidate] = {}
    for channel in channels:
        for candidate in channel:
            existing = merged.get(candidate.misconception_id)
            if existing is None or candidate.confidence > existing.confidence:
                merged[candidate.misconception_id] = candidate
    return tuple(merged.values())


def this_attempt_misconceptions_from(
    active_hypotheses: Sequence[MisconceptionHypothesis],
    candidates: Sequence[MisconceptionCandidate],
) -> tuple[tuple[str, float], ...]:
    """가설 갱신 결과에서 **이번 스캔의 후보에 해당하는 것만** 뽑아 R3 입력 (id, 신뢰)로 만든다.

    두 채점 경로(`/v1/me/attempts` · 코치 서버 판정 오답 EOS-146)가 같은 규칙으로 R3 입력을
    만들도록 한 곳에 둔다(EOS-138 ②). 갱신된 가설 전부가 아니라 **이번 스캔의 게이트 통과 후보
    id에 든 것**만 — 갱신 세트에는 이번에 증거를 못 받고 감쇠만 한 옛 가설도 들어 있기 때문이다.
    신뢰는 후보 원값이 아니라 **갱신 후 가설 신뢰**다: 같은 오개념이 앞서 쌓였다면 이번 증거로
    강화된 값이 교정 경로의 근거가 된다. `apply_candidates`와 같은 조건(`gate_passed`)으로
    거른다 — 저장소가 무시한 후보를 여기서 되살리지 않는다.

    하한(0.7 초과)·정렬은 여기서 하지 않는다 — 조립기(`build_attempt_evidence`)가 한다.
    """
    scanned_ids = {c.misconception_id for c in candidates if c.gate_passed}
    return tuple(
        (h.misconception_id, h.confidence)
        for h in active_hypotheses
        if h.misconception_id in scanned_ids
    )
