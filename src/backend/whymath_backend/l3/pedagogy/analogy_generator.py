"""개념 비유 생성기 — 정본: `docs/architecture/04e_pedagogy_strategy_catalog.md` §6(기능⑯·PED-09).

`slot_generator.py`가 의도적으로 연기해 둔 LLM 생성 경로의 *비유(개념-grain)* 해제다 — 04e §6.1이
소비처를 명시했다: **정본 좌석 = `concept_content.metaphor`**(공백·저품질 채움이 1차 표적),
렌더 소비 경로 = `metaphor → ConceptDSL.intuition → AnalogyAdapter`(기존 경로·기소비). 생성 산출을
슬롯에만 넣으면 AnalogyAdapter가 영원히 읽지 않으므로(배선 없는 생성), 검수 통과분은 반드시
`concept_content.metaphor`로 착지한다(`MetaphorFillStore`).

파이프라인(04e §6.2 — L4=결정·L3=생성 준수):
    표적 계획(select-vs-generate·공백/결함/탈락분만) → LLM 생성(라우터 경유) → DRAFT
    → prescreen → review+비유 결함 검출(`analogy_checker`) → APPROVED만 metaphor 채움

상태기계 재사용 방식(정직한 설계 메모): `pedagogy_content_slot` 테이블은 `objective_id` FK
(목표-grain)를 강제하므로 개념-grain 비유 행을 그 테이블에 넣으면 **grain 불일치 데이터**가 된다
(04e §7.2가 경고하는 "다리 없는 채움"). 그래서 *테이블*이 아니라 **상태기계 함수·전이 규약**을
재사용한다 — 같은 `prescreen_slot`(0..3 루브릭)·`review_slot`(기계 게이트)·같은 상태 전이
(DRAFT→PRESCREENED→APPROVED|REJECTED)를 in-memory 초안 행에 적용하고, 종착만 §6.1 좌석
선언대로 `concept_content.metaphor` UPDATE로 간다(예시 grain은 슬롯 테이블을 그대로 쓴다).

상한 불변식(04e §6.4 — 교육적 압축): 개념당 비유 1(레지스터는 파라미터·독립 생성기 금지)·
**사전 대량 생성 금지** — `plan_analogy_targets`가 공백·결함·검수 탈락분만 표적으로 뽑고, 무결함
기존 비유는 구조적으로 표적에서 배제한다(select-vs-generate). 오개념 교정 비유는 신설하지 않는다
(반례 자산 기담당·오개념은 reactive-only·04c).

LLM 경로(선례 `l3/equivalent/llm_generator.py` 미러): 라우터 경유(직접 호출 금지)·provider 주입
seam(`LLMProvider | None` — 테스트는 Fake·이 컨테이너에 로컬 LLM 없음)·저작 패밀리 GENERAL 스왑·
JSON 관대 파싱·실패 전부 None 폴백(+경고 로그·침묵 실패 금지). **라이브 채움 실행은 Phaiakes9
런북 소관**이다 — 이 모듈은 생성기·게이트·착지 좌석까지만 놓는다(정직한 공백).

7계층: L3 콘텐츠 생성. 검수 함수(`prescreen`/`review`)·sync 엔진 빌더(L1)를 재사용한다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from whymath_backend.config import Settings
from whymath_backend.db.models.concept_content import CONTENT_REVIEW_STATUS_AI_ESTIMATED
from whymath_backend.l1.embedding_primitives import build_sync_engine
from whymath_backend.l3.data_grade_defaults import SELF_AUTHORED_CORPUS
from whymath_backend.l3.interfaces import LLMProvider, TraceSink
from whymath_backend.l3.models import (
    CostTier,
    GenerationResult,
    LocalModelTier,
    ModelFamily,
    RoutingDecision,
    RoutingRequest,
    Usage,
)
from whymath_backend.l3.pedagogy.analogy_checker import check_analogy_defects
from whymath_backend.l3.pedagogy.prescreen import prescreen_slot
from whymath_backend.l3.pedagogy.review import ReviewVerdict, review_slot
from whymath_backend.l3.pedagogy.slot_generator import _is_tts_safe
from whymath_backend.l3.router import Router, _as_cost_tier, actual_cost_krw, langfuse_fields

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

_LOGGER = logging.getLogger(__name__)

# 개념당 비유 상한(04e §6.4) — 레지스터 변형은 파라미터로 소수만(독립 생성기 금지).
MAX_ANALOGY_PER_CONCEPT: Final[int] = 1

# 표적 사유 폐쇄 어휘 — select-vs-generate의 발주 근거(이 밖의 사유로 생성 금지·동결 테스트).
ANALOGY_TARGET_REASONS: Final[frozenset[str]] = frozenset(
    {
        "blank",  # metaphor 공백(렌더 불가 — ConceptDSL.intuition None)
        "defective",  # 기존 metaphor가 규칙 검출 결함 보유(저품질 ai_estimated)
        "rejected",  # 이전 생성분 검수 탈락(재발주)
    }
)

# 학년 레지스터 허용값 — 카탈로그 ANALOGY 카드 target_grade_bands와 동일 축(파라미터·생성기 아님).
ANALOGY_REGISTERS: Final[frozenset[str]] = frozenset({"초등", "중학", "고등", "대학"})

# 비유 초안의 reasoning_type — 슬롯 유형이 아니라 *개념-grain 은유*임을 표기(상태기계 함수 호환 키).
_METAPHOR_REASONING_TYPE: Final[str] = "concept_metaphor"


# ──────────────────────────────────────────────────────────────────────────
# 시스템 프롬프트 — 교수학 제약(04e §6·카탈로그 ANALOGY 카드 usage_notes를 문면으로 강제)
# ──────────────────────────────────────────────────────────────────────────
ANALOGY_SYSTEM_PROMPT: Final[
    str
] = """당신은 WhyMath의 **개념 비유 저작자**입니다. 주어진 수학 개념 1개에 대해 학생의 직관을
세우는 비유(은유) 1개를 지어 JSON 하나로만 출력하세요.

