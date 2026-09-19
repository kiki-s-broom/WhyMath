"""계획서 300 Phase 2 §11 **페르소나 3인 완주** 하네스 (집행 지시문 `P-15`).

판정 대상(원 문서 §11 그대로 — 대표 사용자 **3명**의 서로 다른 여정):

    A 정상 학습자     진단 → 학습 → 문제 → 대부분 정답 → mastery 상승 → 다음 concept
    B 선수학습 결손   진단 → 문제 → 반복 오답 → prerequisite gap → 하위 concept → 보정
                      → **원래 concept 복귀**
    C 특정 오개념     진단 → 문제 → 특정 오답 패턴 → misconception detection
                      → corrective explanation → targeted problem → confidence **감소**

세 경로를 **공개 HTTP 표면만으로** 각각 끝까지 돌리고, 마디마다 산출물을 단언한다. 판정은
pytest exit code로 나오고, 마디마다 `P15_PERSONA_STEP=...` 줄이 표준출력에 남는다(인상 판정
금지). LearnerState 변화표는 그 줄들이 곧 원자료다.

**Week 1~3 게이트와 무엇이 다른가 — 학습자가 *한 명이 아니다***
Week 1·2·3은 전부 고정 데모 계정 **1인**의 1회 관통을 본다. 그래서 "이 경로가 돈다"는 증명은
되지만 "*다른 상태의 학습자*에게 서버가 다르게 반응한다"는 증명은 되지 않는다 — 분기 자체가
관측되지 않기 때문이다. 이 하네스는 provider를 셋 등록해 **서로 다른 세 계정**을 만들고, 같은
저작 콘텐츠 위에서 세 여정이 *서로 다른 산출물*을 내는지를 본다. 세 경로가 같은 응답을 내면
그것은 통과가 아니라 분기 부재다.

**시딩 경계(정직한 선언)** — Week 1~3과 같다.
*학습자 상태*는 단 한 줄도 직접 쓰지 않는다(전부 HTTP 부수효과). *저작 콘텐츠*(concept·
problem·problem_concept·skill_node·concept_edge·atom_node)만 ORM으로 심는다. 픽스처 조립기는
Week 2 하네스에서 그대로 빌려 쓴다(재구현 0). DB를 *읽는* 것은 관측이지 개입이 아니다 —
오개념 confidence는 어떤 HTTP 표면도 *숫자로* 돌려주지 않으므로(§C-3 참조) 그 축만 DB 관측을
쓴다.

**`atom_node`를 심는 이유(실측 함정)**: 선수 추천은 `concept.code ↔ atom_node.code` OUTER
JOIN 뒤 `atom_meta is None`이면 **원자 축 밖으로 보고 조용히 제외**한다
(`l2/prerequisite_recommendation.py` ④ 축 울타리). 그래서 이 행을 안 심으면 페르소나 B의
선수 마디가 *0건*으로 돌아오고, "선수가 안 막혔다"와 "축 밖이라 빠졌다"가 같은 빈 배열로
보인다(2026-09-19 실측 — 처음 짠 픽스처가 정확히 이 상태였다).

**판정 밖(의도적으로 보지 않는 것)**
- 코칭 문구·교정 발화의 교수학적 품질은 보지 않는다(연결성과 *수치 변화*만).
- `POST /v1/me/objectives/{id}/study`(학습 단위 공급)는 지나가지 않는다 — 그 좌석은
  `learning_objective` 행과 DSL 적재를 요구하고, 페르소나 A의 "학습" 마디가 막히는 지점은 그
  앞단(`learner_state` 행 부재)이라 거기까지 가지 못한다. 그 사실 자체는 §A-4가 동결한다.
- 라이브 LLM 0 — 코치는 `decision.prompt`를 AI 턴으로 저장할 뿐 LLM을 부르지 않는다
  (`api/coach.py` 모듈 계약). shadow·judge·의미 매처는 전부 기본 off.
"""

from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import sys
import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from whymath_backend.api._rate_limit import reset_store
from whymath_backend.api.auth import OAuthIdentity, email_hash
from whymath_backend.app import create_app
from whymath_backend.config import get_settings
from whymath_backend.db.models.atom_node import AtomNode
from whymath_backend.db.models.concept import ConceptEdge
from whymath_backend.schema.enums import EdgeType

pytestmark = pytest.mark.integration

# ── Week 2 게이트 하네스의 검증된 픽스처 조립기 재사용 (재구현 0) ────────────────────
# Week 3·P-11이 이미 쓰는 경로 로딩 패턴을 그대로 답습한다. 이 저장소의 pytest는
# `--import-mode=importlib`이라 형제 테스트 모듈이 이름으로 임포트되지 않는다.
_WEEK2_PATH = pathlib.Path(__file__).with_name("test_week2_gate_wrong_answer_propagation.py")
#: 빌려 쓰는 헬퍼 계약 — 하나라도 사라지면 수집 단계에서 이름을 지목하며 실패한다.
_WEEK2_HELPERS = (
    "_EXPECTED_MISCONCEPTION",
    "_QUESTION_TEXT",
    "_UNMATCHED_WRONG_ANSWER",
    "_WRONG_ANSWER",
    "_add_all",
    "_cleanup_content",
    "_concept",
    "_delete_skill_node",
    "_pg_reachable",
    "_problem",
    "_problem_concept",
    "_settings",
    "_skill_node",
)


