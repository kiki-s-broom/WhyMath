"""WH-S 솔버 루프 골격 — 도구 8종 디스패치 + 불변식 강제(설계 §3·§4·§7).

설계 정본: `docs/architecture/03b_wh_s_solver_harness.md` §3(전용 도구 8종)·§4(판정 규칙)·§2(상태
저장소). 본 모듈은 *결정론적 하네스 루프 드라이버*다 — `SolverPolicy`(도구 선택 두뇌)를 주입받아
도구를 실행하고, 검증기 스택(§4)·상태 저장소 4종(§2.1~§2.4)에 결선하며, §3 불변식을 강제한다.
**LLM 정책 모델·생성 도구(`parse_problem`·`decompose`·`apply_strategy`)의 *내용*은 정책이 공급
한다**(프로덕션=Ollama·테스트=`ScriptedPolicy`). 하네스는 그 결정을 *실행·검증·기록*만 한다.

7계층(§7.5): WH-S는 학생 세션 미개입 오프라인 업스트림이다. 본 하네스도 발화·API 노출이 없고
오프라인 솔버 배치가 호출한다.

강제 불변식(§3·§4):
  - **verify 없는 finalize 거부**: `finalize`는 *반드시* 검증기 스택을 돌려 `final_verdict`로 등급을
    매긴다(정책의 주장만으로 적재하지 않는다). 즉 finalize=verify+커밋이 한 몸이다.
  - **failed 차단**: `final_verdict`가 `failed`(오답/틀린 과정)면 *적재하지 않는다*(저장소 enum이
    failed를 배제 — `VerifiedSolution`). 검색은 종료되지 않고(정책이 다른 경로 시도) 계속한다.
  - **unverifiable → unverified 격리**: 판정 불가 최종 풀이는 `unverified` 등급으로 *적재하되*
    학습 배제(§3·R-S2). verified만 finalize 성공으로 검색 종료.
  - **finalize 멱등(dedup)**: 적재는 `bank_solution(dedup=True)`로 한다 — 여러 런이 같은 문제의
    *동일 경로*를 재발견하면 기존 행을 재사용한다(자기진화 데이터 중복 차단·§2.4·§5·위생).
  - **탐색 예산 상한**: `max_tool_calls` 초과 시 하네스가 강제 종료(`budget_exhausted`·안전
    종료·R-S4 문제당 탐색 예산 상한). 무한 루프·과대 컴퓨트 차단.
  - **dead-end 회피**: `apply_strategy`는 적용 전 `is_dead_end`를 조회해 이미 막다른 길이면
    *건너뛴다*(노드 미생성·중복 탐색 차단·§2.3).
  - **검증된 보조정리만 log_lemma**: `log_lemma`는 *직전 verify 등급이 verified*일 때만 적재한다
    (§2.2 — 미검증 부분 결과는 격리되지 않고 아예 안 들어옴).

도구 8종(§3) ↔ 본 하네스 처리:
  1 parse_problem  : 정책 공급(구조화 표현) — 하네스는 상태에 기록(부수효과 0·LLM 본질).
  2 retrieve_similar: 하네스가 검증 풀이 저장소·보조정리 저장소 조회(웜 스타트·결정론).
  3 decompose      : 정책 공급(보조 목표) — 상태 기록.
  4 apply_strategy : 정책 공급(전략 1스텝) — 하네스가 dead-end 회피 후 풀이 트리 노드 생성.
  5 verify         : 하네스가 검증기 스택(verify_answer+verify_solution+final_verdict) 실행.
  6 conjecture_check: 하네스가 수치 반례 탐색(verify_answer 재사용·거짓 추측 가지치기).
  7 log_lemma/log_deadend: 하네스가 저장소 적재(보조정리는 verified 전제).
  8 finalize       : 하네스가 verify+등급 매핑+저장소 커밋(failed 차단·dedup 멱등·검색 종료).

범위 밖(후속·환경 밖): LLM 정책 모델(Ollama·Phaiakes9)·생성 도구 내용 생성·MCTS-lite 탐색·PRM·
Tier3(Lean4). 본 모듈은 *결정론 루프 드라이버 + 도구 결선 + 불변식*만 둔다.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

# AsyncSession은 타입 체킹에만 필요(런타임은 주입). 순환/무거운 import 회피.
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.verified_solution import WhsSolutionGrade
from whymath_backend.l3.equivalent.acceptance import _CONCEPTUAL_VERIFIERS
from whymath_backend.l3.verify_answer import AnswerVerdict, verify_answer
from whymath_backend.l3.verify_solution import verify_solution
from whymath_backend.whs import dead_end_store, lemma_store, node_store, solution_bank
from whymath_backend.whs.verdict import WhsGrade, final_verdict

__all__ = [
    "Action",
    "ApplyStrategyAction",
    "ConjectureCheckAction",
    "DecomposeAction",
    "EndSearchAction",
    "FinalizeAction",
    "LogDeadEndAction",
    "LogLemmaAction",
    "ParseProblemAction",
    "RetrieveSimilarAction",
    "ScriptedPolicy",
    "SolverOutcome",
    "SolverPolicy",
    "SolverState",
    "ToolResult",
    "VerifyAction",
    "run_solver",
]


# ──────────────────────────────────────────────────────────────────────
# 액션(도구 호출) — 정책이 방출, 하네스가 실행. `kind` 판별 유니온.
# ──────────────────────────────────────────────────────────────────────


class _ActionBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ParseProblemAction(_ActionBase):
    """도구1 parse_problem — 정책이 구조화 표현(조건·구할 것·도메인·패턴)을 공급."""

    kind: Literal["parse_problem"] = "parse_problem"
    structured: dict[str, Any]


class RetrieveSimilarAction(_ActionBase):
    """도구2 retrieve_similar — 하네스가 검증 풀이·보조정리 저장소 조회(웜 스타트)."""

    kind: Literal["retrieve_similar"] = "retrieve_similar"


class DecomposeAction(_ActionBase):
    """도구3 decompose — 정책이 보조 목표(부분문제)를 공급."""

    kind: Literal["decompose"] = "decompose"
    subgoals: list[str]


class ApplyStrategyAction(_ActionBase):
    """도구4 apply_strategy — 정책이 전략 1스텝을 공급. 하네스가 dead-end 회피 후 트리 노드 생성."""

    kind: Literal["apply_strategy"] = "apply_strategy"
    action_label: str
    state_repr: dict[str, Any]
    state_hash: str
    parent_id: uuid.UUID | None = None


class VerifyAction(_ActionBase):
    """도구5 verify — 하네스가 검증기 스택 실행(답 검산 + 단계 동치 → final_verdict)."""

    kind: Literal["verify"] = "verify"
    conditions: list[str]
    answer: dict[str, str]
    steps: list[str] = Field(default_factory=list)


class ConjectureCheckAction(_ActionBase):
    """도구6 conjecture_check — 하네스가 수치 반례 탐색(verify_answer 재사용·가지치기)."""

    kind: Literal["conjecture_check"] = "conjecture_check"
    conditions: list[str]
    candidate: dict[str, str]


class LogLemmaAction(_ActionBase):
    """도구7a log_lemma — 검증된 부분 결과 적재(직전 verify=verified 전제)."""

    kind: Literal["log_lemma"] = "log_lemma"
    lemma_key: str
    lemma_repr: dict[str, Any]
    statement: str | None = None
    source_node_id: uuid.UUID | None = None


class LogDeadEndAction(_ActionBase):
    """도구7b log_deadend — 막다른 길 기록(멱등)."""

    kind: Literal["log_deadend"] = "log_deadend"
    state_hash: str
    action_label: str
    reason: str | None = None


class FinalizeAction(_ActionBase):
    """도구8 finalize — 완전 풀이 조립 + 최종 검증 + 저장소 커밋(failed 차단·검색 종료)."""

    kind: Literal["finalize"] = "finalize"
    conditions: list[str]
    answer: dict[str, str]
    steps: list[str] = Field(default_factory=list)
    strategy_tag: str | None = None
    source_root_id: uuid.UUID | None = None
    # P3-95: 답이 값이 아니라 *개수·판정*인 개념형 문항(예: real_root_count — "서로 다른 실근의
    # 개수")은 `answer` 치환맵으로 검산할 수 없다. 그때 `answer_kind`(개념형 검증기 키)와
    # `claimed_answer`(주장 답 원문, 예 "1")를 함께 주면 Tier1을 개념형 검증기로 돌린다.
    answer_kind: str | None = None
    claimed_answer: str | None = None


class EndSearchAction(_ActionBase):
    """검색 포기(정책이 더 시도하지 않기로) — finalize 없이 종료."""

    kind: Literal["end_search"] = "end_search"
    reason: str | None = None


Action = Annotated[
    ParseProblemAction
    | RetrieveSimilarAction
    | DecomposeAction
    | ApplyStrategyAction
    | VerifyAction
    | ConjectureCheckAction
    | LogLemmaAction
    | LogDeadEndAction
    | FinalizeAction
    | EndSearchAction,
    Field(discriminator="kind"),
]


# ──────────────────────────────────────────────────────────────────────
# 결과·상태·정책·결과물
# ──────────────────────────────────────────────────────────────────────


class ToolResult(BaseModel):
    """도구 1회 실행 결과 — 트레이스 단위. `ok=False`는 하네스가 거부·건너뜀(불변식)을 뜻한다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str = Field(description="실행된 도구 종류(action.kind).")
    ok: bool = Field(description="실행/적용 성공 여부(거부·건너뜀·실패 검증은 False).")
    detail: str = Field(description="사람 가독 사유(거부·등급·반례 등).")
    grade: WhsGrade | None = Field(default=None, description="verify/finalize의 최종 등급(있으면).")
    node_id: uuid.UUID | None = Field(default=None, description="apply_strategy가 만든 노드 id.")
    banked_solution_id: uuid.UUID | None = Field(
        default=None, description="finalize가 적재한 검증 풀이 id."
    )


