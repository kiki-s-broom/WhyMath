"""P3-09 — 튜터 출력의 구조화 스키마와 검증 게이트: 통과한 응답만 학생에게 나간다.

정본 지시: `docs/strategy/phase3_math_eos_completion_instruction_set.md` [13] P3-09. 보고서:
`docs/reviews/p3_09_tutor_output_schema_2026-10-21.md`.

튜터(WH-1 primary)의 LLM 출력은 두 단계로 학생에게 간다. 이 모듈은 두 단계 각각의 **스키마**와
**검증기**를 한 곳에 둔다(정본화). 검증기를 *실제로 경유*하는 서빙 경로(집행 지점)는 아래 셋이다.

1. **LLM 원시 출력 → 도구 액션** (`classify_action_payload` · 집행 =
   `LLMTutorPolicy._parse_action`). LLM이 내는 것은 "다음 도구 하나"를 고르는 JSON이다. 깨진
   JSON·미지 도구·필수 필드 누락·타입 오류·**학습 상태 권위 주장**(`mastery_update_allowed`가
   false가 아님, 숙달·능력치를 이름에 담은 키)·이번 턴에 받지 않은 개념 id·카탈로그에 없는 오개념
   id는 **거부**하고 정책의 안전 강등(결정론)으로 보낸다. 거부 사유 코드는 WARNING 로그와 관측
   레코드(`llm_output_rejections`)에 남는다.
2. **학생 대면 튜터 출력** (`TutorTurnOutput` · `build_tutor_output` · 집행 = primary
   러너(`harness/wh1_primary.py`) 톤필터 직후). 학생에게 갈 발화를 진단·전략·다음 행동과 함께
   구조체로 만들고 검증한다. 통과 못 하면 러너가 `None`을 돌려줘 코치가 결정론 Polya 발화를 쓴다.
3. **승격 직전 재검증** (`check_deliverable` · 집행 = `api/coach._wh1_primary_decision_or`). 러너가
   돌려준 문자열과 구조체가 같은지, 구조체가 지금도 스키마를 통과하는지(`model_construct` 우회
   포함)를 *학생 응답 직전에* 한 번 더 본다. 두 세션 핸들러(create·append)가 모두 이 함수를 거친다.

**`mastery_update_allowed`는 언제나 false다.** 타입이 `Literal[False]`라 true를 담은 구조체는
생성되지 않고, 서버 빌더는 그 필드에 값을 *넘기지 않는다*(기본값만). LLM이 원시 출력에 true를
실으면 1단계에서 거부된다. 이 필드는 "이 응답으로 학습 상태를 바꾸지 않는다"는 **선언**이며, 실제로
바꾸지 못하게 하는 구조적 집행은 ARCH-59(`tests/infra/test_llm_state_authority_boundary.py` — 튜터
경로에 mastery writer 0·발화 승격은 `prompt` 한 키)가 소유한다. 둘이 함께 있어야 "LLM은 학습 상태를
결정하지 않는다"(Phase 2 동결 계약)가 응답 계약과 코드 양쪽에 선다.

**진단 id의 실재 확인.** 진단의 `concept_id`는 이번 턴 코치가 **DB에서 PK로 조회한** 개념 code
(`api/coach._concept_label_for` → `TutorContentSummary.concept.code`)만 허용하고,
`misconception_id`는 오개념 카탈로그 정본(`l4.misconception.catalog.CATALOG_BY_ID` — `log_evidence`
증거 게이트와 같은 권위)에 있는 id만 허용한다. 진단 값은 LLM이 아니라 서버(하네스 가설 세트·DB
조회)가 채운다 — LLM은 진단을 *결정하지 않는다*.

**미통과 시 학생이 받는 것(교수학적 안전 기본값).** 어느 단계든 거부되면 LLM 문자열은 학생에게 가지
않는다. 1단계 거부는 정책의 안전 강등이 받는다 — 풀이 단계가 있고 미검증이면 `verify_step`을 먼저
돌리고(검증 의무 유지), 아니면 하네스 격려 템플릿(`ENCOURAGE_FALLBACK_UTTERANCE`)으로 턴을 닫는다.
2·3단계 거부는 코치의 결정론 `PolyaCoach.decide` 발화(Polya 단계 질문)가 나간다. 어느 쪽도 정답을
담지 않는다 — 파생 템플릿·Polya 발문은 구조적으로 정답 문자열이 없다(정답 직접 제공 금지 유지).

**프라이버시.** 로그·관측에는 사유 코드와 필드 *이름*만 싣는다. 발화 원문·LLM 원문·id 값은 싣지
않는다.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from whymath_backend.harness.wh1_loop import EndTurnType
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.l4.misconception.hypothesis import MisconceptionHypothesis

__all__ = [
    "MAX_EXPLANATION_CHARS",
    "REASON_EXPLANATION_MISMATCH",
    "REASON_FIELD_TYPE",
    "REASON_MISSING_FIELD",
    "REASON_MISSING_OUTPUT",
    "REASON_NOT_JSON_OBJECT",
    "REASON_STATE_AUTHORITY_CLAIM",
    "REASON_UNKNOWN_CONCEPT_ID",
    "REASON_UNKNOWN_KIND",
    "REASON_UNKNOWN_MISCONCEPTION_ID",
    "REASON_UNMAPPED_STRATEGY",
    "STATE_AUTHORITY_TOKENS",
    "TUTOR_OUTPUT_SCHEMA_VERSION",
    "NextAction",
    "ResponseStrategy",
    "TutorDiagnosis",
    "TutorOutputReceipt",
    "TutorTurnOutput",
    "build_tutor_output",
    "check_deliverable",
    "classify_action_payload",
    "validate_tutor_output",
]

logger = logging.getLogger("whymath.harness.wh1_tutor_output")

TUTOR_OUTPUT_SCHEMA_VERSION: Final = "tutor-output-v1"
"""스키마 판 — 필드 의미가 바뀌면 판을 올린다(클라이언트가 판으로 해석 분기)."""

MAX_EXPLANATION_CHARS = 400
"""학생 대면 발화 길이 상한. 하네스 파생 발화 최장이 163자(2026-10-21 실측: 카탈로그 72종 × 가설
신뢰도·증거 수 조합의 개입 발문 전수)라 그 약 2.5배로 잡았다. 소크라테스 한 턴은 질문 하나다 —
이보다 긴 LLM 발화는 독백·풀이 전개로 보고 거부한다(정답 누설 표면 축소)."""

_MAX_CONCEPT_ID_CHARS = 120
"""개념 code 상한 — `wh1_tutor_context._MAX_CODE_CHARS`와 같다(그보다 긴 code는 요약에 실리지
않는다)."""

ResponseStrategy = Literal[
    "guided_question", "guided_hint", "diagnostic_probe", "encouragement", "socratic_requestion"
]
"""응답 전략 닫힌 어휘. 하네스 `end_turn` 행위 유형에서 1:1로 정해진다(LLM 자유 문자열 아님).
`socratic_requestion`은 교수법 팩 금지모드 가드가 발화를 소크라테스 재질문으로 대체한 턴이다."""

NextAction = Literal["continue_dialogue", "revise_solution", "solve_probe"]
"""학생에게 기대하는 다음 행동. 출제 턴=`solve_probe`, 이번 턴 검증 판정이 정답이 아니면
`revise_solution`(오답·검증 불가 — 다시 살펴보기), 그 밖은 `continue_dialogue`."""

_STRATEGY_BY_ACTION_TYPE: dict[str, ResponseStrategy] = {
    "질문": "guided_question",
    "힌트": "guided_hint",
    "출제": "diagnostic_probe",
    "격려": "encouragement",
}

# ── 거부 사유 코드(닫힌 어휘·로그/관측에 그대로 실린다·값 미포함) ─────────────
REASON_NOT_JSON_OBJECT = "NOT_JSON_OBJECT"
REASON_UNKNOWN_KIND = "UNKNOWN_KIND"
REASON_MISSING_FIELD = "MISSING_FIELD"
REASON_FIELD_TYPE = "FIELD_TYPE"
REASON_STATE_AUTHORITY_CLAIM = "STATE_AUTHORITY_CLAIM"
REASON_UNKNOWN_CONCEPT_ID = "UNKNOWN_CONCEPT_ID"
REASON_UNKNOWN_MISCONCEPTION_ID = "UNKNOWN_MISCONCEPTION_ID"
REASON_UNMAPPED_STRATEGY = "UNMAPPED_STRATEGY"
REASON_MISSING_OUTPUT = "MISSING_OUTPUT"
REASON_EXPLANATION_MISMATCH = "EXPLANATION_MISMATCH"
_REASON_SCHEMA_PREFIX = "SCHEMA_"  # + pydantic 오류 type 대문자(예: SCHEMA_STRING_TOO_LONG)

STATE_AUTHORITY_TOKENS: tuple[str, ...] = (
    "mastery",
    "proficiency",
    "ability",
    "skill_level",
    "competence",
)
"""학습 상태 권위를 뜻하는 키 이름 조각 — ARCH-59 ③(`_STATE_AUTHORITY_TOKENS`)과 같은 어휘다.
LLM 원시 출력의 *키*에 이것이 들어 있으면 상태 결정 주장으로 보고 거부한다. 유일한 예외는
`mastery_update_allowed: false`(계약과 같은 값의 echo — 무해)다."""

_CONTRACT_FIELD = "mastery_update_allowed"


# ──────────────────────────────────────────────────────────────────────
# 1단계 — LLM 원시 출력(도구 선택 JSON) 검증
# ──────────────────────────────────────────────────────────────────────
def _is_int(value: object) -> bool:
    """JSON 정수 — bool은 int의 하위형이지만 정수로 치지 않는다(`true`가 극성 1로 둔갑 금지)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: object) -> bool:
    return (isinstance(value, (int, float))) and not isinstance(value, bool)


