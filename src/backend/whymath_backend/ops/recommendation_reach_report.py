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

6. **선택 θ 규칙 발동률**(EOS-147·EOS-39) — 같은 처치 기록에서 "추천이 추정 θ가 아니라 규칙이 만든
   표적 θ로 골랐는가"를 센다. `selection_theta` 키(선택 θ ≠ 추정 θ — 전부 정답 상한 사다리·도움
   접기)·`theta_boundary`(`upper`·`lower`)·`selection_help_count`(코치 도움 완료를 실패로 접은
   문항이 있는 처치)·`selection_hint_unknown_count`(힌트 귀속 미상이 섞인 처치)의 **비율**이다
   ("작동한 비율" — 200 응답은 규칙이 일했다는 증거가 아니다). 분모(처치 0건)는 None이다.
   키가 없는 것은 "규칙이 안 돌았다"일 수도, 킬 스위치(`l2_selection_help_fold_enabled`)가 꺼졌던
   기간일 수도 있다 — 두 상태는 이 키만으로 구분되지 않으므로 배포·스위치 기간과 함께 읽는다.

7. **코치 단계 공급 구성**(EOS-178) — EOS-39 선택 θ 접기의 입력인 `used_hint`가 읽는 공급 원장
   (`attempt_event` `힌트제공`)에서, 단계 2 이상 공급이 **학생 신호**로 올랐는가 **라벨만으로**
   올랐는가를 센다. 원장 행의 `base_level`(능력 라벨 없이 계산한 단계 — `hint_level`과 나란히
   적힌다)이 2 미만이면 라벨만으로 올라간 공급이다. 같은 (학생·문항) 안에 학생 신호 공급이 하나도
   없으면 그 라벨은 학생 행동으로 **확인되지 않았다**. 구판 행(`base_level` 없음)은 분류할 수 없어
   분모에서 따로 센다(0으로 접지 않는다). 이 축은 구판 규칙(EOS-133: 최종 단계 2 이상은 전부
   도움)이 독립 성공을 얼마나 도움으로 오귀속했을지의 **상한 신호**이고, 킬 스위치
   `l4_hint_attribution_label_free_enabled`를 끌지 판단하는 근거다.

8. **코치 라벨의 예측 타당도**(EOS-179) — §7이 *구성*을 센다면 이 축은 라벨('초보'|'발전 중'|
   '숙달')이 학생 신호를 **맞히는가**를 잰다. 단위는 (학생·문항) 쌍이다: 그 문항의 *첫* 공급 행이
   단 라벨(`ability_level`)을 층으로, 같은 쌍의 공급 행 중 `base_level >= 2`(학생 신호)가 하나라도
   있었는지를 결과로 센다(창 함수 `row_number() over (partition by user_id, problem_id order by
   event_at)`). '초보'의 정밀도(= '초보' 쌍 중 신호가 나온 비율)·재현율(= 신호가 나온 쌍 중
   첫 라벨이 '초보'였던 비율)과, 변별 여부를 가리는 대조(= '초보'가 아닌 라벨의 신호율)를
   **건수와 함께 Wilson 단측 95% 경계로** 낸다 — 점추정만 내면 30쌍 표본의 1%대 비율을
   가리지 못한다(0/30의 단측 상한이 8.3%). 분모가 0이면 비율은 None이고(0과 구별)
   **판정·임계는 이 리포트가 내지 않는다**(합성 표본으로 임계를 정하지 않는다 — 임계 판정은
   후속 EOS-180). 라벨 출처(`label_source`)로 '서버 파생' 보기를 따로 낸다 — 클라가 정한
   라벨의 정확도는 서버 라벨의 정확도가 아니다. `--min-label-evidence-n K`는 첫 행의 라벨이
   서버 개념 숙달도 관측 K건 이상에서 나온 쌍만 본다(K의 값은 운영 데이터를 보며 고른다 —
   이 리포트가 정하지 않는다).

집계 코어(`build_report`)는 순수 함수(원시 카운트 → 리포트)라 hermetic 테스트로 전량
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

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.activity import AttemptEvent, ProblemAttempt
from whymath_backend.db.models.assessment import ConceptMasteryHistory
from whymath_backend.db.models.evidence_event import EvidenceEvent
from whymath_backend.db.models.problem import Problem
from whymath_backend.db.session import dispose_engine, get_sessionmaker
from whymath_backend.harness.wilson import wilson_lower_bound, wilson_upper_bound
from whymath_backend.l2.recommendation_evidence import (
    EVENT_TYPE_RECOMMENDATION_TREATMENT,
    META_KEY_CANDIDATES,
    META_KEY_POLICY_VERSION,
    META_KEY_SELECTION_HELP_COUNT,
    META_KEY_SELECTION_HINT_UNKNOWN_COUNT,
    META_KEY_SELECTION_THETA,
    META_KEY_THETA_BOUNDARY,
)
from whymath_backend.schema.enums import EventType

