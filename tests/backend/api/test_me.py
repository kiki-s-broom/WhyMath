"""me 라우터 단위테스트 — /v1/me/{sessions,assessments,dialogues}(hermetic).

엔드포인트 결선(200·직렬화·401·빈[])을 검증한다. user_id 스코핑(WHERE) 정확성은 통합
테스트(test_me_integration.py)가 실 PG로 검증한다 — FakeSession은 stmt를 무시하므로.
"""

from __future__ import annotations

import asyncio
import base64
import math
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.api import me as me_module
from whymath_backend.api._auth import get_consented_user
from whymath_backend.api._crypto import SecretCipher
from whymath_backend.api._subject_capability_state import get_attempt_misconception_detector
from whymath_backend.api.me import (
    ConceptAbilityItem,
    NextProblemResponse,
    _add_ability_snapshot_if_attempts,
    _AttemptHistoryState,
    _weak_concept_weights,
    candidate_pool_conditions,
    candidate_pool_order_by,
)
from whymath_backend.app import create_app
from whymath_backend.config import get_settings
from whymath_backend.db.models.activity import LearningSession
from whymath_backend.db.models.assessment import (
    AbilitySnapshot,
    Assessment,
    ConceptMasteryHistory,
)
from whymath_backend.db.models.audit import DeletionAudit, PrivacyAudit
from whymath_backend.db.models.dialogue import Dialogue
from whymath_backend.db.models.evidence_event import EvidenceEvent
from whymath_backend.db.models.problem import Problem
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.l2.concept_diagnosis import ConceptDiagnosis
from whymath_backend.l2.learning_path import LearningPath, LearningStep
from whymath_backend.l2.recommendation_evidence import (
    EVENT_TYPE_RECOMMENDATION_TREATMENT,
    META_KEY_APPLIED_WEIGHTS,
    META_KEY_CANDIDATES,
    META_KEY_MODE,
    META_KEY_POLICY_VERSION,
    META_KEY_POOL_SIZE,
    META_KEY_PROBLEM_ID,
    META_KEY_REASON,
    POLICY_VERSION_CAT,
    POLICY_VERSION_SUNEUNG,
)
from whymath_backend.l2.strong_concept_recommendation import StrongConceptRecommendation
from whymath_backend.l2.weak_concept_recommendation import WeakConceptRecommendation
from whymath_backend.l4.misconception.hypothesis import MisconceptionHypothesis
from whymath_backend.schema.activity import LearningSession as LearningSessionSchema
from whymath_backend.schema.assessment import (
    STUDENT_HIDDEN_PREDICTION_FIELDS,
)
from whymath_backend.schema.assessment import AbilitySnapshot as AbilitySnapshotSchema
from whymath_backend.schema.assessment import Assessment as AssessmentSchema
from whymath_backend.schema.assessment import (
    ConceptMasteryHistory as ConceptMasteryHistorySchema,
)
from whymath_backend.schema.assessment import (
    StudentAssessment as StudentAssessmentSchema,
)
from whymath_backend.schema.audit import DeletionAudit as DeletionAuditSchema
from whymath_backend.schema.audit import PrivacyAudit as PrivacyAuditSchema
from whymath_backend.schema.dialogue import Dialogue as DialogueSchema
from whymath_backend.schema.enums import (
    AssessmentType,
    AuditEventKind,
    AuditResourceType,
    Curriculum,
    EventType,
    ExamType,
    Persona,
    Resolution,
    ReviewStatus,
    SignaturePattern,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem import Problem as SchemaProblem
from whymath_backend.schema.user import UserProfile as UserProfileSchema

_UID = uuid.uuid4()


def _user() -> UserProfile:
    return UserProfile.from_schema(
        UserProfileSchema(user_id=_UID, persona_primary=Persona.A_일반고고3)
    )


class _Scalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)

    def scalar(self) -> int:
        # slice 71: count(*) 쿼리 시뮬 — FakeSession은 stmt를 무시하므로 행 수를 총 건수로
        # 흉내(정확한 필터 적용 count는 통합테스트가 실 PG로 검증). 헤더 결선·숫자성만 본다.
        return len(self._rows)

    def all(self) -> list[Any]:
        # slice L2-5d: join 쿼리(select(CMH, code, name))는 result.all()로 Row 튜플 순회.
        # /mastery/current 테스트는 (cmh, code, name) 튜플 리스트를 그대로 전달(_snapshot_row).
        return list(self._rows)


class FakeSession:
    def __init__(
        self,
        rows: list[Any] | None = None,
        get_map: dict[uuid.UUID, Any] | None = None,
    ) -> None:
        self._rows = list(rows or [])
        # slice 50: session.get(LearningSession, session_id) 시뮬
        self._get_map = get_map or {}
        self.commits = 0
        # slice 51: session.delete(row) 캡처
        self.deleted: list[Any] = []
        # slice 57: session.add(DeletionAudit) 캡처(AsyncSession.add는 동기)
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def execute(self, stmt: Any) -> _Result:
        return _Result(self._rows)

    async def get(self, _model: Any, pk: Any) -> Any:
        return self._get_map.get(pk)

    async def commit(self) -> None:
        self.commits += 1

    async def flush(self) -> None:
        """EOS-103: 진단 캡처가 같은 트랜잭션 안에서 LearnerState 행을 flush한다.

        commit과 달리 회계하지 않는다 — 이 대역이 재는 것은 "몇 번 커밋했는가"이고
        flush는 그 안의 중간 단계다.
        """

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)
        # PK로 찾아 get_map에서도 제거(후속 get은 None 반환·idempotent 검증용)
        for pk, val in list(self._get_map.items()):
            if val is obj:
                del self._get_map[pk]
                break


def _client(
    rows: list[Any],
    get_map: dict[uuid.UUID, Any] | None = None,
) -> tuple[TestClient, FakeSession]:
    """slice 50: get_map 지원 — `.get(LearningSession, id)` 호출 시뮬. 캡처 세션도 반환."""
    app = create_app()
    app.dependency_overrides[get_consented_user] = _user
    fake = FakeSession(rows, get_map=get_map)

    async def _sess() -> AsyncIterator[FakeSession]:
        yield fake

    app.dependency_overrides[get_session] = _sess
    return TestClient(app), fake


def _no_auth_client() -> TestClient:
    app = create_app()

    async def _sess() -> AsyncIterator[FakeSession]:
        yield FakeSession()

    app.dependency_overrides[get_session] = _sess  # 무토큰 401은 세션 전 발생(엔진 격리)
    return TestClient(app)


_ENDPOINTS = (
    "/v1/me/sessions",
    "/v1/me/assessments",
    "/v1/me/dialogues",
    "/v1/me/deletions",
    "/v1/me/privacy-audit",
)


class TestScopedLists:
    def test_sessions_returns_rows(self) -> None:
        rows = [LearningSession.from_schema(LearningSessionSchema(user_id=_UID))]
        client, _ = _client(rows)
        resp = client.get("/v1/me/sessions")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_assessments_returns_rows(self) -> None:
        rows = [Assessment.from_schema(AssessmentSchema(user_id=_UID))]
        client, _ = _client(rows)
        resp = client.get("/v1/me/assessments")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_dialogues_returns_rows(self) -> None:
        rows = [Dialogue.from_schema(DialogueSchema(user_id=_UID))]
        client, _ = _client(rows)
        resp = client.get("/v1/me/dialogues")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_deletions_returns_rows(self) -> None:
        """slice 58: 본인 삭제 감사 이력 조회 — resource_type enum 값 직렬화."""
        rows = [
            DeletionAudit.from_schema(
                DeletionAuditSchema(
                    user_id=_UID,
                    resource_type=AuditResourceType.learning_session,
                    resource_id=uuid.uuid4(),
                )
            )
        ]
        client, _ = _client(rows)
        resp = client.get("/v1/me/deletions")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["resource_type"] == "learning_session"
        assert str(body[0]["user_id"]) == str(_UID)

    def test_privacy_audit_returns_rows(self) -> None:
        """SEC-09: 본인 개인정보 감사 이력 조회 — event_kind enum 값 직렬화."""
        rows = [
            PrivacyAudit.from_schema(
                PrivacyAuditSchema(
                    user_id=_UID,
                    event_kind=AuditEventKind.export_data,
                )
            )
        ]
        client, _ = _client(rows)
        resp = client.get("/v1/me/privacy-audit")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["event_kind"] == "export_data"
        assert str(body[0]["user_id"]) == str(_UID)

    def test_privacy_audit_event_kind_filter_accepted(self) -> None:
        """SEC-09: 유효한 event_kind 값은 200(쿼리 결선) — 실 필터링은 통합테스트가 검증."""
        rows = [
            PrivacyAudit.from_schema(
                PrivacyAuditSchema(user_id=_UID, event_kind=AuditEventKind.consent_change)
            )
        ]
        client, _ = _client(rows)
        for value in ("export_data", "consent_change", "admin_access"):
            resp = client.get("/v1/me/privacy-audit", params={"event_kind": value})
            assert resp.status_code == 200, resp.text

    def test_privacy_audit_invalid_event_kind_rejected(self) -> None:
        """SEC-09: enum 밖 값은 422(임의 문자열 주입 차단)."""
        client, _ = _client([])
        resp = client.get("/v1/me/privacy-audit", params={"event_kind": "bogus"})
        assert resp.status_code == 422

    def test_privacy_audit_naive_datetime_rejected(self) -> None:
        """SEC-09: timezone 없는 datetime은 422(deletions와 동형 시간창 검증)."""
        client, _ = _client([])
        resp = client.get("/v1/me/privacy-audit", params={"since": "2024-01-01T00:00:00"})
        assert resp.status_code == 422

    def test_empty_lists(self) -> None:
        client, _ = _client([])
        for path in _ENDPOINTS:
            resp = client.get(path)
            assert resp.status_code == 200
            assert resp.json() == []

    def test_deletions_resource_type_filter_accepted(self) -> None:
        """slice 65: 유효한 resource_type 값은 200 — 쿼리 결선 검증.

        FakeSession은 stmt를 무시하므로 *실제 필터링*은 통합테스트가 검증한다. 여기선 enum
        값이 파라미터로 수용되고 엔드포인트가 정상 응답하는지(결선)만 본다.
        """
        rows = [
            DeletionAudit.from_schema(
                DeletionAuditSchema(
                    user_id=_UID,
                    resource_type=AuditResourceType.dialogue,
                    resource_id=uuid.uuid4(),
                )
            )
        ]
        client, _ = _client(rows)
        for value in ("learning_session", "dialogue", "assessment"):
            resp = client.get("/v1/me/deletions", params={"resource_type": value})
            assert resp.status_code == 200, resp.text

    def test_deletions_invalid_resource_type_rejected(self) -> None:
        """slice 65: enum 밖 값은 422 — 임의 문자열 주입 차단."""
        client, _ = _client([])
        resp = client.get("/v1/me/deletions", params={"resource_type": "bogus"})
        assert resp.status_code == 422

    def test_deletions_multiple_resource_types_accepted(self) -> None:
        """slice 68: resource_type 반복 지정(OR/IN) 200 — 다중 도메인 결선."""
        client, _ = _client([])
        resp = client.get(
            "/v1/me/deletions",
            params=[("resource_type", "dialogue"), ("resource_type", "assessment")],
        )
        assert resp.status_code == 200, resp.text

    def test_deletions_multiple_resource_types_one_invalid_rejected(self) -> None:
        """slice 68: 다중 값 중 하나라도 enum 밖이면 422(부분 주입 차단)."""
        client, _ = _client([])
        resp = client.get(
            "/v1/me/deletions",
            params=[("resource_type", "dialogue"), ("resource_type", "bogus")],
        )
        assert resp.status_code == 422

    def test_deletions_time_window_accepted(self) -> None:
        """slice 66: TZ-aware since/until은 200 — 시간창 파라미터 결선."""
        client, _ = _client([])
        resp = client.get(
            "/v1/me/deletions",
            params={
                "since": "2024-01-01T00:00:00Z",
                "until": "2024-12-31T23:59:59+00:00",
            },
        )
        assert resp.status_code == 200, resp.text

    def test_deletions_naive_datetime_rejected(self) -> None:
        """slice 66/42: timezone 없는 datetime은 422(PG TZ-aware 컬럼과 비교 모호)."""
        client, _ = _client([])
        resp = client.get("/v1/me/deletions", params={"since": "2024-01-01T00:00:00"})
        assert resp.status_code == 422

    def test_deletions_inverted_window_rejected(self) -> None:
        """slice 66/45: since > until은 빈 시간창 — 클라이언트 버그 명시 거부(422)."""
        client, _ = _client([])
        resp = client.get(
            "/v1/me/deletions",
            params={
                "since": "2024-12-31T00:00:00Z",
                "until": "2024-01-01T00:00:00Z",
            },
        )
        assert resp.status_code == 422

    def test_list_time_window_accepted_all_endpoints(self) -> None:
        """slice 67: sessions·assessments·dialogues도 TZ-aware since/until 수용(200·결선)."""
        client, _ = _client([])
        for path in ("/v1/me/sessions", "/v1/me/assessments", "/v1/me/dialogues"):
            resp = client.get(
                path,
                params={
                    "since": "2024-01-01T00:00:00Z",
                    "until": "2024-12-31T23:59:59+00:00",
                },
            )
            assert resp.status_code == 200, (path, resp.text)

    def test_list_time_window_naive_rejected_all_endpoints(self) -> None:
        """slice 67: 세 리스트도 naive datetime은 422(_query_filters 공용)."""
        client, _ = _client([])
        for path in ("/v1/me/sessions", "/v1/me/assessments", "/v1/me/dialogues"):
            resp = client.get(path, params={"since": "2024-01-01T00:00:00"})
            assert resp.status_code == 422, path

    def test_list_time_window_inverted_rejected_all_endpoints(self) -> None:
        """slice 67: 세 리스트도 since > until은 422(_query_filters 공용)."""
        client, _ = _client([])
        for path in ("/v1/me/sessions", "/v1/me/assessments", "/v1/me/dialogues"):
            resp = client.get(
                path,
                params={
                    "since": "2024-12-31T00:00:00Z",
                    "until": "2024-01-01T00:00:00Z",
                },
            )
            assert resp.status_code == 422, path

    # slice 69: lifecycle 종료 시각 시간창 — 엔드포인트별 파라미터명(ended_/completed_).
    _CLOSE_WINDOW_ENDPOINTS = (
        ("/v1/me/sessions", "ended_since", "ended_until"),
        ("/v1/me/dialogues", "ended_since", "ended_until"),
        ("/v1/me/assessments", "completed_since", "completed_until"),
    )

    def test_close_time_window_accepted_all_endpoints(self) -> None:
        """slice 69: ended_/completed_ 시간창 TZ-aware 수용(200·결선)."""
        client, _ = _client([])
        for path, lo, hi in self._CLOSE_WINDOW_ENDPOINTS:
            resp = client.get(
                path,
                params={lo: "2024-01-01T00:00:00Z", hi: "2024-12-31T23:59:59+00:00"},
            )
            assert resp.status_code == 200, (path, resp.text)

    def test_close_time_window_naive_rejected_all_endpoints(self) -> None:
        """slice 69: 종료 시각 시간창도 naive datetime은 422(공용 검증)."""
        client, _ = _client([])
        for path, lo, _hi in self._CLOSE_WINDOW_ENDPOINTS:
            resp = client.get(path, params={lo: "2024-01-01T00:00:00"})
            assert resp.status_code == 422, path

    def test_close_time_window_inverted_rejected_all_endpoints(self) -> None:
        """slice 69: 종료 시각 시간창도 since > until은 422(공용 검증)."""
        client, _ = _client([])
        for path, lo, hi in self._CLOSE_WINDOW_ENDPOINTS:
            resp = client.get(
                path,
                params={lo: "2024-12-31T00:00:00Z", hi: "2024-01-01T00:00:00Z"},
            )
            assert resp.status_code == 422, path

    def test_order_param_accepted_all_endpoints(self) -> None:
        """slice 70: order=asc/desc 모두 200(결선)·생략도 200(기본 desc)."""
        client, _ = _client([])
        for path in _ENDPOINTS:
            for order in ("asc", "desc"):
                resp = client.get(path, params={"order": order})
                assert resp.status_code == 200, (path, order, resp.text)
            assert client.get(path).status_code == 200, path  # 생략=기본 desc

    def test_order_param_invalid_rejected_all_endpoints(self) -> None:
        """slice 70: order Literal 밖 값은 422(asc/desc만 허용)."""
        client, _ = _client([])
        for path in _ENDPOINTS:
            resp = client.get(path, params={"order": "sideways"})
            assert resp.status_code == 422, path

    def test_include_total_sets_header_all_endpoints(self) -> None:
        """slice 71: include_total=true면 X-Total-Count 헤더 노출(숫자).

        FakeSession은 stmt 무시·scalar()=행 수라 *필터 적용 count*는 통합테스트가 검증.
        여기선 헤더 결선(존재·숫자성)만. 빈 시드라 len([])=0 → "0".
        """
        client, _ = _client([])
        for path in _ENDPOINTS:
            resp = client.get(path, params={"include_total": "true"})
            assert resp.status_code == 200, path
            assert resp.headers.get("X-Total-Count") == "0", path

    def test_no_total_header_by_default_all_endpoints(self) -> None:
        """slice 71: include_total 생략(기본 false)이면 X-Total-Count 헤더 없음(COUNT 비용 회피)."""
        client, _ = _client([])
        for path in _ENDPOINTS:
            resp = client.get(path)
            assert resp.status_code == 200, path
            assert "X-Total-Count" not in resp.headers, path


class TestAuthRequired:
    def test_all_require_token_401(self) -> None:
        client = _no_auth_client()
        for path in _ENDPOINTS:
            resp = client.get(path)
            assert resp.status_code == 401, path
            assert "WWW-Authenticate" in resp.headers

    def test_pagination_out_of_range_422(self) -> None:
        client, _ = _client([])
        assert client.get("/v1/me/sessions?limit=0").status_code == 422
        assert client.get("/v1/me/sessions?limit=999").status_code == 422
        assert client.get("/v1/me/sessions?offset=-1").status_code == 422