## 좋은 비유의 기준 (구조 매핑 — 반드시 지킬 것)
- **표면 유사성이 아니라 관계 구조의 대응**으로 비유하세요(Gentner 구조 매핑). 겉모습이
  닮은 소재가 아니라, 개념 안의 *관계*(입력→출력, 커짐→가까워짐 등)가 그대로 대응되는
  친숙한 상황을 고르세요.
- **비유가 어디서 깨지는지 반드시 함께 밝히세요** — 비유 본문 안에 "다만 ~는 다르다/
  ~에서는 이 비유가 깨진다" 형태의 한계 문장을 포함하고, `breaks` 필드에도 요약하세요.
  한계를 밝히지 않은 비유는 오개념을 심습니다(예: "함수=자판기" 비유가 일대일대응
  오개념을 심는 위험).

## 절대 금기
- **비유는 정의를 대신하지 않습니다** — "이것이 정의다"라고 쓰지 말고, 동일시 단정
  ("완전히 같다"·"똑같다"·"그 자체다")도 금지합니다. "~처럼"·"~같이"의 빗댐 서법만 쓰세요.
- **게임형 산출 금지** — 레벨업·퀘스트·경험치·랭킹·보상 같은 게임화 메커닉을 넣지 마세요.
- 문제의 정답을 흘리지 마세요(비유는 개념 직관용이지 풀이 지름길 제공이 아닙니다).
- 교과서·기출 문장을 복제하지 말고 순수 자작으로 쓰세요.

## 학년 레지스터
지시된 레지스터(초등/중학/고등/대학)의 언어 수준으로 쓰세요 — 같은 개념이라도 레지스터에
맞는 소재·어휘를 고릅니다(레지스터는 입력 파라미터입니다).

