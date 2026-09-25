"""EOS-11 Learning Event Trace 읽기 축 — 계약·투영·가용성 대장 (hermetic·DB 없이).

검증 축 5개:
  ① **어휘 누락 0** — `EventType` 12종이 트레이스 매핑 또는 휴면 집합 중 정확히 한쪽에 속한다.
     새 EventType이 생겼는데 매핑을 안 늘리면 여기서 깨진다(조용한 누락 차단).
  ② **가용성 배정의 실측 일치** — `DORMANT`로 선언한 원천에 정말 writer가 0건인지를 저장소
     **AST 전수 스캔**으로 확인한다. 누군가 `LearningSession` writer를 배선하면 이 테스트가
     깨져서 대장을 고치게 한다 — 배정이 산문 주장이 아니라 기계 판정이 되는 지점이다.
     (EOS-131이 실제로 그렇게 했다 — `l2/learning_session_writer`가 `insert(LearningSession)`로
     생산하므로 스캐너가 `insert(X)` 형태도 생산 지점으로 센다.)
  ③ **투영 의미** — 전후 값·첫 측정(None≠0)·오답 파생·발생/수신 폴백.
  ④ **PII 경계** — 봉투에 답안 슬롯이 없고, `event_data`는 allowlist 스칼라만 통과한다.
  ⑤ **침묵 실패 금지** — 읽기 경로는 실패를 삼키지 않고, 투영이 행을 버릴 때는 로그가 남는다.

적재(writer) 축의 무증상 방지는 `test_attempt_skill_event.py::test_failure_log_carries_the_
exception_type_name`이 이미 동결한다 — 이 파일은 **읽기 축**을 맡는다.
"""

from __future__ import annotations

import ast
import logging
import pathlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.l2.learning_event_trace import (
    _ATTEMPT_EVENT_TYPE_MAP,
    _DETAIL_ALLOWLIST,
    _DORMANT_EVENT_TYPES,
    _SOURCE_REGISTRY,
    _TIE_ORDER,
    MAX_TRACE_LIMIT,
    LearningEvent,
    MasteryChange,
    SourceAvailability,
    TimeBasis,
    TraceEventType,
    TraceSource,
    build_trace,
    project_ability_rows,
    project_assessment_rows,
    project_attempt_event_rows,
    project_attempt_rows,
    project_mastery_rows,
    project_misconception_rows,
    project_recommendation_rows,
    project_session_rows,
    render_trace_lines,
    sort_entries,
)
from whymath_backend.schema.enums import EventType
from whymath_backend.schema.event_data_contract import EVENT_DATA_CONTRACT

_UID = uuid.uuid4()
_T0 = datetime(2026, 9, 16, 9, 0, tzinfo=UTC)


def _at(minutes: int) -> datetime:
    return _T0 + timedelta(minutes=minutes)


# ──────────────────────────────────────────────────────────────────────────
# 픽스처 행 — ORM 없이 필요한 속성만(hermetic·repo 관례)
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class _AssessmentRow:
    started_at: datetime | None
    completed_at: datetime | None = None
    assessment_type: Any = None


@dataclass
class _AttemptRow:
    attempt_id: uuid.UUID
    problem_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    is_correct: bool | None = None
    duration_seconds: int | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    ingested_at: datetime | None = None
    created_at: datetime | None = None


@dataclass
class _EventRow:
    event_type: EventType | None
    event_at: datetime
    event_time: datetime | None = None
    event_data: dict[str, Any] | None = None
    attempt_id: uuid.UUID | None = None
    problem_id: uuid.UUID | None = None


@dataclass
class _MasteryRow:
    measured_at: datetime
    mastery: float | None
    mastery_before: float | None = None
    confidence: float | None = None
    sample_size: int | None = None
    concept_id: uuid.UUID | None = None
    skill_id: str | None = None


@dataclass
class _MisconceptionRow:
    misconception_id: str
    created_at: datetime
    confidence: float = 0.7
    evidence_count: int = 2
    is_active: bool = True


@dataclass
class _AbilityRow:
    measured_at: datetime
    theta: float
    response_count: int
    concept_id: uuid.UUID | None = None


