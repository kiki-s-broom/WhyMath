"""골든 벤치마크 셋 — 검수 판정에서 *정답지*를 승격·동결하는 규약 (EOS-60 acceptance ①③⑥).

무엇을 만드나 (정본: `docs/standards/golden_benchmark_contract.md`)
------------------------------------------------------------------
우리 QA 엔진(`harness/qa_pipeline`)은 PASS/FAIL을 내지만 **자기 FN율을 모른다** — 그 PASS가
얼마나 믿을 만한지 잰 적이 없다(N8 갭 —
`docs/reviews/eos_validation_n1_n10_gap_review_2026-08-30.md` §3.7). 판정기를 재려면
정답지가 필요하고, 이 모듈이 그 정답지(**골든 셋**)를 만든다.
혼동행렬 계산은 `ops/qa_confusion_matrix`가 한다(만드는 쪽과 재는 쪽 분리 —
EOS-54의 writer(harness)/집계(ops) 배치와 동형).

**별도 라벨링 캠페인 금지(acceptance ①)**: 골든 라벨은 새로 만들지 않는다. EOS-54 검수 타이머
이벤트(`schema/review_timer.ReviewTimerEvent`)의 `verdict`·`failure_code`가 곧 사람 라벨이므로,
필요한 것은 "검수 결과 중 무엇을 골든으로 승격하고 언제 동결하는가"의 **규약**뿐이다(추가 인간
시간 ≈ 0 — 검수 185 CU 예산의 부산물). 목표 규모 = 앵커 6개 × 30~35건 ≈ 200건.

as-found 라벨 무결성 — fail-closed (acceptance ⑥)
-------------------------------------------------
골든 라벨은 **QA 엔진이 실제로 본 입력**, 즉 *검수 전(as-found)* 상태의 라벨이어야 한다.
승격 가능성은 verdict별로 다르다:

  - `rejected` → **그대로 승격**(label=defective). `failure_code`(F1~F8)가 as-found 결함을
    명시하고, 반려는 정의상 손질 전 상태의 판정이다. 근거 = `AsFoundBasis.REJECTED_FAILURE_CODE`.
  - `approved` → **기본 제외(모호)**. 손질 후 승인을 clean으로 승격하면 **원래 결함이던
    입력이 정상으로 라벨링되어 FN율이 과소평가**된다 — 골든이 자기 목적을 훼손한다.
    EOS-62가 착지해 verdict는 3값이 됐지만(`approved_with_edit` 실재), **그 이전에 기록된
    `approved` 행은 여전히 모호**하다(소급 재분류 금지 — 아래 `--edit-aware-since`). 다음 둘
    중 하나가 성립할 때만 승격한다:
      ⓐ **검수 전 불변 스냅샷 + as-found 결함 라벨**(`--as-found-labels`) →
        `AsFoundBasis.PRE_REVIEW_SNAPSHOT`. 라벨은 스냅샷이 말하는 대로 쓴다(clean/defective).
      ⓑ **EOS-62의 edit-aware verdict**(`approved_with_edit`가 `ReviewVerdict` 어휘에 존재 —
        2026-09-01 착지) + `--edit-aware-since` 이후 검수분 → `AsFoundBasis.EDIT_AWARE_VERDICT`.
        그 계약 이후의 밋밋한 `approved`는 "무손질 승인"을 뜻하므로 clean으로 승격하고,
        `approved_with_edit`는 defective로 승격한다.
  - 둘 다 없으면 **제외하고 그 건수를 리포트에 명시**한다(조용한 포함 금지 — 미측정 ≠ 정상).

`--edit-aware-since`를 **명시적 인자로 요구**하는 이유: EOS-62 ④가 소급 재분류를 금지하므로
계약 착지 *이전*의 `approved` 행은 어휘가 확장돼도 영구 모호다. 시각 경계 없이 어휘 존재만으로
전부 승격하면 그 과거 행이 조용히 clean으로 섞인다 — 그래서 어휘가 있어도 경계가 없으면
**전부 제외**한다(fail-closed). 골든 표본을 계약 착지 이후 검수분에서 뽑는 것이 정본 경로다.

과적합 방지 — 재채점 금지 (acceptance ③)
-----------------------------------------
S2-11(done)이 명문화한 "결함 교정 후 같은 표본 재채점 금지·신규 독립 표본 재추출"(초인간 검증
표준 §4.5)을 골든에도 건다. 집행 수단 2개:

  1. **동결 기록** — 골든 셋에 `golden_version`·`rotation`·`frozen_at`·`digest`(내용 sha256)를
     박는다. 어떤 셋으로 잰 결과인지가 리포트에서 항상 식별된다.
  2. **평가 원장**(`append_evaluation_ledger`/`find_rescore_violation`) — 평가 1회마다
     (digest, engine_revision)을 append한다. **같은 digest를 다른 engine_revision으로 재채점**
     하면 그것이 곧 "교정 후 같은 표본 재채점"이므로 `ops/qa_confusion_matrix`가 exit 1로
     막는다. 같은 리비전 재실행은 재현성(S4) 확인이므로 허용한다.

재추출의 독립성 원천은 **이전 골든의 명시적 제외**(`--exclude-golden`)다 — `rotation`만으로는
신규 표본이 보장되지 않는다(#928 리뷰 P1 실측: 앵커 후보가 쿼터 이하면 회전은 순서만 바꾸고
전건이 선택돼 같은 digest가 나온다. 그 구간이 하필 우리 목표 규모 30~35다). 회전은 제외 위에서
순서를 재배열하는 보조 축이고, 해시 자체는 새로 만들지 않는다 —
`reviewer_sample_package.rotation_key`(S2-11)를 그대로 재사용한다(단일 진실 원천).
`rotation > 0`인데 제외 집합이 없으면 **거부**한다(fail-closed).

subject 비종속 (acceptance ⑤ 후단)
----------------------------------
`subject_id`를 처음부터 스키마에 둔다(기본 `"math"`). Validation 계층이 수학 전용이 되지
않게 하는 좌석이며, 값 어휘는 대장 `subject`(str) 관례를 따른다(ARCH-28 — enum 미승격).

측정 도구 실패 경로 설계 (2026-08-22 규칙)
------------------------------------------
  - **단계별 즉시 flush** — CLI는 로드 단계마다 건수·실패 사유를 그 자리에서 출력한다.
  - **실패 원인 보존** — 파싱 실패는 예외 타입명 + 줄 번호로 전건 보고(값·원문 미출력).
  - **미측정 ≠ 0** — 승격 0건은 "통과"가 아니라 **exit 1**(측정 실패). 제외 사유별 건수를
    항상 보고한다(모호 승인·앵커 미매핑·비종결 이벤트).
  - **외부 프로세스 0** — 파일 I/O만 한다(서브프로세스·네트워크 없음).

사용:
    python -m whymath_backend.harness.golden_benchmark \\
        --events review_timer.jsonl --anchor-map anchors.jsonl \\
        --out data/corpus/golden_benchmark_v1/golden.json --golden-version v1 --rotation 0
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

from whymath_backend.harness.review_timer import load_events_jsonl
from whymath_backend.harness.reviewer_sample_package import rotation_key
from whymath_backend.ops.hit_cu_metrics import effective_moment
from whymath_backend.schema.enums import GenerationFailureCode
from whymath_backend.schema.review_timer import (
    ReviewTimerEvent,
    ReviewTimerEventType,
    ReviewVerdict,
)

__all__ = [
    "ANCHOR_IDS",
    "ANCHOR_QUOTA_MAX",
    "ANCHOR_QUOTA_MIN",
    "DEFAULT_SUBJECT_ID",
    "GOLDEN_SCHEMA_VERSION",
    "AsFoundBasis",
    "GoldenItem",
    "GoldenLabel",
    "GoldenSet",
    "PromotionReport",
    "append_evaluation_ledger",
    "compute_digest",
    "edit_aware_verdict_available",
    "find_rescore_violation",
    "freeze_golden_set",
    "load_evaluation_ledger",
    "load_golden_set",
    "main",
    "promote_from_events",
    "render_promotion_report",
    "select_by_anchor",
    "write_golden_set",
]

_EXIT_OK = 0
_EXIT_MEASUREMENT_FAIL = 1

GOLDEN_SCHEMA_VERSION = 1
"""골든 셋 파일 스키마 버전 — 구조가 바뀌면 올린다(내용 버전 `golden_version`과 별개 축)."""

# 앵커 6개 id(EOS-51 검증설계서 §1-1 확정·§2 표) — **코드셋의 정본은
# `scripts/analysis/eos_anchor_asset_audit.py::ANCHOR_DEFS`**이고 여기는 id 집합만 소비한다
# (성취기준 코드 → 앵커 해석은 EOS-56 1급 등록의 몫 — 여기서 재구현하지 않는다).
# 두 목록의 정합은 `tests/backend/harness/test_golden_benchmark.py`가 기계로 동결한다.
ANCHOR_IDS: frozenset[str] = frozenset({"A1", "A2", "A3", "A4", "A5", "A6"})

# 앵커당 표본 목표(§3.7 "앵커 6개 × 30~35건 ≈ 200건") — 게이트 값이 아니라 규약 상수다.
ANCHOR_QUOTA_MIN = 30
ANCHOR_QUOTA_MAX = 35

DEFAULT_SUBJECT_ID = "math"
"""subject 축 기본값 — 대장 `subject`(str) 관례(ARCH-28). Validation의 Math 비종속 좌석."""


class GoldenLabel(str, Enum):
    """골든 정답지 라벨 2값 — QA 엔진이 *본 입력*(as-found)이 결함인가 아닌가."""

    DEFECTIVE = "defective"
    """as-found 상태에 결함이 있었다(검출되어야 하는 쪽 = 혼동행렬의 positive)."""

    CLEAN = "clean"
    """as-found 상태가 무결했다(통과되어야 하는 쪽)."""


class AsFoundBasis(str, Enum):
    """이 라벨이 *검수 전* 상태를 말한다고 믿는 근거 — 승격 경로 3종(acceptance ⑥)."""

    REJECTED_FAILURE_CODE = "rejected_failure_code"
    """반려 판정 + F1~F8. 반려는 정의상 손질 전 판정이라 그대로 as-found다."""

    PRE_REVIEW_SNAPSHOT = "pre_review_snapshot"
    """ⓐ 검수 전 불변 스냅샷 + as-found 결함 라벨을 외부에서 제공받았다."""

    EDIT_AWARE_VERDICT = "edit_aware_verdict"
    """ⓑ EOS-62 edit-aware verdict 착지 이후 검수분 — 손질 여부가 판정값에 실려 있다."""


class GoldenItem(BaseModel):
    """골든 1건 — 한 CU의 as-found 정답지 라벨과 그 출처."""

    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=True)

    cu_slug: str = Field(min_length=1, max_length=128, description="CU 식별 slug(검수 축과 동일)")
    subject_id: str = Field(
        default=DEFAULT_SUBJECT_ID,
        min_length=1,
        max_length=64,
        description="과목 축 — Validation 계층의 Math 비종속 좌석(대장 subject 관례·str)",
    )
    anchor_id: str = Field(description="앵커 id(A1~A6) — 앵커별 쿼터·앵커별 FN 보고 축")
    label: GoldenLabel = Field(description="as-found 정답지 라벨(defective|clean)")
    failure_code: GenerationFailureCode | None = Field(
        default=None,
        description="defective일 때의 결함 코드(F1~F8) — 어떤 결함류를 놓치는지의 분해 축. "
        "clean에는 금지",
    )
    as_found_basis: AsFoundBasis = Field(description="as-found라고 믿는 근거(승격 경로)")
    reviewer_id: str | None = Field(
        default=None, max_length=100, description="검수 행위자 핸들(추적용·학생 축 아님)"
    )
    source_event_id: str | None = Field(
        default=None, description="승격 원본 검수 이벤트 id(추적용). 스냅샷 경로는 None 가능"
    )
    reviewed_at: datetime | None = Field(
        default=None, description="검수 판정 귀속 시각(발생 우선·수신 폴백). 미상 가능"
    )

    @model_validator(mode="after")
    def _enforce_label_shape(self) -> "GoldenItem":
        """라벨 × 실패코드 교차 계약 — clean에 결함코드가 붙으면 라벨이 자기모순이다."""
        if self.anchor_id not in ANCHOR_IDS:
            raise ValueError(f"앵커 id는 {sorted(ANCHOR_IDS)} 중 하나여야 한다: {self.anchor_id}")
        if self.label == GoldenLabel.CLEAN and self.failure_code is not None:
            raise ValueError("clean 라벨에 failure_code 금지 — 무결한데 결함코드는 모순")
        return self


class GoldenSet(BaseModel):
    """동결된 골든 셋 — 버전·회전·동결시점·내용 digest를 함께 박는다(acceptance ③)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(default=GOLDEN_SCHEMA_VERSION, description="파일 스키마 버전")
    golden_version: str = Field(min_length=1, max_length=64, description="내용 버전 라벨(예: v1)")
    rotation: int = Field(ge=0, description="S2-11 표본 회전 인덱스 — 재판정은 다음 rotation")
    frozen_at: datetime = Field(description="동결 시점(UTC)")
    subject_id: str = Field(default=DEFAULT_SUBJECT_ID, description="셋 전체의 과목 축")
    digest: str = Field(min_length=64, max_length=64, description="내용 sha256(재채점 식별 키)")
    items: tuple[GoldenItem, ...] = Field(description="골든 항목(cu_slug 오름차순 정렬)")

    @model_validator(mode="after")
    def _enforce_digest(self) -> "GoldenSet":
        """digest는 내용의 함수다 — 손편집으로 라벨만 바꾸면 즉시 불일치로 드러난다."""
        expected = compute_digest(self.items)
        if self.digest != expected:
            raise ValueError("digest 불일치 — 골든 내용이 동결 이후 변조됐다(재동결 필요)")
        return self


