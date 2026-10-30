"""P3-09 — 튜터 출력의 구조화 스키마와 검증 게이트: 통과한 응답만 학생에게 나간다.

정본 지시: `docs/strategy/phase3_math_eos_completion_instruction_set.md` [13] P3-09.
보고서: `docs/reviews/p3_09_tutor_output_schema_2026-10-21.md`.

튜터(WH-1 primary)의 LLM 출력은 여러 단계를 거쳐 학생에게 간다. 이 모듈은 단계마다의
**스키마**와 **검증기**를 한 곳에 둔다(정본화). 검증기를 *실제로 경유*하는 서빙 경로(집행 지점):

1. **LLM 원시 출력 → 도구 액션** (`classify_action_payload` · 집행 =
   `LLMTutorPolicy._parse_action`). 깨진 JSON·미지 도구·필수 필드 누락·타입 오류·범위 밖 값
   (`weight` ∉ [0, 1]·NaN·inf)·**학습 상태 권위 주장**(`mastery_update_allowed`가 false가 아님,
   숙달·능력치를 이름에 담은 키)·카탈로그 밖 오개념 id는 **거부**하고 정책의 안전 강등으로 보낸다.
1-b. **환각 개념 id** (집행 = 하네스 `wh1_loop._exec`). `read_student_state`·`query_curriculum`이
   이번 턴 프롬프트에 실린 개념 code 밖의 id를 받으면 **그 도구만 실패**(`ok=False`)하고 턴은
   계속된다 — 무동작 도구의 잘못된 인자 하나로 학생 턴을 닫지 않는다.
2. **학생 대면 튜터 출력** (`TutorTurnOutput` · `build_tutor_output` · 집행 = primary 러너
   (`harness/wh1_primary.py`) 톤필터 직후). 통과 못 하면 러너가 `None`을 돌려줘 코치가 결정론
   Polya 발화를 쓴다.
3. **승격 직전 재검증** (`check_deliverable` · 집행 = `api/coach._wh1_primary_decision_or`).
   러너가 돌려준 문자열과 구조체가 같은지, 구조체가 지금도 스키마를 통과하는지(`model_construct`
   우회 포함)를 *학생 응답 직전에* 본다. 두 세션 핸들러(create·append)가 모두 이 함수를 거친다.

**`mastery_update_allowed`는 언제나 false다.** 타입이 `Literal[False]`(+ `is False` 검사 — 0·`False`
외 동등 값 금지)라 true를 담은 구조체는 생성되지 않고, 서버 빌더는 그 필드에 값을 넘기지 않는다.
LLM이 원시 출력에 true를 실으면 1단계에서 거부된다. 이 필드는 "이 응답으로 학습 상태를 바꾸지
않는다"는 **선언**이며, 실제로 바꾸지 못하게 하는 구조적 집행은 ARCH-59
(`tests/infra/test_llm_state_authority_boundary.py`)가 소유한다.

**진단은 코치가 큐레이션한 활성 가설 세트에서 온다.** `diagnosis.misconception_id`·`confidence`는
러너에 들어온 *초기* 활성 가설(코치가 결정론 매칭·증거로 큐레이션해 영속한 세트 — 응답
`active_hypotheses`와 같은 원천)의 최상위다. 턴 안에서 LLM이 고른 `log_evidence`·`curate_hypothesis`
가 만든 in-memory 세트는 쓰지 않는다 — 그 세트는 LLM이 제출한 증거(가중치 [0, 1]로 범위 제한)의
영향을 받기 때문이다. 카탈로그 밖 id(DB에 남은 구판 id)는 진단 후보에서 건너뛴다(WARNING) — 그 하나
때문에 그 학생의 튜터 발화가 매 턴 거부되지 않게. 개념 id는 이번 턴 코치가 DB에서 PK로 조회한 code만
허용한다. LLM은 진단을 결정하지 않는다.

**미통과 시 학생이 받는 것(교수학적 안전 기본값).** 어느 단계든 거부되면 LLM 문자열은 학생에게 가지
않는다. 1단계 거부는 정책의 안전 강등이 받는다 — 풀이 단계가 있고 미검증이면 `verify_step`을
먼저 돌리고(검증 의무 유지), 이번 턴 판정이 오답·검증 불가면 **격려가 아니라 질문**(하네스
소크라테스 개입·중립 유도)으로, 그 밖에는 격려 템플릿으로 턴을 닫는다. 2·3단계 거부는 코치의 결정론
`PolyaCoach.decide` 발화가 나간다. 어느 쪽도 정답을 담지 않는다. 또한 스키마가 전략과 다음 행동의
**일관성**을 검사한다 — 다시 살펴봐야 하는(`revise_solution`) 턴에 격려(`encouragement`)는 거부된다
(틀렸는데 잘하고 있다고 말하지 않는다 · 부정적 강화도 하지 않는다).

**프라이버시.** 로그·관측에는 사유 코드와 필드 *이름*만 싣는다. 발화 원문·LLM 원문·id 값은
싣지 않는다.
"""

