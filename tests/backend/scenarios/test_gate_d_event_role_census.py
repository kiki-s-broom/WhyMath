"""Phase 3 Release Gate D — 학습 이벤트 8종 **실세션 기록** 역할 대조 (P3-13).

원 문서가 요구하는 이벤트 8종이 *카탈로그에 이름으로 있는가*가 아니라, 학생 한 명이 공개 HTTP
표면만으로 학습 장면을 지나갈 때 **시간선에 실제 행으로 남는가**를 잰다. 시딩 경계는 시나리오
스위트(`test_phase2_scenario_regression_suite.py`)와 같다 — 학습자 상태는 한 줄도 직접 쓰지 않고
(전부 HTTP 부수효과), 저작 콘텐츠(concept·problem)만 ORM으로 심는다.

────────────────────────────────────────────────────────────────────────────
이름 대조가 아니라 **역할 대조**다 (acceptance ②)
────────────────────────────────────────────────────────────────────────────
저장소 카탈로그(`l2/learning_event_trace.TraceEventType`)에서 원 문서 8종 중 2종은 이름이 다르다.
이름으로 grep하면 0건이라 "2종 미구현"이라는 오판정이 나는 자리다. 그래서 `GATE_D_ROLES`가 역할 →
카탈로그 이름들의 **매핑표**를 쥔다(개명하지 않는다 — 지시문 1번).

    learning_started  ← diagnostic_started · learner_state_created
    concept_viewed    ← concept_selected · content_viewed

────────────────────────────────────────────────────────────────────────────
정직한 공백 동결 — 역할은 대응돼도 **실세션에서 약한** 두 마디
────────────────────────────────────────────────────────────────────────────
카탈로그 대응(8/8)은 "이름이 있다"의 판정이다. 실세션을 지나 보면 두 곳이 더 약하다:

  ⓐ `concept_viewed` — 대응 이벤트 2종 중 `content_viewed`는 생산자가 0건(DORMANT)이다(소유
     `P3-29` — 새 테이블이 필요해 이월). `concept_selected`는 **P3-27에서 승격**됐다: 세션 writer가
     그 묶음에서 처음 확인된 문항의 대표 개념을 `learning_session.target_concept_id`에 채워, "어느
     개념을 봤는가"를 시간선이 말한다(값의 의미는 '목표 개념'이 아니라 '첫 확인 개념'이다).
  ⓑ `content_version` — 추적 필드 6종 중 이 하나는 봉투(`LearningEvent`)에 슬롯이 없다.
     `problem_attempt`에 `problem_version_id`가 없어(`EOS-47` todo) 투영할 원천도 없다.
     현재 `problem.problem_version_id`는 *지금의 서빙 판 포인터*라 시도 시점의 판이 아니므로,
     그 값으로 채우면 날조다(그래서 채우지 않고 부재로 동결한다).

추적 필드의 귀속도 같은 규약이다(P3-27 ②): 숙달 변경은 `attempt_id`로 시도를 되짚어 문항·세션을
싣는다(승격). 코치 도중 이벤트(힌트 요청·응답 지연)는 시도가 아직 없어 세션 귀속의 원천이 없고 —
`attempt_event`에 세션 컬럼이 없다 — 보강하려면 스키마가 필요해 `P3-30`이 소유한다(동결 유지).
오개념 가설은 학습자×오개념 누적 단위라 문항·세션 귀속이 구조적으로 정의되지 않는다(N/A).

남은 공백(ⓐ의 content_viewed·ⓑ·코치 이벤트 세션 귀속)은 `skip`으로 위장하지 않는다. *현행 동작*을 단언하고, 고쳐지면 그 단언이 실패하며 메시지가
소유 태스크를 가리킨다(시나리오 스위트의 "정직한 공백 동결" 규약과 같다).

**테스트 계정 기준** — 이 판정은 내부 테스트 계정(운영 OAuth 콜백 경로로 로그인한 합성 학생)의
세션이다. 실사용자 검증으로 계상하지 않는다(ARCH-66 ⑥ · 게이트 G-student-work-after-internal-
completion 판정 이후로 연기).

회귀 주입(기록을 끊으면 이 테스트가 RED인가) = `scripts/ops/verify_gate_de_discrimination.py`.
판정 문서 = `docs/reviews/p3_13_gate_d_e_recheck_2026-10-09.md`.
"""

from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import sys
import uuid
from collections.abc import Mapping
from types import ModuleType
from typing import Any, Final

import pytest

