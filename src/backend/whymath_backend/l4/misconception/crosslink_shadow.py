"""오개념 crosswalk *shadow 관측* — 노출 없이 kebab-id → M-id 해석을 측정·로깅 (게이트 공존 배선).

`l4/misconception/shadow.py`(의미 매칭 shadow)·`l4/step_shadow.py`(단계-비보존 shadow)의 정본
패턴을 미러한다. 런타임 게이트(증거 저장소 등)는 kebab-id를 *그대로* 런타임 키로 쓰되(현행 불변),
`misconception_crosslink_mode == "shadow"`일 때 crosswalk resolver로 그 kebab-id가 *canonical
M-id로 어떻게 매핑되는지*를 무노출로 해석해 **로그로만** 남긴다 — math_dsl_remediation_design.md
§1.3 step3 "게이트 공존 분기·노출 전 측정(shadow→canary)". crosswalk 테이블은 *사람 검수 전까지
비어 있으므로*(resolve→[]) shadow는 현재 "미매핑(coverage 0)" 분포를 정직하게 수집한다 — 매핑이
검수·적재되며 coverage가 차오르는 것을 노출 전에 관측해 canonical id 플립 근거를 모은다.

비노출·비차단 불변(shadow.py 계승):
- **비노출**: 반환 `None`. 호출자(게이트)가 신호를 받을 변수가 없어 student-facing 누출이 구조적으로
  차단된다 — 노출·DB 저장은 kebab-id 그대로(현행)이고 shadow 로그는 *서버 로그 sink에만* 흐른다.
- **비차단**: resolve(DB 조회)·직렬화·로깅을 한 `try`로 감싸 어떤 예외도 본류(증거 적재)를 안 깬다
  (우선순위: 학생 경험 > 진단 관측·CLAUDE.md #1≫#6). resolve 실패(DB 미도달)도 적재를 막지 않는다.
- **프라이버시**: 레코드엔 학생 식별자·풀이 원문을 *담지 않는다*(미성년 PII) — 담는 건 추상화된
  카탈로그 식별자(kebab-id·M-id)와 개수(비식별·로그 sink 한정·비노출 불변).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from whymath_backend.l1.misconception.crosslink_resolve import (
    CanonicalSelection,
    MisconceptionCrosslinkResolver,
)
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID

logger = logging.getLogger("whymath.l4.misconception.crosslink_shadow")  # shadow.py 네이밍 동형
# 구조화 레코드 JSON 한 줄(harvest 입력) — 평문 로그와 분리된 자식 로거(shadow.record 미러).
record_logger = logging.getLogger("whymath.l4.misconception.crosslink_shadow.record")

# canonical 미해석 시 기본값(관측은 계속 적재 — never-break·정직 미선정과 동일 형태).
_CANONICAL_DEFAULT = CanonicalSelection(
    canonical_mis_id=None, ambiguous=False, direct_count=0, reason="no_links"
)


def _resolve_canonical_safe(
    resolver: MisconceptionCrosslinkResolver, kebab_id: str
) -> CanonicalSelection:
    """canonical 선정을 *실패 허용*으로 해석 — 실패(예: 구식 fake resolver·DB 오류)면 기본값.

    canonical은 shadow 관측의 *부가* 지표라, 해석 실패가 원시 매핑(mis_ids) 관측 적재를 막으면
    안 된다(never-break 계열 — 관측 자체도 잃지 않는다). 기본값은 "미선정"과 동일 형태(정직)다.
    """
    try:
        return resolver.resolve_canonical(kebab_id)
    except Exception:  # noqa: BLE001 — canonical 실패는 관측 적재를 안 깬다(부가 지표)
        return _CANONICAL_DEFAULT


class MisconceptionCrosslinkShadowObservation(BaseModel):
    """crosswalk 해석 shadow 관측 1건의 *구조화 레코드* — record_logger JSON emit (harvest).

    런타임 키인 kebab-id(`kebab_id`)가 crosswalk resolver로 *canonical M-id*(`mis_ids`)에 어떻게
    매핑되는지를 담아, 실 분포에서 매핑 coverage(매핑 유무·다중 매핑)를 무노출로 수집한다.
    **학생 식별자·풀이 원문을 담지 않는다**(shadow.py 규약·프라이버시) — 담는 건 카탈로그 식별자·
    개수(비식별·로그 sink 한정·비노출 불변).
    """

    model_config = ConfigDict(extra="forbid")

    kebab_id: str
    """런타임 게이트가 쓴(노출·DB 저장 기준) kebab-id — 현행 그대로 보존되는 키."""

    kebab_valid: bool
    """`kebab_id`가 정본 kebab 카탈로그(CATALOG_BY_ID)에 실재하는지(게이트 통과 후라 보통 True)."""

    mis_ids: list[str]
    """crosswalk resolver가 해석한 canonical M-id 목록 — 매핑 없으면 [](현재 테이블 비어 보통 []).
    confidence 내림차순(resolver 결정론 순서). 길이>1이면 1:N 모호(canary 정책 결정 입력)."""

    mis_id_count: int
    """`len(mis_ids)` — 0=미매핑(coverage 0)·1=단일 canonical·>1=다중(1:N) 모호."""

    mapped: bool
    """매핑이 1개 이상 존재하는지(`mis_id_count > 0`) — coverage 집계용 플래그."""

    # ── canonical 선정(M2·additive 기본값 — 구 JSONL은 필드 부재 → 기본값 파싱·하위호환) ──
    canonical_mis_id: str | None = None
    """`select_canonical` 정책이 선정한 canonical M-id — 단독 최대 confidence 직접매핑일 때만.
    None이면 미선정(no_links/no_direct/tie 또는 resolve_canonical 실패 — 정직 미선정)."""

    canonical_ambiguous: bool = False
    """직접매핑 최고 confidence 동률(tie) — canonical 플립 전 사람 정책 확정 필요 신호."""

    direct_count: int = 0
    """canonical 후보 자격 링크 수(confidence NOT NULL 직접매핑) — tie·큐레이션 진단용."""

    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def observe_crosslink_shadow(
    misconception_id: str,
    *,
    resolver: MisconceptionCrosslinkResolver | None = None,
    min_confidence: float | None = None,
) -> None:
    """kebab-id → M-id crosswalk 해석을 *로그로만* 관측(shadow·비차단·비노출). 반환 `None`.

    반환이 `None`이라 호출자(게이트)가 신호를 받을 변수가 없다 — student-facing 누출 구조적 차단.
    호출자는 `misconception_crosslink_mode == "shadow"`에서만 부르므로 이 함수는 모드를 재검사하지
    않는다(호출 시점이 곧 shadow·shadow.py 규약 계승). resolver 미주입 시 *지연 생성*한다
    (`MisconceptionCrosslinkResolver()` — 자체 sync 엔진). 해석은 *전부 기록*한다(min_confidence
    기본 None) — shadow는 측정이라 임계로 거르지 않고 분포 전체를 본다(임계는 canary 노출 정책 몫).

    **never-break**(비차단 방어선·shadow.py 미러): resolve(DB 조회)·직렬화·로깅을 한 `try`로 감싸
    *어떤 예외도* 본류(증거 적재)를 깨지 않는다 — DB 미도달·resolver 오류여도 게이트는 정상 진행한다
    (우선순위: 학생 경험·적재 무결성 > 진단 관측). 이 함수는 *부수효과(로그)만* 낸다.
    """
    try:
        resolver = resolver or MisconceptionCrosslinkResolver()
        mis_ids = resolver.resolve(misconception_id, min_confidence=min_confidence)
        # canonical 선정(부가 지표) — 실패해도 원시 관측 적재 불변(_resolve_canonical_safe).
        canonical = _resolve_canonical_safe(resolver, misconception_id)
        logger.info(
            "crosslink shadow(비노출) — kebab=%s valid=%s mis_ids=%s (count=%d) canonical=%s "
            "(ambiguous=%s direct=%d)",
            misconception_id,
            misconception_id in CATALOG_BY_ID,
            mis_ids,
            len(mis_ids),
            canonical.canonical_mis_id,
            canonical.ambiguous,
            canonical.direct_count,
        )
        record_logger.info(
            MisconceptionCrosslinkShadowObservation(
                kebab_id=misconception_id,
                kebab_valid=misconception_id in CATALOG_BY_ID,
                mis_ids=mis_ids,
                mis_id_count=len(mis_ids),
                mapped=len(mis_ids) > 0,
                canonical_mis_id=canonical.canonical_mis_id,
                canonical_ambiguous=canonical.ambiguous,
                direct_count=canonical.direct_count,
            ).model_dump_json()
        )
    # 관측 방어선 — 관측은 본류를 안 깬다(비차단 방어선·shadow.py:107 미러)
    except Exception as exc:  # noqa: BLE001
        # 침묵 실패 금지 — 타입명만 남긴다(메시지는 학생 답안을 담을 수 있어 제외).
        logger.warning("crosslink shadow 관측 실패: %s", type(exc).__name__)
        return


async def observe_crosslink_shadow_async(
    misconception_id: str,
    *,
    resolver: MisconceptionCrosslinkResolver | None = None,
    min_confidence: float | None = None,
) -> None:
    """`observe_crosslink_shadow`의 async 래퍼 — resolve(sync DB)를 스레드로 오프로드(루프 무블록).

    crosswalk resolver는 sync 엔진(`misconception_semantic_mode`·api/gating 선례 동형)이라, async
    게이트(`evidence_store.log_evidence`)에서 호출할 때 `asyncio.to_thread`로 워커 스레드에 넘겨
    이벤트 루프를 블록하지 않는다. sync 헬퍼가 이미 never-break지만, to_thread 자체 실패까지 한 번
    더 `try`로 감싼다(비차단 이중 방어선). 반환 `None`(비노출 불변).
    """
    try:
        await asyncio.to_thread(
            observe_crosslink_shadow,
            misconception_id,
            resolver=resolver,
            min_confidence=min_confidence,
        )
    except Exception as exc:  # noqa: BLE001 — 관측은 본류를 안 깬다(비차단·to_thread 방어선)
        logger.warning("crosslink shadow async 래퍼 실패(to_thread): %s", type(exc).__name__)
        return


__all__ = [
    "MisconceptionCrosslinkShadowObservation",
    "observe_crosslink_shadow",
    "observe_crosslink_shadow_async",
]
