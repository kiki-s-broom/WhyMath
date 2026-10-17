"""L6 수능(정시) 모드 게이팅 — 페르소나 A·B·C 대상 문항 선별 노출.

오버레이 모델(기계장치+synthetic·얇게, RT 트랙 `l6/retake`와 동형): 새 concept 노드·Alembic
마이그레이션·새 enum을 *만들지 않는다*. 기존 L1 `Problem` 필드만 재사용한다 —
  - `Problem.exam_type` (수능/모평/학평 = 권위 있는 기출 유형 신호),
  - `Problem.exam_authority_weight` (수능1.0/모평0.8/학평0.5 = 출처 권위 가중치),
  - `Problem.signature_patterns` (한국 수능 시그니처 패턴 — *존재 여부*만 본다),
  - `Problem.persona_fit: dict[Persona, float]` (페르소나별 적합도 0~1),
  - `Problem.difficulty_overall` (종합 난이도 보조 축),
  - `Problem.source_type` (저작권 노출 게이트 — 평가원/EBS/교과서 본문 미보유 차단).
  - `Problem.achievement_standard_codes` (비영속·L5 주입 — 출제 범위 게이트 `scope.py`. EOS-31).

대상: 정시(수능) 응시 페르소나 A·B·C만. D(학종·수시)·E(영재)는 이 모드 범위 밖.

레이어 규칙(CLAUDE.md): L6→L1 의존만 한다(`schema.problem`·`schema.enums`). L4/L2/L3를
import하지 않는다 — 기존 `Problem` 필드의 *존재·값*만 보므로 하위 카탈로그·검증자가 불필요하다.
L6은 아무도 import하지 않는 최상위 소비자다.

저작권(CLAUDE.md 우선순위 #2): 수능 대비 핵심 자원인 평가원 기출의 *본문* 복제는 절대 금지
(저작권법 §32 단서·MEMORY 2026-05-28) — 평가원/EBS/교과서 출처는 게이트로 원천 차단하고,
학생에게는 *자체생성 동등문제*(WHYMATH_GENERATED)만 노출한다.

S2-06 수능 적응 추천(`recommendation.py`): 위 게이팅(진실 게이트)과 L2 IRT CAT을 결합해
"적격 후보 중 가중 정보량 최대" 문항을 고른다 — 게이팅과 달리 L6→L2 *하향* import를 한다
(import-linter 합법 방향 — recommendation 모듈 docstring 참조).
"""

from __future__ import annotations

from whymath_backend.l6.suneung.gating import (
    METADATA_ONLY_SOURCES,
    SUNEUNG_DEFAULT_MIN_FIT,
    SUNEUNG_EXAM_TYPES,
    SUNEUNG_PERSONAS,
    is_suneung_eligible,
    select_suneung_items,
    suneung_priority,
)
from whymath_backend.l6.suneung.recommendation import (
    recommend_suneung_index,
    suneung_item_weight,
)
from whymath_backend.l6.suneung.scope import (
    SUNEUNG_SCOPE,
    SUNEUNG_SCOPES,
    SUNEUNG_TARGET_EXAM_YEAR,
    ScopeVerdict,
    SuneungScope,
    code_in_scope,
    suneung_scope_verdict,
)

__all__ = [
    "METADATA_ONLY_SOURCES",
    "SUNEUNG_DEFAULT_MIN_FIT",
    "SUNEUNG_EXAM_TYPES",
    "SUNEUNG_PERSONAS",
    "SUNEUNG_SCOPE",
    "SUNEUNG_SCOPES",
    "SUNEUNG_TARGET_EXAM_YEAR",
    "ScopeVerdict",
    "SuneungScope",
    "code_in_scope",
    "is_suneung_eligible",
    "recommend_suneung_index",
    "select_suneung_items",
    "suneung_item_weight",
    "suneung_priority",
    "suneung_scope_verdict",
]
