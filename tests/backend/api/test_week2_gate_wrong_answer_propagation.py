"""계획서 300 Phase 2 §7 **Week 2 Gate 판정** 하네스 — 오답 1건이 전 구간에 전파되는가.

판정 대상(원 문서 §7 완료 판정 그대로):

    Attempt → Assessment → Misconception → Mastery → LearnerState

오답 **한 건**을 공개 HTTP 표면으로 넣고, 그 한 건이 다섯 구간 전부를 실제로 움직였는지
*산출물*로 단언한다. 판정은 pytest exit code로 나오고, 구간마다 `WEEK2_GATE_STEP=...` 줄이
표준출력에 남는다(인상 판정 금지).

**Week 1 Gate(`test_week1_gate_closed_loop.py`)와 무엇이 다른가**
그 하네스는 *루프가 한 바퀴 도는가*(7단계 완주)를 봤고, 그 안에서 오답→숙달은 두 관측
(`mastery_updates` 응답 + `/v1/me/mastery/current` 스냅샷)으로 확인했다. 이 모듈이 더 보는 것은
**중간 두 구간과 이벤트 일치**다:
  - *Assessment* — 정답 여부가 숙달로 직행한 게 아니라 `AssessmentEvidence`(개념·스킬·오개념
    3종)를 **경유**했는가. Week 1은 evidence를 한 번도 보지 않는다.
  - *Misconception* — 그 오답이 오개념 후보로 **식별되고 학습자 상태에 남았는가**.
  - *이벤트 일치* — 상태에 남은 값이 P-02 Event Trace에도 **같은 값으로** 있는가. 두 곳이
    어긋나면 KPI 2(State Integrity) 위반이므로 이 하네스는 그것을 미통과로 친다.

**시딩 경계(정직한 선언)**
Week 1과 같다 — *학습자 상태*는 단 한 줄도 직접 쓰지 않는다(전부 HTTP 부수효과). *저작 콘텐츠*
(concept·problem·problem_concept)만 ORM으로 심는다. 헬퍼는 Week 1 하네스에서 그대로 가져와
쓴다(재구현 0). 그 모듈이 바뀌면 여기는 조용히 통과하는 게 아니라 ImportError로 시끄럽게 깨진다.

**문항이 왜 `(x+2)^2`인가**
오개념 채널(`l4/misconception/answer_signature.py`)은 발문에서 *연산자를 포함한 최장 수식 토큰*을
lhs로 뽑아 학생 답을 rhs로 놓고, 그 등식이 카탈로그의 거짓형(`canonical_wrong_form`)을
인스턴스화했는지 SymPy로 본다. 원 문서 §7이 예시로 든 `(x+2)^2 → x²+4`가 카탈로그의
`distribution-over-power`(`(a+b)**2 = a**2 + b**2`)에 정확히 걸린다. 즉 이 픽스처는 임의의
오답이 아니라 **탐지 채널의 사정거리 안에 있는 오답**이고, 그 사정거리 밖 오답에서는 이 구간이
`ran_no_candidate`로 정직하게 비는 것이 정상이다(§ 변별력 대조군 테스트가 그것을 고정한다).

**판정 밖(원 문서 지시)**: AI 품질·오개념 탐지 정확도·UI는 보지 않는다. 연결성(전파·일치)만.
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
from whymath_backend.db.models.concept import Concept, ProblemConcept
from whymath_backend.db.models.problem import Problem
from whymath_backend.db.models.skill_node import SkillNode
from whymath_backend.schema.concept import Concept as ConceptSchema
from whymath_backend.schema.concept import ProblemConcept as ProblemConceptSchema
from whymath_backend.schema.enums import (
    BehaviorArea,
    ConceptLevel,
    ConceptRole,
    Curriculum,
    ReviewStatus,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem import Problem as ProblemSchema

pytestmark = pytest.mark.integration

# ── Week 1 게이트 하네스의 검증된 헬퍼 재사용 (재구현 0) ──────────────────────────
# 로그인(운영 OAuth 콜백 경로)·삭제권 정리·저작 콘텐츠 시딩·PG 도달성은 그쪽이 정본이다.
# 여기서 다시 쓰면 두 게이트가 *서로 다른 경로*를 재게 되고, 그러면 두 판정을 나란히 읽을 수
# 없다.
#
# 왜 `import test_week1_gate_closed_loop`이 아니라 경로 로딩인가: 이 저장소의 pytest는
# `--import-mode=importlib`이라 형제 테스트 모듈이 이름으로 임포트되지 않는다(bare import는
# ModuleNotFoundError — 2026-09-18 실측). 경로 로딩은 import 모드와 무관하게 성립한다.
#
# 이 결합은 **조용히 깨지지 않는다** — 그쪽이 헬퍼 이름을 바꾸면 아래 계약 검사가 수집 단계에서
# 이름을 지목하며 터진다. 판정 하네스가 *통과*하면서 낡는 경우가 없어야 한다.
_WEEK1_PATH = pathlib.Path(__file__).with_name("test_week1_gate_closed_loop.py")
#: 그쪽에서 빌려 쓰는 헬퍼 계약 — 하나라도 사라지면 수집 단계에서 실패한다.
_WEEK1_HELPERS = (
    "_add_all",
    "_cleanup_content",
    "_client",
    "_erase_learner",
    "_login",
    "_pg_reachable",
    "_settings",
)


def _load_week1_harness() -> ModuleType:
    """Week 1 하네스를 파일 경로로 적재하고 헬퍼 계약을 검사한다."""
    if not _WEEK1_PATH.exists():
        raise RuntimeError(
            f"Week 1 게이트 하네스가 없다: {_WEEK1_PATH}. 이 판정은 그 헬퍼를 재사용한다 — "
            "파일이 옮겨졌으면 이 경로를 함께 고친다."
        )
    spec = importlib.util.spec_from_file_location("_week1_gate_harness", _WEEK1_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Week 1 하네스 스펙 생성 실패: {_WEEK1_PATH}")
    module = importlib.util.module_from_spec(spec)
    # 적재 중 자기 참조 import를 대비해 먼저 등록한다(표준 패턴).
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    missing = [name for name in _WEEK1_HELPERS if not hasattr(module, name)]
    if missing:
        raise RuntimeError(
            f"Week 1 하네스의 헬퍼가 사라졌다: {missing}. 이 판정이 그 경로를 재사용하므로 "
            "이름이 바뀌면 여기도 함께 고쳐야 한다(조용한 표류 방지)."
        )
    return module


_W1 = _load_week1_harness()
_add_all = _W1._add_all
_cleanup_content = _W1._cleanup_content
_client = _W1._client
_erase_learner = _W1._erase_learner
_login = _W1._login
_pg_reachable = _W1._pg_reachable
_settings = _W1._settings


# 발문 — 오개념 채널이 lhs로 뽑을 수식을 담는다(원 문서 §7 예시 그대로).
_QUESTION_TEXT = "다음 식을 전개하시오: (x+2)^2"
# 학생 오답 — `(x+2)^2 = x^2+4`는 거짓이고 `(a+b)**2 = a**2+b**2` 거짓형을 인스턴스화한다.
_WRONG_ANSWER = "x^2+4"
# 사정거리 *밖* 오답 — 틀렸지만 어떤 거짓형도 인스턴스화하지 않는다(변별력 대조군).
_UNMATCHED_WRONG_ANSWER = "7"
# 이 픽스처가 걸리기를 기대하는 오개념 id(카탈로그 정본 값).
_EXPECTED_MISCONCEPTION = "distribution-over-power"
# 정답 비노출 검사 sentinel.
_ANSWER_SENTINEL = "WEEK2_GATE_ANSWER_DONOTLEAK"
# 개념에 붙이는 행동 스킬 id의 접두 — 스킬 증거 축이 채워지려면 해소 대상이 있어야 한다.
# **회차마다 다른 id를 쓴다**: `skill_node`의 PK는 skill_id이고 이 테이블은 학습자 축이 아니라
# 저작 콘텐츠라 `DELETE /v1/me`가 지우지 않는다. 고정 id로 두면 같은 잡의 두 테스트(본 판정 +
# 대조군)가 서로의 행과 PK 충돌을 낸다(2026-09-18 실측).
_SKILL_PREFIX = "skill.w2gate"


def _step(name: str, detail: str) -> None:
    """구간 통과를 표준출력에 남긴다 — 판정은 exit code, 경위는 이 줄들이 말한다."""
    print(f"WEEK2_GATE_STEP={name} :: {detail}")


def _concept(cid: uuid.UUID, code: str, skill_id: str) -> Concept:
    """개념 노드(저작 콘텐츠) — 스킬 증거 축을 위해 behavior_skills를 1건 붙인다."""
    return Concept.from_schema(
        ConceptSchema(
            concept_id=cid,
            code=code,
            name_ko="완전제곱식의 전개",
            level=ConceptLevel.세부개념,
            behavior_skills=[skill_id],
        )
    )


def _skill_node(skill_id: str) -> SkillNode:
    """행동 스킬 노드(저작 콘텐츠) — 스킬 증거 축이 성립하려면 이 행이 있어야 한다.

    `_assessed_skill_ids`는 `concept.behavior_skills` 배열 멤버십으로 `skill_node`를 조인하고
    `mastery_estimable=True`만 남긴다. 즉 개념에 스킬 **이름**만 적어 두면 증거가 나오지 않는다
    — 그 이름이 스킬 레지스트리에 실재하고 추정 가치 게이트를 통과해야 한다. 이것은 결함이
    아니라 설계다(이름 오타로 없는 스킬의 숙달을 만들지 않는다). 그래서 픽스처가 레지스트리
    행까지 심는다.
    """
    return SkillNode(
        skill_id=skill_id,
        name_ko="완전제곱식 전개하기",
        behavior_area=BehaviorArea.TRANSFORM,
        family="algebra",
        mastery_estimable=True,
        prerequisite_skill_ids=[],
        standard_codes=[],
        review_status="reviewed",
    )


def _problem(pid: uuid.UUID, suffix: str, difficulty: float) -> Problem:
    """자체생성 문항 — Week 1과 달리 `question_text`를 채운다(오개념 채널의 입력이다).

    `source_type=자체생성`이라 본문 보유가 법적으로 허용된다(검정교과서·평가원 출처였다면
    `question_text`가 비어 있어야 하고, 그러면 이 채널은 구조적으로 못 돈다 — 저작권 레일과
    탐지 사정거리가 같은 축에서 만난다).
    """
    return Problem.from_schema(
        ProblemSchema(
            problem_id=pid,
            source_type=SourceType.자체생성,
            review_status=ReviewStatus.approved,
            curriculum_version=Curriculum.REVISION_2022,
            valid_from_year=2022,
            subject=Subject.공통,
            unit_codes=[f"U-{suffix}"],
            difficulty_overall=difficulty,
            question_text=_QUESTION_TEXT,
            answer=_ANSWER_SENTINEL,
        )
    )


def _problem_concept(pid: uuid.UUID, cid: uuid.UUID) -> ProblemConcept:
    """문제↔개념 PRIMARY 매핑 — 오답의 책임귀속 축(오답은 PRIMARY에만 반증을 준다)."""
    return ProblemConcept.from_schema(
        ProblemConceptSchema(problem_id=pid, concept_id=cid, role=ConceptRole.PRIMARY)
    )


def _seed(cid: uuid.UUID, pid: uuid.UUID, sfx: str) -> tuple[str, str]:
    """저작 콘텐츠 시딩 — 게이트 구간 밖(원 문서가 허용한 전제). 개념 **코드**를 돌려준다.

    코드·스킬id를 돌려주는 이유가 판정과 직결된다: `LearnerState.mastery`는 concept **code**로
    키가 잡히고(`domain_abilities`·`recent_struggles`도 같다), `mastery_updates` 응답과
    트레이스는 concept **UUID**를 쓴다. 두 축을 섞으면 "상태에 값이 없다"는 거짓 미통과가
    난다(2026-09-18 실측 — 값은 있었고 내가 UUID로 찾았다).
    """
    code = f"UC.w2gate.{sfx}"
    skill_id = f"{_SKILL_PREFIX}.{sfx}"
    asyncio.run(_add_all(_skill_node(skill_id)))
    asyncio.run(_add_all(_concept(cid, code, skill_id)))
    asyncio.run(_add_all(_problem(pid, sfx, 3.0)))
    asyncio.run(_add_all(_problem_concept(pid, cid)))
    return code, skill_id


def _submit_wrong(client: Any, auth: dict[str, str], pid: uuid.UUID, answer: str) -> dict[str, Any]:
    """오답 1건 제출 — 201과 `is_correct=False`까지만 여기서 단언한다."""
    resp = client.post(
        "/v1/me/attempts",
        headers=auth,
        json={"problem_id": str(pid), "is_correct": False, "student_answer": answer},
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    assert body["is_correct"] is False, body
    return body


async def _delete_skill_node(skill_id: str) -> None:
    """이번 회차가 심은 스킬 레지스트리 행만 지운다(저작 콘텐츠 정리 — 학습자 축 아님)."""
    engine = create_async_engine(_settings().database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM skill_node WHERE skill_id = :sid"), {"sid": skill_id}
            )
    finally:
        await engine.dispose()


def _teardown(cid: uuid.UUID, pid: uuid.UUID, skill_id: str | None) -> None:
    """정리 — **학습자를 먼저** 지우고 그 다음 저작 콘텐츠를 지운다.

    순서가 중요하다: `problem_attempt`가 `problem`을 FK로 잡고 있어 학습자를 남긴 채 콘텐츠를
    지우면 `ForeignKeyViolationError`가 난다. 본문이 단언에서 실패해 `_erase_learner`에
    도달하지 못한 경우가 정확히 그 상황인데, 그때 정리가 터지면 **그 예외가 원래의 단언 실패를
    가린다** — 판정이 "무엇이 끊겼는가" 대신 "정리가 터졌다"를 보고하게 된다(2026-09-18 실측).
    그래서 정리는 본문 성패와 무관하게 여기서 한 번 더, 순서대로 돌린다(멱등).
    """
    try:
        with _client() as client:
            _erase_learner(client)
    finally:
        try:
            asyncio.run(_cleanup_content(problem_ids=[pid], concept_ids=[cid]))
        finally:
            if skill_id is not None:
                asyncio.run(_delete_skill_node(skill_id))


def _learner_state(client: Any, auth: dict[str, str]) -> dict[str, Any]:
    """LearnerState 단일 표면 스냅샷 — 전후 비교의 관측 지점."""
    resp = client.get("/v1/me/learner-state", headers=auth)
    assert resp.status_code == 200, resp.text
    state: dict[str, Any] = resp.json()
    return state


def test_week2_gate_wrong_answer_propagates_end_to_end() -> None:
    """Week 2 Gate 판정 — 오답 1건이 5구간을 관통하고 이벤트와 일치하는지."""
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 판정 불가(WHYMATH_DATABASE_URL 확인). 통과가 아니다.")

    # 레이트리미터 격리 — 같은 프로세스의 앞선 통합 테스트가 IP 버킷을 소진하면 이 판정의
    # 쓰기 호출이 429를 받는다(판정은 한도 계약을 재는 자리가 아니다).
    asyncio.run(reset_store())

    sfx = uuid.uuid4().hex[:8]
    cid = uuid.uuid4()
    pid = uuid.uuid4()
    # 시딩 *전에* 선언한다 — 시딩이 중간에 실패해도 정리가 이름을 알아야 지운다.
    skill_id: str | None = None

    try:
        code, skill_id = _seed(cid, pid, sfx)

        with _client() as client:
            _erase_learner(client)  # 선행 정리(멱등) — 지난 회차 잔여가 기준선을 깨지 않게.
            auth = _login(client)

            # ── 0) BEFORE 스냅샷 — 오답 투입 *전*의 LearnerState. ─────────────────────
            before = _learner_state(client, auth)
            assert (
                code not in before["mastery"]
            ), f"투입 전인데 이미 이 개념의 숙달이 있다 — 기준선이 오염됐다: {before['mastery']}"
            assert (
                _EXPECTED_MISCONCEPTION not in before["active_misconceptions"]
            ), f"투입 전인데 이미 그 오개념이 활성이다: {before['active_misconceptions']}"
            _step(
                "0-before-snapshot",
                f"mastery {len(before['mastery'])}건 · active_misconceptions="
                f"{before['active_misconceptions']} · skill_mastery {len(before['skill_mastery'])}건",
            )

            # ── 1) Attempt — 오답 1건 제출(정답 비노출도 같이 본다). ──────────────────
            problem = client.get(f"/v1/problems/{pid}", headers=auth)
            assert problem.status_code == 200, problem.text
            assert (
                _ANSWER_SENTINEL not in problem.text
            ), "학생 대면 문항 조회 응답에 정답이 노출됐다 — CLAUDE.md 금기."

            body = _submit_wrong(client, auth, pid, _WRONG_ANSWER)
            attempt_id = body["attempt_id"]
            assert attempt_id, body
            _step("1-attempt", f"POST /v1/me/attempts 201 · attempt_id={attempt_id}")

            # ── 2) Assessment — 숙달 직행이 아니라 Evidence를 경유했는가. ─────────────
            evidence = body["evidence"]
            assert evidence is not None, (
                "오답인데 응답에 evidence가 없다 — 채점이 Assessment 구간을 만들지 않았다. "
                "정답 여부로 숙달을 바로 만지는 경로였다면 여기가 끊긴 지점이다."
            )
            coverage = evidence["coverage"]
            concept_ev = {e["concept_id"]: e for e in evidence["concept_evidence"]}
            assert (
                str(cid) in concept_ev
            ), f"책임귀속(PRIMARY) 개념이 개념 증거에 없다: {list(concept_ev)}"
            assert (
                concept_ev[str(cid)]["direction"] == "refuting"
            ), f"오답인데 증거 방향이 반증이 아니다: {concept_ev[str(cid)]}"
            assert concept_ev[str(cid)]["role"] == ConceptRole.PRIMARY.value, concept_ev[str(cid)]
            skill_ids = {e["skill_id"] for e in evidence["skill_evidence"]}
            assert (
                skill_id in skill_ids
            ), f"개념의 행동 스킬이 스킬 증거로 해소되지 않았다: {skill_ids}"
            _step(
                "2-assessment",
                f"evidence 3종 filled={coverage['filled_kinds']}/3 · concept={coverage['concept']}"
                f"({coverage['concept_count']}) skill={coverage['skill']}({coverage['skill_count']}) "
                f"misconception={coverage['misconception']}({coverage['misconception_count']})",
            )

            # ── 3) Misconception — 그 오답이 오개념 후보로 식별됐는가. ────────────────
            assert coverage["misconception_scan"] == "ran_with_candidates", (
                f"오개념 훑기가 후보를 내지 못했다(scan={coverage['misconception_scan']}). "
                "not_run이면 훑지도 않은 것이고(재료 부족·킬스위치), ran_no_candidate면 훑었으나 "
                "이 픽스처가 사정거리를 벗어난 것이다 — 어느 쪽이든 이 구간이 끊긴 지점이다."
            )
            candidates = {c["misconception_id"]: c for c in evidence["possible_misconceptions"]}
            assert (
                _EXPECTED_MISCONCEPTION in candidates
            ), f"기대 오개념이 후보에 없다: {list(candidates)}"
            cand = candidates[_EXPECTED_MISCONCEPTION]
            assert cand["gate_passed"] is True, cand
            assert 0.0 < cand["confidence"] <= 1.0, cand
            _step(
                "3-misconception",
                f"{_EXPECTED_MISCONCEPTION} confidence={cand['confidence']} "
                f"gate_passed={cand['gate_passed']}",
            )

            # ── 4) Mastery — 증거가 숙달 갱신으로 이어졌는가. ─────────────────────────
            updates = {u["concept_id"]: u for u in body["mastery_updates"]}
            assert str(cid) in updates, (
                f"증거는 나왔는데 숙달 갱신 목록에 그 개념이 없다 — Assessment→Mastery가 "
                f"끊겼다: {list(updates)}"
            )
            skill_updates = {u["skill_id"] for u in body["skill_mastery_updates"]}
            assert (
                skill_id in skill_updates
            ), f"스킬 증거는 나왔는데 스킬 숙달이 갱신되지 않았다: {skill_updates}"
            _step(
                "4-mastery",
                f"concept {cid} mastery={updates[str(cid)]['mastery']} "
                f"sample_size={updates[str(cid)]['sample_size']} · skill {skill_id} 갱신",
            )

            # ── 5) LearnerState — AFTER 스냅샷이 BEFORE와 *다른가*. ───────────────────
            after = _learner_state(client, auth)
            assert code in after["mastery"], (
                f"응답은 갱신을 말했는데 LearnerState에 그 개념이 없다 — 쓰기가 조회 표면에 "
                f"도달하지 않았다(부분 쓰기): {after['mastery']}"
            )
            assert (
                before["mastery"] != after["mastery"]
            ), "LearnerState의 mastery가 전후 동일하다 — 오답 1건이 상태를 바꾸지 못했다."
            assert _EXPECTED_MISCONCEPTION in after["active_misconceptions"], (
                f"오개념 후보가 학습자 상태에 남지 않았다 — Misconception→LearnerState가 "
                f"끊겼다: {after['active_misconceptions']}"
            )
            assert (
                skill_id in after["skill_mastery"]
            ), f"스킬 숙달이 LearnerState에 없다: {after['skill_mastery']}"
            state_mastery = after["mastery"][code]
            _step(
                "5-learner-state",
                f"mastery {len(before['mastery'])}건→{len(after['mastery'])}건 · "
                f"{code}={state_mastery} · active_misconceptions "
                f"{before['active_misconceptions']}→{after['active_misconceptions']}",
            )

            # ── 6) 이벤트 일치 — 상태의 그 값이 P-02 Event Trace에도 같은 값으로 있는가. ─
            trace = client.get("/v1/me/learning-trace", headers=auth)
            assert trace.status_code == 200, trace.text
            trace_body = trace.json()
            assert (
                trace_body["truncated"] is False
            ), "트레이스가 limit에 잘렸다 — 잘린 결과로 부재를 판정하면 안 된다."
            entries = trace_body["entries"]
            by_type: dict[str, list[dict[str, Any]]] = {}
            for entry in entries:
                by_type.setdefault(entry["event_type"], []).append(entry)

            # ⓐ `problem_attempt` 축 — 시도 자체가 시간선에 실렸는가.
            attempted = [
                e
                for e in by_type.get("problem_attempted", [])
                if e["attempt_id"] == attempt_id and e["source"] == "problem_attempt"
            ]
            assert (
                attempted
            ), f"방금 제출한 attempt가 트레이스에 없다 — 이벤트 기록이 끊겼다: {list(by_type)}"
            assert attempted[0]["correct"] is False, attempted[0]

            # ⓑ `attempt_event` 축 — **독립 원천**이다. ⓐ만 보면 이 축이 통째로 죽어도 판정이
            # 통과한다(2026-09-18 뮤테이션 M6 생존으로 실측). `attempt_event`의 물리 타입
            # `문제시도`는 트레이스에서 `problem_attempted`가 아니라 `skills_resolved`로 실리고,
            # `problem_attempted`는 `problem_attempt` 테이블이 낸다 — 이름이 비슷해 헷갈리는
            # 자리이고, 그래서 여기서는 `source`까지 못박는다.
            resolved = [
                e
                for e in by_type.get("skills_resolved", [])
                if e["attempt_id"] == attempt_id and e["source"] == "attempt_event"
            ]
            assert resolved, (
                f"`attempt_event`(문제시도) 이벤트가 없다 — 상태는 바뀌었는데 행동 이벤트가 "
                f"남지 않았다(KPI 2 위반): {list(by_type)}"
            )
            detail = resolved[0]["detail"] or {}
            assert (
                detail.get("is_correct") is False
            ), f"이벤트의 정오답이 상태와 어긋난다 — state=오답 event={detail}"
            assert detail.get("source") == "attempt_submit", detail

            mastery_events = [
                e
                for e in by_type.get("mastery_updated", [])
                if e["concept_id"] == str(cid) and e["mastery_change"] is not None
            ]
            assert mastery_events, (
                f"숙달이 바뀌었는데 mastery_updated 이벤트가 없다 — 상태와 이벤트가 어긋났다"
                f"(KPI 2 위반): {list(by_type)}"
            )
            change = mastery_events[-1]["mastery_change"]
            # KPI 2 — 상태에 남은 값과 이벤트에 남은 값이 **같아야** 한다.
            assert change["mastery_after"] == pytest.approx(state_mastery), (
                f"상태와 이벤트의 숙달값이 다르다 — State Integrity 위반: "
                f"state={state_mastery} event_after={change['mastery_after']}"
            )
            assert (
                change["is_first_measurement"] is True
            ), f"첫 측정인데 first_measurement가 아니다: {change}"
            assert (
                change["mastery_before"] is None
            ), f"첫 측정인데 before가 0.0으로 접혔다(None≠0 규약 위반): {change}"

            misc_events = [
                e
                for e in by_type.get("misconception_detected", [])
                if e["misconception_id"] == _EXPECTED_MISCONCEPTION
            ]
            assert misc_events, (
                f"오개념이 상태에 남았는데 misconception_detected 이벤트가 없다 — 상태와 "
                f"이벤트가 어긋났다(KPI 2 위반): {list(by_type)}"
            )
            _step(
                "6-event-consistency",
                f"trace {len(entries)}건 · problem_attempted={len(attempted)}(problem_attempt) · "
                f"skills_resolved={len(resolved)}(attempt_event) · "
                f"mastery_updated before={change['mastery_before']}→after={change['mastery_after']} "
                f"(state={state_mastery} 일치) · misconception_detected="
                f"{len(misc_events)}",
            )

            _erase_learner(client)

        print(
            "WEEK2_GATE=PASS :: Attempt→Assessment→Misconception→Mastery→LearnerState 전 구간 "
            "전파 + 이벤트 일치"
        )
    finally:
        _teardown(cid, pid, skill_id)


def test_misconception_step_assertion_is_discriminating() -> None:
    """음성 대조군 — 사정거리 *밖* 오답에서는 3구간이 후보를 내지 않는다.

    이게 없으면 3구간 단언이 "무엇을 넣어도 통과"인지 알 수 없다. 같은 문항·같은 오답 여부인데
    답안만 거짓형을 인스턴스화하지 않는 값으로 바꾸면 `ran_no_candidate`가 나와야 한다 —
    *훑었고(=채널은 살아 있고) 후보가 없다*는 3상태의 가운데 값이다. 이것이 `not_run`으로
    나오면 채널이 아예 안 돈 것이므로 본 판정의 통과도 신뢰할 수 없다.
    """
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 판정 불가. 통과가 아니다.")
    asyncio.run(reset_store())

    sfx = uuid.uuid4().hex[:8]
    cid = uuid.uuid4()
    pid = uuid.uuid4()
    skill_id: str | None = None

    try:
        _, skill_id = _seed(cid, pid, sfx)  # 대조군은 code 축을 쓰지 않는다
        with _client() as client:
            _erase_learner(client)
            auth = _login(client)
            body = _submit_wrong(client, auth, pid, _UNMATCHED_WRONG_ANSWER)
            evidence = body["evidence"]
            assert evidence is not None, body
            scan = evidence["coverage"]["misconception_scan"]
            assert scan == "ran_no_candidate", (
                f"사정거리 밖 오답인데 scan={scan}이다. ran_with_candidates면 채널이 아무 "
                f"오답이나 잡는 것이고(변별력 0), not_run이면 채널이 안 돈 것이다 — 어느 쪽이든 "
                f"본 판정의 3구간 단언은 증거가 되지 못한다: {evidence['possible_misconceptions']}"
            )
            assert evidence["possible_misconceptions"] == [], evidence["possible_misconceptions"]
            # 숙달 축은 여전히 움직여야 한다 — 오개념이 안 잡혀도 오답은 오답이다.
            assert body["mastery_updates"], body
            _erase_learner(client)
        print(f"WEEK2_GATE_CONTROL=OK :: 사정거리 밖 오답 scan={scan} · 후보 0건 · 숙달은 갱신")
    finally:
        _teardown(cid, pid, skill_id)