# ──────────────────────────────────────────────────────────────────────────
# ① 어휘 누락 0 — 거버넌스
# ──────────────────────────────────────────────────────────────────────────
class TestVocabularyGovernance:
    def test_every_event_type_is_mapped_or_declared_dormant(self) -> None:
        """분류되지 않은 EventType이 있으면 그 이벤트는 트레이스에서 조용히 사라진다."""
        classified = set(_ATTEMPT_EVENT_TYPE_MAP) | _DORMANT_EVENT_TYPES
        assert classified == set(EventType), (
            "EventType이 매핑·휴면 어느 쪽에도 없다 — 새 타입이 생겼다면 "
            f"_ATTEMPT_EVENT_TYPE_MAP 또는 _DORMANT_EVENT_TYPES에 넣어라: "
            f"{sorted(e.value for e in set(EventType) - classified)}"
        )

    def test_mapped_and_dormant_are_disjoint(self) -> None:
        assert not (set(_ATTEMPT_EVENT_TYPE_MAP) & _DORMANT_EVENT_TYPES)

    def test_registry_covers_every_trace_event_type(self) -> None:
        """대장에 없는 트레이스 타입이 있으면 그 타입의 0건이 해석 불가가 된다."""
        registered = {et for et, _, _, _ in _SOURCE_REGISTRY}
        assert registered == set(TraceEventType)

    def test_registry_has_no_duplicate_event_types(self) -> None:
        registered = [et for et, _, _, _ in _SOURCE_REGISTRY]
        assert len(registered) == len(set(registered))

    def test_detail_allowlist_keys_exist_in_the_payload_contract(self) -> None:
        """allowlist에 오타가 있으면 그 키는 영원히 비어 있고 아무도 모른다."""
        for event_type, keys in _DETAIL_ALLOWLIST.items():
            model = EVENT_DATA_CONTRACT.get(event_type)
            assert model is not None, f"{event_type.value}는 페이로드 계약에 없다"
            contract_fields = set(model.model_fields)
            unknown = set(keys) - contract_fields
            assert not unknown, (
                f"{event_type.value} allowlist에 계약에 없는 키가 있다: {sorted(unknown)} "
                f"(계약 필드: {sorted(contract_fields)})"
            )

    def test_visualization_payload_is_not_in_the_allowlist(self) -> None:
        """`시각화조작.payload`는 자유형이라 정밀 좌표가 들어올 수 있다(DP-02 금지 축)."""
        assert "payload" not in _DETAIL_ALLOWLIST[EventType.시각화조작]


# ──────────────────────────────────────────────────────────────────────────
# ② 가용성 배정의 실측 일치 — 저장소 AST 전수 스캔
# ──────────────────────────────────────────────────────────────────────────
_BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[3] / "src" / "backend" / "whymath_backend"

#: 트레이스 원천 ↔ 그 테이블의 ORM 클래스명. **PRODUCED·DORMANT 양방향**으로 대조한다 —
#: 한쪽만 보면 "미생산인데 생산으로 선언"(0건이 '학생이 안 했다'로 읽힘)을 못 잡는다.
_ORM_CLASS_BY_SOURCE: dict[TraceSource, str] = {
    TraceSource.ASSESSMENT: "Assessment",
    TraceSource.PROBLEM_ATTEMPT: "ProblemAttempt",
    TraceSource.ATTEMPT_EVENT: "AttemptEvent",
    TraceSource.CONCEPT_MASTERY_HISTORY: "ConceptMasteryHistory",
    TraceSource.SKILL_MASTERY_HISTORY: "SkillMasteryHistory",
    TraceSource.ABILITY_SNAPSHOT: "AbilitySnapshot",
    TraceSource.MISCONCEPTION_HYPOTHESIS: "MisconceptionHypothesisRecord",
    TraceSource.LEARNING_SESSION: "LearningSession",
    TraceSource.USER_STATE_SNAPSHOT: "UserStateSnapshot",
    # EOS-131: 추천 처치의 writer(`EvidenceEvent(...)`)는 종전에도 있었고 결합 키만 없었다 —
    # 실 session_id로 결합되면서 PRODUCED가 됐으므로 이제 생산 지점 스캔 축에 오른다.
    TraceSource.EVIDENCE_EVENT: "EvidenceEvent",
}

#: 스캔 대상이 아닌 원천과 그 사유(빠뜨린 것과 의도적 제외를 구분한다).
_SOURCES_WITHOUT_ORM_SCAN: dict[TraceSource, str] = {
    # 열람 로그 테이블 자체가 없다 — 셀 ORM 클래스가 없으므로 스캔 축에 오르지 않는다.
    TraceSource.CONCEPT_CONTENT: "학습자별 열람 로그 테이블 부재",
}


def _module_aliases(tree: ast.AST) -> dict[str, str]:
    """`from x import Foo as Bar` → {"Bar": "Foo"} (별칭 생산자를 놓치지 않기 위해).

    별칭을 무시하면 `AttemptEvent as AttemptEventORM`로 쓰는 `api/coach.py`의 writer 5건이
    안 보인다 — 그러면 실재 writer가 있는 원천을 '미생산'으로 확인해 주는 **거짓 안심**이 된다.
    """
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.asname:
                    aliases[alias.asname] = alias.name
    return aliases


#: `insert(X)` 형태의 생산 — SQLAlchemy core `insert`와 PostgreSQL 방언 `insert`(흔히
#: `pg_insert`로 별칭). EOS-131 writer가 `ON CONFLICT DO NOTHING` 때문에 이 형태를 쓴다.
_INSERT_CALL_NAMES = frozenset({"insert"})


