"""WH-1 튜터링 턴 루프 골격 — 도구 8종 디스패치 + 불변식 강제(설계 §3·§3.4·§2.2·§5).

설계 정본: `docs/architecture/04a_wh1_tutoring_harness.md` §3(전용 도구 8종)·§3.4(설계 원칙)·
§2.2(확증편향 방지·ε-탐색)·§5(루프 제어). 본 모듈은 *결정론적 한 턴 드라이버*다 — `TutorPolicy`
(도구 선택 두뇌)를 주입받아 도구를 실행하고, 지금까지 만든 *순수 도구*(`diagnose`·`curate`·
`plan_probe`·`verify_solution`·`select_intervention_from_hypotheses`)에 결선하며 §3.4 불변식을
강제한다. **LLM 정책의 *내용*은 정책이 공급**(프로덕션=클라우드/Ollama·테스트=`ScriptedPolicy`).
하네스는 그 결정을 *실행·검증·기록*만 한다(WH-S `run_solver` 선례 동형).

계층(설계 §1): WH-1 하네스는 *새 계층이 아니라 횡단 인프라*다(L5 오케스트레이터처럼 하위 계층
도구를 호출). 본 턴 루프는 **작업 메모리를 in-memory로** 들고 돈다(§2.1 — 세션 작업 메모리는
Redis·턴 종료 시 PostgreSQL 스냅샷). 즉 가설 세트·증거 원장을 `TurnState`에 두고 *영속은 호출자
(세션 오케스트레이터)의 커밋 좌석*이다(`hypothesis_store.curate_hypothesis`·`evidence_store.
log_evidence`·BKT 커밋 결선은 후속). 그래서 본 골격은 *순수·DB 무접근*이라 hermetic 검증된다.

강제 불변식(§3.4·§2.2):
  - **end_turn만이 학생에게 말한다**(§3.4-3): 중간 도구(match·curate·verify·probe·log_evidence)는
    전부 *내부 동작*이고 학생 발화를 만들지 않는다. `EndTurnAction`만 `utterance`를 산출하고 턴을
    종료한다.
  - **verify 호출 의무**(§3.1·§3.4-1): 학생 *풀이 단계 제출 턴*(`has_solution_steps=True`)은
    `verify_step`을 호출해야 한다 — 미호출 상태의 `end_turn`은 *거부*(WH-S "verify 없는 finalize
    거부" 동형). `unverifiable`이어도 *호출*했으면 통과(§3.1 3-state).
  - **정답 억제 백스톱**(감사 Q6·CLAUDE.md "막혔을 때 바로 정답 금지"): 학생 풀이가 `correct`가
    아닌 턴(`incorrect`·`unverifiable`=오답/막힘)에서는 정책이 실은 *명시 발화*(`utterance`)를
    신뢰하지 않고 하네스가 소크라테스 유도 발화를 파생한다 — LLM이 정답을 발화에 흘려도 학생에게
    닿지 못한다. 이 강제는 *하네스*에 있어 정책 선의에 의존하지 않는다(어떤 `TutorPolicy`가 와도
    성립). `correct`·검증 없는 순수 대화 턴에서만 명시 발화를 존중한다(정답 노출 위험 0).
  - **ε-탐색 강제**(§2.2 규칙2): `is_exploration_turn(turn_index)`인 턴의 `select_probe`는 활성
    가설 세트 *밖*을 겨냥해야 한다 — 외부 후보 미제공 등으로 탐색이 안 되면 probe 요청을 *거부*
    (하네스가 카운터 관리·위반 거부).
  - **증거 게이트**(정확성 #1·거짓 낙인 차단): `log_evidence`는 `misconception_id ∈ CATALOG_BY_ID`
    + `polarity ∈ {−1,+1}`만 적재(미등록·잘못된 극성 거부·`evidence_store` 게이트 동형).
  - **턴 예산 상한**(§5.2 루프 가드): `max_tool_calls` 초과 시 안전 종료(`budget_exhausted`).

도구 8종(§3) ↔ 본 하네스 처리(순수):
  1 read_student_state: 정책 공급(노드 컨텍스트) — 기록(L2 BKT 조인은 영속 좌석 후속).
  2 verify_step       : 하네스가 `verify_solution`(L3·순수 SymPy) 실행 → 3-state.
  3 match_misconception: 하네스가 `diagnose`(L4·substring 순수) 실행 → 후보.
  4 curate_hypothesis : 하네스가 순수 `curate`(감쇠·강화·반박·최대5) 실행 — 반박은 *in-memory
    증거 원장 순지지도<0*에서(net_support 동형). 작업 메모리 갱신.
  5 query_curriculum  : 정책 공급(노드·관계) — 기록(L1+L2 조인은 영속 좌석 후속).
  6 select_probe      : 하네스가 `plan_probe`(L4·정보이득·ε) 실행 + ε-탐색 불변식.
  7 log_evidence      : 하네스가 게이트 후 in-memory 증거 원장에 적재.
  8 end_turn          : 하네스가 verify 의무 검사 후 학생 발화 산출(질문/힌트=가설 세트 개입
    발화 결선·출제=직전 probe·격려=정책/기본)·턴 종료.

영속 좌석(분리): 본 모듈은 *순수 골격*이고, in-memory 작업 메모리(가설 세트·증거 원장)를 실제
스토어에 커밋하는 건 `harness/wh1_session.py`(`run_persisted_turn` — 웜 스타트 로드→본 루프 실행→
`evidence_store.log_evidence`·`hypothesis_store.persist_hypotheses` 커밋)가 담당한다.

범위 밖(후속): BKT 커밋 큐(§2.4)·Redis 작업 메모리 스냅샷(§2.1)·`/v1/coach/sessions` 멀티턴
엔드포인트 결선·LLM 정책 모델·fast path(§5.3)·전략 계층 도구(§11.3)·진단-실제 일치율 게이트.
본 모듈은 *결정론 한 턴 드라이버 + 순수 도구 결선 + 불변식*만 둔다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Annotated, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from whymath_backend.config import get_settings
from whymath_backend.l2.remediation_policy import EscalationRung
from whymath_backend.l3.verify_solution import SolutionVerificationResult, verify_solution
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.l4.misconception.crosslink_shadow import observe_crosslink_shadow
from whymath_backend.l4.misconception.diagnose import diagnose
from whymath_backend.l4.misconception.hypothesis import MisconceptionHypothesis, curate
from whymath_backend.l4.misconception.intervene import select_intervention_from_hypotheses
from whymath_backend.l4.misconception.models import MisconceptionMatch
from whymath_backend.l4.misconception.probe_selection import (
    _EXPLORE_PERIOD,
    ProbeCandidate,
    ProbeSelection,
    is_exploration_turn,
    plan_probe,
)

__all__ = [
    "Action",
    "CurateHypothesisAction",
    "ENCOURAGE_FALLBACK_UTTERANCE",
    "EndTurnAction",
    "EndTurnType",
    "EvidenceEdge",
    "LogEvidenceAction",
    "MatchMisconceptionAction",
    "NEUTRAL_GUIDE_UTTERANCE",
    "QueryCurriculumAction",
    "ReadStateAction",
    "ScriptedTutorPolicy",
    "SelectProbeAction",
    "ToolResult",
    "TurnOutcome",
    "TurnState",
    "TutorPolicy",
    "UtteranceSource",
    "VerifyStepAction",
    "run_tutoring_turn",
]

_VALID_POLARITY = (-1, 1)

# 정답 억제 백스톱이 발동하는 3-state verdict — 학생 풀이가 correct가 아닌(오답·미검증=막힘)
# 상태. 이때 end_turn의 정책 명시 발화를 신뢰하지 않고 하네스가 소크라테스 발화를 파생한다.
_ANSWER_SUPPRESSED_VERDICTS: tuple[str, ...] = ("incorrect", "unverifiable")

EndTurnType = Literal["질문", "힌트", "출제", "격려"]
"""end_turn 행위 4종(§3 도구8) — 학생에게 전달되는 발화 유형."""

# 파생 발화 고정 템플릿(공개 상수·값 불변) — "같은 답 반복"의 잔여이자 S4-04 프로즈
# rephrase의 정확-일치 화이트리스트 원천. probe(_FALLBACKS)·프로즈 계층이 import해
# 단일 원천으로 쓴다. 값 변경은 회귀 핀(test_wh1_loop.py 정확 문자열 단언)과 함께만.
NEUTRAL_GUIDE_UTTERANCE = "방금 단계에서 무엇을 근거로 그렇게 했는지 말해줄래?"
ENCOURAGE_FALLBACK_UTTERANCE = "좋아, 지금까지 잘 하고 있어. 다음으로 가보자."

UtteranceSource = Literal["policy", "derived"]
"""발화 출처 — policy(정책 명시 발화 존중 턴)·derived(하네스 파생: 개입·중립·출제·격려).

