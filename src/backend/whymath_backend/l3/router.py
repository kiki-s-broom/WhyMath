"""L3 라우터 결정 로직 — 축1(C.1) → [LOCAL이면] 축3(C.0) → 축2(C.2) 순차 결정.

설계 정본: `docs/architecture/03a_l3_router_design.md`
  - §C.1 축1 결정표(6규칙) / §C.0 축3 패밀리 결정표(5규칙) / §C.2 축2 결정표(7규칙)
    + §C.4 의사코드
  - §A.0 패밀리(축3)×크기(축2) 매트릭스 → 실제 모델 ID lookup
  - §D 에스컬레이션·폴백 체인 / §D.4 guard_cloud
  - §E 비용·예산·구독별 일일 한도 / §F 캐싱 키·Langfuse 필드
  - §A.1 벤치 지연(FAST≈1010ms·MID≈3918ms·QUALITY≈13886ms)

범위 메모 (M1.2): 본 모듈은 *결정 로직*과 *추정·키 생성*만 구현한다(순수 Python).
실제 LLM 호출·Redis·Langfuse·비동기 큐는 `interfaces.py`의 Protocol/스텁으로만
경계를 둔다. `langfuse_fields()`는 *태그 dict만* 만들고 실제 전송은 하지 않는다.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Final

from whymath_backend.config import CloudSeat
from whymath_backend.l3.data_export_policy import (
    OFFSHORE_TIERS,
    export_judgment,
    export_judgment_for,
    guard_data_export,
)
from whymath_backend.l3.models import (
    CallSite,
    CostTier,
    LocalModelTier,
    ModelFamily,
    RoutingDecision,
    RoutingRequest,
    Usage,
)

# ──────────────────────────────────────────────────────────────────────────
# 그라운딩 상수 — 03a §A.1 벤치(2026-05-19, Phaiakes9 / Radeon 8060S / Ollama 0.24.0)
# 로컬 티어별 p50 지연(ms). 토큰당 비용은 0원(Phaiakes9 로컬).
# ──────────────────────────────────────────────────────────────────────────
LOCAL_LATENCY_MS: Final[dict[LocalModelTier, int]] = {
    LocalModelTier.FAST: 1010,  # qwen2-math:1.5b — p50 1,010ms, SLA PASS
    LocalModelTier.MID: 3918,  # qwen2-math:7b — p50 3,918ms
    # QUALITY: qwen3:30b-a3b(MoE) 왕복 p50 ≈ 2,300ms(2026-08-22, ctx 8192/np 1/flash on/ROCm).
    # dense 27B(qwen3.5:27b)는 12,406ms로 5.4배 느림 — OPS-48 판정으로 MoE 채택.
    LocalModelTier.QUALITY: 2300,
}
"""로컬 티어별 예상 지연(ms). 출처: 03a §A.1 벤치 p50.

지연은 *크기 등급별* 대표값이다(2026-05-19 벤치는 qwen2-math 라인업으로 측정).
같은 크기 등급의 GENERAL(qwen2.5:3b/7b) 지연은 동급으로 가정한다(03a §A.1 메모,
패밀리별 지연 재측정은 §H 후속).
"""

# ──────────────────────────────────────────────────────────────────────────
# 축3 그라운딩 — 패밀리(축3)×크기(축2) → 실제 모델 ID 매트릭스 (03a §A.0·§C.4)
# QUALITY(MoE)는 패밀리 무관 상위 티어 — 매트릭스에 (패밀리, QUALITY)는 두지 않고
# resolve_model()이 별도 처리한다(MoE가 양 패밀리 포괄, 03a §A.0).
# ──────────────────────────────────────────────────────────────────────────
LOCAL_MODEL_MATRIX: Final[dict[tuple[ModelFamily, LocalModelTier], str]] = {
    (ModelFamily.MATH, LocalModelTier.FAST): "qwen2-math:1.5b",
    (ModelFamily.MATH, LocalModelTier.MID): "qwen2-math:7b",
    (ModelFamily.GENERAL, LocalModelTier.FAST): "qwen2.5:3b",
    (ModelFamily.GENERAL, LocalModelTier.MID): "qwen2.5:7b",
    # 멀티모달(VL) — Qwen3-VL 단일 모델. `:latest` 드리프트 회피로 `qwen3-vl:8b` 명시 핀
    # (6.1GB·현 :latest·로컬 풀 가능). 2026-06-23 ollama 태그 확인(4b/8b/235b-cloud).
    # ★ pull_ocr_models.sh VL_MODEL 디폴트·OCR_LIVE_VERIFICATION.md와 *반드시* 일치시킬 것.
    (ModelFamily.VISION, LocalModelTier.FAST): "qwen3-vl:8b",
}
"""로컬 모델 ID = (패밀리 축3 × 크기 축2) lookup. 출처: 03a §A.0 매트릭스.

QUALITY는 패밀리 무관 → 이 매트릭스에 없고 QUALITY_MODEL_ID로 해석한다.
llm-architect.md A.0 매트릭스와 동일해야 한다.
"""

QUALITY_MODEL_ID: Final[str] = "qwen3:30b-a3b"
"""QUALITY 티어 실제 모델 — 패밀리 무관(MoE, 03a §A.0).

