"""데이터 열람·이동권 엔드포인트(`GET /v1/me/export`) — hermetic(FakeSession·인증 오버라이드).

`export_my_data`의 *엔드포인트 결선*만 검증한다: 인증(401)·정상 경로(200 + data·not_included +
user_id 스코핑)·외부 store 상세는 응답 미노출·ops 로그 가시화·SEC-09 반출 감사 1행 적재(동일
트랜잭션). ★실제 ORM 직렬화·실 PG 조회는 `privacy/test_export.py`·통합테스트가 검증한다(중복 0).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from _external_store_evidence import assert_manifest_stores_are_deployed
from fastapi.testclient import TestClient

from whymath_backend.api._auth import get_consented_user
from whymath_backend.app import create_app
from whymath_backend.db.models.audit import PrivacyAudit
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.schema.enums import Persona
from whymath_backend.schema.user import UserProfile as UserProfileSchema

_UID = uuid.uuid4()


def _user() -> UserProfile:
    return UserProfile.from_schema(
        UserProfileSchema(user_id=_UID, persona_primary=Persona.A_일반고고3)
    )


class _StubSchema:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def model_dump(self, *, mode: str) -> dict[str, Any]:
        return dict(self._payload)


class _StubRow:
    def __init__(
        self,
        payload: dict[str, Any],
        *,
        content: str | None = None,
        content_encrypted: bytes | None = None,
        content_nonce: bytes | None = None,
        image_uri: str | None = None,
        image_uri_encrypted: bytes | None = None,
        image_uri_nonce: bytes | None = None,
        image_analysis: dict[str, Any] | None = None,
        image_analysis_encrypted: bytes | None = None,
        image_analysis_nonce: bytes | None = None,
    ) -> None:
        self._payload = payload
        # 감사상환 #2: export가 dialogue_turns 행에서 봉투 암호화 컬럼을 읽어 노출 직전 복호한다.
        # SEC-01: 이미지 두 축(image_uri·image_analysis)도 같은 시점에 복호되므로 함께 흉내낸다.
        self.content = content
        self.content_encrypted = content_encrypted
        self.content_nonce = content_nonce
        self.image_uri = image_uri
        self.image_uri_encrypted = image_uri_encrypted
        self.image_uri_nonce = image_uri_nonce
        self.image_analysis = image_analysis
        self.image_analysis_encrypted = image_analysis_encrypted
        self.image_analysis_nonce = image_analysis_nonce

    def to_schema(self) -> _StubSchema:
        return _StubSchema(self._payload)


class _FakeScalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)

    def first(self) -> Any:
        return self._rows[0] if self._rows else None


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._rows)


class _FakeSession:
    """execute(select)별 scalars 큐(15종 + 대화 턴 조인 + profile = 17)를 순서대로 반환.

    SEC-09: `export_my_data`가 반출 후 `privacy_audit` 감사 1행을 같은 트랜잭션으로 적재하므로
    `add`/`commit`도 흉내낸다(`test_parental_consent.FakeSession` 동형) — `added`로 무엇이
    적재됐는지 검사할 수 있다.
    """

    def __init__(self, result_rows: list[list[Any]]) -> None:
        self._queue = list(result_rows)
        self.added: list[Any] = []
        self.committed = False

    async def execute(self, stmt: Any) -> _FakeResult:
        return _FakeResult(self._queue.pop(0) if self._queue else [])

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed = True


def _client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_consented_user] = _user

    async def _sess() -> AsyncIterator[_FakeSession]:
        # _EXPORT_PLAN 19종 카테고리 + 대화 턴 조인(19) + profile(20) = 21 execute.
        # learning_sessions(0)·parental_consents(6)·misconception_evidence(11)·
        # user_behavior_metrics(13)·dialogues(14)·attempt_events(15)·answer_submissions(16·EOS-32·
        # 빈)·hint_usages(17·EOS-45·빈)·student_solution_steps(18·EOS-46·빈)·dialogue_turns(19)에
        # 행, 나머지 빈, profile 1행.
        yield _FakeSession(
            [
                [_StubRow({"sid": "s1"})],
                [],
                [],
                [],
                [],  # skill_mastery_history(Phase 2b-2·빈 구간)
                [],
                [_StubRow({"cid": "c1"})],
                [],
                [],
                [],
                [],
                [_StubRow({"link_id": 7})],
                [],
                [_StubRow({"metric": "churn_risk"})],
                [_StubRow({"resolution": "자기풀이"})],
                [_StubRow({"event": "step_submit"})],
                [],  # answer_submissions(EOS-32·빈 구간)
                [],  # hint_usages(EOS-45·빈 구간)
                [],  # student_solution_steps(EOS-46·빈 구간)
                [_StubRow({"content": "x=2?"}, content="x=2?")],
                [_StubRow({"uid": str(_UID)})],
            ]
        )

    app.dependency_overrides[get_session] = _sess
    return TestClient(app)


def _no_auth_client() -> TestClient:
    app = create_app()

    async def _sess() -> AsyncIterator[_FakeSession]:
        yield _FakeSession([])

    app.dependency_overrides[get_session] = _sess  # 무토큰 401은 세션 사용 전 발생
    return TestClient(app)


class TestExportMyData:
    def test_returns_user_data_200(self) -> None:
        """200 — user_id 스코핑·data 카테고리·user_profile·not_included 고지."""
        resp = _client().get("/v1/me/export")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["user_id"] == str(_UID)
        assert body["data"]["learning_sessions"] == [{"sid": "s1"}]
        assert body["data"]["assessments"] == []
        assert body["data"]["parental_consents"] == [{"cid": "c1"}]  # 증분 2 신규 카테고리
        assert body["data"]["misconception_hypotheses"] == []  # 슬 신규 카테고리(빈)
        assert body["data"]["misconception_evidence"] == [
            {"link_id": 7}
        ]  # 증분 3(student_id 스코핑)
        assert body["data"]["daily_learning_metrics"] == []  # 증분 4 신규(빈)
        assert body["data"]["user_behavior_metrics"] == [{"metric": "churn_risk"}]  # 증분 4 신규
        assert body["data"]["dialogues"] == [{"resolution": "자기풀이"}]  # 증분 5 신규(세션 메타)
        assert body["data"]["attempt_events"] == [{"event": "step_submit"}]  # 증분 7 신규
        assert body["data"]["answer_submissions"] == []  # EOS-32 신규(답 제출 시퀀스·빈)
        assert body["data"]["hint_usages"] == []  # EOS-45 신규(힌트 사용 이력·빈)
        assert body["data"]["student_solution_steps"] == []  # EOS-46 신규(풀이 step·빈)
        # 증분 6 신규(턴 본문) + SEC-01: 이미지 두 축도 복호 표면에 올라 응답에 실린다.
        assert body["data"]["dialogue_turns"] == [
            {"content": "x=2?", "image_uri": None, "image_analysis": None}
        ]
        assert body["user_profile"] == {"uid": str(_UID)}
        assert len(body["not_included"]) >= 1  # 부분 export 정직 고지
        assert "exported_at" in body

    def test_external_store_not_in_response(self) -> None:
        """외부 store 상세(인프라 store명·locator)는 응답에 미노출(정보 누출 0).

        SEC-32: 검사 대상을 매니페스트에서 가져온다 — 종전엔 `"clickhouse"` 한 단어만 봤고,
        그 store는 애초에 존재하지도 않아 *어떤 구현에서도 통과하는* 검사였다.
        """
        from whymath_backend.privacy.export import external_export_pending

        stores = [t.store for t in external_export_pending(_UID)]
        assert_manifest_stores_are_deployed(stores, source="GET /v1/me/export 응답")
        body_text = _client().get("/v1/me/export").text
        leaked = [store for store in stores if store in body_text.lower()]
        assert not leaked, f"응답에 인프라 store명이 샜다: {leaked}"
        assert "locator" not in body_text

    def test_no_token_401(self) -> None:
        """무토큰 → 401(인증 필수·본인 데이터만)."""
        resp = _no_auth_client().get("/v1/me/export")
        assert resp.status_code == 401

    def test_export_writes_privacy_audit_row_same_transaction(self) -> None:
        """SEC-09: 200 응답 + `privacy_audit` 감사 1행 적재(반출 내용은 감사에 없음) + commit."""
        app = create_app()
        app.dependency_overrides[get_consented_user] = _user
        fake = _FakeSession(
            [
                [_StubRow({"sid": "s1"})],
                [],
                [],
                [],
                [],
                [],
                [_StubRow({"cid": "c1"})],
                [],
                [],
                [],
                [],
                [_StubRow({"link_id": 7})],
                [],
                [_StubRow({"metric": "churn_risk"})],
                [_StubRow({"resolution": "자기풀이"})],
                [_StubRow({"event": "step_submit"})],
                [],  # answer_submissions(EOS-32·빈 구간)
                [],  # hint_usages(EOS-45·빈 구간)
                [],  # student_solution_steps(EOS-46·빈 구간)
                [_StubRow({"content": "x=2?"}, content="x=2?")],
                [_StubRow({"uid": str(_UID)})],
            ]
        )

        async def _sess() -> AsyncIterator[_FakeSession]:
            yield fake

        app.dependency_overrides[get_session] = _sess
        resp = TestClient(app).get("/v1/me/export")
        assert resp.status_code == 200, resp.text
        audits = [o for o in fake.added if isinstance(o, PrivacyAudit)]
        assert len(audits) == 1
        assert audits[0].user_id == _UID
        assert audits[0].event_kind == "export_data"
        assert fake.committed is True
        # 반출 *내용*은 감사 행에 없다(최소화 — event_kind/user_id/ip_hash/target_user_id/
        # consent_scope 외 필드 부재 자체가 스키마 레벨 보증이나, 응답 데이터 문자열이 감사
        # 객체 attr로 새지 않았는지도 방어적으로 확인).
        assert not hasattr(audits[0], "data")
        assert not hasattr(audits[0], "export_payload")

    def test_pending_external_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """외부 store 별도 export 필요를 *ops 로그*로 가시화(store명·user_id).

        SEC-32: 매니페스트가 선언한 store가 *전부* 로그에 있어야 한다(한 곳이라도 빠지면
        ops는 그 store를 영영 모른다). 기대 목록은 매니페스트에서 가져온다.
        """
        from whymath_backend.privacy.export import external_export_pending

        with caplog.at_level(logging.INFO, logger="whymath.api.me"):
            _client().get("/v1/me/export")
        msgs = [r.getMessage() for r in caplog.records]
        assert any("열람·이동권 export" in m and str(_UID) in m for m in msgs)
        logged = "\n".join(msgs)
        stores = [t.store for t in external_export_pending(_UID)]
        assert_manifest_stores_are_deployed(stores, source="GET /v1/me/export ops 로그")
        missing = [store for store in stores if store not in logged]
        assert not missing, f"ops 로그에 안 찍힌 외부 store: {missing}"
