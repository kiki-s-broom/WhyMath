"""독립 다관점 LLM 교차검증 — 기계 불가 잔여의 검출기(S4-13 ②).

정본: `docs/architecture/problem_bank_gap_review.md` §3 D7 — "기계 불가 잔여는 **독립 다관점
LLM 교차검증**(생성자≠검증자·K≥3·**원리 다른 프롬프트**, S3 축 준용) + Wilson 표본 검수
게이트(S5 축)". 초인간 검증 §2 S3(독립 다관점)의 LLM 판(`equivalent/retag.py`가 결정론
독립 감사의 선례라면, 이쪽은 결정론으로 닫히지 않는 축의 판).

**이 모듈은 게이트가 아니라 검출기다.** 판정(exit 0/1)은 `harness/residue_cross_verify_eval`
의 Wilson 표본 검수 게이트가 내린다. 여기 결과는 그 게이트의 *감사 라벨 입력*이다 —
검증 권위 서열 ②("측정 통과 기계 게이트")를 경유하지 않은 LLM 의견은 그 자체로 권위가 없다.

────────────────────────────────────────────────────────────────────────────
독립성을 무엇으로 보장하는가 (K개 같은 프롬프트는 독립이 아니다)
────────────────────────────────────────────────────────────────────────────
독립성을 *선언*하지 않고 **구성 시점에 기계로 강제**한다(`_assert_independent`). 세 축이
모두 달라야 관점으로 인정된다:

  1. **원리(principle)** — 무엇을 하는 행위인가가 다르다. 재풀이 / 반증 / 번역대조.
  2. **시스템 프롬프트** — 역할·출력 계약이 다르다(동일 문자열 금지).
  3. **가시 필드(visible_fields)** — *보는 정보가 다르다*. 이것이 핵심이다. 답을 본 관점과
     답을 못 본 관점은 같은 오류에 걸리지 않는다(앵커링 공유 차단). 세 관점의 가시 필드
     집합이 하나라도 겹치면(동일 집합) 구성이 거부된다.

추가로 **생성자≠검증자**를 구조로 강제한다 — 대상은 자신을 만든 주체 서명(`authored_by`)을
들고 오고, 검증자는 자기 서명과 충돌하면 검증을 거부한다(`IndependenceError`). 서명은 3상태다
(`assert_author_independent`): `llm:<모델 id>`(검증자 서명과 비교)·`deterministic:<생성기>`(LLM
생성자 없음 — 비교 대상 아님을 명시 선언)·그 밖(기록 없음 — 독립성 입증 불가라 **거부**). 두 서명은
같은 조립 함수(`llm_author`)로 만들어져야 비교가 성립한다 — 형식이 서로 다르면 가드가 한 번도
발화하지 못한다(PB-15: 코퍼스 `corpus:<유형>` vs 검증자 `llm:<모델>`).

────────────────────────────────────────────────────────────────────────────
K=3 기본 관점(원리가 다르다)
────────────────────────────────────────────────────────────────────────────
① `independent_reconstruction` (독립 재구성) — **발문만** 보여주고 표본공간 크기·유리한
   경우의 수를 스스로 세게 한다. 답·해설·형식모델은 은닉(앵커링 차단). **판정은 기계가**
   한다 — LLM 숫자 vs 전수 열거 숫자의 일치. LLM은 의견이 아니라 *독립 재계산*을 낸다.
② `adversarial_falsification` (적대적 반증) — 발문+답을 주고 "이 문항은 결함이 있다고
   가정하고 근거를 찾아라"로 시작한다(6축 ②적대성). 조건 결측·중의성·복수 정답·등확률
   가정 미명시를 노린다. 형식모델은 은닉(모델을 보면 발문의 빈틈을 모델로 메워 읽는다).
③ `model_grounding` (서술-형식모델 정합) — 발문 + *기계가 실제로 검산한 모델의 한국어
   풀어쓰기*를 나란히 주고 **오직 번역 일치만** 판정한다(수치 계산 금지·답 은닉). 기계가
   못 하는 잔여의 정확히 그 지점 — "기계가 발문과 다른 문제를 풀지 않았는가".

7계층: L3 지역. 라우터·provider·trace만 쓴다(CLAUDE.md "LLM 호출은 항상 라우터 경유").
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from whymath_backend.config import Settings
from whymath_backend.l3.data_grade_defaults import SELF_AUTHORED_CORPUS
from whymath_backend.l3.escalation_defaults import default_student_escalation_signals
from whymath_backend.l3.exact_value import parse_exact_value
from whymath_backend.l3.interfaces import LLMProvider, TraceSink
from whymath_backend.l3.models import (
    CallSite,
    CostTier,
    RoutingDecision,
    RoutingRequest,
    Usage,
)
from whymath_backend.l3.pipeline import served_cloud_seat
from whymath_backend.l3.pregenerate.provenance_bridge import model_name_for_decision
from whymath_backend.l3.prompt_assets import fill, prompt_text
from whymath_backend.l3.router import (
    Router,
    actual_cost_krw,
    langfuse_fields,
)

# 학생 요청 라우팅 신호 기본값 — 6개 호출부 공용 단일 좌석(OPS-18, `api/visualization.py` 미러).
_STUDENT_ESCALATION_DEFAULTS = default_student_escalation_signals()

__all__ = [
    "CrossVerificationResult",
    "CrossVerifier",
    "DETERMINISTIC_AUTHOR_PREFIX",
    "IndependenceError",
    "LLM_AUTHOR_PREFIX",
    "MISSING_CONDITION_PERSPECTIVES",
    "MULTIPLE_VALID_ANSWERS_PERSPECTIVES",
    "PROBABILITY_PERSPECTIVES",
    "SEQUENCE_PERSPECTIVES",
    "STATISTICAL_PERSPECTIVES",
    "UNRECORDED_AUTHOR",
    "Perspective",
    "PerspectiveVerdict",
    "ResidueSubject",
    "AuthorDeclarationConflictError",
    "assert_author_independent",
    "deterministic_author",
    "llm_author",
    "resolve_author_signature",
]

_LOGGER = logging.getLogger(__name__)

# 관점 최소 개수 — D7 명세의 K≥3. 이보다 적은 구성은 "다관점"이 아니다.
MIN_PERSPECTIVES = 3

ResidueVerdictLabel = Literal["ok", "defect", "unclear"]

# 관점이 볼 수 있는 `ResidueSubject` 필드 이름 — 가시 집합의 정의역(오타로 은닉이 새는 것 방어).
# 기계 계산값(machine_total·machine_favorable)은 *판정 재료*이지 프롬프트 노출 대상이 아니라
# 여기 없다 — ①의 대조는 기계가 하지 LLM에게 정답 숫자를 보여주지 않는다.
_FIELD_NAMES = frozenset(
    {"question_text", "answer", "answer_explanation", "machine_model_ko", "data"}
)


@dataclass(frozen=True, slots=True)
class ResidueSubject:
    """교차검증 대상 — 기계가 닫은 축(수치)과 닫지 못한 축(서술)의 재료를 함께 든다.

    `authored_by`는 이 문항을 만든 주체의 서명이다 — `llm_author(모델 id)` 또는
    `deterministic_author(생성기)`로 조립한다(형식·3상태 의미는 `assert_author_independent`).
    검증자는 자기 서명과 충돌하면 검증을 거부한다 — 생성자≠검증자의 구조적 강제.
    `data`는 통계 자료형처럼 원본 자료 문자열이 필요한 도메인용 선택적 필드.
    `machine_value_exact`는 기계 계산값의 **정확값 문자열**(정수 `73`·유리수 `1/2`·목록
    `[1, 3, 6]`) — float인 `machine_value`는 2⁵³ 초과 정수를 무손실로 못 싣는다(S4-66).
    빈 문자열이면 정확값이 없다(기존 도메인 전부).
    """

    problem_id: str
    question_text: str
    answer: str
    answer_explanation: str
    machine_model_ko: str
    machine_total: int
    machine_favorable: int
    authored_by: str
    data: str = ""
    machine_value: float | None = None
    machine_value_exact: str = ""


@dataclass(frozen=True, slots=True)
class PerspectiveVerdict:
    """관점 1개의 판정 — ok(결함 없음)/defect(결함 지목)/unclear(판정 실패·측정 실패)."""

    principle: str
    verdict: ResidueVerdictLabel
    defect_class: str
    reason: str


@dataclass(frozen=True, slots=True)
class Perspective:
    """관점 1개 — 원리·시스템 프롬프트·가시 필드·렌더·판정을 한 묶음으로.

    `judge`는 LLM 응답 JSON을 받아 판정으로 바꾼다. ①처럼 *기계가* 판정하는 관점은 여기서
    대상의 기계 계산값과 대조한다(LLM은 의견이 아니라 재계산을 제공).
    """

    principle: str
    system_prompt: str
    visible_fields: frozenset[str]
    render: Callable[[ResidueSubject], str]
    judge: Callable[[ResidueSubject, Mapping[str, object]], PerspectiveVerdict]


class IndependenceError(RuntimeError):
    """독립성 위반 — 관점 구성이 겹치거나 생성자와 검증자가 같은 주체(자기승인)."""


# ──────────────────────────────────────────────────────────────────────────
# 생성자 서명(author identity) — 형식의 단일 출처 (PB-15)
# ──────────────────────────────────────────────────────────────────────────
# 생성자≠검증자 가드는 두 문자열이 *같은 함수로 조립됐을 때만* 작동한다. 검증자 서명과 저작 측
# 서명이 각자 다른 곳에서 조립되면(종전: 검증자 `llm:<모델>`·코퍼스 `corpus:<유형>`) 두 값은
# 같아질 수 없고 가드는 한 번도 발화하지 못한다 — 그래서 조립 지점을 여기 하나로 모은다.
#
# 서명은 3상태다. "모른다"를 "아니다"로 접지 않는다:
#   `llm:<모델 id>`           LLM이 만들었다 → 검증자 서명과 비교한다(같으면 자기승인).
#   `deterministic:<생성기>`  LLM 생성자가 없다(결정론 템플릿·열거) → 비교 대상이 아님을
#                             *명시적으로 선언*한 값. 빈 문자열·임의 접두어는 이 자리가 아니다.
#   그 밖(`unknown` 포함)     기록이 없다 → 독립성을 입증할 수 없으므로 거부한다(fail-closed).
LLM_AUTHOR_PREFIX = "llm:"
DETERMINISTIC_AUTHOR_PREFIX = "deterministic:"
# 저작 기록이 없는 대상(구 코퍼스·`ProblemVerifyInput` 기본값)의 서명 — 가드가 거부하는 값이다.
UNRECORDED_AUTHOR = "unknown"


def _compose_author(prefix: str, name: str) -> str:
    """접두어 + 이름 조립 — 이름이 비면 서명을 만들지 않는다(빈 값으로 가드를 우회하는 길 차단)."""
    if not name.strip():
        raise ValueError(f"{prefix!r} 서명의 이름이 비었다 — 빈 값으로는 서명을 만들 수 없다")
    return f"{prefix}{name}"


def llm_author(model_id: str) -> str:
    """LLM 서명 `llm:<모델 id>` — 검증자 서명과 저작 측이 이 함수를 같이 쓴다."""
    return _compose_author(LLM_AUTHOR_PREFIX, model_id)


def deterministic_author(generator: str) -> str:
    """결정론 생성기 서명 `deterministic:<생성기>` — LLM 생성자가 없음을 명시 선언한다."""
    return _compose_author(DETERMINISTIC_AUTHOR_PREFIX, generator)


def _author_payload(authored_by: str, prefix: str) -> str | None:
    """`prefix` 뒤의 이름(공백 제거) — 접두어가 다르거나 이름이 비면 None(판독 불가)."""
    if not authored_by.startswith(prefix):
        return None
    payload = authored_by[len(prefix) :].strip()
    return payload or None


class AuthorDeclarationConflictError(IndependenceError):
    """저작 선언(`--authored-by`)이 코퍼스가 기록한 서명과 충돌 — 기록을 선언으로 뒤집을 수 없다."""


def resolve_author_signature(recorded: str, declared: str | None) -> str:
    """기록된 서명과 사람의 선언을 합쳐 *가드에 넘길* 서명을 정한다 (PB-17 재판정).

    선언은 **기록 없음(`UNRECORDED_AUTHOR`)만 채운다**. 기록이 있는 레코드를 선언으로 뒤집을 수
    있으면 LLM 저작분을 `deterministic:`으로 선언해 생성자≠검증자 가드를 우회할 수 있다(종전
    `declared or recorded`가 그 구멍이었다). 규칙:
      - 선언 없음(None·공백) → 기록 그대로.
      - 기록 없음 → 선언으로 채운다.
      - 기록 있음 + 선언이 같음(표기 차이 무시) → 기록 그대로(무해한 중복).
      - 기록 있음 + 선언이 다름 → `AuthorDeclarationConflictError`(조용히 무시하지 않고 거부한다 —
        무시하면 사람은 선언이 먹혔다고 믿고 측정을 해석한다).
    """
    if declared is None or not declared.strip():
        return recorded
    if recorded == UNRECORDED_AUTHOR:
        return declared
    if recorded.strip().casefold() == declared.strip().casefold():
        return recorded
    raise AuthorDeclarationConflictError(
        f"저작 선언({declared!r})이 코퍼스가 기록한 서명({recorded!r})과 충돌한다 — 기록이 있는 "
        "레코드는 선언으로 덮어쓸 수 없다(선언은 '기록 없음'만 채운다). 선언을 빼거나 "
        "코퍼스의 기록을 먼저 정정하라."
    )


def assert_author_independent(authored_by: str, verifier_signature: str) -> None:
    """생성자≠검증자 — 3상태 판정. 자기승인과 판독 불가 서명은 `IndependenceError`.

    LLM 서명은 대소문자·앞뒤 공백을 무시하고 비교한다 — 사람이 `--authored-by`로 손으로 쓴
    값(`llm:Qwen3:30b-a3b`)이 표기 차이만으로 가드를 비껴가면 안 된다. 접두어 자체는 정확히
    일치해야 한다(`LLM:`·` llm:`은 판독 불가 → 거부).
    """
    llm_name = _author_payload(authored_by, LLM_AUTHOR_PREFIX)
    if llm_name is not None:
        if authored_by.strip().casefold() == verifier_signature.strip().casefold():
            raise IndependenceError(f"생성자와 검증자가 같은 주체({authored_by}) — 자기승인 금지")
        return
    if _author_payload(authored_by, DETERMINISTIC_AUTHOR_PREFIX) is not None:
        return  # LLM 생성자가 없다고 명시 선언된 대상 — 자기승인이 성립할 수 없다.
    raise IndependenceError(
        f"생성자 서명을 판독할 수 없다({authored_by!r}) — 독립성을 입증할 수 없어 거부한다"
        f"(fail-closed). '{LLM_AUTHOR_PREFIX}<모델 id>' 또는 "
        f"'{DETERMINISTIC_AUTHOR_PREFIX}<생성기>' 형식으로 저작 기록을 남겨라."
    )


# ──────────────────────────────────────────────────────────────────────────
# 관점 ① 독립 재구성 — 발문만 보고 스스로 센다(판정은 기계)
# ──────────────────────────────────────────────────────────────────────────
_SYSTEM_RECONSTRUCT = prompt_text("l3.cross_verify.reconstruct_system")


def _render_reconstruct(subject: ResidueSubject) -> str:
    """가시 필드 = 발문뿐. 정답·해설·형식 모델은 여기 없다(은닉 = 앵커링 차단)."""
    return fill(
        prompt_text("l3.cross_verify.reconstruct_user"), QUESTION_TEXT=subject.question_text
    )


def _judge_reconstruct(subject: ResidueSubject, data: Mapping[str, object]) -> PerspectiveVerdict:
    """LLM이 독립적으로 센 수 vs 기계 전수 열거 수 — **기계가** 판정한다."""
    total = data.get("total")
    favorable = data.get("favorable")
    if not isinstance(total, int) or not isinstance(favorable, int):
        return PerspectiveVerdict(
            principle="independent_reconstruction",
            verdict="unclear",
            defect_class="reconstruction_declined",
            reason=f"독립 재구성 실패(표본공간 미확정): {data.get('reason', '사유 미제시')}",
        )
    if total == subject.machine_total and favorable == subject.machine_favorable:
        return PerspectiveVerdict(
            principle="independent_reconstruction",
            verdict="ok",
            defect_class="",
            reason=f"독립 재구성 일치({favorable}/{total}).",
        )
    return PerspectiveVerdict(
        principle="independent_reconstruction",
        verdict="defect",
        defect_class="model_mismatch",
        reason=(
            f"독립 재구성 불일치 — 재계산 {favorable}/{total} vs 기계 전수 "
            f"{subject.machine_favorable}/{subject.machine_total}. 발문이 기계가 검산한 "
            "형식 모델과 다르게 읽힐 소지."
        ),
    )


# ──────────────────────────────────────────────────────────────────────────
# 관점 ② 적대적 반증 — 결함이 있다고 가정하고 근거를 찾는다
# ──────────────────────────────────────────────────────────────────────────
_SYSTEM_FALSIFY = prompt_text("l3.cross_verify.falsify_system")


def _render_falsify(subject: ResidueSubject) -> str:
    """가시 필드 = 발문 + 제시된 정답(형식 모델은 은닉 — 모델을 보면 빈틈을 모델로 메워 읽는다)."""
    return fill(
        prompt_text("l3.cross_verify.falsify_user"),
        QUESTION_TEXT=subject.question_text,
        ANSWER=subject.answer,
    )


# ──────────────────────────────────────────────────────────────────────────
# 관점 ③ 서술-형식모델 정합 — 번역 대조만(수치 계산 금지)
# ──────────────────────────────────────────────────────────────────────────
_SYSTEM_GROUNDING = prompt_text("l3.cross_verify.grounding_system")


def _render_grounding(subject: ResidueSubject) -> str:
    """가시 필드 = 발문 + 기계 형식 모델(정답은 은닉 — 번역 일치만 판정하므로 답이 필요 없다)."""
    return fill(
        prompt_text("l3.cross_verify.grounding_user"),
        QUESTION_TEXT=subject.question_text,
        MACHINE_MODEL_KO=subject.machine_model_ko,
    )


def _judge_labelled(
    principle: str,
) -> Callable[[ResidueSubject, Mapping[str, object]], PerspectiveVerdict]:
    """`verdict` 라벨을 직접 내는 관점(②③)의 공용 판정기 — 미지 라벨은 unclear(단정 금지)."""

    def judge(subject: ResidueSubject, data: Mapping[str, object]) -> PerspectiveVerdict:
        del subject  # 라벨형 관점은 대상 재참조 없이 응답만으로 판정된다.
        raw = data.get("verdict")
        reason = str(data.get("reason", "")).strip() or "사유 미제시"
        defect_class = str(data.get("defect_class", "")).strip() or "unspecified"
        if raw == "ok":
            return PerspectiveVerdict(principle, "ok", "", reason)
        if raw == "defect":
            return PerspectiveVerdict(principle, "defect", defect_class, reason)
        return PerspectiveVerdict(
            principle,
            "unclear",
            "verdict_unparsed",
            f"판정 라벨을 읽을 수 없음(verdict={raw!r}) — 측정 실패로 기록.",
        )

    return judge


def _judge_defect_class(
    principle: str, *, expected_defect_class: str
) -> Callable[[ResidueSubject, Mapping[str, object]], PerspectiveVerdict]:
    """결함류 전용 관점(v4)의 판정기 — 응답이 결함류를 비워 두면 기대 결함류로 메운다.

    일반 관점(②③)은 "무엇이 결함인지"를 LLM이 자유롭게 분류하지만, v4 관점은 *애초에 한
    결함류만 겨냥해 구성된* 관점이다. 그래서 응답이 `defect_class`를 비워 보내도 집계
    라벨이 `unspecified`로 흐려질 이유가 없다 — 구성이 이미 결함류를 고정했다.

    응답이 자기 결함류를 적어 보냈으면 **덮어쓰지 않는다**. LLM이 더 좁은 하위 분류를
    지목한 것이므로 그 정보를 지우면 오히려 손실이다.

    주의: `_judge_labelled`은 결함류 미기재를 `"unspecified"` 센티넬로 *정규화한 뒤* 넘기므로,
    "비어 있음" 판정은 정규화된 결과가 아니라 **원본 응답(`data`)**을 다시 본다. 정규화 결과만
    보면 이 분기는 영원히 닫혀 있는 죽은 코드가 된다(CLAUDE.md "작동 신호 없는 알고리즘 부착 금지").
    """
    base = _judge_labelled(principle)

    def judge(subject: ResidueSubject, data: Mapping[str, object]) -> PerspectiveVerdict:
        verdict = base(subject, data)
        if verdict.verdict != "defect":
            return verdict
        if str(data.get("defect_class", "")).strip():
            return verdict  # 응답이 스스로 분류했다 — 그대로 둔다(하위 분류 허용).
        return PerspectiveVerdict(principle, "defect", expected_defect_class, verdict.reason)

    return judge


PROBABILITY_PERSPECTIVES: tuple[Perspective, ...] = (
    Perspective(
        principle="independent_reconstruction",
        system_prompt=_SYSTEM_RECONSTRUCT,
        visible_fields=frozenset({"question_text"}),
        render=_render_reconstruct,
        judge=_judge_reconstruct,
    ),
    Perspective(
        principle="adversarial_falsification",
        system_prompt=_SYSTEM_FALSIFY,
        visible_fields=frozenset({"question_text", "answer"}),
        render=_render_falsify,
        judge=_judge_labelled("adversarial_falsification"),
    ),
    Perspective(
        principle="model_grounding",
        system_prompt=_SYSTEM_GROUNDING,
        visible_fields=frozenset({"question_text", "machine_model_ko"}),
        render=_render_grounding,
        judge=_judge_labelled("model_grounding"),
    ),
)
"""파일럿(확률 유한 전수형) 기본 K=3 관점 — 원리·프롬프트·가시 필드가 모두 다르다."""

# ──────────────────────────────────────────────────────────────────────────
# 관점 ④~⑥ 통계 자료형 — 독립 재계산 / 반증 / 발문↔자료↔통계량 정합
# ──────────────────────────────────────────────────────────────────────────
_SYSTEM_STAT_RECONSTRUCT = prompt_text("l3.cross_verify.statistical_reconstruct_system")
_SYSTEM_STAT_FALSIFY = prompt_text("l3.cross_verify.statistical_falsify_system")
_SYSTEM_STAT_GROUNDING = prompt_text("l3.cross_verify.statistical_grounding_system")


def _render_stat_reconstruct(subject: ResidueSubject) -> str:
    """가시 필드 = 발문 + 데이터. 정답·해설·기계 계산값은 은닉(앵커링 차단)."""
    return fill(
        prompt_text("l3.cross_verify.statistical_reconstruct_user"),
        QUESTION_TEXT=subject.question_text,
        DATA=subject.data,
    )


def _render_stat_falsify(subject: ResidueSubject) -> str:
    """가시 필드 = 발문 + 데이터 + 제시된 정답."""
    return fill(
        prompt_text("l3.cross_verify.statistical_falsify_user"),
        QUESTION_TEXT=subject.question_text,
        DATA=subject.data,
        ANSWER=subject.answer,
    )


def _render_stat_grounding(subject: ResidueSubject) -> str:
    """가시 필드 = 발문 + 데이터 + 기계가 검산한 통계량 설명."""
    return fill(
        prompt_text("l3.cross_verify.statistical_grounding_user"),
        QUESTION_TEXT=subject.question_text,
        DATA=subject.data,
        MACHINE_STAT_KO=subject.machine_model_ko,
    )


def _parse_numeric_value(raw: object) -> float | None:
    """LLM 재계산 값 파싱 — 정수·실수·'a/b' 분수를 float로."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        text = raw.strip().replace(" ", "")
        if "/" in text:
            try:
                num, den = text.split("/", 1)
                return float(num) / float(den)
            except ValueError:
                return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _judge_stat_reconstruct(
    subject: ResidueSubject, data: Mapping[str, object]
) -> PerspectiveVerdict:
    """LLM이 독립적으로 계산한 통계량 vs 기계 계산값 — **기계가** 판정한다."""
    raw_value = data.get("value")
    if raw_value is None:
        return PerspectiveVerdict(
            principle="statistical_reconstruction",
            verdict="unclear",
            defect_class="reconstruction_declined",
            reason=f"독립 재계산 실패: {data.get('reason', '사유 미제시')}",
        )
    llm_value = _parse_numeric_value(raw_value)
    if llm_value is None:
        return PerspectiveVerdict(
            principle="statistical_reconstruction",
            verdict="unclear",
            defect_class="value_unparsed",
            reason=f"재계산 값을 숫자로 읽을 수 없음(value={raw_value!r}).",
        )
    if subject.machine_value is None:
        return PerspectiveVerdict(
            principle="statistical_reconstruction",
            verdict="unclear",
            defect_class="machine_value_missing",
            reason="기계 계산값이 없어 대조 불가.",
        )
    if math.isclose(llm_value, subject.machine_value, rel_tol=1e-9, abs_tol=1e-9):
        return PerspectiveVerdict(
            principle="statistical_reconstruction",
            verdict="ok",
            defect_class="",
            reason=f"독립 재계산 일치({llm_value}).",
        )
    return PerspectiveVerdict(
        principle="statistical_reconstruction",
        verdict="defect",
        defect_class="model_mismatch",
        reason=(
            f"독립 재계산 불일치 — 재계산 {llm_value} vs 기계 계산 "
            f"{subject.machine_value}. 발문이 기계가 검산한 자료·통계량과 다르게 읽힐 소지."
        ),
    )


