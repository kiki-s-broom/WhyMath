"""오답 **서명**(error signature) 기반 오개념 후보 탐지 — *시도(attempt) 단위* 검출기 (EOS-104).

기존 검출 경로와 무엇이 다른가
────────────────────────────────────────────────────────────────────────────
`diagnose`(substring·regex)·`semantic`·`judge`는 전부 **학생이 쓴 서술 텍스트**를 본다. 그래서
대화 턴에서만 재료가 생기고, 산출은 *턴* 단위다. 반면 채점 증거(`AssessmentEvidence`)는
*시도* 단위라, 턴 매칭을 그대로 옮기면 "이 답안의 오개념 후보"라는 **거짓 주장**이 된다
(EOS-104 acceptance ③ — 이 태스크의 핵심 난점).

이 모듈은 그 귀속 문제를 *재료를 바꿔서* 푼다. 학생이 서술을 안 써도 채점에는 반드시 두 가지가
있다 — **문항이 다루는 식**과 **학생이 낸 답**. 그 둘을 이으면 학생이 암묵적으로 주장한 등식이
된다:

    문항 `(x+2)²을 전개하시오` + 답 `x²+4`  →  주장 등식 `(x+2)² = x²+4`

이 등식은 *이 시도에서* 만들어진 것이므로 attempt 귀속이 정의상 성립한다. 판정은
`wrong_form_match.matches_wrong_form`(SymPy Wild 정합 + 동치 권위)을 **그대로 재사용**한다 —
탐지 알고리즘을 새로 쓰지 않는다(재구현 0).

ID 체계를 새로 만들지 않는다
────────────────────────────────────────────────────────────────────────────
후보 id는 `CATALOG`의 kebab id(`distribution-over-power` 등)를 그대로 쓴다. 리포트용 canonical
M-id로의 변환은 crosswalk(`docs/standards/crosswalk_gate_contract.md` · 사람 승인 게이트)가
하류에서 소유한다 — 여기서 M-id를 직접 만들면 그 사람 게이트를 우회하게 된다.

정직 스코프(중요)
────────────────────────────────────────────────────────────────────────────
- **재료가 없으면 훑지 않는다.** 답안이 없거나·문항에서 식을 못 뽑으면
  `MisconceptionScan.NOT_RUN`이다. 0건을 "오개념이 없었다"로 읽히게 하지 않는다. 정답은
  재료 부족이 아니다 — 채점 경로는 정답 답안도 넘긴다(EOS-123 · 아래 `scan_attempt_answer`).
- **탐지 대상은 두 독법이 볼 수 있는 오개념뿐**이다. ① `canonical_wrong_form`을 가진 거짓 항등식형
  (현재 카탈로그 68종 중 2종 — `scanned_forms`) ② 미분 단원 오답 서명 규칙에 걸린 오개념
  (`derivative_signature` — `signature_rules_scanned`, P3-56 후보). 나머지는 이 채널로
  *잡히지 않으며*,
  그 사실을 두 필드가 자기 기술한다 — "훑었는데 없었다"의 범위를 응답이 스스로 말하게 한다
  (작동한 비율 원칙).
- **문항 식 추출은 휴리스틱**이다. 그래서 구조 정합이 SymPy로 *증명*되어도 confidence를 1.0이
  아니라 `_STRUCTURAL_MATCH_CONFIDENCE`로 둔다(아래 상수 주석).
- **학생 원문을 산출물에 담지 않는다**(미성년 PII) — 추상 오개념 id와 신호 라벨만 남긴다.
- **비권위**: 이 모듈은 가설을 확정하지 않는다. 품질 게이트(`apply_match_quality_gate`)를
  통과한 *후보*만 내고, 학습자 상태의 최종 변경은 호출자(Assessment/Mastery 경로)가 한다.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from whymath_backend.config import get_settings
from whymath_backend.l4.misconception.catalog import CATALOG
from whymath_backend.l4.misconception.derivative_signature import (
    DerivativeSignatureResult,
    detect_derivative_signature,
)
from whymath_backend.l4.misconception.match_gate import apply_match_quality_gate
from whymath_backend.l4.misconception.models import Misconception, MisconceptionMatch
from whymath_backend.l4.misconception.wrong_form_match import matches_wrong_form
from whymath_backend.schema.assessment_evidence import (
    MisconceptionCandidate,
    MisconceptionScan,
)

logger = logging.getLogger("whymath.l4.misconception.answer_signature")

__all__ = [
    "ErrorSignature",
    "AttemptMisconceptionScanResult",
    "extract_error_signature",
    "detect_signature_matches",
    "scan_attempt_answer",
    "DerivativeShadowRecord",
]

# 구조 정합이 SymPy로 *증명*돼도 1.0을 주지 않는 이유: 증명된 것은 "이 등식이 그 거짓 규칙의
# 인스턴스"까지이고, "학생이 실제로 그 식을 다뤘다"는 전제는 발문 식 추출(휴리스틱)에 기댄다.
# 0.9는 게이트 floor(0.65)를 넉넉히 넘으면서, 반복 증거가 `reinforce`로 더 올라갈 여지를 남긴다
# (1.0이면 첫 관측에서 포화해 누적 축이 죽는다 — Persona C 감쇠 시나리오의 대조군이 사라진다).
_STRUCTURAL_MATCH_CONFIDENCE = 0.9

# 수식 토큰 런(run) — 한글·조사는 포함하지 않으므로 `(x+2)²을 전개하시오`에서 자연히 끊긴다.
# 위첨자를 포함하는 것은 `wrong_form_match._EQ_TOKEN`과 같은 이유다(정규화는 to_sympy_source).
_EXPR_TOKEN = re.compile(r"[0-9A-Za-z()+\-*/^.⁰¹²³⁴⁵⁶⁷⁸⁹]+(?:[ ][0-9A-Za-z()+\-*/^.⁰¹²³⁴⁵⁶⁷⁸⁹]+)*")

# 단항(`x`·`3`)은 "학생이 다룬 식"이 될 수 없다 — 연산자가 하나라도 있어야 후보다.
_HAS_OPERATOR = re.compile(r"[+\-*/^⁰¹²³⁴⁵⁶⁷⁸⁹]")


class ErrorSignature(BaseModel):
    """오답 1건에서 뽑은 **구조적 오류 서명** — 화면 문자열이 아니라 판정 재료.

    `claimed_lhs = claimed_rhs`는 학생이 *암묵적으로 주장한* 등식이다. 학생이 실제로 그 등호를
    쓴 것이 아니라, 문항이 다루는 식과 제출 답을 이어 우리가 구성한 것이므로 필드명이
    `claimed_*`다 — 이 이름이 "학생이 쓴 원문"과 "우리가 구성한 주장"을 구별한다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    claimed_lhs: str = Field(description="문항에서 추출한, 학생이 다룬 것으로 보이는 식.")
    claimed_rhs: str = Field(description="학생이 제출한 답안 표현.")