from __future__ import annotations

import logging
import math
import re
import unicodedata
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
    "MAX_EVIDENCE_WEIGHT",
    "REASON_EXPLANATION_MISMATCH",
    "REASON_FIELD_RANGE",
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
    "ExplanationSource",
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
신뢰도·증거 수 조합의 개입 발문 전수)라 그 약 2.5배로 잡았다. 소크라테스 한 턴은 질문 하나다."""

MAX_EVIDENCE_WEIGHT = 1.0
"""LLM이 낼 수 있는 증거 가중치 상한. 코치 경로의 가중치 관례가 전부 [0, 1]이다 — 매칭 증거는
`weight=match.confidence`(0~1), 반박은 `_REFUTE_WEIGHT=0.5`·`_REFUTE_STRONG_WEIGHT=1.0`, 미평가
None은 1.0 취급(`evidence_store.net_support`). 그보다 큰 값은 한 건으로 누적 증거를 뒤집는다."""

_MAX_CONCEPT_ID_CHARS = 120
"""개념 code 상한 — `wh1_tutor_context._MAX_CODE_CHARS`와 같다."""

ResponseStrategy = Literal[
    "guided_question", "guided_hint", "diagnostic_probe", "encouragement", "socratic_requestion"
]
"""응답 전략 닫힌 어휘. 하네스 `end_turn` 행위 유형에서 1:1로 정해진다(LLM 자유 문자열 아님).
`socratic_requestion`은 교수법 팩 금지모드 가드가 발화를 소크라테스 재질문으로 대체한 턴이다."""

NextAction = Literal["continue_dialogue", "revise_solution", "solve_probe"]
"""학생에게 기대하는 다음 행동. 출제 턴=`solve_probe`, 이번 턴 검증 판정이 정답이 아니면
`revise_solution`(오답·검증 불가 — 다시 살펴보기), 그 밖은 `continue_dialogue`."""

ExplanationSource = Literal["llm", "harness_template"]
"""발화 본문의 저자 — `llm`(정책 명시 발화·프로즈 rephrase 산출물)·`harness_template`(하네스 파생
템플릿·소크라테스 개입·안전 강등·금지모드 가드 재질문). 강등 턴도 구조체를 채우므로 둘을 가른다."""

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
REASON_FIELD_RANGE = "FIELD_RANGE"
REASON_STATE_AUTHORITY_CLAIM = "STATE_AUTHORITY_CLAIM"
REASON_UNKNOWN_CONCEPT_ID = "UNKNOWN_CONCEPT_ID"
REASON_UNKNOWN_MISCONCEPTION_ID = "UNKNOWN_MISCONCEPTION_ID"
REASON_UNMAPPED_STRATEGY = "UNMAPPED_STRATEGY"
REASON_MISSING_OUTPUT = "MISSING_OUTPUT"
REASON_EXPLANATION_MISMATCH = "EXPLANATION_MISMATCH"
_REASON_SCHEMA_PREFIX = "SCHEMA_"  # + pydantic 오류 type 대문자(예: SCHEMA_STRING_TOO_LONG)

STATE_AUTHORITY_TOKENS: frozenset[str] = frozenset(
    {"mastery", "proficiency", "ability", "competence"}
)
"""학습 상태 권위를 뜻하는 키 **단어**(ARCH-59 ③ 어휘). 부분 문자열이 아니라 단어로 비교한다 —
`probability`·`capability`는 거짓 양성이다. `skill_level`은 두 단어 연쇄로 따로 본다."""

_STATE_AUTHORITY_BIGRAMS: frozenset[tuple[str, str]] = frozenset({("skill", "level")})
_STATE_AUTHORITY_KO: tuple[str, ...] = ("숙달", "능력치", "숙련도")
"""한국어 키 조각 — 한국어에는 단어 경계 문제가 없어 조각 포함으로 본다."""

_CONTRACT_FIELD = "mastery_update_allowed"

_INVISIBLE_CATEGORIES = frozenset({"Cc", "Cf", "Zs", "Zl", "Zp"})
_HANGUL_FILLERS = frozenset({"ᅟ", "ᅠ", "ㅤ", "ﾠ"})
"""보이지 않는 문자 — 제어·형식(ZWSP·ZWJ·BOM)·공백 범주와 한글 채움 문자(범주는 Lo라 따로 둔다)."""


# ──────────────────────────────────────────────────────────────────────
# 1단계 — LLM 원시 출력(도구 선택 JSON) 검증
# ──────────────────────────────────────────────────────────────────────
def _is_int(value: object) -> bool:
    """JSON 정수 — bool은 int의 하위형이지만 정수로 치지 않는다(`true`가 극성 1로 둔갑 금지)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _key_words(key: str) -> list[str]:
    """키 → 소문자 단어(NFKC·camelCase·구분자 분리·복수형 단수화)."""
    text = unicodedata.normalize("NFKC", key)
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    words = [w for w in re.split(r"[^0-9A-Za-z]+", text.lower()) if w]
    out: list[str] = []
    for word in words:
        if word.endswith("ies") and len(word) > 3:
            word = word[:-3] + "y"
        elif word.endswith("s") and len(word) > 3 and not word.endswith("ss"):
            word = word[:-1]
        out.append(word)
    return out


