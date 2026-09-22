"""WH-1 튜터링 하네스 *shadow 관측* — 노출 없이 하네스 거동만 로깅 (S1-b).

`l4/misconception/shadow.py`(judge would-be shadow)의 정본 패턴을 미러한다. coach 세션
엔드포인트가 `wh1_harness_shadow_enabled`일 때, WH-1 하네스(`LLMTutorPolicy`·S1-a)를 *라이브로
돌리되* 학생 응답은 기존 결정론 경로(`_build_response_payload`) 그대로 두고(플래그 OFF와 비트동일),
하네스가 *무슨 도구를 골랐는지·verify 판정이 무엇인지*만 **서버 로그로 남긴다** — "측정 없는
도입 없음"(04a) 원칙에 따라 실 트래픽 분포에서 하네스 거동을 무노출로 수집해 verify 게이트를
primary로 승격할 근거를 모은다(후속).

비노출·비차단·무영속 불변(judge shadow 계승):
- **비노출**: 반환 `None`. 호출자(coach)가 신호를 받을 변수가 없어 student-facing 누출이 구조적으로
  차단된다. 노출 응답은 플래그 OFF와 비트동일(결정론 경로)이고, shadow 로그는 *서버 로그 sink에만*
  흐른다.
- **비차단**: coach가 `_spawn`(create_task)으로 fire-and-forget 실행하므로 응답 경로가 하네스
  한 턴(도구 루프·LLM 왕복 수 초)을 await하지 않는다(노출 무지연). 관측·직렬화·로깅을 한 `try`로
  감싸 *어떤 예외도* 본류(학생 응답)를 안 깬다(우선순위: 학생 경험 > 진단 관측·CLAUDE.md #1≫#6).
- **무영속**: DB 영속 없이 *순수 한 턴* `run_tutoring_turn`(작업 메모리 in-memory)만 돌린다 —
  shadow는 관측만이고 상태를 영속하지 않는다(`run_persisted_turn` 아님·커밋 좌석 미접근).
- **프라이버시(미성년 PII)**: 학생 풀이 원문·풀이 단계·발화 원문·정답을 레코드에 *담지 않는다*
  (`shadow.py`:14 규약 계승). 담는 건 추상화된 status·end action_type·verify verdict·전이별
  verify 판정 카운트(정수 3개·S3-07)·도구 호출 수·활성 가설 수·(있으면) 문항/세션 식별자 id뿐
  (비식별). 학생 원문·단계는 `LLMTutorPolicy`의 *사적 필드*로만 주입돼(S1-a 계약) LLM 프롬프트에도
  레코드에도 실리지 않는다.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from whymath_backend.harness.wh1_llm_policy import LLMTutorPolicy
from whymath_backend.harness.wh1_loop import ToolResult, TurnOutcome, run_tutoring_turn
from whymath_backend.harness.wh1_probe_supply import assemble_probe_candidate_pool
from whymath_backend.l3.interfaces import LLMProvider
from whymath_backend.l4.misconception.hypothesis import MisconceptionHypothesis
from whymath_backend.l4.session_recall import SessionRecall

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["Wh1HarnessShadowObservation", "emit_wh1_observation", "observe_wh1_harness_shadow"]

logger = logging.getLogger("whymath.harness.wh1_shadow")  # judge shadow 네이밍 동형
# 구조화 레코드 JSON 한 줄(harvest 입력) — 평문 로그와 분리된 자식 로거(shadow.record 미러).
record_logger = logging.getLogger("whymath.harness.wh1_shadow.record")

# verify 판정 3-state를 트레이스 detail(`검증 correct(내부).`)에서 추출 — `run_tutoring_turn`은
# `last_verdict`를 `TurnOutcome`에 노출하지 않으므로(하네스 무변경 원칙) 트레이스로 관측한다.
# 'incorrect'가 'correct'를 부분 포함하므로 정규식으로 토큰 경계를 정확히 잡는다.
_VERIFY_VERDICT_RE = re.compile(r"검증 (correct|incorrect|unverifiable)")


class Wh1HarnessShadowObservation(BaseModel):
    """WH-1 하네스 shadow 관측 1건의 *구조화 레코드* — record_logger JSON emit (harvest).

    하네스 한 턴 결과에서 *비식별 요약*만 담는다: 종료 status·end action_type·verify 판정·총 도구
    호출 수·턴 종료 시 활성 가설 수·(있으면) 문항/세션 식별자 id. **학생 풀이 원문·풀이 단계·발화
    원문·정답은 담지 않는다**(`shadow.py` 규약 계승·미성년 PII) — `extra="forbid"`로 그런 필드를
    *주입조차* 못 하게 구조적으로 차단한다(비노출·로그 sink 한정 불변).
    """

    model_config = ConfigDict(extra="forbid")

    status: str
    """하네스 턴 종료 status — `ended`(발화·종료)·`budget_exhausted`(예산 소진·안전 종료)."""

    action_type: str | None
    """end_turn 행위 유형(질문|힌트|출제|격려·`ended`일 때)·비발화 요약(원문 아님·범주 라벨)."""

    verify_verdict: str | None
    """이 턴 verify_step 3-state 판정(correct|incorrect|unverifiable). verify 미호출이면 None."""

    n_correct: int | None = None
    """이 턴 verify_step *전이별* correct 판정 수(S3-07·비식별 정수). **None=구판 레코드**(카운트
    미기록)로 "전이 0회"(=0)와 구분한다 — 신판 emit은 항상 기록(verify 미호출 턴도 0). 마지막
    판정(verify_verdict)이 가리던 앞 전이의 correct를 분포에 보이게 하는 축(2026-07-19 실측:
    이차방정식 자연 풀이의 마지막 단계=근 나열이 미결정이라 턴 전체가 unverifiable로 왜곡)."""

    n_incorrect: int | None = None
    """이 턴 verify_step 전이별 incorrect 판정 수(S3-07). None=구판 레코드(카운트 미기록)."""

    n_unverifiable: int | None = None
    """이 턴 verify_step 전이별 unverifiable 판정 수(S3-07). None=구판 레코드(카운트 미기록)."""

    n_equation_transitions: int | None = None
    """이 턴에서 **해집합 보존 경로**(등호 방정식 변형·S3-02)로 판정된 전이 수(S3-51).

    **None=구판 레코드**(형태 축 이전 emit)로 "등호 전이 0회"(=0)와 구분한다 — 신판 emit은
    항상 기록한다(verify 미호출 턴도 0). 자유사용 대표측정(S3-02 트리거 ③)의 사전등록 유효성
    전제 V3(등호 방정식 변형 턴 >=5건)이 읽는 축이며, S3-02 알고리즘이 실사용에서 *실제로
    작동한 횟수*이기도 하다(CLAUDE.md '작동한 비율' 원칙). 정수 개수만 — 식·원문은 없다."""

    n_mixed_form_transitions: int | None = None
    """이 턴에서 **혼합 형태**(한쪽만 등식)라 비교 전제 불성립으로 회피한 전이 수(S3-51).

    None=구판. V3 미달·unverifiable 잔여의 원인이 백엔드 판정이 아니라 *입력 형태*(단계가
    등식으로 정렬되지 않음)임을 구분하는 진단 축 — 2026-07-19 실측에서 잔여 원인이 입력 UX로
    이동했다는 결론(S3-05)의 후속 관측이다."""

    tool_calls: int
    """총 도구 호출 횟수(하네스 트레이스 길이·거동 프로파일)."""

    hypothesis_count: int
    """턴 종료 시점 활성 오개념 가설 수(id 아님·수만·비식별)."""

    dialogue_id: str | None = None
    """세션 식별자(있으면 id만·문자열화). 학생 원문과 무관한 조인 키(비식별)."""

    turn_index: int = 1
    """세션 내 학생 턴 번호(1-기준) — 턴별 verify verdict 분포·추이 관측 키(S1-11·정수·비식별)."""

    problem_id: str | None = None
    """문항 식별자(있으면 id만·문자열화). 문항 본문 아님(코드/UUID·비식별)."""

    primary: bool = False
    """이 관측이 primary(flip·S1-11) 경로에서 나왔는지 — shadow(False·비노출)와 회계 분리.

    구판·shadow 레코드는 False(기본). True면 이 턴의 하네스 발화가 실제 학생에게 노출된 턴이다
    (`harness/wh1_primary.py` emit). 발화 원문은 여전히 레코드에 없다(비식별 불변) — 신/구·
    shadow/primary 혼합 분포를 분리 집계할 수 있게 하는 회계 축(S3-07 신/구판 분리 선례)."""

    tone_rewritten: bool = False
    """primary 발화가 L4 톤필터(`filter_tone`)로 재작성됐는지 — KPI3(정서 안전) 측정 좌석.

    shadow 관측(비노출)은 톤필터를 안 거치므로 항상 False. True면 LLM 발화에서 금지 패턴이
    검출·치환된 뒤 노출됐다는 뜻(위반 사실의 관측 가능 기록·발화 원문 미저장)."""

    tone_violations: int = 0
    """톤필터가 검출한 금지 패턴 수(중복 포함·비식별 정수). 패턴 원문·발화 원문은 미저장."""

    prose_rephrased: bool = False
    """primary 파생 템플릿 발화가 프로즈 계층(S4-04)에서 LLM 문맥 프로즈로 승격됐는지.

    shadow·구판 레코드는 False(기본값 — 하위호환·구판 파싱 무영향). True면 정답-안전 게이트
    (등호·숫자·GT 유입 전면 차단)를 통과한 프로즈가 노출됐다는 뜻. 발화 원문은 불저장 불변."""

    prose_reason_code: str | None = None
    """프로즈 계층 판정 코드(taxonomy 라벨·비식별) — rephrase 미승격/게이트 거부 사유.

    None=프로즈 계층 미경유(플래그 OFF·shadow) 또는 승격 성공. 문자열이면 wh1_prose의
    REASON_* 코드(NOT_REPHRASABLE·PROSE_EQUATION 등 — 코드만·발화 원문 미포함)."""

    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def _extract_verify_verdict(trace: Sequence[ToolResult]) -> str | None:
    """트레이스에서 *마지막* verify_step 판정(3-state)을 추출 — 없으면 None(verify 미호출).

    `run_tutoring_turn`이 `last_verdict`를 outcome으로 노출하지 않으므로(하네스 무변경) 트레이스
    detail(`검증 {verdict}(내부).`)에서 정규식으로 읽는다. 판정 자체는 correct/incorrect/
    unverifiable 3값뿐이라 학생 원문·정답을 담지 않는다(비식별 라벨).
    """
    for result in reversed(trace):
        if result.kind == "verify_step" and result.ok:
            match = _VERIFY_VERDICT_RE.search(result.detail)
            if match is not None:
                return match.group(1)
    return None


def _count_verify_verdicts(trace: Sequence[ToolResult]) -> tuple[int, int, int]:
    """트레이스의 **모든** verify_step 판정을 집계 — (n_correct, n_incorrect, n_unverifiable).

    `_extract_verify_verdict`(마지막 판정=턴 라벨)의 자매 함수다(S3-07). 마지막 판정만 보면
    이차방정식 자연 풀이처럼 마지막 전이(근 나열·S3-06 전엔 미결정)가 unverifiable일 때 앞
    전이의 correct가 턴 라벨에서 전부 가려진다(2026-07-19 실측 왜곡·S1-11 flip 분포 충실도).
    전이별 카운트를 병기해 그 왜곡이 분포에서 *보이게* 한다. `ok=True` verify_step만 센다
    (거부·게이트 위반은 판정이 아님 — 턴 라벨 규칙과 동형). 산출은 비식별 정수 3개뿐 —
    학생 원문·단계 원문·정답을 담지 않는다(프라이버시 계약 유지).
    """
    counts = {"correct": 0, "incorrect": 0, "unverifiable": 0}
    for result in trace:
        if result.kind == "verify_step" and result.ok:
            match = _VERIFY_VERDICT_RE.search(result.detail)
            if match is not None:
                counts[match.group(1)] += 1
    return counts["correct"], counts["incorrect"], counts["unverifiable"]


def _count_verify_forms(trace: Sequence[ToolResult]) -> tuple[int, int]:
    """트레이스의 verify_step 전이 *형태* 집계 — (등호 방정식 전이 수, 혼합 형태 전이 수).

    `_count_verify_verdicts`(판정 축)의 자매 함수다(S3-51). 하네스가 이미 계산해 트레이스에
    실어 둔 `verify_form_counts`를 **합산만** 한다 — 형태 판정을 재구현하지 않는다(단일 진실
    원천은 `l3/verify_step.py`의 분기). 구판 ToolResult(필드 없음·None)는 0으로 합산되는데,
    그건 *같은 프로세스 안* 이야기라 발생하지 않는다(레코드 축의 신/구판 구분은 관측 필드의
    None이 담당한다).

    산출은 비식별 정수 2개뿐 — 학생 원문·단계·정답을 담지 않는다(프라이버시 계약 유지).
    """
    equation = 0
    mixed = 0
    for result in trace:
        if result.kind != "verify_step" or not result.ok:
            continue
        counts = result.verify_form_counts
        if counts is None:
            continue
        equation += counts.get("equation", 0)
        mixed += counts.get("mixed", 0)
    return equation, mixed


def emit_wh1_observation(
    outcome: TurnOutcome,
    *,
    dialogue_id: str | None = None,
    turn_index: int = 1,
    problem_id: str | None = None,
    primary: bool = False,
    tone_rewritten: bool = False,
    tone_violations: int = 0,
    prose_rephrased: bool = False,
    prose_reason_code: str | None = None,
) -> None:
    """하네스 한 턴 결과를 관측 레코드로 emit — shadow·primary *공통* 단일 좌석(S1-11).

    직전까지 이 로직은 `observe_wh1_harness_shadow` 내부에만 있었다. primary flip에서도
    verdict 관측(원장 축적)이 끊기면 안 되므로(사인오프 방침 ⑤ — 측정 인프라 연속성) emit을
    이 함수로 추출해 primary 경로(`harness/wh1_primary.py`)가 동일 레코드 계약·동일
    record 로거로 재사용한다(재구현 0·수확기 `wh1_shadow_harvest` 하위호환). 프라이버시
    계약은 모델(`extra="forbid"`)이 그대로 강제한다 — 학생 원문·발화 원문·정답은 여기로
    *들어올 수조차* 없다(비식별 status·카운트·bool·id만).
    """
    verify_verdict = _extract_verify_verdict(outcome.trace)
    # 전이별 카운트(S3-07) — 마지막 판정(턴 라벨)이 가리는 앞 전이 correct를 분포에 노출.
    n_correct, n_incorrect, n_unverifiable = _count_verify_verdicts(outcome.trace)
    # 전이 *형태* 집계(S3-51) — S3-02 해집합 경로가 이 턴에 몇 번 작동했는지(V3 축).
    n_equation, n_mixed = _count_verify_forms(outcome.trace)
    logger.info(
        "WH-1 하네스 %s — status=%s action_type=%s verify=%s "
        "transitions(c/i/u)=%d/%d/%d (tool_calls=%d hypotheses=%d tone_rewritten=%s)",
        "primary" if primary else "shadow(비노출)",
        outcome.status,
        outcome.action_type,
        verify_verdict,
        n_correct,
        n_incorrect,
        n_unverifiable,
        outcome.tool_calls,
        len(outcome.hypotheses),
        tone_rewritten,
    )
    record_logger.info(
        Wh1HarnessShadowObservation(
            status=outcome.status,
            action_type=outcome.action_type,
            verify_verdict=verify_verdict,
            n_correct=n_correct,
            n_incorrect=n_incorrect,
            n_unverifiable=n_unverifiable,
            n_equation_transitions=n_equation,
            n_mixed_form_transitions=n_mixed,
            tool_calls=outcome.tool_calls,
            hypothesis_count=len(outcome.hypotheses),
            dialogue_id=dialogue_id,
            turn_index=turn_index,
            problem_id=problem_id,
            primary=primary,
            tone_rewritten=tone_rewritten,
            tone_violations=tone_violations,
            prose_rephrased=prose_rephrased,
            prose_reason_code=prose_reason_code,
        ).model_dump_json()
    )


async def observe_wh1_harness_shadow(
    *,
    student_solution: str,
    solution_steps: Sequence[str],
    active_hypotheses: Sequence[MisconceptionHypothesis],
    provider: LLMProvider | None = None,
    turn_index: int = 1,
    max_tool_calls: int = 16,
    dialogue_id: str | None = None,
    problem_id: str | None = None,
    warmstart_outside_mids: Sequence[str] = (),
    session_recall: SessionRecall | None = None,
    session: AsyncSession | None = None,
    theta: float | None = None,
    user_id: uuid.UUID | None = None,
) -> None:
    """WH-1 하네스를 한 턴 돌려 *거동 요약만* 로그로 관측(shadow·비노출·무영속). 반환 `None`.

    `LLMTutorPolicy`를 구성하되 학생 원문(`student_solution`)·풀이 단계(`solution_steps`)를 정책의
    *사적 필드*로 주입한다(S1-a 계약 — LLM 프롬프트엔 요약만 나가고 원문은 match/verify 인자로만
    사적 사용). `run_tutoring_turn`(순수 한 턴·DB 무접근)으로 도구 루프를 완주시킨 뒤 결과에서
    status·end action_type·verify verdict(트레이스에서 추출)·전이별 verify 판정 카운트(S3-07·
    정수 3개)·총 도구 호출 수·활성 가설 수만 뽑아 레코드로 emit한다. **학생 원문·풀이 단계·발화
    원문·정답은 절대 레코드에 안 담는다**(미성년 PII).

    `has_solution_steps`는 `solution_steps` 유무로 정한다 — 풀이 단계가 있으면 verify 의무(§3.1)가
    걸려 하네스가 verify_step을 강제하므로, 실 트래픽에서 verify 판정 분포를 관측할 수 있다.

    **웜스타트 probe 힌트(S1-c·감사 Q5)**: `warmstart_outside_mids`(진단 시작 시 조립된 외부 오개념
    후보·`l4.misconception.warmstart`)를 `LLMTutorPolicy`의 *사적 probe 컨텍스트*(outside_mids)로만
    주입한다 — 정책이 select_probe를 고르면 `SelectProbeAction.outside_mids`에 실려 하네스의
    `plan_probe`(진단 문항 *선별*)로 흐른다. **이 힌트는 진단 probe 타깃팅 전용이다**: 코칭 context·
    개입 발화에 오개념을 preload하지 않는다(reactive retrieval 유지·CLAUDE.md). student_text·
    solution_steps와 같은 사적 주입 계약이라 LLM 프롬프트에도, shadow 레코드에도 실리지 않는다.

    **select_probe 후보 공급(REC-02 ②)**: `session`이 주어지면 `assemble_probe_candidate_pool`
    (L1 조회 → L4 `ProbeCandidate` 조립)로 활성 가설 mids + `warmstart_outside_mids` 후보 풀을
    조립해 `probe_candidates`를 채운다 — 이전엔 이 인자가 항상 빈 리스트라 `select_probe`가
    라이브에서 구조적으로 항상 실패했다(감사 §3 D2). `session=None`(기존 호출자·단위테스트)이면
    조회를 skip한다(회귀 0). `theta`는 IRT 정보량 계산용 능력 추정값(None→0.0).

    **never-break**(비차단 방어선·judge shadow의 async 미러): 정책 구성·하네스 실행·직렬화·로깅을
    한 `try`로 감싸 *어떤 예외도* 본류(fire-and-forget task)를 깨지 않는다. 정책(`LLMTutorPolicy`)은
    provider 장애를 안전 강등으로 흡수하지만(never-break), 그 위 직렬화·로깅 실패까지 방어한다
    (우선순위: 학생 경험 > 진단 관측).
    """
    try:
        # select_probe 후보 공급(REC-02 ②) — session=None(기존 호출자·단위테스트)이면 조회
        # skip해 빈 리스트(회귀 0). 사적 probe 컨텍스트로만 흐른다(모듈 docstring 참조).
        probe_candidates = await assemble_probe_candidate_pool(
            session,
            active_hypotheses=active_hypotheses,
            outside_mids=warmstart_outside_mids,
            user_id=user_id,
            seat="wh1_shadow",
        )
        policy = LLMTutorPolicy(
            provider,
            # 학생 원문·풀이 단계는 프롬프트가 아니라 정책 보유값으로만 사적 사용(S1-a·요구사항 ⑥).
            student_text=student_solution,
            solution_steps=list(solution_steps),
            probe_candidates=probe_candidates,
            theta=theta if theta is not None else 0.0,
            # 웜스타트 outside_mids도 사적 probe 컨텍스트로만 주입 — select_probe→plan_probe 전용
            # (진단 타깃팅). 코칭 context·프롬프트·레코드에 오개념 preload 0(감사 Q5·CLAUDE.md).
            outside_mids=list(warmstart_outside_mids),
            # PED-04 D1 reader ②: 직전 세션의 교수 이력(메타 한정·원문 0·복호 0). 정책이
            # 예산 가드 안에서 요약에 실어 "이미 시도한 결"을 알게 한다.
            session_recall=session_recall,
        )
        outcome: TurnOutcome = await run_tutoring_turn(
            policy=policy,
            turn_index=turn_index,
            has_solution_steps=bool(solution_steps),
            initial_hypotheses=list(active_hypotheses),
            max_tool_calls=max_tool_calls,
        )
        # emit은 shadow·primary 공통 좌석(`emit_wh1_observation`)으로 — 레코드 계약 단일 진실원천.
        emit_wh1_observation(
            outcome,
            dialogue_id=dialogue_id,
            turn_index=turn_index,
            problem_id=problem_id,
        )
    except Exception:  # noqa: BLE001 — 관측은 본류를 안 깬다(비차단 방어선·shadow.py:244 미러)
        return