def _load_week2_harness() -> Any:
    """Week 2 하네스를 파일 경로로 적재하고 헬퍼 계약을 검사한다."""
    if not _WEEK2_PATH.exists():
        raise RuntimeError(
            f"Week 2 게이트 하네스가 없다: {_WEEK2_PATH}. 이 판정은 그 픽스처 조립기를 "
            "재사용한다 — 파일이 옮겨졌으면 이 경로를 함께 고친다."
        )
    spec = importlib.util.spec_from_file_location("_week2_gate_harness", _WEEK2_PATH)
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
_concept = _W2._concept
_delete_skill_node = _W2._delete_skill_node
_pg_reachable = _W2._pg_reachable
_problem = _W2._problem
_problem_concept = _W2._problem_concept
_settings = _W2._settings
_skill_node = _W2._skill_node

#: 비미성년 출생연도 — `is_minor=False`로 파생돼 동의 게이트(403)를 통과한다(데모 provider와 동일).
_ADULT_BIRTH_YEAR = 2004
#: Week 1 하네스의 Settings가 allowlist에 올려 둔 그 값이어야 한다 — `_settings`를 그쪽에서
#: 빌려 쓰므로 여기서 다른 uri를 쓰면 콜백이 deny-by-default로 400을 낸다(2026-09-19 실측).
_REDIRECT_URI = "http://localhost:8000/auth/demo/callback"
_ERASE_CONFIRM = "DELETE_MY_ACCOUNT"
#: 원 문서 §11의 세 페르소나. provider 이름이 곧 계정 구분 키다(신원마다 다른 email_hash).
_PERSONAS = ("persona-a", "persona-b", "persona-c")


class _PersonaOAuthProvider:
    """페르소나별 고정 신원을 돌려주는 시연 provider — `OAuthProvider` Protocol 구조 충족.

    `api/demo_auth.py`의 `FakeOAuthProvider`와 같은 모양이되 **신원이 페르소나마다 다르다**.
    고정 데모 계정 하나를 셋이 나눠 쓰면 세 여정의 상태가 서로를 오염시켜, 이 판정이 재려는
    "다른 학습자에게 다른 반응"이 관측 자체로 불가능해진다.
    """

    def __init__(self, name: str) -> None:
        self._name = name

    async def fetch_identity(self, code: str, redirect_uri: str) -> OAuthIdentity:
        """code를 무시하고 이 페르소나의 고정 신원을 돌려준다(결정론·재실행 안전)."""
        return OAuthIdentity(
            provider=self._name,
            subject=f"{self._name}-fixed-subject",
            email=_persona_email(self._name),
            birth_year=_ADULT_BIRTH_YEAR,
        )


def _persona_email(name: str) -> str:
    """페르소나 이메일 — 안정 upsert 키(같은 이메일=같은 email_hash=같은 UserProfile)."""
    return f"{name}@p15.whymath.example"


def _client() -> Any:
    """실 PG 클라이언트 — 페르소나 provider 3종만 주입하고 `get_session`은 라이브 PG 그대로."""
    from fastapi.testclient import TestClient

    app = create_app(oauth_providers={n: _PersonaOAuthProvider(n) for n in _PERSONAS})
    app.dependency_overrides[get_settings] = _settings
    return TestClient(app)


