"""학생 답안/풀이 3테이블 봉투 암호화 프리미티브 단위테스트 — AES-256-GCM (SEC-31, hermetic).

`test_dialogue_image_encryption.py`(SEC-01) 선례 미러 — 여기서는 신규 키 소스
(`student_work_encryption_key`)와 `expression` 전용(NOT NULL) 헬퍼를 검증한다.

  ① **round-trip** — 암호화 후 복호하면 원본이 그대로 돌아온다.
  ② **평문 컬럼이 비워진다** — 암호화 행에 원문이 남지 않는다.
  ③ **fail-closed** — 프로덕션 추정 환경에서 키가 없으면 조용한 평문 폴백 대신 RuntimeError.
  ④ **키 유실 시 시끄러운 실패** — 암호화 행인데 cipher가 없으면 빈 값이 아니라 예외.
  ⑤ **expression 전용 계약** — 항상 `str` 반환·평문/암호문 둘 다 없으면 RuntimeError(device
     secret 계약과 동형 — content와 달리 "값 없음"이 정상 상태가 아니다).
  ⑥ **키 소스 분리** — dialogue·evidence·device secret 키와 별개(한 키만 설정해도 다른 축은
     영향받지 않는다).
"""

from __future__ import annotations

import base64
import os

import pytest
from cryptography.exceptions import InvalidTag
from pydantic import SecretStr

from whymath_backend.api._crypto import (
    MultiKeyCipher,
    SecretCipher,
    build_student_work_cipher,
    encrypt_dialogue_content,
    encrypt_student_solution_step_expression,
    require_student_work_cipher,
    resolve_dialogue_content,
    resolve_student_solution_step_expression,
)
from whymath_backend.config import Settings

_SECRET = "integration-jwt-secret-0123456789abcdef"


def _cipher() -> MultiKeyCipher:
    return MultiKeyCipher(SecretCipher(os.urandom(32)))


def _settings(enc_key_b64: str = "", fallback_keys_b64: str = "") -> Settings:
    return Settings(
        jwt_secret_key=SecretStr(_SECRET),
        student_work_encryption_key=SecretStr(enc_key_b64),
        student_work_decryption_fallback_keys=SecretStr(fallback_keys_b64),
    )


class _FakeSecret:
    """`SecretStr` 흉내 — `get_secret_value()`만 있으면 빌더가 동작한다."""

    def __init__(self, value: str) -> None:
        self._value = value

    def get_secret_value(self) -> str:
        return self._value


class _FakeSettings:
    """`require_student_work_cipher`가 읽는 필드만 가진 최소 설정."""

    def __init__(self, *, key: str = "", kakao: bool = False, naver: bool = False) -> None:
        self.student_work_encryption_key = _FakeSecret(key)
        self.student_work_decryption_fallback_keys = _FakeSecret("")
        self.kakao_configured = kakao
        self.naver_configured = naver


class TestBuildStudentWorkCipher:
    def test_none_when_key_unset(self) -> None:
        assert build_student_work_cipher(_settings("")) is None

    def test_cipher_when_key_set(self) -> None:
        key_b64 = base64.b64encode(os.urandom(32)).decode()
        cipher = build_student_work_cipher(_settings(key_b64))
        assert cipher is not None
        ct, nonce = cipher.encrypt("답안 본문")
        assert cipher.decrypt(ct, nonce) == "답안 본문"

    def test_key_source_separated_from_dialogue(self) -> None:
        """대화 본문 키만 설정해도 student_work cipher는 None(키 소스 분리)."""
        dialogue_only = Settings(
            jwt_secret_key=SecretStr(_SECRET),
            dialogue_content_encryption_key=SecretStr(base64.b64encode(os.urandom(32)).decode()),
        )
        assert build_student_work_cipher(dialogue_only) is None