class TestEndSession:
    """slice 50: `PATCH /v1/me/sessions/{id}/end` — 본인 세션 종료(idempotent·404 미존재/타인)."""

    def _session_row(self, owner: uuid.UUID, ended: bool = False) -> LearningSession:
        sid = uuid.uuid4()
        from datetime import UTC, datetime

        schema = LearningSessionSchema(
            session_id=sid,
            user_id=owner,
            ended_at=datetime.now(UTC) if ended else None,
        )
        return LearningSession.from_schema(schema)

    def test_ends_fresh_session(self) -> None:
        """미종료 세션 → ended_at 채움·commit·200."""
        row = self._session_row(_UID, ended=False)
        client, fake = _client([], get_map={row.session_id: row})
        resp = client.patch(f"/v1/me/sessions/{row.session_id}/end")
        assert resp.status_code == 200
        assert resp.json()["ended_at"] is not None
        assert fake.commits == 1
        # ORM row의 ended_at도 채워짐
        assert row.ended_at is not None

    def test_idempotent_already_ended(self) -> None:
        """이미 종료된 세션 → 기존 ended_at 보존·commit 없음·200."""
        row = self._session_row(_UID, ended=True)
        original_ended = row.ended_at
        client, fake = _client([], get_map={row.session_id: row})
        resp = client.patch(f"/v1/me/sessions/{row.session_id}/end")
        assert resp.status_code == 200
        # 시각 변경 없음
        assert row.ended_at == original_ended
        assert fake.commits == 0  # 변경 없으면 commit 0

    def test_nonexistent_returns_404(self) -> None:
        """미존재 세션 → 404."""
        fake_id = uuid.uuid4()
        client, _ = _client([], get_map={})
        resp = client.patch(f"/v1/me/sessions/{fake_id}/end")
        assert resp.status_code == 404

    def test_other_users_session_returns_404(self) -> None:
        """타인 소유 세션 → 404(존재 여부 비누설·slice 24 패턴)."""
        other_uid = uuid.uuid4()
        row = self._session_row(other_uid, ended=False)
        client, fake = _client([], get_map={row.session_id: row})
        resp = client.patch(f"/v1/me/sessions/{row.session_id}/end")
        assert resp.status_code == 404
        # 실제 ended_at는 *수정 안 됨*
        assert row.ended_at is None

    def test_end_captures_ability_snapshot_when_attempts_exist(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """slice 34/75: 처음 종료 + 채점 이력 있으면 θ 스냅샷 자동 적재(종료 1 + 스냅샷 1 commit).

        개념별 θ 적재(slice 75)는 `TestSessionEndConceptSnapshots`·통합테스트가 검증 — 여기선
        전과목 캡처·단일 트랜잭션만 보려 `compute_concept_abilities`를 빈 리스트로 고정한다
        (FakeSession은 단일 행셋만 반환해 전과목 3-튜플과 개념 6-튜플을 동시에 못 줌).
        """

        async def _no_concepts(session: Any, user_id: Any) -> list[ConceptAbilityItem]:
            return []

        monkeypatch.setattr("whymath_backend.api.me.compute_concept_abilities", _no_concepts)
        row = self._session_row(_UID, ended=False)
        # FakeSession.execute(θ 쿼리) → (is_correct, difficulty, irt_difficulty_b) 행
        client, fake = _client(
            [(True, 3.0, None), (False, 3.0, None)], get_map={row.session_id: row}
        )
        resp = client.patch(f"/v1/me/sessions/{row.session_id}/end")
        assert resp.status_code == 200
        snaps = [a for a in fake.added if isinstance(a, AbilitySnapshot)]
        assert len(snaps) == 1
        assert snaps[0].response_count == 2
        assert snaps[0].concept_id is None  # 전과목 단일 θ
        assert fake.commits == 1  # slice 35: 종료 + 스냅샷 단일 트랜잭션

    def test_end_no_attempts_skips_snapshot(self) -> None:
        """채점 이력 0 → θ=0 노이즈 스냅샷 미적재(종료만)."""
        row = self._session_row(_UID, ended=False)
        client, fake = _client([], get_map={row.session_id: row})
        resp = client.patch(f"/v1/me/sessions/{row.session_id}/end")
        assert resp.status_code == 200
        assert not any(isinstance(a, AbilitySnapshot) for a in fake.added)
        assert fake.commits == 1  # 종료만

    def test_idempotent_end_skips_snapshot(self) -> None:
        """이미 종료된 세션 재호출 → 채점 이력 있어도 스냅샷 미적재(멱등 트리거)."""
        row = self._session_row(_UID, ended=True)
        client, fake = _client([(True, 3.0, None)], get_map={row.session_id: row})
        resp = client.patch(f"/v1/me/sessions/{row.session_id}/end")
        assert resp.status_code == 200
        assert not any(isinstance(a, AbilitySnapshot) for a in fake.added)
        assert fake.commits == 0


class TestDeleteSession:
    """slice 51: `DELETE /v1/me/sessions/{id}` — GDPR 영구 삭제·404 미존재/타인."""

    def _session_row(self, owner: uuid.UUID) -> LearningSession:
        sid = uuid.uuid4()
        schema = LearningSessionSchema(session_id=sid, user_id=owner)
        return LearningSession.from_schema(schema)

    def test_delete_own_session_returns_204(self) -> None:
        """본인 세션 삭제 → 204 No Content·session.delete + commit 호출."""
        row = self._session_row(_UID)
        client, fake = _client([], get_map={row.session_id: row})
        resp = client.delete(f"/v1/me/sessions/{row.session_id}")
        assert resp.status_code == 204
        assert resp.content == b""  # 204 응답 body 비어있음
        assert fake.deleted == [row]
        assert fake.commits == 1
        # slice 57: 삭제와 동일 트랜잭션으로 DeletionAudit 1행 적재
        assert len(fake.added) == 1
        audit = fake.added[0]
        assert audit.resource_type == "learning_session"
        assert audit.resource_id == row.session_id
        assert audit.user_id == _UID

    def test_delete_nonexistent_returns_404(self) -> None:
        fake_id = uuid.uuid4()
        client, fake = _client([], get_map={})
        resp = client.delete(f"/v1/me/sessions/{fake_id}")
        assert resp.status_code == 404
        assert fake.deleted == []
        assert fake.commits == 0
        assert fake.added == []  # slice 57: 404는 감사 미적재

    def test_delete_other_users_session_returns_404(self) -> None:
        """타인 소유 → 404 + 행 삭제 안 됨(상태 불변·정보 비누설)."""
        other_uid = uuid.uuid4()
        row = self._session_row(other_uid)
        client, fake = _client([], get_map={row.session_id: row})
        resp = client.delete(f"/v1/me/sessions/{row.session_id}")
        assert resp.status_code == 404
        assert fake.deleted == []
        assert fake.commits == 0
        assert fake.added == []  # slice 57: 타인 소유 404도 감사 미적재
        # 행 그대로 존재
        assert row.session_id in fake._get_map

    def test_delete_then_get_returns_404(self) -> None:
        """slice 51: 삭제 후 같은 ID 재호출은 404
        (idempotent 의미·DELETE *aFTER*는 두 번째 호출이 미존재)."""
        row = self._session_row(_UID)
        client, _ = _client([], get_map={row.session_id: row})
        first = client.delete(f"/v1/me/sessions/{row.session_id}")
        assert first.status_code == 204
        # 두 번째 호출은 미존재 → 404
        second = client.delete(f"/v1/me/sessions/{row.session_id}")
        assert second.status_code == 404


class TestDialogueLifecycle:
    """slice 52: Dialogue end + delete — slice 50/51 패턴 답습 invariant 3회차."""

    def _dialogue_row(
        self,
        owner: uuid.UUID,
        ended: bool = False,
        resolution: Resolution | None = None,
    ) -> Dialogue:
        did = uuid.uuid4()
        schema = DialogueSchema(
            dialogue_id=did,
            user_id=owner,
            ended_at=datetime.now(UTC) if ended else None,
            resolution=resolution,
        )
        return Dialogue.from_schema(schema)

    # ── PATCH end ──
    def test_end_fresh_dialogue(self) -> None:
        row = self._dialogue_row(_UID, ended=False)
        client, fake = _client([], get_map={row.dialogue_id: row})
        resp = client.patch(f"/v1/me/dialogues/{row.dialogue_id}/end")
        assert resp.status_code == 200
        assert resp.json()["ended_at"] is not None
        assert resp.json()["resolution"] is None  # 본문 미제공 → resolution 미설정(하위호환)
        assert fake.commits == 1

    # ── PATCH end + resolution(클라이언트 보고·⑪ self_solve_rate 원천) ──
    def test_end_with_resolution_persists(self) -> None:
        """본문 resolution 제공 → ended_at과 같은 트랜잭션에 적재·commit 1회."""
        row = self._dialogue_row(_UID, ended=False)
        client, fake = _client([], get_map={row.dialogue_id: row})
        resp = client.patch(
            f"/v1/me/dialogues/{row.dialogue_id}/end",
            json={"resolution": Resolution.학생자력해결.value},
        )
        assert resp.status_code == 200
        assert resp.json()["ended_at"] is not None
        assert resp.json()["resolution"] == Resolution.학생자력해결.value
        assert row.resolution == Resolution.학생자력해결
        assert fake.commits == 1

    def test_end_resolution_first_write_wins(self) -> None:
        """이미 resolution 있으면 보존(낙인 방지)·이미 ended면 commit 0(완전 idempotent)."""
        row = self._dialogue_row(_UID, ended=True, resolution=Resolution.학생자력해결)
        client, fake = _client([], get_map={row.dialogue_id: row})
        resp = client.patch(
            f"/v1/me/dialogues/{row.dialogue_id}/end",
            json={"resolution": Resolution.포기.value},  # 다른 값 시도 → 무시(보존)
        )
        assert resp.status_code == 200
        assert row.resolution == Resolution.학생자력해결  # 첫 기록 보존
        assert fake.commits == 0

    def test_end_resolution_on_already_ended(self) -> None:
        """이미 ended지만 resolution 미설정이면 첫 보고를 적재(종료 먼저·결말 나중)·commit 1."""
        row = self._dialogue_row(_UID, ended=True, resolution=None)
        original_ended = row.ended_at
        client, fake = _client([], get_map={row.dialogue_id: row})
        resp = client.patch(
            f"/v1/me/dialogues/{row.dialogue_id}/end",
            json={"resolution": Resolution.힌트필요.value},
        )
        assert resp.status_code == 200
        assert row.ended_at == original_ended  # ended_at 보존
        assert row.resolution == Resolution.힌트필요
        assert fake.commits == 1

    def test_end_idempotent_already_ended(self) -> None:
        row = self._dialogue_row(_UID, ended=True)
        original = row.ended_at
        client, fake = _client([], get_map={row.dialogue_id: row})
        resp = client.patch(f"/v1/me/dialogues/{row.dialogue_id}/end")
        assert resp.status_code == 200
        assert row.ended_at == original
        assert fake.commits == 0

    def test_end_nonexistent_returns_404(self) -> None:
        fake_id = uuid.uuid4()
        client, _ = _client([], get_map={})
        resp = client.patch(f"/v1/me/dialogues/{fake_id}/end")
        assert resp.status_code == 404

    def test_end_other_users_dialogue_returns_404(self) -> None:
        other_uid = uuid.uuid4()
        row = self._dialogue_row(other_uid, ended=False)
        client, fake = _client([], get_map={row.dialogue_id: row})
        resp = client.patch(f"/v1/me/dialogues/{row.dialogue_id}/end")
        assert resp.status_code == 404
        assert row.ended_at is None
        assert fake.commits == 0

    # ── DELETE ──
    def test_delete_own_dialogue_returns_204(self) -> None:
        row = self._dialogue_row(_UID)
        client, fake = _client([], get_map={row.dialogue_id: row})
        resp = client.delete(f"/v1/me/dialogues/{row.dialogue_id}")
        assert resp.status_code == 204
        assert fake.deleted == [row]
        assert fake.commits == 1
        # slice 57: dialogue 삭제 감사 적재
        assert len(fake.added) == 1
        assert fake.added[0].resource_type == "dialogue"
        assert fake.added[0].resource_id == row.dialogue_id

    def test_delete_nonexistent_returns_404(self) -> None:
        fake_id = uuid.uuid4()
        client, fake = _client([], get_map={})
        resp = client.delete(f"/v1/me/dialogues/{fake_id}")
        assert resp.status_code == 404
        assert fake.deleted == []

    def test_delete_other_users_dialogue_returns_404(self) -> None:
        other_uid = uuid.uuid4()
        row = self._dialogue_row(other_uid)
        client, fake = _client([], get_map={row.dialogue_id: row})
        resp = client.delete(f"/v1/me/dialogues/{row.dialogue_id}")
        assert resp.status_code == 404
        assert fake.deleted == []
        assert row.dialogue_id in fake._get_map


class TestAssessmentLifecycle:
    """slice 53: Assessment complete + delete — slice 50/51 패턴 답습 invariant 4회차.

    *Assessment는 completed_at*(`ended_at` 아님). 경로도 `/complete`로 명칭만 컬럼 의미 추종.
    """

    def _assessment_row(self, owner: uuid.UUID, completed: bool = False) -> Assessment:
        aid = uuid.uuid4()
        schema = AssessmentSchema(
            assessment_id=aid,
            user_id=owner,
            completed_at=datetime.now(UTC) if completed else None,
        )
        return Assessment.from_schema(schema)

    # ── PATCH complete ──
    def test_complete_fresh_assessment(self) -> None:
        row = self._assessment_row(_UID, completed=False)
        client, fake = _client([], get_map={row.assessment_id: row})
        resp = client.patch(f"/v1/me/assessments/{row.assessment_id}/complete")
        assert resp.status_code == 200
        assert resp.json()["completed_at"] is not None
        assert fake.commits == 1

    def test_complete_idempotent_already_completed(self) -> None:
        row = self._assessment_row(_UID, completed=True)
        original = row.completed_at
        client, fake = _client([], get_map={row.assessment_id: row})
        resp = client.patch(f"/v1/me/assessments/{row.assessment_id}/complete")
        assert resp.status_code == 200
        assert row.completed_at == original
        assert fake.commits == 0

    def test_complete_nonexistent_returns_404(self) -> None:
        fake_id = uuid.uuid4()
        client, _ = _client([], get_map={})
        resp = client.patch(f"/v1/me/assessments/{fake_id}/complete")
        assert resp.status_code == 404

    def test_complete_other_users_assessment_returns_404(self) -> None:
        other_uid = uuid.uuid4()
        row = self._assessment_row(other_uid, completed=False)
        client, fake = _client([], get_map={row.assessment_id: row})
        resp = client.patch(f"/v1/me/assessments/{row.assessment_id}/complete")
        assert resp.status_code == 404
        assert row.completed_at is None
        assert fake.commits == 0

    # ── DELETE ──
    def test_delete_own_assessment_returns_204(self) -> None:
        row = self._assessment_row(_UID)
        client, fake = _client([], get_map={row.assessment_id: row})
        resp = client.delete(f"/v1/me/assessments/{row.assessment_id}")
        assert resp.status_code == 204
        assert fake.deleted == [row]
        assert fake.commits == 1
        # slice 57: assessment 삭제 감사 적재
        assert len(fake.added) == 1
        assert fake.added[0].resource_type == "assessment"
        assert fake.added[0].resource_id == row.assessment_id

    def test_delete_nonexistent_returns_404(self) -> None:
        fake_id = uuid.uuid4()
        client, fake = _client([], get_map={})
        resp = client.delete(f"/v1/me/assessments/{fake_id}")
        assert resp.status_code == 404
        assert fake.deleted == []

    def test_delete_other_users_assessment_returns_404(self) -> None:
        other_uid = uuid.uuid4()
        row = self._assessment_row(other_uid)
        client, fake = _client([], get_map={row.assessment_id: row})
        resp = client.delete(f"/v1/me/assessments/{row.assessment_id}")
        assert resp.status_code == 404
        assert fake.deleted == []
        assert row.assessment_id in fake._get_map


# ── slice L2-4: POST /v1/me/attempts (풀이 채점 제출 + 숙달 자동 갱신) ──────────
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
        # S4-14: _last_incorrect_problem_id의 단일-스칼라 조회 시뮬(직전 오답 문항 id 유/무).
        return self._rows[0] if self._rows else None


class _QueueSession:
    """execute 호출마다 큐잉 결과를 순서대로 반환 — 채점 엔드포인트의 다중 쿼리(개념 조회 →
    개념별 prior) 시뮬. add/commit 캡처.

    EOS-105 이후: 큐가 **소진된 뒤의 호출은 빈 결과**를 돌려준다(IndexError로 죽지 않는다).
    `submit_attempt`가 학습 상태 머신을 경유하면서 뒤쪽에 질의가 붙었는데, 이 파일의 시나리오들은
    *채점·숙달·보정 코칭*을 재는 것이라 그 뒤 질의의 내용에 관심이 없기 때문이다. 빈 결과는
    "이력이 없는 학생"이라는 정합한 상태이며, 상태 머신이 실제로 무엇을 하는지는
    `tests/backend/api/test_me_learning_state.py`·`tests/backend/l2/test_learning_state_machine.py`가
    전담한다.

    **소진 호출 수를 세어 두는 이유**: 조용히 빈 결과를 주면 *앞쪽* 시나리오 큐가 잘못 짜여
    엉뚱하게 소진된 경우까지 통과한다. `overflow`를 노출해 필요하면 단언할 수 있게 남긴다.
    """

    def __init__(self, results: list[_AQResult], *, question_text: str | None = None) -> None:
        self._results = results
        self._i = 0
        self.added: list[Any] = []
        self.commits = 0
        self.overflow = 0
        # EOS-104: 오답 오개념 훑기가 문항 지문을 단일 스칼라로 조회한다(`session.scalar`).
        # 기본 None은 "지문 없음" → `MisconceptionScan.NOT_RUN`이라 기존 시나리오의 동작이
        # 그대로 유지된다(훑지 않음 = 이 파일의 다른 단언과 무관).
        self.question_text = question_text
        self.flushes = 0

    async def scalar(self, _stmt: Any) -> Any:
        return self.question_text

    async def get(self, _model: Any, _pk: Any) -> Any:
        """EOS-19: `get_state`가 `user_profile`을 단건 조회한다(`session.get`).

        None은 "프로필 없음"이라는 정합한 상태이며 `LearnerState.grade`·`goals`가 비는 것이
        전부다 — 이 파일의 시나리오들은 추천 *선택*을 재므로 그 둘에 관심이 없다.
        """
        return None

    async def flush(self) -> None:
        # EOS-104: 가설 영속(`_persist_active_set`)이 같은 트랜잭션 가시화로 flush를 부른다.
        # 이 대역이 없으면 오개념 훑기가 배선된 시나리오가 AttributeError로 죽는다 — 즉 이
        # 메서드의 존재 자체가 "서빙 경로가 정말 영속까지 간다"는 증거다.
        self.flushes += 1

    async def execute(self, _stmt: Any) -> _AQResult:
        if self._i >= len(self._results):
            self.overflow += 1
            return _AQResult([])
        result = self._results[self._i]
        self._i += 1
        return result

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1


# ── EOS-14: 추천 근거(`reason`) 조립이 소비하는 조회 ────────────────────────────
#: 근거 없음(`type=unmeasured`·`basis=concept_unmapped`)의 직렬화 모양 — 아래 hermetic
#: 픽스처들은 `problem_concept` 행을 두지 않으므로 대표 개념이 잡히지 않는다. 그 상태를
#: "측정했는데 0"이 아니라 **우리 쪽 데이터 공백**으로 표기하는 것이 계약이다.
_REASON_UNMAPPED: dict[str, Any] = {
    "type": "unmeasured",
    "confidence": 0.0,
    "basis": "concept_unmapped",
    "concept_id": None,
    "mastery": None,
}
#: 추천 자체가 없을 때의 근거 — 부재도 이유를 가진다(조회 0건).
_REASON_NO_CANDIDATE: dict[str, Any] = {
    "type": "no_candidate",
    "confidence": 0.0,
    "basis": "no_candidate_pool",
    "concept_id": None,
    "mastery": None,
}


def _reason_results() -> list[_AQResult]:
    """추천이 **나간** 경로에서 근거 조립이 추가로 소비하는 결과 2건.

    `get_primary_concept_id`가 PRIMARY→TESTED 순으로 두 번 묻고 둘 다 비면 거기서 끝난다
    (숙달 조회까지 가지 않는다) — 그래서 2건이다. 큐 소진 IndexError를 검증 수단으로 쓰는
    테스트들(`test_sibling_filter_unset_skips_extra_queries` 등)의 변별력을 유지하려고
    tolerant fake로 바꾸지 않고 **실제로 소비되는 만큼만** 큐에 넣는다.
    """
    return [_AQResult([]), _AQResult([])]


def _learner_state_results() -> list[_AQResult]:
    """EOS-19: 핸들러가 정책을 부르기 **전에** 조립하는 `LearnerState`가 소비하는 결과 5건.

    내역(2026-09-18 실측 — `get_state`를 계수 대역으로 호출해 셈): 개념 진단(`compute_concept_
    diagnoses`) 2건 · 전과목 θ 1건 · 활성 오개념 1건 · 스킬 숙달 1건. 프로필은 `execute`가
    아니라 `session.get`이라 이 큐를 소비하지 않는다(위 `_QueueSession.get` 대역).

    전부 빈 결과인 것은 이 파일의 시나리오가 **선택**을 재기 때문이다 — 이력 없는 학생의
    `LearnerState`는 빈 숙달·θ None이고, 그 상태에서 추천 결과는 이동 전과 같아야 한다
    (회귀 0의 관측 지점이기도 하다). 숙달이 실린 `LearnerState`가 목표 개념 판정에 어떻게
    쓰이는지는 `tests/backend/l2/test_recommendation_policy.py`가 전담한다.

    **개수가 틀리면 조용히 통과하지 않는다**: 큐가 앞에서 어긋나면 후보 풀 결과가 θ 추정
    자리로 들어가 시나리오가 깨진다(실제로 EOS-19 전환 시 45건이 그렇게 깨졌다).
    """
    return [_AQResult([]) for _ in range(5)]


def _next_problem_session(
    results: list[_AQResult], *, question_text: str | None = None
) -> _QueueSession:
    """`GET /v1/me/next-problem` 시나리오용 큐 — 앞에 LearnerState 조회 5건을 채운다.

    시나리오 쪽 큐는 이동 전과 **똑같이** 쓴다(①채점 이력 ②후보 풀 …) — 이 생성기가 앞단만
    책임지므로 각 테스트의 의미가 바뀌지 않는다.
    """
    return _QueueSession(_learner_state_results() + results, question_text=question_text)


def _next_problem_recording_session(results: list[_AQResult]) -> "_RecordingQueueSession":
    """`_next_problem_session`의 stmt 캡처판 — 캡처 인덱스도 5만큼 밀린다.

    그래서 이 생성기를 쓰는 테스트는 `statements[_NP_STMT_BASE + n]`으로 읽는다(생 인덱스를
    박아 두면 LearnerState 조회가 하나 늘 때 엉뚱한 stmt를 단언하게 된다).
    """
    return _RecordingQueueSession(_learner_state_results() + results)


#: `_next_problem_recording_session`이 캡처한 stmt에서 *시나리오 첫 쿼리*의 인덱스.
#: 앞의 5건은 LearnerState 조립분이다(`_learner_state_results` 참조).
_NP_STMT_BASE = 5


def _attempts_client(session: _QueueSession) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_consented_user] = _user

    async def _sess() -> AsyncIterator[_QueueSession]:
        yield session

    app.dependency_overrides[get_session] = _sess
    return TestClient(app)


@contextmanager
def _student_work_key_env(key_b64: str | None) -> Iterator[None]:
    """SEC-31: `WHYMATH_STUDENT_WORK_ENCRYPTION_KEY`를 env로 주입(또는 제거)하고 `get_settings`
    캐시를 리셋·원복(`test_dialogue_content_encryption_integration.py`의 `_dialogue_key_env`
    패턴 미러 — `submit_attempt`가 `get_settings()`를 직접 호출하므로 dependency_overrides로는
    주입할 수 없다)."""
    var = "WHYMATH_STUDENT_WORK_ENCRYPTION_KEY"
    prev = os.environ.get(var)
    if key_b64 is None:
        os.environ.pop(var, None)
    else:
        os.environ[var] = key_b64
    get_settings.cache_clear()
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = prev
        get_settings.cache_clear()