__all__ = [
    "NOT_REACHED",
    "REQUEST_COUNTER_STATUS",
    "LabelValidityRow",
    "LabelValidityView",
    "ReachCounts",
    "ReachReport",
    "WilsonRate",
    "build_report",
    "fetch_label_validity",
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
# DB 접속 경계 — 실제 쿼리 11회(전부 SQLAlchemy Core, 원시 SQL 0).
# ──────────────────────────────────────────────────────────────────────────
@dataclass(slots=True, frozen=True)
class ReachCounts:
    """DB에서 실측한 원시 카운트 11종 — `build_report`(순수)의 유일한 입력.

    뒤의 5종(EOS-39 — 선택 θ 규칙 발동률)은 기본값 0이다: 이 필드 이전 생성자 호출처(테스트 등)와의
    호환용이고, 값 0은 "분자가 0"일 뿐 "분모 없음"이 아니다(분모는
    `recommendation_treatment_total`).
    """

    problem_attempt_total: int
    theta_eligible_response_total: int
    weak_concept_signal_pair_total: int
    candidate_pool_structural_cap: int
    recommendation_treatment_total: int
    recommendation_treatment_with_policy_metadata_total: int
    #: 처치 중 `selection_theta` 키가 있는 건수(선택 θ ≠ 추정 θ — 상한 사다리·도움 접기).
    selection_theta_key_total: int = 0
    #: 처치 중 `theta_boundary == "upper"`(전부 정답)·`"lower"`(전부 오답)인 건수.
    theta_boundary_upper_total: int = 0
    theta_boundary_lower_total: int = 0
    #: 처치 중 `selection_help_count` 키가 있는 건수(코치 도움 완료를 실패로 접은 문항이 있었다).
    selection_help_key_total: int = 0
    #: 처치 중 `selection_hint_unknown_count` 키가 있는 건수(힌트 귀속 미상이 섞였다).
    selection_hint_unknown_key_total: int = 0
    #: EOS-178 — 공급 원장(`힌트제공`) 행 중 단계 2 이상(도움 후보)인 건수.
    coach_supply_help_row_total: int = 0
    #: 위 중 `base_level`이 실린 행(라벨 없는 단계로 분류 가능한 신판 행).
    coach_supply_classified_row_total: int = 0
    #: 분류된 행 중 `base_level < 2` — 학생 신호 없이 **라벨만으로** 올라간 공급.
    coach_supply_label_only_row_total: int = 0
    #: 라벨-단독 행 중 검수 힌트가 실제로 실린(`hint_id`) 행.
    coach_supply_label_only_served_row_total: int = 0
    #: 라벨-단독 행이 하나라도 있는 (학생·문항) 쌍 수.
    coach_label_only_pair_total: int = 0
    #: 그 쌍 중 학생 신호 공급(`base_level >= 2`)이 하나도 없는 쌍 — 라벨이 학생 행동으로
    #: 확인되지 않았다.
    coach_label_only_unsignaled_pair_total: int = 0
    #: EOS-179 — 라벨 예측 타당도의 (라벨, 출처, 쌍 수, 신호 쌍 수) 칸. 쌍 = 문항의 첫 공급 행이
    #: 라벨을 가졌고 같은 쌍의 모든 공급 행에 `base_level`이 실려 신호 판정이 가능한 쌍.
    coach_label_validity_cells: tuple[tuple[str, str | None, int, int], ...] = ()
    #: 첫 공급 행에 라벨(`ability_level`)이 없는 쌍 수 — 타당도 표에서 제외된다.
    coach_label_unlabeled_pair_total: int = 0
    #: 라벨은 있으나 `base_level`이 없는 행이 섞여 신호 판정이 불가능한 쌍 수 — 제외된다.
    coach_label_unclassified_pair_total: int = 0
    #: 이 읽기가 적용한 증거 수 하한(`--min-label-evidence-n`). None=걸지 않음.
    coach_label_min_evidence_n: int | None = None


async def fetch_reach_counts(
    session: AsyncSession, *, min_label_evidence_n: int | None = None
) -> ReachCounts:
    """실측 카운트를 쿼리 18회로 산출한다(전부 SQLAlchemy Core — 원시 SQL 0).

    각 쿼리의 의미는 모듈 docstring "실제로 DB에서 직접 측정하는 축" 참조.
    쿼리 순서는 테스트(큐 기반 가짜 세션)와 계약이므로 바꾸지 않는다: ① problem_attempt
    전체 행 수 ② θ 추정 유효 응답 ③ 개인화(BKT) 유니크 (user, concept) 쌍 ④ 후보 풀 구조적
    상한 ⑤ REC-11 candidates·policy_version 기록률(분모) ⑥ 그 분자 ⑦ `selection_theta` 키
    ⑧ `theta_boundary=upper` ⑨ `theta_boundary=lower` ⑩ `selection_help_count` 키
    ⑪ `selection_hint_unknown_count` 키(EOS-39 — 전부 `recommendation_render` 처치 안에서)
    ⑫ 공급 원장 단계 2+ 행 ⑬ 그중 `base_level` 있는 행 ⑭ 그중 `base_level<2`(라벨-단독) ⑮ 그중
    `hint_id` 있는 행 ⑯ 라벨-단독 행이 있는 (학생·문항) 쌍 ⑰ 그중 학생 신호 공급이 없는 쌍(EOS-178)
    ⑱ 라벨 예측 타당도 — 첫 공급 행 라벨 × 출처별 (학생·문항) 쌍과 신호 쌍(EOS-179 · 행 단위가
    아니라 `fetch_label_validity`가 한 쿼리로 읽는다).
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

    # EOS-39 — 선택 θ 규칙 발동률(같은 처치 모집단 안에서 키·값이 있는 건수). JSONB 키 존재는
    # `has_key`, 값 비교는 `->>` 연산자(Core `op`)다 — 원시 SQL 0.
    async def _count_treatments(*conditions: Any) -> int:
        return int((await session.execute(treatment_total_stmt.where(*conditions))).scalar_one())

    selection_theta_key_total = await _count_treatments(
        EvidenceEvent.meta.has_key(META_KEY_SELECTION_THETA)
    )
    boundary_text = EvidenceEvent.meta.op("->>")(META_KEY_THETA_BOUNDARY)
    boundary_upper_total = await _count_treatments(boundary_text == "upper")
    boundary_lower_total = await _count_treatments(boundary_text == "lower")
    help_key_total = await _count_treatments(
        EvidenceEvent.meta.has_key(META_KEY_SELECTION_HELP_COUNT)
    )
    hint_unknown_key_total = await _count_treatments(
        EvidenceEvent.meta.has_key(META_KEY_SELECTION_HINT_UNKNOWN_COUNT)
    )

    # EOS-178 — 공급 원장의 단계 공급 구성. `hint_level`·`base_level`은 JSONB 정수 키다
    # (`->>` 캐스팅 — 키가 없거나 JSON null이면 SQL NULL이라 비교가 거짓이 된다 = 구판 행이
    # 분류에서 빠지는 방식).
    supply_level = AttemptEvent.event_data["hint_level"].as_integer()
    supply_base = AttemptEvent.event_data["base_level"].as_integer()
    supply_served = AttemptEvent.event_data["hint_id"].as_string()
    supply_stmt = (
        select(func.count())
        .select_from(AttemptEvent)
        .where(AttemptEvent.event_type == EventType.힌트제공, supply_level >= 2)
    )

    async def _count_supply(*conditions: Any) -> int:
        return int((await session.execute(supply_stmt.where(*conditions))).scalar_one())

    supply_help_total = await _count_supply()
    supply_classified_total = await _count_supply(supply_base.isnot(None))
    supply_label_only_total = await _count_supply(supply_base < 2)
    # `hint_id`가 비어 있지 않은 문자열일 때만 검수 힌트가 실린 것이다 — 키가 없거나 JSON null이면
    # `->>`가 SQL NULL이고 `NULL != ''`도 NULL이라 이 조건 하나로 함께 빠진다.
    supply_label_only_served_total = await _count_supply(supply_base < 2, supply_served != "")
    # (학생·문항) 쌍 — 라벨-단독 행이 있는 쌍과, 그중 학생 신호 행이 없는 쌍. `bool_or`는 NULL을
    # 무시하므로 구판 행뿐인 쌍은 둘 다 NULL이고 `is_(True)` 필터에서 빠진다.
    pair_stats = (
        select(
            AttemptEvent.user_id,
            AttemptEvent.problem_id,
            func.bool_or(and_(supply_level >= 2, supply_base < 2)).label("has_label_only"),
            func.bool_or(supply_base >= 2).label("has_signal"),
        )
        .where(AttemptEvent.event_type == EventType.힌트제공)
        .group_by(AttemptEvent.user_id, AttemptEvent.problem_id)
        .subquery()
    )
    label_only_pair_stmt = (
        select(func.count()).select_from(pair_stats).where(pair_stats.c.has_label_only.is_(True))
    )
    label_only_pair_total = int((await session.execute(label_only_pair_stmt)).scalar_one())
    # 라벨-단독 행이 있는 쌍은 `base_level`이 실린 행을 반드시 가지므로 `has_signal`이 NULL일 수
    # 없다(`bool_or`는 그 행들의 참·거짓을 본다) — `is_(False)`만으로 "신호 없음"이 선다.
    label_only_unsignaled_pair_total = int(
        (
            await session.execute(label_only_pair_stmt.where(pair_stats.c.has_signal.is_(False)))
        ).scalar_one()
    )

    validity = await fetch_label_validity(session, min_evidence_n=min_label_evidence_n)

    return ReachCounts(
        problem_attempt_total=attempt_total,
        theta_eligible_response_total=eligible_total,
        weak_concept_signal_pair_total=pair_total,
        candidate_pool_structural_cap=pool_cap,
        recommendation_treatment_total=treatment_total,
        recommendation_treatment_with_policy_metadata_total=with_policy_metadata_total,
        selection_theta_key_total=selection_theta_key_total,
        theta_boundary_upper_total=boundary_upper_total,
        theta_boundary_lower_total=boundary_lower_total,
        selection_help_key_total=help_key_total,
        selection_hint_unknown_key_total=hint_unknown_key_total,
        coach_supply_help_row_total=supply_help_total,
        coach_supply_classified_row_total=supply_classified_total,
        coach_supply_label_only_row_total=supply_label_only_total,
        coach_supply_label_only_served_row_total=supply_label_only_served_total,
        coach_label_only_pair_total=label_only_pair_total,
        coach_label_only_unsignaled_pair_total=label_only_unsignaled_pair_total,
        coach_label_validity_cells=validity.cells,
        coach_label_unlabeled_pair_total=validity.unlabeled_pair_total,
        coach_label_unclassified_pair_total=validity.unclassified_pair_total,
        coach_label_min_evidence_n=min_label_evidence_n,
    )


@dataclass(slots=True, frozen=True)
class _LabelValidityRead:
    """`fetch_label_validity`의 반환 — 칸·제외 쌍 수(`ReachCounts`에 그대로 옮겨 싣는다)."""

    cells: tuple[tuple[str, str | None, int, int], ...]
    unlabeled_pair_total: int
    unclassified_pair_total: int


async def fetch_label_validity(
    session: AsyncSession, *, min_evidence_n: int | None = None
) -> _LabelValidityRead:
    """코치 라벨의 예측 타당도 원자료(EOS-179 · 쿼리 1회 · 조회 전용).

    (학생·문항) 쌍마다 **첫 공급 행**(`event_at` 오름차순 1번)의 라벨(`ability_level`)·출처
    (`label_source`)를 읽고, 같은 쌍의 모든 공급 행에서 학생 신호(`base_level >= 2`)가 하나라도
    있었는지(`bool_or`)와 모든 행에 `base_level`이 실렸는지(`bool_and`)를 창 함수로 함께 계산한 뒤,
    (라벨·출처·분류 가능 여부)로 묶어 쌍 수와 신호 쌍 수를 센다.

    - 첫 행에 라벨이 없으면(`ability_level`이 NULL·빈 문자열) **라벨 없음**으로 따로 센다 — 두 번째
      행의 라벨로 건너뛰지 않는다: 라벨은 그 문항의 *첫 노출 시점*의 예측이어야 하고, 이후 행의
      라벨은 학생이 푼 뒤의 숙달도라 이미 결과의 영향을 받았다.
    - 같은 쌍에 `base_level` 없는 행이 하나라도 섞이면(구판 행·롤백) 신호 없음을 확신할 수 없어
      **분류 불가**로 따로 센다 — 신호 없음(False)으로 접지 않는다(`bool_or`는 NULL을 무시하므로
      그대로 두면 구판 행이 섞인 쌍이 "신호 없음"으로 읽힌다).
    - `min_evidence_n`이 주어지면 첫 행의 `label_evidence_n >= K`인 쌍만 센다(NULL=모름은 빠진다).
      K의 값은 이 함수가 정하지 않는다.

    같은 쌍의 같은 `event_at`을 가진 행은 순차 턴에서 생길 수 없어 동순위 처리를 따로 두지 않는다.
    """
    part = (AttemptEvent.user_id, AttemptEvent.problem_id)
    level = AttemptEvent.event_data["ability_level"].as_string()
    base = AttemptEvent.event_data["base_level"].as_integer()
    ranked = (
        select(
            # 빈 문자열은 라벨 없음과 같게 본다(`hint_id`의 `!= ''` 관례와 동형).
            func.nullif(level, "").label("label"),
            AttemptEvent.event_data["label_source"].as_string().label("source"),
            AttemptEvent.event_data["label_evidence_n"].as_integer().label("evidence_n"),
            func.bool_or(base >= 2).over(partition_by=part).label("has_signal"),
            func.bool_and(base.isnot(None)).over(partition_by=part).label("all_classified"),
            func.row_number()
            .over(partition_by=part, order_by=AttemptEvent.event_at.asc())
            .label("rn"),
        )
        .where(AttemptEvent.event_type == EventType.힌트제공)
        .subquery()
    )
    stmt = (
        select(
            ranked.c.label,
            ranked.c.source,
            ranked.c.all_classified,
            func.count().label("pairs"),
            func.count().filter(ranked.c.has_signal.is_(True)).label("signal_pairs"),
        )
        .where(ranked.c.rn == 1)
        .group_by(ranked.c.label, ranked.c.source, ranked.c.all_classified)
    )
    if min_evidence_n is not None:
        stmt = stmt.where(ranked.c.evidence_n >= min_evidence_n)

    cells: list[tuple[str, str | None, int, int]] = []
    unlabeled = 0
    unclassified = 0
    for label, source, all_classified, pairs, signal_pairs in (await session.execute(stmt)).all():
        if label is None:
            unlabeled += int(pairs)
        elif all_classified is not True:
            unclassified += int(pairs)
        else:
            cells.append((str(label), source, int(pairs), int(signal_pairs)))
    return _LabelValidityRead(
        cells=tuple(sorted(cells, key=lambda c: (c[0], c[1] or ""))),
        unlabeled_pair_total=unlabeled,
        unclassified_pair_total=unclassified,
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
    #: EOS-39 — 선택 θ 규칙 발동률. 분모는 `recommendation_treatment_total`이고 0이면 비율은 None.
    selection_theta_key_total: int
    selection_theta_key_rate: float | None
    theta_boundary_upper_total: int
    theta_boundary_upper_rate: float | None
    theta_boundary_lower_total: int
    theta_boundary_lower_rate: float | None
    selection_help_key_total: int
    selection_help_key_rate: float | None
    selection_hint_unknown_key_total: int
    selection_hint_unknown_key_rate: float | None
    #: EOS-178 — 코치 단계 공급 구성. 분모가 0이면 비율은 None(0과 구별).
    coach_supply_help_row_total: int
    coach_supply_classified_row_total: int
    coach_supply_classified_rate: float | None
    coach_supply_label_only_row_total: int
    coach_supply_label_only_rate: float | None
    coach_supply_label_only_served_row_total: int
    coach_supply_label_only_served_rate: float | None
    coach_label_only_pair_total: int
    coach_label_only_unsignaled_pair_total: int
    coach_label_only_unsignaled_rate: float | None
    #: EOS-179 — 코치 라벨의 예측 타당도. `all`은 모든 출처, `server`는 서버가 만든 라벨(출처가
    #: `server_bkt`·`server_theta`)만. 판정·임계는 싣지 않는다(후속 EOS-180).
    coach_label_validity_all: LabelValidityView
    coach_label_validity_server: LabelValidityView
    coach_label_unlabeled_pair_total: int
    coach_label_unclassified_pair_total: int
    #: 라벨·신호 판정이 모두 있으나 출처가 적히지 않은 쌍(EOS-179 이전 행) — `all`에만 들어간다.
    coach_label_source_unknown_pair_total: int
    coach_label_min_evidence_n: int | None


# 타당도 표의 고정 라벨 순서 — 원장에 없는 라벨도 0쌍 행으로 보인다("없다"와 "안 봤다"를 가른다).
NOVICE_LABEL = "초보"
_LABEL_ORDER = ("초보", "발전 중", "숙달")
#: 서버가 라벨을 만든 출처 — 클라가 직접 보낸('explicit')·클라 제출 bkt('client_bkt') 라벨은
#: 서버 라벨의 정확도가 아니라 앱이 정한 값의 정확도라 이 보기에서 뺀다.
_SERVER_LABEL_SOURCES = frozenset({"server_bkt", "server_theta"})


@dataclass(slots=True, frozen=True)
class WilsonRate:
    """분자·분모·비율과 Wilson 단측 95% 경계 — 분모가 0이면 비율·경계는 전부 None(0과 구별)."""

    numerator: int
    denominator: int
    rate: float | None
    lower95: float | None
    upper95: float | None


def _wilson_rate(numerator: int, denominator: int) -> WilsonRate:
    if denominator == 0:
        return WilsonRate(numerator, 0, None, None, None)
    return WilsonRate(
        numerator,
        denominator,
        numerator / denominator,
        wilson_lower_bound(numerator, denominator),
        wilson_upper_bound(numerator, denominator),
    )


@dataclass(slots=True, frozen=True)
class LabelValidityRow:
    """한 라벨의 칸 — `signal`의 분모는 그 라벨이 첫 공급 행에 달린 쌍, 분자는 신호가 나온 쌍."""

    label: str
    signal: WilsonRate


@dataclass(slots=True, frozen=True)
class LabelValidityView:
    """한 보기(모든 출처 / 서버 출처)의 라벨별 신호율과 '초보'의 정밀도·재현율·대조."""

    pair_total: int
    signal_pair_total: int
    rows: tuple[LabelValidityRow, ...]
    #: '초보' 정밀도 — 첫 라벨이 '초보'인 쌍 중 신호가 나온 비율.
    novice_precision: WilsonRate
    #: '초보' 재현율 — 신호가 나온 쌍 중 첫 라벨이 '초보'였던 비율.
    novice_recall: WilsonRate
    #: 대조 — '초보'가 아닌 라벨의 신호율. 라벨과 무관하게 같다면 라벨은 신호를 변별하지 못한다.
    other_signal_rate: WilsonRate


def _label_validity_view(
    cells: tuple[tuple[str, str | None, int, int], ...], sources: frozenset[str] | None
) -> LabelValidityView:
    """칸들을 라벨별로 합산해 한 보기를 만든다(`sources`가 None이면 전 출처·아니면 그 출처만)."""
    pairs: dict[str, int] = {}
    signals: dict[str, int] = {}
    for label, source, cell_pairs, cell_signals in cells:
        if sources is not None and source not in sources:
            continue
        pairs[label] = pairs.get(label, 0) + cell_pairs
        signals[label] = signals.get(label, 0) + cell_signals
    # 고정 순서 + 원장에만 있는 낯선 라벨(정렬) — 조용히 버리면 분모가 어긋난다.
    labels = list(_LABEL_ORDER) + sorted(k for k in pairs if k not in _LABEL_ORDER)
    rows = tuple(
        LabelValidityRow(k, _wilson_rate(signals.get(k, 0), pairs.get(k, 0))) for k in labels
    )
    pair_total = sum(pairs.values())
    signal_total = sum(signals.values())
    novice_pairs = pairs.get(NOVICE_LABEL, 0)
    novice_signals = signals.get(NOVICE_LABEL, 0)
    return LabelValidityView(
        pair_total=pair_total,
        signal_pair_total=signal_total,
        rows=rows,
        novice_precision=_wilson_rate(novice_signals, novice_pairs),
        novice_recall=_wilson_rate(novice_signals, signal_total),
        other_signal_rate=_wilson_rate(signal_total - novice_signals, pair_total - novice_pairs),
    )


def _rate(numerator: int, denominator: int) -> float | None:
    """분모 없는 비율은 None — 0/0을 0.0으로 지어내지 않는다(이 모듈의 None-vs-0 회계 원칙)."""
    return None if denominator == 0 else numerator / denominator


def build_report(counts: ReachCounts) -> ReachReport:
    """원시 카운트 → `ReachReport`(순수·부작용 0). `reached`는 count>0(분모 없는 0 방지).

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
        selection_theta_key_total=counts.selection_theta_key_total,
        selection_theta_key_rate=_rate(
            counts.selection_theta_key_total, counts.recommendation_treatment_total
        ),
        theta_boundary_upper_total=counts.theta_boundary_upper_total,
        theta_boundary_upper_rate=_rate(
            counts.theta_boundary_upper_total, counts.recommendation_treatment_total
        ),
        theta_boundary_lower_total=counts.theta_boundary_lower_total,
        theta_boundary_lower_rate=_rate(
            counts.theta_boundary_lower_total, counts.recommendation_treatment_total
        ),
        selection_help_key_total=counts.selection_help_key_total,
        selection_help_key_rate=_rate(
            counts.selection_help_key_total, counts.recommendation_treatment_total
        ),
        selection_hint_unknown_key_total=counts.selection_hint_unknown_key_total,
        selection_hint_unknown_key_rate=_rate(
            counts.selection_hint_unknown_key_total, counts.recommendation_treatment_total
        ),
        coach_supply_help_row_total=counts.coach_supply_help_row_total,
        coach_supply_classified_row_total=counts.coach_supply_classified_row_total,
        coach_supply_classified_rate=_rate(
            counts.coach_supply_classified_row_total, counts.coach_supply_help_row_total
        ),
        coach_supply_label_only_row_total=counts.coach_supply_label_only_row_total,
        coach_supply_label_only_rate=_rate(
            counts.coach_supply_label_only_row_total, counts.coach_supply_classified_row_total
        ),
        coach_supply_label_only_served_row_total=counts.coach_supply_label_only_served_row_total,
        coach_supply_label_only_served_rate=_rate(
            counts.coach_supply_label_only_served_row_total,
            counts.coach_supply_label_only_row_total,
        ),
        coach_label_only_pair_total=counts.coach_label_only_pair_total,
        coach_label_only_unsignaled_pair_total=counts.coach_label_only_unsignaled_pair_total,
        coach_label_only_unsignaled_rate=_rate(
            counts.coach_label_only_unsignaled_pair_total, counts.coach_label_only_pair_total
        ),
        coach_label_validity_all=_label_validity_view(counts.coach_label_validity_cells, None),
        coach_label_validity_server=_label_validity_view(
            counts.coach_label_validity_cells, _SERVER_LABEL_SOURCES
        ),
        coach_label_unlabeled_pair_total=counts.coach_label_unlabeled_pair_total,
        coach_label_unclassified_pair_total=counts.coach_label_unclassified_pair_total,
        coach_label_source_unknown_pair_total=sum(
            c[2] for c in counts.coach_label_validity_cells if c[1] is None
        ),
        coach_label_min_evidence_n=counts.coach_label_min_evidence_n,
    )


