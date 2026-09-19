"""WH-1 코치 프로즈 계층(S4-04) — 파생 템플릿 정답-안전 rephrase + 정책 프로즈 게이트.

S1-11 flip으로 LLM이 튜터링을 오케스트레이션하지만, 학생-대면 발화는 정답 억제 백스톱
설계상 파생 템플릿(`wh1_loop.NEUTRAL_GUIDE_UTTERANCE`/`ENCOURAGE_FALLBACK_UTTERANCE`)만
반복 노출된다 — "같은 답 반복"의 잔여. 이 모듈은 그 템플릿을 LLM 문맥 프로즈로 승격하되,
발문 다양화 rephrase(`l3/equivalent/rephrase.py` — LIVE_LLM_ACTIVATION §5)의 fail-closed
계약을 코치 발화용으로 이식한다. 봉인 방향은 **역전**이다: 문항은 방정식을 *보존*해야
하고, 코치 프로즈는 방정식·정답이 *아예 없어야* 한다(정답/다음 줄 미유입).

두 프로필(대상 텍스트의 성질이 다르다):
  - **프로필 S** (`classify_prose_violation`) — 파생 템플릿의 rephrase *산출물* 검증. 원
    템플릿에 등호·숫자가 없으므로 등호·숫자 전면 금지가 오탐 0으로 성립하고, 학생 풀이·
    단계(GT) 문자열 유입·"정답" 키워드·과길이를 구조로 차단한다. 실패=원 템플릿 유지
    (fail-closed — 발화는 이미 안전한 템플릿이라 품질만 잃고 안전은 불변).
  - **프로필 C** (`gate_policy_prose`) — correct·무verdict 턴의 정책 자유발화(이미 LLM
    프로즈) 검증. 정답 억제 백스톱이 닿지 않는 유일한 열린 경로라, *외래* 등식(학생
    재료에 없는 등식 — LLM 날조 "x=3")을 차단하되 학생이 쓴 등식 echo는 허용하고, 위생
    체인으로 격리된 거짓 산술을 거른다. 실패 사유 반환=호출자가 결정론 폴백.

rephrase 대상은 `REPHRASABLE_TEMPLATES` **정확 일치**일 때만 — 오개념 개입 프롬프트
(canonical_statement 등식 포함)·출제 발화(문항번호 보존)는 LLM 호출 0으로 무변형 통과
(오차단 구조 차단·지연 0). LLM 호출은 라우터 경유(GENERAL·easy·sync — rephrase.py 미러)
이며 `asyncio.wait_for` async 직호출이다 — 이 계층은 이미 실행 중인 이벤트 루프 안(primary
러너)에서 돌므로 rephrase.py의 sync CLI용 지속 루프(`_ensure_loop`)는 쓰지 않는다.

hermetic: provider 주입 좌석(테스트=FakeProvider)·provider 부재 시 라이브 호출 0(원 템플릿
유지). 프롬프트에 학생 원문·풀이 단계를 싣지 않는다(비민감 컨텍스트만 — 프라이버시).
"""

from __future__ import annotations

import asyncio
import logging
import unicodedata
from collections.abc import Sequence

from whymath_backend.harness.wh1_llm_seam import Wh1Generation, Wh1LlmSeam
from whymath_backend.harness.wh1_loop import (
    ENCOURAGE_FALLBACK_UTTERANCE,
    NEUTRAL_GUIDE_UTTERANCE,
)
from whymath_backend.l3.data_grade_defaults import SELF_AUTHORED_CORPUS
from whymath_backend.l3.equivalent.rephrase import (
    REASON_EMPTY,
    REASON_HYGIENE_REJECT,
    REASON_NO_CHANGE,
    REASON_PROVIDER_ERROR,
    RephraseOutcome,
)
from whymath_backend.l3.interfaces import CacheBackend, LLMProvider, TraceSink
from whymath_backend.l3.models import ModelFamily, RoutingRequest
from whymath_backend.l3.pregenerate.validator import (
    _RELATION_RE,
    default_seed_validator,
    validate_response,
)

