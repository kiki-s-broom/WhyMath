"""LLM 발문 다양화 — 스켈레톤이 확정한 수치를 보존하며 발문만 rephrase(S2-p 후속).

스켈레톤 생성기(S2-o·LLM 0)는 발문을 소수의 한국어 템플릿 회전으로 조립한다 — 구조 다양성
(수백 조합)은 크지만 문장 표현은 단조롭다. 이 모듈은 확정된 문제의 *수치·수식·정답은 그대로
두고* 발문 문장 표현만 LLM으로 다양화한다. LLM이 수식을 못 바꾸게 **결정론 검증 게이트**로
봉인하므로, LLM 비결정성이 문제의 수학적 실체에 새는 것을 원천 차단한다.

핵심 원칙(왜 안전한가):
  1. **수치는 코드가 소유** — conditions·answer·answer_map·answer_selection·choices·difficulty·
     distractor_map은 rephrase가 건드리지 않는다(입력을 그대로 반환). 오직 `question_text`만
     LLM이 다시 쓴다. 따라서 S2-a 정확성 게이트(verify_answer+근 선택+derive-and-verify)는
     rephrase 후에도 무료로 재통과한다(재검증 대상 필드가 불변).
  2. **방정식 substring 봉인** — 스켈레톤이 발문에 박은 정확한 방정식 문자열(예 '3x^2 - 7x + 4
     = 0')을 원 발문에서 추출해, rephrase 결과에 그 문자열이 *글자·공백까지 그대로* substring으로
     남아 있는지 검사한다. 없으면 fail-closed(원문 유지). 프롬프트가 "방정식은 글자 그대로 보존"을
     명령하고, 검증이 그 준수를 결정론으로 확인한다(오탐 0).
  3. **위생 재검사** — rephrase가 새로 도입한 거짓 수치 등식('3×4=11' 등)을 위생 validator
     (`default_seed_validator`)로 다시 거른다(acceptance._evaluate_hygiene와 같은 검증기).

라우터 경유(CLAUDE.md "LLM 호출은 항상 라우터 경유"): `Router().route()`로 결정하고
`provider.generate(...)`로 위임한다. 저작 패밀리 GENERAL(qwen2.5) — rephrase는 수학 풀이가
아니라 instruction-following(문장 다양화)이라 MATH(qwen2-math)보다 GENERAL이 낫다(S2-h 논거 동형).

hermetic: provider 주입 좌석(테스트=FakeProvider). 이 환경엔 LLM이 없어 라이브 호출을 하지
않는다 — 실 다양화는 Phaiakes9에서 실 provider 주입으로 구동한다(llm_generator 라이브 핸드오프
동형). **결정론 배치와 분리**: 이 rephrase는 비결정적이라 스켈레톤 배치(`run_corpus_batch`·바이트
동일 봉인)에 넣지 않고, 그 산출물을 입력으로 받는 별도 opt-in 후처리다(harness CLI).

7계층: L3 지역. schema·동일 패키지·L3 인프라(interfaces·models·router·pregenerate validator)만
import한다(L4 import 0).
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from functools import lru_cache

from whymath_backend.l3.data_grade_defaults import SELF_AUTHORED_CORPUS
from whymath_backend.l3.equivalent.rephrase_hygiene import (
    REASON_UNCHANGED_FROM_ORIGINAL,
    question_hygiene_violations,
)
from whymath_backend.l3.escalation_defaults import default_student_escalation_signals
from whymath_backend.l3.interfaces import LLMProvider
from whymath_backend.l3.models import ModelFamily, RoutingDecision, RoutingRequest
from whymath_backend.l3.pregenerate.validator import (
    SeedValidator,
    default_seed_validator,
    validate_response,
)
from whymath_backend.l3.prompt_assets import fill, prompt_text
from whymath_backend.l3.router import Router

# 학생 요청 라우팅 신호 기본값 — 6개 호출부 공용 단일 좌석(OPS-18, `api/visualization.py` 미러).
_STUDENT_ESCALATION_DEFAULTS = default_student_escalation_signals()

__all__ = [
    "QuestionRephraser",
    "RephraseOutcome",
    "classify_invariance_failure",
    "extract_equation",
    "verify_numeric_invariance",
]

_logger = logging.getLogger(__name__)

# 실패 reason-code taxonomy — rephrase가 원문을 유지한 *구조적 사유*를 분류한다(디버깅 온톨로지).
# 우리 게이트는 수치 '값' 동치가 아니라 방정식 '문자열' 보존을 보므로, 코드는 실제 코드 경로에
# 1:1 대응한다(검출 못 하는 사유를 지어내지 않는다 — 정직 taxonomy).
#   NO_EQUATION       발문에서 방정식 substring 추출 실패(봉인 대상 부재·rephrase 미시도)
#   PROVIDER_ERROR    LLM 호출 예외(라이브 provider 부재·네트워크·타임아웃)
#   EMPTY             LLM 빈 출력
#   EQUATION_ALTERED  방정식 문자열 미보존 — 표기·공백·지수·부호 변형(가장 흔한 훼손)
#   EXTRA_EQUATION    방정식 외 추가 '=' — 거짓 등식 주입 벡터
#   HYGIENE_REJECT    위생 validator 거부(격리된 거짓 수치 등식·틀린 해 등)
#   QUESTION_HYGIENE  발문 텍스트 위생 위반(S3-12 — 비한글 스크립트·메타 라벨 누출·비표준
#                     용어·요구-정답 부정합·조사 오류: rephrase_hygiene 결정론 게이트)
#   NO_CHANGE         출력이 원문과 동일 — 다양화 실패(오염 아님·안전). QUAL-03(2026-08-10):
#                     `classify_invariance_failure`에 `original_text`를 넘기면(.rephrase()가
#                     항상 넘긴다) 이 사유가 **정규화 비교**(rephrase_hygiene ⑦축)로 여기서
#                     더 일찍 조기 반환된다 — 공백·유니코드 정규화 차이만 있는 근접 무변화까지
#                     잡는다(바이트 완전일치만 보던 기존 사후 검사보다 촘촘함). 아래
#                     `.rephrase()`의 사후 바이트-완전일치 검사는 그대로 남아 있으나(이중 회계 —
#                     이 배선이 빠지는 회귀가 나도 바이트 완전일치만큼은 계속 잡는다), 현재는
#                     이 축이 항상 먼저 걸려 실질적으로 도달하지 않는다(수학적으로: 바이트
#                     완전일치는 정규화 완전일치를 항상 함의하므로).
REASON_NO_EQUATION = "NO_EQUATION"
REASON_PROVIDER_ERROR = "PROVIDER_ERROR"
REASON_EMPTY = "EMPTY"
REASON_EQUATION_ALTERED = "EQUATION_ALTERED"
REASON_EXTRA_EQUATION = "EXTRA_EQUATION"
REASON_HYGIENE_REJECT = "HYGIENE_REJECT"
REASON_QUESTION_HYGIENE = "QUESTION_HYGIENE"
REASON_NO_CHANGE = "NO_CHANGE"


# 시스템 프롬프트 v3 — **경량 회귀 + 정책 앵커**(2026-07-07 라이브 A/B 실측 근거).
# 문면의 정본은 `docs/prompts/l3_rephrase.md`이며 v2 기각(수율 82%→57%·n=100·~6σ)의 실측
# 경위도 거기 있다(OPS-16 — 코드에 사본을 두지 않는다). 봉인 레일ⓑ(수치·정답 불변 지시문)는
# `harness/prompt_asset_audit`가 CI에서 실재를 감사한다. 정본 부재·파손은 폴백 없이
# `PromptAssetError`(fail-closed — 봉인 없는 다양화 금지).
@lru_cache(maxsize=1)
def _system_prompt() -> str:
    """발문 다양화 시스템 프롬프트 — 정본 1회 로드·캐시(매 호출 파일 I/O 금지)."""
    return prompt_text("l3.rephrase.system")


# 발문에서 방정식 문자열을 추출하는 정규식 — 우리 템플릿이 박는 형태를 겨냥한다.
#   ① 로그: 'log_5 x = 2' — **log_ 접두를 포함해 통째로** 잡는다. leftmost 우선이라 'log'에서
#      먼저 매치돼 온전한 등식을 앵커한다(2026-07-07 수복). 이 대안이 없으면 두 번째 대안이
#      base부터 잡아 'log_5 x = 2'를 '5 x = 2'(선형식처럼 보이는 부분)로 오추출 → 프롬프트 앵커가
#      틀려 log rephrase 수율이 붕괴한다(라이브 실측: exp/log ~0%).
#   ② 그 외(이차·지수): '3x^2 - 7x + 4 = 0'·'(x - 1)^2 = 2'·'5^x = 25'. 시작은 숫자/x/여는 괄호,
#      중간은 수식 문자(한글 미포함이라 발문 자연어 경계에서 멈춘다), 끝은 '= 정수'.
_EQUATION_RE = re.compile(r"log_[0-9]+\s*x\s*=\s*[0-9]+|[0-9x(][0-9x^()+\-*/ ]*=\s*[0-9]+")


@dataclass(frozen=True, slots=True)
class RephraseOutcome:
    """rephrase 1건 결과 — 최종 발문 + 실제 변경 여부 + 사유·reason-code·원 LLM 출력.

    `text`는 항상 유효한 발문이다: rephrase가 검증을 통과하면 다양화된 문장, 실패(추출 불가·검증
    실패·provider 예외)면 **원문 그대로**(fail-closed — 비결정 오염이 수치에 새지 않음). `rephrased`
    가 False면 `reason`이 왜 원문을 유지했는지(사람용 문장)·`reason_code`가 구조적 분류(taxonomy·
    위 `REASON_*`)를 준다. `raw_output`은 실패 시 LLM이 실제로 낸 문자열(검증 전)이라 무엇이 봉인을
    깼는지 사후 디버깅할 수 있다(성공·추출 실패 시 None). 조용한 실패 금지 + 사후 분석 가능.
    """

    text: str
    rephrased: bool
    reason: str | None = None
    reason_code: str | None = None
    raw_output: str | None = None


def extract_equation(question_text: str) -> str | None:
    """발문에서 방정식 문자열을 추출 — 없으면 None(rephrase 봉인 불가·fail-closed 신호).

    우리 스켈레톤 템플릿이 박은 단일 방정식을 겨냥한다. 매치가 없으면(예상 밖 형태) None을
    돌려 호출부가 rephrase를 건너뛰게 한다(수치 봉인 대상을 못 찾으면 변형하지 않는다).
    """
    match = _EQUATION_RE.search(question_text)
    return match.group(0).strip() if match is not None else None


def classify_invariance_failure(
    rephrased_text: str,
    *,
    equation: str,
    validator: SeedValidator | None = None,
    original_text: str | None = None,
) -> str | None:
    """rephrase 결과가 수치 불변 봉인을 어겼으면 *어느 관문*인지 reason-code로 분류 — 통과=None.

    검사 순서(먼저 걸린 사유 반환): ① 비어있음(`EMPTY`) ② 방정식 substring 미보존
    (`EQUATION_ALTERED` — 표기·공백·지수·부호 변형) ③ 방정식 외 추가 `=`(`EXTRA_EQUATION` —
    거짓 등식 주입) ④ 위생 validator 거부(`HYGIENE_REJECT`) ⑤ 발문 텍스트 위생 위반
    (`QUESTION_HYGIENE` — S3-12 결정론 게이트: 비한글 스크립트·메타 라벨·비표준 용어·
    요구-정답 부정합·조사 오류) ⑥ 무변화(`NO_CHANGE` — QUAL-03·`original_text`가 주어지고
    정규화 후 원문과 일치하면. `rephrase_hygiene`의 ⑦축을 재사용하되, 반환 코드는 새로 만들지
    않고 기존 `NO_CHANGE` taxonomy를 그대로 쓴다 — "다양화가 실질적으로 안 됨"이라는 같은 실패
    범주이기 때문이다, 위 `REASON_NO_CHANGE` 정의부 주석 참고). 모두 통과면 None(수치 불변).

    이것이 검증의 단일 진실 원천이다 — `verify_numeric_invariance`가 이 위에 얇게 얹힌다(중복
    로직 금지). reason-code는 진단 harness가 실패를 taxonomy로 집계하고 raw 출력을 dump해 "왜
    깨졌나"를 사후 분석하게 한다(온톨로지화). LLM·DB·네트워크 0(순수 결정론).

    ③이 핵심 봉인인 이유: 위생 validator(default_seed_validator)는 한글 문장 사이에 임베디드된
    거짓 산술식('… 2+2=5 …')을 토큰화 한계로 놓친다(실측). 우리 발문은 방정식 외 `=`이 없으므로,
    보존 방정식을 뺀 나머지에 `=`가 남으면 곧 LLM이 새 등식을 주입한 것이다 — 구조로 차단한다.
    정상 rephrase는 발문에 `=`을 추가하지 않으므로(프롬프트도 명령) 거짓 거부가 없다.
    """
    text = rephrased_text.strip()
    if not text:
        return REASON_EMPTY
    if equation not in text:
        return REASON_EQUATION_ALTERED  # 방정식 substring 봉인 위반 — 수식·표기 변형.
    if "=" in text.replace(equation, "", 1):
        return REASON_EXTRA_EQUATION  # 방정식 외 추가 등식 — 거짓 등식 주입.
    active = validator if validator is not None else default_seed_validator()
    if validate_response(active, text) is not None:
        return REASON_HYGIENE_REJECT  # 위생 게이트 — 격리된 거짓 수치 등식/부등식/틀린 해.
    violations = question_hygiene_violations(text, original_text=original_text)
    if violations:
        if any(v.split(":", 1)[0] == REASON_UNCHANGED_FROM_ORIGINAL for v in violations):
            # 무변화(⑦) — 발문 문법 자체는 정상이라 QUESTION_HYGIENE이 아니라 기존 NO_CHANGE
            # taxonomy로 매핑한다(QUAL-03 — 위 함수 docstring ⑥ 참고).
            return REASON_NO_CHANGE
        # 발문 텍스트 위생(S3-12) — 한자·가나 주입/메타 라벨/비표준 용어/방법-값 부정합/조사
        # 오류는 결정론 교정이 불가하므로 fail-closed(원문 유지)로 차단한다(감사 결함 5류 ⑤).
        return REASON_QUESTION_HYGIENE
    return None


def verify_numeric_invariance(
    rephrased_text: str,
    *,
    equation: str,
    validator: SeedValidator | None = None,
    original_text: str | None = None,
) -> str | None:
    """rephrase 결과의 수치 불변을 결정론으로 검증 — 통과=정제 문자열, 실패=None.

    `classify_invariance_failure`에 위임한다(단일 진실 원천) — 사유 코드가 없으면(통과) strip한
    문자열을, 있으면 None을 돌려 호출부가 원문을 유지하게 한다(fail-closed). `original_text`는
    그대로 전달만 한다(선택 인자·기본 None — QUAL-03 무변화 축, 기존 호출부 회귀 0).
    """
    if (
        classify_invariance_failure(
            rephrased_text, equation=equation, validator=validator, original_text=original_text
        )
        is not None
    ):
        return None
    return rephrased_text.strip()


class QuestionRephraser:
    """발문 다양화기 — provider 주입·라우터 경유·수치 불변 검증(fail-closed).

    `provider`(LLMProvider)를 주입한다(테스트=FakeProvider·라이브=CompositeProvider). None이면
    표준 CompositeProvider를 지연 구성하나, 이 환경엔 LLM이 없어 라이브 호출을 하지 않는다(실
    구동은 Phaiakes9). `rephrase`는 항상 유효한 발문을 돌려준다(검증 실패 시 원문 — fail-closed).
    """

    def __init__(
        self,
        provider: LLMProvider | None = None,
        *,
        # 기본 0.7 — 라이브 스윕 실측(repeats 5·온도당 n=250): 0.7=78.4% vs 0.9=72.8%(+5.6%p·
        # 약 2σ)·7회 비교 중 6회 0.7 우세. 고온일수록 방정식 표기 훼손(EQUATION_ALTERED)이 늘어
        # 순 수율이 떨어진다(2026-07-07 결정 로그).
        temperature: float = 0.7,
        authoring_family: ModelFamily | None = ModelFamily.GENERAL,
        subscription: str = _STUDENT_ESCALATION_DEFAULTS.student_subscription,
        validator: SeedValidator | None = None,
    ) -> None:
        self._provider = provider
        self._temperature = temperature
        self._authoring_family = authoring_family
        self._subscription = subscription
        self._validator = validator if validator is not None else default_seed_validator()
        self._loop: asyncio.AbstractEventLoop | None = None

    def rephrase(self, question_text: str) -> RephraseOutcome:
        """발문 1건을 다양화 — 수식 보존·위생 통과 시 정제, 아니면 원문(fail-closed).

        실패 시 `reason_code`(taxonomy)와 `raw_output`(LLM 실제 출력)을 실어 사후 진단을 가능케
        한다 — 성공·추출 실패 외에는 원 출력을 버리지 않는다(무엇이 봉인을 깼는지 dump 가능).
        """
        equation = extract_equation(question_text)
        if equation is None:
            return RephraseOutcome(
                question_text, False, "방정식 추출 실패 — 봉인 대상 부재", REASON_NO_EQUATION
            )

        try:
            raw = self._invoke(question_text, equation)
        except Exception as error:  # noqa: BLE001 — provider 장애는 조용한 크래시 금지·원문 폴백
            _logger.warning("발문 rephrase provider 예외 — 원문 유지: %s", error)
            return RephraseOutcome(
                question_text, False, f"provider 예외: {error}", REASON_PROVIDER_ERROR
            )

        # original_text=question_text — QUAL-03 실제 생성 수용 게이트 배선(rephrase_hygiene ⑦축).
        # 정규화 비교라 아래의 사후 바이트-완전일치 검사보다 먼저·더 촘촘하게 무변화를 잡는다.
        failure = classify_invariance_failure(
            raw, equation=equation, validator=self._validator, original_text=question_text
        )
        if failure is not None:
            return RephraseOutcome(
                question_text, False, "수치 불변 검증 실패 — 원문 유지", failure, raw_output=raw
            )
        verified = raw.strip()
        if verified == question_text:
            # 방어적 이중 검사(현재는 도달 전에 위 classify_invariance_failure의 무변화 축이
            # 항상 먼저 걸러낸다 — 바이트 완전일치는 정규화 완전일치를 함의하므로). original_text
            # 배선이 위 호출부에서 빠지는 회귀가 나더라도 바이트 완전일치만큼은 여전히 잡는다
            # (CLAUDE.md 이중 회계 원칙과 동형 — 판정 경로를 하나로 좁히지 않는다).
            return RephraseOutcome(
                question_text, False, "출력이 원문과 동일 — 다양화 없음", REASON_NO_CHANGE, raw
            )
        return RephraseOutcome(verified, True, None)

    # ── LLM 호출(라우터 경유·GENERAL 저작 패밀리·지속 이벤트 루프) ────────
    def _invoke(self, question_text: str, equation: str) -> str:
        provider = self._resolve_provider()
        decision = self._decide_routing()
        prompt = _build_prompt(question_text, equation)
        # provider 반환은 GenerationResult(text, usage) — rephrase는 텍스트만 소비.
        generated = self._ensure_loop().run_until_complete(
            provider.generate(
                prompt,
                _system_prompt(),
                decision,
                temperature=self._temperature,
            )
        )
        return generated.text

    def _resolve_provider(self) -> LLMProvider:
        if self._provider is None:
            # 지연 구성 — 라이브(Phaiakes9)만 도달. hermetic 테스트는 항상 주입.
            from whymath_backend.l3.providers.composite import CompositeProvider
            from whymath_backend.l3.providers.factory import build_cloud_provider
            from whymath_backend.l3.providers.ollama import OllamaProvider

            self._provider = CompositeProvider(local=OllamaProvider(), cloud=build_cloud_provider())
        return self._provider

    def _decide_routing(self) -> RoutingDecision:
        """라우터 결정 + 저작 패밀리 선호(GENERAL) — llm_generator._decide_routing 축소 미러.

        rephrase는 다단계 추론이 아니라 문장 다양화(instruction-following)라 requires_reasoning=
        False·난이도 easy로 라우팅한다(로컬 FAST 즉답·저비용). 로컬 FAST/MID 결정의 패밀리 축만
        GENERAL로 갈아탄다(라우터의 비용·크기·모드는 존중).
        """
        from whymath_backend.l3.models import CostTier, LocalModelTier

        request = RoutingRequest(
            task_type="generate",
            difficulty="easy",
            requires_reasoning=False,
            student_subscription=self._subscription,
            budget_krw=_STUDENT_ESCALATION_DEFAULTS.budget_krw,  # 단일 좌석 값(OPS-18·회귀 0)
            sync=True,
            # 등급: 다양화 대상은 *자체 저작 동등문제*의 발문이다(평가원·EBS·교과서 본문은
            # 애초에 코퍼스에 없다 — 저작권 레일). 자체 저작이라 반출 가능(EOS-59).
            data_licenses=SELF_AUTHORED_CORPUS,
        )
        decision = Router().route(request)
        if self._authoring_family is None:
            return decision
        is_local = decision.cost_tier == CostTier.LOCAL.value
        family_applicable = is_local and decision.local_model in (
            LocalModelTier.FAST.value,
            LocalModelTier.MID.value,
        )
        if not family_applicable or decision.local_family == self._authoring_family.value:
            return decision
        return RoutingDecision(
            cost_tier=decision.cost_tier,
            local_family=self._authoring_family,
            local_model=decision.local_model,
            mode=decision.mode,
            reason=f"{decision.reason} → rephrase:{self._authoring_family.value}",
            est_latency_ms=decision.est_latency_ms,
            est_cost_krw=decision.est_cost_krw,
            # 데이터 등급 게이트의 판정·발동 신호는 *승계*한다 — 여기서는 패밀리 축만
            # 갈아탈 뿐 법적 판정을 다시 하지 않는다. 안 실어 보내면 원본 결정이 게이트에
            # 막혔다는 사실이 관측에서 조용히 사라진다(발동률 과소집계·EOS-59 ②).
            data_export_blocked=decision.data_export_blocked,
            data_export_reason=decision.data_export_reason,
        )

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        """인스턴스 전용 지속 이벤트 루프 — provider 커넥션 풀 재사용(llm_generator 동형)."""
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
        return self._loop


def _build_prompt(question_text: str, equation: str) -> str:
    """사용자 프롬프트 — 원 발문 + 보존해야 할 방정식 문자열을 명시(Minimal context).

    "복사해 붙여넣듯"·"한 글자도 바꾸지 말고"로 보존 지시를 이중 반복한다 — 실측 실패의 100%가
    방정식 표기 훼손(EQUATION_ALTERED)이라 attention을 방정식 문자열에 앵커링한다.
    문면은 `docs/prompts/l3_rephrase.md` 정본 인용(OPS-16) — 여기서 채우는 것은 *값*뿐이다.
    """
    return fill(prompt_text("l3.rephrase.user"), QUESTION_TEXT=question_text, EQUATION=equation)