class AttemptMisconceptionScanResult(BaseModel):
    """시도 1건의 오개념 훑기 결과 — 후보 + **훑었는지 여부**(3상태).

    `scan`이 있는 이유는 0건의 뜻이 둘이기 때문이다: "재료가 없어 안 봤다"(NOT_RUN)와
    "봤는데 확실한 후보가 없었다"(RAN_NO_CANDIDATE). 이 둘을 같은 빈 리스트로 내보내면
    하류가 미측정을 측정된 0으로 오독한다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    scan: MisconceptionScan = Field(description="이 시도에서 오개념을 실제로 훑었는가(3상태).")
    candidates: tuple[MisconceptionCandidate, ...] = Field(
        default=(),
        description="품질 게이트를 통과한 후보(신뢰도 내림차순). 게이트가 비우면 빈 튜플.",
    )
    signature: ErrorSignature | None = Field(
        default=None,
        description="훑기에 실제로 쓰인 오류 서명. NOT_RUN이면 None(재료가 없었다는 뜻).",
    )
    scanned_forms: int = Field(
        default=0,
        ge=0,
        description=(
            "이번 훑기가 대조한 거짓형(`canonical_wrong_form`) 수 — **이 채널의 사정거리**다. "
            "0건 결과를 '카탈로그 전체에 없었다'로 읽지 못하게 범위를 함께 낸다."
        ),
    )
    signature_rules_scanned: int = Field(
        default=0,
        ge=0,
        description=(
            "미분 오답 서명 규칙(`derivative_signature`) 중 이번에 적재돼 대조 대상이 된 규칙 수. "
            "0이면 이 독법을 **돌리지 못했다**(규칙표 적재 실패) — 질문을 읽지 못해 빈 결과가 "
            "나온 것과 다르다. 후자는 규칙 수가 그대로 실리고 후보만 비어 있다. "
            "모드가 `off`·`shadow`면 독법이 호출자에게 노출되지 않으므로 항상 0이다."
        ),
    )
    shadow_records: tuple[str, ...] = Field(
        default=(),
        description=(
            "그림자 모드(`l4_derivative_signature_mode=shadow`)의 관측 레코드 — **불투명 JSON "
            "문자열**이다. 이 결과는 워커 프로세스에서 만들어져 부모로 돌아오므로, 워커에서 직접 "
            "로그를 남기면 풀 워커의 로깅 설정이 없어 조용히 사라진다. 그래서 관측을 결과에 실어 "
            "보내고 부모(API 계층)가 해석 없이 기록한다. 그림자가 아니면 항상 빈 튜플."
        ),
    )


class DerivativeShadowRecord(BaseModel):
    """그림자 관측 1건 — **켰다면 무엇이 달라졌을지**만 담는다(학생 답·지문 미포함).

    학생 답과 지문을 담지 않는 이유는 미성년 PII 규율이다. 대신 판정에 필요한 파생 사실만 싣는다:
    질문을 읽었는가·정답이었는가·켰다면 새로 얹혔을 후보 id·어느 규칙인가. 오귀속률 평가는 이
    레코드를 문항 id별 **우연 일치 기준선**과 비교하는 방식으로 한다(활성화 게이트 기준 참조).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    channel: Literal["derivative_signature"] = "derivative_signature"
    rules_total: int = Field(ge=0, description="적재된 규칙 수. 0이면 독법을 돌리지 못했다.")
    applicable: bool = Field(description="질문에서 함수식과 묻는 양을 읽었는가.")
    answer_is_correct: bool | None = Field(
        description="학생 답이 정답과 같은가. 질문을 못 읽었으면 None(모른다 ≠ 아니다)."
    )
    fired: bool = Field(description="켰다면 기존에 없던 후보가 게이트를 통과해 얹혔는가.")
    added_candidate_ids: tuple[str, ...] = Field(description="켰다면 새로 얹혔을 후보 id.")
    rule_ids: tuple[str, ...] = Field(description="후보를 낸 규칙 id.")
    changes_top1: bool = Field(description="켜면 top-1 후보가 바뀌는가.")
    attribution_unclear: bool = Field(
        description="한 답이 둘 이상의 오개념에 걸려 귀속이 불명한가."
    )
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def _wrong_form_catalog() -> tuple[Misconception, ...]:
    """`canonical_wrong_form`을 가진 오개념만 — 이 채널이 볼 수 있는 전부."""
    return tuple(m for m in CATALOG if m.canonical_wrong_form is not None)


