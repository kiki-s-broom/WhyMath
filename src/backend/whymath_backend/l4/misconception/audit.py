"""오개념 카탈로그 *정의* 충족도 감사(audit) — WH-1 0단계 ③(설계 §8.4).

설계안(`docs/architecture/04a_wh1_tutoring_harness.md`) §8.4 **0단계 ③**: 오개념 카탈로그가
진단에 충분한 **신호·반례·명제·정규식**을 갖췄는지 순수 집계해 카탈로그 품질을 커버리지 맵에
올린다. 본 모듈은 그 산출물의 구조(리포트)를 제공한다.

**범위 정직성(False-attribute 금기·CLAUDE.md)**: 본 감사는 *오직 카탈로그 정의 충족도*만
측정한다 — 각 `Misconception`이 `signals`·`regex_signals`·`counterexample`·`canonical_statement`를
얼마나 채웠는지(카탈로그 자체의 정적 품질). 이는 *학생 풀이 코퍼스* 충족과 **다른 축**이다.

설계 §8.4 L193의 "오개념 항목당 *예시 오답 5개* 임베딩 적재"는 카탈로그 정의가 아니라
*학생 풀이 코퍼스*(LIVE — `learning_events`/`diagnose` 결과)이며, 그 충족률은 별도 DB 쿼리가
필요한 **후속**이다(본 모듈 범위 밖). 따라서 본 리포트의 `saturation_rate`·`regex_coverage_rate`
등은 "카탈로그가 정의 측면에서 진단에 쓸 신호를 갖췄는가"이지 "학생 예시가 충분히 적재됐는가"가
*아니다* — 후자를 전자인 척 표기하지 않는다.

**후속(범위 밖·미구현)**:
  - 학생 풀이 코퍼스 예시 오답 충족률(§8.4 L193·LIVE·`learning_events`/`diagnose` DB 쿼리).
  - `SurrogateMetrics` 통합(정적·전역 지표라 per-user LIVE 지표와 의미 충돌 회피 — 독립 리포트
    유지·결선 안 함).
  - 0단계 ②④⑤(설계 §8.4의 나머지 0단계 항목).

**순수·결정론·DB 0**: `CATALOG`(불변·frozen 30종)를 *읽기만* 한다. 새 적재·마이그레이션·LLM·
임베딩 호출 0. 인자 없이 같은 카탈로그에 같은 리포트를 낸다(재현·회귀). `diagnose`·`match_gate`·
하네스를 재구현하지 않고 카탈로그 정의만 집계한다.
"""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, ConfigDict, Field

from whymath_backend.l4.misconception.catalog import BODY_CATALOG
from whymath_backend.l4.misconception.models import Misconception, MisconceptionDomain

__all__ = [
    "CatalogAuditItem",
    "CatalogAuditReport",
    "DomainAuditSummary",
    "audit_catalog_coverage",
]


# 권장 신호 수 — 단독 substring 토큰 1개는 *우연 매칭* 위험이 크다(예: '0'·'벡터' 단편이
# 무관한 풀이에 등장). 카탈로그 작성 지침은 *공출현 AND 2개 이상*을 권장(이중 신호로 거짓
# 양성 억제)하므로, 본 감사는 신호 포화의 하한을 2로 둔다. (현 카탈로그 최소 신호 수는 그
# 자체로 1 이상이며, 본 임계는 *권장치* 충족 여부를 잰다 — 강제가 아니라 품질 신호.)
_MIN_SIGNALS = 2


