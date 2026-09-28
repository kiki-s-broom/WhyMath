"""로그 PII·시크릿 스크러버 — `logging.Filter` 1개, 루트 로거에 실제 배선 (SEC-11).

배경
----
저장 축은 fail-closed 게이트로 닫혀 있다(`api/_crypto.py:285`
`require_dialogue_content_cipher` — 프로덕션 추정 환경에서 대화 암호화 키가 없으면 부팅
자체를 거부한다). 그런데 로깅 축은 `CLAUDE.md`·`dev_constitution.md` §9·
`security_privacy.md` 로그 절, 세 곳이 "시크릿·PII를 로그에 남기지 마라"고 **규정만** 하고,
그 규정을 실제로 강제하는 코드는 0건이었다(`logging.Filter`/`addFilter` grep 0 —
`docs/architecture/account_security_gap_review.md` D5 실측). 같은 위험을 한쪽은 게이트로,
한쪽은 사람 기억으로 다루는 비대칭이 갭 그 자체다. 이 모듈이 그 비대칭을 닫는다.

무엇을 마스킹하나
-----------------
1. **시크릿 형태 문자열** — `sk-`/`pk-` 접두 API 키(Anthropic `sk-ant-…`·OpenAI `sk-…`·
   Langfuse `pk-lf-…`/`sk-lf-…` — CLAUDE.md "시크릿 입력 안내 규칙" 2026-07-16 사고 범위 포함)
   · `Bearer <token>` Authorization 헤더 · JWT 3-세그먼트(`WHYMATH_JWT_SECRET_KEY`로 서명되는
   액세스/리프레시 토큰의 실제 모양) · `WHYMATH_*_KEY`/`*_SECRET`/`*_SALT` 환경변수 대입(값만 —
   키 *이름*은 진단에 필요해 보존한다, `config.py`의 `WHYMATH_JWT_SECRET_KEY`·
   `WHYMATH_PII_AUDIT_IP_SALT`·`WHYMATH_DIALOGUE_CONTENT_ENCRYPTION_KEY` 등 실사용 이름 기반).
2. **개인식별정보 형태** — 이메일 · 한국 휴대전화 번호.
3. **학생 발화·풀이 원문 후보 필드** — `student_text`/`student_solution`/`student_answer`/
   `solution_text`/`dialogue_content`/`handwriting_uri`/`ocr_result`/`ocr_text` 등, 코드베이스
   실사용 필드명(`api/coach.py`·`harness/wh1_*.py` grep 답습)이 `key=value`/`"key": "value"`
   형태로 로그에 흘렀을 때 **값만** 마스킹한다. 자유 산문 전체를 의미론적으로 탐지하는 것은
   오탐이 통제 불가능해 채택하지 않는다(구축 플레이북 "과공학 방지") — 필드명 기반이 현실적
   방어선이다. `security_privacy.md` 로그 절이 위임하는 범위와 동일.

무엇을 마스킹하지 않나 (하드 제약)
--------------------------------
- **예외 타입명**(`type(exc).__name__`)은 어떤 패턴도 건드리지 않는다 — CLAUDE.md "침묵 실패
  금지"(dev_constitution.md §9 R1): best-effort 예외 흡수 코드가 타입명을 못 남기면 8일
  무증상 전멸(2026-07-16 langfuse 사고)이 재발한다. `ValueError`·`ConnectionError`·
  `RuntimeError` 같은 평범한 CamelCase 식별자는 하이픈·`@`·자릿수가 없어 시크릿/PII 패턴
  어느 것과도 구조적으로 겹치지 않는다 — `tests/backend/ops/test_log_scrubber.py::
  test_exception_type_names_survive_masking`이 회귀로 동결한다.
- `record.exc_info`(트레이스백 원본)는 건드리지 않는다 — 이 필터는 `record.getMessage()`가
  만든 *최종 렌더 문자열*만 검사한다.
- 마스킹 대상이 없는 메시지는 `record.msg`/`record.args`를 전혀 건드리지 않는다 — 기존 로그
  호출부의 포맷·성능은 무변경(추가적 필터일 뿐 로깅 호출부 재작성이 아니다).

배선 — 왜 `root.addFilter()` 한 줄로는 부족한가 (실측 함정)
--------------------------------------------------------
표준 라이브러리 `logging`의 전파 규칙: 자식 로거(`logging.getLogger(__name__)` — 이 코드베이스
전역의 실사용 패턴)가 만든 레코드가 루트까지 올라갈 때, `Logger.callHandlers`는 **조상 로거의
핸들러만** 순회하고 **조상 로거 자신의 `Filter`는 건너뛴다**(로거 레벨 필터는 그 레코드를
*만든* 로거의 `.handle()`에서 딱 한 번만 검사된다 — CPython `logging/__init__.py` 구현).
즉 `logging.getLogger().addFilter(PiiSecretScrubberFilter())`만 하면 `logging.getLogger()`
(루트를 직접 쓰는 호출)만 걸리고, 이 저장소 전체가 쓰는 `logger = logging.getLogger(__name__)`
호출은 **전혀 걸러지지 않는다** — 이 모듈의 자체 변별력 테스트
(`tests/backend/ops/test_log_scrubber_wiring.py::
TestRootLoggerWiringReality::test_scrubber_active_end_to_end_through_test_client`)를 작성하는
과정에서 실측으로 드러났다("존재함 ≠ 돌아감"이 로깅 레이어 안에서도 성립하는 사례).

그래서 `install_log_scrubber()`는 **`logging.setLogRecordFactory`로 레코드 생성 지점 자체를
감싼다** — 어느 로거·어느 핸들러 경로를 타든(지금 핸들러가 0개라 `logging.lastResort`로
빠지는 경로든, 나중에 ops가 dictConfig로 핸들러를 추가하는 경로든) 레코드가 **만들어지는
순간** 이미 마스킹이 끝나 있다. `PiiSecretScrubberFilter`(마스킹 로직 단일 소스)는 그대로
두고, 추가로 **루트 로거에도 `addFilter`**한다(직접 `logging.getLogger()`/`logging.warning(...)`
호출 경로에 대한 명시적 배선 — acceptance 문구 "필터가 루트 로거에 배선"의 문자 그대로의
충족이자 이중 방어). `app.py`의 `create_app()`이 부팅 시 `install_log_scrubber()`를 1회
호출한다(`api/_crypto.py`의 "게이트는 앱 구성 시점에 건다" 선례 답습 — Settings 게이트 없음:
저장 축 fail-closed 게이트와 마찬가지로 로그 마스킹을 끄는 옵션을 별도로 주지 않는다). 배선이
지워지면 `tests/backend/ops/test_log_scrubber_wiring.py`가 실패한다("존재함 ≠ 돌아감" —
`tests/infra/test_test_suite_wiring.py` 선례).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable

_MASK = "***MASKED***"

# SEC-38: 이 모듈의 모든 정규식은 `re.ASCII`로 컴파일한다. 파이썬 `re`는 기본값(유니코드)에서
# 한글을 단어 문자(`\w`)로 보기 때문에, `\b` 경계가 "010-1234-5678로"·"kid@test.com으로"·
# "키sk-ant-…"처럼 한글이 붙은 자리에서 성립하지 않아 한국어 로그 문장 속 PII·시크릿을 통째로
# 놓쳤다(2026-09-28 실측 — `scrub_text`가 원문 그대로 반환). 패턴의 문자 클래스는 전부 ASCII라
# 경계만 ASCII 기준으로 되돌리면 된다 — 영숫자에 붙은 경우의 판정(비매칭)은 수정 전과 같고,
# 한글에 붙은 경우만 새로 잡힌다(`tests/backend/ops/test_log_scrubber.py`의 SEC-38 절이 대조군과
# 함께 동결한다).
_ASCII = re.ASCII

# ── 1a) 시크릿(자격증명) 형태 패턴 — `SECRET_LITERAL_PATTERNS`로 공개(하드코딩 스캔 재사용) ──
CREDENTIAL_SHAPE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # API 키류: Anthropic `sk-ant-…`, OpenAI `sk-…`, Langfuse `pk-lf-…`/`sk-lf-…` 등.
    re.compile(r"\b(?:sk|pk)-[A-Za-z0-9_-]{6,}", _ASCII),
    # Authorization 헤더 `Bearer <token>` — 토큰 문자(base64url·JWT 마침표 포함) 전체.
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE | _ASCII),
    # JWT 3-세그먼트(header.payload.signature, base64url) — Bearer 접두 없이 단독 로그된 경우.
    re.compile(r"\beyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}", _ASCII),
)

# ── 1b) PII 형태 패턴 — 로그 마스킹 전용으로 신설됐으나(시크릿 하드코딩 스캔에는 재사용하지
#      않음: 이메일은 "시크릿"이 아니라 코드 주석·문서에 정당하게 등장할 수 있어 스캔에 넣으면
#      오탐 유발), ARCH-24(`harness/banned_words_pii_eval.py`)가 학생 대면 산문의 타인 PII
#      하드코딩·자기 PII 반사 스캔에 재사용하는 두 번째 소비처가 되어 공개(`_` 제거)했다.
#      정규식 값 자체는 변경하지 않는다(재구현 금지 — 두 소비처 모두 같은 "PII의 모양"을
#      봐야 한다, 단일 진실 원천). SEC-38로 경계 판정만 `re.ASCII`로 바꿨고, 두 소비처가
#      같은 객체를 쓰므로 수정도 함께 받는다.
PII_SHAPE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # 이메일.
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", _ASCII),
    # 한국 휴대전화(010-1234-5678 / 01012345678 등).
    re.compile(r"\b01[016789]-?\d{3,4}-?\d{4}\b", _ASCII),
)

# 로그 마스킹(scrub_text)이 실제 검사하는 전체 패턴 집합 — 자격증명 + PII.
_SIMPLE_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    CREDENTIAL_SHAPE_PATTERNS + PII_SHAPE_PATTERNS
)

# 시크릿 하드코딩 저장소 스캔(`tests/backend/ops/test_secret_hardcoding_scan.py`)이 재사용하는
# 공개 별칭 — "시크릿의 모양"이 로그 마스킹과 하드코딩 스캔 양쪽에서 동일해야 한다(단일 진실
# 원천, dev_constitution.md:193 "시크릿 형식 자가검증"의 코드화).
SECRET_LITERAL_PATTERNS = CREDENTIAL_SHAPE_PATTERNS

# ── 2) WHYMATH_*_KEY/SECRET/SALT 환경변수 대입 — 키 *이름*은 진단용으로 보존, 값만 마스킹 ──
_ENV_SECRET_PATTERN = re.compile(
    r"\b(WHYMATH_[A-Z0-9_]*(?:KEY|SECRET|SALT)[A-Z0-9_]*)\s*[:=]\s*(\S+)", _ASCII
)


def _mask_env_secret(match: re.Match[str]) -> str:
    return f"{match.group(1)}={_MASK}"


# ── 3) 학생 발화·풀이 원문 후보 필드명 — key=value/"key": "value" 형태에서 값만 마스킹 ──────
_SENSITIVE_FIELD_NAMES: tuple[str, ...] = (
    "student_text",
    "student_solution",
    "student_input",
    "student_answer",
    "solution_text",
    "dialogue_content",
    "handwriting_uri",
    "ocr_result",
    "ocr_text",
    "answer_text",
    "chat_text",
    "message_text",
    "image_analysis",
)
_FIELD_PATTERN = re.compile(
    r"\b(?P<key>" + "|".join(re.escape(name) for name in _SENSITIVE_FIELD_NAMES) + r")"
    r'(?P<sep>"?\s*[:=]\s*)'
    r"(?P<value>\"[^\"]*\"|'[^']*'|\S+)",
    _ASCII,
)


def _mask_field(match: re.Match[str]) -> str:
    value = match.group("value")
    is_quoted = value[:1] in ('"', "'") and value[-1:] == value[:1] and len(value) >= 2
    quote = value[0] if is_quoted else ""
    return f"{match.group('key')}{match.group('sep')}{quote}{_MASK}{quote}"


def scrub_text(text: str) -> str:
    """문자열 1건에서 시크릿·PII 후보를 마스킹한 결과를 돌려준다(순수 함수 — 필터·테스트 공용).

    호출자는 항상 `record.getMessage()`처럼 *이미 렌더된* 최종 문자열을 넘긴다 — `%s` 자리
    표시자 자체(포맷 문자열)는 마스킹 대상이 아니다(그건 시크릿이 아니라 코드다).
    """
    masked = text
    for pattern in _SIMPLE_SECRET_PATTERNS:
        masked = pattern.sub(_MASK, masked)
    masked = _ENV_SECRET_PATTERN.sub(_mask_env_secret, masked)
    masked = _FIELD_PATTERN.sub(_mask_field, masked)
    return masked


class PiiSecretScrubberFilter(logging.Filter):
    """루트 로거에 배선되는 로그 스크러버 — 메시지 본문만 검사, 예외 타입명·트레이스백은 무손상.

    `logging.Filter.filter`는 표준 계약상 True/False로 레코드 통과 여부만 결정하지만,
    표준 로깅 문서가 명시적으로 허용하는 관용(레코드를 in-place 변형 후 항상 True 반환 —
    "필터를 로그 레코드 편집에 사용할 수 있다")을 쓴다. 이 필터는 레코드를 **절대 억제하지
    않는다**(가용성 우선 CLAUDE.md #1≫#6 — 로그 자체가 사라지는 것도 관측성 손실이다).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            original = record.getMessage()
        except Exception:  # noqa: BLE001 — 포맷 실패는 이 필터 책임 밖(로깅을 막지 않음)
            return True
        masked = scrub_text(original)
        if masked != original:
            # args를 이미 메시지에 병합했으므로, Formatter가 record.msg를 그대로 쓰도록
            # args를 비운다(재포맷 시도 시 %-치환 불일치로 예외가 나는 것을 방지).
            record.msg = masked
            record.args = ()
        return True


# LogRecord 팩토리에 심은 스크러버를 식별하기 위한 마커 속성명 — 프로세스 내 중복 래핑 방지.
_FACTORY_SCRUBBER_ATTR = "_whymath_pii_secret_scrubber"


def _wrap_record_factory(
    scrubber: PiiSecretScrubberFilter,
) -> Callable[..., logging.LogRecord]:
    """레코드 *생성 시점*에 스크러버를 적용하는 팩토리로 감싼다(모듈 docstring '배선' 절 참조).

    `logging.getLogRecordFactory()`는 기본적으로 `logging.LogRecord` 클래스 자체다 — 이를
    한 겹 감싸 매 레코드 생성 직후 `scrubber.filter(record)`를 호출한다. 어떤 로거·핸들러
    경로를 타든(핸들러 0개→`lastResort` 폴백 포함) 이 시점을 지나야만 레코드가 존재하므로,
    전파 경로의 핸들러 구성과 무관하게 항상 적용된다.
    """
    original_factory = logging.getLogRecordFactory()

    def _factory(*args: object, **kwargs: object) -> logging.LogRecord:
        record = original_factory(*args, **kwargs)
        scrubber.filter(record)
        return record

    setattr(_factory, _FACTORY_SCRUBBER_ATTR, scrubber)
    return _factory


def install_log_scrubber(
    logger: logging.Logger | None = None,
) -> PiiSecretScrubberFilter:
    """스크러버를 프로세스 전역(LogRecord 팩토리) + 지정 로거(기본 루트)에 배선한다.

    이미 배선돼 있으면(현재 팩토리에 마커가 있으면) 재래핑하지 않고 기존 스크러버 인스턴스를
    재사용한다 — `create_app()`이 프로세스 안에서 여러 번 호출돼도(테스트의 `TestClient` 반복
    생성 등) 팩토리가 겹겹이 감싸이거나 로거에 필터가 누적되지 않는다.
    """
    target = logger if logger is not None else logging.getLogger()

    current_factory = logging.getLogRecordFactory()
    existing = getattr(current_factory, _FACTORY_SCRUBBER_ATTR, None)
    if isinstance(existing, PiiSecretScrubberFilter):
        scrubber = existing
    else:
        scrubber = PiiSecretScrubberFilter()
        logging.setLogRecordFactory(_wrap_record_factory(scrubber))

    if not any(isinstance(f, PiiSecretScrubberFilter) for f in target.filters):
        target.addFilter(scrubber)
    return scrubber


__all__ = [
    "CREDENTIAL_SHAPE_PATTERNS",
    "PII_SHAPE_PATTERNS",
    "PiiSecretScrubberFilter",
    "SECRET_LITERAL_PATTERNS",
    "install_log_scrubber",
    "scrub_text",
]
