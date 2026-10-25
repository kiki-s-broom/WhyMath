"""L1 문제은행 — 오개념 mids → 진단 프로브 후보 *역인덱스 조회* (REC-02 ①).

설계 정본: `docs/architecture/ai_recommendation_module_gap_review.md` §3 D2. WH-1 하네스 도구6
(`select_probe`)가 소비할 진단 문항 후보를 `Problem.distractor_map`(오답 선지→오개념 매핑)에서
찾는 **조회 좌석**이다 — *선택 로직은 담지 않는다*. 겨냥할 오개념을 결정하고(§2.2 ε-탐색/활용)
후보 중 정보량 최대 1개를 고르는 일은 전부 `l4.misconception.probe_selection`(순수·DB 무관) 몫이며,
이 모듈은 그 함수가 씹을 `ProbeCandidate` 재료(문항 id·난이도·오개념 태그)를 DB에서 길어 올릴
뿐이다(7계층: L1 조회 → 하네스 주입 → L4 순수 선택, CLAUDE.md 역방향 의존 금지).

**L1은 L4를 모른다**: 여기서 반환하는 `ProbeCandidateRow`는 L4 `probe_selection.ProbeCandidate`와
필드가 동형이지만 *별개의 L1 소유 모델*이다 — L1이 L4를 import하면 역방향 의존(L4→L1은 허용,
L1→L4는 금지)이 되므로, 그 조립(L1 결과 → L4 `ProbeCandidate`)은 하네스
(`harness/wh1_probe_supply.py` — L1·L2·L4를 자유로이 넘나드는 횡단 인프라, import-linter 계약
밖)가 담당한다. 같은 이유로
난이도 로짓(b) 변환(`l2.ability_estimation.resolve_item_difficulty_b`, L2)도 여기서 하지 않는다 —
`difficulty_overall`·`irt_difficulty_b` *원값*만 반환하고 변환은 하네스가 L2를 불러 수행한다.

필터 2종("미응답 제외·난이도 보유만" — 감사 §3 D2 ①):
  - **난이도 보유**: `difficulty_overall IS NOT NULL`인 문항만(감사 실측 당시 코퍼스
    2,647/2,647=100% 보유). 난이도 없이는 IRT 정보량을 계산할 수 없어 후보 자격이 없다.
  - **미응답**: `user_id`가 주어지면 이 학생이 이미 *채점 완료*(`is_correct IS NOT NULL`) 응답한
    문항을 뺀다(`api/me.py` `/next-problem`의 "미응답 문항" 정의를 그대로 재사용 — 진단 문항도
    이미 답을 아는 문항을 다시 내밀면 판별력이 없다).

설계 분리(코드베이스 패턴 — `l1/misconception/resolve.py` 답습):
  - **순수 코어**(`_match_probe_rows`) — mids 매칭·필터·정렬은 DB 무관·I/O 0. 단위테스트가
    실 DB 없이 이 함수만으로 전 시나리오(태깅 없음/난이도 없음/전부 응답함)를 검증한다.
  - **얇은 DB 시암**(`fetch_probe_candidates_by_mids`·`_fetch_attempted_problem_ids`) — 조회만
    (읽기 전용·신규 테이블·마이그레이션 0). `distractor_map IS NOT NULL`인 문항 전량을 가져와
    (코퍼스 1,616건 규모 — 전량 fetch가 안전) 파이썬에서 mids 교집합을 본다. PostgreSQL JSONB
    배열 원소 매칭을 SQL로 표현하는 대신(가독성·이식성) `_fetch_candidates`(`api/gating.py`)
    선례처럼 "SQL 상한 fetch + 파이썬 정밀 필터"를 택했다 — 이 규모(수천 행)에선 성능 차이가
    무의미하고, JSONB 배열 매칭 SQL은 검증이 어렵다.

정직 회계(④ 원재료 — 최종 사유 판정은 `harness/wh1_probe_supply.py` 몫): `ProbeCandidateQuery`는
`tagged_count`(mids 태깅된 문항 수·난이도 무관)·`tagged_with_difficulty_count`(그 중 난이도 보유)
두 단계를 함께 반환해, "오개념 미태깅"과 "난이도 부재"를 구분할 수 있게 한다(이 모듈 자체는 사유
문자열을 만들지 않는다 — 그건 "가설 없음"까지 아는 상위 계층의 일).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.activity import ProblemAttempt
from whymath_backend.db.models.problem import Problem

__all__ = [
    "ProbeCandidateQuery",
    "ProbeCandidateRow",
    "fetch_probe_candidates_by_mids",
]

logger = logging.getLogger("whymath.l1.problem_bank.probe_candidates")

# distractor_map IS NOT NULL 문항 전량 상한 — 코퍼스 실측 1,616건(감사 §3 D2)에 여유를 둔 상한.
# `_fetch_candidates`(api/gating.py) PB-03 축③ 절단 관측 패턴을 답습(초과 시 WARNING).
_DEFAULT_FETCH_LIMIT = 5000
# 반환 후보 상한(정보이득 비교는 하네스가 하므로 넉넉히 — Minimal Reasoning Subgraph 예산은
# LLM 프롬프트 축이라 여기 적용 대상이 아니다. 결정론 tiebreak은 problem_id 오름차순).
_DEFAULT_LIMIT = 200


class ProbeCandidateRow(BaseModel):
    """L1이 반환하는 진단 프로브 후보 1건 — L4 `ProbeCandidate`와 필드 동형이나 별개 L1 모델.

    `difficulty_overall`·`irt_difficulty_b`는 *원값*이다(logit 변환은 하네스가 L2로 수행).
    `discrimination`은 `irt_a`(양수)가 있으면 그대로, 없거나 비양수면 `1.0`(Rasch 기본 — L4
    `ProbeCandidate.discrimination` 기본값과 동일 규약)으로 여기서 이미 정규화해 둔다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    problem_id: str = Field(description="문항 식별자(UUID 문자열화 — L4 ProbeCandidate와 동형).")
    difficulty_overall: float = Field(
        description="전문가 난이도(1~5). 이 필터를 통과했으니 not-None."
    )
    irt_difficulty_b: float | None = Field(
        default=None,
        description="JMLE 보정 난이도 b(logit). 미보정이면 None(하네스가 휴리스틱 폴백).",
    )
    discrimination: float = Field(
        default=1.0, gt=0.0, description="IRT a(변별도) — irt_a 없거나 비양수면 1.0."
    )
    misconception_tags: frozenset[str] = Field(
        default_factory=frozenset,
        description="이 문항 distractor_map의 misconception_id 전체 집합(질의 mids로 국한 X).",
    )


