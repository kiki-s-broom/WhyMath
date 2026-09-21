"""user 라우터 단위테스트 — /v1/users/me 조회·수정(hermetic).

엔드포인트 로직(PII 제외·자가수정 화이트리스트·If-Match·ETag)은 `get_consented_user`를
오버라이드해 고정 사용자로 검증한다(인증 자체는 test_auth.py가 검증). 무토큰 401은 실제
의존성으로 한 건 확인(라우트 결선).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from whymath_backend.api._auth import get_consented_user
from whymath_backend.app import create_app
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.l4.pedagogy.runtime_selector import grade_to_band
from whymath_backend.schema.enums import Persona
from whymath_backend.schema.user import UserProfile as UserProfileSchema


def _user(**over: Any) -> UserProfile:
    data: dict[str, Any] = {
        "persona_primary": Persona.A_일반고고3,
        "nickname": "기존닉",
        "email_hash": "HASHED_EMAIL_VALUE",
    }
    data.update(over)
    return UserProfile.from_schema(UserProfileSchema(**data))


class FakeSession:
    """PATCH 경로용 — merge/commit/rollback만 모사."""

    def __init__(self, commit_error: Exception | None = None) -> None:
        self._commit_error = commit_error
        self.committed = False
        self.rolled_back = False

    async def merge(self, obj: Any) -> Any:
        return obj

    async def commit(self) -> None:
        if self._commit_error is not None:
            raise self._commit_error
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


def _client(user: UserProfile, fake: FakeSession | None = None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_consented_user] = lambda: user
    if fake is not None:

        async def _sess() -> AsyncIterator[FakeSession]:
            yield fake

        app.dependency_overrides[get_session] = _sess
    return TestClient(app)


def _rejected_by_schema(resp: Any) -> bool:
    """422의 거부 *사유*가 스키마 재검증 실패인지 판별(화이트리스트 거부와 구별).

    `patch_me`는 두 가지 이유로 422를 낸다 — ⑴ 화이트리스트 밖 필드 → `detail`이 문자열
    ⑵ 병합 결과 스키마 위반 → `detail`이 `{"message", "errors"}` dict. 상태 코드가 같으므로
    사유를 가르지 않으면 "필드가 열렸는지"를 검사할 수 없다.
    """
    detail = resp.json().get("detail")
    return isinstance(detail, dict) and "errors" in detail


def test_me_without_token_returns_401() -> None:
    """토큰 없이 /me → 401(실제 인증 의존성 결선 확인).

    get_session은 가짜로 오버라이드한다 — 무토큰 401은 세션을 쓰기 전에 발생하므로 실 엔진
    생성(전역 lazy 캐시 오염)을 피한다(다른 테스트의 import-격리 가정 보호).
    """
    app = create_app()

    async def _sess() -> AsyncIterator[FakeSession]:
        yield FakeSession()

    app.dependency_overrides[get_session] = _sess
    resp = TestClient(app).get("/v1/users/me")
    assert resp.status_code == 401
    assert "WWW-Authenticate" in resp.headers


class TestReadMe:
    def test_returns_profile_without_pii(self) -> None:
        user = _user()
        resp = _client(user).get("/v1/users/me")
        assert resp.status_code == 200
        body = resp.json()
        assert body["nickname"] == "기존닉"
        assert "email_hash" not in body  # PII 제외
        assert "parent_email_hash" not in body
        assert resp.headers.get("ETag", "").startswith('"')


class TestPatchMe:
    def test_updates_whitelisted_field(self) -> None:
        user = _user()
        fake = FakeSession()
        resp = _client(user, fake).patch("/v1/users/me", json={"nickname": "새닉"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["nickname"] == "새닉"
        assert fake.committed is True

    def test_rejects_consent_field_422(self) -> None:
        """parent_consent_at 자가수정 시도 → 422(동의 게이트 우회 차단)."""
        user = _user()
        resp = _client(user, FakeSession()).patch(
            "/v1/users/me", json={"parent_consent_at": "2020-01-01T00:00:00Z"}
        )
        assert resp.status_code == 422

    def test_rejects_identity_field_422(self) -> None:
        """email_hash·is_minor 등 신원/동의 필드 자가수정 → 422."""
        user = _user()
        client = _client(user, FakeSession())
        assert client.patch("/v1/users/me", json={"email_hash": "x"}).status_code == 422
        assert client.patch("/v1/users/me", json={"is_minor": False}).status_code == 422

    def test_birth_year_change_recomputes_is_minor_true(self) -> None:
        """birth_year를 미성년 값으로 PATCH → is_minor가 서버에서 True로 재파생(클라 미요청)."""
        minor_birth_year = datetime.now(tz=timezone.utc).year - 8  # 연나이 8 ≤ 14
        user = _user(is_minor=False)  # 기존값은 False지만 birth_year로 덮어써져야 함
        fake = FakeSession()
        resp = _client(user, fake).patch("/v1/users/me", json={"birth_year": minor_birth_year})
        assert resp.status_code == 200, resp.text
        assert resp.json()["birth_year"] == minor_birth_year
        assert resp.json()["is_minor"] is True
        assert fake.committed is True

    def test_birth_year_change_recomputes_is_minor_false(self) -> None:
        """birth_year를 성인 값으로 PATCH → is_minor가 서버에서 False로 재파생."""
        adult_birth_year = datetime.now(tz=timezone.utc).year - 30  # 연나이 30 > 14
        user = _user(is_minor=True)  # 기존 True도 birth_year 기준으로 재계산되어야 함
        resp = _client(user, FakeSession()).patch(
            "/v1/users/me", json={"birth_year": adult_birth_year}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["is_minor"] is False

    def test_client_supplied_is_minor_cannot_bypass_gate(self) -> None:
        """우회 차단: 미성년 birth_year + is_minor=false 동시 PATCH → 422(is_minor 자가수정 불가).

        is_minor는 화이트리스트에 없어 *직접 지정 자체*가 422다(서버 파생값에 도달하기도 전에
        거부). 즉 미성년이 is_minor=false를 끼워 넣어 게이트를 우회할 수 없다.
        """
        minor_birth_year = datetime.now(tz=timezone.utc).year - 8
        user = _user()
        resp = _client(user, FakeSession()).patch(
            "/v1/users/me",
            json={"birth_year": minor_birth_year, "is_minor": False},
        )
        assert resp.status_code == 422

    def test_unrelated_patch_self_heals_stale_is_minor(self) -> None:
        """birth_year를 안 건드는 PATCH라도 is_minor는 현재 birth_year에서 재파생(자가 치유).

        기존 레코드가 미성년 birth_year인데 is_minor가 (잘못) False로 남아 있으면, 닉네임만
        바꾸는 무관한 PATCH에도 is_minor가 True로 교정된다(is_minor=birth_year의 순수 투영).
        """
        minor_birth_year = datetime.now(tz=timezone.utc).year - 8
        user = _user(birth_year=minor_birth_year, is_minor=False)  # stale False
        resp = _client(user, FakeSession()).patch("/v1/users/me", json={"nickname": "새닉"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["nickname"] == "새닉"
        assert resp.json()["is_minor"] is True  # 서버가 birth_year 기준으로 교정

    def test_stale_if_match_returns_412(self) -> None:
        user = _user()
        resp = _client(user, FakeSession()).patch(
            "/v1/users/me",
            json={"nickname": "새닉"},
            headers={"If-Match": '"deadbeefdeadbeef"'},
        )
        assert resp.status_code == 412

    def test_matching_if_match_succeeds(self) -> None:
        user = _user()
        fake = FakeSession()
        client = _client(user, fake)
        etag = client.get("/v1/users/me").headers["ETag"]
        resp = client.patch("/v1/users/me", json={"nickname": "새닉"}, headers={"If-Match": etag})
        assert resp.status_code == 200

    def test_invalid_value_for_whitelisted_field_422(self) -> None:
        """화이트리스트 필드라도 잘못된 enum 값이면 병합 재검증 422."""
        user = _user()
        resp = _client(user, FakeSession()).patch(
            "/v1/users/me", json={"primary_device": "없는기기"}
        )
        assert resp.status_code == 422

    def test_integrity_conflict_returns_409(self) -> None:
        """commit 단계 IntegrityError → 롤백 후 409."""
        user = _user()
        err = IntegrityError("UPDATE", {}, Exception("duplicate"))
        fake = FakeSession(commit_error=err)
        resp = _client(user, fake).patch("/v1/users/me", json={"nickname": "새닉"})
        assert resp.status_code == 409
        assert fake.rolled_back is True


class TestPatchMeSchoolIdentity:
    """학적 자가신고(`grade`·`school_type`) 자가수정 — EOS-82(리뷰 G1).

    이 클래스가 동결하는 것은 "화이트리스트에 이름이 있다"가 아니라 **넣은 값이 소비자에
    도달한다**는 것이다(정본화 ≠ 집행). 착수 전 상태: 소비자 4곳이 존재하는데 HTTP writer가
    0곳이라 전 학생이 영구 `None`이었고, 그 결과 교수법 학년 밴드 필터·코치 학년 개인화·
    성취기준 커버리지가 **에러 없이 조용히** 스킵/null 됐다.
    """

    def test_grade_and_school_type_are_self_editable(self) -> None:
        """학년·학교유형 PATCH → 200으로 반영(착수 전에는 422로 거부되던 경로)."""
        user = _user()
        fake = FakeSession()
        resp = _client(user, fake).patch(
            "/v1/users/me", json={"grade": 12, "school_type": "자사고_전국"}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["grade"] == 12
        assert body["school_type"] == "자사고_전국"  # use_enum_values — 한글 값 보존
        assert fake.committed is True

    def test_patched_grade_reaches_grade_band_consumer(self) -> None:
        """관통(집행 지점): PATCH가 영속시킨 값을 실제 소비자 변환이 읽는다 — 양방향 변별력.

        `grade_to_band`는 `api/study.py::_build_signals`가 교수법 카탈로그 후보를 좁힐 때 쓰는
        바로 그 순수 변환이다. 이 테스트는 **PATCH 전(None → 밴드 None = 필터 축 조용히 스킵)**과
        **PATCH 후(12 → "고등")**를 함께 확인한다. 한쪽만 보면 "모든 입력에서 같은 값을 내는"
        검사와 구별되지 않는다(CLAUDE.md 변별력 없는 검증 스텝 금지).
        """
        user = _user()
        assert user.grade is None
        assert grade_to_band(user.grade) is None  # 결함 상태 — 필터 축이 무효화된다

        merged: dict[str, Any] = {}

        class CapturingSession(FakeSession):
            async def merge(self, obj: Any) -> Any:
                merged["orm"] = obj
                return obj

        resp = _client(user, CapturingSession()).patch("/v1/users/me", json={"grade": 12})
        assert resp.status_code == 200, resp.text
        # 영속 대상 ORM이 값을 싣고, 소비자 변환이 그 값을 읽어 밴드를 낸다.
        assert merged["orm"].grade == 12
        assert grade_to_band(merged["orm"].grade) == "고등"

    def test_grade_below_range_rejected_by_schema_422(self) -> None:
        """학년 9(중3) → 422, 그리고 **거부 사유가 스키마 위반**임을 확인(ge=10 계약).

        상태 코드만 보면 변별력이 없다 — 화이트리스트에서 `grade`를 빼도 똑같이 422가 나오기
        때문이다(사유는 "자가수정 불가"). 그러면 이 검사는 정상/결함 양쪽에서 같은 값을 내는
        위장이 된다(CLAUDE.md 변별력 없는 검증 스텝 금지). 그래서 `detail`의 **형태**로 사유를
        가른다: 화이트리스트 거부는 문자열, 스키마 재검증 실패는 `errors`를 가진 dict다.
        """
        resp = _client(_user(), FakeSession()).patch("/v1/users/me", json={"grade": 9})
        assert resp.status_code == 422
        assert _rejected_by_schema(resp), resp.text

    def test_grade_above_range_rejected_by_schema_422(self) -> None:
        """학년 15(N수3) → 422 + 스키마 사유. le=14 — 화이트리스트가 값 검증을 무력화하지 않는다."""
        resp = _client(_user(), FakeSession()).patch("/v1/users/me", json={"grade": 15})
        assert resp.status_code == 422
        assert _rejected_by_schema(resp), resp.text

    def test_unknown_school_type_rejected_by_schema_422(self) -> None:
        """enum 12종에 없는 학교유형 → 422 + 스키마 사유(자유 문자열 유입 차단)."""
        resp = _client(_user(), FakeSession()).patch(
            "/v1/users/me", json={"school_type": "국제학교"}
        )
        assert resp.status_code == 422
        assert _rejected_by_schema(resp), resp.text

    def test_school_id_and_region_still_rejected_422(self) -> None:
        """범위 밖 필드는 여전히 거부 — `school_*` 전체가 열린 게 아니다.

        `school_id`·`school_region`은 미소비 컬럼 처분 게이트(`G-prod-dead-column-check`)의
        *제거* 후보라 방향이 반대다. 소비자가 없는 필드의 수집을 열면 목적 없는 PII 수집이 된다.
        """
        client = _client(_user(), FakeSession())
        for field, value in (("school_id", str(uuid4())), ("school_region", "대치")):
            resp = client.patch("/v1/users/me", json={field: value})
            assert resp.status_code == 422, resp.text
            # 사유가 *화이트리스트 거부*여야 한다 — 스키마 위반으로 우연히 막히는 것과 다르다.
            assert not _rejected_by_schema(resp), resp.text
            assert field in resp.json()["detail"]

    def test_grade_patch_does_not_open_minor_gate_bypass(self) -> None:
        """게이트 회귀 방지: 학년을 성인스럽게(N수2) 보내도 `is_minor`는 birth_year에서 파생된다.

        `grade`는 미성년 판정의 입력이 아니다 — 게이트는 `birth_year` → `derive_is_minor` 단일
        경로다. 미성년이 `grade=14`(N수2)로 성인처럼 보이게 해도 게이트는 닫힌 채 유지된다.
        """
        minor_birth_year = datetime.now(tz=timezone.utc).year - 8
        user = _user(birth_year=minor_birth_year, is_minor=True)
        resp = _client(user, FakeSession()).patch("/v1/users/me", json={"grade": 14})
        assert resp.status_code == 200, resp.text
        assert resp.json()["grade"] == 14
        assert resp.json()["is_minor"] is True  # 서버 파생 유지 — 우회 불가

    def test_school_identity_patch_keeps_pii_excluded(self) -> None:
        """학적 필드를 수정해도 응답의 PII 제외 계약은 그대로다."""
        resp = _client(_user(), FakeSession()).patch(
            "/v1/users/me", json={"grade": 11, "school_type": "일반고"}
        )
        assert resp.status_code == 200, resp.text
        assert "email_hash" not in resp.json()
        assert "parent_email_hash" not in resp.json()