def _login(client: Any, persona: str) -> dict[str, str]:
    """페르소나 콜백 로그인 — 신규면 `resolve_user`가 upsert로 **생성**한다(ORM insert 0)."""
    state = client.get(f"/v1/auth/{persona}/state")
    assert state.status_code == 200, state.text
    login = client.post(
        f"/v1/auth/{persona}/callback",
        json={"code": "p15", "redirect_uri": _REDIRECT_URI, "state": state.json()["state"]},
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    assert token, f"{persona}: access_token이 비었다 — 생성 경로가 토큰을 발급하지 못했다."
    return {"Authorization": f"Bearer {token}"}


def _erase(client: Any, persona: str) -> None:
    """페르소나 학습자 데이터 정리 — 운영 삭제권(`DELETE /v1/me`). 멱등(없으면 0행)."""
    auth = _login(client, persona)
    erased = client.request("DELETE", "/v1/me", headers=auth, json={"confirmation": _ERASE_CONFIRM})
    assert erased.status_code == 200, erased.text


def _step(persona: str, name: str, detail: str) -> None:
    """마디 통과를 표준출력에 남긴다 — 판정은 exit code, 경위는 이 줄들이 말한다."""
    print(f"P15_PERSONA_STEP={persona}/{name} :: {detail}")


def _snapshot(client: Any, auth: dict[str, str], persona: str, node: str) -> dict[str, Any]:
    """그 마디 시점의 LearnerState 스냅샷을 표준출력에 남기고 돌려준다.

    원 문서 §11-①("각 단계의 LearnerState 변화를 표로 제시하라")의 *원자료*가 이 줄들이다.
    판정 문서의 표는 여기서 그대로 옮겨 적는다 — 사람이 따로 재구성하면 표와 실행이 어긋난다.
    """
    resp = client.get("/v1/me/learner-state", headers=auth)
    assert resp.status_code == 200, resp.text
    state: dict[str, Any] = resp.json()
    mastery = {k: round(v, 3) for k, v in sorted(state["mastery"].items())}
    print(
        f"P15_LEARNER_STATE={persona}/{node} :: mastery={mastery} · "
        f"theta={state['general_ability']} · misconceptions={state['active_misconceptions']} · "
        f"struggles={state['recent_struggles']} · skills={len(state['skill_mastery'])}건"
    )
    return state


# ── 저작 콘텐츠 조립기(Week 2에 없는 것만 여기서 정의) ────────────────────────────────


def _atom_node(code: str, name_ko: str) -> AtomNode:
    """원자 축 안전 메타 행(PK=code) — 선수 추천의 축 울타리를 통과시키는 필수 픽스처.

    모듈 docstring의 실측 함정 참조: 이 행이 없으면 선수 마디가 조용히 0건이 된다.
    """
    return AtomNode(
        code=code,
        name_ko=name_ko,
        level="세부개념",
        subject_area="대수",
        review_status="reviewed",
    )


def _prereq_edge(from_id: uuid.UUID, to_id: uuid.UUID) -> ConceptEdge:
    """선수 엣지 — from(선수)이 to(후행)의 선수. 방향이 뒤집히면 선수 조회가 0건이 된다."""
    return ConceptEdge(
        from_concept_id=from_id,
        to_concept_id=to_id,
        edge_type=EdgeType.PREREQUISITE.value,
        edge_strength=0.9,
    )


async def _sql(sql: str, **params: Any) -> list[Any]:
    """관측·정리 전용 원시 SQL — 학습자 *상태*는 쓰지 않는다(읽기 또는 저작 콘텐츠 삭제만)."""
    engine = create_async_engine(_settings().database_url)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(sql), params)
            return list(result.fetchall()) if result.returns_rows else []
    finally:
        await engine.dispose()


def _user_id(persona: str) -> uuid.UUID:
    """페르소나 계정의 user_id — 관측 조인 키(email_hash는 운영 코드의 것을 그대로 쓴다)."""
    rows = asyncio.run(
        _sql(
            "SELECT user_id FROM user_profile WHERE email_hash = :h",
            h=email_hash(_persona_email(persona)),
        )
    )
    assert len(rows) == 1, f"{persona}: user_profile이 1건이 아니다 — {rows}"
    return uuid.UUID(str(rows[0][0]))


def _hypotheses(user_id: uuid.UUID) -> list[tuple[str, Decimal, int, int, bool]]:
    """활성·비활성 오개념 가설 관측 — confidence는 HTTP로 숫자가 나오지 않는다(§C-3)."""
    rows = asyncio.run(
        _sql(
            "SELECT misconception_id, confidence, turns_since_evidence, evidence_count, is_active "
            "FROM misconception_hypothesis WHERE user_id = :u ORDER BY confidence DESC",
            u=str(user_id),
        )
    )
    return [(r[0], r[1], r[2], r[3], r[4]) for r in rows]


def _confidence_of(user_id: uuid.UUID, misconception_id: str) -> float:
    """대상 오개념 가설의 confidence 1건 — 없으면 단언 실패(부재와 0을 섞지 않는다)."""
    hit = [h for h in _hypotheses(user_id) if h[0] == misconception_id]
    assert len(hit) == 1, f"가설 {misconception_id}이 1건이 아니다: {_hypotheses(user_id)}"
    return float(hit[0][1])


def _learner_state_rows(user_id: uuid.UUID) -> int:
    """`learner_state` 영속 행 수 — 진단 확정(capture)의 부수효과 관측 지점."""
    rows = asyncio.run(
        _sql("SELECT count(*) FROM learner_state WHERE learner_id = :u", u=str(user_id))
    )
    return int(rows[0][0])


def _mastery_of(client: Any, auth: dict[str, str], code: str) -> float | None:
    """현재 개념 숙달 스냅샷에서 한 개념만 — 없으면 None(미측정과 0을 섞지 않는다)."""
    resp = client.get("/v1/me/mastery/current", headers=auth)
    assert resp.status_code == 200, resp.text
    for item in resp.json():
        if item["concept_code"] == code:
            return float(item["mastery"])
    return None


