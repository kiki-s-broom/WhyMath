"""P3-10 AI 품질 8축 판정기 — 튜터 턴 응답 1건을 축마다 기계로 판정한다(순수·결정론·LLM 0).

**측정 권위는 EOS 검증 레이어다**(acceptance ④ — 이 시점부터 모델 성능보다 검증 레이어가 중요하다).
축마다 이미 저장소에 있는 검증 장치를 판정기로 그대로 부른다 — 새 판정 규칙은 대응 장치가 없는
두 축(Hint 적절성·설명 일관성)과 튜터 턴에만 있는 재료(사다리·학생 위치)에만 둔다.

| 축 | 판정 권위(재사용) | 이 모듈이 더한 것 |
|---|---|---|
| 수학적 정확성 | SymPy 단일 권위 — `l3.verify_step.verify_step`(문항 조건 → 주장 식, 해집합 보존) ·
  `l3.pregenerate.validator.arithmetic_validator`(문맥 무관 수치 관계·단변수 해 일관성) | 본문에서
  관계식 추출 · 학생 가정 인용(오개념 정형 진술) 제외 · "판정한 주장" 회계 |
| 정답 누설 | `harness.pedagogical_rubric.detect_answer_leakage`(정답 문자열) · `l3.safe_parse`(동치
  산술식) | 정답 선언 어구 · 최종 풀이 단계 문자열 · 학생이 이미 정답에 닿은 턴 제외 |
| 오개념 판정 정확도 | 라벨 = 승인 `distractor_map`(평가셋) · 임계 = 내용 KPI `오개념 op-code 라벨
  정확도 ≥85%` | 응답 `diagnosis.misconception_id` ↔ 라벨 대조 |
| Hint 적절성(신설) | 단계 결정 = `l4.hint_deferral.decide_hint_level` · 단계-노출 정합 =
  `l4.hint_content.gates.check_level_reveals`(S4-11 게이트 A) | 사다리 내 노출 단조성 |
| 설명 일관성(신설) | 구조 일관성 = `harness.wh1_tutor_output.TutorTurnOutput`(P3-09 스키마) |
  다음 행동 ↔ 검증 판정 · 발화 극성 ↔ 검증 판정 · 정답 판정 턴의 오개념 진단 금지 |
| 학생 수준 적합성 | 표기 구조 ↔ 학년 밴드 = MATH-04(`extract_range_tokens` ·
  `constructs_by_band`) | 아직 배우지 않은 개념(선수 그래프 후손) 참조 · 개념 학교급 > 학생 밴드 |
| hallucination | 개념 그래프 ids · 런타임 오개념 카탈로그 · 성취기준 정본 · M-id 색인 | 본문 속 id
  모양 문자열(개념 code·성취기준 코드·M-id) 추출 |
| Curriculum 범위 이탈 | P3-01 명세 + 선수 조상(깊이 ≤ 2) | 구조 참조·본문 id·본문 개념 이름 |

LLM 판정자에 의존하는 항목은 **0개**다. 그 대신 기계 정의가 못 보는 것(사각)을 축마다
`BLIND_SPOTS`에 적고 리포트가 그대로 싣는다 — 사각이 있는 채로 "통과"를 말하면 그 통과는 사각까지
포함한 주장이 된다.

응답의 모양
-----------
`TutorResponse.tutor_output`은 P3-09 `TutorTurnOutput`의 **원시 dict**다(검증 전). 판정기는 모델로
변환하지 않고 dict를 직접 본다 — 스키마를 어긴 응답(예: `hint_level: "2"`)도 축별로 판정해야 하기
때문이다. `referenced_concept_ids`는 튜터가 이번 턴에 참조한 개념 id(도구 호출·인용)다.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from tokenize import TokenError
from typing import Any, Final

import sympy
from pydantic import ValidationError

from whymath_backend.harness.ai_quality_eval_set import (
    KIND_HINT,
    EvalCase,
    EvalSet,
    ProblemMaterial,
)
from whymath_backend.harness.ai_quality_registry import BAND_RANK, Registry, normalize_text
from whymath_backend.harness.pedagogical_rubric import LeakageVerdict, detect_answer_leakage
from whymath_backend.harness.wh1_tutor_output import TutorTurnOutput, validate_tutor_output
from whymath_backend.l3.curriculum_notation_gate import extract_range_tokens
from whymath_backend.l3.pregenerate.validator import arithmetic_validator, validate_response
from whymath_backend.l3.safe_parse import safe_sympify
from whymath_backend.l3.verify_solution import scan_value_exposure
from whymath_backend.l3.verify_step import VerifyStepState, verify_step
from whymath_backend.l4.hint_content.gates import GateContext, check_level_reveals
from whymath_backend.l4.hint_content.models import Hint, HintReveals, SolutionStepRef
from whymath_backend.l4.hint_deferral import decide_hint_level
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.l4.subject_adapter_math import math_answer_value_exposure
from whymath_backend.schema.speech import SpeechGradeBand

__all__ = [
    "AXES",
    "AXIS_SPECS",
    "BLIND_SPOTS",
    "AxisSpec",
    "Judgment",
    "JudgeContext",
    "TutorResponse",
    "derived_disclosure_tier",
    "expected_next_action",
    "judge_case",
    "p309_blocks",
    "prepare_ladder_tiers",
]

AXES: Final[tuple[str, ...]] = (
    "math_correctness",
    "answer_leak",
    "misconception_accuracy",
    "hint_appropriateness",
    "explanation_consistency",
    "student_level_fit",
    "hallucination",
    "curriculum_scope",
)


@dataclass(frozen=True)
class AxisSpec:
    """축 1개의 정의 — 판정 방향·임계·KPI 대응·재사용 판정(acceptance ③)."""

    axis: str
    name_ko: str
    direction: str
    """`ceiling` = 실패율 Wilson 상한 ≤ 임계 · `floor` = 통과율 Wilson 하한 ≥ 임계."""
    threshold: float
    threshold_basis: str
    """임계의 출처 — KPI 재사용인지, 이 태스크의 **제안값**(Kiki 확인 전)인지."""
    kpi_mapping: str
    """2회차 §11-5 대응 KPI·Hard Gate."""
    decision: str
    """재사용 / 래핑 / 신설."""
    reuse: str
    min_n: int = 30
    """이보다 판정 대상이 적으면 측정 실패(unmeasured) — 통과로 접지 않는다."""
    zero_tolerance: bool = False
    """True면 Wilson 판정과 별개로 실패 1건이라도 있으면 FAIL(무관용 축 — 표본이 커져도 실패를
    흡수하지 않는다. Wilson 상한만 쓰면 199건 중 4건 누설이 '통과'가 된다 — 2026-10-21 실측)."""


AXIS_SPECS: Final[Mapping[str, AxisSpec]] = {
    "math_correctness": AxisSpec(
        axis="math_correctness",
        name_ko="수학적 정확성",
        direction="ceiling",
        threshold=0.05,
        threshold_basis=(
            "제안값(Kiki 확인 전). KPI '수학적 오류율 ≤0.5%'는 CU 단위·독립 모델 심판 전수 지표라 "
            "그대로 쓰면 실패 0건으로도 표본 540건 미만에서 통과가 불가능하다(0/540 상한 0.0050)."
        ),
        kpi_mapping="KPI 수학적 오류율 ≤0.5% · Hard Gate F-Ⅱ(검수 통과 CU 오류율 >2%) · SymPy 단일 "
        "권위",
        decision="래핑 — KPI 판정기(qa_confusion_matrix)는 골든 CU 혼동행렬이라 튜터 턴에 못 쓴다. "
        "판정 권위(SymPy verify_step·arithmetic_validator)를 그대로 호출하고 주장 추출만 더한다",
        reuse="l3.verify_step.verify_step · l3.pregenerate.validator.arithmetic_validator",
    ),
    "answer_leak": AxisSpec(
        axis="answer_leak",
        name_ko="정답 누설",
        direction="ceiling",
        threshold=0.05,
        threshold_basis=(
            "제안값(Kiki 확인 전). KPI '힌트 누설률 L1·L2 무관용 0%'를 따라 실패 "
            "1건이면 FAIL(무관용) "
            "+ 표본 충분성으로 실패율 Wilson 상한 ≤ 0.05(실패 0건이면 표본 53건 이상)."
        ),
        kpi_mapping="KPI 힌트 누설률 L1·L2 (무관용 0%) · Hard Gate F-Ⅴ(의미적 누설 ≥10%)",
        decision="재사용 + 래핑 — detect_answer_leakage(문자열) 재사용, 동치 산술식·정답 선언·최종 "
        "단계 문자열 검출을 더한다(지시문 ③ '정답 문자열·동치식 포함 여부')",
        reuse="harness.pedagogical_rubric.detect_answer_leakage · l3.safe_parse.safe_sympify",
        zero_tolerance=True,
    ),
    "misconception_accuracy": AxisSpec(
        axis="misconception_accuracy",
        name_ko="오개념 판정 정확도",
        direction="floor",
        threshold=0.85,
        threshold_basis="KPI 재사용 — validation_scorecard.CONTENT_KPI_THRESHOLDS"
        "['오개념 op-code 라벨 정확도 ≥85%'] (floor 0.85)",
        kpi_mapping="KPI 오개념 op-code 라벨 정확도 ≥85% · EOS-60 혼동행렬 FN율",
        decision="재사용(임계) + 래핑(라벨 대조) — EOS-60 채점기는 골든 F6 라벨 축이 0건이라 "
        "소비 지점이 없다(CONTENT_KPI_CONSUMERS consumer_module=None). 라벨 = 승인 distractor_map",
        reuse="ops.validation_scorecard.CONTENT_KPI_THRESHOLDS · harness.wilson",
    ),
    "hint_appropriateness": AxisSpec(
        axis="hint_appropriateness",
        name_ko="Hint 적절성",
        direction="floor",
        threshold=0.90,
        threshold_basis="제안값(Kiki 확인 전) — 대응 KPI 없음(§11-5 '부분 대응')",
        kpi_mapping="대응 KPI 없음 — 누설(정답 누설 축)만 재고 '적절성' 지표는 0건(§11-5)",
        decision="신설 — 판정 부품은 재사용: 단계 = decide_hint_level · 단계-노출 정합 = S4-11 "
        "게이트 A(check_level_reveals) · 더한 것 = 사다리 노출 단조성",
        reuse="l4.hint_deferral.decide_hint_level · l4.hint_content.gates.check_level_reveals",
    ),
    "explanation_consistency": AxisSpec(
        axis="explanation_consistency",
        name_ko="설명 일관성",
        direction="floor",
        threshold=0.90,
        threshold_basis="제안값(Kiki 확인 전) — 인접 KPI '풀이 비약 지적률 ≤10%'와 같은 눈금",
        kpi_mapping="인접 KPI 풀이 비약 지적률 ≤10%(LLM 심판 κ≥0.5) — 동일 축 아님(§11-5 '부분 "
        "대응')",
        decision="신설 — 구조 일관성은 P3-09 TutorTurnOutput 스키마를 재사용, 다음 행동·발화 극성·"
        "진단을 검증 판정과 대조하는 규칙을 더한다",
        reuse="harness.wh1_tutor_output.TutorTurnOutput",
    ),
    "student_level_fit": AxisSpec(
        axis="student_level_fit",
        name_ko="학생 수준 적합성",
        direction="floor",
        threshold=0.90,
        threshold_basis=(
            "제안값(Kiki 확인 전). KPI '난이도 타당도'는 문항 순위 상관(ρ)이라 튜터 턴 비율 임계로 "
            "옮길 수 없다"
        ),
        kpi_mapping="KPI 난이도 타당도(깊이 Spearman ρ≥0.5·폭 ρ≥0.6) — 문항 축이라 튜터 턴에 직접 "
        "대응하지 않는다(§7-4 12월 내 미검증 자인)",
        decision="래핑 — 표기 구조 ↔ 학년 밴드는 MATH-04 부품 재사용, 아직 배우지 않은 개념(선수 "
        "그래프 후손)·개념 학교급 대조를 더한다",
        reuse="l3.curriculum_notation_gate.extract_range_tokens · "
        "harness.curriculum_notation_gate_cli.constructs_by_band",
    ),
    "hallucination": AxisSpec(
        axis="hallucination",
        name_ko="hallucination",
        direction="ceiling",
        threshold=0.05,
        threshold_basis="제안값(Kiki 확인 전) — 존재하지 않는 id 참조는 "
        "무관용(실패 1건이면 FAIL) + "
        "표본 충분성으로 실패율 Wilson 상한 ≤ 0.05",
        kpi_mapping="PRM/도구 검증 필수 계약 + 수학적 오류율(§11-5) — 비율 KPI는 없다",
        decision="재사용 + 래핑 — P3-09 카탈로그·개념 id 검사와 정본 색인을 그대로 쓰고, 본문 속 "
        "id 모양 문자열 추출을 더한다",
        reuse="l4.misconception.catalog.CATALOG_BY_ID · "
        "l1.standards.phase3_scope.load_reference_index"
        " · harness.wh1_tutor_output.validate_tutor_output(노출 경로 판정)",
        zero_tolerance=True,
    ),
    "curriculum_scope": AxisSpec(
        axis="curriculum_scope",
        name_ko="Curriculum 범위 이탈",
        direction="floor",
        threshold=0.92,
        threshold_basis="KPI 재사용 — '교육과정 정합률 ≥92%'(floor 0.92) 값",
        kpi_mapping="KPI 교육과정 정합률 ≥92%(블라인드 역매핑) + MATH-04(표기 범위 게이트)",
        decision="래핑 — KPI 채점기는 미착지(CONTENT_KPI_CONSUMERS "
        "consumer_module=None)라 임계값만 "
        "재사용하고, 판정은 P3-01 명세(+선수 조상 깊이 2)로 한다",
        reuse="l1.standards.phase3_scope.load_scope_spec · ops.validation_scorecard 임계값",
    ),
}

BLIND_SPOTS: Final[Mapping[str, tuple[str, ...]]] = {
    "math_correctness": (
        "본문의 '좌변 = 우변' 관계만 본다 — 등호 없는 서술('x^4의 도함수는 3x^3')은 판정하지 "
        "않는다.",
        "문항 조건과의 대조(verify_step)는 힌트 사례에만 쓴다. 선택 사례는 문맥 무관 산술만 본다 — "
        "예시를 드는 발화(반례)의 변수는 문항 변수가 아니기 때문이다.",
        "판정 불가(unverifiable) 주장은 통과도 실패도 아니다 — 판정한 주장이 1건도 없는 응답은 "
        "이 축의 분모에서 빠진다.",
    ),
    "answer_leak": (
        "정답이 1자(예: '7')면 문자열 판정이 유보된다(detect_answer_leakage 규약) — 선언 어구·동치 "
        "산술식·최종 단계 문자열이 대신 잡는다. 말로 풀어 쓴 정답('일곱')은 못 잡는다.",
        "동치식은 문자 없는 순수 산술식만 본다 — 'f(3)'처럼 함수 표기로 정답을 말하는 것은 못 "
        "잡는다.",
    ),
    "misconception_accuracy": (
        "라벨과 결정론 진단기가 같은 원천(승인 distractor_map)을 읽는다 — 결정론 후보로 잰 점수는 "
        "회귀 감시이지 독립 정확도가 아니다.",
        "객관식 채널만 잰다 — 단답형 오답은 오류 서명이 없다(P3-06 범위 밖 결정 승계).",
    ),
    "hint_appropriateness": (
        "단계-노출 정합은 S4-11 게이트 A의 문자열 규칙이다 — L1은 개념 이름의 "
        "정확한 포함, L2는 단계 "
        "흐름 표지('N단계' 등), L3는 풀이 단계 식의 포함을 요구한다. "
        "동의어·풀어 쓴 흐름은 인정하지 "
        "않는다.",
        "힌트의 교수학적 질(발문의 좋음)은 재지 않는다 — 노출량의 단계 정합과 단조성만 본다.",
    ),
    "explanation_consistency": (
        "발화 극성은 어휘 목록으로 본다 — 목록 밖 표현('그 방향 좋네')의 긍정·부정은 못 잡는다.",
        "설명 본문의 의미가 진단·풀이와 맞는지(의미적 일관성)는 재지 않는다 — 구조·판정 대조만 "
        "본다.",
    ),
    "student_level_fit": (
        "평가셋 학생은 전부 고등 밴드다 — 표기 구조 검사(MATH-04)와 개념 "
        "학교급 검사는 이 평가셋에서 "
        "실패를 낼 수 없다(고등이 전 구조 도입·개념 그래프에 대학 밴드 없음). 이 축의 변별력은 "
        "'아직 배우지 않은 개념' 검사에서 나온다. 두 검사의 작동은 단위 테스트(중등 밴드)가 "
        "봉인한다.",
        "본문 개념 언급은 개념 이름 정확 일치(4자 이상)만 잡는다 — 약칭·동의어는 못 잡는다.",
        "원시 SymPy 코드 표기(`Derivative(4*x - 3, x)`·`.doit()` 등)를 학생 대면 표기로 보지 "
        "않는다 — L3 힌트가 이 표기를 그대로 보여 줘도 이 축은 통과한다(2026-10-21 리뷰 실측: "
        "aq-h-06-04-l3 계열).",
    ),
    "hallucination": (
        "id 모양 문자열(개념 code·성취기준 코드·M-id)과 구조 참조만 본다 — 본문에 지어낸 개념 "
        "*이름*(예: '미분 역류 정리')은 실재 목록과 대조할 근거가 없어 못 잡는다.",
    ),
    "curriculum_scope": (
        "본문 개념 언급은 개념 이름 정확 일치만 잡는다 — 이름이 아닌 "
        "서술로 범위 밖 내용을 가르치는 "
        "것은 못 잡는다.",
    ),
}


# ──────────────────────────────────────────────────────────────────────────
# 응답·판정 타입
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class TutorResponse:
    """튜터 턴 응답 1건 — P3-09 출력의 원시 dict + 참조 개념 id + 출처 표지."""

    case_id: str
    tutor_output: Mapping[str, Any]
    referenced_concept_ids: tuple[str, ...] = ()
    origin: str = "external"
    note: str | None = None


@dataclass(frozen=True)
class Judgment:
    """한 사례 × 한 축의 판정 — 대상 여부·통과 여부·사유·하위 검사 작동 회계."""

    applicable: bool
    passed: bool
    reasons: tuple[str, ...] = ()
    counters: Mapping[str, int] = field(default_factory=dict)


@dataclass
class JudgeContext:
    """판정 재료 — 레지스트리·평가셋·사다리 노출 등급(사전 계산)."""

    registry: Registry
    eval_set: EvalSet
    ladder_tiers: dict[str, int] = field(default_factory=dict)
    """case_id → 본문 파생 노출 등급(Hint 적절성 축 단조성 검사용)."""


def _explanation(output: Mapping[str, Any]) -> str:
    value = output.get("explanation")
    return value if isinstance(value, str) else ""


def _diagnosis(output: Mapping[str, Any]) -> Mapping[str, Any]:
    value = output.get("diagnosis")
    return value if isinstance(value, dict) else {}


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


# ──────────────────────────────────────────────────────────────────────────
# ① 수학적 정확성
# ──────────────────────────────────────────────────────────────────────────
_OP_NORMALIZE: Final = str.maketrans({"×": "*", "÷": "/", "−": "-", "·": "*"})
_MATH_RUN: Final = re.compile(r"[0-9A-Za-z_+\-*/^().,' \t×÷−·]*=[0-9A-Za-z_+\-*/^().,=' \t×÷−·]*")
_HAS_LETTER: Final = re.compile(r"[A-Za-z]")
_HAS_DIGIT_OR_LETTER: Final = re.compile(r"[0-9A-Za-z]")


def _strip_quoted_misconception(text: str, output: Mapping[str, Any]) -> str:
    """진단 오개념의 정형 진술(학생 가정 인용)을 본문에서 지운다 — 의도된 거짓 진술이다."""
    mid = _str_or_none(_diagnosis(output).get("misconception_id"))
    entry = CATALOG_BY_ID.get(mid) if mid is not None else None
    if entry is None:
        return text
    return text.replace(entry.canonical_statement, " ")


def extract_relations(text: str) -> list[str]:
    """본문 → '좌변 = 우변' 관계식 후보(양변에 숫자나 문자가 있는 것만)."""
    out: list[str] = []
    for match in _MATH_RUN.finditer(text.translate(_OP_NORMALIZE)):
        rel = match.group(0).strip(" \t,.")
        if "==" in rel:
            continue
        sides = rel.split("=")
        if len(sides) < 2 or not all(_HAS_DIGIT_OR_LETTER.search(s) for s in sides):
            continue
        out.append(rel)
    return out


#: 식 해석 실패로 *예상되는* 예외 — 이것만 '판정 불가'로 접는다. 그 밖(TypeError·AttributeError 등
#: 호출 계약이 깨진 프로그래밍 오류)은 삼키지 않고 올려 보낸다 — 삼키면 정답 누설 같은 무관용 축이
#: 조용히 통과로 바뀐다(2026-10-21 리뷰 실측: `safe_sympify` 호출이 TypeError를 내도록 깨뜨리자
#: 누설 축 217/217 PASS·종합 exit 0으로 실결함이 사라졌다). 올라간 예외는 축 판정기에서 측정 실패로
#: 계상되고 타입명이 남는다(`ai_quality_eval._judge_axis`).
_PARSE_FAILURES: Final[tuple[type[BaseException], ...]] = (
    sympy.SympifyError,
    TokenError,
    SyntaxError,
    ValueError,
    ZeroDivisionError,
    OverflowError,
    RecursionError,
)

_LOG: Final = logging.getLogger(__name__)


def _closed_numeric(expr: str) -> Any | None:
    """문자 없는 산술식 → 수치(sympy). 파싱 실패·비수치면 None(판정 불가)."""
    if _HAS_LETTER.search(expr):
        return None
    try:
        value = safe_sympify(expr.replace("^", "**"))
    except _PARSE_FAILURES as exc:  # 판정 불가 — 통과도 실패도 아니다(아래 회계에서 unverifiable)
        _LOG.debug("산술식 해석 불가(%s) — 판정 불가로 계상", type(exc).__name__)
        return None
    return value if getattr(value, "is_number", False) else None


@lru_cache(maxsize=65536)
def _step_state(before: str, after: str) -> VerifyStepState:
    """`verify_step` 판정 캐시 — 순수 함수라 문자열 쌍으로 기억해도 된다(자가 점검 9회 반복)."""
    return verify_step(before, after).state


@lru_cache(maxsize=65536)
def _relation_symbols(rel: str) -> frozenset[str] | None:
    """관계식의 자유 변수 이름 집합(SymPy 해석 — `.subs`·`.doit()` 적용 후). 해석 불가면 None."""
    names: set[str] = set()
    for side in rel.split("="):
        try:
            expr = safe_sympify(side.replace("^", "**"))
        except _PARSE_FAILURES as exc:  # 해석 불가 — 비교 대상에서 뺀다(판정 불가로 귀결)
            _LOG.debug("관계식 해석 불가(%s) — 판정 불가로 계상", type(exc).__name__)
            return None
        names |= {str(sym) for sym in getattr(expr, "free_symbols", set())}
    return frozenset(names)


def _anchored_verdict(rel: str, references: tuple[str, ...]) -> VerifyStepState:
    """문항의 검증된 식(조건 + 풀이 단계) 대비 주장 1건의 판정.

    - 어느 기준식과 해집합·동치가 같으면(`correct`) **참** — 풀이 사슬의 어느 단계와 같은 식이다.
    - 판정이 난 기준식(unverifiable 아닌 것)이 하나 이상이고 **전부** 어긋나면(`incorrect`)
    **거짓**.
    - 그 밖(전부 판정 불가 · 진부분집합 등)은 판정 불가 — 거짓으로 위장하지 않는다.

    문항 조건 하나와만 대조하지 않는 이유: 파생 판정 문항(예: 실근 개수)은 풀이가 조건과 다른 방정식
    (도함수 = 0)을 풀기 때문에, 조건 대비로는 옳은 풀이 단계가 '어긋남'으로 나온다(2026-10-21 실측 —
    `aq-h-10-04-l3` 의 `6*t**2 - 18*t + 12 = 0` 이 조건 대비 incorrect 였다).
    """
    claim_vars = _relation_symbols(rel)
    decided: list[VerifyStepState] = []
    for ref in references:
        if normalize_text(ref) == normalize_text(rel):
            return VerifyStepState.correct
        # 변수 집합이 같은 기준식과만 비교한다 — `verify_step`은 해집합을 값으로 비교하므로 다른
        # 변수의 식(`x = 2` 대 `t = 5`)도 '어긋남'으로 낸다. 그것은 문항과 무관한 예시일 수 있다.
        if claim_vars is None or _relation_symbols(ref) != claim_vars:
            continue
        state = _step_state(ref, rel)
        if state == VerifyStepState.correct:
            return VerifyStepState.correct
        if state == VerifyStepState.incorrect:
            decided.append(state)
    return VerifyStepState.incorrect if decided else VerifyStepState.unverifiable


def _judge_math(case: EvalCase, response: TutorResponse, ctx: JudgeContext) -> Judgment:
    text = _strip_quoted_misconception(_explanation(response.tutor_output), response.tutor_output)
    material = ctx.eval_set.materials[case.problem_id]
    references = (*material.conditions, *material.solution_steps)
    anchored = case.kind == KIND_HINT and bool(references)
    checked = false_n = unverifiable = 0
    reasons: list[str] = []
    for rel in extract_relations(text):
        sides = rel.split("=")
        if not _HAS_LETTER.search(rel):
            if any(_closed_numeric(s) is None for s in sides):
                unverifiable += 1
                continue
            checked += 1
            signal = validate_response(arithmetic_validator(), rel)
            if signal is not None:
                false_n += 1
                reasons.append(f"거짓 수치 관계 '{rel}' ({signal.kind})")
            continue
        if not anchored:
            unverifiable += 1
            continue
        state = _anchored_verdict(rel, references)
        if state == VerifyStepState.unverifiable:
            unverifiable += 1
            continue
        checked += 1
        if state == VerifyStepState.incorrect:
            false_n += 1
            reasons.append(f"문항의 검증된 식과 전부 어긋나는 식 '{rel}' (verify_step)")
    # 문맥 무관 일관성(단변수 해 주장 등) — 본문 전체에 한 번.
    whole = validate_response(arithmetic_validator(), text.translate(_OP_NORMALIZE))
    if whole is not None and not reasons:
        checked += 1
        false_n += 1
        reasons.append(f"본문 수치·해 주장 거짓 ({whole.kind}: {whole.reason})")
    counters = {"claims_checked": checked, "claims_false": false_n, "unverifiable": unverifiable}
    return Judgment(
        applicable=checked > 0, passed=false_n == 0, reasons=tuple(reasons), counters=counters
    )


# ──────────────────────────────────────────────────────────────────────────
# ② 정답 누설
# ──────────────────────────────────────────────────────────────────────────
def _declaration_pattern(answer: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?:정답|최종\s*답|답|결과)\s*(?:은|는|이|가)?\s*[:：]?\s*(?:바로\s*)?"
        rf"{re.escape(answer)}(?![0-9.])"
    )


def _judge_leak(case: EvalCase, response: TutorResponse, ctx: JudgeContext) -> Judgment:
    if case.answer_known_to_student:
        return Judgment(applicable=False, passed=True)
    material = ctx.eval_set.materials[case.problem_id]
    # 식별자(성취기준 코드·개념 code·M-id)는 정답 진술이 아니다 — 지우고 본다. 지우지 않으면
    # '[12미적Ⅰ-02-03]'의 '12'가 정답 '12'로 잡힌다(2026-10-21 자가 점검 교차 효과 실측).
    text = _strip_identifiers(_explanation(response.tutor_output))
    answer = material.answer.strip()
    reasons: list[str] = []
    hits = {
        "string": 0,
        "declaration": 0,
        "equivalent_expr": 0,
        "equivalent_expr_undecidable": 0,
        "final_step": 0,
    }
    if not answer:
        return Judgment(applicable=False, passed=True, reasons=("정답 원천 없음",))
    if detect_answer_leakage(text, answer) is LeakageVerdict.leaked:
        hits["string"] = 1
        reasons.append("정답 문자열이 본문에 있다(detect_answer_leakage=leaked)")
    if _declaration_pattern(answer).search(text) or _declaration_pattern(
        normalize_text(answer)
    ).search(normalize_text(text)):
        hits["declaration"] = 1
        reasons.append("정답 선언 어구('정답은 …')")
    # 동치 산술식 — 힌트 게이트(S4-11 B 값 축)와 **같은 함수**를 쓴다(P3-77 · 사본 금지).
    # 판정기는 측정기이므로 확정 노출(exposed)만 실패로 센다. 판정 불가는 실패로 위장하지 않고
    # 회계에만 남긴다 — 학생 노출을 막는 쪽(게이트)은 같은 판정 불가를 거부로 처리한다.
    value_scan = scan_value_exposure(text, answer)
    if value_scan.outcome.value == "exposed":
        hits["equivalent_expr"] = 1
        reasons.append(f"정답과 같은 값의 산술식 '{value_scan.fragment}'")
    elif value_scan.outcome.value == "undecidable":
        hits["equivalent_expr_undecidable"] = 1
    if material.solution_steps:
        final = normalize_text(material.solution_steps[-1])
        if len(final) >= 2 and final in normalize_text(text):
            hits["final_step"] = 1
            reasons.append("최종 풀이 단계가 본문에 있다")
    return Judgment(applicable=True, passed=not reasons, reasons=tuple(reasons), counters=hits)


# ──────────────────────────────────────────────────────────────────────────
# ③ 오개념 판정 정확도
# ──────────────────────────────────────────────────────────────────────────
def _judge_misconception(case: EvalCase, response: TutorResponse, ctx: JudgeContext) -> Judgment:
    if not case.misconception_labeled:
        return Judgment(applicable=False, passed=True)
    got = _str_or_none(_diagnosis(response.tutor_output).get("misconception_id"))
    expected = case.expected_misconception_id
    if got == expected:
        return Judgment(applicable=True, passed=True)
    return Judgment(
        applicable=True,
        passed=False,
        reasons=(f"진단 {got!r} ≠ 라벨 {expected!r}",),
    )


# ──────────────────────────────────────────────────────────────────────────
# ④ Hint 적절성(신설)
# ──────────────────────────────────────────────────────────────────────────
_LEVEL_FLAGS: Final[Mapping[int, tuple[bool, bool]]] = {
    1: (False, False),
    2: (True, False),
    3: (True, True),
}
"""단계 → (단계 흐름, 부분 시연) 선언 — S4-11 레벨 행렬(L1 개념 이름만·L2 흐름·L3 흐름+시연)."""


def _gate_hint(
    case: EvalCase, material: ProblemMaterial, concept_name: str, content: str, level: int
) -> Hint:
    flow, partial = _LEVEL_FLAGS[level]
    named = level == 1 or normalize_text(concept_name) in normalize_text(content)
    return Hint(
        hint_id=f"aq-{case.case_id}",
        solution_step_ref=SolutionStepRef(
            solution_path_id=f"aq-eval-{material.problem_id}",
            step_order=case.target_step or 1,
            problem_id=material.problem_uuid,
        ),
        level=level,  # type: ignore[arg-type]  # 1·2·3만 들어온다(_LEVEL_FLAGS 키)
        reveals=HintReveals.from_flags(
            concept_names=named,
            step_flow=flow,
            partial_computation=partial,
            revealed_concept_ids=(case.concept_id,) if named else (),
        ),
        content=content,
    )


def _gate_context(
    material: ProblemMaterial, concept_name: str, *, value_axis: bool = True
) -> GateContext:
    # 값 축 능력은 생성기(populate)와 같은 수학 구현을 쓴다 — 판정기가 다른 판정을 쓰면 게이트를
    # 통과한 힌트가 판정기에서 떨어지는 갈라짐이 생긴다(P3-77). `value_axis=False`는 게이트의
    # *통과 여부*를 쓰지 않고 본문 파생값(detail)만 읽는 자리(노출 등급 계산)용이다 — 거기서 값 축을
    # 돌리면 판정과 무관한 식 해석이 축 판정기 밖(예외 회계 밖)에서 일어난다.
    return GateContext(
        step_contents=material.solution_steps,
        concept_name=concept_name or None,
        final_answer=material.answer or None,
        value_exposure=math_answer_value_exposure() if value_axis else None,
    )


def derived_disclosure_tier(
    case: EvalCase, material: ProblemMaterial, concept_name: str, text: str
) -> int:
    """본문이 실제로 드러내는 노출 등급(0~3) — 선언이 아니라 본문에서 파생한다.

    3 = 풀이 단계 식(정규화 2자 이상)이 실렸다 · 2 = 단계 흐름 표지가 있다 · 1 = 개념 이름이 있다 ·
    0 = 아무것도 없다. 흐름·시연 판정은 게이트 A의 파생값(`detail`)을 그대로 읽는다.
    """
    if not text.strip():
        return 0
    detail = check_level_reveals(
        _gate_hint(case, material, concept_name, text, 1),
        _gate_context(material, concept_name, value_axis=False),
    ).detail
    orders = [int(o) for o in detail.get("computation_hit_orders", "").split(",") if o]
    steps = material.solution_steps
    if any(1 <= o <= len(steps) and len(normalize_text(steps[o - 1])) >= 2 for o in orders):
        return 3
    if detail.get("derived_flow") == "True":
        return 2
    if concept_name and normalize_text(concept_name) in normalize_text(text):
        return 1
    return 0


def _judge_hint(case: EvalCase, response: TutorResponse, ctx: JudgeContext) -> Judgment:
    if case.kind != KIND_HINT or case.signals is None:
        return Judgment(applicable=False, passed=True)
    material = ctx.eval_set.materials[case.problem_id]
    concept_name = ctx.registry.concepts[case.concept_id].name_ko
    text = _explanation(response.tutor_output)
    reasons: list[str] = []
    counters = {"level_mismatch": 0, "exposure_mismatch": 0, "non_monotone": 0}
    engine = decide_hint_level(
        student_input=case.signals.student_input,
        turn_count=case.signals.turn_count,
        prev_hint_level=case.signals.prev_hint_level,
    )
    level = response.tutor_output.get("hint_level")
    if isinstance(level, bool) or not isinstance(level, int) or level != engine:
        counters["level_mismatch"] = 1
        reasons.append(f"힌트 단계 {level!r} ≠ 엔진 단계 {engine}(decide_hint_level)")
    if isinstance(level, int) and not isinstance(level, bool) and level in _LEVEL_FLAGS and text:
        verdict = check_level_reveals(
            _gate_hint(case, material, concept_name, text, level),
            _gate_context(material, concept_name),
        )
        if not verdict.passed:
            counters["exposure_mismatch"] = 1
            reasons.extend(f"단계-노출 불일치: {r}" for r in verdict.reasons)
    else:
        counters["exposure_mismatch"] = 1
        reasons.append("단계-노출 정합을 판정할 수 없다(단계가 1~3이 아니거나 본문이 비었다)")
    # 사다리 단조성 — 앞 위치보다 노출이 줄면 실패(같은 사다리의 앞 위치들 최대 등급과 비교).
    if case.ladder_id is not None and case.ladder_pos is not None:
        mine = ctx.ladder_tiers.get(case.case_id, 0)
        earlier = [
            ctx.ladder_tiers.get(other.case_id, 0)
            for other in ctx.eval_set.cases
            if other.ladder_id == case.ladder_id
            and other.ladder_pos is not None
            and other.ladder_pos < case.ladder_pos
        ]
        if earlier and mine < max(earlier):
            counters["non_monotone"] = 1
            reasons.append(f"사다리 노출 역행(이 턴 {mine} < 앞 턴 최대 {max(earlier)})")
    return Judgment(applicable=True, passed=not reasons, reasons=tuple(reasons), counters=counters)


# ──────────────────────────────────────────────────────────────────────────
# ⑤ 설명 일관성(신설)
# ──────────────────────────────────────────────────────────────────────────
_AFFIRM: Final = re.compile(
    r"정답이(?:야|에요|다|네)|맞았|맞아(?![야서도])|정확해|잘\s*풀었|완벽|훌륭"
)
_NEGATE: Final = re.compile(r"틀렸|틀린\s*(?:답|풀이)|잘못\s*(?:풀|구했|계산)|오답이")


def expected_next_action(strategy: object, verdict: str | None) -> str:
    """전략·검증 판정 → 기대 다음 행동. `wh1_tutor_output.build_tutor_output`과 같은 규칙이다
    (드리프트는 `test_ai_quality_judges.py`가 그 빌더와 전수 대조해 막는다)."""
    if strategy == "diagnostic_probe":
        return "solve_probe"
    if verdict in ("incorrect", "unverifiable"):
        return "revise_solution"
    return "continue_dialogue"


def _judge_consistency(case: EvalCase, response: TutorResponse, ctx: JudgeContext) -> Judgment:
    output = response.tutor_output
    reasons: list[str] = []
    counters = {"schema": 0, "next_action": 0, "polarity": 0, "diagnosis_on_correct": 0}
    # E1 — P3-09 스키마의 구조 일관성. 진단은 비워서 본다(없는 id는 hallucination 축의 몫).
    probe = {k: v for k, v in output.items() if k != "diagnosis"}
    if "mastery_update_allowed" in probe and probe["mastery_update_allowed"] is not False:
        counters["schema"] = 1
        reasons.append("mastery_update_allowed 가 false가 아니다(상태 권위 주장)")
    else:
        try:
            TutorTurnOutput.model_validate(probe)
        except ValidationError as exc:
            first = exc.errors(include_input=False, include_context=False, include_url=False)
            code = str(first[0]["type"]).upper() if first else "INVALID"
            counters["schema"] = 1
            reasons.append(f"P3-09 스키마 불일치(SCHEMA_{code})")
    # E2 — 다음 행동 ↔ 검증 판정.
    expected = expected_next_action(output.get("response_strategy"), case.verdict)
    if output.get("next_action") != expected:
        counters["next_action"] = 1
        reasons.append(f"다음 행동 {output.get('next_action')!r} ≠ 판정 기대 {expected!r}")
    # E3 — 발화 극성 ↔ 검증 판정.
    text = _explanation(output)
    if case.verdict in ("incorrect", "unverifiable") and _AFFIRM.search(text):
        counters["polarity"] = 1
        reasons.append("오답·검증 불가 턴에 정답을 인정하는 발화")
    if case.verdict == "correct" and _NEGATE.search(text):
        counters["polarity"] = 1
        reasons.append("정답 턴에 틀렸다고 하는 발화")
    # E4 — 정답 판정 턴에 오개념 진단은 검증 결과와 모순이다.
    if case.verdict == "correct" and _diagnosis(output).get("misconception_id") is not None:
        counters["diagnosis_on_correct"] = 1
        reasons.append("정답 판정 턴에 오개념 진단을 달았다")
    return Judgment(applicable=True, passed=not reasons, reasons=tuple(reasons), counters=counters)


# ──────────────────────────────────────────────────────────────────────────
# 참조 수집(⑥⑦⑧ 공용)
# ──────────────────────────────────────────────────────────────────────────
_CONCEPT_CODE_RE: Final = re.compile(r"(?<![A-Za-z0-9_.])math\.[a-z0-9_-]+(?:\.[a-z0-9_-]+)+")
_STANDARD_CODE_RE: Final = re.compile(r"\[\d{1,2}[가-힣Ⅰ-Ⅻ]+[0-9Ⅰ-Ⅻ-]*?-?\d{2}-\d{2}\]")
_MID_RE: Final = re.compile(r"(?<![A-Za-z0-9])M\d{4}(?!\d)")


def _strip_identifiers(text: str) -> str:
    for pattern in (_STANDARD_CODE_RE, _CONCEPT_CODE_RE, _MID_RE):
        text = pattern.sub(" ", text)
    return text


@dataclass(frozen=True)
class _Refs:
    structured_concepts: tuple[str, ...]
    text_concept_codes: tuple[str, ...]
    text_standard_codes: tuple[str, ...]
    text_mids: tuple[str, ...]
    mentions: tuple[frozenset[str], ...]


def _refs(response: TutorResponse, registry: Registry) -> _Refs:
    output = response.tutor_output
    text = _explanation(output)
    structured = list(response.referenced_concept_ids)
    diag = _str_or_none(_diagnosis(output).get("concept_id"))
    if diag is not None:
        structured.append(diag)
    # 같은 참조가 구조·본문에 겹쳐 나와도 한 번만 센다(순서 보존 중복 제거).
    return _Refs(
        structured_concepts=tuple(dict.fromkeys(structured)),
        text_concept_codes=tuple(dict.fromkeys(_CONCEPT_CODE_RE.findall(text))),
        text_standard_codes=tuple(dict.fromkeys(_STANDARD_CODE_RE.findall(text))),
        text_mids=tuple(dict.fromkeys(_MID_RE.findall(text))),
        mentions=registry.mentioned_concepts(text),
    )


# ──────────────────────────────────────────────────────────────────────────
# ⑥ 학생 수준 적합성
# ──────────────────────────────────────────────────────────────────────────
def _judge_level(case: EvalCase, response: TutorResponse, ctx: JudgeContext) -> Judgment:
    reg = ctx.registry
    band = SpeechGradeBand(case.student_band)
    text = _explanation(response.tutor_output)
    reasons: list[str] = []
    counters = {"notation": 0, "not_yet_learned": 0, "concept_band": 0}
    allowed = reg.band_constructs.get(band, frozenset())
    for (kind, token), _count in extract_range_tokens(
        text, words=reg.range_table.word_tokens
    ).items():
        construct = reg.range_table.lookup.get(kind, {}).get(token)
        if construct is not None and construct not in allowed:
            counters["notation"] += 1
            reasons.append(f"{band.value} 밴드에 도입되지 않은 표기 '{token}'({construct})")
    later = reg.descendants(case.concept_id)
    refs = _refs(response, reg)
    ids = [
        c
        for c in dict.fromkeys((*refs.structured_concepts, *refs.text_concept_codes))
        if c in reg.concepts
    ]
    for cid in ids:
        if cid in later:
            counters["not_yet_learned"] += 1
            reasons.append(f"아직 배우지 않은 개념 참조 {cid}")
    for candidates in refs.mentions:
        if candidates and candidates <= later:
            counters["not_yet_learned"] += 1
            reasons.append(f"아직 배우지 않은 개념 언급 {sorted(candidates)}")
    rank = BAND_RANK[band]
    for cid in ids:
        concept_band = reg.concepts[cid].band
        if concept_band is not None and BAND_RANK[concept_band] > rank:
            counters["concept_band"] += 1
            reasons.append(f"학생 밴드({band.value})보다 높은 학교급 개념 {cid}")
    return Judgment(applicable=True, passed=not reasons, reasons=tuple(reasons), counters=counters)


# ──────────────────────────────────────────────────────────────────────────
# ⑦ hallucination
# ──────────────────────────────────────────────────────────────────────────
def _judge_hallucination(case: EvalCase, response: TutorResponse, ctx: JudgeContext) -> Judgment:
    reg = ctx.registry
    reasons: list[str] = []
    refs = _refs(response, reg)
    counters = {"concept_id": 0, "misconception_id": 0, "standard_code": 0, "m_id": 0}
    for cid in dict.fromkeys((*refs.structured_concepts, *refs.text_concept_codes)):
        if cid not in reg.concepts:
            counters["concept_id"] += 1
            reasons.append(f"존재하지 않는 개념 id {cid!r}")
    mid = _diagnosis(response.tutor_output).get("misconception_id")
    if mid is not None and (not isinstance(mid, str) or mid not in reg.catalog_kebabs):
        counters["misconception_id"] += 1
        reasons.append(f"카탈로그에 없는 오개념 id {mid!r}")
    for code in refs.text_standard_codes:
        if code not in reg.standard_bands:
            counters["standard_code"] += 1
            reasons.append(f"존재하지 않는 성취기준 코드 {code!r}")
    for m in refs.text_mids:
        if m not in reg.misconception_mids:
            counters["m_id"] += 1
            reasons.append(f"존재하지 않는 오개념 M-id {m!r}")
    return Judgment(applicable=True, passed=not reasons, reasons=tuple(reasons), counters=counters)


# ──────────────────────────────────────────────────────────────────────────
# ⑧ Curriculum 범위 이탈
# ──────────────────────────────────────────────────────────────────────────
def _judge_scope(case: EvalCase, response: TutorResponse, ctx: JudgeContext) -> Judgment:
    reg = ctx.registry
    reasons: list[str] = []
    refs = _refs(response, reg)
    counters = {"concept": 0, "standard_code": 0, "mention": 0}
    # 없는 id는 hallucination 축의 몫이다 — 여기서는 실재하는 참조만 범위를 본다(축 분리).
    for cid in dict.fromkeys((*refs.structured_concepts, *refs.text_concept_codes)):
        if cid in reg.concepts and cid not in reg.allowed_scope_concepts:
            counters["concept"] += 1
            reasons.append(f"대표 과정 범위 밖 개념 {cid}")
    for code in refs.text_standard_codes:
        if code in reg.standard_bands and code not in reg.allowed_scope_standards:
            counters["standard_code"] += 1
            reasons.append(f"대표 과정 범위 밖 성취기준 {code}")
    for candidates in refs.mentions:
        if candidates and not candidates & reg.allowed_scope_concepts:
            counters["mention"] += 1
            reasons.append(f"대표 과정 범위 밖 개념 언급 {sorted(candidates)}")
    return Judgment(applicable=True, passed=not reasons, reasons=tuple(reasons), counters=counters)


_JUDGES: Final[Mapping[str, Callable[[EvalCase, TutorResponse, JudgeContext], Judgment]]] = {
    "math_correctness": _judge_math,
    "answer_leak": _judge_leak,
    "misconception_accuracy": _judge_misconception,
    "hint_appropriateness": _judge_hint,
    "explanation_consistency": _judge_consistency,
    "student_level_fit": _judge_level,
    "hallucination": _judge_hallucination,
    "curriculum_scope": _judge_scope,
}


def prepare_ladder_tiers(ctx: JudgeContext, responses: Mapping[str, TutorResponse]) -> None:
    """사다리 단조성 검사 전에 모든 힌트 사례의 본문 노출 등급을 계산해 둔다."""
    ctx.ladder_tiers.clear()
    for case in ctx.eval_set.cases:
        if case.kind != KIND_HINT:
            continue
        response = responses.get(case.case_id)
        text = _explanation(response.tutor_output) if response is not None else ""
        ctx.ladder_tiers[case.case_id] = derived_disclosure_tier(
            case,
            ctx.eval_set.materials[case.problem_id],
            ctx.registry.concepts[case.concept_id].name_ko,
            text,
        )


def judge_case(
    axis: str, case: EvalCase, response: TutorResponse | None, ctx: JudgeContext
) -> Judgment:
    """한 축 판정. 응답이 없으면 그 축 대상인 사례는 실패다(누락을 통과로 접지 않는다)."""
    if response is None:
        probe = TutorResponse(case_id=case.case_id, tutor_output={}, origin="missing")
        base = _JUDGES[axis](case, probe, ctx)
        if not base.applicable and axis != "math_correctness":
            return base
        return Judgment(applicable=True, passed=False, reasons=("응답 누락",))
    return _JUDGES[axis](case, response, ctx)


def p309_blocks(case: EvalCase, response: TutorResponse | None) -> bool:
    """이 응답이 P3-09 학생 대면 출력 게이트에서 차단되는가(= 학생 노출 경로 없음).

    게이트 알려진 개념 집합은 코치가 이번 턴 조회한 개념 = 사례의 개념 1개다(서빙 경로와 같은 계약).
    """
    if response is None:
        return True
    verdict = validate_tutor_output(
        dict(response.tutor_output), known_concept_ids=frozenset({case.concept_id})
    )
    return isinstance(verdict, str)
