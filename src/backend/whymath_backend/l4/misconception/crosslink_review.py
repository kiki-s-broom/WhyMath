"""오개념 crosswalk 검수 큐 → 승인분 승격·적재 원커맨드 — 슬라이스 M1.

crosswalk(kebab-id ↔ M-id) 행은 **사람 검수 산출물**이다(`schema/misconception_crosslink.py`
상단 주석 정본·MEMORY 2026-06-30) — AI 자기승인·자동 적재 절대 금지. 기계의 몫은 검수를 30분
작업으로 만드는 것: ① 초안(`docs/data/misconception_crosslink_candidates.md` §2)을 전사한 검수 큐
JSON(`docs/data/misconception_crosslink_review_queue.json`)을 사람이 행별로 승인/반려하고,
② 본 모듈이 *승인분만* 로더 형식(`{"crosslinks": [...]}`)으로 승격·적재한다.

안전장치(기존 설계 승계): 후보 도구 출력 top key `"candidates"` ≠ 로더 입력 top key
`"crosslinks"` ≠ 검수 큐 top key `"review_queue"` — 세 형식이 서로 *직접 호환되지 않아* 검수를
건너뛴 자동 적재가 구조적으로 차단된다. `promote_approved`는 오투입(`"candidates"`/`"crosslinks"`)
을 명시적으로 거부한다.

승격 규칙(위반은 `CrosslinkReviewError`로 *전건 열거* — 조용한 누락 금지):
- approved 행은 reviewer·reviewed_on(검수 서명) 필수.
- 직접매핑 승인은 confidence ≥ 0.6 필수(초안 §0.2 — conf<0.6은 인접 오개념·승격 금지).
- 부분매핑·개념겹침은 승인(approved)해도 승격하지 않는다(MISC-63 — 기본 적재 금지).
  예외는 검수 큐에서 link_type을 직접매핑으로 승격하고 confidence ≥ 0.6 기입 후 재서명하는 경로뿐.
- kebab_id는 L4 탐지 카탈로그(`catalog.py::CATALOG_BY_ID`)에 실재해야 한다(전사 왜곡 가드).
- 출력 행은 `schema.MisconceptionCrosslink` 계약 준수·`method="manual"`(채택 주체=사람·초안 §4).

CLI(`crosslink_candidates.py`·`l1/misconception/populate.py` 골격):
    python -m whymath_backend.l4.misconception.crosslink_review promote \\
        --queue docs/data/misconception_crosslink_review_queue.json \\
        [--out approved.json | --load]
`--load`는 기존 `load_crosslinks`(l1/crosslink_loader) 위임. 승인 0건이면 exit 2(조용한 무동작
금지 — populate CLI의 파일 부재 exit 2 규약 미러).
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from whymath_backend.l1.misconception.crosslink_gate import (
    promotion_violations,
    sign,
)
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.schema.misconception_crosslink import (
    CrosslinkType,
    MisconceptionCrosslink,
)

# 검수 큐 top key — 후보 도구("candidates")·로더("crosslinks")와 *일부러* 다르다(오투입 차단).
_QUEUE_KEY = "review_queue"

# 검수 상태 — pending(미검수)·approved(승인)·rejected(반려)·deferred(보류). 런타임 어휘 정본은
# Gate Contract `REVIEW_STATUSES`이고 이 Literal은 타입 별칭(거버넌스 테스트가 둘의 일치를 동결).
ReviewStatus = Literal["pending", "approved", "rejected", "deferred"]


class CrosslinkReviewItem(BaseModel):
    """검수 큐 1행 — 초안 §2 전사 필드 + 검수 서명(status·reviewer·reviewed_on·note).

    `link_type`은 기존 스키마 `CrosslinkType` 재사용(직접매핑/부분매핑/개념겹침).
    `rationale`은 초안 근거 요약(전사 충실성 대조용). extra=forbid로 오탈자 필드를 차단한다.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kebab_id: str = Field(..., description="L4 탐지 카탈로그 id(CATALOG_BY_ID)")
    mis_id: str = Field(..., description="콘텐츠 카탈로그 M-id(예 'M0049')")
    link_type: CrosslinkType = Field(..., description="연결 의미 — 직접매핑/부분매핑/개념겹침")
    confidence: float | None = Field(
        default=None, ge=0.0, le=1.0, description="초안 신뢰도(무표기 대안은 null)"
    )
    rationale: str = Field(..., description="초안 근거 요약(검수 보조)")
    status: ReviewStatus = Field(..., description="검수 상태 — pending/approved/rejected/deferred")
    reviewer: str | None = Field(default=None, description="검수자(승인 시 필수 서명)")
    reviewed_on: date | None = Field(default=None, description="검수일(승인 시 필수 서명)")
    note: str | None = Field(default=None, description="검수 메모(승격 시 서명과 병합)")


