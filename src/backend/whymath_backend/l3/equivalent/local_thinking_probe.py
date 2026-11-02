"""로컬 좌석 사고 모드 켬/끔 실측 비교 — 같은 스펙 표본으로 수락률·지연·출력 토큰 (EOS-203).

왜 필요한가
----------
EOS-197 A6 회차에서 로컬 좌석(`qwen3:30b-a3b`)은 45회 시도 중 3건만 수락됐다. 사고 모드가 출력
4,400~8,100토큰을 내 컨텍스트 8,192와 요청 타임아웃을 넘긴 것이 원인으로 보였다. 생성기에 사고 모드
지시(`thinking=False` → `/no_think`)를 두었지만(`llm_generator`), **기본값은 실측 없이 바꾸지
않는다** (acceptance ②). 이 도구가 그 실측을 한다 — 같은 스펙 계획 파일을 두 모드로 **번갈아**
돌려(시간에 따른 모델·기기 상태 변화가 한 모드에만 실리지 않게) 수용 게이트 판정까지 낸다.

같은 표본으로 EOS-205의 수정 후 수치(동어반복 거부 건수 = `TautologicalConditionError`)도 함께
나온다.

측정 도구 규칙(CLAUDE.md "측정·수집 도구를 성공 경로만 보고 설계 금지")
----------------------------------------------------------------
① **실패해도 증거가 남는다** — 시도 1건마다 JSONL 한 줄을 즉시 쓰고 flush한다.
② **실패 원인이 남는다** — 생성 실패는 GenerationLog `error_detail`(타입명 + 안전 요약)을, 탐침
   자신의 예외는 타입명을 행에 싣는다.
③ **이번 실행 것인가** — 모든 행에 `run_id`·시각을 싣고, 요약은 이번 `run_id` 행만 센다.
④ **변별력** — 시작 전에 각 모드의 라우팅 결정과 붙을 지시어를 출력하고, `off` 모드에 지시어가 붙지
   않는 결정(비하이브리드 모델·클라우드)이면 **측정을 거부**한다(그 상태로 재면 두 모드가 같은
   호출이다).

실행은 사람 PC(Ollama)에서 한다. 타임아웃은 `WHYMATH_OLLAMA_REQUEST_TIMEOUT_S`가 정하며, 요약에 실제
적용값을 남긴다.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import uuid
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
from whymath_backend.l3.equivalent.orchestrator import run_equivalent_generation
from whymath_backend.l3.router import thinking_soft_switch
from whymath_backend.schema.provenance import GenerationLog

__all__ = ["MODES", "PlanEntry", "load_plan", "main", "run_probe", "summarize"]

# 비교 모드 — 이름 → 생성기 `thinking` 값. `default`는 미지정(종전 동작) 대조군이다.
MODES: dict[str, bool | None] = {"default": None, "off": False, "on": True}

_FAILURE_PREFIX_SPLIT = ": "


@dataclass(frozen=True, slots=True)
class PlanEntry:
    spec_id: str
    spec: EquivalenceSpec
    topic_hint: str


def load_plan(path: Path) -> list[PlanEntry]:
    """스펙 계획 JSONL(`{spec_id, standard_code, difficulty, topic_hint}`) → 항목 목록.

    저작 CLI(`harness/problem_corpus_accumulate --spec-file`)와 같은 파일 형식이다. 이 모듈은 L3라
    하네스를 import하지 않으므로 같은 규칙(성취기준 1개·오개념 비움·난이도 실수)으로 직접 읽는다.
    """
    entries: list[PlanEntry] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        raw = json.loads(line)
        if not isinstance(raw, dict):
            raise ValueError(f"{path}:{line_no} — 객체가 아니다")
        entries.append(
            PlanEntry(
                spec_id=str(raw["spec_id"]),
                spec=EquivalenceSpec(
                    achievement_standard_codes=frozenset({str(raw["standard_code"])}),
                    target_misconception_ids=frozenset(),
                    difficulty_overall=float(raw.get("difficulty", 2.5)),
                    answer_format=None,
                ),
                topic_hint=str(raw["topic_hint"]),
            )
        )
    if not entries:
        raise ValueError(f"{path} — 스펙 0건(빈 계획으로 재면 공허한 측정이다)")
    return entries


GeneratorFactory = Callable[[str, bool | None, Callable[[GenerationLog], None]], object]


def _failure_kind(detail: str | None) -> str | None:
    """`후보 조립 실패: TautologicalConditionError` → `TautologicalConditionError` 꼴의 사유 축."""
    if not detail:
        return None
    head, _, tail = detail.partition(_FAILURE_PREFIX_SPLIT)
    return tail.split("(")[0].strip() or head


def run_probe(
    plan: Sequence[PlanEntry],
    *,
    modes: Sequence[str],
    per_spec: int,
    factory: GeneratorFactory,
    out: TextIO,
    run_id: str,
    clock: Callable[[], float] = time.monotonic,
) -> list[dict[str, object]]:
    """스펙마다 `per_spec`회 × 모드를 번갈아 돌린다. 행은 쓸 때마다 flush한다(규칙 ①)."""
    rows: list[dict[str, object]] = []
    for entry in plan:
        generators: dict[str, object] = {}
        logs: dict[str, list[GenerationLog]] = {}
        for mode in modes:
            logs[mode] = []
            generators[mode] = factory(entry.topic_hint, MODES[mode], logs[mode].append)
        for attempt in range(per_spec):
            for mode in modes:
                before = len(logs[mode])
                started = clock()
                row: dict[str, object] = {
                    "run_id": run_id,
                    "at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "spec_id": entry.spec_id,
                    "mode": mode,
                    "attempt": attempt,
                }
                try:
                    outcome = run_equivalent_generation(
                        entry.spec, generators[mode]  # type: ignore[arg-type]
                    )
                    row["status"] = outcome.status
                except Exception as exc:  # noqa: BLE001 — 한 시도의 장애가 측정 전체를 죽이지 않게
                    row["status"] = "probe_error"
                    row["probe_error"] = type(exc).__name__
                row["wall_s"] = round(clock() - started, 2)
                new_logs = logs[mode][before:]
                last = new_logs[-1] if new_logs else None
                row["calls"] = len(new_logs)
                row["output_tokens"] = last.output_tokens if last else None
                row["latency_ms"] = last.latency_ms if last else None
                row["error_detail"] = last.error_detail if last else None
                row["failure_kind"] = _failure_kind(last.error_detail if last else None)
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                out.flush()
                rows.append(row)
    return rows


def _median(values: Sequence[float]) -> float | None:
    return float(statistics.median(values)) if values else None


def summarize(rows: Sequence[Mapping[str, object]], run_id: str) -> dict[str, object]:
    """이번 `run_id` 행만 모드별로 센다(규칙 ③). 수락 = 수용 게이트 통과(`accepted`)."""
    by_mode: dict[str, list[Mapping[str, object]]] = {}
    for row in rows:
        if row.get("run_id") == run_id:
            by_mode.setdefault(str(row["mode"]), []).append(row)
    modes: dict[str, dict[str, object]] = {}
    for mode, items in by_mode.items():
        statuses = Counter(str(r["status"]) for r in items)
        accepted = statuses.get("accepted", 0) + statuses.get("accepted_stored", 0)
        tokens = [float(t) for r in items if isinstance((t := r.get("output_tokens")), int)]
        latency = [float(v) for r in items if isinstance((v := r.get("latency_ms")), int)]
        modes[mode] = {
            "attempts": len(items),
            "accepted": accepted,
            "acceptance_rate": round(accepted / len(items), 4) if items else None,
            "statuses": dict(sorted(statuses.items())),
            "failure_kinds": dict(
                sorted(Counter(str(r["failure_kind"]) for r in items if r["failure_kind"]).items())
            ),
            "median_output_tokens": _median(tokens),
            "max_output_tokens": max(tokens) if tokens else None,
            "median_latency_ms": _median(latency),
        }
    return {"run_id": run_id, "modes": modes}


def _live_factory(avoid_recent: int) -> GeneratorFactory:
    """사람 PC용 실물 생성기 — 로컬 Ollama·라우터 결정(비동기 저작 = QUALITY)·저작 패밀리 기본."""

    def build(
        topic_hint: str, thinking: bool | None, sink: Callable[[GenerationLog], None]
    ) -> object:
        from whymath_backend.l3.equivalent.llm_generator import LLMEquivalentProblemGenerator
        from whymath_backend.l3.providers.ollama import OllamaProvider

        return LLMEquivalentProblemGenerator(
            OllamaProvider(),
            topic_hint=topic_hint,
            routing_sync=False,  # 저작 CLI `--authoring-tier quality`와 같은 신호(규칙 2 → QUALITY)
            avoid_recent=avoid_recent,
            generation_log_sink=sink,
            thinking=thinking,
        )

    return build


def preflight(
    plan: Sequence[PlanEntry], modes: Sequence[str], factory: GeneratorFactory
) -> list[str]:
    """각 모드의 라우팅 결정·붙을 지시어를 보고, 변별력이 없으면 거부 사유를 돌려준다(규칙 ④)."""
    problems: list[str] = []
    entry = plan[0]
    for mode in modes:
        generator = factory(entry.topic_hint, MODES[mode], lambda _log: None)
        decide = getattr(generator, "_decide_routing", None)
        if decide is None:
            problems.append(f"{mode}: 라우팅 결정을 물을 수 없는 생성기")
            continue
        decision = decide(entry.spec)
        switch = (
            None
            if MODES[mode] is None
            else thinking_soft_switch(decision, enabled=bool(MODES[mode]))
        )
        print(
            f"PREFLIGHT mode={mode} cost_tier={decision.cost_tier} "
            f"local_model={decision.local_model} switch={switch}"
        )
        if MODES[mode] is not None and switch is None:
            problems.append(f"{mode}: 이 결정에는 사고 모드 지시어가 붙지 않는다(비대상 모델)")
    return problems


def main(argv: Sequence[str] | None = None, *, factory: GeneratorFactory | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--plan", required=True, type=Path, help="스펙 계획 JSONL")
    parser.add_argument("--per-spec", type=int, default=3, help="스펙·모드당 시도 수(기본 3)")
    parser.add_argument("--modes", default="default,off", help="쉼표 구분(default·off·on)")
    parser.add_argument("--avoid-recent", type=int, default=10, help="저작 CLI [F]와 같은 10")
    parser.add_argument("--out", required=True, type=Path, help="시도별 JSONL(이어 쓴다)")
    parser.add_argument("--summary", required=True, type=Path, help="요약 JSON")
    args = parser.parse_args(argv)
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    unknown = [m for m in modes if m not in MODES]
    if unknown or len(modes) < 2 or args.per_spec < 1:
        print(
            f"PROBE_REFUSED=True — modes={modes}(2개 이상·{sorted(MODES)}) per_spec={args.per_spec}"
        )
        return 2
    plan = load_plan(args.plan)
    build = factory or _live_factory(args.avoid_recent)
    problems = preflight(plan, modes, build)
    if problems:
        print("PROBE_REFUSED=True — " + " · ".join(problems))
        return 2
    from whymath_backend.config import get_settings

    timeout_s = get_settings().ollama_request_timeout_s
    run_id = uuid.uuid4().hex[:12]
    print(
        f"PROBE_START run_id={run_id} specs={len(plan)} per_spec={args.per_spec} "
        f"modes={','.join(modes)} ollama_timeout_s={timeout_s}"
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("a", encoding="utf-8") as handle:
        rows = run_probe(
            plan, modes=modes, per_spec=args.per_spec, factory=build, out=handle, run_id=run_id
        )
    summary = summarize(rows, run_id)
    summary["ollama_request_timeout_s"] = timeout_s
    summary["plan"] = str(args.plan)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    mode_stats = summary["modes"]
    assert isinstance(mode_stats, dict)
    for mode, stats in mode_stats.items():
        print(
            f"PROBE_RESULT mode={mode} accepted={stats['accepted']}/{stats['attempts']} "
            f"rate={stats['acceptance_rate']} median_tokens={stats['median_output_tokens']} "
            f"median_latency_ms={stats['median_latency_ms']}"
        )
    print(f"PROBE_DONE=True ROWS={len(rows)} SUMMARY={args.summary}")
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI 진입점
    sys.exit(main())
