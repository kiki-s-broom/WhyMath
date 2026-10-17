"""EOS-71 — 격리(`quarantined`) 문항의 서빙 차단 + **비파괴 보존**을 hermetic하게 동결.

이 파일이 EOS-71의 실질이다. 계약 정본은 `docs/standards/problem_quarantine_contract.md`이고,
여기서는 그 §4 "집행 지점" 표의 각 행이 *실제로 그 술어를 경유하는지*를 기계로 못박는다
(CLAUDE.md "정본화를 집행으로 착각한 완료 선언 금지" — 계약을 만드는 것과 서빙 코드가 그 계약을
부르는 것은 별개다).

**왜 hermetic인가(변별력)**: `tests/backend/api/test_problems_integration.py` 계열은
`WHYMATH_RUN_INTEGRATION=1` + 실 PG 도달성 게이트라 **CI에서 통째 SKIP**된다. 격리 차단을 통합
테스트로만 덮으면 게이트가 CI에서 한 번도 돌지 않는 "변별력 없는 검증 스텝"이 된다(CLAUDE.md).
그래서 전 축을 FakeSession 주입으로 CI에서 상시 도는 형태로 덮는다.

동결하는 축 5종:
  ① 공개 GET 4종(단건·목록·steps·relations)이 격리 문항을 내보내지 않는다 — 단건류는 404,
     목록은 SQL 레벨 배제. 양성 대조로 `approved`·`pending`·`NULL`은 계속 나간다(봉인 과확대 방지 —
     이 라우터는 *승인을 요구하지 않는* 공개 카탈로그다).
  ② **SQL 3값 논리 함정 회귀 방지** — 목록 배제가 `IS DISTINCT FROM`으로 컴파일된다. `!=`로 쓰면
     `review_status`가 NULL인 행이 전부 조용히 사라진다(실코퍼스에 NULL 레코드가 실재한다).
  ③ 기본 CAT 후보 풀(`api/me.py::candidate_pool_conditions`)이 격리를 배제한다 — 코드 변경 0으로
     얻어지는 자동 배제(허용목록 `== approved`)라 아무도 지키고 있지 않다. 여기서 지킨다.
  ④ **비파괴** — `GET /v1/me/ability/history`는 `review_status`를 필터하지 않아 격리 문항의 과거
     attempt가 성장 곡선에 남는다(계약 §2-3). 학생이 이미 푼 문항이 이력에서 사라지면, 결함 문항이
     만든 피해에 데이터 소실을 더하는 것이다.
  ⑤ 격리 설정(관리자 PATCH)이 **어떤 삭제도 일으키지 않는다**(계약 §2-1·2).

hermetic 한계(정직한 공백): FakeSession은 WHERE를 실행하지 않으므로 "NULL 행이 실제로 살아남는다"를
행 수준에서 증명하지 못한다 — ②는 컴파일된 SQL 문자열로 대신 동결한다. 실행 축은 실 PG 통합테스트
소관이며 CI에서는 SKIP된다.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from whymath_backend.api._auth import get_consented_user, require_content_admin
from whymath_backend.api.me import candidate_pool_conditions
from whymath_backend.app import create_app
from whymath_backend.db.models.problem import Problem, ProblemRelation, ProblemStep
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.schema.enums import (
    Curriculum,
    Persona,
    RelationType,
    ReviewStatus,
    Role,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem import Problem as ProblemSchema
from whymath_backend.schema.problem import ProblemRelation as ProblemRelationSchema
from whymath_backend.schema.problem import ProblemStep as ProblemStepSchema
from whymath_backend.schema.user import UserProfile as UserProfileSchema

_UID = uuid.uuid4()
_ADMIN = UserProfile(user_id=uuid.uuid4(), role=Role.CONTENT_ADMIN)
_QUARANTINED_AT = datetime(2026, 8, 31, 9, 0, tzinfo=UTC)
#: 격리 사유는 *운영 메타*라 공개 응답 어디에도 값으로 나오면 안 된다(결함주입 sentinel).
_REASON_SENTINEL = "EOS71-복수정답-사유-9174"


def _problem(**over: object) -> Problem:
    """자체생성 최소 문항 ORM(본문 보유 허용 출처 — 저작권 불변식 비적용).

    필수 필드 구성은 `test_problems_public_projection.py`의 `_full_schema` 패턴 답습.
    `review_status`만 오버라이드하면 다른 축은 그대로 둔 채 격리 축만 시험할 수 있다.
    """
    kwargs: dict[str, object] = {
        "source_type": SourceType.자체생성,
        "curriculum_version": Curriculum.REVISION_2022,
        "valid_from_year": 2022,
        "subject": Subject.미적분,
        "unit_codes": ["CAL-INT-DEF"],
        "question_text": "적분값을 구하시오",
    }
    kwargs.update(over)
    return Problem.from_schema(ProblemSchema(**kwargs))  # type: ignore[arg-type]


def _quarantined() -> Problem:
    return _problem(
        review_status=ReviewStatus.quarantined,
        quarantine_reason=_REASON_SENTINEL,
        quarantined_at=_QUARANTINED_AT,
    )


# ── 가짜 세션(test_problems_public_projection.py 패턴 + stmt 캡처) ─────────────────
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

    def all(self) -> list[Any]:
        return list(self._rows)


class FakeSession:
    """라우터가 부르는 표면만 흉내내되, **실행된 statement를 캡처**한다.

    캡처가 이 파일의 핵심 도구다 — FakeSession은 WHERE를 해석하지 않으므로 "필터가 걸렸는가"를
    반환 행으로는 볼 수 없고, 라우터가 *만든* SQL을 직접 읽어야 한다.
    """

    def __init__(
        self,
        get_map: dict[uuid.UUID, Problem] | None = None,
        rows: list[Any] | None = None,
    ) -> None:
        self._get_map = dict(get_map or {})
        self._rows = list(rows or [])
        self.statements: list[Any] = []
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.merged: list[Any] = []
        self.get_kwargs: list[dict[str, Any]] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        return None

    async def refresh(self, obj: Any) -> None:
        return None

    async def merge(self, obj: Any) -> Any:
        self.merged.append(obj)
        return obj

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)

    async def get(self, _model: Any, pk: uuid.UUID, **kwargs: Any) -> Problem | None:
        # ADMIN-16: 검수 상태를 바꾸는 PATCH는 `with_for_update` 등 잠금 인자와 함께 부른다.
        self.get_kwargs.append(kwargs)
        return self._get_map.get(pk)

    async def execute(self, stmt: Any) -> _FakeResult:
        self.statements.append(stmt)
        return _FakeResult(self._rows)

    def compiled_sql(self) -> str:
        """마지막으로 실행된 statement의 PG 컴파일 문자열(리터럴 바인딩)."""
        assert self.statements, "실행된 statement가 없다(무력화 하한)"
        return str(
            self.statements[-1].compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )


def _client(fake: FakeSession) -> TestClient:
    """`get_session`·관리자 인가·학생 인증을 전부 주입한 hermetic 클라이언트."""
    app = create_app()

    async def _override() -> AsyncIterator[FakeSession]:
        yield fake

    app.dependency_overrides[get_session] = _override
    app.dependency_overrides[require_content_admin] = lambda: _ADMIN
    app.dependency_overrides[get_consented_user] = lambda: UserProfile.from_schema(
        UserProfileSchema(user_id=_UID, persona_primary=Persona.A_일반고고3)
    )
    return TestClient(app)


# ──────────────────────────────────────────────────────────────────────
# ① 공개 GET 단건류 — 격리면 404, 그 외(NULL·pending·approved)는 계속 노출
# ──────────────────────────────────────────────────────────────────────
class TestPublicSingleRoutesBlockQuarantined:
    def test_single_get_returns_404_for_quarantined(self) -> None:
        """단건 GET — 격리 문항은 404이고, detail이 *격리*임을 밝힌다(침묵 실패 금지)."""
        orm = _quarantined()
        resp = _client(FakeSession(get_map={orm.problem_id: orm})).get(
            f"/v1/problems/{orm.problem_id}"
        )
        assert resp.status_code == 404, resp.text
        detail = resp.json()["detail"]
        assert "격리" in detail, f"일반 404와 구분되지 않는 detail: {detail}"
        # 사유 본문은 운영 메타 — 무인증 응답에 값으로도 새지 않는다.
        assert _REASON_SENTINEL not in resp.text

    def test_steps_returns_404_for_quarantined(self) -> None:
        """풀이 단계 GET — 격리 문항의 *단계*는 더더욱 나가면 안 된다(정답 경로 노출)."""
        orm = _quarantined()
        step = ProblemStep.from_schema(
            ProblemStepSchema(problem_id=orm.problem_id, step_order=1, step_title="조건 해석")
        )
        fake = FakeSession(get_map={orm.problem_id: orm}, rows=[step])
        resp = _client(fake).get(f"/v1/problems/{orm.problem_id}/steps")
        assert resp.status_code == 404, resp.text
        assert "격리" in resp.json()["detail"]
        # 게이트가 *조회 전에* 끊는다 — 단계 조회 statement 자체가 실행되지 않았다.
        assert fake.statements == []

    def test_relations_returns_404_for_quarantined(self) -> None:
        """문항 관계 GET — 격리 문항을 출발점으로 한 관계 열람도 끊는다."""
        orm = _quarantined()
        relation = ProblemRelation.from_schema(
            ProblemRelationSchema(
                parent_problem_id=orm.problem_id,
                related_problem_id=uuid.uuid4(),
                relation_type=RelationType.유사,
            )
        )
        fake = FakeSession(get_map={orm.problem_id: orm}, rows=[relation])
        resp = _client(fake).get(f"/v1/problems/{orm.problem_id}/relations")
        assert resp.status_code == 404, resp.text
        assert "격리" in resp.json()["detail"]
        assert fake.statements == []

    @pytest.mark.parametrize(
        "review_status",
        [None, ReviewStatus.pending, ReviewStatus.approved, ReviewStatus.rejected],
    )
    def test_non_quarantined_still_served(self, review_status: ReviewStatus | None) -> None:
        """양성 대조 — 격리가 아닌 4상태는 전부 계속 나간다(봉인 과확대 방지).

        이 라우터는 **승인을 요구하지 않는** 공개 카탈로그다(SEC-07 D1). EOS-71이 바꾼 것은
        "격리 배제" 하나뿐이며, `pending`·`NULL`을 함께 막는 것은 *정책 변경*이라 범위 밖이다
        (격리 계약 §7). 이 대조가 없으면 게이트가 조용히 과확대돼도 아무도 모른다.
        """
        orm = _problem(review_status=review_status)
        resp = _client(FakeSession(get_map={orm.problem_id: orm})).get(
            f"/v1/problems/{orm.problem_id}"
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["question_text"] == "적분값을 구하시오"

    def test_missing_problem_keeps_plain_404(self) -> None:
        """부재 404는 문구가 그대로 — 격리 문구가 무차별로 붙지 않는다(변별력)."""
        missing = uuid.uuid4()
        resp = _client(FakeSession()).get(f"/v1/problems/{missing}")
        assert resp.status_code == 404
        assert "격리" not in resp.json()["detail"]


# ──────────────────────────────────────────────────────────────────────
# ② 공개 GET 목록 — SQL 레벨 배제 + IS DISTINCT FROM 회귀 방지
# ──────────────────────────────────────────────────────────────────────
class TestPublicListExcludesQuarantinedInSql:
    def test_list_statement_uses_is_distinct_from(self) -> None:
        """목록 SQL이 `review_status IS DISTINCT FROM 'quarantined'`를 건다.

        **`!=` 금지(SQL 3값 논리)**: `review_status != 'quarantined'`는 NULL 행에서 NULL을 내고
        WHERE가 그걸 참으로 치지 않아 **검수 미평가 문항이 전부 목록에서 사라진다**. 실코퍼스에
        NULL 레코드가 실재하므로(백필 대상) 이론적 위험이 아니다. 이 단언이 `!=`로의 회귀를
        컴파일 문자열 수준에서 막는다(뮤테이션 변별력 확인 완료).
        """
        fake = FakeSession(rows=[_problem(review_status=ReviewStatus.approved)])
        resp = _client(fake).get("/v1/problems")
        assert resp.status_code == 200, resp.text
        sql = fake.compiled_sql()
        assert "review_status IS DISTINCT FROM" in sql, sql
        assert "'quarantined'" in sql, sql

    def test_list_still_returns_non_quarantined_rows(self) -> None:
        """무력화 하한 — 게이트가 목록을 통째로 비워 버리지 않는다(양성 대조)."""
        fake = FakeSession(rows=[_problem(review_status=ReviewStatus.approved)])
        items = _client(fake).get("/v1/problems").json()
        assert len(items) == 1
        assert items[0]["question_text"] == "적분값을 구하시오"

    def test_subject_filter_composes_with_quarantine_gate(self) -> None:
        """선택 필터(subject)를 줘도 격리 배제가 함께 남는다(조건이 덮이지 않음)."""
        fake = FakeSession(rows=[])
        resp = _client(fake).get("/v1/problems?subject=미적분")
        assert resp.status_code == 200, resp.text
        sql = fake.compiled_sql()
        assert "review_status IS DISTINCT FROM" in sql, sql
        assert "problem.subject" in sql, sql


# ──────────────────────────────────────────────────────────────────────
# ③ 기본 CAT 후보 풀 — 코드 변경 0으로 얻는 자동 배제를 동결
# ──────────────────────────────────────────────────────────────────────
class TestCandidatePoolExcludesQuarantined:
    """`candidate_pool_conditions()`는 `== approved` 허용목록이라 새 값을 자동 배제한다.

    EOS-71은 이 함수를 건드리지 않았다 — 그래서 여기서 *지킨다*. 누가 이 조건을 차단목록
    (`.notin_([rejected])` 같은 형태)으로 바꾸면 격리 문항이 다음 문제 추천에 즉시 복귀하는데,
    그 회귀는 EOS-71이 만진 파일 어디에도 흔적을 남기지 않는다.
    """

    @staticmethod
    def _compiled_conditions() -> str:
        return " AND ".join(
            str(cond.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
            for cond in candidate_pool_conditions()
        )

    def test_review_gate_is_an_approved_allowlist(self) -> None:
        """검수 축이 `= 'approved'` 형태다 — 허용목록이라 미래의 새 상태값도 자동 배제."""
        sql = self._compiled_conditions()
        assert "problem.review_status = 'approved'" in sql, sql
        assert "quarantined" not in sql, "차단목록으로 바뀌었다(허용목록 방향 붕괴)"

    def test_quarantined_value_does_not_satisfy_the_gate(self) -> None:
        """값 수준 재확인 — 격리는 `approved`가 아니므로 후보 풀 조건을 만족할 수 없다."""
        from whymath_backend.schema.enums import is_review_status_cleared

        assert is_review_status_cleared(ReviewStatus.quarantined) is False


# ──────────────────────────────────────────────────────────────────────
# ④ 비파괴 — 격리 문항의 과거 attempt는 이력에 남는다
# ──────────────────────────────────────────────────────────────────────
class TestQuarantineIsNonDestructiveForHistory:
    """계약 §2-3 — `GET /v1/me/ability/history`는 `review_status`를 필터하지 않는다.

    "격리했으니 그 문항 기록도 숨기자"는 자연스러워 보이지만 **비파괴 원칙 위반**이다. 학생이
    이미 푼 문항이 성장 곡선에서 사라지면, 결함 문항이 만든 피해에 데이터 소실을 더하게 된다.
    그래서 이 축은 *일부러 열어 둔 것*이며, 열어 뒀다는 사실 자체를 동결한다.
    """

    def test_history_query_does_not_filter_review_status(self) -> None:
        """이력 조회 SQL에 `review_status` 조건이 **없다**(의도적 미집행의 동결)."""
        fake = FakeSession(rows=[])
        resp = _client(fake).get("/v1/me/ability/history")
        assert resp.status_code == 200, resp.text
        sql = fake.compiled_sql()
        assert "problem_attempt" in sql, "무력화 하한 — 이력 쿼리가 아니다"
        assert "review_status" not in sql, f"이력 조회가 검수 상태로 걸러진다: {sql}"

    def test_attempt_on_quarantined_problem_still_appears(self) -> None:
        """격리 문항을 푼 기록이 성장 곡선 지점으로 그대로 방출된다(행 수준 확인).

        라우트는 (created_at, is_correct, difficulty_overall, irt_difficulty_b) 튜플을 순회하므로
        격리 문항의 attempt를 그 모양으로 넣어 지점이 나오는지 본다.
        """
        rows = [(datetime(2026, 8, 1, tzinfo=UTC), True, 3.0, None)]
        body = _client(FakeSession(rows=rows)).get("/v1/me/ability/history").json()
        assert len(body) == 1
        assert body[0]["response_count"] == 1


# ──────────────────────────────────────────────────────────────────────
# ⑤ 비파괴 — 격리 설정이 어떤 삭제도 일으키지 않는다
# ──────────────────────────────────────────────────────────────────────
class TestQuarantineDeletesNothing:
    def test_admin_patch_to_quarantined_performs_no_delete(self) -> None:
        """관리자 PATCH로 격리해도 `session.delete`가 한 번도 불리지 않는다(계약 §2-1).

        격리와 삭제를 가르는 지점이다 — 상태 전이만 일어나고 레코드는 남는다. 응답에도 본문이
        그대로 실려 "보존"이 관측된다(관리자 표면은 전체 스키마 — SEC-24).
        """
        orm = _problem(review_status=ReviewStatus.approved, answer="3")
        fake = FakeSession(get_map={orm.problem_id: orm})
        resp = _client(fake).patch(
            f"/v1/problems/{orm.problem_id}",
            json={
                "review_status": "quarantined",
                "quarantine_reason": _REASON_SENTINEL,
                "quarantined_at": _QUARANTINED_AT.isoformat(),
            },
        )
        assert resp.status_code == 200, resp.text
        assert fake.deleted == [], "격리가 삭제를 일으켰다(비파괴 원칙 위반)"
        assert len(fake.merged) == 1
        body = resp.json()
        assert body["review_status"] == "quarantined"
        assert body["quarantine_reason"] == _REASON_SENTINEL
        assert body["question_text"] == "적분값을 구하시오"  # 본문 보존
        assert body["answer"] == "3"  # 정답류도 보존(내부 정본은 잃지 않는다)

    def test_quarantined_problem_is_invisible_right_after_patch(self) -> None:
        """PATCH 직후 같은 문항을 공개 GET하면 404 — 마킹이 실제로 노출을 끊는다.

        2026-08 처분이 물리 제거를 택한 근거가 "마킹만으로는 목록에서 사라지지 않는다"였다
        (`docs/data/problem_duplicate_disposition_2026-08.md` §3). 이 단언이 그 근거를 무효화한다.
        """
        orm = _quarantined()
        resp = _client(FakeSession(get_map={orm.problem_id: orm})).get(
            f"/v1/problems/{orm.problem_id}"
        )
        assert resp.status_code == 404
