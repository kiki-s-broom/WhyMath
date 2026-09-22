"""풀이 *한 단계* 3상태 검증 도구 — WH-1 1단계 슬라이스 2 `verify_step` 도구화(§3.1).

설계안 §3.1 "verify_step": 학생 풀이의 *한 단계*(expr_before → expr_after)가 올바른 변형인지
**3상태**로 판정한다 — `correct`/`incorrect`/`unverifiable`. 기존
`l3/pregenerate/validator.py`의 게이트(`SymPyArithmeticValidator` 등)는 솔루션 텍스트 *전체*를
훑어 *거짓 등식*만 보는 **2-state**(거짓이면 신호·아니면 None)라, "한 단계가 올바른 변형인가"를
3상태로 묻는 verify_step과 *용도가 다르다*. 본 모듈은 그 격상판의 *순수 primitive*다.

표기 계약·권위 경계(math_dsl_remediation_design.md·docs/architecture/notation_contract.md): SymPy는
이 시스템의 *수식 동치·정오 판정 단일 권위*다. 웹 mathjs(`graph2dSpec.js`·`mathExpr.js`)는 렌더·수치
평가 전용이며 동치 판정에 관여하지 않는다. 두 파서가 같은 canonical 표기(명시 `*`·caret `^`)를 같은
수치로 해석함은 golden test로 교차검증한다(`tests/backend/l3/test_notation_contract.py` ↔
`src/web/graphing-calculator/test/notation_contract.test.js`·공유 `data/notation_contract.json`).

핵심 설계 계약:
  - **식 변형(대수)**: SymPy *심볼릭 동치* 검증 → `correct`/`incorrect`. 자유변수가 있어도
    된다("2(x+1)" ≡ "2x+2"). 기존 `_equality_is_false`는 *numeric-only*(free_symbols 있으면
    skip)라 verify_step에 *재사용하지 않는다* — 같은 `sympify(convert_xor=True)` +
    `simplify().is_zero` *관용구만* 차용해 fresh로 구현한다(심볼릭 동치를 *원하므로*).
  - **등호 방정식 변형(S3-02·방향 B)**: before·after가 *둘 다* 등식 형태(`2x+3=7 → 2x=4`)이면
    표현식 동치가 아니라 **해집합 보존 동치(solution-set-preserving equivalence)** 로 판정한다 —
    두 방정식의 *실수 해집합*이 같으면 `correct`·다르면 `incorrect`·풀이 불가면 `unverifiable`.
    해집합 계산은 `l3/solution_set.py`(→ `l3/pregenerate/validator.py`의 검증된 solset 자산
    재사용·재구현 금지)에 위임한다. 과거엔 등식이 `identity_status`에서 파싱 실패해 전부
    `unverifiable`로 떨어졌다(실사용 shadow 89% unverifiable의 근본원인).
  - **자연 표기 확장(S3-06·2026-07-19 자연 사용 재측정 대응)**: 등식 형태 감지가
    `read_equation_step`으로 확장됐다 — ① 연쇄 등식 `a=b=c`(`x=(1+3)/2=2`)는 인접쌍 내부 동치를
    검사해 거짓 *증명* 시 그 자체로 `incorrect`(단계의 오류·전이 무관 안전), 전부 참이면 최초=
    최종 단일 등식으로 정규화. ② 근 나열(`x=2, x=3`·`또는`)은 같은 변수 해집합 union —
    `(x-2)(x-3)=0 → x=2, x=3`이 correct로 결정된다. ③ **이질 형태 전이 가드**: 한쪽이 항등식(ℝ)
    이면 해집합 비교를 하지 않고 unverifiable(항등 재작성 ↔ 값 선언 전이는 해집합 보존 의무가
    없음 — 거짓 incorrect 함정·`solset_transition_status` 참조). ④ 캐럿 없는 지수(`x2`)는 수열
    표기(`a1`)와 충돌해 재작성 보류 — 해집합 경로에서 판정 불가로 보수(unverifiable 유지가 정직).
  - **진부분집합 전이 가드(S3-08·2026-07-20 대본 측정 턴4)**: 유한↔유한에서 after가 before의
    비어있지 않은 진부분집합(`x=2, x=3 → x=3`)이면 unverifiable — "답 선택"(정당·문항이 큰 근
    요구)과 "근 유실"(오류·`x^2=4 → x=2`)이 구조 동일해 기대정답 없이 구별 불가하므로 거짓
    incorrect 0 계약 우선(`solset_transition_status` 참조·검출 복원은 기대정답 앵커 후속).
    비부분집합 변화({2,3}→{2,4} 등)는 incorrect 유지(검출력 보존).
  - **서술형·증명·보조선 기하·경우 나누기 등 비대수 단계**: `unverifiable`. SymPy 검증 자체가
    부적절하므로 시도하지 않고, step_type을 기록해 *검증 불가 단원에서 교착하지 않게*(정직).
  - **정직성(CLAUDE.md "확실하지 않으면 모른다")**: 판정 불가(SymPy `is_zero is None`)·파싱
    불가·예외·빈 입력은 *절대 `correct`로 위장하지 않고* `unverifiable`로 보수 처리한다.
    `unverifiable`이면 evidence_weight를 0.5로 할인한다(설계 §3.1).
  - **사유 코드 직교 필드(MATH-03·gap review §3 D3)**: "모른다"의 *종류*를 학생·운영이 구분할
    수 있게 unverifiable에 `reason_code`(폐쇄 7종 enum)를 병기한다 — state 3상태·reason 문장·
    가중치는 불변(라벨 부착이지 판정 변경 아님·`VerifyStepReasonCode` docstring이 분기 1:1 표).

정직 스코프(범위 밖 — 후속 슬라이스):
  - **PRM 점수**(PRM800K 가중치·§3.1 후반)는 *0단계 과제*라 본 슬라이스 범위 밖이다(여긴
    SymPy 결정론 3상태만).
  - **step 파싱**(학생 솔루션 텍스트 → (expr_before, expr_after) 단계 쌍 분해)도 후속이다 —
    본 모듈은 이미 분해된 *한 쌍*을 입력으로 받는 도구 primitive다.
  - **coach 파이프라인 결선**(`api/coach.py`의 `recommend_coaching_for_solution`·검산결과 적재
    등과의 배선)도 후속이다. 기존 validator/match_gate/coach/harness는 본 슬라이스에서 *불변*이며
    verify_step은 *신규 좌석*이다(기존 미접촉).
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from whymath_backend.l3.solution_set import (
    EquationReading,
    SolsetUndecidableKind,
    read_equation_step,
    solset_transition_detail,
)
from whymath_backend.l3.symbolic_equivalence import IdentityVerdict, identity_status_detail
from whymath_backend.schema.enums import StepType
from whymath_backend.schema.verification_capabilities import VerificationOutcome

__all__ = [
    "VerifyStepForm",
    "VerifyStepReasonCode",
    "VerifyStepResult",
    "VerifyStepState",
    "verify_step",
]


# EOS-69: 3상태 어휘를 schema의 중립 enum과 **공유**한다(별칭 — 새 enum 정의 금지).
# 어댑터가 자기 enum을 따로 두면 경계에서 매핑이 필요해지고, 그 매핑이 곧
# "unverifiable을 incorrect로 접는" 상태 붕괴 지점이 된다(설계 규칙 3).
# 이름은 유지한다 — 기존 호출부·테스트가 그대로 읽는다(동작 변경 0).
VerifyStepState = VerificationOutcome
"""풀이 한 단계 검증의 3상태 — `VerificationOutcome`의 별칭(§3.1 verify_step)."""

# correct/incorrect는 결정론 검증이라 충분한 증거(가중치 1.0)·unverifiable은 *판정을 못 한*
# 상태라 절반으로 할인(설계 §3.1) — 후속 PRM·다중풀이 집계가 이 가중치를 곱해 쓴다.
_WEIGHT_DECISIVE = 1.0  # correct·incorrect — 결정론 판정 완료.
_WEIGHT_UNVERIFIABLE = 0.5  # unverifiable — 판정 불가, 증거력 할인.


class VerifyStepForm(str, Enum):
    """이 전이를 *어느 경로로* 판정했는가 — 등식(해집합)·혼합·표현식(S3-51 관측 축).

    `state`(3상태)·`reason_code`(왜 판정 못 했는가)와 직교하는 **형태 라벨**이다. 판정 로직을
    바꾸지 않고, 이미 분기에서 결정돼 있던 사실을 하류가 *셀 수 있게* 노출만 한다.

    왜 필요한가(작동한 비율 원칙 — CLAUDE.md "작동 신호 없는 알고리즘 부착 금지"): S3-02가
    붙인 해집합 보존 판정이 실사용에서 **몇 번 실제로 작동했는지**를 현행 관측이 말하지
    못했다. 3상태만으로는 "등호 방정식 변형을 해집합으로 판정한 correct"와 "표현식 동치
    correct"가 같은 글자다. 자유사용 대표측정(S3-02 트리거 ③)의 사전등록 유효성 전제
    V3(등호 방정식 변형 턴 >=5건)이 바로 이 축이라, 축이 없으면 사람이 자유사용 중에 손으로
    세야 하고 그러면 "자연 자유사용"(대본 금지) 전제가 깨진다.

    프라이버시: 값은 경로 라벨 3종뿐이고 학생 원문·식·정답을 담지 않는다 — 하류(shadow 관측
    레코드)가 *개수*로만 집계한다.
    """

    equation = "equation"
    """양변 모두 등식 형태 — 해집합 보존 동치로 판정(S3-02 경로). 연쇄 등식 내부 위반 승격 포함."""

    mixed = "mixed"
    """한쪽만 등식(방정식↔표현식 혼합) — 비교 전제 불성립이라 보수적 unverifiable."""

    expression = "expression"
    """양변 모두 등식 아님 — SymPy 심볼릭 동치 경로(기존 기본 경로)."""


class VerifyStepReasonCode(str, Enum):
    """unverifiable *사유 코드* — 폐쇄 7종 운영 taxonomy(MATH-03·gap review §3 D3).

    `state` 3상태는 **불변**이다(4·5상태 확장 금지 — BKT·코치·집계·모바일 계약이 전부
    흔들린다). 이 코드는 `step_type`처럼 **직교 필드**로만 붙는다: `reason`(사람용 자유문)과
    병렬인 구조 라벨 — `l3/equivalent/rephrase.py`의 reason_code(taxonomy)+reason(문장) 병렬
    필드 선례를 그대로 답습한다(신규 패턴 발명 0·`str, Enum`이라 직렬화는 평문 문자열 동일).

    분기 1:1 실측(2026-08-11 — 전 분기가 기존 코드에 실재·신규 판정 로직 0, 라벨링만):
      - `non_algebraic_step` ← 비대수 step_type 게이트(조건해석·케이스분류·그래프스케치).
      - `empty_input` ← 빈 입력 가드.
      - `parse_error` ← 표현식 경로 `IdentityVerdict.parse_error`(sympify 예외·정규화 공백).
      - `undecidable` ← 표현식 경로 비다항 미결정 **및** 등식 경로 해집합 계산 불가
        (`SolsetUndecidableKind.incomputable_side` — 다변수·비다항·복소·미정·연쇄 미결속).
      - `variable_mismatch` ← 표현식 경로 undecidable 중 *다항 + 자유변수 집합 불일치*(치환
        맥락 — `identity_status_detail`이 이미 계산하던 불리언의 노출).
      - `heterogeneous_form` ← 등식 경로 ℝ↔유한 이질 형태(S3-06) **및** 등호 방정식↔표현식
        혼합 단계. 초안 조정 실측 근거: 혼합 분기는 초안 7종에 별도 코드가 없었는데, 두 분기
        모두 "두 변의 *형태*가 이질적이라 비교 전제 불성립"이라 한 코드로 묶는다(운영 세부는
        `reason` 문장이 이미 달라 코드 폭발 없이 구분 가능).
      - `subset_ambiguous` ← 등식 경로 유한↔유한 진부분집합(답 선택↔근 유실 구별 불가·S3-08).

    노출 비대칭(의도·검증기 내부 미노출): 운영은 7종 전부, 학생 화면은 **3분기**만 — 고칠 수
    있는 것(parse_error·empty_input)/고칠 게 없는 것(non_algebraic_step)/단정하지 않는 것
    (나머지 4종). 접는 쪽은 모바일 `coach_signal_card.dart`다.

    D5 경계(범위 밖 명시): 이 코드는 *"왜 판정 못 했는가"*(검증 메타데이터)이지 *"이 단계가
    어떤 종류의 추론인가"*(`ReasoningStep` 도메인 모델)가 아니다 — D5를 앞당기지 않는다.
    """

    parse_error = "parse_error"
    """파싱 불가 — 표기를 시스템이 못 읽음(학생이 고칠 수 있는 축·MATH-01 발화 조건 데이터)."""

    undecidable = "undecidable"
    """SymPy 미결정 — 증명도 반증도 못 함(비다항·정의역 의존·해집합 계산 불가·보류 톤)."""

    non_algebraic_step = "non_algebraic_step"
    """비대수 단계 — 원래 계산으로 확인하는 종류가 아님(학생이 고칠 게 없는 축)."""

    empty_input = "empty_input"
    """빈 입력 — 검증할 식 자체가 없음(학생이 고칠 수 있는 축)."""

    heterogeneous_form = "heterogeneous_form"
    """형태 이질 — ℝ↔유한(항등 재작성↔값 선언) 또는 등식↔표현식 혼합·비교 전제 불성립."""

    subset_ambiguous = "subset_ambiguous"
    """진부분집합 전이 — 답 선택(정당)↔근 유실(오류)이 구조 동일해 단정 불가(S3-08)."""

    variable_mismatch = "variable_mismatch"
    """변수 집합 불일치 — 치환 맥락 의존이라 항등 반증 봉인(거짓 incorrect 회피)."""


# 등식 경로 undecidable 가드 라벨(`solset_transition_detail`) → 운영 reason_code 사상.
# 라벨은 분기 발생 지점(solution_set)이 내고 여기는 어휘 번역만 한다 — 가드 재검사(병렬 진실)
# 금지. incomputable_side는 세부 원인(파싱·다변수·비다항·복소·미정)이 해집합 계산 안에서 이미
# 합쳐져 있으므로(solution_set_status docstring "parse_error를 따로 두지 않고 undecidable로
# 통합") 정직하게 undecidable로 접는다.
_SOLSET_KIND_TO_REASON: dict[SolsetUndecidableKind, VerifyStepReasonCode] = {
    SolsetUndecidableKind.incomputable_side: VerifyStepReasonCode.undecidable,
    SolsetUndecidableKind.heterogeneous_form: VerifyStepReasonCode.heterogeneous_form,
    SolsetUndecidableKind.proper_subset: VerifyStepReasonCode.subset_ambiguous,
}

# SymPy 검증을 시도하지 *않는* 비대수 step_type — 서술형·경우 나누기·보조선 기하 등.
# 이 단계들은 식 변형이 아니라 대수 동치로 옳고 그름을 가릴 수 없다(unverifiable·정직).
# `계산`·`검산`은 대수(SymPy 검증 가능)라 이 집합에 *없다*(아래 동치 경로로 간다).
_NON_ALGEBRAIC_STEP_TYPES: frozenset[StepType] = frozenset(
    {StepType.조건해석, StepType.케이스분류, StepType.그래프스케치}
)


class VerifyStepResult(BaseModel):
    """`verify_step`의 결과 — 3상태 판정 + 사유(문장·코드)·증거 가중치 + step_type 전파.

    `state`는 항상 채워진다(3상태 중 하나). `reason`은 incorrect/unverifiable일 때 *왜*인지
    한국어 사유(correct이면 None — 사유 불필요). `reason_code`는 unverifiable일 때만 채워지는
    폐쇄 7종 구조 라벨(MATH-03 — `reason`과 병렬·rephrase.py 선례)이고 correct/incorrect는
    None이다(코드의 질문이 "왜 판정 못 했는가"라서). `evidence_weight`는 correct/incorrect=
    1.0·unverifiable=0.5(설계 §3.1 할인 — 라벨 부착과 무관하게 불변). `step_type`은 입력을
    그대로 전파(하류가 어떤 종류의 단계였는지 안다·None 가능).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: VerifyStepState = Field(
        description="3상태 판정 — correct(동치)·incorrect(거짓 증명)·unverifiable(검증 불가)."
    )
    step_type: StepType | None = Field(
        default=None,
        description="입력 step_type 전파(어떤 단계였는지). 미지정이면 None.",
    )
    reason: str | None = Field(
        default=None,
        description="incorrect/unverifiable 사유(한국어). correct이면 None(사유 불필요).",
    )
    reason_code: VerifyStepReasonCode | None = Field(
        default=None,
        description=(
            "unverifiable *사유 코드*(폐쇄 7종·MATH-03). unverifiable이면 항상 채워지고 "
            "correct/incorrect는 None — reason(자유문)과 병렬인 구조 라벨(rephrase.py 선례)."
        ),
    )
    evidence_weight: float = Field(
        description="증거 가중치 — correct/incorrect=1.0·unverifiable=0.5(설계 §3.1 할인).",
    )
    form: VerifyStepForm | None = Field(
        default=None,
        description=(
            "판정 경로 형태(equation|mixed|expression·S3-51 관측 축). None은 형태를 "
            "*판별하기 전에* 회피한 경우(비대수 step_type·빈 입력) — 'expression'으로 "
            "위장하지 않는다(정직 회계)."
        ),
    )