STATISTICAL_PERSPECTIVES: tuple[Perspective, ...] = (
    Perspective(
        principle="statistical_reconstruction",
        system_prompt=_SYSTEM_STAT_RECONSTRUCT,
        visible_fields=frozenset({"question_text", "data"}),
        render=_render_stat_reconstruct,
        judge=_judge_stat_reconstruct,
    ),
    Perspective(
        principle="statistical_falsification",
        system_prompt=_SYSTEM_STAT_FALSIFY,
        visible_fields=frozenset({"question_text", "data", "answer"}),
        render=_render_stat_falsify,
        judge=_judge_labelled("statistical_falsification"),
    ),
    Perspective(
        principle="statistical_grounding",
        system_prompt=_SYSTEM_STAT_GROUNDING,
        visible_fields=frozenset({"question_text", "data", "machine_model_ko"}),
        render=_render_stat_grounding,
        judge=_judge_labelled("statistical_grounding"),
    ),
)
"""통계 자료형 K=3 관점 — 원리·프롬프트·가시 필드가 모두 다르다."""

# ──────────────────────────────────────────────────────────────────────────
# 관점 ⑦~⑨ 수열 귀납 — 독립 재전개 / 반증 / 발문↔점화식 정합 (S4-66)
# ──────────────────────────────────────────────────────────────────────────
# 관점 ①은 발문만 본다 — 발문에서 초기항·점화식을 스스로 읽어 내는 번역이 잔여 축의 본체이므로
# 정의(DSL)를 보여 주면 그 번역이 빠진다. 값 대조는 **기계가 `Fraction` 정확 일치로** 한다.
_SYSTEM_SEQ_RECONSTRUCT = prompt_text("l3.cross_verify.sequence_reconstruct_system")
_SYSTEM_SEQ_FALSIFY = prompt_text("l3.cross_verify.sequence_falsify_system")
_SYSTEM_SEQ_GROUNDING = prompt_text("l3.cross_verify.sequence_grounding_system")