class ProbeCandidateQuery(BaseModel):
    """조회 결과 + 단계별 정직 회계(④ 원재료). 최종 사유 판정은 상위 계층(하네스) 몫."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rows: tuple[ProbeCandidateRow, ...] = Field(
        default_factory=tuple, description="미응답·난이도 보유 필터를 모두 통과한 최종 후보."
    )
    tagged_count: int = Field(
        default=0, description="mids 중 하나 이상 태깅된 문항 수(난이도·응답 필터 전)."
    )
    tagged_with_difficulty_count: int = Field(
        default=0, description="위 중 difficulty_overall 보유(미응답 필터 전)."
    )


def _match_probe_rows(
    rows: Sequence[Sequence[Any]],
    mids: frozenset[str],
    *,
    exclude_problem_ids: frozenset[str] = frozenset(),
    limit: int = _DEFAULT_LIMIT,
) -> ProbeCandidateQuery:
    """`(problem_id, distractor_map, difficulty_overall, irt_a, irt_difficulty_b)` 5-원소 시퀀스
    (SQLAlchemy `Row`·순수 튜플 둘 다 허용)를 mids 태깅 매칭 → 난이도 보유 → 미응답 순으로 필터해
    `ProbeCandidateQuery`로 조립(순수·DB 무관).

    `distractor_map`이 비었거나(None·빈 리스트) `misconception_id`가 mids와 전혀 겹치지 않는 행은
    스킵한다. 매칭된 행은 `tagged_count`에 계상되고, 그 중 `difficulty_overall`이 있는 행만
    `tagged_with_difficulty_count`·최종 후보 자격을 얻는다. 마지막으로 `exclude_problem_ids`
    (미응답 필터 — 이미 응답한 문항 id)를 뺀 뒤 `problem_id` 오름차순 결정론 정렬 후 `limit` 절단.

    입력을 변형하지 않는다(새 객체만 반환). `misconception_id`가 없거나 빈 문자열인 distractor
    엔트리는 태그에서 조용히 제외한다(참조 무결성은 L4 검증자 소관 — `db/models/problem.py`
    docstring과 정합, 여기선 형태만 본다).
    """
    tagged_count = 0
    tagged_with_difficulty: list[ProbeCandidateRow] = []
    for row in rows:
        problem_id, distractor_map, difficulty_overall, irt_a, irt_difficulty_b = row
        if not distractor_map:
            continue
        tags = frozenset(
            str(entry["misconception_id"])
            for entry in distractor_map
            if isinstance(entry, dict) and entry.get("misconception_id")
        )
        if tags.isdisjoint(mids):
            continue
        tagged_count += 1
        if difficulty_overall is None:
            continue
        discrimination = 1.0
        if irt_a is not None and float(irt_a) > 0:
            discrimination = float(irt_a)
        tagged_with_difficulty.append(
            ProbeCandidateRow(
                problem_id=str(problem_id),
                difficulty_overall=float(difficulty_overall),
                irt_difficulty_b=(None if irt_difficulty_b is None else float(irt_difficulty_b)),
                discrimination=discrimination,
                misconception_tags=tags,
            )
        )

    final = sorted(
        (row for row in tagged_with_difficulty if row.problem_id not in exclude_problem_ids),
        key=lambda r: r.problem_id,
    )[:limit]
    return ProbeCandidateQuery(
        rows=tuple(final),
        tagged_count=tagged_count,
        tagged_with_difficulty_count=len(tagged_with_difficulty),
    )


async def _fetch_attempted_problem_ids(
    session: AsyncSession, user_id: uuid.UUID
) -> list[uuid.UUID]:
    """이 학생이 이미 *채점 완료* 응답한 문항 id — "미응답" 필터 원천.

    `api/me.py` `/next-problem`(`_load_attempt_history_state`)과 동일 정의(`is_correct IS NOT
    NULL`)를 재사용한다 — 진단 문항도 이미 채점된 문항을 다시 내밀면 판별력이 없다는 점은
    적응 출제와 같은 논리다(단일 진실원천 — 두 곳에서 "미응답"을 다르게 정의하지 않는다).
    """
    stmt = select(ProblemAttempt.problem_id).where(
        ProblemAttempt.user_id == user_id,
        ProblemAttempt.is_correct.isnot(None),
        ProblemAttempt.problem_id.isnot(None),
    )
    result = await session.execute(stmt)
    return [pid for pid in result.scalars().all() if pid is not None]


async def fetch_probe_candidates_by_mids(
    session: AsyncSession,
    mids: Sequence[str],
    *,
    user_id: uuid.UUID | None = None,
    exclude_problem_ids: Sequence[str] = (),
    limit: int = _DEFAULT_LIMIT,
    fetch_limit: int = _DEFAULT_FETCH_LIMIT,
) -> ProbeCandidateQuery:
    """mids(오개념 id들) → 진단 프로브 후보 문항 역인덱스 조회 — L1 조회 좌석(감사 §3 D2 ①).

    `mids`가 비면 조회 없이 빈 결과(쿼리 낭비 방지 — 호출자가 "가설 없음"을 이미 아는 상태).
    아니면 `distractor_map IS NOT NULL`인 문항을 `fetch_limit`까지 끌어와(코퍼스 1,616건 규모라
    전량 fetch가 안전) `_match_probe_rows`(순수)로 mids 매칭·난이도 필터·미응답 필터를 적용한다.

    Args:
      session: 읽기 전용 async 세션.
      mids: 겨냥 오개념 id 목록(활성 가설 mids ∪ outside_mids — 어느 것을 넣을지는 호출자 몫).
      user_id: 주어지면 이 학생이 이미 채점 완료 응답한 문항을 제외("미응답" 필터). None이면
        미적용(호출자가 익명/미인증 컨텍스트거나 이미 다른 축으로 필터한 경우).
      exclude_problem_ids: 추가로 제외할 문항 id(문자열화 비교 — 예: 이번 세션에 이미 출제한
        진단 문항). `user_id` 배제분과 합집합.
      limit: 최종 반환 후보 상한(결정론 problem_id 오름차순 절단).
      fetch_limit: distractor_map 보유 문항 fetch 상한 — 도달 시 절단 의심 WARNING(침묵 실패 금지·
        `_fetch_candidates` PB-03 축③ 선례).

    Returns:
      `ProbeCandidateQuery`(최종 후보 + 단계별 정직 회계).
    """
    if not mids:
        return ProbeCandidateQuery()
    mids_set = frozenset(mids)

    stmt = (
        select(
            Problem.problem_id,
            Problem.distractor_map,
            Problem.difficulty_overall,
            Problem.irt_a,
            Problem.irt_difficulty_b,
        )
        .where(Problem.distractor_map.isnot(None))
        .order_by(Problem.problem_id)
        .limit(fetch_limit)
    )
    result = await session.execute(stmt)
    rows = result.all()
    if len(rows) == fetch_limit:
        # 절단 의심 — 조용히 넘기지 않는다(침묵 실패 금지). 카운트만(문항 본문·id 미포함).
        logger.warning(
            "probe_candidates fetch 상한(%d) 도달 — distractor_map 보유 문항이 더 있을 수 있음",
            fetch_limit,
        )

    exclude: set[str] = {str(pid) for pid in exclude_problem_ids}
    if user_id is not None:
        attempted = await _fetch_attempted_problem_ids(session, user_id)
        exclude.update(str(pid) for pid in attempted)

    return _match_probe_rows(rows, mids_set, exclude_problem_ids=frozenset(exclude), limit=limit)
