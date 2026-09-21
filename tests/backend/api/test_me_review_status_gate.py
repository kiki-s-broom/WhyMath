"""기본 CAT(`/v1/me/next-problem`, mode 미지정) — PB-03 축①+② SQL 게이트 단위테스트(hermetic).

검증:
  ① 저작권 노출 게이트 — `candidate_stmt`가 `Problem.source_type NOT IN (평가원·EBS·교과서)`
     조건을 실제로 포함하는가.
  ② 검수 노출 게이트 — 같은 `candidate_stmt`가 `Problem.review_status = 'approved'` 조건을
     독립적으로 포함하는가(축①과 절대 하나로 합치지 않는다는 설계를 SQL 레벨에서 확인).

**방법 — 정직한 명시**: 이 sandbox엔 살아있는 Postgres가 없어(`test_me_integration.py`의
`_pg_reachable` 스킵 패턴과 동일 처지) 실PG 통합 테스트로 "그 문항이 실제로 후보에서
빠지는지"는 검증하지 못했다. 대신 `_QueueSession`(test_me.py의 hermetic 패턴 답습 — stmt를
캡처만 하고 무시)으로 라우터를 실제 호출해 **엔드포인트가 실행에 넘기는 진짜 SQLAlchemy
Select 객체**를 가로채고, PostgreSQL dialect로 리터럴 바인딩 컴파일한 SQL 문자열에 두 조건이
*그대로* 나타나는지 화이트박스로 검사한다(FakeSession이 stmt를 실행하지 않고 버리므로 WHERE
가 실제로 걸러내는지는 검증하지 못하지만, *그 조건이 쿼리에 실려 나가는지*는 이 방식으로
검증 가능 — `test_me.py` 모듈 docstring의 "FakeSession은 stmt를 무시하므로" 한계를 그대로
인정한 상태에서 최대한의 검증이다).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from whymath_backend.api._auth import get_consented_user
from whymath_backend.app import create_app
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.schema.enums import Persona
from whymath_backend.schema.user import UserProfile as UserProfileSchema

_UID = uuid.uuid4()


def _user() -> UserProfile:
    return UserProfile.from_schema(
        UserProfileSchema(user_id=_UID, persona_primary=Persona.A_일반고고3)
    )


class _AQResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> "_AQResult":
        return self

    def all(self) -> list[Any]:
        return self._rows

    def first(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None


class _CapturingQueueSession:
    """`_QueueSession`(test_me.py) 동형 + `execute`에 전달된 실제 Select 객체를 캡처.

    캡처만 하고 실행하지 않는다(hermetic) — 컴파일된 SQL 문자열 검사가 목적이지 실 DB
    필터링 검증이 아니다(그건 실PG 통합 테스트 몫 — 이 sandbox엔 없음, 모듈 docstring 참조).
    """

    def __init__(self, results: list[_AQResult]) -> None:
        self._results = results
        self._i = 0
        self.captured_stmts: list[Any] = []

    async def execute(self, stmt: Any) -> _AQResult:
        self.captured_stmts.append(stmt)
        result = self._results[self._i]
        self._i += 1
        return result

    async def get(self, _model: Any, _pk: Any) -> Any:
        """EOS-19: 핸들러가 정책 호출 전에 조립하는 `LearnerState`가 프로필을 단건 조회한다.

        None은 "프로필 없음"이라는 정합한 상태다 — 이 파일이 재는 것은 후보 SQL의 게이트 조건뿐.
        """
        return None

    def add(self, obj: Any) -> None:  # pragma: no cover — 이 라우트는 add를 쓰지 않음
        pass

    async def commit(self) -> None:  # pragma: no cover — 이 라우트는 commit을 쓰지 않음
        pass


#: EOS-19 — 핸들러가 정책을 부르기 **전에** 조립하는 `LearnerState`가 소비하는 결과 수.
#: 내역은 `tests/backend/api/test_me.py::_learner_state_results` docstring이 정본이다(개념 진단
#: 2 · 전과목 θ 1 · 활성 오개념 1 · 스킬 숙달 1). 이 파일은 후보 stmt를 *인덱스로* 집으므로
#: 그 앞단 수를 상수로 둔다 — 생 인덱스를 박아 두면 앞단이 하나 늘 때 엉뚱한 stmt를 검사한다.
_NP_STMT_BASE = 5


def _learner_state_results() -> list[_AQResult]:
    """LearnerState 조립분 자리 채움 — 전부 빈 결과(이력 없는 학생)."""
    return [_AQResult([]) for _ in range(_NP_STMT_BASE)]


def _client_with_session(session: _CapturingQueueSession) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_consented_user] = _user

    async def _sess() -> AsyncIterator[_CapturingQueueSession]:
        yield session

    app.dependency_overrides[get_session] = _sess
    return TestClient(app)


def _compiled_sql(stmt: Any) -> str:
    """PostgreSQL dialect·리터럴 바인딩으로 컴파일한 SQL 문자열(화이트박스 검사용)."""
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


class TestBaseCatCandidateStmtCopyrightAndReviewGates:
    def test_candidate_stmt_excludes_metadata_only_sources(self) -> None:
        """축① — candidate_stmt SQL에 source_type NOT IN (평가원·EBS·교과서) 조건이 실린다."""
        # execute 순서: ①채점 이력(빈 이력 → θ=0) ②기본 CAT candidate_stmt.
        session = _CapturingQueueSession(_learner_state_results() + [_AQResult([]), _AQResult([])])
        client = _client_with_session(session)

        resp = client.get("/v1/me/next-problem")

        assert resp.status_code == 200
        assert len(session.captured_stmts) == _NP_STMT_BASE + 2
        candidate_sql = _compiled_sql(session.captured_stmts[_NP_STMT_BASE + 1])
        assert "NOT IN" in candidate_sql
        for blocked in ("평가원", "EBS", "교과서"):
            assert blocked in candidate_sql, candidate_sql

    def test_candidate_stmt_requires_review_status_approved(self) -> None:
        """축② — 같은 candidate_stmt SQL에 review_status = 'approved' 조건이 독립적으로 실린다.

        축①(저작권)과 축②(검수)이 실제로 *별개* 조건절로 SQL에 나타나는지 확인 — 하나로
        합쳐지지 않았음을 SQL 문자열 레벨에서 재확인(설계 핵심 회귀 방지).
        """
        session = _CapturingQueueSession(_learner_state_results() + [_AQResult([]), _AQResult([])])
        client = _client_with_session(session)

        resp = client.get("/v1/me/next-problem")

        assert resp.status_code == 200
        candidate_sql = _compiled_sql(session.captured_stmts[_NP_STMT_BASE + 1])
        assert "review_status" in candidate_sql
        assert "'approved'" in candidate_sql
        # 축①·축②가 서로 다른 조건절(각자의 컬럼)로 남아 있는지 — 하나로 뭉개지지 않았다는
        # 증거로 두 컬럼명이 모두 별도로 등장해야 한다.
        assert "source_type" in candidate_sql and "review_status" in candidate_sql
