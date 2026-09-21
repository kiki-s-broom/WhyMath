"""EOS Core가 아는 **검증 능력 계약** — 과목 중립 (EOS-69).

**왜 `SubjectAdapter`에 다 넣지 않았나 (2026-08-31 Kiki 결정)**
"계약에 넣을 것인가"의 답은 YES지만, **하나의 Protocol에 전부 넣는 방식은 NO**다.
`SubjectAdapter`(schema/subject_adapter.py)는 *모든* 과목이 반드시 제공해야 하는 최소 3종
(`evaluate_answer`·`detect_misconception`·`validate_problem`)이고, 스스로 메서드 추가를
"이 능력이 Physics·Chemistry·History에도 **반드시** 존재하는가?"로 게이팅한다.

단계 연쇄 검증·기호 항등 판정은 그 질문에 "반드시"라고 답할 수 없다 — 수학·물리엔 있고
역사엔 없다. 그래서 **필수 계약을 넓히는 대신 능력별로 좁게 쪼갠다**(인터페이스 분리 원칙).
과목은 제공 가능한 능력만 구현하고, Core는 자기가 쓰는 좁은 Protocol만 안다.

**설계 규칙 3**
1. **구조적 Protocol만 쓴다(변환·래핑 금지)** — 어댑터의 리치 타입(`VerifyStepResult` 등)이
   그대로 이 Protocol을 만족한다. 중간 변환 객체를 두면 그 변환이 곧 상태 재해석 지점이
   되고, `EOS-69` acceptance ③이 금지한 **unverifiable을 fail로 접기**가 거기서 일어난다.
2. **Core가 실제로 읽는 것만 노출한다** — `reason_code`·`step_type`·`evidence_weight`는
   수학 어댑터 내부 어휘다. Core는 그것을 알 필요가 없고, 알게 되면 다시 과목에 묶인다.
3. **상태 enum은 공유한다(별도 정의 금지)** — 어댑터가 자기 enum을 따로 두면 두 어휘가
   생기고 경계에서 매핑이 필요해진다. 매핑은 곧 붕괴 지점이다(규칙 1과 같은 이유).
4. **멤버는 읽기 전용(`@property`)으로 선언한다** — Protocol에 `x: int`로 쓰면 "쓰기 가능한
   변수"를 요구하게 되어 **frozen pydantic 모델이 계약을 만족하지 못한다**(mypy가
   "expected settable variable, got read-only attribute"로 거부). 게다가 변수 선언은 타입이
   불변(invariant)이라 `list[VerifyStepResult]`가 `Sequence[StepOutcome]`을 만족하지 못한다.
   Core는 읽기만 하므로 읽기 전용이 의미상으로도 옳다. (2026-08-31 실측: 이 규칙 없이
   선언했더니 `SolutionVerificationResult`가 계약을 **만족하지 않았고**, 적합성 증명을
   붙이기 전까지 그 사실이 드러나지 않았다 — "정본화 ≠ 집행"의 타입 축 판)

3상태의 의미는 **불변 계약**이다: `unverifiable`은 "틀렸다"가 아니라 "판정하지 못했다"이며,
이를 `incorrect`로 접는 것은 미검증을 검증으로 위장하는 행위다(초인간 검증 기준).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from whymath_backend.schema.answer_form import FormVerdict
from whymath_backend.schema.assessment_evidence import MisconceptionCandidate, MisconceptionScan

__all__ = [
    "AnswerFormVerifier",
    "AttemptMisconceptionDetector",
    "AttemptMisconceptionScan",
    "VerificationOutcome",
    "EquivalenceOutcome",
    "StepOutcome",
    "ChainVerification",
    "ChainVerificationCounts",
    "StepChainVerifier",
    "FinalAnswerOutcome",
    "FinalAnswerVerifier",
    "SealOutcome",
    "AssessmentAnswerVerifier",
    "ExpressionSeal",
    "ExpressionEquivalence",
]


class VerificationOutcome(str, Enum):
    """검증 3상태 — 과목 중립. 어댑터의 상태 enum은 이것을 **별칭으로 공유**한다.

    `str, Enum`이라 멤버가 문자열 값과 동등 비교된다(`schema/enums.py` 컨벤션).
    """

    correct = "correct"
    """결정론으로 참임을 확인 — 증거 충분."""

    incorrect = "incorrect"
    """결정론으로 거짓임을 **증명** — 반증 확보. '판정 못 함'과 다르다."""

    unverifiable = "unverifiable"
    """판정하지 못함 — 기계가 닫지 못한 축. **`incorrect`로 접으면 안 된다.**"""


class EquivalenceOutcome(str, Enum):
    """두 표현의 항등 판정 4상태 — 과목 중립.

    3상태와 달리 *미결정*이 두 갈래다: 판정 자체가 불가한 것(`undecidable`)과 입력을 읽지
    못한 것(`parse_error`). 둘을 합치면 "표현이 나빴다"와 "문제가 어려웠다"가 구별되지 않아
    개선 방향을 잃는다.
    """

    identity = "identity"
    """두 표현이 항등적으로 같음이 확정."""

    not_identity = "not_identity"
    """항등이 아님이 확정 — 반증 확보."""

    undecidable = "undecidable"
    """증명도 반증도 못 함(정의역 의존·비다항 등). 보수 판정."""

    parse_error = "parse_error"
    """입력을 읽지 못함 — 검증 안전 회피. 내용 판정이 아니다."""


@runtime_checkable
class StepOutcome(Protocol):
    """단계 1건의 검증 결과 중 **Core가 읽는 부분**.

    어댑터의 리치 결과가 이 모양을 이미 만족한다 — 새 타입을 만들지 않는다(설계 규칙 1).
    """

    @property
    def state(self) -> VerificationOutcome: ...


@runtime_checkable
class ChainVerification(Protocol):
    """단계 연쇄 검증 결과 중 **Core가 읽는 부분**.

    `first_incorrect_index`가 `None`이라는 것은 "틀린 전이가 없다"이지 "전부 검증됐다"가
    아니다 — 전부 `unverifiable`이어도 `None`이다. 부분 점수·코칭이 이 둘을 같게 다루면
    미검증을 통과로 위장한다(`l6.blueprint.assembly.partial_credit`이 그래서 `steps`의
    `state`를 따로 본다).
    """

    @property
    def steps(self) -> Sequence[StepOutcome]: ...

    @property
    def first_incorrect_index(self) -> int | None: ...

    @property
    def n_transitions(self) -> int:
        """전이 수(= `len(steps)`) — 부분점수의 **분모**라 채점자도 읽는다.

        계측용 카운트(`ChainVerificationCounts`)와 달리 여기 있는 이유: 0이면 "검증할 전이가
        없음"이고, 0을 분모로 쓰면 채점이 터진다. 채점자가 반드시 봐야 하는 값이다.
        """


@runtime_checkable
class ChainVerificationCounts(ChainVerification, Protocol):
    """연쇄 검증의 **집계 카운트**까지 읽는 소비자를 위한 확장 — 계측·적재 좌석 전용.

    `ChainVerification`을 넓히지 않고 **따로 뺀** 이유(인터페이스 분리):
    부분 점수 계산(`l6.blueprint.assembly.partial_credit`)은 `steps`·`first_incorrect_index`·
    `n_transitions`만 읽는다 — 채점에 필요한 것은 "어디서 틀렸나"와 "분모가 몇인가"이지
    상태별 분포가 아니다. 거기에 카운트 5종을 얹으면 *쓰지도 않는 것*을 구현하라고 강요하게
    된다 — "계약에 넣는다"와 "하나에 다 넣는다"는 다르다.

    카운트 규약(구현이 지켜야 하는 것):
      - `n_correct + n_incorrect + n_unverifiable == n_transitions` (합 보존)
      - `sum(unverifiable_by_reason.values()) == n_unverifiable` (희소 dict·관측된 코드만)
      - `unverified_ratio`는 전이 0건일 때의 정의를 구현이 명시한다(0으로 위장 금지)

    `unverifiable_by_reason`의 **키 타입이 `Any`인 것은 회피가 아니라 배정**이다 —
    보류 사유 어휘는 과목 소유다(수학의 `parse_error`·`sympy_timeout`은 역사에 없다).
    Core가 키에서 읽는 것은 문자열 값 하나(`.value`)뿐이며, 폐쇄 코드 집합을 Core가 알면
    과목이 바뀔 때마다 중립 계약을 고쳐야 한다.
    """

    @property
    def n_correct(self) -> int: ...

    @property
    def n_incorrect(self) -> int: ...

    @property
    def n_unverifiable(self) -> int: ...

    @property
    def unverified_ratio(self) -> float: ...

    @property
    def unverifiable_by_reason(self) -> Mapping[Any, int]: ...


class StepChainVerifier(Protocol):
    """풀이 단계 연쇄를 전이별로 검증하는 능력 — **선택적**.

    제공하지 않는 과목이 정상이다(서술형 역사 답안엔 '전이 동치'가 없다). Core는 이 능력이
    주입되지 않았을 때의 경로를 반드시 갖는다.

    **반환 타입이 `ChainVerification`이 아니라 `ChainVerificationCounts`인 이유(EOS-86 리뷰
    실측 — PR #1018 Codex)**: 이 능력의 유일한 소비처(`l4.solution_coaching.recommend_
    coaching_for_solution` → `api/coach.py`의 `_log_verify_event`)가 `n_correct`·
    `n_incorrect`·`n_unverifiable`·`unverified_ratio`·`unverifiable_by_reason`(카운트
    확장분)을 **무조건 읽는다**. 좁은 `ChainVerification`만 요구했다면, 그것만 만족하는
    커스텀 구현을 주입해도 타입 검사를 통과해 놓고 그 카운트 필드 접근에서
    `AttributeError`가 났을 것이다 — "필요만큼만 요구한다"는 인터페이스 분리 원칙(모듈
    docstring 규칙 2)은 *소비처가 실제로 좁을 때*만 성립하고, 이 계약은 소비처가 넓어서
    성립하지 않는다.
    """

    def verify_chain(
        self, steps: Sequence[str], step_types: Sequence[Any] | None = None
    ) -> ChainVerificationCounts:
        """인접 단계 전이를 순서대로 검증한다. 전이 수 = `len(steps) - 1`.

        `step_types`는 전이당 하나씩(길이 = `len(steps) - 1`) 붙는 *과목별* 단계 유형 힌트
        — 규칙 2("Core가 실제로 읽는 것만 노출한다")에 따라 타입을 `Any`로 둔다. 어휘(수학의
        `StepType.케이스분류` 등)는 과목 소유이고, Core는 값을 해석하지 않고 그대로 통과시킬
        뿐이다(`unverifiable_by_reason`의 `Any` 키와 동일 근거). 제공하지 않는 구현은 무시해도
        된다(선택적 정밀화 — 없어도 계약을 만족한다)."""
        ...


@runtime_checkable
class FinalAnswerOutcome(Protocol):
    """최종답 판정 결과 중 **Core가 읽는 부분** — 상태 하나.

    `reason`(한국어 사유)은 노출하지 않는다: Core가 사유 문자열을 읽기 시작하면 그 문구가
    사실상 계약이 되고, 과목마다 다른 어휘를 Core가 파싱하게 된다(설계 규칙 2).
    """

    @property
    def state(self) -> VerificationOutcome: ...


class FinalAnswerVerifier(Protocol):
    """학생 최종답을 문항의 기대정답과 대조하는 능력 — **선택적**.

    **기대정답은 이 경계 밖으로 나오지 않는다** — Core는 *문항*을 넘기고 *상태*를 받는다.
    기대정답 문자열을 Core가 먼저 꺼내 넘기는 형태(`verify(submitted, expected)`)로 쓰지
    않는 이유가 이것이다: 그러면 정답이 Core를 통과하게 되고, 그 순간 로그·트레이스·예외
    메시지 어디로든 샐 수 있는 경로가 생긴다(수학 로직 코어 권위·정답 비노출).

    `problem`의 타입이 `Any`인 것은 **배정**이다 — 채점에 필요한 문항 필드가 과목 소유이기
    때문이다(수학은 `answer`·`choices`·`question_format`을 읽고, 역사라면 채점 루브릭을
    읽을 것이다). 구현은 자기가 읽는 최소 필드를 자기 쪽 구조적 Protocol로 좁혀 선언한다
    (수학: `l3.verify_final_answer.ProblemAnswerView`).
    """

    def verify_final_answer(self, student_answer: str, problem: Any) -> FinalAnswerOutcome:
        """3상태 판정. 사유가 필요하면 어댑터 내부 API를 쓴다(Core 계약 아님)."""
        ...


@runtime_checkable
class SealOutcome(Protocol):
    """평가 재료 검증 결과 중 **Core가 읽는 부분** — 상태 + 사유.

    여기서만 `reason`을 노출하는 이유: 이 판정의 소비자는 학생이 아니라 **콘텐츠 파이프라인**
    이고(렌더 검증 신호), 사유가 없으면 무엇이 깨졌는지 모른 채 차단만 하게 된다. 학생에게
    가는 경로가 아니므로 정답 누출 축과 무관하다.
    """

    @property
    def state(self) -> str: ...

    @property
    def reason(self) -> str | None: ...


class AssessmentAnswerVerifier(Protocol):
    """평가 재료(조건식 + 답 매핑)의 답이 조건을 만족하는지 판정하는 능력 — **선택적**.

    상태는 `"pass"`/`"fail"`/`"unverifiable"` 문자열이다(3상태 enum이 아닌 이유: 어댑터의
    기존 어휘를 그대로 쓴다 — 변환 금지). Core는 **fail만 차단**하고 unverifiable은 통과
    시킨다 — 판정 불가를 차단으로 접으면 미검증이 위반으로 위장된다.
    """

    def verify_answer(
        self, conditions: Sequence[str], answer_map: Mapping[str, str]
    ) -> SealOutcome:
        """조건식 집합과 답 매핑을 대조한다."""
        ...


class ExpressionSeal(Protocol):
    """본문 수식이 렌더 후에도 **바이트 동일**하게 남았는지 검사하는 능력 — **선택적**.

    "표현 불변(invariance) 봉인"은 과목마다 대상이 다르다 — 수학은 수식, 역사라면 인용
    원문·연도 표기일 것이다. 그래서 Core는 "봉인 대상을 뽑아라 / 깨졌는지 말하라" 두
    동작만 알고, *무엇이 봉인 대상인가*는 과목이 정한다.
    """

    def extract_sealed(self, source: str) -> str | None:
        """본문에서 봉인 대상을 뽑는다. 없으면 None(검사 대상 아님 — 실패가 아니다)."""
        ...

    def classify_invariance_failure(self, rendered: str, *, sealed: str) -> str | None:
        """봉인이 깨졌으면 사유 코드, 지켜졌으면 None."""
        ...


class AnswerFormVerifier(Protocol):
    """제출답이 문항의 **표기 지시**를 따랐는지 판정하는 능력 — **선택적** (EOS-28).

    형태 어휘는 과목 소유다 — 수학의 `기약분수`는 역사에 없고, 역사라면 "연도를 서기로"
    같은 것이 있을 것이다. 그래서 `answer_constraint`를 `Any`로 받는다: 무엇이 형태 요구로
    적히는지는 과목이 정하고, Core는 **4상태 판정만** 읽는다.

    `FormVerdict`는 값 3상태(`VerificationOutcome`)와 별도 어휘다 — 같은 축을 쪼갠 것이
    아니라 **다른 축**이기 때문이다(형태 위반은 오답이 아니다).
    """

    def verify_answer_form(self, student_answer: str | None, answer_constraint: Any) -> FormVerdict:
        """형태 4상태 판정. 정답을 인자로 받지 않는다 — 받지 않으면 이 경로로 샐 수 없다."""
        ...


class ExpressionEquivalence(Protocol):
    """두 표현의 항등 판정 능력 — **선택적**.

    수학·물리엔 있고 역사엔 없다. 이것이 `SubjectAdapter` 필수 3종에 들어가지 않은 이유다.
    """

    def identity_status(self, lhs: str, rhs: str) -> EquivalenceOutcome:
        """4상태 판정 — `undecidable`/`parse_error`를 합치지 않는다."""
        ...


class AttemptMisconceptionScan(Protocol):
    """시도 1건의 오개념 훑기 결과 — Core가 읽는 **두 가지만**(규칙 2).

    구조적 Protocol이라 어댑터의 리치 타입이 그대로 이것을 만족한다(규칙 1 — 변환 객체 금지).
    Core는 후보의 *내용*(정의·반례·개입 전략)을 모른다 — 코드와 신뢰도만 받고, 내용이 필요하면
    reactive하게 조회한다(구축 플레이북: 오개념 preload 금지).
    """

    @property
    def scan(self) -> MisconceptionScan:
        """훑었는가 — 0건이 *미측정*인지 *측정된 0*인지 구별하는 3상태."""
        ...

    @property
    def candidates(self) -> Sequence[MisconceptionCandidate]:
        """품질 게이트를 통과한 후보. 게이트 미통과분은 여기 실릴 수 없다(계약)."""
        ...


class AttemptMisconceptionDetector(Protocol):
    """채점된 **오답 1건**에서 오개념 후보를 뽑는 능력 — **선택적**.

    왜 `SubjectAdapter` 필수 3종이 아닌가: 필수층의 `detect_misconception`은 *학생이 쓴 서술*을
    본다. 그런데 서술 없이 답만 제출되는 채점 경로가 있고, 거기서 오개념을 읽으려면 **문항과 답을
    함께** 봐야 한다. "문항과 답을 이어 오류 구조를 읽는" 능력이 Physics·Chemistry·History에도
    *반드시* 있다고 단언할 수 없으므로(역사 서술형에 그런 구조가 있는가?), 필수층을 넓히는 대신
    선택층에 좁게 둔다 — `subject_adapter.py`의 (나) Core 확장 금지가 가리키는 자리다.

    Core는 이 능력이 **없을 때의 경로를 반드시 갖는다**: 구현이 없으면 훑지 않은 것이므로
    `MisconceptionScan.NOT_RUN`이고, 그것은 "오개념이 없었다"가 아니다.
    """

    def scan_attempt_answer(
        self, *, question_text: str, student_answer: str | None
    ) -> AttemptMisconceptionScan:
        """오답 1건을 훑어 게이트 통과 후보를 3상태와 함께 돌려준다.

        `question_text`·`student_answer`는 Core에게 **불투명 문자열**이다 — Core는 이 값을
        해석하거나 분기 기준으로 쓰지 않고 그대로 전달만 한다(불투명 페이로드 원칙).

        후보 0건은 정상 응답이다. **없는 오개념을 지어내지 않는다.**
        """
        ...