def _unverifiable(
    reason: str,
    step_type: StepType | None,
    reason_code: VerifyStepReasonCode,
    form: VerifyStepForm | None = None,
) -> VerifyStepResult:
    """unverifiable 결과 조립 — 사유·step_type 전파·가중치 0.5(정직 회피의 단일 출구).

    `reason_code`는 필수 인자다(MATH-03) — 모든 unverifiable 분기가 구조 라벨을 갖게 시그니처
    수준에서 강제한다(코드 없는 unverifiable을 만들 수 없음 → 집계 총합 불변식의 구조 보장).

    `form`(S3-51)은 선택이다 — 형태를 *판별하기 전에* 회피한 분기(비대수 step_type·빈 입력)는
    None이 정직하다("expression으로 접기" 금지). 형태를 판별한 뒤의 회피(해집합 판정 불가·
    혼합 형태·SymPy 미결정)는 호출부가 해당 형태를 넘긴다.
    """
    return VerifyStepResult(
        state=VerifyStepState.unverifiable,
        step_type=step_type,
        reason=reason,
        reason_code=reason_code,
        evidence_weight=_WEIGHT_UNVERIFIABLE,
        form=form,
    )


def _equation_step_result(
    expr_before: str,
    expr_after: str,
    before_reading: EquationReading,
    after_reading: EquationReading,
    step_type: StepType | None,
) -> VerifyStepResult:
    """등식 형태 단계를 *해집합 보존 동치*로 판정 → 3상태(S3-02·S3-06·재사용 집계 매핑).

    `solset_transition_status`(해집합 전이 4상태·`l3/solution_set.py`)를 verify_step 3상태로
    매핑한다:
      - identity(해집합 보존) → correct(가중치 1.0·사유 None).
      - not_identity(해집합 변화·진부분집합 아닌 다름) → incorrect(가중치 1.0·사유 채움).
      - undecidable(다변수·비다항·복소·미정·파싱 불가·**ℝ↔유한 이질 형태**·**유한↔유한
        진부분집합**) → unverifiable(가중치 0.5·정직 할인). 이질 형태 가드는 S3-06 거짓
        incorrect 함정 방어 — 항등식(ℝ) ↔ 값 선언 전이는 해집합 보존 의무가 없다. 진부분집합
        가드는 S3-08 — 답 선택(정당)과 근 유실(오류)이 구조 동일해 기대정답 없이 구별 불가
        (`solset_transition_status` 참조).

    표현식 경로(`identity_status`)와 *같은 매핑 형태*를 유지해 하류(verify_solution 집계)가 두
    경로를 구분 없이 흡수하게 한다. `reason`은 학생 제출 등식 원문만 반향한다(정답 미조회·미누출).

    MATH-03: undecidable일 때 `solset_transition_detail`의 가드 라벨(계산 불가·이질 형태·
    진부분집합)을 `reason_code`로 사상한다 — state·reason 문장·가중치는 라벨 부착 전과 동일
    (판정 변경 아님).
    """
    verdict, undecidable_kind = solset_transition_detail(
        before_reading.solset, after_reading.solset
    )
    if verdict is IdentityVerdict.identity:
        return VerifyStepResult(
            state=VerifyStepState.correct,
            step_type=step_type,
            reason=None,
            evidence_weight=_WEIGHT_DECISIVE,
            form=VerifyStepForm.equation,
        )
    if verdict is IdentityVerdict.not_identity:
        return VerifyStepResult(
            state=VerifyStepState.incorrect,
            step_type=step_type,
            reason=f"해집합 비보존 — SymPy: {expr_before} ↛ {expr_after}",
            evidence_weight=_WEIGHT_DECISIVE,
            form=VerifyStepForm.equation,
        )
    # undecidable/parse_error → 위장 없이 unverifiable(다변수·비다항·복소·미정·파싱 불가).
    # 가드 라벨은 발생 지점(solution_set)이 낸 것을 어휘 번역만 한다(가드 재검사 금지). 계약상
    # undecidable이면 kind가 항상 채워지지만, 만약 비면 가장 보수적인 undecidable로 접는다.
    reason_code = (
        _SOLSET_KIND_TO_REASON[undecidable_kind]
        if undecidable_kind is not None
        else VerifyStepReasonCode.undecidable
    )
    return _unverifiable(
        "해집합 판정 불가 — 검증 안전 회피", step_type, reason_code, VerifyStepForm.equation
    )


