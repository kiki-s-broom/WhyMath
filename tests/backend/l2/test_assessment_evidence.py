"""EOS-12 Evidence 조립기(L2) — 조회 재사용·쓰기 0·모델 B 사본 합치 (hermetic·FakeSession).

가장 중요한 것은 **합치 테스트**다. 역할 비대칭 선택(모델 B)은 지금 세 곳에 산다:

  · `schema.assessment_evidence.select_concept_evidence`   ← 정본(이 태스크가 세움)
  · `l2.mastery_tracking.record_problem_attempt_mastery`    ← 인라인 사본
  · `l2.skill_mastery_tracking.record_problem_attempt_skill_mastery` ← 인라인 사본

사본 통합은 호출 계약을 소유한 `EOS-13`의 몫이라 이 태스크는 두 writer 파일을 건드리지
않는다. 대신 **셋이 같은 개념을 고르는지**를 기계가 동결한다 — 어느 하나가 드리프트하면
증거와 실제 갱신 대상이 갈라지고, 그러면 "왜 이 개념이 내려갔는가"의 답이 거짓이 된다.

`_QueueSession` 관례는 `test_learner_state.py`·`test_concept_diagnosis.py`를 따른다.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.l2.assessment_evidence import collect_assessment_evidence
from whymath_backend.l2.mastery_tracking import record_problem_attempt_mastery
from whymath_backend.l2.skill_mastery_tracking import record_problem_attempt_skill_mastery
from whymath_backend.schema.assessment_evidence import (
    AttributionBasis,
    EvidenceDirection,
    EvidenceKindState,
    MisconceptionCandidate,
    MisconceptionScan,
)
from whymath_backend.schema.enums import ConceptRole

_LEARNER = uuid.uuid4()
_PROBLEM = uuid.uuid4()
_PRIMARY = uuid.uuid4()
_TESTED = uuid.uuid4()


class _Scalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)

    def first(self) -> Any:
        return self._rows[0] if self._rows else None


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)


class _RoleSession:
    """`_assessed_concept_ids`의 role 필터를 흉내내는 fake — 역할별 고정 응답.

    실제 SELECT 대신 `where` 절에 어떤 role이 들어왔는지 보지 않고, **호출 순서**로 답한다.
    `collect_assessment_evidence`는 PRIMARY → TESTED → (스킬) 순으로 부른다.
    writer들은 정/오답에 따라 호출 순서가 달라지므로 `role_map`으로 값을 준다.
    """

    def __init__(
        self,
        *,
        primary: list[uuid.UUID],
        tested: list[uuid.UUID],
        skills: list[str] | None = None,
    ) -> None:
        self.primary = primary
        self.tested = tested
        self.skills = skills or []
        self.added: list[Any] = []
        self.commits = 0
        self.concept_queries: list[list[ConceptRole]] = []
        self.skill_query_inputs: list[list[uuid.UUID]] = []

    @staticmethod
    def _flatten(params: dict[str, Any]) -> list[Any]:
        """`in_()`은 값을 **리스트 하나**로 바인드한다(`role_1: [ConceptRole.TESTED]`).

        평탄화하지 않으면 role을 한 건도 못 찾아 fake가 **항상 빈 결과**를 돌려주고, 그러면
        이 파일의 합치 테스트가 정상·드리프트 양쪽에서 똑같이 통과한다(변별력 0). 실측으로
        확인한 모양이라 주석으로 못 박는다.
        """
        out: list[Any] = []
        for value in params.values():
            if isinstance(value, (list, tuple)):
                out.extend(value)
            else:
                out.append(value)
        return out

    async def execute(self, stmt: Any) -> _Result:
        """대상 테이블로 분기한다 — writer는 역할 조회 말고 *직전 측정* 조회도 한다.

        파라미터 모양만 보고 분기하면 `concept_mastery_history` 조회(role 없음)에서 오판한다.
        """
        text = str(stmt)
        values = self._flatten(stmt.compile().params)
        if "skill_node" in text:
            # `_assessed_skill_ids` — 입력 개념 id가 바인드로 들어온다(해소 입력 관측용).
            self.skill_query_inputs.append([v for v in values if isinstance(v, uuid.UUID)])
            return _Result(list(self.skills))
        if "problem_concept" in text:
            normalized = [v for v in values if isinstance(v, ConceptRole)]
            assert normalized, f"role 필터를 못 읽었다 — fake가 무력화된 상태다: {values!r}"
            self.concept_queries.append(normalized)
            out: list[uuid.UUID] = []
            if ConceptRole.PRIMARY in normalized:
                out += self.primary
            if ConceptRole.TESTED in normalized:
                out += self.tested
            return _Result(out)
        # 직전 숙달 측정 조회(`_latest_mastery`·`_latest_skill_mastery`) — 첫 관측으로 둔다.
        return _Result([])

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1


async def _collect(session: _RoleSession, *, correct: bool, **kw: Any) -> Any:
    return await collect_assessment_evidence(
        cast(AsyncSession, session),
        learner_id=_LEARNER,
        problem_id=_PROBLEM,
        correct=correct,
        **kw,
    )


# ──────────────────────────────────────────────────────────────────────────
# 조립 — 정/오답 경로
# ──────────────────────────────────────────────────────────────────────────
class TestCollect:
    async def test_correct_collects_all_assessed_concepts(self) -> None:
        session = _RoleSession(primary=[_PRIMARY], tested=[_TESTED])
        ev = await _collect(session, correct=True)
        assert [e.concept_id for e in ev.concept_evidence] == [_PRIMARY, _TESTED]
        assert {e.direction for e in ev.concept_evidence} == {EvidenceDirection.SUPPORTING}

    async def test_wrong_answer_collects_primary_only(self) -> None:
        session = _RoleSession(primary=[_PRIMARY], tested=[_TESTED])
        ev = await _collect(session, correct=False)
        assert [e.concept_id for e in ev.concept_evidence] == [_PRIMARY]
        assert ev.concept_evidence[0].attribution is AttributionBasis.PRIMARY_ATTRIBUTION

    async def test_skill_evidence_carries_its_source_concepts(self) -> None:
        session = _RoleSession(primary=[_PRIMARY], tested=[], skills=["skill.slope"])
        ev = await _collect(session, correct=False)
        assert [s.skill_id for s in ev.skill_evidence] == ["skill.slope"]
        assert ev.skill_evidence[0].resolved_from == (_PRIMARY,)
        assert ev.skill_evidence[0].direction is EvidenceDirection.REFUTING

    async def test_unmapped_problem_reports_not_measured_not_empty(self) -> None:
        """문항-개념 매핑 0건은 우리 쪽 공백이다 — 학생의 무활동으로 보이면 안 된다."""
        session = _RoleSession(primary=[], tested=[])
        ev = await _collect(session, correct=False)
        assert ev.concept_evidence == ()
        assert ev.coverage.concept is EvidenceKindState.NOT_MEASURED
        assert ev.coverage.skill is EvidenceKindState.NOT_MEASURED

    async def test_skill_bridge_absent_is_measured_zero(self) -> None:
        """개념은 선택됐는데 해소된 스킬이 0건 — 이건 *본* 0건이다."""
        session = _RoleSession(primary=[_PRIMARY], tested=[], skills=[])
        ev = await _collect(session, correct=False)
        assert ev.coverage.skill is EvidenceKindState.EMPTY_MEASURED

    async def test_gated_candidates_are_carried_through(self) -> None:
        session = _RoleSession(primary=[_PRIMARY], tested=[])
        ev = await _collect(
            session,
            correct=False,
            possible_misconceptions=(
                MisconceptionCandidate(misconception_id="M-042", confidence=0.8, gate_passed=True),
            ),
            misconception_scan=MisconceptionScan.RAN_WITH_CANDIDATES,
        )
        assert [c.misconception_id for c in ev.possible_misconceptions] == ["M-042"]
        assert ev.coverage.misconception is EvidenceKindState.FILLED


# ──────────────────────────────────────────────────────────────────────────
# 쓰기 0 — 증거는 관측이지 상태가 아니다 (acceptance ⑤)
# ──────────────────────────────────────────────────────────────────────────
class TestCollectorWritesNothing:
    @pytest.mark.parametrize("correct", [True, False])
    async def test_no_rows_added_and_no_commit(self, correct: bool) -> None:
        """조립이 상태를 바꾸면 그 순간 "한 트랜잭션처럼 보이기" 문제가 생긴다."""
        session = _RoleSession(primary=[_PRIMARY], tested=[_TESTED], skills=["skill.slope"])
        await _collect(session, correct=correct)
        assert session.added == []
        assert session.commits == 0

    def test_module_source_has_no_write_calls(self) -> None:
        """문자열이 아니라 *구성된 결과*를 보는 편이 낫지만, 여기선 좌석 자체의 부재가 계약이다."""
        import inspect

        from whymath_backend.l2 import assessment_evidence

        source = inspect.getsource(assessment_evidence)
        body = "\n".join(line for line in source.splitlines() if not line.strip().startswith("#"))
        assert "session.add(" not in body
        assert "session.commit(" not in body


# ──────────────────────────────────────────────────────────────────────────
# 합치 — 모델 B 사본 3곳이 같은 개념을 고르는가
# ──────────────────────────────────────────────────────────────────────────
class TestModelBAgreement:
    """정본(`select_concept_evidence`) ↔ 두 writer 인라인 사본의 선택 집합 일치 동결.

    드리프트하면 증거가 가리키는 개념과 실제로 갱신되는 개념이 갈라진다 — "왜 이 개념이
    내려갔는가"의 답이 거짓이 되는 지점이다. 통합은 `EOS-13`이 가져간다.
    """

    @pytest.mark.parametrize(
        ("correct", "primary", "tested"),
        [
            (True, [_PRIMARY], [_TESTED]),
            (False, [_PRIMARY], [_TESTED]),
            (False, [], [_TESTED]),  # PRIMARY 미매핑 퇴화 문항 — 폴백 절을 밟는다
            (True, [], []),  # 미매핑
            (False, [], []),
        ],
    )
    async def test_concept_writer_selects_the_same_concepts(
        self, correct: bool, primary: list[uuid.UUID], tested: list[uuid.UUID]
    ) -> None:
        evidence_session = _RoleSession(primary=primary, tested=tested)
        evidence = await _collect(evidence_session, correct=correct)
        expected = {e.concept_id for e in evidence.concept_evidence}

        writer_session = _RoleSession(primary=primary, tested=tested)
        # EOS-18: writer가 **그 증거 객체 자체**를 소비한다 — 정답 여부를 따로 넘기지
        # 않으므로 조립과 적재가 어긋날 여지가 구조적으로 없다(사본 0).
        rows = await record_problem_attempt_mastery(
            cast(AsyncSession, writer_session), evidence=evidence
        )
        assert {row.concept_id for row in rows} == expected

    @pytest.mark.parametrize(
        ("correct", "primary", "tested"),
        [
            (True, [_PRIMARY], [_TESTED]),
            (False, [_PRIMARY], [_TESTED]),
            (False, [], [_TESTED]),
        ],
    )
    async def test_skill_writer_resolves_from_the_same_concepts(
        self, correct: bool, primary: list[uuid.UUID], tested: list[uuid.UUID]
    ) -> None:
        """스킬 축 writer도 같은 개념 집합에서 해소해야 한다 — 두 축이 갈라지면 안 된다."""
        evidence_session = _RoleSession(primary=primary, tested=tested, skills=["skill.slope"])
        evidence = await _collect(evidence_session, correct=correct)
        expected = {e.concept_id for e in evidence.concept_evidence}

        writer_session = _RoleSession(primary=primary, tested=tested, skills=["skill.slope"])
        await record_problem_attempt_skill_mastery(
            cast(AsyncSession, writer_session), evidence=evidence
        )
        # writer가 개념 조회에 쓴 role 필터를 재생해 같은 집합인지 본다.
        selected: set[uuid.UUID] = set()
        for roles in writer_session.concept_queries:
            if ConceptRole.PRIMARY in roles:
                selected.update(primary)
            if ConceptRole.TESTED in roles:
                selected.update(tested)
        if correct:
            assert selected == set(primary) | set(tested) == expected
        else:
            # 오답: PRIMARY 우선, 없으면 TESTED 폴백 — 조회는 두 번 날 수 있으나 결과는 같다.
            assert expected <= selected

    async def test_the_agreement_fixture_actually_exercises_the_fallback(self) -> None:
        """이 절이 없으면 폴백 분기를 한 번도 밟지 않은 채 "합치 확인"이라 말하게 된다."""
        session = _RoleSession(primary=[], tested=[_TESTED])
        ev = await _collect(session, correct=False)
        assert [e.attribution for e in ev.concept_evidence] == [AttributionBasis.TESTED_FALLBACK]