2026-08-22 OPS-48 판정: dense 27B(qwen3.5:27b) 대비 MoE(qwen3:30b-a3b)가
생성 6.0배·왕복 5.4배 빠르면서도 정확도(검출률/오경보)가 열등하지 않음.
단, 파싱 실패율 16%(기준 1%)로 운영 전 추가 샘플링·프롬프트 튜닝이 권장됨.
"""

# ──────────────────────────────────────────────────────────────────────────
# 축3 결정 입력 집합 — NLP임이 분명한 호출지점·태스크 (03a §C.0 규칙1·3)
# "NLP임이 분명할 때 GENERAL, 그 외 MATH(안전 기본값)" — 03a §C.0 메모.
# ──────────────────────────────────────────────────────────────────────────
NLP_CALL_SITES: Final[frozenset[CallSite]] = frozenset(
    {
        CallSite.CONCEPT_EXTRACT,  # ① 개념 추출
        CallSite.TRANSLATE_NORMALIZE,  # ③ 번역·정규화
        CallSite.CONCEPT_ID_MATCH,  # ④ 개념 ID 매칭
    }
)
"""NLP 호출지점(축3=GENERAL) — ①③④ (03a §C.0 규칙1). ②(깊이추론)는 MATH."""

NLP_TASK_TYPES: Final[frozenset[str]] = frozenset({"extract", "match", "translate", "classify"})
"""NLP 계열 task_type(축3=GENERAL) — 추출·매칭·정규화·분류 (03a §C.0 규칙3)."""

SLA_GATE_MS: Final[int] = 2000
"""동기 즉답 SLA 게이트(ms). FAST(p50 1,010ms)만 통과 (03a §A.1·C.2 규칙3)."""

# ──────────────────────────────────────────────────────────────────────────
# 구독별 일일 한도(원) — 03a §E.2 표 (확정값). 한도는 *클라우드 호출에만* 차감.
# 로컬은 0원이므로 한도를 소모하지 않는다(budget_krw = 클라우드 잔여 예산).
# ──────────────────────────────────────────────────────────────────────────
DAILY_LIMIT_KRW: Final[dict[str, int]] = {
    "free": 100,  # 사실상 LOCAL 전용. 한도는 클라우드 우발 호출 차단선
    "basic": 500,  # CLOUD_MID 소량, CLOUD_HIGH 불가(guard)
    "premium": 2000,  # CLOUD_MID 일상 + CLOUD_HIGH 제한적
    "gifted": 5000,  # CLOUD_HIGH 포함 폭넓게
}
"""구독별 일일 한도(원). 출처: 03a §E.2."""

# ──────────────────────────────────────────────────────────────────────────
# 실측 비용 산정 상수 — S1 게이트 ②(루프당 비용 실측)의 *단일 근거 단가표*.
# est(사전 추정)·actual(실측) 둘 다 이 단가표를 근거로 삼는다(#465 — 근거는 하나,
# 토큰 출처만 다르다: est=가정 토큰, actual=실측 토큰). 아래 CLOUD_MIN_COST_KRW도
# 이 표에서 유도한다(더는 하드코딩 매직넘버 아님).
# ──────────────────────────────────────────────────────────────────────────
# 키가 **(티어, 좌석)** 인 이유(ARCH-62): 종전 표는 `CostTier`만으로 키가 잡혀 있어
# "CLOUD_MID = Anthropic Sonnet"이라는 *암묵 가정* 위에 서 있었다. 좌석을 옮기면 그 가정만
# 깨지고 표는 그대로라, MID를 DeepSeek으로 옮긴 순간 원가가 **24.4배 과대 계상**된다
# (8.612원 vs 0.354원 — 03c §2.2). 그 값은 `guard_cloud`의 예산 판정 입력이므로 결과는
# **불필요한 LOCAL 강등**이고, 강등된 응답도 200이라 **무증상**이다(CLAUDE.md 「작동 신호
# 없는 알고리즘 부착 금지」가 겨냥하는 형태 그대로).
#
# 좌석 어휘는 `config.CloudSeat` 하나만 쓴다 — 여기서 새 enum을 세우면 좌석 어휘가 둘이
# 되고, 그것이 `ARCH-58`이 상환한 사고다.
CLOUD_TOKEN_PRICE_USD_PER_1M: Final[dict[tuple[CostTier, CloudSeat], tuple[float, float]]] = {
    # (입력, 출력) USD per 1M tokens.
    # ── anthropic 좌석 — 공개 가격(2026-06-23 확인) ──
    (CostTier.CLOUD_MID, "anthropic"): (3.0, 15.0),  # claude-sonnet-4-6 $3/$15
    (CostTier.CLOUD_HIGH, "anthropic"): (5.0, 25.0),  # claude-opus-4-7 $5/$25
    # ── openrouter 좌석 — deepseek/deepseek-v4.1-flash @ deepinfra ──
    # 공급사가 `openrouter_allowed_providers=("deepinfra",)`로 **고정**돼 있으므로 모델의
    # list price($0.15/$0.60)가 아니라 **그 공급사의 실단가**를 쓴다(공급사마다 다르다 —
    # baseten이면 $0.30/$1.20으로 약 2배다. config 주석 실측 2026-09-17~18 · 03c §2.2).
    (CostTier.CLOUD_MID, "openrouter"): (0.20, 0.60),
    # ── deepseek 공식 API 좌석 — 피크 단가(보수적 상한) ──
    # 이 좌석만 시간대 이중 단가다(off-peak $0.15/$0.60 · peak $0.30/$1.20 — 플랫폼 Usage
    # 공지 배너 2026-09-17, 청구서 101req/236,012tok/$0.11로 교차검증). 단일 값을 골라야
    # 한다면 **상한**이다: 이 표는 `guard_cloud`의 예산 판정에도 쓰이고, 그쪽에서 과소
    # 계상은 한도 초과를 낳는다(과대 계상이 낳는 불필요한 강등보다 되돌리기 어렵다).
    (CostTier.CLOUD_MID, "deepseek"): (0.30, 1.20),
    # ── 의도적 미등재 ──
    # (CLOUD_HIGH, "openrouter") — 핀 `deepseek/deepseek-v4-pro` 자체가 **미확인**이다
    #   (config 주석: MID가 v4.1로 정정된 만큼 이 slug도 같은 오류일 수 있다).
    # (CLOUD_HIGH, "deepseek")   — 같은 이유로 단가 근거 없음.
    # 근거 없는 조합에 값을 지어 넣지 않는다 — 조회는 `None`(미측정)으로 떨어지고,
    # 그것이 "0원이었다"와 구별되는 정직한 답이다(CLAUDE.md 「모른다 ≠ 아니다」).
}
"""클라우드 (티어, 좌석) 토큰 가격(USD/1M, 입력·출력). est·actual 공통 단가 근거."""

SERVING_CLOUD_SEAT: Final[CloudSeat] = "anthropic"
"""**학생 대면 서빙**의 클라우드 좌석 — 항상 anthropic.

`settings.cloud_provider` 셀렉터를 읽지 *않는* 것이 의도다: 그 셀렉터는 **저작 경로 전용**
이고(config `cloud_provider` 주석), 학생 대면을 옮기는 것은 코드 변경이 아니라
`G-arch56-availability-trigger`의 Kiki 판정 사안이다. 여기서 셀렉터를 읽으면 저작 경로의
좌석 변경이 학생 트래픽의 예산 판정까지 조용히 바꾼다.

