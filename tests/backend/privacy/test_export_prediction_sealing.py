"""ASM-12 — 열람권 export의 예측 필드 봉인 (양방향 무가드 해소).

사고 경위(2026-08-11 협업 r3 자체 재검증): ASM-07(#732)이 학생 대면 예측 5필드
(`STUDENT_HIDDEN_PREDICTION_FIELDS`)를 3층 봉인했으나, 그보다 먼저(#668) 배선된
`GET /v1/me/export`는 내부 정본 `Assessment`를 `to_schema().model_dump()` 그대로
실어 필터 0으로 학생에게 반환했다 — 같은 학생 토큰 클래스(ConsentedUser)의 두 번째
표면이 봉인 밖에 있었다. `state_snapshots`(`UserStateSnapshot.estimated_*` 3필드)도
같은 경로다. 봉인 테스트는 export를 0회 참조했고 export 테스트는 봉인 필드를 0회
참조했다(양방향 무가드 — 실측).

이 파일이 그 구멍을 payload 수준에서 동결한다. **OpenAPI 도달성 스캔으로는 잡을 수
없다** — `UserDataExport.data`가 무타입 `dict[str, list[dict]]`라 컴포넌트 스키마
그래프에 Assessment가 아예 나타나지 않는다. 그래서 스키마 스캔(`test_prediction_
field_sealing.py`)이 아니라 *조립된 페이로드*를 직접 검사한다.

픽스처는 봉인 5필드에 **실값**을 넣는다 — 현재 라이브 writer가 0건이라 값이 항상
null이지만, 봉인 설계 취지가 "writer가 붙는 순간"을 막는 것이므로 값 부재를 안전
근거로 쓸 수 없다(태스크 notes). 값이 실린 상태에서 키가 사라져야 진짜 봉인이다.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.assessment import Assessment
from whymath_backend.db.models.user import UserStateSnapshot
from whymath_backend.privacy.export import _EXPORT_PLAN, UserDataExport, export_user_data
from whymath_backend.schema.assessment import STUDENT_HIDDEN_PREDICTION_FIELDS

_USER_ID = uuid.UUID("00000000-0000-0000-0000-00000000a512")

#: UserStateSnapshot이 실제로 갖는 봉인 필드 부분집합 — 정본 집합과의 교집합으로
#: 계산한다(이름을 여기 복사하면 정본이 바뀌어도 이 테스트는 모른 채 남는다).
_SNAPSHOT_SEALED = STUDENT_HIDDEN_PREDICTION_FIELDS & {
    c.key for c in UserStateSnapshot.__mapper__.column_attrs
}


def _sealed_assessment_row() -> Assessment:
    """봉인 5필드 전부에 실값을 넣은 내부 정본 행(transient — DB 불요)."""
    return Assessment(
        assessment_id=uuid.uuid4(),
        user_id=_USER_ID,
        estimated_grade=2.0,
        estimated_score=131,
        estimated_percentile=88.5,
        target_university_id=uuid.uuid4(),
        admission_probability=0.42,
        # JSONB 리스트 컬럼 — transient 행은 서버 default가 안 붙어 None이 되고,
        # 스키마가 `list[...]`(None 불허)라 to_schema 검증에 걸린다. 빈 리스트로 채운다.
        concept_diagnosis=[],
        pattern_diagnosis=[],
        weak_points=[],
        strong_points=[],
        recommended_path=[],
    )


def _sealed_snapshot_row() -> UserStateSnapshot:
    """스냅샷 쪽 봉인 부분집합(estimated_*)에 실값을 넣은 행(transient)."""
    return UserStateSnapshot(
        snapshot_id=uuid.uuid4(),
        user_id=_USER_ID,
        estimated_grade=2.0,
        estimated_score=131,
        estimated_percentile=88.5,
    )


class _FakeScalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)

    def first(self) -> Any:
        return self._rows[0] if self._rows else None


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._rows)


class _FakeSession:
    """execute 순서별 결과 큐 — `test_export.py`의 검증된 패턴 재사용."""

    def __init__(self, result_rows: list[list[Any]]) -> None:
        self._queue = list(result_rows)

    async def execute(self, stmt: Any) -> _FakeResult:
        return _FakeResult(self._queue.pop(0))

    async def commit(self) -> None:  # pragma: no cover - 읽기 전용 경로
        raise AssertionError("export는 읽기 전용이다")


def _run_export() -> UserDataExport:
    """Assessment·UserStateSnapshot 자리에 봉인값 실린 실제 ORM 행을 넣고 조립한다."""
    queue: list[list[Any]] = []
    for model, _column, _category in _EXPORT_PLAN:
        if model is Assessment:
            queue.append([_sealed_assessment_row()])
        elif model is UserStateSnapshot:
            queue.append([_sealed_snapshot_row()])
        else:
            queue.append([])
    queue.append([])  # dialogue_turns 조인
    queue.append([])  # user_profile 단건
    queue.append([])  # recommendation_events 조인(EOS-131 — 프로필 뒤 마지막)
    session = cast(AsyncSession, _FakeSession(queue))
    return asyncio.run(export_user_data(session, user_id=_USER_ID))


class TestExportPredictionSeal:
    """④ 변별력·양방향 가드 — 봉인값이 실린 fixture로 페이로드를 직접 검사한다."""

    def test_fixture_rows_actually_carry_sealed_values(self) -> None:
        """음성 대조 — 내부 정본에는 값이 실려 *있어야* 한다.

        이 검사가 없으면 fixture가 조용히 빈 행을 만들어도 아래 봉인 검사들이
        공허하게 통과한다(성공/실패에 같은 값 — 위장 검증 금지).
        """
        internal = _sealed_assessment_row().to_schema().model_dump()
        for field in sorted(STUDENT_HIDDEN_PREDICTION_FIELDS):
            assert internal[field] is not None, f"fixture가 {field}에 값을 싣지 못했다"
        snapshot_internal = _sealed_snapshot_row().to_schema().model_dump()
        for field in sorted(_SNAPSHOT_SEALED):
            assert snapshot_internal[field] is not None

    def test_snapshot_sealed_subset_is_nonempty(self) -> None:
        """교집합 자체의 하한 — 모델 개명으로 부분집합이 비면 검사가 무효가 된다."""
        assert _SNAPSHOT_SEALED >= {
            "estimated_grade",
            "estimated_score",
            "estimated_percentile",
        }

    def test_export_assessments_do_not_carry_prediction_fields(self) -> None:
        """①/③ — export의 assessments 행에 봉인 5필드가 *키째로* 없어야 한다."""
        export = _run_export()
        for row in export.data["assessments"]:
            leaked = sorted(set(row) & STUDENT_HIDDEN_PREDICTION_FIELDS)
            assert leaked == [], (
                f"GET /v1/me/export의 assessments가 봉인 필드를 나른다: {leaked} — "
                "ASM-07 봉인이 이 표면을 덮지 않는다(ASM-12)"
            )

    def test_export_state_snapshots_do_not_carry_prediction_fields(self) -> None:
        """① — 두 번째 도달 경로 state_snapshots도 같은 계약이다."""
        export = _run_export()
        for row in export.data["state_snapshots"]:
            leaked = sorted(set(row) & STUDENT_HIDDEN_PREDICTION_FIELDS)
            assert leaked == [], f"state_snapshots가 봉인 필드를 나른다: {leaked}"

    def test_every_export_category_is_free_of_sealed_keys(self) -> None:
        """⑤ 미래 표면 가드 — 새 카테고리가 봉인 필드를 실으면 여기서 red가 난다."""
        export = _run_export()
        offenders: list[str] = []
        for category, rows in export.data.items():
            for row in rows:
                for field in sorted(set(row) & STUDENT_HIDDEN_PREDICTION_FIELDS):
                    offenders.append(f"{category}.{field}")
        if export.user_profile is not None:
            for field in sorted(set(export.user_profile) & STUDENT_HIDDEN_PREDICTION_FIELDS):
                offenders.append(f"user_profile.{field}")
        assert offenders == [], f"export 페이로드에 봉인 필드 잔존: {offenders}"

    def test_not_included_discloses_prediction_exclusion(self) -> None:
        """② 정직 고지 — 제외는 침묵이 아니라 고지다(부분 export 정직·완전성).

        열람권 대상 데이터를 빼면서 고지하지 않으면 부분 export를 완전 export로
        위장하게 된다. 변호사 검토 전 잠정 제외임이 사용자에게 보여야 한다.
        """
        export = _run_export()
        assert any("예측" in line for line in export.not_included), (
            "not_included에 예측 필드 제외 고지가 없다 — " f"현재 고지: {export.not_included}"
        )
