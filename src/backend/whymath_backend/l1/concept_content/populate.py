"""콘텐츠 4종 코퍼스 → backend 적재 CLI — `whymath_backend.l1.concept_content.populate`.

캡처·커밋된 콘텐츠 코퍼스(`data/corpus/concept_content_v1/content.json`·K-12 개념 437 +
`data/corpus/concept_content_university_v1/content.json`·대학 소단원 409)를 backend 영속
`concept_content` 테이블에 멱등 적재한다. `l1/misconception/populate`(오개념 적재 CLI)의 콘텐츠
짝이며 같은 CLI 골격을 따른다(argparse·`main(argv)->int`·파일 부재 `return 2`·stdout 행수 보고).
콘텐츠는 임베딩·pgvector와 무관(순수 RDB sync 적재)하므로 vector_store 게이트가 없다.

적재 로직 0(얇은 래퍼): `load_concept_content_from_json`/`populate_concept_content`(projection)이
파싱·멱등 upsert를 담당한다. 본 CLI는 경로 결선·scope 주입·실행·보고만 한다.

사용:
    python -m whymath_backend.l1.concept_content.populate \\
        --k12 data/corpus/concept_content_v1/content.json \\
        --university data/corpus/concept_content_university_v1/content.json
"""

from __future__ import annotations

import argparse
from pathlib import Path

from whymath_backend.db.cms_edit_marker import add_overwrite_argument, conflict_summary
from whymath_backend.db.models.concept_content import (
    CONTENT_SCOPE_K12,
    CONTENT_SCOPE_UNIVERSITY,
)
from whymath_backend.l1.concept_content.projection import (
    load_concept_content_from_json,
    populate_concept_content,
)

# 코퍼스 기본 경로(Phase 3 캡처 관례).
_DEFAULT_K12 = Path("data/corpus/concept_content_v1/content.json")
_DEFAULT_UNIVERSITY = Path("data/corpus/concept_content_university_v1/content.json")


def main(argv: list[str] | None = None) -> int:
    """콘텐츠 코퍼스(K-12 + 대학)를 `concept_content`에 멱등 적재하고 행 수를 보고(CLI 본체).

    반환은 프로세스 종료 코드(0=성공·2=입력 파일 부재). 적재 로직은 projection이 담당하며 본 함수는
    경로 결선·scope 주입·실행·stdout 보고만 한다(조용한 무동작 금지 — 부재 시 명확히 보고).
    """
    parser = argparse.ArgumentParser(
        prog="whymath-concept-content-populate",
        description=(
            "콘텐츠 4종 코퍼스(K-12 + 대학 content.json) → backend concept_content "
            "멱등 적재(code PK 충돌 upsert)."
        ),
    )
    parser.add_argument(
        "--k12",
        type=Path,
        default=_DEFAULT_K12,
        help=f"K-12 콘텐츠 content.json 경로(기본 {_DEFAULT_K12}).",
    )
    parser.add_argument(
        "--university",
        type=Path,
        default=_DEFAULT_UNIVERSITY,
        help=f"대학 콘텐츠 content.json 경로(기본 {_DEFAULT_UNIVERSITY}).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="상세 출력(현재는 표준 보고만 — 호환 자리표시).",
    )
    add_overwrite_argument(parser)
    args = parser.parse_args(argv)

    sources: list[tuple[Path, str]] = [
        (args.k12, CONTENT_SCOPE_K12),
        (args.university, CONTENT_SCOPE_UNIVERSITY),
    ]
    for path, _scope in sources:
        if not path.exists():
            print(f"콘텐츠 코퍼스 없음: {path} — 코퍼스 생성기로 먼저 생성하세요.")
            return 2

    total = 0
    conflicts: list[str] = []
    for path, scope in sources:
        records = load_concept_content_from_json(path, scope=scope)
        count = populate_concept_content(
            records, overwrite_cms_edits=args.overwrite_cms_edits, conflicts=conflicts
        )
        total += count
        print(f"콘텐츠 적재: {count}건 (scope={scope}·src={path}).")
    print(f"콘텐츠 적재 완료: 총 {total}건.")
    if conflicts:
        print(conflict_summary(conflicts))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI 진입
    raise SystemExit(main())