프로즈 계층(S4-04)이 rephrase 대상(derived 템플릿)과 게이트 대상(policy 자유발화)을
구조적으로 구분하는 신호. 판정은 `_uses_explicit_utterance` 단일 술어가 소유한다.
"""


# ──────────────────────────────────────────────────────────────────────
# 액션(도구 호출) — 정책이 방출, 하네스가 실행. `kind` 판별 유니온(WH-S 동형).
# ──────────────────────────────────────────────────────────────────────


class _ActionBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReadStateAction(_ActionBase):
    """도구1 read_student_state — 정책이 조회할 노드 컨텍스트 공급(L2 BKT 조인은 영속 좌석 후속)."""

    kind: Literal["read_student_state"] = "read_student_state"
    node_ids: list[str] = Field(default_factory=list)


class MatchMisconceptionAction(_ActionBase):
    """도구3 match_misconception — 학생 풀이 텍스트. 하네스가 `diagnose`(순수) 실행."""

    kind: Literal["match_misconception"] = "match_misconception"
    student_text: str


class CurateHypothesisAction(_ActionBase):
    """도구4 curate_hypothesis — 하네스가 순수 `curate`로 작업 메모리 가설 세트 갱신."""

    kind: Literal["curate_hypothesis"] = "curate_hypothesis"
    turns_elapsed: int = 1


class VerifyStepAction(_ActionBase):
    """도구2 verify_step — 풀이 단계 시퀀스. 하네스가 `verify_solution`(L3) 실행 → 3-state."""

    kind: Literal["verify_step"] = "verify_step"
    steps: list[str] = Field(default_factory=list)


class QueryCurriculumAction(_ActionBase):
    """도구5 query_curriculum — 정책 공급(노드·관계). 기록(L1+L2 조인은 영속 좌석 후속)."""

    kind: Literal["query_curriculum"] = "query_curriculum"
    node_id: str
    relation: Literal["선수", "후속", "형제"] = "선수"


class SelectProbeAction(_ActionBase):
    """도구6 select_probe — 진단 문항 후보·θ·외부 오개념. 하네스가 `plan_probe` 실행 + ε 불변식."""

    kind: Literal["select_probe"] = "select_probe"
    candidates: list[ProbeCandidate] = Field(default_factory=list)
    theta: float = 0.0
    outside_mids: list[str] = Field(default_factory=list)
    administered: list[str] = Field(default_factory=list)


class LogEvidenceAction(_ActionBase):
    """도구7 log_evidence — 증거 엣지(게이트 후 in-memory 원장 적재)."""

    kind: Literal["log_evidence"] = "log_evidence"
    misconception_id: str
    polarity: int
    weight: float | None = None


class EndTurnAction(_ActionBase):
    """도구8 end_turn — *유일하게 학생에게 말하는* 도구. verify 의무 검사 후 발화·턴 종료."""

    kind: Literal["end_turn"] = "end_turn"
    action_type: EndTurnType
    utterance: str | None = Field(
        default=None, description="명시 발화(없으면 질문/힌트는 가설 세트 개입 발화로 결선)."
    )


Action = Annotated[
    ReadStateAction
    | MatchMisconceptionAction
    | CurateHypothesisAction
    | VerifyStepAction
    | QueryCurriculumAction
    | SelectProbeAction
    | LogEvidenceAction
    | EndTurnAction,
    Field(discriminator="kind"),
]


# ──────────────────────────────────────────────────────────────────────
# 결과·상태·정책·결과물
# ──────────────────────────────────────────────────────────────────────


class ToolResult(BaseModel):
    """도구 1회 실행 결과 — 트레이스 단위. `ok=False`는 하네스가 거부·건너뜀(불변식)을 뜻한다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str = Field(description="실행된 도구 종류(action.kind).")
    ok: bool = Field(description="실행/적용 성공 여부(거부·게이트 위반은 False).")
    detail: str = Field(description="사람 가독 사유(거부·등급·발화 등·내부용·학생 비노출).")
    verify_form_counts: dict[str, int] | None = Field(
        default=None,
        description=(
            "verify_step 전이의 *판정 경로 형태*별 개수(equation|mixed|expression·S3-51). "
            "verify_step 실행 결과에만 채워지고 다른 도구는 None이다. 값은 개수뿐 — 학생 "
            "원문·식은 담지 않는다(shadow 관측 레코드의 비식별 계약 유지). 관측 전용이며 "
            "하네스 판정(3-state·불변식)에는 쓰이지 않는다."
        ),
    )


