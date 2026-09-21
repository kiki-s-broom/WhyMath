"""L2 — `LearnerState` 영속 축의 **단일 읽기·쓰기 경로** (EOS-103).

`l2/learner_state.py`(조립기)와의 관계 — 둘은 같은 이름의 서로 다른 축이다:

| 축 | 모듈 | 정본 | 카디널리티 |
|---|---|---|---|
| 조립(파생) | `learner_state.py::get_state` | BKT·IRT·오개념 가설 테이블 | 호출 시 계산 |
| 영속(생산자 부재 축 + 생성 시점) | **이 모듈** | `learner_state` 테이블 | 학생당 1행 |

이 모듈은 조립기를 **호출하지도 대체하지도 않는다**. 숙련·오개념 맵을 여기에 복제하면 같은
사실의 두 번째 진실 원천이 생긴다(붕괴 연쇄 "유지보수 지옥 ← truth source가 하나가 아님").

**단일 쓰기 경로**(이 모듈이 존재하는 첫 번째 이유): `LearnerStateRecord`를 생성·변경하는
코드는 이 파일의 `provision_learner_state`·`apply_learner_state_mutation` 둘뿐이다.
`tests/backend/db/test_learner_state_single_writer.py`가 백엔드 전 소스를 AST로 훑어 이
사실을 동결한다 — 산문 규약이 아니라 기계 검사다. 여러 모듈이 제각각 상태를 고치면 계획서
KPI 2(State Integrity)를 영원히 측정할 수 없다.

**부재 시 명시적 실패**(두 번째 이유): `require_learner_state`는 행이 없을 때 기본값 객체를
돌려주지 않고 `LearnerStateMissingError`를 던진다. `load_learner_state`는 `| None`을 돌려주어
호출부가 부재를 **타입으로 처리하도록 강제**한다(`mypy --strict`가 미처리를 잡는다). 조용히
기본값으로 진행하는 세 번째 선택지는 이 모듈에 없다.

**확장 가능성을 타입으로**(§2 "알고리즘보다 계약"): 변경은 스칼라 인자 나열이 아니라
`LearnerStateMutation` 한 객체로 받는다. BKT/DKT/Knowledge Tracing이 나중에 새 축을 채울 때
호출부 시그니처는 그대로 두고 **필드만 추가**하면 된다(미지정 필드는 `UNSET` — None과 구별되며
"건드리지 않음"을 뜻한다. 이 구별이 없으면 부분 갱신이 다른 필드를 None으로 지우게 된다).
지금 그 추정기를 구현하지 않는다(§15 동결).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.learner_state import (
    PROVISIONED_BY_BACKFILL,
    PROVISIONED_BY_DIAGNOSIS_CAPTURE,
    LearnerStateRecord,
)

__all__ = [
    "UNSET",
    "Unset",
    "LearnerStateMissingError",
    "LearnerStateMutation",
    "PersistedLearnerState",
    "ProvisionReason",
    "load_learner_state",
    "require_learner_state",
    "provision_learner_state",
    "apply_learner_state_mutation",
]


class Unset:
    """ "이 필드는 건드리지 않는다"를 뜻하는 센티널 타입 — `None`("값을 비운다")과 다르다.

    3상태(값 / 비움 / 미지정)를 2상태로 접으면 부분 갱신이 다른 필드를 조용히 지운다
    (CLAUDE.md "모른다 ≠ 아니다").
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - 디버깅 표기
        return "UNSET"


UNSET: Final[Unset] = Unset()

ProvisionReason = Literal["diagnosis_capture", "backfill"]
"""행 생성 계기 — `db/models/learner_state.py`의 `PROVISIONED_BY_*` 상수와 같은 값.

Literal로 좁혀 두면 오타가 `mypy --strict`에서 잡힌다(문자열 자유 입력이면 관측 축이 조용히
오염된다). 값 자체의 정본은 ORM 모듈이며 아래 `_REASON_VALUES`가 두 곳의 동기화를 동결한다.
"""

_REASON_VALUES: Final[dict[str, str]] = {
    "diagnosis_capture": PROVISIONED_BY_DIAGNOSIS_CAPTURE,
    "backfill": PROVISIONED_BY_BACKFILL,
}


class LearnerStateMissingError(RuntimeError):
    """학습 루프가 요구하는 `LearnerState`가 없다 — 기본값으로 진행하지 않고 여기서 멈춘다.

    이 예외가 던져졌다는 것은 "진단을 완료하지 않은 학생이 학습 루프에 진입하려 했다"는
    뜻이다. 서버 결함이 아니라 **데이터 상태**이므로 호출부는 5xx가 아니라 4xx로 옮긴다.
    """

    def __init__(self, learner_id: uuid.UUID) -> None:
        self.learner_id = learner_id
        super().__init__(
            f"LearnerState 없음(learner_id={learner_id}) — 진단 완료가 상태를 생성한다. "
            "기본값으로 진행하지 않는다."
        )