def _state_authority_claim(data: Mapping[str, object]) -> bool:
    """키 이름에 학습 상태 축이 있으면 주장이다 — `mastery_update_allowed: false`만 예외."""
    for key, value in data.items():
        lowered = key.lower()
        if not any(token in lowered for token in STATE_AUTHORITY_TOKENS):
            continue
        if key == _CONTRACT_FIELD and value is False:
            continue
        return True
    return False


def classify_action_payload(
    data: Mapping[str, object], *, known_concept_ids: frozenset[str] = frozenset()
) -> str | None:
    """LLM이 고른 도구 JSON(dict)의 스키마 위반 사유 코드 — 통과면 None(순수·결정론).

    판정 순서(먼저 걸린 사유): 상태 권위 주장 → 미지 도구 → 도구별 필수 필드·타입 → id 실재.
    `known_concept_ids`는 이번 턴 프롬프트에 실린(DB에서 조회한) 개념 code 집합이다 — LLM이 받은
    적 없는 개념 id는 환각이다. 오개념 id는 카탈로그 정본에서 확인한다. 선택 필드의 `null`은
    부재로 본다(기존 파서와 같다). 미지의 *여분* 키는 거부하지 않는다 — 액션 타입에 실릴 자리가
    없어 버려지며(ARCH-59 ③이 필드 집합을 동결), 상태 축 키만 위 규칙으로 따로 거부한다.
    """
    if _state_authority_claim(data):
        return REASON_STATE_AUTHORITY_CLAIM
    kind = data.get("kind")
    if kind in ("match_misconception", "verify_step", "select_probe"):
        return None  # 필드 없음 — 민감 인자는 정책 보유값으로 채운다.
    if kind == "read_student_state":
        node_ids = data.get("node_ids")
        if node_ids is None:
            return None
        if not isinstance(node_ids, list) or not all(
            isinstance(n, str) and n.strip() for n in node_ids
        ):
            return REASON_FIELD_TYPE
        if any(n not in known_concept_ids for n in node_ids):
            return REASON_UNKNOWN_CONCEPT_ID
        return None
    if kind == "curate_hypothesis":
        turns = data.get("turns_elapsed")
        if turns is not None and not (isinstance(turns, int) and _is_int(turns) and turns >= 0):
            return REASON_FIELD_TYPE
        return None
    if kind == "query_curriculum":
        if "node_id" not in data or data["node_id"] is None:
            return REASON_MISSING_FIELD
        node_id = data["node_id"]
        relation = data.get("relation")
        if not isinstance(node_id, str) or (relation is not None and not isinstance(relation, str)):
            return REASON_FIELD_TYPE
        if node_id not in known_concept_ids:
            return REASON_UNKNOWN_CONCEPT_ID
        return None
    if kind == "log_evidence":
        if data.get("misconception_id") is None or data.get("polarity") is None:
            return REASON_MISSING_FIELD
        weight = data.get("weight")
        if (
            not isinstance(data["misconception_id"], str)
            or not _is_int(data["polarity"])
            or (weight is not None and not _is_number(weight))
        ):
            return REASON_FIELD_TYPE
        if data["misconception_id"] not in CATALOG_BY_ID:
            return REASON_UNKNOWN_MISCONCEPTION_ID
        return None
    if kind == "end_turn":
        if data.get("action_type") is None:
            return REASON_MISSING_FIELD
        utterance = data.get("utterance")
        if not isinstance(data["action_type"], str) or (
            utterance is not None and not isinstance(utterance, str)
        ):
            return REASON_FIELD_TYPE
        return None
    return REASON_UNKNOWN_KIND


