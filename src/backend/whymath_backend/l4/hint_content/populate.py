"""graded 힌트 오프라인 생성 CLI — 원천 로드 → 생성 → 게이트 3종 → (선택) 적재 (S4-11 · D3).

연기 해제 전제 ① generation의 **실행 표면**이다(`whs/path_promotion.py`·`l3/multi_solution.py`
CLI 컨벤션 미러). LLM 호출 0 — 생성은 `generator.py` 템플릿, 검증은 `gates.py`.

    python -m whymath_backend.l4.hint_content.populate            # dry-run(기본·미적재)
    python -m whymath_backend.l4.hint_content.populate --apply    # 실제 적재(commit)

stdout = 리포트 JSON 한 줄(정직 회계 — 원천·생성·건너뜀 사유·게이트별 거부·누출 판정 분포·
레벨별 검수 통과율·적재 카운트). 순수 조립(`build_path_hints`)과 DB glue(`run`)를 나눠
hermetic 테스트가 가능하다.

종료 코드(판정은 exit code로 — 출력 문자열이 아니다):
  - 0 — 원천이 1경로 이상 있었고 생성·(적재)가 끝났다. 검수 통과가 0건이어도 0이다 — 그 사실은
    리포트의 `verified_rate`로 보인다("작동한 비율" — 통과 0을 성공으로 위장하지 않도록 비율을
    항상 싣는다).
  - 1 — 원천 경로가 0건이다. 빈 DB·승격 미실행(`whs.path_promotion --apply` 선행 필요)을
    "0건 생성 성공"으로 보고하지 않는다(측정 실패 ≠ 0건 통과).

값 축 능력(P3-77): 게이트 B·④의 값 동치 판정은 과목 능력(`AnswerValueExposure`)이 한다. 이 CLI는
프로세스의 시작이므로 `main()`이 합성 루트에서 기본 구현을 받아 아래로 **내려 준다**
(`run` → `build_path_hints` → `GateContext`). 순수 조립 함수는 능력을 인자로만 받는다 — 테스트·
다른 과목이 자기 구현을 넘길 수 있고, 넘기지 않은(None) 호출은 값 축이 fail-closed로 거부된다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from whymath_backend.composition import default_answer_value_exposure
from whymath_backend.db.cms_edit_marker import add_overwrite_argument
from whymath_backend.db.session import get_sessionmaker
from whymath_backend.l4.hint_content.gates import (
    GATE_ANSWER_LEAKAGE,
    GATE_NAMES,
    GateContext,
    evaluate_gates,
)
from whymath_backend.l4.hint_content.generator import StepSource, generate_step_hints
from whymath_backend.l4.hint_content.models import HINT_LEVELS, Hint
from whymath_backend.l4.hint_content.store import (
    HintWriteCounts,
    PathInput,
    PathLoadReport,
    load_path_inputs,
    persist_generation,
)
from whymath_backend.schema.verification_capabilities import AnswerValueExposure

__all__ = [
    "GenerationReport",
    "PathHints",
    "build_path_hints",
    "main",
    "run",
    "summarize",
]


@dataclass(frozen=True)
class PathHints:
    """경로 1개의 생성 결과 — 게이트를 거친 힌트 + 건너뛴 (단계, 레벨, 사유)."""

    hints: tuple[Hint, ...]
    skipped: tuple[tuple[int, int, str], ...]


def build_path_hints(path: PathInput, *, value_exposure: AnswerValueExposure | None) -> PathHints:
    """경로 1개 → 단계별 L1~L3 생성 + 게이트 3종 평가(순수·결정론 — DB 0).

    `value_exposure`는 필수 키워드다(기본값 없음 — `GateContext` docstring 같은 이유). None이면
    값 축을 판정하지 못하므로 모든 힌트가 게이트에서 거부된다(fail-closed).
    """
    hints: list[Hint] = []
    skipped: list[tuple[int, int, str]] = []
    for index, verified in enumerate(path.step_verified):
        order = index + 1
        concept = path.step_concepts[index]
        source = StepSource(
            solution_path_id=path.solution_path_id,
            problem_id=path.problem_id,
            step_order=order,
            step_contents=path.step_contents,
            transition_verified=verified,
            concept=concept,
        )
        generation = generate_step_hints(source)
        skipped.extend((order, level, reason) for level, reason in generation.skipped)
        ctx = GateContext(
            step_contents=path.step_contents,
            concept_name=concept.name if concept is not None else None,
            final_answer=path.final_answer,
            value_exposure=value_exposure,
        )
        hints.extend(evaluate_gates(draft, ctx) for draft in generation.drafts)
    return PathHints(hints=tuple(hints), skipped=tuple(skipped))


@dataclass
class GenerationReport:
    """생성 배치 정직 회계 — 수치는 전부 실측(조용한 생략 0)."""

    applied: bool
    load: PathLoadReport
    generated_by_level: dict[int, int] = field(default_factory=dict)
    verified_by_level: dict[int, int] = field(default_factory=dict)
    skipped_by_reason: dict[str, int] = field(default_factory=dict)
    rejected_by_gate: dict[str, int] = field(default_factory=dict)
    leakage_verdicts: dict[str, int] = field(default_factory=dict)
    value_verdicts: dict[str, int] = field(default_factory=dict)
    """게이트 B 값 축 판정 분포(P3-77) — exposed·clean·undecidable·not_run("작동한 비율")."""
    writes: HintWriteCounts | None = None

    @property
    def generated(self) -> int:
        return sum(self.generated_by_level.values())

    @property
    def verified(self) -> int:
        return sum(self.verified_by_level.values())

    def to_json(self) -> dict[str, object]:
        """stdout 한 줄 JSON — 비율은 분모 0이면 None(0/0을 0으로 날조하지 않는다)."""
        return {
            "applied": self.applied,
            "paths_seen": self.load.paths_seen,
            "paths_loaded": self.load.paths_loaded,
            "paths_skipped_missing_header": self.load.skipped_missing_header,
            "paths_skipped_noncontiguous_steps": self.load.skipped_noncontiguous_steps,
            "answers_missing": self.load.answers_missing,
            "concepts_from_step": self.load.concepts_from_step,
            "concepts_from_problem": self.load.concepts_from_problem,
            "concepts_missing": self.load.concepts_missing,
            "concept_codes_off_axis": self.load.concept_codes_off_axis,
            "generated": self.generated,
            "generated_by_level": {str(k): v for k, v in sorted(self.generated_by_level.items())},
            "verified": self.verified,
            "verified_by_level": {str(k): v for k, v in sorted(self.verified_by_level.items())},
            "verified_rate": (self.verified / self.generated) if self.generated else None,
            "skipped_by_reason": dict(sorted(self.skipped_by_reason.items())),
            "rejected_by_gate": dict(sorted(self.rejected_by_gate.items())),
            "leakage_verdicts": dict(sorted(self.leakage_verdicts.items())),
            "value_exposure_verdicts": dict(sorted(self.value_verdicts.items())),
            "writes": (
                {
                    "inserted": self.writes.inserted,
                    "updated": self.writes.updated,
                    "unchanged": self.writes.unchanged,
                    "retired": self.writes.retired,
                    "cms_edit_conflicts": sorted(self.writes.cms_edit_conflicts),
                }
                if self.writes is not None
                else None
            ),
        }


def _gate_passed(hint: Hint, gate: str) -> bool:
    verdict = hint.gate_report.get(gate)
    return isinstance(verdict, dict) and verdict.get("passed") is True


def _leakage_verdict(hint: Hint, key: str = "verdict") -> str:
    verdict = hint.gate_report.get(GATE_ANSWER_LEAKAGE)
    if isinstance(verdict, dict):
        detail = verdict.get("detail")
        if isinstance(detail, dict):
            value = detail.get(key)
            if isinstance(value, str):
                return value
    return "unknown"


def summarize(
    results: Sequence[PathHints], *, load: PathLoadReport, applied: bool
) -> GenerationReport:
    """경로별 결과 → 배치 리포트(레벨별 생성·통과·게이트별 거부·누출 판정 분포)."""
    generated: Counter[int] = Counter()
    verified: Counter[int] = Counter()
    skipped: Counter[str] = Counter()
    rejected: Counter[str] = Counter()
    leakage: Counter[str] = Counter()
    value: Counter[str] = Counter()
    for result in results:
        for _order, _level, reason in result.skipped:
            skipped[reason] += 1
        for hint in result.hints:
            generated[hint.level] += 1
            if hint.verified:
                verified[hint.level] += 1
            for gate in GATE_NAMES:
                if not _gate_passed(hint, gate):
                    rejected[gate] += 1
            leakage[_leakage_verdict(hint)] += 1
            value[_leakage_verdict(hint, "value_verdict")] += 1
    return GenerationReport(
        applied=applied,
        load=load,
        generated_by_level={level: generated[level] for level in HINT_LEVELS},
        verified_by_level={level: verified[level] for level in HINT_LEVELS},
        skipped_by_reason=dict(skipped),
        rejected_by_gate={gate: rejected[gate] for gate in GATE_NAMES},
        leakage_verdicts=dict(leakage),
        value_verdicts=dict(value),
    )


async def run(
    *,
    apply: bool,
    value_exposure: AnswerValueExposure | None,
    overwrite_cms_edits: bool = False,
) -> GenerationReport:
    """DB glue — 원천 로드 → 순수 생성 → (apply면) 한 트랜잭션 적재."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        inputs, load = await load_path_inputs(session)
        results = [build_path_hints(path, value_exposure=value_exposure) for path in inputs]
        report = summarize(results, load=load, applied=apply)
        if apply and inputs:
            report.writes = await persist_generation(
                session,
                [hint for result in results for hint in result.hints],
                processed_path_ids=[path.solution_path_id for path in inputs],
                overwrite_cms_edits=overwrite_cms_edits,
            )
    return report


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 진입점 — 리포트 JSON을 stdout에 한 줄로 내고 종료 코드로 판정한다."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.l4.hint_content.populate",
        description="검증된 풀이 단계에서 graded 힌트 L1~L3를 오프라인 생성·게이트 평가한다.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="hints 테이블에 실제로 적재한다(기본은 dry-run — 적재 없이 리포트만).",
    )
    add_overwrite_argument(parser)
    args = parser.parse_args(list(argv) if argv is not None else None)
    report = asyncio.run(
        run(
            apply=bool(args.apply),
            value_exposure=default_answer_value_exposure(),
            overwrite_cms_edits=bool(args.overwrite_cms_edits),
        )
    )
    print(json.dumps(report.to_json(), ensure_ascii=False, sort_keys=True))
    if report.load.paths_seen == 0:
        print(
            "원천 경로 0건 — 단계가 실체화된 풀이 경로가 없다"
            "(whs.path_promotion --apply 선행 필요). 0건 생성을 성공으로 보고하지 않는다.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI 진입
    raise SystemExit(main())
