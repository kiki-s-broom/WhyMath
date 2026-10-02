"""학생 *최종답* ↔ 기대정답(`Problem.answer`) 동치 검증 — 서버 권위 3상태 (S3-32).

배경(학습 루프 닫힘의 서버 권위 축): `api/me.py::submit_attempt`(v1)는 `is_correct`를 *클라이언트
보고*로 신뢰한다(자체 docstring이 서버측 답안 채점 미구현을 명시). Polya `EXECUTE→REVIEW` 전이
(`l4/polya/transitions.py`)는 최종답의 *형태*(답/따라서/= 포함 + 여러 줄)만 보는 키워드 휴리스틱
이라, "정답에 도달했는가"를 실제로 판정하지 못한다. 이 모듈은 그 판정을 *서버(L3 코어)*로 끌어온다
— 학생의 최종답이 문항 기대정답과 동치인지 **3상태**로 판정한다: `correct`/`incorrect`/
`unverifiable`. CLAUDE.md "수학 로직을 클라에 넣지 않는다"(독립 수학 코어가 권위)를 지킨다.

**verify_step(단계 검증)과의 질문 차이**: `verify_step`(`l3/verify_step.py`)은 "한 *변형*이
동치인가"(expr_before ≡ expr_after)를, 이 모듈은 "학생의 *최종답*이 기대정답과 같은 값인가"를
묻는다. 둘 다 동일한 동치 권위 primitive(SymPy 단일)를 재사용하되 입력 형태가 다르다 — 여기선
`(학생답 문자열, 문항)`을 받아 `Problem.answer`(기대정답 문자열)와 대조한다.

**프리미티브 재사용(SymPy 재구현 금지·CLAUDE.md LLM/수식 동치는 단일 권위)**: 값 추출·비교는
전부 검증된 T1 primitive에 위임한다 — 새 SymPy 로직을 여기서 만들지 않는다.
  - `read_equation_step`(`l3/solution_set.py`): 학생/기대 답을 등식·연쇄 등식(`x=(5+1)/2=3`)·근
    나열(`x=2, x=3`) 형태로 읽어 *실수 값 해집합*을 낸다.
  - `equation_solution_set`(같은 모듈): 등호 없는 *맨 표현식*("3")을 합성 앵커 미지수의 등식
    (`앵커 = 3`)으로 풀어 값 해집합({3})을 얻는다(재구현 대신 기존 해집합 계산 재사용).
  - `solset_transition_status`(같은 모듈): 두 값 해집합의 동일성을 4상태로 판정한다 — 같으면
    identity(→correct)·다르면 not_identity(→incorrect)·부분집합/이질/판정불가는 undecidable
    (→unverifiable). 부분집합 가드(부분답)·이질 형태 가드가 그대로 보수적으로 작동한다.
  - `identity_status`(`l3/symbolic_equivalence.py`): 값 해집합으로 안 읽히는 *식 정답*(answer_format
    "식"·`2x+1`) 폴백 — 표현식 심볼릭 동치.

**객관식(question_format 객관식 또는 choices 보유)**: 선택지 *값* 매칭 + 한국어 수량 접미사
정규화("2개"→"2"). 라벨(원문자 ①②③)은 값-라벨 모호성 때문에 라벨→값 변환을 하지 않는다
(거짓 correct 회피 — 학생 클라이언트는 선택지 값을 제출한다는 계약).

**정직성(CLAUDE.md "확실하지 않으면 모른다"·거짓 correct 0)**: 판정 불가·파싱 불가·기대정답
미보유·빈 입력은 *절대 `correct`로 위장하지 않고* `unverifiable`로 보수 처리한다. 특히
`unverifiable`을 correct로 만드는 경로는 존재하지 않는다(is_correct 승격은 오직 correct 상태에서만).

**기대정답 비노출**: 이 모듈은 판정 상태(3상태)와 사유만 반환한다. 사유에는 학생 제출 원문만
반향하고 기대정답 원문은 싣지 않는다(어떤 응답에도 `Problem.answer`를 노출하지 않는다는 계약).

**범위 밖**: `api/me.py::submit_attempt`의 기존 클라이언트 자가보고 `is_correct` 필드는 이 모듈의
도입으로 *변경하지 않는다* — 코치 대화 흐름(`api/coach.py`·`l4/completion.py`)이 이 모듈을 써서
*별도 경로*로 서버검증 attempt를 적재한다(태스크 S3-32 설계 — 두 경로 병존, 재작성 아님).
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from whymath_backend.l3.solution_set import (
    EquationSolset,
    equation_solution_set,
    read_equation_step,
    solset_transition_status,
)
from whymath_backend.l3.symbolic_equivalence import IdentityVerdict, identity_status
from whymath_backend.schema.enums import QuestionFormat
from whymath_backend.schema.verification_capabilities import VerificationOutcome

__all__ = [
    "FinalAnswerResult",
    "FinalAnswerState",
    "budget_exceeded_result",
    "verify_final_answer",
]


# EOS-69: 3상태를 schema 중립 enum과 공유(별칭). 원 docstring이 이미
# "verify_step의 VerifyStepState와 동형"이라 자인했다 — 이제 문자 그대로 같은 객체다.
FinalAnswerState = VerificationOutcome
"""학생 최종답 검증의 3상태 — `VerificationOutcome`의 별칭."""


class FinalAnswerResult(BaseModel):
    """`verify_final_answer`의 결과 — 3상태 + 사유(한국어).

    `state`는 항상 3상태 중 하나다. `reason`은 incorrect/unverifiable일 때 *왜*인지 한국어 사유
    (correct이면 None — 사유 불필요). 사유에는 학생 제출 원문만 반향하고 기대정답은 싣지 않는다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: FinalAnswerState = Field(description="3상태 판정 — correct·incorrect·unverifiable.")
    reason: str | None = Field(
        default=None,
        description="incorrect/unverifiable 사유(한국어·기대정답 미노출). correct이면 None.",
    )