from whymath_backend.db.models.problem import Problem
from whymath_backend.l2.learning_event_trace import (
    LearningEvent,
    SourceAvailability,
    TraceEventType,
    source_registry,
)
from whymath_backend.l2.next_problem_selection import MAX_ADMINISTERED_ITEMS
from whymath_backend.schema.enums import Curriculum, ReviewStatus, SourceType, Subject
from whymath_backend.schema.problem import Problem as ProblemSchema

pytestmark = pytest.mark.integration

#: 원 문서 Gate D 이벤트 8종 → 저장소 카탈로그 이름. **개명하지 않고 매핑표로 처리**한다.
GATE_D_ROLES: Final[Mapping[str, tuple[TraceEventType, ...]]] = {
    "learning_started": (
        TraceEventType.DIAGNOSTIC_STARTED,
        TraceEventType.LEARNER_STATE_CREATED,
    ),
    "concept_viewed": (TraceEventType.CONCEPT_SELECTED, TraceEventType.CONTENT_VIEWED),
    "problem_attempted": (TraceEventType.PROBLEM_ATTEMPTED,),
    "answer_submitted": (TraceEventType.ANSWER_SUBMITTED,),
    "misconception_detected": (TraceEventType.MISCONCEPTION_DETECTED,),
    "hint_requested": (TraceEventType.HINT_REQUESTED,),
    "mastery_updated": (TraceEventType.MASTERY_UPDATED,),
    "recommendation_generated": (TraceEventType.RECOMMENDATION_GENERATED,),
}

#: 원 문서 지시 2번의 추적 필드 6종 → `LearningEvent` 필드명. `content_version`은 슬롯이 없다(ⓑ).
TRACKING_FIELDS: Final[Mapping[str, str | None]] = {
    "learner_id": "learner_id",
    "session_id": "session_id",
    "concept_id": "concept_id",
    "problem_id": "problem_id",
    "timestamp": "occurred_at",
    "content_version": None,
}

#: 코치 완료 경로가 쓰지 않는 단순 문항의 정답(수치) — 이 테스트는 코치 *완료*가 아니라 *대화*만 본다.
_ANSWER_DEMAND = "그냥 정답 알려줘"
_FOLLOW_UP = "아직 잘 모르겠어요. 다음엔 뭘 봐요?"


# ── 시나리오 스위트의 검증된 조립기 재사용 (재구현 0) ────────────────────────────────────
_SUITE_PATH = pathlib.Path(__file__).resolve().parent / "test_phase2_scenario_regression_suite.py"
_SUITE_HELPERS = (
    "_UNMATCHED_WRONG_ANSWER",
    "_WRONG_ANSWER",
    "_EXPECTED_MISCONCEPTION",
    "_add_all",
    "_attempt",
    "_begin",
    "_client",
    "_erase_learner",
    "_get",
    "_login",
    "_next_problem",
    "_problem_concept",
    "_seed_concept",
    "_seed_problems",
    "_trace",
    "_user_id",
)


