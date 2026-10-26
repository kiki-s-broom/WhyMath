"""SEC-24(원 SEC-15) — 무인증 응답의 정답류 비노출(공개 투영) 거버넌스 + 결함주입 테스트.

정본: `docs/reviews/functional_security_audit_2026-08-08.md` M1 ·
`schema/problem.py` `PublicProblem`/`PublicProblemStep`(`PUBLIC_HIDDEN_ANSWER_FIELDS`).

**계약**: 무인증 GET(problems 단건/목록/steps + gating 6종)의 응답 JSON에는 정답류
필드의 **키 자체가 없다**(값 None이 아니라 부재 — `PED-08`·ASM-07 선례). 관리자 표면
(POST/PATCH — `RequireContentAdmin`)은 전체 `Problem` 스키마를 유지한다.

세 층으로 동결한다(ASM-07 `test_prediction_field_sealing.py` 동형):
  ① 스키마 — 공개 모델에 정답류 필드가 없고, 내부 정본에는 그대로 있다. 상속 방향
     (`Problem` ⊂- `PublicProblem`)이 허용목록을 만든다 — 새 필드는 기본 비노출.
  ② 페이로드(결함주입) — 정답이 *채워진* 문제를 시딩하고도 공개 응답에 키가 없다.
  ③ 변별력(양성 대조) — 같은 데이터가 관리자 라우트 응답에는 값째 나온다(분리가 실제로
     변별됨 — 스캔이 0건을 보고도 green이면 위장이다).

ETag 오라클(SEC-24(원 SEC-15)): 공개 GET의 ETag는 공개 투영 기준이어야 한다 — 전체 스키마 해시면
공개 필드를 다 아는 공격자가 정답 후보를 오프라인 대입해 해시 일치로 정답을 복원한다.
"정답만 다른 두 문제의 공개 ETag가 같고 전체 해시는 다르다"로 양방향 변별을 동결한다.

가짜 세션·클라이언트 구성은 test_problems.py / test_gating.py 패턴 답습(hermetic·실 PG 0).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi.testclient import TestClient

from whymath_backend.api._auth import require_content_admin
from whymath_backend.api._concurrency import etag_for
from whymath_backend.app import create_app
from whymath_backend.db.models.problem import Problem, ProblemStep
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.schema.enums import Role
from whymath_backend.schema.problem import (
    PUBLIC_HIDDEN_ANSWER_FIELDS,
    PUBLIC_HIDDEN_OPS_FIELDS,
    PUBLIC_HIDDEN_STEP_ANSWER_FIELDS,
    PublicProblem,
    PublicProblemStep,
)
from whymath_backend.schema.problem import Problem as ProblemSchema
from whymath_backend.schema.problem import ProblemStep as ProblemStepSchema

_ADMIN_USER = UserProfile(user_id=uuid.uuid4(), role=Role.CONTENT_ADMIN)

#: 결함주입에 심는 정답 sentinel — 응답 어디에도 값으로도 나오면 안 된다.
_ANSWER_SENTINEL = "SEC15-answer-740"


def _full_schema(**over: object) -> ProblemSchema:
    """정답류 6필드가 **전부 채워진** 자체생성 문제(결함주입 픽스처).

    자체생성은 본문 보유 허용 출처라 정답류를 채워도 저작권 불변식을 통과한다 —
    "채워 넣고도 공개 응답에 안 나옴"이 이 파일의 결함주입 축이다.
    """
    kwargs: dict[str, object] = {
        "source_type": "자체생성",
        "review_status": "approved",  # 게이팅 검수 노출 게이트(PB-03) 통과용
        "curriculum_version": "2022_REVISION",
        "valid_from_year": 2022,
        "subject": "미적분",
        "unit_codes": ["CAL-INT-DEF"],
        "question_text": "적분값을 구하시오",
        "answer": _ANSWER_SENTINEL,
        "answer_explanation": "공식 해설(내부 전용)",
        "multiple_answers": {"alt": "x=2"},
        "answer_transform": {"type": "p_plus_q", "p": 3, "q": 5},
        "answer_constraint": {"min": 1, "max": 999, "is_natural": True},
        "distractor_map": [{"choice_index": 1, "misconception_id": "m-a"}],
    }
    kwargs.update(over)
    return ProblemSchema(**kwargs)  # type: ignore[arg-type]


def _full_step(problem_id: uuid.UUID) -> ProblemStep:
    """기대답·흔한실수(힌트류)가 채워진 풀이 단계(결함주입 픽스처)."""
    return ProblemStep.from_schema(
        ProblemStepSchema(
            problem_id=problem_id,
            step_order=1,
            step_title="조건 해석",
            socratic_prompt="조건 (가)를 수식으로 표현해보세요",
            expected_answer=_ANSWER_SENTINEL,
            common_mistakes=[{"error": "부호 실수", "hint": "양변 확인"}],
        )
    )


# ── 가짜 세션(test_problems.py 패턴 — 라우터가 부르는 표면만) ──────────────
class _FakeScalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._rows)


class FakeSession:
    def __init__(
        self,
        get_map: dict[uuid.UUID, Problem] | None = None,
        list_rows: list[Any] | None = None,
    ) -> None:
        self._get_map = dict(get_map or {})
        self._list_rows = list(list_rows or [])
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        return None

    async def flush(self) -> None:
        return None

    async def refresh(self, obj: Any) -> None:
        return None

    async def merge(self, obj: Any) -> Any:
        return obj

    async def get(self, model: Any, pk: uuid.UUID) -> Problem | None:
        return self._get_map.get(pk)

    async def execute(self, stmt: Any) -> _FakeResult:
        return _FakeResult(self._list_rows)


def _client(fake: FakeSession) -> TestClient:
    """get_session 가짜 + require_content_admin 고정 관리자(양성 대조 라우트용)."""
    app = create_app()

    async def _override() -> AsyncIterator[FakeSession]:
        yield fake

    app.dependency_overrides[get_session] = _override
    app.dependency_overrides[require_content_admin] = lambda: _ADMIN_USER
    return TestClient(app)


# ──────────────────────────────────────────────────────────────────────
# ① 스키마 계층 — 필드 분류의 완전성·방향
# ──────────────────────────────────────────────────────────────────────
class TestSchemaLevelSeal:
    def test_public_model_has_no_answer_fields(self) -> None:
        """PublicProblem에_정답류_6필드가_없다(키 부재가 계약)."""
        leaked = set(PublicProblem.model_fields) & PUBLIC_HIDDEN_ANSWER_FIELDS
        assert leaked == set(), f"공개 모델에 정답류 필드가 남아 있습니다: {sorted(leaked)}"

    def test_internal_model_still_has_them(self) -> None:
        """Problem(내부 정본)은_6필드를_그대로_보유 — 비노출은 노출 축이지 영속 축이 아니다."""
        missing = PUBLIC_HIDDEN_ANSWER_FIELDS - set(ProblemSchema.model_fields)
        assert missing == set(), f"내부 정본에서 사라진 필드: {sorted(missing)}"

    def test_classification_is_total(self) -> None:
        """분류_완전성 — 내부 정본 = 공개 투영 + 정답류 + **운영 메타**(잔여·중복 0).

        `Problem`에 새 필드가 붙으면: 기반(`PublicProblem`)에 붙으면 자동 공개(의도 확인
        후), 서브클래스에 붙으면 자동 비공개이나 이 단언이 red가 되어 두 분류 집합 중 하나에
        등재(분류 명시)를 강제한다 — 미분류 필드가 조용히 지나가지 못한다.

        **EOS-71 갱신**: 격리 운영 메타 2필드(`quarantine_reason`·`quarantined_at`)가 내부 정본에
        추가되면서 이 가드가 설계대로 red를 냈고, 그래서 `PUBLIC_HIDDEN_OPS_FIELDS`라는 **두 번째
        분류 집합**을 만들어 등재했다. 정답류에 밀어 넣지 않은 이유는 축이 다르기 때문이다 —
        정답류는 "교수학·보안상 학생에게 주면 안 되는 것", 운영 메타는 "운영자만 알면 되는 것".
        집합을 합치면 한 축의 완화 압력이 다른 축까지 조용히 연다(상수 주석 참조).
        """
        assert set(ProblemSchema.model_fields) - set(PublicProblem.model_fields) == (
            PUBLIC_HIDDEN_ANSWER_FIELDS | PUBLIC_HIDDEN_OPS_FIELDS
        )
        assert set(PublicProblem.model_fields) <= set(ProblemSchema.model_fields)
        # 두 분류 집합은 서로 겹치지 않는다(한 필드가 두 축으로 이중 등재되면 분류가 흐려진다).
        assert PUBLIC_HIDDEN_ANSWER_FIELDS & PUBLIC_HIDDEN_OPS_FIELDS == set()

    def test_public_model_has_no_ops_metadata_fields(self) -> None:
        """공개 모델에 격리 운영 메타가 없다(EOS-71) — 키 부재가 계약.

        `quarantine_reason`은 운영 판단 메모(실중복 판정·출제 오류 서술 등)라 무인증 GET에
        자리를 만드는 순간 그대로 공개된다. 애초에 샐 표면을 만들지 않는다.
        """
        leaked = set(PublicProblem.model_fields) & PUBLIC_HIDDEN_OPS_FIELDS
        assert leaked == set(), f"공개 모델에 운영 메타 필드가 남아 있습니다: {sorted(leaked)}"

    def test_step_classification_is_total(self) -> None:
        """steps도_동일_계약 — expected_answer·common_mistakes·common_errors만 내부 전용.

        이식 판정(main 드리프트): S4-09가 main에 추가한 `common_errors`(오개념 서술 목록)를
        허용목록 원칙에 따라 비공개 쪽에 뒀다 — 나머지 S4-09 additive 5종(구조 메타)은 공개.
        """
        assert (
            set(ProblemStepSchema.model_fields) - set(PublicProblemStep.model_fields)
            == PUBLIC_HIDDEN_STEP_ANSWER_FIELDS
        )
        leaked = set(PublicProblemStep.model_fields) & PUBLIC_HIDDEN_STEP_ANSWER_FIELDS
        assert leaked == set()

    def test_inheritance_direction_makes_allowlist(self) -> None:
        """상속_방향 — 내부 정본이 공개 투영을 상속(더하기)한다.

        방향이 반대(빼기)였다면 새 필드는 기본 노출이 된다(ASM-07 동일 논거).
        """
        assert issubclass(ProblemSchema, PublicProblem)
        assert issubclass(ProblemStepSchema, PublicProblemStep)

    def test_from_problem_drops_filled_values(self) -> None:
        """값이_채워져_있어도_변환에서_사라진다 — 모델 계층의 결함주입."""
        public = PublicProblem.from_problem(_full_schema())
        dumped = public.model_dump(mode="json")
        assert set(dumped) & PUBLIC_HIDDEN_ANSWER_FIELDS == set()
        assert _ANSWER_SENTINEL not in str(dumped)
        assert dumped["question_text"] == "적분값을 구하시오"  # 무력화 하한 — 본문은 공개 유지


# ──────────────────────────────────────────────────────────────────────
# ② 페이로드 계층 — 실제 HTTP 응답의 키 부재(결함주입)
# ──────────────────────────────────────────────────────────────────────
class TestPublicPayloadSeal:
    def test_get_single_has_no_answer_keys(self) -> None:
        """무인증_단건_GET — 정답류 6키 전부 부재 + sentinel 값 부재."""
        orm = Problem.from_schema(_full_schema())
        resp = _client(FakeSession(get_map={orm.problem_id: orm})).get(
            f"/v1/problems/{orm.problem_id}"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert (
            set(body) & PUBLIC_HIDDEN_ANSWER_FIELDS == set()
        ), f"공개 단건 응답에 정답류 키: {sorted(set(body) & PUBLIC_HIDDEN_ANSWER_FIELDS)}"
        assert _ANSWER_SENTINEL not in resp.text
        assert body["question_text"] == "적분값을 구하시오"  # 카탈로그(본문)는 계속 공개(D1 유지)

    def test_get_list_has_no_answer_keys(self) -> None:
        """무인증_목록_GET — 각 원소에 정답류 키 부재."""
        orm = Problem.from_schema(_full_schema())
        resp = _client(FakeSession(list_rows=[orm])).get("/v1/problems")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1  # 무력화 하한 — 빈 목록이면 아래 단언이 공허하다
        assert set(items[0]) & PUBLIC_HIDDEN_ANSWER_FIELDS == set()
        assert _ANSWER_SENTINEL not in resp.text

    def test_get_steps_has_no_answer_keys(self) -> None:
        """무인증_steps_GET — expected_answer·common_mistakes 키 부재, 소크라테스 발문 유지."""
        orm = Problem.from_schema(_full_schema())
        step = _full_step(orm.problem_id)
        resp = _client(FakeSession(get_map={orm.problem_id: orm}, list_rows=[step])).get(
            f"/v1/problems/{orm.problem_id}/steps"
        )
        assert resp.status_code == 200, resp.text
        items = resp.json()
        assert len(items) == 1
        assert set(items[0]) & PUBLIC_HIDDEN_STEP_ANSWER_FIELDS == set()
        assert _ANSWER_SENTINEL not in resp.text
        # 교수학 자산(답 미제공 발문)은 공개 유지 — 봉인 과확대 방지.
        assert items[0]["socratic_prompt"] == "조건 (가)를 수식으로 표현해보세요"

    def test_gating_metacognition_uses_signal_but_hides_it(self) -> None:
        """게이팅 — distractor_map을 *신호로 쓰되* 응답에는 키째 싣지 않는다(양면 변별).

        메타인지 주신호가 distractor_map 존재라, 이 문항이 응답에 *등장*했다는 사실
        자체가 게이팅 입력은 전체 스키마임을 입증하고, 등장한 원소에 그 키가 *없다*는
        것이 공개 투영 변환을 입증한다.
        """
        orm = Problem.from_schema(_full_schema(persona_fit={"A_일반고고3": 0.9}))
        resp = _client(FakeSession(list_rows=[orm])).get("/v1/gating/metacognition")
        assert resp.status_code == 200, resp.text
        items = resp.json()
        assert len(items) == 1, "distractor_map 신호가 게이팅에 전달되지 않았다(입력 축 붕괴)"
        assert set(items[0]) & PUBLIC_HIDDEN_ANSWER_FIELDS == set()
        assert _ANSWER_SENTINEL not in resp.text

    def test_openapi_advertises_public_models_on_unauth_routes(self) -> None:
        """OpenAPI_문서_축 — 무인증 GET들이 Public 모델을 광고하고 정답류 속성이 없다."""
        openapi = create_app().openapi()
        schemas = openapi["components"]["schemas"]
        assert "PublicProblem" in schemas and "PublicProblemStep" in schemas
        for name in ("PublicProblem", "PublicProblemStep"):
            props = set(schemas[name].get("properties", {}))
            assert props, f"{name} 속성 스캔이 비었다(무력화 하한)"
            assert props & (PUBLIC_HIDDEN_ANSWER_FIELDS | PUBLIC_HIDDEN_STEP_ANSWER_FIELDS) == set()


# ──────────────────────────────────────────────────────────────────────
# ③ 변별력 — 관리자 표면(전체 스키마)에는 값째 나온다(양성 대조)
# ──────────────────────────────────────────────────────────────────────
class TestAdminSurfaceKeepsFullSchema:
    def test_admin_post_response_contains_answer(self) -> None:
        """관리자_POST — 같은 데이터가 전체 스키마로 돌아온다(분리가 실제로 변별됨)."""
        # LIC-09 — 자체생성 POST는 provenance 좌석 동반 필수.
        # ADMIN-19 — 생성 시 review_status는 미설정/pending만 허용(픽스처 기본값 approved는 422).
        body = {
            **_full_schema(review_status="pending").model_dump(mode="json"),
            "provenance": {"generation_type": "FULLY_GENERATED", "license": "WHYMATH_GENERATED"},
        }
        resp = _client(FakeSession()).post("/v1/problems", json=body)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["answer"] == _ANSWER_SENTINEL
        assert body["answer_explanation"] == "공식 해설(내부 전용)"
        assert body["distractor_map"] == [
            {"choice_index": 1, "misconception_id": "m-a", "op_code": None}
        ]

    def test_admin_patch_response_contains_answer(self) -> None:
        """관리자_PATCH — 정답 수정 결과가 응답에 값째 보인다(관리 워크플로 유지)."""
        orm = Problem.from_schema(_full_schema())
        resp = _client(FakeSession(get_map={orm.problem_id: orm})).patch(
            f"/v1/problems/{orm.problem_id}", json={"answer": "42"}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["answer"] == "42"


# ──────────────────────────────────────────────────────────────────────
# ETag 오라클 차단 — 공개 ETag는 공개 투영의 함수다
# ──────────────────────────────────────────────────────────────────────
class TestEtagOracle:
    def test_answer_only_difference_yields_same_public_etag(self) -> None:
        """정답만_다른_두_문제 — 공개 ETag 동일(오라클 차단)·전체 해시는 상이(변별).

        전체 스키마 해시를 ETag로 노출하면 공개 필드를 다 아는 공격자가 정답 후보
        (예: 단답형 1~999)를 대입해 해시 일치로 정답을 복원할 수 있다. 공개 투영 기준
        ETag는 정답과 독립이라 그 채널이 닫힌다.
        """
        base = _full_schema()
        other = base.model_copy(update={"answer": "999"})
        assert etag_for(PublicProblem.from_problem(base)) == etag_for(
            PublicProblem.from_problem(other)
        )
        # 변별력 — 전체 스키마 해시는 실제로 정답에 반응한다(위 단언이 공허하지 않음).
        assert etag_for(base) != etag_for(other)

    def test_get_etag_matches_public_projection_hash(self) -> None:
        """공개_GET의_ETag가_공개_투영_해시와_일치 — 라우터가 전체 스키마로 계산하지 않는다."""
        orm = Problem.from_schema(_full_schema())
        resp = _client(FakeSession(get_map={orm.problem_id: orm})).get(
            f"/v1/problems/{orm.problem_id}"
        )
        assert resp.status_code == 200
        assert resp.headers["ETag"] == etag_for(PublicProblem.from_problem(orm.to_schema()))