class ProblemAnswerView(Protocol):
    """`verify_final_answer`가 문항에서 읽는 최소 필드 집합(구조적 타이핑).

    `db.models.problem.Problem`(ORM)이 구조적으로 이 프로토콜을 만족한다 — L3 모듈이 db 레이어를
    *import*하지 않게(역방향 의존 회피·계층 순수) 필요한 필드만 duck-typed로 받는다. 테스트는
    ORM Problem 또는 동형 스텁을 넘길 수 있다.
    """

    answer: str | None
    choices: list[str] | None
    question_format: Any
    answer_format: Any
    multiple_answers: dict[str, Any] | None


# 앵커 미지수 — 등호 없는 맨 표현식("3")을 값 해집합으로 만들 때 좌변으로 쓰는 합성 심볼.
# 순수 영문자(뒤에 숫자 없음)라 파싱 시 단일 심볼로 남고(암묵곱 분해 안 됨), 학생/기대 답의
# 우변과 충돌하지 않는다. `_AMBIGUOUS_TRAILING_DIGIT_SYMBOL`(x2·a1) 가드에도 안 걸린다.
_ANCHOR_SYMBOL = "whymathfinalanswervalue"

# 객관식·수량 답에서 떼어내는 한국어 후행 접미사("2개"→"2"·"3번"→"3"). 최소 집합만 둔다
# (과도한 스트립은 값 훼손 위험). 라벨(원문자 ①②③)은 값-라벨 모호성 때문에 변환하지 않는다.
_ANSWER_NOISE_SUFFIXES: tuple[str, ...] = ("번째", "가지", "개", "번", "쌍")

# 등식 rhs 추출 시 등식이 아님을 알리는 비교/부등 마커(있으면 rhs 추출 보류·identity_status가 판정).
_NON_EQUALITY_MARKERS: tuple[str, ...] = ("==", "!=", "<=", ">=", "<", ">")


