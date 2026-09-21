"""QA 엔진 혼동행렬 CLI — 판정기를 판정한다 (EOS-60 acceptance ②④⑤).

무엇을 재나
-----------
`harness/qa_pipeline`이 내는 PASS/FAIL이 **얼마나 맞는지**를 골든 정답지
(`harness/golden_benchmark` — 검수 판정에서 승격한 as-found 라벨) 대비 혼동행렬로 낸다.

    현재:  생성 → QA 엔진 → PASS  →  (그대로 신뢰)
    필요:  골든 → QA 엔진 → 혼동행렬 ├ Precision ├ Recall └ **FN율** ← 무관용 관리 대상

**positive = defective**(결함이 있어서 걸러져야 하는 쪽)로 잡는다. 교육 콘텐츠에서 결정적인
실패는 **False Negative(틀린 콘텐츠를 정상이라 판정)** 이므로 FN은 다른 지표에 묻지 않고
**별도 절**로 보고한다(`docs/reviews/eos_validation_n1_n10_gap_review_2026-08-30.md` §3.7).

    ┌───────────────┬─────────────────────┬─────────────────────┐
    │               │ QA 판정 fail(걸렀다) │ QA 판정 pass(통과)  │
    ├───────────────┼─────────────────────┼─────────────────────┤
    │ 골든 defective │ TP                  │ **FN** ← 무관용      │
    │ 골든 clean     │ FP(오검출)          │ TN                  │
    └───────────────┴─────────────────────┴─────────────────────┘

    Recall = TP/(TP+FN) · Precision = TP/(TP+FP) · **FN율 = FN/(TP+FN)** ·
    오검출률 = FP/(FP+TN)

판정 형식(불변): 점추정 금지 — **Wilson 단측 경계**로만 판정한다(초인간 검증 표준·
`harness/wilson`). "높을수록 좋은" recall·precision은 **하한**, "낮을수록 좋은" FN율·오검출률은
**상한**을 본다(작은 표본의 5/5=1.0 과신 차단).

"작동한 비율" 원칙 (acceptance ④ — CLAUDE.md 절대 금기)
--------------------------------------------------------
  - **골든 적재율**을 상시 보고한다 — 골든 항목 중 QA 판정이 실제로 붙은 비율(+Wilson 하한).
    판정이 없는 골든 항목은 **pass로 간주하지 않는다**(그러면 FN이 0으로 위장된다) — 별도
    `미평가`로 분리 카운트한다.
  - **골든 0건 = 측정 실패**(exit 1). 통과가 아니다. 평가쌍 0건·예측 파일 부재·파싱 전멸도 같다.
  - **판정 불가 지표는 '미산출'로 쓴다** — 골든에 clean 라벨이 0건이면 Precision·오검출률은
    분모가 없다. 0%로 찍지 않고 미산출로 보고하며, 그 지표에 게이트가 걸려 있으면 통과가
    아니라 **측정 실패(exit 1)** 다.

과적합 방지 — 재채점 금지 (acceptance ③의 집행 지점)
-----------------------------------------------------
`--ledger`(+`--engine-revision`)를 주면 평가 1회마다 (골든 digest, 엔진 리비전)을 원장에
append하고, **같은 골든을 다른 엔진 리비전으로 다시 재는 것**을 exit 1로 막는다(S2-11 ·
초인간 검증 §4.5 "결함 교정 후 같은 표본 재채점 금지"). 교정 후 재판정은 rotation을 올린
신규 표본으로 한다. 같은 리비전 재실행은 재현성(S4) 확인이므로 허용된다.
원장을 주지 않으면 이 규율은 **미집행**이며, 리포트가 그 사실을 상시 명기한다(정본화≠집행).
원장이 **깨져 있으면 통과가 아니라 측정 실패(exit 1)** 다 — 손상된 줄이 하필 이전 평가
기록이면 빈 이력을 보고 재채점을 허용하게 되어, 금지 규율이 그 증거가 손상된 바로 그
순간에 무력화된다.

집행 별항 — 내용 KPI 4종의 소비 지점 (acceptance ⑤)
----------------------------------------------------
EOS-51 §6 내용 KPI 중 4종이 이 골든을 정답지로 쓴다. 어느 라벨 축이 어느 KPI의 정답지이고
그 채점기가 실제로 착지했는지를 `CONTENT_KPI_CONSUMERS`가 표로 동결하고, 리포트가 **정답지
확보 현황(라벨 축별 건수)** 과 함께 상시 출력한다 — 골든이 있어도 F4 라벨이 0건이면 교육과정
정합률 KPI는 여전히 계산 근거가 없다는 사실이 그 자리에서 보인다.

측정 도구 실패 경로 설계 (2026-08-22 규칙)
------------------------------------------
단계별 즉시 flush 출력 · 파싱 실패는 예외 타입명+줄 번호로 전건 보존(값 미출력) ·
`--since`/`--until` 없이도 "이번 실행"을 식별하도록 골든 digest·엔진 리비전을 리포트 머리에
찍는다 · 외부 프로세스 0(파일 I/O만 — 타임아웃 대상 없음).

사용:
    python -m whymath_backend.ops.qa_confusion_matrix \\
        --golden golden.json --predictions qa_verdicts.jsonl \\
        --engine-revision "$(git rev-parse --short HEAD)" --ledger golden_eval_ledger.jsonl \\
        --max-fn-upper 0.10 --min-coverage 0.9
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from whymath_backend.harness.golden_benchmark import (
    EvaluationRecord,
    GoldenItem,
    GoldenLabel,
    GoldenSet,
    append_evaluation_ledger,
    canonical_value,
    find_rescore_violation,
    load_evaluation_ledger,
    load_golden_set,
)
from whymath_backend.harness.wilson import wilson_lower_bound, wilson_upper_bound
from whymath_backend.schema.enums import GenerationFailureCode

__all__ = [
    "CONTENT_KPI_CONSUMERS",
    "ConfusionMatrix",
    "ContentKpiConsumer",
    "MatrixReport",
    "Prediction",
    "build_report",
    "evaluate",
    "main",
    "parse_predictions",
    "render_report",
]

_EXIT_OK = 0
_EXIT_MEASUREMENT_FAIL = 1

_CONFIDENCE = 0.95
"""Wilson 신뢰수준 — 저장소 전 게이트 공용 기본값 0.95(qa_pipeline·defect_detection_eval 동일)."""


# ──────────────────────────────────────────────────────────────────────────
# 집행 별항(acceptance ⑤) — 내용 KPI 4종 × 골든 라벨 축 × 소비 지점.
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class ContentKpiConsumer:
    """내용 KPI 1종이 이 골든을 소비하는 지점 — 라벨 축·채점기·착지 여부."""

    kpi: str
    """EOS-51 §6 내용 KPI 이름(동결 문언 요약)."""

    label_axis: str
    """이 KPI의 정답지가 되는 골든 라벨 축(실패코드 기준)."""

    consumer_module: str | None
    """채점기 모듈 경로(import 경로). None = 아직 만들어지지 않았다(정직한 공백)."""

    seat_task: str
    """채점기의 좌석 태스크 id — 미착지분의 추적 축(만료 없는 유예 금지)."""

    failure_codes: tuple[GenerationFailureCode, ...]
    """정답지 확보 현황을 셀 때 세는 실패코드."""


CONTENT_KPI_CONSUMERS: tuple[ContentKpiConsumer, ...] = (
    ContentKpiConsumer(
        kpi="수학적 오류율 ≤0.5% (독립 모델 심판 전수)",
        label_axis="defective ∧ F1·F2(기계형 결함)",
        consumer_module="whymath_backend.ops.qa_confusion_matrix",
        seat_task="EOS-60-golden-benchmark-qa-confusion-matrix",
        failure_codes=(GenerationFailureCode.F1, GenerationFailureCode.F2),
    ),
    ContentKpiConsumer(
        kpi="교육과정 정합률 ≥92% (블라인드 역매핑)",
        label_axis="defective ∧ F4(성취기준 이탈)",
        consumer_module=None,
        seat_task="EOS-61-validation-scorecard-aggregator",
        failure_codes=(GenerationFailureCode.F4,),
    ),
    ContentKpiConsumer(
        kpi="오개념 op-code 라벨 정확도 ≥85%",
        label_axis="defective ∧ F6(오개념 오연결)",
        consumer_module=None,
        seat_task="MISC-07-anchor-machine-detection-channels",
        failure_codes=(GenerationFailureCode.F6,),
    ),
    ContentKpiConsumer(
        kpi="풀이 비약 지적률 ≤10% (LLM 심판 κ≥0.5 확인 후 전수 확장)",
        label_axis="defective ∧ F3(풀이 논리 비약)",
        consumer_module=None,
        seat_task="EOS-61-validation-scorecard-aggregator",
        failure_codes=(GenerationFailureCode.F3,),
    ),
)
"""내용 KPI 4종의 골든 소비 결선표 — 착지/미착지를 있는 그대로 적는다(추정 금지).