def _render_seq_reconstruct(subject: ResidueSubject) -> str:
    """가시 필드 = 발문뿐. 정답·해설·기계 정의·기계 계산값은 은닉(앵커링 차단)."""
    return fill(
        prompt_text("l3.cross_verify.sequence_reconstruct_user"),
        QUESTION_TEXT=subject.question_text,
    )


def _render_seq_falsify(subject: ResidueSubject) -> str:
    """가시 필드 = 발문 + 제시된 정답(기계 정의는 은닉 — 보면 발문의 빈틈을 정의로 메워 읽는다)."""
    return fill(
        prompt_text("l3.cross_verify.sequence_falsify_user"),
        QUESTION_TEXT=subject.question_text,
        ANSWER=subject.answer,
    )


def _render_seq_grounding(subject: ResidueSubject) -> str:
    """가시 필드 = 발문 + 기계가 실행한 수열 정의(계산 결과 값은 정의에 없다 — 번역 대조 전용)."""
    return fill(
        prompt_text("l3.cross_verify.sequence_grounding_user"),
        QUESTION_TEXT=subject.question_text,
        MACHINE_MODEL_KO=subject.machine_model_ko,
    )


def _judge_seq_reconstruct(
    subject: ResidueSubject, data: Mapping[str, object]
) -> PerspectiveVerdict:
    """LLM 재전개 값 vs 기계 정확값 — **기계가** `Fraction` 정확 일치(`==`)로 판정한다.

    통계 판정기(`_judge_stat_reconstruct`)는 `math.isclose`라 정수 오답(1073741823 vs
    1073741824)이 통과한다(설계서 §6.1·§8.3 C4) — 그래서 그것을 재사용하지 않고 신설했다.
    """
    principle = "sequence_reconstruction"
    raw_value = data.get("value")
    if raw_value is None:
        return PerspectiveVerdict(
            principle=principle,
            verdict="unclear",
            defect_class="reconstruction_declined",
            reason=f"독립 재전개 실패: {data.get('reason', '사유 미제시')}",
        )
    llm_value = parse_exact_value(raw_value)
    if llm_value is None:
        return PerspectiveVerdict(
            principle=principle,
            verdict="unclear",
            defect_class="value_unparsed",
            reason=f"재전개 값을 정수·p/q·목록으로 읽을 수 없음(value={str(raw_value)[:40]!r}).",
        )
    machine_value = parse_exact_value(subject.machine_value_exact)
    if machine_value is None:
        return PerspectiveVerdict(
            principle=principle,
            verdict="unclear",
            defect_class="machine_value_missing",
            reason="기계 정확값이 없어 대조 불가.",
        )
    if llm_value == machine_value:
        return PerspectiveVerdict(
            principle=principle,
            verdict="ok",
            defect_class="",
            reason="독립 재전개 정확 일치.",
        )
    return PerspectiveVerdict(
        principle=principle,
        verdict="defect",
        defect_class="model_mismatch",
        reason=(
            "독립 재전개 불일치 — 발문에서 읽은 수열의 값이 기계가 실행한 정의의 값과 "
            "정확히 다르다. 발문이 기계 정의와 다르게 읽힐 소지."
        ),
    )


