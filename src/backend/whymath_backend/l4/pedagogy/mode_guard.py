"""forbidden_modes 가드 — 팩이 금지한 교수 모드가 코치 응답에 나타났는지 검출(reason_code | None).

`harness/wh1_prose.py::gate_policy_prose`(reason_code | None·pre-`filter_tone` 배치)의 *교수법 팩*
짝이다. 팩(`PedagogyPack.forbidden_modes`)이 자기 지식 유형에 금지한 교수 모드(Kapur/Sweller 제약)를
런타임 응답이 위반하는지 규칙 기반으로 검사한다 — 위반 모드 토큰(reason_code)을 반환하면 호출자가
그 응답을 서빙하지 않고 폴백한다(fail-closed 사용·톤필터 *앞* 계층). 위반 없으면 None(순수).

────────────────────────────────────────────────────────────────────────────
정직한 커버리지 (overclaim 금지)
────────────────────────────────────────────────────────────────────────────
7개 금지 모드(FORBIDDEN_MODE_VOCAB) 중 *명확한 문면 신호가 있는* 모드만 규칙 검출기를 붙인다.
나머지(대부분)는 LLM 판정(샘플드 Claude audit)이 필요해 v1은 **검출기를 두지 않고 건너뛴다** —
이는 "clean(무위반)" 선언이 아니라 "이 축은 규칙으로 판정 불가·후속 audit 대상"이라는 정직한
공백이다(조용히 통과시키지 않고 커버리지를 `RULE_DETECTABLE_MODES`/`DEFERRED_MODES`로 명시).

  - **WORKED_EXAMPLE_FIRST**(개념형) — 규칙 검출 O. 개념형 팩의 핵심은 예/비예로 정의를 *유도*하는
    것인데, 응답이 정의·정답을 *단정*하면서 유도 질문이 전혀 없으면 "완전예제 선행"으로 본다.
    방어 가능한 휴리스틱(단정 신호 ∧ 유도 신호 부재)만 쓴다(오탐 보수적·아래 상수 참조).
  - **PRODUCTIVE_FAILURE·SINGLE_DIRECTION_DRILL·COPY_COMPLETED_PROOF·FORMULA_MEMORIZATION·
    IMMEDIATE_COORDINATE_REDUCTION·FORMULA_PLUGIN_ONLY** — 규칙 검출 X(v1 deferred). 이들은 응답
    *한 건*의 문면이 아니라 교수 *전략/시퀀스*(여러 턴·페이딩·표현 전환 균형)의 성질이라 단일 응답
    substring으로 못 잡는다 — 샘플드 Claude audit으로 이관(후속). 검출기 미등록 = 정직한 공백.

검출기는 `FORBIDDEN_MODE_DETECTORS` 레지스트리에 모드 토큰→Callable로 등록해 커버리지를 *명시적·
확장 가능*하게 둔다. `check_forbidden_modes`는 팩이 실제로 금지한 모드만, 그 중 검출기가 등록된
것만 검사한다.

────────────────────────────────────────────────────────────────────────────
집행 지점 판정 — PED-16(2026-08-10) by-design 미배선 확정 → PED-23(회수) 옵트인 배선 복원
────────────────────────────────────────────────────────────────────────────
PED-16 당시 이 함수는 라이브 코치 응답 경로 어디에도 배선돼 있지 않았다 — 호출자가
`harness/pedagogy_pack_fidelity_eval.py`(오프라인 결함주입 측정·CI 상시) 하나뿐이었다. 근거는
"실제 생성→서빙 경로(WH-1 루프 `harness/wh1_primary.py`)가 `PedagogyPack`을 참조하지 않아
배선하려면 팩 주입을 WH-1 루프 전체에 새로 도입해야 한다"는 것이었고, 재검토 조건으로 "WH-1
루프가 PedagogyPack을 참조하게 되는 시점"을 명시했다.

그러나 격리 브랜치의 원 구현(PED-07)은 이미 그 선결 조건을 충족해 두고 있었다 — coach가
`decide(pack=)`에 넣은 *같은* 팩 객체를 `run_wh1_primary_turn(pack=)`으로 thread하면 러너
전체 도입 없이 톤필터 직전 1좌석 배선으로 끝난다. **PED-23이 그 capability를 현행 main 위에
재적용했다**: `mode_guard_runtime_enabled`(기본 False·옵트인 캔어리) ∧ 팩 주입 시 발화 확정
후·`filter_tone` 직전에 이 가드가 돌고, 위반 발화는 서빙하지 않고 `fallback_reply_for`의
소크라테스 재질문(결정론 템플릿·기존 EXAMPLE_QUESTION 자산)으로 대체한다(fail-closed·
reason_code 구조화 로그). PED-16의 완화 요인(사전 가드 `runtime_selector.forbids_worked_first`)은
불변으로 유지되며, 오프라인 결함주입 측정(`pedagogy_pack_fidelity_eval`)도 그대로 CI 상시다.
상세: `docs/architecture/dsl_integration_gap_review.md` §2-⑤·`docs/architecture/
04g_pedagogy_strategy_catalog.md` §9.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from typing import Protocol

from whymath_backend.l4.socratic.categories import EXAMPLE_QUESTION, SocraticCategory
from whymath_backend.schema.pedagogy_pack import FORBIDDEN_MODE_VOCAB, PedagogyPack

# 가드 컨텍스트 — 검출기에 넘길 선택적 부가 정보 백(문항 메타·k_type 등). v1 검출기는 미사용이나
# 시그니처 seam으로 둔다(후속 검출기가 문항 맥락을 참조할 여지 — 확장 가능).
GuardContext = Mapping[str, object]


class ModeDetector(Protocol):
    """모드 검출기 시그니처 — 응답이 해당 금지 모드를 *위반*하면 True(순수·부작용 0)."""

    def __call__(self, reply: str, *, context: GuardContext | None = None) -> bool: ...


def _nfkc(text: str) -> str:
    """NFKC 정규화 — 전각 물음표(？)·전각 등호(＝) 우회를 ASCII로 붕괴시켜 신호 검사가 잡게 한다."""
    return unicodedata.normalize("NFKC", text)


# ──────────────────────────────────────────────────────────────────────────
# WORKED_EXAMPLE_FIRST(개념형) 휴리스틱 신호 — 방어 가능·보수적
# ──────────────────────────────────────────────────────────────────────────
# 단정 신호: 정의·정답을 *먼저 제시*하는 문면(개념형이 금지하는 "완전예제 선행"의 양성 신호).
_CONCEPT_ASSERTION_SIGNALS: tuple[str, ...] = (
    "정의는",
    "정의하면",
    "라고 정의",
    "로 정의",
    "으로 정의",
    "정의된다",
    "정답은",
    "답은",
    "답:",
    "정답:",
    "란 ",  # "~란 ...이다" 정의 서술
)

# 결론 마커 — `=`(완성 풀이 사슬)와 함께 나타나면 "완전예제"의 결론 제시로 본다.
_CONCLUSION_MARKERS: tuple[str, ...] = ("따라서", "그러므로", "즉,")

# 유도 신호: 응답이 학생을 *질문으로* 이끄는 신호. 하나라도 있으면 "완전예제 선행"이 아니다
# (유도가 살아 있음). 물음표(NFKC로 전각 포함)와 대표 유도 어휘.
_ELICITATION_SIGNALS: tuple[str, ...] = (
    "?",
    "왜",
    "어떻게",
    "어떤",
    "생각",
    "말해",
    "찾아",
    "해볼",
    "볼까",
    "해보자",
    "떠올",
    "구성해",
    "예를 들어볼",
)


def _detect_worked_example_first(reply: str, *, context: GuardContext | None = None) -> bool:
    """WORKED_EXAMPLE_FIRST 위반 검출 — 정의·정답 단정 ∧ 유도 질문 부재면 True.

    개념형 팩은 예/비예로 정의를 *유도*해야 하는데, 응답이 (a) 정의·정답을 단정하거나 완성 풀이
    사슬(`=` + 결론 마커)을 제시하면서 (b) 유도 신호(물음표·유도 어휘)가 전혀 없으면 "완전예제
    선행"으로 판정한다. 보수적(양쪽 조건 모두 필요)이라 유도가 살아 있는 응답은 통과시킨다(오탐
    최소화). 이 휴리스틱은 완전하지 않다 — 단정 없이 우회적으로 정의를 흘리는 경우는 못 잡는다
    (후속 Claude audit 보완). context는 v1 미사용(시그니처 seam).
    """
    del context  # v1 미사용 — 후속 검출기용 시그니처 seam.
    text = _nfkc(reply)
    has_assertion = any(sig in text for sig in _CONCEPT_ASSERTION_SIGNALS) or (
        "=" in text and any(marker in text for marker in _CONCLUSION_MARKERS)
    )
    if not has_assertion:
        return False
    has_elicitation = any(sig in text for sig in _ELICITATION_SIGNALS)
    return not has_elicitation


# ──────────────────────────────────────────────────────────────────────────
# 검출기 레지스트리 — 모드 토큰 → 검출기(커버리지 명시·확장 가능)
# ──────────────────────────────────────────────────────────────────────────
# 규칙 검출 가능한 모드만 등록한다. 미등록 모드는 v1 deferred(정직한 공백·후속 audit) — 아래
# DEFERRED_MODES가 그 목록을 명시한다.
FORBIDDEN_MODE_DETECTORS: dict[str, ModeDetector] = {
    "WORKED_EXAMPLE_FIRST": _detect_worked_example_first,
}

# 규칙 검출 커버리지(명시적 회계 — overclaim 금지) — 등록된 모드 vs 후속 audit 이관 모드.
RULE_DETECTABLE_MODES: frozenset[str] = frozenset(FORBIDDEN_MODE_DETECTORS)
DEFERRED_MODES: frozenset[str] = FORBIDDEN_MODE_VOCAB - RULE_DETECTABLE_MODES


# ──────────────────────────────────────────────────────────────────────────
# 폴백 재질문 — 위반 발화를 대체하는 안전한 소크라테스식 결정론 템플릿 (PED-23 회수)
# ──────────────────────────────────────────────────────────────────────────
# 위반 모드 → 소크라테스 재질문 카테고리. WORKED_EXAMPLE_FIRST(정의·정답 단정)의 안전한 재진입은
# 학생의 현재 이해 지점을 *묻는* 것(명료화) — 04d §2.2 "차단 시 SOCRATIC 강등(말하기 대신 묻기)"
# 선례의 사후 가드판. 미등록 모드(deferred·v1 검출기 없음)는 방어적 기본값 CLARIFICATION —
# 어떤 위반이든 "학생에게 되묻기"가 항상 안전한 강등이다(전량 기존 자산·신규 프로즈 0).
_FALLBACK_CATEGORY: dict[str, SocraticCategory] = {
    "WORKED_EXAMPLE_FIRST": SocraticCategory.CLARIFICATION,
}
_DEFAULT_FALLBACK_CATEGORY = SocraticCategory.CLARIFICATION


def fallback_reply_for(mode: str) -> str:
    """위반 모드 → 안전한 소크라테스식 재질문(결정론 템플릿) — 위반 발화의 대체재.

    정본: `docs/architecture/04g_pedagogy_strategy_catalog.md` §9(런타임 배선)·04d §2.2
    (완전예제 차단 시 SOCRATIC 강등 선례). 런타임 가드가 위반을 검출하면 호출자는 그 발화를
    학생에게 보내지 않고(fail-closed) 이 함수의 재질문으로 *대체*한다. 반환값은
    `l4/socratic/categories.py::EXAMPLE_QUESTION`(스펙 정본 예시 질문)의 기존 자산 그대로다 —
    새 학생-대면 프로즈를 만들지 않는다(교수학 검수 통과 자산 재사용). 순수·전역함수
    (미정의 모드에도 기본 카테고리로 항상 안전한 문자열 반환·예외 0).
    """
    category = _FALLBACK_CATEGORY.get(mode, _DEFAULT_FALLBACK_CATEGORY)
    return EXAMPLE_QUESTION[category]


def check_forbidden_modes(
    pack: PedagogyPack, reply: str, *, context: GuardContext | None = None
) -> str | None:
    """팩이 금지한 모드가 응답에 나타났는지 검사 — 위반 모드 토큰 반환, 없으면 None.

    `pack.forbidden_modes`를 순회하되 **검출기가 등록된 모드만** 검사한다(미등록=deferred·건너뜀·
    clean 선언 아님). 첫 위반 모드 토큰(reason_code)을 반환한다 — 호출자는 이를 "서빙 금지·폴백"
    신호로 쓴다(fail-closed 사용·톤필터 앞 배치). 규칙 검출 가능한 위반이 하나도 없으면 None.

    반환값 None은 "규칙으로는 위반을 못 찾음"이지 "모든 금지 모드가 clean"이 *아니다*(deferred 축은
    이 함수가 판정하지 않는다 — 후속 Claude audit 몫·모듈 docstring 참조).
    """
    for mode in pack.forbidden_modes:
        detector = FORBIDDEN_MODE_DETECTORS.get(mode)
        if detector is None:
            # 규칙 미탐지 모드(LLM 판정 필요) — v1 건너뜀(정직: 통과가 아니라 판정 유보·후속 audit).
            continue
        if detector(reply, context=context):
            return mode
    return None


__all__ = [
    "DEFERRED_MODES",
    "FORBIDDEN_MODE_DETECTORS",
    "RULE_DETECTABLE_MODES",
    "GuardContext",
    "ModeDetector",
    "check_forbidden_modes",
    "fallback_reply_for",
]