def _attempt(
    client: Any, auth: dict[str, str], pid: uuid.UUID, *, correct: bool, answer: str | None = None
) -> dict[str, Any]:
    """시도 1건 제출 — 201과 `is_correct` 일치까지만 여기서 단언한다."""
    body: dict[str, Any] = {"problem_id": str(pid), "is_correct": correct}
    if answer is not None:
        body["student_answer"] = answer
    resp = client.post("/v1/me/attempts", headers=auth, json=body)
    assert resp.status_code == 201, resp.text
    payload: dict[str, Any] = resp.json()
    assert payload["is_correct"] is correct, payload
    return payload


def _seed_concept(
    cid: uuid.UUID, code: str, skill_id: str, pids: list[uuid.UUID], sfx: str, difficulty: float
) -> None:
    """개념 1 + 스킬 1 + 원자 메타 1 + 문항 N(같은 개념 PRIMARY)을 심는다."""
    asyncio.run(_add_all(_skill_node(skill_id)))
    asyncio.run(_add_all(_concept(cid, code, skill_id)))
    asyncio.run(_add_all(_atom_node(code, "완전제곱식의 전개")))
    for index, pid in enumerate(pids):
        asyncio.run(_add_all(_problem(pid, f"{sfx}{index}", difficulty)))
        asyncio.run(_add_all(_problem_concept(pid, cid)))


def _teardown(
    persona: str,
    *,
    concept_ids: list[uuid.UUID],
    problem_ids: list[uuid.UUID],
    skill_ids: list[str],
    codes: list[str],
) -> None:
    """정리 — **학습자를 먼저**(운영 삭제권), 그 다음 저작 콘텐츠를 FK 안전 순서로.

    Week 2와 같은 이유로 멱등이고 본문 성패와 무관하게 돈다: 본문이 단언에서 실패하면
    학습자가 남고, 그 상태로 콘텐츠를 지우면 FK 위반이 터져 **원래의 단언 실패를 가린다**.
    `concept_edge`·`atom_node`는 Week 1의 `_cleanup_content`가 모르는 표라 여기서 지운다.
    """
    try:
        with _client() as client:
            _erase(client, persona)
    finally:
        try:
            asyncio.run(
                _sql(
                    "DELETE FROM concept_edge WHERE from_concept_id = ANY(:ids) "
                    "OR to_concept_id = ANY(:ids)",
                    ids=[str(c) for c in concept_ids],
                )
            )
            asyncio.run(_cleanup_content(problem_ids=problem_ids, concept_ids=concept_ids))
        finally:
            asyncio.run(_sql("DELETE FROM atom_node WHERE code = ANY(:codes)", codes=codes))
            for skill_id in skill_ids:
                asyncio.run(_delete_skill_node(skill_id))


# ── 페르소나 A — 정상 학습자 ─────────────────────────────────────────────────────────


