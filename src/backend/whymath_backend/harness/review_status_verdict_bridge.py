"""사람 판정 → 회차 코퍼스 `review_status` 각인 CLI — 골든 승격 경로 ③단의 집행 도구 (EOS-136).

무엇이 비어 있었나
-----------------
골든 승격 게이트(`harness/golden_promotion_gate`, EOS-64 ③)의 정본 경로는 ① 코퍼스 실재 → ② 사람
검수 판정 → ③ `review_status` 각인(감사로그 각인값 = 코퍼스 값 = approved) → ④ Wilson 게이트다.
그런데 ③단을 채울 수 있는 유일한 도구(`problem_corpus_review_status_backfill`)는 **코퍼스 단위**로
감사 라벨 표본의 판정 1개를 채우는 도구라 사람 판정 이벤트를 읽지 않고, 축적 CLI의 회차 코퍼스는
그 도구의 대상(`KNOWN_CORPORA`)도 아니었다. 그래서 사람이 승인한 수용 문항은 검수가 몇 건이든
`review_status_not_backfilled`로 **영구히** 막혔다(MP-03 실측 — 승격 가능 후보 7건 전부,
`docs/reviews/mp03_canary_threshold_and_promotion_path_2026-09-25.md` §4.2·§8.2). 게이트(판정)만
착지하고 ②→③ 사이의 집행 도구가 빠진 상태였다. 이 모듈이 그 도구다.

무엇을 하는가
------------
검수 타이머 이벤트(`review_session`이 낸 `ReviewTimerEvent` JSONL)의 **slug별 최신 종결 판정**을
회차 코퍼스 JSONL의 `review_status`로 옮기고, 옮긴 1건마다 **각인 감사로그** 1행을 남긴다. 게이트는
그 감사로그를 `--backfill-audit`으로 받아 ③단을 판정한다.

  - 판정 해석: `golden_promotion_gate.latest_human_verdict_events` — 게이트 ②단·④단과 **같은
    함수**다(각인된 판정과 게이트가 본 판정이 갈라지지 않게. started·aborted는 판정이 아니다).
  - 값 변환: `schema/review_timer.review_status_for_verdict` — 판정 → 노출 어휘의 단일 정본.
  - 적용 대상: 회차 코퍼스만(`review_status_domains.verdict_bridge_refusal` — 축적 CLI가 끌 수
    없게 남기는 회차 대장 사이드카 `<corpus>.rounds.jsonl`이 표식). 고정 코퍼스 8종은 코퍼스 단위
    백필의 대상이라 거부한다(계약 정본 `docs/standards/review_status_stamping_contract.md`).

각인 규칙 (최신 판정 → 각인값)
-----------------------------
  ``approved``            → ``approved``
  ``rejected``            → ``rejected`` (노출 차단 사실을 코퍼스에 남긴다 — fail-closed)
  ``approved_with_edit``  → **각인 보류**(`held_edit_pending`). 변환 정본은 이 판정을 `approved`로
                            옮기지만, 그것은 *손질이 반영된* 내용의 노출 어휘다. 검수 CLI의 `e`는
                            "손질하면 쓸 수 있다"이고 손질 내용을 저장하지 않으므로 코퍼스에는
                            **손질 전** 내용이 있다(골든 계약도 as-found `defective`로 본다). 그
                            내용에 approved를 찍으면 사람이 "이대로는 못 쓴다"고 본 문항이 노출된다.
                            술어는 게이트와 공유하는 `certifies_current_content`다. 해금 경로 =
                            손질 반영 → 재검수(`approved`) — 재검수 종결이 최신 판정이 된다.

검수 후 내용 편집 — 지문 대조 (EOS-27)
--------------------------------------
검수 이벤트는 검수자가 본 레코드의 지문(`content_fingerprint` — `schema/review_timer.
review_content_fingerprint`)을 싣는다. 승인·반려를 각인하기 **전에** 그 지문을 코퍼스 현재 레코드의
지문과 대조한다(`review_fingerprint_state` — 3상태). 대조 대상은 각인할 값이 있는 판정(approved·
rejected)뿐이다 — 손질 승인은 어차피 보류다.

  - ``match``   → 아래 불가침 규칙대로 진행.
  - ``changed`` → 각인하지 않고 ``content_changed``로 보고(exit 1). 승인 뒤에 내용이 바뀌었다 —
                  사람이 본 내용이 아니다. 코퍼스에 이미 노출 통과값이 있으면 ``exposure_risk``다
                  (승인 후 편집된 문항이 노출 가능 상태). 이미 같은 값이 찍혀 있어도
                  (``already_stamped``가 될 레코드) 내용이 바뀌었으면 ``content_changed``다 —
                  지문이 달라진 사실이 먼저다.
  - ``unknown`` → 이벤트에 지문이 없다(옛 이벤트·본문을 못 본 항목). 빈 칸이면 각인하지 않고
                  ``fingerprint_unverifiable``로 보류한다(exit 1) — **모름은 일치가 아니다**.
                  해금 경로 = 재검수(새 이벤트가 지문을 싣는다). 이미 채워진 레코드는 쓸 것이
                  없으므로 기존 버킷(``already_stamped``·``conflict``)을 그대로 따른다.
  지문 없는 판정의 처리를 '현행 유지(각인)'가 아니라 '보류'로 둔 근거와 영향 범위는
  `docs/standards/review_status_stamping_contract.md` §9 · 동결 테스트
  `test_review_status_verdict_bridge.py::TestContentFingerprint`.

불가침 규칙 — 이미 채워진 값은 덮어쓰지 않는다
--------------------------------------------
`review_status`가 **이미 채워진** 레코드는 어떤 값이든 원문 줄 그대로 둔다(코퍼스 단위 백필의
바이트 계약과 동형 — 수동 재검수·격리 등 다른 경로의 결정을 조용히 덮지 않는다).
  - 채워진 값 = 각인할 값 → ``already_stamped``(할 일 없음 · 감사 행도 새로 쓰지 않는다).
  - 채워진 값 ≠ 각인할 값 → **충돌**(`conflicts`) — 쓰지 않고 보고하며 exit 1. 그중 채워진 값이
    노출 통과값(`approved`)인데 최신 사람 판정이 그 내용을 인증하지 않으면(반려·손질 승인)
    ``exposure_risk``다 — 학생에게 나가는 문항을 사람이 막았다는 뜻이라 반려로 덮는 것이 아니라
    격리 계약(`docs/standards/problem_quarantine_contract.md`)의 사람 절차 대상이다.

**각인하지 않은 값을 감사로그에 올리지 않는다.** 손으로 approved를 찍어 둔 레코드는 같은 값이라도
``already_stamped``로 두고 감사 행을 만들지 않는다 — 여기서 감사 행을 만들어 주면 손각인이 도구
각인으로 세탁되어 게이트 ③단(`review_status_not_backfilled` = 손각인 의심)이 무력해진다.

판정 없는 slug는 건드리지 않는다(``no_verdict``). 판정은 있는데 코퍼스에 없는 slug(회차 내 구조
중복으로 코퍼스에 안 들어간 문항 등)는 각인 대상이 아니며 ``verdict_not_in_corpus``로 센다.

바이트 계약·입력 손상
--------------------
  - 각인하지 않는 줄은 원문 그대로(앞뒤 공백만 제거 — 코퍼스 단위 백필과 같은 정규화), 각인하는
    줄은 `review_status` 한 키만 채운다(기존 키 순서 보존, 부재면 끝에 추가).
  - 2회 실행은 바이트 동일(멱등) — 첫 실행이 값을 채우므로 두 번째는 전건 ``already_stamped``이고
    코퍼스도 감사로그도 **쓰지 않는다**.
  - **입력 손상 1행이면 아무것도 쓰지 않는다(exit 2)** — 이벤트 파싱·검증 실패, 코퍼스 행 파싱
    실패·JSON 객체 아님·slug 없음·slug 중복·review_status 형식 이상. 잘린 반려 행 하나가 이전
    승인을 최신 판정으로 만들 수 있다(게이트 docstring 선례) — 손상 위에서 각인하면 그 오판이
    코퍼스에 영구히 새겨진다.

쓰기 순서 — 중간에 죽어도 재실행으로 복구된다
-------------------------------------------
① 감사 행을 **먼저** append(flush + fsync) → ② 코퍼스를 같은 폴더 임시 파일에 쓰고 원자 교체
(`os.replace`). ①과 ② 사이에서 죽으면 감사로그에는 각인이 있고 코퍼스는 비어 있다 — 게이트는
그것을 `review_status_audit_mismatch`로 막고(fail-closed), 재실행하면 빈 칸이 다시 각인된다.
순서를 뒤집으면 코퍼스에만 값이 남는데, 재실행은 그것을 ``already_stamped``로 보고 감사 행을
만들지 않으므로(위 세탁 금지) **영영 복구되지 않는다**. 그래서 이 순서다. 감사로그는 append
전용이다 — 여러 회차에 걸쳐 각인이 쌓여야 게이트가 전건을 본다(게이트는 slug별 마지막 기록을 쓴다).

법정·검수 절차의 기계 대체 금지
------------------------------
이 도구는 판정을 **만들지 않는다** — 사람의 종결 판정을 옮길 뿐이다. 판정이 없는 문항을 채울
인자·기본값이 없고, 보류된 손질 승인을 강제로 각인하는 플래그도 없다(`--force` 류 부재를 테스트가
동결한다). 게이트 ④단(검수 배치 Wilson)은 이 도구가 대신하지 않는다.

exit 코드: 0 = 정상(충돌 0 · 각인 대상과 판정이 1건 이상 대응) · 1 = 충돌 1건 이상(비충돌분은
각인한다) 또는 코퍼스와 대응하는 판정 0건(잘못된 짝 의심 — "0건 통과"가 아니다) · 2 = 입력 오류
(파일 부재·적용 대상 위반·입력 손상·쓰기 실패) — 쓰기 실패를 뺀 전부는 무기록이다.

사용법(운영자 — 검수 뒤, 승격 게이트 직전):
    python -m whymath_backend.harness.review_status_verdict_bridge \\
        --corpus <acc>.jsonl --review-events <review_timer.jsonl> [--review-events ...] \\
        [--audit-out <acc>.review_status_audit.jsonl] [--dry-run]

    요약 JSON은 stdout, 사람이 읽는 한 줄 요약과 경고는 stderr로 낸다.

harness는 import-linter 계약 밖(조성/ops 층 — 코퍼스 백필 선례).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from whymath_backend.harness.golden_promotion_gate import (
    certifies_current_content,
    latest_human_verdict_events,
)
from whymath_backend.harness.review_status_domains import verdict_bridge_refusal
from whymath_backend.schema.enums import ReviewStatus, is_review_status_cleared
from whymath_backend.schema.review_timer import (
    ReviewTimerEvent,
    review_content_fingerprint,
    review_fingerprint_state,
    review_status_for_verdict,
)

__all__ = [
    "STAMP_SOURCE",
    "BridgePlan",
    "BridgeReport",
    "ContentChange",
    "Conflict",
    "default_stamp_audit_path",
    "main",
    "plan_stamps",
    "run_bridge",
    "stamp_target",
]

#: 감사 행의 각인 출처 표식 — 코퍼스 단위 백필의 감사 행(`problem_id`·`slug`·`review_status`)과
#: 구분하기 위한 값. 게이트는 두 형식을 같은 키(`slug`·`review_status`)로 읽는다.
STAMP_SOURCE = "human_verdict"

_EXIT_OK = 0
_EXIT_ATTENTION = 1
_EXIT_INPUT_ERROR = 2

Bucket = Literal["stamp", "already_stamped", "held_edit_pending", "conflict"]


def default_stamp_audit_path(corpus_path: Path) -> Path:
    """각인 감사로그 기본 경로 — 회차 코퍼스 곁 사이드카 `<corpus>.review_status_audit.jsonl`.

    축적 CLI 사이드카 규약(`<out>.rounds.jsonl`·`<out>.review.jsonl`·`<out>.genlog.jsonl`)과 같은
    형식이다. 코퍼스마다 하나라 서로 다른 회차 코퍼스의 각인이 한 파일에 섞이지 않는다.
    """
    return corpus_path.with_suffix(".review_status_audit.jsonl")


def stamp_target(verdict: str) -> str | None:
    """사람 최신 종결 판정 → 각인할 `review_status` 값. None = 각인 보류.

    변환은 `review_status_for_verdict`(단일 정본)가 하고, 그 결과가 approved라도 판정이 **지금
    내용 그대로**를 승인한 것이 아니면(`certifies_current_content` — 손질 승인) 보류한다. 어휘 밖
    판정은 변환 정본이 `ValueError`로 거부한다(추측하지 않는다).
    """
    status = review_status_for_verdict(verdict)
    if status is None:
        return None
    if status is ReviewStatus.approved and not certifies_current_content(verdict):
        return None
    return status.value


@dataclass(frozen=True, slots=True)
class Conflict:
    """이미 채워진 `review_status`와 최신 사람 판정이 어긋난 레코드 — 쓰지 않고 보고한다."""

    slug: str
    current: str
    """코퍼스에 이미 있는 값(불가침)."""
    target: str | None
    """최신 판정이 각인하려던 값. None = 손질 승인(각인 보류 판정)."""
    human_verdict: str
    exposure_risk: bool
    """채워진 값이 노출 통과값인데 최신 사람 판정이 그 내용을 인증하지 않는다 — 격리 절차 대상."""

    def to_json(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "current": self.current,
            "target": self.target,
            "human_verdict": self.human_verdict,
            "exposure_risk": self.exposure_risk,
        }


@dataclass(frozen=True, slots=True)
class ContentChange:
    """검수 뒤 내용이 바뀐 레코드 — 판정의 지문이 코퍼스 현재 지문과 다르다. 각인하지 않는다."""

    slug: str
    current: str | None
    """코퍼스에 있는 review_status(빈 칸이면 None)."""
    human_verdict: str
    reviewed_fingerprint: str
    current_fingerprint: str
    exposure_risk: bool
    """채워진 값이 노출 통과값이다 — 사람이 본 적 없는 내용이 노출 가능 상태(격리 절차 대상)."""

    def to_json(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "current": self.current,
            "human_verdict": self.human_verdict,
            "reviewed_fingerprint": self.reviewed_fingerprint,
            "current_fingerprint": self.current_fingerprint,
            "exposure_risk": self.exposure_risk,
        }


@dataclass(frozen=True, slots=True)
class BridgePlan:
    """각인 계획(순수 계산 결과) — 무엇을 쓰고 무엇을 왜 안 쓰는지 전부 나른다."""

    records: int
    """코퍼스 레코드 수(빈 줄 제외)."""
    verdicts: int
    """검수 기록의 사람 최신 종결 판정 수(slug 기준)."""
    out_lines: list[str]
    """각인 반영 후 코퍼스 줄 전건(각인하지 않는 줄은 원문 그대로)."""
    audit_rows: list[dict[str, Any]]
    """쓸 감사 행 — 각인 1건당 1행."""
    already_stamped: list[str] = field(default_factory=list)
    held_edit_pending: list[str] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    content_changed: list[ContentChange] = field(default_factory=list)
    """검수 뒤 내용이 바뀐 레코드(EOS-27) — 각인하지 않았다."""
    fingerprint_unverifiable: list[str] = field(default_factory=list)
    """이벤트에 지문이 없어 각인하지 않고 보류한 빈 칸 레코드(EOS-27) — 재검수가 해금한다."""
    no_verdict: int = 0
    """판정 없는 코퍼스 레코드 수 — 건드리지 않았다."""
    verdict_not_in_corpus: list[str] = field(default_factory=list)
    """판정은 있으나 코퍼스에 없는 slug(각인 대상 아님 — 정보)."""

    @property
    def stamped(self) -> int:
        return len(self.audit_rows)

    @property
    def matched(self) -> int:
        """코퍼스 레코드 중 사람 판정이 대응하는 수 — 여섯 버킷의 합."""
        return (
            self.stamped
            + len(self.already_stamped)
            + len(self.held_edit_pending)
            + len(self.conflicts)
            + len(self.content_changed)
            + len(self.fingerprint_unverifiable)
        )

    def stamped_by_status(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.audit_rows:
            key = str(row["review_status"])
            counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items()))


def _bucket(current: str | None, target: str | None) -> Bucket:
    """(채워진 값, 각인할 값) → 버킷. 모듈 docstring "불가침 규칙"의 판정표를 그대로 옮긴다."""
    if current is None:
        return "stamp" if target is not None else "held_edit_pending"
    if target is None:
        # 손질 승인 — 채워진 값이 노출 통과값이면 사람이 그 내용을 막은 것이라 충돌(노출 위험),
        # 아니면(반려·대기·격리 등) 이미 노출이 막혀 있으므로 보류로 둔다.
        return "conflict" if is_review_status_cleared(current) else "held_edit_pending"
    return "already_stamped" if current == target else "conflict"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _audit_row(
    *,
    slug: str,
    record: dict[str, Any],
    target: str,
    event: ReviewTimerEvent,
    corpus_name: str,
    stamped_at: datetime,
) -> dict[str, Any]:
    """감사 행 1건 — 게이트가 읽는 `slug`·`review_status` + 각인 근거(이벤트·검수자·시각).

    사람 판정 원값은 `human_verdict`에 싣는다 — `verdict` 키는 검수 도구 판정 파일의 고유 키라,
    그 이름을 쓰면 게이트가 이 행을 "판정 파일이 감사로그 자리에 들어왔다"로 거부한다.
    """
    return {
        "slug": slug,
        "review_status": target,
        "problem_id": record.get("problem_id"),
        "human_verdict": str(event.verdict),
        "event_id": str(event.event_id),
        "review_session_id": str(event.review_session_id),
        "reviewer_id": event.reviewer_id,
        "content_fingerprint": event.content_fingerprint,
        "reviewed_at": _iso(event.occurred_at),
        "recorded_at": _iso(event.recorded_at),
        "stamped_at": stamped_at.isoformat(),
        "stamp_source": STAMP_SOURCE,
        "corpus": corpus_name,
    }


@dataclass(frozen=True, slots=True)
class _CorpusRow:
    text: str
    data: dict[str, Any]
    slug: str
    current: str | None


def _load_corpus(path: Path) -> tuple[list[_CorpusRow], list[str]]:
    """코퍼스 JSONL → 행 목록. 손상은 삼키지 않고 파일명·줄 번호·사유 타입명으로 모은다.

    slug 중복은 손상이다 — 어느 행이 검수된 그 문항인지 가릴 수 없으면 각인 대상이 모호하다
    (축적 CLI는 slug 충돌을 append하지 않으므로 정상 산출물에는 없다).
    """
    rows: list[_CorpusRow] = []
    errors: list[str] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            where = f"{path.name} line {line_no}"
            try:
                parsed = json.loads(text)
            except Exception as exc:  # noqa: BLE001 — 사유 수집(타입명 보존)이 목적
                errors.append(f"{where}: {type(exc).__name__}")
                continue
            if not isinstance(parsed, dict):
                errors.append(f"{where}: NotAJsonObject")
                continue
            slug = parsed.get("slug")
            if not (isinstance(slug, str) and slug):
                errors.append(f"{where}: MissingSlug")
                continue
            if slug in seen:
                errors.append(f"{where}: DuplicateSlug")
                continue
            raw_status = parsed.get("review_status")
            if raw_status is not None and not isinstance(raw_status, str):
                errors.append(f"{where}: InvalidReviewStatusType")
                continue
            seen.add(slug)
            rows.append(_CorpusRow(text=text, data=parsed, slug=slug, current=raw_status or None))
    return rows, errors


def plan_stamps(
    rows: Sequence[_CorpusRow],
    latest: dict[str, ReviewTimerEvent],
    *,
    corpus_name: str,
    stamped_at: datetime,
) -> BridgePlan:
    """코퍼스 행 × 최신 사람 판정 → 각인 계획(순수 — 파일 I/O 0)."""
    out_lines: list[str] = []
    audit_rows: list[dict[str, Any]] = []
    already: list[str] = []
    held: list[str] = []
    conflicts: list[Conflict] = []
    changed: list[ContentChange] = []
    unverifiable: list[str] = []
    no_verdict = 0
    corpus_slugs = {row.slug for row in rows}

    for row in rows:
        event = latest.get(row.slug)
        if event is None or event.verdict is None:
            no_verdict += 1
            out_lines.append(row.text)
            continue
        verdict = str(event.verdict)
        target = stamp_target(verdict)
        if target is not None:
            # EOS-27 — 각인할 값이 있는 판정은 먼저 "검수자가 본 내용이 지금 그대로인가"를 가른다.
            # 불가침 규칙(채워진 값 보존)보다 앞선다: 내용이 바뀐 레코드는 이미 같은 값이 찍혀
            # 있어도 `already_stamped`("할 일 없음")로 접을 수 없다 — 그것이 정확히 사각이었다.
            current_fp = review_content_fingerprint(row.data)
            fp_state = review_fingerprint_state(event.content_fingerprint, current_fp)
            if fp_state == "changed":
                assert event.content_fingerprint is not None  # changed는 양쪽 지문이 있을 때만
                out_lines.append(row.text)
                changed.append(
                    ContentChange(
                        slug=row.slug,
                        current=row.current,
                        human_verdict=verdict,
                        reviewed_fingerprint=event.content_fingerprint,
                        current_fingerprint=current_fp,
                        exposure_risk=row.current is not None
                        and is_review_status_cleared(row.current),
                    )
                )
                continue
            if fp_state == "unknown" and row.current is None:
                out_lines.append(row.text)
                unverifiable.append(row.slug)
                continue
        bucket = _bucket(row.current, target)
        if bucket == "stamp":
            assert target is not None  # _bucket이 target 없는 빈 칸을 stamp로 내지 않는다
            updated = dict(row.data)
            updated["review_status"] = target
            out_lines.append(json.dumps(updated, ensure_ascii=False))
            audit_rows.append(
                _audit_row(
                    slug=row.slug,
                    record=row.data,
                    target=target,
                    event=event,
                    corpus_name=corpus_name,
                    stamped_at=stamped_at,
                )
            )
            continue
        out_lines.append(row.text)
        if bucket == "already_stamped":
            already.append(row.slug)
        elif bucket == "held_edit_pending":
            held.append(row.slug)
        else:
            assert row.current is not None  # 충돌은 채워진 값이 있을 때만 난다
            conflicts.append(
                Conflict(
                    slug=row.slug,
                    current=row.current,
                    target=target,
                    human_verdict=verdict,
                    exposure_risk=is_review_status_cleared(row.current)
                    and not is_review_status_cleared(target),
                )
            )

    return BridgePlan(
        records=len(rows),
        verdicts=len(latest),
        out_lines=out_lines,
        audit_rows=audit_rows,
        already_stamped=already,
        held_edit_pending=held,
        conflicts=conflicts,
        content_changed=changed,
        fingerprint_unverifiable=unverifiable,
        no_verdict=no_verdict,
        verdict_not_in_corpus=[slug for slug in latest if slug not in corpus_slugs],
    )


@dataclass(frozen=True, slots=True)
class BridgeReport:
    """실행 결과 — 요약 JSON(stdout)과 exit 코드의 근거."""

    corpus: str
    audit_path: str
    review_events: list[str]
    dry_run: bool
    plan: BridgePlan | None = None
    written: bool = False
    error: str | None = None
    """exit 2 사유 분류(input_missing·domain_refused·input_damaged·write_failed)."""
    messages: list[str] = field(default_factory=list)
    """사람이 읽는 사유(손상 행 목록·거부 사유 등) — 값은 담지 않는다(타입명·줄 번호만)."""

    @property
    def exit_code(self) -> int:
        if self.error is not None or self.plan is None:
            return _EXIT_INPUT_ERROR
        if (
            self.plan.conflicts
            or self.plan.content_changed
            or self.plan.fingerprint_unverifiable
            or self.plan.matched == 0
        ):
            return _EXIT_ATTENTION
        return _EXIT_OK

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "corpus": self.corpus,
            "audit_path": self.audit_path,
            "review_events": self.review_events,
            "dry_run": self.dry_run,
            "error": self.error,
            "messages": self.messages,
            "written": self.written,
            "exit_code": self.exit_code,
        }
        plan = self.plan
        if plan is not None:
            payload.update(
                {
                    "records": plan.records,
                    "verdicts": plan.verdicts,
                    "matched": plan.matched,
                    "stamped": plan.stamped,
                    "stamped_by_status": plan.stamped_by_status(),
                    "stamped_slugs": [str(row["slug"]) for row in plan.audit_rows],
                    "already_stamped": plan.already_stamped,
                    "held_edit_pending": plan.held_edit_pending,
                    "conflicts": [conflict.to_json() for conflict in plan.conflicts],
                    "exposure_risk": sum(1 for c in plan.conflicts if c.exposure_risk)
                    + sum(1 for c in plan.content_changed if c.exposure_risk),
                    "content_changed": [change.to_json() for change in plan.content_changed],
                    "fingerprint_unverifiable": plan.fingerprint_unverifiable,
                    "no_verdict": plan.no_verdict,
                    "verdict_not_in_corpus": plan.verdict_not_in_corpus,
                }
            )
        return payload


def _write(corpus_path: Path, audit_path: Path, plan: BridgePlan) -> None:
    """감사로그 append(먼저) → 코퍼스 원자 교체. 순서의 이유는 모듈 docstring "쓰기 순서"."""
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in plan.audit_rows)
    with audit_path.open("a", encoding="utf-8") as handle:
        handle.write(audit_text)
        handle.flush()
        os.fsync(handle.fileno())

    # 줄바꿈은 텍스트 모드 기본(플랫폼 관례)으로 쓴다 — 축적 CLI가 코퍼스를 텍스트 모드 append로
    # 쓰므로(Windows면 CRLF) 같은 관례여야 각인하지 않는 줄의 바이트가 그대로 남는다.
    body = "\n".join(plan.out_lines) + "\n" if plan.out_lines else ""
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{corpus_path.name}.", suffix=".tmp", dir=corpus_path.parent
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, corpus_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _unreadable_inputs(paths: Sequence[Path]) -> list[str]:
    """부재·확인 불가 입력 목록 — `is_file()`의 권한 예외를 "없다"로 접지 않고 사유를 남긴다."""
    problems: list[str] = []
    for path in paths:
        try:
            present = path.is_file()
        except OSError as exc:
            problems.append(f"확인 불가({type(exc).__name__}): {path}")
            continue
        if not present:
            problems.append(f"파일 부재: {path}")
    return problems


def run_bridge(
    *,
    corpus_path: Path,
    review_events: Sequence[Path],
    audit_path: Path | None = None,
    dry_run: bool = False,
    now_utc: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> BridgeReport:
    """각인 1회 실행 — 입력 검사 → 계획 → (dry-run이 아니고 각인이 있으면) 쓰기."""
    audit = audit_path if audit_path is not None else default_stamp_audit_path(corpus_path)
    base: dict[str, Any] = {
        "corpus": str(corpus_path),
        "audit_path": str(audit),
        "review_events": [str(path) for path in review_events],
        "dry_run": dry_run,
    }

    missing = _unreadable_inputs((corpus_path, *review_events))
    if missing:
        return BridgeReport(**base, error="input_missing", messages=missing)

    refusal = verdict_bridge_refusal(corpus_path)
    if refusal is not None:
        return BridgeReport(**base, error="domain_refused", messages=[refusal])

    try:
        latest, event_errors = latest_human_verdict_events(review_events)
        rows, corpus_errors = _load_corpus(corpus_path)
    except (OSError, UnicodeDecodeError) as exc:
        # 파일 단위 실패(인코딩·읽기 권한)는 행 단위 손상 목록에 못 담긴다 — 그래도 손상이다.
        return BridgeReport(
            **base, error="input_damaged", messages=[f"입력 읽기 실패: {type(exc).__name__}"]
        )
    damage = [*event_errors, *corpus_errors]
    if damage:
        return BridgeReport(**base, error="input_damaged", messages=damage)

    plan = plan_stamps(rows, latest, corpus_name=corpus_path.name, stamped_at=now_utc())
    if dry_run or not plan.audit_rows:
        return BridgeReport(**base, plan=plan)

    try:
        _write(corpus_path, audit, plan)
    except OSError as exc:
        return BridgeReport(
            **base,
            plan=plan,
            error="write_failed",
            messages=[
                f"쓰기 실패({type(exc).__name__}) — 감사로그가 먼저 기록됐을 수 있고 코퍼스는 "
                "교체되지 않았다. 게이트는 이 상태를 review_status_audit_mismatch로 막는다"
                "(fail-closed). 원인을 없앤 뒤 같은 명령을 다시 돌리면 빈 칸이 다시 각인된다."
            ],
        )
    return BridgeReport(**base, plan=plan, written=True)


def _summary_line(report: BridgeReport) -> str:
    """사람이 읽는 한 줄 요약(stderr) — 요약 JSON과 같은 수치."""
    plan = report.plan
    if plan is None:
        return f"[각인 불가] {report.error} — " + "; ".join(report.messages[:5])
    by_status = " · ".join(f"{k} {v}" for k, v in plan.stamped_by_status().items()) or "0"
    mode = "계획(dry-run)" if report.dry_run else ("기록" if report.written else "기록 없음")
    return (
        f"[각인 {mode}] 각인 {plan.stamped}건({by_status}) · 이미 같은 값 "
        f"{len(plan.already_stamped)} · 손질 승인 보류 {len(plan.held_edit_pending)} · 충돌 "
        f"{len(plan.conflicts)}(노출 위험 {sum(1 for c in plan.conflicts if c.exposure_risk)}) · "
        f"검수 후 내용 변경 {len(plan.content_changed)}"
        f"(노출 위험 {sum(1 for c in plan.content_changed if c.exposure_risk)}) · "
        f"지문 없어 보류 {len(plan.fingerprint_unverifiable)} · "
        f"판정 없음 {plan.no_verdict} · 코퍼스 밖 판정 {len(plan.verdict_not_in_corpus)} "
        f"(exit {report.exit_code})"
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 엔트리 — exit 0 정상 · 1 충돌/대응 0건 · 2 입력 오류(무기록)."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.review_status_verdict_bridge",
        description=(
            "사람 판정 → 회차 코퍼스 review_status 각인(EOS-136) — 검수 이벤트의 slug별 최신 종결 "
            "판정을 옮기고 각인 감사로그를 남긴다(골든 승격 게이트 ③단의 근거). 판정을 만들지 "
            "않는다 — 이미 채워진 값은 덮어쓰지 않고, 손질 승인은 재검수 전까지 각인하지 않는다."
        ),
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        required=True,
        help="회차 코퍼스 JSONL(축적 CLI의 --out — 곁에 <corpus>.rounds.jsonl 대장이 있어야 한다).",
    )
    parser.add_argument(
        "--review-events",
        dest="review_events",
        type=Path,
        action="append",
        required=True,
        help="검수 타이머 이벤트 JSONL(복수 지정 가능 — 파일 순서상 마지막 종결이 최신 판정).",
    )
    parser.add_argument(
        "--audit-out",
        dest="audit_path",
        type=Path,
        default=None,
        help="각인 감사로그 JSONL(append 전용 · 생략 시 <corpus>.review_status_audit.jsonl).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="아무것도 쓰지 않고 각인 계획만 낸다(exit 코드 규칙은 같다).",
    )
    args = parser.parse_args(argv)

    report = run_bridge(
        corpus_path=args.corpus,
        review_events=args.review_events,
        audit_path=args.audit_path,
        dry_run=args.dry_run,
    )
    json.dump(report.to_json(), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    sys.stderr.write(_summary_line(report) + "\n")
    plan = report.plan
    if plan is not None and report.error is None:
        for conflict in plan.conflicts:
            note = (
                " — 노출 위험: 격리 계약(docs/standards/problem_quarantine_contract.md) 절차 대상"
                if conflict.exposure_risk
                else ""
            )
            sys.stderr.write(
                f"[충돌] {conflict.slug}: 코퍼스 {conflict.current} ≠ 최신 사람 판정 "
                f"{conflict.human_verdict}(각인값 {conflict.target}) — 덮어쓰지 않았다{note}\n"
            )
        for change in plan.content_changed:
            note = (
                " — 노출 위험: 격리 계약(docs/standards/problem_quarantine_contract.md) 절차 대상"
                if change.exposure_risk
                else ""
            )
            sys.stderr.write(
                f"[검수 후 내용 변경] {change.slug}: 사람 판정 {change.human_verdict}가 본 내용과 "
                f"코퍼스 현재 내용의 지문이 다르다 — 각인하지 않았다(재검수 필요){note}\n"
            )
        if plan.fingerprint_unverifiable:
            sys.stderr.write(
                f"[지문 없음] {len(plan.fingerprint_unverifiable)}건 — 검수 이벤트에 내용 지문이 "
                "없어 '본 내용이 지금 그대로인가'를 확인할 수 없다. 각인하지 않고 보류했다"
                "(모름은 일치가 아니다) — 재검수(review_session)가 지문 있는 판정을 새로 남긴다.\n"
            )
        if plan.matched == 0:
            sys.stderr.write(
                "[대응 0건] 코퍼스 레코드와 짝이 맞는 사람 판정이 없다 — 검수 기록과 코퍼스가 "
                "다른 회차일 수 있다(0건 통과가 아니다).\n"
            )
    return report.exit_code


if __name__ == "__main__":  # pragma: no cover — 모듈 실행 진입점
    raise SystemExit(main())
