"""골든 패스 튜터 되묻기(GP-4) — 오답일 때 LLM 1회 호출로 소크라테스 질문을 만든다."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from golden.problems import Problem
from golden.store import TurnRow

# 옛 코드에서 가져온 것: 라우터 결정 + 프로바이더 팩토리(HARVEST.md)
from whymath_backend.l3.models import RoutingRequest
from whymath_backend.l3.providers.factory import build_cloud_provider
from whymath_backend.l3.router import Router
from whymath_backend.schema.enums import LicenseType

logger = logging.getLogger(__name__)

# 시스템 프롬프트 파일 — 저장소 루트의 golden/tutor_prompt.md
TUTOR_PROMPT_PATH = Path(__file__).resolve().parents[3] / "golden" / "tutor_prompt.md"

# 가짜 LLM·장애 대체 문장의 앞부분(공유 계약 — 뒤에 hint1을 붙인다)
FAKE_PREFIX = "어느 부분이 막히는지 한 가지만 말해 줄래? "

# LLM 호출 제한 시간(초)
LLM_TIMEOUT_S = 10.0


@dataclass(frozen=True)
class TutorReply:
    """튜터 되묻기 결과. degraded=True면 LLM 호출이 실패해 대체 문장을 쓴 것이다."""

    message: str
    degraded: bool


def _fake_message(problem: Problem) -> str:
    """가짜 LLM 문장 = 고정 질문 + 이 문제의 hint1."""
    return FAKE_PREFIX + problem["hint1"]


def build_user_prompt(problem: Problem, history: list[TurnRow], student_text: str) -> str:
    """LLM에 보낼 사용자 프롬프트. 문제 본문·hint1·이번 문제 대화(최대 3턴)·학생 입력만 담는다.

    닉네임·세션 ID는 넣지 않는다(미성년자 데이터 규칙). 정답도 넣지 않는다 — 모델이 모르면
    누설할 수도 없다.
    """
    lines = [
        f"문제: {problem['stem']}",
        f"참고 힌트(정답 아님, 그대로 읽지 말 것): {problem['hint1']}",
    ]
    for turn in history[-3:]:
        lines.append(f"학생: {turn.student_text}")
        lines.append(f"튜터: {turn.tutor_text}")
    lines.append(f"학생: {student_text}")
    lines.append("위 학생 말에 대한 튜터의 다음 한 마디를 써라.")
    return "\n".join(lines)


def _routing_request() -> RoutingRequest:
    """튜터 되묻기 1회의 라우팅 요청 — 라우터가 CLOUD_MID 결정을 내도록 신호를 채운다.

    문항은 자체 생성(WHYMATH_GENERATED)이라 반출 가능 등급으로 선언한다. 등급 게이트가
    막으면 결정이 LOCAL이 되고, 클라우드 좌석 호출이 실패해 대체 문장(degraded)으로 간다.
    """
    return RoutingRequest(
        task_type="coach",
        difficulty="medium",
        requires_reasoning=True,
        student_subscription="premium",
        budget_krw=100.0,
        conversation_phase="probing",
        data_licenses=(LicenseType.WHYMATH_GENERATED,),
    )


async def ask(problem: Problem, history: list[TurnRow], student_text: str) -> TutorReply:
    """되묻기 문장 1개를 만든다. LLM은 정확히 1회 부른다.

    GOLDEN_FAKE_LLM=1이면 LLM을 부르지 않는다(테스트·CI). 환경변수는 호출 시점에 읽는다.
    호출 실패(예외·10초 초과)는 삼키지 않고 예외 타입명을 로그에 남긴 뒤 대체 문장을 쓴다.
    """
    if os.environ.get("GOLDEN_FAKE_LLM") == "1":
        return TutorReply(message=_fake_message(problem), degraded=False)

    try:
        system = TUTOR_PROMPT_PATH.read_text(encoding="utf-8")
        decision = Router().route(_routing_request())
        provider = build_cloud_provider()
        result = await asyncio.wait_for(
            provider.generate(build_user_prompt(problem, history, student_text), system, decision),
            timeout=LLM_TIMEOUT_S,
        )
        message = result.text.strip()
        if not message:
            raise ValueError("LLM 응답이 빈 문자열이다")
    except Exception as exc:  # noqa: BLE001 — 학생 화면은 대체 문장으로 이어 가고, 타입명은 남긴다
        logger.warning("golden 튜터 LLM 호출 실패 — 대체 문장 사용: %s", type(exc).__name__)
        return TutorReply(message=_fake_message(problem), degraded=True)
    return TutorReply(message=message, degraded=False)