def test_persona_a_normal_learner_completes_path() -> None:
    """A: 진단 → (학습) → 문제 → 대부분 정답 → mastery 상승 → 다음 concept."""
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 판정 불가(WHYMATH_DATABASE_URL 확인). 통과가 아니다.")
    asyncio.run(reset_store())

    sfx = uuid.uuid4().hex[:8]
    cid_main, cid_next = uuid.uuid4(), uuid.uuid4()
    code_main, code_next = f"UC.p15a.{sfx}.m", f"UC.p15a.{sfx}.n"
    skill_main, skill_next = f"skill.p15a.{sfx}.m", f"skill.p15a.{sfx}.n"
    pids_main = [uuid.uuid4() for _ in range(5)]
    pids_next = [uuid.uuid4() for _ in range(2)]

    try:
        _seed_concept(cid_main, code_main, skill_main, pids_main, f"{sfx}m", 3.0)
        _seed_concept(cid_next, code_next, skill_next, pids_next, f"{sfx}n", 3.0)

        with _client() as client:
            _erase(client, "persona-a")  # 선행 정리 — 지난 회차 계정이 남으면 기준선이 깨진다.
            auth = _login(client, "persona-a")
            uid = _user_id("persona-a")
            _step(
                "A",
                "0-account",
                f"user_id={uid} · 진단 전 learner_state={_learner_state_rows(uid)}건",
            )

            # ── 1) 진단 — 상태 표기 + CAT 출제(진단 목적). ────────────────────────────
            started = client.post(
                "/v1/me/learning-state/transitions",
                headers=auth,
                json={"to_state": "DIAGNOSING", "trigger": "DIAGNOSIS_STARTED"},
            )
            assert started.status_code == 201, started.text
            assert started.json()["current_state"] == "DIAGNOSING", started.json()
            diag = client.get("/v1/me/next-problem?purpose=diagnosis", headers=auth)
            assert diag.status_code == 200, diag.text
            _snapshot(client, auth, "A", "1-diagnosis")
            _step("A", "1-diagnosis", f"DIAGNOSING 진입 · CAT action={diag.json()['action']}")

            # ── 2) 문제 — 대부분 정답(5문항 중 4정답 1오답). ──────────────────────────
            # 추천기를 따라가지 않고 *우리가 심은* 문항에 직접 제출한다: 후보 풀은 이 DB의
            # 전 문항이라 다른 통합 테스트의 잔여 콘텐츠가 섞이면 이 마디의 mastery 귀속이
            # 흐려진다(어느 개념이 올랐는지 말할 수 없게 된다). CAT *선택* 축은 위 1)과 아래
            # 4)가, Week 1이 이미 따로 판정한다.
            # `pids_main[0]`은 **끝까지 미응답으로 남긴다** — 4)의 판정 변별력이 여기서 나온다.
            before = _mastery_of(client, auth, code_main)
            assert before is None, f"투입 전인데 이미 숙달이 측정돼 있다: {before}"
            for index, pid in enumerate(pids_main[1:]):
                _attempt(client, auth, pid, correct=index != 1)
            after = _mastery_of(client, auth, code_main)
            assert after is not None, "4문항을 풀었는데 개념 숙달이 측정되지 않았다(끊긴 마디)."
            _step("A", "2-attempts", f"3정답/1오답 · mastery {before}→{after:.3f}")

            # ── 3) mastery 상승 — 부재→측정 + 대부분 정답이 상승으로 나타난다. ────────
            assert (
                after > 0.5
            ), f"대부분 정답인데 숙달이 {after:.3f}다 — 정답이 상승으로 이어지지 않았다."
            _snapshot(client, auth, "A", "3-mastery-up")
            _step("A", "3-mastery-up", f"{code_main} mastery={after:.3f} (>0.5)")

            # ── 4) 다음 concept — 약개념 가중 추천이 *다른* 개념으로 넘긴다. ──────────
            # **소진과 구별한다**: main 개념에 미응답 문항이 *남아 있는데도* 추천이 다른
            # 개념으로 가야 "넘어갔다"가 성립한다. main을 다 풀어 버리면 후보가 next밖에
            # 없어 이 마디는 제외 로직을 통째로 지워도 통과한다(변별력 0).
            _attempt(client, auth, pids_next[0], correct=False)  # next 개념에 약점 신호 1건.
            leftover = asyncio.run(
                _sql(
                    "SELECT count(*) FROM problem_attempt WHERE user_id = :u AND problem_id = :p",
                    u=str(uid),
                    p=str(pids_main[0]),
                )
            )
            assert int(leftover[0][0]) == 0, (
                f"미응답으로 남겼어야 할 main 문항에 시도가 있다({leftover}) — 이 상태에서는 "
                "다음 마디가 '넘어갔다'와 '소진됐다'를 구별하지 못한다."
            )
            nxt = client.get("/v1/me/next-problem?prioritize_weak_concepts=true", headers=auth)
            assert nxt.status_code == 200, nxt.text
            recommended = nxt.json()["problem_id"]
            assert recommended is not None, f"추천이 비었다: {nxt.json()}"
            assert recommended in {str(p) for p in pids_next}, (
                f"다음 concept로 넘어가지 않았다 — 추천={recommended} · "
                f"next 개념 문항={[str(p) for p in pids_next]} · "
                f"미응답으로 남긴 main 문항={pids_main[0]}"
            )
            _snapshot(client, auth, "A", "4-next-concept")
            _step(
                "A",
                "4-next-concept",
                f"추천={recommended} · action={nxt.json()['action']} · "
                f"weight_axes={nxt.json()['weight_axes_applied']}",
            )

            # ── 5) 진단 확정 — **현행 main에서 끊긴다**(동결). ────────────────────────
            # CAT 중단 규칙은 SE ≤ 0.3(`l2/next_problem_selection.TARGET_SE`)인데, 실측으로
            # 45문항을 풀어도 SE가 0.39에 머문다(2026-09-19 · 이 하네스와 같은 픽스처).
            # 그래서 `capture`가 한 번도 쓰지 않고, `learner_state` 행이 생기지 않고,
            # `POST /v1/me/objectives/{id}/study`는 영구히 409다. 이 단언은 그 *끊긴 상태*를
            # 계약으로 고정한다 — 해소되면 여기가 빨강이 되고, 그때 이 절을
            # `written is True`로 바꾼다. 소유 태스크는 판정 문서에 적는다.
            cap = client.post("/v1/me/assessments/capture", headers=auth)
            assert cap.status_code == 200, cap.text
            assert cap.json()["written"] is False, (
                "진단 확정이 쓰였다 — CAT 중단 규칙이 해소된 것이다. 이 절을 written=True "
                "단언으로 바꾸고 아래 learner_state 단언도 1건으로 고친다."
            )
            assert cap.json()["reason"] == "insufficient_measurement", cap.json()
            assert (
                _learner_state_rows(uid) == 0
            ), "capture가 쓰지 않았는데 learner_state 행이 있다 — 다른 생산자가 생겼다."
            _snapshot(client, auth, "A", "5-capture")
            _step(
                "A",
                "5-capture-BLOCKED",
                f"written=False · reason={cap.json()['reason']} · "
                f"SE={cap.json()['standard_error']:.3f} (목표 0.3) · learner_state=0건",
            )
    finally:
        _teardown(
            "persona-a",
            concept_ids=[cid_main, cid_next],
            problem_ids=pids_main + pids_next,
            skill_ids=[skill_main, skill_next],
            codes=[code_main, code_next],
        )