class EvidenceEdge(BaseModel):
    """이 턴에 적재된 증거 엣지 1건 — net_support 집계 + 영속(`evidence_links`) 입력. 불변(frozen).

    `log_evidence` 게이트(카탈로그·극성)를 통과한 엣지만 담긴다. 호출자(영속 좌석)가 이 엣지들을
    `evidence_store.log_evidence`로 DB에 커밋한다(session_id·student_id는 그때 주입).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    misconception_id: str = Field(description="증거가 지지/반박하는 오개념 id(카탈로그 실재).")
    polarity: int = Field(description="+1 지지/−1 반박.")
    weight: float | None = Field(
        default=None, description="verify/PRM 기반 가중치(없으면 1.0 취급)."
    )


@dataclass
class TurnState:
    """한 턴 작업 메모리(§2.1) — 정책에 전달(가변). 하네스가 도구 실행마다 갱신한다.

    `hypotheses`(가설 세트)·`evidence`(증거 원장)는 영속 스냅샷에서 복원돼 들어오고(여기선
    `initial_hypotheses`), 턴 종료 후 호출자가 영속한다(커밋 좌석 후속).
    """

    turn_index: int
    has_solution_steps: bool
    hypotheses: list[MisconceptionHypothesis]
    evidence: list[EvidenceEdge] = field(default_factory=list)
    last_matches: list[MisconceptionMatch] = field(default_factory=list)
    last_probe: ProbeSelection | None = None
    verify_called: bool = False
    last_verdict: Literal["correct", "incorrect", "unverifiable"] | None = None
    tool_calls: int = 0
    ended: bool = False
    utterance: str | None = None
    utterance_source: UtteranceSource | None = None
    end_action_type: EndTurnType | None = None
    escalation_rung: EscalationRung | None = None
    history: list[ToolResult] = field(default_factory=list)


@runtime_checkable
class TutorPolicy(Protocol):
    """도구 선택 두뇌 — 다음 액션을 고른다. 프로덕션=LLM·테스트=ScriptedTutorPolicy.

    하네스는 정책이 고른 액션을 *실행·검증·기록*만 한다(정책의 추론 내용은 verify·게이트로 검증).
    """

    async def next_action(self, state: TurnState) -> Action:  # pragma: no cover - 프로토콜
        ...


class TurnOutcome(BaseModel):
    """run_tutoring_turn 종료 결과 — 학생 발화 + 갱신된 작업 메모리 + 트레이스."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ended", "budget_exhausted"] = Field(
        description="ended(end_turn으로 발화·종료)·budget_exhausted(턴 예산 소진·안전 종료)."
    )
    action_type: EndTurnType | None = Field(
        default=None, description="end_turn 행위 유형(ended일 때)."
    )
    utterance: str | None = Field(
        default=None, description="학생에게 전달되는 *유일한* 발화(end_turn 산출·ended일 때)."
    )
    utterance_source: UtteranceSource | None = Field(
        default=None,
        description=(
            "발화 출처 — policy(정책 명시 발화 존중)·derived(하네스 파생 템플릿). "
            "프로즈 계층(S4-04)의 라우팅 신호(ended일 때만·기본 None=하위호환)."
        ),
    )
    escalation_rung: EscalationRung | None = Field(
        default=None,
        description=(
            "이 턴 개입의 반복 오류 강도 등급(`l2/remediation_policy.py` 정본). "
            "**3상태다** — `None`은 이 턴에 개입 결정이 없었다(사다리의 분모 밖), "
            "`NONE`은 개입했으나 사다리가 미발동, 나머지는 발동한 등급이다. "
            "사다리가 *실제로 발동한 비율*은 이 필드의 분포로만 셀 수 있다 "
            '(CLAUDE.md "작동 신호 없는 알고리즘 부착 금지").'
        ),
    )
    hypotheses: list[MisconceptionHypothesis] = Field(
        description="턴 종료 시점 활성 가설 세트(호출자가 영속)."
    )
    evidence: list[EvidenceEdge] = Field(
        description="이 턴에 적재된 증거 엣지(호출자가 `evidence_links`로 영속)."
    )
    tool_calls: int = Field(description="총 도구 호출 횟수.")
    trace: list[ToolResult] = Field(description="도구 실행 트레이스(감사·디버그·학생 비노출).")


