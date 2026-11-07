"""개념 생애 상태 — 어휘·전환표·학생 공개 술어·전환 함수 단위 테스트 (PED-17 A1, 실 DB 불필요).

검증 축(완료 기준 1 · 거부):
  ① 어휘는 4개로 고정이고 허용 전환은 정확히 5쌍이다.
  ② 전환 함수는 16쌍 × 모든 경로를 전수로 시험해 **허용표에 있는 (쌍, 경로)만** 통과시킨다.
  ③ 거부는 DB에 아무것도 쓰기 전에 일어나고, 오류 로그와 예외를 남긴다.
  ④ 학생 공개 술어는 '공개됨'이 아니면 어떤 조합에서도 False다(진리표 전수).

DB 수준 보증(트리거·추가 전용·백필)은 `tests/backend/db/test_concept_lifecycle_migration_integration.py`.
"""

from __future__ import annotations

import itertools
import logging
from typing import Any

import pytest

from whymath_backend.l1.concept_content.lifecycle import (
    ConceptNotFoundError,
    InvalidConceptTransitionError,
    is_student_visible,
    transition_concept_state,
)
from whymath_backend.schema.concept_lifecycle import (
    ALLOWED_TRANSITIONS,
    KIKI_ONLY_VIA,
    ChangedByKind,
    ConceptContentOrigin,
    ConceptLifecycleState,
    ConceptTransitionVia,
)

_S = ConceptLifecycleState
_V = ConceptTransitionVia
_ALL_STATES = list(ConceptLifecycleState)
_ALL_VIAS = list(ConceptTransitionVia)


# ── 테스트 대역 ────────────────────────────────────────────────────────────────────────


class _Result:
    def __init__(self, scalar: Any = None) -> None:
        self._scalar = scalar

    def scalar_one_or_none(self) -> Any:
        return self._scalar


class _FakeSession:
    """전환 함수가 쓰는 표면만 대역: select(현재 상태) · update(상태 변경) · add · flush."""

    def __init__(self, current: str | None, *, update_rowcount: int = 1) -> None:
        self.current = current
        self.update_rowcount = update_rowcount
        self.updates = 0
        self.added: list[Any] = []
        self.flushes = 0

    async def execute(self, stmt: Any) -> _Result:
        if type(stmt).__name__ == "Update":
            self.updates += 1
            # UPDATE ... RETURNING code — 1행 적용이면 code를, 0행이면 아무것도 돌려주지 않는다.
            return _Result(scalar="HIGH-A1-001" if self.update_rowcount == 1 else None)
        return _Result(scalar=self.current)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushes += 1


def _kind_for(via: ConceptTransitionVia) -> ChangedByKind:
    """경로에 맞는 주체 — 긴급 정지만 kiki, 나머지는 에이전트(권한 규칙을 쌍·경로 검사와 분리한다)."""
    return ChangedByKind.KIKI if via in KIKI_ONLY_VIA else ChangedByKind.AGENT


async def _try(
    current: str | None,
    to_state: ConceptLifecycleState,
    via: ConceptTransitionVia,
    *,
    kind: ChangedByKind | None = None,
    name: str = "테스트 에이전트",
    reason: str = "테스트 사유",
) -> tuple[_FakeSession, Any]:
    session = _FakeSession(current)
    record = await transition_concept_state(
        session,  # type: ignore[arg-type]
        concept_code="HIGH-A1-001",
        to_state=to_state,
        via=via,
        changed_by_kind=kind or _kind_for(via),
        changed_by_name=name,
        reason=reason,
    )
    return session, record


# ── ① 어휘와 전환표 ────────────────────────────────────────────────────────────────────


