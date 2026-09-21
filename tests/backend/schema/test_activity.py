"""Schema v1.0 Activity 모델 단위 테스트 — 생성·extra forbid·범위·required·enum 직렬화.

설계 정본: `schemas/v1.0/schema_v1.0.md` §6.1(learning_session·problem_attempt·
attempt_event). 3테이블 + 신규 ENUM 3종(SessionType·AttemptMode·EventType, 기존 Device
재사용).

이 도메인에는 구조 cross-field 불변식(자기관계 등)이 없어 모델에 validator가 없다
(`concept.py`·`activity.py` 방침 — 없는 게 맞다). 따라서 불변식 분기 테스트 없이
required(AttemptEvent.event_at)·복합 PK·BIGSERIAL(event_id None 기본)·범위·enum·
JSONB 필드·extra forbid를 검증한다.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from whymath_backend.schema.activity import (
    AttemptEvent,
    LearningSession,
    ProblemAttempt,
)
from whymath_backend.schema.enums import (
    AttemptMode,
    Device,
    EventType,
    SessionType,
)


# ──────────────────────────────────────────────────────────────────────
# 신규 ENUM 3종 — 값 검증(§6.1 인라인 DDL 정본, 모두 한글)
# ──────────────────────────────────────────────────────────────────────
class TestActivityEnumValues:
    def test_session_type_values_korean(self) -> None:
        """SessionType — §6.1 한글 5종(L602-603)."""
        assert SessionType.자유학습.value == "자유학습"
        assert SessionType.AI추천.value == "AI추천"
        assert {e.value for e in SessionType} == {
            "자유학습",
            "실전모의고사",
            "단원집중",
            "약점보완",
            "AI추천",
        }

    def test_attempt_mode_values_korean(self) -> None:
        """AttemptMode — §6.1 한글 4종(L635-636)."""
        assert AttemptMode.Socratic대화.value == "Socratic대화"
        assert {e.value for e in AttemptMode} == {
            "자유풀이",
            "Socratic대화",
            "힌트제공",
            "풀이공개",
        }

    def test_event_type_values_korean(self) -> None:
        """EventType — §6.1 한글 8종(L667-668) + WH-1 검산결과·힌트제공 + L5 시각화조작
        + EOS-57 문제시도(12종)."""
        assert EventType.문제읽기.value == "문제읽기"
        assert EventType.답입력.value == "답입력"
        assert EventType.검산결과.value == "검산결과"  # WH-1 verify 결과 이벤트(binary 검산·지표 ①)
        assert (
            EventType.힌트제공.value == "힌트제공"
        )  # WH-1 도움 감소 곡선(supply hint_level·지표 ⑤)
        assert EventType.시각화조작.value == "시각화조작"  # L5 시각화 탐구적 조작(슬라이스 96-J)
        assert {e.value for e in EventType} == {
            "문제읽기",
            "조건분석",
            "그래프그리기",
            "계산",
            "지움",
            "막힘",
            "힌트요청",
            "답입력",
            "검산결과",
            "힌트제공",
            "시각화조작",
            "문제시도",  # EOS-57: 채점 확정 이벤트(skill_ids[] 좌석의 event_type)
        }

    def test_str_enum_equality(self) -> None:
        """str-Enum — 문자열 값과 동등 비교(라우터·필터 안정성)."""
        assert SessionType.자유학습 == "자유학습"
        assert AttemptMode.자유풀이 == "자유풀이"
        assert EventType.계산 == "계산"


# ──────────────────────────────────────────────────────────────────────
# LearningSession — 생성·기본값·roundtrip·범위
# ──────────────────────────────────────────────────────────────────────
class TestLearningSession:
    def test_minimal_valid(self) -> None:
        """모든 필드 nullable — 빈 생성 시 session_id만 자동 채워짐."""
        s = LearningSession()
        assert isinstance(s.session_id, uuid.UUID)
        assert s.user_id is None
        assert s.started_at is None
        assert s.session_type is None
        assert s.device_used is None
        assert s.network_type is None

    def test_full_fields_roundtrip(self) -> None:
        """전 필드 채운 세션 — 값 보존 확인."""
        uid = uuid.uuid4()
        concept = uuid.uuid4()
        now = datetime.now(timezone.utc)
        s = LearningSession(
            user_id=uid,
            started_at=now,
            ended_at=now,
            duration_seconds=3600,
            session_type=SessionType.단원집중,
            target_concept_id=concept,
            problems_attempted=10,
            problems_completed=8,
            problems_correct=6,
            focus_score=0.82,
            engagement_score=0.7,
            device_used=Device.아이패드,
            network_type="wifi",
        )
        assert s.user_id == uid
        assert s.target_concept_id == concept
        assert s.duration_seconds == 3600
        assert s.session_type == SessionType.단원집중
        assert s.focus_score == pytest.approx(0.82)
        assert s.device_used == Device.아이패드
        assert s.network_type == "wifi"

    def test_enum_value_serialization_korean(self) -> None:
        """use_enum_values → 한글 enum 값 보존(session_type='약점보완' 등)."""
        s = LearningSession(
            session_type=SessionType.약점보완,
            device_used=Device.안드로이드폰,
        )
        dumped = s.model_dump()
        assert dumped["session_type"] == "약점보완"
        assert dumped["device_used"] == "안드로이드폰"

    def test_focus_score_too_high_rejected(self) -> None:
        """focus_score는 0-1(보수 설정) — 1 초과 거부."""
        with pytest.raises(ValidationError):
            LearningSession(focus_score=1.5)

    def test_engagement_score_negative_rejected(self) -> None:
        """engagement_score는 0-1(보수 설정) — 음수 거부."""
        with pytest.raises(ValidationError):
            LearningSession(engagement_score=-0.1)

    def test_duration_seconds_negative_rejected(self) -> None:
        """duration_seconds는 ge=0(시간 길이) — 음수 거부."""
        with pytest.raises(ValidationError):
            LearningSession(duration_seconds=-1)

    def test_problems_attempted_negative_rejected(self) -> None:
        """problems_attempted는 ge=0(개수) — 음수 거부."""
        with pytest.raises(ValidationError):
            LearningSession(problems_attempted=-1)

    def test_network_type_max_length(self) -> None:
        """network_type은 max_length=20(VARCHAR(20)) — 초과 거부."""
        with pytest.raises(ValidationError):
            LearningSession(network_type="x" * 21)

    def test_invalid_session_type_rejected(self) -> None:
        """session_type에 잘못된 enum 값 거부."""
        with pytest.raises(ValidationError):
            LearningSession(session_type="존재하지않는세션")  # type: ignore[arg-type]

    def test_extra_forbidden(self) -> None:
        """extra='forbid' — 알 수 없는 필드 거부."""
        with pytest.raises(ValidationError):
            LearningSession(bogus="x")  # type: ignore[call-arg]


# ──────────────────────────────────────────────────────────────────────
# ProblemAttempt — 생성·기본값·roundtrip·범위·개인정보 필드
# ──────────────────────────────────────────────────────────────────────
class TestProblemAttempt:
    def test_minimal_valid(self) -> None:
        """모든 필드 nullable — 빈 생성 시 attempt_id만 자동, step_times는 빈 리스트."""
        a = ProblemAttempt()
        assert isinstance(a.attempt_id, uuid.UUID)
        assert a.user_id is None
        assert a.is_correct is None
        assert a.used_socratic is None
        assert a.student_answer is None
        assert a.handwriting_uri is None
        assert a.ocr_result is None
        assert a.step_times == []

    def test_full_fields_roundtrip(self) -> None:
        """전 필드 채운 시도 — 값·JSONB 보존 확인(특성 #96 used_socratic vs used_solution_view)."""
        uid = uuid.uuid4()
        sid = uuid.uuid4()
        pid = uuid.uuid4()
        stuck = uuid.uuid4()
        now = datetime.now(timezone.utc)
        a = ProblemAttempt(
            user_id=uid,
            session_id=sid,
            problem_id=pid,
            started_at=now,
            ended_at=now,
            duration_seconds=240,
            is_correct=False,
            student_answer="42",
            selected_choice_index=1,
            confidence_self_reported=0.6,
            attempt_mode=AttemptMode.Socratic대화,
            used_socratic=True,
            used_hint=True,
            used_solution_view=False,
            handwriting_uri="minio://handwriting/abc.png",
            ocr_result={"latex": "\\int x dx", "confidence": 0.9},
            stuck_at_step=2,
            stuck_at_concept_id=stuck,
            time_vs_expected=2.0,
            step_times=[{"step": 1, "seconds": 30}, {"step": 2, "seconds": 120}],
            created_at=now,
        )
        assert a.session_id == sid
        assert a.is_correct is False
        assert a.student_answer == "42"
        assert a.selected_choice_index == 1
        assert a.attempt_mode == AttemptMode.Socratic대화
        assert a.used_socratic is True
        assert a.used_solution_view is False
        assert a.ocr_result["latex"] == "\\int x dx"
        assert a.stuck_at_step == 2
        assert a.stuck_at_concept_id == stuck
        assert a.time_vs_expected == pytest.approx(2.0)
        assert a.step_times[1]["seconds"] == 120

    def test_enum_value_serialization_korean(self) -> None:
        """use_enum_values → attempt_mode 한글 값 보존."""
        a = ProblemAttempt(attempt_mode=AttemptMode.풀이공개)
        assert a.model_dump()["attempt_mode"] == "풀이공개"

    def test_confidence_too_high_rejected(self) -> None:
        """confidence_self_reported는 0-1(보수 설정) — 1 초과 거부."""
        with pytest.raises(ValidationError):
            ProblemAttempt(confidence_self_reported=1.5)

    def test_time_vs_expected_negative_rejected(self) -> None:
        """time_vs_expected는 ge=0(비율) — 음수 거부."""
        with pytest.raises(ValidationError):
            ProblemAttempt(time_vs_expected=-0.5)

    def test_stuck_at_step_zero_rejected(self) -> None:
        """stuck_at_step은 ge=1(단계 번호) — 0 거부."""
        with pytest.raises(ValidationError):
            ProblemAttempt(stuck_at_step=0)

    def test_selected_choice_index_negative_rejected(self) -> None:
        """ASM-06: selected_choice_index는 ge=0(0-기반 인덱스) — 음수 거부."""
        with pytest.raises(ValidationError):
            ProblemAttempt(selected_choice_index=-1)

    def test_selected_choice_index_zero_accepted(self) -> None:
        """ASM-06: 0은 유효한 0-기반 인덱스(첫 보기) — 거부되지 않는다."""
        a = ProblemAttempt(selected_choice_index=0)
        assert a.selected_choice_index == 0

    def test_duration_seconds_negative_rejected(self) -> None:
        """duration_seconds는 ge=0(시간 길이) — 음수 거부."""
        with pytest.raises(ValidationError):
            ProblemAttempt(duration_seconds=-1)

    def test_invalid_attempt_mode_rejected(self) -> None:
        """attempt_mode에 잘못된 enum 값 거부."""
        with pytest.raises(ValidationError):
            ProblemAttempt(attempt_mode="존재하지않는방식")  # type: ignore[arg-type]

    def test_extra_forbidden(self) -> None:
        """extra='forbid'."""
        with pytest.raises(ValidationError):
            ProblemAttempt(bogus="x")  # type: ignore[call-arg]


# ──────────────────────────────────────────────────────────────────────
# AttemptEvent — required(event_at)·복합 PK·BIGSERIAL(event_id)·범위
# ──────────────────────────────────────────────────────────────────────
class TestAttemptEvent:
    def test_valid_with_required_event_at(self) -> None:
        """event_at(NOT NULL) 필수 — 그것만으로 생성, event_id는 None(BIGSERIAL DB-assigned)."""
        now = datetime.now(timezone.utc)
        e = AttemptEvent(event_at=now)
        assert e.event_at == now
        # BIGSERIAL — DB가 할당하므로 클라이언트 측 기본값은 None
        assert e.event_id is None
        assert e.attempt_id is None
        assert e.event_type is None
        assert e.event_data is None

    def test_full_fields_roundtrip(self) -> None:
        """전 필드 채운 이벤트 — 복합 PK(event_id, event_at)·JSONB 보존."""
        aid = uuid.uuid4()
        uid = uuid.uuid4()
        pid = uuid.uuid4()
        now = datetime.now(timezone.utc)
        e = AttemptEvent(
            event_id=12345,
            event_at=now,
            attempt_id=aid,
            user_id=uid,
            problem_id=pid,
            event_type=EventType.그래프그리기,
            event_data={"x": 1, "y": 2, "tool": "desmos"},
        )
        assert e.event_id == 12345
        assert e.event_at == now
        assert e.attempt_id == aid
        assert e.event_type == EventType.그래프그리기
        assert e.event_data["tool"] == "desmos"

    def test_event_at_required(self) -> None:
        """event_at은 TIMESTAMPTZ NOT NULL(복합 PK 구성요소) → required — 누락 거부."""
        with pytest.raises(ValidationError):
            AttemptEvent()  # type: ignore[call-arg]

    def test_event_id_none_default_bigserial(self) -> None:
        """event_id 미지정 시 None — BIGSERIAL은 DB가 할당(클라이언트 기본값 없음)."""
        e = AttemptEvent(event_at=datetime.now(timezone.utc))
        assert e.event_id is None

    def test_event_id_zero_rejected(self) -> None:
        """event_id는 ge=1(BIGSERIAL 1부터) — 0 거부."""
        with pytest.raises(ValidationError):
            AttemptEvent(event_at=datetime.now(timezone.utc), event_id=0)

    def test_enum_value_serialization_korean(self) -> None:
        """use_enum_values → event_type 한글 값 보존."""
        e = AttemptEvent(
            event_at=datetime.now(timezone.utc),
            event_type=EventType.막힘,
        )
        assert e.model_dump()["event_type"] == "막힘"

    def test_invalid_event_type_rejected(self) -> None:
        """event_type에 잘못된 enum 값 거부."""
        with pytest.raises(ValidationError):
            AttemptEvent(
                event_at=datetime.now(timezone.utc),
                event_type="존재하지않는이벤트",  # type: ignore[arg-type]
            )

    def test_extra_forbidden(self) -> None:
        """extra='forbid'."""
        with pytest.raises(ValidationError):
            AttemptEvent(  # type: ignore[call-arg]
                event_at=datetime.now(timezone.utc),
                bogus="x",
            )