class CrosslinkReviewError(ValueError):
    """검수 큐 위반 — 위반 행을 *전건 열거*한 메시지로 실패한다(조용한 누락 금지)."""


def _validate_top_key(queue: dict[str, Any]) -> list[Any]:
    """top key 검사 — `"review_queue"`만 수용, 다른 형식 오투입은 명시 거부."""
    if _QUEUE_KEY in queue:
        rows = queue[_QUEUE_KEY]
        if not isinstance(rows, list):
            raise CrosslinkReviewError(f"'{_QUEUE_KEY}'는 배열이어야 합니다: {type(rows).__name__}")
        return rows
    if "candidates" in queue:
        raise CrosslinkReviewError(
            "top key 'candidates'는 후보 *자동생성 도구* 출력(미검수)입니다 — 검수 큐"
            f"('{_QUEUE_KEY}')가 아니므로 승격을 거부합니다(자동 적재 차단)."
        )
    if "crosslinks" in queue:
        raise CrosslinkReviewError(
            "top key 'crosslinks'는 *로더 입력*(승격 산출물)입니다 — 검수 큐"
            f"('{_QUEUE_KEY}')가 아니므로 승격을 거부합니다(재승격 오투입 차단)."
        )
    raise CrosslinkReviewError(f"검수 큐 top key '{_QUEUE_KEY}'가 없습니다: {sorted(queue)}")


def _parse_items(rows: list[Any]) -> list[CrosslinkReviewItem]:
    """행별 스키마 검증 — 위반 행 전건 열거 후 일괄 실패(조용한 누락 금지)."""
    items: list[CrosslinkReviewItem] = []
    errors: list[str] = []
    for i, row in enumerate(rows):
        try:
            items.append(CrosslinkReviewItem.model_validate(row))
        except ValidationError as exc:
            summary = "; ".join(
                f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}" for e in exc.errors()
            )
            errors.append(f"[행 {i}] 형식 위반 — {summary}")
    if errors:
        raise CrosslinkReviewError("검수 큐 행 형식 위반:\n" + "\n".join(errors))
    return items


def _promotion_violations(index: int, item: CrosslinkReviewItem) -> list[str]:
    """행 1건의 승격 규칙 위반 목록 — Gate Contract에 위임(카탈로그 주입·단일 정본).

    규칙(kebab 실재·승인 서명·직접매핑 conf 임계)의 정본은 `crosslink_gate.promotion_violations`이며
    여기선 L4 탐지 카탈로그(`CATALOG_BY_ID`)를 주입한다(l1 gate가 l4를 import하지 않도록·계층 규칙).
    """
    return promotion_violations(
        kebab_id=item.kebab_id,
        mis_id=item.mis_id,
        status=item.status,
        reviewer=item.reviewer,
        reviewed_on=item.reviewed_on,
        link_type=item.link_type,
        confidence=item.confidence,
        known_kebab_ids=CATALOG_BY_ID,
        row_label=f"[행 {index}] ",
    )


def parse_review_queue(queue: dict[str, Any]) -> list[CrosslinkReviewItem]:
    """검수 큐 dict → 행 모델 리스트 — top key 검증 + 행 형식 검증(승격 규칙은 미적용).

    `promote_approved`(승격)와 `crosslink_review_aid`(검수 보조 리포트)가 큐를 *같은 방식으로*
    파싱하도록 뽑아낸 공개 헬퍼다(단일 진실 원천). top key `"review_queue"`가 아니면 즉시 오류
    (`"candidates"`/`"crosslinks"` 오투입 명시 거부), 행 형식 위반은 전건 열거로 실패한다.

    Raises:
        CrosslinkReviewError: top key 오투입·행 형식 위반(전건 열거).
    """
    return _parse_items(_validate_top_key(queue))


