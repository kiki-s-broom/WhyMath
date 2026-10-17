"""적재 전 외래키 대상 사전확인 — 쓰기 전에, 읽기만으로, 누락 키를 **전건** 열거한다 (HARN-302).

**왜 필요한가** (정본 사고 2026-10-07 G-misc40 DB 동기화): 크로스링크 68건 적재가 첫 행에서
`ForeignKeyViolation`(`M0864`이 `misconception_catalog`에 없음)으로 실패했다. DB는 한 트랜잭션이라
전체를 롤백해 데이터는 지켰지만, 오류가 **첫 행의 키 하나만** 말하므로 "고치고 다시 돌리면
다음 키에서 또 실패"를 누락 키 수만큼 반복하게 된다. 이 모듈은 쓰기 전에 참조 대상의 존재를
한 번에 확인해 누락 키를 전부 말하고 **아무것도 쓰지 않은 채** 거부한다.

**왜 가드(채팅 블록 검사)가 아니라 쓰기 도구 안인가** (판정 문서 =
`docs/reviews/harn302_fk_target_precheck_judgment_2026-10-07.md`): 누락 여부는 *데이터 값*
(적재 파일의 `mis_id`들)과 *라이브 DB 내용*의 교집합이다. 블록 텍스트에는 둘 다 없다 — 블록은
`promote --load`처럼 CLI 이름만 부르고, 어느 테이블이 어느 외래키를 갖는지는 ORM 메타데이터에만
있다. 텍스트 정규식이 알 수 없는 것을 아는 척하면 오탐/미탐 어느 쪽이든 "보호 있음"의 위장이
된다. 값과 DB를 둘 다 쥔 것은 쓰기 도구뿐이다.

**한계(정직 기술)**:
  · 확인과 쓰기는 **다른 트랜잭션**이다. 확인 뒤 쓰기 전에 참조 대상이 지워지면 DB의 외래키 제약이
    마지막 방어선으로 작동한다(실패는 하되 데이터는 지켜진다) — 이 모듈은 DB 제약을 대체하지 않고
    앞당긴다.
  · 단일 컬럼 외래키만 다룬다. 복합 외래키는 **조용히 건너뛰지 않고** `NotImplementedError`로 멈춘다
    (확인하지 않은 것을 확인한 것으로 보고하지 않는다).
  · 이 모듈은 존재만 본다. 적재가 *얼마나 바꾸는지*(신규/변경 건수)는 HARN-215의 범위다.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlalchemy as sa

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

# IN 절 한 번에 보낼 값 수 — 드라이버별 바인드 파라미터 상한(SQLite 구판 999)보다 작게.
_CHUNK = 500


@dataclass(frozen=True)
class MissingFkTargets:
    """외래키 하나(`child.col → parent.col`)에서 참조 대상이 없는 값 전부."""

    constraint: str  # "misconception_crosslink.mis_id -> misconception_catalog.mis_id"
    values: tuple[str, ...]  # 정렬된 누락 값(중복 제거)


class ForeignKeyTargetMissingError(Exception):
    """적재 전 사전확인이 참조 대상 누락을 발견했다 — 아무것도 쓰지 않았다.

    `missing`에 외래키별 누락 값 **전건**이 있다. 메시지도 전건을 싣는다(일부만 보여 주면 사람이
    고치고 다시 돌려 다음 키에서 또 걸린다 — 이 검사가 없애려는 바로 그 반복이다).
    """

    def __init__(self, missing: list[MissingFkTargets]) -> None:
        self.missing = missing
        total = sum(len(m.values) for m in missing)
        lines = [f"외래키 대상 누락 {total}건 — 아무것도 쓰지 않았습니다:"]
        for item in missing:
            lines.append(f"  · {item.constraint}: {len(item.values)}건")
            lines.extend(f"      - {value}" for value in item.values)
        super().__init__("\n".join(lines))


def missing_fk_targets(
    conn: Connection,
    table: sa.Table,
    rows: Iterable[Mapping[str, object]],
) -> list[MissingFkTargets]:
    """`rows`가 `table`에 적재될 때 외래키 대상이 없는 값을 외래키별로 전부 센다 (읽기 전용).

    각 외래키 컬럼의 비어 있지 않은(`None` 제외) 값만 본다 — NULL은 외래키가 검사하지 않는다.
    반환이 빈 리스트면 *확인한 모든 외래키*의 대상이 존재한다는 뜻이다.

    Raises:
        NotImplementedError: 복합 외래키(여러 컬럼) — 지원하지 않으므로 건너뛰지 않고 멈춘다.
    """
    materialized = list(rows)
    result: list[MissingFkTargets] = []
    for constraint in sorted(table.foreign_key_constraints, key=lambda c: str(c.name or c)):
        if len(constraint.elements) != 1:
            raise NotImplementedError(
                f"{table.name}: 복합 외래키 {constraint.name!r}는 사전확인을 지원하지 않는다 "
                "(건너뛰면 확인하지 않은 것을 확인한 것으로 보고하게 된다)"
            )
        fk = constraint.elements[0]
        child_col, parent_col = fk.parent, fk.column
        wanted = {
            str(row[child_col.name]) for row in materialized if row.get(child_col.name) is not None
        }
        if not wanted:
            continue
        found: set[str] = set()
        ordered = sorted(wanted)
        for start in range(0, len(ordered), _CHUNK):
            chunk = ordered[start : start + _CHUNK]
            stmt = sa.select(parent_col).where(parent_col.in_(chunk))
            found.update(str(v) for v in conn.execute(stmt).scalars().all())
        absent = tuple(sorted(wanted - found))
        if absent:
            label = f"{table.name}.{child_col.name} -> {parent_col.table.name}.{parent_col.name}"
            result.append(MissingFkTargets(label, absent))
    return result


__all__ = [
    "ForeignKeyTargetMissingError",
    "MissingFkTargets",
    "missing_fk_targets",
]
