"""Schema v1.0 Time Series 모델 단위 테스트 — 생성·extra forbid·범위·required·enum 직렬화.

설계 정본: `schemas/v1.0/schema_v1.0.md` §9.1(daily_learning_metrics·
problem_solve_time_distribution·user_behavior_metrics). 3테이블 모두 TimescaleDB
hypertable·복합 PK. **신규 ENUM 없음**(§9가 쓰는 enum은 기존 `Persona` 하나뿐이고
`metric_name`은 VARCHAR open set이라 str) — 따라서 enum 값 검증 클래스는 두지 않는다
(`test_assessment.py`와 달리).

이 도메인에는 구조 cross-field 불변식(자기관계·분위수 정합 등)이 없어 모델에 validator가
없다(`assessment.py`·`activity.py` 방침 — 없는 게 맞다). 따라서 불변식 분기 테스트 없이
required(세 모델 각각의 복합 PK 구성요소)·범위·enum 직렬화·DATE 동작·extra forbid를
검증한다. 특히 `metric_value`는 *범위 제약이 없음*(음수·큰 값 모두 허용)을 확인하고,
`metric_date`가 `datetime.date`로 동작하는지, `persona`가 use_enum_values로 문자열 값으로
직렬화되는지 확인한다.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from whymath_backend.schema.enums import Persona
from whymath_backend.schema.timeseries import (
    DailyLearningMetrics,
    ProblemSolveTimeDistribution,
    UserBehaviorMetrics,
)


# ──────────────────────────────────────────────────────────────────────
# DailyLearningMetrics — required(복합 PK 2종)·DATE·범위·TEXT[] 배열·hypertable
# ──────────────────────────────────────────────────────────────────────
class TestDailyLearningMetrics:
    def test_valid_with_required_pk(self) -> None:
        """복합 PK 2종(user_id·metric_date) 필수 — 그것만으로 생성, 집계값 None·배열 빈."""
        uid = uuid.uuid4()
        d = date(2026, 5, 28)
        m = DailyLearningMetrics(user_id=uid, metric_date=d)
        assert m.user_id == uid
        assert m.metric_date == d
        assert m.minutes_active is None
        assert m.problems_attempted is None
        assert m.problems_correct is None
        assert m.socratic_turns is None
        assert m.avg_focus_score is None
        assert m.concepts_practiced == []

    def test_full_fields_roundtrip(self) -> None:
        """전 필드 채운 일별 집계 — 값·TEXT[] 배열 보존 확인."""
        uid = uuid.uuid4()
        d = date(2026, 5, 28)
        m = DailyLearningMetrics(
            user_id=uid,
            metric_date=d,
            minutes_active=42,
            problems_attempted=15,
            problems_correct=11,
            socratic_turns=7,
            concepts_practiced=["CAL-INT-DEF", "SEQ-LIM"],
            avg_focus_score=0.83,
        )
        assert m.minutes_active == 42
        assert m.problems_attempted == 15
        assert m.problems_correct == 11
        assert m.socratic_turns == 7
        assert m.concepts_practiced == ["CAL-INT-DEF", "SEQ-LIM"]
        assert m.avg_focus_score == pytest.approx(0.83)

    def test_metric_date_is_date_not_datetime(self) -> None:
        """metric_date는 DATE → datetime.date(`user.py` target_exam_date 선례). 날짜로 동작."""
        m = DailyLearningMetrics(user_id=uuid.uuid4(), metric_date=date(2026, 1, 2))
        assert isinstance(m.metric_date, date)
        assert m.metric_date.year == 2026
        assert m.metric_date.month == 1
        assert m.metric_date.day == 2
        # ISO 문자열 입력도 date로 파싱
        m2 = DailyLearningMetrics(
            user_id=uuid.uuid4(),
            metric_date="2026-03-04",  # type: ignore[arg-type]
        )
        assert m2.metric_date == date(2026, 3, 4)

    def test_user_id_required(self) -> None:
        """user_id는 복합 PK 구성요소 → required — 누락 거부."""
        with pytest.raises(ValidationError):
            DailyLearningMetrics(metric_date=date(2026, 5, 28))  # type: ignore[call-arg]

    def test_metric_date_required(self) -> None:
        """metric_date는 복합 PK 구성요소·hypertable 분할 키 → required — 누락 거부."""
        with pytest.raises(ValidationError):
            DailyLearningMetrics(user_id=uuid.uuid4())  # type: ignore[call-arg]

    def test_avg_focus_score_too_high_rejected(self) -> None:
        """avg_focus_score는 0-1(정규화 점수) — 1 초과 거부."""
        with pytest.raises(ValidationError):
            DailyLearningMetrics(
                user_id=uuid.uuid4(),
                metric_date=date(2026, 5, 28),
                avg_focus_score=1.5,
            )

    def test_avg_focus_score_negative_rejected(self) -> None:
        """avg_focus_score는 ge=0 — 음수 거부."""
        with pytest.raises(ValidationError):
            DailyLearningMetrics(
                user_id=uuid.uuid4(),
                metric_date=date(2026, 5, 28),
                avg_focus_score=-0.1,
            )

    def test_minutes_active_negative_rejected(self) -> None:
        """minutes_active는 ge=0(시간 길이) — 음수 거부."""
        with pytest.raises(ValidationError):
            DailyLearningMetrics(
                user_id=uuid.uuid4(),
                metric_date=date(2026, 5, 28),
                minutes_active=-1,
            )

    def test_problems_attempted_negative_rejected(self) -> None:
        """problems_attempted는 ge=0(개수) — 음수 거부."""
        with pytest.raises(ValidationError):
            DailyLearningMetrics(
                user_id=uuid.uuid4(),
                metric_date=date(2026, 5, 28),
                problems_attempted=-1,
            )

    def test_extra_forbidden(self) -> None:
        """extra='forbid' — 알 수 없는 필드 거부."""
        with pytest.raises(ValidationError):
            DailyLearningMetrics(  # type: ignore[call-arg]
                user_id=uuid.uuid4(),
                metric_date=date(2026, 5, 28),
                bogus="x",
            )


# ──────────────────────────────────────────────────────────────────────
# ProblemSolveTimeDistribution — required(복합 PK 3종·persona enum)·범위·enum 직렬화
# ──────────────────────────────────────────────────────────────────────
class TestProblemSolveTimeDistribution:
    def test_valid_with_required_pk(self) -> None:
        """복합 PK 3종(problem_id·persona·measured_at) 필수 — 그것만으로 생성, 분위수 None."""
        pid = uuid.uuid4()
        now = datetime.now(timezone.utc)
        d = ProblemSolveTimeDistribution(
            problem_id=pid,
            persona=Persona.A_일반고고3,
            measured_at=now,
        )
        assert d.problem_id == pid
        assert d.persona == Persona.A_일반고고3
        assert d.measured_at == now
        assert d.p10_seconds is None
        assert d.p50_seconds is None
        assert d.p90_seconds is None
        assert d.sample_size is None

    def test_full_fields_roundtrip(self) -> None:
        """전 필드 채운 풀이 시간 분포 — 분위수·표본 보존 확인."""
        pid = uuid.uuid4()
        now = datetime.now(timezone.utc)
        d = ProblemSolveTimeDistribution(
            problem_id=pid,
            persona=Persona.C_검정고시N수,
            measured_at=now,
            p10_seconds=30,
            p50_seconds=90,
            p90_seconds=240,
            sample_size=512,  # corpus-pin: 코퍼스 무관 — 합성 표본 크기
        )
        assert d.p10_seconds == 30
        assert d.p50_seconds == 90
        assert d.p90_seconds == 240
        assert d.sample_size == 512  # corpus-pin: 코퍼스 무관 — 합성 표본 크기

    def test_persona_enum_value_serialization(self) -> None:
        """use_enum_values → persona가 문자열 값으로 직렬화(예: 'A_일반고고3')."""
        d = ProblemSolveTimeDistribution(
            problem_id=uuid.uuid4(),
            persona=Persona.A_일반고고3,
            measured_at=datetime.now(timezone.utc),
        )
        dumped = d.model_dump()
        assert dumped["persona"] == "A_일반고고3"
        assert isinstance(dumped["persona"], str)

    def test_problem_id_required(self) -> None:
        """problem_id는 복합 PK 구성요소 → required — 누락 거부."""
        with pytest.raises(ValidationError):
            ProblemSolveTimeDistribution(  # type: ignore[call-arg]
                persona=Persona.A_일반고고3,
                measured_at=datetime.now(timezone.utc),
            )

    def test_persona_required(self) -> None:
        """persona는 enum이지만 복합 PK 구성요소 → required(Optional 아님) — 누락 거부."""
        with pytest.raises(ValidationError):
            ProblemSolveTimeDistribution(  # type: ignore[call-arg]
                problem_id=uuid.uuid4(),
                measured_at=datetime.now(timezone.utc),
            )

    def test_measured_at_required(self) -> None:
        """measured_at은 복합 PK 구성요소·hypertable 분할 키 → required — 누락 거부."""
        with pytest.raises(ValidationError):
            ProblemSolveTimeDistribution(  # type: ignore[call-arg]
                problem_id=uuid.uuid4(),
                persona=Persona.A_일반고고3,
            )

    def test_invalid_persona_rejected(self) -> None:
        """persona에 잘못된 enum 값 거부."""
        with pytest.raises(ValidationError):
            ProblemSolveTimeDistribution(
                problem_id=uuid.uuid4(),
                persona="F_존재하지않는페르소나",  # type: ignore[arg-type]
                measured_at=datetime.now(timezone.utc),
            )

    def test_p50_seconds_negative_rejected(self) -> None:
        """p50_seconds는 ge=0(시간 길이) — 음수 거부."""
        with pytest.raises(ValidationError):
            ProblemSolveTimeDistribution(
                problem_id=uuid.uuid4(),
                persona=Persona.A_일반고고3,
                measured_at=datetime.now(timezone.utc),
                p50_seconds=-1,
            )

    def test_sample_size_negative_rejected(self) -> None:
        """sample_size는 ge=0(표본 수) — 음수 거부."""
        with pytest.raises(ValidationError):
            ProblemSolveTimeDistribution(
                problem_id=uuid.uuid4(),
                persona=Persona.A_일반고고3,
                measured_at=datetime.now(timezone.utc),
                sample_size=-1,
            )

    def test_extra_forbidden(self) -> None:
        """extra='forbid' — 알 수 없는 필드 거부."""
        with pytest.raises(ValidationError):
            ProblemSolveTimeDistribution(  # type: ignore[call-arg]
                problem_id=uuid.uuid4(),
                persona=Persona.A_일반고고3,
                measured_at=datetime.now(timezone.utc),
                bogus="x",
            )


# ──────────────────────────────────────────────────────────────────────
# UserBehaviorMetrics — required(복합 PK 3종·metric_name str)·metric_value 무제약
# ──────────────────────────────────────────────────────────────────────
class TestUserBehaviorMetrics:
    def test_valid_with_required_pk(self) -> None:
        """복합 PK 3종(user_id·metric_name·measured_at) 필수 — 그것만으로 생성, 값 None."""
        uid = uuid.uuid4()
        now = datetime.now(timezone.utc)
        m = UserBehaviorMetrics(
            user_id=uid,
            metric_name="churn_risk",
            measured_at=now,
        )
        assert m.user_id == uid
        assert m.metric_name == "churn_risk"
        assert m.measured_at == now
        assert m.metric_value is None

    def test_full_fields_roundtrip(self) -> None:
        """전 필드 채운 행동 지표 — 값 보존 확인."""
        uid = uuid.uuid4()
        now = datetime.now(timezone.utc)
        m = UserBehaviorMetrics(
            user_id=uid,
            metric_name="session_length",
            measured_at=now,
            metric_value=1234.5678,
        )
        assert m.metric_name == "session_length"
        assert m.metric_value == pytest.approx(1234.5678)

    def test_user_id_required(self) -> None:
        """user_id는 복합 PK 구성요소 → required — 누락 거부."""
        with pytest.raises(ValidationError):
            UserBehaviorMetrics(  # type: ignore[call-arg]
                metric_name="streak",
                measured_at=datetime.now(timezone.utc),
            )

    def test_metric_name_required(self) -> None:
        """metric_name은 복합 PK 구성요소(VARCHAR open set) → required — 누락 거부."""
        with pytest.raises(ValidationError):
            UserBehaviorMetrics(  # type: ignore[call-arg]
                user_id=uuid.uuid4(),
                measured_at=datetime.now(timezone.utc),
            )

    def test_measured_at_required(self) -> None:
        """measured_at은 복합 PK 구성요소·hypertable 분할 키 → required — 누락 거부."""
        with pytest.raises(ValidationError):
            UserBehaviorMetrics(  # type: ignore[call-arg]
                user_id=uuid.uuid4(),
                metric_name="streak",
            )

    def test_metric_name_max_length_enforced(self) -> None:
        """metric_name은 max_length=50(VARCHAR(50)) — 초과 거부."""
        with pytest.raises(ValidationError):
            UserBehaviorMetrics(
                user_id=uuid.uuid4(),
                metric_name="x" * 51,
                measured_at=datetime.now(timezone.utc),
            )

    def test_metric_value_allows_negative(self) -> None:
        """⚠️ metric_value는 범위 제약 없음 — 음수 허용(metric_name마다 의미가 달라서)."""
        m = UserBehaviorMetrics(
            user_id=uuid.uuid4(),
            metric_name="persona_shift",
            measured_at=datetime.now(timezone.utc),
            metric_value=-42.0,
        )
        assert m.metric_value == pytest.approx(-42.0)

    def test_metric_value_allows_large(self) -> None:
        """⚠️ metric_value는 범위 제약 없음 — 큰 값도 허용."""
        m = UserBehaviorMetrics(
            user_id=uuid.uuid4(),
            metric_name="session_length",
            measured_at=datetime.now(timezone.utc),
            metric_value=9_999_999.9999,
        )
        assert m.metric_value == pytest.approx(9_999_999.9999)

    def test_extra_forbidden(self) -> None:
        """extra='forbid' — 알 수 없는 필드 거부."""
        with pytest.raises(ValidationError):
            UserBehaviorMetrics(  # type: ignore[call-arg]
                user_id=uuid.uuid4(),
                metric_name="streak",
                measured_at=datetime.now(timezone.utc),
                bogus="x",
            )
