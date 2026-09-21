"""12월 검증 결론 판정기 — Hard Gate F-Ⅰ~F-Ⅴ + KPI 12종 스코어카드 (EOS-61).

`docs/standards/eos_verification_design_v1.md`(G0 동결본)의 §5 실패정의와 §6 KPI는
**이미 동결돼 있다**. 없는 것은 그 기준을 읽어 판정을 뱉는 **실행기**였다. 이 모듈이 그것이다.

BI 대시보드가 아니라 CLI다. 주간 7지표의 주기 집계는 `OPS-56`이 별도 좌석이고, 이쪽은
**12/31 최종 판정**(G5)이다.

────────────────────────────────────────────────────────────────────────────
설계 규칙 4 — 어기면 판정이 판정이 아니게 된다
────────────────────────────────────────────────────────────────────────────
1. **Hard Gate가 점수보다 먼저다.** F-Ⅰ~F-Ⅴ 중 하나라도 해당하면 종합 점수를 *산출하기
   전에* NO_GO다. 단일 EOS Score를 만들지 않는 이유가 이것이다 — 치명 오류 하나가
   나머지 11개 지표의 평균에 묻히면, 그 평균은 실패를 감추는 장치가 된다.
2. **미측정은 PASS가 아니다.** 입력이 비어 있으면 "기준 미달 아님 → 통과"가 아니라
   **측정 실패**다. 이 저장소가 반복해서 다친 부류이므로 `KpiVerdict`에 `unmeasured`를
   독립 상태로 두고, 하나라도 있으면 CLI가 exit 1을 낸다.
3. **평균으로 앵커를 덮지 않는다.** F-Ⅳ는 "앵커 6개 중 3개 이상 미달"이라 **앵커 단위
   분해가 판정의 전제**다. 전체 평균만 보면 한 앵커의 붕괴가 다른 다섯에 희석된다.
4. **점추정으로 게이트를 넘지 않는다.** 비율 지표는 Wilson 단측 경계로 판정한다
   (`superhuman_verification_standard`). "85.1%니까 통과"는 표본이 20이면 아무 말도 아니다.
   **방향까지 지표가 갖는다** — 결함율(≤)에 하한을 쓰면 1%가 0.5% 기준을 통과한다.
5. **임계는 코드가 갖고 입력은 관측치만 낸다.** 입력이 자기 합격선(`floor`)을 써 내면
   그것은 판정이 아니라 자기 신고다. §6 동결값이 `CONTENT_KPI_THRESHOLDS`에 있다.
6. **결선표는 배선이 아니다.** `source_module`을 적는 것만으로는 생산자 산출을 못 읽는다 —
   실제 모양(`hit_median_seconds` vs 기대하던 `hit.median_minutes`)이 만나지 않으면
   *실재하는 산출물이 미측정으로 보고된다*. 어댑터(`adapt_*`)가 그 만남을 담당하고,
   **생산자에 없는 것은 만들지 않는다**(P90·재작업률은 미측정으로 남는 것이 정직하다).

────────────────────────────────────────────────────────────────────────────
사용법
────────────────────────────────────────────────────────────────────────────
    python -m whymath_backend.ops.validation_scorecard \
        --hit-cu-json hit.json --qa-matrix-json qa.json \
        --krw-per-usd 1400 --input manual.json

`--hit-cu-json`·`--qa-matrix-json`은 각 생산자 CLI의 `--json` 산출을 **그대로** 받는다.
`--input`은 기계가 아직 못 재는 구간(앵커 판정·힌트 누설 표본 검수)의 수기 입력이고,
어댑터 산출보다 뒤에 병합돼 필요하면 이길 수 있다.

────────────────────────────────────────────────────────────────────────────
결선표 (acceptance ⑤) — 어느 지표가 어느 소스에서 오는가
────────────────────────────────────────────────────────────────────────────
`KPI_SOURCES`가 그 정본이다. 내용 KPI 6종은 **`qa_confusion_matrix.CONTENT_KPI_CONSUMERS`를
재사용**한다 — 거기 이미 KPI↔골든 라벨축↔채점기 모듈↔좌석 태스크가 모델링돼 있고,
`consumer_module=None`이 "아직 만들어지지 않았다"는 정직한 공백 표기다. 같은 것을 여기
다시 적으면 진실 원천이 둘이 된다.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from whymath_backend.harness.wilson import wilson_lower_bound, wilson_upper_bound
from whymath_backend.ops.qa_confusion_matrix import CONTENT_KPI_CONSUMERS

__all__ = [
    "Verdict",
    "KpiVerdict",
    "KpiResult",
    "HardGateResult",
    "Scorecard",
    "KpiThreshold",
    "KPI_SOURCES",
    "CONTENT_KPI_THRESHOLDS",
    "REQUIRED_ANCHORS",
    "adapt_hit_cu_metrics",
    "adapt_qa_confusion_matrix",
    "merge_payloads",
    "evaluate",
    "render",
    "main",
]

CONFIDENCE = 0.95


class Verdict(str, Enum):
    """최종 3단계 판정 — 검증설계서 §5 '판정 체계'."""

    GO = "GO"
    CONDITIONAL_GO = "CONDITIONAL_GO"
    NO_GO = "NO_GO"


class KpiVerdict(str, Enum):
    """KPI 1종의 판정 — `unmeasured`가 독립 상태인 것이 핵심이다.

    `pass`/`fail` 2상태만 두면 "입력이 없다"가 둘 중 하나로 접히고, 어느 쪽으로 접든
    거짓말이 된다: `pass`면 미측정을 통과로 위장하고, `fail`이면 측정하지도 않은 것을
    미달로 낙인찍는다.
    """

    passed = "pass"
    failed = "fail"
    unmeasured = "unmeasured"


# ──────────────────────────────────────────────────────────────────────────
# 결선표 — 기술 KPI 6종 (내용 6종은 CONTENT_KPI_CONSUMERS 재사용)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class KpiSource:
    """KPI 1종의 입력 출처 — '어디서 오는가'를 코드가 말한다."""

    kpi: str
    """검증설계서 §6 지표명(동결 문언 요약)."""

    target: str
    """목표값 문언. G2에서 재조정 가능하되 *지표 정의*는 불변(§7-1)."""

    source_module: str
    """이 지표를 산출하는 모듈(import 경로). 미착지면 `payload`에 키가 없어 unmeasured."""

    payload_key: str
    """`--input` JSON에서 이 지표가 실리는 키."""

    seat_task: str
    """산출 좌석의 태스크 id — 미착지분의 추적 축(만료 없는 유예 금지)."""


KPI_SOURCES: tuple[KpiSource, ...] = (
    KpiSource(
        kpi="HIT (CU당 인간 개입 시간)",
        target="중앙값 ≤4분 · P90 ≤8분",
        source_module="whymath_backend.ops.hit_cu_metrics",
        payload_key="hit",
        seat_task="EOS-54-hit-cu-metrics",
    ),
    KpiSource(
        kpi="자동검증 1차 통과율",
        target="≥85%",
        source_module="whymath_backend.ops.hit_cu_metrics",
        payload_key="auto_gate_pass",
        seat_task="EOS-55-generation-run-log",
    ),
    KpiSource(
        kpi="재작업률",
        target="≤15% (2회+ 재생성 ≤3%)",
        source_module="whymath_backend.ops.hit_cu_metrics",
        payload_key="rework",
        seat_task="EOS-55-generation-run-log",
    ),
    KpiSource(
        kpi="처리량",
        target="≥30 CU/h (인간 기준)",
        source_module="whymath_backend.ops.hit_cu_metrics",
        payload_key="throughput",
        seat_task="EOS-54-hit-cu-metrics",
    ),
    KpiSource(
        kpi="단위 비용",
        target="≤250원/CU (상한 400원)",
        source_module="whymath_backend.ops.cost_probe",
        payload_key="unit_cost",
        seat_task="EOS-55-generation-run-log",
    ),
    KpiSource(
        kpi="실패 유형 분포 (기계형 F1+F2)",
        target="≥60% — F-Ⅲ의 역·가장 중요한 예측 지표",
        source_module="whymath_backend.ops.hit_cu_metrics",
        payload_key="machine_share",
        seat_task="EOS-54-hit-cu-metrics",
    ),
)


#: 결선표(`CONTENT_KPI_CONSUMERS`)에 **없는** 내용 KPI 2종 — 그것이 결함이 아니라 사실이다.
#:
#: §6은 내용 KPI를 6종으로 동결했는데 EOS-60의 결선표에는 4종만 있다(2026-09-01 실측).
#: 빠진 둘은 **골든 벤치마크의 라벨 축으로 잴 수 없는 것들**이라 거기 없는 것이 맞다:
#:
#:   · 난이도 타당도 — 사람 순위와의 상관(Spearman ρ)이라 혼동행렬 축이 아니다. §7-4가
#:     "12월 내 미검증"으로 이미 자인했다(깊이앵커 A4만 학생 반응 수집).
#:   · 힌트 누설률 — F-Ⅴ Hard Gate가 같은 사실을 *차단* 축에서 본다. KPI 축에도 표기하는
#:     이유는 §6이 6종을 요구하기 때문이고, 게이트에 걸리지 않아도 0%가 아닐 수 있다.
#:
#: 이 둘을 스코어카드에서 빼면 "12종 중 10종만 있는데 12종을 봤다"는 착시가 생긴다.
#: `CONTENT_KPI_CONSUMERS`를 늘리지 않는 이유: 그것은 EOS-60(골든 벤치마크) 소유의
#: 정본이고, 골든 라벨 축이 없는 지표를 거기 끼우면 그 계약이 거짓이 된다.
NON_GOLDEN_CONTENT_KPIS: tuple[tuple[str, str, str], ...] = (
    (
        "난이도 타당도 (깊이 Spearman ρ≥0.5 · 폭 전문가 순위 ρ≥0.6)",
        "ρ≥0.5 / ρ≥0.6",
        "§7-4 — 12월 내 구조적 미검증(폭 앵커 학생 반응 미수집). 골든 라벨 축 아님",
    ),
    (
        "힌트 누설률 L1·L2 (무관용 0%)",
        "0%",
        "F-Ⅴ Hard Gate가 차단 축에서 본다. 골든 라벨 축 아님 — 전수 자동+LLM 심판+인간 30건",
    ),
)


# ──────────────────────────────────────────────────────────────────────────
# 동결 임계 — 방향과 값을 **코드가** 갖는다 (입력이 정하지 않는다)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class KpiThreshold:
    """지표 1종의 판정 방향과 임계값 — §6 동결 문언에서 옮겨 적은 것.

    `direction`이 왜 데이터인가: 내용 KPI 4종은 **방향이 섞여 있다**. 정합률·라벨
    정확도는 높을수록 좋고(floor), 수학적 오류율·비약 지적률은 낮을수록 좋다(ceiling).
    전자에는 Wilson **하한**을, 후자에는 **상한**을 써야 보수적 판정이 된다. 한쪽
    방향만 가정하면 결함율 1%가 0.5% 기준을 통과한다 — 하한은 관측치보다 *작기*
    때문이다(PR #953 codex P1 실측).
    """

    direction: str
    """`"floor"`(≥ 통과) 또는 `"ceiling"`(≤ 통과)."""

    value: float

    def judge(self, hits: int, trials: int) -> tuple[bool, float, str]:
        """(통과 여부, 사용한 Wilson 경계, 사람이 읽는 문언). 점추정은 판정에 쓰지 않는다."""
        point = hits / trials
        if self.direction == "ceiling":
            bound = wilson_upper_bound(hits, trials, CONFIDENCE)
            return bound <= self.value, bound, f"{point:.2%} · Wilson 상한 {bound:.2%}"
        bound = wilson_lower_bound(hits, trials, CONFIDENCE)
        return bound >= self.value, bound, f"{point:.1%} · Wilson 하한 {bound:.1%}"

    @property
    def label(self) -> str:
        return f"{'≤' if self.direction == 'ceiling' else '≥'}{self.value:.2%}"


#: 내용 KPI 4종의 임계 — 키는 `CONTENT_KPI_CONSUMERS[i].kpi` 문자열 그대로다.
#:
#: **입력이 임계를 정하지 못하게 하는 것**이 이 표의 존재 이유다. 이전 판은 `--input`의
#: `floor` 필드를 그대로 기준으로 삼았는데, 그러면 측정 대상이 자기 합격선을 써 내는
#: 구조가 된다(그리고 방향이 하한 하나로 고정돼 결함율 지표가 반대로 판정됐다).
#: §6이 동결한 값이므로 여기가 정본이고, 표에 없는 KPI는 통과가 아니라 **미측정**이다.
#:
#: `CONTENT_KPI_CONSUMERS`(EOS-60 소유)와의 정합은
#: `tests/backend/ops/test_validation_scorecard.py`가 기계로 동결한다 — 거기서 KPI 문언이
#: 바뀌면 이 표가 조용히 빗나가는 대신 테스트가 깨진다.
CONTENT_KPI_THRESHOLDS: dict[str, KpiThreshold] = {
    "수학적 오류율 ≤0.5% (독립 모델 심판 전수)": KpiThreshold("ceiling", 0.005),
    "교육과정 정합률 ≥92% (블라인드 역매핑)": KpiThreshold("floor", 0.92),
    "오개념 op-code 라벨 정확도 ≥85%": KpiThreshold("floor", 0.85),
    "풀이 비약 지적률 ≤10% (LLM 심판 κ≥0.5 확인 후 전수 확장)": KpiThreshold("ceiling", 0.10),
}


#: F-Ⅳ가 요구하는 앵커 전체 — "6개 중 3개 이상 미달"은 **6개가 다 있을 때만** 셀 수 있다.
#:
#: 부분 지도(`{"A1": true}`)를 받아들이면 `0/1 미달`이라는 판정이 나오는데, 그것은
#: "앵커가 멀쩡하다"가 아니라 "5개를 재지 않았다"다. 분모가 6이 아니면 판정 자체가
#: 성립하지 않으므로 measurable=False로 떨어뜨린다(PR #953 codex P1).
REQUIRED_ANCHORS: tuple[str, ...] = ("A1", "A2", "A3", "A4", "A5", "A6")


# ──────────────────────────────────────────────────────────────────────────
# 판정 결과 타입
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class KpiResult:
    """KPI 1종의 판정 — 목표·실측·판정 + **표본수**를 항상 함께 낸다.

    표본수를 빼면 "통과"가 표본 3건짜리인지 300건짜리인지 구별되지 않는다(§7-3의
    검출력 한계가 정직하려면 분모가 보여야 한다).
    """

    kpi: str
    target: str
    verdict: KpiVerdict
    observed: str
    """사람이 읽는 실측 문언. 미측정이면 '—'."""

    sample_size: int | None = None
    wilson_bound: float | None = None
    note: str = ""
    """미측정 사유·한계·좌석 태스크 등."""


@dataclass(frozen=True, slots=True)
class HardGateResult:
    """Hard Gate 1건 — 해당하면 즉시 NO_GO."""

    code: str
    """F-Ⅰ~F-Ⅴ."""

    definition: str
    triggered: bool
    """True = 실패 정의에 해당(= NO_GO 사유)."""

    measurable: bool
    """False = 판정에 필요한 입력이 없다. `triggered`와 구분한다 —
    '실패가 아니다'와 '실패인지 모른다'는 다르다."""

    observed: str


@dataclass(frozen=True, slots=True)
class Scorecard:
    verdict: Verdict
    hard_gates: tuple[HardGateResult, ...]
    kpis: tuple[KpiResult, ...]
    limits: tuple[str, ...]
    unmeasured_count: int = 0
    unmeasurable_gate_count: int = 0

    @property
    def measurement_failed(self) -> bool:
        """측정 자체가 불완전한가 — 판정치와 **별개 축**이다.

        NO_GO는 '검증했더니 실패'이고, 측정 실패는 '검증하지 못함'이다. 둘을 같은
        exit code로 내면 후자가 전자로 읽혀 전략 변경을 오발동시킨다.
        """
        return self.unmeasured_count > 0 or self.unmeasurable_gate_count > 0


# ──────────────────────────────────────────────────────────────────────────
# Hard Gate 판정 — 점수보다 먼저 (설계 규칙 1)
# ──────────────────────────────────────────────────────────────────────────
def _num(payload: Any, *path: str) -> float | None:
    """중첩 dict에서 수치를 꺼낸다 — 없으면 None(0으로 위장하지 않는다)."""
    node: Any = payload
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    if isinstance(node, bool) or not isinstance(node, (int, float)):
        return None
    return float(node)


def _anchor_verdicts(payload: dict[str, Any]) -> tuple[dict[str, bool] | None, str]:
    """앵커 지도 → (A1~A6 전수 bool 지도, 사유). 불완전하면 `(None, 사유)`.

    **불완전을 통과로 접지 않는다.** 거부 사유 3종을 문구로 남기는 이유는 "판정 불가"만
    보여 주면 운영자가 무엇을 고쳐야 하는지 모르기 때문이다(실패 원인 유실 금지).
    """
    anchors = payload.get("anchors")
    if not isinstance(anchors, dict) or not anchors:
        return None, "—"
    missing = [a for a in REQUIRED_ANCHORS if a not in anchors]
    extra = sorted(k for k in anchors if k not in REQUIRED_ANCHORS)
    if missing or extra:
        parts = []
        if missing:
            parts.append(f"누락 {', '.join(missing)}")
        if extra:
            parts.append(f"미정의 {', '.join(extra)}")
        return None, f"앵커 지도 불완전 — {' · '.join(parts)}"
    # bool이 아닌 값(문자열 "fail"·None 등)을 통과로 세지 않는다 — 이전 판은 `is False`만
    # 세어서 "fail"이 조용히 합격이 됐다.
    non_bool = sorted(k for k, v in anchors.items() if not isinstance(v, bool))
    if non_bool:
        return None, f"앵커 판정이 bool이 아님 — {', '.join(non_bool)}"
    return {a: bool(anchors[a]) for a in REQUIRED_ANCHORS}, ""


def evaluate_hard_gates(payload: dict[str, Any]) -> tuple[HardGateResult, ...]:
    """F-Ⅰ~F-Ⅴ 전수 판정 — 동결 문언 그대로(12월 수정 금지)."""
    results: list[HardGateResult] = []

    # F-Ⅰ: 중등 기준선 앵커(A3·A4)에서조차 HIT 중앙값 > 12분/CU
    baseline = payload.get("hit", {}).get("baseline_anchor_median_minutes")
    if isinstance(baseline, dict) and baseline:
        worst = max(float(v) for v in baseline.values() if isinstance(v, (int, float)))
        results.append(
            HardGateResult(
                "F-Ⅰ",
                "중등 기준선 앵커(A3·A4) HIT 중앙값 > 12분/CU",
                triggered=worst > 12.0,
                measurable=True,
                observed=f"최대 {worst:.1f}분 ({', '.join(sorted(baseline))})",
            )
        )
    else:
        results.append(
            HardGateResult("F-Ⅰ", "중등 기준선 앵커 HIT 중앙값 > 12분/CU", False, False, "—")
        )

    # F-Ⅱ: 인간 검수를 통과한 CU의 수학적 오류율 > 2%
    errs = _num(payload, "content", "reviewed_math_errors")
    total = _num(payload, "content", "reviewed_cu_total")
    if errs is not None and total is not None and total > 0:
        # 상한을 쓴다 — "2% 넘지 않았다"를 주장하려면 낙관적 점추정으로는 부족하다.
        upper = wilson_upper_bound(int(errs), int(total), CONFIDENCE)
        results.append(
            HardGateResult(
                "F-Ⅱ",
                "인간 검수 통과 CU의 수학적 오류율 > 2%",
                triggered=upper > 0.02,
                measurable=True,
                observed=f"{errs:.0f}/{total:.0f} · Wilson 상한 {upper:.2%}",
            )
        )
    else:
        results.append(HardGateResult("F-Ⅱ", "검수 통과 CU 오류율 > 2%", False, False, "—"))

    # F-Ⅲ: 판단형(F3+F6+F7) 합 > 60% — 비율이므로 Wilson 상한으로 본다(설계 규칙 4).
    #
    # 점추정 비교(`judgment_share > 0.60`)를 쓰면 반려 5건 중 3건(60.0%)이 "미해당"이 된다 —
    # 그 표본의 상한은 87%다. 이 게이트가 묻는 것은 "판단형이 지배적인가"이고, 지배 여부를
    # 낙관적으로 볼 이유가 없다. 그래서 **상한**을 쓴다(PR #953 codex P1).
    judgment_hits = _num(payload, "failure_distribution", "judgment_hits")
    rejected_total = _num(payload, "failure_distribution", "rejected_total")
    if judgment_hits is not None and rejected_total is not None and rejected_total > 0:
        upper = wilson_upper_bound(int(judgment_hits), int(rejected_total), CONFIDENCE)
        results.append(
            HardGateResult(
                "F-Ⅲ",
                "판단형(F3+F6+F7) 합 > 60% (자동화로 흡수 불가한 실패가 지배)",
                triggered=upper > 0.60,
                measurable=True,
                observed=(f"{judgment_hits:.0f}/{rejected_total:.0f} · Wilson 상한 {upper:.1%}"),
            )
        )
    else:
        results.append(HardGateResult("F-Ⅲ", "판단형(F3+F6+F7) 합 > 60%", False, False, "—"))

    # F-Ⅳ: 앵커 6개 중 3개 이상 기준 미달 (2개면 Conditional Go)
    verdicts, reason = _anchor_verdicts(payload)
    if verdicts is not None:
        failing = sorted(name for name, ok in verdicts.items() if not ok)
        results.append(
            HardGateResult(
                "F-Ⅳ",
                "앵커 6개 중 3개 이상 기준 미달 (2개면 Conditional Go)",
                triggered=len(failing) >= 3,
                measurable=True,
                observed=f"{len(failing)}/{len(REQUIRED_ANCHORS)} 미달"
                + (f" — {', '.join(failing)}" if failing else ""),
            )
        )
    else:
        results.append(HardGateResult("F-Ⅳ", "앵커 6개 중 3개 이상 미달", False, False, reason))

    # F-Ⅴ: 힌트의 의미적 정답 누설이 표본 검수에서 ≥ 10%
    leaks = _num(payload, "content", "hint_leak_hits")
    leak_n = _num(payload, "content", "hint_leak_sample")
    if leaks is not None and leak_n is not None and leak_n > 0:
        upper = wilson_upper_bound(int(leaks), int(leak_n), CONFIDENCE)
        results.append(
            HardGateResult(
                "F-Ⅴ",
                "힌트의 의미적 정답 누설(자동 검사 밖)이 표본 검수에서 ≥ 10%",
                triggered=upper >= 0.10,
                measurable=True,
                observed=f"{leaks:.0f}/{leak_n:.0f} · Wilson 상한 {upper:.2%}",
            )
        )
    else:
        results.append(HardGateResult("F-Ⅴ", "힌트 의미적 정답 누설 ≥ 10%", False, False, "—"))

    return tuple(results)


# ──────────────────────────────────────────────────────────────────────────
# KPI 스코어카드
# ──────────────────────────────────────────────────────────────────────────
def _ratio_kpi(
    src: KpiSource,
    payload: dict[str, Any],
    *,
    threshold: KpiThreshold,
    sub: tuple[str, KpiThreshold] | None = None,
) -> KpiResult:
    """비율 지표 — Wilson 단측 경계로 판정한다(점추정 금지·설계 규칙 4).

    `sub`는 **같은 목표 문언 안에 든 두 번째 조건**이다(재작업률의 "2회+ 재생성 ≤3%").
    목표가 둘인데 하나만 재면 나머지 하나는 재지도 않고 통과한 것이 되므로, 하위지표의
    입력이 없으면 **미측정**으로 떨어뜨린다(PR #953 codex P2).
    """
    node = payload.get(src.payload_key)
    if not isinstance(node, dict):
        return KpiResult(
            src.kpi, src.target, KpiVerdict.unmeasured, "—", note=f"좌석 {src.seat_task}"
        )

    def _pair(hits_key: str, trials_key: str) -> tuple[int, int] | None:
        hits = _num(node, hits_key)
        trials = _num(node, trials_key)
        if hits is None or trials is None or trials <= 0:
            return None
        return int(hits), int(trials)

    primary = _pair("hits", "trials")
    if primary is None:
        return KpiResult(
            src.kpi, src.target, KpiVerdict.unmeasured, "—", note=f"좌석 {src.seat_task}"
        )
    hits, trials = primary
    ok, bound, shown = threshold.judge(hits, trials)

    if sub is not None:
        sub_key, sub_threshold = sub
        pair = _pair(f"{sub_key}_hits", f"{sub_key}_trials")
        if pair is None:
            return KpiResult(
                src.kpi,
                src.target,
                KpiVerdict.unmeasured,
                shown,
                sample_size=trials,
                wilson_bound=bound,
                note=(
                    f"하위지표 '{sub_key}'({sub_threshold.label}) 입력 없음 — "
                    f"'{sub_key}_hits'·'{sub_key}_trials' 필요. 목표 2조건 중 1개만 잰 "
                    "상태를 통과로 세지 않는다"
                ),
            )
        sub_ok, _sub_bound, sub_shown = sub_threshold.judge(*pair)
        ok = ok and sub_ok
        shown = f"{shown} · {sub_key} {sub_shown}"

    return KpiResult(
        src.kpi,
        src.target,
        KpiVerdict.passed if ok else KpiVerdict.failed,
        shown,
        sample_size=trials,
        wilson_bound=bound,
    )


def _scalar_kpi(src: KpiSource, payload: dict[str, Any], *, spec: dict[str, Any]) -> KpiResult:
    """분포 지표(HIT·처리량·단가) — 중앙값·P90 등 요약값을 목표와 대조."""
    node = payload.get(src.payload_key)
    if not isinstance(node, dict):
        return KpiResult(
            src.kpi, src.target, KpiVerdict.unmeasured, "—", note=f"좌석 {src.seat_task}"
        )

    parts: list[str] = []
    verdicts: list[bool] = []
    for key, (limit, direction, unit) in spec.items():
        value = _num(node, key)
        if value is None:
            # 이미 잰 축은 버리지 않는다 — 무엇까지 쟀고 무엇이 없어서 못 쟀는지 둘 다 남긴다.
            return KpiResult(
                src.kpi,
                src.target,
                KpiVerdict.unmeasured,
                " · ".join(parts) if parts else "—",
                note=f"'{key}' 미산출 — 생산자가 이 축을 내지 않는다",
            )
        ok = value <= limit if direction == "max" else value >= limit
        verdicts.append(ok)
        parts.append(f"{key}={value:g}{unit}{'' if ok else ' ✗'}")

    # 표본수 없는 요약값은 판정하지 않는다 — "중앙값 3.2분 통과"가 CU 2건짜리인지
    # 200건짜리인지 모르는 상태에서 통과를 선언하면, 그 통과는 아무것도 보증하지 않는다.
    # 미측정으로 떨어뜨려야 exit 1로 드러난다(PR #953 codex P2).
    n = _num(node, "sample_size")
    if n is None or n <= 0:
        return KpiResult(
            src.kpi,
            src.target,
            KpiVerdict.unmeasured,
            " · ".join(parts),
            note="표본수(sample_size) 미기재 — 요약값만으로는 판정하지 않는다",
        )
    return KpiResult(
        src.kpi,
        src.target,
        KpiVerdict.passed if all(verdicts) else KpiVerdict.failed,
        " · ".join(parts),
        sample_size=int(n),
    )


#: 기술 KPI별 판정 규격 — 목표값은 G2 재조정 가능하되 지표 정의는 불변(§7-1).
_TECHNICAL_SPECS: dict[str, dict[str, Any]] = {
    "hit": {"median_minutes": (4.0, "max", "분"), "p90_minutes": (8.0, "max", "분")},
    "throughput": {"cu_per_hour": (30.0, "min", " CU/h")},
    "unit_cost": {"krw_per_cu": (250.0, "max", "원")},
}


def evaluate_kpis(payload: dict[str, Any]) -> tuple[KpiResult, ...]:
    """KPI 12종 — 기술 6(실측) + 내용 6(결선표 기반 착지 여부)."""
    out: list[KpiResult] = []
    for src in KPI_SOURCES:
        if src.payload_key in _TECHNICAL_SPECS:
            out.append(_scalar_kpi(src, payload, spec=_TECHNICAL_SPECS[src.payload_key]))
        elif src.payload_key == "auto_gate_pass":
            out.append(_ratio_kpi(src, payload, threshold=KpiThreshold("floor", 0.85)))
        elif src.payload_key == "rework":
            # §6 목표는 "≤15% **그리고** 2회+ 재생성 ≤3%" — 조건이 둘이다.
            out.append(
                _ratio_kpi(
                    src,
                    payload,
                    threshold=KpiThreshold("ceiling", 0.15),
                    sub=("repeat", KpiThreshold("ceiling", 0.03)),
                )
            )
        elif src.payload_key == "machine_share":
            out.append(_ratio_kpi(src, payload, threshold=KpiThreshold("floor", 0.60)))
        else:  # pragma: no cover — KPI_SOURCES에 규격 없는 항목이 늘면 여기로 온다
            out.append(
                KpiResult(src.kpi, src.target, KpiVerdict.unmeasured, "—", note="판정 규격 미정의")
            )

    # 내용 KPI 6종 — 채점기가 착지했는지를 결선표(CONTENT_KPI_CONSUMERS)가 말한다.
    content = payload.get("content", {})
    for consumer in CONTENT_KPI_CONSUMERS:
        # 미측정이어도 **동결 목표는 보여준다** — 목표 칸에 "§6 내용 KPI"라는 분류명을
        # 적으면 읽는 사람이 무엇에 미달했는지/무엇을 재야 하는지 알 수 없다.
        goal = (
            CONTENT_KPI_THRESHOLDS[consumer.kpi].label
            if (consumer.kpi in CONTENT_KPI_THRESHOLDS)
            else "§6 내용 KPI"
        )
        if consumer.consumer_module is None:
            out.append(
                KpiResult(
                    consumer.kpi,
                    goal,
                    KpiVerdict.unmeasured,
                    "—",
                    note=f"채점기 미착지 — 좌석 {consumer.seat_task}",
                )
            )
            continue
        # 키는 **KPI 이름**이다. `seat_task`로 키를 잡으면 좌석 하나가 KPI 둘을 갖는
        # 경우(교육과정 정합률·풀이 비약 지적률이 둘 다 EOS-61 좌석)에 뒤가 앞을 덮어
        # 한 지표가 조용히 사라진다 — 실측으로 잡았다(정합률이 비약 입력으로 판정됨).
        node = content.get(consumer.kpi)
        if not isinstance(node, dict):
            out.append(
                KpiResult(
                    consumer.kpi,
                    goal,
                    KpiVerdict.unmeasured,
                    "—",
                    note=f"채점기는 있으나 입력 없음 — {consumer.consumer_module}",
                )
            )
            continue
        # 임계는 **코드가 갖는다** — 입력이 자기 합격선을 써 내지 못하게(codex P1).
        threshold = CONTENT_KPI_THRESHOLDS.get(consumer.kpi)
        if threshold is None:
            out.append(
                KpiResult(
                    consumer.kpi,
                    goal,
                    KpiVerdict.unmeasured,
                    "—",
                    note="동결 임계 미등록 — CONTENT_KPI_THRESHOLDS에 방향·값을 먼저 적는다",
                )
            )
            continue
        # 입력이 임계를 들고 오면 무시하지 않고 **거부**한다. 조용히 버리면 운영자는
        # 자기가 쓴 값이 반영됐다고 믿는다(어느 쪽을 의도했는지 우리가 고를 일이 아니다).
        stale = sorted(k for k in ("floor", "ceiling", "threshold") if k in node)
        if stale:
            out.append(
                KpiResult(
                    consumer.kpi,
                    threshold.label,
                    KpiVerdict.unmeasured,
                    "—",
                    note=(
                        f"입력에 임계 필드({', '.join(stale)})가 있다 — 임계는 §6 동결값이며 "
                        "입력이 정하지 않는다. 해당 필드를 지운 뒤 다시 돌린다"
                    ),
                )
            )
            continue
        hits, trials = _num(node, "hits"), _num(node, "trials")
        if hits is None or trials is None or trials <= 0:
            out.append(
                KpiResult(
                    consumer.kpi,
                    threshold.label,
                    KpiVerdict.unmeasured,
                    "—",
                    note="입력 불완전 — 'hits'·'trials' 필요",
                )
            )
            continue
        ok, bound, shown = threshold.judge(int(hits), int(trials))
        out.append(
            KpiResult(
                consumer.kpi,
                threshold.label,
                KpiVerdict.passed if ok else KpiVerdict.failed,
                shown,
                sample_size=int(trials),
                wilson_bound=bound,
            )
        )

    # 골든 라벨 축으로 잴 수 없는 내용 KPI 2종 — 빼면 12종이 10종이 된다(상수 주석 참조).
    for kpi, target, reason in NON_GOLDEN_CONTENT_KPIS:
        node = content.get(kpi)
        if isinstance(node, dict) and isinstance(node.get("observed"), str):
            out.append(
                KpiResult(
                    kpi,
                    target,
                    KpiVerdict.passed if bool(node.get("passed")) else KpiVerdict.failed,
                    str(node["observed"]),
                    sample_size=(
                        int(node["sample_size"])
                        if isinstance(node.get("sample_size"), int)
                        else None
                    ),
                )
            )
        else:
            out.append(KpiResult(kpi, target, KpiVerdict.unmeasured, "—", note=reason))
    return tuple(out)


# ──────────────────────────────────────────────────────────────────────────
# 산출물 어댑터 — **실제** 생산자 JSON을 스코어카드 입력으로 옮긴다
# ──────────────────────────────────────────────────────────────────────────
# 결선표(`KPI_SOURCES.source_module`)가 생산자를 지목하는 것만으로는 배선이 아니다.
# `hit_cu_metrics --json`은 `hit_median_seconds` 같은 **평면 필드**를 내고
# `qa_confusion_matrix --json`은 `matrix`/`metrics`/`coverage`를 낸다 — 스코어카드가
# 기대하던 `hit.median_minutes` 모양과 아무 데서도 만나지 않았다. 어댑터가 없으면 이
# 집계기는 *실재하는 산출물을 미측정으로 보고*한다(PR #953 codex P1 실측).
#
# 어댑터의 규율: **옮길 수 있는 것만 옮기고, 없는 것은 만들지 않는다.**
# 생산자에 P90·재작업 카운트·자동검증 통과율이 없으면 그 KPI는 미측정으로 남는다 —
# 그것이 정직한 상태이고, 채워 넣으면 좌석 미착지가 통과로 위장된다.


#: 생산자가 JSON 키에 파이썬 enum repr을 새게 했을 때의 접두 — 계약 위반 탐지용(EOS-75).
_ENUM_REPR_KEY_PREFIX = "GenerationFailureCode."


def _has_enum_repr_key(keys: Iterable[str]) -> bool:
    """실패코드 키에 파이썬 repr(`GenerationFailureCode.F1`)이 섞였는가 — 계약 위반이다.

    EOS-61 초판은 `key.rsplit(".", 1)[-1]`로 `F1`·`GenerationFailureCode.F1` 양쪽 표기를
    **조용히** 받았다 — 생산자 `qa_confusion_matrix`가 `str(enum)`을 키로 쓴다고 봤기
    때문이다. EOS-75 실측: 검증을 거친 골든은 `use_enum_values=True`라 실제로는 항상 `F1`을
    냈고, repr 키가 든 저장 산출물은 저장소에 0건이다 — **구버전 호환 대상이 없다**. 생산자는
    이제 `canonical_value`로 `.value`를 명시하고 테스트가 동결한다(생산자·소비자 양쪽).
    그래서 수용 분기를 제거하고 반대로 **거부**한다: repr 키를 그냥 두면 sparse 경로에서
    "키 없음 = 0건"으로 읽혀 *수학 오류 0건*이라는 거짓 통과가 되므로, 미측정(None)으로
    드러내는 편이 정직하다(측정 실패가 통과로 위장되면 안 된다 — CLAUDE.md 이중 회계 원칙).
    """
    return any(key.startswith(_ENUM_REPR_KEY_PREFIX) for key in keys)


def _fc_sum(counts: Any, codes: tuple[str, ...], *, dense: bool) -> int | None:
    """실패코드 카운트 합. `dense=True`면 키 누락을 **계약 위반**으로 보고 None을 낸다.

    두 생산자의 의미가 다르다:
      · `hit_cu_metrics.failure_code_counts`는 enum 전 멤버를 0으로 채워 낸다(dense) —
        키가 없다는 것은 "0건"이 아니라 "우리가 아는 그 산출물이 아니다"이므로 미측정.
      · `qa_confusion_matrix.fn_by_failure_code`는 관측된 코드만 담는다(sparse) —
        키가 없으면 실제로 0건이다.
    이 구분을 뭉개면 한쪽에서 계약 위반이 0으로 위장되거나, 다른 쪽에서 정상 산출이
    미측정으로 버려진다.
    """
    if not isinstance(counts, dict):
        return None
    normalized: dict[str, Any] = {str(k): v for k, v in counts.items()}
    if _has_enum_repr_key(normalized):
        # 표기 계약 위반 산출물 — 조용히 0으로 읽지 않고 미측정으로 드러낸다(EOS-75).
        return None
    total = 0
    for code in codes:
        if code not in normalized:
            if dense:
                return None
            continue
        value = normalized[code]
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        total += value
    return total


#: `hit_cu_metrics`의 실패코드 분류 — F1/F2=기계형, F3/F6/F7=판단형(설계서 §5 표).
#: 문자열로 적는 이유는 생산자 JSON의 키가 문자열이기 때문이고, 분류 자체의 정본은
#: `ops/hit_cu_metrics._MACHINE_CODES`·`_JUDGMENT_CODES`다 — 정합은 테스트가 동결한다.
_MACHINE_FAILURE_CODES: tuple[str, ...] = ("F1", "F2")
_JUDGMENT_FAILURE_CODES: tuple[str, ...] = ("F3", "F6", "F7")


def adapt_hit_cu_metrics(
    report: dict[str, Any], *, krw_per_usd: float | None = None
) -> dict[str, Any]:
    """`hit_cu_metrics --json`(평면 `HitCuReport`) → 스코어카드 입력 조각.

    옮기는 것: HIT 중앙값·처리량·기계형/판단형 분포(·환율을 주면 단위 비용).
    옮기지 **않는** 것과 그 이유:
      · HIT P90 — 생산자가 중앙값·평균만 낸다(EOS-54 미산출). 만들면 없는 측정이 생긴다.
      · 자동검증 1차 통과율·재작업률 — 생성 Run 로그(EOS-55) 좌석 미착지.
      · 앵커별 HIT(F-Ⅰ) — 생산자에 앵커 축이 없다(CU 단위 집계).
    """
    out: dict[str, Any] = {}

    median_s = report.get("hit_median_seconds")
    measured = report.get("cu_measured")
    total_s = report.get("hit_total_seconds")
    if isinstance(median_s, (int, float)) and isinstance(measured, int) and measured > 0:
        out["hit"] = {"median_minutes": float(median_s) / 60.0, "sample_size": measured}
        # 처리량 = 검수 완료 CU ÷ 검수 소요 시간(§6 동결 측정 방법 그대로).
        if isinstance(total_s, (int, float)) and total_s > 0:
            out["throughput"] = {
                "cu_per_hour": measured / (float(total_s) / 3600.0),
                "sample_size": measured,
            }

    counts = report.get("failure_code_counts")
    rejected = report.get("rejected_count")
    if isinstance(rejected, int) and rejected > 0:
        machine = _fc_sum(counts, _MACHINE_FAILURE_CODES, dense=True)
        judgment = _fc_sum(counts, _JUDGMENT_FAILURE_CODES, dense=True)
        if machine is not None:
            out["machine_share"] = {"hits": machine, "trials": rejected}
        if judgment is not None:
            out["failure_distribution"] = {
                "judgment_hits": judgment,
                "rejected_total": rejected,
            }

    cost_usd = report.get("cost_usd_total")
    with_cost = report.get("cu_with_cost")
    if (
        krw_per_usd is not None
        and isinstance(cost_usd, (int, float))
        and isinstance(with_cost, int)
        and with_cost > 0
    ):
        out["unit_cost"] = {
            "krw_per_cu": float(cost_usd) * krw_per_usd / with_cost,
            "sample_size": with_cost,
        }
    return out


#: FN(정답지가 결함이라 한 것을 엔진이 놓친 건수)을 "검수 통과 CU의 오류"로 읽는 근거.
#: 골든 기준 FN은 정의상 **결함인데 통과된 CU**다 — F-Ⅱ와 수학적 오류율 KPI가 묻는
#: 바로 그 모집단이다. 이 동일시가 성립하지 않는 축(교육과정 정합·오개념 라벨·비약
#: 지적)은 채점기 자체가 미착지(`consumer_module=None`)라 옮길 것도 없다.
_MATH_ERROR_KPI = "수학적 오류율 ≤0.5% (독립 모델 심판 전수)"


def adapt_qa_confusion_matrix(report: dict[str, Any]) -> dict[str, Any]:
    """`qa_confusion_matrix --json`(`matrix`/`coverage`/`fn_by_failure_code`) → 입력 조각.

    F-Ⅱ(검수 통과 CU 수학 오류율 > 2%)와 내용 KPI '수학적 오류율'은 같은 모집단을 본다 —
    분자=F1·F2 FN, 분모=평가된 골든 항목 수. 앵커 판정(F-Ⅳ)은 **옮기지 않는다**:
    `by_anchor`가 주는 것은 *QA 엔진의 앵커별 FN율*이지 "그 앵커가 기준을 충족했는가"가
    아니다. 간접 신호를 판정으로 쓰지 않는다.
    """
    evaluated = report.get("coverage", {}).get("evaluated")
    fn_errors = _fc_sum(report.get("fn_by_failure_code"), _MACHINE_FAILURE_CODES, dense=False)
    if not isinstance(evaluated, int) or evaluated <= 0 or fn_errors is None:
        return {}
    return {
        "content": {
            "reviewed_math_errors": fn_errors,
            "reviewed_cu_total": evaluated,
            _MATH_ERROR_KPI: {"hits": fn_errors, "trials": evaluated},
        }
    }


def merge_payloads(*payloads: dict[str, Any]) -> dict[str, Any]:
    """스코어카드 입력 조각들을 병합 — 뒤가 앞을 덮는다(dict는 재귀 병합).

    운영자가 `--input`으로 직접 준 값이 어댑터 산출보다 **뒤**에 오게 호출한다.
    수동 입력이 실측을 이길 수 있어야 하는 구간(앵커 판정·힌트 누설 표본)이 있기 때문이다.
    """
    merged: dict[str, Any] = {}
    for payload in payloads:
        for key, value in payload.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = merge_payloads(merged[key], value)
            else:
                merged[key] = value
    return merged


# ──────────────────────────────────────────────────────────────────────────
# 종합 판정 — Hard Gate가 먼저다 (설계 규칙 1)
# ──────────────────────────────────────────────────────────────────────────
#: §7 한계 — 리포트에 **항상** 동반 출력한다(acceptance ④).
#: 이 한계를 빼면 "오류율 0.5% 통과"가 정밀 추정으로 읽히는데, 185 CU 표본은 그 해상도를
#: 갖지 않는다. 한계를 적어야 판정이 정직하다.
DESIGN_LIMITS: tuple[str, ...] = (
    "§7-1 목표값은 실측 벤치마크가 아니라 산술 손익분기 도출값 — "
    "G2 기준선 실측에서 재조정이 정상 경로다(지표 정의는 불변).",
    "§7-2 손익분기 산식의 물량 가정(545노드×4문항)은 실측(원자 리프 1,823)과 다르다 — "
    "G5 판정 시 통과 학교급 기준으로 재산출해야 한다.",
    "§7-3 검수 185 CU 표본은 '치명적으로 나쁨'(오류율 8%+)은 잡지만 "
    "0.5% 수준의 정밀 추정은 못 한다.",
    "§7-4 폭 앵커 난이도 타당도는 12월 내 미검증 — 학생 반응은 깊이앵커(A4)만 수집.",
)


def evaluate(payload: dict[str, Any]) -> Scorecard:
    """입력 → 3단계 판정. **Hard Gate를 먼저 보고, 걸리면 점수를 만들지 않는다.**"""
    gates = evaluate_hard_gates(payload)
    kpis = evaluate_kpis(payload)

    unmeasured = sum(1 for k in kpis if k.verdict is KpiVerdict.unmeasured)
    unmeasurable_gates = sum(1 for g in gates if not g.measurable)

    if any(g.triggered for g in gates):
        # F-Ⅰ~Ⅴ 중 1+ 해당 → No-Go. 종합 점수를 산출하지 않는다.
        return Scorecard(Verdict.NO_GO, gates, kpis, DESIGN_LIMITS, unmeasured, unmeasurable_gates)

    # Conditional Go — F-Ⅳ의 "2개면 Conditional Go" 조항. 앵커 미달이 1~2개면 학교급 일부만
    # 성립한 것이고, 그때의 결론은 통과가 아니라 **출시 범위 축소 확정**이다.
    verdicts, _ = _anchor_verdicts(payload)
    failing = sum(1 for ok in verdicts.values() if not ok) if verdicts else 0
    if failing > 0 or any(k.verdict is KpiVerdict.failed for k in kpis):
        return Scorecard(
            Verdict.CONDITIONAL_GO, gates, kpis, DESIGN_LIMITS, unmeasured, unmeasurable_gates
        )

    # **GO는 측정이 완결됐을 때만 도달 가능하다.**
    #
    # 이 가드가 없으면 *빈 입력*이 GO를 낸다 — Hard Gate가 전부 '판정 불가'라 아무것도
    # triggered되지 않고, KPI가 전부 '미측정'이라 failed도 없기 때문이다. 실측으로 확인했다:
    # `evaluate({})` → GO(미측정 KPI 10 · 판정 불가 게이트 5). 그 GO를 읽는 소비자에게는
    # "검증했고 통과했다"로 보이는데 실제로는 아무것도 검증하지 않았다.
    #
    # 4번째 상태(UNDETERMINED)를 만들지 않은 이유: 판정 형식 3단계는 §5에서 동결됐고
    # 12월 수정 금지다(acceptance ③). 대신 **GO를 도달 불가로 만든다** — 확인되지 않은
    # 것은 "주 기준 충족"이 아니므로 GO의 정의를 애초에 만족하지 않는다. 측정 불완전의
    # *사실*은 `measurement_failed`·리포트 경고·CLI exit 1이 별도 축으로 말한다.
    if unmeasured or unmeasurable_gates:
        return Scorecard(
            Verdict.CONDITIONAL_GO, gates, kpis, DESIGN_LIMITS, unmeasured, unmeasurable_gates
        )
    return Scorecard(Verdict.GO, gates, kpis, DESIGN_LIMITS, unmeasured, unmeasurable_gates)


def render(card: Scorecard) -> str:
    lines = ["# EOS 12월 검증 결론 스코어카드 (EOS-61)", ""]
    lines.append(f"## 판정: **{card.verdict.value}**")
    if card.measurement_failed:
        lines.append("")
        lines.append(
            f"> ⚠️ **측정 불완전** — 미측정 KPI {card.unmeasured_count}종 · "
            f"판정 불가 Hard Gate {card.unmeasurable_gate_count}건. "
            "이 판정은 확정이 아니다(측정 실패 ≠ 기준 미달)."
        )
    lines += ["", "## Hard Gate — F-Ⅰ~F-Ⅴ (점수보다 먼저)", ""]
    lines.append("| 코드 | 실패 정의 | 실측 | 판정 |")
    lines.append("|---|---|---|---|")
    for g in gates_sorted(card.hard_gates):
        if g.triggered:
            mark = "🚫 해당(NO_GO)"
        else:
            mark = "✔ 미해당" if g.measurable else "— 판정 불가"
        lines.append(f"| {g.code} | {g.definition} | {g.observed} | {mark} |")

    lines += ["", "## KPI 스코어카드 (기술 6 · 내용 6)", ""]
    lines.append("| 지표 | 목표 | 실측 | 표본 | 판정 |")
    lines.append("|---|---|---|---:|---|")
    for k in card.kpis:
        mark = {"pass": "✔", "fail": "✗", "unmeasured": "— 미측정"}[k.verdict.value]
        n = str(k.sample_size) if k.sample_size is not None else "—"
        note = f" <br>_{k.note}_" if k.note else ""
        lines.append(f"| {k.kpi} | {k.target} | {k.observed}{note} | {n} | {mark} |")

    lines += ["", "## 한계 (§7 — 정직)", ""]
    lines += [f"- {limit}" for limit in card.limits]
    return "\n".join(lines)


def gates_sorted(gates: tuple[HardGateResult, ...]) -> tuple[HardGateResult, ...]:
    """해당(triggered) → 판정 불가 → 미해당 순 — 읽는 사람이 먼저 봐야 할 것이 위로."""
    return tuple(sorted(gates, key=lambda g: (not g.triggered, g.measurable)))


def main(argv: list[str] | None = None) -> int:
    """CLI — exit 0 = GO, 1 = 그 외(CONDITIONAL_GO·NO_GO·측정 실패).

    exit 1을 세 경우가 공유하는 이유: **셋 다 '지금 그대로 진행하면 안 된다'**이기 때문이다.
    셋의 *구분*은 stdout의 판정 문구와 측정 불완전 경고가 한다 — exit code를 셋으로 쪼개면
    호출 스크립트가 조건 분기를 잘못 짜서 CONDITIONAL_GO를 GO로 흡수할 여지가 생긴다.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, default=None, help="수동 집계 입력 JSON(어댑터 산출을 덮는다)"
    )
    parser.add_argument(
        "--hit-cu-json",
        type=Path,
        default=None,
        help="`hit_cu_metrics --json` 산출 파일 — HIT·처리량·실패 분포를 여기서 읽는다",
    )
    parser.add_argument(
        "--qa-matrix-json",
        type=Path,
        default=None,
        help="`qa_confusion_matrix --json` 산출 파일 — F-Ⅱ·수학적 오류율을 여기서 읽는다",
    )
    parser.add_argument(
        "--krw-per-usd",
        type=float,
        default=None,
        help="단위 비용 환산 환율. 없으면 단위 비용은 미측정(임의 환율을 가정하지 않는다)",
    )
    parser.add_argument("--json", type=Path, default=None, help="판정 결과 JSON 출력 경로")
    args = parser.parse_args(argv)

    if args.input is None and args.hit_cu_json is None and args.qa_matrix_json is None:
        parser.error("--input · --hit-cu-json · --qa-matrix-json 중 최소 하나가 필요하다")

    def _load(path: Path) -> dict[str, Any] | None:
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            # 입력을 못 읽은 것은 '기준 미달'이 아니라 측정 실패다 — 사유를 남긴다.
            print(f"측정 실패({type(exc).__name__}): {path} — {exc}", file=sys.stderr)
            return None
        if not isinstance(loaded, dict):
            print(f"측정 실패: {path} 최상위가 객체가 아니다", file=sys.stderr)
            return None
        return loaded

    # 어댑터 산출 → 수동 입력 순서로 병합한다(수동이 뒤 = 실측을 이길 수 있다).
    parts: list[dict[str, Any]] = []
    if args.hit_cu_json is not None:
        loaded = _load(args.hit_cu_json)
        if loaded is None:
            return 1
        parts.append(adapt_hit_cu_metrics(loaded, krw_per_usd=args.krw_per_usd))
    if args.qa_matrix_json is not None:
        loaded = _load(args.qa_matrix_json)
        if loaded is None:
            return 1
        parts.append(adapt_qa_confusion_matrix(loaded))
    if args.input is not None:
        loaded = _load(args.input)
        if loaded is None:
            return 1
        parts.append(loaded)
    payload = merge_payloads(*parts)

    card = evaluate(payload)
    print(render(card))
    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "verdict": card.verdict.value,
                    "measurement_failed": card.measurement_failed,
                    "unmeasured_kpis": card.unmeasured_count,
                    "unmeasurable_gates": card.unmeasurable_gate_count,
                    "hard_gates": [
                        {
                            "code": g.code,
                            "triggered": g.triggered,
                            "measurable": g.measurable,
                            "observed": g.observed,
                        }
                        for g in card.hard_gates
                    ],
                    "kpis": [
                        {
                            "kpi": k.kpi,
                            "verdict": k.verdict.value,
                            "observed": k.observed,
                            "sample_size": k.sample_size,
                        }
                        for k in card.kpis
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    if card.measurement_failed:
        print(
            f"\n측정 실패: 미측정 KPI {card.unmeasured_count}종 · "
            f"판정 불가 게이트 {card.unmeasurable_gate_count}건 — 이 상태로 GO를 선언할 수 없다.",
            file=sys.stderr,
        )
        return 1
    return 0 if card.verdict is Verdict.GO else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