def _is_state_key(key: str) -> bool:
    words = _key_words(key)
    if any(w in STATE_AUTHORITY_TOKENS for w in words):
        return True
    if any(pair in _STATE_AUTHORITY_BIGRAMS for pair in zip(words, words[1:], strict=False)):
        return True
    normalized = unicodedata.normalize("NFKC", key)
    return any(token in normalized for token in _STATE_AUTHORITY_KO)


def _state_authority_claim(node: object) -> bool:
    """중첩 dict·list를 따라 내려가며 상태 축 키가 있으면 주장이다.

    유일한 예외는 최상위·중첩 어디서든 정확히 `mastery_update_allowed: false`(계약과 같은 값의
    echo)다. NFKC로 접어 비교하므로 전각 표기(`ｍａｓｔｅｒｙ`)도 같은 키로 본다.
    """
    if isinstance(node, Mapping):
        for key, value in node.items():
            key_text = str(key)
            if _is_state_key(key_text):
                folded = unicodedata.normalize("NFKC", key_text)
                if not (folded == _CONTRACT_FIELD and value is False):
                    return True
            if _state_authority_claim(value):
                return True
        return False
    if isinstance(node, list):
        return any(_state_authority_claim(item) for item in node)
    return False


def classify_action_payload(data: Mapping[str, object]) -> str | None:
    """LLM이 고른 도구 JSON(dict)의 스키마 위반 사유 코드 — 통과면 None(순수·결정론).

    판정 순서(먼저 걸린 사유): 상태 권위 주장 → 미지 도구 → 도구별 필수 필드·타입·범위 → 오개념 id
    실재. 선택 필드의 `null`은 부재로 본다(기존 파서와 같다). 무해한 *여분* 키는 거부하지 않는다 —
    액션 타입에 실릴 자리가 없어 버려진다(ARCH-59 ③이 필드 집합을 동결). **개념 id의 실재는 여기서
    보지 않는다** — 하네스가 그 도구만 실패시킨다(`wh1_loop.CONCEPT_ID_REJECT_DETAIL`·턴 계속).
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
        return None
    if kind == "curate_hypothesis":
        turns = data.get("turns_elapsed")
        if turns is None:
            return None
        if not (isinstance(turns, int) and _is_int(turns)):
            return REASON_FIELD_TYPE
        return None if turns >= 0 else REASON_FIELD_RANGE
    if kind == "query_curriculum":
        if data.get("node_id") is None:
            return REASON_MISSING_FIELD
        relation = data.get("relation")
        if not isinstance(data["node_id"], str) or (
            relation is not None and not isinstance(relation, str)
        ):
            return REASON_FIELD_TYPE
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
        if isinstance(weight, (int, float)) and not (
            math.isfinite(weight) and 0.0 <= weight <= MAX_EVIDENCE_WEIGHT
        ):
            return REASON_FIELD_RANGE
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
def _visible_text(value: str) -> str:
    """보이지 않는 문자를 지운 본문 — 남는 것이 없으면 빈 발화다."""
    return "".join(
        ch
        for ch in value
        if unicodedata.category(ch) not in _INVISIBLE_CATEGORIES and ch not in _HANGUL_FILLERS
    )


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
        description=(
            "코치가 큐레이션한 활성 가설의 최상위 오개념 id — 카탈로그 정본(`CATALOG_BY_ID`)에 "
            "있는 id만 허용."
        ),
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

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence_is_a_number(cls, value: object) -> object:
        if value is not None and (isinstance(value, bool) or not _is_number(value)):
            raise ValueError("신뢰도는 bool이 아닌 수")
        return value

    @model_validator(mode="after")
    def _confidence_needs_misconception(self) -> TutorDiagnosis:
        if self.confidence is not None and self.misconception_id is None:
            raise ValueError("오개념 id 없는 신뢰도")
        return self


class TutorTurnOutput(BaseModel):
    """학생에게 나가는 튜터 응답 1턴의 구조화 스키마(P3-09).

    원 문서 제안 필드(`diagnosis{concept_id, misconception_id, confidence}`·`response_strategy`·
    `hint_level`·`explanation`·`next_action`·`mastery_update_allowed`)를 갖고, 발화 저자
    (`explanation_source`)를 더한다. `explanation`이 학생 화면에 나가는 발화 본문이며 코치 응답
    `decision.prompt`와 같은 문자열이다. `hint_level`은 결정론 Polya 엔진이 정한 값을 옮겨 적은
    것이다 — LLM은 힌트 단계를 정하지 않는다.

    `strict`는 문자열·수 형변환을 막지만 `Literal`은 값 동등(`True == 1`·`2.0 == 2`·
    `0 == False`)으로 통과시키므로, `hint_level`·`mastery_update_allowed`에는 타입 검사를 따로 건다.
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
    explanation_source: ExplanationSource = Field(
        description="발화 본문의 저자 — llm(LLM 작성)·harness_template(하네스 결정론 템플릿·강등)."
    )
    next_action: NextAction
    mastery_update_allowed: Literal[False] = Field(
        default=False,
        description=(
            "이 응답이 학습 상태(숙달도)를 바꿔도 되는가 — **항상 false**. LLM은 학습 상태를 "
            "결정하지 않는다(Phase 2 동결 계약). 숙달 갱신은 완료 판정 증거"
            "(`completion_evidence`)를 거친 평가·숙달 엔진만 한다."
        ),
    )

    @field_validator("hint_level", mode="before")
    @classmethod
    def _hint_level_is_int(cls, value: object) -> object:
        if value is not None and not _is_int(value):
            raise ValueError("힌트 단계는 bool이 아닌 정수")
        return value

    @field_validator("mastery_update_allowed", mode="before")
    @classmethod
    def _mastery_is_exactly_false(cls, value: object) -> object:
        if value is not False:
            raise ValueError("mastery_update_allowed는 정확히 False")
        return value

    @field_validator("explanation")
    @classmethod
    def _explanation_has_visible_text(cls, value: str) -> str:
        if not _visible_text(value):
            raise ValueError("보이는 문자가 없는 발화")
        return value

    @model_validator(mode="after")
    def _strategy_and_next_action_agree(self) -> TutorTurnOutput:
        """전략·다음 행동 일관성 — 출제는 출제끼리, 다시 살펴볼 턴에 격려 금지."""
        if (self.response_strategy == "diagnostic_probe") != (self.next_action == "solve_probe"):
            raise ValueError("출제 전략과 다음 행동 불일치")
        if self.next_action == "revise_solution" and self.response_strategy == "encouragement":
            raise ValueError("다시 살펴볼 턴에 격려")
        return self


