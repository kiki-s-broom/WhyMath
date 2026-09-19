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
(각각 `PED-36` ⑫·`EOS-119` 소유).

**정직한 공백 동결** — 아래 두 가지는 *현행 동작*을 단언한다. 고쳐지면 이 테스트가 실패하며,
실패 메시지가 승계 태스크 id를 가리킨다(조용히 낡지 않게).
  ⓐ `EOS-123` — 정답 제출은 오개념 감쇠 시계를 돌리지 않는다(`apply_candidates` 미호출).
  ⓑ `EOS-124` — 보정이 끝나 선수 결손이 해소된 뒤에도 추천의 `action`/`target_concept`이
     `practice_prerequisite`/선수개념으로 남는다(고른 *문항*은 원래 concept인데 *설명*만 낡음).
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
from whymath_backend.schema.concept import ConceptEdge as ConceptEdgeSchema
from whymath_backend.schema.enums import EdgeType

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

            # ⑤-b 정직한 공백 동결 (`EOS-124`) — 그런데 *고른 것*은 현재 개념의 문항이고
            #      `target_concept`도 방금 숙달한 **현재** 개념을 가리킨다. 즉 정책 축과 선택
            #      축이 따로 계산되고 서로를 보지 않는다. 고쳐지면 이 단언이 실패하며, 그때는
            #      이 자리를 "다음 개념 문항"으로 올려 쓰는 것이 맞다.
            assert picked in {str(x) for x in cur_pids}, (
                "추천이 다음 개념 문항을 골랐다 — `EOS-124`(정책 축·선택 축 불일치)가 해소된 "
                "것으로 보인다. 이 단언을 다음 개념 문항 단언으로 승격하고 EOS-124를 닫아라."
            )
            assert advanced["target_concept"] == str(c_cur), (
                "`advance_next`의 target_concept이 더 이상 현재 개념이 아니다 — `EOS-124` "
                "해소 신호. 위 단언과 함께 승격하라."
            )
            journal.record(
                "⑤-b정책·선택불일치",
                "EOS-124 정직한 공백 — action은 전진, 문항·target은 현재 개념",
                action=advanced["action"],
                target=("현재개념" if advanced["target_concept"] == str(c_cur) else "다음개념"),
                문항소속=("현재개념" if picked in {str(x) for x in cur_pids} else "다음개념"),
            )

            # ⑥ 완주 — 현재 개념 문항을 소진하면 다음 개념으로 넘어간다. 이동이 *일어난다*는
            #    것과 그것이 *숙달 때문*이라는 것은 다르다. 이 하네스는 전자만 판정하고,
            #    후자가 아직 아니라는 사실은 ⑤-b가 동결한다.
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

            # ⑧-b 정직한 공백 동결 (`EOS-124`) — 문항은 복귀했는데 *설명*은 낡았다.
            assert back["action"] == "practice_prerequisite", (
                "복귀 후 action이 더 이상 practice_prerequisite가 아니다 — `EOS-124`(정책 축·"
                "선택 축 불일치) 해소 신호. 이 단언을 올바른 값 단언으로 승격하고 EOS-124를 닫아라."
            )
            journal.record(
                "⑧-b정책·선택불일치",
                "EOS-124 정직한 공백 — 문항은 원래 개념인데 action·target은 선수 개념",
                action=back["action"],
                target=("선수개념" if back["target_concept"] == str(c_pre) else "원래개념"),
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
