"""페르소나 적합도(`persona_fit`) 결정론 백필 규칙 — S3-10.

문제은행 코퍼스 6종(2,667건)의 `persona_fit`이 전부 `{}`였다(실측 2026-07-28,
`docs/architecture/problem_bank_gap_review.md` §3 D3) — L6 수능·학교진도·RT·메타인지·사고력·
영재 6개 모드가 페르소나 적합도 *폴백* 경로로 `persona_fit[persona] >= min_fit`를 쓰는데, 값이
항상 빈 dict라 그 경로가 항상 공집합으로 죽어 있었다.

이 모듈은 **이미 저작된 문항 필드에서만** 적합도를 유도한다(`signature_tagger.derive_signatures`
와 동일한 비날조 원칙 — LLM 추정 아님·문항을 각색해 신호를 만들지 않음). 입력 신호 4종:

  - **난이도 밴드**(`difficulty_overall`) — 주 신호. 페르소나별 학습 목표(수능 정면 대응·재수
    변별력 강화·검정고시 전 범위·학종 탐구·영재 심화)에 따라 밴드별 기본 적합도가 다르다.
  - **시그니처 패턴**(`signature_patterns`) — 한국 수능 시그니처 보유는 정시 페르소나(A·B·C)
    가산, 케이스분류·그래프개형·단원융합(복합 사고 신호) 보유는 사고력·영재 페르소나(D·E) 가산.
  - **질문 형식**(`question_format`) — 객관식(수능 표준형)·단답형(계산 완결형)·서술형(논증)·
    합답형(단계 구조) 각각이 시사하는 학습 맥락으로 소폭 가산.
  - **오답 진단 유무**(`distractor_map` 존재) — 오개념 역추적 자원 — 재수(B·C)의 오개념
    재구조화 핵심 신호(`l6/retake/gating.py::retake_priority`가 이미 이 신호에 최대 가중을 둠).

**`unit_codes`를 스코어링에 쓰지 않는 이유(의도적 단순화, 정직한 공백)**: 작성 당시 코퍼스는 6종
전부 `subject="공통"`·문항당 `unit_codes` 정확히 1개였고, 저장소 안에 unit_code→난이도 등급/과목
계열을 잇는 권위 있는 매핑이 없었다(`units_v1` 코퍼스도 당시 1건뿐 — 현재 건수는
`docs/data/corpus_facts.md`의 `units.count`). 근거 없는 unit_code별 가중은 "LLM 추정"과 같은 종류의
날조가 된다 — 그래서 `unit_codes`는 리포트의 *그룹핑 키*로만 쓰고 점수에는 반영하지 않는다.
페르소나별 세밀 조정(단원 계열 반영 포함)은 D9(파일럿 실데이터) 후속.

7계층: L1 지역 순수 규칙(l1→schema 하향 import만·LLM 0·DB 0·부수효과 0). `signature_tagger.py`
와 나란히 두되 축은 분리한다(시그니처는 그 모듈의 단일 권위·페르소나 적합도는 이 모듈의 단일
권위 — Concept Purity: 한 모듈이 한 축만 다룬다).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from whymath_backend.schema.enums import Persona, QuestionFormat, SignaturePattern
from whymath_backend.schema.problem import Problem

__all__ = [
    "DifficultyBand",
    "PersonaFitRationale",
    "classify_difficulty_band",
    "derive_persona_fit",
]

# 출력 dict의 키 순서(결정론) — 항상 A→E 고정 순서로 직렬화해 재실행 바이트 동일성을 보장한다.
_PERSONA_ORDER: tuple[Persona, ...] = (
    Persona.A_일반고고3,
    Persona.B_자사고N수,
    Persona.C_검정고시N수,
    Persona.D_학종고2,
    Persona.E_홈스쿨링영재,
)


class DifficultyBand(str, Enum):
    """`difficulty_overall`(1.0~5.0, None 허용) 난이도 밴드 — 페르소나 기본 적합도의 1축."""

    UNKNOWN = "UNKNOWN"
    """난이도 미기재(`difficulty_overall is None`) — 신호 없음, 전 페르소나 중립 이하."""

    BASIC = "BASIC"
    """< 2.0 — 기초 개념 확인 수준."""

    CORE = "CORE"
    """2.0 ~ 2.9 — 수능 핵심(주류) 난이도."""

    MID_HIGH = "MID_HIGH"
    """3.0 ~ 3.4 — 수능 변별 구간."""

    HIGH = "HIGH"
    """3.5 ~ 3.9 — 상위권 변별(최상위 직전)."""

    KILLER = "KILLER"
    """>= 4.0 — 킬러문항(최상위 변별·영재 심화 진입)."""


def classify_difficulty_band(difficulty_overall: float | None) -> DifficultyBand:
    """`difficulty_overall`을 5구간 밴드로 분류(None은 UNKNOWN — 조용히 0.0으로 흘리지 않음)."""
    if difficulty_overall is None:
        return DifficultyBand.UNKNOWN
    if difficulty_overall < 2.0:
        return DifficultyBand.BASIC
    if difficulty_overall < 3.0:
        return DifficultyBand.CORE
    if difficulty_overall < 3.5:
        return DifficultyBand.MID_HIGH
    if difficulty_overall < 4.0:
        return DifficultyBand.HIGH
    return DifficultyBand.KILLER


# 밴드별 기본 적합도(페르소나 5종) — 근거:
#   A(일반고고3·MVP·정시 정면) — 전 구간 고르게 높되 킬러에서도 급락하지 않는다(수능 최상위
#     구간까지 A의 학습 범위 — 갭 리뷰 예시 "킬러 Vieta → A 고3 고적합"과 정합).
#   B(자사고N수·결제 최대·RT+정시) — 난이도가 오를수록 적합도가 오른다(재수의 목표가 변별력
#     강화이므로 상위 구간일수록 학습 가치가 크다).
#   C(검정고시N수·수학의존도100%·정시) — 기초~핵심 전 범위를 촘촘히 다져야 해 저·중난도에서
#     가장 높고 심화로 갈수록 완만히 낮아진다(전 범위 확보가 우선순위).
#   D(학종고2·세특/자유연구·정시 비대상) — 전 구간에서 A·B보다 낮되 밴드에 따라 오히려
#     완만히 상승한다(탐구 소재로서 변별 구간 이상 문항이 더 유용).
#   E(홈스쿨링영재·심화) — 밴드가 오를수록 뚜렷이 상승, 킬러에서 최고치에 근접한다.
_BAND_BASE_FIT: dict[DifficultyBand, dict[Persona, float]] = {
    DifficultyBand.UNKNOWN: {
        Persona.A_일반고고3: 0.30,
        Persona.B_자사고N수: 0.30,
        Persona.C_검정고시N수: 0.30,
        Persona.D_학종고2: 0.30,
        Persona.E_홈스쿨링영재: 0.30,
    },
    DifficultyBand.BASIC: {
        Persona.A_일반고고3: 0.90,
        Persona.B_자사고N수: 0.50,
        Persona.C_검정고시N수: 0.80,
        Persona.D_학종고2: 0.40,
        Persona.E_홈스쿨링영재: 0.30,
    },
    DifficultyBand.CORE: {
        Persona.A_일반고고3: 0.90,
        Persona.B_자사고N수: 0.60,
        Persona.C_검정고시N수: 0.85,
        Persona.D_학종고2: 0.50,
        Persona.E_홈스쿨링영재: 0.35,
    },
    DifficultyBand.MID_HIGH: {
        Persona.A_일반고고3: 0.85,
        Persona.B_자사고N수: 0.75,
        Persona.C_검정고시N수: 0.70,
        Persona.D_학종고2: 0.55,
        Persona.E_홈스쿨링영재: 0.50,
    },
    DifficultyBand.HIGH: {
        Persona.A_일반고고3: 0.75,
        Persona.B_자사고N수: 0.85,
        Persona.C_검정고시N수: 0.60,
        Persona.D_학종고2: 0.60,
        Persona.E_홈스쿨링영재: 0.65,
    },
    DifficultyBand.KILLER: {
        Persona.A_일반고고3: 0.70,
        Persona.B_자사고N수: 0.90,
        Persona.C_검정고시N수: 0.50,
        Persona.D_학종고2: 0.60,
        Persona.E_홈스쿨링영재: 0.85,
    },
}

# 시그니처 패턴 보유 가산 — 한국 수능 시그니처 자산은 정시 페르소나(A·B·C)에 가산한다
# (`l6/suneung/gating.py`가 signature_patterns 비공집합 자체를 적격 신호로 이미 인정하는 것과
# 같은 근거 — 여기서는 *적격*이 아니라 *적합도 점수*를 소폭 더한다).
_SIGNATURE_BONUS: float = 0.05
_SIGNATURE_BONUS_PERSONAS: tuple[Persona, ...] = (
    Persona.A_일반고고3,
    Persona.B_자사고N수,
    Persona.C_검정고시N수,
)

# 복합 사고 신호 시그니처 3종 — 케이스분류·그래프개형추론·단원융합은 표면 유형이 아니라 고차
# 인지 행동을 드러내는 시그니처라 사고력(D)·영재(E) 페르소나에 가산한다. L6(`l6/thinking/gating.py`
# 의 `_THINKING_SIGNATURE_PATTERNS`)와 *의도적으로 독립 정의*한다 — L1은 L6를 알지 못한다
# (7계층 역방향 의존 금지). 값이 같은 것은 같은 시그니처가 "고차 사고"를 뜻하는 게 우연이 아니라
# `SignaturePattern` enum 자체의 의미이기 때문이다(양쪽 다 그 의미를 각자 인용할 뿐 서로 참조하지
# 않는다).
_COMPLEX_REASONING_BONUS: float = 0.10
_COMPLEX_REASONING_SIGNATURES: frozenset[SignaturePattern] = frozenset(
    {
        SignaturePattern.CASE_ANALYSIS_DEEP,
        SignaturePattern.GRAPH_SHAPE_INFERENCE,
        SignaturePattern.CROSS_UNIT_FUSION,
    }
)
_COMPLEX_REASONING_BONUS_PERSONAS: tuple[Persona, ...] = (
    Persona.D_학종고2,
    Persona.E_홈스쿨링영재,
)

# 질문 형식 가산 — 형식이 시사하는 학습 맥락에 소폭 가산한다. 신규 P3a 유형(객관식진단 등)이나
# None은 이 표에 없으므로 가산 0(결정론 기본값 — 표에 없는 값을 조용히 추측하지 않는다).
_FORMAT_BONUS: float = 0.05
_FORMAT_BONUS_PERSONAS: dict[QuestionFormat, tuple[Persona, ...]] = {
    # 객관식 — 수능 표준 응시 형식(정시 페르소나 A·C).
    QuestionFormat.객관식: (Persona.A_일반고고3, Persona.C_검정고시N수),
    # 단답형 — 계산 완결형(재수 B의 실전 감각·영재 E의 정확한 산출).
    QuestionFormat.단답형: (Persona.B_자사고N수, Persona.E_홈스쿨링영재),
    # 서술형 — 논증 서술(학종 D의 세특 자료·영재 E의 사고 과정 기술).
    QuestionFormat.서술형: (Persona.D_학종고2, Persona.E_홈스쿨링영재),
    # 합답형 — 단계형 구조 분석(학종 D의 탐구 정리에 적합).
    QuestionFormat.합답형: (Persona.D_학종고2,),
}

# 오답 진단 유무 가산 — distractor_map 보유는 메타인지 코칭 자원(전 페르소나 공통 소폭 가산)
# 이면서 특히 재수(B·C)의 오개념 재구조화 핵심 신호다(`l6/retake/gating.py::retake_priority`가
# distractor_map 보유에 가장 큰 가중 +2.0을 두는 것과 같은 근거의 소폭 반영).
_DISTRACTOR_BONUS_ALL: float = 0.05
_DISTRACTOR_BONUS_EXTRA: float = 0.05
_DISTRACTOR_BONUS_EXTRA_PERSONAS: tuple[Persona, ...] = (
    Persona.B_자사고N수,
    Persona.C_검정고시N수,
)


@dataclass(frozen=True, slots=True)
class PersonaFitRationale:
    """계산 근거 — "근거 동반" 요건. 감사 리포트(`harness` CLI)가 그대로 직렬화해 남긴다.

    각 필드는 *이 문항에 실제로 적용된* 가산 구성요소만 담는다(적용되지 않은 축은 빈 dict) —
    재현 가능한 계산 추적이지, 사후 설명이 아니다(값은 `derive_persona_fit`과 같은 라운딩 규칙).
    """

    band: DifficultyBand
    band_base: dict[str, float]
    signature_bonus: dict[str, float]
    complex_reasoning_bonus: dict[str, float]
    format_bonus: dict[str, float]
    distractor_bonus: dict[str, float]
    final: dict[str, float]


def _as_value(value: Enum | str | None) -> str | None:
    """enum/문자열/None을 *문자열 값*으로 정규화.

    use_enum_values=True 대응(`signature_tagger._as_value`와 동형 — 의도적 중복, 모듈 docstring
    "Concept Purity" 근거와 같은 이유로 축을 나누고 서로 참조하지 않는다).
    """
    if value is None:
        return None
    if isinstance(value, Enum):
        return str(value.value)
    return value


def _as_value_non_none(value: Enum | str) -> str:
    """`_as_value`의 비-None 변형 — `signature_patterns` 원소(항상 존재)에 쓴다."""
    return str(value.value) if isinstance(value, Enum) else value


def _normalized_signatures(problem: Problem) -> frozenset[str]:
    """`signature_patterns`을 문자열 값 집합으로 정규화(enum/문자열 혼재 대응)."""
    return frozenset(_as_value_non_none(pattern) for pattern in problem.signature_patterns)


def derive_persona_fit(problem: Problem) -> tuple[dict[str, float], PersonaFitRationale]:
    """문항 필드에서 `persona_fit`을 결정론 유도 — (점수 dict, 계산 근거) 반환.

    순수 함수다: `problem`의 어떤 필드도 변경하지 않는다. 반환 dict는 A→E 고정 순서로 삽입되고
    (`_PERSONA_ORDER`), 값은 [0.0, 1.0]로 클립·소수 둘째 자리 반올림한다(재실행 동일 출력).
    같은 입력은 항상 같은 출력(결정론)·부수효과 없음(I/O·LLM 호출 없음)·`signature_tagger`와
    동일한 비날조 원칙(문항 필드에 실제로 있는 신호만 조합).

    Args:
      problem: 대상 문항(L1 `Problem`). `persona_fit` 현재 값은 참조하지 않는다(호출자가
        "현재 비어 있는 문항만 채운다"는 판단을 하도록 이 함수는 항상 새로 계산만 한다).

    Returns:
      `(persona_fit, rationale)` — `persona_fit`은 `dict[str, float]`(Persona.value 키),
      `rationale`은 감사 리포트용 계산 근거(`PersonaFitRationale`).
    """
    band = classify_difficulty_band(problem.difficulty_overall)
    base = _BAND_BASE_FIT[band]

    signatures = _normalized_signatures(problem)
    has_signature = bool(signatures)
    has_complex_reasoning = bool(
        signatures & {pattern.value for pattern in _COMPLEX_REASONING_SIGNATURES}
    )
    format_value = _as_value(problem.question_format)
    format_bonus_personas = next(
        (personas for fmt, personas in _FORMAT_BONUS_PERSONAS.items() if fmt.value == format_value),
        (),
    )
    has_distractor = bool(problem.distractor_map)

    signature_bonus: dict[str, float] = {}
    complex_reasoning_bonus: dict[str, float] = {}
    format_bonus: dict[str, float] = {}
    distractor_bonus: dict[str, float] = {}
    final: dict[str, float] = {}

    for persona in _PERSONA_ORDER:
        score = base[persona]

        if has_signature and persona in _SIGNATURE_BONUS_PERSONAS:
            signature_bonus[persona.value] = _SIGNATURE_BONUS
            score += _SIGNATURE_BONUS

        if has_complex_reasoning and persona in _COMPLEX_REASONING_BONUS_PERSONAS:
            complex_reasoning_bonus[persona.value] = _COMPLEX_REASONING_BONUS
            score += _COMPLEX_REASONING_BONUS

        if persona in format_bonus_personas:
            format_bonus[persona.value] = _FORMAT_BONUS
            score += _FORMAT_BONUS

        if has_distractor:
            bonus = _DISTRACTOR_BONUS_ALL
            if persona in _DISTRACTOR_BONUS_EXTRA_PERSONAS:
                bonus += _DISTRACTOR_BONUS_EXTRA
            distractor_bonus[persona.value] = bonus
            score += bonus

        final[persona.value] = round(max(0.0, min(1.0, score)), 2)

    rationale = PersonaFitRationale(
        band=band,
        band_base={persona.value: base[persona] for persona in _PERSONA_ORDER},
        signature_bonus=signature_bonus,
        complex_reasoning_bonus=complex_reasoning_bonus,
        format_bonus=format_bonus,
        distractor_bonus=distractor_bonus,
        final=final,
    )
    return final, rationale