class ScriptedTutorPolicy:
    """결정론 정책 — 미리 정한 액션 시퀀스를 순서대로 방출(테스트·골격 데모용).

    LLM 정책의 *자리표시자*다. 시퀀스 소진 시 `EndTurnAction(격려)`을 방출해 루프를 안전 종료한다
    (단, verify 의무 미충족이면 하네스가 거부 → 예산 소진으로 종료).
    """

    def __init__(self, actions: Sequence[Action]) -> None:
        self._actions = list(actions)
        self._index = 0

    async def next_action(self, state: TurnState) -> Action:
        if self._index >= len(self._actions):
            return EndTurnAction(action_type="격려", utterance="좋아, 다음 단계로 가보자.")
        action = self._actions[self._index]
        self._index += 1
        return action


# ──────────────────────────────────────────────────────────────────────
# 도구 실행 (순수·작업 메모리 결선)
# ──────────────────────────────────────────────────────────────────────


def _turn_verdict(
    result: SolutionVerificationResult,
) -> Literal["correct", "incorrect", "unverifiable"]:
    """`verify_solution` 결과 → 턴 3-state(§3.1). incorrect 우선·검증 0이면 unverifiable."""
    if result.has_incorrect:
        return "incorrect"
    if result.n_correct == 0:  # 전이 없음 또는 전부 unverifiable
        return "unverifiable"
    return "correct"


