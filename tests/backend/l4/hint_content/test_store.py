"""`hints` 유일 writer·reader·원천 로더 — 왕복·멱등·은퇴·서빙 이중 가드 (S4-11 · hermetic).

실 PostgreSQL 없이 검증한다. writer/reader가 던지는 **실제 SQLAlchemy 문장**을 컴파일해 그 WHERE
조건(문자열·바인드 파라미터)만으로 메모리 표를 거르는 가짜 세션을 쓴다 — 가짜가 조건을 *스스로
보태지 않으므로*, reader에서 `verified IS true` 조건이 빠지면 가짜도 미검수 행을 돌려주고, 그때
행 재확인(이중 가드)이 막는지를 볼 수 있다. 실 PG 왕복은 `tests/backend/db/
test_hints_migration_integration.py`(integration 마커) 소관이다.
"""

from __future__ import annotations

import logging
import uuid
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.concept import Concept
from whymath_backend.db.models.concept_node import ConceptNode
from whymath_backend.db.models.hint import Hint as HintORM
from whymath_backend.db.models.problem import Problem
from whymath_backend.l4.hint_content import store
from whymath_backend.l4.hint_content.gates import GateContext, evaluate_gates
from whymath_backend.l4.hint_content.generator import ConceptRef, StepSource, generate_step_hints
from whymath_backend.l4.hint_content.models import Hint, ServedHint

from ._fakes import _HintTableSession, _Result

_PID = uuid.UUID("00000000-0000-0000-0000-00000000c033")
_OTHER_PID = uuid.UUID("00000000-0000-0000-0000-00000000c034")
_STEPS = ("x**2 - 5*x + 6", "(x - 2)*(x - 3)", "x = 2, x = 3")
_CONCEPT = ConceptRef(concept_id="math.algebra.factoring", name="인수분해", source="step")


def _gated_hints(order: int, *, path_id: str = "sp-a", problem_id: uuid.UUID = _PID) -> list[Hint]:
    source = StepSource(
        solution_path_id=path_id,
        problem_id=problem_id,
        step_order=order,
        step_contents=_STEPS,
        transition_verified=True,
        concept=_CONCEPT,
    )
    ctx = GateContext(step_contents=_STEPS, concept_name=_CONCEPT.name, final_answer="123")
    return [evaluate_gates(d, ctx) for d in generate_step_hints(source).drafts]


def _row(hint: Hint) -> HintORM:
    return HintORM(hint_id=hint.hint_id, **store.hint_to_columns(hint))


def _session(fake: object) -> AsyncSession:
    return cast(AsyncSession, fake)


# ── 매핑 왕복 ──────────────────────────────────────────────────────────
class TestMappingRoundTrip:
    def test_row_round_trips_to_the_same_hint(self) -> None:
        for hint in _gated_hints(2):
            assert store.hint_from_row(_row(hint)) == hint

    def test_columns_carry_verification_and_reveals(self) -> None:
        hint = _gated_hints(2)[0]
        columns = store.hint_to_columns(hint)
        assert columns["verified"] is True
        assert columns["level"] == 1
        assert columns["socratic_category"] == "perspective"
        assert columns["revealed_concept_ids"] == [_CONCEPT.concept_id]
        assert columns["reveal_score"] == pytest.approx(1 / 3)


