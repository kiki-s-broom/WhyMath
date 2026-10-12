"""오개념 카탈로그 코퍼스 → backend 적재 CLI — `whymath_backend.l1.misconception.populate`.

#290이 커밋한 코퍼스(`data/corpus/misconceptions_v1/misconceptions.json`·Collection JSON·839
레코드)를 backend 영속 `misconception_catalog` 테이블에 멱등 적재한다. `l1/standards/populate`
(성취기준 적재 CLI)의 오개념 짝이며 같은 CLI 골격을 따른다(argparse·`main(argv)->int`·파일 부재
`return 2`·stdout 행수 보고). 오개념은 임베딩·pgvector와 무관(순수 RDB sync 적재)하므로
vector_store 게이트가 없다(성취기준 CLI와 동일).

적재 로직 0(얇은 래퍼): `load_misconceptions`(catalog_loader)가 Collection 파싱·멱등 upsert를
담당한다. 본 CLI는 경로 결선·실행·보고만 한다.

사용:
    python -m whymath_backend.l1.misconception.populate \\
        --misconceptions data/corpus/misconceptions_v1/misconceptions.json
"""

from __future__ import annotations

import argparse
from pathlib import Path

from whymath_backend.db.cms_edit_marker import add_overwrite_argument, conflict_summary
from whymath_backend.l1.misconception.catalog_loader import load_misconceptions

# 코퍼스 기본 경로(#290 산출 관례).
_DEFAULT_MISCONCEPTIONS = Path("data/corpus/misconceptions_v1/misconceptions.json")


def main(argv: list[str] | None = None) -> int:
    """오개념 Collection JSON을 `misconception_catalog`에 멱등 적재하고 행 수를 보고(CLI 본체).

    반환은 프로세스 종료 코드(0=성공·2=입력 파일 부재). 적재 로직은 `load_misconceptions`가 담당하며
    본 함수는 경로 결선·실행·stdout 보고만 한다(조용한 무동작 금지 — 부재 시 명확히 보고).
    """
    parser = argparse.ArgumentParser(
        prog="whymath-misconception-populate",
        description=(
            "오개념 카탈로그 코퍼스(Collection JSON) → backend misconception_catalog "
            "멱등 적재(mis_id PK 충돌 upsert)."
        ),
    )
    parser.add_argument(
        "--misconceptions",
        type=Path,
        default=_DEFAULT_MISCONCEPTIONS,
        help=f"오개념 Collection JSON 경로(기본 {_DEFAULT_MISCONCEPTIONS}).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="상세 출력(현재는 표준 보고만 — 호환 자리표시).",
    )
    add_overwrite_argument(parser)
    args = parser.parse_args(argv)

    path: Path = args.misconceptions
    if not path.exists():
        print(f"오개념 Collection 없음: {path} — 코퍼스 생성기로 먼저 생성하세요.")
        return 2

    conflicts: list[str] = []
    count = load_misconceptions(
        None, path, overwrite_cms_edits=args.overwrite_cms_edits, conflicts=conflicts
    )
    print(f"오개념 적재 완료: {count}건 (src={path}).")
    if conflicts:
        print(conflict_summary(conflicts))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI 진입
    raise SystemExit(main())