__all__ = [
    "REASON_NOT_REPHRASABLE",
    "REASON_NO_PROVIDER",
    "REASON_PROSE_ANSWER_KEYWORD",
    "REASON_PROSE_DIGIT",
    "REASON_PROSE_EQUATION",
    "REASON_PROSE_FOREIGN_EQUATION",
    "REASON_PROSE_SOLUTION_ECHO",
    "REASON_PROSE_TIMEOUT",
    "REASON_PROSE_TOO_LONG",
    "REPHRASABLE_TEMPLATES",
    "classify_prose_violation",
    "gate_policy_prose",
    "rephrase_coach_utterance",
]

_logger = logging.getLogger(__name__)

# 실패 reason-code taxonomy — rephrase.py 관례(코드 경로 1:1·정직 taxonomy)를 계승·확장.
# 공용 코드(EMPTY·PROVIDER_ERROR·NO_CHANGE·HYGIENE_REJECT)는 l3 rephrase에서 재사용한다.
REASON_NOT_REPHRASABLE = "NOT_REPHRASABLE"  # 화이트리스트 밖(개입·출제) — LLM 미호출 통과
REASON_NO_PROVIDER = "NO_PROVIDER"  # provider 부재(hermetic·미배선) — 라이브 호출 0
REASON_PROSE_TIMEOUT = "PROSE_TIMEOUT"  # LLM 호출 시간 예산 초과
REASON_PROSE_EQUATION = "PROSE_EQUATION"  # 등호 유입(전면 금지 — 원 템플릿에 등호 0)
REASON_PROSE_DIGIT = "PROSE_DIGIT"  # 숫자 유입(등호 없는 정답 진술 "x는 3" 구조 차단)
REASON_PROSE_SOLUTION_ECHO = "PROSE_SOLUTION_ECHO"  # 학생 풀이·단계(GT) 문자열 echo
REASON_PROSE_ANSWER_KEYWORD = "PROSE_ANSWER_KEYWORD"  # "정답" 키워드(소크라테스 프로즈 밖)
REASON_PROSE_TOO_LONG = "PROSE_TOO_LONG"  # 과길이(폭주·주입 표면 방어)
REASON_PROSE_FOREIGN_EQUATION = "PROSE_FOREIGN_EQUATION"  # 프로필 C: 학생 재료 밖 등식 날조

# rephrase 정확-일치 화이트리스트 — wh1_loop 파생 템플릿 공개 상수가 단일 원천.
# 개입 프롬프트(등식 포함)·출제 발화(문항번호)는 여기 없으므로 구조적으로 rephrase 불가.
REPHRASABLE_TEMPLATES: frozenset[str] = frozenset(
    {NEUTRAL_GUIDE_UTTERANCE, ENCOURAGE_FALLBACK_UTTERANCE}
)

# 프로즈 길이 상한 — 원 템플릿(24~27자)의 ~4.5배. LLM 폭주·프롬프트 주입 표면 방어.
_MAX_PROSE_LEN = 120
# GT echo 판정 최소 길이(정규형 기준) — 1자 조각("x")의 우연 일치 오탐 방지.
_MIN_ECHO_LEN = 2
# 발문 rephrase 라이브 스윕 실측 최적(0.7=78.4% vs 0.9=72.8% — rephrase.py 근거 재사용).
_DEFAULT_TEMPERATURE = 0.7

