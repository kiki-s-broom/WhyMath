"""골든 패스 튜터 되묻기(GP-4) — 오답일 때 LLM 1회 호출로 소크라테스 질문을 만든다."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from golden.llm.factory import build_cloud_provider
from golden.llm.gate import guard_cloud_jurisdiction
from golden.problems import Problem
from golden.store import TurnRow

# 옛 코드에서 가져온 것: 라우터 결정(HARVEST.md).
# 프로바이더 팩토리는 골든 복사본(golden.llm — S20A 2일째)
from whymath_backend.l3.models import RoutingRequest
from whymath_backend.l3.router import Router
from whymath_backend.schema.enums import LicenseType

logger = logging.getLogger(__name__)

# 시스템 프롬프트 파일 — 저장소 루트의 golden/tutor_prompt.md
TUTOR_PROMPT_PATH = Path(__file__).resolve().parents[3] / "golden" / "tutor_prompt.md"

# 가짜 LLM·장애 대체 문장의 앞부분(공유 계약 — 뒤에 hint1을 붙인다)
FAKE_PREFIX = "어느 부분이 막히는지 한 가지만 말해 줄래? "

# LLM 호출 제한 시간(초). S8 본인 테스트(2026-11-09 · Kiki 머신 · OpenRouter)에서
# 10초 초과가 2회 나 대체 문장으로 떨어졌다(클라우드 실측은 3.6~4.5초).
# Kiki 지시로 20초로 올린다. 넘기면 여전히 대체 문장(degraded)이다.
LLM_TIMEOUT_S = 20.0

# 한 문제에서 쓸 수 있는 튜터 되묻기 최대 횟수(공유 계약 — api.MAX_TUTOR_TURNS가 이 값을 쓴다)
MAX_TUTOR_TURNS = 3

# S28 T2 적용(GOLDEN_T2_MISCONCEPTION=1 · 매칭이 있을 때만): 사용자 프롬프트에 넣는 한 줄.
# 문장은 지시서 S28 할 일 1 그대로다. 시스템 프롬프트(tutor_prompt.md)는 건드리지 않는다.
T2_HINT_TEMPLATE = (
    "학생의 답은 '{description}' 유형의 실수일 수 있다. 정답은 말하지 말고 그 지점을 짚어 묻는다."
)


@dataclass(frozen=True)
class TutorReply:
    """튜터 되묻기 결과. degraded=True면 LLM 호출이 실패해 대체 문장을 쓴 것이다."""

    message: str
    degraded: bool


def _fake_message(problem: Problem) -> str:
    """가짜 LLM 문장 = 고정 질문 + 이 문제의 hint1."""
    return FAKE_PREFIX + problem["hint1"]


def build_user_prompt(
    problem: Problem,
    history: list[TurnRow],
    student_text: str,
    misconception: str | None = None,
) -> str:
    """LLM에 보낼 사용자 프롬프트. 문제 본문·hint1·이번 문제 대화(최대 3턴)·학생 입력만 담는다.

    닉네임·세션 ID는 넣지 않는다(미성년자 데이터 규칙). 정답도 넣지 않는다 — 모델이 모르면
    누설할 수도 없다.

    S10: 몇 번째 되묻기인지도 넣는다. 3번째(마지막) 되묻기 뒤 학생의 다음 입력은 바로 채점되는데,
    튜터가 그것을 몰라 마지막에도 하위 단계를 물었다(S11 발견 ② · sim_no-setup 4·24·28행 등).

    S28: `misconception`(오개념 한 줄 설명)이 있으면 학생 입력 바로 뒤에 T2 한 줄을 넣는다.
    None이면(플래그 꺼짐·매칭 없음) 프롬프트는 S28 이전과 한 글자도 같다.
    """
    turn_no = len(history) + 1
    lines = [
        f"문제: {problem['stem']}",
        f"참고 힌트(정답 아님, 그대로 읽지 말 것): {problem['hint1']}",
    ]
    for turn in history[-3:]:
        lines.append(f"학생: {turn.student_text}")
        lines.append(f"튜터: {turn.tutor_text}")
    lines.append(f"학생: {student_text}")
    if misconception is not None:
        lines.append(T2_HINT_TEMPLATE.format(description=misconception))
    turn_line = f"되묻기 차례: {MAX_TUTOR_TURNS}번 중 {turn_no}번째"
    if turn_no >= MAX_TUTOR_TURNS:
        turn_line += " — 마지막 되묻기다. 학생의 다음 입력이 바로 채점된다."
    lines.append(turn_line)
    lines.append("위 학생 말에 대한 튜터의 다음 한 마디를 써라.")
    return "\n".join(lines)


def _routing_request() -> RoutingRequest:
    """튜터 되묻기 1회의 라우팅 요청 — 라우터가 CLOUD_MID 결정을 내도록 신호를 채운다.

    문항은 자체 생성(WHYMATH_GENERATED)이라 반출 가능 등급으로 선언한다. 등급 게이트가
    막으면 결정이 LOCAL이 되고, 클라우드 좌석 호출이 실패해 대체 문장(degraded)으로 간다.

    학생 답 송신(Kiki 결정 2026-11-17 · GOLD-22): 프롬프트에는 학생이 쓴 답이 들어간다.
    그 글은 성격상 학생 저작(USER_GENERATED · 반출 금지 등급)이지만, 골든 튜터는 그것을
    클라우드로 보내는 것을 Kiki가 **명시 허용**했다 — 그래서 등급은 문항 기준
    (WHYMATH_GENERATED) 하나만 선언한다. USER_GENERATED를 더하면 라우터가 결정을
    LOCAL로 바꿔(실측 data_export_blocked=True) 튜터가 늘 대체 문장으로 간다.
    허용의 전제(바뀌면 이 결정을 다시 묻는다): ①닉네임·세션 ID·정답은 프롬프트에 넣지
    않는다(build_user_prompt) ②좌석은 OpenRouter, 허용 공급사 기본값은 deepinfra 하나
    (미국 법인 · 데이터 수집 거부 · 보존 0 — config·golden/llm/openrouter.py 표) ③보내기
    직전 관할 게이트(golden/llm/gate.py) ④실학생 세션 전 보호자 동의서에 이 송신을 적는다
    (Kiki 담당).
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