## 출력 형식 — JSON 객체 하나만 (코드펜스·설명 없이)
{"analogy": "비유 본문(한계 문장 포함·2~4문장·한국어)", "breaks": "이 비유가 깨지는 지점 한 줄"}
"""


# ──────────────────────────────────────────────────────────────────────────
# 표적 계획(select-vs-generate) — 공백·결함·검수 탈락분만 발주
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class AnalogyTarget:
    """비유 생성 표적 1건 — 개념 code + 발주 사유(폐쇄 어휘) + 레지스터.

    `reason`은 `ANALOGY_TARGET_REASONS` 안이어야 한다 — 사전 대량 생성(무사유 발주)을 타입
    수준에서 배제한다(04e §6.4 상한 불변식).
    """

    code: str
    name: str
    subject: str
    reason: str  # "blank" | "defective" | "rejected"
    register: str = "고등"

    def __post_init__(self) -> None:
        if self.reason not in ANALOGY_TARGET_REASONS:
            raise ValueError(
                f"비유 발주 사유 위반: {self.reason!r} — 허용 사유 {sorted(ANALOGY_TARGET_REASONS)}"
                " (공백·결함·검수 탈락분만 발주한다 — 04e §6.4 사전 대량 생성 금지)"
            )
        if self.register not in ANALOGY_REGISTERS:
            raise ValueError(
                f"학년 레지스터 위반: {self.register!r} — 허용 {sorted(ANALOGY_REGISTERS)}"
            )


def plan_analogy_targets(
    records: Iterable[Any],
    *,
    rejected_codes: Sequence[str] = (),
    register: str = "고등",
) -> list[AnalogyTarget]:
    """콘텐츠 레코드(코퍼스/ORM 행)에서 비유 생성 표적을 계획 — select-vs-generate.

    표적 = ①metaphor 공백(blank) ②기존 metaphor가 규칙 검출 결함 보유(defective)
    ③이전 생성분 검수 탈락(rejected — 호출자가 code 목록으로 주입). **무결함 기존 비유는
    표적에서 구조적으로 배제**된다(04e §6.4 — 발주는 공백·검수 탈락분만). 개념당 1건으로
    dedup한다(`MAX_ANALOGY_PER_CONCEPT`·첫 사유 우선). 입력 레코드는 `code`/`name`/`subject`/
    `metaphor` 속성만 있으면 된다(코퍼스 `ConceptContentRecord`·ORM 행 양쪽 호환 duck-typing).
    """
    rejected = {str(code) for code in rejected_codes}
    targets: list[AnalogyTarget] = []
    seen: set[str] = set()
    for record in records:
        code = str(record.code)
        if code in seen:
            continue  # 개념당 1건(상한 불변식) — 중복 레코드는 첫 건만.
        metaphor = getattr(record, "metaphor", None)
        text = str(metaphor).strip() if metaphor is not None else ""
        if not text:
            reason = "blank"
        elif code in rejected:
            reason = "rejected"
        elif check_analogy_defects(text):
            reason = "defective"
        else:
            continue  # 무결함 기존 비유 — 재생성 발주 금지(select-vs-generate).
        seen.add(code)
        targets.append(
            AnalogyTarget(
                code=code,
                name=str(record.name),
                subject=str(record.subject),
                reason=reason,
                register=register,
            )
        )
    return targets


# ──────────────────────────────────────────────────────────────────────────
# LLM 생성기 (라우터 경유·provider 주입 seam — llm_generator 선례 미러)
# ──────────────────────────────────────────────────────────────────────────
class AnalogyGenerator:
    """개념 비유 LLM 생성기 — 라우터 경유·주입 seam·실패 None 폴백(크래시 금지).

    `LLMEquivalentProblemGenerator`(S2-e)의 *비유* 짝이다: provider 주입(None이면 표준
    CompositeProvider·지연 연결), `Router().route()` 결정 존중 + 로컬 FAST/MID의 패밀리 축만
    GENERAL로 스왑(저작은 instruction-following 과업 — qwen2-math는 저작 mode collapse 실측·
    S2-h 동형), 고온도(다양성), 관측(TraceSink) 기록. 산출은 `pedagogy_content_slot` 행과 같은
    형태의 **in-memory DRAFT 행**이다(개념-grain이라 슬롯 테이블 미적재 — 모듈 docstring).
    """

    def __init__(
        self,
        provider: LLMProvider | None = None,
        *,
        settings: Settings | None = None,
        trace: TraceSink | None = None,
        subscription: str = "free",
        temperature: float = 0.9,
        authoring_family: ModelFamily | None = ModelFamily.GENERAL,
    ) -> None:
        """생성기 구성 — provider/trace 미주입 시 표준 구성(지연 연결·네트워크 0).

        Args:
            provider: L3 LLM provider(라우터 경유 필수). None이면 CompositeProvider 구성.
            settings: 앱 설정(선택 — trace 기본 구성에 전달).
            trace: 관측 싱크. None이면 LangfuseSink(키 미설정=no-op) — "모든 LLM 호출 →
                Langfuse 추적"(llm_generator 관측 공백 보정 선례 미러).
            subscription: 라우팅 구독 신호(기본 free=LOCAL 강제 — 저작 배치는 로컬 우선).
            temperature: 저작 다양성 온도(S2-g 선례 — 콘텐츠 저작은 고온도).
            authoring_family: 로컬 FAST/MID 결정의 패밀리 스왑(S2-h 선례·None=라우터 그대로).
        """
        if provider is None:
            # 표준 저작 구성 — 지연 연결이라 구성만으로 네트워크 0. 클라우드 좌석은
            # `settings.cloud_provider`가 정한다(ARCH-57). **app.py와는 의도적으로
            # 다르다** — 학생 대면 서빙은 셀렉터를 타지 않는다(ARCH-56 게이트 ⓐ).
            from whymath_backend.l3.providers.composite import CompositeProvider
            from whymath_backend.l3.providers.factory import build_cloud_provider
            from whymath_backend.l3.providers.ollama import OllamaProvider

            provider = CompositeProvider(local=OllamaProvider(), cloud=build_cloud_provider())
        if trace is None:
            from whymath_backend.l3.trace.langfuse_sink import LangfuseSink

            trace = LangfuseSink(settings=settings)
        self._provider = provider
        self._trace = trace
        self._subscription = subscription
        self._temperature = temperature
        self._authoring_family = authoring_family
        # 배치용 지속 이벤트 루프(지연 생성) — asyncio.run 반복이 provider 커넥션 풀을 죽이는
        # 실측 회귀 방어(llm_generator `_ensure_loop` 미러).
        self._loop: asyncio.AbstractEventLoop | None = None

    # ── 공개 API ───────────────────────────────────────────────────────
    def generate_draft(self, target: AnalogyTarget) -> dict[str, Any] | None:
        """표적 1건의 비유 DRAFT 행 생성 — 실패 시 None(안전 폴백·크래시 금지).

        흐름: 프롬프트 조립 → 라우터 결정(+저작 패밀리 스왑) → provider.generate(라우터 경유)
        → JSON 관대 파싱 → DRAFT 행 조립. 반환 행은 상태기계 함수(`prescreen_slot`/`review_slot`)
        호환 형태다: `{id, target_code, register, reason, payload{body,breaks,reasoning_type,
        structure_tags}, sympy_verified=None, tts_safe, status='DRAFT'}`.
        """
        prompt = self._build_user_prompt(target)
        decision = self._decide_routing()
        try:
            generated = self._invoke(prompt, decision)
        except Exception as exc:  # noqa: BLE001 — provider 장애 시 배치 크래시 금지·안전 폴백.
            _LOGGER.warning(
                "비유 생성 provider 호출 실패(%s) — None 폴백: %s", type(exc).__name__, exc
            )
            return None
        # LLM 호출 성공 = 비용 발생 — 파싱 성패와 무관하게 관측을 먼저 남긴다(선례 미러).
        self._record_trace(decision, generated.usage)
        data = _extract_json(generated.text)
        if data is None:
            _LOGGER.warning("비유 생성 응답 JSON 파싱 실패 — None 폴백.")
            return None
        analogy = data.get("analogy")
        breaks = data.get("breaks")
        if not isinstance(analogy, str) or not analogy.strip():
            _LOGGER.warning("비유 생성 응답 analogy 필드 결측/무효 — None 폴백.")
            return None
        if not isinstance(breaks, str) or not breaks.strip():
            # "비유가 어디서 깨지는지" 동봉은 04e §6.3 생성 계약 — 결측은 생성 실패다.
            _LOGGER.warning("비유 생성 응답 breaks(깨짐 명시) 결측 — None 폴백(04e §6.3 계약).")
            return None
        return build_analogy_draft_row(target, analogy.strip(), breaks.strip())

    # ── 내부: 라우팅·호출·관측 (llm_generator 미러) ─────────────────────
    def _decide_routing(self) -> RoutingDecision:
        """라우터 결정 + 저작 패밀리 스왑(S2-h 동형) — 비용·크기·모드 결정은 그대로 존중."""
        decision = Router().route(
            RoutingRequest(
                task_type="generate",
                difficulty="medium",
                requires_reasoning=True,
                student_subscription=self._subscription,
                sync=True,
                # 등급: 비유 생성 프롬프트에는 자체 개념 그래프의 대상 개념만 실린다 —
                # 학생 자료·제3자 저작물 없음(EOS-59).
                data_licenses=SELF_AUTHORED_CORPUS,
            )
        )
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
            reason=f"{decision.reason} → 저작:{self._authoring_family.value}",
            est_latency_ms=decision.est_latency_ms,
            est_cost_krw=decision.est_cost_krw,
            # 데이터 등급 게이트의 판정·발동 신호는 *승계*한다 — 여기서는 패밀리 축만
            # 갈아탈 뿐 법적 판정을 다시 하지 않는다. 안 실어 보내면 원본 결정이 게이트에
            # 막혔다는 사실이 관측에서 조용히 사라진다(발동률 과소집계·EOS-59 ②).
            data_export_blocked=decision.data_export_blocked,
            data_export_reason=decision.data_export_reason,
        )

    def _invoke(
        self, prompt: str, decision: RoutingDecision, *, system: str = ANALOGY_SYSTEM_PROMPT
    ) -> GenerationResult:
        """provider.generate(async)를 sync 배치 경계에서 실행 — 지속 루프(`_ensure_loop`).

        `system` 기본값은 비유 프롬프트다 — `ExampleGenerator`가 같은 호출 경로(라우팅·루프·
        관측)를 조성 재사용하면서 예시 프롬프트로 갈아끼우는 주입 지점(중복 구현 0).
        """
        return self._ensure_loop().run_until_complete(
            self._provider.generate(
                prompt,
                system,
                decision,
                temperature=self._temperature,
            )
        )

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        """인스턴스 전용 이벤트 루프 지연 생성(배치 커넥션 풀 보존 — llm_generator 실측 선례)."""
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
        return self._loop

    def _record_trace(self, decision: RoutingDecision, usage: Usage | None) -> None:
        """생성 1건의 라우팅·실측을 sink에 기록 — never-break(예외 타입명 로그·침묵 실패 금지)."""
        actual_krw: float | None
        is_cloud = _as_cost_tier(decision.cost_tier) is not CostTier.LOCAL
        if usage is None:
            actual_krw = None
        elif is_cloud and (usage.input_tokens is None or usage.output_tokens is None):
            actual_krw = None
        else:
            actual_krw = actual_cost_krw(decision, usage)
        try:
            self._trace.record(
                langfuse_fields(decision, cache_hit=False, usage=usage, cost_krw=actual_krw)
            )
        except Exception as exc:  # noqa: BLE001 — 관측 장애가 저작 배치를 깨면 안 됨
            _LOGGER.warning("비유 생성 관측 기록 실패(%s) — 무시하고 계속", type(exc).__name__)

    @staticmethod
    def _build_user_prompt(target: AnalogyTarget) -> str:
        """표적 1건의 사용자 프롬프트 — 개념명·과목·레지스터만(Minimal context·과다 주입 금지)."""
        return (
            f"개념: {target.name} (과목: {target.subject}, 코드: {target.code})\n"
            f"학년 레지스터: {target.register}\n"
            "위 개념의 비유 1개를 구조 매핑 기준으로 지어 JSON 하나로만 출력하세요 — "
            "비유가 깨지는 지점을 본문과 breaks 필드에 반드시 밝히세요."
        )


# ──────────────────────────────────────────────────────────────────────────
# JSON 관대 추출 — llm_generator `_extract_json`의 축약 미러(코드펜스·주변 산문 허용)
# ──────────────────────────────────────────────────────────────────────────
def _extract_json(raw: str) -> dict[str, object] | None:
    """원시 텍스트에서 JSON 객체를 관대하게 추출 — 실패 시 None(wh1_llm_policy 동형 미러)."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    candidates = [text]
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