# ──────────────────────────────────────────────────────────────────────────
# 렌더 — 사람이 읽는 마크다운 + 기계가 읽는 JSON
# ──────────────────────────────────────────────────────────────────────────
def _status_label(reached: bool) -> str:
    return _MEASURED if reached else NOT_REACHED


def _fmt_axis(total: int, rate: float | None) -> str:
    """`건수 (비율)` — 분모 없는 비율(None)은 '미도달'로 적는다(0.0%로 위장하지 않는다)."""
    return f"**{total}**" if rate is None else f"**{total}** ({rate:.1%})"


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
    lines += [
        "",
        "## 6. 선택 θ 규칙 발동률 (EOS-147·EOS-39 — '작동한 비율')",
        "",
        f"- 분모(처치 기록 전체): **{report.recommendation_treatment_total}**",
    ]
    if report.recommendation_treatment_total == 0:
        lines.append(f"- 발동률 전 축: {NOT_REACHED}(처치 기록 0건 — 분모 없음)")
    else:
        axes = (
            (
                "`selection_theta` 키(선택 θ ≠ 추정 θ)",
                report.selection_theta_key_total,
                report.selection_theta_key_rate,
            ),
            (
                "`theta_boundary=upper`(전부 정답)",
                report.theta_boundary_upper_total,
                report.theta_boundary_upper_rate,
            ),
            (
                "`theta_boundary=lower`(전부 오답)",
                report.theta_boundary_lower_total,
                report.theta_boundary_lower_rate,
            ),
            (
                "`selection_help_count` 키(코치 도움 완료를 실패로 접음)",
                report.selection_help_key_total,
                report.selection_help_key_rate,
            ),
            (
                "`selection_hint_unknown_count` 키(힌트 귀속 미상 섞임)",
                report.selection_hint_unknown_key_total,
                report.selection_hint_unknown_key_rate,
            ),
        )
        lines += [f"- {label}: {_fmt_axis(total, rate)}" for label, total, rate in axes]
        lines.append(
            "  - 키가 없는 처치는 '규칙이 안 돌았다'이거나 킬 스위치"
            "(`l2_selection_help_fold_enabled`)가 꺼진 기간이다 — 배포·스위치 기간과 함께 읽는다."
        )
    lines += [
        "",
        "## 7. 코치 단계 공급 구성 (EOS-178 — 라벨만으로 올라간 단계가 얼마인가)",
        "",
        f"- 공급 원장 단계 2+ 행(도움 후보): **{report.coach_supply_help_row_total}**",
    ]
    if report.coach_supply_help_row_total == 0:
        lines.append(f"- 구성 전 축: {NOT_REACHED}(단계 2+ 공급 행 0건 — 분모 없음)")
    else:
        classified = _fmt_axis(
            report.coach_supply_classified_row_total, report.coach_supply_classified_rate
        )
        label_only = _fmt_axis(
            report.coach_supply_label_only_row_total, report.coach_supply_label_only_rate
        )
        served = _fmt_axis(
            report.coach_supply_label_only_served_row_total,
            report.coach_supply_label_only_served_rate,
        )
        unsignaled = _fmt_axis(
            report.coach_label_only_unsignaled_pair_total, report.coach_label_only_unsignaled_rate
        )
        lines += [
            f"- `base_level`이 실려 분류 가능한 행: {classified}"
            " — 나머지는 구판 행(분류 불가·종전 규칙으로 센다)",
            f"- 그중 **라벨만으로 올라간** 행(`base_level<2`): {label_only}",
            f"- 라벨-단독 행 중 검수 힌트가 실제로 실린 행: {served}"
            " — 이 행은 라벨이 올렸어도 도움으로 센다",
            f"- 라벨-단독 행이 있는 (학생·문항) 쌍: **{report.coach_label_only_pair_total}**, "
            f"그중 학생 신호 공급이 하나도 없는 쌍: {unsignaled}",
            "  - 신호 없는 쌍의 비율이 높으면 라벨('초보')이 학생 행동으로 확인되지 않는다는 "
            "뜻이다 — 구판 규칙이었다면 그 쌍의 독립 완료가 도움으로 접혔을 것이다"
            "(상한 신호·확정 오귀속 수 아님).",
            "  - 라벨-단독 행 비율이 높은데 신호 없는 쌍 비율이 낮으면 라벨이 정확하다는 쪽의 "
            "증거다 — 킬 스위치(`l4_hint_attribution_label_free_enabled`)를 끄고 구판 규칙으로 "
            "돌아갈지 판단한다.",
        ]
    lines += _render_label_validity(report)
    lines.append("")
    return "\n".join(lines)