def canonical_value(value: object) -> str:
    """enum·문자열 혼재 값을 **값 문자열**로 — `str(enum)`은 파이썬 repr을 낸다.

    `GenerationFailureCode`·`GoldenLabel`·`AsFoundBasis`는 `(str, Enum)`이라
    `str(GenerationFailureCode.F1) == "GenerationFailureCode.F1"`이다(Python 3.11+ 실측).
    검증을 거친 `GoldenItem`은 `use_enum_values=True`로 이미 `str`("F1")을 들고 있지만,
    그 사실은 멀리 떨어진 model_config에 기대는 것이라 `model_construct` 같은 검증 우회
    경로에서 enum 인스턴스가 들어오면 digest·JSON 키가 **조용히** repr로 갈라진다(EOS-75
    실측: 같은 정답지가 다른 digest를 내 재채점 금지 원장이 "다른 골든"으로 오판). 표기를
    한 곳에서 `.value`로 고정한다 — 생산자 `qa_confusion_matrix`의 JSON 키도 이 함수를 쓴다.
    """
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


def compute_digest(items: Sequence[GoldenItem]) -> str:
    """골든 내용 digest — 판정에 쓰이는 필드만으로 계산(정렬 무관·부기 필드 무관).

    포함 축 = (cu_slug, subject_id, anchor_id, label, failure_code, as_found_basis).
    reviewer_id·시각·원본 이벤트 id는 *부기*라 digest에 넣지 않는다 — 같은 정답지를 다른
    추적 메타로 다시 쓴 것을 "다른 골든"으로 오판하지 않기 위해서다.
    enum 축은 `canonical_value`로 값 문자열을 쓴다 — 검증 경유(str)·검증 우회(enum) 항목이
    같은 정답지면 같은 digest여야 한다(EOS-75). 검증 경유 항목에서는 기존 digest와 동일하다.
    """
    payload = sorted(
        (
            item.cu_slug,
            item.subject_id,
            item.anchor_id,
            canonical_value(item.label),
            canonical_value(item.failure_code) if item.failure_code is not None else "",
            canonical_value(item.as_found_basis),
        )
        for item in items
    )
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def edit_aware_verdict_available() -> bool:
    """EOS-62(edit-aware verdict)가 착지했는가 — `ReviewVerdict` 어휘를 *실측*한다.

    상수로 박지 않는 이유: 이 저장소의 반복 사고("선언과 실체 불일치")를 피하려면 하류 계약이
    상류 어휘를 직접 보고 판정해야 한다. EOS-62가 착지하면 이 함수가 자동으로 True가 되고,
    착지 전에는 아무도 손대지 않아도 fail-closed가 유지된다.

    **2026-09-01 EOS-62 착지로 현재 True를 낸다** — 설계대로 이 파일은 한 줄도 바뀌지 않은 채
    경로 ⓑ가 열렸다. 함수를 상수 `True`로 대체하지 않는다: 어휘가 롤백되거나 하류가 구버전
    schema와 함께 배포되면 다시 False여야 하고, 그때 fail-closed가 살아 있어야 한다.
    """
    return _EDIT_AWARE_VALUE in get_args(ReviewVerdict)


