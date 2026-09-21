"""검수 단계 — 기계 게이트로 `PRESCREENED → APPROVED | REJECTED` + `k_type_verified` 정직 flip.

PED-01 파일럿 E2E의 세 번째 중간 단계다. 예심 통과 슬롯을 *결정 가능한* 기계 게이트로 판정한다:
  ① 숫자형 SymPy 재검증(답이 실제로 맞는가) ② 구조 완전성(본문·유형·태그) ③ 정답 유출(문제 본문에
  답이 노출됐는가). 셋 다 통과해야 APPROVE, 하나라도 실패하면 REJECT(reject_reason 기록).

────────────────────────────────────────────────────────────────────────────
왜 기계 게이트인가 (초인간 검증 기준)
────────────────────────────────────────────────────────────────────────────
"인간 검수 = 안전"이 아니라 "측정된 기계 게이트 = 안전"(초인간 검증 기준 v1). 이 게이트가 판정하는
범위는 **구조+기호(structural+symbolic) 정확성**으로 한정한다 — 결정 가능하고 재현 가능하다. 반면
*교육적 품질*(이 example_pair가 정말 좋은 대비인가) 같은 undecidable 판단은 인간 폴백으로 미룬다
(deferred). 파일럿 콘텐츠는 자체 저작 픽스처라 그 인간 폴백 구간은 정당하게 비운다. fail-closed:
APPROVED만 `v_manifest_fill`에 계상되므로, 게이트 결함은 서빙을 *막을* 뿐 잘못 노출시키지 않는다.

주의: 팩의 `SUBJECT_NOUN_BLOCKLIST`(과목명사 금지)는 *유형 불변 socratic 발문*용이지 콘텐츠
슬롯용이 아니다 — 슬롯 본문은 당연히 주제(이차함수)를 담으므로 여기 적용하지 않는다(오탐 방지).

7계층: L3 콘텐츠 검증. SymPy 재검증은 생성 단계 `verify_slot_payload` 재사용.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from whymath_backend.config import Settings, get_settings
from whymath_backend.db.models.pedagogy_dsl import (
    LearningObjective,
    PedagogyContentSlot,
)
from whymath_backend.l1.embedding_primitives import build_sync_engine
from whymath_backend.l3.pedagogy.slot_generator import verify_slot_payload
from whymath_backend.schema.verification_capabilities import ExpressionEquivalence

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

# 검수자 각인 — 사람 서명이 아니라 기계 게이트임을 정직하게 표기(버전 포함).
REVIEWER_TAG = "machine:sympy_structural/v0.1"

# 검수가 *확정*하는 verb→k_type(성숙 팩만). MODELING은 스텁이라 의도적으로 제외한다 — 그 verb→
# type 확정은 팩 성숙 시로 deferred(k_type_verified는 정직하게 False로 남는다).
_VERB_KTYPE: dict[str, str] = {
    "이해한다": "CONCEPT",
    "구한다": "PROCEDURE",
    "해석한다": "REPRESENT",
}


@dataclass(frozen=True)
class ReviewVerdict:
    """검수 판정 — 승인 여부 + 반려 사유(승인 시 None)."""

    approved: bool
    reason: str | None = None


# ──────────────────────────────────────────────────────────────────────────
# 기계 게이트
# ──────────────────────────────────────────────────────────────────────────
def review_slot(
    payload: dict[str, Any], *, equivalence: ExpressionEquivalence | None = None
) -> ReviewVerdict:
    """슬롯 1개 검수 — 구조+기호 결정 가능 검사만. 통과=APPROVE, 실패=REJECT(사유).

    ① 숫자형 SymPy 재검증(`verify_slot_payload`가 False면 답 틀림 → 반려) ② 본문·유형·태그 완전성
    ③ 정답 유출(answer 값이 body에 노출) — fail-closed로 하나라도 걸리면 반려한다.

    `equivalence`(과목 항등 판정·EOS-89)는 payload에 `verification` 주장이 있을 때만 필요하다 —
    주입 없이 주장 있는 payload를 넣으면 `LookupError`다(미검증을 통과로 위장하지 않는다).
    """
    # ① 숫자형 재검증(개념형은 None → 통과).
    if verify_slot_payload(payload, equivalence=equivalence) is False:
        return ReviewVerdict(False, "sympy_reverify_failed")

    # ② 구조 완전성.
    body = payload.get("body")
    if not isinstance(body, str) or not body.strip():
        return ReviewVerdict(False, "empty_body")
    if not payload.get("reasoning_type"):
        return ReviewVerdict(False, "missing_reasoning_type")
    if not payload.get("structure_tags"):
        return ReviewVerdict(False, "missing_structure_tags")

    # ③ 정답 유출 — 문제 본문에 답이 그대로 노출되면 반려(풀 문제가 아님).
    answer = payload.get("answer")
    if answer is not None and str(answer) in body:
        return ReviewVerdict(False, "answer_leak")

    return ReviewVerdict(True, None)


def review_rows(
    rows: Sequence[dict[str, Any]], *, equivalence: ExpressionEquivalence | None = None
) -> list[tuple[str, ReviewVerdict]]:
    """슬롯 행들 → `(id, ReviewVerdict)` 리스트(각 payload에 `review_slot` 적용)."""
    return [(str(row["id"]), review_slot(row["payload"], equivalence=equivalence)) for row in rows]


def verb_confirms_k_type(source_verb: str | None, k_type: str) -> bool:
    """성취 동사가 목표 k_type을 확정하는가 — 성숙 팩만 True(MODELING 스텁은 항상 False).

    `_VERB_KTYPE`에 없는 동사/유형(예: 해결한다·MODELING)은 False를 반환해 `k_type_verified`가
    정직하게 미확정(False)으로 남게 한다.
    """
    return _VERB_KTYPE.get((source_verb or "").strip()) == k_type


# ──────────────────────────────────────────────────────────────────────────
# 시더: ReviewStore (PRESCREENED → APPROVED|REJECTED, k_type_verified flip)
# ──────────────────────────────────────────────────────────────────────────
class ReviewStore:
    """검수 판정 → `pedagogy_content_slot` 상태 승격 + `learning_objective.k_type_verified` flip.

    슬롯 UPDATE는 `id` + `status='PRESCREENED'` 가드(예심 통과분만 검수).
    `reviewed_by`(기계 각인)·`reviewed_at`(server now)·`reject_reason`을 기록한다.
    sync 엔진은 슬3 `build_sync_engine` 재사용.
    """

    def __init__(
        self,
        *,
        engine: Engine | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._engine = engine
        self._settings = settings

    @property
    def _resolved_settings(self) -> Settings:
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    def _get_engine(self) -> Engine:
        if self._engine is None:
            self._engine = build_sync_engine(self._resolved_settings)
        return self._engine

    def apply(self, verdicts: Sequence[tuple[str, ReviewVerdict]]) -> int:
        """`(id, verdict)` → PRESCREENED 슬롯만 APPROVED|REJECTED로 승격. 반환=처리 수."""
        from sqlalchemy import func, update

        with self._get_engine().begin() as conn:
            for slot_id, verdict in verdicts:
                new_status = "APPROVED" if verdict.approved else "REJECTED"
                stmt = (
                    update(PedagogyContentSlot)
                    .where(
                        PedagogyContentSlot.id == slot_id,
                        PedagogyContentSlot.status == "PRESCREENED",
                    )
                    .values(
                        status=new_status,
                        reviewed_by=REVIEWER_TAG,
                        reviewed_at=func.now(),
                        reject_reason=verdict.reason,
                    )
                )
                conn.execute(stmt)
        return len(verdicts)

    def set_k_type_verified(self, objective_ids: Sequence[str]) -> int:
        """주어진 학습목표들의 `k_type_verified`를 True로 flip. 반환=대상 수.

        호출자가 `verb_confirms_k_type`로 걸러 넘긴 목표만 True가 된다
        (스텁 팩 목표는 제외돼 False 유지).
        """
        from sqlalchemy import update

        if not objective_ids:
            return 0
        with self._get_engine().begin() as conn:
            stmt = (
                update(LearningObjective)
                .where(LearningObjective.id.in_(list(objective_ids)))
                .values(k_type_verified=True)
            )
            conn.execute(stmt)
        return len(objective_ids)


__all__ = [
    "REVIEWER_TAG",
    "ReviewVerdict",
    "review_slot",
    "review_rows",
    "verb_confirms_k_type",
    "ReviewStore",
]
