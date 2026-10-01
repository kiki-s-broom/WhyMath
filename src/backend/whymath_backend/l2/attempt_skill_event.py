"""채점 확정 시 해소된 스킬 배열을 `attempt_event`에 영속하는 writer (EOS-57).

**존재 이유(소급 불가 축)**: `l2.skill_mastery_tracking.record_problem_attempt_skill_mastery`는
채점 순간 concept→skill 브리지로 스킬을 *해소*해 `skill_mastery_history`를 적재하지만, **어떤
스킬이 이 시도에 귀속됐는가**는 런타임에서만 존재하고 버려져 왔다(EOS-53 crosswalk 갭 #4 실측:
영속 좌석 0). 숙달 시계열은 "스킬 s의 값이 언제 어떻게 변했는가"를 남길 뿐, "시도 a가 스킬
{s1,s2}를 건드렸다"는 결합은 남기지 않는다 — 그 결합은 문항↔개념↔스킬 매핑이 이후에 바뀌면
**영원히 재구성 불가**다(W2 "되돌릴 수 없는 스키마" ①). 12월 데이터에 남길 축이라 지금 적재한다.

**계층 위치**: L2(학습자 모델)의 영속 좌석이다 — 해소 규칙(모델 B·역할 비대칭)은
`skill_mastery_tracking`이 소유하고, 이 모듈은 *그 결과를 기록*만 한다. 채점 경로(L5 API 핸들러)
2곳이 같은 writer를 경유하도록 여기에 단일 seam을 둔다(중복 구현 금지 — `_complete_problem`이
`submit_attempt`의 L2 헬퍼를 재사용하는 기존 관례와 동형).

**범위 경계(EOS-57 acceptance ③ 집행 별항)**: 이 모듈은 **영속 좌석 + writer까지**다. 소비 지점
전환(`skill_mastery_tracking`이 런타임 해소 대신 이 이벤트 기록을 읽는 것)은 후속 태스크
**EOS-63**(`attempt-skill-event-consumption`)이 소유한다 — 지금 소비를 바꾸면 기록이 0건인 상태에서
숙달 전파가 죽는다(기록이 먼저 쌓여야 하며, 전환 선결 조건은 기록률 리포트의 실측 수치다).

**None ≠ [] 규약**: `skill_ids`는 nullable이고 server_default가 없다.
  - NULL = writer 미도달(구판 이벤트·다른 event_type·이 배선 이전의 시도)
  - `[]`  = 해소를 *실행했고* 매핑이 0건이었다(concept→skill 브리지 미보유 문항)
둘을 구분해야 기록률 리포트가 "안 돌았다"와 "돌았는데 0건"을 다른 글자로 말할 수 있다
(`harness/attempt_skill_event_reach_report.py` — CLAUDE.md "작동한 비율" 원칙).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.activity import AttemptEvent
from whymath_backend.schema.enums import EventType
from whymath_backend.schema.event_data_contract import build_event_data

__all__ = ["AttemptSource", "record_attempt_skill_event"]

_logger = logging.getLogger("whymath.l2.attempt_skill_event")


class AttemptSource(str, Enum):
    """채점 경로 라벨(폐쇄 3종) — `문제시도` 이벤트 `event_data.source`.

    한 경로에만 writer가 배선되는 회귀를 기록률 리포트가 *경로별 분모*로 잡아내기 위한 축이다
    (전체 평균 하나면 한쪽 경로 전멸이 절반의 감소로 희석돼 보인다).
    """

    attempt_submit = "attempt_submit"
    """`POST /v1/me/attempts` — 클라 자가보고 `is_correct`를 신뢰하는 v1 경로(api/me.py)."""

    coach_completion = "coach_completion"
    """코치 대화 완료 확정 — 서버가 `verify_final_answer`로 판정한 경로(api/coach.py)."""

    coach_wrong_submission = "coach_wrong_submission"
    """코치 대화의 서버 판정 오답 최초 제출(EOS-146) — 완료가 아니다(api/coach.py).

    `coach_completion`과 갈라 둔 이유: 그 라벨은 "완료 확정 경로"의 분모라 오답 제출이 섞이면
    경로별 기록률이 의미를 잃는다. 이 라벨의 `is_correct`는 항상 False다.
    """


async def record_attempt_skill_event(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    attempt_id: uuid.UUID,
    problem_id: uuid.UUID,
    is_correct: bool,
    skill_ids: Iterable[str],
    source: AttemptSource,
    event_at: datetime | None = None,
) -> AttemptEvent | None:
    """해소된 스킬 배열을 `문제시도` 이벤트 1건으로 적재하고 **commit까지 수행**한다.

    `skill_ids`는 *해소 결과 그대로*를 순서 보존·중복 제거해 싣는다(빈 반복자면 `[]` — None으로
    승격하지 않는다: "해소했는데 0건"은 실측이고 NULL은 미기록이라 의미가 다르다).

    **실패 시 예외를 전파하지 않고 None을 반환한다** — 초안은 전파(500)였으나 PR #913 리뷰
    지적으로 재판정했다. 결정적 근거는 "전파해도 기록이 남지 않는다"는 것이다:

      - 전파(500) 시 — attempt·숙달은 *이미 commit*됐고 이벤트만 실패한다. 클라가 재시도하면
        `submit_attempt`에 멱등키가 없으므로 **새 attempt**(새 UUID)가 생기고 숙달이 한 번 더
        적용된다. 원래 attempt의 이벤트는 그래도 영원히 없다.
      - 흡수(201) 시 — 이벤트만 없다. 중복 attempt도, 이중 계상된 숙달도 없다.

    즉 두 경우 모두 그 이벤트를 잃는다. 전파는 데이터를 구하지 못하면서 **학습자 모델까지
    오염**시킨다(BKT sample_size 이중 계상 = 학생 숙달 추정 왜곡). CLAUDE.md 의사결정
    우선순위상 학생 상태의 정합이 분석 축 한 칸보다 앞선다.

    **침묵 실패가 아니다**(CLAUDE.md 금기 준수) — 두 가지가 실패를 말한다:
      ① 로그에 **예외 타입명**을 남긴다(무타입 경고 금지 — langfuse v2 무증상 전멸 교훈).
      ② `harness/attempt_skill_event_reach_report`의 **"writer 미도달"** 칸이 그 attempt를
         센다 — 유실이 *비율로* 보인다. 이 리포트가 존재하는 이유가 정확히 이것이다.
    삼켜도 되는 이유가 "덜 중요해서"가 아니라 **유실이 계측되기 때문**이라는 점이 핵심이다.

    남은 한계(정직한 공백): 진짜 원자성(attempt·숙달·이벤트 단일 트랜잭션)은 공유 L2 헬퍼 2개
    (`record_problem_attempt_mastery`·`record_problem_attempt_skill_mastery`)의 commit 소유권을
    호출부로 옮겨야 해서 이 PR 범위를 넘는다 — 재시도 멱등성(멱등키)까지 함께 봐야 하는 별도
    설계 사안이다.

    배포 순서 안전성(실측·가정 아님): `문제시도` enum 값이 DB에 없으면 이 INSERT가 실패한다.
    `deploy.yml`은 `alembic upgrade head`를 컨테이너 기동(`up -d`)보다 **먼저** 실행한다
    (deploy.yml:184-190). 흡수 설계로 바뀐 지금은 그 순서가 어긋나도 채점이 죽지 않고 기록률만
    떨어진다(리포트가 즉시 드러낸다).

    `event_at`은 서버 기록(수신) 시각이다 — 이 테이블의 기존 writer 전부와 같은 의미로 서버
    `now(UTC)`를 넣는다(EOS-48 실측 명문화). 클라 신고 발생 시각(`event_time`)은 채점 경로에
    신고 축이 없어 채우지 않는다(NULL=미신고 — 수신 시각 복제는 날조).
    """
    # 순서 보존 중복 제거 — 같은 스킬이 여러 개념에서 해소돼도 배열엔 1회만(집계 분모 왜곡 0).
    deduped: list[str] = list(dict.fromkeys(skill_ids))
    event = AttemptEvent(
        event_at=event_at or datetime.now(UTC),
        attempt_id=attempt_id,
        user_id=user_id,
        problem_id=problem_id,
        event_type=EventType.문제시도,
        event_data=build_event_data(
            EventType.문제시도,
            is_correct=is_correct,
            source=source.value,
        ),
        skill_ids=deduped,  # [] 유지(None 승격 금지 — 미기록과 해소 0건은 다른 사실).
    )
    session.add(event)
    try:
        await session.commit()
    except Exception as exc:  # noqa: BLE001 — 타입명을 남기고 흡수(위 docstring의 재판정 근거)
        # 세션을 되살린다 — commit 실패 후 rollback 없이는 이후 사용이 전부 실패한다.
        await session.rollback()
        _logger.error(
            "문제시도 이벤트 적재 실패 — attempt_id=%s source=%s skill_ids=%d건 (%s): %s. "
            "채점·숙달은 이미 durable하므로 요청은 성공으로 끝내고, 이 유실은 "
            "attempt_skill_event_reach_report의 'writer 미도달' 비율로 계측된다.",
            attempt_id,
            source.value,
            len(deduped),
            type(exc).__name__,
            exc,
        )
        return None
    return event
