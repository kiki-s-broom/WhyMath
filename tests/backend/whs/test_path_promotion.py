"""WH-S 구조 승격 어댑터(`whs/path_promotion.py`) 테스트 — S4-09 + S4-10 재론 (hermetic).

평문 `verified_solutions.solution_path` JSONB → `l3.SolutionPath` 승격의 정상/이상 경로를
검증한다: 정상 승격(sympy_verified 정직 승계·결정론 sp-id·concept 날조 0), 이상(빈 steps·
형식 위반·problem 부재·approach 미매핑 큐·멱등), 다중 경로 재론 규약(S4-10 — 헤더는 문제당
N경로 허용·단계는 대표 1경로만: 추가 경로/레거시 선점은 *헤더만* 적재·단계 스킵 카운트),
검수 큐 분기(자동 적재 불가 형식), CLI 배선(stdout=큐 JSONL·stderr=리포트·exit 0).

분해 전략: 판정 전부가 순수 `plan_promotion`에 있어 DB 없이 검증하고(ORM 인스턴스는 평범한
파이썬 객체), DB 래퍼(`promote_verified_solutions`)는 FakeSession으로 조회 4종·add/flush
배선만 검증한다(실 SQL·FK는 실 PG 통합 몫 — `test_solution_bank.py` 이원화 선례).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.problem import ProblemStep
from whymath_backend.db.models.solution_path import SolutionPath as SolutionPathOrm
from whymath_backend.db.models.verified_solution import (
    VerifiedSolution,
    WhsSolutionGrade,
)
from whymath_backend.whs.path_promotion import (
    PromotionPlan,
    build_solution_path,
    extract_plain_steps,
    main,
    map_strategy_tag_to_approach,
    plan_promotion,
    promote_verified_solutions,
    solution_path_id_for,
)

_NOW = datetime(2026, 7, 29, 12, 0, 0, tzinfo=UTC)


def _vs(
    *,
    problem_id: uuid.UUID | None = None,
    grade: WhsSolutionGrade = WhsSolutionGrade.VERIFIED,
    steps: Any = ("2*x = 6", "x = 3"),
    strategy_tag: str | None = "대수적",
    solution_path: dict[str, Any] | None = None,
) -> VerifiedSolution:
    """DB 없이 VerifiedSolution 인스턴스 구성(id·created_at은 server_default라 수동 지정)."""
    row = VerifiedSolution(
        problem_id=problem_id or uuid.uuid4(),
        grade=grade,
        solution_path=(
            solution_path
            if solution_path is not None
            else {
                "conditions": ["Eq(2*x, 6)"],
                "answer": {"x": "3"},
                "steps": list(steps),
            }
        ),
        strategy_tag=strategy_tag,
        answer="x=3",
    )
    row.id = uuid.uuid4()
    row.created_at = _NOW
    return row


def _plan(rows: list[VerifiedSolution], **overrides: Any) -> PromotionPlan:
    """기본 컨텍스트(모든 문제 실재·기존 적재 0)로 plan_promotion 호출."""
    context: dict[str, Any] = {
        "existing_problem_ids": {row.problem_id for row in rows},
        "already_promoted_path_ids": set(),
        "problem_ids_with_steps": set(),
        "now": _NOW,
    }
    context.update(overrides)
    return plan_promotion(rows, **context)


# ==========================================================================
# 순수 부품 — 매핑·추출·빌더
# ==========================================================================
class TestMapStrategyTag:
    def test_korean_labels_map_one_to_one(self) -> None:
        """한글 라벨 6종 → 영문 6종 결정론 번역(yaml 한글 설명 1:1)."""
        assert map_strategy_tag_to_approach("대수적") == "algebraic"
        assert map_strategy_tag_to_approach("기하적") == "geometric"
        assert map_strategy_tag_to_approach("조합적") == "combinatorial"
        assert map_strategy_tag_to_approach("귀납적") == "inductive"
        assert map_strategy_tag_to_approach("시각적") == "visual"
        assert map_strategy_tag_to_approach("역방향") == "backward"

    def test_english_exact_values_pass_through(self) -> None:
        """영문 정본 값은 그대로 통과."""
        assert map_strategy_tag_to_approach("algebraic") == "algebraic"
        assert map_strategy_tag_to_approach("backward") == "backward"

    def test_unknown_tag_returns_none(self) -> None:
        """미지 태그("corpus-replay" — 620문 재생 실측값)는 None — 추측 금지(검수 큐행)."""
        assert map_strategy_tag_to_approach("corpus-replay") is None
        assert map_strategy_tag_to_approach(None) is None
        assert map_strategy_tag_to_approach("직관적") is None


class TestExtractPlainSteps:
    def test_valid_steps_extracted(self) -> None:
        assert extract_plain_steps({"steps": ["a", "b"]}) == ["a", "b"]

    def test_missing_or_nonlist_steps_returns_none(self) -> None:
        """형식 위반(키 부재·리스트 아님·비문자열 원소)은 None — 조용한 통과 금지."""
        assert extract_plain_steps({}) is None
        assert extract_plain_steps({"steps": "x=3"}) is None
        assert extract_plain_steps({"steps": ["ok", 42]}) is None


class TestBuildSolutionPath:
    def test_orders_enumerated_from_one_and_content_preserved(self) -> None:
        """order는 1부터 열거·content는 표현식 문자열 그대로(렌더러-중립)."""
        path = build_solution_path(
            solution_path_id="sp-x",
            problem_id=uuid.uuid4(),
            approach_type="algebraic",
            steps=["2*x = 6", "x = 3"],
            created_at=_NOW,
        )
        assert [s.order for s in path.steps] == [1, 2]
        assert [s.content for s in path.steps] == ["2*x = 6", "x = 3"]

    def test_sympy_verified_inherited_honestly(self) -> None:
        """첫 스텝 False·이후 True — verified가 보증하는 것은 *인접 전이*뿐(과잉 주장 금지)."""
        path = build_solution_path(
            solution_path_id="sp-x",
            problem_id=uuid.uuid4(),
            approach_type="algebraic",
            steps=["a", "b", "c"],
            created_at=_NOW,
        )
        assert [s.sympy_verified for s in path.steps] == [False, True, True]

    def test_no_fabricated_metadata(self) -> None:
        """concept_sequence 빈 배열·concept/reasoning/justification None — 날조 0."""
        path = build_solution_path(
            solution_path_id="sp-x",
            problem_id=uuid.uuid4(),
            approach_type="geometric",
            steps=["a"],
            created_at=_NOW,
        )
        assert path.concept_sequence == []
        assert path.verified_by_human is False
        step = path.steps[0]
        assert step.concept_node_id is None
        assert step.reasoning_type is None
        assert step.justification is None


# ==========================================================================
# plan_promotion — 판정 분기 전건
# ==========================================================================
class TestPlanPromotion:
    def test_normal_promotion(self) -> None:
        """정상: verified+매핑 가능 태그 → 계획 1건(대표 — 헤더+단계)·additive 필드 충전."""
        row = _vs()
        plan = _plan([row])
        assert plan.report.promoted == 1
        assert plan.report.promoted_with_steps == 1
        assert plan.report.promoted_steps == 2
        assert len(plan.planned) == 1
        planned = plan.planned[0]
        assert planned.path.solution_path_id == solution_path_id_for(row.id)
        assert planned.path.approach_type == "algebraic"
        schemas = planned.step_schemas
        assert [s.step_order for s in schemas] == [1, 2]
        assert [s.expected_answer for s in schemas] == ["2*x = 6", "x = 3"]
        assert [s.solution_path_id for s in schemas] == [planned.path.solution_path_id] * 2
        assert [s.sympy_verified for s in schemas] == [False, True]
        assert all(s.concept_node_id is None for s in schemas)

    def test_unverified_excluded(self) -> None:
        """unverified는 격리 유지(R-S2) — 서빙 표면에 절대 미승격."""
        plan = _plan([_vs(grade=WhsSolutionGrade.UNVERIFIED)])
        assert plan.report.excluded_unverified == 1
        assert plan.report.promoted == 0
        assert plan.planned == []

    def test_empty_steps_skipped(self) -> None:
        """이상: 빈 steps는 실체화할 단계가 없어 스킵(리포트 카운트)."""
        plan = _plan([_vs(steps=())])
        assert plan.report.skipped_empty_steps == 1
        assert plan.report.promoted == 0

    def test_malformed_steps_skipped_with_reason(self) -> None:
        """이상: steps 형식 위반은 스킵 + 사유 기록(조용한 통과 금지)."""
        plan = _plan([_vs(solution_path={"steps": "x=3"})])
        assert plan.report.skipped_malformed == 1
        assert any("malformed_steps" in f for f in plan.report.failures)

    def test_problem_missing_skipped_with_reason(self) -> None:
        """이상: 코퍼스에 없는 문제는 FK 불가 — 스킵 + 사유 기록(날조 금지)."""
        plan = _plan([_vs()], existing_problem_ids=set())
        assert plan.report.skipped_problem_missing == 1
        assert any("problem_missing" in f for f in plan.report.failures)

    def test_approach_unmappable_goes_to_review_queue(self) -> None:
        """매칭 실패 큐 분기 ①: 미매핑 태그는 승격 차단 + 사람 검수 큐(AI 자기승인 금지)."""
        row = _vs(strategy_tag="corpus-replay")
        plan = _plan([row])
        assert plan.report.queued_approach_unmappable == 1
        assert plan.report.promoted == 0
        entries = [e for e in plan.queue_entries if e["reason"] == "approach_unmappable"]
        assert len(entries) == 1
        entry = entries[0]
        assert entry["queue"] == "solution_path_promotion_review"
        assert entry["verified_solution_id"] == str(row.id)
        assert entry["strategy_tag"] == "corpus-replay"
        # 큐에는 시스템 생성 표현식(steps)·ID만 — 문제 본문/조건 미포함(저작권 게이트 불요).
        assert "conditions" not in entry

    def test_concept_unmatched_queued_but_promotion_proceeds(self) -> None:
        """매칭 실패 큐 분기 ②: 개념 매칭은 전건 검수 대기 — 승격은 진행·concept 좌석 NULL."""
        row = _vs()
        plan = _plan([row])
        assert plan.report.promoted == 1
        assert plan.report.queued_concept_unmatched_steps == 2
        entries = [e for e in plan.queue_entries if e["reason"] == "concept_unmatched"]
        assert len(entries) == 1
        assert entries[0]["unmatched_step_orders"] == [1, 2]
        assert entries[0]["solution_path_id"] == solution_path_id_for(row.id)

    def test_idempotent_rerun_skips_already_promoted(self) -> None:
        """멱등: 기존 sp-id 실재 시 재적재하지 않는다(결정론 ID가 열쇠)."""
        row = _vs()
        plan = _plan([row], already_promoted_path_ids={solution_path_id_for(row.id)})
        assert plan.report.already_promoted == 1
        assert plan.report.promoted == 0
        assert plan.queue_entries == []  # 재실행이 큐를 다시 쌓지 않는다

    def test_second_path_same_problem_header_only(self) -> None:
        """다중 경로 재론(S4-10): 추가 경로도 *헤더는* 승격 — 단계만 스킵(UNIQUE 불변).

        `solution_paths`는 문제당 N경로 허용(yaml N:1 관계·다양성 자산), `problem_step`은
        대표(첫) 경로만 실체화한다. 구 S4-09의 경로 전체 스킵(`skipped_additional_path`)이
        단계 스킵 카운트(`steps_skipped_additional_path`)로 바뀐 것을 동결한다.
        """
        problem_id = uuid.uuid4()
        first = _vs(problem_id=problem_id)
        second = _vs(problem_id=problem_id, steps=("x**2 = 9", "x = 3"))
        plan = _plan([first, second])
        assert plan.report.promoted == 2  # 헤더는 둘 다
        assert plan.report.promoted_with_steps == 1  # 단계는 대표(첫 경로)만
        assert plan.report.steps_skipped_additional_path == 1
        assert plan.report.promoted_steps == 2  # 대표 경로 스텝 수만
        # 계획 형상: 첫 경로만 step_schemas 보유·둘째는 헤더만(빈 튜플).
        assert len(plan.planned) == 2
        assert len(plan.planned[0].step_schemas) == 2
        assert plan.planned[1].step_schemas == ()

    def test_cross_run_existing_steps_block_new_steps(self) -> None:
        """이전 런의 대표 경로가 단계를 선점했으면(problem_step 실재) 새 경로는 헤더만."""
        row = _vs()
        plan = _plan([row], problem_ids_with_steps={row.problem_id})
        assert plan.report.promoted == 1
        assert plan.report.promoted_with_steps == 0
        assert plan.report.steps_skipped_step_conflict == 1

    def test_legacy_steps_conflict_header_only(self) -> None:
        """기존 problem_step 행(레거시 Socratic) 선점 문제 — 단계 스킵(클로버 금지)·헤더 적재."""
        row = _vs()
        plan = _plan([row], problem_ids_with_steps={row.problem_id})
        assert plan.report.steps_skipped_step_conflict == 1
        assert plan.report.promoted == 1
        assert plan.planned[0].step_schemas == ()
        # 개념 검수 큐는 헤더만 적재해도 흐른다(concept_sequence 검수 축).
        assert any(e["reason"] == "concept_unmatched" for e in plan.queue_entries)

    def test_summary_rates_are_honest(self) -> None:
        """리포트 비율 — 개념 매칭률 0.0(매칭 유틸 부재 정직)·0/0은 None(위장 금지)."""
        plan = _plan([_vs()])
        summary = plan.report.summary()
        assert summary["pydantic_pass_rate"] == 1.0
        assert summary["approach_mapped_rate"] == 1.0
        assert summary["concept_match_rate"] == 0.0
        assert summary["promoted_with_steps"] == 1
        empty = _plan([]).report.summary()
        assert empty["pydantic_pass_rate"] is None
        assert empty["approach_mapped_rate"] is None
        assert empty["concept_match_rate"] is None


# ==========================================================================
# DB 래퍼 — FakeSession 배선(조회 4종·add/flush)
# ==========================================================================
class _FakeScalars:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return self._items


class _FakeResult:
    """execute 반환 — scalars().all()(단일 컬럼) 제공(promote가 쓰는 표면 전부)."""

    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._items)


class _FakeSession:
    """promote_verified_solutions가 부르는 표면만 — execute(순서대로 canned)·add·flush."""

    def __init__(self, results: list[_FakeResult]) -> None:
        self._results = list(results)
        self.added: list[Any] = []
        self.flushed = 0

    async def execute(self, _stmt: Any) -> _FakeResult:
        return self._results.pop(0)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushed += 1


class TestPromoteVerifiedSolutions:
    @pytest.mark.asyncio
    async def test_wires_prefetch_plan_and_orm_writes(self) -> None:
        """행 1건 정상 승격 — 헤더 ORM 1 + 단계 ORM 2 add·flush 1회·큐/리포트 반환."""
        row = _vs()
        session = _FakeSession(
            [
                _FakeResult([row]),  # ① 전 행
                _FakeResult([row.problem_id]),  # ② problem 실재
                _FakeResult([]),  # ③ 기존 경로 id(멱등)
                _FakeResult([]),  # ④ 기존 단계 선점
            ]
        )
        plan = await promote_verified_solutions(cast(AsyncSession, session))
        assert plan.report.promoted == 1
        headers = [o for o in session.added if isinstance(o, SolutionPathOrm)]
        steps = [o for o in session.added if isinstance(o, ProblemStep)]
        assert len(headers) == 1 and len(steps) == 2
        assert headers[0].solution_path_id == solution_path_id_for(row.id)
        assert headers[0].approach_type == "algebraic"
        assert headers[0].concept_sequence == []
        assert headers[0].verified_by_human is False
        assert {s.solution_path_id for s in steps} == {solution_path_id_for(row.id)}
        assert sorted(s.step_order for s in steps) == [1, 2]
        # 헤더 flush → 단계 flush 2회(외래 키 순서 — 실 PG 회귀는 *_integration.py가 잡는다).
        assert session.flushed == 2

    @pytest.mark.asyncio
    async def test_additional_path_writes_header_without_steps(self) -> None:
        """재론(S4-10) 배선: 같은 문제 두 경로 — 헤더 ORM 2·단계 ORM은 대표 것 2뿐."""
        problem_id = uuid.uuid4()
        first = _vs(problem_id=problem_id)
        second = _vs(problem_id=problem_id, steps=("x**2 = 9", "x = 3"))
        session = _FakeSession(
            [
                _FakeResult([first, second]),
                _FakeResult([problem_id]),
                _FakeResult([]),
                _FakeResult([]),
            ]
        )
        plan = await promote_verified_solutions(cast(AsyncSession, session))
        assert plan.report.promoted == 2
        headers = [o for o in session.added if isinstance(o, SolutionPathOrm)]
        steps = [o for o in session.added if isinstance(o, ProblemStep)]
        assert len(headers) == 2
        assert len(steps) == 2  # 대표(첫 경로) 스텝만
        assert {s.solution_path_id for s in steps} == {solution_path_id_for(first.id)}

    @pytest.mark.asyncio
    async def test_no_rows_short_circuits_prefetch(self) -> None:
        """행 0건 — 프리페치 3종을 건너뛰고(빈 IN 회피) 빈 계획 반환·add 0."""
        session = _FakeSession([_FakeResult([])])
        plan = await promote_verified_solutions(cast(AsyncSession, session))
        assert plan.report.total_input == 0
        assert session.added == []
        assert session.flushed == 0

    @pytest.mark.asyncio
    async def test_existing_path_ids_block_rerun_writes(self) -> None:
        """기존 경로 id 프리페치가 멱등 스킵으로 이어진다 — add 0(재적재 금지)."""
        row = _vs()
        session = _FakeSession(
            [
                _FakeResult([row]),
                _FakeResult([row.problem_id]),
                _FakeResult([solution_path_id_for(row.id)]),
                _FakeResult([]),
            ]
        )
        plan = await promote_verified_solutions(cast(AsyncSession, session))
        assert plan.report.already_promoted == 1
        assert session.added == []


# ==========================================================================
# CLI — stdout=검수 큐 JSONL·stderr=리포트·exit 0·dry-run 기본
# ==========================================================================
class TestCli:
    def _fake_promote_fn(self, plan: PromotionPlan) -> Any:
        calls: list[bool] = []

        async def fake(apply: bool) -> PromotionPlan:
            calls.append(apply)
            return plan

        return fake, calls

    def test_dry_run_default_and_output_split(self, capsys: Any) -> None:
        """기본 dry-run — stdout 큐 JSONL·stderr 리포트 JSON(mode=dry-run)·exit 0."""
        row = _vs()
        plan = _plan([row])
        fake, calls = self._fake_promote_fn(plan)
        assert main([], promote_fn=fake) == 0
        assert calls == [False]  # 기본은 미적재(dry-run)
        captured = capsys.readouterr()
        queue_lines = [json.loads(line) for line in captured.out.strip().splitlines()]
        assert len(queue_lines) == 1
        assert queue_lines[0]["queue"] == "solution_path_promotion_review"
        summary = json.loads(captured.err.strip())
        assert summary["mode"] == "dry-run"
        assert summary["promoted"] == 1
        assert summary["concept_match_rate"] == 0.0

    def test_apply_flag_passed_through(self, capsys: Any) -> None:
        """--apply일 때만 적재 플래그 True — 리포트 mode=apply."""
        fake, calls = self._fake_promote_fn(PromotionPlan())
        assert main(["--apply"], promote_fn=fake) == 0
        assert calls == [True]
        summary = json.loads(capsys.readouterr().err.strip())
        assert summary["mode"] == "apply"
        assert summary["total_input"] == 0
