"""L2 시도 버전 고정 — 시도가 접수되는 순간 문항의 판과 채점 환경을 읽어 둔다 (EOS-47).

────────────────────────────────────────────────────────────────────────────
왜 필요한가
────────────────────────────────────────────────────────────────────────────
`problem_attempt`는 `problem_id`로 문항을 가리킨다. 그런데 문항은 고쳐진다(해설 정정·정답 수정·
발문 보정). `problem_id`는 개체마다 불변이라(ARCH-31 §2) 문항이 바뀐 뒤에는 "그 학생이 실제로
푼 문제의 모습"을 가리킬 방법이 없다 — 채점 이의·오답 재검토·정답 정정 영향 분석이 전부 "지금
모습"을 기준으로 틀린 답을 낸다. 판(`problem_version`)은 ARCH-31이 만들었고, 이 모듈은 시도가
**접수된 순간의 포인터를 복사**해 시도 행에 박는다.

────────────────────────────────────────────────────────────────────────────
고정하는 것 / 안 하는 것 (정직 기술)
────────────────────────────────────────────────────────────────────────────
- `problem_version_id` ← `problem.problem_version_id`(현재 서빙 기준 판 포인터). 문항에 판이 없으면
  **None**이다. 현재 운영 writer가 `problem_version`에 행을 쓰는 곳이 없어(ARCH-31 §5) 모든 문항의
  포인터가 NULL이므로, 이 헬퍼가 지금 만드는 `problem_version_id`는 **전부 None**이다. 이것은 결함이
  아니라 정확한 상태다 — 판 없는 문항에 판을 날조해 넣지 않는다. 발행 경로가 포인터를 채우는
  순간부터
  이 헬퍼는 별도 수정 없이 값을 기록한다(`outcome=pinned` 비율이 "작동한 비율"이다 — 아래 로그).
- `evaluation_context` ← `schema/evaluation_context.py`의 `EVALUATION_CONTEXT_SOURCES` 표에서
  **출처가
  있는 키만** 채운다. 현재는 `curriculum_version` 하나뿐이고 나머지 4개 키는 `None`(기록 불가)이다.

**알려진 한계 — 접수 시점 ≠ 출제 시점.** 이 헬퍼는 시도를 *받은* 순간의 포인터를 읽는다.
학생이 문항을
받은 뒤 푸는 동안 그 문항의 새 판이 발행되면, 학생이 실제로 본 판(옛 판)이 아니라 새 판이 박힌다.
정확한 고정은 **출제 시점에 판을 확정**(응답에 판 id를 싣고 제출 때 되돌려받거나
서버 세션에 보관)해야
성립한다 — 그 경로는 이 태스크 범위 밖이고 별도 태스크로 등재했다. 발행 빈도가 낮고 풀이 시간이 짧은
동안은 오차 창이 작지만 0은 아니다.

────────────────────────────────────────────────────────────────────────────
실패 처리 — 삼키지 않는다
────────────────────────────────────────────────────────────────────────────
`record_learning_activity`와 달리 never-break로 감싸지 **않는다**. 읽기가 실패한 트랜잭션은 이후
INSERT도 못 하므로 삼켜 봐야 가용성이 늘지 않고, 오히려 진짜 원인(첫 오류)을 가리고 뒤의 엉뚱한
오류로 500이 난다. 예외는 그대로 올라간다. 문항이 없는 경우(`session.get` → None)는 오류가 아니라
`outcome=problem_missing`이다 — 어차피 시도 INSERT의 FK가 막는다.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.problem import Problem
from whymath_backend.schema.evaluation_context import EvaluationContext

logger = logging.getLogger(__name__)

#: 고정 결과 분류 — "작동한 비율"(알고리즘 부착 ≠ 작동)을 로그·리포트가 셀 수 있도록
#: 닫힌 어휘로 둔다.
PinOutcome = Literal["pinned", "no_version", "problem_missing", "no_problem"]


@dataclass(frozen=True)
class AttemptVersionPin:
    """`ProblemAttempt` 생성자에 그대로 넘기는 두 값 + 어떻게 나온 값인지.

    `problem_version_id`·`evaluation_context`는 ORM 컬럼 타입 그대로다(JSONB는 dict). 두 값은 같은
    시점의 한 번의 읽기에서 나온다 — 따로 읽으면 그 사이 문항이 바뀌어 서로 다른 판을
    가리킬 수 있다.
    """

    outcome: PinOutcome
    problem_version_id: uuid.UUID | None = None
    evaluation_context: dict[str, Any] | None = None


def _curriculum_label(problem: Problem) -> str:
    """`Problem.curriculum_version`(enum 또는 값)을 라벨 문자열로 — 직렬화 위치를 한 곳에 둔다."""
    value: Any = problem.curriculum_version
    return str(getattr(value, "value", value))


async def resolve_attempt_version_pin(
    session: AsyncSession, problem_id: uuid.UUID | None
) -> AttemptVersionPin:
    """문항의 현재 판 포인터와 채점 환경을 읽어 시도에 박을 값으로 돌려준다.

    `problem_id`가 None이면 DB를 읽지 않고 `no_problem`(고정할 문항이 없다). 문항 행이 없으면
    `problem_missing`. 행이 있으면 판 포인터 유무와 무관하게 `evaluation_context`는 채운다 —
    교육과정 라벨은 판이 없어도 문항 자체의 사실이기 때문이다(`pinned`/`no_version`은 판 포인터로만
    갈린다).

    **`session.get`을 쓰는 이유**: PK 조회라 identity map을 먼저 보고, 이어지는 오개념·증거
    조립이 같은
    문항을 읽을 때 같은 인스턴스를 재사용한다. (부수 이점: 단위 테스트의 가짜 세션이 `.get`을 이미
    지원한다.)
    """
    if problem_id is None:
        return AttemptVersionPin(outcome="no_problem")

    problem = await session.get(Problem, problem_id)
    if problem is None:
        logger.info(
            "시도 버전 고정: 문항 행 없음 — 고정 생략 "
            "outcome=problem_missing problem_id=%s (EOS-47)",
            problem_id,
        )
        return AttemptVersionPin(outcome="problem_missing")

    # 출처가 있는 키만 채운다(`EVALUATION_CONTEXT_SOURCES`에서 값이 `None`인 키는 건드리지 않는다).
    # 새 키의 출처를 연결할 때는 표와 이 딕셔너리를 같이 고친다 — 어긋나면
    # `tests/backend/l2/test_attempt_version_pin.py`가 빨개진다(런타임 assert는 -O에서
    # 사라져 쓰지 않는다).
    sourced: dict[str, str | None] = {"curriculum_version": _curriculum_label(problem)}
    context = EvaluationContext.model_validate(sourced).model_dump(mode="json")

    version_id: uuid.UUID | None = problem.problem_version_id
    outcome: PinOutcome = "pinned" if version_id is not None else "no_version"
    logger.info(
        "시도 버전 고정: outcome=%s problem_id=%s problem_version_id=%s (EOS-47)",
        outcome,
        problem_id,
        version_id,
    )
    return AttemptVersionPin(
        outcome=outcome, problem_version_id=version_id, evaluation_context=context
    )


__all__ = ["AttemptVersionPin", "PinOutcome", "resolve_attempt_version_pin"]