저작 경로는 이 상수를 쓰지 않고 `providers.factory.cloud_provider_name()`이 돌려준 좌석을
`seat=`로 **명시해서** 넘긴다.
"""

USD_TO_KRW: Final[float] = 1540.0
"""환율(원/USD) — 2026-06-23 기준. 라이브 보정 대상."""

# ──────────────────────────────────────────────────────────────────────────
# est(사전 추정) 가정 토큰 상수 — route() 시점엔 실제 토큰이 미상이므로, 사전
# 추정(est_cost_krw·guard_cloud 예산 판정)은 *대표 호출 토큰 수*를 가정해야 한다.
#
# 값의 근거(S1-13 실측 보정·2026-07-14): Phaiakes9 라이브 세션의 Langfuse `l3_routing`
# 실측 p50(input 74·output 358, n=32 — `live_cost_measurement_2026-07.md` 결과표)을
# §H 후속 4 튜닝 절차 그대로 대입했다. 이전 보수 기본(1K+1K)은 실측 대비 입력 13.5배·
# 출력 2.8배 과대 — est가 실측 평균(클라우드 7.08원/콜)과 4배 괴리해 guard_cloud가
# 과도하게 보수적으로 강등하고 있었다. 대입 후 CLOUD_MIN_COST_KRW가 자동 재계산된다
# (단가표 × 가정 토큰의 단일 공식). est/actual 분리는 유지 — actual은 여전히 호출별
# *실측* 토큰으로 계산한다(#465).
#
# 재보정 조건: 표본이 측정 세션 믹스(n=32·스모크·배치 포함)라 대표성 제한 — WH-1 코칭
# 라이브(장문 시스템 프롬프트) 트래픽이 붙으면 p50가 오를 수 있음 → 대표 트래픽 축적 후
# `ops.cost_report`의 suggested_est_*로 재대입(같은 절차·코드 변경은 이 두 상수뿐).
# ──────────────────────────────────────────────────────────────────────────
_EST_ASSUMED_INPUT_TOKENS: Final[int] = 74
"""est 사전 추정용 가정 입력 토큰 — 2026-07-14 라이브 실측 p50(n=32) 보정."""

_EST_ASSUMED_OUTPUT_TOKENS: Final[int] = 358
"""est 사전 추정용 가정 출력 토큰 — 2026-07-14 라이브 실측 p50(n=32) 보정."""

# ──────────────────────────────────────────────────────────────────────────
# 클라우드 1회 호출 추정 비용(원) — 하드코딩이 아니라 *단일 공식*으로 유도:
#   티어 = (가정 입력토큰 × 입력단가 + 가정 출력토큰 × 출력단가)/1M × 환율
# = 가정 토큰 상수(_EST_ASSUMED_*) × 실측 단가표(CLOUD_TOKEN_PRICE_USD_PER_1M,
#   actual_cost_*와 동일 근거) × USD_TO_KRW. 실측 74+358(2026-07-14)이라 ≈8.61(MID)/14.35(HIGH).
# guard_cloud의 "잔여 예산 부족" 판정·est_cost_krw에 쓰인다. 가정 토큰을 튜닝하면
# 이 dict가 자동 재계산된다(위 튜닝 절차 참조·§H 후속 4).
# ──────────────────────────────────────────────────────────────────────────
CLOUD_MIN_COST_KRW: Final[dict[tuple[CostTier, CloudSeat], float]] = {
    key: (_EST_ASSUMED_INPUT_TOKENS * price_in + _EST_ASSUMED_OUTPUT_TOKENS * price_out)
    / 1_000_000
    * USD_TO_KRW
    for key, (price_in, price_out) in CLOUD_TOKEN_PRICE_USD_PER_1M.items()
}
"""클라우드 (티어, 좌석) 1회 호출 추정 비용(원). 가정 토큰 상수 × 실측 단가표 유도.