def _count_verify_forms(result: SolutionVerificationResult) -> dict[str, int]:
    """전이별 *판정 경로 형태*(equation|mixed|expression) 개수 — 관측 전용(S3-51·희소 dict).

    왜 세는가: S3-02가 붙인 해집합 보존 판정이 실사용에서 **몇 번 작동했는지**를 3-state만으로는
    알 수 없다("등호 방정식을 해집합으로 판정한 correct"와 "표현식 동치 correct"가 같은 글자).
    자유사용 대표측정(S3-02 트리거 ③)의 사전등록 유효성 전제 V3가 이 축이라, 관측이 없으면
    사람이 자유사용 중에 손으로 세야 하고 그러면 "대본 금지"(자연 사용) 전제가 깨진다.

    판정 재구현 0 — `verify_step`이 이미 분기에서 정한 `form` 라벨을 세기만 한다. 형태 판별
    *전에* 회피한 전이(비대수 step_type·빈 입력)는 form이 None이라 어느 키에도 안 들어간다
    (값 합 <= n_transitions — 0으로 위장하지 않는 희소 회계·`unverifiable_by_reason` 선례).
    """
    counts: dict[str, int] = {}
    for step in result.steps:
        if step.form is None:
            continue
        counts[step.form.value] = counts.get(step.form.value, 0) + 1
    return counts


