"""골든 패스 튜터 되묻기(GP-4) — 오답일 때 LLM 1회 호출로 소크라테스 질문을 만든다."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, replace
from pathlib import Path

from golden.eval.leak_guard import (
    FIXED_SENTENCE,
    GUARD_VERSION,
    LeakCheck,
    check_reply,
    leak_guard_enabled,
)
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

# S32R T3R 유출 검사(GOLDEN_T3R_LEAK_GUARD=1일 때만): 학생 대기 상한(지시서 "막히면")과
# 다시 만들기에 남아 있어야 하는 최소 시간. 남은 시간이 이보다 짧으면 다시 만들지 않고 고정 문장으로
# 바꾼다.
LEAK_GUARD_WAIT_S = 30.0
LEAK_GUARD_MIN_REGEN_S = 2.0


def _now() -> float:
    """지연 상한을 재는 시계(테스트가 이 함수만 바꿔 끼운다 — 이벤트 루프의 시계는 건드리지
    않는다)."""
    return time.monotonic()


@dataclass(frozen=True)
class TutorReply:
    """튜터 되묻기 결과. degraded=True면 LLM 호출이 실패해 대체 문장을 쓴 것이다."""

    message: str
    degraded: bool
    # S32R: 유출 검사 기록(플래그가 켜졌을 때만 · api가 golden.eval_log에 남긴다). 문장은 담지
    # 않는다
    guard: dict[str, object] | None = None


def _fake_message(problem: Problem) -> str:
    """가짜 LLM 문장 = 고정 질문 + 이 문제의 hint1."""
    return FAKE_PREFIX + problem["hint1"]


def build_user_prompt(problem: Problem, history: list[TurnRow], student_text: str) -> str:
    """LLM에 보낼 사용자 프롬프트. 문제 본문·hint1·이번 문제 대화(최대 3턴)·학생 입력만 담는다.

    닉네임·세션 ID는 넣지 않는다(미성년자 데이터 규칙). 정답도 넣지 않는다 — 모델이 모르면
    누설할 수도 없다.

    S10: 몇 번째 되묻기인지도 넣는다. 3번째(마지막) 되묻기 뒤 학생의 다음 입력은 바로 채점되는데,
    튜터가 그것을 몰라 마지막에도 하위 단계를 물었다(S11 발견 ② · sim_no-setup 4·24·28행 등).
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


async def ask(problem: Problem, history: list[TurnRow], student_text: str) -> TutorReply:
    """되묻기 문장 1개를 만든다. LLM은 1회 부른다(유출 검사가 켜져 ⓐ로 걸리면 최대 2회).

    `GOLDEN_T3R_LEAK_GUARD=1`이 아니면 S32R 이전과 같다(LLM 1회 · `guard` 없음).
    """
    started = _now()
    reply = await _ask_once(problem, history, student_text, LLM_TIMEOUT_S)
    if not leak_guard_enabled():
        return reply
    return await _guard(problem, history, student_text, reply, started)


def _guard_record(
    action: str, first: LeakCheck | None, second: LeakCheck | None
) -> dict[str, object]:
    """eval_log에 합칠 유출 검사 기록 — 축·되짚기 여부·처리만 담는다(튜터·학생 문장은 담지
    않는다)."""
    record: dict[str, object] = {"t3r_guard": GUARD_VERSION, "t3r_action": action}
    if first is not None:
        record["t3r_axis"] = first.axis
        record["t3r_student_echo"] = first.student_echo
    if second is not None:
        record["t3r_second_axis"] = second.axis
    return record


async def _guard(
    problem: Problem,
    history: list[TurnRow],
    student_text: str,
    reply: TutorReply,
    started: float,
) -> TutorReply:
    """S32R T3R(다섯 걸음 ④): 튜터가 정답을 새로 말했으면(ⓐ) 같은 입력으로 한 번만 다시 만들고,
    그래도 걸리면 고정 문장으로 바꾼다. 학생 값 되짚기(ⓑ)·부호 반대 오답 되짚기(ⓒ)는 막지 않는다.

    대체 문장(degraded)은 LLM 문장이 아니라 검사하지 않는다(처리 `skipped_degraded`로 남긴다).
    """
    if reply.degraded:
        return replace(reply, guard=_guard_record("skipped_degraded", None, None))
    answer = problem["answer"]
    students = [turn.student_text for turn in history] + [student_text]
    first = check_reply(reply.message, answer, students)
    if not first.new_leak:
        return replace(reply, guard=_guard_record("pass", first, None))
    remaining = LEAK_GUARD_WAIT_S - (_now() - started)
    if remaining < LEAK_GUARD_MIN_REGEN_S:
        # 지연 상한 — 다시 만들지 않고 고정 문장으로만 바꾼다(지시서 "막히면")
        logger.info("golden T3R: 정답 유출 — 시간 부족, 고정 문장 problem=%s", problem["id"])
        return TutorReply(FIXED_SENTENCE, False, _guard_record("replaced_no_time", first, None))
    second_reply = await _ask_once(problem, history, student_text, min(LLM_TIMEOUT_S, remaining))
    if second_reply.degraded:
        logger.info("golden T3R: 정답 유출 — 다시 만들기 실패, 고정 문장 problem=%s", problem["id"])
        return TutorReply(
            FIXED_SENTENCE, False, _guard_record("replaced_regen_failed", first, None)
        )
    second = check_reply(second_reply.message, answer, students)
    if not second.new_leak:
        logger.info("golden T3R: 정답 유출 — 다시 만듦 problem=%s", problem["id"])
        return TutorReply(second_reply.message, False, _guard_record("regenerated", first, second))
    logger.info("golden T3R: 정답 유출 — 두 번째도 유출, 고정 문장 problem=%s", problem["id"])
    return TutorReply(FIXED_SENTENCE, False, _guard_record("replaced", first, second))


async def _ask_once(
    problem: Problem, history: list[TurnRow], student_text: str, timeout_s: float
) -> TutorReply:
    """LLM을 정확히 1회 부른다(S32R 이전의 `ask` 본문 그대로 · 제한 시간만 인자로 받는다).

    GOLDEN_FAKE_LLM=1이면 LLM을 부르지 않는다(테스트·CI). 환경변수는 호출 시점에 읽는다.
    호출 실패(예외·제한 시간 초과)는 삼키지 않고 예외 타입명을 로그에 남긴 뒤 대체 문장을 쓴다.
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
            provider.generate(build_user_prompt(problem, history, student_text), system, decision),
            timeout=timeout_s,
        )
        message = result.text.strip()
        if not message:
            raise ValueError("LLM 응답이 빈 문자열이다")
    except Exception as exc:  # noqa: BLE001 — 학생 화면은 대체 문장으로 이어 가고, 타입명은 남긴다
        logger.warning("golden 튜터 LLM 호출 실패 — 대체 문장 사용: %s", type(exc).__name__)
        return TutorReply(message=_fake_message(problem), degraded=True)
    return TutorReply(message=message, degraded=False)
