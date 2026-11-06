"""Phase 3 Release **Gate A 10단계 단일 관통** 하네스 — `P3-101`.

    진단 → 추천 → 학습 → 문제 → 답안 → 채점 → 오개념 → Hint/Tutor → Mastery Update → Next Recommendation

정의의 출처는 `docs/strategy/phase3_math_eos_completion_plan_source.md` §Gate A(D2 — 내부 테스트
계정)이고, 이 파일이 생긴 이유는 P3-17 통합 판정(`docs/reviews/p3_17_week3_release_judgment_2026-11-05.md`
· 판정 기준 main `036286a1`)이다. 그 회차는 10단계를 **한 번의 실행으로 재현할 수단이 없어** 조각
테스트 4개(3루프 · week3 코치 · 페르소나 학습 진입 · Gate D 이벤트)를 이어 붙여 읽어야 했다. 이 파일이
다음 판정 회차의 재현 수단이다 — 판정은 이 하네스의 exit code와 `GATE_A_CHAIN_VERDICT` 줄로 한다.

────────────────────────────────────────────────────────────────────────────
무엇을 재는가 (acceptance ①②)
────────────────────────────────────────────────────────────────────────────
- **학습자 1명 · 한 테스트 · 연속.** 데모 OAuth 콜백으로 로그인한 합성 학생(내부 테스트 계정)
  하나가 열 단계를 순서대로 밟는다. 단계 사이에 상태를 다시 만들지 않는다.
- **사람의 DB 수정 0.** 저작 콘텐츠(concept·problem·학습목표)는 로그인 *전*에 심고, 로그인 뒤에는
  봉인(`_Seal`)이 ORM 쓰기를 막는다. 학습자 상태는 전부 HTTP 부수효과다. DB **읽기**는 판정에
  허용된다(읽기는 "수정"이 아니다 — Week 1 하네스와 같은 규약).
- **단계 판정 = 그 단계의 산출물.** 응답 코드 200/201은 판정 근거가 아니다. 각 단계는 그 단계가
  남겨야 하는 이벤트·상태 행이 *이번에 새로* 생겼는지를 본다(아래 표). 응답 코드만 보면 "요청이
  받아들여졌다"는 알아도 "그 단계가 일어났다"는 모른다.

    단계               산출물(판정 근거)
    ①  진단            capture `written=True` + `learner_state.provisioned_by='diagnosis_capture'`
                       + 트레이스 `diagnostic_completed`
    ②  추천            트레이스 `recommendation_generated`가 새로 1건 이상, 추천 문항을 싣는다
    ③  학습            `evidence_event` 처치 행(응답 session_id·목표 id와 같은 행)
    ④  문제            서빙된 문항 본문 == 저작 행(`problem.question_text`) · 아직 미시도
    ⑤  답안            트레이스 `problem_attempted`가 그 시도 id·문항을 싣는다
    ⑥  채점            `problem_attempt` 행의 `is_correct`가 제출한 답의 판정과 같다
    ⑦  오개념          트레이스 `misconception_detected`가 기대 오개념으로 새로 생긴다
    ⑧  Hint/Tutor      트레이스 `hint_requested`(그 문항) + 코치 대화 턴 영속(학생·AI)
    ⑨  Mastery Update  `concept_mastery_history` 행이 ⑤의 시도 id를 가리킨다 + 트레이스
                       `mastery_updated`가 그 시도에 귀속된다
    ⑩  Next Rec.       ⑨ 뒤에 `recommendation_generated`가 새로 생기고 미시도 문항을 싣는다

────────────────────────────────────────────────────────────────────────────
끊긴 단계를 숨기지 않는다 (acceptance ③)
────────────────────────────────────────────────────────────────────────────
③ 학습은 지금 **404로 끝난다** — `/v1/me/objectives/{id}/study`가 진단 게이트(409)는 넘지만
`supply()`가 이 개념의 DSL을 못 찾는다(`PED-17` ① 소유 · 개념 콘텐츠 학생 공급은 KG-02 보류).
이 하네스는 그 단계를 `skip`하지 **않는다**. 관통은 끊긴 단계를 기록하고 다음 단계로 계속 가서
열 단계 전부의 도달 여부를 낸다(한 단계가 끊겼다고 뒤 단계를 미측정으로 두면 판정 회차가 다시
조각을 이어 읽어야 한다). 판정은 셋으로 나눈다:

  - `test_gate_a_chain_matches_frozen_reach` — 단계별 도달이 동결표 `_FROZEN_REACH`와 같은가.
    회귀(성립하던 단계가 끊김)와 해소 신호(끊긴 단계가 열림)를 갈라서 말한다.
  - `test_study_break_is_the_known_content_gap` — ③이 끊겼다면 그 사유가 **PED-17의 사유**인가.
    목표 부재 404(픽스처 결함)나 진단 게이트 409와 섞이면 "끊긴 단계"가 아니라 "판정 불가"다.
  - `test_release_gate_a_ten_steps_hold` — Gate A 문면 그대로 열 단계 전부. 동결표에 끊긴 단계가
    남아 있으면 `xfail(strict=True)`로 돈다(표에서 **유도** — 따로 적지 않는다). XFAIL은 실행된
    것이다: 본문이 끝까지 돌고 단언에서 실패한다. 해소되면 XPASS가 strict 실패로 바뀌어 동결표
    갱신을 강제한다.

**판정 밖** — AI 발화의 교수학적 품질·추천 품질은 보지 않는다(연결성과 산출물만). 실사용자 검증으로
계상하지 않는다(ARCH-66 ⑥ — 내부 테스트 계정 기준).

**채점 단계 단서(정직한 선언)** — ⑥이 보는 `POST /v1/me/attempts`는 `is_correct`를 **클라이언트
보고 그대로** 적재하는 v1 경로다(S3-32 · `api/me.py::submit_attempt` docstring). 서버가 직접 판정하는
경로는 코치 완료(`api/coach.py::_complete_problem` · 정답만 적재)뿐이라 오답 회차에는 쓸 수 없다.
P3-17 판정문은 이 경로를 Gate A의 "채점"으로 읽었고 이 하네스도 같은 기준을 쓴다 — 대신 증거 줄에
`채점원=클라이언트 보고`를 남겨 그 사실이 판정 근거에서 사라지지 않게 한다.

배선(acceptance ④): 이 파일은 `backend — 마이그레이션·통합 (실 PG)` 잡이 `pytest -m integration`
**마커로** 수집한다. 그 수집이 조용히 끊기지 않는지는 `tests/infra/test_gate_harness_marker_reach_wiring.py`
의 `GATE_HARNESS_PATHS`가 동결한다.
"""

