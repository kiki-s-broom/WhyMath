"""`Role` enum 동결 테스트 — SEC-07 D1 · P3-12.

멤버 집합과 서열 비교 부재를 동결한다. `docs/architecture/account_security_gap_review.md`
§2-①이 반증하듯(`docs/legal/pipa_data_matrix.md:33-47` — 부모의 데이터 가시성은 학생 본인의
*부분집합*이지 상위집합이 아님) 7단 선형 서열은 이 앱의 데이터 모델과 구조적으로 모순된다. 이
테스트는 미래 세션이 그 서열을 조용히 되살리지 못하도록 멤버 집합과 비교 연산 부재를 고정한다.

멤버 수는 v0 2값에서 P3-12가 **5값**(CMS 편집자·검수자·배포자 추가)으로 넓혔다. 늘어난 3값은
좌석(`api/admin_cms.py`)이 있어 "좌석 없는 역할 금지" 방침과 충돌하지 않는다. PARENT/TEACHER/
SCHOOL_ADMIN은 여전히 없다 — 그 부재가 아래 `test_deferred_roles_stay_absent`로 동결돼 있다.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from enum import Enum, IntEnum
from pathlib import Path

import pytest

from whymath_backend.schema.enums import Role

_MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "backend"
    / "alembic"
    / "versions"
    / "20261008_1200_c5e9f3a7b1d4_cms_content_roles.py"
)

_EXPECTED = {
    "student",
    "content_admin",
    "content_editor",
    "content_reviewer",
    "content_publisher",
}


class TestExactMemberSet:
    def test_role_has_exactly_five_members(self) -> None:
        """P3-12 확정 — 학생 1 + 콘텐츠 운영 4(관리자·편집자·검수자·배포자)."""
        assert len(list(Role)) == 5

    def test_role_members_are_the_frozen_set(self) -> None:
        assert {member.value for member in Role} == _EXPECTED
        assert Role.STUDENT.value == "student"
        assert Role.CONTENT_ADMIN.value == "content_admin"
        assert Role.CONTENT_EDITOR.value == "content_editor"
        assert Role.CONTENT_REVIEWER.value == "content_reviewer"
        assert Role.CONTENT_PUBLISHER.value == "content_publisher"

    def test_deferred_roles_stay_absent(self) -> None:
        """좌석 없는 역할은 여전히 만들지 않는다 — 학부모·교사·학교관리자는 B2B/대시보드 계약 전까지 부재."""
        names = {member.name for member in Role}
        assert not names & {"PARENT", "TEACHER", "SCHOOL_ADMIN", "SYSTEM_ADMIN"}

    def test_migration_adds_exactly_the_new_roles(self) -> None:
        """DB 어휘(`role_enum`)와 코드 어휘가 어긋나지 않는다 — 어긋나면 새 역할 행을 DB가 거부한다.

        마이그레이션의 `ALTER TYPE role_enum ADD VALUE` 라벨 집합이 `Role`에서 원래 2값을 뺀 집합과
        글자 그대로 같아야 한다. 스캔 0건은 통과가 아니다.
        """
        text = _MIGRATION.read_text(encoding="utf-8")
        added = set(re.findall(r"ALTER TYPE role_enum ADD VALUE IF NOT EXISTS '(\w+)'", text))
        assert added, "마이그레이션에서 ADD VALUE 문장을 하나도 찾지 못했다"
        assert added == _EXPECTED - {"student", "content_admin"}


class TestNoOrderingSupport:
    """7단 선형 서열 재도입 방지 — `<`/`>`/`<=`/`>=`가 TypeError를 던져야 한다.

    `Role`은 다른 `schema/enums.py` enum과 달리 `str` mixin을 쓰지 않는다(house style
    이탈은 의도적 — enums.py `Role` docstring 참조). str mixin이면 멤버가 사전식으로
    비교 가능해져(`"content_admin" < "student"`) 서열 연산 자체가 *존재*하게 되고, 값 자체가
    무의미한 사전순이라도 미래 세션이 실수로 등급 비교 코드를 짤 여지를 준다.
    """

    def test_role_is_not_int_enum(self) -> None:
        """IntEnum이면 정의상 서열이 생긴다 — 채택 금지를 타입으로 고정."""
        assert not issubclass(Role, IntEnum)

    def test_role_does_not_mix_in_str(self) -> None:
        """str mixin이면 사전식 비교가 열린다 — Role은 순수 Enum이어야 한다."""
        assert not issubclass(Role, str)
        assert issubclass(Role, Enum)

    @pytest.mark.parametrize(
        "op",
        [
            lambda a, b: a < b,
            lambda a, b: a > b,
            lambda a, b: a <= b,
            lambda a, b: a >= b,
        ],
    )
    def test_comparison_operators_raise_type_error(self, op: Callable[[Role, Role], bool]) -> None:
        with pytest.raises(TypeError):
            op(Role.STUDENT, Role.CONTENT_ADMIN)