class TestVocabulary:
    def test_state_values_are_exactly_the_four_fixed_words(self) -> None:
        assert [s.value for s in ConceptLifecycleState] == ["초안", "검증됨", "공개됨", "회수됨"]

    def test_origin_values_are_exactly_the_two_fixed_words(self) -> None:
        assert [o.value for o in ConceptContentOrigin] == ["사람 검수", "AI 생성"]

    def test_exactly_five_allowed_pairs(self) -> None:
        assert set(ALLOWED_TRANSITIONS) == {
            (_S.DRAFT, _S.VERIFIED),
            (_S.VERIFIED, _S.PUBLISHED),
            (_S.PUBLISHED, _S.WITHDRAWN),
            (_S.VERIFIED, _S.WITHDRAWN),
            (_S.WITHDRAWN, _S.DRAFT),
        }

    def test_allowed_vias_match_the_instruction_per_pair(self) -> None:
        assert ALLOWED_TRANSITIONS[(_S.DRAFT, _S.VERIFIED)] == {_V.B6_PUBLIC_GATE}
        assert ALLOWED_TRANSITIONS[(_S.VERIFIED, _S.PUBLISHED)] == {
            _V.D4_AI_CANARY,
            _V.D5_STAGED_ROLLOUT,
        }
        assert ALLOWED_TRANSITIONS[(_S.PUBLISHED, _S.WITHDRAWN)] == {
            _V.KILL_SWITCH,
            _V.RECALL,
            _V.EMERGENCY_STOP,
        }
        assert ALLOWED_TRANSITIONS[(_S.VERIFIED, _S.WITHDRAWN)] == {
            _V.D2_AI_AUDIT,
            _V.D4_AI_CANARY,
            _V.D6,
        }
        assert ALLOWED_TRANSITIONS[(_S.WITHDRAWN, _S.DRAFT)] == {_V.REGENERATE}

    def test_initial_assignment_is_never_a_valid_transition_path(self) -> None:
        # '최초 부여'는 마이그레이션 백필 전용이다 — 어느 전환에도 쓸 수 없다.
        assert all(_V.INITIAL_ASSIGNMENT not in vias for vias in ALLOWED_TRANSITIONS.values())

    def test_no_shortcut_from_draft_to_published(self) -> None:
        # 공개 순서를 건너뛰는 지름길(초안→공개됨)은 표에 없다 — B6→D4/D5를 거쳐야 한다.
        assert (_S.DRAFT, _S.PUBLISHED) not in ALLOWED_TRANSITIONS


# ── ② 전환 함수: 16쌍 × 모든 경로 전수 ───────────────────────────────────────────────────

_MATRIX = [
    (frm, to, via) for frm, to, via in itertools.product(_ALL_STATES, _ALL_STATES, _ALL_VIAS)
]


@pytest.mark.parametrize(
    ("frm", "to", "via"),
    _MATRIX,
    ids=[f"{f.name}->{t.name}|{v.name}" for f, t, v in _MATRIX],
)
async def test_transition_allowed_iff_pair_and_via_are_in_the_table(
    frm: ConceptLifecycleState,
    to: ConceptLifecycleState,
    via: ConceptTransitionVia,
    caplog: pytest.LogCaptureFixture,
) -> None:
    expected_allowed = via in ALLOWED_TRANSITIONS.get((frm, to), frozenset())
    caplog.set_level(logging.ERROR, logger="whymath.l1.concept_content.lifecycle")

    if expected_allowed:
        session, record = await _try(frm.value, to, via)
        assert (record.from_state, record.to_state, record.via) == (frm.value, to.value, via.value)
        assert session.updates == 1
        assert len(session.added) == 1
        assert session.added[0] is record
        assert not caplog.records  # 허용 전환은 오류 로그를 남기지 않는다.
    else:
        session = _FakeSession(frm.value)
        with pytest.raises(InvalidConceptTransitionError):
            await transition_concept_state(
                session,  # type: ignore[arg-type]
                concept_code="HIGH-A1-001",
                to_state=to,
                via=via,
                changed_by_kind=_kind_for(via),
                changed_by_name="테스트 에이전트",
                reason="테스트 사유",
            )
        # 거부는 쓰기 전이다 — 상태 변경도, 기록 행도 없다.
        assert session.updates == 0
        assert session.added == []
        assert session.flushes == 0
        # 오류를 남긴다(지시: "거부하고 오류를 남긴다").
        assert any(r.levelno == logging.ERROR for r in caplog.records)


class TestEveryAllowedTransitionWritesExactlyOneRecord:
    """완료 기준 3 (함수 수준): 상태를 바꾸면 기록이 정확히 1건 남는다."""

    @pytest.mark.parametrize(
        ("frm", "to", "via"),
        [(f, t, v) for (f, t), vias in ALLOWED_TRANSITIONS.items() for v in sorted(vias)],
        ids=lambda x: getattr(x, "name", str(x)),
    )
    async def test_one_update_one_record(
        self, frm: ConceptLifecycleState, to: ConceptLifecycleState, via: ConceptTransitionVia
    ) -> None:
        session, record = await _try(
            frm.value, to, via, name="B6 공개 관문", reason="자동 검증 통과"
        )
        assert session.updates == 1
        assert len(session.added) == 1
        assert session.flushes == 1
        assert record.changed_by_name == "B6 공개 관문"
        assert record.reason == "자동 검증 통과"


# ── ③ 권한·입력 거부 ───────────────────────────────────────────────────────────────────