class CatalogAuditItem(BaseModel):
    """오개념 1건의 카탈로그 정의 충족 판정(frozen·순수 데이터).

    각 필드는 *카탈로그 정의*가 채워졌는지의 정적 측정이다(학생 코퍼스 아님 — 모듈 docstring
    참조). `is_signal_saturated`는 진단에 쓸 신호가 *권장 수준*(substring 2개 이상 + 정규식 1개
    이상)으로 갖춰졌는지의 종합 판정이다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    misconception_id: str = Field(
        description="오개념 정본 ID(`Misconception.id`) — 역참조·정렬 키.",
    )
    domain: MisconceptionDomain = Field(
        description="오개념 영역(`Misconception.domain`) — 도메인별 집계 키.",
    )
    signals_count: int = Field(
        description="substring `signals` 토큰 수(공출현 AND 신호).",
    )
    regex_signals_count: int = Field(
        description="보조 `regex_signals` 정규식 수(수치 대입 탐지 OR 경로).",
    )
    has_counterexample: bool = Field(
        description="반례(`counterexample`)가 비어있지 않은가(strip 후) — 패턴 1 어셈블리 입력.",
    )
    has_canonical_statement: bool = Field(
        description="학생 가정 진술(`canonical_statement`)이 비어있지 않은가(strip 후).",
    )
    is_signal_saturated: bool = Field(
        description=(
            "신호 포화 판정 = (signals_count >= 2 AND regex_signals_count >= 1). substring "
            "이중 신호 + 수치 정규식 보조 경로를 모두 갖춘 경우만 포화로 본다(권장 품질)."
        ),
    )


class DomainAuditSummary(BaseModel):
    """도메인 1개의 카탈로그 정의 충족 집계(frozen).

    `n`=도메인 항목 수·`n_saturated`=포화 항목 수·`n_signals_ge_min`=신호 권장치(>=2) 충족 수·
    `saturation_rate`=n_saturated/n(n=0이면 0.0·0 나눗셈 회피).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    domain: MisconceptionDomain = Field(description="집계 대상 영역.")
    n: int = Field(description="이 영역의 오개념 항목 수.")
    n_saturated: int = Field(description="신호 포화(is_signal_saturated) 항목 수.")
    n_signals_ge_min: int = Field(
        description=f"substring 신호 권장치(>= {_MIN_SIGNALS}) 충족 항목 수.",
    )
    saturation_rate: float = Field(
        description="포화율 = n_saturated/n. n=0이면 0.0.",
    )