# ── 페르소나 B — 선수학습 결손 ────────────────────────────────────────────────────────


def test_persona_b_prerequisite_gap_returns_to_original_concept() -> None:
    """B: 반복 오답 → prerequisite gap → 하위 concept → 보정 → **원래 concept 복귀**."""
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 판정 불가(WHYMATH_DATABASE_URL 확인). 통과가 아니다.")
    asyncio.run(reset_store())

    sfx = uuid.uuid4().hex[:8]
    cid_pre, cid_top = uuid.uuid4(), uuid.uuid4()
    code_pre, code_top = f"UC.p15b.{sfx}.pre", f"UC.p15b.{sfx}.top"
    skill_pre, skill_top = f"skill.p15b.{sfx}.pre", f"skill.p15b.{sfx}.top"
    pids_pre = [uuid.uuid4() for _ in range(3)]
    # 후행 문항이 **4개**인 이유: 5) 복귀 마디는 "후행 개념 문항을 추천한다"를 재는데, 추천기는
    # 이미 시도한 문항을 후보에서 제외한다. 3개를 전부 오답으로 쓰면 후보 풀이 0이 되어
    # `candidate_zero_reason=no_candidate_pool`로 끝나고, 그러면 "복귀하지 않았다"와 "돌아갈
    # 문항이 없다"가 구별되지 않는다(2026-09-19 실측 — 처음 픽스처가 정확히 그 상태였다).
    pids_top = [uuid.uuid4() for _ in range(4)]

    try:
        _seed_concept(cid_pre, code_pre, skill_pre, pids_pre, f"{sfx}p", 2.0)
        _seed_concept(cid_top, code_top, skill_top, pids_top, f"{sfx}t", 4.0)
        asyncio.run(_add_all(_prereq_edge(cid_pre, cid_top)))

        with _client() as client:
            _erase(client, "persona-b")
            auth = _login(client, "persona-b")
            _step("B", "0-account", f"user_id={_user_id('persona-b')}")

            # ── 1) 반복 오답 — 후행 개념에서 연속으로 막힌다. ─────────────────────────
            for pid in pids_top[:3]:  # `pids_top[3]`은 복귀 마디의 후보로 남긴다.
                _attempt(client, auth, pid, correct=False, answer=_UNMATCHED_WRONG_ANSWER)
            top_mastery = _mastery_of(client, auth, code_top)
            assert (
                top_mastery is not None and top_mastery < 0.7
            ), f"반복 오답인데 후행 개념이 약점으로 잡히지 않았다: {top_mastery}"
            _snapshot(client, auth, "B", "1-repeated-wrong")
            _step("B", "1-repeated-wrong", f"{code_top} 3연속 오답 · mastery={top_mastery:.3f}")

            # 선수 개념에도 결손이 *측정*돼 있어야 한다 — 미측정 선수는 약점 근거가 없어
            # `weak_only=True`에서 제외된다(추천기 ③). "결손"과 "모름"은 다르다.
            _attempt(client, auth, pids_pre[0], correct=False, answer=_UNMATCHED_WRONG_ANSWER)

            # ── 2) prerequisite gap — 서버가 *스스로* 막힌 선수를 지목한다. ───────────
            gaps = client.get(f"/v1/me/weak-concepts/{cid_top}/prerequisites", headers=auth)
            assert gaps.status_code == 200, gaps.text
            found = {g["concept_code"]: g for g in gaps.json()}
            assert code_pre in found, (
                f"막힌 선수가 지목되지 않았다: {list(found)} — 요청은 후행 개념 id 하나뿐이고 "
                "선수 관계·약점 판정은 전부 서버가 했다."
            )
            assert found[code_pre]["depth"] == 1, found[code_pre]
            _snapshot(client, auth, "B", "2-prereq-gap")
            _step(
                "B",
                "2-prereq-gap",
                f"선수={code_pre} · weakness={found[code_pre]['weakness']} · depth=1",
            )

            # ── 3) 하위 concept — 코칭 결정이 후행을 보류하고 선수 복습으로 내려보낸다. ─
            coaching = client.get(f"/v1/me/weak-concepts/{cid_top}/coaching", headers=auth)
            assert coaching.status_code == 200, coaching.text
            assert (
                coaching.json()["focus"] == "prerequisite_review"
            ), f"막힌 선수가 있는데 코칭이 선수 복습으로 내려가지 않았다: {coaching.json()}"
            _snapshot(client, auth, "B", "3-descend")
            _step("B", "3-descend", f"coaching.focus=prerequisite_review · {code_pre}로 내려감")

            # ── 4) 보정 — 선수 개념을 반복 정답으로 끌어올린다. ───────────────────────
            for _ in range(4):
                for pid in pids_pre:
                    _attempt(client, auth, pid, correct=True)
            pre_mastery = _mastery_of(client, auth, code_pre)
            assert pre_mastery is not None and pre_mastery >= 0.7, (
                f"선수 보정이 임계(0.7)에 못 미친다: {pre_mastery} — 이 상태로는 복귀 마디가 "
                "'보정이 됐다'의 증거가 되지 못한다."
            )
            _snapshot(client, auth, "B", "4-remediate")
            _step("B", "4-remediate", f"{code_pre} mastery={pre_mastery:.3f} (≥0.7)")

            # ── 5) 원래 concept 복귀 — 선수가 더는 막지 않고 코칭이 후행으로 돌아온다. ─
            gaps_after = client.get(f"/v1/me/weak-concepts/{cid_top}/prerequisites", headers=auth)
            assert gaps_after.status_code == 200, gaps_after.text
            assert code_pre not in {
                g["concept_code"] for g in gaps_after.json()
            }, f"보정 후에도 선수가 막힌 것으로 남아 있다: {gaps_after.json()}"
            coaching_after = client.get(f"/v1/me/weak-concepts/{cid_top}/coaching", headers=auth)
            assert coaching_after.status_code == 200, coaching_after.text
            assert (
                coaching_after.json()["focus"] != "prerequisite_review"
            ), f"선수가 풀렸는데 코칭이 여전히 선수 복습이다: {coaching_after.json()}"
            nxt = client.get("/v1/me/next-problem?prioritize_weak_concepts=true", headers=auth)
            assert nxt.status_code == 200, nxt.text
            assert nxt.json()["problem_id"] in {
                str(p) for p in pids_top
            }, f"복귀 추천이 후행 개념 문항이 아니다: {nxt.json()}"
            _snapshot(client, auth, "B", "5-return")
            _step(
                "B",
                "5-return",
                f"선수 gap 0건 · coaching.focus={coaching_after.json()['focus']} · "
                f"추천={nxt.json()['problem_id']}({code_top})",
            )
    finally:
        _teardown(
            "persona-b",
            concept_ids=[cid_pre, cid_top],
            problem_ids=pids_pre + pids_top,
            skill_ids=[skill_pre, skill_top],
            codes=[code_pre, code_top],
        )