좌석 축을 타므로 `(CLOUD_MID, "anthropic")`은 8.612원이지만 `(CLOUD_MID, "openrouter")`는
**0.354원**이다 — 종전 표가 이 둘을 같은 값으로 접고 있었다(ARCH-62).
"""


def cloud_token_price(cost: CostTier, seat: CloudSeat | None) -> tuple[float, float] | None:
    """(티어, 좌석) → (입력단가, 출력단가) USD/1M. **모르면 None**.

    None을 돌려주는 두 경우를 호출부가 같게 다뤄도 되는 이유는 둘 다 "산정 불가"이기
    때문이다: ⓐ `seat`가 None(어느 좌석이 응답했는지 모름) ⓑ 그 (티어, 좌석) 조합이 표에
    없음(단가 근거를 확보하지 못함 — 미등재 목록은 표 주석 참조).

    어느 쪽도 **0원으로 접지 않는다**. 접는 순간 "공짜로 돌았다"와 "얼마인지 모른다"가
    리포트에서 같은 글자가 되고, 비용 합계는 조용히 과소 계상된다.
    """
    if seat is None:
        return None
    return CLOUD_TOKEN_PRICE_USD_PER_1M.get((cost, seat))


def actual_cost_usd(
    decision: RoutingDecision,
    usage: Usage,
    *,
    seat: CloudSeat | None = SERVING_CLOUD_SEAT,
) -> float | None:
    """실측 토큰 → 호출 비용(USD) 순수 함수 (S1 게이트 ② 비용 실측).

    - LOCAL(Phaiakes9) → 0.0 (토큰 무관·0원 확정. 좌석과 무관하다).
    - CLOUD_* → (입력토큰×입력단가 + 출력토큰×출력단가)/1M — **좌석별 단가**를 쓴다.
    - CLOUD_*인데 토큰이 미상(None)이면 0.0을 돌려주지만, 이는 '0원 확정'이 아니라
      '산정 불가'다 — 호출부(파이프라인)는 usage 토큰이 None이면 cost를 **None으로
      기록**해 미상과 0원을 구분한다(값을 지어내지 않음, CLAUDE.md).
    - **좌석 또는 단가가 미상이면 `None`** — 0.0과 구별된다(ARCH-62 acceptance ③).

    `seat`의 세 상태가 각각 다른 사실을 말한다:
      · 생략      — 학생 대면 서빙 좌석(`SERVING_CLOUD_SEAT` = anthropic). 기존 호출부의 뜻.
      · 명시       — 저작 경로 등 **실제 응답한 좌석**(`cloud_provider_name()` 값).
      · `None` 명시 — 좌석 미상. 읽을 단가가 없으므로 `None`을 돌려준다.
    """
    cost = _as_cost_tier(decision.cost_tier)
    if cost is CostTier.LOCAL:
        return 0.0
    if usage.input_tokens is None or usage.output_tokens is None:
        return 0.0  # 토큰 미상 — 호출부가 None 기록으로 구분(지어내지 않음)
    price = cloud_token_price(cost, seat)
    if price is None:
        return None  # 좌석 미상 또는 단가 미등재 — 0원으로 접지 않는다
    price_in, price_out = price
    return (usage.input_tokens * price_in + usage.output_tokens * price_out) / 1_000_000


def actual_cost_krw(
    decision: RoutingDecision,
    usage: Usage,
    *,
    seat: CloudSeat | None = SERVING_CLOUD_SEAT,
) -> float | None:
    """실측 토큰 → 호출 비용(원) 순수 함수 — actual_cost_usd × 환율 (S1 게이트 ②).

    추정 `est_cost_krw`(라우터 결정 시점·대표 토큰 가정)와 *명시적으로 분리*된 실측이다.
    LOCAL=0.0. 토큰 미상 시 0.0 — '미상' 표시는 호출부가 usage 토큰 None으로 판단한다.
    좌석·단가 미상이면 `None`(미측정) — 환율을 곱할 값 자체가 없다.
    """
    usd = actual_cost_usd(decision, usage, seat=seat)
    if usd is None:
        return None
    return usd * USD_TO_KRW


CLOUD_LATENCY_MS: Final[dict[CostTier, int]] = {
    # 03a §A.1 표에서 CLOUD는 "가변" — 네트워크·모델 의존. 지연은 *측정값*이라 공개 가격처럼
    # 유도할 수 없다 → placeholder 유지, 라이브 실측 보정(§H 후속 4).
    CostTier.CLOUD_MID: 3000,  # placeholder — §H 후속 4에서 실측 보정
    CostTier.CLOUD_HIGH: 8000,  # placeholder — §H 후속 4에서 실측 보정
}
"""클라우드 티어 예상 지연(ms). 03a §A.1 "가변" — placeholder, §H 후속 4 보정 대상."""

CACHE_KEY_PREFIX: Final[str] = "llm:cache:"
"""캐시 키 네임스페이스 (llm-architect.md ResponseCache 컨벤션)."""


def _as_cost_tier(value: object) -> CostTier:
    """문자열/enum 어느 쪽이 와도 CostTier로 정규화.

    RoutingDecision은 `use_enum_values=True`라 필드가 문자열일 수 있다(03a §G 스키마).
    """
    if isinstance(value, CostTier):
        return value
    return CostTier(value)


def _as_local_tier(value: object) -> LocalModelTier | None:
    """문자열/enum/None 어느 쪽이 와도 LocalModelTier|None으로 정규화."""
    if value is None:
        return None
    if isinstance(value, LocalModelTier):
        return value
    return LocalModelTier(value)


def _as_call_site(value: object) -> CallSite | None:
    """문자열/enum/None 어느 쪽이 와도 CallSite|None으로 정규화."""
    if value is None:
        return None
    if isinstance(value, CallSite):
        return value
    return CallSite(value)


def _as_model_family(value: object) -> ModelFamily | None:
    """문자열/enum/None 어느 쪽이 와도 ModelFamily|None으로 정규화."""
    if value is None:
        return None
    if isinstance(value, ModelFamily):
        return value
    return ModelFamily(value)


def resolve_model(
    local_family: ModelFamily | None,
    local_model: LocalModelTier | None,
) -> str:
    """(패밀리 축3 × 크기 축2) → 실제 로컬 모델 ID 해석 (03a §A.0 매트릭스 lookup).

    호출 직전 LLMClient가 수행하는 lookup을 로직 헬퍼로 노출한다.
      - QUALITY → 패밀리 무관 `qwen3:30b-a3b`(MoE가 양 패밀리 포괄, 03a §A.0).
      - FAST/MID → (패밀리, 크기) 매트릭스 lookup. 이때 패밀리가 None이면 오류
        (불변식 4 위반 — LOCAL+FAST/MID는 패밀리가 반드시 있어야 한다).
    클라우드(local_model None)에는 적용하지 않는다 — 호출 전 cost_tier로 분기.
    """
    local = _as_local_tier(local_model)
    family = _as_model_family(local_family)
    if local is None:
        raise ValueError("resolve_model은 로컬 티어에만 적용된다(local_model이 None)")
    if local is LocalModelTier.QUALITY:
        return QUALITY_MODEL_ID  # 패밀리 무관
    if family is None:
        raise ValueError(
            f"불변식 위반: local_model={local.value}(FAST/MID)는 local_family가 "
            "필요하다 (03a §A.0·§G 불변식 4)"
        )
    return LOCAL_MODEL_MATRIX[(family, local)]


# ──────────────────────────────────────────────────────────────────────────
# 추정기 (estimators)
# ──────────────────────────────────────────────────────────────────────────
def local_latency(local: LocalModelTier) -> int:
    """로컬 티어 예상 지연(ms) — 03a §A.1 벤치 p50."""
    return LOCAL_LATENCY_MS[local]


def cloud_latency(cost: CostTier) -> int:
    """클라우드 티어 예상 지연(ms) — placeholder(03a §A.1 "가변", §H 후속 4)."""
    return CLOUD_LATENCY_MS[cost]


def cloud_min_cost(desired: CostTier, seat: CloudSeat = SERVING_CLOUD_SEAT) -> float:
    """클라우드 1회 최소 추정 비용(원) — guard_cloud 예산 판정용(§D.4).

    값은 실측 단가표에서 유도된 CLOUD_MIN_COST_KRW를 **좌석별로** 참조한다(ARCH-62).
    기본 좌석은 학생 대면 서빙 좌석이다 — `guard_cloud`가 재는 것이 학생의 예산이므로.

    단가 근거가 없는 (티어, 좌석) 조합은 **기본 좌석으로 접지 않고 raise**한다.
    `providers.factory.cloud_model_pins`와 같은 규율이다: 접으면 "새 좌석을 골랐는데 옛
    좌석 단가로 예산을 판정하는" 침묵 실패가 되고, 그것이 이 태스크가 상환하는 사고다.
    예산 판정은 값 없이 진행할 수 없으므로 `None`을 돌려줄 자리가 아니다.
    """
    try:
        return CLOUD_MIN_COST_KRW[(desired, seat)]
    except KeyError:
        raise ValueError(
            f"단가 미등재 조합: 티어={desired} 좌석={seat!r} — "
            "CLOUD_TOKEN_PRICE_USD_PER_1M에 근거 있는 단가를 등재하라 "
            "(근거 없이 값을 지어 넣지 말 것)."
        ) from None


def cloud_cost(req: RoutingRequest, cost: CostTier, seat: CloudSeat = SERVING_CLOUD_SEAT) -> float:
    """클라우드 호출 예상 비용(원) — 가정 토큰 × 실측 단가표 유도(03a §E·§H 후속 4).

    route() 시점엔 실제 토큰이 미상이라 *가정 토큰*(_EST_ASSUMED_*) 기반 사전 추정을
    쓴다(보수적). 실측 단가표(CLOUD_TOKEN_PRICE_USD_PER_1M)를 근거로 삼아 actual_cost_*와
    같은 단가에서 유도되며, 호출별 실측 비용은 actual_cost_krw로 별도 계산한다(#465).
    """
    return cloud_min_cost(cost, seat)


# ──────────────────────────────────────────────────────────────────────────
# 구독·예산 가드 (03a §D.4 guard_cloud)
# ──────────────────────────────────────────────────────────────────────────
def guard_cloud(
    req: RoutingRequest, desired: CostTier, seat: CloudSeat = SERVING_CLOUD_SEAT
) -> CostTier:
    """클라우드 승급 전 구독·예산 가드. 미통과 시 LOCAL/하위 티어로 강등 (03a §D.4).

    규칙(03a §D.4 의사코드 그대로):
      1. free 구독 → 클라우드 금지(LOCAL 강등).
      2. 잔여 예산(budget_krw)이 1회 최소 비용 미만 → LOCAL 강등(+신뢰도 경고).
      3. CLOUD_HIGH 희망인데 basic 구독 → CLOUD_MID로 제한(HIGH 불가).
      그 외 → 희망 티어 그대로.

    규칙 2의 임계값이 **좌석별**이다(ARCH-62). 종전에는 좌석과 무관하게 anthropic 단가를
    써서, 더 싼 좌석에서도 같은 임계로 강등했다 — basic 일 500원 기준 표가 말하는 58회 대
    실제 1,414회(03c §2.2). 그 강등은 응답 200으로 나가므로 학생도 로그도 눈치채지 못한다.
    """
    if req.student_subscription == "free":
        return CostTier.LOCAL  # 무료는 클라우드 금지
    if req.budget_krw < cloud_min_cost(desired, seat):
        return CostTier.LOCAL  # 잔여 예산 부족 → 강등(+신뢰도 경고)
    if desired == CostTier.CLOUD_HIGH and req.student_subscription == "basic":
        return CostTier.CLOUD_MID  # basic은 HIGH 불가 → MID로 제한
    return desired


# ──────────────────────────────────────────────────────────────────────────
# 축1 비즈니스 규칙 (03a §C.1 6규칙) — 데이터 등급(법적) 게이트 적용 *전*의 희망 티어.
#
# 왜 게이트 전 단계를 이름 붙여 노출하는가: "게이트가 실제로 막았는가"(EOS-59 ② 작동 신호)는
# *희망 티어와 최종 티어의 차이*로만 정의된다. 그 차이를 재려면 게이트 전 값이 필요하고,
# 그 값을 관측 도구가 각자 재구현하면 라우터 규칙이 바뀔 때마다 사본이 갈라진다
# (`ops.cost_probe.classify_local_reason`이 겪던 수동 미러 문제). 그래서 한 자리에 둔다.
# ──────────────────────────────────────────────────────────────────────────
def business_cost_tier(req: RoutingRequest) -> CostTier:
    """축1 결정 중 **비즈니스 축(구독·예산)** 만 — LOCAL / CLOUD_MID / CLOUD_HIGH (03a §C.1).

    평가 순서 = 위에서 아래, 첫 매치 확정. 규칙 5(에스컬레이션 트리거)는 *생성 결과 신뢰
    미달* 시점에 발동하므로 단발 route() 입력만으로는 평가하지 않는다(트리거 감지는 파이프라인
    책임, §D.2). next_tier()로 분리.

    ⚠️ 이 함수의 결과는 **희망 티어**다. 데이터 등급(법적) 게이트를 아직 통과하지 않았으므로
    실제 라우팅 티어로 쓰면 안 된다 — 최종 티어는 `Router._decide_cost_tier`가 낸다.
    """
    # 규칙 1: 쿼터 소진 → 비용 0원 강제 (03a §E.2 budget_krw<=0 = "오늘은 로컬만")
    if req.budget_krw <= 0:
        return CostTier.LOCAL
    # 규칙 2: 무료 사용자 항상 로컬
    if req.student_subscription == "free":
        return CostTier.LOCAL
    # 규칙 3: 킬러·증명 → CLOUD_HIGH (단 구독·예산 가드 통과 시)
    if req.difficulty == "killer" or req.task_type == "prove":
        return guard_cloud(req, CostTier.CLOUD_HIGH)
    # 규칙 4: 어려운 진단(premium↑) → CLOUD_MID
    if req.requires_reasoning and req.student_subscription in ("premium", "gifted"):
        return guard_cloud(req, CostTier.CLOUD_MID)
    # 규칙 6: 그 외 기본 LOCAL (목표 분포 80%)
    return CostTier.LOCAL


# ──────────────────────────────────────────────────────────────────────────
# 캐시 키 (03a §F.1 — 세 축 {cost_tier}:{local_family}:{local_model} 포함)
# ──────────────────────────────────────────────────────────────────────────
def cache_key(
    prompt: str,
    system: str,
    cost_tier: CostTier,
    local_family: ModelFamily | None,
    local_model: LocalModelTier | None,
    *,
    image_digest: str | None = None,
) -> str:
    """프롬프트+시스템+(세 축 합성 식별자)[+이미지 다이제스트] 기반 캐시 키 (03a §F.1).

    같은 프롬프트라도 *어느 티어·패밀리가 생성했는지*가 캐시 정체성의 일부다 —
    FAST 응답과 QUALITY 응답을, 그리고 MATH(qwen2-math) 응답과 GENERAL(qwen2.5)
    응답을 섞지 않는다(패밀리가 다르면 출력 특성·신뢰도가 다르므로, 03a §F.1).
    예: "local:general:fast"(qwen2.5:3b), "local:math:mid"(qwen2-math:7b),
    "cloud_mid:-:-". 학생 ID는 키에 포함하지 않는다(개인화는 컨텍스트로).

    `image_digest`(멀티모달 입력 이미지의 해시)가 주어지면 키에 합성한다 — 같은
    프롬프트라도 *이미지가 다르면 다른 캐시*(다른 크롭=다른 수식). **None(텍스트
    호출)이면 키가 기존과 100% 동일**(하위호환·텍스트 캐시 무영향).
    """
    cost = _as_cost_tier(cost_tier)
    family = _as_model_family(local_family)
    local = _as_local_tier(local_model)
    family_id = family.value if family is not None else "-"
    local_id = local.value if local is not None else "-"
    model_id = f"{cost.value}:{family_id}:{local_id}"
    content = f"{system}|||{prompt}|||{model_id}"
    if image_digest is not None:
        content = f"{content}|||img:{image_digest}"  # 이미지 있을 때만 부가(텍스트 키 불변)
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return f"{CACHE_KEY_PREFIX}{digest}"


def cache_key_for(
    prompt: str, system: str, decision: RoutingDecision, *, image_digest: str | None = None
) -> str:
    """RoutingDecision으로부터 캐시 키 생성 — cache_key()의 편의 래퍼(이미지 다이제스트 통과)."""
    return cache_key(
        prompt,
        system,
        decision.cost_tier,
        decision.local_family,
        decision.local_model,
        image_digest=image_digest,
    )


# ──────────────────────────────────────────────────────────────────────────
# Langfuse 태그 (03a §F.2 — dict만 생성, 실제 전송 X)
# ──────────────────────────────────────────────────────────────────────────
def langfuse_fields(
    decision: RoutingDecision,
    *,
    cache_hit: bool = False,
    escalated_from: CostTier | LocalModelTier | str | None = None,
    call_site: CallSite | str | None = None,
    student_id_hash: str | None = None,
    validation_signal: str | None = None,
    usage: Usage | None = None,
    cost_krw: float | None = None,
    content_source: str | None = None,
    training_allowed: bool | None = None,
) -> dict[str, object]:
    """Langfuse 기록 필드 dict 생성 (03a §F.2 표).

    범위 메모: *dict만* 반환한다. 실제 Langfuse 전송은 TraceSink 구현의 책임이다.
    추정치는 est_*(라우터 결정 시점), 실측치는 `usage`/`cost_krw` 인자로 받아
    `input_tokens`/`output_tokens`/`latency_ms`/`cost_krw` 키로 노출한다(S1 게이트 ② —
    추정 vs 실측 구분 유지). 실측을 모르는 호출부(캐시 히트·비동기 enqueue·미계측)는
    인자를 생략하면 실측 키가 None으로 남는다(지어내지 않음).

    `validation_signal`은 런타임 shadow 검증(L3 결정론 도구) 결과다 — None=통과(또는
    미검증), 문자열=거짓 수치 관계 등 *환각 신호 사유*. 비차단 관측 전용이며 반환
    텍스트·캐시 동작에 영향을 주지 않는다(학생 노출 경계는 L4/L5 책임, CLAUDE.md).

    `training_allowed`는 AI 모델 학습/개선에 사용자 데이터를 사용할 수 있는지의 동의
    상태다(EOS §48). `None`이면 미측정. 관측용이며 provider 동작을 직접 제어하지 않는다.
    """
    cost = _as_cost_tier(decision.cost_tier)
    family = _as_model_family(decision.local_family)
    local = _as_local_tier(decision.local_model)
    site = _as_call_site(call_site)

    escalated: str | None
    if escalated_from is None:
        escalated = None
    elif isinstance(escalated_from, (CostTier, LocalModelTier)):
        escalated = escalated_from.value
    else:
        escalated = escalated_from

    return {
        "cost_tier": cost.value,  # 80/18/2 분포 모니터링
        "local_family": family.value if family is not None else None,  # 패밀리별 분포
        "local_model": local.value if local is not None else None,  # 로컬 내부 분포
        "mode": decision.mode,  # SLA 평가 분리(동기만 게이트 대상)
        "est_latency_ms": decision.est_latency_ms,  # 추정 지연(실측은 latency_ms)
        "est_cost_krw": decision.est_cost_krw,  # 추정 비용(실측은 cost_krw)
        # ── 실측 (S1 게이트 ② — est_*와 분리된 actual, 미계측이면 None) ──
        "input_tokens": usage.input_tokens if usage is not None else None,  # 실측 입력 토큰
        "output_tokens": usage.output_tokens if usage is not None else None,  # 실측 출력 토큰
        "latency_ms": usage.latency_ms if usage is not None else None,  # 실측 지연(ms)
        "cost_krw": cost_krw,  # 실측 비용(원) — 로컬 0.0·클라우드 토큰 산정·미상 None
        "call_site": site.value if site is not None else None,  # 호출지점별 분포
        "cache_hit": cache_hit,  # 캐싱 적중률 KPI
        "escalated_from": escalated,  # 에스컬레이션 빈도 분석
        "student_id_hash": student_id_hash,  # 직접 ID 금지(해시만)
        "reason": decision.reason,  # 결정 근거
        "validation_signal": validation_signal,  # 런타임 shadow 검증 환각 신호(비차단)
        # AI 학습 동의 상태(EOS §48) — 관측용, provider 제어는 별도 계약/설정.
        "training_allowed": training_allowed,
        # ── 데이터 등급 게이트(EOS-59 ②) — "작동한 비율"의 원자료 ──
        # 호출부 인자가 아니라 *결정에서 직접* 읽는다: 새 인자를 만들면 17개 호출부가 각자
        # 채워야 하고 하나만 빠뜨려도 집계가 조용히 새기 때문이다. 결정이 이미 사실을
        # 들고 있으므로 기존 좌석(langfuse_fields)에 그대로 얹는다.
        "data_export_blocked": decision.data_export_blocked,  # 게이트가 실제로 막은 건수
        "data_export_reason": decision.data_export_reason,  # 등급 판정 분포(분모·미판정 None)
        # 공급 경로(03c 2층 캐시) — prompt_cache/generate는 파이프라인이 cache_hit에서 유도하고,
        # dsl_render는 라우팅을 타지 않아 상위(l4 공급 경로)가 자기 이벤트로 기록한다.
        "content_source": content_source,
    }


# ──────────────────────────────────────────────────────────────────────────
# 에스컬레이션 사슬 (03a §D.1 단방향 승급) — 로직 수준 헬퍼
# ──────────────────────────────────────────────────────────────────────────
ESCALATION_CHAIN: Final[list[tuple[CostTier, LocalModelTier | None]]] = [
    (CostTier.LOCAL, LocalModelTier.FAST),
    (CostTier.LOCAL, LocalModelTier.MID),
    (CostTier.LOCAL, LocalModelTier.QUALITY),
    (CostTier.CLOUD_MID, None),
    (CostTier.CLOUD_HIGH, None),
]
"""단방향 승급 사슬 (03a §D.1): FAST→MID→QUALITY→CLOUD_MID→CLOUD_HIGH.

로컬 3단계를 먼저 올리고(비용 0원), 로컬 천장(QUALITY)에서도 미달일 때만
CLOUD로 넘어간다. CLOUD 승급은 항상 guard_cloud를 통과해야 한다(§D.1).
"""


def next_tier(
    cost_tier: CostTier,
    local_model: LocalModelTier | None,
    *,
    data_licenses: Iterable[object],
) -> tuple[CostTier, LocalModelTier | None] | None:
    """현재 (축1, 축2)에서 한 단계 승급한 (축1, 축2) 반환 (03a §D.1·§D.2).

    에스컬레이션 트리거(자기 일관성 불일치·신뢰도 미달 등, §D.2) 발동 시
    "다음 티어 1단계"를 결정하는 로직 수준 헬퍼. 천장(CLOUD_HIGH)이면 None.
    실제 트리거 감지(PRM confidence·다수결 등)는 생성 파이프라인의 책임이며
    M1.2 범위 밖이다 — 본 함수는 *사슬 계산*만 한다.

    ## `data_licenses`가 **필수 인자**인 이유 (EOS-59 · codex P1 수용)

    `route()`가 데이터 등급 게이트로 클라우드를 막아 LOCAL로 강등시켜도, 이후 신뢰도
    재시도가 이 함수를 부르면 사슬이 `LOCAL/QUALITY → CLOUD_MID`로 올라간다. 그 순간
    **막으려던 국외반출이 재시도 경로로 되살아난다**(AIHub 4조건 ② 위반). 사슬 계산이
    요청을 안 보는 순수 함수라는 사실이 곧 그 구멍이었다.

    선택 인자 + 관대한 기본값으로 두지 않는다 — 그러면 부르는 쪽이 빠뜨릴 때 조용히
    fail-open이 되고, 그건 이 게이트가 없애려던 상태 그 자체다. **필수 키워드**로 둬서
    빠뜨리면 `TypeError`가 나게 한다(침묵 대신 즉시 실패). 지금이 필수화의 최적기다 —
    프로덕션 호출부가 아직 0건이라(`ops/cost_probe`가 "이 프로브는 next_tier를 부르지
    않는다"고 자인) 파이프라인이 배선되기 *전에* 계약을 굳힐 수 있다.

    반출이 막힌 자료면 승급은 **국내(LOCAL) 사슬 안에서만** 일어나고, 로컬 천장
    (`QUALITY`)에 닿으면 `None`(더 올릴 곳 없음)을 돌려준다 — 클라우드로 넘어가지 않는다.
    이것이 `guard_data_export`의 단방향성을 *재시도 축*까지 연장한 형태다.
    """
    cost = _as_cost_tier(cost_tier)
    local = _as_local_tier(local_model)
    current = (cost, local)
    try:
        idx = ESCALATION_CHAIN.index(current)
    except ValueError:
        return None
    if idx + 1 >= len(ESCALATION_CHAIN):
        return None  # 천장
    candidate = ESCALATION_CHAIN[idx + 1]
    # 법적 축 재확인 — 사슬의 다음 칸이 국외 티어면 등급을 다시 본다. 비즈니스 가드
    # (guard_cloud)와 합치지 않는 이유는 `data_export_policy` 모듈 docstring 참조.
    if candidate[0] in OFFSHORE_TIERS and export_judgment(data_licenses).blocks_offshore:
        return None  # 국내 천장 — 재시도가 게이트를 우회하지 못한다
    return candidate


# ──────────────────────────────────────────────────────────────────────────
# 라우터 본체
# ──────────────────────────────────────────────────────────────────────────
class Router:
    """비용·지연·품질 최적화 라우팅 (03a §C).

    축1(C.1, 80/18/2) → [LOCAL이면] 축3(C.0, MATH/GENERAL) → 축2(C.2, FAST/MID/
    QUALITY)를 *순차* 평가한다. 패밀리(축3)를 크기(축2)보다 먼저 정한다 — 같은
    크기 등급이라도 패밀리가 가리키는 실제 모델이 다르기 때문(03a §0.2·§C).
    `route()`는 *어디서 생성할지*만 정한다. 생성된 응답은 03 문서 환각 방어
    파이프라인을 *반드시* 통과해야 학생에게 노출된다(03a §C.4 메모,
    CLAUDE.md 절대 금기 "LLM 응답을 검증 없이 학생에게 제공 금지").
    """

    def route(self, req: RoutingRequest) -> RoutingDecision:
        """라우팅 결정 — 축1(C.1) → [LOCAL이면] 축3(C.0) → 축2(C.2) (03a §C.4)."""
        # 멀티모달(VL) 단축 경로 — 이미지 인식은 항상 LOCAL Qwen3-VL(VISION 패밀리)·FAST·동기.
        # 수학/일반 텍스트 패밀리·크기 규칙을 건너뛴다(이미지 인식은 직교 축, 03a 확장).
        # 미성년자 프라이버시·로컬-우선(CLAUDE.md 2026-05-28)이라 클라우드 비전 승급은 없다.
        judgment = export_judgment_for(req)  # 등급 판정은 경로와 무관하게 항상 남긴다
        if req.requires_vision:
            return RoutingDecision(
                cost_tier=CostTier.LOCAL,
                local_family=ModelFamily.VISION,
                local_model=LocalModelTier.FAST,
                mode="sync",
                reason="local/vision/fast (multimodal)",
                est_latency_ms=local_latency(LocalModelTier.FAST),
                est_cost_krw=0.0,
                # 비전은 애초에 LOCAL 직행이라 게이트가 막을 것이 없다 → blocked=False.
                # 사유는 그대로 남긴다(등급 분포 관측 — "게이트가 안 걸렸다"와 "자료가
                # 반출 가능했다"는 다른 사실이다).
                data_export_blocked=False,
                data_export_reason=judgment.reason,
                data_licenses=req.data_licenses,  # 관할 축(ARCH-49)이 읽는 등급 승계
            )
        desired = business_cost_tier(req)  # 게이트 전 희망 티어(작동 신호의 분모)
        cost_tier = guard_data_export(desired, req.data_licenses)  # 법적 축 — 독립 적용
        # "게이트가 *실제로* 막았는가" = 희망과 최종이 갈렸는가. 정상 응답 200은 게이트가
        # 일했다는 증거가 아니다(CLAUDE.md "작동 신호 없는 알고리즘 부착 금지").
        export_blocked = cost_tier != desired

        # CLOUD 경로면 축3·축2 없음 — 불변식 2·4(03a §G)
        if cost_tier != CostTier.LOCAL:
            return RoutingDecision(
                cost_tier=cost_tier,
                local_family=None,
                local_model=None,
                mode="sync",
                reason="cloud escalation",
                est_latency_ms=cloud_latency(cost_tier),
                est_cost_krw=cloud_cost(req, cost_tier),
                data_export_blocked=False,  # 여기 도달했다는 것 자체가 게이트 통과다
                data_export_reason=judgment.reason,
                data_licenses=req.data_licenses,  # 관할 축(ARCH-49)이 읽는 등급 승계
            )

        # LOCAL 경로 → 축3(패밀리) 먼저, 그다음 축2(크기)
        family = self._decide_family(req)
        local_model, mode = self._decide_local_tier(req)

        # QUALITY(MoE)는 패밀리 무관 → local_family=None (불변식 4, 03a §A.0).
        # 단 reason에는 결정된 패밀리를 남겨 추적성을 유지한다(QUALITY로 합류 전 의도).
        family_applicable = local_model in (LocalModelTier.FAST, LocalModelTier.MID)
        decision_family = family if family_applicable else None
        # 법적 게이트가 강등시킨 결정은 근거 문자열에도 남긴다 — Langfuse `reason`만 보는
        # 대시보드에서도 "왜 로컬인가"가 비용 판단으로 오독되지 않게 한다(구조 신호는
        # data_export_blocked, 사람이 읽는 신호는 reason — 둘 다 둔다).
        base_reason = f"local/{family.value}/{local_model.value}"
        reason = (
            f"{base_reason} (data-export gate: {judgment.reason})"
            if export_blocked
            else base_reason
        )
        return RoutingDecision(
            cost_tier=CostTier.LOCAL,
            local_family=decision_family,
            local_model=local_model,
            mode=mode,
            reason=reason,
            est_latency_ms=local_latency(local_model),
            est_cost_krw=0.0,  # 로컬은 0원
            data_export_blocked=export_blocked,
            data_export_reason=judgment.reason,
            data_licenses=req.data_licenses,  # 관할 축(ARCH-49)이 읽는 등급 승계
        )

    # ── 축1: 비용·위치 (03a §C.1 결정표 6규칙) + 데이터 등급 게이트(EOS-59) ──
    def _decide_cost_tier(self, req: RoutingRequest) -> CostTier:
        """축1 최종 결정 — 비즈니스 축(§C.1 6규칙) 통과 후 **법적 축**을 독립 적용한다.

        두 축을 한 함수에 합치지 않는 이유는 `l3.data_export_policy` 모듈 docstring에 있다
        (요약: 구독·예산은 우리가 언제든 완화할 수 있는 비즈니스 규칙이고, 데이터 등급은
        권리자와의 별도합의 없이는 못 푸는 법적 규칙이다 — 합치면 요금제 변경이 법적
        게이트까지 조용히 여는 경로가 된다. `l6/_shared`의 `is_exposable`↔`is_review_cleared`
        분리와 같은 규율).
        """
        desired = business_cost_tier(req)  # ① 비즈니스 축(구독·예산)
        return guard_data_export(desired, req.data_licenses)  # ② 법적 축 — 독립 호출·강등 전용

    # ── 축3: 로컬 모델 패밀리 (03a §C.0 결정표 — 크기보다 먼저) ──
    def _decide_family(self, req: RoutingRequest) -> ModelFamily:
        """축3 결정 — MATH / GENERAL (03a §C.0).

        축1=LOCAL로 확정된 요청만 평가. 태스크 *유형*(수학 vs NLP)으로 패밀리를
        가른다(크기·SLA가 아니라, §0.2 규칙2). "NLP임이 분명할 때 GENERAL,
        그 외 MATH(안전 기본값)" — WhyMath 호출 다수가 수학 계산이고, NLP를 수학
        모델로 보내면 7b조차 0%였으므로 NLP 식별 규칙을 *넓게* 잡는다(§C.0 메모).

        QUALITY로 합류할 요청도 패밀리를 정해두지만, route()에서 QUALITY면
        local_family는 None으로 비운다(MoE가 양 패밀리 포괄, §A.0 불변식 4).
        """
        call_site = _as_call_site(req.call_site)
        # 규칙 1: NLP 호출지점 ①③④ → GENERAL (②=depth는 MATH)
        # 규칙 3: NLP 계열 task_type(추출·매칭·정규화·분류) → GENERAL
        if call_site in NLP_CALL_SITES or req.task_type in NLP_TASK_TYPES:
            return ModelFamily.GENERAL
        # 규칙 2·4·5: 그 외(②깊이추론·계산·풀이·증명·산술·미상) → MATH(안전 기본값)
        return ModelFamily.MATH

    # ── 축2: 로컬 모델 크기 (03a §C.2 결정표 9규칙) ──
    def _decide_local_tier(self, req: RoutingRequest) -> tuple[LocalModelTier, str]:
        """축2 결정 — FAST / MID / QUALITY + 모드 (03a §C.2 9규칙).

        축1=LOCAL·축3(패밀리) 결정 후 평가. 평가 순서 = 위에서 아래, 첫 매치 확정.
        규칙 3·4는 *GENERAL 호출지점 안에서도* 크기를 가른다 — match=FAST(3b=100%),
        extract/translate=MID(3b 하한 미달, 2026-05-20 실측). call_site가 호출지점을
        식별하므로 family 인자 없이 call_site로 분기한다.
        """
        call_site = _as_call_site(req.call_site)

        # 규칙 1: ⑤ 자기검증 → QUALITY 비동기 (패밀리 무관)
        if call_site == CallSite.SELF_VERIFY:
            return LocalModelTier.QUALITY, "async"
        # 규칙 2: 비동기 + (verify/generate or hard/killer) → QUALITY (MoE 비동기 전용)
        if (not req.sync) and (
            req.task_type in ("verify", "generate") or req.difficulty in ("hard", "killer")
        ):
            return LocalModelTier.QUALITY, "async"
        # 규칙 3: ④ match → FAST (GENERAL match는 3b=100% → FAST로 충분, 2026-05-20)
        if call_site == CallSite.CONCEPT_ID_MATCH:
            return LocalModelTier.FAST, "sync"
        # 규칙 4: ① extract·③ translate → MID (GENERAL이나 3b 하한 미달 → 7b 필요)
        if call_site in (CallSite.CONCEPT_EXTRACT, CallSite.TRANSLATE_NORMALIZE):
            return LocalModelTier.MID, "sync"
        # 규칙 5: 동기 + SLA<2s → FAST (FAST만 게이트 통과, p50 1초)
        if req.sync and req.max_latency_ms < SLA_GATE_MS:
            return LocalModelTier.FAST, "sync"
        # 규칙 6: 즉답·분류·경량 매칭 → FAST
        if (
            req.conversation_phase in ("greeting", "followup")
            or req.task_type in ("match", "classify")
            or (req.difficulty == "easy" and not req.requires_reasoning)
        ):
            return LocalModelTier.FAST, "sync"
        # 규칙 7: 정밀 풀이·메인 대화(추론 필요) → MID (p50 4초 허용)
        if req.task_type in ("explain", "coach", "diagnose") and req.requires_reasoning:
            return LocalModelTier.MID, "sync"
        # 규칙 8: 동기인데 추론 필요(medium/hard) → MID
        if req.difficulty in ("medium", "hard") and req.sync:
            return LocalModelTier.MID, "sync"
        # 규칙 9: 안전 기본값 → FAST (가장 빠르고 SLA 충족)
        return LocalModelTier.FAST, "sync"