async def ask(
    problem: Problem,
    history: list[TurnRow],
    student_text: str,
    misconception: str | None = None,
) -> TutorReply:
    """되묻기 문장 1개를 만든다. LLM은 정확히 1회 부른다.

    `misconception`은 S28 T2 한 줄 설명이다(없으면 None) — 사용자 프롬프트에만 들어간다.

    GOLDEN_FAKE_LLM=1이면 LLM을 부르지 않는다(테스트·CI). 환경변수는 호출 시점에 읽는다.
    호출 실패(예외·10초 초과)는 삼키지 않고 예외 타입명을 로그에 남긴 뒤 대체 문장을 쓴다.
    """
    if os.environ.get("GOLDEN_FAKE_LLM") == "1":
        return TutorReply(message=_fake_message(problem), degraded=False)

    try:
        system = TUTOR_PROMPT_PATH.read_text(encoding="utf-8")
        decision = Router().route(_routing_request())
        provider = build_cloud_provider()
        # 보내기 직전 관할 판정(옛 CompositeProvider와 같은 판정 · GOLD-20) — 막히면 호출 0회
        guard_cloud_jurisdiction(provider, decision)
        result = await asyncio.wait_for(
            provider.generate(
                build_user_prompt(problem, history, student_text, misconception), system, decision
            ),
            timeout=LLM_TIMEOUT_S,
        )
        message = result.text.strip()
        if not message:
            raise ValueError("LLM 응답이 빈 문자열이다")
    except Exception as exc:  # noqa: BLE001 — 학생 화면은 대체 문장으로 이어 가고, 타입명은 남긴다
        logger.warning("golden 튜터 LLM 호출 실패 — 대체 문장 사용: %s", type(exc).__name__)
        return TutorReply(message=_fake_message(problem), degraded=True)
    return TutorReply(message=message, degraded=False)
