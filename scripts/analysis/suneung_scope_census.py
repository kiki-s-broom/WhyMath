#!/usr/bin/env python3
"""수능 출제 범위 집계 — 승인 문항이 수능 게이트·SQL 사전필터에서 어떻게 갈리는지 DB에서 센다
(EOS-31).

EOS-31 acceptance ①의 "집계 명령"이다. 수정 전(옛 게이트)과 수정 후(범위 게이트)를 **같은 DB·같은
문항**에서
나란히 세어, 판정문이 인용하는 숫자를 누구나 재현할 수 있게 한다. 읽기 전용이다(DB를 바꾸지 않는다).

세는 것:
  1. 승인 문항 수와 수능 적격(페르소나 A) 수 — 옛 게이트(범위 단계 제외) vs 현행 게이트.
  2. 승인 문항의 범위 판정 3값(`in_scope`·`out_of_scope`·`unknown`) 분포.
  3. 범위 밖으로 갈린 사유(초·중 전용 · 공통/기본수학 · 기하·진로선택).
  4. **SQL 사전필터가 고른 집합 = 파이썬 게이트가 고른 집합**인가(전체 문항 전수 — 같은 정의의
  증거).

사용: `WHYMATH_DATABASE_URL=postgresql+asyncpg://… python3 scripts/analysis/suneung_scope_census.py`
종료 코드: 0 = 집계 완료·SQL↔파이썬 일치 · 1 = **불일치**(같은 정의가 깨졌다) · 2 = 승인 문항
0건(판정 불가 —
"0건 통과"가 아니다).
"""

from __future__ import annotations

import asyncio
import collections
import os
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from whymath_backend.api._next_problem_policy import suneung_scope_clause
from whymath_backend.api.gating import _fetch_achievement_codes
from whymath_backend.db.models.problem import Problem
from whymath_backend.l6.suneung import (
    SUNEUNG_SCOPE,
    ScopeVerdict,
    is_suneung_eligible,
    suneung_scope_verdict,
)
from whymath_backend.schema.enums import Persona
from whymath_backend.schema.problem import Problem as ProblemSchema

_ELEMENTARY_MIDDLE = ("4수", "6수", "9수")
_COMMON_BASIC = ("10공수", "10기수")
_KNOWN_PREFIXES = (
    "12대수",
    "12미적",
    "12확통",
    "12기하",
    "12직수",
    "12수문",
    "12인수",
    "10공수",
    "10기수",
    "9수",
    "6수",
    "4수",
)


def _level(code: str) -> str:
    body = code.strip("[]")
    return next((p for p in _KNOWN_PREFIXES if body.startswith(p)), "?")


def _is_approved(problem: ProblemSchema) -> bool:
    status = problem.review_status
    return str(getattr(status, "value", status)) == "approved"


def _reason_out(problem: ProblemSchema) -> str:
    levels = {_level(code) for code in problem.achievement_standard_codes}
    if levels <= set(_ELEMENTARY_MIDDLE):
        return "초·중 전용"
    if levels & set(_COMMON_BASIC):
        return "공통·기본수학 포함(범위 안 코드 없음)"
    return "진로·융합 선택(기하·미적분Ⅱ 등) 포함(범위 안 코드 없음)"


async def _run(url: str) -> int:
    engine = create_async_engine(url)
    try:
        async with async_sessionmaker(engine)() as session:
            problems = [r.to_schema() for r in (await session.execute(select(Problem))).scalars()]
            codes = await _fetch_achievement_codes(session, [p.problem_id for p in problems])
            sql_rows = await session.execute(
                select(Problem.problem_id).where(suneung_scope_clause())
            )
            by_sql = {row[0] for row in sql_rows.all()}
    finally:
        await engine.dispose()

    for problem in problems:
        problem.achievement_standard_codes = sorted(codes.get(problem.problem_id, ()))
    by_python = {
        p.problem_id for p in problems if suneung_scope_verdict(p) is ScopeVerdict.IN_SCOPE
    }
    approved = [p for p in problems if _is_approved(p)]
    if not approved:
        print("승인 문항 0건 — 판정 불가(적재 여부와 WHYMATH_DATABASE_URL을 확인하라)")
        return 2

    persona = Persona.A_일반고고3
    eligible_now = [p for p in approved if is_suneung_eligible(p, persona)]
    # 옛 게이트 = 범위 단계 없이 신호만 본다 — 범위 안 코드와 목표 개정을 단 사본으로 같은 신호
    # 판정을
    # 다시 돌려 구한다(범위 단계가 항상 통과하므로 ③ 신호·페르소나·저작권·검수 판정만 남는다).
    in_scope_stub = {
        "achievement_standard_codes": ["[12대수00-00]"],
        "curriculum_version": SUNEUNG_SCOPE.curriculum,
    }
    eligible_before = [
        p for p in approved if is_suneung_eligible(p.model_copy(update=in_scope_stub), persona)
    ]
    verdicts = collections.Counter(suneung_scope_verdict(p).value for p in approved)
    out_reasons = collections.Counter(
        _reason_out(p) for p in approved if suneung_scope_verdict(p) is ScopeVerdict.OUT_OF_SCOPE
    )

    print(f"전체 문항 {len(problems)}건 · 승인 {len(approved)}건")
    print(
        f"수능 적격(페르소나 A) — 옛 게이트(범위 단계 없음) {len(eligible_before)}건 "
        f"→ 현행 {len(eligible_now)}건"
    )
    print(f"승인 문항 범위 판정: {dict(verdicts)}")
    print(f"범위 밖 사유: {dict(out_reasons)}")
    print(
        f"SQL 사전필터 범위 안 {len(by_sql)}건 · 파이썬 게이트 범위 안 {len(by_python)}건 "
        f"· 같은 집합: {by_sql == by_python}"
    )
    return 0 if by_sql == by_python else 1


def main() -> int:
    url = os.environ.get("WHYMATH_DATABASE_URL")
    if not url:
        print("WHYMATH_DATABASE_URL(asyncpg URL)이 필요하다")
        return 2
    return asyncio.run(_run(url))


if __name__ == "__main__":
    sys.exit(main())
