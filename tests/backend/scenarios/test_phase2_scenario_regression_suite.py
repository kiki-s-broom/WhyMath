"""계획서 300 Phase 2 §16 **시나리오 회귀 스위트** — SCENARIO-001~010 (EOS-119 · 집행 지시 P-13).

단위 테스트가 아니라 **상태 변화 시나리오**다. 학생 한 명이 공개 HTTP 표면만으로 한 장면을 지나가고,
그 장면 전후의 *구조화된 상태*를 단언한다 — 화면 문자열이 아니라 `LearnerState`(숙달 값·활성 오개념),
학습 상태 머신(`/v1/me/learning-state`의 현재 상태·전이 이력), 오개념 가설 confidence, 추천의
`reason`/`action`/`target_concept`, 그리고 학습 이벤트 시간선(`/v1/me/learning-trace`) 레코드다.

    001 신규 학생 정상 학습      002 낮은 진단점수          003 선수개념 결손
    004 동일 오개념 반복         005 힌트 후 정답           006 AI Tutor 질문
    007 mastery threshold 통과   008 다음 concept 이동      009 세션 종료 후 재접속
    010 학습 상태 복구

**시딩 경계(Week 1·2·3 게이트 · 페르소나 하네스와 같다)** — *학습자 상태*는 단 한 줄도 직접 쓰지
않는다(전부 HTTP 부수효과). *저작 콘텐츠*(concept·atom_node·concept_edge·problem·problem_concept·
skill_node)만 ORM으로 심는다. 읽기 전용 SELECT는 공개 표면이 그 값을 내지 않을 때만 쓴다(읽기는
"DB 직접 수정"이 아니다). 이 규율은 `test_scenario_suite_guard.py`가 AST로 기계 집행한다.

**헬퍼 재사용(재구현 0)** — 로그인(운영 OAuth 콜백 경로)·삭제권 정리·저작 콘텐츠 조립·관측 헬퍼는
페르소나 하네스(`test_e2e_persona_journeys.py`)를 경로 로딩으로 빌려 쓰고, 그쪽은 다시 Week 2·Week 1
하네스를 빌린다. 이름이 바뀌면 여기는 조용히 통과하지 않고 수집 단계에서 이름을 지목하며 깨진다.

**정직한 공백 동결** — 현행 코드로 성립하지 않는 마디는 `skip`으로 위장하지 않는다. *현행 동작*을
단언하고, 고쳐지면 그 단언이 실패하며 메시지가 소유 태스크를 가리킨다.
  - SCENARIO-003 ⓐ `EOS-127` — 상태 머신 R4(선수결손)는 서빙 경로에서 발화하지 않는다.
  - SCENARIO-005 ⓐ 힌트 사용이 그 뒤의 정답 attempt에 귀속되지 않는다(`used_hint` NULL ·
    `hint_usage` 0행) — `EOS-133-coach-hint-usage-attribution`.
  - SCENARIO-005 ⓑ 코치 완료 경로는 학습 상태 머신을 돌리지 않는다 — `EOS-134-coach-completion-state-machine`.
  - (해소) SCENARIO-008 ⓐ `EOS-124` — 추천의 정책 축(action)과 선택 축(problem_id·target) 불일치.
    기본 CAT이 설명을 전달 문항에 정렬하면서 해소돼 올바른 값 단언(전진 = 다음 개념 문항)으로
    승격했다. 같은 변경으로 002·007의 근거 단언도 "그래프 근거가 있을 때만 관계 행위"로 정밀화됐다.
  - (해소) SCENARIO-009 ⓐ `LearningSession` writer 0 — `EOS-131`이 서버 30분 유휴 규칙 writer를
    신설해 정상 동작 단언(재접속이 같은 학습 세션으로 이어진다)으로 승격했다.

대조표·실행 시간·회귀 주입 결과 = `docs/reviews/eos119_scenario_suite_2026-09-24.md`.
회귀 주입 하네스 = `scripts/ops/verify_scenario_suite_discrimination.py`.
"""

from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import sys
import uuid
from types import ModuleType
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from whymath_backend.api._rate_limit import reset_store
from whymath_backend.db.models.problem import Problem
from whymath_backend.l2.next_problem_selection import MAX_ADMINISTERED_ITEMS
from whymath_backend.l2.recommendation_contract import (
    PREREQUISITE_MASTERY_CEILING,
    WEAK_CONCEPT_MASTERY_CEILING,
)
from whymath_backend.schema.enums import Curriculum, ReviewStatus, SourceType, Subject
from whymath_backend.schema.learning_state import REPEATED_FAILURE_THRESHOLD
from whymath_backend.schema.problem import Problem as ProblemSchema

pytestmark = pytest.mark.integration


# ── 페르소나 하네스의 검증된 조립기 재사용 (재구현 0) ────────────────────────────────
# 경로 로딩인 이유는 그쪽 docstring과 같다 — 이 저장소의 pytest는 `--import-mode=importlib`이라
# 형제 테스트 모듈이 이름으로 임포트되지 않는다.
_PERSONA_PATH = pathlib.Path(__file__).resolve().parents[1] / "api" / "test_e2e_persona_journeys.py"
#: 빌려 쓰는 헬퍼 계약 — 하나라도 사라지면 수집 단계에서 실패한다(조용한 표류 방지).
_PERSONA_HELPERS = (
    "_EXPECTED_MISCONCEPTION",
    "_UNMATCHED_WRONG_ANSWER",
    "_WRONG_ANSWER",
    "_Content",
    "_Journal",
    "_add_all",
    "_attempt",
    "_client",
    "_erase_learner",
    "_get",
    "_hypothesis_confidence",
    "_learner_state",
    "_login",
    "_mastery_of",
    "_next_problem",
    "_pg_reachable",
    "_prereq_edge",
    "_problem_concept",
    "_provisioned_by",
    "_seed_concept",
    "_seed_problems",
    "_settings",
)