def _reason_from(exc: ValidationError) -> str:
    """첫 오류의 type을 사유 코드로 — 값·입력 원문은 싣지 않는다."""
    errors = exc.errors(include_input=False, include_context=False, include_url=False)
    first = errors[0]["type"] if errors else "invalid"
    return _REASON_SCHEMA_PREFIX + str(first).upper()


def validate_tutor_output(
    data: Mapping[str, object], *, known_concept_ids: frozenset[str]
) -> TutorTurnOutput | str:
    """dict → 검증된 `TutorTurnOutput`, 또는 거부 사유 코드(str). 예외를 밖으로 내지 않는다.

    `mastery_update_allowed`가 키로 있고 값이 정확히 `False`가 아니면 스키마 오류가 아니라 상태
    권위 주장(`STATE_AUTHORITY_CLAIM`)으로 따로 센다. 진단 개념 id의 실재 대조는 모델 검증자가
    아니라 여기(게이트 함수)에 둔다 — 응답 모델 직렬화처럼 조회 결과를 모르는 자리에서 모델이
    깨지지 않게. `known_concept_ids`가 비면 개념 id를 단 진단은 거부된다(fail-closed).
    """
    if _CONTRACT_FIELD in data and data[_CONTRACT_FIELD] is not False:
        return REASON_STATE_AUTHORITY_CLAIM
    try:
        output = TutorTurnOutput.model_validate(dict(data))
    except ValidationError as exc:
        return _reason_from(exc)
    concept_id = output.diagnosis.concept_id
    if concept_id is not None and concept_id not in known_concept_ids:
        return REASON_UNKNOWN_CONCEPT_ID
    return output