class PersistedLearnerState(BaseModel):
    """`learner_state` 한 행의 읽기 계약 — ORM을 호출부에 새지 않게 하는 경계.

    조립 축(숙련·오개념)은 여기 없다 — 그쪽 정본은 `l2/learner_state.py::get_state`다.
    합성 표면(영속 + 조립을 한 응답으로 묶는 것)은 `EOS-10`이 소유한다.
    """

    model_config = ConfigDict(frozen=True)

    learner_id: uuid.UUID = Field(description="학생 user_id — 이 행의 PK.")
    curriculum_id: str | None = Field(description="교육과정 식별자. 미배정이면 None.")
    current_objective_id: str | None = Field(description="현재 학습목표 id. 미배정이면 None.")
    provisioned_at: datetime = Field(description="최초 생성 시각 — 갱신되지 않는다.")
    provisioned_by: str = Field(description="생성 계기(관측용 — 분기 금지).")
    updated_at: datetime = Field(description="마지막 변경 시각.")
    revision: int = Field(description="변경 횟수 — 단일 쓰기 경로의 이중 회계 축.")

    @classmethod
    def from_record(cls, record: LearnerStateRecord) -> PersistedLearnerState:
        return cls(
            learner_id=record.learner_id,
            curriculum_id=record.curriculum_id,
            current_objective_id=record.current_objective_id,
            provisioned_at=record.provisioned_at,
            provisioned_by=record.provisioned_by,
            updated_at=record.updated_at,
            revision=record.revision,
        )


class LearnerStateMutation(BaseModel):
    """상태 변경 요청 — **확장 좌석**. 새 축이 생산자를 얻으면 여기에 필드만 추가한다.

    각 필드의 기본값은 `UNSET`이다(None이 아니다) — "지정하지 않음"과 "None으로 비움"을
    구별하기 위해서다. `apply_learner_state_mutation`은 `UNSET`인 필드를 건드리지 않는다.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    curriculum_id: str | None | Unset = Field(default=UNSET)
    current_objective_id: str | None | Unset = Field(default=UNSET)

    def assignments(self) -> dict[str, str | None]:
        """`UNSET`이 아닌 필드만 {컬럼명: 값}으로 — 여기 없는 컬럼은 변경되지 않는다."""
        return {
            name: value for name, value in self.__dict__.items() if not isinstance(value, Unset)
        }


# ──────────────────────────────────────────────────────────────────────────
# 읽기 — 두 갈래뿐이다(부재 허용 / 부재 불가). 기본값 채우기는 없다.
# ──────────────────────────────────────────────────────────────────────────
async def load_learner_state(
    session: AsyncSession, learner_id: uuid.UUID
) -> PersistedLearnerState | None:
    """행이 있으면 돌려주고 없으면 None — 호출부가 부재를 **타입으로** 처리하게 한다."""
    record = await session.get(LearnerStateRecord, learner_id)
    return None if record is None else PersistedLearnerState.from_record(record)


async def require_learner_state(
    session: AsyncSession, learner_id: uuid.UUID
) -> PersistedLearnerState:
    """행이 없으면 `LearnerStateMissingError` — 기본값으로 진행하는 경로는 없다."""
    state = await load_learner_state(session, learner_id)
    if state is None:
        raise LearnerStateMissingError(learner_id)
    return state


# ──────────────────────────────────────────────────────────────────────────
# 쓰기 — 이 두 함수가 `LearnerStateRecord`를 만지는 **유일한** 코드다(AST 가드 동결).
# ──────────────────────────────────────────────────────────────────────────
async def provision_learner_state(
    session: AsyncSession,
    learner_id: uuid.UUID,
    *,
    reason: ProvisionReason,
    curriculum_id: str | None = None,
) -> PersistedLearnerState:
    """학습자 상태 행을 **자동 생성**한다 — 멱등(이미 있으면 그 행을 그대로 돌려준다).

    운영자가 DB에 행을 직접 만들 필요가 없게 하는 것이 이 함수의 존재 이유다. 호출 지점은
    진단 완료 경계(`POST /v1/me/assessments/capture`의 신규 적재 분기)이며, 재호출해도
    `provisioned_at`·`provisioned_by`를 덮어쓰지 않는다 — **최초** 생성 계보는 사실이므로
    나중 호출이 그것을 고쳐 쓰면 "무엇이 이 상태를 만들었는가"가 거짓이 된다.

    commit하지 않는다 — 호출부의 트랜잭션 경계 안에서 일어나야 진단 적재와 상태 생성이
    한 단위로 성립한다(반쪽 성공 금지).
    """
    existing = await session.get(LearnerStateRecord, learner_id)
    if existing is not None:
        return PersistedLearnerState.from_record(existing)

    now = datetime.now(UTC)
    record = LearnerStateRecord(
        learner_id=learner_id,
        curriculum_id=curriculum_id,
        current_objective_id=None,
        provisioned_at=now,
        provisioned_by=_REASON_VALUES[reason],
        updated_at=now,
        revision=1,
    )
    session.add(record)
    await session.flush()
    return PersistedLearnerState.from_record(record)


async def apply_learner_state_mutation(
    session: AsyncSession,
    learner_id: uuid.UUID,
    mutation: LearnerStateMutation,
) -> PersistedLearnerState:
    """상태를 변경하는 **유일한** 함수. 행이 없으면 만들지 않고 명시적으로 실패한다.

    생성은 `provision_learner_state`의 책임이다 — 변경 경로가 조용히 행을 만들면 "무엇이
    이 상태를 만들었는가"의 답이 흐려지고, 진단 없이도 상태가 생기는 우회로가 열린다.
    """
    record = await session.get(LearnerStateRecord, learner_id)
    if record is None:
        raise LearnerStateMissingError(learner_id)

    assignments = mutation.assignments()
    if assignments:
        for column, value in assignments.items():
            setattr(record, column, value)
        record.updated_at = datetime.now(UTC)
        record.revision = record.revision + 1
        await session.flush()
    return PersistedLearnerState.from_record(record)