def _result(state: FinalAnswerState, reason: str | None) -> FinalAnswerResult:
    """결과 조립 헬퍼(단일 출구)."""
    return FinalAnswerResult(state=state, reason=reason)


def budget_exceeded_result() -> FinalAnswerResult:
    """계산 시간 상한 초과(OPS-96)의 *판정 불가* 결과 — 정답·오답 어느 쪽으로도 처리하지 않는다.

    호출부의 `is_correct` 승격은 오직 `correct`에서만 일어나므로 초과가 완료 처리나 REDIRECT(부정
    피드백)로 새지 않는다. 사유에는 학생 원문도 기대정답도 싣지 않는다.
    """
    return _result(FinalAnswerState.unverifiable, "계산 시간 상한 초과 — 서버 검증 불가")


def _strip_answer_noise(text: str) -> str:
    """답 텍스트의 공백·후행 수량 접미사를 제거 — 객관식/수량 답 정규화("2개"→"2")."""
    stripped = text.strip()
    for suffix in _ANSWER_NOISE_SUFFIXES:
        if stripped.endswith(suffix) and len(stripped) > len(suffix):
            return stripped[: -len(suffix)].strip()
    return stripped


def _is_multiple_choice(problem: ProblemAnswerView | None) -> bool:
    """문항이 객관식인가 — choices 보유 또는 question_format이 '객관식'."""
    if getattr(problem, "choices", None):
        return True
    qf = getattr(problem, "question_format", None)
    qf_value = getattr(qf, "value", qf)  # enum이면 .value·문자열이면 그대로.
    return qf_value == QuestionFormat.객관식.value


def _last_rhs(text: str) -> str:
    """등식이면 *마지막* `=` 우변만, 아니면 전체 — 식 정답 폴백(identity_status) 입력 정규화.

    비교/부등 연산(`==`·`<=` 등)이 섞이면 등식 rhs 추출을 보류하고 원문을 그대로 넘긴다
    (identity_status가 파싱 불가로 보수 처리 → unverifiable·거짓 판정 회피).
    """
    stripped = text.strip()
    if "=" in stripped and not any(marker in stripped for marker in _NON_EQUALITY_MARKERS):
        return stripped.rsplit("=", 1)[1].strip()
    return stripped


def _answer_value_solset(text: str) -> EquationSolset | None:
    """답 텍스트를 *실수 값 해집합*으로 — 판정 불가면 None(정직·보수).

    등식·연쇄 등식·근 나열은 `read_equation_step`(T1 primitive)에 위임한다(연쇄 내부 모순이면
    solset이 이미 None). 등호 없는 맨 표현식은 합성 앵커 등식(`앵커 = text`)의 해집합으로 값을
    얻는다(`equation_solution_set` 재사용 — SymPy 재구현 없음). 자유변수 포함(다변수)·비수치는
    `equation_solution_set`이 None을 돌려 정직하게 판정 불가로 이어진다.
    """
    reading = read_equation_step(text)
    if reading is not None:
        return reading.solset  # 연쇄 내부 모순(violation)이면 solset=None(정직).
    return equation_solution_set(_ANCHOR_SYMBOL, text)


def _string_scalar_forms(node: Any, out: list[str]) -> None:
    """JSONB(multiple_answers) 트리에서 스칼라(문자열·수) 잎을 답 후보 문자열로 수집(재귀).

    dict/list를 재귀하며 str·int·float 잎만 문자열로 담는다(bool은 제외 — 답 값이 아님). 구조가
    자유형이라 *추가 허용 정답을 넓히는* 용도로만 쓰고(정직: 넓히기만·좁히기 없음), 인식 못 하는
    구조는 무시된다(거짓 correct를 만들지 않는다 — 잎이 실제 답 값일 때만 매칭).
    """
    if isinstance(node, str):
        candidate = node.strip()
        if candidate:
            out.append(candidate)
    elif isinstance(node, bool):
        return  # bool은 답 값이 아님(int 하위타입이라 명시 제외).
    elif isinstance(node, (int, float)):
        out.append(str(node))
    elif isinstance(node, dict):
        for value in node.values():
            _string_scalar_forms(value, out)
    elif isinstance(node, list):
        for value in node:
            _string_scalar_forms(value, out)