class TestNullableFieldsReuseDialogueContentHelpers(object):
    """student_answer·raw_response·latex 등 5개 nullable 필드는 `encrypt_dialogue_content`/
    `resolve_dialogue_content`(JSONB는 별도 파일에서 image_analysis 헬퍼로 커버)를 그대로
    재사용한다 — cipher만 student_work로 바꿔 호출."""

    def test_round_trip_with_student_work_cipher(self) -> None:
        cipher = _cipher()
        plain, encrypted, nonce = encrypt_dialogue_content(cipher, "학생 제출 답안")
        assert plain is None
        assert encrypted is not None and nonce is not None
        assert resolve_dialogue_content(cipher, plain, encrypted, nonce) == "학생 제출 답안"

    def test_none_value_produces_no_ciphertext(self) -> None:
        assert encrypt_dialogue_content(_cipher(), None) == (None, None, None)

    def test_plaintext_fallback_without_cipher(self) -> None:
        assert encrypt_dialogue_content(None, "raw") == ("raw", None, None)


class TestStudentSolutionStepExpression:
    """`expression`은 schema에서 필수 `str`(min_length=1) — NOT NULL 특수 취급."""

    def test_round_trip(self) -> None:
        cipher = _cipher()
        plain, encrypted, nonce = encrypt_student_solution_step_expression(cipher, "x^2 + 1")
        assert plain is None
        assert encrypted is not None and nonce is not None
        assert resolve_student_solution_step_expression(cipher, plain, encrypted, nonce) == (
            "x^2 + 1"
        )

    def test_plaintext_fallback_without_cipher_still_returns_str(self) -> None:
        """cipher 미설정이면 평문 폴백 — 그래도 항상 str(개발·CI 경로)."""
        plain, encrypted, nonce = encrypt_student_solution_step_expression(None, "2x")
        assert plain == "2x"
        assert encrypted is None and nonce is None
        assert resolve_student_solution_step_expression(None, plain, encrypted, nonce) == "2x"

    def test_tamper_raises_invalid_tag(self) -> None:
        cipher = _cipher()
        _, encrypted, nonce = encrypt_student_solution_step_expression(cipher, "3x+1")
        assert encrypted is not None and nonce is not None
        tampered = bytes([encrypted[0] ^ 0x01]) + encrypted[1:]
        with pytest.raises(InvalidTag):
            resolve_student_solution_step_expression(cipher, None, tampered, nonce)

    def test_encrypted_row_without_key_raises_loud(self) -> None:
        """키 유실 — 조용한 빈 문자열 대신 시끄러운 실패."""
        cipher = _cipher()
        _, encrypted, nonce = encrypt_student_solution_step_expression(cipher, "x=1")
        with pytest.raises(RuntimeError):
            resolve_student_solution_step_expression(None, None, encrypted, nonce)

    def test_both_missing_is_data_integrity_error(self) -> None:
        """평문·암호문 둘 다 없으면 정상 상태가 아니다 — expression은 NOT NULL 원본 계약이라
        `resolve_dialogue_content`(None 정상 반환)와 달리 여기서는 RuntimeError."""
        with pytest.raises(RuntimeError):
            resolve_student_solution_step_expression(_cipher(), None, None, None)


class TestProductionFailClosed:
    def test_raises_when_production_like_and_key_missing(self) -> None:
        with pytest.raises(RuntimeError, match="프로덕션 추정 환경"):
            require_student_work_cipher(_FakeSettings(key="", kakao=True))

    def test_naver_alone_also_triggers(self) -> None:
        with pytest.raises(RuntimeError, match="프로덕션 추정 환경"):
            require_student_work_cipher(_FakeSettings(key="", naver=True))

    def test_development_without_key_still_falls_back(self) -> None:
        """**변별력** — 같은 키 부재라도 개발 환경이면 None(폴백 허용)으로 판정이 뒤집힌다."""
        assert require_student_work_cipher(_FakeSettings(key="")) is None

    def test_production_with_key_returns_cipher(self) -> None:
        key = base64.b64encode(os.urandom(32)).decode()
        cipher = require_student_work_cipher(_FakeSettings(key=key, kakao=True))
        assert cipher is not None
        ct, nonce = cipher.encrypt("hello")
        assert cipher.decrypt(ct, nonce) == "hello"