def _fmt_wilson(r: WilsonRate) -> str:
    """`분자/분모 = 비율 (Wilson 단측 95% 하한·상한)` — 분모 0이면 '미도달'(0.0%로 위장 금지)."""
    if r.rate is None or r.lower95 is None or r.upper95 is None:
        return f"{NOT_REACHED}(분모 0)"
    return (
        f"**{r.numerator}/{r.denominator}** = {r.rate:.1%} "
        f"(Wilson 단측 95% 하한 {r.lower95:.1%} · 상한 {r.upper95:.1%})"
    )


def _render_label_validity_view(title: str, view: LabelValidityView) -> list[str]:
    lines = [
        f"- **{title}** — (학생·문항) 쌍 **{view.pair_total}**, "
        f"그중 신호 쌍 **{view.signal_pair_total}**"
    ]
    if view.pair_total == 0:
        lines.append(
            f"  - 타당도 전 축: {NOT_REACHED}(라벨·신호 판정이 모두 있는 쌍 0건 — 분모 없음)"
        )
        return lines
    lines += [f"  - 첫 라벨 `{row.label}` → 신호율 {_fmt_wilson(row.signal)}" for row in view.rows]
    lines += [
        f"  - '초보' 정밀도(첫 라벨이 '초보'인 쌍 중 신호): {_fmt_wilson(view.novice_precision)}",
        f"  - '초보' 재현율(신호가 난 쌍 중 첫 라벨이 '초보'): {_fmt_wilson(view.novice_recall)}",
        f"  - 대조 — '초보' 아닌 라벨의 신호율: {_fmt_wilson(view.other_signal_rate)}",
    ]
    return lines


