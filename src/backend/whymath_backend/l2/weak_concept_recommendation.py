"""L2 약개념 추천 — BKT/IRT 약점 진단 + 원자그래프 안전 메타 enrich (원자그래프 소비 슬2).

L1 *원자그래프* 소비 아크의 좌석이다. runtime truth source가 원자 단일로 확정되며(S0-4 legacy_
snapshot 격하), 메타 enrich 대상 테이블을 `concept_node`(구 437 UC)에서 `atom_node`(code 키·원자
백본)로 전환했다(S0-4d). L2 학습자 모델(BKT/IRT)이 식별한 약개념에 `atom_node`(code) 안전 그래프
메타(name_ko·subject_area·review_status)를 붙여 "지금 무엇을 복습할지" 후보를 돌려준다.

────────────────────────────────────────────────────────────────────────────
재사용 좌석 (신규 진단·정렬 로직 0)
────────────────────────────────────────────────────────────────────────────
① 진단·약점 정렬 — `l2.concept_diagnosis.compute_concept_diagnoses`를 *그대로* 입력으로 쓴다
   (BKT 최신 숙달 + IRT θ 융합·agreement·*약점 먼저* 정렬 이미 수행). 여기서 IRT/BKT 융합이나
   약점 정렬을 재구현하지 않는다 — 진단 결과에 *필터·enrich·상한*만 얹는다.
② code enrich — `l1.atom_graph.axis.fetch_atom_axis_meta`(code 리스트 → `atom_node` 안전 메타
   단일 IN 조회·**호출 세션의 async 엔진**)를 쓴다. 원자 검색 좌석(`search_atoms`)이 쓰는 sync
   짝(`fetch_atom_node_meta`)과 같은 컬럼·같은 반환 계약이며 엔진 평면만 다르다.

────────────────────────────────────────────────────────────────────────────
단일 엔진 (ARCH-13 — 교차 엔진 code 문자열 조인 해소)
────────────────────────────────────────────────────────────────────────────
예전에는 진단(async 세션)과 메타(별도 sync 엔진)를 code 문자열로 이어 붙였다. 원자 축과 구 437이
같은 테이블에 code로 병존하므로 그 조인은 *축이 어긋나도 조용히 성립*했고, 미스는 enrich None →
`reviewed_only`에서 소리 없이 탈락했다. 지금은 메타를 **같은 async 세션**에서 읽고
(`asyncio.to_thread` 제거), `atom_node`에 없는 code는 "메타 누락"이 아니라 **원자 축 밖**으로 읽어
사유별로 계상한다(`AxisExclusions`·구조화 로그).

이 좌석은 traversal이 아니라 *학습자 자신의 mastery*에서 후보가 나오므로 **축 필터는 걸지 않는다** —
학생이 실제로 푼 개념을 축이 다르다는 이유로 감추면 이력을 숨기는 셈이다. 축 밖은 `reviewed_only`
게이팅에서만(기존과 동일하게) 빠지고, 그 사실이 `off_atom_axis`로 드러난다.

────────────────────────────────────────────────────────────────────────────
redaction·노출 계약 (CLAUDE.md 우선순위 #2 — 협상 불가)
────────────────────────────────────────────────────────────────────────────
enrich되는 건 *안전 표시·게이팅 필드*뿐(name_ko·subject_area·review_status). **description·
formal_definition·core_proposition은 어디에도 유입되지 않는다** — `atom_node`에 본문 컬럼
자체가 없어(`atom_node_projection`·`AtomNodeMeta` redaction) 조회로 흐를 경로가 구조적으로 없다.
이 좌석은 *학생 직접 노출이 아니라* 내부 조회 좌석이다(소비 슬 노출 계약과 일관) — 우열 매기기·
정답 빠르게 등 금기 표현 0.

검수 게이팅(`reviewed_only`)은 *필터*다 — 약점 정렬은 유지하고, True면 `review_status ==
"reviewed"`인 개념만 남긴다(메타 없어 확인 불가인 code는 보수적 제외 — 소비 슬 게이팅 규약과
일관·"확실하지 않으면 노출 안 함"). 기본 False는 recall 보존.

7계층: L2 학습자 모델이 L1 `fetch_atom_axis_meta`를 *호출*(L_n→L_{n-1} 허용·경계 준수·원자 축도
동일 방향 `l1.atom_graph`). L4 코칭·L5 노출은 부착하지 않는다(역방향 의존 회피 — 코칭은 L4·
HTTP 표면은 api/me).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.l1.atom_graph.atom_node_projection import AtomNodeMeta
from whymath_backend.l1.atom_graph.axis import fetch_atom_axis_meta
from whymath_backend.l2.axis_exclusions import AxisExclusions, log_axis_exclusions
from whymath_backend.l2.concept_diagnosis import (
    Agreement,
    ConceptDiagnosis,
    compute_concept_diagnoses,
)
from whymath_backend.l2.recommendation_contract import WEAK_CONCEPT_MASTERY_CEILING

# 검수 게이팅 비교 리터럴 — `atom_node.review_status`가 싣는 reviewed 값(원자 검색 좌석과 동일
# 규약). 단, 원자 메타 적재는 review_status를 상수 'ai_estimated'로 박으므로(원자 메타는 AI 추정·
# atom_node_projection redaction), 원자 축에서 reviewed_only=True는 사실상 전부 게이팅될 수 있다
# — 검수 승격은 후속 좌석 몫이고, 기본 False(recall 보존) 경로가 정상 운용이다(S0-4d).
_REVIEWED: str = "reviewed"

# 구조화 로그·집계 좌석명(`whymath.l2.<seat>` 로거로 나간다).
_SEAT: str = "weak_concept_recommendation"


class WeakConceptRecommendation(BaseModel):
    """약개념 추천 1건 — 진단 약점 신호 + `atom_node`(code) 안전 그래프 메타(enrich·소비 슬2).

    `compute_concept_diagnoses`의 약점 진단(BKT/IRT)에 `atom_node` 안전 메타를 붙인 형태다(S0-4d·
    runtime truth=원자). `weakness`는 비교 가능한 두 신호(bkt_mastery·irt_mastery_proxy) 중
    *최저값*(정렬·필터 기준). `domain`·`review_status`·`name_ko`는 `atom_node`(PG 프로젝션) code
    조인으로 붙인 *안전 표시·게이팅 필드*다 — 메타 미적재 code(또는 orphan으로 code 없음)면
    **None**(graceful). **본문(description·formal_definition·core_proposition)은 미포함** —
    `atom_node`에 본문 컬럼 자체가 없어 구조적으로 흐를 수 없다(redaction·노출 계약).
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
    weakness: float | None = Field(
        default=None,
        description="두 신호(bkt_mastery·irt_mastery_proxy) 중 최저값(약점 정렬·필터 기준). "
        "비교 가능한 신호가 없으면 null(이 경우 추천에서 제외).",
    )
    agreement: Agreement = Field(
        description="BKT↔IRT 일치 신호(agree·irt_higher·bkt_higher·insufficient)."
    )
    domain: str | None = Field(
        default=None,
        description="개념 영역명(atom_node 조인·안전 표시 필드). 필드명은 계약 안정을 위해 "
        "`domain`을 유지하나, 값 소스는 이제 원자 `subject_area`다(S0-4d·runtime truth=원자). "
        "메타 미적재 시 null.",
    )
    review_status: str | None = Field(
        default=None,
        description="검수 상태('reviewed'/'pending'·atom_node 조인·게이팅 플래그). "
        "메타 미적재 시 null.",
    )
    name_ko: str | None = Field(
        default=None,
        description="개념 한국어 표시명(atom_node 조인·안전 표시 필드). 메타 미적재 시 null.",
    )