from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import sys
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any, Final

import pytest

from whymath_backend.l2.learning_event_trace import TraceEventType
from whymath_backend.l2.next_problem_selection import MAX_ADMINISTERED_ITEMS

pytestmark = pytest.mark.integration


# ── 3루프 하네스의 검증된 조립기 재사용 (재구현 0) ─────────────────────────────────
# 경로 로딩인 이유는 그쪽 docstring과 같다(`--import-mode=importlib` — 형제 테스트 모듈이 이름으로
# 임포트되지 않는다). 3루프 하네스는 다시 페르소나 하네스(`_P`)를, 그것은 Week 1·2 하네스를 빌린다.
# 봉인(`_Seal`)은 3루프 쪽 `_P`와 그 아래 Week 2 모듈의 `_add_all`을 바꾸므로, 이 파일도 반드시
# **그 `_P`**(`_L._P`)로 시딩·관측해야 봉인이 같은 대상을 막는다.
_LOOPS_PATH = pathlib.Path(__file__).with_name("test_e2e_three_consecutive_loops.py")
#: 빌려 쓰는 3루프 헬퍼 — 하나라도 사라지면 수집 단계에서 이름을 지목하며 실패한다.
_LOOPS_HELPERS = ("_P", "_Seal", "_user_id", "_trace", "_mastery_row_attempt_ids")
#: 빌려 쓰는 페르소나 헬퍼(`_L._P`) — 같은 규약.
_PERSONA_HELPERS = (
    "_EXPECTED_MISCONCEPTION",
    "_UNMATCHED_WRONG_ANSWER",
    "_WRONG_ANSWER",
    "_attempt",
    "_begin",
    "_client",
    "_erase_learner",
    "_get",
    "_login",
    "_next_problem",
    "_provisioned_by",
    "_seed_concept",
    "_seed_objective",
    "_seed_problems",
    "_settings",
)