# ── writer ────────────────────────────────────────────────────────────
class TestWriter:
    async def test_insert_then_second_run_is_all_unchanged(self) -> None:
        """헌법 R3-01 '두 번 실행' — 두 번째 실행은 행 수·결과가 같다(전부 unchanged)."""
        hints = _gated_hints(2) + _gated_hints(3)
        fake = _HintTableSession()
        first = await store.write_hints(_session(fake), hints, processed_path_ids=["sp-a"])
        assert (first.inserted, first.updated, first.unchanged, first.retired) == (5, 0, 0, 0)
        snapshot = {k: store.hint_to_columns(store.hint_from_row(v)) for k, v in fake.rows.items()}

        second = await store.write_hints(_session(fake), hints, processed_path_ids=["sp-a"])
        assert (second.inserted, second.updated, second.unchanged, second.retired) == (0, 0, 5, 0)
        assert len(fake.rows) == 5
        again = {k: store.hint_to_columns(store.hint_from_row(v)) for k, v in fake.rows.items()}
        assert again == snapshot

    async def test_changed_content_is_updated(self) -> None:
        hints = _gated_hints(2)
        fake = _HintTableSession([_row(h) for h in hints])
        changed = [hints[0].model_copy(update={"content": hints[0].content + " 다시 보자."})]
        counts = await store.write_hints(_session(fake), changed + hints[1:])
        assert (counts.updated, counts.unchanged) == (1, 2)
        assert fake.rows[hints[0].hint_id].content.endswith("다시 보자.")
        # updated_at은 writer가 대입하지 않고 ORM onupdate가 UPDATE 시 갱신한다(learner_state
        # 단일 writer 가드와 이름이 겹치는 수동 대입을 두지 않는다) — 선언이 실재하는지 확인.
        assert HintORM.__table__.c.updated_at.onupdate is not None

    async def test_vanished_hint_is_retired_not_deleted(self) -> None:
        """재생성에서 사라진 힌트는 삭제가 아니라 verified=false로 내려 서빙에서 뺀다."""
        old = _gated_hints(2)
        other_path = _gated_hints(2, path_id="sp-other")
        fake = _HintTableSession([_row(h) for h in old + other_path])
        keep = old[1:]  # L1이 사라진 상황(예: 단계 개념이 바뀜)
        counts = await store.write_hints(_session(fake), keep, processed_path_ids=["sp-a"])
        assert counts.retired == 1
        retired = fake.rows[old[0].hint_id]
        assert retired.verified is False
        assert "retired" in retired.gate_report and retired.gate_report["passed"] is False
        # 처리하지 않은 경로의 힌트는 건드리지 않는다.
        assert all(fake.rows[h.hint_id].verified for h in other_path)

    async def test_persist_generation_commits_once(self) -> None:
        fake = _HintTableSession()
        counts = await store.persist_generation(
            _session(fake), _gated_hints(2), processed_path_ids=["sp-a"]
        )
        assert counts.inserted == 3 and fake.commits == 1