def extract_error_signature(question_text: str, student_answer: str) -> ErrorSignature | None:
    """발문과 제출 답에서 오류 서명을 만든다 — 못 만들면 `None`(재료 부족).

    발문에서 *연산자를 포함한 가장 긴* 수식 토큰 런을 고른다. 가장 긴 것을 고르는 이유는
    부분식(`x+2`)보다 전체식(`(x+2)²`)이 학생이 다룬 대상일 가능성이 높기 때문이다. 동률이면
    먼저 나온 것을 쓴다(결정론 — 같은 입력에 같은 서명).

    답안 쪽은 추출하지 않고 **제출 문자열 그대로** 쓴다. 답안은 이미 "학생이 낸 답" 하나이므로
    거기서 또 고르면 우리가 답을 재해석하는 셈이 된다.
    """
    answer = student_answer.strip()
    if not answer:
        return None
    candidates = [
        tok.strip() for tok in _EXPR_TOKEN.findall(question_text) if _HAS_OPERATOR.search(tok)
    ]
    if not candidates:
        return None
    # 최장 우선(동률은 등장 순서) — `max`는 안정적이라 첫 최댓값을 돌려준다.
    lhs = max(candidates, key=len)
    return ErrorSignature(claimed_lhs=lhs, claimed_rhs=answer)


