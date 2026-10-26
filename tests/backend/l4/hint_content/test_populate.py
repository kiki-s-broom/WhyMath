"""오프라인 생성 CLI — 순수 조립·배치 회계·두 번 실행 멱등·종료 코드 (S4-11).

`populate`는 원천 로드 → 생성 → 게이트 → (apply) 적재의 실행 표면이다. DB는 `load_path_inputs`와
세션 팩토리만 monkeypatch하고, 적재는 **실제** `store.persist_generation`을 메모리 표 가짜 세션에
태운다 — 그래서 '두 번 실행' 계약(헌법 R3-01)을 CLI 경로 그대로 잰다.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

from whymath_backend.l4.hint_content import populate
from whymath_backend.l4.hint_content.generator import (
    SKIP_FINAL_STEP_PARTIAL,
    SKIP_NO_CONCEPT,
    SKIP_UNVERIFIED_STEP,
    ConceptRef,
)
from whymath_backend.l4.hint_content.store import PathInput, PathLoadReport
from whymath_backend.l4.subject_adapter_math import math_answer_value_exposure

from ._fakes import _HintTableSession

_PID = uuid.UUID("00000000-0000-0000-0000-00000000d044")
_CONCEPT = ConceptRef(concept_id="math.algebra.factoring", name="인수분해", source="step")
_VALUE = math_answer_value_exposure()


def _path(*, answer: str | None = "123", concept: ConceptRef | None = _CONCEPT) -> PathInput:
    return PathInput(
        solution_path_id="sp-pop",
        problem_id=_PID,
        step_contents=("x**2 - 5*x + 6", "(x - 2)*(x - 3)", "x = 2, x = 3"),
        step_verified=(False, True, True),
        step_concepts=(concept, concept, concept),
        final_answer=answer,
    )


class TestBuildPathHints:
    def test_generates_and_gates_every_verified_step(self) -> None:
        result = populate.build_path_hints(_path(), value_exposure=_VALUE)
        # 2단계: L1·L2·L3 / 3단계(마지막): L1·L2 → 5개, 전부 게이트 통과.
        assert sorted((h.solution_step_ref.step_order, h.level) for h in result.hints) == [
            (2, 1),
            (2, 2),
            (2, 3),
            (3, 1),
            (3, 2),
        ]
        assert all(h.verified for h in result.hints)
        assert (1, 1, SKIP_UNVERIFIED_STEP) in result.skipped
        assert (3, 3, SKIP_FINAL_STEP_PARTIAL) in result.skipped

    def test_missing_answer_makes_every_hint_unverified(self) -> None:
        """정답 원천이 없으면 게이트 B가 fail-closed — 생성은 되지만 전부 미검수."""
        result = populate.build_path_hints(_path(answer=None), value_exposure=_VALUE)
        assert result.hints and not any(h.verified for h in result.hints)

    def test_missing_value_capability_makes_every_hint_unverified(self) -> None:
        """값 축 능력을 넘기지 않으면(None) 값 노출을 판정하지 못한 것 — 전부 미검수(fail-closed)."""
        result = populate.build_path_hints(_path(), value_exposure=None)
        assert result.hints and not any(h.verified for h in result.hints)

    def test_answer_valued_partial_is_rejected_and_counted(self) -> None:
        """P3-77 — L3가 '계산하면 정답이 되는 식'을 보여 주면 거부되고, 값 축 판정이 회계에 남는다."""
        path = PathInput(
            solution_path_id="sp-val",
            problem_id=_PID,
            step_contents=("x = 2", "y = 3*(2) + 1", "y = 7"),
            step_verified=(True, True, True),
            step_concepts=(_CONCEPT, _CONCEPT, _CONCEPT),
            final_answer="7",
        )
        result = populate.build_path_hints(path, value_exposure=_VALUE)
        l3 = {h.solution_step_ref.step_order: h for h in result.hints if h.level == 3}
        assert l3[1].verified is True  # 값 진술 `x = 2`만 보여 준다(2 ≠ 정답 7)
        assert l3[2].verified is False  # `3*(2) + 1` = 7 = 정답
        payload = populate.summarize(
            [result], load=PathLoadReport(paths_seen=1), applied=False
        ).to_json()
        assert payload["value_exposure_verdicts"]["exposed"] >= 1

    def test_no_concept_skips_l1_with_reason(self) -> None:
        result = populate.build_path_hints(_path(concept=None), value_exposure=_VALUE)
        assert {h.level for h in result.hints} == {2, 3}
        assert (2, 1, SKIP_NO_CONCEPT) in result.skipped


class TestSummarize:
    def test_report_accounts_levels_gates_and_rate(self) -> None:
        results = [
            populate.build_path_hints(_path(), value_exposure=_VALUE),
            populate.build_path_hints(_path(answer=None), value_exposure=_VALUE),
        ]
        report = populate.summarize(results, load=PathLoadReport(paths_seen=2), applied=False)
        payload = report.to_json()
        assert payload["generated"] == 10 and payload["verified"] == 5
        assert payload["verified_rate"] == pytest.approx(0.5)
        assert payload["generated_by_level"] == {"1": 4, "2": 4, "3": 2}
        assert payload["verified_by_level"] == {"1": 2, "2": 2, "3": 1}
        assert payload["rejected_by_gate"] == {
            "answer_leakage": 5,
            "level_reveals": 0,
            "tone": 0,
        }
        assert payload["leakage_verdicts"] == {"clean": 5, "not_run": 5}
        assert payload["value_exposure_verdicts"] == {"clean": 5, "not_run": 5}
        assert payload["skipped_by_reason"] == {
            SKIP_FINAL_STEP_PARTIAL: 2,
            SKIP_UNVERIFIED_STEP: 6,
        }
        assert payload["writes"] is None

    def test_zero_generated_rate_is_none_not_zero(self) -> None:
        """0/0을 0으로 날조하지 않는다 — 비율은 None."""
        payload = populate.summarize([], load=PathLoadReport(), applied=False).to_json()
        assert payload["generated"] == 0 and payload["verified_rate"] is None


def _patch_db(
    monkeypatch: pytest.MonkeyPatch, fake: _HintTableSession, inputs: list[PathInput]
) -> None:
    @asynccontextmanager
    async def _session_cm() -> AsyncIterator[_HintTableSession]:
        yield fake

    def _factory() -> Any:
        return _session_cm

    async def _load(_session: object) -> tuple[list[PathInput], PathLoadReport]:
        return inputs, PathLoadReport(paths_seen=len(inputs), paths_loaded=len(inputs))

    monkeypatch.setattr(populate, "get_sessionmaker", _factory)
    monkeypatch.setattr(populate, "load_path_inputs", _load)


class TestRun:
    async def test_dry_run_writes_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _HintTableSession()
        _patch_db(monkeypatch, fake, [_path()])
        report = await populate.run(apply=False, value_exposure=_VALUE)
        assert report.writes is None and fake.rows == {} and fake.commits == 0
        assert report.generated == 5

    async def test_apply_twice_second_run_is_all_unchanged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """헌법 R3-01 — CLI 경로 그대로 두 번 적재해도 행 수·결과가 같다."""
        fake = _HintTableSession()
        _patch_db(monkeypatch, fake, [_path()])
        first = await populate.run(apply=True, value_exposure=_VALUE)
        assert first.writes is not None and first.writes.inserted == 5 and fake.commits == 1
        rows_after_first = len(fake.rows)
        second = await populate.run(apply=True, value_exposure=_VALUE)
        assert second.writes is not None
        assert (second.writes.inserted, second.writes.updated, second.writes.unchanged) == (0, 0, 5)
        assert second.writes.retired == 0
        assert len(fake.rows) == rows_after_first


class TestMain:
    def _report(self, paths_seen: int) -> populate.GenerationReport:
        return populate.summarize([], load=PathLoadReport(paths_seen=paths_seen), applied=False)

    def test_zero_sources_exits_one(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """원천 0건을 '0건 생성 성공'으로 보고하지 않는다(측정 실패 ≠ 0건 통과)."""

        async def _run(
            *, apply: bool, value_exposure: object, overwrite_cms_edits: bool = False
        ) -> populate.GenerationReport:
            return self._report(0)

        monkeypatch.setattr(populate, "run", _run)
        assert populate.main([]) == 1
        captured = capsys.readouterr()
        assert json.loads(captured.out)["paths_seen"] == 0
        assert "원천 경로 0건" in captured.err

    def test_sources_present_exits_zero_and_passes_apply(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        seen: list[bool] = []

        async def _run(
            *, apply: bool, value_exposure: object, overwrite_cms_edits: bool = False
        ) -> populate.GenerationReport:
            seen.append(apply)
            capabilities.append(value_exposure)
            return self._report(3)

        capabilities: list[object] = []
        monkeypatch.setattr(populate, "run", _run)
        assert populate.main(["--apply"]) == 0
        assert seen == [True]
        # 진입점이 합성 루트의 값 축 능력을 실제로 내려 준다(None을 넘기면 전 힌트가 미검수가 된다).
        assert len(capabilities) == 1 and capabilities[0] is not None
        assert hasattr(capabilities[0], "scan_value_exposure")
        assert json.loads(capsys.readouterr().out)["paths_seen"] == 3