def _load_suite() -> ModuleType:
    """시나리오 스위트를 파일 경로로 적재하고 헬퍼 계약을 검사한다(조용한 표류 방지)."""
    if not _SUITE_PATH.exists():
        raise RuntimeError(f"시나리오 스위트가 없다: {_SUITE_PATH}. 경로를 함께 고친다.")
    spec = importlib.util.spec_from_file_location("_gate_d_scenario_suite", _SUITE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"시나리오 스위트 스펙 생성 실패: {_SUITE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    missing = [name for name in _SUITE_HELPERS if not hasattr(module, name)]
    if missing:
        raise RuntimeError(f"시나리오 스위트의 헬퍼가 사라졌다: {missing}.")
    return module


_S = _load_suite()


def _coach_problem(content: Any, cid: uuid.UUID, tag: str) -> uuid.UUID:
    """코치 대화용 문항 1종(저작 콘텐츠) — 대화만 볼 것이라 정답 형식은 중요하지 않다."""
    pid = uuid.uuid4()
    asyncio.run(
        _S._add_all(
            Problem.from_schema(
                ProblemSchema(
                    problem_id=pid,
                    source_type=SourceType.자체생성,
                    review_status=ReviewStatus.approved,
                    curriculum_version=Curriculum.REVISION_2022,
                    valid_from_year=2022,
                    subject=Subject.공통,
                    unit_codes=[f"U-{content.sfx}{tag}"],
                    difficulty_overall=3.0,
                    question_text=f"3x = 12 일 때 x의 값을 구하시오. ({tag})",
                    answer="4",
                )
            )
        )
    )
    asyncio.run(_S._add_all(_S._problem_concept(pid, cid)))
    content.problem_ids.append(pid)
    return pid


def _entries_of(
    entries: list[dict[str, Any]], names: tuple[TraceEventType, ...]
) -> list[dict[str, Any]]:
    wanted = {n.value for n in names}
    return [e for e in entries if e["event_type"] in wanted]


def _fill(entries: list[dict[str, Any]], field: str | None) -> tuple[int, int]:
    """(채워진 행 수, 전체 행 수) — `content_version`처럼 슬롯이 없는 필드는 (0, 전체)."""
    if field is None:
        return 0, len(entries)
    return sum(1 for e in entries if e.get(field) is not None), len(entries)


def test_gate_d_eight_event_roles_recorded_in_a_real_student_session() -> None:
    """한 학생의 실세션이 원 문서 이벤트 8종의 **역할**을 시간선에 남긴다.

    장면: 추천 → 오개념을 일으키는 오답 반복 → 진단 확정 → 코치에게 답을 요구 → 이어지는 질문.
    판정:
      ① 8역할 전부 대응 이벤트가 **1건 이상** 기록됐다(`concept_viewed`만 ⓐ 단서 — 아래).
      ② 기록된 모든 행이 이 학습자의 것이고 시각이 있다(`learner_id`·`timestamp` 필수 축).
      ③ 역할별 계약 필드 — 시도는 문항·시도 포인터, 오개념은 id, 숙달은 개념과 전후 값, 추천은
         세션과 문항, 힌트 요청은 문항.
      ④ ⓐ·ⓑ 정직한 공백이 현행 그대로다(고쳐지면 이 단언이 실패하고 소유 태스크를 가리킨다).
    """
    content, _journal = _S._begin("GATE-D")
    try:
        cid, _code = _S._seed_concept(content, "gd", "일차방정식의 풀이")
        graded = _S._seed_problems(
            content, cid, "gd", [2.4 + 0.05 * i for i in range(MAX_ADMINISTERED_ITEMS)]
        )
        coach_pid = _coach_problem(content, cid, "gdc")

        with _S._client() as client:
            _S._erase_learner(client)
            auth = _S._login(client)
            uid = _S._user_id(client, auth)

            # 추천 — recommendation_generated · learner_state_created · (세션 개시) concept_selected
            first = _S._next_problem(client, auth)
            assert first["problem_id"], first

            # 오답 반복 — 앞 2건은 오개념 서명이 잡히는 거짓형, 나머지는 사정거리 밖 오답.
            for index, pid in enumerate(graded):
                answer = _S._WRONG_ANSWER if index < 2 else _S._UNMATCHED_WRONG_ANSWER
                _S._attempt(client, auth, pid, correct=False, answer=answer)

            # 진단 확정 — diagnostic_started(+completed)
            captured = client.post("/v1/me/assessments/capture", headers=auth)
            assert captured.status_code == 200, captured.text
            assert captured.json()["written"] is True, captured.json()

            # 코치 — 답 요구 발화(hint_requested) → 이어지는 턴(answer_submitted: 응답 지연 이벤트)
            opened = client.post(
                "/v1/coach/sessions",
                headers=auth,
                json={"student_input": _ANSWER_DEMAND, "problem_id": str(coach_pid)},
            )
            assert opened.status_code == 201, opened.text
            did = opened.json()["dialogue_id"]
            follow = client.post(
                f"/v1/coach/sessions/{did}/turns",
                headers=auth,
                json={"student_input": _FOLLOW_UP},
            )
            assert follow.status_code == 201, follow.text

            body = _S._get(client, auth, "/v1/me/learning-trace")
            assert body["truncated"] is False, "잘린 결과로 판정하지 않는다."
            entries: list[dict[str, Any]] = body["entries"]
            coverage = {c["event_type"]: c for c in body["coverage"]}

            # ── 역할별 실측표 — 판정의 근거(stdout에 남겨 판정 문서가 인용한다) ──────────────────
            print("\n=== Gate D 이벤트 8종 — 실세션 역할 대조 (테스트 계정 기준) ===")
            observed_by_role: dict[str, list[dict[str, Any]]] = {}
            for role, names in GATE_D_ROLES.items():
                rows = _entries_of(entries, names)
                observed_by_role[role] = rows
                # 이름별로 따로 센다 — 역할 단위로 합치면 이름마다 다른 채움이 평균에 묻힌다.
                for name in names:
                    named = _entries_of(entries, (name,))
                    fills = {
                        tf: "{}/{}".format(*_fill(named, lf)) for tf, lf in TRACKING_FIELDS.items()
                    }
                    pointer = "{}/{}".format(*_fill(named, "attempt_id"))
                    print(
                        f"ROLE={role} :: NAME={name.value} :: 건수={len(named)} :: 채움={fills}"
                        f" :: 시도포인터(attempt_id)={pointer}"
                    )

            # ① 8역할 전부 기록됐다. 역할당 "하나라도"가 아니라 **생산 중(PRODUCED)인 대응 이름
            #    전부**를 요구한다 — 하나만 보면 `learning_started`는 `diagnostic_started`를 끊어도
            #    `learner_state_created`가 가려 보호가 위장된다(주입으로 확인한 사각). 생산자가 없는
            #    이름(`content_viewed` — DORMANT)은 요구에서 빼고 ④ⓐ가 따로 동결한다.
            absent: list[str] = []
            for role, names in GATE_D_ROLES.items():
                required = [n for n in names if coverage[n.value]["availability"] == "produced"]
                assert required, f"{role}: 생산 중인 대응 이벤트가 하나도 없다(역할 미충족)."
                absent += [f"{role}→{n.value}" for n in required if not _entries_of(entries, (n,))]
            assert absent == [], f"실세션에서 한 건도 기록되지 않은 역할 대응 이벤트: {absent}"

            # ② 모든 행이 이 학습자의 것이고 시각이 있다.
            for role, rows in observed_by_role.items():
                for row in rows:
                    assert row["learner_id"] == str(uid), (role, row)
                    assert row["occurred_at"], (role, row)

            # ③ 역할별 계약 필드.
            for row in observed_by_role["problem_attempted"]:
                assert row["problem_id"] and row["attempt_id"], row
            for row in observed_by_role["misconception_detected"]:
                assert row["misconception_id"], row
            attempts_by_id = {r["attempt_id"]: r for r in observed_by_role["problem_attempted"]}
            assert attempts_by_id, "시도가 하나도 없으면 아래 귀속 대조가 공허하게 통과한다."
            for row in observed_by_role["mastery_updated"]:
                assert row["concept_id"] == str(cid), row
                assert row["mastery_change"] is not None, row
                # P3-27 ②: 숙달 변경이 어느 시도에서 왔는지 — 채워졌다는 것만이 아니라 **그 시도의
                # 문항·세션과 같은가**를 본다(엉뚱한 시도에 붙은 값은 비어 있는 것보다 나쁘다).
                source_attempt = attempts_by_id.get(row["attempt_id"])
                assert source_attempt is not None, (
                    "숙달 변경이 시도에 귀속되지 않는다(attempt_id 누락·불일치) — 트레이스의 시도 귀속 "
                    "투영(P3-27 ②)이 끊겼다.",
                    row,
                )
                assert row["problem_id"] == source_attempt["problem_id"], (
                    "숙달 변경의 문항이 그 시도의 문항과 다르다.",
                    row,
                    source_attempt,
                )
                assert row["session_id"] == source_attempt["session_id"], (
                    "숙달 변경의 세션이 그 시도의 세션과 다르다.",
                    row,
                    source_attempt,
                )
            for row in _entries_of(entries, (TraceEventType.RECOMMENDATION_GENERATED,)):
                assert row["session_id"] and row["problem_id"], row
            for row in observed_by_role["hint_requested"]:
                assert row["problem_id"] == str(coach_pid), row

            # ④ⓐ concept_viewed — content_viewed는 생산자 0건, concept_selected는 개념을 싣지 않는다.
            assert _entries_of(entries, (TraceEventType.CONTENT_VIEWED,)) == [], (
                "content_viewed가 기록되기 시작했다 — 콘텐츠 열람 로그 좌석이 생긴 것으로 보인다. "
                "이 단언을 '콘텐츠 열람이 개념·문항을 싣는다'로 승격하라(소유 P3-29)."
            )
            assert coverage[TraceEventType.CONTENT_VIEWED.value]["availability"] == (
                SourceAvailability.DORMANT.value
            ), coverage[TraceEventType.CONTENT_VIEWED.value]
            # concept_selected — P3-27 승격: 세션 개시 행이 **첫 확인 개념**을 싣는다. 이 장면은 첫
            # 활동이 추천 조회(문항 선택 전이라 개념 미상 → NULL로 열림)이고 이후 시도가 개념을 알려
            # 주므로, HTTP 경로 전체에서 NULL→값 채움까지 함께 본다.
            selected = _entries_of(entries, (TraceEventType.CONCEPT_SELECTED,))
            assert selected, "세션 개시(concept_selected)가 한 건도 없다 — 승격 단언이 공허하다."
            assert all(row["concept_id"] == str(cid) for row in selected), (
                "concept_selected가 첫 확인 개념을 싣지 않는다 — 세션 writer의 개념 채움(P3-27)이 "
                "끊겼다(시도·코치 턴이 문항을 실어 오는데 target_concept_id가 비어 있다).",
                selected,
            )

            # ④ⓒ 코치 도중 이벤트의 세션 귀속 — 현행 공백 동결(소유 P3-30). 시도가 아직 없어
            #     attempt_id도 없고, attempt_event에 세션 컬럼이 없다. 고쳐지면 이 단언이 깨진다.
            for coach_event in (TraceEventType.HINT_REQUESTED, TraceEventType.ANSWER_SUBMITTED):
                for row in _entries_of(entries, (coach_event,)):
                    assert row["session_id"] is None and row["attempt_id"] is None, (
                        f"{coach_event.value}가 세션·시도에 귀속되기 시작했다 — 이 단언을 '코치 도중 "
                        "이벤트가 세션을 싣는다'로 승격하라(소유 P3-30).",
                        row,
                    )

            # ④ⓑ content_version — 봉투에 슬롯이 없다(시도 시점의 판을 기록하는 원천이 없다).
            assert "content_version" not in LearningEvent.model_fields, (
                "LearningEvent에 content_version이 생겼다 — 이 단언을 '모든 행이 시도 시점의 판을 "
                "싣는다'로 승격하라(소유 태스크 EOS-47-attempt-version-pinning)."
            )
            assert all("content_version" not in e for e in entries)

            _S._erase_learner(client)
    finally:
        content.teardown()


def test_coach_first_activity_opens_the_session_with_the_problem_concept() -> None:
    """코치가 첫 활동인 학생 — 세션이 그 문항의 개념으로 열리고 `concept_selected`가 개념을 싣는다.

    위 8역할 시나리오는 첫 활동이 추천 조회라 세션이 개념 없이 열리고 시도가 채운다. 이 테스트는 그
    반대 경로를 본다: 문항이 붙은 코치 대화가 **세션을 여는 첫 활동**일 때 writer가 코치 호출처의
    `problem_id`로 개념을 해석해 열린 세션에 싣는지(P3-27). 코치 호출처의 전달 여부는 AST 테스트가
    전수로 보고, 이 테스트는 그 값이 실제로 개념까지 도달하는 동작을 본다.
    """
    content, _journal = _S._begin("GATE-D-COACH")
    try:
        cid, _code = _S._seed_concept(content, "gc", "일차방정식의 풀이")
        coach_pid = _coach_problem(content, cid, "gcc")

        with _S._client() as client:
            _S._erase_learner(client)
            auth = _S._login(client)
            opened = client.post(
                "/v1/coach/sessions",
                headers=auth,
                json={"student_input": _ANSWER_DEMAND, "problem_id": str(coach_pid)},
            )
            assert opened.status_code == 201, opened.text

            body = _S._get(client, auth, "/v1/me/learning-trace")
            selected = _entries_of(body["entries"], (TraceEventType.CONCEPT_SELECTED,))
            assert len(selected) == 1, f"세션 개시가 정확히 1건이어야 한다: {selected}"
            assert selected[0]["concept_id"] == str(cid), (
                "코치가 연 세션이 문항의 개념을 싣지 않는다 — 코치 호출처의 problem_id 전달 또는 "
                "writer의 개념 채움(P3-27)이 끊겼다.",
                selected,
            )
            _S._erase_learner(client)
    finally:
        content.teardown()


def test_gate_d_role_table_matches_the_repository_catalog() -> None:
    """`GATE_D_ROLES`가 가리키는 이름이 전부 카탈로그에 실재한다 — 매핑표가 허공을 가리키지 않는다.

    이름 대조의 반대 방향 가드다: 카탈로그에서 이벤트 이름이 개명·삭제되면 이 테스트가 매핑표를
    지목하며 깨진다(하드웨어가 아니라 *역할 대응표*가 낡았다는 뜻이다).
    """
    registered = {c.event_type for c in source_registry()}
    for role, names in GATE_D_ROLES.items():
        assert names, role
        for name in names:
            assert name in registered, f"{role} → {name.value}가 원천 대장에 없다."
    # 스캔 0건은 실패다 — 8역할이 비어 있으면 위 루프가 공허하게 통과한다.
    assert len(GATE_D_ROLES) == 8