# 시스템 프롬프트 — rephrase.py v3 교훈 계승(경량 문면·negative example 금지·정책 앵커 1줄.
# v2 적층이 수율 82%→57% 역행시킨 실측 — "더 많이 넣을수록 더 멍청해진다").
_SYSTEM_PROMPT = """당신은 WhyMath의 **코치 발화 편집자**입니다. 주어진 한국어 코치 발화 한
문장을 학생 상황에 맞게 자연스럽게 다시 씁니다. 절대 규칙:

1. 수식·등호·숫자를 **넣지** 마십시오.
2. 정답·풀이 단계를 **언급하지** 마십시오.
3. 원 발화의 교수 의도(스스로 근거를 말하게 하는 질문 / 진행 격려)를 유지하십시오.
4. 위 규칙을 지킬 수 없으면 **원 발화를 그대로** 출력하십시오.
5. 출력은 발화 **한 문장만**. 설명·따옴표·머리말 없이 문장만 내십시오."""


def _nfkc(text: str) -> str:
    """NFKC 정규화 — 전각 등호(＝)·전각 숫자(３) 우회를 ASCII로 붕괴시켜 게이트가 잡게 한다."""
    return unicodedata.normalize("NFKC", text)


def _squash(text: str) -> str:
    """echo·외래 등식 비교용 정규형 — NFKC + 소문자 + 공백 전제거(공백 변형 우회 차단)."""
    return "".join(_nfkc(text).lower().split())


def classify_prose_violation(text: str, *, forbidden_fragments: Sequence[str] = ()) -> str | None:
    """프로필 S — 파생 템플릿 rephrase 산출물의 정답-안전 위반을 분류(통과=None·순수).

    검사 순서(먼저 걸린 사유 반환): ①빈 출력 ②등호 전면 금지 ③숫자 전면 금지 ④GT
    (학생 풀이·단계) 문자열 미유입 ⑤"정답" 키워드 ⑥길이 상한. 원 템플릿에 등호·숫자가
    없으므로 ②③은 오탐 0의 구조 봉인이다(발문 rephrase EXTRA_EQUATION의 "보존분 제외"
    로직이 "전면 금지"로 단순화 — 봉인 방향 역전). 위생 체인은 ③이 엄격 상위집합이라
    이 프로필엔 미배선(발화 불가 게이트를 달지 않는 정직 taxonomy — rephrase.py 원칙).
    """
    stripped = text.strip()
    if not stripped:
        return REASON_EMPTY
    normalized = _nfkc(stripped)
    if "=" in normalized:
        return REASON_PROSE_EQUATION
    if any(ch.isdigit() for ch in normalized):
        return REASON_PROSE_DIGIT
    squashed = _squash(stripped)
    for fragment in forbidden_fragments:
        frag = _squash(fragment)
        if len(frag) >= _MIN_ECHO_LEN and frag in squashed:
            return REASON_PROSE_SOLUTION_ECHO
    if "정답" in normalized:
        return REASON_PROSE_ANSWER_KEYWORD
    if len(stripped) > _MAX_PROSE_LEN:
        return REASON_PROSE_TOO_LONG
    return None


def gate_policy_prose(text: str, *, student_material: Sequence[str] = ()) -> str | None:
    """프로필 C — correct·무verdict 턴 정책 자유발화의 정답-안전 위반 분류(통과=None·순수).

    억제 백스톱이 닿지 않는 유일한 열린 경로의 게이트다. 학생이 이미 쓴 등식의 echo
    ("2x=4 다음이 뭘까?")는 정당한 코칭이라 허용하고, 학생 재료에 없는 **외래 등식**
    (LLM 날조 "x=3" — 거짓 정답·추가 등식의 정의)만 차단한다. 판정: `_RELATION_RE`
    (validator.py — 변수 포함 등식)로 등식 스팬을 뽑아 각 스팬의 정규형(공백 제거)이
    학생 재료 정규형 안에 있으면 허용, 하나라도 외래면 거부. 이후 위생 체인이 격리된
    거짓 산술(예: "삼사는 십일" 아닌 "3*4=11")을 추가로 거른다.

    학생 재료 조각은 구분자 `§`(등식 스팬에 등장 불가 문자)로 이어 붙여 정규형을 만든다 —
    공백 제거 연접이 조각 경계를 넘어 우연 매치를 만드는 오허용(예: "…x=" + "3…")을 막는다.
    """
    stripped = text.strip()
    if not stripped:
        return REASON_EMPTY
    normalized = _nfkc(stripped)
    material = "§".join(_squash(fragment) for fragment in student_material)
    for match in _RELATION_RE.finditer(normalized):
        span = _squash(match.group(0))
        if span and span not in material:
            return REASON_PROSE_FOREIGN_EQUATION
    if validate_response(default_seed_validator(), stripped) is not None:
        return REASON_HYGIENE_REJECT
    return None


