"""활성 오개념 가설 per-student 비동기 저장소 — `misconception_hypothesis` 영속 (§8.4 2단계).

설계 정본: `docs/architecture/04a_wh1_tutoring_harness.md` §8.4 2단계·§2.2·§3 도구4
(`curate_hypothesis`). 직전 슬라이스(#191)가 만든 *순수 결정 로직*(`l4/misconception/
hypothesis.py` — `MisconceptionHypothesis`·`decay`·`reinforce`·`update_hypotheses`·`curate`·
`select_focus`)을 per-student로 *영속*하는 seam이다. 본 모듈은 순수 로직을 **재사용**만 하고
(재구현 0), ORM 레코드(`MisconceptionHypothesisRecord`) ↔ 순수 Pydantic
(`MisconceptionHypothesis`)을 변환하며 활성 가설 세트를 로드·갱신·영속한다.

함수 2종(공유 영속 헬퍼 `_persist_active_set` 위에 구축):
  · `apply_matches` — 매치(증거 신호)만 반영하는 하위 좌석(감쇠·강화·임계 가지치기·영속).
  · `curate_hypothesis`(§3 도구4) — 그 위에 **`evidence_links` 순지지도(`net_support`)로 반박된
    가설 archived** + **최대 5개 캡**(§2.2 큐레이션 규칙)을 더한 하네스 도구. 반박 판정이
    LLM 추론이 아닌 증거 그래프 SQL 집계에서 나온다(확증편향 방지·신뢰 근거).

저장소 패턴(`l2/mastery_tracking.py`·`whs/node_store.py` 선례 답습):
  - 모든 함수는 `AsyncSession`을 *주입받는다*(엔진·세션 생성은 호출자 책임).
  - **트랜잭션(commit/rollback)은 호출자 관리** — 여기서 자동 commit하지 않는다. 새 행/갱신이
    같은 트랜잭션에서 가시화돼야 하는 경우만 `flush`한다(commit은 호출자).
  - **순수 ORM/쿼리빌더만 사용**(원시 SQL 0 — CLAUDE.md "ORM/쿼리 빌더").

개인정보(CLAUDE.md 절대 금기): 활성 오개념 가설은 *미성년 학생*에 결부된 **민감 데이터**다
(per-student 진단 후보). 오개념은 *후보일 뿐* 확정 라벨이 아니며(낙인 금지) 가지치기는
`is_active=false` 비활성화로 표현한다. 평문 저장·동의 없는 학습 사용 금지는 *저장·동의
계층*(암호화·미들웨어·PIPA 권한 매트릭스) 책임이다(ORM·저장소엔 가짜 CHECK·동의 게이트를
두지 않는다 — activity.py 패턴 동형).

범위 밖(후속 — 정직 스코프): `log_evidence` *적재* 자체는 증거 저장소(`evidence_store`) 몫이고
본 모듈은 그 집계(`net_support`)를 *소비*만 한다. coach/intervention 결선(`curate_hypothesis`→
개입 발화·학생 세션 경로)·`select_probe`(ε-탐색 문항)·API 엔드포인트 노출·진단-실제 *일치율*
게이트는 모두 후속 슬라이스다.

오개념 crosswalk shadow(게이트 공존 배선·math_dsl_risk_register.md Q10-⑥): `_persist_active_set`은
kebab-id `misconception_id`를 *런타임 키로 영속*하는 게이트라, `evidence_store.log_evidence`와
동일하게 `misconception_crosslink_mode == "shadow"`에서 영속 kebab-id의 canonical M-id 매핑
coverage를 *비노출·비차단*으로 관측한다(노출·DB 저장은 kebab-id 그대로 불변).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.config import get_settings
from whymath_backend.db.models.misconception_hypothesis import (
    MisconceptionHypothesisRecord,
)
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.l4.misconception.crosslink_shadow import observe_crosslink_shadow_async
from whymath_backend.l4.misconception.evidence_store import (
    net_support,
    strong_refutation_mids,
)
from whymath_backend.l4.misconception.hypothesis import (
    DeactivationReason,
    MisconceptionHypothesis,
    curate_with_reasons,
)
from whymath_backend.l4.misconception.models import MisconceptionMatch
from whymath_backend.schema.assessment_evidence import MisconceptionCandidate

__all__ = [
    "apply_matches",
    "curate_hypothesis",
    "get_active_hypotheses",
    "persist_hypotheses",
]


def _to_pydantic(record: MisconceptionHypothesisRecord) -> MisconceptionHypothesis:
    """영속 Record → 순수 Pydantic 가설(Numeric→float 변환).

    `confidence`는 PG Numeric이라 DB 왕복 시 `Decimal`로 올 수 있어 `float`로 캐스팅한다
    (순수 모델은 float·[0,1] 검증). 그 외 필드는 동명 1:1 사본.
    """
    return MisconceptionHypothesis(
        misconception_id=record.misconception_id,
        confidence=float(record.confidence),
        turns_since_evidence=record.turns_since_evidence,
        evidence_count=record.evidence_count,
    )


async def get_active_hypotheses(
    session: AsyncSession, user_id: uuid.UUID
) -> list[MisconceptionHypothesis]:
    """학생의 *활성*(`is_active=true`) 오개념 가설을 confidence 내림차순으로 로드한다(순수 변환).

    `update_hypotheses`/`select_focus`가 가정하는 *내림차순 정렬*을 DB에서 보장한다(동률은
    misconception_id로 안정 tiebreak). 비활성(가지치기된) 행은 제외한다 — 활성 세트만 반환.
    읽기 전용이라 flush/commit 없음(commit은 호출자 관리·없어도 무방).
    """
    stmt = (
        select(MisconceptionHypothesisRecord)
        .where(
            MisconceptionHypothesisRecord.user_id == user_id,
            MisconceptionHypothesisRecord.is_active.is_(True),
        )
        .order_by(
            MisconceptionHypothesisRecord.confidence.desc(),
            MisconceptionHypothesisRecord.misconception_id,
        )
    )
    result = await session.execute(stmt)
    return [_to_pydantic(r) for r in result.scalars().all()]


async def apply_matches(
    session: AsyncSession,
    user_id: uuid.UUID,
    matches: Sequence[MisconceptionMatch],
    *,
    turns_elapsed: int = 1,
) -> list[MisconceptionHypothesis]:
    """학생 가설 세트를 1턴 갱신·영속한다 — #191 순수 로직 재사용 + upsert + 가지치기 비활성화.

    절차:
      1. `get_active_hypotheses`로 현재 활성 가설(순수)을 로드한다.
      2. **#191 `update_hypotheses(current, matches, turns_elapsed)` 재사용**(감쇠→강화/신규→
         가지치기→정렬 — 순수 로직 재구현 0). 결과가 *이번 턴의 활성 세트*다.
      3. 결과를 영속한다 — `(user_id, misconception_id)` 단위로:
           · 기존 행이 있으면 confidence·turns_since_evidence·evidence_count·is_active=true로
             갱신(가지치기됐다 다시 살아난 가설도 재활성화).
           · 없으면 새 행 insert.
         결과 세트에서 *빠진* 기존 활성 행(= 감쇠로 가지치기된 가설)은 `is_active=false`로
         비활성화한다(행 삭제 X — 증거 이력 보존·낙인 방지).
      4. 갱신된 활성 가설(= update_hypotheses 결과)을 반환한다.

    트랜잭션 commit은 호출자 관리(flush로 같은 트랜잭션 내 가시화). 순수 ORM/쿼리빌더만(원시
    SQL 0). 매치는 *증거*일 뿐 진단 알고리즘이 아니다(#191 불변·재구현 0).
    """
    # 1. 현재 활성 가설(순수) 로드.
    current = await get_active_hypotheses(session, user_id)

    # 2. #191 순수 로직 재사용 — 이번 턴 활성 세트 계산(재구현 0).
    # MISC-20: 사유까지 받는 `curate_with_reasons`를 쓴다 — 반박·캡 입력이 없으므로 생존 세트는
    # `update_hypotheses`와 동일하고(캡을 무력화하는 큰 max_active), 사유는 이 경로의 유일한 탈락
    # 원인인 감쇠·임계 가지치기(DECAYED)만 나온다.
    updated, reasons = curate_with_reasons(
        current, matches, turns_elapsed=turns_elapsed, max_active=len(current) + len(matches) + 1
    )

    # 3. 영속(upsert + 빠진 활성 행 비활성화) — curate_hypothesis와 공유하는 헬퍼(중복 0).
    await _persist_active_set(session, user_id, updated, reasons=reasons)

    # 4. 이번 턴 활성 세트(순수) 반환.
    return updated


async def apply_candidates(
    session: AsyncSession,
    user_id: uuid.UUID,
    candidates: Sequence[MisconceptionCandidate],
    *,
    turns_elapsed: int = 1,
) -> list[MisconceptionHypothesis]:
    """채점 증거의 오개념 **후보**를 가설 세트에 반영·영속한다 — `apply_matches` 얇은 래퍼.

    왜 별도 진입점인가: 채점 경로(Core)가 들고 있는 것은 계약 DTO(`MisconceptionCandidate` —
    id·신뢰도·게이트 플래그)이고, 가설 갱신 로직이 요구하는 것은 L4 리치 타입
    (`MisconceptionMatch` — 카탈로그 객체 포함)이다. 그 간극을 Core에서 메우려면 Core가
    카탈로그를 뒤져야 하고, 그러면 같은 변환이 호출처마다 복제된다. 여기서 **한 번만** 한다.

    감쇠·강화·가지치기는 전부 `apply_matches`가 한다(재구현 0). 특히 **후보가 비어 있어도
    호출은 유효하다** — 그 경우 이번 회차에 증거를 못 받은 기존 가설이 `turns_elapsed`만큼
    감쇠하고, 임계 미만이면 비활성화된다. "오개념이 관측되지 않은 시도"가 신뢰를 *내리는*
    경로가 바로 이것이다.

    `gate_passed=False` 후보는 **무시한다**(가설로 승격하지 않는다). 계약상 그런 후보는
    증거에 실릴 수 없고, 저장소가 그 경계를 느슨하게 하면 게이트가 우회 가능해진다.
    카탈로그에 없는 id도 무시한다 — 알 수 없는 오개념으로 학생 상태를 바꾸지 않는다.

    `curate_hypothesis`(증거 그래프 반박·최대 N 캡)를 부르지 *않는다*: 반박 판정과 확정은
    코치 경로가 소유하고, 채점 증거는 관측이라 그 권위를 갖지 않는다(EOS-104 acceptance ④).
    """
    matches = [
        MisconceptionMatch(
            misconception=CATALOG_BY_ID[c.misconception_id],
            confidence=c.confidence,
            attribution_unclear=c.attribution_unclear,
        )
        for c in candidates
        if c.gate_passed and c.misconception_id in CATALOG_BY_ID
    ]
    return await apply_matches(session, user_id, matches, turns_elapsed=turns_elapsed)


async def persist_hypotheses(
    session: AsyncSession,
    user_id: uuid.UUID,
    hypotheses: Sequence[MisconceptionHypothesis],
) -> None:
    """활성 가설 세트를 그대로 영속한다(upsert + 빠진 활성 행 비활성화) — 공개 커밋 진입점.

    WH-1 턴 루프(`harness/wh1_loop.py`)가 *in-memory로 갱신한* 최종 가설 세트를 턴 종료 시 영속할
    때 쓰는 좌석이다(매치 재계산 없이 *결과 세트*만 커밋). 내부 영속 로직(`_persist_active_set`)에
    위임한다(중복 0). 트랜잭션 commit은 호출자 관리(flush로 같은 트랜잭션 가시화).
    """
    await _persist_active_set(session, user_id, hypotheses)


async def _persist_active_set(
    session: AsyncSession,
    user_id: uuid.UUID,
    active: Sequence[MisconceptionHypothesis],
    *,
    reasons: dict[str, DeactivationReason] | None = None,
) -> None:
    """이번 턴 *활성 가설 세트*를 영속한다 — upsert + 빠진 활성 행 비활성화(공통 영속 절차).

    `apply_matches`(매치만 반영)·`curate_hypothesis`(증거·캡까지 반영)가 *공유*하는 영속 로직이다
    (재구현 0). 기존 행을 `(user_id, misconception_id)`로 인덱싱하고(활성·비활성 모두 조회):
      · `active`에 든 가설은 갱신(가지치기/반박됐다 다시 살아난 가설도 `is_active=true`로 재활성화),
        없으면 새 행 insert.
      · `active`에서 *빠진* 기존 *활성* 행(= 가지치기·반박·최대 N 캡 탈락)은 `is_active=false`로
        비활성화한다(행 삭제 X — 증거 이력 보존·낙인 방지·§5.1 archived 보존).

    MISC-20: `reasons`(오개념 id → `DeactivationReason`)를 주면 비활성화 행에 그 사유를 함께
    쓴다. **사유를 모르는 호출자는 주지 않는다** — 그 경우 `deactivated_reason`은 NULL(사유 미상)로
    남으며 해소율 분자에서 제외된다(날조 0 · 04e §9-D4). 재활성화되는 행은 사유를 비운다(옛 사유가
    되살아난 가설에 라벨로 따라다니지 않게 — `is_active` 컨벤션의 낙인 방지 원칙 승계).
    server_default(id·타임스탬프)·갱신을 같은 트랜잭션에서 가시화하도록 `flush`(commit은 호출자).
    """
    existing_stmt = select(MisconceptionHypothesisRecord).where(
        MisconceptionHypothesisRecord.user_id == user_id
    )
    existing_result = await session.execute(existing_stmt)
    by_mid: dict[str, MisconceptionHypothesisRecord] = {
        row.misconception_id: row for row in existing_result.scalars().all()
    }

    active_mids: set[str] = set()
    for hyp in active:
        active_mids.add(hyp.misconception_id)
        record = by_mid.get(hyp.misconception_id)
        if record is not None:
            # upsert(갱신) — 가지치기/반박됐다 다시 살아난 가설도 is_active=true로 재활성화.
            record.confidence = hyp.confidence
            record.turns_since_evidence = hyp.turns_since_evidence
            record.evidence_count = hyp.evidence_count
            record.is_active = True
            # 재활성화 — 옛 탈락 사유를 비운다(현재 활성 행의 사유는 항상 NULL이라는 불변식).
            record.deactivated_reason = None
        else:
            # upsert(insert) — 신규 가설.
            session.add(
                MisconceptionHypothesisRecord(
                    user_id=user_id,
                    misconception_id=hyp.misconception_id,
                    confidence=hyp.confidence,
                    turns_since_evidence=hyp.turns_since_evidence,
                    evidence_count=hyp.evidence_count,
                    is_active=True,
                    deactivated_reason=None,
                )
            )

    # 활성 세트에서 빠진 *활성* 기존 행 = 가지치기·반박·캡 탈락 → 비활성화(삭제 X).
    pruned_mids = [
        mid for mid, record in by_mid.items() if record.is_active and mid not in active_mids
    ]
    if pruned_mids:
        # MISC-20 — 사유별로 묶어 UPDATE한다. 사유를 모르는 id(reasons 미제공·키 부재)는 마지막
        # 묶음에서 `deactivated_reason=None`으로 남는다(사유 미상 정직 표기 — 임의 값 대입 금지).
        by_reason: dict[DeactivationReason | None, list[str]] = {}
        for mid in pruned_mids:
            by_reason.setdefault((reasons or {}).get(mid), []).append(mid)
        for reason, mids in by_reason.items():
            prune_stmt = (
                update(MisconceptionHypothesisRecord)
                .where(
                    MisconceptionHypothesisRecord.user_id == user_id,
                    MisconceptionHypothesisRecord.misconception_id.in_(mids),
                )
                .values(
                    is_active=False,
                    deactivated_reason=reason.value if reason is not None else None,
                )
            )
            await session.execute(prune_stmt)

    # server_default(id·타임스탬프)·갱신을 같은 트랜잭션에서 가시화(commit은 호출자).
    await session.flush()

    # crosswalk shadow(비노출·비차단 측정·게이트 공존 배선) — 이 좌석은 kebab-id를 *런타임 키로
    # 영속*하는 또 하나의 게이트다(evidence_store와 평행). mode != "off"면 영속된 활성 가설 각각의
    # kebab-id가 canonical M-id로 어떻게 매핑되는지를 *로그로만* 관측한다(crosslink_shadow·
    # math_dsl_risk_register.md Q10-⑥·remediation §1.3 step3). 노출·위 DB 저장은 kebab-id 그대로
    # 불변이고, resolve 실패도 영속을 막지 않는다(never-break). 기본 off라 측정 윈도에서만 켠다.
    if get_settings().misconception_crosslink_mode != "off":
        for hyp in active:
            await observe_crosslink_shadow_async(hyp.misconception_id)


async def curate_hypothesis(
    session: AsyncSession,
    *,
    student_id: uuid.UUID,
    matches: Sequence[MisconceptionMatch],
    turns_elapsed: int = 1,
    max_active: int = 5,
) -> list[MisconceptionHypothesis]:
    """증거 그래프를 반영해 학생 활성 가설 세트를 *큐레이션*·영속한다(§3 도구4·§2.2).

    `apply_matches`(매치만 반영)에서 한 걸음 더 — **`evidence_links` 순지지도(`net_support`)로
    반박된 가설을 archived**하고 **최대 N개로 캡**한다(설계 §2.2 큐레이션 규칙·§5.1):
      1. `get_active_hypotheses`로 현재 활성 가설(순수)을 로드한다.
      2. 이번 턴 후보 오개념(현재 활성 가설 ∪ 새 매치) 각각의 `evidence_store.net_support`를
         조회 — *음수*(반박 우세)면 `refuted` 집합에 넣는다. "이 가설은 틀렸다"가 LLM 추측이
         아니라 증거 그래프 SQL 집계에서 나온다(학부모 리포트 신뢰 근거·확증편향 방지).
      3. **#191 순수 `curate(current, matches, turns_elapsed, refuted, max_active)` 재사용** —
         감쇠→강화/신규→임계 가지치기→반박 제거→내림차순→최대 N 캡(재구현 0).
      4. `_persist_active_set`으로 영속(upsert + 탈락 비활성화) 후 활성 세트를 반환한다.

    트랜잭션 commit은 호출자 관리(`_persist_active_set`이 flush로 같은 트랜잭션 가시화). 순수
    ORM/쿼리빌더만(원시 SQL 0). 반박 판정이 *현재까지 누적된 증거*(prior `log_evidence`) 기준이라,
    반박된 가설은 증거 순지지도가 양으로 돌아서기 전엔 새 매치만으로 부활하지 않는다(R4 확증편향
    방지 — 매치는 confidence를 강화하지만 archived 여부는 증거 원장이 결정).
    """
    # 1. 현재 활성 가설(순수) 로드.
    current = await get_active_hypotheses(session, student_id)

    # 2. 후보 오개념(현재 가설 ∪ 새 매치)별 증거 순지지도 → 음수면 반박(archived 신호·§5.1).
    candidate_mids: set[str] = {h.misconception_id for h in current}
    candidate_mids.update(m.misconception.id for m in matches)
    refuted: set[str] = set()
    for mid in candidate_mids:
        if await net_support(session, student_id, mid) < 0.0:
            refuted.add(mid)

    # 3. #191 순수 큐레이션 재사용(감쇠·강화·가지치기·반박 제거·최대 N 캡) — 재구현 0.
    # 2-b. MISC-20 — 반박 중에서도 *정정 형태를 직접 보였다고 기계가 기록한*(provenance 표식)
    # 오개념만 "해소"(학생이 실제로 넘어섬)로 구분한다. 표식이 없는 반박(막연한 clean 풀이·하네스
    # 경로·구 데이터)은 REFUTED에 머문다 — 해소율 분자를 부풀리지 않는다. 반박 집합이 비면 쿼리 0.
    resolved = await strong_refutation_mids(session, student_id, sorted(refuted))

    # MISC-20: 사유 맵을 함께 받는다(생존 세트는 `curate`와 동일 — 동치 테스트로 동결).
    active, reasons = curate_with_reasons(
        current,
        matches,
        turns_elapsed=turns_elapsed,
        refuted=frozenset(refuted),
        resolved=frozenset(resolved),
        max_active=max_active,
    )

    # 4. 영속(upsert + 탈락 비활성화) 후 활성 세트 반환.
    await _persist_active_set(session, student_id, active, reasons=reasons)
    return active