# ──────────────────────────────────────────────────────────────────────────
# DRAFT 행 조립·상태기계(prescreen→review) 재사용 — 순수 함수
# ──────────────────────────────────────────────────────────────────────────
def build_analogy_draft_row(target: AnalogyTarget, analogy: str, breaks: str) -> dict[str, Any]:
    """비유 초안 → 상태기계 호환 DRAFT 행(순수·결정론).

    행 형태는 `pedagogy_content_slot` 생성 행(`build_slot_rows`)과 동형 키(payload·sympy_verified·
    tts_safe·status)를 가져 `prescreen_slot`/`review_slot`이 무수정으로 적용된다. 개념-grain 키
    (`target_code`·`register`·`reason`)를 별도로 담아 metaphor 착지(`MetaphorFillStore`)가 쓴다.
    수치 검증 재료가 없는 은유라 `sympy_verified=None`(정직 표기·개념형 슬롯 동형).
    """
    payload: dict[str, Any] = {
        "body": analogy,
        "breaks": breaks,
        "reasoning_type": _METAPHOR_REASONING_TYPE,
        "structure_tags": ["analogy", target.register],
    }
    return {
        "id": f"metaphor:{target.code}:{target.register}",
        "target_code": target.code,
        "register": target.register,
        "reason": target.reason,
        "payload": payload,
        "sympy_verified": None,
        "tts_safe": _is_tts_safe(payload),
        "status": "DRAFT",
    }