# ── 페르소나 C — 특정 오개념 ─────────────────────────────────────────────────────────


def test_persona_c_misconception_confidence_decreases() -> None:
    """C: 오답 패턴 → detection → corrective explanation → targeted problem → **감소**."""
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 판정 불가(WHYMATH_DATABASE_URL 확인). 통과가 아니다.")
    asyncio.run(reset_store())

    sfx = uuid.uuid4().hex[:8]
    cid = uuid.uuid4()
    code = f"UC.p15c.{sfx}"
    skill_id = f"skill.p15c.{sfx}"
    pids = [uuid.uuid4() for _ in range(4)]

    try:
        _seed_concept(cid, code, skill_id, pids, f"{sfx}c", 3.0)

        with _client() as client:
            _erase(client, "persona-c")
            auth = _login(client, "persona-c")
            uid = _user_id("persona-c")
            _step("C", "0-account", f"user_id={uid} · 가설 {len(_hypotheses(uid))}건")

            # ── 1) 특정 오답 패턴 — 같은 거짓형을 **두 번** 인스턴스화한다. ───────────
            # 두 번인 이유가 판정과 직결된다: 교정 발화 사다리(`select_rung`)는
            # `evidence_count >= 2`부터 `corrective_explanation`을 낸다. 1회 오답이면
            # rung이 none이라 3)의 교정 마디가 성립하지 않는다(2026-09-19 실측).
            for pid in pids[:2]:
                _attempt(client, auth, pid, correct=False, answer=_WRONG_ANSWER)
            _snapshot(client, auth, "C", "1-wrong-pattern")
            _step("C", "1-wrong-pattern", f"{_WRONG_ANSWER} 2회 · 문항 2건")

            # ── 2) misconception detection — 서버가 오답 문자열에서 거짓형을 찾는다. ──
            initial = _confidence_of(uid, _EXPECTED_MISCONCEPTION)
            detected = [h for h in _hypotheses(uid) if h[0] == _EXPECTED_MISCONCEPTION][0]
            assert detected[3] >= 2, f"증거 누적이 2건 미만이다: {detected}"
            state = client.get("/v1/me/learner-state", headers=auth)
            assert state.status_code == 200, state.text
            assert (
                _EXPECTED_MISCONCEPTION in state.json()["active_misconceptions"]
            ), f"가설은 있는데 학습자 상태에 실리지 않았다: {state.json()['active_misconceptions']}"
            _snapshot(client, auth, "C", "2-detected")
            _step(
                "C",
                "2-detected",
                f"{_EXPECTED_MISCONCEPTION} confidence={initial:.4f} · 증거 {detected[3]}건",
            )

            # ── 3) corrective explanation — 요청은 중립 발화뿐이다. ──────────────────
            opened = client.post(
                "/v1/coach/sessions",
                headers=auth,
                json={"student_input": "잘 모르겠어요", "problem_id": str(pids[0])},
            )
            assert opened.status_code == 201, opened.text
            intervention = opened.json().get("intervention")
            assert intervention is not None, (
                "교정 개입이 나오지 않았다 — 요청에 오개념 id도 힌트 단계도 싣지 않았으므로 "
                f"서버가 스스로 고를 근거는 영속된 가설뿐이다: {opened.json()}"
            )
            # `escalation_rung`은 `exclude=True`라 HTTP 응답에 **일부러** 실리지 않는다
            # (학생 대면 발화를 누적 횟수의 함수로 만들지 않기 위한 설계 — 정서적 낙인 금지).
            # 그래서 노출되는 축으로 단언한다: 서버가 *어느* 오개념을 교정하려는지가 핵심이다.
            assert intervention["misconception_id"] == _EXPECTED_MISCONCEPTION, intervention
            assert intervention["prompt"].strip(), intervention
            assert intervention["pattern"], intervention
            dialogue_id = opened.json()["dialogue_id"]
            after_coach = _confidence_of(uid, _EXPECTED_MISCONCEPTION)
            _snapshot(client, auth, "C", "3-corrective")
            _step(
                "C",
                "3-corrective",
                f"pattern={intervention['pattern']} · mid={intervention['misconception_id']} · "
                f"confidence {initial:.4f}→{after_coach:.4f}",
            )

            # ── 4) targeted problem — 미응답 문항으로 재시도하고 맞힌다. ─────────────
            nxt = client.get("/v1/me/next-problem", headers=auth)
            assert nxt.status_code == 200, nxt.text
            target = nxt.json()["problem_id"]
            assert target in {
                str(p) for p in pids[2:]
            }, f"targeted 문항이 미응답 후보에서 나오지 않았다: {nxt.json()}"
            _attempt(client, auth, uuid.UUID(target), correct=True)
            after_correct = _confidence_of(uid, _EXPECTED_MISCONCEPTION)
            # 정직한 관측: **정답 시도는 감쇠를 트리거하지 않는다**. 오개념 훑기가 정답이면
            # `NOT_RUN`이라 갱신 경로에 들어가지 않기 때문이다(`api/me.py`의 스캔 게이트).
            # 이 단언은 그 사실을 계약으로 고정한다 — 바뀌면 여기가 빨강이 된다.
            assert after_correct == after_coach, (
                f"정답 시도가 confidence를 움직였다({after_coach:.4f}→{after_correct:.4f}) — "
                "현행 설계에서는 움직이지 않는다. 해소됐으면 이 단언을 감소 단언으로 바꾼다."
            )
            _snapshot(client, auth, "C", "4-targeted")
            _step("C", "4-targeted", f"정답 제출 · confidence {after_correct:.4f}(불변)")

            # ── 5) confidence 감소 — 증거 없는 턴이 지나면 신뢰가 내려간다. ──────────
            turn = client.post(
                f"/v1/coach/sessions/{dialogue_id}/turns",
                headers=auth,
                json={"student_input": "이제 알 것 같아요"},
            )
            assert turn.status_code == 201, turn.text
            final = _confidence_of(uid, _EXPECTED_MISCONCEPTION)
            # **두 단언이 다른 것을 잰다.** 아래 `final < initial`만 두면 3)의 코치 세션이
            # 이미 떨어뜨려 둔 값 덕에 이 마디를 통째로 건너뛰어도 통과한다 — 즉 "증거 없는
            # 턴마다 계속 내려간다"가 아니라 "한 번 내려갔다"만 증명된다(2026-09-19 뮤테이션
            # M5로 실측: 이 턴을 생략해도 초록이었다). 그래서 *이 턴의 기여*를 먼저 단언한다.
            assert final < after_correct, (
                f"증거 없는 코치 턴이 지났는데 신뢰가 그대로다: {after_correct:.4f} → "
                f"{final:.4f}. 감쇠가 턴마다 적용되지 않으면 오개념이 영속 라벨이 된다."
            )
            assert final < initial, (
                f"오개념 신뢰가 내려가지 않았다: {initial:.4f} → {final:.4f}. 올라가기만 하면 "
                "보정이 작동하지 않은 것이다(원 문서 §11 판정 포인트)."
            )
            _snapshot(client, auth, "C", "5-confidence-down")
            _step(
                "C",
                "5-confidence-down",
                f"{initial:.4f} → {after_coach:.4f} → {final:.4f} "
                f"(감소 {initial - final:.4f} · 총 {(1 - final / initial) * 100:.1f}%)",
            )
    finally:
        _teardown(
            "persona-c",
            concept_ids=[cid],
            problem_ids=pids,
            skill_ids=[skill_id],
            codes=[code],
        )
