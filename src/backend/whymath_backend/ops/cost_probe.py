"""L3 대표 트래픽 프로브 — pipeline.generate를 대표 요청 믹스로 태워 게이트② 실측.

배경 (왜 이 도구가 필요한가)
----------------------------
S1 탈출 게이트 ②("루프당 LLM 비용 실측·로컬 ≥80%")는 `l3_routing` 이벤트의 분포로
판정한다(`ops/cost_report.py`). 그런데 이 이벤트를 내는 유일한 실측 경로는
**`l3.pipeline.generate`**(라우터→캐시→provider→관측 전 결선)뿐이다:

- `harness/problem_corpus_accumulate`는 `LLMEquivalentProblemGenerator`가 provider를
  *직접* 호출해 파이프라인·라우터·sink를 **우회**한다 → `l3_routing` 이벤트 0.
- `ops/live_preflight --via-pipeline`은 파이프라인을 태우지만 스모크 **1콜**뿐이라
  로컬:클라우드 *분포*를 낼 수 없다(단일 티어).

즉 게이트 ②를 *대표 트래픽*으로 재려면 파이프라인을 여러 요청으로 태우는 도구가
필요하다 — 이 모듈이 그 도구다(2026-07-16 실측에서 두 차례 "0건"으로 드러난 공백).
`live_preflight`의 pipeline 배선(CompositeProvider·InMemoryCache·LangfuseSink)을
재사용하되, 단일 스모크가 아니라 **문서화된 대표 요청 믹스**를 태운다.

무엇을 재나
-----------
1. **로컬 비율(게이트 ② 핵심)** — 라우터가 각 요청에 내린 `cost_tier` 결정을
   *인프로세스*로 집계한다(`result.decision.cost_tier`). Langfuse·DB에 의존하지 않으므로
   관측 인프라가 죽어도 판정선(Wilson 단측 하한 ≥0.8 — 점추정 판정 금지)을 낸다. 이번
   세션에서 드러난 취약점(Langfuse 키가 자리표시자면 cost_report가 조용히 0건) 방어.
2. **비용·지연 분포** — 파이프라인이 `l3_routing` 이벤트를 Langfuse에 실제 기록·flush
   하므로, 이 프로브를 돌린 뒤 `ops/cost_report --days 1`이 p50/p90·실측 cost_krw를
   집계한다(인그레션 지연 수 초 후).
3. **클라우드 승급 사슬 도달(OPS-18)** — `local_reason_counts`(LOCAL로 귀결된 사유를
   budget0/free/data_export_blocked/rule6_catchall 4버킷으로 계상)·`cloud_reach_count`
   (CLOUD_MID+CLOUD_HIGH 실측 도달 횟수)·`next_tier_calls`(에스컬레이션 재시도 호출 —
   이 단발 프로브는 항상 0). 0은 "0건 통과"가 아니라 **"미도달"**로 렌더한다 — 학생 요청
   6개 호출부가 구조적으로 클라우드에 못 올라가는 상태(§5-① 결제 미배선)가 "정상 응답"으로
   위장되지 않게 한다.
4. **데이터 등급 게이트 발동률(EOS-59 ②)** — 국외 반출 차단이 *실제로 몇 번 발동했는지*와
   그것이 반출 *시도*(클라우드 도달 + 차단) 중 몇 %인지. 이 수치는 **인프로세스**로 낸다 —
   Langfuse(외부 SaaS)에만 의존하면 관측이 죽었을 때 "0건 발동"과 "측정 실패"가 같은 색이
   된다(CLAUDE.md 이중 회계 원칙). Langfuse 측 집계는 `ops/cost_report.py`가 별도로 낸다.

대표 믹스의 근거 (표현이 아니라 트래픽 모델)
--------------------------------------------
PRD v1.2 §3의 첫 노출 페르소나 **A(일반고 고3·MVP)**는 대다수가 free/basic 구독이다.
라우터 불변식상 `free → LOCAL`(guard 규칙1)이라, free-우세 MVP 트래픽은 자연히
로컬-우세다. 이 믹스는 그 트래픽 모델을 반영한다 — 티어를 *지정*하지 않고 라우터가
결정하게 두므로, 라우터가 오라우팅하면 로컬 비율이 떨어져 그대로 드러난다(실측이지
날조가 아니다). 클라우드 지분을 빼고 싶으면 `--no-cloud`(과금 회피·로컬만).

설계 경계 (live_preflight 미러)
-------------------------------
- **순수 계획·집계 코어**(`build_probe_plan`·`summarize_decisions`)는 I/O 0 — 픽스처로
  전수 검증 가능(hermetic).
- **의존성 묶음**(`ProbeDeps`)은 팩토리로 주입 가능 — 테스트가 가짜 provider·스파이
  sink로 라이브 없이 파이프라인을 태운다(pipeline.generate 자체는 순수라 실물 그대로).
- 클라우드 archetype은 `anthropic_configured`일 때만 태운다(미설정 시 provider 오류
  회피) — live_preflight의 cloud_configured 게이팅과 동형. 키는 있으나 ARCH-66 정책
  차단으로 빠진 경우 그 사유를 `cloud_excluded_reason`에 싣는다(ARCH-68).

시크릿·비용 경계
----------------
키 *값*은 출력하지 않는다(설정 여부만). 클라우드 archetype은 실 Anthropic 호출이라
소액 과금된다 — 프롬프트는 짧게, 기본 라운드는 작게 둔다(`--rounds`).
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from whymath_backend.config import Settings
from whymath_backend.harness.wilson import wilson_lower_bound
from whymath_backend.l3 import pipeline
from whymath_backend.l3.data_export_policy import guard_data_export
from whymath_backend.l3.data_grade_defaults import SYNTHETIC_PROBE
from whymath_backend.l3.interfaces import CacheBackend, InMemoryCache, LLMProvider
from whymath_backend.l3.models import CostTier, RoutingRequest
from whymath_backend.l3.providers.anthropic import AnthropicProvider
from whymath_backend.l3.providers.composite import CompositeProvider
from whymath_backend.l3.providers.ollama import OllamaProvider
from whymath_backend.l3.router import _as_cost_tier, business_cost_tier
from whymath_backend.l3.trace.langfuse_sink import LangfuseSink

# 프로브 시스템 프롬프트 — 짧고 결정적(토큰·비용 실측이 목적이지 정답 채점이 아님).
_PROBE_SYSTEM = "너는 간결한 수학 조수다. 요청받은 것만 최소로 답한다."

# 종료 코드 — 게이트 CLI 관례(exit 0/1 — defect_detection_eval·corpus_audit_eval 동형).
_EXIT_OK = 0
_EXIT_GATE_FAIL = 1

# 게이트 ② 로컬 판정 임계 — 판정은 점추정이 아니라 **Wilson 단측 하한(95%)**으로 한다
# (초인간 검증 표준 "점추정·인상 판정 금지"). 하한은 표본 수를 보정하므로 소표본은
# 구조적으로 통과 불가 — 예: 4/5=80%(점추정)도 하한 ≈44%라 FAIL, 전량 로컬이어도
# n≥11이어야 하한이 0.80을 넘는다(2026-07-21 정합성 검토: 점추정 PASS이던 공백 보정).
_GATE2_LOCAL_THRESHOLD = 0.80


# ──────────────────────────────────────────────────────────────────────────
# 대표 요청 믹스 — 티어를 지정하지 않고 라우터가 결정하게 둔다(실측). 각 archetype은
# 왜 그 티어로 라우팅되는지 근거를 주석에 남긴다(router 규칙 참조).
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class Archetype:
    """대표 트래픽 1종 — 요청 템플릿 + 프롬프트 stub + 가중치(라운드당 인스턴스 수)."""

    label: str
    request: RoutingRequest
    prompt_stub: str
    weight: int
    routes_cloud: bool  # 클라우드 라우팅 기대 여부(anthropic 미설정 시 제외 대상)


def _local_request(
    task_type: str, difficulty: str, *, reasoning: bool = False, sub: str = "free"
) -> RoutingRequest:
    """LOCAL로 라우팅되는 요청 — free 구독(guard 규칙1: free→LOCAL) 또는 예산 0 강등.

    sync=True라 QUALITY(async)로 새지 않는다(동기 생성만 — 큐 없이 안전).
    """
    return RoutingRequest(
        task_type=task_type,
        difficulty=difficulty,
        requires_reasoning=reasoning,
        student_subscription=sub,
        budget_krw=0.0,  # 클라우드 예산 0 → guard 규칙2로도 LOCAL 강등(free면 규칙1이 이미 강등)
        sync=True,
        # 등급: 프롬프트가 이 파일의 합성 스텁("1 + 1은 얼마인가?" 등)뿐 — 제3자 자료 0(EOS-59).
        data_licenses=SYNTHETIC_PROBE,
    )


def _cloud_mid_request(task_type: str, difficulty: str) -> RoutingRequest:
    """CLOUD_MID(sync)로 신뢰성 있게 라우팅되는 요청 (live_preflight._cloud_mid_smoke_request 동형).

    premium + requires_reasoning + 충분한 budget → guard(CLOUD_MID) 통과. killer/prove가
    아니라 CLOUD_HIGH로 승급 안 하고, sync=True라 async로도 안 샌다.
    """
    return RoutingRequest(
        task_type=task_type,
        difficulty=difficulty,
        requires_reasoning=True,
        student_subscription="premium",
        budget_krw=1000.0,  # cloud_min_cost(CLOUD_MID) 여유(guard 통과)
        sync=True,
        max_latency_ms=30000,
        # 등급: 합성 스텁 — 반출 가능. 이 프로브의 *존재 이유*가 클라우드 1콜 실측이므로
        # 등급이 제한이면 게이트가 로컬로 강등해 클라우드 비용을 영영 못 잰다(EOS-59).
        data_licenses=SYNTHETIC_PROBE,
    )


# free-우세 MVP(페르소나 A) 트래픽 모델 — 로컬 archetype 9 : 클라우드 1(라운드당 10건).
# 가중치는 "라운드당 인스턴스 수"다(--rounds가 전체를 배수). 티어는 라우터가 결정한다.
REPRESENTATIVE_MIX: tuple[Archetype, ...] = (
    # ── 학생 대면 로컬 경로(텍스트 태스크·free/basic 구독) ──
    Archetype(
        "explain-easy-free", _local_request("explain", "easy"), "1 + 1은 얼마인가?", 3, False
    ),
    Archetype(
        "diagnose-medium-free",
        _local_request("diagnose", "medium", reasoning=True),
        "이차방정식 x^2-5x+6=0의 근을 구하는 과정을 짧게 설명하라.",
        2,
        False,
    ),
    Archetype(
        "coach-medium-free",
        _local_request("coach", "medium"),
        "학생이 미분 개념에서 막혔다. 힌트 한 줄만 제시하라.",
        2,
        False,
    ),
    Archetype(
        "verify-easy-free",
        _local_request("verify", "easy"),
        "3 + 4 = 7 인가? 예/아니오로만 답하라.",
        1,
        False,
    ),
    Archetype(
        "explain-medium-basic",
        _local_request("explain", "medium", sub="basic"),  # basic·예산0 → guard 규칙2 LOCAL 강등
        "일차함수의 기울기를 한 문장으로 설명하라.",
        1,
        False,
    ),
    # ── 소수 premium 클라우드 경로(anthropic 설정 시에만 태움) ──
    Archetype(
        "diagnose-hard-premium",
        _cloud_mid_request("diagnose", "hard"),
        "로그 함수의 정의역을 구하는 사고 과정을 단계별로 짧게 제시하라.",
        1,
        True,
    ),
)


# ──────────────────────────────────────────────────────────────────────────
# 순수 계획·집계 코어 — I/O 없음(hermetic 테스트 가능).
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class ProbeItem:
    """실행 계획 1건 — archetype에서 펼쳐진 (라벨·요청·고유 프롬프트)."""

    label: str
    request: RoutingRequest
    prompt: str


def build_probe_plan(
    mix: tuple[Archetype, ...], rounds: int, *, include_cloud: bool
) -> list[ProbeItem]:
    """대표 믹스를 rounds배로 펼쳐 실행 계획을 만든다(프롬프트는 인스턴스마다 고유).

    include_cloud=False면 클라우드 archetype(routes_cloud)을 제외한다(anthropic 미설정).
    프롬프트에 전역 순번을 붙여 캐시 키를 유일화한다 — 같은 프롬프트 반복이 캐시 히트가
    되면 실측 usage 표본이 유실되므로(pipeline은 히트 시 usage 미기록) 전부 미스를 강제.
    """
    if rounds < 1:
        raise ValueError("rounds는 1 이상이어야 합니다.")
    plan: list[ProbeItem] = []
    idx = 0
    for _ in range(rounds):
        for arc in mix:
            if arc.routes_cloud and not include_cloud:
                continue
            for _ in range(arc.weight):
                prompt = f"{arc.prompt_stub} (변형 {idx})"
                plan.append(ProbeItem(label=arc.label, request=arc.request, prompt=prompt))
                idx += 1
    return plan


# ──────────────────────────────────────────────────────────────────────────
# LOCAL 강등 사유 4버킷 (OPS-18 acceptance② — "왜 로컬로 귀결됐는가" 계상
#                        + EOS-59 ② — 데이터 등급 게이트 "작동한 비율")
#
# `router.Router._decide_cost_tier`(03a §C.1)와 *동일한 규칙 순서*로 판별한다:
#   규칙1 budget_krw<=0            → "budget0"
#   규칙2(규칙1 미해당) subscription=="free" → "free"
#   법적 게이트(EOS-59): 비즈니스 축은 클라우드를 원했는데 데이터 등급이 막음
#                                  → "data_export_blocked"
#   그 외(규칙3·4가 매치 안 했거나 guard_cloud가 강등)  → "rule6_catchall"
# 호출자는 실제 결정이 LOCAL로 확정된 요청에만 분류를 적용한다(그 외 티어에는 의미 없음).
#
# EOS-59에서 규칙1·2 이후 구간은 *손 미러를 그만두고* 라우터 함수(`business_cost_tier`·
# `guard_data_export`)를 직접 호출한다 — 사유를 하나 더 가르려면 규칙3·4·guard_cloud까지
# 베껴야 하는데, 그 사본은 반드시 갈라진다(이 주석이 원래 "자동 동기화 없음"을 경고하던
# 바로 그 위험). 규칙1·2만 여기 남는 이유는 그 둘이 *사유를 가르는* 정보(어느 규칙이
# 먼저 걸렸나)를 라우터 반환값에서 복원할 수 없기 때문이다.
# ──────────────────────────────────────────────────────────────────────────
LOCAL_REASON_BUDGET0 = "budget0"
LOCAL_REASON_FREE = "free"
LOCAL_REASON_DATA_EXPORT = "data_export_blocked"
LOCAL_REASON_RULE6_CATCHALL = "rule6_catchall"
LOCAL_REASONS: tuple[str, ...] = (
    LOCAL_REASON_BUDGET0,
    LOCAL_REASON_FREE,
    LOCAL_REASON_DATA_EXPORT,
    LOCAL_REASON_RULE6_CATCHALL,
)


def classify_local_reason(req: RoutingRequest) -> str:
    """LOCAL 결정 사유 분류 — 규칙1·2 미러 + 법적 게이트는 라우터 함수 직접 호출(OPS-18·EOS-59).

    호출자는 실제 `route(req).cost_tier`가 LOCAL로 확정된 요청에만 이 함수를 쓴다. CLOUD로
    간 요청에 호출해도 값은 나오지만 의미가 없다(그 요청은 애초에 이 계상 대상이 아니다).

    `data_export_blocked` 버킷이 **in-process 이중 회계**의 판정치다 — 데이터 등급 게이트의
    발동률을 Langfuse(외부 SaaS)에만 의존해 세면 관측 인프라가 죽었을 때 "0건 발동"과
    "측정 실패"가 같은 색이 된다(CLAUDE.md 이중 회계 원칙·`cost_probe` 로컬 비율 선례).
    """
    if req.budget_krw <= 0:
        return LOCAL_REASON_BUDGET0
    if req.student_subscription == "free":
        return LOCAL_REASON_FREE
    # 비즈니스 축이 클라우드를 원했는데 법적 축이 막았는가 — 라우터와 같은 함수로 판정한다.
    desired = business_cost_tier(req)
    if desired is not CostTier.LOCAL and guard_data_export(desired, req.data_licenses) is (
        CostTier.LOCAL
    ):
        return LOCAL_REASON_DATA_EXPORT
    return LOCAL_REASON_RULE6_CATCHALL


def _local_reason_counts(
    tier_values: Sequence[str], requests: Sequence[RoutingRequest]
) -> dict[str, int]:
    """성공분 (tier, request) 쌍에서 LOCAL만 골라 사유별 계상 — 4버킷 모두 키 보장(미관측=0)."""
    counts = {reason: 0 for reason in LOCAL_REASONS}
    for tier, req in zip(tier_values, requests, strict=True):
        if tier != CostTier.LOCAL.value:
            continue
        counts[classify_local_reason(req)] += 1
    return counts


@dataclass(slots=True)
class ProbeReport:
    """프로브 결과 — 라우터 결정 기반 로컬 비율(게이트② 판정선)·티어 분포·오류 회계.

    `local_reason_counts`·`cloud_reach_count`·`next_tier_calls`는 OPS-18 승급 사슬 도달
    관측 계상이다 — "0건 통과"(측정해서 0)와 "미도달"(구조적으로 도달한 적이 없음, 또는
    이 프로브가 애초에 시행하지 않는 축)을 구분한다(CLAUDE.md 침묵 실패 금지).
    """

    total: int
    tier_counts: dict[str, int]
    errors: int
    error_samples: list[str]
    cloud_included: bool
    local_ratio: float | None  # 로컬/성공분. 성공분 0이면 None('미상'과 0 구분 — 날조 금지).
    rounds: int
    # LOCAL 강등 사유별 계상(budget0/free/rule6_catchall). `requests`를 준 호출만 채워진다 —
    # None은 "0건"이 아니라 "이 호출은 사유를 계상하지 않았다"(레거시 순수 tier_values 호출
    # 호환·회귀 0, OPS-18 acceptance②).
    local_reason_counts: dict[str, int] | None = None
    # 자동 결정(include_cloud=None)이 ARCH-66 정책 차단 때문에 클라우드 archetype을 뺐을 때의
    # 사유(ARCH-68). `cloud_included=False`만으로는 키가 없어서인지·막혀서인지·--no-cloud인지
    # 모른다. 키 미설정·--no-cloud면 None(종전 출력 그대로).
    cloud_excluded_reason: str | None = None

    def to_json(self) -> dict[str, object]:
        data = dataclasses.asdict(self)
        data["local_ratio_lower"] = self.local_ratio_lower
        data["gate2_local_pass"] = self.gate2_local_pass
        data["cloud_reach_count"] = self.cloud_reach_count
        data["next_tier_calls"] = self.next_tier_calls
        data["data_export_blocked_count"] = self.data_export_blocked_count
        data["offshore_intent_count"] = self.offshore_intent_count
        data["data_export_block_rate"] = self.data_export_block_rate
        data["data_export_block_rate_of_intent"] = self.data_export_block_rate_of_intent
        return data

    # ── 데이터 등급 게이트 "작동한 비율" (EOS-59 ②) ──────────────────────
    @property
    def data_export_blocked_count(self) -> int | None:
        """법적 게이트가 *실제로* 클라우드를 막은 건수. 사유 계상을 안 한 호출이면 None.

        None은 0이 아니다 — "게이트가 한 번도 안 걸렸다"와 "이 프로브는 사유를 안 물었다"를
        구분한다(`local_reason_counts`의 None 의미론 그대로).
        """
        if self.local_reason_counts is None:
            return None
        return self.local_reason_counts.get(LOCAL_REASON_DATA_EXPORT, 0)

    @property
    def offshore_intent_count(self) -> int | None:
        """비즈니스 축이 *국외 티어를 원한* 요청 수 = 실제 클라우드 도달 + 게이트가 막은 건수.

        "작동한 비율"의 정직한 분모다 — 전체 라우팅으로 나누면 애초에 로컬만 도는 트래픽에서
        비율이 한없이 0에 수렴해 게이트가 일했는지 알 수 없다(로컬 우세가 MVP 트래픽 모델이라
        그 왜곡이 상시적이다).
        """
        blocked = self.data_export_blocked_count
        if blocked is None:
            return None
        return self.cloud_reach_count + blocked

    @property
    def data_export_block_rate(self) -> float | None:
        """전체 성공분 대비 게이트 발동 비율. 성공분 0이거나 미계상이면 None(미상 ≠ 0%)."""
        blocked = self.data_export_blocked_count
        succeeded = self.total - self.errors
        if blocked is None or succeeded <= 0:
            return None
        return blocked / succeeded

    @property
    def data_export_block_rate_of_intent(self) -> float | None:
        """국외 반출을 *시도한* 요청 중 게이트가 막은 비율 — 게이트의 실효 발동률.

        분모 0(아무도 클라우드를 원하지 않았다)이면 None이다 — 그 경우 "0% 발동"이 아니라
        **"게이트가 판정할 기회가 없었다"**가 맞다(0건 통과 ≠ 미도달, OPS-18 관례).
        """
        blocked = self.data_export_blocked_count
        intent = self.offshore_intent_count
        if blocked is None or intent is None or intent == 0:
            return None
        return blocked / intent

    @property
    def local_ratio_lower(self) -> float | None:
        """로컬 비율의 Wilson 단측 하한(95%) — 게이트 판정용(소표본 과신 방지).

        성공 표본 0이면 None('미상'과 0 구분 — 날조 금지). 점추정(local_ratio)은
        리포트용으로 병기하고, 판정은 항상 이 하한으로 한다.
        """
        succeeded = self.total - self.errors
        if succeeded <= 0:
            return None
        local = self.tier_counts.get(CostTier.LOCAL.value, 0)
        return wilson_lower_bound(local, succeeded)

    @property
    def gate2_local_pass(self) -> bool | None:
        """게이트 ② 로컬 판정선 — Wilson 하한(95%) ≥ 0.80. 표본 0이면 None(판정 불가)."""
        lower = self.local_ratio_lower
        if lower is None:
            return None
        return lower >= _GATE2_LOCAL_THRESHOLD

    @property
    def cloud_reach_count(self) -> int:
        """CLOUD_MID+CLOUD_HIGH 합산 — 승급 사슬이 실제로 클라우드에 도달한 실측 횟수.

        `tier_counts`에서 유도(신규 회계 없음 — 이미 있던 분포를 이름 붙여 노출). 0이면
        render_report는 "0건 통과"가 아니라 **"미도달"**로 표기한다 — 구조적으로 도달한 적
        없음과 측정해서 0인 것을 같은 말로 뭉개지 않는다(OPS-18 배경 그 자체).
        """
        return self.tier_counts.get(CostTier.CLOUD_MID.value, 0) + self.tier_counts.get(
            CostTier.CLOUD_HIGH.value, 0
        )

    @property
    def next_tier_calls(self) -> int:
        """`router.next_tier()` 호출 횟수 — 이 단발 프로브는 `route()`만 태우므로 **항상 0**.

        에스컬레이션 재시도(자기일관성 불일치 등, 03a §D.2)는 생성 파이프라인이 트리거를
        감지한 *다음*에 호출하는 별도 경로다 — 단발 `route()` 프로브의 범위 밖(OPS-18 범위
        밖 동결). 0을 "미시행"으로 명시해 조용한 누락(어디에도 안 적힘)과 구분한다.
        """
        return 0


def summarize_decisions(
    tier_values: list[str],
    *,
    errors: int,
    error_samples: list[str],
    cloud_included: bool,
    rounds: int,
    requests: Sequence[RoutingRequest] | None = None,
) -> ProbeReport:
    """라우터가 결정한 cost_tier 문자열 리스트 → 로컬 비율·분포 집계(순수).

    성공분(tier_values)만 분모로 쓴다 — 오류(생성 실패)는 티어 결정과 무관한 실패라
    별도 회계한다(지어내지 않음). 성공분 0이면 local_ratio=None(미상).

    `requests`: `tier_values`와 같은 순서·같은 길이의 원 `RoutingRequest`(선택, OPS-18).
    주어지면 LOCAL 강등 사유(budget0/free/rule6_catchall)를 계상해 `local_reason_counts`를
    채운다. None이면(레거시 호출·회귀 0) 계상하지 않고 None으로 남긴다 — "0건"과
    "이 호출은 사유를 안 물었다"를 구분한다(날조 금지).
    """
    tier_counts: dict[str, int] = {}
    for tier in tier_values:
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
    succeeded = len(tier_values)
    local = tier_counts.get(CostTier.LOCAL.value, 0)
    local_ratio = (local / succeeded) if succeeded > 0 else None
    reason_counts = _local_reason_counts(tier_values, requests) if requests is not None else None
    return ProbeReport(
        total=succeeded + errors,
        tier_counts=tier_counts,
        errors=errors,
        error_samples=error_samples,
        cloud_included=cloud_included,
        local_ratio=local_ratio,
        rounds=rounds,
        local_reason_counts=reason_counts,
    )


# ──────────────────────────────────────────────────────────────────────────
# 의존성·구동 — live_preflight의 pipeline 배선 미러(주입 가능).
# ──────────────────────────────────────────────────────────────────────────
class _FlushSink(Protocol):
    """record(파이프라인) + flush(CLI 후처리)를 갖춘 관측성 싱크 경계(LangfuseSink 충족)."""

    def record(self, fields: dict[str, object]) -> None: ...

    def flush(self) -> None: ...


# pipeline.generate 시그니처의 좁은 별칭(테스트 주입용).
_PipelineGenerate = Callable[..., Awaitable[pipeline.GenerationResult]]


@dataclass(slots=True)
class ProbeDeps:
    """프로브 의존성 묶음 — 테스트가 통째로 주입 가능(live_preflight.PipelineDeps 미러)."""

    provider: LLMProvider
    cache: CacheBackend
    trace: _FlushSink
    generate: _PipelineGenerate


ProbeDepsFactory = Callable[[Settings], ProbeDeps]


def _default_probe_deps(settings: Settings) -> ProbeDeps:
    """기본 의존성 — CompositeProvider·InMemoryCache·LangfuseSink(지연 클라이언트).

    provider·sink는 지연 접속이라 여기서 네트워크·키를 요구하지 않는다(첫 호출 시에만).
    capturing 래핑은 쓰지 않는다 — 로컬 비율은 result.decision에서 인프로세스로 집계하고,
    비용·지연 분포는 cost_report가 Langfuse에서 읽는다(관심사 분리).
    """
    provider = CompositeProvider(
        local=OllamaProvider(settings=settings),
        cloud=AnthropicProvider(settings=settings),
    )
    return ProbeDeps(
        provider=provider,
        cache=InMemoryCache(),
        trace=LangfuseSink(settings=settings),
        generate=pipeline.generate,
    )


@dataclass(slots=True)
class _RunOutcome:
    """구동 중간 회계 — 성공 (티어·요청) 목록 + 오류 수·표본(최대 5건).

    `requests`는 `tier_values`와 같은 순서로 쌓인다(같은 루프 반복에서 함께 append) —
    LOCAL 강등 사유 계상(`summarize_decisions(requests=...)`)이 이 정렬에 의존한다(OPS-18).
    """

    tier_values: list[str] = field(default_factory=list)
    requests: list[RoutingRequest] = field(default_factory=list)
    errors: int = 0
    error_samples: list[str] = field(default_factory=list)


async def run_probe(
    settings: Settings,
    *,
    rounds: int = 3,
    include_cloud: bool | None = None,
    mix: tuple[Archetype, ...] = REPRESENTATIVE_MIX,
    deps_factory: ProbeDepsFactory = _default_probe_deps,
) -> ProbeReport:
    """대표 믹스를 pipeline.generate로 태워 로컬 비율을 집계하고 Langfuse에 기록·flush 한다.

    include_cloud=None이면 anthropic 설정 여부로 자동 결정한다(미설정 시 로컬 믹스만 —
    클라우드 provider 오류 회피). 각 요청의 예외는 흡수해 오류로 회계한다(never-break:
    한 요청 실패가 전체 측정을 깨지 않는다). flush 실패도 삼킨다(LangfuseSink 방침 동형).
    """
    cloud = settings.anthropic_configured if include_cloud is None else include_cloud
    # 자동 결정이 정책 차단 때문에 클라우드를 뺐다면 그 사유를 리포트에 남긴다(ARCH-68).
    # --no-cloud(include_cloud=False)는 사람이 고른 것이라 사유를 붙이지 않는다.
    policy_block = settings.anthropic_policy_block_reason
    excluded_reason = policy_block if include_cloud is None and not cloud else None
    plan = build_probe_plan(mix, rounds, include_cloud=cloud)
    deps = deps_factory(settings)

    outcome = _RunOutcome()
    for item in plan:
        try:
            result = await deps.generate(
                item.request,
                item.prompt,
                _PROBE_SYSTEM,
                provider=deps.provider,
                cache=deps.cache,
                trace=deps.trace,
            )
        except Exception as exc:  # noqa: BLE001 — 요청별 실패를 오류로 회계(전체 측정 보존)
            outcome.errors += 1
            if len(outcome.error_samples) < 5:
                outcome.error_samples.append(f"[{item.label}] {type(exc).__name__}: {exc}")
            continue
        outcome.tier_values.append(_as_cost_tier(result.decision.cost_tier).value)
        outcome.requests.append(item.request)

    # 짧게 끝나는 CLI — 배치 유실 방지로 전송을 지금 확정한다(LangfuseSink.flush는 오류를 삼킴).
    deps.trace.flush()

    report = summarize_decisions(
        outcome.tier_values,
        errors=outcome.errors,
        error_samples=outcome.error_samples,
        cloud_included=cloud,
        rounds=rounds,
        requests=outcome.requests,
    )
    return dataclasses.replace(report, cloud_excluded_reason=excluded_reason)


# ──────────────────────────────────────────────────────────────────────────
# 렌더링·CLI — live_preflight/cost_report 관례(사람용 표 + 선택 JSON·얇은 main).
# ──────────────────────────────────────────────────────────────────────────
def _fmt_ratio(value: float | None) -> str:
    """비율|None 표기 — None은 '미상'(0%와 구분)."""
    return "미상" if value is None else f"{value * 100:.1f}%"


def render_report(report: ProbeReport) -> str:
    """사람용 요약 — 로컬 비율(게이트② 판정선)·티어 분포·오류. 시크릿 값 출력 0."""
    lines: list[str] = []
    lines.append("=" * 64)
    lines.append("WhyMath L3 대표 트래픽 프로브 — 로컬 비율 실측(게이트② 판정)")
    lines.append("=" * 64)
    lines.append(f"라운드: {report.rounds}  ·  클라우드 archetype 포함: {report.cloud_included}")
    if report.cloud_excluded_reason is not None:
        lines.append(f"  ↳ 클라우드 제외 사유: {report.cloud_excluded_reason}")
    succeeded = report.total - report.errors
    lines.append(f"총 요청: {report.total}건  ·  성공: {succeeded}  ·  오류: {report.errors}")
    if report.error_samples:
        lines.append("[오류 표본 — 최대 5건]")
        for sample in report.error_samples:
            lines.append(f"  {sample}")
    lines.append("[티어 분포 — 라우터 결정 실측]")
    if report.tier_counts:
        for tier, count in sorted(report.tier_counts.items()):
            lines.append(f"  {tier:<12}: {count}건")
    else:
        lines.append("  (성공 표본 없음)")
    lines.append("[로컬:클라우드 — 게이트② 목표 ≥80% 로컬]")
    lines.append(f"  로컬 비율(점추정): {_fmt_ratio(report.local_ratio)}")
    lines.append(f"  로컬 비율 Wilson 하한(95%): {_fmt_ratio(report.local_ratio_lower)}")
    verdict = report.gate2_local_pass
    verdict_str = "판정 불가(표본 0)" if verdict is None else ("PASS" if verdict else "미달")
    lines.append(f"  게이트② 로컬 판정선(Wilson 하한 ≥80%): {verdict_str}")
    if verdict is False and report.local_ratio is not None and report.local_ratio >= 0.80:
        lines.append("  ※ 점추정은 80% 이상이나 표본이 작아 하한 미달 — --rounds를 키워 재측정.")
    lines.append(
        "[LOCAL 강등 사유 — budget0/free/data_export_blocked/rule6_catchall 4버킷"
        "(OPS-18·EOS-59)]"
    )
    if report.local_reason_counts is None:
        lines.append("  (사유 계상 미제공 — requests 없이 호출된 리포트)")
    else:
        for reason in LOCAL_REASONS:
            lines.append(f"  {reason:<20}: {report.local_reason_counts[reason]}건")
    lines.append("[클라우드 승급 도달 — CLOUD_MID+CLOUD_HIGH 실측(OPS-18)]")
    if report.cloud_reach_count == 0:
        lines.append(
            "  클라우드 도달: 미도달 (0건 통과가 아니라 승급 사슬이 구조적으로 도달한 적 없음)"
        )
    else:
        lines.append(f"  클라우드 도달: {report.cloud_reach_count}건")
    # 데이터 등급 게이트 "작동한 비율"(EOS-59 ②) — 인프로세스 판정치. 정상 응답 200은
    # 게이트가 일했다는 증거가 아니므로, 몇 번 발동했고 그것이 *반출 시도* 중 몇 %인지 적는다.
    lines.append("[데이터 등급 게이트 — 국외 반출 차단 발동률(EOS-59)]")
    blocked = report.data_export_blocked_count
    if blocked is None:
        lines.append("  (사유 계상 미제공 — requests 없이 호출된 리포트라 발동률 산정 불가)")
    else:
        intent = report.offshore_intent_count
        lines.append(f"  차단 발동: {blocked}건  ·  국외 반출 시도(도달+차단): {intent}건")
        lines.append(f"  전체 대비 발동률: {_fmt_ratio(report.data_export_block_rate)}")
        rate_of_intent = report.data_export_block_rate_of_intent
        if rate_of_intent is None:
            lines.append(
                "  반출 시도 대비 발동률: 판정 기회 없음 "
                "(아무 요청도 국외 티어를 원하지 않았다 — 0% 발동과 다르다)"
            )
        else:
            lines.append(f"  반출 시도 대비 발동률: {_fmt_ratio(rate_of_intent)}")
    lines.append("[next_tier() 호출 — 에스컬레이션 재시도, 단발 프로브 범위 밖(OPS-18)]")
    if report.next_tier_calls == 0:
        lines.append(
            "  next_tier 호출: 미도달 (0건 실패가 아니라 이 프로브가 애초에 시행하지 않음)"
        )
    else:
        lines.append(f"  next_tier 호출: {report.next_tier_calls}건")
    lines.append("=" * 64)
    lines.append("다음: 수 초 후 `python -m whymath_backend.ops.cost_report --days 1`로")
    lines.append("비용·지연 분포(p50/p90)를 집계한다 — 로컬 비율은 위 인프로세스 실측이")
    lines.append("Langfuse 상태와 무관하게 이미 판정선을 냈다(관측 인프라 취약점 방어).")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.ops.cost_probe",
        description=(
            "L3 대표 트래픽 프로브 — pipeline.generate를 대표 요청 믹스로 태워 로컬 비율을 "
            "실측(게이트② 판정)하고 Langfuse에 l3_routing 이벤트를 기록한다."
        ),
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=3,
        help=(
            "대표 믹스 반복 배수(표본 크기). 판정은 Wilson 하한이라 소표본은 구조적으로 "
            "통과 불가 — 전량 로컬 기준 n≥11(rounds≥2) 필요, 기본 3 권장."
        ),
    )
    parser.add_argument(
        "--no-cloud",
        action="store_true",
        help="anthropic 설정돼 있어도 클라우드 archetype 제외(로컬만·과금 회피).",
    )
    parser.add_argument("--json", type=Path, default=None, help="JSON 리포트 출력 경로(선택).")
    args = parser.parse_args(argv)

    settings = Settings()
    include_cloud = False if args.no_cloud else None  # None=anthropic 설정 여부로 자동
    report = asyncio.run(run_probe(settings, rounds=args.rounds, include_cloud=include_cloud))

    print(render_report(report))
    if args.json is not None:
        args.json.write_text(
            json.dumps(report.to_json(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"JSON 리포트 저장: {args.json}")

    # 종료 코드 = 판정선 그대로(게이트 CLI 관례 exit 0/1 — 인상 판정 금지). PASS=0,
    # 미달·판정불가=1(argparse 사용 오류의 2와 구분 — 형제 게이트 동형).
    return _EXIT_OK if report.gate2_local_pass else _EXIT_GATE_FAIL


if __name__ == "__main__":
    sys.exit(main())