def promote_approved(queue: dict[str, Any]) -> dict[str, Any]:
    """검수 큐 dict → 승인분만 로더 형식 `{"crosslinks": [...]}`으로 승격(순수 함수).

    top key `"review_queue"`가 아니면 즉시 오류(`"candidates"`/`"crosslinks"` 오투입 명시 거부).
    행 형식·승격 규칙 위반은 `CrosslinkReviewError`로 전건 열거한다. 출력 각 행은
    `schema.MisconceptionCrosslink` 계약 준수 — `method="manual"`(채택 주체=사람)·note에
    "검수:{reviewer} {reviewed_on}" 서명을 병합한다. 승인 0건이면 빈 crosslinks(판단은 호출부).

    Raises:
        CrosslinkReviewError: top key 오투입·행 형식 위반·승격 규칙 위반(전건 열거).
    """
    items = parse_review_queue(queue)

    violations: list[str] = []
    for i, item in enumerate(items):
        violations.extend(_promotion_violations(i, item))
    if violations:
        raise CrosslinkReviewError("승격 규칙 위반:\n" + "\n".join(violations))

    crosslinks: list[dict[str, Any]] = []
    for item in items:
        if item.status != "approved":
            continue
        # 위 규칙 검증으로 승인 행의 reviewer·reviewed_on은 non-None이 보장된다.
        assert item.reviewer is not None and item.reviewed_on is not None
        # 서명 stamp 정본은 Gate Contract `sign`(load 게이트 `is_signed`가 검증하는 형식과 동일).
        stamp = sign(item.reviewer, item.reviewed_on)
        note = stamp if item.note is None else f"{item.note} · {stamp}"
        crosslink = MisconceptionCrosslink(
            kebab_id=item.kebab_id,
            mis_id=item.mis_id,
            link_type=item.link_type,
            confidence=item.confidence,
            method="manual",
            note=note,
        )
        crosslinks.append(crosslink.model_dump())
    return {"crosslinks": crosslinks}


def main(argv: list[str] | None = None) -> int:
    """검수 큐 승인분 승격 CLI — `promote --queue Q.json [--out OUT.json | --load]`.

    반환은 종료 코드: 0=성공 · 1=검수 큐 위반(전건 열거 출력) · 2=입력 파일 부재/승인 0건
    (조용한 무동작 금지) · 3=외래키 대상 누락(HARN-302 — 쓰기 0건·누락 키 전건 열거).
    `--load`는 기존 `load_crosslinks`(l1/crosslink_loader)에 위임해 `misconception_crosslink`
    테이블에 멱등 적재한다(승인→적재 원커맨드).
    """
    parser = argparse.ArgumentParser(
        prog="whymath-crosslink-review",
        description=(
            "오개념 crosswalk 검수 큐(review_queue) 승인분 → 로더 형식(crosslinks) 승격·적재. "
            "crosswalk 행은 사람 검수 산출물 — 승인 행만 승격한다(자동 채택 금지)."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    promote = sub.add_parser("promote", help="승인 행만 추출해 --out 저장 또는 --load 적재")
    promote.add_argument("--queue", type=Path, required=True, help="검수 큐 JSON 경로")
    target = promote.add_mutually_exclusive_group(required=True)
    target.add_argument("--out", type=Path, help="승격 결과(crosslinks JSON) 출력 경로")
    target.add_argument(
        "--load",
        action="store_true",
        help="승격 결과를 misconception_crosslink 테이블에 멱등 적재(load_crosslinks 위임)",
    )
    args = parser.parse_args(argv)

    queue_path: Path = args.queue
    if not queue_path.exists():
        print(f"검수 큐 없음: {queue_path}")
        return 2

    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    try:
        payload = promote_approved(queue)
    except CrosslinkReviewError as exc:
        print(f"승격 거부 — {exc}")
        return 1

    approved = len(payload["crosslinks"])
    if approved == 0:
        print(f"승인 0건 — 승격/적재할 행이 없습니다(전행 검수 대기?): {queue_path}")
        return 2

    if args.load:
        # 지연 import — 로더는 DB 설정(Settings)·sqlalchemy를 끌므로 승격-전용 경로를 hermetic 유지.
        from whymath_backend.l1.fk_precheck import ForeignKeyTargetMissingError
        from whymath_backend.l1.misconception.crosslink_loader import load_crosslinks

        try:
            count = load_crosslinks(None, payload)
        except ForeignKeyTargetMissingError as exc:
            # 외래키 대상 누락(HARN-302) — 쓰기 0건. 종료 코드 3 = 라이브 DB가 적재 입력을 받을
            # 준비가 안 됨(검수 큐 위반 1·입력 부재 2와 구분). 블록은 이 코드를 보고
            # 후속 쓰기를 멈춘다.
            print(f"적재 거부 — {exc}")
            return 3
        print(f"crosswalk 적재 완료: 승인 {approved}건 → {count}건 멱등 upsert.")
    else:
        out_path: Path = args.out
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"승격 완료: 승인 {approved}건 → {out_path} (적재는 --load 또는 crosslink_loader).")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI 진입
    raise SystemExit(main())


__all__ = [
    "CrosslinkReviewError",
    "CrosslinkReviewItem",
    "ReviewStatus",
    "main",
    "parse_review_queue",
    "promote_approved",
]