def _net_support(evidence: list[EvidenceEdge], misconception_id: str) -> float:
    """in-memory 증거 순지지도 = Σ polarity×(weight or 1.0) — `evidence_store.net_support` 동형."""
    return sum(
        (
            e.polarity * (e.weight if e.weight is not None else 1.0)
            for e in evidence
            if e.misconception_id == misconception_id
        ),
        0.0,
    )


def _refuted_mids(state: TurnState) -> frozenset[str]:
    """순지지도<0(반박 우세)인 오개념 집합 — `curate`의 반박 제거 입력(§2.2·§5.1)."""
    candidate_mids = {h.misconception_id for h in state.hypotheses}
    candidate_mids.update(m.misconception.id for m in state.last_matches)
    return frozenset(mid for mid in candidate_mids if _net_support(state.evidence, mid) < 0.0)


def _uses_explicit_utterance(state: TurnState, action: EndTurnAction) -> bool:
    """정책 명시 발화를 존중하는 턴인가 — `_end_turn_utterance` 분기의 단일 원천 술어.

    True = correct·검증 없는 순수 대화 턴에서 정책 자유 발화 노출(정답 노출 위험 0),
    False = 억제 턴(오답·막힘) 또는 발화 미지정 → 하네스 파생. 발화 출처(`UtteranceSource`)
    기록과 프로즈 계층(S4-04) 라우팅이 이 술어를 공유해 드리프트를 없앤다.
    """
    answer_suppressed = state.last_verdict in _ANSWER_SUPPRESSED_VERDICTS
    return action.utterance is not None and not answer_suppressed


def _end_turn_utterance(state: TurnState, action: EndTurnAction) -> str:
    """end_turn 발화 산출 — *유일한* 학생 노출(§3.4-3). 질문/힌트는 가설 세트 개입 발화로 결선.

    정답 억제 백스톱(§3.4·감사 Q6): 학생 풀이가 `correct`가 아닌 턴(`incorrect`·`unverifiable`)에선
    정책 명시 발화(`action.utterance`)를 *무시*하고 아래 파생 경로(소크라테스 개입·출제·중립)로만
    말한다 — 정책이 정답을 발화에 실어도 학생에게 닿지 못하게 하는 *하네스* 강제(정책 무관). 파생
    발화는 가설·직전 probe·중립 유도뿐이라 구조적으로 정답을 담지 않는다.
    """
    # correct·검증 없는 순수 대화 턴에서만 정책 명시 발화 존중 — 판정은 술어가 소유.
    if _uses_explicit_utterance(state, action) and action.utterance is not None:
        # 두 번째 조건은 술어가 이미 보장하는 값의 타입 내로잉용 재확인(중복 판정 아님).
        return action.utterance
    if action.action_type in ("질문", "힌트"):
        # 개입 발화 결선(#237) — 누적 가설 세트가 소크라테스 발화를 구동.
        decision = select_intervention_from_hypotheses(state.hypotheses)
        if decision is not None:
            # 반복 오류 사다리 등급을 작업 메모리에 남긴다(MISC-30 ⑥ 작동 비율의 원자료).
            # *발화에는 싣지 않는다* — 학생에게 반복 횟수를 말하지 않는다(정서적 낙인 금지).
            # 보류(None)일 때 덮어쓰지 않는 이유: 개입 자체가 없었던 턴은 사다리의 분모가
            # 아니다(미발동과 미관측을 섞으면 비율이 희석된다).
            state.escalation_rung = decision.escalation_rung
            return decision.prompt
        return NEUTRAL_GUIDE_UTTERANCE  # 보류 시 중립 유도
    if action.action_type == "출제" and state.last_probe is not None:
        return f"이 문항을 한번 풀어보자(진단 #{state.last_probe.problem_id})."
    return ENCOURAGE_FALLBACK_UTTERANCE  # 격려·출제 폴백