SEQUENCE_PERSPECTIVES: tuple[Perspective, ...] = (
    Perspective(
        principle="sequence_reconstruction",
        system_prompt=_SYSTEM_SEQ_RECONSTRUCT,
        visible_fields=frozenset({"question_text"}),
        render=_render_seq_reconstruct,
        judge=_judge_seq_reconstruct,
    ),
    Perspective(
        principle="sequence_falsification",
        system_prompt=_SYSTEM_SEQ_FALSIFY,
        visible_fields=frozenset({"question_text", "answer"}),
        render=_render_seq_falsify,
        judge=_judge_labelled("sequence_falsification"),
    ),
    Perspective(
        principle="sequence_grounding",
        system_prompt=_SYSTEM_SEQ_GROUNDING,
        visible_fields=frozenset({"question_text", "machine_model_ko"}),
        render=_render_seq_grounding,
        judge=_judge_labelled("sequence_grounding"),
    ),
)
"""수열 귀납 K=3 관점 — 원리·프롬프트·가시 필드가 모두 다르다."""


# ──────────────────────────────────────────────────────────────────────────
# v4 — 결함류별 적대적 검증 관점 (missing_condition / multiple_valid_answers)
# ──────────────────────────────────────────────────────────────────────────
# ①~⑥이 "어떤 결함이든 있으면 찾아라"라면, v4는 D7 잔여 축 검출에서 병목이 된 **두 결함류를
# 겨냥한 전용 K=3 묶음**이다. 위 관점들과 별개로 쓰이며(`Verifier`가 도메인별로 고른다), 함께
# 돌릴 수도 있다.
#
# 설계 요지 — **solver가 아니라 adversarial verifier다.** 모든 v4 프롬프트는 문제를 *푸는*
# 것이 목표가 아니라 "문제 서술의 빈틈·대안 해석을 **증명하는** 것"이 목표다. 정답을 맞히는
# 능력이 아니라 *반례를 구성하는* 능력을 요구하므로, 모델이 문제를 잘 풀지 못해도 결함 지목은
# 성립한다(6축 ②적대성). 판정 라벨은 LLM이 내지만 그 라벨은 권위가 아니라 **게이트의 감사
# 라벨 입력**이다(모듈 docstring 참조).
#
# ⚠️ 알려진 간극(회수 시점 기록 · 이식 중 발견) — **선언된 가시 필드 ⊋ 실제 렌더 필드**.
# `_assert_independent`는 K개 관점의 `visible_fields` *집합이 서로 다를 것*을 요구하는데,
# v4의 A2·A3·D3은 사용자 템플릿이 발문(+정답)만 싣는데도 `answer`/`answer_explanation`을
# 함께 선언해 그 검사를 통과한다. 즉 이 세 관점에서 "보는 정보가 다르다" 축은 *명목*이고,
# 실제로 다른 것은 원리와 시스템 프롬프트 두 축이다(그 둘은 실질적으로 다르다 — 체크리스트
# / 재구성 역추론 / 학생 대안 읽기). 정본 프롬프트를 고치지 않는 범위에서는 해소할 수 없어
# (정직하게 좁히면 세 집합이 모두 `{question_text}`로 같아져 구성이 거부된다) 브랜치 원안을
# 그대로 이식하되 여기에 명시한다 — 침묵으로 넘기면 "독립 3축 충족"이라는 거짓 주장이 된다.
# 해소 방향: 정본 사용자 템플릿에 해당 필드를 실제로 싣거나(그러면 선언이 참이 된다),
# 가시 필드 축 대신 *질의 대상*으로 독립성을 재정의한다. 후속 태스크 대상.
#
# 결함류 A: 필요조건 결측 — 유일한 해를 위해 필요한 조건이 발문에 명시돼 있는가.
_SYSTEM_MISSING_CONDITION_CHECKLIST = prompt_text(
    "l3.cross_verify.missing_condition_checklist_system"
)
_SYSTEM_MISSING_CONDITION_MODEL_GROUNDING = prompt_text(
    "l3.cross_verify.missing_condition_model_grounding_system"
)
_SYSTEM_MISSING_CONDITION_STUDENT_READING = prompt_text(
    "l3.cross_verify.missing_condition_student_reading_system"
)