def _render_label_validity(report: ReachReport) -> list[str]:
    lines = [
        "",
        "## 8. 코치 라벨의 예측 타당도 (EOS-179 — '초보'가 학생 신호를 맞히는가)",
        "",
        "- 단위: (학생·문항) 쌍. 문항의 **첫** 공급 행에 달린 라벨별로, 같은 쌍의 공급 행 중 "
        "학생 신호(`base_level>=2`)가 하나라도 있었는지를 센다. 임계·판정은 이 리포트가 내지 "
        "않는다(건수와 Wilson 경계만 — 임계 판정은 후속 EOS-180).",
    ]
    if report.coach_label_min_evidence_n is not None:
        lines.append(
            "- 증거 수 하한 적용: 첫 라벨이 서버 개념 숙달도 관측 "
            f"**{report.coach_label_min_evidence_n}건 이상**에서 나온 쌍만 본다"
            "(증거 수를 모르는 쌍은 빠진다)."
        )
    lines += [
        "- 표에서 **제외**된 쌍 — 첫 공급 행에 라벨 없음: "
        f"**{report.coach_label_unlabeled_pair_total}** · 신호 판정 불가"
        f"(`base_level` 없는 구판 행이 섞임): **{report.coach_label_unclassified_pair_total}**",
    ]
    lines += _render_label_validity_view("모든 출처", report.coach_label_validity_all)
    if report.coach_label_source_unknown_pair_total:
        lines.append(
            f"  - 이 중 라벨 출처가 적히지 않은 쌍(EOS-179 이전 행): "
            f"**{report.coach_label_source_unknown_pair_total}** — 아래 서버 보기에서는 빠진다."
        )
    lines += _render_label_validity_view(
        "서버가 만든 라벨만(`server_bkt`·`server_theta`)", report.coach_label_validity_server
    )
    lines += [
        "  - 읽는 법: '초보'의 신호율이 다른 라벨보다 **뚜렷이 높아야** 라벨이 도움 필요를 "
        "변별한다. 라벨과 무관하게 비슷하면 라벨은 신호를 예측하지 못한다 — 하한·상한이 겹치는 "
        "구간은 표본이 그 차이를 가리지 못한다는 뜻이다.",
    ]
    return lines