class TestAttemptMisconceptionScan:
    """EOS-104 — 오답 1건이 오개념 후보로 이어지는 **서빙 경로**의 집행 지점.

    여기서 재는 것은 탐지 품질이 아니라 *배선*이다: 핸들러가 실제로 과목 능력을 불러 그 결과를
    채점 증거에 싣는가. 탐지 자체는 `tests/backend/l4/misconception/test_answer_signature.py`가
    본다. 둘을 나누는 이유는, 배선이 끊겨도 탐지 테스트는 초록이기 때문이다.
    """

    @staticmethod
    def _post(*, is_correct: bool, answer: str | None, question: str | None) -> dict[str, Any]:
        session = _QueueSession([], question_text=question)
        client = _attempts_client(session)
        payload: dict[str, Any] = {"problem_id": str(uuid.uuid4()), "is_correct": is_correct}
        if answer is not None:
            payload["student_answer"] = answer
        resp = client.post("/v1/me/attempts", json=payload)
        assert resp.status_code == 201, resp.text
        body: dict[str, Any] = resp.json()
        return body

    def test_wrong_answer_pattern_reaches_evidence_as_candidate(self) -> None:
        """오답 `x²+4` → 증거의 `possible_misconceptions`에 게이트 통과 후보가 실린다."""
        body = self._post(is_correct=False, answer="x²+4", question="(x+2)²을 전개하시오.")
        evidence = body["evidence"]
        assert evidence["coverage"]["misconception_scan"] == "ran_with_candidates"
        candidates = evidence["possible_misconceptions"]
        assert [c["misconception_id"] for c in candidates] == ["distribution-over-power"]
        # P-07 산출 형태 — {misconception_id, confidence}.
        assert 0.0 < candidates[0]["confidence"] <= 1.0
        assert candidates[0]["gate_passed"] is True

    def test_wrong_answer_without_pattern_is_measured_zero_not_unmeasured(self) -> None:
        """훑었는데 없었다 — 빈 후보와 `not_run`을 구별해 응답한다."""
        body = self._post(is_correct=False, answer="x²+4x+4", question="(x+2)²을 전개하시오.")
        assert body["evidence"]["coverage"]["misconception_scan"] == "ran_no_candidate"
        assert body["evidence"]["possible_misconceptions"] == []

    def test_correct_answer_is_not_scanned(self) -> None:
        """정답 시도는 훑지 않는다 — 오개념은 *틀린 방식*의 이름이다."""
        body = self._post(is_correct=True, answer="x²+4x+4", question="(x+2)²을 전개하시오.")
        assert body["evidence"]["coverage"]["misconception_scan"] == "not_run"

    def test_missing_answer_is_not_scanned(self) -> None:
        """답안 미제출은 재료 부족 — 0건을 '오개념 없음'으로 위장하지 않는다."""
        body = self._post(is_correct=False, answer=None, question="(x+2)²을 전개하시오.")
        assert body["evidence"]["coverage"]["misconception_scan"] == "not_run"

    def test_detector_failure_does_not_break_grading(self) -> None:
        """검출기가 터져도 채점은 성사된다 — 관측 실패가 채점 실패를 만들지 않는다.

        이 시점에 attempt는 **이미 commit됐다**. 여기서 예외가 새어 나가면 기록된 제출이 500으로
        돌아가 학생이 같은 문제를 다시 푼다. 그래서 삼키되 `not_run`으로 정직하게 표기한다.

        변별력: 반드시 터지는 검출기를 *주입*해 확인한다. 정상 검출기로는 이 경로가 한 번도
        실행되지 않으므로, 주입 없는 초록은 이 가드의 증거가 아니다.
        """

        class _ExplodingDetector:
            def scan_attempt_answer(self, *, question_text: str, student_answer: str | None) -> Any:
                raise RuntimeError("의도적 주입 — 검출기 내부 실패 시뮬")

        session = _QueueSession([], question_text="(x+2)²을 전개하시오.")
        app = create_app()
        app.dependency_overrides[get_consented_user] = _user

        async def _sess() -> AsyncIterator[_QueueSession]:
            yield session

        app.dependency_overrides[get_session] = _sess
        app.dependency_overrides[get_attempt_misconception_detector] = _ExplodingDetector
        client = TestClient(app)
        resp = client.post(
            "/v1/me/attempts",
            json={
                "problem_id": str(uuid.uuid4()),
                "is_correct": False,
                "student_answer": "x²+4",
            },
        )
        # 채점은 성사된다(500이 아니다).
        assert resp.status_code == 201, resp.text
        # 그리고 실패를 "오개념 없음"으로 위장하지 않는다.
        assert resp.json()["evidence"]["coverage"]["misconception_scan"] == "not_run"

    def test_kill_switch_off_reports_not_run_not_empty(self) -> None:
        """킬 스위치를 끄면 **훑지 않았다**로 표기된다 — 끈 것과 없는 것을 섞지 않는다.

        변별력 주입: 같은 입력이 ON에서 `ran_with_candidates`, OFF에서 `not_run`이어야 한다.
        둘이 같으면 이 스위치는 아무것도 하지 않는 것이다.
        """
        on = self._post(is_correct=False, answer="x²+4", question="(x+2)²을 전개하시오.")
        assert on["evidence"]["coverage"]["misconception_scan"] == "ran_with_candidates"

        var = "WHYMATH_L4_ATTEMPT_MISCONCEPTION_SCAN_ENABLED"
        prev = os.environ.get(var)
        os.environ[var] = "false"
        get_settings.cache_clear()
        try:
            off = self._post(is_correct=False, answer="x²+4", question="(x+2)²을 전개하시오.")
        finally:
            if prev is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = prev
            get_settings.cache_clear()
        assert off["evidence"]["coverage"]["misconception_scan"] == "not_run"
        assert off["evidence"]["possible_misconceptions"] == []