`consumer_module=None`은 "그 KPI의 채점기가 아직 없다"는 정직한 공백이고, `seat_task`가 그
공백의 추적 축이다. 표와 실체의 정합(착지분은 import 가능·미착지분은 좌석 태스크 실재)은
`tests/backend/ops/test_qa_confusion_matrix.py`가 기계로 동결한다.
"""


def _module_available(dotted: str | None) -> bool:
    """모듈 실재 실측 — 선언이 아니라 import 가능 여부로 착지를 판정한다(find_spec·실행 없음)."""
    if dotted is None:
        return False
    try:
        return importlib.util.find_spec(dotted) is not None
    except (ImportError, ValueError):
        return False


# ──────────────────────────────────────────────────────────────────────────
# 입력 — QA 엔진 판정 예측.
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class Prediction:
    """QA 엔진의 CU 1건 판정 — passed=True면 '정상으로 통과시켰다'."""

    cu_slug: str
    passed: bool
    failure_code: GenerationFailureCode | None = None
    """엔진이 붙인 실패코드(있으면). 라벨 정확도 분해에 쓰지만 혼동행렬 판정에는 쓰지 않는다."""


_PASS_TOKENS = frozenset({"pass", "passed", "ok", "approved", "accept", "accepted", "true"})
_FAIL_TOKENS = frozenset({"fail", "failed", "reject", "rejected", "block", "blocked", "false"})


def parse_predictions(rows: Iterable[Mapping[str, Any]]) -> tuple[list[Prediction], list[str]]:
    """예측 JSONL 파싱 — 어휘 밖 판정은 삼키지 않고 실패로 센다(pass로 관용하면 FN이 위장된다).

    식별 키는 cu_slug/slug/code, 판정 키는 qa_verdict/verdict/status(문자열) 또는
    passed/qa_pass(불리언).
    """
    parsed: list[Prediction] = []
    errors: list[str] = []
    for index, row in enumerate(rows, start=1):
        cu_slug = row.get("cu_slug") or row.get("slug") or row.get("code")
        if not cu_slug:
            errors.append(f"KeyError: 예측 {index}번째 행(cu_slug 누락)")
            continue
        passed: bool | None = None
        for key in ("passed", "qa_pass"):
            value = row.get(key)
            if isinstance(value, bool):
                passed = value
                break
        if passed is None:
            raw = row.get("qa_verdict") or row.get("verdict") or row.get("status")
            token = str(raw).strip().lower() if raw is not None else ""
            if token in _PASS_TOKENS:
                passed = True
            elif token in _FAIL_TOKENS:
                passed = False
            else:
                errors.append(f"ValueError: 예측 {index}번째 행(판정 어휘 밖)")
                continue
        raw_code = row.get("failure_code")
        code: GenerationFailureCode | None = None
        if raw_code:
            try:
                code = GenerationFailureCode(str(raw_code))
            except ValueError as exc:
                errors.append(f"{type(exc).__name__}: 예측 {index}번째 행(실패코드 어휘 밖)")
                continue
        parsed.append(Prediction(cu_slug=str(cu_slug), passed=passed, failure_code=code))
    return parsed, errors


# ──────────────────────────────────────────────────────────────────────────
# 순수 집계 코어 — I/O 없음(픽스처 전수 검증 가능).
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class ConfusionMatrix:
    """혼동행렬 4칸 — positive = defective(걸러져야 하는 쪽)."""

    tp: int = 0
    fn: int = 0
    fp: int = 0
    tn: int = 0

    @property
    def evaluated(self) -> int:
        return self.tp + self.fn + self.fp + self.tn

    @property
    def defective(self) -> int:
        return self.tp + self.fn

    @property
    def clean(self) -> int:
        return self.fp + self.tn

    @property
    def flagged(self) -> int:
        """엔진이 fail로 판정한 수 — Precision의 분모."""
        return self.tp + self.fp

    def recall_lower(self, confidence: float = _CONFIDENCE) -> float | None:
        """검출률(recall) Wilson **하한** — 높을수록 좋으므로 정직하게 낮춰 본다."""
        if self.defective == 0:
            return None
        return wilson_lower_bound(self.tp, self.defective, confidence)

    def precision_lower(self, confidence: float = _CONFIDENCE) -> float | None:
        """정밀도 Wilson **하한**. 엔진이 아무것도 걸르지 않으면 분모 0 → 미산출(0% 아님)."""
        if self.flagged == 0:
            return None
        return wilson_lower_bound(self.tp, self.flagged, confidence)

    def fn_rate_upper(self, confidence: float = _CONFIDENCE) -> float | None:
        """**FN율 Wilson 상한** — 낮을수록 좋으므로 보수적으로 높여 본다(무관용 축)."""
        if self.defective == 0:
            return None
        return wilson_upper_bound(self.fn, self.defective, confidence)

    def false_alarm_upper(self, confidence: float = _CONFIDENCE) -> float | None:
        """오검출률 Wilson 상한. clean 라벨이 0건이면 미산출(승격 경로 ⓐ·ⓑ 부재 시 정상 상태)."""
        if self.clean == 0:
            return None
        return wilson_upper_bound(self.fp, self.clean, confidence)


def evaluate(
    items: Sequence[GoldenItem], predictions: Sequence[Prediction]
) -> tuple[ConfusionMatrix, tuple[str, ...], tuple[str, ...]]:
    """골든 × 예측 → (혼동행렬, 미평가 골든 slug, 골든 밖 예측 slug).

    미평가(예측 없음)는 **pass로 간주하지 않는다** — 그러면 FN이 0으로 위장된다. 골든 밖 예측은
    분모를 오염시키지 않도록 제외하고 별도 보고한다(예측 파일이 다른 배치일 수 있다).
    """
    by_slug: dict[str, Prediction] = {}
    for prediction in predictions:
        by_slug[prediction.cu_slug] = prediction  # 같은 CU 중복 예측은 마지막 것이 이긴다
    golden_slugs = {item.cu_slug for item in items}

    tp = fn = fp = tn = 0
    unevaluated: list[str] = []
    for item in items:
        matched = by_slug.get(item.cu_slug)
        if matched is None:
            unevaluated.append(item.cu_slug)
            continue
        if item.label == GoldenLabel.DEFECTIVE:
            if matched.passed:
                fn += 1
            else:
                tp += 1
        else:
            if matched.passed:
                tn += 1
            else:
                fp += 1
    extraneous = sorted(slug for slug in by_slug if slug not in golden_slugs)
    return ConfusionMatrix(tp=tp, fn=fn, fp=fp, tn=tn), tuple(unevaluated), tuple(extraneous)


@dataclass(frozen=True, slots=True)
class AnchorBreakdown:
    """앵커 1개의 혼동행렬 — 평균 은폐 방지(F-Ⅳ가 앵커 단위 판정이므로 분해가 필수)."""

    anchor_id: str
    matrix: ConfusionMatrix
    unevaluated: int


@dataclass(frozen=True, slots=True)
class MatrixReport:
    """혼동행렬 리포트 — 판정치 + 적재율 + 정답지 확보 현황 + 미집행 자인."""

    golden_version: str
    golden_digest: str
    rotation: int
    frozen_at: datetime
    subject_id: str
    engine_revision: str | None
    matrix: ConfusionMatrix
    golden_total: int
    unevaluated: tuple[str, ...]
    extraneous_predictions: tuple[str, ...]
    by_anchor: tuple[AnchorBreakdown, ...]
    fn_by_failure_code: Mapping[str, int]
    """놓친 결함(FN)의 실패코드 분포 — 어떤 결함류를 못 보는지가 다음 교정 대상이다.

    키 계약(EOS-75): 코드 **값** 문자열(`F1`~`F8`) 또는 `(코드 없음)` — 파이썬 enum
    repr(`GenerationFailureCode.F1`)은 금지. JSON 소비자(`validation_scorecard`)가 이 표기만
    읽는다.
    """
    golden_by_failure_code: Mapping[str, int]
    """골든 정답지의 실패코드 분포 — 내용 KPI별 정답지 확보 현황(acceptance ⑤). 키 계약 동일."""
    ledger_enforced: bool
    parse_errors: tuple[str, ...] = field(default=())
    confidence: float = _CONFIDENCE

    @property
    def coverage_rate(self) -> float | None:
        """골든 적재율 — 골든 중 QA 판정이 붙은 비율. 골든 0건이면 미산출."""
        if self.golden_total == 0:
            return None
        return self.matrix.evaluated / self.golden_total

    @property
    def coverage_lower(self) -> float | None:
        if self.golden_total == 0:
            return None
        return wilson_lower_bound(self.matrix.evaluated, self.golden_total, self.confidence)


def build_report(
    golden: GoldenSet,
    predictions: Sequence[Prediction],
    *,
    engine_revision: str | None = None,
    ledger_enforced: bool = False,
    parse_errors: Sequence[str] = (),
    confidence: float = _CONFIDENCE,
) -> MatrixReport:
    """골든 셋 + 예측 → 리포트(순수). I/O·게이트 판정 없음 — 판정은 `main`이 한다."""
    matrix, unevaluated, extraneous = evaluate(golden.items, predictions)

    by_slug = {p.cu_slug: p for p in predictions}
    fn_by_code: dict[str, int] = {}
    golden_by_code: dict[str, int] = {}
    for item in golden.items:
        if item.label == GoldenLabel.DEFECTIVE:
            # 키는 코드 값(`F1`)이다 — `str(enum)`은 repr(`GenerationFailureCode.F1`)을 내고,
            # 검증 경유 항목이 우연히 str인 것에 기대지 않는다(EOS-75 · `canonical_value`).
            code = (
                canonical_value(item.failure_code)
                if item.failure_code is not None
                else "(코드 없음)"
            )
            golden_by_code[code] = golden_by_code.get(code, 0) + 1
            prediction = by_slug.get(item.cu_slug)
            if prediction is not None and prediction.passed:
                fn_by_code[code] = fn_by_code.get(code, 0) + 1

    anchors: dict[str, list[GoldenItem]] = {}
    for item in golden.items:
        anchors.setdefault(item.anchor_id, []).append(item)
    breakdowns: list[AnchorBreakdown] = []
    for anchor_id in sorted(anchors):
        anchor_matrix, anchor_unevaluated, _ = evaluate(anchors[anchor_id], predictions)
        breakdowns.append(
            AnchorBreakdown(
                anchor_id=anchor_id,
                matrix=anchor_matrix,
                unevaluated=len(anchor_unevaluated),
            )
        )

    return MatrixReport(
        golden_version=golden.golden_version,
        golden_digest=golden.digest,
        rotation=golden.rotation,
        frozen_at=golden.frozen_at,
        subject_id=golden.subject_id,
        engine_revision=engine_revision,
        matrix=matrix,
        golden_total=len(golden.items),
        unevaluated=unevaluated,
        extraneous_predictions=extraneous,
        by_anchor=tuple(breakdowns),
        fn_by_failure_code=fn_by_code,
        golden_by_failure_code=golden_by_code,
        ledger_enforced=ledger_enforced,
        parse_errors=tuple(parse_errors),
        confidence=confidence,
    )


def _fmt(value: float | None) -> str:
    """미산출은 0%로 찍지 않는다 — 판정 불가와 0은 다른 사태다."""
    return "미산출" if value is None else f"{value:.4f}"


def render_report(report: MatrixReport) -> str:
    """혼동행렬 리포트 markdown — FN을 별도 절로 세우고, 미측정·미집행을 상시 자인한다."""
    m = report.matrix
    lines: list[str] = ["# QA 엔진 혼동행렬 (EOS-60)", ""]
    lines.append(
        f"- 골든: version={report.golden_version} · rotation={report.rotation} · "
        f"digest={report.golden_digest[:12]}… · 동결 {report.frozen_at.isoformat()}"
    )
    lines.append(f"- 과목 축(subject_id): {report.subject_id}")
    lines.append(f"- 엔진 리비전: {report.engine_revision or '미지정'}")
    lines.append(f"- Wilson 신뢰수준(단측): {report.confidence}")
    lines.append("")

    lines.append('## 적재율 ("작동한 비율" 원칙 — 응답 200은 평가가 아니다)')
    lines.append(
        f"- 골든 {report.golden_total}건 중 QA 판정 동반 {m.evaluated}건 = "
        f"{_fmt(report.coverage_rate)} (Wilson 하한 {_fmt(report.coverage_lower)})"
    )
    lines.append(
        f"- 미평가 {len(report.unevaluated)}건 — **pass로 간주하지 않음**(FN 위장 방지·분리 카운트)"
    )
    lines.append(f"- 골든 밖 예측 {len(report.extraneous_predictions)}건(분모 제외)")
    lines.append("")

    lines.append("## 혼동행렬 (positive = defective)")
    lines.append("")
    lines.append("| | QA fail(걸렀다) | QA pass(통과) |")
    lines.append("|---|---|---|")
    lines.append(f"| 골든 defective | TP {m.tp} | **FN {m.fn}** |")
    lines.append(f"| 골든 clean | FP {m.fp} | TN {m.tn} |")
    lines.append("")
    lines.append(f"- Recall(검출률) Wilson 하한: {_fmt(m.recall_lower(report.confidence))}")
    lines.append(f"- Precision Wilson 하한: {_fmt(m.precision_lower(report.confidence))}")
    lines.append(f"- 오검출률 Wilson 상한: {_fmt(m.false_alarm_upper(report.confidence))}")
    if m.clean == 0:
        lines.append(
            "  - clean 라벨 0건 → Precision·오검출률 **미산출**(승격 경로 ⓐ·ⓑ 부재 시 정상 상태 — "
            "반려분만 골든이 되면 clean 축이 비어 있다)"
        )
    lines.append("")

    lines.append("## False Negative — 무관용 축 (별도 보고)")
    lines.append(
        f"- FN {m.fn} / defective {m.defective} · **FN율 Wilson 상한 "
        f"{_fmt(m.fn_rate_upper(report.confidence))}**"
    )
    if m.defective == 0:
        lines.append("  - defective 라벨 0건 → FN율 **미산출**(측정 실패 — 통과 아님)")
    if report.fn_by_failure_code:
        lines.append("- 놓친 결함의 실패코드 분포(다음 교정 대상):")
        for code in sorted(report.fn_by_failure_code):
            lines.append(f"  - {code}: {report.fn_by_failure_code[code]}건")
    else:
        lines.append("- 놓친 결함 0건(또는 defective 미평가) — 표본 수와 함께 읽을 것")
    lines.append("")

    lines.append("## 앵커별 분해 (평균 은폐 방지 — F-Ⅳ는 앵커 단위 판정)")
    lines.append("")
    lines.append("| 앵커 | TP | FN | FP | TN | 미평가 | FN율 상한 |")
    lines.append("|---|---|---|---|---|---|---|")
    for row in report.by_anchor:
        am = row.matrix
        lines.append(
            f"| {row.anchor_id} | {am.tp} | {am.fn} | {am.fp} | {am.tn} | {row.unevaluated} | "
            f"{_fmt(am.fn_rate_upper(report.confidence))} |"
        )
    lines.append("")

    lines.append("## 내용 KPI 정답지 확보 현황 (집행 별항 — acceptance ⑤)")
    lines.append("")
    lines.append("| 내용 KPI (EOS-51 §6) | 골든 라벨 축 | 정답지 건수 | 채점기 | 좌석 |")
    lines.append("|---|---|---|---|---|")
    for consumer in CONTENT_KPI_CONSUMERS:
        # 조회 키도 같은 표기(`canonical_value`)로 — 생산·조회가 갈라지면 정답지가 있어도 0건.
        count = sum(
            report.golden_by_failure_code.get(canonical_value(code), 0)
            for code in consumer.failure_codes
        )
        landed = _module_available(consumer.consumer_module)
        engine = f"`{consumer.consumer_module}`" if landed else "**미착지**"
        lines.append(
            f"| {consumer.kpi} | {consumer.label_axis} | {count}건 | {engine} | "
            f"`{consumer.seat_task}` |"
        )
    lines.append("")
    lines.append(
        "정답지 0건인 축은 골든이 있어도 그 KPI의 계산 근거가 아직 없다는 뜻이다" "(미측정 ≠ 정상)."
    )
    lines.append("")

    lines.append("## 재채점 금지 집행 상태 (acceptance ③)")
    if report.ledger_enforced:
        lines.append(
            "- 평가 원장 **집행 중** — 같은 골든을 다른 엔진 리비전으로 재채점하면 exit 1."
        )
    else:
        lines.append(
            "- **미집행** — `--ledger`(+`--engine-revision`) 미제공. 이 실행은 S2-11 재채점 금지를 "
            "강제하지 않는다(정본화≠집행 자인)."
        )
    if report.parse_errors:
        lines.append("")
        lines.append(f"## 파싱 실패 {len(report.parse_errors)}건 (사유 보존)")
        lines.extend(f"- {reason}" for reason in report.parse_errors)
    return "\n".join(lines) + "\n"


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────
def _say(message: str) -> None:
    """단계별 진행·판정 출력 — stderr·즉시 flush(중간에 죽어도 어디까지 갔는지 남는다).

    stdout은 데이터(리포트 본문) 전용이다 — `ops/hit_cu_metrics` 동일 규약(#909 codex P2).
    """
    print(message, file=sys.stderr, flush=True)


def _load_jsonl_dicts(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """JSONL → dict 목록. 파싱 실패 줄은 예외 타입명+줄 번호로 수집(값·원문 미출력)."""
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    with path.open(encoding="utf-8") as fp:
        for lineno, line in enumerate(fp, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                obj = json.loads(text)
            except json.JSONDecodeError as exc:
                errors.append(f"{type(exc).__name__}: {path.name} {lineno}번째 줄")
                continue
            if isinstance(obj, dict):
                rows.append(obj)
            else:
                errors.append(f"TypeError: {path.name} {lineno}번째 줄(객체 아님)")
    return rows, errors


def _check_gate(
    label: str, value: float | None, threshold: float | None, *, upper: bool
) -> tuple[bool, str] | None:
    """게이트 1건 판정 — 미지정이면 None, 미산출인데 게이트가 걸리면 **측정 실패**로 본다."""
    if threshold is None:
        return None
    if value is None:
        return (False, f"[측정 실패] {label} 미산출인데 게이트가 지정됐다 — 통과 아님")
    if upper:
        ok = value <= threshold
        return (ok, f"{'[통과]' if ok else '[미달]'} {label} 상한 {value:.4f} vs ≤{threshold}")
    ok = value >= threshold
    return (ok, f"{'[통과]' if ok else '[미달]'} {label} 하한 {value:.4f} vs ≥{threshold}")


def main(argv: Sequence[str] | None = None) -> int:
    """혼동행렬 CLI — exit 0(측정 성공 + 게이트 통과) / 1(측정 실패 또는 게이트 위반)."""
    parser = argparse.ArgumentParser(
        prog="qa_confusion_matrix",
        description="골든 대비 QA 엔진 혼동행렬(Precision·Recall·FN율) — EOS-60 acceptance ②",
    )
    parser.add_argument("--golden", required=True, help="동결 골든 셋 JSON(golden_benchmark 산출)")
    parser.add_argument("--predictions", required=True, help="QA 엔진 판정 JSONL(cu_slug+판정)")
    parser.add_argument("--engine-revision", default=None, help="엔진 리비전(재채점 금지 식별 축)")
    parser.add_argument("--ledger", default=None, help="평가 원장 JSONL — 재채점 금지 집행")
    parser.add_argument("--confidence", type=float, default=_CONFIDENCE, help="Wilson 신뢰수준")
    parser.add_argument("--report", default=None, help="리포트 markdown 저장 경로")
    parser.add_argument("--json", dest="json_out", default=None, help="리포트 JSON 저장 경로")
    parser.add_argument("--min-recall-lower", type=float, default=None, help="검출률 하한 게이트")
    parser.add_argument(
        "--min-precision-lower", type=float, default=None, help="정밀도 하한 게이트"
    )
    parser.add_argument("--max-fn-upper", type=float, default=None, help="FN율 상한 게이트")
    parser.add_argument(
        "--max-false-alarm-upper", type=float, default=None, help="오검출률 상한 게이트"
    )
    parser.add_argument(
        "--min-coverage", type=float, default=None, help="골든 적재율 하한 게이트(Wilson 하한)"
    )
    args = parser.parse_args(argv)

    golden_path = Path(args.golden)
    if not golden_path.exists():
        _say(f"[측정 실패] FileNotFoundError: 골든 파일 없음 — {golden_path}")
        return _EXIT_MEASUREMENT_FAIL
    try:
        golden = load_golden_set(golden_path)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        _say(f"[측정 실패] {type(exc).__name__}: 골든 로드 불가 — {golden_path}")
        return _EXIT_MEASUREMENT_FAIL
    _say(
        f"[① 골든] {len(golden.items)}건 · version={golden.golden_version} "
        f"rotation={golden.rotation} digest={golden.digest[:12]}… — {golden_path}"
    )
    if not golden.items:
        _say("[측정 실패] 골든 0건 — '통과'가 아니라 잰 것이 없다(exit 1).")
        return _EXIT_MEASUREMENT_FAIL

    predictions_path = Path(args.predictions)
    if not predictions_path.exists():
        _say(f"[측정 실패] FileNotFoundError: 예측 파일 없음 — {predictions_path}")
        return _EXIT_MEASUREMENT_FAIL
    raw_rows, load_errors = _load_jsonl_dicts(predictions_path)
    predictions, parse_errors = parse_predictions(raw_rows)
    all_errors = [*load_errors, *parse_errors]
    _say(f"[② 예측] {len(predictions)}건 · 파싱 실패 {len(all_errors)}건 — {predictions_path}")
    for reason in all_errors:
        _say(f"  · {reason}")
    if not predictions:
        _say("[측정 실패] 예측 0건 — QA 판정이 하나도 읽히지 않았다(exit 1).")
        return _EXIT_MEASUREMENT_FAIL

    # 재채점 금지(acceptance ③) — 원장이 있으면 *평가 전에* 위반을 막는다.
    ledger_enforced = False
    ledger_path: Path | None = None
    if args.ledger:
        if not args.engine_revision:
            _say("[측정 실패] --ledger에는 --engine-revision이 필요하다(재채점 식별 축 없음).")
            return _EXIT_MEASUREMENT_FAIL
        ledger_path = Path(args.ledger)
        records, ledger_errors = load_evaluation_ledger(ledger_path)
        for reason in ledger_errors:
            _say(f"  · {reason}")
        # 원장이 깨졌으면 **판정하지 않는다**(#928 리뷰 P1). 깨진 줄이 하필 이전 평가 기록이면
        # `find_rescore_violation`이 빈/부분 이력을 보고 재채점을 통과시킨다 — 금지 규율이
        # 그 증거가 손상된 바로 그 순간에 무력화된다. 손상 = 판정 불가지 통과가 아니다.
        if ledger_errors:
            _say(
                f"[측정 실패] 원장 파싱 실패 {len(ledger_errors)}건 — 재채점 이력이 손상된 "
                "상태에서는 재채점 금지를 판정할 수 없다(원장을 고치고 재실행)"
            )
            return _EXIT_MEASUREMENT_FAIL
        violation = find_rescore_violation(
            records, digest=golden.digest, engine_revision=args.engine_revision
        )
        if violation is not None:
            _say(
                "[재채점 금지 위반] 같은 골든(digest "
                f"{golden.digest[:12]}…)을 이미 리비전 '{violation.engine_revision}'로 "
                f"평가했다({violation.evaluated_at.isoformat()}). 교정 후 같은 표본 재채점은 "
                "S2-11·초인간 검증 §4.5 위반 — rotation을 올린 신규 독립 표본으로 재판정하라."
            )
            return _EXIT_MEASUREMENT_FAIL
        ledger_enforced = True

    report = build_report(
        golden,
        predictions,
        engine_revision=args.engine_revision,
        ledger_enforced=ledger_enforced,
        parse_errors=all_errors,
        confidence=args.confidence,
    )
    rendered = render_report(report)
    # 데이터는 stdout(리포트 본문), 진행·판정은 stderr(_say) — 분리.
    print(rendered, flush=True)

    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered, encoding="utf-8")
        _say(f"[리포트] {report_path}")
    if args.json_out:
        json_path = Path(args.json_out)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(_report_payload(report), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        _say(f"[JSON] {json_path}")

    # 파싱 실패가 하나라도 있으면 판정하지 않는다 — 깨진 행이 하필 FN을 만드는 pass
    # 판정이었다면 FN이 조용히 사라진 채 게이트가 통과한다(부분 입력 판정 금지·
    # hit_cu_metrics 동일 규약). 리포트는 이미 출력했으므로 증거는 남는다.
    if all_errors:
        _say(
            f"[측정 실패] 파싱 실패 {len(all_errors)}건 — 유실된 행이 혼동행렬을 바꿨을 수 "
            "있어 부분 입력으로는 판정하지 않는다(입력을 고치고 재실행)"
        )
        return _EXIT_MEASUREMENT_FAIL
    if report.matrix.evaluated == 0:
        _say("[측정 실패] 골든과 겹치는 예측 0건 — 평가쌍이 없다(exit 1).")
        return _EXIT_MEASUREMENT_FAIL

    # 원장 append는 *측정이 성립한 뒤*에만 한다 — 측정 실패 회차를 재채점 이력으로 남기지 않는다.
    if ledger_enforced and ledger_path is not None and args.engine_revision:
        append_evaluation_ledger(
            ledger_path,
            EvaluationRecord(
                digest=golden.digest,
                engine_revision=args.engine_revision,
                evaluated_at=datetime.now(UTC),
                golden_version=golden.golden_version,
                rotation=golden.rotation,
            ),
        )
        _say(f"[원장] 평가 기록 append — {ledger_path}")

    m = report.matrix
    conf = args.confidence
    gates = [
        _check_gate("검출률(recall)", m.recall_lower(conf), args.min_recall_lower, upper=False),
        _check_gate(
            "정밀도(precision)", m.precision_lower(conf), args.min_precision_lower, upper=False
        ),
        _check_gate("FN율", m.fn_rate_upper(conf), args.max_fn_upper, upper=True),
        _check_gate("오검출률", m.false_alarm_upper(conf), args.max_false_alarm_upper, upper=True),
        _check_gate("골든 적재율", report.coverage_lower, args.min_coverage, upper=False),
    ]
    failed = False
    for gate in gates:
        if gate is None:
            continue
        ok, message = gate
        _say(message)
        failed = failed or not ok
    if failed:
        return _EXIT_MEASUREMENT_FAIL
    return _EXIT_OK


def _report_payload(report: MatrixReport) -> dict[str, Any]:
    """JSON 산출 — 리포트의 판정치를 기계가 읽을 수 있게(EOS-61 스코어카드 입력)."""
    m = report.matrix
    return {
        "golden": {
            "version": report.golden_version,
            "digest": report.golden_digest,
            "rotation": report.rotation,
            "frozen_at": report.frozen_at.isoformat(),
            "subject_id": report.subject_id,
            "total": report.golden_total,
        },
        "engine_revision": report.engine_revision,
        "confidence": report.confidence,
        "matrix": {"tp": m.tp, "fn": m.fn, "fp": m.fp, "tn": m.tn},
        "coverage": {
            "evaluated": m.evaluated,
            "rate": report.coverage_rate,
            "wilson_lower": report.coverage_lower,
            "unevaluated": len(report.unevaluated),
            "extraneous_predictions": len(report.extraneous_predictions),
        },
        "metrics": {
            "recall_lower": m.recall_lower(report.confidence),
            "precision_lower": m.precision_lower(report.confidence),
            "fn_rate_upper": m.fn_rate_upper(report.confidence),
            "false_alarm_upper": m.false_alarm_upper(report.confidence),
        },
        "fn_by_failure_code": dict(report.fn_by_failure_code),
        "golden_by_failure_code": dict(report.golden_by_failure_code),
        "by_anchor": [
            {
                "anchor_id": row.anchor_id,
                "tp": row.matrix.tp,
                "fn": row.matrix.fn,
                "fp": row.matrix.fp,
                "tn": row.matrix.tn,
                "unevaluated": row.unevaluated,
                "fn_rate_upper": row.matrix.fn_rate_upper(report.confidence),
            }
            for row in report.by_anchor
        ],
        "ledger_enforced": report.ledger_enforced,
        "parse_errors": list(report.parse_errors),
    }


if __name__ == "__main__":  # pragma: no cover - CLI 진입점
    sys.exit(main())
