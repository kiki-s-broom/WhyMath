"""자체생성 동등문제 *수용 게이트* — S2-a(순수·결정론·DB 0·LLM 0).

설계 정본: `docs/architecture/03_content_generation.md` §"개념 시퀀스 동치성 판정 —
휴리스틱 + 사람 검수 병행". 핵심 명제: **동등성은 미해결 연구 난제**이므로 스코어러는
*확정이 아니라 분류*만 한다("휴리스틱으로 좁히고 사람이 닫는다"). 따라서 본 게이트는 두
등급(`동치후보`·`비동치후보`)과 *사람 검수 큐*로 보낼 중간 등급(`검수필요`)만 낸다.

이 게이트는 자체생성 동등문제(평가원·교과서 본문 복제 없이 성취기준·오개념·난이도를 대응)가
코퍼스에 *저장되기 전에* 통과해야 하는 4종 게이트를 결정론으로 조합한다:

  1. **저작권 게이트**(`copyright_ok`) — provenance/Problem 생성 시 Pydantic 불변식이 이미
     A/B/C를 강제하므로(`schema/provenance.py`·`schema/problem.py`) 여기선 *값 확인*만 한다
     (재구현 0). generation_type이 변형/생성류이고 license가 WHYMATH_GENERATED이며
     source_type이 자체생성인지 확인한다.
  2. **정확성 게이트**(`verification`) — Tier1 답 검산(`l3/verify_answer`) + (있으면) Tier2
     단계 판정(`l3/verify_solution.verify_solution_interpreted` — 이웃 동치 + 해석 단계(근
     선택·대입)의 조건 판정, P3-76)을 *직접 조합*한다. whs/verdict의 결합 규칙을 미러하되
     l3→whs 역참조를 피하려고 두 검증기를 직접 부른다(계층 규칙).
  3. **위생 게이트**(`hygiene_ok`) — 후보 본문(해설·발문)에 거짓 수치 등식 등 슬립이 있는지
     `l3/pregenerate/validator`의 시드 검증기로 본다(신호 None=통과).
  4. **동등성 분류**(`equivalence`·`equivalence_score`) — 성취기준·오개념·난이도·답 형태 4성분을
     가중 평균해 점수를 내고 임계값으로 3등급 분류한다(확정 아님).

정직성(CLAUDE.md "확실하지 않으면 모른다"·"조용한 실패 금지"): 정확성 판정 불가·중간 점수는
`검수필요`로 사람 큐에 보낸다. 최종 `accepted`는 4종이 *모두* 깨끗할 때만 True다. 모든 거부/검수
사유는 `reasons`에 정직히 기록한다(학생 비노출·감사/운영용).

범위 메모(S2-a): *수용 게이트*만이다. 동등문제 *생성부*(LLM 호출·프롬프트)는 후속 슬라이스다.
사람 검수 큐 *결선*·임계값 점진 보정(검수 누적→임계값 학습)도 후속(§03 로드맵).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from whymath_backend.l3.equivalent.latex_gate import validate_problem_latex
from whymath_backend.l3.equivalent.retag import TagAuditor
from whymath_backend.l3.finite_probability import (
    verify_finite_count,
    verify_finite_probability,
)
from whymath_backend.l3.pregenerate.validator import (
    SeedValidator,
    default_seed_validator,
    validate_response,
)
from whymath_backend.l3.verify_answer import (
    AnswerVerdict,
    classify_solvability,
    verify_answer,
    verify_conditional_equal,
    verify_congruent_by_ratio,
    verify_dot_product_scalar,
    verify_events_independent,
    verify_extremum_count,
    verify_geometric_convergence,
    verify_inequality_direction,
    verify_is_differentiable,
    verify_is_one_to_one,
    verify_limit_equals_value,
    verify_mean_equals_median,
    verify_real_root_count,
    verify_root_aggregate,
    verify_root_selection,
    verify_series_converges,
)
from whymath_backend.l3.verify_solution import verify_solution_interpreted
from whymath_backend.schema.enums import (
    AnswerFormat,
    GenerationType,
    LicenseType,
    SourceType,
    StepType,
)
from whymath_backend.schema.problem import Problem
from whymath_backend.schema.provenance import (
    _TRANSFORMED_GENERATION_TYPES,
    ContentProvenance,
)

__all__ = [
    "AcceptanceVerdict",
    "EquivalenceSpec",
    "EquivalenceVerdict",
    "evaluate_equivalent_candidate",
]


# ──────────────────────────────────────────────────────────────────────────
# 동등성 스코어 가중치·임계값 — 코드 상수(문서화). 합=1.0.
# 성취기준을 최상위 축으로(같은 성취기준을 다루는가), 오개념·난이도·답형태 순.
# ──────────────────────────────────────────────────────────────────────────
_W_STANDARD = 0.40
_W_MISCONCEPTION = 0.30
_W_DIFFICULTY = 0.20
_W_ANSWER_FORMAT = 0.10

# 난이도 초과분 선형 감쇠 스케일 — 난이도는 1~5 척도라 최대 격차가 4.0.
_DIFFICULTY_DECAY_SCALE = 4.0

# 동등성 분류 임계값 — HIGH 이상 동치후보·LOW 미만 비동치후보·그 사이(또는 정확성
# 미검증) 검수필요. §03 "경계 구간은 반드시 사람 검수 큐"의 코드화.
_EQUIVALENCE_HIGH = 0.85
_EQUIVALENCE_LOW = 0.50

# 저작권 게이트가 허용하는 generation_type(변형/생성류 ∪ FULLY_GENERATED). FULLY_GENERATED는
# 이미 _TRANSFORMED_GENERATION_TYPES에 포함되나, 계약을 자기설명적으로 두려고 명시 union 한다.
_ACCEPTED_GENERATION_TYPES: frozenset[GenerationType] = frozenset(
    _TRANSFORMED_GENERATION_TYPES | {GenerationType.FULLY_GENERATED}
)
# use_enum_values=True 환경(provenance)이라 값이 문자열일 수 있어 *문자열 값 집합*으로 비교한다.
_ACCEPTED_GENERATION_VALUES: frozenset[str] = frozenset(
    str(g.value) for g in _ACCEPTED_GENERATION_TYPES
)

# 개념형 검증기 디스패치 — answer_kind → SymPy 독립 검증 프리미티브. 답이 값이 아니라 개수/판정인
# 문항(실근·극값 개수·일대일·등비급수 수렴)을 게이트가 이 표로 분기해 검증한다(축 확장은 여기 등록).
_CONCEPTUAL_VERIFIERS: dict[str, Callable[[str | Sequence[str], str], AnswerVerdict]] = {
    "real_root_count": verify_real_root_count,
    "extremum_count": verify_extremum_count,
    "is_one_to_one": verify_is_one_to_one,
    "geometric_convergence": verify_geometric_convergence,
    "limit_equals_value": verify_limit_equals_value,
    "is_differentiable": verify_is_differentiable,
    "series_converges": verify_series_converges,
    # division-by-zero: 정의역 제외점(분모=0 실근) 개수 — 근 개수 검증기를 그대로 재사용.
    "excluded_point_count": verify_real_root_count,
    # Tier C 계산가능(통계·확률·기하·벡터 판정) — 도메인 프리미티브로 결정론 검증.
    "mean_equals_median": verify_mean_equals_median,
    "events_independent": verify_events_independent,
    "conditional_equal": verify_conditional_equal,
    "congruent_by_ratio": verify_congruent_by_ratio,
    "dot_product_scalar": verify_dot_product_scalar,
    "inequality_direction": verify_inequality_direction,
    # root-loss-by-dividing: ax²=bx 양변 x 나눗셈 근 손실 — 근 개수(정답 2·손실 1) 검증기 재사용.
    "root_loss_count": verify_real_root_count,
    # S4-13 ① SymPy 불가 영역의 *기계 가능 부분* — 유한 표본공간을 **전수 열거**해 정확
    # 유리수로 검산한다(난수 표본이 아니라 전수라 그 형식 모델 위에서는 증명). 기계 불가
    # 잔여(발문↔형식모델 정합)는 `cross_verify` + Wilson 표본 검수 게이트가 로트로 본다.
    "finite_probability": verify_finite_probability,
    "finite_count": verify_finite_count,
}


# ──────────────────────────────────────────────────────────────────────────
# 타입
# ──────────────────────────────────────────────────────────────────────────
class EquivalenceSpec(BaseModel):
    """원본이 요구하는 *대응 명세* — 동등문제가 맞춰야 할 성취기준·오개념·난이도·답형태.

    스코어러는 후보(`Problem`)의 대응 필드를 이 명세와 비교해 동등성 점수를 낸다. 빈 frozenset은
    "요구 없음"(= 그 축은 만점)으로 해석한다 — 부분 명세를 허용한다(원본이 특정 오개념을 겨냥하지
    않을 수 있음). L3-지역 타입이다(schema는 l3를 import하지 않는 계층 규칙을 지키려 여기 둔다).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    achievement_standard_codes: frozenset[str] = Field(
        default_factory=frozenset,
        description="원본이 다루는 성취기준 고시코드 집합(빈 집합=요구 없음·만점).",
    )
    target_misconception_ids: frozenset[str] = Field(
        default_factory=frozenset,
        description=(
            "원본이 겨냥한 오개념 id 집합. 후보 distractor 오개념 집합과 Jaccard로 비교한다 "
            "— 둘 다 비면 1.0(요구·보유 모두 없음)이나, 빈 spec에 후보가 오개념을 도입하면 "
            "0.0(겨냥 밖 오개념)."
        ),
    )
    difficulty_overall: float = Field(
        ...,
        ge=1.0,
        le=5.0,
        description="원본 종합 난이도 1.0~5.0.",
    )
    answer_format: AnswerFormat | None = Field(
        default=None,
        description="원본 정답 형식(None=제약 없음·만점).",
    )