def _render_missing_condition_checklist(subject: ResidueSubject) -> str:
    """가시 필드 = 발문뿐 — 필요조건 목록을 발문만 보고 세운다(정답 앵커링 차단)."""
    return fill(
        prompt_text("l3.cross_verify.missing_condition_checklist_user"),
        QUESTION_TEXT=subject.question_text,
    )


def _render_missing_condition_model_grounding(subject: ResidueSubject) -> str:
    """가시 필드 = 발문 + 기계 모델 서술. 기계 모델이 *전제하는* 조건 중 발문이 말하지
    않는 것을 역으로 캐게 한다 — 1차 강등전이 전건 놓친(0/3) 축을 직접 조준한다.

    정답을 보여주지 않는 것이 핵심이다. 정답을 보면 모델이 그 값을 정당화하는 방향으로
    사후 합리화하므로(앵커링), 조건 결측 탐지에는 정답이 독이다.
    """
    return fill(
        prompt_text("l3.cross_verify.missing_condition_model_grounding_user"),
        QUESTION_TEXT=subject.question_text,
        MACHINE_MODEL_KO=subject.machine_model_ko,
    )


def _render_missing_condition_student_reading(subject: ResidueSubject) -> str:
    """가시 필드 = 발문 + 해설. 해설이 *의도한* 읽기와 학생이 할 법한 *다른 읽기*를
    대조시킨다 — 정답 수치는 주지 않으므로 값 앵커링은 없다."""
    return fill(
        prompt_text("l3.cross_verify.missing_condition_student_reading_user"),
        QUESTION_TEXT=subject.question_text,
        ANSWER_EXPLANATION=subject.answer_explanation,
    )