def _routing_request() -> RoutingRequest:
    """프로즈 문맥화의 라우팅 **입력** — 결정은 파이프라인 안의 라우터가 내린다(OPS-36).

    문맥화는 다단계 추론이 아니라 instruction-following이라 easy·비추론·sync로 라우팅한다
    (로컬 FAST 즉답·저비용). 패밀리 축 GENERAL(qwen2.5) 선호는 **여기서 결정을 손으로
    재조립하지 않고** `pipeline.generate(prefer_local_family=...)`로 넘긴다 — 종전에는 이 함수가
    `Router().route()` 결과를 받아 `RoutingDecision`을 직접 다시 만들었고(rephrase.py와 같은
    코드의 3대째 미러), 그 재조립이 곧 파이프라인 우회였다(관측·캐시 미결선). 적용 조건·승계
    필드는 `_apply_family_preference`가 그대로 승계한다(라우터의 비용·크기·모드 결정은 존중).
    """
    return RoutingRequest(
        task_type="generate",
        difficulty="easy",
        requires_reasoning=False,
        student_subscription="free",
        sync=True,
        # 등급: 이 프롬프트에는 *학생 자료가 실리지 않는다* — `_build_prompt`가 원 템플릿 +
        # 비민감 컨텍스트(행위 유형·판정·턴 번호·오개념 라벨)만 싣고, "학생 원문·풀이 단계는
        # 절대 싣지 않는다"를 프롬프트 캡처 테스트로 봉인하고 있다. `student_material`은
        # *산출물 검증*(gate_policy_prose의 외래 등식 판별)에만 쓰이지 프롬프트에 안 들어간다.
        # 실리는 것은 우리 코치 템플릿·카탈로그 라벨뿐 → 자체 저작(EOS-59).
        data_licenses=SELF_AUTHORED_CORPUS,
    )


def _build_prompt(
    utterance: str,
    *,
    action_type: str | None,
    verdict: str | None,
    turn_index: int,
    hypothesis_label: str | None,
) -> str:
    """user 프롬프트 — 원 템플릿 + **비민감 컨텍스트만**(라벨·턴 번호).

    학생 원문·풀이 단계는 절대 싣지 않는다(프라이버시 — 프롬프트 캡처 테스트가 봉인).
    가설 라벨은 카탈로그 메타(name_kr·비PII) 1건만 — 오개념 preload가 아니라 이미 턴에
    활성인 최상위 가설의 표시 이름이다(reactive retrieval 불변).
    """
    context_bits = [
        f"행위 유형: {action_type or '미상'}",
        f"직전 판정: {verdict or '없음'}",
        f"턴 번호: {turn_index}",
    ]
    if hypothesis_label:
        context_bits.append(f"의심 오개념 라벨: {hypothesis_label}")
    context = " · ".join(context_bits)
    return (
        "다음 코치 발화를 학생 상황에 맞게 자연스럽게 한 문장으로 다시 쓰십시오.\n"
        f"[상황] {context}\n"
        f"[원 발화] {utterance}\n"
        "규칙을 지킬 수 없으면 원 발화를 그대로 출력하십시오."
    )


