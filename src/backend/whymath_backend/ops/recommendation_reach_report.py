"""추천 도달 관측 리포트 — `/v1/me/next-problem` 입력 루프 미도달 실측(REC-01).

배경 (왜 이 모듈이 필요한가)
----------------------------
`GET /v1/me/next-problem`(IRT CAT 적응 출제)은 이미 프로덕션이지만, Flutter 앱이
`POST /v1/me/attempts`를 호출하지 않아(전수 실측 완료) `problem_attempt` 테이블이 0행이다.
그 결과 θ(능력 추정)는 콜드스타트 기본값 0.0에 고정되고, 약점 개념 가중
(`prioritize_weak_concepts=true`)도 BKT 숙달 스냅샷이 없어 전 후보에 중립(1.0)으로만
적용된다 — 그런데 이 상태가 지금까지 *관측되지 않았다*. 이 모듈은 그 도달 여부를 실 DB
쿼리로 계측해 "0건"과 "0건 통과"를 구분한다(분모 없는 0을 지어내지 않는다 —
`harness/visualization_reach_report.py`·`ops/cost_probe.py`의 None-vs-0 회계 원칙과 동형).

왜 harness/가 아니라 ops/인가
-----------------------------
`harness/*.py`(예: `problem_bank_coverage.py`·`visualization_reach_report.py`)는 전부
*코퍼스 JSON을 읽는 빌드타임 결정론 리포트*(DB 0·라이브 0)다. 이 리포트는 반대로 **실 DB를
쿼리**해야만 의미가 있다(도달 여부 자체가 실 운영 데이터의 문제라서). `ops/service_health.py`
가 이 저장소에서 *DB 쿼리 기반 관측*의 정본 위치이므로, 그 파일의 docstring 톤과 None-vs-0
회계 원칙(컴포넌트 미구성=`configured=False`·판정 불가=`reachable=None`)을 그대로 따른다.

추천 요청 수 — 관측 불가(정직 표기, 지어내지 않는다)
------------------------------------------------------
"`/next-problem`이 몇 번 호출됐는가"를 세는 카운터는 이 저장소 어디에도 없다(전수 확인):
`ops/service_health.ServiceMetrics`는 프로세스 전역 HTTP 요청 수만 셀 뿐 *경로별*이 아니고,
`attempt_event.EventType`(8+3종)에도 "추천 요청" 계열이 없다. 이 리포트는 이 사실 자체를
`REQUEST_COUNTER_STATUS`로 정직하게 보고한다 — 없는 카운터를 지어내거나 새 미들웨어·이벤트
타입을 신설하지 않는다(그건 이 슬라이스의 범위 밖이자 더 큰 설계 결정이다).

실제로 DB에서 직접 측정하는 5축 (전부 SQLAlchemy Core — 원시 SQL 0)
----------------------------------------------------------------------
1. **problem_attempt 적재** — 전체 행 수. 0이면 "0건 통과"가 아니라 **'미도달'**로 표시한다
   (이 리포트에서 가장 중요한 숫자 — 아래 3축이 전부 이 축에 종속된 부분집합이다).
2. **θ 추정 유효 응답** — `problem_attempt` 중 채점 완료(`is_correct` not null)이고 IRT b
   소스(`Problem.irt_difficulty_b` 또는 `Problem.difficulty_overall`)가 있는 행 수
   (`api/me.py`의 `attempt_stmt`·`resolve_item_difficulty_b` 필터와 동일 축). 1이 0이면
   구조적으로 0이라 자동 '미도달'이다.
3. **개인화 가중 적용 가능** — `concept_mastery_history`의 유니크 `(user_id, concept_id)`
   쌍 수(BKT 숙달 스냅샷이 있어야 `_weak_concept_weights`가 중립 아닌 가중을 낼 수 있다).
4. **후보 풀 구조적 상한** — `Problem.difficulty_overall IS NOT NULL`인 문항 수(전체 후보
   모집단). `/next-problem`의 `_CANDIDATE_POOL_SIZE=50`은 이 모집단에서 θ 근방으로 잘라내는
   *상한값*일 뿐이다 — 이 리포트는 그 상한 자체를 명시하지, 실제 요청별 후보 풀 크기는
   `NextProblemResponse.candidate_pool_size`(REC-01 갈래 B)에서 확인한다.
5. **REC-11 candidates·policy_version 기록률** — `evidence_event`의 `recommendation_render`
   처치 전체 중 `meta`에 `candidates`·`policy_version`이 둘 다 실린 건수의 비율("작동한
   비율" — CLAUDE.md 원칙). 분모(처치 전체)가 0이면 비율은 **None**(0/0을 지어내지 않는다).

집계 코어(`build_report`)는 순수 함수(원시 카운트 6개 → 리포트)라 hermetic 테스트로 전량
검증 가능하다. DB 접속(`fetch_reach_counts`)만 async I/O 경계다.

실행
----
    python -m whymath_backend.ops.recommendation_reach_report
    python -m whymath_backend.ops.recommendation_reach_report --json out/reach.json

종료 코드: 0=성공(수치가 0이어도 게이트 아님) / 2=실행 오류(DB 접속 실패 등 전제 미충족).
접속 실패는 예외를 삼키지 않고 **타입명**과 함께 stderr에 보고한다(침묵 실패 금지 —
`str(exc)`엔 DSN 등 환경값이 섞일 수 있어 메시지에는 타입명을 우선 싣는다).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.activity import ProblemAttempt
from whymath_backend.db.models.assessment import ConceptMasteryHistory
from whymath_backend.db.models.evidence_event import EvidenceEvent
from whymath_backend.db.models.problem import Problem
from whymath_backend.db.session import dispose_engine, get_sessionmaker
from whymath_backend.l2.recommendation_evidence import (
    EVENT_TYPE_RECOMMENDATION_TREATMENT,
    META_KEY_CANDIDATES,
    META_KEY_POLICY_VERSION,
)

__all__ = [
    "NOT_REACHED",
    "REQUEST_COUNTER_STATUS",
    "ReachCounts",
    "ReachReport",
    "build_report",
    "fetch_reach_counts",
    "main",
    "render_report",
    "report_to_json",
]

_EXIT_OK = 0
_EXIT_RUNTIME_ERROR = 2

# `/next-problem`(api/me.py)의 θ 근방 SQL 선별 상한 — 실제 값은 그 모듈이 단일 출처다.
# 여기서는 리포트 문구에만 쓰는 참고 상수라 import로 결합하지 않는다(무거운 API 앱 import
# 체인 회피 — 값이 바뀌면 이 리포트의 설명 문구만 갱신하면 된다·과공학 방지).
_NEXT_PROBLEM_CANDIDATE_POOL_SIZE = 50

# 분모 있는 실측치가 0일 때의 표시 — "0건 통과"와 구분(None-vs-0 회계, VIZ-01·NLP-01 선례).
NOT_REACHED = "미도달"
_MEASURED = "측정됨"

# 추천 요청 수 — 카운터 부재를 지어내지 않고 정직하게 보고(모듈 docstring 참조).
REQUEST_COUNTER_STATUS = (
    "관측 불가(요청 카운터 없음) — /v1/me/next-problem 호출 횟수를 세는 카운터가 이 저장소에 "
    "없다. ops/service_health.ServiceMetrics는 경로별이 아니라 프로세스 전역 HTTP 요청만 "
    "집계하고, attempt_event.EventType에도 '추천 요청' 계열이 없다(전수 확인). 이 슬라이스는 "
    "새 카운터·미들웨어·이벤트 타입을 신설하지 않는다(범위 밖 동결)."
)


# ──────────────────────────────────────────────────────────────────────────
# DB 접속 경계 — 실제 쿼리 6회(전부 SQLAlchemy Core, 원시 SQL 0).
# ──────────────────────────────────────────────────────────────────────────
@dataclass(slots=True, frozen=True)
class ReachCounts:
    """DB에서 실측한 원시 카운트 6종 — `build_report`(순수)의 유일한 입력."""

    problem_attempt_total: int
    theta_eligible_response_total: int
    weak_concept_signal_pair_total: int
    candidate_pool_structural_cap: int
    recommendation_treatment_total: int
    recommendation_treatment_with_policy_metadata_total: int


async def fetch_reach_counts(session: AsyncSession) -> ReachCounts:
    """6개 실측 카운트를 쿼리 6회로 산출한다(전부 SQLAlchemy Core — 원시 SQL 0).

    각 쿼리의 의미는 모듈 docstring "실제로 DB에서 직접 측정하는 5축" 참조.
    쿼리 순서는 테스트(큐 기반 가짜 세션)와 계약이므로 바꾸지 않는다: ① problem_attempt
    전체 행 수 ② θ 추정 유효 응답 ③ 개인화(BKT) 유니크 (user, concept) 쌍 ④ 후보 풀 구조적
    상한 ⑤ REC-11 candidates·policy_version 기록률(분자·분모).
    """
    attempt_total = int(
        (await session.execute(select(func.count()).select_from(ProblemAttempt))).scalar_one()
    )

    # θ 추정에 실제로 기여 가능한 유효 응답 — api/me.py의 attempt_stmt 필터(is_correct not
    # null)와 동일 축 + IRT b 소스(irt_difficulty_b 또는 difficulty_overall) 존재.
    eligible_stmt = (
        select(func.count())
        .select_from(ProblemAttempt)
        .join(Problem, ProblemAttempt.problem_id == Problem.problem_id)
        .where(
            ProblemAttempt.is_correct.isnot(None),
            or_(Problem.irt_difficulty_b.isnot(None), Problem.difficulty_overall.isnot(None)),
        )
    )
    eligible_total = int((await session.execute(eligible_stmt)).scalar_one())

    # 개인화 가중 적용 가능 건수 — BKT 숙달 스냅샷이 존재하는 유니크 (user_id, concept_id) 쌍.
    distinct_pairs = (
        select(ConceptMasteryHistory.user_id, ConceptMasteryHistory.concept_id)
        .distinct()
        .subquery()
    )
    pair_total = int(
        (await session.execute(select(func.count()).select_from(distinct_pairs))).scalar_one()
    )

    # 후보 풀 구조적 상한 — 난이도 라벨(difficulty_overall) 보유 문항 전체 모집단.
    pool_cap = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Problem)
                .where(Problem.difficulty_overall.isnot(None))
            )
        ).scalar_one()
    )

    # REC-11 — 처치 기록 전체 중 candidates·policy_version 둘 다 실린 건수("작동한 비율"의
    # 분자·분모). 정본 함수(`record_recommendation_treatment`)는 두 키를 항상 같이 넣거나
    # 같이 생략하므로(호출자가 둘 다 넘기거나 둘 다 생략) 둘 다 있어야만 "기록됨"으로 센다.
    treatment_total_stmt = (
        select(func.count())
        .select_from(EvidenceEvent)
        .where(EvidenceEvent.event_type == EVENT_TYPE_RECOMMENDATION_TREATMENT)
    )
    treatment_total = int((await session.execute(treatment_total_stmt)).scalar_one())
    with_policy_metadata_stmt = treatment_total_stmt.where(
        EvidenceEvent.meta.has_key(META_KEY_CANDIDATES),
        EvidenceEvent.meta.has_key(META_KEY_POLICY_VERSION),
    )
    with_policy_metadata_total = int(
        (await session.execute(with_policy_metadata_stmt)).scalar_one()
    )

    return ReachCounts(
        problem_attempt_total=attempt_total,
        theta_eligible_response_total=eligible_total,
        weak_concept_signal_pair_total=pair_total,
        candidate_pool_structural_cap=pool_cap,
        recommendation_treatment_total=treatment_total,
        recommendation_treatment_with_policy_metadata_total=with_policy_metadata_total,
    )


# ──────────────────────────────────────────────────────────────────────────
# 집계 — 도달 관측 리포트(순수 코어, I/O 0·hermetic 검증 가능).
# ──────────────────────────────────────────────────────────────────────────
@dataclass(slots=True, frozen=True)
class ReachReport:
    """추천 도달 관측 결과 전량(불변·렌더/직렬화의 단일 입력)."""

    request_counter_status: str
    problem_attempt_total: int
    problem_attempt_reached: bool
    theta_eligible_response_total: int
    theta_eligible_reached: bool
    weak_concept_signal_pair_total: int
    weak_concept_signal_reached: bool
    candidate_pool_structural_cap: int
    recommendation_treatment_total: int
    recommendation_treatment_with_policy_metadata_total: int
    recommendation_treatment_policy_metadata_rate: float | None


def build_report(counts: ReachCounts) -> ReachReport:
    """원시 카운트 5개 → `ReachReport`(순수·부작용 0). `reached`는 count>0(분모 없는 0 방지).

    `recommendation_treatment_policy_metadata_rate`(REC-11 "작동한 비율")는 분모
    (`recommendation_treatment_total`)가 0이면 **None**이다 — 0/0을 0.0으로 지어내지
    않는다(이 모듈의 None-vs-0 회계 원칙 그대로 승계).
    """
    rate = (
        None
        if counts.recommendation_treatment_total == 0
        else counts.recommendation_treatment_with_policy_metadata_total
        / counts.recommendation_treatment_total
    )
    return ReachReport(
        request_counter_status=REQUEST_COUNTER_STATUS,
        problem_attempt_total=counts.problem_attempt_total,
        problem_attempt_reached=counts.problem_attempt_total > 0,
        theta_eligible_response_total=counts.theta_eligible_response_total,
        theta_eligible_reached=counts.theta_eligible_response_total > 0,
        weak_concept_signal_pair_total=counts.weak_concept_signal_pair_total,
        weak_concept_signal_reached=counts.weak_concept_signal_pair_total > 0,
        candidate_pool_structural_cap=counts.candidate_pool_structural_cap,
        recommendation_treatment_total=counts.recommendation_treatment_total,
        recommendation_treatment_with_policy_metadata_total=(
            counts.recommendation_treatment_with_policy_metadata_total
        ),
        recommendation_treatment_policy_metadata_rate=rate,
    )


# ──────────────────────────────────────────────────────────────────────────
# 렌더 — 사람이 읽는 마크다운 + 기계가 읽는 JSON
# ──────────────────────────────────────────────────────────────────────────
def _status_label(reached: bool) -> str:
    return _MEASURED if reached else NOT_REACHED


def render_report(report: ReachReport) -> str:
    """도달 관측 결과를 마크다운으로 렌더(순수·입력 외 계산 없음)."""
    lines: list[str] = [
        "# 추천 도달 관측 리포트 (REC-01)",
        "",
        "> 관측 리포트다 — **exit 게이트가 아니다**(수치가 0이어도 exit 0).",
        "> '0건'을 '0건 통과'로 위장하지 않는다 — 분모 없는 축은 **'미도달'**로 표시한다.",
        "",
        "## 0. 추천 요청 수 (/v1/me/next-problem 호출 횟수)",
        "",
        f"- {report.request_counter_status}",
        "",
        "## 1. problem_attempt 적재 (POST /v1/me/attempts 결과가 실제로 쌓였는가)",
        "",
        f"- 전체 행 수: **{report.problem_attempt_total}** "
        f"({_status_label(report.problem_attempt_reached)})",
    ]
    if not report.problem_attempt_reached:
        lines.append(
            "  - 0행 — θ(능력 추정)가 콜드스타트 기본값(0.0)에 고정되고, 개인화 가중은 "
            "구조적으로 전 후보 중립(1.0)일 수밖에 없다(아래 2·3 참조)."
        )
    lines += [
        "",
        "## 2. θ 추정 유효 응답 (IRT b 소스 보유 문항의 채점 완료 응답)",
        "",
        f"- 유효 응답 수: **{report.theta_eligible_response_total}** "
        f"({_status_label(report.theta_eligible_reached)})",
        "  - problem_attempt가 0행이면 이 축도 자동으로 '미도달'이다(엄격한 부분집합).",
        "",
        "## 3. 개인화 가중 적용 가능 (BKT 숙달 스냅샷이 있는 유니크 (user, concept) 쌍)",
        "",
        f"- 유니크 쌍 수: **{report.weak_concept_signal_pair_total}** "
        f"({_status_label(report.weak_concept_signal_reached)})",
        "  - 0이면 `prioritize_weak_concepts=true`를 걸어도 가중치가 구조적으로 전부 "
        "1.0(중립)일 수밖에 없다(`api/me.py _weak_concept_weights` 참조).",
        "",
        "## 4. 후보 풀 구조적 상한 (난이도 라벨 보유 문항 전체 모집단)",
        "",
        f"- 모집단: **{report.candidate_pool_structural_cap}**",
        f"  - `/next-problem`은 이 모집단에서 θ 근방 {_NEXT_PROBLEM_CANDIDATE_POOL_SIZE}개만 "
        "SQL로 잘라 후보 풀을 구성한다 — 이 값은 그 상한일 뿐, 실제 요청별 후보 풀 크기는 "
        "`NextProblemResponse.candidate_pool_size`(REC-01 갈래 B)에서 확인한다.",
        "",
        "## 5. candidates·policy_version 기록률 (REC-11 — '작동한 비율')",
        "",
        f"- 처치 기록 전체: **{report.recommendation_treatment_total}**",
        f"- candidates·policy_version 둘 다 실린 건수: "
        f"**{report.recommendation_treatment_with_policy_metadata_total}**",
    ]
    if report.recommendation_treatment_policy_metadata_rate is None:
        lines.append(f"- 기록률: {NOT_REACHED}(처치 기록 0건 — 분모 없음)")
    else:
        lines.append(f"- 기록률: **{report.recommendation_treatment_policy_metadata_rate:.1%}**")
        if report.recommendation_treatment_policy_metadata_rate < 1.0:
            lines.append(
                "  - 1.0 미만이면 REC-11 이전(구버전 배선)에 기록된 처치가 섞여 있다는 뜻이다 "
                "— 결함이 아니라 배선 시점 이전 데이터의 정직한 흔적."
            )
    lines.append("")
    return "\n".join(lines)


def report_to_json(report: ReachReport) -> dict[str, Any]:
    """리포트 → JSON 직렬화 가능 dict(키 정렬은 dump 시 `sort_keys=True`로 고정)."""
    return {
        "request_counter": {"status": report.request_counter_status},
        "problem_attempt": {
            "total": report.problem_attempt_total,
            "reached": report.problem_attempt_reached,
        },
        "theta_eligible_response": {
            "total": report.theta_eligible_response_total,
            "reached": report.theta_eligible_reached,
        },
        "weak_concept_signal_pair": {
            "total": report.weak_concept_signal_pair_total,
            "reached": report.weak_concept_signal_reached,
        },
        "candidate_pool_structural_cap": report.candidate_pool_structural_cap,
        "next_problem_candidate_pool_size": _NEXT_PROBLEM_CANDIDATE_POOL_SIZE,
        "recommendation_treatment_policy_metadata": {
            "total": report.recommendation_treatment_total,
            "with_policy_metadata": report.recommendation_treatment_with_policy_metadata_total,
            "rate": report.recommendation_treatment_policy_metadata_rate,
        },
    }


def dump_json(report: ReachReport) -> str:
    return json.dumps(report_to_json(report), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


# ──────────────────────────────────────────────────────────────────────────
# CLI (얇은 껍데기 — DB 세션 열고 닫기·입출력만, 집계는 위 순수 코어)
# ──────────────────────────────────────────────────────────────────────────
async def _run() -> ReachReport:
    """세션을 열어 5축을 실측하고 리포트를 조립한다(조회 전용·쓰기 0). 종료 시 엔진 정리."""
    sessionmaker = get_sessionmaker()
    try:
        async with sessionmaker() as session:
            counts = await fetch_reach_counts(session)
    finally:
        await dispose_engine()
    return build_report(counts)


def main(argv: list[str] | None = None) -> int:
    """CLI 엔트리 — 추천 도달 관측 리포트를 stdout에 출력. **0=성공 / 2=실행 오류**(1 없음).

    수치가 전부 '미도달'이어도 exit 0이다(게이트 아님). exit 2는 DB 접속 자체가 안 되는 등
    실행 전제가 충족되지 않을 때만 쓴다 — 예외를 삼키지 않고 **타입명**을 stderr에 남긴다
    (`str(exc)`엔 DSN 등 환경값이 섞일 수 있어 우선 타입명만 메시지 앞에 싣는다).
    """
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.ops.recommendation_reach_report",
        description=(
            "추천 도달 관측 리포트(REC-01) — problem_attempt 적재·θ 추정 유효 응답·개인화 "
            "가중 적용 가능 건수·후보 풀 구조적 상한·candidates/policy_version 기록률"
            "(REC-11)을 실 DB에서 집계한다. 결정론적 exit 0/2"
            "(게이트 아님). 추천 요청 수는 카운터가 없어 그 사실 자체를 보고한다."
        ),
    )
    parser.add_argument(
        "--json", dest="json_path", type=Path, default=None, help="JSON 산출물 경로(선택)"
    )
    args = parser.parse_args(argv)

    try:
        report = asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001 — 침묵 실패 금지: 실행 오류를 타입명과 함께 보고
        print(
            f"실행 오류 — 추천 도달 리포트 생성 실패({type(exc).__name__}): {exc}",
            file=sys.stderr,
        )
        return _EXIT_RUNTIME_ERROR

    print(render_report(report))
    if args.json_path is not None:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(dump_json(report), encoding="utf-8")
        print(f"JSON 산출물: {args.json_path}")
    return _EXIT_OK


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트
    sys.exit(main())