MISSING_CONDITION_PERSPECTIVES: tuple[Perspective, ...] = (
    Perspective(
        principle="missing_condition_checklist",
        system_prompt=_SYSTEM_MISSING_CONDITION_CHECKLIST,
        visible_fields=frozenset({"question_text"}),
        render=_render_missing_condition_checklist,
        judge=_judge_defect_class(
            "missing_condition_checklist", expected_defect_class="missing_condition"
        ),
    ),
    Perspective(
        principle="missing_condition_model_grounding",
        system_prompt=_SYSTEM_MISSING_CONDITION_MODEL_GROUNDING,
        visible_fields=frozenset({"question_text", "machine_model_ko"}),
        render=_render_missing_condition_model_grounding,
        judge=_judge_defect_class(
            "missing_condition_model_grounding", expected_defect_class="missing_condition"
        ),
    ),
    Perspective(
        principle="missing_condition_student_reading",
        system_prompt=_SYSTEM_MISSING_CONDITION_STUDENT_READING,
        visible_fields=frozenset({"question_text", "answer_explanation"}),
        render=_render_missing_condition_student_reading,
        judge=_judge_defect_class(
            "missing_condition_student_reading", expected_defect_class="missing_condition"
        ),
    ),
)
"""결함류 A(필요조건 결측) 전용 K=3 관점 — 체크리스트 / 재구성 역추론 / 학생 대안 읽기."""


# 결함류 D: 복수 정답 — 제시된 정답 외의 합리적 해석에서 다른 답이 나오는가.
_SYSTEM_MULTIPLE_ANSWERS_COUNTEREXAMPLE = prompt_text(
    "l3.cross_verify.multiple_valid_answers_counterexample_system"
)
_SYSTEM_MULTIPLE_ANSWERS_ALTERNATIVE_MODEL = prompt_text(
    "l3.cross_verify.multiple_valid_answers_alternative_model_system"
)
_SYSTEM_MULTIPLE_ANSWERS_BOUNDARY = prompt_text(
    "l3.cross_verify.multiple_valid_answers_boundary_system"
)


def _render_multiple_answers_counterexample(subject: ResidueSubject) -> str:
    """가시 필드 = 발문 + 정답 — 조건 하나를 달리 읽어 *다른 답을 실제로 계산*하게 한다."""
    return fill(
        prompt_text("l3.cross_verify.multiple_valid_answers_counterexample_user"),
        QUESTION_TEXT=subject.question_text,
        ANSWER=subject.answer,
    )


def _render_multiple_answers_alternative_model(subject: ResidueSubject) -> str:
    """가시 필드 = 발문 + 해설 — 해설이 쓴 모델 외의 대안 확률 모델을 찾는다(정답 은닉)."""
    return fill(
        prompt_text("l3.cross_verify.multiple_valid_answers_alternative_model_user"),
        QUESTION_TEXT=subject.question_text,
        ANSWER_EXPLANATION=subject.answer_explanation,
    )


def _render_multiple_answers_boundary(subject: ResidueSubject) -> str:
    """가시 필드 = 발문 + 정답 + 해설. 결정적 문구를 빼거나 뒤집어 경계를 흔들고, 그
    변경이 해설이 전제한 해석을 실제로 깨뜨리는지까지 대조시킨다."""
    return fill(
        prompt_text("l3.cross_verify.multiple_valid_answers_boundary_user"),
        QUESTION_TEXT=subject.question_text,
        ANSWER=subject.answer,
        ANSWER_EXPLANATION=subject.answer_explanation,
    )