def _collect_expected_forms(expected: str, problem: ProblemAnswerView | None) -> list[str]:
    """기대정답 후보 목록 — `Problem.answer` + `multiple_answers`(복수해)의 스칼라 잎.

    `multiple_answers`(출제오류 검증·자유형 JSONB)가 있으면 그 안의 스칼라 답 후보를 *추가로*
    허용한다(복수 정답 허용). 넓히기 전용(거짓 correct 0 — 잎이 실제 답 값과 동치일 때만 매칭).
    구조를 인식 못 하면 단일 `Problem.answer`만 쓴다(안전 폴백).
    """
    forms = [expected]
    multiple = getattr(problem, "multiple_answers", None)
    if isinstance(multiple, dict) and multiple:
        extra: list[str] = []
        _string_scalar_forms(multiple, extra)
        for candidate in extra:
            if candidate not in forms:
                forms.append(candidate)
    return forms


def _verify_choice(
    student: str, expected: str, problem: ProblemAnswerView | None
) -> FinalAnswerResult:
    """객관식 답 검증 — 선택지 *값* 매칭 + 수량 접미사 정규화("2개"→"2").

    판정: 정규화 값이 기대정답과 같으면 correct·수치 동치(2 vs 2.0)여도 correct. 다른 선택지
    값이거나 수치 불일치 확정이면 incorrect. 파싱 불가한 텍스트 답 등은 unverifiable(정직).
    라벨(원문자)은 값-라벨 모호성 때문에 라벨→값 변환을 하지 않는다(거짓 correct 회피).
    """
    normalized_student = _strip_answer_noise(student)
    normalized_expected = _strip_answer_noise(expected)
    if not normalized_student:
        return _result(FinalAnswerState.unverifiable, "빈 학생 답(객관식) — 검증 불가")
    if normalized_student == normalized_expected:
        return _result(FinalAnswerState.correct, None)
    # 수치 동치(예: "2" vs "2.0") — 동치 권위 primitive에 위임.
    verdict = identity_status(normalized_student, normalized_expected)
    if verdict is IdentityVerdict.identity:
        return _result(FinalAnswerState.correct, None)
    # 다른 선택지 값을 골랐거나 수치 불일치가 확정 → incorrect.
    choices = [_strip_answer_noise(str(c)) for c in (getattr(problem, "choices", None) or [])]
    if normalized_student in choices and normalized_student != normalized_expected:
        return _result(FinalAnswerState.incorrect, "다른 선택지 값 제출 — 객관식 불일치")
    if verdict is IdentityVerdict.not_identity:
        return _result(FinalAnswerState.incorrect, "객관식 답 불일치")
    # parse_error/undecidable(선택지에도 없고 수치 판정도 불가) → 위장 없이 보수.
    return _result(FinalAnswerState.unverifiable, "객관식 답 판정 불가 — 검증 안전 회피")