class TestEmergencyStopIsKikiOnly:
    @pytest.mark.parametrize("kind", [ChangedByKind.AGENT, ChangedByKind.RULE])
    async def test_non_kiki_cannot_use_emergency_stop(self, kind: ChangedByKind) -> None:
        session = _FakeSession(_S.PUBLISHED.value)
        with pytest.raises(InvalidConceptTransitionError, match="Kiki"):
            await transition_concept_state(
                session,  # type: ignore[arg-type]
                concept_code="HIGH-A1-001",
                to_state=_S.WITHDRAWN,
                via=_V.EMERGENCY_STOP,
                changed_by_kind=kind,
                changed_by_name="릴리스 에이전트",
                reason="긴급 정지 시도",
            )
        assert session.updates == 0
        assert session.added == []

    async def test_kiki_can_use_emergency_stop(self) -> None:
        # 대조군 — 위 거부가 "긴급 정지 전체 차단"이 아니라 주체 검사 때문임을 보인다.
        session, record = await _try(
            _S.PUBLISHED.value,
            _S.WITHDRAWN,
            _V.EMERGENCY_STOP,
            kind=ChangedByKind.KIKI,
            name="Kiki",
            reason="심각 오류 신고 확인",
        )
        assert record.changed_by_kind == "kiki"
        assert session.updates == 1

    async def test_agent_uses_kill_switch_not_emergency_stop(self) -> None:
        # 심각 오류 신고 1건의 자동 회수는 킬스위치 경로다 — 에이전트가 쓸 수 있어야 한다.
        _session, record = await _try(_S.PUBLISHED.value, _S.WITHDRAWN, _V.KILL_SWITCH)
        assert record.via == "킬스위치"


class TestInputRejection:
    @pytest.mark.parametrize("reason", ["", "   ", "\n\t"])
    async def test_blank_reason_is_rejected_before_any_db_access(self, reason: str) -> None:
        session = _FakeSession(_S.DRAFT.value)
        with pytest.raises(InvalidConceptTransitionError, match="사유"):
            await transition_concept_state(
                session,  # type: ignore[arg-type]
                concept_code="HIGH-A1-001",
                to_state=_S.VERIFIED,
                via=_V.B6_PUBLIC_GATE,
                changed_by_kind=ChangedByKind.AGENT,
                changed_by_name="B6",
                reason=reason,
            )
        assert session.updates == 0
        assert session.added == []

    @pytest.mark.parametrize("name", ["", "  "])
    async def test_blank_actor_name_is_rejected(self, name: str) -> None:
        session = _FakeSession(_S.DRAFT.value)
        with pytest.raises(InvalidConceptTransitionError, match="주체"):
            await transition_concept_state(
                session,  # type: ignore[arg-type]
                concept_code="HIGH-A1-001",
                to_state=_S.VERIFIED,
                via=_V.B6_PUBLIC_GATE,
                changed_by_kind=ChangedByKind.AGENT,
                changed_by_name=name,
                reason="사유",
            )
        assert session.added == []

    async def test_missing_concept_row_is_refused_not_silently_recorded(self) -> None:
        session = _FakeSession(None)
        with pytest.raises(ConceptNotFoundError):
            await transition_concept_state(
                session,  # type: ignore[arg-type]
                concept_code="NOPE",
                to_state=_S.VERIFIED,
                via=_V.B6_PUBLIC_GATE,
                changed_by_kind=ChangedByKind.AGENT,
                changed_by_name="B6",
                reason="사유",
            )
        assert session.added == []  # 없는 행의 기록을 남기지 않는다.

    async def test_out_of_vocabulary_current_state_is_refused(self) -> None:
        # DB CHECK가 막으므로 정상 경로에선 오지 않지만, 오면 조용히 통과시키지 않는다.
        session = _FakeSession("Published")
        with pytest.raises(InvalidConceptTransitionError, match="어휘 밖"):
            await transition_concept_state(
                session,  # type: ignore[arg-type]
                concept_code="HIGH-A1-001",
                to_state=_S.WITHDRAWN,
                via=_V.RECALL,
                changed_by_kind=ChangedByKind.AGENT,
                changed_by_name="회수",
                reason="사유",
            )
        assert session.updates == 0

    async def test_update_not_applied_to_exactly_one_row_fails_loudly(self) -> None:
        from whymath_backend.l1.concept_content.lifecycle import ConceptTransitionError

        session = _FakeSession(_S.DRAFT.value, update_rowcount=0)
        with pytest.raises(ConceptTransitionError, match="대상 0행"):
            await transition_concept_state(
                session,  # type: ignore[arg-type]
                concept_code="HIGH-A1-001",
                to_state=_S.VERIFIED,
                via=_V.B6_PUBLIC_GATE,
                changed_by_kind=ChangedByKind.AGENT,
                changed_by_name="B6",
                reason="사유",
            )
        assert session.added == []  # 상태가 안 바뀌었으면 기록도 남기지 않는다.

    async def test_same_state_is_not_a_transition(self) -> None:
        for state in _ALL_STATES:
            session = _FakeSession(state.value)
            with pytest.raises(InvalidConceptTransitionError):
                await transition_concept_state(
                    session,  # type: ignore[arg-type]
                    concept_code="HIGH-A1-001",
                    to_state=state,
                    via=_V.RECALL,
                    changed_by_kind=ChangedByKind.AGENT,
                    changed_by_name="회수",
                    reason="사유",
                )

    async def test_rejection_log_has_no_student_identifier_fields(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.ERROR, logger="whymath.l1.concept_content.lifecycle")
        session = _FakeSession(_S.DRAFT.value)
        with pytest.raises(InvalidConceptTransitionError):
            await transition_concept_state(
                session,  # type: ignore[arg-type]
                concept_code="HIGH-A1-001",
                to_state=_S.PUBLISHED,
                via=_V.D5_STAGED_ROLLOUT,
                changed_by_kind=ChangedByKind.AGENT,
                changed_by_name="릴리스 에이전트",
                reason="사유",
            )
        text = " ".join(r.getMessage() for r in caplog.records)
        assert "HIGH-A1-001" in text
        assert "초안" in text
        assert "공개됨" in text