class TestSubmitAttempt:
    def test_submit_with_assessed_concept(self) -> None:
        """채점 제출 → ProblemAttempt 적재 + 평가 개념 숙달 갱신 응답."""
        cid = uuid.uuid4()
        # EOS-12 증거 조립(숙달 전파 *앞*): #1=PRIMARY·#2=TESTED·#3=스킬 해소.
        # 개념 숙달: #4=개념 [cid]·#5=EOS-108 멱등 조회(미반영)·#6=개념 prior 없음.
        # 스킬 숙달(Phase 2b-2): #7=개념 [cid]·#8=스킬 해소 [](미매핑 → 스킬행 0).
        #   스킬 해소가 0건이라 스킬 축 멱등 조회는 돌지 않는다(빈 집합 조기 반환).
        session = _QueueSession(
            [
                _AQResult([cid]),
                _AQResult([]),
                _AQResult([]),
                _AQResult([cid]),
                _AQResult([]),
                _AQResult([]),
                _AQResult([cid]),
                _AQResult([]),
            ]
        )
        client = _attempts_client(session)
        resp = client.post(
            "/v1/me/attempts",
            json={"problem_id": str(uuid.uuid4()), "is_correct": True},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        uuid.UUID(body["attempt_id"])  # 발급됨
        assert body["is_correct"] is True
        assert len(body["mastery_updates"]) == 1
        upd = body["mastery_updates"][0]
        assert upd["concept_id"] == str(cid)
        assert upd["mastery"] == 0.69  # 첫 관측·정답
        assert upd["sample_size"] == 1
        assert body["skill_mastery_updates"] == []  # 스킬 해소 0(미매핑)
        # ProblemAttempt + 개념 숙달행 + EOS-57 `문제시도` 이벤트(스킬행 0).
        # 카운트만 세면 신규 축이 숫자에 묻히므로 *종류*로 고정한다.
        assert [type(o).__name__ for o in session.added] == [
            "ProblemAttempt",
            "ConceptMasteryHistory",
            "AttemptEvent",
        ]
        event = session.added[-1]
        assert event.event_type is EventType.문제시도
        # 해소 0건은 `[]`로 적재된다 — None(미기록)으로 접히지 않는다(EOS-57 핵심 계약).
        assert event.skill_ids == []
        assert event.event_data == {"is_correct": True, "source": "attempt_submit"}

    def test_submit_no_mapped_concepts(self) -> None:
        """문제↔개념 매핑 없으면 attempt만 적재·mastery/skill 갱신 빈 리스트."""
        # 오답(모델 B): 개념 PRIMARY→[]·TESTED 폴백→[]. 스킬(Phase 2b-2): PRIMARY→[]·TESTED→[].
        # EOS-12 증거 조립(숙달 전파 *앞*): #1=PRIMARY []·#2=TESTED [] —
        # 개념 0건이면 스킬 해소는 조회 없이 빈 목록이라 큐를 쓰지 않는다.
        session = _QueueSession(
            [
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
            ]
        )
        client = _attempts_client(session)
        resp = client.post(
            "/v1/me/attempts",
            json={"problem_id": str(uuid.uuid4()), "is_correct": False},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["mastery_updates"] == []
        assert resp.json()["skill_mastery_updates"] == []
        # attempt + EOS-57 `문제시도` 이벤트(숙달행 0 — 개념 매핑 없음).
        assert [type(o).__name__ for o in session.added] == ["ProblemAttempt", "AttemptEvent"]
        assert session.added[-1].skill_ids == []  # 해소 0건도 기록된다(미기록 None과 구분)

    def test_submit_overconfident_returns_coaching(self) -> None:
        """과신 제출(틀림 + 확신≥0.7) → calibration_coaching.focus==overconfident(§11.4)."""
        # 오답(모델 B): 개념 PRIMARY→[]·TESTED→[]·스킬 PRIMARY→[]·TESTED→[](매핑 없음).
        # EOS-12 증거 조립(숙달 전파 *앞*): #1=PRIMARY []·#2=TESTED [] —
        # 개념 0건이면 스킬 해소는 조회 없이 빈 목록이라 큐를 쓰지 않는다.
        session = _QueueSession(
            [
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
            ]
        )
        client = _attempts_client(session)
        resp = client.post(
            "/v1/me/attempts",
            json={
                "problem_id": str(uuid.uuid4()),
                "is_correct": False,
                "confidence_self_reported": 0.9,
            },
        )
        assert resp.status_code == 201, resp.text
        coaching = resp.json()["calibration_coaching"]
        assert coaching is not None
        assert coaching["focus"] == "calibration_overconfident"
        assert coaching["socratic_category"] == "assumption"
        # 적재 로직 불변 — attempt + EOS-57 `문제시도` 이벤트(개념 매핑 없어 숙달행 0).
        assert [type(o).__name__ for o in session.added] == ["ProblemAttempt", "AttemptEvent"]

    def test_submit_well_calibrated_no_coaching(self) -> None:
        """잘 보정됨(맞음 + 확신 높음) → calibration_coaching==null."""
        # EOS-12 증거 조립(숙달 전파 *앞*): #1=PRIMARY []·#2=TESTED [] —
        # 개념 0건이면 스킬 해소는 조회 없이 빈 목록이라 큐를 쓰지 않는다.
        # 정답: 개념 assessed→[]·스킬 assessed→[](매핑 없음·둘 다 갱신 0).
        session = _QueueSession([_AQResult([]), _AQResult([]), _AQResult([]), _AQResult([])])
        client = _attempts_client(session)
        resp = client.post(
            "/v1/me/attempts",
            json={
                "problem_id": str(uuid.uuid4()),
                "is_correct": True,
                "confidence_self_reported": 0.9,
            },
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["calibration_coaching"] is None

    def test_submit_no_confidence_no_coaching(self) -> None:
        """확신 미제출(confidence 없음) → calibration_coaching==null(보정 평가 불가)."""
        # 오답(모델 B): 개념 PRIMARY→[]·TESTED→[]·스킬 PRIMARY→[]·TESTED→[](매핑 없음).
        # EOS-12 증거 조립(숙달 전파 *앞*): #1=PRIMARY []·#2=TESTED [] —
        # 개념 0건이면 스킬 해소는 조회 없이 빈 목록이라 큐를 쓰지 않는다.
        session = _QueueSession(
            [
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
            ]
        )
        client = _attempts_client(session)
        resp = client.post(
            "/v1/me/attempts",
            json={"problem_id": str(uuid.uuid4()), "is_correct": False},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["calibration_coaching"] is None

    def test_submit_stores_student_answer_plaintext_when_key_unset(self) -> None:
        """SEC-31: 키 미설정(기존 동작) — student_answer는 평문 그대로·암호화 컬럼은 None."""
        # EOS-12 증거 조립(숙달 전파 *앞*): #1=PRIMARY []·#2=TESTED [] —
        # 개념 0건이면 스킬 해소는 조회 없이 빈 목록이라 큐를 쓰지 않는다.
        session = _QueueSession(
            [
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
            ]
        )
        client = _attempts_client(session)
        with _student_work_key_env(None):
            resp = client.post(
                "/v1/me/attempts",
                json={
                    "problem_id": str(uuid.uuid4()),
                    "is_correct": False,
                    "student_answer": "내 답은 3이야",
                },
            )
        assert resp.status_code == 201, resp.text
        attempt = session.added[0]
        assert type(attempt).__name__ == "ProblemAttempt"
        assert attempt.student_answer == "내 답은 3이야"
        assert attempt.student_answer_encrypted is None
        assert attempt.student_answer_nonce is None

    def test_submit_encrypts_student_answer_when_key_configured(self) -> None:
        """SEC-31: 키 설정 시 — student_answer는 NULL·암호화 컬럼에 ciphertext/nonce가 실리고
        그 ciphertext를 같은 키로 복호하면 원문이 그대로 나온다(dialogue_turn 선례 계약 미러)."""
        # EOS-12 증거 조립(숙달 전파 *앞*): #1=PRIMARY []·#2=TESTED [] —
        # 개념 0건이면 스킬 해소는 조회 없이 빈 목록이라 큐를 쓰지 않는다.
        session = _QueueSession(
            [
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
            ]
        )
        client = _attempts_client(session)
        key_b64 = base64.b64encode(os.urandom(32)).decode()
        with _student_work_key_env(key_b64):
            resp = client.post(
                "/v1/me/attempts",
                json={
                    "problem_id": str(uuid.uuid4()),
                    "is_correct": False,
                    "student_answer": "내 답은 5야",
                },
            )
        assert resp.status_code == 201, resp.text
        attempt = session.added[0]
        assert type(attempt).__name__ == "ProblemAttempt"
        assert attempt.student_answer is None  # 평문 컬럼 비움
        assert attempt.student_answer_encrypted is not None
        assert attempt.student_answer_nonce is not None
        cipher = SecretCipher(base64.b64decode(key_b64))
        assert (
            cipher.decrypt(attempt.student_answer_encrypted, attempt.student_answer_nonce)
            == "내 답은 5야"
        )

    def test_submit_persists_reported_started_at_verbatim(self) -> None:
        """PED-37: 클라 신고 발생 시각을 *그대로* 적재하고, 수신 시각은 ingested_at에 따로 남긴다.

        이 컬럼이 비어 있던 동안 `harness/wh1_evaluation`의 since/until 집계와
        `privacy/retention` 파기가 조용히 0행이었다 — 그래서 라우트 경유로 배선을 고정한다.
        `started_at != ingested_at` 단언이 "서버 now 폴백 부재"의 증거다(같으면 폴백 잔존).
        """
        reported = datetime(2026, 3, 2, 9, 30, tzinfo=UTC)
        # EOS-12 증거 조립(숙달 전파 *앞*): #1=PRIMARY []·#2=TESTED [] —
        # 개념 0건이면 스킬 해소는 조회 없이 빈 목록이라 큐를 쓰지 않는다.
        session = _QueueSession(
            [
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
            ]
        )
        client = _attempts_client(session)
        resp = client.post(
            "/v1/me/attempts",
            json={
                "problem_id": str(uuid.uuid4()),
                "is_correct": False,
                "duration_seconds": 240,
                "started_at": reported.isoformat(),
            },
        )
        assert resp.status_code == 201, resp.text
        attempt = session.added[0]
        assert type(attempt).__name__ == "ProblemAttempt"
        assert attempt.started_at == reported
        assert attempt.ingested_at is not None
        assert attempt.ingested_at > reported  # 신고는 과거·수신은 지금(복제가 아니다)
        # 기존 계약 불변 — ended_at은 서버 now를 유지한다(수신 시각과 같은 값).
        assert attempt.ended_at == attempt.ingested_at

    def test_submit_without_started_at_leaves_null(self) -> None:
        """PED-37: 미신고면 NULL=미측정으로 남긴다 — 서버 now로 메우지 않는다(날조 금지)."""
        # EOS-12 증거 조립(숙달 전파 *앞*): #1=PRIMARY []·#2=TESTED [] —
        # 개념 0건이면 스킬 해소는 조회 없이 빈 목록이라 큐를 쓰지 않는다.
        session = _QueueSession(
            [
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
            ]
        )
        client = _attempts_client(session)
        resp = client.post(
            "/v1/me/attempts",
            json={"problem_id": str(uuid.uuid4()), "is_correct": False},
        )
        assert resp.status_code == 201, resp.text
        attempt = session.added[0]
        assert attempt.started_at is None
        assert attempt.ingested_at is not None  # 수신 시각은 서버가 아는 사실이라 채운다

    def test_submit_rejects_naive_started_at(self) -> None:
        """P2(PR #1036 Codex): 오프셋 없는 값은 422 — asyncpg가 서버 로컬 TZ로 해석한다.

        실측 경위: 초판은 `tz-aware 권장`이라고만 적고 검증하지 않아 `2026-09-07T10:00:00`이
        `tzinfo=None`으로 수용됐다. 프로덕션 컨테이너가 UTC이므로 한국 로컬 시각이 **9시간
        어긋나** 저장되고, 그러면 PED-37이 되살리려던 시간창 귀속이 오히려 조용히 망가진다.
        """
        # EOS-12 증거 조립(숙달 전파 *앞*): #1=PRIMARY []·#2=TESTED [] —
        # 개념 0건이면 스킬 해소는 조회 없이 빈 목록이라 큐를 쓰지 않는다.
        session = _QueueSession(
            [
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
            ]
        )
        client = _attempts_client(session)
        resp = client.post(
            "/v1/me/attempts",
            json={
                "problem_id": str(uuid.uuid4()),
                "is_correct": True,
                "started_at": "2026-09-07T10:00:00",  # Z도 ±HH:MM도 없다
            },
        )
        assert resp.status_code == 422, resp.text
        assert not session.added, "거부된 요청이 행을 남기면 안 된다"

    def test_submit_rejects_future_started_at(self) -> None:
        """P1(PR #1036 Codex): 미래 시각은 422 — 보존기한 파기를 영원히 회피한다.

        `privacy/retention`은 `started_at < cutoff`인 행만 지운다. 클라가 2076년을 신고하면
        3년 보존기한이 지나도 그 조건을 **영원히** 만족하지 않아 미성년자 답안이 무기한
        잔존한다(2026-09-07 실측: 검증 없이 수용됐고 cutoff 판정이 False였다).

        이 PR *이전*에는 started_at이 항상 NULL이라 조작할 값 자체가 없었다 — 통로를 여는
        변경이 공격 표면도 함께 만들었으므로 여는 쪽에서 닫는다.
        """
        # EOS-12 증거 조립(숙달 전파 *앞*): #1=PRIMARY []·#2=TESTED [] —
        # 개념 0건이면 스킬 해소는 조회 없이 빈 목록이라 큐를 쓰지 않는다.
        session = _QueueSession(
            [
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
            ]
        )
        client = _attempts_client(session)
        far_future = datetime.now(UTC) + timedelta(days=365 * 50)
        resp = client.post(
            "/v1/me/attempts",
            json={
                "problem_id": str(uuid.uuid4()),
                "is_correct": True,
                "started_at": far_future.isoformat(),
            },
        )
        assert resp.status_code == 422, resp.text
        assert not session.added, "거부된 요청이 행을 남기면 안 된다"

    def test_submit_tolerates_small_clock_skew(self) -> None:
        """대조군 — 몇 초 앞선 기기 시계는 **통과**한다.

        이 대조가 없으면 위 두 거부가 "미래면 무조건 막는다"인지 "무한한 미래를 막는다"인지
        구별되지 않는다. 학생 태블릿은 NTP 미동기로 실제로 몇 초~몇 분 어긋나므로, 엄격히
        거부하면 정직한 제출이 튕겨 학습 기록이 통째로 유실된다 — 막아야 할 것은 시계 오차가
        아니라 보존기한 회피다.
        """
        # EOS-12 증거 조립(숙달 전파 *앞*): #1=PRIMARY []·#2=TESTED [] —
        # 개념 0건이면 스킬 해소는 조회 없이 빈 목록이라 큐를 쓰지 않는다.
        session = _QueueSession(
            [
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
                _AQResult([]),
            ]
        )
        client = _attempts_client(session)
        slightly_ahead = datetime.now(UTC) + timedelta(seconds=30)
        resp = client.post(
            "/v1/me/attempts",
            json={
                "problem_id": str(uuid.uuid4()),
                "is_correct": True,
                "started_at": slightly_ahead.isoformat(),
            },
        )
        assert resp.status_code == 201, resp.text
        assert session.added[0].started_at == slightly_ahead

    def test_submit_requires_auth(self) -> None:
        """무토큰은 401(인증 게이트)."""
        app = create_app()

        async def _sess() -> AsyncIterator[_QueueSession]:
            yield _QueueSession([_AQResult([])])

        app.dependency_overrides[get_session] = _sess
        client = TestClient(app)
        resp = client.post(
            "/v1/me/attempts",
            json={"problem_id": str(uuid.uuid4()), "is_correct": True},
        )
        assert resp.status_code == 401

    def test_submit_missing_fields_422(self) -> None:
        session = _QueueSession([_AQResult([])])
        client = _attempts_client(session)
        # is_correct 누락
        assert (
            client.post("/v1/me/attempts", json={"problem_id": str(uuid.uuid4())}).status_code
            == 422
        )
        # problem_id 누락
        assert client.post("/v1/me/attempts", json={"is_correct": True}).status_code == 422

    def test_submit_extra_field_422(self) -> None:
        """extra='forbid' — 모르는 필드 거부(예: user_id 사칭 시도)."""
        session = _QueueSession([_AQResult([])])
        client = _attempts_client(session)
        resp = client.post(
            "/v1/me/attempts",
            json={
                "problem_id": str(uuid.uuid4()),
                "is_correct": True,
                "user_id": str(uuid.uuid4()),
            },
        )
        assert resp.status_code == 422


# ── slice L2-5: GET /v1/me/mastery (학습곡선 조회 — ConceptMasteryHistory 시계열) ──
def _mastery_row(mastery: float = 0.69, sample_size: int = 1) -> ConceptMasteryHistory:
    return ConceptMasteryHistory.from_schema(
        ConceptMasteryHistorySchema(
            user_id=_UID,
            concept_id=uuid.uuid4(),
            measured_at=datetime(2026, 1, 1, tzinfo=UTC),
            mastery=mastery,
            sample_size=sample_size,
        )
    )


def _snapshot_row(
    mastery: float | None = 0.69, code: str | None = "C-1", name: str | None = "개념"
) -> tuple[ConceptMasteryHistory, str | None, str | None]:
    """slice L2-5d: /mastery/current join 쿼리의 Row 튜플 시뮬 — (CMH, code, name_ko)."""
    cmh = ConceptMasteryHistory.from_schema(
        ConceptMasteryHistorySchema(
            user_id=_UID,
            concept_id=uuid.uuid4(),
            measured_at=datetime(2026, 1, 1, tzinfo=UTC),
            mastery=mastery,
            sample_size=1,
        )
    )
    return (cmh, code, name)


class TestMasteryCurve:
    def test_returns_rows(self) -> None:
        client, _ = _client([_mastery_row()])
        resp = client.get("/v1/me/mastery")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body) == 1
        assert float(body[0]["mastery"]) == 0.69
        assert str(body[0]["user_id"]) == str(_UID)

    def test_empty(self) -> None:
        client, _ = _client([])
        resp = client.get("/v1/me/mastery")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_requires_auth(self) -> None:
        assert _no_auth_client().get("/v1/me/mastery").status_code == 401

    def test_concept_id_filter_accepted(self) -> None:
        """?concept_id=<uuid> 결선(200)·잘못된 uuid는 422."""
        client, _ = _client([_mastery_row()])
        assert (
            client.get("/v1/me/mastery", params={"concept_id": str(uuid.uuid4())}).status_code
            == 200
        )
        assert client.get("/v1/me/mastery", params={"concept_id": "not-a-uuid"}).status_code == 422

    def test_include_total_header(self) -> None:
        client, _ = _client([_mastery_row()])
        resp = client.get("/v1/me/mastery", params={"include_total": "true"})
        assert resp.headers.get("X-Total-Count") == "1"

    def test_order_accepted(self) -> None:
        client, _ = _client([_mastery_row()])
        for order in ("asc", "desc"):
            assert client.get("/v1/me/mastery", params={"order": order}).status_code == 200
        assert client.get("/v1/me/mastery", params={"order": "sideways"}).status_code == 422

    def test_time_window_validation(self) -> None:
        """measured_at 시간창도 naive 422·since>until 422(공용 검증)."""
        client, _ = _client([])
        assert (
            client.get("/v1/me/mastery", params={"since": "2024-01-01T00:00:00"}).status_code == 422
        )
        assert (
            client.get(
                "/v1/me/mastery",
                params={
                    "since": "2024-12-31T00:00:00Z",
                    "until": "2024-01-01T00:00:00Z",
                },
            ).status_code
            == 422
        )

    def test_current_returns_rows_with_concept_meta(self) -> None:
        """slice L2-5b/5d: 스냅샷 — 200·개념 메타(name/code) 조인 노출."""
        client, _ = _client([_snapshot_row(0.69, code="CAL-1", name="정적분")])
        resp = client.get("/v1/me/mastery/current")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body) == 1
        assert body[0]["concept_code"] == "CAL-1"
        assert body[0]["concept_name"] == "정적분"
        assert float(body[0]["mastery"]) == 0.69

    def test_current_orphan_concept_null_meta(self) -> None:
        """개념 삭제(orphan·LEFT JOIN) 시 name/code는 null이나 행은 보존."""
        client, _ = _client([_snapshot_row(0.5, code=None, name=None)])
        resp = client.get("/v1/me/mastery/current")
        body = resp.json()
        assert len(body) == 1
        assert body[0]["concept_name"] is None
        assert body[0]["concept_code"] is None

    def test_current_empty(self) -> None:
        client, _ = _client([])
        assert client.get("/v1/me/mastery/current").json() == []

    def test_current_requires_auth(self) -> None:
        assert _no_auth_client().get("/v1/me/mastery/current").status_code == 401

    def test_current_order_by_mastery_weakest_first(self) -> None:
        """slice L2-5c: order_by=mastery&order=asc → 약점(낮은 숙달) 우선."""
        rows = [_snapshot_row(0.9), _snapshot_row(0.3), _snapshot_row(0.6)]
        client, _ = _client(rows)
        resp = client.get("/v1/me/mastery/current", params={"order_by": "mastery", "order": "asc"})
        assert resp.status_code == 200, resp.text
        assert [float(r["mastery"]) for r in resp.json()] == [0.3, 0.6, 0.9]

    def test_current_order_by_mastery_strongest_first(self) -> None:
        rows = [_snapshot_row(0.3), _snapshot_row(0.9)]
        client, _ = _client(rows)
        resp = client.get("/v1/me/mastery/current", params={"order_by": "mastery", "order": "desc"})
        assert [float(r["mastery"]) for r in resp.json()] == [0.9, 0.3]

    def test_current_mastery_null_always_last(self) -> None:
        """mastery NULL은 정렬 방향 무관 항상 끝."""
        client, _ = _client([_snapshot_row(None), _snapshot_row(0.5)])
        resp = client.get("/v1/me/mastery/current", params={"order_by": "mastery", "order": "asc"})
        body = resp.json()
        assert body[-1]["mastery"] is None

    def test_current_invalid_order_by_422(self) -> None:
        client, _ = _client([])
        assert client.get("/v1/me/mastery/current", params={"order_by": "bogus"}).status_code == 422


class TestAbility:
    """slice L2-11: GET /v1/me/ability — 채점 풀이 이력에서 IRT θ 추정.

    FakeSession._Result.all()이 (is_correct, difficulty_overall, irt_difficulty_b) 튜플 리스트를
    반환(조인 쿼리 시뮬). 실제 JOIN/WHERE 정확성은 통합테스트가 검증. slice 79: 보정 b 컬럼 추가
    (여기선 None=휴리스틱 폴백 — 보정 b 소비는 L2 단위테스트가 검증).
    """

    def test_empty_zero_theta(self) -> None:
        """응답 0건 → θ=0·측정 불가(SE·CI null)."""
        client, _ = _client([])
        resp = client.get("/v1/me/ability")
        assert resp.status_code == 200
        assert resp.json() == {
            "theta": 0.0,
            "response_count": 0,
            "standard_error": None,
            "confidence_interval": None,
        }

    def test_requires_auth(self) -> None:
        assert _no_auth_client().get("/v1/me/ability").status_code == 401

    def test_all_correct_upper_bound(self) -> None:
        """전부 정답 → θ 상한(4.0)·응답 수 반영."""
        client, _ = _client([(True, 3.0, None), (True, 4.0, None)])
        body = client.get("/v1/me/ability").json()
        assert body["theta"] == 4.0
        assert body["response_count"] == 2

    def test_all_incorrect_lower_bound(self) -> None:
        client, _ = _client([(False, 3.0, None), (False, 2.0, None)])
        assert client.get("/v1/me/ability").json()["theta"] == -4.0

    def test_correct_on_hard_higher_theta(self) -> None:
        """어려운 문항을 맞히면(쉬운 문항 맞힘보다) 능력 추정 높음."""
        # 어려움(5.0) 정답·중간(3.0) 오답 vs 쉬움(1.0) 정답·중간 오답
        hard, _ = _client([(True, 5.0, None), (False, 3.0, None)])
        easy, _ = _client([(True, 1.0, None), (False, 3.0, None)])
        theta_hard = hard.get("/v1/me/ability").json()["theta"]
        theta_easy = easy.get("/v1/me/ability").json()["theta"]
        assert theta_hard > theta_easy

    def test_skips_null_difficulty(self) -> None:
        """difficulty_overall NULL·보정 b 없는 문항은 제외(추정에서 빠짐)."""
        client, _ = _client([(True, 3.0, None), (True, None, None)])
        body = client.get("/v1/me/ability").json()
        assert body["response_count"] == 1  # NULL 난이도 1건 제외

    def test_standard_error_and_confidence_interval(self) -> None:
        """혼합 응답(난이도3 1정답·1오답) → θ=0·SE=1/√0.5·대칭 95% CI(θ±1.96·SE)."""
        client, _ = _client([(True, 3.0, None), (False, 3.0, None)])
        body = client.get("/v1/me/ability").json()
        assert body["theta"] == 0.0
        # 두 문항 b=0·θ=0 → 정보 2·0.25=0.5 → SE=1/√0.5≈1.41421
        assert round(body["standard_error"], 5) == 1.41421
        lo, hi = body["confidence_interval"]
        assert round(lo, 5) == -2.77186  # -1.96·SE
        assert round(hi, 5) == 2.77186

    def test_more_responses_smaller_standard_error(self) -> None:
        """응답이 많을수록 SE↓(측정 정밀도↑)."""
        few, _ = _client([(True, 3.0, None), (False, 3.0, None)])
        many, _ = _client([(True, 3.0, None), (False, 3.0, None)] * 4)
        se_few = few.get("/v1/me/ability").json()["standard_error"]
        se_many = many.get("/v1/me/ability").json()["standard_error"]
        assert se_many < se_few


class TestAbilityHistory:
    """slice L2-28: GET /v1/me/ability/history — θ 성장 곡선(시간 재생).

    FakeSession._Result.all()이 (created_at, is_correct, difficulty, irt_difficulty_b) 튜플(시간
    오름차순)을 반환. 누적 재생·시점 방출만 본다(실 ORDER BY는 통합테스트). slice 81: 보정 b 컬럼
    추가(None=휴리스틱 폴백).
    """

    @staticmethod
    def _ts(day: int) -> datetime:
        return datetime(2026, 1, day, tzinfo=UTC)

    def test_empty_returns_empty(self) -> None:
        client, _ = _client([])
        resp = client.get("/v1/me/ability/history")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_requires_auth(self) -> None:
        assert _no_auth_client().get("/v1/me/ability/history").status_code == 401

    def test_cumulative_growth_curve(self) -> None:
        """1오답→θ-4, +1정답→θ0, +1정답→θ>0. response_count 1·2·3·as_of 보존."""
        client, _ = _client(
            [
                (self._ts(1), False, 3.0, None),
                (self._ts(2), True, 3.0, None),
                (self._ts(3), True, 3.0, None),
            ]
        )
        body = client.get("/v1/me/ability/history").json()
        assert [p["response_count"] for p in body] == [1, 2, 3]
        assert body[0]["theta"] == -4.0  # 전부 오답
        assert body[1]["theta"] == 0.0  # 1F1T 대칭
        assert body[2]["theta"] > 0.0  # 2T1F → 양수
        assert body[0]["as_of"].startswith("2026-01-01")

    def test_limit_returns_last_n(self) -> None:
        """?limit=1 → 끝(최근) 1개 지점만."""
        client, _ = _client(
            [
                (self._ts(1), False, 3.0, None),
                (self._ts(2), True, 3.0, None),
                (self._ts(3), True, 3.0, None),
            ]
        )
        body = client.get("/v1/me/ability/history?limit=1").json()
        assert len(body) == 1
        assert body[0]["response_count"] == 3  # 마지막 지점

    def test_standard_error_present(self) -> None:
        client, _ = _client([(self._ts(1), True, 3.0, None), (self._ts(2), False, 3.0, None)])
        body = client.get("/v1/me/ability/history").json()
        # 응답 있으니 SE 유한(측정 가능)
        assert all(p["standard_error"] is not None for p in body)

    def test_skips_attempt_without_b_source(self) -> None:
        """slice 81: 난이도·보정 b 둘 다 없는 풀이는 θ 시점 생성에서 제외."""
        client, _ = _client([(self._ts(1), True, 3.0, None), (self._ts(2), True, None, None)])
        body = client.get("/v1/me/ability/history").json()
        assert len(body) == 1  # None-b 풀이 제외 → 시점 1개


class TestAbilitySnapshots:
    """slice L2-32: POST/GET /v1/me/ability/snapshots — θ 시계열 적재·조회."""

    @staticmethod
    def _snap(theta: float, day: int) -> AbilitySnapshot:
        return AbilitySnapshot.from_schema(
            AbilitySnapshotSchema(
                user_id=_UID,
                theta=theta,
                response_count=1,
                measured_at=datetime(2026, 1, day, tzinfo=UTC),
            )
        )

    def test_capture_inserts_snapshot(self) -> None:
        """POST → 현재 θ 계산(난이도3 1정답1오답→θ0)·1행 적재·201 + 스키마 반환."""
        client, fake = _client([(True, 3.0, None), (False, 3.0, None)])
        resp = client.post("/v1/me/ability/snapshots")
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["theta"] == 0.0
        assert body["response_count"] == 2
        assert body["standard_error"] is not None
        assert body["concept_id"] is None  # 전 과목 단일 θ
        uuid.UUID(body["snapshot_id"])  # 발급됨
        assert len(fake.added) == 1  # AbilitySnapshot 1행 적재
        assert fake.commits == 1

    def test_capture_empty_history_se_null(self) -> None:
        """채점 이력 0 → θ0·response_count0·SE null도 적재."""
        client, fake = _client([])
        body = client.post("/v1/me/ability/snapshots").json()
        assert body["theta"] == 0.0
        assert body["response_count"] == 0
        assert body["standard_error"] is None
        assert len(fake.added) == 1

    def test_capture_requires_auth(self) -> None:
        assert _no_auth_client().post("/v1/me/ability/snapshots").status_code == 401

    def test_list_returns_chronological(self) -> None:
        client, _ = _client([self._snap(0.2, 1), self._snap(1.1, 2)])
        body = client.get("/v1/me/ability/snapshots").json()
        assert [s["theta"] for s in body] == [0.2, 1.1]
        assert body[0]["measured_at"].startswith("2026-01-01")

    def test_list_limit_tail(self) -> None:
        client, _ = _client([self._snap(0.2, 1), self._snap(1.1, 2)])
        body = client.get("/v1/me/ability/snapshots?limit=1").json()
        assert len(body) == 1
        assert body[0]["theta"] == 1.1  # 끝(최근) 1개

    def test_list_requires_auth(self) -> None:
        assert _no_auth_client().get("/v1/me/ability/snapshots").status_code == 401

    def test_capture_include_concepts_writes_per_concept(self) -> None:
        """slice 33: ?include_concepts=true → 전과목 1행 + 개념별 N행 적재(같은 시각)."""
        c1, c2 = uuid.uuid4(), uuid.uuid4()
        # execute#1=전과목 attempt 행·#2=개념별 행(둘 다 끝에 irt_b 컬럼 추가)
        session = _QueueSession(
            [
                _AQResult([(True, 3.0, None), (False, 3.0, None)]),
                _AQResult(
                    [
                        (c1, "C1", "개념1", True, 3.0, None),
                        (c2, "C2", "개념2", False, 3.0, None),
                    ]
                ),
            ]
        )
        client = _attempts_client(session)
        resp = client.post("/v1/me/ability/snapshots?include_concepts=true")
        assert resp.status_code == 201, resp.text
        assert resp.json()["concept_id"] is None  # 응답은 전과목 스냅샷
        assert len(session.added) == 3  # 전과목 1 + 개념 2
        assert session.commits == 1
        # 적재된 행 중 개념별 2행은 concept_id 보유
        concept_ids = {s.concept_id for s in session.added if s.concept_id is not None}
        assert concept_ids == {c1, c2}

    def test_list_concept_id_filter_serializes(self) -> None:
        """slice 33: ?concept_id 지정 → 그 개념 스냅샷(concept_id 직렬화)."""
        cid = uuid.uuid4()
        snap = AbilitySnapshot.from_schema(
            AbilitySnapshotSchema(
                user_id=_UID,
                concept_id=cid,
                theta=0.5,
                response_count=1,
                measured_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        client, _ = _client([snap])
        body = client.get(f"/v1/me/ability/snapshots?concept_id={cid}").json()
        assert len(body) == 1
        assert body[0]["concept_id"] == str(cid)


class TestAbilityByConcept:
    """slice L2-18: GET /v1/me/ability/by-concept — 개념별 θ 분리 추정.

    FakeSession._Result.all()이 (concept_id, code, name, is_correct, difficulty, irt_difficulty_b)
    6튜플을 반환(조인 시뮬). 그룹화·정렬·θ/SE 산출만 본다(실 JOIN/WHERE는 통합테스트). slice 79:
    보정 b 컬럼 추가(None=휴리스틱 폴백).
    """

    def test_empty_returns_empty_list(self) -> None:
        client, _ = _client([])
        resp = client.get("/v1/me/ability/by-concept")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_requires_auth(self) -> None:
        assert _no_auth_client().get("/v1/me/ability/by-concept").status_code == 401

    def test_single_concept_theta_and_meta(self) -> None:
        """한 개념 1정답·1오답(난이도3) → θ=0·count 2·SE=1/√0.5·개념 메타 노출."""
        cid = uuid.uuid4()
        client, _ = _client(
            [
                (cid, "TRIG-1", "삼각함수", True, 3.0, None),
                (cid, "TRIG-1", "삼각함수", False, 3.0, None),
            ]
        )
        body = client.get("/v1/me/ability/by-concept").json()
        assert len(body) == 1
        item = body[0]
        assert item["concept_id"] == str(cid)
        assert item["concept_code"] == "TRIG-1"
        assert item["concept_name"] == "삼각함수"
        assert item["theta"] == 0.0
        assert item["response_count"] == 2
        assert round(item["standard_error"], 5) == 1.41421

    def test_multiple_concepts_sorted_weakest_first(self) -> None:
        """능력 낮은(약점) 개념 먼저 — 전부오답(θ=-4) < 전부정답(θ=4)."""
        c_weak, c_strong = uuid.uuid4(), uuid.uuid4()
        client, _ = _client(
            [
                (c_strong, "S", "강점개념", True, 3.0, None),
                (c_weak, "W", "약점개념", False, 3.0, None),
            ]
        )
        body = client.get("/v1/me/ability/by-concept").json()
        assert [i["concept_id"] for i in body] == [str(c_weak), str(c_strong)]
        assert body[0]["theta"] == -4.0
        assert body[1]["theta"] == 4.0

    def test_orphan_concept_null_meta(self) -> None:
        """concept 행 없는(orphan) 개념은 code·name null(LEFT JOIN)."""
        cid = uuid.uuid4()
        client, _ = _client([(cid, None, None, True, 3.0, None)])
        item = client.get("/v1/me/ability/by-concept").json()[0]
        assert item["concept_code"] is None
        assert item["concept_name"] is None
        assert item["theta"] == 4.0  # 단일 정답 → 상한


class TestNextProblem:
    """slice L2-12: GET /v1/me/next-problem — IRT 정보량 최대 미응답 문항 추천.

    _QueueSession이 execute 2회(①채점 이력 ②후보 풀)를 큐로 반환. 실 JOIN/NOT IN/거리정렬은
    통합테스트가 검증(FakeSession은 stmt 무시).
    """

    def test_no_candidates_null(self) -> None:
        """이력 없음(θ=0)·후보 없음 → 추천 null."""
        session = _next_problem_session([_AQResult([]), _AQResult([])])
        client = _attempts_client(session)
        body = client.get("/v1/me/next-problem").json()
        assert body == {
            "problem_id": None,
            "theta": 0.0,
            "difficulty": None,
            "standard_error": None,
            "measurement_sufficient": False,
            # REC-01: 후보 풀 0건 → '미도달' 사유 코드(응답 정직 표기 신규 4필드).
            "weight_axes_applied": [],
            "candidate_pool_size": 0,
            "weak_concept_signal_count": 0,
            "candidate_zero_reason": "no_candidate_pool",
            "band_calibrated": None,  # REC-04: purpose 기본(diagnosis)은 밴드 미적용
            # EOS-14: 추천이 없어도 **이유는 있다** — 근거 필드가 비는 경로를 만들지 않는다.
            "reason": _REASON_NO_CANDIDATE,
            # EOS-19: 부재도 행위 공간의 한 값이다(none) — 목표 개념은 댈 대상이 없어 null.
            "action": "none",
            "target_concept": None,
        }

    def test_requires_auth(self) -> None:
        app = create_app()

        async def _sess() -> AsyncIterator[_QueueSession]:
            yield _next_problem_session([_AQResult([]), _AQResult([])])

        app.dependency_overrides[get_session] = _sess
        assert TestClient(app).get("/v1/me/next-problem").status_code == 401

    def test_recommends_nearest_difficulty(self) -> None:
        """이력 없음(θ=0) → 난이도 2·3·5 후보 중 b=0(난이도 3)이 정보량 최대로 추천."""
        pid_easy, pid_mid, pid_hard = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        session = _next_problem_session(
            [
                _AQResult([]),
                _AQResult([(pid_easy, 2.0, None), (pid_mid, 3.0, None), (pid_hard, 5.0, None)]),
            ]
            + _reason_results()
        )
        client = _attempts_client(session)
        body = client.get("/v1/me/next-problem").json()
        assert body["problem_id"] == str(pid_mid)
        assert body["difficulty"] == 3.0
        assert body["theta"] == 0.0

    def test_uses_calibrated_b_over_heuristic(self) -> None:
        """slice 81: 후보 선택이 보정 b(irt_difficulty_b) 우선 — θ=0에서 보정 b=0 문항 선택.

        A: 난이도 5(휴리스틱 b=2)이나 보정 b=0 · B: 난이도 3(휴리스틱 b=0)이나 보정 b=2.
        휴리스틱이면 B(난이도3→b0)가 θ=0 정보량 최대지만, 보정 b를 쓰면 A(b=0)가 선택된다.
        """
        pid_a, pid_b = uuid.uuid4(), uuid.uuid4()
        session = _next_problem_session(
            [
                _AQResult([]),  # 이력 없음 → θ=0
                _AQResult([(pid_a, 5.0, 0.0), (pid_b, 3.0, 2.0)]),
            ]
            + _reason_results()
        )
        client = _attempts_client(session)
        body = client.get("/v1/me/next-problem").json()
        assert body["theta"] == 0.0
        assert body["problem_id"] == str(pid_a)  # 보정 b=0 → θ 근접(휴리스틱이면 pid_b)

    def test_skips_attempt_without_b_source(self) -> None:
        """slice 81: 난이도·보정 b 둘 다 없는 풀이는 θ 추정에서 제외(θ=0)."""
        cand = uuid.uuid4()
        session = _next_problem_session(
            [
                _AQResult([(uuid.uuid4(), True, None, None)]),  # b 소스 없음 → 제외
                _AQResult([(cand, 3.0, None)]),
            ]
            + _reason_results()
        )
        client = _attempts_client(session)
        body = client.get("/v1/me/next-problem").json()
        assert body["theta"] == 0.0  # 유효 응답 0 → θ=0
        assert body["problem_id"] == str(cand)

    def test_high_theta_picks_harder(self) -> None:
        """전부 정답 → θ 상한(4.0). 난이도 3·5 후보 중 b=2(난이도 5)가 정보량 최대."""
        pid_mid, pid_hard = uuid.uuid4(), uuid.uuid4()
        attempts = [(uuid.uuid4(), True, 5.0, None), (uuid.uuid4(), True, 4.0, None)]
        session = _next_problem_session(
            [
                _AQResult(attempts),
                _AQResult([(pid_mid, 3.0, None), (pid_hard, 5.0, None)]),
            ]
            + _reason_results()
        )
        client = _attempts_client(session)
        body = client.get("/v1/me/next-problem").json()
        assert body["theta"] == 4.0
        assert body["problem_id"] == str(pid_hard)
        assert body["difficulty"] == 5.0
        # 응답 2건뿐 → SE 큼(>0.3)·측정 불충분
        assert body["standard_error"] is not None
        assert body["measurement_sufficient"] is False

    def test_measurement_sufficient_when_many_responses(self) -> None:
        """난이도3(b=0) 46건 절반 정답 → θ=0·SE=2/√46≈0.295 ≤ 0.3 → 중단 권고."""
        attempts = [(uuid.uuid4(), i % 2 == 0, 3.0, None) for i in range(46)]
        cand = uuid.uuid4()
        session = _next_problem_session(
            [_AQResult(attempts), _AQResult([(cand, 3.0, None)])] + _reason_results()
        )
        client = _attempts_client(session)
        body = client.get("/v1/me/next-problem").json()
        assert body["theta"] == 0.0
        assert round(body["standard_error"], 3) == 0.295
        assert body["measurement_sufficient"] is True
        # 중단 권고와 무관히 후보가 있으면 추천은 제공
        assert body["problem_id"] == str(cand)

    def test_no_responses_se_null_not_sufficient(self) -> None:
        """응답 없음 → SE null·measurement_sufficient=False(측정 불가)."""
        cand = uuid.uuid4()
        session = _next_problem_session(
            [_AQResult([]), _AQResult([(cand, 3.0, None)])] + _reason_results()
        )
        client = _attempts_client(session)
        body = client.get("/v1/me/next-problem").json()
        assert body["standard_error"] is None
        assert body["measurement_sufficient"] is False
        assert body["problem_id"] == str(cand)

    def test_weak_concept_priority_reorders(self) -> None:
        """slice 17: 동일 정보량 두 후보 중 약점 개념(저숙달) 문항이 가중으로 선택.

        쿼리 4회: ①채점 이력 ②후보 ③숙달 스냅샷 ④후보 개념 매핑.
        """
        c_strong, c_weak = uuid.uuid4(), uuid.uuid4()
        pid_a, pid_b = uuid.uuid4(), uuid.uuid4()
        session = _next_problem_session(
            [
                _AQResult([]),  # 채점 이력 없음 → θ=0
                _AQResult([(pid_a, 3.0, None), (pid_b, 3.0, None)]),  # 동일 난이도(b=0)
                _AQResult([(c_strong, 1.0), (c_weak, 0.0)]),  # 숙달: 강·약
                _AQResult([(pid_a, c_strong), (pid_b, c_weak)]),  # 개념 매핑
            ]
            + _reason_results()
        )
        client = _attempts_client(session)
        body = client.get("/v1/me/next-problem?prioritize_weak_concepts=true").json()
        # 균등이면 동률→pid_a(낮은 인덱스)이나, 약점 가중으로 pid_b(저숙달) 선택
        assert body["problem_id"] == str(pid_b)
        assert body["theta"] == 0.0

    def test_default_ignores_weak_concepts(self) -> None:
        """기본(flag 미지정) → 가중 쿼리 없이 동률은 낮은 인덱스(slice 12 동작 보존)."""
        pid_a, pid_b = uuid.uuid4(), uuid.uuid4()
        session = _next_problem_session(
            [_AQResult([]), _AQResult([(pid_a, 3.0, None), (pid_b, 3.0, None)])] + _reason_results()
        )
        client = _attempts_client(session)
        body = client.get("/v1/me/next-problem").json()
        assert body["problem_id"] == str(pid_a)

    def test_weak_priority_no_candidates_skips_weight_queries(self) -> None:
        """후보 없으면 flag=true라도 가중 쿼리 생략(2쿼리만)·problem_id null."""
        # _QueueSession에 2건만 제공 — 가중 쿼리를 돌리면 IndexError(가드 검증)
        session = _next_problem_session([_AQResult([]), _AQResult([])])
        client = _attempts_client(session)
        body = client.get("/v1/me/next-problem?prioritize_weak_concepts=true").json()
        assert body["problem_id"] is None

    def test_no_candidates_does_not_record_treatment(self) -> None:
        """REC-03 — 가짜 처치 금지: problem_id=null이면 evidence_event를 기록하지 않는다."""
        session = _next_problem_session([_AQResult([]), _AQResult([])])
        client = _attempts_client(session)
        client.get("/v1/me/next-problem")
        assert session.added == []
        assert session.commits == 0

    def test_recommendation_records_treatment_evidence(self) -> None:
        """REC-03 — 추천이 실제로 반환되면 evidence_event 처치 1건이 기록·commit된다."""
        pid = uuid.uuid4()
        session = _next_problem_session(
            [_AQResult([]), _AQResult([(pid, 3.0, None)])] + _reason_results()
        )
        client = _attempts_client(session)
        body = client.get("/v1/me/next-problem").json()
        assert body["problem_id"] == str(pid)
        assert len(session.added) == 1
        row = session.added[0]
        assert isinstance(row, EvidenceEvent)
        assert row.event_type == EVENT_TYPE_RECOMMENDATION_TREATMENT
        assert row.meta[META_KEY_PROBLEM_ID] == str(pid)
        assert row.meta[META_KEY_POOL_SIZE] == 1
        assert row.meta[META_KEY_APPLIED_WEIGHTS] is False
        assert META_KEY_MODE not in row.meta  # 기본 CAT은 mode 미기록
        assert session.commits == 1

    def test_recommendation_records_candidates_and_policy_version(self) -> None:
        """REC-11 — 기본 CAT 처치 기록에 candidates[]·policy_version=cat_v1이 함께 실린다."""
        pid_a, pid_b = uuid.uuid4(), uuid.uuid4()
        session = _next_problem_session(
            [_AQResult([]), _AQResult([(pid_a, 3.0, None), (pid_b, 3.0, 1.0)])] + _reason_results()
        )
        client = _attempts_client(session)
        client.get("/v1/me/next-problem")
        assert len(session.added) == 1
        row = session.added[0]
        assert row.meta[META_KEY_POLICY_VERSION] == POLICY_VERSION_CAT
        candidates = row.meta[META_KEY_CANDIDATES]
        assert {c["problem_id"] for c in candidates} == {str(pid_a), str(pid_b)}
        # 점수 내림차순 — b=0(θ와 일치)이 정보량 최대이므로 pid_a(difficulty_to_logit(3.0)≈0)가
        # pid_b(irt_b=1.0, θ=0에서 멀어 정보량 낮음)보다 위.
        assert candidates[0]["problem_id"] == str(pid_a)

    def test_recommendation_records_applied_weights_true_when_weak_concept_used(
        self,
    ) -> None:
        c_strong, c_weak = uuid.uuid4(), uuid.uuid4()
        pid_a, pid_b = uuid.uuid4(), uuid.uuid4()
        session = _next_problem_session(
            [
                _AQResult([]),
                _AQResult([(pid_a, 3.0, None), (pid_b, 3.0, None)]),
                _AQResult([(c_strong, 1.0), (c_weak, 0.0)]),
                _AQResult([(pid_a, c_strong), (pid_b, c_weak)]),
            ]
            + _reason_results()
        )
        client = _attempts_client(session)
        client.get("/v1/me/next-problem?prioritize_weak_concepts=true")
        assert len(session.added) == 1
        assert session.added[0].meta[META_KEY_APPLIED_WEIGHTS] is True

    def test_purpose_learning_selects_in_band_candidate_and_sets_band_calibrated_false(
        self,
    ) -> None:
        """REC-04 — purpose=learning은 밴드(70~85%) 안 후보를 고르고 band_calibrated=false."""
        pid_mid, pid_band = uuid.uuid4(), uuid.uuid4()
        band_b = -math.log(0.8 / 0.2)  # θ=0에서 P=0.8(밴드 안)
        session = _next_problem_session(
            [
                _AQResult([]),  # 이력 없음 → θ=0
                _AQResult([(pid_mid, 3.0, 0.0), (pid_band, 3.0, band_b)]),
            ]
            + _reason_results()
        )
        client = _attempts_client(session)
        body = client.get("/v1/me/next-problem?purpose=learning").json()
        assert body["problem_id"] == str(pid_band)  # 정보량 최대(pid_mid)가 아니라 밴드 안
        assert body["band_calibrated"] is False

    def test_purpose_diagnosis_explicit_matches_default_info_max_selection(self) -> None:
        """대조군 — 명시적 diagnosis는 기본과 동일하게 정보량 최대(P≈0.5) 후보를 고른다."""
        pid_mid, pid_band = uuid.uuid4(), uuid.uuid4()
        band_b = -math.log(0.8 / 0.2)
        session = _next_problem_session(
            [
                _AQResult([]),
                _AQResult([(pid_mid, 3.0, 0.0), (pid_band, 3.0, band_b)]),
            ]
            + _reason_results()
        )
        client = _attempts_client(session)
        body = client.get("/v1/me/next-problem?purpose=diagnosis").json()
        assert body["problem_id"] == str(pid_mid)
        assert body["band_calibrated"] is None

    def test_purpose_invalid_value_returns_422(self) -> None:
        """값 공간이 Literal로 닫혀 있어 오타는 422(mode 선례와 동형)."""
        session = _next_problem_session([_AQResult([]), _AQResult([])])
        client = _attempts_client(session)
        resp = client.get("/v1/me/next-problem?purpose=bogus")
        assert resp.status_code == 422

    def test_purpose_learning_combines_with_weak_concept_weight(self) -> None:
        """REC-04②·slice17 — 밴드 가중과 약점 가중이 같은 곱 결합 축에서 함께 적용된다."""
        c_strong, c_weak = uuid.uuid4(), uuid.uuid4()
        pid_mid_strong, pid_band_weak = uuid.uuid4(), uuid.uuid4()
        band_b = -math.log(0.8 / 0.2)
        session = _next_problem_session(
            [
                _AQResult([]),
                _AQResult([(pid_mid_strong, 3.0, 0.0), (pid_band_weak, 3.0, band_b)]),
                _AQResult([(c_strong, 1.0), (c_weak, 0.0)]),
                _AQResult([(pid_mid_strong, c_strong), (pid_band_weak, c_weak)]),
            ]
            + _reason_results()
        )
        client = _attempts_client(session)
        body = client.get(
            "/v1/me/next-problem?purpose=learning&prioritize_weak_concepts=true"
        ).json()
        # 밴드 안(P=0.8) + 약점(저숙달) 둘 다 만족하는 pid_band_weak가 이중 가중으로 선택.
        assert body["problem_id"] == str(pid_band_weak)

    # ── S4-14: ?sibling_filter — problem_relation(변형·유사) 첫 소비처 ──────────
    def test_sibling_filter_unset_skips_extra_queries(self) -> None:
        """미지정(기본) → 형제 조회 자체를 생략 — 쿼리 2회만(회귀 0 — 큐 소진 시 IndexError)."""
        pid = uuid.uuid4()
        session = _next_problem_session(
            [_AQResult([]), _AQResult([(pid, 3.0, None)])] + _reason_results()
        )
        client = _attempts_client(session)
        body = client.get("/v1/me/next-problem").json()
        assert body["problem_id"] == str(pid)

    def test_sibling_filter_set_but_no_prior_incorrect_skips_sibling_query(self) -> None:
        """직전 오답이 없으면(2번째 쿼리가 None) 형제 조회 자체를 생략 — 쿼리 3회만."""
        pid = uuid.uuid4()
        session = _next_problem_session(
            [
                _AQResult([]),  # ① 채점 이력 없음
                _AQResult([]),  # ② _last_incorrect_problem_id → None(오답 이력 없음)
                _AQResult([(pid, 3.0, None)]),  # ③ 후보(형제 조회 생략 — 4번째 큐 없음)
            ]
            + _reason_results()
        )
        client = _attempts_client(session)
        body = client.get("/v1/me/next-problem?sibling_filter=exclude").json()
        assert body["problem_id"] == str(pid)

    def test_sibling_include_boosts_sibling_candidate(self) -> None:
        """include — 직전 오답 문항의 형제 후보가 동일 정보량 경쟁자보다 가중으로 우선.

        쿼리 4회: ①채점 이력 ②직전 오답 문항 id ③형제 id(양방향) ④후보 풀. pid_sibling·
        pid_other는 난이도(=정보량) 동일이라 가중 없이는 인덱스(순서) 의존 동률 — 형제 가중
        (1+BOOST=2.0배)이 그 동률을 결정론으로 깬다(순서 무관 — score가 2배 차이).
        """
        pid_wrong = uuid.uuid4()
        pid_sibling, pid_other = uuid.uuid4(), uuid.uuid4()
        session = _next_problem_session(
            [
                _AQResult([(pid_wrong, False, 3.0, None)]),  # ① 오답 이력(θ 추정 겸용)
                _AQResult([pid_wrong]),  # ② 직전 오답 문항 id
                _AQResult([(pid_wrong, pid_sibling)]),  # ③ 형제(parent=오답, related=형제)
                _AQResult(  # ④ 후보(동일 난이도)
                    [(pid_other, 3.0, None), (pid_sibling, 3.0, None)]
                ),
            ]
            + _reason_results()
        )
        client = _attempts_client(session)
        body = client.get("/v1/me/next-problem?sibling_filter=include").json()
        assert body["problem_id"] == str(pid_sibling)

    def test_sibling_include_combines_with_weak_concept_weight(self) -> None:
        """include + prioritize_weak_concepts 동시 지정 — 가중이 곱으로 합성(둘 다 강한 후보 승).

        쿼리 6회: ①채점이력 ②직전오답 ③형제 ④후보 ⑤숙달스냅샷 ⑥후보개념매핑.
        """
        pid_wrong = uuid.uuid4()
        pid_sibling_weak, pid_plain = uuid.uuid4(), uuid.uuid4()
        c_weak = uuid.uuid4()
        session = _next_problem_session(
            [
                _AQResult([(pid_wrong, False, 3.0, None)]),
                _AQResult([pid_wrong]),
                _AQResult([(pid_wrong, pid_sibling_weak)]),
                _AQResult([(pid_plain, 3.0, None), (pid_sibling_weak, 3.0, None)]),
                _AQResult([(c_weak, 0.0)]),  # 숙달 스냅샷 — 저숙달
                _AQResult([(pid_sibling_weak, c_weak)]),  # 후보 개념 매핑(pid_plain은 매핑 없음)
            ]
            + _reason_results()
        )
        client = _attempts_client(session)
        body = client.get(
            "/v1/me/next-problem?sibling_filter=include&prioritize_weak_concepts=true"
        ).json()
        assert body["problem_id"] == str(pid_sibling_weak)

    def test_sibling_exclude_smoke_no_crash(self) -> None:
        """exclude — FakeSession은 SQL notin_을 적용하지 않으므로(stmt 무시) 실 배제는
        통합테스트가 검증. 여기선 쿼리 배선(4회)과 무크래시만 스모크."""
        pid_wrong = uuid.uuid4()
        pid_sibling = uuid.uuid4()
        session = _next_problem_session(
            [
                _AQResult([(pid_wrong, False, 3.0, None)]),
                _AQResult([pid_wrong]),
                _AQResult([(pid_wrong, pid_sibling)]),
                _AQResult([(pid_sibling, 3.0, None)]),
            ]
            + _reason_results()
        )
        client = _attempts_client(session)
        resp = client.get("/v1/me/next-problem?sibling_filter=exclude")
        assert resp.status_code == 200


# ── REC-06: 후보 조회 결정론(정렬 2차 키) + 제외 축 변별력 ──────────────────────────────
class _RecordingQueueSession(_QueueSession):
    """`_QueueSession`에 **실행된 stmt 캡처**를 더한 것 — SQL 자체를 단언하기 위함.

    기존 FakeSession은 stmt를 통째로 무시해서 "WHERE/ORDER BY가 실제로 붙었는가"를 볼 수 없었다.
    반환값은 그대로 큐에서 주되(동작 무변경), 컴파일된 SQL 문자열을 남겨 정렬 키·NOT IN 유무를
    검사할 수 있게 한다. 실 PG 왕복 검증은 `test_me_integration.py`가 별도로 맡는다.
    """

    def __init__(self, results: list[_AQResult]) -> None:
        super().__init__(results)
        self.statements: list[Any] = []

    async def execute(self, _stmt: Any) -> _AQResult:
        self.statements.append(_stmt)
        return await super().execute(_stmt)


def _order_by_tail(stmt: Any) -> str:
    """컴파일된 SQL에서 ORDER BY 이후 조각(정렬 키 순서 검사용)."""
    sql = str(stmt)
    assert "ORDER BY" in sql, sql
    return sql.split("ORDER BY", 1)[1]


class TestCandidatePoolOrdering:
    """REC-06 acceptance③ — 후보 조회 `ORDER BY`에 2차 키(problem_id)가 붙어 동률 구간이 동결."""

    def test_helper_orders_by_distance_then_problem_id(self) -> None:
        """정렬 키는 정확히 2개이고 순서는 ① |b−θ| ② problem_id다."""
        keys = candidate_pool_order_by(0.0)
        assert len(keys) == 2
        stmt = select(Problem.problem_id).order_by(*keys)
        tail = _order_by_tail(stmt)
        assert "abs(" in tail
        assert "problem.problem_id" in tail
        assert tail.index("abs(") < tail.index("problem.problem_id")

    def test_default_cat_query_carries_secondary_key(self) -> None:
        """핸들러가 실제로 실행하는 후보 stmt에 2차 키가 실린다(헬퍼만 고쳐 놓고 미사용 방지)."""
        pid = uuid.uuid4()
        session = _next_problem_recording_session(
            [_AQResult([]), _AQResult([(pid, 3.0, None)])] + _reason_results()
        )
        client = _attempts_client(session)
        assert client.get("/v1/me/next-problem").status_code == 200
        tail = _order_by_tail(session.statements[_NP_STMT_BASE + 1])
        assert tail.index("abs(") < tail.index("problem.problem_id")

    def test_suneung_query_carries_same_secondary_key(self) -> None:
        """수능 분기의 후보 조회도 같은 동률 결함을 갖고 있었다 — 같은 동결을 적용한다."""
        session = _next_problem_recording_session([_AQResult([]), _AQResult([])])
        client = _attempts_client(session)
        assert client.get("/v1/me/next-problem?mode=suneung").status_code == 200
        tail = _order_by_tail(session.statements[_NP_STMT_BASE + 1])
        assert tail.index("abs(") < tail.index("problem.problem_id")

    def test_exposure_gate_conditions_are_single_sourced(self) -> None:
        """후보 WHERE 3축(난이도·저작권 출처·검수)이 헬퍼 한 곳에서만 정의된다."""
        sql = str(select(Problem.problem_id).where(*candidate_pool_conditions()))
        assert "problem.difficulty_overall IS NOT NULL" in sql
        assert "problem.source_type NOT IN" in sql
        assert "problem.review_status =" in sql

    def test_secondary_key_does_not_change_pick_when_max_is_unique(self) -> None:
        """**회귀 0 증명** — 2차 키가 바꾸는 것은 *동률 구간의 순서*뿐이다.

        정렬 키 추가로 달라질 수 있는 것은 후보 리스트의 순서이므로, "순서가 달라져도 선택이
        같다"를 보이면 회귀가 없다는 뜻이 된다. 정보량 최댓값이 유일한 풀을 여러 순열로 넣어
        `select_weighted_item`이 매번 같은 문항을 고르는지 확인한다(동률이 있는 경우에만
        순서가 결과를 가르며, 그때의 기존 동작은 'PG 임의'라 정의된 동작이 아니었다).
        """
        pool = [(uuid.uuid4(), d, None) for d in (5.0, 3.0, 1.0, 4.0)]
        picks = set()
        for rotation in range(len(pool)):
            rotated = pool[rotation:] + pool[:rotation]
            session = _next_problem_session([_AQResult([]), _AQResult(rotated)] + _reason_results())
            body = _attempts_client(session).get("/v1/me/next-problem").json()
            picks.add(body["problem_id"])
        assert len(picks) == 1  # 순서를 어떻게 흔들어도 같은 문항(θ=0 → 난이도 3.0)
        assert picks == {str(next(pid for pid, d, _b in pool if d == 3.0))}

    def test_attempt_exclusion_toggles_returned_problem_bidirectionally(self) -> None:
        """REC-06 acceptance④ — attempt 1건 주입 → 그 문항이 후보에서 빠지고, 되돌리면 원복.

        두 축을 함께 본다: ⑴ `attempted_ids`가 실제로 **SQL의 NOT IN까지 도달**하는가(핸들러가
        제외를 거는가) ⑵ 그 결과 반환 문항이 실제로 바뀌는가. FakeSession은 WHERE를 평가하지
        않으므로 ⑵는 PG가 적용한 결과를 후보 큐로 흉내낸다 — PG가 `NOT IN`을 실제로 적용한다는
        사실 자체는 `test_me_integration.py`의 실 PG 테스트가 별도로 증명한다.
        """
        pid_a, pid_b = uuid.uuid4(), uuid.uuid4()  # 둘 다 난이도 3.0(θ=0 동률)

        def _call(attempts: list[Any], pool: list[Any]) -> tuple[str | None, str]:
            session = _next_problem_recording_session(
                [_AQResult(attempts), _AQResult(pool)] + _reason_results()
            )
            body = _attempts_client(session).get("/v1/me/next-problem").json()
            return body["problem_id"], str(session.statements[_NP_STMT_BASE + 1])

        # ① attempt 0행 — NOT IN 없음·풀 첫 문항 반환
        before_id, before_sql = _call([], [(pid_a, 3.0, None), (pid_b, 3.0, None)])
        assert "problem_id NOT IN" not in before_sql
        assert before_id == str(pid_a)

        # ② attempt 1건 주입(pid_a 채점) — NOT IN이 SQL에 실리고, 반환 문항이 바뀐다
        after_id, after_sql = _call([(pid_a, True, 3.0, None)], [(pid_b, 3.0, None)])
        assert "problem_id NOT IN" in after_sql
        assert after_id == str(pid_b)
        assert after_id != before_id

        # ③ 되돌림 — NOT IN이 사라지고 원래 문항으로 복귀
        back_id, back_sql = _call([], [(pid_a, 3.0, None), (pid_b, 3.0, None)])
        assert "problem_id NOT IN" not in back_sql
        assert back_id == before_id


# ── S2-06: GET /v1/me/next-problem?mode=suneung (수능 적응 추천 — L6 게이팅 × IRT CAT) ──
def _suneung_problem(**over: object) -> SchemaProblem:
    """수능 모드 후보용 최소 자체생성 schema Problem 빌더(l6 test_gating `_problem` 답습)."""
    kwargs: dict[str, object] = {
        "source_type": SourceType.자체생성,
        # PB-03 — 검수 노출 게이트(`is_review_cleared`) 추가로 기본값도 approved가 필요.
        "review_status": ReviewStatus.approved,
        "curriculum_version": Curriculum.REVISION_2022,
        "valid_from_year": 2022,
        "subject": Subject.미적분,
        "unit_codes": ["CAL-INT-DEF"],
        "difficulty_overall": 3.0,
    }
    kwargs.update(over)
    return SchemaProblem(**kwargs)  # type: ignore[arg-type]


class _OrmProblemRow:
    """`select(Problem)` ORM 행 시뮬 — 핸들러는 `.to_schema()`만 호출한다(hermetic)."""

    def __init__(self, problem: SchemaProblem) -> None:
        self._problem = problem

    def to_schema(self) -> SchemaProblem:
        return self._problem


class TestNextProblemSuneungMode:
    """S2-06: ?mode=suneung — 수능 게이팅(진실 게이트) × IRT CAT 결합 분기.

    _QueueSession 큐: ①채점 이력 ②수능 후보(ORM 행 — scalars().all()이 그대로 반환되어
    `.to_schema()`만 요구). prioritize_weak_concepts=true면 ③숙달 스냅샷 ④개념 매핑 추가.
    SQL 사전필터(저작권·수능 신호·θ 근방)는 stmt 무시(FakeSession)라 여기선 *진실 게이트*
    (recommend_suneung_index 내부 is_suneung_eligible)의 최종 판정만 검증된다 — 사전필터가
    못 거른 행도 게이트가 차단함을 그대로 보여준다(설계 계약).
    """

    def test_response_reason_field_is_required_not_optional(self) -> None:
        """EOS-19: 응답 경계에서도 `reason`은 **필수**다 — 옵셔널이면 비는 경로가 생긴다.

        키 집합 단언(`set(body)`)만으로는 이것을 못 잡는다: 기본값 None을 준 옵셔널 필드도
        키는 그대로 실리기 때문이다(뮤테이션 M2 생존으로 실측 · 2026-09-18). 계획서 §8 KPI 3
        ("reason 없이 생성된 추천 = 0")을 응답 스키마에서 지키는 것은 이 단언이다.
        """
        assert NextProblemResponse.model_fields["reason"].is_required() is True
        assert NextProblemResponse.model_fields["action"].is_required() is True

    def test_recommends_signature_item_same_response_schema(self) -> None:
        """시그니처 보유 자체생성 문항 추천 — 응답 스키마는 기본 CAT과 동일(회귀 0 계약)."""
        problem = _suneung_problem(
            signature_patterns=[SignaturePattern.COMPOUND_CHOICES],
        )
        session = _next_problem_session(
            [_AQResult([]), _AQResult([_OrmProblemRow(problem)])] + _reason_results()
        )
        client = _attempts_client(session)
        body = client.get("/v1/me/next-problem?mode=suneung").json()
        # 응답 모델(NextProblemResponse) — 기존 5필드 + REC-01 4필드 + REC-04 band_calibrated.
        assert set(body) == {
            "problem_id",
            "theta",
            "difficulty",
            "standard_error",
            "measurement_sufficient",
            "weight_axes_applied",
            "candidate_pool_size",
            "weak_concept_signal_count",
            "candidate_zero_reason",
            "band_calibrated",
            "reason",  # EOS-14: 추천 근거 — 기존 관측 메타와 별개 축(옵셔널 아님)
            "action",  # EOS-19: 근거에서 파생된 학습 행위(근거와 어긋나면 생성 자체가 실패)
            "target_concept",  # EOS-19: 다음에 다뤄야 할 개념(선수 막힘이면 막힌 선수)
        }
        assert body["problem_id"] == str(problem.problem_id)
        assert body["difficulty"] == 3.0
        assert body["theta"] == 0.0
        # 수능 모드는 suneung_priority 축이 항상 적용(약점 가중은 flag 미지정 → 미적용).
        assert body["weight_axes_applied"] == ["suneung_priority"]
        assert body["candidate_pool_size"] == 1
        assert body["weak_concept_signal_count"] == 0
        assert body["candidate_zero_reason"] is None
        assert body["band_calibrated"] is None  # purpose 기본(diagnosis)은 밴드 미적용

    def test_recommendation_records_mode_suneung_in_treatment_meta(self) -> None:
        """REC-03 — 수능 모드 추천도 처치로 기록되며 meta.mode="suneung"이 남는다."""
        problem = _suneung_problem(signature_patterns=[SignaturePattern.COMPOUND_CHOICES])
        session = _next_problem_session(
            [_AQResult([]), _AQResult([_OrmProblemRow(problem)])] + _reason_results()
        )
        client = _attempts_client(session)
        client.get("/v1/me/next-problem?mode=suneung")
        assert len(session.added) == 1
        row = session.added[0]
        assert row.meta[META_KEY_MODE] == "suneung"
        assert row.meta[META_KEY_PROBLEM_ID] == str(problem.problem_id)
        assert session.commits == 1

    def test_recommendation_records_candidates_and_policy_version_suneung(self) -> None:
        """REC-11 — 수능 모드 처치 기록에 candidates[]·policy_version=suneung_v1이 실린다.

        적격(시그니처 보유)·부적격(수능 신호 전무) 후보를 함께 넣어 candidates[]가 부적격을
        빼고 적격만 담는지(진실 게이트 재적용)까지 함께 확인한다.
        """
        eligible = _suneung_problem(signature_patterns=[SignaturePattern.COMPOUND_CHOICES])
        ineligible = _suneung_problem()  # 수능 신호 전무 → is_suneung_eligible=False
        session = _next_problem_session(
            [_AQResult([]), _AQResult([_OrmProblemRow(eligible), _OrmProblemRow(ineligible)])]
            + _reason_results()
        )
        client = _attempts_client(session)
        client.get("/v1/me/next-problem?mode=suneung")
        assert len(session.added) == 1
        row = session.added[0]
        assert row.meta[META_KEY_POLICY_VERSION] == POLICY_VERSION_SUNEUNG
        candidates = row.meta[META_KEY_CANDIDATES]
        assert {c["problem_id"] for c in candidates} == {str(eligible.problem_id)}

    def test_purpose_learning_applies_in_suneung_mode_too(self) -> None:
        """REC-04 — purpose는 mode와 직교한다: 수능 모드에서도 밴드 안 후보가 선택된다."""
        band_b = -math.log(0.8 / 0.2)  # θ=0에서 P=0.8(밴드 안)
        mid = _suneung_problem(
            signature_patterns=[SignaturePattern.COMPOUND_CHOICES], irt_difficulty_b=0.0
        )
        banded = _suneung_problem(
            signature_patterns=[SignaturePattern.COMPOUND_CHOICES], irt_difficulty_b=band_b
        )
        session = _next_problem_session(
            [_AQResult([]), _AQResult([_OrmProblemRow(mid), _OrmProblemRow(banded)])]
            + _reason_results()
        )
        client = _attempts_client(session)
        body = client.get("/v1/me/next-problem?mode=suneung&purpose=learning").json()
        assert body["problem_id"] == str(banded.problem_id)
        assert body["band_calibrated"] is False

    def test_no_eligible_candidates_null(self) -> None:
        """적격 0 → problem_id null(기본 CAT과 동일한 null 응답 계약)."""
        # 수능 신호 전무(기출 아님·시그니처 없음·적합도 없음) → 진실 게이트에서 탈락.
        no_signal = _suneung_problem()
        session = _next_problem_session([_AQResult([]), _AQResult([_OrmProblemRow(no_signal)])])
        client = _attempts_client(session)
        body = client.get("/v1/me/next-problem?mode=suneung").json()
        assert body == {
            "problem_id": None,
            "theta": 0.0,
            "difficulty": None,
            "standard_error": None,
            "measurement_sufficient": False,
            # REC-01: 후보 풀은 1건 있었으나(SQL 사전필터 통과) L6 진실 게이트가 전부 배제
            # — '후보 0건'과 '전부 부적격'을 사유 코드로 구분(candidate_pool_size 참고).
            "weight_axes_applied": ["suneung_priority"],
            "candidate_pool_size": 1,
            "weak_concept_signal_count": 0,
            "candidate_zero_reason": "all_candidates_gated_ineligible",
            "band_calibrated": None,  # REC-04: purpose 기본(diagnosis)은 밴드 미적용
            # EOS-14: 전부 부적격도 "후보 없음"의 한 형태 — 이유가 비지 않는다.
            "reason": _REASON_NO_CANDIDATE,
            # EOS-19: 부재의 행위는 none이고 목표 개념은 없다(지어내지 않는다).
            "action": "none",
            "target_concept": None,
        }
        assert session.added == []  # REC-03: null 응답은 처치가 아니다(가짜 처치 금지)
        assert session.commits == 0

    def test_copyright_blocked_source_null_even_if_sql_leaks(self) -> None:
        """평가원 출처가 후보에 섞여 들어와도(사전필터 실패 가정) 진실 게이트가 차단 → null.

        수능 모드 핵심 저작권 계약 — 평가원 기출 본문 절대 노출 불가(자체생성 동등문제만).
        """
        blocked = _suneung_problem(source_type=SourceType.평가원, exam_type=ExamType.수능)
        session = _next_problem_session([_AQResult([]), _AQResult([_OrmProblemRow(blocked)])])
        client = _attempts_client(session)
        body = client.get("/v1/me/next-problem?mode=suneung").json()
        assert body["problem_id"] is None

    def test_persona_d_blocks_all(self) -> None:
        """persona=D_학종고2(비응시) → 적격 후보가 있어도 전부 차단 → null."""
        eligible = _suneung_problem(exam_type=ExamType.수능)
        session = _next_problem_session([_AQResult([]), _AQResult([_OrmProblemRow(eligible)])])
        client = _attempts_client(session)
        body = client.get(
            "/v1/me/next-problem", params={"mode": "suneung", "persona": "D_학종고2"}
        ).json()
        assert body["problem_id"] is None

    def test_weak_concept_priority_combines(self) -> None:
        """prioritize_weak_concepts 결합 — 동률 수능 후보 중 약점 개념 문항이 곱 가중으로 선택.

        쿼리 4회: ①채점 이력 ②수능 후보 ③숙달 스냅샷 ④후보 개념 매핑(기본 CAT과 동일 헬퍼).
        """
        strong = _suneung_problem(exam_type=ExamType.수능)
        weak = _suneung_problem(exam_type=ExamType.수능)
        c_strong, c_weak = uuid.uuid4(), uuid.uuid4()
        session = _next_problem_session(
            [
                _AQResult([]),  # 채점 이력 없음 → θ=0
                _AQResult([_OrmProblemRow(strong), _OrmProblemRow(weak)]),  # 동률 후보
                _AQResult([(c_strong, 1.0), (c_weak, 0.0)]),  # 숙달: 강·약
                _AQResult([(strong.problem_id, c_strong), (weak.problem_id, c_weak)]),  # 개념 매핑
            ]
            + _reason_results()
        )
        client = _attempts_client(session)
        body = client.get("/v1/me/next-problem?mode=suneung&prioritize_weak_concepts=true").json()
        # 균등이면 동률→strong(낮은 인덱스)이나, 약점 곱 가중으로 weak 선택.
        assert body["problem_id"] == str(weak.problem_id)

    def test_mode_unspecified_regression_preserved(self) -> None:
        """mode 미지정 → 기존 기본 CAT 경로 그대로(튜플 행 후보·동률은 낮은 인덱스·회귀 0)."""
        pid_a, pid_b = uuid.uuid4(), uuid.uuid4()
        session = _next_problem_session(
            [_AQResult([]), _AQResult([(pid_a, 3.0, None), (pid_b, 3.0, None)])] + _reason_results()
        )
        client = _attempts_client(session)
        body = client.get("/v1/me/next-problem").json()
        assert body["problem_id"] == str(pid_a)

    def test_requires_auth(self) -> None:
        """미인증 → 401(기본 CAT과 동일 — 세션 전 인증 게이트)."""
        app = create_app()

        async def _sess() -> AsyncIterator[_QueueSession]:
            yield _next_problem_session([_AQResult([]), _AQResult([])])

        app.dependency_overrides[get_session] = _sess
        resp = TestClient(app).get("/v1/me/next-problem?mode=suneung")
        assert resp.status_code == 401


# ── EOS-14: 추천 근거(`reason`)가 응답에 **실제로** 실리는가 ────────────────────────
class _MasteryRow:
    """`_latest_mastery`가 돌려주는 ORM 행의 최소 시뮬 — 근거가 읽는 두 필드만 가진다."""

    def __init__(self, mastery: float | None, confidence: float | None) -> None:
        self.mastery = mastery
        self.confidence = confidence


def _reason_results_measured(concept_id: uuid.UUID, row: _MasteryRow | None) -> list[_AQResult]:
    """대표 개념이 **잡히는** 경로의 근거 조회 2건 — ①PRIMARY 히트 ②최신 숙달(없으면 빈 행).

    PRIMARY가 비지 않으므로 TESTED 폴백 조회는 일어나지 않는다(그래서 2건) — 이 개수 자체가
    `get_primary_concept_id`의 단락 동작을 동결한다.
    """
    return [_AQResult([concept_id]), _AQResult([row] if row is not None else [])]


class TestNextProblemReason:
    """`GET /v1/me/next-problem`의 `reason` — 계약이 응답 표면까지 도달했는가(집행 지점).

    계약·규칙 자체는 `tests/backend/l2/test_recommendation_contract.py`가, 조회기는
    `test_recommendation_reason.py`가 검증한다. 여기서 보는 것은 **핸들러 4경로가 모두
    근거를 싣는가** 하나다 — "모듈은 있는데 아무도 안 부른다"(CLAUDE.md 정본화≠집행)를 막는다.
    """

    @staticmethod
    def _measured(mastery: float, confidence: float = 0.5) -> tuple[uuid.UUID, dict[str, object]]:
        """숙달 실측이 있는 CAT 경로 1건을 돌려 실행하고 `reason`을 꺼낸다."""
        pid, cid = uuid.uuid4(), uuid.uuid4()
        session = _next_problem_session(
            [_AQResult([]), _AQResult([(pid, 3.0, None)])]
            + _reason_results_measured(cid, _MasteryRow(mastery, confidence))
        )
        body = _attempts_client(session).get("/v1/me/next-problem").json()
        assert body["problem_id"] == str(pid)
        return cid, body["reason"]

    def test_low_mastery_reports_prerequisite_gap_with_measured_basis(self) -> None:
        """숙달 0.2(<0.4) → 선수개념으로 돌아가라 · 근거는 실측이고 개념·숙달이 함께 실린다."""
        cid, reason = self._measured(0.2)
        assert reason == {
            "type": "prerequisite_gap",
            "confidence": 0.5,
            "basis": "measured_mastery",
            "concept_id": str(cid),
            "mastery": 0.2,
        }

    def test_mid_mastery_reports_current_concept(self) -> None:
        _, reason = self._measured(0.55)
        assert reason["type"] == "current_concept"
        assert reason["basis"] == "measured_mastery"

    def test_high_mastery_reports_next_concept(self) -> None:
        _, reason = self._measured(0.9)
        assert reason["type"] == "next_concept"

    def test_cold_start_is_not_reported_as_prerequisite_gap(self) -> None:
        """개념은 매핑됐는데 숙달 이력이 없다 → `cold_start`.

        이 갈래를 `prerequisite_gap`으로 접으면 **측정된 적 없는 학생이 전부 "선수개념이
        막혔다"로 분류된다** — 없는 약점을 만들어 내는 형태라 따로 본다.
        """
        pid, cid = uuid.uuid4(), uuid.uuid4()
        session = _next_problem_session(
            [_AQResult([]), _AQResult([(pid, 3.0, None)])] + _reason_results_measured(cid, None)
        )
        reason = _attempts_client(session).get("/v1/me/next-problem").json()["reason"]
        assert reason["type"] == "unmeasured"
        assert reason["basis"] == "cold_start"
        assert reason["concept_id"] == str(cid)
        assert reason["mastery"] is None  # 0.0으로 접지 않는다(S3-07 None≠0)

    def test_unmapped_problem_is_reported_as_our_data_gap(self) -> None:
        """문항-개념 매핑이 없으면 학생 상태가 아니라 **우리 쪽 공백**으로 표기된다."""
        pid = uuid.uuid4()
        session = _next_problem_session(
            [_AQResult([]), _AQResult([(pid, 3.0, None)])] + _reason_results()
        )
        reason = _attempts_client(session).get("/v1/me/next-problem").json()["reason"]
        assert reason == _REASON_UNMAPPED

    def test_suneung_branch_carries_reason_too(self) -> None:
        """수능 분기도 같은 근거를 싣는다 — 한쪽 분기만 배선하면 그 경로가 조용히 빈다."""
        problem = _suneung_problem(signature_patterns=[SignaturePattern.COMPOUND_CHOICES])
        cid = uuid.uuid4()
        session = _next_problem_session(
            [_AQResult([]), _AQResult([_OrmProblemRow(problem)])]
            + _reason_results_measured(cid, _MasteryRow(0.2, 0.75))
        )
        body = _attempts_client(session).get("/v1/me/next-problem?mode=suneung").json()
        assert body["problem_id"] == str(problem.problem_id)
        assert body["reason"] == {
            "type": "prerequisite_gap",
            "confidence": 0.75,
            "basis": "measured_mastery",
            "concept_id": str(cid),
            "mastery": 0.2,
        }

    def test_absent_recommendation_asks_nothing(self) -> None:
        """추천이 없으면 근거 조회 0건 — 소비된 쿼리 수를 변별력으로 쓴다.

        EOS-19 이후 기준선은 `_NP_STMT_BASE`(LearnerState 조립 5건)이다. 시나리오가 쓰는 것은
        그 뒤의 2건(①채점 이력 ②후보 풀)뿐이고, 근거가 한 건이라도 물었으면 그보다 커진다.
        """
        session = _next_problem_session([_AQResult([]), _AQResult([])])
        body = _attempts_client(session).get("/v1/me/next-problem").json()
        assert body["reason"] == _REASON_NO_CANDIDATE
        assert session._i == _NP_STMT_BASE + 2

    def test_learning_purpose_alone_still_records_applied_weights(self) -> None:
        """EOS-19 회귀 가드 — `purpose=learning`만 준 요청도 '가중 적용됨'으로 기록된다.

        전환 중 처치 기록의 `applied_weights`를 응답의 `weight_axes_applied`(정직 표기)에서
        유도했다가 이 경우가 갈라졌다: 정직 표기는 약점·수능 축만 싣고 학습 밴드 축은 싣지
        않으므로, 밴드 가중만 적용된 요청이 **가중 미적용(False)**으로 기록됐다. 전환 전
        핸들러는 `weights is not None`이라 True였다 — 스위트는 이 조합을 재는 시나리오가
        없어 초록이었고, 적대적 diff 재검토가 잡았다(2026-09-18).
        """
        pid = uuid.uuid4()
        session = _next_problem_session(
            [_AQResult([]), _AQResult([(pid, 3.0, None)])] + _reason_results()
        )
        client = _attempts_client(session)
        # prioritize_weak_concepts 미지정(기본 false) + purpose=learning → 밴드 가중만 적용.
        body = client.get("/v1/me/next-problem?purpose=learning").json()
        assert body["problem_id"] == str(pid)
        assert body["weight_axes_applied"] == []  # 정직 표기에는 밴드 축이 없다(기존 계약)
        treatment = [row for row in session.added if hasattr(row, "meta") and row.meta is not None]
        assert treatment, "처치 기록이 없다 — 이 단언이 공허해진다"
        assert treatment[0].meta[META_KEY_APPLIED_WEIGHTS] is True

    def test_persisted_treatment_carries_the_same_reason_as_the_response(self) -> None:
        """acceptance ④ — 근거가 응답에만 있고 로그에는 없으면 소급 평가에서 사라진다.

        같은 값이어야 한다는 점이 핵심이다: 응답용·영속용을 각자 계산하면 언젠가 갈라지고,
        갈라진 뒤에는 어느 쪽이 그때 학생이 본 근거인지 아무도 모른다.
        """
        pid, cid = uuid.uuid4(), uuid.uuid4()
        session = _next_problem_session(
            [_AQResult([]), _AQResult([(pid, 3.0, None)])]
            + _reason_results_measured(cid, _MasteryRow(0.2, 0.5))
        )
        body = _attempts_client(session).get("/v1/me/next-problem").json()
        assert len(session.added) == 1
        assert session.added[0].meta[META_KEY_REASON] == body["reason"]
        assert body["reason"]["type"] == "prerequisite_gap"

    def test_suneung_persisted_treatment_carries_reason_too(self) -> None:
        problem = _suneung_problem(signature_patterns=[SignaturePattern.COMPOUND_CHOICES])
        cid = uuid.uuid4()
        session = _next_problem_session(
            [_AQResult([]), _AQResult([_OrmProblemRow(problem)])]
            + _reason_results_measured(cid, _MasteryRow(0.9, 0.6))
        )
        body = _attempts_client(session).get("/v1/me/next-problem?mode=suneung").json()
        assert len(session.added) == 1
        assert session.added[0].meta[META_KEY_REASON] == body["reason"]
        assert body["reason"]["type"] == "next_concept"

    def test_reason_does_not_change_the_selected_problem(self) -> None:
        """acceptance⑥ — 근거를 붙여도 선택은 그대로다.

        같은 후보 풀에 서로 다른 근거 재료(저숙달 · 고숙달 · 매핑 없음)를 물려도 선택된
        문항이 바뀌지 않는지 본다. 근거 조립이 선택 *뒤에* 오는 구조라 그럴 수밖에 없지만,
        그 구조가 깨지면(예: 근거를 먼저 계산해 가중에 쓰면) 여기서 먼저 드러난다.
        """
        pid_a, pid_b = uuid.uuid4(), uuid.uuid4()
        cid = uuid.uuid4()
        picks = set()
        for tail in (
            _reason_results_measured(cid, _MasteryRow(0.0, 1.0)),
            _reason_results_measured(cid, _MasteryRow(1.0, 1.0)),
            _reason_results(),
        ):
            session = _next_problem_session(
                [_AQResult([]), _AQResult([(pid_a, 3.0, None), (pid_b, 3.0, None)])] + tail
            )
            picks.add(_attempts_client(session).get("/v1/me/next-problem").json()["problem_id"])
        assert picks == {str(pid_a)}


class TestWeakConceptWeights:
    """slice 17: `_weak_concept_weights` 순수 헬퍼 — 문항별 약점 가중치 산출."""

    def test_no_concept_mapping_neutral(self) -> None:
        pid = uuid.uuid4()
        assert _weak_concept_weights([pid], {}, {}) == [1.0]

    def test_mapped_but_no_mastery_neutral(self) -> None:
        pid, c = uuid.uuid4(), uuid.uuid4()
        assert _weak_concept_weights([pid], {pid: {c}}, {}) == [1.0]

    def test_weakness_scales_weight(self) -> None:
        pid, c = uuid.uuid4(), uuid.uuid4()
        assert _weak_concept_weights([pid], {pid: {c}}, {c: 0.0}) == [2.0]  # 완전 약점
        assert _weak_concept_weights([pid], {pid: {c}}, {c: 1.0}) == [1.0]  # 완전 숙달
        assert _weak_concept_weights([pid], {pid: {c}}, {c: 0.25}) == [1.75]

    def test_min_mastery_among_concepts(self) -> None:
        """문항의 여러 평가 개념 중 *최저* 숙달로 weakness 산출."""
        pid = uuid.uuid4()
        c1, c2 = uuid.uuid4(), uuid.uuid4()
        weights = _weak_concept_weights([pid], {pid: {c1, c2}}, {c1: 0.8, c2: 0.2})
        assert weights == [1.8]  # min(0.8, 0.2)=0.2 → 1+0.8

    def test_order_and_independence(self) -> None:
        p1, p2 = uuid.uuid4(), uuid.uuid4()
        c = uuid.uuid4()
        # p1 약점·p2 매핑 없음 → [2.0, 1.0] 순서 보존
        assert _weak_concept_weights([p1, p2], {p1: {c}}, {c: 0.0}) == [2.0, 1.0]


def _diagnosis_client(mastery_rows: list[Any], irt_rows: list[Any]) -> TestClient:
    """slice 19: 진단 엔드포인트(쿼리 2회 — ①BKT 스냅샷 ②개념별 IRT) 큐 세션."""
    return _attempts_client(_QueueSession([_AQResult(mastery_rows), _AQResult(irt_rows)]))


class TestConceptDiagnosis:
    """slice L2-19: GET /v1/me/diagnosis/concepts — BKT↔IRT 교차검증.

    쿼리 2회: ①BKT 숙달 스냅샷(concept_id,code,name,mastery) ②개념별 IRT
    (concept_id,code,name,is_correct,difficulty,irt_difficulty_b). 그룹화·합집합·신호 분류만 본다.
    slice 81: IRT 행에 보정 b 컬럼 추가(None=휴리스틱 폴백).
    """

    def test_empty_returns_empty(self) -> None:
        body = _diagnosis_client([], []).get("/v1/me/diagnosis/concepts").json()
        assert body == []

    def test_requires_auth(self) -> None:
        app = create_app()

        async def _sess() -> AsyncIterator[_QueueSession]:
            yield _QueueSession([_AQResult([]), _AQResult([])])

        app.dependency_overrides[get_session] = _sess
        assert TestClient(app).get("/v1/me/diagnosis/concepts").status_code == 401

    def test_both_signals_agree(self) -> None:
        """BKT 0.5 · IRT 1정답1오답(θ=0→프록시 0.5) → agree."""
        cid = uuid.uuid4()
        client = _diagnosis_client(
            [(cid, "C", "개념", 0.5)],
            [(cid, "C", "개념", True, 3.0, None), (cid, "C", "개념", False, 3.0, None)],
        )
        body = client.get("/v1/me/diagnosis/concepts").json()
        assert len(body) == 1
        item = body[0]
        assert item["bkt_mastery"] == 0.5
        assert item["irt_theta"] == 0.0
        assert item["irt_mastery_proxy"] == 0.5
        assert item["response_count"] == 2
        assert item["agreement"] == "agree"
        assert item["concept_name"] == "개념"
        # slice 21: L4 코칭 처방 결선 — 합의·수준 0.5<0.6 → foundation
        assert item["coaching"]["focus"] == "foundation"
        assert item["coaching"]["prompt"]
        assert item["coaching"]["rationale"]
        # MOB-10: bkt_mastery=0.5 → mastery_to_level 발전 중 구간(0.4~0.8)
        assert item["mastery_level"] == "발전 중"

    def test_irt_higher_signal(self) -> None:
        """BKT 0.1인데 전부 정답(θ=4·프록시≈0.98) → irt_higher·코칭 consolidate."""
        cid = uuid.uuid4()
        client = _diagnosis_client([(cid, "C", "개념", 0.1)], [(cid, "C", "개념", True, 3.0, None)])
        item = client.get("/v1/me/diagnosis/concepts").json()[0]
        assert item["agreement"] == "irt_higher"
        assert item["irt_theta"] == 4.0
        assert item["coaching"]["focus"] == "consolidate"
        # slice 22: 코칭에 대화 진입 소크라테스 카테고리 노출
        assert item["coaching"]["socratic_category"] == "evidence"

    def test_bkt_higher_signal(self) -> None:
        """BKT 0.9인데 전부 오답(θ=-4·프록시≈0.02) → bkt_higher·코칭 retrieval."""
        cid = uuid.uuid4()
        client = _diagnosis_client(
            [(cid, "C", "개념", 0.9)], [(cid, "C", "개념", False, 3.0, None)]
        )
        item = client.get("/v1/me/diagnosis/concepts").json()[0]
        assert item["agreement"] == "bkt_higher"
        assert item["coaching"]["focus"] == "retrieval"
        # MOB-10: bkt_mastery=0.9 → mastery_to_level 숙달 구간(>=0.8)
        assert item["mastery_level"] == "숙달"

    def test_bkt_only_concept_insufficient(self) -> None:
        """IRT 채점 없는 개념 → theta·proxy null·insufficient·코칭 diagnose."""
        cid = uuid.uuid4()
        client = _diagnosis_client([(cid, "C", "개념", 0.6)], [])
        item = client.get("/v1/me/diagnosis/concepts").json()[0]
        assert item["bkt_mastery"] == 0.6
        assert item["irt_theta"] is None
        assert item["irt_mastery_proxy"] is None
        assert item["response_count"] == 0
        assert item["agreement"] == "insufficient"
        assert item["coaching"]["focus"] == "diagnose"

    def test_irt_only_concept_insufficient(self) -> None:
        """BKT 숙달 없는 개념(IRT만) → bkt null·insufficient."""
        cid = uuid.uuid4()
        client = _diagnosis_client([], [(cid, "C", "개념", True, 3.0, None)])
        item = client.get("/v1/me/diagnosis/concepts").json()[0]
        assert item["bkt_mastery"] is None
        assert item["irt_theta"] == 4.0
        assert item["agreement"] == "insufficient"
        # MOB-10: bkt_mastery null이면 mastery_level도 null(무데이터 정직 표기 — 가짜 라벨 금지)
        assert item["mastery_level"] is None

    def test_irt_row_without_b_source_skipped(self) -> None:
        """slice 81: IRT 행의 난이도·보정 b 둘 다 없으면 제외 — 그 개념 IRT 신호 없음."""
        cid = uuid.uuid4()
        client = _diagnosis_client(
            [(cid, "C", "개념", 0.6)], [(cid, "C", "개념", True, None, None)]
        )
        item = client.get("/v1/me/diagnosis/concepts").json()[0]
        assert item["irt_theta"] is None  # 유일 IRT 행 제외 → θ 없음
        assert item["response_count"] == 0
        assert item["agreement"] == "insufficient"

    def test_mastery_level_boundary_labels(self) -> None:
        """MOB-10: mastery_to_level 3구간 경계 — 0.4·0.8은 *상위* 라벨에 포함(≥)."""
        below, at_dev, at_mastered = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        client = _diagnosis_client(
            [
                (below, "C1", "개념1", 0.39),
                (at_dev, "C2", "개념2", 0.4),
                (at_mastered, "C3", "개념3", 0.8),
            ],
            [],
        )
        by_id = {
            item["concept_id"]: item["mastery_level"]
            for item in client.get("/v1/me/diagnosis/concepts").json()
        }
        assert by_id[str(below)] == "초보"
        assert by_id[str(at_dev)] == "발전 중"
        assert by_id[str(at_mastered)] == "숙달"

    def test_sorted_weakest_first(self) -> None:
        """약점(저신호) 개념 먼저 — BKT 0.1 < 0.9."""
        c_low, c_high = uuid.uuid4(), uuid.uuid4()
        client = _diagnosis_client([(c_high, "H", "상", 0.9), (c_low, "L", "하", 0.1)], [])
        body = client.get("/v1/me/diagnosis/concepts").json()
        assert [i["concept_id"] for i in body] == [str(c_low), str(c_high)]

    def test_limit_returns_n_weakest(self) -> None:
        """slice 26: ?limit=1 → 약점 먼저 정렬 후 상위 1개(가장 약한 개념)."""
        c_low, c_mid, c_high = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        client = _diagnosis_client(
            [
                (c_high, "H", "상", 0.9),
                (c_low, "L", "하", 0.1),
                (c_mid, "M", "중", 0.5),
            ],
            [],
        )
        body = client.get("/v1/me/diagnosis/concepts?limit=1").json()
        assert len(body) == 1
        assert body[0]["concept_id"] == str(c_low)

    def test_agreement_filter_only_matching(self) -> None:
        """slice 26: ?agreement=insufficient → 해당 신호 개념만."""
        # BKT만(insufficient) c1 · 합의(agree) c2
        c_insuff, c_agree = uuid.uuid4(), uuid.uuid4()
        client = _diagnosis_client(
            [(c_insuff, "I", "불충분", 0.3), (c_agree, "A", "합의", 0.5)],
            [
                (c_agree, "A", "합의", True, 3.0, None),
                (c_agree, "A", "합의", False, 3.0, None),
            ],
        )
        body = client.get("/v1/me/diagnosis/concepts?agreement=insufficient").json()
        assert [i["concept_id"] for i in body] == [str(c_insuff)]
        assert all(i["agreement"] == "insufficient" for i in body)

    def test_agreement_filter_multi_or(self) -> None:
        """반복 지정 시 OR — 두 신호 모두 포함."""
        c_insuff, c_agree = uuid.uuid4(), uuid.uuid4()
        client = _diagnosis_client(
            [(c_insuff, "I", "불충분", 0.3), (c_agree, "A", "합의", 0.5)],
            [
                (c_agree, "A", "합의", True, 3.0, None),
                (c_agree, "A", "합의", False, 3.0, None),
            ],
        )
        body = client.get("/v1/me/diagnosis/concepts?agreement=insufficient&agreement=agree").json()
        assert len(body) == 2

    def test_invalid_agreement_rejected_422(self) -> None:
        client = _diagnosis_client([], [])
        resp = client.get("/v1/me/diagnosis/concepts?agreement=bogus")
        assert resp.status_code == 422


class TestDiagnosisSummary:
    """slice L2-27: GET /v1/me/diagnosis/summary — 진단 집계(대시보드 헤더)."""

    def test_empty_zeros(self) -> None:
        body = _diagnosis_client([], []).get("/v1/me/diagnosis/summary").json()
        assert body == {
            "total_concepts": 0,
            "agree": 0,
            "irt_higher": 0,
            "bkt_higher": 0,
            "insufficient": 0,
            "attention_count": 0,
            "weakest_concept_id": None,
            "weakest_concept_name": None,
        }

    def test_requires_auth(self) -> None:
        app = create_app()

        async def _sess() -> AsyncIterator[_QueueSession]:
            yield _QueueSession([_AQResult([]), _AQResult([])])

        app.dependency_overrides[get_session] = _sess
        assert TestClient(app).get("/v1/me/diagnosis/summary").status_code == 401

    def test_aggregates_and_weakest(self) -> None:
        """c1 insufficient(BKT 0.3)·c2 agree(0.5+θ0)·c3 irt_higher(0.1+전부정답·θ4)."""
        c1, c2, c3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        client = _diagnosis_client(
            [(c1, "I", "불충분", 0.3), (c2, "A", "합의", 0.5), (c3, "H", "높θ", 0.1)],
            [
                (c2, "A", "합의", True, 3.0, None),
                (c2, "A", "합의", False, 3.0, None),
                (c3, "H", "높θ", True, 3.0, None),
            ],
        )
        body = client.get("/v1/me/diagnosis/summary").json()
        assert body["total_concepts"] == 3
        assert body["agree"] == 1
        assert body["irt_higher"] == 1
        assert body["bkt_higher"] == 0
        assert body["insufficient"] == 1
        assert body["attention_count"] == 1  # irt_higher + bkt_higher
        # 최약점 = 최저 신호 c3(0.1)
        assert body["weakest_concept_id"] == str(c3)
        assert body["weakest_concept_name"] == "높θ"


class TestSessionEndConceptSnapshots:
    """slice 75: 세션 종료 자동 적재가 전과목 θ + 개념별 θ를 *같은 시각*으로 함께 추가."""

    async def test_adds_global_and_concept_snapshots(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cid_x, cid_y = uuid.uuid4(), uuid.uuid4()

        async def _fake_global(session: Any, user_id: Any) -> tuple[float, float | None, int]:
            return (1.2, 0.3, 5)

        async def _fake_concepts(session: Any, user_id: Any) -> list[ConceptAbilityItem]:
            return [
                ConceptAbilityItem(
                    concept_id=cid_x,
                    concept_code="A",
                    concept_name="가",
                    theta=0.8,
                    response_count=3,
                    standard_error=0.4,
                ),
                ConceptAbilityItem(
                    concept_id=cid_y,
                    concept_code="B",
                    concept_name="나",
                    theta=-0.5,
                    response_count=2,
                    standard_error=None,
                ),
            ]

        monkeypatch.setattr("whymath_backend.api.me.estimate_global_ability", _fake_global)
        monkeypatch.setattr("whymath_backend.api.me.compute_concept_abilities", _fake_concepts)
        fake = FakeSession()
        await _add_ability_snapshot_if_attempts(cast(AsyncSession, fake), _UID)

        # 전과목 1(concept_id None) + 개념 2(concept_id 값)
        assert len(fake.added) == 3
        globals_ = [a for a in fake.added if a.concept_id is None]
        concepts_ = [a for a in fake.added if a.concept_id is not None]
        assert len(globals_) == 1
        assert {a.concept_id for a in concepts_} == {cid_x, cid_y}
        # 전과목·개념 전원 동일 measured_at(같은 시각 원자 적재)
        assert len({a.measured_at for a in fake.added}) == 1
        # commit은 호출자(end_my_session) 책임 — 헬퍼는 add만
        assert fake.commits == 0

    async def test_skips_all_when_no_attempts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _fake_global(session: Any, user_id: Any) -> tuple[float, float | None, int]:
            return (0.0, None, 0)

        async def _boom(session: Any, user_id: Any) -> list[ConceptAbilityItem]:
            raise AssertionError("count==0이면 개념 θ 계산조차 하지 않아야 함")

        monkeypatch.setattr("whymath_backend.api.me.estimate_global_ability", _fake_global)
        monkeypatch.setattr("whymath_backend.api.me.compute_concept_abilities", _boom)
        fake = FakeSession()
        await _add_ability_snapshot_if_attempts(cast(AsyncSession, fake), _UID)
        # 채점 0 → 전과목·개념 θ 모두 미적재(개념 계산도 skip)
        assert fake.added == []


# ── ASM-03: POST /v1/me/assessments/capture ────────────────────────────────
class TestAssessmentCaptureWindow:
    """`_capture_window_start` — idempotency 창 시작 시각(UTC 자정) 순수 함수."""

    def test_truncates_to_utc_midnight(self) -> None:
        now = datetime(2026, 3, 15, 13, 45, 30, 123456, tzinfo=UTC)
        start = me_module._capture_window_start(now)
        assert start == datetime(2026, 3, 15, 0, 0, 0, 0, tzinfo=UTC)


class TestAssembleMeasurementAssessment:
    """`_assemble_measurement_assessment` — 기존 L2 산출물 4종 조립(신규 계산 0)을 단위검증.

    실 DB 쿼리(compute_concept_diagnoses 등 내부)는 monkeypatch로 대체 — 이 함수 자체가 하는
    일(호출 순서·필드 매핑·kind 판별자·예측 필드 하드 null)만 본다(실 쿼리는 통합테스트 몫).
    """

    def _patch_l2_outputs(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        diagnoses: list[ConceptDiagnosis],
        hypotheses: list[MisconceptionHypothesis],
        weak: list[WeakConceptRecommendation],
        strong: list[StrongConceptRecommendation] | None = None,
        gaps_calls: list[uuid.UUID] | None = None,
        path_steps: tuple[Any, ...] = (),
        ordering_basis: str = "empty",
        ordering_edge_count: int = 0,
        has_cycle: bool = False,
        path_calls: list[int] | None = None,
        weak_diagnoses_calls: list[Any] | None = None,
        strong_diagnoses_calls: list[Any] | None = None,
    ) -> None:
        async def _fake_diag(session: Any, user_id: Any) -> list[ConceptDiagnosis]:
            return diagnoses

        async def _fake_hyp(session: Any, user_id: Any) -> list[MisconceptionHypothesis]:
            return hypotheses

        async def _fake_weak(
            session: Any, user_id: Any, *, diagnoses: Any = None
        ) -> list[WeakConceptRecommendation]:
            # PR #1018 Codex 리뷰 — 호출자가 넘긴 diagnoses 스냅샷을 실제로 받는지 캡처.
            if weak_diagnoses_calls is not None:
                weak_diagnoses_calls.append(diagnoses)
            return weak

        async def _fake_strong(
            session: Any, user_id: Any, *, diagnoses: Any = None
        ) -> list[StrongConceptRecommendation]:
            if strong_diagnoses_calls is not None:
                strong_diagnoses_calls.append(diagnoses)
            return strong or []

        async def _fake_gaps(
            session: Any, user_id: Any, concept_id: uuid.UUID, **kwargs: Any
        ) -> list[Any]:
            if gaps_calls is not None:
                gaps_calls.append(concept_id)
            return []

        async def _fake_path(session: Any, gaps: Any) -> LearningPath:
            if path_calls is not None:
                path_calls.append(1)
            return LearningPath(
                steps=path_steps,
                ordering_basis=cast(Any, ordering_basis),
                ordering_edge_count=ordering_edge_count,
                has_cycle=has_cycle,
            )

        monkeypatch.setattr("whymath_backend.api.me.compute_concept_diagnoses", _fake_diag)
        monkeypatch.setattr("whymath_backend.api.me.get_active_hypotheses", _fake_hyp)
        monkeypatch.setattr("whymath_backend.api.me.recommend_weak_concepts", _fake_weak)
        monkeypatch.setattr("whymath_backend.api.me.recommend_strong_concepts", _fake_strong)
        monkeypatch.setattr("whymath_backend.api.me.recommend_prerequisite_gaps", _fake_gaps)
        monkeypatch.setattr("whymath_backend.api.me.build_learning_path", _fake_path)

    def test_never_populates_prediction_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """4개 예측 필드(등급·점수·백분위·합격예측)는 실 L2 산출물이 있어도 항상 null(게임화 금기)."""
        cid = uuid.uuid4()
        self._patch_l2_outputs(
            monkeypatch,
            diagnoses=[
                ConceptDiagnosis(
                    concept_id=cid,
                    concept_code="C-1",
                    concept_name="개념",
                    bkt_mastery=0.4,
                    irt_theta=-0.5,
                    irt_mastery_proxy=0.3,
                    response_count=5,
                    agreement="agree",
                )
            ],
            hypotheses=[
                MisconceptionHypothesis(
                    misconception_id="frac-add-denominator",
                    confidence=0.8,
                    turns_since_evidence=0,
                    evidence_count=2,
                )
            ],
            weak=[
                WeakConceptRecommendation(
                    concept_id=cid,
                    concept_code="C-1",
                    concept_name="개념",
                    bkt_mastery=0.4,
                    irt_mastery_proxy=0.3,
                    weakness=0.3,
                    agreement="agree",
                )
            ],
        )
        now = datetime(2026, 1, 1, tzinfo=UTC)
        schema = asyncio.run(
            me_module._assemble_measurement_assessment(
                cast(AsyncSession, FakeSession()), _UID, now=now
            )
        )
        assert schema.estimated_grade is None
        assert schema.estimated_score is None
        assert schema.estimated_percentile is None
        assert schema.admission_probability is None
        assert schema.target_university_id is None

    def test_concept_diagnosis_and_misconceptions_share_field_with_kind_tag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """concept_diagnosis JSONB 배열에 진단 1건 + 오개념 가설 1건이 kind로 구분돼 함께 담긴다."""
        cid = uuid.uuid4()
        self._patch_l2_outputs(
            monkeypatch,
            diagnoses=[
                ConceptDiagnosis(
                    concept_id=cid,
                    response_count=3,
                    agreement="insufficient",
                )
            ],
            hypotheses=[
                MisconceptionHypothesis(
                    misconception_id="frac-add-denominator",
                    confidence=0.6,
                    turns_since_evidence=1,
                    evidence_count=1,
                )
            ],
            weak=[],
        )
        schema = asyncio.run(
            me_module._assemble_measurement_assessment(
                cast(AsyncSession, FakeSession()), _UID, now=datetime(2026, 1, 1, tzinfo=UTC)
            )
        )
        assert len(schema.concept_diagnosis) == 2
        kinds = {item["kind"] for item in schema.concept_diagnosis}
        assert kinds == {"concept_diagnosis", "misconception_hypothesis"}
        misconception_item = next(
            item for item in schema.concept_diagnosis if item["kind"] == "misconception_hypothesis"
        )
        assert misconception_item["misconception_id"] == "frac-add-denominator"
        # 약개념 추천 0건 → weak_points·recommended_path 모두 빈 리스트(대상 개념 없음).
        assert schema.weak_points == []
        assert schema.recommended_path == []

    def test_weak_points_and_recommended_path_from_weakest_concept(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """weak_points는 recommend_weak_concepts 그대로, recommended_path는 *가장 약한*
        (첫 항목) 개념을 대상으로 build_learning_path를 호출해 얻는다(신규 계산 0)."""
        weakest, second = uuid.uuid4(), uuid.uuid4()
        gaps_calls: list[uuid.UUID] = []
        self._patch_l2_outputs(
            monkeypatch,
            diagnoses=[],
            hypotheses=[],
            weak=[
                WeakConceptRecommendation(concept_id=weakest, weakness=0.1, agreement="agree"),
                WeakConceptRecommendation(concept_id=second, weakness=0.5, agreement="agree"),
            ],
            gaps_calls=gaps_calls,
            path_steps=(
                LearningStep(position=0, concept_id=weakest, depth=1, is_cycle_residual=False),
            ),
        )
        schema = asyncio.run(
            me_module._assemble_measurement_assessment(
                cast(AsyncSession, FakeSession()), _UID, now=datetime(2026, 1, 1, tzinfo=UTC)
            )
        )
        assert len(schema.weak_points) == 2
        # 학습 경로는 첫(가장 약한) 개념(weakest)만 대상으로 조회됨.
        assert gaps_calls == [weakest]
        assert len(schema.recommended_path) == 1
        assert schema.recommended_path[0]["concept_id"] == str(weakest)

    def test_strong_points_from_recommend_strong_concepts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ASM-13 — `strong_points`는 `recommend_strong_concepts` 결과를 그대로 담는다.

        `recommend_weak_concepts`(weak_points)와 마찬가지로 신규 계산 0 — 호출·매핑만 검증."""
        strong_cid = uuid.uuid4()
        self._patch_l2_outputs(
            monkeypatch,
            diagnoses=[],
            hypotheses=[],
            weak=[],
            strong=[
                StrongConceptRecommendation(concept_id=strong_cid, mastery=0.95, agreement="agree")
            ],
        )
        schema = asyncio.run(
            me_module._assemble_measurement_assessment(
                cast(AsyncSession, FakeSession()), _UID, now=datetime(2026, 1, 1, tzinfo=UTC)
            )
        )
        assert len(schema.strong_points) == 1
        assert schema.strong_points[0]["concept_id"] == str(strong_cid)
        assert schema.strong_points[0]["mastery"] == 0.95

    def test_weak_and_strong_share_one_diagnoses_snapshot(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PR #1018 Codex 리뷰 — weak·strong이 각자 재조회하면 동시 mastery 갱신 시 서로 다른
        스냅샷을 볼 수 있었다. 이제 위에서 한 번 구한 `diagnoses`를 그대로 넘겨받는지 확인한다
        (둘 다 *같은 리스트 객체*를 받아야 한다 — 값만 같은 사본이 아니라 identity로 못 박는다).
        """
        cid = uuid.uuid4()
        shared = [
            ConceptDiagnosis(concept_id=cid, response_count=1, agreement="agree"),
        ]
        weak_calls: list[Any] = []
        strong_calls: list[Any] = []
        self._patch_l2_outputs(
            monkeypatch,
            diagnoses=shared,
            hypotheses=[],
            weak=[],
            strong=[],
            weak_diagnoses_calls=weak_calls,
            strong_diagnoses_calls=strong_calls,
        )
        asyncio.run(
            me_module._assemble_measurement_assessment(
                cast(AsyncSession, FakeSession()), _UID, now=datetime(2026, 1, 1, tzinfo=UTC)
            )
        )
        assert len(weak_calls) == 1 and weak_calls[0] is shared
        assert len(strong_calls) == 1 and strong_calls[0] is shared

    def test_strong_points_empty_when_no_recommendations(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_l2_outputs(monkeypatch, diagnoses=[], hypotheses=[], weak=[], strong=[])
        schema = asyncio.run(
            me_module._assemble_measurement_assessment(
                cast(AsyncSession, FakeSession()), _UID, now=datetime(2026, 1, 1, tzinfo=UTC)
            )
        )
        assert schema.strong_points == []


class TestCapturedPathOrderingHonesty:
    """`PATH-09` — 영속된 `recommended_path`에서 *정렬 근거*를 판독할 수 있는가.

    결함(상환 전): `path.steps`만 저장해 부모 `LearningPath`의 정직 표기 3종
    (`ordering_basis`·`ordering_edge_count`·`has_cycle`)이 통째로 사라졌다. 실측상 기본
    파라미터에서 **96.4%가 `tiebreak_only`**인데, 학생이 `GET /v1/me/assessments`로 다시 읽는
    스냅샷에는 그 사실이 없어 "근거 있는 순서"와 구별되지 않았다.

    비대칭이 결함의 증거였다 — `is_cycle_residual`은 *자식*(`LearningStep`) 필드라 살아남고
    `ordering_basis`는 *부모* 필드라 죽었다. 그런데 살아남은 축(사이클)은 원자 백본이 DAG
    보장이라 발생률 **0%**이고, 죽은 축은 **96.4%**다.
    """

    _STEPS_FIXTURE_CONCEPT = uuid.UUID("11111111-1111-1111-1111-111111111111")

    def _steps(self) -> tuple[Any, ...]:
        """두 fixture가 공유하는 **완전히 동일한** steps — 변별력 테스트의 전제."""
        return (
            LearningStep(
                position=0,
                concept_id=self._STEPS_FIXTURE_CONCEPT,
                depth=1,
                is_cycle_residual=False,
            ),
        )

    def _assemble(self, monkeypatch: pytest.MonkeyPatch, **ordering: Any) -> AssessmentSchema:
        helper = TestAssembleMeasurementAssessment()
        helper._patch_l2_outputs(
            monkeypatch,
            diagnoses=[],
            hypotheses=[],
            weak=[
                WeakConceptRecommendation(
                    concept_id=self._STEPS_FIXTURE_CONCEPT, weakness=0.1, agreement="agree"
                )
            ],
            path_steps=self._steps(),
            **ordering,
        )
        return asyncio.run(
            me_module._assemble_measurement_assessment(
                cast(AsyncSession, FakeSession()), _UID, now=datetime(2026, 1, 1, tzinfo=UTC)
            )
        )

    def test_persisted_step_carries_ordering_basis(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """①결함 재현 — 영속 산출물에서 정렬 근거 3종이 판독 가능해야 한다.

        상환 전 코드(`[step.model_dump() for step in path.steps]`)에서는 이 단언이 전부
        KeyError/누락으로 실패한다.
        """
        schema = self._assemble(monkeypatch, ordering_basis="tiebreak_only", ordering_edge_count=0)
        item = schema.recommended_path[0]
        assert item["ordering_basis"] == "tiebreak_only"
        assert item["ordering_edge_count"] == 0
        assert item["has_cycle"] is False
        # 자식 필드(원래도 살아남던 축)가 회귀하지 않았는지도 함께 고정.
        assert item["is_cycle_residual"] is False

    def test_identical_steps_different_basis_produce_different_snapshots(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """③변별력(핵심) — `steps`가 **완전히 동일**하고 `ordering_basis`만 다른 두 fixture의
        영속 산출물이 실제로 갈리는가. 갈리지 않으면 정직 표기는 위장이다."""
        topological = self._assemble(
            monkeypatch, ordering_basis="topological", ordering_edge_count=3
        )
        tiebreak = self._assemble(
            monkeypatch, ordering_basis="tiebreak_only", ordering_edge_count=0
        )

        # 전제 확인: 두 경우의 step 본체(정렬 근거 키 제외)는 바이트 단위로 같다.
        ordering_keys = set(me_module._CAPTURE_PATH_ORDERING_KEYS)

        def _body(schema: AssessmentSchema) -> list[dict[str, Any]]:
            return [
                {k: v for k, v in item.items() if k not in ordering_keys}
                for item in schema.recommended_path
            ]

        assert _body(topological) == _body(tiebreak)
        # 그럼에도 영속 산출물 전체는 달라야 한다 — 이 단언이 변별력 그 자체다.
        assert topological.recommended_path != tiebreak.recommended_path
        assert topological.recommended_path[0]["ordering_basis"] == "topological"
        assert tiebreak.recommended_path[0]["ordering_basis"] == "tiebreak_only"

    def test_ordering_values_copied_verbatim_with_single_path_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """④날조 방지 — 값은 `build_learning_path` 산출물을 *그대로* 옮긴 것이고,
        `LearningPath` 재호출은 0이다(조립당 정확히 1회)."""
        path_calls: list[int] = []
        schema = self._assemble(
            monkeypatch,
            ordering_basis="topological",
            ordering_edge_count=7,
            has_cycle=True,
            path_calls=path_calls,
        )
        assert path_calls == [1]  # 재호출 0 — 정확히 1회
        item = schema.recommended_path[0]
        # 정규화·보정·신뢰도 점수화 없이 원값 그대로(7이 0..1로 스케일되거나 하지 않는다).
        assert item["ordering_edge_count"] == 7
        assert item["has_cycle"] is True
        assert item["ordering_basis"] == "topological"

    def test_array_length_still_equals_step_count(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """②의 안전 조건 — 정직 표기를 넣었다고 **배열 길이 의미가 바뀌면 안 된다**.

        `assessment_seat_reach_report`의 `jsonb_array_length(recommended_path) > 0` 관측
        지표와 기존 step 수 단언이 그 길이를 소비한다. 헤더 원소를 끼우지 않은 이유가 이것이다.
        """
        schema = self._assemble(monkeypatch, ordering_basis="tiebreak_only", ordering_edge_count=0)
        assert len(schema.recommended_path) == len(self._steps()) == 1
        # 모든 원소가 여전히 step이다(메타 전용 원소가 섞이지 않았다).
        assert all("concept_id" in item for item in schema.recommended_path)

    def test_no_weak_concepts_yields_empty_array(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """빈 배열은 "담을 step이 없다"이며 별도 표기를 만들지 않는다(상수 docstring 계약)."""
        helper = TestAssembleMeasurementAssessment()
        helper._patch_l2_outputs(monkeypatch, diagnoses=[], hypotheses=[], weak=[])
        schema = asyncio.run(
            me_module._assemble_measurement_assessment(
                cast(AsyncSession, FakeSession()), _UID, now=datetime(2026, 1, 1, tzinfo=UTC)
            )
        )
        assert schema.recommended_path == []

    def test_student_facing_model_exposes_basis_without_prediction_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """⑤노출 정합 — 학생 대면 정본(`StudentAssessment`)에서도 정렬 근거가 판독 가능하고,
        예측 5필드는 여전히 **스키마에 자리가 없다**(ASM-07 구조적 배제 회귀 동결)."""
        schema = self._assemble(monkeypatch, ordering_basis="tiebreak_only", ordering_edge_count=0)
        student = StudentAssessmentSchema.from_assessment(schema)
        assert student.recommended_path[0]["ordering_basis"] == "tiebreak_only"
        for hidden in (
            "estimated_grade",
            "estimated_score",
            "estimated_percentile",
            "target_university_id",
            "admission_probability",
        ):
            assert hidden not in StudentAssessmentSchema.model_fields


class TestAssessmentCaptureEndpoint:
    """`POST /v1/me/assessments/capture` — measurement_sufficient 경계 결선(조립 함수는
    monkeypatch로 대체해 orchestration만 검증. 조립 자체는 `TestAssembleMeasurementAssessment`)."""

    def test_requires_auth(self) -> None:
        app = create_app()

        async def _sess() -> AsyncIterator[FakeSession]:
            yield FakeSession()

        app.dependency_overrides[get_session] = _sess
        assert TestClient(app).post("/v1/me/assessments/capture").status_code == 401

    def test_insufficient_measurement_not_written(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _fake_state(session: Any, user_id: Any) -> _AttemptHistoryState:
            return _AttemptHistoryState(
                attempted_ids=set(), theta=0.0, standard_error=0.9, measurement_sufficient=False
            )

        async def _boom_assemble(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("측정 불충분이면 조립 함수가 호출되면 안 된다")

        monkeypatch.setattr("whymath_backend.api.me._load_attempt_history_state", _fake_state)
        monkeypatch.setattr(
            "whymath_backend.api.me._assemble_measurement_assessment", _boom_assemble
        )
        client, fake = _client([])
        resp = client.post("/v1/me/assessments/capture")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["written"] is False
        assert body["reason"] == "insufficient_measurement"
        assert body["assessment"] is None
        assert body["measurement_sufficient"] is False
        assert body["standard_error"] == 0.9
        # 측정 불충분 → Assessment 적재 0(가짜 행 생성 금지 — CLAUDE.md).
        assert fake.commits == 0
        assert fake.added == []

    def test_written_when_measurement_sufficient(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _fake_state(session: Any, user_id: Any) -> _AttemptHistoryState:
            return _AttemptHistoryState(
                attempted_ids=set(), theta=0.5, standard_error=0.2, measurement_sufficient=True
            )

        async def _no_existing(session: Any, user_id: Any, now: Any) -> Assessment | None:
            return None

        async def _fake_assemble(session: Any, user_id: Any, *, now: datetime) -> AssessmentSchema:
            return AssessmentSchema(
                user_id=user_id,
                assessment_type=AssessmentType.단원진단,
                started_at=now,
                completed_at=now,
            )

        monkeypatch.setattr("whymath_backend.api.me._load_attempt_history_state", _fake_state)
        monkeypatch.setattr("whymath_backend.api.me._find_existing_capture", _no_existing)
        monkeypatch.setattr(
            "whymath_backend.api.me._assemble_measurement_assessment", _fake_assemble
        )
        client, fake = _client([])
        resp = client.post("/v1/me/assessments/capture")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["written"] is True
        assert body["reason"] == "captured"
        assert body["measurement_sufficient"] is True
        assert body["assessment"] is not None
        assert body["assessment"]["user_id"] == str(_UID)
        # ASM-07: 예측 5필드는 학생 대면 응답에 **키 자체가 없다**(구조적 배제).
        #
        # 이 단언은 원래 `body["assessment"][field] is None` 이었다 — 값이 null 임을
        # 확인하면서 *키의 존재*를 함께 동결하고 있었고, 그게 2026-08-08에 "노출 대기"
        # 상태(배관 완성·값만 빈 상태)를 드러낸 증거였다. 봉인 후 이 자리는 KeyError로
        # red 전환되는 것을 실측한 뒤 아래 형태로 갱신했다(ASM-07 acceptance ③).
        assert set(body["assessment"]) & STUDENT_HIDDEN_PREDICTION_FIELDS == set()
        # 실제로 Assessment ORM 행 1건 add + commit 1회(실 적재 발생).
        assert fake.commits == 1
        # EOS-103: 이 분기가 진단 완료 경계이므로 **같은 트랜잭션**에서 두 행이 적재된다 —
        # Assessment(진단 결과) + LearnerStateRecord(학습자 상태 자동 생성). 개수만 세지
        # 않고 타입으로 대조한다: 개수 단언은 한쪽이 다른 쪽으로 바뀌어도 통과한다.
        assert [type(row).__name__ for row in fake.added] == [
            "Assessment",
            "LearnerStateRecord",
        ], f"적재 구성이 바뀌었다: {[type(r).__name__ for r in fake.added]}"
        provisioned = fake.added[1]
        assert provisioned.learner_id == _UID
        assert provisioned.provisioned_by == "diagnosis_capture"
        assert isinstance(fake.added[0], Assessment)
        # 적재된 *내부* 정본에는 5필드가 그대로 있고 값은 None이다 — 봉인은 노출 축이지
        # 영속 축이 아니다(필드 폐기는 ASM-02에서 (d) 미채택).
        for field in STUDENT_HIDDEN_PREDICTION_FIELDS:
            assert getattr(fake.added[0], field) is None

    def test_idempotent_within_same_window_no_double_write(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """동일 학생·동일 창(오늘)에 이미 캡처된 행이 있으면 재조립·재적재하지 않는다
        (더블클릭·재시도 등 동일 요청 반복 시 이중 계상 방지)."""

        async def _fake_state(session: Any, user_id: Any) -> _AttemptHistoryState:
            return _AttemptHistoryState(
                attempted_ids=set(), theta=0.5, standard_error=0.2, measurement_sufficient=True
            )

        existing_row = Assessment.from_schema(
            AssessmentSchema(user_id=_UID, assessment_type=AssessmentType.단원진단)
        )

        async def _existing(session: Any, user_id: Any, now: Any) -> Assessment:
            return existing_row

        async def _boom_assemble(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("이미 캡처된 창이면 재조립하면 안 된다(이중 계상 방지)")

        monkeypatch.setattr("whymath_backend.api.me._load_attempt_history_state", _fake_state)
        monkeypatch.setattr("whymath_backend.api.me._find_existing_capture", _existing)
        monkeypatch.setattr(
            "whymath_backend.api.me._assemble_measurement_assessment", _boom_assemble
        )
        client, fake = _client([])
        resp = client.post("/v1/me/assessments/capture")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["written"] is False
        assert body["reason"] == "already_captured_window"
        assert body["assessment"] is not None
        assert body["assessment"]["assessment_id"] == str(existing_row.assessment_id)
        # 재적재 없음 — 커밋 0·add 0(이중 계상 방지가 실제로 동작함을 확인).
        assert fake.commits == 0
        assert fake.added == []


# ──────────────────────────────────────────────────────────────────────────
# EOS-10 — GET /v1/me/learner-state (LearnerState 단일 조회 표면)
# ──────────────────────────────────────────────────────────────────────────
class _LearnerStateSession(_QueueSession):
    """`_QueueSession` + `get()` — `get_state()`는 `session.get(UserProfile, ...)`도 부른다.

    execute 큐 순서(조립기 계약): ①BKT 숙달 ②개념별 IRT ③전과목 θ ④활성 오개념 ⑤스킬 숙달.
    """

    def __init__(self, results: list[_AQResult], profile: Any = None) -> None:
        super().__init__(results)
        self._profile = profile

    async def get(self, _model: Any, _pk: Any) -> Any:
        return self._profile


def _learner_state_client(
    *,
    mastery_rows: list[Any] | None = None,
    irt_rows: list[Any] | None = None,
    theta_rows: list[Any] | None = None,
    misconception_rows: list[Any] | None = None,
    skill_rows: list[Any] | None = None,
    profile: Any = None,
) -> TestClient:
    session = _LearnerStateSession(
        [
            _AQResult(mastery_rows or []),
            _AQResult(irt_rows or []),
            _AQResult(theta_rows or []),
            _AQResult(misconception_rows or []),
            _AQResult(skill_rows or []),
        ],
        profile=profile,
    )
    return _attempts_client(cast(_QueueSession, session))


class TestLearnerStateSurface:
    """EOS-10: 조각 3개(`/mastery/current`·`/ability`·`/diagnosis/summary`)의 **합성 표면**."""

    def test_requires_auth(self) -> None:
        app = create_app()

        async def _sess() -> AsyncIterator[_LearnerStateSession]:
            yield _LearnerStateSession([_AQResult([]) for _ in range(5)])

        app.dependency_overrides[get_session] = _sess
        assert TestClient(app).get("/v1/me/learner-state").status_code == 401

    def test_returns_all_fields_for_new_student(self) -> None:
        """진단·오개념·프로필이 전부 없는 신규 학생도 200 — 빈 값이지 오류가 아니다."""
        resp = _learner_state_client().get("/v1/me/learner-state")
        assert resp.status_code == 200
        body = resp.json()
        assert body["student_id"] == str(_UID)
        assert body["mastery"] == {}
        assert body["skill_mastery"] == {}
        assert body["curriculum_id"] is None
        assert body["current_objective_id"] is None

    def test_assembles_concept_and_skill_axes_in_one_call(self) -> None:
        """한 호출로 개념 축(BKT)과 행동 축(스킬)이 함께 온다 — 조각 조회의 이유가 사라진다."""
        cid = uuid.uuid4()
        resp = _learner_state_client(
            mastery_rows=[(cid, "C-1", "개념", 0.85)],
            skill_rows=[("skill.factorize", 0.72)],
            theta_rows=[1.2],
        ).get("/v1/me/learner-state")
        assert resp.status_code == 200
        body = resp.json()
        assert body["mastery"] == {"C-1": 0.85}
        assert body["skill_mastery"] == {"skill.factorize": 0.72}
        assert body["recent_successes"] == ["C-1"]  # 0.85 >= 숙달 임계 0.8

    def test_origins_exposes_no_producer_distinctly_from_no_data(self) -> None:
        """응답이 '이력이 없다'와 '생산자가 없다'를 구별해 말하는가 — 이 표면의 핵심 계약."""
        body = (
            _learner_state_client(
                skill_rows=[("skill.factorize", 0.5)],
            )
            .get("/v1/me/learner-state")
            .json()
        )
        origins = body["origins"]
        assert origins["skill_mastery"]["status"] == "measured"
        assert origins["mastery"]["status"] == "no_data"  # 생산자는 있으나 이력 없음
        assert origins["curriculum_id"]["status"] == "no_producer"
        assert origins["current_objective_id"]["status"] == "no_producer"

    def test_origins_reports_estimator_for_swap_visibility(self) -> None:
        """추정기가 응답에 실린다 — BKT→DKT 교체가 소비처에 보이게 하는 축(계획서 §2)."""
        body = (
            _learner_state_client(
                skill_rows=[("skill.factorize", 0.5)],
                theta_rows=[0.3],
            )
            .get("/v1/me/learner-state")
            .json()
        )
        assert body["origins"]["skill_mastery"]["estimator"] == "bkt.v1"
        assert body["origins"]["general_ability"]["estimator"] == "irt.2pl"