def _verify_value(student: str, expected_forms: list[str]) -> FinalAnswerResult:
    """일반(비객관식) 최종답 동치 — 값 해집합 비교 우선, 안 읽히면 식 동치 폴백.

    먼저 학생 답을 읽어 **연쇄 등식 내부 모순(violation)**이면 즉시 unverifiable — 최종값이 우연히
    맞아도 correct로 위장하지 않는다(자기모순 제출은 코치 개입 대상·last-rhs 폴백으로 rescue 금지).
    그 외 각 기대정답 후보에 대해:
      - 학생·기대 둘 다 값 해집합으로 읽히면 `solset_transition_status`로 비교(identity→correct·
        not_identity→incorrect·undecidable(부분답/이질/판정불가)→보류).
      - 한쪽이라도 값으로 안 읽히면(식 정답 등) `identity_status`로 표현식 동치 폴백(우변만 취함).
    어느 후보든 correct면 즉시 correct. correct는 없고 어느 후보에서 incorrect가 확정됐으면
    incorrect. 그 외(전부 보류)면 unverifiable(정직 — correct/incorrect 위장 금지).
    """
    student_reading = read_equation_step(student)
    if student_reading is not None and student_reading.violation is not None:
        # 자기모순 연쇄(예 x=(1+3)/2=3의 (1+3)/2≠3) — 최종값이 맞아도 correct 위장 금지.
        # last-rhs 표현식 폴백으로 rescue하지 않는다(거짓 correct 0·코치 개입 유도).
        return _result(FinalAnswerState.unverifiable, "학생 답 연쇄 등식 내부 모순 — 검증 보류")
    student_solset = (
        student_reading.solset
        if student_reading is not None
        else equation_solution_set(_ANCHOR_SYMBOL, student)
    )
    decided_incorrect = False
    for expected in expected_forms:
        expected_solset = _answer_value_solset(expected)
        if student_solset is not None and expected_solset is not None:
            # 값 해집합 경로 — 전이 판정(부분집합·이질 형태 가드 그대로 보수 작동).
            verdict = solset_transition_status(expected_solset, student_solset)
        else:
            # 식 정답 등 값 미해석 → 표현식 심볼릭 동치 폴백(등식이면 우변만).
            verdict = identity_status(_last_rhs(student), _last_rhs(expected))
        if verdict is IdentityVerdict.identity:
            return _result(FinalAnswerState.correct, None)
        if verdict is IdentityVerdict.not_identity:
            decided_incorrect = True
        # undecidable/parse_error → 이 후보는 보류(다른 후보·최종 집계에 위임).
    if decided_incorrect:
        return _result(FinalAnswerState.incorrect, "학생 최종답이 기대정답과 불일치")
    return _result(FinalAnswerState.unverifiable, "서버 검증 불가 — 판정 안전 회피")


def verify_final_answer(
    student_answer: str | None,
    problem: ProblemAnswerView | None,
) -> FinalAnswerResult:
    """학생 최종답이 문항 기대정답(`Problem.answer`)과 동치인지 *3상태*로 판정 — 순수·결정론·DB 0.

    서버 권위 채점의 L3 primitive(S3-32). 입력은 학생 최종답 문자열과 문항(기대정답·선택지·형식
    보유)이다. 판정 흐름:
      1. **기대정답 미보유**(`Problem.answer` None/빈값) → `unverifiable`(서버가 채점 근거 없음).
      2. **빈 학생 답** → `unverifiable`.
      3. **객관식**(choices/question_format 객관식) → `_verify_choice`(값 매칭·수량 접미사 정규).
      4. **그 외** → `_verify_value`(값 해집합 비교·식 정답 폴백). `multiple_answers`가 있으면
         복수 정답을 추가 허용(넓히기 전용).

    프리미티브 재사용(SymPy 재구현 금지): 값 추출·비교는 `read_equation_step`·
    `equation_solution_set`·`solset_transition_status`·`identity_status`(T1 primitive)에 위임한다.

    정직성(CLAUDE.md): 판정 불가·파싱 불가·미보유·빈 입력은 *절대 `correct`로 위장하지 않고*
    `unverifiable`로 보수 처리한다. `unverifiable`을 `correct`로 만드는 경로는 없다(호출자의
    is_correct 승격은 오직 `correct` 상태에서만). 기대정답 원문은 반환·사유에 노출하지 않는다.
    """
    expected_raw = getattr(problem, "answer", None)
    if expected_raw is None or not str(expected_raw).strip():
        return _result(FinalAnswerState.unverifiable, "기대정답 미보유 — 서버 검증 불가")
    expected = str(expected_raw).strip()

    student = (student_answer or "").strip()
    if not student:
        return _result(FinalAnswerState.unverifiable, "빈 학생 답 — 검증 불가")

    if _is_multiple_choice(problem):
        return _verify_choice(student, expected, problem)

    expected_forms = _collect_expected_forms(expected, problem)
    return _verify_value(student, expected_forms)