async def rephrase_coach_utterance(
    utterance: str,
    *,
    action_type: str | None,
    verdict: str | None,
    turn_index: int,
    hypothesis_label: str | None,
    forbidden_fragments: Sequence[str],
    provider: LLMProvider | None,
    timeout_seconds: float,
    temperature: float = _DEFAULT_TEMPERATURE,
    cache: CacheBackend | None = None,
    trace: TraceSink | None = None,
    seam: Wh1Generation | None = None,
) -> RephraseOutcome:
    """파생 템플릿 발화를 LLM 문맥 프로즈로 rephrase — fail-closed(어떤 실패든 원 템플릿).

    `RephraseOutcome`(l3 rephrase 공용 봉투)의 `text`는 항상 유효한 발화다: 게이트 통과 시
    문맥화 프로즈, 그 외 전부 **원 템플릿 그대로**. 화이트리스트 밖(개입·출제)·provider
    부재는 LLM 호출 자체가 0이다(지연 0·라이브 0). 실패는 reason_code + (게이트 거부 시)
    raw_output으로 사후 분석 가능(조용한 실패 금지 — 로그는 코드·타입명만, 발화 원문 미출력).
    """
    if utterance not in REPHRASABLE_TEMPLATES:
        return RephraseOutcome(
            text=utterance,
            rephrased=False,
            reason="rephrase 화이트리스트 밖(개입·출제 등) — 무변형 통과",
            reason_code=REASON_NOT_REPHRASABLE,
        )
    if provider is None:
        return RephraseOutcome(
            text=utterance,
            rephrased=False,
            reason="provider 부재 — 라이브 호출 0·원 템플릿 유지",
            reason_code=REASON_NO_PROVIDER,
        )
    prompt = _build_prompt(
        utterance,
        action_type=action_type,
        verdict=verdict,
        turn_index=turn_index,
        hypothesis_label=hypothesis_label,
    )
    # 좌석 경유(OPS-36) — 라우터 결정·캐시·Langfuse 기록이 전부 파이프라인 안에서 일어난다.
    generation: Wh1Generation = (
        seam if seam is not None else Wh1LlmSeam(provider=provider, cache=cache, trace=trace)
    )
    try:
        raw = await asyncio.wait_for(
            generation.generate(
                _routing_request(),
                prompt,
                _SYSTEM_PROMPT,
                prefer_local_family=ModelFamily.GENERAL,
                temperature=temperature,
            ),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        _logger.warning("코치 프로즈 rephrase 타임아웃(%.1fs) — 원 템플릿 유지", timeout_seconds)
        return RephraseOutcome(
            text=utterance,
            rephrased=False,
            reason="LLM 호출 시간 예산 초과",
            reason_code=REASON_PROSE_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001 — fail-closed(발화는 이미 안전한 템플릿)·타입명 로그
        _logger.warning("코치 프로즈 rephrase 실패(%s) — 원 템플릿 유지", type(exc).__name__)
        return RephraseOutcome(
            text=utterance,
            rephrased=False,
            reason="LLM 호출 예외",
            reason_code=REASON_PROVIDER_ERROR,
        )
    code = classify_prose_violation(raw, forbidden_fragments=forbidden_fragments)
    if code is not None:
        # 게이트 거부 — 사유 코드만 로그(발화 원문·raw는 로그 미출력·Outcome으로만 사후 분석).
        _logger.warning("코치 프로즈 게이트 거부(%s) — 원 템플릿 유지", code)
        return RephraseOutcome(
            text=utterance,
            rephrased=False,
            reason="프로즈 게이트 거부",
            reason_code=code,
            raw_output=raw,
        )
    stripped = raw.strip()
    if stripped == utterance:
        return RephraseOutcome(
            text=utterance,
            rephrased=False,
            reason="출력이 원 템플릿과 동일 — 다양화 실패(오염 아님·안전)",
            reason_code=REASON_NO_CHANGE,
        )
    return RephraseOutcome(text=stripped, rephrased=True)
