"""SEC-11 로그 스크러버 — 변별력 쌍 + 예외 타입명 보존 회귀 (`ops/log_scrubber.py`).

acceptance ②의 핵심: "마스킹을 끄면 테스트가 실패한다"를 문자 그대로 구현한다 — 같은
어서션 블록을 스크러버 *있음*/*없음* 양쪽에 태워, 있음은 통과·없음은 실패하는 것을 직접
확인한다(CLAUDE.md "변별력 없는 검증 스텝 금지" — 성공/실패 양쪽에서 같은 값을 내면
검사가 아니라 위장).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest

from whymath_backend.ops.log_scrubber import (
    PiiSecretScrubberFilter,
    install_log_scrubber,
    scrub_text,
)


def _capture(logger: logging.Logger, level: int, message: str, *args: object) -> str:
    """`logger`가 실제로 방출하는 최종 포맷 문자열 1건을 캡처한다(핸들러 경유 — 필터 적용 확인)."""
    records: list[logging.LogRecord] = []

    class _Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Collector()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        logger.log(level, message, *args)
    finally:
        logger.removeHandler(handler)
    assert records, "로그 레코드가 캡처되지 않음(테스트 배선 오류)"
    return records[0].getMessage()


@pytest.fixture()
def scrubbed_logger() -> logging.Logger:
    """스크러버가 배선된 전용 로거(루트 오염 방지 — 테스트마다 새 이름)."""
    logger = logging.getLogger("test.log_scrubber.on")
    logger.filters = []
    logger.addFilter(PiiSecretScrubberFilter())
    return logger


@pytest.fixture()
def unscrubbed_logger() -> logging.Logger:
    """스크러버가 *없는* 동일 계열 로거 — '마스킹을 끄면 실패' 대조군."""
    logger = logging.getLogger("test.log_scrubber.off")
    logger.filters = []
    return logger


@pytest.fixture()
def scrubber_globally_disabled() -> Iterator[None]:
    """LogRecord 팩토리를 기본값으로 되돌려 SEC-11 스크러버를 프로세스 전역에서 *잠시* 끈다.

    `install_log_scrubber()`는 레코드 *생성 시점*에 개입하는 전역 팩토리로 동작한다(모듈
    docstring '배선' 절 — 로거별 `addFilter`만으로는 자식 로거의 레코드를 못 잡는 Python
    logging 전파 규칙 때문). 그래서 "마스킹을 끄면 실패한다"(CLAUDE.md 변별력 규칙)를 문자
    그대로 재현하려면 로거에서 필터를 떼는 것만으론 부족하고, 이 전역 팩토리 자체를 기본값
    (`logging.LogRecord`)으로 되돌려야 한다. 테스트 종료 시 원래 팩토리(스크러버 포함)를
    반드시 복원해 나머지 테스트 스위트가 무방비 상태로 남지 않게 한다.
    """
    original_factory = logging.getLogRecordFactory()
    logging.setLogRecordFactory(logging.LogRecord)
    try:
        yield
    finally:
        logging.setLogRecordFactory(original_factory)


# ──────────────────────────────────────────────────────────────────────────
# 변별력 쌍 (a) 학생 원문 (b) sk-/pk- 시크릿 (c) Bearer 토큰
# ──────────────────────────────────────────────────────────────────────────
class TestDiscriminationPairs:
    """각 케이스: 스크러버 有 → 마스킹됨(원문 미노출) / 스크러버 無 → 원문 그대로(같은 코드가
    실패)."""

    _STUDENT_DIALOGUE_CASES = [
        'student_text="x^2 + 2x + 1 = (x+1)^2 입니다, 제 이름은 김민수이고 '
        '010-1234-5678로 연락주세요"',
        "student_solution: 부모님 이메일은 minsu.parent@example.com 입니다",
    ]

    @pytest.mark.parametrize("raw_message", _STUDENT_DIALOGUE_CASES)
    def test_student_dialogue_masked_with_scrubber(
        self, scrubbed_logger: logging.Logger, raw_message: str
    ) -> None:
        """(a) 학생 발화/연락처 원문 후보 — 스크러버가 있으면 값이 노출되지 않는다."""
        out = _capture(scrubbed_logger, logging.INFO, raw_message)
        assert "김민수" not in out
        assert "010-1234-5678" not in out
        assert "minsu.parent@example.com" not in out

    @pytest.mark.parametrize("raw_message", _STUDENT_DIALOGUE_CASES)
    def test_student_dialogue_leaks_without_scrubber(
        self,
        unscrubbed_logger: logging.Logger,
        scrubber_globally_disabled: None,
        raw_message: str,
    ) -> None:
        """동일 케이스 — 스크러버를 끄면(대조군) 원문이 그대로 새어나간다.

        이 테스트가 통과한다는 사실 자체가 위 `test_student_dialogue_masked_with_scrubber`가
        변별력 있는 검사였음을 증명한다(마스킹 여부에 따라 반대 결과가 나옴).
        """
        out = _capture(unscrubbed_logger, logging.INFO, raw_message)
        assert ("010-1234-5678" in out) or ("minsu.parent@example.com" in out)

    @pytest.mark.parametrize(
        "raw_message",
        [
            "Anthropic 키 설정: sk-ant-api03-abcdEFGH12345678zzzzYYYY",
            "Langfuse public key: pk-lf-1234567890abcdef",
        ],
    )
    def test_api_key_masked_with_scrubber(
        self, scrubbed_logger: logging.Logger, raw_message: str
    ) -> None:
        """(b) sk-/pk- 시크릿 — 스크러버가 있으면 원문 키가 로그에 남지 않는다."""
        out = _capture(scrubbed_logger, logging.INFO, raw_message)
        assert "sk-ant-api03-abcdEFGH12345678zzzzYYYY" not in out
        assert "pk-lf-1234567890abcdef" not in out
        assert "***MASKED***" in out

    @pytest.mark.parametrize(
        "raw_message",
        [
            "Anthropic 키 설정: sk-ant-api03-abcdEFGH12345678zzzzYYYY",
            "Langfuse public key: pk-lf-1234567890abcdef",
        ],
    )
    def test_api_key_leaks_without_scrubber(
        self,
        unscrubbed_logger: logging.Logger,
        scrubber_globally_disabled: None,
        raw_message: str,
    ) -> None:
        """동일 케이스 — 스크러버 없이는 실제 키 값이 그대로 로그에 남는다(대조군)."""
        out = _capture(unscrubbed_logger, logging.INFO, raw_message)
        assert ("sk-ant-api03-abcdEFGH12345678zzzzYYYY" in out) or ("pk-lf-1234567890abcdef" in out)

    def test_bearer_token_masked_with_scrubber(self, scrubbed_logger: logging.Logger) -> None:
        """(c) Bearer 토큰 — 스크러버가 있으면 Authorization 헤더 값이 마스킹된다."""
        raw = (
            "요청 헤더 Authorization: Bearer "
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJzdHVkZW50LTEyMyJ9.dGVzdHNpZ25hdHVyZQ"
        )
        out = _capture(scrubbed_logger, logging.INFO, raw)
        assert "eyJhbGciOiJIUzI1NiJ9" not in out
        assert "***MASKED***" in out

    def test_bearer_token_leaks_without_scrubber(
        self, unscrubbed_logger: logging.Logger, scrubber_globally_disabled: None
    ) -> None:
        """동일 케이스 — 스크러버 없이는 Bearer 토큰이 그대로 노출된다(대조군)."""
        raw = (
            "요청 헤더 Authorization: Bearer "
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJzdHVkZW50LTEyMyJ9.dGVzdHNpZ25hdHVyZQ"
        )
        out = _capture(unscrubbed_logger, logging.INFO, raw)
        assert "eyJhbGciOiJIUzI1NiJ9" in out

    def test_env_secret_value_masked_but_key_name_preserved(
        self, scrubbed_logger: logging.Logger
    ) -> None:
        """WHYMATH_*_KEY/SECRET/SALT 대입 — 값은 마스킹하되 진단용 키 *이름*은 남긴다."""
        raw = "WHYMATH_JWT_SECRET_KEY=super-real-signing-secret-value-000"
        out = _capture(scrubbed_logger, logging.INFO, raw)
        assert "super-real-signing-secret-value-000" not in out
        assert "WHYMATH_JWT_SECRET_KEY" in out  # 키 이름은 진단에 필요 — 보존


# ──────────────────────────────────────────────────────────────────────────
# 예외 타입명 보존 회귀 — CLAUDE.md "침묵 실패 금지"(무타입 경고 금지)와 충돌 방지
# ──────────────────────────────────────────────────────────────────────────
class TestExceptionTypeNamesSurvive:
    """스크러버가 예외 *타입명*을 지우면 8일 무증상 전멸(2026-07-16 langfuse 사고)이 재발한다."""

    @pytest.mark.parametrize(
        "exc_type_name",
        ["ValueError", "ConnectionError", "RuntimeError", "TimeoutError", "KeyError"],
    )
    def test_exception_type_names_survive_masking(
        self, scrubbed_logger: logging.Logger, exc_type_name: str
    ) -> None:
        """관측 코드의 표준 관용구(`type(exc).__name__`)가 그대로 로그에 남는다."""
        message = f"요청 계측 실패(요청은 정상 반환) — 예외 타입: {exc_type_name}"
        out = _capture(scrubbed_logger, logging.WARNING, message)
        assert exc_type_name in out
        assert "***MASKED***" not in out  # 이 메시지엔 시크릿이 없으니 마스킹도 없어야 정상

    def test_exception_type_name_survives_alongside_secret_in_same_message(
        self, scrubbed_logger: logging.Logger
    ) -> None:
        """같은 메시지에 시크릿과 예외 타입명이 동시에 있어도 타입명만 살아남는다(핵심 케이스)."""
        message = (
            "Anthropic 호출 실패 — 예외 타입: ConnectionError, "
            "사용된 키 sk-ant-api03-leakedkey0001"
        )
        out = _capture(scrubbed_logger, logging.WARNING, message)
        assert "ConnectionError" in out
        assert "sk-ant-api03-leakedkey0001" not in out


# ──────────────────────────────────────────────────────────────────────────
# 기존 로그 호출부 회귀 — 시크릿·PII가 없는 메시지는 포맷·내용이 무변경(추가적 필터일 뿐)
# ──────────────────────────────────────────────────────────────────────────
class TestBenignMessagesUnaffected:
    def test_plain_korean_message_unchanged(self, scrubbed_logger: logging.Logger) -> None:
        raw = "오개념 의미 매처 웜업 실패 — 첫 요청 시 lazy 재시도"
        out = _capture(scrubbed_logger, logging.WARNING, raw)
        assert out == raw

    def test_percent_style_args_still_interpolated(self, scrubbed_logger: logging.Logger) -> None:
        """`logger.warning("... %s", value)` 관용구 — 시크릿이 없으면 %-포맷이 그대로 동작."""
        records: list[logging.LogRecord] = []

        class _Collector(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        handler = _Collector()
        scrubbed_logger.addHandler(handler)
        try:
            scrubbed_logger.warning("요청 계측 실패 — 예외 타입: %s", "ValueError")
        finally:
            scrubbed_logger.removeHandler(handler)
        assert records[0].getMessage() == "요청 계측 실패 — 예외 타입: ValueError"

    def test_no_mutation_when_nothing_to_mask(self) -> None:
        """마스킹 대상이 없으면 record.msg/args를 건드리지 않는다(성능·포맷 무변경 보증)."""
        record = logging.LogRecord(
            name="x",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="평범한 진단 메시지 — 시크릿 없음",
            args=(),
            exc_info=None,
        )
        original_msg = record.msg
        original_args = record.args
        assert PiiSecretScrubberFilter().filter(record) is True
        assert record.msg is original_msg
        assert record.args is original_args


# ──────────────────────────────────────────────────────────────────────────
# scrub_text 순수 함수 단위 — 필터 내부 로직 직접 검증(핸들러 우회 없이)
# ──────────────────────────────────────────────────────────────────────────
def test_scrub_text_masks_all_three_discrimination_categories() -> None:
    combined = (
        'student_text="학생 원문 예시" '
        "key=sk-testkey1234567890 "
        "Authorization: Bearer abc123.def456.ghi789xyz"
    )
    out = scrub_text(combined)
    assert "학생 원문 예시" not in out
    assert "sk-testkey1234567890" not in out
    assert "abc123.def456.ghi789xyz" not in out


def test_install_log_scrubber_is_idempotent() -> None:
    """같은 로거에 두 번 배선해도 필터가 누적되지 않는다."""
    logger = logging.getLogger("test.log_scrubber.idempotent")
    logger.filters = []
    first = install_log_scrubber(logger)
    second = install_log_scrubber(logger)
    assert first is second
    assert sum(isinstance(f, PiiSecretScrubberFilter) for f in logger.filters) == 1


# ──────────────────────────────────────────────────────────────────────────
# SEC-38 — 한글 인접 경계: 정규식 `\b`가 한글을 단어 문자로 봐서 한국어 문장 속 PII·시크릿을
# 놓치던 사각. 2026-09-28 실측에서 아래 입력이 전부 원문 그대로 통과했다(수정 전 RED 확인).
# ──────────────────────────────────────────────────────────────────────────
_KOREAN_ADJACENT_CASES: tuple[tuple[str, str], ...] = (
    # (입력 문장, 마스킹돼야 할 부분)
    ("연락처 010-1234-5678로 문의", "010-1234-5678"),  # 조사가 뒤에 붙은 휴대전화
    ("전화 01012345678입니다", "01012345678"),  # 하이픈 없는 휴대전화 + 조사
    ("메일 kid@test.com으로", "kid@test.com"),  # 조사가 뒤에 붙은 이메일
    ("메일은kid@test.com", "kid@test.com"),  # 한글이 바로 앞에 붙은 이메일
    ("키sk-ant-abcdefgh1234 노출", "sk-ant-abcdefgh1234"),  # 한글 직후 API 키
    ("토큰eyJhbGciOi.eyJzdWIiOi.c2lnbmF0dXJl", "eyJhbGciOi.eyJzdWIiOi.c2lnbmF0dXJl"),  # JWT
    ("헤더Bearer abcdefgh12345", "abcdefgh12345"),  # 한글 직후 Bearer 토큰
)


@pytest.mark.parametrize(("text", "secret"), _KOREAN_ADJACENT_CASES)
def test_korean_adjacent_pii_and_secrets_are_masked(text: str, secret: str) -> None:
    """한글이 앞뒤에 붙어도 PII·시크릿이 가려진다 — 로그는 한국어 문장이 기본이다."""
    out = scrub_text(text)
    assert secret not in out
    assert "***MASKED***" in out


def test_korean_adjacent_env_secret_masks_value_and_keeps_name() -> None:
    """한글 직후의 `WHYMATH_*_KEY=` 대입도 값만 가리고 키 이름은 진단용으로 남긴다."""
    out = scrub_text("설정WHYMATH_JWT_SECRET_KEY=abc123xyz")
    assert "abc123xyz" not in out
    assert "WHYMATH_JWT_SECRET_KEY" in out


def test_korean_adjacent_sensitive_field_value_is_masked() -> None:
    """한글 직후의 학생 원문 필드명(`student_text=`)도 값이 가려진다."""
    out = scrub_text("필드student_text=학생원문풀이")
    assert "학생원문풀이" not in out


@pytest.mark.parametrize(
    "text",
    [
        "주문번호 A01012345678 참조",  # 영문자 바로 뒤 숫자열 — 전화번호가 아니다(종전과 같음)
        "일련번호 9901012345678 참조",  # 더 긴 숫자열의 일부 — 전화번호가 아니다(종전과 같음)
        "변수 mysk-abcdefgh123 확인",  # 영문자 바로 뒤 sk- — API 키 접두가 아니다(종전과 같음)
    ],
)
def test_ascii_alnum_adjacency_still_not_masked(text: str) -> None:
    """대조군 — 경계 수정은 한글 인접만 푼다. 영숫자 인접 판정은 수정 전과 같아야 한다."""
    assert scrub_text(text) == text