def _weakness_of(diagnosis: ConceptDiagnosis) -> float | None:
    """비교 가능한 신호(bkt_mastery·irt_mastery_proxy) 중 최저값 — 둘 다 없으면 None.

    `compute_concept_diagnoses`의 약점 정렬 키와 *동일 정의*(최저 신호 = 약점). 신호가 하나도
    없으면 추천 근거가 없으므로 None을 돌려 호출부가 제외한다(insufficient도 한쪽 신호는 있으면
    그 값으로 약점 판정 — 신호 0건만 제외).
    """
    signals = [v for v in (diagnosis.bkt_mastery, diagnosis.irt_mastery_proxy) if v is not None]
    return min(signals) if signals else None


@dataclass(frozen=True, slots=True)
class WeakConceptResult:
    """약개념 추천 결과 + **제외 사유 집계** — 빈 결과의 이유를 알 수 있게 하는 반환형.

    `recommendations`만 필요한 호출자는 얇은 래퍼 `recommend_weak_concepts`를 쓴다(기존 계약 불변).
    """

    recommendations: list[WeakConceptRecommendation]
    exclusions: AxisExclusions


async def recommend_weak_concepts_detailed(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    limit: int = 10,
    mastery_threshold: float = WEAK_CONCEPT_MASTERY_CEILING,
    reviewed_only: bool = False,
    diagnoses: list[ConceptDiagnosis] | None = None,
) -> WeakConceptResult:
    """학습자 약점(BKT/IRT) → 약점 필터 → `atom_node`(code) 안전 메타 enrich → 상위 N 추천.

    흐름:
      ① `compute_concept_diagnoses`로 개념별 진단(BKT 최신 + IRT θ 융합·*약점 먼저* 정렬)을 받는다
         — 진단·정렬은 L2 좌석 재사용(신규 0). 정렬은 이미 약점 우선이라 이 함수가 보존한다.
         호출자가 이미 계산해 둔 진단 스냅샷이 있으면 `diagnoses`로 넘겨 *재사용*한다(기본
         None이면 이 함수가 직접 조회) — 같은 요청 안에서 약점·강점 추천이 각자 새로 조회하면
         동시 mastery 갱신 시 서로 다른 스냅샷을 볼 수 있다(코드 리뷰 실측 — `api/me.py`의
         `_assemble_measurement_assessment`가 단일 스냅샷을 셋에 공유하도록 이 파라미터를 쓴다).
      ② **약점 필터** — 비교 가능한 신호(bkt_mastery·irt_mastery_proxy 중 존재) 최저값이
         `mastery_threshold` *미만*인 개념만(약점). 신호가 하나도 없으면 추천 근거 없음으로 제외.
      ③ **code enrich** — 약점 후보들의 `concept_code`(None 아닌 code)를 모아 `fetch_atom_axis_meta`
         를 *단일 호출*(N+1 0·**호출 세션의 async 엔진**)로 `atom_node` 안전 메타를 받아 붙인다
         (S0-4d·runtime truth=원자). code 없거나(orphan) 결과에 없으면(=**원자 축 밖**) enrich
         필드 None graceful — 격하 취지 부합.
      ④ **검수 게이팅** — `reviewed_only=True`면 `review_status == "reviewed"`인 개념만. 제외 사유는
         **축 밖**(`off_atom_axis`)과 **검수 전**(`not_reviewed`)으로 분리 계상한다 — 예전처럼
         "메타 None이면 그냥 continue"로 뭉뚱그리지 않는다(ARCH-13 표면화). 기본 False는 recall
         보존.
      ⑤ **상한** — 약점 정렬을 보존하며 상위 `limit`개만 반환.

    반환은 `recommendations` + `exclusions`(제외 사유별 건수)다. 제외가 있으면 구조화 로그도 1줄
    남긴다(카운트만·식별 정보 0).

    user_id 스코핑·읽기 전용(마이그레이션 불필요). enrich되는 건 안전 필드(name_ko·subject_area·
    review_status)뿐 — 본문(description·formal_definition·core_proposition)은 `atom_node`에 본문
    컬럼이 없어 구조적으로 0(redaction). mastery 파생 로직·`concept_code` 키 축은 건드리지 않는다
    (메타 *조회 엔진*만 sync→호출 세션으로 교체·rekey 0·데이터 변경 0).
    """
    # ① 진단(약점 먼저 정렬) — 호출자 스냅샷 재사용(제공 시) 또는 L2 좌석 재사용(융합·정렬·
    # 합집합은 이 좌석이 이미 수행).
    diagnoses = (
        diagnoses if diagnoses is not None else await compute_concept_diagnoses(session, user_id)
    )

    # ② 약점 필터 — 최저 신호 < 임계인 개념만(신호 0건은 None → 제외). 정렬은 보존(in-place 순서).
    weak: list[tuple[ConceptDiagnosis, float]] = []
    not_weak = 0
    for diagnosis in diagnoses:
        weakness = _weakness_of(diagnosis)
        if weakness is not None and weakness < mastery_threshold:
            weak.append((diagnosis, weakness))
        else:
            not_weak += 1

    if not weak:
        exclusions = AxisExclusions(not_weak=not_weak)
        log_axis_exclusions(_SEAT, exclusions, kept=0)
        return WeakConceptResult(recommendations=[], exclusions=exclusions)

    # ③ code enrich — 약점 후보의 code(concept_code) 중복 제거해 단일 IN 조회(호출 세션 엔진·
    #    교차 엔진 왕복 0). uc_list는 변수명만 유지하되 이제 원자 code 목록이다(concept_code 키
    #    축은 불변). 결과에 없는 code = 원자 축 밖(구 437 UC 등) — None이 아니라 사유로 읽는다.
    uc_list = sorted({d.concept_code for d, _ in weak if d.concept_code is not None})
    meta: dict[str, AtomNodeMeta] = {}
    if uc_list:
        meta = await fetch_atom_axis_meta(session, uc_list)

    # ④/⑤ 게이팅 필터 + 상한 — 약점 정렬 보존하며 reviewed 필터 후 상위 limit. 제외 사유는
    #     축 밖(off_atom_axis)과 검수 전(not_reviewed)으로 분리 계상한다(ARCH-13 표면화).
    off_atom_axis = 0
    not_reviewed = 0
    out: list[WeakConceptRecommendation] = []
    for diagnosis, weakness in weak:
        node = meta.get(diagnosis.concept_code) if diagnosis.concept_code is not None else None
        if reviewed_only:
            if node is None:
                off_atom_axis += 1  # 원자 축 밖(또는 orphan) — 검수 확인 불가라 보수적 제외.
                continue
            if node.review_status != _REVIEWED:
                not_reviewed += 1  # 축 안이지만 검수 전 → 보수적 제외.
                continue
        out.append(
            WeakConceptRecommendation(
                concept_id=diagnosis.concept_id,
                concept_code=diagnosis.concept_code,
                concept_name=diagnosis.concept_name,
                bkt_mastery=diagnosis.bkt_mastery,
                irt_mastery_proxy=diagnosis.irt_mastery_proxy,
                weakness=weakness,
                agreement=diagnosis.agreement,
                # DTO 필드명 `domain`은 유지(계약 안정)·값 소스만 원자 subject_area로 교체(S0-4d).
                domain=node.subject_area if node is not None else None,
                review_status=node.review_status if node is not None else None,
                name_ko=node.name_ko if node is not None else None,
            )
        )
        if len(out) >= limit:
            break  # 상한 — 약점 정렬 보존하며 상위 N(게이팅 후 카운트).

    exclusions = AxisExclusions(
        off_atom_axis=off_atom_axis, not_reviewed=not_reviewed, not_weak=not_weak
    )
    log_axis_exclusions(_SEAT, exclusions, kept=len(out))
    return WeakConceptResult(recommendations=out, exclusions=exclusions)


async def recommend_weak_concepts(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    limit: int = 10,
    mastery_threshold: float = WEAK_CONCEPT_MASTERY_CEILING,
    reviewed_only: bool = False,
    diagnoses: list[ConceptDiagnosis] | None = None,
) -> list[WeakConceptRecommendation]:
    """`recommend_weak_concepts_detailed`의 추천 목록만 돌려주는 얇은 래퍼(기존 계약 보존).

    제외 사유 집계까지 필요한 호출자만 `_detailed`를 쓴다 — 로직 중복 0(본체는 하나).
    """
    result = await recommend_weak_concepts_detailed(
        session,
        user_id,
        limit=limit,
        mastery_threshold=mastery_threshold,
        reviewed_only=reviewed_only,
        diagnoses=diagnoses,
    )
    return result.recommendations


__all__ = [
    "WeakConceptRecommendation",
    "WeakConceptResult",
    "recommend_weak_concepts",
    "recommend_weak_concepts_detailed",
]
