"""디바이스 secret at-rest 봉투(envelope) 암호화 — AES-256-GCM (slice 72).

`PgDeviceStore`는 v1에서 `secret_plain`을 평문 저장한다 — verify가 `HMAC(secret, device_id)`
재계산에 *원본*을 써야 해서 KDF(one-way)로는 검증이 불가하기 때문(`_device_store.py` 모듈
docstring). 그 결과 DB dump·DBA 접근 시 모든 device secret이 노출되는 게 위협 모델이다.

봉투 암호화는 secret을 *마스터 키*(DB 밖·env/Settings)로 AES-GCM 암호화해 저장한다 → DB dump
*단독*으로는 복호 불가(마스터 키가 DB에 없으므로). verify는 복호 후 HMAC 재계산.

설계:
  - **AES-256-GCM**(AEAD): 기밀성 + *무결성*. ciphertext 변조 시 복호가 `InvalidTag`로 실패
    (조용한 비트플립 차단). 96-bit nonce를 매 암호화 새로 생성(GCM 권장·키 재사용 한계 내).
  - **키 = 32바이트**(AES-256). Settings `device_secret_encryption_key`(base64)에서 주입.
  - **봉투만 구현**: 진짜 KMS(키 회전·HSM·per-secret DEK)는 후속. 본 모듈은 단일 마스터 키
    봉투를 제공하고 키 *출처*만 추상화(`build_secret_cipher`).

이 슬라이스(72)는 *프리미티브*만 — `PgDeviceStore` 결선(컬럼·register 암호화·verify 복호화)은
후속 슬라이스. 보안 코드는 프리미티브를 격리해 먼저 철저히 검증한다.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any, Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_KEY_BYTES = 32  # AES-256
_NONCE_BYTES = 12  # 96-bit — GCM 표준 권장 nonce 길이


class SupportsEnvelope(Protocol):
    """봉투 암호화기 인터페이스 — `SecretCipher`(단일 키)·`MultiKeyCipher`(회전) 공통.

    PgDeviceStore·저장 헬퍼는 이 구조적 타입에 의존해 단일/다중 키 구현을 교체 가능.
    """

    def encrypt(self, plaintext: str) -> tuple[bytes, bytes]: ...

    def decrypt(self, ciphertext: bytes, nonce: bytes) -> str: ...


class SecretCipher:
    """AES-256-GCM 봉투 암호화기 — `encrypt`/`decrypt` (nonce는 매 암호화 새로 생성).

    키는 32바이트(AES-256). 같은 인스턴스를 재사용해도 매 `encrypt`가 새 nonce를 뽑으므로
    동일 평문도 매번 다른 ciphertext가 된다(결정론 노출 차단).
    """

    def __init__(self, key: bytes) -> None:
        if len(key) != _KEY_BYTES:
            raise ValueError(
                f"AES-256 마스터 키는 {_KEY_BYTES}바이트여야 합니다(받음: {len(key)}바이트). "
                "base64 디코딩 후 길이를 확인하세요."
            )
        self._aesgcm = AESGCM(key)

    def encrypt(self, plaintext: str) -> tuple[bytes, bytes]:
        """평문 → `(ciphertext, nonce)`. ciphertext는 GCM 인증 태그를 포함(변조 탐지)."""
        nonce = os.urandom(_NONCE_BYTES)
        ciphertext = self._aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        return ciphertext, nonce

    def decrypt(self, ciphertext: bytes, nonce: bytes) -> str:
        """`(ciphertext, nonce)` → 평문. 변조·잘못된 키/nonce면 `InvalidTag` raise(조용한 실패 X).

        GCM 인증 태그가 ciphertext에 포함돼 무결성 검증 — 비트플립·키 불일치를 예외로 노출한다.
        """
        plaintext = self._aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext.decode("utf-8")


class MultiKeyCipher:
    """키 회전 지원 봉투 암호화기 — *primary*로 암호화·*primary+fallbacks*로 복호.

    키 회전 무중단 핵심: 새 키(primary)를 도입해도 기존 키(fallbacks)로 암호화된 행이
    *lockout 없이* 복호된다. 회전 절차: ① 새 키 생성·primary로 승격·구 키를 fallback으로
    이동 ② 재시작(신규 등록은 새 키로 암호화·구 행은 fallback으로 복호) ③ (후속) 구 행을
    새 키로 재암호화해 fallback 제거. encrypt는 *항상 primary*만 사용한다.
    """

    def __init__(self, primary: SecretCipher, fallbacks: list[SecretCipher] | None = None) -> None:
        self._primary = primary
        self._fallbacks: list[SecretCipher] = list(fallbacks or [])

    def encrypt(self, plaintext: str) -> tuple[bytes, bytes]:
        """항상 primary 키로 암호화(신규/재암호화 모두 현재 키로 수렴)."""
        return self._primary.encrypt(plaintext)

    def decrypt(self, ciphertext: bytes, nonce: bytes) -> str:
        """primary → fallbacks 순으로 복호 시도. 모든 키 실패 시 `InvalidTag`(변조/미지원 키)."""
        for cipher in (self._primary, *self._fallbacks):
            try:
                return cipher.decrypt(ciphertext, nonce)
            except InvalidTag:
                continue
        raise InvalidTag("어떤 복호 키로도 복호 실패 — 변조이거나 키 회전 fallback 누락.")


def _multikey_from_raw(primary_raw: str, fallbacks_raw: str) -> MultiKeyCipher | None:
    """base64 원시 키 문자열들에서 `MultiKeyCipher` 조립 — primary 미설정이면 None.

    device secret·대화 본문 등 *여러 자산*의 봉투 암호화기가 이 한 조립 로직을 공유한다(자산별
    키 소스만 다름·프리미티브 재사용). primary는 base64 32바이트, `fallbacks_raw`는 쉼표 구분
    base64(복호 전용·키 회전). 빈 토큰은 무시. 잘못된 길이는 `SecretCipher.__init__`이
    `ValueError`(부팅 fail-fast).
    """
    if not primary_raw:
        return None
    primary = SecretCipher(base64.b64decode(primary_raw))
    fallbacks: list[SecretCipher] = []
    if fallbacks_raw:
        for part in fallbacks_raw.split(","):
            token = part.strip()
            if token:
                fallbacks.append(SecretCipher(base64.b64decode(token)))
    return MultiKeyCipher(primary, fallbacks)


def build_secret_cipher(settings: Any) -> MultiKeyCipher | None:
    """`Settings`에서 device secret용 `MultiKeyCipher` 생성 — primary 키 미설정이면 None.

    None은 *암호화 비활성*(평문 폴백·기존 동작) 신호다(호출자가 분기). primary 키는 base64
    인코딩 32바이트. `device_secret_decryption_fallback_keys`(쉼표 구분 base64·복호 전용)는
    키 회전 중 구 키로 암호화된 행을 lockout 없이 복호하기 위한 fallback.

    `settings: Any` — `whymath_backend.config.Settings` 순환 import 회피(typing-only 명시).
    """
    return _multikey_from_raw(
        settings.device_secret_encryption_key.get_secret_value(),
        settings.device_secret_decryption_fallback_keys.get_secret_value(),
    )


def build_dialogue_content_cipher(settings: Any) -> MultiKeyCipher | None:
    """`Settings`에서 미성년 대화 본문(`dialogue_turn.content`)용 `MultiKeyCipher` 생성.

    `build_secret_cipher`와 *동일 조립 로직*(`_multikey_from_raw`)이나 **키 소스가 분리**된다
    (`dialogue_content_encryption_key`·`dialogue_content_decryption_fallback_keys`) — device
    secret 키와 별개라 한 키 유출의 폭발 반경을 대화 본문/디바이스 사이에서 격리한다. primary
    키 미설정이면 None(평문 폴백·CI·기존 배포 무영향·점진 도입).

    `settings: Any` — `whymath_backend.config.Settings` 순환 import 회피(typing-only 명시).
    """
    return _multikey_from_raw(
        settings.dialogue_content_encryption_key.get_secret_value(),
        settings.dialogue_content_decryption_fallback_keys.get_secret_value(),
    )


def encrypt_secret_for_storage(
    cipher: SupportsEnvelope | None,
    secret_plain: str,
    *,
    allow_plaintext_fallback: bool = False,
) -> tuple[str | None, bytes | None, bytes | None]:
    """slice 73: register용 — `(secret_plain, secret_encrypted, nonce)` 저장 3-튜플 결정.

    cipher 있으면 `(None, ciphertext, nonce)`(평문 컬럼 비우고 암호화 저장).

    cipher 없으면:
      - `allow_plaintext_fallback=True` → `(secret_plain, None, None)`(평문 폴백·개발/CI 전용).
      - `allow_plaintext_fallback=False` → `RuntimeError`(prod-like 추정 환경에서 조용한
        평문 저장 금지 — SEC-28 fail-closed).

    셋 중 *정확히 한 표현*만 채워진다.
    """
    if cipher is None:
        if not allow_plaintext_fallback:
            raise RuntimeError(
                "device secret 암호화기가 미설정입니다 — "
                "`WHYMATH_DEVICE_SECRET_ENCRYPTION_KEY`를 설정하거나 개발 모드에서만 "
                "평문 폴백을 명시적으로 허용하세요."
            )
        return secret_plain, None, None
    ciphertext, nonce = cipher.encrypt(secret_plain)
    return None, ciphertext, nonce


def resolve_stored_secret(
    cipher: SupportsEnvelope | None,
    secret_plain: str | None,
    secret_encrypted: bytes | None,
    nonce: bytes | None,
) -> str:
    """slice 73: verify용 — 저장 표현에서 HMAC용 평문 secret 복원.

    암호화 행(secret_encrypted+nonce)이면 복호, 평문 행이면 그대로 반환. *암호화 행인데
    cipher 미설정*이면 `RuntimeError`(조용한 401 lockout 대신 *시끄러운* 500 — 운영자가 키
    유실/미설정을 즉시 인지). 둘 다 없으면 데이터 무결성 오류(RuntimeError).
    """
    if secret_encrypted is not None and nonce is not None:
        if cipher is None:
            raise RuntimeError(
                "암호화된 device secret이나 복호 키가 미설정입니다 — "
                "`WHYMATH_DEVICE_SECRET_ENCRYPTION_KEY`를 확인하세요(키 유실 시 복호 불가)."
            )
        return cipher.decrypt(secret_encrypted, nonce)
    if secret_plain is not None:
        return secret_plain
    raise RuntimeError(
        "device 자격증명 행에 secret_plain·secret_encrypted가 모두 없습니다(데이터 무결성 오류)."
    )


def encrypt_dialogue_content(
    cipher: SupportsEnvelope | None, content: str | None
) -> tuple[str | None, bytes | None, bytes | None]:
    """대화 본문 저장용 — `(content_plain, content_encrypted, content_nonce)` 3-튜플 결정.

    `encrypt_secret_for_storage`의 대화 본문 래퍼. **content가 None이면 `(None, None, None)`**
    (본문 없는 턴·이미지 전용 턴 — 암호화 대상 자체가 없음). content 있으면 프리미티브에
    위임: cipher 있으면 `(None, ct, nonce)`(평문 컬럼 비움), 없으면 `(content, None, None)`
    (평문 폴백·기존 동작·명시적 폴백). device secret과 달리 content는 nullable이라 None 분기가
    추가된다.
    """
    if content is None:
        return None, None, None
    # 대화 본문은 개발·CI에서 cipher 미설정 시에도 평문 폴백을 허용(SEC-01·SEC-28).
    # prod-like 환경은 `require_dialogue_content_cipher`가 부팅 시 미리 차단한다.
    return encrypt_secret_for_storage(cipher, content, allow_plaintext_fallback=True)


def resolve_dialogue_content(
    cipher: SupportsEnvelope | None,
    content_plain: str | None,
    content_encrypted: bytes | None,
    content_nonce: bytes | None,
) -> str | None:
    """저장 표현에서 대화 본문 평문 복원 — 노출(GET·export) 직전 복호.

    암호화 행(content_encrypted+nonce)이면 복호하고, *암호화 행인데 cipher 미설정*이면
    `RuntimeError`(조용한 평문 유출/빈 응답 대신 *시끄러운* 실패 — 운영자가 키 유실/미설정을
    즉시 인지). 그 외(평문 행·본문 없는 턴)는 `content_plain`을 그대로 반환한다 —
    `resolve_stored_secret`과 달리 **평문·암호문 둘 다 None이면 None을 반환**(대화 본문은
    nullable이라 정상 상태·데이터 무결성 오류 아님).
    """
    if content_encrypted is not None and content_nonce is not None:
        if cipher is None:
            raise RuntimeError(
                "암호화된 대화 본문이나 복호 키가 미설정입니다 — "
                "`WHYMATH_DIALOGUE_CONTENT_ENCRYPTION_KEY`를 확인하세요(키 유실 시 복호 불가)."
            )
        return cipher.decrypt(content_encrypted, content_nonce)
    return content_plain


def build_evidence_payload_cipher(settings: Any) -> MultiKeyCipher | None:
    """`Settings`에서 미성년 학습 증거 payload(`evidence_event.payload_encrypted`)용 cipher 생성.

    `build_dialogue_content_cipher`와 *동일 조립 로직*(`_multikey_from_raw`)이나 **키 소스가 분리**
    된다(`evidence_payload_encryption_key`·`evidence_payload_decryption_fallback_keys`) — dialogue·
    device secret 키와 별개라 한 키 유출의 폭발 반경을 자산 간 격리한다. primary 키 미설정이면
    None(암호화 비활성 → 증거는 메타 전용으로만 적재·B1).

    `settings: Any` — `whymath_backend.config.Settings` 순환 import 회피(typing-only 명시).
    """
    return _multikey_from_raw(
        settings.evidence_payload_encryption_key.get_secret_value(),
        settings.evidence_payload_decryption_fallback_keys.get_secret_value(),
    )


def encrypt_evidence_payload(
    cipher: SupportsEnvelope | None, payload: str | None
) -> tuple[bytes | None, bytes | None]:
    """증거 payload 저장용 — `(payload_encrypted, payload_nonce)` 2-튜플 결정.

    **dialogue와 다른 점**: `evidence_event`에는 *평문 컬럼이 없다*. 따라서 cipher 미설정이거나
    payload가 None이면 `(None, None)`(메타 전용 — 미성년 원문 payload를 평문으로 저장하지 *않는다*·
    B1). cipher 있으면 `(ciphertext, nonce)`. 3-튜플(평문 폴백)인 대화 본문과 의도적으로 다르다.
    """
    if cipher is None or payload is None:
        return None, None
    ciphertext, nonce = cipher.encrypt(payload)
    return ciphertext, nonce


def resolve_evidence_payload(
    cipher: SupportsEnvelope | None,
    payload_encrypted: bytes | None,
    payload_nonce: bytes | None,
) -> str | None:
    """저장된 증거 payload 복호 — 노출(감사·분석) 직전. 없으면 None.

    암호화 행(payload_encrypted+nonce)인데 *cipher 미설정*이면 `RuntimeError`(조용한 유실/빈 응답
    대신 *시끄러운* 실패 — 운영자가 키 유실/미설정을 즉시 인지). 그 외(메타 전용 행)는 None.
    """
    if payload_encrypted is not None and payload_nonce is not None:
        if cipher is None:
            raise RuntimeError(
                "암호화된 증거 payload이나 복호 키가 미설정입니다 — "
                "`WHYMATH_EVIDENCE_PAYLOAD_ENCRYPTION_KEY`를 확인하세요(키 유실 시 복호 불가)."
            )
        return cipher.decrypt(payload_encrypted, payload_nonce)
    return None


def require_device_secret_cipher(settings: Any) -> MultiKeyCipher | None:
    """SEC-28: device secret cipher를 만들되, **프로덕션 추정 환경에서 키가 없으면 거부**한다.

    `build_secret_cipher`는 키가 없으면 조용히 `None`(평문 폴백)을 돌려준다. 이 폴백은
    개발·CI에서는 편의지만 프로덕션에서는 **CLAUDE.md 절대 금기("디바이스 secret 평문 저장")를
    조용히 위반**한다 — 그리고 조용하기 때문에 아무도 모른다. 이 게이트는 잊어도 작동한다.

    **프로덕션 판별**: `config.is_production_like`(단일 좌석)에 위임한다.

    Raises:
        RuntimeError: prod 추정 환경인데 `WHYMATH_DEVICE_SECRET_ENCRYPTION_KEY` 미설정.
    """
    from whymath_backend.config import is_production_like

    cipher = build_secret_cipher(settings)
    if cipher is not None:
        return cipher
    if is_production_like(settings):
        raise RuntimeError(
            "프로덕션 추정 환경(실 OAuth provider 구성)인데 device secret 암호화 키가 "
            "미설정입니다 — "
            "`WHYMATH_DEVICE_SECRET_ENCRYPTION_KEY`를 설정하세요. 디바이스 secret을 "
            "평문으로 저장하는 것은 절대 금기라 평문 폴백을 허용하지 않습니다."
        )
    return None


def require_dialogue_content_cipher(settings: Any) -> MultiKeyCipher | None:
    """SEC-01: cipher를 만들되, **프로덕션 추정 환경에서 키가 없으면 거부**한다(fail-closed).

    `build_dialogue_content_cipher`는 키가 없으면 조용히 `None`(평문 폴백)을 돌려준다. 그 폴백은
    개발·CI에서는 옳지만 프로덕션에서는 **CLAUDE.md 절대 금기("미성년자 채팅 데이터를 평문으로
    저장 금지")를 조용히 위반**한다 — 그리고 조용하기 때문에 아무도 모른다. 체크리스트는 사람이
    기억해야 작동하지만, 이 게이트는 잊어도 작동한다.

    **프로덕션 판별**: `config.is_production_like`(단일 좌석)에 위임한다 — 판정 로직을 여기에
    복사하면 스키마 버전 가드(SEC-03) 등 다른 소비처와 서로 표류한다. 판별 근거·새 env 축을
    두지 않은 이유는 그 함수 docstring 참조.

    Raises:
        RuntimeError: prod 추정 환경인데 `WHYMATH_DIALOGUE_CONTENT_ENCRYPTION_KEY` 미설정.
    """
    from whymath_backend.config import is_production_like

    cipher = build_dialogue_content_cipher(settings)
    if cipher is not None:
        return cipher
    if is_production_like(settings):
        raise RuntimeError(
            "프로덕션 추정 환경(실 OAuth provider 구성)인데 대화 암호화 키가 미설정입니다 — "
            "`WHYMATH_DIALOGUE_CONTENT_ENCRYPTION_KEY`를 설정하세요. 미성년자 대화·손글씨를 "
            "평문으로 저장하는 것은 절대 금기라 평문 폴백을 허용하지 않습니다."
        )
    return None


def build_student_work_cipher(settings: Any) -> MultiKeyCipher | None:
    """`Settings`에서 학생 답안/풀이 본문(SEC-31 — `problem_attempt`·`answer_submission`·
    `student_solution_step` 3테이블) 저장용 `MultiKeyCipher` 생성.

    `build_dialogue_content_cipher`·`build_evidence_payload_cipher`와 *동일 조립 로직*
    (`_multikey_from_raw`)이나 **키 소스가 분리**된다(`student_work_encryption_key`·
    `student_work_decryption_fallback_keys`) — dialogue·evidence·device secret 키와 별개라 한
    키 유출의 폭발 반경을 자산 간 격리한다. 3테이블은 *이 키 하나를* 공유한다 — 한 답안 제출
    흐름 안에서 같은 데이터 주체(그 학생)의 같은 논리적 사건으로 함께 적재되는 관계라, 테이블별로
    쪼개도 폭발 반경이 실질적으로 줄지 않는 반면 "미설정→평문 폴백" 함정만 3배가 된다(dialogue_turn
    내부 3축 공유 결정과 동일 근거). primary 키 미설정이면 None(평문 폴백·CI·기존 배포 무영향·
    점진 도입).

    `settings: Any` — `whymath_backend.config.Settings` 순환 import 회피(typing-only 명시).
    """
    return _multikey_from_raw(
        settings.student_work_encryption_key.get_secret_value(),
        settings.student_work_decryption_fallback_keys.get_secret_value(),
    )


def require_student_work_cipher(settings: Any) -> MultiKeyCipher | None:
    """SEC-31: cipher를 만들되, **프로덕션 추정 환경에서 키가 없으면 거부**한다(fail-closed).

    `build_student_work_cipher`는 키가 없으면 조용히 `None`(평문 폴백)을 돌려준다. 그 폴백은
    개발·CI에서는 옳지만 프로덕션에서는 **CLAUDE.md 절대 금기("학생 데이터는 민감 정보로 분류 —
    암호화 저장")를 조용히 위반**한다 — 그리고 조용하기 때문에 아무도 모른다.
    `require_dialogue_content_cipher`(SEC-01)와 동일한 게이트 형태.

    **프로덕션 판별**: `config.is_production_like`(단일 좌석)에 위임한다.

    Raises:
        RuntimeError: prod 추정 환경인데 `WHYMATH_STUDENT_WORK_ENCRYPTION_KEY` 미설정.
    """
    from whymath_backend.config import is_production_like

    cipher = build_student_work_cipher(settings)
    if cipher is not None:
        return cipher
    if is_production_like(settings):
        raise RuntimeError(
            "프로덕션 추정 환경(실 OAuth provider 구성)인데 학생 답안/풀이 암호화 키가 "
            "미설정입니다 — `WHYMATH_STUDENT_WORK_ENCRYPTION_KEY`를 설정하세요. 학생 답안·풀이 "
            "본문을 평문으로 저장하는 것은 절대 금기라 평문 폴백을 허용하지 않습니다."
        )
    return None


def encrypt_student_solution_step_expression(
    cipher: SupportsEnvelope | None, expression: str
) -> tuple[str | None, bytes | None, bytes | None]:
    """`student_solution_step.expression` 저장용 3-튜플 — **NOT NULL** 전용(schema min_length=1).

    다른 5개 학생 답안/풀이 필드(nullable)는 `encrypt_dialogue_content`(값 없음 분기 포함)를
    그대로 재사용하지만, `expression`은 값이 *항상* 있어(빈 문자열 없음) 그 분기가 필요 없다 —
    "값이 항상 있고 cipher 없으면 평문 폴백"인 `encrypt_secret_for_storage`(device secret 계약)
    를 재사용한다.
    """
    return encrypt_secret_for_storage(cipher, expression, allow_plaintext_fallback=True)


def resolve_student_solution_step_expression(
    cipher: SupportsEnvelope | None,
    expression_plain: str | None,
    expression_encrypted: bytes | None,
    expression_nonce: bytes | None,
) -> str:
    """저장 표현에서 `expression` 평문 복원 — 항상 `str` 반환(schema 계약 `min_length=1`).

    `resolve_dialogue_content`와 달리 *평문·암호문 둘 다 없는 상태는 정상이 아니다* — expression은
    NOT NULL 계약이라 `resolve_stored_secret`(device secret과 동일 계약: 암호행인데 cipher
    미설정이면 RuntimeError, 평문·암호문 둘 다 없으면 데이터 무결성 오류 RuntimeError)을
    재사용한다 — 조용히 빈 문자열/None을 만들지 않는다.
    """
    return resolve_stored_secret(cipher, expression_plain, expression_encrypted, expression_nonce)


def encrypt_dialogue_image_uri(
    cipher: SupportsEnvelope | None, image_uri: str | None
) -> tuple[str | None, bytes | None, bytes | None]:
    """손글씨 이미지 URI 저장용 3-튜플 — `encrypt_dialogue_content`와 동일 계약(문자열).

    URI 자체가 미성년 풀이 이미지를 가리키는 포인터라 본문과 같은 등급으로 다룬다.
    """
    return encrypt_dialogue_content(cipher, image_uri)


def resolve_dialogue_image_uri(
    cipher: SupportsEnvelope | None,
    image_uri_plain: str | None,
    image_uri_encrypted: bytes | None,
    image_uri_nonce: bytes | None,
) -> str | None:
    """저장 표현에서 이미지 URI 복원 — `resolve_dialogue_content`와 동일 계약."""
    return resolve_dialogue_content(cipher, image_uri_plain, image_uri_encrypted, image_uri_nonce)


def encrypt_dialogue_image_analysis(
    cipher: SupportsEnvelope | None, image_analysis: dict[str, Any] | None
) -> tuple[dict[str, Any] | None, bytes | None, bytes | None]:
    """Qwen3-VL 분석(JSONB) 저장용 3-튜플 — **결정론 JSON 직렬화 후** 암호화.

    JSONB는 바이트가 아니라 구조라 그대로 암호화할 수 없다. `sort_keys=True`로 직렬화해
    같은 dict가 같은 평문이 되게 하고(재현성), `ensure_ascii=False`로 한글을 보존한다.
    분석 결과가 없으면 `(None, None, None)`(암호화 대상 없음).
    """
    if image_analysis is None:
        return None, None, None
    if cipher is None:
        return image_analysis, None, None
    serialized = json.dumps(image_analysis, sort_keys=True, ensure_ascii=False)
    ciphertext, nonce = cipher.encrypt(serialized)
    return None, ciphertext, nonce


def resolve_dialogue_image_analysis(
    cipher: SupportsEnvelope | None,
    image_analysis_plain: dict[str, Any] | None,
    image_analysis_encrypted: bytes | None,
    image_analysis_nonce: bytes | None,
) -> dict[str, Any] | None:
    """저장 표현에서 분석 dict 복원 — 복호 후 역직렬화.

    암호화 행인데 cipher 미설정이면 `RuntimeError`(조용한 빈 응답 대신 시끄러운 실패).
    역직렬화 결과가 dict가 아니면 데이터 무결성 오류로 `RuntimeError` — 조용히 None으로
    삼키면 분석이 사라진 것을 아무도 모른다.
    """
    if image_analysis_encrypted is not None and image_analysis_nonce is not None:
        if cipher is None:
            raise RuntimeError(
                "암호화된 이미지 분석이나 복호 키가 미설정입니다 — "
                "`WHYMATH_DIALOGUE_CONTENT_ENCRYPTION_KEY`를 확인하세요(키 유실 시 복호 불가)."
            )
        decoded = json.loads(cipher.decrypt(image_analysis_encrypted, image_analysis_nonce))
        if not isinstance(decoded, dict):
            raise RuntimeError(
                f"복호된 이미지 분석이 dict가 아닙니다(받음: {type(decoded).__name__}) — "
                "데이터 무결성 오류."
            )
        return decoded
    return image_analysis_plain


__all__ = [
    "MultiKeyCipher",
    "SecretCipher",
    "SupportsEnvelope",
    "build_dialogue_content_cipher",
    "build_evidence_payload_cipher",
    "build_secret_cipher",
    "build_student_work_cipher",
    "encrypt_dialogue_content",
    "encrypt_dialogue_image_analysis",
    "encrypt_dialogue_image_uri",
    "encrypt_evidence_payload",
    "encrypt_secret_for_storage",
    "encrypt_student_solution_step_expression",
    "require_device_secret_cipher",
    "require_dialogue_content_cipher",
    "require_student_work_cipher",
    "resolve_dialogue_content",
    "resolve_dialogue_image_analysis",
    "resolve_dialogue_image_uri",
    "resolve_evidence_payload",
    "resolve_stored_secret",
    "resolve_student_solution_step_expression",
]
