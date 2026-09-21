"""L2 강개념 추천 — BKT/IRT 숙달 신호 기반 강점 개념 + 원자그래프 안전 메타 enrich.

`l2.weak_concept_recommendation`의 거울상(mirror) 좌석이다 — 약점 판정과 *동일한* 신호 정의
(비교 가능한 두 신호(bkt_mastery·irt_mastery_proxy) 중 최저값)를 그대로 재사용하고, 임계
비교 방향만 뒤집는다(강점 = 최저 신호가 `mastery_threshold` *이상*). 신규 통계·진단 로직은
0건 — `compute_concept_diagnoses`가 이미 계산해 둔 신호에 필터·enrich·정렬만 얹는다
("작동 신호 없는 알고리즘 부착 금지" 준수 — 새 알고리즘이 아니라 기존 신호의 반대쪽 절반).

강점을 학생에게 보여주는 것은 CLAUDE.md 의사결정 우선순위 #1(학생 안전·웰빙)과 상충하지
않는다 — 오히려 긍정적 메타인지 강화(강점 자각)에 부합한다. "부정적 피드백을 정서적으로
강화하는 표현 금지" 조항의 반대 방향(긍정 강화)이라 이 좌석 자체는 그 조항의 규제 대상이
아니다.

출처(ASM-13): `assessment.strong_points`가 `StudentAssessment`(학생 대면) 스키마엔 있으나
채우는 writer가 0건이던 공급 축 결함 — 판정 (a) 채운다(writer 배선)의 집행.

7계층: L2 학습자 모델이 L1 `fetch_atom_axis_meta`를 *호출*(L_n→L_{n-1} 허용). L4/L5는
부착하지 않는다(호출부인 `api/me.py`가 L5 노출을 담당).
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.l1.atom_graph.atom_node_projection import AtomNodeMeta
from whymath_backend.l1.atom_graph.axis import fetch_atom_axis_meta
from whymath_backend.l2.concept_diagnosis import (
    Agreement,
    ConceptDiagnosis,
    compute_concept_diagnoses,
)


class StrongConceptRecommendation(BaseModel):
    """강개념 추천 1건 — 진단 강점 신호 + `atom_node`(code) 안전 그래프 메타(enrich).

    `weak_concept_recommendation.WeakConceptRecommendation`과 필드 형태를 맞춘다 — 학생
    화면에서 약점·강점 두 목록이 같은 모양이어야 렌더가 대칭을 이룬다. `mastery`는 비교
    가능한 두 신호 중 *최저값*(약점 판정의 `weakness`와 동일 정의 — 한쪽 신호만 높고 다른
    쪽이 낮으면 보수적으로 강점에서 제외한다).
    """

    concept_id: uuid.UUID = Field(description="개념 id(backend `concept` UUID PK).")
    concept_code: str | None = Field(
        default=None, description="개념 코드(=UC·개념그래프 키). orphan이면 null."
    )
    concept_name: str | None = Field(
        default=None, description="개념명(backend `concept`.name_ko·orphan이면 null)."
    )
    bkt_mastery: float | None = Field(
        default=None, description="BKT 최신 숙달 P(L). 측정 없으면 null."
    )
    irt_mastery_proxy: float | None = Field(
        default=None, description="logistic(θ)∈[0,1] — IRT 능력 프록시. θ 없으면 null."
    )
    mastery: float | None = Field(
        default=None,
        description="두 신호(bkt_mastery·irt_mastery_proxy) 중 최저값(강점 정렬·필터 기준 — "
        "weak_concept_recommendation의 weakness와 동일 정의, 임계 비교 방향만 반대).",
    )
    agreement: Agreement = Field(
        description="BKT↔IRT 일치 신호(agree·irt_higher·bkt_higher·insufficient)."
    )
    domain: str | None = Field(
        default=None,
        description="개념 영역명(atom_node 조인·안전 표시 필드. 값 소스는 원자 subject_area). "
        "메타 미적재 시 null.",
    )
    review_status: str | None = Field(
        default=None,
        description="검수 상태('reviewed'/'pending'·atom_node 조인·게이팅 플래그). 메타 미적재 "
        "시 null.",
    )
    name_ko: str | None = Field(
        default=None,
        description="개념 한국어 표시명(atom_node 조인·안전 표시 필드). 메타 미적재 시 null.",
    )


def _mastery_of(diagnosis: ConceptDiagnosis) -> float | None:
    """비교 가능한 신호 중 최저값 — `weak_concept_recommendation._weakness_of`와 동일 정의.

    강점 판정도 *보수적*이어야 한다(한쪽 신호만 높은 경우를 강점으로 세지 않는다) — 그래서
    별도 공식을 만들지 않고 약점 판정과 같은 최저값을 그대로 쓴다. 다른 것은 임계 비교
    방향(`>=`)뿐이다.
    """
    signals = [v for v in (diagnosis.bkt_mastery, diagnosis.irt_mastery_proxy) if v is not None]
    return min(signals) if signals else None


async def recommend_strong_concepts(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    limit: int = 10,
    mastery_threshold: float = 0.7,
    diagnoses: list[ConceptDiagnosis] | None = None,
) -> list[StrongConceptRecommendation]:
    """학습자 강점(BKT/IRT) → 강점 필터(mastery ≥ threshold) → `atom_node` enrich → 상위 N.

    흐름:
      ① `compute_concept_diagnoses`로 개념별 진단을 받는다(L2 좌석 재사용·신규 진단 0). 이
         함수는 *약점 먼저* 정렬해 반환하므로 강점 후보는 뒤쪽에 몰려 있다. 호출자가 이미 계산해
         둔 진단 스냅샷이 있으면 `diagnoses`로 넘겨 *재사용*한다(기본 None이면 직접 조회) — 같은
         요청 안에서 약점·강점 추천이 각자 새로 조회하면 동시 mastery 갱신 시 서로 다른 스냅샷을
         볼 수 있다(코드 리뷰 실측 — `weak_concept_recommendation`과 동일 근거·동일 파라미터).
      ② **강점 필터** — 최저 신호가 `mastery_threshold` *이상*인 개념만. 신호가 하나도 없으면
         제외(추천 근거 없음 — 약점 판정과 동일 취급).
      ③ 필터된 목록을 뒤집어(reverse) 최고 mastery가 먼저 오게 한다(재정렬만·재계산 0).
      ④ **code enrich** — 강점 후보의 `concept_code`를 모아 `fetch_atom_axis_meta`를 단일
         호출(N+1 0·호출 세션의 async 엔진)로 `atom_node` 안전 메타를 붙인다. code 없거나
         결과에 없으면(원자 축 밖) enrich 필드는 None(graceful).
      ⑤ **상한** — 강점 정렬을 보존하며 상위 `limit`개만 반환.

    `recommend_weak_concepts`와 달리 `reviewed_only` 게이팅은 두지 않는다 — 학생 본인의
    강점 자각 표시는 검수 상태와 무관하게(자기 이력이므로) 보여준다는 판단(ASM-13 범위).
    """
    diagnoses = (
        diagnoses if diagnoses is not None else await compute_concept_diagnoses(session, user_id)
    )

    strong: list[tuple[ConceptDiagnosis, float]] = []
    for diagnosis in diagnoses:
        mastery = _mastery_of(diagnosis)
        if mastery is not None and mastery >= mastery_threshold:
            strong.append((diagnosis, mastery))
    strong.reverse()  # 약점 먼저 정렬의 역순 = 강점(최고 mastery) 먼저.

    if not strong:
        return []

    code_list = sorted({d.concept_code for d, _ in strong if d.concept_code is not None})
    meta: dict[str, AtomNodeMeta] = {}
    if code_list:
        meta = await fetch_atom_axis_meta(session, code_list)

    out: list[StrongConceptRecommendation] = []
    for diagnosis, mastery in strong:
        node = meta.get(diagnosis.concept_code) if diagnosis.concept_code is not None else None
        out.append(
            StrongConceptRecommendation(
                concept_id=diagnosis.concept_id,
                concept_code=diagnosis.concept_code,
                concept_name=diagnosis.concept_name,
                bkt_mastery=diagnosis.bkt_mastery,
                irt_mastery_proxy=diagnosis.irt_mastery_proxy,
                mastery=mastery,
                agreement=diagnosis.agreement,
                domain=node.subject_area if node is not None else None,
                review_status=node.review_status if node is not None else None,
                name_ko=node.name_ko if node is not None else None,
            )
        )
        if len(out) >= limit:
            break

    return out


__all__ = ["StrongConceptRecommendation", "recommend_strong_concepts"]
