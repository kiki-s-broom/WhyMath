"""Phase 2 학습 루프 KPI 5종 게이트 — 계측되지 않는 KPI는 KPI가 아니다 (EOS-15 · 계획서 §19).

계약 정본: `docs/standards/loop_kpi_contract.md`(정본 경계·5종 정의표·CI 배선 판단 근거).

계획서 300 §19가 Phase 2의 성공을 "기능 개수"가 아니라 **학습 루프의 런타임 무결성 5축**으로
다시 정의했다. 없던 것은 그 5축의 *정의*가 아니라 그것을 숫자로 뱉고 exit code로 판정하는
**실행기**다. 이 모듈이 그것이다.

────────────────────────────────────────────────────────────────────────────
정본 경계 — 이것은 기존 KPI 12종의 확장이 아니라 **다른 축**이다 (EOS-15 acceptance ④)
────────────────────────────────────────────────────────────────────────────
이 저장소에는 이미 KPI 정본이 있다: `ops/validation_scorecard.py`의 **12종**(기술 6 + 내용 6).
그것은 **콘텐츠 생산 파이프라인**을 잰다 — CU당 인간 개입 시간·자동검증 통과율·재작업률·
처리량·단위 비용·실패 유형, 그리고 골든 벤치마크 라벨 축의 내용 품질 6종. 판정 시점은
12/31 최종 G5다.

이 모듈의 5종은 **학습 루프 런타임**을 잰다 — 학생 한 명의 Attempt가 Assessment·Mastery를
거쳐 Recommendation까지 흐르는가, 그 흐름의 상태가 서로 모순되지 않는가, 추천에 이유가
붙는가, 사람이 DB를 손으로 고치지 않고도 굴러가는가, 나온 추천을 원 문제까지 되짚을 수 있는가.

즉 **분모가 다르다**: 12종의 분모는 *생산된 콘텐츠 단위(CU)*이고, 5종의 분모는 *실행된 학습
루프*다. 같은 표에 얹으면 "KPI 17종"이라는 하나의 평균이 생기고, 그 평균은 콘텐츠 생산이
잘 되는 것으로 루프 붕괴를 덮는다(붕괴 연쇄 ④ "truth source가 하나가 아님"). 그래서
**편입하지 않고 별도 축으로 선언**하며, 그 경계를 코드가 지킨다:

  · 이 모듈은 `validation_scorecard`를 import하지 않고, 그쪽도 이쪽을 모른다.
  · 두 KPI 이름 공간이 겹치지 않음을 거버넌스 테스트가 상시 확인한다
    (`tests/backend/ops/test_loop_kpi_gate.py::test_axis_is_disjoint_from_validation_scorecard`).
  · 종합 점수를 만들지 않는다 — 5종은 각각 자기 verdict를 갖는다(평균 금지, 12종과 동일 규율).

────────────────────────────────────────────────────────────────────────────
5종 정의표 — ①분자 ②분모 ③출처 (계획서 §19 문언 → 이 저장소의 실재 테이블로 귀착)
────────────────────────────────────────────────────────────────────────────
`LOOP_KPI_SPECS`가 그 정본이고 아래는 요약이다. **임계는 전부 코드가 갖는다** — 입력(`--input`)은
관측치(분자·분모)만 낸다(자기 합격선을 써 내면 그것은 판정이 아니라 자기 신고다).

  KPI① Loop Completion Rate  (≥95%)
      분자 = 시작된 학습 루프 중 Recommendation 단계까지 도달한 수
      분모 = 관측창에 시작된 학습 루프 수
      출처 = `learning_session` × `evidence_event`(recommendation_render)
      **현행 구조적 미측정** — 아래 「분모 판정」.

  KPI② State Integrity       (불일치 ≤1%)
      분자 = 무결성 위반 행 수(7종 합)   분모 = 스캔 대상 행 수(7종 합)
      출처 = `ops/integrity_violations_gate.scan_integrity` — **재구현하지 않고 호출**한다.

  KPI③ Explainability        (reason 없는 추천 = 0 · 무관용)
      분자 = `meta.reason`이 없는 recommendation_render 건수   분모 = 그 전체 건수
      출처 = `l2/recommendation_evidence`(REC-11이 심은 `META_KEY_REASON`).

  KPI④ Manual Intervention   (운영자 DB 개입 = 0 · 무관용)
      분자 = 관측창의 운영자 감사 행 수(`privacy_audit` 중 운영자 계열 3종)
      분모 = 관측창의 정상 학습 실행 건수(`problem_attempt` 적재 수)
      출처 = `privacy_audit` × `problem_attempt`. **관측 범위는 부분이다** — 아래 「④의 사각」.

  KPI⑤ Traceability          (역추적 실패 = 0 · 무관용)
      분자 = 5홉 체인이 끊기는 recommendation 건수   분모 = recommendation 전체
      체인 = Recommendation → LearnerState → Assessment → Attempt → Problem
      출처 = `l2/learning_event_trace`의 원천 대장. **현행 구조적 미측정**(2홉 파손).

────────────────────────────────────────────────────────────────────────────
분모 판정 — KPI①의 분모는 오늘 정의되지 않는다 (EOS-15 acceptance ②)
────────────────────────────────────────────────────────────────────────────
계획서는 분모를 "시작한 학습 세션"이라고 적었는데, 이 저장소에서 그 단위는 **아무도 쓰지
않는다**. 두 사실이 겹친다:

  1. `learning_session`에 **writer가 0건**이다(조회·종료·삭제 표면만 있다).
  2. 추천은 적재되지만 `evidence_event`에 `user_id` 컬럼이 없고 `session_id`는 호출마다
     `uuid.uuid4()` placeholder다 — 즉 **분자를 분모에 붙일 조인 키가 없다**.

그래서 이 모듈은 분모를 **지어내지 않는다**. 세 선택지(①세션 writer를 배선한다 ②다른 분모로
갈아탄다 ③측정 불가를 명시한다) 중 **③을 택하되 ①이 착지하면 자동으로 측정이 시작되게**
만들었다: 구조적 선결(`_REQUIRED_SOURCES`)을 `l2/learning_event_trace`의 원천 대장에서 읽어
판정하므로, 누군가 세션 writer를 배선해 그 대장이 `PRODUCED`로 바뀌는 순간 이 KPI는 스스로
`unmeasured`를 벗는다. 사실을 여기 다시 적지 않는 이유가 그것이다 — 적으면 두 곳이 어긋난다.

②(다른 분모로 갈아타기)를 택하지 않은 이유: `problem_attempt` 건수를 분모로 쓰면 "시도마다
추천이 하나씩 나와야 한다"는, 계획서가 말한 적 없는 계약이 새로 생긴다. 그건 지표가 아니라
설계 변경이다.

────────────────────────────────────────────────────────────────────────────
④의 사각 — 우리가 볼 수 있는 개입과 볼 수 없는 개입 (정직 표기)
────────────────────────────────────────────────────────────────────────────
"운영자 DB 개입"의 관측 가능한 표면은 `privacy_audit`뿐이며, 거기에는 감사 행을 *남기는*
경로만 나타난다(`ops/role_grant_cli`·콘텐츠 CUD 라우터). **`psql`로 직접 친 UPDATE, 시드
스크립트의 직접 적재, 마이그레이션 데이터 수정은 이 표면을 지나지 않는다.** 그러므로 이
KPI가 0이라는 것은 "개입이 없었다"가 아니라 "**감사되는 표면에서는** 개입이 없었다"이다.
리포트는 이 한계를 `coverage_note`로 항상 함께 낸다 — 가리면 없는 보호를 있다고 말하는 것이
되고, 그것이 이 저장소가 반복해서 다친 부류다.

────────────────────────────────────────────────────────────────────────────
설계 규칙 6 — 어기면 계측기가 계측기가 아니게 된다
────────────────────────────────────────────────────────────────────────────
1. **미측정은 통과가 아니다.** 분모가 0이면 "위반 0건 → 100%"가 아니라 `unmeasured`다.
   `KpiVerdict`에 독립 상태로 두고 CLI가 별도 exit code(2)를 낸다.
2. **무관용 축에는 Wilson을 쓰지 않는다.** ③④⑤는 "0이어야 한다"이므로 분자>0이면 즉시
   fail이다(신뢰구간으로 1건을 통과시키지 않는다). 대신 분자=0일 때 Wilson **상한**을
   `residual_upper_bound`로 함께 낸다 — 관측 0을 확정 0으로 과신하지 않기 위해서다.
3. **비율 축은 방향까지 지표가 갖는다.** ①은 하한(≥), ②는 상한(≤)으로 판정한다. 결함율에
   하한을 쓰면 1%가 0.5% 기준을 통과한다.
4. **임계는 코드가, 관측치는 입력이.** `--input`은 분자·분모·미측정 사유만 받는다. 임계·
   방향 키가 섞여 오면 **거부**한다(자기 신고 금지).
5. **인프로세스 이중 회계.** 5종 전부 우리 PostgreSQL에서 직접 센다 — 외부 관측 SaaS
   (Langfuse 등)를 판정 경로에 두지 않는다. 그 인프라가 죽었을 때 "측정 실패"가 보여야지
   "0건 통과"로 위장되면 안 되기 때문이다. 이 불변식은 거버넌스 테스트가 동결한다.
6. **실패해도 증거가 남는다.** `--evidence`를 주면 단계마다 **즉시 flush**되는 NDJSON이
   쌓이고, 수집 실패는 **예외 타입명**과 함께 기록된다(침묵 실패 금지). 모든 줄에 `run_id`와
   관측창이 박혀 있어 *이전 실행의 증거를 이번 것으로 오독*할 수 없다.

────────────────────────────────────────────────────────────────────────────
사용
────────────────────────────────────────────────────────────────────────────
    python -m whymath_backend.ops.loop_kpi_gate --since-hours 24
    python -m whymath_backend.ops.loop_kpi_gate --json out/loop_kpi.json --evidence out/ev.ndjson
    # DB 없이 관측치만 넣어 판정(위반 주입 드릴·CI 하네스):
    python -m whymath_backend.ops.loop_kpi_gate --no-db --input observations.json

종료 코드
--------
- 0 : 5종 전부 측정됐고 전부 목표 충족.
- 1 : 1종 이상 **위반**(측정됐고 미달). 미측정이 함께 있어도 위반이 우선이다.
- 2 : 위반은 없으나 1종 이상 **미측정**. "0건 통과" 위장을 막는 자리다.
- 3 : 실행 오류(인자·파일 I/O). DB 접속 실패는 3이 아니라 *해당 KPI의 미측정*(→ 2)이다 —
      접속이 안 된다고 판정 자체가 사라지면 나머지 KPI의 결과까지 잃는다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Final

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.activity import LearningSession, ProblemAttempt
from whymath_backend.db.models.audit import PrivacyAudit
from whymath_backend.db.models.evidence_event import EvidenceEvent
from whymath_backend.db.session import dispose_engine, get_sessionmaker
from whymath_backend.harness.wilson import wilson_lower_bound, wilson_upper_bound
from whymath_backend.l2.learning_event_trace import (
    SourceAvailability,
    TraceEventType,
    source_registry,
)
from whymath_backend.l2.recommendation_evidence import (
    EVENT_TYPE_RECOMMENDATION_TREATMENT,
    META_KEY_REASON,
)
from whymath_backend.ops.integrity_violations_gate import IntegrityReport, scan_integrity
from whymath_backend.schema.enums import AuditEventKind

__all__ = [
    "CONFIDENCE",
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_WINDOW_HOURS",
    "EXIT_OK",
    "EXIT_RUNTIME_ERROR",
    "EXIT_UNMEASURED",
    "EXIT_VIOLATION",
    "OPERATOR_AUDIT_KINDS",
    "LOOP_KPI_SPECS",
    "Direction",
    "EvidenceWriter",
    "KpiOutcome",
    "KpiVerdict",
    "LoopKpi",
    "LoopKpiReport",
    "LoopKpiSpec",
    "Observation",
    "ObservationWindow",
    "blocked_preconditions",
    "collect_all",
    "collect_explainability",
    "collect_loop_completion",
    "collect_manual_intervention",
    "collect_state_integrity",
    "collect_traceability",
    "evaluate",
    "main",
    "parse_input_observations",
    "render",
    "schema_smoke_failures",
    "spec_for",
]

CONFIDENCE: Final = 0.95
DEFAULT_WINDOW_HOURS: Final = 24
DEFAULT_TIMEOUT_SECONDS: Final = 30.0

EXIT_OK: Final = 0
EXIT_VIOLATION: Final = 1
EXIT_UNMEASURED: Final = 2
EXIT_RUNTIME_ERROR: Final = 3


class LoopKpi(str, Enum):
    """계획서 §19의 5축. 값은 `--input` JSON의 키이자 리포트의 식별자다."""

    LOOP_COMPLETION = "loop_completion_rate"
    STATE_INTEGRITY = "state_integrity"
    EXPLAINABILITY = "explainability"
    MANUAL_INTERVENTION = "manual_intervention"
    TRACEABILITY = "traceability"


class KpiVerdict(str, Enum):
    """KPI 1종의 판정 — `unmeasured`가 독립 상태인 것이 이 모듈의 존재 이유다.

    2상태(pass/fail)로 접으면 "입력이 없다"가 어느 쪽으로 접히든 거짓말이 된다: `pass`면
    미측정을 통과로 위장하고, `fail`이면 재 보지도 않은 것을 미달로 낙인찍는다.
    """

    passed = "pass"
    failed = "fail"
    unmeasured = "unmeasured"


class Direction(str, Enum):
    """비율 판정 방향 — 지표가 방향을 갖지 않으면 결함율이 하한으로 통과한다."""

    AT_LEAST = ">="
    """높을수록 좋다 → Wilson **하한**이 임계 이상이어야 통과."""

    AT_MOST = "<="
    """낮을수록 좋다 → Wilson **상한**이 임계 이하여야 통과."""


@dataclass(frozen=True, slots=True)
class LoopKpiSpec:
    """KPI 1종의 계약 — 분자·분모·출처·임계·구조적 선결을 코드가 말한다.

    v1 내부 구현(수집 쿼리)은 SQL이지만 이 타입은 store에 중립이다. 행동 로그가 ClickHouse로
    가거나 세션 축이 새로 배선돼도 바뀌는 것은 `collect_*`의 내부이고, 소비자가 보는 계약
    (`Observation` → `KpiOutcome`)은 그대로다.
    """

    kpi: LoopKpi
    title: str
    """계획서 §19 문언(요약)."""

    numerator_def: str
    denominator_def: str
    source: str
    """이 관측치를 내는 모듈·테이블(import 경로 또는 테이블명)."""

    seat_task: str
    """산출 좌석의 태스크 id — 미착지분의 추적 축(만료 없는 유예 금지)."""

    threshold: float
    direction: Direction
    zero_tolerance: bool
    """True면 비율 게이트가 아니라 0-불변식이다(분자>0 즉시 fail · Wilson 미적용)."""

    coverage_note: str | None = None
    """관측 범위가 부분일 때 그 사실. 리포트에 항상 함께 실린다."""


#: KPI④가 "운영자 개입"으로 세는 감사 종류. 본인 행위(반출·동의변경)는 학생 자신의 정상
#: 사용이므로 제외한다 — 세면 정상 시나리오가 위반으로 계상된다.
OPERATOR_AUDIT_KINDS: Final[tuple[str, ...]] = (
    AuditEventKind.admin_access.value,
    AuditEventKind.role_change.value,
    AuditEventKind.content_mutation.value,
)

_COVERAGE_NOTE_MANUAL = (
    "관측 범위는 `privacy_audit`에 행을 남기는 경로뿐이다. psql 직접 UPDATE·시드 스크립트·"
    "마이그레이션 데이터 수정은 이 표면을 지나지 않으므로 0은 '개입이 없었다'가 아니라 "
    "'감사되는 표면에서는 없었다'이다."
)
_COVERAGE_NOTE_INTEGRITY = (
    "`integrity_violations_gate` 7종이 보는 느슨참조·발행포인터 축만이다. DB FK가 이미 "
    "막는 축과, 그 7종이 스캔하지 않는 테이블의 불일치는 여기 나타나지 않는다."
)

LOOP_KPI_SPECS: Final[tuple[LoopKpiSpec, ...]] = (
    LoopKpiSpec(
        kpi=LoopKpi.LOOP_COMPLETION,
        title="Loop Completion Rate — 시작한 학습 루프 중 Recommendation까지 도달한 비율",
        numerator_def="관측창에 시작된 learning_session 중 같은 session_id의 "
        "recommendation_render 증거가 관측창 안에 존재하는 세션 수",
        denominator_def="관측창에 started_at을 가진 learning_session 행 수",
        source="db.models.activity.LearningSession × db.models.evidence_event.EvidenceEvent",
        seat_task="EOS-15-loop-completion-and-manual-intervention-kpi",
        threshold=0.95,
        direction=Direction.AT_LEAST,
        zero_tolerance=False,
    ),
    LoopKpiSpec(
        kpi=LoopKpi.STATE_INTEGRITY,
        title="State Integrity — Attempt·Assessment·Mastery·Recommendation 간 불일치 <1%",
        numerator_def="integrity_violations_gate 7종이 검출한 위반 행 수의 합",
        denominator_def="같은 7종이 스캔한 대상 행 수의 합",
        source="whymath_backend.ops.integrity_violations_gate.scan_integrity",
        seat_task="OPS-55 / EOS-07 (기존 좌석 — 재구현 금지)",
        threshold=0.01,
        direction=Direction.AT_MOST,
        zero_tolerance=False,
        coverage_note=_COVERAGE_NOTE_INTEGRITY,
    ),
    LoopKpiSpec(
        kpi=LoopKpi.EXPLAINABILITY,
        title="Explainability — reason 없이 생성된 recommendation = 0",
        numerator_def="관측창의 recommendation_render 중 meta.reason이 없는 건수",
        denominator_def="관측창의 recommendation_render 전체 건수",
        source="db.models.evidence_event.EvidenceEvent(meta.reason — REC-11)",
        seat_task="REC-11 (done — 이 게이트는 그 산출을 판정만 한다)",
        threshold=0.0,
        direction=Direction.AT_MOST,
        zero_tolerance=True,
    ),
    LoopKpiSpec(
        kpi=LoopKpi.MANUAL_INTERVENTION,
        title="Manual Intervention — 정상 학습 시나리오에서 운영자 DB 개입 = 0",
        numerator_def="관측창의 privacy_audit 중 운영자 계열 "
        "3종(admin_access·role_change·content_mutation) 행 수",
        denominator_def="관측창에 적재된 problem_attempt 행 수(= 정상 학습 실행 건수)",
        source="db.models.audit.PrivacyAudit × db.models.activity.ProblemAttempt",
        seat_task="EOS-15-loop-completion-and-manual-intervention-kpi",
        threshold=0.0,
        direction=Direction.AT_MOST,
        zero_tolerance=True,
        coverage_note=_COVERAGE_NOTE_MANUAL,
    ),
    LoopKpiSpec(
        kpi=LoopKpi.TRACEABILITY,
        title="Traceability — Recommendation → LearnerState → Assessment → Attempt → Problem "
        "역추적 100%",
        numerator_def="관측창의 recommendation 중 5홉 체인이 한 군데라도 끊기는 건수",
        denominator_def="관측창의 recommendation 전체 건수",
        source="whymath_backend.l2.learning_event_trace(원천 대장) × evidence_event",
        seat_task="EOS-11 / EOS-79 (트레이스 좌석 — 이 게이트는 그 체인의 해소율을 판정한다)",
        threshold=0.0,
        direction=Direction.AT_MOST,
        zero_tolerance=True,
    ),
)

_SPEC_BY_KPI: Final[Mapping[LoopKpi, LoopKpiSpec]] = {s.kpi: s for s in LOOP_KPI_SPECS}


def spec_for(kpi: LoopKpi) -> LoopKpiSpec:
    """KPI의 계약을 돌려준다(없는 KPI는 프로그래밍 오류이므로 KeyError가 맞다)."""
    return _SPEC_BY_KPI[kpi]


# ──────────────────────────────────────────────────────────────────────────
# 구조적 선결 — 사실을 여기 다시 적지 않고 원천 대장에서 읽는다
# ──────────────────────────────────────────────────────────────────────────
#: KPI가 성립하려면 `PRODUCED`여야 하는 트레이스 원천. `l2/learning_event_trace`의
#: `_SOURCE_REGISTRY`가 그 가용성의 단일 진실 원천이며, 그쪽이 `PRODUCED`로 바뀌면 이 게이트는
#: 스스로 `unmeasured`를 벗는다(사실을 두 곳에 적지 않는다 — 붕괴 연쇄 ④).
_REQUIRED_SOURCES: Final[Mapping[LoopKpi, tuple[TraceEventType, ...]]] = {
    LoopKpi.LOOP_COMPLETION: (
        # 분모 축(세션 생성)과 분자 축(추천의 학습자 결합)이 둘 다 필요하다.
        TraceEventType.CONCEPT_SELECTED,
        TraceEventType.RECOMMENDATION_GENERATED,
    ),
    LoopKpi.STATE_INTEGRITY: (),
    # ③은 결합이 아니라 *행 자신의 필드*를 보므로 조인 키가 없어도 잴 수 있다 —
    # 추천이 UNJOINABLE인 것과 reason이 실렸는지는 별개 축이다.
    LoopKpi.EXPLAINABILITY: (),
    LoopKpi.MANUAL_INTERVENTION: (),
    LoopKpi.TRACEABILITY: (
        TraceEventType.RECOMMENDATION_GENERATED,
        TraceEventType.LEARNER_STATE_CREATED,
        TraceEventType.DIAGNOSTIC_COMPLETED,
        TraceEventType.PROBLEM_ATTEMPTED,
    ),
}


def blocked_preconditions(kpi: LoopKpi) -> tuple[str, ...]:
    """이 KPI를 구조적으로 막고 있는 원천의 사유 문장들(없으면 빈 튜플).

    반환값이 비어 있지 않으면 그 KPI는 데이터를 조회하기도 전에 `unmeasured`다 — 조회해서
    나오는 0은 "위반이 없다"가 아니라 "아무도 기록하지 않는다"이기 때문이다.
    """
    required = _REQUIRED_SOURCES[kpi]
    if not required:
        return ()
    by_type = {c.event_type: c for c in source_registry()}
    blocked: list[str] = []
    for event_type in required:
        coverage = by_type[event_type]
        if coverage.availability is not SourceAvailability.PRODUCED:
            blocked.append(
                f"{event_type.value}({coverage.source.value}) = "
                f"{coverage.availability.value} — {coverage.reason}"
            )
    return tuple(blocked)


# ──────────────────────────────────────────────────────────────────────────
# 관측치 — 임계를 담지 않는다(규칙 4)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class ObservationWindow:
    """관측창 — 모든 조회·증거 줄에 박힌다(이전 실행의 증거를 이번 것으로 오독 금지)."""

    start: datetime
    end: datetime

    def as_dict(self) -> dict[str, str]:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}


@dataclass(frozen=True, slots=True)
class Observation:
    """한 KPI의 관측치. 임계·방향·판정은 들어올 수 없다(자기 신고 금지)."""

    kpi: LoopKpi
    numerator: int | None = None
    denominator: int | None = None
    unmeasured_reason: str | None = None
    """채워져 있으면 분자·분모와 무관하게 미측정이다(구조적 선결 미충족·수집 실패)."""

    source: str = "unknown"
    """이 관측치를 실제로 낸 주체(수집기 이름·`--input` 등) — 판정의 출처 추적."""

    error_type: str | None = None
    """수집이 예외로 끝났을 때 그 **예외 타입명**(침묵 실패 금지). 값·시크릿은 싣지 않는다."""

    def as_dict(self) -> dict[str, Any]:
        return {
            "kpi": self.kpi.value,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "unmeasured_reason": self.unmeasured_reason,
            "source": self.source,
            "error_type": self.error_type,
        }


@dataclass(frozen=True, slots=True)
class KpiOutcome:
    """한 KPI의 판정 결과."""

    kpi: LoopKpi
    verdict: KpiVerdict
    observed: float | None
    """점추정 비율(분자/분모). 판정 근거가 아니라 *참고*다 — 판정은 아래 경계로 한다."""

    bound: float | None
    """판정에 실제로 쓴 값. 비율 축이면 Wilson 경계, 무관용 축이면 분자 그 자체(float)."""

    numerator: int | None
    denominator: int | None
    reason: str
    source: str
    error_type: str | None = None
    residual_upper_bound: float | None = None
    """무관용 축이 통과했을 때의 Wilson 상한 — 관측 0을 확정 0으로 과신하지 않기 위한 표기."""

    def as_dict(self) -> dict[str, Any]:
        spec = spec_for(self.kpi)
        payload: dict[str, Any] = {
            "kpi": self.kpi.value,
            "title": spec.title,
            "verdict": self.verdict.value,
            "threshold": spec.threshold,
            "direction": spec.direction.value,
            "zero_tolerance": spec.zero_tolerance,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "numerator_def": spec.numerator_def,
            "denominator_def": spec.denominator_def,
            "observed": self.observed,
            "bound": self.bound,
            "residual_upper_bound": self.residual_upper_bound,
            "source": self.source,
            "seat_task": spec.seat_task,
            "reason": self.reason,
            "error_type": self.error_type,
        }
        if spec.coverage_note is not None:
            payload["coverage_note"] = spec.coverage_note
        return payload


def _evaluate_one(observation: Observation) -> KpiOutcome:
    """관측치 1건 → 판정 1건. 순수 함수(입출력 외 부작용 0)."""
    spec = spec_for(observation.kpi)
    num, den = observation.numerator, observation.denominator

    if observation.unmeasured_reason is not None:
        return KpiOutcome(
            kpi=spec.kpi,
            verdict=KpiVerdict.unmeasured,
            observed=None,
            bound=None,
            numerator=num,
            denominator=den,
            reason=observation.unmeasured_reason,
            source=observation.source,
            error_type=observation.error_type,
        )

    if num is None or den is None:
        return KpiOutcome(
            kpi=spec.kpi,
            verdict=KpiVerdict.unmeasured,
            observed=None,
            bound=None,
            numerator=num,
            denominator=den,
            reason="분자 또는 분모가 없다 — 수집기가 값을 내지 못했다.",
            source=observation.source,
            error_type=observation.error_type,
        )

    if den <= 0:
        # 규칙 1 — 분모 0에서 "위반 0건 → 100% 달성"을 만들지 않는다. 이 자리가 이 모듈이
        # 존재하는 이유의 절반이다.
        return KpiOutcome(
            kpi=spec.kpi,
            verdict=KpiVerdict.unmeasured,
            observed=None,
            bound=None,
            numerator=num,
            denominator=den,
            reason=(
                f"분모가 0이다({spec.denominator_def}) — 위반이 없는 것이 아니라 "
                "잰 것이 없다. 관측창을 넓히거나 생산 좌석을 확인한다."
            ),
            source=observation.source,
        )

    if num < 0 or num > den:
        return KpiOutcome(
            kpi=spec.kpi,
            verdict=KpiVerdict.unmeasured,
            observed=None,
            bound=None,
            numerator=num,
            denominator=den,
            reason=f"관측치가 비율로 성립하지 않는다(분자 {num} / 분모 {den}) — 수집기 결함.",
            source=observation.source,
        )

    observed = num / den

    if spec.zero_tolerance:
        # 규칙 2 — 무관용 축에 신뢰구간을 적용하지 않는다. 1건은 1건이다.
        if num > 0:
            return KpiOutcome(
                kpi=spec.kpi,
                verdict=KpiVerdict.failed,
                observed=observed,
                bound=float(num),
                numerator=num,
                denominator=den,
                reason=f"무관용 축에서 {num}건 관측({spec.numerator_def}) — 0이어야 한다.",
                source=observation.source,
            )
        return KpiOutcome(
            kpi=spec.kpi,
            verdict=KpiVerdict.passed,
            observed=observed,
            bound=0.0,
            numerator=num,
            denominator=den,
            reason=f"{den}건 중 0건 — 무관용 충족.",
            source=observation.source,
            residual_upper_bound=wilson_upper_bound(num, den, CONFIDENCE),
        )

    if spec.direction is Direction.AT_LEAST:
        bound = wilson_lower_bound(num, den, CONFIDENCE)
        ok = bound >= spec.threshold
        shape = f"Wilson 하한 {bound:.4f} {'≥' if ok else '<'} 기준 {spec.threshold:.4f}"
    else:
        bound = wilson_upper_bound(num, den, CONFIDENCE)
        ok = bound <= spec.threshold
        shape = f"Wilson 상한 {bound:.4f} {'≤' if ok else '>'} 기준 {spec.threshold:.4f}"

    return KpiOutcome(
        kpi=spec.kpi,
        verdict=KpiVerdict.passed if ok else KpiVerdict.failed,
        observed=observed,
        bound=bound,
        numerator=num,
        denominator=den,
        reason=f"{shape} (점추정 {observed:.4f} · 표본 {den})",
        source=observation.source,
    )


@dataclass(frozen=True, slots=True)
class LoopKpiReport:
    """5종 판정 묶음 — 종합 점수를 만들지 않는다(평균이 붕괴를 덮는다)."""

    window: ObservationWindow
    run_id: str
    outcomes: tuple[KpiOutcome, ...]

    @property
    def failed(self) -> tuple[KpiOutcome, ...]:
        return tuple(o for o in self.outcomes if o.verdict is KpiVerdict.failed)

    @property
    def unmeasured(self) -> tuple[KpiOutcome, ...]:
        return tuple(o for o in self.outcomes if o.verdict is KpiVerdict.unmeasured)

    @property
    def exit_code(self) -> int:
        if self.failed:
            return EXIT_VIOLATION
        if self.unmeasured:
            return EXIT_UNMEASURED
        return EXIT_OK

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "window": self.window.as_dict(),
            "confidence": CONFIDENCE,
            # 규칙 5 — 판정 경로가 외부 관측 SaaS에 의존하지 않음을 산출물이 스스로 말한다.
            "accounting": {
                "in_process": True,
                "external_observability_dependency": None,
            },
            "exit_code": self.exit_code,
            "counts": {
                "total": len(self.outcomes),
                "passed": sum(1 for o in self.outcomes if o.verdict is KpiVerdict.passed),
                "failed": len(self.failed),
                "unmeasured": len(self.unmeasured),
            },
            "kpis": [o.as_dict() for o in self.outcomes],
        }


def evaluate(
    observations: Mapping[LoopKpi, Observation],
    *,
    window: ObservationWindow,
    run_id: str,
) -> LoopKpiReport:
    """관측치 묶음 → 5종 판정. 누락된 KPI는 조용히 빠지지 않고 미측정으로 계상된다."""
    outcomes: list[KpiOutcome] = []
    for spec in LOOP_KPI_SPECS:
        observation = observations.get(
            spec.kpi,
            Observation(
                kpi=spec.kpi,
                unmeasured_reason=(
                    "관측치가 제출되지 않았다 — 수집기도 입력도 이 KPI를 내지 않았다."
                ),
                source="missing",
            ),
        )
        outcomes.append(_evaluate_one(observation))
    return LoopKpiReport(window=window, run_id=run_id, outcomes=tuple(outcomes))


# ──────────────────────────────────────────────────────────────────────────
# 증거 — 실패해도 남는다(규칙 6). 단계마다 즉시 flush·예외 타입명 기록·관측창 각인
# ──────────────────────────────────────────────────────────────────────────
class EvidenceWriter:
    """단계별 NDJSON 증거 기록기.

    마지막에 한 번 저장하면 중간에 멈출 때 전부 잃는다 — 그래서 **줄마다 즉시 flush**한다.
    모든 줄에 `run_id`와 관측창이 박히므로, 로그를 나중에 읽는 사람이 *이전 실행의 증거를
    이번 원인으로 오독*할 수 없다.

    경로를 주지 않으면 아무 데도 쓰지 않는다(no-op) — 호출부가 `if writer:` 분기를 갖지
    않도록 하기 위해서다(분기 없는 쪽이 실패 경로에서 덜 깨진다).
    """

    def __init__(self, path: Path | None, *, run_id: str, window: ObservationWindow) -> None:
        self._path = path
        self._run_id = run_id
        self._window = window
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path | None:
        return self._path

    def record(self, *, kpi: LoopKpi | None, phase: str, ok: bool, **detail: Any) -> None:
        """증거 1줄 — 기록 자체가 실패해도 본 판정을 막지 않되 **조용히 넘어가지 않는다**."""
        if self._path is None:
            return
        line = {
            "run_id": self._run_id,
            "at": datetime.now(UTC).isoformat(),
            "window": self._window.as_dict(),
            "kpi": None if kpi is None else kpi.value,
            "phase": phase,
            "ok": ok,
            **detail,
        }
        try:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(line, ensure_ascii=False) + "\n")
                handle.flush()
        except OSError as exc:  # pragma: no cover - 디스크 장애 경로
            # 침묵 실패 금지 — 예외 타입명을 반드시 남긴다(시크릿·필드값은 싣지 않는다).
            print(
                f"[loop_kpi_gate] 증거 기록 실패: {type(exc).__name__} (경로={self._path})",
                file=sys.stderr,
            )


# ──────────────────────────────────────────────────────────────────────────
# 수집기 — 전부 우리 PostgreSQL에서 직접 센다(규칙 5 인프로세스 이중 회계)
# ──────────────────────────────────────────────────────────────────────────
CollectFn = Callable[[AsyncSession, ObservationWindow], Awaitable[Observation]]


async def _recover_session(session: AsyncSession | None, evidence: EvidenceWriter) -> None:
    """실패한 수집기가 남긴 중단 트랜잭션을 되돌린다 — 없으면 뒤 수집기가 *거짓* 실패한다.

    PostgreSQL은 트랜잭션 안에서 한 문장이 실패하면 그 트랜잭션의 남은 문장을 전부 거부한다.
    그래서 rollback 없이 다음 수집기를 돌리면 멀쩡한 쿼리가 `DBAPIError`로 끝나고, 리포트는
    고장 하나를 여러 개로 보고한다(2026-09-19 실측: `evidence_event.meta` 하나를 개명했더니
    수집기 2종이 실패로 찍혔다). 고칠 곳을 잘못 짚게 만드는 종류의 거짓말이다.
    """
    if session is None:
        return
    try:
        await session.rollback()
    except Exception as exc:  # noqa: BLE001 - 복구 실패가 판정 표를 죽이지 않게
        evidence.record(
            kpi=None,
            phase="session_recover_error",
            ok=False,
            error_type=type(exc).__name__,
        )


def _precondition_observation(kpi: LoopKpi, source: str) -> Observation | None:
    """구조적으로 막혀 있으면 조회 없이 미측정을 돌려준다(없으면 None)."""
    blocked = blocked_preconditions(kpi)
    if not blocked:
        return None
    return Observation(
        kpi=kpi,
        unmeasured_reason="구조적 선결 미충족 — " + " / ".join(blocked),
        source=source,
    )


async def collect_loop_completion(session: AsyncSession, window: ObservationWindow) -> Observation:
    """KPI① — 세션 축이 배선되기 전까지는 조회하지 않고 미측정을 낸다.

    조회해서 나오는 0은 "도달 실패"가 아니라 "아무도 세션을 만들지 않는다"이고, 그 둘을 같은
    숫자로 내면 0%라는 거짓 미달이 보고된다. 선결이 풀리면(원천 대장이 PRODUCED로 바뀌면)
    아래 실 조회가 자동으로 살아난다.
    """
    source = "collect_loop_completion"
    blocked = _precondition_observation(LoopKpi.LOOP_COMPLETION, source)
    if blocked is not None:
        return blocked

    denominator = await session.scalar(
        select(func.count())
        .select_from(LearningSession)
        .where(
            LearningSession.started_at >= window.start,
            LearningSession.started_at < window.end,
        )
    )
    reached = select(EvidenceEvent.session_id).where(
        EvidenceEvent.event_type == EVENT_TYPE_RECOMMENDATION_TREATMENT,
        EvidenceEvent.time >= window.start,
        EvidenceEvent.time < window.end,
    )
    numerator = await session.scalar(
        select(func.count())
        .select_from(LearningSession)
        .where(
            LearningSession.started_at >= window.start,
            LearningSession.started_at < window.end,
            LearningSession.session_id.in_(reached),
        )
    )
    return Observation(
        kpi=LoopKpi.LOOP_COMPLETION,
        numerator=int(numerator or 0),
        denominator=int(denominator or 0),
        source=source,
    )


async def collect_state_integrity(session: AsyncSession, window: ObservationWindow) -> Observation:
    """KPI② — 기존 무결성 게이트를 **호출**한다(재구현 금지·이중 진실원천 금지).

    무결성은 관측창 개념이 없는 *현재 상태 스냅샷*이다(고아 참조는 언제 생겼든 지금 고아다).
    그래서 `window`를 쓰지 않으며, 그 사실을 관측치의 `source`가 말한다.
    """
    report: IntegrityReport = await scan_integrity(session)
    scanned = sum(report.scanned.values())
    return Observation(
        kpi=LoopKpi.STATE_INTEGRITY,
        numerator=len(report.violations),
        denominator=scanned,
        source="integrity_violations_gate.scan_integrity(스냅샷 — 관측창 무관)",
    )


def _recommendation_rows_in_window(window: ObservationWindow) -> Any:
    """관측창 안의 recommendation_render 행 조건(두 수집기가 같은 정의를 공유)."""
    return (
        EvidenceEvent.event_type == EVENT_TYPE_RECOMMENDATION_TREATMENT,
        EvidenceEvent.time >= window.start,
        EvidenceEvent.time < window.end,
    )


async def collect_explainability(session: AsyncSession, window: ObservationWindow) -> Observation:
    """KPI③ — 추천 행 *자신의* meta.reason을 본다(조인 키가 없어도 잴 수 있는 축)."""
    in_window = _recommendation_rows_in_window(window)
    denominator = await session.scalar(
        select(func.count()).select_from(EvidenceEvent).where(*in_window)
    )
    numerator = await session.scalar(
        select(func.count())
        .select_from(EvidenceEvent)
        .where(
            *in_window,
            or_(
                EvidenceEvent.meta.is_(None),
                # `->>`(astext)를 쓴다. `->`는 JSON null을 *값이 있는 것*으로 돌려주므로
                # `{"reason": null}`이 "이유 있음"으로 새 나간다 — 의미상 그것은 이유 없음이다.
                # `->>`는 키 부재와 JSON null을 **둘 다** SQL NULL로 접고, 객체 값은 그 JSON
                # 텍스트를 돌려주므로 정상 reason은 걸리지 않는다.
                EvidenceEvent.meta[META_KEY_REASON].astext.is_(None),
            ),
        )
    )
    return Observation(
        kpi=LoopKpi.EXPLAINABILITY,
        numerator=int(numerator or 0),
        denominator=int(denominator or 0),
        source="collect_explainability",
    )


async def collect_manual_intervention(
    session: AsyncSession, window: ObservationWindow
) -> Observation:
    """KPI④ — 운영자 감사 행 수 / 정상 학습 실행 건수.

    분모를 두는 이유: 개입 0건이 "운영이 깨끗했다"인지 "그 창에 아무 일도 없었다"인지
    구분해야 한다. 학습이 한 건도 안 돌아간 창에서의 0은 통과가 아니라 미측정이다.
    """
    interventions = await session.scalar(
        select(func.count())
        .select_from(PrivacyAudit)
        .where(
            PrivacyAudit.event_kind.in_(OPERATOR_AUDIT_KINDS),
            PrivacyAudit.occurred_at >= window.start,
            PrivacyAudit.occurred_at < window.end,
        )
    )
    # 발생 시각이 아니라 *서버 수신* 시각으로 센다 — 클라 신고 started_at은 NULL일 수 있고
    # (미신고) 오프라인 지연 도착이 창을 건너뛴다. 수신 축이 "이 창에 시스템이 무슨 일을
    # 했는가"에 맞는 축이다.
    loop_runs = await session.scalar(
        select(func.count())
        .select_from(ProblemAttempt)
        .where(
            func.coalesce(ProblemAttempt.ingested_at, ProblemAttempt.created_at) >= window.start,
            func.coalesce(ProblemAttempt.ingested_at, ProblemAttempt.created_at) < window.end,
        )
    )
    return Observation(
        kpi=LoopKpi.MANUAL_INTERVENTION,
        numerator=int(interventions or 0),
        denominator=int(loop_runs or 0),
        source="collect_manual_intervention",
    )


async def collect_traceability(session: AsyncSession, window: ObservationWindow) -> Observation:
    """KPI⑤ — 5홉 체인의 해소율. 현행은 2홉(추천 결합·LearnerState 시각)이 구조적으로 끊겨 있다.

    끊긴 홉이 하나라도 있으면 조회하지 않는다. 남은 3홉만 재서 "100% 역추적"이라고 적으면
    그것이 정확히 이 게이트가 막으려는 거짓말이다.
    """
    source = "collect_traceability"
    blocked = _precondition_observation(LoopKpi.TRACEABILITY, source)
    if blocked is not None:
        return blocked

    denominator = await session.scalar(
        select(func.count())
        .select_from(EvidenceEvent)
        .where(*_recommendation_rows_in_window(window))
    )
    # 선결이 풀린 뒤의 실 체인 해소는 그 배선이 어떤 조인 키를 남기느냐에 달려 있다. 지금
    # 추측해 짜 두면 *검증된 적 없는* 쿼리가 통과 판정을 내게 된다 — 그래서 분자를 미측정으로
    # 남기고 배선 좌석(EOS-11/EOS-79)이 그 조인 키를 확정할 때 함께 채운다.
    return Observation(
        kpi=LoopKpi.TRACEABILITY,
        denominator=int(denominator or 0),
        unmeasured_reason=(
            "5홉 체인의 조인 키가 확정되기 전까지 분자(역추적 실패 건수)를 세지 않는다 — "
            "검증된 적 없는 쿼리가 100%를 선언하지 않게 한다."
        ),
        source=source,
    )


_COLLECTORS: Final[Mapping[LoopKpi, CollectFn]] = {
    LoopKpi.LOOP_COMPLETION: collect_loop_completion,
    LoopKpi.STATE_INTEGRITY: collect_state_integrity,
    LoopKpi.EXPLAINABILITY: collect_explainability,
    LoopKpi.MANUAL_INTERVENTION: collect_manual_intervention,
    LoopKpi.TRACEABILITY: collect_traceability,
}


async def collect_all(
    session: AsyncSession,
    window: ObservationWindow,
    *,
    evidence: EvidenceWriter,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    collectors: Mapping[LoopKpi, CollectFn] | None = None,
) -> dict[LoopKpi, Observation]:
    """5종 수집. 한 수집기의 실패가 나머지를 죽이지 않고 **그 KPI만** 미측정으로 만든다.

    모든 외부 호출에 타임아웃을 건다 — 무한 대기는 증거도 원인도 남기지 않고 측정 회차만
    태운다(2026-08-22 Phaiakes9 진단의 첫 번째 결함 유형).
    """
    active = dict(_COLLECTORS) if collectors is None else dict(collectors)
    observations: dict[LoopKpi, Observation] = {}
    for spec in LOOP_KPI_SPECS:
        collect = active.get(spec.kpi)
        if collect is None:
            observations[spec.kpi] = Observation(
                kpi=spec.kpi,
                unmeasured_reason="수집기가 등록되지 않았다.",
                source="missing",
            )
            continue
        evidence.record(kpi=spec.kpi, phase="collect_start", ok=True, source=spec.source)
        try:
            observation = await asyncio.wait_for(collect(session, window), timeout_seconds)
        except TimeoutError:
            observation = Observation(
                kpi=spec.kpi,
                unmeasured_reason=f"수집 타임아웃({timeout_seconds}s) — 판정 불가.",
                source="timeout",
                error_type="TimeoutError",
            )
            evidence.record(
                kpi=spec.kpi,
                phase="collect_error",
                ok=False,
                error_type="TimeoutError",
                timeout_seconds=timeout_seconds,
            )
            await _recover_session(session, evidence)
        except Exception as exc:  # noqa: BLE001 - 한 KPI의 실패로 전 판정을 잃지 않는다
            # 예외 타입명을 반드시 남긴다(무타입 경고 금지). 메시지는 DSN·시크릿을 품을 수
            # 있으므로 `repr`을 싣지 않고 타입명 + 클래스 모듈만 남긴다.
            error_type = type(exc).__name__
            observation = Observation(
                kpi=spec.kpi,
                unmeasured_reason=f"수집 실패({error_type}) — 판정 불가.",
                source="error",
                error_type=error_type,
            )
            evidence.record(
                kpi=spec.kpi,
                phase="collect_error",
                ok=False,
                error_type=error_type,
                error_module=type(exc).__module__,
            )
            await _recover_session(session, evidence)
        else:
            evidence.record(
                kpi=spec.kpi,
                phase="collect_ok",
                ok=True,
                observation=observation.as_dict(),
            )
        observations[spec.kpi] = observation
    return observations


# ──────────────────────────────────────────────────────────────────────────
# 입력 — 관측치만 받는다(규칙 4). 임계·판정 키가 오면 거부한다
# ──────────────────────────────────────────────────────────────────────────
#: `--input` JSON의 KPI 항목에서 허용되는 키. 이 밖은 전부 거부한다 — 특히 임계·방향·판정을
#: 입력이 써 내면 그것은 측정이 아니라 자기 신고다(validation_scorecard 설계 규칙 5 승계).
_ALLOWED_INPUT_KEYS: Final[frozenset[str]] = frozenset(
    {"numerator", "denominator", "unmeasured_reason", "source"}
)


class InputContractError(ValueError):
    """`--input` JSON이 관측치 계약을 어겼다 — 조용히 무시하지 않고 실행을 멈춘다."""


def parse_input_observations(payload: Any) -> dict[LoopKpi, Observation]:
    """`--input` JSON → 관측치. 계약 위반은 `InputContractError`로 **거부**한다.

    "알 수 없는 키는 무시"는 관대함이 아니라 위장이다 — 오타 난 `numerater`가 조용히 버려지면
    분자 없는 미측정이 "입력했는데도 미측정"으로 보이고, 제출자는 자기가 낸 값이 쓰였다고 믿는다.
    """
    if not isinstance(payload, Mapping):
        raise InputContractError("최상위가 객체가 아니다 — {KPI이름: {관측치}} 형태여야 한다.")
    known = {k.value for k in LoopKpi}
    observations: dict[LoopKpi, Observation] = {}
    for raw_key, raw_value in payload.items():
        if raw_key not in known:
            raise InputContractError(f"알 수 없는 KPI 키 {raw_key!r} — 허용: {sorted(known)}")
        if not isinstance(raw_value, Mapping):
            raise InputContractError(f"{raw_key}: 값이 객체가 아니다.")
        extra = set(raw_value) - _ALLOWED_INPUT_KEYS
        if extra:
            raise InputContractError(
                f"{raw_key}: 허용되지 않은 키 {sorted(extra)} — 입력은 관측치만 낸다"
                f"(임계·방향·판정은 코드가 갖는다). 허용: {sorted(_ALLOWED_INPUT_KEYS)}"
            )
        kpi = LoopKpi(raw_key)
        numerator = raw_value.get("numerator")
        denominator = raw_value.get("denominator")
        for name, value in (("numerator", numerator), ("denominator", denominator)):
            if value is not None and not isinstance(value, int):
                raise InputContractError(f"{raw_key}.{name}: 정수여야 한다(받은 값 타입 불일치).")
        reason = raw_value.get("unmeasured_reason")
        if reason is not None and not isinstance(reason, str):
            raise InputContractError(f"{raw_key}.unmeasured_reason: 문자열이어야 한다.")
        source = raw_value.get("source")
        if source is not None and not isinstance(source, str):
            raise InputContractError(f"{raw_key}.source: 문자열이어야 한다.")
        observations[kpi] = Observation(
            kpi=kpi,
            numerator=numerator,
            denominator=denominator,
            unmeasured_reason=reason,
            source=source or "input",
        )
    return observations


# ──────────────────────────────────────────────────────────────────────────
# 렌더 · CLI
# ──────────────────────────────────────────────────────────────────────────
_VERDICT_MARK: Final[Mapping[KpiVerdict, str]] = {
    KpiVerdict.passed: "PASS",
    KpiVerdict.failed: "FAIL",
    KpiVerdict.unmeasured: "미측정",
}


def render(report: LoopKpiReport) -> str:
    """사람이 읽는 판정표. 미측정을 통과와 같은 줄 모양으로 내지 않는다."""
    lines: list[str] = []
    lines.append("Phase 2 학습 루프 KPI 5종 (계획서 §19) — 콘텐츠 생산 KPI 12종과 **별도 축**")
    lines.append(f"  run_id : {report.run_id}")
    lines.append(f"  관측창 : {report.window.start.isoformat()} ~ {report.window.end.isoformat()}")
    lines.append("  회계   : 인프로세스 전량(외부 관측 SaaS 비의존)")
    lines.append("")
    for outcome in report.outcomes:
        spec = spec_for(outcome.kpi)
        mark = _VERDICT_MARK[outcome.verdict]
        lines.append(f"[{mark:>4}] {spec.title}")
        if outcome.numerator is not None or outcome.denominator is not None:
            lines.append(f"        분자/분모 : {outcome.numerator} / {outcome.denominator}")
        if outcome.observed is not None:
            lines.append(f"        점추정    : {outcome.observed:.4f}")
        lines.append(f"        판정근거  : {outcome.reason}")
        if outcome.residual_upper_bound is not None:
            lines.append(
                f"        잔여상한  : {outcome.residual_upper_bound:.4f}"
                " (관측 0이 확정 0은 아니다)"
            )
        if outcome.error_type is not None:
            lines.append(f"        예외타입  : {outcome.error_type}")
        lines.append(f"        출처      : {outcome.source} · 좌석 {spec.seat_task}")
        if spec.coverage_note is not None:
            lines.append(f"        관측범위  : {spec.coverage_note}")
        lines.append("")
    counts = report.as_dict()["counts"]
    lines.append(
        f"합계: 통과 {counts['passed']} · 위반 {counts['failed']} · 미측정 {counts['unmeasured']}"
        f" / 전체 {counts['total']}"
    )
    if report.failed:
        lines.append("판정: 위반 있음 → exit 1")
    elif report.unmeasured:
        lines.append("판정: 측정 실패 있음 → exit 2 (미측정은 통과가 아니다)")
    else:
        lines.append("판정: 5종 전부 충족 → exit 0")
    return "\n".join(lines)


def schema_smoke_failures(
    observations: Mapping[LoopKpi, Observation],
) -> tuple[Observation, ...]:
    """수집기가 **예외로** 끝난 관측치만 골라낸다(빈 DB의 미측정은 실패가 아니다).

    빈 DB에서 KPI 판정은 전부 미측정이라 게이트로 쓸 수 없지만, "5종 수집 쿼리가 실제 스키마를
    상대로 완주하는가"는 빈 DB에서도 변별력이 있다 — 컬럼이 개명되거나 테이블이 사라지면 그
    수집기가 예외로 끝나고 여기서 잡힌다. 그래서 이 축만 CI(실 PG 잡)에 건다.
    """
    return tuple(o for o in observations.values() if o.error_type is not None)


async def _collect_via_db(
    window: ObservationWindow,
    *,
    evidence: EvidenceWriter,
    timeout_seconds: float,
) -> dict[LoopKpi, Observation]:
    """실 DB 세션을 열어 5종을 수집한다. 접속 실패는 **전 KPI 미측정**이지 실행 오류가 아니다."""
    try:
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            return await collect_all(
                session, window, evidence=evidence, timeout_seconds=timeout_seconds
            )
    except Exception as exc:  # noqa: BLE001 - 접속 실패로 판정 표 전체를 잃지 않는다
        error_type = type(exc).__name__
        evidence.record(
            kpi=None,
            phase="db_connect_error",
            ok=False,
            error_type=error_type,
            error_module=type(exc).__module__,
        )
        return {
            spec.kpi: Observation(
                kpi=spec.kpi,
                unmeasured_reason=f"DB 세션 확보 실패({error_type}) — 판정 불가.",
                source="db_unavailable",
                error_type=error_type,
            )
            for spec in LOOP_KPI_SPECS
        }
    finally:
        await dispose_engine()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.ops.loop_kpi_gate",
        description=(
            "Phase 2 학습 루프 KPI 5종 게이트 — Loop Completion·State Integrity·"
            "Explainability·Manual Intervention·Traceability."
        ),
    )
    parser.add_argument(
        "--since-hours",
        type=float,
        default=float(DEFAULT_WINDOW_HOURS),
        help=f"관측창 길이(시간·기본 {DEFAULT_WINDOW_HOURS}). 끝점은 실행 시각이다.",
    )
    parser.add_argument(
        "--json",
        dest="json_path",
        default=None,
        help="판정 JSON 저장 경로(선택).",
    )
    parser.add_argument(
        "--evidence",
        dest="evidence_path",
        default=None,
        help="단계별 증거 NDJSON 경로(선택) — 줄마다 즉시 flush된다.",
    )
    parser.add_argument(
        "--input",
        dest="input_path",
        default=None,
        help=(
            "관측치 JSON({KPI: {numerator, denominator, unmeasured_reason, source}}). "
            "DB 수집분보다 **뒤에** 병합돼 이긴다 — 위반 주입 드릴에 쓴다. "
            "임계·방향 키가 섞이면 거부한다."
        ),
    )
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="DB 수집을 건너뛴다(--input만으로 판정 — hermetic 드릴·CI 하네스).",
    )
    parser.add_argument(
        "--schema-smoke",
        action="store_true",
        help=(
            "KPI 판정 대신 **수집 완주**만 본다 — 5종 수집기가 실 스키마를 상대로 예외 없이 "
            "끝나면 exit 0, 하나라도 예외면 exit 1. 데이터가 없는 CI DB에서도 변별력이 있는 "
            "축이라 실 PG 잡에 거는 것은 이쪽이다(판정 게이트는 운영 DB에서 돈다)."
        ),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"수집기 1종당 타임아웃(기본 {DEFAULT_TIMEOUT_SECONDS}s).",
    )
    args = parser.parse_args(argv)

    if args.since_hours <= 0:
        print("[loop_kpi_gate] --since-hours는 양수여야 한다.", file=sys.stderr)
        return EXIT_RUNTIME_ERROR
    if args.schema_smoke and args.no_db:
        # DB를 안 보는 스키마 스모크는 아무것도 검사하지 않는다 — 공허한 통과 금지.
        print("[loop_kpi_gate] --schema-smoke는 --no-db와 함께 쓸 수 없다.", file=sys.stderr)
        return EXIT_RUNTIME_ERROR
    if args.schema_smoke and args.input_path:
        # 스모크는 판정 전에 끝나므로 `--input`을 읽지 않는다. 조용히 무시하면 제출자는 자기
        # 관측치가 반영됐다고 믿는다 — `--input`의 미허용 키를 거부하는 것과 같은 이유다.
        print(
            "[loop_kpi_gate] --schema-smoke는 --input을 쓰지 않는다(수집 완주만 본다). "
            "판정이 필요하면 --schema-smoke를 빼십시오.",
            file=sys.stderr,
        )
        return EXIT_RUNTIME_ERROR

    end = datetime.now(UTC)
    window = ObservationWindow(start=end - timedelta(hours=args.since_hours), end=end)
    run_id = uuid.uuid4().hex[:12]

    try:
        evidence = EvidenceWriter(
            Path(args.evidence_path) if args.evidence_path else None,
            run_id=run_id,
            window=window,
        )
    except OSError as exc:
        print(
            f"[loop_kpi_gate] 증거 경로 준비 실패: {type(exc).__name__}",
            file=sys.stderr,
        )
        return EXIT_RUNTIME_ERROR

    evidence.record(kpi=None, phase="run_start", ok=True, no_db=bool(args.no_db))

    observations: dict[LoopKpi, Observation] = {}
    if not args.no_db:
        observations.update(
            asyncio.run(
                _collect_via_db(window, evidence=evidence, timeout_seconds=args.timeout_seconds)
            )
        )
    else:
        evidence.record(kpi=None, phase="db_skipped", ok=True)

    if args.schema_smoke:
        broken = schema_smoke_failures(observations)
        for observation in broken:
            print(
                f"[스키마 스모크] {observation.kpi.value}: 수집 실패 "
                f"{observation.error_type} — {observation.unmeasured_reason}",
                file=sys.stderr,
            )
        exit_code = EXIT_VIOLATION if broken else EXIT_OK
        print(
            f"[스키마 스모크] 수집기 {len(observations)}종 중 완주 "
            f"{len(observations) - len(broken)}종 · 예외 {len(broken)}종 → exit {exit_code}"
        )
        evidence.record(kpi=None, phase="schema_smoke", ok=not broken, broken=len(broken))
        return exit_code

    if args.input_path:
        try:
            raw = json.loads(Path(args.input_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(
                f"[loop_kpi_gate] --input 읽기 실패: {type(exc).__name__}",
                file=sys.stderr,
            )
            evidence.record(kpi=None, phase="input_error", ok=False, error_type=type(exc).__name__)
            return EXIT_RUNTIME_ERROR
        try:
            injected = parse_input_observations(raw)
        except InputContractError as exc:
            print(f"[loop_kpi_gate] --input 계약 위반: {exc}", file=sys.stderr)
            evidence.record(
                kpi=None, phase="input_error", ok=False, error_type="InputContractError"
            )
            return EXIT_RUNTIME_ERROR
        for kpi, observation in injected.items():
            evidence.record(
                kpi=kpi, phase="input_merge", ok=True, observation=observation.as_dict()
            )
        observations.update(injected)

    report = evaluate(observations, window=window, run_id=run_id)
    for outcome in report.outcomes:
        evidence.record(
            kpi=outcome.kpi,
            phase="verdict",
            ok=outcome.verdict is KpiVerdict.passed,
            verdict=outcome.verdict.value,
            bound=outcome.bound,
        )

    print(render(report))

    if args.json_path:
        try:
            path = Path(args.json_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(report.as_dict(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            print(
                f"[loop_kpi_gate] JSON 저장 실패: {type(exc).__name__}",
                file=sys.stderr,
            )
            return EXIT_RUNTIME_ERROR

    evidence.record(kpi=None, phase="run_end", ok=True, exit_code=report.exit_code)
    return report.exit_code


if __name__ == "__main__":  # pragma: no cover - 엔트리포인트
    raise SystemExit(main())
