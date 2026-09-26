"""운영자 단기 액세스 토큰 발급 *ops CLI* — content_admin 계정 전용(ADMIN-15).

배경
----
관리 콘솔 셸(`GET /v1/admin/menu`)은 **데모가 아닌 실 신원**의 액세스 토큰을 요구한다
(`api/admin_menu.py`가 데모 계정을 403). 그런데 저장소에서 액세스 토큰을 만드는 경로는 OAuth
콜백(`api/auth.py`)과 데모 로그인(`api/demo_auth.py`) 둘뿐이고, 운영자 계정은
`account_bootstrap_cli`로 만들어져 OAuth 로그인 이력이 없다 — 즉 운영자 계정으로 콘솔을 실제로
열어 볼 방법이 없었다(게이트 `G-admin06-browser-menu-call` B단계의 실행 경로 공백). 이 CLI가 그
공백을 메운다(`role_grant_cli`·`account_bootstrap_cli` ops 컨벤션 미러: HTTP 미노출·운영자가 셸에서
직접 실행).

사용법
------
    python -m whymath_backend.ops.operator_token_cli issue <user_id>
    python -m whymath_backend.ops.operator_token_cli issue <user_id> --ttl-minutes 15

PowerShell에서 토큰만 변수로 받기(토큰을 화면·파일에 남기지 않는 형태):

    $Out = python -m whymath_backend.ops.operator_token_cli issue <user_id>
    $Tok = ($Out | ConvertFrom-Json).access_token

**JWT 시크릿은 실행 중인 서버와 같아야 한다.** 토큰은 이 프로세스의 `WHYMATH_JWT_SECRET_KEY`로
서명된다. 서버(uvicorn)가 다른 시크릿으로 떠 있으면 발급은 성공해도 서버는 401을 낸다 — 특히
`scripts/demo/run_demo.ps1`은 실행할 때마다 시크릿을 새로 만들므로, 그 서버에 쓸 토큰이면 그
셸의 시크릿을 그대로 써야 한다. 이 CLI는 서버의 시크릿을 알 방법이 없어 불일치를 검출하지 못한다
(정직한 한계 — 확인은 발급 직후 `GET /v1/admin/menu` 1회로 한다).

발급 대상 거부(비0 종료코드 + 사유 stderr, 발급 0·감사 0)
------------------------------------------------------
  - 존재하지 않는 `user_id` → `OperatorTokenError`(exit 1)
  - 데모 계정(`api/admin_module_registry.is_demo_account`) → `OperatorTokenError`(exit 1).
    콘솔 입구(`admin_menu`)가 막는 신원을 이 CLI가 우회로로 열어 주지 않는다
  - `Role.CONTENT_ADMIN`이 아닌 계정 → `OperatorTokenError`(exit 1). 학생 계정 토큰을 로그인 없이
    찍어 내는 경로가 되지 않게 하는 것이 이 거부의 목적이다
  - 만료가 상한을 넘음 → argparse 단계 거부(exit 2, `--ttl-minutes`는 1~60) 또는 서버 기본 만료
    (`Settings.jwt_expire_minutes`)보다 긺 → exit 1
  - JWT 시크릿 미설정·스키마 프리플라이트 실패 → exit 1(DB 쓰기 전)

만료
----
기본 30분, 상한 60분(`MAX_TTL_MINUTES`). 상한은 서버 기본 만료(24시간)보다 **짧게** 둔다 — OAuth
경로와 달리 이 토큰에는 리프레시 토큰이 딸려 오지 않으므로(재발급 = 이 CLI 재실행 = 감사 1행 더),
만료가 곧 회수 수단이다.

감사(누가·누구에게·언제·만료)
----------------------------
발급 1건마다 `privacy_audit`에 `event_kind=operator_token_issued` 1행을 적재한다
(`privacy/audit.py::record_operator_token_audit`). 순서가 계약이다: **토큰 생성 → 감사 행 add →
커밋 → 커밋이 성공한 뒤에만 토큰 출력**. 커밋이 실패하면 토큰은 stdout에 나가지 않는다 — 흔적
없이 쓸 수 있는 토큰이 나가는 경로가 없다. 토큰 값은 감사 행·로그·stderr 어디에도 쓰지 않고
stdout JSON 한 곳에만 낸다.

  - 누구에게 = `user_id`(토큰 `sub`) / 언제 = `occurred_at`(토큰 `iat`과 같은 값으로 명시)
  - 만료 = `token_expires_at`(토큰 `exp`) / 누가 = `issued_by`(셸 로그인 이름, `--by`로 덮어쓰기)

DB 왕복(`_default_issue_fn`·`_default_preflight_fn`)은 실 PostgreSQL을 요구하므로 단위테스트는
주입 좌석으로 CLI 배선만 hermetic 검증하고, 거부 3종·감사 행 조립은 `issue_operator_token`을
FakeSession으로 직접 검증한다. 실 DB 왕복(감사 행 실제 적재·발급 토큰으로 메뉴 200)은
`test_operator_token_cli_integration.py`(`@pytest.mark.integration`)가 검증한다.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import re
import sys
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.api.admin_module_registry import is_demo_account
from whymath_backend.config import Settings, get_settings
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import dispose_engine, get_sessionmaker
from whymath_backend.privacy.audit import record_operator_token_audit
from whymath_backend.schema.enums import Role
from whymath_backend.security import create_access_token

__all__ = [
    "DEFAULT_TTL_MINUTES",
    "MAX_TTL_MINUTES",
    "IssueFn",
    "IssuedToken",
    "OperatorTokenError",
    "PreflightFn",
    "SchemaPreflightError",
    "issue_operator_token",
    "judge_schema_readiness",
    "main",
    "validate_issuer",
    "validate_ttl",
]

# 기본·상한 만료(분). 상한은 서버 기본 만료(`Settings.jwt_expire_minutes`, 기본 24시간)보다 짧다 —
# 리프레시 토큰이 없는 발급이라 만료가 곧 회수 수단이다(모듈 docstring "만료" 참조).
DEFAULT_TTL_MINUTES = 30
MAX_TTL_MINUTES = 60

# 발급 대상으로 허용하는 유일한 역할. 콘솔(`admin_menu`)을 열어 볼 이유가 있는 역할만 허용한다.
_ALLOWED_ROLE = Role.CONTENT_ADMIN

# `issued_by` 형식 — 셸 로그인 *식별자*만 받는다(자유서술 금지 — `PrivacyAudit`의 "자유텍스트
# 필드 없음" 불변식을 이 컬럼이 깨지 않게 하는 장치). `\w`는 유니코드라 한글 Windows 계정명도
# 통과하고, 공백·줄바꿈·문장부호 산문은 거부된다. 역슬래시는 `DOMAIN\user` 형태 때문에 허용한다.
_ISSUER_PATTERN = re.compile(r"^[\w.@\\-]{1,64}$")

# 이 CLI가 실제로 읽고 쓰는 컬럼 — 프리플라이트가 *직접* 실재를 확인하는 대상이다.
_REQUIRED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("user_profile", "role"),
    ("user_profile", "email_hash"),
    ("privacy_audit", "token_expires_at"),
    ("privacy_audit", "issued_by"),
)


class OperatorTokenError(Exception):
    """발급 거부 사유 — 사용자 없음·데모 계정·허용 역할 아님·만료 상한 초과·JWT 미설정."""


class SchemaPreflightError(Exception):
    """DB 스키마가 이 코드와 맞지 않아 실행할 수 없는 상태(`role_grant_cli` 동명 예외와 같은 취지).

    이 CLI는 ADMIN-15 마이그레이션(`8c19e8a611e4`)이 추가한 `privacy_audit` 2컬럼에 쓴다 —
    그 마이그레이션이 적용되지 않은 DB에서 돌리면 raw 트레이스백 대신 한 줄의 행동 지시를 낸다.
    """


@dataclass(frozen=True)
class IssuedToken:
    """발급 결과 — 토큰과 그 토큰의 `iat`/`exp`(감사 행과 같은 값)."""

    user_id: uuid.UUID
    access_token: str
    issued_at: datetime
    expires_at: datetime


# 발급 좌석 — 기본은 실 DB(단일 TX·커밋), 테스트는 합성 함수를 주입해 DB 없이 CLI 배선(인자
# 파싱·거부 경로·JSON 직렬화·종료 코드)을 검증한다(`role_grant_cli.GrantFn` 미러).
IssueFn = Callable[[uuid.UUID, int, str], Coroutine[Any, Any, IssuedToken]]
PreflightFn = Callable[[], Coroutine[Any, Any, None]]


def validate_ttl(ttl_minutes: int, *, settings: Settings) -> None:
    """만료가 상한 안인가(순수). 위반이면 `OperatorTokenError`.

    argparse가 1~`MAX_TTL_MINUTES`를 먼저 거르지만, 함수 호출 경로(테스트·다른 호출자)에서도
    같은 상한이 걸리도록 여기서 다시 판정한다. 서버 기본 만료보다 긴 값도 거부한다 — 운영자
    토큰이 정규 로그인 토큰보다 오래 사는 역전을 막는다.
    """
    if ttl_minutes < 1 or ttl_minutes > MAX_TTL_MINUTES:
        raise OperatorTokenError(
            f"만료는 1~{MAX_TTL_MINUTES}분이어야 합니다(요청: {ttl_minutes}분)."
        )
    if ttl_minutes > settings.jwt_expire_minutes:
        raise OperatorTokenError(
            f"만료({ttl_minutes}분)가 서버 기본 액세스 토큰 만료"
            f"({settings.jwt_expire_minutes}분)보다 깁니다 — 운영자 토큰은 정규 로그인 토큰보다 "
            "짧아야 합니다."
        )


def validate_issuer(value: str) -> str:
    """`issued_by` 형식 검사(순수) — 식별자만 통과. 위반이면 `OperatorTokenError`."""
    candidate = value.strip()
    if not _ISSUER_PATTERN.fullmatch(candidate):
        raise OperatorTokenError(
            f"발급자 식별자 형식이 아닙니다: {value!r} — 영문·숫자·한글·`._@-\\` 1~64자만 "
            "허용합니다(`--by`로 지정)."
        )
    return candidate


async def issue_operator_token(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    ttl_minutes: int,
    issued_by: str,
    settings: Settings,
) -> IssuedToken:
    """대상 검증 → 토큰 생성 → 감사 1행 `session.add()`. **commit은 호출자**.

    거부 순서: 만료 상한 → JWT 설정 → 사용자 존재 → 데모 계정 → 역할. 전부 토큰을 만들기
    *전*이라 거부 시 토큰도 감사 행도 생기지 않는다(발급 0). 감사 행의 시각은 토큰 클레임에서
    읽는다 — 토큰과 감사가 같은 사건을 서로 다른 시각으로 적지 않게 한다.
    """
    validate_ttl(ttl_minutes, settings=settings)
    issuer = validate_issuer(issued_by)
    if not settings.jwt_configured:
        raise OperatorTokenError(
            "JWT 시크릿(WHYMATH_JWT_SECRET_KEY)이 설정되지 않았습니다 — 실행 중인 서버와 같은 "
            "값을 이 셸에 설정한 뒤 다시 실행하세요."
        )

    user = await session.get(UserProfile, user_id)
    if user is None:
        raise OperatorTokenError(f"사용자를 찾을 수 없습니다: {user_id}")
    if is_demo_account(user):
        raise OperatorTokenError(
            f"데모 계정에는 발급하지 않습니다: {user_id} — 관리 콘솔은 실 신원만 허용합니다."
        )
    if user.role != _ALLOWED_ROLE:
        raise OperatorTokenError(
            f"{_ALLOWED_ROLE.value} 계정에만 발급합니다(대상 역할: {user.role.value}) — 좌석은 "
            "`role_grant_cli grant`로 먼저 부여하세요."
        )

    token = create_access_token(
        user_id, settings=settings, expires_delta=timedelta(minutes=ttl_minutes)
    )
    # 서명은 방금 우리가 했으므로 검증 없이 클레임만 읽는다 — 감사 시각의 출처를 토큰 자체로 둔다.
    claims = jwt.get_unverified_claims(token)
    issued_at = datetime.fromtimestamp(int(claims["iat"]), tz=UTC)
    expires_at = datetime.fromtimestamp(int(claims["exp"]), tz=UTC)

    record_operator_token_audit(
        session,
        user_id=user_id,
        issued_at=issued_at,
        expires_at=expires_at,
        issued_by=issuer,
    )
    return IssuedToken(
        user_id=user_id, access_token=token, issued_at=issued_at, expires_at=expires_at
    )


async def _default_issue_fn(  # pragma: no cover — 실 DB(integration)
    user_id: uuid.UUID, ttl_minutes: int, issued_by: str
) -> IssuedToken:
    """기본 발급 — 검증·토큰 생성·감사 add를 한 세션에서 하고 커밋.

    커밋이 실패하면 예외가 전파되고 토큰은 반환되지 않는다(감사 없는 발급 0).
    """
    settings = get_settings()
    async with get_sessionmaker()() as session:
        issued = await issue_operator_token(
            session,
            user_id=user_id,
            ttl_minutes=ttl_minutes,
            issued_by=issued_by,
            settings=settings,
        )
        await session.commit()
    return issued


def judge_schema_readiness(missing: tuple[str, ...] | list[str]) -> str | None:
    """스키마 준비 판정(순수 — DB 무관). 문제 없으면 `None`.

    판정의 정본은 `alembic_version`이 아니라 컬럼의 실재다(`role_grant_cli.judge_schema_readiness`
    동일 교훈 — 버전 테이블에는 무엇이든 적혀 있을 수 있다).
    """
    missing_cols = tuple(missing)
    if not missing_cols:
        return None
    return (
        f"DB에 필요한 컬럼이 없습니다: {', '.join(missing_cols)} — 이 CLI가 그 컬럼을 읽고 씁니다. "
        "먼저 `alembic upgrade head`를 적용하세요(대상 DB가 맞는지 `alembic current`로 먼저 "
        "대조할 것)."
    )


async def _default_preflight_fn() -> None:  # pragma: no cover — 실 DB
    """이 CLI가 쓰는 컬럼의 실재를 실행 *전에* 확인한다(확인 실패를 통과로 위장하지 않는다).

    `finally: dispose_engine()` — `main()`이 프리플라이트와 본 명령을 서로 다른 `asyncio.run()`
    으로 돌리므로 풀을 살려 두면 다음 루프가 "attached to a different loop"로 죽는다
    (`role_grant_cli` 2026-08-11 실측).
    """
    from sqlalchemy import text

    try:
        async with get_sessionmaker()() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT table_name, column_name FROM information_schema.columns "
                        "WHERE table_name IN ('user_profile', 'privacy_audit')"
                    )
                )
            ).all()
            present = {(str(t), str(c)) for t, c in rows}
    except Exception as exc:
        raise SchemaPreflightError(
            f"DB 스키마를 확인하지 못했습니다({type(exc).__name__}) — "
            "DB 도달성(WHYMATH_DATABASE_URL)과 접근 권한을 확인하세요."
        ) from exc
    finally:
        await dispose_engine()

    missing = tuple(f"{t}.{c}" for t, c in _REQUIRED_COLUMNS if (t, c) not in present)
    message = judge_schema_readiness(missing)
    if message is not None:
        raise SchemaPreflightError(message)


def _default_issuer() -> str | None:
    """셸 로그인 이름. 알아낼 수 없으면 None(→ `--by` 필수 안내)."""
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 — getpass는 환경에 따라 OSError·KeyError 등을 낸다
        return None


def _uuid_arg(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"올바른 UUID가 아닙니다: {value!r}") from exc


def _ttl_arg(value: str) -> int:
    try:
        minutes = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"정수 분이 아닙니다: {value!r}") from exc
    if minutes < 1 or minutes > MAX_TTL_MINUTES:
        raise argparse.ArgumentTypeError(
            f"만료는 1~{MAX_TTL_MINUTES}분이어야 합니다(요청: {minutes}분)."
        )
    return minutes


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.ops.operator_token_cli",
        description=(
            "운영자(content_admin) 계정에 단기 액세스 토큰 발급 — HTTP 미노출, 운영자 직접 실행. "
            "발급마다 privacy_audit 감사 1행."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    issue_p = sub.add_parser("issue", help="지정 운영자 계정에 단기 액세스 토큰을 발급한다.")
    issue_p.add_argument("user_id", type=_uuid_arg, help="대상 사용자 UUID(content_admin)")
    issue_p.add_argument(
        "--ttl-minutes",
        type=_ttl_arg,
        default=DEFAULT_TTL_MINUTES,
        help=f"만료(분) — 기본 {DEFAULT_TTL_MINUTES}, 상한 {MAX_TTL_MINUTES}",
    )
    issue_p.add_argument(
        "--by",
        default=None,
        help="발급자 식별자(감사 행 issued_by) — 생략 시 셸 로그인 이름",
    )
    return parser


def main(
    argv: list[str] | None = None,
    *,
    issue_fn: IssueFn = _default_issue_fn,
    preflight_fn: PreflightFn = _default_preflight_fn,
    issuer_fn: Callable[[], str | None] = _default_issuer,
) -> int:
    """CLI 엔트리 — issue 서브커맨드. 결과 JSON은 stdout(토큰 포함 — 이 한 곳에만), 거부는 stderr.

    반환 종료 코드: 0(발급 성공·감사 커밋 완료) / 1(런타임 거부 — 프리플라이트·사용자 없음·데모·
    역할·만료·JWT 미설정·그 밖의 DB 오류) / 2(argparse 파싱 실패 — 잘못된 UUID·만료 범위 밖).
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    def _fail(message: str) -> int:
        print(json.dumps({"error": message}, ensure_ascii=False), file=sys.stderr)
        return 1

    issuer_raw = args.by if args.by is not None else issuer_fn()
    if issuer_raw is None:
        return _fail(
            "셸 로그인 이름을 알아내지 못했습니다 — `--by <식별자>`로 발급자를 지정하세요."
        )
    try:
        issuer = validate_issuer(issuer_raw)
    except OperatorTokenError as exc:
        return _fail(str(exc))

    try:
        asyncio.run(preflight_fn())
    except SchemaPreflightError as exc:
        return _fail(str(exc))

    try:
        issued = asyncio.run(issue_fn(args.user_id, args.ttl_minutes, issuer))
    except OperatorTokenError as exc:
        return _fail(str(exc))
    except Exception as exc:  # noqa: BLE001 — 침묵 실패 금지: 타입명을 남기고 종료 코드로 판정
        # 이 지점의 예외(커밋 실패 등)에는 토큰이 실리지 않는다 — 토큰은 반환값으로만 나온다.
        return _fail(f"실행 실패({type(exc).__name__}): {exc}")

    print(
        json.dumps(
            {
                "user_id": str(issued.user_id),
                "access_token": issued.access_token,
                "token_type": "bearer",
                "issued_at": issued.issued_at.isoformat(),
                "expires_at": issued.expires_at.isoformat(),
                "issued_by": issuer,
            }
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트, main이 테스트 대상
    sys.exit(main())