# ── reader ────────────────────────────────────────────────────────────
class TestServingReader:
    def _catalog(self) -> _HintTableSession:
        return _HintTableSession(
            [
                _row(h)
                for h in _gated_hints(2)
                + _gated_hints(3)
                + _gated_hints(2, problem_id=_OTHER_PID, path_id="sp-b")
            ]
        )

    async def test_serves_earliest_verified_hint_at_or_after_step(self) -> None:
        fake = self._catalog()
        served = await store.find_served_hint(
            _session(fake), problem_id=_PID, hint_level=2, from_step_order=1
        )
        assert isinstance(served, ServedHint)
        assert (served.level, served.step_order) == (2, 2)
        assert served.hint_id == "hint-sp-a-s2-l2"
        assert served.reveal_score == pytest.approx(2 / 3)
        later = await store.find_served_hint(
            _session(fake), problem_id=_PID, hint_level=2, from_step_order=3
        )
        assert later is not None and later.step_order == 3

    async def test_none_when_student_is_past_every_hint(self) -> None:
        served = await store.find_served_hint(
            _session(self._catalog()), problem_id=_PID, hint_level=1, from_step_order=4
        )
        assert served is None

    async def test_level_four_is_never_queried(self) -> None:
        """Level 4(전체 풀이)는 Hint 엔티티 밖 — 조회 자체를 하지 않는다."""
        fake = self._catalog()
        served = await store.find_served_hint(
            _session(fake), problem_id=_PID, hint_level=4, from_step_order=1
        )
        assert served is None and fake.executed == []

    async def test_unverified_row_is_never_served(self) -> None:
        hint = _gated_hints(2)[1]
        fake = _HintTableSession([_row(hint.model_copy(update={"verified": False}))])
        served = await store.find_served_hint(
            _session(fake), problem_id=_PID, hint_level=2, from_step_order=1
        )
        assert served is None
        assert "hints.verified IS true" in fake.executed[0]  # 쿼리 조건이 실재한다

    async def test_row_recheck_blocks_unverified_even_if_query_leaks_it(self) -> None:
        """이중 가드 — 쿼리가 미검수 행을 흘려도(가짜가 조건 무시) 행 재확인이 막는다."""
        leaky_row = _row(_gated_hints(2)[1].model_copy(update={"verified": False}))

        class _Leaky:
            async def execute(self, _stmt: Any) -> _Result:
                return _Result([leaky_row])

        served = await store.find_served_hint(
            _session(_Leaky()), problem_id=_PID, hint_level=2, from_step_order=1
        )
        assert served is None

    async def test_non_hint_row_is_not_served(self) -> None:
        class _Garbage:
            async def execute(self, _stmt: Any) -> _Result:
                return _Result([("not", "a", "hint")])

        served = await store.find_served_hint(
            _session(_Garbage()), problem_id=_PID, hint_level=1, from_step_order=1
        )
        assert served is None

    async def test_contract_breaking_row_is_withheld_with_type_name(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """DB 행이 계약(level 1~3)을 벗어나면 서빙하지 않고 예외 타입명을 남긴다."""
        corrupt = _row(_gated_hints(2)[1])
        corrupt.level = 4

        class _Corrupt:
            async def execute(self, _stmt: Any) -> _Result:
                return _Result([corrupt])

        with caplog.at_level(logging.WARNING, logger="whymath.l4.hint_content.store"):
            served = await store.find_served_hint(
                _session(_Corrupt()), problem_id=_PID, hint_level=2, from_step_order=1
            )
        assert served is None
        assert "ValidationError" in caplog.text


@pytest.mark.parametrize(
    ("steps", "expected"),
    [(None, 1), ([], 1), (["a"], 2), (["a", "  ", "b"], 3)],
)
def test_serving_step_order_counts_written_steps(steps: list[str] | None, expected: int) -> None:
    assert store.serving_step_order(steps) == expected


# ── 원천 로더 ──────────────────────────────────────────────────────────
class _GetSession:
    """`session.get(Model, pk)`만 쓰는 로더 경로용 가짜(execute는 monkeypatch한 함수가 대신)."""

    def __init__(self, preload: dict[tuple[type, object], object]) -> None:
        self._preload = preload

    async def get(self, model: type, pk: object) -> object | None:
        return self._preload.get((model, pk))


def _step(order: int, content: str, *, verified: bool | None, concept: str | None = None) -> Any:
    return SimpleNamespace(
        step_order=order, expected_answer=content, sympy_verified=verified, concept_node_id=concept
    )


class TestLoader:
    async def test_loads_inputs_and_accounts_every_skip(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        concept_uuid = uuid.uuid4()
        headers = {
            "sp-ok": SimpleNamespace(problem_id=_PID),
            "sp-gap": SimpleNamespace(problem_id=_PID),
            "sp-noanswer": SimpleNamespace(problem_id=_OTHER_PID),
        }
        steps = {
            "sp-ok": [
                _step(1, _STEPS[0], verified=False),
                _step(2, _STEPS[1], verified=True, concept="math.algebra.factoring"),
                _step(3, _STEPS[2], verified=True),
            ],
            "sp-gap": [_step(1, "a", verified=False), _step(3, "b", verified=True)],
            "sp-noanswer": [_step(1, "y", verified=False), _step(2, "z", verified=True)],
        }

        async def _ids(_session: object) -> list[str]:
            return ["sp-gap", "sp-missing", "sp-noanswer", "sp-ok"]

        async def _header(_session: object, path_id: str) -> object | None:
            return headers.get(path_id)

        async def _steps(_session: object, path_id: str) -> list[Any]:
            return steps[path_id]

        async def _primary(_session: object, problem_id: uuid.UUID) -> uuid.UUID | None:
            return concept_uuid if problem_id == _PID else None

        monkeypatch.setattr(store, "list_step_materialized_path_ids", _ids)
        monkeypatch.setattr(store, "get_solution_path", _header)
        monkeypatch.setattr(store, "get_solution_path_steps", _steps)
        monkeypatch.setattr(store, "get_primary_concept_id", _primary)
        preload: dict[tuple[type, object], object] = {
            (Problem, _PID): SimpleNamespace(answer="x = 2, x = 3"),
            (Problem, _OTHER_PID): SimpleNamespace(answer=None),
            (ConceptNode, "math.algebra.factoring"): SimpleNamespace(
                concept_id="math.algebra.factoring", name_ko="인수분해"
            ),
            (Concept, concept_uuid): SimpleNamespace(code="math.algebra.poly", name_ko="다항식"),
        }
        inputs, report = await store.load_path_inputs(_session(_GetSession(preload)))

        assert report.paths_seen == 4 and report.paths_loaded == 2
        assert report.skipped_missing_header == 1 and report.skipped_noncontiguous_steps == 1
        assert sorted(report.skipped_path_ids) == ["sp-gap", "sp-missing"]
        assert report.answers_missing == 1
        by_id = {p.solution_path_id: p for p in inputs}
        ok = by_id["sp-ok"]
        assert ok.step_contents == _STEPS
        assert ok.step_verified == (False, True, True)
        assert ok.final_answer == "x = 2, x = 3"
        # 단계 매칭 개념이 우선, 없으면 문제 대표 개념(출처 표기 분리).
        assert [c.source if c else None for c in ok.step_concepts] == [
            "problem_primary",
            "step",
            "problem_primary",
        ]
        assert ok.step_concepts[1] == ConceptRef("math.algebra.factoring", "인수분해", "step")
        assert ok.step_concepts[0] == ConceptRef("math.algebra.poly", "다항식", "problem_primary")
        # 문제 대표 개념도 없으면 None(날조 금지).
        assert by_id["sp-noanswer"].step_concepts == (None, None)
        assert report.concepts_from_step == 1
        assert report.concepts_from_problem == 2
        assert report.concepts_missing == 2