def _wilson_json(r: WilsonRate) -> dict[str, Any]:
    return {
        "numerator": r.numerator,
        "denominator": r.denominator,
        "rate": r.rate,
        "lower95": r.lower95,
        "upper95": r.upper95,
    }


def _validity_view_json(view: LabelValidityView) -> dict[str, Any]:
    return {
        "pair_total": view.pair_total,
        "signal_pair_total": view.signal_pair_total,
        "by_label": {row.label: _wilson_json(row.signal) for row in view.rows},
        "novice_precision": _wilson_json(view.novice_precision),
        "novice_recall": _wilson_json(view.novice_recall),
        "other_signal_rate": _wilson_json(view.other_signal_rate),
    }


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
        "selection_theta_rules": {
            "treatment_total": report.recommendation_treatment_total,
            "selection_theta_key": {
                "total": report.selection_theta_key_total,
                "rate": report.selection_theta_key_rate,
            },
            "theta_boundary_upper": {
                "total": report.theta_boundary_upper_total,
                "rate": report.theta_boundary_upper_rate,
            },
            "theta_boundary_lower": {
                "total": report.theta_boundary_lower_total,
                "rate": report.theta_boundary_lower_rate,
            },
            "selection_help_key": {
                "total": report.selection_help_key_total,
                "rate": report.selection_help_key_rate,
            },
            "selection_hint_unknown_key": {
                "total": report.selection_hint_unknown_key_total,
                "rate": report.selection_hint_unknown_key_rate,
            },
        },
        "coach_hint_supply": {
            "help_row_total": report.coach_supply_help_row_total,
            "classified": {
                "total": report.coach_supply_classified_row_total,
                "rate": report.coach_supply_classified_rate,
            },
            "label_only": {
                "total": report.coach_supply_label_only_row_total,
                "rate": report.coach_supply_label_only_rate,
            },
            "label_only_served": {
                "total": report.coach_supply_label_only_served_row_total,
                "rate": report.coach_supply_label_only_served_rate,
            },
            "label_only_pair": {
                "total": report.coach_label_only_pair_total,
                "unsignaled_total": report.coach_label_only_unsignaled_pair_total,
                "unsignaled_rate": report.coach_label_only_unsignaled_rate,
            },
        },
        "coach_label_validity": {
            "min_evidence_n": report.coach_label_min_evidence_n,
            "unlabeled_pair_total": report.coach_label_unlabeled_pair_total,
            "unclassified_pair_total": report.coach_label_unclassified_pair_total,
            "source_unknown_pair_total": report.coach_label_source_unknown_pair_total,
            "all": _validity_view_json(report.coach_label_validity_all),
            "server": _validity_view_json(report.coach_label_validity_server),
        },
    }


