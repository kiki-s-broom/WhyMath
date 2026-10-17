"""구조화 에러코드 체계 — 학생 대면 API 에러에 **안정된 코드**를 싣는다 (OPS-82).

왜 있는가
---------
예외 클래스 57종이 코드 축 없이 흩어져 있고, API 에러는 `detail` 문자열(한국어 문장)로만
나간다. 문장은 바뀌고 번역되고 변수가 섞이므로 "같은 종류의 실패"를 세려면 문장을 파싱해야
한다 — 서로 다른 실패가 같은 글자로 보이면 실패가 정보가 되지 못한다. 코드는 문장과 독립된
**안정 식별자**다.

`GenerationFailureCode`(F1~F8)와 다른 축이다 (acceptance ②)
------------------------------------------------------------
그쪽은 *콘텐츠* 생성 실패 분류(검증설계서 동결), 이쪽은 *시스템* 에러코드다. 형식도 갈라
충돌이 불가능하다: 여기는 `WM-<계열>-<3자리>`, 그쪽은 `F<숫자>`다.

부여 규칙 (acceptance ⑥ — 범위를 먼저 접는다)
---------------------------------------------
1. 형식 = `WM-<FAMILY>-<NNN>`. FAMILY는 `FAMILIES`의 닫힌 집합, NNN은 계열 내 3자리 일련번호.
2. **안정성 보증**: 한 번 배포된 코드는 의미를 바꾸거나 재사용하지 않는다. 폐기는 레지스트리
   에서 지우지 않고 `deprecated=True`로 표시한다(클라이언트·대시보드가 옛 코드를 계속 만난다).
3. 코드는 **필드값·시크릿을 담지 않는다** — 고정 문자열이다(2026-07-16 langfuse 교훈).
4. 적용 범위 = **신규 예외 + 학생 대면 API 경로**. 기존 57종 전건 소급은 별도 후속이다.
5. 하위 호환: 응답 본문은 종전 `detail`을 그대로 두고 **옆에** `error_code`를 더한다
   (`detail`이 문자열이라고 가정하는 클라이언트를 깨지 않는다).

이 모듈은 stdlib + fastapi만 의존한다 — 어느 라우터에서도 import해도 순환이 없다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from fastapi import HTTPException

__all__ = [
    "CODE_PATTERN",
    "ERROR_CODES",
    "FAMILIES",
    "CodedHTTPException",
    "ErrorCode",
    "UNCLASSIFIED",
    "error_code_of",
]

CODE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^WM-(?P<family>[A-Z]+)-(?P<seq>\d{3})$")
"""코드 형식 — 거버넌스 테스트가 레지스트리 전건과 소스 속 리터럴을 이 패턴으로 잰다."""

FAMILIES: Final[Mapping[str, str]] = {
    "RATE": "호출 빈도 제한",
    "CLIENT": "클라이언트 버전·환경 게이트",
}
"""계열의 닫힌 집합 — 새 계열은 여기에 한 줄 + 의미를 적어야 생긴다(남발 방지)."""

UNCLASSIFIED: Final[str] = "WM-UNCLASSIFIED-000"
"""코드가 아직 없는 예외의 자리표시 — "분류 안 됨"을 *보이게* 하는 값이다(없음과 구분)."""


@dataclass(frozen=True)
class ErrorCode:
    """에러코드 1건의 등록부 항목."""

    code: str
    http_status: int
    retryable: bool
    summary: str
    deprecated: bool = False


def _register(*entries: ErrorCode) -> Mapping[str, ErrorCode]:
    registry: dict[str, ErrorCode] = {}
    for entry in entries:
        match = CODE_PATTERN.match(entry.code)
        if match is None or match.group("family") not in FAMILIES:
            raise ValueError(f"에러코드 형식·계열 위반: {entry.code!r}")
        if entry.code in registry:
            raise ValueError(f"에러코드 중복: {entry.code!r}")
        registry[entry.code] = entry
    return registry


ERROR_CODES: Final[Mapping[str, ErrorCode]] = _register(
    ErrorCode("WM-RATE-001", 429, True, "분당 호출 한도 초과(사용자·IP 차원 공통)"),
    ErrorCode("WM-CLIENT-001", 426, False, "클라이언트 앱 버전이 최소 지원 버전 미만"),
)


class CodedHTTPException(HTTPException):
    """`error_code`를 나르는 HTTPException — app.py 핸들러가 `detail` 옆에 코드를 싣는다."""

    def __init__(
        self,
        code: str,
        *,
        detail: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        entry = ERROR_CODES.get(code)
        if entry is None:
            # 미등록 코드를 조용히 내보내지 않는다 — 개발 시점에 즉시 드러난다.
            raise KeyError(f"미등록 에러코드: {code!r}")
        super().__init__(status_code=entry.http_status, detail=detail, headers=headers)
        self.error_code: str = code


def error_code_of(exc: BaseException) -> str:
    """예외의 에러코드 — 없거나 미등록이면 `UNCLASSIFIED`(= 분류 안 됨을 보이게)."""
    value = getattr(exc, "error_code", None)
    if isinstance(value, str) and value in ERROR_CODES:
        return value
    return UNCLASSIFIED