# 동등성 3등급 — 확정이 아니라 *분류*. `검수필요`는 사람 검수 큐로(§03 정본).
EquivalenceVerdict = Literal["동치후보", "비동치후보", "검수필요"]


class AcceptanceVerdict(BaseModel):
    """수용 게이트 결과 — 4종 게이트 신호 + 최종 accepted + 사유(학생 비노출).

    `accepted`는 copyright_ok·verification=="verified"·hygiene_ok·equivalence=="동치후보"가
    *모두* 참일 때만 True다. 그 외(검수필요·비동치·실패)는 사람 큐 또는 거부다. `reasons`는
    사람이 읽는 거부/검수 사유(감사·운영용)이며 학생에게 노출하지 않는다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    accepted: bool = Field(description="게이트 모두 통과 시에만 True(코퍼스 저장 허용).")
    equivalence: EquivalenceVerdict = Field(description="동등성 분류(3등급).")
    equivalence_score: float = Field(ge=0.0, le=1.0, description="동등성 가중 점수 0~1.")
    copyright_ok: bool = Field(description="저작권 게이트 — 값 확인 통과 여부.")
    verification: Literal["verified", "failed", "unverified"] = Field(
        description="정확성 게이트 — Tier1+Tier2 결합 판정.",
    )
    hygiene_ok: bool = Field(description="위생 게이트 — 본문 슬립 검출 없음 여부.")
    consistency_ok: bool = Field(
        default=True,
        description=(
            "발문-수식 정합 감사(초인간 검증 S3·독립 주체) — 감사기 미주입 시 True(기존 동작 "
            "비트동일). 발문의 수식/선택 문구가 검산 조건과 확정적으로 어긋나면만 False."
        ),
    )
    latex_ok: bool = Field(
        default=True,
        description=(
            "LaTeX/문법 게이트(품질 15축 ⑩·ARCH-19) — 발문·해설·선택지의 $ /중괄호/"
            "\\left\\right 구조 정합(결정론 파스). 깨진 표기(렌더 불가) 검출 시 False."
        ),
    )
    reasons: list[str] = Field(
        default_factory=list,
        description="거부/검수 사유(사람 가독·학생 비노출·조용한 실패 금지).",
    )


# ──────────────────────────────────────────────────────────────────────────
# 내부 헬퍼
# ──────────────────────────────────────────────────────────────────────────
def _enum_str(value: Enum | str | None) -> str | None:
    """enum/문자열/None을 *문자열 값*으로 정규화(use_enum_values=True 대응).

    provenance·Problem은 use_enum_values=True라 런타임 필드가 문자열일 수 있으나, 타입 계약은
    enum이다 — 양쪽을 문자열 값으로 접어 비교한다(`problem.py`·`provenance.py` 정규화 패턴).
    """
    if value is None:
        return None
    if isinstance(value, Enum):
        return str(value.value)
    return value


def _evaluate_copyright(
    candidate: Problem,
    provenance: ContentProvenance,
) -> tuple[bool, list[str]]:
    """저작권 게이트 — 값 확인만(재구현 0). 불변식은 이미 생성 시 강제됐다.

    ContentProvenance·Problem 생성 시 Pydantic 불변식이 A/B/C(원본 그대로 금지·본문 미보유·
    지배 license 강제)를 이미 던진다. 여기선 그 *값*이 동등문제 수용 조건에 맞는지 확인한다:
    generation_type ∈ 변형/생성류, license == WHYMATH_GENERATED, source_type == 자체생성.
    """
    reasons: list[str] = []
    gen = _enum_str(provenance.generation_type)
    lic = _enum_str(provenance.license)
    src = _enum_str(candidate.source_type)

    ok = True
    if gen not in _ACCEPTED_GENERATION_VALUES:
        ok = False
        reasons.append(f"저작권 게이트 — generation_type={gen!r}가 변형/생성류가 아님.")
    if lic != LicenseType.WHYMATH_GENERATED.value:
        ok = False
        reasons.append(f"저작권 게이트 — license={lic!r}가 WHYMATH_GENERATED가 아님.")
    if src != SourceType.자체생성.value:
        ok = False
        reasons.append(f"저작권 게이트 — source_type={src!r}가 자체생성이 아님.")
    return ok, reasons


def _evaluate_verification(
    conditions: str | Sequence[str],
    answer_map: Mapping[str, str],
    solution_steps: Sequence[str] | None,
    solution_step_types: Sequence[StepType | None] | None,
    answer_selection: str | None,
    answer_aggregate: str | None = None,
    claimed_answer: str | None = None,
    answer_kind: str | None = None,
) -> tuple[Literal["verified", "failed", "unverified"], list[str]]:
    """정확성 게이트 — 존재성/유일성 + Tier1(답 검산) + (있으면) Tier2(단계 동치) + 근 선택(S2-i).

    존재성/유일성 축(문항 품질 ②③·`classify_solvability`): 답 검산 이전에 방정식 *자체*가 성립
    문제인지 본다 — 항등식(무한해)·해 없음이면 어떤 답을 줘도 malformed이라 **failed**(명시 사유).
    이 축이 없으면 항등식이 Tier1 pass + unique 프로브 unverifiable로 verified 통과하는 구멍이 있다.

    Tier2 단계 판정(P3-76): 이웃 동치(`verify_solution`)에 더해, 동치가 아닌 해석 단계(근 선택
    `x = -3, x = 4 → x = 4`·대입 `x = 4 → y = -202`)를 문항 조건으로 판정한다 — Solution QA C4·
    야간 재검증과 같은 공용 구현(`verify_solution_interpreted`). 허용 목록 다항 증명이 성립하면
    그 전이는 correct, 조건과 어긋남이 확정이면 incorrect, 판정 불가면 이웃 동치 판정 그대로다
    (incorrect 였던 전이는 증명될 때만 바뀐다 — 판정 확장이지 기준 완화가 아니다).

    Tier1/Tier2 결합 규칙(whs/verdict §4 미러·l3→whs 역참조 회피):
      - **failed**: Tier1 fail *또는* 단계 has_incorrect=True(틀린 과정은 답 무관 차단).
      - **verified**: Tier1 pass *그리고* (단계 없음 OR has_incorrect=False·n_unverifiable=0·
        n_correct≥1). 결정론적으로 전부 검증되고 답도 통과한 경우만.
      - **unverified**: 그 외(Tier1 판정 불가·일부 단계 미검증·단 incorrect 없음). 격리 등급.

    근 선택(S2-i·`verify_root_selection`): "큰 근/작은 근/유일" 문제는 *방정식만으론 답이 유일하게
    정해지지 않아* Tier1이 **틀린 근도 통과**시킨다(Phaiakes9 실측: 큰 근 요구에 작은 근 -4도 pass).
    따라서 Tier1/Tier2 결합 뒤 선택을 추가로 판정한다:
      - `answer_selection`이 명시됨(largest/smallest/unique):
        · 선택 위반이 확정되면(틀린 근) → **failed**(오답을 verified로 통과시키지 않음).
        · 선택 확인 불가(풀 수 없음 등)면 verified를 → **unverified**로 강등(확신 없으면 단정 금지).
      - `answer_selection`이 없음 + Tier1 verified: 다근 방정식이면 답이 유일하게 확정되지 않으므로
        (선택 미declared) verified를 → **unverified**로 강등(needs_review). 틀린 근을 조용히
        통과시키는 구멍 차단. 단근·파라미터·연립 등 유일성 판정 밖은 그대로 둔다(회귀 0).
    """
    reasons: list[str] = []

    # ★ S2 킬러 — 근 집계(합/곱) 문항: 답이 f=0의 근이 아니라 근들의 집계값이라 Tier1
    #    (답이 근인가) 경로가 부적합하다. verify_root_aggregate로 분기해 판정하고 즉시 반환.
    if answer_aggregate in ("sum", "product"):
        if claimed_answer is None:
            reasons.append("정확성 미검증 — 근 집계 문항인데 주장값(answer) 없음.")
            return "unverified", reasons
        agg = verify_root_aggregate(conditions, claimed_answer, answer_aggregate)  # type: ignore[arg-type]
        if agg.state == "pass":
            return "verified", reasons
        if agg.state == "fail":
            reasons.append(f"정확성 실패 — 근 {answer_aggregate} 불일치: {agg.reason}")
            return "failed", reasons
        reasons.append(f"정확성 미검증 — 근 {answer_aggregate} 확인 불가: {agg.reason}")
        return "unverified", reasons

    # ★ 개념형 문항 — 답이 값이 아니라 개수/판정(실근·극값 개수·일대일·등비급수 수렴)이라 SymPy로
    #    독립 계산해 검증한다. 오개념의 틀린 답(판별식 무시·임계점=극값·역함수 오인·늘 수렴)은
    #    여기서 failed로 걸린다.
    if answer_kind in _CONCEPTUAL_VERIFIERS:
        if claimed_answer is None:
            reasons.append("정확성 미검증 — 개념형 문항인데 주장값(answer) 없음.")
            return "unverified", reasons
        cnt = _CONCEPTUAL_VERIFIERS[answer_kind](conditions, claimed_answer)
        if cnt.state == "pass":
            return "verified", reasons
        if cnt.state == "fail":
            reasons.append(f"정확성 실패 — {answer_kind} 불일치: {cnt.reason}")
            return "failed", reasons
        reasons.append(f"정확성 미검증 — {answer_kind} 확인 불가: {cnt.reason}")
        return "unverified", reasons

    # ★ 존재성·유일성 축(문항 품질 ②③·Kiki #1) — 답과 무관하게 방정식 *자체*가 성립 문제인가.
    #    항등식(무한해)·해 없음은 어떤 답을 줘도 단일 정답 문항으로 malformed → 즉시 failed(명시
    #    사유). 다근(선택 미declared)은 아래 근 선택 강등이 이어받고, unique/undecidable은 통과해
    #    기존 Tier1/Tier2 경로가 판정한다(회귀 0 — 정상 문항은 unique/multiple/undecidable뿐).
    solv = classify_solvability(conditions)
    if solv.state == "identity":
        reasons.append(f"정확성 실패 — 무한해(항등식): {solv.reason}")
        return "failed", reasons
    if solv.state == "no_solution":
        reasons.append(f"정확성 실패 — 해 없음: {solv.reason}")
        return "failed", reasons

    answer_verdict = verify_answer(conditions, answer_map)
    tier1 = answer_verdict.state

    # Tier2 — 이웃 동치 + 해석 단계(근 선택·대입)의 조건 판정(P3-76 · solution_qa C4·야간
    # 재검증과 같은 공용 구현). 해석 단계는 허용 목록 다항 증명이 성립할 때만 통과로 바뀌고,
    # 동치 판정이 incorrect 였던 전이는 증명 불가면 incorrect 그대로다(단조 규칙 — 기준 완화 없음).
    steps_result = (
        verify_solution_interpreted(
            solution_steps,
            solution_step_types,
            conditions=conditions,
            answer_selection=answer_selection,
        ).result
        if solution_steps is not None
        else None
    )

    # ① failed — 답 fail 또는 틀린 과정(단계 incorrect). 답이 맞아도 과정이 틀리면 차단.
    if tier1 == "fail":
        reasons.append(f"정확성 실패 — Tier1 답 검산 fail: {answer_verdict.reason}")
        return "failed", reasons
    if steps_result is not None and steps_result.has_incorrect:
        idx = steps_result.first_incorrect_index
        reasons.append(f"정확성 실패 — Tier2 풀이 단계 {idx}에 incorrect(틀린 과정).")
        return "failed", reasons

    # ② 기저 상태 — Tier1 pass AND (단계 없음 OR 전 단계 correct·미검증 0·correct≥1).
    steps_ok = steps_result is None or (
        not steps_result.has_incorrect
        and steps_result.n_unverifiable == 0
        and steps_result.n_correct >= 1
    )
    if tier1 == "pass" and steps_ok:
        state: Literal["verified", "failed", "unverified"] = "verified"
    else:
        state = "unverified"
        if tier1 != "pass":
            reasons.append(f"정확성 미검증 — Tier1 답 검산 {tier1}: {answer_verdict.reason}")
        elif steps_result is not None:
            reasons.append(
                "정확성 미검증 — Tier2 단계 미검증"
                f"(unverifiable {steps_result.n_unverifiable}·correct {steps_result.n_correct})."
            )

    # ③ 근 선택(S2-i) — Tier1이 확정 못 하는 "어느 근인가"를 판정.
    if answer_selection in ("largest", "smallest", "unique"):
        sel = verify_root_selection(conditions, answer_map, answer_selection)  # type: ignore[arg-type]
        if sel.state == "fail":
            reasons.append(f"정확성 실패 — 근 선택({answer_selection}) 위반: {sel.reason}")
            return "failed", reasons
        if sel.state == "unverifiable" and state == "verified":
            state = "unverified"
            reasons.append(f"정확성 미검증 — 근 선택({answer_selection}) 확인 불가: {sel.reason}")
    elif state == "verified":
        # 선택 미declared + Tier1 통과 → 다근이면 답이 유일 확정 안 됨 → 강등(needs_review).
        probe = verify_root_selection(conditions, answer_map, "unique")
        if probe.state == "fail":
            state = "unverified"
            reasons.append(
                "정확성 미검증 — 답이 여러 실근 중 하나이나 선택(큰 근/작은 근/유일)이 명시되지 "
                f"않아 유일하게 확정되지 않음: {probe.reason}"
            )

    return state, reasons


def _evaluate_hygiene(
    candidate: Problem,
    validator: SeedValidator | None,
) -> tuple[bool, list[str]]:
    """위생 게이트 — 후보 해설·발문에 시드 검증기를 적용(신호 None=통과).

    거짓 수치 등식("3×4=11")·거짓 부등식·틀린 단변수 해 등 결정론으로 반증 가능한 슬립을 거른다
    (`default_seed_validator`). 비어있는 필드는 검사 대상에서 제외한다(부재는 슬립이 아님).
    """
    active = validator if validator is not None else default_seed_validator()
    reasons: list[str] = []
    ok = True
    fields: tuple[tuple[str, str | None], ...] = (
        ("answer_explanation", candidate.answer_explanation),
        ("question_text", candidate.question_text),
    )
    for label, text in fields:
        if not text:
            continue
        signal = validate_response(active, text)
        if signal is not None:
            ok = False
            reasons.append(f"위생 게이트 — {label} {signal.kind}: {signal.reason}")
    return ok, reasons


def _evaluate_latex(candidate: Problem) -> tuple[bool, list[str]]:
    """LaTeX 게이트(품질 15축 ⑩) — 발문·해설·선택지 구조 정합성(결정론 파스, ARCH-19).

    실 코퍼스는 현재 `$`/역슬래시 마크업이 0건(정직한 공백·`latex_gate` 모듈 docstring)이라
    기존 문항 전량 트리비얼하게 통과한다 — 이 게이트는 결함 주입 강등전(합성 데이터)과 향후
    LaTeX 콘텐츠 유입에 대한 선제 방어선이다.
    """
    issues = validate_problem_latex(candidate)
    if not issues:
        return True, []
    return False, [f"LaTeX 게이트 — {issue}" for issue in issues]


def _standard_score(spec_codes: frozenset[str], cand_codes: frozenset[str]) -> float:
    """성취기준 점수 — spec ⊆ cand면 1.0·부분 교집합 비율·공집합이면 0. 빈 spec=만점."""
    if not spec_codes:
        return 1.0
    return len(spec_codes & cand_codes) / len(spec_codes)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """오개념 점수 — 두 집합의 Jaccard. 둘 다 비면 1.0(요구·보유 모두 없음=정합)."""
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def _difficulty_score(cand_diff: float | None, spec_diff: float, tol: float) -> float:
    """난이도 점수 — |격차|≤tol이면 1.0·초과분 선형 감쇠. 후보 난이도 None이면 0(비교 불가)."""
    if cand_diff is None:
        return 0.0
    gap = abs(cand_diff - spec_diff)
    if gap <= tol:
        return 1.0
    return max(0.0, 1.0 - (gap - tol) / _DIFFICULTY_DECAY_SCALE)


def _answer_format_score(spec_af: AnswerFormat | None, cand_af: AnswerFormat | None) -> float:
    """답형태 점수 — spec None(제약 없음) 또는 후보와 일치면 1.0·아니면 0."""
    if spec_af is None:
        return 1.0
    return 1.0 if _enum_str(spec_af) == _enum_str(cand_af) else 0.0


def _classify_equivalence(
    score: float,
    verification: Literal["verified", "failed", "unverified"],
) -> EquivalenceVerdict:
    """동등성 점수 + 정확성 상태 → 3등급. 정확성 미검증 또는 경계 구간은 검수필요.

    §03 정본: 경계 점수·판정 불가는 확정하지 않고 사람 검수 큐(`검수필요`)로 보낸다. 정확성이
    unverified면 점수가 높아도 검수필요다(정확성 신뢰가 없으면 동치를 단정하지 않음).
    """
    if verification == "unverified":
        return "검수필요"
    if score >= _EQUIVALENCE_HIGH:
        return "동치후보"
    if score < _EQUIVALENCE_LOW:
        return "비동치후보"
    return "검수필요"


# ──────────────────────────────────────────────────────────────────────────
# 공개 진입점
# ──────────────────────────────────────────────────────────────────────────
def evaluate_equivalent_candidate(
    spec: EquivalenceSpec,
    candidate: Problem,
    *,
    provenance: ContentProvenance,
    conditions: str | Sequence[str],
    answer_map: Mapping[str, str],
    solution_steps: Sequence[str] | None = None,
    solution_step_types: Sequence[StepType | None] | None = None,
    answer_selection: str | None = None,
    answer_aggregate: str | None = None,
    answer_kind: str | None = None,
    validator: SeedValidator | None = None,
    tag_auditor: TagAuditor | None = None,
    difficulty_tol: float = 0.5,
) -> AcceptanceVerdict:
    """자체생성 동등문제 후보를 게이트로 평가 — 순수·결정론·DB 0·LLM 0.

    다음을 *순서·단락평가 무관*하게 전부 평가해 `reasons`를 모은다(조용한 실패 금지):
      1. 저작권(`_evaluate_copyright`) — 값 확인(불변식 재구현 0).
      2. 정확성(`_evaluate_verification`) — Tier1 답 검산 + (있으면) Tier2 단계 동치 결합.
      3. 위생(`_evaluate_hygiene`) — 본문 슬립 검출.
      4. 동등성(성분 가중 평균 → 3등급 분류).
      5. 발문-수식 정합(`tag_auditor` 주입 시만 — 미주입은 True).
      6. LaTeX/문법(`_evaluate_latex`, 품질 15축 ⑩·ARCH-19) — 항상 실행.

    인자:
      - `conditions`·`answer_map`: 후보 답 검산용 원 조건·치환맵(호출자 제공·L5 파싱 밖).
      - `answer_selection`: (선택·S2-i) "큰 근/작은 근/유일" 문제의 근 선택(largest/smallest/
        unique). 방정식만으론 답이 유일하게 정해지지 않는 문제에서 *어느 근인가*를 검증한다 —
        위반 시 failed, 미declared·다근이면 verified→unverified(needs_review) 강등. None=선택 요구
        없음(단, 다근 방정식이면 유일성 미확정으로 강등될 수 있음).
      - `solution_steps`·`solution_step_types`: (선택) 이미 분해된 단계·전이당 타입.
      - `validator`: (선택) 위생 검증기(기본 `default_seed_validator()`).
      - `difficulty_tol`: 난이도 격차 허용치(만점 밴드).

    최종 `accepted` = copyright_ok AND verification=="verified" AND hygiene_ok AND
    equivalence=="동치후보" AND consistency_ok AND latex_ok. 그 외는 사람 큐(검수필요) 또는
    거부(비동치·실패)다.

    동등성은 미해결 연구 난제이므로 스코어러는 *확정이 아니라 분류*만 한다(§03). 정확성 판정 불가·
    중간 점수는 `검수필요`로 보낸다.
    """
    reasons: list[str] = []

    # ① 저작권 게이트 (값 확인).
    copyright_ok, copyright_reasons = _evaluate_copyright(candidate, provenance)
    reasons.extend(copyright_reasons)

    # ② 정확성 게이트 (Tier1 + Tier2 + 근 선택 S2-i 결합).
    verification, verification_reasons = _evaluate_verification(
        conditions,
        answer_map,
        solution_steps,
        solution_step_types,
        answer_selection,
        answer_aggregate,
        candidate.answer,
        answer_kind,
    )
    reasons.extend(verification_reasons)

    # ③ 위생 게이트 (본문 슬립).
    hygiene_ok, hygiene_reasons = _evaluate_hygiene(candidate, validator)
    reasons.extend(hygiene_reasons)

    # ④ 동등성 분류 (성분 가중 평균).
    cand_codes = frozenset(candidate.achievement_standard_codes)
    cand_misc = frozenset(entry.misconception_id for entry in (candidate.distractor_map or []))
    s_standard = _standard_score(spec.achievement_standard_codes, cand_codes)
    s_misconception = _jaccard(spec.target_misconception_ids, cand_misc)
    s_difficulty = _difficulty_score(
        candidate.difficulty_overall, spec.difficulty_overall, difficulty_tol
    )
    s_answer_format = _answer_format_score(spec.answer_format, candidate.answer_format)
    score = (
        _W_STANDARD * s_standard
        + _W_MISCONCEPTION * s_misconception
        + _W_DIFFICULTY * s_difficulty
        + _W_ANSWER_FORMAT * s_answer_format
    )
    # 부동소수 오차로 [0,1] 경계를 살짝 벗어날 수 있어 클램프(Field ge/le 위반 방지).
    score = min(1.0, max(0.0, score))

    equivalence = _classify_equivalence(score, verification)
    if equivalence != "동치후보":
        reasons.append(
            f"동등성 {equivalence} — 점수 {score:.2f}"
            f"(성취기준 {s_standard:.2f}·오개념 {s_misconception:.2f}·"
            f"난이도 {s_difficulty:.2f}·답형태 {s_answer_format:.2f})."
        )

    # ⑤ 발문-수식 정합 감사 (초인간 검증 S3·독립 주체). 감사기 미주입이면 True(기존 동작
    #    비트동일 — 자기신고 태그의 자기 채점을 독립 검증기로 교차한다).
    consistency_ok = True
    if tag_auditor is not None:
        audit = tag_auditor.audit(candidate, answer_selection=answer_selection)
        consistency_ok = audit.consistency_ok
        if not consistency_ok and audit.reason is not None:
            reasons.append(f"발문-수식 정합 감사 실패 — {audit.reason}")

    # ⑥ LaTeX/문법 게이트 (품질 15축 ⑩·ARCH-19). 감사기와 달리 항상 실행(주입 불필요 —
    #    순수 텍스트 구조 검사라 컨텍스트가 없다).
    latex_ok, latex_reasons = _evaluate_latex(candidate)
    reasons.extend(latex_reasons)

    accepted = (
        copyright_ok
        and verification == "verified"
        and hygiene_ok
        and equivalence == "동치후보"
        and consistency_ok
        and latex_ok
    )
    return AcceptanceVerdict(
        accepted=accepted,
        equivalence=equivalence,
        equivalence_score=score,
        copyright_ok=copyright_ok,
        verification=verification,
        hygiene_ok=hygiene_ok,
        consistency_ok=consistency_ok,
        latex_ok=latex_ok,
        reasons=reasons,
    )