def detect_signature_matches(signature: ErrorSignature) -> list[MisconceptionMatch]:
    """오류 서명이 카탈로그의 거짓형을 인스턴스화했는지 — 매칭을 신뢰도 내림차순으로.

    판정은 `matches_wrong_form`에 위임한다(재구현 0). 그 함수가 ⓪학생 등식이 실제로 거짓인지
    ①lhs 구조 정합 ②rhs 동치를 모두 확인하므로, 정답·우연히 참인 등식은 여기까지 오지 않는다.
    """
    matches: list[MisconceptionMatch] = []
    for misconception in _wrong_form_catalog():
        wrong_form = misconception.canonical_wrong_form
        assert wrong_form is not None  # `_wrong_form_catalog`이 이미 걸렀다(mypy 좁히기용).
        if matches_wrong_form(signature.claimed_lhs, signature.claimed_rhs, wrong_form):
            matches.append(
                MisconceptionMatch(
                    misconception=misconception,
                    confidence=_STRUCTURAL_MATCH_CONFIDENCE,
                    # 학생 원문이 아니라 *대조에 쓰인 거짓형 템플릿*을 남긴다(PII 없음·재현 가능).
                    matched_signals=(f"{wrong_form[0]}={wrong_form[1]}",),
                )
            )
    # 게이트는 입력을 재정렬하지 않고 `matches[0]`을 top-1으로 신뢰한다 — 여기서 정렬해 준다.
    matches.sort(key=lambda m: m.confidence, reverse=True)
    return matches


_INERT_DERIVATIVE = DerivativeSignatureResult(matches=(), applicable=False, rules_total=0)
"""독법을 부르지 않았을 때의 결과 — `off`와 `shadow`의 반환 조립에 쓴다(후보 0·읽지 못함)."""


def _read_derivative_channel(
    question_text: str, student_answer: str, *, report_correctness: bool = False
) -> DerivativeSignatureResult:
    """미분 오답 서명 독법을 돌린다 — 규칙표가 깨져도 기존 거짓형 채널은 죽이지 않는다.

    적재 실패는 **조용히 삼키지 않고** 예외 타입명을 로그에 남기며(시크릿·필드값 제외), 결과의
    `signature_rules_scanned=0`으로 "이 독법을 돌리지 못했다"가 드러난다. 데이터 결함 자체는 규칙표
    적재 테스트가 CI에서 막으므로 이 경로는 배포 산출물에서 코퍼스가 빠진 경우의 안전망이다.
    """
    try:
        return detect_derivative_signature(
            question_text, student_answer, report_correctness=report_correctness
        )
    except Exception as exc:  # noqa: BLE001 — 새 독법의 실패가 기존 채널을 죽이지 않게 격리한다
        logger.error("미분 오답 서명 독법 적재 실패: %s", type(exc).__name__)
        return _INERT_DERIVATIVE


def _merge_matches(
    first: list[MisconceptionMatch], second: tuple[MisconceptionMatch, ...]
) -> list[MisconceptionMatch]:
    """두 독법의 후보를 오개념 id별 최고 신뢰도 하나로 합쳐 신뢰도 내림차순으로 낸다.

    게이트는 입력을 재정렬하지 않고 `matches[0]`을 top-1으로 신뢰하므로 여기서 정렬한다.
    """
    best: dict[str, MisconceptionMatch] = {}
    for match in (*first, *second):
        current = best.get(match.misconception.id)
        if current is None or match.confidence > current.confidence:
            best[match.misconception.id] = match
    return sorted(best.values(), key=lambda m: m.confidence, reverse=True)