# ──────────────────────────────────────────────────────────────────────
# 2단계 — 학생 대면 튜터 출력 스키마
# ──────────────────────────────────────────────────────────────────────
class TutorDiagnosis(BaseModel):
    """이번 턴 진단 — 서버가 채운다(LLM 결정 아님). 셋 다 None이면 '진단 없음'이다."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    concept_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=_MAX_CONCEPT_ID_CHARS,
        description="이번 문항의 PRIMARY 개념 code — 이번 턴 DB에서 조회한 값만 허용.",
    )
    misconception_id: str | None = Field(
        default=None,
        description="활성 가설 최상위 오개념 id — 카탈로그 정본(`CATALOG_BY_ID`)에 있는 id만 허용.",
    )
    confidence: float | None = Field(
        default=None, ge=0.0, le=1.0, description="그 가설의 신뢰도(0~1). 오개념 id가 없으면 None."
    )

    @field_validator("misconception_id")
    @classmethod
    def _misconception_exists(cls, value: str | None) -> str | None:
        if value is not None and value not in CATALOG_BY_ID:
            raise ValueError("카탈로그에 없는 오개념 id")
        return value

    @model_validator(mode="after")
    def _confidence_needs_misconception(self) -> TutorDiagnosis:
        if self.confidence is not None and self.misconception_id is None:
            raise ValueError("오개념 id 없는 신뢰도")
        return self


class TutorTurnOutput(BaseModel):
    """학생에게 나가는 튜터 응답 1턴의 구조화 스키마(P3-09).

    원 문서 제안 필드(`diagnosis{concept_id, misconception_id, confidence}`·`response_strategy`·
    `hint_level`·`explanation`·`next_action`·`mastery_update_allowed`)를 그대로 갖는다.
    `explanation`이 학생 화면에 나가는 발화 본문이며 코치 응답 `decision.prompt`와 같은 문자열이다.
    `hint_level`은 결정론 Polya 엔진(`PedagogyDecision.hint_level`)이 정한 값을 옮겨 적은 것이다 —
    LLM은 힌트 단계를 정하지 않는다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["tutor-output-v1"] = TUTOR_OUTPUT_SCHEMA_VERSION
    diagnosis: TutorDiagnosis = Field(default_factory=TutorDiagnosis)
    response_strategy: ResponseStrategy
    hint_level: Literal[1, 2, 3, 4] | None = Field(
        default=None,
        description="결정론 Polya 엔진이 정한 답 미루기 단계(1~4). 엔진 미경유면 None.",
    )
    explanation: str = Field(
        min_length=1,
        max_length=MAX_EXPLANATION_CHARS,
        description=(
            "학생 대면 발화 본문 — 하네스 verify 의무·정답 억제·프로즈 게이트·톤필터 통과분."
        ),
    )
    next_action: NextAction
    mastery_update_allowed: Literal[False] = Field(
        default=False,
        description=(
            "이 응답이 학습 상태(숙달도)를 바꿔도 되는가 — **항상 false**. LLM은 학습 상태를 "
            "결정하지 "
            "않는다(Phase 2 동결 계약). 숙달 갱신은 완료 판정 증거(`completion_evidence`)를 거친 "
            "평가·숙달 엔진만 한다."
        ),
    )

    @field_validator("explanation")
    @classmethod
    def _explanation_has_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("빈 발화")
        return value