_EDIT_AWARE_VALUE = "approved_with_edit"
"""EOS-62가 추가할 verdict 값 — 어휘 실측의 탐침 문자열(여기 상수는 *기대*이지 선언이 아니다)."""


@dataclass(frozen=True, slots=True)
class AnchorRow:
    """앵커 매핑 1행 — cu_slug를 앵커·과목 축에 붙인다(검수 이벤트에는 앵커 축이 없다)."""

    cu_slug: str
    anchor_id: str
    subject_id: str = DEFAULT_SUBJECT_ID


@dataclass(frozen=True, slots=True)
class AsFoundRow:
    """검수 전 스냅샷 라벨 1행(승격 경로 ⓐ) — 손질 전 상태가 결함이었는지를 외부가 증언한다."""

    cu_slug: str
    label: GoldenLabel
    failure_code: GenerationFailureCode | None = None


@dataclass(frozen=True, slots=True)
class PromotionReport:
    """승격 결과 — 승격분과 **제외분 사유별 건수**를 같은 무게로 보고한다(조용한 포함/제외 금지)."""

    promoted: tuple[GoldenItem, ...]
    total_events: int
    finished_events: int
    excluded_ambiguous_approved: int
    """모호 승인(무손질/손질 후 구분 불가) — acceptance ⑥의 핵심 보고 축."""
    excluded_unmapped_anchor: int
    """앵커 매핑 없음 — 앵커별 쿼터·앵커별 FN 보고가 불가하므로 제외(0 산입 아님)."""
    excluded_unknown_verdict: int
    """어휘 밖 verdict — 상류가 확장됐는데 이 규약이 따라가지 않은 상태(fail-closed)."""
    excluded_duplicate_cu: int
    """같은 CU의 중복 판정 — 최신 1건만 승격(정답지 중복 계수 금지)."""
    edit_aware_available: bool
    edit_aware_since: datetime | None
    as_found_rows: int
    parse_errors: tuple[str, ...] = field(default=())
    prior_golden_slugs: int = 0
    """제외 집합(이전 골든)의 크기 — 재추출 독립성의 근거가 얼마나 있는지."""
    excluded_prior_golden: int = 0
    """이전 골든에 이미 쓰여 이번 선택에서 빠진 승격 후보 수(0이면 겹침이 없었다는 뜻)."""

    @property
    def promoted_count(self) -> int:
        return len(self.promoted)

    @property
    def by_anchor(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.promoted:
            counts[item.anchor_id] = counts.get(item.anchor_id, 0) + 1
        return counts

    @property
    def by_label(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.promoted:
            counts[str(item.label)] = counts.get(str(item.label), 0) + 1
        return counts


def _finish_events(events: Iterable[ReviewTimerEvent]) -> list[ReviewTimerEvent]:
    """종결(finished) 이벤트만 — started/aborted는 판정이 없어 라벨이 되지 못한다."""
    return [e for e in events if e.event_type == ReviewTimerEventType.FINISHED]


def promote_from_events(
    events: Sequence[ReviewTimerEvent],
    *,
    anchor_rows: Sequence[AnchorRow],
    as_found_rows: Sequence[AsFoundRow] = (),
    edit_aware_since: datetime | None = None,
) -> PromotionReport:
    """검수 이벤트 → 골든 후보 승격 (acceptance ①⑥ — fail-closed).

    같은 CU에 판정이 여러 건이면 **귀속 시각이 가장 늦은 1건**만 승격한다(시각 미상은 가장
    이른 것으로 취급 — 최신 판정이 이긴다). 승격 실패는 전부 사유별로 카운트된다.
    """
    anchors = {row.cu_slug: row for row in anchor_rows}
    as_found = {row.cu_slug: row for row in as_found_rows}
    finished = _finish_events(events)

    edit_aware = edit_aware_verdict_available()
    ambiguous = 0
    unmapped = 0
    unknown_verdict = 0

    # CU별 최신 판정 1건으로 축약 — 중복 계수 금지(정답지에서 한 CU는 한 표다).
    latest: dict[str, ReviewTimerEvent] = {}
    duplicates = 0
    for event in sorted(finished, key=lambda e: (effective_moment(e) or _EPOCH, str(e.event_id))):
        if event.cu_slug in latest:
            duplicates += 1
        latest[event.cu_slug] = event

    promoted: list[GoldenItem] = []
    for cu_slug in sorted(latest):
        event = latest[cu_slug]
        anchor = anchors.get(cu_slug)
        if anchor is None:
            unmapped += 1
            continue
        outcome = _resolve_label(
            event,
            as_found=as_found.get(cu_slug),
            edit_aware=edit_aware,
            edit_aware_since=edit_aware_since,
        )
        if outcome is None:
            # 판정별 제외 사유 분류 — 어휘 밖 verdict와 모호 승인은 다른 사태다.
            if str(event.verdict) in _KNOWN_VERDICTS:
                ambiguous += 1
            else:
                unknown_verdict += 1
            continue
        label, failure_code, basis = outcome
        promoted.append(
            GoldenItem(
                cu_slug=cu_slug,
                subject_id=anchor.subject_id,
                anchor_id=anchor.anchor_id,
                label=label,
                failure_code=failure_code,
                as_found_basis=basis,
                reviewer_id=event.reviewer_id,
                source_event_id=str(event.event_id),
                reviewed_at=effective_moment(event),
            )
        )

    return PromotionReport(
        promoted=tuple(promoted),
        total_events=len(events),
        finished_events=len(finished),
        excluded_ambiguous_approved=ambiguous,
        excluded_unmapped_anchor=unmapped,
        excluded_unknown_verdict=unknown_verdict,
        excluded_duplicate_cu=duplicates,
        edit_aware_available=edit_aware,
        edit_aware_since=edit_aware_since,
        as_found_rows=len(as_found),
    )


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_KNOWN_VERDICTS = frozenset({"approved", "rejected", _EDIT_AWARE_VALUE})


def _resolve_label(
    event: ReviewTimerEvent,
    *,
    as_found: AsFoundRow | None,
    edit_aware: bool,
    edit_aware_since: datetime | None,
) -> tuple[GoldenLabel, GenerationFailureCode | None, AsFoundBasis] | None:
    """한 판정의 as-found 라벨 해석 — 승격 불가면 None(fail-closed·모듈 docstring ⑥ 표와 1:1)."""
    verdict = str(event.verdict)

    if verdict == "rejected":
        code = event.failure_code
        return (
            GoldenLabel.DEFECTIVE,
            GenerationFailureCode(code) if code is not None else None,
            AsFoundBasis.REJECTED_FAILURE_CODE,
        )

    if verdict not in _KNOWN_VERDICTS:
        return None  # 어휘 밖 — 규약이 상류 확장을 따라가지 않은 상태(추측 승격 금지)

    # ⓐ 검수 전 스냅샷이 있으면 verdict 해상도와 무관하게 그 라벨이 정답지다.
    if as_found is not None:
        code = as_found.failure_code if as_found.label == GoldenLabel.DEFECTIVE else None
        return (as_found.label, code, AsFoundBasis.PRE_REVIEW_SNAPSHOT)

    # ⓑ edit-aware verdict — 어휘 존재 + 계약 착지 이후 검수분에만 적용(소급 재분류 금지).
    if edit_aware and edit_aware_since is not None:
        moment = effective_moment(event)
        if moment is not None and moment >= edit_aware_since:
            if verdict == _EDIT_AWARE_VALUE:
                code = event.failure_code
                return (
                    GoldenLabel.DEFECTIVE,
                    GenerationFailureCode(code) if code is not None else None,
                    AsFoundBasis.EDIT_AWARE_VERDICT,
                )
            return (GoldenLabel.CLEAN, None, AsFoundBasis.EDIT_AWARE_VERDICT)

    return None  # 모호 승인 — 제외하고 건수로 보고한다(조용한 포함 금지)


def select_by_anchor(
    items: Sequence[GoldenItem],
    *,
    quota: int = ANCHOR_QUOTA_MAX,
    rotation: int = 0,
    exclude: Collection[str] = (),
) -> tuple[GoldenItem, ...]:
    """앵커별 쿼터 선택 — 이전 골든 제외 + S2-11 회전 해시 재배열(재추출 메커니즘 재구현 금지).

    **rotation만으로는 신규 표본이 보장되지 않는다**(#928 리뷰 P1 실측): 앵커 후보가 쿼터
    이하면(우리 목표 구간 30~35 = 기본 쿼터 35의 바로 그 구간이다) 회전은 *순서만* 바꾸고
    전건이 선택되므로 같은 셋·같은 digest가 나온다 — 그러면 교정 후 재판정이 원장에
    "재채점"으로 영구 차단된다. 후보가 많아도 겹침은 크게 남는다.

    그래서 독립성의 원천은 **이전 골든의 명시적 제외**(`exclude` = 이전 셋의 cu_slug)이고,
    회전은 그 위에서 순서를 재배열하는 보조 축이다. `rotation > 0`인데 제외 집합이 비어
    있으면 **거부**한다(fail-closed — 독립을 확인할 근거가 없는 재추출은 재추출이 아니다).

    같은 (rotation, exclude)면 바이트 재현(`rotation_key`가 단일 진실 원천 —
    `reviewer_sample_package`). quota를 못 채우는 앵커는 있는 만큼만 담고, 부족분·후보
    소진은 리포트가 드러낸다(0 채움·묵인 금지).
    """
    if quota <= 0:
        raise ValueError(f"quota는 1 이상이어야 한다: {quota}")
    excluded = frozenset(exclude)
    if rotation > 0 and not excluded:
        raise ValueError(
            "rotation>0에는 이전 골든의 slug 제외 집합이 필요하다 — 회전만으로는 신규 표본이 "
            "보장되지 않는다(후보 ≤ 쿼터면 순서만 바뀌고 같은 셋·같은 digest가 나온다). "
            "이전 동결 셋을 --exclude-golden으로 넘겨라"
        )
    buckets: dict[str, list[GoldenItem]] = {}
    for item in items:
        if item.cu_slug in excluded:
            continue  # 이전 골든에 쓰인 표본 — 재채점 금지의 실질(같은 표본 재사용 차단)
        buckets.setdefault(item.anchor_id, []).append(item)
    selected: list[GoldenItem] = []
    for anchor_id in sorted(buckets):
        ordered = sorted(buckets[anchor_id], key=lambda i: (rotation_key(i.cu_slug, rotation)))
        selected.extend(ordered[:quota])
    return tuple(sorted(selected, key=lambda i: i.cu_slug))


def freeze_golden_set(
    items: Sequence[GoldenItem],
    *,
    golden_version: str,
    rotation: int = 0,
    subject_id: str = DEFAULT_SUBJECT_ID,
    frozen_at: datetime | None = None,
) -> GoldenSet:
    """골든 셋 동결 — 버전·회전·시점·digest를 박아 "어느 셋으로 쟀는가"를 식별 가능하게 한다."""
    ordered = tuple(sorted(items, key=lambda i: i.cu_slug))
    return GoldenSet(
        golden_version=golden_version,
        rotation=rotation,
        frozen_at=frozen_at or datetime.now(UTC),
        subject_id=subject_id,
        digest=compute_digest(ordered),
        items=ordered,
    )


def write_golden_set(path: Path, golden: GoldenSet) -> None:
    """동결 셋 저장 — 부모 디렉터리를 만들고 즉시 flush(중간에 죽어도 파일은 온전)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = golden.model_dump(mode="json")
    with path.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2, sort_keys=True)
        fp.write("\n")
        fp.flush()


def load_golden_set(path: Path) -> GoldenSet:
    """동결 셋 로드 — digest 검증은 모델 validator가 한다(변조는 로드 시점에 터진다)."""
    with path.open(encoding="utf-8") as fp:
        return GoldenSet.model_validate(json.load(fp))


# ──────────────────────────────────────────────────────────────────────────
# 평가 원장 — 재채점 금지(acceptance ③)의 집행 부품. 소비처 = ops/qa_confusion_matrix.
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class EvaluationRecord:
    """평가 1회의 기록 — (골든 digest, 엔진 리비전, 시각)."""

    digest: str
    engine_revision: str
    evaluated_at: datetime
    golden_version: str = ""
    rotation: int = 0


def append_evaluation_ledger(path: Path, record: EvaluationRecord) -> None:
    """원장 1줄 append + 즉시 flush — 마지막 일괄 저장 금지(중간 중단에도 증거 잔존)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "digest": record.digest,
        "engine_revision": record.engine_revision,
        "evaluated_at": record.evaluated_at.isoformat(),
        "golden_version": record.golden_version,
        "rotation": record.rotation,
    }
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        fp.flush()


def load_evaluation_ledger(path: Path) -> tuple[list[EvaluationRecord], list[str]]:
    """원장 로드 — 파싱 실패는 삼키지 않고 예외 타입명+줄 번호로 돌려준다(침묵 실패 금지)."""
    records: list[EvaluationRecord] = []
    errors: list[str] = []
    if not path.exists():
        return records, errors
    with path.open(encoding="utf-8") as fp:
        for lineno, line in enumerate(fp, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
                records.append(
                    EvaluationRecord(
                        digest=str(row["digest"]),
                        engine_revision=str(row["engine_revision"]),
                        evaluated_at=datetime.fromisoformat(str(row["evaluated_at"])),
                        golden_version=str(row.get("golden_version", "")),
                        rotation=int(row.get("rotation", 0)),
                    )
                )
            except (ValueError, TypeError, KeyError) as exc:
                errors.append(f"{type(exc).__name__}: 원장 {lineno}번째 줄")
    return records, errors


def find_rescore_violation(
    records: Sequence[EvaluationRecord], *, digest: str, engine_revision: str
) -> EvaluationRecord | None:
    """재채점 금지 위반 탐지 — 같은 골든을 *다른* 엔진 리비전으로 다시 재는 첫 기록을 돌려준다.

    같은 리비전 재실행은 위반이 아니다(재현성 S4 확인 — 판정이 바뀌면 안 되는 쪽). 위반이면
    호출자는 통과가 아니라 **exit 1**로 막고 rotation을 올린 신규 표본을 요구한다.
    """
    for record in records:
        if record.digest == digest and record.engine_revision != engine_revision:
            return record
    return None


# ──────────────────────────────────────────────────────────────────────────
# 입력 파서 — 형식 관용(별칭 키 수용)·실패는 사유 보존.
# ──────────────────────────────────────────────────────────────────────────
def _load_jsonl_dicts(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """JSONL → dict 목록. 파싱 실패 줄은 예외 타입명+줄 번호로 수집(값·원문 미출력)."""
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    with path.open(encoding="utf-8") as fp:
        for lineno, line in enumerate(fp, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                obj = json.loads(text)
            except json.JSONDecodeError as exc:
                errors.append(f"{type(exc).__name__}: {path.name} {lineno}번째 줄")
                continue
            if isinstance(obj, dict):
                rows.append(obj)
            else:
                errors.append(f"TypeError: {path.name} {lineno}번째 줄(객체 아님)")
    return rows, errors


def parse_anchor_rows(rows: Iterable[Mapping[str, Any]]) -> tuple[list[AnchorRow], list[str]]:
    """앵커 매핑 파싱 — 식별 키는 cu_slug/slug/code, 앵커 키는 anchor_id/anchor."""
    parsed: list[AnchorRow] = []
    errors: list[str] = []
    for index, row in enumerate(rows, start=1):
        cu_slug = row.get("cu_slug") or row.get("slug") or row.get("code")
        anchor_id = row.get("anchor_id") or row.get("anchor")
        if not cu_slug or not anchor_id:
            errors.append(f"KeyError: 앵커 매핑 {index}번째 행(cu_slug/anchor_id 누락)")
            continue
        if str(anchor_id) not in ANCHOR_IDS:
            errors.append(f"ValueError: 앵커 매핑 {index}번째 행(앵커 id 어휘 밖)")
            continue
        parsed.append(
            AnchorRow(
                cu_slug=str(cu_slug),
                anchor_id=str(anchor_id),
                subject_id=str(row.get("subject_id") or row.get("subject") or DEFAULT_SUBJECT_ID),
            )
        )
    return parsed, errors


def parse_as_found_rows(rows: Iterable[Mapping[str, Any]]) -> tuple[list[AsFoundRow], list[str]]:
    """검수 전 스냅샷 라벨 파싱 — 라벨 키는 as_found_label/label, 코드 키는 failure_code."""
    parsed: list[AsFoundRow] = []
    errors: list[str] = []
    for index, row in enumerate(rows, start=1):
        cu_slug = row.get("cu_slug") or row.get("slug") or row.get("code")
        raw_label = row.get("as_found_label") or row.get("label")
        if not cu_slug or not raw_label:
            errors.append(f"KeyError: as-found {index}번째 행(cu_slug/label 누락)")
            continue
        try:
            label = GoldenLabel(str(raw_label))
        except ValueError as exc:
            errors.append(f"{type(exc).__name__}: as-found {index}번째 행(라벨 어휘 밖)")
            continue
        raw_code = row.get("failure_code")
        code: GenerationFailureCode | None = None
        if raw_code:
            try:
                code = GenerationFailureCode(str(raw_code))
            except ValueError as exc:
                errors.append(f"{type(exc).__name__}: as-found {index}번째 행(실패코드 어휘 밖)")
                continue
        parsed.append(AsFoundRow(cu_slug=str(cu_slug), label=label, failure_code=code))
    return parsed, errors


# ──────────────────────────────────────────────────────────────────────────
# 렌더 — 승격분과 제외분을 같은 무게로 보고("작동한 비율" 원칙 · acceptance ④).
# ──────────────────────────────────────────────────────────────────────────
def render_promotion_report(report: PromotionReport, *, quota: int = ANCHOR_QUOTA_MAX) -> str:
    """승격 리포트 markdown — 0건도 "통과"가 아니라 측정 실패로 읽히게 쓴다."""
    lines: list[str] = ["# 골든 벤치마크 승격 리포트 (EOS-60)", ""]
    lines.append(
        f"- 입력 이벤트 {report.total_events}건 · 종결(finished) {report.finished_events}건"
    )
    lines.append(
        f"- **승격 {report.promoted_count}건** "
        f"(목표 앵커 6 × {ANCHOR_QUOTA_MIN}~{ANCHOR_QUOTA_MAX} ≈ 200)"
    )
    if report.promoted_count == 0:
        lines.append("  - ⚠ **측정 실패** — 승격 0건은 '통과'가 아니다(exit 1).")
    lines.append("")
    lines.append("## 라벨 분포")
    by_label = report.by_label
    for label in (GoldenLabel.DEFECTIVE, GoldenLabel.CLEAN):
        lines.append(f"- {label.value}: {by_label.get(label.value, 0)}건")
    lines.append("")
    lines.append("## 앵커별 승격 수 (쿼터 미달은 그대로 노출)")
    by_anchor = report.by_anchor
    for anchor_id in sorted(ANCHOR_IDS):
        count = by_anchor.get(anchor_id, 0)
        mark = "" if count >= quota else f" · 쿼터({quota}) 미달"
        lines.append(f"- {anchor_id}: {count}건{mark}")
    lines.append("")
    lines.append("## 제외분 (조용한 포함/제외 금지 — 미측정 ≠ 정상)")
    lines.append(
        f"- 모호 승인(무손질/손질 후 구분 불가): **{report.excluded_ambiguous_approved}건**"
    )
    lines.append(f"- 앵커 미매핑: {report.excluded_unmapped_anchor}건")
    lines.append(f"- 어휘 밖 verdict: {report.excluded_unknown_verdict}건")
    lines.append(f"- 같은 CU 중복 판정(최신 1건만 승격): {report.excluded_duplicate_cu}건")
    lines.append("")
    lines.append("## 회전·재추출 (acceptance ③ — 재채점 금지의 실질)")
    lines.append(f"- 이전 골든 제외 집합: {report.prior_golden_slugs}건")
    lines.append(f"- 그중 이번 후보와 겹쳐 제외된 건수: {report.excluded_prior_golden}건")
    if report.prior_golden_slugs == 0:
        lines.append(
            "  - 제외 집합 없음 → rotation 0(초판)만 가능하다. 교정 후 재판정은 이전 동결 셋을 "
            "`--exclude-golden`으로 넘겨야 **독립 표본**이 된다(회전만으로는 같은 셋이 나온다)."
        )
    lines.append("")
    lines.append("## as-found 라벨 무결성 경로 (acceptance ⑥)")
    lines.append(
        f"- ⓑ edit-aware verdict 어휘(EOS-62): "
        f"{'착지' if report.edit_aware_available else '**미착지**'}"
    )
    since = report.edit_aware_since.isoformat() if report.edit_aware_since else "미지정"
    lines.append(f"- ⓑ 적용 시작 시각(--edit-aware-since): {since}")
    lines.append(f"- ⓐ 검수 전 스냅샷 라벨 행: {report.as_found_rows}건")
    if not report.edit_aware_available and report.as_found_rows == 0:
        lines.append(
            "  - ⓐ·ⓑ 둘 다 없음 → **approved는 전부 제외**(fail-closed). 반려분만 골든이 된다 — "
            "clean 라벨이 없으면 Precision·오검출 축은 측정 불가다."
        )
    if report.parse_errors:
        lines.append("")
        lines.append(f"## 파싱 실패 {len(report.parse_errors)}건 (사유 보존)")
        lines.extend(f"- {reason}" for reason in report.parse_errors)
    return "\n".join(lines) + "\n"


def _say(message: str) -> None:
    """단계별 진행·판정 출력 — stderr·즉시 flush(중간에 죽어도 어디까지 갔는지 남는다).

    stdout은 데이터(리포트 본문) 전용이다 — `ops/hit_cu_metrics` 동일 규약(#909 codex P2).
    """
    print(message, file=sys.stderr, flush=True)


def main(argv: Sequence[str] | None = None) -> int:
    """골든 승격·동결 CLI — exit 0(승격 ≥1) / 1(측정 실패·입력 부재)."""
    parser = argparse.ArgumentParser(
        prog="golden_benchmark",
        description="검수 판정 → 골든 벤치마크 셋 승격·동결 (EOS-60 acceptance ①③⑥)",
    )
    parser.add_argument("--events", required=True, help="검수 타이머 이벤트 JSONL(EOS-54 산출)")
    parser.add_argument("--anchor-map", required=True, help="cu_slug→앵커 매핑 JSONL")
    parser.add_argument(
        "--as-found-labels", default=None, help="검수 전 스냅샷 라벨 JSONL(승격 경로 ⓐ)"
    )
    parser.add_argument(
        "--edit-aware-since",
        default=None,
        help="EOS-62 edit-aware verdict 계약 착지 시각(ISO8601) — 이후 검수분만 승격 경로 ⓑ 적용",
    )
    parser.add_argument("--golden-version", default="v1", help="골든 내용 버전 라벨(기본 v1)")
    parser.add_argument(
        "--rotation", type=int, default=0, help="S2-11 표본 회전 인덱스(재판정은 다음 rotation)"
    )
    parser.add_argument(
        "--exclude-golden",
        action="append",
        default=None,
        metavar="PATH",
        help="이전 동결 골든 셋 JSON(반복 가능) — 그 slug를 이번 선택에서 제외한다. "
        "rotation>0의 필수 입력(회전만으로는 신규 표본이 보장되지 않음)",
    )
    parser.add_argument(
        "--quota", type=int, default=ANCHOR_QUOTA_MAX, help=f"앵커당 쿼터(기본 {ANCHOR_QUOTA_MAX})"
    )
    parser.add_argument("--subject-id", default=DEFAULT_SUBJECT_ID, help="과목 축(기본 math)")
    parser.add_argument("--out", default=None, help="동결 골든 셋 저장 경로(JSON)")
    parser.add_argument("--report", default=None, help="승격 리포트 markdown 저장 경로")
    args = parser.parse_args(argv)

    events_path = Path(args.events)
    if not events_path.exists():
        _say(f"[측정 실패] FileNotFoundError: 이벤트 파일 없음 — {events_path}")
        return _EXIT_MEASUREMENT_FAIL
    events, event_errors = load_events_jsonl(events_path)
    _say(f"[① 이벤트] {len(events)}건 · 파싱 실패 {len(event_errors)}건 — {events_path}")
    for reason in event_errors:
        _say(f"  · {reason}")

    anchor_path = Path(args.anchor_map)
    if not anchor_path.exists():
        _say(f"[측정 실패] FileNotFoundError: 앵커 매핑 없음 — {anchor_path}")
        return _EXIT_MEASUREMENT_FAIL
    anchor_dicts, anchor_load_errors = _load_jsonl_dicts(anchor_path)
    anchor_rows, anchor_parse_errors = parse_anchor_rows(anchor_dicts)
    _say(
        f"[② 앵커 매핑] {len(anchor_rows)}건 · 실패 "
        f"{len(anchor_load_errors) + len(anchor_parse_errors)}건 — {anchor_path}"
    )
    for reason in (*anchor_load_errors, *anchor_parse_errors):
        _say(f"  · {reason}")

    as_found_rows: list[AsFoundRow] = []
    as_found_errors: list[str] = []
    if args.as_found_labels:
        as_found_path = Path(args.as_found_labels)
        if not as_found_path.exists():
            _say(f"[측정 실패] FileNotFoundError: as-found 라벨 파일 없음 — {as_found_path}")
            return _EXIT_MEASUREMENT_FAIL
        as_found_dicts, load_errors = _load_jsonl_dicts(as_found_path)
        as_found_rows, parse_errors = parse_as_found_rows(as_found_dicts)
        as_found_errors = [*load_errors, *parse_errors]
        _say(
            f"[③ as-found 스냅샷] {len(as_found_rows)}건 · 실패 {len(as_found_errors)}건 — "
            f"{as_found_path}"
        )
        for reason in as_found_errors:
            _say(f"  · {reason}")

    edit_aware_since: datetime | None = None
    if args.edit_aware_since:
        try:
            edit_aware_since = datetime.fromisoformat(args.edit_aware_since)
        except ValueError as exc:
            _say(f"[측정 실패] {type(exc).__name__}: --edit-aware-since 파싱 불가")
            return _EXIT_MEASUREMENT_FAIL
        if edit_aware_since.tzinfo is None:
            edit_aware_since = edit_aware_since.replace(tzinfo=UTC)
        if not edit_aware_verdict_available():
            _say(
                "[주의] --edit-aware-since가 지정됐으나 ReviewVerdict 어휘에 "
                f"'{_EDIT_AWARE_VALUE}'가 없다(EOS-62 미착지) — 경로 ⓑ는 적용되지 않는다."
            )

    exclude_slugs: set[str] = set()
    for raw_path in args.exclude_golden or []:
        prior_path = Path(raw_path)
        if not prior_path.exists():
            _say(f"[측정 실패] FileNotFoundError: 제외용 이전 골든 없음 — {prior_path}")
            return _EXIT_MEASUREMENT_FAIL
        try:
            prior = load_golden_set(prior_path)
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            _say(f"[측정 실패] {type(exc).__name__}: 이전 골든 로드 불가 — {prior_path}")
            return _EXIT_MEASUREMENT_FAIL
        exclude_slugs.update(item.cu_slug for item in prior.items)
        _say(
            f"[④ 제외] 이전 골든 {len(prior.items)}건 (version={prior.golden_version} "
            f"rotation={prior.rotation}) — {prior_path}"
        )

    report = promote_from_events(
        events,
        anchor_rows=anchor_rows,
        as_found_rows=as_found_rows,
        edit_aware_since=edit_aware_since,
    )
    try:
        selected = select_by_anchor(
            report.promoted,
            quota=args.quota,
            rotation=args.rotation,
            exclude=exclude_slugs,
        )
    except ValueError as exc:
        # rotation>0인데 제외 집합 없음 — 독립 표본을 확인할 근거가 없다(fail-closed).
        _say(f"[측정 실패] {type(exc).__name__}: {exc}")
        return _EXIT_MEASUREMENT_FAIL
    overlapped = sum(1 for item in report.promoted if item.cu_slug in exclude_slugs)
    selected_report = PromotionReport(
        promoted=selected,
        total_events=report.total_events,
        finished_events=report.finished_events,
        excluded_ambiguous_approved=report.excluded_ambiguous_approved,
        excluded_unmapped_anchor=report.excluded_unmapped_anchor,
        excluded_unknown_verdict=report.excluded_unknown_verdict,
        excluded_duplicate_cu=report.excluded_duplicate_cu,
        edit_aware_available=report.edit_aware_available,
        edit_aware_since=report.edit_aware_since,
        as_found_rows=report.as_found_rows,
        parse_errors=(
            *event_errors,
            *anchor_load_errors,
            *anchor_parse_errors,
            *as_found_errors,
        ),
        prior_golden_slugs=len(exclude_slugs),
        excluded_prior_golden=overlapped,
    )

    rendered = render_promotion_report(selected_report, quota=args.quota)
    # 데이터는 stdout(리포트 본문), 진행·판정은 stderr(_say) — 분리.
    print(rendered, flush=True)

    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered, encoding="utf-8")
        _say(f"[리포트] {report_path}")

    # 파싱 실패가 하나라도 있으면 승격하지 않는다 — 깨진 행이 하필 반려 판정이었다면
    # 정답지에서 defective 1건이 조용히 사라진 채 골든이 동결된다(부분 입력 판정 금지·
    # hit_cu_metrics 동일 규약). 리포트는 이미 출력했으므로 증거는 남는다.
    if selected_report.parse_errors:
        _say(
            f"[측정 실패] 파싱 실패 {len(selected_report.parse_errors)}건 — 유실된 행이 정답지를 "
            "바꿨을 수 있어 부분 입력으로는 동결하지 않는다(입력을 고치고 재실행)"
        )
        return _EXIT_MEASUREMENT_FAIL
    if selected_report.promoted_count == 0:
        _say("[측정 실패] 승격 0건 — 골든 셋을 만들 수 없다(통과 아님·exit 1).")
        return _EXIT_MEASUREMENT_FAIL

    golden = freeze_golden_set(
        selected,
        golden_version=args.golden_version,
        rotation=args.rotation,
        subject_id=args.subject_id,
    )
    _say(
        f"[동결] version={golden.golden_version} rotation={golden.rotation} "
        f"digest={golden.digest[:12]}… items={len(golden.items)}"
    )
    if args.out:
        out_path = Path(args.out)
        write_golden_set(out_path, golden)
        _say(f"[저장] {out_path}")
    return _EXIT_OK


if __name__ == "__main__":  # pragma: no cover - CLI 진입점
    sys.exit(main())