def _load_loops_harness() -> ModuleType:
    """3루프 하네스를 파일 경로로 적재하고 헬퍼 계약을 검사한다."""
    if not _LOOPS_PATH.exists():
        raise RuntimeError(
            f"연속 3루프 하네스가 없다: {_LOOPS_PATH}. 이 하네스는 그 조립기를 재사용한다 — "
            "파일이 옮겨졌으면 이 경로를 함께 고친다."
        )
    spec = importlib.util.spec_from_file_location("_gate_a_chain_loops_harness", _LOOPS_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"3루프 하네스 스펙 생성 실패: {_LOOPS_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    missing = [name for name in _LOOPS_HELPERS if not hasattr(module, name)]
    missing += [f"_P.{name}" for name in _PERSONA_HELPERS if not hasattr(module._P, name)]
    if missing:
        raise RuntimeError(
            f"재사용하는 헬퍼가 사라졌다: {missing}. 이 하네스가 그 조립기를 쓰므로 이름이 바뀌면 "
            "여기도 함께 고쳐야 한다."
        )
    return module


_L = _load_loops_harness()
_P = _L._P

#: Gate A 10단계 — 이름과 순서가 판정 계약이다(동결표·출력 줄이 이 순서를 따른다).
GATE_A_STEPS: Final[tuple[str, ...]] = (
    "진단",
    "추천",
    "학습",
    "문제",
    "답안",
    "채점",
    "오개념",
    "Hint/Tutor",
    "Mastery Update",
    "Next Recommendation",
)

#: 진단 문항 수 — 진단 확정은 문항 수 상한에서 선다(`EOS-126` 2차 중단 규칙). 정밀도(SE)로는 한
#: 자리에서 도달할 수 없으므로(페르소나 A 연장 docstring) 상한만큼 채점한다.
_DIAGNOSIS_ITEMS = MAX_ADMINISTERED_ITEMS
#: 진단 뒤에도 남겨 둘 미시도 문항 수 — ②·④·⑩이 *새* 문항을 받을 수 있어야 한다. 이 여유가 없으면
#: ⑩이 "후보 고갈"로 끊겨 다음 추천의 판정이 픽스처 결함과 구별되지 않는다.
_SPARE_ITEMS = 6
#: 문항 난이도 — 서로 다르게 둔다(추천은 θ 근방 최근접이라 같은 난이도면 결정론이 아니다).
#: 1~5 범위 강제(`ProblemSchema`). 0.1 간격 26개 = 2.0~4.5.
_DIFFICULTIES: Final[list[float]] = [
    round(2.0 + 0.1 * i, 2) for i in range(_DIAGNOSIS_ITEMS + _SPARE_ITEMS)
]

#: ⑧ 코치에게 보내는 발화 — 답을 요구하는 발화는 `hint_requested`를 낸다(Gate D 실세션 실측과 같은
#: 문장 · `tests/backend/scenarios/test_gate_d_event_role_census.py::_ANSWER_DEMAND`).
_HINT_DEMAND = "그냥 정답 알려줘"

#: ③ 학습이 끊긴 *알려진* 사유 — PED-17 ① 소유(개념 DSL 미적재 → `supply()` 404).
_STUDY_CONTENT_GAP_DETAIL = "이 개념의 학습 콘텐츠가 아직 준비되지 않았습니다."


# ── 판정 구조 ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Step:
    """한 단계의 도달 여부와 근거."""

    number: int
    name: str
    reached: bool
    evidence: str

    def line(self) -> str:
        mark = "REACHED" if self.reached else "BROKEN"
        return f"GATE_A_STEP[{self.number:>2}/{self.name}] {mark} :: {self.evidence}"


@dataclass
class _Chain:
    """10단계 관통 1회의 관측 — 판정은 테스트가 한다."""

    steps: list[_Step] = field(default_factory=list)
    #: ③ 학습 응답 — 끊김 사유 판정(`test_study_break_is_the_known_content_gap`)이 읽는다.
    study_status: int | None = None
    study_detail: Any = None
    #: 로그인 뒤 ORM 쓰기 시도 수 — 0이어야 "사람의 DB 수정 없이"가 선다.
    sealed_calls: int = 0
    #: 관통 전후 학습자 id — 같아야 "한 계정"이 선다.
    learner_before: str | None = None
    learner_after: str | None = None
    trace_truncated: bool = False

    def add(self, name: str, reached: bool, evidence: str) -> None:
        expected = GATE_A_STEPS[len(self.steps)]
        assert name == expected, f"단계 순서가 어긋났다: {name!r} 자리에 {expected!r}가 와야 한다."
        self.steps.append(_Step(len(self.steps) + 1, name, reached, evidence))

    def as_map(self) -> dict[str, bool]:
        return {s.name: s.reached for s in self.steps}

    def verdict_line(self) -> str:
        reached = sum(1 for s in self.steps if s.reached)
        broken = [s.name for s in self.steps if not s.reached]
        overall = "PASS" if not broken and len(self.steps) == len(GATE_A_STEPS) else "FAIL"
        owners = ",".join(f"{b}({_GAP_OWNERS.get(b, '소유자 미상')})" for b in broken) or "없음"
        return (
            f"GATE_A_CHAIN_VERDICT :: 도달={reached}/{len(GATE_A_STEPS)} · 끊김={owners} · "
            f"봉인위반={self.sealed_calls} · Gate A={overall}"
        )


# ── 단계 판정 규칙 (순수 — 관측값만 받는다. 절별 변별력은 아래 합성 테스트가 밟는다) ─────


def _entries(trace: dict[str, Any], event: TraceEventType) -> list[dict[str, Any]]:
    return [e for e in (trace.get("entries") or []) if e["event_type"] == event.value]


def _new_entries(
    before: dict[str, Any], after: dict[str, Any], event: TraceEventType
) -> list[dict[str, Any]]:
    """`after`에만 있는 행 — 이번 단계가 *새로* 남긴 산출물(이전 단계의 행으로 통과하지 않게).

    트레이스 행(`LearningEvent`)에는 고유 id가 없어 행 전체의 정렬 표현으로 식별한다(발생 시각·
    시도·문항이 함께 들어가므로 서로 다른 행이 같은 키가 되지 않는다). `event_id`는 합성 입력용이다.
    """

    def key(e: dict[str, Any]) -> str:
        return str(e.get("event_id") or sorted(e.items()))

    seen = {key(e) for e in _entries(before, event)}
    return [e for e in _entries(after, event) if key(e) not in seen]


def _judge_diagnosis(
    capture: dict[str, Any], provisioned_by: str | None, completed_events: int
) -> tuple[bool, str]:
    ok = (
        capture.get("written") is True
        and provisioned_by == "diagnosis_capture"
        and completed_events >= 1
    )
    return ok, (
        f"capture.written={capture.get('written')} · reason={capture.get('reason')} · "
        f"채점수={capture.get('administered_count')} · provisioned_by={provisioned_by} · "
        f"diagnostic_completed={completed_events}건"
    )


def _judge_recommendation(
    rec: dict[str, Any], new_events: list[dict[str, Any]]
) -> tuple[bool, str]:
    pid = rec.get("problem_id")
    carried = [e for e in new_events if pid is not None and e.get("problem_id") == str(pid)]
    ok = pid is not None and bool(carried)
    return ok, (
        f"action={rec.get('action')} · problem_id={'있음' if pid else '없음'} · "
        f"새 recommendation_generated={len(new_events)}건 · 그 문항을 실은 행={len(carried)}건"
    )


def _judge_study(
    status: int, body: Any, treatment_rows: list[tuple[str, str]], objective_id: str
) -> tuple[bool, str]:
    """`treatment_rows` = 이 학습 응답의 session_id로 찾은 `evidence_event` (objective_id, event_type)."""
    session_id = body.get("session_id") if isinstance(body, dict) else None
    matched = [r for r in treatment_rows if r[0] == objective_id]
    ok = session_id is not None and bool(matched)
    detail = body.get("detail") if isinstance(body, dict) else None
    return ok, (
        f"status={status} · session_id={'있음' if session_id else '없음'} · "
        f"처치 행(evidence_event)={len(matched)}건" + (f" · detail={detail}" if detail else "")
    )


def _judge_problem(
    served: dict[str, Any] | None, authored_text: str | None, attempted_before: bool
) -> tuple[bool, str]:
    served_text = (served or {}).get("question_text")
    ok = (
        served_text is not None
        and authored_text is not None
        and served_text == authored_text
        and not attempted_before
    )
    return ok, (
        f"서빙 본문==저작 행? {served_text == authored_text if served_text else '서빙 없음'} · "
        f"이미 시도한 문항? {attempted_before}"
    )


def _judge_answer(
    attempt_body: dict[str, Any], pid: str, new_attempted: list[dict[str, Any]]
) -> tuple[bool, str]:
    aid = str(attempt_body.get("attempt_id"))
    carried = [
        e for e in new_attempted if e.get("attempt_id") == aid and e.get("problem_id") == pid
    ]
    return (
        bool(carried),
        f"새 problem_attempted={len(new_attempted)}건 · 이 시도·문항을 실은 행={len(carried)}건",
    )


def _judge_grading(row_is_correct: bool | None, submitted_correct: bool) -> tuple[bool, str]:
    ok = row_is_correct is not None and row_is_correct is submitted_correct
    return ok, (
        f"problem_attempt.is_correct={row_is_correct} · 제출 판정={submitted_correct} · "
        "채점원=클라이언트 보고(S3-32 v1 경로)"
    )


def _judge_misconception(new_detected: list[dict[str, Any]], expected: str) -> tuple[bool, str]:
    ids = sorted({str(e.get("misconception_id")) for e in new_detected})
    return (
        expected in ids,
        f"새 misconception_detected={len(new_detected)}건 · id={ids} · 기대={expected}",
    )


def _judge_tutor(
    new_hints: list[dict[str, Any]], pid: str, turn_roles: list[str]
) -> tuple[bool, str]:
    on_problem = [e for e in new_hints if e.get("problem_id") == pid]
    # 역할은 `TurnRole` 3종(student·assistant·system). system은 AI 응답이 아니다.
    has_ai = "assistant" in turn_roles
    has_student = "student" in turn_roles
    ok = bool(on_problem) and has_ai and has_student
    return ok, (
        f"새 hint_requested={len(new_hints)}건(그 문항 {len(on_problem)}건) · "
        f"대화 턴={len(turn_roles)}개 · 역할={sorted(set(turn_roles))}"
    )


def _judge_mastery(
    history_attempt_ids: list[str | None], new_updates: list[dict[str, Any]], aid: str
) -> tuple[bool, str]:
    in_history = history_attempt_ids.count(aid)
    attributed = [e for e in new_updates if e.get("attempt_id") == aid]
    ok = in_history >= 1 and bool(attributed)
    changes = [e.get("mastery_change") for e in attributed]
    return ok, (
        f"concept_mastery_history 중 이 시도 행={in_history}건 · "
        f"이 시도에 귀속된 mastery_updated={len(attributed)}건 · 변화={changes}"
    )


def _judge_next_recommendation(
    rec: dict[str, Any], new_events: list[dict[str, Any]], attempted: set[str]
) -> tuple[bool, str]:
    pid = rec.get("problem_id")
    pid_s = None if pid is None else str(pid)
    carried = [e for e in new_events if pid_s is not None and e.get("problem_id") == pid_s]
    fresh = pid_s is not None and pid_s not in attempted
    ok = bool(carried) and fresh
    return ok, (
        f"action={rec.get('action')} · reason={(rec.get('reason') or {}).get('type')} · "
        f"새 recommendation_generated={len(new_events)}건(그 문항 {len(carried)}건) · 미시도 문항? {fresh}"
    )


# ── 관측 헬퍼 (읽기 전용 — 쓰기 0) ────────────────────────────────────────────────


def _read_rows(sql: str, params: dict[str, Any]) -> list[tuple[Any, ...]]:
    """읽기 전용 SELECT 1회 — 공개 표면이 내지 않는 산출물(행 자체)을 본다."""

    async def _read() -> list[tuple[Any, ...]]:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(_P._settings().database_url)
        try:
            async with engine.begin() as conn:
                return [tuple(r) for r in (await conn.execute(text(sql), params)).all()]
        finally:
            await engine.dispose()

    return asyncio.run(_read())


def _delete_study_rows(session_ids: list[str]) -> None:
    """③이 열린 회차가 남긴 처치 행 정리 — `evidence_event`는 학습자 키가 없어(가명화)
    `DELETE /v1/me`가 지우지 못한다. 저작 콘텐츠 정리와 같은 teardown 범주다(학습 *도중* 쓰기 아님)."""
    if not session_ids:
        return

    async def _drop() -> None:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(_P._settings().database_url)
        try:
            async with engine.begin() as conn:
                for sid in session_ids:
                    await conn.execute(
                        text("DELETE FROM evidence_event WHERE session_id = :sid"), {"sid": sid}
                    )
        finally:
            await engine.dispose()

    asyncio.run(_drop())


# ── 관통 ──────────────────────────────────────────────────────────────────────


def _run_chain() -> _Chain:
    """학습자 1명이 Gate A 10단계를 한 번에 밟는다 — 끊긴 단계가 있어도 끝까지 간다."""
    content, _journal = _P._begin("GATE-A")
    chain = _Chain()
    study_sessions: list[str] = []
    try:
        # 저작 콘텐츠 시딩 — 로그인 *전*에 끝낸다(그 뒤로는 봉인).
        cid, code = _P._seed_concept(content, "ga", "완전제곱식의 전개")
        pids = {str(p) for p in _P._seed_problems(content, cid, "ga", _DIFFICULTIES)}
        objective_id = _P._seed_objective(content, code)
        attempted: set[str] = set()

        with _P._client() as client:
            _P._erase_learner(client)  # 기준선 = 신규 학습자(지난 회차 잔여 제거)
            auth = _P._login(client)
            chain.learner_before = _L._user_id(client, auth)

            def trace() -> dict[str, Any]:
                return _L._trace(client, auth)

            with _L._Seal() as seal:
                # ── ① 진단 — 추천을 따라 상한만큼 채점 → 확정 ─────────────────────────
                # 오답은 오개념 서명이 잡히지 않는 답으로 낸다 — ⑦이 *그 단계에서 새로* 생긴 탐지를
                # 보려면 그 전에 오개념이 관측되면 안 된다.
                for index in range(_DIAGNOSIS_ITEMS):
                    rec = _P._next_problem(client, auth)
                    pid = rec["problem_id"]
                    assert pid is not None and str(pid) in pids, (
                        f"진단 {index + 1}번째 추천이 이 회차가 심은 문항이 아니다({pid}) — 격리 실패. "
                        "판정 불가이지 통과가 아니다."
                    )
                    # 절반만 맞힌다 — 2/3 정답이면 숙달이 상한(1.0)에 포화돼 ⑤의 오답이 ⑨ 증거에서
                    # `1.0 → 1.0`으로 보인다(2026-11-05 첫 실행 실측). 갱신은 났지만 값이 움직였는지
                    # 사람이 읽을 수 없으면 근거로서 약하다.
                    correct = index % 2 == 1
                    _P._attempt(
                        client,
                        auth,
                        uuid.UUID(str(pid)),
                        correct=correct,
                        answer="정답" if correct else _P._UNMATCHED_WRONG_ANSWER,
                    )
                    attempted.add(str(pid))
                capture_resp = client.post("/v1/me/assessments/capture", headers=auth)
                capture = capture_resp.json() if capture_resp.status_code == 200 else {}
                t1 = trace()
                chain.add(
                    "진단",
                    *_judge_diagnosis(
                        capture,
                        _P._provisioned_by(client, auth),
                        len(_entries(t1, TraceEventType.DIAGNOSTIC_COMPLETED)),
                    ),
                )

                # ── ② 추천 ────────────────────────────────────────────────────────────
                rec2 = _P._next_problem(client, auth)
                t2 = trace()
                chain.add(
                    "추천",
                    *_judge_recommendation(
                        rec2, _new_entries(t1, t2, TraceEventType.RECOMMENDATION_GENERATED)
                    ),
                )

                # ── ③ 학습 — 끊겨도 기록하고 계속 간다(skip 금지 · acceptance ③) ─────────
                study = client.post(f"/v1/me/objectives/{objective_id}/study", headers=auth)
                chain.study_status = study.status_code
                try:
                    study_body: Any = study.json()
                except ValueError:
                    study_body = None
                chain.study_detail = (
                    study_body.get("detail") if isinstance(study_body, dict) else study_body
                )
                session_id = study_body.get("session_id") if isinstance(study_body, dict) else None
                treatment_rows: list[tuple[str, str]] = []
                if session_id:
                    study_sessions.append(str(session_id))
                    treatment_rows = [
                        (str(r[0]), str(r[1]))
                        for r in _read_rows(
                            "SELECT objective_id, event_type FROM evidence_event "
                            "WHERE session_id = :sid",
                            {"sid": str(session_id)},
                        )
                    ]
                chain.add(
                    "학습",
                    *_judge_study(study.status_code, study_body, treatment_rows, objective_id),
                )

                # ── ④ 문제 — ②가 준 문항을 받아 본다 ───────────────────────────────────
                pid4 = None if rec2.get("problem_id") is None else str(rec2["problem_id"])
                served: dict[str, Any] | None = None
                authored: str | None = None
                if pid4 is not None:
                    got = client.get(f"/v1/problems/{pid4}", headers=auth)
                    served = got.json() if got.status_code == 200 else None
                    rows = _read_rows(
                        "SELECT question_text FROM problem WHERE problem_id = :pid", {"pid": pid4}
                    )
                    authored = str(rows[0][0]) if rows else None
                chain.add("문제", *_judge_problem(served, authored, pid4 in attempted))
                assert (
                    pid4 is not None
                ), "② 추천이 문항을 주지 않아 ④~⑨를 밟을 문항이 없다 — 위 단계 줄이 끊긴 지점이다."

                # ── ⑤ 답안 — 오개념을 인스턴스화하는 오답 제출 ─────────────────────────
                attempt = _P._attempt(
                    client, auth, uuid.UUID(pid4), correct=False, answer=_P._WRONG_ANSWER
                )
                aid = str(attempt["attempt_id"])
                attempted.add(pid4)
                t5 = trace()
                chain.add(
                    "답안",
                    *_judge_answer(
                        attempt, pid4, _new_entries(t2, t5, TraceEventType.PROBLEM_ATTEMPTED)
                    ),
                )

                # ── ⑥ 채점 — 적재된 시도 행의 판정 ───────────────────────────────────
                graded = _read_rows(
                    "SELECT is_correct FROM problem_attempt WHERE attempt_id = :aid", {"aid": aid}
                )
                chain.add(
                    "채점",
                    *_judge_grading(None if not graded else bool(graded[0][0]), False),
                )

                # ── ⑦ 오개념 ───────────────────────────────────────────────────────────
                chain.add(
                    "오개념",
                    *_judge_misconception(
                        _new_entries(t2, t5, TraceEventType.MISCONCEPTION_DETECTED),
                        _P._EXPECTED_MISCONCEPTION,
                    ),
                )

                # ── ⑧ Hint/Tutor — 방금 틀린 문항으로 코치 대화 ────────────────────────
                opened = client.post(
                    "/v1/coach/sessions",
                    headers=auth,
                    json={"student_input": _HINT_DEMAND, "problem_id": pid4},
                )
                roles: list[str] = []
                if opened.status_code == 201:
                    did = opened.json()["dialogue_id"]
                    got = client.get(f"/v1/coach/sessions/{did}", headers=auth)
                    if got.status_code == 200:
                        roles = [str(t.get("role")) for t in got.json().get("turns") or []]
                t8 = trace()
                chain.add(
                    "Hint/Tutor",
                    *_judge_tutor(_new_entries(t5, t8, TraceEventType.HINT_REQUESTED), pid4, roles),
                )

                # ── ⑨ Mastery Update — ⑤의 시도가 숙달 시계열에 귀속됐는가 ──────────────
                learner = _L._user_id(client, auth)
                chain.add(
                    "Mastery Update",
                    *_judge_mastery(
                        _L._mastery_row_attempt_ids(learner),
                        _new_entries(t2, t8, TraceEventType.MASTERY_UPDATED),
                        aid,
                    ),
                )

                # ── ⑩ Next Recommendation ───────────────────────────────────────────────
                rec10 = _P._next_problem(client, auth)
                t10 = trace()
                chain.add(
                    "Next Recommendation",
                    *_judge_next_recommendation(
                        rec10,
                        _new_entries(t8, t10, TraceEventType.RECOMMENDATION_GENERATED),
                        attempted,
                    ),
                )
                chain.trace_truncated = bool(t10.get("truncated"))

            chain.sealed_calls = seal.blocked
            chain.learner_after = _L._user_id(client, auth)
        return chain
    finally:
        try:
            _delete_study_rows(study_sessions)
        finally:
            content.teardown()


def _dump(chain: _Chain) -> None:
    """판정 근거 — 판정은 exit code가, *어디서 끊겼는지*는 이 줄들이 말한다."""
    print("\n=== Release Gate A — 10단계 단일 관통 (내부 테스트 계정) ===")
    for step in chain.steps:
        print(step.line())
    print(chain.verdict_line())


@pytest.fixture(scope="module")
def chain() -> Iterator[_Chain]:
    """10단계 관통 1회 — 아래 판정 테스트들이 같은 관통을 본다(재실행 0)."""
    result = _run_chain()
    _dump(result)
    yield result


# ── 동결표 — 현행 도달 여부 (판정 기준 main `036286a1` + P3-17 판정문 Gate A) ─────────

#: 단계별 도달 동결값. 끊긴 단계는 **소유 태스크가 있어야** 한다(`_GAP_OWNERS`).
_FROZEN_REACH: Final[dict[str, bool]] = {name: name != "학습" for name in GATE_A_STEPS}

#: 동결된 끊김의 소유자 — 해소 신호가 날 때 메시지가 가리킬 곳.
_GAP_OWNERS: Final[dict[str, str]] = {"학습": "PED-17"}


def _open_steps() -> set[str]:
    """동결표에서 False인 단계 — Gate A 문면 테스트의 xfail 대상(표에서 유도)."""
    return {name for name, ok in _FROZEN_REACH.items() if not ok}


# ── 관통 판정 ───────────────────────────────────────────────────────────────────


def test_gate_a_chain_is_one_operator_free_learner(chain: _Chain) -> None:
    """한 계정 · 사람의 DB 수정 0 · 열 단계 전부 관측 — 이 셋이 서야 아래 판정이 의미를 갖는다."""
    assert [s.name for s in chain.steps] == list(GATE_A_STEPS), (
        "관통이 열 단계를 다 관측하지 못했다 — 중간에 멈춘 단계 뒤는 미측정이다(판정 불가): "
        f"{[s.name for s in chain.steps]}"
    )
    assert (
        chain.sealed_calls == 0
    ), f"로그인 뒤 ORM 쓰기 시도 {chain.sealed_calls}건 — Gate A '사람의 DB 수정 없이' 위반."
    assert (
        chain.learner_before and chain.learner_before == chain.learner_after
    ), f"관통 도중 학습자가 바뀌었다: {chain.learner_before} → {chain.learner_after} — 한 계정이 아니다."
    assert chain.trace_truncated is False, "잘린 트레이스로 단계 산출물을 판정하지 않는다."


def test_gate_a_chain_matches_frozen_reach(chain: _Chain) -> None:
    """단계별 도달이 동결표와 같은가 — 달라지면 회귀인지 해소인지 갈라서 말한다."""
    observed = chain.as_map()
    assert (
        observed.keys() == _FROZEN_REACH.keys()
    ), f"단계 구성이 동결표와 다르다: {sorted(observed)} vs {sorted(_FROZEN_REACH)}"
    evidence = "\n" + "\n".join(s.line() for s in chain.steps) + "\n" + chain.verdict_line()
    regressed = [n for n, was in _FROZEN_REACH.items() if was and not observed[n]]
    improved = [
        f"'{n}'(소유자: {_GAP_OWNERS.get(n, '소유자 미상')})"
        for n, was in _FROZEN_REACH.items()
        if observed[n] and not was
    ]
    assert not regressed, "회귀 — 성립하던 단계가 끊겼다: " + " · ".join(regressed) + evidence
    assert not improved, (
        "해소 신호 — 끊겨 있던 단계가 열렸다. `_FROZEN_REACH`를 True로 올리고 `_GAP_OWNERS`에서 "
        "지운다(문면 테스트의 xfail은 표에서 유도되므로 자동으로 풀린다): "
        + " · ".join(improved)
        + evidence
    )


def test_study_break_is_the_known_content_gap(chain: _Chain) -> None:
    """③이 끊겼다면 사유가 PED-17의 사유(콘텐츠 미적재 404)여야 한다 — 다른 404·409는 판정 불가.

    목표 부재 404는 픽스처 결함이고(진단 게이트보다 *앞서* 막는다), 409는 진단이 확정되지 않은
    것이다. 둘 다 "학습이 끊겼다"가 아니라 "학습을 판정하지 못했다"이므로 같은 칸에 두면 안 된다.
    ③이 열렸으면(201) 이 테스트는 할 일이 없다 — 동결표 테스트가 해소 신호를 낸다.
    """
    study = next(s for s in chain.steps if s.name == "학습")
    if study.reached:
        return
    assert chain.study_status == 404 and chain.study_detail == _STUDY_CONTENT_GAP_DETAIL, (
        f"학습 단계가 PED-17의 사유가 아닌 이유로 끊겼다: status={chain.study_status} · "
        f"detail={chain.study_detail!r}. 409면 ① 진단 확정이 학습 게이트에 닿지 않은 것이고, "
        "'학습목표를 찾을 수 없습니다' 계열 404면 픽스처가 목표 행을 심지 못한 것이다."
    )


def test_release_gate_a_ten_steps_hold(chain: _Chain, request: pytest.FixtureRequest) -> None:
    """Gate A 문면 그대로: 열 단계 전부 도달. 동결표에 끊긴 단계가 남으면 `xfail(strict=True)`."""
    if _open_steps():
        request.applymarker(
            pytest.mark.xfail(
                strict=True,
                reason=(
                    f"Release Gate A 미충족 — 동결표 `_FROZEN_REACH`에 끊긴 단계 {sorted(_open_steps())} "
                    f"(소유: {_GAP_OWNERS}). 해소되면 XPASS가 strict 실패로 바뀐다 — 표를 올리면 이 "
                    "표식은 자동으로 풀린다."
                ),
            )
        )
    broken = [f"{s.name} ({s.evidence})" for s in chain.steps if not s.reached]
    assert not broken, "끊긴 단계: " + " · ".join(broken) + "\n" + chain.verdict_line()


# ── 동결표 자체의 계약 ───────────────────────────────────────────────────────────


def test_every_frozen_break_has_an_owner() -> None:
    """끊긴 단계마다 소유 태스크가 있고, 소유자 표에 열린 단계가 아닌 항목이 없다."""
    assert (
        set(_GAP_OWNERS) == _open_steps()
    ), f"끊김 소유자 표가 동결표와 어긋난다: 소유자 {sorted(_GAP_OWNERS)} vs 끊김 {sorted(_open_steps())}"


def test_open_steps_snapshot() -> None:
    """2026-11-05(판정 기준 main `036286a1`) — 끊긴 단계는 학습 하나. 바뀌면 판정문과 함께 고친다."""
    assert _open_steps() == {"학습"}


# ── 판정 규칙의 절별 변별력 — 관통 데이터가 밟지 않는 절을 합성 입력으로 밟는다 ──────────

_PID = "p-1"
_AID = "a-1"


def _ev(event: TraceEventType, **fields: Any) -> dict[str, Any]:
    return {"event_type": event.value, **fields}


@pytest.mark.parametrize(
    ("capture", "provisioned", "completed", "ok"),
    [
        ({"written": True}, "diagnosis_capture", 1, True),
        ({"written": False}, "diagnosis_capture", 1, False),  # 확정 안 됨
        ({"written": True}, None, 1, False),  # 학습자 상태 행 없음
        ({"written": True}, "attempt_lazy", 1, False),  # 진단 아닌 사유로 생긴 행
        ({"written": True}, "diagnosis_capture", 0, False),  # 이벤트 미기록
    ],
)
def test_judge_diagnosis_requires_every_artifact(
    capture: dict[str, Any], provisioned: str | None, completed: int, ok: bool
) -> None:
    assert _judge_diagnosis(capture, provisioned, completed)[0] is ok


@pytest.mark.parametrize(
    ("rec", "events", "ok"),
    [
        ({"problem_id": _PID}, [{"problem_id": _PID}], True),
        ({"problem_id": None}, [{"problem_id": _PID}], False),  # 문항 없는 추천
        ({"problem_id": _PID}, [], False),  # 응답은 왔는데 이벤트 없음(응답 코드만으로 통과 금지)
        ({"problem_id": _PID}, [{"problem_id": "other"}], False),  # 다른 문항의 이벤트
    ],
)
def test_judge_recommendation_requires_event_for_that_problem(
    rec: dict[str, Any], events: list[dict[str, Any]], ok: bool
) -> None:
    assert _judge_recommendation(rec, events)[0] is ok


@pytest.mark.parametrize(
    ("status", "body", "rows", "ok"),
    [
        (201, {"session_id": "s"}, [("OBJ", "treatment")], True),
        (201, {"session_id": "s"}, [], False),  # 201인데 처치 행이 없다
        (201, {"session_id": "s"}, [("OTHER", "treatment")], False),  # 다른 목표의 행
        (404, {"detail": _STUDY_CONTENT_GAP_DETAIL}, [], False),  # 현행(PED-17)
    ],
)
def test_judge_study_requires_treatment_row(
    status: int, body: Any, rows: list[tuple[str, str]], ok: bool
) -> None:
    assert _judge_study(status, body, rows, "OBJ")[0] is ok


@pytest.mark.parametrize(
    ("served", "authored", "attempted", "ok"),
    [
        ({"question_text": "Q"}, "Q", False, True),
        (None, "Q", False, False),  # 서빙 실패
        ({"question_text": "Q2"}, "Q", False, False),  # 저작 행과 다른 본문
        ({"question_text": "Q"}, "Q", True, False),  # 이미 푼 문항(새 문제 아님)
    ],
)
def test_judge_problem_compares_against_authored_row(
    served: dict[str, Any] | None, authored: str | None, attempted: bool, ok: bool
) -> None:
    assert _judge_problem(served, authored, attempted)[0] is ok


@pytest.mark.parametrize(
    ("events", "ok"),
    [
        ([{"attempt_id": _AID, "problem_id": _PID}], True),
        ([], False),
        ([{"attempt_id": "other", "problem_id": _PID}], False),  # 다른 시도
        ([{"attempt_id": _AID, "problem_id": "other"}], False),  # 다른 문항
    ],
)
def test_judge_answer_requires_this_attempt(events: list[dict[str, Any]], ok: bool) -> None:
    assert _judge_answer({"attempt_id": _AID}, _PID, events)[0] is ok


@pytest.mark.parametrize(
    ("row", "submitted", "ok"),
    [(False, False, True), (None, False, False), (True, False, False), (True, True, True)],
)
def test_judge_grading_requires_matching_row(row: bool | None, submitted: bool, ok: bool) -> None:
    assert _judge_grading(row, submitted)[0] is ok


def test_judge_grading_names_the_grading_source() -> None:
    """채점원이 클라이언트 보고라는 단서가 증거 줄에서 사라지지 않는다(정직한 선언)."""
    assert "클라이언트 보고" in _judge_grading(False, False)[1]


@pytest.mark.parametrize(
    ("events", "ok"),
    [
        ([{"misconception_id": "m"}], True),
        ([], False),
        ([{"misconception_id": "other"}], False),
    ],
)
def test_judge_misconception_requires_expected_id(events: list[dict[str, Any]], ok: bool) -> None:
    assert _judge_misconception(events, "m")[0] is ok


@pytest.mark.parametrize(
    ("hints", "roles", "ok"),
    [
        ([{"problem_id": _PID}], ["student", "assistant"], True),
        ([], ["student", "assistant"], False),  # 힌트 이벤트 없음
        ([{"problem_id": "other"}], ["student", "assistant"], False),  # 다른 문항
        ([{"problem_id": _PID}], ["student"], False),  # AI 턴이 영속되지 않음
        ([{"problem_id": _PID}], ["student", "system"], False),  # 시스템 메시지는 AI 응답이 아님
        ([{"problem_id": _PID}], [], False),  # 대화 자체가 없음
    ],
)
def test_judge_tutor_requires_hint_event_and_both_turns(
    hints: list[dict[str, Any]], roles: list[str], ok: bool
) -> None:
    assert _judge_tutor(hints, _PID, roles)[0] is ok


@pytest.mark.parametrize(
    ("history", "updates", "ok"),
    [
        ([_AID], [{"attempt_id": _AID, "mastery_change": -0.1}], True),
        ([], [{"attempt_id": _AID}], False),  # 시계열 행 없음
        ([_AID], [], False),  # 트레이스 귀속 없음
        (["other", None], [{"attempt_id": "other"}], False),  # 다른 시도의 갱신
    ],
)
def test_judge_mastery_requires_attribution_to_this_attempt(
    history: list[str | None], updates: list[dict[str, Any]], ok: bool
) -> None:
    assert _judge_mastery(history, updates, _AID)[0] is ok


@pytest.mark.parametrize(
    ("rec", "events", "attempted", "ok"),
    [
        ({"problem_id": "p-2"}, [{"problem_id": "p-2"}], {_PID}, True),
        ({"problem_id": _PID}, [{"problem_id": _PID}], {_PID}, False),  # 이미 푼 문항
        ({"problem_id": "p-2"}, [], {_PID}, False),  # ⑨ 뒤 새 이벤트 없음
        ({"problem_id": None}, [], {_PID}, False),  # 후보 없음
    ],
)
def test_judge_next_recommendation_requires_fresh_problem_and_new_event(
    rec: dict[str, Any], events: list[dict[str, Any]], attempted: set[str], ok: bool
) -> None:
    assert _judge_next_recommendation(rec, events, attempted)[0] is ok


def test_new_entries_excludes_rows_from_earlier_steps() -> None:
    """이전 단계의 행으로 이번 단계가 통과하지 않는다 — `_new_entries`가 차집합을 낸다."""
    old = _ev(TraceEventType.RECOMMENDATION_GENERATED, event_id="1", problem_id=_PID)
    new = _ev(TraceEventType.RECOMMENDATION_GENERATED, event_id="2", problem_id=_PID)
    other = _ev(TraceEventType.MASTERY_UPDATED, event_id="3")
    before = {"entries": [old]}
    after = {"entries": [old, new, other]}
    assert _new_entries(before, after, TraceEventType.RECOMMENDATION_GENERATED) == [new]
    assert _new_entries(after, after, TraceEventType.RECOMMENDATION_GENERATED) == []


def test_chain_rejects_out_of_order_steps() -> None:
    """단계 순서가 계약이다 — 순서를 바꿔 기록하면 즉시 실패한다."""
    c = _Chain()
    c.add("진단", True, "")
    with pytest.raises(AssertionError, match="순서"):
        c.add("학습", True, "")


def test_verdict_line_reports_every_break_with_owner() -> None:
    """출력 끝 판정 줄이 끊긴 단계와 그 소유자를 말한다(acceptance ②)."""
    c = _Chain()
    for name in GATE_A_STEPS:
        c.add(name, name != "학습", "")
    line = c.verdict_line()
    assert "도달=9/10" in line and "학습(PED-17)" in line and "Gate A=FAIL" in line
    full = _Chain()
    for name in GATE_A_STEPS:
        full.add(name, True, "")
    assert "Gate A=PASS" in full.verdict_line()