@dataclass(frozen=True, slots=True)
class AnalogyOutcome:
    """비유 초안 1건의 상태기계 통과 결과 — 최종 상태 + 예심 점수 + 반려 사유(승인 시 None)."""

    row: dict[str, Any]
    status: str  # "APPROVED" | "REJECTED"
    prescreen_score: int
    reject_reason: str | None


def run_analogy_review(rows: Sequence[dict[str, Any]]) -> list[AnalogyOutcome]:
    """DRAFT 행들을 상태기계(DRAFT→PRESCREENED→APPROVED|REJECTED)에 태운다 — 순수·결정론.

    전이 재사용: ①`prescreen_slot`(0..3 루브릭 — 점수 기록 후 PRESCREENED로 전이·슬롯 파이프라인
    동형) ②`review_slot`(구조+기호 기계 게이트) ③`check_analogy_defects`(비유 4축 결함 — 04e
    §6.3 신설 게이트). ②③ 모두 통과해야 APPROVED, 하나라도 걸리면 REJECTED(사유=첫 결함 코드·
    fail-closed). 게임형 산출은 여기서 GAMIFIED로 반려된다 — **APPROVED 산출의 게임형 0**은 이
    게이트가 구조적으로 보장한다(acceptance "게임형 산출 0 검사"의 생성측 시행 지점).
    """
    outcomes: list[AnalogyOutcome] = []
    for row in rows:
        payload = row["payload"]
        score = prescreen_slot(
            payload,
            sympy_verified=row.get("sympy_verified"),
            tts_safe=row.get("tts_safe"),
        )
        # EOS-89: 비유 payload도 `verification` 주장이 없다 — 능력 주입 불요(위 example_generator
        # 주석과 같은 이유). 주장이 생기면 조용히 통과하지 않고 LookupError로 드러난다.
        verdict: ReviewVerdict = review_slot(payload)
        if verdict.approved:
            # 비유 전용 결함 축 — 본문+깨짐 요약을 합쳐 검사한다(둘 다 학생 노출 후보 문면).
            defects = check_analogy_defects(f"{payload['body']}\n{payload.get('breaks', '')}")
            if defects:
                verdict = ReviewVerdict(False, defects[0])
        approved = verdict.approved
        outcomes.append(
            AnalogyOutcome(
                row=row,
                status="APPROVED" if approved else "REJECTED",
                prescreen_score=score,
                reject_reason=verdict.reason,
            )
        )
    return outcomes