@dataclass
class SolverState:
    """탐색 진행 상태 — 정책에 전달(가변). 하네스가 도구 실행마다 갱신한다."""

    problem_id: uuid.UUID
    tool_calls: int = 0
    root_id: uuid.UUID | None = None  # 첫 apply_strategy 노드(트리 루트)
    last_verify_grade: WhsGrade | None = None  # 직전 verify 등급(log_lemma 전제)
    finalized: bool = False
    banked_solution_id: uuid.UUID | None = None
    history: list[ToolResult] = field(default_factory=list)


@runtime_checkable
class SolverPolicy(Protocol):
    """도구 선택 두뇌 — 다음 액션을 고른다. 프로덕션=LLM(Ollama)·테스트=ScriptedPolicy.

    하네스는 정책이 고른 액션을 *실행·검증·기록*만 한다(정책의 추론 내용은 신뢰하되 verify로 검증).
    """

    async def next_action(self, state: SolverState) -> Action:  # pragma: no cover - 프로토콜
        ...


class SolverOutcome(BaseModel):
    """run_solver 종료 결과 — 최종 상태 + 트레이스."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["finalized", "budget_exhausted", "ended"] = Field(
        description=(
            "finalized(검증 풀이 적재 완료)·budget_exhausted(탐색 예산 소진·안전 종료)·"
            "ended(정책이 end_search로 포기)."
        )
    )
    final_grade: WhsGrade | None = Field(
        default=None, description="finalize된 풀이의 등급(verified/unverified)."
    )
    banked_solution_id: uuid.UUID | None = Field(
        default=None, description="적재된 검증 풀이 id(finalize 성공 시)."
    )
    tool_calls: int = Field(description="총 도구 호출 횟수.")
    trace: list[ToolResult] = Field(description="도구 실행 트레이스(감사·디버그).")


class ScriptedPolicy:
    """결정론 정책 — 미리 정한 액션 시퀀스를 순서대로 방출(테스트·골격 데모용).

    LLM 정책의 *자리표시자*다. 시퀀스 소진 시 `EndSearchAction`을 반환해 루프를 안전 종료한다.
    """

    def __init__(self, actions: Sequence[Action]) -> None:
        self._actions = list(actions)
        self._index = 0

    async def next_action(self, state: SolverState) -> Action:
        if self._index >= len(self._actions):
            return EndSearchAction(reason="스크립트 소진")
        action = self._actions[self._index]
        self._index += 1
        return action


# ──────────────────────────────────────────────────────────────────────
# 도구 실행 (결정론·저장소/검증기 결선)
# ──────────────────────────────────────────────────────────────────────


def _tier1(
    conditions: list[str],
    answer: dict[str, str],
    *,
    answer_kind: str | None,
    claimed_answer: str | None,
) -> AnswerVerdict:
    """Tier1 답 검산 — 값형은 `verify_answer`(치환 대입), 개념형은 `_CONCEPTUAL_VERIFIERS`(P3-95).

    개념형 판정은 `l3/equivalent/acceptance`와 같은 표를 쓴다(검증기 단일 원천). 알 수 없는 키·
    주장 답 없음은 pass로 위장하지 않고 unverifiable로 둔다 — final_verdict가 unverified(격리)로
    매긴다.
    """
    if answer_kind is None:
        return verify_answer(conditions, answer)
    verifier = _CONCEPTUAL_VERIFIERS.get(answer_kind)
    if verifier is None:
        return AnswerVerdict(
            state="unverifiable",
            reason=f"개념형 검증기 없음({answer_kind}) — 안전 회피",
            samples_checked=0,
        )
    if claimed_answer is None or not claimed_answer.strip():
        return AnswerVerdict(
            state="unverifiable",
            reason=f"개념형({answer_kind}) 주장 답 없음 — 안전 회피",
            samples_checked=0,
        )
    return verifier(conditions, claimed_answer)


def _run_verify(
    conditions: list[str],
    answer: dict[str, str],
    steps: list[str],
    *,
    answer_kind: str | None = None,
    claimed_answer: str | None = None,
) -> WhsGrade:
    """검증기 스택 실행 → 최종 등급(§4). 답 검산(Tier1) + 단계 동치(Tier2) → final_verdict."""
    answer_verdict = _tier1(
        conditions, answer, answer_kind=answer_kind, claimed_answer=claimed_answer
    )
    steps_result = verify_solution(steps)
    return final_verdict(answer_verdict, steps_result).grade


async def _exec(session: AsyncSession, state: SolverState, action: Action) -> ToolResult:
    """단일 액션 실행 — 도구별 디스패치 + 불변식 강제. 상태를 in-place 갱신한다."""
    if isinstance(action, ParseProblemAction):
        return ToolResult(kind=action.kind, ok=True, detail="구조화 표현 기록(정책 공급).")

    if isinstance(action, DecomposeAction):
        return ToolResult(
            kind=action.kind, ok=True, detail=f"보조 목표 {len(action.subgoals)}개 기록."
        )

    if isinstance(action, RetrieveSimilarAction):
        verified = await solution_bank.get_verified(session, state.problem_id)
        lemmas = await lemma_store.get_lemmas(session, state.problem_id)
        return ToolResult(
            kind=action.kind,
            ok=True,
            detail=f"웜스타트 — 검증풀이 {len(verified)}·보조정리 {len(lemmas)}.",
        )

    if isinstance(action, ApplyStrategyAction):
        # dead-end 회피(§2.3) — 이미 막다른 길이면 노드 생성하지 않고 건너뛴다.
        if await dead_end_store.is_dead_end(
            session,
            problem_id=state.problem_id,
            state_hash=action.state_hash,
            action=action.action_label,
        ):
            return ToolResult(kind=action.kind, ok=False, detail="dead-end 회피 — 건너뜀.")
        node = await node_store.create_node(
            session,
            problem_id=state.problem_id,
            parent_id=action.parent_id,
            state_repr=action.state_repr,
            action=action.action_label,
        )
        if state.root_id is None:
            state.root_id = node.id
        return ToolResult(kind=action.kind, ok=True, detail="전략 적용 노드 생성.", node_id=node.id)

    if isinstance(action, VerifyAction):
        grade = _run_verify(action.conditions, action.answer, action.steps)
        state.last_verify_grade = grade
        return ToolResult(kind=action.kind, ok=True, detail=f"검증 등급 {grade}.", grade=grade)

    if isinstance(action, ConjectureCheckAction):
        # 수치 반례 탐색 — fail이면 추측 반증(가지치기 신호). pass/unverifiable이면 반례 없음.
        verdict = verify_answer(action.conditions, action.candidate)
        if verdict.state == "fail":
            return ToolResult(kind=action.kind, ok=True, detail="반례 발견 — 추측 반증(가지치기).")
        return ToolResult(kind=action.kind, ok=True, detail="반례 없음(수치 한정).")

    if isinstance(action, LogDeadEndAction):
        await dead_end_store.log_dead_end(
            session,
            problem_id=state.problem_id,
            state_hash=action.state_hash,
            action=action.action_label,
            reason=action.reason,
        )
        return ToolResult(kind=action.kind, ok=True, detail="막다른 길 기록(멱등).")

    if isinstance(action, LogLemmaAction):
        # 검증된 보조정리만 적재(§2.2) — 직전 verify가 verified일 때만.
        if state.last_verify_grade != "verified":
            return ToolResult(
                kind=action.kind,
                ok=False,
                detail="거부 — 직전 verify=verified 아님(미검증 보조정리).",
            )
        await lemma_store.log_lemma(
            session,
            problem_id=state.problem_id,
            lemma_key=action.lemma_key,
            lemma_repr=action.lemma_repr,
            statement=action.statement,
            source_node_id=action.source_node_id,
        )
        return ToolResult(kind=action.kind, ok=True, detail="검증 보조정리 적재(멱등).")

    if isinstance(action, FinalizeAction):
        # verify 없는 finalize 거부(§3) — finalize는 항상 검증기 스택을 돌린다.
        grade = _run_verify(
            action.conditions,
            action.answer,
            action.steps,
            answer_kind=action.answer_kind,
            claimed_answer=action.claimed_answer,
        )
        state.last_verify_grade = grade
        if grade == "failed":
            # failed 차단(§4·R-S2) — 적재하지 않는다. 검색은 종료되지 않음(정책 재시도 가능).
            return ToolResult(
                kind=action.kind,
                ok=False,
                detail="finalize 거부 — failed(오답/틀린 과정·미적재).",
                grade=grade,
            )
        # verified/unverified만 적재. unverifiable→unverified 격리(§3).
        bank_grade = (
            WhsSolutionGrade.VERIFIED if grade == "verified" else WhsSolutionGrade.UNVERIFIED
        )
        # dedup=True(§2.4·#255): 여러 런이 같은 문제의 *동일 경로*를 재발견하면 기존 행을 재사용
        # 한다(idempotent) — 자기진화 데이터(§5)에 재발견 중복이 쌓이는 것을 막는다(위생·R-S2).
        solution = await solution_bank.bank_solution(
            session,
            problem_id=state.problem_id,
            grade=bank_grade,
            solution_path=_solution_path_json(action),
            strategy_tag=action.strategy_tag,
            answer=(
                _answer_str(action.answer) if action.answer_kind is None else action.claimed_answer
            ),
            source_root_id=action.source_root_id or state.root_id,
            dedup=True,
        )
        state.finalized = True
        state.banked_solution_id = solution.id
        return ToolResult(
            kind=action.kind,
            ok=True,
            # dedup 히트 시 "적재"는 과대주장 → "확정"으로 정직 표기(구조 필드는 히트/미스 불변).
            detail=f"검증 풀이 확정(등급 {grade}·중복은 기존 재사용).",
            grade=grade,
            banked_solution_id=solution.id,
        )

    # EndSearchAction은 run_solver가 루프에서 직접 처리(여기 도달하지 않음).
    raise AssertionError(f"미처리 액션: {action!r}")  # pragma: no cover - 유니온 가드


def _solution_path_json(action: FinalizeAction) -> dict[str, Any]:
    """적재 JSONB — 값형은 종전 3키 그대로(dedup 정확 일치 불변), 개념형만 2키를 더한다."""
    path: dict[str, Any] = {
        "conditions": action.conditions,
        "answer": action.answer,
        "steps": action.steps,
    }
    if action.answer_kind is not None:
        path["answer_kind"] = action.answer_kind
        path["claimed_answer"] = action.claimed_answer
    return path


def _answer_str(answer: dict[str, str]) -> str | None:
    """답 dict → 검색·중복 식별용 안정 문자열. 빈 dict면 None(증명 등 답 없음)."""
    if not answer:
        return None
    return ", ".join(f"{k}={answer[k]}" for k in sorted(answer))


# ──────────────────────────────────────────────────────────────────────
# 루프 드라이버
# ──────────────────────────────────────────────────────────────────────


async def run_solver(
    session: AsyncSession,
    *,
    problem_id: uuid.UUID,
    policy: SolverPolicy,
    max_tool_calls: int = 32,
) -> SolverOutcome:
    """WH-S 솔버 루프 — 정책이 도구를 고르고 하네스가 실행·검증·기록한다(§3 골격).

    종료 조건: ① `finalize` 성공(검증 풀이 적재·`finalized`) ② 탐색 예산(`max_tool_calls`) 소진
    (`budget_exhausted`·안전 종료) ③ 정책이 `end_search`(`ended`). 불변식(verify 없는 finalize 거부·
    failed 차단·unverifiable 격리·dead-end 회피·검증 보조정리만)은 `_exec`가 강제한다. 트랜잭션
    commit은 호출자 관리(저장소 패턴 일관).

    `max_tool_calls`는 R-S4 문제당 탐색 예산 상한 — 무한 루프·과대 컴퓨트를 구조 차단한다.
    """
    if max_tool_calls < 1:
        raise ValueError("max_tool_calls는 1 이상이어야 합니다.")
    state = SolverState(problem_id=problem_id)

    while state.tool_calls < max_tool_calls and not state.finalized:
        action = await policy.next_action(state)
        if isinstance(action, EndSearchAction):
            return SolverOutcome(
                status="ended",
                final_grade=None,
                banked_solution_id=None,
                tool_calls=state.tool_calls,
                trace=state.history,
            )
        result = await _exec(session, state, action)
        state.tool_calls += 1
        state.history.append(result)

    if state.finalized:
        return SolverOutcome(
            status="finalized",
            final_grade=state.last_verify_grade,
            banked_solution_id=state.banked_solution_id,
            tool_calls=state.tool_calls,
            trace=state.history,
        )
    return SolverOutcome(
        status="budget_exhausted",
        final_grade=None,
        banked_solution_id=None,
        tool_calls=state.tool_calls,
        trace=state.history,
    )