# ── ④ 학생 공개 술어 진리표 ──────────────────────────────────────────────────────────────

_LIFECYCLES = [*(s.value for s in ConceptLifecycleState), None, "Published", "공개", " 공개됨"]
_ORIGINS = [*(o.value for o in ConceptContentOrigin), None, "human", ""]
_REVIEWS = ["ai_estimated", "reviewed", "rejected", None, "Reviewed", " reviewed"]


def _expected_visible(lifecycle: str | None, origin: str | None, review: str | None) -> bool:
    """술어의 독립 재서술 — 규칙을 별도 형태로 다시 적어 구현과 대조한다."""
    if lifecycle != "공개됨":
        return False
    if origin == "사람 검수":
        return review == "reviewed"
    if origin == "AI 생성":
        return review != "rejected"
    return False


@pytest.mark.parametrize(
    ("lifecycle", "origin", "review"),
    list(itertools.product(_LIFECYCLES, _ORIGINS, _REVIEWS)),
)
def test_student_visible_truth_table(
    lifecycle: str | None, origin: str | None, review: str | None
) -> None:
    got = is_student_visible(
        lifecycle_status=lifecycle, content_origin=origin, review_status=review
    )
    assert got is _expected_visible(lifecycle, origin, review)


class TestStudentVisibleDiscriminativePower:
    """같은 행에서 한 축만 바꿔 결과가 뒤집히는지 — 통과만 보이는 가드는 보호가 아니다."""

    def test_only_published_opens_regardless_of_review_label(self) -> None:
        for lifecycle in (_S.DRAFT, _S.VERIFIED, _S.WITHDRAWN):
            for origin in ConceptContentOrigin:
                assert not is_student_visible(
                    lifecycle_status=lifecycle.value,
                    content_origin=origin.value,
                    review_status="reviewed",
                ), (lifecycle, origin)

    def test_published_ai_generated_opens_without_human_review(self) -> None:
        # C안의 핵심: 사람 검수 없이도(ai_estimated) 자동 검증을 통과해 공개됨이면 열린다.
        assert is_student_visible(
            lifecycle_status="공개됨", content_origin="AI 생성", review_status="ai_estimated"
        )

    def test_human_reviewed_row_closes_when_review_label_is_demoted(self) -> None:
        # CONT-05 ③ 보존: 코퍼스 재적재가 review_status를 되돌리면 생애가 공개됨이어도 즉시 닫힌다.
        assert is_student_visible(
            lifecycle_status="공개됨", content_origin="사람 검수", review_status="reviewed"
        )
        assert not is_student_visible(
            lifecycle_status="공개됨", content_origin="사람 검수", review_status="ai_estimated"
        )

    def test_human_rejection_beats_ai_published(self) -> None:
        assert not is_student_visible(
            lifecycle_status="공개됨", content_origin="AI 생성", review_status="rejected"
        )

    def test_unflushed_orm_row_with_none_columns_is_closed(self) -> None:
        # flush 전 ORM 객체는 server_default 컬럼이 None이다 — 모르면 닫는다.
        assert not is_student_visible(
            lifecycle_status=None, content_origin=None, review_status="reviewed"
        )