def _reason_from(exc: ValidationError) -> str:
    """첫 오류의 type을 사유 코드로 — 값·입력 원문은 싣지 않는다."""
    errors = exc.errors(include_input=False, include_context=False, include_url=False)
    first = errors[0]["type"] if errors else "invalid"
    return _REASON_SCHEMA_PREFIX + str(first).upper()


def validate_tutor_output(
    data: Mapping[str, object], *, known_concept_ids: frozenset[str]
) -> TutorTurnOutput | str:
    """dict → 검증된 `TutorTurnOutput`, 또는 거부 사유 코드(str). 예외를 밖으로 내지 않는다.

    `mastery_update_allowed`가 false가 아니면(키가 있고 값이 정확히 `False`가 아님) 스키마 오류가
    아니라
    상태 권위 주장(`STATE_AUTHORITY_CLAIM`)으로 따로 센다 — 관측에서 두 부류를 가르기 위해서다.
    """
    if _CONTRACT_FIELD in data and data[_CONTRACT_FIELD] is not False:
        return REASON_STATE_AUTHORITY_CLAIM
    try:
        output = TutorTurnOutput.model_validate(dict(data))
    except ValidationError as exc:
        return _reason_from(exc)
    # 진단 개념 id는 `known_concept_ids`(이번 턴 DB 조회 결과) 안에만 있다. 집합이 비면 개념 id를 단
    # 진단은 거부된다(확인할 수 없는 id를 통과시키지 않는다·fail-closed). 이 대조는 모델 검증자가
    # 아니라
    # 여기(게이트 함수)에 둔다 — 응답 모델 직렬화·재검증처럼 조회 결과를 모르는 자리에서 모델이
    # 스스로
    # 깨지지 않게 하고, 실재 확인은 게이트를 경유한 경로에서만 일어나게 한다.
    concept_id = output.diagnosis.concept_id
    if concept_id is not None and concept_id not in known_concept_ids:
        return REASON_UNKNOWN_CONCEPT_ID
    return output


