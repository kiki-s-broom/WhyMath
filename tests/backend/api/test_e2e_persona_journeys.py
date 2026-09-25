"""계획서 300 Phase 2 §11 **페르소나 3종 완주** 하네스 — 대표 학습자 3인이 끝까지 도는가.

집행 지시문 `P-15`("페르소나 3종 안정화")의 판정 자리다. 새 엔진을 추가하지 않고, 이미 있는
공개 HTTP 표면만으로 세 여정을 각각 **끝까지** 돌린 뒤 단계별 LearnerState 변화를 표로 남긴다.

    Persona A 정상 학습자   진단 → 학습 → 문제 → 대부분 정답 → mastery 상승 → 다음 concept
    Persona B 선수학습 결손 진단 → 문제 → 반복 오답 → prerequisite gap → 하위 concept
                            → 보정 → **원래 concept 복귀**
    Persona C 특정 오개념   진단 → 문제 → 특정 오답 패턴 → misconception detection
                            → corrective explanation → targeted problem
                            → misconception confidence **감소**

**판정 포인트 2종(원 지시문이 못박은 것)**
- `B`는 하위 concept에서 **멈추면 미통과**다. 그래서 이 하네스는 보정을 마친 시점에 선수 개념
  문항을 **일부러 미시도로 남겨 둔다** — 추천이 그때도 선수 문항을 집으면 복귀가 아니라 정체다.
  즉 "복귀했다"가 *후보 고갈의 부산물*이 아니라 **선택**이었음이 구별된다.
- `C`는 confidence가 실제로 **내려가야** 통과다. 올라가기만 하면 보정이 작동하지 않은 것이다.
  그래서 감소는 *여정 전체의 차이*가 아니라 **targeted problem 한 회차의 전후 차이**로 잰다 —
  그 앞의 코치 대화도 감쇠를 일으키므로, 구간을 좁히지 않으면 무엇이 내렸는지 구별되지 않는다.

**시딩 경계(정직한 선언)** — Week 1·2·3 게이트와 같다. *학습자 상태*는 단 한 줄도 직접 쓰지
않는다(전부 HTTP 부수효과). *저작 콘텐츠*(concept·atom_node·concept_edge·problem·
problem_concept·skill_node)만 ORM으로 심는다. 헬퍼는 Week 1·2 하네스에서 그대로 빌려 쓴다
(재구현 0) — 그쪽이 이름을 바꾸면 여기는 조용히 통과하지 않고 수집 단계에서 이름을 지목하며 깨진다.

**`atom_node`를 왜 심는가(실측 사유)**: `/v1/me/weak-concepts/{cid}/prerequisites`는 선수 후보를
`atom_node`(code 조인)의 안전 메타와 함께 돌려준다. 그 행이 없으면 엣지가 있어도 응답이
**빈 배열**이 된다(2026-09-19 실측 — 처음엔 엣지만 심어 `[]`를 받았고, 그것은 "선수가 없다"가
아니라 "메타가 없다"였다). 픽스처가 그 행까지 심어야 B 여정이 실제로 그 경로를 지나간다.

**판정 밖** — AI 답변 품질·교정 발화의 교수학적 적절성·추천 품질은 보지 않는다(연결성과
수치 방향만). 연속 3루프(계획서 §18)·SCENARIO-001~010(§16)은 이 하네스의 범위가 아니다
(각각 `PED-36` ⑫ — `test_e2e_three_consecutive_loops.py` · `EOS-119` 소유). 연속 3루프 하네스는
이 파일의 조립기를 경로 로딩으로 재사용하므로, 여기서 헬퍼 이름을 바꾸면 그쪽이 수집 단계에서
이름을 지목하며 깨진다.

**정직한 공백 동결** — 아래는 *현행 동작*을 단언한다. 고쳐지면 이 테스트가 실패하며, 실패
메시지가 승계 태스크 id를 가리킨다(조용히 낡지 않게).
  ⓐ `EOS-123` — 정답 제출은 오개념 감쇠 시계를 돌리지 않는다(`apply_candidates` 미호출).

**해소된 공백 — `EOS-124`(정책 축·선택 축 불일치)**: 이 하네스가 2026-09-19에 두 자리(A ⑤-b ·
B ⑧-b)에서 동결했던 불일치 — 숙달한 개념 문항에 `advance_next`가 붙고, 선수 결손이 해소된
뒤에도 원래 개념 문항에 `practice_prerequisite`가 붙던 것 — 는 기본 CAT 정책이 설명을 전달
문항에 정렬하면서 해소됐다. 두 자리는 **올바른 값 단언으로 승격**됐다(A는 다음 개념 문항을
*선택*으로 받고, B는 복귀 문항에 맞는 `practice_current`를 받는다).
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

from whymath_backend.api._rate_limit import reset_store
from whymath_backend.db.models.atom_node import AtomNode
from whymath_backend.db.models.concept import ConceptEdge
from whymath_backend.db.models.pedagogy_dsl import LearningObjective, UnitSpec
from whymath_backend.schema.concept import ConceptEdge as ConceptEdgeSchema
from whymath_backend.schema.enums import EdgeType, KnowledgeType

pytestmark = pytest.mark.integration


# ── Week 1·2 게이트 하네스의 검증된 조립기 재사용 (재구현 0) ──────────────────────
# 경로 로딩인 이유는 그쪽 docstring과 같다 — 이 저장소의 pytest는 `--import-mode=importlib`이라
# 형제 테스트 모듈이 이름으로 임포트되지 않는다.
_WEEK2_PATH = pathlib.Path(__file__).with_name("test_week2_gate_wrong_answer_propagation.py")
#: 빌려 쓰는 헬퍼 계약 — 하나라도 사라지면 수집 단계에서 실패한다(조용한 표류 방지).
_WEEK2_HELPERS = (
    "_EXPECTED_MISCONCEPTION",
    "_UNMATCHED_WRONG_ANSWER",
    "_WRONG_ANSWER",
    "_add_all",
    "_cleanup_content",
    "_client",
    "_concept",
    "_erase_learner",
    "_learner_state",
    "_login",
    "_pg_reachable",
    "_problem",
    "_problem_concept",
    "_settings",
    "_skill_node",
)


def _load_week2_harness() -> ModuleType:
    """Week 2 하네스를 파일 경로로 적재하고 헬퍼 계약을 검사한다."""
    if not _WEEK2_PATH.exists():
        raise RuntimeError(
            f"Week 2 게이트 하네스가 없다: {_WEEK2_PATH}. 이 판정은 그 픽스처 조립기를 "
            "재사용한다 — 파일이 옮겨졌으면 이 경로를 함께 고친다."
        )
    spec = importlib.util.spec_from_file_location("_persona_week2_harness", _WEEK2_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Week 2 하네스 스펙 생성 실패: {_WEEK2_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    missing = [name for name in _WEEK2_HELPERS if not hasattr(module, name)]
    if missing:
        raise RuntimeError(
            f"Week 2 하네스의 헬퍼가 사라졌다: {missing}. 이 판정이 그 조립기를 재사용하므로 "
            "이름이 바뀌면 여기도 함께 고쳐야 한다."
        )
    return module


_W2 = _load_week2_harness()
# EOS-126 중단 규칙 2종의 상수 — 테스트가 값을 복제하지 않고 소스에서 읽는다(상한을 바꾸면
# 단언과 픽스처가 함께 따라간다).
from whymath_backend.l2.next_problem_selection import (  # noqa: E402
    MAX_ADMINISTERED_ITEMS as _MAX_ADMINISTERED_ITEMS,
)
from whymath_backend.l2.next_problem_selection import TARGET_SE as _TARGET_SE  # noqa: E402

_EXPECTED_MISCONCEPTION = _W2._EXPECTED_MISCONCEPTION
_UNMATCHED_WRONG_ANSWER = _W2._UNMATCHED_WRONG_ANSWER
_WRONG_ANSWER = _W2._WRONG_ANSWER
_add_all = _W2._add_all
_cleanup_content = _W2._cleanup_content
_client = _W2._client
_concept = _W2._concept
_erase_learner = _W2._erase_learner
_learner_state = _W2._learner_state
_login = _W2._login
_pg_reachable = _W2._pg_reachable
_problem = _W2._problem
_problem_concept = _W2._problem_concept
_settings = _W2._settings
_skill_node = _W2._skill_node


# ── 픽스처 조립기 (이 하네스 고유분) ─────────────────────────────────────────────


def _atom(code: str, name_ko: str) -> AtomNode:
    """원자 축 안전 메타(code PK) — 선수 조회가 이 행과 조인한다(모듈 docstring 참조)."""
    return AtomNode(
        code=code,
        name_ko=name_ko,
        level="세부개념",
        subject_area="대수",
        review_status="reviewed",
    )


def _prereq_edge(from_id: uuid.UUID, to_id: uuid.UUID) -> ConceptEdge:
    """선수 엣지 — from(선수)이 to(후행)의 선수."""
    return ConceptEdge.from_schema(
        ConceptEdgeSchema(
            from_concept_id=from_id,
            to_concept_id=to_id,
            edge_type=EdgeType.PREREQUISITE.value,
            edge_strength=0.9,
        )
    )


# ── 여정 기록 ───────────────────────────────────────────────────────────────────


class _Journal:
    """단계별 LearnerState 변화 기록 — 지시문 1번("표로 제시")의 산출물.

    판정은 exit code로 나온다. 이 표는 *왜 그렇게 판정됐는지*를 말하는 자리이고, 미통과일 때
    어느 마디에서 끊겼는지를 사람이 읽을 수 있게 한다(인상 판정 금지 — 표는 근거이지 판정이 아니다).
    """

    def __init__(self, persona: str) -> None:
        self.persona = persona
        self.rows: list[dict[str, Any]] = []

    def record(self, step: str, detail: str, **state: Any) -> None:
        row = {"step": step, "detail": detail, **state}
        self.rows.append(row)
        rendered = " · ".join(f"{k}={v}" for k, v in state.items())
        print(f"PERSONA_{self.persona}_STEP={step} :: {detail} :: {rendered}")

    def dump(self) -> None:
        print(f"\n=== Persona {self.persona} — LearnerState 변화표 ===")
        for i, row in enumerate(self.rows, start=1):
            head = f"{i:>2}. {row['step']}"
            body = " · ".join(f"{k}={v}" for k, v in row.items() if k not in ("step", "detail"))
            print(f"{head:<34} | {body}")
            print(f"{'':<34} | ↳ {row['detail']}")


# ── 관측 헬퍼 (공개 HTTP 표면만) ─────────────────────────────────────────────────


def _get(client: Any, auth: dict[str, str], url: str) -> Any:
    resp = client.get(url, headers=auth)
    assert resp.status_code == 200, (url, resp.status_code, resp.text[:400])
    return resp.json()


def _attempt(
    client: Any, auth: dict[str, str], pid: uuid.UUID, *, correct: bool, answer: str
) -> dict[str, Any]:
    """시도 1건 제출 — 학습자 상태를 움직이는 유일한 쓰기 경로(ORM 직접 쓰기 0)."""
    resp = client.post(
        "/v1/me/attempts",
        headers=auth,
        json={"problem_id": str(pid), "is_correct": correct, "student_answer": answer},
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    assert body["is_correct"] is correct, body
    return body


def _mastery_of(client: Any, auth: dict[str, str], cid: uuid.UUID) -> float | None:
    """개념 숙달 현재값 — 미측정이면 None(0.0과 구별한다)."""
    for row in _get(client, auth, "/v1/me/mastery/current"):
        if row["concept_id"] == str(cid):
            value = row["mastery"]
            return None if value is None else float(value)
    return None


def _hypothesis_confidence(client: Any, auth: dict[str, str], mid: str) -> float | None:
    """누적 오개념 가설의 confidence — 본인 반출권 표면에서 읽는다.

    이 값을 읽는 공개 표면은 둘뿐이다: 코치 응답의 `active_hypotheses`와 이 반출이다
    (`/v1/me/learner-state`는 **id만** 주고 confidence는 주지 않는다 — 2026-09-19 실측).
    코치 응답은 *그 호출이 가설을 움직인 뒤*의 값이라 전후 비교의 관측점으로 쓸 수 없으므로,
    이 하네스는 부수효과가 없는 반출을 관측점으로 삼는다.
    """
    payload = _get(client, auth, "/v1/me/export")
    rows = payload.get("data", {}).get("misconception_hypotheses") or []
    for row in rows:
        if row.get("misconception_id") == mid:
            value = row.get("confidence")
            return None if value is None else float(value)
    return None


def _next_problem(client: Any, auth: dict[str, str], *, weak_first: bool = True) -> dict[str, Any]:
    suffix = "?prioritize_weak_concepts=true" if weak_first else ""
    body: dict[str, Any] = _get(client, auth, f"/v1/me/next-problem{suffix}")
    return body


def _state_of(attempt_body: dict[str, Any]) -> str | None:
    """학습 상태 머신이 이 시도로 도달한 상태 — 시도 응답이 유일한 노출 지점이다.

    `/v1/me/learner-state`는 숙달·능력·활성 오개념을 주지만 **상태 머신의 상태 이름은 주지
    않는다**(생산자가 시도 경로에만 있다 — 2026-09-19 실측). 그래서 여정 표의 '상태' 열은
    조회가 아니라 그 회차 시도의 산출물에서 읽는다.
    """
    state = attempt_body.get("learning_state")
    if not state:
        return None
    value: str | None = state.get("to_state")
    return value


def _misconceptions(client: Any, auth: dict[str, str]) -> list[str]:
    """활성 오개념 id 목록 — `/v1/me/learner-state`는 id만 주고 confidence는 주지 않는다."""
    ids: list[str] = _learner_state(client, auth).get("active_misconceptions") or []
    return ids


# ── 시딩·정리 ───────────────────────────────────────────────────────────────────


class _Content:
    """이번 회차가 심은 저작 콘텐츠의 명세 — 정리가 이름을 알아야 지운다.

    시딩 *전에* 만들고, 중간에 실패해도 `teardown`이 심은 만큼만 멱등하게 지운다.
    """

    def __init__(self, sfx: str) -> None:
        self.sfx = sfx
        self.concept_ids: list[uuid.UUID] = []
        self.problem_ids: list[uuid.UUID] = []
        self.skill_ids: list[str] = []
        self.atom_codes: list[str] = []
        #: 학습 단위 공급 좌석이 요구하는 목표·단원(§A-진단확정 여정만 쓴다).
        self.objective_ids: list[str] = []
        self.unit_ids: list[str] = []

    def teardown(self) -> None:
        """**학습자를 먼저** 지우고 그 다음 저작 콘텐츠를 지운다.

        순서가 중요하다: `problem_attempt`가 `problem`을 FK로 잡고 있어 학습자를 남긴 채
        콘텐츠를 지우면 `ForeignKeyViolationError`가 나고, 그 예외가 **원래의 단언 실패를
        가린다**(판정이 "어디서 끊겼는가" 대신 "정리가 터졌다"를 보고하게 된다 — Week 2
        하네스가 같은 사고를 겪고 남긴 교훈이다).
        """
        try:
            with _client() as client:
                _erase_learner(client)
        finally:
            try:
                asyncio.run(_cleanup_content(problem_ids=self.problem_ids, concept_ids=[]))
            finally:
                try:
                    asyncio.run(_drop_objectives(self.objective_ids, self.unit_ids))
                finally:
                    asyncio.run(_drop_graph(self.concept_ids, self.skill_ids, self.atom_codes))


async def _drop_graph(
    concept_ids: list[uuid.UUID], skill_ids: list[str], atom_codes: list[str]
) -> None:
    """개념 그래프·스킬 레지스트리·원자 메타 정리(저작 콘텐츠 — 학습자 축 아님).

    `_cleanup_content`(Week 1 정본)는 concept_edge·skill_node·atom_node를 모르므로 그 셋만
    여기서 지운다. 엣지를 먼저 지워야 개념 삭제가 FK로 막히지 않는다.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(_settings().database_url)
    cids = [str(c) for c in concept_ids]
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM concept_edge "
                    "WHERE from_concept_id = ANY(:ids) OR to_concept_id = ANY(:ids)"
                ),
                {"ids": cids},
            )
            await conn.execute(
                text("DELETE FROM concept WHERE concept_id = ANY(:ids)"), {"ids": cids}
            )
            await conn.execute(
                text("DELETE FROM skill_node WHERE skill_id = ANY(:ids)"), {"ids": skill_ids}
            )
            await conn.execute(
                text("DELETE FROM atom_node WHERE code = ANY(:codes)"), {"codes": atom_codes}
            )
    finally:
        await engine.dispose()


