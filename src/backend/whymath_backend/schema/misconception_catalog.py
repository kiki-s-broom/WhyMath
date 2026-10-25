"""오개념 카탈로그(MisconceptionCatalog) 백엔드 Pydantic 스키마 — M-id 콘텐츠 카탈로그 계약.

설계 정본: L1 데이터 파이프라인의 오개념 추출기(`data_pipeline/misconception/extract.py`의
`MisconceptionRecord` TypedDict 16필드)를 *백엔드 API/계약 모델*로 옮긴 것. #290에서 커밋한 코퍼스
`data/corpus/misconceptions_v1/misconceptions.json`(Collection JSON·#290 커밋 당시 839 레코드 — 현재
건수는 `docs/data/corpus_facts.md`의 `misconceptions.count`)을 적재할 영속 카탈로그의 계약이며, 이
슬라이스(Phase B.2)는 ORM·계약·마이그레이션만 세운다 — 코퍼스 로더는 후속 슬라이스 몫이다.

⚠️ 별개 체계 주의: 이 카탈로그는 **M-id(예 'M0425') 콘텐츠 카탈로그**다. 기존 L4 탐지 엔진
(`l4/misconception/catalog.py`의 30종 kebab-id)·런타임 테이블(`misconception_hypothesis`·
`evidence_links`·`misconception_embedding`의 kebab `misconception_id` 느슨참조)과는 *별개 체계*이며
**FK로 잇지 않는다**(두 체계 공존).

타입 매핑 판단(`MisconceptionRecord` TypedDict → 백엔드 Pydantic, `schema/standard.py`
AchievementStandard 선례 그대로):
  - `mis_id`(식별 필드·PK) → required `str`. 의미 문자열(예 'M0425' — UUID 아님).
  - `error_type`(8종) → `str | None`. 닫힌 enum 강제는 *파이프라인 책임*이라 `str`로 둔다
    (AchievementStandard subject/domain이 str인 것·slice8a country_code가 enum 날조를 회피한
    방침과 동일).
  - `difficulty`('상'/'중'/'하') → `str | None`. 동일하게 닫힌 어휘 강제는 파이프라인 책임.
  - `concept_src_id`·`standard_code`(느슨참조) → `str | None`. 개념·성취기준 해소는 *로더*
    책임이라 원천 코드를 그대로 보존(`concept_standard_link.concept_code` 느슨참조 선례 —
    FK 아님).
  - `mapping_score`(float·예 0.454~1.236) → `float | None`. 나머지 자유텍스트·코드 필드는
    `str | None`.

법적 메모: 본문(`canonical_statement`·`student_wrong_thinking`·`correction_point` 등)은
*와이매스 자체 저작*이라 보유가 허용된다(검정교과서·EBS 본문 금지와 대비 — AchievementStandard
`statement` 공공누리 1유형 보유 허용 선례와 동형의 보유 근거).
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, ConfigDict, Field

# severity 닫힌 어휘(Phase 4a) — 오개념의 후속 학습 손상도(문항 난이도 difficulty와 별개 축).
#   blocking = 후속 개념 습득을 막는 개념적 결손 / local = 절차·주제 국소 오류 / cosmetic = 실수성
#   (개념 결손 없음). 강제는 파이프라인 책임(가짜 CHECK 없음)이나 어휘는 이 상수로 동결한다.
SEVERITY_VALUES: Final[tuple[str, ...]] = ("blocking", "local", "cosmetic")


# ──────────────────────────────────────────────────────────────────────────
# 핵심: MisconceptionCatalog (오개념 카탈로그 — mis_id PK·M-id 콘텐츠 카탈로그)
# ──────────────────────────────────────────────────────────────────────────
class MisconceptionCatalog(BaseModel):
    """오개념 카탈로그 1건 — 백엔드 API/계약 모델(`data_pipeline` MisconceptionRecord 대응).

    `mis_id`는 카탈로그 유일 식별자(PK·의미 문자열). 나머지 필드는 소스 채우율이 52~100%라
    빈 값이면 None(배열은 `[]`)이다. 형식 검증(error_type 8종·difficulty 3종·severity 3종·코드
    형식)은 *데이터 파이프라인 책임*이며, 백엔드 계약은 파이프라인이 추출·정규화한 값을 받는
    전제다(AchievementStandard가 cross-dataset 검증을 파이프라인에 맡긴 방침과 동형).

    Phase 4a enrichment 2필드: `severity`(후속 학습 손상도·difficulty와 별개 축·SEVERITY_VALUES)·
    `behavior_skills`(arises-in skill 참조 배열·진단 방향·신규 엣지 타입 0). 상세는 각 필드 주석.
    """

    model_config = ConfigDict(
        # 추가 필드 금지 — Pydantic 모델이 계약의 단일 진실
        extra="forbid",
        # 직렬화 시 enum 값 그대로(이 모델엔 enum 없음 — 일관성 위해 둠)
        use_enum_values=True,
        # 문자열 양끝 공백 제거
        str_strip_whitespace=True,
    )

    # ===== 식별 — mis_id(PK·의미 문자열·UUID 아님) =====
    mis_id: str = Field(
        ...,
        description="오개념 카탈로그 식별자(PK) — 의미 문자열(예 'M0425', gen_random_uuid 없음)",
    )

    # ===== 본문(와이매스 자체 저작 — 보유 허용) =====
    canonical_statement: str | None = Field(default=None, description="오개념 정규 서술 (선택)")
    student_wrong_thinking: str | None = Field(
        default=None, description="학생의 잘못된 사고 (선택)"
    )
    distractor_rule: str | None = Field(default=None, description="오답 보기 생성 규칙 (선택)")

    # ===== 분류 (닫힌 enum 강제는 파이프라인 책임 — str) =====
    error_type: str | None = Field(default=None, description="오류 유형(8종 — 강제는 파이프라인)")
    difficulty: str | None = Field(default=None, description="난이도('상'/'중'/'하', 선택)")
    correction_point: str | None = Field(default=None, description="교정 포인트 (선택)")
    # severity(Phase 4a) — 후속 학습 손상도(blocking/local/cosmetic·SEVERITY_VALUES). difficulty
    # (문항 난이도)와 *다른 축*이며 어휘도 disjoint. 강제는 파이프라인 책임(가짜 CHECK 없음).
    severity: str | None = Field(
        default=None,
        description="오개념 손상도(blocking/local/cosmetic — 후속 학습 차단도·difficulty와 별개)",
    )

    # ===== 코드·매핑 (느슨참조 — 해소는 로더 책임) =====
    ccss_code: str | None = Field(default=None, description="매칭 CCSS 코드 (선택)")
    concept_src_id: str | None = Field(
        default=None,
        description="개념 식별자(느슨참조 — FK 아님, 해소는 로더 후속)",
    )
    standard_code: str | None = Field(
        default=None,
        description="성취기준 코드(느슨참조 — FK 아님, 해소는 로더 후속)",
    )
    school_level: str | None = Field(default=None, description="학교급 (선택)")
    domain: str | None = Field(default=None, description="2022 개정 영역 (선택)")
    subunit: str | None = Field(default=None, description="세부단원·개념 (선택)")
    mapping_confidence: str | None = Field(default=None, description="매핑 신뢰도 (선택)")
    mapping_score: float | None = Field(
        default=None,
        description="매핑 점수(float·예 0.454~1.236, 선택)",
    )
    provenance_note: str | None = Field(default=None, description="생성·검수 출처 메모 (선택)")

    # ===== cognition 참조 (Phase 4a·arises-in·신규 엣지 타입 0) =====
    # behavior_skills — 이 오개념이 *어느 skill 수행 중 튀어나오는가*(arises-in·진단 방향). concept/
    # problem_type의 'exercise' 의미와 구별된다. skill_graph_v1 skill_id(`skill.<slug>`) 참조 배열·
    # FK·junction 아님(anti-explosion). v1은 대응 개념(concept_src_id)의 behavior_skills를 승계한
    # ai_estimated 시드(검수 전·데이터카드 §승계 규칙)이고, 검수로 오개념별 재판단·override된다.
    behavior_skills: list[str] = Field(
        default_factory=list,
        description="발생(arises-in) skill_id 참조 배열 — 이 오개념이 튀어나오는 skill(진단 방향)",
    )


__all__ = ["MisconceptionCatalog", "SEVERITY_VALUES"]