def verify_step(
    expr_before: str,
    expr_after: str,
    step_type: StepType | None = None,
) -> VerifyStepResult:
    """풀이 한 단계(expr_before → expr_after)가 올바른 변형인지 *3상태*로 판정 — 순수·결정론·DB 0.

    설계안 §3.1 verify_step의 도구 primitive. 입력은 이미 분해된 *한 단계 쌍*(step 파싱은 후속).

    판정 로직:
      1. **비대수 step_type**(조건해석·케이스분류·그래프스케치) → 즉시 `unverifiable`. SymPy를
         *시도하지 않는다*(식 변형이 아니라 동치로 가릴 수 없음·검증 불가 단원 교착 방지·정직).
      1.4. **연쇄 등식 내부 위반**(S3-06): 어느 쪽이든 `a=b=c` 체인의 인접쌍이 거짓으로 *증명*
         되면(예 `x=(1+3)/2=3`의 `(1+3)/2≠3`) 전이 비교와 무관하게 `incorrect` — 단계 자체의
         거짓이라 승격이 안전하다(해집합 비교의 이질 형태 함정과 무관).
      1.5. **등식 형태 단계**(before·after가 *둘 다* 등식 형태 — 단일 등식·연쇄 정규화·근 나열)
         → 해집합 보존 동치로 판정(S3-02·S3-06·S3-08·`solset_transition_status`). 해집합 같으면
         correct·다르면 incorrect·풀이 불가/**이질 형태(ℝ↔유한)**/**유한↔유한 진부분집합
         (답 선택↔근 유실 구별 불가·S3-08)** 면 unverifiable. 한쪽만 등식이면(방정식↔표현식
         혼합) 비교 대상이 어긋나 보수적 unverifiable(거짓 incorrect 회피).
      2. **그 외**(계산·검산·미지정·등호 없는 식) → SymPy 심볼릭 동치 검증(자유변수 OK — "2(x+1)" ≡
         "2x+2"·`convert_xor=True`라 `^`=거듭제곱). 차이 `diff = before - after`에서:
         - **correct**: `expand(diff) == 0`(다항식 항등식이 0으로 환원) *또는*
           `simplify(diff).is_zero is True`(삼각 등 비다항 항등식)이면 올바른 변형(가중치 1.0).
         - **incorrect**: `simplify(diff).is_zero is False`(상수 차 등 0-아님 확정) *또는* `diff`가
           *같은 자유변수*의 다항식(`before.free_symbols == after.free_symbols`)인데 전개가 0이
           아니면 — 0-아닌 다항식은 영함수가 아니므로 *항등식 아님이 증명*된다(예: `(a+b)² ≠
           a²+b²`·`2ab`는 `a=b=1`에서 거짓). 가장 흔한 대수 오류를 잡는다(가중치 1.0).
         - **unverifiable**: 비다항이고 simplify 미정(예: `√(x²)` vs `x`는 정의역 의존)·**변수
           집합이 달라 맥락 의존**(예: 치환 `a`→`b+1`·산문이 심볼로 강제)·sympify 예외(파싱
           불가)·빈 입력 → *위장 없이* 보수 처리(거짓 incorrect 금지·가중치 0.5).

    정직성(CLAUDE.md "확실하지 않으면 모른다"): 판정 불가·파싱 불가·예외·빈 입력은 *절대*
    `correct`로 위장하지 않고 보수적으로 `unverifiable`로 떨어뜨린다(가중치 0.5 할인).

    범위 밖(후속): PRM 점수(PRM800K 가중치)·step 파싱(솔루션→단계 분해)·coach 파이프라인 결선.
    """
    # ① 비대수 단계 — SymPy 시도 없이 unverifiable(검증 불가 단원 교착 방지·정직).
    if step_type in _NON_ALGEBRAIC_STEP_TYPES:
        return _unverifiable(
            "비대수 단계(서술형/경우나누기/기하) — SymPy 검증 불가",
            step_type,
            VerifyStepReasonCode.non_algebraic_step,
        )

    # 빈 입력은 동치 판정 불가 — 파싱 전에 보수적 unverifiable(빈 문자열을 0으로 오인 회피).
    if not expr_before.strip() or not expr_after.strip():
        return _unverifiable(
            "빈 입력 — 검증 안전 회피", step_type, VerifyStepReasonCode.empty_input
        )

    # ①.4 등식 형태 해석(S3-06) — 단일 등식·연쇄 등식(a=b=c)·근 나열(x=2, x=3)을 통합해 읽는다.
    before_reading = read_equation_step(expr_before)
    after_reading = read_equation_step(expr_after)

    # ①.45 연쇄 등식 내부 위반 — 인접쌍 거짓이 *증명*되면 단계 자체가 거짓이므로 전이 비교와
    # 무관하게 incorrect 승격이 안전하다(예: x=(1+3)/2=3 의 (1+3)/2≠3·S3-06 ①). 반면 전이의
    # 해집합 비교는 동질 형태일 때만 한다(이질 형태 함정·solset_transition_status 참조). reason은
    # 학생 제출 원문 조각만 반향한다(정답 미조회·미누출).
    for reading in (after_reading, before_reading):
        if reading is not None and reading.violation is not None:
            violated_lhs, violated_rhs = reading.violation
            return VerifyStepResult(
                state=VerifyStepState.incorrect,
                step_type=step_type,
                reason=f"연쇄 등식 내부 동치 위반 — SymPy: {violated_lhs} ≠ {violated_rhs}",
                evidence_weight=_WEIGHT_DECISIVE,
                form=VerifyStepForm.equation,
            )

    # ①.5 등식 형태 단계 — before·after가 *둘 다* 등식 형태면 해집합 보존 동치로 판정한다
    # (표현식 동치가 아니라 방정식 변형·S3-02·S3-06). 한쪽만 등식이면(방정식↔표현식 혼합) 비교
    # 대상이 어긋나므로 보수적 unverifiable(거짓 incorrect 회피·정확성 #1).
    if before_reading is not None and after_reading is not None:
        return _equation_step_result(
            expr_before, expr_after, before_reading, after_reading, step_type
        )
    if before_reading is not None or after_reading is not None:
        # 형태 이질(등식↔표현식)이라 비교 전제 불성립 — ℝ↔유한 가드와 같은 계열이므로 같은
        # heterogeneous_form 코드로 라벨한다(운영 세부는 reason 문장으로 이미 구분·MATH-03).
        return _unverifiable(
            "등호 방정식↔표현식 혼합 단계 — 검증 대상 불일치·안전 회피",
            step_type,
            VerifyStepReasonCode.heterogeneous_form,
            VerifyStepForm.mixed,
        )

    # ② 대수 단계(계산·검산·None·등호 없는 식) — 동치 권위 primitive(`identity_status`·SymPy) 위임.
    # 자유변수 OK·convert_xor로 ^=거듭제곱·같은 변수 다항 비항등식은 not_identity로 *증명*된다
    # ((a+b)²−(a²+b²)=2ab는 a=b=1에서 거짓·freshman's dream). 변수 집합이 다른 치환 등은 primitive
    # 가 undecidable로 보수 처리해 거짓 incorrect를 회피한다(정확성 #1). MATH-03: detail판을 불러
    # undecidable의 변수 불일치 라벨(variable_mismatch)까지 받는다 — 판정(verdict)은 동일 본체.
    detail = identity_status_detail(expr_before, expr_after)
    verdict = detail.verdict
    if verdict is IdentityVerdict.identity:
        return VerifyStepResult(
            state=VerifyStepState.correct,
            step_type=step_type,
            reason=None,
            evidence_weight=_WEIGHT_DECISIVE,
            form=VerifyStepForm.expression,
        )
    if verdict is IdentityVerdict.not_identity:
        return VerifyStepResult(
            state=VerifyStepState.incorrect,
            step_type=step_type,
            reason=f"동치 아님 — SymPy: {expr_before} ≠ {expr_after}",
            evidence_weight=_WEIGHT_DECISIVE,
            form=VerifyStepForm.expression,
        )
    # parse_error(빈 입력은 위에서 거름·sympify 예외) → "파싱 불가" 표기로 보수. 이 코드의 비중이
    # 곧 MATH-01(표기 권위)·자연표기 확장(gap review §5-③)의 발화 조건 데이터다.
    if verdict is IdentityVerdict.parse_error:
        return _unverifiable(
            "SymPy 판정 불가/파싱 불가 — 검증 안전 회피",
            step_type,
            VerifyStepReasonCode.parse_error,
            VerifyStepForm.expression,
        )
    # undecidable — 항등성을 *증명도 반증도* 못 함(예: √(x²) vs x는 정의역 의존)·correct 위장 금지.
    # 변수 집합 불일치(치환 맥락·detail이 이미 계산한 불리언)면 별도 라벨 — 운영이 "치환 맥락"과
    # "비다항 미결정"을 구분하게 한다(reason 문장·state·가중치는 두 경우 동일).
    return _unverifiable(
        "SymPy 판정 불가 — 검증 안전 회피",
        step_type,
        (
            VerifyStepReasonCode.variable_mismatch
            if detail.variable_mismatch
            else VerifyStepReasonCode.undecidable
        ),
        VerifyStepForm.expression,
    )