class CatalogAuditReport(BaseModel):
    """오개념 카탈로그 정의 충족도 감사 리포트(frozen·0단계 ③ 산출물).

    `items`는 misconception_id 정렬·`by_domain`은 domain 값 정렬이다. 각 비율(rate)은 [0,1]·
    total=0이면 0.0(0 나눗셈 회피·정직한 빈 집계). **정직 스코프**: 본 리포트는 *카탈로그 정의*
    충족도이지 *학생 예시 코퍼스* 충족률이 아니다(모듈 docstring — 후자는 LIVE·후속).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    total: int = Field(
        description=(
            "감사 대상 오개념 수(`len(BODY_CATALOG)`) — 본문 채널 항목만이다. 선지 역추적 전용 "
            "항목(P3-61 `choice_trace_only`)은 신호가 정의상 0이라 신호 포화 비율의 분모를 "
            "희석하므로 제외한다(`len(CATALOG)`보다 작을 수 있다)."
        )
    )
    items: list[CatalogAuditItem] = Field(
        description="오개념별 정의 충족 판정(misconception_id 오름차순 정렬).",
    )
    canonical_rate: float = Field(
        description="canonical_statement 보유 비율(채워진 수/total). total=0이면 0.0.",
    )
    counterexample_rate: float = Field(
        description="counterexample 보유 비율(채워진 수/total). total=0이면 0.0.",
    )
    signals_ge_min_rate: float = Field(
        description=(f"substring 신호 권장치(>= {_MIN_SIGNALS}) 충족 비율. total=0이면 0.0."),
    )
    regex_coverage_rate: float = Field(
        description="regex_signals 1개 이상 보유 비율. total=0이면 0.0.",
    )
    saturation_rate: float = Field(
        description="신호 포화(is_signal_saturated) 비율. total=0이면 0.0.",
    )
    by_domain: list[DomainAuditSummary] = Field(
        description="도메인별 집계(domain 값 오름차순 정렬).",
    )


def _audit_item(m: Misconception) -> CatalogAuditItem:
    """오개념 1건의 카탈로그 정의 충족을 판정한다(순수·입력 비변형).

    문자열 필드는 `strip()` 후 비어있지 않음을 보유로 본다(공백만 채운 위장 방지). 신호 포화는
    substring 권장치(>= _MIN_SIGNALS)와 정규식 1개 이상을 모두 만족할 때만 True.
    """
    signals_count = len(m.signals)
    regex_signals_count = len(m.regex_signals)
    is_saturated = signals_count >= _MIN_SIGNALS and regex_signals_count >= 1
    return CatalogAuditItem(
        misconception_id=m.id,
        domain=m.domain,
        signals_count=signals_count,
        regex_signals_count=regex_signals_count,
        has_counterexample=bool(m.counterexample.strip()),
        has_canonical_statement=bool(m.canonical_statement.strip()),
        is_signal_saturated=is_saturated,
    )


def _summarize_domain(
    domain: MisconceptionDomain, domain_items: list[CatalogAuditItem]
) -> DomainAuditSummary:
    """한 도메인의 항목 판정들을 집계한다(n=0 가드·포화율 0.0)."""
    n = len(domain_items)
    n_saturated = sum(1 for it in domain_items if it.is_signal_saturated)
    n_signals_ge_min = sum(1 for it in domain_items if it.signals_count >= _MIN_SIGNALS)
    saturation_rate = n_saturated / n if n else 0.0
    return DomainAuditSummary(
        domain=domain,
        n=n,
        n_saturated=n_saturated,
        n_signals_ge_min=n_signals_ge_min,
        saturation_rate=saturation_rate,
    )


def audit_catalog_coverage() -> CatalogAuditReport:
    """오개념 카탈로그 정의 충족도를 집계한다 — 순수·인자 0·DB 0·결정론(설계 §8.4 0단계 ③).

    `BODY_CATALOG`(`CATALOG`에서 선지 역추적 전용을 뺀 본문 채널 항목)를 순회해 항목별 정의
    충족(`_audit_item`)을 판정하고, 전체 비율과
    도메인별 집계를 낸다. 입력(카탈로그)을 변형하지 않으며 같은 카탈로그에 같은 리포트를 낸다.

    집계 규약:
      - `items`: misconception_id 오름차순 정렬(안정적 리포트·디프 가독).
      - 비율(canonical/counterexample/signals_ge_min/regex_coverage/saturation): 충족 수/total.
        total=0이면 모두 0.0(0 나눗셈 회피·정직한 빈 집계).
      - `by_domain`: 카탈로그에 *실제 등장한* 도메인만, domain 값 오름차순 정렬. 각 도메인 n의
        합은 total과 같다.

    **정직성(범위 정직)**: 측정 대상은 *카탈로그 정의* 충족도(정적 품질)이지 *학생 예시 코퍼스*
    충족률(§8.4 L193·LIVE)이 아니다(모듈 docstring). 후자는 별도 DB 쿼리가 필요한 후속이며 본
    함수는 카탈로그 불변 읽기만 한다. `SurrogateMetrics`와 결선하지 않는다(독립 리포트).
    """
    # 1) 항목별 판정(id 정렬) — 입력 비변형(정렬은 새 리스트).
    items = sorted(
        (_audit_item(m) for m in BODY_CATALOG),
        key=lambda it: it.misconception_id,
    )
    total = len(items)

    # 2) 전체 비율 — total=0 가드.
    if total:
        canonical_rate = sum(1 for it in items if it.has_canonical_statement) / total
        counterexample_rate = sum(1 for it in items if it.has_counterexample) / total
        signals_ge_min_rate = sum(1 for it in items if it.signals_count >= _MIN_SIGNALS) / total
        regex_coverage_rate = sum(1 for it in items if it.regex_signals_count >= 1) / total
        saturation_rate = sum(1 for it in items if it.is_signal_saturated) / total
    else:
        canonical_rate = counterexample_rate = signals_ge_min_rate = 0.0
        regex_coverage_rate = saturation_rate = 0.0

    # 3) 도메인별 집계 — 카탈로그에 등장한 도메인만·domain 값 정렬.
    domain_counter: Counter[MisconceptionDomain] = Counter(it.domain for it in items)
    by_domain = [
        _summarize_domain(
            domain,
            [it for it in items if it.domain == domain],
        )
        for domain in sorted(domain_counter)
    ]

    return CatalogAuditReport(
        total=total,
        items=items,
        canonical_rate=canonical_rate,
        counterexample_rate=counterexample_rate,
        signals_ge_min_rate=signals_ge_min_rate,
        regex_coverage_rate=regex_coverage_rate,
        saturation_rate=saturation_rate,
        by_domain=by_domain,
    )