MULTIPLE_VALID_ANSWERS_PERSPECTIVES: tuple[Perspective, ...] = (
    Perspective(
        principle="multiple_valid_answers_counterexample",
        system_prompt=_SYSTEM_MULTIPLE_ANSWERS_COUNTEREXAMPLE,
        visible_fields=frozenset({"question_text", "answer"}),
        render=_render_multiple_answers_counterexample,
        judge=_judge_defect_class(
            "multiple_valid_answers_counterexample",
            expected_defect_class="multiple_valid_answers",
        ),
    ),
    Perspective(
        principle="multiple_valid_answers_alternative_model",
        system_prompt=_SYSTEM_MULTIPLE_ANSWERS_ALTERNATIVE_MODEL,
        visible_fields=frozenset({"question_text", "answer_explanation"}),
        render=_render_multiple_answers_alternative_model,
        judge=_judge_defect_class(
            "multiple_valid_answers_alternative_model",
            expected_defect_class="multiple_valid_answers",
        ),
    ),
    Perspective(
        principle="multiple_valid_answers_boundary",
        system_prompt=_SYSTEM_MULTIPLE_ANSWERS_BOUNDARY,
        visible_fields=frozenset({"question_text", "answer", "answer_explanation"}),
        render=_render_multiple_answers_boundary,
        judge=_judge_defect_class(
            "multiple_valid_answers_boundary",
            expected_defect_class="multiple_valid_answers",
        ),
    ),
)
"""결함류 D(복수 정답) 전용 K=3 관점 — 반례 생성 / 대안 모델 탐색 / 경계조건 테스트."""


@dataclass(frozen=True, slots=True)
class CrossVerificationResult:
    """대상 1건의 교차검증 결과 — 관점별 판정 + 집계.

    집계 규칙(보수적 — "검증 없이 학생에게 제공 금지"):
      - 하나라도 `defect` → **defect**(반증 우선. 다수결이 아니다 — 결함 지목은 다수결로
        덮이지 않는다).
      - 그 외 하나라도 `unclear` → **unclear**(*측정 실패*이며 통과가 아니다).
      - 전 관점 `ok` → **ok**(만장일치만 통과).
    """

    problem_id: str
    verdicts: tuple[PerspectiveVerdict, ...]
    aggregate: ResidueVerdictLabel
    defect_class: str
    reason: str


def _aggregate(problem_id: str, verdicts: Sequence[PerspectiveVerdict]) -> CrossVerificationResult:
    defects = [v for v in verdicts if v.verdict == "defect"]
    if defects:
        first = defects[0]
        return CrossVerificationResult(
            problem_id=problem_id,
            verdicts=tuple(verdicts),
            aggregate="defect",
            defect_class=f"{first.principle}:{first.defect_class}",
            reason=" | ".join(f"[{v.principle}] {v.reason}" for v in defects),
        )
    unclear = [v for v in verdicts if v.verdict == "unclear"]
    if unclear:
        first = unclear[0]
        return CrossVerificationResult(
            problem_id=problem_id,
            verdicts=tuple(verdicts),
            aggregate="unclear",
            defect_class=f"{first.principle}:{first.defect_class}",
            reason=" | ".join(f"[{v.principle}] {v.reason}" for v in unclear),
        )
    return CrossVerificationResult(
        problem_id=problem_id,
        verdicts=tuple(verdicts),
        aggregate="ok",
        defect_class="",
        reason=f"K={len(verdicts)} 관점 만장일치 ok.",
    )


def _assert_independent(perspectives: Sequence[Perspective], min_k: int) -> None:
    """관점 구성의 독립성을 *구성 시점에* 기계로 강제 — 선언이 아니라 검사."""
    if len(perspectives) < min_k:
        raise IndependenceError(f"관점 수 {len(perspectives)} < 최소 K={min_k}(다관점 아님)")
    principles = [p.principle for p in perspectives]
    if len(set(principles)) != len(principles):
        raise IndependenceError(f"원리 중복 — 같은 원리 반복은 독립이 아님: {principles}")
    prompts = [p.system_prompt for p in perspectives]
    if len(set(prompts)) != len(prompts):
        raise IndependenceError("시스템 프롬프트 중복 — 같은 프롬프트 K회는 독립이 아님")
    fields = [p.visible_fields for p in perspectives]
    if len(set(fields)) != len(fields):
        raise IndependenceError(
            "가시 필드 집합 중복 — 같은 정보를 보는 관점은 같은 앵커링을 공유해 독립이 아님"
        )
    for perspective in perspectives:
        unknown = perspective.visible_fields - _FIELD_NAMES
        if unknown:
            raise IndependenceError(f"미지 가시 필드 {sorted(unknown)}({perspective.principle})")


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(raw: str) -> dict[str, object] | None:
    """코드펜스·주변 산문을 허용하는 관대 파싱(llm_generator `_extract_json` 동형)."""
    match = _JSON_BLOCK.search(raw)
    if match is None:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


