"""실 LLM 동등문제 생성기 — S2-e(프로덕션 `EquivalentProblemGenerator` 구현).

S2-d 오케스트레이터(`orchestrator.run_equivalent_generation`)의 stub 생성기
(`generator.ScriptedGenerator`)를 대체하는 *프로덕션 LLM 생성기*다. `EquivalenceSpec`을
받아 실 LLM(Phaiakes9 로컬 Qwen3-Math·라우터 경유)으로 *자체생성 동등문제 후보*를 만들어
`CandidateProblem`으로 조립한다. 오케스트레이터는 이 후보를 *신뢰하지 않고* S2-a 게이트
(`evaluate_equivalent_candidate`)로 검증한 뒤에야 저장한다(좌석 계약 동형·재구현 0).

선례(S1-a `harness/wh1_llm_policy.py::LLMTutorPolicy`)를 정확히 미러한다:
  - **provider 주입**: `LLMProvider | None`(None이면 표준 `CompositeProvider` 구성·지연 연결).
    이 환경(클라우드)엔 Ollama·키가 없어 **FakeProvider로 hermetic 검증**하고, Kiki가 Phaiakes9
    에서 실 Ollama provider를 주입해 라이브 구동한다(mock→live 동형·아래 라이브 핸드오프 참조).
  - **라우터 경유**(CLAUDE.md "LLM 호출은 항상 라우터 경유·직접 호출 금지"): `Router().route()`가
    비용·크기를 결정하고 `provider.generate(prompt, system, decision)`로 위임한다.
  - **JSON 관대 파싱**(`_extract_json` 미러·코드펜스/주변 산문 허용).
  - **안전 폴백**(조용한 크래시 금지): 파싱 실패·필수 필드 결측·미지 오개념·provider 예외·
    Problem/Provenance 생성 불변식 위반(저작권 게이트가 생성 거부)은 *전부* `None` 반환 +
    로그. 오케스트레이터가 이를 `generation_failed`로 정직히 기록한다.

**저작권 이중(삼중) 방어** — CLAUDE.md 최우선 금기("검정 교과서·평가원·EBS 본문 복제 절대 금지"):
  ① **프롬프트 지시**: 시스템 프롬프트가 "평가원·EBS·교과서 본문·기출을 절대 복제·재현 금지·
     순수 자작 수식 문제만"을 명령한다.
  ② **코드 강제(구조적)**: LLM 출력의 출처 주장을 *읽지 않고* `Problem.source_type=자체생성`·
     `ContentProvenance.license=WHYMATH_GENERATED`·`generation_type=FULLY_GENERATED`·
     `original_source=None`(본문성 키 0)을 **무조건 박는다**. LLM이 응답에 "평가원 …"이라 써도
     provenance는 자체생성으로 고정된다(구조적 봉인).
  ③ **게이트 최종 봉인**: 생성기가 ①②를 어겨도 S2-a 저작권 게이트(`_evaluate_copyright`)가
     최종 차단한다(오케스트레이터가 `rejected_gate`). 생성기는 *본문 복제 여부를 판정하지 않는다*
     — 그건 사람 검수·후속이며, 여기서는 구조적으로 자체생성 메타만 박고 게이트에 맡긴다.

**레이어 순수성(import-linter 7계층 계약)**: 이 모듈은 **L3**에 산다. L3는 L4를 import할 수
없으므로(역방향 금지) `l4.misconception.catalog.CATALOG_BY_ID`를 *직접 참조하지 않는다*. 대신
오개념 카탈로그(id→한국어 라벨)를 **주입**받는다(`misconception_catalog`) — DistractorEntry
docstring이 못 박은 원칙("L1/L3은 형태만, 카탈로그 실재는 L4·게이트 소관")과 정합한다.
카탈로그를 주입하면 그 키를 allowlist로 삼아 미존재 오개념 id를 드롭하고, 라벨을 프롬프트에
싣는다. 주입이 없으면 `spec.target_misconception_ids`(스펙 저자가 이미 검증한 카탈로그-실재
집합)를 안전 allowlist로 폴백한다. 테스트·라이브 배선은 `CATALOG_BY_ID`를 주입한다(둘 다
계약 면제 지점).

────────────────────────────────────────────────────────────────────────────
라이브 핸드오프 (Kiki·Phaiakes9 실 Ollama Qwen3-Math 구동 절차)
────────────────────────────────────────────────────────────────────────────
이 환경엔 LLM 키·Ollama가 없어 라이브 호출을 하지 않는다(hermetic·FakeProvider만). Phaiakes9
에서 실제로 코퍼스를 생성하려면:

  1. **로컬 Ollama 준비**: Phaiakes9에 Qwen 계열 모델을 pull(라우터 매트릭스 모델 —
     `whymath_backend.l3.router.LOCAL_MODEL_MATRIX`·`QUALITY_MODEL_ID`). 데몬 주소는 환경변수로
     주입한다(시크릿 아님·값 아닌 변수명만):
         export WHYMATH_OLLAMA_HOST=http://127.0.0.1:11434
         export WHYMATH_OLLAMA_REQUEST_TIMEOUT_S=120
     `/status`(OllamaProvider.check_status)로 라우팅 매트릭스 모델 설치 여부를 먼저 확인한다.

  2. **실 provider 주입**(mock→live 전환):
         from whymath_backend.l3.providers.ollama import OllamaProvider
         from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID  # 배선부는 계약 면제
         gen = LLMEquivalentProblemGenerator(
             OllamaProvider(),                       # 실 Ollama(지연 연결)
             misconception_catalog={mid: m.name_kr for mid, m in CATALOG_BY_ID.items()},
             topic_hint="이차방정식 — 두 근 중 큰 근을 구하는 형태(답 하나)",  # 코드→주제 번역
             subject=Subject.공통,
             slug_prefix="wm-gen-quad",
         )
     provider=None으로 두면 표준 CompositeProvider(Ollama+Anthropic)가 자동 구성된다(라우터가
     로컬로 결정하면 Anthropic 키 없이도 로컬만 태운다).
     **모델 선택(S2-h·기본 GENERAL)**: `qwen2-math:*`는 문제를 *푸는* 데 특화돼 *저작·JSON·지시
     준수*가 약하다(플레이스홀더 베끼기·주제 이탈·영어 leak·같은 계수 반복 mode collapse — 온도
     ↑로도 안 풀림, Phaiakes9 실측). 저작에는 instruction-following이 좋은 일반 모델
     (`qwen2.5:7b`)이 낫다. 그래서 이 생성기는 **`authoring_family=GENERAL`을 기본값**으로 두어,
     라우터가 task_type='generate'를 MATH로 보내도 로컬 저작 패밀리만 GENERAL로 갈아탄다(라우터의
     비용·크기·모드 결정은 그대로 존중·아래 `_decide_routing` 참조). 수학 정확성은 하류 SymPy
     게이트(S2-a)가 검증하므로 저작 모델은 지시 준수·다양성이 우선이다. `authoring_family=None`
     으로 두면 라우터 결정을 그대로 쓴다(옵트아웃). `topic_hint`는 코드→주제 번역을 사람이 미리
     줘 모델의 주제 이탈(이차 요청→일차 생성)을 막는다.

  3. **배치 생성**(`orchestrator.run_batch`)로 코퍼스를 채운다 — 생성물은 **S2-a 게이트 +
     S2-c dedup을 통과한 분만** 저장된다(store 좌석 주입 시). 게이트가 `검수필요`로 보낸 분은
     `needs_review`(사람 검수 큐)로 남고 자동 저장되지 않는다:
         from whymath_backend.l3.equivalent.orchestrator import run_batch
         outcomes = run_batch(spec, gen, n=50, store=store,
                              dedup_index=index, embed_provider=embed)
         # outcome.status ∈ {accepted_stored, needs_review, rejected_gate,
         #                    rejected_duplicate, generation_failed}

  4. **사람 검수 큐**: `needs_review`·저작권 경계·사용자 신고분은 사람 검수로(§03 정본·환각 방어
     ④/5번). 생성기는 판정하지 않고 게이트가 분류한 것을 오케스트레이터가 큐로 흘린다.

주의(CLAUDE.md 절대 금기): provider가 돌려주는 텍스트는 *검증 전 원시 출력*이다. 학생 노출 전
반드시 S2-a 게이트(→ 스키마·SymPy·위생·동등성)를 통과해야 한다 — 이 생성기의 후보는 그 자체로
학생 노출 자격을 갖지 않는다.

범위 밖(후속): 실 Ollama 베이스라인 품질 측정·PRM·Lean·자기검증 패스 결선은 이 환경 밖이다.
본 슬라이스는 *생성기 좌석의 프로덕션 구현* + hermetic 검증까지다.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from functools import lru_cache
from typing import Any

import sympy
from pydantic import ValidationError

from whymath_backend.config import CloudSeat, Settings
from whymath_backend.l1.problem_bank.populate import ConceptTag
from whymath_backend.l3.data_grade_defaults import SELF_AUTHORED_CORPUS
from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
from whymath_backend.l3.equivalent.canonicalize import condition_dsl_violation
from whymath_backend.l3.equivalent.generator import CandidateProblem
from whymath_backend.l3.escalation_defaults import default_student_escalation_signals
from whymath_backend.l3.generation_seed import SeedSource, seed_for_decision
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
from whymath_backend.l3.pregenerate.provenance_bridge import (
    actual_cost_usd_or_none,
    model_name_for_decision,
)
from whymath_backend.l3.prompt_assets import fill, prompt_text
from whymath_backend.l3.router import Router, _as_cost_tier, actual_cost_krw, langfuse_fields
from whymath_backend.l3.verify_answer import derive_selected_root
from whymath_backend.schema.enums import (
    AnswerFormat,
    ConceptRole,
    Curriculum,
    GenerationType,
    LicenseType,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem import DistractorEntry, Problem
from whymath_backend.schema.provenance import ContentProvenance, GenerationLog, text_sha256

__all__ = ["LLMEquivalentProblemGenerator"]

_LOGGER = logging.getLogger(__name__)

# 개념 태깅 role 유효값(ConceptRole) — LLM이 낸 role 문자열 검증용(schema는 최하위·import 허용).
_VALID_ROLES: frozenset[str] = frozenset(r.value for r in ConceptRole)

# 근 선택(S2-i) 유효값 — LLM이 낸 answer_selection 검증용. verify_root_selection 계약과 동일.
_VALID_ROOT_SELECTIONS: frozenset[str] = frozenset({"largest", "smallest", "unique"})

# ──────────────────────────────────────────────────────────────────────────
# 출력 JSON 스키마(S2-j structured output) — 로컬(Ollama) 결정일 때 format= 제약 디코딩으로
# 강제한다. 자유 텍스트·코드펜스·LaTeX 이스케이프·필수 필드 누락을 *문법 수준에서 원천 차단*.
# 필수(required)는 결측 시 어차피 생성 실패(None 폴백)가 되는 4필드 + unit_codes만 최소로
# 잡는다(과잉 제약은 모델과 싸움). enum(answer_format·answer_selection)·수치 범위(난이도)도
# 문법으로 제약한다. 이 스키마는 *형식*만 보장한다 — 관대 파서(_extract_json)·조립 검증
# (_assemble)·S2-a 게이트는 그대로 유지된다(이중 방어: 클라우드 경로·의미 오류는 여전히
# 파서·게이트 소관).
# ──────────────────────────────────────────────────────────────────────────
_OUTPUT_JSON_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "question_text": {"type": "string"},
        "answer": {"type": "string"},
        "answer_explanation": {"type": "string"},
        "conditions": {
            "anyOf": [
                {"type": "string"},
                {"type": "array", "items": {"type": "string"}},
            ],
        },
        "answer_map": {"type": "object", "additionalProperties": {"type": "string"}},
        "answer_selection": {"type": "string", "enum": sorted(_VALID_ROOT_SELECTIONS)},
        "difficulty_overall": {"type": "number", "minimum": 1.0, "maximum": 5.0},
        "unit_codes": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "answer_format": {"type": "string", "enum": [f.value for f in AnswerFormat]},
        "achievement_standard_codes": {"type": "array", "items": {"type": "string"}},
        "distractor_map": {"type": "array", "items": {"type": "object"}},
        "concept_tags": {"type": "array", "items": {"type": "object"}},
    },
    # answer_selection을 required로 강제(S2-k) — 모델이 항상 근 선택을 선언하게 해 "선택 미명시"
    # 유일성 강등을 없앤다(유일해면 unique). 오선언은 게이트가 failed로 안전 차단(수율 손실 감수).
    # solution_steps는 스키마에서 뺀다 — 저작 산문은 Tier2 심볼릭 체인이 아니라 answer_explanation
    # 소관(위 _assemble·S2-k). answer_map은 정확값(분수/정수)이어야 하나 이는 프롬프트로 강제한다
    # (JSON schema로 "분수 문자열"을 문법 표현하기 어려움 — 하류 Tier1이 반올림 소수를 fail로 잡음).
    "required": [
        "question_text",
        "answer",
        "conditions",
        "answer_map",
        "answer_selection",
        "unit_codes",
    ],
}

# 유효하지 않은 JSON 백슬래시 이스케이프 탐지 — LLM이 발문·해설에 LaTeX(`\(`·`\)`·`\frac`·`\sqrt`
# 등)를 넣으면 `json.loads`가 "Invalid \escape"로 거부한다(실 LLM 실측·Phaiakes9). 유효 이스케이프
# (`\"`·`\\`·`\/`·`\b`·`\f`·`\n`·`\r`·`\t`·`\uXXXX`)를 뒤따르지 *않는* 백슬래시만 매칭한다.
_INVALID_JSON_ESCAPE = re.compile(r'\\(?!["\\/bfnrtu])')

# 난이도 float(1~5) → 라우팅 난이도 라벨. 라우터는 문자열(easy/medium/hard/killer)을 받는다.
# 콘텐츠·게이트는 spec.difficulty_overall(float)을 그대로 쓰고, 이 라벨은 *라우팅 신호*로만 쓴다.
_DIFFICULTY_EASY_MAX = 2.0
_DIFFICULTY_MEDIUM_MAX = 3.5
_DIFFICULTY_HARD_MAX = 4.5


# ──────────────────────────────────────────────────────────────────────────
# 시스템 프롬프트 — 저작권 절대 금기 + 출력 JSON 스키마 명세.
# LLM 출력의 출처 주장은 코드가 무시하므로(source_type/license 구조적 강제), 프롬프트는
# "본문 복제 금지·순수 자작"을 명령하고 정확성·형식만 요구한다.
#
# OPS-16: 문면의 정본은 `docs/prompts/l3_equivalent_gen.md`다 — 여기엔 사본을 두지 않고
# 로더로 인용한다(doc-first). 저작권 레일ⓐ(평가원·EBS·검정 교과서 본문 복제 금지 지시문)는
# `harness/prompt_asset_audit`가 CI에서 실재를 감사하고, 사라지면 exit 1로 차단한다.
# 정본 부재·파손은 폴백 없이 `PromptAssetError`(fail-closed — 레일 없는 저작 금지).
# ──────────────────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def _system_prompt() -> str:
    """저작 시스템 프롬프트 — 정본 1회 로드·캐시(매 호출 파일 I/O 금지)."""
    return prompt_text("l3.equivalent.system")


# 이 생성기가 인용하는 정본 프롬프트 자산 전량(고정 순서) — prompt_version 식별의 재료.
_EQUIVALENT_PROMPT_ASSET_IDS: tuple[str, ...] = (
    "l3.equivalent.system",
    "l3.equivalent.user",
    "l3.equivalent.user_topic",
)


@lru_cache(maxsize=1)
def _prompt_version() -> str:
    """이 경로의 프롬프트 정본 식별자 — 자산 내용 해시(EOS-55 `prompt_version` 좌석).

    별도 버전 번호 체계가 없으므로(2026-08-30 실측: `prompt_template_id` 적재 0·Langfuse
    프롬프트 버전 미사용·정본 md에 버전 헤더 없음) 번호를 *발명하지 않고*, 실제 호출부가
    아는 값 — 인용하는 정본 자산 3종의 내용 — 으로 결정론 식별한다. 정본(doc-first)이
    바뀌면 식별자도 바뀐다(같은 식별자 = 같은 문면 보증). 형식:
    `l3.equivalent@sha256:<12hex>`. 프로세스당 1회 계산(`_system_prompt` 캐시 동형).
    """
    digest = hashlib.sha256()
    for asset_id in _EQUIVALENT_PROMPT_ASSET_IDS:
        # 자산 경계를 \x00으로 구분 — 이어붙임 모호성(id/본문 경계 이동) 방지.
        digest.update(asset_id.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(prompt_text(asset_id).encode("utf-8"))
        digest.update(b"\x00")
    return f"l3.equivalent@sha256:{digest.hexdigest()[:12]}"


# 학생 요청 라우팅 신호 기본값 — 6개 호출부 공용 단일 좌석(OPS-18, `api/visualization.py` 미러).
_STUDENT_ESCALATION_DEFAULTS = default_student_escalation_signals()


class LLMEquivalentProblemGenerator:
    """프로덕션 LLM 동등문제 생성기 — `EquivalentProblemGenerator` 좌석 구현(S2-e).

    `generate(spec)`는 스펙을 비민감 요약 프롬프트로 만들어 라우터 경유로 LLM을 호출하고,
    응답 JSON을 `CandidateProblem`으로 조립한다. 저작권 메타(자체생성·WHYMATH_GENERATED·
    FULLY_GENERATED)는 LLM 출력과 무관하게 *구조적으로 강제*한다. 실패는 전부 None(안전 폴백).

    provider는 주입 가능(테스트=FakeProvider)하며 None이면 표준 `CompositeProvider`를 구성한다
    (LLMTutorPolicy·app.py 패턴 재사용·지연 연결이라 구성만으로 네트워크 미발생).
    """

    def __init__(
        self,
        provider: LLMProvider | None = None,
        *,
        settings: Settings | None = None,
        trace: TraceSink | None = None,
        misconception_catalog: Mapping[str, str] | None = None,
        topic_hint: str | None = None,
        subscription: str = _STUDENT_ESCALATION_DEFAULTS.student_subscription,
        budget_krw: float = _STUDENT_ESCALATION_DEFAULTS.budget_krw,
        difficulty: str | None = None,
        temperature: float = 0.9,
        top_p: float | None = None,
        authoring_family: ModelFamily | None = ModelFamily.GENERAL,
        slug_prefix: str = "wm-gen",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        fallback_unit_codes: Sequence[str] = (),
        generation_log_sink: Callable[[GenerationLog], None] | None = None,
        seed_source: SeedSource | None = None,
    ) -> None:
        """생성기 구성.

        Args:
            provider: L3 LLM provider(라우터 경유 필수). None이면 표준 CompositeProvider 구성.
            settings: 앱 설정(선택·후속 튜닝 좌석). 지금은 보관만.
            trace: 관측성 싱크(TraceSink). None이면 LangfuseSink를 기본 구성한다 — 코퍼스
                저작 LLM 호출도 Langfuse에 남긴다("모든 LLM 호출 → Langfuse 추적"·2026-07-21
                정합성 검토: 이 생성기가 pipeline.generate를 우회해 추적 0이던 공백 보정).
                키 미설정이면 sink가 no-op이라 hermetic·오프라인에서도 안전하다(네트워크 0).
                배치 CLI는 종료 시 `flush_trace()`로 전송을 확정할 것.
            misconception_catalog: 오개념 id→한국어 라벨 맵(주입). **L4 카탈로그를 직접 import하지
                않기 위한 주입 지점**(레이어 순수성) — 키는 distractor 오개념 allowlist, 값은
                프롬프트 라벨. None이면 `spec.target_misconception_ids`를 안전 allowlist로 폴백.
            topic_hint: **주제 힌트**(사람이 읽는 단원·출제 형태). 스펙의 성취기준 *코드*만으로는
                모델이 "무엇을 출제할지" 모른다(예 `[10공수1-02-02]`가 이차방정식인 줄 모름) —
                이 힌트를 프롬프트에 실어 주제·답 형태를 명시한다(예 "이차방정식 — 두 근 중 큰
                근을 구하는 형태"). None이면 스펙 코드만 준다(약한 모델은 주제를 못 맞힐 수 있음).
            subscription: 라우팅 신호(구독 — 클라우드 승급 가드). 기본값은
                `escalation_defaults.default_student_escalation_signals()` 단일 좌석(OPS-18,
                오늘은 free).
            budget_krw: 라우팅 신호(클라우드 잔여 예산·원). 기본값은 같은 단일 좌석(오늘은 0.0)
                이라 **동작 변경 0**이다. 이 좌석이 따로 필요한 이유(EOS-99 PR #1023 codex P1):
                클라우드로 나가려면 `subscription != free`와 `budget_krw > 0`이 **둘 다** 필요한데
                (`router.business_cost_tier` 규칙1이 예산을, 규칙2가 구독을 각각 LOCAL로 강제하고
                `guard_cloud`가 한 번 더 본다), 종전에는 구독만 열려 있고 예산은 단일 좌석 상수로
                박혀 있어 **구독만 바꿔도 여전히 LOCAL**이었다. 즉 클라우드 경로를 실제로 태울
                방법이 이 생성기에 없었고, 그래서 프롬프트 캐시 적중 계측(EOS-99)이 이 경로에서는
                영영 `not_applicable`만 낸다. 실측(2026-09-07): free/0=local · premium/0=local ·
                premium/5000=cloud_mid.
            difficulty: 라우팅 난이도 라벨(None이면 spec.difficulty_overall에서 파생).
            temperature: **생성 샘플링 온도**(S2-g 생성 다양성·기본 0.9). 튜터링(도구선택·다음
                행동)은 *결정론*이 좋아 온도를 지정하지 않지만(제공자 기본), *동등문제 저작*은
                **다양성이 목표**라 고온도로 호출한다 — Phaiakes9 실측에서 온도 무지정 시 같은
                문제(예 `x^2-8x+c`·상수만 변주)를 반복하는 mode collapse가 관측됐다. 0.9는
                다양성과 형식 안정의 균형점이다: 더 높이면(>1.2) JSON 붕괴·수식 오류가 급증하고,
                낮추면 다시 collapse로 회귀한다. 값을 provider.generate(temperature=)로 전달한다.
            top_p: **누적확률 절단**(nucleus sampling·EOS-121 선결조건 A). 기본은 **None이고,
                그것이 이 인자의 요점이다** — temperature(0.9)와 달리 기본값을 두지 않는다.
                이유: top_p를 무조건 명시 전송하면 현재 각 공급사 기본값과 다른 값이 나가
                **기존 저작 품질이 조용히 바뀐다**(회귀). 목표는 top_p를 켜는 것이 아니라
                *양 좌석에 같은 값을 줄 수단*을 갖는 것이다. 좌석별 생성 다양성을 측정할 때
                top_p가 통제되지 않으면(= 각 공급사 기본값에 의존하면) 어떤 숫자가 나와도
                "설정 차이 아님"을 말할 수 없다 — 저장소에는 두 공급사 기본값이 같다는 근거도
                다르다는 근거도 없기 때문이다(사전 실측 문서
                `docs/ops/eos121_seat_generation_diversity_precheck.md` §1의 3상태 분류:
                같음/다름/**통제되지 않음**). 값을 주면 provider.generate(top_p=)로 전달되고,
                `_input_snapshot`에도 기록된다.
            authoring_family: **저작용 로컬 모델 패밀리**(S2-h·기본 GENERAL). 라우터는
                task_type='generate'를 MATH 패밀리(qwen2-math)로 보내지만, qwen2-math는 *풀이*
                특화라 저작 시 같은 문제를 반복한다(mode collapse — 온도로도 안 풀림, Phaiakes9
                실측). 동등문제 저작은 본질적으로 instruction-following 과업이고 수학 정확성은 하류
                SymPy 게이트가 검증하므로 로컬 저작은 GENERAL(qwen2.5)로 태운다. 라우터의 비용·
                크기·모드 결정은 그대로 두고 *로컬 FAST/MID 결정의 패밀리 축만* 이 값으로 바꾼다
                (불변식 4 유지·`_decide_routing`). None이면 라우터 결정을 그대로 쓴다(옵트아웃).
            slug_prefix: 안정 slug 접두사(결정론 해시와 결합해 멱등 upsert 키 생성).
            subject·curriculum_version·valid_from_year: Problem 필수 메타 기본값(스펙 밖·저작 배선).
            fallback_unit_codes: LLM이 unit_codes를 안 주면 쓰는 폴백(비면 결측 시 생성 실패).
            generation_log_sink: **생성 Run 재현 로그 싱크**(EOS-55 집행 별항). LLM 호출
                1건마다 `GenerationLog`(모델·prompt_version·seed 좌석·입력 스냅샷 해시+참조)를
                조립해 흘린다 — provider 예외·파싱/조립 실패도 success=False로 기록한다
                (성공 경로만 보는 계측 금지·2026-08-22 규칙). Langfuse trace(SaaS)와 별개의
                인프로세스 이중 회계 축이다. None(기본)이면 종전 동작 그대로(기존 호출부
                무영향) — 배치 CLI(`harness/problem_corpus_accumulate`)가 JSONL appender를
                배선한다.
            seed_source: **샘플링 시드 공급자**(EOS-73). LLM 호출마다 여기서 시드를 뽑아
                provider로 실어 보내고 *같은 값을* GenerationLog.seed에 기록한다 — 좌석만 있고
                값이 전무하던 상태(전 경로 NULL)의 해소. None(기본)이면
                `generation_seed.default_seed_source()`(호출마다 새 난수)다. **난수인 이유**:
                입력에서 결정론 유도하면 같은 스펙 n건 배치가 같은 문항 n개가 되어 temperature
                0.9로 방어하던 mode collapse가 되돌아온다(모듈 `generation_seed` docstring ②).
                재현은 *기록된 시드를 되먹이는 쪽*이 담당하며, 고정 공급자를 주입하면 그 좌표로
                재투입된다(`harness/generation_seed_replay_probe`).
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
            # 관측 기본 배선 — providers와 동형의 지연 구성(키 미설정=no-op·네트워크 0).
            from whymath_backend.l3.trace.langfuse_sink import LangfuseSink

            trace = LangfuseSink(settings=settings)
        self._provider = provider
        self._trace = trace
        self._settings = settings
        self._catalog = dict(misconception_catalog) if misconception_catalog is not None else None
        self._topic_hint = topic_hint
        self._subscription = subscription
        self._budget_krw = budget_krw
        self._difficulty = difficulty
        self._temperature = temperature
        self._top_p = top_p
        self._authoring_family = authoring_family
        # 배치용 지속 이벤트 루프(지연 생성) — asyncio.run의 루프 생성·종료 반복이 provider의
        # 캐시 커넥션 풀을 죽여 배치가 격회 실패하던 실측 회귀 방어(_invoke·_ensure_loop 참조).
        self._loop: asyncio.AbstractEventLoop | None = None
        self._generation_log_sink = generation_log_sink
        self._seed_source = seed_source
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._fallback_unit_codes = list(fallback_unit_codes)

    # ── EquivalentProblemGenerator 좌석 ────────────────────────────────
    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """스펙에 맞는 동등문제 후보 1건을 생성(실패 시 None·크래시 금지).

        흐름: 프롬프트 조립 → 라우터 결정 → 시드 추출 → provider.generate(동기 경계) → JSON
        관대 파싱 → CandidateProblem 조립(저작권 메타 구조적 강제). 어느 단계든 실패하면 로그 +
        None을 돌려 오케스트레이터가 `generation_failed`로 정직히 처리하게 한다.

        시드(EOS-73)는 결정 직후 *한 번만* 뽑아 provider 호출과 GenerationLog 기록이 **같은 값**을
        보게 한다 — 종단마다 다시 뽑으면 기록된 좌표로 재투입해도 재현되지 않는다.
        """
        prompt = self._build_user_prompt(spec)
        decision = self._decide_routing(spec)
        # LOCAL이면 시드 1개, 클라우드면 None(Messages API에 seed 파라미터 부재 — 구조적 불가).
        seed = seed_for_decision(decision, source=self._seed_source)
        try:
            generated = self._invoke(prompt, decision, seed=seed)
        except Exception as exc:  # noqa: BLE001 — provider 장애 시 배치 크래시 금지·안전 폴백.
            _LOGGER.warning("동등문제 생성 provider 호출 실패 — None 폴백: %s", exc)
            # 실패한 호출 *시도*도 Run 이력이다(EOS-55) — usage 미상(None)·정직 실패 기록.
            self._emit_generation_log(
                spec,
                prompt,
                decision,
                usage=None,
                success=False,
                error_detail=f"provider.generate failed: {type(exc).__name__}: {exc}",
                # 호출을 *시도한* 좌표는 남긴다 — 같은 시드로 재시도해 실패를 재현할 수 있다.
                seed=seed,
            )
            return None
        # LLM 호출 성공 = 비용 발생 — 하류 JSON 파싱·조립 성패와 무관하게 관측을 먼저 남긴다
        # ("모든 LLM 호출 → Langfuse 추적" — 추적 0이던 공백 보정·2026-07-21 정합성 검토).
        self._record_trace(decision, generated.usage)
        raw = generated.text

        data = self._extract_json(raw)
        if data is None:
            _LOGGER.warning("동등문제 생성 응답 JSON 파싱 실패 — None 폴백.")
            self._emit_generation_log(
                spec,
                prompt,
                decision,
                usage=generated.usage,
                success=False,
                error_detail="응답 JSON 파싱 실패",
                seed=seed,
            )
            return None

        try:
            candidate = self._assemble(spec, data)
        except (ValidationError, ValueError, KeyError, TypeError) as exc:
            # Problem/Provenance 불변식 위반(저작권 게이트가 생성 거부)·필수 결측·타입 오류.
            # 조용히 통과시키지 않고 로그 + None(게이트에 도달하기 전 정직한 생성 실패).
            _LOGGER.warning("동등문제 후보 조립 실패 — None 폴백: %s", exc)
            self._emit_generation_log(
                spec,
                prompt,
                decision,
                usage=generated.usage,
                success=False,
                error_detail=f"후보 조립 실패: {type(exc).__name__}",
                seed=seed,
            )
            return None
        self._emit_generation_log(
            spec,
            prompt,
            decision,
            usage=generated.usage,
            success=True,
            error_detail=None,
            seed=seed,
            # 조립된 후보의 안정 slug = 코퍼스 키(멱등 upsert·검수 타이머 cu_slug와 동일 축)
            # — hit_cu_metrics CU당 토큰·비용 조인 정체성(#912 P1-2).
            cu_slug=candidate.problem.slug,
        )
        return candidate

    # ── 동기 경계(async provider.generate를 배치 sync 문맥에서 호출) ─────
    def _invoke(
        self, prompt: str, decision: RoutingDecision, *, seed: int | None
    ) -> GenerationResult:
        """provider.generate(async)를 sync 경계에서 실행 — 오프라인 배치 문맥 전용.

        오케스트레이터(`run_batch`)는 sync라 여기서 코루틴을 완주시킨다. **인스턴스 전용 지속
        이벤트 루프**(`_ensure_loop`)를 쓴다 — 종전 `asyncio.run`(호출마다 새 루프 생성·종료)은
        배치에서 provider가 캐시한 AsyncClient(httpx 커넥션 풀)가 죽은 루프에 묶여 다음 호출이
        "Event loop is closed"로 격회 실패하는 실측 회귀를 냈다(Phaiakes9 run_batch n=20 —
        단건 프로세스에선 절대 안 드러나는 배치 전용 결함). 같은 루프를 생성기 수명 동안
        재사용하면 커넥션 풀이 산 루프에 남아 전 회차가 정상 동작한다. 이미 러닝 루프가 있는
        async 문맥에서의 호출은 이 배치 좌석의 계약 밖이다(명확한 RuntimeError로 드러남).

        `temperature=self._temperature`(기본 0.9)를 실어 *생성 다양성*을 확보한다 — 튜터링과
        달리 콘텐츠 저작은 고온도가 필요하다(mode collapse 방어·__init__ temperature 참조).

        `top_p`(EOS-121 선결조건 A)는 **값이 있을 때만** 싣는다 — 기본 None이면 키 자체를
        넘기지 않아 각 공급사 기본값이 그대로 쓰인다(*기존 동작 무변경*). temperature처럼
        기본값을 박아 두지 않는 이유는 __init__ top_p 항 참조(무조건 전송 = 조용한 품질 변경).

        `json_schema`(S2-j structured output)는 **LOCAL 결정일 때만** 싣는다 — Ollama는
        format= 제약 디코딩으로 출력을 스키마에 맞는 JSON으로 문법 강제하고, 클라우드
        (Anthropic)는 문법 제약이 없어 스키마를 주면 명확히 거부하므로(조용한 무시 금지)
        클라우드 경로는 종전처럼 프롬프트+관대 파서(_extract_json)로 동작한다(이중 방어).

        `seed`(EOS-73 생성 재현)는 **값이 있을 때만** 싣는다. 호출부가 `seed_for_decision`으로
        뽑으므로 LOCAL이면 값이, 클라우드면 None이 온다 — 클라우드에 실으면 AnthropicProvider가
        명확히 거부한다(seed 파라미터 부재·조용한 무시 금지). 기본값을 두지 않고 **키워드 필수**로
        받는 이유: 호출부가 "이 호출의 재현 좌표를 기록했는가"를 매번 자문하게 하기 위함이다.
        """
        is_local = decision.cost_tier == CostTier.LOCAL.value
        schema = _OUTPUT_JSON_SCHEMA if is_local else None
        # provider 반환은 GenerationResult(text, usage) — 텍스트는 조립이, usage는 관측
        # (_record_trace: 실측 토큰·지연·비용)이 소비한다.
        loop = self._ensure_loop()
        # 선택 인자는 *값이 있을 때만* 키를 싣는다 — 둘 다 None이면 호출 형태가 종전과 완전히
        # 같다(`generate(prompt, system, decision, temperature=, json_schema=)`).
        #   · seed: 시드 미지원 경로(클라우드)에 실으면 provider가 거부한다(조용한 무시 금지).
        #   · top_p: 미지정이면 공급사 기본값 — 무조건 전송이 곧 조용한 품질 변경이다(EOS-121 A).
        call_kwargs: dict[str, Any] = {
            "temperature": self._temperature,
            "json_schema": schema,
        }
        if self._top_p is not None:
            call_kwargs["top_p"] = self._top_p
        if seed is not None:
            call_kwargs["seed"] = seed
        return loop.run_until_complete(
            self._provider.generate(prompt, _system_prompt(), decision, **call_kwargs)
        )

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        """인스턴스 전용 이벤트 루프 지연 생성 — 배치 전 회차가 *같은 살아있는 루프*를 공유한다.

        provider의 캐시된 async 클라이언트(커넥션 풀)가 루프에 묶이므로, 루프를 호출마다 닫으면
        (asyncio.run) 배치가 격회로 죽는다(_invoke docstring 실측). 루프는 생성기 수명과 함께
        가고 프로세스 종료 시 정리된다(오프라인 배치 CLI 문맥·장수 서버 문맥이 아님).
        """
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
        return self._loop

    # ── 저작 좌석(ARCH-62) ──
    def _authoring_seat(self) -> CloudSeat:
        """이 저작 배치의 클라우드 좌석 — 비용 기록이 **어느 단가표를 읽을지** 정한다.

        저작 경로의 좌석은 `settings.cloud_provider` 셀렉터가 정하고(config 주석·
        `build_cloud_provider`가 같은 값을 읽어 provider를 만든다), 그 값을 여기서도 읽어
        비용 회계와 실제 호출 좌석을 **같은 근거**에 묶는다. 둘이 갈라진 상태가 ARCH-62가
        상환하는 결함이다 — 셀렉터를 openrouter로 두고도 원가는 anthropic 단가로 적혀
        24.4배 과대 계상됐다.

        한계(명시): provider를 외부에서 주입한 경우(테스트·특수 배치) 그 provider가
        셀렉터와 다른 좌석일 수 있다. 그 조합은 이 저장소의 저작 계약 밖이며, 좌석을
        알 수 없게 되면 호출부가 `seat=None`을 넘겨 비용을 '미측정'으로 남기면 된다.
        """
        from whymath_backend.l3.providers.factory import cloud_provider_name

        return cloud_provider_name()

    # ── 관측(코퍼스 저작 호출도 Langfuse에 남긴다 — 게이트② 관측 공백 보정) ──
    def _record_trace(self, decision: RoutingDecision, usage: Usage | None) -> None:
        """생성 1건의 라우팅·실측(usage·비용)을 sink에 기록 — never-break(배치 비차단).

        비용 회계는 `pipeline.generate`와 동형: usage 없음(미계측)·클라우드인데 토큰
        미상이면 None('미상'과 0원 구분 — 지어내지 않음), 그 외 토큰 산정(로컬 0원 확정).
        student_id_hash는 없다(오프라인 저작 — 학생 무관).
        """
        actual_krw: float | None
        is_cloud = _as_cost_tier(decision.cost_tier) is not CostTier.LOCAL
        if usage is None:
            actual_krw = None
        elif is_cloud and (usage.input_tokens is None or usage.output_tokens is None):
            actual_krw = None
        else:
            actual_krw = actual_cost_krw(decision, usage, seat=self._authoring_seat())
        try:
            self._trace.record(
                langfuse_fields(decision, cache_hit=False, usage=usage, cost_krw=actual_krw)
            )
        except Exception as exc:  # noqa: BLE001 — 관측 장애가 저작 배치를 깨면 안 됨
            # 침묵실패 금지 — 예외 *타입명*만 경고(필드·키 값 미출력, langfuse_sink 방침 동형).
            _LOGGER.warning("동등문제 생성 관측 기록 실패(%s) — 무시하고 계속", type(exc).__name__)

    def flush_trace(self) -> None:
        """배치 종료 시 관측 전송 확정 — LangfuseSink는 배치 전송이라 CLI가 flush로 확정한다.

        TraceSink 계약은 record만 요구하므로 flush 없는 sink(테스트 대역)는 조용히 통과
        (계약 밖 표면의 duck-typing — cost_probe `_FlushSink` 동형). flush 오류도 삼키되
        타입명은 남긴다(never-break·침묵실패 금지).
        """
        flush = getattr(self._trace, "flush", None)
        if not callable(flush):
            return
        try:
            flush()
        except Exception as exc:  # noqa: BLE001 — 전송 확정 실패가 배치 결과를 깨면 안 됨
            _LOGGER.warning("동등문제 생성 관측 flush 실패(%s) — 무시하고 계속", type(exc).__name__)

    # ── 생성 Run 재현 로그 (EOS-55 집행 별항 — Langfuse와 별개의 인프로세스 이중 회계) ──
    def _input_snapshot(self, spec: EquivalenceSpec, prompt: str) -> dict[str, object]:
        """호출 1건의 입력 스냅샷(전문+해시 — 자기완결) — 재현 계약의 accumulate측 조립.

        담는 것(전부 JSON 원시형 — canonical 직렬화·JSONB 왕복 안정):
          - `prompt`/`system`: 실제 전송 텍스트 **전문(verbatim)** — 스냅샷 자기완결의 핵심
            (#912 P1-1: 해시만 남기면 정본 자산·스펙이 바뀐 뒤 모델 입력을 재구성할 수 없다.
            자체 정본 템플릿+자체 스펙 조합이라 저작권 무관·행당 수 KB 허용).
          - `prompt_sha256`/`system_sha256`: 전문의 sha256 병기 — 무결성 대조 축.
          - `spec`: 이 경로가 실제로 가진 구조 입력 — 성취기준·오개념·난이도·답형태.
            (전문과 중복되는 재료지만 명료성 우선 — 구조 신호로도, 문면으로도 복원 가능.)
          - `topic_hint`/`temperature`/`top_p`: 프롬프트·샘플링에 실제 반영된 생성 신호.
            `top_p`는 미지정이면 **null로 기록된다** — 키를 빼지 않는 이유는 "안 보냈다"와
            "구판이라 기록 자체가 없다"를 구분하기 위해서다(부재 ≠ 값 없음·EOS-121 A).
        라우터 결정은 담지 않는다 — spec에서 결정론 유도되는 파생물이고, 실행 모델은
        `model_name` 컬럼이 별도 기록한다(pregenerate측 `input_snapshot_for_prewarm` 동형).
        시드도 담지 않는다 — `GenerationLog.seed` 전용 컬럼이 정본이고, 스냅샷에 사본을 두면
        둘이 갈라졌을 때 어느 쪽이 실제로 보낸 값인지 알 수 없게 된다(단일 진실 원천).
        """
        return {
            "kind": "l3.equivalent.llm_generate",
            "prompt": prompt,
            "system": _system_prompt(),
            "prompt_sha256": text_sha256(prompt),
            "system_sha256": text_sha256(_system_prompt()),
            "spec": {
                "achievement_standard_codes": sorted(spec.achievement_standard_codes),
                "target_misconception_ids": sorted(spec.target_misconception_ids),
                "difficulty_overall": spec.difficulty_overall,
                "answer_format": self._enum_value(spec.answer_format),
            },
            "topic_hint": self._topic_hint,
            "temperature": self._temperature,
            "top_p": self._top_p,
        }

    def _emit_generation_log(
        self,
        spec: EquivalenceSpec,
        prompt: str,
        decision: RoutingDecision,
        *,
        usage: Usage | None,
        success: bool,
        error_detail: str | None,
        seed: int | None,
        cu_slug: str | None = None,
    ) -> None:
        """호출 1건의 GenerationLog 조립·싱크 적재 — never-break(배치 비차단).

        기록 원칙(날조 금지):
          - `problem_id=None` — 배치 저작 후보는 DB problem 레코드가 아직 없다(JSONL 코퍼스
            v0 단계·slug 기반). DB 적재 시점의 연결은 적재 파이프라인 소관.
          - `cu_slug`(#912 P1-2): 후보 조립까지 도달한 성공 종단만 코퍼스 키와 동일 산식의
            안정 slug(`_stable_slug` 산출물·`candidate.problem.slug`)를 전달한다 —
            `ops/hit_cu_metrics --generation-log` CU 조인 정체성. 정체성이 생기기 전에
            실패한 종단(provider 예외·파싱 실패·조립 실패)은 None=미기록(정직).
          - `seed`(EOS-73): **이 호출에 실제로 실려 나간 시드**를 그대로 받는다(호출부가
            `generate()`에서 한 번 뽑아 provider와 이 기록에 같은 값을 넘긴다). 여기서 다시
            뽑지 않는 이유는 뽑은 값과 보낸 값이 갈라지는 순간 기록이 재현을 보장하지 못하기
            때문이다. 클라우드 결정은 None=미기록이 정직하다(Anthropic Messages API에 seed
            파라미터 부재 — 구조적 불가·날조 금지). 기본값 없는 키워드 필수 인자다.
          - `prompt_version`: 정본 자산 내용 해시(`_prompt_version` — 실제 아는 값).
          - `cost_usd`: 로컬 0원 확정 / 클라우드 토큰 미상 None(`actual_cost_usd_or_none`).
        싱크·조립 예외는 흡수하되 **타입명을 로그에 남긴다**(침묵 실패 금지 —
        `_record_trace` 동형).
        """
        if self._generation_log_sink is None:
            return
        try:
            latency_ms: int | None = None
            if usage is not None and usage.latency_ms is not None:
                # 실측 float(ms) → 스키마 계약 int(ms) 반올림(provenance_bridge 동형).
                latency_ms = int(round(usage.latency_ms))
            log = GenerationLog(
                model_name=model_name_for_decision(decision, settings=self._settings),
                prompt_version=_prompt_version(),
                seed=seed,  # 실려 나간 값만(클라우드=None 미기록·날조 금지)
                input_tokens=usage.input_tokens if usage is not None else None,
                output_tokens=usage.output_tokens if usage is not None else None,
                # 프롬프트 캐시 2종(EOS-99) — 캐시 개념이 없는 로컬 경로는 provider가 채우지
                # 않아 None(해당 없음)이고, 클라우드는 응답 usage 실측이 그대로 실린다.
                cache_read_input_tokens=(
                    usage.cache_read_input_tokens if usage is not None else None
                ),
                cache_creation_input_tokens=(
                    usage.cache_creation_input_tokens if usage is not None else None
                ),
                # 관측 좌석(EOS-112) — 위 `model_name`이 *설정이 지목한* 모델이라면 이 둘은
                # *응답이 온* 모델과 그 호출의 재시도 횟수다. usage가 None(호출 자체가 없었던
                # 종단)이면 둘 다 None=미관측이다(0으로 접지 않는다).
                served_model=usage.served_model if usage is not None else None,
                retries=usage.retries if usage is not None else None,
                cost_usd=actual_cost_usd_or_none(decision, usage, seat=self._authoring_seat()),
                latency_ms=latency_ms,
                success=success,
                error_detail=error_detail,
                input_snapshot=self._input_snapshot(spec, prompt),
                cu_slug=cu_slug,
            )
            self._generation_log_sink(log)
        except Exception as exc:  # noqa: BLE001 — 관측 적재 장애는 저작 배치 비차단(타입명 로그)
            _LOGGER.warning("동등문제 생성 로그 적재 실패(%s) — 무시하고 계속", type(exc).__name__)

    # ── 라우팅 결정(라우터 경유 + 저작 패밀리 선호) ─────────────────────
    def _decide_routing(self, spec: EquivalenceSpec) -> RoutingDecision:
        """라우터 결정 + 저작 패밀리 선호 적용(S2-h).

        라우터는 task_type='generate'를 MATH 패밀리(qwen2-math)로 보내지만, qwen2-math는 문제를
        *푸는* 데 특화돼 저작 시 같은 계수를 반복한다(mode collapse — 온도↑로도 안 풀림,
        Phaiakes9 실측). 동등문제 저작은 본질적으로 instruction-following 과업이고 수학 정확성은
        하류 SymPy 게이트(S2-a)가 검증하므로, 로컬 저작은 GENERAL(qwen2.5)로 태운다.

        라우터의 *비용·크기·모드* 결정은 그대로 존중한다 — 오직 **로컬 FAST/MID 결정의 패밀리
        축만** `authoring_family`로 바꾼다(불변식 4가 성립하는 지점뿐). QUALITY(27b·패밀리 무관)·
        CLOUD_*(축3 없음)·이미 원하는 패밀리·`authoring_family=None`(옵트아웃)이면 라우터 결정을
        그대로 반환한다. 재구성 시 RoutingDecision 검증기가 다시 돌아 불변식을 재확인한다.

        전역 라우터 정책은 건드리지 않는다(scene·visualization 등 다른 'generate' 소비처 무영향)
        — 저작 선호는 이 생성기 스코프에 국한한다.
        """
        decision = Router().route(self._routing_request(spec))
        if self._authoring_family is None:
            return decision
        # 필드는 use_enum_values=True라 문자열일 수 있으나, CostTier/LocalModelTier는 str-Enum이라
        # `.value` 비교가 enum·문자열 양쪽에 성립한다(str 서브클래스 동치).
        is_local = decision.cost_tier == CostTier.LOCAL.value
        family_applicable = is_local and decision.local_model in (
            LocalModelTier.FAST.value,
            LocalModelTier.MID.value,
        )
        if not family_applicable or decision.local_family == self._authoring_family.value:
            return decision  # 패밀리 축이 없는 티어(QUALITY·CLOUD)·이미 원하는 패밀리 → 그대로
        return RoutingDecision(
            cost_tier=decision.cost_tier,
            local_family=self._authoring_family,  # 저작 패밀리로 갈아탐(GENERAL=qwen2.5)
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

    # ── 라우팅 신호 ────────────────────────────────────────────────────
    def _routing_request(self, spec: EquivalenceSpec) -> RoutingRequest:
        """생성 호출의 라우팅 신호 — task_type='generate'.

        라우터는 이 신호로 비용·크기·모드를 정한다. 패밀리 축은 기본이 MATH지만, 저작에는
        GENERAL이 낫기에 `_decide_routing`이 로컬 FAST/MID 결정의 패밀리만 `authoring_family`로
        갈아탄다(라우터 결정 후처리). 난이도는 스펙에서 파생(생성자 override 우선), 다단계 추론
        필요(정답이 조건을 만족하는 새 문제 구성). 무료·예산 0이면 라우터가 LOCAL로 강제한다.
        """
        difficulty = self._difficulty or self._difficulty_label(spec.difficulty_overall)
        return RoutingRequest(
            task_type="generate",
            difficulty=difficulty,
            requires_reasoning=True,
            student_subscription=self._subscription,
            budget_krw=self._budget_krw,  # 기본값=단일 좌석(OPS-18·회귀 0)·호출자 명시 시 override
            sync=True,
            # 등급: 프롬프트에는 비민감 스펙 요약(성취기준 코드·오개념 id·난이도·답 형태)만
            # 싣고 원본 본문·풀이는 애초에 스펙에 없다(`_build_user_prompt` 참조) — 실리는
            # 것은 자체 저작 메타뿐이다. 코퍼스 provenance가 바뀌면 단일 좌석에서 잠긴다.
            data_licenses=SELF_AUTHORED_CORPUS,
        )

    @staticmethod
    def _difficulty_label(overall: float) -> str:
        """난이도 float(1~5) → 라우팅 라벨(easy/medium/hard/killer)."""
        if overall < _DIFFICULTY_EASY_MAX:
            return "easy"
        if overall < _DIFFICULTY_MEDIUM_MAX:
            return "medium"
        if overall < _DIFFICULTY_HARD_MAX:
            return "hard"
        return "killer"

    # ── 사용자 프롬프트(비민감 스펙 요약·Minimal context) ───────────────
    def _build_user_prompt(self, spec: EquivalenceSpec) -> str:
        """스펙을 비민감 요약으로 압축 — 과다 주입 금지(Minimal context·플레이북 Part 8).

        성취기준 코드·오개념 id(주입된 라벨 병기)·난이도·답 형태만 싣는다. 원본 본문·풀이는
        스펙에 없고(애초에 자작 대응이므로) 프롬프트에도 없다.

        문면은 `docs/prompts/l3_equivalent_gen.md` 정본 인용(OPS-16) — 여기서 조립하는 것은
        *값*(주제 힌트·스펙 JSON)뿐이다.
        """
        misconceptions = [
            {"id": mid, "label": self._label_for(mid)}
            for mid in sorted(spec.target_misconception_ids)
        ]
        summary: dict[str, object] = {
            "achievement_standard_codes": sorted(spec.achievement_standard_codes),
            "target_misconceptions": misconceptions,
            "difficulty_overall": spec.difficulty_overall,
            "answer_format": self._enum_value(spec.answer_format),
        }
        spec_json = json.dumps(summary, ensure_ascii=False, indent=2)
        # 주제 힌트 — 성취기준 *코드*만으론 모델이 주제를 못 맞히므로(예 [10공수1-02-02]=이차방정식)
        # 사람이 읽는 주제·출제 형태를 최상단에 명시한다(있을 때만).
        topic_line = (
            fill(prompt_text("l3.equivalent.user_topic"), TOPIC=self._topic_hint) + "\n"
            if self._topic_hint
            else ""
        )
        return fill(prompt_text("l3.equivalent.user"), TOPIC_LINE=topic_line, SPEC_JSON=spec_json)

    def _label_for(self, misconception_id: str) -> str:
        """오개념 id의 한국어 라벨 — 주입된 카탈로그에 있으면 그 라벨, 없으면 id 자체."""
        if self._catalog is not None:
            return self._catalog.get(misconception_id, misconception_id)
        return misconception_id

    # ── JSON 관대 추출(LLMTutorPolicy `_extract_json` 미러 + LaTeX 이스케이프 내성) ──
    @classmethod
    def _extract_json(cls, raw: str) -> dict[str, object] | None:
        """원시 텍스트에서 JSON 객체를 관대하게 추출 — 코드펜스·주변 산문·LaTeX 백슬래시 허용.

        후보(통째로 / 첫 `{`…마지막 `}` 구간) 각각을 *원문* 그리고 *이스케이프 sanitize본*으로
        파싱 시도한다. sanitize는 LaTeX(`\\(`·`\\frac` 등) 유효하지 않은 백슬래시 이스케이프를
        리터럴로 이중화해 `json.loads`의 "Invalid \\escape" 실패를 구제한다(실 LLM 실측). 유효
        이스케이프는 보존하므로 정상 JSON은 그대로 파싱된다(무해).
        """
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
            for attempt in (candidate, _INVALID_JSON_ESCAPE.sub(r"\\\\", candidate)):
                try:
                    obj = json.loads(attempt)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    return obj
        return None

    # ── CandidateProblem 조립(저작권 메타 구조적 강제) ──────────────────
    def _assemble(self, spec: EquivalenceSpec, data: dict[str, object]) -> CandidateProblem:
        """파싱된 응답 → `CandidateProblem`. 저작권 메타는 LLM과 무관하게 구조적으로 박는다.

        필수 결측·타입 오류·불변식 위반은 예외로 전파돼(호출자가) None 폴백된다. distractor 오개념
        id는 allowlist(주입 카탈로그 키 ∪ 스펙 타깃)에 없는 것을 드롭한다.
        """
        question_text = self._require_str(data, "question_text")
        answer = self._require_str(data, "answer")
        answer_explanation = self._opt_str(data, "answer_explanation")
        conditions = self._parse_conditions(data.get("conditions"))
        answer_map = self._parse_answer_map(data.get("answer_map"))
        answer_selection = self._parse_answer_selection(data.get("answer_selection"))
        # derive-and-verify(S2-n) — 근 선택 문제는 정답을 우리가 유도해 대조·정확값 정규화.
        answer, answer_map = self._derive_and_normalize(
            answer, answer_map, conditions, answer_selection
        )
        difficulty_overall = self._parse_difficulty(data.get("difficulty_overall"), spec)
        unit_codes = self._parse_unit_codes(data.get("unit_codes"))
        answer_format = self._parse_answer_format(data.get("answer_format"), spec)
        standard_codes = self._parse_standard_codes(data.get("achievement_standard_codes"), spec)
        distractor_map = self._parse_distractor_map(data.get("distractor_map"), spec)
        # 저작 LLM은 *검증 가능한 Tier2 심볼릭 체인*(expr_before ≡ expr_after)을 만들지 않는다 —
        # 모델이 내는 solution_steps는 산문 설명("인수분해하면…")이라 Tier2(verify_solution)에
        # 넣으면 전부 unverifiable로 잡혀 정답 문제까지 검수필요로 강등된다(S2-k·Phaiakes9 실측).
        # 답 정확성은 Tier1(대입)+근 선택(S2-i)이 이미 확정하고, 사람용 설명은 answer_explanation
        # (위생 게이트가 거짓 등식 검사)에 담긴다. 검증된 단계 체인은 WH-S 솔버의 몫이다.
        solution_steps = None
        concept_tags = self._parse_concept_tags(data.get("concept_tags"))
        slug = self._stable_slug(question_text, answer, standard_codes)

        # ── 저작권 구조적 강제(② 코드 방어) — LLM 출력의 출처 주장은 읽지 않는다. ──
        problem = Problem(
            slug=slug,
            source_type=SourceType.자체생성,  # 무조건 자체생성(본문 보유 자격)
            curriculum_version=self._curriculum_version,
            valid_from_year=self._valid_from_year,
            subject=self._subject,
            unit_codes=unit_codes,
            difficulty_overall=difficulty_overall,
            answer_format=answer_format,
            achievement_standard_codes=standard_codes,
            distractor_map=distractor_map or None,
            question_text=question_text,
            answer=answer,
            answer_explanation=answer_explanation,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,  # AI 완전 생성
            license=LicenseType.WHYMATH_GENERATED,  # 지배 license 고정
            original_source=None,  # 원본 없음(자작) — 본문성 키 0
            transformation_pipeline={
                "steps": [
                    "LLM 자작 초안(라우터 경유)",
                    "S2-a 수용 게이트",
                    "사람 검수 큐(필요 시)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=conditions,
            answer_map=answer_map,
            answer_selection=answer_selection,
            solution_steps=solution_steps,
            concept_tags=concept_tags,
        )

    # ── 필드 파싱·강제 헬퍼(전부 결정론·순수) ──────────────────────────
    @staticmethod
    def _require_str(data: Mapping[str, object], key: str) -> str:
        """필수 문자열 필드 — 결측·빈값·비문자열은 ValueError(→ None 폴백)."""
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"필수 문자열 필드 결측/무효: {key!r}")
        return value.strip()

    @staticmethod
    def _opt_str(data: Mapping[str, object], key: str) -> str | None:
        """선택 문자열 — 없거나 비문자열이면 None."""
        value = data.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _parse_conditions(value: object) -> str | list[str]:
        """조건 — 문자열 또는 문자열 배열 + **닫힌 검증 DSL 강제**(S2-m).

        결측·무효는 ValueError(정확성 검산 재료 결측). 각 조건은 `condition_dsl_violation`으로
        언어 폐쇄를 검사한다 — 실 LLM이 흘리는 pseudo-symbolic(`largest_root(2,8)==8`·
        `solve(...)==[6,4]`·파이썬 문법 혼입)은 검증기가 판정할 수 없어 needs_review로 새던 것을
        조립 단계에서 거부해(생성 실패·재생성) 사람 검수 큐 오염을 막는다.
        """
        items: list[str]
        if isinstance(value, str) and value.strip():
            items = [value.strip()]
            single = True
        elif isinstance(value, list):
            items = [str(v).strip() for v in value if isinstance(v, str) and str(v).strip()]
            single = False
            if not items:
                raise ValueError("conditions 결측/무효 — 정확성 검산 재료가 없습니다.")
        else:
            raise ValueError("conditions 결측/무효 — 정확성 검산 재료가 없습니다.")
        for item in items:
            violation = condition_dsl_violation(item)
            if violation is not None:
                raise ValueError(f"conditions DSL 위반({item!r}) — {violation}")
        return items[0] if single else items

    @staticmethod
    def _derive_and_normalize(
        answer: str,
        answer_map: dict[str, str],
        conditions: str | list[str],
        answer_selection: str | None,
    ) -> tuple[str, dict[str, str]]:
        """derive-and-verify(S2-n) — LLM 답을 신뢰하지 않고 (방정식+선택)에서 정답을 유도해 대조.

        근 선택 문제(answer_selection 있음·단일변수 answer_map)는 정답이 (방정식, 선택)만으로
        결정론 유도 가능하다(`derive_selected_root`). 유도값과 LLM 답을 수치 대조해:
          - **일치**(부동소수 표기 차이 포함): answer_map·answer를 **유도된 정확값**(예 `'4/3'`)
            으로 정규화한다 — 반올림 소수(`1.3333…`) display·검산 실패를 원천 제거하고 canonical
            정답의 소유권을 코드가 가진다(리뷰 "canonical_answer 분리" 채택).
          - **불일치**(모델이 틀린 근·산술 붕괴·과도한 반올림): ValueError → 생성 실패(None 폴백·
            배치 재생성). 단순 repair(답 몰래 교체)는 하지 않는다 — answer_explanation 등 본문이
            틀린 값을 참조할 수 있어 조용한 수정은 모순 콘텐츠를 만든다(정직한 거부·재생성).
        유도 불가(파라미터·연립·비적용)는 무변경 통과 — 게이트가 기존 규약대로 판정한다.
        """
        if answer_selection is None or len(answer_map) != 1:
            return answer, answer_map
        derived = derive_selected_root(conditions, answer_selection)
        if derived is None:
            return answer, answer_map  # 유도 불가 — 게이트에 판정 위임(보수적).
        var, given = next(iter(answer_map.items()))
        try:
            given_value = complex(sympy.sympify(given, convert_xor=True).evalf())
            derived_value = complex(sympy.sympify(derived, convert_xor=True).evalf())
        except Exception:  # noqa: BLE001 — 답 파싱 불가는 정규화 포기(게이트 위임)
            return answer, answer_map
        # 부동소수 표기 차이만 흡수(상대 1e-6) — 반올림 소수(1.33)·틀린 근은 불일치로 거부.
        tolerance = max(1e-6, 1e-6 * abs(derived_value))
        if abs(given_value - derived_value) > tolerance:
            raise ValueError(
                f"derive-and-verify 불일치 — LLM 답({given})이 유도 정답({derived})과 다름"
                f"(근 선택 {answer_selection}·오답 원천 거부)."
            )
        return derived, {var: derived}

    @staticmethod
    def _parse_answer_selection(value: object) -> str | None:
        """근 선택(S2-i) — largest/smallest/unique만 허용, 그 외·결측은 None(선택 요구 없음).

        게이트가 "어느 근인가"를 검증하는 신호다(`verify_root_selection`). 미지 값은 조용히
        None으로 떨궈(오분류 방지) 다근 유일성 강등 경로에 맡긴다(조용한 오채택 금지).
        """
        if isinstance(value, str) and value.strip() in _VALID_ROOT_SELECTIONS:
            return value.strip()
        return None

    @staticmethod
    def _parse_answer_map(value: object) -> dict[str, str]:
        """치환맵 — {변수: 값} 문자열 맵. 무효면 ValueError(정확성 검산 재료 결측)."""
        if isinstance(value, dict) and value:
            result: dict[str, str] = {}
            for var, val in value.items():
                if not isinstance(var, str) or not str(var).strip():
                    raise ValueError("answer_map 변수 키 무효.")
                result[str(var).strip()] = str(val).strip()
            if result:
                return result
        raise ValueError("answer_map 결측/무효 — 정확성 검산 재료가 없습니다.")

    def _parse_difficulty(self, value: object, spec: EquivalenceSpec) -> float:
        """난이도 — LLM값을 1.0~5.0으로 클램프, 무효면 스펙 난이도로 폴백."""
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return min(5.0, max(1.0, float(value)))
        return spec.difficulty_overall

    def _parse_unit_codes(self, value: object) -> list[str]:
        """단원 코드 — 문자열 배열(최소 1). 없으면 폴백, 폴백도 비면 ValueError."""
        if isinstance(value, list):
            codes = [str(v).strip() for v in value if isinstance(v, str) and str(v).strip()]
            if codes:
                return codes
        if self._fallback_unit_codes:
            return list(self._fallback_unit_codes)
        raise ValueError("unit_codes 결측 — Problem은 단원 코드 최소 1개가 필요합니다.")

    def _parse_answer_format(self, value: object, spec: EquivalenceSpec) -> AnswerFormat | None:
        """답 형태 — 유효 enum 값이면 그대로, 무효면 스펙 답형태로 폴백."""
        if isinstance(value, str):
            try:
                return AnswerFormat(value.strip())
            except ValueError:
                pass
        return spec.answer_format

    @staticmethod
    def _parse_standard_codes(value: object, spec: EquivalenceSpec) -> list[str]:
        """성취기준 코드 — LLM 배열이 있으면 그것(게이트가 스펙 대비 검증), 없으면 스펙 폴백."""
        if isinstance(value, list):
            codes = [str(v).strip() for v in value if isinstance(v, str) and str(v).strip()]
            if codes:
                return codes
        return sorted(spec.achievement_standard_codes)

    def _acceptable_misconceptions(self, spec: EquivalenceSpec) -> frozenset[str]:
        """distractor 오개념 allowlist — 주입 카탈로그 키(있으면), 없으면 스펙 타깃(안전 폴백).

        레이어 순수성: L3는 L4 카탈로그를 import하지 않으므로 주입된 키집합을 실재 검증에 쓴다.
        미주입 시 `spec.target_misconception_ids`(스펙 저자가 검증한 카탈로그-실재 집합)로 폴백.
        """
        if self._catalog is not None:
            return frozenset(self._catalog)
        return spec.target_misconception_ids

    def _parse_distractor_map(self, value: object, spec: EquivalenceSpec) -> list[DistractorEntry]:
        """오답→오개념 매핑 — allowlist 밖 오개념 id는 드롭(미존재 방어). 무효 원소도 스킵."""
        if not isinstance(value, list):
            return []
        acceptable = self._acceptable_misconceptions(spec)
        entries: list[DistractorEntry] = []
        for raw in value:
            if not isinstance(raw, dict):
                continue
            mid = raw.get("misconception_id")
            idx = raw.get("choice_index")
            if not isinstance(mid, str) or mid.strip() not in acceptable:
                continue  # 미존재/미지 오개념 — 드롭(조용한 채택 금지)
            if not isinstance(idx, int) or isinstance(idx, bool) or idx < 0:
                continue
            op_raw = raw.get("op_code")
            op_code = op_raw.strip() if isinstance(op_raw, str) and op_raw.strip() else None
            entries.append(
                DistractorEntry(choice_index=idx, misconception_id=mid.strip(), op_code=op_code)
            )
        return entries

    @staticmethod
    def _parse_concept_tags(value: object) -> list[ConceptTag]:
        """개념 태깅(선택) — (concept_src_id·role·relevance). role은 ConceptRole 값·기본 PRIMARY."""
        if not isinstance(value, list):
            return []
        tags: list[ConceptTag] = []
        for raw in value:
            if not isinstance(raw, dict):
                continue
            src_id = raw.get("concept_src_id")
            if not isinstance(src_id, str) or not src_id.strip():
                continue
            role_raw = raw.get("role")
            role = role_raw if isinstance(role_raw, str) and role_raw in _VALID_ROLES else "PRIMARY"
            rel_raw = raw.get("relevance")
            relevance = (
                float(rel_raw)
                if isinstance(rel_raw, (int, float)) and not isinstance(rel_raw, bool)
                else None
            )
            tags.append(ConceptTag(concept_src_id=src_id.strip(), role=role, relevance=relevance))
        return tags

    def _stable_slug(self, question_text: str, answer: str, standard_codes: Sequence[str]) -> str:
        """결정론 안정 slug — `slug_prefix` + 내용 해시. 멱등 upsert 안정 키(재실행 재현).

        같은 내용은 같은 slug → S2-b 멱등 upsert가 중복 저장을 방지한다. 해시는 발문·정답·
        성취기준으로 만들어 콘텐츠가 바뀌면 slug도 바뀐다(내용-주소화).
        """
        payload = "|".join([question_text, answer, ",".join(sorted(standard_codes))])
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
        return f"{self._slug_prefix}-{digest}"

    @staticmethod
    def _enum_value(value: object) -> object:
        """enum이면 .value, 아니면 그대로(프롬프트 직렬화용·use_enum_values 대응)."""
        if isinstance(value, AnswerFormat):
            return value.value
        return value