def _top_hypothesis(
    hypotheses: Sequence[MisconceptionHypothesis],
) -> MisconceptionHypothesis | None:
    """최상위 가설 — 신뢰도 내림차순, 같으면 id 오름차순(결정론)."""
    if not hypotheses:
        return None
    return sorted(hypotheses, key=lambda h: (-h.confidence, h.misconception_id))[0]


def build_tutor_output(
    *,
    explanation: str,
    action_type: EndTurnType | None,
    mode_guard_replaced: bool,
    verify_verdict: str | None,
    hypotheses: Sequence[MisconceptionHypothesis],
    concept_id: str | None,
    known_concept_ids: frozenset[str],
    hint_level: int | None,
) -> TutorTurnOutput | str:
    """하네스 턴 결말로 학생 대면 출력을 조립·검증한다 — 통과면 구조체, 아니면 사유 코드.

    값의 출처는 전부 서버다: 발화=톤필터 산출물, 전략=하네스 행위 유형, 진단=하네스 가설 세트·DB
    조회
    개념, 힌트 단계=결정론 엔진. `mastery_update_allowed`는 **넘기지 않는다**(기본값 false만).
    `known_concept_ids`는 이번 턴 DB에서 조회한 개념 code 집합이다(정책이 프롬프트에 실은 것과 같은
    원천). 러너에서는 `concept_id`와 같은 원천이라 이 대조가 동어반복이지만, 진단 개념의 출처가
    바뀌는 순간(예: LLM이 고른 id를 싣는 리팩터) 거부로 바뀐다 — 출처 고정 장치다.
    """
    if mode_guard_replaced:
        strategy: ResponseStrategy | None = "socratic_requestion"
    else:
        strategy = _STRATEGY_BY_ACTION_TYPE.get(action_type) if action_type is not None else None
    if strategy is None:
        return REASON_UNMAPPED_STRATEGY
    if action_type == "출제" and not mode_guard_replaced:
        next_action: NextAction = "solve_probe"
    elif verify_verdict in ("incorrect", "unverifiable"):
        next_action = "revise_solution"
    else:
        next_action = "continue_dialogue"
    top = _top_hypothesis(hypotheses)
    payload: dict[str, object] = {
        "diagnosis": {
            "concept_id": concept_id,
            "misconception_id": top.misconception_id if top is not None else None,
            "confidence": top.confidence if top is not None else None,
        },
        "response_strategy": strategy,
        "hint_level": hint_level,
        "explanation": explanation,
        "next_action": next_action,
    }
    return validate_tutor_output(payload, known_concept_ids=known_concept_ids)