def scan_attempt_answer(
    *, question_text: str, student_answer: str | None
) -> AttemptMisconceptionScanResult:
    """시도 1건을 훑어 게이트 통과 후보를 낸다 — 이 모듈의 단일 공개 진입점.

    호출자는 **정답·오답 모두** 부른다(EOS-123). 정답 답안은 ⓪ 거짓 등식 가드가 막아 후보가
    없는 것이 정상이며(`RAN_NO_CANDIDATE` — 채점 경로는 그것을 오답 회차와 같은 1턴 감쇠의
    근거로 쓴다), 정답으로 보고됐는데 후보가 나오면 호출자가 보고와 관측의 충돌로 다룬다(가설
    보류). 종전에는 "안 보는 것과 봐서 없는 것을 구별하려면 정답은 호출하지 않는 쪽이 정직하다"며
    오답일 때만 불렀는데, 그 결과 정답 회차가 가설을 전혀 움직이지 못하는 역방향 비대칭이
    생겼다 — 봐서 없는 것은 이제 `RAN_NO_CANDIDATE`로 정직하게 구별된다.

    3상태 귀결:
      · 재료 부족(답안 없음·발문에서 식 추출 실패) → `NOT_RUN`
      · 훑었고 게이트가 후보를 비움           → `RAN_NO_CANDIDATE`
      · 훑었고 게이트 통과 후보 있음           → `RAN_WITH_CANDIDATES`

    `gate_passed=True`는 *게이트를 통과한 것만 싣는다*는 이 함수의 계약을 자기 기술한 것이다
    (`build_assessment_evidence`가 False를 ValueError로 거부한다 — 그 경계를 우회하지 않는다).
    """
    scanned_forms = len(_wrong_form_catalog())
    if student_answer is None or not student_answer.strip():
        return AttemptMisconceptionScanResult(scan=MisconceptionScan.NOT_RUN)
    mode = get_settings().l4_derivative_signature_mode
    signature = extract_error_signature(question_text, student_answer)
    old_matches = detect_signature_matches(signature) if signature is not None else []

    # 모드: off=독법을 부르지 않는다(비트동일) · shadow=돌리되 반환은 off와 같다 · on=합류.
    derivative = (
        _INERT_DERIVATIVE
        if mode == "off"
        else _read_derivative_channel(
            question_text, student_answer, report_correctness=(mode == "shadow")
        )
    )
    effective = derivative if mode == "on" else _INERT_DERIVATIVE
    result = _assemble(signature, old_matches, effective, scanned_forms)
    if mode != "shadow":
        return result
    try:
        record = _shadow_record(old_matches, derivative)
    except Exception as exc:  # noqa: BLE001 — 관측이 훑기를 깨뜨리지 않는다(예외 타입명만 남김)
        logger.error("미분 오답 서명 그림자 관측 실패: %s", type(exc).__name__)
        return result
    return result.model_copy(update={"shadow_records": (record,)})


def _assemble(
    signature: ErrorSignature | None,
    old_matches: list[MisconceptionMatch],
    derivative: DerivativeSignatureResult,
    scanned_forms: int,
) -> AttemptMisconceptionScanResult:
    """두 독법의 결과로 훑기 결과를 조립한다 — `off`·`shadow`·`on`이 같은 조립 경로를 쓴다."""
    if signature is None and not derivative.applicable:
        # 두 독법 모두 재료를 못 읽었다 — 0건을 '오개념 없음'으로 읽히게 하지 않는다.
        return AttemptMisconceptionScanResult(scan=MisconceptionScan.NOT_RUN)

    merged = _merge_matches(old_matches, derivative.matches)
    gated = apply_match_quality_gate(merged)
    if not gated.matches:
        return AttemptMisconceptionScanResult(
            scan=MisconceptionScan.RAN_NO_CANDIDATE,
            signature=signature,
            scanned_forms=scanned_forms,
            signature_rules_scanned=derivative.rules_total,
        )
    return AttemptMisconceptionScanResult(
        scan=MisconceptionScan.RAN_WITH_CANDIDATES,
        candidates=tuple(
            MisconceptionCandidate(
                misconception_id=match.misconception.id,
                confidence=match.confidence,
                gate_passed=True,
                low_quality=gated.low_quality,
                attribution_unclear=gated.attribution_unclear,
            )
            for match in gated.matches
        ),
        signature=signature,
        scanned_forms=scanned_forms,
        signature_rules_scanned=derivative.rules_total,
    )


def _shadow_record(
    old_matches: list[MisconceptionMatch], derivative: DerivativeSignatureResult
) -> str:
    """'독법을 켰다면 무엇이 달라졌는가'를 JSON 한 줄로 — 학생 답·지문은 담지 않는다."""
    off = apply_match_quality_gate(_merge_matches(old_matches, ()))
    on = apply_match_quality_gate(_merge_matches(old_matches, derivative.matches))
    ids_off = [m.misconception.id for m in off.matches]
    ids_on = [m.misconception.id for m in on.matches]
    added = tuple(i for i in ids_on if i not in ids_off)
    return DerivativeShadowRecord(
        rules_total=derivative.rules_total,
        applicable=derivative.applicable,
        answer_is_correct=derivative.answer_is_correct,
        fired=bool(added),
        added_candidate_ids=added,
        rule_ids=tuple(sorted({sig for m in derivative.matches for sig in m.matched_signals})),
        changes_top1=bool(ids_on) and (not ids_off or ids_on[0] != ids_off[0]),
        attribution_unclear=on.attribution_unclear,
    ).model_dump_json()
