"""WH-1 튜터링 하네스 *primary(flip) 실행* — 학생-대면 발화를 하네스 경유로 산출 (S1-11).

설계 정본: `docs/architecture/04a_wh1_tutoring_harness.md` §8.4 3단계(전체 도구 루프 + 웜 스타트)·
MEMORY 2026-07-20 flip 사인오프(ⓑ 재판정 통과·ⓒ Kiki 사인오프). `wh1_shadow.py`(비노출 관측)의
자매 모듈이다 — 같은 정책 구성(사적 주입 계약 S1-a)·같은 순수 턴 루프(`run_tutoring_turn`)를 돌되,
shadow와 달리 **발화(`outcome.utterance`)를 호출자(coach)에게 돌려줘 학생에게 노출**시킨다.

노출 전 3중 게이트(사인오프 방침 ②·③):
  1. **하네스 verify 의무·정답 억제** — 발화는 `run_tutoring_turn`의 §3.1(풀이 제출 턴 verify
     의무)·§3.4(정답 억제 백스톱·end_turn만 발화) 불변식을 통과한 것만 나온다(하네스가 강제·
     정책 선의 비의존). LLM provider 장애는 정책(`LLMTutorPolicy`)이 안전 강등으로 흡수해
     결정론 파생 발화(격려·소크라테스 개입)로 귀결된다 — 이 역시 하네스 게이트 통과분이다.
  2. **L4 톤필터 라이브 배선** — 노출 직전 `filter_tone`으로 금지 6패턴을 치환한다. 위반 시
     rewritten 텍스트만 노출하고 위반 *사실*을 관측 가능하게 기록한다(구조화 WARNING 로그 —
     패턴 라벨·건수만, 발화 원문 미포함 — + 관측 레코드 `tone_rewritten`/`tone_violations` —
     KPI3 정서 안전 측정 좌석의 첫 배선). 톤위반 전용 `attempt_event` 적재는 하지 않는다 —
     `EventType`이 네이티브 PG enum(`event_type_enum`)이라 값 추가 = DB 마이그레이션이며,
     사인오프 방침이 '마이그레이션 없는 경로 우선'을 명시(구조화 로그+레코드까지·event 적재는
     후속 명시).
  3. **폴백 신호** — 타임아웃(`asyncio.wait_for`)·예산 소진(`budget_exhausted`)·예기치 못한
     예외면 `None`을 반환해 호출자가 결정론 Polya 템플릿으로 안전 폴백하게 한다(가용성 — 앱은
     죽지 않는다). 모든 실패는 예외 *타입명* 포함 WARNING 로그(침묵 실패 금지·CLAUDE.md).

옵트인 추가 계층(PED-23 회수·기본 OFF — 정본 `docs/architecture/04e_pedagogy_strategy_catalog.md`
§9): `mode_guard_runtime_enabled` ∧ 팩 주입 시, 발화 확정 후·톤필터 직전에 교수법 팩 금지모드 가드
(`l4/pedagogy/mode_guard.py`)를 태운다 — 위반 발화는 서빙하지 않고 소크라테스 재질문(결정론
템플릿)으로 대체 + reason_code 구조화 로그(fail-closed). OFF/무팩이면 기존 경로와 비트동일.

관측 연속성(사인오프 방침 ⑤): primary 경로에서도 shadow와 *동일 레코드 계약*으로
`emit_wh1_observation`을 호출해 verdict 원장 축적이 끊기지 않는다(`primary=True` 표식으로 회계
분리·S3-07 신/구판 분리 선례). coach는 primary on이면 별도 shadow spawn을 하지 않는다(같은 턴
이중 LLM 호출·중복 레코드 회피).

프라이버시(불변): 학생 원문·풀이 단계는 정책 *사적 필드*로만 주입되고(LLM 프롬프트·레코드
미노출·S1-a), 발화 원문은 서버 로그에 싣지 않는다(학생 응답·DB dialogue_turn에만 — 저장 계층
암호화 방침 동일 적용). 관측 레코드는 비식별 필드뿐이다(`Wh1HarnessShadowObservation`
`extra="forbid"`).

범위 밖(후속): fast path(§5.3·비풀이 턴 경량 즉답 — 레이턴시 최적화)·실 LLM 프롬프트 품질
튜닝·상태 오케스트레이션 수렴(`run_persisted_turn` HTTP 배선 — 라이브 coach가 이미 턴당
가설 큐레이션·증거 생산을 영속하므로 이중 영속 회피를 위해 발화 승격과 분리·해당 모듈 docstring
참조).

Langfuse trace·캐시는 **결선 완료**(OPS-36) — 정책·프로즈 모두 `Wh1LlmSeam`을 거쳐
`l3.pipeline`으로 간다(라우터 경유·캐시·`l3_routing` 기록). 호출자(coach)가 `cache`·`trace`에
앱 공유 인스턴스를 넘기면 학생 대면 트래픽이 비용 게이트② 표본에 계상된다. 미주입이면 좌석이
인메모리 기본값으로 폴백한다 — 그때는 기록이 앱 밖으로 나가지 않을 뿐 경유 자체는 유지된다.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Sequence
from typing import TYPE_CHECKING

from whymath_backend.config import get_settings
from whymath_backend.harness.wh1_llm_policy import LLMTutorPolicy
from whymath_backend.harness.wh1_loop import TurnOutcome, run_tutoring_turn
from whymath_backend.harness.wh1_probe_supply import assemble_probe_candidate_pool
from whymath_backend.harness.wh1_prose import gate_policy_prose, rephrase_coach_utterance
from whymath_backend.harness.wh1_shadow import _extract_verify_verdict, emit_wh1_observation
from whymath_backend.l3.interfaces import CacheBackend, LLMProvider, TraceSink
from whymath_backend.l4.misconception.hypothesis import MisconceptionHypothesis
from whymath_backend.l4.pedagogy.mode_guard import check_forbidden_modes, fallback_reply_for
from whymath_backend.l4.session_recall import SessionRecall
from whymath_backend.l4.tone_filter import filter_tone
from whymath_backend.schema.pedagogy_pack import PedagogyPack

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["run_wh1_primary_turn"]

logger = logging.getLogger("whymath.harness.wh1_primary")


def _safe_emit(
    outcome: TurnOutcome,
    *,
    dialogue_id: str | None,
    turn_index: int,
    problem_id: str | None,
    tone_rewritten: bool = False,
    tone_violations: int = 0,
    prose_rephrased: bool = False,
    prose_reason_code: str | None = None,
) -> None:
    """관측 emit — 실패해도 발화 서빙(본류)을 깨지 않는다(예외 타입명 로그·침묵 실패 금지)."""
    try:
        emit_wh1_observation(
            outcome,
            dialogue_id=dialogue_id,
            turn_index=turn_index,
            problem_id=problem_id,
            primary=True,
            tone_rewritten=tone_rewritten,
            tone_violations=tone_violations,
            prose_rephrased=prose_rephrased,
            prose_reason_code=prose_reason_code,
        )
    except Exception as exc:  # noqa: BLE001 — 관측 실패는 서빙을 안 깬다(우선순위 #1≫#6).
        logger.warning(
            "WH-1 primary 관측 emit 실패(%s) — 발화 서빙은 계속", type(exc).__name__, exc_info=True
        )


async def run_wh1_primary_turn(
    *,
    student_solution: str,
    solution_steps: Sequence[str],
    active_hypotheses: Sequence[MisconceptionHypothesis],
    provider: LLMProvider | None = None,
    cache: CacheBackend | None = None,
    trace: TraceSink | None = None,
    turn_index: int = 1,
    max_tool_calls: int = 16,
    timeout_seconds: float | None = None,
    dialogue_id: str | None = None,
    problem_id: str | None = None,
    warmstart_outside_mids: Sequence[str] = (),
    session_recall: SessionRecall | None = None,
    session: AsyncSession | None = None,
    theta: float | None = None,
    user_id: uuid.UUID | None = None,
    pack: PedagogyPack | None = None,
) -> str | None:
    """WH-1 하네스를 한 턴 돌려 *학생-대면 발화*를 산출한다 — flip primary 경로(S1-11).

    반환: 톤필터를 통과한 발화 문자열, 또는 `None`(=호출자는 결정론 템플릿 폴백).
    `None` 사유: ① 타임아웃/예외(WARNING·타입명 로그) ② `budget_exhausted`(발화 없음·안전
    종료) ③ ended인데 발화 빈 값(이론적 경계·방어). ②③은 관측 레코드는 emit하고 폴백한다
    (실패도 원장에 보이게 — 관측 연속).

    `active_hypotheses`(post-apply 누적 가설 세트)가 §2.2 웜 스타트다 — 호출자(coach)가
    `_apply_hypotheses`로 영속·큐레이션한 세트를 그대로 실어 shadow와 동일 계약을 유지한다.
    `timeout_seconds` 미지정 시 설정(config)의 primary 타임아웃을 쓴다.

    **도구6 select_probe 후보 공급(REC-02 ②)**: `session`이 주어지면 *활성 가설이 선 뒤*
    (`active_hypotheses`)·`warmstart_outside_mids`로 `assemble_probe_candidate_pool`(L1 조회
    → L4 `ProbeCandidate` 조립)을 호출해 `LLMTutorPolicy(probe_candidates=...)`에 실제 후보를
    채운다 — 이전엔 이 인자가 항상 `()`라 `select_probe`가 라이브에서 구조적으로 항상 실패했다
    (감사 §3 D2). `session=None`(기존 호출자·단위테스트)이면 조회를 skip해 후보가 빈 리스트로
    남는다(기존 동작 완전 보존·회귀 0). `theta`는 IRT 정보량 계산에 쓰이는 학생 능력 추정값
    (None이면 0.0 — 콜드스타트 폴백)이며, 후보 조립 자체는 **사적 probe 컨텍스트**로만 흐른다
    (오개념 preload 0 불변 — 모듈 docstring·`wh1_probe_supply.py` docstring 참조).

    `pack`(PED-23 회수 — 정본 `docs/architecture/04e_pedagogy_strategy_catalog.md` §9): 호출자
    (coach)가 문항 PRIMARY 개념으로 해석해 `decide(pack=)`에 이미 주입한 *같은* 교수법 팩 객체.
    `mode_guard_runtime_enabled`(기본 False·옵트인) ∧ pack 주입 시에만, 발화 확정 후·톤필터
    직전에 팩 금지 모드 가드를 태운다 — 위반이면 그 발화를 서빙하지 않고(fail-closed) 안전한
    소크라테스 재질문(결정론 템플릿)으로 대체 + reason_code(위반 모드 토큰) 구조화 로그. 팩
    None(기본·미주입)이거나 플래그 OFF면 가드 블록 전체 미실행 — 기존 경로와 비트동일(회귀 0).
    """
    try:
        probe_candidates = await assemble_probe_candidate_pool(
            session,
            active_hypotheses=active_hypotheses,
            outside_mids=warmstart_outside_mids,
            user_id=user_id,
            seat="wh1_primary",
        )
        policy = LLMTutorPolicy(
            provider,
            # L3 관측·캐시 결선(OPS-36) — 앱 공유 LangfuseSink·RedisCache가 여기로 흘러
            # 학생 대면 LLM 호출이 비용 게이트② 표본에 계상된다. 미주입(단위테스트·app.state
            # 없는 경로)이면 좌석이 인메모리 기본값으로 폴백한다(하위호환).
            cache=cache,
            trace=trace,
            # 학생 원문·풀이 단계는 프롬프트가 아니라 정책 보유값으로만 사적 사용(S1-a 계약).
            student_text=student_solution,
            solution_steps=list(solution_steps),
            # select_probe 후보 공급(REC-02 ②) — 사적 probe 컨텍스트로만(프롬프트 미노출).
            probe_candidates=probe_candidates,
            theta=theta if theta is not None else 0.0,
            # 웜스타트 outside_mids도 사적 probe 컨텍스트로만(select_probe→plan_probe 전용·
            # 코칭 context에 오개념 preload 0·reactive retrieval 유지·CLAUDE.md).
            outside_mids=list(warmstart_outside_mids),
            # PED-04 D1 reader ②: 직전 세션의 교수 이력(메타 한정·원문 0·복호 0). 정책이
            # 예산 가드 안에서 요약에 실어 "이미 시도한 결"을 알게 한다.
            session_recall=session_recall,
        )
        timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else get_settings().wh1_primary_timeout_seconds
        )
        outcome: TurnOutcome = await asyncio.wait_for(
            run_tutoring_turn(
                policy=policy,
                turn_index=turn_index,
                has_solution_steps=bool(solution_steps),
                initial_hypotheses=list(active_hypotheses),
                max_tool_calls=max_tool_calls,
            ),
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001 — 앱은 죽지 않는다(방침 ④·결정론 폴백 신호).
        logger.warning(
            "WH-1 primary 하네스 실행 실패(%s) — 결정론 템플릿 폴백",
            type(exc).__name__,
            exc_info=True,
        )
        return None

    if outcome.status != "ended" or not outcome.utterance:
        # 예산 소진·발화 없음 — 관측은 남기고(원장 연속) 폴백 신호. 발화 원문 없음이라 톤 필드 0.
        _safe_emit(outcome, dialogue_id=dialogue_id, turn_index=turn_index, problem_id=problem_id)
        logger.warning(
            "WH-1 primary 발화 없음(status=%s·tool_calls=%d) — 결정론 템플릿 폴백",
            outcome.status,
            outcome.tool_calls,
        )
        return None

    # ── 프로즈 계층(S4-04·기본 OFF canary) — 톤필터 *직전*에 얹힌다(톤필터=최종 게이트 불변).
    # OFF면 이 블록 전체 미실행으로 기존 경로와 비트동일. ON이면: 파생 템플릿(utterance_source
    # =derived)은 정답-안전 rephrase(fail-closed=원 템플릿), 정책 자유발화(policy)는 외래
    # 등식·위생 게이트(실패=None 반환 → coach의 기존 결정론 폴백 재사용 — 파생 재조립 신설 0).
    utterance = outcome.utterance
    prose_rephrased = False
    prose_reason: str | None = None
    settings = get_settings()
    if settings.wh1_prose_rephrase_enabled:
        # 학생 재료(GT) — 러너가 이미 수령한 값(정책 사적 주입과 동일 원천·프롬프트 미유입).
        student_material = [student_solution, *solution_steps]
        if outcome.utterance_source == "policy":
            prose_reason = gate_policy_prose(utterance, student_material=student_material)
            if prose_reason is not None:
                # 거부 사유 코드만 로그·관측(발화 원문 미출력) — 결정론 폴백 신호.
                _safe_emit(
                    outcome,
                    dialogue_id=dialogue_id,
                    turn_index=turn_index,
                    problem_id=problem_id,
                    prose_reason_code=prose_reason,
                )
                logger.warning(
                    "WH-1 primary 정책 프로즈 게이트 거부(%s) — 결정론 템플릿 폴백", prose_reason
                )
                return None
        else:
            prose_outcome = await rephrase_coach_utterance(
                utterance,
                action_type=outcome.action_type,
                verdict=_extract_verify_verdict(outcome.trace),
                turn_index=turn_index,
                # 비민감 라벨 1건 — 활성 최상위 가설의 카탈로그 id(kebab·비PII). preload 아님.
                hypothesis_label=(
                    outcome.hypotheses[0].misconception_id if outcome.hypotheses else None
                ),
                forbidden_fragments=student_material,
                provider=provider,
                timeout_seconds=settings.wh1_prose_timeout_seconds,
                cache=cache,
                trace=trace,
            )
            utterance = prose_outcome.text  # fail-closed — 실패면 원 템플릿 그대로.
            prose_rephrased = prose_outcome.rephrased
            prose_reason = prose_outcome.reason_code

    # ── 금지모드 가드(PED-23 회수·옵트인 — 정본 04e §9) — 발화 확정 후·톤필터 *직전* 계층.
    # 팩(coach가 decide에 주입한 같은 객체)이 금지한 교수 모드를 발화가 위반하면 그 발화를
    # 학생에게 보내지 않고(fail-closed) 소크라테스 재질문(결정론 템플릿·기존 자산)으로 대체
    # 한다 — 04d §2.2 "차단 시 SOCRATIC 강등(말하기 대신 묻기)" 선례의 사후 가드판. 플래그
    # OFF(기본)거나 팩 부재(None — 팩 없으면 forbidden_modes도 없음)면 블록 미실행·비트동일.
    if settings.mode_guard_runtime_enabled and pack is not None:
        try:
            violated_mode = check_forbidden_modes(pack, utterance)
        except Exception as exc:  # noqa: BLE001 — 가드 자체 장애로 서빙을 죽이지 않는다.
            # 예외 skip은 침묵 금지(CLAUDE.md) — 타입명 로그. 발화는 기존 게이트(하네스 verify·
            # 정답 억제·톤필터)를 이미/곧 통과하므로 가드 판정 유보 상태로 서빙을 계속한다.
            logger.warning(
                "mode_guard 실행 실패(%s) — 가드 판정 유보·발화는 기존 게이트로만 서빙",
                type(exc).__name__,
                exc_info=True,
            )
            violated_mode = None
        if violated_mode is not None:
            # reason_code(위반 모드 토큰)·팩 유형만 구조화 로그 — 발화 원문은 싣지
            # 않는다(프라이버시·톤필터 로그 관례 동형). 조용한 폴백 금지.
            logger.warning(
                "mode_guard 위반(reason_code=%s·k_type=%s·detector=rule) — "
                "발화 미서빙·소크라테스 재질문 폴백",
                violated_mode,
                pack.k_type,
            )
            utterance = fallback_reply_for(violated_mode)

    # 톤필터 라이브 배선(방침 ③·KPI3) — 위반 시 rewritten 텍스트만 노출·위반 사실은 관측 기록.
    filtered, report = filter_tone(utterance)
    if report.rewritten:
        # 패턴 라벨·건수만 로그(고정 6패턴 카탈로그 상수) — 발화 원문은 로그에 싣지 않는다.
        logger.warning(
            "WH-1 primary 톤필터 위반 %d건 재작성(패턴=%s) — KPI3 관측",
            len(report.violations),
            sorted(set(report.violations)),
        )
    _safe_emit(
        outcome,
        dialogue_id=dialogue_id,
        turn_index=turn_index,
        problem_id=problem_id,
        tone_rewritten=report.rewritten,
        tone_violations=len(report.violations),
        prose_rephrased=prose_rephrased,
        prose_reason_code=prose_reason,
    )
    return filtered