class CrossVerifier:
    """독립 다관점 LLM 교차검증기 — 라우터 경유·관측 기록·생성자≠검증자 강제.

    provider 주입(테스트=결정론 fake). None이면 표준 `CompositeProvider`를 지연 구성한다
    (구성만으로 네트워크 0 — `LLMEquivalentProblemGenerator` 동형).
    """

    def __init__(
        self,
        provider: LLMProvider | None = None,
        *,
        perspectives: Sequence[Perspective] = PROBABILITY_PERSPECTIVES,
        min_perspectives: int = MIN_PERSPECTIVES,
        settings: Settings | None = None,
        trace: TraceSink | None = None,
        subscription: str = _STUDENT_ESCALATION_DEFAULTS.student_subscription,
        difficulty: str = "medium",
    ) -> None:
        _assert_independent(perspectives, min_perspectives)
        if provider is None:
            from whymath_backend.l3.providers.composite import CompositeProvider
            from whymath_backend.l3.providers.factory import build_cloud_provider
            from whymath_backend.l3.providers.ollama import OllamaProvider

            provider = CompositeProvider(local=OllamaProvider(), cloud=build_cloud_provider())
        if trace is None:
            from whymath_backend.l3.trace.langfuse_sink import LangfuseSink

            trace = LangfuseSink(settings=settings)
        self._provider = provider
        self._trace = trace
        self._settings = settings
        self._perspectives = tuple(perspectives)
        self._subscription = subscription
        self._difficulty = difficulty

    # ── 라우팅(호출지점 ⑤ 자기검증 좌석) ────────────────────────────────
    def _routing_request(self) -> RoutingRequest:
        """검증 호출의 라우팅 신호 — task_type='verify'·call_site=⑤.

        호출지점 ⑤는 03a에서 "생성 결과를 *별도 LLM 호출로* 재검토"의 좌석이다(라우터가
        QUALITY 비동기로 보낸다). 이름은 '자기검증'이지만 본 모듈의 대상은 *다른 주체가
        만든* 문항이며 생성자≠검증자를 별도로 강제한다 — 라우팅 좌석만 공유한다.
        """
        return RoutingRequest(
            task_type="verify",
            difficulty=self._difficulty,
            requires_reasoning=True,
            student_subscription=self._subscription,
            budget_krw=_STUDENT_ESCALATION_DEFAULTS.budget_krw,  # 단일 좌석 값(OPS-18·회귀 0)
            call_site=CallSite.SELF_VERIFY,
            sync=False,
            # 등급: 교차검증 대상은 *자체 저작 코퍼스의 문항*이다(2026-09-01 실측 —
            # data/corpus 전 27개 pool이 whymath-original). AIHub 유래 자료가 저작
            # 입력이 되면 `SELF_AUTHORED_CORPUS` 한 자리만 고치면 이 경로도 함께 잠긴다.
            data_licenses=SELF_AUTHORED_CORPUS,
        )

    @property
    def signature(self) -> str:
        """검증자 서명 `llm:<모델 id>` — 생성자 서명과의 충돌 검사에 쓴다.

        모델 id는 저작 측(`LLMEquivalentProblemGenerator`)이 `GenerationLog.model_name`에 쓰는
        `model_name_for_decision`과 **같은 함수**로 해석한다. 종전 판은 로컬만 모델 id를 내고
        클라우드는 티어명(`llm:cloud_mid`)을 냈다 — 저작 측이 모델 핀(`deepseek/…`)을 기록하는
        한 같은 클라우드 모델이 만든 문항을 같은 모델이 검증해도 두 문자열이 같아질 수 없었다.

        **선언값이지 관측값이 아니다**: 설정이 지목한 모델이며, 폴백·프록시 라우팅으로 실제
        응답한 모델이 달라지는 경로는 이 서명이 보지 못한다(`model_name_for_decision` 동일 한계).
        """
        decision = Router().route(self._routing_request())
        return llm_author(model_name_for_decision(decision, settings=self._settings))

    def _record_trace(self, decision: RoutingDecision, usage: Usage | None) -> None:
        """호출 1건의 라우팅·실측을 관측에 남긴다 — never-break(배치 비차단·타입명 로그)."""
        is_cloud = decision.cost_tier != CostTier.LOCAL.value
        # OPS-116 — 단가 좌석은 꽂힌 provider에서 읽는다(생략하면 anthropic 단가로 적혀
        # openrouter 호출이 과대 계상된다). 미상(None)은 anthropic으로 접지 않고 '미측정'.
        seat = served_cloud_seat(self._provider) if is_cloud else None
        if usage is None or (
            is_cloud and (usage.input_tokens is None or usage.output_tokens is None)
        ):
            cost_krw: float | None = None
        else:
            cost_krw = actual_cost_krw(decision, usage, seat=seat)
        try:
            self._trace.record(
                langfuse_fields(
                    decision,
                    cache_hit=False,
                    call_site=CallSite.SELF_VERIFY,
                    usage=usage,
                    cost_krw=cost_krw,
                    cloud_seat=seat,
                )
            )
        except Exception as exc:  # noqa: BLE001 — 관측 장애가 검증 배치를 깨면 안 됨
            _LOGGER.warning("교차검증 관측 기록 실패(%s) — 무시하고 계속", type(exc).__name__)

    # ── 검증 ───────────────────────────────────────────────────────────
    def verify(
        self,
        subject: ResidueSubject,
        perspectives: Sequence[Perspective] | None = None,
    ) -> CrossVerificationResult:
        """대상 1건을 K개 관점으로 교차검증. 관점 실패는 unclear(측정 실패·통과 아님).

        `perspectives`가 주어지면 해당 관점 집합을, 아니면 인스턴스 기본 관점을 사용한다.
        도메인별 관점 분기는 `Verifier`가 담당한다.

        동기 API로 유지하면서 async provider 호출은 내부에서 새 이벤트 루프를 열어 실행한다.
        호출부가 이미 async loop 안에 있을 경우 `asyncio.to_thread()`로 격리해 충돌을 피한다.
        """
        assert_author_independent(subject.authored_by, self.signature)
        perspectives_to_use = self._perspectives if perspectives is None else perspectives
        decision = Router().route(self._routing_request())
        return asyncio.run(self._verify_async(subject, decision, perspectives_to_use))

    async def _verify_async(
        self,
        subject: ResidueSubject,
        decision: RoutingDecision,
        perspectives: Sequence[Perspective],
    ) -> CrossVerificationResult:
        """관점별 판정을 순차 await하고 집계한다."""
        verdicts: list[PerspectiveVerdict] = []
        for perspective in perspectives:
            verdict = await self._run_perspective(perspective, subject, decision)
            verdicts.append(verdict)
        return _aggregate(subject.problem_id, verdicts)

    async def _run_perspective(
        self, perspective: Perspective, subject: ResidueSubject, decision: RoutingDecision
    ) -> PerspectiveVerdict:
        try:
            generated = await self._provider.generate(
                perspective.render(subject),
                perspective.system_prompt,
                decision,
            )
        except Exception as exc:  # noqa: BLE001 — provider 장애로 배치가 죽으면 안 됨
            # 침묵 실패 금지 — 예외 *타입명*을 사유에 남긴다(값·시크릿은 제외).
            _LOGGER.warning(
                "교차검증 provider 호출 실패(%s·%s) — unclear 기록",
                perspective.principle,
                type(exc).__name__,
            )
            return PerspectiveVerdict(
                perspective.principle,
                "unclear",
                "provider_error",
                f"provider 호출 실패({type(exc).__name__}) — 측정 실패로 기록.",
            )
        self._record_trace(decision, generated.usage)
        data = _extract_json(generated.text)
        if data is None:
            return PerspectiveVerdict(
                perspective.principle,
                "unclear",
                "response_unparsed",
                "응답에서 JSON을 읽을 수 없음 — 측정 실패로 기록.",
            )
        return perspective.judge(subject, data)

    def flush_trace(self) -> None:
        """배치 종료 시 관측 전송 확정 — flush 없는 sink는 조용히 통과(계약 밖 표면)."""
        flush = getattr(self._trace, "flush", None)
        if not callable(flush):
            return
        try:
            flush()
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("교차검증 관측 flush 실패(%s) — 무시하고 계속", type(exc).__name__)