def _top_hypothesis(
    hypotheses: Sequence[MisconceptionHypothesis],
) -> MisconceptionHypothesis | None:
    """카탈로그에 있는 가설 중 최상위 — 신뢰도 내림차순, 같으면 id 오름차순(결정론).

    카탈로그 밖 id(DB에 남은 구판 id)는 건너뛰고 건수를 WARNING으로 남긴다(id 값은 싣지 않는다).
    """
    known = [h for h in hypotheses if h.misconception_id in CATALOG_BY_ID]
    skipped = len(hypotheses) - len(known)
    if skipped:
        logger.warning("튜터 진단 — 카탈로그 밖 가설 %d건 건너뜀(진단 후보 제외)", skipped)
    if not known:
        return None
    return sorted(known, key=lambda h: (-h.confidence, h.misconception_id))[0]


def build_tutor_output(
    *,
    explanation: str,
    explanation_source: ExplanationSource,
    action_type: EndTurnType | None,
    mode_guard_replaced: bool,
    verify_verdict: str | None,
    hypotheses: Sequence[MisconceptionHypothesis],
    concept_id: str | None,
    known_concept_ids: frozenset[str],
    hint_level: int | None,
) -> TutorTurnOutput | str:
    """하네스 턴 결말로 학생 대면 출력을 조립·검증한다 — 통과면 구조체, 아니면 사유 코드.

    값의 출처는 전부 서버다: 발화 = 톤필터 산출물, 전략 = 하네스 행위 유형, 진단 = **코치가
    큐레이션한 초기 활성 가설**과 DB 조회 개념, 힌트 단계 = 결정론 엔진. `mastery_update_allowed`는
    **넘기지 않는다**(기본값 false만). 러너에서는 `concept_id`와 `known_concept_ids`가 같은 원천이라
    개념 대조가 동어반복이지만, 진단 개념의 출처가 바뀌는 순간 거부로 바뀐다 — 출처 고정 장치다.
    """
    if mode_guard_replaced:
        strategy: ResponseStrategy | None = "socratic_requestion"
    else:
        strategy = _STRATEGY_BY_ACTION_TYPE.get(action_type) if action_type is not None else None
    if strategy is None:
        return REASON_UNMAPPED_STRATEGY
    if strategy == "diagnostic_probe":
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
        "explanation_source": explanation_source,
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
    같다. `known_concept_ids`는 **호출자(코치)가 자기 DB 조회로 얻은** 개념 code 집합이다.
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
