"""Phase 3 지표 7종 일괄 CLI — 한 명령으로 산출하고 위반 주입 반응을 스스로 증명한다 (P3-14).

계약 정본: `docs/standards/phase3_metrics_contract.md`(전 평면 구분표 · 7종 정의/출처/흡수 근거 ·
현재 상태 · 목표 미확정 · 지시문과 저장소의 불일치 기록).

────────────────────────────────────────────────────────────────────────────
평면 — 이 7종은 '제품 완성도 평면'이다 (acceptance ③)
────────────────────────────────────────────────────────────────────────────
이 저장소에는 이미 지표 묶음이 여럿 있다. 분모가 서로 다르므로 **합산·평균하지 않는다**(붕괴 연쇄
④ "truth source가 하나가 아님"). 이 CLI의 7종은 아래 한 줄이 정의다.

  제품 완성도 평면 (Phase 3 Math EOS 대표 과정) — 대표 과정(`scope_spec.yaml`)이 얼마나 채워졌나.
  ≠ 생산 공정 평면 (KPI 12종 · `ops/validation_scorecard.py`) — 콘텐츠를 얼마나 싸고
    정확하게 만드나.
  ≠ Phase 2 루프 KPI 5종(`ops/loop_kpi_gate.py`) · Phase 1 구조 지표 5종
    (`ops/phase1_structure_report.py`) · 주간 기술 KPI 6종(`ops/weekly_metrics_report.py`).

이름 충돌 주의: `harness/objective_coverage.py`(CUR-02)도 "coverage"를 말하지만 분모가 성취기준
895건이다. 여기 `Curriculum Coverage` 는 **대표 과정 10노드**가 분모이며 출력에 범위를 박는다.

────────────────────────────────────────────────────────────────────────────
7종 — 출처와 흡수 (중복 정의를 새로 만들지 않는다 · acceptance ④)
────────────────────────────────────────────────────────────────────────────
  ① Curriculum Coverage        `l1.standards.phase3_coverage` (P3-02) 재사용
  ② Concept Completeness       같은 모듈 재사용 — 필드 채움이 아니라 5연결 재설계본(아래 ARCH-43 절)
  ③ Problem Coverage           **신규 계산** — 대표 과정 스킬 중 승인 문항이 1건 이상인 스킬의 비율
  ④ Solution QA Pass           `harness.corpus_reverify` 재검증 + 임계는 스코어카드에서 흡수
  ⑤ Learning Loop Success      `ops.loop_kpi_gate` 의 LOOP_COMPLETION **그대로**(새 정의 없음)
  ⑥ Critical Defect            `ops.validation_scorecard.evaluate_hard_gates` 의 F-Ⅰ~Ⅴ **그대로**
  ⑦ Graph Connectivity Coverage  P3-02 재사용 — 목표는 명세가 null 이면 '목표 미정'(판정 없음)

③의 목표값은 명세 `problem_coverage_by_skill` 에서 **읽는다**(하드코딩 금지). ④의 임계 0.995 는
스코어카드의 `KpiThreshold("ceiling", 0.005)` 를 import 해 `1 - ceiling` 으로 **흡수**한다(수치 복제
금지 — 스코어카드가 바뀌면 이쪽이 따라 움직인다). 단 ④와 스코어카드의 모집단은 다르다: 스코어카드는
골든 항목의 FN(독립 모델 심판 전수), 여기는 대표 과정 승인 문항의 **SymPy 재검증 통과율**이다.

────────────────────────────────────────────────────────────────────────────
Concept Completeness 를 필드 채움으로 만들지 않은 이유 (acceptance ⑤)
────────────────────────────────────────────────────────────────────────────
원 문서 정의("Prerequisite·Misconception·Solution·Hint·Pedagogy가 모두 연결된 비율")를 필드가 비어
있지 않은지로 구현하면 반증력이 0이다. 재설계 근거와 연결 5종의 정의는 **P3-02 가 이미 기록했다** —
`l1/standards/phase3_coverage.py` 모듈 docstring 「Concept Completeness 를 '필드 채움 검사'로 만들지
않은 이유」. 여기서는 그 정의를 다시 쓰지 않고 그 계산을 그대로 쓴다.
정직 단서: 필드 채움 검사를 기각한 선례(ARCH-43)의 대상은 Subject Contract 15필드의 **과목 중립성
검사**이지 Concept Completeness 가 아니다. 이 모듈의 인용은 같은 결함 구조(임의 문자열을 받는
필드는 성공/실패 양쪽에서 같은 값을 낸다)에 대한 **유추 적용**이며, ARCH-43 이 이 지표를 직접
기각한 것은 아니다.

────────────────────────────────────────────────────────────────────────────
상태와 종합 — 모른다 ≠ 아니다 · 종합 점수를 만들지 않는다
────────────────────────────────────────────────────────────────────────────
지표 1종의 상태는 셋이다.
  measured    잰 값·목표·충족 여부가 있다(충족/미달).
  unmeasured  잴 수 없었다(사유·예외 타입명 동반). **0도 100%도 아니다.**
  no_target   값은 잰 가치가 있으나 명세에 목표가 없다 → PASS/FAIL 을 만들지 않는다.

종합 판정(점수 합산·평균 금지 — 12종과 동일 규율). 한 줄 규칙: **하나라도 unmeasured 이면
'측정 실패'**(지시문 규칙). 오늘의 실 상태에서 측정 실패가 정상 동작이다(⑤ DB 부재·
⑥ 입력 payload 부재 — 결함으로 오인하지 말 것).

  exit 0  7종 전부 측정됐고 전부 충족.
  exit 1  7종 전부 측정됐으나 1종 이상 미달(위반).
  exit 2  1종 이상 측정 실패(미측정), 또는 미측정은 없으나 목표 미정 지표가 있어 종합을 못 낸다.
          **미측정이 위반보다 먼저다** — 구멍 난 7종은 '미달'이기 전에 '아직 말할 수 없음'이다.
          (loop_kpi_gate 는 위반을 우선한다. 거기는 독립 5종이고 여기는 한 묶음의 완결성이 전제다.)
          위반이 함께 있어도 출력·JSON 에 지표별로 전부 남는다.
  exit 3  실행 오류(인자·파일 I/O·계약 위반 입력). DB 접속 실패는 3이 아니라 ⑤의 미측정이다.

`--json PATH` 는 loop_kpi_gate 와 같은 형태다: 사람이 읽는 표는 stdout, 기계 판독 JSON 은 파일로
(boolean stdout 플래그면 두 산출을 동시에 못 낸다 — P3-02 의 `--json` 과 다른 점).

────────────────────────────────────────────────────────────────────────────
위반 주입 반응 검증 (acceptance ②) — 전 항목 초록은 증거가 아니다
────────────────────────────────────────────────────────────────────────────
`--self-check` 는 합성 대조 세계(7종 전부 충족)에서 지표마다 위반을 하나씩 주입해 **그 지표만**
미달로 바뀌는지 확인하고, 미측정 주입이 통과로 접히지 않는지, 판정 경계(값 == 목표는 충족)와
종합 규칙이 맞는지 확인한다. 하나라도 무반응이면 exit 1. DB·LLM·네트워크 0 이다(SymPy 만
쓴다). 주입은 **적용 자체를 단언**한다(변경 전후가 같으면 정상 세계로 검사가 돈 것이다 —
`InjectionNotAppliedError`).
실 코퍼스는 ②⑦ 이 0 이라 하락을 보일 수 없으므로 합성 세계가 필수다. 단위 테스트는
`tests/backend/ops/test_phase3_metrics.py`, CI 배선은 `backend` 잡 게이트 스텝 + `tests/infra`
배선 동결 테스트가 소유한다.

────────────────────────────────────────────────────────────────────────────
사용
────────────────────────────────────────────────────────────────────────────
    python -m whymath_backend.ops.phase3_metrics                       # 실 코퍼스 + DB(⑤)
    python -m whymath_backend.ops.phase3_metrics --no-db --json out/p3_metrics.json
    python -m whymath_backend.ops.phase3_metrics --self-check          # CI 게이트(결정론)
    # 숫자 주입(측정이 아니다 — 표본 기준을 반드시 명시해야 한다):
    python -m whymath_backend.ops.phase3_metrics --no-db --sample-basis synthetic \\
        --input loop.json --hard-gate-input scorecard_payload.json

한계(정직 표기)
--------------
· 목표 수치(95%·98%·99%)는 원 문서의 **목표 예시**다. P3-02·P3-10 실측 기준선을 본 뒤
  Kiki 가 확정한다.
· ④는 정답 재검증 통과율이다 — 해설의 질·교수학적 타당성은 보지 않는다. skip(재검증 불가)은 통과로
  세지 않고 '검증 불가 비율'로 따로 낸다. 검증 가능한 문항이 하나도 없으면 측정 실패다.
· ⑥은 생산 공정 평면의 Hard Gate 를 흡수한 것이다. F-Ⅰ·Ⅲ·Ⅳ 는 생산 공정(HIT·실패 분포·앵커) 신호이고
  제품 완성도 의미에 가까운 것은 F-Ⅱ·Ⅴ 뿐이다 — 지시문의 'P0/P1 결함' 출처는 저장소에 심각도 필드가
  없어 채택하지 않았다(문서 §불일치 기록 · Kiki 확인 사항).
· 이 CLI 는 ⑥의 입력 payload 수집기를 갖지 않는다(`--hard-gate-input` 으로 받는다).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Final, NoReturn

from whymath_backend.db.session import dispose_engine, get_sessionmaker
from whymath_backend.harness.corpus_reverify import ReverifyReport, reverify_corpus
from whymath_backend.l1.standards import phase3_coverage as p3c
from whymath_backend.l1.standards.phase3_scope import (
    CurriculumNode,
    ReferenceIndex,
    ScopeSpec,
    ScopeSpecError,
    Target,
    default_spec_path,
    load_reference_index,
    load_scope_spec,
    verify_spec,
)
from whymath_backend.ops import loop_kpi_gate as lkg
from whymath_backend.ops.validation_scorecard import (
    CONTENT_KPI_THRESHOLDS,
    HardGateResult,
    evaluate_hard_gates,
)

__all__ = [
    "BASIS_INJECTED",
    "BASIS_MEASURED",
    "EXIT_ALL_MET",
    "EXIT_RUNTIME_ERROR",
    "EXIT_UNMEASURED",
    "EXIT_VIOLATION",
    "METRIC_ORDER",
    "VIOLATION_INJECTIONS",
    "UNMEASURED_INJECTIONS",
    "Bundle",
    "Composite",
    "Injection",
    "InjectionNotAppliedError",
    "MetricKey",
    "MetricOutcome",
    "MetricState",
    "MetricsConfigError",
    "MetricsReport",
    "SelfCheckResult",
    "Unit",
    "World",
    "WorldFailure",
    "build_control_bundle",
    "compose",
    "evaluate_all",
    "evaluate_bundle",
    "exit_code_of",
    "judge_ratio",
    "load_world",
    "main",
    "render",
    "run_self_check",
    "solution_qa_target",
]

EXIT_ALL_MET: Final = 0
EXIT_VIOLATION: Final = 1
EXIT_UNMEASURED: Final = 2
EXIT_RUNTIME_ERROR: Final = 3

#: 이 7종이 속한 평면 — 출력 헤더·JSON 에 박는다(정본이 셋이 되지 않게 이름으로 구분).
PLANE_NAME: Final = "제품 완성도 평면 (Phase 3 Math EOS 대표 과정)"
OTHER_PLANE_NAME: Final = "생산 공정 평면 (KPI 12종 · ops.validation_scorecard)"

BASIS_MEASURED: Final = "measured"
BASIS_INJECTED: Final = "injected"

DEFAULT_WINDOW_HOURS: Final = 24
DEFAULT_TIMEOUT_SECONDS: Final = 30.0

#: 문항 코퍼스 glob — `phase3_coverage._PROBLEM_GLOB` 와 같아야 한다(거버넌스 테스트가 동결).
#: 공개 함수가 원본 행(verify 재료)을 돌려주지 않아 같은 위치를 한 번 더 읽는다.
_PROBLEM_GLOB: Final = "data/corpus/problem_bank_*/problems.jsonl"

#: 스코어카드 임계 표에서 ④가 흡수하는 항목의 이름 접두 — 긴 문언 전체를 복제하지 않는다.
_MATH_ERROR_KPI_PREFIX: Final = "수학적 오류율"

#: ③이 읽는 명세 목표 키(명세는 `problem_coverage_by_skill` 로 부른다).
_SPEC_TARGET_KEY_PROBLEM: Final = "problem_coverage_by_skill"

#: `--self-check` 가 시계에 의존하지 않도록 고정한 관측창.
_SELF_CHECK_WINDOW: Final = lkg.ObservationWindow(
    start=datetime(2026, 1, 1, tzinfo=UTC), end=datetime(2026, 1, 2, tzinfo=UTC)
)

#: 자가 점검의 가설 목표 — 실제 명세의 ⑦ 목표는 null 이다. 반응을 보려면 목표가 있어야 해서
#: **합성 세계 안에서만** 둔다(권고값이 아니다 — 목표 확정은 Kiki 몫).
_SELF_CHECK_HYPOTHETICAL_GRAPH_TARGET: Final = 0.95


class MetricsConfigError(RuntimeError):
    """명세·스코어카드 등 입력 계약이 이 모듈의 가정과 어긋났다 — 조용히 넘기지 않고 던진다."""


class InjectionNotAppliedError(AssertionError):
    """위반 주입이 세계를 바꾸지 못했다 — 정상 세계로 검사가 돈 것이므로 초록이 검출처럼 보인다."""


# ──────────────────────────────────────────────────────────────────────────
# 지표 식별·결과 모델
# ──────────────────────────────────────────────────────────────────────────
class MetricKey(str, Enum):
    """7종의 식별자 — 값은 JSON 키이자 문서의 이름이다. 선언 순서가 출력 순서(①~⑦)다."""

    CURRICULUM_COVERAGE = "curriculum_coverage"
    CONCEPT_COMPLETENESS = "concept_completeness"
    PROBLEM_COVERAGE = "problem_coverage"
    SOLUTION_QA_PASS = "solution_qa_pass"
    LEARNING_LOOP_SUCCESS = "learning_loop_success"
    CRITICAL_DEFECT = "critical_defect"
    GRAPH_CONNECTIVITY = "graph_connectivity_coverage"


METRIC_ORDER: Final[tuple[MetricKey, ...]] = tuple(MetricKey)

_DISPLAY_NAME: Final[Mapping[MetricKey, str]] = {
    MetricKey.CURRICULUM_COVERAGE: "Curriculum Coverage",
    MetricKey.CONCEPT_COMPLETENESS: "Concept Completeness",
    MetricKey.PROBLEM_COVERAGE: "Problem Coverage",
    MetricKey.SOLUTION_QA_PASS: "Solution QA Pass",
    MetricKey.LEARNING_LOOP_SUCCESS: "Learning Loop Success",
    MetricKey.CRITICAL_DEFECT: "Critical Defect",
    MetricKey.GRAPH_CONNECTIVITY: "Graph Connectivity Coverage",
}

_SOURCE: Final[Mapping[MetricKey, str]] = {
    MetricKey.CURRICULUM_COVERAGE: "l1.standards.phase3_coverage (P3-02)",
    MetricKey.CONCEPT_COMPLETENESS: "l1.standards.phase3_coverage (P3-02 · 5연결 재설계본)",
    MetricKey.PROBLEM_COVERAGE: "신규 계산 (명세 skills × 승인 문항 × 문제유형 스킬)",
    MetricKey.SOLUTION_QA_PASS: "harness.corpus_reverify + ops.validation_scorecard 임계 흡수",
    MetricKey.LEARNING_LOOP_SUCCESS: "ops.loop_kpi_gate LOOP_COMPLETION (재사용)",
    MetricKey.CRITICAL_DEFECT: "ops.validation_scorecard.evaluate_hard_gates F-Ⅰ~Ⅴ (흡수)",
    MetricKey.GRAPH_CONNECTIVITY: "l1.standards.phase3_coverage (P3-02)",
}


class MetricState(str, Enum):
    """지표 1종의 상태 — `unmeasured`·`no_target` 이 독립 상태인 것이 이 모듈의 존재 이유다."""

    MEASURED = "measured"
    UNMEASURED = "unmeasured"
    NO_TARGET = "no_target"


class Unit(str, Enum):
    RATIO = "ratio"
    COUNT = "count"


@dataclass(frozen=True)
class MetricOutcome:
    """지표 1종의 결과. 상태별 불변식을 생성 시점에 강제한다(잘못된 조합은 만들어지지 않는다)."""

    key: MetricKey
    state: MetricState
    scope: str
    reason: str
    source: str
    unit: Unit = Unit.RATIO
    value: float | None = None
    target: float | None = None
    met: bool | None = None
    numerator: int | None = None
    denominator: int | None = None
    error_type: str | None = None
    basis: str = BASIS_MEASURED
    facts: tuple[tuple[str, str], ...] = ()
    unmet: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.state is MetricState.MEASURED:
            if self.value is None or self.target is None or not isinstance(self.met, bool):
                raise ValueError(
                    f"{self.key.value}: measured 는 값·목표·충족 여부가 모두 있어야 한다"
                )
        elif self.state is MetricState.NO_TARGET:
            if self.value is None or self.target is not None or self.met is not None:
                raise ValueError(
                    f"{self.key.value}: no_target 은 값만 있고 목표·판정은 없어야 한다"
                )
        else:
            if self.value is not None or self.met is not None:
                raise ValueError(f"{self.key.value}: unmeasured 는 값·판정을 가질 수 없다")

    @property
    def name(self) -> str:
        return _DISPLAY_NAME[self.key]

    @property
    def is_violation(self) -> bool:
        return self.state is MetricState.MEASURED and self.met is False


def judge_ratio(value: float, target: float) -> bool:
    """비율 충족 판정 — 값이 목표와 **같으면 충족**이다(경계 포함). 점추정 비교다(전수 계수)."""
    return value >= target


def _unmeasured(
    key: MetricKey,
    scope: str,
    reason: str,
    *,
    error_type: str | None = None,
    basis: str = BASIS_MEASURED,
    unit: Unit = Unit.RATIO,
    numerator: int | None = None,
    denominator: int | None = None,
    facts: tuple[tuple[str, str], ...] = (),
) -> MetricOutcome:
    return MetricOutcome(
        key=key,
        state=MetricState.UNMEASURED,
        scope=scope,
        reason=reason,
        source=_SOURCE[key],
        unit=unit,
        numerator=numerator,
        denominator=denominator,
        error_type=error_type,
        basis=basis,
        facts=facts,
    )


def _ratio_outcome(
    key: MetricKey,
    scope: str,
    *,
    numerator: int,
    denominator: int,
    target: float | None,
    no_target_reason: str | None,
    reason: str,
    facts: tuple[tuple[str, str], ...] = (),
    unmet: tuple[str, ...] = (),
) -> MetricOutcome:
    """분자/분모 → 3상태 결과. 분모 0 은 측정 불가이고 목표가 없으면 판정하지 않는다."""
    if denominator <= 0:
        return _unmeasured(
            key,
            scope,
            f"분모가 0 이다 — 측정 불가(통과가 아니다). {reason}",
            numerator=numerator,
            denominator=denominator,
            facts=facts,
        )
    value = numerator / denominator
    if target is None:
        return MetricOutcome(
            key=key,
            state=MetricState.NO_TARGET,
            scope=scope,
            reason=f"{reason} / 목표 미정: {no_target_reason or '명세에 목표가 없다'}",
            source=_SOURCE[key],
            value=value,
            numerator=numerator,
            denominator=denominator,
            facts=facts,
            unmet=unmet,
        )
    return MetricOutcome(
        key=key,
        state=MetricState.MEASURED,
        scope=scope,
        reason=reason,
        source=_SOURCE[key],
        value=value,
        target=target,
        met=judge_ratio(value, target),
        numerator=numerator,
        denominator=denominator,
        facts=facts,
        unmet=unmet,
    )


# ──────────────────────────────────────────────────────────────────────────
# 종합 — 점수를 만들지 않는다. 미측정이 위반보다 먼저다
# ──────────────────────────────────────────────────────────────────────────
class Composite(str, Enum):
    ALL_MET = "all_met"
    VIOLATION = "violation"
    MEASUREMENT_FAILED = "measurement_failed"
    TARGET_PENDING = "target_pending"


def compose(outcomes: Sequence[MetricOutcome]) -> Composite:
    """7종 → 종합. 7종이 정확히 한 번씩 있지 않으면 그 자체가 측정 실패다(빈 입력 ≠ 통과)."""
    keys = [o.key for o in outcomes]
    if len(keys) != len(METRIC_ORDER) or set(keys) != set(METRIC_ORDER):
        return Composite.MEASUREMENT_FAILED
    if any(o.state is MetricState.UNMEASURED for o in outcomes):
        return Composite.MEASUREMENT_FAILED
    if any(o.is_violation for o in outcomes):
        return Composite.VIOLATION
    if any(o.state is MetricState.NO_TARGET for o in outcomes):
        return Composite.TARGET_PENDING
    return Composite.ALL_MET


_COMPOSITE_EXIT: Final[Mapping[Composite, int]] = {
    Composite.ALL_MET: EXIT_ALL_MET,
    Composite.VIOLATION: EXIT_VIOLATION,
    Composite.MEASUREMENT_FAILED: EXIT_UNMEASURED,
    Composite.TARGET_PENDING: EXIT_UNMEASURED,
}


def exit_code_of(composite: Composite) -> int:
    return _COMPOSITE_EXIT[composite]


# ──────────────────────────────────────────────────────────────────────────
# 세계 적재 — 명세·코퍼스. 실패는 예외가 아니라 값(WorldFailure)으로 운반한다
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class World:
    """대표 과정 측정 입력 묶음 — ①②③④⑦ 이 읽는다. 합성 세계도 같은 타입이다."""

    spec: ScopeSpec
    index: ReferenceIndex
    corpus: p3c.CoverageCorpus
    qa_records: tuple[dict[str, object], ...]
    """④ 재검증 대상 원본 행 — 승인 ∧ 범위 개념 PRIMARY 문항의 raw 레코드(verify 재료 포함)."""

    qa_expected: int
    """④ 모집단 크기(= 적격 문항 수). `len(qa_records)` 와 다르면 ④는 측정 실패다."""


@dataclass(frozen=True)
class WorldFailure:
    """명세·코퍼스를 읽지 못했다 — 해당 지표들은 측정 실패다(0 도 통과도 아니다)."""

    stage: str
    error_type: str
    reason: str
    spec: ScopeSpec | None = None


def _repo_root() -> Path:
    # ops/phase3_metrics.py → ops → whymath_backend → backend → src → 레포 루트(parents[4]).
    return Path(__file__).resolve().parents[4]


def _load_qa_records(root: Path, eligible_ids: frozenset[str]) -> tuple[dict[str, object], ...]:
    """적격 문항의 원본 행을 문제은행에서 읽는다. 읽기 실패·파싱 실패는 예외(침묵 금지)."""
    found: list[dict[str, object]] = []
    for path in sorted(root.glob(_PROBLEM_GLOB)):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise p3c.CoverageError(
                    f"문항 코퍼스 {number}행 파싱 실패 ({path}): {type(exc).__name__}"
                ) from exc
            if isinstance(row, dict) and row.get("problem_id") in eligible_ids:
                found.append(row)
    return tuple(found)


def load_world(
    spec_path: Path | None = None, repo_root: Path | None = None
) -> World | WorldFailure:
    """명세 → 참조 색인 → 명세 무결성 → 코퍼스 → ④ 원본 행. 어느 단계든 실패하면 `WorldFailure`."""
    root = repo_root or _repo_root()
    spec: ScopeSpec | None = None
    stage = "spec"
    try:
        spec = load_scope_spec(spec_path or default_spec_path())
        stage = "reference_index"
        index = load_reference_index(spec, root)
        stage = "verify_spec"
        violations = verify_spec(spec, index)
        if violations:
            # 분모(명세)가 오염된 상태에서 잰 수치는 의미가 없다 — P3-02 와 같이 측정을 거부한다.
            return WorldFailure(
                stage,
                "ScopeSpecViolation",
                "범위 명세가 코퍼스와 어긋나 있다 — 분모를 신뢰할 수 없어 측정을 거부한다: "
                + " | ".join(violations[:5]),
                spec,
            )
        stage = "corpus"
        corpus = p3c.load_corpus(spec, root)
        stage = "qa_records"
        eligible = [p for p in corpus.problems if p.review_status == p3c.PROBLEM_ELIGIBLE_STATUS]
        records = _load_qa_records(root, frozenset(p.problem_id for p in eligible))
    except (ScopeSpecError, p3c.CoverageError, OSError, ValueError, KeyError) as exc:
        return WorldFailure(stage, type(exc).__name__, str(exc), spec)
    return World(
        spec=spec, index=index, corpus=corpus, qa_records=records, qa_expected=len(eligible)
    )


# ──────────────────────────────────────────────────────────────────────────
# 지표 계산 — ①②⑦ (P3-02 재사용) · ③ (신규) · ④ (재검증)
# ──────────────────────────────────────────────────────────────────────────
def _spec_target(spec: ScopeSpec, key: str) -> Target:
    """명세 목표. 키가 **없으면** 던진다(null 과 부재는 다르다 — 부재는 명세 구조 결함)."""
    target = spec.targets.get(key)
    if target is None:
        raise MetricsConfigError(f"명세 targets 에 {key!r} 가 없다 — 지표의 목표를 알 수 없다")
    return target


def _scope_nodes(spec: ScopeSpec | None) -> str:
    return "대표 과정 노드" if spec is None else f"대표 과정 {len(spec.nodes)}노드"


def _scope_concepts(spec: ScopeSpec | None) -> str:
    if spec is None:
        return "대표 과정 핵심 개념"
    return f"대표 과정 핵심 개념 {len(spec.core_concepts)}개"


def _unmet_lines(result: p3c.MetricResult) -> tuple[str, ...]:
    return tuple(f"{u.subject}: {' / '.join(u.missing)}" for u in result.unmet)


def _from_p3c_metric(
    key: MetricKey, scope: str, result: p3c.MetricResult, spec: ScopeSpec, spec_key: str
) -> MetricOutcome:
    """P3-02 의 비율 지표 1종 → 3상태 결과(①⑦ 공용). 충족 판정은 이 모듈의 `judge_ratio` 가 한다."""
    target = _spec_target(spec, spec_key)
    return _ratio_outcome(
        key,
        scope,
        numerator=result.met_count,
        denominator=result.population,
        target=result.target,
        no_target_reason=target.reason,
        reason=result.note or "",
        unmet=_unmet_lines(result),
    )


def _completeness_outcome(report: p3c.CoverageReport, spec: ScopeSpec, scope: str) -> MetricOutcome:
    """② — 측정 불가 연결(힌트 등)이 남은 개념은 '충족도 미달도 아닌' 구간으로 다룬다.

    c = 연결 5종이 전부 linked 인 개념(확정 충족) · p = 'missing' 연결이 없는 개념(최대 가능).
    c/n >= 목표 → 충족 확정 · p/n < 목표 → 미달 확정 · 그 사이 → 측정 불가(모른다 ≠ 아니다).
    """
    key = MetricKey.CONCEPT_COMPLETENESS
    result = report.metric("concept_completeness")
    target = _spec_target(spec, "concept_completeness")
    n = result.population
    c = result.met_count
    possible = max(report.completeness_measurable[0], c)
    names = tuple(name for name, cnt in report.link_counts.items() if cnt["unmeasured"] > 0)
    facts = (
        ("완전 연결 확정", f"{c}/{n}"),
        ("미달이 확정되지 않은 개념(측정 불가 연결만 남음)", f"{possible - c}/{n}"),
        ("측정 불가 연결", ", ".join(names) or "없음"),
    )
    note = result.note or ""
    if n > 0 and target.value is not None and possible > c:
        if judge_ratio(c / n, target.value):
            note += " 측정 불가 연결이 있으나 확정 충족분만으로 목표를 충족한다."
        elif not judge_ratio(possible / n, target.value):
            note += (
                f" 측정 불가 연결이 전부 충족돼도 상한 {possible}/{n} 이 목표 미달이므로 미달 확정."
            )
        else:
            return _unmeasured(
                key,
                scope,
                f"충족 여부를 알 수 없다 — 측정 불가 연결({', '.join(names)})만 남은 개념이 "
                f"{possible - c}개 있어 값이 {c}/{n}~{possible}/{n} 구간이다"
                f"(목표 {target.value:.0%}). 측정 불가는 충족이 아니고 미달도 아니다.",
                numerator=c,
                denominator=n,
                facts=facts,
            )
    return _ratio_outcome(
        key,
        scope,
        numerator=c,
        denominator=n,
        target=target.value,
        no_target_reason=target.reason,
        reason=note,
        facts=facts,
        unmet=_unmet_lines(result),
    )


def _problem_coverage(world: World, scope: str) -> MetricOutcome:
    """③ — 명세 스킬 중 승인 문항이 1건 이상 행사하는 스킬의 비율. 목표는 명세에서 읽는다."""
    key = MetricKey.PROBLEM_COVERAGE
    spec, corpus = world.spec, world.corpus
    target = _spec_target(spec, _SPEC_TARGET_KEY_PROBLEM)
    counts: dict[str, int] = {skill: 0 for skill in spec.skills}
    for problem in corpus.problems:
        if problem.review_status != p3c.PROBLEM_ELIGIBLE_STATUS:
            continue
        skills: set[str] = set()
        for code in problem.problem_type_codes:
            skills.update(corpus.type_skills.get(code, ()))
        for skill in skills & set(counts):
            counts[skill] += 1
    covered = [s for s in spec.skills if counts[s] > 0]
    uncovered = tuple(s for s in spec.skills if counts[s] == 0)
    return _ratio_outcome(
        key,
        scope,
        numerator=len(covered),
        denominator=len(spec.skills),
        target=target.value,
        no_target_reason=target.reason,
        reason="명세 skills 중 승인 문항이 문제유형 경유로 행사하는 스킬의 비율(직접 계수).",
        facts=(("스킬별 승인 문항 수", ", ".join(f"{s}={counts[s]}" for s in spec.skills)),),
        unmet=tuple(f"{s}: 승인 문항 0건" for s in uncovered),
    )


def solution_qa_target() -> float:
    """④의 통과율 목표 — 스코어카드 `수학적 오류율` 상한(ceiling)을 흡수한 `1 - ceiling`.

    수치를 복제하지 않는다: 항목이 정확히 1개이고 방향이 ceiling 이 아니면 던진다(스코어카드 계약이
    바뀌었는데 조용히 다른 수치를 쓰는 것을 막는다).
    """
    matches = [
        threshold
        for name, threshold in CONTENT_KPI_THRESHOLDS.items()
        if name.startswith(_MATH_ERROR_KPI_PREFIX)
    ]
    if len(matches) != 1 or matches[0].direction != "ceiling":
        raise MetricsConfigError(
            f"스코어카드 임계 표에서 {_MATH_ERROR_KPI_PREFIX!r} ceiling 항목을 1개 찾지 못했다"
            f"(찾은 {len(matches)}개) — 흡수 계약이 깨졌다"
        )
    return 1.0 - matches[0].value


ReverifyFn = Callable[..., ReverifyReport]


def _solution_qa(world: World, scope: str, reverify: ReverifyFn) -> MetricOutcome:
    """④ — 승인 문항 전수 SymPy 재검증 통과율. skip 은 통과가 아니고 evaluable 0 은 측정 실패."""
    key = MetricKey.SOLUTION_QA_PASS
    try:
        target = solution_qa_target()
    except MetricsConfigError as exc:
        return _unmeasured(key, scope, str(exc), error_type=type(exc).__name__)
    if world.qa_expected <= 0 or not world.qa_records:
        return _unmeasured(
            key,
            scope,
            "재검증 대상 승인 문항이 0건이다 — 위반이 없는 것이 아니라 잰 것이 없다.",
        )
    if len(world.qa_records) != world.qa_expected:
        return _unmeasured(
            key,
            scope,
            f"재검증 모집단이 어긋났다(적격 문항 {world.qa_expected}건 vs 읽은 원본 행 "
            f"{len(world.qa_records)}건) — 같은 문항을 재검증했다고 말할 수 없다.",
        )
    try:
        report = reverify(list(world.qa_records), use_fuzz=False)
    except Exception as exc:  # noqa: BLE001 - 한 지표의 실패로 7종 전체를 잃지 않는다
        return _unmeasured(
            key,
            scope,
            f"재검증 실행 실패({type(exc).__name__}) — 판정 불가.",
            error_type=type(exc).__name__,
        )
    evaluable = report.passed + report.failed
    total = report.total
    facts = (
        ("통과/실패/검증 불가", f"{report.passed}/{report.failed}/{report.skipped}"),
        (
            "검증 불가 비율",
            f"{report.skipped}/{total}" + (f" = {report.skipped / total:.1%}" if total else ""),
        ),
        ("재검증 도구", "harness.corpus_reverify(Tier1+Tier2·fuzz 미사용)"),
        (
            "모집단 주의",
            "스코어카드 '수학적 오류율'은 골든 항목 FN(독립 모델 심판), 이 값은 대표 과정 "
            "승인 문항 SymPy 재검증 통과율 — 같은 숫자가 아니다",
        ),
    )
    if evaluable <= 0:
        return _unmeasured(
            key,
            scope,
            f"재검증 가능한 문항이 0건이다(전부 검증 불가 {report.skipped}건) — 0%도 100%도 아님",
            numerator=0,
            denominator=0,
            facts=facts,
        )
    return _ratio_outcome(
        key,
        scope,
        numerator=report.passed,
        denominator=evaluable,
        target=target,
        no_target_reason=None,
        reason="통과/(통과+실패). 검증 불가(skip)는 분모·분자에 넣지 않고 따로 낸다. 전수 계수.",
        facts=facts,
        unmet=tuple(f"{ident}: {why}" for ident, why in report.failures[:20]),
    )


EmitFn = Callable[[MetricOutcome], None]


def _noop_emit(_: MetricOutcome) -> None:
    return None


def _guarded(key: MetricKey, scope: str, compute: Callable[[], MetricOutcome]) -> MetricOutcome:
    """지표 1종의 계산 — 예외는 그 지표만 측정 실패로 만들고 타입명을 남긴다(침묵 실패 금지)."""
    try:
        return compute()
    except MetricsConfigError as exc:
        return _unmeasured(key, scope, str(exc), error_type=type(exc).__name__)
    except Exception as exc:  # noqa: BLE001 - 한 지표의 실패로 7종 전체를 잃지 않는다
        return _unmeasured(
            key,
            scope,
            f"계산 중 예외({type(exc).__name__}) — 판정 불가.",
            error_type=type(exc).__name__,
        )


def _compute_world_metrics(
    world: World | WorldFailure, reverify: ReverifyFn, emit: EmitFn
) -> dict[MetricKey, MetricOutcome]:
    """①②③④⑦ — 대표 과정 세계가 읽히면 계산하고, 못 읽었으면 전부 측정 실패다."""
    outcomes: dict[MetricKey, MetricOutcome] = {}

    def done(outcome: MetricOutcome) -> None:
        outcomes[outcome.key] = outcome
        emit(outcome)

    keys = (
        MetricKey.CURRICULUM_COVERAGE,
        MetricKey.CONCEPT_COMPLETENESS,
        MetricKey.PROBLEM_COVERAGE,
        MetricKey.SOLUTION_QA_PASS,
        MetricKey.GRAPH_CONNECTIVITY,
    )
    if isinstance(world, WorldFailure):
        for k in keys:
            done(
                _unmeasured(
                    k,
                    "대표 과정",
                    f"대표 과정 세계를 읽지 못했다({world.stage}: {world.error_type}) — "
                    f"{world.reason}",
                    error_type=world.error_type,
                )
            )
        return outcomes

    spec = world.spec
    nodes_scope = _scope_nodes(spec)
    concepts_scope = _scope_concepts(spec)
    skills_scope = f"대표 과정 스킬 {len(spec.skills)}종"
    qa_scope = f"대표 과정 승인 문항 {world.qa_expected}건 재검증"

    coverage: p3c.CoverageReport | None = None
    coverage_error: str | None = None
    coverage_error_type: str | None = None
    try:
        coverage = p3c.evaluate(spec, world.index, world.corpus)
    except Exception as exc:  # noqa: BLE001 - P3-02 계측 실패는 ①②⑦ 의 측정 실패다
        coverage_error = f"P3-02 계측 실패({type(exc).__name__}) — {exc}"
        coverage_error_type = type(exc).__name__

    def from_coverage(
        k: MetricKey, scope: str, build: Callable[[p3c.CoverageReport], MetricOutcome]
    ) -> None:
        if coverage is None:
            done(_unmeasured(k, scope, coverage_error or "", error_type=coverage_error_type))
        else:
            done(_guarded(k, scope, lambda: build(coverage)))

    from_coverage(
        MetricKey.CURRICULUM_COVERAGE,
        nodes_scope,
        lambda r: _from_p3c_metric(
            MetricKey.CURRICULUM_COVERAGE,
            nodes_scope,
            r.metric("curriculum_coverage"),
            spec,
            "curriculum_coverage",
        ),
    )
    from_coverage(
        MetricKey.CONCEPT_COMPLETENESS,
        concepts_scope,
        lambda r: _completeness_outcome(r, spec, concepts_scope),
    )
    done(
        _guarded(
            MetricKey.PROBLEM_COVERAGE,
            skills_scope,
            lambda: _problem_coverage(world, skills_scope),
        )
    )
    done(
        _guarded(
            MetricKey.SOLUTION_QA_PASS,
            qa_scope,
            lambda: _solution_qa(world, qa_scope, reverify),
        )
    )
    from_coverage(
        MetricKey.GRAPH_CONNECTIVITY,
        concepts_scope,
        lambda r: _from_p3c_metric(
            MetricKey.GRAPH_CONNECTIVITY,
            concepts_scope,
            r.metric("graph_connectivity_coverage"),
            spec,
            "graph_connectivity_coverage",
        ),
    )
    return outcomes


# ──────────────────────────────────────────────────────────────────────────
# ⑤ Learning Loop Success — loop_kpi_gate LOOP_COMPLETION 재사용
# ──────────────────────────────────────────────────────────────────────────
_LOOP_SCOPE: Final = "학습 루프(세션) · 관측창"


def _loop_outcome(
    observation: lkg.Observation | None,
    *,
    injected: bool,
    window: lkg.ObservationWindow,
    run_id: str,
    sample_basis: str,
) -> MetricOutcome:
    key = MetricKey.LEARNING_LOOP_SUCCESS
    basis = BASIS_INJECTED if injected else BASIS_MEASURED
    if observation is None:
        return _unmeasured(
            key,
            _LOOP_SCOPE,
            "관측치가 없다 — DB 수집을 하지 않았고(--no-db) 입력도 없다. 0 이 아니라 측정 불가다.",
            basis=basis,
        )
    report = lkg.evaluate(
        {lkg.LoopKpi.LOOP_COMPLETION: observation},
        window=window,
        run_id=run_id,
        sample_basis=sample_basis,
    )
    outcome = next(o for o in report.outcomes if o.kpi is lkg.LoopKpi.LOOP_COMPLETION)
    spec = lkg.spec_for(lkg.LoopKpi.LOOP_COMPLETION)
    facts: list[tuple[str, str]] = [
        ("출처", f"{outcome.source} · 좌석 {spec.seat_task}"),
        ("표본 기준", sample_basis),
    ]
    if outcome.bound is not None:
        facts.append(("Wilson 하한(판정에 쓴 값)", f"{outcome.bound:.4f}"))
    if outcome.detail:
        facts.append(
            ("보조 계수", ", ".join(f"{k}={v}" for k, v in sorted(outcome.detail.items())))
        )
    if injected:
        facts.append(("주입 경고", "--input 숫자 주입이다 — 수집기가 잰 값이 아니라 측정이 아니다"))
    if sample_basis == lkg.SAMPLE_BASIS_SYNTHETIC:
        facts.append(("합성 표본", lkg.SYNTHETIC_BASIS_NOTE))
    if outcome.verdict is lkg.KpiVerdict.unmeasured:
        return _unmeasured(
            key,
            _LOOP_SCOPE,
            outcome.reason,
            error_type=outcome.error_type,
            basis=basis,
            numerator=outcome.numerator,
            denominator=outcome.denominator,
            facts=tuple(facts),
        )
    assert outcome.observed is not None
    return MetricOutcome(
        key=key,
        state=MetricState.MEASURED,
        scope=_LOOP_SCOPE,
        reason=outcome.reason,
        source=_SOURCE[key],
        value=outcome.observed,
        target=spec.threshold,
        met=outcome.verdict is lkg.KpiVerdict.passed,
        numerator=outcome.numerator,
        denominator=outcome.denominator,
        basis=basis,
        facts=tuple(facts),
    )


# ──────────────────────────────────────────────────────────────────────────
# ⑥ Critical Defect — Hard Gate F-Ⅰ~Ⅴ 흡수
# ──────────────────────────────────────────────────────────────────────────
_DEFECT_SCOPE: Final = "Hard Gate F-Ⅰ~Ⅴ 5종"
_HARD_GATE_CODES: Final[tuple[str, ...]] = ("F-Ⅰ", "F-Ⅱ", "F-Ⅲ", "F-Ⅳ", "F-Ⅴ")


def _gate_state(gate: HardGateResult) -> str:
    if gate.triggered:
        return "해당"
    return "미해당" if gate.measurable else "판정 불가"


def _critical_defect(payload: Mapping[str, Any] | None, *, injected: bool) -> MetricOutcome:
    """⑥ — 해당(triggered) 게이트가 있으면 확정 위반, 판정 불가 게이트가 남으면 측정 실패.

    '해당 없음'과 '판정 불가'는 다르다: 입력이 없는 게이트를 해당 없음으로 접으면 0건 통과가 된다.
    """
    key = MetricKey.CRITICAL_DEFECT
    basis = BASIS_INJECTED if injected else BASIS_MEASURED
    if payload is None:
        return _unmeasured(
            key,
            _DEFECT_SCOPE,
            "입력 payload 가 없다 — Hard Gate 5종 전부 판정 불가. 이 CLI 는 payload 수집기를 갖지 "
            "않는다(--hard-gate-input). 0 이 아니라 '측정 불가'다.",
            unit=Unit.COUNT,
            basis=basis,
        )
    try:
        gates: tuple[HardGateResult, ...] = evaluate_hard_gates(dict(payload))
    except (AttributeError, TypeError, ValueError, KeyError) as exc:
        return _unmeasured(
            key,
            _DEFECT_SCOPE,
            f"Hard Gate 판정 중 입력 형식 오류({type(exc).__name__}) — 판정 불가.",
            unit=Unit.COUNT,
            error_type=type(exc).__name__,
            basis=basis,
        )
    if tuple(g.code for g in gates) != _HARD_GATE_CODES:
        return _unmeasured(
            key,
            _DEFECT_SCOPE,
            f"스코어카드가 낸 게이트가 {_HARD_GATE_CODES} 가 아니다 — 흡수 계약이 깨졌다.",
            unit=Unit.COUNT,
            basis=basis,
        )
    triggered = [g for g in gates if g.triggered]
    undecidable = [g for g in gates if not g.measurable]
    facts = tuple((g.code, f"{_gate_state(g)} · {g.observed}") for g in gates)
    unmet = tuple(f"{g.code}: {g.definition}" for g in triggered)
    if not triggered and undecidable:
        return _unmeasured(
            key,
            _DEFECT_SCOPE,
            "판정 불가 게이트가 남았다(" + ", ".join(g.code for g in undecidable) + ") — "
            "'해당 없음'과 '판정 불가'는 다르다. 0건이라고 말할 수 없다.",
            unit=Unit.COUNT,
            numerator=0,
            denominator=len(gates),
            basis=basis,
            facts=facts,
        )
    suffix = (
        f" (판정 불가 {len(undecidable)}종은 이 판정에 영향이 없다 — 해당 1종이면 확정 위반)"
        if undecidable
        else ""
    )
    return MetricOutcome(
        key=key,
        state=MetricState.MEASURED,
        scope=_DEFECT_SCOPE,
        reason=f"Hard Gate {len(triggered)}/{len(gates)}종 해당 (목표 0건){suffix}.",
        source=_SOURCE[key],
        unit=Unit.COUNT,
        value=float(len(triggered)),
        target=0.0,
        met=len(triggered) == 0,
        numerator=len(triggered),
        denominator=len(gates),
        basis=basis,
        facts=facts,
        unmet=unmet,
    )


# ──────────────────────────────────────────────────────────────────────────
# 전체 평가 · 보고서
# ──────────────────────────────────────────────────────────────────────────
def evaluate_all(
    world: World | WorldFailure,
    *,
    loop_observation: lkg.Observation | None,
    loop_injected: bool,
    defect_payload: Mapping[str, Any] | None,
    defect_injected: bool,
    window: lkg.ObservationWindow,
    run_id: str,
    sample_basis: str,
    reverify: ReverifyFn = reverify_corpus,
    emit: EmitFn = _noop_emit,
) -> tuple[MetricOutcome, ...]:
    """7종 전부를 ①~⑦ 순서로 산출한다. 어느 지표도 조용히 빠지지 않는다.

    `emit` 은 지표가 끝날 때마다 불려 호출부가 증거를 **즉시 flush** 할 수 있게 한다(④ 재검증이
    십수 초 걸리므로 마지막에 한 번 쓰면 중간에 멈출 때 전부 잃는다).
    """
    by_key = _compute_world_metrics(world, reverify, emit)
    loop = _guarded(
        MetricKey.LEARNING_LOOP_SUCCESS,
        _LOOP_SCOPE,
        lambda: _loop_outcome(
            loop_observation,
            injected=loop_injected,
            window=window,
            run_id=run_id,
            sample_basis=sample_basis,
        ),
    )
    by_key[loop.key] = loop
    emit(loop)
    defect = _guarded(
        MetricKey.CRITICAL_DEFECT,
        _DEFECT_SCOPE,
        lambda: _critical_defect(defect_payload, injected=defect_injected),
    )
    by_key[defect.key] = defect
    emit(defect)
    return tuple(by_key[k] for k in METRIC_ORDER)


@dataclass(frozen=True)
class MetricsReport:
    run_id: str
    observed_at: datetime
    sample_basis: str
    spec_id: str | None
    outcomes: tuple[MetricOutcome, ...]

    @property
    def composite(self) -> Composite:
        return compose(self.outcomes)

    @property
    def exit_code(self) -> int:
        return exit_code_of(self.composite)

    def as_dict(self) -> dict[str, Any]:
        def count(pred: Callable[[MetricOutcome], bool]) -> int:
            return sum(1 for o in self.outcomes if pred(o))

        return {
            "tool": "phase3_metrics",
            "plane": PLANE_NAME,
            "other_plane": OTHER_PLANE_NAME,
            "run_id": self.run_id,
            "observed_at": self.observed_at.isoformat(),
            "sample_basis": self.sample_basis,
            "spec_id": self.spec_id,
            "composite": self.composite.value,
            "exit_code": self.exit_code,
            "counts": {
                "total": len(self.outcomes),
                "met": count(lambda o: o.state is MetricState.MEASURED and o.met is True),
                "violation": count(lambda o: o.is_violation),
                "unmeasured": count(lambda o: o.state is MetricState.UNMEASURED),
                "no_target": count(lambda o: o.state is MetricState.NO_TARGET),
            },
            "metrics": [_outcome_dict(o) for o in self.outcomes],
        }


def _outcome_dict(o: MetricOutcome) -> dict[str, Any]:
    return {
        "key": o.key.value,
        "name": o.name,
        "scope": o.scope,
        "state": o.state.value,
        "unit": o.unit.value,
        "value": o.value,
        "target": o.target,
        "met": o.met,
        "numerator": o.numerator,
        "denominator": o.denominator,
        "basis": o.basis,
        "reason": o.reason,
        "source": o.source,
        "error_type": o.error_type,
        "facts": {label: text for label, text in o.facts},
        "unmet": list(o.unmet),
    }


_MARK: Final[Mapping[str, str]] = {
    "met": "충족",
    "violation": "미달",
    "unmeasured": "미측정",
    "no_target": "목표미정",
}


def _mark(o: MetricOutcome) -> str:
    if o.state is MetricState.UNMEASURED:
        return _MARK["unmeasured"]
    if o.state is MetricState.NO_TARGET:
        return _MARK["no_target"]
    return _MARK["met"] if o.met else _MARK["violation"]


def _value_line(o: MetricOutcome) -> str:
    if o.state is MetricState.UNMEASURED:
        part = f" (분자/분모 {o.numerator}/{o.denominator})" if o.numerator is not None else ""
        return f"측정 불가{part}"
    assert o.value is not None
    if o.unit is Unit.COUNT:
        return f"{int(o.value)}건 / {o.denominator}종" + (
            "" if o.target is None else f" (목표 {int(o.target)}건)"
        )
    ratio = f"{o.numerator}/{o.denominator} = {o.value:.1%}"
    return ratio if o.target is None else f"{ratio} (목표 ≥{o.target:.1%})"


_COMPOSITE_TEXT: Final[Mapping[Composite, str]] = {
    Composite.ALL_MET: "7종 전부 측정되고 전부 충족 → exit 0",
    Composite.VIOLATION: "7종 전부 측정됐으나 미달 있음 → exit 1",
    Composite.MEASUREMENT_FAILED: "측정 실패 — 미측정 지표가 있어 종합을 못 낸다 → exit 2",
    Composite.TARGET_PENDING: "목표 미정 지표가 있어 종합 판정을 내리지 않는다 → exit 2",
}


def render(report: MetricsReport) -> str:
    """사람이 읽는 표. 미측정·목표미정을 충족과 같은 모양으로 내지 않는다."""
    lines = [
        f"Phase 3 지표 7종 — {PLANE_NAME}",
        f"  ※ {OTHER_PLANE_NAME} 과 별개 평면이다 — 합산·평균하지 않는다",
        f"  run_id    : {report.run_id}",
        f"  관측 시각 : {report.observed_at.isoformat()}",
        f"  표본 기준 : {report.sample_basis}",
        f"  명세      : {report.spec_id or '읽지 못함'}",
        "",
    ]
    for number, o in enumerate(report.outcomes, start=1):
        lines.append(f"[{_mark(o):>4}] {number}. {o.name} [{o.scope}]")
        lines.append(f"        값/목표  : {_value_line(o)}")
        lines.append(f"        판정근거 : {o.reason}")
        if o.basis == BASIS_INJECTED:
            lines.append("        기준     : 주입값(--input) — 측정이 아니다")
        if o.error_type:
            lines.append(f"        예외타입 : {o.error_type}")
        lines.append(f"        출처     : {o.source}")
        for label, text in o.facts:
            lines.append(f"        · {label}: {text}")
        for item in o.unmet[:12]:
            lines.append(f"        - 미충족 {item}")
        if len(o.unmet) > 12:
            lines.append(f"        - … 외 {len(o.unmet) - 12}건")
        lines.append("")
    d = report.as_dict()["counts"]
    lines.append(
        f"합계: 충족 {d['met']} · 미달 {d['violation']} · 미측정 {d['unmeasured']} · "
        f"목표미정 {d['no_target']} / 전체 {d['total']}  (종합 점수 없음)"
    )
    lines.append(f"종합: {_COMPOSITE_TEXT[report.composite]}")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────
# 합성 세계 · 위반 주입 · 자가 점검 (acceptance ②)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Bundle:
    """측정 입력 전체 — 대표 과정 세계 + ⑤ 관측치 + ⑥ payload. 주입은 이 값의 변형이다."""

    world: World | WorldFailure
    loop: lkg.Observation | None
    defect_payload: Mapping[str, Any] | None


def _synthetic_world(spec: ScopeSpec, index: ReferenceIndex) -> World:
    """핵심 개념마다 연결 5종·경로·스킬·재검증 문항이 전부 성립하는 합성 코퍼스(7종 100%).

    P3-02 테스트의 `_world` 와 같은 구성이다(개념·원자·스킬·핵심 오개념은 실물, 문항·교수 목표·
    힌트만 합성). ④를 위해 문항마다 SymPy 로 재검증되는 최소 원본 행을 함께 만든다.
    """
    atom_nodes = set(index.atoms)
    edges: list[tuple[str, str]] = []
    problems: list[p3c.ProblemRef] = []
    type_skills: dict[str, tuple[str, ...]] = {}
    crosslinks: dict[str, frozenset[str]] = {}
    content: dict[str, str | None] = {}
    objectives: list[p3c.UnitObjective] = []
    records: list[dict[str, object]] = []
    for n, concept in enumerate(spec.core_concepts):
        atoms = tuple(a for a in index.crosswalk[concept.concept_id].atom_codes if a in index.atoms)
        skills = sorted(
            {s for a in atoms for s in index.atoms[a].behavior_skills if s in spec.skills}
        )
        mis_ids = [m.mis_id for m in spec.core_misconceptions if m.concept_code == concept.code]
        prerequisite = f"SYN-PRE-{n}"
        atom_nodes.add(prerequisite)
        edges.append((prerequisite, atoms[0]))
        type_skills[f"ptype.syn-{n}"] = tuple(skills)
        crosslinks[f"syn-kebab-{n}"] = frozenset(mis_ids[:1])
        problem_id = f"syn-problem-{n}"
        problems.append(
            p3c.ProblemRef(
                problem_id=problem_id,
                primary_src_ids=frozenset({concept.source_id}),
                review_status=p3c.PROBLEM_ELIGIBLE_STATUS,
                has_explanation=True,
                has_steps=True,
                problem_type_codes=(f"ptype.syn-{n}",),
                distractor_ids=(f"syn-kebab-{n}",),
            )
        )
        content[concept.source_id] = "reviewed"
        objectives.append(p3c.UnitObjective("syn-unit", "CONCEPT", frozenset({atoms[0]})))
        records.append(
            {
                "problem_id": problem_id,
                "slug": f"syn-qa-{n}",
                "answer": "2",
                "verify": {"conditions": f"x + {n} = {n + 2}", "answer_map": {"x": "2"}},
            }
        )
    corpus = p3c.CoverageCorpus(
        atom_nodes=frozenset(atom_nodes),
        prerequisite_edges=tuple(edges),
        problems=tuple(problems),
        problems_scanned=len(problems),
        type_skills=type_skills,
        crosslinks=crosslinks,
        content_status=content,
        objectives=tuple(objectives),
        full_pack_k_types=frozenset({"CONCEPT"}),
        stub_pack_k_types=frozenset(),
        hint_problem_ids=frozenset(p.problem_id for p in problems),
    )
    # ⑦ 의 가설 목표 — 실제 명세는 null 이라 반응을 볼 수 없다. 합성 세계 안에서만 둔다.
    targets = dict(spec.targets)
    targets["graph_connectivity_coverage"] = Target(
        value=_SELF_CHECK_HYPOTHETICAL_GRAPH_TARGET, reason=None
    )
    return World(
        spec=replace(spec, targets=targets),
        index=index,
        corpus=corpus,
        qa_records=tuple(records),
        qa_expected=len(records),
    )


def _control_defect_payload() -> dict[str, Any]:
    """Hard Gate 5종이 전부 '측정됨 ∧ 해당 없음'인 payload."""
    return {
        "hit": {"baseline_anchor_median_minutes": {"A3": 5.0, "A4": 6.0}},
        "content": {
            "reviewed_math_errors": 0,
            "reviewed_cu_total": 1000,
            "hint_leak_hits": 0,
            "hint_leak_sample": 100,
        },
        "failure_distribution": {"judgment_hits": 0, "rejected_total": 100},
        "anchors": {a: True for a in ("A1", "A2", "A3", "A4", "A5", "A6")},
    }


def build_control_bundle(spec: ScopeSpec, index: ReferenceIndex) -> Bundle:
    """7종 전부 충족하는 합성 대조 세계. 위반 주입의 출발점이다."""
    return Bundle(
        world=_synthetic_world(spec, index),
        loop=lkg.Observation(
            kpi=lkg.LoopKpi.LOOP_COMPLETION, numerator=200, denominator=200, source="self-check"
        ),
        defect_payload=_control_defect_payload(),
    )


def evaluate_bundle(
    bundle: Bundle, *, reverify: ReverifyFn = reverify_corpus
) -> tuple[MetricOutcome, ...]:
    return evaluate_all(
        bundle.world,
        loop_observation=bundle.loop,
        loop_injected=True,
        defect_payload=bundle.defect_payload,
        defect_injected=True,
        window=_SELF_CHECK_WINDOW,
        run_id="self-check",
        sample_basis=lkg.SAMPLE_BASIS_SYNTHETIC,
        reverify=reverify,
    )


@dataclass(frozen=True)
class Injection:
    """위반/미측정 주입 1건 — 세계가 안 바뀌면 `InjectionNotAppliedError`."""

    name: str
    key: MetricKey
    mutate: Callable[[Bundle], Bundle]
    isolated: bool = True
    """True 면 이 지표**만** 변해야 한다(나머지는 대조군과 같다). 입력이 겹치면 False."""

    def apply(self, bundle: Bundle) -> Bundle:
        mutated = self.mutate(bundle)
        if mutated == bundle:
            raise InjectionNotAppliedError(
                f"[{self.name}] 주입이 세계를 바꾸지 못했다(변경 전후가 같다)"
            )
        return mutated


def _world_of(bundle: Bundle) -> World:
    assert isinstance(bundle.world, World), "대조 세계는 World 여야 한다"
    return bundle.world


def _with_world(bundle: Bundle, **changes: Any) -> Bundle:
    return replace(bundle, world=replace(_world_of(bundle), **changes))


def _with_corpus(bundle: Bundle, **changes: Any) -> Bundle:
    world = _world_of(bundle)
    return replace(bundle, world=replace(world, corpus=replace(world.corpus, **changes)))


def _with_spec(bundle: Bundle, **changes: Any) -> Bundle:
    world = _world_of(bundle)
    return replace(bundle, world=replace(world, spec=replace(world.spec, **changes)))


def _v_curriculum(b: Bundle) -> Bundle:
    node = CurriculumNode(code="[99수00-00]", sub_domain="합성 노드(개념 없음)")
    return _with_spec(b, nodes=_world_of(b).spec.nodes + (node,))


def _v_completeness(b: Bundle) -> Bundle:
    problems = list(_world_of(b).corpus.problems)
    problems[0] = replace(problems[0], has_steps=False)
    return _with_corpus(b, problems=tuple(problems))


def _v_problem_coverage(b: Bundle) -> Bundle:
    return _with_spec(b, skills=_world_of(b).spec.skills + ("skill.synthetic-uncovered",))


def _v_solution_qa(b: Bundle) -> Bundle:
    records = [dict(r) for r in _world_of(b).qa_records]
    verify = records[0]["verify"]
    assert isinstance(verify, dict)
    records[0]["verify"] = {**verify, "answer_map": {"x": "3"}}
    return _with_world(b, qa_records=tuple(records))


def _v_loop(b: Bundle) -> Bundle:
    return replace(
        b,
        loop=lkg.Observation(
            kpi=lkg.LoopKpi.LOOP_COMPLETION, numerator=190, denominator=200, source="self-check"
        ),
    )


def _v_defect(b: Bundle) -> Bundle:
    payload = _control_defect_payload()
    payload["content"]["reviewed_math_errors"] = 50
    return replace(b, defect_payload=payload)


def _v_graph(b: Bundle) -> Bundle:
    return _with_corpus(b, crosslinks={})


VIOLATION_INJECTIONS: Final[tuple[Injection, ...]] = (
    Injection("개념 없는 교육과정 노드 추가", MetricKey.CURRICULUM_COVERAGE, _v_curriculum),
    Injection("풀이 단계 삭제", MetricKey.CONCEPT_COMPLETENESS, _v_completeness),
    Injection("승인 문항이 없는 스킬 추가", MetricKey.PROBLEM_COVERAGE, _v_problem_coverage),
    Injection("문항 정답을 오답으로 교체", MetricKey.SOLUTION_QA_PASS, _v_solution_qa),
    # 190/200: 점추정은 0.95 = 목표지만 Wilson 하한은 목표 아래다 — 점추정 판정 퇴행도 잡는다.
    Injection("루프 완주 200건 중 190건(점추정=목표)", MetricKey.LEARNING_LOOP_SUCCESS, _v_loop),
    Injection("검수 통과 CU 수학 오류 50/1000 (F-Ⅱ)", MetricKey.CRITICAL_DEFECT, _v_defect),
    Injection("오답 보기→오개념 크로스링크 삭제", MetricKey.GRAPH_CONNECTIVITY, _v_graph),
)


def _u_curriculum(b: Bundle) -> Bundle:
    return _with_spec(b, nodes=())


def _u_completeness(b: Bundle) -> Bundle:
    return _with_corpus(b, hint_problem_ids=None)


def _u_problem_coverage(b: Bundle) -> Bundle:
    return _with_spec(b, skills=())


def _u_solution_qa(b: Bundle) -> Bundle:
    return _with_world(b, qa_records=(), qa_expected=0)


def _u_loop(b: Bundle) -> Bundle:
    return replace(
        b,
        loop=lkg.Observation(
            kpi=lkg.LoopKpi.LOOP_COMPLETION, numerator=0, denominator=0, source="self-check"
        ),
    )


def _u_defect(b: Bundle) -> Bundle:
    return replace(b, defect_payload=None)


def _u_graph(b: Bundle) -> Bundle:
    world = _world_of(b)
    concepts = tuple(replace(c, core=False) for c in world.spec.concepts)
    return _with_spec(b, concepts=concepts)


UNMEASURED_INJECTIONS: Final[tuple[Injection, ...]] = (
    Injection("교육과정 노드 0건", MetricKey.CURRICULUM_COVERAGE, _u_curriculum),
    Injection("힌트 좌석 없음(측정 불가 연결)", MetricKey.CONCEPT_COMPLETENESS, _u_completeness),
    Injection("명세 스킬 0종", MetricKey.PROBLEM_COVERAGE, _u_problem_coverage, isolated=False),
    Injection("재검증 대상 0건", MetricKey.SOLUTION_QA_PASS, _u_solution_qa),
    Injection("루프 분모 0", MetricKey.LEARNING_LOOP_SUCCESS, _u_loop),
    Injection("Hard Gate payload 없음", MetricKey.CRITICAL_DEFECT, _u_defect),
    Injection("핵심 개념 0건", MetricKey.GRAPH_CONNECTIVITY, _u_graph, isolated=False),
)


@dataclass(frozen=True)
class SelfCheckResult:
    rows: tuple[tuple[str, bool, str], ...]
    """(점검 이름, 통과 여부, 상세)."""

    run_id: str = "-"
    observed_at: str = "-"
    """CLI 가 실행 시각·run_id 를 찍는다(점검 자체는 시계와 무관하게 결정론이다)."""

    @property
    def failures(self) -> tuple[tuple[str, bool, str], ...]:
        return tuple(r for r in self.rows if not r[1])

    @property
    def exit_code(self) -> int:
        return EXIT_VIOLATION if self.failures or not self.rows else EXIT_ALL_MET

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": "phase3_metrics",
            "mode": "self-check",
            "run_id": self.run_id,
            "observed_at": self.observed_at,
            "exit_code": self.exit_code,
            "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in self.rows],
        }


def _signature(o: MetricOutcome) -> tuple[Any, ...]:
    return (o.state, o.met, o.numerator, o.denominator)


def run_self_check(
    spec: ScopeSpec | None = None, index: ReferenceIndex | None = None
) -> SelfCheckResult:
    """합성 대조 세계에서 7종 각각에 위반·미측정을 주입하고 반응을 점검한다. 무반응이면 실패 행."""
    rows: list[tuple[str, bool, str]] = []
    if spec is None or index is None:
        spec = load_scope_spec(default_spec_path())
        index = load_reference_index(spec)
    control = build_control_bundle(spec, index)
    base = evaluate_bundle(control)
    base_by_key = {o.key: o for o in base}

    # ① 대조군 — 7종 전부 측정되고 충족, 종합 exit 0
    not_met = [o.key.value for o in base if not (o.state is MetricState.MEASURED and o.met)]
    rows.append(
        (
            "대조군: 7종 전부 충족",
            not not_met and compose(base) is Composite.ALL_MET,
            f"충족 아님 {not_met}" if not_met else f"종합 {compose(base).value}",
        )
    )

    # ② 위반 주입 — 그 지표만 '측정됐으나 미달'로 바뀐다
    for inj in VIOLATION_INJECTIONS:
        try:
            after = {o.key: o for o in evaluate_bundle(inj.apply(control))}
        except InjectionNotAppliedError as exc:
            rows.append((f"위반 주입 [{inj.key.value}] {inj.name}", False, str(exc)))
            continue
        target_ok = after[inj.key].is_violation
        others = [
            k.value
            for k in METRIC_ORDER
            if k is not inj.key and _signature(after[k]) != _signature(base_by_key[k])
        ]
        ok = target_ok and not others
        detail = f"{inj.key.value}={after[inj.key].state.value}/met={after[inj.key].met}"
        if others:
            detail += f" · 함께 변한 지표 {others}"
        rows.append((f"위반 주입 [{inj.key.value}] {inj.name}", ok, detail))

    # ③ 미측정 주입 — 그 지표가 측정 불가가 되고 종합이 '측정 실패'(통과로 접히지 않음)
    for inj in UNMEASURED_INJECTIONS:
        try:
            outcomes = evaluate_bundle(inj.apply(control))
        except InjectionNotAppliedError as exc:
            rows.append((f"미측정 주입 [{inj.key.value}] {inj.name}", False, str(exc)))
            continue
        after = {o.key: o for o in outcomes}
        ok = after[inj.key].state is MetricState.UNMEASURED and compose(outcomes) is (
            Composite.MEASUREMENT_FAILED
        )
        if ok and inj.isolated:
            others = [
                k.value
                for k in METRIC_ORDER
                if k is not inj.key and _signature(after[k]) != _signature(base_by_key[k])
            ]
            ok = not others
        rows.append(
            (
                f"미측정 주입 [{inj.key.value}] {inj.name}",
                ok,
                f"{inj.key.value}={after[inj.key].state.value} · 종합 {compose(outcomes).value}",
            )
        )

    # ④ 목표 미정 — 값은 내되 PASS/FAIL 을 만들지 않고 종합이 충족으로 접히지 않는다
    world = _world_of(control)
    nulled = dict(world.spec.targets)
    nulled["graph_connectivity_coverage"] = Target(value=None, reason="self-check 목표 미정")
    pending = evaluate_bundle(
        replace(control, world=replace(world, spec=replace(world.spec, targets=nulled)))
    )
    graph = next(o for o in pending if o.key is MetricKey.GRAPH_CONNECTIVITY)
    rows.append(
        (
            "목표 미정: 판정 없음 · 종합 충족 아님",
            graph.state is MetricState.NO_TARGET
            and graph.met is None
            and compose(pending) is Composite.TARGET_PENDING,
            f"graph={graph.state.value} · 종합 {compose(pending).value}",
        )
    )

    # ⑤ 판정 경계 — 값 == 목표는 충족, 목표 아래는 미달
    rows.append(
        (
            "경계: 값 == 목표는 충족 · 아래는 미달",
            judge_ratio(0.95, 0.95) is True and judge_ratio(0.9499, 0.95) is False,
            "judge_ratio(0.95,0.95) / (0.9499,0.95)",
        )
    )

    # ⑥ 종합 규칙 — 미측정+위반 혼재는 측정 실패, 7종이 아니면 측정 실패
    mixed = list(base)
    mixed[0] = replace(base[0], met=False, value=0.5)  # 위반 하나
    mixed[3] = _unmeasured(MetricKey.SOLUTION_QA_PASS, "x", "합성 미측정")
    rows.append(
        (
            "종합: 미측정이 위반보다 먼저",
            compose(mixed) is Composite.MEASUREMENT_FAILED
            and compose(base[:6]) is Composite.MEASUREMENT_FAILED
            and compose(()) is Composite.MEASUREMENT_FAILED,
            f"혼재 {compose(mixed).value} · 6종 {compose(base[:6]).value} · "
            f"빈 입력 {compose(()).value}",
        )
    )
    return SelfCheckResult(rows=tuple(rows))


def _render_self_check(result: SelfCheckResult) -> str:
    lines = [
        "Phase 3 지표 7종 — 위반 주입 반응 자가 점검 (합성 세계 · DB 0 · LLM 0)",
        f"  run_id    : {result.run_id}",
        f"  관측 시각 : {result.observed_at}",
    ]
    for name, ok, detail in result.rows:
        lines.append(f"  [{'OK' if ok else 'NG'}] {name} — {detail}")
    lines.append(
        f"판정: 점검 {len(result.rows)}건 중 실패 {len(result.failures)}건"
        f" → exit {result.exit_code}"
    )
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────
class _Parser(argparse.ArgumentParser):
    """argparse 기본 오류 종료코드(2)는 이 CLI 의 '측정 실패'와 겹친다 — 인자 오류는 3 이다."""

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        print(f"[phase3_metrics] 인자 오류: {message}", file=sys.stderr)
        raise SystemExit(EXIT_RUNTIME_ERROR)


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="python -m whymath_backend.ops.phase3_metrics",
        description="Phase 3 지표 7종 일괄 산출 — 제품 완성도 평면(대표 과정).",
    )
    parser.add_argument("--spec", type=Path, default=None, help="범위 명세 YAML 경로")
    parser.add_argument("--json", dest="json_path", default=None, help="판정 JSON 저장 경로(선택)")
    parser.add_argument(
        "--evidence", dest="evidence_path", default=None, help="단계별 증거 NDJSON 경로(선택)"
    )
    parser.add_argument(
        "--since-hours", type=float, default=float(DEFAULT_WINDOW_HOURS), help="⑤ 관측창(시간)"
    )
    parser.add_argument(
        "--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS, help="⑤ 수집 타임아웃"
    )
    parser.add_argument("--no-db", action="store_true", help="⑤ DB 수집을 건너뛴다")
    parser.add_argument("--input", dest="input_path", default=None, help="⑤ 관측치 JSON(주입)")
    parser.add_argument(
        "--hard-gate-input",
        dest="hard_gate_path",
        default=None,
        help="⑥ 스코어카드 payload JSON(주입)",
    )
    parser.add_argument(
        "--sample-basis",
        choices=lkg.SAMPLE_BASES,
        default=None,
        help="표본 성격. 숫자를 주입(--input/--hard-gate-input)할 때는 반드시 명시한다.",
    )
    parser.add_argument(
        "--self-check", action="store_true", help="합성 세계에서 7종 위반 주입 반응을 점검한다"
    )
    return parser


def _read_json_object(path: str, label: str) -> dict[str, Any] | None:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[phase3_metrics] {label} 읽기 실패: {type(exc).__name__}", file=sys.stderr)
        return None
    if not isinstance(raw, dict):
        print(f"[phase3_metrics] {label}: 최상위가 객체가 아니다", file=sys.stderr)
        return None
    return raw


async def _collect_loop_observation(
    window: lkg.ObservationWindow,
    *,
    evidence: lkg.EvidenceWriter,
    timeout_seconds: float,
) -> lkg.Observation:
    """⑤ 의 DB 수집. 접속 실패는 실행 오류가 아니라 ⑤의 미측정이다(예외 타입명 기록)."""
    key = lkg.LoopKpi.LOOP_COMPLETION
    try:
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            observed = await lkg.collect_all(
                session,
                window,
                evidence=evidence,
                timeout_seconds=timeout_seconds,
                collectors={key: lkg.collect_loop_completion},
            )
        return observed[key]
    except Exception as exc:  # noqa: BLE001 - 접속 실패로 7종 전체를 잃지 않는다
        error_type = type(exc).__name__
        evidence.record(
            kpi=None,
            phase="db_connect_error",
            ok=False,
            error_type=error_type,
            error_module=type(exc).__module__,
        )
        return lkg.Observation(
            kpi=key,
            unmeasured_reason=f"DB 세션 확보 실패({error_type}) — 판정 불가.",
            source="db_unavailable",
            error_type=error_type,
        )
    finally:
        await dispose_engine()


_SELF_CHECK_INCOMPATIBLE: Final[tuple[str, ...]] = (
    "spec",
    "evidence_path",
    "input_path",
    "hard_gate_path",
    "sample_basis",
)


def main(argv: list[str] | None = None) -> int:
    """CLI 진입. 예기치 못한 예외는 기본 종료코드 1(위반으로 오독됨) 대신 3 으로 낸다."""
    try:
        return _run(argv)
    except SystemExit as exc:  # argparse(-h → 0 · 인자 오류 → 3)의 종료를 반환값으로 바꾼다
        if exc.code is None:
            return EXIT_ALL_MET
        return exc.code if isinstance(exc.code, int) else EXIT_RUNTIME_ERROR
    except Exception as exc:  # noqa: BLE001 - 미처리 예외가 exit 1(미달)로 위장되지 않게
        print(
            f"[phase3_metrics] 예기치 못한 실행 오류: {type(exc).__name__}: {str(exc)[:200]}",
            file=sys.stderr,
        )
        return EXIT_RUNTIME_ERROR


def _run(argv: list[str] | None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.since_hours <= 0:
        print("[phase3_metrics] --since-hours 는 양수여야 한다.", file=sys.stderr)
        return EXIT_RUNTIME_ERROR

    if args.self_check:
        bad = [n for n in _SELF_CHECK_INCOMPATIBLE if getattr(args, n) is not None]
        if bad or args.no_db:
            print(
                "[phase3_metrics] --self-check 는 측정 옵션과 함께 쓸 수 없다"
                f"(받은 옵션: {bad + (['no_db'] if args.no_db else [])}). 합성 세계만 본다.",
                file=sys.stderr,
            )
            return EXIT_RUNTIME_ERROR
        try:
            result = replace(
                run_self_check(),
                run_id=uuid.uuid4().hex[:12],
                observed_at=datetime.now(UTC).isoformat(),
            )
        except (ScopeSpecError, p3c.CoverageError, OSError, ValueError, KeyError) as exc:
            print(
                f"[phase3_metrics] 자가 점검 준비 실패: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            return EXIT_RUNTIME_ERROR
        print(_render_self_check(result))
        if args.json_path:
            code = _write_json(args.json_path, result.as_dict())
            if code:
                return code
        return result.exit_code

    injecting = args.input_path is not None or args.hard_gate_path is not None
    if injecting and args.sample_basis is None:
        print(
            "[phase3_metrics] 숫자를 주입(--input/--hard-gate-input)할 때는 --sample-basis 를 "
            "명시해야 한다 — 주입은 측정이 아니며, 합성 숫자가 live 로 읽히는 것을 막는다.",
            file=sys.stderr,
        )
        return EXIT_RUNTIME_ERROR
    sample_basis: str = args.sample_basis or lkg.SAMPLE_BASIS_LIVE

    observed_at = datetime.now(UTC)
    window = lkg.ObservationWindow(
        start=observed_at - timedelta(hours=args.since_hours), end=observed_at
    )
    run_id = uuid.uuid4().hex[:12]
    try:
        evidence = lkg.EvidenceWriter(
            Path(args.evidence_path) if args.evidence_path else None, run_id=run_id, window=window
        )
    except OSError as exc:
        print(f"[phase3_metrics] 증거 경로 준비 실패: {type(exc).__name__}", file=sys.stderr)
        return EXIT_RUNTIME_ERROR
    evidence.record(
        kpi=None, phase="run_start", ok=True, no_db=bool(args.no_db), sample_basis=sample_basis
    )

    # 입력 파일은 측정 전에 전부 읽어 형식 오류를 실행 오류(3)로 먼저 낸다.
    injected_loop: lkg.Observation | None = None
    if args.input_path:
        raw = _read_json_object(args.input_path, "--input")
        if raw is None:
            evidence.record(kpi=None, phase="input_error", ok=False, error_type="InputUnreadable")
            return EXIT_RUNTIME_ERROR
        try:
            parsed = lkg.parse_input_observations(raw)
        except lkg.InputContractError as exc:
            print(f"[phase3_metrics] --input 계약 위반: {exc}", file=sys.stderr)
            evidence.record(
                kpi=None, phase="input_error", ok=False, error_type="InputContractError"
            )
            return EXIT_RUNTIME_ERROR
        extra = set(parsed) - {lkg.LoopKpi.LOOP_COMPLETION}
        if extra:
            print(
                f"[phase3_metrics] --input 은 {lkg.LoopKpi.LOOP_COMPLETION.value} 만 받는다"
                f"(받은 다른 KPI: {sorted(k.value for k in extra)}) — 무시하지 않고 거부한다.",
                file=sys.stderr,
            )
            evidence.record(kpi=None, phase="input_error", ok=False, error_type="UnsupportedKpiKey")
            return EXIT_RUNTIME_ERROR
        injected_loop = parsed.get(lkg.LoopKpi.LOOP_COMPLETION)
    defect_payload: dict[str, Any] | None = None
    if args.hard_gate_path:
        defect_payload = _read_json_object(args.hard_gate_path, "--hard-gate-input")
        if defect_payload is None:
            evidence.record(kpi=None, phase="input_error", ok=False, error_type="InputUnreadable")
            return EXIT_RUNTIME_ERROR

    world = load_world(args.spec)
    if isinstance(world, WorldFailure):
        evidence.record(
            kpi=None,
            phase="world_load_error",
            ok=False,
            error_type=world.error_type,
            stage=world.stage,
        )
    else:
        evidence.record(kpi=None, phase="world_loaded", ok=True, qa_expected=world.qa_expected)

    loop_observation = injected_loop
    if injected_loop is None and not args.no_db:
        loop_observation = asyncio.run(
            _collect_loop_observation(
                window, evidence=evidence, timeout_seconds=args.timeout_seconds
            )
        )
    evidence.record(kpi=None, phase="loop_ready", ok=loop_observation is not None)

    evidence.record(kpi=None, phase="evaluate_start", ok=True)

    def record_metric(o: MetricOutcome) -> None:
        evidence.record(
            kpi=None,
            phase="metric_done",
            ok=o.state is MetricState.MEASURED and bool(o.met),
            metric=o.key.value,
            state=o.state.value,
            error_type=o.error_type,
        )

    outcomes = evaluate_all(
        world,
        loop_observation=loop_observation,
        loop_injected=injected_loop is not None,
        defect_payload=defect_payload,
        defect_injected=defect_payload is not None,
        window=window,
        run_id=run_id,
        sample_basis=sample_basis,
        emit=record_metric,
    )
    spec_id = None
    if isinstance(world, World):
        spec_id = world.spec.spec_id
    elif world.spec is not None:
        spec_id = world.spec.spec_id
    report = MetricsReport(
        run_id=run_id,
        observed_at=observed_at,
        sample_basis=sample_basis,
        spec_id=spec_id,
        outcomes=outcomes,
    )
    print(render(report))
    if args.json_path:
        code = _write_json(args.json_path, report.as_dict())
        if code:
            return code
    evidence.record(kpi=None, phase="run_end", ok=True, exit_code=report.exit_code)
    return report.exit_code


def _write_json(path: str, payload: Mapping[str, Any]) -> int:
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except OSError as exc:
        print(f"[phase3_metrics] JSON 저장 실패: {type(exc).__name__}", file=sys.stderr)
        return EXIT_RUNTIME_ERROR
    return 0


if __name__ == "__main__":  # pragma: no cover - 엔트리포인트
    raise SystemExit(main())