def _exec_end_turn(state: TurnState, action: EndTurnAction, *, explore_period: int) -> ToolResult:
    """end_turn 실행 — verify 의무 검사(§3.1) 후 발화·턴 종료. 거부 시 ok=False(루프 지속)."""
    # verify 의무(§3.1·§3.4-1) — 풀이 단계 제출 턴은 verify_step 호출이 의무(미호출 거부).
    if state.has_solution_steps and not state.verify_called:
        return ToolResult(
            kind=action.kind,
            ok=False,
            detail="end_turn 거부 — 풀이 단계 제출 턴인데 verify_step 미호출(§3.1).",
        )
    state.utterance = _end_turn_utterance(state, action)
    # 발화 출처 기록 — 산출 분기와 같은 술어를 공유(policy=명시 발화 존중·derived=하네스 파생).
    state.utterance_source = "policy" if _uses_explicit_utterance(state, action) else "derived"
    state.end_action_type = action.action_type
    state.ended = True
    return ToolResult(kind=action.kind, ok=True, detail=f"학생 발화 산출({action.action_type}).")


def _exec(state: TurnState, action: Action, *, explore_period: int) -> ToolResult:
    """단일 액션 실행 — 도구별 디스패치 + 불변식 강제. 상태를 in-place 갱신한다."""
    if isinstance(action, ReadStateAction):
        return ToolResult(
            kind=action.kind, ok=True, detail=f"노드 컨텍스트 {len(action.node_ids)}개 조회(기록)."
        )

    if isinstance(action, MatchMisconceptionAction):
        # diagnose(순수·substring) → 후보. 매칭은 *내부 동작*(학생 비노출·§3.4-3).
        state.last_matches = diagnose(action.student_text)
        return ToolResult(
            kind=action.kind, ok=True, detail=f"오개념 후보 {len(state.last_matches)}건(내부)."
        )

    if isinstance(action, CurateHypothesisAction):
        # 순수 curate — 감쇠·강화·임계 가지치기·반박(in-memory net_support<0)·최대5(재구현 0).
        state.hypotheses = curate(
            state.hypotheses,
            state.last_matches,
            turns_elapsed=action.turns_elapsed,
            refuted=_refuted_mids(state),
        )
        return ToolResult(
            kind=action.kind, ok=True, detail=f"활성 가설 {len(state.hypotheses)}건(내부)."
        )

    if isinstance(action, VerifyStepAction):
        verification = verify_solution(action.steps)
        verdict = _turn_verdict(verification)
        state.verify_called = True
        state.last_verdict = verdict
        return ToolResult(
            kind=action.kind,
            ok=True,
            detail=f"검증 {verdict}(내부).",
            verify_form_counts=_count_verify_forms(verification),
        )

    if isinstance(action, QueryCurriculumAction):
        return ToolResult(
            kind=action.kind, ok=True, detail=f"{action.relation} 노드 조회(기록·내부)."
        )

    if isinstance(action, SelectProbeAction):
        selection = plan_probe(
            action.candidates,
            state.hypotheses,
            action.outside_mids,
            theta=action.theta,
            turn_index=state.turn_index,
            administered=frozenset(action.administered),
            period=explore_period,
        )
        # ε-탐색 강제(§2.2 규칙2) — 탐색 턴인데 활성 세트 밖을 못 겨냥하면 거부.
        if is_exploration_turn(state.turn_index, period=explore_period) and (
            selection is None or not selection.is_exploration
        ):
            return ToolResult(
                kind=action.kind,
                ok=False,
                detail="probe 거부 — ε-탐색 턴인데 활성 세트 밖 미겨냥(§2.2 규칙2).",
            )
        if selection is None:
            return ToolResult(kind=action.kind, ok=False, detail="판별 문항 없음(억지 매칭 금지).")
        state.last_probe = selection
        return ToolResult(
            kind=action.kind,
            ok=True,
            detail=f"진단 문항 {selection.problem_id}(탐색={selection.is_exploration}·내부).",
        )

    if isinstance(action, LogEvidenceAction):
        # 증거 게이트(정확성 #1·거짓 낙인 차단·evidence_store 동형).
        if action.misconception_id not in CATALOG_BY_ID:
            return ToolResult(
                kind=action.kind,
                ok=False,
                detail="log_evidence 거부 — 미등록 오개념(카탈로그 부재).",
            )
        if action.polarity not in _VALID_POLARITY:
            return ToolResult(
                kind=action.kind,
                ok=False,
                detail=f"log_evidence 거부 — 극성 위반({action.polarity}).",
            )
        # crosswalk shadow(비노출·비차단) — 게이트 통과한 kebab-id의 M-id 매핑 coverage를
        # 로그로만 관측(state·ToolResult 불변). off(기본)면 조회 0이라 "순수·DB 무접근" 유지 —
        # shadow일 때만 never-break resolver를 touch(비차단·evidence_store 미러·remediation §1.3).
        if get_settings().misconception_crosslink_mode != "off":
            observe_crosslink_shadow(action.misconception_id)
        state.evidence.append(
            EvidenceEdge(
                misconception_id=action.misconception_id,
                polarity=action.polarity,
                weight=action.weight,
            )
        )
        return ToolResult(kind=action.kind, ok=True, detail="증거 적재(in-memory·내부).")

    # EndTurnAction
    return _exec_end_turn(state, action, explore_period=explore_period)


