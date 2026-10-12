"""CMS 편집 표지 — 사람이 CMS로 고친 행을 CLI 적재가 덮어쓰지 못하게 하는 단일 규약 (P3-25).

왜 필요한가
-----------
관리자 CMS(`api/admin_cms.py`)의 제자리 편집은 DB 행만 바꾼다. 같은 행의 원천 정본은 파일 코퍼스
(`data/corpus/*`)이고, `populate` CLI들이 그 정본을 키 충돌 upsert(`ON CONFLICT DO UPDATE`)로 DB에
투영한다. 즉 **CMS 편집 → 다음 적재 = 편집 소실**이다. 예외도 알림도 없이 사라진다(P3-12 사후 대조표
`docs/reviews/p3_12_cms_12_survey_2026-10-08.md` §6).

규약 (계약 정본: `docs/standards/cms_edit_vs_loader_contract.md`)
----------------------------------------------------------------
- 덮어쓰기 위험이 실측된 5개 테이블에 `cms_edited_at TIMESTAMPTZ NULL` 컬럼을 둔다. `NULL`=사람이
  고친 적 없음(적재가 소유), 값 있음=CMS가 마지막으로 고친 시각(사람이 소유).
- **사람이 쓰면 표지를 채운다**(`mark_cms_edited`) — CMS 편집(`PATCH`)·검수 표시
  (`POST .../review`)와 문항의 기존 관리자 경로(`PATCH /v1/problems`·검수 큐 전이) 모두.
- **적재는 표지가 있는 행을 건너뛰고 충돌로 보고한다**(`ON CONFLICT DO UPDATE ... WHERE
  cms_edited_at IS NULL`). 조용히 덮지도, 조용히 버리지도 않는다.
- 덮어쓰기는 운영자가 `--overwrite-cms-edits`를 줄 때만 일어나며, 그때 표지를 비운다(적재가 다시
  소유). 이것이 표지를 푸는 유일한 길이다.

풀이 단계(`problem_step`)·교육과정 판(`curriculum_version`)에는 표지를 두지 않는다 — 두 테이블은
CLI 적재가 같은 행을 갱신하는 경로가 없다(풀이 단계는 좌석이 빈 문제에만 insert, 교육과정 판은
alembic 시드 1회 `ON CONFLICT DO NOTHING`). 실측 근거는 계약 문서 §2.

이 모듈은 L1~L5가 모두 import하는 db 계층 어휘다(수학 로직 0).
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from typing import Any, Final

#: 표지 컬럼 이름 — ORM 모델 5종과 마이그레이션이 같은 글자를 쓴다(회귀 테스트가 대조).
CMS_EDIT_MARKER: Final[str] = "cms_edited_at"

#: 표지를 두는 테이블 — CLI 적재가 같은 행을 upsert하는 것이 실측된 5종.
#: 새 적재 경로가 생기는 CMS 편집 리소스는 여기에 더하고 ORM·마이그레이션·적재기를 함께 고친다.
CMS_PROTECTED_TABLES: Final[frozenset[str]] = frozenset(
    {
        "problem",
        "misconception_catalog",
        "strategy_node",
        "concept_content",
        "hints",
    }
)

#: 적재 CLI의 덮어쓰기 옵션 이름 — 5개 CLI가 같은 글자를 쓴다.
OVERWRITE_FLAG: Final[str] = "--overwrite-cms-edits"


def now_utc() -> datetime:
    """표지에 쓰는 시각 — 항상 tz-aware UTC."""
    return datetime.now(tz=UTC)


def mark_cms_edited(row: Any, *, at: datetime | None = None) -> None:
    """사람이 쓴 행에 표지를 채운다. 표지 컬럼이 없는 모델이면 `AttributeError`.

    `setattr`만 하면 컬럼이 없는 객체에도 평범한 파이썬 속성이 조용히 생긴다(DB에는 아무것도
    안 써지는데 호출은 성공한다) — 그래서 클래스에 컬럼이 있는지 먼저 본다.
    """
    if not hasattr(type(row), CMS_EDIT_MARKER):
        raise AttributeError(f"{type(row).__name__}에 {CMS_EDIT_MARKER} 컬럼이 없다")
    setattr(row, CMS_EDIT_MARKER, at if at is not None else now_utc())


def upsert_guard(model: Any, *, overwrite: bool) -> tuple[Any, dict[str, None]]:
    """적재 upsert의 보호 조각 `(where, 추가 set_)`를 돌려준다 — 5개 적재기가 같은 모양을 쓴다.

    - 보호 모드(기본): `where = <표지> IS NULL`. 표지가 있는 행은 `DO UPDATE`가 일어나지 않는다
      (INSERT 충돌 시 행을 건드리지 않고 영향 행 0).
    - 덮어쓰기 모드(`--overwrite-cms-edits`): `where = None`, 추가 set_으로 표지를 비운다(적재가
      다시 그 행을 소유한다 — 표지를 푸는 유일한 길).
    """
    if overwrite:
        return None, {CMS_EDIT_MARKER: None}
    return getattr(model, CMS_EDIT_MARKER).is_(None), {}


def upsert_skipped(result: Any) -> bool:
    """`INSERT ... ON CONFLICT DO UPDATE ... WHERE ... RETURNING <pk>` 결과가 "건너뜀"인지 판정한다.

    적재 문장은 반드시 `.returning(<기본키>)`를 달아야 한다: 삽입·갱신된 행은 키를 돌려주고,
    보호(`WHERE cms_edited_at IS NULL`)로 건너뛴 행은 **결과가 비어 있다**. 영향 행 수
    (`rowcount`)는 쓰지 않는다 — 실 PG(psycopg3)에서 `INSERT ... ON CONFLICT`의 `rowcount`는
    갱신·건너뜀과 무관하게 **항상 -1**이라 변별력이 0이다(2026-10-09 실측: 삽입·갱신·건너뜀 셋 모두
    -1). 처음 설계(`rowcount == 0`)는 가짜 엔진에서만 통과했고 실 DB에서 예외로 터졌다.
    """
    return bool(result.first() is None)


def add_overwrite_argument(parser: argparse.ArgumentParser) -> None:
    """적재 CLI 5종이 같은 글자·같은 의미의 덮어쓰기 옵션을 갖게 한다(dest=overwrite_cms_edits)."""
    parser.add_argument(
        OVERWRITE_FLAG,
        dest="overwrite_cms_edits",
        action="store_true",
        help=(
            "CMS로 고친 행도 코퍼스 값으로 덮어쓴다(편집 소실을 감수 — 기본은 건너뛰고 충돌 보고). "
            "덮어쓴 행은 CMS 편집 표지가 비워져 다시 적재가 소유한다."
        ),
    )


def format_conflict(table: str, key: object) -> str:
    """적재가 건너뛴 CMS 편집 행 1건의 보고 문자열 — `테이블:키`. 값(본문)은 싣지 않는다."""
    return f"{table}:{key}"


def conflict_summary(conflicts: list[str]) -> str:
    """CLI가 stdout에 내는 충돌 요약. 0건이면 빈 문자열(소음 금지)."""
    if not conflicts:
        return ""
    head = ", ".join(conflicts[:10])
    more = f" 외 {len(conflicts) - 10}건" if len(conflicts) > 10 else ""
    return (
        f"CMS 편집 보호로 건너뜀: {len(conflicts)}건 [{head}{more}] — "
        f"덮어쓰려면 {OVERWRITE_FLAG}(편집 소실을 감수)."
    )


__all__ = [
    "CMS_EDIT_MARKER",
    "CMS_PROTECTED_TABLES",
    "OVERWRITE_FLAG",
    "add_overwrite_argument",
    "conflict_summary",
    "format_conflict",
    "mark_cms_edited",
    "now_utc",
    "upsert_guard",
    "upsert_skipped",
]