async def _drop_objectives(objective_ids: list[str], unit_ids: list[str]) -> None:
    """학습목표·단원 스펙 정리 — 목표가 단원을 복합 FK로 잡으므로 목표를 먼저 지운다."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    if not objective_ids and not unit_ids:
        return
    engine = create_async_engine(_settings().database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM learning_objective WHERE id = ANY(:ids)"),
                {"ids": objective_ids},
            )
            await conn.execute(
                text("DELETE FROM unit_spec WHERE unit_id = ANY(:ids)"), {"ids": unit_ids}
            )
    finally:
        await engine.dispose()


def _seed_objective(content: _Content, code: str) -> str:
    """학습 단위 공급 좌석이 요구하는 단원 스펙 1 + 학습목표 1을 심고 목표 id를 돌려준다.

    **이 행이 없으면 진단 게이트에 닿지 못한다.** `post_study_unit`은 목표 로드(부재 시 404)를
    `require_learner_state`(부재 시 409)보다 *먼저* 하므로, 목표를 안 심으면 학습자 상태와
    무관하게 404가 나고 "진단이 안 끝나서 막혔다"와 "목표가 없어서 막혔다"가 구별되지 않는다
    (2026-09-19 실측 — 이 마디의 초판이 그 상태로 차단 사유를 *추론*만 하고 있었다).
    """
    unit_id = f"U.persona.{content.sfx}"
    objective_id = f"OBJ.persona.{content.sfx}"
    asyncio.run(
        _add_all(
            UnitSpec(
                unit_id=unit_id,
                unit_version=1,
                api_version="v1",
                title="페르소나 여정 판정용 단원",
                curriculum_rev="2022",
                standard_codes=["[10공수1-01-01]"],
                concept_nodes=[code],
                yaml_sha256="0" * 64,
                compiler_ver="v1",
            )
        )
    )
    asyncio.run(
        _add_all(
            LearningObjective(
                id=objective_id,
                unit_id=unit_id,
                unit_version=1,
                statement="페르소나 여정 판정용 학습목표",
                achievement_std="[10공수1-01-01]",
                k_type=KnowledgeType.CONCEPT,
                concept_nodes=[code],
                slot_manifest={},
                exit_evidence={},
            )
        )
    )
    content.unit_ids.append(unit_id)
    content.objective_ids.append(objective_id)
    return objective_id


def _seed_concept(content: _Content, tag: str, name_ko: str) -> tuple[uuid.UUID, str]:
    """개념 1종(개념 + 원자 메타 + 행동 스킬)을 심고 `(concept_id, code)`를 돌려준다.

    스킬 id를 회차마다 다르게 두는 이유는 Week 2 하네스와 같다 — `skill_node`는 학습자 축이
    아니라 저작 콘텐츠라 `DELETE /v1/me`가 지우지 않는다. 고정 id면 같은 잡의 두 테스트가
    서로의 행과 PK 충돌을 낸다.
    """
    cid = uuid.uuid4()
    code = f"UC.persona.{content.sfx}.{tag}"
    skill_id = f"skill.persona.{content.sfx}.{tag}"
    asyncio.run(_add_all(_skill_node(skill_id)))
    asyncio.run(_add_all(_concept(cid, code, skill_id)))
    asyncio.run(_add_all(_atom(code, name_ko)))
    content.concept_ids.append(cid)
    content.skill_ids.append(skill_id)
    content.atom_codes.append(code)
    return cid, code


def _seed_problems(
    content: _Content, cid: uuid.UUID, tag: str, difficulties: list[float]
) -> list[uuid.UUID]:
    """한 개념에 붙는 자체생성 문항 n종 — 난이도를 서로 다르게 준다.

    난이도를 벌리는 이유: 추천은 θ 근방 최근접을 고르므로 같은 난이도면 어느 쪽이 나올지
    결정론이 아니다. 이 하네스의 판정은 "어느 *개념*의 문항인가"이지 "몇 번 문항인가"가
    아니지만, 단계별 단언이 흔들리지 않게 후보를 구별 가능하게 만든다.
    """
    pids: list[uuid.UUID] = []
    for i, difficulty in enumerate(difficulties):
        pid = uuid.uuid4()
        asyncio.run(_add_all(_problem(pid, f"{content.sfx}{tag}{i}", difficulty)))
        asyncio.run(_add_all(_problem_concept(pid, cid)))
        content.problem_ids.append(pid)
        pids.append(pid)
    return pids


def _provisioned_by(client: Any, auth: dict[str, str]) -> str | None:
    """이 학생의 `learner_state` 행이 **무엇 때문에** 생겼는지 — 없으면 None.

    읽기 전용 SELECT다(Week 1 하네스 `_fetch_all`과 같은 규약 — 읽기는 "DB 직접 수정"이
    아니므로 판정에 허용된다). 공개 표면으로는 볼 수 없는 값이라 행을 직접 읽는다.
    """
    # `GET /v1/me`는 없다(`DELETE`만 — 2026-09-21 라우터 실측). 본인 user_id를 내는 공개
    # 표면은 반출권 export다(`UserDataExport.user_id`).
    user_id = uuid.UUID(_get(client, auth, "/v1/me/export")["user_id"])

    async def _read() -> str | None:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(_settings().database_url)
        try:
            async with engine.begin() as conn:
                row = (
                    await conn.execute(
                        text("SELECT provisioned_by FROM learner_state WHERE learner_id = :lid"),
                        {"lid": str(user_id)},
                    )
                ).first()
            return None if row is None else str(row[0])
        finally:
            await engine.dispose()

    return asyncio.run(_read())


def _begin(persona: str) -> tuple[_Content, _Journal]:
    """회차 시작 — PG 도달성 확인·레이트리미터 격리·식별자 발급."""
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 판정 불가(WHYMATH_DATABASE_URL 확인). 통과가 아니다.")
    # 같은 프로세스의 앞선 통합 테스트가 IP 버킷을 소진하면 이 여정의 쓰기 호출이 429를
    # 받는다(판정은 한도 계약을 재는 자리가 아니다).
    asyncio.run(reset_store())
    return _Content(uuid.uuid4().hex[:8]), _Journal(persona)


# ── Persona A — 정상 학습자 ─────────────────────────────────────────────────────


def test_persona_a_normal_learner_masters_concept_and_advances() -> None:
    """A: 진단 → 학습 → 문제 → 대부분 정답 → mastery 상승 → 다음 concept.

    완주 판정은 마지막 마디다 — 숙달이 오른 것만으로는 "다음 concept"이 아니다. 그래서 현재
    개념에도 **미시도 문항을 남겨 둔 채** 추천을 부른다. 추천이 그때 다음 개념을 고르면 이동은
    후보 고갈의 부산물이 아니라 선택이다.
    """
    content, journal = _begin("A")
    try:
        c_cur, _ = _seed_concept(content, "a-cur", "일차식의 전개")
        c_next, _ = _seed_concept(content, "a-next", "이차식의 전개")
        asyncio.run(_add_all(_prereq_edge(c_cur, c_next)))
        cur_pids = _seed_problems(content, c_cur, "ac", [2.0, 2.4, 2.8, 3.2, 3.6, 4.0])
        next_pids = _seed_problems(content, c_next, "an", [4.0, 4.4])

        with _client() as client:
            _erase_learner(client)  # 지난 회차 잔여 제거 — 기준선이 "신규 학습자"여야 한다
            auth = _login(client)

            # ① 진단 — 아직 아무 측정도 없다(미측정과 숙달 0을 구별해 기록한다).
            first = _next_problem(client, auth)
            journal.record(
                "①진단",
                "신규 학습자 — 측정 이력 0",
                문항=first["problem_id"] is not None,
                action=first["action"],
                reason=first["reason"]["type"],
                숙달=_mastery_of(client, auth, c_cur),
            )
            assert (
                first["problem_id"] is not None
            ), "진단 문항이 나오지 않으면 여정이 시작되지 않는다."
            assert _mastery_of(client, auth, c_cur) is None, "시작 전 숙달은 *미측정*이어야 한다."

            # ② 학습·문제 — 첫 정답으로 측정이 생긴다(기준선).
            first_ok = _attempt(client, auth, cur_pids[0], correct=True, answer="정답1")
            baseline = _mastery_of(client, auth, c_cur)
            journal.record(
                "②첫정답",
                "측정 개시",
                숙달=baseline,
                상태=_state_of(first_ok),
                활성오개념=_misconceptions(client, auth),
            )
            assert baseline is not None, "정답 1건 뒤에도 숙달이 미측정이면 전파가 끊긴 것이다."

            # ③ 대부분 정답 — 3문항 중 2정답 1오답(“대부분”이지 전부가 아니다).
            _attempt(client, auth, cur_pids[1], correct=True, answer="정답2")
            wrong = _attempt(client, auth, cur_pids[2], correct=False, answer="오답")
            dip = _mastery_of(client, auth, c_cur)
            journal.record(
                "③오답1건", "숙달이 내려간다(방향 확인)", 숙달=dip, 상태=_state_of(wrong)
            )
            _attempt(client, auth, cur_pids[3], correct=True, answer="정답3")
            last = _attempt(client, auth, cur_pids[4], correct=True, answer="정답4")
            mid = _mastery_of(client, auth, c_cur)
            journal.record("③대부분정답", "5회 중 4정답 1오답", 숙달=mid, 상태=_state_of(last))

            # ④ mastery 상승 — 방향이 판정이다(절대값이 아니라).
            assert mid is not None
            assert mid > baseline, (
                f"대부분 정답인데 숙달이 오르지 않았다: {baseline} → {mid}. "
                "A 여정의 네 번째 마디가 끊겼다."
            )
            journal.record("④숙달상승", f"{baseline} → {mid}", 상승폭=round(mid - baseline, 4))

            # ⑤ 다음 concept — 현재 개념에 미시도 문항(cur_pids[3])이 **남아 있는데도**
            #    추천이 다음 개념을 고르는지. 고르면 이동은 선택이다.
            advanced = _next_problem(client, auth)
            picked = advanced["problem_id"]
            journal.record(
                "⑤다음concept",
                f"현재개념 미시도 {cur_pids[5]} 남김",
                추천문항=picked,
                action=advanced["action"],
                target=advanced["target_concept"],
            )
            assert picked is not None, "다음 문항이 없으면 '다음 concept'을 판정할 수 없다."

            # ⑤-a 정책 축은 이동을 **말한다** — 숙달을 근거로 `advance_next`가 선다.
            assert advanced["action"] == "advance_next", (
                f"숙달 {mid}인데 추천 action이 {advanced['action']}이다 — 정책 축이 전진을 "
                "판정하지 못했다."
            )

            # ⑤-b 정책·선택 정렬 (`EOS-124` 해소 — 2026-09-19 동결을 승격) — 현재 개념에 미시도
            #      문항이 **남아 있는데도** 다음 개념 문항을 받는다. 즉 이동은 후보 고갈의 부산물이
            #      아니라 선택이다. 설명도 그 문항을 가리킨다: target은 다음 개념이고, 근거(reason)는
            #      "방금 숙달한 현재 개념"이다 — 전진의 이유와 전진의 목적지가 각자 제자리에 있다.
            assert picked in {str(x) for x in next_pids}, (
                f"숙달 {mid}인데 추천 문항 {picked}가 다음 개념 것이 아니다 — 정책은 전진을 "
                "말하는데 콘텐츠는 제자리다(`EOS-124` 재발)."
            )
            assert advanced["target_concept"] == str(c_next), (
                f"advance_next의 target이 {advanced['target_concept']}다 — 다음 개념이 아니면 "
                "설명이 받은 문항과 어긋난다(`EOS-124` 재발)."
            )
            assert advanced["reason"]["concept_id"] == str(c_cur), (
                "전진의 근거는 숙달한 현재 개념이어야 한다 — 근거가 다른 개념을 가리키면 "
                "'왜 넘어가는가'에 답하지 못한다."
            )
            assert advanced["reason"]["type"] == "next_concept"
            assert advanced["intent_resolution"] == "served", (
                f"intent_resolution={advanced['intent_resolution']} — 전진이 문항으로 실렸는데 "
                "관측값이 그것을 말하지 않으면 '정렬이 일한 비율'을 셀 수 없다."
            )
            journal.record(
                "⑤-b정책·선택정렬",
                "EOS-124 해소 — action은 전진, 문항·target도 다음 개념",
                action=advanced["action"],
                target=("다음개념" if advanced["target_concept"] == str(c_next) else "현재개념"),
                문항소속=("다음개념" if picked in {str(x) for x in next_pids} else "현재개념"),
                근거개념=("현재개념" if advanced["reason"]["concept_id"] == str(c_cur) else "기타"),
                해소=advanced["intent_resolution"],
            )

            # ⑥ 완주 — 현재 개념 문항까지 소진한 뒤에도 다음 개념에 머문다. ⑤-b가 이동이
            #    *선택*임을 이미 판정했으므로, 여기서 보는 것은 고갈 경로에서도 목적지가 같은가다
            #    (다음 개념이 미측정이면 진단 문항으로 나간다 — 행위는 diagnose, target은 다음 개념).
            _attempt(client, auth, cur_pids[5], correct=True, answer="정답5")
            drained = _next_problem(client, auth)
            journal.record(
                "⑥다음concept도달",
                "현재 개념 후보 소진 후",
                추천문항소속=(
                    "다음개념"
                    if drained["problem_id"] in {str(x) for x in next_pids}
                    else "현재개념"
                ),
                action=drained["action"],
                target=("다음개념" if drained["target_concept"] == str(c_next) else "현재개념"),
            )
            assert drained["problem_id"] in {str(x) for x in next_pids}, (
                f"현재 개념을 다 풀었는데도 다음 개념으로 가지 않았다(고른 문항 "
                f"{drained['problem_id']}). A 여정의 마지막 마디가 끊겼다."
            )
            assert drained["target_concept"] == str(c_next), "다음 개념이 target으로 서지 않았다."
        journal.dump()
    finally:
        content.teardown()


# ── Persona B — 선수학습 결손 ───────────────────────────────────────────────────


def test_persona_b_prerequisite_gap_remediates_and_returns_to_origin() -> None:
    """B: 반복 오답 → prerequisite gap → 하위 concept → 보정 → **원래 concept 복귀**.

    원 지시문이 못박은 대로 **하위 concept에서 멈추면 미통과**다. 그래서 보정을 마친 시점에
    선수 개념 문항을 하나 미시도로 남겨 둔다 — 추천이 그때도 선수 문항을 집으면 복귀가 아니라
    정체이고, 원래 개념 문항을 집으면 그것은 후보 고갈이 아니라 **선택**이다.
    """
    content, journal = _begin("B")
    try:
        c_pre, _ = _seed_concept(content, "b-pre", "일차방정식의 풀이")
        c_main, _ = _seed_concept(content, "b-main", "이차방정식의 풀이")
        asyncio.run(_add_all(_prereq_edge(c_pre, c_main)))
        # 난이도를 **겹쳐서** 준다 — 이것이 이 판정의 변별력 장치다.
        # 선수 문항을 쉽게, 원래 문항을 어렵게 두면 보정으로 θ가 오른 것만으로도 추천이
        # 원래 개념 쪽으로 밀린다. 그러면 "복귀"가 *결손 해소* 때문인지 *θ 상승* 때문인지
        # 구별되지 않는다(2026-09-19 실측 — 처음 픽스처가 2.0~2.8 대 4.0~4.8이었다).
        # 두 개념의 난이도 대역을 서로 물리면 θ는 둘을 가르지 못하고, 남는 축은 개념뿐이다.
        pre_pids = _seed_problems(content, c_pre, "bp", [4.0, 4.2, 4.4])
        main_pids = _seed_problems(content, c_main, "bm", [4.1, 4.3, 4.5])

        with _client() as client:
            _erase_learner(client)
            auth = _login(client)

            # ① 진단
            first = _next_problem(client, auth)
            journal.record(
                "①진단", "신규 학습자", action=first["action"], reason=first["reason"]["type"]
            )

            # ② 문제 → 반복 오답 (원래 개념)
            for i in range(3):
                body = _attempt(client, auth, main_pids[i % 2], correct=False, answer="9")
            journal.record(
                "②반복오답",
                "원래 개념 3회 오답",
                원래개념숙달=_mastery_of(client, auth, c_main),
                상태=_state_of(body),
            )
            weak = _get(client, auth, "/v1/me/weak-concepts")
            assert str(c_main) in {
                row["concept_id"] for row in weak
            }, "반복 오답 뒤에도 원래 개념이 약점으로 잡히지 않았다 — B 여정의 두 번째 마디가 끊겼다."

            # ③ prerequisite gap — 선수 후보가 보이는가(아직 측정 전이라 weakness는 미측정).
            seen = _get(
                client, auth, f"/v1/me/weak-concepts/{c_main}/prerequisites?weak_only=false"
            )
            journal.record(
                "③선수후보",
                "엣지·원자 메타를 타고 선수가 보인다",
                선수수=len(seen),
                weakness=(seen[0]["weakness"] if seen else None),
            )
            assert any(
                row["concept_id"] == str(c_pre) for row in seen
            ), "선수 개념이 조회되지 않았다 — 엣지 또는 원자 메타가 끊겼다(모듈 docstring 참조)."

            # ④ 결손 실증 — 선수 개념 오답 1건으로 weakness가 측정된다.
            _attempt(client, auth, pre_pids[0], correct=False, answer="9")
            gaps = _get(client, auth, f"/v1/me/weak-concepts/{c_main}/prerequisites")
            journal.record(
                "④결손확정",
                "선수 개념 오답 1건 — weak_only 필터를 통과한다",
                결손수=len(gaps),
                선수숙달=_mastery_of(client, auth, c_pre),
            )
            assert any(
                row["concept_id"] == str(c_pre) for row in gaps
            ), "선수 개념이 *결손*으로 분류되지 않았다 — 세 번째 마디가 끊겼다."

            # ⑤ 하위 concept 이동 — 추천이 선수 개념 문항을 준다.
            down = _next_problem(client, auth)
            journal.record(
                "⑤하위concept이동",
                "추천이 선수 개념으로 내려간다",
                action=down["action"],
                reason=down["reason"]["type"],
                문항소속=(
                    "선수개념" if down["problem_id"] in {str(x) for x in pre_pids} else "원래개념"
                ),
            )
            assert (
                down["action"] == "practice_prerequisite"
            ), f"추천 action이 {down['action']}이다 — 결손이 확정됐는데 선수 연습으로 라우팅되지 않았다."
            assert down["problem_id"] in {
                str(x) for x in pre_pids
            }, f"추천 문항 {down['problem_id']}가 선수 개념 것이 아니다 — 하위 concept 이동이 말뿐이다."
            # EOS-124 — 설명도 콘텐츠와 맞아야 한다: 목표는 받은 문항의 개념(선수)이고, 근거는
            # "원래 개념이 막혔다"이다. 종전에는 선수 문항 자신의 숙달로 근거를 대고 목표가 우연히
            # 맞았다(선수의 선수가 없어 폴백) — 여기서 그 우연이 아니라 이유를 판정한다.
            assert down["target_concept"] == str(
                c_pre
            ), f"선수 연습인데 target이 {down['target_concept']}다 — 받은 선수 문항과 어긋난다."
            assert down["reason"]["concept_id"] == str(c_main), (
                "선수로 내려간 근거는 막힌 원래 개념이어야 한다 — 선수 자신을 근거로 대면 "
                "'왜 이 선수인가'에 답하지 못한다."
            )
            assert down["intent_resolution"] == "served"

            # ⑥ 보정 — 선수 개념을 정답으로 메운다. pre_pids[2]는 **미시도로 남긴다**.
            for i in range(6):
                _attempt(client, auth, pre_pids[i % 2], correct=True, answer="정답")
            pre_after = _mastery_of(client, auth, c_pre)
            journal.record("⑥보정", "선수 개념 6회 정답", 선수숙달=pre_after)
            assert (
                pre_after is not None and pre_after > 0.7
            ), f"보정했는데 선수 숙달이 {pre_after}다 — 네 번째 마디가 끊겼다."

            # ⑦ 결손 해소 — weak_only 필터에서 사라진다.
            cleared = _get(client, auth, f"/v1/me/weak-concepts/{c_main}/prerequisites")
            journal.record("⑦결손해소", "weak_only 필터 통과 0건", 잔여결손=len(cleared))
            assert not any(
                row["concept_id"] == str(c_pre) for row in cleared
            ), "보정 후에도 선수가 결손으로 남아 있다 — 복귀 조건이 서지 않는다."

            # ⑧ **원래 concept 복귀** — 선수 개념에 미시도 문항이 남아 있는데도 원래 개념을 고른다.
            back = _next_problem(client, auth)
            picked = back["problem_id"]
            journal.record(
                "⑧원래concept복귀",
                f"선수 미시도 {pre_pids[2]} 남김 — 그런데도 원래 개념을 고른다",
                추천문항소속=("원래개념" if picked in {str(x) for x in main_pids} else "선수개념"),
                미시도선수존재=True,
            )
            assert picked in {str(x) for x in main_pids}, (
                f"복귀하지 않았다 — 고른 문항 {picked}는 원래 개념 문항이 아니다. "
                "하위 concept에서 멈췄다면 B 여정 미통과다(원 지시문 3번)."
            )

            # ⑧-b 정책·선택 정렬 (`EOS-124` 해소 — 2026-09-19 동결을 승격) — 문항이 복귀했으면
            #      *설명*도 복귀해야 한다. 선수가 1.0으로 숙달됐으므로 "선수를 연습하라"는 측정이
            #      반증한 설명이고, 받은 것은 원래 개념 문항이다 → 원래 개념 연습(practice_current).
            #      원래 개념 숙달은 여전히 낮다 — 그 수치는 근거에 **그대로** 실린다(강등은 행위를
            #      콘텐츠에 맞추는 것이지 측정을 고치는 것이 아니다).
            assert back["action"] == "practice_current", (
                f"복귀 후 action이 {back['action']}다 — 선수 결손이 해소됐는데 선수 연습을 말하면 "
                "설명이 받은 문항과 어긋난다(`EOS-124` 재발)."
            )
            assert back["target_concept"] == str(
                c_main
            ), f"복귀 후 target이 {back['target_concept']}다 — 받은 문항은 원래 개념 것이다."
            assert back["reason"]["concept_id"] == str(c_main)
            assert back["reason"]["type"] == "current_concept"
            assert (
                back["reason"]["mastery"] is not None and back["reason"]["mastery"] < 0.4
            ), "원래 개념의 실측 숙달이 근거에 그대로 실려야 한다 — 강등이 수치를 바꾸면 위장이다."
            assert back["intent_resolution"] == "refuted", (
                f"intent_resolution={back['intent_resolution']} — 선수가 측정으로 숙달이 확인된 "
                "경우는 '근거 없음'이 아니라 '반증'이다(모른다 ≠ 아니다)."
            )
            journal.record(
                "⑧-b정책·선택정렬",
                "EOS-124 해소 — 문항·action·target 모두 원래 개념(선수 결손은 측정이 반증)",
                action=back["action"],
                target=("원래개념" if back["target_concept"] == str(c_main) else "선수개념"),
                해소=back["intent_resolution"],
            )
        journal.dump()
    finally:
        content.teardown()


# ── Persona C — 특정 오개념 ─────────────────────────────────────────────────────

#: 교정 대화에 실어 보내는 학생 풀이 — 오개념 거짓형 `(a+b)^2 = a^2+b^2`를 그대로 쓴다.
_MISCONCEPTION_SOLUTION = "(x+2)^2 = x^2+4"
#: 단계 검증용 풀이 단계(거짓 전이 1개 — `solution_step_types` 길이는 len(steps)-1).
_MISCONCEPTION_STEPS = ["(x+2)^2", "x^2+4"]


def test_persona_c_misconception_confidence_declines_after_targeted_problem() -> None:
    """C: 특정 오답 패턴 → detection → corrective explanation → targeted problem → confidence **감소**.

    판정 포인트는 마지막 마디의 **방향**이다(원 지시문 2번). 올라가기만 하면 보정이 작동하지
    않은 것이다. 그래서 감소를 *여정 전체의 차이*가 아니라 **targeted problem 한 회차의 전후
    차이**로 잰다 — 그 앞의 교정 대화도 감쇠를 일으키므로, 구간을 좁히지 않으면 무엇이 내렸는지
    구별되지 않는다(변별력).

    **감소가 실제로 일어나는 자리(실측)**: 감쇠 시계는 `POST /v1/me/attempts`가 오개념 훑기를
    *돌린* 회차에만 돈다. 그 회차의 후보가 비어 있어도 호출 자체는 유효하고, 그것이 "이번엔
    그 오개념이 관측되지 않았다"를 신뢰 하락으로 바꾸는 경로다. 그래서 targeted problem은
    **그 오개념을 인스턴스화하지 않는 오답**으로 제출한다.
    """
    content, journal = _begin("C")
    try:
        c_mis, _ = _seed_concept(content, "c-mis", "완전제곱식의 전개")
        pids = _seed_problems(content, c_mis, "cm", [3.0, 3.4, 3.8, 4.2])

        with _client() as client:
            _erase_learner(client)
            auth = _login(client)

            # ① 진단
            first = _next_problem(client, auth)
            journal.record(
                "①진단", "신규 학습자", action=first["action"], reason=first["reason"]["type"]
            )

            # ② 특정 오답 패턴 → misconception detection
            body = _attempt(client, auth, pids[0], correct=False, answer=_WRONG_ANSWER)
            candidates = [
                m["misconception_id"] for m in body["evidence"]["possible_misconceptions"]
            ]
            conf1 = _hypothesis_confidence(client, auth, _EXPECTED_MISCONCEPTION)
            journal.record(
                "②오답패턴→탐지",
                f"{_WRONG_ANSWER} 는 거짓형 (a+b)^2 = a^2+b^2 를 인스턴스화한다",
                후보=candidates,
                confidence=conf1,
                상태=_state_of(body),
                next_action=(body.get("learning_state") or {}).get("next_action"),
            )
            assert (
                _EXPECTED_MISCONCEPTION in candidates
            ), f"오개념이 탐지되지 않았다(후보 {candidates}) — C 여정의 두 번째 마디가 끊겼다."
            assert conf1 is not None, "탐지됐는데 누적 가설이 영속되지 않았다."
            assert (body.get("learning_state") or {}).get(
                "target_misconception_id"
            ) == _EXPECTED_MISCONCEPTION, "상태 머신이 교정 대상을 지목하지 못했다."

            # ③ 같은 패턴 반복 → confidence 강화(올라가는 방향을 먼저 확인한다).
            #    이 단계가 없으면 뒤의 '감소'가 *애초에 낮았던 값*과 구별되지 않는다.
            _attempt(client, auth, pids[1], correct=False, answer=_WRONG_ANSWER)
            conf2 = _hypothesis_confidence(client, auth, _EXPECTED_MISCONCEPTION)
            journal.record("③패턴반복", "같은 거짓형 재관측", confidence=conf2)
            assert conf2 is not None and conf2 > conf1, (
                f"같은 오개념을 다시 관측했는데 신뢰가 오르지 않았다: {conf1} → {conf2}. "
                "강화가 없으면 뒤의 감소 판정이 변별력을 잃는다."
            )

            # ④ corrective explanation — 교정 발화가 학생에게 돌아오는가.
            coached = client.post(
                "/v1/coach/sessions",
                headers=auth,
                json={
                    "student_input": "이렇게 풀었는데 확인해줘",
                    "student_solution": _MISCONCEPTION_SOLUTION,
                    "problem_id": str(pids[0]),
                    "solution_steps": _MISCONCEPTION_STEPS,
                    "solution_step_types": ["계산"],
                    "coaching_focus": "verify",
                },
            )
            assert coached.status_code == 201, coached.text
            cbody = coached.json()
            journal.record(
                "④교정발화",
                "코치가 오답 풀이에 교정 신호를 돌려준다",
                개입=(
                    (cbody.get("intervention") or {}).get("misconception_id")
                    if cbody.get("intervention")
                    else None
                ),
                활성가설수=len(cbody.get("active_hypotheses") or []),
                단계검증=bool((cbody.get("solution_coaching") or {}).get("solution_verification")),
            )
            assert (
                cbody.get("solution_coaching") is not None
            ), "거짓 풀이를 냈는데 교정 코칭이 없다 — C 여정의 네 번째 마디가 끊겼다."

            # ⑤ **targeted problem → confidence 감소** (판정 포인트)
            #    구간을 이 한 회차로 좁힌다 — 직전 값을 다시 읽고, 제출 후 값과 비교한다.
            conf_pre = _hypothesis_confidence(client, auth, _EXPECTED_MISCONCEPTION)
            _attempt(client, auth, pids[2], correct=False, answer=_UNMATCHED_WRONG_ANSWER)
            conf_post = _hypothesis_confidence(client, auth, _EXPECTED_MISCONCEPTION)
            journal.record(
                "⑤targeted→감소",
                f"교정 문항에서 그 오개념이 재관측되지 않음({_UNMATCHED_WRONG_ANSWER})",
                직전=conf_pre,
                직후=conf_post,
                감소폭=(
                    None
                    if conf_pre is None or conf_post is None
                    else round(conf_pre - conf_post, 4)
                ),
            )
            assert conf_pre is not None and conf_post is not None
            assert conf_post < conf_pre, (
                f"교정 문항 이후에도 오개념 신뢰가 내려가지 않았다: {conf_pre} → {conf_post}. "
                "원 지시문 2번 — 올라가기만 하면 보정이 작동하지 않은 것이다(C 여정 미통과)."
            )

            # ⑥ 정직한 공백 동결 (`EOS-123`) — *정답* 회차는 감쇠 시계를 돌리지 않는다.
            #    `_scan_attempt_misconceptions`가 correct=True에서 NOT_RUN을 돌려주고,
            #    호출부가 그 값으로 `apply_candidates`를 건너뛰기 때문이다. 즉 "교정 문항을
            #    맞혔다" 자체는 신뢰를 1도 깎지 못한다 — 같은 반증을 코치 경로는 반영하는데
            #    (clean verify + 무매치 → −1 증거) 채점 경로만 비대칭이다.
            _attempt(client, auth, pids[3], correct=True, answer="x^2+4x+4")
            conf_correct = _hypothesis_confidence(client, auth, _EXPECTED_MISCONCEPTION)
            journal.record(
                "⑥정답회차",
                "EOS-123 정직한 공백 — 정답은 감쇠 시계를 돌리지 않는다",
                직전=conf_post,
                직후=conf_correct,
            )
            assert conf_correct == conf_post, (
                f"정답 회차가 오개념 신뢰를 바꿨다: {conf_post} → {conf_correct}. "
                "`EOS-123`(정답 반증 비대칭)이 해소된 것으로 보인다 — 이 단언을 감소 단언으로 "
                "승격하고 EOS-123을 닫아라."
            )
        journal.dump()
    finally:
        content.teardown()


# ── Persona A 연장 — 진단 확정 → 학습 진입 ───────────────────────────────────────
#
# 위 A 여정은 "문제 → 숙달 상승 → 다음 concept"까지 본다. 원 지시문 §11의 A는 그 **앞에**
# "진단 → 학습"을 둔다. 그 두 마디는 위 여정이 지나가지 않는 표면에 있고(어느 통합 테스트도
# `POST /v1/me/assessments/capture`를 호출한 적이 없다 — 2026-09-19 전수 실측), 실제로 **끊겨
# 있다**. 이 테스트는 그 끊김을 계약으로 고정한다.
#
# 왜 별도 테스트인가: 위 A 여정은 *통과하는* 경로의 기록이고 이것은 *막힌* 경로의 기록이다.
# 한 테스트에 합치면 앞 마디에서 멈출 때 뒤 마디가 아예 판정되지 않는다(Week 1 하네스가
# 읽기 축을 분리해 둔 것과 같은 이유).


def test_persona_a_diagnosis_confirmation_and_study_entry_are_blocked() -> None:
    """A 연장: **짧은** 진단 세션은 확정되지 않아 학습 진입이 409로 막힌다.

    사슬 세 마디 — ①중단 규칙 **둘 다** 미발화(SE > 0.3이고 채점 응답 4건 < 상한 20)라
    ②`assessments/capture`가 `insufficient_measurement`로 끝나고, 그 분기에서만 도는
    `provision_learner_state`가 실행되지 않아 ③`POST /v1/me/objectives/{id}/study`가 **409**.

    **`EOS-126` 해소 후 이 테스트의 지위가 바뀌었다.** 해소 전에는 "진단이 *영원히* 확정되지
    않는다"는 결함의 동결이었다. 지금은 **정상 동작의 동결**이다 — 4문항짜리 세션이 진단으로
    확정되면 그것이 결함이다(측정 근거 없이 학습 경로를 정하게 된다). 해소의 증거는 여기가
    아니라 바로 아래 `..._confirms_at_item_cap`이며, 그쪽이 `written=True`·`study 201`을
    단언한다(`EOS-126` acceptance ④의 뒤집기 — ⑬이 열어 둔 "문항 수를 늘려 뒤집을지"의 답).

    두 테스트가 함께 있어야 변별력이 산다: 이것만 있으면 "아무것도 확정 안 됨"이, 저것만
    있으면 "아무거나 확정됨"이 통과한다.
    """
    content, journal = _begin("A-진단확정")
    try:
        cid, code = _seed_concept(content, "diag", "완전제곱식의 전개")
        pids = _seed_problems(content, cid, "d", [3.0, 3.2, 3.4, 3.6])
        objective_id = _seed_objective(content, code)

        with _client() as client:
            _erase_learner(client)
            auth = _login(client)

            # ① 진단 — 대부분 정답으로 네 문항을 푼다(측정 근거를 쌓는다).
            for index, pid in enumerate(pids):
                _attempt(client, auth, pid, correct=index != 2, answer=_UNMATCHED_WRONG_ANSWER)
            journal.record(
                "①진단응답", "4문항 제출(3정답 1오답)", 숙달=_mastery_of(client, auth, cid)
            )

            # ② 진단 확정 — CAT 중단 규칙에 닿지 못해 **쓰이지 않는다**.
            capture = client.post("/v1/me/assessments/capture", headers=auth)
            assert capture.status_code == 200, capture.text
            body = capture.json()
            journal.record(
                "②진단확정",
                "중단 규칙 둘 다 미발화(SE > 0.3 · 채점 4건 < 상한) → 적재 안 됨",
                written=body["written"],
                reason=body["reason"],
                SE=round(body["standard_error"], 3) if body["standard_error"] else None,
            )
            assert body["written"] is False, (
                "4문항 세션이 진단으로 확정됐다 — 중단 규칙 둘 중 하나가 너무 느슨하다. "
                f"상한({_MAX_ADMINISTERED_ITEMS})이 4 이하로 내려갔거나 `TARGET_SE`가 "
                "측정 근거를 잃을 만큼 완화된 것이다(`EOS-126` acceptance ③의 금지선)."
            )
            assert body["reason"] == "insufficient_measurement", body

            # ③ 학습 진입 — `learner_state` 행이 없어 루프 진입 게이트가 막는다.
            #    단언은 하나다. `== 409`가 404를 이미 배제하므로 "목표가 실재한다"를 별도
            #    절로 두지 않는다(어떤 입력에서도 판정을 바꾸지 못하는 절은 보호가 아니다).
            #    404가 나오는 상태는 `_seed_objective`를 지우는 뮤테이션이 RED로 잡는다.
            study = client.post(f"/v1/me/objectives/{objective_id}/study", headers=auth)
            journal.record(
                "③학습진입",
                "진단 확정이 없으므로 루프 진입 게이트가 막는다",
                status=study.status_code,
                응답=study.json().get("detail"),
            )
            assert study.status_code == 409, (
                f"학습 진입이 409가 아니다: {study.status_code} {study.text}\n"
                "  · 404라면 EOS-126의 증거가 아니라 **픽스처 결함**이다 — 목표 행이 안 심겼고, "
                "그 검사가 진단 게이트보다 앞서므로 학습자 상태와 무관하게 막힌다.\n"
                "  · 201이라면 4문항만으로 학습자 상태가 생긴 것이다 — 진단 게이트가 "
                "측정 근거 없이 열렸다."
            )
            assert "진단" in study.json()["detail"], study.json()
        journal.dump()
    finally:
        content.teardown()


def test_persona_a_diagnosis_confirms_at_item_cap_and_study_entry_opens() -> None:
    """A 연장: 문항 수 상한에 닿으면 진단이 확정되고 학습 진입이 열린다(`EOS-126` 해소 동결).

    이것이 `EOS-126` acceptance ④/⑨가 요구한 **뒤집기**다. 위 4문항 테스트가 "짧은 세션은
    확정되지 않는다"를 지키고, 이 테스트가 "감당 가능한 길이에서는 확정된다"를 지킨다.

    네 마디를 단언한다:
      ① 상한만큼 채점되면 `capture`가 `written=True`로 적재한다.
      ② 그 확정은 정밀도를 **참칭하지 않는다** — `reason="captured_at_item_cap"`이고
         `measurement_sufficient`는 False다(SE는 여전히 목표 미달). 이 절이 이 테스트의
         핵심이다: 상한을 "임계를 낮춰 통과시키는 장치"로 쓰지 않았음을 기계가 지킨다.
      ③ 그 분기에서 `provision_learner_state`가 돌아 `learner_state` 행이 생긴다.
      ④ 그래서 `POST /v1/me/objectives/{id}/study`가 **409를 내지 않는다** — 끊겼던
         "진단 → 학습" 화살표가 이어진다(계획서 §11 페르소나 A · §18 조건 3).

    **왜 201이 아니라 "409 아님"인가**: 이 화살표에는 마디가 둘이고 `EOS-126`은 앞 마디만
    소유한다. 게이트를 통과한 뒤 `supply()`가 이 개념의 DSL을 못 찾아 404를 내는데, 그것은
    `PED-17` acceptance ①이 이미 소유한 **다른 결함**이다(저장소에서 `/study` 201에 닿는
    테스트는 전부 `supply()`를 대역으로 바꾼다 — 실제 콘텐츠를 심는 경로가 없다). 여기서
    201을 요구하면 `EOS-126`의 판정이 남의 태스크에 인질로 잡힌다. 대신 ④-b가 그 404를
    사유까지 동결해 두어, 콘텐츠가 열리면 빨강으로 알려 준다.

    **왜 이 길이인가**: `TARGET_SE=0.3`은 이 경로가 모든 응답을 Rasch(a=1.0)로 다루는 한
    45문항이 이론적 하한이라(`MAX_ADMINISTERED_ITEMS` 주석의 실측) 한 자리에서 도달할 수
    없다. 상한은 그 도달 불가를 *정직하게 우회*하는 2차 중단 규칙이다.
    """
    content, journal = _begin("A-상한확정")
    try:
        cid, code = _seed_concept(content, "cap", "완전제곱식의 전개")
        # 상한 도달에 필요한 만큼 + 1(경계 바로 앞과 바로 뒤를 같은 회차에서 본다).
        difficulties = [2.0 + 0.1 * i for i in range(_MAX_ADMINISTERED_ITEMS)]
        pids = _seed_problems(content, cid, "c", difficulties)
        objective_id = _seed_objective(content, code)

        with _client() as client:
            _erase_learner(client)
            auth = _login(client)

            # ① 상한 **직전**까지 — 아직 확정되면 안 된다(경계의 변별력).
            for index, pid in enumerate(pids[:-1]):
                _attempt(client, auth, pid, correct=index % 3 != 0, answer=_UNMATCHED_WRONG_ANSWER)
            before = client.post("/v1/me/assessments/capture", headers=auth)
            assert before.status_code == 200, before.text
            before_body = before.json()
            journal.record(
                "①상한직전",
                f"채점 {_MAX_ADMINISTERED_ITEMS - 1}건 — 상한 미달이라 확정 안 됨",
                written=before_body["written"],
                reason=before_body["reason"],
                채점수=before_body["administered_count"],
            )
            assert before_body["written"] is False, (
                f"상한({_MAX_ADMINISTERED_ITEMS}) 직전인 "
                f"{_MAX_ADMINISTERED_ITEMS - 1}건에서 확정됐다 — 경계가 하나 어긋났다(off-by-one)."
            )
            assert before_body["reason"] == "insufficient_measurement", before_body
            assert before_body["administered_count"] == _MAX_ADMINISTERED_ITEMS - 1, before_body

            # ② 상한 도달 — 여기서 확정된다.
            _attempt(client, auth, pids[-1], correct=True, answer=_UNMATCHED_WRONG_ANSWER)
            capture = client.post("/v1/me/assessments/capture", headers=auth)
            assert capture.status_code == 200, capture.text
            body = capture.json()
            journal.record(
                "②상한확정",
                "EOS-126 2차 중단 규칙 발화 — 정밀도가 아니라 문항 수로 확정",
                written=body["written"],
                reason=body["reason"],
                정밀도달성=body["measurement_sufficient"],
                SE=round(body["standard_error"], 3) if body["standard_error"] else None,
                채점수=body["administered_count"],
            )
            assert body["written"] is True, (
                f"상한({_MAX_ADMINISTERED_ITEMS})에 닿았는데 확정되지 않았다: {body}. "
                "2차 중단 규칙이 끊긴 것이다 — `EOS-126`이 재발했다."
            )
            assert body["administered_count"] >= _MAX_ADMINISTERED_ITEMS, body
            # ②-b **정직 표기** — 상한 확정이 정밀도 달성을 참칭하면 안 된다.
            assert body["reason"] == "captured_at_item_cap", (
                f"상한 확정의 사유가 `captured_at_item_cap`이 아니다: {body['reason']}. "
                "정밀도로 확정된 회차와 구별되지 않으면 downstream이 이 진단의 신뢰도를 "
                "알 수 없다(침묵 실패)."
            )
            assert body["measurement_sufficient"] is False, (
                "상한으로 확정했는데 `measurement_sufficient`가 True다 — 상한이 정밀도 달성을 "
                "참칭하고 있다. `TARGET_SE`를 낮춰 통과시킨 것과 같다"
                "(`EOS-126` acceptance ③의 금지선)."
            )
            assert body["standard_error"] is not None and body["standard_error"] > _TARGET_SE, body

            # ③ 학습자 상태 행 — 확정 분기에서만 도는 `provision_learner_state`의 산출물.
            #    학습 진입 201과 **별개로** 단언한다: 201만 보면 "게이트가 열렸다"는 알아도
            #    "행이 생겨서 열렸다"는 모른다(게이트 자체가 사라져도 201이 나온다).
            #    `GET /v1/me/learner-state`로는 볼 수 없다 — 그 표면은 숙달·능력을 합성해
            #    돌려줄 뿐 행의 생성 사유(`provisioned_by`)를 담지 않는다(2026-09-21 실측).
            provisioned_by = _provisioned_by(client, auth)
            journal.record(
                "③학습자상태",
                "진단 확정 분기에서 자동 생성(계획서 §18 조건 3)",
                provisioned_by=provisioned_by,
            )
            assert provisioned_by == "diagnosis_capture", (
                f"학습자 상태 행이 진단 확정으로 만들어지지 않았다: {provisioned_by!r}. "
                "None이면 행 자체가 없다 — 확정 분기에서 "
                "`provision_learner_state(reason=diagnosis_capture)`가 돌지 않은 것이다."
            )

            # ④ 학습 진입 — 끊겼던 화살표가 이어진다.
            study = client.post(f"/v1/me/objectives/{objective_id}/study", headers=auth)
            journal.record(
                "④학습진입",
                "진단이 확정됐으므로 루프 진입 게이트가 열린다",
                status=study.status_code,
                응답=study.json().get("detail"),
            )
            # ④-a **EOS-126의 뒤집기는 이 단언이다** — 진단 게이트가 더 이상 막지 않는다.
            assert study.status_code != 409, (
                f"학습 진입이 여전히 409다: {study.text}\n"
                "진단이 확정(`written=True`)되고 학습자 상태 행까지 생겼는데 루프 진입이 "
                "막혔다 — `EOS-126`의 끊긴 화살표가 재발했다."
            )
            # ④-b 남은 마디는 **다른 결함**이다(`PED-17` acceptance ① 소유). 진단 게이트를
            #     통과한 뒤 `supply()`가 이 개념의 DSL을 못 찾아 404를 낸다. `EOS-126`의
            #     범위가 아니므로 여기서 고치지 않고, 대신 *지금 사실*을 동결한다 — 콘텐츠
            #     공급이 열리면 이 단언이 빨강이 되고, 그때 201로 승격하면 된다.
            #     사유를 문자열로 함께 잠근다: 그러지 않으면 목표 부재 404(픽스처 결함)와
            #     구별되지 않아 단언이 변별력을 잃는다(`EOS-126` acceptance ⑦).
            assert study.status_code == 404, (
                f"학습 진입이 404가 아니다: {study.status_code} {study.text}\n"
                "201이라면 콘텐츠 공급이 열린 것이다 — `PED-17`을 닫으면서 이 단언을 201로 "
                "승격하라."
            )
            assert study.json()["detail"] == "이 개념의 학습 콘텐츠가 아직 준비되지 않았습니다.", (
                f"404의 사유가 콘텐츠 미적재가 아니다: {study.json()}. "
                "'학습목표를 찾을 수 없습니다' 계열이면 픽스처 결함이다(목표 행 미시딩) — "
                "그 상태는 진단 게이트보다 *앞서* 막으므로 이 회차는 EOS-126을 판정하지 "
                "못한 것이다."
            )
        journal.dump()
    finally:
        content.teardown()