# ──────────────────────────────────────────────────────────────────────────
# 착지: MetaphorFillStore — APPROVED만 `concept_content.metaphor` UPDATE (§6.1 좌석)
# ──────────────────────────────────────────────────────────────────────────
class MetaphorFillStore:
    """검수 통과 비유 → `concept_content.metaphor` 갱신기 — §6.1 정본 좌석 착지(sync).

    `ContentSlotStore`(sync 엔진 재사용·주입 seam)의 *metaphor* 짝이다. `apply`는 APPROVED
    outcome만 UPDATE하며, WHERE 가드로 **공백·ai_estimated 행만** 갱신한다 — 사람 검수를 통과한
    행(review_status≠'ai_estimated')을 기계 산출이 덮어쓰지 않는다(fail-closed).

    `review_status`는 **'ai_estimated'를 유지**한다(정직 표기): 본 기계 게이트가 측정하는 범위는
    규칙 검출 4축뿐이고 의미론 축(SEMANTIC_MISCONCEPTION)은 DEFERRED다 — 'reviewed' 승격은 측정
    범위를 초과하는 overclaim이라 하지 않는다(초인간 검증 기준 — 측정된 것만 주장).
    """

    def __init__(
        self,
        *,
        engine: Engine | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._engine = engine
        self._settings = settings

    def _get_engine(self) -> Engine:
        if self._engine is None:
            from whymath_backend.config import get_settings

            resolved = self._settings if self._settings is not None else get_settings()
            self._engine = build_sync_engine(resolved)
        return self._engine

    def apply(self, outcomes: Sequence[AnalogyOutcome]) -> int:
        """APPROVED outcome의 비유를 metaphor 컬럼에 갱신. 반환=UPDATE 시도 행 수.

        UPDATE 가드: `code == :code AND (metaphor IS NULL OR review_status == 'ai_estimated')`
        — 공백 채움과 저품질(ai_estimated) 교체만 허용, 검수 승격 행은 불변(fail-closed).
        REJECTED outcome은 건드리지 않는다(반려 사유는 호출자·재발주 계획이 소비).
        """
        from sqlalchemy import func, or_, update

        from whymath_backend.db.models.concept_content import ConceptContent

        approved = [o for o in outcomes if o.status == "APPROVED"]
        with self._get_engine().begin() as conn:
            for outcome in approved:
                stmt = (
                    update(ConceptContent)
                    .where(
                        ConceptContent.code == outcome.row["target_code"],
                        or_(
                            ConceptContent.metaphor.is_(None),
                            ConceptContent.review_status == CONTENT_REVIEW_STATUS_AI_ESTIMATED,
                        ),
                    )
                    .values(
                        metaphor=outcome.row["payload"]["body"],
                        # 정직 표기 — 기계 게이트는 규칙 4축만 측정(의미론 DEFERRED) →
                        # review_status는 'ai_estimated' 유지(승격은 overclaim·클래스 docstring).
                        review_status=CONTENT_REVIEW_STATUS_AI_ESTIMATED,
                        updated_at=func.now(),
                    )
                )
                conn.execute(stmt)
        return len(approved)


__all__ = [
    "MAX_ANALOGY_PER_CONCEPT",
    "ANALOGY_TARGET_REASONS",
    "ANALOGY_REGISTERS",
    "ANALOGY_SYSTEM_PROMPT",
    "AnalogyTarget",
    "plan_analogy_targets",
    "AnalogyGenerator",
    "build_analogy_draft_row",
    "AnalogyOutcome",
    "run_analogy_review",
    "MetaphorFillStore",
]