# ──────────────────────────────────────────────────────────────────────
# 3단계 — 승격 직전 재검증
# ──────────────────────────────────────────────────────────────────────
@dataclass
class TutorOutputReceipt:
    """러너가 채우는 출력 영수증 — 검증을 통과한 구조체만 담긴다(거부·폴백 턴은 None)."""

    output: TutorTurnOutput | None = None


def check_deliverable(
    output: TutorTurnOutput | None, *, utterance: str, known_concept_ids: frozenset[str]
) -> str | None:
    """학생 응답 직전 재검증 — 통과면 None, 아니면 사유 코드(값 미포함).

    ① 구조체가 있다 ② 지금도 스키마를 통과한다(`model_construct`로 우회 생성된 객체·
    `mastery_update_allowed=True` 포함 — dump 후 재검증) ③ 승격할 문자열이 구조체의 `explanation`과
    같다(러너가 돌려준 문자열과 구조체가 갈라지지 않았다). `known_concept_ids`는 **호출자(코치)가
    자기 DB 조회로 얻은** 개념 code 집합이다 — 러너가 만든 진단 개념이 그 밖이면 거부한다(추가
    조회 0).
    """
    if output is None:
        return REASON_MISSING_OUTPUT
    revalidated = validate_tutor_output(output.model_dump(), known_concept_ids=known_concept_ids)
    if isinstance(revalidated, str):
        return revalidated
    if revalidated.mastery_update_allowed is not False:  # 타입이 막지만 런타임에서 한 번 더.
        return REASON_STATE_AUTHORITY_CLAIM
    if revalidated.explanation != utterance:
        return REASON_EXPLANATION_MISMATCH
    return None