# ──────────────────────────────────────────────────────────────────────
# 턴 루프 드라이버
# ──────────────────────────────────────────────────────────────────────


async def run_tutoring_turn(
    *,
    policy: TutorPolicy,
    turn_index: int = 1,
    has_solution_steps: bool = False,
    initial_hypotheses: Sequence[MisconceptionHypothesis] = (),
    max_tool_calls: int = 16,
    explore_period: int = _EXPLORE_PERIOD,
) -> TurnOutcome:
    """WH-1 한 턴 루프 — 정책이 도구를 고르고 하네스가 실행·검증·기록한다(§3 골격·순수).

    종료 조건: ① `end_turn` 성공(학생 발화 산출·`ended`) ② 턴 예산(`max_tool_calls`) 소진
    (`budget_exhausted`·안전 종료·§5.2). 불변식(end_turn만 발화·verify 의무·ε-탐색·증거 게이트)은
    `_exec`가 강제한다. *순수·DB 무접근* — 작업 메모리는 `TurnState`에 in-memory로 들고(§2.1),
    영속은 호출자의 커밋 좌석(후속).

    `turn_index`(1-기반·세션 누적)는 ε-탐색 주기 판정에 쓰인다(§2.2). `has_solution_steps`는 이번
    턴 학생 입력에 풀이 단계가 있는지로, verify 의무(§3.1) 게이트의 입력이다. `initial_hypotheses`는
    직전 턴 스냅샷에서 복원한 활성 가설 세트다(웜 스타트·§2.2).
    """
    if max_tool_calls < 1:
        raise ValueError("max_tool_calls는 1 이상이어야 합니다.")
    state = TurnState(
        turn_index=turn_index,
        has_solution_steps=has_solution_steps,
        hypotheses=list(initial_hypotheses),
    )

    while state.tool_calls < max_tool_calls and not state.ended:
        action = await policy.next_action(state)
        result = _exec(state, action, explore_period=explore_period)
        state.tool_calls += 1
        state.history.append(result)

    if state.ended:
        return TurnOutcome(
            status="ended",
            action_type=state.end_action_type,
            utterance=state.utterance,
            utterance_source=state.utterance_source,
            escalation_rung=state.escalation_rung,
            hypotheses=state.hypotheses,
            evidence=list(state.evidence),
            tool_calls=state.tool_calls,
            trace=state.history,
        )
    return TurnOutcome(
        status="budget_exhausted",
        action_type=None,
        utterance=None,
        hypotheses=state.hypotheses,
        evidence=list(state.evidence),
        tool_calls=state.tool_calls,
        trace=state.history,
    )