def _construction_sites(class_name: str) -> list[str]:
    """`ClassName(...)`·`ClassName.from_schema(...)`·`insert(ClassName)` 호출 지점 전수 스캔.

    별칭을 해소한다(`from ... import insert as pg_insert` 포함).

    모델·스키마 정의 자신은 제외한다(정의는 생산이 아니다). 스캔 대상이 0파일이면 경로가
    틀린 것이므로 그 자체를 실패로 만든다(공허한 통과 금지).
    """
    scanned = 0
    sites: list[str] = []
    for path in _BACKEND_ROOT.rglob("*.py"):
        rel = path.relative_to(_BACKEND_ROOT).as_posix()
        if rel.startswith(("db/models/", "schema/")):
            continue
        scanned += 1
        tree = ast.parse(path.read_text(encoding="utf-8"))
        aliases = _module_aliases(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            local: str | None = None
            if (
                isinstance(func, ast.Name)
                and aliases.get(func.id, func.id) in _INSERT_CALL_NAMES
                and node.args
                and isinstance(node.args[0], ast.Name)
            ):
                # `insert(X)` — 생산 대상은 호출 이름이 아니라 첫 인자다.
                local = node.args[0].id
            elif isinstance(func, ast.Name):
                local = func.id
            elif (
                isinstance(func, ast.Attribute)
                and func.attr == "from_schema"
                and isinstance(func.value, ast.Name)
            ):
                local = func.value.id
            if local is None:
                continue
            if aliases.get(local, local) == class_name:
                sites.append(f"{rel}:{node.lineno}")
    assert scanned > 0, f"스캔 대상 0파일 — 경로가 틀렸다: {_BACKEND_ROOT}"
    return sites


def _availability_of(source: TraceSource) -> SourceAvailability:
    avails = {av for _, src, av, _ in _SOURCE_REGISTRY if src is source}
    assert len(avails) == 1, f"{source.value}의 가용성 배정이 일관되지 않다: {avails}"
    return avails.pop()


class TestAvailabilityAssignmentMatchesReality:
    """대장의 가용성 배정이 코드 실측과 어긋나면 깨진다(배정을 기계가 판정한다).

    **양방향**이다: writer가 없는데 PRODUCED라고 하면 실재하지 않는 활동을 학생 탓으로
    돌리고, writer가 생겼는데 DORMANT로 두면 실재하는 활동을 '미측정'으로 은폐한다.
    """

    @pytest.mark.parametrize(
        ("source", "class_name"), sorted(_ORM_CLASS_BY_SOURCE.items(), key=lambda kv: kv[0].value)
    )
    def test_writer_presence_matches_the_declared_availability(
        self, source: TraceSource, class_name: str
    ) -> None:
        sites = _construction_sites(class_name)
        declared = _availability_of(source)
        expected_produced = declared is SourceAvailability.PRODUCED
        assert bool(sites) == expected_produced, (
            f"{source.value}({class_name})의 대장 배정은 {declared.value}인데 "
            f"실측 생산 지점은 {len(sites)}건이다: {sites[:3]}. "
            "대장을 실측에 맞춰 고쳐라 — 어긋난 채로 두면 0건의 의미가 거짓이 된다."
        )

    def test_the_scanner_finds_a_known_producer(self) -> None:
        """스캐너 자신의 변별력 — 실재 writer(ProblemAttempt)는 반드시 잡혀야 한다.

        이 대조군이 없으면 스캐너가 *아무것도 못 찾는* 고장 상태에서도 위 테스트가
        '전부 DORMANT'로 통과한다.
        """
        assert _construction_sites("ProblemAttempt"), "스캐너가 실재 writer를 못 찾는다(고장)"

    def test_the_scanner_resolves_import_aliases(self) -> None:
        """별칭 해소의 변별력 — `AttemptEvent as AttemptEventORM`로 쓰는 코치 writer를 잡는가.

        별칭을 못 보면 실재 writer가 '미생산'으로 확인돼 거짓 안심이 된다.
        """
        sites = _construction_sites("AttemptEvent")
        assert any(
            site.startswith("api/coach.py") for site in sites
        ), f"별칭(AttemptEventORM) 생산 지점을 못 찾았다: {sites}"

    def test_every_source_is_either_scanned_or_explicitly_excluded(self) -> None:
        """대장의 모든 원천이 스캔 대상이거나 사유 있는 제외여야 한다(조용한 누락 0)."""
        registered = {src for _, src, _, _ in _SOURCE_REGISTRY}
        covered = set(_ORM_CLASS_BY_SOURCE) | set(_SOURCES_WITHOUT_ORM_SCAN)
        assert (
            registered - covered == set()
        ), f"스캔 축에도 제외 목록에도 없는 원천: {sorted(s.value for s in registered - covered)}"

    def test_the_scanner_counts_insert_statements_as_production(self) -> None:
        """`insert(X)` 형태 생산의 변별력 — EOS-131 세션 writer는 이 형태로만 생산한다.

        이 형태를 못 보면 실재 writer가 있는 `learning_session`이 '생산 0'으로 읽혀, PRODUCED
        배정이 거짓 RED가 되거나(대장이 옳을 때) 거짓 DORMANT가 통과한다(대장이 틀릴 때).
        """
        sites = _construction_sites("LearningSession")
        assert any(
            site.startswith("l2/learning_session_writer.py") for site in sites
        ), f"insert(LearningSession) 생산 지점을 못 찾았다: {sites}"

    def test_recommendation_is_joinable_only_through_the_session(self) -> None:
        """EOS-131 ④: 추천은 PRODUCED가 됐지만 **user_id 컬럼·슬롯 없이** 결합된다.

        종전 `UNJOINABLE` 동결(학습자 축 컬럼 부재)의 반대 방향 단언이다 — 컬럼 부재는 그대로
        지키고(PED-03·REC-03 구조적 차단), 결합 경로가 `session_id` 하나임을 고정한다.
        """
        import inspect

        from whymath_backend.db.models.evidence_event import EvidenceEvent
        from whymath_backend.l2.recommendation_evidence import record_recommendation_treatment

        columns = set(EvidenceEvent.__table__.columns.keys())
        assert "user_id" not in columns
        assert "learner_id" not in columns
        assert "session_id" in columns
        params = set(inspect.signature(record_recommendation_treatment).parameters)
        assert "user_id" not in params and "learner_id" not in params
        assert "learning_session_id" in params
        assert _availability_of(TraceSource.EVIDENCE_EVENT) is SourceAvailability.PRODUCED
        assert _availability_of(TraceSource.LEARNING_SESSION) is SourceAvailability.PRODUCED


# ──────────────────────────────────────────────────────────────────────────
# ③ 투영 의미
# ──────────────────────────────────────────────────────────────────────────
class TestMasteryProjection:
    def test_before_and_after_are_both_carried(self) -> None:
        """계획서 §17 `mastery_updated(0.54→0.43)` — 전후 둘 다 없으면 역추적이 불가능하다."""
        rows = [_MasteryRow(measured_at=_at(1), mastery=0.43, mastery_before=0.54)]
        (event,) = project_mastery_rows(_UID, rows, concept_axis=True)
        assert event.mastery_change is not None
        assert event.mastery_change.mastery_before == pytest.approx(0.54)
        assert event.mastery_change.mastery_after == pytest.approx(0.43)
        assert event.mastery_change.delta == pytest.approx(-0.11)
        assert event.mastery_change.is_first_measurement is False

    def test_first_measurement_keeps_before_as_none_not_zero(self) -> None:
        """0.0으로 채우면 첫 채점이 항상 '0.0에서 올랐다'는 없는 상승이 된다(S3-07 None≠0)."""
        rows = [_MasteryRow(measured_at=_at(1), mastery=0.6, mastery_before=None)]
        (event,) = project_mastery_rows(_UID, rows, concept_axis=True)
        assert event.mastery_change is not None
        assert event.mastery_change.mastery_before is None
        assert event.mastery_change.is_first_measurement is True
        assert event.mastery_change.delta is None

    def test_skill_axis_fills_skill_id_and_not_concept_id(self) -> None:
        rows = [_MasteryRow(measured_at=_at(1), mastery=0.5, skill_id="skill.slope")]
        (event,) = project_mastery_rows(_UID, rows, concept_axis=False)
        assert event.event_type is TraceEventType.SKILL_MASTERY_UPDATED
        assert event.skill_id == "skill.slope"
        assert event.concept_id is None

    def test_delta_is_none_when_after_is_missing(self) -> None:
        change = MasteryChange(mastery_before=0.5, mastery_after=None, is_first_measurement=False)
        assert change.delta is None


class TestAttemptProjection:
    def test_wrong_answer_emits_both_attempted_and_failed(self) -> None:
        rows = [_AttemptRow(attempt_id=uuid.uuid4(), is_correct=False, ingested_at=_at(2))]
        events = project_attempt_rows(_UID, rows)
        assert [e.event_type for e in events] == [
            TraceEventType.PROBLEM_ATTEMPTED,
            TraceEventType.ASSESSMENT_FAILED,
        ]

    def test_correct_answer_emits_only_attempted(self) -> None:
        rows = [_AttemptRow(attempt_id=uuid.uuid4(), is_correct=True, ingested_at=_at(2))]
        events = project_attempt_rows(_UID, rows)
        assert [e.event_type for e in events] == [TraceEventType.PROBLEM_ATTEMPTED]
        assert events[0].correct is True

    def test_ungraded_attempt_is_not_a_failure(self) -> None:
        """`is_correct=None`은 미채점이다 — falsy라고 실패로 접으면 없는 오답이 생긴다."""
        rows = [_AttemptRow(attempt_id=uuid.uuid4(), is_correct=None, ingested_at=_at(2))]
        events = project_attempt_rows(_UID, rows)
        assert [e.event_type for e in events] == [TraceEventType.PROBLEM_ATTEMPTED]
        assert events[0].correct is None

    def test_reported_start_time_wins_and_is_labelled_occurred(self) -> None:
        rows = [
            _AttemptRow(
                attempt_id=uuid.uuid4(), is_correct=True, started_at=_at(1), ingested_at=_at(5)
            )
        ]
        (event,) = project_attempt_rows(_UID, rows)
        assert event.occurred_at == _at(1)
        assert event.time_basis is TimeBasis.OCCURRED

    def test_missing_report_falls_back_to_ingest_and_says_so(self) -> None:
        rows = [_AttemptRow(attempt_id=uuid.uuid4(), is_correct=True, ingested_at=_at(5))]
        (event,) = project_attempt_rows(_UID, rows)
        assert event.occurred_at == _at(5)
        assert event.time_basis is TimeBasis.INGESTED

    def test_future_report_is_clamped_to_ingest(self) -> None:
        """발생이 수신보다 미래일 수 없다 — 클라 시계 왜곡은 수신 시각으로 접는다."""
        rows = [
            _AttemptRow(
                attempt_id=uuid.uuid4(), is_correct=True, started_at=_at(99), ingested_at=_at(5)
            )
        ]
        (event,) = project_attempt_rows(_UID, rows)
        assert event.occurred_at == _at(5)
        assert event.time_basis is TimeBasis.INGESTED

    def test_row_without_any_timestamp_is_skipped_loudly(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """시간 없는 행을 조용히 버리면 트레이스가 이유 없이 짧아진다."""
        aid = uuid.uuid4()
        rows = [_AttemptRow(attempt_id=aid, is_correct=False)]
        with caplog.at_level(logging.WARNING, logger="whymath.l2.learning_event_trace"):
            assert project_attempt_rows(_UID, rows) == []
        assert str(aid) in caplog.text
        assert "귀속 가능한 시각이 없음" in caplog.text

    def test_duration_is_converted_to_milliseconds(self) -> None:
        rows = [
            _AttemptRow(
                attempt_id=uuid.uuid4(), is_correct=True, duration_seconds=7, ingested_at=_at(1)
            )
        ]
        (event,) = project_attempt_rows(_UID, rows)
        assert event.response_time_ms == 7000

    def test_missing_duration_stays_none_not_zero(self) -> None:
        rows = [_AttemptRow(attempt_id=uuid.uuid4(), is_correct=True, ingested_at=_at(1))]
        (event,) = project_attempt_rows(_UID, rows)
        assert event.response_time_ms is None


class TestAttemptEventProjection:
    def test_produced_types_map_to_trace_vocabulary(self) -> None:
        rows = [
            _EventRow(event_type=EventType.힌트제공, event_at=_at(1), event_data={"hint_level": 2}),
            _EventRow(event_type=EventType.막힘, event_at=_at(2), event_data={"turn_count": 5}),
        ]
        events = project_attempt_event_rows(_UID, rows)
        assert [e.event_type for e in events] == [
            TraceEventType.HINT_PROVIDED,
            TraceEventType.STUCK_DETECTED,
        ]
        assert events[0].detail == {"hint_level": 2}
        assert events[1].detail == {"turn_count": 5}

    def test_dormant_type_is_skipped_loudly(self, caplog: pytest.LogCaptureFixture) -> None:
        """휴면 타입이 실제로 생산되기 시작하면 매핑을 늘려야 한다 — 침묵하면 아무도 모른다."""
        rows = [_EventRow(event_type=EventType.계산, event_at=_at(1))]
        with caplog.at_level(logging.WARNING, logger="whymath.l2.learning_event_trace"):
            assert project_attempt_event_rows(_UID, rows) == []
        assert "계산" in caplog.text

    def test_non_allowlisted_keys_are_dropped(self) -> None:
        rows = [
            _EventRow(
                event_type=EventType.힌트제공,
                event_at=_at(1),
                event_data={"hint_level": 3, "persona": "A_일반고고3"},
            )
        ]
        (event,) = project_attempt_event_rows(_UID, rows)
        assert event.detail == {"hint_level": 3}

    def test_nested_values_are_rejected_even_under_an_allowed_key(self) -> None:
        """키 이름만 막으면 계약 확장 시 같은 이름 아래 dict가 들어와 자유형이 되살아난다."""
        rows = [
            _EventRow(
                event_type=EventType.시각화조작,
                event_at=_at(1),
                event_data={"interaction": {"x": 12.5, "y": 30.1}},
            )
        ]
        (event,) = project_attempt_event_rows(_UID, rows)
        assert event.detail is None

    def test_visualization_payload_never_reaches_the_trace(self) -> None:
        rows = [
            _EventRow(
                event_type=EventType.시각화조작,
                event_at=_at(1),
                event_data={"interaction": "drag", "payload": {"x": 12.5, "y": 30.1}},
            )
        ]
        (event,) = project_attempt_event_rows(_UID, rows)
        assert event.detail == {"interaction": "drag"}

    def test_empty_detail_is_none_not_empty_dict(self) -> None:
        rows = [_EventRow(event_type=EventType.힌트요청, event_at=_at(1), event_data={})]
        (event,) = project_attempt_event_rows(_UID, rows)
        assert event.detail is None

    def test_reported_event_time_is_labelled_occurred(self) -> None:
        rows = [_EventRow(event_type=EventType.막힘, event_at=_at(9), event_time=_at(3))]
        (event,) = project_attempt_event_rows(_UID, rows)
        assert event.occurred_at == _at(3)
        assert event.time_basis is TimeBasis.OCCURRED


class TestOtherProjections:
    def test_assessment_emits_start_and_completion_separately(self) -> None:
        rows = [_AssessmentRow(started_at=_at(0), completed_at=_at(4))]
        events = project_assessment_rows(_UID, rows)
        assert [e.event_type for e in events] == [
            TraceEventType.DIAGNOSTIC_STARTED,
            TraceEventType.DIAGNOSTIC_COMPLETED,
        ]

    def test_incomplete_assessment_has_no_completion_event(self) -> None:
        rows = [_AssessmentRow(started_at=_at(0), completed_at=None)]
        events = project_assessment_rows(_UID, rows)
        assert [e.event_type for e in events] == [TraceEventType.DIAGNOSTIC_STARTED]

    def test_misconception_row_carries_the_id_and_evidence_count(self) -> None:
        rows = [_MisconceptionRow(misconception_id="M-042", created_at=_at(6), evidence_count=3)]
        (event,) = project_misconception_rows(_UID, rows)
        assert event.event_type is TraceEventType.MISCONCEPTION_DETECTED
        assert event.misconception_id == "M-042"
        assert event.detail is not None
        assert event.detail["evidence_count"] == 3

    def test_ability_row_carries_theta(self) -> None:
        rows = [_AbilityRow(measured_at=_at(7), theta=0.8, response_count=12)]
        (event,) = project_ability_rows(_UID, rows)
        assert event.event_type is TraceEventType.ABILITY_MEASURED
        assert event.detail == {"theta": 0.8, "response_count": 12}


class TestOrdering:
    def test_same_moment_rows_are_ordered_deterministically(self) -> None:
        """동시각 동률이 실행마다 뒤바뀌면 같은 트레이스가 매번 달라 보인다."""
        a = LearningEvent(
            event_type=TraceEventType.MASTERY_UPDATED,
            learner_id=_UID,
            occurred_at=_at(1),
            time_basis=TimeBasis.INGESTED,
            source=TraceSource.CONCEPT_MASTERY_HISTORY,
        )
        b = LearningEvent(
            event_type=TraceEventType.ASSESSMENT_FAILED,
            learner_id=_UID,
            occurred_at=_at(1),
            time_basis=TimeBasis.INGESTED,
            source=TraceSource.PROBLEM_ATTEMPT,
        )
        assert sort_entries([a, b]) == sort_entries([b, a])


# ──────────────────────────────────────────────────────────────────────────
# ④ PII 경계
# ──────────────────────────────────────────────────────────────────────────
class TestPrivacyBoundary:
    def test_envelope_has_no_slot_for_student_prose(self) -> None:
        """구조적 차단 — 답안 슬롯이 없으면 나중에 실수로 채울 여지 자체가 없다."""
        forbidden = {
            "answer",
            "answer_text",
            "student_answer",
            "solution",
            "solution_latex",
            "latex",
            "handwriting_uri",
            "ocr_result",
            "content",
            "message",
        }
        assert not (forbidden & set(LearningEvent.model_fields))

    def test_envelope_rejects_unknown_fields(self) -> None:
        with pytest.raises(Exception):  # noqa: B017 — pydantic ValidationError(버전 무관 형태)
            LearningEvent(
                event_type=TraceEventType.PROBLEM_ATTEMPTED,
                learner_id=_UID,
                occurred_at=_at(0),
                time_basis=TimeBasis.INGESTED,
                source=TraceSource.PROBLEM_ATTEMPT,
                student_answer="x=3",  # type: ignore[call-arg]
            )


# ──────────────────────────────────────────────────────────────────────────
# ⑤ build_trace — 조립·절단·가용성·침묵 실패 금지
# ──────────────────────────────────────────────────────────────────────────
class _Scalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)


class _QueueSession:
    """`execute()`가 호출 순서대로 미리 준 결과를 반환(`test_learner_state.py` 관례).

    `build_trace`의 질의 순서: ①assessment ②problem_attempt ③attempt_event
    ④concept_mastery ⑤skill_mastery ⑥misconception ⑦ability_snapshot
    ⑧learning_session ⑨evidence_event 추천(세션 조인 — EOS-131).
    `fail_at`(1-based)을 주면 그 순번의 질의가 예외를 던진다(실패 주입).
    """

    def __init__(self, queue: list[list[Any]], *, fail_at: int | None = None) -> None:
        self._queue = queue
        self._fail_at = fail_at
        self.calls = 0

    async def execute(self, _stmt: Any) -> _Result:
        self.calls += 1
        if self._fail_at is not None and self.calls == self._fail_at:
            raise RuntimeError("주입된 원천 질의 실패")
        return _Result(self._queue[self.calls - 1] if self.calls <= len(self._queue) else [])


def _mastery_view(
    measured_at: datetime,
    mastery: float,
    before: float | None,
    axis: Any,
) -> Any:
    """`_mastery_stmt` 결과 행(`axis_id` 라벨) 모양."""

    @dataclass
    class _Row:
        axis_id: Any
        measured_at: datetime
        mastery: float | None
        confidence: float | None
        sample_size: int | None
        mastery_before: float | None

    return _Row(axis, measured_at, mastery, None, None, before)


_CONCEPT = uuid.uuid4()


@dataclass
class _SessionRow:
    session_id: uuid.UUID
    started_at: datetime | None
    target_concept_id: uuid.UUID | None


@dataclass
class _RecommendationRow:
    time: datetime
    session_id: uuid.UUID
    meta: dict[str, Any] | None


class TestSessionAndRecommendationProjection:
    """EOS-131 — 세션 개시·추천 처치 투영의 의미."""

    def test_session_start_without_time_is_skipped_not_invented(self) -> None:
        rows = [
            _SessionRow(session_id=uuid.uuid4(), started_at=None, target_concept_id=None),
            _SessionRow(session_id=uuid.uuid4(), started_at=_at(2), target_concept_id=_CONCEPT),
        ]
        (event,) = project_session_rows(_UID, rows)
        assert event.event_type is TraceEventType.CONCEPT_SELECTED
        assert event.concept_id == _CONCEPT
        assert event.time_basis is TimeBasis.INGESTED

    def test_malformed_problem_id_is_none_not_fabricated(self) -> None:
        rows = [_RecommendationRow(time=_at(3), session_id=uuid.uuid4(), meta={"problem_id": "x"})]
        (event,) = project_recommendation_rows(_UID, rows)
        assert event.problem_id is None
        assert event.detail is None


def _full_queue() -> list[list[Any]]:
    """계획서 §17 시나리오 한 세트 — 진단부터 오개념·숙달 하락까지."""
    return [
        [_AssessmentRow(started_at=_at(0), completed_at=_at(4))],
        [
            _AttemptRow(
                attempt_id=uuid.uuid4(),
                problem_id=uuid.uuid4(),
                is_correct=False,
                started_at=_at(10),
                ingested_at=_at(10),
                duration_seconds=95,
            )
        ],
        [_EventRow(event_type=EventType.막힘, event_at=_at(8), event_data={"turn_count": 5})],
        [_mastery_view(_at(12), 0.43, 0.54, _CONCEPT)],
        [],
        [_MisconceptionRow(misconception_id="M-087", created_at=_at(11))],
        [],
    ]


class TestBuildTrace:
    async def test_reconstructs_the_session_in_chronological_order(self) -> None:
        session = _QueueSession(_full_queue())
        trace = await build_trace(cast(AsyncSession, session), learner_id=_UID)
        assert [e.event_type.value for e in trace.entries] == [
            "diagnostic_started",
            "diagnostic_completed",
            "stuck_detected",
            "problem_attempted",
            "assessment_failed",
            "misconception_detected",
            "mastery_updated",
        ]
        moments = [e.occurred_at for e in trace.entries]
        assert moments == sorted(moments)

    async def test_mastery_entry_carries_the_before_after_pair(self) -> None:
        session = _QueueSession(_full_queue())
        trace = await build_trace(cast(AsyncSession, session), learner_id=_UID)
        (mastery,) = [e for e in trace.entries if e.event_type is TraceEventType.MASTERY_UPDATED]
        assert mastery.mastery_change is not None
        assert mastery.mastery_change.mastery_before == pytest.approx(0.54)
        assert mastery.mastery_change.mastery_after == pytest.approx(0.43)

    async def test_coverage_counts_only_what_this_query_produced(self) -> None:
        session = _QueueSession(_full_queue())
        trace = await build_trace(cast(AsyncSession, session), learner_id=_UID)
        counts = {c.event_type: c.count for c in trace.coverage}
        assert counts[TraceEventType.MASTERY_UPDATED] == 1
        assert counts[TraceEventType.ASSESSMENT_FAILED] == 1
        assert counts[TraceEventType.HINT_PROVIDED] == 0

    async def test_unmeasured_sources_are_reported_apart_from_empty_ones(self) -> None:
        """미생산·미결합의 0건이 '이 학생은 안 했다'와 같은 글자로 보이면 안 된다."""
        session = _QueueSession(_full_queue())
        trace = await build_trace(cast(AsyncSession, session), learner_id=_UID)
        unmeasured = {c.event_type: c.availability for c in trace.unmeasured_sources}
        assert unmeasured[TraceEventType.LEARNER_STATE_CREATED] is SourceAvailability.DORMANT
        assert unmeasured[TraceEventType.CONTENT_VIEWED] is SourceAvailability.DORMANT
        # EOS-131: 세션·추천은 이제 생산 중이다 — 미측정 목록에 있으면 실재 활동이 은폐된다.
        assert TraceEventType.CONCEPT_SELECTED not in unmeasured
        assert TraceEventType.RECOMMENDATION_GENERATED not in unmeasured
        # 생산 중인 축은 이 목록에 없어야 한다 — 있으면 실재 데이터가 '미측정'으로 은폐된다.
        assert TraceEventType.PROBLEM_ATTEMPTED not in unmeasured
        assert TraceEventType.MASTERY_UPDATED not in unmeasured

    async def test_session_and_recommendation_rows_are_projected(self) -> None:
        """EOS-131 ⑥: ⑧세션 ⑨추천 질의 결과가 시간선·coverage 건수에 실린다."""
        sid = uuid.uuid4()
        pid = uuid.uuid4()
        queue = _full_queue() + [
            [_SessionRow(session_id=sid, started_at=_at(1), target_concept_id=None)],
            [
                _RecommendationRow(
                    time=_at(13),
                    session_id=sid,
                    meta={
                        "problem_id": str(pid),
                        "policy_version": "cat_v1",
                        "candidates": [{"problem_id": str(pid), "score": 1.0}],
                    },
                )
            ],
        ]
        trace = await build_trace(cast(AsyncSession, _QueueSession(queue)), learner_id=_UID)
        counts = {c.event_type: c.count for c in trace.coverage}
        assert counts[TraceEventType.CONCEPT_SELECTED] == 1
        assert counts[TraceEventType.RECOMMENDATION_GENERATED] == 1
        (rec,) = [
            e for e in trace.entries if e.event_type is TraceEventType.RECOMMENDATION_GENERATED
        ]
        assert rec.session_id == sid and rec.problem_id == pid
        # 후보 목록(리스트)은 싣지 않는다 — 비식별 스칼라만.
        assert rec.detail == {"policy_version": "cat_v1"}
        assert trace.entries[-1].event_type is TraceEventType.RECOMMENDATION_GENERATED

    async def test_truncation_is_disclosed_and_keeps_the_recent_end(self) -> None:
        session = _QueueSession(_full_queue())
        trace = await build_trace(cast(AsyncSession, session), learner_id=_UID, limit=2)
        assert trace.truncated is True
        assert len(trace.entries) == 2
        assert trace.entries[-1].event_type is TraceEventType.MASTERY_UPDATED

    async def test_untruncated_result_says_so(self) -> None:
        session = _QueueSession(_full_queue())
        trace = await build_trace(cast(AsyncSession, session), learner_id=_UID, limit=50)
        assert trace.truncated is False

    @pytest.mark.parametrize("limit", [0, -1, MAX_TRACE_LIMIT + 1])
    async def test_out_of_range_limit_is_rejected(self, limit: int) -> None:
        session = _QueueSession(_full_queue())
        with pytest.raises(ValueError, match="limit"):
            await build_trace(cast(AsyncSession, session), learner_id=_UID, limit=limit)

    async def test_empty_learner_returns_empty_entries_with_full_coverage(self) -> None:
        session = _QueueSession([[] for _ in range(9)])
        trace = await build_trace(cast(AsyncSession, session), learner_id=_UID)
        assert trace.entries == ()
        assert len(trace.coverage) == len(TraceEventType)

    # EOS-131: ⑧learning_session ⑨추천 조인 질의가 더해져 9개 — 새 두 질의의 실패도 삼키지 않는다.
    @pytest.mark.parametrize("failing_query", range(1, 10))
    async def test_source_failure_is_never_swallowed(self, failing_query: int) -> None:
        """주입 검증 — 어느 원천 질의가 깨져도 조용한 부분 결과가 나오지 않는다.

        읽기 축에는 적재 경로 같은 "삼켜도 데이터가 안 죽는다"는 근거가 없다. 한 원천이 조용히
        빠지면 그 학생이 그 행동을 *안 한 것처럼* 보이므로, 실패는 반드시 관측 가능해야 한다.
        """
        session = _QueueSession(_full_queue(), fail_at=failing_query)
        with pytest.raises(RuntimeError, match="주입된 원천 질의 실패"):
            await build_trace(cast(AsyncSession, session), learner_id=_UID)

    async def test_the_failure_injection_actually_reaches_the_query(self) -> None:
        """주입 자체의 실재 — 주입 없이 같은 입력이 성공해야 위 테스트가 의미를 갖는다."""
        session = _QueueSession(_full_queue())
        trace = await build_trace(cast(AsyncSession, session), learner_id=_UID)
        assert session.calls == 9
        assert trace.entries


class TestRender:
    async def test_mastery_line_shows_the_arrow_form(self) -> None:
        session = _QueueSession(_full_queue())
        trace = await build_trace(cast(AsyncSession, session), learner_id=_UID)
        lines = render_trace_lines(trace)
        assert any("mastery_updated(0.54→0.43)" in line for line in lines)

    async def test_unmeasured_sources_are_rendered_too(self) -> None:
        session = _QueueSession(_full_queue())
        trace = await build_trace(cast(AsyncSession, session), learner_id=_UID)
        lines = render_trace_lines(trace)
        assert any("[dormant] content_viewed" in line for line in lines)
        assert any("[dormant] learner_state_created" in line for line in lines)
        # EOS-131: 추천은 이제 생산 중이라 미측정 목록에 렌더되지 않는다(종전 [unjoinable]의 반대).
        assert not any("recommendation_generated —" in line for line in lines)

    async def test_truncation_notice_is_rendered(self) -> None:
        session = _QueueSession(_full_queue())
        trace = await build_trace(cast(AsyncSession, session), learner_id=_UID, limit=2)
        lines = render_trace_lines(trace)
        assert any("잘렸습니다" in line for line in lines)

    async def test_first_measurement_renders_as_unmeasured_not_zero(self) -> None:
        queue: list[list[Any]] = [[] for _ in range(7)]
        queue[3] = [_mastery_view(_at(1), 0.6, None, _CONCEPT)]
        session = _QueueSession(queue)
        trace = await build_trace(cast(AsyncSession, session), learner_id=_UID)
        lines = render_trace_lines(trace)
        assert any("mastery_updated(미측정→0.60)" in line for line in lines)


class TestCausalTieOrder:
    """동시각 동률의 순서가 인과를 뒤집지 않는지 — §17 흐름의 최소 보장."""

    def test_tie_order_covers_every_trace_event_type(self) -> None:
        """빠진 타입이 있으면 정렬이 KeyError로 죽는다(조용한 누락보다 낫지만 CI가 먼저 잡는다)."""
        assert set(_TIE_ORDER) == set(TraceEventType)

    def test_tie_order_ranks_are_unique(self) -> None:
        assert len(set(_TIE_ORDER.values())) == len(_TIE_ORDER)

    def test_attempt_precedes_its_own_grading_at_the_same_instant(self) -> None:
        """사전순이면 `assessment_failed`가 앞선다 — 결과가 원인보다 먼저 보이는 시간선."""
        rows = [_AttemptRow(attempt_id=uuid.uuid4(), is_correct=False, ingested_at=_at(3))]
        events = sort_entries(project_attempt_rows(_UID, rows))
        assert [e.event_type for e in events] == [
            TraceEventType.PROBLEM_ATTEMPTED,
            TraceEventType.ASSESSMENT_FAILED,
        ]
        assert events[0].occurred_at == events[1].occurred_at
