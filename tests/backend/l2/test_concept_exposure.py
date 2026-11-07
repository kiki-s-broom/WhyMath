"""학생 개념 노출 기록 — 가명 ID와 기록 행 단위 테스트 (PED-17 A1, 실 DB 불필요).

검증 축(학생 정보 보호):
  ① 가명은 키드 해시(소문자 16진 64자)이고, 원본 user_id·이름이 어떤 형태로도 들어 있지 않다.
  ② 같은 학생은 같은 가명, 다른 학생·다른 키는 다른 가명 — "서로 다른 학생 수"를 셀 수 있다.
  ③ 세션 바인딩(SEC-24) 해시와 입력 도메인이 분리돼 있다.
  ④ 기록 행은 호출자가 명시한 `ai_label_shown`을 그대로 담는다(기본값 없음).

DB 수준 형식 강제(CHECK)·UPDATE 거부는 `tests/backend/db/test_concept_lifecycle_migration_integration.py`.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import pytest
from pydantic import SecretStr

from whymath_backend.config import Settings
from whymath_backend.db.models.concept_lifecycle_log import ConceptExposureEvent
from whymath_backend.l2.concept_exposure import record_concept_exposure, student_pseudonym
from whymath_backend.l2.pedagogy_evidence import session_user_binding

_USER_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
_USER_B = uuid.UUID("22222222-2222-2222-2222-222222222222")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _settings(secret: str = "test-secret-key-for-exposure-0123456789") -> Settings:
    return Settings(jwt_secret_key=SecretStr(secret))


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)


class TestStudentPseudonym:
    def test_is_lowercase_hex_64(self) -> None:
        assert _HEX64.match(student_pseudonym(_USER_A, settings=_settings()))

    def test_contains_no_raw_user_id_in_any_common_form(self) -> None:
        pseudo = student_pseudonym(_USER_A, settings=_settings())
        for form in (str(_USER_A), _USER_A.hex, str(_USER_A).replace("-", "").upper()):
            assert form not in pseudo

    def test_same_student_same_pseudonym_different_student_different(self) -> None:
        s = _settings()
        assert student_pseudonym(_USER_A, settings=s) == student_pseudonym(_USER_A, settings=s)
        assert student_pseudonym(_USER_A, settings=s) != student_pseudonym(_USER_B, settings=s)

    def test_depends_on_the_server_secret(self) -> None:
        # 비밀 없이는 user_id만으로 재계산할 수 없다 — 키가 바뀌면 가명도 바뀐다.
        assert student_pseudonym(
            _USER_A, settings=_settings("secret-one-0123456789-0123456789")
        ) != (student_pseudonym(_USER_A, settings=_settings("secret-two-0123456789-0123456789")))

    def test_domain_is_separated_from_session_binding(self) -> None:
        # 같은 키·같은 user_id라도 세션 바인딩 해시와 같으면 안 된다(교차 용도 위조 차단).
        s = _settings()
        assert student_pseudonym(_USER_A, settings=s) != session_user_binding(
            _USER_A, _USER_A, settings=s
        )

    def test_does_not_depend_on_study_session(self) -> None:
        # 같은 학생의 여러 학습 세션이 한 가명으로 묶여야 "개념을 본 서로 다른 학생 수"를 센다.
        # (입력에 session_id가 없다는 사실의 직접 증거: 시그니처가 user_id만 받는다.)
        import inspect

        assert list(inspect.signature(student_pseudonym).parameters) == ["user_id", "settings"]


class TestRecordConceptExposure:
    @pytest.mark.parametrize("label", [True, False])
    async def test_row_carries_the_explicit_label_fact(self, label: bool) -> None:
        session = _FakeSession()
        event = await record_concept_exposure(
            session,  # type: ignore[arg-type]
            concept_code="HIGH-A1-001",
            user_id=_USER_A,
            settings=_settings(),
            ai_label_shown=label,
        )
        assert session.added == [event]
        assert isinstance(event, ConceptExposureEvent)
        assert event.concept_code == "HIGH-A1-001"
        assert event.ai_label_shown is label
        assert _HEX64.match(event.student_pseudonym)
        assert str(_USER_A) not in event.student_pseudonym

    def test_ai_label_has_no_default(self) -> None:
        # 사실을 호출자가 명시해야 한다 — 기본값이 있으면 "모르면 True/False" 가정이 숨어든다.
        import inspect

        param = inspect.signature(record_concept_exposure).parameters["ai_label_shown"]
        assert param.default is inspect.Parameter.empty

    async def test_row_has_no_field_that_could_hold_a_name_or_raw_id(self) -> None:
        cols = {c.name for c in ConceptExposureEvent.__table__.columns}
        assert cols == {
            "exposure_id",
            "concept_code",
            "student_pseudonym",
            "exposed_at",
            "ai_label_shown",
        }