def _load_persona_harness() -> ModuleType:
    """페르소나 하네스를 파일 경로로 적재하고 헬퍼 계약을 검사한다."""
    if not _PERSONA_PATH.exists():
        raise RuntimeError(
            f"페르소나 하네스가 없다: {_PERSONA_PATH}. 이 스위트는 그 조립기를 재사용한다 — "
            "파일이 옮겨졌으면 이 경로를 함께 고친다."
        )
    spec = importlib.util.spec_from_file_location("_scenario_persona_harness", _PERSONA_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"페르소나 하네스 스펙 생성 실패: {_PERSONA_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    missing = [name for name in _PERSONA_HELPERS if not hasattr(module, name)]
    if missing:
        raise RuntimeError(
            f"페르소나 하네스의 헬퍼가 사라졌다: {missing}. 이 스위트가 그 조립기를 재사용하므로 "
            "이름이 바뀌면 여기도 함께 고쳐야 한다."
        )
    return module


_P = _load_persona_harness()
_EXPECTED_MISCONCEPTION: str = _P._EXPECTED_MISCONCEPTION
_UNMATCHED_WRONG_ANSWER: str = _P._UNMATCHED_WRONG_ANSWER
_WRONG_ANSWER: str = _P._WRONG_ANSWER
_Content = _P._Content
_Journal = _P._Journal
_add_all = _P._add_all
_attempt = _P._attempt
_client = _P._client
_erase_learner = _P._erase_learner
_get = _P._get
_hypothesis_confidence = _P._hypothesis_confidence
_learner_state = _P._learner_state
_login = _P._login
_mastery_of = _P._mastery_of
_next_problem = _P._next_problem
_pg_reachable = _P._pg_reachable
_prereq_edge = _P._prereq_edge
_problem_concept = _P._problem_concept
_provisioned_by = _P._provisioned_by
_seed_concept = _P._seed_concept
_seed_problems = _P._seed_problems
_settings = _P._settings

#: 코치 완료 경로가 값으로 판정할 수 있는 기대정답(수치 해집합). 코칭 보일러플레이트와 우연히
#: 겹치지 않게 특이한 수를 고른다(관통 테스트의 "70414" 선례와 동형 · 값만 다르게).
_COMPLETION_ANSWER = "58213"
#: 정답 도달 풀이 — 마지막 단계가 기대정답과 동치라 서버 verify가 correct로 판정한다.
_CORRECT_STEPS = ["3*x = 174639", f"x = {_COMPLETION_ANSWER}"]
#: 코치에게 보내는 중립 발화(오개념 id·힌트 단계 미포함 — 서버가 스스로 사다리를 올려야 한다).
_STUCK = "잘 모르겠어요"
#: 학생 질문(AI Tutor) — 풀이·답안을 싣지 않은 *질문*이다.
_QUESTION = "이 문제에서 무엇부터 봐야 해요?"
#: 대화 종결 보고값(`Resolution` enum — 클라이언트 보고·서버는 영속만 한다).
_DIALOGUE_RESOLUTION = "힌트필요"


# ── 관측 헬퍼 (공개 HTTP 표면 · 읽기 전용 SELECT) ───────────────────────────────────


def _begin(tag: str) -> tuple[Any, Any]:
    """회차 시작 — PG 도달성 확인·레이트리미터 격리·식별자 발급(페르소나 `_begin`과 같은 규약).

    미도달은 `skip`이지만 그것은 *판정 불가*이지 통과가 아니다 — CI 잡은 PG 서비스를 띄우므로
    거기서의 skip은 곧 배선 결함이다(문서 §CI 실행 증거가 skipped 0건을 확인한다).
    """
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 판정 불가(WHYMATH_DATABASE_URL 확인). 통과가 아니다.")
    asyncio.run(reset_store())
    return _Content(uuid.uuid4().hex[:8]), _Journal(tag)


def _learning_state(client: Any, auth: dict[str, str]) -> dict[str, Any]:
    """학습 상태 머신의 현재 상태·전이 이력(원장에서 읽는다)."""
    body: dict[str, Any] = _get(client, auth, "/v1/me/learning-state")
    return body


def _trace(client: Any, auth: dict[str, str]) -> list[dict[str, Any]]:
    """학습 이벤트 시간선(오름차순). 잘렸으면 부재 판정에 쓰지 않는다."""
    body = _get(client, auth, "/v1/me/learning-trace")
    assert body["truncated"] is False, "트레이스가 limit에 잘렸다 — 잘린 결과로 판정하지 않는다."
    entries: list[dict[str, Any]] = body["entries"]
    return entries


def _events(entries: list[dict[str, Any]], event_type: str) -> list[dict[str, Any]]:
    return [e for e in entries if e["event_type"] == event_type]


def _hint_levels(entries: list[dict[str, Any]]) -> list[int]:
    """트레이스의 `hint_provided` 단계(시간순). `is not None`으로 거른다(0을 부재로 접지 않는다)."""
    return [
        level
        for e in _events(entries, "hint_provided")
        if (level := (e.get("detail") or {}).get("hint_level")) is not None
    ]


def _user_id(client: Any, auth: dict[str, str]) -> uuid.UUID:
    """본인 user_id — `GET /v1/me`가 없어 반출권 export가 그것을 내는 공개 표면이다."""
    return uuid.UUID(_get(client, auth, "/v1/me/export")["user_id"])


def _read_rows(sql: str, params: dict[str, Any]) -> list[tuple[Any, ...]]:
    """관측 전용 SELECT — 공개 표면이 내지 않는 컬럼만 여기서 읽는다(쓰기 0)."""

    async def _run() -> list[tuple[Any, ...]]:
        engine = create_async_engine(_settings().database_url)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(text(sql), params)
                return [tuple(row) for row in result.all()]
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _answered_problem(content: Any, cid: uuid.UUID, tag: str, difficulty: float) -> uuid.UUID:
    """코치 완료 경로용 문항(저작 콘텐츠) — 기대정답이 *수치*라 서버가 correct로 판정할 수 있다.

    Week 2 `_problem`의 정답은 값으로 파싱되지 않는 sentinel이라 완료 판정 입력으로 못 쓴다.
    그래서 이 좌석만 정답을 달리한 문항을 심는다(조립 방식은 같다 — 자체생성·approved).
    """
    pid = uuid.uuid4()
    asyncio.run(
        _add_all(
            Problem.from_schema(
                ProblemSchema(
                    problem_id=pid,
                    source_type=SourceType.자체생성,
                    review_status=ReviewStatus.approved,
                    curriculum_version=Curriculum.REVISION_2022,
                    valid_from_year=2022,
                    subject=Subject.공통,
                    unit_codes=[f"U-{content.sfx}{tag}"],
                    difficulty_overall=difficulty,
                    question_text=f"3x = 174639 일 때 x의 값을 구하시오. ({tag})",
                    answer=_COMPLETION_ANSWER,
                )
            )
        )
    )
    asyncio.run(_add_all(_problem_concept(pid, cid)))
    content.problem_ids.append(pid)
    return pid


def _drop_dialogues(user_ids: list[uuid.UUID]) -> None:
    """정리 보조 — 삭제권 경로가 이미 지우지만, 본문이 중간에 실패해 삭제권에 닿지 못한 회차의
    잔여가 다음 회차 기준선을 깨지 않게 한다. `DELETE`만 쓴다(정리 목적 — 쓰기 동사 아님).
    """
    if not user_ids:
        return

    async def _run() -> None:
        engine = create_async_engine(_settings().database_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text("DELETE FROM dialogue WHERE user_id = ANY(:ids)"),
                    {"ids": [str(u) for u in user_ids]},
                )
        finally:
            await engine.dispose()

    asyncio.run(_run())


# ── SCENARIO-001 신규 학생 정상 학습 ─────────────────────────────────────────────────


def test_scenario_001_new_student_normal_learning() -> None:
    """SCENARIO-001 신규 학생 정상 학습 — 빈 상태에서 출발해 첫 측정이 생기고 루프가 전진한다.

    단언하는 상태 변화:
      ① 기준선: 숙달 *미측정*(0.0이 아니라 부재) · 활성 오개념 0 · 학습 상태 `NEW`·전이 0건 ·
         시도 이벤트 0건 · 첫 추천 근거는 `cold_start`(측정 없음을 측정으로 위장하지 않는다).
      ② 첫 정답: 학습 상태가 `NEW → LEARNING → ASSESSING → PRACTICING`을 원장에 남긴다
         (`entered_learning_from=NEW` — 학습 진입 전이가 실제로 돌았다) · 숙달이 첫 측정으로 생기고
         이벤트의 `mastery_before`는 `None`(0으로 접히지 않음) · 이벤트 값 = 상태 값.
      ③ 두 번째 정답: 숙달이 **오른다**(방향) · 추천 근거가 `measured_mastery`로 바뀌고 그 값이
         `LearnerState`의 값과 같다 · 시도한 문항은 다시 추천되지 않는다.
    """
    content, journal = _begin("SCENARIO-001")
    try:
        cid, code = _seed_concept(content, "s1", "일차방정식의 풀이")
        pids = _seed_problems(content, cid, "s1", [3.0, 3.4, 3.8])
        pid_set = {str(p) for p in pids}

        with _client() as client:
            _erase_learner(client)
            auth = _login(client)

            # ① 기준선
            before_state = _learner_state(client, auth)
            before_ls = _learning_state(client, auth)
            before_trace = _trace(client, auth)
            journal.record(
                "①기준선",
                "신규 학생",
                숙달=before_state["mastery"].get(code),
                학습상태=before_ls["current_state"],
                전이수=len(before_ls["transitions"]),
            )
            assert code not in before_state["mastery"], before_state["mastery"]
            assert before_state["active_misconceptions"] == [], before_state
            assert before_ls["current_state"] == "NEW", before_ls
            assert before_ls["transitions"] == [], before_ls
            assert _events(before_trace, "problem_attempted") == [], before_trace

            first = _next_problem(client, auth)
            assert first["problem_id"] in pid_set, first
            assert first["reason"]["type"] == "unmeasured", first["reason"]
            assert first["reason"]["basis"] == "cold_start", first["reason"]
            assert first["action"] == "diagnose", first

            # ② 첫 정답
            body = _attempt(client, auth, uuid.UUID(first["problem_id"]), correct=True, answer="1")
            ls_block = body["learning_state"]
            m1 = _mastery_of(client, auth, cid)
            after_ls = _learning_state(client, auth)
            journal.record(
                "②첫정답",
                "측정 개시",
                숙달=m1,
                from_state=ls_block["from_state"],
                to_state=ls_block["to_state"],
                rule=ls_block["rule_id"],
            )
            assert ls_block["entered_learning_from"] == "NEW", ls_block
            assert ls_block["to_state"] == "PRACTICING", ls_block
            assert ls_block["rule_id"] == "R2-correct-low-confidence", ls_block
            assert ls_block["rejected_transition"] is None, ls_block
            assert after_ls["current_state"] == "PRACTICING", after_ls
            # 원장은 최신순 — 뒤집어 시간순 경로로 읽는다.
            path = [(t["from_state"], t["to_state"]) for t in reversed(after_ls["transitions"])]
            assert path == [
                ("NEW", "LEARNING"),
                ("LEARNING", "ASSESSING"),
                ("ASSESSING", "PRACTICING"),
            ], path
            assert m1 is not None, "정답 1건 뒤에도 숙달이 미측정이다 — 전파가 끊겼다."

            entries = _trace(client, auth)
            attempted = [e for e in _events(entries, "problem_attempted")]
            assert [e["attempt_id"] for e in attempted] == [body["attempt_id"]], attempted
            changes = [
                e["mastery_change"]
                for e in _events(entries, "mastery_updated")
                if e["concept_id"] == str(cid) and e["mastery_change"] is not None
            ]
            assert len(changes) == 1, changes
            assert changes[0]["mastery_before"] is None, changes[0]
            assert changes[0]["mastery_after"] == pytest.approx(m1), (changes[0], m1)

            # ③ 두 번째 정답 — 방향과 추천 근거의 전환
            nxt = _next_problem(client, auth)
            assert nxt["problem_id"] in pid_set - {first["problem_id"]}, nxt
            assert nxt["reason"]["basis"] == "measured_mastery", nxt["reason"]
            state_now = _learner_state(client, auth)
            assert nxt["reason"]["mastery"] == pytest.approx(state_now["mastery"][code]), (
                nxt["reason"],
                state_now["mastery"],
            )
            _attempt(client, auth, uuid.UUID(nxt["problem_id"]), correct=True, answer="1")
            m2 = _mastery_of(client, auth, cid)
            journal.record("③두번째정답", "숙달 상승", 숙달=m2)
            assert m2 is not None and m2 > m1, f"정답 2회째인데 숙달이 오르지 않았다: {m1} → {m2}"
        journal.dump()
    finally:
        content.teardown()


# ── SCENARIO-002 낮은 진단점수 ───────────────────────────────────────────────────────


def test_scenario_002_low_diagnostic_score() -> None:
    """SCENARIO-002 낮은 진단점수 — 진단이 대부분 오답으로 확정되면 상태가 '약함'으로 서고
    추천이 쉬운 쪽·선수 쪽으로 내려간다.

    진단 확정은 CAT 중단 규칙이 발화해야 적재된다(`EOS-126` · 문항 수 상한 `MAX_ADMINISTERED_ITEMS`).
    그래서 상한만큼 채점하고 확정한 뒤 다음 상태를 단언한다:
      ① 확정 직전까지는 적재되지 않는다(경계 변별력 — 오답이 많다고 일찍 확정하지 않는다).
      ② 상한 도달 확정 → `assessment.weak_points`에 그 개념이 있고 `strong_points`에는 없다 ·
         학습자 상태 행이 진단 확정으로 생긴다(`provisioned_by=diagnosis_capture`).
      ③ `LearnerState` 숙달 < 선수결손 경계(0.4) · 약점 목록에 그 개념.
      ④ 추천은 남은 두 문항 중 **쉬운 쪽**을 고른다(θ가 내려갔다). 이 픽스처에는 선수 개념이
         없으므로 "선수로 내려가라"를 실어 줄 문항이 없다 — 근거는 `current_concept`(정직 강등 ·
         `intent_resolution=unsupported`)이고 낮은 숙달은 근거에 **그대로** 실린다(EOS-124).
         선수가 측정돼 약하면 선수로 내려가는 갈래는 SCENARIO-003이 판정한다.
    """
    content, journal = _begin("SCENARIO-002")
    try:
        cid, code = _seed_concept(content, "s2", "이차함수의 그래프")
        # 채점용 = 상한 수만큼 중간 난이도 · 남길 문항 2종 = 아주 쉬움/아주 어려움.
        graded = _seed_problems(
            content, cid, "s2g", [2.4 + 0.05 * i for i in range(MAX_ADMINISTERED_ITEMS)]
        )
        easy, hard = _seed_problems(content, cid, "s2r", [1.0, 5.0])

        with _client() as client:
            _erase_learner(client)
            auth = _login(client)
            first = _next_problem(client, auth)
            theta0 = first["theta"]

            # 5문항 중 1정답 — 오개념 사정거리 밖 오답(탐지 채널이 이 시나리오를 흐리지 않게).
            for index, pid in enumerate(graded[:-1]):
                _attempt(client, auth, pid, correct=index % 5 == 4, answer=_UNMATCHED_WRONG_ANSWER)
            # ① 상한 직전 — 확정되지 않는다.
            early = client.post("/v1/me/assessments/capture", headers=auth)
            assert early.status_code == 200, early.text
            assert early.json()["written"] is False, early.json()

            _attempt(client, auth, graded[-1], correct=False, answer=_UNMATCHED_WRONG_ANSWER)
            captured = client.post("/v1/me/assessments/capture", headers=auth)
            assert captured.status_code == 200, captured.text
            cap = captured.json()
            assessment = cap["assessment"]
            weak_ids = {str(w.get("concept_id")) for w in assessment["weak_points"]}
            strong_ids = {str(s.get("concept_id")) for s in assessment["strong_points"]}
            journal.record(
                "②진단확정",
                f"{MAX_ADMINISTERED_ITEMS}문항 중 대부분 오답",
                written=cap["written"],
                reason=cap["reason"],
                약점=len(weak_ids),
                강점=len(strong_ids),
            )
            assert cap["written"] is True, cap
            assert str(cid) in weak_ids, assessment["weak_points"]
            assert str(cid) not in strong_ids, assessment["strong_points"]
            assert _provisioned_by(client, auth) == "diagnosis_capture"

            # ③ 학습자 상태가 '약함'으로 선다.
            state = _learner_state(client, auth)
            mastery = state["mastery"][code]
            weak = _get(client, auth, "/v1/me/weak-concepts")
            journal.record("③상태", "숙달·약점", 숙달=mastery, 약점수=len(weak))
            assert mastery < PREREQUISITE_MASTERY_CEILING, mastery
            assert str(cid) in {w["concept_id"] for w in weak}, weak

            # ④ 추천이 쉬운 쪽으로 내려간다.
            rec = _next_problem(client, auth)
            journal.record(
                "④추천",
                "남은 문항 쉬움/어려움 중 선택",
                theta=rec["theta"],
                theta0=theta0,
                문항=("쉬움" if rec["problem_id"] == str(easy) else rec["problem_id"]),
                reason=rec["reason"]["type"],
            )
            assert rec["theta"] < theta0, (theta0, rec["theta"])
            assert rec["problem_id"] == str(easy), (
                f"낮은 진단 뒤 추천이 쉬운 문항({easy})이 아니다: {rec['problem_id']}"
                f"(어려운 문항 {hard})"
            )
            # EOS-124 — 선수 엣지가 없는 개념에 "선수를 연습하라"를 붙이면 설명이 받은 문항(이
            # 개념의 쉬운 문항)과 어긋난다. 규칙(0.4 미만 → 선수)은 그대로이고, 실어 줄 근거가
            # 없다는 사실이 해소값으로 드러난다.
            assert rec["reason"]["type"] == "current_concept", rec["reason"]
            assert rec["reason"]["mastery"] < PREREQUISITE_MASTERY_CEILING, rec["reason"]
            assert rec["action"] == "practice_current", rec
            assert rec["target_concept"] == str(cid), rec
            assert rec["intent_resolution"] == "unsupported", rec
        journal.dump()
    finally:
        content.teardown()


# ── SCENARIO-003 선수개념 결손 ───────────────────────────────────────────────────────


def test_scenario_003_prerequisite_gap() -> None:
    """SCENARIO-003 선수개념 결손 — 원래 개념의 오답과 선수 개념의 결손이 확인되면 추천이 선수로
    내려가고 target이 선수 개념을 가리킨다.

      ① 원래 개념 오답만 있을 때: 선수 후보는 보이지만 `weak_only` 결손 목록엔 없다(미측정).
      ② 선수 개념 오답 1건 → 결손으로 분류 · 추천 `action=practice_prerequisite`·
         `target_concept=선수` · 고른 문항이 선수 개념 문항.
      ③ 정직한 공백 동결(`EOS-127`) — 같은 상황에서 상태 머신 규칙 R4(선수결손)는 발화하지
         않는다(`prerequisite_gap_concept_ids` 생산자 미배선). 정책 결정은 R6(원인 미상 오답)이다.
    """
    content, journal = _begin("SCENARIO-003")
    try:
        c_pre, _ = _seed_concept(content, "s3pre", "일차방정식의 풀이")
        c_main, _ = _seed_concept(content, "s3main", "이차방정식의 풀이")
        asyncio.run(_add_all(_prereq_edge(c_pre, c_main)))
        pre_pids = _seed_problems(content, c_pre, "s3p", [4.0, 4.2])
        main_pids = _seed_problems(content, c_main, "s3m", [4.1, 4.3, 4.5, 4.7])

        with _client() as client:
            _erase_learner(client)
            auth = _login(client)

            _attempt(client, auth, main_pids[0], correct=False, answer=_UNMATCHED_WRONG_ANSWER)
            candidates = _get(
                client, auth, f"/v1/me/weak-concepts/{c_main}/prerequisites?weak_only=false"
            )
            gaps0 = _get(client, auth, f"/v1/me/weak-concepts/{c_main}/prerequisites")
            journal.record("①원래개념오답", "선수 미측정", 후보=len(candidates), 결손=len(gaps0))
            assert str(c_pre) in {r["concept_id"] for r in candidates}, candidates
            assert str(c_pre) not in {r["concept_id"] for r in gaps0}, gaps0

            _attempt(client, auth, pre_pids[0], correct=False, answer=_UNMATCHED_WRONG_ANSWER)
            gaps = _get(client, auth, f"/v1/me/weak-concepts/{c_main}/prerequisites")
            rec = _next_problem(client, auth)
            journal.record(
                "②결손확정",
                "선수 오답 1건",
                결손=len(gaps),
                action=rec["action"],
                target=("선수" if rec["target_concept"] == str(c_pre) else rec["target_concept"]),
                문항소속=("선수" if rec["problem_id"] in {str(p) for p in pre_pids} else "원래"),
            )
            assert str(c_pre) in {r["concept_id"] for r in gaps}, gaps
            assert rec["action"] == "practice_prerequisite", rec
            assert rec["target_concept"] == str(c_pre), rec
            assert rec["problem_id"] in {str(p) for p in pre_pids}, rec

            # ③ 정직한 공백 동결 (EOS-127) — 결손이 확정된 상태의 원래 개념 오답.
            #    연속 오답 임계(R5)가 R4보다 앞서므로, 정답 1건으로 연속을 끊은 뒤에 본다 —
            #    끊지 않으면 3연속 오답이 R5로 가서 "R4가 없어서 R6"과 구별되지 않는다.
            _attempt(client, auth, main_pids[1], correct=True, answer="정답")
            body = _attempt(
                client, auth, main_pids[2], correct=False, answer=_UNMATCHED_WRONG_ANSWER
            )
            ls_block = body["learning_state"]
            journal.record(
                "③R4미발화",
                "EOS-127 정직한 공백",
                rule=ls_block["rule_id"],
                next_action=ls_block["next_action"],
                target=ls_block["target_concept_id"],
            )
            assert ls_block["rule_id"] == "R6-wrong-undiagnosed", (
                f"선수 결손 상태의 오답에 규칙 {ls_block['rule_id']}가 발화했다 — `EOS-127`(R4 "
                "생산자 배선)이 해소된 것으로 보인다. 이 단언을 R4·GO_TO_PREREQUISITE_CONCEPT·"
                "target=선수 단언으로 승격하고 EOS-127을 닫아라."
            )
            assert ls_block["target_concept_id"] is None, ls_block
        journal.dump()
    finally:
        content.teardown()


# ── SCENARIO-004 동일 오개념 반복 ────────────────────────────────────────────────────


def test_scenario_004_repeated_same_misconception() -> None:
    """SCENARIO-004 동일 오개념 반복 — 같은 거짓형을 거듭 쓰면 가설 confidence가 오르고, 반복이
    임계에 닿으면 정책이 교정(R3)에서 설명·힌트(R5)로 넘어간다.

      ① 매 회차 그 시도의 증거에서 같은 오개념이 탐지되고(`ran_with_candidates`) 누적 가설
         confidence가 **단조 증가**한다.
      ② 1·2회차 정책 = R3(오개념 교정)·target=그 오개념 · `REMEDIATING`.
      ③ 3회차(`REPEATED_FAILURE_THRESHOLD`) = R5(반복 실패)가 R3보다 앞선다 — 막힌 학생에게 교정을
         거듭하지 않고 설명·힌트로 넘어간다(규칙 우선순위의 상태 증거).
    """
    content, journal = _begin("SCENARIO-004")
    try:
        cid, code = _seed_concept(content, "s4", "완전제곱식의 전개")
        pids = _seed_problems(content, cid, "s4", [3.0, 3.4, 3.8, 4.2])

        with _client() as client:
            _erase_learner(client)
            auth = _login(client)
            confidences: list[float] = []
            rules: list[str | None] = []
            detected_counts: list[int] = []
            for index in range(REPEATED_FAILURE_THRESHOLD):
                body = _attempt(client, auth, pids[index], correct=False, answer=_WRONG_ANSWER)
                ls_block = body["learning_state"]
                conf = _hypothesis_confidence(client, auth, _EXPECTED_MISCONCEPTION)
                coverage = body["evidence"]["coverage"]
                detected = [
                    c["misconception_id"]
                    for c in body["evidence"]["possible_misconceptions"]
                    if c["misconception_id"] == _EXPECTED_MISCONCEPTION
                ]
                journal.record(
                    f"회차{index + 1}",
                    f"같은 거짓형 {_WRONG_ANSWER}",
                    confidence=conf,
                    rule=ls_block["rule_id"],
                    next_action=ls_block["next_action"],
                    scan=coverage["misconception_scan"],
                )
                assert conf is not None, "오개념이 가설로 영속되지 않았다."
                confidences.append(conf)
                rules.append(ls_block["rule_id"])
                # 매 회차 *그 시도에서* 탐지된다(누적 가설을 되읽은 것이 아니다).
                assert coverage["misconception_scan"] == "ran_with_candidates", coverage
                detected_counts.append(len(detected))
                if index < REPEATED_FAILURE_THRESHOLD - 1:
                    assert ls_block["rule_id"] == "R3-wrong-misconception", ls_block
                    assert ls_block["target_misconception_id"] == _EXPECTED_MISCONCEPTION, ls_block
                    assert ls_block["to_state"] == "REMEDIATING", ls_block

            assert all(
                b > a for a, b in zip(confidences, confidences[1:], strict=False)
            ), f"같은 오개념을 거듭 관측했는데 confidence가 단조 증가하지 않는다: {confidences}"
            assert detected_counts == [1] * REPEATED_FAILURE_THRESHOLD, detected_counts
            assert (
                rules[-1] == "R5-repeated-failure"
            ), f"{REPEATED_FAILURE_THRESHOLD}연속 오답인데 R5가 R3를 앞서지 않았다: {rules}"
            assert _EXPECTED_MISCONCEPTION in _learner_state(client, auth)["active_misconceptions"]
        journal.dump()
    finally:
        content.teardown()


# ── SCENARIO-005 힌트 후 정답 ────────────────────────────────────────────────────────


def test_scenario_005_correct_after_hint() -> None:
    """SCENARIO-005 힌트 후 정답 — 막혀서 힌트를 받은 뒤 코치 대화 안에서 정답에 도달하면, 돌아보기
    1턴을 거쳐 서버가 정답 attempt를 적재하고 숙달이 측정된다.

      ① 막힘 → 힌트: `hint_provided` 이벤트(단계 1~4)가 적재되고 아직 attempt·숙달은 없다.
      ② 정답 풀이 제출 → **바로 완료하지 않는다**(돌아보기 대기 · 적재 0 · 숙달 미측정 유지).
      ③ 돌아보기 응답 → 완료 · `problem_attempt` 1행(is_correct=True·used_socratic=True) ·
         숙달이 첫 측정으로 생긴다 · 힌트 이벤트가 그 문항에 묶여 시간선에 남는다.
      ④ 정직한 공백 동결 2건(ⓐ `EOS-133` · ⓑ `EOS-134`):
         ⓐ 힌트 사용이 그 attempt에 귀속되지 않는다 — `used_hint` NULL · `hint_usage` 0행
            (그래서 힌트 받은 정답과 스스로 푼 정답이 숙달 갱신에서 구별되지 않는다).
         ⓑ 코치 완료 경로는 학습 상태 머신을 돌리지 않는다 — 원장이 `NEW` 그대로다.
    """
    content, journal = _begin("SCENARIO-005")
    try:
        cid, code = _seed_concept(content, "s5", "일차방정식의 풀이")
        pid = _answered_problem(content, cid, "s5", 3.0)

        with _client() as client:
            _erase_learner(client)
            auth = _login(client)
            uid = _user_id(client, auth)

            # ① 막힘 → 힌트
            opened = client.post(
                "/v1/coach/sessions",
                headers=auth,
                json={"student_input": _STUCK, "problem_id": str(pid)},
            )
            assert opened.status_code == 201, opened.text
            obody = opened.json()
            did = obody["dialogue_id"]
            hint = obody["decision"]["hint_level"]
            levels = _hint_levels(_trace(client, auth))
            journal.record("①힌트", "막힘 신호", hint_level=hint, 적재=levels)
            assert isinstance(hint, int) and 1 <= hint <= 4, obody["decision"]
            assert levels == [hint], levels
            assert _mastery_of(client, auth, cid) is None

            # ② 정답 풀이 제출 → 돌아보기 대기
            solved = client.post(
                f"/v1/coach/sessions/{did}/turns",
                headers=auth,
                json={
                    "student_input": "이렇게 풀었어요",
                    "solution_steps": _CORRECT_STEPS,
                    "solution_step_types": ["계산"],
                },
            )
            assert solved.status_code == 201, solved.text
            sbody = solved.json()
            journal.record(
                "②정답제출",
                "돌아보기 대기",
                awaiting=sbody["awaiting_reflection"],
                complete=sbody["problem_complete"],
            )
            assert sbody["awaiting_reflection"] is True, sbody
            assert sbody["problem_complete"] is False, sbody
            assert _events(_trace(client, auth), "problem_attempted") == []
            assert _mastery_of(client, auth, cid) is None

            # ③ 돌아보기 → 완료
            reflected = client.post(
                f"/v1/coach/sessions/{did}/turns",
                headers=auth,
                json={"student_input": "양변을 3으로 나누면 x만 남아서 그렇게 풀었어요"},
            )
            assert reflected.status_code == 201, reflected.text
            rbody = reflected.json()
            assert rbody["problem_complete"] is True, rbody
            attempt_id = rbody["completed_attempt_id"]
            assert attempt_id is not None, rbody
            rows = _read_rows(
                "SELECT attempt_id, is_correct, used_socratic, used_hint FROM problem_attempt "
                "WHERE user_id = :uid",
                {"uid": str(uid)},
            )
            mastery = _mastery_of(client, auth, cid)
            entries = _trace(client, auth)
            timeline = [e["event_type"] for e in entries]
            journal.record(
                "③완료",
                "돌아보기 후 적재",
                attempt수=len(rows),
                숙달=mastery,
                시간선=timeline,
            )
            assert len(rows) == 1 and str(rows[0][0]) == attempt_id, rows
            assert rows[0][1] is True and rows[0][2] is True, rows
            assert mastery is not None, "정답 완료 뒤에도 숙달이 미측정이다."
            assert code in _learner_state(client, auth)["mastery"]
            # 힌트 이벤트는 이 문항에 묶여 있다. 시간선 *순서*는 단언하지 않는다 — 완료 attempt의
            # 발생 시각은 대화 시작 시각(PED-37: 풀이 시작=발생)이라 힌트보다 앞에 놓이는 것이
            # 정본 계약이다(수신 시각으로 정렬하면 날조다).
            hint_events = _events(entries, "hint_provided")
            assert hint_events and all(
                e["problem_id"] == str(pid) for e in hint_events
            ), hint_events

            # ④ⓐ 정직한 공백 동결 — 힌트 사용이 attempt에 귀속되지 않는다.
            hint_rows = _read_rows(
                "SELECT count(*) FROM hint_usage WHERE attempt_id = :aid", {"aid": attempt_id}
            )
            journal.record(
                "④ⓐ힌트귀속",
                "정직한 공백 — EOS-133",
                used_hint=rows[0][3],
                hint_usage=hint_rows[0][0],
            )
            assert rows[0][3] is None and hint_rows[0][0] == 0, (
                "힌트를 받은 뒤의 정답 attempt에 힌트 사용이 기록됐다(used_hint="
                f"{rows[0][3]} · hint_usage={hint_rows[0][0]}) — 힌트 귀속 공백이 해소된 것으로 "
                "보인다. 이 단언을 '힌트 사용이 기록되고 숙달 이득이 감액된다'로 승격하라"
                "(소유 태스크 EOS-133-coach-hint-usage-attribution)."
            )

            # ④ⓑ 정직한 공백 동결 — 코치 완료 경로는 학습 상태 머신을 돌리지 않는다.
            ls = _learning_state(client, auth)
            journal.record(
                "④ⓑ상태머신",
                "정직한 공백 — EOS-134",
                current=ls["current_state"],
                전이수=len(ls["transitions"]),
            )
            assert ls["current_state"] == "NEW" and ls["transitions"] == [], (
                f"코치 완료 뒤 학습 상태 원장이 움직였다: {ls['current_state']} · "
                f"{len(ls['transitions'])}건 — 코치 완료 경로에 상태 머신이 배선된 것으로 보인다. "
                "이 단언을 `/v1/me/attempts`와 같은 전이(… → PRACTICING) 단언으로 승격하라"
                "(소유 태스크 EOS-134-coach-completion-state-machine)."
            )
            _erase_learner(client)
        journal.dump()
    finally:
        content.teardown()


# ── SCENARIO-006 AI Tutor 질문 ───────────────────────────────────────────────────────


def test_scenario_006_ai_tutor_question() -> None:
    """SCENARIO-006 AI Tutor 질문 — 학생이 풀이 없이 질문하면 대화가 영속되고 힌트 사다리가
    서버 원장을 따라 오르되, **채점 상태는 움직이지 않는다**(질문은 시도가 아니다).

      ① 첫 질문 → 대화 1건·턴 2(학생/AI) 영속 · `hint_provided` 1건 · 숙달 미측정 유지.
      ② 이어지는 질문(클라가 단계를 보내지 않음) → 서버가 직전 적재에서 단계를 되찾아
         **올린다** · 턴 4 · `hint_provided` 2건(오름차순).
      ③ 두 질문 뒤에도 `problem_attempted` 0건 · 숙달 미측정 · 학습 상태 `NEW` 그대로
         (질문이 채점으로 새지 않는다 — 정답 즉시 제공 금지와 짝인 상태 불변).
      ④ 새 대화를 열어 같은 문항에 다시 막히면 사다리가 **원장의 직전 단계를 이어** 오른다.
    """
    content, journal = _begin("SCENARIO-006")
    try:
        cid, _ = _seed_concept(content, "s6", "완전제곱식의 전개")
        (pid,) = _seed_problems(content, cid, "s6", [3.0])

        with _client() as client:
            _erase_learner(client)
            auth = _login(client)

            opened = client.post(
                "/v1/coach/sessions",
                headers=auth,
                json={"student_input": _QUESTION, "problem_id": str(pid)},
            )
            assert opened.status_code == 201, opened.text
            obody = opened.json()
            did = obody["dialogue_id"]
            first_level = obody["decision"]["hint_level"]
            got = _get(client, auth, f"/v1/coach/sessions/{did}")
            levels1 = _hint_levels(_trace(client, auth))
            journal.record(
                "①첫질문", "대화 영속", 턴=len(got["turns"]), hint=first_level, 적재=levels1
            )
            assert len(got["turns"]) == 2, got["turns"]
            assert levels1 == [first_level], levels1
            assert first_level < 4, "사다리 상한에서 시작하면 ②의 상승을 관측할 수 없다(픽스처)."

            follow = client.post(
                f"/v1/coach/sessions/{did}/turns",
                headers=auth,
                json={"student_input": "아직 잘 모르겠어요. 다음엔 뭘 봐요?"},
            )
            assert follow.status_code == 201, follow.text
            second_level = follow.json()["decision"]["hint_level"]
            got2 = _get(client, auth, f"/v1/coach/sessions/{did}")
            entries = _trace(client, auth)
            levels2 = _hint_levels(entries)
            journal.record(
                "②이어질문", "사다리 상승", 턴=len(got2["turns"]), hint=second_level, 적재=levels2
            )
            assert second_level > first_level, (first_level, second_level)
            assert len(got2["turns"]) == 4, got2["turns"]
            assert levels2 == [first_level, second_level], levels2

            # ③ 채점 상태 불변
            ls = _learning_state(client, auth)
            assert _events(entries, "problem_attempted") == [], entries
            assert _mastery_of(client, auth, cid) is None
            assert ls["current_state"] == "NEW", ls
            dialogues = _get(client, auth, "/v1/me/dialogues")
            assert [d["dialogue_id"] for d in dialogues] == [did], dialogues
            journal.record(
                "③채점불변", "질문은 시도가 아니다", 시도=0, 학습상태=ls["current_state"]
            )

            # ④ 새 대화에서 같은 문항에 다시 막히면 사다리는 1단계로 되돌아가지 않고 **원장의
            #    직전 단계에서 이어 오른다** — 새 대화의 첫 턴에는 턴 메타가 없으므로 이어짐의
            #    근거는 `hint_provided` 원장(문항 단위)뿐이다. ②만으로는 원장 읽기를 볼 수 없다:
            #    대화 안에서는 턴 메타가 같은 역할을 해 원장 읽기를 끊어도 사다리가 오른다
            #    (2026-09-24 뮤테이션 실측 — append 경로의 원장 읽기를 끊은 주입이 ②에서 생존).
            #    막힘 신호로 묻는 이유: 막힘이 아닌 순수 질문은 새 대화에서 1단계로 시작한다
            #    (실측) — 그것은 리셋이 아니라 사다리를 올릴 근거가 없는 것이다.
            reopened = client.post(
                "/v1/coach/sessions",
                headers=auth,
                json={
                    "student_input": "아직 잘 모르겠어요. 다음엔 뭘 봐요?",
                    "problem_id": str(pid),
                },
            )
            assert reopened.status_code == 201, reopened.text
            third_level = reopened.json()["decision"]["hint_level"]
            journal.record("④새대화", "원장에서 이어짐", hint=third_level, 직전=second_level)
            assert third_level > second_level, (
                f"새 대화에서 사다리가 원장의 직전 단계({second_level})를 잇지 않았다: "
                f"{third_level} — 세션을 새로 열면 답 미루기 사다리가 리셋된다."
            )
            _erase_learner(client)
        journal.dump()
    finally:
        content.teardown()


# ── SCENARIO-007 mastery threshold 통과 ─────────────────────────────────────────────


def test_scenario_007_mastery_threshold_crossing() -> None:
    """SCENARIO-007 mastery threshold 통과 — 정답이 쌓여 숙달이 경계(0.7)를 넘는 순간 추천 근거가
    `current_concept`에서 `next_concept`로, 약점 목록에서 그 개념이 빠진다.

    판정은 **궤적 전체**에 걸친다 — 매 회차마다 `(숙달, 추천 근거)` 쌍이 경계 규칙과 일치해야
    한다(0.7 이하 ⇒ next 아님 · 0.7 초과 ⇒ next). 한 점만 보면 "처음부터 next였다"와 "경계에서
    바뀌었다"가 구별되지 않으므로, 경계 **아래** 관측과 **위** 관측이 각각 1건 이상이어야 통과다.

    **후행 개념을 함께 심는 이유(EOS-124)**: 전진(`next_concept`)은 넘어갈 개념이 있어야 문항으로
    실린다. 후행이 없으면 정책은 숙달한 개념의 문항에 `advance_next`를 붙이지 않고 정직 강등한다
    — 그래서 경계 통과를 관측하려면 목적지가 필요하다. 후행 문항은 **아주 쉽게** 둔다: 1차 CAT
    선택(θ 근방)은 경계 아래 동안 현재 개념 문항을 고르고, 경계를 넘는 순간 정책이 다음 개념
    문항으로 다시 고른다 — 난이도가 아니라 숙달이 이동을 일으켰다는 것이 구별된다.
    """
    content, journal = _begin("SCENARIO-007")
    try:
        cid, code = _seed_concept(content, "s7", "일차함수의 기울기")
        c_next, _ = _seed_concept(content, "s7next", "일차함수의 그래프 해석")
        asyncio.run(_add_all(_prereq_edge(cid, c_next)))
        pids = _seed_problems(content, cid, "s7", [3.0 + 0.2 * i for i in range(10)])
        next_pids = _seed_problems(content, c_next, "s7n", [1.0, 1.2])
        pid_set = {str(p) for p in pids}
        next_set = {str(p) for p in next_pids}

        with _client() as client:
            _erase_learner(client)
            auth = _login(client)
            trajectory: list[tuple[float, str, bool]] = []
            crossed = False
            for step in range(len(pids) - 1):
                rec = _next_problem(client, auth)
                if step == 0:
                    assert rec["problem_id"] in pid_set, rec
                if step > 0:
                    mastery = _learner_state(client, auth)["mastery"][code]
                    weak = {w["concept_id"] for w in _get(client, auth, "/v1/me/weak-concepts")}
                    in_weak = str(cid) in weak
                    trajectory.append((mastery, rec["reason"]["type"], in_weak))
                    journal.record(
                        f"회차{step}",
                        "정답 누적",
                        숙달=mastery,
                        reason=rec["reason"]["type"],
                        action=rec["action"],
                        약점=in_weak,
                        문항=("다음개념" if rec["problem_id"] in next_set else "현재개념"),
                    )
                    # 근거는 앵커(현재 개념)의 숙달이다 — 전진 회차에도 같다.
                    assert rec["reason"]["mastery"] == pytest.approx(mastery), (rec, mastery)
                    if mastery > WEAK_CONCEPT_MASTERY_CEILING:
                        # EOS-124 — 전진은 말뿐이 아니라 문항으로 실린다(목적지 = 다음 개념).
                        assert rec["problem_id"] in next_set, rec
                        assert rec["target_concept"] == str(c_next), rec
                        assert rec["intent_resolution"] == "served", rec
                        crossed = True
                        break
                    assert rec["problem_id"] in pid_set, rec
                _attempt(client, auth, uuid.UUID(rec["problem_id"]), correct=True, answer="1")

            below = [t for t in trajectory if t[0] <= WEAK_CONCEPT_MASTERY_CEILING]
            above = [t for t in trajectory if t[0] > WEAK_CONCEPT_MASTERY_CEILING]
            assert (
                crossed and below and above
            ), f"경계 아래·위 관측이 모두 있어야 판정할 수 있다: {trajectory}"
            for mastery, reason_type, in_weak in trajectory:
                expected_next = mastery > WEAK_CONCEPT_MASTERY_CEILING
                assert (reason_type == "next_concept") is expected_next, (mastery, reason_type)
                assert in_weak is not expected_next, (mastery, in_weak)
            for mastery, reason_type, _ in below:
                if mastery >= PREREQUISITE_MASTERY_CEILING:
                    assert reason_type == "current_concept", (mastery, reason_type)
        journal.dump()
    finally:
        content.teardown()


# ── SCENARIO-008 다음 concept 이동 ───────────────────────────────────────────────────


def test_scenario_008_move_to_next_concept() -> None:
    """SCENARIO-008 다음 concept 이동 — 현재 개념을 확신 있게 맞히면 상태 머신이 `ADVANCING`으로
    가고, 추천은 전진을 말하며, 현재 개념 후보가 소진되면 다음 개념 문항·target으로 옮겨 간다.

      ① 높은 자기보고 확신도의 정답 → R1 · `ADVANCING` · `ADVANCE_TO_NEXT_CONCEPT`.
      ② 숙달 경계 통과 후 추천 `action=advance_next`.
      ③ 정책·선택 정렬(`EOS-124` 해소 — 동결 승격) — 현재 개념에 미시도 문항이 남아 있어도 그
         순간 고른 문항·target은 **다음** 개념이다(이동이 후보 고갈의 부산물이 아니라 선택이다).
      ④ 현재 개념 소진 뒤에도 다음 개념에 머문다 · `target_concept=다음 개념`.
    """
    content, journal = _begin("SCENARIO-008")
    try:
        c_cur, _ = _seed_concept(content, "s8cur", "일차식의 전개")
        c_next, _ = _seed_concept(content, "s8next", "이차식의 전개")
        asyncio.run(_add_all(_prereq_edge(c_cur, c_next)))
        # 남겨 둘 현재 개념 문항(cur_pids[5])을 **가장 어렵게** 둔다. 전부 맞힌 학생의 θ는 척도
        # 상단에 붙으므로 θ 근방 1차 선택은 가장 어려운 문항 — 즉 **현재 개념** 문항을 집는다.
        # 그런데도 ③에서 다음 개념 문항이 나오면, 이동을 만든 것은 난이도 배치가 아니라 정책의
        # 정렬 재선택이다(EOS-124). 다음 개념 문항을 더 어렵게 두면 1차 선택이 먼저 그쪽을 집어
        # 이 변별력이 사라진다(2026-09-24 실측: 다음 개념 4.8/5.0 배치에서 ②·③ 판정 불가).
        cur_pids = _seed_problems(content, c_cur, "s8c", [2.0, 2.4, 2.8, 3.2, 3.6, 5.0])
        next_pids = _seed_problems(content, c_next, "s8n", [3.0, 3.4])
        cur_set = {str(p) for p in cur_pids}

        with _client() as client:
            _erase_learner(client)
            auth = _login(client)

            # ① 확신 있는 정답 → ADVANCING
            resp = client.post(
                "/v1/me/attempts",
                headers=auth,
                json={
                    "problem_id": str(cur_pids[0]),
                    "is_correct": True,
                    "student_answer": "정답",
                    "confidence_self_reported": 0.9,
                },
            )
            assert resp.status_code == 201, resp.text
            ls_block = resp.json()["learning_state"]
            journal.record(
                "①확신정답",
                "R1",
                rule=ls_block["rule_id"],
                to_state=ls_block["to_state"],
                next_action=ls_block["next_action"],
            )
            assert ls_block["rule_id"] == "R1-correct-high-confidence", ls_block
            assert ls_block["to_state"] == "ADVANCING", ls_block
            assert ls_block["next_action"] == "ADVANCE_TO_NEXT_CONCEPT", ls_block
            assert _learning_state(client, auth)["current_state"] == "ADVANCING"

            # ② 숙달 경계 통과 → 전진을 말한다. 현재 개념 문항 하나는 미시도로 남긴다.
            for pid in cur_pids[1:5]:
                _attempt(client, auth, pid, correct=True, answer="정답")
            advanced = _next_problem(client, auth)
            journal.record(
                "②전진",
                f"현재 개념 미시도 {cur_pids[5]} 남김",
                action=advanced["action"],
                target=("현재" if advanced["target_concept"] == str(c_cur) else "다음"),
                문항=("현재" if advanced["problem_id"] in cur_set else "다음"),
            )
            assert advanced["action"] == "advance_next", advanced

            # ③ 정책·선택 정렬 (EOS-124 해소 — 동결 승격)
            next_set = {str(p) for p in next_pids}
            assert advanced["problem_id"] in next_set, (
                f"전진 추천의 문항 {advanced['problem_id']}가 다음 개념 것이 아니다 — 정책은 전진을 "
                "말하는데 콘텐츠는 제자리다(`EOS-124` 재발)."
            )
            assert advanced["target_concept"] == str(c_next), advanced
            assert advanced["reason"]["concept_id"] == str(c_cur), advanced  # 전진의 근거
            assert advanced["intent_resolution"] == "served", advanced

            # ④ 현재 개념 소진 → 다음 개념
            _attempt(client, auth, cur_pids[5], correct=True, answer="정답")
            moved = _next_problem(client, auth)
            journal.record(
                "④이동",
                "현재 개념 소진",
                문항=("다음" if moved["problem_id"] in {str(p) for p in next_pids} else "현재"),
                target=("다음" if moved["target_concept"] == str(c_next) else "현재"),
            )
            assert moved["problem_id"] in {str(p) for p in next_pids}, moved
            assert moved["target_concept"] == str(c_next), moved
        journal.dump()
    finally:
        content.teardown()


# ── SCENARIO-009 세션 종료 후 재접속 ─────────────────────────────────────────────────


def test_scenario_009_reconnect_after_session_end() -> None:
    """SCENARIO-009 세션 종료 후 재접속 — 학습 대화를 종료하고 앱을 새로 띄워 다시 로그인해도
    같은 학생의 기록이 그대로 이어진다.

    "세션"의 실재 좌석은 코치 대화(`dialogue`)다 — 종료 표면 `PATCH /v1/me/dialogues/{id}/end`가
    있다. 재접속은 **새 앱 인스턴스 + 새 토큰**으로 흉내 낸다(같은 이메일 → 같은 학생).
      ① 종료 전: 대화 `ended_at` 없음 · 시도 1건 · 숙달 측정됨.
      ② 종료: `ended_at`·`resolution`이 채워진다.
      ③ 재접속(새 앱·새 토큰): 같은 user_id · 종료된 대화가 목록에 종료 상태로 · 턴 보존 ·
         숙달·활성 오개념 동일 · 시도한 문항은 다시 추천되지 않는다.
      ④ 학습 세션 이어짐(EOS-131 — 종전 '세션 행 0' 공백 동결의 승격) — 서버 30분 유휴 규칙이
         연 `LearningSession`은 재접속(새 앱·새 토큰) 뒤에도 **같은 세션**으로 이어진다. 대화 종료는
         학습 세션 종료가 아니다(세션은 학습 활동 묶음). 점수(`focus_score`·`engagement_score`)는
         계속 비어 있다(S3-16 ③ 점수 미신설 유지).
    """
    content, journal = _begin("SCENARIO-009")
    uids: list[uuid.UUID] = []
    try:
        cid, code = _seed_concept(content, "s9", "완전제곱식의 전개")
        pids = _seed_problems(content, cid, "s9", [3.0, 3.4, 3.8])

        with _client() as client:
            _erase_learner(client)
            auth = _login(client)
            uid = _user_id(client, auth)
            uids.append(uid)
            _attempt(client, auth, pids[0], correct=False, answer=_WRONG_ANSWER)
            first_sessions = _get(client, auth, "/v1/me/sessions")
            assert len(first_sessions) == 1, first_sessions
            learning_session_id = first_sessions[0]["session_id"]
            opened = client.post(
                "/v1/coach/sessions",
                headers=auth,
                json={"student_input": _STUCK, "problem_id": str(pids[0])},
            )
            assert opened.status_code == 201, opened.text
            did = opened.json()["dialogue_id"]
            before_state = _learner_state(client, auth)
            before_dialogue = _get(client, auth, "/v1/me/dialogues")
            journal.record(
                "①종료전",
                "대화 진행 중",
                ended_at=before_dialogue[0]["ended_at"],
                숙달=before_state["mastery"].get(code),
            )
            assert before_dialogue[0]["ended_at"] is None, before_dialogue

            ended = client.patch(
                f"/v1/me/dialogues/{did}/end",
                headers=auth,
                json={"resolution": _DIALOGUE_RESOLUTION},
            )
            assert ended.status_code == 200, ended.text
            ebody = ended.json()
            journal.record(
                "②종료", "대화 종료", ended_at=ebody["ended_at"], resolution=ebody["resolution"]
            )
            assert ebody["ended_at"] is not None, ebody
            assert ebody["resolution"] == _DIALOGUE_RESOLUTION, ebody

        # ③ 재접속 — 프로세스 인메모리 상태(레이트리미터)도 비우고 새 앱을 띄운다.
        asyncio.run(reset_store())
        with _client() as client2:
            # 토큰 문자열 비교는 하지 않는다 — JWT `iat`가 초 단위라 같은 초 안의 재로그인은
            # 같은 토큰을 낸다(2026-09-24 실측: 무작위 순서 4회 중 1회 거짓 실패). 재접속의 실체는
            # 새 앱 인스턴스 + 로그인 경로 재통과이며, 같은 학생인지는 아래 user_id로 본다.
            auth2 = _login(client2)
            assert _user_id(client2, auth2) == uid, "재접속이 다른 학생으로 이어졌다."
            dialogues = _get(client2, auth2, "/v1/me/dialogues")
            assert [d["dialogue_id"] for d in dialogues] == [did], dialogues
            assert dialogues[0]["ended_at"] is not None, dialogues
            assert dialogues[0]["resolution"] == _DIALOGUE_RESOLUTION, dialogues
            turns = _get(client2, auth2, f"/v1/coach/sessions/{did}")["turns"]
            after_state = _learner_state(client2, auth2)
            rec = _next_problem(client2, auth2)
            journal.record(
                "③재접속",
                "새 앱·새 토큰",
                턴=len(turns),
                숙달=after_state["mastery"].get(code),
                추천=rec["problem_id"],
            )
            assert len(turns) == 2, turns
            assert after_state["mastery"] == before_state["mastery"], (before_state, after_state)
            assert after_state["active_misconceptions"] == before_state["active_misconceptions"], (
                before_state,
                after_state,
            )
            assert rec["problem_id"] != str(pids[0]), rec

            # ④ 학습 세션 이어짐(EOS-131) — 재접속 뒤에도 30분 안이면 같은 학습 세션이다.
            sessions = _get(client2, auth2, "/v1/me/sessions")
            journal.record("④학습세션", "EOS-131 서버 유휴 규칙", 세션수=len(sessions))
            assert [s["session_id"] for s in sessions] == [learning_session_id], (
                "재접속이 같은 학습 세션으로 이어지지 않았다 — `EOS-131` 서버 30분 유휴 규칙 "
                "writer(`l2/learning_session_writer`)를 확인하라."
            )
            assert sessions[0]["ended_at"] is None, sessions
            assert sessions[0]["focus_score"] is None, sessions
            assert sessions[0]["engagement_score"] is None, sessions
            _erase_learner(client2)
        journal.dump()
    finally:
        try:
            content.teardown()
        finally:
            _drop_dialogues(uids)


# ── SCENARIO-010 학습 상태 복구 ──────────────────────────────────────────────────────


def test_scenario_010_learning_state_recovery() -> None:
    """SCENARIO-010 학습 상태 복구 — 학습 상태는 프로세스 기억이 아니라 **원장에서 복구**된다.

    오개념 교정 국면(`REMEDIATING`)까지 진행한 학생을, 앱 인스턴스·토큰·인메모리 상태를 모두
    새로 한 뒤 다시 본다.
      ① 복구 전: 학습 상태 `REMEDIATING` · 활성 오개념 1 · 가설 confidence 측정됨.
      ② 새 앱: 현재 상태·전이 이력·숙달·활성 오개념·가설 confidence가 **동일**하다.
      ③ 복구된 상태에서 이어서 풀면 상태 머신이 `NEW`가 아니라 **복구된 상태에서 출발**한다
         (`from_state=REMEDIATING` · 학습 진입 전이 재적재 없음 · 옛 이력 보존·새 전이만 추가).
    """
    content, journal = _begin("SCENARIO-010")
    try:
        cid, code = _seed_concept(content, "s10", "완전제곱식의 전개")
        pids = _seed_problems(content, cid, "s10", [3.0, 3.4, 3.8])

        with _client() as client:
            _erase_learner(client)
            auth = _login(client)
            body = _attempt(client, auth, pids[0], correct=False, answer=_WRONG_ANSWER)
            assert body["learning_state"]["to_state"] == "REMEDIATING", body["learning_state"]
            before_ls = _learning_state(client, auth)
            before_state = _learner_state(client, auth)
            before_conf = _hypothesis_confidence(client, auth, _EXPECTED_MISCONCEPTION)
            journal.record(
                "①복구전",
                "교정 국면",
                학습상태=before_ls["current_state"],
                전이수=len(before_ls["transitions"]),
                confidence=before_conf,
            )
            assert before_ls["current_state"] == "REMEDIATING", before_ls
            assert before_conf is not None

        asyncio.run(reset_store())
        with _client() as client2:
            auth2 = _login(client2)
            after_ls = _learning_state(client2, auth2)
            after_state = _learner_state(client2, auth2)
            after_conf = _hypothesis_confidence(client2, auth2, _EXPECTED_MISCONCEPTION)
            journal.record(
                "②새앱",
                "원장에서 복구",
                학습상태=after_ls["current_state"],
                전이수=len(after_ls["transitions"]),
                confidence=after_conf,
            )
            assert after_ls["current_state"] == before_ls["current_state"], after_ls
            assert after_ls["transitions"] == before_ls["transitions"], after_ls
            assert after_state["mastery"] == before_state["mastery"], after_state
            assert after_state["active_misconceptions"] == before_state["active_misconceptions"]
            assert after_conf == pytest.approx(before_conf), (before_conf, after_conf)

            # ③ 복구된 상태에서 이어 풀기
            cont = _attempt(client2, auth2, pids[1], correct=True, answer="x^2+4x+4")
            ls_block = cont["learning_state"]
            final_ls = _learning_state(client2, auth2)
            journal.record(
                "③이어풀기",
                "복구된 상태에서 출발",
                from_state=ls_block["from_state"],
                to_state=ls_block["to_state"],
                entered_learning_from=ls_block["entered_learning_from"],
                전이수=len(final_ls["transitions"]),
            )
            assert ls_block["from_state"] == "REMEDIATING", ls_block
            assert ls_block["entered_learning_from"] is None, ls_block
            assert ls_block["rejected_transition"] is None, ls_block
            added = list(
                reversed(
                    final_ls["transitions"][
                        : len(final_ls["transitions"]) - len(before_ls["transitions"])
                    ]
                )
            )
            assert added, final_ls
            assert added[0]["from_state"] == "REMEDIATING", added
            assert all(t["from_state"] != "NEW" for t in added), added
            assert added[-1]["to_state"] == final_ls["current_state"] == ls_block["to_state"], added
            # 원장의 옛 이력은 그대로다(복구가 이력을 다시 쓰지 않는다).
            assert final_ls["transitions"][len(added) :] == before_ls["transitions"], final_ls
            _erase_learner(client2)
        journal.dump()
    finally:
        content.teardown()
