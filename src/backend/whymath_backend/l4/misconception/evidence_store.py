"""WH-1 학습 증거 저장소 — `evidence_links` 적재·진단 조회·보존 파기(설계 04a §2.3·§3 도구7).

설계 정본: `docs/architecture/04a_wh1_tutoring_harness.md` §2.3(학습 증거 그래프)·§3 도구7
(`log_evidence`). 하네스가 verify/match 신호로 증거를 *적재*(`log_evidence`)하고, 진단·학부모
리포트가 *조회*(`get_evidence_for_misconception`·`net_support`)한다. 보존 기한 경과분은 야간 배치
(`purge_expired`)로 파기한다(삭제권은 `student_id` FK CASCADE가 학생 삭제 시 자동 처리).

배치(L4·hypothesis_store 옆): 증거는 per-student 오개념 가설의 *근거*라 오개념 패키지에 둔다.
`CATALOG_BY_ID`(같은 L4 패키지)로 참조 무결성을 강제하고, `EvidenceLink`(L1 모델)을 import한다
(L4→L1 허용).

저장소 패턴(`hypothesis_store.py`·WH-S 저장소 선례 답습):
  - 모든 함수는 `AsyncSession`을 *주입받는다*. 트랜잭션 commit은 호출자 관리.
  - **순수 ORM/쿼리빌더만**(원시 SQL 0). `log_evidence`는 BIGSERIAL `link_id`를 호출자가 바로 쓰게
    `flush`+`refresh`(commit은 호출자).

★게이트(참조 무결성·정합): `log_evidence`는 적재 전 ① `misconception_id ∈ CATALOG_BY_ID`(정본
오개념 실재·`validate_distractor_map` 패턴) ② `polarity ∈ {−1,+1}`(DB CHECK 이중)를 강제한다.
위반은 `EvidenceValidationError`. *거짓 증거(미등록 오개념·잘못된 극성)가 진단 그래프에 유입되는
것을 차단*한다(CLAUDE.md 정확성 #1·거짓 낙인 방지).

개인정보(§2.3): 민감 학생 데이터지만 식별자·극성·가중치·날짜만 담아 평문 적정. 삭제권은 모델
FK CASCADE + 본 모듈 `purge_expired`(보존 경과)로 보장. API 노출은 하네스/리포트 계층 몫(후속).

범위 밖(후속): `curate_hypothesis`(증거→가설 세트·감쇠·ε-규칙·하네스)·BKT 초기화·pgvector 삭제까지
단일 트랜잭션 삭제 오케스트레이션·`select_probe`. 본 모듈은 *증거 CRUD + 진단 집계*만 둔다.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.config import get_settings
from whymath_backend.db.models.evidence_link import EvidenceLink
from whymath_backend.l1.misconception.crosslink_resolve import MisconceptionCrosslinkResolver
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.l4.misconception.crosslink_shadow import observe_crosslink_shadow_async

__all__ = [
    "EvidenceValidationError",
    "default_retention_until",
    "get_evidence_for_misconception",
    "get_evidence_for_student",
    "log_evidence",
    "net_support",
    "net_support_by_misconception",
    "CORRECT_FORM_DEMONSTRATED",
    "purge_expired",
    "strong_refutation_mids",
]

_VALID_POLARITY = (-1, 1)


def default_retention_until(logged_on: date, *, years: int) -> date:
    """적재일 기준 기본 보존기한 = `logged_on + years`년(순수·윤년 안전).

    GDPR 데이터 최소화 — 미성년 증거를 *무기한 보존하지 않도록* 적재 시 만료일을 박는다.
    2/29 적재분은 비윤년에 2/28로 클램프(ValueError 회피). `years`는 Settings로 조정
    (`evidence_retention_years`·기본 3·법무 확정 시 변경).
    """
    try:
        return logged_on.replace(year=logged_on.year + years)
    except ValueError:  # 2/29 → +years년이 비윤년이면 2/28로 클램프.
        return logged_on.replace(year=logged_on.year + years, month=2, day=28)


class EvidenceValidationError(ValueError):
    """증거 적재 게이트 위반 — 미등록 오개념(CATALOG_BY_ID 부재) 또는 잘못된 극성."""


async def log_evidence(
    session: AsyncSession,
    *,
    session_id: uuid.UUID,
    student_id: uuid.UUID,
    misconception_id: str,
    polarity: int,
    event_id: int | None = None,
    node_id: str | None = None,
    weight: float | None = None,
    provenance: str | None = None,
    retention_until: date | None = None,
    logged_on: date | None = None,
    crosslink_resolver: MisconceptionCrosslinkResolver | None = None,
) -> EvidenceLink:
    """증거 엣지 1개를 적재한다(§3 도구7 — 게이트 통과 후).

    게이트(거짓 증거 차단·CLAUDE.md 정확성 #1):
      ① `misconception_id ∈ CATALOG_BY_ID` — 정본 오개념 실재(미등록이면 거짓 낙인 차단).
      ② `polarity ∈ {−1, +1}` — +1 지지/−1 반박만(DB CHECK 이중 가드).
    위반은 `EvidenceValidationError`. `flush`+`refresh`로 DB-assigned `link_id`를 같은 트랜잭션에서
    가시화(commit은 호출자). `student_id` FK CASCADE가 삭제권을 자동 보장한다.

    **보존기한(GDPR 데이터 최소화)**: `retention_until` *미제공 시* `logged_on`(기본 오늘)+
    `Settings.evidence_retention_years`(기본 3년)으로 *자동* 채운다 — 미성년 증거를 무기한 보존
    안 함(`purge_expired`가 경과분 파기). 명시 제공 시 그 값 존중(테스트·특수 정책). `logged_on`은
    테스트 주입용(기본 `date.today()`).

    **crosswalk shadow(게이트 공존 배선·비노출 측정)**: `misconception_crosslink_mode == "shadow"`
    면 적재 직전 kebab-id의 canonical M-id 매핑을 *비차단·비노출*로 해석해 coverage를 로그로만
    남긴다(`crosslink_shadow`) — kebab-id를 *그대로* 저장하는 현행 동작은 불변, resolve 실패도
    적재를 막지 않는다(증거 무결성 우선). `crosslink_resolver`는 테스트 주입용(기본 지연 생성).
    """
    settings = get_settings()
    if misconception_id not in CATALOG_BY_ID:
        raise EvidenceValidationError(
            f"증거 참조 무결성 위반 — misconception_id {misconception_id!r}이(가) "
            "정본 카탈로그(CATALOG_BY_ID)에 없음."
        )
    if polarity not in _VALID_POLARITY:
        raise EvidenceValidationError(
            f"극성 위반 — polarity={polarity!r}(허용 {_VALID_POLARITY} — +1 지지/−1 반박)."
        )
    # crosswalk shadow(비노출 측정·비차단) — 게이트 통과한 kebab-id의 M-id 매핑 coverage를
    # 로그로만 관측한다(노출·아래 DB 저장은 kebab-id 그대로). off면 crosslink 조회 0.
    if settings.misconception_crosslink_mode != "off":
        await observe_crosslink_shadow_async(misconception_id, resolver=crosslink_resolver)
    # GDPR 데이터 최소화 — 명시 미제공 시 적재일+정책 보존년으로 *반드시* 만료일을 박는다
    # (무기한 보존 금지·미성년 데이터). 명시 제공 시 그 값 존중(테스트·특수 정책).
    if retention_until is None:
        retention_until = default_retention_until(
            logged_on or date.today(), years=settings.evidence_retention_years
        )
    link = EvidenceLink(
        session_id=session_id,
        student_id=student_id,
        misconception_id=misconception_id,
        polarity=polarity,
        event_id=event_id,
        node_id=node_id,
        weight=weight,
        provenance=provenance,
        retention_until=retention_until,
    )
    session.add(link)
    await session.flush()
    await session.refresh(link)
    return link


async def get_evidence_for_student(
    session: AsyncSession, student_id: uuid.UUID
) -> list[EvidenceLink]:
    """한 학생의 증거 전체를 적재순 조회(감사·삭제권 일괄 로드). student_id 인덱스 prefix."""
    stmt = (
        select(EvidenceLink)
        .where(EvidenceLink.student_id == student_id)
        .order_by(EvidenceLink.created_at, EvidenceLink.link_id)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_evidence_for_misconception(
    session: AsyncSession, student_id: uuid.UUID, misconception_id: str
) -> list[EvidenceLink]:
    """한 학생의 *한 오개념 가설*을 지지/반박하는 증거를 조회(진단 조인). 복합 인덱스 정확 매칭."""
    stmt = (
        select(EvidenceLink)
        .where(
            EvidenceLink.student_id == student_id,
            EvidenceLink.misconception_id == misconception_id,
        )
        .order_by(EvidenceLink.created_at, EvidenceLink.link_id)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def net_support(session: AsyncSession, student_id: uuid.UUID, misconception_id: str) -> float:
    """오개념 가설의 *순 지지도* = Σ(polarity × COALESCE(weight, 1.0)) — SQL 진단 신호(§2.3).

    양수면 가설 지지 우세·음수면 반박 우세·0이면 균형/증거 없음. "이 학생의 진짜 원인은 X"라는
    진단이 LLM 추론이 아닌 이 집계로 나온다(학부모 리포트 신뢰 근거). 증거 없으면 0.0.
    """
    stmt = select(
        func.coalesce(
            func.sum(EvidenceLink.polarity * func.coalesce(EvidenceLink.weight, 1.0)),
            0.0,
        )
    ).where(
        EvidenceLink.student_id == student_id,
        EvidenceLink.misconception_id == misconception_id,
    )
    result = await session.execute(stmt)
    return float(result.scalar_one())


async def net_support_by_misconception(
    session: AsyncSession, student_id: uuid.UUID
) -> dict[str, float]:
    """한 학생의 *오개념별 순 지지도* 맵 = {misconception_id: Σ(polarity×COALESCE(weight,1.0))}.

    `net_support`의 *배치판*(GROUP BY) — 학생의 모든 증거를 단일 쿼리로 집계해 오개념별 순지지도를
    돌려준다(N+1 회피). 증거가 있는 오개념만 키로 담는다(증거 없는 오개념은 키 부재 → 호출자가
    0.0 취급). 적응형 장면이 *렌더 시점*에 활성 가설을 증거로 재확인(반박 net_support<0 억제·RS2)
    하는 데 쓴다 — `curate_hypothesis`가 턴 시점에 쓰는 `net_support` 신호와 동형(SQL 진단 신호).
    """
    stmt = (
        select(
            EvidenceLink.misconception_id,
            func.coalesce(
                func.sum(EvidenceLink.polarity * func.coalesce(EvidenceLink.weight, 1.0)),
                0.0,
            ),
        )
        .where(EvidenceLink.student_id == student_id)
        .group_by(EvidenceLink.misconception_id)
    )
    result = await session.execute(stmt)
    return {mid: float(support) for mid, support in result.all()}


# MISC-20 — "해소"로 셀 수 있는 증거의 **출처 표식**. 값이 있는 행만 해소 후보이며, 이 상수는
# `correct_form_present`(정정 형태 실측)가 True일 때 coach가 기록한다.
#
# **왜 `weight`로 판정하지 않는가**(Codex P1 수용 · PR #1044): 초판은
# `polarity=-1 AND coalesce(weight, 1.0) >= 0.75`로 가중치에서 출처를 추론했는데 두 곳에서 깨졌다.
#   ① `weight`는 nullable(미평가 None)이라 `coalesce(..., 1.0)`이 **NULL을 최강 신호로** 접었다
#      — *모른다*가 *확정*이 되는 방향이며 CLAUDE.md "모른다 ≠ 아니다"의 정확한 반대다.
#   ② WH-1 하네스의 `LogEvidenceAction.weight`는 **LLM이 지정**한다 — 숫자 하나로 "학생이
#      오개념을 넘어섰다"가 영구 기록될 수 있었다.
# 가중치는 *강도*를 말할 뿐 **누가 무엇을 근거로 썼는지**를 말하지 못한다. 그래서 출처를 1급
# 컬럼으로 분리하고, 이 판정은 그 컬럼만 본다(가중치 무관·NULL은 해소 아님).
CORRECT_FORM_DEMONSTRATED = "correct_form_demonstrated"


async def strong_refutation_mids(
    session: AsyncSession, student_id: uuid.UUID, misconception_ids: Sequence[str]
) -> set[str]:
    """주어진 오개념들 중 **정정 형태를 직접 보였다고 기계가 기록한** 증거가 있는 id 집합(MISC-20).

    "해소"(학생이 실제로 넘어섬)와 "반박"(그냥 안 틀렸음)을 가르는 유일한 신호이며, 판정 축은
    **출처 표식 `provenance == CORRECT_FORM_DEMONSTRATED`**다(가중치가 아니다 — 위 상수 주석의
    ①② 참조). 막연한 clean 풀이의 약한 반박은 출처가 없어 `REFUTED`에 머문다(과대해석 금지 ·
    해소율 분자를 부풀리지 않는다). `provenance`가 NULL인 행(구 데이터·하네스 경로)도 **해소가
    아니다** — 모르는 것을 확정으로 세지 않는다.

    `misconception_ids`가 비면 쿼리 없이 빈 집합(N+1·불필요 왕복 회피). 순수 쿼리빌더만.
    """
    if not misconception_ids:
        return set()
    stmt = (
        select(EvidenceLink.misconception_id)
        .where(
            EvidenceLink.student_id == student_id,
            EvidenceLink.misconception_id.in_(list(misconception_ids)),
            EvidenceLink.polarity == -1,
            EvidenceLink.provenance == CORRECT_FORM_DEMONSTRATED,
        )
        .distinct()
    )
    result = await session.execute(stmt)
    return {mid for (mid,) in result.all()}


async def purge_expired(session: AsyncSession, *, as_of: date) -> int:
    """보존 기한(`retention_until`)이 `as_of` 이전인 증거를 파기한다 — 야간 배치(§2.3 자동 파기).

    `retention_until < as_of`인 레코드만 삭제한다(NULL=무기한은 미삭제). 삭제 행수를 반환한다.
    `idx_evidence_retention`을 탄다. 학생 단위 삭제권은 FK CASCADE가 별도 처리(여기선 보존 만료만).
    트랜잭션 commit은 호출자 관리.
    """
    stmt = (
        delete(EvidenceLink)
        .where(
            EvidenceLink.retention_until.is_not(None),
            EvidenceLink.retention_until < as_of,
        )
        .execution_options(synchronize_session=False)
    )
    result = await session.execute(stmt)
    # DELETE는 CursorResult(rowcount 보유) — Result[Any] 타입 좁히기. -1 드라이버는 0 폴백.
    return cast("CursorResult[Any]", result).rowcount or 0