def dump_json(report: ReachReport) -> str:
    return json.dumps(report_to_json(report), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


# ──────────────────────────────────────────────────────────────────────────
# CLI (얇은 껍데기 — DB 세션 열고 닫기·입출력만, 집계는 위 순수 코어)
# ──────────────────────────────────────────────────────────────────────────
async def _run(min_label_evidence_n: int | None = None) -> ReachReport:
    """세션을 열어 실측하고 리포트를 조립한다(조회 전용·쓰기 0). 종료 시 엔진 정리."""
    sessionmaker = get_sessionmaker()
    try:
        async with sessionmaker() as session:
            counts = await fetch_reach_counts(session, min_label_evidence_n=min_label_evidence_n)
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
    parser.add_argument(
        "--min-label-evidence-n",
        dest="min_label_evidence_n",
        type=int,
        default=None,
        help=(
            "§8 라벨 예측 타당도를 첫 라벨이 서버 개념 숙달도 관측 K건 이상에서 나온 쌍으로 한정"
            "(선택 — K는 운영 데이터를 보고 고른다·미지정이면 한정 없음)"
        ),
    )
    args = parser.parse_args(argv)
    if args.min_label_evidence_n is not None and args.min_label_evidence_n < 0:
        parser.error("--min-label-evidence-n은 0 이상이어야 한다")

    try:
        report = asyncio.run(_run(args.min_label_evidence_n))
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
